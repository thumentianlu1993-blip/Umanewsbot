"""B091: six reported-token stop methods, only ROOT's fixed PG window may execute.

Only closed SDK/broker boundaries are substituted. Core admission, request reservation,
usage audit, source reads, checkpoint and final writers remain the current real code.
The limit-4 normal control runs before the limit-3 assertion in each test method.
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from uuid import uuid4
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import OperationalError, connection, connections, transaction
from django.db.models import QuerySet
from django.test import RequestFactory

from stable import admin as article_admin
from stable.models import (
    ArticleTranslationStatus, NewsArticle, NotificationLog, OperationLog, RacingRegion,
    TaskExecutionLog, TranslationRequestAttempt, TranslationRetryBudget, TranslationRun,
)
from stable.readonly_translation_e2e_fixture import CommittedFixtureExit, RemainingReadonlyE2EFixture
from stable.services import managed_readonly_steps as ro, managed_readonly_translation as job
from stable.services import translation, translation_recovery as recovery, translation_retry_budget as core
from stable.tasks import translate_article_task
from stable.test_managed_translation_budget_consumer import (
    ManagedTranslationBudgetConsumerFixture, NOW, NORMAL_PAYLOAD, fixture_requirement,
)
from stable.test_translation_failure_recovery_change import article_for_retry


REPORTED_USAGE = {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
FIRST_RED_METHODS = (
    "test_registered_quality_retry_stops_when_reported_total_reaches_limit",
    "test_ordinary_quality_retry_stop_and_failed_closure_repeat",
)


def canonical_digest(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


class ReportedTokenStopTests(RemainingReadonlyE2EFixture, ManagedTranslationBudgetConsumerFixture):
    def setUp(self):
        super().setUp()
        self.readers, self.sdks = [], []
        self.addCleanup(connections.close_all)
        self.scenario_count = 0

    def prepare_scenario(self, *, registered, token_limit, receipt_version=1):
        fixture_requirement(connection.vendor == "postgresql" and not connection.in_atomic_block,
                            "B089 requires ROOT's real PG window, without outer atomic")
        self.clock.return_value = NOW
        body = "There is more than enough time to decide after the sale. " * 6
        if self.scenario_count:
            self.article = article_for_retry(
                source_article_id="b089-" + str(uuid4()), translation_next_retry_at=NOW,
                racing_region=RacingRegion.UNITED_STATES, title_ja="Stable update",
                body_ja_raw=body, body_ja_normalized=body,
            )
        else:
            self.article.body_ja_raw = body
            self.article.body_ja_normalized = body
            self.article.save(update_fields=["body_ja_raw", "body_ja_normalized", "updated_at"])
        self.scenario_count += 1
        self.case_reader_index, self.case_sdk_index = len(self.readers), len(self.sdks)
        self.registered = registered
        self.payload = {**NORMAL_PAYLOAD, "body_zh": "拍卖后仍有十分充足的时间考虑并作出决定。" * 6}
        user = get_user_model().objects.create_user(
            username="b089-" + str(uuid4()), is_staff=True, is_superuser=True,
        )
        request = RequestFactory().post("/admin/stable/newsarticle/")
        request.user, request.session = user, {}
        request._messages = FallbackStorage(request)
        controller = article_admin.NewsArticleAdmin(NewsArticle, AdminSite())
        with patch.object(article_admin, "dispatch_task") as admin_broker:
            controller.retry_failed_translations(request, NewsArticle.objects.filter(pk=self.article.pk))
        fixture_requirement(admin_broker.call_count == 1
                            and admin_broker.call_args.args == (article_admin.translate_article_task, self.article.pk),
                            "real admin retry must capture one exact task dispatch")
        self.article.refresh_from_db()
        fixture_requirement(self.article.translation_status == ArticleTranslationStatus.FAILED
                            and self.article.translation_next_retry_at == NOW,
                            "admin must persist failed/due without fixture rewriting")
        fixture_requirement(OperationLog.objects.filter(
            admin=user, action_type="translation_retry_requested", target_type="article",
            target_id=str(self.article.pk),
        ).count() == 1, "real admin retry OperationLog must exist")
        policy = {"mode": "offline_test", "version": 2,
                  "reported_token_stop_v1": {"total_tokens_limit": token_limit}}
        identity = core.BudgetIdentity(
            "managed_translation_retry", self.article.source_site, self.article.source_article_id,
            recovery.translation_input_sha256(self.article), canonical_digest(policy),
            "offline-synthetic", "offline-only", article_pk_snapshot=self.article.pk,
        )
        decision = core.resolve_budget(identity, mode="offline_test", now=NOW, initial_contract={
            "request_limit": 2, "opened_at": NOW, "deadline_at": NOW + timedelta(minutes=10),
            "policy_snapshot": policy, "baseline_receipt": {"kind": "synthetic_no_prior_consumption"},
        })
        fixture_requirement(decision.allowed, "normal version2 JSON baseline: " + decision.reason)
        self.identity = replace(identity, operation_uuid=decision.operation_uuid)
        self.budget = TranslationRetryBudget.objects.get(pk=decision.budget_pk)
        with recovery._offline_budget_scope(self.identity):
            with patch.object(recovery.translate_article_task, "delay") as broker:
                dispatched = recovery.dispatch_due_translation_retries(now=NOW)
            fixture_requirement(dispatched.dispatched_ids == [self.article.pk] and broker.call_count == 1,
                                "real selector must persist and capture one exact claim")
            args, kwargs = broker.call_args
            self.message = (tuple(args), {**kwargs, "suppress_automation": True})
            fixture_requirement(kwargs.get("preclaimed_retry") is True
                                and type(kwargs.get("claim_run_id")) is int
                                and kwargs.get("claim_started_at") == NOW.isoformat(),
                                "exact real claim message prerequisite")
            self.envelope = ro.ReadEnvelope(self.article.pk, kwargs["claim_run_id"], kwargs["claim_started_at"])
            self.readroot = ro.initialize_read_budget(tool_read_limit=1, now=NOW, receipt_version=receipt_version, baseline={
                "kind": "synthetic_no_prior_tool_reads", "operation_uuid": str(self.identity.operation_uuid),
            }) if registered else None
        if registered:
            with self.dependencies(self.normal_script()):
                plan = job.register_offline_readonly_translation_job(self.envelope)
            self.message = (self.message[0], {**self.message[1], "readonly_job_uuid": plan["payload"]["plan_uuid"]})
            run = TranslationRun.objects.get(pk=self.envelope.run_id)
            fixture_requirement(job.decode_control(run.raw_response)[job.PLAN_KEY] == plan
                                and run.raw_response[recovery.CLAIM_KEY]["phase"] == "claimed",
                                "real registration/codec must not consume claim")
        fixture_requirement(self.budget.request_attempts.count() == 0 and self.budget.requests_reserved == 0,
                            "synthetic baseline has no earlier requests")

    def normal_script(self):
        return [{"content": json.dumps(self.payload, ensure_ascii=False), "usage": REPORTED_USAGE}]

    @contextmanager
    def dependencies(self, script, *, sdk=None):
        sdk = sdk if sdk is not None else self.fake(script)
        if sdk not in self.sdks:
            self.sdks.append(sdk)
        reader = ro._ClosedSourceExcerptReader() if self.registered else None
        if reader is not None:
            self.readers.append(reader)
        with ExitStack() as stack:
            stack.enter_context(recovery._offline_budget_scope(self.identity))
            if reader is not None:
                stack.enter_context(ro.readonly_scope(self.readroot.pk))
            stack.enter_context(translation._offline_sdk_dependency(sdk))
            if reader is not None:
                stack.enter_context(ro.reader_dependency(reader))
            yield sdk
        fixture_requirement(sdk._closed and (reader is None or reader.closed), "closed dependencies released")
        self.constructor.assert_not_called()

    def run_quality_scenario(self, *, registered, token_limit, max_attempts=2, expect_provider_failure=False,
                             expect_audit_failure=False, receipt_version=1):
        self.prepare_scenario(registered=registered, token_limit=token_limit, receipt_version=receipt_version)
        script = [{"content": json.dumps({**self.payload, "body_zh": ""}, ensure_ascii=False),
                   "usage": REPORTED_USAGE, "wait_for_receipt": True}, *self.normal_script()]
        sdk = self.fake(script)
        self.sdks.append(sdk)
        def consume(_):
            with self.dependencies(script, sdk=sdk):
                try:
                    return translate_article_task.run(*self.message[0], **self.message[1])
                except translation.TranslationResponseError:
                    if not expect_provider_failure:
                        raise
                    return {"provider_failure": True}
                except OperationalError as exc:
                    if not expect_audit_failure:
                        raise
                    return {"raised_audit_error": str(exc)}
        with self.settings(TRANSLATION_MAX_ATTEMPTS=max_attempts):
            with self.running_workers(consume, releases=(sdk.choices_release,)) as state:
                fixture_requirement(sdk.choices_ready.wait(8),
                                    "first real usage must precede closed choices gate: " + repr(state["errors"]))
                attempt = self.budget.request_attempts.get(provider_attempt_index=1)
                fixture_requirement(attempt.state == "usage_reported" and attempt.usage_report == REPORTED_USAGE,
                                    "first response usage must be committed by real writer")
                self.no_business_locks(state["pids"][0])
                receipt = {"kind": "synthetic_offline_usage_v1", "budget_uuid": str(self.budget.budget_uuid),
                           "attempt_pk": attempt.pk, "usage_sha256": canonical_digest(REPORTED_USAGE)}
                audited = core.record_usage(budget_pk=self.budget.pk, attempt_pk=attempt.pk,
                                            mode="offline_test", usage_report=REPORTED_USAGE, receipt=receipt)
                fixture_requirement(audited.allowed, "real synthetic reconciliation prerequisite: " + audited.reason)
                self.receipt_gate_snapshot = self.stop_snapshot()
                sdk.choices_release.set()
            self.workers_clean(state)
        self.constructor.assert_not_called()
        fixture_requirement(sdk._closed, "worker dependency must close")
        fixture_requirement(recovery._current_offline_budget_binding() is None
                            and translation._offline_sdk_binding.get() is None, "main scope remains empty")
        creates = [event for event in sdk.trace if event["event"] == "create"]
        fixture_requirement(creates and all(not event["in_atomic_block"] for event in creates),
                            "closed create observed real committed reservation outside transaction")
        self.budget.refresh_from_db()
        self.article.refresh_from_db()
        result = state["results"][0]
        print("B089_ACTUAL_QUALITY", "registered", registered, "limit", token_limit,
              "create_count", len(creates), "slot_count", self.budget.requests_reserved,
              "task_result", result, flush=True)
        return result, creates

    def assert_limit4_control(self, *, registered):
        result, creates = self.run_quality_scenario(registered=registered, token_limit=4)
        fixture_requirement(result.get("translated") is True, "limit4 normal control must reach real final Article")
        fixture_requirement(len(creates) == 2 and self.budget.requests_reserved == 2,
                            "limit4 must allow real second quality request; otherwise prerequisite ERROR")
        fixture_requirement([event["requests_reserved"] for event in creates] == [1, 2],
                            "each control create sees its committed real request slot")
        fixture_requirement(self.article.body_zh == self.payload["body_zh"]
                            and self.article.translation_status == ArticleTranslationStatus.TRANSLATED,
                            "normal control must persist actual translated text/status")
        run = TranslationRun.objects.get(pk=self.envelope.run_id)
        fixture_requirement(run.status == "success" and recovery.RESULT_KEY in run.raw_response,
                            "control must commit real checkpoint and successful Run")
        self.assertEqual([a.usage_report for a in self.budget.request_attempts.order_by("seq")],
                         [REPORTED_USAGE, REPORTED_USAGE])
        self.assertEqual(sum(a.usage_report["total_tokens"] for a in self.budget.request_attempts.all()), 6)

    def assert_stop(self, *, registered):
        result, creates = self.run_quality_scenario(registered=registered, token_limit=3)
        # On the unchanged candidate this is the target business FAIL, not a missing-interface ERROR.
        self.assertEqual(len(creates), 1, "reported total=3 reached limit=3, but the real second create occurred")
        self.assertEqual(self.budget.requests_reserved, 1)
        self.assertEqual(self.budget.request_attempts.count(), 1)
        self.assertEqual(result.get("reason"), "reported_token_stop_reached")
        self.assertFalse(result.get("translated"))
        self.assertEqual(self.article.body_zh, "")
        self.assertNotEqual(self.article.translation_status, ArticleTranslationStatus.TRANSLATED)
        attempt = self.budget.request_attempts.get()
        self.assertEqual(attempt.usage_report, REPORTED_USAGE)
        self.assertEqual((attempt.state, attempt.usage_validation, attempt.reconciliation_state),
                         ("reconciled", "known", "offline_reconciled"))
        self.assertEqual(self.budget.policy_sha256, canonical_digest(self.budget.policy_snapshot))
        self.assertEqual(self.budget.deadline_at, NOW + timedelta(minutes=10))
        self.assertTrue(TaskExecutionLog.objects.filter(
            task_name="translate_article", detail__contains="reported_token_stop_reached",
            detail__icontains="article=" + str(self.article.pk),
        ).exists())
        self.assertTrue(OperationLog.objects.filter(
            action_type="translation_budget_stopped", target_type="article", target_id=str(self.article.pk),
            detail__contains="reported_token_stop_reached",
        ).exists())
        self.assertEqual(NotificationLog.objects.count(), 0)
        if registered:
            self.readroot.refresh_from_db()
            step = self.readroot.steps.get()
            self.assertEqual((self.readroot.tool_reads_reserved, step.state), (1, "completed"))
            self.assertEqual(sum(e["event"] == "business_read" for reader in self.readers[
                self.case_reader_index:] for e in reader.trace), 1)

    def test_publication_v2_retains_reported_token_stop_and_free_checkpoint(self):
        control, creates = self.run_quality_scenario(registered=True, token_limit=4, receipt_version=2)
        self.assertTrue(control.get("translated"), control)
        self.assertEqual(len(creates), 2)
        self.assertIn("publication", self.readroot.steps.get().result)
        stopped, creates = self.run_quality_scenario(registered=True, token_limit=3, receipt_version=2)
        self.assertEqual(stopped.get("reason"), core.REPORTED_TOKEN_STOP)
        self.assertEqual(len(creates), 1)
        before = self.stop_snapshot()
        repeated, sdk = self.replay()
        self.assertEqual(repeated.get("reason"), "model_start_unknown")
        self.assertEqual(sdk.trace, [])
        self.assertEqual(self.stop_snapshot(), before)
        self.prepare_scenario(registered=True, token_limit=3, receipt_version=2)
        with self.storage_fault("final_article"):
            with self.assertRaises(OperationalError):self.replay()
        self.assertEqual(self.actual_run().raw_response[job.PROGRESS_KEY]["state"], "checkpoint_saved")
        step = self.readroot.steps.get()
        self.reconcile_report(self.budget.request_attempts.get())
        self.assertEqual(core.resolve_budget(self.identity, mode="offline_test", now=NOW).reason, core.REPORTED_TOKEN_STOP)
        checkpoint = deepcopy(self.actual_run().raw_response[recovery.RESULT_KEY])
        ledger = deepcopy(list(self.budget.request_attempts.values()))
        finished, sdk = self.replay()
        self.assertTrue(finished.get("translated"), finished)
        self.assertEqual(sdk.trace, [])
        self.assertEqual(self.actual_run().raw_response[recovery.RESULT_KEY], checkpoint)
        self.assertEqual(list(self.budget.request_attempts.values()), ledger)
        self.assertEqual(finished["final_receipt"]["payload"]["read_result_sha256"], step.result_sha256)
        self.assertEqual(sum(e["event"] == "business_read" for r in self.readers[self.case_reader_index:] for e in r.trace), 1)

    def test_registered_quality_retry_stops_when_reported_total_reaches_limit(self):
        self.assert_limit4_control(registered=True)
        self.assert_stop(registered=True)
        before = self.stop_snapshot()
        repeated, sdk = self.replay()
        self.assertEqual(repeated.get("reason"), "model_start_unknown")
        self.assertEqual(sdk.trace, [])
        self.assertEqual(self.stop_snapshot(), before)
        self.assertEqual(self.actual_run().raw_response[job.PROGRESS_KEY]["state"], "model_started")
        self.assert_task_reason("model_start_unknown")
        # All states come from real CAS/reservation/writer/refusal, never a fabricated terminal.
        for fault in ("before_create_exit", "missing_usage", "unreconciled", "reconciled_exit", "timeout", "quality_failed"):
            with self.subTest(fault=fault):
                self.prepare_scenario(registered=True, token_limit=3)
                script = self.normal_script()
                if fault == "missing_usage":script = [{**script[0], "usage": None}]
                if fault == "timeout":script = [{"error": "timeout"}]
                if fault == "quality_failed":script = [{**script[0], "content": json.dumps({**self.payload, "body_zh": ""})}]
                with ExitStack() as stack:
                    if fault == "before_create_exit":
                        def create(client, **kwargs):raise CommittedFixtureExit("real CAS+slot before wire")
                        stack.enter_context(patch.object(translation._ClosedOfflineSDKClient, "create", new=create))
                    if fault in {"unreconciled", "reconciled_exit"}:
                        def choices(response):raise CommittedFixtureExit("real usage committed before choices")
                        stack.enter_context(patch.object(translation._ClosedOfflineSDKResponse, "choices", new=property(choices)))
                    if fault in {"before_create_exit", "unreconciled", "reconciled_exit"}:
                        with self.assertRaises(CommittedFixtureExit):self.replay(script)
                    else:
                        with self.settings(TRANSLATION_MAX_ATTEMPTS=1):result, _ = self.replay(script)
                        self.assertFalse(result.get("translated"))
                if fault == "reconciled_exit":self.reconcile_report(self.budget.request_attempts.get())
                before = self.stop_snapshot()
                repeated, sdk = self.replay()
                self.assertIn(repeated.get("reason"), {"model_start_unknown", "model_refused", "usage_unknown"})
                self.assertEqual(sdk.trace, [])
                self.assertEqual(self.stop_snapshot(), before)
                self.assertEqual(self.budget.request_attempts.count(), 1)
                self.assertNotIn(recovery.RESULT_KEY, self.actual_run().raw_response)
                # Existing blocked/fresh invocation reason is never replaced by the sum.
                if fault == "quality_failed":self.assertEqual(repeated.get("reason"), "model_refused")
        for fence in ("grant", "deadline", "source", "claim_uuid"):
            with self.subTest(fence=fence):
                self.assert_stop(registered=True)
                self.mutate_fence(fence)
                before = self.stop_snapshot()
                result, sdk = self.replay()
                self.assertNotEqual(result.get("reason"), core.REPORTED_TOKEN_STOP)
                self.assertFalse(result.get("translated"))
                self.assertEqual(sdk.trace, [])
                self.assertEqual(self.stop_snapshot(), before)

    def test_ordinary_quality_retry_stop_and_failed_closure_repeat(self):
        self.assert_limit4_control(registered=False)
        self.assert_stop(registered=False)
        result, creates = self.run_quality_scenario(registered=False, token_limit=3, max_attempts=1)
        self.assertEqual((result.get("reason"), len(creates)), (core.REPORTED_TOKEN_STOP, 1))
        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_retry_count, 1)
        self.assertIsNone(self.article.translation_next_retry_at)
        run = self.actual_run()
        self.assertEqual((run.status, run.raw_response[recovery.CLAIM_KEY]["phase"]), ("failed", "failed"))
        self.assertEqual(run.raw_response[recovery.CLAIM_KEY]["budget_blocked_reason"], core.REPORTED_TOKEN_STOP)
        self.assert_task_reason(core.REPORTED_TOKEN_STOP)
        self.assert_stop_log()
        with recovery._offline_budget_scope(self.identity), patch.object(recovery.translate_article_task, "delay") as broker:
            dispatched = recovery.dispatch_due_translation_retries(now=NOW)
        self.assertEqual(dispatched.dispatched_ids, [])
        broker.assert_not_called()
        before = self.stop_snapshot()
        logs = OperationLog.objects.filter(action_type="translation_budget_stopped", target_id=str(self.article.pk)).count()
        result, sdk = self.replay()
        self.assertEqual(result.get("reason"), core.REPORTED_TOKEN_STOP)
        self.assertEqual(sdk.trace, [])
        self.assertEqual(self.stop_snapshot(), before)
        self.assertEqual(OperationLog.objects.filter(action_type="translation_budget_stopped", target_id=str(self.article.pk)).count(), logs + 1)
        self.assert_stop_log()
        before = self.stop_snapshot()
        logs = OperationLog.objects.filter(action_type="translation_budget_stopped", target_id=str(self.article.pk)).count()
        with self.settings(TRANSLATION_MODEL="changed-model"):
            refused, sdk = self.replay()
        self.assertEqual(refused.get("reason"), "budget_version_changed")
        self.assertEqual(sdk.trace, [])
        self.assertEqual(self.stop_snapshot(), before)
        self.assertEqual(OperationLog.objects.filter(action_type="translation_budget_stopped", target_id=str(self.article.pk)).count(), logs)
        restored, sdk = self.replay()
        self.assertEqual(restored.get("reason"), core.REPORTED_TOKEN_STOP)
        self.assertEqual(sdk.trace, [])
        self.assertEqual(self.stop_snapshot(), before)
        self.assertEqual(OperationLog.objects.filter(action_type="translation_budget_stopped", target_id=str(self.article.pk)).count(), logs + 1)
        with self.dependencies(self.normal_script()) as sdk:
            unbound_message = translate_article_task.run(self.article.pk, suppress_automation=True)
        self.assertEqual(unbound_message.get("reason"), "bound_claim_identity_missing")
        self.assertEqual(sdk.trace, [])
        # Fail only the finite persistent stop-log save, never mock admission or audit success.
        saved = OperationLog.save
        hits = []
        def fail_stop_log(log, *args, **kwargs):
            if log.action_type == "translation_budget_stopped":
                hits.append(log.target_id)
                raise OperationalError("B091 stop diagnostic save fault")
            return saved(log, *args, **kwargs)
        with patch.object(OperationLog, "save", new=fail_stop_log):
            result, creates = self.run_quality_scenario(registered=False, token_limit=3, max_attempts=1,
                                                        expect_audit_failure=True)
        self.assertEqual(result, {"raised_audit_error": "B091 stop diagnostic save fault"})
        self.assertEqual(hits, [str(self.article.pk)])
        self.assertEqual(len(creates), 1)
        self.assertEqual(self.stop_snapshot(), self.receipt_gate_snapshot)
        self.assertEqual(self.actual_run().status, "started")
        self.assertEqual(self.actual_run().raw_response[recovery.CLAIM_KEY]["phase"], "executing")
        self.assertNotIn("budget_blocked_reason", self.actual_run().raw_response[recovery.CLAIM_KEY])
        self.assertFalse(OperationLog.objects.filter(action_type="translation_budget_stopped", target_id=str(self.article.pk)).exists())
        failed_log = TaskExecutionLog.objects.filter(task_name="translate_article",
            detail__contains="B091 stop diagnostic save fault").first()
        self.assertIsNotNone(failed_log)
        self.assertEqual(failed_log.status, "failed")
        # Corrupting an existing negative fixture cannot create new stop/claim evidence.
        for fault in ("missing_stop", "phase", "status", "raw", "usage", "claim_uuid", "source", "policy", "deadline", "new_run", "unknown", "unreconciled"):
            with self.subTest(fault=fault):
                self.run_quality_scenario(registered=False, token_limit=3, max_attempts=1)
                run = self.actual_run(); raw = deepcopy(run.raw_response)
                if fault == "missing_stop":raw[recovery.CLAIM_KEY].pop("budget_blocked_reason")
                elif fault == "phase":raw[recovery.CLAIM_KEY]["phase"] = "executing"
                elif fault == "status":TranslationRun.objects.filter(pk=run.pk).update(status="started")
                elif fault == "raw":raw = {}
                elif fault == "usage":raw["usage"] = {"total_tokens": 3}
                elif fault == "claim_uuid":raw[recovery.CLAIM_KEY]["claim_execution_uuid"] = str(uuid4())
                elif fault == "source":NewsArticle.objects.filter(pk=self.article.pk).update(body_ja_normalized="changed")
                elif fault == "policy":self.identity = replace(self.identity, policy_sha256="d" * 64)
                elif fault == "deadline":self.clock.return_value = self.budget.deadline_at
                elif fault in {"unknown", "unreconciled"}:
                    attempt = self.budget.request_attempts.get()
                    QuerySet.update(TranslationRequestAttempt.objects.filter(pk=attempt.pk),
                        state="unknown" if fault == "unknown" else "usage_reported",
                        usage_validation="unknown" if fault == "unknown" else "known", reconciliation_state="unreconciled")
                else:TranslationRun.objects.create(article=self.article, status="started")
                if fault in {"missing_stop", "phase", "raw", "usage", "claim_uuid"}:
                    TranslationRun.objects.filter(pk=run.pk).update(raw_response=raw)
                before = self.stop_snapshot()
                result, sdk = self.replay()
                self.assertNotEqual(result.get("reason"), core.REPORTED_TOKEN_STOP)
                self.assertEqual(sdk.trace, [])
                self.assertEqual(self.stop_snapshot(), before)
        # max1 below threshold may also have no due; that alone is never stop evidence.
        result, creates = self.run_quality_scenario(registered=False, token_limit=4, max_attempts=1,
                                                    expect_provider_failure=True)
        self.assertTrue(result.get("provider_failure"))
        self.assertEqual(len(creates), 1)
        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_retry_count, 1)
        self.assertIsNone(self.article.translation_next_retry_at)
        self.assertEqual(self.actual_run().raw_response[recovery.CLAIM_KEY]["budget_blocked_reason"], "")
        self.assertFalse(OperationLog.objects.filter(action_type="translation_budget_stopped", target_id=str(self.article.pk)).exists())
        repeated, sdk = self.replay()
        self.assertEqual(repeated.get("reason"), "claim_already_consumed")
        self.assertEqual(sdk.trace, [])

    def actual_run(self):
        return TranslationRun.objects.get(pk=self.envelope.run_id)

    def replay(self, script=None):
        script = self.normal_script() if script is None else script
        with self.dependencies(script) as sdk:
            result = translate_article_task.run(*self.message[0], **self.message[1])
        return result, sdk

    def reconcile_report(self, attempt):
        receipt = {"kind": "synthetic_offline_usage_v1", "budget_uuid": str(self.budget.budget_uuid),
                   "attempt_pk": attempt.pk, "usage_sha256": canonical_digest(attempt.usage_report)}
        result = core.record_usage(budget_pk=self.budget.pk, attempt_pk=attempt.pk,
                                   mode="offline_test", usage_report=attempt.usage_report, receipt=receipt)
        self.assertTrue(result.allowed, result)
        return result

    def stop_snapshot(self):
        return deepcopy({
            "budget": TranslationRetryBudget.objects.filter(pk=self.budget.pk).values().get(),
            "attempts": list(self.budget.request_attempts.order_by("seq").values()),
            "article": NewsArticle.objects.filter(pk=self.article.pk).values().get(),
            "run": TranslationRun.objects.filter(pk=self.envelope.run_id).values().get(),
            "read": None if self.readroot is None else type(self.readroot).objects.filter(pk=self.readroot.pk).values().get(),
            "steps": [] if self.readroot is None else list(self.readroot.steps.order_by("pk").values()),
        })

    def assert_task_reason(self, reason):
        self.assertTrue(TaskExecutionLog.objects.filter(task_name="translate_article",
            detail__contains="reason=" + reason, detail__icontains="article=" + str(self.article.pk)).exists())

    def assert_stop_log(self):
        log = OperationLog.objects.filter(action_type="translation_budget_stopped", target_id=str(self.article.pk)).first()
        self.assertIsNotNone(log)
        self.assertIsNone(log.admin_id)
        detail = json.loads(log.detail)
        self.assertEqual(detail, {"reason": core.REPORTED_TOKEN_STOP,
            "operation_uuid": str(self.budget.operation_uuid), "budget_uuid": str(self.budget.budget_uuid),
            "budget_pk": self.budget.pk, "run_id": self.envelope.run_id,
            "claim_execution_uuid": self.actual_run().raw_response[recovery.CLAIM_KEY]["claim_execution_uuid"],
            "claimed_at": self.envelope.claimed_at, "reported_total": 3, "limit": 3})

    def test_policy_validation_and_existing_contract_compatibility(self):
        policy = {"mode": "offline_test", "version": 2,
                  "reported_token_stop_v1": {"total_tokens_limit": 3}}
        invalid = []
        for value in (True, 3.0, 0, None, -1, 2**63):
            invalid.append({**policy, "reported_token_stop_v1": {"total_tokens_limit": value}})
        invalid += [{**policy, "reported_token_stop_v1": {}},
                    {**policy, "reported_token_stop_v1": None}, {**policy, "reported_token_stop_v1": []},
                    {**policy, "reported_token_stop_v1": {"total_tokens_limit": 3, "extra": 1}},
                    {**policy, "version": True}, {**policy, "version": 1}, {**policy, "version": 99},
                    {**policy, "extra": 1}, {k:v for k,v in policy.items() if k != "version"},
                    {k:v for k,v in policy.items() if k != "reported_token_stop_v1"},
                    {"mode": "offline_test", "version": 2, "reported_token_stop_v99": {"total_tokens_limit": 3}}]
        for candidate in invalid:
            with self.subTest(policy=candidate):
                identity = core.BudgetIdentity("managed_translation_retry", self.article.source_site,
                    "b091-policy-" + str(uuid4()), "a" * 64, canonical_digest(candidate), "offline-synthetic", "offline-only")
                result = core.resolve_budget(identity, mode="offline_test", now=NOW, initial_contract={
                    "request_limit": 2, "opened_at": NOW, "deadline_at": NOW + timedelta(minutes=10),
                    "policy_snapshot": candidate, "baseline_receipt": {"kind": "synthetic_no_prior_consumption"}})
                self.assertEqual(result.reason, "invalid_policy_snapshot")
                self.assertFalse(TranslationRetryBudget.objects.filter(source_article_id_snapshot=identity.source_article_id).exists())
        for mode, digest, expected in (("production", canonical_digest(policy), "supported_mode_missing"),
                                       ("offline_test", "b" * 64, "policy_digest_mismatch")):
            identity = core.BudgetIdentity("managed_translation_retry", self.article.source_site,
                "b091-policy-" + str(uuid4()), "a" * 64, digest, "offline-synthetic", "offline-only")
            result = core.resolve_budget(identity, mode=mode, now=NOW, initial_contract={
                "request_limit": 2, "opened_at": NOW, "deadline_at": NOW + timedelta(minutes=10),
                "policy_snapshot": policy, "baseline_receipt": {"kind": "synthetic_no_prior_consumption"}})
            self.assertEqual(result.reason, expected)
        self.prepare_scenario(registered=False, token_limit=3)
        before = self.stop_snapshot()
        changed_message_identity = replace(self.identity, policy_sha256=canonical_digest(
            {**policy, "reported_token_stop_v1": {"total_tokens_limit": 4}}))
        result = core.resolve_budget(changed_message_identity, mode="offline_test", now=NOW)
        self.assertEqual(result.reason, "budget_version_changed")
        self.assertEqual(self.stop_snapshot(), before)
        QuerySet.update(TranslationRetryBudget.objects.filter(pk=self.budget.pk), policy_snapshot=
            {**policy, "reported_token_stop_v1": {"total_tokens_limit": 4}})
        before = self.stop_snapshot()
        self.assertEqual(core.resolve_budget(self.identity, mode="offline_test", now=NOW).reason, "policy_digest_mismatch")
        self.assertEqual(self.stop_snapshot(), before)
        # v1 keeps its original noncanonical fixture digest and real ordinary/checkpoint route.
        self.fresh_input()
        result = self.consume(self.fake([{"content": json.dumps(NORMAL_PAYLOAD), "usage": REPORTED_USAGE}]))
        self.assertTrue(result.get("translated"))
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.policy_snapshot, self.budget.policy_sha256),
                         ({"mode": "offline_test", "version": 1}, "b" * 64))
        self.fresh_input()
        ordinary = translate_article_task.run(self.article.pk, suppress_automation=True)
        self.assertTrue(ordinary.get("translated"))
        NewsArticle.objects.filter(pk=self.article.pk).update(workflow_status="published", automation_status="published",
            translation_status="translated", translation_next_retry_at=None)
        forced = translate_article_task.run(self.article.pk, force=True, suppress_automation=True)
        self.assertTrue(forced.get("translated"))
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 0)
        self.fresh_input()
        claim = recovery.claim_translation_retry(self.article.pk, expected_due_at=NOW, now=NOW)
        article, run, checkpoint, reason = recovery.prepare_translation_claim(self.article.pk, claim.run_id,
            claim.claimed_at, suppress_automation=True)
        self.assertEqual(reason, "")
        result = translation.translate_article(article, managed_run=run)
        checkpoint = recovery.build_translation_checkpoint(article, run, result, suppress_automation=True)
        recovery.save_translation_checkpoint(article.pk, run.pk, claim.claimed_at, checkpoint)
        result = translate_article_task.run(self.article.pk, preclaimed_retry=True, claim_run_id=run.pk,
            claim_started_at=claim.claimed_at, suppress_automation=True)
        self.assertTrue(result.get("translated"))
        run.refresh_from_db()
        self.assertNotIn("claim_execution_uuid", run.raw_response[recovery.CLAIM_KEY])
        self.assertEqual(self.budget.request_attempts.count(), 0)
        self.constructor.assert_not_called()
        # Provider control metadata remains rejected by the existing codec.
        for key in (job.PLAN_KEY, job.PROGRESS_KEY, job.FINAL_KEY, job.PREFIX + "unknown_v99", recovery.CLAIM_KEY):
            with self.assertRaises(recovery.TranslationCheckpointError):job.business_metadata({key: {}})

    def core_reserve(self, *, index=1, claim_uuid=None):
        claim_uuid = claim_uuid or self.actual_run().raw_response[recovery.CLAIM_KEY]["claim_execution_uuid"]
        from uuid import UUID
        return core.reserve_request(self.identity, mode="offline_test", now=NOW,
            claim_execution_uuid=UUID(claim_uuid), claimed_at=NOW,
            provider_attempt_index=index, run_pk_snapshot=self.envelope.run_id)

    def test_unknown_unreconciled_and_invalid_ledger_never_become_zero(self):
        for usage, expected in ((None, "usage_unknown"),
            ({"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}, "cost_unreconciled"),
            ({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, "cost_unreconciled"),
            ({"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 3}, "usage_unknown")):
            with self.subTest(usage=usage):
                self.prepare_scenario(registered=False, token_limit=3)
                decision = self.core_reserve()
                self.assertTrue(decision.allowed)
                attempt = self.budget.request_attempts.get()
                if usage is not None:
                    core.record_usage(budget_pk=self.budget.pk, attempt_pk=attempt.pk, mode="offline_test", usage_report=usage)
                before = self.stop_snapshot()
                refusal = self.core_reserve(index=2)
                self.assertEqual(refusal.reason, expected)
                self.assertEqual(self.stop_snapshot(), before)
        for fault in ("total_relation", "negative", "bool", "receipt", "overflow", "source", "operation", "counter", "seq"):
            with self.subTest(fault=fault):
                self.prepare_scenario(registered=False, token_limit=3)
                self.assertTrue(self.core_reserve().allowed)
                attempt = self.budget.request_attempts.get()
                core.record_usage(budget_pk=self.budget.pk, attempt_pk=attempt.pk, mode="offline_test", usage_report=REPORTED_USAGE)
                attempt.refresh_from_db(); self.reconcile_report(attempt)
                if fault in {"total_relation", "negative", "bool", "overflow"}:
                    report = {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 4}
                    if fault == "negative":report = {"prompt_tokens": -1, "completion_tokens": 4, "total_tokens": 3}
                    if fault == "bool":report = {"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 3}
                    if fault == "overflow":report = {"prompt_tokens": 2**63, "completion_tokens": 0, "total_tokens": 2**63}
                    QuerySet.update(TranslationRequestAttempt.objects.filter(pk=attempt.pk), usage_report=report)
                elif fault == "receipt":QuerySet.update(TranslationRequestAttempt.objects.filter(pk=attempt.pk), receipt_sha256="d" * 64)
                elif fault == "source":QuerySet.update(TranslationRequestAttempt.objects.filter(pk=attempt.pk), source_sha256="d" * 64)
                elif fault == "operation":QuerySet.update(TranslationRequestAttempt.objects.filter(pk=attempt.pk), operation_uuid=uuid4())
                elif fault == "seq":QuerySet.update(TranslationRequestAttempt.objects.filter(pk=attempt.pk), seq=2)
                else:QuerySet.update(TranslationRetryBudget.objects.filter(pk=self.budget.pk), requests_reserved=0)
                before = self.stop_snapshot()
                self.assertEqual(self.core_reserve(index=2).reason, "ledger_inconsistent")
                self.assertEqual(self.stop_snapshot(), before)
        # Real writer upgrade and idempotent receipt preserve one slot and one total.
        self.prepare_scenario(registered=False, token_limit=3)
        self.assertTrue(self.core_reserve().allowed)
        attempt = self.budget.request_attempts.get()
        core.record_usage(budget_pk=self.budget.pk, attempt_pk=attempt.pk, mode="offline_test", usage_report=REPORTED_USAGE)
        attempt.refresh_from_db(); self.reconcile_report(attempt)
        before = self.stop_snapshot()
        self.assertEqual(self.reconcile_report(attempt).reason, "usage_already_recorded")
        self.assertEqual(self.core_reserve(index=2).reason, core.REPORTED_TOKEN_STOP)
        self.assertEqual(self.stop_snapshot(), before)
        QuerySet.update(TranslationRetryBudget.objects.filter(pk=self.budget.pk), state="blocked", blocked_reason="original_block")
        self.assertEqual(self.core_reserve(index=2).reason, "original_block")
        # Individually legal reports can still overflow the bounded full-root sum.
        self.prepare_scenario(registered=False, token_limit=core.MAX_REPORTED_TOKENS)
        for index, total in ((1, core.MAX_REPORTED_TOKENS - 1), (2, 2)):
            self.assertTrue(self.core_reserve(index=index).allowed)
            attempt = self.budget.request_attempts.get(provider_attempt_index=index)
            report = {"prompt_tokens": total, "completion_tokens": 0, "total_tokens": total}
            core.record_usage(budget_pk=self.budget.pk, attempt_pk=attempt.pk, mode="offline_test", usage_report=report)
            attempt.refresh_from_db(); self.reconcile_report(attempt)
        self.assertEqual(core.resolve_budget(self.identity, mode="offline_test", now=NOW).reason, "ledger_inconsistent")

    def test_concurrent_admission_and_deadline_keep_original_fences(self):
        self.prepare_scenario(registered=False, token_limit=3)
        self.assertTrue(self.core_reserve().allowed)
        attempt = self.budget.request_attempts.get()
        core.record_usage(budget_pk=self.budget.pk, attempt_pk=attempt.pk, mode="offline_test", usage_report=REPORTED_USAGE)
        attempt.refresh_from_db(); self.reconcile_report(attempt)
        before = self.stop_snapshot()
        results, errors = self.locked_workers(TranslationRetryBudget, self.budget.pk,
            lambda index:self.core_reserve(index=index + 2), count=2)
        self.assertEqual(errors, [])
        self.assertEqual([r.reason for r in results], [core.REPORTED_TOKEN_STOP] * 2)
        self.assertEqual(self.stop_snapshot(), before)
        self.prepare_scenario(registered=False, token_limit=4)
        results, errors = self.locked_workers(TranslationRetryBudget, self.budget.pk,
            lambda index:self.core_reserve(index=index + 1), count=2)
        self.assertEqual(errors, [])
        self.assertCountEqual([r.reason for r in results], ["request_reserved", "usage_unknown"])
        self.assertEqual(self.budget.request_attempts.count(), 1)
        self.prepare_scenario(registered=False, token_limit=3)
        before = self.stop_snapshot()
        results, errors = self.locked_workers(TranslationRetryBudget, self.budget.pk,
            lambda _:self.core_reserve(), cross_deadline=True)
        self.assertEqual(errors, [])
        self.assertEqual(results[0].reason, "budget_deadline_expired")
        self.assertEqual(self.stop_snapshot(), before)
        # Inflight owner has a real reconciled usage>=N, but a fresh invocation still cannot take it.
        self.prepare_scenario(registered=True, token_limit=3)
        script = [{"content": json.dumps({**self.payload, "body_zh": ""}),
                   "usage": REPORTED_USAGE, "wait_for_receipt": True}, *self.normal_script()]
        sdk = self.fake(script); self.sdks.append(sdk)
        def owner(_):
            with self.dependencies(script, sdk=sdk):return translate_article_task.run(*self.message[0], **self.message[1])
        with self.running_workers(owner, releases=(sdk.choices_release,)) as state:
            fixture_requirement(sdk.choices_ready.wait(8), "real owner first usage gate")
            attempt = self.budget.request_attempts.get(); self.reconcile_report(attempt)
            self.no_business_locks(state["pids"][0])
            before = self.stop_snapshot()
            result, contender = self.replay()
            self.assertEqual(result.get("reason"), "model_start_unknown")
            self.assertEqual(contender.trace, [])
            self.assertEqual(self.stop_snapshot(), before)
            sdk.choices_release.set()
        self.workers_clean(state)
        self.assertEqual(state["results"][0].get("reason"), core.REPORTED_TOKEN_STOP)
        self.assertEqual(self.budget.request_attempts.count(), 1)
        self.constructor.assert_not_called()

    def test_committed_checkpoint_resumes_without_token_recharge(self):
        for fence in (None, "grant", "deadline"):
            with self.subTest(fence=fence):
                self.prepare_scenario(registered=True, token_limit=3)
                # The failure happens in the real final transaction after real checkpoint commit.
                from django.db import OperationalError
                with self.storage_fault("final_article") as hits:
                    with self.assertRaises(OperationalError):self.replay()
                self.assertEqual(hits, ["final_article"])
                run = self.actual_run()
                fixture_requirement(run.raw_response[job.PROGRESS_KEY]["state"] == "checkpoint_saved"
                    and recovery.RESULT_KEY in run.raw_response, "real committed checkpoint prerequisite")
                attempt = self.budget.request_attempts.get(); self.reconcile_report(attempt)
                self.assertEqual(core.resolve_budget(self.identity, mode="offline_test", now=NOW).reason, core.REPORTED_TOKEN_STOP)
                checkpoint = deepcopy(run.raw_response[recovery.RESULT_KEY])
                creates = sum(e["event"] == "create" for s in self.sdks[self.case_sdk_index:] for e in s.trace)
                read_count = sum(e["event"] == "business_read" for r in self.readers[self.case_reader_index:] for e in r.trace)
                ledger = deepcopy(list(self.budget.request_attempts.values()))
                if fence:self.mutate_fence(fence)
                before = self.stop_snapshot()
                result, sdk = self.replay()
                self.assertEqual(sdk.trace, [])
                self.assertEqual(self.actual_run().raw_response[recovery.RESULT_KEY], checkpoint)
                self.assertEqual(list(self.budget.request_attempts.values()), ledger)
                if fence:
                    self.assertFalse(result.get("translated"))
                    self.assertEqual(self.stop_snapshot(), before)
                else:
                    self.assertTrue(result.get("translated"))
                    self.article.refresh_from_db()
                    self.assertEqual(self.article.body_zh, self.payload["body_zh"])
                    self.assertEqual(self.actual_run().raw_response[job.PROGRESS_KEY]["state"], "final_applied")
                    repeated, sdk = self.replay()
                    self.assertEqual(repeated.get("reason"), "claim_already_consumed")
                    self.assertEqual(repeated.get("final_receipt"), result.get("final_receipt"))
                    self.assertEqual(sdk.trace, [])
                self.assertEqual(sum(e["event"] == "create" for s in self.sdks[self.case_sdk_index:] for e in s.trace), creates)
                self.assertEqual(sum(e["event"] == "business_read" for r in self.readers[self.case_reader_index:] for e in r.trace), read_count)
                self.assertEqual(self.budget.request_attempts.count(), 1)

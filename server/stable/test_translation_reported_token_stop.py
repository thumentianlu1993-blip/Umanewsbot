"""B089: two real-entry RED candidates, never execute outside ROOT's fixed PG window.

Only closed SDK/broker boundaries are substituted. Core admission, request reservation,
usage audit, source reads, checkpoint and final writers remain the current real code.
The limit-4 normal control runs before the limit-3 assertion in each test method.
"""
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from uuid import uuid4
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import connection, connections
from django.test import RequestFactory

from stable import admin as article_admin
from stable.models import (
    ArticleTranslationStatus, NewsArticle, NotificationLog, OperationLog, RacingRegion,
    TaskExecutionLog, TranslationRetryBudget, TranslationRun,
)
from stable.readonly_translation_e2e_fixture import RemainingReadonlyE2EFixture
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

    def prepare_scenario(self, *, registered, token_limit):
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
            self.readroot = ro.initialize_read_budget(tool_read_limit=1, now=NOW, baseline={
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

    def run_quality_scenario(self, *, registered, token_limit):
        self.prepare_scenario(registered=registered, token_limit=token_limit)
        script = [{"content": json.dumps({**self.payload, "body_zh": ""}, ensure_ascii=False),
                   "usage": REPORTED_USAGE, "wait_for_receipt": True}, *self.normal_script()]
        sdk = self.fake(script)
        self.sdks.append(sdk)
        def consume(_):
            with self.dependencies(script, sdk=sdk):
                return translate_article_task.run(*self.message[0], **self.message[1])
        with self.settings(TRANSLATION_MAX_ATTEMPTS=2):
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

    def test_registered_quality_retry_stops_when_reported_total_reaches_limit(self):
        self.assert_limit4_control(registered=True)
        self.assert_stop(registered=True)

    def test_ordinary_quality_retry_stop_and_failed_closure_repeat(self):
        # Early failed closure/repeat subscenarios belong to the approved later GREEN contract;
        # this RED-prep card freezes its real same-claim second-create counterexample only.
        self.assert_limit4_control(registered=False)
        self.assert_stop(registered=False)

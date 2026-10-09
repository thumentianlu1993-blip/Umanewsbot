"""B057：冻结十方法的真实PG端到端测试源码，原三方法保持原文。

B056原三方法已获独立实际synthetic GREEN；B057集中新增冻结E04–E10七方法源码。
新候选未collect/执行，前置不满足仍为ERROR，绝不手填目标终态，35总义务保持。
"""
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
import json
import inspect
import unittest
from uuid import uuid4
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import connection, connections
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from stable import admin as article_admin
from stable.models import (ArticleStatus, ArticleTranslationStatus, NewsArticle, NotificationLog,
                           OperationLog, TranslationRetryBudget, TranslationRun, WorkflowStatus)
from stable.services import managed_readonly_steps as ro, managed_readonly_translation as job
from stable.services import translation, translation_recovery as recovery, translation_retry_budget as core
from stable.tasks import translate_article_task
from stable.test_managed_translation_budget_consumer import (
    ManagedTranslationBudgetConsumerFixture, NOW, NORMAL_PAYLOAD, USAGE, fixture_requirement,
)
from copy import deepcopy
from threading import Event
from django.db import IntegrityError, OperationalError, transaction
from django.db.models.query import QuerySet
from stable.models import ManagedReadonlyTaskBudget
from stable.readonly_translation_e2e_fixture import RemainingReadonlyE2EFixture, CommittedFixtureExit


FIRST_RED_METHODS = (
    "test_user_retry_reaches_read_step_and_final_article",
    "test_resume_after_read_commit_before_model_start",
)
E03_PREREQUISITE = "real registered chain must commit Article/Run/final receipt before E03 target RED"


class ManagedReadonlyTranslationEndToEndTests(RemainingReadonlyE2EFixture, ManagedTranslationBudgetConsumerFixture):
    def setUp(self):
        super().setUp()
        self.article.body_ja_raw = self.article.body_ja_raw * 6
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save(update_fields=["body_ja_raw", "body_ja_normalized", "updated_at"])
        self.payload = {**NORMAL_PAYLOAD, "body_zh": "拍卖后仍有十分充足的时间考虑并作出决定。" * 6}
        self.readers, self.sdks = [], []
        self.readroot = None
        self.message = None
        self.plan = None
        self.addCleanup(connections.close_all)

    def user_retry_message(self, receipt_version=1):
        """真实admin→OperationLog/due→selector/claim；仅外部broker dispatch capture。"""
        fixture_requirement(connection.vendor == "postgresql" and not connection.in_atomic_block,
                            "B051必须ROOT独占真实PG、无外层atomic")
        user = get_user_model().objects.create_user(username="b051-" + str(uuid4()), is_staff=True, is_superuser=True)
        request = RequestFactory().post("/admin/stable/newsarticle/")
        request.user, request.session = user, {}
        request._messages = FallbackStorage(request)
        controller = article_admin.NewsArticleAdmin(NewsArticle, AdminSite())
        with patch.object(article_admin, "dispatch_task") as broker:
            controller.retry_failed_translations(request, NewsArticle.objects.filter(pk=self.article.pk))
        fixture_requirement(broker.call_count == 1, "admin必须实际接受一次请求并调用外部派发边界")
        fixture_requirement(broker.call_args.args == (article_admin.translate_article_task, self.article.pk),
                            "admin捕获消息必须绑定真实article/task")
        self.article.refresh_from_db()
        fixture_requirement(self.article.translation_status == ArticleTranslationStatus.FAILED
                            and self.article.translation_next_retry_at == NOW, "真实due状态未落库")
        fixture_requirement(OperationLog.objects.filter(admin=user, action_type="translation_retry_requested",
                            target_type="article", target_id=str(self.article.pk)).count() == 1,
                            "真实用户重试OperationLog未落库")
        identity = core.BudgetIdentity("managed_translation_retry", self.article.source_site,
            self.article.source_article_id, recovery.translation_input_sha256(self.article), "b" * 64,
            "offline-synthetic", "offline-only", article_pk_snapshot=self.article.pk)
        decision = core.resolve_budget(identity, mode="offline_test", now=NOW, initial_contract={
            "request_limit": 2, "opened_at": NOW, "deadline_at": NOW + timedelta(minutes=10),
            "policy_snapshot": {"mode": "offline_test", "version": 1},
            "baseline_receipt": {"kind": "synthetic_no_prior_consumption"}})
        fixture_requirement(decision.allowed, "真实fixture parent建立失败: " + decision.reason)
        self.identity = replace(identity, operation_uuid=decision.operation_uuid)
        self.budget = TranslationRetryBudget.objects.get(pk=decision.budget_pk)
        with recovery._offline_budget_scope(self.identity):
            with patch.object(recovery.translate_article_task, "delay") as broker:
                dispatched = recovery.dispatch_due_translation_retries(now=NOW)
            fixture_requirement(dispatched.dispatched_ids == [self.article.pk] and broker.call_count == 1,
                                "真实selector必须取得唯一确切claim消息")
            args, kwargs = broker.call_args
            self.message = (tuple(args), dict(kwargs))
            fixture_requirement(kwargs.get("preclaimed_retry") is True and type(kwargs.get("claim_run_id")) is int
                                and kwargs.get("claim_started_at") == NOW.isoformat(), "claim envelope不完整")
            self.envelope = ro.ReadEnvelope(self.article.pk, kwargs["claim_run_id"], kwargs["claim_started_at"])
            options = {"tool_read_limit": 1, "now": NOW, "baseline": {
                "kind": "synthetic_no_prior_tool_reads", "operation_uuid": str(self.identity.operation_uuid)}}
            if "receipt_version" in inspect.signature(ro.initialize_read_budget).parameters:
                options["receipt_version"] = receipt_version
            self.readroot = ro.initialize_read_budget(**options)
        fixture_requirement(self.budget.requests_reserved == 0 and self.budget.request_attempts.count() == 0
                            and self.readroot.steps.count() == 0, "新合成baseline不能已有消费")

    @contextmanager
    def scope(self, *, reader_fault="none"):
        sdk = self.fake([{"content": json.dumps(self.payload, ensure_ascii=False), "usage": USAGE}])
        reader = ro._ClosedSourceExcerptReader(reader_fault)
        self.sdks.append(sdk); self.readers.append(reader)
        with recovery._offline_budget_scope(self.identity), ro.readonly_scope(self.readroot.pk), \
                translation._offline_sdk_dependency(sdk), ro.reader_dependency(reader):
            yield reader, sdk
        self.constructor.assert_not_called()
        self.assertTrue(reader.closed and sdk._closed)
        self.assertIsNone(recovery._current_offline_budget_binding())
        self.assertIsNone(translation._offline_sdk_binding.get())

    def register(self):
        with self.scope():
            self.plan = job.register_offline_readonly_translation_job(self.envelope)
        args, kwargs = self.message
        # Persisted UUID is added to the captured exact original envelope, never a replacement run/claim.
        self.message = (args, {**kwargs, "readonly_job_uuid": self.plan["payload"]["plan_uuid"],
                              "suppress_automation": True})
        run = TranslationRun.objects.get(pk=self.envelope.run_id)
        fixture_requirement(job.decode_control(run.raw_response)[job.PLAN_KEY] == self.plan,
                            "真实安全登记/strict codec前置必须成功，不计作业务RED")
        fixture_requirement(run.raw_response[recovery.CLAIM_KEY]["phase"] == "claimed", "登记不能消费claim")

    def consume(self):
        args, kwargs = self.message
        with self.scope():
            result = translate_article_task.run(*args, **kwargs)
        print("B051_ACTUAL_CONSUMER", self.envelope, result, flush=True)
        return result

    def test_publication_receipt_real_consumer_checkpoint(self):
        publication = NOW - timedelta(days=3)
        self.article.published_at = publication
        self.article.published_at_verified = None
        self.article.published_at_evidence = {"method": "stored-db"}
        self.article.save(update_fields=["published_at", "published_at_verified", "published_at_evidence"])
        self.user_retry_message(receipt_version=2)
        self.register()
        outcome = self.consume()
        run = TranslationRun.objects.get(pk=self.envelope.run_id)
        step = self.readroot.steps.get()
        self.assertEqual(run.status, "success", outcome)
        self.assertEqual(self.reads(), 1)
        self.assertIn("publication", step.result)
        self.assertEqual(step.result["publication"]["published_at"], publication.isoformat())
        self.assertIsNone(step.result["publication"]["verified"])
        progress = run.raw_response[job.PROGRESS_KEY]
        self.assertEqual(progress["read_reference"], {"step_uuid": str(step.step_uuid), "result_sha256": step.result_sha256})
        self.assertEqual(run.raw_response[recovery.RESULT_KEY]["metadata"][job.PROVENANCE_KEY]["read_result_sha256"], step.result_sha256)

    def test_publication_v2_lifecycle_only_fetches_bounded_evidence_projection(self):
        self.user_retry_message(receipt_version=2)
        with CaptureQueriesContext(connection) as queries:
            self.register()
            initial = self.consume()
            repeated = self.consume()
        self.assertTrue(initial.get("translated"), initial)
        self.assertEqual(repeated.get("final_receipt"), initial["final_receipt"])
        selects = [q["sql"] for q in queries if q["sql"].lstrip().upper().startswith("SELECT") and '"published_at_evidence"' in q["sql"]]
        self.assertEqual(len(selects), 1, "v2 registration/claim/source/model/checkpoint/final/replay must not fetch unbounded JSON")
        self.assertIn('AS "_ro_publication_evidence"', selects[0])
        self.assertIn("4097", selects[0])
        self.assertEqual(self.reads(), 1)
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(self.plan["payload"]["job_kind"], "readonly_translation_retry_v2")
        self.assertEqual(self.plan["payload"]["steps"][0]["tool"], "source_excerpt_v2")
        # A re-signed mixed plan still cannot turn v2 result identity into a v1 job.
        altered = deepcopy(self.actual_run().raw_response)
        altered[job.PLAN_KEY]["payload"]["job_kind"] = "readonly_translation_retry_v1"
        altered[job.PLAN_KEY]["payload_sha256"] = job._sha(altered[job.PLAN_KEY]["payload"])
        with self.assertRaises(job.RegisteredJobRefusal):job.decode_control(altered)

    def test_publication_v2_read_checkpoint_final_reuse_preserves_original_receipt(self):
        self.user_retry_message(receipt_version=2); self.register()
        with self.scope(reader_fault="exit_after_commit"):
            job.prepare_registered_read_phase(self.envelope)
            with self.assertRaises(ro.ReadFixtureExit):ro.execute_step(self.envelope, {"body_chars": 256}, now=NOW)
        step = self.readroot.steps.get()
        original = deepcopy((step.step_uuid, step.read_at, step.result_sha256, step.result))
        NewsArticle.objects.filter(pk=self.article.pk).update(published_at=NOW-timedelta(days=20), published_at_verified=True,
            published_at_evidence={"method": "changed-after-read"})
        # Exit after the actual checkpoint transaction; resume gets no new model/read charge.
        with self.checkpoint_commit_gate(exit_after=True):
            with self.assertRaises(CommittedFixtureExit):self.consume()
        run = self.actual_run()
        self.assertEqual(run.raw_response[job.PROGRESS_KEY]["state"], "checkpoint_saved")
        checkpoint = deepcopy(run.raw_response[recovery.RESULT_KEY])
        before = (self.reads(), len(self.creates()), self.counters())
        completed = self.consume()
        self.assertTrue(completed.get("translated"), completed)
        replay = self.consume()
        self.assertEqual(replay.get("final_receipt"), completed["final_receipt"])
        self.assertEqual(self.actual_run().raw_response[recovery.RESULT_KEY], checkpoint)
        self.assertEqual((self.reads(), len(self.creates()), self.counters()), before)
        step.refresh_from_db()
        self.assertEqual((step.step_uuid, step.read_at, step.result_sha256, step.result), original)
        self.assertEqual(completed["final_receipt"]["payload"]["read_step_uuid"], str(step.step_uuid))
        self.assertEqual(completed["final_receipt"]["payload"]["read_result_sha256"], step.result_sha256)

    def test_publication_v2_invalid_material_prevents_provider_and_stays_unknown(self):
        self.article.published_at_evidence = {"raw": "x" * 10000}
        self.article.save(update_fields=["published_at_evidence"])
        self.user_retry_message(receipt_version=2); self.register()
        denied = self.consume()
        self.assertFalse(denied.get("translated"), denied)
        self.assertEqual(denied.get("reason"), "publication_evidence_oversized")
        self.assertEqual((self.reads(), self.creates(), self.counters()), (1, [], (1, 0, 1, 0)))
        self.assertNotIn(recovery.RESULT_KEY, self.actual_run().raw_response)
        repeated = self.consume()
        self.assertIn(repeated.get("reason"), {"step_result_unknown", "read_unknown"})
        self.assertEqual((self.reads(), self.creates(), self.counters()), (1, [], (1, 0, 1, 0)))

    def test_publication_v2_model_started_unknown_never_reissued(self):
        self.user_retry_message(receipt_version=2); self.register()
        def create(client, **kwargs):raise CommittedFixtureExit("actual CAS and request slot before wire")
        with patch.object(translation._ClosedOfflineSDKClient, "create", new=create):
            with self.assertRaises(CommittedFixtureExit):self.consume()
        progress = deepcopy(self.actual_run().raw_response[job.PROGRESS_KEY])
        self.assertEqual(progress["state"], "model_started")
        self.assertEqual(self.counters(), (1, 1, 1, 1))
        repeated = self.consume()
        self.assertEqual(repeated.get("reason"), "model_start_unknown")
        self.assertEqual(self.actual_run().raw_response[job.PROGRESS_KEY], progress)
        self.assertEqual((self.reads(), self.creates(), self.counters()), (1, [], (1, 1, 1, 1)))

    def test_publication_v2_checkpoint_apply_rejects_revocation_expiry_and_source_change(self):
        for fence in ("grant", "deadline", "source"):
            with self.subTest(fence=fence):
                # Only the fixture's explicit initialization option is varied.
                with patch.object(self, "user_retry_message", wraps=lambda: type(self).user_retry_message(self, receipt_version=2)):
                    self.new_scenario()
                with self.checkpoint_commit_gate(exit_after=True):
                    with self.assertRaises(CommittedFixtureExit):self.case_consume()
                checkpoint = deepcopy(self.actual_run().raw_response[recovery.RESULT_KEY])
                self.mutate_fence(fence); before = self.business_snapshot()
                denied = self.case_consume()
                self.assertFalse(denied.get("translated"), denied)
                self.assertEqual(self.business_snapshot(), before)
                self.assertEqual(self.actual_run().raw_response[recovery.RESULT_KEY], checkpoint)
                self.assertEqual((self.case_reads(), len(self.case_creates()), self.counters()), (1, 1, (1, 1, 1, 1)))
                self.assert_not_applied()

    def reads(self):
        return sum(sum(event["event"] == "business_read" for event in reader.trace) for reader in self.readers)

    def creates(self):
        return [event for sdk in self.sdks for event in sdk.trace if event["event"] == "create"]

    def assert_registration_preflight(self):
        """入口负校准是真实调用；正常拒绝不是RED目标，无内部授权/保存mock。"""
        args, kwargs = self.message
        before = TranslationRun.objects.get(pk=self.envelope.run_id).raw_response
        # 公共API必须收到真实目标；无scope + 显式run/仅article均不能绕过task guard。
        fixture_requirement(recovery._current_offline_budget_binding() is None, "直接API负校准必须无scope")
        run = TranslationRun.objects.get(pk=self.envelope.run_id)
        for target_run in (run, None):
            try:
                translation.translate_article(self.article, managed_run=target_run)
            except recovery.ManagedTranslationBudgetBlocked as exc:
                fixture_requirement(str(exc) == "registered_job_wrapper_required", "直接API拒绝原因不正确")
            else:
                fixture_requirement(False, "无scope直接API绕过持久登记guard；这是前置ERROR而不是目标RED")
        self.constructor.assert_not_called()
        self.budget.refresh_from_db(); self.readroot.refresh_from_db()
        fixture_requirement(TranslationRun.objects.get(pk=self.envelope.run_id).raw_response == before
                            and self.budget.requests_reserved == 0 and self.readroot.tool_reads_reserved == 0
                            and self.budget.request_attempts.count() == 0 and self.readroot.steps.count() == 0,
                            "直接API拒绝不能改plan/消费read或SDK")
        missing = translate_article_task.run(*args, **kwargs)
        fixture_requirement(missing.get("reason") == "registered_scope_missing", "登记后scope丢失不能旧路由")
        with recovery._offline_budget_scope(self.identity), ro.readonly_scope(self.readroot.pk):
            no_dependency = translate_article_task.run(*args, **kwargs)
        fixture_requirement(no_dependency.get("reason") == "registered_dependency_missing", "缺SDK必须入口拒绝")
        fixture_requirement(TranslationRun.objects.get(pk=self.envelope.run_id).raw_response == before
                            and self.reads() == 0 and self.creates() == [], "入口拒绝不能消费/改plan")
        self.constructor.assert_not_called()

    def test_user_retry_reaches_read_step_and_final_article(self):
        self.user_retry_message(); self.register(); self.assert_registration_preflight()
        result = self.consume()
        fixture_requirement(type(result) is dict and ("reason" in result or result.get("translated")),
                            "consumer必须正常业务返回，不能missing import/setup ERROR")
        self.budget.refresh_from_db(); self.readroot.refresh_from_db()
        print("B051_RED_E01_OBSERVATION", "read_count", self.reads(), "sdk_count", len(self.creates()),
              "requests", self.budget.requests_reserved, "readslots", self.readroot.tool_reads_reserved, flush=True)
        # RED目标：合法已登记真实入口目前停在组合缺口，正常返回却无真实read/最终产物。
        self.assertEqual(self.reads(), 1, "合法登记的真实consumer未抵达只读业务SELECT")
        self.assertTrue(result.get("translated"), result)
        self.assertEqual(len(self.creates()), 1)
        step = self.readroot.steps.get()
        self.assertEqual(step.state, "completed")
        self.assertGreater(len(self.article.body_ja_normalized), 256)
        self.assertEqual(step.result["body_excerpt"], self.article.body_ja_normalized[:256])
        self.assertTrue(any(self.article.body_ja_normalized in json.dumps(event["messages"], ensure_ascii=False)
                            for event in self.creates()), "摘录不能替代模型的完整原正文")
        self.assertTrue(any(step.result["body_excerpt"] in json.dumps(event["messages"], ensure_ascii=False)
                            and str(step.step_uuid) in json.dumps(event["messages"], ensure_ascii=False)
                            and step.result_sha256 in json.dumps(event["messages"], ensure_ascii=False)
                            for event in self.creates()))
        self.article.refresh_from_db()
        run = TranslationRun.objects.get(pk=self.envelope.run_id)
        self.assertEqual(self.article.status, ArticleStatus.TRANSLATED)
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PENDING_EDIT)
        self.assertEqual(self.article.translation_status, ArticleTranslationStatus.TRANSLATED)
        self.assertEqual(run.status, "success")
        self.assertEqual(self.budget.requests_reserved, 1)
        self.assertEqual(self.budget.request_attempts.get().state, "usage_reported")
        self.assertEqual(self.readroot.tool_reads_reserved, 1)
        self.assertIn(job.FINAL_KEY, run.raw_response)
        self.assertEqual(run.raw_response[recovery.RESULT_KEY]["metadata"][job.PROVENANCE_KEY]["read_result_sha256"],
                         step.result_sha256)
        self.assertEqual(NotificationLog.objects.count(), 0)

    def test_resume_after_read_commit_before_model_start(self):
        self.user_retry_message(); self.register()
        with self.scope(reader_fault="exit_after_commit"):
            job.prepare_registered_read_phase(self.envelope)
            with self.assertRaises(ro.ReadFixtureExit):
                ro.execute_step(self.envelope, {"body_chars": 256}, now=NOW)
        step = self.readroot.steps.get()
        before = (step.pk, step.step_uuid, step.result_sha256, step.read_at, step.result)
        self.readroot.refresh_from_db(); self.budget.refresh_from_db()
        run = TranslationRun.objects.get(pk=self.envelope.run_id)
        fixture_requirement(step.state == "completed" and self.reads() == 1
                            and self.readroot.tool_reads_reserved == 1 and self.budget.requests_reserved == 0
                            and self.budget.request_attempts.count() == 0 and self.creates() == []
                            and run.raw_response[recovery.CLAIM_KEY]["phase"] == "executing"
                            and recovery.RESULT_KEY not in run.raw_response, "真实read提交断点不成立，不能充RED")
        original_deadline = self.readroot.deadline_at
        result = self.consume()
        print("B051_RED_E02_OBSERVATION", "committed_read", before[:4], result, flush=True)
        self.assertTrue(result.get("translated"), "真实read-completed断点无法由原消息恢复到Article终态: " + str(result))
        step.refresh_from_db(); self.readroot.refresh_from_db()
        self.assertEqual((step.pk, step.step_uuid, step.result_sha256, step.read_at, step.result), before)
        self.assertEqual(self.reads(), 1)
        self.assertEqual(self.readroot.tool_reads_reserved, 1)
        self.assertEqual(self.readroot.deadline_at, original_deadline)
        self.assertEqual(len(self.creates()), 1)

    def test_completed_job_redelivery_returns_same_final_receipt(self):
        self.user_retry_message(); self.register()
        initial = self.consume()
        # Explicit prerequisite ERROR if somebody incorrectly selects E03 before the real GREEN dependency.
        # Never fabricate registered terminal/checkpoint/final; no legacy receipt requirement.
        fixture_requirement(initial.get("translated"), E03_PREREQUISITE)
        run = TranslationRun.objects.get(pk=self.envelope.run_id)
        self.article.refresh_from_db()
        fixture_requirement(run.status == "success" and job.FINAL_KEY in run.raw_response,
                            "E03真实registered终态缺失，不能计RED")
        final = run.raw_response[job.FINAL_KEY]
        before = (self.article.updated_at, run.updated_at, self.reads(), len(self.creates()),
                  self.budget.request_attempts.count(), self.readroot.steps.count())
        repeated = self.consume()
        print("B053_E03_ACTUAL_COMPLETED_REDELIVERY", initial, repeated, flush=True)
        self.assertEqual(repeated.get("final_receipt"), final, "真实registered完成态重投未返回同一final receipt")
        self.article.refresh_from_db(); run.refresh_from_db()
        self.assertEqual(run.raw_response[job.FINAL_KEY], final)
        self.assertEqual((self.article.updated_at, run.updated_at, self.reads(), len(self.creates()),
                         self.budget.request_attempts.count(), self.readroot.steps.count()), before)
        self.assertEqual(NotificationLog.objects.count(), 0)

    def test_two_quality_rounds_share_one_read_and_cumulative_request_budget(self):
        self.new_scenario()
        bad = {**self.payload, "body_zh": ""}
        script = [{"content": json.dumps(bad), "usage": USAGE}, *self.normal_script()]
        with self.wire_gate("after_usage_choices") as (ready, release, observed):
            with self.running_workers(lambda _: self.case_consume(script), releases=(release,)) as state:
                fixture_requirement(ready.wait(8), "真实第一轮usage journal须先于choices")
                attempt = self.budget.request_attempts.get()
                fixture_requirement(attempt.state == "usage_reported" and attempt.usage_report == USAGE,
                                    "质量失败前usage必须实际提交")
                self.no_business_locks(observed["pid"])
                self.reconcile(attempt)  # 主连接显式synthetic receipt，绝非SDK response自动对账。
                release.set()
            self.workers_clean(state)
        self.assertTrue(state["results"][0].get("translated"), state["results"])
        self.assertEqual((self.case_reads(), len(self.case_creates()), self.counters()), (1, 2, (1, 2, 1, 2)))
        self.assertEqual([e["requests_reserved"] for e in self.case_creates()], [1, 2])
        self.assertEqual([e["attempts"][-1]["provider_attempt_index"] for e in self.case_creates()], [1, 2])
        final = self.actual_run().raw_response[job.FINAL_KEY]
        repeated = self.case_consume()
        self.assertEqual(repeated.get("final_receipt"), final)
        self.assertEqual((self.case_reads(), len(self.case_creates())), (1, 2))
        # 同一次provider允许3质量轮时，前两次独立对账也不能突破固定request2。
        self.new_scenario()
        gates, releases = [Event(), Event()], [Event(), Event()]
        original = translation._ClosedOfflineSDKResponse.choices.fget
        hit = [0]
        def choices(response):
            index = hit[0]; hit[0] += 1
            fixture_requirement(index < 2, "第三wire response不应抵达")
            gates[index].set()
            if not releases[index].wait(8):raise RuntimeError("quality receipt gate timeout")
            return original(response)
        script = [{"content": json.dumps(bad), "usage": USAGE}] * 2
        with self.settings(TRANSLATION_MAX_ATTEMPTS=3), patch.object(
                translation._ClosedOfflineSDKResponse, "choices", new=property(choices)):
            with self.running_workers(lambda _: self.case_consume(script), releases=releases) as state:
                for index in range(2):
                    fixture_requirement(gates[index].wait(8), "每轮真实usage提交gate")
                    attempt = self.budget.request_attempts.get(provider_attempt_index=index + 1)
                    fixture_requirement(attempt.usage_report == USAGE, "每轮usage先提交")
                    self.reconcile(attempt); releases[index].set()
            self.workers_clean(state)
        self.assertFalse(state["results"][0].get("translated"), state["results"])
        self.assertEqual(state["results"][0].get("reason"), "request_limit_exhausted")
        self.assertEqual((self.case_reads(), len(self.case_creates()), self.counters()), (1, 2, (1, 2, 1, 2)))
        self.assert_not_applied()

    def test_tool_exhaustion_or_unknown_prevents_model_start(self):
        self.new_scenario()
        # 固定登记合同tool1变为0，是实际策略耗尽/漂移负例，不伪造slot或completed ledger。
        QuerySet.update(ManagedReadonlyTaskBudget.objects.filter(pk=self.readroot.pk), tool_read_limit=0)
        result = self.case_consume()
        self.assertFalse(result.get("translated"), result)
        self.assertIn(result.get("reason"), {"tool_read_limit_exhausted", "registered_plan_invalid"})
        self.assertEqual((self.case_reads(), self.case_creates(), self.counters()), (0, [], (0, 0, 0, 0)))
        for fault, expected_reads in [("timeout_before_read", 0), ("timeout_after_read", 1),
                                      ("exit_after_reservation", 0), ("exit_after_read", 1)]:
            with self.subTest(fault=fault):
                self.new_scenario()
                if fault.startswith("exit_"):
                    with self.assertRaises(ro.ReadFixtureExit):self.case_consume(reader_fault=fault)
                else:
                    result = self.case_consume(reader_fault=fault)
                    self.assertFalse(result.get("translated"), result)
                fixture_requirement(self.counters() == (1, 0, 1, 0)
                                    and self.readroot.steps.get().state == "inflight", "真实保留unknown槽前置")
                step = self.readroot.steps.get(); token = (step.pk, step.step_uuid, step.reservation_token)
                repeated = self.case_consume()
                self.assertFalse(repeated.get("translated"), repeated)
                self.assertIn(repeated.get("reason"), {"read_unknown", "step_result_unknown"})
                step.refresh_from_db()
                self.assertEqual((step.pk, step.step_uuid, step.reservation_token), token)
                self.assertEqual((self.case_reads(), self.case_creates(), self.counters()),
                                 (expected_reads, [], (1, 0, 1, 0)))
                self.assert_not_applied()

    def test_model_unavailable_retains_structured_evidence_and_explicit_gap(self):
        self.new_scenario()
        before = self.business_snapshot()
        args, kwargs = self.message
        with recovery._offline_budget_scope(self.identity), ro.readonly_scope(self.readroot.pk):
            missing = translate_article_task.run(*args, **kwargs)
        self.assertEqual(missing.get("reason"), "registered_dependency_missing")
        self.assertEqual(self.business_snapshot(), before)
        self.assertEqual((self.case_reads(), self.case_creates()), (0, []))
        result = self.case_consume([{"error": "timeout"}])
        self.assertFalse(result.get("translated"), result)
        self.assertEqual(result.get("reason"), "model_start_unknown")
        step = self.readroot.steps.get()
        self.assertEqual(step.state, "completed")
        self.assertEqual(step.result["body_excerpt"], self.article.body_ja_normalized[:256])
        progress = self.actual_run().raw_response[job.PROGRESS_KEY]
        self.assertEqual(progress["exit_reason"], "model_start_unknown")
        self.assertEqual(progress["read_reference"], {"step_uuid": str(step.step_uuid), "result_sha256": step.result_sha256})
        self.assertEqual(self.budget.request_attempts.get().state, "reserved")
        self.assertEqual((self.case_reads(), len(self.case_creates()), self.counters()), (1, 1, (1, 1, 1, 1)))
        with self.case_scope():
            cached = ro.execute_step(self.envelope, {"body_chars": 256}, now=NOW)
        self.assertTrue(cached.allowed and cached.cached)
        self.assertEqual((str(cached.step_uuid), cached.result), (str(step.step_uuid), step.result))
        self.assertEqual(self.case_reads(), 1)
        self.mutate_fence("grant")
        with self.case_scope():denied = ro.execute_step(self.envelope, {"body_chars": 256}, now=NOW)
        self.assertFalse(denied.allowed)
        self.assertIsNone(denied.result)
        self.assert_not_applied()

    def test_model_started_or_usage_unknown_is_not_reissued(self):
        for fault in ("before_create_exit", "SDK_exit", "SDK_timeout", "missing_usage", "after_usage_exit"):
            with self.subTest(fault=fault):
                self.new_scenario()
                script = self.normal_script()
                if fault == "SDK_exit":script = [{"error": "exit"}]
                if fault == "SDK_timeout":script = [{"error": "timeout"}]
                if fault == "missing_usage":script = self.normal_script(usage=None)
                if fault == "before_create_exit":
                    def create(client, **kwargs):raise CommittedFixtureExit("CAS+slot committed before wire create")
                    with patch.object(translation._ClosedOfflineSDKClient, "create", new=create):
                        with self.assertRaises(CommittedFixtureExit):self.case_consume(script)
                elif fault == "after_usage_exit":
                    def choices(response):raise CommittedFixtureExit("usage committed before response consumption")
                    with patch.object(translation._ClosedOfflineSDKResponse, "choices", new=property(choices)):
                        with self.assertRaises(CommittedFixtureExit):self.case_consume(script)
                elif fault == "SDK_exit":
                    with self.assertRaises(SystemExit):self.case_consume(script)
                else:
                    result = self.case_consume(script)
                    self.assertFalse(result.get("translated"), result)
                run = self.actual_run(); progress = deepcopy(run.raw_response[job.PROGRESS_KEY])
                fixture_requirement(self.counters() == (1, 1, 1, 1) and progress["model_owner_token"] is not None,
                                    "原CAS与slot须实际提交，不能手填model_started")
                self.assertNotIn(recovery.RESULT_KEY, run.raw_response)
                count = len(self.case_creates())
                self.assertEqual(count, 0 if fault == "before_create_exit" else 1)
                if fault == "after_usage_exit":self.reconcile(self.budget.request_attempts.get())
                repeated = self.case_consume()
                self.assertFalse(repeated.get("translated"), repeated)
                self.assertIn(repeated.get("reason"), {"model_start_unknown", "usage_unknown"})
                self.assertEqual(self.actual_run().raw_response[job.PROGRESS_KEY], progress)
                self.assertEqual((self.case_reads(), len(self.case_creates()), self.counters()), (1, count, (1, 1, 1, 1)))
                self.assert_not_applied()

    def test_version_source_grant_and_deadline_fence_each_resume_and_apply(self):
        fences = ("workflow_version", "query_version", "result_version", "source", "source_pair",
                  "claim_uuid", "permission_epoch", "grant", "deadline", "schema_bool",
                  "revision_float", "unknown_namespace", "null_plan")
        for fence in fences:
            with self.subTest(phase="read_completed_resume", fence=fence):
                self.new_scenario(); committed = self.committed_read()
                self.mutate_fence(fence); before = self.business_snapshot()
                result = self.case_consume()
                self.assertFalse(result.get("translated"), result)
                self.assertEqual(self.business_snapshot(), before)
                self.assertEqual((self.case_reads(), self.case_creates(), self.counters()), (1, [], (1, 0, 1, 0)))
                step = self.readroot.steps.get()
                self.assertEqual((step.pk, step.step_uuid, step.result_sha256, step.read_at, step.result), committed)
        # 实际PG锁等待在授权之前跨原deadline/撤权，绝不调用wire。
        for fence in ("grant", "deadline"):
            with self.subTest(phase="before_authorization_locked", fence=fence):
                self.new_scenario(); self.committed_read()
                with self.running_workers_during_parent_lock(fence) as state:pass
                self.workers_clean(state)
                self.assertFalse(state["results"][0].get("translated"), state["results"])
                self.assertEqual((self.case_reads(), self.case_creates(), self.counters()), (1, [], (1, 0, 1, 0)))
                self.assert_not_applied()
        for stage in ("before_create", "after_usage_choices", "checkpoint_committed"):
            stage_fences = fences if stage == "checkpoint_committed" else ("grant", "deadline")
            for fence in stage_fences:
                with self.subTest(phase=stage, fence=fence):
                    self.new_scenario()
                    gate = self.checkpoint_commit_gate(worker_only=True) if stage == "checkpoint_committed" else self.wire_gate(stage)
                    with gate as (ready, release, observed):
                        with self.running_workers(lambda _: self.case_consume(), releases=(release,)) as state:
                            fixture_requirement(ready.wait(8), "真实提交/SDK观察点必须到达: " + stage)
                            fixture_requirement(self.counters() == (1, 1, 1, 1), "真实CAS+slot已提交")
                            if stage != "checkpoint_committed":self.no_business_locks(observed["pid"])
                            if stage == "checkpoint_committed":
                                fixture_requirement(self.actual_run().raw_response[job.PROGRESS_KEY]["state"] == "checkpoint_saved",
                                                    "真实checkpoint/progress必须已提交")
                            self.mutate_fence(fence); before = self.business_snapshot()
                            if stage == "checkpoint_committed":
                                self.assertEqual(observed["hits"], 1, "主线程fence写入不得重复注册checkpoint gate")
                                self.assertNotEqual(observed["writer_thread"], observed["observer_thread"],
                                                    "checkpoint gate只观察真实worker提交")
                            release.set()
                        self.workers_clean(state)
                    self.assertFalse(state["results"][0].get("translated"), state["results"])
                    self.assertEqual(self.business_snapshot(), before)
                    self.assertEqual((self.case_reads(), len(self.case_creates()), self.counters()), (1, 1, (1, 1, 1, 1)))
                    self.assertEqual(recovery.RESULT_KEY in self.actual_run().raw_response, stage == "checkpoint_committed")
                    self.assert_not_applied()
        # final先持root锁并写Article/Run，独立撤权worker真实等待其commit；先合法提交不逆转。
        self.new_scenario()
        with self.final_commit_gate() as (ready, release, observed):
            def action(index):
                if index == 0:return self.case_consume()
                fixture_requirement(ready.wait(8), "撤权worker等实际final事务CAS")
                self.mutate_fence("grant")
                return {"revoked": True}
            with self.running_workers(action, count=2, releases=(release,)) as state:
                fixture_requirement(ready.wait(8), "真实final commit前观察点")
                contender = [pid for pid in state["pids"] if pid != observed["pid"]]
                fixture_requirement(len(contender) == 1, "两worker PID归属")
                self.wait_lock_graph(contender, observed["pid"], owner_is_worker=True)
                self.article.refresh_from_db()
                self.assertNotEqual(self.article.translation_status, ArticleTranslationStatus.TRANSLATED,
                                    "final commit之前不可披露未提交Article")
                release.set()
            self.workers_clean(state)
        self.assertEqual(sum(r.get("translated") is True for r in state["results"]), 1)
        self.article.refresh_from_db(); self.readroot.refresh_from_db()
        self.assertEqual(self.article.translation_status, ArticleTranslationStatus.TRANSLATED)
        self.assertEqual(self.readroot.state, "revoked")
        self.assertEqual((self.case_reads(), len(self.case_creates()), self.counters()), (1, 1, (1, 1, 1, 1)))
        # 合法final先提交的顺序不逆转Article；后围栏变化的重投不能披露旧receipt。
        for fence in ("grant", "deadline", "source", "workflow_version"):
            with self.subTest(phase="final_committed_redelivery", fence=fence):
                self.new_scenario(); completed = self.case_consume()
                fixture_requirement(completed.get("translated"), "已GREEN原整链完成前置")
                self.mutate_fence(fence); before = self.business_snapshot()
                denied = self.case_consume()
                self.assertFalse(denied.get("translated"), denied)
                self.assertNotIn("final_receipt", denied)
                self.assertEqual(self.business_snapshot(), before)
                self.assertEqual((self.case_reads(), len(self.case_creates())), (1, 1))

    def test_two_redeliveries_have_one_model_owner_and_one_final_apply(self):
        with self.subTest(phase="registered_read_race"):
            # 先从真实registered/未读状态竞争，不能用事先completed read掩盖read-inflight竞态。
            self.new_scenario()
            with self.parent_locked_workers(count=2) as state:pass
            self.workers_clean(state)
            self.assertEqual(sum(r.get("translated") is True for r in state["results"]), 1, state["results"])
            self.assertEqual((self.case_reads(), len(self.case_creates()), self.counters()), (1, 1, (1, 1, 1, 1)))
            self.assertEqual(self.actual_run().raw_response[job.PROGRESS_KEY]["state"], "final_applied")
        with self.subTest(phase="committed_read_model_owner"):
            self.new_scenario(); self.committed_read()
            with self.wire_gate("before_create") as (ready, release, observed):
                # 两worker真实排队于主连接parent锁，释放后竞争同原消息。
                with self.parent_locked_workers(count=2, releases=(release,)) as state:
                    fixture_requirement(ready.wait(8), "唯一owner必须在真实CAS+slot提交后抵达wire")
                    progress = deepcopy(self.actual_run().raw_response[job.PROGRESS_KEY])
                    fixture_requirement(progress["state"] == "model_started" and self.counters() == (1, 1, 1, 1),
                                        "单owner预留的真实前置")
                    self.no_business_locks(observed["pid"])
                    fixture_requirement(state["finished"].wait(8), "败者须在winner wire暂停期间退出")
                    self.assertEqual(self.actual_run().raw_response[job.PROGRESS_KEY], progress,
                                     "并发败者不能blocked/close活跃赢家")
                    self.budget.refresh_from_db()
                    self.assertEqual(self.budget.state, "open")
                    release.set()
                self.workers_clean(state)
            self.assertEqual(sum(r.get("translated") is True for r in state["results"]), 1, state["results"])
            self.assertEqual((self.case_reads(), len(self.case_creates()), self.counters()), (1, 1, (1, 1, 1, 1)))
            final = self.actual_run().raw_response[job.FINAL_KEY]; before = self.business_snapshot()
            repeated = self.case_consume()
            self.assertEqual(repeated.get("final_receipt"), final)
            self.assertEqual(self.business_snapshot(), before)
            self.assertEqual((self.case_reads(), len(self.case_creates())), (1, 1))
            self.assertEqual(NotificationLog.objects.count(), 0)

    def test_storage_failures_keep_commit_boundaries_and_free_checkpoint_resume(self):
        self.new_scenario(register=False); before = self.business_snapshot()
        with self.storage_fault("plan") as hits:
            with self.assertRaises(OperationalError):self.register()
        fixture_requirement(hits == ["plan"], "必须命中指定存储层而非setup错误")
        self.assertEqual(self.business_snapshot(), before)
        self.assertEqual((self.case_reads(), self.case_creates(), self.counters()), (0, [], (0, 0, 0, 0)))
        expected = {"read_reserve": (0, 0, 0, 0), "read_result": (1, 0, 1, 0),
                    "model_attempt": (1, 0, 1, 0), "model_cas": (1, 0, 1, 0),
                    "usage": (1, 1, 1, 1), "checkpoint": (1, 1, 1, 1),
                    "checkpoint_progress": (1, 1, 1, 1), "final_article": (1, 1, 1, 1),
                    "final_run": (1, 1, 1, 1)}
        for stage, counters in expected.items():
            with self.subTest(storage=stage):
                self.new_scenario()
                error = ro.ReadonlyAuditFailure if stage.startswith("read_") else (
                    OperationalError if stage.startswith("final_") else recovery.ManagedTranslationAuditFailure)
                with self.storage_fault(stage) as hits:
                    with self.assertRaises(error) as raised:self.case_consume()
                fixture_requirement(hits == [stage], "必须实际命中唯一有限存储故障: " + stage)
                if not stage.startswith("final_"):
                    self.assertIsInstance(raised.exception.__cause__, (IntegrityError, OperationalError))
                    self.assertIn(stage, str(raised.exception.__cause__))
                    audit_stage = {"read_reserve": "admission", "read_result": "result_commit",
                                   "model_attempt": "reserve", "model_cas": "reserve", "usage": "usage",
                                   "checkpoint": "checkpoint", "checkpoint_progress": "checkpoint"}
                    self.assertEqual(raised.exception.stage, audit_stage[stage])
                else:self.assertIn(stage, str(raised.exception))
                self.assertEqual(self.counters(), counters)
                self.assert_not_applied()
                run = self.actual_run(); progress = run.raw_response[job.PROGRESS_KEY]
                if stage in {"model_attempt", "model_cas"}:
                    self.assertEqual(progress["state"], "read_ready")
                    self.assertIsNone(progress["model_owner_token"])
                    self.assertEqual(len(self.case_creates()), 0)
                if stage in {"usage", "checkpoint", "checkpoint_progress"}:
                    self.assertNotIn(recovery.RESULT_KEY, run.raw_response)
                    self.assertEqual(progress["state"], "model_started")
                if stage in {"final_article", "final_run"}:
                    fixture_requirement(progress["state"] == "checkpoint_saved" and recovery.RESULT_KEY in run.raw_response,
                                        "免费apply必须基于真实已提交checkpoint")
                    checkpoint = deepcopy(run.raw_response[recovery.RESULT_KEY]); creates = len(self.case_creates())
                    resumed = self.case_consume()
                    self.assertTrue(resumed.get("translated"), resumed)
                    self.assertEqual(self.actual_run().raw_response[recovery.RESULT_KEY], checkpoint)
                    self.assertEqual((self.case_reads(), len(self.case_creates()), self.counters()), (1, creates, (1, 1, 1, 1)))
        self.new_scenario()
        with self.checkpoint_commit_gate(exit_after=True):
            with self.assertRaises(CommittedFixtureExit):self.case_consume()
        fixture_requirement(self.actual_run().raw_response[job.PROGRESS_KEY]["state"] == "checkpoint_saved",
                            "提交后退出必须来自真实DB checkpoint")
        raw = deepcopy(self.actual_run().raw_response); count = len(self.case_creates())
        self.assertTrue(self.case_consume().get("translated"))
        self.assertEqual(self.actual_run().raw_response[recovery.RESULT_KEY], raw[recovery.RESULT_KEY])
        self.assertEqual((self.case_reads(), len(self.case_creates()), self.counters()), (1, count, (1, 1, 1, 1)))
        # 控制键/provenance metadata注入必须全次拒绝；普通registered helper不绕过私有consumer。
        for key in (job.PLAN_KEY, job.PROGRESS_KEY, job.FINAL_KEY, job.PREFIX + "unknown_v99",
                    recovery.CLAIM_KEY, recovery.RESULT_KEY, job.PROVENANCE_KEY):
            with self.subTest(metadata=key):
                before = self.business_snapshot()
                with self.assertRaises(recovery.TranslationCheckpointError):job.business_metadata({"provider":"offline", key:{}})
                self.assertEqual(self.business_snapshot(), before)
        valid = job.decode_control(self.actual_run().raw_response)
        bad_controls = []
        for field, value in (("revision", True), ("revision", 0.0), ("state", "unknown-v99")):
            altered = deepcopy(valid); altered[job.PROGRESS_KEY][field] = value
            bad_controls.append(altered)
        altered = deepcopy(valid); altered[job.PROGRESS_KEY].pop("revision"); bad_controls.append(altered)
        altered = deepcopy(valid); altered[job.PROGRESS_KEY]["extra"] = 1; bad_controls.append(altered)
        for field, value in (("claim_execution_uuid", "not-a-uuid"), ("input_sha256", "invalid"),
                             ("deadline_at", "2026-10-06T00:00:00")):
            altered = deepcopy(valid); altered[job.PLAN_KEY]["payload"]["identity"][field] = value
            altered[job.PLAN_KEY]["payload_sha256"] = job._sha(altered[job.PLAN_KEY]["payload"])
            bad_controls.append(altered)
        altered = deepcopy(valid); altered[job.PLAN_KEY]["payload_sha256"] = "0" * 64; bad_controls.append(altered)
        altered = deepcopy(valid); altered[job.PREFIX + "unknown_v99"] = {}; bad_controls.append(altered)
        altered = deepcopy(valid); altered[job.PLAN_KEY]["payload"]["identity"]["provider"] = "x" * 2049
        bad_controls.append(altered)
        altered = deepcopy(valid); altered[job.PROGRESS_KEY]["extra"] = [None] * 1025; bad_controls.append(altered)
        altered = deepcopy(valid); nested = None
        for _ in range(10):nested = [nested]
        altered[job.PROGRESS_KEY]["extra"] = nested; bad_controls.append(altered)
        for index, altered in enumerate(bad_controls):
            with self.subTest(codec=index):
                before = self.business_snapshot()
                with self.assertRaises(job.RegisteredJobRefusal):job.decode_control(altered)
                self.assertEqual(self.business_snapshot(), before)
        with self.assertRaises(job.RegisteredJobRefusal):
            job.decode_control_json('{"m02_readonly_plan_v1":{},"m02_readonly_plan_v1":{}}')
        with self.assertRaises(job.RegisteredJobRefusal):job.decode_control_json("x" * 16385)
        checkpoint = self.actual_run().raw_response[recovery.RESULT_KEY]
        with self.assertRaises(recovery.TranslationCheckpointError):
            recovery.decode_translation_checkpoint(checkpoint, self.article.pk, self.envelope.run_id, self.envelope.claimed_at)
        self.new_scenario()
        original_plan = deepcopy(self.plan)
        injected = {**self.payload, job.PLAN_KEY: {"untrusted": 1}, job.PROGRESS_KEY: {},
                    job.FINAL_KEY: {}, recovery.CLAIM_KEY: {}, recovery.RESULT_KEY: {}, job.PROVENANCE_KEY: {}}
        result = self.case_consume([{"content": json.dumps(injected), "usage": USAGE}])
        self.assertTrue(result.get("translated"), result)
        self.assertEqual(self.actual_run().raw_response[job.PLAN_KEY], original_plan)
        self.assertEqual(self.actual_run().raw_response[job.FINAL_KEY], result["final_receipt"])
        self.assertEqual(self.counters(), (1, 1, 1, 1))
        self.new_scenario()
        run = self.actual_run(); before = self.business_snapshot()
        with self.case_scope():
            _, _, _, refusal = recovery.prepare_translation_claim(self.article.pk, run.pk,
                self.envelope.claimed_at, suppress_automation=True)
        self.assertEqual(refusal, "registered_job_wrapper_required")
        self.assertEqual(self.business_snapshot(), before)
        self.assertEqual(NotificationLog.objects.count(), 0)


class BusinessMetadataBoundaryTests(unittest.TestCase):
    """执行真实纯函数源码；无需导入DB/SDK，集成用例仍由原类负责。"""

    def setUp(self):
        import ast
        import math
        from dataclasses import asdict, dataclass
        from pathlib import Path
        from types import SimpleNamespace
        root = Path(__file__).resolve().parent / "services"

        def load(path, names, namespace):
            parsed = ast.parse(path.read_text())
            selected = [node for node in parsed.body if getattr(node, "name", None) in names]
            self.assertEqual({node.name for node in selected}, set(names))
            exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
            return namespace

        codec_globals = {"json": json, "math": math}
        for node in ast.parse((root / "translation_recovery.py").read_text()).body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in {"RESULT_MAX_DEPTH", "RESULT_MAX_BYTES", "CLAIM_KEY", "RESULT_KEY"}):
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(root / "translation_recovery.py"), "exec"), codec_globals)
        codec = load(root / "translation_recovery.py", {"TranslationCheckpointError", "_checkpoint_json"}, codec_globals)
        recovery = SimpleNamespace(**codec)
        service_path = root / "managed_readonly_translation.py"
        available = {getattr(node, "name", None) for node in ast.parse(service_path.read_text()).body}
        names = {"business_metadata", "_business_metadata_without_reserved_keys", "ordinary_business_metadata"} & available
        service_globals = {"json": json, "recovery": recovery}
        for node in ast.parse(service_path.read_text()).body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in {"PROVENANCE_KEY", "PREFIX"}):
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(service_path), "exec"), service_globals)
        service = load(service_path, names, service_globals)
        self.reserved_keys = (recovery.CLAIM_KEY, recovery.RESULT_KEY, service["PROVENANCE_KEY"],
                              *(service["PREFIX"] + name for name in ("plan_v1", "progress_v1", "final_v1", "future_v99")))
        self.strict = service["business_metadata"]
        # 在修复前对实际ordinary原入口取得RED；修复后使用新的明确边界。
        self.ordinary = service.get("ordinary_business_metadata", self.strict)
        self.error = codec["TranslationCheckpointError"]
        terms = load(root / "terms.py", {"RecognizedHorseName", "serialize_recognized_horse_names"},
                     {"dataclass": dataclass, "asdict": asdict, "__name__": __name__})
        self.horse = terms["RecognizedHorseName"]
        self.serialize = terms["serialize_recognized_horse_names"]

    def test_real_recognized_horse_serializer_tuple_is_ordinary_json_array(self):
        horse = self.horse(name_ja="Brilliant", source="term", matched_text="Brilliant", confidence=100,
                           external_horse_ids=[], primary_external_horse_id="", needs_preserve=True,
                           has_translation=True, first_position=0, detection_reason="horse_context",
                           conflict_flags=[], matched_span=(0, 9))
        metadata = {"recognized_horse_names": self.serialize([horse]), "model": "offline"}
        self.assertIs(type(metadata["recognized_horse_names"][0]["matched_span"]), tuple)
        result = self.ordinary(metadata)
        self.assertEqual(result["recognized_horse_names"][0]["matched_span"], [0, 9])
        self.assertIs(type(metadata["recognized_horse_names"][0]["matched_span"]), tuple)

    def test_ordinary_json_is_detached_and_preserves_scalar_types(self):
        metadata = {"usage": {"count": 1, "known": True, "cost": 0.5}, "terms": ["Brilliant"], "empty": None}
        result = self.ordinary(metadata)
        self.assertIs(type(result["usage"]["count"]), int)
        self.assertIs(type(result["usage"]["known"]), bool)
        result["terms"].append("other")
        self.assertEqual(metadata["terms"], ["Brilliant"])

    def test_reserved_control_domains_are_rejected_by_both_boundaries(self):
        for key in self.reserved_keys:
            for boundary in (self.ordinary, self.strict):
                with self.subTest(key=key, boundary=boundary.__name__):
                    with self.assertRaisesRegex(self.error, "reserved metadata overwrite"):
                        boundary({"provider": "offline", key: {}})

    def test_invalid_top_level_metadata_and_nonstring_keys_are_rejected(self):
        for metadata in ([], "provider", {1: "not a string key"}, {True: "boolean key"}):
            for boundary in (self.ordinary, self.strict):
                with self.subTest(metadata=metadata, boundary=boundary.__name__):
                    with self.assertRaisesRegex(self.error, "reserved metadata invalid"):
                        boundary(metadata)
        self.assertEqual(self.ordinary(None), {})

    def test_nonjson_objects_cycles_and_nonfinite_values_are_rejected(self):
        cycle = {}; cycle["cycle"] = cycle
        for metadata in ({"value": object()}, {"value": {1}}, {"value": float("nan")},
                         {"value": float("inf")}, cycle):
            for boundary in (self.ordinary, self.strict):
                with self.subTest(boundary=boundary.__name__):
                    with self.assertRaises(self.error):
                        boundary(metadata)

    def test_private_checkpoint_still_rejects_tuple_metadata(self):
        with self.assertRaisesRegex(self.error, "checkpoint value type"):
            self.strict({"matched_span": (0, 9)})

    def test_private_checkpoint_retains_depth_and_size_limits(self):
        deep = {}; cursor = deep
        for _ in range(34):
            cursor["child"] = {}; cursor = cursor["child"]
        for metadata, reason in ((deep, "checkpoint too deep"),
                                 ({"value": "x" * (2 * 1024 * 1024)}, "checkpoint too large")):
            with self.assertRaisesRegex(self.error, reason):
                self.strict(metadata)

    def test_private_checkpoint_accepts_original_finite_json(self):
        metadata = {"provider": "offline", "usage": {"known": True, "count": 1}, "terms": ["Brilliant"]}
        self.assertEqual(self.strict(metadata), metadata)

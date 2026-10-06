"""B043：3个原RED与9个真实隔离边界；运行必须由ROOT绑定固定SHA/PG窗口。"""

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import hashlib
import time
from threading import Event, Thread
from uuid import uuid4
from unittest.mock import patch

from django.db import DatabaseError, IntegrityError, OperationalError, connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from stable.models import (NewsArticle, TranslationRun, TaskExecutionLog, NotificationLog, RacingRegion, SourceLanguage, TermEntry, TermType,
                           TranslationRequestAttempt, TranslationRetryBudget)
from stable.services import translation as translation
from stable.services import translation_recovery as recovery
from stable.services import translation_retry_budget as core
from stable.services.terms import resolve_article_entities_for_article
from stable.tasks import translate_article_task
from stable.test_translation_failure_recovery_change import article_for_retry


NOW = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
NORMAL_PAYLOAD = {"title_zh": "马房动态", "body_zh": "拍卖后仍有充足时间决定。", "push_summary_zh": "马房动态。"}


def fixture_requirement(condition, message):
    if not condition:
        raise RuntimeError("B043 fixture/interface prerequisite: " + message)


class ForbiddenRealSDK(BaseException):
    """外部构造防线；出现即前置失败，不算目标业务RED。"""


@override_settings(
    TRANSLATION_AUTO_RETRY_ENABLED=True, TRANSLATION_AUTO_RETRY_BATCH_SIZE=1,
    TRANSLATION_AUTO_RETRY_JITTER_SECONDS=0, TRANSLATION_STALE_AFTER_SECONDS=1800,
    TRANSLATION_PROVIDER="dummy", TRANSLATION_MODEL="offline-only", TRANSLATION_MAX_ATTEMPTS=2,
    ENGLISH_TERM_CONTEXT_MODE="enforce", TRANSLATION_UNKNOWN_HORSE_LIMIT=20,
    AUTOMATION_ENABLED=False, TRANSLATION_FAILURE_EMAIL_ENABLED=False,
    TRANSLATION_FAILURE_NOTIFY_EMAILS=[],
)
class ManagedTranslationBudgetConsumerFixture(TransactionTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = self.stack.enter_context(patch("django.utils.timezone.now", return_value=NOW))
        # 只在外部SDK/broker边界防止真实调用；不替换业务provider或审批/审计函数。
        self.constructor = self.stack.enter_context(patch.object(
            translation, "OpenAI", side_effect=ForbiddenRealSDK("offline bound constructed OpenAI"),
        ))
        self.article = article_for_retry(
            source_article_id="b043-offline-consumer", translation_next_retry_at=NOW,
            racing_region=RacingRegion.UNITED_STATES, title_ja="Stable update",
            body_ja_raw="There is more than enough time to decide after the sale.",
            body_ja_normalized="There is more than enough time to decide after the sale.",
        )
        self.budget = None
        self.identity = None

    def fixture_preflight(self, *, person=False):
        """真实前置；失败必须报告fixture/interface ERROR，不充作预算业务RED。"""
        fixture_requirement(connection.vendor == "postgresql", "仅ROOT指定官方PG窗口")
        fixture_requirement(not connection.in_atomic_block, "fixture不能有外层atomic")
        if person:
            self.term = TermEntry.objects.create(
                term_type=TermType.JOCKEY, source_language=SourceLanguage.ENGLISH,
                racing_region=RacingRegion.UNITED_STATES, source_ja="Irad Ortiz Jr.",
                target_zh="奥天信", priority=100,
            )
            self.article.title_ja = "Stewards review the incident"
            self.article.body_ja_raw = "Jockey Irad Ortiz Jr. was knocked off balance while riding Mindframe."
            self.article.body_ja_normalized = self.article.body_ja_raw
            self.article.save(update_fields=["title_ja", "body_ja_raw", "body_ja_normalized", "updated_at"])
            resolution = resolve_article_entities_for_article(self.article)
            fixture_requirement(self.term.pk in resolution.accepted_term_ids, "人物fixture必须进入真实术语识别")
        source_sha = recovery.translation_input_sha256(self.article)
        identity = core.BudgetIdentity(
            "managed_translation_retry", self.article.source_site, self.article.source_article_id,
            source_sha, "b" * 64, "offline-synthetic", "offline-only",
            article_pk_snapshot=self.article.pk,
        )
        decision = core.resolve_budget(identity, mode="offline_test", now=NOW, initial_contract={
            "request_limit": 2, "opened_at": NOW, "deadline_at": NOW + timedelta(minutes=30),
            "policy_snapshot": {"mode": "offline_test", "version": 1},
            "baseline_receipt": {"kind": "synthetic_no_prior_consumption"},
        })
        fixture_requirement(decision.allowed, str(decision))
        self.budget = TranslationRetryBudget.objects.get(pk=decision.budget_pk)
        self.identity = replace(identity, operation_uuid=decision.operation_uuid)
        self.assertEqual(self.budget.requests_reserved, 0)
        self.assertEqual(self.budget.request_attempts.count(), 0)
        self.assertEqual(self.budget.source_sha256, source_sha)
        self.assertIsNone(recovery._current_offline_budget_binding())
        self.assertIsNone(translation._offline_sdk_binding.get())

    def consume(self, fake, *, suppress=True):
        with recovery._offline_budget_scope(self.identity):
            with translation._offline_sdk_dependency(fake):
                with patch.object(recovery.translate_article_task, "delay") as broker:
                    dispatched = recovery.dispatch_due_translation_retries(now=NOW)
                fixture_requirement(dispatched.dispatched_ids == [self.article.pk], "selector前置失败")
                fixture_requirement(broker.call_count == 1, "broker捕获数量不符")
                args, kwargs = broker.call_args
                kwargs["suppress_automation"] = suppress
                return translate_article_task.run(*args, **kwargs)

    def fake(self, script):
        return translation._ClosedOfflineSDKClient(script, budget_pk=self.budget.pk)

    def assert_interface_clean(self, fake):
        self.constructor.assert_not_called()
        self.assertTrue(fake._closed)
        self.assertIsNone(recovery._current_offline_budget_binding())
        self.assertIsNone(translation._offline_sdk_binding.get())
        fixture_requirement(bool(fake.trace), "真实_request_completion必须抵达封闭fake")
        self.assertTrue(all(not event["in_atomic_block"] for event in fake.trace))


    def fresh_input(self):
        self.clock.return_value = NOW
        self.article = article_for_retry(source_article_id="b043-" + str(uuid4()), translation_next_retry_at=NOW,
            racing_region=RacingRegion.UNITED_STATES, title_ja="Stable update",
            body_ja_raw="There is more than enough time to decide after the sale.",
            body_ja_normalized="There is more than enough time to decide after the sale.")
        self.fixture_preflight()

    def prepared_claim(self):
        with recovery._offline_budget_scope(self.identity):
            claim = recovery.claim_translation_retry(self.article.pk, expected_due_at=NOW, now=NOW)
            self.assertTrue(claim.claimed, claim)
            article, run, checkpoint, reason = recovery.prepare_translation_claim(
                self.article.pk, claim.run_id, claim.claimed_at, suppress_automation=True)
        self.assertEqual(reason, "")
        self.assertIsNone(checkpoint)
        return article, run, claim.claimed_at

    def reconcile(self, attempt):
        receipt = {"kind": "synthetic_offline_usage_v1", "budget_uuid": str(self.budget.budget_uuid),
                   "attempt_pk": attempt.pk, "usage_sha256": hashlib.sha256(json.dumps(
                       USAGE, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        decision = core.record_usage(budget_pk=self.budget.pk, attempt_pk=attempt.pk, mode="offline_test",
                                     usage_report=USAGE, receipt=receipt)
        self.assertTrue(decision.allowed, decision)

    def real_reserve(self, run, stamp, index=1):
        with recovery._offline_budget_scope(self.identity):
            return recovery._reserve_managed_translation_request(self.article.pk, run.pk, stamp, index, now=NOW)

    def locked_workers(self, lock_model, lock_pk, action, *, count=1, cross_deadline=False):
        # 用实际独立PG连接和blocking_pids证明锁等待，而非顺序mock。
        pids, errors, results, closed = [], [], [], []
        ready = [Event() for _ in range(count)]
        def worker(index):
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                ready[index].set()
                results.append(action(index))
            except BaseException as exc:
                errors.append(exc)
            finally:
                connections.close_all()
                closed.append(connections["default"].connection is None)
        threads = [Thread(target=worker, args=(i,), daemon=True) for i in range(count)]
        try:
            with transaction.atomic():
                lock_model.objects.select_for_update().get(pk=lock_pk)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    owner = cursor.fetchone()[0]
                for thread in threads:
                    thread.start()
                for event in ready:
                    self.assertTrue(event.wait(8), "PG worker未连接")
                rows, verified = [], []
                stop = time.monotonic() + 8
                while time.monotonic() < stop:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pid, wait_event_type, pg_blocking_pids(pid) "
                            "FROM pg_stat_activity WHERE pid = ANY(%s)", [pids + [owner]])
                        rows = cursor.fetchall()
                    graph = {pid: (wait_type, blockers) for pid, wait_type, blockers in rows}
                    allowed = set(pids) | {owner}
                    def reaches_owner(pid, path):
                        if pid == owner:
                            return owner in graph and connection.in_atomic_block
                        if pid in path or pid not in graph:
                            return False
                        wait_type, blockers = graph[pid]
                        return (wait_type == "Lock" and bool(blockers)
                                and all(blocker in allowed and reaches_owner(blocker, path | {pid})
                                        for blocker in blockers))
                    verified = [pid for pid in pids if reaches_owner(pid, set())]
                    if len(set(pids)) == count and len(verified) == count:
                        break
                    time.sleep(.025)
                # 断言前保留完整指定worker/owner图；允许真实PG排队的传递边，拒绝陌生节点和循环。
                print("B043_ACTUAL_LOCK", lock_model.__name__, "owner", owner, "workers", pids,
                      "pid_wait_type_blockers", rows, "verified_to_owner", verified, flush=True)
                self.assertEqual(len(set(pids)), count, "须所有worker使用独立PG连接")
                self.assertEqual(len(verified), count, "须所有worker真实Lock等待且全部阻塞边最终到持锁owner")
                if cross_deadline:
                    self.clock.return_value = NOW + timedelta(minutes=31)
        finally:
            for thread in threads:
                thread.join(12)
            self.assertFalse(any(t.is_alive() for t in threads), "worker必须在窗口内退出")
        self.assertEqual(closed, [True] * count)
        self.assertEqual(len(set(pids)), count)
        return results, errors


class ManagedTranslationBudgetConsumerRedTests(ManagedTranslationBudgetConsumerFixture):
    def test_each_create_observes_committed_reservation(self):
        self.fixture_preflight()
        fake = self.fake([{"content": json.dumps(NORMAL_PAYLOAD, ensure_ascii=False), "usage": USAGE}])
        result = self.consume(fake)
        self.assert_interface_clean(fake)
        fixture_requirement(result.get("translated"), "合法译文应完成真实checkpoint/终态，非接口错误")
        creates = [event for event in fake.trace if event["event"] == "create"]
        self.assertEqual(len(creates), 1)
        # 当前旧消费者fake入场为0；必须是业务FAIL，不在fake内抛断言。
        self.assertEqual(creates[0]["requests_reserved"], 1, "create前没有committed reservation")
        self.assertEqual(len(creates[0]["attempts"]), 1)
        self.assertEqual(creates[0]["attempts"][0]["state"], "reserved")
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 1)
        self.assertEqual(self.budget.request_attempts.get().state, "usage_reported")
        self.assertEqual(NotificationLog.objects.count(), 0)
        self.fresh_input()
        retry_payload = {**NORMAL_PAYLOAD, "body_zh": ""}
        fake = self.fake([{"content": json.dumps(retry_payload, ensure_ascii=False), "usage": USAGE,
                           "wait_for_receipt": True},
                          {"content": json.dumps(NORMAL_PAYLOAD, ensure_ascii=False), "usage": USAGE}])
        results, errors = [], []
        def worker():
            try:
                results.append(self.consume(fake))
            except BaseException as exc:
                errors.append(exc)
            finally:
                connections.close_all()
        thread = Thread(target=worker, daemon=True)
        thread.start()
        try:
            self.assertTrue(fake.choices_ready.wait(8), "真实usage提交后须抵达choices同步门")
            attempt = self.budget.request_attempts.get()
            self.assertEqual(attempt.state, "usage_reported")
            self.assertEqual(attempt.usage_report, USAGE)
            self.reconcile(attempt)  # 独立fixture真实写账，不让response供应receipt。
        finally:
            fake.choices_release.set()
            thread.join(12)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(results[0].get("translated"), results)
        creates = [event for event in fake.trace if event["event"] == "create"]
        self.assertEqual([e["requests_reserved"] for e in creates], [1, 2])
        attempts = list(self.budget.request_attempts.order_by("seq"))
        self.assertEqual(len({a.claim_execution_uuid for a in attempts}), 1)
        self.assertEqual([a.provider_attempt_index for a in attempts], [1, 2])
        self.assertEqual(attempts[0].reconciliation_state, "offline_reconciled")
        self.assertEqual(attempts[1].state, "usage_reported")
        self.assert_interface_clean(fake)

    def test_usage_is_committed_before_invalid_json(self):
        self.fixture_preflight()
        fake = self.fake([{"content": "{invalid-json", "usage": USAGE}])
        with self.assertRaises(json.JSONDecodeError):
            self.consume(fake)
        self.assert_interface_clean(fake)
        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_retry_count, 1, "原JSON真实失败必须计一次")
        choices = [event for event in fake.trace if event["event"] == "choices"]
        self.assertEqual(len(choices), 1)
        self.assertEqual(len(choices[0]["attempts"]), 1, "解析JSON前usage没有独立journal")
        self.assertEqual(choices[0]["attempts"][0]["state"], "usage_reported")
        self.assertEqual(choices[0]["attempts"][0]["usage_report"], USAGE)
        attempt = TranslationRequestAttempt.objects.get(budget=self.budget)
        self.assertEqual(attempt.usage_report, USAGE)
        self.assertIsNone(self.article.translation_next_retry_at)
        self.assertEqual(NotificationLog.objects.count(), 0)

    def test_quality_retry_cannot_create_again_with_unknown_usage(self):
        self.fixture_preflight(person=True)
        bad = {"title_zh": "裁判复核事故", "body_zh": "小伊拉德·奥尔蒂斯策骑Mindframe时失去平衡。",
               "push_summary_zh": "小伊拉德·奥尔蒂斯在事故中失去平衡。"}
        good = {"title_zh": "裁判复核事故", "body_zh": "骑师__UMA_TERM_1__策骑Mindframe时失去平衡。",
                "push_summary_zh": "__UMA_TERM_1__在事故中失去平衡。"}
        fake = self.fake([{"content": json.dumps(bad, ensure_ascii=False)},
                          {"content": json.dumps(good, ensure_ascii=False), "usage": USAGE}])
        result = self.consume(fake)
        self.assert_interface_clean(fake)
        creates = [event for event in fake.trace if event["event"] == "create"]
        self.assertIn("__UMA_TERM_1__", creates[0]["messages"][1]["content"], "真实人物placeholder未进入prompt")
        if len(creates) == 2:
            self.assertIn("上一版", creates[1]["messages"][1]["content"], "未抵达真实质量retry分支")
        self.assertEqual(len(creates), 1, "首轮usage未知后仍发起第二次create")
        self.assertTrue(result.get("skipped"), result)
        self.assertFalse(result.get("translated"), result)
        self.assertEqual(result.get("reason"), "usage_unknown")
        self.article.refresh_from_db()
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 1)
        self.assertEqual(self.budget.request_attempts.get().state, "unknown")
        self.assertEqual(self.article.translation_status, "failed")
        self.assertEqual(self.article.translation_retry_count, 0)
        self.assertIsNone(self.article.translation_next_retry_at)
        self.assertIsNone(self.article.translation_started_at)
        self.assertIsNone(self.article.translation_retry_exhausted_at)
        run = self.article.translation_runs.get()
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.raw_response[recovery.CLAIM_KEY]["phase"], "interrupted")
        self.assertEqual(NotificationLog.objects.count(), 0)


class ManagedTranslationBudgetConsumerBoundaryTests(ManagedTranslationBudgetConsumerFixture):
    def test_timeout_and_stale_new_claim_keep_unknown_without_second_create(self):
        self.fixture_preflight()
        fake = self.fake([{"error": "timeout"}])
        with self.assertRaises(TimeoutError):
            self.consume(fake)
        self.assert_interface_clean(fake)
        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_retry_count, 1)
        self.assertEqual(self.article.translation_error_category, "transient_timeout")
        self.assertIsNone(self.article.translation_next_retry_at)
        attempt = self.budget.request_attempts.get()
        self.assertEqual(attempt.state, "reserved")
        self.article.translation_next_retry_at = NOW
        self.article.save(update_fields=["translation_next_retry_at"])
        with recovery._offline_budget_scope(self.identity), patch.object(recovery.translate_article_task, "delay") as broker:
            selected = recovery.dispatch_due_translation_retries(now=NOW)
        self.assertEqual(selected.dispatched_ids, [])
        broker.assert_not_called()
        self.article.refresh_from_db()
        self.assertIsNone(self.article.translation_next_retry_at)
        self.assertEqual(self.article.translation_runs.count(), 1)
        self.assertEqual(self.article.translation_retry_count, 1)
        snapshot = NewsArticle.objects.values().get(pk=self.article.pk)
        with recovery._offline_budget_scope(self.identity):
            refused = translate_article_task.run(self.article.pk)
        self.assertEqual(refused["reason"], "bound_claim_identity_missing")
        self.assertEqual(NewsArticle.objects.values().get(pk=self.article.pk), snapshot)
        self.assertEqual(NotificationLog.objects.count(), 0)
        self.fresh_input()
        original_deadline = self.budget.deadline_at
        fake = self.fake([{"error": "exit"}])
        with self.assertRaises(SystemExit):
            self.consume(fake)
        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_status, "translating")
        self.clock.return_value = NOW + timedelta(minutes=31)
        with recovery._offline_budget_scope(self.identity):
            self.assertTrue(recovery.recover_one_stale_translation(self.article.pk,
                expected_started_at=NOW, now=self.clock.return_value))
            with patch.object(recovery.translate_article_task, "delay") as broker:
                selected = recovery.dispatch_due_translation_retries(now=self.clock.return_value)
        self.assertEqual(selected.dispatched_ids, [])
        broker.assert_not_called()
        self.article.refresh_from_db()
        self.budget.refresh_from_db()
        self.assertEqual(self.article.translation_retry_count, 0)
        self.assertIsNone(self.article.translation_next_retry_at)
        self.assertEqual(self.budget.requests_reserved, 1)
        self.assertEqual(self.budget.deadline_at, original_deadline)
        self.assertEqual(self.article.translation_runs.get().raw_response[recovery.CLAIM_KEY]["phase"], "interrupted")
        self.assertEqual(len([t for t in fake.trace if t["event"] == "create"]), 1)

    def test_two_consumers_last_slot_wait_on_root_and_authorize_one_create(self):
        self.fixture_preflight()
        # 正常第一请求独立对账；最后一槽由两个真实provider争用同claim/index。
        seeded = core.reserve_request(self.identity, mode="offline_test", now=NOW,
            claim_execution_uuid=uuid4(), claimed_at=NOW, provider_attempt_index=1)
        self.assertTrue(seeded.allowed)
        self.reconcile(TranslationRequestAttempt.objects.get(pk=seeded.attempt_pk))
        article, run, stamp = self.prepared_claim()
        fakes = [self.fake([{"content": json.dumps(NORMAL_PAYLOAD, ensure_ascii=False), "usage": USAGE}]) for _ in range(2)]
        def action(index):
            article = NewsArticle.objects.get(pk=self.article.pk)
            current_run = TranslationRun.objects.get(pk=run.pk)
            with recovery._offline_budget_scope(self.identity), translation._offline_sdk_dependency(fakes[index]):
                return translation.translate_article(article, managed_run=current_run)
        results, errors = self.locked_workers(TranslationRetryBudget, self.budget.pk, action, count=2)
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], recovery.ManagedTranslationBudgetBlocked)
        self.assertEqual(errors[0].core_reason, "request_already_reserved")
        self.assertEqual(sum(len([t for t in f.trace if t["event"] == "create"]) for f in fakes), 1)
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 2)
        self.assertEqual(self.budget.request_attempts.count(), 2)
        self.assertTrue(all(f._closed for f in fakes))
        self.constructor.assert_not_called()

    def test_lock_wait_crossing_effective_deadline_never_calls_sdk(self):
        self.fixture_preflight()
        for model in (TranslationRetryBudget, NewsArticle, TranslationRun):
            with self.subTest(model=model.__name__):
                if model is not TranslationRetryBudget:
                    self.fresh_input()
                article, run, stamp = self.prepared_claim()
                fake = self.fake([{"content": json.dumps(NORMAL_PAYLOAD, ensure_ascii=False), "usage": USAGE}])
                def action(index):
                    with recovery._offline_budget_scope(self.identity), translation._offline_sdk_dependency(fake):
                        return translation.translate_article(NewsArticle.objects.get(pk=article.pk),
                                                             managed_run=TranslationRun.objects.get(pk=run.pk))
                pk = self.budget.pk if model is TranslationRetryBudget else article.pk if model is NewsArticle else run.pk
                results, errors = self.locked_workers(model, pk, action, cross_deadline=True)
                self.assertEqual(results, [])
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], recovery.ManagedTranslationBudgetBlocked)
                self.assertEqual(errors[0].core_reason, "claim_expired")
                self.assertEqual(fake.trace, [])
                self.budget.refresh_from_db()
                self.assertEqual(self.budget.requests_reserved, 0)
                self.assertEqual(self.budget.request_attempts.count(), 0)
        self.constructor.assert_not_called()

    def test_checkpoint_resume_with_unreconciled_budget_uses_no_provider_or_slot(self):
        self.fixture_preflight()
        class ExitBeforeTerminal(BaseException):
            pass
        save = TranslationRun.save
        def exit_terminal(instance, *args, **kwargs):
            if instance.status == "success":
                raise ExitBeforeTerminal()
            return save(instance, *args, **kwargs)
        fake = self.fake([{"content": json.dumps(NORMAL_PAYLOAD, ensure_ascii=False), "usage": USAGE}])
        with patch.object(TranslationRun, "save", new=exit_terminal):
            with self.assertRaises(ExitBeforeTerminal):
                self.consume(fake, suppress=False)
        run = self.article.translation_runs.get()
        checkpoint = run.raw_response[recovery.RESULT_KEY]
        self.assertIs(checkpoint["suppress_automation"], False)
        self.assertEqual(self.budget.request_attempts.get().reconciliation_state, "unreconciled")
        self.budget.refresh_from_db()
        before = (self.budget.requests_reserved, self.budget.deadline_at)
        replay_fake = self.fake([{"error": "exit"}])
        from stable.tasks import process_article_automation_task
        with override_settings(AUTOMATION_ENABLED=True), patch.object(process_article_automation_task, "delay") as delivery:
            with recovery._offline_budget_scope(self.identity), translation._offline_sdk_dependency(replay_fake):
                result = translate_article_task.run(self.article.pk, preclaimed_retry=True, claim_run_id=run.pk,
                    claim_started_at=run.raw_response[recovery.CLAIM_KEY]["claimed_at"], suppress_automation=True)
        self.assertTrue(result.get("translated"), result)
        delivery.assert_not_called()
        self.assertEqual(TaskExecutionLog.objects.filter(task_name="process_article_automation").count(), 0)
        self.assertEqual(replay_fake.trace, [])
        self.constructor.assert_not_called()
        run.refresh_from_db()
        self.budget.refresh_from_db()
        self.assertEqual(run.raw_response[recovery.RESULT_KEY], checkpoint)
        self.assertEqual((self.budget.requests_reserved, self.budget.deadline_at), before)
        self.assertEqual(NotificationLog.objects.count(), 0)

    def test_deleted_recreated_source_and_reused_pk_cannot_reset_authority(self):
        self.fixture_preflight()
        article, run, stamp = self.prepared_claim()
        reservation = self.real_reserve(run, stamp)
        self.assertTrue(reservation.allowed)
        old_pk, source_id, operation, deadline = article.pk, article.source_article_id, self.budget.operation_uuid, self.budget.deadline_at
        article.delete()  # 真实collector，Run删而两账独立保留。
        self.assertFalse(TranslationRun.objects.filter(pk=run.pk).exists())
        self.article = article_for_retry(source_article_id=source_id, translation_next_retry_at=NOW)
        self.identity = replace(self.identity, article_pk_snapshot=self.article.pk)
        self.assertNotEqual(self.article.pk, old_pk)
        resolved = core.resolve_budget(self.identity, mode="offline_test", now=NOW)
        self.assertEqual(resolved.reason, "usage_unknown")
        self.assertEqual(resolved.operation_uuid, operation)
        with recovery._offline_budget_scope(self.identity), patch.object(recovery.translate_article_task, "delay") as delivery:
            selected = recovery.dispatch_due_translation_retries(now=NOW)
        self.assertEqual(selected.dispatched_ids, [])
        delivery.assert_not_called()
        self.budget.refresh_from_db()
        self.assertEqual((self.budget.requests_reserved, self.budget.deadline_at), (1, deadline))
        self.assertEqual(TranslationRequestAttempt.objects.get(pk=reservation.attempt_pk).article_pk_snapshot, old_pk)
        foreign = article_for_retry(pk=old_pk, source_article_id="b043-other-source", translation_next_retry_at=NOW)
        identity = replace(self.identity, article_pk_snapshot=old_pk, source_article_id=foreign.source_article_id,
                           source_sha256=recovery.translation_input_sha256(foreign))
        before = NewsArticle.objects.values().get(pk=foreign.pk)
        with recovery._offline_budget_scope(identity):
            denied = recovery.claim_translation_retry(foreign.pk, expected_due_at=NOW, now=NOW)
        self.assertFalse(denied.claimed)
        self.assertEqual(denied.reason, "identity_changed")
        self.assertEqual(NewsArticle.objects.values().get(pk=foreign.pk), before)
        self.assertEqual(TranslationRetryBudget.objects.count(), 1)
        self.constructor.assert_not_called()

    def test_consumer_production_mode_refusal_has_no_legacy_fallback(self):
        self.fixture_preflight()
        article, run, stamp = self.prepared_claim()
        for mode in ("production", "offline_test"):
            with self.subTest(mode=mode), recovery._offline_budget_scope(self.identity, mode=mode):
                fake = self.fake([{"content": json.dumps(NORMAL_PAYLOAD), "usage": USAGE}])
                with translation._offline_sdk_dependency(fake):
                    if mode == "production":
                        with self.assertRaisesRegex(recovery.ManagedTranslationBudgetBlocked, "supported_mode_missing"):
                            translation.translate_article(article, managed_run=run)
                self.assertTrue(fake._closed)
                with self.assertRaisesRegex(recovery.ManagedTranslationBudgetBlocked,
                        "supported_mode_missing" if mode == "production" else "offline_sdk_dependency_missing"):
                    translation.translate_article(article, managed_run=run)
                for foreign in (object(), lambda: object()):
                    with self.assertRaisesRegex(recovery.ManagedTranslationBudgetBlocked, "offline_sdk_dependency_invalid"):
                        with translation._offline_sdk_dependency(foreign):
                            self.fail("foreign/factory不得进入")
                with self.assertRaisesRegex(recovery.ManagedTranslationBudgetBlocked, "offline_sdk_dependency_closed"):
                    with translation._offline_sdk_dependency(fake):
                        self.fail("closed fake不得复用")
                with self.assertRaisesRegex(recovery.ManagedTranslationBudgetBlocked, "offline_scope_already_bound"):
                    with recovery._offline_budget_scope(self.identity):
                        self.fail("不能嵌套")
                binding = recovery._current_offline_budget_binding()
                errors = []
                def wrong_owner():
                    from contextvars import copy_context
                    token = recovery._offline_budget_binding.set(binding)  # fixture仅复制数据模拟跨线程继承。
                    try:
                        translation.get_translation_provider(article=article, managed_run=run)
                    except BaseException as exc:
                        errors.append(exc)
                    finally:
                        recovery._offline_budget_binding.reset(token)
                        connections.close_all()
                thread = Thread(target=wrong_owner, daemon=True)
                thread.start(); thread.join(8)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertEqual(str(errors[0]), "offline_scope_mismatch")
        # 消息/env/JSON仅数据，绝无scope setter。
        import os
        run.raw_response[recovery.CLAIM_KEY]["offline_test"] = True
        run.save(update_fields=["raw_response"])
        with patch.dict(os.environ, {"TRANSLATION_BUDGET_MODE": "offline_test"}):
            self.assertIsNone(recovery._current_offline_budget_binding())
            ordinary = translation.get_translation_provider()
        self.assertIsInstance(ordinary, translation.DummyTranslationProvider)
        with self.assertRaisesRegex(recovery.ManagedTranslationBudgetBlocked, "offline_scope_missing"):
            with translation._offline_sdk_dependency(self.fake([{"error": "exit"}])):
                self.fail("SDK单独不能激活")
        self.assertEqual(self.budget.request_attempts.count(), 0)
        self.constructor.assert_not_called()
        self.assertIsNone(recovery._current_offline_budget_binding())
        self.assertIsNone(translation._offline_sdk_binding.get())

    def test_bound_claim_uuid_policy_source_and_model_changes_do_not_topup(self):
        self.fixture_preflight()
        article, run, stamp = self.prepared_claim()
        reservation = self.real_reserve(run, stamp)
        attempt = TranslationRequestAttempt.objects.get(pk=reservation.attempt_pk)
        self.reconcile(attempt)
        original = json.loads(json.dumps(run.raw_response))
        original_uuid = attempt.claim_execution_uuid
        for kind in ("uuid_changed", "uuid_missing", "budget_reference_changed", "index_reset", "index_jump",
                     "claimed_at_argument", "run_argument", "source_pair", "input_changed"):
            with self.subTest(kind=kind):
                raw = json.loads(json.dumps(original)); claim = raw[recovery.CLAIM_KEY]
                call_stamp, call_run, index = stamp, run, 2
                previous_source, previous_body = article.source_article_id, article.body_ja_normalized
                if kind == "uuid_changed":
                    claim["claim_execution_uuid"] = str(uuid4())
                elif kind == "uuid_missing":
                    del claim["claim_execution_uuid"]
                elif kind == "budget_reference_changed":
                    claim["budget_uuid"] = str(uuid4())
                elif kind == "index_reset":
                    index = 1
                elif kind == "index_jump":
                    index = 3
                elif kind == "claimed_at_argument":
                    call_stamp = (NOW + timedelta(seconds=1)).isoformat()
                elif kind == "run_argument":
                    call_run = TranslationRun.objects.create(article=article, status="started", raw_response={})
                elif kind == "source_pair":
                    article.source_article_id = "b043-renamed-source"
                    article.save(update_fields=["source_article_id"])
                elif kind == "input_changed":
                    article.body_ja_normalized += " Changed."
                    article.save(update_fields=["body_ja_normalized"])
                run.raw_response = raw; run.save(update_fields=["raw_response"])
                before = (NewsArticle.objects.values().get(pk=article.pk), TranslationRun.objects.values().get(pk=run.pk))
                decision = self.real_reserve(call_run, call_stamp, index)
                self.assertFalse(decision.allowed, decision)
                expected = {"uuid_changed": "claim_execution_uuid_changed", "uuid_missing": "claim_execution_uuid_missing",
                    "budget_reference_changed": "bound_claim_identity_missing", "index_reset": "request_already_reserved",
                    "index_jump": "claim_attempt_sequence_changed", "claimed_at_argument": "claim_changed",
                    "run_argument": "claim_changed", "source_pair": "offline_scope_mismatch", "input_changed": "input_changed"}
                self.assertEqual(decision.reason, expected[kind])
                self.assertEqual((NewsArticle.objects.values().get(pk=article.pk), TranslationRun.objects.values().get(pk=run.pk)), before)
                self.budget.refresh_from_db(); attempt.refresh_from_db()
                self.assertEqual(self.budget.requests_reserved, 1)
                self.assertEqual(attempt.claim_execution_uuid, original_uuid)
                self.assertEqual(attempt.reconciliation_state, "offline_reconciled")
                article.source_article_id, article.body_ja_normalized = previous_source, previous_body
                article.save(update_fields=["source_article_id", "body_ja_normalized"])
                if kind == "run_argument":
                    call_run.delete()
        run.raw_response = original; run.save(update_fields=["raw_response"])
        for identity in (replace(self.identity, policy_sha256="c" * 64), replace(self.identity, provider="different")):
            with recovery._offline_budget_scope(identity):
                decision = recovery._reserve_managed_translation_request(article.pk, run.pk, stamp, 2, now=NOW)
            self.assertEqual(decision.reason, "budget_version_changed")
        with override_settings(TRANSLATION_MODEL="changed-model"):
            self.assertEqual(self.real_reserve(run, stamp, 2).reason, "budget_version_changed")
        # 同run消息重投仍旧fence拒绝，不再构造provider。
        fake = self.fake([{"error": "exit"}])
        with recovery._offline_budget_scope(self.identity), translation._offline_sdk_dependency(fake):
            repeated = translate_article_task.run(article.pk, preclaimed_retry=True, claim_run_id=run.pk,
                                                 claim_started_at=stamp, suppress_automation=True)
        self.assertEqual(repeated["reason"], "claim_already_consumed")
        self.assertEqual(fake.trace, [])
        # 合法新claim可随机新UUID，仍同root/history、不充值。先原fence终态结束，再真实领取。
        article.translation_retry_count = 2
        article.translation_retry_exhausted_at = NOW
        article.save(update_fields=["translation_retry_count", "translation_retry_exhausted_at"])
        with recovery._offline_budget_scope(self.identity):
            _, _, stored = recovery._close_bound_budget_failure(article.pk, run.pk, stamp, core_reason="fixture_stop")
        self.assertTrue(stored)
        article.refresh_from_db()
        self.assertEqual((article.translation_retry_count, article.translation_retry_exhausted_at), (2, NOW))
        self.assertIsNone(article.translation_next_retry_at)
        self.assertTrue(recovery.request_manual_translation_retry(article, now=NOW).accepted)
        with recovery._offline_budget_scope(self.identity):
            new_claim = recovery.claim_translation_retry(article.pk, expected_due_at=NOW, now=NOW)
        self.assertTrue(new_claim.claimed)
        new_run = TranslationRun.objects.get(pk=new_claim.run_id)
        self.assertNotEqual(new_run.raw_response[recovery.CLAIM_KEY]["claim_execution_uuid"], str(original_uuid))
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 1)
        self.assertEqual(self.budget.request_attempts.count(), 1)
        self.constructor.assert_not_called()

    def test_reservation_and_usage_write_failure_preserve_atomic_audit(self):
        self.fixture_preflight()
        save = TranslationRequestAttempt.save
        def fail_insert(instance, *args, **kwargs):
            raise IntegrityError("synthetic attempt insert storage fault")
        fake = self.fake([{"content": json.dumps(NORMAL_PAYLOAD), "usage": USAGE}])
        with patch.object(TranslationRequestAttempt, "save", new=fail_insert):
            result = self.consume(fake)
        self.assertEqual(result["reason"], "local_audit_failed")
        self.assertEqual(result["stage"], "reserve")
        self.assertEqual(result["audit_cause_type"], "IntegrityError")
        self.assertIn("synthetic attempt insert", result["audit_cause"])
        self.assertEqual(fake.trace, [])
        self.budget.refresh_from_db(); self.article.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 0)
        self.assertEqual(self.budget.request_attempts.count(), 0)
        self.assertEqual(self.article.translation_retry_count, 0)
        self.assertIsNone(self.article.translation_next_retry_at)
        self.assertEqual(self.article.translation_runs.get().raw_response[recovery.CLAIM_KEY]["phase"], "interrupted")
        from django.db.models.query import QuerySet
        update = QuerySet.update
        def fail_usage(queryset, **values):
            if queryset.model is TranslationRequestAttempt:
                raise OperationalError("synthetic usage storage fault")
            return update(queryset, **values)
        article_save = NewsArticle.save
        def fail_terminal(instance, *args, **kwargs):
            if instance.translation_status == "failed":
                raise OperationalError("synthetic still unwritable terminal")
            return article_save(instance, *args, **kwargs)
        for terminal_unwritable in (False, True):
            with self.subTest(terminal_unwritable=terminal_unwritable):
                self.fresh_input()
                fake = self.fake([{"content": json.dumps(NORMAL_PAYLOAD), "usage": USAGE}])
                with ExitStack() as faults:
                    faults.enter_context(patch.object(QuerySet, "update", new=fail_usage))
                    if terminal_unwritable:
                        faults.enter_context(patch.object(NewsArticle, "save", new=fail_terminal))
                        with self.assertRaises(OperationalError) as raised:
                            self.consume(fake)
                        self.assertIn("still unwritable", str(raised.exception))
                        self.assertIsInstance(raised.exception.__context__, recovery.ManagedTranslationAuditFailure)
                        self.assertIsInstance(raised.exception.__context__.__cause__, OperationalError)
                    else:
                        result = self.consume(fake)
                        self.assertTrue(result["persisted"])
                        self.assertEqual((result["reason"], result["stage"], result["audit_cause_type"]),
                                         ("local_audit_failed", "usage", "OperationalError"))
                self.budget.refresh_from_db(); self.article.refresh_from_db()
                self.assertEqual(self.budget.requests_reserved, 1)
                attempt = self.budget.request_attempts.get()
                self.assertEqual((attempt.state, attempt.usage_report), ("reserved", {}))
                self.assertEqual(self.article.translation_retry_count, 0)
                self.assertEqual(len([e for e in fake.trace if e["event"] == "create"]), 1)
                if terminal_unwritable:
                    self.assertEqual(self.article.translation_status, "translating")
                    self.assertEqual(self.article.translation_started_at, NOW)
                    self.clock.return_value = NOW + timedelta(minutes=31)
                    with recovery._offline_budget_scope(self.identity):
                        self.assertTrue(recovery.recover_one_stale_translation(self.article.pk,
                            expected_started_at=NOW, now=self.clock.return_value))
                    self.article.refresh_from_db()
                self.assertIsNone(self.article.translation_next_retry_at)
                self.assertEqual(self.article.translation_runs.get().raw_response[recovery.CLAIM_KEY]["phase"], "interrupted")
        # 预留前故障且终态也不可写：不得谎称永久已停止或0费用完成。
        self.fresh_input()
        fake = self.fake([{"content": json.dumps(NORMAL_PAYLOAD), "usage": USAGE}])
        with patch.object(TranslationRequestAttempt, "save", new=fail_insert), patch.object(NewsArticle, "save", new=fail_terminal):
            with self.assertRaises(OperationalError) as raised:
                self.consume(fake)
        self.assertIsInstance(raised.exception.__context__, recovery.ManagedTranslationAuditFailure)
        self.assertIsInstance(raised.exception.__context__.__cause__, IntegrityError)
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 0)
        self.assertEqual(self.budget.request_attempts.count(), 0)
        self.assertEqual(fake.trace, [])
        self.constructor.assert_not_called()
        self.assertEqual(NotificationLog.objects.count(), 0)

    def test_unbound_ordinary_force_and_legacy_checkpoint_are_compatible(self):
        self.fixture_preflight()
        self.article.body_zh = "编辑正文"
        self.article.manually_edited_fields = ["body_zh"]
        self.article.save(update_fields=["body_zh", "manually_edited_fields"])
        # 无scope，真实普通Dummy provider沿旧任务路径，账不被激活。
        ordinary = translate_article_task.run(self.article.pk, suppress_automation=True)
        self.assertTrue(ordinary["translated"])
        self.article.refresh_from_db()
        self.assertEqual(self.article.body_zh, "编辑正文")
        self.assertFalse("claim_execution_uuid" in self.article.translation_runs.get().raw_response[recovery.CLAIM_KEY])
        NewsArticle.objects.filter(pk=self.article.pk).update(workflow_status="published", automation_status="published",
            translation_status="translated", translation_next_retry_at=None)
        forced = translate_article_task.run(self.article.pk, force=True, suppress_automation=True)
        self.assertTrue(forced["translated"])
        self.article.refresh_from_db()
        self.assertEqual((self.article.workflow_status, self.article.automation_status), ("published", "published"))
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.requests_reserved, 0)
        # 真实普通构造参数保留；仅外部constructor spy返回惰性对象，无业务翻译patch。
        with patch.object(translation, "OpenAI", return_value=object()) as ctor:
            translation.OpenAICompatibleTranslationProvider(api_key="synthetic", base_url=" https://example.invalid/v1 ")
        ctor.assert_called_once_with(api_key="synthetic", base_url="https://example.invalid/v1")
        self.fresh_input()
        article, run, stamp = self.prepared_claim()
        before = TranslationRun.objects.values().get(pk=run.pk)
        with recovery._offline_budget_scope(self.identity), transaction.atomic():
            denied = recovery._reserve_managed_translation_request(article.pk, run.pk, stamp, 1, now=NOW)
            self.assertEqual(denied.reason, "outer_transaction_forbidden")
            result = translate_article_task.run(article.pk, preclaimed_retry=True, claim_run_id=run.pk, claim_started_at=stamp)
            self.assertEqual(result["reason"], "claim_outer_transaction")
        self.assertEqual(TranslationRun.objects.values().get(pk=run.pk), before)
        self.assertEqual(self.budget.request_attempts.count(), 0)
        self.constructor.assert_not_called()
        # 无预算scope的旧claim/checkpoint免费恢复，无追溯UUID：原39/77回归另列精确135全集。
        self.fresh_input()
        claim = recovery.claim_translation_retry(self.article.pk, expected_due_at=NOW, now=NOW)
        article, run, checkpoint, reason = recovery.prepare_translation_claim(article_id=self.article.pk,
            run_id=claim.run_id, claimed_at=claim.claimed_at, suppress_automation=True)
        self.assertEqual(reason, "")
        result = translation.translate_article(article, managed_run=run)
        checkpoint = recovery.build_translation_checkpoint(article, run, result, suppress_automation=True)
        recovery.save_translation_checkpoint(article.pk, run.pk, claim.claimed_at, checkpoint)
        resumed = translate_article_task.run(article.pk, preclaimed_retry=True, claim_run_id=run.pk,
                                             claim_started_at=claim.claimed_at, suppress_automation=True)
        self.assertTrue(resumed["translated"])
        run.refresh_from_db()
        self.assertNotIn("claim_execution_uuid", run.raw_response[recovery.CLAIM_KEY])
        self.assertEqual(self.budget.requests_reserved, 0)

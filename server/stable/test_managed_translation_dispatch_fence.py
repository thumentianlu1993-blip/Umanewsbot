"""B045 R01：仅隔离合成时钟/broker故障，原领取/释放业务与严格fence真实执行。"""

from datetime import timedelta
from unittest.mock import patch

from django.db import connection

from stable.models import NewsArticle, NotificationLog, TranslationRun
from stable.services import translation, translation_recovery as recovery
from stable.test_managed_translation_budget_consumer import (
    ManagedTranslationBudgetConsumerFixture, NOW, fixture_requirement,
)


class ManagedTranslationDispatchFenceTests(ManagedTranslationBudgetConsumerFixture):
    def test_bound_dispatch_failure_releases_postlock_committed_claim_time(self):
        self.fixture_preflight()
        NewsArticle.objects.filter(pk=self.article.pk).update(translation_retry_count=1)
        t1 = NOW + timedelta(seconds=7)
        self.clock.return_value = t1
        root_before = self.budget.__class__.objects.values().get(pk=self.budget.pk)
        snapshots = []
        fake = self.fake([{"error": "timeout"}])
        def failed_broker(article_id, **kwargs):
            current = NewsArticle.objects.get(pk=article_id)
            run = TranslationRun.objects.get(pk=kwargs["claim_run_id"])
            claim = run.raw_response[recovery.CLAIM_KEY].copy()
            fixture_requirement(not connection.in_atomic_block, "broker必须在领取事务提交后")
            fixture_requirement(current.translation_started_at == t1, "真实锁后Article时间须为t1")
            fixture_requirement(kwargs["claim_started_at"] == claim["claimed_at"] == t1.isoformat(),
                                "broker envelope必须与已持久化Run/Article一致")
            fixture_requirement(current.translation_status == "translating" and run.status == "started"
                                and claim["phase"] == "claimed", "派发前真实领取状态必须完整")
            fixture_requirement(claim["budget_operation_uuid"] == str(self.budget.operation_uuid)
                                and claim["budget_uuid"] == str(self.budget.budget_uuid), "真实budget引用必须固定")
            snapshots.append((run.pk, claim))
            raise RuntimeError("B045 synthetic broker dispatch failure")
        with recovery._offline_budget_scope(self.identity), translation._offline_sdk_dependency(fake):
            with patch.object(recovery.translate_article_task, "delay", side_effect=failed_broker) as broker:
                result = recovery.dispatch_due_translation_retries(now=NOW)
        fixture_requirement(broker.call_count == 1 and len(snapshots) == 1, "broker故障fixture须实际到达")
        self.assertEqual(result.dispatched_ids, [])
        self.assertEqual(fake.trace, [])
        self.constructor.assert_not_called()
        self.assertTrue(fake._closed)
        self.assertEqual(self.budget.__class__.objects.values().get(pk=self.budget.pk), root_before)
        self.assertEqual(self.budget.request_attempts.count(), 0)
        self.article.refresh_from_db()
        run = TranslationRun.objects.get(pk=snapshots[0][0])
        # 原实现预期在此真实RED：selector旧t0与已提交t1不符，严格fence拒绝释放。
        self.assertEqual(self.article.translation_status, "failed")
        self.assertEqual(self.article.translation_error_category, "transient_dispatch_failed")
        self.assertEqual(self.article.translation_error_message, "B045 synthetic broker dispatch failure")
        self.assertIsNone(self.article.translation_started_at)
        self.assertEqual(self.article.translation_next_retry_at,
                         t1 + timedelta(seconds=recovery.retry_delay_seconds(1)))
        self.assertEqual(self.article.translation_retry_count, 1)
        self.assertIsNone(self.article.translation_retry_exhausted_at)
        self.assertEqual(self.article.workflow_status, "translation_failed")
        self.assertEqual(self.article.automation_status, "failed")
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_message, "B045 synthetic broker dispatch failure")
        self.assertEqual(run.raw_response[recovery.CLAIM_KEY], {**snapshots[0][1], "phase": "failed"})
        self.assertEqual(NotificationLog.objects.count(), 0)
        self.assertIsNone(recovery._current_offline_budget_binding())
        self.assertIsNone(translation._offline_sdk_binding.get())

    def test_unbound_dispatch_failure_preserves_selector_claim_and_retry_semantics(self):
        self.fixture_preflight()
        NewsArticle.objects.filter(pk=self.article.pk).update(translation_retry_count=1)
        self.clock.return_value = NOW + timedelta(seconds=7)
        root_before = self.budget.__class__.objects.values().get(pk=self.budget.pk)
        snapshots = []
        def failed_broker(article_id, **kwargs):
            current = NewsArticle.objects.get(pk=article_id)
            run = TranslationRun.objects.get(pk=kwargs["claim_run_id"])
            claim = run.raw_response[recovery.CLAIM_KEY].copy()
            fixture_requirement(not connection.in_atomic_block and current.translation_started_at == NOW,
                                "无scope旧领取须使用selector t0并已经提交")
            fixture_requirement(kwargs["claim_started_at"] == claim["claimed_at"] == NOW.isoformat(),
                                "无scope envelope须保留旧时间语义")
            snapshots.append((run.pk, claim))
            raise RuntimeError("B045 unbound broker failure")
        with patch.object(recovery.translate_article_task, "delay", side_effect=failed_broker) as broker:
            result = recovery.dispatch_due_translation_retries(now=NOW)
        fixture_requirement(broker.call_count == 1 and len(snapshots) == 1, "无scope故障必须实际派发")
        self.assertEqual(result.dispatched_ids, [])
        self.article.refresh_from_db()
        run = TranslationRun.objects.get(pk=snapshots[0][0])
        self.assertEqual(self.article.translation_status, "failed")
        self.assertEqual(self.article.translation_error_category, "transient_dispatch_failed")
        self.assertIsNone(self.article.translation_started_at)
        self.assertEqual(self.article.translation_next_retry_at,
                         NOW + timedelta(seconds=recovery.retry_delay_seconds(1)))
        self.assertEqual(self.article.translation_retry_count, 1)
        self.assertIsNone(self.article.translation_retry_exhausted_at)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.raw_response[recovery.CLAIM_KEY], {**snapshots[0][1], "phase": "failed"})
        self.assertNotIn("claim_execution_uuid", snapshots[0][1])
        self.assertEqual(self.budget.__class__.objects.values().get(pk=self.budget.pk), root_before)
        self.assertEqual(self.budget.request_attempts.count(), 0)
        self.constructor.assert_not_called()
        self.assertEqual(NotificationLog.objects.count(), 0)

    def test_bound_release_rejects_wrong_time_run_and_article_without_relaxing_fence(self):
        self.fixture_preflight()
        t1 = NOW + timedelta(seconds=7)
        self.clock.return_value = t1
        with recovery._offline_budget_scope(self.identity):
            claim = recovery.claim_translation_retry(self.article.pk, expected_due_at=NOW, now=NOW)
            fixture_requirement(claim.claimed and claim.claimed_at == t1.isoformat(), "须真实领取锁后claim t1")
            other = TranslationRun.objects.create(article=self.article, status="started")
            before_article = NewsArticle.objects.values().get(pk=self.article.pk)
            before_run = TranslationRun.objects.values().get(pk=claim.run_id)
            root_before = self.budget.__class__.objects.values().get(pk=self.budget.pk)
            for article_id, run_id, stamp in [(self.article.pk, claim.run_id, NOW),
                    (self.article.pk, other.pk, t1), (self.article.pk + 100000, claim.run_id, t1)]:
                with self.subTest(article_id=article_id, run_id=run_id, stamp=stamp):
                    released = recovery.release_failed_translation_dispatch(
                        article_id, run_id=run_id, claimed_at=stamp, error=RuntimeError("B045 wrong fence"))
                    self.assertFalse(released)
                    self.assertEqual(NewsArticle.objects.values().get(pk=self.article.pk), before_article)
                    self.assertEqual(TranslationRun.objects.values().get(pk=claim.run_id), before_run)
                    self.assertEqual(self.budget.__class__.objects.values().get(pk=self.budget.pk), root_before)
            self.assertTrue(recovery.release_failed_translation_dispatch(
                self.article.pk, run_id=claim.run_id, claimed_at=t1, error=RuntimeError("B045 exact fence")))
        other.refresh_from_db()
        self.assertEqual(other.status, "started")
        run = TranslationRun.objects.get(pk=claim.run_id)
        self.assertEqual(run.raw_response[recovery.CLAIM_KEY],
                         {**before_run["raw_response"][recovery.CLAIM_KEY], "phase": "failed"})
        self.assertEqual(self.budget.request_attempts.count(), 0)
        self.assertEqual(self.budget.__class__.objects.values().get(pk=self.budget.pk), root_before)
        self.constructor.assert_not_called()
        self.assertEqual(NotificationLog.objects.count(), 0)

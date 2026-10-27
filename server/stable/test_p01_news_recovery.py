"""T17/T18：broker 丢任务与 worker 崩溃不能丢稿或重复收费。"""
from datetime import timedelta
from unittest.mock import patch
from django.test import TransactionTestCase
from django.utils import timezone
from stable.models import NewsStageAttempt
from stable.services import news_pipeline
from stable.services.news_model_gateway import reserve_request, execute_request
from stable.test_p01_news_workflow import WorkflowFixture


class RecoveryTests(WorkflowFixture, TransactionTestCase):
    def claim_editorial(self):
        news_pipeline.process_news_run(self.run.pk)
        self.run.refresh_from_db()
        payload = news_pipeline.stage_payload(self.run)
        return news_pipeline.claim_stage(self.run.pk, payload), payload

    def expire(self):
        type(self.run).objects.filter(pk=self.run.pk).update(lease_until=timezone.now()-timedelta(seconds=1))

    def test_completed_provider_receipt_recovers_without_another_call(self):
        attempt, payload = self.claim_editorial()
        execute_request(attempt.pk, payload)
        self.expire()
        self.assertEqual(len(self.calls), 1)
        news_pipeline.recover_expired_run(self.run.pk)
        self.run.refresh_from_db()
        self.assertEqual(self.run.stage, "entity_check")
        self.assertEqual(self.run.state, "pending")
        self.assertEqual(len(self.calls), 1)

    def test_inflight_crash_keeps_cost_reserved_and_requires_reconciliation(self):
        attempt, payload = self.claim_editorial()
        attempt = reserve_request(attempt.pk, payload)
        NewsStageAttempt.objects.filter(pk=attempt.pk).update(state="inflight")
        self.expire()
        news_pipeline.recover_expired_run(self.run.pk)
        attempt.refresh_from_db()
        self.run.refresh_from_db()
        self.assertEqual(attempt.state, "unknown")
        self.assertEqual(self.run.state, "review")
        self.assertGreater(attempt.month_budget.reserved, 0)
        self.assertEqual(self.calls, [])

    def test_never_dispatched_reservation_is_released_then_retryable(self):
        attempt, payload = self.claim_editorial()
        attempt = reserve_request(attempt.pk, payload)
        self.expire()
        news_pipeline.recover_expired_run(self.run.pk)
        attempt.refresh_from_db()
        self.run.refresh_from_db()
        self.assertEqual(attempt.state, "failed")
        self.assertEqual(attempt.actual_cost, 0)
        self.assertEqual(attempt.month_budget.reserved, 0)
        self.assertEqual(self.run.state, "pending")

    def test_broker_failure_keeps_durable_pending_run(self):
        with self.settings(NEWS_QUALITY_DISPATCH_ENABLED=True), patch("stable.tasks.process_news_quality_run_task.apply_async", side_effect=ConnectionError("fixture")):
            self.assertFalse(news_pipeline.enqueue_news_run(self.run.pk))
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "pending")

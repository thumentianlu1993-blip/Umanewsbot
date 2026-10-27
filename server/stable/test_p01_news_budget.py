"""T18/T30：不让供应商重试、费用未知或超上界绕过额度。"""
from datetime import timedelta
from decimal import Decimal
from django.test import TestCase, override_settings
from django.utils import timezone
from stable.models import NewsStageAttempt, NewsModelBudget
from stable.services.ingestion import upsert_article_from_draft
from stable.services.news_pipeline import start_revision, digest
from stable.services.news_model_gateway import RequestDenied, reserve_request
from stable.test_france_news_freshness_change import draft_for

POLICY = {
    "currency": "USD", "day_cap": "10", "month_cap": "100",
    "models": {"entity_check": {
        "provider": "openai", "model": "fixture-strong", "prompt_version": "v1",
        "input_per_million": "1", "output_per_million": "2",
        "max_output_tokens": 1000, "max_input_bytes": 10000,
    }},
}


@override_settings(NEWS_QUALITY_MODE="shadow", NEWS_QUALITY_POLICY=POLICY)
class ModelBudgetTests(TestCase):
    def setUp(self):
        self.run = start_revision(upsert_article_from_draft(draft_for()).article)
        self.run.state = "running"
        self.run.lease_until = timezone.now() + timedelta(seconds=180)
        self.run.save(update_fields=["state", "lease_until"])
        self.attempt = NewsStageAttempt.objects.create(run=self.run, stage="entity_check", seq=1,
            generation=self.run.generation, input_sha=digest({"text": "test"}))

    def test_valid_request_reserves_day_and_month_once(self):
        try:
            attempt = reserve_request(self.attempt.pk, {"text": "test"})
        except RequestDenied as error:
            self.fail(f"已配置的固定任务没有进入金额预约：{error}")
        self.assertGreater(attempt.reservation, Decimal(0))
        again = reserve_request(self.attempt.pk, {"text": "test"})
        self.assertEqual(attempt.pk, again.pk)
        self.assertEqual(NewsModelBudget.objects.count(), 2)
        for budget in NewsModelBudget.objects.all():
            self.assertEqual(budget.reserved, attempt.reservation)
            self.assertEqual(budget.spent, 0)

    @override_settings(NEWS_QUALITY_POLICY={})
    def test_missing_prices_never_creates_a_paid_attempt(self):
        with self.assertRaises(RequestDenied):
            reserve_request(self.attempt.pk, {"text": "test"})
        self.assertFalse(NewsModelBudget.objects.exists())

    def test_actual_overage_is_recorded_and_settlement_is_idempotent(self):
        from stable.services.news_model_gateway import settle_request
        attempt = reserve_request(self.attempt.pk, {"text": "test"})
        NewsModelBudget.objects.all().update(cap=10, spent=8, reserved=2)
        NewsStageAttempt.objects.filter(pk=attempt.pk).update(reservation=2)
        settle_request(attempt.pk, actual_cost="3", result={"ok": True})
        settle_request(attempt.pk, actual_cost="3", result={"ok": True})
        for budget in NewsModelBudget.objects.all():
            self.assertEqual(budget.spent, Decimal(11))
            self.assertEqual(budget.reserved, 0)
            self.assertEqual(budget.overage, 1)
            self.assertEqual(budget.state, "blocked_overage")
        settle_request(attempt.pk, actual_cost="3.5", version=2, usage={"invoice": "fixture"})
        for budget in NewsModelBudget.objects.all():
            self.assertEqual(budget.spent, Decimal("11.5"))
        attempt.refresh_from_db()
        self.assertEqual(attempt.result, {"ok": True})

    def test_unknown_request_keeps_money_and_blocks_new_requests(self):
        from stable.services.news_model_gateway import mark_unknown
        attempt = reserve_request(self.attempt.pk, {"text": "test"})
        mark_unknown(attempt.pk, "timeout")
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "unknown")
        for budget in NewsModelBudget.objects.all():
            self.assertEqual(budget.reserved, attempt.reservation)
            self.assertEqual(budget.state, "blocked_unknown")
        other = NewsStageAttempt.objects.create(run=self.run, stage="entity_check", seq=2,
            generation=self.run.generation, input_sha=digest({"text": "other"}))
        with self.assertRaisesRegex(RequestDenied, "unreconciled_bill"):
            reserve_request(other.pk, {"text": "other"})

    def test_settlement_after_midnight_stays_in_original_buckets(self):
        from stable.services.news_model_gateway import settle_request
        from unittest.mock import patch
        from datetime import datetime, timezone as dtz
        with patch("stable.services.news_model_gateway.timezone.now", return_value=datetime(2026, 10, 31, 15, 59, 59, tzinfo=dtz.utc)):
            self.run.lease_until = timezone.now() + timedelta(seconds=180)
            self.run.save(update_fields=["lease_until"])
            attempt = reserve_request(self.attempt.pk, {"text": "test"})
        original_ids = set(NewsModelBudget.objects.values_list("id", flat=True))
        with patch("stable.services.news_model_gateway.timezone.now", return_value=datetime(2026, 10, 31, 16, 0, 1, tzinfo=dtz.utc)):
            settle_request(attempt.pk, actual_cost="0.001", result={"ok": True})
        self.assertEqual(set(NewsModelBudget.objects.values_list("id", flat=True)), original_ids)
        self.assertTrue(all(b.spent == Decimal("0.001") for b in NewsModelBudget.objects.all()))

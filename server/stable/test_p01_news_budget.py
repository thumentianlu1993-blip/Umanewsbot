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

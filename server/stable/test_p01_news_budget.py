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


from concurrent.futures import ThreadPoolExecutor
from django.db import close_old_connections
from django.test import TransactionTestCase
from threading import Barrier
from copy import deepcopy

CONCURRENT_POLICY = deepcopy(POLICY)
CONCURRENT_POLICY.update(day_cap="5", month_cap="5")
CONCURRENT_POLICY["models"]["entity_check"].update(input_per_million="1000", output_per_million="2000")


@override_settings(NEWS_QUALITY_MODE="shadow", NEWS_QUALITY_POLICY=CONCURRENT_POLICY)
class BudgetConcurrencyTests(TransactionTestCase):
    def test_two_workers_cannot_reserve_the_same_remaining_money(self):
        attempts = []
        for index in range(2):
            run = start_revision(upsert_article_from_draft(draft_for(source_article_id=f"concurrent-{index}")).article)
            run.state = "running"
            run.lease_until = timezone.now() + timedelta(seconds=180)
            run.save(update_fields=["state", "lease_until"])
            attempts.append(NewsStageAttempt.objects.create(run=run, stage="entity_check", seq=1,
                generation=run.generation, input_sha=digest({"text": "test"})).pk)
        barrier = Barrier(2)
        def worker(attempt_id):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                reserve_request(attempt_id, {"text": "test"})
                return "reserved"
            except RequestDenied as exc:
                return str(exc)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = sorted(pool.map(worker, attempts))
        self.assertEqual(result, ["budget_exhausted", "reserved"])
        for budget in NewsModelBudget.objects.all():
            self.assertGreater(budget.reserved, 0)
            self.assertLessEqual(budget.reserved + budget.spent, budget.cap)


@override_settings(NEWS_QUALITY_MODE="shadow", NEWS_QUALITY_POLICY=POLICY)
class SingleDispatchTests(TransactionTestCase):
    setUp = ModelBudgetTests.setUp

    def test_duplicate_dispatch_reuses_response_without_second_charge(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from stable.services.news_model_gateway import execute_request
        response = SimpleNamespace(id="fixture-request", choices=[SimpleNamespace(message=SimpleNamespace(content='{"coverage":"complete","entities":[]}', tool_calls=None))], usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20))
        with patch("stable.services.news_model_gateway._single_request", return_value=response) as provider:
            first = execute_request(self.attempt.pk, {"text": "test"})
            second = execute_request(self.attempt.pk, {"text": "test"})
        self.assertEqual(first.state, "completed")
        self.assertEqual(second.result, {"coverage": "complete", "entities": []})
        self.assertEqual(provider.call_count, 1)
        for budget in NewsModelBudget.objects.all():
            self.assertEqual(budget.reserved, 0)
            self.assertEqual(budget.spent, Decimal("0.00009"))

    def test_timeout_is_unknown_and_never_automatically_resends(self):
        from unittest.mock import patch
        from stable.services.news_model_gateway import execute_request
        with patch("stable.services.news_model_gateway._single_request", side_effect=TimeoutError("fixture")) as provider:
            first = execute_request(self.attempt.pk, {"text": "test"})
            second = execute_request(self.attempt.pk, {"text": "test"})
        self.assertEqual(first.state, "unknown")
        self.assertEqual(second.state, "unknown")
        self.assertEqual(provider.call_count, 1)
        self.assertTrue(all(b.reserved > 0 and b.spent == 0 for b in NewsModelBudget.objects.all()))

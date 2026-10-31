"""P02 T12：两个崩溃窗口和迟到 ack 的实际数据库回归。"""
from datetime import timedelta
from django.test import TestCase
from stable import models
from stable.services import race_lifecycle_projection as service
from stable.test_race_multisource_identity import NOW


class LifecycleDeliveryTests(TestCase):
    def setUp(self):
        self.event = models.RaceEvent.objects.create(year=2026, slug="delivery", original_name="Delivery")
        self.row = models.RaceLifecycleDelivery.objects.create(
            event=self.event, epoch=1, consumer="cache", next_attempt_at=NOW, payload_sha256="a" * 64)

    def claim(self, now=NOW):
        function = getattr(service, "claim_deliveries", None)
        self.assertTrue(callable(function), "outbox 无消费者租约入口，running 崩溃后无法恢复")
        return function(now=now, limit=100)

    def test_expired_running_reclaimed_and_late_ack_rejected(self):
        first = self.claim()[0]
        self.assertEqual(self.claim(NOW + timedelta(seconds=119)), [])
        second = self.claim(NOW + timedelta(seconds=120))[0]
        self.assertNotEqual(first.lease_token, second.lease_token)
        self.assertFalse(service.finish_delivery(first, now=NOW + timedelta(seconds=121)))
        self.assertTrue(service.finish_delivery(second, now=NOW + timedelta(seconds=121)))
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "done")
        self.assertEqual(self.row.attempts, 2)

    def test_retry_and_renew_require_current_live_token(self):
        first = self.claim()[0]
        self.assertTrue(service.renew_delivery(first, now=NOW + timedelta(seconds=90)))
        self.assertEqual(self.claim(NOW + timedelta(seconds=150)), [])
        second = self.claim(NOW + timedelta(seconds=211))[0]
        self.assertFalse(service.renew_delivery(first, now=NOW + timedelta(seconds=212)))
        self.assertTrue(service.finish_delivery(second, now=NOW + timedelta(seconds=212), error="probe_failed"))
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "pending")
        self.assertGreater(self.row.next_attempt_at, NOW + timedelta(seconds=212))

    def test_operation_then_ack_crash_replays_one_idempotent_operation(self):
        first = self.claim()[0]
        from django.core.cache import cache
        cache.set("race-events:public:calendar-years:v2", [1900])
        service.execute_delivery(first, now=NOW)
        self.assertIsNone(cache.get("race-events:public:calendar-years:v2"))
        second = self.claim(NOW + timedelta(seconds=121))[0]
        service.execute_delivery(second, now=NOW + timedelta(seconds=121))
        self.assertTrue(service.finish_delivery(second, now=NOW + timedelta(seconds=122)))

    def test_scheduled_consumer_retries_failure_and_continues(self):
        from stable import tasks
        from unittest.mock import patch
        worker = getattr(tasks, "deliver_race_lifecycle_outbox_task", None)
        self.assertTrue(callable(worker), "未注册持久 outbox 消费任务")
        with patch("django.utils.timezone.now", return_value=NOW), patch.object(
                service, "execute_delivery", side_effect=ValueError("cache_down")):
            result = worker()
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "pending")
        self.assertEqual(result["failed"], 1)


from django.test import TransactionTestCase


class LifecycleDeliveryConcurrencyTests(TransactionTestCase):
    def test_two_postgres_workers_claim_one_delivery_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections
        event = models.RaceEvent.objects.create(year=2026, slug='concurrent-delivery', original_name='Concurrent')
        models.RaceLifecycleDelivery.objects.create(event=event, epoch=1, consumer='cache', next_attempt_at=NOW, payload_sha256='b'*64)
        barrier = Barrier(2)
        def claim():
            try:
                barrier.wait(timeout=10)
                return [r.pk for r in service.claim_deliveries(now=NOW, limit=1)]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim) for _ in range(2)]
            results = [f.result(timeout=15) for f in futures]
        self.assertEqual(sum(len(rows) for rows in results), 1)

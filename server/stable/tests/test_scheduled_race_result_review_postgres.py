"""PostgreSQL-only locking evidence for scheduled race-result review."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Event, Lock
from unittest import mock, skipUnless

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings

from stable import models
from stable.services import scheduled_race_result_review as service


NOW = datetime(2026, 7, 27, 10, 30, tzinfo=dt_timezone.utc)


@skipUnless(
    connection.vendor == "postgresql",
    "requires PostgreSQL row-lock semantics",
)
class ScheduledRaceResultReviewPostgresLockTests(TransactionTestCase):
    reset_sequences = True

    def _event(self, slug: str):
        return models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=slug,
            chinese_name=slug,
            country_region=models.RacingRegion.UNITED_KINGDOM,
            racecourse="Goodwood",
            grade_text="G2",
            surface=models.RaceEventSurface.TURF,
            timezone_name="Europe/London",
            local_date=NOW.date(),
            race_datetime=NOW - timedelta(hours=4),
            status=models.RaceEventStatus.SCHEDULED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )

    @override_settings(RACE_RESULT_REVIEW_ENABLED=True)
    def test_same_slot_second_runner_never_enters_prepare_while_lease_is_live(self):
        entered = Event()
        release = Event()
        calls = 0
        calls_lock = Lock()

        def fake_prepare(**kwargs):
            nonlocal calls
            with calls_lock:
                calls += 1
            entered.set()
            release.wait(timeout=10)
            return {
                "status": "noop",
                "selector_sha256": "d" * 64,
                "target_count": 0,
            }

        def run():
            close_old_connections()
            try:
                return service.run_scheduled_prepare(schedule_slot=NOW)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            with mock.patch(
                "stable.services.scheduled_race_result_review.prepare_review_bundle",
                side_effect=fake_prepare,
            ):
                first = executor.submit(run)
                self.assertTrue(entered.wait(timeout=10))
                second = executor.submit(run)
                second_result = second.result(timeout=10)
                release.set()
                first_result = first.result(timeout=10)

        self.assertEqual(calls, 1)
        self.assertEqual(first_result["status"], "noop")
        self.assertEqual(second_result["status"], "already_claimed")

    def test_event_then_result_lock_observes_concurrent_committed_baseline_drift(self):
        event = self._event("pg-baseline-lock")
        baseline = service.compute_event_baseline(event)
        writer_locked = Event()
        release_writer = Event()

        def writer():
            close_old_connections()
            try:
                with transaction.atomic():
                    locked = models.RaceEvent.objects.select_for_update().get(
                        pk=event.pk
                    )
                    locked.original_name = "Concurrent committed identity"
                    locked.save(update_fields=("original_name", "updated_at"))
                    writer_locked.set()
                    release_writer.wait(timeout=10)
            finally:
                close_old_connections()

        payload = {
            "event_id": event.pk,
            "baseline_sha256": baseline,
            "authority": "human_reviewed_reference",
            "source_authority": "third_party_high_access",
            "result_order_complete": True,
            "results": [
                {
                    "finish_position": 1,
                    "horse_number": "5",
                    "horse_name": "Gold Phoenix",
                    "running_status": "finished",
                }
            ],
        }
        payload["reviewed_row_digest"] = service.compute_reviewed_row_digest(
            payload["results"]
        )

        def apply():
            close_old_connections()
            try:
                return service.apply_reviewed_event_payloads(
                    bundle_sha256="a" * 64,
                    approved_event_ids=[event.pk],
                    reviewer="reviewer@example.test",
                    event_payloads=[payload],
                    confirmed_at=NOW,
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            writer_future = executor.submit(writer)
            self.assertTrue(writer_locked.wait(timeout=10))
            apply_future = executor.submit(apply)
            with self.assertRaises(TimeoutError):
                apply_future.result(timeout=0.2)
            release_writer.set()
            writer_future.result(timeout=10)
            summary = apply_future.result(timeout=10)

        event.refresh_from_db()
        self.assertEqual(event.status, models.RaceEventStatus.SCHEDULED)
        self.assertFalse(event.results.exists())
        self.assertEqual(
            summary["events"][0]["reason_code"],
            "database_baseline_drift",
        )

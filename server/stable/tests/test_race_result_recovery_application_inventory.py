"""Application RED contracts for the race-result recovery inventory.

Native change task: application inventory contract.

These tests intentionally freeze the public service boundary used by the
integration and application implementations.  The inventory is an immutable
artifact, not a new database model.
"""

from __future__ import annotations

import importlib
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from stable import models
from stable.services.race_event_lifecycle import decide_race_lifecycle


WINDOW_START = date(2026, 7, 8)
WINDOW_END = date(2026, 7, 27)
AS_OF = datetime(2026, 7, 27, 12, 0, tzinfo=dt_timezone.utc)


class RaceResultRecoveryInventoryContractTests(TestCase):
    """Freeze the 59-row / 50-race-group recovery accounting contract."""

    maxDiff = None

    def _service(self):
        try:
            return importlib.import_module(
                "stable.services.race_result_recovery_inventory"
            )
        except ModuleNotFoundError:
            self.fail(
                "缺少 stable.services.race_result_recovery_inventory；"
                "RED 要求实现不可变双层 inventory 服务"
            )

    def _event(
        self,
        *,
        ordinal: int,
        name: str,
        local_date: date,
        race_series=None,
        status: str = models.RaceEventStatus.SCHEDULED,
    ):
        return models.RaceEvent.objects.create(
            year=2026,
            slug=f"recovery-inventory-{ordinal}",
            original_name=name,
            chinese_name=f"恢复测试 {name}",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            timezone_name="Asia/Tokyo",
            local_date=local_date,
            status=status,
            priority=models.RaceEventPriority.P0,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
            race_series=race_series,
        )

    def _series(self, ordinal: int, name: str):
        return models.RaceSeries.objects.create(
            key=f"recovery-series-{ordinal}",
            country_region=models.RacingRegion.JAPAN,
            canonical_name_original=name,
            chinese_name=f"系列 {ordinal}",
            review_status=models.RaceSeriesReviewStatus.APPROVED,
        )

    def _build_59_row_fixture(self):
        events = []
        # Forty true missing races, each represented by one zero-result row.
        for ordinal in range(1, 41):
            events.append(
                self._event(
                    ordinal=ordinal,
                    name=f"Missing Race {ordinal}",
                    local_date=WINDOW_START + timedelta(days=(ordinal - 1) % 18),
                )
            )

        # Nine real races represented by two cross-RaceSeries rows each.  The
        # product row is empty while the historical row has confirmed results.
        duplicate_pairs = []
        next_ordinal = 41
        for pair_no in range(1, 10):
            race_date = WINDOW_START + timedelta(days=pair_no)
            name = f"Duplicate Race {pair_no}"
            product = self._event(
                ordinal=next_ordinal,
                name=name,
                local_date=race_date,
                race_series=self._series(next_ordinal, f"{name} Product"),
            )
            historical = self._event(
                ordinal=next_ordinal + 1,
                name=name,
                local_date=race_date,
                race_series=self._series(next_ordinal + 1, f"{name} Ledger"),
                status=models.RaceEventStatus.FINISHED,
            )
            models.RaceEventResult.objects.create(
                event=historical,
                finish_position=1,
                official_finish_position=1,
                horse_name=f"Confirmed Winner {pair_no}",
                is_confirmed=True,
            )
            events.extend((product, historical))
            duplicate_pairs.append((product, historical))
            next_ordinal += 2

        # Event 924 shape: one real race with only provisional rows.
        provisional = self._event(
            ordinal=59,
            name="Hackwood Stakes",
            local_date=date(2026, 7, 18),
        )
        models.RaceEventResult.objects.create(
            event=provisional,
            finish_position=1,
            horse_name="Provisional Winner",
            is_confirmed=False,
        )
        events.append(provisional)
        self.assertEqual(len(events), 59)
        return events, duplicate_pairs, provisional

    def _build_inventory(self):
        events, duplicate_pairs, provisional = self._build_59_row_fixture()
        service = self._service()
        with CaptureQueriesContext(connection) as captured:
            artifact = service.build_recovery_inventory(
                start_date=WINDOW_START,
                end_date=WINDOW_END,
                as_of=AS_OF,
                expected_event_ids=[event.pk for event in events],
            )
        self.assertLessEqual(
            len(captured),
            25,
            f"59 行 inventory 必须批量读取，实际 SQL={len(captured)}",
        )
        return artifact, events, duplicate_pairs, provisional

    def test_inventory_preserves_59_rows_and_builds_50_candidate_groups(self):
        artifact, events, duplicate_pairs, provisional = self._build_inventory()

        self.assertEqual(len(artifact["event_rows"]), 59)
        self.assertEqual(len(artifact["race_groups"]), 50)
        self.assertEqual(
            artifact["classification_counts"],
            {
                "missing_result": 40,
                "duplicate_zero": 9,
                "duplicate_confirmed": 9,
                "provisional": 1,
            },
        )
        self.assertEqual(
            {row["event_id"] for row in artifact["event_rows"]},
            {event.pk for event in events},
        )
        self.assertEqual(len(artifact["manifest_sha256"]), 64)
        self.assertEqual(len(artifact["baseline_sha256"]), 64)
        self.assertNotEqual(
            artifact["manifest_sha256"], artifact["baseline_sha256"]
        )
        self.assertEqual(
            {
                tuple(sorted(review["event_ids"]))
                for review in artifact["identity_reviews"]
            },
            {
                tuple(sorted((product.pk, historical.pk)))
                for product, historical in duplicate_pairs
            },
        )
        self.assertTrue(
            all(
                review["status"] == "pending"
                for review in artifact["identity_reviews"]
            )
        )
        self.assertEqual(artifact["provisional_event_ids"], [provisional.pk])

    def test_cross_series_candidate_remains_pending_and_never_copies_results(self):
        artifact, _events, duplicate_pairs, _provisional = self._build_inventory()
        product, historical = duplicate_pairs[0]

        review = next(
            item
            for item in artifact["identity_reviews"]
            if set(item["event_ids"]) == {product.pk, historical.pk}
        )
        self.assertEqual(review["status"], "pending")
        self.assertIsNone(review["canonical_event_id"])
        self.assertEqual(product.results.count(), 0)
        self.assertEqual(historical.results.filter(is_confirmed=True).count(), 1)

    def test_inventory_reuses_shared_lifecycle_due_boundary(self):
        race_datetime = datetime(
            2026, 7, 27, 10, 0, tzinfo=dt_timezone.utc
        )
        event = models.RaceEvent.objects.create(
            year=2026,
            slug="recovery-shared-lifecycle",
            original_name="Shared Lifecycle",
            chinese_name="共享生命周期",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=models.RaceEventSurface.TURF,
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 7, 27),
            race_datetime=race_datetime,
            status=models.RaceEventStatus.SCHEDULED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )
        expected = decide_race_lifecycle(
            race_datetime=event.race_datetime,
            timezone_name=event.timezone_name,
            status=event.status,
            now=race_datetime + timedelta(minutes=29),
            region=event.country_region,
        )
        service = self._service()
        before = service.build_recovery_inventory(
            start_date=WINDOW_START,
            end_date=WINDOW_END,
            as_of=race_datetime + timedelta(minutes=29),
            expected_event_ids=[event.pk],
        )
        self.assertEqual(before["event_rows"][0]["lifecycle_action"], expected.action)
        self.assertFalse(before["event_rows"][0]["result_due"])

        expected_due = decide_race_lifecycle(
            race_datetime=event.race_datetime,
            timezone_name=event.timezone_name,
            status=event.status,
            now=race_datetime + timedelta(minutes=30),
            region=event.country_region,
        )
        due = service.build_recovery_inventory(
            start_date=WINDOW_START,
            end_date=WINDOW_END,
            as_of=race_datetime + timedelta(minutes=30),
            expected_event_ids=[event.pk],
        )
        self.assertEqual(
            due["event_rows"][0]["lifecycle_action"], expected_due.action
        )
        self.assertTrue(due["event_rows"][0]["result_due"])

    def test_manifest_verifier_rejects_event_identity_and_result_drift(self):
        artifact, events, _duplicate_pairs, _provisional = self._build_inventory()
        service = self._service()

        events[0].chinese_name = "审批后名称漂移"
        events[0].save(update_fields=("chinese_name", "updated_at"))
        with self.assertRaises(service.RecoveryInventoryDrift) as caught:
            service.verify_recovery_inventory(artifact)
        self.assertIn("event_identity_drift", caught.exception.reason_codes)

        events[0].chinese_name = "恢复测试 Missing Race 1"
        events[0].save(update_fields=("chinese_name", "updated_at"))
        models.RaceEventResult.objects.create(
            event=events[1],
            finish_position=1,
            horse_name="Late Result",
            is_confirmed=False,
        )
        with self.assertRaises(service.RecoveryInventoryDrift) as caught:
            service.verify_recovery_inventory(artifact)
        self.assertIn("result_identity_drift", caught.exception.reason_codes)

    def test_accounted_conservation_does_not_equal_completed_with_blockers(self):
        service = self._service()
        target_ids = list(range(1, 51))
        states = {
            target_id: (
                "confirmed_result" if target_id <= 47 else
                "cancelled" if target_id == 48 else
                "postponed" if target_id == 49 else
                "blocked_with_evidence"
            )
            for target_id in target_ids
        }
        summary = service.summarize_recovery_accounting(
            target_ids=target_ids,
            terminal_states=states,
        )

        self.assertEqual(summary["accounted_total"], 50)
        self.assertEqual(summary["target_total"], 50)
        self.assertTrue(summary["is_accounted"])
        self.assertEqual(summary["blocker_count"], 1)
        self.assertFalse(summary["is_completed"])
        self.assertEqual(summary["run_status"], "partial")

        states[50] = "confirmed_result"
        completed = service.summarize_recovery_accounting(
            target_ids=target_ids,
            terminal_states=states,
        )
        self.assertTrue(completed["is_accounted"])
        self.assertEqual(completed["blocker_count"], 0)
        self.assertTrue(completed["is_completed"])
        self.assertEqual(completed["run_status"], "completed")

    def test_accounting_rejects_missing_duplicate_and_unknown_target_states(self):
        service = self._service()
        with self.assertRaises(service.RecoveryAccountingError):
            service.summarize_recovery_accounting(
                target_ids=[1, 2, 3],
                terminal_states={1: "confirmed_result", 2: "confirmed_result"},
            )
        with self.assertRaises(service.RecoveryAccountingError):
            service.summarize_recovery_accounting(
                target_ids=[1, 1, 2],
                terminal_states={1: "confirmed_result", 2: "confirmed_result"},
            )
        with self.assertRaises(service.RecoveryAccountingError):
            service.summarize_recovery_accounting(
                target_ids=[1],
                terminal_states={1: "invented_terminal_state"},
            )

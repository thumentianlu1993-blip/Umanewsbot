from __future__ import annotations

import hashlib
import json
import tempfile
from unittest.mock import patch
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventResult,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services import race_events
from stable.services import race_event_reconciliation
from stable.services.race_event_reconciliation import RaceEventReconciliationError


class RaceEventCoverageReconciliationTests(TestCase):
    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _approve(self, artifact_dir: Path, manifest_sha256: str) -> tuple[Path, str]:
        approval_path = artifact_dir / "approval.json"
        approval_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "approved",
                    "approved_by": "coverage-reviewer",
                    "approved_at": "2026-07-17T01:00:00+00:00",
                    "manifest_sha256": manifest_sha256,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        return approval_path, self._sha256(approval_path)

    def _series(self, key: str, *, name: str | None = None) -> RaceSeries:
        return RaceSeries.objects.create(
            key=key,
            country_region=RacingRegion.JAPAN,
            canonical_name_original=name or key,
            review_status=RaceSeriesReviewStatus.APPROVED,
        )

    def _event(
        self,
        *,
        series: RaceSeries | None,
        year: int,
        slug: str,
        name: str,
        local_date: date,
        status: str = RaceEventStatus.SCHEDULED,
        local_start_time: time | None = time(15, 0),
        visibility_status: str = RaceEventVisibility.DRAFT,
    ) -> RaceEvent:
        return RaceEvent.objects.create(
            race_series=series,
            year=year,
            slug=slug,
            original_name=name,
            chinese_name=name,
            country_region=RacingRegion.JAPAN,
            racecourse="Chukyo",
            grade_text="G2",
            surface=RaceEventSurface.DIRT,
            local_date=local_date,
            local_start_time=local_start_time,
            timezone_name="Asia/Tokyo",
            status=status,
            visibility_status=visibility_status,
        )

    def _target(
        self,
        *,
        series: RaceSeries,
        year: int,
        name: str,
        local_date: date,
        expectation_status: str = HistoricalRaceExpectationStatus.HELD,
        resolution_status: str = HistoricalRaceResolutionStatus.PENDING,
        event: RaceEvent | None = None,
        target_id: int | None = None,
        module_statuses: dict | None = None,
    ) -> HistoricalRaceEventTarget:
        values = {
            "race_series": series,
            "year": year,
            "country_region": RacingRegion.JAPAN,
            "original_name": name,
            "local_date": local_date,
            "expectation_status": expectation_status,
            "resolution_status": resolution_status,
            "event": event,
            "module_statuses": module_statuses or {},
        }
        if target_id is not None:
            values["id"] = target_id
        return HistoricalRaceEventTarget.objects.create(**values)

    def _reconcile(self):
        reconciler = getattr(
            race_events,
            "reconcile_historical_race_event_targets",
            None,
        )
        self.assertTrue(
            callable(reconciler),
            "历史正式目标与 RaceEvent 的安全关联服务尚未实现",
        )
        return reconciler()

    def _export_approved(self, output: Path) -> tuple[dict, Path, str]:
        exported = race_events.export_race_event_coverage_reconciliation(
            output_dir=output,
            as_of=datetime(2026, 7, 17, tzinfo=dt_timezone.utc),
        )
        approval_path, approval_sha = self._approve(output, exported["manifest_sha256"])
        return exported, approval_path, approval_sha

    def _report(
        self,
        *,
        as_of: datetime,
        result_grace: timedelta = timedelta(hours=2),
    ):
        builder = getattr(
            race_events,
            "build_layered_race_event_coverage_report",
            None,
        )
        self.assertTrue(
            callable(builder),
            "historical/current/result 三分母覆盖报告尚未实现",
        )
        return builder(as_of=as_of, result_grace=result_grace)

    def test_not_due_target_can_link_scheduled_event_without_becoming_imported(self):
        series = self._series("japan-future-cup")
        event = self._event(
            series=series,
            year=2026,
            slug="future-cup-2026",
            name="Future Cup",
            local_date=date(2026, 9, 5),
        )
        target = self._target(
            series=series,
            year=2026,
            name="Future Cup",
            local_date=date(2026, 9, 5),
            expectation_status=HistoricalRaceExpectationStatus.NOT_DUE,
            resolution_status=HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE,
        )

        outcome = self._reconcile()

        target.refresh_from_db()
        self.assertEqual(target.event_id, event.id)
        self.assertEqual(target.expectation_status, HistoricalRaceExpectationStatus.NOT_DUE)
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE)
        self.assertIn(target.id, outcome["linked_target_ids"])

    def test_unique_series_and_year_match_is_linked_without_claiming_data_complete(self):
        series = self._series("japan-unique-cup")
        event = self._event(
            series=series,
            year=2025,
            slug="unique-cup-2025",
            name="Unique Cup",
            local_date=date(2025, 5, 1),
            status=RaceEventStatus.FINISHED,
        )
        target = self._target(
            series=series,
            year=2025,
            name="Historical Sponsored Unique Cup",
            local_date=date(2025, 5, 1),
        )

        outcome = self._reconcile()

        target.refresh_from_db()
        self.assertEqual(target.event_id, event.id)
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.PENDING)
        self.assertEqual(outcome["linked_target_ids"], [target.id])

    def test_same_name_from_different_series_is_not_auto_linked(self):
        target_series = self._series("japan-gold-cup-flat", name="Gold Cup")
        other_series = self._series("japan-gold-cup-jumps", name="Gold Cup")
        self._event(
            series=other_series,
            year=2026,
            slug="gold-cup-jumps-2026",
            name="Gold Cup",
            local_date=date(2026, 4, 1),
        )
        target = self._target(
            series=target_series,
            year=2026,
            name="Gold Cup",
            local_date=date(2026, 4, 1),
        )

        outcome = self._reconcile()

        target.refresh_from_db()
        self.assertIsNone(target.event_id)
        conflict = next(item for item in outcome["conflicts"] if item["target_id"] == target.id)
        self.assertEqual(conflict["reason"], "series_mismatch")

    def test_one_to_many_legacy_name_match_is_reported_as_conflict_not_linked(self):
        series = self._series("japan-legacy-cup", name="Legacy Cup")
        first = self._event(
            series=None,
            year=2026,
            slug="legacy-cup-a-2026",
            name="Legacy Cup",
            local_date=date(2026, 6, 1),
        )
        second = self._event(
            series=None,
            year=2026,
            slug="legacy-cup-b-2026",
            name="Legacy Cup",
            local_date=date(2026, 6, 2),
        )
        target = self._target(
            series=series,
            year=2026,
            name="Legacy Cup",
            local_date=date(2026, 6, 1),
        )

        outcome = self._reconcile()

        target.refresh_from_db()
        self.assertIsNone(target.event_id)
        conflict = next(item for item in outcome["conflicts"] if item["target_id"] == target.id)
        self.assertEqual(conflict["reason"], "ambiguous_name_match")
        self.assertEqual(set(conflict["candidate_event_ids"]), {first.id, second.id})

    def test_display_only_event_outside_formal_targets_does_not_change_denominators(self):
        as_of = datetime(2026, 7, 17, 0, 0, tzinfo=dt_timezone.utc)
        before = self._report(as_of=as_of)
        display_series = self._series("japan-display-only")
        self._event(
            series=display_series,
            year=2026,
            slug="display-only-2026",
            name="Display Only Invitational",
            local_date=date(2026, 7, 20),
            visibility_status=RaceEventVisibility.PUBLISHED,
        )

        after = self._report(as_of=as_of)

        self.assertEqual(after["historical"]["denominator"], before["historical"]["denominator"])
        self.assertEqual(after["current"]["denominator"], before["current"]["denominator"])
        self.assertEqual(after["result"]["denominator"], before["result"]["denominator"])

    def test_finished_event_moves_to_awaiting_result_only_after_grace_period(self):
        series = self._series("japan-grace-cup")
        event = self._event(
            series=series,
            year=2026,
            slug="grace-cup-2026",
            name="Grace Cup",
            local_date=date(2026, 7, 17),
            local_start_time=time(15, 0),
            status=RaceEventStatus.FINISHED,
        )
        self._target(
            series=series,
            year=2026,
            name="Grace Cup",
            local_date=date(2026, 7, 17),
            event=event,
        )

        inside_grace = self._report(
            as_of=datetime(2026, 7, 17, 7, 30, tzinfo=dt_timezone.utc),
            result_grace=timedelta(hours=2),
        )
        after_grace = self._report(
            as_of=datetime(2026, 7, 17, 8, 1, tzinfo=dt_timezone.utc),
            result_grace=timedelta(hours=2),
        )

        self.assertIn(event.id, inside_grace["result"]["grace_period_event_ids"])
        self.assertNotIn(event.id, inside_grace["result"]["awaiting_result_event_ids"])
        self.assertIn(event.id, after_grace["result"]["awaiting_result_event_ids"])
        self.assertEqual(after_grace["result"]["awaiting_result_count"], 1)

    def test_cancelled_and_postponed_events_are_not_counted_as_missing_results(self):
        for key, status in (
            ("cancelled", RaceEventStatus.CANCELLED),
            ("postponed", RaceEventStatus.POSTPONED),
        ):
            series = self._series(f"japan-{key}-cup")
            event = self._event(
                series=series,
                year=2026,
                slug=f"{key}-cup-2026",
                name=f"{key.title()} Cup",
                local_date=date(2026, 7, 1),
                status=status,
            )
            self._target(
                series=series,
                year=2026,
                name=f"{key.title()} Cup",
                local_date=date(2026, 7, 1),
                expectation_status=(
                    HistoricalRaceExpectationStatus.CANCELLED
                    if status == RaceEventStatus.CANCELLED
                    else HistoricalRaceExpectationStatus.HELD
                ),
                event=event,
            )

        report = self._report(
            as_of=datetime(2026, 7, 17, 0, 0, tzinfo=dt_timezone.utc),
        )

        self.assertEqual(report["result"]["denominator"], 0)
        self.assertEqual(report["result"]["missing_count"], 0)
        self.assertEqual(report["result"]["excluded_status_counts"], {"cancelled": 1, "postponed": 1})
        self.assertEqual(report["result"]["candidate_count"], 2)
        self.assertTrue(report["result"]["conservation_ok"])

    def test_reconciliation_is_idempotent(self):
        series = self._series("japan-idempotent-cup")
        event = self._event(
            series=series,
            year=2025,
            slug="idempotent-cup-2025",
            name="Idempotent Cup",
            local_date=date(2025, 8, 1),
            status=RaceEventStatus.FINISHED,
        )
        target = self._target(
            series=series,
            year=2025,
            name="Idempotent Cup",
            local_date=date(2025, 8, 1),
        )

        first = self._reconcile()
        second = self._reconcile()

        target.refresh_from_db()
        self.assertEqual(target.event_id, event.id)
        self.assertEqual(first["linked_target_ids"], [target.id])
        self.assertEqual(second["linked_target_ids"], [])
        self.assertEqual(second["conflicts"], [])
        self.assertEqual(HistoricalRaceEventTarget.objects.count(), 1)
        self.assertEqual(RaceEvent.objects.count(), 1)

    def test_tokai_2026_real_regression_shape_keeps_future_tokai_and_finished_kinko_separate(self):
        tokai_series = self._series("japan-tokai", name="Tokai S")
        kinko_series = self._series("japan-tokai-tv-hai-kinko-sho", name="Tokai TV Hai Kinko Sho")
        tokai_event = self._event(
            series=tokai_series,
            year=2026,
            slug="japan-tokai-2026",
            name="Tokai S",
            local_date=date(2026, 7, 26),
            status=RaceEventStatus.SCHEDULED,
        )
        kinko_event = self._event(
            series=kinko_series,
            year=2026,
            slug="japan-tokai-tv-hai-kinko-sho-2026",
            name="Tokai TV Hai Kinko Sho",
            local_date=date(2026, 3, 15),
            status=RaceEventStatus.FINISHED,
        )
        tokai_target = self._target(
            target_id=53418,
            series=tokai_series,
            year=2026,
            name="Tokai S",
            local_date=date(2026, 7, 26),
            expectation_status=HistoricalRaceExpectationStatus.NOT_DUE,
            resolution_status=HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE,
        )
        self._target(
            target_id=53419,
            series=kinko_series,
            year=2026,
            name="Tokai TV Hai Kinko Sho",
            local_date=date(2026, 3, 15),
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
            event=kinko_event,
            module_statuses={"results": "complete"},
        )
        RaceEventResult.objects.create(
            event=kinko_event,
            finish_position=1,
            official_finish_position=1,
            horse_number="1",
            horse_name="Kinko Winner",
            is_confirmed=True,
        )
        kinko_event.result_confirmed_at = datetime(2026, 3, 15, 9, 0, tzinfo=dt_timezone.utc)
        kinko_event.save(update_fields={"result_confirmed_at"})

        outcome = self._reconcile()
        report = self._report(
            as_of=datetime(2026, 7, 15, 12, 0, tzinfo=dt_timezone.utc),
            result_grace=timedelta(days=3),
        )

        tokai_target.refresh_from_db()
        self.assertEqual(tokai_target.event_id, tokai_event.id)
        self.assertEqual(tokai_target.expectation_status, HistoricalRaceExpectationStatus.NOT_DUE)
        self.assertEqual(tokai_target.resolution_status, HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE)
        self.assertEqual(outcome["conflicts"], [])
        self.assertEqual(report["current"]["denominator"], 2)
        self.assertEqual(report["result"]["denominator"], 1)
        self.assertEqual(report["result"]["complete_count"], 1)
        self.assertEqual(report["result"]["awaiting_result_count"], 0)

    def test_report_keeps_historical_current_and_result_denominators_separate(self):
        historical_series = self._series("japan-historical-cup")
        historical_event = self._event(
            series=historical_series,
            year=2024,
            slug="historical-cup-2024",
            name="Historical Cup",
            local_date=date(2024, 5, 1),
            status=RaceEventStatus.FINISHED,
        )
        self._target(
            series=historical_series,
            year=2024,
            name="Historical Cup",
            local_date=date(2024, 5, 1),
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
            event=historical_event,
            module_statuses={"results": "complete"},
        )
        RaceEventResult.objects.create(
            event=historical_event,
            finish_position=1,
            horse_name="Historical Winner",
            is_confirmed=True,
        )
        historical_event.result_confirmed_at = datetime(2024, 5, 1, 9, 0, tzinfo=dt_timezone.utc)
        historical_event.save(update_fields={"result_confirmed_at"})

        future_series = self._series("japan-current-future-cup")
        future_event = self._event(
            series=future_series,
            year=2026,
            slug="current-future-cup-2026",
            name="Current Future Cup",
            local_date=date(2026, 9, 1),
        )
        self._target(
            series=future_series,
            year=2026,
            name="Current Future Cup",
            local_date=date(2026, 9, 1),
            expectation_status=HistoricalRaceExpectationStatus.NOT_DUE,
            resolution_status=HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE,
            event=future_event,
        )

        due_series = self._series("japan-current-due-cup")
        due_event = self._event(
            series=due_series,
            year=2026,
            slug="current-due-cup-2026",
            name="Current Due Cup",
            local_date=date(2026, 7, 1),
            status=RaceEventStatus.FINISHED,
        )
        self._target(
            series=due_series,
            year=2026,
            name="Current Due Cup",
            local_date=date(2026, 7, 1),
            event=due_event,
        )

        report = self._report(
            as_of=datetime(2026, 7, 17, 0, 0, tzinfo=dt_timezone.utc),
        )

        self.assertEqual(report["historical"]["denominator"], 1)
        self.assertEqual(report["historical"]["complete_count"], 1)
        self.assertEqual(report["current"]["denominator"], 2)
        self.assertEqual(report["current"]["not_due_count"], 1)
        self.assertEqual(report["result"]["denominator"], 2)
        self.assertEqual(report["result"]["complete_count"], 1)
        self.assertEqual(report["result"]["awaiting_result_count"], 1)

    def test_result_rows_without_explicit_completion_evidence_are_not_complete(self):
        events = []
        for index, (case, module_complete, has_confirmed_at, result_confirmed) in enumerate(
            (
                ("missing-module", False, True, True),
                ("missing-confirmed-at", True, False, True),
                ("unconfirmed-result", True, True, False),
            ),
            start=1,
        ):
            series = self._series(f"japan-partial-{case}")
            event = self._event(
                series=series,
                year=2024,
                slug=f"partial-{case}-2024",
                name=f"Partial {case}",
                local_date=date(2024, 6, index),
                status=RaceEventStatus.FINISHED,
            )
            self._target(
                series=series,
                year=2024,
                name=f"Partial {case}",
                local_date=date(2024, 6, index),
                resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
                event=event,
                module_statuses={"results": "complete"} if module_complete else {},
            )
            RaceEventResult.objects.create(
                event=event,
                finish_position=1,
                horse_name=f"Winner {case}",
                is_confirmed=result_confirmed,
            )
            if has_confirmed_at:
                event.result_confirmed_at = datetime(2024, 6, index, 9, 0, tzinfo=dt_timezone.utc)
                event.save(update_fields={"result_confirmed_at"})
            events.append(event)

        report = self._report(
            as_of=datetime(2026, 7, 17, 0, 0, tzinfo=dt_timezone.utc),
        )

        self.assertEqual(report["result"]["denominator"], 3)
        self.assertEqual(report["result"]["complete_count"], 0)
        self.assertEqual(report["result"]["incomplete_count"], 3)
        self.assertEqual(set(report["result"]["incomplete_event_ids"]), {event.id for event in events})

    def test_artifact_is_atomic_non_overwriting_and_default_command_is_read_only(self):
        series = self._series("japan-artifact-cup")
        self._event(
            series=series,
            year=2026,
            slug="artifact-cup-2026",
            name="Artifact Cup",
            local_date=date(2026, 8, 1),
        )
        target = self._target(
            series=series,
            year=2026,
            name="Artifact Cup",
            local_date=date(2026, 8, 1),
            expectation_status=HistoricalRaceExpectationStatus.NOT_DUE,
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run-001"
            call_command(
                "reconcile_race_event_coverage",
                "--output-dir",
                str(output),
                "--as-of",
                "2026-07-17T00:00:00+00:00",
            )
            target.refresh_from_db()
            self.assertIsNone(target.event_id)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {
                    "approval.json",
                    "coverage_report.json",
                    "manifest.json",
                    "reconciliation.jsonl",
                    "review.csv",
                    "review.html",
                },
            )
            with self.assertRaises(CommandError):
                call_command("reconcile_race_event_coverage", "--output-dir", str(output))

    def test_apply_requires_independent_double_sha_and_rejects_identity_drift(self):
        series = self._series("japan-approval-cup")
        event = self._event(
            series=series,
            year=2026,
            slug="approval-cup-2026",
            name="Approval Cup",
            local_date=date(2026, 8, 2),
        )
        target = self._target(
            series=series,
            year=2026,
            name="Approval Cup",
            local_date=date(2026, 8, 2),
            expectation_status=HistoricalRaceExpectationStatus.NOT_DUE,
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run-approval"
            exported = race_events.export_race_event_coverage_reconciliation(
                output_dir=output,
                as_of=datetime(2026, 7, 17, tzinfo=dt_timezone.utc),
            )
            with self.assertRaises(RaceEventReconciliationError):
                race_events.apply_race_event_coverage_reconciliation(
                    artifact_dir=output,
                    expected_manifest_sha256=exported["manifest_sha256"],
                    approval_path=output / "approval.json",
                    expected_approval_sha256=exported["approval_sha256"],
                )
            approval_path, approval_sha = self._approve(output, exported["manifest_sha256"])
            target.original_name = "Drifted Approval Cup"
            target.save(update_fields={"original_name"})
            with self.assertRaisesRegex(RaceEventReconciliationError, "identity drift"):
                race_events.apply_race_event_coverage_reconciliation(
                    artifact_dir=output,
                    expected_manifest_sha256=exported["manifest_sha256"],
                    approval_path=approval_path,
                    expected_approval_sha256=approval_sha,
                )
            target.refresh_from_db()
            self.assertIsNone(target.event_id)
            self.assertEqual(event.historical_target if hasattr(event, "historical_target") else None, None)

    def test_apply_logs_verifies_and_rollback_restores_only_the_link(self):
        series = self._series("japan-rollback-cup")
        event = self._event(
            series=series,
            year=2026,
            slug="rollback-cup-2026",
            name="Rollback Cup",
            local_date=date(2026, 8, 3),
            visibility_status=RaceEventVisibility.PUBLISHED,
        )
        target = self._target(
            series=series,
            year=2026,
            name="Rollback Cup",
            local_date=date(2026, 8, 3),
            expectation_status=HistoricalRaceExpectationStatus.NOT_DUE,
            resolution_status=HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE,
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run-rollback"
            exported = race_events.export_race_event_coverage_reconciliation(
                output_dir=output,
                as_of=datetime(2026, 7, 17, tzinfo=dt_timezone.utc),
            )
            approval_path, approval_sha = self._approve(output, exported["manifest_sha256"])
            applied = race_events.apply_race_event_coverage_reconciliation(
                artifact_dir=output,
                expected_manifest_sha256=exported["manifest_sha256"],
                approval_path=approval_path,
                expected_approval_sha256=approval_sha,
            )
            target.refresh_from_db()
            event.refresh_from_db()
            self.assertEqual(target.event_id, event.pk)
            self.assertEqual(target.expectation_status, HistoricalRaceExpectationStatus.NOT_DUE)
            self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE)
            self.assertEqual(event.visibility_status, RaceEventVisibility.PUBLISHED)
            self.assertTrue(applied["verification"]["ok"])
            self.assertTrue(
                OperationLog.objects.filter(
                    action_type="race_event_target_reconciled",
                    target_id=str(target.pk),
                ).exists()
            )
            rolled_back = race_events.rollback_race_event_coverage_reconciliation(
                artifact_dir=output,
                expected_manifest_sha256=exported["manifest_sha256"],
                approval_path=approval_path,
                expected_approval_sha256=approval_sha,
                rollback_path=applied["rollback_path"],
                expected_rollback_sha256=applied["rollback_sha256"],
            )
            target.refresh_from_db()
            self.assertIsNone(target.event_id)
            self.assertEqual(rolled_back["rolled_back_target_ids"], [target.pk])

    def test_manifest_or_approval_byte_drift_blocks_apply(self):
        series = self._series("japan-byte-drift-cup")
        self._event(
            series=series,
            year=2026,
            slug="byte-drift-cup-2026",
            name="Byte Drift Cup",
            local_date=date(2026, 8, 4),
        )
        self._target(
            series=series,
            year=2026,
            name="Byte Drift Cup",
            local_date=date(2026, 8, 4),
            expectation_status=HistoricalRaceExpectationStatus.NOT_DUE,
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run-byte-drift"
            exported = race_events.export_race_event_coverage_reconciliation(
                output_dir=output,
                as_of=datetime(2026, 7, 17, tzinfo=dt_timezone.utc),
            )
            approval_path, approval_sha = self._approve(output, exported["manifest_sha256"])
            approval_path.write_bytes(approval_path.read_bytes() + b" ")
            with self.assertRaisesRegex(RaceEventReconciliationError, "approval SHA"):
                race_events.apply_race_event_coverage_reconciliation(
                    artifact_dir=output,
                    expected_manifest_sha256=exported["manifest_sha256"],
                    approval_path=approval_path,
                    expected_approval_sha256=approval_sha,
                )

    def test_apply_preflights_existing_or_unpublishable_ledger_before_db_writes(self):
        series = self._series("japan-ledger-preflight")
        event = self._event(series=series, year=2026, slug="ledger-preflight-2026", name="Ledger", local_date=date(2026, 8, 5))
        target = self._target(series=series, year=2026, name="Ledger", local_date=date(2026, 8, 5))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            exported, approval, approval_sha = self._export_approved(output)
            existing = Path(temporary) / "existing.jsonl"
            existing.write_text("reserved", encoding="utf-8")
            for ledger in (existing, Path(temporary) / "parent-file" / "rollback.jsonl"):
                if ledger != existing:
                    ledger.parent.write_text("not a directory", encoding="utf-8")
                with self.assertRaisesRegex(RaceEventReconciliationError, "ledger"):
                    race_events.apply_race_event_coverage_reconciliation(
                        artifact_dir=output,
                        expected_manifest_sha256=exported["manifest_sha256"],
                        approval_path=approval,
                        expected_approval_sha256=approval_sha,
                        rollback_path=ledger,
                    )
                target.refresh_from_db()
                self.assertIsNone(target.event_id)
                self.assertFalse(OperationLog.objects.filter(action_type="race_event_target_reconciled").exists())
        self.assertFalse(hasattr(event, "historical_target"))

    def test_ledger_publish_failure_rolls_back_whole_apply(self):
        series = self._series("japan-ledger-publish")
        self._event(series=series, year=2026, slug="ledger-publish-2026", name="Ledger Publish", local_date=date(2026, 8, 6))
        target = self._target(series=series, year=2026, name="Ledger Publish", local_date=date(2026, 8, 6))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            exported, approval, approval_sha = self._export_approved(output)
            with patch.object(race_event_reconciliation.os, "link", side_effect=OSError("denied")):
                with self.assertRaisesRegex(RaceEventReconciliationError, "cannot be published"):
                    race_events.apply_race_event_coverage_reconciliation(
                        artifact_dir=output,
                        expected_manifest_sha256=exported["manifest_sha256"],
                        approval_path=approval,
                        expected_approval_sha256=approval_sha,
                    )
            target.refresh_from_db()
            self.assertIsNone(target.event_id)
            self.assertFalse((output / "rollback.jsonl").exists())
            self.assertFalse(OperationLog.objects.filter(action_type="race_event_target_reconciled").exists())

    def test_rollback_validates_all_rows_before_unlinking_any(self):
        targets = []
        events = []
        for index in (1, 2):
            series = self._series(f"japan-multi-rollback-{index}")
            events.append(self._event(series=series, year=2026, slug=f"multi-{index}-2026", name=f"Multi {index}", local_date=date(2026, 8, 6 + index)))
            targets.append(self._target(series=series, year=2026, name=f"Multi {index}", local_date=date(2026, 8, 6 + index)))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            exported, approval, approval_sha = self._export_approved(output)
            applied = race_events.apply_race_event_coverage_reconciliation(
                artifact_dir=output, expected_manifest_sha256=exported["manifest_sha256"],
                approval_path=approval, expected_approval_sha256=approval_sha,
            )
            events[0].original_name = "drifted"
            events[0].save(update_fields={"original_name"})
            with self.assertRaisesRegex(RaceEventReconciliationError, "event changed"):
                race_events.rollback_race_event_coverage_reconciliation(
                    artifact_dir=output, expected_manifest_sha256=exported["manifest_sha256"],
                    approval_path=approval, expected_approval_sha256=approval_sha,
                    rollback_path=applied["rollback_path"], expected_rollback_sha256=applied["rollback_sha256"],
                )
            for target, event in zip(targets, events):
                target.refresh_from_db()
                self.assertEqual(target.event_id, event.pk)

    def test_symlinked_reconciliation_or_approval_is_rejected(self):
        series = self._series("japan-symlink")
        self._event(series=series, year=2026, slug="symlink-2026", name="Symlink", local_date=date(2026, 8, 9))
        target = self._target(series=series, year=2026, name="Symlink", local_date=date(2026, 8, 9))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            exported, approval, approval_sha = self._export_approved(output)
            saved = Path(temporary) / "reconciliation-copy"
            source = output / "reconciliation.jsonl"
            saved.write_bytes(source.read_bytes())
            source.unlink()
            source.symlink_to(saved)
            with self.assertRaisesRegex(RaceEventReconciliationError, "safely open"):
                race_events.apply_race_event_coverage_reconciliation(
                    artifact_dir=output, expected_manifest_sha256=exported["manifest_sha256"],
                    approval_path=approval, expected_approval_sha256=approval_sha,
                )
            target.refresh_from_db()
            self.assertIsNone(target.event_id)
            source.unlink()
            source.write_bytes(saved.read_bytes())
            approval_copy = Path(temporary) / "approval-copy"
            approval_copy.write_bytes(approval.read_bytes())
            approval.unlink()
            approval.symlink_to(approval_copy)
            with self.assertRaisesRegex(RaceEventReconciliationError, "safely open"):
                race_events.apply_race_event_coverage_reconciliation(
                    artifact_dir=output, expected_manifest_sha256=exported["manifest_sha256"],
                    approval_path=approval, expected_approval_sha256=approval_sha,
                )

    def test_reconciliation_bytes_are_not_reopened_after_verification(self):
        series = self._series("japan-toctou")
        event = self._event(series=series, year=2026, slug="toctou-2026", name="TOCTOU", local_date=date(2026, 8, 10))
        target = self._target(series=series, year=2026, name="TOCTOU", local_date=date(2026, 8, 10))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            exported, approval, approval_sha = self._export_approved(output)
            original_reader = race_event_reconciliation._read_regular_file_bytes
            replaced = False
            def replace_after_read(path, *, label):
                nonlocal replaced
                payload = original_reader(path, label=label)
                if path.name == "reconciliation.jsonl" and not replaced:
                    replaced = True
                    path.write_bytes(b"")
                return payload
            with patch.object(race_event_reconciliation, "_read_regular_file_bytes", side_effect=replace_after_read):
                race_events.apply_race_event_coverage_reconciliation(
                    artifact_dir=output, expected_manifest_sha256=exported["manifest_sha256"],
                    approval_path=approval, expected_approval_sha256=approval_sha,
                )
            target.refresh_from_db()
            self.assertEqual(target.event_id, event.pk)

    def test_manifest_artifact_key_must_bind_same_canonical_unique_path(self):
        series = self._series("japan-manifest-binding")
        self._event(series=series, year=2026, slug="binding-2026", name="Binding", local_date=date(2026, 8, 11))
        target = self._target(series=series, year=2026, name="Binding", local_date=date(2026, 8, 11))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            exported, _, _ = self._export_approved(output)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest["artifacts"]["reconciliation.jsonl"]["path"] = "coverage_report.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            manifest_sha = self._sha256(manifest_path)
            approval, approval_sha = self._approve(output, manifest_sha)
            with self.assertRaisesRegex(RaceEventReconciliationError, "key/path"):
                race_events.apply_race_event_coverage_reconciliation(
                    artifact_dir=output, expected_manifest_sha256=manifest_sha,
                    approval_path=approval, expected_approval_sha256=approval_sha,
                )
            target.refresh_from_db()
            self.assertIsNone(target.event_id)

    def test_export_baseline_target_and_report_denominators_conserve(self):
        for year in (2024, 2025):
            series = self._series(f"japan-export-{year}")
            self._target(series=series, year=year, name=str(year), local_date=date(year, 1, 1))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            self._export_approved(output)
            manifest = json.loads((output / "manifest.json").read_bytes())
            report = json.loads((output / "coverage_report.json").read_bytes())
            self.assertEqual(len(manifest["target_ids"]), manifest["database_baseline"]["target_count"])
            self.assertEqual(report["historical"]["denominator"] + report["current"]["denominator"], manifest["database_baseline"]["target_count"])

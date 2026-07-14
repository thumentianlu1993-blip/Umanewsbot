from __future__ import annotations

import hashlib
import json
import re
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    HorseProfile,
    OperationLog,
    RaceEvent,
    RaceEventDataCandidate,
    RaceEventResult,
    RaceEventRunner,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
    TermEntry,
)
from stable.services.historical_race_batches import (
    _locked_historical_target,
    materialize_historical_event,
    read_immutable_selection_snapshot,
    select_historical_band_batch_targets,
    select_first_acceptance_targets,
    target_identity,
    validate_standard_batch,
    write_band_batch_artifact,
    write_event_input_csvs,
    write_batch_snapshot,
)
from stable.services.historical_race_inventory import InventoryValidationError, canonical_json
from stable.services.historical_race_importer import (
    apply_authoritative_event_fields,
    apply_historical_champion_supplement,
    apply_historical_target_candidate,
    audit_historical_candidate_coverage,
)
from stable.services.race_event_crawl_orchestration import (
    PlanValidationError,
    expected_targets_from_plan,
    validate_plan,
)


class HistoricalRaceBatchTests(TestCase):
    def _series(self, region: str, suffix: str) -> RaceSeries:
        return RaceSeries.objects.create(
            key=f"{region}-{suffix}",
            country_region=region,
            canonical_name_original=f"{region} {suffix}",
            chinese_name=f"{region} {suffix}",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )

    def _target(
        self,
        series: RaceSeries,
        year: int,
        *,
        expectation: str = HistoricalRaceExpectationStatus.HELD,
        resolution: str = HistoricalRaceResolutionStatus.READY,
        with_event: bool = True,
    ) -> HistoricalRaceEventTarget:
        event = None
        if with_event:
            event = RaceEvent.objects.create(
                year=year,
                slug=f"{series.key}-{year}",
                race_series=series,
                original_name=series.canonical_name_original,
                chinese_name=series.chinese_name,
                country_region=series.country_region,
                racecourse="Test Course",
                grade_text="G1",
                surface=RaceEventSurface.TURF,
                status=RaceEventStatus.FINISHED,
                visibility_status=RaceEventVisibility.DRAFT,
                source_refs={"official": True},
            )
        return HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=year,
            expectation_status=expectation,
            resolution_status=resolution,
            original_name=series.canonical_name_original,
            chinese_name=series.chinese_name,
            racecourse="Test Course",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            source_refs={"catalog": "official"},
            artifact_sha256="a" * 64,
            event=event,
        )

    def test_materialize_creates_stable_draft_and_is_idempotent(self):
        series = self._series(RacingRegion.FRANCE, "prix-test")
        target = self._target(series, 1984, with_event=False)

        event = materialize_historical_event(target)
        event.visibility_status = RaceEventVisibility.PUBLISHED
        event.save(update_fields={"visibility_status"})
        repeated = materialize_historical_event(target)

        self.assertEqual(event.slug, "france-prix-test-1984")
        self.assertEqual(repeated.pk, event.pk)
        self.assertEqual(repeated.visibility_status, RaceEventVisibility.PUBLISHED)
        self.assertEqual(RaceEvent.objects.count(), 1)

    def test_materialize_lock_query_does_not_join_nullable_event_relation(self):
        target = self._target(self._series(RacingRegion.UNITED_KINGDOM, "lock-query"), 2000)

        queryset = _locked_historical_target(target.pk)

        self.assertIn("race_series", queryset.query.select_related)
        self.assertNotIn("event", queryset.query.select_related)

    def test_historical_target_lock_queries_never_join_nullable_event(self):
        services = Path(__file__).resolve().parent / "services"
        forbidden = re.compile(
            r"select_for_update\(\)[\s\S]{0,180}select_related\([^\n]*[\"']event[\"']"
        )
        for name in (
            "historical_race_batches.py",
            "historical_race_date_discovery.py",
            "historical_race_importer.py",
            "historical_race_inventory.py",
        ):
            with self.subTest(name=name):
                self.assertNotRegex((services / name).read_text(encoding="utf-8"), forbidden)

    def test_event_input_export_writes_ready_materialized_targets_by_region(self):
        target = self._target(self._series(RacingRegion.HONG_KONG, "event-export"), 2000)
        target.event.source_refs = {"detail_discovery": {"urls": {"result_url": {"url": "https://hkjc.com/result"}}}}
        target.event.save(update_fields={"source_refs"})

        with TemporaryDirectory() as tmp:
            result = write_event_input_csvs([target], output_dir=Path(tmp))
            output = Path(result["files"][RacingRegion.HONG_KONG])
            rows = output.read_text(encoding="utf-8-sig")

        self.assertEqual(result["target_count"], 1)
        self.assertIn(target.event.slug, rows)
        self.assertIn("detail_discovery", rows)
        self.assertIn(target_identity(target)["target_sha256"], rows)
        self.assertIn(target.artifact_sha256, rows)

    def test_event_input_export_rejects_pending_or_unmaterialized_target(self):
        target = self._target(
            self._series(RacingRegion.UNITED_STATES, "event-export-pending"),
            2000,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )

        with TemporaryDirectory() as tmp, self.assertRaisesMessage(
            InventoryValidationError, "ready and materialized"
        ):
            write_event_input_csvs([target], output_dir=Path(tmp))

    def test_event_input_export_command_accepts_approval_target_ids(self):
        target = self._target(self._series(RacingRegion.JAPAN, "event-export-command"), 2000)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = root / "approval.json"
            ids.write_text(json.dumps({"approved_target_ids": [target.pk]}), encoding="utf-8")

            call_command(
                "export_historical_race_event_inputs",
                target_ids_json=str(ids),
                output_dir=str(root / "events"),
            )

            self.assertTrue((root / "events" / "events_japan.csv").is_file())

    def test_not_held_target_never_creates_fake_event(self):
        target = self._target(
            self._series(RacingRegion.FRANCE, "not-held"),
            1984,
            expectation=HistoricalRaceExpectationStatus.NOT_HELD,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )

        self.assertIsNone(materialize_historical_event(target))
        self.assertFalse(RaceEvent.objects.exists())

    def test_first_acceptance_selects_five_regions_three_series_and_three_eras(self):
        selected_series: dict[str, list[str]] = {}
        regions = [
            RacingRegion.JAPAN,
            RacingRegion.HONG_KONG,
            RacingRegion.UNITED_KINGDOM,
            RacingRegion.FRANCE,
            RacingRegion.UNITED_STATES,
        ]
        for region in regions:
            selected_series[region] = []
            for index in range(3):
                series = self._series(region, f"series-{index}")
                selected_series[region].append(series.key)
                for year in (1988, 2000, 2025):
                    self._target(series, year)

        targets = select_first_acceptance_targets(
            series_keys_by_region=selected_series,
            anchors=(1988, 2000, 2025),
            require_ready=True,
        )

        self.assertEqual(len(targets), 45)
        for region in regions:
            regional = [target for target in targets if target.country_region == region]
            self.assertEqual(len(regional), 9)
            self.assertEqual(len({target.race_series.key for target in regional}), 3)
            self.assertEqual({target.year for target in regional}, {1988, 2000, 2025})

    def test_standard_batch_enforces_region_limit_and_progress_lead(self):
        series = self._series(RacingRegion.JAPAN, "batch")
        targets = [self._target(series, 1984 + index) for index in range(43)]
        second_series = self._series(RacingRegion.JAPAN, "batch-two")
        targets.extend(self._target(second_series, 1984 + index) for index in range(8))

        with self.assertRaisesMessage(InventoryValidationError, "limit exceeded"):
            validate_standard_batch(targets, approved_region_limit=50)

        with self.assertRaisesMessage(InventoryValidationError, "lead exceeds 100"):
            validate_standard_batch(
                targets[:1],
                current_progress={
                    RacingRegion.JAPAN: 100,
                    RacingRegion.HONG_KONG: 0,
                    RacingRegion.UNITED_KINGDOM: 0,
                    RacingRegion.FRANCE: 0,
                    RacingRegion.UNITED_STATES: 0,
                },
            )

    def test_band_batch_selects_pending_targets_per_region_in_newest_year_order(self):
        regions = [
            RacingRegion.JAPAN,
            RacingRegion.HONG_KONG,
            RacingRegion.UNITED_KINGDOM,
            RacingRegion.FRANCE,
            RacingRegion.UNITED_STATES,
        ]
        for region in regions:
            series = self._series(region, "band")
            for year in range(2016, 2026):
                self._target(
                    series,
                    year,
                    resolution=HistoricalRaceResolutionStatus.PENDING,
                    with_event=False,
                )
            self._target(
                self._series(region, "outside-band"),
                2015,
                resolution=HistoricalRaceResolutionStatus.PENDING,
                with_event=False,
            )
            self._target(
                self._series(region, "already-imported"),
                2025,
                resolution=HistoricalRaceResolutionStatus.IMPORTED,
                with_event=True,
            )

        targets = select_historical_band_batch_targets(
            year_start=2016,
            year_end=2025,
            inventory_manifest_sha256="a" * 64,
            region_limit=3,
        )

        self.assertEqual(len(targets), 15)
        for region in regions:
            regional = [target for target in targets if target.country_region == region]
            self.assertEqual([target.year for target in regional], [2025, 2024, 2023])
            self.assertTrue(
                all(target.resolution_status == HistoricalRaceResolutionStatus.PENDING for target in regional)
            )
            self.assertTrue(all(target.event_id is None for target in regional))

    def test_band_batch_progress_guard_still_blocks_101_between_unfinished_regions(self):
        for region in (RacingRegion.JAPAN, RacingRegion.UNITED_KINGDOM):
            series = self._series(region, "unfinished-lead")
            for year in (2025, 2024):
                self._target(
                    series,
                    year,
                    resolution=HistoricalRaceResolutionStatus.PENDING,
                    with_event=False,
                )

        with patch(
            "stable.services.historical_race_batches.accounted_progress_by_region",
            return_value={RacingRegion.JAPAN: 101, RacingRegion.UNITED_KINGDOM: 0},
        ), self.assertRaisesMessage(InventoryValidationError, "lead exceeds 100"):
            select_historical_band_batch_targets(
                year_start=2016,
                year_end=2025,
                inventory_manifest_sha256="a" * 64,
                region_limit=1,
            )

    def test_band_batch_progress_guard_allows_exactly_100_between_unfinished_regions(self):
        for region in (RacingRegion.JAPAN, RacingRegion.UNITED_KINGDOM):
            series = self._series(region, "unfinished-boundary")
            for year in (2025, 2024):
                self._target(
                    series,
                    year,
                    resolution=HistoricalRaceResolutionStatus.PENDING,
                    with_event=False,
                )

        with patch(
            "stable.services.historical_race_batches.accounted_progress_by_region",
            return_value={RacingRegion.JAPAN: 100, RacingRegion.UNITED_KINGDOM: 0},
        ):
            targets = select_historical_band_batch_targets(
                year_start=2016,
                year_end=2025,
                inventory_manifest_sha256="a" * 64,
                region_limit=1,
            )

        self.assertEqual(len(targets), 2)

    def test_band_batch_progress_guard_ignores_regions_exhausted_after_selection(self):
        japan = self._target(
            self._series(RacingRegion.JAPAN, "exhausted"),
            2025,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )
        uk_series = self._series(RacingRegion.UNITED_KINGDOM, "still-pending")
        for year in (2025, 2024):
            self._target(
                uk_series,
                year,
                resolution=HistoricalRaceResolutionStatus.PENDING,
                with_event=False,
            )

        with patch(
            "stable.services.historical_race_batches.accounted_progress_by_region",
            return_value={RacingRegion.JAPAN: 201, RacingRegion.UNITED_KINGDOM: 101},
        ):
            targets = select_historical_band_batch_targets(
                year_start=2016,
                year_end=2025,
                inventory_manifest_sha256="a" * 64,
                region_limit=1,
            )

        self.assertIn(japan, targets)
        self.assertEqual(len(targets), 2)

    def test_band_batch_progress_guard_treats_excluded_only_region_as_exhausted(self):
        excluded = self._target(
            self._series(RacingRegion.FRANCE, "excluded-only"),
            2025,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )
        japan_series = self._series(RacingRegion.JAPAN, "continues-after-exclusion")
        for year in (2025, 2024):
            self._target(
                japan_series,
                year,
                resolution=HistoricalRaceResolutionStatus.PENDING,
                with_event=False,
            )

        with patch(
            "stable.services.historical_race_batches.accounted_progress_by_region",
            return_value={RacingRegion.JAPAN: 201, RacingRegion.FRANCE: 0},
        ):
            targets = select_historical_band_batch_targets(
                year_start=2016,
                year_end=2025,
                inventory_manifest_sha256="a" * 64,
                region_limit=1,
                excluded_target_ids=[excluded.pk],
            )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].country_region, RacingRegion.JAPAN)

    def test_band_batch_artifact_keeps_unselected_pending_region_in_progress_guard(self):
        japan_series = self._series(RacingRegion.JAPAN, "partial-selection")
        selected = self._target(
            japan_series,
            2025,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )
        self._target(
            japan_series,
            2024,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )
        self._target(
            self._series(RacingRegion.FRANCE, "unselected-pending"),
            2025,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )

        with patch(
            "stable.services.historical_race_batches.accounted_progress_by_region",
            return_value={RacingRegion.JAPAN: 101, RacingRegion.FRANCE: 0},
        ), TemporaryDirectory() as tmp, self.assertRaisesMessage(
            InventoryValidationError, "lead exceeds 100"
        ):
            write_band_batch_artifact(
                [selected],
                output_dir=Path(tmp) / "partial",
                inventory_manifest_sha256="a" * 64,
                year_start=2016,
                year_end=2025,
            )

    def test_band_batch_command_writes_reviewable_immutable_artifact(self):
        for region in (
            RacingRegion.JAPAN,
            RacingRegion.HONG_KONG,
            RacingRegion.UNITED_KINGDOM,
            RacingRegion.FRANCE,
            RacingRegion.UNITED_STATES,
        ):
            self._target(
                self._series(region, "command-band"),
                2025,
                resolution=HistoricalRaceResolutionStatus.PENDING,
                with_event=False,
            )

        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "band"
            call_command(
                "build_historical_race_band_batch",
                "--year-start",
                "2016",
                "--year-end",
                "2025",
                "--region-limit",
                "1",
                "--inventory-manifest-sha256",
                "a" * 64,
                "--output-dir",
                str(output_dir),
                verbosity=0,
            )

            snapshot = json.loads((output_dir / "selection_snapshot.json").read_text(encoding="utf-8"))
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            approval = json.loads((output_dir / "approval.json").read_text(encoding="utf-8"))
            review = (output_dir / "expected_targets_review.csv").read_text(encoding="utf-8-sig")

        self.assertEqual(snapshot["target_count"], 5)
        self.assertEqual(set(snapshot["region_counts"].values()), {1})
        self.assertEqual(manifest["year_band"], {"start": 2016, "end": 2025})
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["approved_target_ids"], [])
        self.assertEqual(review.count("\n"), 6)

    def test_band_batch_excludes_prior_selection_before_region_limit_and_preserves_denominator(self):
        targets_by_region: dict[str, list[HistoricalRaceEventTarget]] = {}
        for region in (
            RacingRegion.JAPAN,
            RacingRegion.HONG_KONG,
            RacingRegion.UNITED_KINGDOM,
            RacingRegion.FRANCE,
            RacingRegion.UNITED_STATES,
        ):
            series = self._series(region, "excluded-band")
            targets_by_region[region] = [
                self._target(
                    series,
                    year,
                    resolution=HistoricalRaceResolutionStatus.PENDING,
                    with_event=False,
                )
                for year in (2025, 2024)
            ]

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior_snapshot_path = root / "prior-selection.json"
            write_batch_snapshot(
                [targets_by_region[RacingRegion.JAPAN][0]],
                output_path=prior_snapshot_path,
                inventory_manifest_sha256="a" * 64,
            )
            prior_bytes = prior_snapshot_path.read_bytes()
            output_dir = root / "band"

            call_command(
                "build_historical_race_band_batch",
                "--year-start",
                "2016",
                "--year-end",
                "2025",
                "--region-limit",
                "1",
                "--inventory-manifest-sha256",
                "a" * 64,
                "--exclude-selection-snapshot",
                str(prior_snapshot_path),
                "--output-dir",
                str(output_dir),
                verbosity=0,
            )

            selection = json.loads((output_dir / "selection_snapshot.json").read_text(encoding="utf-8"))
            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            copied_path = output_dir / "exclusions" / "selection-001.json"

            selected_japan = [
                row for row in selection["targets"] if row["country_region"] == RacingRegion.JAPAN
            ]
            self.assertEqual(
                [row["target_id"] for row in selected_japan],
                [targets_by_region[RacingRegion.JAPAN][1].pk],
            )
            self.assertEqual(copied_path.read_bytes(), prior_bytes)
            self.assertEqual(summary["excluded_target_count"], 1)
            self.assertEqual(summary["excluded_pending_by_region"], {RacingRegion.JAPAN: 1})
            self.assertEqual(summary["available_pending_by_region"][RacingRegion.JAPAN], 2)
            self.assertEqual(summary["eligible_pending_by_region"][RacingRegion.JAPAN], 1)
            self.assertEqual(summary["remaining_pending_by_region"][RacingRegion.JAPAN], 1)
            self.assertNotIn(RacingRegion.JAPAN, summary["progress_guard_regions"])
            self.assertEqual(
                manifest["artifacts"]["excluded_selection_snapshot_001"]["path"],
                "exclusions/selection-001.json",
            )
            self.assertEqual(
                manifest["artifacts"]["excluded_selection_snapshot_001"]["sha256"],
                hashlib.sha256(prior_bytes).hexdigest(),
            )

    def test_band_batch_accepts_repeated_snapshot_and_changed_current_target_sha(self):
        series = self._series(RacingRegion.JAPAN, "imported-exclusion")
        previous = self._target(
            series,
            2025,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )
        replacement = self._target(
            series,
            2024,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior_path = root / "prior.json"
            write_batch_snapshot(
                [previous],
                output_path=prior_path,
                inventory_manifest_sha256="a" * 64,
            )
            previous.resolution_status = HistoricalRaceResolutionStatus.IMPORTED
            previous.original_name = "Changed after successful import"
            previous.save(update_fields={"resolution_status", "original_name"})
            output_dir = root / "band"

            call_command(
                "build_historical_race_band_batch",
                "--year-start",
                "2016",
                "--year-end",
                "2025",
                "--region-limit",
                "1",
                "--inventory-manifest-sha256",
                "a" * 64,
                "--exclude-selection-snapshot",
                str(prior_path),
                "--exclude-selection-snapshot",
                str(prior_path),
                "--output-dir",
                str(output_dir),
                verbosity=0,
            )

            selection = json.loads((output_dir / "selection_snapshot.json").read_text(encoding="utf-8"))
            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual([row["target_id"] for row in selection["targets"]], [replacement.pk])
            self.assertEqual(summary["excluded_snapshot_count"], 2)
            self.assertEqual(summary["excluded_target_count"], 1)
            self.assertEqual(summary["excluded_pending_by_region"], {})
            self.assertEqual((output_dir / "exclusions" / "selection-001.json").read_bytes(), prior_path.read_bytes())
            self.assertEqual((output_dir / "exclusions" / "selection-002.json").read_bytes(), prior_path.read_bytes())

    def test_band_batch_command_rejects_invalid_exclusion_without_output(self):
        target = self._target(
            self._series(RacingRegion.JAPAN, "invalid-exclusion"),
            2025,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_path = root / "valid.json"
            write_batch_snapshot(
                [target],
                output_path=valid_path,
                inventory_manifest_sha256="a" * 64,
            )
            cross_inventory_path = root / "cross-inventory.json"
            write_batch_snapshot(
                [target],
                output_path=cross_inventory_path,
                inventory_manifest_sha256="b" * 64,
            )
            drifted_path = root / "drifted.json"
            drifted_payload = json.loads(valid_path.read_text(encoding="utf-8"))
            drifted_payload["targets"][0]["year"] = 2024
            drifted_path.write_text(json.dumps(drifted_payload), encoding="utf-8")
            unknown_target_path = root / "unknown-target.json"
            unknown_payload = json.loads(valid_path.read_text(encoding="utf-8"))
            unknown_payload["targets"][0]["target_id"] = target.pk + 1000
            unsigned = dict(unknown_payload)
            unsigned.pop("snapshot_sha256")
            unknown_payload["snapshot_sha256"] = hashlib.sha256(
                canonical_json(unsigned).encode("utf-8")
            ).hexdigest()
            unknown_target_path.write_text(json.dumps(unknown_payload), encoding="utf-8")
            duplicate_target_path = root / "duplicate-target.json"
            duplicate_payload = json.loads(valid_path.read_text(encoding="utf-8"))
            duplicate_payload["targets"].append(dict(duplicate_payload["targets"][0]))
            duplicate_payload["target_count"] = 2
            duplicate_payload["region_counts"] = {RacingRegion.JAPAN: 2}
            duplicate_unsigned = dict(duplicate_payload)
            duplicate_unsigned.pop("snapshot_sha256")
            duplicate_payload["snapshot_sha256"] = hashlib.sha256(
                canonical_json(duplicate_unsigned).encode("utf-8")
            ).hexdigest()
            duplicate_target_path.write_text(json.dumps(duplicate_payload), encoding="utf-8")

            for label, exclusion_path, message in (
                ("cross", cross_inventory_path, "inventory mismatch"),
                ("drift", drifted_path, "SHA is invalid"),
                ("unknown", unknown_target_path, "target identity is invalid"),
                ("duplicate", duplicate_target_path, "target identity is invalid"),
            ):
                with self.subTest(label=label):
                    output_dir = root / f"output-{label}"
                    with self.assertRaisesMessage(CommandError, message):
                        call_command(
                            "build_historical_race_band_batch",
                            "--year-start",
                            "2016",
                            "--year-end",
                            "2025",
                            "--region-limit",
                            "1",
                            "--inventory-manifest-sha256",
                            "a" * 64,
                            "--exclude-selection-snapshot",
                            str(exclusion_path),
                            "--output-dir",
                            str(output_dir),
                            verbosity=0,
                        )
                    self.assertFalse(output_dir.exists())

    def test_band_batch_artifact_rejects_selection_exclusion_intersection(self):
        target = self._target(
            self._series(RacingRegion.FRANCE, "selection-intersection"),
            2025,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior_path = root / "prior.json"
            write_batch_snapshot(
                [target],
                output_path=prior_path,
                inventory_manifest_sha256="a" * 64,
            )
            exclusion = read_immutable_selection_snapshot(
                prior_path,
                inventory_manifest_sha256="a" * 64,
            )
            output_dir = root / "output"

            with self.assertRaisesMessage(InventoryValidationError, "intersects exclusion"):
                write_band_batch_artifact(
                    [target],
                    output_dir=output_dir,
                    inventory_manifest_sha256="a" * 64,
                    year_start=2016,
                    year_end=2025,
                    exclusion_snapshots=[exclusion],
                )

            self.assertFalse(output_dir.exists())

    def test_band_batch_artifact_rejects_empty_duplicate_and_non_pending_targets(self):
        with TemporaryDirectory() as tmp, self.assertRaisesMessage(
            InventoryValidationError, "no pending targets"
        ):
            write_band_batch_artifact(
                [],
                output_dir=Path(tmp) / "empty",
                inventory_manifest_sha256="a" * 64,
                year_start=2016,
                year_end=2025,
            )

        target = self._target(
            self._series(RacingRegion.JAPAN, "invalid-band"),
            2025,
            resolution=HistoricalRaceResolutionStatus.PENDING,
            with_event=False,
        )
        with TemporaryDirectory() as tmp, self.assertRaisesMessage(
            InventoryValidationError, "duplicate targets"
        ):
            write_band_batch_artifact(
                [target, target],
                output_dir=Path(tmp) / "duplicate",
                inventory_manifest_sha256="a" * 64,
                year_start=2016,
                year_end=2025,
            )

        target.resolution_status = HistoricalRaceResolutionStatus.IMPORTED
        target.save(update_fields={"resolution_status"})
        with TemporaryDirectory() as tmp, self.assertRaisesMessage(
            InventoryValidationError, "not pending"
        ):
            write_band_batch_artifact(
                [target],
                output_dir=Path(tmp) / "imported",
                inventory_manifest_sha256="a" * 64,
                year_start=2016,
                year_end=2025,
            )

    def test_batch_snapshot_binds_target_and_inventory_identities(self):
        target = self._target(self._series(RacingRegion.FRANCE, "snapshot"), 1984)
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "batch.json"
            payload = write_batch_snapshot(
                [target],
                output_path=output,
                inventory_manifest_sha256="b" * 64,
            )

            self.assertTrue(output.is_file())
            self.assertEqual(payload["target_count"], 1)
            self.assertEqual(len(payload["targets"][0]["target_sha256"]), 64)
            self.assertEqual(len(payload["snapshot_sha256"]), 64)

    @override_settings(
        HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET=10,
        HISTORICAL_RACE_BACKFILL_MAX_SOURCE_CACHE_BYTES=1024,
    )
    def test_orchestrator_only_accepts_unchanged_ready_ledger_targets(self):
        target = self._target(self._series(RacingRegion.FRANCE, "orchestration"), 1984)
        plan = {
            "target_layer": "race_event",
            "historical_inventory_sha256": "a" * 64,
            "batch_size": 50,
            "max_source_cache_bytes": 1024,
            "min_free_disk_bytes": 1,
            "rate_limit": {"max_requests": 1, "request_interval_seconds": 1},
            "regions": [
                {
                    "region": RacingRegion.FRANCE,
                    "source": "official_fixture",
                    "source_authority": "official",
                    "modules": {"runners": {}, "results": {}, "history_winners": {}},
                    "targets": [target_identity(target)],
                }
            ],
            "adapters": [],
        }

        validate_plan(plan)
        expected = expected_targets_from_plan(plan)
        self.assertEqual(expected[0]["historical_target_id"], target.pk)

        target.original_name = "Changed after approval"
        target.save(update_fields={"original_name"})
        with self.assertRaisesMessage(PlanValidationError, "changed after approval"):
            expected_targets_from_plan(plan)


class HistoricalRaceImporterTests(HistoricalRaceBatchTests):
    def _ready_target(self):
        return self._target(self._series(RacingRegion.FRANCE, "importer"), 1984)

    def _results(self, *, complete=True, trainer_name="Trainer"):
        return {
            "is_complete": complete,
            "source_cache_identity": {"sha256": "f" * 64},
            "items": [
                {
                    "finish_position": 1,
                    "official_finish_position": 1,
                    "horse_number": "1",
                    "horse_name": "Winner",
                    "jockey_name": "Jockey",
                    "trainer_name": trainer_name,
                    "finish_time": "2:30.0",
                    "source_refs": {"official_result": True},
                },
                {
                    "finish_position": 2,
                    "official_finish_position": 1,
                    "horse_number": "2",
                    "horse_name": "Dead Heat Winner",
                    "jockey_name": "Jockey Two",
                    "trainer_name": trainer_name,
                    "finish_time": "2:30.0",
                    "source_refs": {"official_result": True},
                },
            ],
        }

    def test_complete_results_derive_runners_and_preserve_dead_heat_positions(self):
        target = self._ready_target()
        identity = target_identity(target)
        term_count_before = TermEntry.objects.count()
        horse_count_before = HorseProfile.objects.count()

        counts = apply_historical_target_candidate(
            target_id=target.pk,
            expected_target_sha256=identity["target_sha256"],
            inventory_artifact_sha256="a" * 64,
            source_name="official_fixture",
            source_url="https://official.test/result",
            modules={"results": self._results()},
        )

        target.refresh_from_db()
        self.assertEqual(counts, {"runners": 2, "results": 2, "history_winners": 0})
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.IMPORTED)
        self.assertEqual(
            list(target.event.results.values_list("official_finish_position", flat=True)),
            [1, 1],
        )
        self.assertTrue(
            all(row.source_refs.get("derived_from_results") for row in target.event.runners.all())
        )
        self.assertEqual(
            {gap["source_text"] for gap in target.module_statuses["term_gaps"]},
            {"Winner", "Dead Heat Winner", "Jockey", "Jockey Two"},
        )
        self.assertEqual(TermEntry.objects.count(), term_count_before)
        self.assertEqual(HorseProfile.objects.count(), horse_count_before)

    def test_partial_results_fail_without_writes(self):
        target = self._ready_target()
        with self.assertRaisesMessage(InventoryValidationError, "complete results"):
            apply_historical_target_candidate(
                target_id=target.pk,
                expected_target_sha256=target_identity(target)["target_sha256"],
                inventory_artifact_sha256="a" * 64,
                source_name="fixture",
                source_url="https://official.test/result",
                modules={"results": self._results(complete=False)},
            )

        target.refresh_from_db()
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.READY)
        self.assertFalse(RaceEventDataCandidate.objects.exists())

    def test_duplicate_runner_horse_numbers_fail_during_validation(self):
        target = self._ready_target()
        runners = {
            "is_complete": True,
            "items": [
                {"horse_number": "SCR", "horse_name": "One"},
                {"horse_number": "SCR", "horse_name": "Two"},
            ],
        }
        with self.assertRaisesMessage(InventoryValidationError, "duplicate horse_number"):
            apply_historical_target_candidate(
                target_id=target.pk,
                expected_target_sha256=target_identity(target)["target_sha256"],
                inventory_artifact_sha256="a" * 64,
                source_name="fixture",
                source_url="https://official.test/result",
                modules={"runners": runners, "results": self._results()},
            )

        self.assertFalse(target.event.runners.exists())

    def test_duplicate_storage_finish_positions_fail_during_validation(self):
        target = self._ready_target()
        results = self._results()
        results["items"][1]["finish_position"] = 1
        with self.assertRaisesMessage(InventoryValidationError, "duplicate finish_position"):
            apply_historical_target_candidate(
                target_id=target.pk,
                expected_target_sha256=target_identity(target)["target_sha256"],
                inventory_artifact_sha256="a" * 64,
                source_name="fixture",
                source_url="https://official.test/result",
                modules={"results": results},
            )

        self.assertFalse(target.event.results.exists())

    def test_field_completeness_regression_is_blocked(self):
        target = self._ready_target()
        RaceEventResult.objects.create(
            event=target.event,
            finish_position=1,
            official_finish_position=1,
            horse_name="Existing",
            trainer_name="Existing Trainer",
        )
        RaceEventRunner.objects.create(
            event=target.event,
            horse_number="1",
            horse_name="Existing",
            trainer_name="Existing Trainer",
        )

        with self.assertRaisesMessage(InventoryValidationError, "trainer_name"):
            apply_historical_target_candidate(
                target_id=target.pk,
                expected_target_sha256=target_identity(target)["target_sha256"],
                inventory_artifact_sha256="a" * 64,
                source_name="fixture",
                source_url="https://official.test/result",
                modules={"results": self._results(trainer_name="")},
            )

        self.assertEqual(target.event.results.get().trainer_name, "Existing Trainer")

    def test_scope_failure_rolls_back_candidates_rows_and_target_status(self):
        target = self._ready_target()
        identity = target_identity(target)
        original_apply = __import__(
            "stable.services.historical_race_importer",
            fromlist=["apply_data_candidate"],
        ).apply_data_candidate
        calls = {"count": 0}

        def fail_second(candidate, *, user=None):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("simulated result failure")
            return original_apply(candidate, user=user)

        with patch("stable.services.historical_race_importer.apply_data_candidate", side_effect=fail_second):
            with self.assertRaisesMessage(RuntimeError, "simulated result failure"):
                apply_historical_target_candidate(
                    target_id=target.pk,
                    expected_target_sha256=identity["target_sha256"],
                    inventory_artifact_sha256="a" * 64,
                    source_name="fixture",
                    source_url="https://official.test/result",
                    modules={"results": self._results()},
                )

        target.refresh_from_db()
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.READY)
        self.assertFalse(RaceEventDataCandidate.objects.exists())
        self.assertFalse(target.event.runners.exists())
        self.assertFalse(target.event.results.exists())

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_historical_import_command_dry_run_then_applies_exact_candidate_sha(self):
        target = self._ready_target()
        record = {
            "target_id": target.pk,
            "target_sha256": target_identity(target)["target_sha256"],
            "inventory_artifact_sha256": "a" * 64,
            "source_name": "official_fixture",
            "source_url": "https://official.test/result",
            "modules": {"results": self._results()},
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            identity = hashlib.sha256(path.read_bytes()).hexdigest()

            call_command(
                "import_historical_race_event_candidates",
                "--jsonl",
                str(path),
                "--expected-sha256",
                identity,
                "--dry-run",
                verbosity=0,
            )
            self.assertFalse(target.event.results.exists())
            call_command(
                "import_historical_race_event_candidates",
                "--jsonl",
                str(path),
                "--expected-sha256",
                identity,
                "--apply",
                verbosity=0,
            )

        target.refresh_from_db()
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.IMPORTED)

    def test_historical_import_command_rejects_wrong_candidate_sha(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.jsonl"
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesMessage(CommandError, "candidate_sha256_mismatch"):
                call_command(
                    "import_historical_race_event_candidates",
                    "--jsonl",
                    str(path),
                    "--expected-sha256",
                    "0" * 64,
                    "--dry-run",
                    verbosity=0,
                )

    def test_champion_supplement_is_single_year_and_does_not_fake_complete_results(self):
        target = self._ready_target()
        target.resolution_status = HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE
        target.save(update_fields={"resolution_status"})
        identity = target_identity(target)

        count = apply_historical_champion_supplement(
            target_id=target.pk,
            expected_target_sha256=identity["target_sha256"],
            source_authority="official_archive",
            source_refs={"url": "https://official.test/archive", "sha256": "f" * 64},
            winners=[{"winner_year": 1984, "horse_name": "Known Champion"}],
        )

        target.refresh_from_db()
        self.assertEqual(count, 1)
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE)
        self.assertEqual(target.module_statuses["history_winners"], "supplemented")
        self.assertTrue(target.event.history_winners.filter(horse_name="Known Champion").exists())
        self.assertFalse(target.event.results.exists())

    def test_coverage_keeps_gaps_without_blocking_complete_scopes(self):
        complete = self._ready_target()
        gap = self._target(self._series(RacingRegion.FRANCE, "gap"), 1985)
        expected = [target_identity(complete), target_identity(gap)]
        candidate = {
            "target_id": complete.pk,
            "source_name": "official_fixture",
            "source_url": "https://official.test/result",
            "modules": {"results": self._results()},
        }

        coverage = audit_historical_candidate_coverage(
            expected_targets=expected,
            candidate_records=[candidate],
        )

        self.assertEqual(coverage["complete_count"], 1)
        self.assertEqual(coverage["gap_count"], 1)
        self.assertEqual(coverage["complete_scopes"][0]["target_id"], complete.pk)
        self.assertEqual(coverage["gaps"][0]["target_id"], gap.pk)

    def test_authoritative_basic_update_preserves_manual_locks_and_audits_diff(self):
        target = self._ready_target()
        target.field_provenance = {
            "racecourse": {"source_authority": "reference", "source_id": "old"}
        }
        target.save(update_fields={"field_provenance"})
        target.event.manual_lock_flags = {"chinese_name": True}
        target.event.save(update_fields={"manual_lock_flags"})

        result = apply_authoritative_event_fields(
            target_id=target.pk,
            artifact_sha256="9" * 64,
            candidates=[
                {
                    "source_authority": "official_archive",
                    "source_id": "yearbook",
                    "source_url": "https://official.test/yearbook",
                    "fields": {"racecourse": "Historical Course", "chinese_name": "禁止覆盖"},
                }
            ],
        )

        target.event.refresh_from_db()
        self.assertEqual(target.event.racecourse, "Historical Course")
        self.assertNotEqual(target.event.chinese_name, "禁止覆盖")
        self.assertEqual(result["skipped_manual"], ["chinese_name"])
        self.assertTrue(OperationLog.objects.filter(action_type="historical_event_fields_updated").exists())

    def test_same_authority_basic_conflict_rolls_back_all_fields(self):
        target = self._ready_target()
        before = target.event.racecourse

        with self.assertRaisesMessage(InventoryValidationError, "racecourse"):
            apply_authoritative_event_fields(
                target_id=target.pk,
                artifact_sha256="8" * 64,
                candidates=[
                    {
                        "source_authority": "official_archive",
                        "source_id": "a",
                        "fields": {"racecourse": "Course A"},
                    },
                    {
                        "source_authority": "official_archive",
                        "source_id": "b",
                        "fields": {"racecourse": "Course B"},
                    },
                ],
            )

        target.event.refresh_from_db()
        self.assertEqual(target.event.racecourse, before)

    def _authoritative_field_record(self, target, *, fields=None, **candidate_overrides):
        candidate = {
            "source_authority": "official",
            "source_id": "official-result-2025",
            "source_url": "https://official.test/results/2025",
            "snapshot_sha256": "b" * 64,
            "parser_version": "2026.07.1",
            "fields": fields if fields is not None else {"distance_text": "2400m"},
        }
        candidate.update(candidate_overrides)
        return {
            "target_id": target.pk,
            "target_sha256": target_identity(target)["target_sha256"],
            "inventory_artifact_sha256": target.artifact_sha256,
            "field_artifact_sha256": "c" * 64,
            "candidates": [candidate],
        }

    def _write_authoritative_field_jsonl(self, root: Path, records: list[dict]):
        path = root / "authoritative_fields.jsonl"
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_authoritative_field_command_dry_run_then_preserves_explicit_distance_unit(self):
        target = self._ready_target()
        target.event.distance_text = "2400"
        target.event.save(update_fields={"distance_text"})
        record = self._authoritative_field_record(target)
        with TemporaryDirectory() as tmp:
            path, candidate_sha = self._write_authoritative_field_jsonl(Path(tmp), [record])
            dry_run_output = StringIO()
            call_command(
                "import_historical_race_event_field_candidates",
                "--jsonl",
                str(path),
                "--expected-sha256",
                candidate_sha,
                "--dry-run",
                stdout=dry_run_output,
                verbosity=0,
            )
            target.event.refresh_from_db()
            self.assertEqual(target.event.distance_text, "2400")
            report = json.loads(dry_run_output.getvalue())
            self.assertEqual(report["updated_field_count"], 1)
            self.assertEqual(report["scopes"][0]["before"], {"distance_text": "2400"})
            self.assertEqual(report["scopes"][0]["after"], {"distance_text": "2400m"})

            call_command(
                "import_historical_race_event_field_candidates",
                "--jsonl",
                str(path),
                "--expected-sha256",
                candidate_sha,
                "--apply",
                verbosity=0,
            )

        target.event.refresh_from_db()
        self.assertEqual(target.event.distance_text, "2400m")
        log = OperationLog.objects.get(action_type="historical_event_fields_updated")
        self.assertEqual(json.loads(log.detail)["before"], {"distance_text": "2400"})
        self.assertEqual(json.loads(log.detail)["after"], {"distance_text": "2400m"})

    def test_authoritative_field_command_rejects_unknown_field_and_incomplete_evidence(self):
        target = self._ready_target()
        cases = [
            self._authoritative_field_record(target, fields={"country_region": RacingRegion.FRANCE}),
            self._authoritative_field_record(target, snapshot_sha256=""),
            self._authoritative_field_record(target, source_url="http://official.test/results/2025"),
        ]
        for index, record in enumerate(cases):
            with self.subTest(index=index), TemporaryDirectory() as tmp:
                path, candidate_sha = self._write_authoritative_field_jsonl(Path(tmp), [record])
                with self.assertRaises(CommandError):
                    call_command(
                        "import_historical_race_event_field_candidates",
                        "--jsonl",
                        str(path),
                        "--expected-sha256",
                        candidate_sha,
                        "--dry-run",
                        verbosity=0,
                    )
        target.event.refresh_from_db()
        self.assertEqual(target.event.country_region, target.country_region)

    def test_authoritative_field_command_rejects_wrong_file_sha_and_duplicate_targets(self):
        target = self._ready_target()
        record = self._authoritative_field_record(target)
        with TemporaryDirectory() as tmp:
            path, _candidate_sha = self._write_authoritative_field_jsonl(Path(tmp), [record])
            with self.assertRaisesMessage(CommandError, "candidate_sha256_mismatch"):
                call_command(
                    "import_historical_race_event_field_candidates",
                    "--jsonl",
                    str(path),
                    "--expected-sha256",
                    "0" * 64,
                    "--dry-run",
                    verbosity=0,
                )
            duplicate_path, duplicate_sha = self._write_authoritative_field_jsonl(
                Path(tmp), [record, record]
            )
            with self.assertRaisesMessage(CommandError, "duplicate targets"):
                call_command(
                    "import_historical_race_event_field_candidates",
                    "--jsonl",
                    str(duplicate_path),
                    "--expected-sha256",
                    duplicate_sha,
                    "--dry-run",
                    verbosity=0,
                )

    def test_authoritative_field_command_rejects_apply_when_backfill_is_disabled(self):
        target = self._ready_target()
        record = self._authoritative_field_record(target)
        with TemporaryDirectory() as tmp:
            path, candidate_sha = self._write_authoritative_field_jsonl(Path(tmp), [record])
            with self.assertRaisesMessage(CommandError, "historical race backfill is disabled"):
                call_command(
                    "import_historical_race_event_field_candidates",
                    "--jsonl",
                    str(path),
                    "--expected-sha256",
                    candidate_sha,
                    "--apply",
                    verbosity=0,
                )

        target.event.refresh_from_db()
        self.assertEqual(target.event.distance_text, "")

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_authoritative_field_command_preserves_manual_lock(self):
        target = self._ready_target()
        target.event.distance_text = "3m"
        target.event.manual_lock_flags = {"distance_text": True}
        target.event.save(update_fields={"distance_text", "manual_lock_flags"})
        record = self._authoritative_field_record(target, fields={"distance_text": "3m 210y"})
        with TemporaryDirectory() as tmp:
            path, candidate_sha = self._write_authoritative_field_jsonl(Path(tmp), [record])
            output = StringIO()
            call_command(
                "import_historical_race_event_field_candidates",
                "--jsonl",
                str(path),
                "--expected-sha256",
                candidate_sha,
                "--apply",
                stdout=output,
                verbosity=0,
            )

        target.event.refresh_from_db()
        self.assertEqual(target.event.distance_text, "3m")
        self.assertEqual(json.loads(output.getvalue())["scopes"][0]["skipped_manual"], ["distance_text"])

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_authoritative_field_command_rejects_one_drifted_target_before_any_write(self):
        first = self._ready_target()
        second = self._target(self._series(RacingRegion.FRANCE, "field-drift"), 1985)
        records = [
            self._authoritative_field_record(first, fields={"distance_text": "2400m"}),
            self._authoritative_field_record(second, fields={"distance_text": "2000m"}),
        ]
        second.event.racecourse = "Changed after approval"
        second.event.save(update_fields={"racecourse"})
        with TemporaryDirectory() as tmp:
            path, candidate_sha = self._write_authoritative_field_jsonl(Path(tmp), records)
            with self.assertRaisesMessage(CommandError, "changed after field approval"):
                call_command(
                    "import_historical_race_event_field_candidates",
                    "--jsonl",
                    str(path),
                    "--expected-sha256",
                    candidate_sha,
                    "--apply",
                    verbosity=0,
                )

        first.event.refresh_from_db()
        self.assertEqual(first.event.distance_text, "")
        self.assertFalse(OperationLog.objects.filter(action_type="historical_event_fields_updated").exists())

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_authoritative_field_command_rolls_back_whole_batch_on_late_failure(self):
        first = self._ready_target()
        second = self._target(self._series(RacingRegion.FRANCE, "field-rollback"), 1985)
        records = [self._authoritative_field_record(first), self._authoritative_field_record(second)]
        original = apply_authoritative_event_fields
        calls = {"count": 0}

        def fail_second(**kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("simulated field apply failure")
            return original(**kwargs)

        with TemporaryDirectory() as tmp:
            path, candidate_sha = self._write_authoritative_field_jsonl(Path(tmp), records)
            with patch(
                "stable.services.historical_race_importer.apply_authoritative_event_fields",
                side_effect=fail_second,
            ):
                with self.assertRaisesMessage(RuntimeError, "simulated field apply failure"):
                    call_command(
                        "import_historical_race_event_field_candidates",
                        "--jsonl",
                        str(path),
                        "--expected-sha256",
                        candidate_sha,
                        "--apply",
                        verbosity=0,
                    )

        first.event.refresh_from_db()
        second.event.refresh_from_db()
        self.assertEqual(first.event.distance_text, "")
        self.assertEqual(second.event.distance_text, "")
        self.assertFalse(OperationLog.objects.filter(action_type="historical_event_fields_updated").exists())

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_authoritative_field_apply_invalidates_old_detail_target_sha(self):
        target = self._ready_target()
        old_target_sha = target_identity(target)["target_sha256"]
        record = self._authoritative_field_record(target)
        with TemporaryDirectory() as tmp:
            path, candidate_sha = self._write_authoritative_field_jsonl(Path(tmp), [record])
            call_command(
                "import_historical_race_event_field_candidates",
                "--jsonl",
                str(path),
                "--expected-sha256",
                candidate_sha,
                "--apply",
                verbosity=0,
            )

        with self.assertRaisesMessage(InventoryValidationError, "changed after candidate approval"):
            apply_historical_target_candidate(
                target_id=target.pk,
                expected_target_sha256=old_target_sha,
                inventory_artifact_sha256=target.artifact_sha256,
                source_name="fixture",
                source_url="https://official.test/result",
                modules={"results": self._results()},
            )

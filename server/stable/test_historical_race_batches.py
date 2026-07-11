from __future__ import annotations

import hashlib
import json
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
    materialize_historical_event,
    select_first_acceptance_targets,
    target_identity,
    validate_standard_batch,
    write_batch_snapshot,
)
from stable.services.historical_race_inventory import InventoryValidationError
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
            current_year=2026,
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
            validate_standard_batch(targets)

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

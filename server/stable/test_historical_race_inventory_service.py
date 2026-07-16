from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventDataQuality,
    RaceEventHistoryWinner,
    RaceEventPriority,
    RaceEventResult,
    RaceEventRunner,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesName,
    RaceSeriesRelation,
    RaceSeriesRelationType,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.historical_race_inventory import (
    InventoryValidationError,
    build_inventory_artifact,
    build_existing_event_mapping_artifact,
    commit_existing_event_mapping,
    commit_inventory_artifact,
    inventory_summary,
    expectation_status_for_date,
    file_identity,
    merge_authoritative_fields,
    propose_series_mapping,
    publish_historical_target,
    sanitize_structured_row_evidence,
    transition_target_resolution,
    validate_inventory_artifact,
    validate_mapping_artifact,
    validate_permanent_unavailable_evidence,
    validate_resolution_transition,
    validate_series_name_period,
    validate_series_relation,
)
from stable.services.race_event_crawl_orchestration import (
    PlanValidationError,
    validate_historical_plan_budgets,
    validate_prepare_authorization,
)
from stable.services.race_event_public_cache import (
    invalidate_public_race_cache,
    public_race_calendar_years,
    public_race_sitemap_count,
)


class HistoricalRaceInventoryServiceTests(TestCase):
    def _series(self, key: str) -> RaceSeries:
        return RaceSeries.objects.create(
            key=key,
            country_region=RacingRegion.UNITED_KINGDOM,
            canonical_name_original=key,
            review_status=RaceSeriesReviewStatus.APPROVED,
        )

    def test_official_value_wins_without_majority_vote(self):
        result = merge_authoritative_fields(
            [
                {
                    "source_authority": "official_current",
                    "source_id": "official",
                    "fields": {"winner": "Official Horse"},
                },
                {
                    "source_authority": "reference",
                    "source_id": "copy-1",
                    "fields": {"winner": "Copied Error"},
                },
                {
                    "source_authority": "reference",
                    "source_id": "copy-2",
                    "fields": {"winner": "Copied Error"},
                },
            ]
        )

        self.assertEqual(result["fields"]["winner"], "Official Horse")
        self.assertFalse(result["blocked"])
        self.assertEqual(len(result["lower_authority_disagreements"]), 2)

    def test_third_party_database_outranks_third_party_and_reference(self):
        result = merge_authoritative_fields(
            [
                {
                    "source_authority": "reference",
                    "source_id": "reference",
                    "fields": {"winner": "Reference Horse"},
                },
                {
                    "source_authority": "third_party",
                    "source_id": "third-party",
                    "fields": {"winner": "Third Party Horse"},
                },
                {
                    "source_authority": "third_party_database",
                    "source_id": "database",
                    "fields": {"winner": "Database Horse"},
                },
            ]
        )

        self.assertEqual(result["fields"]["winner"], "Database Horse")
        self.assertEqual(result["field_provenance"]["winner"]["source_authority"], "third_party_database")
        self.assertFalse(result["blocked"])
        self.assertEqual(len(result["lower_authority_disagreements"]), 2)

    def test_lower_authority_fills_blank_field(self):
        result = merge_authoritative_fields(
            [{"source_authority": "reference", "source_id": "reference", "fields": {"racecourse": "Epsom"}}],
            existing_fields={"winner": "Official Horse", "racecourse": ""},
            existing_provenance={"winner": {"source_authority": "official_current"}},
        )

        self.assertEqual(result["fields"]["winner"], "Official Horse")
        self.assertEqual(result["fields"]["racecourse"], "Epsom")

    def test_same_authority_conflict_blocks_field(self):
        result = merge_authoritative_fields(
            [
                {"source_authority": "official_archive", "source_id": "a", "fields": {"winner": "A"}},
                {"source_authority": "official_archive", "source_id": "b", "fields": {"winner": "B"}},
            ]
        )

        self.assertTrue(result["blocked"])
        self.assertNotIn("winner", result["fields"])

    def test_manual_lock_preserves_existing_value(self):
        result = merge_authoritative_fields(
            [{"source_authority": "official_current", "source_id": "official", "fields": {"winner": "New"}}],
            existing_fields={"winner": "Manual"},
            manual_locks={"winner": True},
        )

        self.assertEqual(result["fields"]["winner"], "Manual")
        self.assertEqual(result["skipped_manual"][0]["field"], "winner")

    def test_relation_cycle_is_rejected_with_path(self):
        first = self._series("first")
        second = self._series("second")
        third = self._series("third")
        approver = get_user_model().objects.create_user(username="lineage-reviewer")
        for source, target in ((first, second), (second, third)):
            RaceSeriesRelation.objects.create(
                from_series=source,
                to_series=target,
                relation_type=RaceSeriesRelationType.SUCCESSOR,
                review_status=RaceSeriesReviewStatus.APPROVED,
                approved_by=approver,
                approved_at=timezone.now(),
            )
        relation = RaceSeriesRelation(
            from_series=third,
            to_series=first,
            relation_type=RaceSeriesRelationType.SUCCESSOR,
            review_status=RaceSeriesReviewStatus.APPROVED,
            approved_by=approver,
            approved_at=timezone.now(),
        )

        with self.assertRaisesMessage(ValidationError, "形成循环"):
            validate_series_relation(relation)

    def test_series_name_overlap_is_rejected_and_fuzzy_name_never_auto_matches(self):
        series = self._series("the-derby")
        RaceSeriesName.objects.create(
            series=series,
            text="Sponsored Derby",
            source_language="en",
            valid_from_year=1990,
            valid_to_year=2000,
        )
        overlap = RaceSeriesName(
            series=series,
            text="sponsored derby",
            source_language="en",
            valid_from_year=1999,
            valid_to_year=2005,
        )
        with self.assertRaisesMessage(ValidationError, "有效期"):
            validate_series_name_period(overlap)

        mapping = propose_series_mapping(
            name="Sponsored Derbi",
            region=RacingRegion.UNITED_KINGDOM,
            year=1999,
            fuzzy_threshold=0.8,
        )
        self.assertEqual(mapping["status"], HistoricalRaceResolutionStatus.IDENTITY_REVIEW_REQUIRED)
        self.assertEqual(mapping["candidates"][0]["series_key"], series.key)

    def test_permanent_gap_sources_must_be_complete_and_independent(self):
        evidence = {
            "official_archive": {
                "url": "https://official.test/archive",
                "checked_at": "2026-07-12T00:00:00Z",
                "query_scope": "1984 Derby",
                "snapshot_sha256": "a" * 64,
            },
            "independent_source": {
                "url": "https://database.test/result",
                "checked_at": "2026-07-12T00:01:00Z",
                "query_scope": "1984 Derby",
                "snapshot_sha256": "b" * 64,
            },
        }
        validate_permanent_unavailable_evidence(evidence)

        evidence["independent_source"]["url"] = "https://official.test/mirror"
        with self.assertRaisesMessage(ValidationError, "相互独立"):
            validate_permanent_unavailable_evidence(evidence)

    def test_imported_target_cannot_be_silently_downgraded(self):
        target = HistoricalRaceEventTarget(
            race_series=self._series("imported"),
            year=1984,
            country_region=RacingRegion.UNITED_KINGDOM,
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
        )

        with self.assertRaises(ValidationError):
            validate_resolution_transition(target, HistoricalRaceResolutionStatus.READY)

    def test_permanent_gap_transition_and_reopen_are_audited(self):
        actor = get_user_model().objects.create_user(username="gap-approver")
        target = HistoricalRaceEventTarget.objects.create(
            race_series=self._series("permanent-gap"),
            year=1984,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
        )
        evidence = {
            "official_archive": {
                "url": "https://official.test/archive",
                "checked_at": "2026-07-12T00:00:00Z",
                "query_scope": "1984",
                "snapshot_sha256": "a" * 64,
            },
            "independent_source": {
                "url": "https://database.test/result",
                "checked_at": "2026-07-12T00:01:00Z",
                "query_scope": "1984",
                "snapshot_sha256": "b" * 64,
            },
        }

        transition_target_resolution(
            target,
            HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE,
            actor=actor,
            reason="双来源核查无资料",
            artifact_sha256="c" * 64,
            permanent_evidence=evidence,
        )
        transition_target_resolution(
            target,
            HistoricalRaceResolutionStatus.PENDING,
            actor=actor,
            reason="发现新档案，重新开启",
        )

        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.PENDING)
        self.assertEqual(target.permanent_unavailable_evidence, {})
        self.assertEqual(
            OperationLog.objects.filter(action_type="historical_target_resolution_transition").count(),
            2,
        )

    def test_structured_row_evidence_rejects_full_documents_and_oversized_rows(self):
        self.assertEqual(sanitize_structured_row_evidence({"horse_name": "Example"})["horse_name"], "Example")
        with self.assertRaisesMessage(InventoryValidationError, "full document"):
            sanitize_structured_row_evidence({"raw_html": "<!doctype html><html></html>"})
        with self.assertRaisesMessage(InventoryValidationError, "exceeds"):
            sanitize_structured_row_evidence({"notes": "x" * 100}, max_bytes=32)

    def test_summary_separates_accounted_and_data_complete_rates(self):
        summary = inventory_summary(
            [
                {"expectation_status": "held", "resolution_status": "imported"},
                {"expectation_status": "not_held", "resolution_status": "pending"},
                {"expectation_status": "held", "resolution_status": "permanently_unavailable"},
                {"expectation_status": "held", "resolution_status": "source_unavailable"},
            ]
        )

        self.assertEqual(summary["accounted_rate"], 0.75)
        self.assertEqual(summary["data_complete_rate"], 0.25)

    def test_future_and_grace_period_targets_are_not_due(self):
        self.assertEqual(
            expectation_status_for_date(
                target_year=2026,
                local_date=date(2026, 7, 10),
                today=date(2026, 7, 12),
                result_grace_days=3,
            ),
            HistoricalRaceExpectationStatus.NOT_DUE,
        )
        self.assertEqual(
            expectation_status_for_date(
                target_year=2026,
                local_date=date(2026, 7, 10),
                today=date(2026, 7, 14),
                result_grace_days=3,
            ),
            HistoricalRaceExpectationStatus.HELD,
        )

    @override_settings(
        HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET=10,
        HISTORICAL_RACE_BACKFILL_MAX_SOURCE_CACHE_BYTES=1024,
    )
    def test_historical_plan_budgets_fail_closed_at_configured_ceilings(self):
        plan = {
            "historical_inventory_sha256": "a" * 64,
            "rate_limit": {"max_requests": 11},
            "max_source_cache_bytes": 1024,
            "min_free_disk_bytes": 1,
        }

        with self.assertRaisesMessage(PlanValidationError, "request budget"):
            validate_historical_plan_budgets(plan)

    @override_settings(
        HISTORICAL_RACE_BACKFILL_ENABLED=True,
        HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=False,
        HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET=10,
        HISTORICAL_RACE_BACKFILL_MAX_SOURCE_CACHE_BYTES=1024,
    )
    def test_historical_prepare_requires_global_network_switch(self):
        plan = {
            "historical_inventory_sha256": "a" * 64,
            "allow_network": True,
            "rate_limit": {"max_requests": 1},
            "max_source_cache_bytes": 1024,
            "min_free_disk_bytes": 1,
            "adapters": [],
        }

        with self.assertRaisesMessage(PlanValidationError, "network access is disabled"):
            validate_prepare_authorization(plan)


class HistoricalRaceInventoryArtifactTests(TestCase):
    def _event(self, *, slug: str, series_key: str, name: str) -> RaceEvent:
        return RaceEvent.objects.create(
            year=2026,
            slug=slug,
            series_key=series_key,
            original_name=name,
            chinese_name=name,
            country_region=RacingRegion.UNITED_STATES,
            racecourse="Test Course",
            grade_text="Grade 1",
            surface=RaceEventSurface.DIRT,
        )

    def _write_input(self, root: Path) -> Path:
        path = root / "catalog.jsonl"
        rows = [
            {
                "series_key": "uk-derby",
                "region": "united_kingdom",
                "year": 1984,
                "canonical_name_original": "The Derby",
                "chinese_name": "叶森德比",
                "original_name": "The Derby",
                "grade_text": "Group 1",
                "expectation_status": "held",
                "resolution_status": "pending",
                "source_refs": {"catalog_url": "https://official.test/1984"},
            },
            {
                "series_key": "uk-derby",
                "region": "united_kingdom",
                "year": 1985,
                "canonical_name_original": "The Derby",
                "original_name": "The Derby",
                "grade_text": "Group 1",
                "expectation_status": "not_held",
                "resolution_status": "pending",
                "source_refs": {"catalog_url": "https://official.test/1985"},
            },
        ]
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        return path

    def _artifact(self, root: Path) -> tuple[Path, Path]:
        source = self._write_input(root)
        artifact = root / "artifact"
        build_inventory_artifact(catalog_paths=[source], timeline_paths=[], output_dir=artifact)
        approval = artifact / "approval.json"
        payload = json.loads(approval.read_text(encoding="utf-8"))
        payload.update(
            {
                "status": "approved",
                "approved_by": "inventory-reviewer",
                "approved_at": "2026-07-12T00:00:00+08:00",
            }
        )
        approval.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return artifact, approval

    def test_build_generates_complete_manifest_and_review_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._write_input(root)
            artifact = root / "artifact"

            result = build_inventory_artifact(catalog_paths=[source], timeline_paths=[], output_dir=artifact)
            manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(result["target_count"], 2)
            self.assertEqual(result["series_count"], 1)
            self.assertEqual(
                set(manifest["artifacts"]),
                {
                    "series_candidates",
                    "series_conflicts",
                    "annual_targets",
                    "annual_targets_review",
                    "gap_ledger",
                    "summary",
                },
            )
            for identity in manifest["artifacts"].values():
                self.assertEqual(len(identity["sha256"]), 64)
                self.assertGreater(identity["size"], 0)

    def test_same_series_key_with_different_names_is_an_identity_conflict(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._write_input(root)
            second = root / "second.jsonl"
            second.write_text(
                json.dumps(
                    {
                        "series_key": "uk-derby",
                        "region": RacingRegion.UNITED_KINGDOM,
                        "year": 1986,
                        "canonical_name_original": "A Different Derby",
                        "original_name": "A Different Derby",
                        "grade_text": "Group 1",
                        "expectation_status": "held",
                        "resolution_status": "pending",
                        "source_refs": {"catalog_url": "https://official.test/1986"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = build_inventory_artifact(
                catalog_paths=[first, second],
                timeline_paths=[],
                output_dir=root / "artifact",
            )

        self.assertGreaterEqual(result["conflict_count"], 1)

    def test_same_series_name_punctuation_and_diacritics_do_not_create_conflicts(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "catalog.jsonl"
            rows = [
                {
                    "series_key": "france-automne-hurdle-g-p-d",
                    "region": RacingRegion.FRANCE,
                    "year": year,
                    "canonical_name_original": name,
                    "original_name": name,
                    "grade_text": "G1",
                }
                for year, name in (
                    (2000, "Automne Hurdle (G.P. d’Essai)"),
                    (2001, "Automne Hurdle(G.P. d'Essai)"),
                    (2002, "Automne Hurdle (G P d Essai)"),
                    (2003, "AutomneHurdle (G P d Essai) (H)"),
                    (2004, "AutomneHurdle (G P d Essai) S"),
                )
            ]
            source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

            result = build_inventory_artifact(
                catalog_paths=[source],
                timeline_paths=[],
                output_dir=root / "artifact",
            )

        self.assertEqual(result["conflict_count"], 0)

    def test_artifact_byte_change_invalidates_approval(self):
        with TemporaryDirectory() as tmp:
            artifact, approval = self._artifact(Path(tmp))
            targets = artifact / "annual_targets.jsonl"
            targets.write_text(targets.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaisesMessage(InventoryValidationError, "changed after manifest"):
                validate_inventory_artifact(artifact, approval)

    def test_artifact_manifest_cannot_reference_files_outside_its_directory(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact, approval = self._artifact(root)
            outside = root / "outside.jsonl"
            outside.write_text("{}\n", encoding="utf-8")
            manifest_path = artifact / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"]["annual_targets"] = {
                **file_identity(outside).as_dict(),
                "path": "../outside.jsonl",
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            approval_payload = json.loads(approval.read_text(encoding="utf-8"))
            approval_payload["manifest_identity"] = file_identity(
                manifest_path,
                relative_to=artifact,
            ).as_dict()
            approval.write_text(json.dumps(approval_payload), encoding="utf-8")

            with self.assertRaisesMessage(InventoryValidationError, "outside artifact directory"):
                validate_inventory_artifact(artifact, approval)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=False)
    def test_commit_is_disabled_by_default(self):
        with TemporaryDirectory() as tmp:
            artifact, approval = self._artifact(Path(tmp))

            with self.assertRaisesMessage(InventoryValidationError, "disabled"):
                commit_inventory_artifact(artifact_dir=artifact, approval_path=approval)
            self.assertFalse(RaceSeries.objects.exists())

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_approved_commit_is_idempotent_and_logs_once(self):
        get_user_model().objects.create_user(username="inventory-reviewer")
        with TemporaryDirectory() as tmp:
            artifact, approval = self._artifact(Path(tmp))

            first = commit_inventory_artifact(artifact_dir=artifact, approval_path=approval)
            second = commit_inventory_artifact(artifact_dir=artifact, approval_path=approval)

        self.assertEqual(first["series_created"], 1)
        self.assertEqual(first["targets_created"], 2)
        self.assertEqual(second["series_created"], 0)
        self.assertEqual(second["series_updated"], 0)
        self.assertEqual(second["targets_updated"], 0)
        self.assertEqual(RaceSeries.objects.count(), 1)
        self.assertEqual(HistoricalRaceEventTarget.objects.count(), 2)
        self.assertEqual(
            OperationLog.objects.filter(action_type="historical_inventory_commit").count(),
            1,
        )

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_commit_requires_an_existing_approver_account(self):
        with TemporaryDirectory() as tmp:
            artifact, approval = self._artifact(Path(tmp))

            with self.assertRaisesMessage(InventoryValidationError, "approver account"):
                commit_inventory_artifact(artifact_dir=artifact, approval_path=approval)

        self.assertFalse(RaceSeries.objects.exists())

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_inventory_commit_preserves_manually_locked_series_fields(self):
        get_user_model().objects.create_user(username="inventory-reviewer")
        RaceSeries.objects.create(
            key="uk-derby",
            country_region=RacingRegion.UNITED_KINGDOM,
            canonical_name_original="The Derby",
            chinese_name="人工锁定译名",
            review_status=RaceSeriesReviewStatus.APPROVED,
            manual_lock_flags={"chinese_name": True},
        )
        with TemporaryDirectory() as tmp:
            artifact, approval = self._artifact(Path(tmp))

            commit_inventory_artifact(artifact_dir=artifact, approval_path=approval)

        series = RaceSeries.objects.get(key="uk-derby")
        self.assertEqual(series.chinese_name, "人工锁定译名")

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_inventory_recommit_blocks_material_drift_for_imported_target(self):
        get_user_model().objects.create_user(username="inventory-reviewer")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_artifact, first_approval = self._artifact(root)
            commit_inventory_artifact(
                artifact_dir=first_artifact,
                approval_path=first_approval,
            )
            target = HistoricalRaceEventTarget.objects.select_related("race_series").get(year=1984)
            event = RaceEvent.objects.create(
                year=target.year,
                slug="united-kingdom-uk-derby-1984",
                race_series=target.race_series,
                original_name=target.original_name,
                chinese_name=target.chinese_name,
                country_region=target.country_region,
                racecourse=target.racecourse,
                grade_text=target.grade_text,
                surface=RaceEventSurface.TURF,
                visibility_status=RaceEventVisibility.DRAFT,
            )
            target.event = event
            target.resolution_status = HistoricalRaceResolutionStatus.IMPORTED
            target.module_statuses = {"runners": "complete", "results": "complete"}
            target.save(update_fields={"event", "resolution_status", "module_statuses"})

            second_source = root / "second-catalog.jsonl"
            rows = [json.loads(line) for line in self._write_input(root).read_text(encoding="utf-8").splitlines()]
            rows[0]["racecourse"] = "Changed Course"
            second_source.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            second_artifact = root / "second-artifact"
            build_inventory_artifact(
                catalog_paths=[second_source],
                timeline_paths=[],
                output_dir=second_artifact,
            )
            second_approval = second_artifact / "approval.json"
            approval_payload = json.loads(second_approval.read_text(encoding="utf-8"))
            approval_payload.update(
                {
                    "status": "approved",
                    "approved_by": "inventory-reviewer",
                    "approved_at": "2026-07-12T01:00:00+08:00",
                }
            )
            second_approval.write_text(json.dumps(approval_payload), encoding="utf-8")

            with self.assertRaisesMessage(InventoryValidationError, "imported target facts changed"):
                commit_inventory_artifact(
                    artifact_dir=second_artifact,
                    approval_path=second_approval,
                )

        target.refresh_from_db()
        self.assertEqual(target.racecourse, "")
        self.assertEqual(target.module_statuses, {"runners": "complete", "results": "complete"})

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_inventory_recommit_does_not_reopen_approved_permanent_gap(self):
        reviewer = get_user_model().objects.create_user(username="inventory-reviewer")
        with TemporaryDirectory() as tmp:
            artifact, approval = self._artifact(Path(tmp))
            commit_inventory_artifact(artifact_dir=artifact, approval_path=approval)
            target = HistoricalRaceEventTarget.objects.get(year=1984)
            target.resolution_status = HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE
            target.permanent_unavailable_approved_by = reviewer
            target.permanent_unavailable_approved_at = timezone.now()
            target.permanent_unavailable_evidence = {
                "official_archive": {"snapshot_sha256": "a" * 64},
                "independent_source": {"snapshot_sha256": "b" * 64},
            }
            target.save(
                update_fields={
                    "resolution_status",
                    "permanent_unavailable_approved_by",
                    "permanent_unavailable_approved_at",
                    "permanent_unavailable_evidence",
                }
            )

            commit_inventory_artifact(artifact_dir=artifact, approval_path=approval)

        target.refresh_from_db()
        self.assertEqual(
            target.resolution_status,
            HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE,
        )

    def test_command_defaults_to_read_only_artifact_generation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._write_input(root)
            output = root / "command-artifact"

            call_command(
                "build_historical_race_inventory",
                "--catalog-jsonl",
                str(source),
                "--output-dir",
                str(output),
                verbosity=0,
            )

            self.assertTrue((output / "manifest.json").is_file())
            self.assertFalse(RaceSeries.objects.exists())

    def test_command_rejects_commit_that_also_regenerates_inputs(self):
        with self.assertRaisesMessage(CommandError, "不能同时重新生成"):
            call_command(
                "build_historical_race_inventory",
                "--commit",
                "--artifact-dir",
                "/tmp/artifact",
                "--approval",
                "/tmp/approval.json",
                "--output-dir",
                "/tmp/new",
                verbosity=0,
            )

    def test_inventory_and_mapping_generation_refuse_to_overwrite_review_artifacts(self):
        self._event(slug="stable-race", series_key="stable-race", name="Stable Race")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._write_input(root)
            inventory = root / "inventory"
            build_inventory_artifact(catalog_paths=[source], timeline_paths=[], output_dir=inventory)
            with self.assertRaisesMessage(InventoryValidationError, "not empty"):
                build_inventory_artifact(catalog_paths=[source], timeline_paths=[], output_dir=inventory)

            mapping = root / "mapping"
            build_existing_event_mapping_artifact(output_dir=mapping)
            with self.assertRaisesMessage(InventoryValidationError, "not empty"):
                build_existing_event_mapping_artifact(output_dir=mapping)

    def test_existing_event_mapping_blocks_unstable_and_duplicate_keys(self):
        self._event(slug="stable-race", series_key="stable-race", name="Stable Race")
        self._event(slug="dated-race", series_key="dated-race-2026-05-01", name="Dated Race")
        self._event(slug="duplicate-a", series_key="duplicate-key", name="Duplicate Alpha")
        self._event(slug="duplicate-b", series_key="duplicate-key", name="Duplicate Beta")
        with TemporaryDirectory() as tmp:
            result = build_existing_event_mapping_artifact(output_dir=Path(tmp) / "mapping")

            self.assertEqual(result["event_count"], 4)
            self.assertEqual(result["approved_count"], 1)
            self.assertEqual(result["review_required_count"], 3)
            self.assertGreaterEqual(result["conflict_count"], 3)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_mapping_commit_requires_existing_approver_and_rejects_rejected_series(self):
        event = self._event(slug="stable-race", series_key="stable-race", name="Stable Race")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "mapping"
            build_existing_event_mapping_artifact(output_dir=artifact)
            approval = artifact / "approval.json"
            payload = json.loads(approval.read_text(encoding="utf-8"))
            payload.update(
                {
                    "status": "approved",
                    "approved_by": "missing-reviewer",
                    "approved_at": "2026-07-12T00:00:00+08:00",
                }
            )
            approval.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesMessage(InventoryValidationError, "approver account"):
                commit_existing_event_mapping(artifact_dir=artifact, approval_path=approval)

            reviewer = get_user_model().objects.create_user(username="mapping-reviewer")
            payload["approved_by"] = reviewer.username
            approval.write_text(json.dumps(payload), encoding="utf-8")
            RaceSeries.objects.create(
                key="stable-race",
                country_region=event.country_region,
                canonical_name_original=event.original_name,
                review_status=RaceSeriesReviewStatus.REJECTED,
            )
            with self.assertRaisesMessage(InventoryValidationError, "rejected"):
                commit_existing_event_mapping(artifact_dir=artifact, approval_path=approval)

        event.refresh_from_db()
        self.assertIsNone(event.race_series_id)

    def test_mapping_manifest_cannot_reference_files_outside_its_directory(self):
        self._event(slug="stable-race", series_key="stable-race", name="Stable Race")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "mapping"
            build_existing_event_mapping_artifact(output_dir=artifact)
            outside = root / "outside.jsonl"
            outside.write_text("{}\n", encoding="utf-8")
            manifest_path = artifact / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"]["mapping_candidates"] = {
                **file_identity(outside).as_dict(),
                "path": "../outside.jsonl",
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            approval = artifact / "approval.json"
            payload = json.loads(approval.read_text(encoding="utf-8"))
            payload["manifest_identity"] = file_identity(
                manifest_path,
                relative_to=artifact,
            ).as_dict()
            payload.update(
                {
                    "status": "approved",
                    "approved_by": "mapping-reviewer",
                    "approved_at": "2026-07-12T00:00:00+08:00",
                }
            )
            approval.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesMessage(InventoryValidationError, "outside artifact directory"):
                validate_mapping_artifact(artifact, approval)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_reviewed_existing_mapping_commits_idempotently_without_changing_urls(self):
        stable = self._event(slug="stable-race", series_key="stable-race", name="Stable Race")
        dated = self._event(slug="dated-race", series_key="dated-race-2026-05-01", name="Dated Race")
        duplicate_a = self._event(slug="duplicate-a", series_key="duplicate-key", name="Duplicate Alpha")
        duplicate_b = self._event(slug="duplicate-b", series_key="duplicate-key", name="Duplicate Beta")
        get_user_model().objects.create_user(username="mapping-reviewer")
        original_paths = {event.pk: event.public_path for event in (stable, dated, duplicate_a, duplicate_b)}
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            overrides = root / "overrides.json"
            overrides.write_text(
                json.dumps(
                    {
                        str(dated.pk): {"status": "approved", "series_key": "dated-race"},
                        str(duplicate_a.pk): {"status": "approved", "series_key": "duplicate-alpha"},
                        str(duplicate_b.pk): {"status": "approved", "series_key": "duplicate-beta"},
                    }
                ),
                encoding="utf-8",
            )
            artifact = root / "mapping"
            result = build_existing_event_mapping_artifact(
                output_dir=artifact,
                overrides_path=overrides,
            )
            self.assertEqual(result["review_required_count"], 0)
            self.assertEqual(result["conflict_count"], 0)
            approval = artifact / "approval.json"
            payload = json.loads(approval.read_text(encoding="utf-8"))
            payload.update(
                {
                    "status": "approved",
                    "approved_by": "mapping-reviewer",
                    "approved_at": "2026-07-12T00:00:00+08:00",
                }
            )
            approval.write_text(json.dumps(payload), encoding="utf-8")

            first = commit_existing_event_mapping(artifact_dir=artifact, approval_path=approval)
            second = commit_existing_event_mapping(artifact_dir=artifact, approval_path=approval)

        self.assertEqual(first["events_bound"], 4)
        self.assertEqual(second["events_bound"], 0)
        for event in RaceEvent.objects.all():
            self.assertIsNotNone(event.race_series_id)
            self.assertEqual(event.public_path, original_paths[event.pk])
        self.assertEqual(OperationLog.objects.filter(action_type="historical_series_mapping_commit").count(), 1)


class HistoricalRaceInventoryAdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="inventory-admin",
            email="inventory@example.test",
            password="test-password",
        )
        self.series = RaceSeries.objects.create(
            key="admin-series",
            country_region=RacingRegion.FRANCE,
            canonical_name_original="Prix Admin",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )
        HistoricalRaceEventTarget.objects.bulk_create(
            [
                HistoricalRaceEventTarget(
                    race_series=self.series,
                    year=1984 + index,
                    country_region=RacingRegion.FRANCE,
                )
                for index in range(20)
            ]
        )
        self.url = reverse("admin:stable_historicalraceeventtarget_changelist")

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_staff_list_is_filtered_paginated_read_only_and_query_bounded(self):
        self.client.force_login(self.admin)
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(
                self.url,
                {
                    "country_region__exact": RacingRegion.FRANCE,
                    "year__exact": 1984,
                    "resolution_status__exact": HistoricalRaceResolutionStatus.PENDING,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(captured), 12)
        self.assertContains(response, "Prix Admin")
        self.assertNotContains(response, reverse("admin:stable_historicalraceeventtarget_add"))


class HistoricalRacePublicPageTests(TestCase):
    def setUp(self):
        self.series = RaceSeries.objects.create(
            key="france-prix-example",
            country_region=RacingRegion.FRANCE,
            canonical_name_original="Prix Example",
            chinese_name="示例大奖赛",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )
        RaceSeriesName.objects.create(
            series=self.series,
            text="Ancien Prix Sponsor",
            source_language="fr",
            valid_from_year=1984,
            valid_to_year=1990,
        )
        self.old_event = self._event(1984, "france-prix-example-1984", "Ancien Prix Sponsor")
        self.current_event = self._event(2026, "france-prix-example-2026", "Prix Example")

    def _event(self, year: int, slug: str, original_name: str) -> RaceEvent:
        return RaceEvent.objects.create(
            year=year,
            slug=slug,
            race_series=self.series,
            original_name=original_name,
            chinese_name="示例大奖赛",
            country_region=RacingRegion.FRANCE,
            racecourse="ParisLongchamp",
            grade_text="Groupe I",
            surface=RaceEventSurface.TURF,
            status=RaceEventStatus.FINISHED,
            priority=RaceEventPriority.P0,
            visibility_status=RaceEventVisibility.PUBLISHED,
            local_date=date(year, 10, 1),
        )

    def test_calendar_filters_by_year_and_valid_historical_series_name(self):
        response = self.client.get(
            reverse("public-race-calendar"),
            {"tab": "all", "year": "1984", "q": "Ancien Prix Sponsor", "region": RacingRegion.FRANCE},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.old_event.public_path)
        self.assertNotContains(response, self.current_event.public_path)
        self.assertContains(response, 'name="year"')
        self.assertContains(response, 'name="q"')

    def test_detail_aggregates_series_winners_and_prefers_official_results(self):
        RaceEventResult.objects.create(
            event=self.old_event,
            finish_position=1,
            official_finish_position=1,
            horse_name="Official Winner 1984",
            jockey_name="Official Jockey",
        )
        RaceEventHistoryWinner.objects.create(
            event=self.current_event,
            winner_year=1984,
            horse_name="Fallback Must Not Display",
        )
        RaceEventHistoryWinner.objects.create(
            event=self.current_event,
            winner_year=1985,
            horse_name="Fallback Winner 1985",
        )

        response = self.client.get(self.current_event.public_path)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Official Winner 1984")
        self.assertContains(response, "Fallback Winner 1985")
        self.assertNotContains(response, "Fallback Must Not Display")

    @override_settings(RACE_EVENT_SITEMAP_SHARD_SIZE=1, SITE_URL="https://example.test")
    def test_sitemap_is_sharded_and_excludes_unimported_or_incomplete_history(self):
        self.old_event.data_quality_status = RaceEventDataQuality.COMPLETE
        self.old_event.save(update_fields={"data_quality_status"})
        self.current_event.data_quality_status = RaceEventDataQuality.COMPLETE
        self.current_event.save(update_fields={"data_quality_status"})
        HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=self.old_event.year,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
            event=self.old_event,
        )
        blocked_event = self._event(1985, "france-prix-example-1985", "Prix Example")
        blocked_event.data_quality_status = RaceEventDataQuality.COMPLETE
        blocked_event.save(update_fields={"data_quality_status"})
        HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=blocked_event.year,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.READY,
            event=blocked_event,
        )

        index = self.client.get(reverse("public-sitemap-index"))
        first_shard = self.client.get(reverse("public-race-sitemap-shard", args=[1]))
        second_shard = self.client.get(reverse("public-race-sitemap-shard", args=[2]))

        self.assertEqual(index.status_code, 200)
        self.assertContains(index, "races-1.xml")
        self.assertContains(index, "races-2.xml")
        combined = first_shard.content.decode() + second_shard.content.decode()
        self.assertIn(self.old_event.public_path, combined)
        self.assertIn(self.current_event.public_path, combined)
        self.assertNotIn(blocked_event.public_path, combined)
        self.assertEqual(self.client.get(reverse("public-race-sitemap-shard", args=[3])).status_code, 404)

    @override_settings(
        RACE_EVENT_SITEMAP_SHARD_SIZE=1,
        RACE_EVENT_PUBLIC_CACHE_SECONDS=600,
        SITE_URL="https://example.test",
    )
    def test_sitemap_count_cache_is_reused_and_invalidated_by_event_changes(self):
        cache.clear()
        for event in (self.old_event, self.current_event):
            event.data_quality_status = RaceEventDataQuality.COMPLETE
            event.save(update_fields={"data_quality_status"})

        with CaptureQueriesContext(connection) as first_queries:
            first = self.client.get(reverse("public-sitemap-index"))
        with CaptureQueriesContext(connection) as cached_queries:
            cached = self.client.get(reverse("public-sitemap-index"))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(cached.status_code, 200)
        self.assertGreaterEqual(len(first_queries), 1)
        self.assertEqual(len(cached_queries), 0)

        added = self._event(1985, "france-prix-example-cache-1985", "Prix Example Cache")
        added.data_quality_status = RaceEventDataQuality.COMPLETE
        added.save(update_fields={"data_quality_status"})
        with CaptureQueriesContext(connection) as invalidated_queries:
            refreshed = self.client.get(reverse("public-sitemap-index"))

        self.assertGreaterEqual(len(invalidated_queries), 1)
        self.assertContains(refreshed, "races-3.xml")

    def test_public_race_cache_falls_back_to_database_when_cache_is_unavailable(self):
        queryset = RaceEvent.objects.filter(visibility_status=RaceEventVisibility.PUBLISHED)
        with patch(
            "stable.services.race_event_public_cache.cache.get",
            side_effect=ConnectionError("redis unavailable"),
        ), patch(
            "stable.services.race_event_public_cache.cache.set",
            side_effect=ConnectionError("redis unavailable"),
        ):
            self.assertEqual(public_race_sitemap_count(queryset), 2)
            self.assertEqual(public_race_calendar_years(), [2026, 1984])

        with patch(
            "stable.services.race_event_public_cache.cache.delete_many",
            side_effect=ConnectionError("redis unavailable"),
        ):
            invalidate_public_race_cache()

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_publication_requires_explicit_scope_complete_results_and_runner_provenance(self):
        actor = get_user_model().objects.create_user(username="publisher")
        self.current_event.visibility_status = RaceEventVisibility.DRAFT
        self.current_event.source_refs = {"official_result": "https://official.test/result"}
        self.current_event.save(update_fields={"visibility_status", "source_refs"})
        target = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=self.current_event.year,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
            event=self.current_event,
            artifact_sha256="d" * 64,
        )
        scope = {"artifact_sha256": "d" * 64, "target_ids": [target.pk]}

        with self.assertRaisesMessage(InventoryValidationError, "confirmed_results_missing"):
            publish_historical_target(target, actor=actor, publication_scope=scope)

        RaceEventResult.objects.create(
            event=self.current_event,
            finish_position=1,
            official_finish_position=1,
            horse_name="Winner",
        )
        RaceEventRunner.objects.create(
            event=self.current_event,
            horse_number="1",
            horse_name="Winner",
            source_refs={"derived_from_results": True},
        )
        published = publish_historical_target(target, actor=actor, publication_scope=scope)

        self.assertEqual(published.visibility_status, RaceEventVisibility.PUBLISHED)
        self.assertEqual(published.data_quality_status, RaceEventDataQuality.COMPLETE)
        self.assertTrue(OperationLog.objects.filter(action_type="historical_race_publication").exists())

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_cancelled_publication_uses_evidence_instead_of_fake_results(self):
        actor = get_user_model().objects.create_user(username="cancel-publisher")
        cancelled = self._event(1985, "france-prix-example-1985", "Prix Example")
        cancelled.status = RaceEventStatus.CANCELLED
        cancelled.visibility_status = RaceEventVisibility.DRAFT
        cancelled.source_refs = {"official_schedule": "https://official.test/schedule"}
        cancelled.save(update_fields={"status", "visibility_status", "source_refs"})
        target = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=cancelled.year,
            expectation_status=HistoricalRaceExpectationStatus.CANCELLED,
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
            event=cancelled,
            artifact_sha256="e" * 64,
            source_refs={
                "scheduled_evidence": {"url": "https://official.test/schedule"},
                "cancellation_evidence": {"url": "https://official.test/cancelled"},
            },
        )

        published = publish_historical_target(
            target,
            actor=actor,
            publication_scope={"artifact_sha256": "e" * 64, "target_ids": [target.pk]},
        )

        self.assertEqual(published.visibility_status, RaceEventVisibility.PUBLISHED)

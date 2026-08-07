from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, models, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from stable.models import (
    HistoricalRaceEventTarget,
    RaceEvent,
    RaceEventAlias,
    RaceEventPublicPath,
    RaceEventProductCanonicalLink,
    RaceSeries,
)
from stable.services.historical_race_calendar_admission import (
    enter_historical_calendar_maintenance,
)


def _event_payload(*, year: int, slug: str, series: RaceSeries) -> dict:
    return {
        "year": year,
        "edition_year": year,
        "slug": slug,
        "series_key": series.key,
        "original_name": slug,
        "chinese_name": slug,
        "country_region": series.country_region,
        "racecourse": "Sha Tin",
        "grade_text": "G1",
        "surface": "turf",
        "local_date": date(year, 1, 1),
        "race_series": series,
    }


class ReleaseBSchemaStateTests(SimpleTestCase):
    def test_event_identity_uses_non_null_series_and_edition(self):
        constraints = {constraint.name: constraint for constraint in RaceEvent._meta.constraints}
        self.assertNotIn("uq_race_event_series_year", constraints)
        constraint = constraints["uq_race_event_series_edition"]
        self.assertEqual(constraint.fields, ("race_series", "edition_year"))
        self.assertEqual(
            constraint.condition,
            models.Q(race_series__isnull=False, edition_year__isnull=False),
        )

    def test_target_identity_only_constrains_non_superseded_rows(self):
        constraints = {
            constraint.name: constraint
            for constraint in HistoricalRaceEventTarget._meta.constraints
        }
        self.assertNotIn("uq_historical_target_series_year", constraints)
        constraint = constraints["uq_hist_target_active_series_year"]
        self.assertEqual(constraint.fields, ("race_series", "year"))
        self.assertEqual(
            constraint.condition,
            ~models.Q(resolution_status="superseded"),
        )


class ReleaseBSchemaPreflightTests(TestCase):
    def setUp(self):
        self.series = RaceSeries.objects.create(
            key="release-b-preflight",
            country_region="hong_kong",
            canonical_name_original="Release B Preflight",
            chinese_name="Release B 预检",
        )

    def test_forward_reports_duplicate_series_edition_without_writing(self):
        from stable.services.historical_calendar_release_b_schema import (
            check_release_b_schema_compatibility,
        )

        before = RaceEvent._base_manager.count()
        with patch(
            "stable.services.historical_calendar_release_b_schema._event_conflicts",
            return_value=[
                {
                    "race_series_id": self.series.pk,
                    "edition_year": 2025,
                    "event_ids": [101, 102],
                }
            ],
        ):
            result = check_release_b_schema_compatibility(direction="forward")
        after = RaceEvent._base_manager.count()

        self.assertFalse(result["ok"])
        self.assertEqual(result["event_conflict_count"], 1)
        self.assertEqual(result["target_conflict_count"], 0)
        self.assertRegex(result["rows_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(after, before)

    def test_management_command_emits_machine_readable_identity(self):
        from io import StringIO
        import json

        output = StringIO()
        call_command(
            "check_historical_calendar_release_b_schema",
            direction="forward",
            json_output=True,
            stdout=output,
        )
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["schema_version"], "historical-calendar-release-b-preflight/v1")
        self.assertEqual(payload["direction"], "forward")
        self.assertIn("migration_leaf", payload)
        self.assertIn("database_identity_sha256", payload)
        self.assertRegex(payload["rows_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            payload["migration_leaf"],
            "stable.0071_historical_calendar_release_b",
        )

    def test_unknown_applied_stable_migration_fails_closed(self):
        from stable.services.historical_calendar_release_b_schema import (
            check_release_b_schema_compatibility,
        )

        with patch(
            "stable.services.historical_calendar_release_b_schema."
            "MigrationRecorder.applied_migrations",
            return_value={
                ("stable", "0071_historical_calendar_release_b"),
                ("stable", "9999_unknown_production_migration"),
            },
        ):
            result = check_release_b_schema_compatibility(direction="forward")

        self.assertFalse(result["ok"])
        self.assertFalse(result["migration_graph_known"])
        self.assertEqual(
            result["unknown_applied_migrations"],
            ["stable.9999_unknown_production_migration"],
        )

    def test_preflight_command_rejects_unknown_applied_stable_migration(self):
        import json
        from io import StringIO

        from django.core.management.base import CommandError

        output = StringIO()
        with patch(
            "stable.services.historical_calendar_release_b_schema."
            "MigrationRecorder.applied_migrations",
            return_value={
                ("stable", "0071_historical_calendar_release_b"),
                ("stable", "9999_unknown_production_migration"),
            },
        ), self.assertRaisesMessage(CommandError, "schema preflight failed"):
            call_command(
                "check_historical_calendar_release_b_schema",
                direction="forward",
                json_output=True,
                expected_migration_leaf=(
                    "stable.0071_historical_calendar_release_b"
                ),
                stdout=output,
            )

        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(
            payload["unknown_applied_migrations"],
            ["stable.9999_unknown_production_migration"],
        )

    def test_superseded_target_requires_same_series_year_active_survivor(self):
        survivor = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2024,
            country_region="hong_kong",
        )
        duplicate = HistoricalRaceEventTarget(
            race_series=self.series,
            year=2025,
            country_region="hong_kong",
            resolution_status="superseded",
            superseded_by=survivor,
            superseded_at=timezone.now(),
            supersession_manifest_sha256="a" * 64,
        )
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_target_with_existing_dependents_cannot_be_superseded_again(self):
        from django.core.exceptions import ValidationError

        middle = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2024,
            country_region="hong_kong",
        )
        HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2024,
            country_region="hong_kong",
            resolution_status="superseded",
            superseded_by=middle,
            superseded_at=timezone.now(),
            supersession_manifest_sha256="a" * 64,
        )
        final = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2025,
            country_region="hong_kong",
        )
        middle.year = 2025
        middle.resolution_status = "superseded"
        middle.superseded_by = final
        middle.superseded_at = timezone.now()
        middle.supersession_manifest_sha256 = "b" * 64

        with self.assertRaisesMessage(ValidationError, "禁止形成多层替代链"):
            middle.full_clean()

    def test_b_only_event_shape_passes_forward_and_blocks_reverse_preflight(self):
        RaceEvent._base_manager.bulk_create(
            [
                RaceEvent(
                    **{
                        **_event_payload(
                            year=2024,
                            slug="release-b-public-year-a",
                            series=self.series,
                        ),
                        "edition_year": 2024,
                    }
                ),
                RaceEvent(
                    **{
                        **_event_payload(
                            year=2024,
                            slug="release-b-public-year-b",
                            series=self.series,
                        ),
                        "edition_year": 2025,
                    }
                ),
            ]
        )
        from stable.services.historical_calendar_release_b_schema import (
            check_release_b_schema_compatibility,
        )

        self.assertTrue(check_release_b_schema_compatibility(direction="forward")["ok"])
        self.assertFalse(check_release_b_schema_compatibility(direction="reverse")["ok"])

    def test_active_target_unique_allows_superseded_audit_row(self):
        HistoricalRaceEventTarget._base_manager.bulk_create(
            [
                HistoricalRaceEventTarget(
                    race_series=self.series,
                    year=2024,
                    country_region="hong_kong",
                ),
                HistoricalRaceEventTarget(
                    race_series=self.series,
                    year=2024,
                    country_region="hong_kong",
                    resolution_status="superseded",
                ),
            ]
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            HistoricalRaceEventTarget._base_manager.bulk_create(
                [
                    HistoricalRaceEventTarget(
                        race_series=self.series,
                        year=2024,
                        country_region="hong_kong",
                    )
                ]
            )


class ReleaseBDeployContractTests(SimpleTestCase):
    def test_deploy_runs_candidate_preflight_before_release_orchestration(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        for relative in ("deploy/deploy.sh", "deploy/deploy_lowcost.sh"):
            script = (root / relative).read_text(encoding="utf-8")
            build = script.index('build web')
            preflight = script.index('run_historical_calendar_release_b_preflight.sh')
            release = script.index('run_application_release.sh')
            self.assertLess(build, preflight, relative)
            self.assertLess(preflight, release, relative)
        wrapper = (root / "deploy/run_historical_calendar_release_b_preflight.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("run --rm --no-deps", wrapper)
        self.assertIn("check_historical_calendar_release_b_schema", wrapper)
        self.assertIn("EXPECTED_CANDIDATE_COMMIT", wrapper)
        self.assertIn("EXPECTED_CANDIDATE_IMAGE_ID", wrapper)
        self.assertIn("EXPECTED_PRODUCTION_DB_IDENTITY_SHA256", wrapper)
        self.assertIn("stable.0070_horse_identity_evidence_commit_receipt", wrapper)
        self.assertIn("stable.0071_historical_calendar_release_b", wrapper)


class ReleaseBSeriesPlannerTests(TransactionTestCase):
    def setUp(self):
        self.series = RaceSeries.objects.create(
            key="release-b-series-planner",
            country_region="hong_kong",
            canonical_name_original="Release B Series Planner",
            chinese_name="Release B 系列计划",
        )

    def _event(self, *, year: int, slug: str, day: int) -> RaceEvent:
        return RaceEvent.objects.create(
            **{
                **_event_payload(year=year, slug=slug, series=self.series),
                "local_date": date(year, 1, day),
            }
        )

    def test_planner_groups_full_series_and_detects_duplicate_boundary(self):
        shifted = self._event(year=2023, slug="shifted", day=5)
        canonical = self._event(year=2024, slug="canonical", day=5)
        tail = self._event(year=2025, slug="tail", day=6)
        RaceEvent._base_manager.filter(pk=shifted.pk).update(
            local_date=date(2024, 1, 5)
        )

        from stable.services.historical_race_calendar_integrity_v2 import (
            build_release_b_series_actions,
        )

        actions = build_release_b_series_actions()
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["series_id"], self.series.pk)
        self.assertEqual(
            {row["id"] for row in action["events"]},
            {shifted.pk, canonical.pk, tail.pk},
        )
        self.assertEqual(action["mismatch_event_ids"], [shifted.pk])
        self.assertEqual(len(action["duplicate_groups"]), 1)
        duplicate_group = action["duplicate_groups"][0]
        self.assertEqual(duplicate_group["local_date"], "2024-01-05")
        self.assertEqual(duplicate_group["event_ids"], [shifted.pk, canonical.pk])
        self.assertEqual(
            set(duplicate_group["identity_sha256_by_event"]),
            {str(shifted.pk), str(canonical.pk)},
        )
        self.assertEqual(action["disposition"], "block")
        self.assertIn("reviewed_overlay_required", action["block_reasons"])

    def test_canonical_links_are_managed_not_immutable_dependencies(self):
        duplicate = self._event(year=2023, slug="duplicate", day=3)
        canonical = self._event(year=2024, slug="winner", day=4)
        actor = get_user_model().objects.create_user(username="release-b-link-reviewer")
        link = RaceEventProductCanonicalLink.objects.create(
            duplicate_event=duplicate,
            canonical_event=canonical,
            identity_sha256="a" * 64,
            manifest_sha256="b" * 64,
            approved_by=actor,
            approved_at=timezone.now(),
        )

        from stable.services.historical_race_calendar_integrity_v2 import (
            enumerate_series_ledgers,
        )

        ledgers = enumerate_series_ledgers(self.series.pk)
        self.assertEqual(
            [row["payload"]["id"] for row in ledgers["managed_canonical_links"]],
            [link.pk],
        )
        immutable_keys = set(ledgers["immutable_reverse_dependencies"])
        self.assertFalse(any("raceeventproductcanonicallink" in key for key in immutable_keys))
        self.assertEqual(
            set(ledgers),
            {
                "managed_targets_and_paths",
                "managed_canonical_links",
                "immutable_reverse_dependencies",
            },
        )

    def test_target_supersession_rejects_cross_edition_and_chains(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            validate_target_supersession_overlay,
        )

        rows = [
            {
                "id": 1,
                "race_series_id": 10,
                "year": 2024,
                "resolution_status": "superseded",
                "superseded_by_id": 2,
            },
            {
                "id": 2,
                "race_series_id": 10,
                "year": 2025,
                "resolution_status": "pending",
                "superseded_by_id": None,
            },
        ]
        with self.assertRaisesMessage(ValueError, "target_supersession_edition_mismatch"):
            validate_target_supersession_overlay(rows)

        rows[0]["year"] = 2025
        rows[1]["resolution_status"] = "superseded"
        rows[1]["superseded_by_id"] = 3
        rows.append(
            {
                "id": 3,
                "race_series_id": 10,
                "year": 2025,
                "resolution_status": "pending",
                "superseded_by_id": None,
            }
        )
        with self.assertRaisesMessage(ValueError, "target_supersession_chain_forbidden"):
            validate_target_supersession_overlay(rows)

    def test_prepare_v2_writes_blocked_series_manifest_and_review_template(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        shifted = self._event(year=2023, slug="prepare-shifted", day=5)
        self._event(year=2024, slug="prepare-canonical", day=5)
        RaceEvent._base_manager.filter(pk=shifted.pk).update(
            local_date=date(2024, 1, 5)
        )
        from stable.services.historical_race_calendar_integrity_v2 import (
            prepare_release_b_series_census,
        )

        before = RaceEvent._base_manager.count()
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "census-v2"
            result = prepare_release_b_series_census(
                output_dir=output,
                artifact_root=root,
                all_regions=True,
            )
            manifest = json.loads((output / "manifest.json").read_text())
            review = json.loads((output / "review.template.json").read_text())
        self.assertEqual(result["series_action_count"], 1)
        self.assertEqual(manifest["schema_version"], "historical-race-calendar-integrity-manifest.v2")
        self.assertEqual(manifest["actions"][0]["disposition"], "block")
        self.assertEqual(review["schema_version"], "historical-race-calendar-integrity-review.v2")
        self.assertEqual(review["census_manifest_sha256"], "")
        self.assertEqual(
            set(review["actions"][0]),
            {"action_id", "operations", "reviewed"},
        )
        self.assertEqual(review["actions"][0]["action_id"], f"series-{self.series.pk}")
        self.assertEqual(RaceEvent._base_manager.count(), before)

    def test_management_command_exposes_prepare_v2_without_upgrading_v1(self):
        import json
        from io import StringIO
        from pathlib import Path
        from tempfile import TemporaryDirectory

        shifted = self._event(year=2023, slug="command-shifted", day=7)
        RaceEvent._base_manager.filter(pk=shifted.pk).update(
            local_date=date(2024, 1, 7)
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = StringIO()
            call_command(
                "repair_historical_race_calendar_integrity",
                prepare_v2=True,
                all_regions=True,
                output=str(root / "command-v2"),
                artifact_root=str(root),
                stdout=output,
            )
            result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "prepared_v2")


class ReleaseBProductionShapeFixtureTests(SimpleTestCase):
    def test_sanitized_fixture_preserves_81_to_14_conservation(self):
        import hashlib
        import json
        from pathlib import Path

        path = Path(__file__).with_name("fixtures") / "historical_calendar_release_b_census_shape.json"
        raw = path.read_bytes()
        payload = json.loads(raw)
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            "59b48579c6100da2176b6dc14449fbccab55dbb220c7ca9d1522d0765503ac5e",
        )
        self.assertEqual(len(payload["series"]), 14)
        self.assertEqual(sum(row["mismatch_count"] for row in payload["series"]), 81)
        self.assertEqual(
            sum(row["duplicate_boundary_count"] for row in payload["series"]), 12
        )
        self.assertEqual(
            {row["region"] for row in payload["series"]},
            {"hong_kong", "united_kingdom"},
        )


@override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
class ReleaseBReviewedApplyTests(TransactionTestCase):
    def setUp(self):
        self.series = RaceSeries.objects.create(
            key="release-b-reviewed-apply",
            country_region="hong_kong",
            canonical_name_original="Release B Reviewed Apply",
            chinese_name="Release B 审核应用",
        )
        self.duplicate = RaceEvent.objects.create(
            **_event_payload(year=2023, slug="reviewed-duplicate", series=self.series)
        )
        self.canonical = RaceEvent.objects.create(
            **_event_payload(year=2024, slug="reviewed-canonical", series=self.series)
        )
        RaceEvent._base_manager.filter(pk=self.duplicate.pk).update(
            local_date=date(2024, 1, 1),
            original_name=self.canonical.original_name,
        )
        self.alias = RaceEventAlias.objects.create(
            event=self.duplicate,
            text="Release B immutable alias",
        )
        self.actor = get_user_model().objects.create_user(username="release-b-apply-actor")

    def _reviewed_action(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            build_release_b_series_actions,
        )

        action = build_release_b_series_actions()[0]
        duplicate_path = self.duplicate.public_paths.get(path_kind="canonical")
        canonical_path = self.canonical.public_paths.get(path_kind="canonical")
        duplicate_group = action["duplicate_groups"][0]
        action["disposition"] = "action"
        action["operations"] = [
            "collapse_exact_duplicate_boundary",
            "rotate_ordinary_season_chain",
        ]
        action["reviewed"] = {
            "events": [
                {
                    "id": self.duplicate.pk,
                    "year": 2024,
                    "edition_year": 2023,
                    "slug": f"release-b-tombstone-{self.duplicate.pk}",
                    "race_series_id": None,
                    "visibility_status": "draft",
                },
                {
                    "id": self.canonical.pk,
                    "year": 2024,
                    "edition_year": 2024,
                    "slug": "reviewed-canonical",
                    "race_series_id": self.series.pk,
                    "visibility_status": "draft",
                },
            ],
            "targets": [],
            "paths": [
                {
                    "id": duplicate_path.pk,
                    "event_id": self.canonical.pk,
                    "year": 2023,
                    "slug": "reviewed-duplicate",
                    "path_kind": "legacy",
                },
                {
                    "id": canonical_path.pk,
                    "event_id": self.canonical.pk,
                    "year": 2024,
                    "slug": "reviewed-canonical",
                    "path_kind": "canonical",
                },
            ],
            "canonical_links": [
                {
                    "duplicate_event_id": self.duplicate.pk,
                    "canonical_event_id": self.canonical.pk,
                    "identity_sha256": duplicate_group[
                        "identity_sha256_by_event"
                    ][str(self.duplicate.pk)],
                    "is_active": True,
                }
            ],
            "duplicate_boundaries": [
                {
                    "local_date": group["local_date"],
                    "event_ids": group["event_ids"],
                    "identity_sha256_by_event": group[
                        "identity_sha256_by_event"
                    ],
                    "survivor_event_id": self.canonical.pk,
                    "duplicate_event_ids": [self.duplicate.pk],
                    "decision": "equivalent",
                    "rationale": "人工核对同日边界并选择保留记录。",
                }
                for group in action["duplicate_groups"]
            ],
            "dependency_policies": {
                key: "retain_on_tombstone"
                for key in action["ledgers"]["immutable_reverse_dependencies"]
            },
        }
        action["block_reasons"] = []
        return action

    def test_review_rejects_non_equivalent_duplicate_boundary(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            _validate_reviewed_action,
        )

        RaceEvent._base_manager.filter(pk=self.duplicate.pk).update(
            original_name="Different actual race"
        )
        action = self._reviewed_action()
        with self.assertRaisesRegex(ValueError, "not_equivalent"):
            _validate_reviewed_action(action)

    def test_review_rejects_different_source_identity_as_equivalent(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            _validate_reviewed_action,
        )

        RaceEvent._base_manager.filter(pk=self.duplicate.pk).update(
            source_refs={"provider": "different-upstream", "race_id": "other"}
        )
        action = self._reviewed_action()
        with self.assertRaisesRegex(ValueError, "not_equivalent"):
            _validate_reviewed_action(action)

    def test_review_rejects_equivalent_duplicate_without_exact_tombstone_state(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            _validate_reviewed_action,
        )

        action = self._reviewed_action()
        duplicate = action["reviewed"]["events"][0]
        duplicate["race_series_id"] = self.series.pk
        duplicate["visibility_status"] = "published"
        duplicate["slug"] = "still-public"
        with self.assertRaisesRegex(ValueError, "tombstone_invalid"):
            _validate_reviewed_action(action)

    def test_review_rejects_surplus_canonical_link(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            _validate_reviewed_action,
        )

        action = self._reviewed_action()
        action["reviewed"]["canonical_links"].append(
            {
                "duplicate_event_id": self.canonical.pk,
                "canonical_event_id": self.duplicate.pk,
                "identity_sha256": "e" * 64,
                "is_active": True,
            }
        )
        with self.assertRaisesRegex(ValueError, "boundary_mismatch"):
            _validate_reviewed_action(action)

    def test_review_allows_multiple_duplicates_for_one_survivor(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            _validate_reviewed_action,
        )

        third = RaceEvent.objects.create(
            **_event_payload(year=2022, slug="reviewed-third", series=self.series)
        )
        RaceEvent._base_manager.filter(pk=third.pk).update(
            local_date=date(2024, 1, 1),
            original_name=self.canonical.original_name,
        )
        action = self._reviewed_action()
        group = action["duplicate_groups"][0]
        third_path = third.public_paths.get(path_kind="canonical")
        action["reviewed"]["events"].append(
            {
                "id": third.pk,
                "year": 2024,
                "edition_year": 2022,
                "slug": f"release-b-tombstone-{third.pk}",
                "race_series_id": None,
                "visibility_status": "draft",
            }
        )
        action["reviewed"]["paths"].append(
            {
                "id": third_path.pk,
                "event_id": self.canonical.pk,
                "year": 2022,
                "slug": "reviewed-third",
                "path_kind": "legacy",
            }
        )
        action["reviewed"]["canonical_links"].append(
            {
                "duplicate_event_id": third.pk,
                "canonical_event_id": self.canonical.pk,
                "identity_sha256": group["identity_sha256_by_event"][str(third.pk)],
                "is_active": True,
            }
        )
        boundary = action["reviewed"]["duplicate_boundaries"][0]
        boundary["duplicate_event_ids"] = [self.duplicate.pk, third.pk]
        _validate_reviewed_action(action)

    def test_review_rejects_superseded_target_without_audit_fields(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            _validate_reviewed_action,
        )

        survivor = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2023,
            country_region="hong_kong",
        )
        duplicate = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2023,
            country_region="hong_kong",
            resolution_status="superseded",
            superseded_by=survivor,
            superseded_at=timezone.now(),
            supersession_manifest_sha256="d" * 64,
        )
        action = self._reviewed_action()
        action["reviewed"]["targets"] = [
            {
                "id": survivor.pk,
                "race_series_id": self.series.pk,
                "year": 2023,
                "event_id": None,
                "resolution_status": "pending",
                "superseded_by_id": None,
                "superseded_at": None,
                "supersession_manifest_sha256": "",
            },
            {
                "id": duplicate.pk,
                "race_series_id": self.series.pk,
                "year": 2023,
                "event_id": None,
                "resolution_status": "superseded",
                "superseded_by_id": survivor.pk,
                "superseded_at": None,
                "supersession_manifest_sha256": "",
            },
        ]
        with self.assertRaisesRegex(ValueError, "audit_invalid"):
            _validate_reviewed_action(action)

    def test_review_rejects_unrelated_target_field(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            _validate_reviewed_action,
        )

        target = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2023,
            country_region="hong_kong",
        )
        action = self._reviewed_action()
        action["reviewed"]["targets"] = [
            {
                "id": target.pk,
                "race_series_id": self.series.pk,
                "year": 2023,
                "event_id": None,
                "resolution_status": "pending",
                "superseded_by_id": None,
                "superseded_at": None,
                "supersession_manifest_sha256": "",
                "notes": "out of scope",
            }
        ]
        with self.assertRaisesRegex(ValueError, "target_fields_invalid"):
            _validate_reviewed_action(action)

    def test_review_rejects_imported_target_without_event(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            _validate_reviewed_action,
        )

        target = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2023,
            country_region="hong_kong",
        )
        action = self._reviewed_action()
        action["reviewed"]["targets"] = [
            {
                "id": target.pk,
                "race_series_id": self.series.pk,
                "year": 2023,
                "event_id": None,
                "resolution_status": "imported",
                "superseded_by_id": None,
                "superseded_at": None,
                "supersession_manifest_sha256": "",
            }
        ]
        with self.assertRaisesRegex(ValueError, "imported_target_event_required"):
            _validate_reviewed_action(action)

    def test_verifier_rejects_published_event_without_canonical_path(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            verify_release_b_series_actions,
        )

        RaceEvent._base_manager.filter(pk=self.canonical.pk).update(
            visibility_status="published"
        )
        RaceEventPublicPath._base_manager.filter(
            event_id=self.canonical.pk, path_kind="canonical"
        ).delete()
        result = verify_release_b_series_actions(actions=[])
        self.assertFalse(result["ok"])
        self.assertIn(
            f"global_published_canonical_path_count:{self.canonical.pk}",
            result["errors"],
        )

    def test_reviewed_series_apply_tombstones_duplicate_and_preserves_legacy_path(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            apply_release_b_series_actions,
            release_b_action_scope_sha256,
            rollback_release_b_series_actions,
            verify_release_b_series_actions,
        )

        inactive_audit = RaceEventProductCanonicalLink.objects.create(
            duplicate_event=self.duplicate,
            canonical_event=self.canonical,
            identity_sha256="b" * 64,
            manifest_sha256="a" * 64,
            approved_by=self.actor,
            approved_at=timezone.now(),
            is_active=False,
        )
        action = self._reviewed_action()
        action_scope = release_b_action_scope_sha256([action])
        enter_historical_calendar_maintenance(
            manifest_sha256="d" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
        )
        result = apply_release_b_series_actions(
            actions=[action],
            manifest_sha256="d" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
            confirm_reviewed_artifact=True,
        )
        self.duplicate.refresh_from_db()
        self.assertIsNone(self.duplicate.race_series_id)
        self.assertEqual(self.duplicate.year, 2024)
        self.assertEqual(self.duplicate.slug, f"release-b-tombstone-{self.duplicate.pk}")
        self.assertTrue(
            RaceEventProductCanonicalLink.objects.filter(
                duplicate_event=self.duplicate,
                canonical_event=self.canonical,
                is_active=True,
            ).exists()
        )
        self.assertTrue(
            RaceEventProductCanonicalLink.objects.filter(
                pk=inactive_audit.pk,
                is_active=False,
            ).exists()
        )
        self.assertTrue(
            self.canonical.public_paths.filter(
                year=2023,
                slug="reviewed-duplicate",
                path_kind="legacy",
            ).exists()
        )
        self.assertEqual(result["applied_series_ids"], [self.series.pk])
        self.alias.refresh_from_db()
        self.assertEqual(self.alias.event_id, self.duplicate.pk)
        verification = verify_release_b_series_actions(actions=[action])
        self.assertTrue(verification["ok"])
        rolled_back = rollback_release_b_series_actions(
            rollback_payload=result["rollback_payload"],
            manifest_sha256="d" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
            confirm_reviewed_artifact=True,
        )
        self.duplicate.refresh_from_db()
        self.assertEqual(self.duplicate.year, 2023)
        self.assertEqual(self.duplicate.slug, "reviewed-duplicate")
        self.assertEqual(self.duplicate.race_series_id, self.series.pk)
        self.assertEqual(rolled_back["status"], "rolled_back")

    def test_target_reassignment_is_verified_and_rolled_back_exactly(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            apply_release_b_series_actions,
            release_b_action_scope_sha256,
            rollback_release_b_series_actions,
        )

        target = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2023,
            country_region="hong_kong",
            event=self.duplicate,
            resolution_status="imported",
        )
        action = self._reviewed_action()
        action["reviewed"]["targets"] = [
            {
                "id": target.pk,
                "race_series_id": self.series.pk,
                "year": 2023,
                "event_id": None,
                "resolution_status": "pending",
                "superseded_by_id": None,
                "superseded_at": None,
                "supersession_manifest_sha256": "",
            }
        ]
        action_scope = release_b_action_scope_sha256([action])
        enter_historical_calendar_maintenance(
            manifest_sha256="f" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
        )
        applied = apply_release_b_series_actions(
            actions=[action],
            manifest_sha256="f" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
            confirm_reviewed_artifact=True,
        )
        target.refresh_from_db()
        self.assertIsNone(target.event_id)
        self.assertEqual(target.resolution_status, "pending")
        rollback_release_b_series_actions(
            rollback_payload=applied["rollback_payload"],
            manifest_sha256="f" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
            confirm_reviewed_artifact=True,
        )
        target.refresh_from_db()
        self.assertEqual(target.event_id, self.duplicate.pk)
        self.assertEqual(target.resolution_status, "imported")

    def test_valid_supersession_timestamp_is_normalized_for_post_state_verification(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            apply_release_b_series_actions,
            release_b_action_scope_sha256,
            rollback_release_b_series_actions,
        )

        superseded_at = timezone.now()
        survivor = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2023,
            country_region="hong_kong",
        )
        duplicate = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2023,
            country_region="hong_kong",
            resolution_status="superseded",
            superseded_by=survivor,
            superseded_at=superseded_at,
            supersession_manifest_sha256="a" * 64,
        )
        action = self._reviewed_action()
        action["reviewed"]["targets"] = [
            {
                "id": survivor.pk,
                "race_series_id": self.series.pk,
                "year": 2023,
                "event_id": None,
                "resolution_status": "pending",
                "superseded_by_id": None,
                "superseded_at": None,
                "supersession_manifest_sha256": "",
            },
            {
                "id": duplicate.pk,
                "race_series_id": self.series.pk,
                "year": 2023,
                "event_id": None,
                "resolution_status": "superseded",
                "superseded_by_id": survivor.pk,
                "superseded_at": superseded_at.isoformat().replace("+00:00", "Z"),
                "supersession_manifest_sha256": "__RELEASE_B_MANIFEST_SHA256__",
            },
        ]
        action_scope = release_b_action_scope_sha256([action])
        enter_historical_calendar_maintenance(
            manifest_sha256="7" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
        )

        applied = apply_release_b_series_actions(
            actions=[action],
            manifest_sha256="7" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
            confirm_reviewed_artifact=True,
        )

        self.assertTrue(applied["rollback_payload"]["after"]["sha256"])
        rolled_back = rollback_release_b_series_actions(
            rollback_payload=applied["rollback_payload"],
            manifest_sha256="7" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
            confirm_reviewed_artifact=True,
        )
        self.assertEqual(rolled_back["status"], "rolled_back")

    def test_invalid_reviewed_action_rolls_back_whole_batch(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            apply_release_b_series_actions,
            release_b_action_scope_sha256,
        )

        action = self._reviewed_action()
        action["reviewed"]["events"][0]["slug"] = "reviewed-canonical"
        action_scope = release_b_action_scope_sha256([action])
        enter_historical_calendar_maintenance(
            manifest_sha256="d" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
        )
        before = list(
            RaceEvent._base_manager.filter(pk__in=(self.duplicate.pk, self.canonical.pk))
            .order_by("pk")
            .values_list("pk", "year", "slug", "race_series_id")
        )
        with self.assertRaises(ValueError):
            apply_release_b_series_actions(
                actions=[action],
                manifest_sha256="d" * 64,
                action_scope_sha256=action_scope,
                actor=self.actor,
                confirm_reviewed_artifact=True,
            )
        after = list(
            RaceEvent._base_manager.filter(pk__in=(self.duplicate.pk, self.canonical.pk))
            .order_by("pk")
            .values_list("pk", "year", "slug", "race_series_id")
        )
        self.assertEqual(after, before)

    def test_rollback_rejects_exact_post_state_drift_without_partial_restore(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            apply_release_b_series_actions,
            release_b_action_scope_sha256,
            rollback_release_b_series_actions,
        )

        action = self._reviewed_action()
        action_scope = release_b_action_scope_sha256([action])
        enter_historical_calendar_maintenance(
            manifest_sha256="e" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
        )
        applied = apply_release_b_series_actions(
            actions=[action],
            manifest_sha256="e" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
            confirm_reviewed_artifact=True,
        )
        RaceEvent._base_manager.filter(pk=self.canonical.pk).update(notes="post-apply drift")
        with self.assertRaisesMessage(ValueError, "release_b_rollback_post_state_drift"):
            rollback_release_b_series_actions(
                rollback_payload=applied["rollback_payload"],
                manifest_sha256="e" * 64,
                action_scope_sha256=action_scope,
                actor=self.actor,
                confirm_reviewed_artifact=True,
            )
        self.duplicate.refresh_from_db()
        self.canonical.refresh_from_db()
        self.assertIsNone(self.duplicate.race_series_id)
        self.assertEqual(self.canonical.notes, "post-apply drift")

    def test_review_overlay_binds_census_and_emits_executable_v2_manifest(self):
        import hashlib
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from stable.services.historical_race_calendar_integrity_v2 import (
            apply_release_b_reviewed_manifest,
            prepare_release_b_series_census,
            prepare_reviewed_release_b_manifest,
            rollback_release_b_reviewed_manifest,
        )

        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            census_result = prepare_release_b_series_census(
                output_dir=root / "census",
                artifact_root=root,
                all_regions=True,
            )
            action = self._reviewed_action()
            overlay = {
                "schema_version": "historical-race-calendar-integrity-review.v2",
                "status": "reviewed",
                "census_manifest_sha256": census_result["manifest_sha256"],
                "actions": [
                    {
                        "action_id": action["action_id"],
                        "operations": action["operations"],
                        "reviewed": action["reviewed"],
                    }
                ],
            }
            overlay_path = root / "review.json"
            overlay_bytes = (
                json.dumps(overlay, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode()
            overlay_path.write_bytes(overlay_bytes)
            result = prepare_reviewed_release_b_manifest(
                census_manifest_path=Path(census_result["manifest_path"]),
                expected_census_manifest_sha256=census_result["manifest_sha256"],
                review_overlay_path=overlay_path,
                expected_review_overlay_sha256=hashlib.sha256(overlay_bytes).hexdigest(),
                output_dir=root / "reviewed",
                artifact_root=root,
            )
            manifest = json.loads(Path(result["manifest_path"]).read_text())
            reviewer = get_user_model().objects.create_user(username="release-b-reviewer")
            approval = {
                "schema_version": "historical-race-calendar-integrity-approval.v2",
                "status": "approved",
                "manifest_sha256": result["manifest_sha256"],
                "action_scope_sha256": result["action_scope_sha256"],
                "approved_action_ids": [action["action_id"]],
                "approved_by": reviewer.get_username(),
                "approved_at": timezone.now().isoformat(),
                "actor": self.actor.get_username(),
            }
            approval_path = root / "approval.json"
            approval_bytes = (
                json.dumps(approval, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode()
            approval_path.write_bytes(approval_bytes)
            maintenance = {
                "schema_version": "historical-race-calendar-maintenance-evidence.v1",
                "status": "frozen",
                "manifest_sha256": result["manifest_sha256"],
                "action_scope_sha256": result["action_scope_sha256"],
                "observed_at": timezone.now().isoformat(),
                "checks": {
                    "historical_import": "stopped",
                    "reconciliation": "stopped",
                    "race_live_projection": "stopped",
                    "p0_participant": "stopped",
                },
            }
            maintenance_path = root / "maintenance.json"
            maintenance_bytes = (
                json.dumps(maintenance, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode()
            maintenance_path.write_bytes(maintenance_bytes)
            enter_historical_calendar_maintenance(
                manifest_sha256=result["manifest_sha256"],
                action_scope_sha256=result["action_scope_sha256"],
                actor=self.actor,
            )
            applied = apply_release_b_reviewed_manifest(
                manifest_path=result["manifest_path"],
                expected_manifest_sha256=result["manifest_sha256"],
                approval_path=approval_path,
                expected_approval_sha256=hashlib.sha256(approval_bytes).hexdigest(),
                maintenance_evidence_path=maintenance_path,
                expected_maintenance_evidence_sha256=hashlib.sha256(
                    maintenance_bytes
                ).hexdigest(),
                actor=self.actor,
                artifact_root=root,
                confirm_reviewed_artifact=True,
            )
            self.assertEqual(applied["status"], "verified")
            rolled_back = rollback_release_b_reviewed_manifest(
                manifest_path=result["manifest_path"],
                expected_manifest_sha256=result["manifest_sha256"],
                approval_path=approval_path,
                expected_approval_sha256=hashlib.sha256(approval_bytes).hexdigest(),
                maintenance_evidence_path=maintenance_path,
                expected_maintenance_evidence_sha256=hashlib.sha256(
                    maintenance_bytes
                ).hexdigest(),
                rollback_path=applied["rollback_path"],
                expected_rollback_sha256=applied["rollback_sha256"],
                actor=self.actor,
                artifact_root=root,
                confirm_reviewed_artifact=True,
            )
            self.assertEqual(rolled_back["status"], "rolled_back")
        self.assertEqual(manifest["schema_version"], "historical-race-calendar-integrity-manifest.v2")
        self.assertEqual(manifest["actions"][0]["disposition"], "action")
        self.assertEqual(manifest["actions"][0]["block_reasons"], [])
        self.assertEqual(result["executable_action_count"], 1)


@override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
class ReleaseBEditionRotationTests(TransactionTestCase):
    def setUp(self):
        self.series = RaceSeries.objects.create(
            key="release-b-edition-rotation",
            country_region="hong_kong",
            canonical_name_original="Release B Edition Rotation",
            chinese_name="Release B 届次轮转",
        )
        self.first = RaceEvent.objects.create(
            **_event_payload(year=2023, slug="rotation-first", series=self.series)
        )
        self.second = RaceEvent.objects.create(
            **_event_payload(year=2024, slug="rotation-second", series=self.series)
        )
        self.actor = get_user_model().objects.create_user(
            username="release-b-rotation-actor"
        )

    def _rotation_action(self):
        from stable.services.historical_race_calendar_integrity_v2 import _series_action

        current = _series_action(self.series.pk)
        paths = [
            {
                key: row["payload"][key]
                for key in ("id", "event_id", "year", "slug", "path_kind")
            }
            for row in current["ledgers"]["managed_targets_and_paths"]["paths"]
        ]
        return {
            **current,
            "disposition": "action",
            "block_reasons": [],
            "operations": ["rotate_ordinary_season_chain"],
            "reviewed": {
                "events": [
                    {
                        "id": self.first.pk,
                        "year": 2023,
                        "edition_year": 2024,
                        "slug": "rotation-first",
                        "race_series_id": self.series.pk,
                        "visibility_status": "draft",
                    },
                    {
                        "id": self.second.pk,
                        "year": 2024,
                        "edition_year": 2023,
                        "slug": "rotation-second",
                        "race_series_id": self.series.pk,
                        "visibility_status": "draft",
                    },
                ],
                "targets": [],
                "paths": paths,
                "canonical_links": [],
                "duplicate_boundaries": [],
                "dependency_policies": {
                    key: "retain_on_tombstone"
                    for key in current["ledgers"]["immutable_reverse_dependencies"]
                },
            },
        }

    def test_manifest_bound_rotation_avoids_intermediate_series_edition_conflict(self):
        from stable.services.historical_race_calendar_integrity_v2 import (
            apply_release_b_series_actions,
            release_b_action_scope_sha256,
            rollback_release_b_series_actions,
        )

        action = self._rotation_action()
        action_scope = release_b_action_scope_sha256([action])
        enter_historical_calendar_maintenance(
            manifest_sha256="8" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
        )

        applied = apply_release_b_series_actions(
            actions=[action],
            manifest_sha256="8" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
            confirm_reviewed_artifact=True,
        )
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.edition_year, 2024)
        self.assertEqual(self.second.edition_year, 2023)

        rolled_back = rollback_release_b_series_actions(
            rollback_payload=applied["rollback_payload"],
            manifest_sha256="8" * 64,
            action_scope_sha256=action_scope,
            actor=self.actor,
            confirm_reviewed_artifact=True,
        )
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(self.first.edition_year, 2023)
        self.assertEqual(self.second.edition_year, 2024)
        self.assertEqual(rolled_back["status"], "rolled_back")

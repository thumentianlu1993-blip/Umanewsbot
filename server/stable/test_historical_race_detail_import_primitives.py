from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    RaceEvent,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.historical_race_batches import target_identity
from stable.services.historical_race_detail_sources import apply_approved_detail_source
from stable.services.historical_race_importer import (
    apply_historical_target_candidate,
    historical_basic_fields_complete,
)
from stable.services.historical_race_inventory import InventoryValidationError


class HistoricalRaceDetailImportPrimitiveTests(TestCase):
    def setUp(self):
        self.series = RaceSeries.objects.create(
            key="france-import-primitive",
            country_region=RacingRegion.FRANCE,
            canonical_name_original="Prix Primitive",
            chinese_name="测试锦标",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )
        self.event = RaceEvent.objects.create(
            year=2012,
            slug="france-import-primitive-2012",
            race_series=self.series,
            original_name="Prix Primitive",
            chinese_name="测试锦标",
            country_region=RacingRegion.FRANCE,
            racecourse="Longchamp",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            distance_text="2400m",
            local_date=date(2012, 10, 7),
            status=RaceEventStatus.FINISHED,
            visibility_status=RaceEventVisibility.DRAFT,
            source_refs={"existing_event_ref": True},
        )
        self.target = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2012,
            country_region=RacingRegion.FRANCE,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.READY,
            original_name="Prix Primitive",
            chinese_name="测试锦标",
            racecourse="Longchamp",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            distance_text="2400m",
            local_date=date(2012, 10, 7),
            source_refs={"catalog": "official"},
            event=self.event,
            artifact_sha256="a" * 64,
        )

    def _source_row(self, root: Path) -> dict:
        source = root / "source.html"
        source.write_bytes(b"<html>verified source</html>")
        source_url = "https://www.zeturf.fr/fr/course-du-jour/2012-10-07/R1C6-prix-primitive"
        return {
            "target_id": self.target.pk,
            "expected_target_sha256": target_identity(self.target)["target_sha256"],
            "inventory_artifact_sha256": self.target.artifact_sha256,
            "year": self.target.year,
            "slug": self.event.slug,
            "source_name": "zeturf",
            "source_url": source_url,
            "source_provider": "zeturf",
            "source_authority": "third_party_high_access",
            "redirect_chain": [],
            "source_cache_identity": {
                "path": source.name,
                "size": source.stat().st_size,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "source_url": source_url,
                "cached_at": "2026-07-13T00:00:00Z",
                "protected_by": [],
            },
        }

    def _results(self) -> dict:
        return {
            "is_complete": True,
            "source_cache_identity": {"sha256": "f" * 64},
            "items": [
                {
                    "finish_position": 1,
                    "official_finish_position": 1,
                    "horse_number": "1",
                    "horse_name": "Winner",
                    "jockey_name": "Jockey",
                    "trainer_name": "Trainer",
                    "source_refs": {"official_result": True},
                }
            ],
        }

    def test_approved_detail_source_primitive_preserves_other_sources_and_replaces_same_url(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = self._source_row(root)
            old_same_url = {"url": row["source_url"], "source_provider": "old"}
            other = {"url": "https://www.france-galop.com/fixture", "source_provider": "france_galop"}
            self.target.source_refs = {
                "catalog": "official",
                "detail_discovery": {"approved_detail_sources": [old_same_url, other]},
            }
            self.target.save(update_fields={"source_refs"})
            self.event.source_refs = {
                "existing_event_ref": True,
                "detail_discovery": {"approved_detail_sources": [old_same_url, other]},
            }
            self.event.save(update_fields={"source_refs"})
            row["expected_target_sha256"] = target_identity(self.target)["target_sha256"]

            result = apply_approved_detail_source(
                target=self.target,
                event=self.event,
                row=row,
                artifact_root=root,
                artifact_manifest_sha256="b" * 64,
                approved_by="admin",
                approved_at="2026-07-13T00:00:00Z",
            )

        self.target.refresh_from_db()
        self.event.refresh_from_db()
        target_sources = self.target.source_refs["detail_discovery"]["approved_detail_sources"]
        event_sources = self.event.source_refs["detail_discovery"]["approved_detail_sources"]
        self.assertEqual(target_sources, event_sources)
        self.assertEqual([item["url"] for item in target_sources], [other["url"], row["source_url"]])
        self.assertEqual(target_sources[-1]["artifact_manifest_sha256"], "b" * 64)
        self.assertNotEqual(result["before"], result["after"])

    def test_approved_detail_source_primitive_rejects_cache_identity_provider_and_target_event_errors(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = self._source_row(root)
            cases = (
                ("cache", {"source_cache_identity": {**row["source_cache_identity"], "sha256": "0" * 64}}),
                ("cache_size", {"source_cache_identity": {**row["source_cache_identity"], "size": "invalid"}}),
                ("provider", {"source_provider": "uk_sportinglife"}),
                ("identity", {"expected_target_sha256": "0" * 64}),
            )
            for label, changes in cases:
                with self.subTest(label=label), self.assertRaises(InventoryValidationError):
                    apply_approved_detail_source(
                        target=self.target,
                        event=self.event,
                        row={**row, **changes},
                        artifact_root=root,
                        artifact_manifest_sha256="b" * 64,
                        approved_by="admin",
                        approved_at="2026-07-13T00:00:00Z",
                    )

            bad_url = "https://example.com/untrusted-result"
            with self.assertRaises(InventoryValidationError):
                apply_approved_detail_source(
                    target=self.target,
                    event=self.event,
                    row={
                        **row,
                        "source_url": bad_url,
                        "source_cache_identity": {**row["source_cache_identity"], "source_url": bad_url},
                    },
                    artifact_root=root,
                    artifact_manifest_sha256="b" * 64,
                    approved_by="admin",
                    approved_at="2026-07-13T00:00:00Z",
                )

            other_event = RaceEvent.objects.create(
                year=2013,
                slug="france-import-primitive-2013",
                original_name="Other",
                chinese_name="其他",
                country_region=RacingRegion.FRANCE,
                racecourse="Longchamp",
                grade_text="G1",
                surface=RaceEventSurface.TURF,
            )
            with self.assertRaisesMessage(InventoryValidationError, "target/event mismatch"):
                apply_approved_detail_source(
                    target=self.target,
                    event=other_event,
                    row=row,
                    artifact_root=root,
                    artifact_manifest_sha256="b" * 64,
                    approved_by="admin",
                    approved_at="2026-07-13T00:00:00Z",
                )

    def test_basic_complete_report_distinguishes_required_and_policy_optional_fields(self):
        report = historical_basic_fields_complete(self.target, self.event)
        self.assertTrue(report["complete"])
        self.assertEqual(report["missing_fields"], [])
        self.assertEqual(report["policy_optional"], [])

        self.target.grade_text = ""
        self.target.surface = ""
        self.event.grade_text = ""
        self.event.surface = ""
        report = historical_basic_fields_complete(self.target, self.event)
        self.assertTrue(report["complete"])
        self.assertEqual(report["missing_fields"], [])
        self.assertEqual(report["policy_optional"], ["grade_text", "surface"])

    def test_basic_complete_report_rejects_missing_sources_and_target_event_mismatch(self):
        self.event.distance_text = ""
        self.event.source_refs = {}
        self.target.racecourse = "Chantilly"

        report = historical_basic_fields_complete(self.target, self.event)

        self.assertFalse(report["complete"])
        self.assertIn("event.distance_text", report["missing_fields"])
        self.assertIn("event.source_refs", report["missing_fields"])
        self.assertIn("mismatch.racecourse", report["missing_fields"])

    def test_detail_import_marks_basic_incomplete_without_blocking_imported_detail(self):
        self.target.distance_text = ""
        self.target.local_date = None
        self.event.distance_text = ""
        self.event.local_date = None
        self.target.save(update_fields={"distance_text", "local_date"})
        self.event.save(update_fields={"distance_text", "local_date"})

        apply_historical_target_candidate(
            target_id=self.target.pk,
            expected_target_sha256=target_identity(self.target)["target_sha256"],
            inventory_artifact_sha256=self.target.artifact_sha256,
            source_name="official_fixture",
            source_url="https://official.test/result",
            modules={"results": self._results()},
        )

        self.target.refresh_from_db()
        self.assertEqual(self.target.resolution_status, HistoricalRaceResolutionStatus.IMPORTED)
        self.assertEqual(self.target.module_statuses["basic"], "incomplete")
        self.assertEqual(
            self.target.module_statuses["basic_missing_fields"],
            ["target.local_date", "target.distance_text", "event.local_date", "event.distance_text"],
        )

    def test_detail_import_uses_shared_basic_predicate_for_complete_target(self):
        with patch(
            "stable.services.historical_race_importer.historical_basic_fields_complete",
            wraps=historical_basic_fields_complete,
        ) as predicate:
            apply_historical_target_candidate(
                target_id=self.target.pk,
                expected_target_sha256=target_identity(self.target)["target_sha256"],
                inventory_artifact_sha256=self.target.artifact_sha256,
                source_name="official_fixture",
                source_url="https://official.test/result",
                modules={"results": self._results()},
            )

        self.target.refresh_from_db()
        predicate.assert_called_once()
        self.assertEqual(self.target.module_statuses["basic"], "complete")
        self.assertNotIn("basic_missing_fields", self.target.module_statuses)

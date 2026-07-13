from __future__ import annotations

import hashlib
import json
from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.historical_race_batches import target_identity
from stable.services.historical_race_detail_sources import (
    apply_detail_source_artifact,
    build_detail_source_artifact,
    check_detail_source_artifact,
    validate_detail_source_artifact,
)
from stable.services.historical_race_inventory import InventoryValidationError, file_identity


@override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
class HistoricalRaceDetailSourceArtifactTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="admin")
        self.series = RaceSeries.objects.create(
            key="france-detail-source-fixture",
            country_region=RacingRegion.FRANCE,
            canonical_name_original="Prix Fixture",
            chinese_name="法国测试赛",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )
        self.event = RaceEvent.objects.create(
            year=2012,
            slug="france-fixture-2012",
            original_name="Prix Fixture",
            chinese_name="法国测试赛",
            country_region=RacingRegion.FRANCE,
            racecourse="Longchamp",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            distance_text="2400m",
            status=RaceEventStatus.FINISHED,
            visibility_status=RaceEventVisibility.DRAFT,
            local_date=date(2012, 10, 7),
            race_series=self.series,
            source_refs={"existing_event_ref": True},
        )
        self.primary_url = "https://www.france-galop.com/fr/content/fixture"
        self.source_url = "https://www.zeturf.fr/fr/course-du-jour/2012-10-07/R1C6-longchamp-fixture"
        self.target = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=2012,
            country_region=RacingRegion.FRANCE,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.READY,
            original_name="Prix Fixture",
            chinese_name="法国测试赛",
            racecourse="Longchamp",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            distance_text="2400m",
            local_date=date(2012, 10, 7),
            source_refs={
                "catalog": "official",
                "detail_discovery": {
                    "urls": {
                        "result_url": {
                            "url": self.primary_url,
                            "source_provider": "france_galop",
                            "source_authority": "official",
                        }
                    }
                },
            },
            event=self.event,
            artifact_sha256="a" * 64,
        )

    def _inputs(self, root: Path) -> tuple[Path, Path]:
        source = root / "source.html"
        source.write_bytes(b"<html>verified source</html>")
        identity = {
            "path": source.name,
            "size": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_url": self.source_url,
            "cached_at": "2026-07-13T00:00:00Z",
            "protected_by": [],
        }
        cache_manifest = root / "source_cache_manifest.json"
        cache_manifest.write_text(
            json.dumps({"schema_version": "1.0", "files": {source.name: identity}}) + "\n",
            encoding="utf-8",
        )
        candidate = root / "candidate.jsonl"
        candidate.write_text(
            json.dumps(
                {
                    "year": 2012,
                    "slug": self.event.slug,
                    "source_name": "zeturf",
                    "source_url": self.source_url,
                    "modules": {
                        "runners": {"items": [{"horse_name": "Runner"}]},
                        "results": {"items": [{"horse_name": "Winner", "finish_position": 1}]},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return candidate, cache_manifest

    def _build(self, root: Path) -> Path:
        candidate, cache_manifest = self._inputs(root)
        artifact = root / "artifact"
        result = build_detail_source_artifact(
            candidate_jsonl_paths=[candidate],
            source_cache_manifest_paths=[cache_manifest],
            output_dir=artifact,
        )
        self.assertEqual(result["candidate_count"], 1)
        return artifact

    def _approve(self, artifact: Path) -> Path:
        approval = artifact / "approval.json"
        approval.write_text(
            json.dumps(
                {
                    "status": "approved",
                    "manifest_identity": file_identity(
                        artifact / "manifest.json", relative_to=artifact
                    ).as_dict(),
                    "approved_by": self.actor.username,
                    "approved_at": "2026-07-13T00:00:00Z",
                    "approved_target_ids": [self.target.pk],
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return approval

    def test_build_copies_verified_source_and_creates_pending_approval(self):
        with TemporaryDirectory() as tmp:
            artifact = self._build(Path(tmp))
            manifest, approval, rows = validate_detail_source_artifact(
                artifact, artifact / "approval.json", require_approved=False
            )

            copied = artifact / rows[0]["source_cache_identity"]["path"]
            self.assertTrue(copied.is_file())
            self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), rows[0]["source_cache_identity"]["sha256"])
            self.assertEqual(manifest["candidate_count"], 1)
            self.assertEqual(approval["status"], "pending")
            self.assertEqual(rows[0]["expected_target_sha256"], target_identity(self.target)["target_sha256"])

    def test_build_rejects_non_object_source_cache_manifest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, cache_manifest = self._inputs(root)
            cache_manifest.write_text("[]\n", encoding="utf-8")

            with self.assertRaisesMessage(InventoryValidationError, "manifest is invalid"):
                build_detail_source_artifact(
                    candidate_jsonl_paths=[candidate],
                    source_cache_manifest_paths=[cache_manifest],
                    output_dir=root / "artifact",
                )

    def test_build_accepts_region_specific_irishracing_fallback(self):
        self.source_url = "https://www.irishracing.com/raceresults/Sun-1st-Oct-2000/Longchamp/1520"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, cache_manifest = self._inputs(root)
            row = json.loads(candidate.read_text(encoding="utf-8"))
            row["source_name"] = "irishracing_france"
            candidate.write_text(json.dumps(row) + "\n", encoding="utf-8")

            artifact = root / "artifact"
            build_detail_source_artifact(
                candidate_jsonl_paths=[candidate],
                source_cache_manifest_paths=[cache_manifest],
                output_dir=artifact,
            )
            detail_row = json.loads((artifact / "detail_source_candidates.jsonl").read_text(encoding="utf-8"))

        self.assertEqual(detail_row["source_provider"], "france_irishracing")
        self.assertEqual(detail_row["source_authority"], "third_party_high_access")

    def test_build_rejects_irishracing_provider_from_another_region(self):
        self.source_url = "https://www.irishracing.com/raceresults/Sun-1st-Oct-2000/Longchamp/1520"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, cache_manifest = self._inputs(root)
            row = json.loads(candidate.read_text(encoding="utf-8"))
            row["source_name"] = "irishracing_uk"
            candidate.write_text(json.dumps(row) + "\n", encoding="utf-8")

            with self.assertRaisesMessage(InventoryValidationError, "region mismatch"):
                build_detail_source_artifact(
                    candidate_jsonl_paths=[candidate],
                    source_cache_manifest_paths=[cache_manifest],
                    output_dir=root / "artifact",
                )

    def test_build_accepts_archived_equibase_pdf_for_united_states(self):
        self.series.country_region = RacingRegion.UNITED_STATES
        self.series.save(update_fields={"country_region"})
        self.event.country_region = RacingRegion.UNITED_STATES
        self.event.save(update_fields={"country_region"})
        self.target.country_region = RacingRegion.UNITED_STATES
        self.target.save(update_fields={"country_region"})
        self.source_url = (
            "https://www.equibase.com/premium/eqbPDFChartPlus.cfm?"
            "RACE=9&BorP=P&TID=CD&CTRY=USA&DT=10/29/2000&DAY=D&STYLE=EQB"
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, cache_manifest = self._inputs(root)
            row = json.loads(candidate.read_text(encoding="utf-8"))
            row["source_name"] = "equibase_pdf_chart"
            candidate.write_text(json.dumps(row) + "\n", encoding="utf-8")

            artifact = root / "artifact"
            build_detail_source_artifact(
                candidate_jsonl_paths=[candidate],
                source_cache_manifest_paths=[cache_manifest],
                output_dir=artifact,
            )
            detail_row = json.loads((artifact / "detail_source_candidates.jsonl").read_text(encoding="utf-8"))

        self.assertEqual(detail_row["source_provider"], "equibase")
        self.assertEqual(detail_row["source_authority"], "third_party")

    def test_build_accepts_equibase_yearbook_for_united_states(self):
        self.series.country_region = RacingRegion.UNITED_STATES
        self.series.save(update_fields={"country_region"})
        self.event.country_region = RacingRegion.UNITED_STATES
        self.event.save(update_fields={"country_region"})
        self.target.country_region = RacingRegion.UNITED_STATES
        self.target.save(update_fields={"country_region"})
        self.source_url = (
            "https://www.equibase.com/yearbook/Result.cfm?"
            "cy=USA&de=D&rd=2025-04-19&rn=10&tk=KEE"
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, cache_manifest = self._inputs(root)
            row = json.loads(candidate.read_text(encoding="utf-8"))
            row["source_name"] = "equibase_yearbook"
            candidate.write_text(json.dumps(row) + "\n", encoding="utf-8")
            artifact = root / "artifact"
            build_detail_source_artifact(
                candidate_jsonl_paths=[candidate],
                source_cache_manifest_paths=[cache_manifest],
                output_dir=artifact,
            )
            detail_row = json.loads((artifact / "detail_source_candidates.jsonl").read_text(encoding="utf-8"))

        self.assertEqual(detail_row["source_provider"], "equibase")

    def test_build_accepts_jra_official_result_page_for_japan(self):
        self.series.country_region = RacingRegion.JAPAN
        self.series.save(update_fields={"country_region"})
        self.event.country_region = RacingRegion.JAPAN
        self.event.save(update_fields={"country_region"})
        self.target.country_region = RacingRegion.JAPAN
        self.target.save(update_fields={"country_region"})
        self.source_url = "https://www.jra.go.jp/datafile/seiseki/replay/2025/033.html"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, cache_manifest = self._inputs(root)
            row = json.loads(candidate.read_text(encoding="utf-8"))
            row["source_name"] = "jra_official_result_page"
            candidate.write_text(json.dumps(row) + "\n", encoding="utf-8")
            artifact = root / "artifact"
            build_detail_source_artifact(
                candidate_jsonl_paths=[candidate],
                source_cache_manifest_paths=[cache_manifest],
                output_dir=artifact,
            )
            detail_row = json.loads((artifact / "detail_source_candidates.jsonl").read_text(encoding="utf-8"))

        self.assertEqual(detail_row["source_provider"], "jra")
        self.assertEqual(detail_row["source_authority"], "official")

    def test_apply_preserves_primary_evidence_and_records_approved_detail_source(self):
        with TemporaryDirectory() as tmp:
            artifact = self._build(Path(tmp))
            approval = self._approve(artifact)
            before = target_identity(self.target)["target_sha256"]

            result = apply_detail_source_artifact(artifact_dir=artifact, approval_path=approval)

        self.target.refresh_from_db()
        discovery = self.target.source_refs["detail_discovery"]
        self.assertEqual(discovery["urls"]["result_url"]["url"], self.primary_url)
        self.assertEqual(discovery["approved_detail_sources"][0]["url"], self.source_url)
        self.event.refresh_from_db()
        self.assertTrue(self.event.source_refs["existing_event_ref"])
        self.assertEqual(
            self.event.source_refs["detail_discovery"]["approved_detail_sources"][0]["url"],
            self.source_url,
        )
        self.assertEqual(self.target.resolution_status, HistoricalRaceResolutionStatus.READY)
        self.assertEqual(self.target.event_id, self.event.pk)
        self.assertNotEqual(result["target_sha256_changes"][0]["after"], before)
        self.assertTrue(OperationLog.objects.filter(action_type="historical_detail_sources_applied").exists())

    def test_apply_locks_events_before_merging_source_refs(self):
        with TemporaryDirectory() as tmp:
            artifact = self._build(Path(tmp))
            approval = self._approve(artifact)

            with patch.object(RaceEvent.objects, "select_for_update", wraps=RaceEvent.objects.select_for_update) as lock:
                apply_detail_source_artifact(artifact_dir=artifact, approval_path=approval)

        lock.assert_called_once_with()

    def test_check_validates_current_targets_without_writing(self):
        with TemporaryDirectory() as tmp:
            artifact = self._build(Path(tmp))
            approval = self._approve(artifact)

            result = check_detail_source_artifact(artifact_dir=artifact, approval_path=approval)

        self.target.refresh_from_db()
        self.assertEqual(result["checked_count"], 1)
        self.assertNotIn("approved_detail_sources", self.target.source_refs["detail_discovery"])
        self.assertFalse(OperationLog.objects.filter(action_type="historical_detail_sources_applied").exists())

    def test_apply_rejects_target_drift_without_partial_write(self):
        with TemporaryDirectory() as tmp:
            artifact = self._build(Path(tmp))
            approval = self._approve(artifact)
            refs = dict(self.target.source_refs)
            refs["changed_after_approval"] = True
            self.target.source_refs = refs
            self.target.save(update_fields={"source_refs"})

            with self.assertRaisesMessage(InventoryValidationError, "changed after approval"):
                apply_detail_source_artifact(artifact_dir=artifact, approval_path=approval)

        self.target.refresh_from_db()
        self.event.refresh_from_db()
        self.assertNotIn("approved_detail_sources", self.target.source_refs["detail_discovery"])
        self.assertNotIn("detail_discovery", self.event.source_refs)
        self.assertFalse(OperationLog.objects.filter(action_type="historical_detail_sources_applied").exists())

    def test_approved_artifact_hash_drift_is_rejected(self):
        with TemporaryDirectory() as tmp:
            artifact = self._build(Path(tmp))
            approval = self._approve(artifact)
            (artifact / "detail_source_candidates.jsonl").write_text("{}\n", encoding="utf-8")

            with self.assertRaisesMessage(InventoryValidationError, "changed after manifest"):
                validate_detail_source_artifact(artifact, approval)

    def test_management_command_checks_without_writing_then_commits(self):
        with TemporaryDirectory() as tmp:
            artifact = self._build(Path(tmp))
            approval = self._approve(artifact)
            output = StringIO()

            call_command(
                "manage_historical_race_detail_sources",
                artifact_dir=str(artifact),
                approval=str(approval),
                check=True,
                stdout=output,
            )
            self.assertIn('"checked_count": 1', output.getvalue())
            self.target.refresh_from_db()
            self.assertNotIn("approved_detail_sources", self.target.source_refs["detail_discovery"])

            call_command(
                "manage_historical_race_detail_sources",
                artifact_dir=str(artifact),
                approval=str(approval),
                commit=True,
                stdout=StringIO(),
            )

        self.target.refresh_from_db()
        self.assertEqual(
            self.target.source_refs["detail_discovery"]["approved_detail_sources"][0]["url"],
            self.source_url,
        )

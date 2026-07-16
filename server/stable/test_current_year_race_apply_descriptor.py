from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    RaceEvent,
    RaceEventAlias,
    RaceEventDataQuality,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
    TaskExecutionLog,
)
from stable.services.historical_race_batches import historical_event_slug, target_identity


CUTOFF = date(2026, 7, 15)
CLASSIFIER_PATH = (
    Path(__file__).resolve().parents[2]
    / "runtime/tools/classify_current_year_race_due_checks.py"
)
CLASSIFIER_SPEC = importlib.util.spec_from_file_location(
    "current_year_descriptor_test_classifier", CLASSIFIER_PATH
)
CLASSIFIER = importlib.util.module_from_spec(CLASSIFIER_SPEC)
assert CLASSIFIER_SPEC.loader is not None
sys.path.insert(0, str(CLASSIFIER_PATH.parent))
try:
    CLASSIFIER_SPEC.loader.exec_module(CLASSIFIER)
finally:
    sys.path.pop(0)


def canonical(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


class CurrentYearRaceApplyDescriptorTests(TestCase):
    def _target(
        self,
        suffix: str = "january-cup",
        *,
        year: int = 2026,
        region: str = RacingRegion.HONG_KONG,
    ) -> HistoricalRaceEventTarget:
        series = RaceSeries.objects.create(
            key=f"{region}-{suffix}",
            country_region=region,
            canonical_name_original=suffix.replace("-", " ").title(),
            chinese_name=f"测试赛事 {suffix}",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )
        return HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=year,
            country_region=region,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.PENDING,
            artifact_sha256="a" * 64,
        )

    def _date_match(self, target: HistoricalRaceEventTarget) -> dict:
        return {
            "target_id": target.pk,
            "target_sha256": target_identity(target)["target_sha256"],
            "inventory_artifact_sha256": target.artifact_sha256,
            "year": target.year,
            "slug": historical_event_slug(target),
            "original_name": target.race_series.canonical_name_original,
            "chinese_name": target.race_series.chinese_name,
            "country_region": target.country_region,
            "racecourse": "Happy Valley",
            "grade_text": "G3",
            "normalized_grade": "G3",
            "surface": RaceEventSurface.TURF,
            "distance_text": "1650m",
            "status": RaceEventStatus.FINISHED,
            "local_date": f"{target.year}-01-07",
            "source_refs": {"official": {"url": "https://example.test/result"}},
            # The real classifier deliberately drops these untrusted fields.
            "visibility_status": RaceEventVisibility.PUBLISHED,
            "data_quality_status": RaceEventDataQuality.COMPLETE,
            "is_featured": True,
        }

    def _refresh_signed_chain(self, paths: dict[str, Path]) -> None:
        manifest = json.loads(paths["manifest"].read_text())
        manifest["apply_artifacts"]["events_hong_kong"] = CLASSIFIER.identity(
            paths["due_csv"], root=paths["classified"]
        )
        paths["manifest"].write_bytes(canonical(manifest))
        descriptor = json.loads(paths["descriptor"].read_text())
        descriptor["classified_manifest"] = CLASSIFIER.identity(
            paths["manifest"], root=paths["classified"]
        )
        descriptor["apply_artifacts"] = manifest["apply_artifacts"]
        paths["descriptor"].write_bytes(canonical(descriptor))
        paths["approval"].write_bytes(
            canonical(
                {
                    "status": "approved",
                    "approved_by": "test-operator",
                    "approved_at": "2026-07-15T15:00:00+08:00",
                    "cutoff_date": CUTOFF.isoformat(),
                    "descriptor_sha256": hashlib.sha256(
                        paths["descriptor"].read_bytes()
                    ).hexdigest(),
                    "classified_manifest_sha256": hashlib.sha256(
                        paths["manifest"].read_bytes()
                    ).hexdigest(),
                }
            )
        )

    def _fixture(
        self,
        root: Path,
        *,
        targets: list[HistoricalRaceEventTarget] | None = None,
    ) -> dict[str, Path]:
        targets = targets or [self._target(f"fixture-{RaceSeries.objects.count() + 1}")]
        bootstrap = root / "bootstrap-v2"
        requests = root / "requests-v2"
        parse = root / "parse-v2"
        classified = root / "classified-v2"
        for directory in (bootstrap, requests, parse):
            directory.mkdir()
        selection = bootstrap / "selection_snapshot.json"
        catalog = bootstrap / "source_catalog.json"
        request_manifest = requests / "manifest.json"
        parse_manifest = parse / "manifest.json"
        date_matches = parse / "date_matches.jsonl"
        gaps = parse / "gaps.jsonl"

        identities = [target_identity(target) for target in targets]
        selection.write_bytes(
            canonical(
                {
                    "schema_version": "1.0",
                    "inventory_manifest_sha256": "a" * 64,
                    "targets": identities,
                }
            )
        )
        catalog.write_bytes(canonical({"schema_version": "1.0", "sources": []}))
        request_manifest.write_bytes(
            canonical(
                {
                    "schema_version": "1.0",
                    "selection": CLASSIFIER.identity(selection, root=bootstrap),
                    "source_catalog": CLASSIFIER.identity(catalog, root=bootstrap),
                }
            )
        )
        date_matches.write_bytes(
            b"".join(canonical(self._date_match(target)) for target in targets)
        )
        gaps.write_bytes(b"")
        parse_manifest.write_bytes(
            canonical(
                {
                    "schema_version": "1.0",
                    "selection": CLASSIFIER.identity(selection, root=parse),
                    "source_catalog": CLASSIFIER.identity(catalog, root=parse),
                    "request_manifest": CLASSIFIER.identity(
                        request_manifest, root=parse
                    ),
                    "artifacts": {
                        "date_matches": CLASSIFIER.identity(date_matches, root=parse),
                        "gaps": CLASSIFIER.identity(gaps, root=parse),
                    },
                }
            )
        )
        CLASSIFIER.classify_due_checks(
            selection_path=selection,
            source_catalog_path=catalog,
            request_manifest_path=request_manifest,
            parse_manifest_path=parse_manifest,
            date_matches_path=date_matches,
            gaps_path=gaps,
            cutoff=CUTOFF,
            output_dir=classified,
        )
        paths = {
            "raw_csv": parse / "events_hong_kong.csv",
            "due_csv": classified / "events_hong_kong.csv",
            "manifest": classified / "manifest.json",
            "descriptor": classified / "apply_descriptor.json",
            "approval": classified / "apply_approval.json",
            "classified": classified,
        }
        self._refresh_signed_chain(paths)
        return paths

    def _argv(self, paths: dict[str, Path], *, dry_run: bool = True) -> list[str]:
        argv = [
            "--csv",
            str(paths["due_csv"]),
            "--current-year-descriptor",
            str(paths["descriptor"]),
            "--current-year-approval",
            str(paths["approval"]),
            "--approved-cutoff-date",
            CUTOFF.isoformat(),
        ]
        if dry_run:
            argv.append("--dry-run")
        return argv

    def test_raw_protected_year_is_rejected_even_when_clock_moves_to_2027(self):
        with TemporaryDirectory() as temporary:
            paths = self._fixture(Path(temporary))
            paths["raw_csv"].write_bytes(paths["due_csv"].read_bytes())

            with patch(
                "stable.management.commands.import_race_events.timezone.localdate",
                return_value=date(2027, 2, 1),
            ), self.assertRaisesRegex(CommandError, "current-year.*descriptor"):
                call_command(
                    "import_race_events",
                    "--csv",
                    str(paths["raw_csv"]),
                    "--dry-run",
                )

    def test_future_year_cannot_use_legacy_path(self):
        target = self._target("future-cup", year=2027)
        with TemporaryDirectory() as temporary:
            raw_csv = Path(temporary) / "events_hong_kong_2027.csv"
            row = self._date_match(target)
            row["source_refs"] = json.dumps(row["source_refs"])
            with raw_csv.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)

            with self.assertRaisesRegex(CommandError, "current-year.*descriptor"):
                call_command("import_race_events", "--csv", str(raw_csv), "--dry-run")

    def test_cutoff_after_today_is_rejected(self):
        with TemporaryDirectory() as temporary:
            paths = self._fixture(Path(temporary))

            with patch(
                "stable.management.commands.import_race_events.timezone.localdate",
                return_value=date(2026, 7, 14),
            ), self.assertRaisesRegex(CommandError, "cutoff.*today|未来"):
                call_command("import_race_events", *self._argv(paths))

    def test_manifest_or_due_csv_identity_drift_is_rejected(self):
        for drifted in ("manifest", "due_csv"):
            with self.subTest(drifted=drifted), TemporaryDirectory() as temporary:
                paths = self._fixture(Path(temporary))
                with paths[drifted].open("ab") as handle:
                    handle.write(b"drift")

                with self.assertRaisesRegex(CommandError, "identity|SHA|size"):
                    call_command("import_race_events", *self._argv(paths))

    def test_target_identity_drift_is_rejected_before_materialization(self):
        target = self._target("identity-drift")
        with TemporaryDirectory() as temporary:
            paths = self._fixture(Path(temporary), targets=[target])
            target.original_name = "Mutated after approval"
            target.save(update_fields={"original_name"})

            with self.assertRaisesRegex(CommandError, "target.*identity|身份"):
                call_command(
                    "import_race_events", *self._argv(paths, dry_run=False)
                )

        self.assertFalse(RaceEvent.objects.exists())
        self.assertFalse(TaskExecutionLog.objects.exists())

    def test_real_classifier_output_materializes_bound_non_public_event(self):
        target = self._target("classifier-output")
        with TemporaryDirectory() as temporary:
            paths = self._fixture(Path(temporary), targets=[target])
            classifier_rows = list(
                csv.DictReader(paths["due_csv"].open(encoding="utf-8-sig"))
            )
            self.assertNotIn("visibility_status", classifier_rows[0])
            self.assertNotIn("data_quality_status", classifier_rows[0])
            output = StringIO()

            call_command("import_race_events", *self._argv(paths), stdout=output)
            self.assertFalse(RaceEvent.objects.exists())
            call_command(
                "import_race_events",
                *self._argv(paths, dry_run=False),
                stdout=output,
            )

        target.refresh_from_db()
        event = target.event
        self.assertIsNotNone(event)
        self.assertEqual(event.race_series_id, target.race_series_id)
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.READY)
        self.assertEqual(event.local_date, date(2026, 1, 7))
        self.assertEqual(event.visibility_status, RaceEventVisibility.DRAFT)
        self.assertEqual(event.data_quality_status, RaceEventDataQuality.INCOMPLETE)
        self.assertFalse(event.is_featured)
        self.assertEqual(event.source_refs["historical_target_id"], target.pk)
        log = TaskExecutionLog.objects.get(task_name="import_race_events")
        self.assertEqual(log.payload["created"], 1)
        self.assertEqual(log.payload["adopted"], 0)
        self.assertIn("created=1 adopted=0", output.getvalue())

    def test_descriptor_adopts_unique_existing_event_without_changing_publication_state(self):
        target = self._target("existing-calendar-event")
        existing = RaceEvent.objects.create(
            race_series=target.race_series,
            year=target.year,
            slug="public-existing-calendar-event-2026",
            original_name=target.race_series.canonical_name_original,
            chinese_name=target.race_series.chinese_name,
            country_region=target.country_region,
            racecourse="Happy Valley",
            grade_text="G3",
            normalized_grade="G3",
            surface=RaceEventSurface.TURF,
            local_date=date(2026, 1, 7),
            status=RaceEventStatus.FINISHED,
            visibility_status=RaceEventVisibility.PUBLISHED,
            data_quality_status=RaceEventDataQuality.COMPLETE,
            is_featured=True,
        )
        manual_alias = RaceEventAlias.objects.create(
            event=existing,
            source_language="",
            text="Manual Alias",
            alias_type="manual-reviewed",
            source="operator",
            is_active=False,
        )
        with TemporaryDirectory() as temporary:
            paths = self._fixture(Path(temporary), targets=[target])
            rows = list(csv.DictReader(paths["due_csv"].open(encoding="utf-8-sig")))
            fieldnames = [*rows[0].keys(), "aliases"]
            rows[0]["aliases"] = "Manual Alias|New Alias"
            with paths["due_csv"].open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            self._refresh_signed_chain(paths)
            output = StringIO()
            call_command("import_race_events", *self._argv(paths, dry_run=False), stdout=output)

        target.refresh_from_db()
        existing.refresh_from_db()
        self.assertEqual(target.event_id, existing.pk)
        self.assertEqual(existing.visibility_status, RaceEventVisibility.PUBLISHED)
        self.assertEqual(existing.data_quality_status, RaceEventDataQuality.COMPLETE)
        self.assertTrue(existing.is_featured)
        manual_alias.refresh_from_db()
        self.assertEqual(manual_alias.alias_type, "manual-reviewed")
        self.assertEqual(manual_alias.source, "operator")
        self.assertFalse(manual_alias.is_active)
        self.assertTrue(RaceEventAlias.objects.filter(event=existing, text="New Alias", source="csv").exists())
        log = TaskExecutionLog.objects.get(task_name="import_race_events")
        self.assertEqual(log.payload["created"], 0)
        self.assertEqual(log.payload["adopted"], 1)
        self.assertEqual(log.payload["alias_count"], 1)
        self.assertIn("created=0 adopted=1", output.getvalue())

    def test_descriptor_ignores_explicit_publication_fields(self):
        target = self._target("explicit-publication")
        with TemporaryDirectory() as temporary:
            paths = self._fixture(Path(temporary), targets=[target])
            rows = list(csv.DictReader(paths["due_csv"].open(encoding="utf-8-sig")))
            fieldnames = [
                *rows[0].keys(),
                "visibility_status",
                "data_quality_status",
                "is_featured",
            ]
            rows[0].update(
                {
                    "visibility_status": RaceEventVisibility.PUBLISHED,
                    "data_quality_status": RaceEventDataQuality.COMPLETE,
                    "is_featured": "true",
                }
            )
            with paths["due_csv"].open(
                "w", encoding="utf-8-sig", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            self._refresh_signed_chain(paths)

            call_command("import_race_events", *self._argv(paths, dry_run=False))

        target.refresh_from_db()
        self.assertEqual(target.event.visibility_status, RaceEventVisibility.DRAFT)
        self.assertEqual(
            target.event.data_quality_status, RaceEventDataQuality.INCOMPLETE
        )
        self.assertFalse(target.event.is_featured)

    def test_published_fields_and_aliases_stay_inside_atomic_descriptor_apply(self):
        first = self._target("atomic-first")
        second = self._target("atomic-second")
        with TemporaryDirectory() as temporary:
            paths = self._fixture(Path(temporary), targets=[first, second])
            rows = list(csv.DictReader(paths["due_csv"].open(encoding="utf-8-sig")))
            fieldnames = [
                *rows[0].keys(),
                "visibility_status",
                "data_quality_status",
                "is_featured",
                "aliases",
            ]
            for row in rows:
                row.update(
                    {
                        "visibility_status": RaceEventVisibility.PUBLISHED,
                        "data_quality_status": RaceEventDataQuality.COMPLETE,
                        "is_featured": "true",
                        "aliases": "Approved alias",
                    }
                )
            with paths["due_csv"].open(
                "w", encoding="utf-8-sig", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            self._refresh_signed_chain(paths)
            conflicting = RaceEvent.objects.create(
                year=second.year,
                slug=historical_event_slug(second),
                race_series=self._target("other-series").race_series,
                original_name="Conflicting event",
                chinese_name="冲突赛事",
                country_region=RacingRegion.HONG_KONG,
                racecourse="Sha Tin",
                grade_text="G3",
                surface=RaceEventSurface.TURF,
                status=RaceEventStatus.FINISHED,
                visibility_status=RaceEventVisibility.DRAFT,
            )

            with self.assertRaisesRegex(CommandError, "slug|event.*conflict|冲突"):
                call_command(
                    "import_race_events", *self._argv(paths, dry_run=False)
                )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.resolution_status, HistoricalRaceResolutionStatus.PENDING)
        self.assertEqual(second.resolution_status, HistoricalRaceResolutionStatus.PENDING)
        self.assertIsNone(first.event_id)
        self.assertIsNone(second.event_id)
        self.assertEqual(list(RaceEvent.objects.values_list("pk", flat=True)), [conflicting.pk])
        self.assertFalse(RaceEventAlias.objects.exists())
        self.assertFalse(TaskExecutionLog.objects.exists())

    def test_completed_historical_year_csv_keeps_legacy_import_path(self):
        with TemporaryDirectory() as temporary:
            historical_csv = Path(temporary) / "events_hong_kong_2025.csv"
            row = {
                "year": 2025,
                "slug": "hong-kong-january-cup-2025",
                "original_name": "January Cup",
                "chinese_name": "一月杯",
                "country_region": RacingRegion.HONG_KONG,
                "racecourse": "Happy Valley",
                "grade_text": "G3",
                "surface": RaceEventSurface.TURF,
            }
            with historical_csv.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)

            call_command("import_race_events", "--csv", str(historical_csv))

        self.assertTrue(
            RaceEvent.objects.filter(
                year=2025, slug="hong-kong-january-cup-2025"
            ).exists()
        )

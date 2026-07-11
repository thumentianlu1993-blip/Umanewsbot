from __future__ import annotations

import csv
import hashlib
import json
import shutil
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase
from django.core.management import call_command

from stable.models import RaceEventSurface, RaceGrade, RacingRegion
from stable.services.historical_race_catalog_adapters import (
    ADAPTER_PARSER_VERSION,
    CATALOG_SCHEMA_VERSION,
    discover_catalog_and_timeline,
    parse_historical_catalog_manifest,
)
from stable.services.historical_race_inventory import InventoryValidationError


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "historical_race_catalog"
REGION_CASES = {
    "japan": {
        "adapter_key": "japan_official_catalog",
        "provider": "jra",
        "authority": "official_archive",
        "url": "https://www.jra.go.jp/datafile/gradedrace/",
        "region": RacingRegion.JAPAN,
        "years": {1984, 2000, 2026},
    },
    "hong_kong": {
        "adapter_key": "hkjc_official_catalog",
        "provider": "hkjc",
        "authority": "official_archive",
        "url": "https://racing.hkjc.com/racing/information/English/Racing/LocalResults.aspx",
        "region": RacingRegion.HONG_KONG,
        "years": {1988, 2000, 2026},
    },
    "united_kingdom": {
        "adapter_key": "bha_pattern_catalog",
        "provider": "bha",
        "authority": "official_archive",
        "url": "https://www.britishhorseracing.com/racing/fixtures/",
        "region": RacingRegion.UNITED_KINGDOM,
        "years": {1984, 2000, 2026},
    },
    "france": {
        "adapter_key": "france_galop_pattern_catalog",
        "provider": "france_galop",
        "authority": "official_archive",
        "url": "https://www.france-galop.com/fr/courses",
        "region": RacingRegion.FRANCE,
        "years": {1984, 2000, 2026},
    },
    "united_states": {
        "adapter_key": "toba_graded_stakes_catalog",
        "provider": "toba",
        "authority": "official_archive",
        "url": "https://toba.org/graded-stakes/",
        "region": RacingRegion.UNITED_STATES,
        "years": {1984, 2000, 2026},
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HistoricalRaceCatalogAdapterTests(SimpleTestCase):
    def _manifest(
        self,
        root: Path,
        region_key: str,
        *,
        source_csv: Path | None = None,
        cache_path: str = "source/catalog.csv",
        sha256: str | None = None,
        supported_years: dict[str, int] | None = None,
    ) -> Path:
        case = REGION_CASES[region_key]
        source = source_csv or FIXTURE_ROOT / region_key / "catalog_extract.csv"
        destination = root / cache_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        manifest = {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "adapter_key": case["adapter_key"],
            "parser_version": ADAPTER_PARSER_VERSION,
            "source_provider": case["provider"],
            "source_authority": case["authority"],
            "supported_years": supported_years or {"start": 1984, "end": 2026},
            "fixture_kind": "parser_contract_extract_not_complete_catalog",
            "cache_files": [
                {
                    "path": cache_path,
                    "sha256": sha256 or _sha256(destination),
                    "source_url": case["url"],
                }
            ],
        }
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def _csv(self, root: Path, rows: list[dict[str, str]]) -> Path:
        fields = [
            "record_type",
            "year",
            "series_key",
            "canonical_name_original",
            "original_name",
            "chinese_name",
            "grade_text",
            "racecourse",
            "local_date",
            "distance_text",
            "surface",
            "expectation_status",
            "founded_year",
            "ended_year",
            "series_status",
            "season_label",
            "source_scope",
            "discipline",
        ]
        root.mkdir(parents=True, exist_ok=True)
        path = root / "input.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_five_region_extracts_cover_1980s_middle_and_recent_eras(self):
        with TemporaryDirectory() as tmp:
            manifests = []
            for region_key in REGION_CASES:
                root = Path(tmp) / region_key
                manifest = self._manifest(root, region_key)
                manifests.append(manifest)
                rows = parse_historical_catalog_manifest(manifest)
                case = REGION_CASES[region_key]

                self.assertTrue(case["years"].issubset({row["year"] for row in rows}))
                self.assertEqual({row["country_region"] for row in rows}, {case["region"]})
                self.assertTrue(all(row["source_refs"]["source_cache_sha256"] for row in rows))
                self.assertTrue(all(row["source_refs"]["parser_version"] == ADAPTER_PARSER_VERSION for row in rows))

            discovered = discover_catalog_and_timeline(manifests)

        self.assertGreaterEqual(len(discovered["catalog"]), 15)
        self.assertEqual(
            {row["country_region"] for row in discovered["catalog"]},
            {case["region"] for case in REGION_CASES.values()},
        )

    def test_region_specific_formats_preserve_season_scope_discipline_and_accents(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hong_kong = parse_historical_catalog_manifest(self._manifest(root / "hk", "hong_kong"))
            japan = parse_historical_catalog_manifest(self._manifest(root / "jp", "japan"))
            united_kingdom = parse_historical_catalog_manifest(
                self._manifest(root / "uk", "united_kingdom")
            )
            france = parse_historical_catalog_manifest(self._manifest(root / "fr", "france"))

        self.assertEqual(hong_kong[0]["season_label"], "1987/88")
        self.assertEqual(hong_kong[0]["source_scope"], "international")
        self.assertEqual(japan[-1]["normalized_grade"], RaceGrade.JG1)
        self.assertEqual(japan[-1]["surface"], RaceEventSurface.JUMPS)
        self.assertEqual(japan[-1]["discipline"], "jumps")
        self.assertEqual(
            {row["discipline"] for row in united_kingdom},
            {"flat", "jumps"},
        )
        self.assertEqual(france[0]["canonical_name_original"], "Prix de l'Arc de Triomphe")

    def test_timeline_allows_pre_grade_and_cancelled_year_without_inventing_an_event(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hong_kong_manifest = self._manifest(root / "hk", "hong_kong")
            uk_manifest = self._manifest(root / "uk", "united_kingdom")
            discovered = discover_catalog_and_timeline([hong_kong_manifest, uk_manifest])

        pre_grade = next(row for row in discovered["timeline"] if row["year"] == 1988)
        cancelled = next(row for row in discovered["timeline"] if row["year"] == 2020)
        self.assertEqual(pre_grade["normalized_grade"], RaceGrade.OTHER)
        self.assertEqual(cancelled["expectation_status"], "cancelled")
        self.assertEqual(cancelled["local_date"], "")

    def test_same_display_name_can_remain_two_distinct_us_series(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                {
                    "record_type": "catalog",
                    "year": "2000",
                    "series_key": key,
                    "canonical_name_original": "Example Stakes",
                    "original_name": "Example Stakes",
                    "chinese_name": "示例锦标",
                    "grade_text": "Grade III",
                    "racecourse": course,
                    "local_date": "2000-06-01",
                    "distance_text": "1 mile",
                    "surface": "dirt",
                    "expectation_status": "held",
                    "founded_year": "1984",
                    "ended_year": "",
                    "series_status": "active",
                    "season_label": "",
                    "source_scope": "graded_stakes",
                    "discipline": "flat",
                }
                for key, course in (("us-example-east", "Belmont Park"), ("us-example-west", "Santa Anita"))
            ]
            source = self._csv(root, rows)
            parsed = parse_historical_catalog_manifest(
                self._manifest(root / "manifest-root", "united_states", source_csv=source)
            )

        self.assertEqual({row["series_key"] for row in parsed}, {"us-example-east", "us-example-west"})

    def test_timeline_only_series_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._csv(
                root,
                [
                    {
                        "record_type": "timeline",
                        "year": "1984",
                        "series_key": "never-graded",
                        "canonical_name_original": "Never Graded",
                        "original_name": "Never Graded",
                        "chinese_name": "",
                        "grade_text": "Ungraded",
                        "racecourse": "Epsom",
                        "local_date": "1984-01-01",
                        "distance_text": "1m",
                        "surface": "turf",
                        "expectation_status": "held",
                        "founded_year": "1984",
                        "ended_year": "",
                        "series_status": "ended",
                        "season_label": "",
                        "source_scope": "flat",
                        "discipline": "flat",
                    }
                ],
            )
            manifest = self._manifest(root / "manifest-root", "united_kingdom", source_csv=source)
            with self.assertRaisesMessage(InventoryValidationError, "never entered"):
                discover_catalog_and_timeline([manifest])

    def test_catalog_rejects_non_graded_entry(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._csv(
                root,
                [
                    {
                        "record_type": "catalog",
                        "year": "1984",
                        "series_key": "ordinary-race",
                        "canonical_name_original": "Ordinary Race",
                        "original_name": "Ordinary Race",
                        "chinese_name": "",
                        "grade_text": "Ungraded",
                        "racecourse": "Epsom",
                        "local_date": "1984-01-01",
                        "distance_text": "1m",
                        "surface": "turf",
                        "expectation_status": "held",
                        "founded_year": "1984",
                        "ended_year": "",
                        "series_status": "active",
                        "season_label": "",
                        "source_scope": "flat",
                        "discipline": "flat",
                    }
                ],
            )
            manifest = self._manifest(root / "manifest-root", "united_kingdom", source_csv=source)
            with self.assertRaisesMessage(InventoryValidationError, "unsupported historical grade"):
                parse_historical_catalog_manifest(manifest)

    def test_cache_identity_and_manifest_directory_boundary_fail_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_sha_manifest = self._manifest(root / "bad-sha", "france", sha256="0" * 64)
            with self.assertRaisesMessage(InventoryValidationError, "cache identity mismatch"):
                parse_historical_catalog_manifest(bad_sha_manifest)

            boundary = root / "boundary"
            boundary.mkdir()
            outside = root / "outside.csv"
            shutil.copy2(FIXTURE_ROOT / "france" / "catalog_extract.csv", outside)
            manifest = self._manifest(
                boundary,
                "france",
                source_csv=outside,
                cache_path="../outside.csv",
            )
            with self.assertRaisesMessage(InventoryValidationError, "outside manifest directory"):
                parse_historical_catalog_manifest(manifest)

    def test_management_command_writes_hashed_standard_candidates_for_inventory(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifests = [
                self._manifest(root / "sources" / region_key, region_key)
                for region_key in REGION_CASES
            ]
            output = root / "candidates"
            stdout = StringIO()
            args = [item for manifest in manifests for item in ("--source-manifest", str(manifest))]

            call_command(
                "parse_historical_race_catalog",
                *args,
                "--output-dir",
                str(output),
                stdout=stdout,
            )

            result = json.loads(stdout.getvalue())
            artifact_manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            catalog_lines = (output / "catalog_candidate.jsonl").read_text(encoding="utf-8").splitlines()
            timeline_lines = (output / "series_timeline_candidate.jsonl").read_text(encoding="utf-8").splitlines()
            inventory_output = root / "inventory"
            inventory_stdout = StringIO()
            call_command(
                "build_historical_race_inventory",
                "--catalog-jsonl",
                str(output / "catalog_candidate.jsonl"),
                "--timeline-jsonl",
                str(output / "series_timeline_candidate.jsonl"),
                "--output-dir",
                str(inventory_output),
                stdout=inventory_stdout,
            )
            inventory_result = json.loads(inventory_stdout.getvalue())
            inventory_approval = json.loads(
                (inventory_output / "approval.json").read_text(encoding="utf-8")
            )
            annual_targets = [
                json.loads(line)
                for line in (inventory_output / "annual_targets.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

        self.assertEqual(result["catalog_count"], len(catalog_lines))
        self.assertEqual(result["timeline_count"], len(timeline_lines))
        self.assertEqual(len(artifact_manifest["inputs"]), 5)
        self.assertEqual(
            set(artifact_manifest["artifacts"]),
            {"catalog_candidate", "series_timeline_candidate", "summary"},
        )
        self.assertEqual(
            catalog_lines,
            sorted(
                catalog_lines,
                key=lambda line: (
                    json.loads(line)["country_region"],
                    json.loads(line)["year"],
                    json.loads(line)["series_key"],
                ),
            ),
        )
        self.assertEqual(inventory_result["target_count"], len(catalog_lines) + len(timeline_lines))
        self.assertEqual(inventory_approval["status"], "pending")
        hong_kong_1988 = next(
            row
            for row in annual_targets
            if row["country_region"] == RacingRegion.HONG_KONG and row["year"] == 1988
        )
        self.assertEqual(hong_kong_1988["source_refs"]["season_label"], "1987/88")
        self.assertEqual(hong_kong_1988["source_refs"]["source_scope"], "international")
        self.assertEqual(hong_kong_1988["source_refs"]["discipline"], "flat")

    def test_management_command_refuses_to_overwrite_nonempty_output(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._manifest(root / "source", "japan")
            output = root / "candidates"
            output.mkdir()
            (output / "reviewed.txt").write_text("keep", encoding="utf-8")

            with self.assertRaisesMessage(Exception, "not empty"):
                call_command(
                    "parse_historical_race_catalog",
                    "--source-manifest",
                    str(manifest),
                    "--output-dir",
                    str(output),
                )
            self.assertEqual((output / "reviewed.txt").read_text(encoding="utf-8"), "keep")

    def test_manifest_may_cover_pre_1984_source_years_but_output_cannot(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._manifest(
                root,
                "united_states",
                supported_years={"start": 1973, "end": 2026},
            )

            rows = parse_historical_catalog_manifest(manifest)

        self.assertTrue(rows)
        self.assertTrue(all(row["year"] >= 1984 for row in rows))

    def test_hong_kong_season_and_local_date_must_match_calendar_year(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (FIXTURE_ROOT / "hong_kong" / "catalog_extract.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["season_label"] = "1987/99"
            bad_season = self._csv(root / "bad-season", rows)
            with self.assertRaisesMessage(InventoryValidationError, "season_label"):
                parse_historical_catalog_manifest(
                    self._manifest(root / "bad-season-manifest", "hong_kong", source_csv=bad_season)
                )

            rows[0]["season_label"] = "1987/88"
            rows[0]["local_date"] = "1989-01-24"
            bad_date = self._csv(root / "bad-date", rows)
            with self.assertRaisesMessage(InventoryValidationError, "local_date"):
                parse_historical_catalog_manifest(
                    self._manifest(root / "bad-date-manifest", "hong_kong", source_csv=bad_date)
                )

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


TOOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "runtime/tools/package_historical_race_source_discovery_gaps.py"
)


def load_tool():
    tools_path = str(TOOL_PATH.parent)
    if tools_path not in sys.path:
        sys.path.insert(0, tools_path)
    spec = importlib.util.spec_from_file_location("source_discovery_gap_packager", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HistoricalRaceSourceDiscoveryGapPackagerTests(SimpleTestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_packages_each_frozen_target_with_discovery_evidence_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            selection = root / "selection.json"
            evidence = root / "evidence.json"
            output = root / "parse-source-discovery"
            selection.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "targets": [
                            {
                                "target_id": target_id,
                                "target_sha256": f"{target_id}" * 64,
                                "inventory_artifact_sha256": "a" * 64,
                                "series_key": f"france-race-{target_id}",
                                "year": 2021,
                                "country_region": "france",
                            }
                            for target_id in (1, 2)
                        ],
                    }
                )
            )
            evidence.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "country_region": "france",
                        "edition_year": 2021,
                        "discovery_status": "source_discovery_pending",
                        "sources": [
                            {
                                "source_id": "france-docutheque",
                                "adapter_key": "france_galop",
                                "source_authority": "official",
                                "status": "discovery_page_verified",
                                "url": "https://www.france-galop.com/fr/content/programme-des-courses-agenda",
                            }
                        ],
                        "source_recipe": [{"discovery": "docutheque_groupes_listed"}],
                    }
                )
            )

            result = self.tool.package_source_discovery_gaps(
                selection_path=selection,
                evidence_path=evidence,
                country_region="france",
                year=2021,
                recorded_at="2026-07-15T12:45:00Z",
                output_dir=output,
            )

            self.assertEqual(result["scope_count"], 2)
            self.assertEqual(result["gap_count"], 2)
            gaps = [json.loads(line) for line in (output / "gaps.jsonl").read_text().splitlines()]
            self.assertEqual({row["target_id"] for row in gaps}, {1, 2})
            self.assertTrue(all(row["reason_code"] == "source_discovery_pending" for row in gaps))
            self.assertTrue(all(row["evidence_identity"]["sha256"] for row in gaps))
            self.assertEqual(gaps[0]["source_evidence"][0]["status"], "discovery_page_verified")

    def test_rejects_evidence_for_another_year(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            selection = root / "selection.json"
            evidence = root / "evidence.json"
            selection.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "targets": [
                            {
                                "target_id": 1,
                                "target_sha256": "1" * 64,
                                "inventory_artifact_sha256": "a" * 64,
                                "series_key": "france-race",
                                "year": 2021,
                                "country_region": "france",
                            }
                        ],
                    }
                )
            )
            evidence.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "country_region": "france",
                        "edition_year": 2020,
                        "discovery_status": "source_discovery_pending",
                        "sources": [],
                        "source_recipe": [],
                    }
                )
            )

            with self.assertRaisesRegex(self.tool.SourceDiscoveryGapError, "scope"):
                self.tool.package_source_discovery_gaps(
                    selection_path=selection,
                    evidence_path=evidence,
                    country_region="france",
                    year=2021,
                    recorded_at="2026-07-15T12:45:00Z",
                    output_dir=root / "output",
                )

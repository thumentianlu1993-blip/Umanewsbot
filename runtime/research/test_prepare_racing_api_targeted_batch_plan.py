#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_racing_api_targeted_batch_plan.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("targeted_batch_plan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PrepareRacingApiTargetedBatchPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def _fixture(self, root: Path) -> dict:
        seed_root = root / "seeds"
        seed_root.mkdir()
        rows = [
            {
                "schema_version": "targeted-horse-seed.v1",
                "seed_id": seed_id,
                "name": seed_id,
                "target": {
                    "country_region": region,
                    "year": year,
                    "local_date": date,
                },
            }
            for seed_id, region, year, date in (
                ("b", "united_kingdom", 2023, "2023-02-01"),
                ("a", "united_kingdom", 2023, "2023-01-01"),
                ("c", "france", 2026, "2026-01-01"),
            )
        ]
        ledger = seed_root / "targeted-horse-seeds.jsonl"
        ledger.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        manifest = {
            "schema_version": "targeted-horse-seed-ledger.v1",
            "status": "complete",
            "completion_marker": "COMPLETE",
            "database_writes": 0,
            "seed_count": 3,
            "target_manifest_sha256": "c" * 64,
            "target_ledger_sha256": "d" * 64,
            "seed_ledger": {"sha256": sha(ledger), "rows": 3},
        }
        manifest_path = seed_root / "seed-ledger-manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        (seed_root / "COMPLETE").write_text(sha(manifest_path) + "\n", encoding="ascii")
        return {
            "seed_root": seed_root,
            "approved_seed_manifest_sha256": sha(manifest_path),
            "approved_seed_ledger_sha256": sha(ledger),
            "output_dir": root / "output",
            "batch_size_cap": 2,
        }

    def test_partitions_by_region_year_with_exact_ceiling(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self._fixture(Path(temporary))
            manifest = self.module.prepare_batch_plan(**args)
            self.assertEqual(manifest["counts"]["seeds"], 3)
            self.assertEqual(manifest["counts"]["batches"], 2)
            self.assertEqual(manifest["counts"]["request_ceiling"], 48)
            self.assertEqual(manifest["parameters"]["per_seed_request_ceiling"], 16)
            batches = [
                json.loads(line)
                for line in (args["output_dir"] / "batch-plan.jsonl").read_text().splitlines()
            ]
            self.assertEqual([row["country_region"] for row in batches], ["france", "united_kingdom"])
            self.assertTrue((args["output_dir"] / "PREPARED").is_file())

    def test_seed_sha_drift_fails_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self._fixture(Path(temporary))
            args["approved_seed_ledger_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "identity"):
                self.module.prepare_batch_plan(**args)
            self.assertFalse(args["output_dir"].exists())

    def test_v2_seed_allows_missing_date_with_structured_race_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self._fixture(Path(temporary))
            ledger = args["seed_root"] / "targeted-horse-seeds.jsonl"
            row = {
                "schema_version": "targeted-horse-seed.v2",
                "seed_id": "pre2005-alpha",
                "name": "Alpha",
                "target": {
                    "country_region": "france",
                    "year": 2000,
                    "edition_year": 2000,
                    "canonical_name_original": "Prix Alpha",
                    "racecourse": "Longchamp",
                    "grade_text": "G1",
                    "discipline": "flat",
                },
            }
            ledger.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
            manifest_path = args["seed_root"] / "seed-ledger-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["seed_count"] = 1
            manifest["seed_ledger"] = {"sha256": sha(ledger), "rows": 1}
            manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
            (args["seed_root"] / "COMPLETE").write_text(sha(manifest_path) + "\n", encoding="ascii")
            args["approved_seed_manifest_sha256"] = sha(manifest_path)
            args["approved_seed_ledger_sha256"] = sha(ledger)

            plan = self.module.prepare_batch_plan(**args)

            self.assertEqual(plan["counts"]["seeds"], 1)
            self.assertEqual(plan["counts"]["batches"], 1)
            batch_row = json.loads((args["output_dir"] / "seed-ledgers" / "0001-france-2000-01.jsonl").read_text())
            self.assertNotIn("local_date", batch_row["target"])


if __name__ == "__main__":
    unittest.main()

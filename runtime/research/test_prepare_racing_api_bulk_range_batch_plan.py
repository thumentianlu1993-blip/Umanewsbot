#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("prepare_racing_api_bulk_range_batch_plan.py")


def load_tool():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("bulk_range_batch_plan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RacingApiBulkRangeBatchPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def classified(self, key: str, region: str, year: int) -> dict:
        return {
            "schema_version": "racing-api-bulk-target-classification.v1",
            "target_key": key,
            "country_region": region,
            "year": year,
            "grade_text": "G1",
            "discipline": "flat",
            "evidence_state": "source_route_only",
            "local_date_known": False,
            "route_class": "bulk_results_region_year_then_stable_id",
        }

    def target(self, classified: dict) -> dict:
        return {
            "target_key": classified["target_key"],
            "country_region": classified["country_region"],
            "year": classified["year"],
            "grade_text": classified["grade_text"],
            "discipline": classified["discipline"],
            "canonical_name_original": classified["target_key"],
        }

    def partition(self, region: str, year: int, keys: list[str], ranges: int) -> dict:
        date_ranges = [
            {
                "start_date": f"{year}-01-01",
                "end_date": f"{year}-06-30" if ranges == 2 else f"{year}-12-31",
                "max_pages_protocol_ceiling": 10,
            }
        ]
        if ranges == 2:
            date_ranges.append(
                {
                    "start_date": f"{year}-07-01",
                    "end_date": f"{year}-12-31",
                    "max_pages_protocol_ceiling": 10,
                }
            )
        import hashlib

        return {
            "schema_version": "racing-api-bulk-region-year-partition.v1",
            "country_region": region,
            "year": year,
            "target_count": len(keys),
            "target_keys_sha256": hashlib.sha256(
                ("\n".join(sorted(keys)) + "\n").encode("utf-8")
            ).hexdigest(),
            "evidence_state_counts": {"source_route_only": len(keys)},
            "ranges": date_ranges,
            "range_count": ranges,
            "protocol_request_ceiling": ranges * 10,
            "actual_request_count": None,
            "execution_ready": False,
        }

    def fixture(self):
        classified = [
            self.classified("france:2005:a", "france", 2005),
            self.classified("france:2006:b", "france", 2006),
            self.classified("france:2008:c", "france", 2008),
            self.classified("ireland:2005:d", "ireland", 2005),
        ]
        partitions = [
            self.partition("france", 2005, ["france:2005:a"], 1),
            self.partition("france", 2006, ["france:2006:b"], 1),
            self.partition("france", 2008, ["france:2008:c"], 2),
            self.partition("ireland", 2005, ["ireland:2005:d"], 1),
        ]
        return partitions, classified, [self.target(row) for row in classified]

    def test_packs_only_same_region_and_holds_configured_range_ceiling(self):
        partitions, classified, targets = self.fixture()
        batches = self.module.build_batches(
            partitions=partitions,
            bulk_targets=classified,
            target_rows=targets,
        )
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[0]["country_region"], "france")
        self.assertEqual(batches[0]["region_year_unit_count"], 3)
        self.assertEqual(batches[0]["date_range_count"], 4)
        self.assertEqual(batches[0]["request_ceiling"], 40)
        self.assertEqual(batches[0]["theoretical_min_duration_seconds"], 10.0)
        self.assertEqual(batches[1]["country_region"], "ireland")
        self.assertEqual(batches[1]["not_before_offset_minutes"], 5)
        self.assertFalse(batches[0]["execution_ready"])

    def test_target_classification_drift_and_parameter_escape_fail_closed(self):
        partitions, classified, targets = self.fixture()
        targets[0]["grade_text"] = "G2"
        with self.assertRaisesRegex(ValueError, "classification does not match"):
            self.module.build_batches(
                partitions=partitions,
                bulk_targets=classified,
                target_rows=targets,
            )
        with self.assertRaisesRegex(ValueError, "outside safety bounds"):
            self.module.build_batches(
                partitions=partitions,
                bulk_targets=classified,
                target_rows=[self.target(row) for row in classified],
                max_date_ranges_per_batch=367,
            )

    def test_prepare_writes_private_non_executable_exact_plan(self):
        partitions, classified, targets = self.fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target_root = root / "target"
            target_root.mkdir()
            output = root / "plan"
            target_identity = {
                "root": str(target_root.resolve()),
                "manifest_sha256": "1" * 64,
                "ledger_sha256": "2" * 64,
                "rows": len(targets),
                "as_of_date": "2026-08-29",
            }
            readiness = {
                "root": str((root / "readiness").resolve()),
                "report_sha256": "3" * 64,
                "partitions_sha256": "4" * 64,
                "bulk_targets_sha256": "5" * 64,
                "target_artifact": dict(target_identity),
                "counts": {},
            }
            with patch.object(
                self.module,
                "load_readiness_artifact",
                return_value=(partitions, classified, readiness),
            ), patch.object(
                self.module,
                "load_target_artifact",
                return_value=(targets, target_identity),
            ):
                summary = self.module.prepare_plan(
                    readiness_root=root / "readiness",
                    expected_readiness_report_sha256="3" * 64,
                    target_root=target_root,
                    expected_target_manifest_sha256="1" * 64,
                    expected_target_ledger_sha256="2" * 64,
                    output_dir=output,
                )
            manifest = json.loads(
                (output / "batch-plan-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["counts"]["batches"], 2)
            self.assertEqual(summary["counts"]["targets"], 4)
            self.assertEqual(summary["counts"]["protocol_request_ceiling"], 50)
            self.assertEqual(manifest["status"], "PROPOSED_NOT_APPROVED")
            self.assertFalse(manifest["approval"])
            self.assertFalse(manifest["execution_ready"])
            self.assertEqual(manifest["network_requests"], 0)
            self.assertEqual(manifest["database_writes"], 0)
            self.assertEqual(
                (output / "PREPARED").read_text(encoding="ascii").strip(),
                summary["manifest_sha256"],
            )
            self.assertEqual((output.stat().st_mode & 0o777), 0o700)
            self.assertEqual(
                len(list((output / "target-ledgers").glob("*.jsonl"))), 2
            )
            with self.assertRaisesRegex(ValueError, "must not already exist"):
                self.module.prepare_plan(
                    readiness_root=root / "readiness",
                    expected_readiness_report_sha256="3" * 64,
                    target_root=target_root,
                    expected_target_manifest_sha256="1" * 64,
                    expected_target_ledger_sha256="2" * 64,
                    output_dir=output,
                )


if __name__ == "__main__":
    unittest.main()

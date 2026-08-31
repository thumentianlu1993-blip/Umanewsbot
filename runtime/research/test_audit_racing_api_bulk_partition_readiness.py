#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPT = Path(__file__).with_name("audit_racing_api_bulk_partition_readiness.py")


def load_tool():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("bulk_partition_readiness", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RacingApiBulkPartitionReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def target(self, key: str, region: str, year: int) -> dict:
        return {
            "target_key": key,
            "country_region": region,
            "year": year,
            "grade_text": "G1",
            "discipline": "flat",
            "local_date": "",
        }

    def coverage(self, target: dict, state: str = "source_route_only") -> dict:
        return {
            "target_key": target["target_key"],
            "country_region": target["country_region"],
            "year": target["year"],
            "grade_text": target["grade_text"],
            "discipline": target["discipline"],
            "evidence_state": state,
        }

    def build(self, targets: list[dict], coverage: list[dict]) -> dict:
        return self.module.build_readiness(
            target_rows=targets,
            coverage_rows=coverage,
            target_identity={
                "manifest_sha256": "1" * 64,
                "ledger_sha256": "2" * 64,
                "rows": len(targets),
                "as_of_date": "2026-08-31",
            },
            coverage_identity={
                "manifest_sha256": "3" * 64,
                "plan_sha256": "4" * 64,
                "rows": len(coverage),
                "status": "review_required",
                "execution_ready": False,
            },
        )

    def test_classifies_cutoff_leap_current_and_not_due_without_execution(self):
        targets = [
            self.target("france:2004:pre", "france", 2004),
            self.target("france:2005:first", "france", 2005),
            self.target("ireland:2008:leap", "ireland", 2008),
            self.target("united_states:2026:due", "united_states", 2026),
            self.target("united_kingdom:2026:not-due", "united_kingdom", 2026),
        ]
        coverage = [self.coverage(target) for target in targets]
        coverage[-1]["evidence_state"] = "not_due_official_calendar"

        report = self.build(targets, coverage)

        self.assertEqual(report["status"], "BLOCKED_ENTITLEMENT_PROOF_AND_EXECUTION_PLAN")
        self.assertFalse(report["execution_ready"])
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(report["database_writes"], 0)
        self.assertEqual(
            report["counts"],
            {
                "targets": 5,
                "due_targets": 4,
                "bulk_eligible_2005_plus_targets": 3,
                "pre_2005_targeted_anchor_targets": 1,
                "not_due_targets": 1,
                "bulk_region_year_units": 3,
                "bulk_date_ranges": 974,
                "protocol_request_ceiling": 9740,
                "protocol_minimum_seconds_at_4_requests_per_second": 2435.0,
            },
        )
        partitions = {
            (row["country_region"], row["year"]): row for row in report["partitions"]
        }
        self.assertEqual(partitions[("france", 2005)]["range_count"], 365)
        self.assertEqual(partitions[("ireland", 2008)]["range_count"], 366)
        self.assertEqual(
            partitions[("united_states", 2026)]["ranges"][0],
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-01",
                "max_pages_protocol_ceiling": 10,
            },
        )
        self.assertEqual(
            partitions[("united_states", 2026)]["ranges"][-1]["start_date"],
            "2026-08-31",
        )

    def test_target_and_coverage_keys_must_conserve(self):
        target = self.target("france:2005:a", "france", 2005)
        other = self.target("france:2005:b", "france", 2005)
        with self.assertRaisesRegex(ValueError, "key sets do not conserve"):
            self.build([target], [self.coverage(other)])

    def test_execution_date_may_advance_with_fresh_calendar_in_same_year(self):
        target = self.target("france:2026:a", "france", 2026)
        report = self.module.build_readiness(
            target_rows=[target],
            coverage_rows=[self.coverage(target)],
            target_identity={
                "manifest_sha256": "1" * 64,
                "ledger_sha256": "2" * 64,
                "rows": 1,
                "as_of_date": "2026-08-29",
            },
            coverage_identity={
                "manifest_sha256": "3" * 64,
                "plan_sha256": "4" * 64,
                "rows": 1,
                "status": "review_required",
                "execution_ready": False,
                "calendar_as_of_date": "2026-08-31",
            },
            execution_as_of_date=date(2026, 8, 31),
        )

        self.assertEqual(report["execution_as_of_date"], "2026-08-31")
        self.assertEqual(
            report["partitions"][0]["ranges"][-1]["end_date"], "2026-08-31"
        )
        with self.assertRaisesRegex(ValueError, "calendar is stale"):
            self.module.build_readiness(
                target_rows=[target],
                coverage_rows=[self.coverage(target)],
                target_identity={
                    "manifest_sha256": "1" * 64,
                    "ledger_sha256": "2" * 64,
                    "rows": 1,
                    "as_of_date": "2026-08-29",
                },
                coverage_identity={
                    "calendar_as_of_date": "2026-08-31",
                },
                execution_as_of_date=date(2026, 9, 1),
            )

    def test_classification_field_drift_and_future_due_year_fail_closed(self):
        target = self.target("france:2005:a", "france", 2005)
        drifted = self.coverage(target)
        drifted["grade_text"] = "G2"
        with self.assertRaisesRegex(ValueError, "classification fields disagree"):
            self.build([target], [drifted])

        future = self.target("france:2027:a", "france", 2027)
        with self.assertRaisesRegex(ValueError, "after as_of_date"):
            self.build([future], [self.coverage(future)])

    def test_output_is_prepared_zero_write_artifact_and_existing_path_is_rejected(self):
        target = self.target("france:2005:a", "france", 2005)
        report = self.build([target], [self.coverage(target)])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "artifact"
            summary = self.module.write_audit(report, output)
            persisted = json.loads((output / "readiness-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], report["status"])
            self.assertEqual((output / "PREPARED").read_text(encoding="ascii").strip(), summary["report_sha256"])
            self.assertEqual(persisted["network_requests"], 0)
            self.assertEqual(persisted["database_writes"], 0)
            self.assertEqual(persisted["outputs"]["bulk-partitions.jsonl"]["rows"], 1)
            with self.assertRaisesRegex(ValueError, "must not already exist"):
                self.module.write_audit(report, output)


if __name__ == "__main__":
    unittest.main()

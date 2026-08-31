#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("audit_stable_id_enrichment_readiness.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("stable_enrichment_readiness", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class StableEnrichmentReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def seed(self, horse_id: str, source_seed_id: str, region: str, year: int) -> dict:
        return {
            "schema_version": "targeted-runner-stable-id-seed.v2",
            "horse_id": horse_id,
            "target_occurrences": [
                {
                    "source_targeted_seed_id": source_seed_id,
                    "race_id": f"rac_{horse_id}",
                    "target": {
                        "country_region": region,
                        "year": year,
                        "local_date": f"{year}-01-01",
                    },
                }
            ],
        }

    def test_reports_source_gap_and_conservative_budget_without_execution(self):
        stable = [
            self.seed("hrs_a", "held-a", "france", 2023),
            self.seed("hrs_b", "external-b", "ireland", 2024),
        ]
        with patch.object(
            self.module,
            "load_stable_runner_ledger",
            return_value=(stable, {"manifest_sha256": "1" * 64}),
        ), patch.object(
            self.module,
            "_load_held_seed_proposal",
            return_value=([{"seed_id": "held-a"}], {"manifest_sha256": "2" * 64}),
        ):
            report = self.module.build_readiness_audit(
                stable_runner_ledger_root=Path("/stable"),
                approved_stable_runner_manifest_sha256="1" * 64,
                held_seed_proposal_root=Path("/held"),
                approved_held_seed_proposal_manifest_sha256="2" * 64,
                audited_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
            )
        self.assertEqual(report["status"], "BLOCKED_SOURCE_CENSUS_AND_APPROVAL_GAPS")
        self.assertEqual(report["missing_from_held_seed_ids"], ["external-b"])
        self.assertEqual(report["counts"]["request_ceiling_if_approved"], 414)
        self.assertFalse(report["execution_ready"])
        self.assertEqual(report["network_requests"], 0)

    def test_proposal_coverage_without_approval_is_reported_as_approval_gap(self):
        stable = [self.seed("hrs_a", "held-a", "france", 2023)]
        with patch.object(
            self.module,
            "load_stable_runner_ledger",
            return_value=(stable, {"manifest_sha256": "1" * 64}),
        ), patch.object(
            self.module,
            "_load_held_seed_proposal",
            return_value=([{"seed_id": "held-a"}], {"manifest_sha256": "2" * 64}),
        ):
            report = self.module.build_readiness_audit(
                stable_runner_ledger_root=Path("/stable"),
                approved_stable_runner_manifest_sha256="1" * 64,
                held_seed_proposal_root=Path("/held"),
                approved_held_seed_proposal_manifest_sha256="2" * 64,
            )
        self.assertEqual(report["status"], "BLOCKED_SOURCE_APPROVAL_GAPS")
        self.assertEqual(report["missing_from_held_seed_ids"], [])
        self.assertEqual(report["unapproved_occurrence_seed_ids"], ["held-a"])
        self.assertIn(
            "held winner seed proposal has no independent COMPLETE approval",
            report["blockers"],
        )

    def test_approved_held_seed_closes_approval_gap_but_not_reconciliation(self):
        stable = [self.seed("hrs_a", "held-a", "france", 2023)]
        held_rows = [{"seed_id": "held-a"}, {"seed_id": "held-unused"}]
        with patch.object(
            self.module,
            "load_stable_runner_ledger",
            return_value=(stable, {"manifest_sha256": "1" * 64}),
        ), patch.object(
            self.module,
            "_load_held_seed_proposal",
            return_value=(held_rows, {"manifest_sha256": "2" * 64}),
        ), patch.object(
            self.module,
            "_load_approved_held_seed",
            return_value=(held_rows, {"manifest_sha256": "3" * 64, "approval": True}),
        ):
            report = self.module.build_readiness_audit(
                stable_runner_ledger_root=Path("/stable"),
                approved_stable_runner_manifest_sha256="1" * 64,
                held_seed_proposal_root=Path("/held"),
                approved_held_seed_proposal_manifest_sha256="2" * 64,
                approved_held_seed_root=Path("/approved-held"),
                approved_held_seed_manifest_sha256="3" * 64,
                approved_held_seed_ledger_sha256="4" * 64,
            )
        self.assertEqual(report["status"], "BLOCKED_APPROVED_RECONCILIATION_MISSING")
        self.assertEqual(report["approved_held_seed_ids"], ["held-a"])
        self.assertEqual(report["counts"]["approved_occurrence_seed_ids"], 1)
        self.assertEqual(report["unapproved_occurrence_seed_ids"], [])
        self.assertNotIn(
            "held winner seed proposal has no independent COMPLETE approval",
            report["blockers"],
        )

    def test_approved_external_census_closes_external_approval_gap(self):
        stable = [
            self.seed("hrs_a", "held-a", "france", 2023),
            self.seed("hrs_b", "external-b", "ireland", 2024),
        ]
        held_rows = [{"seed_id": "held-a"}]
        stable_identity = {"manifest_sha256": "1" * 64}
        with patch.object(
            self.module,
            "load_stable_runner_ledger",
            return_value=(stable, stable_identity),
        ), patch.object(
            self.module,
            "_load_held_seed_proposal",
            return_value=(held_rows, {"manifest_sha256": "2" * 64}),
        ), patch.object(
            self.module,
            "_load_approved_held_seed",
            return_value=(held_rows, {"manifest_sha256": "3" * 64, "approval": True}),
        ), patch.object(
            self.module,
            "_load_approved_external_census",
            return_value=(
                {"external-b"},
                {
                    "manifest_sha256": "5" * 64,
                    "starter_rows": 1,
                    "approval": True,
                },
            ),
        ):
            report = self.module.build_readiness_audit(
                stable_runner_ledger_root=Path("/stable"),
                approved_stable_runner_manifest_sha256="1" * 64,
                held_seed_proposal_root=Path("/held"),
                approved_held_seed_proposal_manifest_sha256="2" * 64,
                approved_held_seed_root=Path("/approved-held"),
                approved_held_seed_manifest_sha256="3" * 64,
                approved_held_seed_ledger_sha256="4" * 64,
                external_census_approvals=[(Path("/approved-external"), "5" * 64)],
            )
        self.assertEqual(report["status"], "BLOCKED_APPROVED_RECONCILIATION_MISSING")
        self.assertEqual(report["approved_external_census_seed_ids"], ["external-b"])
        self.assertEqual(report["counts"]["approved_occurrence_seed_ids"], 2)
        self.assertEqual(report["uncensused_occurrence_seed_ids"], [])

    def test_partial_approved_held_identity_is_rejected(self):
        stable = [self.seed("hrs_a", "held-a", "france", 2023)]
        with patch.object(
            self.module,
            "load_stable_runner_ledger",
            return_value=(stable, {"manifest_sha256": "1" * 64}),
        ), patch.object(
            self.module,
            "_load_held_seed_proposal",
            return_value=([{"seed_id": "held-a"}], {"manifest_sha256": "2" * 64}),
        ), self.assertRaisesRegex(
            self.module.StableEnrichmentReadinessError,
            "must be supplied together",
        ):
            self.module.build_readiness_audit(
                stable_runner_ledger_root=Path("/stable"),
                approved_stable_runner_manifest_sha256="1" * 64,
                held_seed_proposal_root=Path("/held"),
                approved_held_seed_proposal_manifest_sha256="2" * 64,
                approved_held_seed_root=Path("/approved-held"),
            )

    def test_prepared_external_census_closes_absence_but_not_approval(self):
        stable = [
            self.seed("hrs_a", "held-a", "france", 2023),
            self.seed("hrs_b", "external-b", "ireland", 2024),
        ]
        stable_identity = {"manifest_sha256": "1" * 64}
        external_identity = {
            "manifest_sha256": "3" * 64,
            "source_targeted_seed_id": "external-b",
            "stable_runner_manifest_sha256": "1" * 64,
            "starter_rows": 1,
            "candidate_crosswalk_rows": 1,
            "approval": False,
        }
        with patch.object(
            self.module,
            "load_stable_runner_ledger",
            return_value=(stable, stable_identity),
        ), patch.object(
            self.module,
            "_load_held_seed_proposal",
            return_value=([{"seed_id": "held-a"}], {"manifest_sha256": "2" * 64}),
        ), patch.object(
            self.module,
            "load_external_census_proposal",
            return_value=([{}], [{}], external_identity),
        ):
            report = self.module.build_readiness_audit(
                stable_runner_ledger_root=Path("/stable"),
                approved_stable_runner_manifest_sha256="1" * 64,
                held_seed_proposal_root=Path("/held"),
                approved_held_seed_proposal_manifest_sha256="2" * 64,
                external_census_proposals=[(Path("/external"), "3" * 64)],
            )
        self.assertEqual(
            report["status"],
            "BLOCKED_EXTERNAL_CENSUS_AND_APPROVAL_GAPS",
        )
        self.assertEqual(report["prepared_external_census_seed_ids"], ["external-b"])
        self.assertEqual(report["uncensused_occurrence_seed_ids"], [])
        self.assertEqual(report["counts"]["prepared_external_census_proposals"], 1)
        self.assertFalse(report["execution_ready"])

    def test_external_census_must_bind_same_stable_ledger(self):
        stable = [self.seed("hrs_b", "external-b", "ireland", 2024)]
        with patch.object(
            self.module,
            "load_stable_runner_ledger",
            return_value=(stable, {"manifest_sha256": "1" * 64}),
        ), patch.object(
            self.module,
            "_load_held_seed_proposal",
            return_value=([], {"manifest_sha256": "2" * 64}),
        ), patch.object(
            self.module,
            "load_external_census_proposal",
            return_value=(
                [{}],
                [{}],
                {
                    "source_targeted_seed_id": "external-b",
                    "stable_runner_manifest_sha256": "9" * 64,
                    "starter_rows": 1,
                    "candidate_crosswalk_rows": 1,
                    "approval": False,
                },
            ),
        ):
            with self.assertRaisesRegex(
                self.module.StableEnrichmentReadinessError,
                "does not bind one uncovered stable occurrence seed",
            ):
                self.module.build_readiness_audit(
                    stable_runner_ledger_root=Path("/stable"),
                    approved_stable_runner_manifest_sha256="1" * 64,
                    held_seed_proposal_root=Path("/held"),
                    approved_held_seed_proposal_manifest_sha256="2" * 64,
                    external_census_proposals=[(Path("/external"), "3" * 64)],
                )

    def test_parameter_and_output_contracts_fail_closed(self):
        stable = [self.seed("hrs_a", "held-a", "france", 2023)]
        with patch.object(
            self.module,
            "load_stable_runner_ledger",
            return_value=(stable, {}),
        ), patch.object(
            self.module,
            "_load_held_seed_proposal",
            return_value=([{"seed_id": "held-a"}], {}),
        ):
            with self.assertRaisesRegex(
                self.module.StableEnrichmentReadinessError, "safety bounds"
            ):
                self.module.build_readiness_audit(
                    stable_runner_ledger_root=Path("/stable"),
                    approved_stable_runner_manifest_sha256="1" * 64,
                    held_seed_proposal_root=Path("/held"),
                    approved_held_seed_proposal_manifest_sha256="2" * 64,
                    min_interval_ms=249,
                )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(
                self.module.StableEnrichmentReadinessError, "must not already exist"
            ):
                self.module.write_audit(
                    {
                        "status": "BLOCKED",
                        "counts": {
                            "unique_horses": 0,
                            "target_occurrence_rows": 0,
                            "held_covered_seed_ids": 0,
                            "occurrence_seed_ids": 0,
                            "planned_batches_if_approved": 0,
                            "request_ceiling_if_approved": 0,
                            "schedule_span_minutes_if_approved": 0,
                        },
                        "missing_from_held_seed_ids": [],
                    },
                    existing,
                )


if __name__ == "__main__":
    unittest.main()

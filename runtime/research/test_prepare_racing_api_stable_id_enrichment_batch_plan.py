#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("prepare_racing_api_stable_id_enrichment_batch_plan.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("stable_id_enrichment_batch_plan", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class StableIdEnrichmentBatchPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def seed(self, horse_id: str, region="france", date="2026-01-02") -> dict:
        return {
            "schema_version": "targeted-runner-stable-id-seed.v1",
            "seed_id": f"target-runner-{horse_id}",
            "horse_id": horse_id,
            "source_names": [horse_id],
            "source_targeted_batch_manifest_sha256": "a" * 64,
            "target_occurrences": [
                {
                    "race_id": f"rac_{horse_id}",
                    "target": {
                        "country_region": region,
                        "local_date": date,
                        "year": int(date[:4]),
                        "grade_text": "G3",
                        "discipline": "flat",
                    },
                }
            ],
        }

    def reconciliation_artifact(self, root: Path, stable_identity: dict, horse_ids: list[str]):
        proposal = root / "proposal"
        proposal.mkdir()
        output_shas = {
            "binding-candidates.jsonl": "1" * 64,
            "review-items.jsonl": "2" * 64,
            "target-summaries.jsonl": "3" * 64,
        }
        proposal_manifest = {
            "schema_version": "held-census-tra-reconciliation-proposal.v1",
            "status": "PREPARED_NOT_EXECUTABLE",
            "stable_runner_ledger": stable_identity,
            "outputs": {
                name: {"sha256": sha}
                for name, sha in output_shas.items()
            },
        }
        proposal_manifest_path = proposal / "proposal-manifest.json"
        proposal_manifest_path.write_text(json.dumps(proposal_manifest, indent=2, sort_keys=True) + "\n")
        proposal_sha = hashlib.sha256(proposal_manifest_path.read_bytes()).hexdigest()

        approved = root / "approved"
        approved.mkdir()
        bindings = [
            {
                "schema_version": "held-starter-tra-binding-candidate.v1",
                "target_key": f"france:2026:target-{index}:flat",
                "starter_occurrence_key": f"slot-{index}",
                "tra_horse_id": horse_id,
            }
            for index, horse_id in enumerate(horse_ids, 1)
        ]
        binding_body = "".join(canonical(row) + "\n" for row in bindings).encode()
        binding_path = approved / "approved-bindings.jsonl"
        binding_path.write_bytes(binding_body)
        decision = {
            "schema_version": "held-census-tra-reconciliation-approval-decision.v1",
            "decision": "approve",
        }
        decision_path = approved / "approval-decision.json"
        decision_path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n")
        decision_sha = hashlib.sha256(decision_path.read_bytes()).hexdigest()
        manifest = {
            "schema_version": "held-census-tra-reconciliation-approval.v1",
            "status": "complete",
            "completion_marker": "COMPLETE",
            "network_requests": 0,
            "database_writes": 0,
            "source_proposal": {
                "root": str(proposal),
                "manifest_sha256": proposal_sha,
                "approved_outputs": output_shas,
            },
            "decision": {
                "sha256": decision_sha,
                "reviewed_by": "independent-reviewer",
                "reviewed_at": "2026-08-30T12:00:00+08:00",
                "decision_source_reference": "review://stable-plan/1",
                "independence_acknowledgement": "REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR",
            },
            "approval_decision": {
                "path": decision_path.name,
                "size": decision_path.stat().st_size,
                "sha256": decision_sha,
            },
            "counts": {
                "targets": len(bindings),
                "approved_starter_bindings": len(bindings),
                "unique_tra_horse_ids": len(set(horse_ids)),
                "review_items": 0,
                "count_mismatches": 0,
            },
            "approved_bindings": {
                "path": binding_path.name,
                "rows": len(bindings),
                "size": len(binding_body),
                "sha256": hashlib.sha256(binding_body).hexdigest(),
            },
        }
        manifest_path = approved / "approval-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (approved / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
        return approved, manifest_sha

    def coverage_artifact(
        self,
        root: Path,
        stable_identity: dict,
        occurrences: list[tuple[str, str, str]],
    ):
        components = []
        for index, (component_type, schema_version) in enumerate(
            (
                (
                    "held_census_reconciliation_approval",
                    "held-census-tra-reconciliation-approval.v1",
                ),
                (
                    "external_census_occurrence_approval",
                    "external-result-actual-starter-census-approval.v1",
                ),
            ),
            1,
        ):
            component_root = root / f"component-{index}"
            component_root.mkdir()
            component_manifest = component_root / "approval-manifest.json"
            component_manifest.write_text(
                json.dumps(
                    {"schema_version": schema_version, "status": "complete"},
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            component_sha = hashlib.sha256(component_manifest.read_bytes()).hexdigest()
            (component_root / "COMPLETE").write_text(component_sha + "\n")
            components.append(
                {
                    "type": component_type,
                    "root": str(component_root.resolve()),
                    "manifest_sha256": component_sha,
                    "binding_rows": 1,
                }
            )
        coverage = root / "coverage"
        coverage.mkdir()
        bindings = []
        for index, (horse_id, race_id, seed_id) in enumerate(occurrences, 1):
            occurrence_key = canonical(
                {
                    "horse_id": horse_id,
                    "race_id": race_id,
                    "source_targeted_seed_id": seed_id,
                }
            )
            bindings.append(
                {
                    "schema_version": "stable-id-reconciliation-coverage-binding.v1",
                    "occurrence_key": occurrence_key,
                    "horse_id": horse_id,
                    "race_id": race_id,
                    "source_targeted_seed_id": seed_id,
                    "target_key": f"france:2026:target-{index}:flat",
                    "starter_occurrence_key": f"slot-{index}",
                    "component_type": components[index - 1]["type"],
                    "component_manifest_sha256": components[index - 1][
                        "manifest_sha256"
                    ],
                    "component_binding_sha256": "8" * 64,
                    "stable_occurrence_sha256": "9" * 64,
                }
            )
        body = "".join(canonical(row) + "\n" for row in bindings).encode()
        binding_path = coverage / "coverage-bindings.jsonl"
        binding_path.write_bytes(body)
        horse_ids = {row[0] for row in occurrences}
        manifest = {
            "schema_version": "stable-id-reconciliation-coverage.v1",
            "status": "complete",
            "completion_marker": "COMPLETE",
            "coverage_complete": True,
            "planning_eligible": True,
            "network_execution_authorized": False,
            "database_write_authorized": False,
            "network_requests": 0,
            "database_writes": 0,
            "stable_runner_ledger": stable_identity,
            "components": components,
            "counts": {
                "stable_occurrences": len(bindings),
                "covered_occurrences": len(bindings),
                "stable_horses": len(horse_ids),
                "unique_tra_horse_ids": len(horse_ids),
                "overlap_or_gap_count": 0,
            },
            "coverage_bindings": {
                "path": binding_path.name,
                "rows": len(bindings),
                "size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            },
        }
        manifest_path = coverage / "coverage-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (coverage / "COMPLETE").write_text(manifest_sha + "\n")
        return coverage, manifest_sha

    def test_stable_batches_have_zero_search_and_full_pagination_ceiling(self):
        seeds = [self.seed("hrs_a"), self.seed("hrs_b"), self.seed("hrs_c")]
        seeds[1]["schema_version"] = "targeted-runner-stable-id-seed.v2"
        seeds[1]["source_targeted_batch_manifest_sha256s"] = ["a" * 64]
        seeds[1].pop("source_targeted_batch_manifest_sha256", None)
        stable_identity = {
            "root": "/stable",
            "manifest_sha256": "4" * 64,
            "ledger_sha256": "5" * 64,
            "stable_horse_rows": 3,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(
                self.module,
                "load_stable_runner_ledger",
                return_value=(seeds, stable_identity),
            ), patch.object(
                self.module,
                "_load_approved_reconciliation",
                return_value={"manifest_sha256": "6" * 64},
            ):
                manifest = self.module.prepare_batch_plan(
                    stable_runner_ledger_root=root / "stable",
                    approved_stable_runner_manifest_sha256="4" * 64,
                    approved_reconciliation_root=root / "approved",
                    approved_reconciliation_manifest_sha256="6" * 64,
                    output_dir=root / "plan",
                    batch_size_cap=2,
                )
            batches = [
                json.loads(line)
                for line in (root / "plan" / "batch-plan.jsonl").read_text().splitlines()
            ]
            from runtime.research import racing_api_targeted_batch_execution_ledger as execution

            loaded = execution._load_plan(
                plan_root=root / "plan",
                expected_manifest_sha256=self.module.sha256_path(
                    root / "plan" / "batch-plan-manifest.json"
                ),
                expected_plan_sha256=self.module.sha256_path(
                    root / "plan" / "batch-plan.jsonl"
                ),
            )
        self.assertEqual(manifest["parameters"]["search_requests_per_seed"], 0)
        self.assertEqual(manifest["parameters"]["max_results_pages_per_horse"], 201)
        self.assertEqual(manifest["parameters"]["per_seed_request_ceiling"], 207)
        self.assertEqual(manifest["counts"]["request_ceiling"], 621)
        self.assertEqual([row["request_ceiling"] for row in batches], [414, 207])
        self.assertEqual(manifest["status"], "PROPOSED_NOT_APPROVED")
        self.assertEqual(len(loaded["batches"]), 2)
        self.assertNotIn("horse_search", execution._plan_endpoint_kinds(loaded))

    def test_execution_scope_keeps_search_for_legacy_plans_and_rejects_invalid_values(self):
        from runtime.research import racing_api_targeted_batch_execution_ledger as execution

        legacy = {"manifest": {"parameters": {}}}
        self.assertIn("horse_search", execution._plan_endpoint_kinds(legacy))
        for value in (True, -1, "0"):
            with self.subTest(value=value), self.assertRaisesRegex(
                execution.TargetedBatchExecutionError,
                "non-negative integer",
            ):
                execution._plan_endpoint_kinds(
                    {
                        "manifest": {
                            "parameters": {"search_requests_per_seed": value}
                        }
                    }
                )

    def test_results_page_or_rate_parameters_cannot_exceed_safety_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kwargs in (
                {"max_results_pages_per_horse": 202},
                {"min_interval_ms": 249},
                {"batch_size_cap": 21},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "safety bounds"):
                    self.module.prepare_batch_plan(
                        stable_runner_ledger_root=root / "stable",
                        approved_stable_runner_manifest_sha256="4" * 64,
                        approved_reconciliation_root=root / "approved",
                        approved_reconciliation_manifest_sha256="6" * 64,
                        output_dir=root / f"plan-{len(kwargs)}-{next(iter(kwargs))}",
                        **kwargs,
                    )

    def test_planning_bucket_is_deterministic_for_multi_target_horse(self):
        seed = self.seed("hrs_a", region="united_kingdom", date="2024-01-02")
        seed["target_occurrences"].append(
            {
                "race_id": "rac_france",
                "target": {
                    "country_region": "france",
                    "local_date": "2025-02-03",
                    "year": 2025,
                    "grade_text": "G1",
                    "discipline": "flat",
                },
            }
        )
        self.assertEqual(self.module._planning_bucket(seed), ("france", 2025))

    def test_approved_reconciliation_must_bind_exact_stable_ledger_and_horse_set(self):
        stable_identity = {
            "root": "/stable/root",
            "manifest_sha256": "4" * 64,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            approved, manifest_sha = self.reconciliation_artifact(
                root,
                stable_identity,
                ["hrs_a", "hrs_b"],
            )
            identity = self.module._load_approved_reconciliation(
                approved,
                approved_manifest_sha256=manifest_sha,
                stable_identity=stable_identity,
                expected_horse_ids={"hrs_a", "hrs_b"},
            )
            self.assertEqual(identity["unique_tra_horse_ids"], 2)
            with self.assertRaisesRegex(ValueError, "exact stable runner ledger"):
                self.module._load_approved_reconciliation(
                    approved,
                    approved_manifest_sha256=manifest_sha,
                    stable_identity={**stable_identity, "manifest_sha256": "7" * 64},
                    expected_horse_ids={"hrs_a", "hrs_b"},
                )
            with self.assertRaisesRegex(ValueError, "binding conservation"):
                self.module._load_approved_reconciliation(
                    approved,
                    approved_manifest_sha256=manifest_sha,
                    stable_identity=stable_identity,
                    expected_horse_ids={"hrs_a", "hrs_c"},
                )

    def test_mixed_source_coverage_must_bind_every_exact_occurrence(self):
        stable_identity = {
            "root": "/stable/root",
            "manifest_sha256": "4" * 64,
        }
        occurrences = [
            ("hrs_a", "rac_a", "held-a"),
            ("hrs_b", "rac_b", "external-b"),
        ]
        occurrence_keys = {
            canonical(
                {
                    "horse_id": horse_id,
                    "race_id": race_id,
                    "source_targeted_seed_id": seed_id,
                }
            )
            for horse_id, race_id, seed_id in occurrences
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            coverage, manifest_sha = self.coverage_artifact(
                root, stable_identity, occurrences
            )
            identity = self.module._load_approved_reconciliation(
                coverage,
                approved_manifest_sha256=manifest_sha,
                stable_identity=stable_identity,
                expected_horse_ids={"hrs_a", "hrs_b"},
                expected_occurrence_keys=occurrence_keys,
            )
            self.assertEqual(identity["schema_version"], "stable-id-reconciliation-coverage.v1")
            self.assertEqual(identity["approved_binding_rows"], 2)
            with self.assertRaisesRegex(ValueError, "binding conservation"):
                self.module._load_approved_reconciliation(
                    coverage,
                    approved_manifest_sha256=manifest_sha,
                    stable_identity=stable_identity,
                    expected_horse_ids={"hrs_a", "hrs_b"},
                    expected_occurrence_keys={next(iter(occurrence_keys))},
                )
    def test_duplicate_or_invalid_stable_horse_ids_are_rejected_before_planning(self):
        seeds = [self.seed("hrs_a"), self.seed("hrs_a")]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(
                self.module,
                "load_stable_runner_ledger",
                return_value=(seeds, {"root": "/stable", "manifest_sha256": "4" * 64}),
            ):
                with self.assertRaisesRegex(ValueError, "identity drift"):
                    self.module.prepare_batch_plan(
                        stable_runner_ledger_root=root / "stable",
                        approved_stable_runner_manifest_sha256="4" * 64,
                        approved_reconciliation_root=root / "approved",
                        approved_reconciliation_manifest_sha256="6" * 64,
                        output_dir=root / "plan",
                    )


if __name__ == "__main__":
    unittest.main()

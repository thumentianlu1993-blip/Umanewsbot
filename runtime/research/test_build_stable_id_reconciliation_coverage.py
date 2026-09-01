#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("build_stable_id_reconciliation_coverage.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("stable_reconciliation_coverage", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class StableReconciliationCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def occurrence(self, horse_id: str, race_id: str, seed_id: str) -> tuple[dict, dict]:
        occurrence = {
            "race_id": race_id,
            "source_targeted_seed_id": seed_id,
            "source_runner_payload_sha256": "1" * 64,
            "target_race_payload_sha256": "2" * 64,
            "target": {"country_region": "france", "local_date": "2026-01-01"},
        }
        return (
            {"horse_id": horse_id, "target_occurrences": [occurrence]},
            occurrence,
        )

    def coverage_row(
        self,
        horse_id: str,
        race_id: str,
        seed_id: str,
        occurrence: dict,
        component_type: str,
    ) -> dict:
        key = self.module.occurrence_key(horse_id, occurrence)
        return {
            "schema_version": self.module.BINDING_SCHEMA_VERSION,
            "occurrence_key": key,
            "horse_id": horse_id,
            "race_id": race_id,
            "source_targeted_seed_id": seed_id,
            "target_key": f"france:2026:{race_id}:flat",
            "starter_occurrence_key": f"slot-{horse_id}",
            "component_type": component_type,
            "component_manifest_sha256": "3" * 64,
            "component_binding_sha256": "4" * 64,
            "stable_occurrence_sha256": "5" * 64,
        }

    def test_exact_component_union_publishes_complete_planning_only_coverage(self):
        seed_a, occurrence_a = self.occurrence("hrs_a", "rac_a", "held-a")
        seed_b, occurrence_b = self.occurrence("hrs_b", "rac_b", "external-b")
        held_row = self.coverage_row(
            "hrs_a",
            "rac_a",
            "held-a",
            occurrence_a,
            "held_census_reconciliation_approval",
        )
        external_row = self.coverage_row(
            "hrs_b",
            "rac_b",
            "external-b",
            occurrence_b,
            "external_census_occurrence_approval",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(
                self.module,
                "load_stable_runner_ledger",
                return_value=(
                    [seed_a, seed_b],
                    {"root": "/stable", "manifest_sha256": "a" * 64},
                ),
            ), patch.object(
                self.module,
                "_merged_source_identities",
                return_value={("/stable", "a" * 64)},
            ), patch.object(
                self.module,
                "_held_component",
                return_value=(
                    [held_row],
                    {
                        "type": "held_census_reconciliation_approval",
                        "manifest_sha256": "b" * 64,
                    },
                ),
            ), patch.object(
                self.module,
                "_external_component",
                return_value=(
                    [external_row],
                    {
                        "type": "external_census_occurrence_approval",
                        "manifest_sha256": "c" * 64,
                    },
                ),
            ):
                manifest = self.module.build_coverage(
                    stable_runner_ledger_root=root / "stable",
                    approved_stable_runner_manifest_sha256="a" * 64,
                    held_approval_roots=[root / "held"],
                    held_approval_manifest_sha256s=["b" * 64],
                    external_approval_roots=[root / "external"],
                    external_approval_manifest_sha256s=["c" * 64],
                    output_dir=root / "coverage",
                )
            marker = (root / "coverage" / "COMPLETE").read_text().strip()
            self.assertEqual(
                marker,
                self.module.sha256_path(root / "coverage" / "coverage-manifest.json"),
            )
        self.assertTrue(manifest["coverage_complete"])
        self.assertTrue(manifest["planning_eligible"])
        self.assertFalse(manifest["network_execution_authorized"])
        self.assertEqual(manifest["counts"]["covered_occurrences"], 2)

    def test_gap_or_overlap_fails_before_output(self):
        stable_seed, occurrence = self.occurrence("hrs_a", "rac_a", "held-a")
        second_seed, _second_occurrence = self.occurrence(
            "hrs_b", "rac_b", "external-b"
        )
        row = self.coverage_row(
            "hrs_a",
            "rac_a",
            "held-a",
            occurrence,
            "held_census_reconciliation_approval",
        )
        for stable_rows, external_rows in (
            ([stable_seed, second_seed], []),
            ([stable_seed], [dict(row)]),
        ):
            with self.subTest(
                stable_rows=len(stable_rows), external_rows=len(external_rows)
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with patch.object(
                    self.module,
                    "load_stable_runner_ledger",
                    return_value=(
                        stable_rows,
                        {"root": "/stable", "manifest_sha256": "a" * 64},
                    ),
                ), patch.object(
                    self.module,
                    "_merged_source_identities",
                    return_value={("/stable", "a" * 64)},
                ), patch.object(
                    self.module,
                    "_held_component",
                    return_value=(
                        [row],
                        {
                            "type": "held_census_reconciliation_approval",
                            "manifest_sha256": "b" * 64,
                        },
                    ),
                ), patch.object(
                    self.module,
                    "_external_component",
                    return_value=(
                        external_rows,
                        {
                            "type": "external_census_occurrence_approval",
                            "manifest_sha256": "c" * 64,
                        },
                    ),
                ), self.assertRaisesRegex(
                        self.module.ReconciliationCoverageError,
                        "overlap or do not cover",
                    ):
                        self.module.build_coverage(
                            stable_runner_ledger_root=root / "stable",
                            approved_stable_runner_manifest_sha256="a" * 64,
                            held_approval_roots=[root / "held"],
                            held_approval_manifest_sha256s=["b" * 64],
                            external_approval_roots=[root / "external"],
                            external_approval_manifest_sha256s=["c" * 64],
                            output_dir=root / "coverage",
                        )
                self.assertFalse((root / "coverage").exists())

    def test_targeted_duplicate_observation_has_one_owner_and_supporter(self):
        runner = {
            "horse_id": "hrs_shared",
            "horse": "Shared (FR)",
            "position": "1",
            "participant_status": "finished",
        }
        target_race = {
            "race_id": "rac_shared",
            "date": "2026-05-01",
            "region": "FR",
            "pattern": "Grade 3",
            "type": "Flat",
            "race_name": "Prix Shared",
            "course": "Fixture",
            "runners": [dict(runner)],
            "actual_starters": [dict(runner)],
            "excluded_non_runner_count": 0,
            "source_mode": "targeted_horse_content_pool",
        }
        occurrence_a = self.module._target_occurrence(
            seed_id="target-runner-a",
            run_manifest_sha256="1" * 64,
            target_race=target_race,
            runner=runner,
        )
        occurrence_b = self.module._target_occurrence(
            seed_id="target-runner-b",
            run_manifest_sha256="2" * 64,
            target_race=target_race,
            runner=runner,
        )
        merged_occurrence = self.module._merge_occurrence_observations(
            occurrence_a, occurrence_b
        )
        merged_key = self.module.occurrence_key(
            "hrs_shared", merged_occurrence
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materializations = []
            stable_by_root = {}
            for suffix, seed_id, run_sha, occurrence in (
                ("a", "target-runner-a", "1" * 64, occurrence_a),
                ("b", "target-runner-b", "2" * 64, occurrence_b),
            ):
                material = root / f"material-{suffix}"
                material.mkdir()
                manifest_path = material / "materialization-manifest.json"
                manifest_path.write_text(
                    json.dumps({"component": suffix}) + "\n", encoding="utf-8"
                )
                manifest_sha = hashlib.sha256(
                    manifest_path.read_bytes()
                ).hexdigest()
                stable = root / f"stable-{suffix}"
                stable.mkdir()
                source_materialization = {
                    "path": str(material.resolve()),
                    "manifest_sha256": manifest_sha,
                    "source_targeted_batch_manifest_sha256": "f" * 64,
                }
                (stable / "manifest.json").write_text(
                    json.dumps(
                        {"source_materialization": source_materialization}
                    )
                    + "\n",
                    encoding="utf-8",
                )
                stable_sha = suffix.encode().hex().ljust(64, "0")[:64]
                stable_by_root[str(stable)] = (
                    [{
                        "horse_id": "hrs_shared",
                        "target_occurrences": [occurrence],
                    }],
                    {
                        "root": str(stable),
                        "manifest_sha256": stable_sha,
                        "source_route": None,
                    },
                )
                materializations.append(
                    (material, manifest_sha, seed_id, run_sha, stable, stable_sha)
                )

            def load_stable(path, *, approved_manifest_sha256):
                rows, identity = stable_by_root[str(path)]
                self.assertEqual(
                    approved_manifest_sha256, identity["manifest_sha256"]
                )
                return rows, identity

            results = []
            for material, manifest_sha, seed_id, run_sha, stable, stable_sha in materializations:
                with patch.object(
                    self.module,
                    "_load_materialized_target_races",
                    return_value=(
                        {"source_batch_manifest_sha256": "f" * 64},
                        [(seed_id, run_sha, target_race, None)],
                    ),
                ), patch.object(
                    self.module,
                    "load_stable_runner_ledger",
                    side_effect=load_stable,
                ), patch.object(
                    self.module,
                    "_read_json",
                    return_value={
                        "source_materialization": {
                            "path": str(material.resolve()),
                            "manifest_sha256": manifest_sha,
                            "source_targeted_batch_manifest_sha256": "f" * 64,
                        }
                    },
                ):
                    results.append(
                        self.module._targeted_materialization_component(
                            material,
                            expected_manifest_sha256=manifest_sha,
                            allowed_stable_identities={(str(stable), stable_sha)},
                            merged_occurrences={
                                merged_key: ("hrs_shared", merged_occurrence)
                            },
                        )
                    )

        owner_rows, owner_identity = results[0]
        supporting_rows, supporting_identity = results[1]
        self.assertEqual(len(owner_rows), 1)
        self.assertEqual(owner_rows[0]["occurrence_key"], merged_key)
        self.assertEqual(owner_identity["binding_rows"], 1)
        self.assertEqual(owner_identity["supporting_occurrence_rows"], 0)
        self.assertEqual(supporting_rows, [])
        self.assertEqual(supporting_identity["binding_rows"], 0)
        self.assertEqual(supporting_identity["supporting_occurrence_rows"], 1)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("merge_target_runner_stable_id_ledgers.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("merge_stable_runner_ledgers", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MergeStableRunnerLedgersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def _occurrence(self, race_id: str, seed_id: str, name: str) -> dict:
        return {
            "race_id": race_id,
            "target_race_payload_sha256": "a" * 64,
            "source_targeted_seed_id": seed_id,
            "source_materialized_run_manifest_sha256": hashlib.sha256(
                f"run:{race_id}".encode()
            ).hexdigest(),
            "source_runner_payload_sha256": hashlib.sha256(
                f"runner:{race_id}:{name}".encode()
            ).hexdigest(),
            "source_runner_name": name,
            "source_runner_position": "1",
            "target": {
                "year": 2026,
                "country_region": "united_states",
                "local_date": "2026-07-01",
                "canonical_name_original": seed_id,
                "race_name_aliases": [],
                "racecourse": "Fixture",
                "racecourse_aliases": [],
                "grade_text": "G3",
                "discipline": "flat",
            },
        }

    def _ledger(
        self, root: Path, name: str, batch_sha: str, rows: list[dict]
    ) -> tuple[Path, str]:
        artifact = root / name
        artifact.mkdir()
        normalized = [
            {
                "schema_version": "targeted-runner-stable-id-seed.v1",
                "seed_id": row["seed_id"],
                "horse_id": row["horse_id"],
                "source_names": row["source_names"],
                "source_targeted_batch_manifest_sha256": batch_sha,
                "target_occurrences": row["target_occurrences"],
            }
            for row in rows
        ]
        ledger = artifact / "target-runner-stable-id-seeds.v1.jsonl"
        ledger.write_text(
            "".join(canonical(row) + "\n" for row in normalized), encoding="utf-8"
        )
        manifest = {
            "schema_version": "target-runner-stable-id-ledger.v1",
            "status": "complete",
            "network_requests": 0,
            "database_writes": 0,
            "source_target_occurrence_count": sum(
                len(row["target_occurrences"]) for row in normalized
            ),
            "unique_target_race_count": len(
                {
                    occurrence["race_id"]
                    for row in normalized
                    for occurrence in row["target_occurrences"]
                }
            ),
            "seed_ledger": {
                "path": ledger.name,
                "sha256": sha(ledger),
                "size": ledger.stat().st_size,
                "rows": len(normalized),
            },
        }
        manifest_path = artifact / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        manifest_sha = sha(manifest_path)
        (artifact / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
        return artifact, manifest_sha

    def test_merges_same_horse_across_batches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, first_sha = self._ledger(
                root,
                "first",
                "1" * 64,
                [{
                    "seed_id": "one",
                    "horse_id": "hrs_alpha",
                    "source_names": ["Alpha"],
                    "target_occurrences": [self._occurrence("rac_one", "one", "Alpha")],
                }],
            )
            second, second_sha = self._ledger(
                root,
                "second",
                "2" * 64,
                [{
                    "seed_id": "two",
                    "horse_id": "hrs_alpha",
                    "source_names": ["Alpha (USA)"],
                    "target_occurrences": [self._occurrence("rac_two", "two", "Alpha")],
                }],
            )
            output = root / "merged"
            manifest = self.module.merge_stable_runner_ledgers(
                source_roots=[first, second],
                approved_manifest_sha256s=[first_sha, second_sha],
                output_dir=output,
            )
            rows, identity = sys.modules[
                "prepare_held_census_tra_reconciliation"
            ].load_stable_runner_ledger(
                output,
                approved_manifest_sha256=sha(output / "manifest.json"),
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["target_occurrences"]), 2)
        self.assertEqual(manifest["cross_batch_duplicate_horse_count"], 1)
        self.assertEqual(identity["schema_version"], "target-runner-stable-id-ledger.v2")

    def test_same_physical_race_with_distinct_targets_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, first_sha = self._ledger(
                root,
                "first",
                "1" * 64,
                [{
                    "seed_id": "horse-one",
                    "horse_id": "hrs_alpha",
                    "source_names": ["Alpha"],
                    "target_occurrences": [
                        self._occurrence("rac_same", "delaware-oaks", "Alpha"),
                        self._occurrence("rac_same", "delaware", "Alpha"),
                    ],
                }],
            )
            second, second_sha = self._ledger(
                root,
                "second",
                "2" * 64,
                [{
                    "seed_id": "horse-two",
                    "horse_id": "hrs_beta",
                    "source_names": ["Beta"],
                    "target_occurrences": [self._occurrence("rac_two", "two", "Beta")],
                }],
            )
            manifest = self.module.merge_stable_runner_ledgers(
                source_roots=[first, second],
                approved_manifest_sha256s=[first_sha, second_sha],
                output_dir=root / "merged",
            )
        self.assertEqual(manifest["unique_target_race_count"], 3)
        self.assertEqual(manifest["unique_physical_race_count"], 2)


if __name__ == "__main__":
    unittest.main()

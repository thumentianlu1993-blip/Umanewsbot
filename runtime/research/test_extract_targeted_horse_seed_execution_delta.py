from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("extract_targeted_horse_seed_execution_delta.py")
SPEC = importlib.util.spec_from_file_location("extract_seed_execution_delta", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ExtractTargetedHorseSeedExecutionDeltaTests(unittest.TestCase):
    def _seed(self, seed_id: str, target_key: str, occurrence: str = "") -> dict:
        row = {
            "schema_version": "targeted-horse-seed.v2",
            "seed_id": seed_id,
            "name": seed_id,
            "target": {"target_key": target_key, "country_region": "united_states", "year": 2024},
        }
        if occurrence:
            row["source_occurrence_id"] = occurrence
        return row

    def _artifact(self, root: Path, name: str, rows: list[dict]) -> tuple[Path, str]:
        artifact = root / name
        artifact.mkdir()
        ledger = artifact / "targeted-horse-seeds.jsonl"
        ledger.write_text("".join(MODULE.canonical_json(row) + "\n" for row in rows))
        identity = {
            "path": ledger.name,
            "rows": len(rows),
            "sha256": MODULE.sha256_path(ledger),
            "size": ledger.stat().st_size,
        }
        manifest = {
            "schema_version": "targeted-horse-seed-ledger.v1",
            "status": "complete",
            "completion_marker": "COMPLETE",
            "database_writes": 0,
            "network_requests": 0,
            "seed_count": len(rows),
            "seed_ledger": identity,
        }
        manifest_path = artifact / "seed-ledger-manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
        manifest_sha = MODULE.sha256_path(manifest_path)
        (artifact / "COMPLETE").write_text(manifest_sha + "\n")
        return artifact, manifest_sha

    def test_skips_singleton_target_and_keeps_new_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prior = self._artifact(root, "prior", [self._seed("old", "target-a")])
            candidate = self._artifact(
                root,
                "candidate",
                [self._seed("replacement", "target-a"), self._seed("new", "target-b")],
            )
            manifest = MODULE.extract(
                candidates=[candidate],
                already_scheduled=[prior],
                output_dir=root / "delta",
            )
            self.assertEqual(manifest["seed_count"], 1)
            self.assertEqual(manifest["counts"]["skipped_existing_occurrences"], 1)
            row = json.loads((root / "delta" / "targeted-horse-seeds.jsonl").read_text())
            self.assertEqual(row["seed_id"], "new")

    def test_conserves_new_split_division_by_occurrence_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prior = self._artifact(
                root, "prior", [self._seed("old-a", "split", "division-a")]
            )
            candidate = self._artifact(
                root,
                "candidate",
                [
                    self._seed("new-a", "split", "division-a"),
                    self._seed("new-b", "split", "division-b"),
                ],
            )
            manifest = MODULE.extract(
                candidates=[candidate],
                already_scheduled=[prior],
                output_dir=root / "delta",
            )
            self.assertEqual(manifest["seed_count"], 1)
            row = json.loads((root / "delta" / "targeted-horse-seeds.jsonl").read_text())
            self.assertEqual(row["source_occurrence_id"], "division-b")

    def test_rejects_unprovable_multi_occurrence_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prior = self._artifact(root, "prior", [self._seed("old", "split")])
            candidate = self._artifact(
                root,
                "candidate",
                [self._seed("a", "split", "a"), self._seed("b", "split", "b")],
            )
            with self.assertRaisesRegex(ValueError, "cannot be proven"):
                MODULE.extract(
                    candidates=[candidate],
                    already_scheduled=[prior],
                    output_dir=root / "delta",
                )


if __name__ == "__main__":
    unittest.main()

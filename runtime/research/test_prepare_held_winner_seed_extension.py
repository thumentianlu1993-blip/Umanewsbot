#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_held_winner_seed_extension.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("held_winner_seed_extension", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class HeldWinnerSeedExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def target(self, key="france:2026:france-test:flat"):
        return {
            "target_key": key,
            "year": 2026,
            "country_region": "france",
            "discipline": "flat",
            "grade_text": "G1",
            "canonical_name_original": "Prix Test",
            "original_name": "Test",
            "racecourse": "Longchamp",
        }

    def occurrence(self, root: Path, key="france:2026:france-test:flat"):
        source = root / "source.pdf"
        source.write_bytes(b"official result fixture")
        return {
            "target_key": key,
            "country_region": "france",
            "discipline": "flat",
            "normalized_grade": "G1",
            "local_date": "2026-01-02",
            "race_name": "PRIX TEST",
            "racecourse": "Longchamp",
            "anchor_horse_name": "Winner IRE",
            "starters": [
                {"horse_name": "Winner IRE", "finish_position": 1},
                {"horse_name": "Second", "finish_position": 2},
            ],
            "source_evidence": {
                "source_authority": "organizer_official",
                "source_provider": "france_galop",
                "source_url": "https://www.france-galop.com/result.pdf",
                "cache_path": str(source),
                "sha256": self.module.sha256_path(source),
                "size": source.stat().st_size,
            },
        }

    def test_new_official_winner_is_prepared_but_not_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = self.target()
            output = root / "output"
            manifest = self.module.build_proposal(
                targets={target["target_key"]: target},
                target_identity={"manifest_sha256": "a" * 64, "ledger_sha256": "b" * 64},
                occurrences=[self.occurrence(root)],
                held_identity={"manifest_sha256": "c" * 64},
                existing_seeds={},
                existing_seed_identity={"manifest_sha256": "d" * 64},
                output_dir=output,
            )
            candidate = json.loads((output / "new-seed-candidates.jsonl").read_text())
        self.assertEqual(manifest["status"], "PREPARED_NOT_EXECUTABLE")
        self.assertFalse(manifest["execution_ready"])
        self.assertEqual(manifest["counts"]["new_organizer_official_candidates"], 1)
        self.assertEqual(manifest["non_executable_request_projection"]["total_request_ceiling"], 16)
        self.assertEqual(manifest["non_executable_request_projection"]["projected_batches"], 1)
        self.assertEqual(candidate["seed"]["name"], "Winner")
        self.assertEqual(candidate["seed"]["country_suffix"], "IRE")

    def test_existing_complete_seed_is_reused_byte_for_fact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = self.target()
            occurrence = self.occurrence(root)
            seed_id = self.module._target_seed_id(target["target_key"])
            seed = {
                "schema_version": "targeted-horse-seed.v1",
                "seed_id": seed_id,
                "name": "Winner",
                "expected_finish_position": "1",
                "target": {
                    "country_region": "france",
                    "local_date": "2026-01-02",
                    "grade_text": "G1",
                    "discipline": "flat",
                    "edition_year": 2026,
                },
            }
            output = root / "output"
            manifest = self.module.build_proposal(
                targets={target["target_key"]: target},
                target_identity={},
                occurrences=[occurrence],
                held_identity={},
                existing_seeds={seed_id: seed},
                existing_seed_identity={},
                output_dir=output,
            )
            combined = json.loads((output / "all-held-targeted-horse-seeds.jsonl").read_text())
        self.assertEqual(manifest["counts"]["reused_complete_seeds"], 1)
        self.assertEqual(
            manifest["counts"]["replacement_organizer_official_candidates"], 0
        )
        self.assertEqual(combined, seed)

    def test_existing_seed_with_wrong_winner_is_replaced_from_official_occurrence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = self.target()
            occurrence = self.occurrence(root)
            seed_id = self.module._target_seed_id(target["target_key"])
            stale = {
                "schema_version": "targeted-horse-seed.v1",
                "seed_id": seed_id,
                "name": "Wrong Winner",
                "expected_finish_position": "1",
                "target": {
                    "country_region": "france",
                    "local_date": "2026-01-02",
                    "grade_text": "G1",
                    "discipline": "flat",
                    "edition_year": 2026,
                },
            }
            output = root / "output"
            manifest = self.module.build_proposal(
                targets={target["target_key"]: target},
                target_identity={},
                occurrences=[occurrence],
                held_identity={},
                existing_seeds={seed_id: stale},
                existing_seed_identity={},
                output_dir=output,
            )
            candidate = json.loads(
                (output / "new-seed-candidates.jsonl").read_text()
            )
            combined = json.loads(
                (output / "all-held-targeted-horse-seeds.jsonl").read_text()
            )
            binding = json.loads(
                (output / "existing-seed-bindings.jsonl").read_text()
            )
        self.assertEqual(manifest["counts"]["reused_complete_seeds"], 0)
        self.assertEqual(
            manifest["counts"]["replacement_organizer_official_candidates"], 1
        )
        self.assertEqual(manifest["counts"]["review_candidates_total"], 1)
        self.assertEqual(candidate["disposition"], "replace_conflicting_existing_seed")
        self.assertEqual(candidate["replaced_winner_name"], "Wrong Winner")
        self.assertEqual(candidate["authoritative_winner_name"], "Winner IRE")
        self.assertEqual(combined["name"], "Winner")
        self.assertEqual(binding["disposition"], "replace_conflicting_existing_seed")
        self.assertEqual(binding["replacement_seed_id"], combined["seed_id"])

    def test_existing_seed_winner_conflict_requires_organizer_official_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = self.target()
            occurrence = self.occurrence(root)
            occurrence["source_evidence"]["source_authority"] = "human_reviewed_reference"
            seed_id = self.module._target_seed_id(target["target_key"])
            stale = {
                "schema_version": "targeted-horse-seed.v1",
                "seed_id": seed_id,
                "name": "Wrong Winner",
                "expected_finish_position": "1",
                "target": {
                    "country_region": "france",
                    "local_date": "2026-01-02",
                    "grade_text": "G1",
                    "discipline": "flat",
                    "edition_year": 2026,
                },
            }
            with self.assertRaisesRegex(
                ValueError, "not uniquely organizer-official"
            ):
                self.module.build_proposal(
                    targets={target["target_key"]: target},
                    target_identity={},
                    occurrences=[occurrence],
                    held_identity={},
                    existing_seeds={seed_id: stale},
                    existing_seed_identity={},
                    output_dir=root / "output",
                )

    def test_unused_existing_seed_fails_conservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = self.target()
            with self.assertRaisesRegex(ValueError, "strict subset"):
                self.module.build_proposal(
                    targets={target["target_key"]: target},
                    target_identity={},
                    occurrences=[self.occurrence(root)],
                    held_identity={},
                    existing_seeds={"unrelated": {"seed_id": "unrelated"}},
                    existing_seed_identity={},
                    output_dir=root / "output",
                )

    def test_new_candidate_requires_unique_official_winner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            occurrence = self.occurrence(root)
            occurrence["starters"].append({"horse_name": "Other", "finish_position": 1})
            with self.assertRaisesRegex(ValueError, "uniquely organizer-official"):
                self.module._new_seed(occurrence["target_key"], self.target(), occurrence)

    def test_source_payload_drift_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            occurrence = self.occurrence(root)
            Path(occurrence["source_evidence"]["cache_path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "source evidence drift"):
                self.module._new_seed(occurrence["target_key"], self.target(), occurrence)


if __name__ == "__main__":
    unittest.main()

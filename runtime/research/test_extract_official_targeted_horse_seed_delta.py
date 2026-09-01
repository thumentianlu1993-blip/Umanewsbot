from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("extract_official_targeted_horse_seed_delta.py")
SPEC = importlib.util.spec_from_file_location("extract_official_seed_delta", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class OfficialTargetedHorseSeedDeltaTests(unittest.TestCase):
    def seed(self, seed_id: str, *, authority: str, target_key: str) -> dict:
        return {
            "schema_version": "targeted-horse-seed.v2",
            "seed_id": seed_id,
            "name": seed_id,
            "source_authority": authority,
            "target": {"target_key": target_key, "country_region": "france"},
        }

    def test_extracts_only_new_official_seeds(self):
        base = self.seed("base", authority="encyclopedic_reference", target_key="base-target")
        official = self.seed(
            "official", authority="organizer_official", target_key="official-target"
        )
        merged_manifest = {
            "base_seed_artifact": {
                "root": "/base",
                "manifest_sha256": "b" * 64,
                "seed_ledger_sha256": "c" * 64,
                "semantic_gaps_sha256": "d" * 64,
            },
            "counts": {"supplemental_organizer_official_seeds": 1},
            "target_manifest_sha256": "e" * 64,
            "target_ledger_sha256": "f" * 64,
        }
        merged_identity = {
            "root": "/merged",
            "manifest_sha256": "a" * 64,
            "seed_ledger_sha256": "1" * 64,
            "semantic_gaps_sha256": "2" * 64,
        }
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "delta"
            with patch.object(
                MODULE,
                "load_base",
                side_effect=[
                    (merged_manifest, [base, official], [], merged_identity),
                    ({}, [base], [], merged_manifest["base_seed_artifact"]),
                ],
            ):
                manifest = MODULE.extract(
                    merged_root=Path("/merged"),
                    approved_merged_manifest_sha256="a" * 64,
                    output_dir=output,
                )

            rows = [json.loads(line) for line in (output / "targeted-horse-seeds.jsonl").read_text().splitlines()]
            self.assertEqual([row["seed_id"] for row in rows], ["official"])
            self.assertEqual(manifest["seed_count"], 1)
            self.assertEqual((output / "COMPLETE").read_text().strip(), MODULE.sha256_path(output / "seed-ledger-manifest.json"))

    def test_rejects_non_official_delta(self):
        base = self.seed("base", authority="encyclopedic_reference", target_key="base-target")
        extra = self.seed("extra", authority="encyclopedic_reference", target_key="extra-target")
        merged = {
            "base_seed_artifact": {"root": "/base", "manifest_sha256": "b" * 64},
            "counts": {"supplemental_organizer_official_seeds": 1},
        }
        with TemporaryDirectory() as temporary:
            with patch.object(
                MODULE,
                "load_base",
                side_effect=[
                    (merged, [base, extra], [], {}),
                    ({}, [base], [], merged["base_seed_artifact"]),
                ],
            ):
                with self.assertRaisesRegex(ValueError, "organizer-official"):
                    MODULE.extract(
                        merged_root=Path("/merged"),
                        approved_merged_manifest_sha256="a" * 64,
                        output_dir=Path(temporary) / "delta",
                    )


if __name__ == "__main__":
    unittest.main()

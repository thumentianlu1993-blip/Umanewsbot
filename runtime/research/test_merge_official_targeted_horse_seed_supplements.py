from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("merge_official_targeted_horse_seed_supplements.py")
SPEC = importlib.util.spec_from_file_location("merge_official_seed_supplements", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> dict:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    return {
        "path": path.name,
        "rows": len(rows),
        "sha256": digest(path),
        "size": path.stat().st_size,
    }


class OfficialSeedSupplementTests(unittest.TestCase):
    def _base(self, root: Path) -> str:
        seeds = [
            {
                "schema_version": "targeted-horse-seed.v2",
                "seed_id": "existing",
                "name": "Known",
                "source_authority": "human_reviewed_reference",
                "target": {
                    "target_key": "france:2021:known:flat",
                    "country_region": "france",
                    "edition_year": 2021,
                },
            }
        ]
        gaps = [
            {
                "schema_version": "graded-winner-anchor-gap.v1",
                "target_key": "france:2021:missing:flat",
                "series_key": "france-missing",
                "country_region": "france",
                "year": 2021,
                "reason": "winner_anchor_not_found",
            }
        ]
        seed_identity = write_jsonl(root / "targeted-horse-seeds.jsonl", seeds)
        gap_identity = write_jsonl(root / "semantic-gaps.jsonl", gaps)
        manifest = {
            "artifact_schema_version": "graded-winner-targeted-seed-artifact.v1",
            "schema_version": "targeted-horse-seed-ledger.v1",
            "status": "complete",
            "completion_marker": "COMPLETE",
            "coverage_status": "complete_with_gaps",
            "database_writes": 0,
            "network_requests": 0,
            "seed_count": 1,
            "counts": {
                "by_region": {"france": 1},
                "by_source": {"frozen_history": 1},
                "covered_target_occurrences": 1,
                "physical_winner_seeds": 1,
                "semantic_gaps": 1,
                "target_occurrences": 2,
            },
            "outputs": {
                "targeted-horse-seeds.jsonl": seed_identity,
                "semantic-gaps.jsonl": gap_identity,
            },
            "seed_ledger": seed_identity,
        }
        manifest_path = root / "seed-ledger-manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        manifest_sha = digest(manifest_path)
        (root / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
        return manifest_sha

    def _audit(self, root: Path, *, target_key: str = "france:2021:missing:flat") -> str:
        rows = [
            {
                "schema_version": "targeted-horse-seed.v2",
                "seed_id": "official",
                "name": "Official Winner",
                "expected_finish_position": "1",
                "source_authority": "organizer_official",
                "source_url": "https://www.france-galop.com/result.pdf",
                "source_payload_sha256": "a" * 64,
                "source_occurrence_id": "france:2021-01-01:france_galop:1:1",
                "allow_profile_only_if_target_missing": True,
                "target": {
                    "target_key": target_key,
                    "country_region": "france",
                    "edition_year": 2021,
                },
            }
        ]
        identity = write_jsonl(root / "targeted-horse-seed-proposals.jsonl", rows)
        identity["runnable"] = False
        identity["reason"] = "reference only"
        manifest = {
            "schema_version": "france-galop-bulletin-occurrence-audit.v1",
            "status": "reference_only_target_review_required",
            "completion_marker": "AUDITED_REFERENCE_ONLY",
            "approval": False,
            "database_writes": 0,
            "racing_api_requests": 0,
            "targeted_seed_proposals": identity,
            "source_proposal": {"manifest_sha256": "b" * 64},
        }
        manifest_path = root / "audit-manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        manifest_sha = digest(manifest_path)
        (root / "AUDITED_REFERENCE_ONLY").write_text(manifest_sha + "\n", encoding="ascii")
        return manifest_sha

    def test_merges_only_exact_gap_and_conserves_target_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            base = parent / "base"
            audit = parent / "audit"
            base.mkdir()
            audit.mkdir()
            base_sha = self._base(base)
            audit_sha = self._audit(audit)
            output = parent / "output"

            manifest = MODULE.merge(
                base_root=base,
                approved_base_manifest_sha256=base_sha,
                audits=[(audit, audit_sha)],
                output_dir=output,
            )

            self.assertEqual(manifest["coverage_status"], "complete")
            self.assertEqual(manifest["counts"]["covered_target_occurrences"], 2)
            self.assertEqual(manifest["counts"]["semantic_gaps"], 0)
            self.assertEqual(manifest["seed_count"], 2)
            self.assertEqual((output / "semantic-gaps.jsonl").read_text(), "")
            self.assertEqual(
                (output / "COMPLETE").read_text().strip(),
                digest(output / "seed-ledger-manifest.json"),
            )

    def test_rejects_audit_seed_not_bound_to_a_base_gap(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            base = parent / "base"
            audit = parent / "audit"
            base.mkdir()
            audit.mkdir()
            base_sha = self._base(base)
            audit_sha = self._audit(audit, target_key="france:2021:other:flat")

            with self.assertRaisesRegex(ValueError, "do not resolve"):
                MODULE.merge(
                    base_root=base,
                    approved_base_manifest_sha256=base_sha,
                    audits=[(audit, audit_sha)],
                    output_dir=parent / "output",
                )


if __name__ == "__main__":
    unittest.main()

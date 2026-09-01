from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_hri_unmatched_official_targeted_seeds.py")
SPEC = importlib.util.spec_from_file_location("prepare_hri_unmatched_official_seeds", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
prepare = MODULE.prepare
sha256_path = MODULE.sha256_path


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


class PrepareHriUnmatchedOfficialTargetedSeedsTests(unittest.TestCase):
    def _source(self, root: Path) -> tuple[Path, str, Path, str]:
        proposal = root / "proposal"
        audit = root / "audit"
        proposal.mkdir()
        audit.mkdir()
        row = {
            "schema_version": "hri-graded-result-unmatched.v1",
            "edition_year": 2024,
            "local_date": "2024-04-01",
            "race_name": "The Example Novice Hurdle (Grade 2)",
            "normalized_grade": "G2",
            "racecourse": "Fairyhouse",
            "result_url": "https://www.hri.ie/results/race-result/?date=2024-04-01&race=1&venue=FH",
            "winner": {"finish_position": 1, "horse_name": "Test Winner"},
            "source_evidence": {
                "source_url": "https://www.hri.ie/results?date=2024-04-01",
                "sha256": hashlib.sha256(b"official page").hexdigest(),
            },
        }
        unmatched = proposal / "unmatched.jsonl"
        unmatched.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
        proposal_manifest = {
            "schema_version": "hri-graded-winner-candidate-proposal.v1",
            "status": "PROPOSED_NOT_APPROVED",
            "approval": False,
            "database_writes": 0,
            "racing_api_requests": 0,
            "counts": {
                "official_graded_results": 3,
                "matched_targets": 2,
                "unmatched_official_results": 1,
            },
            "outputs": {
                "unmatched": {
                    "path": unmatched.name,
                    "rows": 1,
                    "sha256": sha256_path(unmatched),
                    "size": unmatched.stat().st_size,
                }
            },
            "target_artifact": {
                "manifest_sha256": hashlib.sha256(b"target manifest").hexdigest(),
                "ledger_sha256": hashlib.sha256(b"target ledger").hexdigest(),
            },
        }
        proposal_path = proposal / "proposal-manifest.json"
        _write(proposal_path, proposal_manifest)
        proposal_sha = sha256_path(proposal_path)
        (proposal / "PREPARED").write_text(proposal_sha + "\n", encoding="ascii")
        audit_manifest = {
            "schema_version": "hri-graded-winner-candidate-audit.v1",
            "status": "reference_only_target_review_required",
            "approval": False,
            "database_writes": 0,
            "racing_api_requests": 0,
            "counts": {"unmatched_official_results": 1},
            "source_proposal": {
                "root": str(proposal.resolve()),
                "manifest_sha256": proposal_sha,
            },
        }
        audit_path = audit / "audit-manifest.json"
        _write(audit_path, audit_manifest)
        audit_sha = sha256_path(audit_path)
        (audit / "AUDITED_REFERENCE_ONLY").write_text(audit_sha + "\n", encoding="ascii")
        return proposal, proposal_sha, audit, audit_sha

    def test_builds_one_direct_official_occurrence_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal, proposal_sha, audit, audit_sha = self._source(root)
            output = root / "output"
            manifest = prepare(
                proposal_root=proposal,
                approved_proposal_manifest_sha256=proposal_sha,
                audit_root=audit,
                approved_audit_manifest_sha256=audit_sha,
                output_dir=output,
            )
            self.assertEqual(manifest["counts"]["official_graded_results"], 3)
            self.assertEqual(manifest["counts"]["direct_official_occurrence_seeds"], 1)
            self.assertEqual(manifest["counts"]["unaccounted_official_results"], 0)
            seed = json.loads((output / "targeted-horse-seeds.jsonl").read_text())
            self.assertEqual(seed["name"], "Test Winner")
            self.assertEqual(seed["target"]["discipline"], "jumps")
            self.assertEqual(seed["target"]["local_date"], "2024-04-01")
            self.assertEqual(seed["target"]["grade_text"], "G2")
            self.assertTrue(seed["target"]["allow_unique_structured_name_mismatch"])
            self.assertEqual(
                (output / "COMPLETE").read_text().strip(),
                sha256_path(output / "seed-ledger-manifest.json"),
            )

    def test_rejects_audit_binding_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal, proposal_sha, audit, audit_sha = self._source(root)
            audit_manifest = json.loads((audit / "audit-manifest.json").read_text())
            audit_manifest["source_proposal"]["manifest_sha256"] = "0" * 64
            _write(audit / "audit-manifest.json", audit_manifest)
            drift_sha = sha256_path(audit / "audit-manifest.json")
            (audit / "AUDITED_REFERENCE_ONLY").write_text(drift_sha + "\n")
            with self.assertRaisesRegex(ValueError, "binding drift"):
                prepare(
                    proposal_root=proposal,
                    approved_proposal_manifest_sha256=proposal_sha,
                    audit_root=audit,
                    approved_audit_manifest_sha256=drift_sha,
                    output_dir=root / "output",
                )

    def test_rejects_duplicate_official_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal, _proposal_sha, audit, _audit_sha = self._source(root)
            unmatched = proposal / "unmatched.jsonl"
            body = unmatched.read_text()
            unmatched.write_text(body + body, encoding="utf-8")
            manifest = json.loads((proposal / "proposal-manifest.json").read_text())
            manifest["outputs"]["unmatched"].update(
                rows=2, sha256=sha256_path(unmatched), size=unmatched.stat().st_size
            )
            manifest["counts"].update(
                official_graded_results=4, matched_targets=2, unmatched_official_results=2
            )
            _write(proposal / "proposal-manifest.json", manifest)
            proposal_sha = sha256_path(proposal / "proposal-manifest.json")
            (proposal / "PREPARED").write_text(proposal_sha + "\n")
            audit_manifest = json.loads((audit / "audit-manifest.json").read_text())
            audit_manifest["source_proposal"]["manifest_sha256"] = proposal_sha
            audit_manifest["counts"]["unmatched_official_results"] = 2
            _write(audit / "audit-manifest.json", audit_manifest)
            audit_sha = sha256_path(audit / "audit-manifest.json")
            (audit / "AUDITED_REFERENCE_ONLY").write_text(audit_sha + "\n")
            with self.assertRaisesRegex(ValueError, "duplicated"):
                prepare(
                    proposal_root=proposal,
                    approved_proposal_manifest_sha256=proposal_sha,
                    audit_root=audit,
                    approved_audit_manifest_sha256=audit_sha,
                    output_dir=root / "output",
                )


if __name__ == "__main__":
    unittest.main()

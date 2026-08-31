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


SCRIPT = Path(__file__).with_name("publish_held_census_tra_reconciliation_approval.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("publish_held_census_tra_reconciliation", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class PublishHeldCensusTraReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def proposal(self, root: Path, *, with_gap: bool = False):
        proposal = root / "proposal"
        proposal.mkdir()
        binding = {
            "schema_version": "held-starter-tra-binding-candidate.v1",
            "target_key": "france:2026:france-test:flat",
            "starter_occurrence_key": "slot-one",
            "tra_horse_id": "hrs_one",
            "binding_status": "unique_occurrence_name_candidate_requires_review",
        }
        summary = {
            "schema_version": "held-starter-tra-reconciliation-summary.v1",
            "target_key": "france:2026:france-test:flat",
            "expected_actual_starters": 1,
            "tra_actual_starters": 1 if not with_gap else 0,
            "unique_binding_candidates": 1 if not with_gap else 0,
            "unmatched_or_ambiguous_source_slots": 0 if not with_gap else 1,
            "unmatched_or_ambiguous_tra_runners": 0,
            "count_conserved": not with_gap,
            "reconciliation_complete": False,
        }
        review = [] if not with_gap else [{"schema_version": "held-starter-tra-reconciliation-review.v1"}]
        members = {
            "binding-candidates.jsonl": [] if with_gap else [binding],
            "review-items.jsonl": review,
            "target-summaries.jsonl": [summary],
        }
        outputs = {}
        for filename, rows in members.items():
            body = "".join(canonical(row) + "\n" for row in rows).encode()
            path = proposal / filename
            path.write_bytes(body)
            outputs[filename] = {
                "path": filename,
                "rows": len(rows),
                "size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        counts = {
            "targets": 1,
            "expected_actual_starter_slots": 1,
            "tra_actual_starter_occurrences": 1 if not with_gap else 0,
            "unique_binding_candidates": 1 if not with_gap else 0,
            "review_items": len(review),
            "targets_with_count_mismatch": 0 if not with_gap else 1,
            "source_slots_unmatched_or_ambiguous": 0 if not with_gap else 1,
            "tra_runners_unmatched_or_ambiguous": 0,
        }
        manifest = {
            "schema_version": "held-census-tra-reconciliation-proposal.v1",
            "status": "PREPARED_NOT_EXECUTABLE",
            "execution_ready": False,
            "approval": False,
            "network_requests": 0,
            "database_writes": 0,
            "completion_marker": "PREPARED",
            "census": {},
            "held_seed_proposal": {},
            "approved_held_seed_artifact": {},
            "stable_runner_ledger": {},
            "scope": {
                "mode": "full_census",
                "source_targeted_seed_ids": ["seed-one"],
                "target_keys": ["france:2026:france-test:flat"],
            },
            "counts": counts,
            "outputs": outputs,
        }
        manifest_path = proposal / "proposal-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (proposal / "PREPARED").write_text(manifest_sha + "\n", encoding="ascii")
        return proposal, manifest_sha, outputs

    def decision(self, root: Path, manifest_sha: str, outputs: dict, **overrides):
        decision = {
            "schema_version": "held-census-tra-reconciliation-approval-decision.v1",
            "decision": "approve",
            "proposal_manifest_sha256": manifest_sha,
            "approved_outputs": {name: value["sha256"] for name, value in outputs.items()},
            "reviewed_by": "independent-reviewer",
            "reviewed_at": "2026-08-30T12:00:00+08:00",
            "decision_source_reference": "review://held-census-tra/1",
            "reason": "all target counts and slot bindings independently reviewed",
            "independence_acknowledgement": "REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR",
            **overrides,
        }
        path = root / "decision.json"
        path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_publishes_only_exact_independently_approved_zero_gap_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal, manifest_sha, outputs = self.proposal(root)
            decision, decision_sha = self.decision(root, manifest_sha, outputs)
            with patch.object(self.module, "_replay_proposal") as replay:
                manifest = self.module.publish_approval(
                    proposal_root=proposal,
                    approved_proposal_manifest_sha256=manifest_sha,
                    decision_file=decision,
                    approved_decision_sha256=decision_sha,
                    output_dir=root / "approved",
                )
            replay.assert_called_once()
            approved = root / "approved"
            marker = (approved / "COMPLETE").read_text().strip()
            self.assertEqual(marker, self.module.sha256_path(approved / "approval-manifest.json"))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["counts"]["approved_starter_bindings"], 1)
        self.assertEqual(manifest["counts"]["unique_tra_horse_ids"], 1)

    def test_nonzero_gap_cannot_be_approved_even_with_an_approve_decision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal, manifest_sha, outputs = self.proposal(root, with_gap=True)
            decision, decision_sha = self.decision(root, manifest_sha, outputs)
            with patch.object(self.module, "_replay_proposal"), self.assertRaisesRegex(
                ValueError, "not zero-gap"
            ):
                self.module.publish_approval(
                    proposal_root=proposal,
                    approved_proposal_manifest_sha256=manifest_sha,
                    decision_file=decision,
                    approved_decision_sha256=decision_sha,
                    output_dir=root / "approved",
                )
            self.assertFalse((root / "approved").exists())

    def test_self_approval_or_output_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal, manifest_sha, outputs = self.proposal(root)
            decision, decision_sha = self.decision(
                root,
                manifest_sha,
                outputs,
                independence_acknowledgement="IMPLEMENTER_APPROVES_OWN_OUTPUT",
            )
            with patch.object(self.module, "_replay_proposal"), self.assertRaisesRegex(
                ValueError, "does not bind exact"
            ):
                self.module.publish_approval(
                    proposal_root=proposal,
                    approved_proposal_manifest_sha256=manifest_sha,
                    decision_file=decision,
                    approved_decision_sha256=decision_sha,
                    output_dir=root / "approved-one",
                )
            drifted = {name: dict(value) for name, value in outputs.items()}
            drifted["binding-candidates.jsonl"]["sha256"] = "f" * 64
            decision_two, decision_two_sha = self.decision(root, manifest_sha, drifted)
            with patch.object(self.module, "_replay_proposal"), self.assertRaisesRegex(
                ValueError, "does not bind exact"
            ):
                self.module.publish_approval(
                    proposal_root=proposal,
                    approved_proposal_manifest_sha256=manifest_sha,
                    decision_file=decision_two,
                    approved_decision_sha256=decision_two_sha,
                    output_dir=root / "approved-two",
                )

    def test_replay_failure_prevents_decision_consumption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal, manifest_sha, outputs = self.proposal(root)
            decision, decision_sha = self.decision(root, manifest_sha, outputs)
            with patch.object(
                self.module,
                "_replay_proposal",
                side_effect=ValueError("reconciliation output no longer replays"),
            ), self.assertRaisesRegex(ValueError, "no longer replays"):
                self.module.publish_approval(
                    proposal_root=proposal,
                    approved_proposal_manifest_sha256=manifest_sha,
                    decision_file=decision,
                    approved_decision_sha256=decision_sha,
                    output_dir=root / "approved",
                )


if __name__ == "__main__":
    unittest.main()

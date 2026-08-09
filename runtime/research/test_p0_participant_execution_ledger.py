from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from runtime.research.p0_participant_execution_ledger import (
    ParticipantExecutionLedgerError,
    update_execution_ledger,
)


class ParticipantExecutionLedgerTests(unittest.TestCase):
    def test_retry_preserves_all_blocked_attempt_and_reopens_same_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / "index.json"
            index.write_text(
                json.dumps(
                    {
                        "artifact_type": "p0_horse_participant_completion_batch_plan",
                        "batch_count": 1,
                        "candidate_count": 2,
                        "batches": [
                            {"path": "batch-1", "ordinal": 1, "row_count": 2}
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            index_sha = hashlib.sha256(index.read_bytes()).hexdigest()
            ledger = root / "ledger.json"
            review_sha = "a" * 64
            completion = root / "completion.json"
            completion.write_text(
                json.dumps(
                    {
                        "artifact_type": "p0_horse_completion_batch_manifest",
                        "database_writes": 0,
                        "summary": {
                            "processed_count": 2,
                            "complete_candidate_count": 0,
                            "blocked_count": 2,
                        },
                        "review_manifest_input": {
                            "sha256": review_sha,
                            "batch_contract": {
                                "batch_membership": {
                                    "path": "batch-1",
                                    "ordinal": 1,
                                    "index_sha256": index_sha,
                                }
                            },
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            update_execution_ledger(
                action="claim",
                index_path=index,
                ledger_path=ledger,
                batch_path="batch-1",
                review_manifest_sha256=review_sha,
            )
            update_execution_ledger(
                action="prepared",
                index_path=index,
                ledger_path=ledger,
                batch_path="batch-1",
                review_manifest_sha256=review_sha,
                completion_manifest_path=completion,
            )

            retried = update_execution_ledger(
                action="retry",
                index_path=index,
                ledger_path=ledger,
                batch_path="batch-1",
                review_manifest_sha256=review_sha,
                completion_manifest_path=completion,
                retry_reason="deterministic_blocker_repaired",
            )

            completion_sha = hashlib.sha256(completion.read_bytes()).hexdigest()
            self.assertEqual(retried["active"]["phase"], "claimed")
            self.assertEqual(
                retried["active"]["prepare_attempts"],
                [
                    {
                        "completion_manifest_sha256": completion_sha,
                        "retry_reason": "deterministic_blocker_repaired",
                    }
                ],
            )
            replacement = root / "replacement.json"
            replacement_payload = json.loads(completion.read_text(encoding="utf-8"))
            replacement_payload["summary"].update(
                {"complete_candidate_count": 1, "blocked_count": 1}
            )
            replacement.write_text(
                json.dumps(replacement_payload, sort_keys=True),
                encoding="utf-8",
            )
            prepared_again = update_execution_ledger(
                action="prepared",
                index_path=index,
                ledger_path=ledger,
                batch_path="batch-1",
                review_manifest_sha256=review_sha,
                completion_manifest_path=replacement,
            )
            self.assertEqual(
                prepared_again["active"]["prepare_attempts"],
                retried["active"]["prepare_attempts"],
            )
            with self.assertRaisesRegex(
                ParticipantExecutionLedgerError,
                "retry completion manifest",
            ):
                update_execution_ledger(
                    action="retry",
                    index_path=index,
                    ledger_path=ledger,
                    batch_path="batch-1",
                    review_manifest_sha256=review_sha,
                    completion_manifest_path=replacement,
                    retry_reason="deterministic_blocker_repaired",
                )

    def test_enforces_order_resume_identity_and_completion_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / "index.json"
            index.write_text(
                json.dumps(
                    {
                        "artifact_type": "p0_horse_participant_completion_batch_plan",
                        "batch_count": 2,
                        "candidate_count": 3,
                        "batches": [
                            {"path": "batch-1", "ordinal": 1, "row_count": 2},
                            {"path": "batch-2", "ordinal": 2, "row_count": 1},
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            index_sha = hashlib.sha256(index.read_bytes()).hexdigest()
            ledger = root / "ledger.json"
            review_sha = "a" * 64
            update_execution_ledger(
                action="claim",
                index_path=index,
                ledger_path=ledger,
                batch_path="batch-1",
                review_manifest_sha256=review_sha,
            )
            update_execution_ledger(
                action="claim",
                index_path=index,
                ledger_path=ledger,
                batch_path="batch-1",
                review_manifest_sha256=review_sha,
            )
            with self.assertRaisesRegex(
                ParticipantExecutionLedgerError, "next ordinal"
            ):
                update_execution_ledger(
                    action="claim",
                    index_path=index,
                    ledger_path=ledger,
                    batch_path="batch-2",
                    review_manifest_sha256="b" * 64,
                )
            completion = root / "completion.json"
            completion.write_text(
                json.dumps(
                    {
                        "artifact_type": "p0_horse_completion_batch_manifest",
                        "database_writes": 0,
                        "summary": {"processed_count": 2},
                        "review_manifest_input": {
                            "sha256": review_sha,
                            "batch_contract": {
                                "batch_membership": {
                                    "path": "batch-1",
                                    "ordinal": 1,
                                    "index_sha256": index_sha,
                                }
                            },
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            update_execution_ledger(
                action="prepared",
                index_path=index,
                ledger_path=ledger,
                batch_path="batch-1",
                review_manifest_sha256=review_sha,
                completion_manifest_path=completion,
            )
            with self.assertRaisesRegex(
                ParticipantExecutionLedgerError, "next ordinal"
            ):
                update_execution_ledger(
                    action="claim",
                    index_path=index,
                    ledger_path=ledger,
                    batch_path="batch-2",
                    review_manifest_sha256="b" * 64,
                )
            completion_sha = hashlib.sha256(completion.read_bytes()).hexdigest()

            def write_evidence(name: str, payload: dict) -> tuple[Path, str]:
                path = root / f"{name}.json"
                path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
                return path, hashlib.sha256(path.read_bytes()).hexdigest()

            common = {
                "artifact_type": "p0_horse_participant_execution_evidence.v1",
                "batch_index_sha256": index_sha,
                "batch_path": "batch-1",
                "ordinal": 1,
                "review_manifest_sha256": review_sha,
            }
            release, release_sha = write_evidence(
                "release",
                {
                    **common,
                    "phase": "released",
                    "previous_evidence_sha256": completion_sha,
                    "mapping_snapshot_sha256": "b" * 64,
                    "production_release_manifest_sha256": "c" * 64,
                    "g3_approval_sha256": "d" * 64,
                },
            )
            update_execution_ledger(
                action="released",
                index_path=index,
                ledger_path=ledger,
                batch_path="batch-1",
                review_manifest_sha256=review_sha,
                stage_evidence_path=release,
            )
            apply, apply_sha = write_evidence(
                "apply",
                {
                    **common,
                    "phase": "applied",
                    "previous_evidence_sha256": release_sha,
                    "production_release_manifest_sha256": "c" * 64,
                    "g3_approval_sha256": "d" * 64,
                    "apply_receipt_sha256": "e" * 64,
                    "database_write_count": 2,
                },
            )
            update_execution_ledger(
                action="applied",
                index_path=index,
                ledger_path=ledger,
                batch_path="batch-1",
                review_manifest_sha256=review_sha,
                stage_evidence_path=apply,
            )
            applied_ledger = ledger.read_bytes()
            valid_planned_remaining = {
                "planned_profile_creates": 0,
                "planned_profile_updates": 0,
                "planned_race_record_creates": 0,
                "planned_race_record_updates": 0,
                "planned_module_audits": 0,
            }
            invalid_planned_remaining = {
                "missing_key": {
                    key: value
                    for key, value in valid_planned_remaining.items()
                    if key != "planned_module_audits"
                },
                "extra_key": {**valid_planned_remaining, "unrelated": 0},
                "none_value": {
                    **valid_planned_remaining,
                    "planned_module_audits": None,
                },
                "boolean_value": {
                    **valid_planned_remaining,
                    "planned_module_audits": False,
                },
                "string_value": {
                    **valid_planned_remaining,
                    "planned_module_audits": "0",
                },
            }
            for case, planned_remaining in invalid_planned_remaining.items():
                invalid_ledger = root / f"ledger-{case}.json"
                invalid_ledger.write_bytes(applied_ledger)
                invalid_verifier, _ = write_evidence(
                    f"verifier-{case}",
                    {
                        **common,
                        "phase": "verified",
                        "previous_evidence_sha256": apply_sha,
                        "production_release_manifest_sha256": "c" * 64,
                        "apply_receipt_sha256": "e" * 64,
                        "verifier_receipt_sha256": "f" * 64,
                        "verifier_passed": True,
                        "planned_remaining": planned_remaining,
                    },
                )
                with (
                    self.subTest(case=case),
                    self.assertRaisesRegex(
                        ParticipantExecutionLedgerError,
                        "verified evidence does not bind",
                    ),
                ):
                    update_execution_ledger(
                        action="verified",
                        index_path=index,
                        ledger_path=invalid_ledger,
                        batch_path="batch-1",
                        review_manifest_sha256=review_sha,
                        stage_evidence_path=invalid_verifier,
                    )
            verifier, _ = write_evidence(
                "verifier",
                {
                    **common,
                    "phase": "verified",
                    "previous_evidence_sha256": apply_sha,
                    "production_release_manifest_sha256": "c" * 64,
                    "apply_receipt_sha256": "e" * 64,
                    "verifier_receipt_sha256": "f" * 64,
                    "verifier_passed": True,
                    "planned_remaining": valid_planned_remaining,
                },
            )
            update_execution_ledger(
                action="verified",
                index_path=index,
                ledger_path=ledger,
                batch_path="batch-1",
                review_manifest_sha256=review_sha,
                stage_evidence_path=verifier,
            )
            with self.assertRaisesRegex(
                ParticipantExecutionLedgerError, "next ordinal"
            ):
                update_execution_ledger(
                    action="claim",
                    index_path=index,
                    ledger_path=ledger,
                    batch_path="batch-1",
                    review_manifest_sha256=review_sha,
                )
            with self.assertRaisesRegex(ParticipantExecutionLedgerError, "incomplete"):
                update_execution_ledger(
                    action="verify", index_path=index, ledger_path=ledger
                )


if __name__ == "__main__":
    unittest.main()

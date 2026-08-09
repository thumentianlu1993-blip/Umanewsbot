#!/usr/bin/env python3
"""为 2025 participant P0 批次提供严格顺序、可续跑的本地执行账本。"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class ParticipantExecutionLedgerError(ValueError):
    pass


EXPECTED_PLANNED_REMAINING_KEYS = {
    "planned_profile_creates",
    "planned_profile_updates",
    "planned_race_record_creates",
    "planned_race_record_updates",
    "planned_module_audits",
}


def _read_json(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        data = path.read_bytes()
        payload = json.loads(data)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ParticipantExecutionLedgerError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise ParticipantExecutionLedgerError(f"{label} must be an object")
    return data, payload


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    data = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_index(index_path: Path) -> tuple[str, dict[str, Any]]:
    data, payload = _read_json(index_path, label="batch index")
    batches = payload.get("batches")
    if (
        payload.get("artifact_type") != "p0_horse_participant_completion_batch_plan"
        or not isinstance(batches, list)
        or payload.get("batch_count") != len(batches)
        or payload.get("candidate_count")
        != sum(
            int(row.get("row_count") or 0) for row in batches if isinstance(row, dict)
        )
    ):
        raise ParticipantExecutionLedgerError("batch index identity is invalid")
    return hashlib.sha256(data).hexdigest(), payload


def update_execution_ledger(
    *,
    action: str,
    index_path: str | Path,
    ledger_path: str | Path,
    batch_path: str = "",
    review_manifest_sha256: str = "",
    completion_manifest_path: str | Path | None = None,
    stage_evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    index_sha, index = _load_index(Path(index_path))
    ledger_file = Path(ledger_path)
    lock_file = ledger_file.with_suffix(ledger_file.suffix + ".lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if ledger_file.exists():
            _, ledger = _read_json(ledger_file, label="execution ledger")
        else:
            ledger = {
                "artifact_type": "p0_horse_participant_execution_ledger",
                "schema_version": "p0-horse-participant-execution-ledger.v1",
                "batch_index_sha256": index_sha,
                "batch_count": index["batch_count"],
                "candidate_count": index["candidate_count"],
                "completed": [],
                "active": None,
            }
        if (
            ledger.get("artifact_type") != "p0_horse_participant_execution_ledger"
            or ledger.get("batch_index_sha256") != index_sha
            or ledger.get("batch_count") != index["batch_count"]
            or ledger.get("candidate_count") != index["candidate_count"]
            or not isinstance(ledger.get("completed"), list)
        ):
            raise ParticipantExecutionLedgerError(
                "execution ledger does not match the frozen batch index"
            )
        completed = ledger["completed"]
        if len(completed) > index["batch_count"]:
            raise ParticipantExecutionLedgerError(
                "execution ledger completed sequence is invalid"
            )
        for completed_ordinal, completed_entry in enumerate(completed, start=1):
            expected_completed = index["batches"][completed_ordinal - 1]
            if (
                not isinstance(completed_entry, dict)
                or completed_entry.get("path") != expected_completed.get("path")
                or completed_entry.get("ordinal") != completed_ordinal
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(completed_entry.get("review_manifest_sha256") or ""),
                )
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(completed_entry.get("completion_manifest_sha256") or ""),
                )
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(completed_entry.get("release_evidence_sha256") or ""),
                )
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(completed_entry.get("apply_evidence_sha256") or ""),
                )
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(completed_entry.get("verifier_evidence_sha256") or ""),
                )
            ):
                raise ParticipantExecutionLedgerError(
                    "execution ledger completed sequence is invalid"
                )
        next_ordinal = len(completed) + 1
        if action == "verify":
            if (
                ledger.get("active") is not None
                or len(completed) != index["batch_count"]
            ):
                raise ParticipantExecutionLedgerError("execution ledger is incomplete")
            return ledger
        if not re.fullmatch(r"[0-9a-f]{64}", review_manifest_sha256):
            raise ParticipantExecutionLedgerError("review manifest SHA-256 is invalid")
        if not 1 <= next_ordinal <= index["batch_count"]:
            raise ParticipantExecutionLedgerError("all batches are already complete")
        expected = index["batches"][next_ordinal - 1]
        if batch_path != expected.get("path"):
            raise ParticipantExecutionLedgerError(
                "batch is not the next ordinal in the frozen index"
            )
        active = ledger.get("active")
        identity = {
            "path": batch_path,
            "ordinal": next_ordinal,
            "review_manifest_sha256": review_manifest_sha256,
        }
        if action == "claim":
            if active is not None and any(
                active.get(key) != value for key, value in identity.items()
            ):
                raise ParticipantExecutionLedgerError(
                    "another batch or manifest is already active"
                )
            if active is None:
                ledger["active"] = {**identity, "phase": "claimed"}
            _write_atomic(ledger_file, ledger)
            return ledger
        if not isinstance(active, dict) or any(
            active.get(key) != value for key, value in identity.items()
        ):
            raise ParticipantExecutionLedgerError(
                "stage transition requires the exact active batch identity"
            )
        if action == "prepared":
            if active.get("phase") not in {"claimed", "prepared"}:
                raise ParticipantExecutionLedgerError(
                    "prepare evidence is out of order"
                )
            if completion_manifest_path is None:
                raise ParticipantExecutionLedgerError(
                    "prepared transition requires a completion manifest"
                )
            completion_bytes, completion = _read_json(
                Path(completion_manifest_path), label="completion manifest"
            )
            contract = (
                completion.get("review_manifest_input", {}).get("batch_contract", {})
                if isinstance(completion.get("review_manifest_input"), dict)
                else {}
            )
            membership = (
                contract.get("batch_membership") if isinstance(contract, dict) else None
            )
            summary = completion.get("summary")
            review_input = completion.get("review_manifest_input")
            completion_sha = hashlib.sha256(completion_bytes).hexdigest()
            if (
                completion.get("artifact_type") != "p0_horse_completion_batch_manifest"
                or completion.get("database_writes") != 0
                or not isinstance(membership, dict)
                or membership.get("path") != batch_path
                or membership.get("ordinal") != next_ordinal
                or membership.get("index_sha256") != index_sha
                or not isinstance(review_input, dict)
                or review_input.get("sha256") != review_manifest_sha256
                or not isinstance(summary, dict)
                or summary.get("processed_count") != expected.get("row_count")
            ):
                raise ParticipantExecutionLedgerError(
                    "completion manifest does not bind the active batch"
                )
            if (
                active.get("phase") == "prepared"
                and active.get("completion_manifest_sha256") != completion_sha
            ):
                raise ParticipantExecutionLedgerError(
                    "prepared completion manifest identity drifted"
                )
            ledger["active"] = {
                **identity,
                "phase": "prepared",
                "completion_manifest_sha256": completion_sha,
            }
            _write_atomic(ledger_file, ledger)
            return ledger
        phase_requirements = {
            "released": "prepared",
            "applied": "released",
            "verified": "applied",
        }
        if action not in phase_requirements or stage_evidence_path is None:
            raise ParticipantExecutionLedgerError("unsupported ledger action")
        if active.get("phase") != phase_requirements[action]:
            raise ParticipantExecutionLedgerError(f"{action} evidence is out of order")
        evidence_bytes, evidence = _read_json(
            Path(stage_evidence_path), label=f"{action} evidence"
        )
        evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
        previous_sha_field = {
            "released": "completion_manifest_sha256",
            "applied": "release_evidence_sha256",
            "verified": "apply_evidence_sha256",
        }[action]
        common_valid = (
            evidence.get("artifact_type")
            == "p0_horse_participant_execution_evidence.v1"
            and evidence.get("phase") == action
            and evidence.get("batch_index_sha256") == index_sha
            and evidence.get("batch_path") == batch_path
            and evidence.get("ordinal") == next_ordinal
            and evidence.get("review_manifest_sha256") == review_manifest_sha256
            and evidence.get("previous_evidence_sha256")
            == active.get(previous_sha_field)
        )
        release_sha = str(evidence.get("production_release_manifest_sha256") or "")
        if action == "released":
            phase_valid = all(
                re.fullmatch(r"[0-9a-f]{64}", str(evidence.get(field) or ""))
                for field in (
                    "mapping_snapshot_sha256",
                    "production_release_manifest_sha256",
                    "g3_approval_sha256",
                )
            )
        elif action == "applied":
            phase_valid = (
                release_sha == active.get("production_release_manifest_sha256")
                and evidence.get("g3_approval_sha256")
                == active.get("g3_approval_sha256")
                and re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(evidence.get("apply_receipt_sha256") or ""),
                )
                is not None
                and isinstance(evidence.get("database_write_count"), int)
                and not isinstance(evidence.get("database_write_count"), bool)
                and evidence.get("database_write_count") >= 0
            )
        else:
            planned_remaining = evidence.get("planned_remaining")
            phase_valid = (
                release_sha == active.get("production_release_manifest_sha256")
                and evidence.get("apply_receipt_sha256")
                == active.get("apply_receipt_sha256")
                and evidence.get("verifier_passed") is True
                and isinstance(planned_remaining, dict)
                and set(planned_remaining) == EXPECTED_PLANNED_REMAINING_KEYS
                and all(
                    isinstance(value, int) and not isinstance(value, bool)
                    for value in planned_remaining.values()
                )
                and not any(planned_remaining.values())
                and re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(evidence.get("verifier_receipt_sha256") or ""),
                )
                is not None
            )
        if not common_valid or not phase_valid:
            raise ParticipantExecutionLedgerError(
                f"{action} evidence does not bind the active batch"
            )
        if action == "released":
            ledger["active"] = {
                **active,
                "phase": "released",
                "release_evidence_sha256": evidence_sha,
                "mapping_snapshot_sha256": evidence["mapping_snapshot_sha256"],
                "production_release_manifest_sha256": release_sha,
                "g3_approval_sha256": evidence["g3_approval_sha256"],
            }
        elif action == "applied":
            ledger["active"] = {
                **active,
                "phase": "applied",
                "apply_evidence_sha256": evidence_sha,
                "apply_receipt_sha256": evidence["apply_receipt_sha256"],
            }
        else:
            completed.append(
                {
                    **identity,
                    "completion_manifest_sha256": active["completion_manifest_sha256"],
                    "release_evidence_sha256": active["release_evidence_sha256"],
                    "apply_evidence_sha256": active["apply_evidence_sha256"],
                    "verifier_evidence_sha256": evidence_sha,
                    "production_release_manifest_sha256": release_sha,
                    "apply_receipt_sha256": active["apply_receipt_sha256"],
                    "verifier_receipt_sha256": evidence["verifier_receipt_sha256"],
                }
            )
            ledger["active"] = None
        _write_atomic(ledger_file, ledger)
        return ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        required=True,
        choices=("claim", "prepared", "released", "applied", "verified", "verify"),
    )
    parser.add_argument("--index", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--batch", default="")
    parser.add_argument("--review-manifest-sha256", default="")
    parser.add_argument("--completion-manifest")
    parser.add_argument("--stage-evidence")
    args = parser.parse_args()
    try:
        result = update_execution_ledger(
            action=args.action,
            index_path=args.index,
            ledger_path=args.ledger,
            batch_path=args.batch,
            review_manifest_sha256=args.review_manifest_sha256,
            completion_manifest_path=args.completion_manifest,
            stage_evidence_path=args.stage_evidence,
        )
    except ParticipantExecutionLedgerError as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

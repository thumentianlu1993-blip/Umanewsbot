#!/usr/bin/env python3
"""Exact-G3 and non-skippable execution ledger for TRA bulk range batches."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

from prepare_racing_api_bulk_range_batch_plan import SCHEMA_VERSION as PLAN_SCHEMA_VERSION
from racing_api_account_budget import load_exclusive_account_proof
from racing_api_bulk_range_batch_export import (
    RUN_SCHEMA_VERSION,
    _batch_definition,
    _read_strict_json,
    _validate_checkpoint_pages,
    load_planned_batch,
)
from racing_api_horse_export import load_openapi_fingerprint, openapi_contract_manifest
from racing_api_targeted_batch_execution_ledger import (
    TargetedBatchExecutionError as BulkRangeExecutionError,
    _absolute_future_path,
    _canonical_bytes,
    _directory,
    _jsonl_rows,
    _new_output_dir,
    _parse_timestamp,
    _read_json,
    _regular,
    _scope_matches,
    _sha256_bytes,
    _sha256_path,
    _timestamp,
    _utc_now,
    _write_atomic,
    _write_json,
)


PROPOSAL_SCHEMA = "racing-api-bulk-range-batch-g3-proposal.v1"
APPROVAL_SCHEMA = "racing-api-bulk-range-batch-g3-approval.v1"
LEDGER_SCHEMA = "racing-api-bulk-range-execution-ledger.v1"
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SHA256_RE = re.compile(r"[0-9a-f]{64}$")


def _load_plan(
    *, plan_root: Path, expected_manifest_sha256: str, expected_plan_sha256: str
) -> dict:
    root = _directory(plan_root, label="bulk range plan root", private=True)
    manifest_raw, manifest = _read_json(
        root / "batch-plan-manifest.json", label="bulk range plan manifest", private=True
    )
    if _sha256_bytes(manifest_raw) != expected_manifest_sha256:
        raise BulkRangeExecutionError("bulk range plan manifest SHA-256 mismatch")
    marker = _regular(root / "PREPARED", label="bulk range plan PREPARED", private=True)
    identity = manifest.get("batch_plan")
    counts = manifest.get("counts")
    parameters = manifest.get("parameters")
    if (
        marker.read_text(encoding="ascii").strip() != expected_manifest_sha256
        or manifest.get("schema_version") != PLAN_SCHEMA_VERSION
        or manifest.get("status") != "PROPOSED_NOT_APPROVED"
        or manifest.get("approval") is not False
        or manifest.get("execution_ready") is not False
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or not isinstance(identity, dict)
        or not isinstance(counts, dict)
        or not isinstance(parameters, dict)
        or parameters.get("max_concurrent_batches") != 1
        or parameters.get("exclusive_account_proof_required_per_batch") is not True
        or parameters.get("exact_g3_required_per_batch") is not True
        or parameters.get("min_interval_ms") < 250
        or parameters.get("spacing_minutes") < 5
    ):
        raise BulkRangeExecutionError("bulk range plan manifest contract drift")
    plan_path = root / str(identity.get("path") or "")
    try:
        plan_path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise BulkRangeExecutionError("bulk range plan path escapes root") from exc
    plan_raw, rows = _jsonl_rows(plan_path, label="bulk range batch plan")
    if (
        _sha256_bytes(plan_raw) != expected_plan_sha256
        or identity.get("sha256") != expected_plan_sha256
        or identity.get("size") != len(plan_raw)
        or identity.get("rows") != len(rows)
        or counts.get("batches") != len(rows)
    ):
        raise BulkRangeExecutionError("bulk range batch plan identity drift")
    total_targets = 0
    total_ceiling = 0
    validated_rows = []
    for ordinal, row in enumerate(rows, 1):
        if row.get("ordinal") != ordinal:
            raise BulkRangeExecutionError("bulk range batch ordinal drift")
        batch, targets, identity_result = load_planned_batch(
            root,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_plan_sha256=expected_plan_sha256,
            batch_id=str(row.get("batch_id") or ""),
        )
        if batch != row or len(targets) != row.get("target_count"):
            raise BulkRangeExecutionError("bulk range batch replay drift")
        validated_rows.append({**row, "_identity": identity_result})
        total_targets += int(row["target_count"])
        total_ceiling += int(row["request_ceiling"])
    if (
        counts.get("targets") != total_targets
        or counts.get("protocol_request_ceiling") != total_ceiling
    ):
        raise BulkRangeExecutionError("bulk range batch plan totals drift")
    return {
        "root": root,
        "manifest": manifest,
        "manifest_sha256": expected_manifest_sha256,
        "plan_sha256": expected_plan_sha256,
        "batches": validated_rows,
    }


def _initial_ledger(plan: Mapping[str, object]) -> dict:
    counts = plan["manifest"]["counts"]
    return {
        "schema_version": LEDGER_SCHEMA,
        "plan_manifest_sha256": plan["manifest_sha256"],
        "batch_plan_sha256": plan["plan_sha256"],
        "batch_count": counts["batches"],
        "target_count": counts["targets"],
        "planned_request_ceiling": counts["protocol_request_ceiling"],
        "completed": [],
        "active": None,
    }


def _attempt_digest(attempt: Mapping[str, object]) -> str:
    return _sha256_bytes(_canonical_bytes(attempt))


def _validate_attempt(attempt: object, *, expected_number: int) -> None:
    if not isinstance(attempt, dict):
        raise BulkRangeExecutionError("bulk range attempt must be an object")
    request_count = attempt.get("request_count")
    ceiling = attempt.get("request_ceiling")
    if (
        attempt.get("attempt_number") != expected_number
        or attempt.get("status") not in {"safe_stopped", "complete"}
        or not SHA256_RE.fullmatch(str(attempt.get("approval_manifest_sha256") or ""))
        or not SHA256_RE.fullmatch(str(attempt.get("proposal_manifest_sha256") or ""))
        or not SHA256_RE.fullmatch(str(attempt.get("exclusive_proof_sha256") or ""))
        or isinstance(ceiling, bool)
        or not isinstance(ceiling, int)
        or ceiling < 1
        or isinstance(request_count, bool)
        or not isinstance(request_count, int)
        or not 0 <= request_count <= ceiling
        or attempt.get("attempt_sha256")
        != _attempt_digest({key: value for key, value in attempt.items() if key != "attempt_sha256"})
    ):
        raise BulkRangeExecutionError("bulk range attempt identity drift")
    _parse_timestamp(attempt.get("finished_at"), label="bulk range attempt finished_at")


def _validate_complete_artifact(entry: Mapping[str, object], batch: Mapping[str, object]) -> None:
    root = _directory(
        Path(str(entry.get("output_dir") or "")), label="completed bulk range output", private=True
    )
    raw, manifest = _read_json(
        root / "batch-manifest.json", label="completed bulk range manifest", private=True
    )
    manifest_sha = _sha256_bytes(raw)
    marker = _regular(root / "COMPLETE", label="completed bulk range COMPLETE", private=True)
    plan = manifest.get("plan")
    manifest_batch = manifest.get("batch")
    if (
        manifest_sha != entry.get("batch_manifest_sha256")
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != RUN_SCHEMA_VERSION
        or manifest.get("status") not in {"complete", "complete_with_gaps"}
        or manifest.get("completion_marker") != "COMPLETE"
        or manifest.get("reconciliation_status")
        != ("complete" if manifest.get("gap_count") == 0 else "needs_review")
        or manifest.get("database_writes") != 0
        or not isinstance(plan, dict)
        or not isinstance(manifest_batch, dict)
        or plan.get("manifest_sha256") != batch["_identity"].get("manifest_sha256")
        or plan.get("plan_sha256") != batch["_identity"].get("plan_sha256")
        or manifest_batch.get("batch_id") != batch.get("batch_id")
        or manifest_batch.get("target_ledger", {}).get("sha256")
        != batch.get("target_ledger", {}).get("sha256")
        or manifest.get("request_count") != entry.get("request_count")
    ):
        raise BulkRangeExecutionError("completed bulk range artifact identity drift")


def _validate_ledger(ledger: dict, plan: Mapping[str, object]) -> None:
    expected = _initial_ledger(plan)
    for key, value in expected.items():
        if key not in {"completed", "active"} and ledger.get(key) != value:
            raise BulkRangeExecutionError("bulk range ledger plan identity drift")
    completed = ledger.get("completed")
    if not isinstance(completed, list) or len(completed) > len(plan["batches"]):
        raise BulkRangeExecutionError("bulk range completed sequence drift")
    for ordinal, entry in enumerate(completed, 1):
        batch = plan["batches"][ordinal - 1]
        attempts = entry.get("attempts") if isinstance(entry, dict) else None
        if (
            not isinstance(entry, dict)
            or entry.get("ordinal") != ordinal
            or entry.get("batch_id") != batch.get("batch_id")
            or entry.get("target_ledger_sha256") != batch["target_ledger"].get("sha256")
            or not isinstance(attempts, list)
            or not attempts
            or attempts[-1].get("status") != "complete"
            or entry.get("request_count") != sum(attempt["request_count"] for attempt in attempts)
        ):
            raise BulkRangeExecutionError("bulk range completed sequence drift")
        for attempt_number, attempt in enumerate(attempts, 1):
            _validate_attempt(attempt, expected_number=attempt_number)
            prior_request_count = sum(
                row["request_count"] for row in attempts[: attempt_number - 1]
            )
            if attempt.get("request_ceiling") != (
                batch["request_ceiling"] - prior_request_count
            ):
                raise BulkRangeExecutionError("bulk range attempt ceiling drift")
        _parse_timestamp(entry.get("completed_at"), label="bulk range completed_at")
        _validate_complete_artifact(entry, batch)
    active = ledger.get("active")
    if active is None:
        return
    ordinal = len(completed) + 1
    if not 1 <= ordinal <= len(plan["batches"]):
        raise BulkRangeExecutionError("bulk range active ordinal is invalid")
    batch = plan["batches"][ordinal - 1]
    attempts = active.get("attempts") if isinstance(active, dict) else None
    if (
        not isinstance(active, dict)
        or active.get("ordinal") != ordinal
        or active.get("batch_id") != batch.get("batch_id")
        or active.get("target_ledger_sha256") != batch["target_ledger"].get("sha256")
        or active.get("phase") not in {"running", "safe_stopped"}
        or not isinstance(attempts, list)
    ):
        raise BulkRangeExecutionError("bulk range active identity drift")
    for attempt_number, attempt in enumerate(attempts, 1):
        _validate_attempt(attempt, expected_number=attempt_number)
        if attempt.get("status") != "safe_stopped":
            raise BulkRangeExecutionError("active bulk range attempts must be safe-stopped")
        prior_request_count = sum(
            row["request_count"] for row in attempts[: attempt_number - 1]
        )
        if attempt.get("request_ceiling") != (
            batch["request_ceiling"] - prior_request_count
        ):
            raise BulkRangeExecutionError("active bulk range attempt ceiling drift")
    prior_request_count = sum(attempt["request_count"] for attempt in attempts)
    if active["phase"] == "running" and (
        not re.fullmatch(r"[0-9a-f]{32}", str(active.get("claim_token") or ""))
        or active.get("attempt_number") != len(attempts) + 1
        or not SHA256_RE.fullmatch(str(active.get("approval_manifest_sha256") or ""))
        or not SHA256_RE.fullmatch(str(active.get("proposal_manifest_sha256") or ""))
        or not SHA256_RE.fullmatch(str(active.get("exclusive_proof_sha256") or ""))
        or active.get("request_ceiling")
        != batch["request_ceiling"] - prior_request_count
    ):
        raise BulkRangeExecutionError("running bulk range claim identity drift")
    if active["phase"] == "safe_stopped" and (
        not attempts
        or active.get("request_ceiling") != attempts[-1].get("request_ceiling")
        or "claim_token" in active
        or "attempt_number" in active
    ):
        raise BulkRangeExecutionError("safe-stopped bulk range identity drift")


class _LedgerWindow:
    """Reuse the targeted ledger's private atomic lock implementation through composition."""

    def __init__(self, path: Path, plan: Mapping[str, object]):
        self.path = path
        self.plan = plan
        self.ledger = None

    def __enter__(self):
        # TargetedWindow calls its own schema validator, so only reuse its locking fields manually.
        import fcntl
        import os
        import stat

        parent = self.path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if parent.is_symlink() or stat.S_IMODE(parent.stat(follow_symlinks=False).st_mode) & 0o077:
            raise BulkRangeExecutionError("bulk range ledger parent must be private")
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        if self.lock_path.is_symlink():
            raise BulkRangeExecutionError("bulk range ledger lock must not be a symlink")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.lock_path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        self.handle = os.fdopen(descriptor, "a+b", closefd=True)
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        if self.path.exists() or self.path.is_symlink():
            _, ledger = _read_json(self.path, label="bulk range execution ledger", private=True)
        else:
            ledger = _initial_ledger(self.plan)
            _write_json(self.path, ledger)
        _validate_ledger(ledger, self.plan)
        self.ledger = ledger
        return self

    def write(self) -> None:
        _validate_ledger(self.ledger, self.plan)
        _write_json(self.path, self.ledger)

    def __exit__(self, exc_type, exc, traceback):
        import fcntl

        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()


def _next_scope(
    *,
    plan: Mapping[str, object],
    ledger: Mapping[str, object],
    batch_output_dir: Path,
    account_budget_root: Path,
    credential_alias: str,
    account_scope_id: str,
    openapi_contract: Mapping[str, object],
) -> dict:
    if ledger.get("active") is not None:
        raise BulkRangeExecutionError("bulk range batch is already active or safe-stopped")
    ordinal = len(ledger["completed"]) + 1
    if not 1 <= ordinal <= len(plan["batches"]):
        raise BulkRangeExecutionError("all bulk range batches are complete")
    if not IDENTIFIER_RE.fullmatch(str(credential_alias or "")) or not IDENTIFIER_RE.fullmatch(
        str(account_scope_id or "")
    ):
        raise BulkRangeExecutionError("bulk range account identity is invalid")
    batch = plan["batches"][ordinal - 1]
    output_path = _absolute_future_path(
        batch_output_dir, label="bulk range output directory", allow_existing=False
    )
    budget_path = _absolute_future_path(
        account_budget_root, label="bulk range account budget root", allow_existing=False
    )
    batch_digest = hashlib.sha256(
        _canonical_bytes({key: value for key, value in batch.items() if key != "_identity"})
    ).hexdigest()
    return {
        "plan": {
            "manifest_sha256": plan["manifest_sha256"],
            "batch_plan_sha256": plan["plan_sha256"],
        },
        "batch": {
            "ordinal": ordinal,
            "batch_id": batch["batch_id"],
            "batch_sha256": batch_digest,
            "country_region": batch["country_region"],
            "target_count": batch["target_count"],
            "target_ledger_path": batch["_identity"]["target_ledger"]["path"],
            "target_ledger_sha256": batch["target_ledger"]["sha256"],
            "region_year_unit_count": batch["region_year_unit_count"],
            "date_range_count": batch["date_range_count"],
        },
        "run": {
            "output_dir": str(output_path),
            "request_ceiling": batch["request_ceiling"],
            "min_interval_ms": plan["manifest"]["parameters"]["min_interval_ms"],
            "endpoint_kinds": ["bulk_results"],
            "openapi_contract": dict(openapi_contract),
            "database_writes": 0,
        },
        "account": {
            "credential_alias": credential_alias,
            "scope_id": account_scope_id,
            "budget_root": str(budget_path),
            "exclusive_account_proof_required": True,
        },
        "previous_completed_batch": (
            {
                "ordinal": ledger["completed"][-1]["ordinal"],
                "batch_id": ledger["completed"][-1]["batch_id"],
                "batch_manifest_sha256": ledger["completed"][-1]["batch_manifest_sha256"],
                "completed_at": ledger["completed"][-1]["completed_at"],
            }
            if ledger["completed"]
            else None
        ),
    }


def prepare_next_batch_g3_proposal(
    *,
    plan_root: Path,
    expected_plan_manifest_sha256: str,
    expected_batch_plan_sha256: str,
    execution_ledger_path: Path,
    batch_output_dir: Path,
    account_budget_root: Path,
    credential_alias: str,
    account_scope_id: str,
    openapi_fingerprint_path: Path,
    approved_openapi_fingerprint_sha256: str,
    output_dir: Path,
    now: datetime | None = None,
) -> dict:
    plan = _load_plan(
        plan_root=plan_root,
        expected_manifest_sha256=expected_plan_manifest_sha256,
        expected_plan_sha256=expected_batch_plan_sha256,
    )
    openapi_contract = openapi_contract_manifest(
        load_openapi_fingerprint(
            openapi_fingerprint_path, approved_openapi_fingerprint_sha256
        )
    )
    with _LedgerWindow(execution_ledger_path, plan) as window:
        scope = _next_scope(
            plan=plan,
            ledger=window.ledger,
            batch_output_dir=batch_output_dir,
            account_budget_root=account_budget_root,
            credential_alias=credential_alias,
            account_scope_id=account_scope_id,
            openapi_contract=openapi_contract,
        )
    proposal_root = _new_output_dir(output_dir, label="bulk range G3 proposal output")
    proposal = {
        "schema_version": PROPOSAL_SCHEMA,
        "status": "PROPOSED_NOT_APPROVED",
        "approval": False,
        "execution_ready": False,
        "network_requests": 0,
        "database_writes": 0,
        "prepared_at": _timestamp(_utc_now(now)),
        "scope": scope,
    }
    path = proposal_root / "proposal-manifest.json"
    _write_json(path, proposal)
    proposal_sha = _sha256_path(path)
    _write_atomic(proposal_root / "PREPARED", f"{proposal_sha}\n".encode("ascii"))
    return {**proposal, "proposal_manifest_sha256": proposal_sha}


def _load_proposal(root: Path, expected_sha256: str) -> tuple[dict, str]:
    proposal_root = _directory(root, label="bulk range G3 proposal root", private=True)
    raw, proposal = _read_json(
        proposal_root / "proposal-manifest.json", label="bulk range G3 proposal", private=True
    )
    marker = _regular(proposal_root / "PREPARED", label="bulk range G3 PREPARED", private=True)
    if (
        _sha256_bytes(raw) != expected_sha256
        or marker.read_text(encoding="ascii").strip() != expected_sha256
        or proposal.get("schema_version") != PROPOSAL_SCHEMA
        or proposal.get("status") != "PROPOSED_NOT_APPROVED"
        or proposal.get("approval") is not False
        or proposal.get("execution_ready") is not False
        or proposal.get("network_requests") != 0
        or proposal.get("database_writes") != 0
        or not isinstance(proposal.get("scope"), dict)
    ):
        raise BulkRangeExecutionError("bulk range G3 proposal contract drift")
    return proposal, expected_sha256


def publish_batch_g3_approval(
    *,
    proposal_root: Path,
    approved_proposal_manifest_sha256: str,
    approved_by: str,
    decision_source_reference: str,
    output_dir: Path,
    now: datetime | None = None,
) -> dict:
    proposal, proposal_sha = _load_proposal(
        proposal_root, approved_proposal_manifest_sha256
    )
    reviewer = str(approved_by or "").strip()
    reference = str(decision_source_reference or "").strip()
    if not reviewer or not reference:
        raise BulkRangeExecutionError("bulk range approval requires reviewer and source")
    approval_root = _new_output_dir(output_dir, label="bulk range G3 approval output")
    approval = {
        "schema_version": APPROVAL_SCHEMA,
        "status": "approved",
        "approval": True,
        "execution_ready": True,
        "network_requests_allowed": True,
        "database_writes": 0,
        "proposal_manifest_sha256": proposal_sha,
        "scope": proposal["scope"],
        "approved_by": reviewer,
        "approved_at": _timestamp(_utc_now(now)),
        "decision_source_reference": reference,
    }
    path = approval_root / "approval-manifest.json"
    _write_json(path, approval)
    approval_sha = _sha256_path(path)
    _write_atomic(approval_root / "COMPLETE", f"{approval_sha}\n".encode("ascii"))
    return {**approval, "approval_manifest_sha256": approval_sha}


def _load_approval(root: Path, expected_sha256: str) -> tuple[dict, str]:
    approval_root = _directory(root, label="bulk range G3 approval root", private=True)
    raw, approval = _read_json(
        approval_root / "approval-manifest.json", label="bulk range G3 approval", private=True
    )
    marker = _regular(approval_root / "COMPLETE", label="bulk range G3 COMPLETE", private=True)
    if (
        _sha256_bytes(raw) != expected_sha256
        or marker.read_text(encoding="ascii").strip() != expected_sha256
        or approval.get("schema_version") != APPROVAL_SCHEMA
        or approval.get("status") != "approved"
        or approval.get("approval") is not True
        or approval.get("execution_ready") is not True
        or approval.get("network_requests_allowed") is not True
        or approval.get("database_writes") != 0
        or not isinstance(approval.get("scope"), dict)
        or not str(approval.get("approved_by") or "").strip()
        or not str(approval.get("decision_source_reference") or "").strip()
    ):
        raise BulkRangeExecutionError("bulk range G3 approval contract drift")
    _parse_timestamp(approval.get("approved_at"), label="bulk range approval time")
    return approval, expected_sha256


def _load_execution_ledger_read_only(
    execution_ledger_path: Path,
    plan: Mapping[str, object],
) -> dict:
    _, ledger = _read_json(
        execution_ledger_path,
        label="bulk range execution ledger",
        private=True,
    )
    _validate_ledger(ledger, plan)
    return ledger


def _validate_approved_next_scope(
    *,
    plan: Mapping[str, object],
    ledger: Mapping[str, object],
    approval: Mapping[str, object],
    batch_output_dir: Path,
    account_budget_root: Path,
    credential_alias: str,
    account_scope_id: str,
    openapi_contract: Mapping[str, object],
    now: datetime,
) -> dict:
    expected_scope = _next_scope(
        plan=plan,
        ledger=ledger,
        batch_output_dir=batch_output_dir,
        account_budget_root=account_budget_root,
        credential_alias=credential_alias,
        account_scope_id=account_scope_id,
        openapi_contract=openapi_contract,
    )
    if not _scope_matches(expected_scope, approval["scope"]):
        raise BulkRangeExecutionError("bulk range approval does not bind next scope")
    if ledger["completed"]:
        earliest = _parse_timestamp(
            ledger["completed"][-1]["completed_at"], label="previous completion"
        ) + timedelta(minutes=plan["manifest"]["parameters"]["spacing_minutes"])
        if now < earliest:
            raise BulkRangeExecutionError(
                f"next bulk range batch cannot start before {_timestamp(earliest)}"
            )
    return expected_scope


def preflight_next_batch_execution(
    *,
    plan_root: Path,
    expected_plan_manifest_sha256: str,
    expected_batch_plan_sha256: str,
    execution_ledger_path: Path,
    approval_root: Path,
    approved_g3_manifest_sha256: str,
    batch_output_dir: Path,
    account_budget_root: Path,
    credential_alias: str,
    account_scope_id: str,
    openapi_fingerprint_path: Path,
    approved_openapi_fingerprint_sha256: str,
    now: datetime | None = None,
) -> dict:
    """Validate the exact next bulk command without loading proof or claiming."""

    clock = _utc_now(now)
    plan = _load_plan(
        plan_root=plan_root,
        expected_manifest_sha256=expected_plan_manifest_sha256,
        expected_plan_sha256=expected_batch_plan_sha256,
    )
    approval, approval_sha = _load_approval(approval_root, approved_g3_manifest_sha256)
    openapi_contract = openapi_contract_manifest(
        load_openapi_fingerprint(
            openapi_fingerprint_path, approved_openapi_fingerprint_sha256
        )
    )
    ledger = _load_execution_ledger_read_only(execution_ledger_path, plan)
    scope = _validate_approved_next_scope(
        plan=plan,
        ledger=ledger,
        approval=approval,
        batch_output_dir=batch_output_dir,
        account_budget_root=account_budget_root,
        credential_alias=credential_alias,
        account_scope_id=account_scope_id,
        openapi_contract=openapi_contract,
        now=clock,
    )
    return {
        "schema_version": "racing-api-bulk-range-next-preflight.v1",
        "status": "ready_for_fresh_exclusive_proof",
        "network_requests": 0,
        "database_writes": 0,
        "proof_loaded": False,
        "ledger_mutated": False,
        "approval_manifest_sha256": approval_sha,
        "proposal_manifest_sha256": approval["proposal_manifest_sha256"],
        "next_batch": {
            "ordinal": scope["batch"]["ordinal"],
            "batch_id": scope["batch"]["batch_id"],
            "country_region": scope["batch"]["country_region"],
            "target_count": scope["batch"]["target_count"],
            "target_ledger_sha256": scope["batch"]["target_ledger_sha256"],
            "date_range_count": scope["batch"]["date_range_count"],
            "request_ceiling": scope["run"]["request_ceiling"],
            "output_dir": scope["run"]["output_dir"],
            "account_budget_root": scope["account"]["budget_root"],
            "endpoint_kinds": scope["run"]["endpoint_kinds"],
        },
    }


def claim_batch_execution(
    *,
    plan_root: Path,
    expected_plan_manifest_sha256: str,
    expected_batch_plan_sha256: str,
    execution_ledger_path: Path,
    approval_root: Path,
    approved_g3_manifest_sha256: str,
    exclusive_proof_path: Path,
    exclusive_proof_sha256: str,
    batch_output_dir: Path,
    account_budget_root: Path,
    credential_alias: str,
    account_scope_id: str,
    openapi_fingerprint_path: Path,
    approved_openapi_fingerprint_sha256: str,
    now: datetime | None = None,
) -> dict:
    clock = _utc_now(now)
    plan = _load_plan(
        plan_root=plan_root,
        expected_manifest_sha256=expected_plan_manifest_sha256,
        expected_plan_sha256=expected_batch_plan_sha256,
    )
    approval, approval_sha = _load_approval(approval_root, approved_g3_manifest_sha256)
    openapi_contract = openapi_contract_manifest(
        load_openapi_fingerprint(
            openapi_fingerprint_path, approved_openapi_fingerprint_sha256
        )
    )
    with _LedgerWindow(execution_ledger_path, plan) as window:
        _validate_approved_next_scope(
            plan=plan,
            ledger=window.ledger,
            approval=approval,
            batch_output_dir=batch_output_dir,
            account_budget_root=account_budget_root,
            credential_alias=credential_alias,
            account_scope_id=account_scope_id,
            openapi_contract=openapi_contract,
            now=clock,
        )
        proposal_sha = approval["proposal_manifest_sha256"]
        load_exclusive_account_proof(
            exclusive_proof_path,
            expected_sha256=exclusive_proof_sha256,
            credential_alias=credential_alias,
            scope_id=account_scope_id,
            scope_manifest_sha256=proposal_sha,
            now=clock,
        )
        batch = plan["batches"][len(window.ledger["completed"])]
        active = {
            "ordinal": batch["ordinal"],
            "batch_id": batch["batch_id"],
            "target_ledger_sha256": batch["target_ledger"]["sha256"],
            "output_dir": approval["scope"]["run"]["output_dir"],
            "phase": "running",
            "attempt_number": 1,
            "attempts": [],
            "claim_token": uuid.uuid4().hex,
            "approval_manifest_sha256": approval_sha,
            "proposal_manifest_sha256": proposal_sha,
            "exclusive_proof_sha256": exclusive_proof_sha256,
            "request_ceiling": batch["request_ceiling"],
            "account_budget_root": approval["scope"]["account"]["budget_root"],
            "account_scope_id": account_scope_id,
            "claimed_at": _timestamp(clock),
        }
        window.ledger["active"] = active
        window.write()
        return dict(active)


def _validate_resume_scope(
    *,
    plan: Mapping[str, object],
    ledger: Mapping[str, object],
    approval: Mapping[str, object],
    approval_sha256: str,
    batch_output_dir: Path,
    account_budget_root: Path,
    credential_alias: str,
    account_scope_id: str,
    openapi_contract: Mapping[str, object],
) -> tuple[dict, int, int]:
    active = ledger.get("active")
    if not isinstance(active, dict) or active.get("phase") != "safe_stopped":
        raise BulkRangeExecutionError("resume requires a safe-stopped bulk range batch")
    batch = plan["batches"][active["ordinal"] - 1]
    attempts = active["attempts"]
    prior_request_count = sum(attempt["request_count"] for attempt in attempts)
    remaining_request_ceiling = batch["request_ceiling"] - prior_request_count
    if remaining_request_ceiling < 1:
        raise BulkRangeExecutionError("bulk range batch request ceiling is exhausted")
    if (
        approval_sha256 != active.get("approval_manifest_sha256")
        or approval.get("proposal_manifest_sha256")
        != active.get("proposal_manifest_sha256")
    ):
        raise BulkRangeExecutionError("resume requires the exact original G3 approval")
    output_path = _absolute_future_path(
        batch_output_dir,
        label="bulk range resume output directory",
        allow_existing=True,
    )
    budget_path = _absolute_future_path(
        account_budget_root,
        label="bulk range resume account budget root",
        allow_existing=True,
    )
    batch_digest = hashlib.sha256(
        _canonical_bytes({key: value for key, value in batch.items() if key != "_identity"})
    ).hexdigest()
    expected_scope = {
        "plan": {
            "manifest_sha256": plan["manifest_sha256"],
            "batch_plan_sha256": plan["plan_sha256"],
        },
        "batch": {
            "ordinal": batch["ordinal"],
            "batch_id": batch["batch_id"],
            "batch_sha256": batch_digest,
            "country_region": batch["country_region"],
            "target_count": batch["target_count"],
            "target_ledger_path": batch["_identity"]["target_ledger"]["path"],
            "target_ledger_sha256": batch["target_ledger"]["sha256"],
            "region_year_unit_count": batch["region_year_unit_count"],
            "date_range_count": batch["date_range_count"],
        },
        "run": {
            "output_dir": str(output_path),
            "request_ceiling": batch["request_ceiling"],
            "min_interval_ms": plan["manifest"]["parameters"]["min_interval_ms"],
            "endpoint_kinds": ["bulk_results"],
            "openapi_contract": dict(openapi_contract),
            "database_writes": 0,
        },
        "account": {
            "credential_alias": credential_alias,
            "scope_id": account_scope_id,
            "budget_root": str(budget_path),
            "exclusive_account_proof_required": True,
        },
        "previous_completed_batch": (
            {
                "ordinal": ledger["completed"][-1]["ordinal"],
                "batch_id": ledger["completed"][-1]["batch_id"],
                "batch_manifest_sha256": ledger["completed"][-1][
                    "batch_manifest_sha256"
                ],
                "completed_at": ledger["completed"][-1]["completed_at"],
            }
            if ledger["completed"]
            else None
        ),
    }
    if (
        not _scope_matches(expected_scope, approval["scope"])
        or Path(str(active.get("output_dir") or "")).resolve(strict=True)
        != output_path
        or active.get("account_budget_root") != str(budget_path)
        or active.get("account_scope_id") != account_scope_id
    ):
        raise BulkRangeExecutionError("resume approval does not bind active scope")
    try:
        definition = _read_strict_json(
            output_path / "batch-definition.json",
            label="bulk range batch definition",
        )
        expected_definition = _batch_definition(
            batch=batch,
            plan_identity=batch["_identity"],
            openapi_contract=openapi_contract,
        )
        if definition != expected_definition:
            raise ValueError("bulk range batch definition drift")
        checkpoint = _read_strict_json(
            output_path / "checkpoint.json",
            label="bulk range checkpoint",
        )
        _validate_checkpoint_pages(
            output_dir=output_path,
            definition=definition,
            checkpoint=checkpoint,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise BulkRangeExecutionError(str(exc)) from exc
    checkpoint_attempts = checkpoint["attempt_request_ledgers"]
    if (
        checkpoint.get("status") != "safe_stopped"
        or checkpoint.get("cumulative_request_count") != prior_request_count
        or len(checkpoint_attempts) != len(attempts)
        or [row.get("request_count") for row in checkpoint_attempts]
        != [row.get("request_count") for row in attempts]
        or any(row.get("status") != "safe_stopped" for row in checkpoint_attempts)
    ):
        raise BulkRangeExecutionError("execution ledger and checkpoint resume drift")
    return batch, prior_request_count, remaining_request_ceiling


def resume_batch_execution(
    *,
    plan_root: Path,
    expected_plan_manifest_sha256: str,
    expected_batch_plan_sha256: str,
    execution_ledger_path: Path,
    approval_root: Path,
    approved_g3_manifest_sha256: str,
    exclusive_proof_path: Path,
    exclusive_proof_sha256: str,
    batch_output_dir: Path,
    account_budget_root: Path,
    credential_alias: str,
    account_scope_id: str,
    openapi_fingerprint_path: Path,
    approved_openapi_fingerprint_sha256: str,
    now: datetime | None = None,
) -> dict:
    """Explicitly resume one safe-stopped batch under a fresh exclusive proof."""

    clock = _utc_now(now)
    plan = _load_plan(
        plan_root=plan_root,
        expected_manifest_sha256=expected_plan_manifest_sha256,
        expected_plan_sha256=expected_batch_plan_sha256,
    )
    approval, approval_sha = _load_approval(approval_root, approved_g3_manifest_sha256)
    openapi_contract = openapi_contract_manifest(
        load_openapi_fingerprint(
            openapi_fingerprint_path, approved_openapi_fingerprint_sha256
        )
    )
    with _LedgerWindow(execution_ledger_path, plan) as window:
        batch, prior_request_count, remaining_request_ceiling = _validate_resume_scope(
            plan=plan,
            ledger=window.ledger,
            approval=approval,
            approval_sha256=approval_sha,
            batch_output_dir=batch_output_dir,
            account_budget_root=account_budget_root,
            credential_alias=credential_alias,
            account_scope_id=account_scope_id,
            openapi_contract=openapi_contract,
        )
        proposal_sha = approval["proposal_manifest_sha256"]
        load_exclusive_account_proof(
            exclusive_proof_path,
            expected_sha256=exclusive_proof_sha256,
            credential_alias=credential_alias,
            scope_id=account_scope_id,
            scope_manifest_sha256=proposal_sha,
            now=clock,
        )
        active = window.ledger["active"]
        active.update(
            phase="running",
            attempt_number=len(active["attempts"]) + 1,
            claim_token=uuid.uuid4().hex,
            approval_manifest_sha256=approval_sha,
            proposal_manifest_sha256=proposal_sha,
            exclusive_proof_sha256=exclusive_proof_sha256,
            request_ceiling=remaining_request_ceiling,
            resumed_at=_timestamp(clock),
        )
        window.write()
        return {
            **active,
            "batch_request_ceiling": batch["request_ceiling"],
            "prior_request_count": prior_request_count,
            "remaining_request_ceiling": remaining_request_ceiling,
        }


def _attempt_from_active(
    active: Mapping[str, object],
    *,
    status: str,
    request_count: int,
    finished_at: datetime,
    batch_manifest_sha256: str = "",
    error_type: str = "",
    error_message: str = "",
) -> dict:
    if (
        isinstance(request_count, bool)
        or not isinstance(request_count, int)
        or not 0 <= request_count <= active["request_ceiling"]
    ):
        raise BulkRangeExecutionError("bulk range attempt request count is invalid")
    attempt = {
        "attempt_number": active["attempt_number"],
        "status": status,
        "approval_manifest_sha256": active["approval_manifest_sha256"],
        "proposal_manifest_sha256": active["proposal_manifest_sha256"],
        "exclusive_proof_sha256": active["exclusive_proof_sha256"],
        "request_ceiling": active["request_ceiling"],
        "request_count": request_count,
        "finished_at": _timestamp(finished_at),
        "batch_manifest_sha256": batch_manifest_sha256,
        "error_type": str(error_type or "")[:160],
        "error_message": str(error_message or "")[:500],
    }
    attempt["attempt_sha256"] = _attempt_digest(attempt)
    return attempt


def mark_batch_safe_stopped(
    *,
    plan_root: Path,
    expected_plan_manifest_sha256: str,
    expected_batch_plan_sha256: str,
    execution_ledger_path: Path,
    claim_token: str,
    request_count: int,
    error_type: str,
    error_message: str,
    now: datetime | None = None,
) -> dict:
    plan = _load_plan(
        plan_root=plan_root,
        expected_manifest_sha256=expected_plan_manifest_sha256,
        expected_plan_sha256=expected_batch_plan_sha256,
    )
    with _LedgerWindow(execution_ledger_path, plan) as window:
        active = window.ledger.get("active")
        if (
            not isinstance(active, dict)
            or active.get("phase") != "running"
            or active.get("claim_token") != claim_token
        ):
            raise BulkRangeExecutionError("safe-stop requires exact bulk range claim")
        attempt = _attempt_from_active(
            active,
            status="safe_stopped",
            request_count=request_count,
            finished_at=_utc_now(now),
            error_type=error_type,
            error_message=error_message,
        )
        active["attempts"].append(attempt)
        active["phase"] = "safe_stopped"
        active.pop("claim_token", None)
        active.pop("attempt_number", None)
        window.write()
        return dict(active)


def mark_batch_complete(
    *,
    plan_root: Path,
    expected_plan_manifest_sha256: str,
    expected_batch_plan_sha256: str,
    execution_ledger_path: Path,
    claim_token: str,
    batch_output_dir: Path,
    expected_batch_manifest_sha256: str,
    request_count: int,
    now: datetime | None = None,
) -> dict:
    plan = _load_plan(
        plan_root=plan_root,
        expected_manifest_sha256=expected_plan_manifest_sha256,
        expected_plan_sha256=expected_batch_plan_sha256,
    )
    clock = _utc_now(now)
    with _LedgerWindow(execution_ledger_path, plan) as window:
        active = window.ledger.get("active")
        if (
            not isinstance(active, dict)
            or active.get("phase") != "running"
            or active.get("claim_token") != claim_token
            or Path(active["output_dir"]).resolve(strict=True)
            != batch_output_dir.resolve(strict=True)
        ):
            raise BulkRangeExecutionError("completion requires exact bulk range claim")
        raw, manifest = _read_json(
            batch_output_dir / "batch-manifest.json",
            label="bulk range batch completion manifest",
            private=True,
        )
        manifest_sha = _sha256_bytes(raw)
        if (
            manifest_sha != expected_batch_manifest_sha256
            or manifest.get("request_count") != request_count
        ):
            raise BulkRangeExecutionError("bulk range completion manifest drift")
        prior_request_count = sum(
            attempt["request_count"] for attempt in active["attempts"]
        )
        current_attempt_request_count = request_count - prior_request_count
        if current_attempt_request_count < 0:
            raise BulkRangeExecutionError(
                "bulk range cumulative request count precedes prior attempts"
            )
        attempt = _attempt_from_active(
            active,
            status="complete",
            request_count=current_attempt_request_count,
            finished_at=clock,
            batch_manifest_sha256=manifest_sha,
        )
        batch = plan["batches"][active["ordinal"] - 1]
        entry = {
            "ordinal": active["ordinal"],
            "batch_id": active["batch_id"],
            "target_ledger_sha256": active["target_ledger_sha256"],
            "output_dir": str(batch_output_dir.resolve(strict=True)),
            "batch_manifest_sha256": manifest_sha,
            "request_count": request_count,
            "attempts": [*active["attempts"], attempt],
            "completed_at": _timestamp(clock),
        }
        _validate_complete_artifact(entry, batch)
        window.ledger["completed"].append(entry)
        window.ledger["active"] = None
        window.write()
        return entry


if __name__ == "__main__":
    raise SystemExit("library only; no network execution command is exposed")

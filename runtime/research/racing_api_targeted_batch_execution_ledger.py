#!/usr/bin/env python3
"""为 TRA targeted-horse 网络批次生成精确 G3，并维护不可跳批的执行账本。

本模块本身不访问 TRA、不读取凭据、不写业务数据库。只有 ``claim`` 会读取并验证一份
限时 exclusive-account proof；真正的网络调用仍由
``racing_api_targeted_batch_export.py`` 执行。
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from .racing_api_account_budget import load_exclusive_account_proof
    from .racing_api_horse_export import (
        load_openapi_fingerprint,
        openapi_contract_manifest,
    )
except ImportError:  # pragma: no cover - direct script execution
    from racing_api_account_budget import load_exclusive_account_proof
    from racing_api_horse_export import (
        load_openapi_fingerprint,
        openapi_contract_manifest,
    )


PLAN_SCHEMA = "racing-api-targeted-batch-plan.v1"
PROPOSAL_SCHEMA = "racing-api-targeted-batch-g3-proposal.v1"
APPROVAL_SCHEMA = "racing-api-targeted-batch-g3-approval.v1"
LEDGER_SCHEMA = "racing-api-targeted-batch-execution-ledger.v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MAX_JSON_BYTES = 1024 * 1024
ALLOWED_ENDPOINT_KINDS = [
    "horse_search",
    "horse_results",
    "horse_pro",
    "horse_standard_fallback_on_404",
]


class TargetedBatchExecutionError(ValueError):
    pass


def _strict_object(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise TargetedBatchExecutionError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path: Path, *, label: str, private: bool = False) -> Path:
    if path.is_symlink():
        raise TargetedBatchExecutionError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise TargetedBatchExecutionError(f"{label} is missing") from exc
    if not stat.S_ISREG(metadata.st_mode) or not resolved.is_file():
        raise TargetedBatchExecutionError(f"{label} must be a regular file")
    if private and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise TargetedBatchExecutionError(
            f"{label} permissions must not grant group/other access"
        )
    return resolved


def _directory(path: Path, *, label: str, private: bool = False) -> Path:
    if path.is_symlink():
        raise TargetedBatchExecutionError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise TargetedBatchExecutionError(f"{label} is missing") from exc
    if not stat.S_ISDIR(metadata.st_mode) or not resolved.is_dir():
        raise TargetedBatchExecutionError(f"{label} must be a directory")
    if private and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise TargetedBatchExecutionError(
            f"{label} permissions must not grant group/other access"
        )
    return resolved


def _read_json(path: Path, *, label: str, private: bool = False) -> tuple[bytes, dict]:
    resolved = _regular(path, label=label, private=private)
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise TargetedBatchExecutionError(f"{label} is unreadable") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise TargetedBatchExecutionError(f"{label} is too large")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                TargetedBatchExecutionError(f"invalid JSON constant: {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TargetedBatchExecutionError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise TargetedBatchExecutionError(f"{label} must be a JSON object")
    return raw, value


def _write_atomic(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise TargetedBatchExecutionError("output parent must not be a symlink")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.is_symlink():
            raise TargetedBatchExecutionError("output path must not be a symlink")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    _write_atomic(path, _canonical_bytes(payload))


def _new_output_dir(path: Path, *, label: str) -> Path:
    if path.is_symlink() or path.exists():
        raise TargetedBatchExecutionError(f"{label} must be absent")
    parent = path.parent.resolve(strict=True)
    if path.parent.is_symlink() or not parent.is_dir():
        raise TargetedBatchExecutionError(f"{label} parent is invalid")
    path.mkdir(mode=0o700)
    return path.resolve(strict=True)


def _absolute_future_path(path: Path, *, label: str, allow_existing: bool = False) -> Path:
    if not path.is_absolute():
        raise TargetedBatchExecutionError(f"{label} must be absolute")
    if path.is_symlink():
        raise TargetedBatchExecutionError(f"{label} must not be a symlink")
    if path.exists():
        if not allow_existing or not path.is_dir():
            raise TargetedBatchExecutionError(f"{label} already exists")
        return path.resolve(strict=True)
    parent = path.parent.resolve(strict=True)
    if path.parent.is_symlink() or not parent.is_dir():
        raise TargetedBatchExecutionError(f"{label} parent is invalid")
    return parent / path.name


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TargetedBatchExecutionError("clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise TargetedBatchExecutionError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise TargetedBatchExecutionError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _jsonl_rows(path: Path, *, label: str) -> tuple[bytes, list[dict]]:
    resolved = _regular(path, label=label)
    raw = resolved.read_bytes()
    rows = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(
                line.decode("utf-8"),
                object_pairs_hook=_strict_object,
                parse_constant=lambda item: (_ for _ in ()).throw(
                    TargetedBatchExecutionError(f"invalid JSON constant: {item}")
                ),
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TargetedBatchExecutionError(
                f"{label} has invalid JSON at line {line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise TargetedBatchExecutionError(
                f"{label} row {line_number} must be an object"
            )
        rows.append(row)
    return raw, rows


def _load_plan(
    *,
    plan_root: Path,
    expected_manifest_sha256: str,
    expected_plan_sha256: str,
) -> dict:
    if not SHA256_RE.fullmatch(str(expected_manifest_sha256 or "")) or not SHA256_RE.fullmatch(
        str(expected_plan_sha256 or "")
    ):
        raise TargetedBatchExecutionError("plan SHA-256 is invalid")
    root = _directory(plan_root, label="batch plan root", private=True)
    manifest_raw, manifest = _read_json(
        root / "batch-plan-manifest.json", label="batch plan manifest", private=True
    )
    if _sha256_bytes(manifest_raw) != expected_manifest_sha256:
        raise TargetedBatchExecutionError("batch plan manifest SHA-256 mismatch")
    prepared = _regular(root / "PREPARED", label="batch plan PREPARED", private=True)
    if prepared.read_text(encoding="ascii").strip() != expected_manifest_sha256:
        raise TargetedBatchExecutionError("batch plan PREPARED marker drift")
    plan_identity = manifest.get("batch_plan")
    parameters = manifest.get("parameters")
    counts = manifest.get("counts")
    if (
        manifest.get("schema_version") != PLAN_SCHEMA
        or manifest.get("status") != "PROPOSED_NOT_APPROVED"
        or manifest.get("approval") is not False
        or manifest.get("execution_ready") is not False
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or not isinstance(plan_identity, dict)
        or not isinstance(parameters, dict)
        or not isinstance(counts, dict)
        or parameters.get("max_concurrent_batches") != 1
        or parameters.get("exclusive_account_proof_required_per_batch") is not True
        or parameters.get("min_interval_ms") < 250
        or parameters.get("spacing_minutes") < 5
    ):
        raise TargetedBatchExecutionError("batch plan manifest contract drift")
    plan_path = root / str(plan_identity.get("path") or "")
    try:
        plan_path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise TargetedBatchExecutionError("batch plan path escapes root") from exc
    plan_raw, batches = _jsonl_rows(plan_path, label="batch plan")
    if (
        _sha256_bytes(plan_raw) != expected_plan_sha256
        or plan_identity.get("sha256") != expected_plan_sha256
        or plan_identity.get("size") != len(plan_raw)
        or plan_identity.get("rows") != len(batches)
        or counts.get("batches") != len(batches)
    ):
        raise TargetedBatchExecutionError("batch plan identity mismatch")
    total_seeds = 0
    total_ceiling = 0
    for ordinal, batch in enumerate(batches, 1):
        seed_identity = batch.get("seed_ledger")
        if (
            batch.get("schema_version") != PLAN_SCHEMA
            or batch.get("ordinal") != ordinal
            or batch.get("approval_status") != "proposed_not_approved"
            or not str(batch.get("batch_id") or "")
            or not isinstance(seed_identity, dict)
            or isinstance(batch.get("seed_count"), bool)
            or not isinstance(batch.get("seed_count"), int)
            or batch["seed_count"] < 1
            or isinstance(batch.get("request_ceiling"), bool)
            or not isinstance(batch.get("request_ceiling"), int)
            or batch["request_ceiling"] < 1
            or seed_identity.get("rows") != batch["seed_count"]
        ):
            raise TargetedBatchExecutionError(f"batch plan row {ordinal} contract drift")
        seed_path = root / str(seed_identity.get("path") or "")
        try:
            seed_path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise TargetedBatchExecutionError(
                f"batch {ordinal} seed path escapes plan root"
            ) from exc
        seed_raw, seed_rows = _jsonl_rows(seed_path, label=f"batch {ordinal} seed ledger")
        if (
            _sha256_bytes(seed_raw) != seed_identity.get("sha256")
            or len(seed_raw) != seed_identity.get("size")
            or len(seed_rows) != seed_identity.get("rows")
        ):
            raise TargetedBatchExecutionError(f"batch {ordinal} seed identity mismatch")
        total_seeds += batch["seed_count"]
        total_ceiling += batch["request_ceiling"]
    if counts.get("seeds") != total_seeds or counts.get("request_ceiling") != total_ceiling:
        raise TargetedBatchExecutionError("batch plan totals drift")
    return {
        "root": root,
        "manifest": manifest,
        "manifest_sha256": expected_manifest_sha256,
        "plan_sha256": expected_plan_sha256,
        "batches": batches,
    }


def _initial_ledger(plan: Mapping[str, object]) -> dict:
    manifest = plan["manifest"]
    assert isinstance(manifest, Mapping)
    counts = manifest["counts"]
    assert isinstance(counts, Mapping)
    return {
        "schema_version": LEDGER_SCHEMA,
        "plan_manifest_sha256": plan["manifest_sha256"],
        "batch_plan_sha256": plan["plan_sha256"],
        "batch_count": counts["batches"],
        "seed_count": counts["seeds"],
        "planned_request_ceiling": counts["request_ceiling"],
        "completed": [],
        "active": None,
    }


def _attempt_digest(attempt: Mapping[str, object]) -> str:
    return _sha256_bytes(_canonical_bytes(attempt))


def _validate_attempt(attempt: object, *, expected_number: int) -> None:
    if not isinstance(attempt, dict):
        raise TargetedBatchExecutionError("execution attempt must be an object")
    request_count = attempt.get("request_count")
    run_ceiling = attempt.get("run_request_ceiling")
    if (
        attempt.get("attempt_number") != expected_number
        or attempt.get("status") not in {"safe_stopped", "complete"}
        or not SHA256_RE.fullmatch(str(attempt.get("approval_manifest_sha256") or ""))
        or not SHA256_RE.fullmatch(str(attempt.get("proposal_manifest_sha256") or ""))
        or not SHA256_RE.fullmatch(str(attempt.get("exclusive_proof_sha256") or ""))
        or isinstance(run_ceiling, bool)
        or not isinstance(run_ceiling, int)
        or run_ceiling < 1
        or isinstance(request_count, bool)
        or not isinstance(request_count, int)
        or request_count < 0
        or request_count > run_ceiling
        or attempt.get("attempt_sha256")
        != _attempt_digest({key: value for key, value in attempt.items() if key != "attempt_sha256"})
    ):
        raise TargetedBatchExecutionError("execution attempt identity is invalid")
    _parse_timestamp(attempt.get("finished_at"), label="attempt finished_at")


def _validate_completed_artifact(entry: Mapping[str, object]) -> None:
    output_dir = Path(str(entry.get("output_dir") or ""))
    root = _directory(output_dir, label="completed batch output", private=True)
    raw, manifest = _read_json(
        root / "batch-manifest.json", label="completed batch manifest", private=True
    )
    manifest_sha = _sha256_bytes(raw)
    complete = _regular(root / "COMPLETE", label="completed batch COMPLETE", private=True)
    if (
        manifest_sha != entry.get("batch_manifest_sha256")
        or complete.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != "targeted-horse-batch-run.v1"
        or manifest.get("status") not in {"complete", "complete_with_gaps"}
        or manifest.get("database_writes") != 0
        or not isinstance(manifest.get("seed_ledger"), dict)
        or manifest["seed_ledger"].get("sha256") != entry.get("seed_ledger_sha256")
        or manifest.get("planned_seed_count")
        != manifest.get("completed_seed_count", 0) + manifest.get("gap_seed_count", 0)
        or manifest.get("gap_seed_count", 0) != len(manifest.get("gaps", {}))
        or entry.get("completed_seed_count", manifest.get("completed_seed_count"))
        != manifest.get("completed_seed_count")
        or entry.get("gap_seed_count", manifest.get("gap_seed_count", 0))
        != manifest.get("gap_seed_count", 0)
    ):
        raise TargetedBatchExecutionError("completed batch artifact identity drift")


def _validate_ledger(ledger: dict, plan: Mapping[str, object]) -> None:
    expected = _initial_ledger(plan)
    for key, value in expected.items():
        if key not in {"completed", "active"} and ledger.get(key) != value:
            raise TargetedBatchExecutionError("execution ledger plan identity drift")
    completed = ledger.get("completed")
    if not isinstance(completed, list) or len(completed) > len(plan["batches"]):
        raise TargetedBatchExecutionError("execution ledger completed sequence is invalid")
    for ordinal, entry in enumerate(completed, 1):
        batch = plan["batches"][ordinal - 1]
        attempts = entry.get("attempts") if isinstance(entry, dict) else None
        if (
            not isinstance(entry, dict)
            or entry.get("ordinal") != ordinal
            or entry.get("batch_id") != batch.get("batch_id")
            or entry.get("seed_ledger_sha256") != batch["seed_ledger"].get("sha256")
            or not isinstance(attempts, list)
            or not attempts
            or attempts[-1].get("status") != "complete"
            or not SHA256_RE.fullmatch(str(entry.get("batch_manifest_sha256") or ""))
            or attempts[-1].get("batch_manifest_sha256")
            != entry.get("batch_manifest_sha256")
            or isinstance(entry.get("total_request_count"), bool)
            or not isinstance(entry.get("total_request_count"), int)
            or entry.get("total_request_count")
            != sum(attempt.get("request_count", -1) for attempt in attempts)
        ):
            raise TargetedBatchExecutionError("execution ledger completed sequence is invalid")
        for attempt_number, attempt in enumerate(attempts, 1):
            _validate_attempt(attempt, expected_number=attempt_number)
        _parse_timestamp(entry.get("completed_at"), label="batch completed_at")
        _validate_completed_artifact(entry)
    active = ledger.get("active")
    if active is None:
        return
    next_ordinal = len(completed) + 1
    if not 1 <= next_ordinal <= len(plan["batches"]):
        raise TargetedBatchExecutionError("execution ledger active batch is out of range")
    batch = plan["batches"][next_ordinal - 1]
    attempts = active.get("attempts") if isinstance(active, dict) else None
    if (
        not isinstance(active, dict)
        or active.get("ordinal") != next_ordinal
        or active.get("batch_id") != batch.get("batch_id")
        or active.get("seed_ledger_sha256") != batch["seed_ledger"].get("sha256")
        or active.get("phase") not in {"running", "safe_stopped"}
        or not isinstance(attempts, list)
        or (active.get("phase") == "safe_stopped" and not attempts)
    ):
        raise TargetedBatchExecutionError("execution ledger active identity is invalid")
    for attempt_number, attempt in enumerate(attempts, 1):
        _validate_attempt(attempt, expected_number=attempt_number)
        if attempt.get("status") != "safe_stopped":
            raise TargetedBatchExecutionError("active attempt history must be safe-stopped")
    if active["phase"] == "running":
        if (
            not re.fullmatch(r"[0-9a-f]{32}", str(active.get("claim_token") or ""))
            or active.get("attempt_number") != len(attempts) + 1
            or not SHA256_RE.fullmatch(str(active.get("approval_manifest_sha256") or ""))
            or not SHA256_RE.fullmatch(str(active.get("proposal_manifest_sha256") or ""))
            or not SHA256_RE.fullmatch(str(active.get("exclusive_proof_sha256") or ""))
        ):
            raise TargetedBatchExecutionError("running claim identity is invalid")
        _parse_timestamp(active.get("claimed_at"), label="claim claimed_at")


class _LedgerWindow:
    def __init__(self, ledger_path: Path, plan: Mapping[str, object]):
        self.ledger_path = ledger_path
        self.plan = plan
        self.lock_path = ledger_path.with_suffix(ledger_path.suffix + ".lock")
        self.handle = None
        self.ledger = None

    def __enter__(self):
        parent = self.ledger_path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if parent.is_symlink() or stat.S_IMODE(parent.stat(follow_symlinks=False).st_mode) & 0o077:
            raise TargetedBatchExecutionError("execution ledger parent must be private")
        if self.lock_path.is_symlink():
            raise TargetedBatchExecutionError("execution ledger lock must not be a symlink")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.lock_path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        self.handle = os.fdopen(descriptor, "a+b", closefd=True)
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        if self.ledger_path.exists() or self.ledger_path.is_symlink():
            _, ledger = _read_json(
                self.ledger_path, label="execution ledger", private=True
            )
        else:
            ledger = _initial_ledger(self.plan)
            _write_json(self.ledger_path, ledger)
        _validate_ledger(ledger, self.plan)
        self.ledger = ledger
        return self

    def write(self) -> None:
        assert self.ledger is not None
        _validate_ledger(self.ledger, self.plan)
        _write_json(self.ledger_path, self.ledger)

    def __exit__(self, exc_type, exc, traceback):
        if self.handle is not None:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            finally:
                self.handle.close()


def _plan_parameters(plan: Mapping[str, object]) -> dict:
    parameters = plan["manifest"]["parameters"]
    return {
        "max_search_candidates": parameters["max_search_candidates"],
        "max_results_pages_per_horse": parameters["max_results_pages_per_horse"],
        "max_parent_profiles": parameters["max_parent_profiles"],
        "min_interval_ms": parameters["min_interval_ms"],
    }


def _plan_endpoint_kinds(plan: Mapping[str, object]) -> list[str]:
    """Derive the smallest endpoint scope authorized by the immutable plan."""

    parameters = plan["manifest"]["parameters"]
    search_requests = parameters.get("search_requests_per_seed")
    if search_requests is None:
        # Existing name-seed plans predate the explicit field and require search.
        return list(ALLOWED_ENDPOINT_KINDS)
    if isinstance(search_requests, bool) or not isinstance(search_requests, int):
        raise TargetedBatchExecutionError(
            "plan search-requests-per-seed must be a non-negative integer"
        )
    if search_requests < 0:
        raise TargetedBatchExecutionError(
            "plan search-requests-per-seed must be a non-negative integer"
        )
    if search_requests == 0:
        return [
            "horse_results",
            "horse_pro",
            "horse_standard_fallback_on_404",
        ]
    return list(ALLOWED_ENDPOINT_KINDS)


def _resume_ceiling(
    *,
    output_dir: Path,
    batch: Mapping[str, object],
    plan: Mapping[str, object],
    openapi_contract: Mapping[str, object],
) -> int:
    root = _directory(output_dir, label="resume output directory", private=True)
    _, definition = _read_json(root / "batch-definition.json", label="batch definition", private=True)
    _, checkpoint = _read_json(root / "checkpoint.json", label="batch checkpoint", private=True)
    parameters = _plan_parameters(plan)
    definition_parameters = definition.get("parameters")
    completed = checkpoint.get("completed")
    gaps = checkpoint.get("gaps", {})
    seeds = definition.get("seeds")
    if (
        definition.get("schema_version") != "targeted-horse-batch-definition.v1"
        or not isinstance(definition.get("seed_ledger"), dict)
        or definition["seed_ledger"].get("sha256") != batch["seed_ledger"].get("sha256")
        or definition_parameters
        != {
            "max_search_candidates": parameters["max_search_candidates"],
            "max_results_pages_per_horse": parameters["max_results_pages_per_horse"],
            "max_parent_profiles": parameters["max_parent_profiles"],
            "content_pool_schema_version": "racing-api-content-pool.v1",
            "openapi_contract": dict(openapi_contract),
        }
        or not isinstance(seeds, list)
        or len(seeds) != batch.get("seed_count")
        or checkpoint.get("schema_version") != "targeted-horse-batch-checkpoint.v1"
        or checkpoint.get("status") != "safe_stopped"
        or not isinstance(completed, dict)
        or not isinstance(gaps, dict)
        or set(completed) & set(gaps)
        or len(completed) + len(gaps) >= len(seeds)
    ):
        raise TargetedBatchExecutionError("resume checkpoint does not bind the planned batch")
    per_seed = plan["manifest"]["parameters"].get("per_seed_request_ceiling")
    if isinstance(per_seed, bool) or not isinstance(per_seed, int) or per_seed < 1:
        raise TargetedBatchExecutionError("plan per-seed request ceiling is invalid")
    remaining = (len(seeds) - len(completed) - len(gaps)) * per_seed
    if remaining < 1:
        raise TargetedBatchExecutionError("resume request ceiling is empty")
    return remaining


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
    if not IDENTIFIER_RE.fullmatch(str(credential_alias or "")) or not IDENTIFIER_RE.fullmatch(
        str(account_scope_id or "")
    ):
        raise TargetedBatchExecutionError("account identity is invalid")
    completed = ledger["completed"]
    active = ledger.get("active")
    ordinal = len(completed) + 1
    if not 1 <= ordinal <= len(plan["batches"]):
        raise TargetedBatchExecutionError("all planned batches are complete")
    batch = plan["batches"][ordinal - 1]
    if active is None:
        resume = False
        attempts = []
        output_path = _absolute_future_path(
            batch_output_dir, label="batch output directory", allow_existing=False
        )
        run_ceiling = batch["request_ceiling"]
    else:
        if active.get("phase") == "running":
            raise TargetedBatchExecutionError("a network batch is already running")
        attempts = active["attempts"]
        prior_request_count = sum(attempt["request_count"] for attempt in attempts)
        active_output = Path(str(active.get("output_dir") or ""))
        has_resume_checkpoint = (
            active_output.is_dir()
            and not active_output.is_symlink()
            and (active_output / "batch-definition.json").is_file()
            and (active_output / "checkpoint.json").is_file()
        )
        if has_resume_checkpoint:
            resume = True
            if str(batch_output_dir.resolve(strict=True)) != str(active_output.resolve(strict=True)):
                raise TargetedBatchExecutionError("resume output directory identity drift")
            output_path = batch_output_dir.resolve(strict=True)
            run_ceiling = _resume_ceiling(
                output_dir=output_path,
                batch=batch,
                plan=plan,
                openapi_contract=openapi_contract,
            )
        elif prior_request_count == 0:
            # claim 后、首个 request 前的本地失败没有可续跑 checkpoint。保留零请求 attempt，
            # 但要求新的输出目录、budget root、proposal、approval 和 proof，从 fresh run 重启。
            resume = False
            output_path = _absolute_future_path(
                batch_output_dir, label="replacement batch output directory", allow_existing=False
            )
            run_ceiling = batch["request_ceiling"]
        else:
            raise TargetedBatchExecutionError(
                "a request-consuming safe-stop requires an exact resume checkpoint"
            )
    budget_path = _absolute_future_path(
        account_budget_root, label="account budget root", allow_existing=False
    )
    prior_request_count = sum(attempt["request_count"] for attempt in attempts)
    seed_path = plan["root"] / batch["seed_ledger"]["path"]
    previous = completed[-1] if completed else None
    return {
        "plan": {
            "manifest_sha256": plan["manifest_sha256"],
            "batch_plan_sha256": plan["plan_sha256"],
        },
        "batch": {
            "batch_id": batch["batch_id"],
            "ordinal": batch["ordinal"],
            "country_region": batch["country_region"],
            "edition_year": batch["edition_year"],
            "seed_count": batch["seed_count"],
            "seed_ledger_path": str(seed_path.resolve(strict=True)),
            "seed_ledger_sha256": batch["seed_ledger"]["sha256"],
            "planned_request_ceiling": batch["request_ceiling"],
        },
        "run": {
            "attempt_number": len(attempts) + 1,
            "resume": resume,
            "output_dir": str(output_path),
            "request_ceiling": run_ceiling,
            "prior_request_count": prior_request_count,
            "cumulative_request_ceiling": prior_request_count + run_ceiling,
            "parameters": _plan_parameters(plan),
            "endpoint_kinds": _plan_endpoint_kinds(plan),
            "openapi_contract": dict(openapi_contract),
            "database_writes": 0,
        },
        "account": {
            "credential_alias": credential_alias,
            "scope_id": account_scope_id,
            "budget_root": str(budget_path),
            "exclusive_account_proof_required": True,
        },
        "prior_attempt_sha256": [attempt["attempt_sha256"] for attempt in attempts],
        "previous_completed_batch": (
            {
                "ordinal": previous["ordinal"],
                "batch_id": previous["batch_id"],
                "batch_manifest_sha256": previous["batch_manifest_sha256"],
                "completed_at": previous["completed_at"],
            }
            if previous
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
    openapi_contract = openapi_contract_manifest(
        load_openapi_fingerprint(
            openapi_fingerprint_path,
            approved_openapi_fingerprint_sha256,
        )
    )
    plan = _load_plan(
        plan_root=plan_root,
        expected_manifest_sha256=expected_plan_manifest_sha256,
        expected_plan_sha256=expected_batch_plan_sha256,
    )
    proposal_root = _new_output_dir(output_dir, label="G3 proposal output directory")
    try:
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
        manifest_path = proposal_root / "proposal-manifest.json"
        _write_json(manifest_path, proposal)
        proposal_sha = _sha256_path(manifest_path)
        _write_atomic(proposal_root / "PREPARED", f"{proposal_sha}\n".encode("ascii"))
        return {**proposal, "proposal_manifest_sha256": proposal_sha}
    except BaseException:
        if proposal_root.exists() and not any(proposal_root.iterdir()):
            proposal_root.rmdir()
        raise


def _load_proposal(root: Path, expected_sha256: str) -> tuple[dict, str]:
    if not SHA256_RE.fullmatch(str(expected_sha256 or "")):
        raise TargetedBatchExecutionError("proposal manifest SHA-256 is invalid")
    proposal_root = _directory(root, label="G3 proposal root", private=True)
    raw, proposal = _read_json(
        proposal_root / "proposal-manifest.json", label="G3 proposal manifest", private=True
    )
    if _sha256_bytes(raw) != expected_sha256:
        raise TargetedBatchExecutionError("proposal manifest SHA-256 mismatch")
    prepared = _regular(proposal_root / "PREPARED", label="G3 proposal PREPARED", private=True)
    if prepared.read_text(encoding="ascii").strip() != expected_sha256:
        raise TargetedBatchExecutionError("proposal PREPARED marker drift")
    if (
        proposal.get("schema_version") != PROPOSAL_SCHEMA
        or proposal.get("status") != "PROPOSED_NOT_APPROVED"
        or proposal.get("approval") is not False
        or proposal.get("execution_ready") is not False
        or proposal.get("network_requests") != 0
        or proposal.get("database_writes") != 0
        or not isinstance(proposal.get("scope"), dict)
    ):
        raise TargetedBatchExecutionError("proposal contract drift")
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
        raise TargetedBatchExecutionError(
            "approval requires approved_by and decision_source_reference"
        )
    approval_root = _new_output_dir(output_dir, label="G3 approval output directory")
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
    manifest_path = approval_root / "approval-manifest.json"
    _write_json(manifest_path, approval)
    approval_sha = _sha256_path(manifest_path)
    _write_atomic(approval_root / "COMPLETE", f"{approval_sha}\n".encode("ascii"))
    return {**approval, "approval_manifest_sha256": approval_sha}


def _load_approval(root: Path, expected_sha256: str) -> tuple[dict, str]:
    if not SHA256_RE.fullmatch(str(expected_sha256 or "")):
        raise TargetedBatchExecutionError("G3 approval SHA-256 is invalid")
    approval_root = _directory(root, label="G3 approval root", private=True)
    raw, approval = _read_json(
        approval_root / "approval-manifest.json", label="G3 approval manifest", private=True
    )
    if _sha256_bytes(raw) != expected_sha256:
        raise TargetedBatchExecutionError("G3 approval SHA-256 mismatch")
    complete = _regular(approval_root / "COMPLETE", label="G3 approval COMPLETE", private=True)
    if complete.read_text(encoding="ascii").strip() != expected_sha256:
        raise TargetedBatchExecutionError("G3 approval COMPLETE marker drift")
    if (
        approval.get("schema_version") != APPROVAL_SCHEMA
        or approval.get("status") != "approved"
        or approval.get("approval") is not True
        or approval.get("execution_ready") is not True
        or approval.get("network_requests_allowed") is not True
        or approval.get("database_writes") != 0
        or not SHA256_RE.fullmatch(str(approval.get("proposal_manifest_sha256") or ""))
        or not isinstance(approval.get("scope"), dict)
        or not str(approval.get("approved_by") or "").strip()
        or not str(approval.get("decision_source_reference") or "").strip()
    ):
        raise TargetedBatchExecutionError("G3 approval contract drift")
    _parse_timestamp(approval.get("approved_at"), label="G3 approval approved_at")
    return approval, expected_sha256


def _scope_matches(expected: Mapping[str, object], actual: Mapping[str, object]) -> bool:
    return _canonical_bytes(expected) == _canonical_bytes(actual)


def _load_execution_ledger_read_only(
    execution_ledger_path: Path,
    plan: Mapping[str, object],
) -> dict:
    """Load an existing execution ledger without creating a ledger or lock file."""

    _, ledger = _read_json(
        execution_ledger_path,
        label="execution ledger",
        private=True,
    )
    _validate_ledger(ledger, plan)
    return ledger


def _validate_approved_next_scope(
    *,
    plan: Mapping[str, object],
    ledger: Mapping[str, object],
    approval: Mapping[str, object],
    seed_ledger_path: Path,
    output_dir: Path,
    account_budget_root: Path,
    credential_alias: str,
    account_scope_id: str,
    account_scope_manifest_sha256: str,
    request_ceiling: int,
    account_request_ceiling: int,
    max_search_candidates: int,
    max_results_pages_per_horse: int,
    max_parent_profiles: int,
    openapi_fingerprint_path: Path,
    approved_openapi_fingerprint_sha256: str,
    openapi_contract: Mapping[str, object],
    resume: bool,
    now: datetime,
) -> dict:
    if ledger.get("active") is not None and ledger["active"].get("phase") == "running":
        raise TargetedBatchExecutionError("a network batch is already running")
    approval_scope = approval["scope"]
    account = approval_scope.get("account")
    run = approval_scope.get("run")
    batch = approval_scope.get("batch")
    if not all(isinstance(value, dict) for value in (account, run, batch)):
        raise TargetedBatchExecutionError("G3 approval scope is incomplete")
    expected_scope = _next_scope(
        plan=plan,
        ledger=ledger,
        batch_output_dir=output_dir,
        account_budget_root=account_budget_root,
        credential_alias=credential_alias,
        account_scope_id=account_scope_id,
        openapi_contract=openapi_contract,
    )
    if not _scope_matches(expected_scope, approval_scope):
        raise TargetedBatchExecutionError("G3 approval does not bind the next execution scope")
    proposal_sha = approval["proposal_manifest_sha256"]
    supplied = {
        "seed_ledger_path": str(seed_ledger_path.resolve(strict=True)),
        "output_dir": str(output_dir.resolve(strict=resume)),
        "account_budget_root": str(account_budget_root.resolve(strict=False)),
        "credential_alias": credential_alias,
        "account_scope_id": account_scope_id,
        "account_scope_manifest_sha256": account_scope_manifest_sha256,
        "request_ceiling": request_ceiling,
        "account_request_ceiling": account_request_ceiling,
        "max_search_candidates": max_search_candidates,
        "max_results_pages_per_horse": max_results_pages_per_horse,
        "max_parent_profiles": max_parent_profiles,
        "openapi_fingerprint_path": str(openapi_fingerprint_path.resolve(strict=True)),
        "approved_openapi_fingerprint_sha256": approved_openapi_fingerprint_sha256,
        "resume": resume,
    }
    expected_supplied = {
        "seed_ledger_path": batch["seed_ledger_path"],
        "output_dir": run["output_dir"],
        "account_budget_root": account["budget_root"],
        "credential_alias": account["credential_alias"],
        "account_scope_id": account["scope_id"],
        "account_scope_manifest_sha256": proposal_sha,
        "request_ceiling": run["request_ceiling"],
        "account_request_ceiling": run["request_ceiling"],
        "max_search_candidates": run["parameters"]["max_search_candidates"],
        "max_results_pages_per_horse": run["parameters"]["max_results_pages_per_horse"],
        "max_parent_profiles": run["parameters"]["max_parent_profiles"],
        "openapi_fingerprint_path": run["openapi_contract"]["fingerprint"]["path"],
        "approved_openapi_fingerprint_sha256": run["openapi_contract"]["fingerprint"]["sha256"],
        "resume": run["resume"],
    }
    if supplied != expected_supplied:
        raise TargetedBatchExecutionError("network command arguments drift from G3 approval")
    completed = ledger["completed"]
    if completed:
        spacing = timedelta(minutes=plan["manifest"]["parameters"]["spacing_minutes"])
        earliest = _parse_timestamp(
            completed[-1]["completed_at"], label="previous batch completed_at"
        ) + spacing
        if now < earliest:
            raise TargetedBatchExecutionError(
                f"next batch cannot start before {_timestamp(earliest)}"
            )
    return {
        "approval_scope": approval_scope,
        "account": account,
        "run": run,
        "batch": batch,
        "proposal_manifest_sha256": proposal_sha,
    }


def preflight_next_batch_execution(
    *,
    plan_root: Path,
    expected_plan_manifest_sha256: str,
    expected_batch_plan_sha256: str,
    execution_ledger_path: Path,
    approval_root: Path,
    approved_g3_manifest_sha256: str,
    seed_ledger_path: Path,
    output_dir: Path,
    account_budget_root: Path,
    credential_alias: str,
    account_scope_id: str,
    account_scope_manifest_sha256: str,
    request_ceiling: int,
    account_request_ceiling: int,
    max_search_candidates: int,
    max_results_pages_per_horse: int,
    max_parent_profiles: int,
    openapi_fingerprint_path: Path,
    approved_openapi_fingerprint_sha256: str,
    resume: bool,
    now: datetime | None = None,
) -> dict:
    """Validate the exact next command before obtaining proof or claiming the ledger."""

    clock = _utc_now(now)
    openapi_contract = openapi_contract_manifest(
        load_openapi_fingerprint(
            openapi_fingerprint_path,
            approved_openapi_fingerprint_sha256,
        )
    )
    plan = _load_plan(
        plan_root=plan_root,
        expected_manifest_sha256=expected_plan_manifest_sha256,
        expected_plan_sha256=expected_batch_plan_sha256,
    )
    approval, approval_sha = _load_approval(approval_root, approved_g3_manifest_sha256)
    ledger = _load_execution_ledger_read_only(execution_ledger_path, plan)
    validated = _validate_approved_next_scope(
        plan=plan,
        ledger=ledger,
        approval=approval,
        seed_ledger_path=seed_ledger_path,
        output_dir=output_dir,
        account_budget_root=account_budget_root,
        credential_alias=credential_alias,
        account_scope_id=account_scope_id,
        account_scope_manifest_sha256=account_scope_manifest_sha256,
        request_ceiling=request_ceiling,
        account_request_ceiling=account_request_ceiling,
        max_search_candidates=max_search_candidates,
        max_results_pages_per_horse=max_results_pages_per_horse,
        max_parent_profiles=max_parent_profiles,
        openapi_fingerprint_path=openapi_fingerprint_path,
        approved_openapi_fingerprint_sha256=approved_openapi_fingerprint_sha256,
        openapi_contract=openapi_contract,
        resume=resume,
        now=clock,
    )
    batch = validated["batch"]
    run = validated["run"]
    return {
        "schema_version": "racing-api-targeted-batch-next-preflight.v1",
        "status": "ready_for_fresh_exclusive_proof",
        "network_requests": 0,
        "database_writes": 0,
        "proof_loaded": False,
        "ledger_mutated": False,
        "approval_manifest_sha256": approval_sha,
        "proposal_manifest_sha256": validated["proposal_manifest_sha256"],
        "next_batch": {
            "ordinal": batch["ordinal"],
            "batch_id": batch["batch_id"],
            "seed_count": batch["seed_count"],
            "seed_ledger_sha256": batch["seed_ledger_sha256"],
            "request_ceiling": run["request_ceiling"],
            "output_dir": run["output_dir"],
            "account_budget_root": validated["account"]["budget_root"],
            "endpoint_kinds": run["endpoint_kinds"],
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
    seed_ledger_path: Path,
    output_dir: Path,
    account_budget_root: Path,
    credential_alias: str,
    account_scope_id: str,
    account_scope_manifest_sha256: str,
    request_ceiling: int,
    account_request_ceiling: int,
    max_search_candidates: int,
    max_results_pages_per_horse: int,
    max_parent_profiles: int,
    openapi_fingerprint_path: Path,
    approved_openapi_fingerprint_sha256: str,
    resume: bool,
    now: datetime | None = None,
) -> dict:
    clock = _utc_now(now)
    openapi_contract = openapi_contract_manifest(
        load_openapi_fingerprint(
            openapi_fingerprint_path,
            approved_openapi_fingerprint_sha256,
        )
    )
    plan = _load_plan(
        plan_root=plan_root,
        expected_manifest_sha256=expected_plan_manifest_sha256,
        expected_plan_sha256=expected_batch_plan_sha256,
    )
    approval, approval_sha = _load_approval(approval_root, approved_g3_manifest_sha256)
    with _LedgerWindow(execution_ledger_path, plan) as window:
        validated = _validate_approved_next_scope(
            plan=plan,
            ledger=window.ledger,
            approval=approval,
            seed_ledger_path=seed_ledger_path,
            output_dir=output_dir,
            account_budget_root=account_budget_root,
            credential_alias=credential_alias,
            account_scope_id=account_scope_id,
            account_scope_manifest_sha256=account_scope_manifest_sha256,
            request_ceiling=request_ceiling,
            account_request_ceiling=account_request_ceiling,
            max_search_candidates=max_search_candidates,
            max_results_pages_per_horse=max_results_pages_per_horse,
            max_parent_profiles=max_parent_profiles,
            openapi_fingerprint_path=openapi_fingerprint_path,
            approved_openapi_fingerprint_sha256=approved_openapi_fingerprint_sha256,
            openapi_contract=openapi_contract,
            resume=resume,
            now=clock,
        )
        account = validated["account"]
        run = validated["run"]
        batch = validated["batch"]
        proposal_sha = validated["proposal_manifest_sha256"]
        load_exclusive_account_proof(
            exclusive_proof_path,
            expected_sha256=exclusive_proof_sha256,
            credential_alias=credential_alias,
            scope_id=account_scope_id,
            scope_manifest_sha256=proposal_sha,
            now=clock,
        )
        prior_active = window.ledger.get("active")
        attempts = list(prior_active.get("attempts") or []) if prior_active else []
        claim_token = uuid.uuid4().hex
        window.ledger["active"] = {
            "ordinal": batch["ordinal"],
            "batch_id": batch["batch_id"],
            "seed_ledger_sha256": batch["seed_ledger_sha256"],
            "output_dir": run["output_dir"],
            "phase": "running",
            "attempt_number": run["attempt_number"],
            "attempts": attempts,
            "claim_token": claim_token,
            "approval_manifest_sha256": approval_sha,
            "proposal_manifest_sha256": proposal_sha,
            "exclusive_proof_sha256": exclusive_proof_sha256,
            "run_request_ceiling": run["request_ceiling"],
            "cumulative_request_ceiling": run["cumulative_request_ceiling"],
            "openapi_contract": run["openapi_contract"],
            "account_budget_root": account["budget_root"],
            "account_scope_id": account["scope_id"],
            "claimed_at": _timestamp(clock),
        }
        window.write()
        return dict(window.ledger["active"])


def _attempt_from_active(
    active: Mapping[str, object],
    *,
    status: str,
    request_count: int,
    finished_at: datetime,
    error_type: str = "",
    error_message: str = "",
    account_budget_state_sha256: str = "",
    batch_manifest_sha256: str = "",
) -> dict:
    if (
        isinstance(request_count, bool)
        or not isinstance(request_count, int)
        or request_count < 0
        or request_count > active["run_request_ceiling"]
    ):
        raise TargetedBatchExecutionError("attempt request count is invalid")
    attempt = {
        "attempt_number": active["attempt_number"],
        "status": status,
        "approval_manifest_sha256": active["approval_manifest_sha256"],
        "proposal_manifest_sha256": active["proposal_manifest_sha256"],
        "exclusive_proof_sha256": active["exclusive_proof_sha256"],
        "run_request_ceiling": active["run_request_ceiling"],
        "request_count": request_count,
        "finished_at": _timestamp(finished_at),
        "error_type": str(error_type or "")[:160],
        "error_message": str(error_message or "")[:500],
        "account_budget_state_sha256": account_budget_state_sha256,
        "batch_manifest_sha256": batch_manifest_sha256,
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
    account_budget_state_path: Path | None = None,
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
        ):
            raise TargetedBatchExecutionError("safe-stop requires the exact running claim")
        state_sha = ""
        if account_budget_state_path is not None and account_budget_state_path.exists():
            raw, state = _read_json(
                account_budget_state_path, label="account budget state", private=True
            )
            if (
                state.get("schema_version") != "racing-api-account-budget.v1"
                or state.get("scope_id") != active.get("account_scope_id")
                or state.get("scope_manifest_sha256")
                != active.get("proposal_manifest_sha256")
                or state.get("request_count") != request_count
            ):
                raise TargetedBatchExecutionError("account budget state does not bind safe-stop")
            state_sha = _sha256_bytes(raw)
        attempt = _attempt_from_active(
            active,
            status="safe_stopped",
            request_count=request_count,
            finished_at=clock,
            error_type=error_type,
            error_message=error_message,
            account_budget_state_sha256=state_sha,
        )
        attempts = [*active["attempts"], attempt]
        window.ledger["active"] = {
            "ordinal": active["ordinal"],
            "batch_id": active["batch_id"],
            "seed_ledger_sha256": active["seed_ledger_sha256"],
            "output_dir": active["output_dir"],
            "phase": "safe_stopped",
            "attempts": attempts,
        }
        window.write()
        return dict(window.ledger["active"])


def complete_batch_execution(
    *,
    plan_root: Path,
    expected_plan_manifest_sha256: str,
    expected_batch_plan_sha256: str,
    execution_ledger_path: Path,
    claim_token: str,
    batch_manifest_path: Path,
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
        ):
            raise TargetedBatchExecutionError("completion requires the exact running claim")
        output_root = Path(active["output_dir"]).resolve(strict=True)
        manifest_resolved = _regular(
            batch_manifest_path, label="targeted batch manifest", private=True
        )
        if manifest_resolved != output_root / "batch-manifest.json":
            raise TargetedBatchExecutionError("batch manifest path drift")
        raw, manifest = _read_json(
            manifest_resolved, label="targeted batch manifest", private=True
        )
        manifest_sha = _sha256_bytes(raw)
        complete = _regular(output_root / "COMPLETE", label="targeted batch COMPLETE", private=True)
        batch = plan["batches"][active["ordinal"] - 1]
        parameters = _plan_parameters(plan)
        expected_parameters = {
            "max_search_candidates": parameters["max_search_candidates"],
            "max_results_pages_per_horse": parameters["max_results_pages_per_horse"],
            "max_parent_profiles": parameters["max_parent_profiles"],
            "content_pool_schema_version": "racing-api-content-pool.v1",
            "openapi_contract": active["openapi_contract"],
        }
        request_count = manifest.get("request_count")
        if (
            complete.read_text(encoding="ascii").strip() != manifest_sha
            or manifest.get("schema_version") != "targeted-horse-batch-run.v1"
            or manifest.get("status") not in {"complete", "complete_with_gaps"}
            or manifest.get("database_writes") != 0
            or not isinstance(manifest.get("seed_ledger"), dict)
            or manifest["seed_ledger"].get("sha256") != active["seed_ledger_sha256"]
            or manifest.get("parameters") != expected_parameters
            or manifest.get("planned_seed_count") != batch["seed_count"]
            or manifest.get("completed_seed_count", 0)
            + manifest.get("gap_seed_count", 0)
            != batch["seed_count"]
            or manifest.get("gap_seed_count", 0)
            != len(manifest.get("gaps", {}))
            or manifest.get("request_ceiling") != active["run_request_ceiling"]
            or isinstance(request_count, bool)
            or not isinstance(request_count, int)
            or request_count < 0
            or request_count > active["run_request_ceiling"]
        ):
            raise TargetedBatchExecutionError("targeted batch manifest does not bind running claim")
        attempt = _attempt_from_active(
            active,
            status="complete",
            request_count=request_count,
            finished_at=clock,
            batch_manifest_sha256=manifest_sha,
        )
        attempts = [*active["attempts"], attempt]
        total_request_count = sum(row["request_count"] for row in attempts)
        if total_request_count > active["cumulative_request_ceiling"]:
            raise TargetedBatchExecutionError("cumulative request ceiling exceeded")
        completed_entry = {
            "ordinal": active["ordinal"],
            "batch_id": active["batch_id"],
            "seed_ledger_sha256": active["seed_ledger_sha256"],
            "output_dir": active["output_dir"],
            "attempts": attempts,
            "total_request_count": total_request_count,
            "batch_manifest_sha256": manifest_sha,
            "completed_seed_count": manifest.get("completed_seed_count", 0),
            "gap_seed_count": manifest.get("gap_seed_count", 0),
            "completed_at": _timestamp(clock),
        }
        window.ledger["completed"].append(completed_entry)
        window.ledger["active"] = None
        window.write()
        return completed_entry


def verify_execution_ledger(
    *,
    plan_root: Path,
    expected_plan_manifest_sha256: str,
    expected_batch_plan_sha256: str,
    execution_ledger_path: Path,
) -> dict:
    plan = _load_plan(
        plan_root=plan_root,
        expected_manifest_sha256=expected_plan_manifest_sha256,
        expected_plan_sha256=expected_batch_plan_sha256,
    )
    with _LedgerWindow(execution_ledger_path, plan) as window:
        if window.ledger.get("active") is not None or len(window.ledger["completed"]) != len(
            plan["batches"]
        ):
            raise TargetedBatchExecutionError("execution ledger is incomplete")
        return dict(window.ledger)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("prepare", "publish", "preflight", "claim", "safe-stop", "complete", "verify"),
    )
    parser.add_argument("--plan-root", type=Path)
    parser.add_argument("--plan-manifest-sha256")
    parser.add_argument("--batch-plan-sha256")
    parser.add_argument("--execution-ledger", type=Path)
    parser.add_argument("--batch-output-dir", type=Path)
    parser.add_argument("--account-budget-root", type=Path)
    parser.add_argument("--credential-alias")
    parser.add_argument("--account-scope-id")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--proposal-root", type=Path)
    parser.add_argument("--proposal-manifest-sha256")
    parser.add_argument("--approved-by")
    parser.add_argument("--decision-source-reference")
    parser.add_argument("--approval-root", type=Path)
    parser.add_argument("--approval-manifest-sha256")
    parser.add_argument("--exclusive-proof", type=Path)
    parser.add_argument("--exclusive-proof-sha256")
    parser.add_argument("--seed-ledger", type=Path)
    parser.add_argument("--account-scope-manifest-sha256")
    parser.add_argument("--request-ceiling", type=int)
    parser.add_argument("--account-request-ceiling", type=int)
    parser.add_argument("--max-search-candidates", type=int)
    parser.add_argument("--max-results-pages-per-horse", type=int)
    parser.add_argument("--max-parent-profiles", type=int)
    parser.add_argument("--openapi-fingerprint", type=Path)
    parser.add_argument("--approved-openapi-fingerprint-sha256")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--claim-token")
    parser.add_argument("--request-count", type=int)
    parser.add_argument("--error-type", default="")
    parser.add_argument("--error-message", default="")
    parser.add_argument("--account-budget-state", type=Path)
    parser.add_argument("--batch-manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    common = {
        "plan_root": args.plan_root,
        "expected_plan_manifest_sha256": args.plan_manifest_sha256,
        "expected_batch_plan_sha256": args.batch_plan_sha256,
        "execution_ledger_path": args.execution_ledger,
    }
    try:
        if args.action == "prepare":
            result = prepare_next_batch_g3_proposal(
                **common,
                batch_output_dir=args.batch_output_dir,
                account_budget_root=args.account_budget_root,
                credential_alias=args.credential_alias,
                account_scope_id=args.account_scope_id,
                openapi_fingerprint_path=args.openapi_fingerprint,
                approved_openapi_fingerprint_sha256=args.approved_openapi_fingerprint_sha256,
                output_dir=args.output_dir,
            )
        elif args.action == "publish":
            result = publish_batch_g3_approval(
                proposal_root=args.proposal_root,
                approved_proposal_manifest_sha256=args.proposal_manifest_sha256,
                approved_by=args.approved_by,
                decision_source_reference=args.decision_source_reference,
                output_dir=args.output_dir,
            )
        elif args.action == "preflight":
            result = preflight_next_batch_execution(
                **common,
                approval_root=args.approval_root,
                approved_g3_manifest_sha256=args.approval_manifest_sha256,
                seed_ledger_path=args.seed_ledger,
                output_dir=args.batch_output_dir,
                account_budget_root=args.account_budget_root,
                credential_alias=args.credential_alias,
                account_scope_id=args.account_scope_id,
                account_scope_manifest_sha256=args.account_scope_manifest_sha256,
                request_ceiling=args.request_ceiling,
                account_request_ceiling=args.account_request_ceiling,
                max_search_candidates=args.max_search_candidates,
                max_results_pages_per_horse=args.max_results_pages_per_horse,
                max_parent_profiles=args.max_parent_profiles,
                openapi_fingerprint_path=args.openapi_fingerprint,
                approved_openapi_fingerprint_sha256=args.approved_openapi_fingerprint_sha256,
                resume=args.resume,
            )
        elif args.action == "claim":
            result = claim_batch_execution(
                **common,
                approval_root=args.approval_root,
                approved_g3_manifest_sha256=args.approval_manifest_sha256,
                exclusive_proof_path=args.exclusive_proof,
                exclusive_proof_sha256=args.exclusive_proof_sha256,
                seed_ledger_path=args.seed_ledger,
                output_dir=args.batch_output_dir,
                account_budget_root=args.account_budget_root,
                credential_alias=args.credential_alias,
                account_scope_id=args.account_scope_id,
                account_scope_manifest_sha256=args.account_scope_manifest_sha256,
                request_ceiling=args.request_ceiling,
                account_request_ceiling=args.account_request_ceiling,
                max_search_candidates=args.max_search_candidates,
                max_results_pages_per_horse=args.max_results_pages_per_horse,
                max_parent_profiles=args.max_parent_profiles,
                openapi_fingerprint_path=args.openapi_fingerprint,
                approved_openapi_fingerprint_sha256=args.approved_openapi_fingerprint_sha256,
                resume=args.resume,
            )
        elif args.action == "safe-stop":
            result = mark_batch_safe_stopped(
                **common,
                claim_token=args.claim_token,
                request_count=args.request_count,
                error_type=args.error_type,
                error_message=args.error_message,
                account_budget_state_path=args.account_budget_state,
            )
        elif args.action == "complete":
            result = complete_batch_execution(
                **common,
                claim_token=args.claim_token,
                batch_manifest_path=args.batch_manifest,
            )
        else:
            result = verify_execution_ledger(**common)
    except (OSError, TypeError, TargetedBatchExecutionError, ValueError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

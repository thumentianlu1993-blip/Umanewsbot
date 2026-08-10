"""Bridge a reviewed participant completion batch into the P0 release chain.

The participant census tracks race occurrences, while the production profile
release chain operates on unique horse identities.  This module performs the
only permitted conversion between those contracts: it validates the frozen
batch index, active execution ledger and read-only completion manifest, then
deduplicates semantically identical provider identities without losing the
original occurrence evidence.

The output is a rolling-batch compatible *draft*.  It records the earlier
batch-inclusion approval only; module approval, mapping, release approval and
production writes remain in the existing guarded commands.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from stable.services.p0_horse_completion_batch import (
    BatchRunState,
    P0_HORSE_BATCH_MANIFEST_FILENAME,
    P0_HORSE_BATCH_SCHEMA_VERSION,
    P0HorseBatchError,
    _append_approvals_ledger,
    _manifest_sha256,
    adapter_config_fingerprint,
    load_batch_manifest,
)
from stable.services.p0_horse_production_apply import deterministic_identity_key


BRIDGE_SCHEMA = "p0-horse-participant-release-bridge.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VOLATILE_KEYS = {
    "candidate_key",
    "fetched_at",
    "official_start_count_verified_at",
    "source_fetched_at",
}


@contextmanager
def _execution_ledger_window(execution_ledger_path: str | Path):
    """Share the exact lock used by the participant execution ledger writer."""
    ledger = Path(execution_ledger_path)
    lock_path = ledger.with_suffix(ledger.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular(path: str | Path, *, label: str) -> tuple[bytes, Any]:
    file_path = Path(path)
    descriptor = -1
    try:
        descriptor = os.open(file_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise P0HorseBatchError(f"{label} must be a regular non-symlink file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        data = b"".join(chunks)
        payload = json.loads(data)
    except P0HorseBatchError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise P0HorseBatchError(f"{label} is unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return data, payload


def _read_jsonl_regular(path: str | Path, *, label: str) -> tuple[bytes, list[dict[str, Any]]]:
    file_path = Path(path)
    descriptor = -1
    try:
        descriptor = os.open(file_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise P0HorseBatchError(f"{label} must be a regular non-symlink file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        data = b"".join(chunks)
        rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    except P0HorseBatchError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise P0HorseBatchError(f"{label} is unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if any(not isinstance(row, dict) for row in rows):
        raise P0HorseBatchError(f"{label} rows must be objects")
    return data, rows


def _file_identity(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"path": str(path), "size_bytes": len(data), "sha256": _sha256(data)}


def _publish_without_clobber(
    staging: Path, destination: Path, *, ready_filename: str
) -> None:
    """Reserve the destination and publish its readiness marker last."""
    try:
        destination.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise P0HorseBatchError(
            "participant release bridge output already exists"
        ) from exc
    try:
        children = {child.name: child for child in staging.iterdir()}
        ready = children.pop(ready_filename, None)
        if ready is None or not ready.is_file():
            raise P0HorseBatchError("participant release bridge ready marker is missing")
        for name in sorted(children):
            os.replace(children[name], destination / name)
        os.replace(ready, destination / ready_filename)
        staging.rmdir()
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _semantic_payload(value: Any, *, depth: int = 0) -> Any:
    """Remove occurrence/timestamp evidence, retaining all profile semantics."""
    if isinstance(value, dict):
        if value.get("evidence_role") == "reviewed_candidate":
            return None
        return {
            key: normalized
            for key in sorted(value)
            if not (key == "candidate_key" and depth == 0)
            and key not in (_VOLATILE_KEYS - {"candidate_key"})
            and (normalized := _semantic_payload(value[key], depth=depth + 1))
            is not None
        }
    if isinstance(value, list):
        return [
            normalized
            for item in value
            if (normalized := _semantic_payload(item, depth=depth + 1)) is not None
        ]
    return value


def _identity(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("identity")
    if not isinstance(raw, dict):
        raise P0HorseBatchError("completed participant has no identity object")
    identity = {
        "horse_name": str(raw.get("horse_name") or "").strip(),
        "sire_name": str(raw.get("sire_name") or "").strip(),
        "dam_name": str(raw.get("dam_name") or "").strip(),
        "birth_year": raw.get("birth_year"),
    }
    if (
        not all(identity[field] for field in ("horse_name", "sire_name", "dam_name"))
        or not isinstance(identity["birth_year"], int)
        or isinstance(identity["birth_year"], bool)
    ):
        raise P0HorseBatchError("completed participant four-field identity is incomplete")
    return identity


def _provider_key(payload: dict[str, Any]) -> tuple[str, str]:
    raw = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    source_name = str(raw.get("source_name") or payload.get("source_name") or "").strip()
    external_id = str(
        raw.get("external_horse_id") or payload.get("external_horse_id") or ""
    ).strip()
    if not source_name or not external_id:
        raise P0HorseBatchError("completed participant provider identity is incomplete")
    return source_name, external_id


def _verified_at(payload: dict[str, Any]) -> datetime:
    career = payload.get("career_history")
    if not isinstance(career, dict):
        raise P0HorseBatchError("completed participant career history is missing")
    text = str(career.get("official_start_count_verified_at") or "").strip()
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise P0HorseBatchError(
            "completed participant official verification time is invalid"
        ) from exc
    if value.tzinfo is None:
        raise P0HorseBatchError(
            "completed participant official verification time must include timezone"
        )
    return value


def _validate_inputs(
    *,
    batch_index_path: str | Path,
    execution_ledger_path: str | Path,
    completion_manifest_path: str | Path,
    candidates_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    index_bytes, index = _read_regular(batch_index_path, label="participant batch index")
    ledger_bytes, ledger = _read_regular(
        execution_ledger_path, label="participant execution ledger"
    )
    completion_bytes, completion = _read_regular(
        completion_manifest_path, label="participant completion manifest"
    )
    candidate_bytes, rows = _read_jsonl_regular(
        candidates_path, label="participant completion candidates"
    )
    index_sha = _sha256(index_bytes)
    completion_sha = _sha256(completion_bytes)
    candidate_sha = _sha256(candidate_bytes)
    active = ledger.get("active")
    batches = index.get("batches")
    valid_index_entries = isinstance(batches, list) and all(
        isinstance(batch, dict)
        and isinstance(batch.get("row_count"), int)
        and not isinstance(batch.get("row_count"), bool)
        and batch["row_count"] >= 0
        for batch in batches
    )
    indexed_candidate_count = (
        sum(batch["row_count"] for batch in batches) if valid_index_entries else -1
    )
    if (
        index.get("artifact_type") != "p0_horse_participant_completion_batch_plan"
        or index.get("schema_version") != "p0-horse-participant-review-batch.v2"
        or not isinstance(batches, list)
        or not valid_index_entries
        or index.get("batch_count") != len(batches)
        or index.get("candidate_count") != indexed_candidate_count
        or any(
            not isinstance(batch, dict)
            or batch.get("ordinal") != expected_ordinal
            or not str(batch.get("path") or "")
            for expected_ordinal, batch in enumerate(batches, start=1)
        )
        or len({str(batch["path"]) for batch in batches}) != len(batches)
        or not _SHA256_RE.fullmatch(index_sha)
    ):
        raise P0HorseBatchError("participant batch index identity is invalid")
    if (
        ledger.get("artifact_type") != "p0_horse_participant_execution_ledger"
        or ledger.get("schema_version") != "p0-horse-participant-execution-ledger.v1"
        or ledger.get("batch_index_sha256") != index_sha
        or ledger.get("batch_count") != index.get("batch_count")
        or ledger.get("candidate_count") != index.get("candidate_count")
        or not isinstance(active, dict)
        or active.get("phase") != "prepared"
        or not _SHA256_RE.fullmatch(
            str(active.get("review_manifest_sha256") or "")
        )
        or active.get("completion_manifest_sha256") != completion_sha
        or not isinstance(ledger.get("completed"), list)
    ):
        raise P0HorseBatchError("participant execution ledger is not the active prepared batch")
    ordinal = active.get("ordinal")
    if (
        not isinstance(ordinal, int)
        or isinstance(ordinal, bool)
        or not 1 <= ordinal <= len(batches)
    ):
        raise P0HorseBatchError("participant execution ledger ordinal is invalid")
    completed = ledger["completed"]
    if len(completed) != ordinal - 1 or any(
        not isinstance(entry, dict)
        or entry.get("path") != batches[expected_ordinal - 1].get("path")
        or entry.get("ordinal") != expected_ordinal
        or any(
            not _SHA256_RE.fullmatch(str(entry.get(field) or ""))
            for field in (
                "review_manifest_sha256",
                "completion_manifest_sha256",
                "release_evidence_sha256",
                "apply_evidence_sha256",
                "verifier_evidence_sha256",
            )
        )
        for expected_ordinal, entry in enumerate(completed, start=1)
    ):
        raise P0HorseBatchError(
            "participant execution ledger completed sequence is invalid"
        )
    index_entry = batches[ordinal - 1]
    review_input = completion.get("review_manifest_input")
    contract = review_input.get("batch_contract") if isinstance(review_input, dict) else None
    membership = contract.get("batch_membership") if isinstance(contract, dict) else None
    summary = completion.get("summary")
    declared_candidate = (completion.get("files") or {}).get(
        Path(candidates_path).name
    )
    expected_keys = index_entry.get("candidate_keys") if isinstance(index_entry, dict) else None
    actual_keys = [str(row.get("candidate_key") or "") for row in rows]
    if (
        completion.get("artifact_type") != "p0_horse_completion_batch_manifest"
        or completion.get("schema_version")
        != "p0-horse-completion-batch-manifest.v1"
        or completion.get("read_only") is not True
        or completion.get("database_writes") != 0
        or not isinstance(summary, dict)
        or not isinstance(review_input, dict)
        or not isinstance(membership, dict)
        or not isinstance(declared_candidate, dict)
        or index_entry.get("path") != active.get("path")
        or index_entry.get("ordinal") != ordinal
        or membership.get("path") != active.get("path")
        or membership.get("ordinal") != ordinal
        or membership.get("index_sha256") != index_sha
        or review_input.get("sha256") != active.get("review_manifest_sha256")
        or summary.get("processed_count") != index_entry.get("row_count")
        or len(rows) != index_entry.get("row_count")
        or expected_keys != actual_keys
        or any(
            not key
            or row.get("region") != index_entry.get("region")
            or row.get("schema_version") != "p0-horse-completion.v1"
            or not isinstance(row.get("failure_reason"), list)
            for key, row in zip(actual_keys, rows)
        )
        or len(set(actual_keys)) != len(actual_keys)
        or declared_candidate.get("sha256") != candidate_sha
        or declared_candidate.get("size_bytes") != len(candidate_bytes)
    ):
        raise P0HorseBatchError("participant completion inputs do not bind the active batch")
    complete_count = sum(not bool(row.get("failure_reason")) for row in rows)
    blocked_count = len(rows) - complete_count
    if (
        summary.get("complete_candidate_count") != complete_count
        or summary.get("blocked_count") != blocked_count
    ):
        raise P0HorseBatchError("participant completion summary counts drifted")
    binding = {
        "schema_version": BRIDGE_SCHEMA,
        "source": {
            "batch_index": {"path": str(batch_index_path), "sha256": index_sha},
            "execution_ledger": {
                "path": str(execution_ledger_path),
                "sha256": _sha256(ledger_bytes),
            },
            "completion_manifest": {
                "path": str(completion_manifest_path),
                "sha256": completion_sha,
            },
            "completion_candidates": {
                "path": str(candidates_path),
                "sha256": candidate_sha,
                "size_bytes": len(candidate_bytes),
            },
            "review_manifest_sha256": active["review_manifest_sha256"],
        },
        "batch": {
            "path": active["path"],
            "ordinal": ordinal,
            "region": index_entry.get("region"),
            "occurrence_count": len(rows),
            "complete_occurrence_count": complete_count,
            "blocked_occurrence_count": blocked_count,
        },
    }
    return index, ledger, completion, rows, binding


def _deduplicate(
    rows: list[dict[str, Any]], *, region: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    complete = [row for row in rows if not row.get("failure_reason")]
    blocked = [row for row in rows if row.get("failure_reason")]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in complete:
        if row.get("region") != region:
            raise P0HorseBatchError("completed participant region drifted")
        groups.setdefault(_provider_key(row), []).append(row)
    canonical_rows: list[dict[str, Any]] = []
    occurrences: list[dict[str, Any]] = []
    identity_owners: dict[str, tuple[str, str]] = {}
    for provider_key in sorted(groups):
        group = groups[provider_key]
        identities = {_canonical_bytes(_identity(row)) for row in group}
        semantic = {_canonical_bytes(_semantic_payload(row)) for row in group}
        if len(identities) != 1 or len(semantic) != 1:
            raise P0HorseBatchError(
                "duplicate provider identity has conflicting participant content: "
                f"{provider_key[0]}:{provider_key[1]}"
            )
        identity = _identity(group[0])
        identity_key = deterministic_identity_key(identity)
        previous_provider = identity_owners.setdefault(identity_key, provider_key)
        if previous_provider != provider_key:
            raise P0HorseBatchError(
                "four-field identity is owned by multiple provider identities"
            )
        canonical = max(
            group,
            key=lambda row: (_verified_at(row), str(row.get("candidate_key") or "")),
        )
        occurrence_keys = sorted(str(row["candidate_key"]) for row in group)
        canonical = dict(canonical)
        canonical["participant_occurrence_keys"] = occurrence_keys
        canonical["participant_provider_identity"] = {
            "source_name": provider_key[0],
            "external_horse_id": provider_key[1],
        }
        canonical_rows.append(canonical)
        occurrences.append(
            {
                "provider_identity": canonical["participant_provider_identity"],
                "identity": identity,
                "identity_key": identity_key,
                "canonical_candidate_key": canonical["candidate_key"],
                "occurrence_candidate_keys": occurrence_keys,
                "occurrence_evidence": [
                    {
                        "candidate_key": str(row["candidate_key"]),
                        "reviewed_candidate_source_evidence": [
                            evidence
                            for evidence in row.get("source_evidence") or []
                            if isinstance(evidence, dict)
                            and evidence.get("evidence_role") == "reviewed_candidate"
                        ],
                    }
                    for row in sorted(
                        group, key=lambda item: str(item.get("candidate_key") or "")
                    )
                ],
            }
        )
    canonical_rows.sort(key=lambda row: deterministic_identity_key(_identity(row)))
    occurrences.sort(key=lambda row: row["identity_key"])
    blocked_rows = [
        {
            "candidate_key": str(row.get("candidate_key") or ""),
            "horse_name": str(row.get("horse_name") or ""),
            "region": str(row.get("region") or ""),
            "failure_reason": list(row.get("failure_reason") or []),
        }
        for row in blocked
    ]
    blocked_rows.sort(key=lambda row: row["candidate_key"])
    return canonical_rows, occurrences, blocked_rows


def prepare_participant_release_bridge(
    *,
    batch_index_path: str | Path,
    execution_ledger_path: str | Path,
    completion_manifest_path: str | Path,
    candidates_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Create an immutable rolling-compatible draft; never query or write DB."""
    with _execution_ledger_window(execution_ledger_path):
        return _prepare_participant_release_bridge_locked(
            batch_index_path=batch_index_path,
            execution_ledger_path=execution_ledger_path,
            completion_manifest_path=completion_manifest_path,
            candidates_path=candidates_path,
            output_dir=output_dir,
        )


def _prepare_participant_release_bridge_locked(
    *,
    batch_index_path: str | Path,
    execution_ledger_path: str | Path,
    completion_manifest_path: str | Path,
    candidates_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    index, _ledger, completion, rows, binding = _validate_inputs(
        batch_index_path=batch_index_path,
        execution_ledger_path=execution_ledger_path,
        completion_manifest_path=completion_manifest_path,
        candidates_path=candidates_path,
    )
    region = str(binding["batch"]["region"] or "")
    canonical_rows, occurrences, blocked_rows = _deduplicate(rows, region=region)
    binding["result"] = {
        "unique_identity_count": len(canonical_rows),
        "deduplicated_occurrence_count": sum(
            len(row["occurrence_candidate_keys"]) - 1 for row in occurrences
        ),
        "occurrences": occurrences,
        "blocked": blocked_rows,
    }
    destination = Path(output_dir)
    if destination.exists():
        raise P0HorseBatchError("participant release bridge output already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        artifact_dir = staging / "artifact"
        artifact_dir.mkdir()
        combined_path = artifact_dir / "combined_candidates.jsonl"
        combined_path.write_bytes(
            b"".join(_canonical_bytes(row) + b"\n" for row in canonical_rows)
        )
        binding_path = artifact_dir / "participant_source_binding.json"
        binding_path.write_bytes(_canonical_bytes(binding) + b"\n")
        blocked_path = artifact_dir / "participant_blockers.jsonl"
        blocked_path.write_bytes(
            b"".join(_canonical_bytes(row) + b"\n" for row in blocked_rows)
        )

        generated_at = str(completion.get("generated_at") or "")
        decision_reference = str(index.get("decision_reference") or "").strip()
        if not generated_at or not decision_reference:
            raise P0HorseBatchError(
                "participant completion time or decision reference is missing"
            )
        batch_approval_reviewer = "participant-batch-contract"
        manifest: dict[str, Any] = {
            "schema_version": P0_HORSE_BATCH_SCHEMA_VERSION,
            "batch_id": "",
            "status": "approved",
            "created_at": generated_at,
            "created_by": "participant-release-bridge",
            "parameters": {
                "participant_release_bridge": binding,
                "regions": [region],
                "profile_ids": [],
                "limit_per_region": len(canonical_rows),
                "include_complete": True,
                "allow_in_flight": True,
            },
            "adapter_config_fingerprint": adapter_config_fingerprint(),
            "regions": [region],
            "region_counts": {region: len(canonical_rows)},
            "horses": [
                {
                    "candidate_key": row["candidate_key"],
                    "region": region,
                    "horse_name": row.get("horse_name", ""),
                    "participant_occurrence_keys": row["participant_occurrence_keys"],
                    "provider_identity": row["participant_provider_identity"],
                }
                for row in canonical_rows
            ],
            "approval": {
                "reviewer": batch_approval_reviewer,
                "approved_at": generated_at,
                "note": decision_reference,
                "excluded_profile_ids": [],
            },
        }
        manifest["batch_sha256"] = _manifest_sha256(manifest)
        manifest["batch_id"] = f"p0batch-{manifest['batch_sha256'][:12]}"
        manifest_path = staging / P0_HORSE_BATCH_MANIFEST_FILENAME
        manifest_path.write_bytes(_canonical_bytes(manifest) + b"\n")
        state = BatchRunState.create(batch_id=manifest["batch_id"], run_dir=staging)
        state.stage = "prepared"
        state.completed_stages = ["prepare", "participant-bridge"]
        state.artifacts["participant_source_binding"] = {
            **_file_identity(binding_path),
            "path": "artifact/participant_source_binding.json",
        }
        state.artifacts["combined_candidates"] = {
            **_file_identity(combined_path),
            "path": "artifact/combined_candidates.jsonl",
        }
        state.write()
        _append_approvals_ledger(
            staging,
            {
                "event": "batch_approved",
                "batch_id": manifest["batch_id"],
                "batch_sha256": manifest["batch_sha256"],
                "reviewer": batch_approval_reviewer,
                "approved_at": generated_at,
                "note": decision_reference,
                "excluded_profile_ids": [],
            },
        )
        _publish_without_clobber(
            staging,
            destination,
            ready_filename=P0_HORSE_BATCH_MANIFEST_FILENAME,
        )
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    loaded = load_batch_manifest(destination / P0_HORSE_BATCH_MANIFEST_FILENAME)
    return {
        "output_dir": str(destination),
        "batch_manifest_path": str(destination / P0_HORSE_BATCH_MANIFEST_FILENAME),
        "batch_id": loaded["batch_id"],
        "batch_sha256": loaded["batch_sha256"],
        "region": region,
        "occurrence_count": len(rows),
        "unique_identity_count": len(canonical_rows),
        "blocked_occurrence_count": len(blocked_rows),
        "deduplicated_occurrence_count": binding["result"][
            "deduplicated_occurrence_count"
        ],
        "combined_candidates": _file_identity(
            destination / "artifact" / "combined_candidates.jsonl"
        ),
        "participant_source_binding": _file_identity(
            destination / "artifact" / "participant_source_binding.json"
        ),
        "module_review_status": "pending",
        "database_writes": 0,
    }

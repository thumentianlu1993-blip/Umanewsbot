from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from stable.models import (
    HistoricalBatchLock,
    HistoricalBatchPhase,
    HistoricalBatchRun,
    HistoricalBatchRunStatus,
    HistoricalRaceDetailImportLayer,
    HistoricalRaceDetailImportReceipt,
    HistoricalRaceDetailImportReceiptStatus,
    HistoricalRaceEventTarget,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventCandidateStatus,
    RaceEventDataCandidate,
    RaceEventModule,
)
from stable.services.historical_race_batches import materialize_historical_event, target_identity
from stable.services.historical_race_detail_sources import (
    PROVIDER_AUTHORITIES,
    SOURCE_NAME_TO_PROVIDER,
    apply_approved_detail_source,
)
from stable.services.historical_race_importer import (
    apply_authoritative_event_fields,
    apply_historical_target_candidate,
    historical_basic_fields_complete,
)
from stable.services.historical_race_inventory import InventoryValidationError


SCHEMA_VERSION = "2.0"
ARTIFACT_KIND = "historical_race_detail_source_bundle"
CHUNK_KIND = "historical_race_detail_source_bundle_chunk"
APPROVAL_KIND = "historical_race_detail_chunk_approval"
CURRENT_YEAR_CUTOFF = date(2026, 7, 15)
MAX_CHUNK_TARGETS = 250
SOURCE_PROVIDER_ALIASES = {"sporting_life": "uk_sportinglife"}
RUNNER_OWNER_TOKEN_ENV = "HISTORICAL_RUNNER_OWNER_TOKEN"
RUNNER_PLAN_PATH_ENV = "HISTORICAL_RUNNER_PLAN_PATH"
RUNNER_STEP_ID_ENV = "HISTORICAL_RUNNER_STEP_ID"
RUNNER_GLOBAL_LOCK_KEY = "global"


class HistoricalRaceDetailChunkError(ValueError):
    pass


@dataclass(frozen=True)
class ApprovedChunk:
    root: Path
    bundle_manifest: dict[str, Any]
    bundle_sha256: str
    chunk_root: Path
    chunk_manifest_path: Path
    chunk_manifest: dict[str, Any]
    chunk_sha256: str
    approval: dict[str, Any]
    approval_path: Path
    approval_sha256: str
    candidates_sha256: str
    rows: tuple[dict[str, Any], ...]

    @property
    def layer(self) -> str:
        return str(self.chunk_manifest["layer"])

    @property
    def target_ids(self) -> tuple[int, ...]:
        return tuple(int(row["pending_target"]["target_id"]) for row in self.rows)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _is_sha256(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "")))


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalRaceDetailChunkError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise HistoricalRaceDetailChunkError(f"{label} must be a JSON object")
    return payload, raw


def _load_jsonl(path: Path, label: str) -> tuple[list[dict[str, Any]], bytes]:
    try:
        raw = path.read_bytes()
        rows = []
        for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise HistoricalRaceDetailChunkError(
                    f"{label} line {line_number} must be an object"
                )
            rows.append(row)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalRaceDetailChunkError(f"{label} is unreadable") from exc
    return rows, raw


def _safe_path(root: Path, supplied: str | Path, label: str) -> Path:
    root = root.resolve(strict=True)
    raw = Path(supplied)
    lexical = raw if raw.is_absolute() else root / raw
    lexical = Path(lexical.absolute())
    try:
        relative = lexical.relative_to(root)
    except ValueError:
        # macOS exposes /var through /private/var. Accept that system-level alias
        # while continuing to reject symlinks inside the artifact tree.
        try:
            relative = lexical.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise HistoricalRaceDetailChunkError(f"{label} escapes bundle root") from exc
        lexical = root / relative
    relative_parts = relative.parts
    cursor = root
    for part in relative_parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise HistoricalRaceDetailChunkError(f"{label} must not contain symlinks")
    try:
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise HistoricalRaceDetailChunkError(f"{label} is missing or outside bundle root") from exc
    if not resolved.is_file():
        raise HistoricalRaceDetailChunkError(f"{label} must be a file")
    return resolved


def _verify_identity(root: Path, identity: Any, label: str) -> Path:
    if not isinstance(identity, dict) or set(("path", "sha256", "size")) - set(identity):
        raise HistoricalRaceDetailChunkError(f"{label} identity is invalid")
    path = _safe_path(root, str(identity["path"]), label)
    raw = path.read_bytes()
    try:
        expected_size = int(identity["size"])
    except (TypeError, ValueError) as exc:
        raise HistoricalRaceDetailChunkError(f"{label} identity is invalid") from exc
    if expected_size != len(raw) or identity["sha256"] != _sha256(raw):
        raise HistoricalRaceDetailChunkError(f"{label} identity changed")
    return path


def _require_exact_sha(actual: str, expected: str, label: str) -> None:
    if not _is_sha256(expected) or actual != expected:
        raise HistoricalRaceDetailChunkError(f"{label} SHA does not match")


def _parse_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise HistoricalRaceDetailChunkError(f"{label} is invalid") from exc


def validate_distance_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalRaceDetailChunkError("distance_text is empty")
    original = value
    normalized = unicodedata.normalize("NFKC", value).strip()
    compact_units = re.search(
        r"(?i)(?:\d+(?:\.\d+)?\s*km\b|\d+(?:\.\d+)?\s*m(?:\s*\d+(?:\.\d+)?\s*f)?(?:\s*\d+\s*y)?\b|\d+(?:\.\d+)?\s*f\b|\d+\s*y\b)",
        normalized,
    )
    word_units = re.search(r"(?i)\b(?:mile|miles|furlong|furlongs|yard|yards)\b", normalized)
    if not compact_units and not word_units:
        raise HistoricalRaceDetailChunkError(f"distance_text has no recognized unit: {original}")
    return original


def resolve_source_provider(source_name: Any, advertised_provider: Any) -> str:
    source_name = str(source_name or "").strip()
    advertised_provider = str(advertised_provider or "").strip()
    canonical_provider = SOURCE_NAME_TO_PROVIDER.get(source_name)
    normalized_advertised = SOURCE_PROVIDER_ALIASES.get(
        advertised_provider, advertised_provider
    )
    if (
        not canonical_provider
        or normalized_advertised != canonical_provider
        or canonical_provider not in PROVIDER_AUTHORITIES
    ):
        raise HistoricalRaceDetailChunkError("candidate source provider is not approved")
    return canonical_provider


def _validate_row_shape(row: dict[str, Any], *, layer: str, cutoff: date | None) -> int:
    pending = row.get("pending_target")
    if not isinstance(pending, dict):
        raise HistoricalRaceDetailChunkError("candidate pending_target is invalid")
    try:
        target_id = int(pending["target_id"])
        year = int(pending["year"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoricalRaceDetailChunkError("candidate target identity is invalid") from exc
    if target_id <= 0 or not _is_sha256(pending.get("target_sha256")):
        raise HistoricalRaceDetailChunkError("candidate target identity is invalid")
    if pending.get("resolution_status") != HistoricalRaceResolutionStatus.PENDING:
        raise HistoricalRaceDetailChunkError("candidate must bind a pending target")
    if not str(pending.get("series_key") or "").strip() or not str(pending.get("region") or "").strip():
        raise HistoricalRaceDetailChunkError("candidate series/region identity is invalid")
    if not _is_sha256(row.get("approved_inventory_artifact_sha256")):
        raise HistoricalRaceDetailChunkError("candidate approved inventory SHA is invalid")
    local_date = _parse_date(row.get("local_date"), "candidate local_date")
    if row.get("status") != "finished":
        raise HistoricalRaceDetailChunkError("candidate race is not finished")
    if layer == HistoricalRaceDetailImportLayer.HISTORICAL_THROUGH_2024:
        if year > 2024:
            raise HistoricalRaceDetailChunkError("historical chunk contains a post-2024 target")
    elif layer == HistoricalRaceDetailImportLayer.CURRENT_YEAR_DUE:
        if cutoff != CURRENT_YEAR_CUTOFF:
            raise HistoricalRaceDetailChunkError("current-year chunk cutoff is not 2026-07-15")
        if year != 2026 or local_date > cutoff:
            raise HistoricalRaceDetailChunkError("current-year target is outside the approved due window")
    else:
        raise HistoricalRaceDetailChunkError("chunk layer is invalid")
    validate_distance_text(row.get("distance_text"))
    modules = row.get("modules")
    results = modules.get("results") if isinstance(modules, dict) else None
    if not isinstance(results, dict) or results.get("is_complete") is not True or not isinstance(
        results.get("items"), list
    ) or not results["items"]:
        raise HistoricalRaceDetailChunkError("candidate results are not complete")
    source = row.get("source")
    if not isinstance(source, dict):
        raise HistoricalRaceDetailChunkError("candidate source is invalid")
    resolve_source_provider(source.get("name"), source.get("provider"))
    if not str(source.get("url") or "").strip():
        raise HistoricalRaceDetailChunkError("candidate source URL is missing")
    if not isinstance(row.get("calendar_evidence"), dict) or not isinstance(row.get("source_refs"), dict):
        raise HistoricalRaceDetailChunkError("candidate date/source evidence is incomplete")
    provenance = row.get("distance_provenance")
    if (
        not isinstance(provenance, dict)
        or not str(provenance.get("source") or "").strip()
        or provenance.get("source_url") != source.get("url")
    ):
        raise HistoricalRaceDetailChunkError("candidate distance provenance is incomplete")
    return target_id


def load_approved_chunk(
    *,
    bundle_dir: str | Path,
    chunk_manifest_path: str | Path,
    approval_path: str | Path,
    expected_bundle_sha256: str,
    expected_chunk_sha256: str,
    expected_approval_sha256: str,
    today: date | None = None,
) -> ApprovedChunk:
    supplied_root = Path(bundle_dir)
    if supplied_root.is_symlink():
        raise HistoricalRaceDetailChunkError("bundle root must not be a symlink")
    try:
        root = supplied_root.resolve(strict=True)
    except OSError as exc:
        raise HistoricalRaceDetailChunkError("bundle root is missing") from exc
    if not root.is_dir():
        raise HistoricalRaceDetailChunkError("bundle root is not a directory")
    bundle_path = _safe_path(root, "manifest.json", "bundle manifest")
    bundle_manifest, bundle_raw = _load_json(bundle_path, "bundle manifest")
    bundle_sha = _sha256(bundle_raw)
    _require_exact_sha(bundle_sha, expected_bundle_sha256, "bundle manifest")
    if bundle_manifest.get("artifact_kind") != ARTIFACT_KIND or bundle_manifest.get("schema_version") != SCHEMA_VERSION:
        raise HistoricalRaceDetailChunkError("bundle manifest contract is invalid")

    chunk_path = _safe_path(root, chunk_manifest_path, "chunk manifest")
    chunk_manifest, chunk_raw = _load_json(chunk_path, "chunk manifest")
    chunk_sha = _sha256(chunk_raw)
    _require_exact_sha(chunk_sha, expected_chunk_sha256, "chunk manifest")
    if chunk_manifest.get("artifact_kind") != CHUNK_KIND or chunk_manifest.get("schema_version") != SCHEMA_VERSION:
        raise HistoricalRaceDetailChunkError("chunk manifest contract is invalid")
    chunk_root = chunk_path.parent

    approval_file = _safe_path(root, approval_path, "chunk approval")
    approval, approval_raw = _load_json(approval_file, "chunk approval")
    approval_sha = _sha256(approval_raw)
    _require_exact_sha(approval_sha, expected_approval_sha256, "chunk approval")
    if approval.get("artifact_kind") != APPROVAL_KIND or approval.get("schema_version") != SCHEMA_VERSION:
        raise HistoricalRaceDetailChunkError("chunk approval contract is invalid")
    if approval.get("status") != "approved":
        raise HistoricalRaceDetailChunkError("chunk approval is not approved")
    if not str(approval.get("approved_by") or "").strip() or not str(approval.get("approved_at") or "").strip():
        raise HistoricalRaceDetailChunkError("chunk approval operator identity is incomplete")
    try:
        approved_at = datetime.fromisoformat(str(approval["approved_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HistoricalRaceDetailChunkError("chunk approval timestamp is invalid") from exc
    if approved_at.tzinfo is None:
        raise HistoricalRaceDetailChunkError("chunk approval timestamp must include a timezone")

    target_count = chunk_manifest.get("target_count")
    target_ids = chunk_manifest.get("target_ids")
    if (
        isinstance(target_count, bool)
        or not isinstance(target_count, int)
        or not 1 <= target_count <= MAX_CHUNK_TARGETS
        or not isinstance(target_ids, list)
        or len(target_ids) != target_count
        or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in target_ids)
        or target_ids != sorted(target_ids)
        or len(set(target_ids)) != len(target_ids)
    ):
        raise HistoricalRaceDetailChunkError("chunk target IDs are not stable and unique")

    layer = str(chunk_manifest.get("layer") or "")
    cutoff = (
        _parse_date(chunk_manifest.get("cutoff_date"), "chunk cutoff")
        if chunk_manifest.get("cutoff_date")
        else None
    )
    if layer == HistoricalRaceDetailImportLayer.CURRENT_YEAR_DUE:
        if (today or timezone.localdate()) < CURRENT_YEAR_CUTOFF:
            raise HistoricalRaceDetailChunkError("production date is before the approved cutoff")
    elif cutoff is not None:
        raise HistoricalRaceDetailChunkError("historical chunk must not carry a cutoff")

    candidates_identity = chunk_manifest.get("candidates")
    candidates_path = _verify_identity(chunk_root, candidates_identity, "chunk candidates")
    rows, candidate_raw = _load_jsonl(candidates_path, "chunk candidates")
    candidate_sha = _sha256(candidate_raw)
    if len(rows) != target_count:
        raise HistoricalRaceDetailChunkError("chunk candidate count does not match manifest")
    row_ids = [_validate_row_shape(row, layer=layer, cutoff=cutoff) for row in rows]
    if row_ids != target_ids:
        raise HistoricalRaceDetailChunkError("chunk candidate target order does not match manifest")

    artifacts = chunk_manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != target_count + 1:
        raise HistoricalRaceDetailChunkError("chunk artifact list is incomplete")
    artifact_by_path: dict[str, dict[str, Any]] = {}
    for index, identity in enumerate(artifacts):
        _verify_identity(chunk_root, identity, f"chunk artifact {index}")
        artifact_path = str(identity.get("path") or "")
        if not artifact_path or artifact_path in artifact_by_path:
            raise HistoricalRaceDetailChunkError("chunk artifact paths are duplicated")
        artifact_by_path[artifact_path] = identity
    if artifacts[0] != candidates_identity or candidates_identity.get("sha256") != candidate_sha:
        raise HistoricalRaceDetailChunkError("chunk candidate identity is inconsistent")
    source_paths = []
    for row in rows:
        approved = row.get("approved_source_cache_identity")
        if not isinstance(approved, dict):
            raise HistoricalRaceDetailChunkError("candidate approved source identity is missing")
        source_path = str(approved.get("path") or "")
        manifest_identity = artifact_by_path.get(source_path)
        if manifest_identity != approved or source_path == candidates_identity.get("path"):
            raise HistoricalRaceDetailChunkError("candidate approved source identity is not bound")
        if approved.get("source_url") != row["source"]["url"]:
            raise HistoricalRaceDetailChunkError("candidate approved source URL does not match")
        source_paths.append(source_path)
    if len(set(source_paths)) != target_count or set(source_paths) != set(artifact_by_path) - {
        str(candidates_identity["path"])
    }:
        raise HistoricalRaceDetailChunkError("chunk source/candidate conservation failed")

    chunk_id = str(chunk_manifest.get("chunk_id") or "")
    layers = bundle_manifest.get("layers")
    layer_summary = layers.get(layer) if isinstance(layers, dict) else None
    summaries = layer_summary.get("chunks") if isinstance(layer_summary, dict) else None
    matched = [summary for summary in summaries or [] if summary.get("chunk_id") == chunk_id]
    if len(matched) != 1:
        raise HistoricalRaceDetailChunkError("bundle does not bind this chunk exactly once")
    summary = matched[0]
    expected_chunk_relative = chunk_path.relative_to(root).as_posix()
    if (
        summary.get("manifest", {}).get("path") != expected_chunk_relative
        or summary.get("manifest", {}).get("sha256") != chunk_sha
        or summary.get("target_ids") != target_ids
        or summary.get("target_count") != target_count
        or summary.get("candidates", {}).get("sha256") != candidate_sha
    ):
        raise HistoricalRaceDetailChunkError("bundle chunk summary is inconsistent")
    approval_bindings = {
        "bundle_manifest_sha256": bundle_sha,
        "layer": layer,
        "cutoff_date": chunk_manifest.get("cutoff_date"),
        "chunk_id": chunk_id,
        "chunk_manifest_sha256": chunk_sha,
        "candidates_sha256": candidate_sha,
        "target_count": target_count,
        "target_ids": target_ids,
    }
    for key, expected in approval_bindings.items():
        if approval.get(key) != expected:
            raise HistoricalRaceDetailChunkError(f"chunk approval does not bind {key}")
    if bundle_manifest.get("approved_inventory_artifact_sha256") != rows[0].get(
        "approved_inventory_artifact_sha256"
    ) or any(
        row.get("approved_inventory_artifact_sha256")
        != bundle_manifest.get("approved_inventory_artifact_sha256")
        for row in rows
    ):
        raise HistoricalRaceDetailChunkError("chunk approved inventory identity is inconsistent")
    return ApprovedChunk(
        root=root,
        bundle_manifest=bundle_manifest,
        bundle_sha256=bundle_sha,
        chunk_root=chunk_root,
        chunk_manifest_path=chunk_path,
        chunk_manifest=chunk_manifest,
        chunk_sha256=chunk_sha,
        approval=approval,
        approval_path=approval_file,
        approval_sha256=approval_sha,
        candidates_sha256=candidate_sha,
        rows=tuple(rows),
    )


def _runner_secret_context() -> tuple[str, str, str]:
    owner_token = os.environ.get(RUNNER_OWNER_TOKEN_ENV, "")
    plan_path = os.environ.get(RUNNER_PLAN_PATH_ENV, "")
    step_id = os.environ.get(RUNNER_STEP_ID_ENV, "")
    if not owner_token:
        raise HistoricalRaceDetailChunkError("historical runner owner token is missing")
    if not plan_path or not step_id:
        raise HistoricalRaceDetailChunkError("historical runner private step context is missing")
    return owner_token, plan_path, step_id


def _option_values(argv: list[Any], option: str) -> list[str]:
    values: list[str] = []
    for index, value in enumerate(argv):
        if value == option and index + 1 < len(argv):
            values.append(str(argv[index + 1]))
        elif isinstance(value, str) and value.startswith(option + "="):
            values.append(value.split("=", 1)[1])
    return values


def _one_option(argv: list[Any], option: str) -> str:
    values = _option_values(argv, option)
    if len(values) != 1 or not values[0]:
        raise HistoricalRaceDetailChunkError(
            f"historical runner current step does not bind {option}"
        )
    return values[0]


def _path_within(path: Path, root: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise HistoricalRaceDetailChunkError(
            f"historical runner {label} is outside artifact root"
        ) from exc
    return resolved


def _validate_runner_step_binding(
    run: HistoricalBatchRun,
    *,
    purpose: str,
    chunk: ApprovedChunk | None = None,
    receipt_id: str = "",
) -> None:
    _owner_token, supplied_plan_path, supplied_step_id = _runner_secret_context()
    artifact_root = Path(run.artifact_root).resolve(strict=True)
    plan_path = _path_within(Path(supplied_plan_path), artifact_root, "plan")
    try:
        plan_raw = plan_path.read_bytes()
        plan = json.loads(plan_raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalRaceDetailChunkError("historical runner plan is unreadable") from exc
    if _sha256(plan_raw) != run.plan_sha256 or not isinstance(plan, dict):
        raise HistoricalRaceDetailChunkError("historical runner plan identity changed")
    if (
        plan.get("batch_id") != run.batch_id
        or plan.get("phase") != run.phase
        or Path(str(plan.get("artifact_root") or "")).resolve() != artifact_root
        or supplied_step_id != run.current_step
    ):
        raise HistoricalRaceDetailChunkError("historical runner current step identity mismatch")
    steps = plan.get("steps")
    matched = (
        [step for step in steps if isinstance(step, dict) and step.get("id") == supplied_step_id]
        if isinstance(steps, list)
        else []
    )
    if len(matched) != 1:
        raise HistoricalRaceDetailChunkError("historical runner current step is not in its plan")
    step = matched[0]
    argv = step.get("argv")
    if not isinstance(argv, list) or len(argv) < 3:
        raise HistoricalRaceDetailChunkError("historical runner current step argv is invalid")
    expected_command = {
        "apply": "import_historical_race_detail_chunk",
        "verify": "verify_historical_race_detail_chunk",
        "reconcile": "reconcile_historical_race_detail_receipt",
    }[purpose]
    if argv[2] != expected_command or _one_option(argv, "--runner-run-id") != run.run_id:
        raise HistoricalRaceDetailChunkError("historical runner current step command mismatch")
    if purpose == "reconcile":
        if _one_option(argv, "--receipt-id") != receipt_id:
            raise HistoricalRaceDetailChunkError("historical runner receipt binding mismatch")
        return
    if chunk is None:
        raise HistoricalRaceDetailChunkError("historical runner chunk binding is missing")
    chunk_root = _path_within(chunk.root, artifact_root, "chunk bundle")
    expected_paths = {
        "--bundle-dir": chunk_root,
        "--chunk-manifest": chunk.chunk_manifest_path,
        "--approval": chunk.approval_path,
    }
    for option, expected in expected_paths.items():
        supplied = Path(_one_option(argv, option))
        if option == "--bundle-dir":
            try:
                actual = supplied.resolve(strict=True)
            except OSError as exc:
                raise HistoricalRaceDetailChunkError("historical runner bundle path is missing") from exc
        else:
            actual = _path_within(supplied, artifact_root, option)
        if actual != expected.resolve(strict=True):
            raise HistoricalRaceDetailChunkError(
                f"historical runner current step does not bind {option}"
            )
    sha_bindings = {
        "--expected-bundle-sha256": chunk.bundle_sha256,
        "--expected-chunk-sha256": chunk.chunk_sha256,
        "--expected-approval-sha256": chunk.approval_sha256,
    }
    for option, expected in sha_bindings.items():
        if _one_option(argv, option) != expected:
            raise HistoricalRaceDetailChunkError(
                f"historical runner current step does not bind {option}"
            )
    declared = {
        _path_within(Path(str(item.get("path") or "")), artifact_root, "declared input"):
        str(item.get("sha256") or "")
        for item in step.get("inputs", [])
        if isinstance(item, dict)
    }
    required = {
        chunk.root / "manifest.json": chunk.bundle_sha256,
        chunk.chunk_manifest_path: chunk.chunk_sha256,
        chunk.approval_path: chunk.approval_sha256,
    }
    if any(declared.get(path.resolve(strict=True)) != sha for path, sha in required.items()):
        raise HistoricalRaceDetailChunkError("historical runner plan inputs do not bind this chunk")


def _validate_live_runner(
    run: HistoricalBatchRun,
    lock: HistoricalBatchLock,
    *,
    owner_token: str,
    purpose: str,
    chunk: ApprovedChunk | None = None,
    receipt_id: str = "",
) -> HistoricalBatchRun:
    owner_sha256 = _sha256(owner_token.encode("utf-8"))
    now = timezone.now()
    if (
        run.status != HistoricalBatchRunStatus.RUNNING
        or lock.locked_by_run_id != run.pk
        or not run.owner_token_sha256
        or owner_sha256 != run.owner_token_sha256
        or lock.owner_token_sha256 != owner_sha256
        or not lock.lease_expires_at
        or lock.lease_expires_at <= now
        or not run.lease_expires_at
        or run.lease_expires_at <= now
    ):
        raise HistoricalRaceDetailChunkError(
            "historical runner owner token or live global lease does not match"
        )
    if purpose in {"apply", "reconcile"}:
        if run.phase != HistoricalBatchPhase.APPLY or run.network_enabled or not run.write_enabled:
            raise HistoricalRaceDetailChunkError("chunk write requires an APPLY write-only runner")
    elif purpose == "verify":
        if run.phase != HistoricalBatchPhase.VERIFY:
            raise HistoricalRaceDetailChunkError("chunk verify requires a VERIFY runner")
        if run.network_enabled or run.write_enabled:
            raise HistoricalRaceDetailChunkError("chunk verify runner permissions are invalid")
    _validate_runner_step_binding(
        run,
        purpose=purpose,
        chunk=chunk,
        receipt_id=receipt_id,
    )
    return run


def _runner_gate(
    run_id: str,
    *,
    purpose: str,
    chunk: ApprovedChunk | None = None,
    receipt_id: str = "",
    lock_for_transaction: bool = False,
) -> HistoricalBatchRun:
    owner_token, _plan_path, _step_id = _runner_secret_context()
    try:
        if lock_for_transaction:
            lock = HistoricalBatchLock.objects.select_for_update().get(
                key=RUNNER_GLOBAL_LOCK_KEY
            )
            run = HistoricalBatchRun.objects.select_for_update().get(run_id=run_id)
        else:
            run = HistoricalBatchRun.objects.get(run_id=run_id)
            lock = HistoricalBatchLock.objects.get(key=RUNNER_GLOBAL_LOCK_KEY)
    except (HistoricalBatchRun.DoesNotExist, HistoricalBatchLock.DoesNotExist) as exc:
        raise HistoricalRaceDetailChunkError("historical runner lease is missing") from exc
    return _validate_live_runner(
        run,
        lock,
        owner_token=owner_token,
        purpose=purpose,
        chunk=chunk,
        receipt_id=receipt_id,
    )


def _merge_source_refs(existing: Any, incoming: Any) -> dict[str, Any]:
    if not isinstance(existing, dict) or not isinstance(incoming, dict):
        raise HistoricalRaceDetailChunkError("source_refs must be objects")
    merged = dict(existing)
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = value
        elif isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_source_refs(merged[key], value)
        elif merged[key] != value:
            raise HistoricalRaceDetailChunkError(f"existing source_refs conflict at {key}")
    return merged


def _fresh_target(target_id: int) -> HistoricalRaceEventTarget:
    return HistoricalRaceEventTarget.objects.select_related("race_series", "event").get(pk=target_id)


def _validate_pending_target(target: HistoricalRaceEventTarget, row: dict[str, Any]) -> None:
    pending = row["pending_target"]
    if target_identity(target)["target_sha256"] != pending["target_sha256"]:
        raise HistoricalRaceDetailChunkError(f"target {target.pk} changed after packaging")
    if target.artifact_sha256 != row["approved_inventory_artifact_sha256"]:
        raise HistoricalRaceDetailChunkError(f"target {target.pk} inventory identity changed")
    if (
        target.resolution_status != HistoricalRaceResolutionStatus.PENDING
        or target.event_id is not None
        or target.race_series.key != pending["series_key"]
        or target.year != int(pending["year"])
        or target.country_region != pending["region"]
    ):
        raise HistoricalRaceDetailChunkError(f"target {target.pk} is not pending and unmaterialized")


def _set_approved_basic_fields(target: HistoricalRaceEventTarget, row: dict[str, Any]) -> None:
    local_date = _parse_date(row["local_date"], "candidate local_date")
    distance_text = validate_distance_text(row["distance_text"])
    if target.local_date and target.local_date != local_date:
        raise HistoricalRaceDetailChunkError(f"target {target.pk} local_date conflicts with approval")
    # _validate_pending_target has already bound the current expression to the
    # approved pending-target SHA; the approved source text may promote it.
    target.local_date = local_date
    target.distance_text = distance_text
    target.source_refs = _merge_source_refs(target.source_refs or {}, row["source_refs"])
    target.resolution_status = HistoricalRaceResolutionStatus.READY
    target.save(update_fields={"local_date", "distance_text", "source_refs", "resolution_status"})


def _detail_source_row(
    *, target: HistoricalRaceEventTarget, event: RaceEvent, row: dict[str, Any]
) -> dict[str, Any]:
    source = row["source"]
    provider = resolve_source_provider(source["name"], source["provider"])
    return {
        "target_id": target.pk,
        "expected_target_sha256": target_identity(target)["target_sha256"],
        "inventory_artifact_sha256": target.artifact_sha256,
        "year": target.year,
        "slug": event.slug,
        "source_name": source["name"],
        "source_url": source["url"],
        "source_provider": provider,
        "source_authority": PROVIDER_AUTHORITIES[provider],
        "redirect_chain": [],
        "source_cache_identity": row["approved_source_cache_identity"],
    }


def _distance_candidate(row: dict[str, Any]) -> dict[str, Any]:
    source = row["source"]
    provenance = row["distance_provenance"]
    provider = resolve_source_provider(source["name"], source["provider"])
    return {
        "source_authority": PROVIDER_AUTHORITIES[provider],
        "source_id": source["name"],
        "source_url": source["url"],
        "snapshot_sha256": row["approved_source_cache_identity"]["sha256"],
        "parser_version": str(provenance["source"]),
        "fields": {"distance_text": row["distance_text"]},
    }


def _initial_payload(chunk: ApprovedChunk) -> dict[str, Any]:
    return {
        "target_ids": list(chunk.target_ids),
        "pending_targets": [
            {
                **row["pending_target"],
                "inventory_artifact_sha256": row["approved_inventory_artifact_sha256"],
            }
            for row in chunk.rows
        ],
        "chunk_payload": {
            "bundle_sha256": chunk.bundle_sha256,
            "chunk_sha256": chunk.chunk_sha256,
            "candidates_sha256": chunk.candidates_sha256,
        },
        "approval_identity": {
            "sha256": chunk.approval_sha256,
            "approved_by": chunk.approval["approved_by"],
            "approved_at": chunk.approval["approved_at"],
            "cutoff_date": chunk.approval.get("cutoff_date"),
        },
    }


def _build_started_receipt(chunk: ApprovedChunk, run: HistoricalBatchRun) -> HistoricalRaceDetailImportReceipt:
    receipt = HistoricalRaceDetailImportReceipt(
        receipt_id=HistoricalRaceDetailImportReceipt.build_receipt_id(
            layer=chunk.layer, chunk_sha256=chunk.chunk_sha256
        ),
        runner=run,
        layer=chunk.layer,
        bundle_sha256=chunk.bundle_sha256,
        chunk_sha256=chunk.chunk_sha256,
        target_count=len(chunk.rows),
        initial_payload=_initial_payload(chunk),
    )
    receipt.save()
    return receipt


def _existing_receipt(chunk: ApprovedChunk) -> HistoricalRaceDetailImportReceipt | None:
    receipt_id = HistoricalRaceDetailImportReceipt.build_receipt_id(
        layer=chunk.layer, chunk_sha256=chunk.chunk_sha256
    )
    receipt = HistoricalRaceDetailImportReceipt.objects.filter(receipt_id=receipt_id).first()
    if receipt and (
        receipt.bundle_sha256 != chunk.bundle_sha256
        or receipt.chunk_sha256 != chunk.chunk_sha256
        or receipt.layer != chunk.layer
        or receipt.initial_payload != _initial_payload(chunk)
    ):
        raise HistoricalRaceDetailChunkError("existing receipt identity does not match this artifact")
    return receipt


def _execute_chunk(chunk: ApprovedChunk, receipt: HistoricalRaceDetailImportReceipt) -> dict[str, Any]:
    actor = get_user_model().objects.filter(username=chunk.approval["approved_by"]).first()
    if actor is None:
        raise HistoricalRaceDetailChunkError("chunk approval operator does not exist")
    target_ids = list(chunk.target_ids)
    rows_by_id = {int(row["pending_target"]["target_id"]): row for row in chunk.rows}
    locked_targets = list(
        HistoricalRaceEventTarget.objects.select_for_update()
        .select_related("race_series")
        .filter(pk__in=target_ids)
        .order_by("pk")
    )
    if [target.pk for target in locked_targets] != target_ids:
        raise HistoricalRaceDetailChunkError("one or more chunk targets are missing")
    for target in locked_targets:
        _validate_pending_target(target, rows_by_id[target.pk])

    pairs = {(target.race_series_id, target.year) for target in locked_targets}
    potential_events = list(
        RaceEvent.objects.select_for_update()
        .filter(race_series_id__in={pair[0] for pair in pairs}, year__in={pair[1] for pair in pairs})
        .order_by("pk")
    )
    conflicts = [event for event in potential_events if (event.race_series_id, event.year) in pairs]
    if conflicts:
        raise HistoricalRaceDetailChunkError("chunk has an existing RaceEvent conflict")

    target_reports = []
    total_runners = 0
    total_results = 0
    for target in locked_targets:
        row = rows_by_id[target.pk]
        pending_sha = row["pending_target"]["target_sha256"]
        _set_approved_basic_fields(target, row)
        event = materialize_historical_event(target, actor=actor)
        if event is None:
            raise HistoricalRaceDetailChunkError(f"target {target.pk} did not materialize")
        event = RaceEvent.objects.select_for_update().get(pk=event.pk)
        target = _fresh_target(target.pk)
        after_materialize_sha = target_identity(target)["target_sha256"]

        source_change = apply_approved_detail_source(
            target=target,
            event=event,
            row=_detail_source_row(target=target, event=event, row=row),
            artifact_root=chunk.chunk_root,
            artifact_manifest_sha256=chunk.bundle_sha256,
            approved_by=chunk.approval["approved_by"],
            approved_at=chunk.approval["approved_at"],
        )
        field_report = apply_authoritative_event_fields(
            target_id=target.pk,
            artifact_sha256=chunk.candidates_sha256,
            candidates=[_distance_candidate(row)],
            actor=actor,
        )
        target = _fresh_target(target.pk)
        before_detail_sha = target_identity(target)["target_sha256"]
        previous_candidate_ids = set(
            event.data_candidates.values_list("pk", flat=True)
        )
        counts = apply_historical_target_candidate(
            target_id=target.pk,
            expected_target_sha256=before_detail_sha,
            inventory_artifact_sha256=target.artifact_sha256,
            source_name=row["source"]["name"],
            source_url=row["source"]["url"],
            modules=row["modules"],
            actor=actor,
        )
        applied_candidates = list(
            RaceEventDataCandidate.objects.filter(event=event)
            .exclude(pk__in=previous_candidate_ids)
            .order_by("pk")
        )
        if (
            len(applied_candidates) != 2
            or {candidate.module for candidate in applied_candidates}
            != {RaceEventModule.RUNNERS, RaceEventModule.RESULTS}
            or any(
                candidate.status != RaceEventCandidateStatus.APPLIED
                for candidate in applied_candidates
            )
        ):
            raise HistoricalRaceDetailChunkError(
                f"target {target.pk} did not create exactly two applied detail candidates"
            )
        candidate_receipts = [
            {
                "id": candidate.pk,
                "module": candidate.module,
                "candidate_payload_sha256": _canonical_json_sha256(
                    candidate.candidate_payload
                ),
                "raw_provenance_sha256": _canonical_json_sha256(
                    candidate.raw_payload
                ),
            }
            for candidate in applied_candidates
        ]
        target = _fresh_target(target.pk)
        basic = historical_basic_fields_complete(target, target.event)
        if not basic["complete"]:
            raise HistoricalRaceDetailChunkError(
                f"target {target.pk} basic fields are incomplete: {basic['missing_fields']}"
            )
        after_import_sha = target_identity(target)["target_sha256"]
        total_runners += counts["runners"]
        total_results += counts["results"]
        target_reports.append(
            {
                "target_id": target.pk,
                "pending_target_sha256": pending_sha,
                "after_materialize_sha256": after_materialize_sha,
                "before_detail_sha256": before_detail_sha,
                "after_import_sha256": after_import_sha,
                "inventory_artifact_sha256": target.artifact_sha256,
                "runner_count": counts["runners"],
                "result_count": counts["results"],
                "basic_complete": True,
                "basic_missing_fields": [],
                "manual_locked_fields": field_report["skipped_manual"],
                "source_url": row["source"]["url"],
                "source_name": row["source"]["name"],
                "source_provider": resolve_source_provider(
                    row["source"]["name"], row["source"]["provider"]
                ),
                "source_cache_identity": row["approved_source_cache_identity"],
                "source_approval_before_sha256": source_change["before"],
                "source_approval_after_sha256": source_change["after"],
                "package_identity": row["package_identity"],
                "candidate_identity": row["candidate_identity"],
                "data_candidates": candidate_receipts,
            }
        )
    return {
        "bundle_sha256": chunk.bundle_sha256,
        "chunk_sha256": chunk.chunk_sha256,
        "approval_sha256": chunk.approval_sha256,
        "candidates_sha256": chunk.candidates_sha256,
        "target_count": len(target_reports),
        "runner_count": total_runners,
        "result_count": total_results,
        "targets": target_reports,
    }


def _artifact_kwargs(
    *,
    bundle_dir: str | Path,
    chunk_manifest_path: str | Path,
    approval_path: str | Path,
    expected_bundle_sha256: str,
    expected_chunk_sha256: str,
    expected_approval_sha256: str,
    today: date | None,
) -> ApprovedChunk:
    return load_approved_chunk(
        bundle_dir=bundle_dir,
        chunk_manifest_path=chunk_manifest_path,
        approval_path=approval_path,
        expected_bundle_sha256=expected_bundle_sha256,
        expected_chunk_sha256=expected_chunk_sha256,
        expected_approval_sha256=expected_approval_sha256,
        today=today,
    )


def import_historical_race_detail_chunk(
    *,
    bundle_dir: str | Path,
    chunk_manifest_path: str | Path,
    approval_path: str | Path,
    expected_bundle_sha256: str,
    expected_chunk_sha256: str,
    expected_approval_sha256: str,
    runner_run_id: str,
    dry_run: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    chunk = _artifact_kwargs(
        bundle_dir=bundle_dir,
        chunk_manifest_path=chunk_manifest_path,
        approval_path=approval_path,
        expected_bundle_sha256=expected_bundle_sha256,
        expected_chunk_sha256=expected_chunk_sha256,
        expected_approval_sha256=expected_approval_sha256,
        today=today,
    )
    run = _runner_gate(runner_run_id, purpose="apply", chunk=chunk)
    if not get_user_model().objects.filter(username=chunk.approval["approved_by"]).exists():
        raise HistoricalRaceDetailChunkError("chunk approval operator does not exist")
    existing = _existing_receipt(chunk)
    if existing:
        with transaction.atomic():
            _runner_gate(
                runner_run_id,
                purpose="apply",
                chunk=chunk,
                lock_for_transaction=True,
            )
            existing = HistoricalRaceDetailImportReceipt.objects.select_for_update().get(
                pk=existing.pk
            )
            if existing.status == HistoricalRaceDetailImportReceiptStatus.COMPLETED:
                report = _verify_chunk_state(chunk, existing)
                if report["error_count"]:
                    raise HistoricalRaceDetailChunkError(
                        "completed receipt replay verification failed"
                    )
                return {
                    "status": "replayed",
                    "receipt_id": existing.receipt_id,
                    "completion_payload": existing.completion_payload,
                    "verification": report,
                }
            raise HistoricalRaceDetailChunkError(
                f"receipt is not replayable: {existing.status}"
            )

    try:
        if dry_run:
            with transaction.atomic():
                run = _runner_gate(
                    runner_run_id,
                    purpose="apply",
                    chunk=chunk,
                    lock_for_transaction=True,
                )
                receipt = _build_started_receipt(chunk, run)
                receipt = HistoricalRaceDetailImportReceipt.objects.select_for_update().get(pk=receipt.pk)
                payload = _execute_chunk(chunk, receipt)
                receipt.status = HistoricalRaceDetailImportReceiptStatus.COMPLETED
                receipt.completed_at = timezone.now()
                receipt.completion_payload = payload
                receipt.save()
                transaction.set_rollback(True)
            return {
                "status": "dry_run",
                "target_count": payload["target_count"],
                "runner_count": payload["runner_count"],
                "result_count": payload["result_count"],
            }

        # A durable STARTED receipt survives a business rollback, but it is only
        # created after the private owner-token snapshot gate above succeeded.
        receipt = _build_started_receipt(chunk, run)
        with transaction.atomic():
            _runner_gate(
                runner_run_id,
                purpose="apply",
                chunk=chunk,
                lock_for_transaction=True,
            )
            receipt = HistoricalRaceDetailImportReceipt.objects.select_for_update().get(pk=receipt.pk)
            payload = _execute_chunk(chunk, receipt)
            receipt.status = HistoricalRaceDetailImportReceiptStatus.COMPLETED
            receipt.completed_at = timezone.now()
            receipt.completion_payload = payload
            receipt.save()
        return {
            "status": "completed",
            "receipt_id": receipt.receipt_id,
            "completion_payload": payload,
        }
    except HistoricalRaceDetailChunkError:
        raise
    except (InventoryValidationError, ValueError) as exc:
        raise HistoricalRaceDetailChunkError(str(exc)) from exc


def _approved_sources(target: HistoricalRaceEventTarget) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target_discovery = (target.source_refs or {}).get("detail_discovery") or {}
    event_discovery = (target.event.source_refs or {}).get("detail_discovery") or {}
    return (
        list(target_discovery.get("approved_detail_sources") or []),
        list(event_discovery.get("approved_detail_sources") or []),
    )


def _verify_chunk_state(
    chunk: ApprovedChunk, receipt: HistoricalRaceDetailImportReceipt
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    payload = receipt.completion_payload if isinstance(receipt.completion_payload, dict) else {}
    payload_rows = payload.get("targets") if isinstance(payload.get("targets"), list) else []
    expected_by_id = {
        int(row["pending_target"]["target_id"]): row for row in chunk.rows
    }
    receipt_by_id = {
        int(row.get("target_id") or 0): row for row in payload_rows if isinstance(row, dict)
    }
    if (
        receipt.status != HistoricalRaceDetailImportReceiptStatus.COMPLETED
        or receipt.bundle_sha256 != chunk.bundle_sha256
        or receipt.chunk_sha256 != chunk.chunk_sha256
        or payload.get("approval_sha256") != chunk.approval_sha256
        or payload.get("candidates_sha256") != chunk.candidates_sha256
        or set(receipt_by_id) != set(expected_by_id)
    ):
        errors.append({"scope": "receipt", "error": "receipt completion identity mismatch"})
    if (
        payload.get("target_count") != len(payload_rows)
        or payload.get("runner_count")
        != sum(int(row.get("runner_count") or 0) for row in payload_rows)
        or payload.get("result_count")
        != sum(int(row.get("result_count") or 0) for row in payload_rows)
    ):
        errors.append({"scope": "receipt", "error": "receipt aggregate counts mismatch"})
    targets = HistoricalRaceEventTarget.objects.select_related("race_series", "event").in_bulk(
        expected_by_id
    )
    for target_id in sorted(expected_by_id):
        row = expected_by_id[target_id]
        scope = receipt_by_id.get(target_id) or {}
        target = targets.get(target_id)
        target_errors = []
        if target is None or target.event is None:
            target_errors.append("target/event missing")
        else:
            if target.resolution_status != HistoricalRaceResolutionStatus.IMPORTED:
                target_errors.append("target not imported")
            if target_identity(target)["target_sha256"] != scope.get("after_import_sha256"):
                target_errors.append("after_import SHA mismatch")
            if scope.get("pending_target_sha256") != row["pending_target"]["target_sha256"]:
                target_errors.append("pending target SHA mismatch")
            if scope.get("inventory_artifact_sha256") != row["approved_inventory_artifact_sha256"]:
                target_errors.append("inventory SHA mismatch")
            if target.event.runners.count() != scope.get("runner_count"):
                target_errors.append("runner count mismatch")
            if target.event.results.count() != scope.get("result_count"):
                target_errors.append("result count mismatch")
            receipt_candidates = (
                scope.get("data_candidates")
                if isinstance(scope.get("data_candidates"), list)
                else []
            )
            receipt_candidate_ids = [
                item.get("id") for item in receipt_candidates if isinstance(item, dict)
            ]
            receipt_candidates_by_id = {
                item.get("id"): item
                for item in receipt_candidates
                if isinstance(item, dict) and isinstance(item.get("id"), int)
            }
            if (
                len(receipt_candidates) != 2
                or len(receipt_candidates_by_id) != 2
                or set(item.get("module") for item in receipt_candidates)
                != {RaceEventModule.RUNNERS, RaceEventModule.RESULTS}
            ):
                target_errors.append("receipt detail candidate identity mismatch")
            data_candidates = RaceEventDataCandidate.objects.in_bulk(
                receipt_candidate_ids
            )
            if set(data_candidates) != set(receipt_candidates_by_id):
                target_errors.append("receipt detail candidate missing")
            for candidate_id, candidate_scope in receipt_candidates_by_id.items():
                candidate = data_candidates.get(candidate_id)
                if candidate is None:
                    continue
                raw = candidate.raw_payload or {}
                if (
                    candidate.event_id != target.event_id
                    or candidate.status != RaceEventCandidateStatus.APPLIED
                    or candidate.module != candidate_scope.get("module")
                    or _canonical_json_sha256(candidate.candidate_payload)
                    != candidate_scope.get("candidate_payload_sha256")
                    or _canonical_json_sha256(raw)
                    != candidate_scope.get("raw_provenance_sha256")
                    or raw.get("historical_target_id") != target_id
                    or raw.get("target_sha256") != scope.get("before_detail_sha256")
                    or raw.get("inventory_artifact_sha256")
                    != row["approved_inventory_artifact_sha256"]
                    or (raw.get("source_cache_identity") or {}).get("sha256")
                    != row["approved_source_cache_identity"]["sha256"]
                ):
                    target_errors.append(
                        f"{candidate.module} receipt candidate provenance mismatch"
                    )
            basic = historical_basic_fields_complete(target, target.event)
            if not basic["complete"]:
                target_errors.append(f"basic incomplete: {basic['missing_fields']}")
            target_sources, event_sources = _approved_sources(target)
            expected_source = {
                "url": row["source"]["url"],
                "sha256": row["approved_source_cache_identity"]["sha256"],
                "provider": resolve_source_provider(
                    row["source"]["name"], row["source"]["provider"]
                ),
            }
            for owner, sources in (("target", target_sources), ("event", event_sources)):
                matching = [item for item in sources if item.get("url") == expected_source["url"]]
                if len(matching) != 1:
                    target_errors.append(f"{owner} approved source missing or duplicated")
                elif (
                    matching[0].get("artifact_manifest_sha256") != chunk.bundle_sha256
                    or matching[0].get("source_provider") != expected_source["provider"]
                    or matching[0].get("source_authority")
                    != PROVIDER_AUTHORITIES[expected_source["provider"]]
                    or matching[0].get("approved_by") != chunk.approval["approved_by"]
                    or matching[0].get("approved_at") != chunk.approval["approved_at"]
                    or (matching[0].get("source_cache_identity") or {}).get("sha256")
                    != expected_source["sha256"]
                ):
                    target_errors.append(f"{owner} approved source provenance mismatch")
        if target_errors:
            errors.append({"target_id": target_id, "errors": target_errors})
    return {
        "receipt_id": receipt.receipt_id,
        "target_count": len(expected_by_id),
        "checked_count": len(expected_by_id),
        "error_count": len(errors),
        "errors": errors,
    }


def verify_historical_race_detail_chunk(
    *,
    bundle_dir: str | Path,
    chunk_manifest_path: str | Path,
    approval_path: str | Path,
    expected_bundle_sha256: str,
    expected_chunk_sha256: str,
    expected_approval_sha256: str,
    runner_run_id: str,
    dry_run: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    del dry_run
    chunk = _artifact_kwargs(
        bundle_dir=bundle_dir,
        chunk_manifest_path=chunk_manifest_path,
        approval_path=approval_path,
        expected_bundle_sha256=expected_bundle_sha256,
        expected_chunk_sha256=expected_chunk_sha256,
        expected_approval_sha256=expected_approval_sha256,
        today=today,
    )
    with transaction.atomic():
        _runner_gate(
            runner_run_id,
            purpose="verify",
            chunk=chunk,
            lock_for_transaction=True,
        )
        receipt = _existing_receipt(chunk)
        if receipt is None or receipt.status != HistoricalRaceDetailImportReceiptStatus.COMPLETED:
            raise HistoricalRaceDetailChunkError("completed receipt is missing")
        return _verify_chunk_state(chunk, receipt)


def reconcile_historical_race_detail_receipt(
    *, receipt_id: str, runner_run_id: str, approved_by: str, reason: str
) -> dict[str, Any]:
    _runner_gate(
        runner_run_id,
        purpose="reconcile",
        receipt_id=receipt_id,
    )
    actor = get_user_model().objects.filter(username=approved_by).first()
    if actor is None or not reason.strip():
        raise HistoricalRaceDetailChunkError("receipt reconciliation approval is incomplete")
    with transaction.atomic():
        _runner_gate(
            runner_run_id,
            purpose="reconcile",
            receipt_id=receipt_id,
            lock_for_transaction=True,
        )
        try:
            receipt = HistoricalRaceDetailImportReceipt.objects.select_for_update().get(
                receipt_id=receipt_id
            )
        except HistoricalRaceDetailImportReceipt.DoesNotExist as exc:
            raise HistoricalRaceDetailChunkError("receipt does not exist") from exc
        if receipt.status != HistoricalRaceDetailImportReceiptStatus.STARTED:
            raise HistoricalRaceDetailChunkError("only STARTED receipt can be abandoned")
        target_ids = receipt.initial_payload.get("target_ids") or []
        pending_rows = receipt.initial_payload.get("pending_targets") or []
        pending_by_id = {
            int(row.get("target_id") or 0): row for row in pending_rows if isinstance(row, dict)
        }
        if set(pending_by_id) != set(target_ids):
            raise HistoricalRaceDetailChunkError("receipt pending target identities are incomplete")
        targets = list(
            HistoricalRaceEventTarget.objects.select_for_update()
            .select_related("race_series")
            .filter(pk__in=target_ids)
            .order_by("pk")
        )
        if [target.pk for target in targets] != sorted(target_ids):
            raise HistoricalRaceDetailChunkError("receipt targets are missing")
        if any(
            target.resolution_status != HistoricalRaceResolutionStatus.PENDING or target.event_id
            for target in targets
        ):
            raise HistoricalRaceDetailChunkError("receipt targets are mixed or already imported")
        for target in targets:
            pending = pending_by_id[target.pk]
            if (
                target_identity(target)["target_sha256"] != pending.get("target_sha256")
                or target.artifact_sha256 != pending.get("inventory_artifact_sha256")
                or target.race_series.key != pending.get("series_key")
                or target.year != int(pending.get("year") or 0)
                or target.country_region != pending.get("region")
            ):
                raise HistoricalRaceDetailChunkError("receipt target identity changed after STARTED")
        pairs = {(target.race_series_id, target.year) for target in targets}
        if any(
            (event.race_series_id, event.year) in pairs
            for event in RaceEvent.objects.select_for_update().filter(
                race_series_id__in={pair[0] for pair in pairs},
                year__in={pair[1] for pair in pairs},
            )
        ):
            raise HistoricalRaceDetailChunkError("related RaceEvent exists")
        if RaceEventDataCandidate.objects.filter(
            raw_payload__historical_target_id__in=target_ids
        ).exists():
            raise HistoricalRaceDetailChunkError("related data candidate exists")
        if OperationLog.objects.filter(
            target_type="historical_race_event_target", target_id__in=[str(value) for value in target_ids]
        ).exists():
            raise HistoricalRaceDetailChunkError("related operation log exists")
        receipt.status = HistoricalRaceDetailImportReceiptStatus.ABANDONED
        receipt.abandoned_at = timezone.now()
        receipt.abandoned_by = actor
        receipt.abandon_reason = reason.strip()
        receipt.reconcile_payload = {
            "verified_target_ids": sorted(target_ids),
            "approved_by": approved_by,
            "reason": reason.strip(),
        }
        receipt.save()
    return {"status": "abandoned", "receipt_id": receipt.receipt_id, "target_count": len(target_ids)}

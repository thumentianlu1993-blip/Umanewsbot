"""Rolling P0 horse completion batch selection, manifest, and approval gates.

This module productizes the batch layer of P0 horse profile completion:
queue-driven batch selection (replacing the fixed 50-row reviewed CSV),
a SHA-256 bound batch manifest with a human approval gate, and an
append-only approvals ledger. Network fetching, checkpoint/resume and the
commit chain live in dedicated modules; selection and approval here never
touch the network and never write profile data fields.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings

from stable.models import (
    HorseCompletionRunStatus,
    HorseP0Source,
    HorseP0SourceStatus,
    HorseProfileCompleteness,
    HorseProfileCompletionRun,
    RacingRegion,
)
from stable.services.p0_horse_completion_adapters import REGION_ADAPTERS
from stable.services.p0_horse_profiles import build_p0_completion_queue

P0_HORSE_BATCH_SCHEMA_VERSION = "p0-horse-completion-batch.v1"
P0_HORSE_BATCH_REGIONS: tuple[str, ...] = tuple(REGION_ADAPTERS.keys())
P0_HORSE_BATCH_MANIFEST_FILENAME = "batch_manifest.json"
P0_HORSE_BATCH_LEDGER_FILENAME = "approvals_ledger.jsonl"

_IN_FLIGHT_RUN_STATUSES = (
    HorseCompletionRunStatus.PLANNED,
    HorseCompletionRunStatus.RUNNING,
    HorseCompletionRunStatus.DRY_RUN,
)
_IN_FLIGHT_MANIFEST_STATUSES = ("pending", "approved")
_HTTP_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


class P0HorseBatchError(Exception):
    """Raised when a rolling batch operation must fail closed."""


def _region_batch_limit() -> int:
    return int(getattr(settings, "HORSE_PROFILE_COMPLETION_REGION_BATCH_LIMIT", 100))


def _total_batch_limit() -> int:
    return int(getattr(settings, "HORSE_PROFILE_COMPLETION_TOTAL_BATCH_LIMIT", 500))


def default_batch_state_dir() -> Path:
    configured = getattr(settings, "HORSE_PROFILE_COMPLETION_BATCH_STATE_DIR", "") or (
        "runtime/horse_profile_completion/batches"
    )
    return Path(configured)


def _utcnow_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _manifest_sha256(manifest: dict[str, Any]) -> str:
    # batch_id is derived from the hash itself, so it is excluded together
    # with the stored digest; everything else is content-bound.
    content = {
        key: value
        for key, value in manifest.items()
        if key not in ("batch_sha256", "batch_id")
    }
    return hashlib.sha256(_canonical_bytes(content)).hexdigest()


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(_canonical_bytes(payload) + b"\n")
    os.replace(tmp_path, path)


def _normalized_regions(regions: Iterable[str] | None) -> list[str]:
    if regions is None:
        return []
    normalized: list[str] = []
    for region in regions:
        value = str(region or "").strip()
        if not value:
            continue
        if value not in P0_HORSE_BATCH_REGIONS:
            raise P0HorseBatchError(f"unsupported P0 batch region: {value}")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _in_flight_profile_ids(state_dir: Path | None) -> set[int]:
    profile_ids: set[int] = set()
    runs = HorseProfileCompletionRun.objects.filter(
        status__in=_IN_FLIGHT_RUN_STATUSES,
    ).values_list("parameters", flat=True)
    for parameters in runs:
        batch = (parameters or {}).get("p0_batch") or {}
        for value in batch.get("profile_ids") or []:
            try:
                profile_ids.add(int(value))
            except (TypeError, ValueError):
                continue
    if state_dir is not None and state_dir.exists():
        for manifest_path in sorted(
            state_dir.glob(f"p0batch-*/{P0_HORSE_BATCH_MANIFEST_FILENAME}")
        ):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("status") not in _IN_FLIGHT_MANIFEST_STATUSES:
                continue
            for horse in data.get("horses") or []:
                try:
                    profile_ids.add(int(horse.get("profile_id")))
                except (TypeError, ValueError):
                    continue
    return profile_ids


def _profile_horse_name(profile) -> str:
    for value in (
        profile.original_name,
        profile.english_name,
        profile.japanese_name,
        profile.display_name_zh,
    ):
        text = str(value or "").strip()
        if text:
            return text
    term = getattr(profile, "primary_term", None)
    return str(getattr(term, "source_ja", "") or "").strip()


def _candidate_from_queue_item(
    item,
    *,
    include_complete: bool,
    allow_in_flight: bool,
    in_flight_ids: set[int],
) -> dict[str, Any] | None:
    profile = item.profile
    reasons = list(item.reasons)
    if profile.completeness_status == HorseProfileCompleteness.COMPLETE_PROFILE_FULL:
        if not include_complete:
            return None
        reasons.append("include_complete_override")
    if profile.pk in in_flight_ids:
        if not allow_in_flight:
            return None
        reasons.append("allow_in_flight_override")

    refs = profile.source_refs if isinstance(profile.source_refs, dict) else {}
    identity_keys: list[str] = []
    seen_keys: set[str] = set()

    def _add_identity_key(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in seen_keys:
            seen_keys.add(text)
            identity_keys.append(text)

    for key in refs.get("horse_identity_keys") or []:
        _add_identity_key(key)
    source_rows = HorseP0Source.objects.filter(
        id__in=item.source_ids,
        status=HorseP0SourceStatus.ACTIVE,
    ).values_list("evidence_payload", flat=True)
    for evidence in source_rows:
        for key in (evidence or {}).get("horse_identity_keys") or []:
            _add_identity_key(key)

    region_namespaces = REGION_ADAPTERS[item.region].source_names
    source_namespace = ""
    for key in identity_keys:
        namespace = key.split(":", 1)[0].strip()
        if namespace and namespace in region_namespaces:
            source_namespace = namespace
            break

    source_urls = [
        url
        for url in (refs.get("horse_source_urls") or [])
        if _HTTP_URL_RE.match(str(url or "").strip())
    ]
    has_external_id = bool(source_namespace) and any(
        key.startswith(f"{source_namespace}:") for key in identity_keys
    )

    candidate: dict[str, Any] = {
        "profile_id": profile.pk,
        "candidate_key": f"profile:{profile.pk}",
        "region": item.region,
        "sample_region": item.region,
        "horse_name": _profile_horse_name(profile),
        "identity_keys": identity_keys,
        "source_namespace": source_namespace,
        "source_urls": source_urls,
        "expected_sire_name": str(profile.sire_text or "").strip(),
        "expected_dam_name": str(profile.dam_text or "").strip(),
        "expected_birth_year": profile.birth_date.year if profile.birth_date else None,
        "queue_reasons": reasons,
        "p0_source_ids": list(item.source_ids),
    }
    if not has_external_id and not source_urls:
        candidate["identity_status"] = "needs_identity_enrichment"
    return candidate


def select_p0_horse_batch(
    *,
    regions: Iterable[str] | None = None,
    profile_ids: Iterable[int] | None = None,
    limit_per_region: int | None = None,
    include_complete: bool = False,
    allow_in_flight: bool = False,
    operator: str = "",
    state_dir: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a pending rolling-batch manifest from the P0 completion queue.

    Selection is read-only: it never writes profile data fields and never
    touches the network. Unbounded selection fails closed.
    """
    region_list = _normalized_regions(regions)
    profile_id_list = sorted({int(value) for value in profile_ids} if profile_ids else [])
    if not region_list and not profile_id_list and limit_per_region is None:
        raise P0HorseBatchError(
            "refusing unbounded batch selection: pass --regions/--profile-ids "
            "or an explicit --limit-per-region"
        )
    effective_limit = limit_per_region if limit_per_region is not None else _region_batch_limit()
    if effective_limit <= 0:
        raise P0HorseBatchError("limit_per_region must be greater than zero")
    scope_regions = region_list or list(P0_HORSE_BATCH_REGIONS)
    if effective_limit * len(scope_regions) > _total_batch_limit():
        raise P0HorseBatchError(
            "batch selection exceeds total batch limit "
            f"{_total_batch_limit()}: {effective_limit} x {len(scope_regions)} regions"
        )

    queue = build_p0_completion_queue(
        regions=region_list or None,
        profile_ids=profile_id_list or None,
        limit_per_region=None,
    )
    in_flight_ids = _in_flight_profile_ids(
        Path(state_dir) if state_dir is not None else None
    )

    horses: list[dict[str, Any]] = []
    for region in P0_HORSE_BATCH_REGIONS:
        region_items = queue.get(region, [])
        accepted = 0
        for item in region_items:
            if accepted >= effective_limit:
                break
            candidate = _candidate_from_queue_item(
                item,
                include_complete=include_complete,
                allow_in_flight=allow_in_flight,
                in_flight_ids=in_flight_ids,
            )
            if candidate is None:
                continue
            horses.append(candidate)
            accepted += 1

    region_counts: dict[str, int] = {}
    for horse in horses:
        region_counts[horse["region"]] = region_counts.get(horse["region"], 0) + 1

    manifest: dict[str, Any] = {
        "schema_version": P0_HORSE_BATCH_SCHEMA_VERSION,
        "batch_id": "",
        "status": "pending",
        "created_at": _utcnow_iso(now),
        "created_by": str(operator or "").strip(),
        "parameters": {
            "regions": region_list,
            "profile_ids": profile_id_list,
            "limit_per_region": effective_limit,
            "include_complete": include_complete,
            "allow_in_flight": allow_in_flight,
        },
        "regions": [
            region for region in P0_HORSE_BATCH_REGIONS if region_counts.get(region)
        ],
        "region_counts": region_counts,
        "horses": horses,
        "approval": None,
    }
    manifest["batch_sha256"] = _manifest_sha256(manifest)
    manifest["batch_id"] = f"p0batch-{manifest['batch_sha256'][:12]}"
    return manifest


def write_batch_manifest(
    manifest: dict[str, Any],
    *,
    state_dir: str | Path,
) -> Path:
    if manifest.get("schema_version") != P0_HORSE_BATCH_SCHEMA_VERSION:
        raise P0HorseBatchError("unsupported batch manifest schema version")
    if not manifest.get("batch_id"):
        raise P0HorseBatchError("batch manifest is missing batch_id")
    expected_sha = _manifest_sha256(manifest)
    if manifest.get("batch_sha256") != expected_sha:
        raise P0HorseBatchError("batch manifest SHA-256 does not match its content")
    batch_dir = Path(state_dir) / manifest["batch_id"]
    manifest_path = batch_dir / P0_HORSE_BATCH_MANIFEST_FILENAME
    _write_json_atomically(manifest_path, manifest)
    return manifest_path


def load_batch_manifest(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise P0HorseBatchError(f"batch manifest is unreadable: {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != P0_HORSE_BATCH_SCHEMA_VERSION:
        raise P0HorseBatchError("unsupported batch manifest schema version")
    if data.get("batch_sha256") != _manifest_sha256(data):
        raise P0HorseBatchError("batch manifest SHA-256 mismatch: content was modified")
    return data


def _append_approvals_ledger(batch_dir: Path, entry: dict[str, Any]) -> None:
    ledger_path = batch_dir / P0_HORSE_BATCH_LEDGER_FILENAME
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def approve_batch_manifest(
    manifest_path: str | Path,
    *,
    reviewer: str,
    note: str = "",
    excluded_profile_ids: Iterable[int] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    manifest = load_batch_manifest(manifest_path)
    reviewer_text = str(reviewer or "").strip()
    if not reviewer_text:
        raise P0HorseBatchError("batch approval requires a reviewer")
    if manifest.get("status") != "pending":
        raise P0HorseBatchError(
            f"batch manifest is not pending: {manifest.get('status')}"
        )
    excluded = sorted({int(value) for value in excluded_profile_ids})
    known_ids = {int(horse["profile_id"]) for horse in manifest["horses"]}
    unknown = sorted(set(excluded) - known_ids)
    if unknown:
        raise P0HorseBatchError(
            f"excluded profile ids not in batch: {unknown}"
        )
    if excluded:
        manifest["horses"] = [
            horse
            for horse in manifest["horses"]
            if int(horse["profile_id"]) not in excluded
        ]
        region_counts: dict[str, int] = {}
        for horse in manifest["horses"]:
            region_counts[horse["region"]] = region_counts.get(horse["region"], 0) + 1
        manifest["region_counts"] = region_counts
        manifest["regions"] = [
            region for region in P0_HORSE_BATCH_REGIONS if region_counts.get(region)
        ]
    approved_at = _utcnow_iso(now)
    manifest["approval"] = {
        "reviewer": reviewer_text,
        "approved_at": approved_at,
        "note": str(note or "").strip(),
        "excluded_profile_ids": excluded,
    }
    manifest["status"] = "approved"
    manifest["batch_sha256"] = _manifest_sha256(manifest)
    path = Path(manifest_path)
    _write_json_atomically(path, manifest)
    _append_approvals_ledger(
        path.parent,
        {
            "event": "batch_approved",
            "batch_id": manifest["batch_id"],
            "batch_sha256": manifest["batch_sha256"],
            "reviewer": reviewer_text,
            "approved_at": approved_at,
            "note": str(note or "").strip(),
            "excluded_profile_ids": excluded,
        },
    )
    return manifest


def validate_approved_batch_manifest(
    manifest_path: str | Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Fail-closed binding check used before any network prepare."""
    manifest = load_batch_manifest(manifest_path)
    if manifest.get("status") != "approved":
        raise P0HorseBatchError("batch manifest is not approved")
    approval = manifest.get("approval") or {}
    if not str(approval.get("reviewer") or "").strip():
        raise P0HorseBatchError("batch approval is missing reviewer")
    if not str(approval.get("approved_at") or "").strip():
        raise P0HorseBatchError("batch approval is missing approved_at")
    if expected_sha256 is not None and expected_sha256 != manifest["batch_sha256"]:
        raise P0HorseBatchError(
            "expected batch SHA-256 does not match the approved manifest"
        )
    ledger_path = Path(manifest_path).parent / P0_HORSE_BATCH_LEDGER_FILENAME
    ledger_match = False
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("batch_sha256") == manifest["batch_sha256"]:
                ledger_match = True
                break
    if not ledger_match:
        raise P0HorseBatchError(
            "batch approval ledger has no entry for the approved SHA-256"
        )
    return manifest

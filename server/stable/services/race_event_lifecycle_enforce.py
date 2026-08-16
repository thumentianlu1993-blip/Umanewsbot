"""Frozen full-cohort authorization registry for race lifecycle enforcement.

This module is deliberately provider-free.  It prepares immutable artifacts,
promotes them while lifecycle is closed, and authorizes one event at a time
through a database-backed active root and membership row.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone as django_timezone

from stable.models import (
    OperationLog,
    RaceEvent,
    RaceEventLifecycleControl,
    RaceEventLifecycleEnforceMembership,
    RaceEventLifecycleEnforceRegistry,
    RaceEventLifecycleMode,
    RaceEventStatus,
    RaceEventLifecycleTransition,
    RaceEventLifecycleTransitionKind,
)
from stable.services.race_event_lifecycle import _validate_timezone
from stable.services.race_event_lifecycle_enrollment import (
    _canonical_bytes,
    _parse_json,
    _schedule_hash,
)


SCHEMA_VERSION = 1
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
ALLOWED_SCOPES = frozenset(
    {"datetime_7d_canary", "datetime_30d", "no_time_canary", "full_eligible"}
)
SCOPE_STAGES = (
    "datetime_7d_canary", "datetime_30d", "no_time_canary", "full_eligible"
)
SUPPORTED_REGIONS = frozenset(
    {"japan", "hong_kong", "united_kingdom", "france", "united_states"}
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_ADVISORY_LOCK_KEY = 0x554D415245473031  # "UMAREG01"
_SQLITE_LOCK = threading.RLock()


class RegistryError(ValueError):
    """Fail-closed registry contract error."""


@dataclass(frozen=True)
class RegistryCensus:
    included_event_ids: tuple[int, ...]
    enrollment_required_event_ids: tuple[int, ...]
    successor_pending_event_ids: tuple[int, ...]
    inspected: int
    included: int
    blocked_by_reason: int
    blocked_by_scope: int
    reason_counts: dict[str, int]


@dataclass(frozen=True)
class LoadedRegistryManifest:
    data: dict[str, Any]
    raw: bytes
    raw_sha256: str
    content_sha256: str
    event_ids: tuple[int, ...]
    enrollment_sha_by_event: dict[int, str]
    predecessor_root_sha256: str


@dataclass(frozen=True)
class RegistryResult:
    outcome: str
    event_ids: tuple[int, ...]
    activation_id: str = ""
    total: int = 0
    remaining: int = 0


@dataclass(frozen=True)
class MembershipValidation:
    valid: bool
    reason_code: str = ""
    membership: RaceEventLifecycleEnforceMembership | None = None


def canonical_artifact_bytes(payload: dict[str, Any]) -> bytes:
    """Public canonical JSON encoder for registry-side read-only artifacts."""
    return _canonical_bytes(payload)


def _utc_iso(value: datetime) -> str:
    if not isinstance(value, datetime) or django_timezone.is_naive(value):
        raise RegistryError("datetime 必须为 aware")
    return value.astimezone(timezone.utc).isoformat()


def _parse_dt(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise RegistryError(f"{label} 必须为 ISO-8601")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RegistryError(f"{label} 非法") from exc
    if django_timezone.is_naive(parsed) or parsed.utcoffset() != timedelta(0):
        raise RegistryError(f"{label} 必须为 UTC aware datetime")
    return parsed


def scope_sha256(scope: dict[str, Any]) -> str:
    canonical = json.dumps(
        scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_registry_selector_scope(
    *,
    kind: str,
    cutoff: datetime,
    window_end: datetime | None,
    explicit_event_ids: list[int] | None = None,
    limit: int | None,
    predecessor_carry_forward: bool,
) -> dict[str, Any]:
    if kind not in ALLOWED_SCOPES:
        raise RegistryError("selector scope kind 非法")
    if django_timezone.is_naive(cutoff):
        raise RegistryError("cutoff 必须为 aware")
    ids = sorted(set(explicit_event_ids or []))
    if any(type(item) is not int or item <= 0 for item in ids):
        raise RegistryError("explicit_event_ids 必须为正整数")
    requires_datetime = kind in {"datetime_7d_canary", "datetime_30d"}
    if requires_datetime and window_end is None:
        raise RegistryError("datetime scope 必须提供 window_end")
    if window_end is not None and (
        django_timezone.is_naive(window_end) or window_end <= cutoff
    ):
        raise RegistryError("window_end 必须晚于 cutoff")
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise RegistryError("limit 必须为正整数")
    scope = {
        "kind": kind,
        "cutoff": _utc_iso(cutoff),
        "window_end": _utc_iso(window_end) if window_end else None,
        "start_inclusive": True,
        "end_inclusive": False,
        "require_datetime": requires_datetime,
        "explicit_event_ids": ids,
        "limit": limit,
        "order_by": ["race_datetime", "event_id"],
        "predecessor_carry_forward": bool(predecessor_carry_forward),
    }
    _validate_selector_scope(scope)
    return scope


def _eligibility_reason(
    event: RaceEvent,
    control: RaceEventLifecycleControl | None,
    *,
    allow_running: bool = False,
) -> str:
    if event.visibility_status != "published":
        return "not_published"
    if event.status != RaceEventStatus.SCHEDULED and not (
        allow_running and event.status == RaceEventStatus.RUNNING
    ):
        return "not_scheduled"
    if event.local_date is None:
        return "missing_local_date"
    if event.country_region not in SUPPORTED_REGIONS:
        return "unsupported_region"
    if event.manual_lock_flags:
        return "manual_lock"
    if event.race_datetime is not None and django_timezone.is_naive(event.race_datetime):
        return "naive_race_datetime"
    if control is None:
        # A missing control is an enrollment action, not an eligibility
        # exclusion.  The frozen census must retain the event so a nominal
        # full artifact cannot silently omit it.
        error = _validate_timezone(
            event.timezone_name, event.country_region, None
        )
        return "timezone_invalid" if error else ""
    if control.manual_pause_reason:
        return "manual_pause"
    if not _SHA_RE.fullmatch(control.enrollment_manifest_sha256 or ""):
        return "invalid_enrollment_provenance"
    if control.manifest_data.get("schema_version") != 2:
        return "invalid_enrollment_provenance"
    if control.manifest_data.get("enrollment_schedule_hash") != _schedule_hash(event):
        return "schedule_drift"
    zones = control.manifest_data.get("allowed_us_zones") or []
    if event.country_region == "united_states" and not zones:
        return "us_allowlist_missing"
    error = _validate_timezone(
        event.timezone_name,
        event.country_region,
        frozenset(zones) if event.country_region == "united_states" else None,
    )
    return "timezone_invalid" if error else ""


def select_registry_candidates(
    *, scope: dict[str, Any], predecessor_event_ids: list[int] | None = None
) -> RegistryCensus:
    _validate_selector_scope(scope)
    cutoff = _parse_dt(scope.get("cutoff"), "scope.cutoff")
    window_end = (
        _parse_dt(scope["window_end"], "scope.window_end")
        if scope.get("window_end")
        else None
    )
    events = list(RaceEvent.objects.all().order_by("id"))
    controls = {
        row.event_id: row
        for row in RaceEventLifecycleControl.objects.filter(
            event_id__in=[event.id for event in events]
        )
    }
    predecessors = set(predecessor_event_ids or [])
    carry_forward = bool(scope.get("predecessor_carry_forward"))
    successor: list[int] = []
    eligible: list[RaceEvent] = []
    reason_counts: dict[str, int] = {}
    inspected = 0
    for event in events:
        if event.updated_at > cutoff:
            successor.append(event.id)
            continue
        inspected += 1
        reason = _eligibility_reason(
            event,
            controls.get(event.id),
            allow_running=carry_forward and event.id in predecessors,
        )
        if reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        else:
            eligible.append(event)

    eligible_by_id = {event.id: event for event in eligible}
    carried = (
        [eligible_by_id[item] for item in sorted(predecessors) if item in eligible_by_id]
        if scope.get("predecessor_carry_forward")
        else []
    )
    kind = scope["kind"]
    explicit = set(scope.get("explicit_event_ids") or [])

    def in_scope(event: RaceEvent) -> bool:
        if event.id in predecessors and scope.get("predecessor_carry_forward"):
            return True
        if kind == "full_eligible":
            return True
        if kind == "no_time_canary":
            return event.race_datetime is None and event.id in explicit
        if event.race_datetime is None or window_end is None:
            return False
        race_at = event.race_datetime.astimezone(timezone.utc)
        return cutoff <= race_at < window_end

    scoped = [event for event in eligible if in_scope(event) and event.id not in predecessors]
    scoped.sort(
        key=lambda item: (
            item.race_datetime.astimezone(timezone.utc)
            if item.race_datetime is not None
            else datetime.max.replace(tzinfo=timezone.utc),
            item.id,
        )
    )
    limit = scope.get("limit")
    if limit is not None:
        if len(carried) > limit:
            raise RegistryError("predecessor 成员数超过 successor limit")
        scoped = scoped[: max(0, limit - len(carried))]
    # Selection/truncation is by (T,event_id), while the artifact's events map
    # is always canonical numeric ID order.
    included_ids = tuple(sorted(event.id for event in carried + scoped))
    enrollment_required_ids = tuple(
        event_id for event_id in included_ids if event_id not in controls
    )
    blocked_scope = len(eligible) - len(included_ids)
    blocked_reason = sum(reason_counts.values())
    return RegistryCensus(
        included_event_ids=included_ids,
        enrollment_required_event_ids=enrollment_required_ids,
        successor_pending_event_ids=tuple(sorted(successor)),
        inspected=inspected,
        included=len(included_ids),
        blocked_by_reason=blocked_reason,
        blocked_by_scope=blocked_scope,
        reason_counts=reason_counts,
    )


def _validate_selector_scope(scope: Any) -> None:
    required = {
        "kind", "cutoff", "window_end", "start_inclusive", "end_inclusive",
        "require_datetime", "explicit_event_ids", "limit", "order_by",
        "predecessor_carry_forward",
    }
    if not isinstance(scope, dict) or set(scope) != required:
        raise RegistryError("selector scope schema 不匹配")
    kind = scope.get("kind")
    if kind not in ALLOWED_SCOPES:
        raise RegistryError("selector scope kind 非法")
    cutoff = _parse_dt(scope.get("cutoff"), "scope.cutoff")
    window = scope.get("window_end")
    window_end = _parse_dt(window, "scope.window_end") if window is not None else None
    expected_require_datetime = kind in {"datetime_7d_canary", "datetime_30d"}
    if (
        scope.get("start_inclusive") is not True
        or scope.get("end_inclusive") is not False
        or scope.get("require_datetime") is not expected_require_datetime
        or type(scope.get("predecessor_carry_forward")) is not bool
        or scope.get("order_by") != ["race_datetime", "event_id"]
    ):
        raise RegistryError("selector scope policy 字段非法")
    if expected_require_datetime and (window_end is None or window_end <= cutoff):
        raise RegistryError("datetime scope window 非法")
    if not expected_require_datetime and window_end is not None:
        raise RegistryError("非 datetime scope 不得提供 window_end")
    ids = scope.get("explicit_event_ids")
    if (
        not isinstance(ids, list)
        or ids != sorted(set(ids))
        or any(type(item) is not int or item <= 0 for item in ids)
    ):
        raise RegistryError("selector explicit_event_ids 非法")
    limit = scope.get("limit")
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise RegistryError("selector limit 非法")
    if kind == "full_eligible" and limit is not None:
        raise RegistryError("full_eligible scope 必须 limit=None")
    if kind == "datetime_7d_canary" and limit != 20:
        raise RegistryError("datetime_7d_canary scope 必须 limit=20")
    if kind == "datetime_30d" and limit != 100:
        raise RegistryError("datetime_30d scope 必须 limit=100")


def _entry_snapshot(event: RaceEvent, control: RaceEventLifecycleControl, source_sha: str) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "event_updated_at": _utc_iso(event.updated_at),
        "status": event.status,
        "visibility_status": event.visibility_status,
        "region": event.country_region,
        "timezone_name": event.timezone_name,
        "local_date": event.local_date.isoformat() if event.local_date else None,
        "race_datetime": _utc_iso(event.race_datetime) if event.race_datetime else None,
        "manual_lock_flags": event.manual_lock_flags,
        "manual_pause_reason": control.manual_pause_reason,
        "control_mode": control.mode,
        "schedule_generation": control.schedule_generation,
        "schedule_hash": _schedule_hash(event),
        "source_enrollment_sha256": source_sha,
        "allowed_us_zones": control.manifest_data.get("allowed_us_zones") or [],
    }


def validate_registry_artifact_identity(
    *,
    approved_commit: str,
    generation: int,
    predecessor_root_sha256: str = "",
) -> None:
    if not _OID_RE.fullmatch(approved_commit or ""):
        raise RegistryError("approved_commit 非法")
    if type(generation) is not int or generation <= 0:
        raise RegistryError("generation 非法")
    if predecessor_root_sha256 and not _SHA_RE.fullmatch(predecessor_root_sha256):
        raise RegistryError("predecessor root 非法")


def build_registry_artifact(
    *,
    event_ids: tuple[int, ...] | list[int],
    enrollment_sha_by_event: dict[int, str],
    approved_commit: str,
    generation: int,
    selector_scope: dict[str, Any],
    now: datetime | None = None,
    predecessor_root_sha256: str = "",
) -> bytes:
    _validate_selector_scope(selector_scope)
    validate_registry_artifact_identity(
        approved_commit=approved_commit,
        generation=generation,
        predecessor_root_sha256=predecessor_root_sha256,
    )
    ids = tuple(sorted(set(event_ids)))
    if not ids or tuple(event_ids) != ids or any(type(item) is not int or item <= 0 for item in ids):
        raise RegistryError("registry event IDs 必须非空、唯一、升序")
    if set(enrollment_sha_by_event) != set(ids) or any(
        not _SHA_RE.fullmatch(value or "") for value in enrollment_sha_by_event.values()
    ):
        raise RegistryError("每场必须绑定合法 enrollment SHA")
    generated = (now or django_timezone.now()).astimezone(timezone.utc)
    events = list(RaceEvent.objects.filter(id__in=ids).order_by("id"))
    controls = {
        row.event_id: row
        for row in RaceEventLifecycleControl.objects.filter(event_id__in=ids)
    }
    if tuple(event.id for event in events) != ids or set(controls) != set(ids):
        raise RegistryError("registry event/control cohort 不完整")
    entries: dict[str, Any] = {}
    entry_shas: list[str] = []
    for event in events:
        snapshot = _entry_snapshot(event, controls[event.id], enrollment_sha_by_event[event.id])
        entry_sha = hashlib.sha256(_canonical_bytes(snapshot)).hexdigest()
        entries[str(event.id)] = {**snapshot, "entry_sha256": entry_sha}
        entry_shas.append(entry_sha)
    membership_sha = hashlib.sha256(_canonical_bytes({"entry_sha256s": entry_shas})).hexdigest()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_iso(generated),
        "apply_expires_at": _utc_iso(generated + timedelta(hours=24)),
        "runtime_valid_until": _utc_iso(generated + timedelta(days=35)),
        "approved_commit": approved_commit,
        "generation": generation,
        "predecessor_root_sha256": predecessor_root_sha256,
        "selector_scope": selector_scope,
        "scope_sha256": scope_sha256(selector_scope),
        "member_count": len(ids),
        "membership_sha256": membership_sha,
        "events": entries,
    }
    payload["content_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    raw = _canonical_bytes(payload)
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise RegistryError("registry artifact 超限")
    return raw


def load_registry_manifest_bytes(
    raw: bytes,
    *,
    expected_raw_sha256: str,
    expected_commit: str,
    now: datetime | None = None,
    require_apply_fresh: bool = False,
) -> LoadedRegistryManifest:
    if not raw or len(raw) > MAX_ARTIFACT_BYTES:
        raise RegistryError("registry artifact 为空或超限")
    actual = hashlib.sha256(raw).hexdigest()
    if not _SHA_RE.fullmatch(expected_raw_sha256 or "") or actual != expected_raw_sha256:
        raise RegistryError("registry raw SHA-256 不匹配")
    if not _OID_RE.fullmatch(expected_commit or ""):
        raise RegistryError("expected commit 非法")
    try:
        data = _parse_json(raw)
    except ValueError as exc:
        raise RegistryError(str(exc)) from exc
    required = {
        "schema_version", "generated_at", "apply_expires_at", "runtime_valid_until",
        "approved_commit", "generation", "predecessor_root_sha256", "selector_scope",
        "scope_sha256", "member_count", "membership_sha256", "events", "content_sha256",
    }
    if set(data) != required or data.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError("registry artifact schema 不匹配")
    if data["approved_commit"] != expected_commit:
        raise RegistryError("approved_commit 不匹配")
    generated = _parse_dt(data["generated_at"], "generated_at")
    expires = _parse_dt(data["apply_expires_at"], "apply_expires_at")
    runtime_until = _parse_dt(data["runtime_valid_until"], "runtime_valid_until")
    current = now or django_timezone.now()
    if expires != generated + timedelta(hours=24) or runtime_until != generated + timedelta(days=35):
        raise RegistryError("registry 有效期合同不匹配")
    if current >= runtime_until or (require_apply_fresh and current >= expires):
        raise RegistryError("registry artifact 已过期")
    if scope_sha256(data["selector_scope"]) != data["scope_sha256"]:
        raise RegistryError("scope SHA 不匹配")
    _validate_selector_scope(data["selector_scope"])
    payload = dict(data)
    content = payload.pop("content_sha256")
    if not _SHA_RE.fullmatch(content or "") or hashlib.sha256(_canonical_bytes(payload)).hexdigest() != content:
        raise RegistryError("content SHA 不匹配")
    if raw != _canonical_bytes(data):
        raise RegistryError("registry artifact 非 canonical JSON")
    events = data["events"]
    if not isinstance(events, dict) or not events:
        raise RegistryError("registry events 必须非空")
    try:
        ids = tuple(int(key) for key in events)
    except (TypeError, ValueError) as exc:
        raise RegistryError("registry event key 必须为正整数") from exc
    if any(str(event_id) not in events or event_id <= 0 for event_id in ids):
        raise RegistryError("registry event key 必须为 canonical 正整数")
    if ids != tuple(sorted(set(ids))) or data["member_count"] != len(ids):
        raise RegistryError("registry member count/order 不匹配")
    entry_shas: list[str] = []
    enrollment: dict[int, str] = {}
    for event_id in ids:
        entry = events[str(event_id)]
        if entry.get("event_id") != event_id:
            raise RegistryError("entry event ID 不匹配")
        declared = entry.get("entry_sha256", "")
        snapshot = dict(entry)
        snapshot.pop("entry_sha256", None)
        if hashlib.sha256(_canonical_bytes(snapshot)).hexdigest() != declared:
            raise RegistryError("entry SHA 不匹配")
        source_sha = entry.get("source_enrollment_sha256", "")
        if not _SHA_RE.fullmatch(source_sha):
            raise RegistryError("entry enrollment SHA 非法")
        entry_shas.append(declared)
        enrollment[event_id] = source_sha
    expected_membership = hashlib.sha256(_canonical_bytes({"entry_sha256s": entry_shas})).hexdigest()
    if data["membership_sha256"] != expected_membership:
        raise RegistryError("membership SHA 不匹配")
    predecessor = data["predecessor_root_sha256"]
    if predecessor and not _SHA_RE.fullmatch(predecessor):
        raise RegistryError("predecessor root 非法")
    return LoadedRegistryManifest(data, raw, actual, content, ids, enrollment, predecessor)


def _assert_closed() -> None:
    if getattr(settings, "RACE_EVENT_LIFECYCLE_ENABLED", False) or getattr(
        settings, "RACE_EVENT_LIFECYCLE_MODE", "off"
    ) != "off":
        raise RegistryError("registry promotion 只允许 lifecycle false/off")


def _advisory_lock() -> None:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_ADVISORY_LOCK_KEY])


def _advisory_shared_lock() -> None:
    """Rotation barrier shared by per-event workers without root-row serialization."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock_shared(%s)", [_ADVISORY_LOCK_KEY]
            )


def _context_lock():
    return _SQLITE_LOCK if connection.vendor == "sqlite" else _NullContext()


class _NullContext:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


def _assert_manifest_matches_db(
    manifest: LoadedRegistryManifest,
    event_ids: tuple[int, ...] | None = None,
    allow_lifecycle_progress: bool = False,
    allow_running_event_ids: frozenset[int] = frozenset(),
) -> tuple[list[RaceEvent], list[RaceEventLifecycleControl]]:
    expected_ids = event_ids or manifest.event_ids
    events = list(RaceEvent.objects.select_for_update().filter(id__in=expected_ids).order_by("id"))
    controls = list(RaceEventLifecycleControl.objects.select_for_update().filter(event_id__in=expected_ids).order_by("event_id"))
    if tuple(event.id for event in events) != expected_ids or tuple(control.event_id for control in controls) != expected_ids:
        raise RegistryError("registry cohort 数据库行不完整")
    for event, control in zip(events, controls, strict=True):
        entry = manifest.data["events"][str(event.id)]
        if _schedule_hash(event) != entry["schedule_hash"] or control.schedule_generation != entry["schedule_generation"]:
            raise RegistryError(f"event {event.id} schedule/generation 漂移")
        if event.country_region != entry["region"] or event.timezone_name != entry["timezone_name"]:
            raise RegistryError(f"event {event.id} region/timezone 漂移")
        if control.enrollment_manifest_sha256 != entry["source_enrollment_sha256"]:
            raise RegistryError(f"event {event.id} enrollment provenance 漂移")
        reason = (
            _active_member_safety_reason(event, control)
            if allow_lifecycle_progress
            else _eligibility_reason(
                event,
                control,
                allow_running=event.id in allow_running_event_ids,
            )
        )
        if reason:
            raise RegistryError(f"event {event.id} 不再合格: {reason}")
    return events, controls


def _active_member_safety_reason(
    event: RaceEvent, control: RaceEventLifecycleControl
) -> str:
    if event.visibility_status != "published":
        return "not_published"
    if event.status not in {
        RaceEventStatus.SCHEDULED,
        RaceEventStatus.RUNNING,
        RaceEventStatus.FINISHED,
        RaceEventStatus.CANCELLED,
        RaceEventStatus.POSTPONED,
    }:
        return "invalid_lifecycle_status"
    if event.local_date is None:
        return "missing_local_date"
    if event.manual_lock_flags:
        return "manual_lock"
    if control.manual_pause_reason:
        return "manual_pause"
    if control.enrollment_manifest_sha256 == "" or control.manifest_data.get(
        "enrollment_schedule_hash"
    ) != _schedule_hash(event):
        return "invalid_enrollment_provenance"
    zones = control.manifest_data.get("allowed_us_zones") or []
    if event.country_region == "united_states" and not zones:
        return "us_allowlist_missing"
    timezone_error = _validate_timezone(
        event.timezone_name,
        event.country_region,
        frozenset(zones) if event.country_region == "united_states" else None,
    )
    return "timezone_invalid" if timezone_error else ""


def _assert_stage_transition(
    manifest: LoadedRegistryManifest,
    predecessor: RaceEventLifecycleEnforceRegistry | None,
) -> None:
    target_kind = manifest.data["selector_scope"]["kind"]
    if predecessor is None:
        if (
            manifest.predecessor_root_sha256
            or manifest.data["generation"] != 1
            or target_kind != "datetime_7d_canary"
        ):
            raise RegistryError("first registry generation 必须为 datetime_7d_canary")
        return
    predecessor_kind = predecessor.selector_scope.get("kind")
    if predecessor_kind not in SCOPE_STAGES:
        raise RegistryError("predecessor selector scope 非法")
    predecessor_index = SCOPE_STAGES.index(predecessor_kind)
    target_index = SCOPE_STAGES.index(target_kind)
    if target_index not in {predecessor_index, predecessor_index + 1}:
        raise RegistryError("registry scope 只允许同阶段轮换或前进一档")
    if manifest.data["generation"] != predecessor.generation + 1:
        raise RegistryError("successor generation 必须等于 predecessor + 1")
    if manifest.predecessor_root_sha256 != predecessor.root_sha256:
        raise RegistryError("declared predecessor root 不匹配")
    if target_index == predecessor_index:
        return
    member_ids = list(
        predecessor.memberships.order_by("event_id").values_list(
            "event_id", flat=True
        )
    )
    if predecessor_kind == "datetime_7d_canary" and target_kind == "datetime_30d":
        evidence: dict[int, set[str]] = {}
        for event_id, reason_code, metadata in RaceEventLifecycleTransition.objects.filter(
            event_id__in=member_ids,
            record_kind=RaceEventLifecycleTransitionKind.APPLIED,
            reason_code__in=("time_reached_race_datetime", "time_t_plus_30"),
        ).values_list("event_id", "reason_code", "metadata"):
            root = (metadata or {}).get("enforce_registry", {}).get("root_sha256")
            if root == predecessor.root_sha256:
                evidence.setdefault(event_id, set()).add(reason_code)
        required = {"time_reached_race_datetime", "time_t_plus_30"}
        if not any(reasons >= required for reasons in evidence.values()):
            raise RegistryError("7d→30d 缺少同场 T/T+30 applied proof")
    if predecessor_kind == "no_time_canary" and target_kind == "full_eligible":
        proven = False
        for metadata in RaceEventLifecycleTransition.objects.filter(
            event_id__in=member_ids,
            record_kind=RaceEventLifecycleTransitionKind.APPLIED,
            reason_code="local_next_day_midnight",
        ).values_list("metadata", flat=True):
            if (metadata or {}).get("enforce_registry", {}).get(
                "root_sha256"
            ) == predecessor.root_sha256:
                proven = True
                break
        if not proven:
            raise RegistryError("no_time→full 缺少 local_next_day_midnight applied proof")


def promote_registry(
    manifest: LoadedRegistryManifest, *, apply: bool, batch_size: int = 100
) -> RegistryResult:
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise RegistryError("promotion batch_size 必须为 1–100")
    predecessor_running_ids = frozenset(
        RaceEventLifecycleEnforceMembership.objects.filter(
            registry__root_sha256=manifest.predecessor_root_sha256,
            event__status=RaceEventStatus.RUNNING,
        ).values_list("event_id", flat=True)
    ) if manifest.predecessor_root_sha256 else frozenset()
    if apply:
        _assert_closed()
    else:
        # Dry-run is a complete preflight, not a simulation of one bounded
        # write batch.  A drift at member 101 must be visible before apply.
        with transaction.atomic():
            _assert_manifest_matches_db(
                manifest, allow_running_event_ids=predecessor_running_ids
            )
    with _context_lock():
        with transaction.atomic():
            _advisory_lock()
            registry = RaceEventLifecycleEnforceRegistry.objects.select_for_update().filter(root_sha256=manifest.raw_sha256).first()
            if registry:
                if (
                    registry.membership_sha256 != manifest.data["membership_sha256"]
                    or registry.member_count != len(manifest.event_ids)
                    or registry.generation != manifest.data["generation"]
                    or registry.scope_sha256 != manifest.data["scope_sha256"]
                ):
                    raise RegistryError("existing registry evidence 冲突")
            predecessor = None
            if manifest.predecessor_root_sha256:
                predecessor = RaceEventLifecycleEnforceRegistry.objects.select_for_update().filter(
                    root_sha256=manifest.predecessor_root_sha256
                ).first()
                if predecessor is None:
                    raise RegistryError("declared predecessor registry 不存在")
            _assert_stage_transition(manifest, predecessor)
            if (
                predecessor is None
                and RaceEventLifecycleEnforceRegistry.objects.exclude(
                    root_sha256=manifest.raw_sha256
                ).exists()
            ):
                raise RegistryError("非首代 registry 必须声明 predecessor")
            if registry is None and apply:
                registry = RaceEventLifecycleEnforceRegistry.objects.create(
                    root_sha256=manifest.raw_sha256,
                    generation=manifest.data["generation"],
                    predecessor=predecessor,
                    membership_sha256=manifest.data["membership_sha256"],
                    member_count=len(manifest.event_ids),
                    state="inactive",
                    is_active=False,
                    approved_commit=manifest.data["approved_commit"],
                    selector_scope=manifest.data["selector_scope"],
                    scope_sha256=manifest.data["scope_sha256"],
                    census_cutoff=_parse_dt(manifest.data["selector_scope"]["cutoff"], "scope.cutoff"),
                    apply_expires_at=_parse_dt(manifest.data["apply_expires_at"], "apply_expires_at"),
                    runtime_valid_until=_parse_dt(manifest.data["runtime_valid_until"], "runtime_valid_until"),
                    artifact_receipt={"raw_sha256": manifest.raw_sha256, "content_sha256": manifest.content_sha256},
                )
            existing_ids = set(
                RaceEventLifecycleEnforceMembership.objects.filter(
                    registry=registry
                ).values_list("event_id", flat=True)
            ) if registry else set()
            missing_ids = tuple(
                event_id for event_id in manifest.event_ids if event_id not in existing_ids
            )
            if not missing_ids:
                return RegistryResult(
                    "replay", manifest.event_ids,
                    registry.activation_id if registry else "",
                    total=len(manifest.event_ids), remaining=0,
                )
            batch_ids = missing_ids[:batch_size]
            events, controls = _assert_manifest_matches_db(
                manifest,
                batch_ids,
                allow_running_event_ids=predecessor_running_ids,
            )
            if not apply:
                return RegistryResult(
                    "would_apply", manifest.event_ids,
                    total=len(manifest.event_ids), remaining=len(missing_ids),
                )
            assert registry is not None
            memberships = []
            for event, control in zip(events, controls, strict=True):
                entry = manifest.data["events"][str(event.id)]
                memberships.append(RaceEventLifecycleEnforceMembership(
                    registry=registry,
                    event=event,
                    entry_sha256=entry["entry_sha256"],
                    source_enrollment_sha256=entry["source_enrollment_sha256"],
                    schedule_generation=entry["schedule_generation"],
                    schedule_hash=entry["schedule_hash"],
                    country_region=entry["region"],
                    timezone_name=entry["timezone_name"],
                    frozen_snapshot=entry,
                ))
                data = dict(control.manifest_data)
                data["enforce_registry"] = {
                    "root_sha256": manifest.raw_sha256,
                    "membership_sha256": manifest.data["membership_sha256"],
                    "entry_sha256": entry["entry_sha256"],
                    "activation_state": "inactive",
                }
                control.mode = RaceEventLifecycleMode.ENFORCE
                control.manifest_data = data
            RaceEventLifecycleEnforceMembership.objects.bulk_create(memberships)
            RaceEventLifecycleControl.objects.bulk_update(controls, ["mode", "manifest_data", "updated_at"])
            OperationLog.objects.create(
                action_type="lifecycle_enforce_registry_batch_promoted",
                target_type="race_event_lifecycle_registry",
                target_id=manifest.raw_sha256,
                detail=json.dumps(
                    {
                        "generation": registry.generation,
                        "batch_event_ids": list(batch_ids),
                        "promoted_count": len(existing_ids) + len(batch_ids),
                        "member_count": registry.member_count,
                    },
                    sort_keys=True,
                ),
            )
            outcome = (
                "applied"
                if len(existing_ids) + len(batch_ids) == registry.member_count
                else "partial"
            )
            return RegistryResult(
                outcome, batch_ids,
                total=len(manifest.event_ids),
                remaining=len(missing_ids) - len(batch_ids),
            )


def activate_registry(
    manifest: LoadedRegistryManifest,
    *,
    apply: bool = True,
    activation_id: str = "",
    expected_activation_id: str = "",
) -> RegistryResult:
    """Atomically activate a promoted registry.

    A release wrapper may pre-generate an activation ID and activate while the
    resident runtime is still strictly false/off.  That closes the otherwise
    unavoidable true/enforce + inactive-root window.  The no-argument branch
    preserves the reviewed legacy/test path where a true/enforce runtime is
    already bound to the remaining registry root fields.
    """
    if activation_id and expected_activation_id and activation_id != expected_activation_id:
        raise RegistryError("activation ID 参数不一致")
    requested_activation_id = activation_id or expected_activation_id
    if requested_activation_id:
        if _SHA_RE.fullmatch(requested_activation_id) is None:
            raise RegistryError("activation ID 必须为 64 位小写 hex")
        _assert_closed()
    elif (
        not getattr(settings, "RACE_EVENT_LIFECYCLE_ENABLED", False)
        or getattr(settings, "RACE_EVENT_LIFECYCLE_MODE", "off") != "enforce"
        or getattr(settings, "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256", "")
        != manifest.raw_sha256
        or getattr(
            settings,
            "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256",
            "",
        )
        != manifest.data["membership_sha256"]
        or getattr(settings, "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT", 0)
        != len(manifest.event_ids)
    ):
        raise RegistryError("registry activation runtime trust root 不匹配")
    with _context_lock():
        with transaction.atomic():
            _advisory_lock()
            target = RaceEventLifecycleEnforceRegistry.objects.select_for_update().get(root_sha256=manifest.raw_sha256)
            old = RaceEventLifecycleEnforceRegistry.objects.select_for_update().filter(
                is_active=True
            ).exclude(pk=target.pk).first()
            membership_rows = list(
                target.memberships.select_for_update().order_by("event_id")
            )
            if (
                tuple(row.event_id for row in membership_rows) != manifest.event_ids
                or len(membership_rows) != target.member_count
                or target.membership_sha256 != manifest.data["membership_sha256"]
                or target.member_count != manifest.data["member_count"]
                or hashlib.sha256(
                    _canonical_bytes(
                        {"entry_sha256s": [row.entry_sha256 for row in membership_rows]}
                    )
                ).hexdigest()
                != target.membership_sha256
            ):
                raise RegistryError("registry membership 尚未完整 promotion")
            predecessor_member_ids = frozenset(
                target.predecessor.memberships.filter(
                    event__status=RaceEventStatus.RUNNING
                ).values_list("event_id", flat=True)
            ) if target.predecessor_id else frozenset()
            _, target_controls = _assert_manifest_matches_db(
                manifest,
                allow_lifecycle_progress=target.is_active,
                allow_running_event_ids=predecessor_member_ids,
            )
            if target.is_active:
                for membership, control in zip(
                    membership_rows, target_controls, strict=True
                ):
                    evidence = control.manifest_data.get("enforce_registry")
                    if (
                        control.mode != RaceEventLifecycleMode.ENFORCE
                        or not isinstance(evidence, dict)
                        or evidence.get("root_sha256") != manifest.raw_sha256
                        or evidence.get("membership_sha256")
                        != manifest.data["membership_sha256"]
                        or evidence.get("entry_sha256") != membership.entry_sha256
                        or evidence.get("activation_state") != "active"
                        or evidence.get("activation_id") != target.activation_id
                    ):
                        raise RegistryError(
                            f"event {control.event_id} active control evidence 不匹配"
                        )
                if requested_activation_id and target.activation_id != requested_activation_id:
                    raise RegistryError("active registry activation ID replay 不匹配")
                return RegistryResult("replay", manifest.event_ids, target.activation_id)
            if target.state != "inactive" or target.member_count != len(manifest.event_ids):
                raise RegistryError("target registry 尚未完整 promotion")
            for membership, control in zip(
                membership_rows, target_controls, strict=True
            ):
                evidence = control.manifest_data.get("enforce_registry")
                if (
                    control.mode != RaceEventLifecycleMode.ENFORCE
                    or not isinstance(evidence, dict)
                    or evidence.get("root_sha256") != manifest.raw_sha256
                    or evidence.get("membership_sha256")
                    != manifest.data["membership_sha256"]
                    or evidence.get("entry_sha256") != membership.entry_sha256
                    or evidence.get("activation_state") != "inactive"
                ):
                    raise RegistryError(
                        f"event {control.event_id} control promotion evidence 不完整"
                    )
            census = select_registry_candidates(
                scope=manifest.data["selector_scope"],
                predecessor_event_ids=(
                    list(target.predecessor.memberships.values_list("event_id", flat=True))
                    if target.predecessor_id else []
                ),
            )
            if census.included_event_ids != manifest.event_ids:
                raise RegistryError("activation cutoff census 与 artifact 不一致")
            if not apply:
                return RegistryResult("would_activate", manifest.event_ids)
            now = django_timezone.now()
            if target.predecessor_id:
                if (
                    old is None
                    or old.pk != target.predecessor_id
                    or manifest.predecessor_root_sha256 != old.root_sha256
                ):
                    raise RegistryError("active predecessor CAS 不匹配")
            elif (
                old is not None
                or target.generation != 1
                or manifest.predecessor_root_sha256
            ):
                raise RegistryError("first-generation activation CAS 不匹配")
            _assert_stage_transition(manifest, target.predecessor)
            for control in target_controls:
                # A claim is issued under a particular active root even though
                # it lives on the per-event control.  Clear predecessor claims
                # before the successor becomes active so stale queued work is
                # inert and cannot delay the new scanner until TTL expiry.
                control.claim_token = ""
                control.claim_expires_at = None
            RaceEventLifecycleControl.objects.bulk_update(
                target_controls,
                ["claim_token", "claim_expires_at", "updated_at"],
            )
            outside_controls = list(
                RaceEventLifecycleControl.objects.select_for_update()
                .filter(mode=RaceEventLifecycleMode.ENFORCE)
                .exclude(event_id__in=manifest.event_ids)
                .order_by("event_id")
            )
            if old:
                old.is_active = False
                old.state = "retired"
                old.retired_at = now
                old.save(update_fields=("is_active", "state", "retired_at", "updated_at"))
                old.memberships.update(state="retired")
            for control in outside_controls:
                data = dict(control.manifest_data)
                runtime_evidence = data.pop("enforce_registry", None)
                if isinstance(runtime_evidence, dict):
                    history = list(data.get("enforce_registry_history") or [])
                    history.append(
                        {
                            **runtime_evidence,
                            "activation_state": "retired",
                            "retired_at": _utc_iso(now),
                        }
                    )
                    data["enforce_registry_history"] = history
                control.mode = RaceEventLifecycleMode.SHADOW
                control.manifest_data = data
                control.claim_token = ""
                control.claim_expires_at = None
                control.next_refresh_at = None
            if outside_controls:
                RaceEventLifecycleControl.objects.bulk_update(
                    outside_controls,
                    [
                        "mode", "manifest_data", "claim_token",
                        "claim_expires_at", "next_refresh_at", "updated_at",
                    ],
                )
            resolved_activation_id = requested_activation_id or secrets.token_hex(32)
            target.is_active = True
            target.state = "active"
            target.activation_id = resolved_activation_id
            target.activated_at = now
            target.save(update_fields=("is_active", "state", "activation_id", "activated_at", "updated_at"))
            for membership in target.memberships.select_related("event"):
                control = membership.event.lifecycle_control
                data = dict(control.manifest_data)
                evidence = dict(data.get("enforce_registry") or {})
                evidence.update({"activation_state": "active", "activation_id": resolved_activation_id})
                data["enforce_registry"] = evidence
                control.manifest_data = data
                control.save(update_fields=("manifest_data", "updated_at"))
            return RegistryResult("activated", manifest.event_ids, resolved_activation_id)


def verify_registry_state(
    manifest: LoadedRegistryManifest,
    *,
    expected_state: str,
    expected_activation_id: str = "",
) -> RegistryResult:
    """Strictly bind a persisted registry back to its reviewed artifact."""
    if expected_state not in {"inactive", "active"}:
        raise RegistryError("expected registry state 非法")
    if expected_activation_id and _SHA_RE.fullmatch(expected_activation_id) is None:
        raise RegistryError("activation ID 必须为 64 位小写 hex")
    with transaction.atomic():
        registry = RaceEventLifecycleEnforceRegistry.objects.select_for_update().get(
            root_sha256=manifest.raw_sha256
        )
        rows = list(registry.memberships.order_by("event_id"))
        computed_membership = hashlib.sha256(
            _canonical_bytes({"entry_sha256s": [row.entry_sha256 for row in rows]})
        ).hexdigest()
        if (
            registry.state != expected_state
            or registry.is_active != (expected_state == "active")
            or registry.artifact_receipt.get("raw_sha256") != manifest.raw_sha256
            or registry.artifact_receipt.get("content_sha256") != manifest.content_sha256
            or registry.membership_sha256 != manifest.data["membership_sha256"]
            or registry.member_count != manifest.data["member_count"]
            or tuple(row.event_id for row in rows) != manifest.event_ids
            or computed_membership != registry.membership_sha256
        ):
            raise RegistryError("registry DB/artifact binding 不匹配")
        if expected_state == "active":
            if not _SHA_RE.fullmatch(registry.activation_id or ""):
                raise RegistryError("active registry activation ID 非法")
            if expected_activation_id and registry.activation_id != expected_activation_id:
                raise RegistryError("active registry activation ID 不匹配")
        elif registry.activation_id:
            raise RegistryError("inactive registry 不得已有 activation ID")
        predecessor_running_ids = (
            frozenset(
                registry.predecessor.memberships.filter(
                    event__status=RaceEventStatus.RUNNING
                ).values_list("event_id", flat=True)
            )
            if registry.predecessor_id
            else frozenset()
        )
        _, controls = _assert_manifest_matches_db(
            manifest,
            allow_lifecycle_progress=(expected_state == "active"),
            allow_running_event_ids=predecessor_running_ids,
        )
        if expected_state == "active":
            for row, control in zip(rows, controls, strict=True):
                evidence = control.manifest_data.get("enforce_registry")
                if (
                    control.mode != RaceEventLifecycleMode.ENFORCE
                    or not isinstance(evidence, dict)
                    or evidence.get("root_sha256") != manifest.raw_sha256
                    or evidence.get("membership_sha256")
                    != manifest.data["membership_sha256"]
                    or evidence.get("entry_sha256") != row.entry_sha256
                    or evidence.get("activation_state") != "active"
                    or evidence.get("activation_id") != registry.activation_id
                ):
                    raise RegistryError(
                        f"event {control.event_id} active control evidence 不匹配"
                    )
        return RegistryResult(
            f"verified_{expected_state}", manifest.event_ids, registry.activation_id
        )


def validate_active_registry_membership(
    *, event_id: int, root_sha256: str, membership_sha256: str,
    member_count: int, activation_id: str, lock: bool = False
) -> MembershipValidation:
    try:
        # Rotation is excluded by the transaction-level advisory barrier in
        # apply_registry_lifecycle_decision.  Never lock the shared root row:
        # that would serialize otherwise independent event workers.
        registry = RaceEventLifecycleEnforceRegistry.objects.get(
            root_sha256=root_sha256,
            membership_sha256=membership_sha256,
            member_count=member_count,
            is_active=True,
            state="active",
            activation_id=activation_id,
        )
        membership_query = RaceEventLifecycleEnforceMembership.objects.select_related("registry")
        if lock:
            membership_query = membership_query.select_for_update(of=("self",))
        membership = membership_query.get(
            registry=registry,
            event_id=event_id,
            state="active",
        )
    except (
        RaceEventLifecycleEnforceRegistry.DoesNotExist,
        RaceEventLifecycleEnforceMembership.DoesNotExist,
    ):
        return MembershipValidation(False, "registry_root_stale")
    if django_timezone.now() >= membership.registry.runtime_valid_until:
        return MembershipValidation(False, "registry_runtime_expired")
    return MembershipValidation(True, membership=membership)


def validate_runtime_registry_settings() -> tuple[bool, str | RaceEventLifecycleEnforceRegistry]:
    root = getattr(settings, "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256", "")
    membership_sha = getattr(settings, "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256", "")
    member_count = getattr(settings, "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT", 0)
    activation_id = getattr(settings, "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID", "")
    if not (_SHA_RE.fullmatch(root or "") and _SHA_RE.fullmatch(membership_sha or "") and _SHA_RE.fullmatch(activation_id or "")):
        return False, "registry_runtime_settings_invalid"
    try:
        registry = RaceEventLifecycleEnforceRegistry.objects.get(
            root_sha256=root, membership_sha256=membership_sha,
            member_count=member_count, activation_id=activation_id,
            state="active", is_active=True,
        )
    except RaceEventLifecycleEnforceRegistry.DoesNotExist:
        return False, "registry_runtime_root_mismatch"
    if django_timezone.now() >= registry.runtime_valid_until:
        return False, "registry_runtime_expired"
    return True, registry


def apply_registry_lifecycle_decision(
    *, event_id: int, expected_generation: int, now: datetime,
    expected_registry_root_sha256: str, expected_registry_activation_id: str,
    expected_registry_membership_sha256: str,
    expected_registry_member_count: int,
    expected_runtime_enabled: bool, expected_runtime_mode: str,
    attempt_token: str = "", expected_claim_generation: int = 0,
):
    from stable.services.race_event_lifecycle import ApplyResult, apply_race_lifecycle_decision

    if (
        _SHA_RE.fullmatch(expected_registry_root_sha256 or "") is None
        or _SHA_RE.fullmatch(expected_registry_membership_sha256 or "") is None
        or type(expected_registry_member_count) is not int
        or expected_registry_member_count <= 0
        or _SHA_RE.fullmatch(expected_registry_activation_id or "") is None
    ):
        return ApplyResult(action="noop", reason_code="registry_expected_trust_root_invalid")
    if (
        not getattr(settings, "RACE_EVENT_LIFECYCLE_ENABLED", False)
        or getattr(settings, "RACE_EVENT_LIFECYCLE_MODE", "off") != "enforce"
        or not expected_runtime_enabled
        or expected_runtime_mode != "enforce"
    ):
        return ApplyResult(action="noop", reason_code="lifecycle_disabled_mid_flight")
    with _context_lock():
        with transaction.atomic():
            _advisory_shared_lock()
            validation = validate_active_registry_membership(
                event_id=event_id,
                root_sha256=expected_registry_root_sha256,
                membership_sha256=expected_registry_membership_sha256,
                member_count=expected_registry_member_count,
                activation_id=expected_registry_activation_id,
                lock=True,
            )
            if not validation.valid:
                return ApplyResult(action="noop", reason_code=validation.reason_code)
            membership = validation.membership
            assert membership is not None
            control = RaceEventLifecycleControl.objects.select_for_update().get(event_id=event_id)
            # Hold the event row lock before checking the frozen schedule and
            # manual gates.  The lower-level apply locks the same row again in
            # this transaction, so no writer can change the validated snapshot
            # between registry authorization and the public transition.
            event = RaceEvent.objects.select_for_update(of=("self",)).get(
                pk=event_id
            )
            if event.visibility_status != "published":
                return ApplyResult(action="noop", reason_code="registry_event_not_published")
            if event.manual_lock_flags:
                return ApplyResult(action="noop", reason_code="registry_event_manual_lock")
            if control.manual_pause_reason:
                return ApplyResult(action="noop", reason_code="registry_control_manual_pause")
            if (
                membership.schedule_generation != expected_generation
                or membership.schedule_generation != control.schedule_generation
                or membership.source_enrollment_sha256
                != control.enrollment_manifest_sha256
                or membership.schedule_hash != _schedule_hash(event)
                or membership.country_region != event.country_region
                or membership.timezone_name != event.timezone_name
                or not membership.registry.is_active
                or membership.registry.state != "active"
            ):
                return ApplyResult(action="noop", reason_code="registry_membership_drift")
            zones = membership.frozen_snapshot.get("allowed_us_zones") or []
            return apply_race_lifecycle_decision(
                event_id=event_id, expected_generation=expected_generation, now=now,
                mode="enforce", attempt_token=attempt_token,
                expected_claim_generation=expected_claim_generation,
                allowed_us_zones=frozenset(zones) if zones else None,
                registry_authorized=True,
                registry_transition_metadata={
                    "enforce_registry": {
                        "root_sha256": expected_registry_root_sha256,
                        "membership_sha256": membership.registry.membership_sha256,
                        "entry_sha256": membership.entry_sha256,
                        "activation_id": expected_registry_activation_id,
                    }
                },
            )

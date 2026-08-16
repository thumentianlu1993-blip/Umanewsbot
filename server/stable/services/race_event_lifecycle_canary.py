"""Strict artifact and database gates for the two-event lifecycle canary."""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, BinaryIO

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone as django_timezone

from stable.models import (
    OperationLog,
    RaceEvent,
    RaceEventLifecycleControl,
    RaceEventLifecycleTransition,
    RaceEventLifecycleTransitionKind,
)
from stable.services.race_event_lifecycle_enrollment import (
    _canonical_bytes,
    _control_manifest_data_sha,
    _iso_datetime,
    _parse_json,
    _schedule_hash,
)


SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 1024 * 1024
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_ADVISORY_LOCK_KEY = 0x554D41434E525931  # "UMACNRY1", stable across releases
_SQLITE_LOCK = threading.RLock()
_TOP_FIELDS = frozenset({
    "schema_version", "generated_at", "apply_expires_at",
    "runtime_valid_until", "approved_commit", "mode",
    "source_enrollment_manifest_sha256", "events", "content_sha256",
})
_EVENT_FIELDS = frozenset({
    "event_id", "event_updated_at", "status", "visibility_status", "region",
    "timezone_name", "local_date", "local_start_time", "race_datetime",
    "manual_lock_flags", "control_updated_at", "control_mode",
    "next_refresh_at", "schedule_generation", "enrollment_manifest_sha256",
    "manifest_data_sha256", "enrollment_schedule_hash", "manual_pause_reason",
    "claim_token", "claim_generation", "claim_expires_at", "target_mode",
})


class CanaryError(ValueError):
    """Fail-closed canary validation error."""


@dataclass(frozen=True)
class LoadedCanaryManifest:
    data: dict[str, Any]
    raw: bytes
    raw_sha256: str
    content_sha256: str
    event_ids: tuple[int, int]


@dataclass(frozen=True)
class CanaryResult:
    outcome: str
    event_ids: tuple[int, int]
    activation_id: str = ""


def parse_canary_event_ids(value: Any) -> tuple[int, int]:
    if not isinstance(value, str):
        raise CanaryError("canary event IDs 必须为字符串")
    parts = value.split(",")
    if len(parts) != 2 or any(not re.fullmatch(r"[1-9][0-9]*", part) for part in parts):
        raise CanaryError("canary 必须恰好包含两个正整数 event ID")
    ids = tuple(int(part) for part in parts)
    if tuple(sorted(set(ids))) != ids:
        raise CanaryError("canary event IDs 必须唯一且按升序排列")
    return ids  # type: ignore[return-value]


def parse_canary_sha(value: Any) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise CanaryError("canary raw SHA-256 必须为 64 位小写 hex")
    return value


def read_bounded_manifest_stdin(stream: BinaryIO) -> bytes:
    raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not raw:
        raise CanaryError("manifest stdin 为空")
    if len(raw) > MAX_MANIFEST_BYTES:
        raise CanaryError("manifest stdin 超过 1 MiB")
    # A second read detects streams that ignored the requested bound.
    if stream.read(1):
        raise CanaryError("manifest stdin 含超限尾随字节")
    return raw


def _parse_dt(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise CanaryError(f"{label} 必须为 ISO-8601")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CanaryError(f"{label} 非法") from exc
    if django_timezone.is_naive(parsed) or parsed.utcoffset() != timedelta(0):
        raise CanaryError(f"{label} 必须为 UTC aware datetime")
    return parsed


def _exact(value: dict[str, Any], fields: frozenset[str], label: str) -> None:
    if frozenset(value) != fields:
        raise CanaryError(
            f"{label} 字段不匹配: missing={sorted(fields - frozenset(value))} "
            f"unknown={sorted(frozenset(value) - fields)}"
        )


def load_canary_manifest_bytes(
    raw: bytes,
    *,
    expected_raw_sha256: str,
    expected_commit: str,
    now: datetime | None = None,
    require_apply_fresh: bool = False,
    allow_expired_runtime: bool = False,
) -> LoadedCanaryManifest:
    expected_sha = parse_canary_sha(expected_raw_sha256)
    if not isinstance(expected_commit, str) or _OID_RE.fullmatch(expected_commit) is None:
        raise CanaryError("expected commit 必须为 40 位小写 Git OID")
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha:
        raise CanaryError("canary manifest raw SHA-256 不匹配")
    try:
        data = _parse_json(raw)
    except ValueError as exc:
        raise CanaryError(str(exc)) from exc
    _exact(data, _TOP_FIELDS, "manifest")
    if data["schema_version"] != SCHEMA_VERSION or data["mode"] != "enforce":
        raise CanaryError("manifest 必须为 schema_version=1、mode=enforce")
    if data["approved_commit"] != expected_commit or _OID_RE.fullmatch(data["approved_commit"] or "") is None:
        raise CanaryError("manifest approved_commit 不匹配")
    parse_canary_sha(data["source_enrollment_manifest_sha256"])
    generated = _parse_dt(data["generated_at"], "generated_at")
    apply_expires = _parse_dt(data["apply_expires_at"], "apply_expires_at")
    runtime_until = _parse_dt(data["runtime_valid_until"], "runtime_valid_until")
    if apply_expires != generated + timedelta(hours=24):
        raise CanaryError("apply_expires_at 必须等于 generated_at +24h")
    current = now or django_timezone.now()
    if not isinstance(current, datetime) or django_timezone.is_naive(current):
        raise CanaryError("manifest validation now 必须为 aware datetime")
    if require_apply_fresh and current >= apply_expires:
        raise CanaryError("canary promotion manifest apply 窗口已过期")
    if current >= runtime_until and not allow_expired_runtime:
        raise CanaryError("canary runtime 已过期")
    events = data["events"]
    if not isinstance(events, dict) or len(events) != 2:
        raise CanaryError("canary manifest 必须恰好包含两场")
    ids: list[int] = []
    race_times: list[datetime] = []
    for key, snapshot in events.items():
        if not isinstance(key, str) or re.fullmatch(r"[1-9][0-9]*", key) is None:
            raise CanaryError("非法 event key")
        event_id = int(key)
        if not isinstance(snapshot, dict):
            raise CanaryError(f"event {event_id} snapshot 必须为 object")
        _exact(snapshot, _EVENT_FIELDS, f"event {event_id}")
        if type(snapshot["event_id"]) is not int or snapshot["event_id"] != event_id:
            raise CanaryError(f"event {event_id} ID 不一致")
        if snapshot["control_mode"] != "shadow" or snapshot["target_mode"] != "enforce":
            raise CanaryError(f"event {event_id} control mode 合同不匹配")
        if snapshot["enrollment_manifest_sha256"] != data["source_enrollment_manifest_sha256"]:
            raise CanaryError(f"event {event_id} enrollment SHA 不一致")
        for field in ("manifest_data_sha256", "enrollment_schedule_hash"):
            parse_canary_sha(snapshot[field])
        if not isinstance(snapshot["schedule_generation"], int) or isinstance(snapshot["schedule_generation"], bool) or snapshot["schedule_generation"] <= 0:
            raise CanaryError(f"event {event_id} generation 非法")
        if (
            type(snapshot["claim_generation"]) is not int
            or snapshot["claim_generation"] < 0
            or not isinstance(snapshot["claim_token"], str)
            or not isinstance(snapshot["manual_pause_reason"], str)
            or not isinstance(snapshot["manual_lock_flags"], dict)
        ):
            raise CanaryError(f"event {event_id} control/lock 字段非法")
        for field in ("region", "timezone_name", "status", "visibility_status"):
            if not isinstance(snapshot[field], str) or not snapshot[field]:
                raise CanaryError(f"event {event_id}.{field} 必须为非空字符串")
        if snapshot["local_date"] is not None:
            try:
                date.fromisoformat(snapshot["local_date"])
            except (TypeError, ValueError) as exc:
                raise CanaryError(f"event {event_id}.local_date 非法") from exc
        if snapshot["local_start_time"] is not None:
            try:
                time.fromisoformat(snapshot["local_start_time"])
            except (TypeError, ValueError) as exc:
                raise CanaryError(f"event {event_id}.local_start_time 非法") from exc
        race_at = _parse_dt(snapshot["race_datetime"], f"event {event_id}.race_datetime")
        _parse_dt(snapshot["event_updated_at"], f"event {event_id}.event_updated_at")
        _parse_dt(snapshot["control_updated_at"], f"event {event_id}.control_updated_at")
        if snapshot["claim_expires_at"] is not None:
            _parse_dt(snapshot["claim_expires_at"], f"event {event_id}.claim_expires_at")
        if snapshot["next_refresh_at"] is not None:
            _parse_dt(snapshot["next_refresh_at"], f"event {event_id}.next_refresh_at")
        if snapshot["status"] != "scheduled" or snapshot["visibility_status"] != "published":
            raise CanaryError(f"event {event_id} 必须 scheduled/published")
        if snapshot["manual_lock_flags"] or snapshot["manual_pause_reason"] or snapshot["claim_token"]:
            raise CanaryError(f"event {event_id} 存在 lock/pause/claim")
        ids.append(event_id)
        race_times.append(race_at)
    if ids != sorted(set(ids)):
        raise CanaryError("events 必须按唯一数字 ID 升序")
    expected_runtime = max(race_times) + timedelta(minutes=30, hours=24)
    if runtime_until != expected_runtime:
        raise CanaryError("runtime_valid_until 必须覆盖 max(T)+30m+24h")
    content = parse_canary_sha(data["content_sha256"])
    payload = dict(data)
    payload.pop("content_sha256")
    if hashlib.sha256(_canonical_bytes(payload)).hexdigest() != content:
        raise CanaryError("manifest content SHA-256 不匹配")
    if raw != _canonical_bytes(data):
        raise CanaryError("manifest 不是 canonical JSON")
    return LoadedCanaryManifest(data, raw, actual_sha, content, tuple(ids))  # type: ignore[arg-type]


def _event_manifest_snapshot(event: RaceEvent, control: RaceEventLifecycleControl) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "event_updated_at": _iso_datetime(event.updated_at),
        "status": event.status,
        "visibility_status": event.visibility_status,
        "region": event.country_region,
        "timezone_name": event.timezone_name,
        "local_date": event.local_date.isoformat() if event.local_date else None,
        "local_start_time": event.local_start_time.isoformat() if event.local_start_time else None,
        "race_datetime": _iso_datetime(event.race_datetime),
        "manual_lock_flags": event.manual_lock_flags,
        "control_updated_at": _iso_datetime(control.updated_at),
        "control_mode": control.mode,
        "next_refresh_at": _iso_datetime(control.next_refresh_at),
        "schedule_generation": control.schedule_generation,
        "enrollment_manifest_sha256": control.enrollment_manifest_sha256,
        "manifest_data_sha256": _control_manifest_data_sha(control),
        "enrollment_schedule_hash": control.manifest_data.get("enrollment_schedule_hash", ""),
        "manual_pause_reason": control.manual_pause_reason,
        "claim_token": control.claim_token,
        "claim_generation": control.claim_generation,
        "claim_expires_at": _iso_datetime(control.claim_expires_at),
        "target_mode": "enforce",
    }


def build_canary_artifact(*, event_ids: list[int], approved_commit: str, now: datetime | None = None) -> bytes:
    if len(event_ids) != 2 or sorted(set(event_ids)) != event_ids or any(type(item) is not int or item <= 0 for item in event_ids):
        raise CanaryError("prepare 必须提供两个唯一、升序、正整数 event ID")
    if _OID_RE.fullmatch(approved_commit or "") is None:
        raise CanaryError("approved_commit 必须为 40 位小写 Git OID")
    events = list(RaceEvent.objects.filter(id__in=event_ids).order_by("id"))
    controls = {item.event_id: item for item in RaceEventLifecycleControl.objects.filter(event_id__in=event_ids)}
    if [event.id for event in events] != event_ids or set(controls) != set(event_ids):
        raise CanaryError("event/control cohort 不完整")
    source_shas = {control.enrollment_manifest_sha256 for control in controls.values()}
    generated = (now or django_timezone.now()).astimezone(timezone.utc)
    snapshots: dict[str, Any] = {}
    race_times: list[datetime] = []
    for event in events:
        control = controls[event.id]
        if event.status != "scheduled" or event.visibility_status != "published" or not event.race_datetime:
            raise CanaryError(f"event {event.id} 必须 scheduled/published 且有 race_datetime")
        if django_timezone.is_naive(event.race_datetime):
            raise CanaryError(f"event {event.id} race_datetime 必须为 aware")
        if event.manual_lock_flags or control.manual_pause_reason or control.claim_token or control.mode != "shadow":
            raise CanaryError(f"event {event.id} control/event 不可 promotion")
        if not control.enrollment_manifest_sha256 or not _SHA_RE.fullmatch(control.enrollment_manifest_sha256):
            raise CanaryError(f"event {event.id} enrollment SHA 非法")
        if _schedule_hash(event) != control.manifest_data.get("enrollment_schedule_hash"):
            raise CanaryError(f"event {event.id} schedule hash 漂移")
        snapshots[str(event.id)] = _event_manifest_snapshot(event, control)
        race_times.append(event.race_datetime.astimezone(timezone.utc))
    if len(source_shas) != 1:
        raise CanaryError("两场必须来自同一 enrollment manifest")
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat(),
        "apply_expires_at": (generated + timedelta(hours=24)).isoformat(),
        "runtime_valid_until": (max(race_times) + timedelta(minutes=30, hours=24)).isoformat(),
        "approved_commit": approved_commit,
        "mode": "enforce",
        "source_enrollment_manifest_sha256": next(iter(source_shas)),
        "events": snapshots,
    }
    payload["content_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return _canonical_bytes(payload)


def _acquire_advisory_lock() -> None:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_ADVISORY_LOCK_KEY])
    elif connection.vendor != "sqlite":
        raise CanaryError("数据库不支持 lifecycle canary advisory lock")


def _assert_closed() -> None:
    if not (
        getattr(settings, "RACE_EVENT_LIFECYCLE_ENABLED", None) is False
        and getattr(settings, "RACE_EVENT_LIFECYCLE_MODE", None) == "off"
    ):
        raise CanaryError("canary promotion/activation 只允许在严格 false/off 下执行")


def _assert_activation_runtime(manifest: LoadedCanaryManifest) -> None:
    if not (
        getattr(settings, "RACE_EVENT_LIFECYCLE_ENABLED", None) is True
        and getattr(settings, "RACE_EVENT_LIFECYCLE_MODE", None) == "enforce"
        and getattr(settings, "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256", "")
        == manifest.raw_sha256
        and getattr(settings, "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS", "")
        == ",".join(map(str, manifest.event_ids))
    ):
        raise CanaryError("activate 必须绑定当前 true/enforce runtime trust root")


def _load_locked_cohort(manifest: LoadedCanaryManifest) -> tuple[list[RaceEvent], list[RaceEventLifecycleControl]]:
    events = list(RaceEvent.objects.select_for_update().filter(id__in=manifest.event_ids).order_by("id"))
    controls = list(RaceEventLifecycleControl.objects.select_for_update().filter(event_id__in=manifest.event_ids).order_by("event_id"))
    if tuple(item.id for item in events) != manifest.event_ids or tuple(item.event_id for item in controls) != manifest.event_ids:
        raise CanaryError("event/control cohort 不完整")
    return events, controls


def _expected_evidence(manifest: LoadedCanaryManifest, *, state: str, activation_id: str = "", activated_at: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "raw_sha256": manifest.raw_sha256,
        "content_sha256": manifest.content_sha256,
        "event_ids": list(manifest.event_ids),
        "approved_commit": manifest.data["approved_commit"],
        "runtime_valid_until": manifest.data["runtime_valid_until"],
        "activation_state": state,
        "activation_id": activation_id,
        "activated_at": activated_at,
    }


def _assert_db_matches(manifest: LoadedCanaryManifest, events: list[RaceEvent], controls: list[RaceEventLifecycleControl], *, allow_promoted: bool) -> None:
    if RaceEventLifecycleControl.objects.exclude(event_id__in=manifest.event_ids).filter(mode="enforce").exists():
        raise CanaryError("存在范围外 enforce control")
    for event, control in zip(events, controls, strict=True):
        frozen = manifest.data["events"][str(event.id)]
        if allow_promoted:
            base_manifest_data = dict(control.manifest_data)
            base_manifest_data.pop("enforce_canary", None)
            frozen_runtime = base_manifest_data.pop("enforce_canary_frozen", None)
            expected_frozen_runtime = {
                "schedule_generation": frozen["schedule_generation"],
                "enrollment_manifest_sha256": frozen["enrollment_manifest_sha256"],
                "enrollment_schedule_hash": frozen["enrollment_schedule_hash"],
            }
            if frozen_runtime != expected_frozen_runtime:
                raise CanaryError(f"event {event.id} frozen runtime evidence 漂移")
            if hashlib.sha256(_canonical_bytes(base_manifest_data)).hexdigest() != frozen["manifest_data_sha256"]:
                raise CanaryError(f"event {event.id} enrollment manifest_data 漂移")
            # Reactivation must tolerate only the lifecycle's own monotonic
            # runtime fields.  Schedule, enrollment, authority and the cohort
            # trust root remain frozen.  An outstanding claim or an operator
            # pause/lock still fails closed.
            static_event_fields = (
                "visibility_status", "region", "timezone_name", "local_date",
                "local_start_time", "race_datetime", "manual_lock_flags",
            )
            current = _event_manifest_snapshot(event, control)
            if any(current[field] != frozen[field] for field in static_event_fields):
                raise CanaryError(f"event {event.id} 静态授权字段漂移")
            allowed_statuses = {"scheduled", "running", "finished"}
            if frozen["status"] != "scheduled" or event.status not in allowed_statuses:
                raise CanaryError(f"event {event.id} 生命周期状态不可重新激活")
            _assert_canary_status_provenance(
                manifest=manifest,
                event=event,
                control=control,
            )
            if (
                control.mode != "enforce"
                or control.manual_pause_reason
                or control.claim_token
                or event.manual_lock_flags
            ):
                raise CanaryError(f"event {event.id} 存在 mode/lock/pause/claim 漂移")
        else:
            current = _event_manifest_snapshot(event, control)
            if current != frozen:
                raise CanaryError(f"event {event.id} 或 control 快照漂移")
        if control.schedule_generation != frozen["schedule_generation"] or _schedule_hash(event) != frozen["enrollment_schedule_hash"]:
            raise CanaryError(f"event {event.id} schedule/generation 漂移")


def _assert_canary_status_provenance(
    *,
    manifest: LoadedCanaryManifest,
    event: RaceEvent,
    control: RaceEventLifecycleControl,
) -> None:
    """Prove non-scheduled state came from this exact canary lifecycle."""
    transitions = list(
        RaceEventLifecycleTransition.objects.filter(
            event=event,
            record_kind=RaceEventLifecycleTransitionKind.APPLIED,
            schedule_generation=control.schedule_generation,
        ).order_by("effective_at", "id")
    )
    expected_edges: list[tuple[str, str, str]]
    if event.status == "scheduled":
        expected_edges = []
    elif event.status == "running":
        expected_edges = [
            ("scheduled", "running", "time_reached_race_datetime"),
        ]
    else:
        expected_edges = [
            ("scheduled", "running", "time_reached_race_datetime"),
            ("running", "finished", "time_t_plus_30"),
        ]
    if len(transitions) != len(expected_edges):
        raise CanaryError(f"event {event.id} lifecycle applied transition 链不完整")

    frozen = manifest.data["events"][str(event.id)]
    race_at = _parse_dt(frozen["race_datetime"], f"event {event.id}.race_datetime")
    expected_metadata = {
        "schema_version": 1,
        "raw_sha256": manifest.raw_sha256,
        "content_sha256": manifest.content_sha256,
        "event_ids": list(manifest.event_ids),
        "approved_commit": manifest.data["approved_commit"],
    }
    previous_at: datetime | None = None
    for index, (transition, edge) in enumerate(
        zip(transitions, expected_edges, strict=True)
    ):
        from_status, to_status, reason_code = edge
        metadata = transition.metadata.get("enforce_canary") if isinstance(
            transition.metadata, dict
        ) else None
        if (
            transition.from_status != from_status
            or transition.to_status != to_status
            or transition.reason_code != reason_code
            or transition.trigger_task != "advance_race_event_lifecycle_task"
            or transition.source_authority != "time_rule"
            or not isinstance(metadata, dict)
            or frozenset(metadata) != frozenset((*expected_metadata, "activation_id"))
            or any(metadata.get(key) != value for key, value in expected_metadata.items())
            or _SHA_RE.fullmatch(metadata.get("activation_id", "")) is None
        ):
            raise CanaryError(f"event {event.id} lifecycle applied transition provenance 不匹配")
        if transition.effective_at < race_at:
            raise CanaryError(f"event {event.id} lifecycle transition 时间早于 T")
        if index == 0 and transition.effective_at >= race_at + timedelta(minutes=30):
            raise CanaryError(f"event {event.id} running transition 不在 T 到 T+30 窗口")
        if index == 1 and transition.effective_at < race_at + timedelta(minutes=30):
            raise CanaryError(f"event {event.id} finished transition 早于 T+30")
        if previous_at is not None and transition.effective_at < previous_at:
            raise CanaryError(f"event {event.id} lifecycle transition 时间不连续")
        previous_at = transition.effective_at


def promote_canary(manifest: LoadedCanaryManifest, *, apply: bool) -> CanaryResult:
    if apply:
        _assert_closed()
    context = _SQLITE_LOCK if connection.vendor == "sqlite" else _NullContext()
    with context:
        with transaction.atomic():
            _acquire_advisory_lock()
            events, controls = _load_locked_cohort(manifest)
            already = [control.manifest_data.get("enforce_canary") for control in controls]
            expected_inactive = _expected_evidence(manifest, state="inactive")
            if all(control.mode == "enforce" and evidence == expected_inactive for control, evidence in zip(controls, already, strict=True)):
                _assert_db_matches(manifest, events, controls, allow_promoted=True)
                return CanaryResult("replay", manifest.event_ids)
            if any(control.mode != "shadow" or evidence is not None for control, evidence in zip(controls, already, strict=True)):
                raise CanaryError("control 已由不同 canary promotion 或处于部分状态")
            _assert_db_matches(manifest, events, controls, allow_promoted=False)
            if not apply:
                return CanaryResult("would_apply", manifest.event_ids)
            applied_at = django_timezone.now().astimezone(timezone.utc).isoformat()
            evidence = dict(expected_inactive)
            for control in controls:
                data = dict(control.manifest_data)
                data["enforce_canary"] = evidence
                data["enforce_canary_frozen"] = {
                    "schedule_generation": control.schedule_generation,
                    "enrollment_manifest_sha256": control.enrollment_manifest_sha256,
                    "enrollment_schedule_hash": control.manifest_data.get(
                        "enrollment_schedule_hash", ""
                    ),
                }
                control.mode = "enforce"
                control.manifest_data = data
                control.updated_at = django_timezone.now()
            RaceEventLifecycleControl.objects.bulk_update(controls, ["mode", "manifest_data", "updated_at"])
            detail = {
                "schema_version": 1,
                "raw_sha256": manifest.raw_sha256,
                "content_sha256": manifest.content_sha256,
                "approved_commit": manifest.data["approved_commit"],
                "event_ids": list(manifest.event_ids),
                "from_mode": "shadow",
                "to_mode": "enforce",
                "activation_state": "inactive",
                "applied_at": applied_at,
            }
            OperationLog.objects.create(
                action_type="lifecycle_enforce_canary_applied",
                target_type="race_event_lifecycle_canary",
                target_id=manifest.raw_sha256,
                detail=_canonical_bytes(detail).decode("utf-8").rstrip("\n"),
            )
            return CanaryResult("applied", manifest.event_ids)


class _NullContext:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


def verify_or_mutate_canary(manifest: LoadedCanaryManifest, *, expected_state: str, activate: bool = False, disarm: bool = False) -> CanaryResult:
    if expected_state not in {"inactive", "active"} or activate and disarm:
        raise CanaryError("非法 canary verify action")
    if activate:
        _assert_activation_runtime(manifest)
    elif disarm:
        _assert_closed()
    context = _SQLITE_LOCK if connection.vendor == "sqlite" else _NullContext()
    with context:
        with transaction.atomic():
            _acquire_advisory_lock()
            events, controls = _load_locked_cohort(manifest)
            _assert_db_matches(manifest, events, controls, allow_promoted=True)
            evidence = [control.manifest_data.get("enforce_canary") for control in controls]
            if any(control.mode != "enforce" for control in controls):
                raise CanaryError("canary control 尚未 promotion")
            if activate:
                if all(isinstance(item, dict) and item.get("activation_state") == "active" for item in evidence):
                    activation_ids = {item.get("activation_id") for item in evidence}
                    if len(activation_ids) == 1 and next(iter(activation_ids), "") and all(item == evidence[0] for item in evidence):
                        return CanaryResult("replay", manifest.event_ids, next(iter(activation_ids)))
                    raise CanaryError("canary active evidence 不一致")
                expected = _expected_evidence(manifest, state="inactive")
                if any(item != expected for item in evidence):
                    raise CanaryError("canary 必须由完整 inactive cohort 原子激活")
                activation_id = secrets.token_hex(32)
                activated_at = django_timezone.now().astimezone(timezone.utc).isoformat()
                active = _expected_evidence(manifest, state="active", activation_id=activation_id, activated_at=activated_at)
                for control in controls:
                    data = dict(control.manifest_data)
                    data["enforce_canary"] = active
                    control.manifest_data = data
                    control.updated_at = django_timezone.now()
                RaceEventLifecycleControl.objects.bulk_update(controls, ["manifest_data", "updated_at"])
                return CanaryResult("activated", manifest.event_ids, activation_id)
            if disarm:
                inactive = _expected_evidence(manifest, state="inactive")
                if all(item == inactive for item in evidence):
                    return CanaryResult("replay", manifest.event_ids)
                if not _cohort_active_evidence(evidence, manifest):
                    raise CanaryError("canary active evidence 不完整，拒绝 disarm")
                for control in controls:
                    data = dict(control.manifest_data)
                    data["enforce_canary"] = inactive
                    control.manifest_data = data
                    control.updated_at = django_timezone.now()
                RaceEventLifecycleControl.objects.bulk_update(controls, ["manifest_data", "updated_at"])
                return CanaryResult("disarmed", manifest.event_ids)
            if expected_state == "inactive":
                expected = _expected_evidence(manifest, state="inactive")
                if any(item != expected for item in evidence):
                    raise CanaryError("inactive canary evidence 不一致")
                return CanaryResult("verified_inactive", manifest.event_ids)
            if not _cohort_active_evidence(evidence, manifest):
                raise CanaryError("active canary evidence 不一致")
            return CanaryResult("verified_active", manifest.event_ids, evidence[0]["activation_id"])


def _cohort_active_evidence(evidence: list[Any], manifest: LoadedCanaryManifest) -> bool:
    if len(evidence) != 2 or not all(isinstance(item, dict) for item in evidence):
        return False
    first = evidence[0]
    if evidence[1] != first or first.get("activation_state") != "active":
        return False
    activation_id = first.get("activation_id")
    activated_at = first.get("activated_at")
    if not isinstance(activation_id, str) or _SHA_RE.fullmatch(activation_id) is None or not activated_at:
        return False
    return first == _expected_evidence(manifest, state="active", activation_id=activation_id, activated_at=activated_at)


def validate_active_canary_cohort(*, raw_sha256: str, event_ids_text: str, expected_activation_id: str = "", lock: bool = False, now: datetime | None = None) -> tuple[bool, str]:
    try:
        raw_sha = parse_canary_sha(raw_sha256)
        event_ids = parse_canary_event_ids(event_ids_text)
    except CanaryError:
        return False, "canary_runtime_settings_invalid"
    query = RaceEventLifecycleControl.objects.filter(event_id__in=event_ids).order_by("event_id")
    if lock:
        query = query.select_for_update()
    controls = list(query)
    if tuple(item.event_id for item in controls) != event_ids:
        return False, "canary_control_cohort_incomplete"
    evidence = [item.manifest_data.get("enforce_canary") for item in controls]
    if any(control.mode != "enforce" for control in controls):
        return False, "canary_control_mode_invalid"
    if not all(isinstance(item, dict) for item in evidence) or evidence[0] != evidence[1]:
        return False, "canary_activation_evidence_inconsistent"
    item = evidence[0]
    expected_fields = frozenset({
        "schema_version", "raw_sha256", "content_sha256", "event_ids",
        "approved_commit", "runtime_valid_until", "activation_state",
        "activation_id", "activated_at",
    })
    activation_id = item.get("activation_id", "")
    if (
        frozenset(item) != expected_fields
        or item.get("schema_version") != 1
        or item.get("raw_sha256") != raw_sha
        or _SHA_RE.fullmatch(item.get("content_sha256", "")) is None
        or item.get("event_ids") != list(event_ids)
        or _OID_RE.fullmatch(item.get("approved_commit", "")) is None
        or item.get("activation_state") != "active"
        or _SHA_RE.fullmatch(activation_id or "") is None
        or not item.get("activated_at")
    ):
        return False, "canary_activation_evidence_invalid"
    try:
        _parse_dt(item.get("activated_at"), "activated_at")
        if (now or django_timezone.now()) >= _parse_dt(item.get("runtime_valid_until"), "runtime_valid_until"):
            return False, "canary_runtime_expired"
    except CanaryError:
        return False, "canary_activation_evidence_invalid"
    if expected_activation_id and activation_id != expected_activation_id:
        return False, "canary_activation_handshake_mismatch"
    return True, activation_id


def validate_event_for_enforce(
    *, event: RaceEvent, control: RaceEventLifecycleControl, raw_sha256: str,
    event_ids_text: str, expected_activation_id: str = "", now: datetime | None = None,
) -> str | None:
    try:
        raw_sha = parse_canary_sha(raw_sha256)
        event_ids = parse_canary_event_ids(event_ids_text)
    except CanaryError:
        return "canary_runtime_settings_invalid"
    if event.id not in event_ids:
        return "canary_event_out_of_scope"
    valid, cohort_result = validate_active_canary_cohort(
        raw_sha256=raw_sha,
        event_ids_text=event_ids_text,
        expected_activation_id=expected_activation_id,
        lock=True,
        now=now,
    )
    if not valid:
        return cohort_result
    evidence = control.manifest_data.get("enforce_canary")
    if not isinstance(evidence, dict):
        return "canary_evidence_missing"
    if evidence.get("raw_sha256") != raw_sha or evidence.get("event_ids") != list(event_ids):
        return "canary_evidence_mismatch"
    if evidence.get("activation_state") != "active" or _SHA_RE.fullmatch(evidence.get("activation_id", "")) is None:
        return "canary_not_active"
    if expected_activation_id and evidence.get("activation_id") != expected_activation_id:
        return "canary_activation_handshake_mismatch"
    try:
        if (now or django_timezone.now()) >= _parse_dt(evidence.get("runtime_valid_until"), "runtime_valid_until"):
            return "canary_runtime_expired"
    except CanaryError:
        return "canary_evidence_invalid"
    if (
        event.visibility_status != "published"
        or event.status not in {"scheduled", "running"}
        or event.manual_lock_flags
        or control.manual_pause_reason
    ):
        return "canary_event_not_writable"
    frozen = control.manifest_data.get("enforce_canary_frozen")
    if not isinstance(frozen, dict) or frozenset(frozen) != frozenset({
        "schedule_generation", "enrollment_manifest_sha256",
        "enrollment_schedule_hash",
    }):
        return "canary_control_invalid"
    if (
        control.schedule_generation != frozen["schedule_generation"]
        or control.enrollment_manifest_sha256 != frozen["enrollment_manifest_sha256"]
        or control.manifest_data.get("enrollment_schedule_hash")
        != frozen["enrollment_schedule_hash"]
    ):
        return "canary_control_invalid"
    if _schedule_hash(event) != control.manifest_data.get("enrollment_schedule_hash"):
        return "canary_schedule_drift"
    return None

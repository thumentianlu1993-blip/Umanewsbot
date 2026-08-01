"""Strict, read-only preparation and atomic application of lifecycle enrollment.

This module deliberately has no provider, Celery, news, or publication hooks.
It is the single implementation of the v2 manifest loader and database
preflight used by both dry-run and apply.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone as django_timezone

from stable.models import (
    RaceEvent,
    RaceEventLifecycleControl,
    RaceEventStatus,
)
from stable.services.race_event_lifecycle import (
    _initial_next_refresh,
    _validate_timezone,
    decide_race_lifecycle,
)


MAX_EVENTS = 20
MAX_MANIFEST_BYTES = 1024 * 1024
SCHEMA_VERSION = 2
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_SUPPORTED_REGIONS = frozenset(
    {"japan", "hong_kong", "united_kingdom", "france", "united_states"}
)
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "generated_at",
        "expires_at",
        "approved_commit",
        "mode",
        "events",
        "content_sha256",
    }
)
_EVENT_FIELDS = frozenset(
    {
        "event_id",
        "event_updated_at",
        "region",
        "timezone_name",
        "allowed_us_zones",
        "status",
        "priority",
        "is_featured",
        "visibility_status",
        "eligibility",
        "local_date",
        "local_start_time",
        "race_datetime",
        "manual_lock_flags",
        "enrollment_schedule_hash",
        "expected_control",
        "predicted_decision",
        "predicted_next_refresh_at",
    }
)
_ELIGIBILITY_FIELDS = frozenset(
    {"is_key_race", "is_published", "is_cancelled"}
)
_PREDICTED_DECISION_FIELDS = frozenset(
    {"action", "to_status", "reason_code", "effective_at", "error_message"}
)


class EnrollmentError(ValueError):
    """Fail-closed enrollment validation error."""


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _is_git_oid(value: Any) -> bool:
    return isinstance(value, str) and _GIT_OID_RE.fullmatch(value) is not None


@dataclass(frozen=True)
class LoadedEnrollmentManifest:
    data: dict[str, Any]
    raw_sha256: str
    content_sha256: str
    event_ids: tuple[int, ...]
    path: Path


def read_manifest_bytes(manifest_path: str | Path) -> bytes:
    """Read a regular manifest with a hard size bound and no symlink following."""
    path = Path(manifest_path)
    try:
        before = path.lstat()
    except OSError as exc:
        raise EnrollmentError(f"manifest 无法读取: {exc}") from exc
    if stat.S_ISLNK(before.st_mode):
        raise EnrollmentError("manifest 不得为 symlink")
    if not stat.S_ISREG(before.st_mode):
        raise EnrollmentError("manifest 必须为普通文件")
    if before.st_size > MAX_MANIFEST_BYTES:
        raise EnrollmentError("manifest 超过 1 MiB")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise EnrollmentError(f"manifest 无法安全打开: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise EnrollmentError("manifest 必须为普通文件")
        metadata_fields = (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        before_identity = tuple(getattr(before, field) for field in metadata_fields)
        opened_identity = tuple(getattr(opened, field) for field in metadata_fields)
        if opened_identity != before_identity:
            raise EnrollmentError("manifest 在检查与打开之间发生变化")
        if opened.st_size > MAX_MANIFEST_BYTES:
            raise EnrollmentError("manifest 超过 1 MiB")
        chunks: list[bytes] = []
        remaining = MAX_MANIFEST_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise EnrollmentError("manifest 超过 1 MiB")
        after = os.fstat(descriptor)
        after_identity = tuple(getattr(after, field) for field in metadata_fields)
        if after_identity != opened_identity or len(raw) != opened.st_size:
            raise EnrollmentError("manifest 在读取过程中发生变化")
        return raw
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class EnrollmentPreflight:
    manifest: LoadedEnrollmentManifest
    events: tuple[RaceEvent, ...]
    existing_controls: dict[int, RaceEventLifecycleControl]
    outcomes: dict[int, str]

    @property
    def would_create(self) -> int:
        return sum(value == "would_create" for value in self.outcomes.values())

    @property
    def replayed(self) -> int:
        return sum(value == "replay" for value in self.outcomes.values())


def _canonicalize_json(value: Any, *, numeric_event_keys: bool = False) -> Any:
    """Return a deterministically ordered JSON value.

    JSON object keys are strings, so ``sort_keys=True`` orders event IDs as
    ``10, 9``.  The manifest contract requires numeric event ordering.  All
    ordinary objects remain lexicographically ordered; only the value of an
    ``events`` key receives integer-key ordering.
    """
    if isinstance(value, dict):
        try:
            keys = (
                sorted(value, key=lambda item: int(item))
                if numeric_event_keys
                else sorted(value)
            )
        except (TypeError, ValueError) as exc:
            raise EnrollmentError("events key 必须可按数值排序") from exc
        return {
            key: _canonicalize_json(
                value[key],
                numeric_event_keys=(not numeric_event_keys and key == "events"),
            )
            for key in keys
        }
    if isinstance(value, list):
        return [_canonicalize_json(item) for item in value]
    return value


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    try:
        body = json.dumps(
            _canonicalize_json(payload),
            ensure_ascii=False,
            sort_keys=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise EnrollmentError(f"manifest 无法 canonicalize: {exc}") from exc
    return (body + "\n").encode("utf-8")


def _reject_duplicate_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EnrollmentError(f"manifest 含重复 JSON key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise EnrollmentError(f"manifest 不允许 JSON constant: {value}")


def _parse_json(raw: bytes) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise EnrollmentError("manifest 不允许 UTF-8 BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EnrollmentError("manifest 必须为 UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_key,
            parse_constant=_reject_json_constant,
        )
    except EnrollmentError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise EnrollmentError(f"manifest JSON 解析失败: {exc}") from exc
    if not isinstance(value, dict):
        raise EnrollmentError("manifest 顶层必须为 object")
    return value


def peek_manifest_schema(manifest_path: str | Path) -> Any:
    """Return schema_version through the same bounded strict file reader."""
    return _parse_json(read_manifest_bytes(manifest_path)).get("schema_version")


def _ensure_exact_fields(
    value: dict[str, Any],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    actual = frozenset(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise EnrollmentError(
            f"{label} 字段不匹配: missing={missing} unknown={unknown}"
        )


def _parse_aware_datetime(value: Any, *, label: str, require_utc: bool = False) -> datetime:
    if not isinstance(value, str):
        raise EnrollmentError(f"{label} 必须为 ISO-8601 字符串")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise EnrollmentError(f"{label} 不是合法 ISO-8601: {value!r}") from exc
    if django_timezone.is_naive(parsed):
        raise EnrollmentError(f"{label} 必须包含时区")
    if require_utc and parsed.utcoffset() != timedelta(0):
        raise EnrollmentError(f"{label} 必须使用 UTC offset")
    return parsed


def _optional_iso_datetime(value: Any, *, label: str) -> datetime | None:
    if value is None:
        return None
    return _parse_aware_datetime(value, label=label)


def _validate_expected_control(value: Any, *, event_id: int) -> None:
    if not isinstance(value, dict):
        raise EnrollmentError(f"event {event_id}: expected_control 必须为 object")
    state = value.get("state")
    if state == "absent":
        _ensure_exact_fields(
            value, frozenset({"state"}), label=f"event {event_id}.expected_control"
        )
        return
    if state != "present":
        raise EnrollmentError(
            f"event {event_id}: expected_control.state 必须为 absent|present"
        )
    fields = frozenset(
        {
            "state",
            "manifest_sha256",
            "mode",
            "generation",
            "next_refresh_at",
            "manifest_data_sha256",
        }
    )
    _ensure_exact_fields(value, fields, label=f"event {event_id}.expected_control")
    if not _is_sha256(value["manifest_sha256"]):
        raise EnrollmentError(f"event {event_id}: control manifest SHA 非法")
    if value["mode"] != "shadow":
        raise EnrollmentError(f"event {event_id}: control mode 必须为 shadow")
    if not isinstance(value["generation"], int) or isinstance(value["generation"], bool):
        raise EnrollmentError(f"event {event_id}: control generation 必须为整数")
    if value["generation"] <= 0:
        raise EnrollmentError(f"event {event_id}: control generation 必须大于 0")
    if value["next_refresh_at"] is not None:
        _parse_aware_datetime(
            value["next_refresh_at"],
            label=f"event {event_id}.expected_control.next_refresh_at",
        )
    if not _is_sha256(value["manifest_data_sha256"]):
        raise EnrollmentError(f"event {event_id}: control manifest_data SHA 非法")


def _validate_event_snapshot(event_id: int, snapshot: Any) -> None:
    if not isinstance(snapshot, dict):
        raise EnrollmentError(f"event {event_id}: snapshot 必须为 object")
    _ensure_exact_fields(snapshot, _EVENT_FIELDS, label=f"event {event_id}")
    if (
        not isinstance(snapshot["event_id"], int)
        or isinstance(snapshot["event_id"], bool)
        or snapshot["event_id"] != event_id
    ):
        raise EnrollmentError(f"event {event_id}: event_id 与 key 不一致")
    _parse_aware_datetime(
        snapshot["event_updated_at"], label=f"event {event_id}.event_updated_at"
    )
    if (
        not isinstance(snapshot["region"], str)
        or snapshot["region"] not in _SUPPORTED_REGIONS
    ):
        raise EnrollmentError(f"event {event_id}: 不支持 region={snapshot['region']!r}")
    if not isinstance(snapshot["timezone_name"], str):
        raise EnrollmentError(f"event {event_id}: timezone_name 必须为字符串")

    zones = snapshot["allowed_us_zones"]
    if not isinstance(zones, list) or any(not isinstance(zone, str) for zone in zones):
        raise EnrollmentError(f"event {event_id}: allowed_us_zones 必须为字符串数组")
    if zones != sorted(set(zones)):
        raise EnrollmentError(f"event {event_id}: allowed_us_zones 必须去重排序")
    if snapshot["region"] == "united_states":
        if not zones:
            raise EnrollmentError(f"event {event_id}: 美国赛事必须提供时区 allowlist")
        if any(not zone.startswith("America/") for zone in zones):
            raise EnrollmentError(f"event {event_id}: 美国时区必须为 America/*")
        allowed_zones: frozenset[str] | None = frozenset(zones)
    else:
        if zones:
            raise EnrollmentError(f"event {event_id}: 非美国赛事不得提供 US allowlist")
        allowed_zones = None
    timezone_error = _validate_timezone(
        snapshot["timezone_name"], snapshot["region"], allowed_zones
    )
    if timezone_error:
        raise EnrollmentError(f"event {event_id}: {timezone_error}")

    for field in ("status", "priority", "visibility_status"):
        if not isinstance(snapshot[field], str) or not snapshot[field]:
            raise EnrollmentError(f"event {event_id}: {field} 必须为非空字符串")
    if not isinstance(snapshot["is_featured"], bool):
        raise EnrollmentError(f"event {event_id}: is_featured 必须为 boolean")
    eligibility = snapshot["eligibility"]
    if not isinstance(eligibility, dict):
        raise EnrollmentError(f"event {event_id}: eligibility 必须为 object")
    _ensure_exact_fields(
        eligibility, _ELIGIBILITY_FIELDS, label=f"event {event_id}.eligibility"
    )
    if any(not isinstance(eligibility[field], bool) for field in _ELIGIBILITY_FIELDS):
        raise EnrollmentError(f"event {event_id}: eligibility 值必须为 boolean")

    if snapshot["local_date"] is not None:
        try:
            date.fromisoformat(snapshot["local_date"])
        except (TypeError, ValueError) as exc:
            raise EnrollmentError(f"event {event_id}: local_date 非法") from exc
    if snapshot["local_start_time"] is not None:
        try:
            time.fromisoformat(snapshot["local_start_time"])
        except (TypeError, ValueError) as exc:
            raise EnrollmentError(f"event {event_id}: local_start_time 非法") from exc
    _optional_iso_datetime(
        snapshot["race_datetime"], label=f"event {event_id}.race_datetime"
    )
    if not isinstance(snapshot["manual_lock_flags"], dict):
        raise EnrollmentError(f"event {event_id}: manual_lock_flags 必须为 object")
    if not _is_sha256(snapshot["enrollment_schedule_hash"]):
        raise EnrollmentError(f"event {event_id}: schedule SHA 非法")
    _validate_expected_control(snapshot["expected_control"], event_id=event_id)

    predicted = snapshot["predicted_decision"]
    if not isinstance(predicted, dict):
        raise EnrollmentError(f"event {event_id}: predicted_decision 必须为 object")
    _ensure_exact_fields(
        predicted,
        _PREDICTED_DECISION_FIELDS,
        label=f"event {event_id}.predicted_decision",
    )
    if (
        not isinstance(predicted["action"], str)
        or predicted["action"] not in {"noop", "transition", "error"}
    ):
        raise EnrollmentError(f"event {event_id}: predicted action 非法")
    for field in ("to_status", "reason_code", "error_message"):
        if not isinstance(predicted[field], str):
            raise EnrollmentError(f"event {event_id}: predicted {field} 必须为字符串")
    if predicted["effective_at"] is not None:
        _parse_aware_datetime(
            predicted["effective_at"],
            label=f"event {event_id}.predicted_decision.effective_at",
        )
    if snapshot["predicted_next_refresh_at"] is not None:
        _parse_aware_datetime(
            snapshot["predicted_next_refresh_at"],
            label=f"event {event_id}.predicted_next_refresh_at",
        )


def load_enrollment_manifest(
    manifest_path: str | Path,
    *,
    expected_raw_sha256: str,
    expected_commit: str,
    now: datetime | None = None,
) -> LoadedEnrollmentManifest:
    """Load and fully validate a v2 manifest without touching the database."""
    path = Path(manifest_path)
    raw = read_manifest_bytes(path)

    if not _is_sha256(expected_raw_sha256):
        raise EnrollmentError("manifest 原始 SHA-256 必须为 64 位小写 hex")
    raw_sha = hashlib.sha256(raw).hexdigest()
    if raw_sha != expected_raw_sha256:
        raise EnrollmentError(
            f"manifest 原始 SHA-256 不匹配: expected={expected_raw_sha256} actual={raw_sha}"
        )
    data = _parse_json(raw)
    _ensure_exact_fields(data, _TOP_LEVEL_FIELDS, label="manifest")
    if data["schema_version"] != SCHEMA_VERSION:
        raise EnrollmentError("此 loader 只接受 schema_version=2")
    if data["mode"] != "shadow":
        raise EnrollmentError("manifest mode 必须为 shadow")
    if not _is_git_oid(data["approved_commit"]):
        raise EnrollmentError("approved_commit 必须为 40 位小写 Git OID")
    if not _is_git_oid(expected_commit):
        raise EnrollmentError("--expected-commit 必须为 40 位小写 Git OID")
    if data["approved_commit"] != expected_commit:
        raise EnrollmentError("manifest approved_commit 与 --expected-commit 不一致")
    generated_at = _parse_aware_datetime(
        data["generated_at"], label="generated_at", require_utc=True
    )
    expires_at = _parse_aware_datetime(
        data["expires_at"], label="expires_at", require_utc=True
    )
    if expires_at <= generated_at:
        raise EnrollmentError("expires_at 必须晚于 generated_at")
    current_time = now or django_timezone.now()
    if django_timezone.is_naive(current_time):
        raise EnrollmentError("preflight now 必须为 aware datetime")
    if current_time >= expires_at:
        raise EnrollmentError("manifest 已过期")

    content_sha = data["content_sha256"]
    if not _is_sha256(content_sha):
        raise EnrollmentError("content_sha256 必须为 64 位小写 hex")
    payload = dict(data)
    payload.pop("content_sha256")
    computed_content_sha = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    if computed_content_sha != content_sha:
        raise EnrollmentError("manifest content_sha256 不匹配")
    if raw != _canonical_bytes(data):
        raise EnrollmentError("manifest 文件不是 canonical JSON")

    events = data["events"]
    if not isinstance(events, dict):
        raise EnrollmentError("manifest.events 必须为 object")
    if not 1 <= len(events) <= MAX_EVENTS:
        raise EnrollmentError("manifest.events 必须包含 1–20 场")
    event_ids: list[int] = []
    for key, snapshot in events.items():
        if not isinstance(key, str) or not re.fullmatch(r"[1-9][0-9]*", key):
            raise EnrollmentError(f"非法 event key: {key!r}")
        event_id = int(key)
        event_ids.append(event_id)
        _validate_event_snapshot(event_id, snapshot)
    if event_ids != sorted(event_ids):
        raise EnrollmentError("manifest.events 必须按数字 event ID 升序")

    return LoadedEnrollmentManifest(
        data=data,
        raw_sha256=raw_sha,
        content_sha256=content_sha,
        event_ids=tuple(event_ids),
        path=path,
    )


def _iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if django_timezone.is_naive(value):
        raise EnrollmentError("数据库 datetime 必须为 aware")
    return value.astimezone(timezone.utc).isoformat()


def _schedule_hash(event: RaceEvent) -> str:
    payload = {
        "local_date": event.local_date.isoformat() if event.local_date else None,
        "local_start_time": (
            event.local_start_time.isoformat() if event.local_start_time else None
        ),
        "race_datetime": _iso_datetime(event.race_datetime),
        "timezone_name": event.timezone_name,
    }
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _manifest_data_for(
    manifest: LoadedEnrollmentManifest,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "content_sha256": manifest.content_sha256,
        "enrollment_schedule_hash": snapshot["enrollment_schedule_hash"],
        "allowed_us_zones": snapshot["allowed_us_zones"],
    }


def _control_manifest_data_sha(control: RaceEventLifecycleControl) -> str:
    return hashlib.sha256(_canonical_bytes(control.manifest_data)).hexdigest()


def _control_snapshot(control: RaceEventLifecycleControl) -> dict[str, Any]:
    return {
        "state": "present",
        "manifest_sha256": control.enrollment_manifest_sha256,
        "mode": control.mode,
        "generation": control.schedule_generation,
        "next_refresh_at": _iso_datetime(control.next_refresh_at),
        "manifest_data_sha256": _control_manifest_data_sha(control),
    }


def _event_snapshot_values(event: RaceEvent) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "event_updated_at": _iso_datetime(event.updated_at),
        "region": event.country_region,
        "timezone_name": event.timezone_name,
        "status": event.status,
        "priority": event.priority,
        "is_featured": event.is_featured,
        "visibility_status": event.visibility_status,
        "eligibility": {
            "is_key_race": event.is_key_race,
            "is_published": event.visibility_status == "published",
            "is_cancelled": event.status == RaceEventStatus.CANCELLED,
        },
        "local_date": event.local_date.isoformat() if event.local_date else None,
        "local_start_time": (
            event.local_start_time.isoformat() if event.local_start_time else None
        ),
        "race_datetime": _iso_datetime(event.race_datetime),
        "manual_lock_flags": event.manual_lock_flags,
        "enrollment_schedule_hash": _schedule_hash(event),
    }


def _validate_enrollment_eligibility(
    event: RaceEvent,
    *,
    allowed_us_zones: list[str],
) -> None:
    if event.visibility_status != "published":
        raise EnrollmentError(f"event {event.id}: 未发布")
    if event.status != RaceEventStatus.SCHEDULED:
        raise EnrollmentError(f"event {event.id}: status 必须为 scheduled")
    if event.country_region not in _SUPPORTED_REGIONS:
        raise EnrollmentError(f"event {event.id}: 不支持地区 {event.country_region!r}")
    if event.local_date is None:
        raise EnrollmentError(f"event {event.id}: local_date 为空")
    if event.manual_lock_flags:
        raise EnrollmentError(f"event {event.id}: 存在 manual_lock_flags")
    if event.race_datetime is not None and django_timezone.is_naive(event.race_datetime):
        raise EnrollmentError(f"event {event.id}: race_datetime 必须为 aware")
    zones = frozenset(allowed_us_zones) if event.country_region == "united_states" else None
    timezone_error = _validate_timezone(
        event.timezone_name, event.country_region, zones
    )
    if timezone_error:
        raise EnrollmentError(f"event {event.id}: {timezone_error}")


def _normalize_us_zone_map(
    event_ids: list[int],
    allowed_us_zones: dict[int, list[str]] | None,
) -> dict[int, list[str]]:
    known = set(event_ids)
    normalized: dict[int, list[str]] = {}
    for event_id, zones in (allowed_us_zones or {}).items():
        if event_id not in known:
            raise EnrollmentError(f"US allowlist 指向未纳管 event {event_id}")
        if not isinstance(zones, list) or not zones:
            raise EnrollmentError(f"event {event_id}: US allowlist 不能为空")
        if any(not isinstance(zone, str) or not zone.startswith("America/") for zone in zones):
            raise EnrollmentError(f"event {event_id}: US allowlist 只能包含 America/*")
        normalized[event_id] = sorted(set(zones))
    return normalized


def build_enrollment_artifacts(
    *,
    event_ids: list[int],
    approved_commit: str,
    allowed_us_zones: dict[int, list[str]] | None = None,
    now: datetime | None = None,
) -> tuple[bytes, bytes]:
    """Read the database and return canonical manifest and summary bytes."""
    if not _is_git_oid(approved_commit):
        raise EnrollmentError("approved_commit 必须为 40 位小写 Git OID")
    if not 1 <= len(event_ids) <= MAX_EVENTS:
        raise EnrollmentError("必须明确提供 1–20 个 event ID")
    if any(
        not isinstance(event_id, int)
        or isinstance(event_id, bool)
        or event_id <= 0
        for event_id in event_ids
    ):
        raise EnrollmentError("event ID 必须为正整数")
    if len(set(event_ids)) != len(event_ids):
        raise EnrollmentError("event ID 不得重复")
    sorted_ids = sorted(event_ids)
    zone_map = _normalize_us_zone_map(sorted_ids, allowed_us_zones)
    events = list(RaceEvent.objects.filter(id__in=sorted_ids).order_by("id"))
    if [event.id for event in events] != sorted_ids:
        found = {event.id for event in events}
        raise EnrollmentError(f"赛事不存在: {sorted(set(sorted_ids) - found)}")
    existing = {
        control.event_id: control
        for control in RaceEventLifecycleControl.objects.filter(
            event_id__in=sorted_ids
        )
    }
    if existing:
        raise EnrollmentError(
            f"prepare 只接受尚未纳管赛事，已有 control: {sorted(existing)}"
        )

    generated_at = now or django_timezone.now()
    if django_timezone.is_naive(generated_at):
        raise EnrollmentError("generated_at 必须为 aware")
    generated_at = generated_at.astimezone(timezone.utc)
    events_payload: dict[str, Any] = {}
    for event in events:
        zones = zone_map.get(event.id, [])
        if event.country_region == "united_states" and not zones:
            raise EnrollmentError(f"event {event.id}: 美国赛事缺少逐场 allowlist")
        if event.country_region != "united_states" and zones:
            raise EnrollmentError(f"event {event.id}: 非美国赛事不得配置 US allowlist")
        _validate_enrollment_eligibility(event, allowed_us_zones=zones)
        decision = decide_race_lifecycle(
            race_datetime=event.race_datetime,
            timezone_name=event.timezone_name,
            status=event.status,
            now=generated_at,
            local_date=event.local_date,
            region=event.country_region,
            allowed_us_zones=frozenset(zones) if zones else None,
        )
        next_refresh = _initial_next_refresh(event)
        snapshot = _event_snapshot_values(event)
        snapshot.update(
            {
                "allowed_us_zones": zones,
                "expected_control": {"state": "absent"},
                "predicted_decision": {
                    "action": decision.action,
                    "to_status": decision.to_status,
                    "reason_code": decision.reason_code,
                    "effective_at": _iso_datetime(decision.effective_at),
                    "error_message": decision.error_message,
                },
                "predicted_next_refresh_at": _iso_datetime(next_refresh),
            }
        )
        events_payload[str(event.id)] = snapshot

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "expires_at": (generated_at + timedelta(hours=24)).isoformat(),
        "approved_commit": approved_commit,
        "mode": "shadow",
        "events": events_payload,
    }
    content_sha = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    manifest = dict(payload)
    manifest["content_sha256"] = content_sha
    manifest_bytes = _canonical_bytes(manifest)
    raw_sha = hashlib.sha256(manifest_bytes).hexdigest()
    summary = {
        "schema_version": 1,
        "event_count": len(sorted_ids),
        "event_ids": sorted_ids,
        "mode": "shadow",
        "approved_commit": approved_commit,
        "manifest_content_sha256": content_sha,
        "manifest_raw_sha256": raw_sha,
        "generated_at": generated_at.isoformat(),
        "expires_at": (generated_at + timedelta(hours=24)).isoformat(),
    }
    return manifest_bytes, _canonical_bytes(summary)


def write_enrollment_artifacts(
    output_dir: str | Path,
    *,
    manifest_bytes: bytes,
    summary_bytes: bytes,
) -> None:
    """Publish both artifacts through stable directory descriptors.

    Every path traversal is relative to an already-open no-follow directory
    descriptor.  Path names are revalidated before and after publication, so
    replacing an ancestor cannot redirect writes to an attacker directory.
    """
    output = Path(output_dir)
    if ".." in output.parts:
        raise EnrollmentError("output-dir 不得包含 ..")
    absolute = output.absolute()
    _require_secure_dir_fd_support()
    output_name = absolute.name
    if not output_name or output_name in {".", ".."}:
        raise EnrollmentError("output-dir 名称非法")

    parent_fd = _open_directory_chain(absolute.parent)
    parent_identity = _directory_identity(parent_fd)
    staging_name = ""
    staging_fd: int | None = None
    staging_identity: tuple[int, int] | None = None
    publish_rename_succeeded = False
    try:
        _probe_atomic_noreplace_semantics(parent_fd)
        _require_relative_absence(parent_fd, output_name, "output-dir 必须原本不存在")
        for _ in range(16):
            candidate = f".{output_name}.tmp-{secrets.token_hex(16)}"
            try:
                os.mkdir(candidate, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                continue
            staging_name = candidate
            break
        if not staging_name:
            raise EnrollmentError("无法分配安全 staging 目录")

        staging_fd = os.open(
            staging_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        staging_identity = _directory_identity(staging_fd)
        _write_relative_file(staging_fd, "manifest.json", manifest_bytes)
        _write_relative_file(staging_fd, "summary.json", summary_bytes)
        os.fsync(staging_fd)

        _verify_parent_path(absolute.parent, parent_identity)
        _require_relative_absence(parent_fd, output_name, "output-dir 在发布前已出现")
        if _relative_directory_identity(parent_fd, staging_name) != staging_identity:
            raise EnrollmentError("staging 名称在发布前已被替换")
        _atomic_rename_noreplace(parent_fd, staging_name, output_name)
        publish_rename_succeeded = True
        if _relative_directory_identity(parent_fd, output_name) != staging_identity:
            raise EnrollmentError("发布后的 output 名称未指向已审核 staging inode")
        os.fsync(parent_fd)
        _verify_parent_path(absolute.parent, parent_identity)
    except EnrollmentError as exc:
        quarantine_error = _quarantine_after_failed_publish(
            parent_fd,
            output_name,
            publish_rename_succeeded=publish_rename_succeeded,
        )
        _cleanup_owned_artifact(
            parent_fd,
            staging_identity,
            staging_fd=staging_fd,
        )
        if quarantine_error is not None:
            raise EnrollmentError(
                f"{exc}; 且无法隔离失败发布的 output: {quarantine_error}"
            ) from exc
        raise
    except OSError as exc:
        quarantine_error = _quarantine_after_failed_publish(
            parent_fd,
            output_name,
            publish_rename_succeeded=publish_rename_succeeded,
        )
        _cleanup_owned_artifact(
            parent_fd,
            staging_identity,
            staging_fd=staging_fd,
        )
        if quarantine_error is not None:
            raise EnrollmentError(
                f"artifact 原子发布失败: {exc}; "
                f"且无法隔离失败发布的 output: {quarantine_error}"
            ) from exc
        raise EnrollmentError(f"artifact 原子发布失败: {exc}") from exc
    finally:
        if staging_fd is not None:
            os.close(staging_fd)
        os.close(parent_fd)


def _require_secure_dir_fd_support() -> None:
    required = (os.open, os.mkdir, os.rename, os.unlink, os.stat)
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise EnrollmentError("当前平台缺少 O_DIRECTORY/O_NOFOLLOW，拒绝写 artifact")
    if any(function not in os.supports_dir_fd for function in required):
        raise EnrollmentError("当前平台缺少安全 dir_fd 操作，拒绝写 artifact")
    if os.stat not in os.supports_follow_symlinks:
        raise EnrollmentError("当前平台无法 no-follow stat，拒绝写 artifact")
    _load_atomic_noreplace_primitive()


def _load_atomic_noreplace_primitive():
    """Load and type the platform's atomic no-clobber directory rename."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except OSError as exc:
        raise EnrollmentError("无法加载原子 no-replace 发布原语") from exc

    if sys.platform.startswith("linux"):
        try:
            function = libc.renameat2
        except AttributeError as exc:
            raise EnrollmentError("当前 Linux libc 不支持 renameat2") from exc
        function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        function.restype = ctypes.c_int
        return function, 1  # RENAME_NOREPLACE

    if sys.platform == "darwin":
        try:
            function = libc.renameatx_np
        except AttributeError as exc:
            raise EnrollmentError("当前 macOS libc 不支持 renameatx_np") from exc
        function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        function.restype = ctypes.c_int
        return function, 0x00000004  # RENAME_EXCL

    raise EnrollmentError("当前平台没有受支持的原子 no-replace 发布原语")


def _atomic_rename_noreplace(
    parent_fd: int,
    source_name: str,
    destination_name: str,
) -> None:
    function, flags = _load_atomic_noreplace_primitive()
    _invoke_atomic_noreplace(
        function,
        flags,
        parent_fd,
        source_name,
        destination_name,
    )


def _invoke_atomic_noreplace(
    function,
    flags: int,
    parent_fd: int,
    source_name: str,
    destination_name: str,
) -> None:
    source = os.fsencode(source_name)
    destination = os.fsencode(destination_name)
    ctypes.set_errno(0)
    result = function(parent_fd, source, parent_fd, destination, flags)
    if result == 0:
        return
    error_number = ctypes.get_errno() or errno.EIO
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(
            error_number,
            "原子 no-replace 发布目标已存在",
        )
    raise OSError(error_number, "原子 no-replace 发布失败")


def _probe_atomic_noreplace_semantics(parent_fd: int) -> None:
    """Prove no-clobber semantics on this exact filesystem before payload I/O.

    Probe directories are empty, random, mode 0700, and contain no business
    data.  They are deliberately retained as harmless owned residue because
    this workflow has no portable identity-addressed directory unlink; cleanup
    by a potentially rebound pathname would weaken the safety contract.
    """
    function, flags = _load_atomic_noreplace_primitive()
    token = secrets.token_hex(24)
    source_name = f".lifecycle-noreplace-probe-source-{token}"
    destination_name = f".lifecycle-noreplace-probe-target-{token}"
    try:
        os.mkdir(source_name, mode=0o700, dir_fd=parent_fd)
        os.mkdir(destination_name, mode=0o700, dir_fd=parent_fd)
    except OSError as exc:
        raise EnrollmentError(f"无法创建原子 no-replace 语义探针: {exc}") from exc

    source_identity = _relative_directory_identity(parent_fd, source_name)
    destination_identity = _relative_directory_identity(
        parent_fd, destination_name
    )
    conflict_observed = False
    try:
        _invoke_atomic_noreplace(
            function,
            flags,
            parent_fd,
            source_name,
            destination_name,
        )
    except FileExistsError:
        conflict_observed = True
    except OSError as exc:
        raise EnrollmentError(
            f"原子 no-replace 运行时语义不可用: errno={exc.errno}"
        ) from exc

    if not conflict_observed:
        raise EnrollmentError("原子 no-replace 原语错误覆盖了已存在目标")
    if (
        _relative_directory_identity(parent_fd, source_name) != source_identity
        or _relative_directory_identity(parent_fd, destination_name)
        != destination_identity
    ):
        raise EnrollmentError("原子 no-replace 探针未保持源/目标 inode")


def _open_directory_chain(directory: Path) -> int:
    if not directory.is_absolute():
        raise EnrollmentError("内部错误：目录链必须为绝对路径")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        current_fd = os.open(directory.anchor, flags)
    except OSError as exc:
        raise EnrollmentError(f"无法安全打开根目录: {exc}") from exc
    try:
        for component in directory.parts[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except OSError as exc:
                raise EnrollmentError(
                    f"output-dir 祖先无法 no-follow 打开: {component!r}: {exc}"
                ) from exc
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _directory_identity(descriptor: int) -> tuple[int, int]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise EnrollmentError("稳定 parent fd 不是目录")
    return metadata.st_dev, metadata.st_ino


def _relative_directory_identity(parent_fd: int, name: str) -> tuple[int, int]:
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise EnrollmentError(f"无法核对相对目录 {name!r}: {exc}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise EnrollmentError(f"相对名称 {name!r} 不再是普通目录")
    return metadata.st_dev, metadata.st_ino


def _verify_parent_path(directory: Path, expected: tuple[int, int]) -> None:
    verification_fd = _open_directory_chain(directory)
    try:
        if _directory_identity(verification_fd) != expected:
            raise EnrollmentError("output-dir parent 路径映射在发布期间发生变化")
    finally:
        os.close(verification_fd)


def _require_relative_absence(
    parent_fd: int,
    name: str,
    message: str,
) -> None:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise EnrollmentError(f"无法核对 artifact 目标: {exc}") from exc
    raise EnrollmentError(message)


def _write_relative_file(directory_fd: int, name: str, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    try:
        view = memoryview(payload)
        written = 0
        while written < len(view):
            try:
                count = os.write(descriptor, view[written:])
            except InterruptedError:
                continue
            if count <= 0:
                raise EnrollmentError(f"写入 {name} 时未取得进展")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _quarantine_unknown_directory(parent_fd: int, name: str) -> None:
    """Move an untrusted replacement away from the public output name."""
    for _ in range(16):
        quarantine = f".artifact.quarantine-{secrets.token_hex(16)}"
        try:
            os.rename(
                name,
                quarantine,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
            return
        except FileExistsError:
            continue
        except FileNotFoundError:
            return
        except OSError as exc:
            raise EnrollmentError(
                f"无法隔离未知 output 替换目录: {exc}"
            ) from exc
    raise EnrollmentError("无法分配 output 隔离名称")


def _quarantine_after_failed_publish(
    parent_fd: int,
    output_name: str,
    *,
    publish_rename_succeeded: bool,
) -> EnrollmentError | None:
    if not publish_rename_succeeded:
        return None
    try:
        _quarantine_unknown_directory(parent_fd, output_name)
    except EnrollmentError as exc:
        return exc
    return None


def _cleanup_owned_artifact(
    parent_fd: int,
    expected_identity: tuple[int, int] | None,
    *,
    staging_fd: int | None,
) -> None:
    if expected_identity is None or staging_fd is None:
        return
    for filename in ("manifest.json", "summary.json"):
        try:
            os.unlink(filename, dir_fd=staging_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass
    try:
        os.fsync(staging_fd)
    except OSError:
        pass


def _snapshot_matches_event(snapshot: dict[str, Any], event: RaceEvent) -> bool:
    current = _event_snapshot_values(event)
    return all(snapshot[field] == value for field, value in current.items())


def _desired_control_matches(
    control: RaceEventLifecycleControl,
    manifest: LoadedEnrollmentManifest,
    snapshot: dict[str, Any],
) -> bool:
    return bool(
        control.mode == "shadow"
        and control.enrollment_manifest_sha256 == manifest.raw_sha256
        and control.schedule_generation == 1
        and _iso_datetime(control.next_refresh_at)
        == snapshot["predicted_next_refresh_at"]
        and control.manifest_data == _manifest_data_for(manifest, snapshot)
        and not control.claim_token
        and control.claim_generation == 0
        and control.claim_expires_at is None
        and not control.manual_pause_reason
    )


def preflight_enrollment(
    manifest: LoadedEnrollmentManifest,
    *,
    lock: bool = False,
) -> EnrollmentPreflight:
    """Perform complete DB CAS validation; caller owns any transaction."""
    event_query = RaceEvent.objects.filter(id__in=manifest.event_ids).order_by("id")
    if lock:
        event_query = event_query.select_for_update()
    events = tuple(event_query)
    if tuple(event.id for event in events) != manifest.event_ids:
        found = {event.id for event in events}
        raise EnrollmentError(
            f"赛事不存在: {sorted(set(manifest.event_ids) - found)}"
        )

    control_query = RaceEventLifecycleControl.objects.filter(
        event_id__in=manifest.event_ids
    ).order_by("event_id")
    if lock:
        control_query = control_query.select_for_update()
    controls = {control.event_id: control for control in control_query}
    outcomes: dict[int, str] = {}
    observed_at = django_timezone.now()
    if django_timezone.is_naive(observed_at):
        raise EnrollmentError("preflight now 必须为 aware datetime")
    expires_at = _parse_aware_datetime(
        manifest.data["expires_at"], label="expires_at", require_utc=True
    )
    if observed_at >= expires_at:
        raise EnrollmentError("manifest 已过期")
    for event in events:
        snapshot = manifest.data["events"][str(event.id)]
        zones = snapshot["allowed_us_zones"]
        _validate_enrollment_eligibility(event, allowed_us_zones=zones)
        if not _snapshot_matches_event(snapshot, event):
            raise EnrollmentError(f"event {event.id}: 数据库快照已漂移")
        expected_next = _initial_next_refresh(event)
        if _iso_datetime(expected_next) != snapshot["predicted_next_refresh_at"]:
            raise EnrollmentError(f"event {event.id}: next_refresh 预测已漂移")
        decision = decide_race_lifecycle(
            race_datetime=event.race_datetime,
            timezone_name=event.timezone_name,
            status=event.status,
            now=observed_at,
            local_date=event.local_date,
            region=event.country_region,
            allowed_us_zones=frozenset(zones) if zones else None,
        )
        predicted = snapshot["predicted_decision"]
        current_prediction = {
            "action": decision.action,
            "to_status": decision.to_status,
            "reason_code": decision.reason_code,
            "error_message": decision.error_message,
        }
        frozen_prediction = {
            field: predicted[field]
            for field in ("action", "to_status", "reason_code", "error_message")
        }
        if current_prediction != frozen_prediction:
            raise EnrollmentError(f"event {event.id}: predicted decision 不一致")

        control = controls.get(event.id)
        if control is None:
            if snapshot["expected_control"] != {"state": "absent"}:
                raise EnrollmentError(f"event {event.id}: expected control 已漂移")
            outcomes[event.id] = "would_create"
        elif _desired_control_matches(control, manifest, snapshot):
            outcomes[event.id] = "replay"
        else:
            raise EnrollmentError(f"event {event.id}: 已存在不同或漂移的 control")
    return EnrollmentPreflight(
        manifest=manifest,
        events=events,
        existing_controls=controls,
        outcomes=outcomes,
    )


def apply_enrollment(
    manifest: LoadedEnrollmentManifest,
) -> EnrollmentPreflight:
    """Apply an entire v2 manifest or write nothing."""
    # The service is a public safety boundary: callers cannot bypass the
    # management command's closed-state gate.  This check precedes atomic()
    # and therefore every row lock and write.
    if not (
        getattr(settings, "RACE_EVENT_LIFECYCLE_ENABLED", None) is False
        and getattr(settings, "RACE_EVENT_LIFECYCLE_MODE", None) == "off"
    ):
        raise EnrollmentError(
            "v2 apply 只允许在严格 RACE_EVENT_LIFECYCLE_ENABLED=false、"
            "RACE_EVENT_LIFECYCLE_MODE=off 下执行"
        )
    with transaction.atomic():
        result = preflight_enrollment(manifest, lock=True)
        to_create: list[RaceEventLifecycleControl] = []
        for event in result.events:
            if result.outcomes[event.id] != "would_create":
                continue
            snapshot = manifest.data["events"][str(event.id)]
            to_create.append(
                RaceEventLifecycleControl(
                    event=event,
                    mode="shadow",
                    next_refresh_at=_initial_next_refresh(event),
                    schedule_generation=1,
                    enrollment_manifest_sha256=manifest.raw_sha256,
                    manifest_data=_manifest_data_for(manifest, snapshot),
                )
            )
        if to_create:
            RaceEventLifecycleControl.objects.bulk_create(to_create)
        return result

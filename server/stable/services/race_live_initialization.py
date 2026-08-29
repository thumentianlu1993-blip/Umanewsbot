from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from stable import models
from stable.services.race_live_target_eligibility import (
    MATRIX_VERSION,
    evaluate_race_live_target_eligibility,
)


class RaceLiveInitializationError(ValueError):
    """Raised when an initialization manifest or database baseline is unsafe."""


_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_SOURCE_KEY = "the_racing_api"
_HOST = "api.theracingapi.com"
_TERMS_URL = "https://www.theracingapi.com/terms-of-service"

_TOP_LEVEL_KEYS_V1 = frozenset(
    {
        "schema_version",
        "approved_commit",
        "generated_at",
        "registry_digest",
        "coverage_proof_digest",
        "terms_evidence_sha256",
        "source_key",
        "host",
        "policy_valid_until",
        "official_verification_route",
        "official_verification_route_version",
        "official_verification_valid_until",
        "events",
    }
)
_TOP_LEVEL_KEYS_V2 = _TOP_LEVEL_KEYS_V1 | frozenset(
    {
        "registry_valid_until",
        "requests_sha256",
        "report_sha256",
        "official_verification_evidence_sha256",
    }
)
_EVENT_KEYS_V1 = frozenset(
    {
        "event_id",
        "expected_event_updated_at",
        "year",
        "slug",
        "original_name",
        "country_region",
        "racecourse",
        "grade_text",
        "race_datetime",
        "external_race_id",
        "tracking_state",
        "next_poll_at",
        "participants",
    }
)
_EVENT_KEYS_V2 = _EVENT_KEYS_V1 | frozenset(
    {
        "expected_race_datetime_before",
        "expected_local_start_time_before",
        "expected_status",
        "expected_local_date",
        "expected_timezone_name",
        "local_date",
        "source_off_dt",
        "source_response_sha256",
    }
)
_EVENT_KEYS_V2_MULTIREGION = _EVENT_KEYS_V2 | frozenset(
    {
        "normalized_grade",
        "eligibility_matrix_version",
        "eligibility_exception_digest",
        "eligibility_exception",
    }
)
_REGION_TIMEZONES = {
    models.RacingRegion.UNITED_KINGDOM: "Europe/London",
    models.RacingRegion.FRANCE: "Europe/Paris",
    models.RacingRegion.HONG_KONG: "Asia/Hong_Kong",
    models.RacingRegion.JAPAN: "Asia/Tokyo",
    models.RacingRegion.UNITED_STATES: None,
}
_PARTICIPANT_KEYS_V1 = frozenset(
    {
        "stable_key",
        "canonical_name",
        "country_region",
        "external_runner_id",
        "horse_number",
        "status",
    }
)
_PARTICIPANT_KEYS_V2 = _PARTICIPANT_KEYS_V1 | frozenset(
    {"barrier", "jockey_name", "jockey_id"}
)
_TRACKING_STATES = frozenset(
    {
        models.RaceEventLiveState.RACECARD_READY,
        models.RaceEventLiveState.AWAITING_RESULT,
    }
)
_PARTICIPANT_STATUSES = frozenset(
    {
        models.RaceEventRevisionItemStatus.DECLARED,
        models.RaceEventRevisionItemStatus.SCRATCHED,
        models.RaceEventRevisionItemStatus.WITHDRAWN,
        models.RaceEventRevisionItemStatus.NON_RUNNER,
    }
)


@dataclass(frozen=True)
class LoadedRaceLiveInitializationManifest:
    path: Path
    sha256: str
    payload: dict[str, Any]
    generated_at: datetime
    policy_valid_until: datetime
    official_verification_valid_until: datetime


def _fail(message: str) -> None:
    raise RaceLiveInitializationError(message)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _fail(f"JSON 含重复 key：{key}")
        value[key] = item
    return value


def _exact_keys(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} 必须是 object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        _fail(f"{label} schema 不匹配：missing={missing} unknown={unknown}")
    return value


def _nonempty_string(
    value: Any,
    label: str,
    *,
    max_length: int | None = None,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        _fail(f"{label} 必须是无首尾空白的非空字符串")
    if max_length is not None and len(value) > max_length:
        _fail(f"{label} 超过最大长度 {max_length}")
    return value


def _positive_int(value: Any, label: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(f"{label} 必须是正整数")
    if maximum is not None and value > maximum:
        _fail(f"{label} 超过最大值 {maximum}")
    return value


def _lower_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} 必须是 64 位 lowercase SHA-256")
    return value


def _lower_commit(value: Any, label: str) -> str:
    if not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None:
        _fail(f"{label} 必须是 40 位 lowercase commit OID")
    return value


def _aware_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(f"{label} 必须是非空 ISO-8601 时间")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RaceLiveInitializationError(f"{label} 不是合法 ISO-8601 时间") from exc
    if timezone.is_naive(parsed):
        _fail(f"{label} 必须包含时区")
    return parsed


def _optional_aware_datetime(value: Any, label: str) -> datetime | None:
    if value is None:
        return None
    return _aware_datetime(value, label)


def _iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str) or value != value.strip():
        _fail(f"{label} 必须是 ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RaceLiveInitializationError(f"{label} 不是合法 ISO date") from exc


def _optional_local_time(value: Any, label: str) -> datetime_time | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "T" in value
        or "+" in value
        or value.endswith("Z")
    ):
        _fail(f"{label} 必须是严格本地 time 或 null")
    try:
        parsed = datetime_time.fromisoformat(value)
    except ValueError as exc:
        raise RaceLiveInitializationError(
            f"{label} 不是合法本地 time"
        ) from exc
    if parsed.tzinfo is not None:
        _fail(f"{label} 不能包含时区")
    return parsed


def _read_regular_file(path: Path, *, label: str = "manifest") -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise RaceLiveInitializationError(f"无法读取 {label}：{exc}") from exc
    if not stat.S_ISREG(before.st_mode):
        _fail(f"{label} 必须是 regular file，不能是 symlink 或目录")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RaceLiveInitializationError(f"无法安全打开 {label}：{exc}") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            _fail(f"{label} 必须是 regular file")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            _fail(f"{label} 在打开期间发生替换")
        if opened.st_size > _MAX_MANIFEST_BYTES:
            _fail(f"{label} 超过 {_MAX_MANIFEST_BYTES} bytes")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(65536, _MAX_MANIFEST_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_MANIFEST_BYTES:
                _fail(f"{label} 超过 {_MAX_MANIFEST_BYTES} bytes")
        after = os.fstat(fd)
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            _fail(f"{label} 在读取期间发生变化")
        return b"".join(chunks)
    finally:
        os.close(fd)


def load_race_live_initialization_manifest(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    expected_approved_commit: str,
    now: datetime | None = None,
) -> LoadedRaceLiveInitializationManifest:
    expected_sha = _lower_sha256(
        expected_manifest_sha256, "--expected-manifest-sha256"
    )
    expected_commit = _lower_commit(
        expected_approved_commit, "--expected-approved-commit"
    )
    path = Path(manifest_path)
    raw = _read_regular_file(path)
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha:
        _fail(
            "manifest SHA-256 不匹配："
            f"expected={expected_sha} actual={actual_sha}"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RaceLiveInitializationError("manifest 必须使用 UTF-8") from exc
    try:
        payload = json.loads(text, object_pairs_hook=_strict_object)
    except json.JSONDecodeError as exc:
        raise RaceLiveInitializationError(f"manifest JSON 无效：{exc}") from exc
    if not isinstance(payload, dict):
        _fail("manifest 必须是 object")
    schema_version = payload.get("schema_version")
    if isinstance(schema_version, bool) or schema_version not in {1, 2}:
        _fail("schema_version 必须精确为 1 或 2")
    payload = _exact_keys(
        payload,
        _TOP_LEVEL_KEYS_V2 if schema_version == 2 else _TOP_LEVEL_KEYS_V1,
        "manifest",
    )
    approved_commit = _lower_commit(payload["approved_commit"], "approved_commit")
    if approved_commit != expected_commit:
        _fail(
            "approved_commit 不匹配："
            f"expected={expected_commit} actual={approved_commit}"
        )
    generated_at = _aware_datetime(payload["generated_at"], "generated_at")
    registry_digest = _lower_sha256(payload["registry_digest"], "registry_digest")
    coverage_digest = _lower_sha256(
        payload["coverage_proof_digest"], "coverage_proof_digest"
    )
    terms_digest = _lower_sha256(
        payload["terms_evidence_sha256"], "terms_evidence_sha256"
    )
    del registry_digest, coverage_digest, terms_digest
    if payload["source_key"] != _SOURCE_KEY:
        _fail(f"source_key 必须精确为 {_SOURCE_KEY}")
    if payload["host"] != _HOST:
        _fail(f"host 必须精确为 {_HOST}")
    policy_valid_until = _aware_datetime(
        payload["policy_valid_until"], "policy_valid_until"
    )
    registry_valid_until = None
    if schema_version == 2:
        registry_valid_until = _aware_datetime(
            payload["registry_valid_until"],
            "registry_valid_until",
        )
        if policy_valid_until > registry_valid_until:
            _fail("policy_valid_until 不得晚于 registry_valid_until")
        _lower_sha256(payload["requests_sha256"], "requests_sha256")
        _lower_sha256(payload["report_sha256"], "report_sha256")
        _lower_sha256(
            payload["official_verification_evidence_sha256"],
            "official_verification_evidence_sha256",
        )
    official_valid_until = _aware_datetime(
        payload["official_verification_valid_until"],
        "official_verification_valid_until",
    )
    _nonempty_string(
        payload["official_verification_route"],
        "official_verification_route",
        max_length=255,
    )
    _nonempty_string(
        payload["official_verification_route_version"],
        "official_verification_route_version",
        max_length=64,
    )
    effective_now = now or timezone.now()
    if not isinstance(effective_now, datetime) or timezone.is_naive(effective_now):
        _fail("now 必须是 aware datetime")
    if generated_at > effective_now + timedelta(minutes=5):
        _fail("generated_at 晚于运行时 now + 5 分钟")
    if policy_valid_until <= effective_now:
        _fail("policy_valid_until 已过期")
    if official_valid_until <= effective_now:
        _fail("official_verification_valid_until 已过期")
    if policy_valid_until <= generated_at:
        _fail("policy_valid_until 必须晚于 generated_at")
    if official_valid_until <= generated_at:
        _fail("official_verification_valid_until 必须晚于 generated_at")
    if registry_valid_until is not None and registry_valid_until <= effective_now:
        _fail("registry_valid_until 已过期")

    if schema_version == 2:
        parent = path.parent
        try:
            parent_stat = parent.lstat()
        except OSError as exc:
            raise RaceLiveInitializationError(f"无法读取 artifact 目录：{exc}") from exc
        if not stat.S_ISDIR(parent_stat.st_mode):
            _fail("artifact parent 必须是目录且不能是 symlink")
        for filename, digest_key in (
            ("requests.jsonl", "requests_sha256"),
            ("report.json", "report_sha256"),
        ):
            companion = parent / filename
            companion_raw = _read_regular_file(companion, label=filename)
            if hashlib.sha256(companion_raw).hexdigest() != payload[digest_key]:
                _fail(f"{filename} SHA-256 不匹配")

    events = payload["events"]
    if not isinstance(events, list) or not events or len(events) > 500:
        _fail("events 必须是 1-500 个元素的数组")
    seen_event_ids: set[int] = set()
    seen_event_keys: set[tuple[int, str]] = set()
    seen_external_race_ids: set[str] = set()
    allowed_regions = set(models.RacingRegion.values)
    for event_index, raw_event in enumerate(events):
        label = f"events[{event_index}]"
        selected_event_keys = (
            _EVENT_KEYS_V2_MULTIREGION
            if (
                schema_version == 2
                and isinstance(raw_event, dict)
                and set(raw_event) == _EVENT_KEYS_V2_MULTIREGION
            )
            else (
                _EVENT_KEYS_V2
                if schema_version == 2
                else _EVENT_KEYS_V1
            )
        )
        event = _exact_keys(
            raw_event,
            selected_event_keys,
            label,
        )
        event_id = _positive_int(event["event_id"], f"{label}.event_id")
        _aware_datetime(
            event["expected_event_updated_at"],
            f"{label}.expected_event_updated_at",
        )
        year = _positive_int(event["year"], f"{label}.year", maximum=9999)
        slug = _nonempty_string(event["slug"], f"{label}.slug", max_length=160)
        _nonempty_string(
            event["original_name"], f"{label}.original_name", max_length=255
        )
        region = _nonempty_string(
            event["country_region"], f"{label}.country_region", max_length=32
        )
        if region not in allowed_regions:
            _fail(f"{label}.country_region 不在允许范围")
        _nonempty_string(
            event["racecourse"], f"{label}.racecourse", max_length=255
        )
        _nonempty_string(
            event["grade_text"], f"{label}.grade_text", max_length=128
        )
        race_datetime = _aware_datetime(
            event["race_datetime"], f"{label}.race_datetime"
        )
        external_race_id = _nonempty_string(
            event["external_race_id"],
            f"{label}.external_race_id",
            max_length=128,
        )
        if event["tracking_state"] not in _TRACKING_STATES:
            _fail(f"{label}.tracking_state 不允许")
        _aware_datetime(event["next_poll_at"], f"{label}.next_poll_at")
        if schema_version == 2:
            _optional_aware_datetime(
                event["expected_race_datetime_before"],
                f"{label}.expected_race_datetime_before",
            )
            _optional_local_time(
                event["expected_local_start_time_before"],
                f"{label}.expected_local_start_time_before",
            )
            if event["expected_status"] != models.RaceEventStatus.SCHEDULED:
                _fail(f"{label}.expected_status 必须是 scheduled")
            expected_local_date = _iso_date(
                event["expected_local_date"],
                f"{label}.expected_local_date",
            )
            local_date = _iso_date(event["local_date"], f"{label}.local_date")
            if expected_local_date != local_date:
                _fail(f"{label}.local_date 与 expected_local_date 不一致")
            expected_timezone = _REGION_TIMEZONES.get(region)
            timezone_name = event["expected_timezone_name"]
            if (
                expected_timezone is not None
                and timezone_name != expected_timezone
            ) or (
                expected_timezone is None
                and (
                    region != models.RacingRegion.UNITED_STATES
                    or not isinstance(timezone_name, str)
                    or not timezone_name.startswith("America/")
                )
            ):
                _fail(f"{label}.expected_timezone_name 与地区不匹配")
            source_off_dt = _aware_datetime(
                event["source_off_dt"], f"{label}.source_off_dt"
            )
            if source_off_dt != race_datetime:
                _fail(f"{label}.source_off_dt 与 race_datetime instant 不一致")
            local_time = source_off_dt.astimezone(ZoneInfo(timezone_name))
            if local_time.date() != local_date:
                _fail(f"{label}.source_off_dt 的赛事当地日期不匹配")
            if selected_event_keys == _EVENT_KEYS_V2_MULTIREGION:
                normalized_grade = _nonempty_string(
                    event["normalized_grade"],
                    f"{label}.normalized_grade",
                    max_length=16,
                )
                if normalized_grade not in models.RaceGrade.values:
                    _fail(f"{label}.normalized_grade 不在允许范围")
                if event["eligibility_matrix_version"] != MATRIX_VERSION:
                    _fail(f"{label}.eligibility_matrix_version 漂移")
                eligibility = evaluate_race_live_target_eligibility(
                    event_id=event_id,
                    year=year,
                    region=region,
                    normalized_grade=normalized_grade,
                    exception_artifact=event["eligibility_exception"],
                    expected_approved_commit=payload["approved_commit"],
                    now=generated_at,
                )
                if (
                    eligibility.eligible is not True
                    or eligibility.exception_digest
                    != event["eligibility_exception_digest"]
                    or (
                        eligibility.reason == "exception_approved"
                        and not isinstance(
                            event["eligibility_exception"],
                            dict,
                        )
                    )
                    or (
                        eligibility.reason != "exception_approved"
                        and event["eligibility_exception"] is not None
                    )
                ):
                    _fail(f"{label}.eligibility 不通过")
            elif region != models.RacingRegion.UNITED_KINGDOM:
                _fail(f"{label} 非英国 event 必须绑定 eligibility")
            _lower_sha256(
                event["source_response_sha256"],
                f"{label}.source_response_sha256",
            )
            expected_state = (
                models.RaceEventLiveState.RACECARD_READY
                if generated_at < source_off_dt
                else models.RaceEventLiveState.AWAITING_RESULT
            )
            if event["tracking_state"] != expected_state:
                _fail(f"{label}.tracking_state 与 generated_at/off time 不一致")
            from stable.services.race_events import (
                calculate_race_live_next_poll_at,
            )

            expected_next_poll = (
                calculate_race_live_next_poll_at(
                    off_time=source_off_dt,
                    now=generated_at,
                    state=expected_state,
                )
                if generated_at < source_off_dt
                else generated_at
            )
            if _aware_datetime(
                event["next_poll_at"], f"{label}.next_poll_at"
            ) != expected_next_poll:
                _fail(f"{label}.next_poll_at 与调度算法不一致")
        if event_id in seen_event_ids:
            _fail(f"{label}.event_id 重复")
        if (year, slug) in seen_event_keys:
            _fail(f"{label} 的 year/slug 重复")
        if external_race_id in seen_external_race_ids:
            _fail(f"{label}.external_race_id 重复")
        seen_event_ids.add(event_id)
        seen_event_keys.add((year, slug))
        seen_external_race_ids.add(external_race_id)

        participants = event["participants"]
        if (
            not isinstance(participants, list)
            or not participants
            or len(participants) > 100
        ):
            _fail(f"{label}.participants 必须是 1-100 个元素的数组")
        stable_keys: set[str] = set()
        external_runner_ids: set[str] = set()
        for participant_index, raw_participant in enumerate(participants):
            part_label = f"{label}.participants[{participant_index}]"
            participant = _exact_keys(
                raw_participant,
                (
                    _PARTICIPANT_KEYS_V2
                    if schema_version == 2
                    else _PARTICIPANT_KEYS_V1
                ),
                part_label,
            )
            stable_key = _nonempty_string(
                participant["stable_key"],
                f"{part_label}.stable_key",
                max_length=128,
            )
            _nonempty_string(
                participant["canonical_name"],
                f"{part_label}.canonical_name",
                max_length=255,
            )
            if schema_version == 2:
                if participant["country_region"] != "":
                    _fail(f"{part_label}.country_region 必须留空")
            else:
                part_region = _nonempty_string(
                    participant["country_region"],
                    f"{part_label}.country_region",
                    max_length=32,
                )
                if part_region not in allowed_regions:
                    _fail(f"{part_label}.country_region 不在允许范围")
            external_runner_id = _nonempty_string(
                participant["external_runner_id"],
                f"{part_label}.external_runner_id",
                max_length=128,
            )
            horse_number = _nonempty_string(
                participant["horse_number"],
                f"{part_label}.horse_number",
                max_length=32,
            )
            if participant["status"] not in _PARTICIPANT_STATUSES:
                _fail(f"{part_label}.status 不允许")
            if schema_version == 2:
                expected_stable_key = "tra:" + hashlib.sha256(
                    external_runner_id.encode("utf-8")
                ).hexdigest()
                if stable_key != expected_stable_key:
                    _fail(f"{part_label}.stable_key 与 TRA runner ID 不一致")
                if (
                    participant["status"]
                    != models.RaceEventRevisionItemStatus.DECLARED
                ):
                    _fail(f"{part_label}.status 必须是 declared")
                for field, maximum in (
                    ("barrier", 32),
                    ("jockey_name", 255),
                    ("jockey_id", 128),
                ):
                    value = participant[field]
                    if (
                        not isinstance(value, str)
                        or value != value.strip()
                        or "\x00" in value
                        or len(value) > maximum
                    ):
                        _fail(f"{part_label}.{field} 类型或长度无效")
            if stable_key in stable_keys:
                _fail(f"{part_label}.stable_key 重复")
            if external_runner_id in external_runner_ids:
                _fail(f"{part_label}.external_runner_id 重复")
            stable_keys.add(stable_key)
            external_runner_ids.add(external_runner_id)

    return LoadedRaceLiveInitializationManifest(
        path=path,
        sha256=actual_sha,
        payload=payload,
        generated_at=generated_at,
        policy_valid_until=policy_valid_until,
        official_verification_valid_until=official_valid_until,
    )


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _racecard_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "event_id": event["event_id"],
        "external_race_id": event["external_race_id"],
        "participants": [
            {
                "stable_key": participant["stable_key"],
                "canonical_name": participant["canonical_name"],
                "country_region": participant["country_region"],
                "external_runner_id": participant["external_runner_id"],
                "horse_number": participant["horse_number"],
                "status": participant["status"],
            }
            for participant in event["participants"]
        ],
    }
    if "source_off_dt" in event:
        payload["source_off_dt"] = event["source_off_dt"]
        for row, participant in zip(
            payload["participants"],
            event["participants"],
            strict=True,
        ):
            row.update(
                {
                    "barrier": participant["barrier"],
                    "jockey_name": participant["jockey_name"],
                    "jockey_id": participant["jockey_id"],
                }
            )
    return payload


def _policy_specs(
    manifest: LoadedRaceLiveInitializationManifest,
) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = [
        (models.RaceLivePublicationScopeType.GLOBAL, "global"),
        (models.RaceLivePublicationScopeType.SOURCE, _SOURCE_KEY),
    ]
    seen = set(result)
    for event in manifest.payload["events"]:
        for spec in (
            (
                models.RaceLivePublicationScopeType.REGION,
                event["country_region"],
            ),
            (models.RaceLivePublicationScopeType.EVENT, str(event["event_id"])),
        ):
            if spec not in seen:
                result.append(spec)
                seen.add(spec)
    return result


def _shared_policy_specs(
    manifest: LoadedRaceLiveInitializationManifest,
) -> list[tuple[str, str]]:
    return [
        spec
        for spec in _policy_specs(manifest)
        if spec[0] != models.RaceLivePublicationScopeType.EVENT
    ]


def _event_policy_specs(
    manifest: LoadedRaceLiveInitializationManifest,
) -> list[tuple[str, str]]:
    return [
        spec
        for spec in _policy_specs(manifest)
        if spec[0] == models.RaceLivePublicationScopeType.EVENT
    ]


def _event_identity_matches(row: models.RaceEvent, event: dict[str, Any]) -> bool:
    return (
        row.pk == event["event_id"]
        and row.year == event["year"]
        and row.slug == event["slug"]
        and row.original_name == event["original_name"]
        and row.country_region == event["country_region"]
        and row.racecourse == event["racecourse"]
        and row.grade_text == event["grade_text"]
        and (
            "normalized_grade" not in event
            or row.normalized_grade == event["normalized_grade"]
        )
    )


def _event_matches_manifest(
    row: models.RaceEvent,
    event: dict[str, Any],
    *,
    schema_version: int,
    replay: bool,
) -> bool:
    if not _event_identity_matches(row, event):
        return False
    if schema_version == 1:
        return (
            row.race_datetime == _aware_datetime(
            event["race_datetime"], "race_datetime"
            )
            and row.updated_at
            == _aware_datetime(
                event["expected_event_updated_at"], "expected_event_updated_at"
            )
        )
    source_off_dt = _aware_datetime(event["source_off_dt"], "source_off_dt")
    expected_local_time = source_off_dt.astimezone(
        ZoneInfo(event["expected_timezone_name"])
    ).time().replace(tzinfo=None)
    common = (
        row.status == event["expected_status"]
        and row.local_date == _iso_date(event["expected_local_date"], "local_date")
        and row.timezone_name == event["expected_timezone_name"]
    )
    if replay:
        return (
            common
            and row.race_datetime == source_off_dt
            and row.local_start_time == expected_local_time
        )
    return (
        common
        and row.updated_at
        == _aware_datetime(
            event["expected_event_updated_at"], "expected_event_updated_at"
        )
        and row.race_datetime
        == _optional_aware_datetime(
            event["expected_race_datetime_before"],
            "expected_race_datetime_before",
        )
        and row.local_start_time
        == _optional_local_time(
            event["expected_local_start_time_before"],
            "expected_local_start_time_before",
        )
    )


def _load_and_validate_events(
    manifest: LoadedRaceLiveInitializationManifest,
    *,
    lock: bool,
) -> dict[int, models.RaceEvent]:
    event_ids = [event["event_id"] for event in manifest.payload["events"]]
    query = models.RaceEvent.objects
    if lock:
        query = query.select_for_update()
    rows = {row.pk: row for row in query.filter(pk__in=event_ids)}
    if set(rows) != set(event_ids):
        _fail(
            "manifest 赛事不存在："
            f"{sorted(set(event_ids) - set(rows))}"
        )
    for event in manifest.payload["events"]:
        row = rows[event["event_id"]]
        manual_locks = row.manual_lock_flags
        if not isinstance(manual_locks, dict):
            _fail(f"RaceEvent manual_lock_flags 无效：event_id={row.pk}")
        if manual_locks.get(models.RaceEventModule.RUNNERS) or manual_locks.get(
            models.RaceEventModule.RESULTS
        ):
            _fail(f"RaceEvent runners/results 已被人工锁定：event_id={row.pk}")
        if manifest.payload["schema_version"] == 1 and not _event_matches_manifest(
            row,
            event,
            schema_version=1,
            replay=False,
        ):
            _fail(f"RaceEvent baseline 漂移：event_id={row.pk}")
    return rows


def _shared_policy_matches(
    row: models.RaceLivePublicationPolicy,
    manifest: LoadedRaceLiveInitializationManifest,
) -> bool:
    return (
        row.scope_type != models.RaceLivePublicationScopeType.EVENT
        and row.mode
        in {
            models.RaceLivePublicationMode.SHADOW,
            models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            models.RaceLivePublicationMode.OFFICIAL_PUBLIC,
        }
        and row.version >= 1
        and row.registry_digest == manifest.payload["registry_digest"]
        and row.coverage_proof_digest
        == manifest.payload["coverage_proof_digest"]
        and row.valid_until == manifest.policy_valid_until
    )


def _event_policy_matches(
    row: models.RaceLivePublicationPolicy,
    manifest: LoadedRaceLiveInitializationManifest,
) -> bool:
    return (
        row.scope_type == models.RaceLivePublicationScopeType.EVENT
        and row.mode == models.RaceLivePublicationMode.SHADOW
        and row.version == 1
        and row.registry_digest == manifest.payload["registry_digest"]
        and row.coverage_proof_digest
        == manifest.payload["coverage_proof_digest"]
        and row.valid_until == manifest.policy_valid_until
    )


def _validate_shared_rows(
    manifest: LoadedRaceLiveInitializationManifest,
) -> None:
    for scope_type, scope_key in _shared_policy_specs(manifest):
        policy = models.RaceLivePublicationPolicy.objects.filter(
            scope_type=scope_type,
            scope_key=scope_key,
        ).first()
        if policy is not None and not _shared_policy_matches(policy, manifest):
            _fail(f"publication policy 冲突：{scope_type}:{scope_key}")
    for scope_type, scope_key in _event_policy_specs(manifest):
        policy = models.RaceLivePublicationPolicy.objects.filter(
            scope_type=scope_type,
            scope_key=scope_key,
        ).first()
        if policy is not None and not _event_policy_matches(policy, manifest):
            _fail(f"publication policy 冲突：{scope_type}:{scope_key}")
    budget = models.RaceLiveHostBudget.objects.filter(host=_HOST).first()
    budget_matches = budget is None or (
        budget.min_interval_ms >= 1050
        and (
            manifest.payload["schema_version"] == 2
            or (
                budget.next_allowed_at is None
                and budget.consecutive_failures == 0
                and budget.circuit_open_until is None
                and budget.last_error_code == ""
                and budget.lock_version == 0
            )
        )
    )
    if not budget_matches:
        _fail("The Racing API host budget 已存在且低于安全下限")


def _event_has_any_initialization_rows(event_id: int) -> bool:
    return any(
        (
            models.RaceEventProjectionControl.objects.filter(
                event_id=event_id
            ).exists(),
            models.RaceEventLiveTracking.objects.filter(event_id=event_id).exists(),
            models.RaceResultSourceIdentity.objects.filter(event_id=event_id).exists(),
            models.RaceLiveEventPublicationAllowlist.objects.filter(
                event_id=event_id
            ).exists(),
            models.RaceEventParticipant.objects.filter(event_id=event_id).exists(),
            models.RaceEventRevision.objects.filter(event_id=event_id).exists(),
            models.OperationLog.objects.filter(
                action_type="race_live_event_initialized",
                target_type="race_event",
                target_id=str(event_id),
            ).exists(),
        )
    )


def _event_has_legacy_runners(event_id: int) -> bool:
    return models.RaceEventRunner.objects.filter(event_id=event_id).exists()


def _event_has_forbidden_result_state(event_id: int) -> bool:
    return any(
        (
            models.RaceEventResult.objects.filter(event_id=event_id).exists(),
            models.RaceResultObservation.objects.filter(
                source_identity__event_id=event_id
            ).exists(),
            models.RaceEventRevision.objects.filter(
                event_id=event_id,
                kind=models.RaceEventRevisionKind.RESULT,
            ).exists(),
            models.RaceEventRevisionPublication.objects.filter(
                revision__event_id=event_id
            ).exists(),
            models.RaceLiveOfficialVerificationIncident.objects.filter(
                event_id=event_id
            ).exists(),
        )
    )


def _expected_operation_detail(
    manifest: LoadedRaceLiveInitializationManifest,
    event: dict[str, Any],
) -> str:
    return json.dumps(
        {
            "approved_commit": manifest.payload["approved_commit"],
            "external_race_id": event["external_race_id"],
            "manifest_sha256": manifest.sha256,
            "source_key": _SOURCE_KEY,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _verify_event_exact(
    manifest: LoadedRaceLiveInitializationManifest,
    event: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    event_id = event["event_id"]
    event_row = models.RaceEvent.objects.filter(pk=event_id).first()
    if event_row is None or not _event_matches_manifest(
        event_row,
        event,
        schema_version=manifest.payload["schema_version"],
        replay=manifest.payload["schema_version"] == 2,
    ):
        errors.append("event_final_state_mismatch")
    control = models.RaceEventProjectionControl.objects.filter(
        event_id=event_id
    ).first()
    tracking = models.RaceEventLiveTracking.objects.filter(event_id=event_id).first()
    source = models.RaceResultSourceIdentity.objects.filter(
        event_id=event_id,
        source_key=_SOURCE_KEY,
    ).first()
    allowlist = models.RaceLiveEventPublicationAllowlist.objects.filter(
        event_id=event_id,
        source_key=_SOURCE_KEY,
    ).first()
    revision = models.RaceEventRevision.objects.filter(
        event_id=event_id,
        kind=models.RaceEventRevisionKind.RACECARD,
    ).first()

    if control is None:
        errors.append("projection_control_missing")
    elif not (
        control.write_owner == models.RaceEventProjectionWriteOwner.LIVE
        and control.owner_generation == 1
        and control.owner_manifest_sha256 == manifest.sha256
        and control.owner_changed_at == manifest.generated_at
        and control.owner_changed_by_id is None
        and control.next_racecard_revision_no == 2
        and control.next_result_revision_no == 1
        and control.current_result_revision_id is None
        and control.last_known_good_result_revision_id is None
    ):
        errors.append("projection_control_mismatch")

    if tracking is None:
        errors.append("tracking_missing")
    elif not (
        tracking.state == event["tracking_state"]
        and tracking.tracking_enabled is True
        and tracking.next_poll_at
        == _aware_datetime(event["next_poll_at"], "next_poll_at")
        and tracking.window_started_at is None
        and tracking.window_ends_at is None
        and tracking.last_attempt_at is None
        and tracking.last_success_at is None
        and tracking.last_observation_hash == ""
        and tracking.provisional_published_at is None
        and tracking.official_published_at is None
        and tracking.corrected_at is None
        and tracking.consecutive_failures == 0
        and tracking.circuit_reason == ""
        and tracking.stale_at is None
        and tracking.lock_version == 0
        and tracking.claim_generation == 0
        and tracking.active_attempt_token == ""
        and tracking.claim_expires_at is None
        and tracking.checkpoint_payload == {}
        and tracking.source_route_version == "the_racing_api-free-v1"
        and tracking.selection_reason
        == f"approved initialization manifest {manifest.sha256}"
    ):
        errors.append("tracking_mismatch")

    expected_identity_fields = {
        "event_id": event_id,
        "event_slug": event["slug"],
        "event_year": event["year"],
        "manifest_sha256": manifest.sha256,
    }
    if source is None:
        errors.append("source_identity_missing")
    elif not (
        source.external_race_id == event["external_race_id"]
        and source.canonical_url
        == f"https://{_HOST}/v1/racecards/{event['external_race_id']}"
        and source.host == _HOST
        and source.identity_fields == expected_identity_fields
        and source.review_status == models.RaceLiveReviewStatus.APPROVED
        and source.result_authority
        == models.RaceResultSourceAuthority.SUPPLEMENTAL
        and source.reviewed_by_id is None
        and source.reviewed_at == manifest.generated_at
        and source.terms_status == models.RaceSourceTermsStatus.APPROVED
        and source.automation_allowed is True
        and source.proof_network_allowed is False
        and source.evidence_url == _TERMS_URL
        and source.evidence_sha256
        == manifest.payload["terms_evidence_sha256"]
        and source.valid_until == manifest.policy_valid_until
        and source.registry_digest == manifest.payload["registry_digest"]
    ):
        errors.append("source_identity_mismatch")

    if allowlist is None:
        errors.append("allowlist_missing")
    elif not (
        allowlist.max_mode
        == models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
        and allowlist.coverage_proof_digest
        == manifest.payload["coverage_proof_digest"]
        and allowlist.official_verification_route
        == manifest.payload["official_verification_route"]
        and allowlist.official_verification_route_version
        == manifest.payload["official_verification_route_version"]
        and allowlist.official_verification_valid_until
        == manifest.official_verification_valid_until
        and allowlist.enabled is True
        and allowlist.version == 1
    ):
        errors.append("allowlist_mismatch")

    expected_participants = event["participants"]
    legacy_runner_rows = list(
        models.RaceEventRunner.objects.filter(event_id=event_id).order_by(
            "sort_order",
            "id",
        )
    )
    if len(legacy_runner_rows) != len(expected_participants):
        errors.append("legacy_runner_count_mismatch")
    else:
        for index, (legacy_runner, participant) in enumerate(
            zip(
                legacy_runner_rows,
                expected_participants,
                strict=True,
            ),
            start=1,
        ):
            if not (
                legacy_runner.external_runner_id
                == participant["external_runner_id"]
                and legacy_runner.sort_order == index
                and legacy_runner.horse_number
                == participant["horse_number"]
                and legacy_runner.horse_name
                == participant["canonical_name"]
                and legacy_runner.source_refs
                == {
                    "source_key": _SOURCE_KEY,
                    "external_runner_id": participant[
                        "external_runner_id"
                    ],
                }
            ):
                errors.append(
                    "legacy_runner_mismatch:"
                    f"{participant['external_runner_id']}"
                )

    participant_rows = list(
        models.RaceEventParticipant.objects.filter(event_id=event_id).order_by(
            "stable_key"
        )
    )
    participant_by_key = {row.stable_key: row for row in participant_rows}
    if len(participant_by_key) != len(expected_participants):
        errors.append("participant_count_mismatch")
    for participant in expected_participants:
        row = participant_by_key.get(participant["stable_key"])
        if row is None or not (
            row.canonical_name == participant["canonical_name"]
            and row.country_region == participant["country_region"]
            and row.horse_profile_id is None
            and row.term_id is None
            and row.birth_year is None
            and row.review_status == models.RaceLiveReviewStatus.APPROVED
        ):
            errors.append(
                f"participant_mismatch:{participant['stable_key']}"
            )
            continue
        identity_rows = list(row.source_identities.all())
        if (
            source is None
            or len(identity_rows) != 1
            or identity_rows[0].source_identity_id != source.pk
            or identity_rows[0].external_runner_id
            != participant["external_runner_id"]
        ):
            errors.append(
                f"participant_source_mismatch:{participant['stable_key']}"
            )

    expected_content_sha = _canonical_sha256(_racecard_payload(event))
    if revision is None:
        errors.append("racecard_revision_missing")
    elif not (
        models.RaceEventRevision.objects.filter(
            event_id=event_id,
            kind=models.RaceEventRevisionKind.RACECARD,
        ).count()
        == 1
        and revision.revision_no == 1
        and revision.phase == models.RaceResultPhase.RACECARD
        and revision.content_sha256 == expected_content_sha
        and revision.source_authority
        == models.RaceResultSourceAuthority.SUPPLEMENTAL
        and revision.decision_reason
        == f"initialized from approved manifest {manifest.sha256}"
        and revision.primary_observation_id is None
        and revision.supersedes_id is None
        and revision.published_at is None
        and revision.official_confirmed_at is None
        and revision.conflict_status
        == models.RaceEventRevisionConflictStatus.NONE
        and revision.applied_by_id is None
    ):
        errors.append("racecard_revision_mismatch")
    if control is not None and revision is not None and not (
        control.current_racecard_revision_id == revision.pk
        and control.last_known_good_racecard_revision_id == revision.pk
    ):
        errors.append("racecard_pointer_mismatch")

    if revision is not None:
        item_rows = list(revision.items.order_by("internal_order"))
        if len(item_rows) != len(expected_participants):
            errors.append("racecard_item_count_mismatch")
        for index, participant in enumerate(expected_participants, start=1):
            if index > len(item_rows):
                break
            item = item_rows[index - 1]
            participant_row = participant_by_key.get(participant["stable_key"])
            expected_barrier = participant.get("barrier", "")
            expected_jockey_name = participant.get("jockey_name", "")
            expected_field_provenance = {
                "external_runner_id": participant["external_runner_id"],
                "manifest_sha256": manifest.sha256,
                "source_key": _SOURCE_KEY,
            }
            if manifest.payload["schema_version"] == 2:
                expected_field_provenance["jockey_id"] = participant["jockey_id"]
            if participant_row is None or not (
                item.participant_id == participant_row.pk
                and item.source_order == index
                and item.internal_order == index
                and item.official_finish_position is None
                and item.status == participant["status"]
                and item.raw_status == participant["status"]
                and item.finish_time == ""
                and item.margin == ""
                and item.horse_number == participant["horse_number"]
                and item.barrier == expected_barrier
                and item.jockey_name == expected_jockey_name
                and item.trainer_name == ""
                and item.carried_weight == ""
                and item.field_provenance == expected_field_provenance
            ):
                errors.append(
                    f"racecard_item_mismatch:{participant['stable_key']}"
                )

    logs = list(
        models.OperationLog.objects.filter(
            action_type="race_live_event_initialized",
            target_type="race_event",
            target_id=str(event_id),
        )
    )
    if len(logs) != 1 or logs[0].detail != _expected_operation_detail(
        manifest, event
    ):
        errors.append("operation_log_mismatch")

    if _event_has_forbidden_result_state(event_id):
        errors.append("forbidden_result_state")
    return errors


def _inspect_initialization_state(
    manifest: LoadedRaceLiveInitializationManifest,
    rows: dict[int, models.RaceEvent],
) -> tuple[list[int], list[int]]:
    fresh: list[int] = []
    replayed: list[int] = []
    for event in manifest.payload["events"]:
        event_id = event["event_id"]
        if _event_has_forbidden_result_state(event_id):
            _fail(f"赛事已有赛果/observation/publication：event_id={event_id}")
        if not _event_has_any_initialization_rows(event_id):
            if _event_has_legacy_runners(event_id):
                _fail(
                    "赛事已有 legacy_runner，拒绝 fresh 初始化："
                    f"event_id={event_id}"
                )
            if not _event_matches_manifest(
                rows[event_id],
                event,
                schema_version=manifest.payload["schema_version"],
                replay=False,
            ):
                _fail(f"RaceEvent baseline 漂移：event_id={event_id}")
            fresh.append(event_id)
            continue
        control = models.RaceEventProjectionControl.objects.filter(
            event_id=event_id
        ).first()
        if (
            control is None
            or control.owner_manifest_sha256 != manifest.sha256
        ):
            _fail(f"赛事已由不同 manifest 初始化：event_id={event_id}")
        errors = _verify_event_exact(manifest, event)
        if errors:
            _fail(
                f"赛事存在非精确初始化状态：event_id={event_id} "
                + ",".join(errors)
            )
        replayed.append(event_id)
    return fresh, replayed


def _summary(
    manifest: LoadedRaceLiveInitializationManifest,
    *,
    mode: str,
    replayed_event_count: int = 0,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    event_ids = [event["event_id"] for event in manifest.payload["events"]]
    return {
        "mode": mode,
        "ok": not errors,
        "manifest_sha256": manifest.sha256,
        "approved_commit": manifest.payload["approved_commit"],
        "event_ids": event_ids,
        "event_count": len(event_ids),
        "participant_count": sum(
            len(event["participants"]) for event in manifest.payload["events"]
        ),
        "replayed_event_count": replayed_event_count,
        "error_count": len(errors or []),
        "errors": errors or [],
    }


def dry_run_race_live_initialization(
    manifest: LoadedRaceLiveInitializationManifest,
) -> dict[str, Any]:
    rows = _load_and_validate_events(manifest, lock=False)
    _validate_shared_rows(manifest)
    _, replayed = _inspect_initialization_state(manifest, rows)
    return _summary(
        manifest,
        mode="dry_run",
        replayed_event_count=len(replayed),
    )


def _create_missing_shared_rows(
    manifest: LoadedRaceLiveInitializationManifest,
) -> None:
    for scope_type, scope_key in _shared_policy_specs(manifest):
        policy = models.RaceLivePublicationPolicy.objects.filter(
            scope_type=scope_type,
            scope_key=scope_key,
        ).first()
        if policy is None:
            models.RaceLivePublicationPolicy.objects.create(
                scope_type=scope_type,
                scope_key=scope_key,
                mode=models.RaceLivePublicationMode.SHADOW,
                version=1,
                registry_digest=manifest.payload["registry_digest"],
                coverage_proof_digest=manifest.payload[
                    "coverage_proof_digest"
                ],
                valid_until=manifest.policy_valid_until,
            )
        elif not _shared_policy_matches(policy, manifest):
            _fail(f"publication policy 冲突：{scope_type}:{scope_key}")
    for scope_type, scope_key in _event_policy_specs(manifest):
        policy = models.RaceLivePublicationPolicy.objects.filter(
            scope_type=scope_type,
            scope_key=scope_key,
        ).first()
        if policy is None:
            models.RaceLivePublicationPolicy.objects.create(
                scope_type=scope_type,
                scope_key=scope_key,
                mode=models.RaceLivePublicationMode.SHADOW,
                version=1,
                registry_digest=manifest.payload["registry_digest"],
                coverage_proof_digest=manifest.payload[
                    "coverage_proof_digest"
                ],
                valid_until=manifest.policy_valid_until,
            )
        elif not _event_policy_matches(policy, manifest):
            _fail(f"publication policy 冲突：{scope_type}:{scope_key}")
    budget = models.RaceLiveHostBudget.objects.filter(host=_HOST).first()
    if budget is None:
        models.RaceLiveHostBudget.objects.create(
            host=_HOST,
            min_interval_ms=1050,
        )
    elif not (
        budget.min_interval_ms >= 1050
        and (
            manifest.payload["schema_version"] == 2
            or (
                budget.next_allowed_at is None
                and budget.consecutive_failures == 0
                and budget.circuit_open_until is None
                and budget.last_error_code == ""
                and budget.lock_version == 0
            )
        )
    ):
        _fail("The Racing API host budget 已存在且低于安全下限")


def _create_event_rows(
    manifest: LoadedRaceLiveInitializationManifest,
    event: dict[str, Any],
) -> None:
    event_id = event["event_id"]
    control = models.RaceEventProjectionControl.objects.create(
        event_id=event_id,
        write_owner=models.RaceEventProjectionWriteOwner.LIVE,
        owner_generation=1,
        owner_manifest_sha256=manifest.sha256,
        owner_changed_at=manifest.generated_at,
        next_racecard_revision_no=1,
        next_result_revision_no=1,
    )
    models.RaceEventLiveTracking.objects.create(
        event_id=event_id,
        state=event["tracking_state"],
        tracking_enabled=True,
        next_poll_at=_aware_datetime(event["next_poll_at"], "next_poll_at"),
        source_route_version="the_racing_api-free-v1",
        selection_reason=f"approved initialization manifest {manifest.sha256}",
    )
    source = models.RaceResultSourceIdentity.objects.create(
        event_id=event_id,
        source_key=_SOURCE_KEY,
        external_race_id=event["external_race_id"],
        canonical_url=f"https://{_HOST}/v1/racecards/{event['external_race_id']}",
        host=_HOST,
        identity_fields={
            "event_id": event_id,
            "event_slug": event["slug"],
            "event_year": event["year"],
            "manifest_sha256": manifest.sha256,
        },
        review_status=models.RaceLiveReviewStatus.APPROVED,
        result_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
        reviewed_at=manifest.generated_at,
        terms_status=models.RaceSourceTermsStatus.APPROVED,
        automation_allowed=True,
        proof_network_allowed=False,
        evidence_url=_TERMS_URL,
        evidence_sha256=manifest.payload["terms_evidence_sha256"],
        valid_until=manifest.policy_valid_until,
        registry_digest=manifest.payload["registry_digest"],
    )
    models.RaceLiveEventPublicationAllowlist.objects.create(
        event_id=event_id,
        source_key=_SOURCE_KEY,
        max_mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
        coverage_proof_digest=manifest.payload["coverage_proof_digest"],
        official_verification_route=manifest.payload[
            "official_verification_route"
        ],
        official_verification_route_version=manifest.payload[
            "official_verification_route_version"
        ],
        official_verification_valid_until=(
            manifest.official_verification_valid_until
        ),
        enabled=True,
        version=1,
    )
    participant_rows: list[models.RaceEventParticipant] = []
    for participant in event["participants"]:
        participant_row = models.RaceEventParticipant.objects.create(
            event_id=event_id,
            stable_key=participant["stable_key"],
            canonical_name=participant["canonical_name"],
            country_region=participant["country_region"],
            review_status=models.RaceLiveReviewStatus.APPROVED,
        )
        participant_rows.append(participant_row)
        models.RaceEventParticipantSourceIdentity.objects.create(
            participant=participant_row,
            source_identity=source,
            external_runner_id=participant["external_runner_id"],
        )
    revision = models.RaceEventRevision.objects.create(
        event_id=event_id,
        kind=models.RaceEventRevisionKind.RACECARD,
        revision_no=1,
        phase=models.RaceResultPhase.RACECARD,
        content_sha256=_canonical_sha256(_racecard_payload(event)),
        source_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
        decision_reason=f"initialized from approved manifest {manifest.sha256}",
        conflict_status=models.RaceEventRevisionConflictStatus.NONE,
    )
    for index, (participant, participant_row) in enumerate(
        zip(event["participants"], participant_rows, strict=True),
        start=1,
    ):
        field_provenance = {
            "external_runner_id": participant["external_runner_id"],
            "manifest_sha256": manifest.sha256,
            "source_key": _SOURCE_KEY,
        }
        if manifest.payload["schema_version"] == 2:
            field_provenance["jockey_id"] = participant["jockey_id"]
        models.RaceEventRevisionItem.objects.create(
            revision=revision,
            participant=participant_row,
            source_order=index,
            internal_order=index,
            status=participant["status"],
            raw_status=participant["status"],
            horse_number=participant["horse_number"],
            barrier=participant.get("barrier", ""),
            jockey_name=participant.get("jockey_name", ""),
            field_provenance=field_provenance,
        )
        models.RaceEventRunner.objects.create(
            event_id=event_id,
            external_runner_id=participant["external_runner_id"],
            sort_order=index,
            horse_number=participant["horse_number"],
            barrier=participant.get("barrier", ""),
            horse_name=participant["canonical_name"],
            jockey_name=participant.get("jockey_name", ""),
            running_status=models.RaceRunnerStatus.DECLARED,
            source_refs={
                "source_key": _SOURCE_KEY,
                "external_runner_id": participant["external_runner_id"],
            },
            raw_payload={},
        )
    control.current_racecard_revision = revision
    control.last_known_good_racecard_revision = revision
    control.next_racecard_revision_no = 2
    control.save(
        update_fields=(
            "current_racecard_revision",
            "last_known_good_racecard_revision",
            "next_racecard_revision_no",
            "updated_at",
        )
    )
    models.OperationLog.objects.create(
        action_type="race_live_event_initialized",
        target_type="race_event",
        target_id=str(event_id),
        detail=_expected_operation_detail(manifest, event),
    )


def apply_race_live_initialization(
    manifest: LoadedRaceLiveInitializationManifest,
) -> dict[str, Any]:
    with transaction.atomic():
        rows = _load_and_validate_events(manifest, lock=True)
        event_ids = [event["event_id"] for event in manifest.payload["events"]]
        list(
            models.RaceEventProjectionControl.objects.select_for_update().filter(
                event_id__in=event_ids
            )
        )
        list(
            models.RaceEventRunner.objects.select_for_update().filter(
                event_id__in=event_ids
            )
        )
        # Lock every existing shared row before deciding whether it is reusable.
        list(
            models.RaceLivePublicationPolicy.objects.select_for_update().filter(
                scope_type__in={
                    scope_type for scope_type, _ in _policy_specs(manifest)
                }
            )
        )
        list(
            models.RaceLiveHostBudget.objects.select_for_update().filter(host=_HOST)
        )
        _validate_shared_rows(manifest)
        fresh, replayed = _inspect_initialization_state(manifest, rows)
        _create_missing_shared_rows(manifest)
        fresh_set = set(fresh)
        for event in manifest.payload["events"]:
            if event["event_id"] in fresh_set:
                # Recheck uniqueness under the transaction before any event write.
                if models.RaceResultSourceIdentity.objects.filter(
                    source_key=_SOURCE_KEY,
                    external_race_id=event["external_race_id"],
                ).exists():
                    _fail(
                        "external_race_id 已绑定其他赛事："
                        f"{event['external_race_id']}"
                    )
        for event in manifest.payload["events"]:
            if event["event_id"] in fresh_set:
                if manifest.payload["schema_version"] == 2:
                    row = rows[event["event_id"]]
                    source_off_dt = _aware_datetime(
                        event["source_off_dt"],
                        "source_off_dt",
                    )
                    row.race_datetime = source_off_dt
                    row.local_start_time = source_off_dt.astimezone(
                        ZoneInfo(event["expected_timezone_name"])
                    ).time().replace(tzinfo=None)
                    row.save(
                        update_fields=(
                            "race_datetime",
                            "local_start_time",
                            "updated_at",
                        )
                    )
                _create_event_rows(manifest, event)
        for event in manifest.payload["events"]:
            errors = _verify_event_exact(manifest, event)
            if errors:
                _fail(
                    f"apply 后精确核验失败：event_id={event['event_id']} "
                    + ",".join(errors)
                )
    return _summary(
        manifest,
        mode="apply",
        replayed_event_count=len(replayed),
    )


def verify_race_live_initialization(
    manifest: LoadedRaceLiveInitializationManifest,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        _load_and_validate_events(manifest, lock=False)
    except RaceLiveInitializationError as exc:
        errors.append(str(exc))
    for scope_type, scope_key in _shared_policy_specs(manifest):
        policies = list(
            models.RaceLivePublicationPolicy.objects.filter(
                scope_type=scope_type,
                scope_key=scope_key,
            )
        )
        if len(policies) != 1 or not _shared_policy_matches(
            policies[0],
            manifest,
        ):
            errors.append(f"policy_mismatch:{scope_type}:{scope_key}")
    for scope_type, scope_key in _event_policy_specs(manifest):
        policies = list(
            models.RaceLivePublicationPolicy.objects.filter(
                scope_type=scope_type,
                scope_key=scope_key,
            )
        )
        if len(policies) != 1 or not _event_policy_matches(
            policies[0],
            manifest,
        ):
            errors.append(f"policy_mismatch:{scope_type}:{scope_key}")
    budgets = list(models.RaceLiveHostBudget.objects.filter(host=_HOST))
    if len(budgets) != 1 or not (
        budgets[0].min_interval_ms >= 1050
        and (
            manifest.payload["schema_version"] == 2
            or (
                budgets[0].next_allowed_at is None
                and budgets[0].consecutive_failures == 0
                and budgets[0].circuit_open_until is None
                and budgets[0].last_error_code == ""
                and budgets[0].lock_version == 0
            )
        )
    ):
        errors.append("host_budget_mismatch")
    for event in manifest.payload["events"]:
        errors.extend(
            f"event_id={event['event_id']}:{error}"
            for error in _verify_event_exact(manifest, event)
        )
    return _summary(
        manifest,
        mode="verify",
        replayed_event_count=0,
        errors=errors,
    )

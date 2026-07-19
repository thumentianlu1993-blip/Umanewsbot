from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from stable import models
from stable.services.race_events import (
    admit_persisted_race_live_publication,
    resolve_race_live_public_read,
)


class RaceLivePublicationTransitionError(ValueError):
    """Raised when a publication transition is not an exact, safe CAS."""


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MAX_FILE_BYTES = 2 * 1024 * 1024
_TRANSITIONS = {
    "promote_shadow",
    "disable_public_read",
    "restore_public_read",
}
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "transition",
        "approved_commit",
        "generated_at",
        "event_id",
        "source_key",
        "route_registry_digest",
        "route_contract_digest",
        "route_terms_digest",
        "unrelated_scope_digest",
        "expected",
        "target",
    }
)
_EXPECTED_KEYS = frozenset(
    {
        "event",
        "manual_locks",
        "write_owner",
        "owner_generation",
        "owner_manifest_sha256",
        "source",
        "tracking",
        "observation",
        "result_revision",
        "racecard_revision",
        "participant_digest",
        "participant_identity_digest",
        "policies",
        "allowlist",
        "event_universes",
        "counts",
        "event_status",
        "result_confirmed",
    }
)
_TRACKING_KEYS = frozenset(
    {
        "state",
        "tracking_enabled",
        "next_poll_at",
        "last_attempt_at",
        "last_success_at",
        "last_observation_hash",
        "consecutive_failures",
        "stale_at",
        "claim_generation",
        "active_attempt_token",
        "claim_expires_at",
        "provisional_published",
    }
)
_POLICY_KEYS = frozenset(
    {
        "scope_type",
        "scope_key",
        "mode",
        "version",
        "registry_digest",
        "coverage_proof_digest",
        "valid_until",
    }
)
_ALLOWLIST_KEYS = frozenset(
    {
        "version",
        "enabled",
        "max_mode",
        "coverage_proof_digest",
        "official_verification_route",
        "official_verification_route_version",
        "official_verification_contract_digest",
        "official_terms_evidence_digest",
        "official_verification_valid_until",
    }
)
_REGISTRY_KEYS = frozenset(
    {
        "schema_version",
        "route",
        "parser_version",
        "country_region",
        "source_key",
        "official_results_url",
        "access_mode",
        "automation_allowed",
        "responsible_role",
        "sla_minutes",
        "allowed_marker_types",
        "terms_evidence",
        "valid_until",
        "contract_digest",
    }
)


@dataclass(frozen=True)
class LoadedRaceLivePublicationTransition:
    path: Path
    sha256: str
    payload: dict[str, Any]


def _fail(message: str) -> None:
    raise RaceLivePublicationTransitionError(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise RaceLivePublicationTransitionError("JSON 不是严格可序列化值") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if timezone.is_naive(value):
        _fail("数据库时间必须包含时区")
    return value.isoformat()


def _aware_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(f"{label} 必须是 ISO-8601 aware datetime")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RaceLivePublicationTransitionError(
            f"{label} 不是合法时间"
        ) from exc
    if timezone.is_naive(result):
        _fail(f"{label} 必须包含时区")
    return result


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"JSON 含重复 key：{key}")
        result[key] = value
    return result


def _read_safe_file(path_value: str | os.PathLike[str]) -> tuple[Path, bytes]:
    path = Path(path_value)
    if not path.is_absolute():
        _fail("文件路径必须是绝对路径")
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise RaceLivePublicationTransitionError("文件不可读") from exc
    if not stat.S_ISREG(path_stat.st_mode) or stat.S_ISLNK(path_stat.st_mode):
        _fail("文件必须是非 symlink 普通文件")
    if path_stat.st_size <= 0 or path_stat.st_size > _MAX_FILE_BYTES:
        _fail("文件大小不安全")
    if stat.S_IMODE(path_stat.st_mode) & 0o077:
        _fail("文件不得授予 group/other 权限")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != path_stat.st_dev
            or opened.st_ino != path_stat.st_ino
            or opened.st_size != path_stat.st_size
        ):
            _fail("文件读取期间发生变化")
        chunks: list[bytes] = []
        remaining = path_stat.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65536))
            if not chunk:
                _fail("文件读取不完整")
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if os.fstat(descriptor).st_size != path_stat.st_size:
            _fail("文件读取期间发生变化")
    finally:
        os.close(descriptor)
    return path, data


def _parse_json(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda constant: _fail(
                f"{label} 含非法常量 {constant}"
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RaceLivePublicationTransitionError(f"{label} 不是合法 JSON") from exc
    if not isinstance(value, dict):
        _fail(f"{label} 必须是 object")
    return value


def _registry_path() -> Path:
    return (
        Path(settings.BASE_DIR).parent
        / "runtime"
        / "policies"
        / "race_live"
        / "official_route_bha_manual_v1.json"
    )


def read_bha_manual_route_registry(
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    path = _registry_path()
    data = path.read_bytes()
    payload = _parse_json(data, "BHA route registry")
    if set(payload) != _REGISTRY_KEYS:
        _fail("BHA route registry schema 不匹配")
    if payload["schema_version"] != 1:
        _fail("BHA route registry schema version 不支持")
    expected_values = {
        "route": "bha_manual_verification",
        "parser_version": "bha-manual-v1",
        "country_region": models.RacingRegion.UNITED_KINGDOM,
        "source_key": "bha_manual",
        "access_mode": "manual_browser_only",
        "automation_allowed": False,
        "responsible_role": "release_operator",
        "sla_minutes": 15,
    }
    if any(payload[key] != value for key, value in expected_values.items()):
        _fail("BHA route registry 固定契约不匹配")
    if (
        not isinstance(payload["official_results_url"], str)
        or not payload["official_results_url"].startswith(
            "https://www.britishhorseracing.com/"
        )
    ):
        _fail("BHA Results URL 不合法")
    markers = payload["allowed_marker_types"]
    if (
        not isinstance(markers, list)
        or not markers
        or len(set(markers)) != len(markers)
        or any(not isinstance(marker, str) or not marker for marker in markers)
    ):
        _fail("BHA marker allowlist 不合法")
    terms = payload["terms_evidence"]
    if (
        not isinstance(terms, dict)
        or set(terms) != {"url", "sha256", "observed_at"}
        or _SHA256_RE.fullmatch(str(terms["sha256"])) is None
        or not str(terms["url"]).startswith(
            "https://www.britishhorseracing.com/"
        )
    ):
        _fail("BHA terms evidence 不合法")
    contract_payload = dict(payload)
    contract_digest = contract_payload.pop("contract_digest", None)
    if contract_digest != _sha256(contract_payload):
        _fail("BHA route contract digest 不匹配")
    try:
        valid_until = datetime.fromisoformat(
            str(payload["valid_until"]).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise RaceLivePublicationTransitionError(
            "BHA route valid_until 不合法"
        ) from exc
    if timezone.is_naive(valid_until):
        _fail("BHA route valid_until 必须包含时区")
    effective_now = now or timezone.now()
    if timezone.is_naive(effective_now) or valid_until <= effective_now:
        _fail("BHA route registry 已过期")
    return payload, hashlib.sha256(data).hexdigest()


def read_manual_official_route_registry(
    *,
    route: str,
    now: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    """Read one tracked manual route; retain the frozen BHA v1 compatibility."""

    if route == "bha_manual_verification":
        return read_bha_manual_route_registry(now=now)
    path = (
        Path(__file__).resolve().parents[3]
        / "runtime"
        / "policies"
        / "race_live"
        / "official_routes_manual_v1.json"
    )
    data = path.read_bytes()
    payload = _parse_json(data, "manual official route registry")
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("routes"), dict)
    ):
        _fail("manual official route registry schema 不匹配")
    entry = payload["routes"].get(route)
    if not isinstance(entry, dict):
        _fail("manual official route 不在受审 registry")
    expected_entry_keys = {
        "country_region",
        "source_key",
        "access_mode",
        "automation_allowed",
        "allowed_hosts",
        "allowed_path_prefixes",
        "allowed_marker_types",
        "parser_version",
        "responsible_role",
        "sla_minutes",
        "permission_evidence",
        "terms_evidence",
        "contract_digest",
    }
    if (
        set(entry) != expected_entry_keys
        or entry.get("access_mode") != "manual_browser_only"
        or entry.get("automation_allowed") is not False
        or entry.get("country_region")
        not in {
            models.RacingRegion.UNITED_KINGDOM,
            models.RacingRegion.FRANCE,
            models.RacingRegion.HONG_KONG,
            models.RacingRegion.JAPAN,
            models.RacingRegion.UNITED_STATES,
        }
        or not isinstance(entry.get("allowed_hosts"), list)
        or len(entry["allowed_hosts"]) != 1
        or not isinstance(entry.get("allowed_path_prefixes"), list)
        or len(entry["allowed_path_prefixes"]) != 1
        or _SHA256_RE.fullmatch(str(entry.get("contract_digest"))) is None
    ):
        _fail("manual official route contract 不合法")
    contract_payload = dict(entry)
    contract_digest = contract_payload.pop("contract_digest")
    if contract_digest != _sha256(contract_payload):
        _fail("manual official route contract digest 不匹配")
    effective_now = now or timezone.now()
    valid_until = _aware_datetime(payload.get("valid_until"), "valid_until")
    if timezone.is_naive(effective_now) or valid_until <= effective_now:
        _fail("manual official route registry 已过期")
    official_results_url = (
        f"https://{entry['allowed_hosts'][0]}"
        f"{entry['allowed_path_prefixes'][0]}"
    )
    permission = entry["permission_evidence"]
    terms = entry["terms_evidence"]
    if (
        not isinstance(permission, dict)
        or set(permission)
        != {
            "basis",
            "authorized_at",
            "valid_until",
            "route",
            "source_key",
            "scope",
            "manual_access_allowed",
            "automation_allowed",
            "sha256",
        }
        or permission["basis"]
        != "user_source_use_authorization_2026-07-19"
        or permission["route"] != route
        or permission["source_key"] != entry["source_key"]
        or permission["scope"] != "manual_official_facts_verification"
        or permission["manual_access_allowed"] is not True
        or permission["automation_allowed"] is not False
    ):
        _fail("manual official route permission evidence 不合法")
    permission_payload = dict(permission)
    permission_digest = permission_payload.pop("sha256")
    if (
        _SHA256_RE.fullmatch(str(permission_digest)) is None
        or permission_digest != _sha256(permission_payload)
        or _aware_datetime(
            permission["authorized_at"],
            "permission_evidence.authorized_at",
        )
        > effective_now
        or _aware_datetime(
            permission["valid_until"],
            "permission_evidence.valid_until",
        )
        <= effective_now
    ):
        _fail("manual official route permission evidence 漂移或过期")
    if (
        not isinstance(terms, dict)
        or set(terms)
        != {
            "basis",
            "observed_at",
            "valid_until",
            "route",
            "source_key",
            "scope",
            "manual_access_allowed",
            "automation_allowed",
            "sha256",
        }
        or terms["basis"]
        != "user_source_use_authorization_2026-07-19"
        or terms["route"] != route
        or terms["source_key"] != entry["source_key"]
        or terms["scope"] != "source_terms_use_authorization"
        or terms["manual_access_allowed"] is not True
        or terms["automation_allowed"] is not False
    ):
        _fail("manual official route terms evidence 不合法")
    terms_payload = dict(terms)
    terms_digest = terms_payload.pop("sha256")
    if (
        _SHA256_RE.fullmatch(str(terms_digest)) is None
        or terms_digest != _sha256(terms_payload)
        or terms_digest == contract_digest
        or _aware_datetime(
            terms["observed_at"],
            "terms_evidence.observed_at",
        )
        > effective_now
        or _aware_datetime(
            terms["valid_until"],
            "terms_evidence.valid_until",
        )
        <= effective_now
    ):
        _fail("manual official route terms evidence 漂移或过期")
    normalized = {
        "schema_version": 1,
        "route": route,
        "parser_version": entry["parser_version"],
        "country_region": entry["country_region"],
        "source_key": entry["source_key"],
        "official_results_url": official_results_url,
        "access_mode": entry["access_mode"],
        "automation_allowed": False,
        "responsible_role": entry["responsible_role"],
        "sla_minutes": entry["sla_minutes"],
        "allowed_marker_types": entry["allowed_marker_types"],
        "allowed_hosts": tuple(entry["allowed_hosts"]),
        "allowed_path_prefixes": tuple(entry["allowed_path_prefixes"]),
        "terms_evidence": dict(terms),
        "valid_until": min(
            valid_until,
            _aware_datetime(
                permission["valid_until"],
                "permission_evidence.valid_until",
            ),
            _aware_datetime(
                terms["valid_until"],
                "terms_evidence.valid_until",
            ),
        ).isoformat(),
        "contract_digest": entry["contract_digest"],
    }
    route_registry_digest = _sha256(
        {
            "registry_version": payload.get("registry_version"),
            "route": route,
            "entry": entry,
        }
    )
    return normalized, route_registry_digest


def _policy_snapshot(event: models.RaceEvent, source_key: str) -> list[dict[str, Any]]:
    specs = (
        (models.RaceLivePublicationScopeType.GLOBAL, "global"),
        (models.RaceLivePublicationScopeType.REGION, event.country_region),
        (models.RaceLivePublicationScopeType.SOURCE, source_key),
        (models.RaceLivePublicationScopeType.EVENT, str(event.pk)),
    )
    rows = {
        (row.scope_type, row.scope_key): row
        for row in models.RaceLivePublicationPolicy.objects.filter(
            scope_type__in=[spec[0] for spec in specs],
        )
    }
    result = []
    for scope_type, scope_key in specs:
        row = rows.get((scope_type, scope_key))
        if row is None:
            _fail(f"publication policy 缺失：{scope_type}:{scope_key}")
        result.append(
            {
                "scope_type": row.scope_type,
                "scope_key": row.scope_key,
                "mode": row.mode,
                "version": row.version,
                "registry_digest": row.registry_digest,
                "coverage_proof_digest": row.coverage_proof_digest,
                "valid_until": _dt(row.valid_until),
            }
        )
    return result


def _tracking_snapshot(tracking: models.RaceEventLiveTracking) -> dict[str, Any]:
    return {
        "state": tracking.state,
        "tracking_enabled": tracking.tracking_enabled,
        "next_poll_at": _dt(tracking.next_poll_at),
        "last_attempt_at": _dt(tracking.last_attempt_at),
        "last_success_at": _dt(tracking.last_success_at),
        "last_observation_hash": tracking.last_observation_hash,
        "consecutive_failures": tracking.consecutive_failures,
        "stale_at": _dt(tracking.stale_at),
        "claim_generation": tracking.claim_generation,
        "active_attempt_token": tracking.active_attempt_token,
        "claim_expires_at": _dt(tracking.claim_expires_at),
        "provisional_published": tracking.provisional_published_at is not None,
    }


def _allowlist_snapshot(
    allowlist: models.RaceLiveEventPublicationAllowlist,
) -> dict[str, Any]:
    return {
        "version": allowlist.version,
        "enabled": allowlist.enabled,
        "max_mode": allowlist.max_mode,
        "coverage_proof_digest": allowlist.coverage_proof_digest,
        "official_verification_route": allowlist.official_verification_route,
        "official_verification_route_version": (
            allowlist.official_verification_route_version
        ),
        "official_verification_contract_digest": (
            allowlist.official_verification_contract_digest
        ),
        "official_terms_evidence_digest": (
            allowlist.official_terms_evidence_digest
        ),
        "official_verification_valid_until": _dt(
            allowlist.official_verification_valid_until
        ),
    }


def _participant_digest(revision: models.RaceEventRevision) -> str:
    return _sha256(
        [
            {
                "participant_id": item.participant_id,
                "participant_review_status": item.participant.review_status,
                "internal_order": item.internal_order,
                "official_finish_position": item.official_finish_position,
                "status": item.status,
            }
            for item in revision.items.select_related("participant").order_by(
                "internal_order", "pk"
            )
        ]
    )


def _racecard_revision_snapshot(
    revision: models.RaceEventRevision,
) -> dict[str, Any]:
    return {
        "id": revision.pk,
        "content_sha256": revision.content_sha256,
        "item_digest": _sha256(
            [
                {
                    "participant_id": item.participant_id,
                    "participant_review_status": (
                        item.participant.review_status
                    ),
                    "source_order": item.source_order,
                    "internal_order": item.internal_order,
                    "status": item.status,
                    "horse_number": item.horse_number,
                    "barrier": item.barrier,
                    "jockey_name": item.jockey_name,
                    "trainer_name": item.trainer_name,
                    "carried_weight": item.carried_weight,
                }
                for item in revision.items.select_related(
                    "participant"
                ).order_by("internal_order", "pk")
            ]
        ),
    }


def _participant_identity_digest(
    *,
    event_id: int,
    source_identity_id: int,
) -> str:
    return _sha256(
        list(
            models.RaceEventParticipantSourceIdentity.objects.filter(
                participant__event_id=event_id,
                source_identity_id=source_identity_id,
            )
            .order_by("participant_id", "pk")
            .values("participant_id", "external_runner_id")
        )
    )


def _current_snapshot(event_id: int, source_key: str) -> dict[str, Any]:
    try:
        event = models.RaceEvent.objects.get(pk=event_id)
        control = models.RaceEventProjectionControl.objects.get(event_id=event_id)
        tracking = models.RaceEventLiveTracking.objects.get(event_id=event_id)
        source = models.RaceResultSourceIdentity.objects.get(
            event_id=event_id,
            source_key=source_key,
        )
        allowlist = models.RaceLiveEventPublicationAllowlist.objects.get(
            event_id=event_id,
            source_key=source_key,
        )
        observation = models.RaceResultObservation.objects.get(
            pk=control.current_result_revision.primary_observation_id
        )
        result_revision = control.current_result_revision
        racecard_revision = control.current_racecard_revision
    except (
        models.RaceEvent.DoesNotExist,
        models.RaceEventProjectionControl.DoesNotExist,
        models.RaceEventLiveTracking.DoesNotExist,
        models.RaceResultSourceIdentity.DoesNotExist,
        models.RaceLiveEventPublicationAllowlist.DoesNotExist,
        models.RaceResultObservation.DoesNotExist,
        AttributeError,
    ) as exc:
        raise RaceLivePublicationTransitionError(
            "event publication baseline 不完整"
        ) from exc
    if result_revision is None or racecard_revision is None:
        _fail("current revision baseline 不完整")
    lock_flags = event.manual_lock_flags
    return {
        "event": {
            "id": event.pk,
            "slug": event.slug,
            "year": event.year,
            "country_region": event.country_region,
            "race_datetime": _dt(event.race_datetime),
        },
        "manual_locks": {
            "results": (
                not isinstance(lock_flags, dict)
                or bool(lock_flags.get("results"))
            ),
            "runners": (
                not isinstance(lock_flags, dict)
                or bool(lock_flags.get("runners"))
            ),
        },
        "write_owner": control.write_owner,
        "owner_generation": control.owner_generation,
        "owner_manifest_sha256": control.owner_manifest_sha256,
        "source": {
            "id": source.pk,
            "external_race_id": source.external_race_id,
            "review_status": source.review_status,
            "result_authority": source.result_authority,
            "terms_status": source.terms_status,
            "automation_allowed": source.automation_allowed,
            "valid_until": _dt(source.valid_until),
            "registry_digest": source.registry_digest,
        },
        "tracking": _tracking_snapshot(tracking),
        "observation": {
            "id": observation.pk,
            "parser_version": observation.parser_version,
            "phase": observation.result_phase,
            "normalized_sha256": observation.normalized_sha256,
        },
        "result_revision": {
            "id": result_revision.pk,
            "revision_no": result_revision.revision_no,
            "phase": result_revision.phase,
            "content_sha256": result_revision.content_sha256,
            "published": result_revision.published_at is not None,
        },
        "racecard_revision": _racecard_revision_snapshot(
            racecard_revision
        ),
        "participant_digest": _participant_digest(result_revision),
        "participant_identity_digest": _participant_identity_digest(
            event_id=event_id,
            source_identity_id=source.pk,
        ),
        "policies": _policy_snapshot(event, source_key),
        "allowlist": _allowlist_snapshot(allowlist),
        "event_universes": {
            "tracking_event_ids": list(
                models.RaceEventLiveTracking.objects.order_by("event_id").values_list(
                    "event_id", flat=True
                )
            ),
            "allowlist_event_ids": list(
                models.RaceLiveEventPublicationAllowlist.objects.order_by(
                    "event_id"
                ).values_list("event_id", flat=True)
            ),
        },
        "counts": {
            "publication": models.RaceEventRevisionPublication.objects.filter(
                revision__event_id=event_id
            ).count(),
            "legacy_result": models.RaceEventResult.objects.filter(
                event_id=event_id
            ).count(),
            "incident": models.RaceLiveOfficialVerificationIncident.objects.filter(
                event_id=event_id
            ).count(),
        },
        "event_status": event.status,
        "result_confirmed": event.result_confirmed_at is not None,
    }


def _unrelated_scope_digest(*, event_id: int) -> str:
    """Bind state that a single-event transition is forbidden to mutate."""

    tracking = [
        {
            **row,
            "next_poll_at": _dt(row["next_poll_at"]),
            "claim_expires_at": _dt(row["claim_expires_at"]),
        }
        for row in models.RaceEventLiveTracking.objects.exclude(
            event_id=event_id
        )
        .order_by("event_id")
        .values(
            "event_id",
            "state",
            "tracking_enabled",
            "next_poll_at",
            "claim_generation",
            "active_attempt_token",
            "claim_expires_at",
            "lock_version",
        )
    ]
    allowlists = [
        {
            **row,
            "official_verification_valid_until": _dt(
                row["official_verification_valid_until"]
            ),
        }
        for row in models.RaceLiveEventPublicationAllowlist.objects.exclude(
            event_id=event_id
        )
        .order_by("event_id", "source_key")
        .values(
            "event_id",
            "source_key",
            "enabled",
            "max_mode",
            "coverage_proof_digest",
            "version",
            "official_verification_route",
            "official_verification_route_version",
            "official_verification_contract_digest",
            "official_terms_evidence_digest",
            "official_verification_valid_until",
        )
    ]
    policies = [
        {
            **row,
            "valid_until": _dt(row["valid_until"]),
        }
        for row in models.RaceLivePublicationPolicy.objects.exclude(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(event_id),
        )
        .order_by("scope_type", "scope_key")
        .values(
            "scope_type",
            "scope_key",
            "mode",
            "version",
            "registry_digest",
            "coverage_proof_digest",
            "valid_until",
        )
    ]
    controls = list(
        models.RaceEventProjectionControl.objects.exclude(
            event_id=event_id
        )
        .order_by("event_id")
        .values(
            "event_id",
            "write_owner",
            "owner_generation",
            "current_racecard_revision_id",
            "current_result_revision_id",
            "last_provisional_result_revision_id",
        )
    )
    return _sha256(
        {
            "tracking": tracking,
            "allowlists": allowlists,
            "policies": policies,
            "projection_controls": controls,
        }
    )


def _predict_target(
    snapshot: dict[str, Any],
    *,
    transition_name: str,
    contract_digest: str,
    terms_digest: str,
) -> dict[str, Any]:
    target = deepcopy(snapshot)
    policy_targets: list[dict[str, Any]] = []
    for policy in target["policies"]:
        changed = (
            policy["scope_type"]
            == models.RaceLivePublicationScopeType.EVENT
        )
        if changed:
            policy["version"] += 1
            policy["mode"] = (
                models.RaceLivePublicationMode.SHADOW
                if transition_name == "disable_public_read"
                else models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
            )
        policy_targets.append(
            {
                "scope_type": policy["scope_type"],
                "scope_key": policy["scope_key"],
                "mode": policy["mode"],
                "version": policy["version"],
            }
        )
    if transition_name == "promote_shadow":
        target["allowlist"]["version"] += 1
        target["allowlist"][
            "official_verification_contract_digest"
        ] = contract_digest
        target["allowlist"]["official_terms_evidence_digest"] = terms_digest
        target["tracking"]["tracking_enabled"] = False
        target["tracking"]["next_poll_at"] = None
        target["tracking"]["provisional_published"] = True
        target["result_revision"]["published"] = True
        target["counts"] = {
            "publication": 1,
            "legacy_result": target["result_revision"].get(
                "participant_count",
                0,
            ),
            "incident": 1,
        }
        target["event_status"] = models.RaceEventStatus.FINISHED
        target["result_confirmed"] = False
    return {
        "policies": policy_targets,
        "allowlist": target["allowlist"],
        "tracking": target["tracking"],
        "result_revision_published": target["result_revision"]["published"],
        "counts": target["counts"],
        "event_status": target["event_status"],
        "result_confirmed": target["result_confirmed"],
    }


def _with_participant_count(snapshot: dict[str, Any], event_id: int) -> dict[str, Any]:
    snapshot = deepcopy(snapshot)
    revision_id = snapshot["result_revision"]["id"]
    snapshot["result_revision"]["participant_count"] = (
        models.RaceEventRevisionItem.objects.filter(
            revision_id=revision_id
        ).count()
    )
    return snapshot


def _manifest_payload(
    *,
    approved_commit: str,
    generated_at: datetime,
    transition_name: str,
    event_id: int,
    source_key: str,
    registry_digest: str,
    registry: dict[str, Any],
    expected: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "transition": transition_name,
        "approved_commit": approved_commit,
        "generated_at": generated_at.isoformat(),
        "event_id": event_id,
        "source_key": source_key,
        "route_registry_digest": registry_digest,
        "route_contract_digest": registry["contract_digest"],
        "route_terms_digest": registry["terms_evidence"]["sha256"],
        "unrelated_scope_digest": _unrelated_scope_digest(
            event_id=event_id
        ),
        "expected": expected,
        "target": _predict_target(
            expected,
            transition_name=transition_name,
            contract_digest=registry["contract_digest"],
            terms_digest=registry["terms_evidence"]["sha256"],
        ),
    }


def _build_race_live_publication_transition_bundle_snapshot(
    *,
    event_id: int,
    approved_commit: str,
    generated_at: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
    ):
        _fail("event_id 必须是正整数")
    if not isinstance(approved_commit, str) or _COMMIT_RE.fullmatch(
        approved_commit
    ) is None:
        _fail("approved_commit 必须是 40 位 lowercase commit")
    now = generated_at or timezone.now()
    if timezone.is_naive(now):
        _fail("generated_at 必须包含时区")
    source_key = "the_racing_api"
    configured_route = (
        models.RaceLiveEventPublicationAllowlist.objects.filter(
            event_id=event_id,
            source_key=source_key,
        )
        .values_list("official_verification_route", flat=True)
        .first()
    )
    registry, registry_digest = read_manual_official_route_registry(
        route=configured_route,
        now=now,
    )
    current = _with_participant_count(
        _current_snapshot(event_id, source_key),
        event_id,
    )
    source_valid_until = current["source"]["valid_until"]
    policy_valid_until = [
        policy["valid_until"] for policy in current["policies"]
    ]
    policy_registry_digests = {
        policy["registry_digest"] for policy in current["policies"]
    }
    policy_coverage_digests = {
        policy["coverage_proof_digest"] for policy in current["policies"]
    }
    result_participant_ids = set(
        models.RaceEventRevisionItem.objects.filter(
            revision_id=current["result_revision"]["id"]
        ).values_list("participant_id", flat=True)
    )
    racecard_participant_ids = set(
        models.RaceEventRevisionItem.objects.filter(
            revision_id=current["racecard_revision"]["id"]
        ).values_list("participant_id", flat=True)
    )
    participant_identity_rows = list(
        models.RaceEventParticipantSourceIdentity.objects.filter(
            source_identity_id=current["source"]["id"],
            participant_id__in=result_participant_ids,
        ).values_list("participant_id", "external_runner_id")
    )
    unrelated_scope_digest = _sha256(
        {
            "tracking_event_ids": [
                value
                for value in current["event_universes"][
                    "tracking_event_ids"
                ]
                if value != event_id
            ],
            "allowlist_event_ids": [
                value
                for value in current["event_universes"][
                    "allowlist_event_ids"
                ]
                if value != event_id
            ],
        }
    )
    if (
        current["write_owner"]
        != models.RaceEventProjectionWriteOwner.LIVE
        or current["event"]["country_region"] != registry["country_region"]
        or current["event"]["race_datetime"] is None
        or current["event_status"]
        not in {
            models.RaceEventStatus.SCHEDULED,
            models.RaceEventStatus.RUNNING,
            models.RaceEventStatus.FINISHED,
        }
        or current["manual_locks"] != {"results": False, "runners": False}
        or current["tracking"]["state"]
        != models.RaceEventLiveState.PROVISIONAL_RESULT
        or current["tracking"]["active_attempt_token"] != ""
        or current["tracking"]["claim_expires_at"] is not None
        or current["result_revision"]["published"] is not False
        or current["counts"]
        != {"publication": 0, "legacy_result": 0, "incident": 0}
        or current["allowlist"]["version"] != 1
        or current["allowlist"]["enabled"] is not True
        or current["allowlist"]["max_mode"]
        != models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
        or current["allowlist"]["official_verification_route"]
        != registry["route"]
        or current["allowlist"]["official_verification_route_version"]
        != registry["parser_version"]
        or current["allowlist"]["official_verification_contract_digest"] != ""
        or current["allowlist"]["official_terms_evidence_digest"] != ""
        or current["source"]["review_status"]
        != models.RaceLiveReviewStatus.APPROVED
        or current["source"]["result_authority"]
        != models.RaceResultSourceAuthority.SUPPLEMENTAL
        or current["source"]["terms_status"]
        != models.RaceSourceTermsStatus.APPROVED
        or current["source"]["automation_allowed"] is not True
        or source_valid_until is None
        or _aware_datetime(
            source_valid_until,
            "source.valid_until",
        )
        <= now
        or policy_registry_digests
        != {current["source"]["registry_digest"]}
        or len(policy_coverage_digests) != 1
        or current["allowlist"]["coverage_proof_digest"]
        not in policy_coverage_digests
        or any(
            valid_until is None
            or _aware_datetime(
                valid_until,
                "policy.valid_until",
            )
            <= now
            for valid_until in policy_valid_until
        )
        or result_participant_ids != racecard_participant_ids
        or not result_participant_ids
        or len(participant_identity_rows) != len(result_participant_ids)
        or {row[0] for row in participant_identity_rows}
        != result_participant_ids
        or any(not row[1] for row in participant_identity_rows)
        or any(
            policy["mode"]
            != (
                models.RaceLivePublicationMode.SHADOW
                if policy["scope_type"]
                == models.RaceLivePublicationScopeType.EVENT
                else models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
            )
            or policy["version"] < 1
            for policy in current["policies"]
        )
    ):
        _fail(
            "promotion baseline 不符合通用 shadow contract "
            f"(unrelated_scope_digest={unrelated_scope_digest})"
        )
    route_valid_until = current["allowlist"][
        "official_verification_valid_until"
    ]
    if (
        route_valid_until is None
        or datetime.fromisoformat(route_valid_until) <= now
    ):
        _fail("event allowlist official route 已过期")
    promotion = _manifest_payload(
        approved_commit=approved_commit,
        generated_at=now,
        transition_name="promote_shadow",
        event_id=event_id,
        source_key=source_key,
        registry_digest=registry_digest,
        registry=registry,
        expected=current,
    )
    predicted_promotion = deepcopy(current)
    predicted_promotion["policies"] = [
        {
            **policy,
            "mode": (
                models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                if policy["scope_type"]
                == models.RaceLivePublicationScopeType.EVENT
                else policy["mode"]
            ),
            "version": (
                policy["version"] + 1
                if policy["scope_type"]
                == models.RaceLivePublicationScopeType.EVENT
                else policy["version"]
            ),
        }
        for policy in current["policies"]
    ]
    predicted_promotion["allowlist"] = promotion["target"]["allowlist"]
    predicted_promotion["tracking"] = promotion["target"]["tracking"]
    predicted_promotion["result_revision"]["published"] = True
    predicted_promotion["counts"] = promotion["target"]["counts"]
    predicted_promotion["event_status"] = models.RaceEventStatus.FINISHED
    disable = _manifest_payload(
        approved_commit=approved_commit,
        generated_at=now,
        transition_name="disable_public_read",
        event_id=event_id,
        source_key=source_key,
        registry_digest=registry_digest,
        registry=registry,
        expected=predicted_promotion,
    )
    predicted_disable = deepcopy(predicted_promotion)
    predicted_disable["policies"] = [
        {
            **policy,
            "mode": (
                models.RaceLivePublicationMode.SHADOW
                if policy["scope_type"]
                == models.RaceLivePublicationScopeType.EVENT
                else policy["mode"]
            ),
            "version": (
                policy["version"] + 1
                if policy["scope_type"]
                == models.RaceLivePublicationScopeType.EVENT
                else policy["version"]
            ),
        }
        for policy in predicted_promotion["policies"]
    ]
    restore = _manifest_payload(
        approved_commit=approved_commit,
        generated_at=now,
        transition_name="restore_public_read",
        event_id=event_id,
        source_key=source_key,
        registry_digest=registry_digest,
        registry=registry,
        expected=predicted_disable,
    )
    return {
        "promotion": promotion,
        "disable": disable,
        "restore": restore,
    }


def build_race_live_publication_transition_bundle(
    *,
    event_id: int,
    approved_commit: str,
    generated_at: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    already_in_transaction = connection.in_atomic_block
    with transaction.atomic():
        if connection.vendor == "postgresql" and not already_in_transaction:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
        return _build_race_live_publication_transition_bundle_snapshot(
            event_id=event_id,
            approved_commit=approved_commit,
            generated_at=generated_at,
        )


def _validate_manifest_schema(payload: dict[str, Any]) -> None:
    if set(payload) != _TOP_LEVEL_KEYS:
        _fail("transition manifest schema 不匹配")
    if payload["schema_version"] != 1:
        _fail("transition manifest schema version 不支持")
    if payload["transition"] not in _TRANSITIONS:
        _fail("transition 类型不支持")
    if _COMMIT_RE.fullmatch(str(payload["approved_commit"])) is None:
        _fail("approved_commit 不合法")
    _aware_datetime(payload["generated_at"], "generated_at")
    if (
        isinstance(payload["event_id"], bool)
        or not isinstance(payload["event_id"], int)
        or payload["event_id"] <= 0
    ):
        _fail("event_id 必须是正整数")
    if payload["source_key"] != "the_racing_api":
        _fail("source_key 不在本次范围")
    for key in (
        "route_registry_digest",
        "route_contract_digest",
        "route_terms_digest",
        "unrelated_scope_digest",
    ):
        if _SHA256_RE.fullmatch(str(payload[key])) is None:
            _fail(f"{key} 不合法")
    if not isinstance(payload["expected"], dict) or not isinstance(
        payload["target"], dict
    ):
        _fail("expected/target 必须是 object")
    expected = payload["expected"]
    if set(expected) != _EXPECTED_KEYS:
        _fail("expected schema 不匹配")
    if isinstance(expected["event"], dict) and isinstance(
        expected["event"].get("race_datetime"), str
    ):
        _aware_datetime(
            expected["event"]["race_datetime"],
            "expected.event.race_datetime",
        )
    if (
        not isinstance(expected["event"], dict)
        or set(expected["event"])
        != {"id", "slug", "year", "country_region", "race_datetime"}
        or expected["event"]["id"] != payload["event_id"]
        or not isinstance(expected["event"]["slug"], str)
        or not expected["event"]["slug"]
        or isinstance(expected["event"]["year"], bool)
        or not isinstance(expected["event"]["year"], int)
        or expected["event"]["country_region"]
        not in {
            models.RacingRegion.UNITED_KINGDOM,
            models.RacingRegion.FRANCE,
            models.RacingRegion.HONG_KONG,
            models.RacingRegion.JAPAN,
            models.RacingRegion.UNITED_STATES,
        }
        or not isinstance(expected["event"]["race_datetime"], str)
        or not isinstance(expected["manual_locks"], dict)
        or set(expected["manual_locks"]) != {"results", "runners"}
        or any(
            not isinstance(expected["manual_locks"][key], bool)
            for key in ("results", "runners")
        )
        or not isinstance(expected["source"], dict)
        or set(expected["source"])
        != {
            "id",
            "external_race_id",
            "review_status",
            "result_authority",
            "terms_status",
            "automation_allowed",
            "valid_until",
            "registry_digest",
        }
        or not isinstance(expected["tracking"], dict)
        or set(expected["tracking"]) != _TRACKING_KEYS
        or not isinstance(expected["observation"], dict)
        or set(expected["observation"])
        != {"id", "parser_version", "phase", "normalized_sha256"}
        or not isinstance(expected["result_revision"], dict)
        or set(expected["result_revision"])
        != {
            "id",
            "revision_no",
            "phase",
            "content_sha256",
            "published",
            "participant_count",
        }
        or not isinstance(expected["racecard_revision"], dict)
        or set(expected["racecard_revision"])
        != {"id", "content_sha256", "item_digest"}
        or not isinstance(expected["allowlist"], dict)
        or set(expected["allowlist"]) != _ALLOWLIST_KEYS
        or not isinstance(expected["event_universes"], dict)
        or set(expected["event_universes"])
        != {"tracking_event_ids", "allowlist_event_ids"}
        or not isinstance(expected["counts"], dict)
        or set(expected["counts"])
        != {"publication", "legacy_result", "incident"}
        or not isinstance(expected["policies"], list)
        or len(expected["policies"]) != 4
        or any(
            not isinstance(policy, dict) or set(policy) != _POLICY_KEYS
            for policy in expected["policies"]
        )
    ):
        _fail("expected nested schema 不匹配")
    policy_scopes = [
        (policy["scope_type"], policy["scope_key"])
        for policy in expected["policies"]
    ]
    if len(set(policy_scopes)) != 4 or set(policy_scopes) != {
        (models.RaceLivePublicationScopeType.GLOBAL, "global"),
        (
            models.RaceLivePublicationScopeType.REGION,
            expected["event"]["country_region"],
        ),
        (
            models.RaceLivePublicationScopeType.SOURCE,
            "the_racing_api",
        ),
        (
            models.RaceLivePublicationScopeType.EVENT,
            str(payload["event_id"]),
        ),
    }:
        _fail("expected policy scope 不匹配或重复")
    sha_values = (
        expected["owner_manifest_sha256"],
        expected["source"]["registry_digest"],
        expected["observation"]["normalized_sha256"],
        expected["result_revision"]["content_sha256"],
        expected["racecard_revision"]["content_sha256"],
        expected["racecard_revision"]["item_digest"],
        expected["participant_digest"],
        expected["participant_identity_digest"],
        expected["allowlist"]["coverage_proof_digest"],
        *(
            value
            for policy in expected["policies"]
            for value in (
                policy["registry_digest"],
                policy["coverage_proof_digest"],
            )
        ),
    )
    if any(_SHA256_RE.fullmatch(str(value)) is None for value in sha_values):
        _fail("expected digest 不合法")
    predicted_target = _predict_target(
        expected,
        transition_name=payload["transition"],
        contract_digest=payload["route_contract_digest"],
        terms_digest=payload["route_terms_digest"],
    )
    if payload["target"] != predicted_target:
        _fail("target 不是 expected 的唯一合法 CAS 投影")


def load_race_live_publication_transition_manifest(
    *,
    manifest_path: str | os.PathLike[str],
    expected_manifest_sha256: str,
    expected_approved_commit: str,
) -> LoadedRaceLivePublicationTransition:
    if _SHA256_RE.fullmatch(str(expected_manifest_sha256)) is None:
        _fail("expected manifest SHA-256 不合法")
    if _COMMIT_RE.fullmatch(str(expected_approved_commit)) is None:
        _fail("expected approved commit 不合法")
    path, data = _read_safe_file(manifest_path)
    actual_sha = hashlib.sha256(data).hexdigest()
    if actual_sha != expected_manifest_sha256:
        _fail("manifest SHA-256 不匹配")
    payload = _parse_json(data, "transition manifest")
    _validate_manifest_schema(payload)
    if payload["approved_commit"] != expected_approved_commit:
        _fail("approved commit 不匹配")
    registry, registry_digest = read_manual_official_route_registry(
        route=payload["expected"]["allowlist"][
            "official_verification_route"
        ]
    )
    if (
        payload["route_registry_digest"] != registry_digest
        or payload["route_contract_digest"] != registry["contract_digest"]
        or payload["route_terms_digest"]
        != registry["terms_evidence"]["sha256"]
    ):
        _fail("manual official route registry 发生漂移")
    return LoadedRaceLivePublicationTransition(
        path=path,
        sha256=actual_sha,
        payload=payload,
    )


def _summary(
    manifest: LoadedRaceLivePublicationTransition,
    *,
    mode: str,
    replayed: bool = False,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": not errors,
        "mode": mode,
        "transition": manifest.payload["transition"],
        "manifest_sha256": manifest.sha256,
        "approved_commit": manifest.payload["approved_commit"],
        "event_ids": [manifest.payload["event_id"]],
        "network_request_count": 0,
        "replayed": replayed,
        "errors": errors or [],
    }


def _validate_exact_pre(
    manifest: LoadedRaceLivePublicationTransition,
) -> None:
    payload = manifest.payload
    current = _with_participant_count(
        _current_snapshot(payload["event_id"], payload["source_key"]),
        payload["event_id"],
    )
    if current != payload["expected"]:
        _fail("transition exact pre-state 漂移")
    if (
        _unrelated_scope_digest(event_id=payload["event_id"])
        != payload["unrelated_scope_digest"]
    ):
        _fail("transition unrelated scope 漂移")
    unrelated_scope_digest = _sha256(
        {
            "tracking_event_ids": [
                value
                for value in current["event_universes"][
                    "tracking_event_ids"
                ]
                if value != payload["event_id"]
            ],
            "allowlist_event_ids": [
                value
                for value in current["event_universes"][
                    "allowlist_event_ids"
                ]
                if value != payload["event_id"]
            ],
        }
    )
    if payload["transition"] == "promote_shadow":
        effective_now = timezone.now()
        source_valid_until = current["source"]["valid_until"]
        allowlist_valid_until = current["allowlist"][
            "official_verification_valid_until"
        ]
        policy_valid_until = [
            policy["valid_until"] for policy in current["policies"]
        ]
        policy_registry_digests = {
            policy["registry_digest"] for policy in current["policies"]
        }
        policy_coverage_digests = {
            policy["coverage_proof_digest"] for policy in current["policies"]
        }
        result_participant_ids = set(
            models.RaceEventRevisionItem.objects.filter(
                revision_id=current["result_revision"]["id"]
            ).values_list("participant_id", flat=True)
        )
        racecard_participant_ids = set(
            models.RaceEventRevisionItem.objects.filter(
                revision_id=current["racecard_revision"]["id"]
            ).values_list("participant_id", flat=True)
        )
        participant_identity_rows = list(
            models.RaceEventParticipantSourceIdentity.objects.filter(
                source_identity_id=current["source"]["id"],
                participant_id__in=result_participant_ids,
            ).values_list("participant_id", "external_runner_id")
        )
        if (
            current["event"]["id"] != payload["event_id"]
            or current["event"]["race_datetime"] is None
            or current["event_status"]
            not in {
                models.RaceEventStatus.SCHEDULED,
                models.RaceEventStatus.RUNNING,
                models.RaceEventStatus.FINISHED,
            }
            or current["manual_locks"]
            != {"results": False, "runners": False}
            or current["write_owner"]
            != models.RaceEventProjectionWriteOwner.LIVE
            or current["tracking"]["state"]
            != models.RaceEventLiveState.PROVISIONAL_RESULT
            or current["tracking"]["tracking_enabled"] is not True
            or current["tracking"]["active_attempt_token"] != ""
            or current["tracking"]["claim_expires_at"] is not None
            or current["result_revision"]["published"] is not False
            or current["counts"]
            != {"publication": 0, "legacy_result": 0, "incident": 0}
            or current["source"]["review_status"]
            != models.RaceLiveReviewStatus.APPROVED
            or current["source"]["result_authority"]
            != models.RaceResultSourceAuthority.SUPPLEMENTAL
            or current["source"]["terms_status"]
            != models.RaceSourceTermsStatus.APPROVED
            or current["source"]["automation_allowed"] is not True
            or source_valid_until is None
            or _aware_datetime(
                source_valid_until,
                "source.valid_until",
            )
            <= effective_now
            or policy_registry_digests
            != {current["source"]["registry_digest"]}
            or len(policy_coverage_digests) != 1
            or current["allowlist"]["coverage_proof_digest"]
            not in policy_coverage_digests
            or any(
                valid_until is None
                or _aware_datetime(
                    valid_until,
                    "policy.valid_until",
                )
                <= effective_now
                for valid_until in policy_valid_until
            )
            or current["allowlist"]["enabled"] is not True
            or current["allowlist"]["max_mode"]
            != models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
            or current["allowlist"]["version"] != 1
            or current["allowlist"][
                "official_verification_contract_digest"
            ]
            != ""
            or current["allowlist"]["official_terms_evidence_digest"] != ""
            or current["allowlist"]["official_verification_route"]
            != payload["expected"]["allowlist"][
                "official_verification_route"
            ]
            or current["allowlist"][
                "official_verification_route_version"
            ]
            != payload["expected"]["allowlist"][
                "official_verification_route_version"
            ]
            or allowlist_valid_until is None
            or _aware_datetime(
                allowlist_valid_until,
                "allowlist.official_verification_valid_until",
            )
            <= effective_now
            or result_participant_ids != racecard_participant_ids
            or not result_participant_ids
            or len(participant_identity_rows)
            != len(result_participant_ids)
            or {row[0] for row in participant_identity_rows}
            != result_participant_ids
            or any(not row[1] for row in participant_identity_rows)
            or any(
                policy["mode"]
                != (
                    models.RaceLivePublicationMode.SHADOW
                    if policy["scope_type"]
                    == models.RaceLivePublicationScopeType.EVENT
                    else models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                )
                or policy["version"] < 1
                for policy in current["policies"]
            )
        ):
            _fail(
                "promotion exact pre-state 不符合 shadow contract "
                f"(unrelated_scope_digest={unrelated_scope_digest})"
            )


def _expected_post_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    expected_post = deepcopy(payload["expected"])
    target = payload["target"]
    target_policy_by_scope = {
        (row["scope_type"], row["scope_key"]): row
        for row in target["policies"]
    }
    for policy in expected_post["policies"]:
        target_policy = target_policy_by_scope[
            (policy["scope_type"], policy["scope_key"])
        ]
        policy["mode"] = target_policy["mode"]
        policy["version"] = target_policy["version"]
    expected_post["allowlist"] = target["allowlist"]
    expected_post["tracking"] = target["tracking"]
    expected_post["result_revision"]["published"] = target[
        "result_revision_published"
    ]
    expected_post["counts"] = target["counts"]
    expected_post["event_status"] = target["event_status"]
    expected_post["result_confirmed"] = target["result_confirmed"]
    return expected_post


def _post_errors(
    manifest: LoadedRaceLivePublicationTransition,
) -> list[str]:
    payload = manifest.payload
    current = _with_participant_count(
        _current_snapshot(payload["event_id"], payload["source_key"]),
        payload["event_id"],
    )
    target = payload["target"]
    current_policy_targets = [
        {
            "scope_type": policy["scope_type"],
            "scope_key": policy["scope_key"],
            "mode": policy["mode"],
            "version": policy["version"],
        }
        for policy in current["policies"]
    ]
    errors: list[str] = []
    comparisons = (
        ("policies", current_policy_targets, target["policies"]),
        ("allowlist", current["allowlist"], target["allowlist"]),
        ("tracking", current["tracking"], target["tracking"]),
        (
            "result_revision_published",
            current["result_revision"]["published"],
            target["result_revision_published"],
        ),
        ("counts", current["counts"], target["counts"]),
        ("event_status", current["event_status"], target["event_status"]),
        (
            "result_confirmed",
            current["result_confirmed"],
            target["result_confirmed"],
        ),
    )
    for label, actual, expected in comparisons:
        if actual != expected:
            errors.append(f"{label}_mismatch")
    if current != _expected_post_snapshot(payload):
        errors.append("exact_post_state_mismatch")
    if (
        _unrelated_scope_digest(event_id=payload["event_id"])
        != payload["unrelated_scope_digest"]
    ):
        errors.append("unrelated_scope_mismatch")
    if target["counts"]["publication"] == 1:
        incident = models.RaceLiveOfficialVerificationIncident.objects.filter(
            event_id=payload["event_id"],
            provisional_revision_id=payload["expected"]["result_revision"]["id"],
        ).first()
        publication = models.RaceEventRevisionPublication.objects.filter(
            revision_id=payload["expected"]["result_revision"]["id"],
        ).first()
        revision = models.RaceEventRevision.objects.filter(
            pk=payload["expected"]["result_revision"]["id"],
        ).first()
        tracking = models.RaceEventLiveTracking.objects.filter(
            event_id=payload["event_id"],
        ).first()
        if (
            incident is None
            or incident.official_route_contract_digest
            != payload["route_contract_digest"]
            or incident.official_terms_evidence_digest
            != payload["route_terms_digest"]
            or incident.manual_verification_due_at is None
        ):
            errors.append("official_incident_contract_mismatch")
        if (
            incident is None
            or publication is None
            or revision is None
            or tracking is None
            or revision.published_at is None
            or publication.published_at != revision.published_at
            or incident.opened_at != revision.published_at
            or tracking.provisional_published_at != revision.published_at
            or incident.manual_verification_due_at
            != revision.published_at + timedelta(minutes=15)
        ):
            errors.append("publication_timeline_mismatch")
    return errors


def dry_run_race_live_publication_transition(
    manifest: LoadedRaceLivePublicationTransition,
) -> dict[str, Any]:
    if (
        manifest.payload["transition"] == "promote_shadow"
        and settings.RACE_LIVE_SCHEDULER_ENABLED is not False
    ):
        _fail("scheduler 必须保持 false")
    _validate_exact_pre(manifest)
    return _summary(manifest, mode="dry_run")


def apply_race_live_publication_transition(
    manifest: LoadedRaceLivePublicationTransition,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    effective_now = now or timezone.now()
    if timezone.is_naive(effective_now):
        _fail("apply time 必须包含时区")
    payload = manifest.payload
    event_id = payload["event_id"]
    with transaction.atomic():
        # Global lock order is intentionally control -> tracking -> event.
        try:
            control = (
                models.RaceEventProjectionControl.objects.select_for_update(
                    of=("self",)
                ).get(event_id=event_id)
            )
            tracking = models.RaceEventLiveTracking.objects.select_for_update().get(
                event_id=event_id
            )
            models.RaceEvent.objects.select_for_update().get(pk=event_id)
        except (
            models.RaceEventProjectionControl.DoesNotExist,
            models.RaceEventLiveTracking.DoesNotExist,
            models.RaceEvent.DoesNotExist,
        ) as exc:
            raise RaceLivePublicationTransitionError(
                "transition lock baseline 缺失"
            ) from exc
        # Complete the shared lock order before touching policy rows:
        # control -> tracking -> event -> source/observation/revision/items ->
        # participants/source identities -> policy/allowlist.
        try:
            models.RaceResultSourceIdentity.objects.select_for_update().get(
                pk=payload["expected"]["source"]["id"],
                event_id=event_id,
                source_key=payload["source_key"],
            )
            models.RaceResultObservation.objects.select_for_update().get(
                pk=payload["expected"]["observation"]["id"],
                source_identity_id=payload["expected"]["source"]["id"],
            )
            models.RaceEventRevision.objects.select_for_update().get(
                pk=payload["expected"]["racecard_revision"]["id"],
                event_id=event_id,
            )
            models.RaceEventRevision.objects.select_for_update().get(
                pk=payload["expected"]["result_revision"]["id"],
                event_id=event_id,
            )
            locked_revision_items = list(
                models.RaceEventRevisionItem.objects.select_for_update().filter(
                    revision_id__in=(
                        payload["expected"]["racecard_revision"]["id"],
                        payload["expected"]["result_revision"]["id"],
                    )
                ).order_by("revision_id", "internal_order", "pk")
            )
        except (
            models.RaceResultSourceIdentity.DoesNotExist,
            models.RaceResultObservation.DoesNotExist,
            models.RaceEventRevision.DoesNotExist,
        ) as exc:
            raise RaceLivePublicationTransitionError(
                "transition revision baseline 缺失"
            ) from exc

        participant_ids = {
            item.participant_id for item in locked_revision_items
        }
        list(
            models.RaceEventParticipant.objects.select_for_update()
            .filter(pk__in=participant_ids, event_id=event_id)
            .order_by("pk")
        )
        list(
            models.RaceEventParticipantSourceIdentity.objects.select_for_update()
            .filter(
                participant_id__in=participant_ids,
                source_identity_id=payload["expected"]["source"]["id"],
            )
            .order_by("participant_id", "pk")
        )

        policy_filter = Q()
        for expected_policy in payload["expected"]["policies"]:
            policy_filter |= Q(
                scope_type=expected_policy["scope_type"],
                scope_key=expected_policy["scope_key"],
            )
        locked_policies = list(
            models.RaceLivePublicationPolicy.objects.select_for_update()
            .filter(policy_filter)
            .order_by("scope_type", "scope_key")
        )
        if len(locked_policies) != 4:
            _fail("target policy 缺失或重复")
        policy_by_scope = {
            (row.scope_type, row.scope_key): row
            for row in locked_policies
        }
        try:
            locked_allowlist = (
                models.RaceLiveEventPublicationAllowlist.objects.select_for_update()
                .get(event_id=event_id, source_key=payload["source_key"])
            )
        except models.RaceLiveEventPublicationAllowlist.DoesNotExist as exc:
            raise RaceLivePublicationTransitionError(
                "target allowlist 缺失"
            ) from exc

        existing_log = models.OperationLog.objects.filter(
            action_type="race_live_publication_transition",
            target_type="race_event",
            target_id=str(event_id),
            detail__contains=manifest.sha256,
        ).first()
        post_errors = _post_errors(manifest)
        if existing_log is not None and not post_errors:
            return _summary(manifest, mode="apply", replayed=True)
        _validate_exact_pre(manifest)
        if (
            payload["transition"] == "promote_shadow"
            and settings.RACE_LIVE_SCHEDULER_ENABLED is not False
        ):
            _fail("scheduler 必须保持 false")
        if (
            payload["transition"] == "promote_shadow"
            and (
                tracking.active_attempt_token != ""
                or tracking.claim_expires_at is not None
            )
        ):
            _fail("operator transition 遇到 active claim")

        expected_policy_by_scope = {
            (row["scope_type"], row["scope_key"]): row
            for row in payload["expected"]["policies"]
        }
        for target in payload["target"]["policies"]:
            scope = (target["scope_type"], target["scope_key"])
            row = policy_by_scope.get(scope)
            if row is None:
                _fail("target policy 缺失")
            expected_policy = expected_policy_by_scope[scope]
            if (
                row.mode != expected_policy["mode"]
                or row.version != expected_policy["version"]
                or row.registry_digest
                != expected_policy["registry_digest"]
                or row.coverage_proof_digest
                != expected_policy["coverage_proof_digest"]
                or _dt(row.valid_until) != expected_policy["valid_until"]
            ):
                _fail("target policy CAS 漂移")
            if row.version != target["version"] or row.mode != target["mode"]:
                row.mode = target["mode"]
                row.version = target["version"]
                row.save(update_fields=("mode", "version", "updated_at"))

        if payload["transition"] == "promote_shadow":
            target_allowlist = payload["target"]["allowlist"]
            locked_allowlist.version = target_allowlist["version"]
            locked_allowlist.official_verification_contract_digest = payload[
                "route_contract_digest"
            ]
            locked_allowlist.official_terms_evidence_digest = payload[
                "route_terms_digest"
            ]
            locked_allowlist.save(
                update_fields=(
                    "version",
                    "official_verification_contract_digest",
                    "official_terms_evidence_digest",
                    "updated_at",
                )
            )
            decision = admit_persisted_race_live_publication(
                observation_id=payload["expected"]["observation"]["id"],
                expected_owner_generation=control.owner_generation,
                now=effective_now,
            )
            if decision.applied is not True:
                _fail(f"publication admission 失败：{decision.reason}")
            tracking.refresh_from_db()
            tracking.tracking_enabled = False
            tracking.next_poll_at = None
            tracking.save(
                update_fields=("tracking_enabled", "next_poll_at", "updated_at")
            )

        models.OperationLog.objects.create(
            action_type="race_live_publication_transition",
            target_type="race_event",
            target_id=str(event_id),
            detail=json.dumps(
                {
                    "approved_commit": payload["approved_commit"],
                    "manifest_sha256": manifest.sha256,
                    "transition": payload["transition"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        errors = _post_errors(manifest)
        if errors:
            _fail("apply 后 verify 失败：" + ",".join(errors))
    return _summary(manifest, mode="apply")


def verify_race_live_publication_transition(
    manifest: LoadedRaceLivePublicationTransition,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    effective_now = now or timezone.now()
    if timezone.is_naive(effective_now):
        _fail("verify time 必须包含时区")
    errors = _post_errors(manifest)
    if manifest.payload["transition"] in {
        "promote_shadow",
        "restore_public_read",
    }:
        decision = resolve_race_live_public_read(
            event_id=manifest.payload["event_id"],
            now=effective_now,
        )
        if decision.visible is not True:
            errors.append(f"public_read_hidden:{decision.reason}")
    elif manifest.payload["transition"] == "disable_public_read":
        decision = resolve_race_live_public_read(
            event_id=manifest.payload["event_id"],
            now=effective_now,
        )
        if decision.visible is not False:
            errors.append("public_read_not_hidden")
    summary = _summary(manifest, mode="verify", errors=errors)
    if manifest.payload["transition"] == "promote_shadow":
        incident = models.RaceLiveOfficialVerificationIncident.objects.filter(
            event_id=manifest.payload["event_id"],
            provisional_revision_id=manifest.payload["expected"][
                "result_revision"
            ]["id"],
        ).first()
        summary["official_incident_status"] = (
            incident.status if incident is not None else "missing"
        )
        summary["official_incident_overdue"] = bool(
            incident is not None
            and incident.status
            == models.RaceLiveOfficialVerificationIncidentStatus.OPEN
            and incident.deadline_at <= effective_now
        )
    return summary


def _validate_output_root(path_value: str | os.PathLike[str]) -> Path:
    root = Path(path_value)
    if not root.is_absolute():
        _fail("artifact root 必须是绝对路径")
    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise RaceLivePublicationTransitionError(
            "artifact root 必须已存在"
        ) from exc
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        _fail("artifact root 必须是真实目录")
    if stat.S_IMODE(root_stat.st_mode) & 0o077:
        _fail("artifact root 必须为 0700")
    current = root.parent
    macos_var_alias_allowed = Path("/var").is_symlink()
    while current != current.parent:
        if stat.S_ISLNK(current.lstat().st_mode) and not (
            macos_var_alias_allowed and current == Path("/var")
        ):
            _fail("artifact root ancestor 不得是 symlink")
        current = current.parent
    return root


def _exclusive_write(path: Path, payload: Any) -> str:
    data = _canonical_bytes(payload) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)
    return hashlib.sha256(data).hexdigest()


def prepare_race_live_publication_transition_bundle(
    *,
    event_id: int,
    approved_commit: str,
    run_id: str,
    output_root: str | os.PathLike[str] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        _fail("run_id 不合法")
    root = _validate_output_root(
        output_root or settings.RACE_LIVE_PUBLICATION_ARTIFACT_ROOT
    )
    final_dir = root / run_id
    temporary_dir = root / f".{run_id}.tmp"
    if final_dir.exists() or temporary_dir.exists():
        _fail("run_id 已存在，禁止覆盖")
    os.mkdir(temporary_dir, 0o700)
    try:
        bundle = build_race_live_publication_transition_bundle(
            event_id=event_id,
            approved_commit=approved_commit,
            generated_at=generated_at,
        )
        sha_rows: dict[str, str] = {}
        for name, payload in bundle.items():
            filename = f"{name}.manifest.json"
            sha_rows[filename] = _exclusive_write(
                temporary_dir / filename,
                payload,
            )
        report = {
            "approved_commit": approved_commit,
            "event_ids": [event_id],
            "network_request_count": 0,
            "run_id": run_id,
            "transitions": ["promotion", "disable", "restore"],
        }
        sha_rows["report.json"] = _exclusive_write(
            temporary_dir / "report.json",
            report,
        )
        _exclusive_write(temporary_dir / "sha256s.json", sha_rows)
        os.chmod(temporary_dir, 0o700)
        os.rename(temporary_dir, final_dir)
    except Exception:
        if temporary_dir.exists():
            for child in temporary_dir.iterdir():
                child.unlink()
            temporary_dir.rmdir()
        raise
    return {
        "ok": True,
        "event_ids": [event_id],
        "output_dir": str(final_dir),
        "file_count": 5,
        "network_request_count": 0,
    }

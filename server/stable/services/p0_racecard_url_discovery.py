"""Fail-closed discovery of official P0 racecard page URLs.

The tracked provider registry is intentionally network-disabled.  Provider
transport may only be enabled by a separately reviewed registry contract.
"""

from __future__ import annotations

import fcntl
import hashlib
import html
import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import stat
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from billiard.exceptions import SoftTimeLimitExceeded


SCHEMA_VERSION = 1
MAX_TARGETS_DEFAULT = 500
MAX_URL_LENGTH = 2048
MAX_RESPONSE_BYTES_DEFAULT = 1_000_000
SCHEDULE_TIMEZONE = "Asia/Shanghai"
IDENTITY_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")


class DiscoveryInvariantError(RuntimeError):
    pass


class TargetLimitExceeded(DiscoveryInvariantError):
    pass


class RoutePolicyError(DiscoveryInvariantError):
    pass


class ArtifactSafetyError(DiscoveryInvariantError):
    pass


class StaleRunError(DiscoveryInvariantError):
    pass


class PublishLockBusyError(DiscoveryInvariantError):
    pass


class DiscoveryOutcome(str, Enum):
    FOUND = "found"
    LISTING_REACHABLE = "listing_reachable"
    NOT_PUBLISHED = "not_published"
    CANDIDATE_UNVERIFIED = "candidate_unverified"
    IDENTITY_MISSING = "identity_missing"
    ADAPTER_DISABLED = "adapter_disabled"
    POLICY_BLOCKED = "policy_blocked"
    IDENTITY_CONFLICT = "identity_conflict"
    DUPLICATE_MATCH = "duplicate_match"
    PATH_UNVERIFIED = "path_unverified"
    SOURCE_ERROR = "source_error"


ERROR_OUTCOMES = frozenset(
    {
        DiscoveryOutcome.SOURCE_ERROR,
        DiscoveryOutcome.PATH_UNVERIFIED,
        DiscoveryOutcome.IDENTITY_CONFLICT,
        DiscoveryOutcome.DUPLICATE_MATCH,
    }
)


@dataclass(frozen=True)
class EventSnapshot:
    event_id: int
    year: int
    slug: str
    series_key: str
    original_name: str
    name_zh: str
    country_region: str
    racecourse: str
    race_datetime: datetime | None
    timezone_name: str
    local_date: date | None
    priority: str
    status: str
    visibility_status: str
    data_quality_status: str
    is_featured: bool
    series_review_status: str
    source_refs: Mapping[str, Any]
    inclusion_basis: str = "race_datetime"

    @classmethod
    def from_event(
        cls, event: Any, *, inclusion_basis: str = "race_datetime"
    ) -> "EventSnapshot":
        return cls(
            event_id=int(event.id),
            year=int(event.year),
            slug=str(event.slug),
            series_key=str(event.series_key),
            original_name=str(event.original_name),
            name_zh=str(event.chinese_name),
            country_region=str(event.country_region),
            racecourse=str(event.racecourse),
            race_datetime=event.race_datetime,
            timezone_name=str(event.timezone_name),
            local_date=event.local_date,
            priority=str(event.priority),
            status=str(event.status),
            visibility_status=str(event.visibility_status),
            data_quality_status=str(
                getattr(event, "data_quality_status", "")
            ),
            is_featured=bool(getattr(event, "is_featured", False)),
            series_review_status=str(
                getattr(
                    getattr(event, "race_series", None),
                    "review_status",
                    "",
                )
            ),
            source_refs=(
                dict(event.source_refs)
                if isinstance(event.source_refs, Mapping)
                else {}
            ),
            inclusion_basis=inclusion_basis,
        )


@dataclass(frozen=True)
class TargetInventory:
    future: tuple[EventSnapshot, ...]
    orphans: tuple[EventSnapshot, ...]
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True)
class DiscoveryResult:
    outcome: DiscoveryOutcome
    checked_at: str
    provider: str
    provider_contract_version: str
    reason: str
    url: str | None = None
    provider_event_id: str = ""
    verification_method: str = ""
    verification_scope: str = ""
    source_url: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, DiscoveryOutcome):
            raise ValueError("unknown discovery outcome")
        if self.reason != self.outcome.value:
            raise ValueError("reason must be the fixed outcome code")
        url_outcomes = {
            DiscoveryOutcome.FOUND,
            DiscoveryOutcome.LISTING_REACHABLE,
        }
        if self.outcome in url_outcomes and not self.url:
            raise ValueError("URL outcome requires a URL")
        if self.outcome not in url_outcomes and self.url is not None:
            raise ValueError("non-found outcome cannot introduce a URL")


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    final_url: str
    body: bytes


@dataclass(frozen=True)
class PublishedGeneration:
    generation_id: str
    path: Path
    canonical_payload_sha256: str
    markdown_sha256: str
    json_sha256: str
    payload: dict[str, Any]


def _iso(value: datetime) -> str:
    return value.isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DiscoveryInvariantError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _local_day_intersects_window(
    local_day: date,
    timezone_name: str,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DiscoveryInvariantError("invalid timezone_name") from exc
    day_start = datetime.combine(local_day, datetime.min.time(), tzinfo=zone)
    day_end = datetime.combine(
        local_day + timedelta(days=1), datetime.min.time(), tzinfo=zone
    )
    return _as_utc(day_start) < window_end and _as_utc(day_end) > window_start


def enumerate_event_snapshots(
    events: Iterable[Any],
    *,
    run_started_at: datetime,
    max_targets: int = MAX_TARGETS_DEFAULT,
) -> TargetInventory:
    """Enumerate the complete P0 target set without silently truncating."""
    start = _as_utc(run_started_at)
    end = start + timedelta(days=7)
    years = {
        start.year,
        (end - timedelta(microseconds=1)).year,
    }
    future: list[EventSnapshot] = []
    orphans: list[EventSnapshot] = []
    for event in events:
        if str(event.priority) != "P0" or str(event.status) == "cancelled":
            continue
        if event.race_datetime is not None:
            moment = _as_utc(event.race_datetime)
            if start <= moment < end:
                future.append(EventSnapshot.from_event(event))
                if len(future) + len(orphans) > max_targets:
                    raise TargetLimitExceeded("target_limit_exceeded")
            continue
        if event.local_date is not None and str(event.timezone_name):
            if _local_day_intersects_window(
                event.local_date, str(event.timezone_name), start, end
            ):
                future.append(
                    EventSnapshot.from_event(
                        event, inclusion_basis="local_date_superset"
                    )
                )
                if len(future) + len(orphans) > max_targets:
                    raise TargetLimitExceeded("target_limit_exceeded")
            continue
        if (
            int(event.year) in years
            and str(event.status) in {"scheduled", "postponed"}
        ):
            orphans.append(
                EventSnapshot.from_event(
                    event, inclusion_basis="time_identity_missing"
                )
            )
        if len(future) + len(orphans) > max_targets:
            raise TargetLimitExceeded("target_limit_exceeded")
    key = lambda row: (
        row.local_date is None,
        row.local_date or date.max,
        row.country_region,
        row.event_id,
    )
    return TargetInventory(
        future=tuple(sorted(future, key=key)),
        orphans=tuple(sorted(orphans, key=key)),
        window_start=start,
        window_end=end,
    )


def merge_discovery_state(
    previous: Mapping[str, Any] | None,
    result: DiscoveryResult,
) -> dict[str, Any]:
    previous = dict(previous or {})
    previous_url = previous.get("url")
    had_confirmed = bool(previous_url) and previous.get(
        "persisted_status"
    ) in {
        "confirmed",
        "listing_reachable",
        "previous_url_unverified",
    }
    checked_provenance = {
        "checked_provider": result.provider,
        "checked_provider_event_id": result.provider_event_id,
        "checked_provider_contract_version": (
            result.provider_contract_version
        ),
        "checked_verification_method": result.verification_method,
        "checked_verification_scope": result.verification_scope,
        "checked_source_url": result.source_url,
    }
    result_provenance = {
        "provider": result.provider,
        "provider_event_id": result.provider_event_id,
        "provider_contract_version": result.provider_contract_version,
        "verification_method": result.verification_method,
        "verification_scope": result.verification_scope,
        "source_url": result.source_url,
    }
    if result.outcome is DiscoveryOutcome.FOUND:
        return {
            **result_provenance,
            **checked_provenance,
            "discovery_outcome": result.outcome.value,
            "persisted_status": "confirmed",
            "url": result.url,
            "last_confirmed_at": result.checked_at,
            "last_checked_at": result.checked_at,
            "reason": result.reason,
        }
    if result.outcome is DiscoveryOutcome.LISTING_REACHABLE:
        return {
            **result_provenance,
            **checked_provenance,
            "discovery_outcome": result.outcome.value,
            "persisted_status": "listing_reachable",
            "url": result.url,
            "last_confirmed_at": None,
            "last_checked_at": result.checked_at,
            "reason": result.reason,
        }
    if had_confirmed:
        return {
            "provider": str(previous.get("provider", "")),
            "provider_event_id": str(
                previous.get("provider_event_id", "")
            ),
            "provider_contract_version": str(
                previous.get("provider_contract_version", "")
            ),
            "verification_method": str(
                previous.get("verification_method", "")
            ),
            "verification_scope": str(
                previous.get("verification_scope", "")
            ),
            "source_url": str(previous.get("source_url", "")),
            **checked_provenance,
            "discovery_outcome": result.outcome.value,
            "persisted_status": "previous_url_unverified",
            "url": previous_url,
            "last_confirmed_at": previous.get("last_confirmed_at"),
            "last_checked_at": result.checked_at,
            "reason": result.reason,
        }
    return {
        **result_provenance,
        **checked_provenance,
        "discovery_outcome": result.outcome.value,
        "persisted_status": (
            "error_without_previous"
            if result.outcome in ERROR_OUTCOMES
            else "not_available"
        ),
        "url": None,
        "last_confirmed_at": None,
        "last_checked_at": result.checked_at,
        "reason": result.reason,
    }


def load_route_registry(
    path: str | os.PathLike[str], *, expected_sha256: str = ""
) -> list[dict[str, Any]]:
    registry_path = Path(path)
    registry_bytes = registry_path.read_bytes()
    if expected_sha256 and _sha256(registry_bytes) != expected_sha256:
        raise RoutePolicyError("registry_sha_mismatch")
    payload = json.loads(registry_bytes.decode("utf-8"))
    if payload.get("schema_version") != 1:
        raise RoutePolicyError("registry_schema_invalid")
    routes = payload.get("routes")
    if not isinstance(routes, list):
        raise RoutePolicyError("registry_routes_invalid")
    required = {
        "provider",
        "region",
        "source_namespace",
        "allowed_hosts",
        "allowed_path_prefixes",
        "automation_allowed",
        "access_mode",
        "robots_allowed",
        "contract_version",
        "valid_until",
        "identity_fields",
    }
    validated: list[dict[str, Any]] = []
    for raw in routes:
        if not isinstance(raw, dict) or not required.issubset(raw):
            raise RoutePolicyError("registry_route_invalid")
        route = dict(raw)
        if (
            not isinstance(route["automation_allowed"], bool)
            or not isinstance(route["robots_allowed"], bool)
            or not re.fullmatch(
                r"[a-z0-9_-]{1,64}", str(route["provider"])
            )
            or not re.fullmatch(
                r"[a-z0-9_-]{1,64}", str(route["region"])
            )
            or not re.fullmatch(
                r"[a-z0-9_-]{1,64}", str(route["source_namespace"])
            )
            or not re.fullmatch(
                r"[A-Za-z0-9_.:-]{1,128}",
                str(route["contract_version"]),
            )
        ):
            raise RoutePolicyError("registry_route_invalid")
        _parse_contract_expiry(str(route["valid_until"]))
        hosts = route["allowed_hosts"]
        paths = route["allowed_path_prefixes"]
        identity_fields = route["identity_fields"]
        if (
            not isinstance(hosts, list)
            or not hosts
            or any(
                not re.fullmatch(
                    r"[A-Za-z0-9.-]{1,253}", str(host)
                )
                for host in hosts
            )
            or not isinstance(paths, list)
            or not paths
            or any(
                not str(path).startswith("/")
                or ".." in Path(str(path)).parts
                or "?" in str(path)
                or "#" in str(path)
                for path in paths
            )
            or not isinstance(identity_fields, list)
            or not identity_fields
            or any(
                not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", str(field))
                for field in identity_fields
            )
        ):
            raise RoutePolicyError("registry_route_invalid")
        if (
            route["automation_allowed"]
            and str(route.get("verification_method", "")).startswith("head_")
            and not _head_contract_is_valid(route)
        ):
            raise RoutePolicyError("registry_route_contract_invalid")
        validated.append(route)
    return validated


def _identity_for_route(
    event: EventSnapshot, route: Mapping[str, Any]
) -> dict[str, str] | None:
    namespace = str(route.get("source_namespace", ""))
    identity_source = str(
        route.get("identity_source", "source_refs_namespace")
    )
    if identity_source == "source_refs_namespace":
        raw = event.source_refs.get(namespace)
    elif identity_source == "event_root_fields":
        raw = event.source_refs
    elif identity_source == "event_fields":
        raw = {}
    else:
        return None
    if not isinstance(raw, Mapping):
        return None
    identity: dict[str, str] = {}
    for field in route.get("identity_fields", []):
        if field == "event_id":
            value = event.event_id
        elif field == "local_date_yyyymmdd":
            value = event.local_date.strftime("%Y%m%d") if event.local_date else None
        elif field == "local_date_mmddyy":
            value = event.local_date.strftime("%m%d%y") if event.local_date else None
        else:
            value = raw.get(field)
        if value in (None, ""):
            return None
        normalized = str(value)
        if not IDENTITY_VALUE_PATTERN.fullmatch(normalized):
            return None
        identity[str(field)] = normalized
    track_codes = {str(value) for value in route.get("track_codes", [])}
    if track_codes:
        track_code = str(raw.get("track_code", ""))
        if track_code not in track_codes:
            return None
    return identity


def _route_candidates(
    event: EventSnapshot, routes: Iterable[Mapping[str, Any]]
) -> list[tuple[Mapping[str, Any], dict[str, str]]]:
    candidates = []
    for route in routes:
        if str(route.get("region")) != event.country_region:
            continue
        identity = _identity_for_route(event, route)
        if identity is not None:
            candidates.append((route, identity))
    return candidates


def validate_official_url(
    url: str,
    route: Mapping[str, Any],
    *,
    allow_fragment: bool = False,
) -> str:
    if not isinstance(url, str) or len(url) > MAX_URL_LENGTH:
        raise RoutePolicyError("url_invalid")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or (parsed.fragment and not allow_fragment)
    ):
        raise RoutePolicyError("url_invalid")
    host = parsed.hostname.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise RoutePolicyError("ip_literal_blocked")
    allowed_hosts = {
        str(value).lower().rstrip(".")
        for value in route.get("allowed_hosts", [])
    }
    if host not in allowed_hosts:
        raise RoutePolicyError("host_blocked")

    normalized_path = parsed.path
    for _ in range(5):
        if "\\" in normalized_path:
            raise RoutePolicyError("path_encoding_blocked")
        if any(
            segment in {".", ".."}
            for segment in normalized_path.split("/")
        ):
            raise RoutePolicyError("path_traversal_blocked")
        encoded_octets = re.findall(
            r"%([0-9A-Fa-f]{2})", normalized_path
        )
        if any(
            chr(int(octet, 16)) in {".", "/", "\\", "%"}
            for octet in encoded_octets
        ):
            raise RoutePolicyError("path_encoding_blocked")
        try:
            decoded_path = unquote(normalized_path, errors="strict")
        except UnicodeError as exc:
            raise RoutePolicyError("path_encoding_blocked") from exc
        if decoded_path == normalized_path:
            break
        normalized_path = decoded_path
    else:
        raise RoutePolicyError("path_encoding_blocked")
    if "%" in normalized_path:
        raise RoutePolicyError("path_encoding_blocked")

    def path_allowed(prefix: Any) -> bool:
        normalized = str(prefix)
        return (
            normalized_path.startswith(normalized)
            if normalized.endswith("/")
            else normalized_path == normalized
        )

    if not any(path_allowed(prefix) for prefix in route.get("allowed_path_prefixes", [])):
        raise RoutePolicyError("path_blocked")
    return url


def _parse_contract_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _as_utc(parsed)
    except (ValueError, TypeError) as exc:
        raise RoutePolicyError("contract_expiry_invalid") from exc


def _route_contract_digest(route: Mapping[str, Any]) -> str:
    payload = {
        key: value for key, value in route.items() if key != "contract_digest"
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(encoded)


def _head_contract_is_valid(route: Mapping[str, Any]) -> bool:
    method = str(route.get("verification_method", ""))
    if method not in {"head_exact_path", "head_application_entry"}:
        return False
    digest = str(route.get("contract_digest", ""))
    if (
        not re.fullmatch(r"[0-9a-f]{64}", digest)
        or digest != _route_contract_digest(route)
    ):
        return False
    origin = urlsplit(str(route.get("robots_evidence_origin", "")))
    allowed_hosts = {
        str(host).lower().rstrip(".")
        for host in route.get("allowed_hosts", [])
    }
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.hostname.lower().rstrip(".") not in allowed_hosts
        or origin.username is not None
        or origin.password is not None
        or origin.port not in (None, 443)
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
    ):
        return False
    try:
        status = int(route["robots_evidence_status"])
        _parse_contract_expiry(str(route["robots_evidence_observed_at"]))
        max_requests = int(route["max_requests_per_run"])
        min_interval = float(route["min_interval_seconds"])
    except (KeyError, TypeError, ValueError, RoutePolicyError):
        return False
    return (
        100 <= status <= 599
        and max_requests >= 1
        and min_interval >= 0
        and bool(str(route.get("request_url_template", "")))
        and bool(str(route.get("verification_scope", "")))
        and bool(
            re.fullmatch(
                r"[0-9a-f]{64}",
                str(route.get("robots_evidence_sha256", "")),
            )
        )
    )


def _result(
    outcome: DiscoveryOutcome,
    *,
    checked_at: datetime,
    provider: str = "",
    contract_version: str = "",
    url: str | None = None,
    provider_event_id: str = "",
    verification_method: str = "",
    verification_scope: str = "",
    source_url: str = "",
) -> DiscoveryResult:
    return DiscoveryResult(
        outcome=outcome,
        checked_at=_iso(_as_utc(checked_at)),
        provider=provider,
        provider_contract_version=contract_version,
        url=url,
        provider_event_id=provider_event_id,
        verification_method=verification_method,
        verification_scope=verification_scope,
        source_url=source_url,
        reason=outcome.value,
    )


def discover_event_url(
    event: EventSnapshot,
    *,
    routes: Iterable[Mapping[str, Any]],
    transport: Callable[..., TransportResponse],
    checked_at: datetime,
    max_response_bytes: int = MAX_RESPONSE_BYTES_DEFAULT,
) -> DiscoveryResult:
    """Discover one URL. Raw response data never leaves this stack frame."""
    checked_at = _as_utc(checked_at)
    candidates = _route_candidates(event, routes)
    if not candidates:
        return _result(
            DiscoveryOutcome.IDENTITY_MISSING, checked_at=checked_at
        )
    if len(candidates) != 1:
        return _result(
            DiscoveryOutcome.IDENTITY_CONFLICT, checked_at=checked_at
        )
    route, identity = candidates[0]
    provider = str(route["provider"])
    contract = str(route["contract_version"])
    verification_method = str(route.get("verification_method", ""))
    verification_scope = str(route.get("verification_scope", ""))
    provider_event_id = "|".join(
        f"{key}={identity[key]}" for key in sorted(identity)
    )

    def selected_result(
        outcome: DiscoveryOutcome,
        *,
        url: str | None = None,
        source_url: str = "",
    ) -> DiscoveryResult:
        return _result(
            outcome,
            checked_at=checked_at,
            provider=provider,
            contract_version=contract,
            url=url,
            provider_event_id=provider_event_id,
            verification_method=verification_method,
            verification_scope=verification_scope,
            source_url=source_url,
        )

    if not route.get("automation_allowed"):
        return selected_result(
            DiscoveryOutcome.ADAPTER_DISABLED
        )
    if (
        route.get("access_mode") != "automated_official_url_discovery"
        or route.get("robots_allowed") is not True
    ):
        return selected_result(DiscoveryOutcome.POLICY_BLOCKED)
    if verification_method.startswith("head_") and not _head_contract_is_valid(
        route
    ):
        return selected_result(DiscoveryOutcome.POLICY_BLOCKED)
    try:
        expiry = _parse_contract_expiry(str(route["valid_until"]))
    except RoutePolicyError:
        return selected_result(DiscoveryOutcome.POLICY_BLOCKED)
    if checked_at >= expiry:
        return selected_result(DiscoveryOutcome.POLICY_BLOCKED)
    template = str(route.get("url_template", ""))
    if not template:
        return selected_result(DiscoveryOutcome.CANDIDATE_UNVERIFIED)
    try:
        candidate_url = template.format(**identity)
        validate_official_url(
            candidate_url,
            route,
            allow_fragment=(
                verification_method == "head_application_entry"
            ),
        )
        request_template = str(
            route.get("request_url_template", template)
        )
        request_url = request_template.format(**identity)
        validate_official_url(request_url, route)
    except (KeyError, ValueError, RoutePolicyError):
        return selected_result(DiscoveryOutcome.POLICY_BLOCKED)
    try:
        response = transport(
            request_url,
            route=route,
            timeout_seconds=int(route.get("timeout_seconds", 10)),
            max_response_bytes=max_response_bytes,
            **(
                {"method": "HEAD"}
                if verification_method.startswith("head_")
                else {}
            ),
        )
        validate_official_url(response.final_url, route)
    except SoftTimeLimitExceeded:
        raise
    except RoutePolicyError:
        return selected_result(
            DiscoveryOutcome.POLICY_BLOCKED, source_url=request_url
        )
    except Exception:
        return selected_result(
            DiscoveryOutcome.SOURCE_ERROR, source_url=request_url
        )
    is_head = verification_method.startswith("head_")
    if not is_head and len(response.body) > max_response_bytes:
        return selected_result(
            DiscoveryOutcome.SOURCE_ERROR, source_url=request_url
        )
    if response.status_code == 404:
        if verification_method == "head_exact_path":
            return selected_result(
                DiscoveryOutcome.NOT_PUBLISHED, source_url=request_url
            )
        return selected_result(
            DiscoveryOutcome.PATH_UNVERIFIED, source_url=request_url
        )
    if response.status_code == 429 or response.status_code >= 500:
        return selected_result(
            DiscoveryOutcome.SOURCE_ERROR, source_url=request_url
        )
    if response.status_code != 200:
        return selected_result(
            DiscoveryOutcome.PATH_UNVERIFIED, source_url=request_url
        )
    if verification_method == "head_exact_path":
        return selected_result(
            DiscoveryOutcome.FOUND,
            url=candidate_url,
            source_url=request_url,
        )
    if verification_method == "head_application_entry":
        return selected_result(
            DiscoveryOutcome.LISTING_REACHABLE,
            url=candidate_url,
            source_url=request_url,
        )
    body = response.body.decode("utf-8", errors="replace")
    unpublished = str(route.get("not_published_marker", ""))
    if unpublished and unpublished in body:
        return selected_result(
            DiscoveryOutcome.NOT_PUBLISHED, source_url=request_url
        )
    marker_template = str(route.get("identity_marker_template", ""))
    try:
        marker = marker_template.format(**identity)
    except (KeyError, ValueError):
        marker = ""
    matches = body.count(marker) if marker else 0
    if matches > 1:
        return selected_result(
            DiscoveryOutcome.DUPLICATE_MATCH, source_url=request_url
        )
    if matches != 1:
        return selected_result(
            DiscoveryOutcome.CANDIDATE_UNVERIFIED, source_url=request_url
        )
    return selected_result(
        DiscoveryOutcome.FOUND,
        url=response.final_url,
        source_url=request_url,
    )


def _public_dns_addresses(host: str) -> tuple[str, ...]:
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise RoutePolicyError("dns_failed") from exc
    validated: list[str] = []
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_global is not True:
            raise RoutePolicyError("dns_address_blocked")
        normalized = str(ip)
        if normalized not in validated:
            validated.append(normalized)
    if not validated:
        raise RoutePolicyError("dns_failed")
    return tuple(validated)


class SafeHttpTransport:
    """Small, redirect-free HTTP client used only by an enabled route."""

    def __init__(
        self,
        *,
        total_request_budget: int = 50,
        per_host_request_budget: int = 10,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.remaining_requests = total_request_budget
        self.per_host_request_budget = per_host_request_budget
        self._host_requests: dict[str, int] = {}
        self._route_requests: dict[str, int] = {}
        self._last_host_request_at: dict[str, float] = {}
        self._responses: dict[tuple[str, str], TransportResponse] = {}
        self._monotonic = monotonic
        self._sleeper = sleeper

    def __call__(
        self,
        url: str,
        *,
        route: Mapping[str, Any],
        timeout_seconds: int,
        max_response_bytes: int,
        method: str = "GET",
    ) -> TransportResponse:
        method = method.upper()
        if method not in {"GET", "HEAD"}:
            raise RoutePolicyError("method_blocked")
        validated = validate_official_url(url, route)
        cache_key = (method, validated)
        if cache_key in self._responses:
            return self._responses[cache_key]
        parsed = urlsplit(validated)
        host = parsed.hostname
        assert host is not None
        if self.remaining_requests <= 0:
            raise RoutePolicyError("request_budget_exhausted")
        if self._host_requests.get(host, 0) >= self.per_host_request_budget:
            raise RoutePolicyError("host_request_budget_exhausted")
        route_key = str(
            route.get("contract_digest")
            or route.get("contract_version")
            or route.get("provider")
            or "unresolved"
        )
        route_budget = int(
            route.get("max_requests_per_run", self.per_host_request_budget)
        )
        if self._route_requests.get(route_key, 0) >= route_budget:
            raise RoutePolicyError("route_request_budget_exhausted")
        now = self._monotonic()
        interval = max(0.0, float(route.get("min_interval_seconds", 0)))
        last_request = self._last_host_request_at.get(host)
        if last_request is not None:
            remaining = interval - (now - last_request)
            if remaining > 0:
                self._sleeper(remaining)
                now = self._monotonic()
        addresses = _public_dns_addresses(host)
        self.remaining_requests -= 1
        self._host_requests[host] = self._host_requests.get(host, 0) + 1
        self._route_requests[route_key] = (
            self._route_requests.get(route_key, 0) + 1
        )
        self._last_host_request_at[host] = now
        context = ssl.create_default_context()
        raw_socket = socket.create_connection(
            (addresses[0], 443), timeout=max(1, timeout_seconds)
        )
        try:
            tls_socket = context.wrap_socket(raw_socket, server_hostname=host)
        except BaseException:
            raw_socket.close()
            raise
        connection = http.client.HTTPSConnection(
            host,
            port=443,
            timeout=max(1, timeout_seconds),
            context=context,
        )
        connection.sock = tls_socket
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        try:
            connection.request(
                method,
                target,
                headers={
                    "Host": host,
                    "User-Agent": "UmanewsOfficialUrlDiscovery/1.0",
                    "Accept": "text/html,application/xhtml+xml",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if 300 <= int(response.status) < 400:
                raise RoutePolicyError("redirect_blocked")
            body = (
                b""
                if method == "HEAD"
                else response.read(max_response_bytes + 1)
            )
            result = TransportResponse(
                status_code=int(response.status),
                final_url=validated,
                body=body,
            )
            self._responses[cache_key] = result
            return result
        finally:
            connection.close()


def _canonical_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    canonical = json.loads(json.dumps(payload, ensure_ascii=False))
    for key in (
        "canonical_payload_sha256",
        "markdown_sha256",
        "json_sha256",
        "manifest_sha256",
    ):
        canonical.pop(key, None)
    canonical["events"] = sorted(
        canonical.get("events", []),
        key=lambda row: (
            row.get("local_date") is None,
            row.get("local_date") or "9999-12-31",
            row.get("country_region") or "",
            int(row.get("event_id", 0)),
        ),
    )
    return canonical


def _merge_payload_events_against_current(
    payload: Mapping[str, Any],
    current: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Apply discovery outcomes against the current state held under the lock."""
    merged_payload = json.loads(json.dumps(payload, ensure_ascii=False))
    current_by_id = {
        int(row["event_id"]): row
        for row in (current or {}).get("events", [])
    }
    merged_events: list[dict[str, Any]] = []
    state_fields = {
        "provider",
        "provider_event_id",
        "provider_contract_version",
        "verification_method",
        "verification_scope",
        "source_url",
        "checked_provider",
        "checked_provider_event_id",
        "checked_provider_contract_version",
        "checked_verification_method",
        "checked_verification_scope",
        "checked_source_url",
        "discovery_outcome",
        "persisted_status",
        "url",
        "last_confirmed_at",
        "last_checked_at",
        "reason",
    }
    for row in merged_payload.get("events", []):
        outcome = DiscoveryOutcome(str(row["discovery_outcome"]))
        result = DiscoveryResult(
            outcome=outcome,
            checked_at=str(row["last_checked_at"]),
            provider=str(row.get("checked_provider", "")),
            provider_contract_version=str(
                row.get("checked_provider_contract_version", "")
            ),
            provider_event_id=str(
                row.get("checked_provider_event_id", "")
            ),
            verification_method=str(
                row.get("checked_verification_method", "")
            ),
            verification_scope=str(
                row.get("checked_verification_scope", "")
            ),
            source_url=str(row.get("checked_source_url", "")),
            url=(
                str(row["url"])
                if outcome
                in {
                    DiscoveryOutcome.FOUND,
                    DiscoveryOutcome.LISTING_REACHABLE,
                }
                else None
            ),
            reason=outcome.value,
        )
        identity = {
            key: value for key, value in row.items() if key not in state_fields
        }
        merged_events.append(
            {
                **identity,
                **merge_discovery_state(
                    current_by_id.get(int(row["event_id"])),
                    result,
                ),
            }
        )
    merged_payload["events"] = merged_events
    return merged_payload


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _markdown_bytes(
    canonical: Mapping[str, Any], canonical_sha: str
) -> bytes:
    window = canonical.get("window", {})
    coverage = canonical.get("coverage", {})
    lines = [
        "# 未来七天 P0 赛事官方出马页面",
        "",
        f"- 生成时间：{html.escape(str(canonical.get('generated_at', '')))}",
        f"- UTC 窗口：`{html.escape(str(window.get('start', '')))}` 至 "
        f"`{html.escape(str(window.get('end', '')))}`（左闭右开）",
        f"- 中文窗口：`{html.escape(str(window.get('start_zh', '')))}` 至 "
        f"`{html.escape(str(window.get('end_zh', '')))}`（左闭右开）",
        f"- 调度时区：`{html.escape(str(window.get('timezone', '')))}`",
        f"- 可判窗 P0：{int(coverage.get('future_expected', 0))}",
        f"- 时间身份缺失：{int(coverage.get('orphans', 0))}",
        f"- Canonical SHA-256：`{canonical_sha}`",
        "",
        "| 日期 | 地区 | 赛事 | URL Provider / 本轮检查 | 出马页面 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    for row in canonical.get("events", []):
        url = row.get("url")
        if not url:
            link = "暂无"
        else:
            is_listing = (
                row.get("persisted_status") == "listing_reachable"
                or row.get("discovery_outcome") == "listing_reachable"
                or row.get("verification_method")
                == "head_application_entry"
                or row.get("verification_scope") == "date_listing"
            )
            label = (
                "官方日期索引（需人工确认）"
                if is_listing
                else "已确认出马索引"
            )
            link = (
                f"[{label}]({html.escape(str(url), quote=True)})"
            )
        provider = str(row.get("provider") or "")
        checked_provider = str(row.get("checked_provider") or "")
        provider_display = provider
        if checked_provider and checked_provider != provider:
            provider_display = f"{provider or '无'} / 检查:{checked_provider}"
        cells = [
            str(row.get("local_date") or "未知"),
            str(row.get("country_region") or ""),
            str(row.get("name_zh") or row.get("original_name") or ""),
            provider_display,
            link,
            str(row.get("reason") or row.get("discovery_outcome") or ""),
        ]
        safe_cells = [
            html.escape(value, quote=True).replace("|", "\\|")
            if index != 4
            else value
            for index, value in enumerate(cells)
        ]
        lines.append("| " + " | ".join(safe_cells) + " |")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _validate_artifact_root(root: Path) -> None:
    if not root.is_absolute():
        raise ArtifactSafetyError("artifact_root_not_absolute")
    if ".." in root.parts:
        raise ArtifactSafetyError("artifact_root_not_normalized")
    ancestor = root.parent
    while True:
        if ancestor.is_symlink():
            raise ArtifactSafetyError("artifact_root_parent_symlink")
        if ancestor == ancestor.parent:
            break
        ancestor = ancestor.parent
    if root.is_symlink():
        raise ArtifactSafetyError("artifact_root_symlink")
    if not root.exists():
        if not root.parent.is_dir():
            raise ArtifactSafetyError("artifact_root_parent_missing")
        root.mkdir(mode=0o750)
    if not root.is_dir():
        raise ArtifactSafetyError("artifact_root_not_directory")
    for path in root.rglob("*"):
        if path == root / "current":
            continue
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ArtifactSafetyError("unexpected_symlink")
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ArtifactSafetyError("unexpected_file_type")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_durable(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o640,
    )
    try:
        written = 0
        while written < len(content):
            written += os.write(descriptor, content[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _current_generation(root: Path) -> Path | None:
    current = root / "current"
    if not current.exists() and not current.is_symlink():
        return None
    if not current.is_symlink():
        raise ArtifactSafetyError("current_not_symlink")
    target = os.readlink(current)
    parts = Path(target).parts
    if (
        len(parts) != 2
        or parts[0] != "generations"
        or len(parts[1]) != 64
        or any(char not in "0123456789abcdef" for char in parts[1])
    ):
        raise ArtifactSafetyError("current_target_invalid")
    resolved = (root / target).resolve()
    generations = (root / "generations").resolve()
    if resolved.parent != generations or not resolved.is_dir():
        raise ArtifactSafetyError("current_target_invalid")
    return resolved


def read_current_payload(root: Path) -> dict[str, Any] | None:
    current = _current_generation(root)
    if current is None:
        return None
    verify_generation(current)
    return json.loads((current / "latest.json").read_text(encoding="utf-8"))


def verify_generation(path: Path) -> None:
    if path.is_symlink():
        path = path.resolve()
    for name in ("latest.md", "latest.json", "manifest.json"):
        file_path = path / name
        if not file_path.is_file() or file_path.is_symlink():
            raise ArtifactSafetyError("generation_file_invalid")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    for name, digest_key in (
        ("latest.md", "markdown_sha256"),
        ("latest.json", "json_sha256"),
    ):
        actual = _sha256((path / name).read_bytes())
        if actual != manifest.get(digest_key):
            raise ArtifactSafetyError("generation_sha_mismatch")
    latest = json.loads((path / "latest.json").read_text(encoding="utf-8"))
    canonical = _canonical_payload(latest)
    canonical_sha = _sha256(_json_bytes(canonical))
    if canonical_sha != latest.get("canonical_payload_sha256"):
        raise ArtifactSafetyError("canonical_sha_mismatch")
    if canonical_sha != manifest.get("generation_id"):
        raise ArtifactSafetyError("generation_id_mismatch")


def _cleanup_generations(
    root: Path, current_id: str, previous_id: str | None
) -> None:
    generations = root / "generations"
    candidates = [
        path
        for path in generations.iterdir()
        if path.is_dir()
        and not path.is_symlink()
        and not path.name.startswith(".tmp-")
    ]
    keep = {current_id}
    if previous_id and previous_id != current_id:
        keep.add(previous_id)
    for path in candidates:
        if path.name not in keep:
            shutil.rmtree(path)


def publish_generation(
    root: Path | str,
    payload: Mapping[str, Any],
    *,
    merge_event_results: bool = False,
    phase_hook: Callable[[str], None] | None = None,
) -> PublishedGeneration:
    root = Path(root)
    _validate_artifact_root(root)
    generations = root / "generations"
    generations.mkdir(mode=0o750, exist_ok=True)
    lock_path = root / ".publish.lock"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PublishLockBusyError("publish_lock_busy") from exc
        for leftover in generations.glob(".tmp-*"):
            if leftover.is_dir() and not leftover.is_symlink():
                shutil.rmtree(leftover)
            else:
                raise ArtifactSafetyError("temporary_generation_invalid")
        previous_path = _current_generation(root)
        previous_id = previous_path.name if previous_path else None
        previous = read_current_payload(root)
        new_started = _as_utc(
            datetime.fromisoformat(
                str(payload["run_started_at"]).replace("Z", "+00:00")
            )
        )
        if previous:
            previous_started = _as_utc(
                datetime.fromisoformat(
                    str(previous["run_started_at"]).replace("Z", "+00:00")
                )
            )
            if previous_started > new_started:
                raise StaleRunError("stale_run")
        locked_payload = (
            _merge_payload_events_against_current(payload, previous)
            if merge_event_results
            else dict(payload)
        )
        canonical = _canonical_payload(locked_payload)
        canonical_bytes = _json_bytes(canonical)
        canonical_sha = _sha256(canonical_bytes)
        markdown = _markdown_bytes(canonical, canonical_sha)
        markdown_sha = _sha256(markdown)
        latest = dict(canonical)
        latest["canonical_payload_sha256"] = canonical_sha
        latest["markdown_sha256"] = markdown_sha
        latest_json = _json_bytes(latest)
        json_sha = _sha256(latest_json)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "generation_id": canonical_sha,
            "markdown_sha256": markdown_sha,
            "json_sha256": json_sha,
        }
        manifest_json = _json_bytes(manifest)
        final = generations / canonical_sha
        if not final.exists():
            temporary = generations / f".tmp-{os.getpid()}-{canonical_sha}"
            if temporary.exists():
                shutil.rmtree(temporary)
            temporary.mkdir(mode=0o750)
            try:
                _write_durable(temporary / "latest.md", markdown)
                if phase_hook:
                    phase_hook("after_markdown_fsync")
                _write_durable(temporary / "latest.json", latest_json)
                if phase_hook:
                    phase_hook("after_json_fsync")
                _write_durable(temporary / "manifest.json", manifest_json)
                _fsync_directory(temporary)
                if phase_hook:
                    phase_hook("after_generation_fsync")
                os.rename(temporary, final)
                _fsync_directory(generations)
                if phase_hook:
                    phase_hook("after_generation_rename")
            except BaseException:
                if temporary.exists():
                    shutil.rmtree(temporary)
                raise
        verify_generation(final)
        temporary_link = root / f".current-{os.getpid()}-{canonical_sha}"
        if temporary_link.exists() or temporary_link.is_symlink():
            temporary_link.unlink()
        try:
            temporary_link.symlink_to(f"generations/{canonical_sha}")
            if phase_hook:
                phase_hook("before_current_replace")
            os.replace(temporary_link, root / "current")
        finally:
            if temporary_link.is_symlink():
                temporary_link.unlink()
        _fsync_directory(root)
        if phase_hook:
            phase_hook("after_current_replace")
        verify_generation(_current_generation(root) or final)
        _cleanup_generations(root, canonical_sha, previous_id)
        return PublishedGeneration(
            generation_id=canonical_sha,
            path=final,
            canonical_payload_sha256=canonical_sha,
            markdown_sha256=markdown_sha,
            json_sha256=json_sha,
            payload=latest,
        )


def _event_document_row(
    event: EventSnapshot,
    result: DiscoveryResult,
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    state = merge_discovery_state(previous, result)
    return {
        "event_id": event.event_id,
        "year": event.year,
        "slug": event.slug,
        "series_key": event.series_key,
        "original_name": event.original_name,
        "name_zh": event.name_zh,
        "country_region": event.country_region,
        "racecourse": event.racecourse,
        "race_datetime": (
            _iso(_as_utc(event.race_datetime))
            if event.race_datetime
            else None
        ),
        "local_date": event.local_date.isoformat() if event.local_date else None,
        "timezone_name": event.timezone_name,
        "priority": event.priority,
        "status": event.status,
        "visibility_status": event.visibility_status,
        "data_quality_status": event.data_quality_status,
        "is_featured": event.is_featured,
        "series_review_status": event.series_review_status,
        "inclusion_basis": event.inclusion_basis,
        "provider": result.provider,
        "provider_event_id": result.provider_event_id,
        "provider_contract_version": result.provider_contract_version,
        **state,
    }


def _summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "found": 0,
        "listing_reachable": 0,
        "not_available": 0,
        "preserved_previous": 0,
        "blocked": 0,
        "errors": 0,
        "by_region": {},
        "by_provider": {},
    }
    for row in events:
        status = row["persisted_status"]
        if status == "confirmed":
            result["found"] += 1
        elif status == "listing_reachable":
            result["listing_reachable"] += 1
        elif status == "previous_url_unverified":
            result["preserved_previous"] += 1
        else:
            result["not_available"] += 1
        if row["discovery_outcome"] in {
            "adapter_disabled",
            "policy_blocked",
            "identity_missing",
            "identity_conflict",
        }:
            result["blocked"] += 1
        if DiscoveryOutcome(row["discovery_outcome"]) in ERROR_OUTCOMES:
            result["errors"] += 1
        region = row["country_region"]
        provider = row.get("checked_provider") or "unresolved"
        result["by_region"][region] = result["by_region"].get(region, 0) + 1
        result["by_provider"][provider] = (
            result["by_provider"].get(provider, 0) + 1
        )
    return result


def run_p0_racecard_url_discovery(
    *,
    events: Iterable[Any],
    run_started_at: datetime,
    artifact_root: Path | str,
    registry_path: Path | str,
    registry_sha256: str = "",
    transport: Callable[..., TransportResponse],
    max_targets: int = MAX_TARGETS_DEFAULT,
) -> dict[str, Any]:
    inventory = enumerate_event_snapshots(
        events,
        run_started_at=run_started_at,
        max_targets=max_targets,
    )
    routes = load_route_registry(
        registry_path, expected_sha256=registry_sha256
    )
    root = Path(artifact_root)
    if root.exists():
        _validate_artifact_root(root)
    checked_at = _as_utc(run_started_at)
    document_events: list[dict[str, Any]] = []
    for event in inventory.future:
        result = discover_event_url(
            event,
            routes=routes,
            transport=transport,
            checked_at=checked_at,
        )
        document_events.append(_event_document_row(event, result, None))
    for event in inventory.orphans:
        result = _result(
            DiscoveryOutcome.IDENTITY_MISSING, checked_at=checked_at
        )
        document_events.append(_event_document_row(event, result, None))
    coverage = {
        "future_expected": len(inventory.future),
        "orphans": len(inventory.orphans),
    }
    provider_coverage = [
        {
            "provider": route["provider"],
            "region": route["region"],
            "registered": True,
            "enabled": bool(route["automation_allowed"]),
            "blocked": not bool(route["automation_allowed"]),
            "contract_version": route["contract_version"],
            "access_mode": route["access_mode"],
            "robots_allowed": route["robots_allowed"],
            "valid_until": route["valid_until"],
            "evidence_url": route.get("evidence_url", ""),
        }
        for route in routes
    ]
    generated_at = datetime.now(timezone.utc)
    shanghai = ZoneInfo(SCHEDULE_TIMEZONE)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(generated_at),
        "run_started_at": _iso(_as_utc(run_started_at)),
        "window": {
            "start": _iso(inventory.window_start),
            "end": _iso(inventory.window_end),
            "start_zh": _iso(inventory.window_start.astimezone(shanghai)),
            "end_zh": _iso(inventory.window_end.astimezone(shanghai)),
            "timezone": SCHEDULE_TIMEZONE,
        },
        "coverage": coverage,
        "providers": provider_coverage,
        "events": document_events,
    }
    published = publish_generation(
        root, payload, merge_event_results=True
    )
    published_events = published.payload["events"]
    summary = {
        **coverage,
        **_summary(published_events),
        "generation_id": published.generation_id,
    }
    return summary

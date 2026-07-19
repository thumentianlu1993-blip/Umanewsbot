from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.cache import cache as django_cache
from django.utils import timezone

from stable.models import (
    RaceEvent,
    RaceEventLiveState,
    RaceEventLiveTracking,
    RaceEventProjectionControl,
    RaceEventProjectionWriteOwner,
    RaceResultSourceIdentity,
)
from stable.services.race_events import (
    admit_race_live_publication,
    apply_race_result_observation_revision,
    calculate_race_live_next_poll_at,
    checkpoint_or_promote_race_event_live_pre_off,
    complete_race_event_live_checkpoint,
    record_race_result_observation,
    record_race_live_host_outcome,
    reserve_race_live_host_request,
    resolve_race_source_network_permission,
)
from stable.services.race_live_fixtures import (
    parse_the_racing_api_live_racecards_payload,
    parse_the_racing_api_live_results_payload,
    parse_the_racing_api_offline_fixture,
)
from stable.services.race_live_source_proof import (
    _read_secret,
    build_the_racing_api_route_url,
    read_the_racing_api_automation_registry,
)
from stable.services.race_live_racecard_sync import refresh_race_live_racecard


_SOURCE_KEY = "the_racing_api"
_HOST = "api.theracingapi.com"
_RESULTS_URL = (
    "https://api.theracingapi.com/v1/results/today/free?limit=50&skip=0"
)
_SAFE_EXTERNAL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MAX_FIXTURE_BYTES = 2 * 1024 * 1024
_RESULTS_PAGE_LIMIT = 50
_RESULTS_MAX_TOTAL = 500
_RESULTS_SNAPSHOT_TTL_SECONDS = 150
_RACECARD_SNAPSHOT_TTL_SECONDS = 150
_REGION_CODES = frozenset({"gb", "fr", "hk", "jpn", "usa"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_PAGINATION_REASON_CATEGORIES = {
    "results_pagination_deadline_exceeded": "deadline_exceeded",
    "results_pagination_incomplete": "incomplete",
    "results_pagination_metadata_drift": "metadata_drift",
    "results_pagination_overflow": "overflow",
}


class _ResultsPageFetchError(Exception):
    def __init__(self, reason: str, *, now: datetime):
        super().__init__(reason)
        self.reason = reason
        self.now = now


class _ResultsPaginationError(Exception):
    def __init__(
        self,
        reason: str,
        *,
        category: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.category = category
        self.details = {} if details is None else dict(details)


def _pagination_checkpoint_payload(
    *,
    reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    category = _PAGINATION_REASON_CATEGORIES.get(reason)
    if category is None:
        return {}
    pagination = {
        "category": category,
        "reason": reason,
    }
    if details:
        pagination.update(details)
    return {"pagination": pagination}


def build_race_live_results_snapshot_cache_key(
    *,
    source_key: str,
    provider_date: date,
    registry_digest: str,
    endpoint_contract_version: str,
    region_code: str,
) -> str:
    if source_key != _SOURCE_KEY:
        raise PermissionError("results snapshot source is not allowed")
    if not isinstance(provider_date, date) or isinstance(
        provider_date, datetime
    ):
        raise TypeError("provider_date must be a date")
    if (
        not isinstance(registry_digest, str)
        or _SHA256_RE.fullmatch(registry_digest) is None
    ):
        raise ValueError("registry digest is invalid")
    if (
        not isinstance(endpoint_contract_version, str)
        or not endpoint_contract_version
        or endpoint_contract_version != endpoint_contract_version.strip()
        or ":" in endpoint_contract_version
    ):
        raise ValueError("endpoint contract version is invalid")
    if region_code not in _REGION_CODES:
        raise PermissionError("results snapshot region is not allowed")
    return (
        "race-live:tra-results:v2:"
        f"{registry_digest}:{region_code}:{provider_date.isoformat()}:"
        f"{endpoint_contract_version}"
    )


def build_race_live_racecard_snapshot_cache_key(
    *,
    source_key: str,
    provider_date: date,
    registry_digest: str,
    endpoint_contract_version: str,
    region_code: str,
    day: str,
) -> str:
    if day not in {"today", "tomorrow"}:
        raise ValueError("racecard snapshot day is invalid")
    base = build_race_live_results_snapshot_cache_key(
        source_key=source_key,
        provider_date=provider_date,
        registry_digest=registry_digest,
        endpoint_contract_version=endpoint_contract_version,
        region_code=region_code,
    )
    return base.replace("tra-results", "tra-racecards", 1) + f":{day}"


def get_or_fetch_region_racecard_snapshot(
    *,
    source_key: str,
    provider_date: date,
    registry_digest: str,
    endpoint_contract_version: str,
    region_code: str,
    day: str,
    fetch_snapshot,
    fetched_at: datetime,
    cache_backend=None,
) -> dict[str, Any]:
    if not callable(fetch_snapshot):
        raise TypeError("fetch_snapshot must be callable")
    if not isinstance(fetched_at, datetime) or timezone.is_naive(fetched_at):
        raise ValueError("fetched_at must be aware")
    cache_key = build_race_live_racecard_snapshot_cache_key(
        source_key=source_key,
        provider_date=provider_date,
        registry_digest=registry_digest,
        endpoint_contract_version=endpoint_contract_version,
        region_code=region_code,
        day=day,
    )
    backend = django_cache if cache_backend is None else cache_backend
    try:
        cached = backend.get(cache_key)
    except Exception:
        cached = None
    expected = {
        "schema_version": 2,
        "source_key": source_key,
        "region_code": region_code,
        "provider_date": provider_date.isoformat(),
        "registry_digest": registry_digest,
        "endpoint_contract_version": endpoint_contract_version,
        "day": day,
    }
    if (
        isinstance(cached, dict)
        and set(cached)
        == {
            *expected,
            "fetched_at",
            "payload_sha256",
            "races",
        }
        and all(cached.get(key) == value for key, value in expected.items())
        and _SHA256_RE.fullmatch(str(cached.get("payload_sha256"))) is not None
        and isinstance(cached.get("races"), dict)
        and all(
            isinstance(race_id, str)
            and isinstance(race, dict)
            and race.get("external_race_id") == race_id
            for race_id, race in cached["races"].items()
        )
    ):
        return cached
    fetched = fetch_snapshot()
    if not isinstance(fetched, dict) or set(fetched) != {
        "payload_sha256",
        "races",
    }:
        raise ValueError("racecard snapshot fetch contract is invalid")
    if _SHA256_RE.fullmatch(str(fetched["payload_sha256"])) is None:
        raise ValueError("racecard snapshot hash is invalid")
    races_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(fetched["races"], (list, tuple)):
        raise ValueError("racecard snapshot races are invalid")
    for race in fetched["races"]:
        if not isinstance(race, dict):
            raise ValueError("racecard snapshot race is invalid")
        race_id = race.get("external_race_id")
        if (
            not isinstance(race_id, str)
            or not race_id
            or race_id in races_by_id
        ):
            raise PermissionError("racecard snapshot race identity is invalid")
        races_by_id[race_id] = race
    snapshot = {
        **expected,
        "fetched_at": fetched_at.isoformat(),
        "payload_sha256": fetched["payload_sha256"],
        "races": races_by_id,
    }
    try:
        backend.set(
            cache_key,
            snapshot,
            timeout=_RACECARD_SNAPSHOT_TTL_SECONDS,
        )
    except Exception:
        pass
    return snapshot


def build_the_racing_api_results_page_skips(*, total: int) -> tuple[int, ...]:
    if isinstance(total, bool) or not isinstance(total, int):
        raise TypeError("results total must be an integer")
    if total < 0 or total > _RESULTS_MAX_TOTAL:
        raise ValueError("results total is outside the bounded Free contract")
    page_count = max(1, (total + _RESULTS_PAGE_LIMIT - 1) // _RESULTS_PAGE_LIMIT)
    return tuple(range(0, page_count * _RESULTS_PAGE_LIMIT, _RESULTS_PAGE_LIMIT))


def _valid_cached_region_results_snapshot(
    value: Any,
    *,
    source_key: str,
    provider_date: date,
    registry_digest: str,
    endpoint_contract_version: str,
    region_code: str,
) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "source_key",
        "region_code",
        "provider_date",
        "registry_digest",
        "endpoint_contract_version",
        "fetched_at",
        "total",
        "pages",
        "payload_sha256",
        "races",
    }:
        return False
    try:
        fetched_at = datetime.fromisoformat(
            value["fetched_at"].replace("Z", "+00:00")
        )
        expected_pages = len(
            build_the_racing_api_results_page_skips(total=value["total"])
        )
    except (AttributeError, TypeError, ValueError):
        return False
    races = value["races"]
    if (
        timezone.is_naive(fetched_at)
        or value["schema_version"] != 2
        or value["source_key"] != source_key
        or value["provider_date"] != provider_date.isoformat()
        or value["registry_digest"] != registry_digest
        or value["endpoint_contract_version"] != endpoint_contract_version
        or value["region_code"] != region_code
        or value["pages"] != expected_pages
        or _SHA256_RE.fullmatch(str(value["payload_sha256"])) is None
        or not isinstance(races, dict)
        or len(races) > value["total"]
    ):
        return False
    return all(
        isinstance(external_race_id, str)
        and isinstance(race, dict)
        and race.get("external_race_id") == external_race_id
        for external_race_id, race in races.items()
    )


def get_or_fetch_region_results_snapshot(
    *,
    source_key: str,
    provider_date: date,
    registry_digest: str,
    endpoint_contract_version: str,
    region_code: str,
    fetch_page,
    fetched_at: datetime,
    cache_backend=None,
) -> dict[str, Any]:
    """Fetch one complete bounded region result snapshot and cache normalized rows."""

    if not callable(fetch_page):
        raise TypeError("fetch_page must be callable")
    if not isinstance(fetched_at, datetime) or timezone.is_naive(fetched_at):
        raise ValueError("fetched_at must be aware")
    cache_key = build_race_live_results_snapshot_cache_key(
        source_key=source_key,
        provider_date=provider_date,
        registry_digest=registry_digest,
        endpoint_contract_version=endpoint_contract_version,
        region_code=region_code,
    )
    backend = django_cache if cache_backend is None else cache_backend
    try:
        cached = backend.get(cache_key)
    except Exception:
        cached = None
    if _valid_cached_region_results_snapshot(
        cached,
        source_key=source_key,
        provider_date=provider_date,
        registry_digest=registry_digest,
        endpoint_contract_version=endpoint_contract_version,
        region_code=region_code,
    ):
        return cached

    first = fetch_page(skip=0, limit=_RESULTS_PAGE_LIMIT)
    if not isinstance(first, dict):
        raise ValueError("results page must be an object")
    total = first.get("total")
    if (
        isinstance(total, int)
        and not isinstance(total, bool)
        and total > _RESULTS_MAX_TOTAL
    ):
        raise _ResultsPaginationError(
            "results_pagination_overflow",
            category="overflow",
            details={
                "total": total,
                "maximum_total": _RESULTS_MAX_TOTAL,
            },
        )
    skips = build_the_racing_api_results_page_skips(total=total)
    pages = [first]
    for skip in skips[1:]:
        pages.append(fetch_page(skip=skip, limit=_RESULTS_PAGE_LIMIT))

    races_by_id: dict[str, dict[str, Any]] = {}
    payload_hashes: list[str] = []
    for expected_skip, page in zip(skips, pages, strict=True):
        if not isinstance(page, dict):
            raise ValueError("results page must be an object")
        if (
            page.get("total") != total
            or page.get("skip") != expected_skip
            or page.get("limit") != _RESULTS_PAGE_LIMIT
        ):
            raise _ResultsPaginationError(
                "results_pagination_metadata_drift",
                category="metadata_drift",
                details={
                    "expected_total": total,
                    "expected_skip": expected_skip,
                },
            )
        payload_sha256 = page.get("payload_sha256")
        if (
            not isinstance(payload_sha256, str)
            or _SHA256_RE.fullmatch(payload_sha256) is None
        ):
            raise ValueError("results page hash is invalid")
        payload_hashes.append(payload_sha256)
        races = page.get("races")
        if not isinstance(races, (list, tuple)) or len(races) > _RESULTS_PAGE_LIMIT:
            raise ValueError("results page race collection is invalid")
        for race in races:
            if not isinstance(race, dict):
                raise ValueError("normalized result race must be an object")
            external_race_id = race.get("external_race_id")
            if (
                not isinstance(external_race_id, str)
                or not external_race_id
                or external_race_id != external_race_id.strip()
                or external_race_id in races_by_id
            ):
                raise PermissionError(
                    "results snapshot external race identity is invalid"
                )
            races_by_id[external_race_id] = race
    if len(races_by_id) > total:
        raise PermissionError("results snapshot exceeds provider total")

    combined_sha256 = hashlib.sha256(
        json.dumps(
            payload_hashes,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    snapshot = {
        "schema_version": 2,
        "source_key": source_key,
        "region_code": region_code,
        "provider_date": provider_date.isoformat(),
        "registry_digest": registry_digest,
        "endpoint_contract_version": endpoint_contract_version,
        "fetched_at": fetched_at.isoformat(),
        "total": total,
        "pages": len(pages),
        "payload_sha256": combined_sha256,
        "races": races_by_id,
    }
    try:
        backend.set(
            cache_key,
            snapshot,
            timeout=_RESULTS_SNAPSHOT_TTL_SECONDS,
        )
    except Exception:
        pass
    return snapshot


def _checkpoint_result(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    now,
    success: bool,
    next_poll_at,
    checkpoint_payload: dict[str, Any],
    observation_sha256: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    checkpoint = complete_race_event_live_checkpoint(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
        success=success,
        next_poll_at=next_poll_at,
        checkpoint_payload=checkpoint_payload,
        observation_sha256=observation_sha256,
    )
    if not checkpoint.applied:
        return {
            "processed": False,
            "reason": f"checkpoint_{checkpoint.reason}",
            "event_id": event_id,
        }
    return result


def _failure(
    *,
    reason: str,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    now,
    checkpoint_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checkpoint_payload = {"status": "failed", "reason": reason}
    if checkpoint_details:
        checkpoint_payload.update(checkpoint_details)
    return _checkpoint_result(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
        success=False,
        next_poll_at=now + timedelta(minutes=5),
        checkpoint_payload=checkpoint_payload,
        observation_sha256="",
        result={"processed": False, "reason": reason, "event_id": event_id},
    )


def _safe_fixture_path(fixture_root: str, external_race_id: str) -> Path | None:
    if (
        not isinstance(fixture_root, str)
        or not fixture_root
        or not isinstance(external_race_id, str)
        or external_race_id in {".", ".."}
        or _SAFE_EXTERNAL_ID_RE.fullmatch(external_race_id) is None
        or Path(external_race_id).name != external_race_id
    ):
        return None
    configured_root = Path(fixture_root)
    if not configured_root.is_absolute():
        return None
    root = configured_root.resolve(strict=False)
    candidate = (root / _SOURCE_KEY / f"{external_race_id}.json").resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _normalized_result_payload(race: dict[str, Any]) -> dict[str, Any]:
    participants = []
    for participant in race["participants"]:
        status = participant["status"]
        participants.append(
            {
                "external_runner_id": participant["external_runner_id"],
                "status": status,
                "official_finish_position": participant["official_finish_position"],
                "raw_status": str(participant["position_raw"]),
                "finish_time": "",
                "margin": "",
                "number": participant["number"],
                "barrier": "",
                "jockey_name": "",
                "trainer_name": "",
                "carried_weight": "",
                "field_provenance": {"result": _SOURCE_KEY},
            }
        )
    return {
        "external_race_id": race["external_race_id"],
        "off_time": race["off_time"],
        "region": race["region"],
        "course": race["course"],
        "race_name": race["race_name"],
        "race_status": race["race_status"],
        "participants": participants,
    }


def run_race_live_offline_fixture(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    fixture_root: str,
    configured_mode: str,
) -> dict[str, Any]:
    """Run one claimed event from a bounded local fixture; this function never uses HTTP."""
    now = timezone.now()
    if configured_mode != "offline_fixture":
        return _failure(
            reason="runner_mode_invalid",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    source = RaceResultSourceIdentity.objects.filter(
        event_id=event_id,
        source_key=_SOURCE_KEY,
    ).first()
    if source is None:
        return _failure(
            reason="source_identity_missing",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    fixture_path = _safe_fixture_path(fixture_root, source.external_race_id)
    if fixture_path is None:
        return _failure(
            reason="unsafe_fixture_identity",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    try:
        with fixture_path.open("rb") as fixture_file:
            raw_fixture = fixture_file.read(_MAX_FIXTURE_BYTES + 1)
    except FileNotFoundError:
        return _failure(
            reason="fixture_missing",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    except OSError:
        return _failure(
            reason="fixture_unreadable",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    if len(raw_fixture) > _MAX_FIXTURE_BYTES:
        return _failure(
            reason="fixture_too_large",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    try:
        fixture = json.loads(raw_fixture.decode("utf-8"))
        if not isinstance(fixture, dict):
            raise ValueError("fixture container must be an object")
        snapshot = parse_the_racing_api_offline_fixture(fixture)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        RecursionError,
    ):
        return _failure(
            reason="fixture_invalid",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    matching = [
        race
        for race in snapshot.races
        if race["external_race_id"] == source.external_race_id
    ]
    if len(matching) != 1 or snapshot.phase != "provisional":
        return _failure(
            reason="fixture_race_not_found" if not matching else "fixture_phase_unsupported",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    normalized_payload = _normalized_result_payload(matching[0])
    observation_decision = record_race_result_observation(
        source_identity_id=source.pk,
        observed_at=now,
        source_updated_at=None,
        parser_version="the_racing_api_fixture_v1",
        raw_sha256=hashlib.sha256(raw_fixture).hexdigest(),
        result_phase=snapshot.phase,
        normalized_payload=normalized_payload,
        field_provenance={"source": _SOURCE_KEY},
        parse_warnings=[],
        permission_classification="offline_fixture",
    )
    if not observation_decision.recorded or observation_decision.observation is None:
        return _failure(
            reason=f"observation_{observation_decision.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    apply_decision = apply_race_result_observation_revision(
        observation_id=observation_decision.observation.pk,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
        source_authority=source.result_authority,
        official_marker=False,
        identity_valid=True,
        payload_complete=True,
        manual_lock_conflict=False,
        project_current=False,
    )
    successful = apply_decision.applied or apply_decision.action == "replay"
    revision_id = apply_decision.revision.pk if apply_decision.revision else None
    result = {
        "processed": successful,
        "reason": "offline_fixture_applied" if successful else f"apply_{apply_decision.reason}",
        "event_id": event_id,
        "action": apply_decision.action,
        "revision_id": revision_id,
    }
    next_poll_at = now + timedelta(minutes=5)
    if successful:
        tracking_state = RaceEventLiveTracking.objects.filter(
            event_id=event_id
        ).values_list("state", flat=True).first()
        off_time = datetime.fromisoformat(
            matching[0]["off_time"].replace("Z", "+00:00")
        )
        calculated_next_poll_at = calculate_race_live_next_poll_at(
            off_time=off_time,
            now=now,
            state=tracking_state,
        )
        next_poll_at = calculated_next_poll_at
    return _checkpoint_result(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
        success=successful,
        next_poll_at=next_poll_at,
        checkpoint_payload={
            "status": "succeeded" if successful else "failed",
            "reason": result["reason"],
            "fixture_payload_sha256": snapshot.payload_sha256,
            "action": apply_decision.action,
            "revision_id": revision_id,
        },
        observation_sha256=(
            observation_decision.observation.normalized_sha256 if successful else ""
        ),
        result=result,
    )


def _current_claim_rejection_reason(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    now: datetime,
) -> str:
    control = RaceEventProjectionControl.objects.filter(event_id=event_id).first()
    if control is None:
        return "control_missing"
    if (
        control.write_owner != RaceEventProjectionWriteOwner.LIVE
        or control.owner_generation != expected_owner_generation
    ):
        return "owner_mismatch"
    tracking = RaceEventLiveTracking.objects.filter(event_id=event_id).first()
    if tracking is None:
        return "tracking_missing"
    if (
        tracking.claim_generation != expected_claim_generation
        or tracking.active_attempt_token != attempt_token
    ):
        return "claim_mismatch"
    if tracking.claim_expires_at is None:
        return "claim_missing_expiry"
    if tracking.claim_expires_at <= now:
        return "claim_expired"
    return ""


def _apply_live_result_race(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    source: RaceResultSourceIdentity,
    normalized_race: dict[str, Any],
    raw_sha256: str,
    response_sha256: str,
    now: datetime,
    parser_version: str = "the_racing_api_free_v2",
) -> dict[str, Any]:
    normalized_payload = _normalized_result_payload(normalized_race)
    observation_decision = record_race_result_observation(
        source_identity_id=source.pk,
        observed_at=now,
        source_updated_at=None,
        parser_version=parser_version,
        raw_sha256=raw_sha256,
        result_phase="provisional",
        normalized_payload=normalized_payload,
        field_provenance={"source": _SOURCE_KEY},
        parse_warnings=[],
        permission_classification="licensed_api_automation",
    )
    if not observation_decision.recorded or observation_decision.observation is None:
        return _failure(
            reason=f"observation_{observation_decision.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    apply_decision = apply_race_result_observation_revision(
        observation_id=observation_decision.observation.pk,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
        source_authority=source.result_authority,
        official_marker=False,
        identity_valid=True,
        payload_complete=True,
        manual_lock_conflict=False,
        project_current=False,
    )
    if not apply_decision.applied and apply_decision.action != "replay":
        return _failure(
            reason=f"apply_{apply_decision.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    admission = admit_race_live_publication(
        observation_id=observation_decision.observation.pk,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
    )
    if not admission.applied and admission.action != "replay":
        if admission.reason == "shadow_only":
            tracking_state = (
                RaceEventLiveTracking.objects.filter(event_id=event_id)
                .values_list("state", flat=True)
                .first()
            )
            next_poll_at = calculate_race_live_next_poll_at(
                off_time=datetime.fromisoformat(
                    normalized_race["off_time"].replace("Z", "+00:00")
                ),
                now=now,
                state=tracking_state,
            )
            revision = admission.revision or apply_decision.revision
            return _checkpoint_result(
                event_id=event_id,
                expected_owner_generation=expected_owner_generation,
                expected_claim_generation=expected_claim_generation,
                attempt_token=attempt_token,
                now=now,
                success=True,
                next_poll_at=next_poll_at,
                checkpoint_payload={
                    "status": "shadow_applied",
                    "reason": "the_racing_api_shadow_applied",
                    "response_sha256": response_sha256,
                    "revision_id": (
                        revision.pk if revision is not None else None
                    ),
                },
                observation_sha256=(
                    observation_decision.observation.normalized_sha256
                ),
                result={
                    "processed": True,
                    "reason": "the_racing_api_shadow_applied",
                    "event_id": event_id,
                    "action": admission.action,
                    "revision_id": (
                        revision.pk if revision is not None else None
                    ),
                },
            )
        return _failure(
            reason=f"admission_{admission.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    next_poll_at = calculate_race_live_next_poll_at(
        off_time=datetime.fromisoformat(
            normalized_race["off_time"].replace("Z", "+00:00")
        ),
        now=now,
        state="provisional_result",
    )
    revision = admission.revision or apply_decision.revision
    return _checkpoint_result(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
        success=True,
        next_poll_at=next_poll_at,
        checkpoint_payload={
            "status": "provisional_published",
            "reason": "the_racing_api_provisional_published",
            "response_sha256": response_sha256,
            "revision_id": revision.pk if revision is not None else None,
        },
        observation_sha256=observation_decision.observation.normalized_sha256,
        result={
            "processed": True,
            "reason": "the_racing_api_provisional_published",
            "event_id": event_id,
            "action": admission.action,
            "revision_id": revision.pk if revision is not None else None,
        },
    )


def _run_v2_region_racecard_refresh(
    *,
    event: RaceEvent,
    registry: dict[str, Any],
    registry_digest: str,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    username: str,
    password: str,
    now: datetime,
    transport,
    clock,
) -> dict[str, Any]:
    clock_fn = timezone.now if clock is None else clock
    try:
        event_timezone = ZoneInfo(event.timezone_name)
        provider_date = now.astimezone(event_timezone).date()
        day_offset = (event.local_date - provider_date).days
        if day_offset not in {0, 1}:
            raise PermissionError("racecard refresh date is outside window")
        day = "today" if day_offset == 0 else "tomorrow"
        region_code = registry["allowed_region_codes"][event.country_region]
    except (
        KeyError,
        TypeError,
        ValueError,
        PermissionError,
        ZoneInfoNotFoundError,
    ):
        return _failure(
            reason="racecard_refresh_route_rejected",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    fetch_time = now

    def fetch_snapshot() -> dict[str, Any]:
        nonlocal fetch_time
        reservation = reserve_race_live_host_request(host=_HOST, now=now)
        if not reservation.reserved:
            raise _ResultsPageFetchError(
                f"host_reservation_{reservation.reason}",
                now=now,
            )
        try:
            url = build_the_racing_api_route_url(
                registry=registry,
                route_name="racecards_free",
                region=event.country_region,
                day=day,
                limit=500,
                skip=0,
            )
            response = transport(
                endpoint_name=f"racecards_sync_{day}",
                url=url,
                username=username,
                password=password,
                timeout_seconds=15,
                max_response_bytes=_MAX_FIXTURE_BYTES,
                allow_redirects=False,
            )
            fetch_time = clock_fn()
            if (
                not isinstance(fetch_time, datetime)
                or timezone.is_naive(fetch_time)
                or (clock is not None and fetch_time < now)
            ):
                raise _ResultsPageFetchError(
                    "fresh_clock_invalid",
                    now=now,
                )
            if fetch_time < now:
                fetch_time = now
            if response.redirect_url is not None or (
                isinstance(response.status_code, int)
                and 300 <= response.status_code < 400
            ):
                raise ValueError("redirect rejected")
            if response.status_code != 200:
                raise ValueError("http error")
            if (
                not isinstance(response.body, bytes)
                or len(response.body) > _MAX_FIXTURE_BYTES
                or not isinstance(response.content_type, str)
                or response.content_type.split(";", 1)[0].strip().lower()
                not in {"application/json", "application/problem+json"}
            ):
                raise ValueError("response contract rejected")
            payload = json.loads(response.body)
            if (
                isinstance(payload.get("total"), bool)
                or not isinstance(payload.get("total"), int)
                or payload["total"] < 0
                or payload["total"] > 500
                or payload.get("limit") != 500
                or payload.get("skip") != 0
            ):
                raise ValueError("racecard metadata rejected")
            normalized = parse_the_racing_api_live_racecards_payload(payload)
            races = tuple(
                race
                for race in normalized.races
                if race["region"].strip().casefold() == region_code
            )
        except _ResultsPageFetchError:
            raise
        except Exception as exc:
            outcome = record_race_live_host_outcome(
                host=_HOST,
                now=fetch_time,
                success=False,
                error_code="the_racing_api_payload_invalid",
                circuit_threshold=3,
                circuit_seconds=300,
                expected_reservation_version=(
                    reservation.reservation_version
                ),
            )
            reason = (
                "the_racing_api_payload_invalid"
                if outcome.recorded
                else f"host_outcome_{outcome.reason}"
            )
            raise _ResultsPageFetchError(reason, now=fetch_time) from exc
        outcome = record_race_live_host_outcome(
            host=_HOST,
            now=fetch_time,
            success=True,
            error_code="",
            circuit_threshold=3,
            circuit_seconds=300,
            expected_reservation_version=reservation.reservation_version,
        )
        if not outcome.recorded:
            raise _ResultsPageFetchError(
                f"host_outcome_{outcome.reason}",
                now=fetch_time,
            )
        return {
            "payload_sha256": hashlib.sha256(response.body).hexdigest(),
            "races": races,
        }

    try:
        snapshot = get_or_fetch_region_racecard_snapshot(
            source_key=_SOURCE_KEY,
            provider_date=provider_date,
            registry_digest=registry_digest,
            endpoint_contract_version="racecards-free-v2",
            region_code=region_code,
            day=day,
            fetch_snapshot=fetch_snapshot,
            fetched_at=now,
        )
        fresh_now = clock_fn()
    except _ResultsPageFetchError as exc:
        return _failure(
            reason=exc.reason,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=exc.now,
        )
    except (KeyError, TypeError, ValueError, PermissionError):
        return _failure(
            reason="the_racing_api_payload_invalid",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    if (
        not isinstance(fresh_now, datetime)
        or timezone.is_naive(fresh_now)
        or (clock is not None and fresh_now < now)
    ):
        return {
            "processed": False,
            "reason": "fresh_clock_invalid",
            "event_id": event_id,
        }
    if fresh_now < now:
        fresh_now = now
    claim_rejection = _current_claim_rejection_reason(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=fresh_now,
    )
    if claim_rejection:
        return _failure(
            reason=claim_rejection,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
        )
    racecard = snapshot["races"].get(
        RaceResultSourceIdentity.objects.filter(
            event_id=event_id,
            source_key=_SOURCE_KEY,
        ).values_list("external_race_id", flat=True).first()
    )
    if racecard is None:
        return _checkpoint_result(
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
            success=True,
            next_poll_at=calculate_race_live_next_poll_at(
                off_time=event.race_datetime,
                now=fresh_now,
                state=RaceEventLiveState.RACECARD_READY,
            ),
            checkpoint_payload={
                "status": "racecard_not_found",
                "reason": "the_racing_api_racecard_not_found",
                "response_sha256": snapshot["payload_sha256"],
            },
            observation_sha256=snapshot["payload_sha256"],
            result={
                "processed": False,
                "reason": "the_racing_api_racecard_not_found",
                "event_id": event_id,
            },
        )
    refresh = refresh_race_live_racecard(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=fresh_now,
        normalized_racecard=racecard,
        raw_sha256=snapshot["payload_sha256"],
    )
    return {
        "processed": refresh.applied,
        "reason": refresh.reason,
        "event_id": event_id,
        "revision_id": refresh.revision_id,
        "replayed": refresh.replayed,
    }


def _run_v2_region_results(
    *,
    event: RaceEvent,
    source: RaceResultSourceIdentity,
    registry: dict[str, Any],
    registry_digest: str,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    username: str,
    password: str,
    now: datetime,
    transport,
    clock,
    sleeper,
) -> dict[str, Any]:
    clock_fn = timezone.now if clock is None else clock
    sleep_fn = time.sleep if sleeper is None else sleeper
    fetch_budget_seconds = getattr(
        settings,
        "RACE_LIVE_RESULTS_FETCH_BUDGET_SECONDS",
        165,
    )
    if (
        isinstance(fetch_budget_seconds, bool)
        or not isinstance(fetch_budget_seconds, int)
        or fetch_budget_seconds <= 0
    ):
        return _failure(
            reason="results_fetch_budget_invalid",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    fetch_deadline = now + timedelta(seconds=fetch_budget_seconds)
    try:
        provider_timezone = ZoneInfo(event.timezone_name)
        provider_date = now.astimezone(provider_timezone).date()
        region_code = registry["allowed_region_codes"][event.country_region]
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        return _failure(
            reason="results_region_route_rejected",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    def _fresh_time(*, minimum: datetime) -> datetime:
        fresh = clock_fn()
        if not isinstance(fresh, datetime) or timezone.is_naive(fresh):
            raise _ResultsPageFetchError(
                "fresh_clock_invalid",
                now=minimum,
            )
        if fresh < minimum:
            if clock is not None:
                raise _ResultsPageFetchError(
                    "fresh_clock_before_start",
                    now=minimum,
                )
            return minimum
        return fresh

    def fetch_page(*, skip: int, limit: int) -> dict[str, Any]:
        page_now = _fresh_time(minimum=now)
        remaining_seconds = (fetch_deadline - page_now).total_seconds()
        if remaining_seconds <= 0:
            raise _ResultsPageFetchError(
                "results_pagination_deadline_exceeded",
                now=page_now,
            )
        reservation = reserve_race_live_host_request(host=_HOST, now=page_now)
        if (
            not reservation.reserved
            and reservation.reason == "rate_limited"
            and reservation.next_allowed_at is not None
        ):
            delay_seconds = (
                reservation.next_allowed_at - page_now
            ).total_seconds()
            if 0 < delay_seconds <= 2:
                sleep_fn(delay_seconds)
                page_now = _fresh_time(minimum=reservation.next_allowed_at)
                reservation = reserve_race_live_host_request(
                    host=_HOST,
                    now=page_now,
                )
        if not reservation.reserved:
            raise _ResultsPageFetchError(
                f"host_reservation_{reservation.reason}",
                now=page_now,
            )
        try:
            request_url = build_the_racing_api_route_url(
                registry=registry,
                route_name="results_today_free",
                region=event.country_region,
                limit=limit,
                skip=skip,
            )
        except (KeyError, TypeError, ValueError, PermissionError) as exc:
            raise _ResultsPageFetchError(
                "results_region_route_rejected",
                now=page_now,
            ) from exc

        failure_reason = ""
        response = None
        remaining_seconds = (fetch_deadline - page_now).total_seconds()
        if remaining_seconds <= 0:
            raise _ResultsPageFetchError(
                "results_pagination_deadline_exceeded",
                now=page_now,
            )
        try:
            response = transport(
                endpoint_name="results_today",
                url=request_url,
                username=username,
                password=password,
                timeout_seconds=min(15, remaining_seconds),
                max_response_bytes=_MAX_FIXTURE_BYTES,
                allow_redirects=False,
            )
        except Exception:
            failure_reason = "the_racing_api_transport_error"
        fresh_now = _fresh_time(minimum=page_now)
        if fresh_now >= fetch_deadline:
            failure_reason = "results_pagination_deadline_exceeded"
        payload = None
        normalized = None
        if not failure_reason:
            try:
                if response.redirect_url is not None or (
                    isinstance(response.status_code, int)
                    and 300 <= response.status_code < 400
                ):
                    failure_reason = "the_racing_api_redirect_rejected"
                elif response.status_code != 200:
                    failure_reason = "the_racing_api_http_error"
                elif (
                    not isinstance(response.body, bytes)
                    or len(response.body) > _MAX_FIXTURE_BYTES
                ):
                    failure_reason = "the_racing_api_response_too_large"
                elif (
                    not isinstance(response.content_type, str)
                    or response.content_type.split(";", 1)[0].strip().lower()
                    not in {"application/json", "application/problem+json"}
                ):
                    failure_reason = "the_racing_api_content_type_rejected"
                else:
                    payload = json.loads(response.body)
                    if (
                        isinstance(payload.get("total"), bool)
                        or not isinstance(payload.get("total"), int)
                        or payload["total"] < skip
                        or payload.get("limit") != limit
                        or payload.get("skip") != skip
                    ):
                        failure_reason = (
                            "results_pagination_metadata_drift"
                        )
                    else:
                        raw_results = payload.get("results")
                        expected_page_size = min(
                            limit,
                            payload["total"] - skip,
                        )
                        if (
                            not isinstance(raw_results, list)
                            or len(raw_results) != expected_page_size
                        ):
                            failure_reason = (
                                "results_pagination_incomplete"
                            )
                        else:
                            normalized = (
                                parse_the_racing_api_live_results_payload(
                                    payload
                                )
                            )
            except (
                AttributeError,
                UnicodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
                PermissionError,
                OverflowError,
                RecursionError,
            ):
                failure_reason = "the_racing_api_payload_invalid"

        outcome = record_race_live_host_outcome(
            host=_HOST,
            now=fresh_now,
            success=not failure_reason,
            error_code=failure_reason,
            circuit_threshold=3,
            circuit_seconds=300,
            expected_reservation_version=reservation.reservation_version,
        )
        if not outcome.recorded:
            raise _ResultsPageFetchError(
                f"host_outcome_{outcome.reason}",
                now=fresh_now,
            )
        if failure_reason or response is None or normalized is None:
            raise _ResultsPageFetchError(
                failure_reason or "the_racing_api_payload_invalid",
                now=fresh_now,
            )
        races = tuple(
            race
            for race in normalized.races
            if race["region"].strip().casefold() == region_code
        )
        return {
            "total": payload["total"],
            "skip": skip,
            "limit": limit,
            "payload_sha256": hashlib.sha256(response.body).hexdigest(),
            "races": races,
        }

    try:
        snapshot = get_or_fetch_region_results_snapshot(
            source_key=_SOURCE_KEY,
            provider_date=provider_date,
            registry_digest=registry_digest,
            endpoint_contract_version="results-free-v2",
            region_code=region_code,
            fetch_page=fetch_page,
            fetched_at=now,
        )
        fresh_now = _fresh_time(minimum=now)
        if fresh_now >= fetch_deadline:
            raise _ResultsPageFetchError(
                "results_pagination_deadline_exceeded",
                now=fresh_now,
            )
    except _ResultsPageFetchError as exc:
        return _failure(
            reason=exc.reason,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=exc.now,
            checkpoint_details=_pagination_checkpoint_payload(
                reason=exc.reason,
            ),
        )
    except _ResultsPaginationError as exc:
        return _failure(
            reason=exc.reason,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
            checkpoint_details=_pagination_checkpoint_payload(
                reason=exc.reason,
                details=exc.details,
            ),
        )
    except (KeyError, TypeError, ValueError, PermissionError):
        return _failure(
            reason="the_racing_api_payload_invalid",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    claim_rejection = _current_claim_rejection_reason(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=fresh_now,
    )
    if claim_rejection:
        return _failure(
            reason=claim_rejection,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
        )
    normalized_race = snapshot["races"].get(source.external_race_id)
    if normalized_race is None:
        return _checkpoint_result(
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
            success=True,
            next_poll_at=fresh_now + timedelta(minutes=3),
            checkpoint_payload={
                "status": "result_not_found",
                "reason": "the_racing_api_result_not_found",
                "response_sha256": snapshot["payload_sha256"],
            },
            observation_sha256=snapshot["payload_sha256"],
            result={
                "processed": False,
                "reason": "the_racing_api_result_not_found",
                "event_id": event_id,
            },
        )
    return _apply_live_result_race(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        source=source,
        normalized_race=normalized_race,
        raw_sha256=snapshot["payload_sha256"],
        response_sha256=snapshot["payload_sha256"],
        now=fresh_now,
    )


def run_race_live_the_racing_api_free(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    secret_env_file: str,
    registry_file: str,
    expected_registry_sha256: str,
    now: datetime,
    transport,
    clock=None,
    sleeper=None,
) -> dict[str, Any]:
    """Fetch and publish one claimed event from the fixed TRA Free results endpoint."""
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return {
            "processed": False,
            "reason": "invalid_start_time",
            "event_id": event_id,
        }
    tracking_state = (
        RaceEventLiveTracking.objects.filter(event_id=event_id)
        .values_list("state", flat=True)
        .first()
    )
    event = RaceEvent.objects.filter(pk=event_id).first()
    pre_off_refresh = bool(
        tracking_state == "racecard_ready"
        and event is not None
        and event.race_datetime is not None
        and now < event.race_datetime
    )
    if tracking_state == "racecard_ready":
        if not pre_off_refresh:
            pre_off = checkpoint_or_promote_race_event_live_pre_off(
                event_id=event_id,
                expected_owner_generation=expected_owner_generation,
                expected_claim_generation=expected_claim_generation,
                attempt_token=attempt_token,
                now=now,
            )
            if not pre_off.applied:
                return {
                    "processed": False,
                    "reason": f"pre_off_{pre_off.reason}",
                    "event_id": event_id,
                }
    try:
        registry, registry_digest = read_the_racing_api_automation_registry(
            registry_file=registry_file,
            expected_registry_sha256=expected_registry_sha256,
            now=now,
        )
    except Exception:
        return _failure(
            reason="source_registry_rejected",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    if pre_off_refresh and registry.get("schema_version", 1) == 1:
        pre_off = checkpoint_or_promote_race_event_live_pre_off(
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
        return {
            "processed": False,
            "reason": (
                pre_off.reason
                if pre_off.applied
                else f"pre_off_{pre_off.reason}"
            ),
            "event_id": event_id,
        }

    source = RaceResultSourceIdentity.objects.filter(
        event_id=event_id,
        source_key=_SOURCE_KEY,
    ).first()
    if source is None:
        return _failure(
            reason="source_identity_missing",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    if source.host != _HOST:
        return _failure(
            reason="source_host_rejected",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    control = RaceEventProjectionControl.objects.filter(event_id=event_id).first()
    historical_handoff_complete = bool(
        control
        and control.write_owner == RaceEventProjectionWriteOwner.LIVE
        and control.owner_generation == expected_owner_generation
    )
    network_permission = resolve_race_source_network_permission(
        mode="production",
        terms_status=source.terms_status,
        automation_allowed=source.automation_allowed,
        proof_network_allowed=source.proof_network_allowed,
        valid_until=source.valid_until,
        evidence_sha256=source.evidence_sha256,
        registry_digest=source.registry_digest,
        expected_registry_digest=registry_digest,
        manifest_approved=True,
        request_budget=1,
        historical_handoff_complete=historical_handoff_complete,
        now=now,
    )
    if not network_permission.allowed:
        return _failure(
            reason=f"source_permission_{network_permission.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    claim_rejection = _current_claim_rejection_reason(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
    )
    if claim_rejection:
        return _failure(
            reason=claim_rejection,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    try:
        username, password = _read_secret(secret_env_file)
    except Exception:
        return _failure(
            reason="source_secret_rejected",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    if registry.get("schema_version") == 2:
        if pre_off_refresh:
            return _run_v2_region_racecard_refresh(
                event=event,
                registry=registry,
                registry_digest=registry_digest,
                event_id=event_id,
                expected_owner_generation=expected_owner_generation,
                expected_claim_generation=expected_claim_generation,
                attempt_token=attempt_token,
                username=username,
                password=password,
                now=now,
                transport=transport,
                clock=clock,
            )
        return _run_v2_region_results(
            event=event,
            source=source,
            registry=registry,
            registry_digest=registry_digest,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            username=username,
            password=password,
            now=now,
            transport=transport,
            clock=clock,
            sleeper=sleeper,
        )

    reservation = reserve_race_live_host_request(host=_HOST, now=now)
    if not reservation.reserved:
        return _failure(
            reason=f"host_reservation_{reservation.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    response = None
    failure_reason = ""
    request_url = _RESULTS_URL
    endpoint_name = "results_today"
    if pre_off_refresh:
        try:
            event_timezone = ZoneInfo(event.timezone_name)
            provider_date = now.astimezone(event_timezone).date()
            day_offset = (event.local_date - provider_date).days
            if day_offset not in {0, 1}:
                raise PermissionError("racecard refresh date is outside window")
            day = "today" if day_offset == 0 else "tomorrow"
            request_url = build_the_racing_api_route_url(
                registry=registry,
                route_name="racecards_free",
                region=event.country_region,
                day=day,
                limit=500,
                skip=0,
            )
            endpoint_name = f"racecards_sync_{day}"
        except (TypeError, ValueError, PermissionError, KeyError):
            return _failure(
                reason="racecard_refresh_route_rejected",
                event_id=event_id,
                expected_owner_generation=expected_owner_generation,
                expected_claim_generation=expected_claim_generation,
                attempt_token=attempt_token,
                now=now,
            )
    try:
        response = transport(
            endpoint_name=endpoint_name,
            url=request_url,
            username=username,
            password=password,
            timeout_seconds=15,
            max_response_bytes=_MAX_FIXTURE_BYTES,
            allow_redirects=False,
        )
    except Exception:
        failure_reason = "the_racing_api_transport_error"

    try:
        clock_fn = timezone.now if clock is None else clock
        fresh_now = clock_fn()
    except Exception:
        return {
            "processed": False,
            "reason": "fresh_clock_error",
            "event_id": event_id,
        }
    if not isinstance(fresh_now, datetime) or timezone.is_naive(fresh_now):
        return {
            "processed": False,
            "reason": "fresh_clock_invalid",
            "event_id": event_id,
        }
    if fresh_now < now:
        if clock is not None:
            return {
                "processed": False,
                "reason": "fresh_clock_before_start",
                "event_id": event_id,
            }
        fresh_now = now

    snapshot = None
    if not failure_reason:
        try:
            if response.redirect_url is not None or (
                isinstance(response.status_code, int)
                and 300 <= response.status_code < 400
            ):
                failure_reason = "the_racing_api_redirect_rejected"
            elif response.status_code != 200:
                failure_reason = "the_racing_api_http_error"
            elif (
                not isinstance(response.body, bytes)
                or len(response.body) > _MAX_FIXTURE_BYTES
            ):
                failure_reason = "the_racing_api_response_too_large"
            elif (
                not isinstance(response.content_type, str)
                or response.content_type.split(";", 1)[0].strip().lower()
                not in {"application/json", "application/problem+json"}
            ):
                failure_reason = "the_racing_api_content_type_rejected"
            else:
                payload = json.loads(response.body)
                snapshot = (
                    parse_the_racing_api_live_racecards_payload(payload)
                    if pre_off_refresh
                    else parse_the_racing_api_live_results_payload(payload)
                )
        except (
            AttributeError,
            UnicodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ):
            failure_reason = "the_racing_api_payload_invalid"

    matching = []
    if snapshot is not None:
        matching = [
            race
            for race in snapshot.races
            if race["external_race_id"] == source.external_race_id
        ]
        if len(matching) > 1:
            failure_reason = "the_racing_api_result_ambiguous"

    outcome = record_race_live_host_outcome(
        host=_HOST,
        now=fresh_now,
        success=not failure_reason,
        error_code=failure_reason,
        circuit_threshold=3,
        circuit_seconds=300,
        expected_reservation_version=reservation.reservation_version,
    )
    if not outcome.recorded:
        return _failure(
            reason=f"host_outcome_{outcome.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
        )
    if failure_reason:
        return _failure(
            reason=failure_reason,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
        )

    claim_rejection = _current_claim_rejection_reason(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=fresh_now,
    )
    if claim_rejection:
        return _failure(
            reason=claim_rejection,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
        )

    if not matching:
        next_poll_at = fresh_now + timedelta(minutes=3)
        missing_reason = "the_racing_api_result_not_found"
        status = "result_not_found"
        if pre_off_refresh:
            next_poll_at = calculate_race_live_next_poll_at(
                off_time=event.race_datetime,
                now=fresh_now,
                state=tracking_state,
            )
            missing_reason = "the_racing_api_racecard_not_found"
            status = "racecard_not_found"
        return _checkpoint_result(
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
            success=True,
            next_poll_at=next_poll_at,
            checkpoint_payload={
                "status": status,
                "reason": missing_reason,
                "response_sha256": snapshot.payload_sha256,
            },
            observation_sha256=snapshot.payload_sha256,
            result={
                "processed": False,
                "reason": missing_reason,
                "event_id": event_id,
            },
        )

    raw_sha256 = hashlib.sha256(response.body).hexdigest()
    if pre_off_refresh:
        refresh = refresh_race_live_racecard(
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
            normalized_racecard=matching[0],
            raw_sha256=raw_sha256,
        )
        return {
            "processed": refresh.applied,
            "reason": refresh.reason,
            "event_id": event_id,
            "revision_id": refresh.revision_id,
            "replayed": refresh.replayed,
        }
    return _apply_live_result_race(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        source=source,
        normalized_race=matching[0],
        raw_sha256=raw_sha256,
        response_sha256=snapshot.payload_sha256,
        now=fresh_now,
        parser_version="the_racing_api_free_v1",
    )

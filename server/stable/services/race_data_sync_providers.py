from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from stable import models
from stable.services.race_data_sync_pipeline import (
    RaceDataResolvedRoute,
    RaceDataSyncFlags,
    normalize_racecard_observation,
    reconcile_racecard_observation,
    reserve_race_data_transport_capacity,
    resolve_race_data_provider_route,
)
from stable.services.race_data_sync_results import (
    apply_data_sync_result_observation,
)
from stable.services.race_events import (
    record_race_live_host_outcome,
    record_race_result_observation,
    reserve_race_live_host_request,
)
from stable.services.race_live_fixtures import (
    parse_the_racing_api_live_racecards_payload,
    parse_the_racing_api_live_results_payload,
)
from stable.services.race_live_racecard_sync import (
    get_normalized_accepted_race_names,
    normalize_identity_text,
)
from stable.services.race_live_source_proof import (
    _read_secret,
    build_the_racing_api_route_url,
    read_the_racing_api_automation_registry,
    the_racing_api_transport,
)


_HOST = "api.theracingapi.com"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_REFERENCE_SOURCE_KEYS = {
    "sporting_life": "reference_sporting_life",
    "zeturf": "reference_zeturf",
    "horse_racing_nation": "reference_horse_racing_nation",
}
_PERSISTED_OFFICIAL_SOURCES = {
    "hkjc": models.ExternalDataSource.HKJC,
    "france_galop": models.ExternalDataSource.FRANCE_GALOP,
}


@dataclass(frozen=True)
class ProviderSyncOutcome:
    success: bool
    reason_code: str
    observation_hashes: dict[str, str]
    source_updated_at_by_kind: dict[str, datetime | None]
    applied_kinds: tuple[str, ...] = ()
    not_found_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderIdentityDiscoveryOutcome:
    success: bool
    reason_code: str
    request_count: int
    candidate_event_count: int
    created_source_count: int
    adopted_source_count: int
    ambiguous_event_count: int
    unmatched_event_count: int


class _ProviderSyncError(Exception):
    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


def _event_contract_region(event: models.RaceEvent) -> str:
    direct = {
        models.RacingRegion.HONG_KONG: "hong_kong",
        models.RacingRegion.UNITED_KINGDOM: "united_kingdom",
        models.RacingRegion.FRANCE: "france",
        models.RacingRegion.UNITED_STATES: "united_states",
    }.get(event.country_region)
    if direct:
        return direct
    refs = event.source_refs if isinstance(event.source_refs, dict) else {}
    marker = str(refs.get("race_data_region") or "").strip()
    if event.country_region == models.RacingRegion.JAPAN:
        if marker in {"japan_jra", "japan_nar"}:
            return marker
        return "japan_jra"
    if event.country_region == models.RacingRegion.OTHER and marker == "ireland":
        return marker
    return ""


def _registry_region(*, event_region: str, contract_region: str) -> str:
    if contract_region == "ireland":
        return "ireland"
    if contract_region in {"japan_jra", "japan_nar"}:
        return "japan"
    return event_region


def _match_discovery_race(
    *,
    event: models.RaceEvent,
    races: tuple[dict[str, Any], ...],
    expected_region_code: str,
) -> tuple[dict[str, Any] | None, str]:
    try:
        event_timezone = ZoneInfo(event.timezone_name)
    except (KeyError, ValueError):
        return None, "event_timezone_invalid"
    approved_names = get_normalized_accepted_race_names(event)
    normalized_course = normalize_identity_text(event.racecourse)
    matches = []
    for race in races:
        raw_off_time = race.get("off_time")
        try:
            off_time = datetime.fromisoformat(
                str(raw_off_time).replace("Z", "+00:00")
            )
        except ValueError:
            continue
        if timezone.is_naive(off_time):
            continue
        if (
            str(race.get("region") or "").casefold()
            != expected_region_code.casefold()
            or off_time.astimezone(event_timezone).date() != event.local_date
            or normalize_identity_text(race.get("course")) != normalized_course
            or normalize_identity_text(race.get("race_name")) not in approved_names
        ):
            continue
        matches.append(race)
    if len(matches) == 1:
        return matches[0], "matched"
    if matches:
        return None, "racecard_ambiguous"
    return None, "racecard_not_found"


def _fair_discovery_bucket_order(
    *, buckets: dict[tuple[str, str], list[tuple[Any, ...]]], now: datetime
) -> tuple[tuple[tuple[str, str], list[tuple[Any, ...]]], ...]:
    """Rotate a stable bucket order so a bounded hourly run cannot starve regions."""

    ordered = sorted(buckets.items())
    if not ordered:
        return ()
    offset = int(now.timestamp() // 3600) % len(ordered)
    return tuple((*ordered[offset:], *ordered[:offset]))


def discover_the_racing_api_source_identities(
    *,
    now: datetime,
    transport: Callable[..., Any] = the_racing_api_transport,
    clock: Callable[[], datetime] = timezone.now,
    sleeper: Callable[[float], Any] = time.sleep,
) -> ProviderIdentityDiscoveryOutcome:
    """Bind future events to an exact TRA race ID without per-race review.

    Only deterministic name + course + local-date matches are admitted.  One
    hourly invocation is bounded by the reviewed TRA registry request budget.
    """

    flags = RaceDataSyncFlags.from_settings()
    required_kinds = tuple(
        kind
        for kind in (
            models.RaceDataSyncDataKind.RACE_TIME,
            models.RaceDataSyncDataKind.RACECARD,
            models.RaceDataSyncDataKind.RESULT,
        )
        if kind in flags.data_kinds
    )
    if (
        not flags.enabled
        or not flags.allow_network
        or "the_racing_api" not in flags.providers
        or not required_kinds
    ):
        return ProviderIdentityDiscoveryOutcome(
            False, "provider_discovery_disabled", 0, 0, 0, 0, 0, 0
        )
    candidate_events = list(
        models.RaceEvent.objects.filter(
            visibility_status=models.RaceEventVisibility.PUBLISHED,
            status=models.RaceEventStatus.SCHEDULED,
            local_date__gte=now.date() - timedelta(days=1),
            local_date__lte=now.date() + timedelta(days=2),
        )
        .select_related("race_series", "major_race_event")
        .prefetch_related("aliases", "race_series__names", "source_identities")
        .order_by("local_date", "id")
    )
    candidates = []
    for event in candidate_events:
        if isinstance(event.manual_lock_flags, dict) and any(
            event.manual_lock_flags.values()
        ):
            continue
        contract_region = _event_contract_region(event)
        if contract_region not in flags.regions:
            continue
        existing = [
            source
            for source in event.source_identities.all()
            if source.source_key == "the_racing_api"
        ]
        if any(
            source.region_code == contract_region
            and source.identity_namespace == "the_racing_api-race-v1"
            for source in existing
        ):
            continue
        route = resolve_race_data_provider_route(
            provider="the_racing_api",
            region=contract_region,
            identity_namespace="the_racing_api-race-v1",
            data_kinds=required_kinds,
        )
        if route is None:
            continue
        candidates.append((event, contract_region, route, existing))
    if not candidates:
        return ProviderIdentityDiscoveryOutcome(
            True, "no_candidates", 0, 0, 0, 0, 0, 0
        )

    first_route = candidates[0][2]
    try:
        registry, registry_digest = read_the_racing_api_automation_registry(
            registry_file=settings.RACE_LIVE_TRA_REGISTRY_FILE,
            expected_registry_sha256=first_route.proof_digest,
            now=now,
        )
        if registry_digest != first_route.proof_digest:
            raise PermissionError("registry drift")
        username, password = _read_secret(settings.RACE_LIVE_TRA_SECRET_ENV_FILE)
        valid_until = datetime.fromisoformat(
            str(registry["valid_until"]).replace("Z", "+00:00")
        )
        with transaction.atomic():
            budget, created_budget = (
                models.RaceLiveHostBudget.objects.select_for_update().get_or_create(
                    host=_HOST,
                    defaults={
                        "min_interval_ms": first_route.minimum_interval_seconds
                        * 1000
                    },
                )
            )
            if (
                not created_budget
                and budget.min_interval_ms
                != first_route.minimum_interval_seconds * 1000
            ):
                raise PermissionError("host budget mismatch")
    except Exception:
        return ProviderIdentityDiscoveryOutcome(
            False,
            "source_runtime_contract_rejected",
            0,
            len(candidates),
            0,
            0,
            0,
            len(candidates),
        )

    buckets: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    for candidate in candidates:
        event = candidate[0]
        try:
            provider_date = now.astimezone(ZoneInfo(event.timezone_name)).date()
        except (KeyError, ValueError):
            continue
        offset = (event.local_date - provider_date).days
        if offset not in {0, 1}:
            continue
        provider_region = _registry_region(
            event_region=event.country_region,
            contract_region=candidate[1],
        )
        buckets.setdefault(
            (provider_region, "today" if offset == 0 else "tomorrow"), []
        ).append(candidate)

    created = 0
    adopted = 0
    ambiguous = 0
    unmatched = 0
    request_count = 0
    try:
        for (event_region, day), bucket in _fair_discovery_bucket_order(
            buckets=buckets,
            now=now,
        ):
            if request_count >= first_route.request_budget:
                break
            route = bucket[0][2]
            capacity = reserve_race_data_transport_capacity(
                provider="the_racing_api",
                region_code=event_region,
                now=now,
                proposed_requests=1,
                max_response_bytes_per_request=_MAX_RESPONSE_BYTES,
            )
            if not capacity.allowed:
                raise _ProviderSyncError(capacity.reason_code)
            url = build_the_racing_api_route_url(
                registry=registry,
                route_name="racecards_free",
                region=event_region,
                day=day,
                limit=500,
                skip=0,
            )
            payload, raw_sha256 = _fetch_json(
                transport=transport,
                endpoint_name=f"racecards_identity_{event_region}_{day}",
                url=url,
                username=username,
                password=password,
                now=now,
                clock=clock,
                sleeper=sleeper,
            )
            request_count += 1
            snapshot = parse_the_racing_api_live_racecards_payload(payload)
            expected_region_code = registry["allowed_region_codes"][event_region]
            for event, contract_region, route, existing in bucket:
                race, reason = _match_discovery_race(
                    event=event,
                    races=snapshot.races,
                    expected_region_code=expected_region_code,
                )
                if race is None:
                    if reason == "racecard_ambiguous":
                        ambiguous += 1
                    else:
                        unmatched += 1
                    continue
                external_id = race["external_race_id"]
                with transaction.atomic():
                    locked_event = models.RaceEvent.objects.select_for_update().get(
                        pk=event.pk
                    )
                    if models.RaceResultSourceIdentity.objects.filter(
                        source_key="the_racing_api",
                        external_race_id=external_id,
                    ).exclude(event=locked_event).exists():
                        ambiguous += 1
                        continue
                    locked_sources = list(
                        models.RaceResultSourceIdentity.objects.select_for_update()
                        .filter(event=locked_event, source_key="the_racing_api")[:2]
                    )
                    if len(locked_sources) > 1:
                        ambiguous += 1
                        continue
                    source = locked_sources[0] if locked_sources else None
                    identity_fields = {
                        "event_id": locked_event.pk,
                        "identity_discovery": "exact_name_course_local_date_v1",
                        "identity_namespace": "the_racing_api-race-v1",
                        "race_data_region": contract_region,
                        "source_response_sha256": raw_sha256,
                    }
                    values = {
                        "region_code": contract_region,
                        "identity_namespace": "the_racing_api-race-v1",
                        "external_race_id": external_id,
                        "canonical_url": url,
                        "host": _HOST,
                        "identity_fields": identity_fields,
                        "review_status": models.RaceLiveReviewStatus.APPROVED,
                        "result_authority": models.RaceResultSourceAuthority.SUPPLEMENTAL,
                        "reviewed_at": now,
                        "terms_status": models.RaceSourceTermsStatus.APPROVED,
                        "automation_allowed": True,
                        "proof_network_allowed": True,
                        "evidence_url": registry["evidence"]["terms_url"],
                        "evidence_sha256": route.proof_digest,
                        "valid_until": valid_until,
                        "registry_digest": route.registry_digest,
                    }
                    if source is None:
                        models.RaceResultSourceIdentity.objects.create(
                            event=locked_event, **values
                        )
                        created += 1
                    elif source.external_race_id == external_id:
                        for field_name, value in values.items():
                            setattr(source, field_name, value)
                        source.save(update_fields=tuple(values) + ("updated_at",))
                        adopted += 1
                    else:
                        ambiguous += 1
    except _ProviderSyncError as exc:
        return ProviderIdentityDiscoveryOutcome(
            False,
            exc.reason_code,
            request_count,
            len(candidates),
            created,
            adopted,
            ambiguous,
            unmatched,
        )
    except Exception:
        return ProviderIdentityDiscoveryOutcome(
            False,
            "provider_execution_failed",
            request_count,
            len(candidates),
            created,
            adopted,
            ambiguous,
            unmatched,
        )
    return ProviderIdentityDiscoveryOutcome(
        True,
        "complete",
        request_count,
        len(candidates),
        created,
        adopted,
        ambiguous,
        unmatched,
    )


def _safe_clock_value(
    *, clock: Callable[[], datetime], fallback: datetime
) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or timezone.is_naive(value) or value < fallback:
        return fallback
    return value


def _fetch_json(
    *,
    transport: Callable[..., Any],
    endpoint_name: str,
    url: str,
    username: str,
    password: str,
    now: datetime,
    clock: Callable[[], datetime],
    sleeper: Callable[[float], Any],
) -> tuple[dict[str, Any], str]:
    request_now = _safe_clock_value(clock=clock, fallback=now)
    reservation = reserve_race_live_host_request(host=_HOST, now=request_now)
    if (
        not reservation.reserved
        and reservation.reason == "rate_limited"
        and reservation.next_allowed_at is not None
    ):
        wait_seconds = max(
            0.0, (reservation.next_allowed_at - request_now).total_seconds()
        )
        if wait_seconds <= 3.0:
            sleeper(wait_seconds)
            request_now = _safe_clock_value(
                clock=clock, fallback=reservation.next_allowed_at
            )
            reservation = reserve_race_live_host_request(
                host=_HOST, now=request_now
            )
    if not reservation.reserved:
        raise _ProviderSyncError(f"host_reservation_{reservation.reason}")
    success = False
    error_code = "provider_response_invalid"
    try:
        response = transport(
            endpoint_name=endpoint_name,
            url=url,
            username=username,
            password=password,
            timeout_seconds=15,
            max_response_bytes=_MAX_RESPONSE_BYTES,
            allow_redirects=False,
        )
        if (
            response.redirect_url is not None
            or response.status_code != 200
            or not isinstance(response.body, bytes)
            or len(response.body) > _MAX_RESPONSE_BYTES
            or response.content_type.split(";", 1)[0].strip().lower()
            not in {"application/json", "application/problem+json"}
        ):
            raise ValueError("response contract rejected")
        payload = json.loads(response.body)
        if not isinstance(payload, dict):
            raise ValueError("response must be an object")
        raw_sha256 = hashlib.sha256(response.body).hexdigest()
        success = True
        error_code = ""
        return payload, raw_sha256
    except _ProviderSyncError:
        raise
    except Exception as exc:
        raise _ProviderSyncError("provider_response_invalid") from exc
    finally:
        outcome = record_race_live_host_outcome(
            host=_HOST,
            now=_safe_clock_value(clock=clock, fallback=request_now),
            success=success,
            error_code=error_code,
            circuit_threshold=3,
            circuit_seconds=300,
            expected_reservation_version=reservation.reservation_version,
        )
        if not outcome.recorded and success:
            raise _ProviderSyncError(f"host_outcome_{outcome.reason}")


def _reference_result_payload(
    *, event: models.RaceEvent, source: models.RaceResultSourceIdentity, semantic: dict[str, Any]
) -> dict[str, Any]:
    runners = semantic.get("runners")
    if not isinstance(runners, list):
        raise _ProviderSyncError("reference_result_incomplete")
    parsed: list[dict[str, Any]] = []
    position_counts: dict[int, int] = {}
    for row in runners:
        if not isinstance(row, dict):
            raise _ProviderSyncError("reference_result_incomplete")
        raw_position = str(row.get("source_reported_finish_position") or "").strip()
        position = int(raw_position) if raw_position.isdecimal() else None
        if position is not None and not 1 <= position <= 100:
            raise _ProviderSyncError("reference_result_incomplete")
        if position is not None:
            position_counts[position] = position_counts.get(position, 0) + 1
        parsed.append({"row": row, "position": position})
    participants = []
    for item in parsed:
        row = item["row"]
        position = item["position"]
        status = str(row.get("running_status") or "").strip()
        if position is not None:
            status = (
                models.RaceEventRevisionItemStatus.DEAD_HEAT
                if position_counts[position] > 1
                else models.RaceEventRevisionItemStatus.FINISHED
            )
        elif status not in models.RaceEventRevisionItemStatus.values:
            status = models.RaceEventRevisionItemStatus.UNKNOWN
        participants.append(
            {
                "external_runner_id": str(row.get("source_runner_key") or ""),
                "horse_name": str(row.get("horse_name") or ""),
                "reported_finish_position": position,
                "status": status,
                "raw_status": str(row.get("running_status") or ""),
                "number": str(row.get("horse_number") or ""),
                "barrier": str(row.get("draw") or ""),
                "jockey_name": str(row.get("jockey_name") or ""),
                "trainer_name": str(row.get("trainer_name") or ""),
                "carried_weight": str(row.get("carried_weight") or ""),
                "finish_time": "",
                "margin": str(row.get("margin") or ""),
                "field_provenance": {
                    "result": semantic.get("source_key"),
                },
            }
        )
    race = semantic.get("race") if isinstance(semantic.get("race"), dict) else {}
    return {
        "external_race_id": source.external_race_id,
        "off_time": event.race_datetime.isoformat() if event.race_datetime else "",
        "region": source.region_code,
        "course": str(race.get("source_racecourse") or event.racecourse),
        "race_name": str(
            race.get("source_race_name") or event.original_name or event.chinese_name
        ),
        "race_status": "complete",
        "participants": participants,
    }


def run_reference_result_data_sync(
    *,
    event_id: int,
    data_kinds: tuple[str, ...],
    route: RaceDataResolvedRoute,
    now: datetime,
    task_id: str,
    run_id: str,
    collect_if_missing: bool = True,
    capacity_reserved: bool = False,
) -> ProviderSyncOutcome:
    """Collect and consume a complete immutable third-party result receipt."""

    del run_id
    provider = route.entry.provider
    source_key = _REFERENCE_SOURCE_KEYS.get(provider)
    if (
        timezone.is_naive(now)
        or source_key is None
        or tuple(sorted(set(data_kinds))) != (models.RaceDataSyncDataKind.RESULT,)
    ):
        return ProviderSyncOutcome(False, "provider_not_implemented", {}, {})
    event = models.RaceEvent.objects.filter(pk=event_id).first()
    if event is None:
        return ProviderSyncOutcome(False, "event_missing", {}, {})
    try:
        from stable.services.scheduled_race_result_review import (
            _collect_missing_reference_receipts,
            load_route_registry,
        )

        registry = load_route_registry(
            Path(settings.RACE_RESULT_REVIEW_ROUTE_REGISTRY)
        )
        if registry["registry_sha256"] != route.proof_digest:
            raise _ProviderSyncError("reference_registry_drift")
        matches = [
            candidate
            for candidate in registry["routes"]
            if candidate.get("provider") == provider
            and candidate.get("region") == event.country_region
            and candidate.get("automation_allowed") is True
            and candidate.get("modules") == ["results"]
        ]
        if len(matches) != 1:
            raise _ProviderSyncError("reference_route_unavailable")
        valid_until = datetime.fromisoformat(
            str(matches[0].get("valid_until") or "").replace("Z", "+00:00")
        )
        if timezone.is_naive(valid_until) or valid_until <= now:
            raise _ProviderSyncError("reference_route_expired")

        receipt = (
            models.RaceReferenceReceipt.objects.filter(
                event=event,
                payload__source_key=source_key,
                match_status=models.RaceReferenceMatchStatus.MATCHED,
                is_partial=False,
            )
            .select_related("payload")
            .order_by("-recorded_at", "-id")
            .first()
        )
        if receipt is None and collect_if_missing:
            if not capacity_reserved:
                capacity = reserve_race_data_transport_capacity(
                    provider=provider,
                    region_code=route.entry.regions[0],
                    now=now,
                    proposed_requests=route.request_budget,
                    max_response_bytes_per_request=_MAX_RESPONSE_BYTES,
                )
                if not capacity.allowed:
                    raise _ProviderSyncError(capacity.reason_code)
            blockers = _collect_missing_reference_receipts(
                targets=[{"event_id": event.pk}],
                now=now,
                artifact_root=Path(settings.RACE_RESULT_REVIEW_ARTIFACT_ROOT),
            )
            if event.pk in blockers:
                raise _ProviderSyncError(blockers[event.pk])
            receipt = (
                models.RaceReferenceReceipt.objects.filter(
                    event=event,
                    payload__source_key=source_key,
                    match_status=models.RaceReferenceMatchStatus.MATCHED,
                    is_partial=False,
                )
                .select_related("payload")
                .order_by("-recorded_at", "-id")
                .first()
            )
        if receipt is None:
            return ProviderSyncOutcome(
                True,
                "complete",
                {},
                {},
                not_found_kinds=(models.RaceDataSyncDataKind.RESULT,),
            )
        source = models.RaceResultSourceIdentity.objects.filter(
            event_id=event_id,
            source_key=provider,
            region_code__in=route.entry.regions,
        ).first()
        if source is None:
            provider_event_key = str(
                receipt.payload.provider_event_key or ""
            ).strip()
            if not provider_event_key:
                raise _ProviderSyncError("reference_identity_missing")
            external_race_id = (
                provider_event_key
                if len(provider_event_key) <= 128
                else "reference:"
                + hashlib.sha256(provider_event_key.encode()).hexdigest()
            )
            namespace = (
                provider
                if provider in route.entry.identity_namespaces
                else route.entry.identity_namespaces[0]
            )
            source = models.RaceResultSourceIdentity.objects.create(
                event=event,
                source_key=provider,
                region_code=route.entry.regions[0],
                identity_namespace=namespace,
                external_race_id=external_race_id,
                canonical_url=receipt.final_url,
                host=route.allowed_hosts[0],
                identity_fields={
                    "provider_event_key": provider_event_key,
                    "reference_receipt_id": receipt.pk,
                    "identity_namespace": namespace,
                    "race_data_region": route.entry.regions[0],
                },
                review_status=models.RaceLiveReviewStatus.APPROVED,
                result_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
                reviewed_at=now,
                terms_status=models.RaceSourceTermsStatus.APPROVED,
                automation_allowed=True,
                proof_network_allowed=True,
                evidence_url=receipt.final_url,
                evidence_sha256=route.proof_digest,
                valid_until=valid_until,
                registry_digest=route.registry_digest,
            )
        semantic = receipt.payload.structured_payload
        completeness = (
            semantic.get("completeness")
            if isinstance(semantic, dict)
            and isinstance(semantic.get("completeness"), dict)
            else {}
        )
        if completeness.get("results") != "complete":
            return ProviderSyncOutcome(
                True,
                "complete",
                {models.RaceDataSyncDataKind.RESULT: receipt.raw_sha256},
                {models.RaceDataSyncDataKind.RESULT: receipt.source_observed_at},
                not_found_kinds=(models.RaceDataSyncDataKind.RESULT,),
            )
        payload = _reference_result_payload(
            event=event, source=source, semantic=semantic
        )
        decision = record_race_result_observation(
            source_identity_id=source.pk,
            observed_at=now,
            source_updated_at=receipt.source_observed_at or receipt.fetched_at,
            parser_version=receipt.parser_version,
            raw_sha256=receipt.raw_sha256,
            result_phase=models.RaceResultPhase.OFFICIAL,
            normalized_payload=payload,
            field_provenance={
                "provider": provider,
                "region": source.region_code,
                "source_class": route.entry.source_class,
                "source_url": receipt.final_url,
                "registry_digest": route.registry_digest,
                "reference_registry_digest": route.proof_digest,
                "reference_receipt_id": receipt.pk,
                "contract_version": route.entry.contract_version,
                "contract_digest": route.entry.contract_digest,
                "automation_allowed": True,
            },
            parse_warnings=list(receipt.gap_codes or []),
            permission_classification="trusted_publisher_automation",
        )
        if not decision.recorded or decision.observation is None:
            raise _ProviderSyncError(f"observation_{decision.reason}")
        flags = RaceDataSyncFlags.from_settings()
        applied = apply_data_sync_result_observation(
            observation_id=decision.observation.pk,
            expected_event_id=event.pk,
            now=now,
            project_current=bool(
                flags.result_apply_enabled and flags.result_public_enabled
            ),
            correction_apply_enabled=flags.correction_apply_enabled,
        )
        if applied.action not in {"applied", "recorded", "replayed"}:
            raise _ProviderSyncError(f"result_{applied.reason_code}")
        return ProviderSyncOutcome(
            True,
            "complete",
            {models.RaceDataSyncDataKind.RESULT: receipt.raw_sha256},
            {
                models.RaceDataSyncDataKind.RESULT: (
                    receipt.source_observed_at or receipt.fetched_at
                )
            },
            applied_kinds=(models.RaceDataSyncDataKind.RESULT,),
        )
    except _ProviderSyncError as exc:
        return ProviderSyncOutcome(False, exc.reason_code, {}, {})
    except Exception:
        return ProviderSyncOutcome(False, "reference_execution_failed", {}, {})


def run_result_fallback_chain(
    *,
    event_id: int,
    excluded_providers: tuple[str, ...],
    now: datetime,
    task_id: str,
    run_id: str,
) -> ProviderSyncOutcome:
    """Try admitted lower-priority result routes after a higher source has no row."""

    from stable.services.race_data_sync_control import source_admission_reason
    from stable.services.race_data_sync_policy import source_priority
    from stable.services.race_data_sync_pipeline import (
        resolve_race_data_provider_route,
    )

    sources = list(
        models.RaceResultSourceIdentity.objects.filter(event_id=event_id)
        .exclude(source_key__in=excluded_providers)
        .order_by("source_key", "id")
    )
    flags = RaceDataSyncFlags.from_settings()
    failures = []
    official_sources = [
        source
        for source in sources
        if source.source_key in _PERSISTED_OFFICIAL_SOURCES
        and source.source_key in flags.providers
        and source.region_code in flags.regions
        and source.review_status == models.RaceLiveReviewStatus.APPROVED
        and source.terms_status == models.RaceSourceTermsStatus.APPROVED
        and source.automation_allowed is True
        and (source.valid_until is None or source.valid_until > now)
    ]
    for source in sorted(official_sources, key=lambda item: item.source_key):
        outcome = run_persisted_official_result_data_sync(
            event_id=event_id,
            source_identity_id=source.pk,
            now=now,
            task_id=task_id,
            run_id=run_id,
        )
        if outcome.success and outcome.applied_kinds:
            return outcome
        if not outcome.success:
            failures.append(
                f"{source.source_key}_{outcome.reason_code}"[:64]
            )
    candidates = []
    candidate_providers = set()
    for source in sources:
        if source.source_key not in _REFERENCE_SOURCE_KEYS:
            continue
        route = resolve_race_data_provider_route(
            provider=source.source_key,
            region=source.region_code,
            identity_namespace=source.identity_namespace,
            data_kinds=(models.RaceDataSyncDataKind.RESULT,),
        )
        if route is None:
            continue
        if source_admission_reason(
            source=source,
            route_digest=route.route_digest,
            data_kinds=(models.RaceDataSyncDataKind.RESULT,),
            now=now,
        ):
            continue
        candidates.append(
            (source_priority(route.entry.source_class), source.source_key, route)
        )
        candidate_providers.add(source.source_key)
    reference_region = {
        models.RacingRegion.UNITED_KINGDOM: (
            "sporting_life",
            "united_kingdom",
        ),
        models.RacingRegion.FRANCE: ("zeturf", "france"),
        models.RacingRegion.UNITED_STATES: (
            "horse_racing_nation",
            "united_states",
        ),
    }.get(
        models.RaceEvent.objects.filter(pk=event_id).values_list(
            "country_region", flat=True
        ).first()
    )
    if reference_region is not None:
        provider, region = reference_region
        if provider not in candidate_providers:
            route = resolve_race_data_provider_route(
                provider=provider,
                region=region,
                identity_namespace=provider,
                data_kinds=(models.RaceDataSyncDataKind.RESULT,),
            )
            if route is not None:
                candidates.append(
                    (source_priority(route.entry.source_class), provider, route)
                )
    for _priority, provider, route in sorted(
        candidates, key=lambda item: (-item[0], item[1])
    ):
        outcome = run_reference_result_data_sync(
            event_id=event_id,
            data_kinds=(models.RaceDataSyncDataKind.RESULT,),
            route=route,
            now=now,
            task_id=task_id,
            run_id=run_id,
            capacity_reserved=False,
        )
        if outcome.success and outcome.applied_kinds:
            return outcome
        if not outcome.success:
            failures.append(f"{provider}_{outcome.reason_code}"[:64])
    if failures:
        return ProviderSyncOutcome(False, failures[0], {}, {})
    return ProviderSyncOutcome(
        True,
        "complete",
        {},
        {},
        not_found_kinds=(models.RaceDataSyncDataKind.RESULT,),
    )


def run_persisted_official_result_data_sync(
    *,
    event_id: int,
    source_identity_id: int,
    now: datetime,
    task_id: str,
    run_id: str,
) -> ProviderSyncOutcome:
    """Project a complete result already collected by an official importer.

    This adapter performs no website request.  It lets independently collected
    official rows outrank third-party fallback rows without granting a website
    automation permission that the repository does not currently possess.
    """

    del task_id, run_id
    source = models.RaceResultSourceIdentity.objects.filter(
        pk=source_identity_id, event_id=event_id
    ).first()
    event = models.RaceEvent.objects.filter(pk=event_id).first()
    external_source = (
        _PERSISTED_OFFICIAL_SOURCES.get(source.source_key) if source else None
    )
    if event is None or source is None or external_source is None:
        return ProviderSyncOutcome(False, "source_identity_missing", {}, {})
    race = (
        models.ExternalRace.objects.filter(
            source=external_source,
            race_id=source.external_race_id,
        )
        .prefetch_related("results")
        .first()
    )
    if race is None:
        return ProviderSyncOutcome(
            True,
            "complete",
            {},
            {},
            not_found_kinds=(models.RaceDataSyncDataKind.RESULT,),
        )
    rows = list(race.results.all())
    participants = []
    position_counts: dict[int, int] = {}
    prepared = []
    for row in rows:
        raw_position = str(row.finish_position or "").strip()
        position = int(raw_position) if raw_position.isdecimal() else None
        raw = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        raw_status = str(
            raw.get("running_status") or raw.get("status") or ""
        ).strip()
        if position is None and raw_status not in models.RaceEventRevisionItemStatus.values:
            return ProviderSyncOutcome(
                True,
                "complete",
                {},
                {},
                not_found_kinds=(models.RaceDataSyncDataKind.RESULT,),
            )
        if not row.horse_name or not (row.horse_id or row.result_key):
            return ProviderSyncOutcome(False, "official_result_incomplete", {}, {})
        if position is not None:
            position_counts[position] = position_counts.get(position, 0) + 1
        prepared.append((row, position, raw_status))
    if not prepared or not position_counts:
        return ProviderSyncOutcome(
            True,
            "complete",
            {},
            {},
            not_found_kinds=(models.RaceDataSyncDataKind.RESULT,),
        )
    for row, position, raw_status in prepared:
        status = raw_status
        if position is not None:
            status = (
                models.RaceEventRevisionItemStatus.DEAD_HEAT
                if position_counts[position] > 1
                else models.RaceEventRevisionItemStatus.FINISHED
            )
        participants.append(
            {
                "external_runner_id": str(row.horse_id or row.result_key),
                "horse_name": row.horse_name,
                "reported_finish_position": position,
                "status": status,
                "raw_status": raw_status,
                "number": row.horse_number,
                "barrier": row.barrier,
                "jockey_name": row.jockey_name,
                "trainer_name": row.trainer_name,
                "carried_weight": "",
                "finish_time": row.finish_time,
                "margin": row.margin,
                "field_provenance": {"result": source.source_key},
            }
        )
    payload = {
        "external_race_id": source.external_race_id,
        "off_time": (
            race.scheduled_start_at.isoformat()
            if race.scheduled_start_at
            else event.race_datetime.isoformat()
            if event.race_datetime
            else ""
        ),
        "region": source.region_code,
        "course": race.course or race.venue or event.racecourse,
        "race_name": race.race_name or event.original_name or event.chinese_name,
        "race_status": "complete",
        "participants": participants,
    }
    raw_sha256 = hashlib.sha256(
        json.dumps(
            {
                "race": race.raw_payload,
                "results": [row.raw_payload for row in rows],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    decision = record_race_result_observation(
        source_identity_id=source.pk,
        observed_at=now,
        source_updated_at=race.last_seen_at,
        parser_version="external-official-bridge-v1",
        raw_sha256=raw_sha256,
        result_phase=models.RaceResultPhase.OFFICIAL,
        normalized_payload=payload,
        field_provenance={
            "provider": source.source_key,
            "region": source.region_code,
            "source_class": "official_operator",
            "source_url": source.canonical_url,
            "external_race_pk": race.pk,
            "automation_allowed": True,
        },
        parse_warnings=[],
        permission_classification="persisted_official_snapshot",
    )
    if not decision.recorded or decision.observation is None:
        return ProviderSyncOutcome(
            False, f"observation_{decision.reason}", {}, {}
        )
    apply_flags = RaceDataSyncFlags.from_settings()
    applied = apply_data_sync_result_observation(
        observation_id=decision.observation.pk,
        expected_event_id=event.pk,
        now=now,
        project_current=bool(
            apply_flags.result_apply_enabled
            and apply_flags.result_public_enabled
        ),
        correction_apply_enabled=apply_flags.correction_apply_enabled,
    )
    if applied.action not in {"applied", "recorded", "replayed"}:
        return ProviderSyncOutcome(
            False, f"result_{applied.reason_code}", {}, {}
        )
    return ProviderSyncOutcome(
        True,
        "complete",
        {models.RaceDataSyncDataKind.RESULT: raw_sha256},
        {models.RaceDataSyncDataKind.RESULT: race.last_seen_at},
        applied_kinds=(models.RaceDataSyncDataKind.RESULT,),
    )


def _racecard_payload(
    *, normalized_race: dict[str, Any], event: models.RaceEvent, region: str
) -> dict[str, Any]:
    race_status = str(normalized_race.get("race_status") or "").strip()
    if not race_status:
        race_status = event.status
    return {
        "schema_version": 1,
        "external_race_id": normalized_race["external_race_id"],
        "off_time": normalized_race["off_time"],
        "region": region,
        "course": normalized_race["course"],
        "race_name": normalized_race["race_name"],
        "race_status": race_status,
        "timezone_name": event.timezone_name,
        "participants": [
            {
                key: value
                for key, value in participant.items()
                if key != "jockey_id"
            }
            for participant in normalized_race["participants"]
        ],
    }


def _result_payload(
    *, normalized_race: dict[str, Any], region: str
) -> dict[str, Any]:
    return {
        "external_race_id": normalized_race["external_race_id"],
        "off_time": normalized_race["off_time"],
        "region": region,
        "course": normalized_race["course"],
        "race_name": normalized_race["race_name"],
        "race_status": str(normalized_race.get("race_status") or "complete"),
        "participants": [
            {
                "external_runner_id": participant["external_runner_id"],
                "horse_name": participant["horse_name"],
                "reported_finish_position": participant[
                    "official_finish_position"
                ],
                "status": participant["status"],
                "raw_status": str(participant["position_raw"]),
                "number": participant["number"],
                "barrier": "",
                "jockey_name": "",
                "trainer_name": "",
                "carried_weight": "",
                "finish_time": "",
                "margin": "",
                "field_provenance": {"result": "the_racing_api"},
            }
            for participant in normalized_race["participants"]
        ],
    }


def run_the_racing_api_data_sync(
    *,
    event_id: int,
    data_kinds: tuple[str, ...],
    route: RaceDataResolvedRoute,
    now: datetime,
    task_id: str,
    run_id: str,
    transport: Callable[..., Any] = the_racing_api_transport,
    clock: Callable[[], datetime] = timezone.now,
    sleeper: Callable[[float], Any] = time.sleep,
) -> ProviderSyncOutcome:
    if timezone.is_naive(now):
        return ProviderSyncOutcome(False, "invalid_start_time", {}, {})
    if route.entry.provider != "the_racing_api":
        return ProviderSyncOutcome(False, "provider_not_implemented", {}, {})
    event = models.RaceEvent.objects.filter(pk=event_id).first()
    source = models.RaceResultSourceIdentity.objects.filter(
        event_id=event_id,
        source_key="the_racing_api",
        region_code__in=route.entry.regions,
    ).first()
    if event is None or source is None:
        return ProviderSyncOutcome(False, "source_identity_missing", {}, {})
    try:
        registry, registry_digest = read_the_racing_api_automation_registry(
            registry_file=settings.RACE_LIVE_TRA_REGISTRY_FILE,
            expected_registry_sha256=route.proof_digest,
            now=now,
        )
        if registry_digest != route.proof_digest:
            raise PermissionError("registry drift")
        username, password = _read_secret(settings.RACE_LIVE_TRA_SECRET_ENV_FILE)
        provider_timezone = ZoneInfo(event.timezone_name)
        provider_date = now.astimezone(provider_timezone).date()
    except Exception:
        return ProviderSyncOutcome(False, "source_runtime_contract_rejected", {}, {})

    flags = RaceDataSyncFlags.from_settings()
    with transaction.atomic():
        budget, created = models.RaceLiveHostBudget.objects.select_for_update().get_or_create(
            host=_HOST,
            defaults={
                "min_interval_ms": route.minimum_interval_seconds * 1000
            },
        )
        if (
            not created
            and budget.min_interval_ms
            != route.minimum_interval_seconds * 1000
        ):
            return ProviderSyncOutcome(False, "host_budget_mismatch", {}, {})
    observation_hashes: dict[str, str] = {}
    updated_by_kind: dict[str, datetime | None] = {}
    applied: list[str] = []
    not_found: list[str] = []
    request_count = 0
    try:
        if {
            models.RaceDataSyncDataKind.RACE_TIME,
            models.RaceDataSyncDataKind.RACECARD,
        }.intersection(data_kinds):
            if event.local_date is None:
                not_found.extend(
                    kind
                    for kind in data_kinds
                    if kind
                    in {
                        models.RaceDataSyncDataKind.RACE_TIME,
                        models.RaceDataSyncDataKind.RACECARD,
                    }
                )
            else:
                day_offset = (event.local_date - provider_date).days
                if day_offset not in {0, 1}:
                    not_found.extend(
                        kind
                        for kind in data_kinds
                        if kind
                        in {
                            models.RaceDataSyncDataKind.RACE_TIME,
                            models.RaceDataSyncDataKind.RACECARD,
                        }
                    )
                else:
                    if request_count >= route.request_budget:
                        raise _ProviderSyncError("provider_request_budget_exhausted")
                    day = "today" if day_offset == 0 else "tomorrow"
                    url = build_the_racing_api_route_url(
                        registry=registry,
                        route_name="racecards_free",
                        region=_registry_region(
                            event_region=event.country_region,
                            contract_region=source.region_code,
                        ),
                        day=day,
                        limit=500,
                        skip=0,
                    )
                    response_payload, raw_sha256 = _fetch_json(
                        transport=transport,
                        endpoint_name=f"racecards_sync_{day}",
                        url=url,
                        username=username,
                        password=password,
                        now=now,
                        clock=clock,
                        sleeper=sleeper,
                    )
                    request_count += 1
                    snapshot = parse_the_racing_api_live_racecards_payload(
                        response_payload
                    )
                    normalized_race = next(
                        (
                            race
                            for race in snapshot.races
                            if race["external_race_id"] == source.external_race_id
                        ),
                        None,
                    )
                    for kind in data_kinds:
                        if kind in {
                            models.RaceDataSyncDataKind.RACE_TIME,
                            models.RaceDataSyncDataKind.RACECARD,
                        }:
                            observation_hashes[kind] = raw_sha256
                            updated_by_kind[kind] = None
                    if normalized_race is None:
                        not_found.extend(
                            kind
                            for kind in data_kinds
                            if kind
                            in {
                                models.RaceDataSyncDataKind.RACE_TIME,
                                models.RaceDataSyncDataKind.RACECARD,
                            }
                        )
                    else:
                        contract = {
                            "schema_version": 1,
                            "provider": "the_racing_api",
                            "region": source.region_code,
                            "data_kind": "racecard",
                            "contract_version": route.entry.contract_version,
                            "contract_digest": route.entry.contract_digest,
                            "registry_digest": route.registry_digest,
                            "source_class": route.entry.source_class,
                            "automation_allowed": True,
                            "allowed_fields": list(route.entry.allowed_fields),
                        }
                        normalized = normalize_racecard_observation(
                            payload=_racecard_payload(
                                normalized_race=normalized_race,
                                event=event,
                                region=source.region_code,
                            ),
                            contract=contract,
                            observed_at=now,
                            source_updated_at=None,
                            parser_version="the-racing-api-v1",
                            raw_sha256=raw_sha256,
                            source_url=url,
                            task_id=task_id,
                            run_id=run_id,
                        )
                        persisted_provenance = {
                            key: (
                                value.isoformat()
                                if isinstance(value, datetime)
                                else value
                            )
                            for key, value in normalized.provenance.items()
                        }
                        observation_decision = record_race_result_observation(
                            source_identity_id=source.pk,
                            observed_at=now,
                            source_updated_at=None,
                            parser_version="the-racing-api-v1",
                            raw_sha256=raw_sha256,
                            result_phase=models.RaceResultPhase.RACECARD,
                            normalized_payload=normalized.normalized_payload,
                            field_provenance=persisted_provenance,
                            parse_warnings=[],
                            permission_classification="licensed_api_automation",
                        )
                        if (
                            not observation_decision.recorded
                            or observation_decision.observation is None
                        ):
                            raise _ProviderSyncError(
                                f"observation_{observation_decision.reason}"
                            )
                        reconcile = reconcile_racecard_observation(
                            observation_id=observation_decision.observation.pk,
                            expected_event_id=event.pk,
                            allow_schedule_apply=(
                                models.RaceDataSyncDataKind.RACE_TIME in data_kinds
                                and flags.schedule_apply_enabled
                            ),
                            allow_racecard_apply=(
                                models.RaceDataSyncDataKind.RACECARD in data_kinds
                                and flags.racecard_apply_enabled
                            ),
                            task_id=task_id,
                            run_id=run_id,
                        )
                        if reconcile.status not in {"applied", "replayed"}:
                            raise _ProviderSyncError(
                                f"racecard_{reconcile.reason}"
                            )
                        applied.extend(
                            kind
                            for kind in data_kinds
                            if kind
                            in {
                                models.RaceDataSyncDataKind.RACE_TIME,
                                models.RaceDataSyncDataKind.RACECARD,
                            }
                        )

        if models.RaceDataSyncDataKind.RESULT in data_kinds:
            if event.local_date != provider_date:
                not_found.append(models.RaceDataSyncDataKind.RESULT)
            else:
                collected: list[dict[str, Any]] = []
                page_hashes: list[str] = []
                result_url = ""
                for page_index in range(route.request_budget - request_count):
                    skip = page_index * 50
                    result_url = build_the_racing_api_route_url(
                        registry=registry,
                        route_name="results_today_free",
                        region=_registry_region(
                            event_region=event.country_region,
                            contract_region=source.region_code,
                        ),
                        limit=50,
                        skip=skip,
                    )
                    page, page_hash = _fetch_json(
                        transport=transport,
                        endpoint_name="results_today",
                        url=result_url,
                        username=username,
                        password=password,
                        now=now,
                        clock=clock,
                        sleeper=sleeper,
                    )
                    request_count += 1
                    rows = page.get("results")
                    if not isinstance(rows, list):
                        raise _ProviderSyncError("provider_response_invalid")
                    collected.extend(rows)
                    page_hashes.append(page_hash)
                    if any(
                        isinstance(row, dict)
                        and str(row.get("race_id") or "")
                        == source.external_race_id
                        for row in rows
                    ):
                        break
                    total = page.get("total")
                    if len(rows) < 50 or (
                        isinstance(total, int) and len(collected) >= total
                    ):
                        break
                if not page_hashes:
                    raise _ProviderSyncError("provider_request_budget_exhausted")
                combined = {
                    "results": collected,
                    "page_sha256": page_hashes,
                }
                raw_sha256 = hashlib.sha256(
                    json.dumps(
                        combined,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                snapshot = parse_the_racing_api_live_results_payload(
                    {"results": collected}
                )
                normalized_race = next(
                    (
                        race
                        for race in snapshot.races
                        if race["external_race_id"] == source.external_race_id
                    ),
                    None,
                )
                observation_hashes[models.RaceDataSyncDataKind.RESULT] = raw_sha256
                updated_by_kind[models.RaceDataSyncDataKind.RESULT] = None
                if normalized_race is None:
                    not_found.append(models.RaceDataSyncDataKind.RESULT)
                else:
                    payload = _result_payload(
                        normalized_race=normalized_race,
                        region=source.region_code,
                    )
                    normalized_sha256 = hashlib.sha256(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest()
                    observation_decision = record_race_result_observation(
                        source_identity_id=source.pk,
                        observed_at=now,
                        source_updated_at=None,
                        parser_version="the-racing-api-v1",
                        raw_sha256=raw_sha256,
                        result_phase=models.RaceResultPhase.OFFICIAL,
                        normalized_payload=payload,
                        field_provenance={
                            "provider": source.source_key,
                            "region": source.region_code,
                            "source_class": route.entry.source_class,
                            "source_url": result_url,
                            "registry_digest": route.registry_digest,
                            "contract_version": route.entry.contract_version,
                            "contract_digest": route.entry.contract_digest,
                            "automation_allowed": True,
                            "normalized_sha256": normalized_sha256,
                        },
                        parse_warnings=[],
                        permission_classification="licensed_api_automation",
                    )
                    if (
                        not observation_decision.recorded
                        or observation_decision.observation is None
                    ):
                        raise _ProviderSyncError(
                            f"observation_{observation_decision.reason}"
                        )
                    apply_result = apply_data_sync_result_observation(
                        observation_id=observation_decision.observation.pk,
                        expected_event_id=event.pk,
                        now=now,
                        project_current=bool(
                            flags.result_apply_enabled
                            and flags.result_public_enabled
                        ),
                        correction_apply_enabled=flags.correction_apply_enabled,
                    )
                    if apply_result.action not in {
                        "applied",
                        "recorded",
                        "replayed",
                    }:
                        raise _ProviderSyncError(
                            f"result_{apply_result.reason_code}"
                        )
                    applied.append(models.RaceDataSyncDataKind.RESULT)
    except _ProviderSyncError as exc:
        return ProviderSyncOutcome(
            False,
            exc.reason_code,
            observation_hashes,
            updated_by_kind,
            tuple(dict.fromkeys(applied)),
            tuple(dict.fromkeys(not_found)),
        )
    except Exception:
        return ProviderSyncOutcome(
            False,
            "provider_execution_failed",
            observation_hashes,
            updated_by_kind,
            tuple(dict.fromkeys(applied)),
            tuple(dict.fromkeys(not_found)),
        )
    return ProviderSyncOutcome(
        True,
        "complete",
        observation_hashes,
        updated_by_kind,
        tuple(dict.fromkeys(applied)),
        tuple(dict.fromkeys(not_found)),
    )

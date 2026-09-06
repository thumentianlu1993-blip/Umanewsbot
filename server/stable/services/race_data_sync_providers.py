from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import logging
import os
from pathlib import Path
import stat
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from stable import models
from stable.services.race_data_sync_control import (
    RaceDataSyncClaim,
    build_snapshot_cache_key,
    claim_snapshot_lease,
    fail_snapshot_lease,
    publish_snapshot,
    resolve_source_route_admission,
)
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
    ensure_race_live_host_budget_floor,
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
logger = logging.getLogger(__name__)
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_SNAPSHOT_LEASE_TTL_SECONDS = 120
_SNAPSHOT_WAITER_POLL_SECONDS = 2.0
# Jitter can shorten each sleep by 0.25s.  Keep the bounded waiter long enough
# that even the shortest legal sequence crosses the full lease TTL and gets one
# CAS takeover opportunity instead of failing just before expiry.
_SNAPSHOT_WAITER_MAX_POLLS = 69
_REFERENCE_SOURCE_KEYS = {
    "sporting_life": "reference_sporting_life",
    "zeturf": "reference_zeturf",
    "horse_racing_nation": "reference_horse_racing_nation",
}
_PERSISTED_OFFICIAL_SOURCES = {
    "hkjc": models.ExternalDataSource.HKJC,
    "france_galop": models.ExternalDataSource.FRANCE_GALOP,
}
_TRA_CORRECTION_MARKERS = frozenset({"amended", "corrected", "revised"})


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
    already_valid_count: int = 0
    awaiting_source_window_count: int = 0
    deferred_event_count: int = 0
    rejected_event_count: int = 0


@dataclass(frozen=True)
class SnapshotCleanupOutcome:
    cleaned: int
    cleaned_bytes: int
    skipped: int


class _ProviderSyncError(Exception):
    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


def _snapshot_artifact_root() -> Path:
    configured = tuple(
        Path(str(value))
        for value in getattr(settings, "RACE_DATA_RAW_ARTIFACT_ROOTS", ())
        if str(value)
    )
    if not configured:
        raise _ProviderSyncError("artifact_root_not_configured")
    root = configured[0]
    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise _ProviderSyncError("artifact_root_unavailable") from exc
    if root.is_symlink() or not stat.S_ISDIR(root_stat.st_mode):
        raise _ProviderSyncError("artifact_root_unsafe")
    snapshots = root / "snapshots"
    try:
        snapshots.mkdir(mode=0o700, exist_ok=True)
        snapshot_stat = snapshots.lstat()
    except OSError as exc:
        raise _ProviderSyncError("artifact_snapshot_root_unavailable") from exc
    if snapshots.is_symlink() or not stat.S_ISDIR(snapshot_stat.st_mode):
        raise _ProviderSyncError("artifact_snapshot_root_unsafe")
    return snapshots


def _write_snapshot_artifact(
    *, cache_key: str, owner_token: str, payload: dict[str, Any]
) -> tuple[Path, str]:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _ProviderSyncError("snapshot_payload_invalid") from exc
    max_bytes = int(getattr(settings, "RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES", 0))
    if max_bytes <= 0 or len(encoded) > max_bytes:
        raise _ProviderSyncError("snapshot_payload_too_large")
    artifact_sha256 = hashlib.sha256(encoded).hexdigest()
    root = _snapshot_artifact_root()
    basename = hashlib.sha256(cache_key.encode()).hexdigest()
    final_path = root / f"{basename}-{artifact_sha256}.json"
    temporary_path = root / f".{basename}-{artifact_sha256}.{owner_token}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary_path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
        try:
            os.link(temporary_path, final_path, follow_symlinks=False)
        except FileExistsError:
            existing_fd = os.open(
                final_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                existing_stat = os.fstat(existing_fd)
                existing = os.read(existing_fd, len(encoded) + 1)
            finally:
                os.close(existing_fd)
            if not stat.S_ISREG(existing_stat.st_mode) or existing != encoded:
                raise OSError("snapshot digest path contains different bytes")
        temporary_path.unlink(missing_ok=True)
        os.chmod(final_path, 0o600)
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise _ProviderSyncError("snapshot_artifact_publish_failed") from exc
    return final_path, artifact_sha256


def _read_snapshot_artifact(*, manifest: dict[str, Any]) -> tuple[dict[str, Any], str]:
    cache_key = manifest.get("cache_key")
    artifact_sha256 = manifest.get("artifact_sha256")
    if not isinstance(cache_key, str) or not isinstance(artifact_sha256, str):
        raise _ProviderSyncError("snapshot_manifest_invalid")
    root = _snapshot_artifact_root().resolve()
    path = root / (
        f"{hashlib.sha256(cache_key.encode()).hexdigest()}-{artifact_sha256}.json"
    )
    try:
        resolved = path.resolve(strict=True)
        path_stat = path.lstat()
    except OSError as exc:
        raise _ProviderSyncError("snapshot_artifact_missing") from exc
    if (
        resolved.parent != root
        or path.is_symlink()
        or not stat.S_ISREG(path_stat.st_mode)
        or stat.S_IMODE(path_stat.st_mode) & 0o077
    ):
        raise _ProviderSyncError("snapshot_artifact_unsafe")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                encoded = handle.read(
                    int(getattr(settings, "RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES", 0))
                    + 1
                )
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise _ProviderSyncError("snapshot_artifact_read_failed") from exc
    if hashlib.sha256(encoded).hexdigest() != artifact_sha256:
        raise _ProviderSyncError("snapshot_artifact_digest_mismatch")
    try:
        payload = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _ProviderSyncError("snapshot_artifact_invalid") from exc
    if not isinstance(payload, dict):
        raise _ProviderSyncError("snapshot_artifact_invalid")
    return payload, artifact_sha256


def _delete_unreferenced_snapshot_artifact(
    *, cache_key: str, artifact_sha256: str
) -> None:
    """Retire one superseded content-addressed snapshot after a successful CAS."""

    if not artifact_sha256 or models.RaceDataSnapshotLease.objects.filter(
        cache_key=cache_key,
        artifact_sha256=artifact_sha256,
    ).exists():
        return
    root = _snapshot_artifact_root().resolve()
    name = (
        f"{hashlib.sha256(cache_key.encode()).hexdigest()}-"
        f"{artifact_sha256}.json"
    )
    path = root / name
    try:
        path_stat = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(path_stat.st_mode):
            return
        directory_flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        parent_fd = os.open(root, directory_flags)
        try:
            file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            file_fd = os.open(name, file_flags, dir_fd=parent_fd)
            try:
                opened = os.fstat(file_fd)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_dev != path_stat.st_dev
                    or opened.st_ino != path_stat.st_ino
                ):
                    return
            finally:
                os.close(file_fd)
            if models.RaceDataSnapshotLease.objects.filter(
                cache_key=cache_key,
                artifact_sha256=artifact_sha256,
            ).exists():
                return
            os.unlink(name, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    except OSError:
        logger.warning(
            "Unable to retire superseded race-data snapshot",
            extra={"cache_key": cache_key, "artifact_sha256": artifact_sha256},
        )


def cleanup_expired_shared_snapshots(
    *, now: datetime, batch_size: int = 100, max_bytes: int | None = None
) -> SnapshotCleanupOutcome:
    """Remove complete shared snapshots after the correction window expires."""

    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    if isinstance(batch_size, bool) or not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if max_bytes is None:
        max_bytes = int(
            getattr(settings, "RACE_DATA_RAW_CLEANUP_MAX_BYTES", 0) or (2**63 - 1)
        )
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    retention_seconds = int(
        getattr(settings, "RACE_DATA_SNAPSHOT_RETENTION_SECONDS", 0)
    )
    if not 7 * 24 * 3600 <= retention_seconds <= 90 * 24 * 3600:
        raise ValueError("snapshot retention must cover 7 to 90 days")
    cutoff = now - timedelta(seconds=retention_seconds)
    candidate_ids = tuple(
        models.RaceDataSnapshotLease.objects.filter(
            state=models.RaceDataSnapshotLeaseState.COMPLETE,
            updated_at__lte=cutoff,
        )
        .order_by("updated_at", "id")
        .values_list("id", flat=True)[:batch_size]
    )
    cleaned = 0
    cleaned_bytes = 0
    skipped = 0
    for lease_id in candidate_ids:
        with transaction.atomic():
            lease = (
                models.RaceDataSnapshotLease.objects.select_for_update()
                .filter(
                    pk=lease_id,
                    state=models.RaceDataSnapshotLeaseState.COMPLETE,
                    updated_at__lte=cutoff,
                )
                .first()
            )
            if lease is None:
                skipped += 1
                continue
            manifest = lease.manifest_data
            if (
                not isinstance(manifest, dict)
                or manifest.get("cache_key") != lease.cache_key
                or manifest.get("artifact_sha256") != lease.artifact_sha256
            ):
                skipped += 1
                continue
            root = _snapshot_artifact_root().resolve()
            name = (
                f"{hashlib.sha256(lease.cache_key.encode()).hexdigest()}-"
                f"{lease.artifact_sha256}.json"
            )
            path = root / name
            try:
                _payload, digest = _read_snapshot_artifact(manifest=manifest)
                before = path.lstat()
                if before.st_size > max_bytes - cleaned_bytes:
                    break
                directory_flags = os.O_RDONLY | os.O_DIRECTORY
                if hasattr(os, "O_NOFOLLOW"):
                    directory_flags |= os.O_NOFOLLOW
                parent_fd = os.open(root, directory_flags)
                try:
                    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                    file_fd = os.open(name, file_flags, dir_fd=parent_fd)
                    try:
                        opened = os.fstat(file_fd)
                        if (
                            not stat.S_ISREG(opened.st_mode)
                            or opened.st_dev != before.st_dev
                            or opened.st_ino != before.st_ino
                            or digest != lease.artifact_sha256
                        ):
                            raise OSError("snapshot artifact identity changed")
                    finally:
                        os.close(file_fd)
                    os.unlink(name, dir_fd=parent_fd)
                finally:
                    os.close(parent_fd)
            except (OSError, TypeError, ValueError, _ProviderSyncError):
                skipped += 1
                continue
            lease.delete()
            cleaned += 1
            cleaned_bytes += before.st_size
    return SnapshotCleanupOutcome(
        cleaned=cleaned,
        cleaned_bytes=cleaned_bytes,
        skipped=skipped,
    )


def _get_or_fetch_shared_snapshot(
    *,
    provider: str,
    region: str,
    scope_key: str,
    data_kind: str,
    registry_digest: str,
    run_id: str,
    now: datetime,
    proposed_requests: int,
    clock: Callable[[], datetime],
    sleeper: Callable[[float], Any],
    fetcher: Callable[[], tuple[dict[str, Any], int, int]],
) -> tuple[dict[str, Any], str]:
    cache_key = build_snapshot_cache_key(
        provider=provider,
        region=region,
        scope_key=scope_key,
        data_kind=data_kind,
        registry_digest=registry_digest,
    )
    owner_token = "snapshot-" + hashlib.sha256(
        f"{run_id}:{cache_key}".encode()
    ).hexdigest()[:48]
    decision_now = now
    decision = claim_snapshot_lease(
        provider=provider,
        region=region,
        scope_key=scope_key,
        data_kind=data_kind,
        registry_digest=registry_digest,
        owner_token=owner_token,
        now=decision_now,
        ttl_seconds=_SNAPSHOT_LEASE_TTL_SECONDS,
    )
    if decision.action == "busy" and decision.reason_code == "lease_active":
        for poll_index in range(_SNAPSHOT_WAITER_MAX_POLLS):
            jitter_seed = hashlib.sha256(
                f"{owner_token}:{poll_index}".encode()
            ).digest()[0]
            jitter = ((jitter_seed / 255.0) - 0.5) * 0.5
            sleeper(max(0.1, _SNAPSHOT_WAITER_POLL_SECONDS + jitter))
            decision_now = _safe_clock_value(clock=clock, fallback=decision_now)
            decision = claim_snapshot_lease(
                provider=provider,
                region=region,
                scope_key=scope_key,
                data_kind=data_kind,
                registry_digest=registry_digest,
                owner_token=owner_token,
                now=decision_now,
                ttl_seconds=_SNAPSHOT_LEASE_TTL_SECONDS,
            )
            if decision.action != "busy":
                break
            if decision.reason_code != "lease_active":
                break
    if decision.action == "complete":
        lease = models.RaceDataSnapshotLease.objects.filter(
            cache_key=cache_key,
            state=models.RaceDataSnapshotLeaseState.COMPLETE,
        ).first()
        if lease is None:
            raise _ProviderSyncError("snapshot_manifest_missing")
        return _read_snapshot_artifact(manifest=lease.manifest_data)
    if decision.action not in {"acquired", "replay", "taken_over"}:
        raise _ProviderSyncError(
            "snapshot_lease_busy"
            if decision.action == "busy"
            else "snapshot_lease_rejected"
        )
    lease_state = models.RaceDataSnapshotLease.objects.filter(
        cache_key=cache_key,
        owner_token=owner_token,
        lease_generation=decision.generation,
    ).values_list("manifest_data", flat=True).first()
    previous_artifact_sha256 = (
        str(lease_state.get("previous_artifact_sha256") or "")
        if isinstance(lease_state, dict)
        else ""
    )
    try:
        capacity = reserve_race_data_transport_capacity(
            provider=provider,
            region_code=region,
            now=decision_now,
            proposed_requests=proposed_requests,
            max_response_bytes_per_request=_MAX_RESPONSE_BYTES,
        )
        if not capacity.allowed:
            raise _ProviderSyncError(capacity.reason_code)
        payload, page_count, item_count = fetcher()
        completed_at = _safe_clock_value(clock=clock, fallback=decision_now)
        _artifact_path, artifact_sha256 = _write_snapshot_artifact(
            cache_key=cache_key,
            owner_token=owner_token,
            payload=payload,
        )
        manifest = {
            "schema_version": 1,
            "complete": True,
            "cache_key": cache_key,
            "artifact_sha256": artifact_sha256,
            "registry_digest": registry_digest,
            "fetched_at": completed_at.isoformat(),
            "page_count": page_count,
            "item_count": item_count,
        }
        published = publish_snapshot(
            provider=provider,
            region=region,
            scope_key=scope_key,
            data_kind=data_kind,
            registry_digest=registry_digest,
            owner_token=owner_token,
            expected_generation=decision.generation,
            artifact_sha256=artifact_sha256,
            manifest=manifest,
            now=completed_at,
        )
        if published.action != "published":
            raise _ProviderSyncError("snapshot_publish_cas_stale")
        if previous_artifact_sha256 != artifact_sha256:
            _delete_unreferenced_snapshot_artifact(
                cache_key=cache_key,
                artifact_sha256=previous_artifact_sha256,
            )
        return payload, artifact_sha256
    except Exception as exc:
        failed_at = _safe_clock_value(clock=clock, fallback=decision_now)
        fail_snapshot_lease(
            provider=provider,
            region=region,
            scope_key=scope_key,
            data_kind=data_kind,
            registry_digest=registry_digest,
            owner_token=owner_token,
            expected_generation=decision.generation,
            error_code=(
                exc.reason_code
                if isinstance(exc, _ProviderSyncError)
                else "snapshot_fetch_failed"
            ),
            retry_after=failed_at + timedelta(minutes=5),
            now=failed_at,
        )
        if isinstance(exc, _ProviderSyncError):
            raise
        raise _ProviderSyncError("snapshot_fetch_failed") from exc


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
    horizon_days: int = 30,
    transport: Callable[..., Any] = the_racing_api_transport,
    clock: Callable[[], datetime] = timezone.now,
    sleeper: Callable[[float], Any] = time.sleep,
) -> ProviderIdentityDiscoveryOutcome:
    """Bind future events to an exact TRA race ID without per-race review.

    Only deterministic name + course + local-date matches are admitted.  One
    hourly invocation is bounded by the reviewed TRA registry request budget.
    Every scanned event is accounted exactly once: already valid, waiting for
    the source window, rejected before candidacy, deferred by budget, or
    processed to created/adopted/ambiguous/unmatched.
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
    if (
        isinstance(horizon_days, bool)
        or not isinstance(horizon_days, int)
        or not 1 <= horizon_days <= 366
    ):
        raise ValueError("horizon_days is invalid")
    candidate_events = list(
        models.RaceEvent.objects.filter(
            visibility_status=models.RaceEventVisibility.PUBLISHED,
            status=models.RaceEventStatus.SCHEDULED,
            local_date__gte=now.date() - timedelta(days=1),
            local_date__lte=now.date() + timedelta(days=horizon_days + 1),
        )
        .select_related("race_series", "major_race_event")
        .prefetch_related("aliases", "race_series__names", "source_identities")
        .order_by("local_date", "id")
    )
    total = len(candidate_events)
    already_valid = 0
    awaiting = 0
    rejected = 0
    candidates = []
    for event in candidate_events:
        if isinstance(event.manual_lock_flags, dict) and any(
            event.manual_lock_flags.values()
        ):
            rejected += 1
            continue
        contract_region = _event_contract_region(event)
        if contract_region not in flags.regions:
            rejected += 1
            continue
        existing = [
            source
            for source in event.source_identities.all()
            if source.source_key == "the_racing_api"
        ]
        route = resolve_race_data_provider_route(
            provider="the_racing_api",
            region=contract_region,
            identity_namespace="the_racing_api-race-v1",
            data_kinds=required_kinds,
        )
        if route is None:
            rejected += 1
            continue
        exact_existing = [
            source
            for source in existing
            if source.region_code == contract_region
            and source.identity_namespace == route.identity_namespace
        ]
        if len(exact_existing) == 1:
            admission_reason, _binding = resolve_source_route_admission(
                source=exact_existing[0],
                route_digest=route.route_digest,
                data_kinds=required_kinds,
                now=now,
            )
            if not admission_reason:
                already_valid += 1
                continue
        try:
            provider_date = now.astimezone(ZoneInfo(event.timezone_name)).date()
        except (KeyError, ValueError):
            rejected += 1
            continue
        offset = (event.local_date - provider_date).days
        if offset > 1:
            awaiting += 1
            continue
        if offset < 0:
            rejected += 1
            continue
        candidates.append((event, contract_region, route, existing, offset))
    if not candidates:
        return ProviderIdentityDiscoveryOutcome(
            True,
            "no_candidates",
            0,
            total,
            0,
            0,
            0,
            0,
            already_valid_count=already_valid,
            awaiting_source_window_count=awaiting,
            rejected_event_count=rejected,
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
        ensure_race_live_host_budget_floor(
            host=_HOST,
            minimum_interval_ms=first_route.minimum_interval_seconds * 1000,
        )
    except Exception:
        logger.exception("TRA identity discovery runtime contract failed")
        return ProviderIdentityDiscoveryOutcome(
            False,
            "source_runtime_contract_rejected",
            0,
            total,
            0,
            0,
            0,
            len(candidates),
            already_valid_count=already_valid,
            awaiting_source_window_count=awaiting,
            rejected_event_count=rejected,
        )

    buckets: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    for candidate in candidates:
        event = candidate[0]
        provider_region = _registry_region(
            event_region=event.country_region,
            contract_region=candidate[1],
        )
        buckets.setdefault(
            (provider_region, "today" if candidate[4] == 0 else "tomorrow"), []
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
            for event, contract_region, route, existing, _offset in bucket:
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
                        region_code=contract_region,
                        identity_namespace=route.identity_namespace,
                        external_race_id=external_id,
                    ).exclude(event=locked_event).exists():
                        ambiguous += 1
                        continue
                    locked_sources = list(
                        models.RaceResultSourceIdentity.objects.select_for_update()
                        .filter(
                            event=locked_event,
                            source_key="the_racing_api",
                            region_code=contract_region,
                            identity_namespace=route.identity_namespace,
                        )[:2]
                    )
                    if len(locked_sources) > 1:
                        ambiguous += 1
                        continue
                    source = locked_sources[0] if locked_sources else None
                    identity_fields = {
                        "event_id": locked_event.pk,
                        "identity_discovery": "exact_name_course_local_date_v1",
                        "identity_namespace": route.identity_namespace,
                        "race_data_region": contract_region,
                        "source_response_sha256": raw_sha256,
                    }
                    values = {
                        "region_code": contract_region,
                        "identity_namespace": route.identity_namespace,
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
                            event=locked_event,
                            source_key="the_racing_api",
                            **values,
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
            total,
            created,
            adopted,
            ambiguous,
            unmatched,
            already_valid_count=already_valid,
            awaiting_source_window_count=awaiting,
            deferred_event_count=(
                len(candidates) - created - adopted - ambiguous - unmatched
            ),
            rejected_event_count=rejected,
        )
    except Exception:
        logger.exception("TRA identity discovery execution failed")
        return ProviderIdentityDiscoveryOutcome(
            False,
            "provider_execution_failed",
            request_count,
            total,
            created,
            adopted,
            ambiguous,
            unmatched,
            already_valid_count=already_valid,
            awaiting_source_window_count=awaiting,
            deferred_event_count=(
                len(candidates) - created - adopted - ambiguous - unmatched
            ),
            rejected_event_count=rejected,
        )
    return ProviderIdentityDiscoveryOutcome(
        True,
        "complete",
        request_count,
        total,
        created,
        adopted,
        ambiguous,
        unmatched,
        already_valid_count=already_valid,
        awaiting_source_window_count=awaiting,
        deferred_event_count=(
            len(candidates) - created - adopted - ambiguous - unmatched
        ),
        rejected_event_count=rejected,
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
    allow_not_found: bool = False,
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
            allow_not_found
            and response.redirect_url is None
            and response.status_code == 404
            and isinstance(response.body, bytes)
            and len(response.body) <= _MAX_RESPONSE_BYTES
        ):
            raw_sha256 = hashlib.sha256(response.body).hexdigest()
            success = True
            error_code = ""
            return {"_not_found": True}, raw_sha256
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
    claim_guard: RaceDataSyncClaim | None = None,
    project_current: bool | None = None,
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
        namespace = route.identity_namespace
        source = models.RaceResultSourceIdentity.objects.filter(
            event_id=event_id,
            source_key=provider,
            region_code=route.entry.regions[0],
            identity_namespace=namespace,
        ).first()
        if source is None:
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
        elif (
            source.external_race_id != external_race_id
            or (
                isinstance(source.identity_fields, dict)
                and source.identity_fields.get("provider_event_key") not in {
                    None,
                    "",
                    provider_event_key,
                }
            )
        ):
            raise _ProviderSyncError("reference_identity_conflict")
        elif not isinstance(source.identity_fields, dict) or not source.identity_fields.get(
            "provider_event_key"
        ):
            source.identity_fields = {
                **(
                    source.identity_fields
                    if isinstance(source.identity_fields, dict)
                    else {}
                ),
                "provider_event_key": provider_event_key,
                "identity_namespace": namespace,
                "race_data_region": route.entry.regions[0],
            }
            source.save(update_fields=("identity_fields", "updated_at"))
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
        should_project = (
            bool(flags.result_apply_enabled and flags.result_public_enabled)
            if project_current is None
            else project_current
        )
        applied = apply_data_sync_result_observation(
            observation_id=decision.observation.pk,
            expected_event_id=event.pk,
            now=now,
            project_current=should_project,
            correction_apply_enabled=flags.correction_apply_enabled,
            claim_guard=claim_guard,
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
    claim_guard: RaceDataSyncClaim | None = None,
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
            claim_guard=claim_guard,
            project_current=None,
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
        if (
            source.source_key not in flags.providers
            or source.region_code not in flags.regions
        ):
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
        if (
            provider in flags.providers
            and region in flags.regions
            and provider not in candidate_providers
        ):
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
            claim_guard=claim_guard,
            project_current=None,
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
    claim_guard: RaceDataSyncClaim | None = None,
    project_current: bool | None = None,
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
    from stable.services.race_data_sync_pipeline import (
        build_race_data_provider_roster,
    )

    roster = build_race_data_provider_roster(configuration_only=True)
    roster_entry = next(
        (
            entry
            for entry in roster.entries
            if entry.provider == source.source_key
            and source.region_code in entry.regions
            and source.identity_namespace in entry.identity_namespaces
            and models.RaceDataSyncDataKind.RESULT in entry.data_kinds
        ),
        None,
    )
    if (
        roster_entry is None
        or source.review_status != models.RaceLiveReviewStatus.APPROVED
        or source.terms_status != models.RaceSourceTermsStatus.APPROVED
        or source.automation_allowed is not True
        or source.valid_until is None
        or source.valid_until <= now
        or source.registry_digest != roster.registry_digest
    ):
        return ProviderSyncOutcome(False, "source_runtime_contract_rejected", {}, {})
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
            "source_class": roster_entry.source_class,
            "source_url": source.canonical_url,
            "external_race_pk": race.pk,
            "registry_digest": roster.registry_digest,
            "contract_version": roster_entry.contract_version,
            "contract_digest": roster_entry.contract_digest,
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
    should_project = (
        bool(
            apply_flags.result_apply_enabled
            and apply_flags.result_public_enabled
        )
        if project_current is None
        else project_current
    )
    applied = apply_data_sync_result_observation(
        observation_id=decision.observation.pk,
        expected_event_id=event.pk,
        now=now,
        project_current=should_project,
        correction_apply_enabled=apply_flags.correction_apply_enabled,
        claim_guard=claim_guard,
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


_KNOWN_NONSTARTER_STATUSES = frozenset(
    {
        models.RaceRunnerStatus.SCRATCHED,
        models.RaceRunnerStatus.WITHDRAWN,
        models.RaceRunnerStatus.NON_RUNNER,
    }
)


def _runner_source_id(
    *, runner: models.RaceEventRunner, source_key: str
) -> str:
    refs = runner.source_refs if isinstance(runner.source_refs, dict) else {}
    direct = str(refs.get(source_key) or "").strip()
    if direct:
        return direct
    if refs.get("source_key") == source_key:
        return str(refs.get("external_runner_id") or "").strip()
    return ""


def _result_payload(
    *,
    normalized_race: dict[str, Any],
    region: str,
    event: models.RaceEvent,
    source_key: str,
) -> dict[str, Any]:
    participants = [
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
    ]
    seen_runner_ids = {
        participant["external_runner_id"] for participant in participants
    }
    for runner in event.runners.filter(
        running_status__in=_KNOWN_NONSTARTER_STATUSES
    ).order_by("sort_order", "id"):
        external_runner_id = _runner_source_id(
            runner=runner,
            source_key=source_key,
        )
        if not external_runner_id or external_runner_id in seen_runner_ids:
            continue
        seen_runner_ids.add(external_runner_id)
        participants.append(
            {
                "external_runner_id": external_runner_id,
                "horse_name": runner.horse_name,
                "reported_finish_position": None,
                "status": runner.running_status,
                "raw_status": runner.running_status,
                "number": runner.horse_number,
                "barrier": runner.barrier,
                "jockey_name": runner.jockey_name,
                "trainer_name": runner.trainer_name,
                "carried_weight": runner.carried_weight,
                "finish_time": "",
                "margin": "",
                "field_provenance": {
                    "result": "racecard_terminal_nonstarter",
                    "source_key": source_key,
                },
            }
        )
    return {
        "external_race_id": normalized_race["external_race_id"],
        "off_time": normalized_race["off_time"],
        "region": region,
        "course": normalized_race["course"],
        "race_name": normalized_race["race_name"],
        "race_status": str(normalized_race.get("race_status") or "complete"),
        "participants": participants,
    }


def run_the_racing_api_data_sync(
    *,
    event_id: int,
    data_kinds: tuple[str, ...],
    route: RaceDataResolvedRoute,
    now: datetime,
    task_id: str,
    run_id: str,
    claim_guard: RaceDataSyncClaim | None = None,
    transport: Callable[..., Any] = the_racing_api_transport,
    clock: Callable[[], datetime] = timezone.now,
    sleeper: Callable[[float], Any] = time.sleep,
) -> ProviderSyncOutcome:
    if timezone.is_naive(now):
        return ProviderSyncOutcome(False, "invalid_start_time", {}, {})
    if route.entry.provider != "the_racing_api":
        return ProviderSyncOutcome(False, "provider_not_implemented", {}, {})
    event = models.RaceEvent.objects.filter(pk=event_id).first()
    enrollment = (
        models.RaceDataSyncEnrollment.objects.select_related("source_identity")
        .filter(
            event_id=event_id,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
        )
        .first()
    )
    source = enrollment.source_identity if enrollment is not None else None
    if event is None or enrollment is None or source is None:
        return ProviderSyncOutcome(False, "source_identity_missing", {}, {})
    if (
        source.event_id != event_id
        or source.source_key != "the_racing_api"
        or source.region_code not in route.entry.regions
        or source.identity_namespace not in route.entry.identity_namespaces
        or enrollment.route_digest != route.route_digest
        or source.review_status != models.RaceLiveReviewStatus.APPROVED
        or source.terms_status != models.RaceSourceTermsStatus.APPROVED
        or source.automation_allowed is not True
        or source.valid_until is None
        or source.valid_until <= now
        or source.registry_digest != route.registry_digest
    ):
        return ProviderSyncOutcome(False, "source_runtime_contract_rejected", {}, {})
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
    try:
        ensure_race_live_host_budget_floor(
            host=_HOST,
            minimum_interval_ms=route.minimum_interval_seconds * 1000,
        )
    except (TypeError, ValueError):
        return ProviderSyncOutcome(False, "host_budget_mismatch", {}, {})
    observation_hashes: dict[str, str] = {}
    updated_by_kind: dict[str, datetime | None] = {}
    applied: list[str] = []
    not_found: list[str] = []
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
                    day = "today" if day_offset == 0 else "tomorrow"
                    provider_region = _registry_region(
                        event_region=event.country_region,
                        contract_region=source.region_code,
                    )
                    url = build_the_racing_api_route_url(
                        registry=registry,
                        route_name="racecards_free",
                        region=provider_region,
                        day=day,
                        limit=500,
                        skip=0,
                    )

                    def fetch_racecard_snapshot() -> tuple[dict[str, Any], int, int]:
                        payload, _payload_sha256 = _fetch_json(
                            transport=transport,
                            endpoint_name=f"racecards_sync_{day}",
                            url=url,
                            username=username,
                            password=password,
                            now=now,
                            clock=clock,
                            sleeper=sleeper,
                        )
                        rows = payload.get("racecards")
                        if not isinstance(rows, list):
                            raise _ProviderSyncError("provider_response_invalid")
                        return payload, 1, len(rows)

                    response_payload, raw_sha256 = _get_or_fetch_shared_snapshot(
                        provider=source.source_key,
                        region=source.region_code,
                        scope_key=(
                            f"{event.local_date.isoformat()}:{day}:{provider_region}"
                        ),
                        data_kind=models.RaceDataSyncDataKind.RACECARD,
                        registry_digest=route.registry_digest,
                        run_id=run_id,
                        now=now,
                        proposed_requests=1,
                        clock=clock,
                        sleeper=sleeper,
                        fetcher=fetch_racecard_snapshot,
                    )
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
                            claim_guard=claim_guard,
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
                        if reconcile.claim_invalidated:
                            raise _ProviderSyncError(
                                "schedule_changed_claim_invalidated"
                            )

        if models.RaceDataSyncDataKind.RESULT in data_kinds:
            day_offset = (
                (event.local_date - provider_date).days
                if event.local_date is not None
                else None
            )
            result_url = ""
            response_payload: dict[str, Any] | None = None
            raw_sha256 = ""
            provider_region = _registry_region(
                event_region=event.country_region,
                contract_region=source.region_code,
            )
            if day_offset == 0:
                result_url = build_the_racing_api_route_url(
                    registry=registry,
                    route_name="results_today_free",
                    region=provider_region,
                    limit=50,
                    skip=0,
                )

                def fetch_result_snapshot() -> tuple[dict[str, Any], int, int]:
                    collected: list[dict[str, Any]] = []
                    page_hashes: list[str] = []
                    pagination_complete = False
                    for page_index in range(route.request_budget):
                        page_url = build_the_racing_api_route_url(
                            registry=registry,
                            route_name="results_today_free",
                            region=provider_region,
                            limit=50,
                            skip=page_index * 50,
                        )
                        page, page_hash = _fetch_json(
                            transport=transport,
                            endpoint_name="results_today",
                            url=page_url,
                            username=username,
                            password=password,
                            now=now,
                            clock=clock,
                            sleeper=sleeper,
                        )
                        rows = page.get("results")
                        if not isinstance(rows, list):
                            raise _ProviderSyncError("provider_response_invalid")
                        collected.extend(rows)
                        page_hashes.append(page_hash)
                        total = page.get("total")
                        if len(rows) < 50 or (
                            isinstance(total, int) and len(collected) >= total
                        ):
                            pagination_complete = True
                            break
                    if not page_hashes:
                        raise _ProviderSyncError(
                            "provider_request_budget_exhausted"
                        )
                    if not pagination_complete:
                        raise _ProviderSyncError("provider_pagination_incomplete")
                    return {
                        "results": collected,
                        "page_sha256": page_hashes,
                    }, len(page_hashes), len(collected)

                response_payload, raw_sha256 = _get_or_fetch_shared_snapshot(
                    provider=source.source_key,
                    region=source.region_code,
                    scope_key=f"{provider_date.isoformat()}:{provider_region}",
                    data_kind=models.RaceDataSyncDataKind.RESULT,
                    registry_digest=route.registry_digest,
                    run_id=run_id,
                    now=now,
                    proposed_requests=route.request_budget,
                    clock=clock,
                    sleeper=sleeper,
                    fetcher=fetch_result_snapshot,
                )
            elif day_offset is not None and -7 <= day_offset < 0:
                capacity = reserve_race_data_transport_capacity(
                    provider=source.source_key,
                    region_code=source.region_code,
                    now=now,
                    proposed_requests=1,
                    max_response_bytes_per_request=_MAX_RESPONSE_BYTES,
                )
                if not capacity.allowed:
                    raise _ProviderSyncError(capacity.reason_code)
                result_url = build_the_racing_api_route_url(
                    registry=registry,
                    route_name="result_by_id",
                    region=provider_region,
                    race_id=source.external_race_id,
                    limit=0,
                    skip=0,
                )
                exact_result, raw_sha256 = _fetch_json(
                    transport=transport,
                    endpoint_name="result_by_id",
                    url=result_url,
                    username=username,
                    password=password,
                    now=now,
                    clock=clock,
                    sleeper=sleeper,
                    allow_not_found=True,
                )
                if exact_result.get("_not_found") is not True:
                    response_payload = {
                        "results": [
                            {
                                **exact_result,
                                "race_status": (
                                    exact_result.get("race_status") or "official"
                                ),
                            }
                        ]
                    }

            if response_payload is None:
                not_found.append(models.RaceDataSyncDataKind.RESULT)
            else:
                snapshot = parse_the_racing_api_live_results_payload(
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
                observation_hashes[models.RaceDataSyncDataKind.RESULT] = raw_sha256
                updated_by_kind[models.RaceDataSyncDataKind.RESULT] = None
                if normalized_race is None:
                    not_found.append(models.RaceDataSyncDataKind.RESULT)
                else:
                    normalized_status = (
                        str(normalized_race.get("race_status") or "")
                        .strip()
                        .casefold()
                    )
                    correction_marked = (
                        normalized_status in _TRA_CORRECTION_MARKERS
                    )
                    phase = (
                        models.RaceResultPhase.CORRECTED
                        if correction_marked
                        else models.RaceResultPhase.OFFICIAL
                        if normalized_status in route.entry.terminal_markers
                        else models.RaceResultPhase.PROVISIONAL
                    )
                    payload = _result_payload(
                        normalized_race=normalized_race,
                        region=source.region_code,
                        event=event,
                        source_key=source.source_key,
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
                        result_phase=phase,
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
                            "correction_marker": correction_marked,
                            "correction_marker_value": (
                                normalized_status if correction_marked else ""
                            ),
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
                        claim_guard=claim_guard,
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

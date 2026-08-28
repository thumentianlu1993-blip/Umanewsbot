"""Reviewed census and manifest boundary for race-data enrollment.

The census is read-only and accounts for every published event in its frozen
date window.  Applying a manifest is only allowed while every race-data
runtime, network, apply and public switch is off.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from stable import models
from stable.services import race_data_sync_control
from stable.services.race_data_sync_pipeline import resolve_race_data_provider_route
from stable.services.race_data_sync_policy import source_priority


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_RUNTIME_SWITCHES = (
    "RACE_DATA_SYNC_ENABLED",
    "RACE_DATA_SYNC_SCHEDULER_ENABLED",
    "RACE_DATA_SYNC_ALLOW_NETWORK",
    "RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED",
    "RACE_DATA_SYNC_RACECARD_APPLY_ENABLED",
    "RACE_DATA_SYNC_RESULT_APPLY_ENABLED",
    "RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED",
    "RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED",
    "RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED",
    "RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED",
)
_MANIFEST_PAYLOAD_FIELDS = {
    "schema_version",
    "candidate_commit",
    "created_at",
    "apply_expires_at",
    "census_cutoff",
    "census_sha256",
    "standing_policy_digest",
    "entries",
}
_MANIFEST_ENTRY_FIELDS = {
    "event_id",
    "year",
    "slug",
    "classification",
    "reason_code",
    "source_identity_id",
    "provider",
    "region_code",
    "identity_namespace",
    "route_digest",
    "registry_digest",
    "contract_digest",
    "proof_digest",
    "allowed_hosts",
    "allowed_path_prefixes",
    "request_budget",
    "minimum_interval_seconds",
    "data_kinds",
    "owner",
    "owner_generation",
    "owner_manifest_sha256",
    "event_snapshot_sha256",
    "entry_sha256",
}
_DISENROLL_MANIFEST_PAYLOAD_FIELDS = _MANIFEST_PAYLOAD_FIELDS | {"operation"}


def _canonical_sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _aware_iso(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be aware")
    return parsed


def _require_aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be aware")


@dataclass(frozen=True)
class StandingPolicyRoute:
    country_region: str
    provider: str
    region_code: str
    identity_namespace: str
    route_digest: str
    data_kinds: tuple[str, ...]


@dataclass(frozen=True)
class StandingPolicy:
    policy_id: str
    digest: str
    valid_from: datetime
    valid_until: datetime
    visibility_statuses: tuple[str, ...]
    event_statuses: tuple[str, ...]
    routes: tuple[StandingPolicyRoute, ...]


@dataclass(frozen=True)
class CensusEntry:
    event_id: int
    year: int
    slug: str
    classification: str
    reason_code: str
    source_identity_id: int | None
    provider: str
    region_code: str
    identity_namespace: str
    route_digest: str
    registry_digest: str
    contract_digest: str
    proof_digest: str
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    request_budget: int
    minimum_interval_seconds: int
    data_kinds: tuple[str, ...]
    owner: str
    owner_generation: int
    owner_manifest_sha256: str
    event_snapshot_sha256: str

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["data_kinds"] = list(self.data_kinds)
        value["allowed_hosts"] = list(self.allowed_hosts)
        value["allowed_path_prefixes"] = list(self.allowed_path_prefixes)
        return value


@dataclass(frozen=True)
class EnrollmentCensus:
    cutoff: str
    horizon_days: int
    standing_policy_digest: str
    entries: tuple[CensusEntry, ...]
    census_sha256: str

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def classification_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.classification] = counts.get(entry.classification, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "cutoff": self.cutoff,
            "horizon_days": self.horizon_days,
            "standing_policy_digest": self.standing_policy_digest,
            "total": self.total,
            "classification_counts": self.classification_counts,
            "entries": [entry.as_dict() for entry in self.entries],
            "census_sha256": self.census_sha256,
        }


@dataclass(frozen=True)
class EnrollmentManifest:
    payload: dict[str, Any]
    manifest_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {**self.payload, "manifest_sha256": self.manifest_sha256}


@dataclass(frozen=True)
class FutureEnrollmentProposal:
    census: EnrollmentCensus
    manifest: EnrollmentManifest | None
    selected_event_ids: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "census": self.census.as_dict(),
            "selected_event_ids": list(self.selected_event_ids),
            "manifest": self.manifest.as_dict() if self.manifest else None,
        }


def parse_standing_policy(value: dict[str, Any]) -> StandingPolicy:
    required = {
        "schema_version",
        "policy_id",
        "approved_by",
        "approved_at",
        "valid_from",
        "valid_until",
        "routes",
        "visibility_statuses",
        "event_statuses",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("standing policy schema is invalid")
    if value["schema_version"] != 1:
        raise ValueError("standing policy version is invalid")
    for label in ("policy_id", "approved_by"):
        if not isinstance(value[label], str) or not value[label].strip():
            raise ValueError(f"standing policy {label} is invalid")
    _aware_iso(value["approved_at"], "approved_at")
    valid_from = _aware_iso(value["valid_from"], "valid_from")
    valid_until = _aware_iso(value["valid_until"], "valid_until")
    if valid_until <= valid_from:
        raise ValueError("standing policy validity window is invalid")

    visibility = tuple(sorted(set(value["visibility_statuses"])))
    statuses = tuple(sorted(set(value["event_statuses"])))
    if (
        not visibility
        or any(item not in models.RaceEventVisibility.values for item in visibility)
        or not statuses
        or any(item not in models.RaceEventStatus.values for item in statuses)
    ):
        raise ValueError("standing policy event filters are invalid")

    routes = []
    route_keys = set()
    if not isinstance(value["routes"], list) or not value["routes"]:
        raise ValueError("standing policy routes are invalid")
    route_fields = {
        "country_region",
        "provider",
        "region_code",
        "identity_namespace",
        "route_digest",
        "data_kinds",
    }
    for raw in value["routes"]:
        if not isinstance(raw, dict) or set(raw) != route_fields:
            raise ValueError("standing policy route schema is invalid")
        if raw["country_region"] not in models.RacingRegion.values:
            raise ValueError("standing policy country region is invalid")
        for label in ("provider", "region_code", "identity_namespace"):
            if not isinstance(raw[label], str) or not raw[label].strip():
                raise ValueError(f"standing policy route {label} is invalid")
        if not isinstance(raw["route_digest"], str) or _SHA_RE.fullmatch(raw["route_digest"]) is None:
            raise ValueError("standing policy route digest is invalid")
        data_kinds = tuple(sorted(set(raw["data_kinds"])))
        if not data_kinds or any(kind not in models.RaceDataSyncDataKind.values for kind in data_kinds):
            raise ValueError("standing policy data kinds are invalid")
        key = (
            raw["country_region"],
            raw["provider"],
            raw["region_code"],
            raw["identity_namespace"],
        )
        if key in route_keys:
            raise ValueError("standing policy route is duplicated")
        route_keys.add(key)
        routes.append(
            StandingPolicyRoute(
                country_region=raw["country_region"],
                provider=raw["provider"],
                region_code=raw["region_code"],
                identity_namespace=raw["identity_namespace"],
                route_digest=raw["route_digest"],
                data_kinds=data_kinds,
            )
        )
    return StandingPolicy(
        policy_id=value["policy_id"],
        digest=_canonical_sha(value),
        valid_from=valid_from,
        valid_until=valid_until,
        visibility_statuses=visibility,
        event_statuses=statuses,
        routes=tuple(sorted(routes, key=lambda item: (item.country_region, item.provider))),
    )


def load_standing_policy_file(
    *, path: str | Path, expected_sha256: str
) -> dict[str, Any]:
    """Load one reviewed policy through a no-follow, size-bounded descriptor."""

    if _SHA_RE.fullmatch(expected_sha256 or "") is None:
        raise ValueError("standing policy expected SHA is invalid")
    source = Path(path)
    if not source.is_absolute():
        raise ValueError("standing policy path must be absolute")
    try:
        before = source.lstat()
    except OSError as exc:
        raise ValueError("standing policy file is unavailable") from exc
    if not stat.S_ISREG(before.st_mode) or source.is_symlink() or before.st_size > 1_000_000:
        raise ValueError("standing policy file is not an allowed regular file")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(source, flags)
        try:
            current = os.fstat(descriptor)
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_dev != before.st_dev
                or current.st_ino != before.st_ino
                or current.st_size != before.st_size
            ):
                raise ValueError("standing policy file identity changed")
            raw = b""
            while len(raw) <= 1_000_000:
                chunk = os.read(descriptor, min(65_536, 1_000_001 - len(raw)))
                if not chunk:
                    break
                raw += chunk
            if len(raw) > 1_000_000:
                raise ValueError("standing policy file is too large")
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ValueError("standing policy file could not be read safely") from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("standing policy file SHA mismatch")

    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("standing policy contains duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("standing policy JSON is invalid") from exc
    parse_standing_policy(value)
    return value


def _event_snapshot(
    *,
    event: models.RaceEvent,
    control: models.RaceEventProjectionControl | None,
    enrollment: models.RaceDataSyncEnrollment | None,
    source: models.RaceResultSourceIdentity | None,
    route: StandingPolicyRoute | None,
) -> str:
    return _canonical_sha(
        {
            "event": {
                "id": event.pk,
                "year": event.year,
                "slug": event.slug,
                "country_region": event.country_region,
                "local_date": event.local_date.isoformat() if event.local_date else None,
                "race_datetime": event.race_datetime.isoformat() if event.race_datetime else None,
                "status": event.status,
                "visibility_status": event.visibility_status,
                "manual_lock_flags": event.manual_lock_flags,
            },
            "owner": {
                "write_owner": control.write_owner if control else models.RaceEventProjectionWriteOwner.UNMANAGED,
                "generation": control.owner_generation if control else 0,
                "manifest_sha256": control.owner_manifest_sha256 if control else "",
            },
            "enrollment": {
                "state": enrollment.state if enrollment else "",
                "generation": enrollment.enrollment_generation if enrollment else 0,
                "manifest_sha256": enrollment.manifest_sha256 if enrollment else "",
            },
            "source": {
                "id": source.pk if source else None,
                "source_key": source.source_key if source else "",
                "region_code": source.region_code if source else "",
                "identity_namespace": source.identity_namespace if source else "",
                "external_race_id": source.external_race_id if source else "",
                "registry_digest": source.registry_digest if source else "",
            },
            "route": asdict(route) if route else None,
        }
    )


def build_race_data_enrollment_census(
    *, standing_policy: dict[str, Any], cutoff: datetime, horizon_days: int
) -> EnrollmentCensus:
    _require_aware(cutoff, "cutoff")
    if not 1 <= horizon_days <= 366:
        raise ValueError("horizon_days is invalid")
    policy = parse_standing_policy(standing_policy)
    end_at = cutoff + timedelta(days=horizon_days)
    end_date = end_at.date()
    candidate_events = list(
        models.RaceEvent.objects.filter(
            visibility_status=models.RaceEventVisibility.PUBLISHED,
            local_date__gte=cutoff.date() - timedelta(days=1),
            local_date__lte=end_date + timedelta(days=1),
        )
        .select_related("projection_control", "race_data_sync_enrollment")
        .prefetch_related("source_identities")
        .order_by("id")
    )
    events = []
    for event in candidate_events:
        if event.race_datetime is not None:
            if timezone.is_naive(event.race_datetime):
                continue
            if cutoff <= event.race_datetime <= end_at:
                events.append(event)
            continue
        try:
            event_zone = ZoneInfo(event.timezone_name)
            local_start = cutoff.astimezone(event_zone).date()
            local_end = end_at.astimezone(event_zone).date()
        except (KeyError, ValueError):
            local_start = cutoff.date()
            local_end = end_date
        if event.local_date is not None and local_start <= event.local_date <= local_end:
            events.append(event)
    duplicate_ids = set(
        models.RaceEventProductCanonicalLink.objects.filter(
            duplicate_event_id__in=[event.pk for event in events],
            is_active=True,
        ).values_list("duplicate_event_id", flat=True)
    )

    entries = []
    for event in events:
        control = getattr(event, "projection_control", None)
        enrollment = getattr(event, "race_data_sync_enrollment", None)
        owner = control.write_owner if control else models.RaceEventProjectionWriteOwner.UNMANAGED
        generation = control.owner_generation if control else 0
        owner_manifest = control.owner_manifest_sha256 if control else ""
        matching_routes = tuple(
            item for item in policy.routes if item.country_region == event.country_region
        )
        route = matching_routes[0] if len(matching_routes) == 1 else None
        source = None
        if len(matching_routes) > 1:
            ranked_routes = []
            for candidate_route in matching_routes:
                candidate_binding = resolve_race_data_provider_route(
                    provider=candidate_route.provider,
                    region=candidate_route.region_code,
                    identity_namespace=candidate_route.identity_namespace,
                    data_kinds=candidate_route.data_kinds,
                )
                candidate_sources = [
                    candidate
                    for candidate in event.source_identities.all()
                    if candidate.source_key == candidate_route.provider
                    and candidate.region_code == candidate_route.region_code
                    and candidate.identity_namespace
                    == candidate_route.identity_namespace
                ]
                if (
                    candidate_binding is None
                    or candidate_route.route_digest
                    != candidate_binding.route_digest
                    or len(candidate_sources) != 1
                    or race_data_sync_control.source_admission_reason(
                        source=candidate_sources[0],
                        route_digest=candidate_route.route_digest,
                        data_kinds=candidate_route.data_kinds,
                        now=cutoff,
                    )
                ):
                    continue
                ranked_routes.append(
                    (
                        -source_priority(candidate_binding.entry.source_class),
                        candidate_route.provider,
                        candidate_route.region_code,
                        candidate_route,
                        candidate_sources[0],
                    )
                )
            if ranked_routes:
                _priority, _provider, _region, route, source = sorted(
                    ranked_routes, key=lambda item: item[:3]
                )[0]
        route_binding = (
            resolve_race_data_provider_route(
                provider=route.provider,
                region=route.region_code,
                identity_namespace=route.identity_namespace,
                data_kinds=route.data_kinds,
            )
            if route is not None
            else None
        )
        reason = ""
        classification = "eligible"
        if not (policy.valid_from <= cutoff < policy.valid_until):
            reason = "standing_policy_expired"
        elif event.pk in duplicate_ids:
            reason = "canonical_duplicate"
        elif event.visibility_status not in policy.visibility_statuses:
            reason = "visibility_not_allowed"
        elif event.status not in policy.event_statuses:
            reason = "event_status_not_allowed"
        elif isinstance(event.manual_lock_flags, dict) and any(event.manual_lock_flags.values()):
            reason = "manual_lock_present"
        elif not matching_routes:
            reason = "standing_policy_route_missing"
        elif len(matching_routes) > 1 and route is None:
            reason = "standing_policy_route_ambiguous"
        elif route_binding is None:
            reason = "provider_route_unavailable"
        elif route.route_digest != route_binding.route_digest:
            reason = "standing_policy_route_drift"
        elif owner in {
            models.RaceEventProjectionWriteOwner.LIVE,
            models.RaceEventProjectionWriteOwner.HISTORICAL,
            models.RaceEventProjectionWriteOwner.MANUAL_PAUSED,
        }:
            reason = "writer_owner_conflict"
        else:
            candidates = (
                [source]
                if source is not None
                else [
                    candidate
                    for candidate in event.source_identities.all()
                    if candidate.source_key == route.provider
                    and candidate.region_code == route.region_code
                    and candidate.identity_namespace == route.identity_namespace
                ]
            )
            if len(candidates) != 1:
                reason = "source_identity_missing" if not candidates else "source_identity_ambiguous"
            else:
                source = candidates[0]
                source_reason = race_data_sync_control.source_admission_reason(
                    source=source,
                    route_digest=route.route_digest,
                    data_kinds=route.data_kinds,
                    now=cutoff,
                )
                if source_reason:
                    reason = source_reason
                elif owner == models.RaceEventProjectionWriteOwner.DATA_SYNC:
                    if (
                        enrollment is not None
                        and enrollment.state == models.RaceDataSyncEnrollmentState.ENROLLED
                        and enrollment.source_identity_id == source.pk
                        and enrollment.standing_policy_digest == policy.digest
                        and enrollment.route_digest == route.route_digest
                        and enrollment.projection_owner_generation == generation
                        and enrollment.manifest_sha256 == owner_manifest
                    ):
                        classification = "enrolled"
                    else:
                        classification = "eligible"
        if reason:
            classification = "blocked"
        snapshot = _event_snapshot(
            event=event,
            control=control,
            enrollment=enrollment,
            source=source,
            route=route,
        )
        entries.append(
            CensusEntry(
                event_id=event.pk,
                year=event.year,
                slug=event.slug,
                classification=classification,
                reason_code=reason,
                source_identity_id=source.pk if source else None,
                provider=route.provider if route else "",
                region_code=route.region_code if route else "",
                identity_namespace=route.identity_namespace if route else "",
                route_digest=route.route_digest if route else "",
                registry_digest=(
                    route_binding.registry_digest if route_binding else ""
                ),
                contract_digest=(
                    route_binding.contract_digest if route_binding else ""
                ),
                proof_digest=route_binding.proof_digest if route_binding else "",
                allowed_hosts=(
                    route_binding.allowed_hosts if route_binding else ()
                ),
                allowed_path_prefixes=(
                    route_binding.allowed_path_prefixes if route_binding else ()
                ),
                request_budget=(route_binding.request_budget if route_binding else 0),
                minimum_interval_seconds=(
                    route_binding.minimum_interval_seconds if route_binding else 0
                ),
                data_kinds=route.data_kinds if route else (),
                owner=owner,
                owner_generation=generation,
                owner_manifest_sha256=owner_manifest,
                event_snapshot_sha256=snapshot,
            )
        )
    payload = {
        "schema_version": 1,
        "cutoff": cutoff.isoformat(),
        "horizon_days": horizon_days,
        "standing_policy_digest": policy.digest,
        "entries": [entry.as_dict() for entry in entries],
    }
    return EnrollmentCensus(
        cutoff=cutoff.isoformat(),
        horizon_days=horizon_days,
        standing_policy_digest=policy.digest,
        entries=tuple(entries),
        census_sha256=_canonical_sha(payload),
    )


def build_race_data_enrollment_manifest(
    *,
    census: EnrollmentCensus,
    selected_event_ids: Iterable[int],
    candidate_commit: str,
    created_at: datetime,
    apply_expires_at: datetime,
) -> EnrollmentManifest:
    _require_aware(created_at, "created_at")
    _require_aware(apply_expires_at, "apply_expires_at")
    if not created_at < apply_expires_at <= created_at + timedelta(hours=24):
        raise ValueError("manifest apply window is invalid")
    if _COMMIT_RE.fullmatch(candidate_commit or "") is None:
        raise ValueError("candidate_commit is invalid")
    selected = tuple(sorted(set(selected_event_ids)))
    if not selected:
        raise ValueError("selected_event_ids is empty")
    by_id = {entry.event_id: entry for entry in census.entries}
    entries = []
    for event_id in selected:
        census_entry = by_id.get(event_id)
        if census_entry is None or census_entry.classification not in {"eligible", "enrolled"}:
            raise ValueError(f"event {event_id} is not eligible for enrollment")
        raw = census_entry.as_dict()
        raw["entry_sha256"] = _canonical_sha(raw)
        entries.append(raw)
    payload = {
        "schema_version": 1,
        "candidate_commit": candidate_commit,
        "created_at": created_at.isoformat(),
        "apply_expires_at": apply_expires_at.isoformat(),
        "census_cutoff": census.cutoff,
        "census_sha256": census.census_sha256,
        "standing_policy_digest": census.standing_policy_digest,
        "entries": entries,
    }
    return EnrollmentManifest(payload=payload, manifest_sha256=_canonical_sha(payload))


def build_race_data_disenrollment_manifest(
    *,
    census: EnrollmentCensus,
    selected_event_ids: Iterable[int],
    candidate_commit: str,
    created_at: datetime,
    apply_expires_at: datetime,
) -> EnrollmentManifest:
    """Build an exact reverse manifest for currently enrolled events."""

    _require_aware(created_at, "created_at")
    _require_aware(apply_expires_at, "apply_expires_at")
    if not created_at < apply_expires_at <= created_at + timedelta(hours=24):
        raise ValueError("manifest apply window is invalid")
    if _COMMIT_RE.fullmatch(candidate_commit or "") is None:
        raise ValueError("candidate_commit is invalid")
    selected = tuple(sorted(set(selected_event_ids)))
    if not selected:
        raise ValueError("selected_event_ids is empty")
    by_id = {entry.event_id: entry for entry in census.entries}
    entries = []
    for event_id in selected:
        census_entry = by_id.get(event_id)
        if census_entry is None or census_entry.classification != "enrolled":
            raise ValueError(f"event {event_id} is not enrolled for reverse manifest")
        if census_entry.owner != models.RaceEventProjectionWriteOwner.DATA_SYNC:
            raise ValueError(f"event {event_id} is not owned by data_sync")
        raw = census_entry.as_dict()
        raw["entry_sha256"] = _canonical_sha(raw)
        entries.append(raw)
    payload = {
        "schema_version": 1,
        "operation": "disenroll",
        "candidate_commit": candidate_commit,
        "created_at": created_at.isoformat(),
        "apply_expires_at": apply_expires_at.isoformat(),
        "census_cutoff": census.cutoff,
        "census_sha256": census.census_sha256,
        "standing_policy_digest": census.standing_policy_digest,
        "entries": entries,
    }
    return EnrollmentManifest(payload=payload, manifest_sha256=_canonical_sha(payload))


def build_future_race_data_enrollment_proposal(
    *,
    standing_policy: dict[str, Any],
    cutoff: datetime,
    horizon_days: int,
    max_events: int,
    candidate_commit: str,
    apply_expires_at: datetime,
) -> FutureEnrollmentProposal:
    """Discover newly eligible future events without mutating enrollment state."""

    if isinstance(max_events, bool) or not isinstance(max_events, int) or not 1 <= max_events <= 100:
        raise ValueError("max_events is invalid")
    census = build_race_data_enrollment_census(
        standing_policy=standing_policy,
        cutoff=cutoff,
        horizon_days=horizon_days,
    )
    selected = tuple(
        entry.event_id
        for entry in census.entries
        if entry.classification == "eligible"
    )[:max_events]
    manifest = None
    if selected:
        manifest = build_race_data_enrollment_manifest(
            census=census,
            selected_event_ids=selected,
            candidate_commit=candidate_commit,
            created_at=cutoff,
            apply_expires_at=apply_expires_at,
        )
    return FutureEnrollmentProposal(
        census=census,
        manifest=manifest,
        selected_event_ids=selected,
    )


def _assert_runtime_closed() -> None:
    if any(getattr(settings, name, False) is True for name in _RUNTIME_SWITCHES):
        raise ValueError("all race-data runtime switches must be off before enrollment apply")


def apply_race_data_enrollment_manifest(
    *,
    manifest: dict[str, Any],
    expected_manifest_sha256: str,
    current_commit: str,
    now: datetime,
    allow_runtime_open: bool = False,
) -> tuple[race_data_sync_control.ControlDecision, ...]:
    if not allow_runtime_open:
        _assert_runtime_closed()
    _require_aware(now, "now")
    if _SHA_RE.fullmatch(expected_manifest_sha256 or "") is None:
        raise ValueError("expected_manifest_sha256 is invalid")
    if not isinstance(manifest, dict):
        raise ValueError("manifest is invalid")
    if set(manifest) != _MANIFEST_PAYLOAD_FIELDS | {"manifest_sha256"}:
        raise ValueError("manifest schema is invalid")
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("manifest_sha256") != expected_manifest_sha256 or _canonical_sha(payload) != expected_manifest_sha256:
        raise ValueError("manifest digest mismatch")
    if _COMMIT_RE.fullmatch(current_commit or "") is None or payload.get("candidate_commit") != current_commit:
        raise ValueError("manifest candidate commit mismatch")
    created_at = _aware_iso(payload.get("created_at"), "created_at")
    apply_expires_at = _aware_iso(payload.get("apply_expires_at"), "apply_expires_at")
    if not created_at < apply_expires_at <= created_at + timedelta(hours=24):
        raise ValueError("manifest apply window is invalid")
    if now < created_at:
        raise ValueError("manifest is not active yet")
    if now >= apply_expires_at:
        raise ValueError("manifest has expired")
    _aware_iso(payload.get("census_cutoff"), "census_cutoff")
    for label in ("census_sha256", "standing_policy_digest"):
        if _SHA_RE.fullmatch(payload.get(label) or "") is None:
            raise ValueError(f"manifest {label} is invalid")
    entries = payload.get("entries")
    if payload.get("schema_version") != 1 or not isinstance(entries, list) or not entries:
        raise ValueError("manifest schema is invalid")
    event_ids = [entry.get("event_id") for entry in entries if isinstance(entry, dict)]
    if len(event_ids) != len(entries) or event_ids != sorted(set(event_ids)):
        raise ValueError("manifest entries must have unique sorted event IDs")

    decisions = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _MANIFEST_ENTRY_FIELDS:
            raise ValueError("manifest entry schema is invalid")
        entry_payload = {key: value for key, value in entry.items() if key != "entry_sha256"}
        if entry.get("entry_sha256") != _canonical_sha(entry_payload):
            raise ValueError("manifest entry digest mismatch")
        if (
            entry.get("classification") not in {"eligible", "enrolled"}
            or entry.get("reason_code") != ""
            or not isinstance(entry.get("source_identity_id"), int)
            or isinstance(entry.get("source_identity_id"), bool)
            or entry.get("owner") not in models.RaceEventProjectionWriteOwner.values
            or not isinstance(entry.get("owner_generation"), int)
            or isinstance(entry.get("owner_generation"), bool)
            or entry.get("owner_generation") < 0
            or _SHA_RE.fullmatch(entry.get("route_digest") or "") is None
            or _SHA_RE.fullmatch(entry.get("event_snapshot_sha256") or "") is None
        ):
            raise ValueError("manifest entry admission is invalid")
        data_kinds = tuple(sorted(set(entry.get("data_kinds", ()))))
        if (
            not data_kinds
            or list(data_kinds) != entry.get("data_kinds")
            or any(kind not in models.RaceDataSyncDataKind.values for kind in data_kinds)
        ):
            raise ValueError("manifest entry data kinds are invalid")
        for label in ("registry_digest", "contract_digest", "proof_digest"):
            if _SHA_RE.fullmatch(entry.get(label) or "") is None:
                raise ValueError(f"manifest entry {label} is invalid")
        for label in ("allowed_hosts", "allowed_path_prefixes"):
            values = entry.get(label)
            if (
                not isinstance(values, list)
                or not values
                or values != sorted(set(values))
                or any(not isinstance(value, str) or not value for value in values)
            ):
                raise ValueError(f"manifest entry {label} is invalid")
        if (
            isinstance(entry.get("request_budget"), bool)
            or not isinstance(entry.get("request_budget"), int)
            or entry["request_budget"] <= 0
            or isinstance(entry.get("minimum_interval_seconds"), bool)
            or not isinstance(entry.get("minimum_interval_seconds"), int)
            or entry["minimum_interval_seconds"] <= 0
        ):
            raise ValueError("manifest entry route budget is invalid")
        with transaction.atomic():
            models.RaceEventLifecycleControl.objects.select_for_update().filter(
                event_id=entry["event_id"]
            ).first()
            event = models.RaceEvent.objects.select_for_update().get(pk=entry["event_id"])
            control, control_created = (
                models.RaceEventProjectionControl.objects.get_or_create(event=event)
            )
            control = models.RaceEventProjectionControl.objects.select_for_update().get(
                pk=control.pk
            )
            tracking, tracking_created = (
                models.RaceEventLiveTracking.objects.get_or_create(event=event)
            )
            tracking = models.RaceEventLiveTracking.objects.select_for_update().get(
                pk=tracking.pk
            )
            enrollment = (
                models.RaceDataSyncEnrollment.objects.select_for_update()
                .filter(event=event)
                .first()
            )
            source_hint = (
                models.RaceResultSourceIdentity.objects.filter(
                    pk=entry["source_identity_id"],
                    event=event,
                )
                .values("source_key")
                .first()
            )
            if tracking is not None:
                tuple(
                    models.RaceEventLiveProviderCheckpoint.objects.select_for_update()
                    .filter(tracking=tracking)
                    .order_by("source_key", "data_kind")
                )
            source = (
                models.RaceResultSourceIdentity.objects.select_for_update()
                .filter(pk=entry["source_identity_id"], event=event)
                .first()
            )
            if (
                source_hint is None
                or source is None
                or source.source_key != source_hint["source_key"]
            ):
                source = None
            route = StandingPolicyRoute(
                country_region=event.country_region,
                provider=entry["provider"],
                region_code=entry["region_code"],
                identity_namespace=entry["identity_namespace"],
                route_digest=entry["route_digest"],
                data_kinds=tuple(entry["data_kinds"]),
            )
            route_binding = resolve_race_data_provider_route(
                provider=route.provider,
                region=route.region_code,
                identity_namespace=route.identity_namespace,
                data_kinds=route.data_kinds,
            )
            if route_binding is None or (
                route_binding.route_digest != entry["route_digest"]
                or route_binding.registry_digest != entry["registry_digest"]
                or route_binding.contract_digest != entry["contract_digest"]
                or route_binding.proof_digest != entry["proof_digest"]
                or list(route_binding.allowed_hosts) != entry["allowed_hosts"]
                or list(route_binding.allowed_path_prefixes)
                != entry["allowed_path_prefixes"]
                or route_binding.request_budget != entry["request_budget"]
                or route_binding.minimum_interval_seconds
                != entry["minimum_interval_seconds"]
            ):
                decisions.append(
                    race_data_sync_control.ControlDecision(
                        "rejected",
                        "provider_route_drift",
                        event.pk,
                        control.owner_generation if control else 0,
                    )
                )
                transaction.set_rollback(True)
                continue
            if tracking_created and (
                control.write_owner == models.RaceEventProjectionWriteOwner.DATA_SYNC
                or enrollment is not None
            ):
                decisions.append(
                    race_data_sync_control.ControlDecision(
                        "rejected",
                        "enrollment_missing",
                        event.pk,
                        control.owner_generation,
                    )
                )
                transaction.set_rollback(True)
                continue
            if (
                control is not None
                and enrollment is not None
                and source is not None
                and control.write_owner
                == models.RaceEventProjectionWriteOwner.DATA_SYNC
                and control.owner_manifest_sha256 == expected_manifest_sha256
                and enrollment.state
                == models.RaceDataSyncEnrollmentState.ENROLLED
                and enrollment.manifest_sha256 == expected_manifest_sha256
                and enrollment.entry_sha256 == entry["entry_sha256"]
                and enrollment.source_identity_id == source.pk
                and enrollment.route_digest == entry["route_digest"]
                and enrollment.standing_policy_digest
                == payload["standing_policy_digest"]
                and enrollment.projection_owner_generation
                == control.owner_generation
                and enrollment.enrollment_generation == control.owner_generation
            ):
                decisions.append(
                    race_data_sync_control.ControlDecision(
                        "replay", "", event.pk, control.owner_generation
                    )
                )
                continue
            snapshot = _event_snapshot(
                event=event,
                control=control,
                enrollment=enrollment,
                source=source,
                route=route,
            )
            if snapshot != entry["event_snapshot_sha256"]:
                decisions.append(
                    race_data_sync_control.ControlDecision(
                        "rejected",
                        "event_snapshot_drift",
                        event.pk,
                        control.owner_generation if control else 0,
                    )
                )
                transaction.set_rollback(True)
                continue
            if entry["owner"] == models.RaceEventProjectionWriteOwner.DATA_SYNC:
                decision = race_data_sync_control.rotate_enrollment(
                    event_id=event.pk,
                    source_identity_id=entry["source_identity_id"],
                    standing_policy_digest=payload["standing_policy_digest"],
                    route_digest=entry["route_digest"],
                    event_snapshot_sha256=entry["event_snapshot_sha256"],
                    successor_manifest_sha256=expected_manifest_sha256,
                    successor_entry_sha256=entry["entry_sha256"],
                    expected_manifest_sha256=entry["owner_manifest_sha256"],
                    expected_owner_generation=entry["owner_generation"],
                    data_kinds=entry["data_kinds"],
                    now=now,
                )
            else:
                decision = race_data_sync_control.acquire_enrollment(
                    event_id=event.pk,
                    source_identity_id=entry["source_identity_id"],
                    standing_policy_digest=payload["standing_policy_digest"],
                    route_digest=entry["route_digest"],
                    event_snapshot_sha256=entry["event_snapshot_sha256"],
                    manifest_sha256=expected_manifest_sha256,
                    entry_sha256=entry["entry_sha256"],
                    expected_owner=entry["owner"],
                    expected_owner_generation=entry["owner_generation"],
                    data_kinds=entry["data_kinds"],
                    now=now,
                )
            decisions.append(decision)
            if decision.action == "rejected" and (control_created or tracking_created):
                transaction.set_rollback(True)
    return tuple(decisions)


def apply_race_data_disenrollment_manifest(
    *,
    manifest: dict[str, Any],
    expected_manifest_sha256: str,
    current_commit: str,
    now: datetime,
) -> tuple[race_data_sync_control.ControlDecision, ...]:
    """Release only the events bound by one current-baseline reverse manifest."""

    _assert_runtime_closed()
    _require_aware(now, "now")
    if _SHA_RE.fullmatch(expected_manifest_sha256 or "") is None:
        raise ValueError("expected_manifest_sha256 is invalid")
    if not isinstance(manifest, dict):
        raise ValueError("manifest is invalid")
    if set(manifest) != _DISENROLL_MANIFEST_PAYLOAD_FIELDS | {"manifest_sha256"}:
        raise ValueError("disenrollment manifest schema is invalid")
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if (
        manifest.get("manifest_sha256") != expected_manifest_sha256
        or _canonical_sha(payload) != expected_manifest_sha256
    ):
        raise ValueError("manifest digest mismatch")
    if payload.get("schema_version") != 1 or payload.get("operation") != "disenroll":
        raise ValueError("disenrollment manifest operation is invalid")
    if (
        _COMMIT_RE.fullmatch(current_commit or "") is None
        or payload.get("candidate_commit") != current_commit
    ):
        raise ValueError("manifest candidate commit mismatch")
    created_at = _aware_iso(payload.get("created_at"), "created_at")
    apply_expires_at = _aware_iso(payload.get("apply_expires_at"), "apply_expires_at")
    if not created_at < apply_expires_at <= created_at + timedelta(hours=24):
        raise ValueError("manifest apply window is invalid")
    if now < created_at:
        raise ValueError("manifest is not active yet")
    if now >= apply_expires_at:
        raise ValueError("manifest has expired")
    _aware_iso(payload.get("census_cutoff"), "census_cutoff")
    for label in ("census_sha256", "standing_policy_digest"):
        if _SHA_RE.fullmatch(payload.get(label) or "") is None:
            raise ValueError(f"manifest {label} is invalid")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("disenrollment manifest entries are invalid")
    event_ids = [entry.get("event_id") for entry in entries if isinstance(entry, dict)]
    if len(event_ids) != len(entries) or event_ids != sorted(set(event_ids)):
        raise ValueError("manifest entries must have unique sorted event IDs")

    decisions = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _MANIFEST_ENTRY_FIELDS:
            raise ValueError("manifest entry schema is invalid")
        entry_payload = {
            key: value for key, value in entry.items() if key != "entry_sha256"
        }
        if entry.get("entry_sha256") != _canonical_sha(entry_payload):
            raise ValueError("manifest entry digest mismatch")
        if (
            entry.get("classification") != "enrolled"
            or entry.get("reason_code") != ""
            or entry.get("owner") != models.RaceEventProjectionWriteOwner.DATA_SYNC
            or not isinstance(entry.get("source_identity_id"), int)
            or isinstance(entry.get("source_identity_id"), bool)
            or not isinstance(entry.get("owner_generation"), int)
            or isinstance(entry.get("owner_generation"), bool)
            or entry.get("owner_generation") < 1
            or _SHA_RE.fullmatch(entry.get("owner_manifest_sha256") or "") is None
            or _SHA_RE.fullmatch(entry.get("route_digest") or "") is None
            or _SHA_RE.fullmatch(entry.get("event_snapshot_sha256") or "") is None
        ):
            raise ValueError("disenrollment manifest entry admission is invalid")
        data_kinds = tuple(sorted(set(entry.get("data_kinds", ()))))
        if (
            not data_kinds
            or list(data_kinds) != entry.get("data_kinds")
            or any(kind not in models.RaceDataSyncDataKind.values for kind in data_kinds)
        ):
            raise ValueError("manifest entry data kinds are invalid")

        with transaction.atomic():
            models.RaceEventLifecycleControl.objects.select_for_update().filter(
                event_id=entry["event_id"]
            ).first()
            event = models.RaceEvent.objects.select_for_update().get(pk=entry["event_id"])
            control = (
                models.RaceEventProjectionControl.objects.select_for_update()
                .filter(event=event)
                .first()
            )
            tracking = (
                models.RaceEventLiveTracking.objects.select_for_update()
                .filter(event=event)
                .first()
            )
            enrollment = (
                models.RaceDataSyncEnrollment.objects.select_for_update()
                .filter(event=event)
                .first()
            )
            if tracking is not None:
                tuple(
                    models.RaceEventLiveProviderCheckpoint.objects.select_for_update()
                    .filter(tracking=tracking)
                    .order_by("source_key", "data_kind")
                )
            source = (
                models.RaceResultSourceIdentity.objects.select_for_update()
                .filter(pk=entry["source_identity_id"], event=event)
                .first()
            )
            route = StandingPolicyRoute(
                country_region=event.country_region,
                provider=entry["provider"],
                region_code=entry["region_code"],
                identity_namespace=entry["identity_namespace"],
                route_digest=entry["route_digest"],
                data_kinds=tuple(entry["data_kinds"]),
            )
            snapshot = _event_snapshot(
                event=event,
                control=control,
                enrollment=enrollment,
                source=source,
                route=route,
            )
            if snapshot != entry["event_snapshot_sha256"]:
                decisions.append(
                    race_data_sync_control.ControlDecision(
                        "rejected",
                        "event_snapshot_drift",
                        event.pk,
                        control.owner_generation if control else 0,
                    )
                )
                continue
            decisions.append(
                race_data_sync_control.disenroll(
                    event_id=event.pk,
                    expected_manifest_sha256=entry["owner_manifest_sha256"],
                    expected_owner_generation=entry["owner_generation"],
                    now=now,
                )
            )
    return tuple(decisions)

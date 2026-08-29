from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from stable import models
from stable.services.race_data_sync_control import (
    RaceDataSyncClaim,
    lock_and_validate_race_data_sync_claim_for_apply,
)
from stable.services.race_data_sync_policy import (
    arbitrate_source_value,
    calculate_next_poll_at,
    normalize_source_class,
    source_priority,
)
from stable.services.race_event_public_cache import invalidate_public_race_cache


_SHA256_LENGTH = 64
_REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "external_race_id",
    "off_time",
    "region",
    "course",
    "race_name",
    "race_status",
    "participants",
}
_OPTIONAL_TOP_LEVEL_KEYS = {"local_start_time", "timezone_name"}
_LEGACY_RECONCILE_REQUIRED_KEYS = _REQUIRED_TOP_LEVEL_KEYS - {"off_time"}
_CONTRACT_KEYS = {
    "schema_version",
    "provider",
    "region",
    "data_kind",
    "contract_version",
    "contract_digest",
    "registry_digest",
    "source_class",
    "automation_allowed",
    "allowed_fields",
}
_PARTICIPANT_KEYS = {
    "external_runner_id",
    "horse_name",
    "number",
    "draw",
    "jockey_name",
    "jockey_id",
    "trainer_name",
    "carried_weight",
    "status",
    "odds",
    "popularity",
}
_NON_WRITABLE_PARTICIPANT_METADATA_KEYS = frozenset({"jockey_id"})
_PARTICIPANT_STATUSES = {
    models.RaceRunnerStatus.DECLARED,
    models.RaceRunnerStatus.SCRATCHED,
    models.RaceRunnerStatus.WITHDRAWN,
    models.RaceRunnerStatus.REINSTATED,
    models.RaceRunnerStatus.NON_RUNNER,
}
_SECRET_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "password",
    "signature",
    "access_token",
    "secret",
)


@dataclass(frozen=True)
class NormalizedRacecardObservation:
    normalized_payload: dict[str, Any]
    normalized_sha256: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class RacecardReconciliationDecision:
    status: str
    reason: str
    event_id: int | None = None
    observation_id: int | None = None
    claim_invalidated: bool = False


@dataclass(frozen=True)
class RawCleanupResult:
    cleaned: int
    cleaned_bytes: int
    held: int
    skipped: int


@dataclass(frozen=True)
class RaceDataSyncCapacityLimits:
    raw_max_compressed_bytes: int
    raw_max_uncompressed_bytes: int
    provider_region_daily_bytes: int
    provider_region_daily_requests: int
    artifact_high_water_bytes: int
    artifact_low_water_bytes: int
    min_free_disk_bytes: int
    cleanup_max_rows: int
    cleanup_max_bytes: int
    hold_alert_bytes: int

    @classmethod
    def from_settings(cls) -> "RaceDataSyncCapacityLimits":
        limits = cls(
            raw_max_compressed_bytes=int(
                getattr(settings, "RACE_DATA_RAW_MAX_COMPRESSED_BYTES", 0)
            ),
            raw_max_uncompressed_bytes=int(
                getattr(settings, "RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES", 0)
            ),
            provider_region_daily_bytes=int(
                getattr(settings, "RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES", 0)
            ),
            provider_region_daily_requests=int(
                getattr(settings, "RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS", 0)
            ),
            artifact_high_water_bytes=int(
                getattr(settings, "RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES", 0)
            ),
            artifact_low_water_bytes=int(
                getattr(settings, "RACE_DATA_RAW_ROOT_LOW_WATER_BYTES", 0)
            ),
            min_free_disk_bytes=int(
                getattr(settings, "RACE_DATA_RAW_MIN_FREE_DISK_BYTES", 0)
            ),
            cleanup_max_rows=int(
                getattr(settings, "RACE_DATA_RAW_CLEANUP_MAX_ROWS", 0)
            ),
            cleanup_max_bytes=int(
                getattr(settings, "RACE_DATA_RAW_CLEANUP_MAX_BYTES", 0)
            ),
            hold_alert_bytes=int(
                getattr(settings, "RACE_DATA_RAW_HOLD_ALERT_BYTES", 0)
            ),
        )
        positive = (
            limits.raw_max_compressed_bytes,
            limits.raw_max_uncompressed_bytes,
            limits.provider_region_daily_bytes,
            limits.provider_region_daily_requests,
            limits.artifact_high_water_bytes,
            limits.artifact_low_water_bytes,
            limits.min_free_disk_bytes,
            limits.cleanup_max_rows,
            limits.cleanup_max_bytes,
            limits.hold_alert_bytes,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("race data capacity limits must be positive")
        if limits.raw_max_uncompressed_bytes < limits.raw_max_compressed_bytes:
            raise ValueError("race data raw payload limits are inconsistent")
        if limits.artifact_high_water_bytes <= limits.artifact_low_water_bytes:
            raise ValueError("race data artifact watermarks are inconsistent")
        return limits


@dataclass(frozen=True)
class RaceDataSyncCapacityDecision:
    allowed: bool
    reason_code: str


def evaluate_race_data_capacity(
    *,
    limits: RaceDataSyncCapacityLimits,
    proposed_compressed_bytes: int,
    proposed_uncompressed_bytes: int,
    provider_region_daily_bytes: int,
    provider_region_daily_requests: int,
    artifact_root_bytes: int,
    free_disk_bytes: int,
    hold_bytes: int,
    capacity_circuit_open: bool,
    cleanup_failed: bool,
) -> RaceDataSyncCapacityDecision:
    """Pure pre-transport capacity admission.

    Callers reserve their worst-case payload sizes.  A rejection must happen
    before constructing transport or issuing a network request.
    """

    counters = (
        proposed_compressed_bytes,
        proposed_uncompressed_bytes,
        provider_region_daily_bytes,
        provider_region_daily_requests,
        artifact_root_bytes,
        free_disk_bytes,
        hold_bytes,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counters):
        raise ValueError("race data capacity counters are invalid")
    if cleanup_failed:
        return RaceDataSyncCapacityDecision(False, "artifact_capacity_cleanup_failed")
    if hold_bytes >= limits.hold_alert_bytes:
        return RaceDataSyncCapacityDecision(False, "artifact_capacity_hold_exceeded")
    if capacity_circuit_open and artifact_root_bytes > limits.artifact_low_water_bytes:
        return RaceDataSyncCapacityDecision(False, "artifact_capacity_circuit_open")
    if proposed_compressed_bytes > limits.raw_max_compressed_bytes:
        return RaceDataSyncCapacityDecision(False, "artifact_payload_compressed_too_large")
    if proposed_uncompressed_bytes > limits.raw_max_uncompressed_bytes:
        return RaceDataSyncCapacityDecision(False, "artifact_payload_uncompressed_too_large")
    if (
        provider_region_daily_bytes + proposed_compressed_bytes
        > limits.provider_region_daily_bytes
    ):
        return RaceDataSyncCapacityDecision(False, "artifact_daily_bytes_exceeded")
    if provider_region_daily_requests + 1 > limits.provider_region_daily_requests:
        return RaceDataSyncCapacityDecision(False, "artifact_daily_requests_exceeded")
    if artifact_root_bytes + proposed_compressed_bytes > limits.artifact_high_water_bytes:
        return RaceDataSyncCapacityDecision(False, "artifact_root_high_water")
    if free_disk_bytes - proposed_compressed_bytes < limits.min_free_disk_bytes:
        return RaceDataSyncCapacityDecision(False, "artifact_min_free_disk")
    return RaceDataSyncCapacityDecision(True, "")


def inspect_race_data_artifact_capacity(
    *, artifact_roots: tuple[str, ...]
) -> tuple[int, int]:
    if not artifact_roots:
        raise ValueError("race data artifact roots are not configured")
    total_bytes = 0
    free_bytes: list[int] = []
    for raw_root in artifact_roots:
        root = Path(raw_root)
        try:
            root_stat = root.lstat()
        except OSError as exc:
            raise ValueError("race data artifact root is unavailable") from exc
        if root.is_symlink() or not stat.S_ISDIR(root_stat.st_mode):
            raise ValueError("race data artifact root is unsafe")
        try:
            filesystem = os.statvfs(root)
        except OSError as exc:
            raise ValueError("race data artifact filesystem is unavailable") from exc
        free_bytes.append(filesystem.f_bavail * filesystem.f_frsize)
        for directory, directory_names, filenames in os.walk(
            root, followlinks=False
        ):
            directory_path = Path(directory)
            directory_names[:] = [
                name
                for name in directory_names
                if not (directory_path / name).is_symlink()
            ]
            for filename in filenames:
                candidate = directory_path / filename
                try:
                    candidate_stat = candidate.lstat()
                except OSError:
                    continue
                if stat.S_ISREG(candidate_stat.st_mode) and not candidate.is_symlink():
                    total_bytes += candidate_stat.st_size
    return total_bytes, min(free_bytes)


def reserve_race_data_transport_capacity(
    *,
    provider: str,
    region_code: str,
    now: datetime,
    proposed_requests: int,
    max_response_bytes_per_request: int,
) -> RaceDataSyncCapacityDecision:
    """Atomically reserve a provider/region daily budget before transport."""

    if not isinstance(now, datetime) or timezone.is_naive(now):
        raise ValueError("now must be aware")
    if (
        not isinstance(provider, str)
        or not provider
        or provider != provider.strip()
        or len(provider) > 64
        or not isinstance(region_code, str)
        or not region_code
        or region_code != region_code.strip()
        or len(region_code) > 32
    ):
        raise ValueError("capacity scope is invalid")
    if (
        isinstance(proposed_requests, bool)
        or not isinstance(proposed_requests, int)
        or not 1 <= proposed_requests <= 100
        or isinstance(max_response_bytes_per_request, bool)
        or not isinstance(max_response_bytes_per_request, int)
        or max_response_bytes_per_request <= 0
    ):
        raise ValueError("capacity reservation is invalid")
    limits = RaceDataSyncCapacityLimits.from_settings()
    if max_response_bytes_per_request > limits.raw_max_compressed_bytes:
        return RaceDataSyncCapacityDecision(
            False, "artifact_payload_compressed_too_large"
        )
    proposed_bytes = proposed_requests * max_response_bytes_per_request
    artifact_bytes, free_disk_bytes = inspect_race_data_artifact_capacity(
        artifact_roots=tuple(
            str(value)
            for value in getattr(settings, "RACE_DATA_RAW_ARTIFACT_ROOTS", ())
            if str(value)
        )
    )
    hold_bytes = int(
        models.RaceResultObservation.objects.filter(
            field_provenance__raw_hold=True,
            raw_size_bytes__isnull=False,
        ).aggregate(total=Sum("raw_size_bytes"))["total"]
        or 0
    )
    if hold_bytes >= limits.hold_alert_bytes:
        return RaceDataSyncCapacityDecision(
            False, "artifact_capacity_hold_exceeded"
        )
    if artifact_bytes + proposed_bytes > limits.artifact_high_water_bytes:
        return RaceDataSyncCapacityDecision(False, "artifact_root_high_water")
    if free_disk_bytes - proposed_bytes < limits.min_free_disk_bytes:
        return RaceDataSyncCapacityDecision(False, "artifact_min_free_disk")

    with transaction.atomic():
        ledger, _created = (
            models.RaceDataTransportCapacityLedger.objects.select_for_update()
            .get_or_create(
                provider=provider,
                region_code=region_code,
                usage_date=now.date(),
            )
        )
        if (
            ledger.request_count + proposed_requests
            > limits.provider_region_daily_requests
        ):
            return RaceDataSyncCapacityDecision(
                False, "artifact_daily_requests_exceeded"
            )
        if (
            ledger.budgeted_response_bytes + proposed_bytes
            > limits.provider_region_daily_bytes
        ):
            return RaceDataSyncCapacityDecision(
                False, "artifact_daily_bytes_exceeded"
            )
        ledger.request_count += proposed_requests
        ledger.budgeted_response_bytes += proposed_bytes
        ledger.save(
            update_fields=(
                "request_count",
                "budgeted_response_bytes",
                "updated_at",
            )
        )
    return RaceDataSyncCapacityDecision(True, "")


class _RacecardNeedsReview(Exception):
    def __init__(self, *, reason: str, event_id: int, observation_id: int, changes=()):
        super().__init__(reason)
        self.reason = reason
        self.event_id = event_id
        self.observation_id = observation_id
        self.changes = tuple(changes)


@dataclass(frozen=True)
class RaceDataSyncFlags:
    enabled: bool
    providers: frozenset[str]
    regions: frozenset[str]
    fields: frozenset[str]
    data_kinds: frozenset[str]
    scheduler_enabled: bool
    allow_network: bool
    schedule_apply_enabled: bool
    racecard_apply_enabled: bool
    result_apply_enabled: bool
    result_public_enabled: bool
    correction_apply_enabled: bool

    @classmethod
    def from_settings(cls) -> "RaceDataSyncFlags":
        return cls(
            enabled=bool(getattr(settings, "RACE_DATA_SYNC_ENABLED", False)),
            providers=frozenset(
                str(value).strip()
                for value in getattr(
                    settings, "RACE_DATA_SYNC_ENABLED_PROVIDERS", ()
                )
                if str(value).strip()
            ),
            regions=frozenset(
                str(value).strip()
                for value in getattr(
                    settings, "RACE_DATA_SYNC_ENABLED_REGIONS", ()
                )
                if str(value).strip()
            ),
            fields=frozenset(
                str(value).strip()
                for value in getattr(
                    settings, "RACE_DATA_SYNC_ENABLED_FIELDS", ()
                )
                if str(value).strip()
            ),
            data_kinds=frozenset(
                str(value).strip()
                for value in getattr(
                    settings, "RACE_DATA_SYNC_ENABLED_DATA_KINDS", ()
                )
                if str(value).strip()
            ),
            scheduler_enabled=bool(
                getattr(settings, "RACE_DATA_SYNC_SCHEDULER_ENABLED", False)
            ),
            allow_network=bool(
                getattr(settings, "RACE_DATA_SYNC_ALLOW_NETWORK", False)
            ),
            schedule_apply_enabled=bool(
                getattr(settings, "RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED", False)
            ),
            racecard_apply_enabled=bool(
                getattr(settings, "RACE_DATA_SYNC_RACECARD_APPLY_ENABLED", False)
            ),
            result_apply_enabled=bool(
                getattr(settings, "RACE_DATA_SYNC_RESULT_APPLY_ENABLED", False)
            ),
            result_public_enabled=bool(
                getattr(settings, "RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED", False)
            ),
            correction_apply_enabled=bool(
                getattr(settings, "RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED", False)
            ),
        )

    def allows(self, *, provider: str, region: str, field_name: str) -> bool:
        return bool(
            self.enabled
            and provider in self.providers
            and region in self.regions
            and field_name in self.fields
        )

    def allows_data_kind(self, data_kind: str) -> bool:
        return bool(self.enabled and data_kind in self.data_kinds)

    def apply_enabled_for(self, data_kind: str) -> bool:
        if not self.allows_data_kind(data_kind):
            return False
        return {
            "race_time": self.schedule_apply_enabled,
            "racecard": self.racecard_apply_enabled,
            "result": self.result_apply_enabled,
        }.get(data_kind, False)


@dataclass(frozen=True)
class RaceDataProviderRosterEntry:
    provider: str
    regions: tuple[str, ...]
    enabled_regions: tuple[str, ...]
    source_class: str
    adapter_status: str
    transport_enabled: bool
    apply_enabled: bool
    contract_version: str
    contract_digest: str
    allowed_fields: tuple[str, ...]
    identity_namespaces: tuple[str, ...]
    data_kinds: tuple[str, ...]
    enabled_data_kinds: tuple[str, ...]
    terminal_markers: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    request_budget: int
    minimum_interval_seconds: int
    automation_allowed: bool
    proof_digest: str


@dataclass(frozen=True)
class RaceDataProviderRoster:
    schema_version: int
    registry_digest: str
    entries: tuple[RaceDataProviderRosterEntry, ...]

    def verify_digest(self) -> bool:
        return self.registry_digest == _provider_roster_digest(
            schema_version=self.schema_version,
            entries=self.entries,
        )

    def resolve(
        self, *, provider: str, region: str, field_name: str
    ) -> RaceDataProviderRosterEntry | None:
        if not self.verify_digest():
            return None
        return next(
            (
                entry
                for entry in self.entries
                if entry.provider == provider
                and region in entry.regions
                and region in entry.enabled_regions
                and field_name in entry.allowed_fields
                and entry.adapter_status == "implemented"
                and entry.transport_enabled
                and entry.apply_enabled
            ),
            None,
        )

    def resolve_route(
        self,
        *,
        provider: str,
        region: str,
        identity_namespace: str,
        data_kind: str,
    ) -> RaceDataProviderRosterEntry | None:
        if not self.verify_digest():
            return None
        return next(
            (
                entry
                for entry in self.entries
                if entry.provider == provider
                and region in entry.regions
                and region in entry.enabled_regions
                and identity_namespace in entry.identity_namespaces
                and data_kind in entry.enabled_data_kinds
                and entry.adapter_status == "implemented"
                and entry.automation_allowed
                and bool(entry.proof_digest)
                and bool(entry.allowed_hosts)
                and bool(entry.allowed_path_prefixes)
                and entry.request_budget > 0
                and entry.minimum_interval_seconds > 0
            ),
            None,
        )


@dataclass(frozen=True)
class RaceDataResolvedRoute:
    registry_digest: str
    route_digest: str
    contract_digest: str
    proof_digest: str
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    request_budget: int
    minimum_interval_seconds: int
    identity_namespace: str
    entry: RaceDataProviderRosterEntry


_ROSTER_ALLOWED_FIELDS = tuple(
    sorted(
        {
            "off_time",
            "local_start_time",
            "timezone_name",
            "status",
            "participants.horse_name",
            "participants.number",
            "participants.draw",
            "participants.jockey_name",
            "participants.trainer_name",
            "participants.carried_weight",
            "participants.status",
            "participants.odds",
            "participants.popularity",
        }
    )
)
_ROSTER_DEFINITIONS = (
    ("equibase", ("united_states",), "official_operator", "proof_required"),
    ("france_galop", ("france",), "official_operator", "proof_required"),
    ("hkjc", ("hong_kong",), "official_operator", "proof_required"),
    ("horse_racing_nation", ("united_states",), "trusted_publisher", "implemented"),
    ("hri", ("ireland",), "official_operator", "proof_required"),
    ("jra", ("japan_jra",), "official_operator", "proof_required"),
    ("nar", ("japan_nar",), "official_operator", "proof_required"),
    ("sporting_life", ("united_kingdom",), "trusted_publisher", "implemented"),
    (
        "the_racing_api",
        (
            "france",
            "hong_kong",
            "ireland",
            "japan_jra",
            "japan_nar",
            "united_kingdom",
            "united_states",
        ),
        "licensed_api",
        "implemented",
    ),
    ("zeturf", ("france",), "trusted_publisher", "implemented"),
)
_EVENT_REGION_BY_CONTRACT_REGION = {
    "hong_kong": models.RacingRegion.HONG_KONG,
    "japan_jra": models.RacingRegion.JAPAN,
    "japan_nar": models.RacingRegion.JAPAN,
    "united_kingdom": models.RacingRegion.UNITED_KINGDOM,
    "france": models.RacingRegion.FRANCE,
    "united_states": models.RacingRegion.UNITED_STATES,
    "ireland": models.RacingRegion.OTHER,
}


def _canonical_sha256(value: Any) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _provider_roster_digest(
    *, schema_version: int, entries: tuple[RaceDataProviderRosterEntry, ...]
) -> str:
    return _canonical_sha256(
        {
            "schema_version": schema_version,
            "entries": [
                {
                    "provider": entry.provider,
                    "regions": list(entry.regions),
                    "enabled_regions": list(entry.enabled_regions),
                    "source_class": entry.source_class,
                    "adapter_status": entry.adapter_status,
                    "contract_version": entry.contract_version,
                    "contract_digest": entry.contract_digest,
                    "identity_namespaces": list(entry.identity_namespaces),
                    "data_kinds": list(entry.data_kinds),
                    "terminal_markers": list(entry.terminal_markers),
                    "allowed_hosts": list(entry.allowed_hosts),
                    "allowed_path_prefixes": list(entry.allowed_path_prefixes),
                    "request_budget": entry.request_budget,
                    "minimum_interval_seconds": entry.minimum_interval_seconds,
                    "proof_digest": entry.proof_digest,
                }
                for entry in entries
            ],
        }
    )


def race_data_route_digest(
    *, roster: RaceDataProviderRoster, entry: RaceDataProviderRosterEntry
) -> str:
    """Bind one runnable route to the exact current roster and audit proof."""

    return _canonical_sha256(
        {
            "registry_digest": roster.registry_digest,
            "provider": entry.provider,
            "regions": list(entry.regions),
            "identity_namespaces": list(entry.identity_namespaces),
            # Route identity describes the provider contract, not the current
            # rollout stage.  Keep the existing canonical key so enrollments
            # created while every supported kind was enabled retain their
            # digest, but bind its value to the stable supported-kind set.
            "enabled_data_kinds": list(entry.data_kinds),
            "contract_version": entry.contract_version,
            "contract_digest": entry.contract_digest,
            "proof_digest": entry.proof_digest,
            "allowed_hosts": list(entry.allowed_hosts),
            "allowed_path_prefixes": list(entry.allowed_path_prefixes),
            "request_budget": entry.request_budget,
            "minimum_interval_seconds": entry.minimum_interval_seconds,
        }
    )


def resolve_race_data_provider_route(
    *,
    provider: str,
    region: str,
    identity_namespace: str,
    data_kinds: Iterable[str],
    configuration_only: bool = False,
) -> RaceDataResolvedRoute | None:
    """Resolve every requested kind through the one current Slice A roster."""

    kinds = tuple(sorted(set(data_kinds)))
    if not kinds:
        return None
    roster = build_race_data_provider_roster(configuration_only=configuration_only)
    matches = {
        roster.resolve_route(
            provider=provider,
            region=region,
            identity_namespace=identity_namespace,
            data_kind=kind,
        )
        for kind in kinds
    }
    if None in matches or len(matches) != 1:
        return None
    entry = next(iter(matches))
    assert entry is not None
    return RaceDataResolvedRoute(
        registry_digest=roster.registry_digest,
        route_digest=race_data_route_digest(roster=roster, entry=entry),
        contract_digest=entry.contract_digest,
        proof_digest=entry.proof_digest,
        allowed_hosts=entry.allowed_hosts,
        allowed_path_prefixes=entry.allowed_path_prefixes,
        request_budget=entry.request_budget,
        minimum_interval_seconds=entry.minimum_interval_seconds,
        identity_namespace=identity_namespace,
        entry=entry,
    )


def build_race_data_provider_roster(
    *,
    expected_registry_digest: str | None = None,
    configuration_only: bool = False,
) -> RaceDataProviderRoster:
    flags = RaceDataSyncFlags.from_settings()
    entries = []
    for provider, regions, source_class, adapter_status in _ROSTER_DEFINITIONS:
        contract_version = "race-data-v2"
        identity_namespaces = (f"{provider}-race-v1",)
        data_kinds = tuple(models.RaceDataSyncDataKind.values)
        terminal_markers: tuple[str, ...] = ()
        allowed_hosts: tuple[str, ...] = ()
        allowed_path_prefixes: tuple[str, ...] = ()
        request_budget = 0
        minimum_interval_seconds = 1
        proof_digest = ""
        if provider == "the_racing_api":
            terminal_markers = ("complete", "official", "result")
            allowed_hosts = ("api.theracingapi.com",)
            allowed_path_prefixes = (
                "/v1/racecards/free",
                "/v1/results/today/free",
                "/v1/results/",
            )
            request_budget = 3
            minimum_interval_seconds = 2
            configured_proof_digest = str(
                getattr(settings, "RACE_LIVE_TRA_REGISTRY_SHA256", "") or ""
            )
            if (
                len(configured_proof_digest) == _SHA256_LENGTH
                and all(
                    char in "0123456789abcdef"
                    for char in configured_proof_digest
                )
            ):
                proof_digest = configured_proof_digest
        elif provider in {
            "sporting_life",
            "zeturf",
            "horse_racing_nation",
        }:
            identity_namespaces = (f"{provider}-race-v1", provider)
            data_kinds = (models.RaceDataSyncDataKind.RESULT,)
            terminal_markers = ("complete",)
            reference_route = {
                "sporting_life": ("sportinglife.com", "/racing/results/"),
                "zeturf": ("zeturf.fr", "/fr/course-du-jour/"),
                "horse_racing_nation": (
                    "horseracingnation.com",
                    "/entries-results/",
                ),
            }[provider]
            allowed_hosts = (reference_route[0],)
            allowed_path_prefixes = (reference_route[1],)
            request_budget = 1
            minimum_interval_seconds = 2
            configured_proof_digest = str(
                getattr(
                    settings,
                    "RACE_DATA_SYNC_REFERENCE_REGISTRY_SHA256",
                    "",
                )
                or ""
            )
            if (
                len(configured_proof_digest) == _SHA256_LENGTH
                and all(
                    char in "0123456789abcdef"
                    for char in configured_proof_digest
                )
            ):
                proof_digest = configured_proof_digest
        elif source_class == "official_operator":
            terminal_markers = ("complete",)
        contract_digest = _canonical_sha256(
            {
                "provider": provider,
                "regions": list(regions),
                "source_class": source_class,
                "adapter_status": adapter_status,
                "contract_version": contract_version,
                "allowed_fields": list(_ROSTER_ALLOWED_FIELDS),
                "identity_namespaces": list(identity_namespaces),
                "data_kinds": list(data_kinds),
                "terminal_markers": list(terminal_markers),
                "allowed_hosts": list(allowed_hosts),
                "allowed_path_prefixes": list(allowed_path_prefixes),
                "request_budget": request_budget,
                "minimum_interval_seconds": minimum_interval_seconds,
            }
        )
        runtime_provider_enabled = bool(
            (flags.enabled or configuration_only)
            and provider in flags.providers
            and set(regions).intersection(flags.regions)
            and adapter_status == "implemented"
        )
        enabled_regions = tuple(
            region for region in regions if region in flags.regions
        )
        runtime_fields = tuple(
            field
            for field in _ROSTER_ALLOWED_FIELDS
            if field in flags.fields
        )
        runtime_apply_enabled = bool(
            runtime_provider_enabled and runtime_fields
        )
        enabled_data_kinds = tuple(
            kind for kind in data_kinds if kind in flags.data_kinds
        )
        automation_allowed = bool(runtime_provider_enabled and enabled_data_kinds)
        entries.append(
            RaceDataProviderRosterEntry(
                provider=provider,
                regions=regions,
                enabled_regions=enabled_regions,
                source_class=source_class,
                adapter_status=adapter_status,
                transport_enabled=runtime_provider_enabled,
                apply_enabled=runtime_apply_enabled,
                contract_version=contract_version,
                contract_digest=contract_digest,
                allowed_fields=_ROSTER_ALLOWED_FIELDS,
                identity_namespaces=identity_namespaces,
                data_kinds=data_kinds,
                enabled_data_kinds=enabled_data_kinds,
                terminal_markers=terminal_markers,
                allowed_hosts=allowed_hosts,
                allowed_path_prefixes=allowed_path_prefixes,
                request_budget=request_budget,
                minimum_interval_seconds=minimum_interval_seconds,
                automation_allowed=automation_allowed,
                proof_digest=proof_digest,
            )
        )
    roster_entries = tuple(entries)
    registry_digest = _provider_roster_digest(
        schema_version=2, entries=roster_entries
    )
    if (
        expected_registry_digest is not None
        and expected_registry_digest != registry_digest
    ):
        raise ValueError("race data provider roster digest mismatch")
    return RaceDataProviderRoster(
        schema_version=2,
        registry_digest=registry_digest,
        entries=roster_entries,
    )

def _require_trimmed_string(value: Any, name: str, *, max_length: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_length
    ):
        raise ValueError(f"{name} is invalid")
    return value


def _validate_strict_json(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("payload contains a non-finite number")
        return
    if isinstance(value, list):
        for item in value:
            _validate_strict_json(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("payload keys must be strings")
            _validate_strict_json(item)
        return
    raise ValueError("payload is not strict JSON")


def _validate_digest(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{name} is invalid")
    return value


def normalize_racecard_observation(
    *,
    payload: dict[str, Any],
    contract: dict[str, Any],
    observed_at: datetime,
    source_updated_at: datetime | None,
    parser_version: str,
    raw_sha256: str,
    source_url: str,
    task_id: str,
    run_id: str,
) -> NormalizedRacecardObservation:
    """Validate and digest a provider response without provider-specific rules."""

    if (
        not isinstance(payload, dict)
        or not _REQUIRED_TOP_LEVEL_KEYS.issubset(payload)
        or not set(payload).issubset(
            _REQUIRED_TOP_LEVEL_KEYS | _OPTIONAL_TOP_LEVEL_KEYS
        )
    ):
        raise ValueError("racecard payload does not match the strict schema")
    if not isinstance(contract, dict) or set(contract) != _CONTRACT_KEYS:
        raise ValueError("contract is invalid")
    if contract.get("schema_version") != 1 or contract.get("data_kind") != "racecard":
        raise ValueError("contract version/kind is invalid")
    provider = _require_trimmed_string(contract.get("provider"), "provider", max_length=64)
    _require_trimmed_string(contract.get("region"), "region", max_length=64)
    source_class = _require_trimmed_string(
        contract.get("source_class"), "source_class", max_length=32
    )
    contract_version = _require_trimmed_string(
        contract.get("contract_version"), "contract_version", max_length=64
    )
    registry_digest = _validate_digest(contract.get("registry_digest"), "registry_digest")
    contract_digest = _validate_digest(contract.get("contract_digest"), "contract_digest")
    if contract.get("automation_allowed") is not True:
        raise ValueError("contract does not allow automation")
    allowed_fields = contract.get("allowed_fields")
    if not isinstance(allowed_fields, list) or not all(
        isinstance(item, str) and item for item in allowed_fields
    ):
        raise ValueError("contract fields are invalid")
    allowed_field_set = set(allowed_fields)
    if len(allowed_field_set) != len(allowed_fields) or "off_time" not in allowed_field_set:
        raise ValueError("contract fields are invalid")

    if payload.get("schema_version") != 1:
        raise ValueError("payload schema version is invalid")
    external_race_id = _require_trimmed_string(
        payload.get("external_race_id"), "external_race_id", max_length=128
    )
    for key, limit in (
        ("region", 64),
        ("course", 255),
        ("race_name", 255),
        ("race_status", 32),
    ):
        _require_trimmed_string(payload.get(key), key, max_length=limit)
    if payload["region"] != contract["region"]:
        raise ValueError("payload region does not match contract")
    try:
        parsed_off_time = datetime.fromisoformat(
            _require_trimmed_string(
                payload.get("off_time"), "off_time", max_length=64
            ).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("off_time is invalid") from exc
    if timezone.is_naive(parsed_off_time):
        raise ValueError("off_time must include a timezone")
    if "local_start_time" in payload:
        if "local_start_time" not in allowed_field_set:
            raise ValueError("local_start_time is not allowed")
        try:
            parsed_local_start = datetime.strptime(
                _require_trimmed_string(
                    payload["local_start_time"],
                    "local_start_time",
                    max_length=8,
                ),
                "%H:%M:%S",
            ).time()
        except ValueError as exc:
            raise ValueError("local_start_time is invalid") from exc
        if parsed_local_start.tzinfo is not None:
            raise ValueError("local_start_time must be local wall time")
    if "timezone_name" in payload:
        if "timezone_name" not in allowed_field_set:
            raise ValueError("timezone_name is not allowed")
        timezone_name = _require_trimmed_string(
            payload["timezone_name"], "timezone_name", max_length=64
        )
        try:
            ZoneInfo(timezone_name)
        except (KeyError, ValueError) as exc:
            raise ValueError("timezone_name is invalid") from exc
    race_status = payload["race_status"]
    if race_status in models.RaceEventStatus.values and "status" not in allowed_field_set:
        raise ValueError("status is not allowed")

    participants = payload.get("participants")
    if not isinstance(participants, list) or len(participants) > 100:
        raise ValueError("participants are invalid")
    seen_runner_ids: set[str] = set()
    for row in participants:
        if not isinstance(row, dict) or not set(row).issubset(_PARTICIPANT_KEYS):
            raise ValueError("participant does not match the strict schema")
        runner_id = _require_trimmed_string(
            row.get("external_runner_id"), "external_runner_id", max_length=128
        )
        if runner_id in seen_runner_ids:
            raise ValueError("external_runner_id is duplicated")
        seen_runner_ids.add(runner_id)
        _require_trimmed_string(row.get("horse_name"), "horse_name", max_length=255)
        for source_field in row:
            if source_field == "external_runner_id" or source_field in _NON_WRITABLE_PARTICIPANT_METADATA_KEYS:
                continue
            if f"participants.{source_field}" not in allowed_field_set:
                raise ValueError(f"participant field {source_field} is not allowed")
        for optional_name, limit in (
            ("number", 32),
            ("draw", 32),
            ("jockey_name", 255),
            ("trainer_name", 255),
            ("carried_weight", 64),
            ("popularity", 64),
            ("jockey_id", 128),
        ):
            if optional_name in row:
                value = row[optional_name]
                if not isinstance(value, str) or value != value.strip() or len(value) > limit:
                    raise ValueError(f"participant {optional_name} is invalid")
        if "odds" in row:
            odds = row["odds"]
            if isinstance(odds, bool) or not isinstance(odds, (str, int, float)):
                raise ValueError("participant odds is invalid")
            if isinstance(odds, float) and not math.isfinite(odds):
                raise ValueError("participant odds is invalid")
        if row.get("status", models.RaceRunnerStatus.DECLARED) not in _PARTICIPANT_STATUSES:
            raise ValueError("participant status is invalid")
    if not isinstance(observed_at, datetime) or timezone.is_naive(observed_at):
        raise ValueError("observed_at must be aware")
    if source_updated_at is not None and (
        not isinstance(source_updated_at, datetime) or timezone.is_naive(source_updated_at)
    ):
        raise ValueError("source_updated_at must be aware")
    parser_version = _require_trimmed_string(
        parser_version, "parser_version", max_length=64
    )
    raw_sha256 = _validate_digest(raw_sha256, "raw_sha256")
    source_url = _require_trimmed_string(source_url, "source_url", max_length=1000)
    task_id = _require_trimmed_string(task_id, "task_id", max_length=255)
    run_id = _require_trimmed_string(run_id, "run_id", max_length=64)
    _validate_strict_json(payload)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    normalized_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return NormalizedRacecardObservation(
        normalized_payload=payload,
        normalized_sha256=normalized_sha256,
        provenance={
            "provider": provider,
            "region": contract["region"],
            "source_class": source_class,
            "source_url": source_url,
            "external_race_id": external_race_id,
            "observed_at": observed_at,
            "source_updated_at": source_updated_at,
            "parser_version": parser_version,
            "raw_sha256": raw_sha256,
            "normalized_sha256": normalized_sha256,
            "task_id": task_id,
            "run_id": run_id,
            "registry_digest": registry_digest,
            "contract_version": contract_version,
            "contract_digest": contract_digest,
            "automation_allowed": True,
            "allowed_fields": tuple(allowed_fields),
        },
    )


def sanitize_provider_raw_payload(payload: Any) -> Any:
    """Return strict JSON-shaped data with secret-bearing keys removed recursively."""

    if isinstance(payload, Mapping):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            rendered_key = str(key)
            normalized_key = rendered_key.casefold().replace("-", "_")
            if any(part in normalized_key for part in _SECRET_KEY_PARTS):
                continue
            sanitized[rendered_key] = sanitize_provider_raw_payload(value)
        return sanitized
    if isinstance(payload, (list, tuple)):
        return [sanitize_provider_raw_payload(value) for value in payload]
    return payload


def _audit_defaults(
    *, observation: models.RaceResultObservation, task_id: str, run_id: str
) -> dict[str, Any]:
    provenance = (
        observation.field_provenance
        if isinstance(observation.field_provenance, dict)
        else {}
    )
    return {
        "source_key": observation.source_identity.source_key,
        "source_url": observation.source_identity.canonical_url,
        "external_id": observation.source_identity.external_race_id,
        "authority_level": 0,
        "trigger_task": task_id,
        "run_id": run_id,
        "observation": observation,
        "source_class": str(provenance.get("source_class") or ""),
        "source_updated_at": observation.source_updated_at,
        "parser_version": observation.parser_version,
        "raw_sha256": observation.raw_sha256,
        "normalized_sha256": observation.normalized_sha256,
        "registry_digest": str(provenance.get("registry_digest") or ""),
        "contract_version": str(provenance.get("contract_version") or ""),
        "contract_digest": str(provenance.get("contract_digest") or ""),
        "celery_task_id": task_id,
        "operation_mode": "slice_a",
    }


def _runner_field_candidates(row: dict[str, Any]) -> dict[str, tuple[str, str]]:
    candidates = {
        "horse_name": ("participants.horse_name", str(row["horse_name"])),
    }
    for source_field, model_field in (
        ("number", "horse_number"),
        ("draw", "barrier"),
        ("jockey_name", "jockey_name"),
        ("trainer_name", "trainer_name"),
        ("carried_weight", "carried_weight"),
        ("odds", "odds_value"),
        ("popularity", "popularity"),
        ("status", "running_status"),
    ):
        if source_field in row:
            candidates[model_field] = (
                f"participants.{source_field}",
                str(row[source_field]),
            )
    return candidates


def _resolve_namespaced_runner(
    *,
    event: models.RaceEvent,
    source: models.RaceResultSourceIdentity,
    external_runner_id: str,
) -> tuple[models.RaceEventRunner | None, bool]:
    """Resolve a runner only through this source or an approved cross-source map."""

    source_mapping = (
        models.RaceEventParticipantSourceIdentity.objects.select_for_update()
        .select_related("participant")
        .filter(
            source_identity=source,
            external_runner_id=external_runner_id,
            participant__event=event,
            participant__review_status=models.RaceLiveReviewStatus.APPROVED,
        )
        .first()
    )
    if source_mapping is not None:
        mapped_identities = list(
            models.RaceEventParticipantSourceIdentity.objects.select_for_update()
            .select_related("source_identity")
            .filter(
                participant=source_mapping.participant,
                source_identity__review_status=models.RaceLiveReviewStatus.APPROVED,
            )
        )
        mapped_pairs = {
            (identity.source_identity.source_key, identity.external_runner_id)
            for identity in mapped_identities
        }
        candidates = []
        for runner in (
            models.RaceEventRunner.objects.select_for_update()
            .filter(event=event)
            .order_by("id")
        ):
            refs = runner.source_refs if isinstance(runner.source_refs, dict) else {}
            if any(refs.get(provider) == runner_id for provider, runner_id in mapped_pairs):
                candidates.append(runner)
                continue
            if any(runner.external_runner_id == runner_id for _, runner_id in mapped_pairs):
                candidates.append(runner)
        unique = {runner.pk: runner for runner in candidates}
        if len(unique) > 1:
            return None, True
        return (next(iter(unique.values())) if unique else None), False

    exact = (
        models.RaceEventRunner.objects.select_for_update()
        .filter(event=event, external_runner_id=external_runner_id)
        .first()
    )
    if exact is not None:
        refs = exact.source_refs if isinstance(exact.source_refs, dict) else {}
        owned = bool(
            refs.get(source.source_key) == external_runner_id
            or (
                refs.get("source_key") == source.source_key
                and refs.get("external_runner_id") == external_runner_id
            )
        )
        return (exact, False) if owned else (exact, True)

    legacy_matches = [
        candidate
        for candidate in models.RaceEventRunner.objects.select_for_update()
        .filter(event=event, external_runner_id="")
        .order_by("id")
        if isinstance(candidate.source_refs, dict)
        and candidate.source_refs.get("source_key") == source.source_key
        and str(candidate.source_refs.get("external_runner_id") or "").strip()
        == external_runner_id
    ][:2]
    if len(legacy_matches) > 1:
        return None, True
    return (legacy_matches[0] if legacy_matches else None), False


def _reconcile_racecard_observation_atomic(
    *,
    observation_id: int,
    expected_event_id: int,
    allow_schedule_apply: bool,
    allow_racecard_apply: bool,
    task_id: str,
    run_id: str,
    claim_guard: RaceDataSyncClaim | None = None,
) -> RacecardReconciliationDecision:
    """Apply admitted racecard and schedule fields under source arbitration."""
    with transaction.atomic():
        lifecycle = (
            models.RaceEventLifecycleControl.objects.select_for_update()
            .filter(event_id=expected_event_id)
            .first()
        )
        locked_claim = None
        if claim_guard is not None:
            claim_decision, locked_claim = (
                lock_and_validate_race_data_sync_claim_for_apply(
                    claim=claim_guard,
                    now=timezone.now(),
                    required_data_kinds=tuple(
                        kind
                        for kind, enabled in (
                            (
                                models.RaceDataSyncDataKind.RACE_TIME,
                                allow_schedule_apply,
                            ),
                            (
                                models.RaceDataSyncDataKind.RACECARD,
                                allow_racecard_apply,
                            ),
                        )
                        if enabled
                    ),
                )
            )
            if locked_claim is None:
                return RacecardReconciliationDecision(
                    "rejected", claim_decision.reason_code, expected_event_id
                )
            if locked_claim.event.pk != expected_event_id:
                return RacecardReconciliationDecision(
                    "rejected", "event_identity_mismatch", expected_event_id
                )
        observation = (
            models.RaceResultObservation.objects.select_for_update()
            .select_related("source_identity")
            .filter(pk=observation_id)
            .first()
        )
        if observation is None:
            return RacecardReconciliationDecision("rejected", "observation_missing")
        source = observation.source_identity
        if (
            source.event_id != expected_event_id
            or observation.result_phase != models.RaceResultPhase.RACECARD
        ):
            return RacecardReconciliationDecision(
                "rejected", "event_identity_mismatch", observation_id=observation.pk
            )
        if (
            source.review_status != models.RaceLiveReviewStatus.APPROVED
            or source.automation_allowed is not True
        ):
            return RacecardReconciliationDecision(
                "rejected", "source_not_approved", expected_event_id, observation.pk
            )
        payload = observation.normalized_payload
        provenance = (
            observation.field_provenance
            if isinstance(observation.field_provenance, dict)
            else {}
        )
        if (
            not isinstance(payload, dict)
            or not _LEGACY_RECONCILE_REQUIRED_KEYS.issubset(payload)
            or not set(payload).issubset(
                _REQUIRED_TOP_LEVEL_KEYS | _OPTIONAL_TOP_LEVEL_KEYS
            )
            or payload.get("external_race_id") != source.external_race_id
            or not isinstance(payload.get("participants"), (list, tuple))
            or len(payload["participants"]) > 100
        ):
            return RacecardReconciliationDecision(
                "rejected", "source_identity_mismatch", expected_event_id, observation.pk
            )
        if (
            provenance.get("provider") != source.source_key
            or not isinstance(provenance.get("region"), str)
            or not isinstance(provenance.get("source_class"), str)
            or not provenance["source_class"]
            or not isinstance(provenance.get("contract_version"), str)
            or not provenance["contract_version"]
            or provenance.get("automation_allowed") is not True
        ):
            return RacecardReconciliationDecision(
                "rejected", "source_contract_mismatch", expected_event_id, observation.pk
            )
        try:
            _validate_digest(provenance.get("registry_digest"), "registry_digest")
            _validate_digest(provenance.get("contract_digest"), "contract_digest")
        except ValueError:
            return RacecardReconciliationDecision(
                "rejected", "source_contract_mismatch", expected_event_id, observation.pk
            )
        contract_region = provenance["region"]
        allowed_fields = provenance.get("allowed_fields")
        if (
            not isinstance(allowed_fields, (list, tuple))
            or not all(isinstance(value, str) for value in allowed_fields)
            or _EVENT_REGION_BY_CONTRACT_REGION.get(contract_region)
            != source.event.country_region
        ):
            return RacecardReconciliationDecision(
                "rejected", "source_contract_mismatch", expected_event_id, observation.pk
            )
        roster = build_race_data_provider_roster()
        roster_entry = next(
            (
                entry
                for entry in roster.entries
                if entry.provider == source.source_key
                and contract_region in entry.regions
                and (
                    not source.identity_namespace
                    or source.identity_namespace in entry.identity_namespaces
                )
                and models.RaceDataSyncDataKind.RACECARD in entry.data_kinds
            ),
            None,
        )
        if roster_entry is None or contract_region not in roster_entry.regions:
            return RacecardReconciliationDecision(
                "rejected", "source_contract_mismatch", expected_event_id, observation.pk
            )
        if (
            provenance.get("registry_digest") != roster.registry_digest
            or provenance.get("contract_version")
            != roster_entry.contract_version
            or provenance.get("contract_digest") != roster_entry.contract_digest
            or provenance.get("source_class") != roster_entry.source_class
            or not set(allowed_fields).issubset(set(_ROSTER_ALLOWED_FIELDS))
        ):
            return RacecardReconciliationDecision(
                "rejected", "source_contract_mismatch", expected_event_id, observation.pk
            )
        actual_fields: set[str] = set()
        if "off_time" in payload:
            actual_fields.add("off_time")
        if "local_start_time" in payload:
            actual_fields.add("local_start_time")
        if "timezone_name" in payload:
            actual_fields.add("timezone_name")
        if payload.get("race_status") in models.RaceEventStatus.values:
            actual_fields.add("status")
        for row in payload["participants"]:
            if not isinstance(row, dict):
                return RacecardReconciliationDecision(
                    "rejected", "source_contract_mismatch", expected_event_id, observation.pk
                )
            actual_fields.update(
                f"participants.{key}"
                for key in row
                if key != "external_runner_id"
                and key not in _NON_WRITABLE_PARTICIPANT_METADATA_KEYS
            )
        if not actual_fields.issubset(set(allowed_fields)):
            return RacecardReconciliationDecision(
                "rejected", "source_contract_mismatch", expected_event_id, observation.pk
            )
        if (
            roster_entry.adapter_status != "implemented"
            or not roster_entry.transport_enabled
            or not roster_entry.apply_enabled
        ):
            return RacecardReconciliationDecision(
                "rejected", "runtime_admission_closed", expected_event_id, observation.pk
            )
        flags = RaceDataSyncFlags.from_settings()
        admitted_fields = {
            field_name
            for field_name in actual_fields
            if flags.allows(
                provider=source.source_key,
                region=contract_region,
                field_name=field_name,
            )
        }
        if not admitted_fields:
            return RacecardReconciliationDecision(
                "rejected", "runtime_admission_closed", expected_event_id, observation.pk
            )
        existing_changes = models.RaceEventFieldChange.objects.filter(
            observation=observation
        )
        reprocessable = Q(pk__in=())
        if allow_schedule_apply:
            reprocessable |= Q(rejection_reason="schedule_apply_disabled")
        if flags.racecard_apply_enabled:
            reprocessable |= Q(rejection_reason="racecard_apply_disabled")
        runtime_contract_by_field = {
            "horse_name": "participants.horse_name",
            "horse_number": "participants.number",
            "barrier": "participants.draw",
            "jockey_name": "participants.jockey_name",
            "trainer_name": "participants.trainer_name",
            "carried_weight": "participants.carried_weight",
            "odds_value": "participants.odds",
            "popularity": "participants.popularity",
            "running_status": "participants.status",
            "race_datetime": "off_time",
            "local_date": "off_time",
            "local_start_time": "local_start_time",
            "timezone_name": "timezone_name",
            "status": "status",
        }
        newly_admitted_model_fields = {
            model_field
            for model_field, contract_field in runtime_contract_by_field.items()
            if contract_field in admitted_fields
        }
        if newly_admitted_model_fields:
            reprocessable |= Q(
                rejection_reason="runtime_admission_closed",
                field_name__in=newly_admitted_model_fields,
            )
        processed_fields = set(
            existing_changes.exclude(
                Q(decision="rejected") & reprocessable
            ).values_list("subject_type", "subject_key", "field_name")
        )
        had_existing_review = existing_changes.filter(
            decision="needs_review"
        ).exists()
        if had_existing_review:
            return RacecardReconciliationDecision(
                "needs_review",
                "racecard_needs_review",
                expected_event_id,
                observation.pk,
            )

        event = (
            locked_claim.event
            if locked_claim is not None
            else models.RaceEvent.objects.select_for_update()
            .filter(pk=expected_event_id)
            .first()
        )
        if event is None:
            return RacecardReconciliationDecision(
                "rejected", "event_missing", expected_event_id, observation.pk
            )
        control = (
            locked_claim.control
            if locked_claim is not None
            else None
        )
        if control is None:
            control, _created = models.RaceEventProjectionControl.objects.get_or_create(
                event=event
            )
            control = models.RaceEventProjectionControl.objects.select_for_update().get(
                pk=control.pk
            )
        if control.write_owner not in {
            models.RaceEventProjectionWriteOwner.UNMANAGED,
            models.RaceEventProjectionWriteOwner.LIVE,
            models.RaceEventProjectionWriteOwner.DATA_SYNC,
        }:
            return RacecardReconciliationDecision(
                "rejected",
                "writer_owner_conflict",
                expected_event_id,
                observation.pk,
            )
        if control.write_owner == models.RaceEventProjectionWriteOwner.DATA_SYNC and (
            source.terms_status != models.RaceSourceTermsStatus.APPROVED
            or source.valid_until is None
            or source.valid_until <= timezone.now()
            or source.registry_digest != roster.registry_digest
            or source.region_code != contract_region
            or source.identity_namespace not in roster_entry.identity_namespaces
        ):
            return RacecardReconciliationDecision(
                "rejected",
                "source_contract_mismatch",
                expected_event_id,
                observation.pk,
            )
        audit = _audit_defaults(observation=observation, task_id=task_id, run_id=run_id)
        candidate_watermark = observation.source_updated_at or observation.observed_at
        candidate_source_class = normalize_source_class(
            provenance.get("source_class")
        )
        aggregate = "replayed"
        participants = list(payload["participants"]) if allow_racecard_apply else []
        seen: set[str] = set()
        validated_participants: list[tuple[str, str, dict[str, Any]]] = []
        for row in participants:
            if not isinstance(row, dict):
                return RacecardReconciliationDecision(
                    "rejected", "participants_invalid", event.pk, observation.pk
                )
            external_runner_id = str(row.get("external_runner_id") or "").strip()
            horse_name = str(row.get("horse_name") or "").strip()
            if (
                not external_runner_id
                or len(external_runner_id) > 128
                or external_runner_id in seen
                or not horse_name
            ):
                return RacecardReconciliationDecision(
                    "rejected", "participants_invalid", event.pk, observation.pk
                )
            seen.add(external_runner_id)
            status = row.get("status")
            if status is not None and status not in _PARTICIPANT_STATUSES:
                return RacecardReconciliationDecision(
                    "rejected", "participants_invalid", event.pk, observation.pk
                )
            validated_participants.append((external_runner_id, horse_name, row))

        for order, (external_runner_id, horse_name, row) in enumerate(
            validated_participants, start=1
        ):
            candidate_fields = _runner_field_candidates(row)
            candidate_fields = {
                model_field: proposed
                for model_field, (contract_field, proposed) in candidate_fields.items()
                if contract_field in admitted_fields
                and (
                    models.RaceEventFieldSubjectType.PARTICIPANT,
                    external_runner_id,
                    model_field,
                )
                not in processed_fields
                and (
                    models.RaceEventFieldSubjectType.PARTICIPANT,
                    f"{source.source_key}:{external_runner_id}",
                    model_field,
                )
                not in processed_fields
            }
            runner, identity_conflict = _resolve_namespaced_runner(
                event=event,
                source=source,
                external_runner_id=external_runner_id,
            )
            if identity_conflict:
                raise _RacecardNeedsReview(
                    reason="runner_identity_mapping_required",
                    event_id=event.pk,
                    observation_id=observation.pk,
                    changes=(
                        {
                        "event": event,
                        "subject_type": models.RaceEventFieldSubjectType.PARTICIPANT,
                        "subject_key": (
                            runner.external_runner_id
                            if runner is not None and runner.external_runner_id
                            else f"{source.source_key}:{external_runner_id}"
                        ),
                        "field_name": field_name,
                        "old_value": (
                            getattr(runner, field_name) if runner is not None else None
                        ),
                        "new_value": proposed,
                        "applied": False,
                        "decision": "needs_review",
                        "rejection_reason": "runner_identity_mapping_required",
                        **audit,
                        }
                        for field_name, proposed in candidate_fields.items()
                    ),
                )
            created = runner is None
            if runner is None:
                if "participants.horse_name" not in admitted_fields:
                    raise _RacecardNeedsReview(
                        reason="runner_identity_field_not_admitted",
                        event_id=event.pk,
                        observation_id=observation.pk,
                    )
                runner = models.RaceEventRunner.objects.create(
                    event=event,
                    external_runner_id=external_runner_id,
                    sort_order=order,
                    horse_name=horse_name,
                    source_refs={
                        source.source_key: external_runner_id,
                    },
                )
            locks = runner.manual_lock_flags if isinstance(runner.manual_lock_flags, dict) else {}
            subject_key = runner.external_runner_id or external_runner_id
            runner_field_applied = False
            for field_name, proposed in candidate_fields.items():
                old_value = None if created else getattr(runner, field_name)
                authority, _ = models.RaceEventFieldAuthority.objects.select_for_update().get_or_create(
                    event=event,
                    subject_type=models.RaceEventFieldSubjectType.PARTICIPANT,
                    subject_key=subject_key,
                    field_name=field_name,
                    defaults={
                        "authority_level": 0,
                        "source_key": "",
                        "value_sha256": "",
                    },
                )
                arbitration = arbitrate_source_value(
                    current_source_key=authority.source_key,
                    current_source_class=authority.source_class,
                    current_observed_at=authority.observed_at,
                    candidate_source_key=source.source_key,
                    candidate_source_class=candidate_source_class,
                    candidate_observed_at=candidate_watermark,
                    has_current_value=not created and old_value not in (None, ""),
                    values_equal=not created and old_value == proposed,
                    manual_locked=(
                        locks.get(field_name) is True or authority.manual_lock
                    ),
                )
                applied = arbitration.apply
                decision = "applied" if applied else (
                    "replayed"
                    if arbitration.reason_code == "idempotent_replay"
                    else "rejected"
                )
                reason = arbitration.reason_code
                models.RaceEventFieldChange.objects.create(
                    event=event,
                    subject_type=models.RaceEventFieldSubjectType.PARTICIPANT,
                    subject_key=external_runner_id,
                    field_name=field_name,
                    old_value=old_value,
                    new_value=proposed,
                    applied=applied,
                    decision=decision,
                    rejection_reason=(
                        "" if applied or decision == "replayed" else reason
                    ),
                    **audit,
                )
                if applied:
                    setattr(runner, field_name, proposed)
                    runner_field_applied = True
                    if aggregate != "needs_review":
                        aggregate = "applied"
                if (
                    applied
                    or not authority.source_key
                    or (
                        authority.source_key == source.source_key
                        and (
                            authority.observed_at is None
                            or candidate_watermark > authority.observed_at
                        )
                    )
                ):
                    authority.authority_level = source_priority(
                        candidate_source_class
                    )
                    authority.source_class = candidate_source_class
                    authority.source_key = source.source_key
                    authority.source_url = source.canonical_url
                    authority.external_id = external_runner_id
                    authority.observed_at = candidate_watermark
                    authority.value_sha256 = hashlib.sha256(
                        json.dumps(
                            proposed, ensure_ascii=False, sort_keys=True
                        ).encode("utf-8")
                    ).hexdigest()
                    authority.save(
                        update_fields=(
                            "authority_level",
                            "source_class",
                            "source_key",
                            "source_url",
                            "external_id",
                            "observed_at",
                            "value_sha256",
                            "updated_at",
                        )
                    )
            if runner_field_applied and (
                runner.dynamic_updated_at is None
                or candidate_watermark > runner.dynamic_updated_at
            ):
                runner.dynamic_updated_at = candidate_watermark
            runner.source_refs = {
                **(runner.source_refs if isinstance(runner.source_refs, dict) else {}),
                source.source_key: external_runner_id,
            }
            runner.save()

        if (
            allow_racecard_apply
            and validated_participants
            and control.write_owner != models.RaceEventProjectionWriteOwner.LIVE
        ):
            revision_rows: list[tuple[models.RaceEventRunner, models.RaceEventParticipant]] = []
            canonical_participants: list[dict[str, Any]] = []
            for runner in models.RaceEventRunner.objects.select_for_update().filter(
                event=event
            ).order_by("sort_order", "id"):
                refs = runner.source_refs if isinstance(runner.source_refs, dict) else {}
                external_runner_id = str(refs.get(source.source_key) or "").strip()
                if not external_runner_id and refs.get("source_key") == source.source_key:
                    external_runner_id = str(
                        refs.get("external_runner_id") or ""
                    ).strip()
                if not external_runner_id:
                    continue
                stable_key = (
                    f"{source.source_key}:"
                    f"{hashlib.sha256(external_runner_id.encode()).hexdigest()[:48]}"
                )
                existing_identity = (
                    models.RaceEventParticipantSourceIdentity.objects.select_for_update()
                    .select_related("participant")
                    .filter(
                        source_identity=source,
                        external_runner_id=external_runner_id,
                        participant__event=event,
                    )
                    .first()
                )
                participant = (
                    existing_identity.participant
                    if existing_identity is not None
                    else models.RaceEventParticipant.objects.get_or_create(
                        event=event,
                        stable_key=stable_key,
                        defaults={
                            "canonical_name": runner.horse_name,
                            "country_region": event.country_region,
                            "review_status": models.RaceLiveReviewStatus.APPROVED,
                        },
                    )[0]
                )
                models.RaceEventParticipantSourceIdentity.objects.get_or_create(
                    participant=participant,
                    source_identity=source,
                    defaults={"external_runner_id": external_runner_id},
                )
                canonical_participants.append(
                    {
                        "external_runner_id": external_runner_id,
                        "horse_name": runner.horse_name,
                        "number": runner.horse_number,
                        "draw": runner.barrier,
                        "jockey_name": runner.jockey_name,
                        "trainer_name": runner.trainer_name,
                        "carried_weight": runner.carried_weight,
                        "status": runner.running_status,
                    }
                )
                revision_rows.append((runner, participant))
            canonical_payload = {
                "external_race_id": source.external_race_id,
                "participants": canonical_participants,
            }
            content_sha256 = _canonical_sha256(canonical_payload)
            current_racecard = control.current_racecard_revision
            existing_revision = models.RaceEventRevision.objects.filter(
                event=event,
                kind=models.RaceEventRevisionKind.RACECARD,
                phase=models.RaceResultPhase.RACECARD,
                content_sha256=content_sha256,
            ).first()
            if existing_revision is None:
                revision = models.RaceEventRevision.objects.create(
                    event=event,
                    kind=models.RaceEventRevisionKind.RACECARD,
                    revision_no=control.next_racecard_revision_no,
                    phase=models.RaceResultPhase.RACECARD,
                    content_sha256=content_sha256,
                    source_authority=candidate_source_class,
                    decision_reason="data_sync_racecard_reconciled",
                    primary_observation=observation,
                    supersedes=current_racecard,
                )
                models.RaceEventRevisionItem.objects.bulk_create(
                    [
                        models.RaceEventRevisionItem(
                            revision=revision,
                            participant=participant,
                            source_order=index,
                            internal_order=index,
                            status=runner.running_status,
                            raw_status=runner.running_status,
                            horse_number=runner.horse_number,
                            barrier=runner.barrier,
                            jockey_name=runner.jockey_name,
                            trainer_name=runner.trainer_name,
                            carried_weight=runner.carried_weight,
                            field_provenance={
                                "source_key": source.source_key,
                                "external_runner_id": canonical_participants[index - 1][
                                    "external_runner_id"
                                ],
                                "observation_id": observation.pk,
                            },
                        )
                        for index, (runner, participant) in enumerate(
                            revision_rows, start=1
                        )
                    ]
                )
                models.RaceEventRevisionEvidence.objects.create(
                    revision=revision,
                    observation=observation,
                    role="primary",
                )
                control.last_known_good_racecard_revision = current_racecard
                control.current_racecard_revision = revision
                control.next_racecard_revision_no += 1
                control.save(
                    update_fields=(
                        "last_known_good_racecard_revision",
                        "current_racecard_revision",
                        "next_racecard_revision_no",
                        "updated_at",
                    )
                )
                aggregate = "applied"
            elif control.current_racecard_revision_id != existing_revision.pk:
                control.last_known_good_racecard_revision = current_racecard
                control.current_racecard_revision = existing_revision
                control.save(
                    update_fields=(
                        "last_known_good_racecard_revision",
                        "current_racecard_revision",
                        "updated_at",
                    )
                )
                aggregate = "applied"

        candidate_timezone = str(
            payload.get("timezone_name") or event.timezone_name or ""
        ).strip()
        try:
            candidate_zone = ZoneInfo(candidate_timezone)
        except (KeyError, ValueError):
            candidate_zone = None
        parsed_off: datetime | None = None
        if payload.get("off_time"):
            try:
                parsed_off = datetime.fromisoformat(
                    str(payload["off_time"]).replace("Z", "+00:00")
                )
                if parsed_off.tzinfo is None or parsed_off.utcoffset() is None:
                    parsed_off = None
            except ValueError:
                parsed_off = None
        schedule_candidates: dict[str, Any] = {}
        if parsed_off is not None:
            schedule_candidates["race_datetime"] = parsed_off
        if candidate_zone is not None and "timezone_name" in payload:
            schedule_candidates["timezone_name"] = candidate_timezone
        if "local_start_time" in payload:
            try:
                schedule_candidates["local_start_time"] = datetime.strptime(
                    str(payload["local_start_time"]), "%H:%M:%S"
                ).time()
            except ValueError:
                try:
                    schedule_candidates["local_start_time"] = datetime.strptime(
                        str(payload["local_start_time"]), "%H:%M"
                    ).time()
                except ValueError:
                    pass
        elif parsed_off is not None and candidate_zone is not None:
            schedule_candidates["local_start_time"] = (
                parsed_off.astimezone(candidate_zone).time().replace(tzinfo=None)
            )
        if parsed_off is not None and candidate_zone is not None:
            schedule_candidates["local_date"] = parsed_off.astimezone(
                candidate_zone
            ).date()
        if payload.get("race_status") in models.RaceEventStatus.values:
            schedule_candidates["status"] = payload["race_status"]
        old_schedule_values = {
            field_name: getattr(event, field_name)
            for field_name in (
                "race_datetime",
                "local_date",
                "local_start_time",
                "timezone_name",
                "status",
            )
        }
        schedule_changed = False
        locks = (
            event.manual_lock_flags
            if isinstance(event.manual_lock_flags, dict)
            else {}
        )
        for field_name, candidate_value in schedule_candidates.items():
            if (
                models.RaceEventFieldSubjectType.EVENT,
                str(event.pk),
                field_name,
            ) in processed_fields:
                continue
            authority, _ = models.RaceEventFieldAuthority.objects.select_for_update().get_or_create(
                event=event,
                subject_type=models.RaceEventFieldSubjectType.EVENT,
                subject_key=str(event.pk),
                field_name=field_name,
                defaults={
                    "authority_level": 0,
                    "source_class": "",
                    "source_key": "",
                    "value_sha256": "",
                },
            )
            old_value = old_schedule_values[field_name]
            field_value_changed = old_value != candidate_value
            arbitration = arbitrate_source_value(
                current_source_key=authority.source_key,
                current_source_class=authority.source_class,
                current_observed_at=authority.observed_at,
                candidate_source_key=source.source_key,
                candidate_source_class=candidate_source_class,
                candidate_observed_at=candidate_watermark,
                has_current_value=old_value is not None and old_value != "",
                values_equal=old_value == candidate_value,
                manual_locked=(
                    locks.get(field_name) is True or authority.manual_lock
                ),
            )
            contract_field_name = {
                "race_datetime": "off_time",
                "local_date": "off_time",
                "local_start_time": "local_start_time",
                "timezone_name": "timezone_name",
                "status": "status",
            }[field_name]
            field_admitted = contract_field_name in admitted_fields
            terminal_status_regression = bool(
                field_name == "status"
                and old_value
                in {
                    models.RaceEventStatus.CANCELLED,
                    models.RaceEventStatus.FINISHED,
                }
                and candidate_value != old_value
            )
            applied = bool(
                allow_schedule_apply
                and field_admitted
                and arbitration.apply
                and not terminal_status_regression
            )
            decision = (
                "applied"
                if applied
                else (
                    "replayed"
                    if arbitration.reason_code == "idempotent_replay"
                    else "rejected"
                )
            )
            rejection_reason = ""
            if not applied and decision != "replayed":
                rejection_reason = (
                    "terminal_status_regression"
                    if terminal_status_regression
                    else "schedule_apply_disabled"
                    if not allow_schedule_apply
                    else (
                        "runtime_admission_closed"
                        if not field_admitted
                        else arbitration.reason_code
                    )
                )
            rendered_old = (
                old_value.isoformat()
                if hasattr(old_value, "isoformat")
                else old_value
            )
            rendered_candidate = (
                candidate_value.isoformat()
                if hasattr(candidate_value, "isoformat")
                else candidate_value
            )
            schedule_audit = {**audit, "operation_mode": "slice_c"}
            models.RaceEventFieldChange.objects.create(
                event=event,
                subject_type=models.RaceEventFieldSubjectType.EVENT,
                subject_key=str(event.pk),
                field_name=field_name,
                old_value=rendered_old,
                new_value=rendered_candidate,
                applied=applied,
                decision=decision,
                rejection_reason=rejection_reason,
                **schedule_audit,
            )
            if not applied:
                continue
            setattr(event, field_name, candidate_value)
            schedule_changed = schedule_changed or field_value_changed
            authority.authority_level = source_priority(candidate_source_class)
            authority.source_class = candidate_source_class
            authority.source_key = source.source_key
            authority.source_url = source.canonical_url
            authority.external_id = source.external_race_id
            authority.observed_at = candidate_watermark
            authority.value_sha256 = hashlib.sha256(
                json.dumps(
                    rendered_candidate,
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            authority.save(
                update_fields=(
                    "authority_level",
                    "source_class",
                    "source_key",
                    "source_url",
                    "external_id",
                    "observed_at",
                    "value_sha256",
                    "updated_at",
                )
            )
        if schedule_changed:
            event.save(
                update_fields=tuple(schedule_candidates) + ("updated_at",)
            )
            tracking = (
                locked_claim.tracking
                if locked_claim is not None
                else models.RaceEventLiveTracking.objects.select_for_update()
                .filter(event=event)
                .first()
            )
            if tracking is not None:
                checkpoints = tuple(
                    models.RaceEventLiveProviderCheckpoint.objects.select_for_update()
                    .filter(tracking=tracking)
                    .order_by("source_key", "data_kind")
                )
                checkpoint_now = candidate_watermark
                for checkpoint in checkpoints:
                    checkpoint.next_poll_at = calculate_next_poll_at(
                        data_kind=checkpoint.data_kind,
                        now=checkpoint_now,
                        race_datetime=(
                            None
                            if event.status == models.RaceEventStatus.POSTPONED
                            else event.race_datetime
                        ),
                        result_confirmed=event.result_confirmed_at is not None,
                        event_terminal=(
                            event.status == models.RaceEventStatus.CANCELLED
                            or (
                                event.status == models.RaceEventStatus.FINISHED
                                and checkpoint.data_kind
                                != models.RaceDataSyncDataKind.RESULT
                            )
                        ),
                    )
                    checkpoint.lock_version += 1
                    checkpoint.save(
                        update_fields=("next_poll_at", "lock_version", "updated_at")
                    )
                tracking.active_attempt_token = ""
                tracking.claim_expires_at = None
                tracking.claim_generation += 1
                tracking.next_poll_at = min(
                    (
                        checkpoint.next_poll_at
                        for checkpoint in checkpoints
                        if checkpoint.next_poll_at is not None
                    ),
                    default=None,
                )
                tracking.lock_version += 1
                tracking.save(
                    update_fields=(
                        "active_attempt_token",
                        "claim_expires_at",
                        "claim_generation",
                        "next_poll_at",
                        "lock_version",
                        "updated_at",
                    )
                )
            if lifecycle is not None:
                lifecycle.schedule_generation += 1
                lifecycle.claim_token = ""
                lifecycle.claim_expires_at = None
                lifecycle.next_refresh_at = event.race_datetime or timezone.now()
                lifecycle.last_source_key = source.source_key
                lifecycle.save(
                    update_fields=(
                        "schedule_generation",
                        "claim_token",
                        "claim_expires_at",
                        "next_refresh_at",
                        "last_source_key",
                        "updated_at",
                    )
                )
            if event.status != old_schedule_values["status"]:
                schedule_generation = (
                    lifecycle.schedule_generation if lifecycle is not None else 0
                )
                models.RaceEventLifecycleTransition.objects.get_or_create(
                    dedupe_key=(
                        f"data-sync-source:{event.pk}:{observation.pk}:"
                        f"{event.status}"
                    ),
                    defaults={
                        "event": event,
                        "from_status": old_schedule_values["status"],
                        "to_status": event.status,
                        "reason_code": "provider_status_update",
                        "effective_at": candidate_watermark,
                        "source_authority": candidate_source_class,
                        "source_key": source.source_key,
                        "source_url": source.canonical_url,
                        "trigger_task": task_id,
                        "run_id": run_id,
                        "schedule_generation": schedule_generation,
                        "record_kind": (
                            models.RaceEventLifecycleTransitionKind.APPLIED
                        ),
                        "metadata": {
                            "observation_id": observation.pk,
                            "normalized_sha256": observation.normalized_sha256,
                        },
                    },
                )
                tracking_state = {
                    models.RaceEventStatus.SCHEDULED: models.RaceEventLiveState.SCHEDULED,
                    models.RaceEventStatus.POSTPONED: models.RaceEventLiveState.SCHEDULED,
                    models.RaceEventStatus.FINISHED: models.RaceEventLiveState.AWAITING_RESULT,
                }.get(event.status)
                if tracking_state:
                    models.RaceEventLiveTracking.objects.filter(event=event).update(
                        state=tracking_state,
                        updated_at=timezone.now(),
                    )
            transaction.on_commit(invalidate_public_race_cache)
            aggregate = "applied"
        return RacecardReconciliationDecision(
            aggregate,
            f"racecard_{aggregate}",
            event.pk,
            observation.pk,
            claim_invalidated=bool(schedule_changed and claim_guard is not None),
        )


def reconcile_racecard_observation(
    *,
    observation_id: int,
    expected_event_id: int,
    allow_schedule_apply: bool,
    allow_racecard_apply: bool = True,
    task_id: str,
    run_id: str,
    claim_guard: RaceDataSyncClaim | None = None,
) -> RacecardReconciliationDecision:
    try:
        return _reconcile_racecard_observation_atomic(
            observation_id=observation_id,
            expected_event_id=expected_event_id,
            allow_schedule_apply=allow_schedule_apply,
            allow_racecard_apply=allow_racecard_apply,
            task_id=task_id,
            run_id=run_id,
            claim_guard=claim_guard,
        )
    except _RacecardNeedsReview as review:
        with transaction.atomic():
            for change in review.changes:
                models.RaceEventFieldChange.objects.create(**change)
        return RacecardReconciliationDecision(
            "needs_review",
            review.reason,
            review.event_id,
            review.observation_id,
        )


def cleanup_expired_race_data_raw_payloads(
    *, now: datetime, batch_size: int = 100, max_bytes: int | None = None
) -> RawCleanupResult:
    if not isinstance(now, datetime) or timezone.is_naive(now):
        raise ValueError("now must be aware")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if max_bytes is None:
        max_bytes = int(
            getattr(settings, "RACE_DATA_RAW_CLEANUP_MAX_BYTES", 0) or (2**63 - 1)
        )
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    configured_roots = getattr(settings, "RACE_DATA_RAW_ARTIFACT_ROOTS", ())
    allowed_roots = [Path(value).resolve() for value in configured_roots if value]
    if not allowed_roots:
        allowed_roots = [(Path(settings.MEDIA_ROOT) / "race_data_raw").resolve()]
        if getattr(settings, "RUNNING_TESTS", False):
            allowed_roots.append(Path(tempfile.gettempdir()).resolve())
    candidates: list[models.RaceResultObservation] = []
    held = 0
    cursor_retention = None
    cursor_id = None
    page_size = min(max(batch_size, 100), 1_000)
    while len(candidates) < batch_size:
        page_query = models.RaceResultObservation.objects.filter(
            retention_until__lte=now,
        ).exclude(raw_artifact_path="")
        if cursor_retention is not None and cursor_id is not None:
            page_query = page_query.filter(
                Q(retention_until__gt=cursor_retention)
                | Q(retention_until=cursor_retention, id__gt=cursor_id)
            )
        page = list(page_query.order_by("retention_until", "id")[:page_size])
        if not page:
            break
        for candidate in page:
            cursor_retention = candidate.retention_until
            cursor_id = candidate.id
            provenance = candidate.field_provenance
            if (
                isinstance(provenance, dict)
                and provenance.get("raw_hold") is True
            ):
                held += 1
                continue
            candidates.append(candidate)
            if len(candidates) >= batch_size:
                break
    cleaned = 0
    cleaned_bytes = 0
    skipped = 0
    for candidate in candidates:
        provenance = candidate.field_provenance
        if isinstance(provenance, dict) and provenance.get("raw_hold") is True:
            held += 1
            continue
        path = Path(candidate.raw_artifact_path)
        try:
            resolved_path = path.resolve(strict=False)
        except OSError:
            skipped += 1
            continue
        matching_root = next(
            (
                root
                for root in allowed_roots
                if resolved_path != root and root in resolved_path.parents
            ),
            None,
        )
        if matching_root is None:
            skipped += 1
            continue
        try:
            path_stat = path.lstat()
        except OSError:
            skipped += 1
            continue
        if not stat.S_ISREG(path_stat.st_mode) or path.is_symlink():
            skipped += 1
            continue
        if path_stat.st_size > max_bytes - cleaned_bytes:
            break

        with transaction.atomic():
            current = (
                models.RaceResultObservation.objects.select_for_update()
                .filter(pk=candidate.pk)
                .first()
            )
            if current is None:
                skipped += 1
                continue
            current_provenance = current.field_provenance
            if (
                isinstance(current_provenance, dict)
                and current_provenance.get("raw_hold") is True
            ):
                held += 1
                continue
            if (
                current.raw_artifact_path != candidate.raw_artifact_path
                or current.retention_until is None
                or current.retention_until > now
            ):
                skipped += 1
                continue

            opened_fds: list[int] = []
            try:
                relative_parts = resolved_path.relative_to(matching_root).parts
                if not relative_parts:
                    raise ValueError("artifact path cannot equal its root")
                directory_flags = os.O_RDONLY | os.O_DIRECTORY
                if hasattr(os, "O_NOFOLLOW"):
                    directory_flags |= os.O_NOFOLLOW
                parent_fd = os.open(matching_root, directory_flags)
                opened_fds.append(parent_fd)
                for directory_name in relative_parts[:-1]:
                    parent_fd = os.open(
                        directory_name,
                        directory_flags,
                        dir_fd=parent_fd,
                    )
                    opened_fds.append(parent_fd)
                file_flags = os.O_RDONLY
                if hasattr(os, "O_NOFOLLOW"):
                    file_flags |= os.O_NOFOLLOW
                file_fd = os.open(
                    relative_parts[-1], file_flags, dir_fd=parent_fd
                )
                opened_fds.append(file_fd)
                current_stat = os.fstat(file_fd)
                if (
                    not stat.S_ISREG(current_stat.st_mode)
                    or current_stat.st_dev != path_stat.st_dev
                    or current_stat.st_ino != path_stat.st_ino
                    or stat.S_IFMT(current_stat.st_mode)
                    != stat.S_IFMT(path_stat.st_mode)
                    or current_stat.st_size != path_stat.st_size
                    or current_stat.st_mtime_ns != path_stat.st_mtime_ns
                ):
                    raise OSError("raw artifact identity changed")
                os.close(file_fd)
                opened_fds.pop()
                os.unlink(relative_parts[-1], dir_fd=parent_fd)
                if path.resolve(strict=False) != resolved_path:
                    raise OSError("raw artifact ancestor path changed")
            except (OSError, TypeError, ValueError):
                skipped += 1
                continue
            finally:
                for opened_fd in reversed(opened_fds):
                    try:
                        os.close(opened_fd)
                    except OSError:
                        pass
            updated = models.RaceResultObservation.objects.filter(
                pk=current.pk,
                raw_artifact_path=candidate.raw_artifact_path,
                retention_until__lte=now,
            ).update(raw_artifact_path="", raw_size_bytes=None)
            if updated:
                cleaned += 1
                cleaned_bytes += path_stat.st_size
            else:
                skipped += 1
    return RawCleanupResult(
        cleaned=cleaned,
        cleaned_bytes=cleaned_bytes,
        held=held,
        skipped=skipped,
    )

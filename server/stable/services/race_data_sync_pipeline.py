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
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from stable import models


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


@dataclass(frozen=True)
class RawCleanupResult:
    cleaned: int
    held: int
    skipped: int


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
        )

    def allows(self, *, provider: str, region: str, field_name: str) -> bool:
        return bool(
            self.enabled
            and provider in self.providers
            and region in self.regions
            and field_name in self.fields
        )


@dataclass(frozen=True)
class RaceDataProviderRosterEntry:
    provider: str
    regions: tuple[str, ...]
    source_class: str
    adapter_status: str
    transport_enabled: bool
    apply_enabled: bool
    contract_version: str
    contract_digest: str
    allowed_fields: tuple[str, ...]


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
                and field_name in entry.allowed_fields
                and entry.adapter_status == "implemented"
                and entry.transport_enabled
                and entry.apply_enabled
            ),
            None,
        )


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
    ("horse_racing_nation", ("united_states",), "trusted_publisher", "proof_required"),
    ("hri", ("ireland",), "official_operator", "proof_required"),
    ("jra", ("japan_jra",), "official_operator", "proof_required"),
    ("nar", ("japan_nar",), "official_operator", "proof_required"),
    ("sporting_life", ("ireland", "united_kingdom"), "trusted_publisher", "proof_required"),
    (
        "the_racing_api",
        ("france", "hong_kong", "ireland", "united_kingdom", "united_states"),
        "licensed_api",
        "implemented",
    ),
    ("zeturf", ("france",), "trusted_publisher", "proof_required"),
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
                    "source_class": entry.source_class,
                    "adapter_status": entry.adapter_status,
                    "contract_version": entry.contract_version,
                    "contract_digest": entry.contract_digest,
                }
                for entry in entries
            ],
        }
    )


def build_race_data_provider_roster(
    *, expected_registry_digest: str | None = None
) -> RaceDataProviderRoster:
    flags = RaceDataSyncFlags.from_settings()
    entries = []
    for provider, regions, source_class, adapter_status in _ROSTER_DEFINITIONS:
        contract_version = "racecard-v1"
        contract_digest = _canonical_sha256(
            {
                "provider": provider,
                "regions": list(regions),
                "source_class": source_class,
                "adapter_status": adapter_status,
                "contract_version": contract_version,
                "allowed_fields": list(_ROSTER_ALLOWED_FIELDS),
            }
        )
        runtime_provider_enabled = bool(
            flags.enabled
            and provider in flags.providers
            and set(regions).intersection(flags.regions)
            and adapter_status == "implemented"
        )
        runtime_fields = tuple(
            field
            for field in _ROSTER_ALLOWED_FIELDS
            if field in flags.fields
        )
        runtime_apply_enabled = bool(
            runtime_provider_enabled and runtime_fields
        )
        entries.append(
            RaceDataProviderRosterEntry(
                provider=provider,
                regions=regions,
                source_class=source_class,
                adapter_status=adapter_status,
                transport_enabled=runtime_provider_enabled,
                apply_enabled=runtime_apply_enabled,
                contract_version=contract_version,
                contract_digest=contract_digest,
                allowed_fields=(
                    runtime_fields
                    if runtime_apply_enabled
                    else _ROSTER_ALLOWED_FIELDS
                ),
            )
        )
    roster_entries = tuple(entries)
    registry_digest = _provider_roster_digest(
        schema_version=1, entries=roster_entries
    )
    if (
        expected_registry_digest is not None
        and expected_registry_digest != registry_digest
    ):
        raise ValueError("race data provider roster digest mismatch")
    return RaceDataProviderRoster(
        schema_version=1,
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
    task_id: str,
    run_id: str,
) -> RacecardReconciliationDecision:
    """Apply non-schedule racecard fields under source and identity checks."""

    if allow_schedule_apply:
        return RacecardReconciliationDecision("rejected", "slice_c_required")
    with transaction.atomic():
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
            (entry for entry in roster.entries if entry.provider == source.source_key),
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
            observation=observation, operation_mode="slice_a"
        )
        processed_fields = set(
            existing_changes.values_list(
                "subject_type", "subject_key", "field_name"
            )
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

        event = models.RaceEvent.objects.select_for_update().filter(
            pk=expected_event_id
        ).first()
        if event is None:
            return RacecardReconciliationDecision(
                "rejected", "event_missing", expected_event_id, observation.pk
            )
        audit = _audit_defaults(observation=observation, task_id=task_id, run_id=run_id)
        aggregate = "replayed"
        participants = list(payload["participants"])
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
            candidate_watermark = (
                observation.source_updated_at or observation.observed_at
            )
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
                decision = (
                    "applied"
                    if created or old_value != proposed
                    else "replayed"
                )
                reason = ""
                if not created and old_value != proposed:
                    if locks.get(field_name) is True or authority.manual_lock:
                        decision = "needs_review"
                        reason = "manual_lock"
                    elif (
                        not created
                        and authority.source_key
                        and authority.source_key != source.source_key
                    ):
                        decision = "needs_review"
                        reason = "cross_source_conflict"
                    elif (
                        authority.source_key == source.source_key
                        and authority.observed_at is not None
                        and candidate_watermark <= authority.observed_at
                    ):
                        decision = "needs_review"
                        reason = "stale_source_version"
                applied = decision == "applied"
                if decision == "needs_review":
                    raise _RacecardNeedsReview(
                        reason=reason,
                        event_id=event.pk,
                        observation_id=observation.pk,
                        changes=(
                            {
                                "event": event,
                                "subject_type": models.RaceEventFieldSubjectType.PARTICIPANT,
                                "subject_key": external_runner_id,
                                "field_name": field_name,
                                "old_value": old_value,
                                "new_value": proposed,
                                "applied": False,
                                "decision": "needs_review",
                                "rejection_reason": reason,
                                **audit,
                            },
                        ),
                    )
                models.RaceEventFieldChange.objects.create(
                    event=event,
                    subject_type=models.RaceEventFieldSubjectType.PARTICIPANT,
                    subject_key=external_runner_id,
                    field_name=field_name,
                    old_value=old_value,
                    new_value=proposed,
                    applied=applied,
                    decision=decision,
                    rejection_reason=reason,
                    **audit,
                )
                if applied:
                    setattr(runner, field_name, proposed)
                    runner_field_applied = True
                    if aggregate != "needs_review":
                        aggregate = "applied"
                # Legacy authority_level is deliberately never read or changed.
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

        schedule_candidates: dict[str, Any] = {}
        if "off_time" in payload:
            schedule_candidates["race_datetime"] = payload["off_time"]
        if "local_start_time" in payload:
            schedule_candidates["local_start_time"] = payload["local_start_time"]
        elif (
            payload.get("off_time")
            and event.timezone_name
            and "local_start_time" in set(allowed_fields)
        ):
            try:
                parsed_off = datetime.fromisoformat(
                    str(payload["off_time"]).replace("Z", "+00:00")
                )
                schedule_candidates["local_start_time"] = (
                    parsed_off.astimezone(ZoneInfo(event.timezone_name))
                    .time()
                    .replace(tzinfo=None)
                    .isoformat()
                )
            except (ValueError, KeyError):
                pass
        if "timezone_name" in payload:
            schedule_candidates["timezone_name"] = payload["timezone_name"]
        if payload.get("race_status") in models.RaceEventStatus.values:
            schedule_candidates["status"] = payload["race_status"]
        old_schedule_values = {
            "race_datetime": (
                event.race_datetime.isoformat() if event.race_datetime else None
            ),
            "local_start_time": (
                event.local_start_time.isoformat()
                if event.local_start_time
                else None
            ),
            "timezone_name": event.timezone_name,
            "status": event.status,
        }
        for field_name, candidate_value in schedule_candidates.items():
            if (
                models.RaceEventFieldSubjectType.EVENT,
                str(event.pk),
                field_name,
            ) in processed_fields:
                continue
            models.RaceEventFieldChange.objects.create(
                event=event,
                subject_type=models.RaceEventFieldSubjectType.EVENT,
                subject_key=str(event.pk),
                field_name=field_name,
                old_value=old_schedule_values[field_name],
                new_value=candidate_value,
                applied=False,
                decision="rejected",
                rejection_reason="slice_c_required",
                **audit,
            )
        return RacecardReconciliationDecision(
            aggregate,
            f"racecard_{aggregate}",
            event.pk,
            observation.pk,
        )


def reconcile_racecard_observation(
    *,
    observation_id: int,
    expected_event_id: int,
    allow_schedule_apply: bool,
    task_id: str,
    run_id: str,
) -> RacecardReconciliationDecision:
    try:
        return _reconcile_racecard_observation_atomic(
            observation_id=observation_id,
            expected_event_id=expected_event_id,
            allow_schedule_apply=allow_schedule_apply,
            task_id=task_id,
            run_id=run_id,
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
    *, now: datetime, batch_size: int = 100
) -> RawCleanupResult:
    if not isinstance(now, datetime) or timezone.is_naive(now):
        raise ValueError("now must be aware")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
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
            else:
                skipped += 1
    return RawCleanupResult(cleaned=cleaned, held=held, skipped=skipped)

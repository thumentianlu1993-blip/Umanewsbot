"""Private post-race reference observations for Phase B0.1.

This module deliberately has no publishing, candidate-apply, race-live, task,
or network dependency.  It validates immutable semantic facts and records
manifest-bound provenance in private tables only.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from datetime import date
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from stable.models import (
    RaceEvent,
    RaceEventStatus,
    RaceReferenceCollectionRun,
    RaceReferenceCollectionStatus,
    RaceReferenceMatchStatus,
    RaceReferencePayload,
    RaceReferenceReceipt,
)
from stable.services.race_live_racecard_sync import normalize_identity_text


REFERENCE_SCHEMA_VERSION = 1
MAX_CANONICAL_BYTES = 262_144
MAX_JSON_DEPTH = 12
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "reference_sporting_life": {
        "region": "united_kingdom",
        "host": "sportinglife.com",
        "path_prefix": "/racing/results/",
        "parser_module": "stable.race_reference_parsers.sporting_life",
        "parser_name": "sporting_life",
        "parser_version": "reference-v1",
        "provider_pattern": re.compile(r"^sl:(?P<race_id>[1-9]\d*)$"),
        "path_pattern": re.compile(
            r"^/racing/results/(?P<local_date>\d{4}-\d{2}-\d{2})/"
            r"[^/]+/(?P<race_id>[1-9]\d*)/[^/]+/?$"
        ),
    },
    "reference_zeturf": {
        "region": "france",
        "host": "zeturf.fr",
        "path_prefix": "/fr/course-du-jour/",
        "parser_module": "stable.race_reference_parsers.zeturf",
        "parser_name": "zeturf",
        "parser_version": "reference-v1",
        "provider_pattern": re.compile(
            r"^zt:(?P<local_date>\d{4}-\d{2}-\d{2}):"
            r"R(?P<meeting>[1-9]\d*)C(?P<race>[1-9]\d*)$"
        ),
        "path_pattern": re.compile(
            r"^/fr/course-du-jour/(?P<local_date>\d{4}-\d{2}-\d{2})/"
            r"R(?P<meeting>[1-9]\d*)C(?P<race>[1-9]\d*)-[^/]+/?$"
        ),
    },
    "reference_horse_racing_nation": {
        "region": "united_states",
        "host": "horseracingnation.com",
        "path_prefix": "/entries-results/",
        "parser_module": "stable.race_reference_parsers.horse_racing_nation",
        "parser_name": "horse_racing_nation",
        "parser_version": "reference-v1",
        "provider_pattern": re.compile(
            r"^hrn:(?P<track_slug>[a-z0-9]+(?:-[a-z0-9]+)*):"
            r"(?P<local_date>\d{4}-\d{2}-\d{2}):R(?P<race>[1-9]\d*)$"
        ),
        "path_pattern": re.compile(
            r"^/entries-results/(?P<track_slug>[a-z0-9]+(?:-[a-z0-9]+)*)/"
            r"(?P<local_date>\d{4}-\d{2}-\d{2})/?$"
        ),
    },
}

_TOP_LEVEL_FIELDS = {
    "schema_version",
    "source_key",
    "country_region",
    "provider_event_key",
    "race",
    "runners",
    "completeness",
}
_RACE_FIELDS = {
    "source_race_name",
    "source_racecourse",
    "local_date",
    "source_start_time",
}
_RUNNER_FIELDS = {
    "source_runner_key",
    "horse_number",
    "draw",
    "horse_name",
    "jockey_name",
    "trainer_name",
    "carried_weight",
    "odds_value",
    "running_status",
    "source_reported_finish_position",
    "margin",
}
_RUNNER_LIMITS = {
    "source_runner_key": 255,
    "horse_number": 32,
    "draw": 32,
    "horse_name": 255,
    "jockey_name": 255,
    "trainer_name": 255,
    "carried_weight": 64,
    "odds_value": 64,
    "running_status": 64,
    "source_reported_finish_position": 32,
    "margin": 64,
}
_COMPLETENESS_FIELDS = {"race_identity", "runners", "results", "gap_codes"}
_COMPLETENESS_VALUES = {"complete", "partial", "unknown"}
_FORBIDDEN_KEYS = {
    "official",
    "is_official",
    "is_confirmed",
    "official_finish_position",
    "result_confirmed_at",
    "authority",
    "publication_status",
    "apply",
}
_PROVENANCE_FIELDS = {
    "source_url",
    "final_url",
    "source_observed_at",
    "fetched_at",
    "parser",
    "legacy_payload_sha256",
    "raw_sha256",
    "source_cache_ref",
}


def get_reference_parser_contract(source_key: str) -> dict[str, str]:
    """Return the frozen parser identity without importing parser code."""
    registry = SOURCE_REGISTRY.get(source_key)
    if registry is None:
        _fail("unsupported reference source")
    return {
        "module": registry["parser_module"],
        "name": registry["parser_name"],
        "version": registry["parser_version"],
    }


def _fail(message: str) -> None:
    raise ValidationError(message)


def _normalize_json(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_JSON_DEPTH:
        _fail(f"JSON depth exceeds {MAX_JSON_DEPTH}")
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        _fail("float values are forbidden")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize_json(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                _fail("JSON object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                _fail("normalization produced a duplicate JSON key")
            normalized[normalized_key] = _normalize_json(item, depth=depth + 1)
        return normalized
    _fail(f"unsupported JSON type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    normalized = _normalize_json(value)
    try:
        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"cannot canonicalize JSON: {exc}") from exc


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _require_exact_fields(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        _fail(
            f"{label} fields differ: missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )
    return value


def _require_string(value: Any, label: str, maximum: int, *, nonempty: bool = False) -> str:
    if not isinstance(value, str):
        _fail(f"{label} must be a string")
    if nonempty and not value:
        _fail(f"{label} must not be empty")
    if len(value) > maximum:
        _fail(f"{label} exceeds {maximum} characters")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail(f"{label} must be a lowercase 64-hex SHA-256")
    return value


def _require_date(value: Any, label: str) -> str:
    value = _require_string(value, label, 10, nonempty=True)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{label} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        _fail(f"{label} must be canonical YYYY-MM-DD")
    return value


def _require_aware_datetime(value: Any, label: str, *, nullable: bool = False):
    if value is None and nullable:
        return None
    value = _require_string(value, label, 64, nonempty=True)
    parsed = parse_datetime(value)
    if parsed is None or timezone.is_naive(parsed):
        _fail(f"{label} must be an aware ISO-8601 datetime")
    return parsed


def _find_forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_KEYS:
                found.add(key)
            found.update(_find_forbidden_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_forbidden_keys(item))
    return found


def normalize_legacy_runner(legacy_runner: Mapping[str, Any]) -> dict[str, str]:
    """Downgrade historical parser vocabulary into source-reported facts."""
    if not isinstance(legacy_runner, Mapping):
        _fail("legacy runner must be an object")
    aliases = {
        "source_runner_key": ("source_runner_key", "runner_id", "horse_id"),
        "horse_number": ("horse_number", "number", "cloth_number"),
        "draw": ("draw", "barrier"),
        "horse_name": ("horse_name", "name"),
        "jockey_name": ("jockey_name", "jockey"),
        "trainer_name": ("trainer_name", "trainer"),
        "carried_weight": ("carried_weight", "weight"),
        "odds_value": ("odds_value", "odds"),
        "running_status": ("running_status", "status"),
        "source_reported_finish_position": (
            "source_reported_finish_position",
            "official_finish_position",
            "finish_position",
            "position",
        ),
        "margin": ("margin",),
    }
    normalized: dict[str, str] = {}
    for output_key, input_keys in aliases.items():
        raw = ""
        for input_key in input_keys:
            if input_key in legacy_runner and legacy_runner[input_key] is not None:
                raw = legacy_runner[input_key]
                break
        if isinstance(raw, bool) or isinstance(raw, (dict, list, float)):
            _fail(f"legacy runner field {output_key} has unsupported type")
        normalized[output_key] = unicodedata.normalize("NFC", str(raw))
    return normalized


def enforce_source_completeness(
    payload: Mapping[str, Any],
    *,
    legacy_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    del legacy_metadata  # Historical confirmation is intentionally non-authoritative.
    normalized = deepcopy(dict(payload))
    if normalized.get("source_key") == "reference_horse_racing_nation":
        completeness = normalized.get("completeness")
        if isinstance(completeness, dict):
            completeness["results"] = "partial"
            gaps = completeness.get("gap_codes")
            if isinstance(gaps, list) and "hrn_results_partial" not in gaps:
                gaps.append("hrn_results_partial")
    return normalized


def normalize_reference_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_json(payload)
    forbidden = _find_forbidden_keys(normalized)
    if forbidden:
        _fail(f"authority-bearing keys are forbidden: {sorted(forbidden)}")
    normalized = enforce_source_completeness(normalized)

    top = _require_exact_fields(normalized, _TOP_LEVEL_FIELDS, "payload")
    if top["schema_version"] != REFERENCE_SCHEMA_VERSION or isinstance(
        top["schema_version"], bool
    ):
        _fail("schema_version must equal 1")
    source_key = _require_string(top["source_key"], "source_key", 64, nonempty=True)
    registry = SOURCE_REGISTRY.get(source_key)
    if registry is None:
        _fail("source_key is not registered for internal references")
    region = _require_string(top["country_region"], "country_region", 32, nonempty=True)
    if region != registry["region"]:
        _fail("country_region does not match source registry")
    provider_event_key = _require_string(
        top["provider_event_key"], "provider_event_key", 255, nonempty=True
    )
    if registry["provider_pattern"].fullmatch(provider_event_key) is None:
        _fail("provider_event_key does not match source contract")

    race = _require_exact_fields(top["race"], _RACE_FIELDS, "race")
    _require_string(race["source_race_name"], "race.source_race_name", 255)
    _require_string(race["source_racecourse"], "race.source_racecourse", 255)
    _require_date(race["local_date"], "race.local_date")
    _require_string(race["source_start_time"], "race.source_start_time", 64)

    runners = top["runners"]
    if not isinstance(runners, list) or len(runners) > 80:
        _fail("runners must be an array with at most 80 items")
    runner_keys: set[str] = set()
    for index, runner_value in enumerate(runners):
        runner = _require_exact_fields(
            runner_value, _RUNNER_FIELDS, f"runners[{index}]"
        )
        for field, maximum in _RUNNER_LIMITS.items():
            _require_string(
                runner[field],
                f"runners[{index}].{field}",
                maximum,
                nonempty=field == "source_runner_key",
            )
        if runner["source_runner_key"] in runner_keys:
            _fail("source_runner_key must be unique within a payload")
        runner_keys.add(runner["source_runner_key"])

    completeness = _require_exact_fields(
        top["completeness"], _COMPLETENESS_FIELDS, "completeness"
    )
    for field in ("race_identity", "runners", "results"):
        if completeness[field] not in _COMPLETENESS_VALUES:
            _fail(f"completeness.{field} has an invalid value")
    gaps = completeness["gap_codes"]
    if not isinstance(gaps, list) or len(gaps) > 32:
        _fail("completeness.gap_codes must contain at most 32 items")
    seen_gaps: set[str] = set()
    for index, gap in enumerate(gaps):
        gap = _require_string(
            gap, f"completeness.gap_codes[{index}]", 64, nonempty=True
        )
        if gap in seen_gaps:
            _fail("completeness.gap_codes must be unique")
        seen_gaps.add(gap)

    canonical_bytes = canonical_json_bytes(top)
    if len(canonical_bytes) > MAX_CANONICAL_BYTES:
        _fail(f"canonical payload exceeds {MAX_CANONICAL_BYTES} bytes")
    payload_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    return {
        "payload": top,
        "canonical_bytes": canonical_bytes,
        "payload_sha256": payload_sha256,
        "observation_key": f"{source_key}:{provider_event_key}",
    }


def _safe_https_parts(url: str, *, registry: Mapping[str, Any]):
    _require_string(url, "source_url", 1000, nonempty=True)
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    root_host = registry["host"]
    if (
        parts.scheme.lower() != "https"
        or not host
        or not (host == root_host or host.endswith("." + root_host))
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
        or parts.query
        or parts.fragment
    ):
        _fail("source URL violates the fixed HTTPS host contract")
    path_match = registry["path_pattern"].fullmatch(parts.path)
    if path_match is None:
        _fail("source URL violates the fixed path contract")
    return parts, path_match.groupdict()


def validate_source_identity(
    *,
    source_key: str,
    country_region: str,
    provider_event_key: str,
    source_url: str,
) -> dict[str, Any]:
    registry = SOURCE_REGISTRY.get(source_key)
    if registry is None:
        _fail("unsupported reference source")
    if country_region != registry["region"]:
        _fail("source region does not match registry")
    provider_match = registry["provider_pattern"].fullmatch(provider_event_key)
    if provider_match is None:
        _fail("provider event key violates source contract")
    _parts, path_values = _safe_https_parts(source_url, registry=registry)
    provider_values = provider_match.groupdict()

    for key in set(provider_values) & set(path_values):
        if provider_values[key] != path_values[key]:
            _fail(f"provider key and URL disagree on {key}")
    if source_key == "reference_sporting_life":
        return {"race_id": int(provider_values["race_id"])}
    if source_key == "reference_zeturf":
        return {
            "local_date": provider_values["local_date"],
            "meeting": int(provider_values["meeting"]),
            "race": int(provider_values["race"]),
        }
    return {
        "track_slug": provider_values["track_slug"],
        "local_date": provider_values["local_date"],
        "race": int(provider_values["race"]),
    }


def normalize_reference_racecourse_identity(
    *,
    source_key: str,
    value: object,
) -> str:
    """Return a source-aware comparison token without changing stored raw text."""
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_like = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    token = re.sub(r"[^a-z0-9]+", "", ascii_like.casefold())
    reviewed_alias_groups = {
        "reference_sporting_life": {
            "ascot": frozenset({"ascot", "royalascot"}),
        },
        "reference_zeturf": {
            "parislongchamp": frozenset({"longchamp", "parislongchamp"}),
        },
        "reference_horse_racing_nation": {
            "belmontpark": frozenset({"belmont", "belmontpark"}),
            "losalamitos": frozenset(
                {"losalamitos", "losalamitosracecourse"}
            ),
        },
    }.get(source_key, {})
    for canonical, aliases in reviewed_alias_groups.items():
        if token in aliases:
            return canonical
    return token


def reference_racecourse_matches(
    *,
    source_key: str,
    page_value: object,
    manifest_value: object,
) -> bool:
    """Compare a page venue to the frozen DB venue using the reviewed aliases."""
    page = normalize_reference_racecourse_identity(
        source_key=source_key,
        value=page_value,
    )
    frozen = normalize_reference_racecourse_identity(
        source_key=source_key,
        value=manifest_value,
    )
    if not page or not frozen:
        return False
    return page == frozen


def _validate_matched_page_identity(
    *,
    semantic_payload: Mapping[str, Any],
    manifest_event: Mapping[str, Any],
) -> None:
    race = semantic_payload["race"]
    completeness = semantic_payload["completeness"]
    if completeness["race_identity"] != "complete":
        _fail("matched observation requires complete page race identity")
    if not race["source_race_name"].strip():
        _fail("matched observation requires a source race name")
    try:
        normalized_race_name = normalize_identity_text(
            race["source_race_name"]
        )
    except ValueError:
        _fail("matched observation source race name is invalid")
    if normalized_race_name not in set(
        manifest_event["normalized_accepted_race_names"]
    ):
        _fail("matched observation race name conflicts with manifest event")
    if race["local_date"] != manifest_event["local_date"]:
        _fail("matched observation local date differs from manifest event")
    if not reference_racecourse_matches(
        source_key=semantic_payload["source_key"],
        page_value=race["source_racecourse"],
        manifest_value=manifest_event["racecourse"],
    ):
        _fail("matched observation racecourse conflicts with manifest event")


def match_reference_observation(
    observation: Mapping[str, Any],
    *,
    candidates: Iterable[Mapping[str, Any]],
    strong_identity_evidence: Mapping[str, Any] | None,
    classification_version: str,
) -> dict[str, Any]:
    """Classify local candidates without ever promoting a name-only match."""
    envelope = normalize_reference_payload(observation)
    candidate_list = list(candidates)
    if not strong_identity_evidence:
        return {
            "match_status": (
                RaceReferenceMatchStatus.AMBIGUOUS
                if len(candidate_list) > 1
                else RaceReferenceMatchStatus.UNMATCHED
            ),
            "event_id": None,
            "match_confidence": 0,
            "match_evidence": {
                "reason": "missing_strong_identity",
                "candidate_count": len(candidate_list),
            },
            "classification_version": classification_version,
        }

    event_id = strong_identity_evidence.get("event_id")
    matches = [
        candidate
        for candidate in candidate_list
        if event_id is not None and candidate.get("event_id") == event_id
    ]
    race = envelope["payload"]["race"]
    exact = [
        candidate
        for candidate in matches
        if candidate.get("country_region")
        == envelope["payload"]["country_region"]
        and str(candidate.get("local_date")) == race["local_date"]
        and reference_racecourse_matches(
            source_key=envelope["payload"]["source_key"],
            page_value=race["source_racecourse"],
            manifest_value=candidate.get("racecourse"),
        )
    ]
    if len(exact) != 1:
        return {
            "match_status": (
                RaceReferenceMatchStatus.AMBIGUOUS
                if len(exact) > 1
                else RaceReferenceMatchStatus.UNMATCHED
            ),
            "event_id": None,
            "match_confidence": 0,
            "match_evidence": {
                "reason": "strong_identity_candidate_mismatch",
                "candidate_count": len(exact),
            },
            "classification_version": classification_version,
        }
    return {
        "match_status": RaceReferenceMatchStatus.MATCHED,
        "event_id": exact[0]["event_id"],
        "match_confidence": 100,
        "match_evidence": _normalize_json(dict(strong_identity_evidence)),
        "classification_version": classification_version,
    }


def _normalize_provenance(
    provenance: Mapping[str, Any],
    *,
    source_key: str | None = None,
    country_region: str | None = None,
    provider_event_key: str | None = None,
) -> tuple[dict[str, Any], Any, Any]:
    normalized = _normalize_json(provenance)
    value = _require_exact_fields(normalized, _PROVENANCE_FIELDS, "provenance")
    parser = _require_exact_fields(value["parser"], {"name", "version"}, "provenance.parser")
    _require_string(parser["name"], "provenance.parser.name", 64, nonempty=True)
    _require_string(parser["version"], "provenance.parser.version", 64, nonempty=True)
    _require_sha256(value["legacy_payload_sha256"], "legacy_payload_sha256")
    _require_sha256(value["raw_sha256"], "raw_sha256")
    source_ref = _require_string(
        value["source_cache_ref"], "source_cache_ref", 500, nonempty=True
    )
    ref_path = PurePosixPath(source_ref)
    if (
        ref_path.is_absolute()
        or ".." in ref_path.parts
        or source_ref != ref_path.as_posix()
        or len(ref_path.parts) != 2
        or ref_path.parts[0] != "raw"
        or not ref_path.parts[1].endswith(".body")
    ):
        _fail("source_cache_ref must be a safe relative POSIX path")
    source_observed_at = _require_aware_datetime(
        value["source_observed_at"], "source_observed_at", nullable=True
    )
    fetched_at = _require_aware_datetime(value["fetched_at"], "fetched_at")
    if source_key and country_region and provider_event_key:
        validate_source_identity(
            source_key=source_key,
            country_region=country_region,
            provider_event_key=provider_event_key,
            source_url=value["source_url"],
        )
        validate_source_identity(
            source_key=source_key,
            country_region=country_region,
            provider_event_key=provider_event_key,
            source_url=value["final_url"],
        )
    else:
        for field in ("source_url", "final_url"):
            url = _require_string(value[field], field, 1000, nonempty=True)
            parts = urlsplit(url)
            if (
                parts.scheme.lower() != "https"
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
            ):
                _fail(f"{field} must be a credential-free HTTPS URL")
    return value, source_observed_at, fetched_at


def hash_reference_provenance(provenance: Mapping[str, Any]) -> str:
    normalized, _source_observed_at, _fetched_at = _normalize_provenance(provenance)
    return canonical_json_sha256(normalized)


_MANIFEST_FIELDS = {
    "schema_version",
    "purpose",
    "source_key",
    "reference_schema_version",
    "parser",
    "generated_at",
    "events",
}
_MANIFEST_EVENT_FIELDS = {
    "event_id",
    "slug",
    "country_region",
    "local_date",
    "timezone_name",
    "racecourse",
    "original_name",
    "normalized_accepted_race_names",
    "status",
    "provider_event_key",
    "source_url",
    "event_snapshot_sha256",
}
_EVENT_SNAPSHOT_FIELDS = (
    "event_id",
    "slug",
    "country_region",
    "local_date",
    "timezone_name",
    "racecourse",
    "original_name",
    "normalized_accepted_race_names",
    "status",
)
_DATABASE_EVENT_SNAPSHOT_FIELDS = tuple(
    field
    for field in _EVENT_SNAPSHOT_FIELDS
    if field != "normalized_accepted_race_names"
)


def validate_reference_manifest(
    manifest: Mapping[str, Any],
    *,
    manifest_sha256: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_json(manifest)
    value = _require_exact_fields(normalized, _MANIFEST_FIELDS, "manifest")
    if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
        _fail("manifest schema_version must equal 1")
    if value["purpose"] != "internal_reference_post_race":
        _fail("manifest purpose is not internal_reference_post_race")
    source_key = _require_string(value["source_key"], "manifest.source_key", 64, nonempty=True)
    registry = SOURCE_REGISTRY.get(source_key)
    if registry is None:
        _fail("manifest source is not registered")
    if value["reference_schema_version"] != 1 or isinstance(
        value["reference_schema_version"], bool
    ):
        _fail("reference_schema_version must equal 1")
    parser = _require_exact_fields(value["parser"], {"name", "version"}, "manifest.parser")
    _require_string(parser["name"], "manifest.parser.name", 64, nonempty=True)
    _require_string(parser["version"], "manifest.parser.version", 64, nonempty=True)
    parser_contract = get_reference_parser_contract(source_key)
    if parser != {
        "name": parser_contract["name"],
        "version": parser_contract["version"],
    }:
        _fail("manifest parser identity does not match the frozen source contract")
    _require_aware_datetime(value["generated_at"], "manifest.generated_at")
    events = value["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= 100:
        _fail("manifest events must contain 1..100 items")
    event_ids: set[int] = set()
    provider_keys: set[str] = set()
    for index, event in enumerate(events):
        event = _require_exact_fields(
            event, _MANIFEST_EVENT_FIELDS, f"manifest.events[{index}]"
        )
        event_id = event["event_id"]
        if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
            _fail("manifest event_id must be a positive integer")
        if event_id in event_ids:
            _fail("manifest event_id must be unique")
        event_ids.add(event_id)
        _require_string(event["slug"], "manifest.event.slug", 255, nonempty=True)
        if event["country_region"] != registry["region"]:
            _fail("manifest event region does not match source")
        _require_date(event["local_date"], "manifest.event.local_date")
        _require_string(
            event["timezone_name"], "manifest.event.timezone_name", 64, nonempty=True
        )
        _require_string(event["racecourse"], "manifest.event.racecourse", 255, nonempty=True)
        _require_string(
            event["original_name"], "manifest.event.original_name", 255, nonempty=True
        )
        accepted_names = event["normalized_accepted_race_names"]
        if not isinstance(accepted_names, list) or not accepted_names:
            _fail(
                "manifest event normalized_accepted_race_names "
                "must be a non-empty array"
            )
        normalized_names = []
        for name in accepted_names:
            normalized_name = _require_string(
                name,
                "manifest.event.normalized_accepted_race_names[]",
                255,
                nonempty=True,
            )
            try:
                if normalize_identity_text(normalized_name) != normalized_name:
                    _fail(
                        "manifest event accepted race names "
                        "must already be normalized"
                    )
            except ValueError:
                _fail("manifest event accepted race name is invalid")
            normalized_names.append(normalized_name)
        if normalized_names != sorted(set(normalized_names)):
            _fail(
                "manifest event accepted race names "
                "must be sorted and unique"
            )
        try:
            normalized_original_name = normalize_identity_text(
                event["original_name"]
            )
        except ValueError:
            _fail("manifest event original name is invalid")
        if normalized_original_name not in normalized_names:
            _fail("manifest event original name is absent from accepted names")
        if event["status"] != RaceEventStatus.FINISHED:
            _fail("manifest only accepts finished events")
        provider_key = _require_string(
            event["provider_event_key"],
            "manifest.event.provider_event_key",
            255,
            nonempty=True,
        )
        if provider_key in provider_keys:
            _fail("manifest provider identity must be unique")
        provider_keys.add(provider_key)
        validate_source_identity(
            source_key=source_key,
            country_region=event["country_region"],
            provider_event_key=provider_key,
            source_url=event["source_url"],
        )
        snapshot = {field: event[field] for field in _EVENT_SNAPSHOT_FIELDS}
        expected_snapshot_sha = canonical_json_sha256(snapshot)
        supplied_snapshot_sha = _require_sha256(
            event["event_snapshot_sha256"], "event_snapshot_sha256"
        )
        if supplied_snapshot_sha != expected_snapshot_sha:
            _fail("event_snapshot_sha256 does not match manifest snapshot")
    computed_sha = canonical_json_sha256(value)
    if manifest_sha256 is not None:
        _require_sha256(manifest_sha256, "manifest_sha256")
        if manifest_sha256 != computed_sha:
            _fail("manifest SHA-256 mismatch")
    return value


def _database_snapshot(event: RaceEvent) -> dict[str, Any]:
    return {
        "event_id": event.pk,
        "slug": event.slug,
        "country_region": event.country_region,
        "local_date": event.local_date.isoformat() if event.local_date else None,
        "timezone_name": event.timezone_name,
        "racecourse": event.racecourse,
        "original_name": event.original_name,
        "status": event.status,
    }


def validate_manifest_database_snapshot(
    manifest: Mapping[str, Any],
    *,
    lock_rows: bool = False,
) -> dict[int, RaceEvent]:
    queryset = RaceEvent.objects
    if lock_rows:
        queryset = queryset.select_for_update()
    ids = [item["event_id"] for item in manifest["events"]]
    events_by_id = queryset.in_bulk(ids)
    if set(events_by_id) != set(ids):
        _fail("one or more manifest events no longer exist")
    for item in manifest["events"]:
        event = events_by_id[item["event_id"]]
        snapshot = _database_snapshot(event)
        expected = {
            field: item[field]
            for field in _DATABASE_EVENT_SNAPSHOT_FIELDS
        }
        if snapshot != expected:
            _fail(f"RaceEvent {event.pk} drifted from the frozen manifest")
        frozen_snapshot = {
            field: item[field] for field in _EVENT_SNAPSHOT_FIELDS
        }
        if (
            canonical_json_sha256(frozen_snapshot)
            != item["event_snapshot_sha256"]
        ):
            _fail(f"RaceEvent {event.pk} snapshot hash drifted")
    return events_by_id


def _advisory_lock(manifest_sha256: str, artifact_sha256: str) -> None:
    if connection.vendor != "postgresql":
        return
    digest = hashlib.sha256(
        f"race-reference:{manifest_sha256}:{artifact_sha256}".encode("ascii")
    ).digest()
    lock_id = int.from_bytes(digest[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])


def _artifact_sha(artifact: Mapping[str, Any]) -> str:
    value = artifact.get("artifact_sha256")
    return _require_sha256(value, "artifact.artifact_sha256")


def _run_defaults(
    manifest: Mapping[str, Any],
    artifact: Mapping[str, Any],
    *,
    now,
    collection_started_at=None,
    collection_finished_at=None,
) -> dict[str, Any]:
    local_dates = [date.fromisoformat(item["local_date"]) for item in manifest["events"]]
    summary = artifact.get("summary")
    if summary is None:
        summary = {}
    summary = _normalize_json(summary)
    if not isinstance(summary, dict):
        _fail("artifact summary must be an object")
    errors = artifact.get("error_summary")
    if errors is None:
        errors = {}
    errors = _normalize_json(errors)
    if not isinstance(errors, dict):
        _fail("artifact error_summary must be an object")
    numeric_fields: dict[str, int] = {}
    for field in ("request_count", "cache_hit_count", "error_count"):
        raw = artifact.get(field, 0)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            _fail(f"artifact.{field} must be a non-negative integer")
        numeric_fields[field] = raw
    return {
        "source_key": manifest["source_key"],
        "country_region": SOURCE_REGISTRY[manifest["source_key"]]["region"],
        "parser_name": manifest["parser"]["name"],
        "parser_version": manifest["parser"]["version"],
        "local_date_from": min(local_dates),
        "local_date_to": max(local_dates),
        "target_count": len(manifest["events"]),
        "status": RaceReferenceCollectionStatus.FINISHED,
        "trigger_kind": "management_command",
        "started_at": collection_started_at or now,
        "finished_at": collection_finished_at or now,
        **numeric_fields,
        "summary": summary,
        "error_summary": errors,
    }


def record_reference_collection(
    *,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    artifact: Mapping[str, Any],
    fail_after_receipt_for_test: bool = False,
    collection_started_at=None,
    collection_finished_at=None,
) -> dict[str, Any]:
    """Atomically record one verified, already-collected in-memory artifact."""
    normalized_manifest = validate_reference_manifest(
        manifest, manifest_sha256=manifest_sha256
    )
    artifact_sha256 = _artifact_sha(artifact)
    observations = artifact.get("observations", [])
    if not isinstance(observations, list):
        _fail("artifact.observations must be an array")

    with transaction.atomic():
        _advisory_lock(manifest_sha256, artifact_sha256)
        existing = RaceReferenceCollectionRun.objects.filter(
            scope_manifest_sha256=manifest_sha256,
            artifact_sha256=artifact_sha256,
        ).first()
        if existing is not None:
            return {
                "run": existing,
                "run_id": existing.pk,
                "replayed": True,
                "receipt_count": existing.receipts.count(),
            }

        events_by_id = validate_manifest_database_snapshot(
            normalized_manifest, lock_rows=True
        )
        manifest_by_event_id = {
            event["event_id"]: event for event in normalized_manifest["events"]
        }
        manifest_by_provider_key = {
            event["provider_event_key"]: event for event in normalized_manifest["events"]
        }
        now = timezone.now()
        run = RaceReferenceCollectionRun.objects.create(
            scope_manifest_sha256=manifest_sha256,
            artifact_sha256=artifact_sha256,
            **_run_defaults(
                normalized_manifest,
                artifact,
                now=now,
                collection_started_at=collection_started_at,
                collection_finished_at=collection_finished_at,
            ),
        )

        counters = {
            "matched": 0,
            "unmatched": 0,
            "ambiguous": 0,
            "source_only": 0,
            "partial": 0,
            "unchanged": 0,
            "changed": 0,
        }
        seen_payload_ids: set[int] = set()
        for index, observation in enumerate(observations):
            if not isinstance(observation, dict):
                _fail(f"artifact.observations[{index}] must be an object")
            allowed_observation_fields = {
                "payload",
                "provenance",
                "event_id",
                "match_status",
                "match_confidence",
                "match_evidence",
                "classification_version",
            }
            if set(observation) != allowed_observation_fields:
                _fail(f"artifact.observations[{index}] fields differ from contract")

            envelope = normalize_reference_payload(observation["payload"])
            semantic = envelope["payload"]
            if semantic["source_key"] != normalized_manifest["source_key"]:
                _fail("observation source does not match manifest")
            manifest_event = manifest_by_provider_key.get(semantic["provider_event_key"])
            if manifest_event is None:
                _fail("observation provider identity is outside manifest")
            if semantic["country_region"] != manifest_event["country_region"]:
                _fail("observation region does not match manifest")

            provenance, source_observed_at, fetched_at = _normalize_provenance(
                observation["provenance"],
                source_key=semantic["source_key"],
                country_region=semantic["country_region"],
                provider_event_key=semantic["provider_event_key"],
            )
            if provenance["source_url"] != manifest_event["source_url"]:
                _fail("observation source URL does not equal manifest URL")
            if provenance["parser"] != normalized_manifest["parser"]:
                _fail("observation parser provenance does not match manifest")

            match_status = observation["match_status"]
            if match_status not in RaceReferenceMatchStatus.values:
                _fail("invalid match_status")
            event_id = observation["event_id"]
            if match_status == RaceReferenceMatchStatus.MATCHED:
                if (
                    isinstance(event_id, bool)
                    or not isinstance(event_id, int)
                    or event_id != manifest_event["event_id"]
                ):
                    _fail("matched receipt must bind the manifest event")
                event = events_by_id[event_id]
                _validate_matched_page_identity(
                    semantic_payload=semantic,
                    manifest_event=manifest_event,
                )
            else:
                if event_id is not None:
                    _fail("non-matched receipt cannot bind an event")
                event = None
            confidence = observation["match_confidence"]
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, int)
                or not 0 <= confidence <= 100
            ):
                _fail("match_confidence must be an integer from 0 to 100")
            evidence = _normalize_json(observation["match_evidence"])
            if not isinstance(evidence, dict):
                _fail("match_evidence must be an object")
            classification_version = _require_string(
                observation["classification_version"],
                "classification_version",
                64,
                nonempty=True,
            )

            payload, _created = RaceReferencePayload.objects.get_or_create(
                source_key=semantic["source_key"],
                observation_key=envelope["observation_key"],
                payload_sha256=envelope["payload_sha256"],
                defaults={
                    "provider_event_key": semantic["provider_event_key"],
                    "structured_payload": semantic,
                },
            )
            if payload.provider_event_key != semantic["provider_event_key"]:
                _fail("existing semantic payload identity is inconsistent")
            if payload.structured_payload != semantic:
                _fail("existing semantic payload hash collision")
            if payload.pk in seen_payload_ids:
                _fail("artifact contains duplicate semantic payload membership")
            seen_payload_ids.add(payload.pk)

            completeness = semantic["completeness"]
            is_partial = any(
                completeness[field] != "complete"
                for field in ("race_identity", "runners", "results")
            )
            if is_partial:
                counters["partial"] += 1
            counters[match_status] += 1

            if event is not None:
                previous = (
                    RaceReferenceReceipt.objects.filter(
                        event=event,
                        payload__source_key=semantic["source_key"],
                        match_status=RaceReferenceMatchStatus.MATCHED,
                    )
                    .select_related("payload")
                    .order_by("-recorded_at", "-pk")
                    .first()
                )
                if previous is not None:
                    if previous.payload.payload_sha256 == envelope["payload_sha256"]:
                        counters["unchanged"] += 1
                    else:
                        counters["changed"] += 1

            RaceReferenceReceipt.objects.create(
                run=run,
                payload=payload,
                source_url=provenance["source_url"],
                final_url=provenance["final_url"],
                source_observed_at=source_observed_at,
                fetched_at=fetched_at,
                parser_name=provenance["parser"]["name"],
                parser_version=provenance["parser"]["version"],
                legacy_payload_sha256=provenance["legacy_payload_sha256"],
                raw_sha256=provenance["raw_sha256"],
                source_cache_ref=provenance["source_cache_ref"],
                provenance_sha256=canonical_json_sha256(provenance),
                event=event,
                match_status=match_status,
                match_confidence=confidence,
                match_evidence=evidence,
                event_snapshot={
                    field: manifest_event[field] for field in _EVENT_SNAPSHOT_FIELDS
                },
                event_snapshot_sha256=manifest_event["event_snapshot_sha256"],
                classification_version=classification_version,
                is_partial=is_partial,
                gap_codes=completeness["gap_codes"],
            )
            if fail_after_receipt_for_test:
                raise RuntimeError("forced failure after receipt")

        run.matched_count = counters["matched"]
        run.unmatched_count = counters["unmatched"]
        run.ambiguous_count = counters["ambiguous"]
        run.partial_count = counters["partial"]
        run.unchanged_count = counters["unchanged"]
        run.changed_count = counters["changed"]
        run.save(
            update_fields=(
                "matched_count",
                "unmatched_count",
                "ambiguous_count",
                "partial_count",
                "unchanged_count",
                "changed_count",
            )
        )
        return {
            "run": run,
            "run_id": run.pk,
            "replayed": False,
            "receipt_count": len(observations),
        }


def build_reference_collection_summary(run: RaceReferenceCollectionRun) -> dict[str, Any]:
    return {
        "run_id": run.pk,
        "source_key": run.source_key,
        "target_count": run.target_count,
        "matched": run.matched_count,
        "unmatched": run.unmatched_count,
        "ambiguous": run.ambiguous_count,
        "source_only": run.receipts.filter(
            match_status=RaceReferenceMatchStatus.SOURCE_ONLY
        ).count(),
        "partial": run.partial_count,
        "unchanged": run.unchanged_count,
        "changed": run.changed_count,
        "errors": run.error_count,
        "artifact_sha256": run.artifact_sha256,
    }

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from stable.models import (
    HorseCareerRecordAuthorityStatus,
    HorseCompletionRunStatus,
    HorseP0Source,
    HorseP0SourceStatus,
    HorseP0SourceType,
    HorseProfile,
    HorseProfileCandidateStatus,
    HorseProfileCompletionRun,
    HorseProfileDataCandidate,
    HorseRaceRecord,
    HorseRaceResultStatus,
    RacingRegion,
    SourceLanguage,
    TaskExecutionLog,
    TaskStatus,
    TermAlias,
    TermEntry,
    TermTranslationStatus,
    TermType,
)
from stable.services.horse_race_records import (
    canonical_race_key,
    record_idempotency_key,
    valid_http_url,
)
from stable.services.p0_horse_completion_adapters import (
    normalize_p0_horse_race_records,
)
from stable.services.p0_horse_profiles import (
    FULL_PROFILE_COMPLETENESS_POLICY_VERSION,
    REQUIRED_COMPLETION_MODULES,
    apply_reviewed_completion_artifact,
    evaluate_full_profile_completeness,
)


ARTIFACT_SCHEMA = "p0-horse-reviewed-completion-artifact.v1"
MAPPING_SCHEMA = "p0-horse-profile-mapping-decisions.v1"
RESEARCH_SCHEMA = "p0-horse-research.v3"
AUTHORITY_SCHEMA = "p0-horse-us-career-source-authority-review.v1"
RELEASE_MANIFEST_SCHEMA = "p0_horse_production_release_manifest.v1"
RELEASE_MANIFEST_SCHEMA_V2 = "p0_horse_production_release_manifest.v2"
# Phase A is deliberately prepare-only. Phase B must add the exact independently
# approved manifest byte SHA here in a reviewed repository change.
TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256: tuple[str, ...] = (
    "74be2ce42f425bbd24794fb9573ee8b71348f40b0ed6fc0af8599b167c575153",
)
COMMIT_IDENTITY_TABLE_LOCK_MODE = "SHARE ROW EXCLUSIVE"
COMMIT_IDENTITY_TABLE_LOCK_TIMEOUT_MS = 5_000
COMMIT_IDENTITY_TABLE_LOCKS = (
    TermEntry._meta.db_table,
    HorseProfile._meta.db_table,
    TermAlias._meta.db_table,
)
MIN_FORMAL_CONFIDENCE = 90
SHA256_RE = re.compile(r"[0-9a-f]{64}")
IDENTITY_FIELDS = ("horse_name", "sire_name", "dam_name", "birth_year")
PROFILE_FIELDS = (
    "display_name_zh",
    "original_name",
    "english_name",
    "japanese_name",
    "racing_region",
    "country",
    "sex",
    "color",
    "birth_date",
    "owner_name",
    "trainer_name",
    "breeder_name",
    "racing_career_status",
    "records_synced_through",
)
PEDIGREE_FIELDS = (
    "sire_text",
    "dam_text",
    "sire_sire_text",
    "sire_dam_text",
    "dam_sire_text",
    "dam_dam_text",
)
SOURCE_HOST_NAMES = {
    "en.netkeiba.com": "netkeiba_en",
    "www.netkeiba.com": "netkeiba",
    "www.jbis.jp": "jbis",
    "www.hkjc.com": "hkjc",
    "racing.hkjc.com": "hkjc",
    "www.sportinglife.com": "sporting_life",
    "www.racingpost.com": "racing_post",
    "www.horseracingnation.com": "horseracingnation",
    "www.equibase.com": "equibase",
    "equibase.com": "equibase",
    "www.geny.com": "geny",
    "www.france-galop.com": "france_galop",
}


class P0ReviewedArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class FrozenJsonInput:
    path: str
    sha256: str
    payload: dict[str, Any]


def _fail(message: str) -> None:
    raise P0ReviewedArtifactError(message)


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(_read_regular_file_once(path, label="file")).hexdigest()


def _read_regular_file_once(path: str | Path, *, label: str) -> bytes:
    resolved = Path(path)
    try:
        metadata = resolved.lstat()
    except OSError as exc:
        _fail(f"{label} is not readable: {exc}")
    if stat.S_ISLNK(metadata.st_mode):
        _fail(f"{label} must not be a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        _fail(f"{label} must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
        try:
            opened_metadata = os.fstat(descriptor)
            if not stat.S_ISREG(opened_metadata.st_mode):
                _fail(f"{label} must be a regular file")
            if (
                opened_metadata.st_dev != metadata.st_dev
                or opened_metadata.st_ino != metadata.st_ino
            ):
                _fail(f"{label} changed before it could be read")
            chunks = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
        finally:
            os.close(descriptor)
    except OSError as exc:
        _fail(f"{label} is not readable: {exc}")
    return b"".join(chunks)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default))


def _load_json_once(
    path: str | Path,
    *,
    label: str,
    expected_sha256: str | None = None,
) -> FrozenJsonInput:
    data = _read_regular_file_once(path, label=label)
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None:
        if not SHA256_RE.fullmatch(str(expected_sha256 or "")):
            _fail(f"{label} SHA-256 must be lowercase hexadecimal")
        if actual_sha256 != expected_sha256:
            _fail(
                f"{label} SHA-256 mismatch: expected {expected_sha256}, "
                f"got {actual_sha256}"
            )
    try:
        payload = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not readable JSON: {exc}")
    if not isinstance(payload, dict):
        _fail(f"{label} must be a JSON object")
    return FrozenJsonInput(path=str(path), sha256=actual_sha256, payload=payload)


@contextmanager
def _production_release_execution_window(
    *,
    release_manifest_path: str | Path,
    release_manifest_sha256: str,
):
    """Route rolling v2 validation and apply through its batch execution lock."""
    release_input = _load_json_once(
        release_manifest_path,
        label="production release manifest",
        expected_sha256=release_manifest_sha256,
    )
    if release_input.payload.get("schema_version") != RELEASE_MANIFEST_SCHEMA_V2:
        yield release_input
        return
    from stable.services.p0_horse_completion_batch import batch_execution_window

    batch_dir = Path(release_manifest_path).resolve().parent.parent
    with batch_execution_window(batch_dir):
        yield release_input


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", " ", text)


def _identity(identity: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(identity, dict):
        _fail(f"{context} identity must be an object")
    result = {field: identity.get(field) for field in IDENTITY_FIELDS}
    for field in IDENTITY_FIELDS[:3]:
        if not isinstance(result[field], str) or not result[field].strip():
            _fail(f"{context} identity.{field} is required")
        result[field] = result[field].strip()
    year = result["birth_year"]
    if isinstance(year, bool) or not isinstance(year, int) or not 1800 <= year <= timezone.localdate().year:
        _fail(f"{context} identity.birth_year is invalid")
    return result


def deterministic_identity_key(identity: dict[str, Any]) -> str:
    reviewed = _identity(identity, context="deterministic")
    normalized = [
        _normalized(reviewed["horse_name"]),
        _normalized(reviewed["sire_name"]),
        _normalized(reviewed["dam_name"]),
        str(reviewed["birth_year"]),
    ]
    return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()


def _valid_https_url(value: Any, *, allow_fragment: bool = False) -> bool:
    text = str(value or "").strip()
    if not valid_http_url(text):
        return False
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and port is None
        and (allow_fragment or not parsed.fragment)
    )


def _require_url(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not _valid_https_url(text):
        _fail(f"{context} URL must be a credential-free HTTPS URL without explicit port or fragment")
    return text


def _require_evidence_url(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not _valid_https_url(text, allow_fragment=True):
        _fail(
            f"{context} URL must be a credential-free HTTPS URL without explicit port"
        )
    return text


def _validate_urls_recursive(value: Any, *, context: str) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_urls_recursive(item, context=f"{context}[{index}]")
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        key_name = str(key).casefold()
        if key_name.endswith("_url") or key_name == "url":
            if item not in ("", None):
                _require_evidence_url(item, context=f"{context}.{key}")
        elif key_name.endswith("_urls"):
            if not isinstance(item, list):
                _fail(f"{context}.{key} URL collection must be a list")
            for index, url in enumerate(item):
                _require_evidence_url(url, context=f"{context}.{key}[{index}]")
        else:
            _validate_urls_recursive(item, context=f"{context}.{key}")


def _profile_names(profile: HorseProfile) -> list[str]:
    values = [
        profile.display_name_zh,
        profile.original_name,
        profile.english_name,
        profile.japanese_name,
        profile.primary_term.source_ja,
        profile.primary_term.target_zh,
        *(profile.primary_term.aliases_ja or []),
        *(profile.primary_term.aliases_zh or []),
        *profile.primary_term.source_aliases.filter(is_active=True).values_list("text", flat=True),
    ]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = _normalized(text)
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def build_profile_snapshot(profile: HorseProfile) -> dict[str, Any]:
    profile = (
        HorseProfile.objects.select_related("primary_term")
        .prefetch_related("primary_term__source_aliases")
        .get(pk=profile.pk)
    )
    race_record_snapshot = list(
        profile.race_records.order_by("id").values(
            "id",
            "race_name",
            "race_year",
            "race_date",
            "race_date_precision",
            "racecourse",
            "race_number",
            "distance_text",
            "finish_position",
            "result_status",
            "start_status",
            "source_name",
            "source_url",
            "idempotency_key",
            "canonical_race_key",
            "source_refs",
            "raw_payload",
        )
    )
    data = {
        "profile_id": profile.id,
        "primary_term": {
            "id": profile.primary_term_id,
            "source_ja": profile.primary_term.source_ja,
            "target_zh": profile.primary_term.target_zh,
            "translation_status": profile.primary_term.translation_status,
            "racing_region": profile.primary_term.racing_region,
            "aliases_ja": profile.primary_term.aliases_ja,
            "aliases_zh": profile.primary_term.aliases_zh,
            "source_aliases": list(
                profile.primary_term.source_aliases.filter(is_active=True)
                .order_by("source_language", "text")
                .values("source_language", "text")
            ),
        },
        "names": _profile_names(profile),
        "profile_fields": {
            field: _jsonable(getattr(profile, field))
            for field in PROFILE_FIELDS
        },
        "pedigree_fields": {
            field: getattr(profile, field)
            for field in PEDIGREE_FIELDS
        },
        "manual_lock_flags": profile.manual_lock_flags or {},
        "source_refs": profile.source_refs or {},
        "review_status": profile.review_status,
        "completeness_status": profile.completeness_status,
        "career": {
            "career_history_status": profile.career_history_status,
            "official_or_source_start_count": profile.official_or_source_start_count,
            "collected_start_count": profile.collected_start_count,
            "career_history_gap_count": profile.career_history_gap_count,
            "career_record_authority_status": profile.career_record_authority_status,
            "race_record_count": len(race_record_snapshot),
            "race_record_set_sha256": _digest(race_record_snapshot),
        },
    }
    return {
        "schema_version": "p0-horse-profile-snapshot.v1",
        "sha256": _digest(data),
        "data": data,
    }


def _name_match_profiles(horse_name: str) -> list[HorseProfile]:
    candidates = (
        HorseProfile.objects.select_related("primary_term")
        .prefetch_related("primary_term__source_aliases")
        .filter(
            Q(display_name_zh__iexact=horse_name)
            | Q(original_name__iexact=horse_name)
            | Q(english_name__iexact=horse_name)
            | Q(japanese_name__iexact=horse_name)
            | Q(primary_term__source_ja__iexact=horse_name)
            | Q(primary_term__target_zh__iexact=horse_name)
            | Q(primary_term__source_aliases__text__iexact=horse_name)
        )
        .distinct()
        .order_by("id")
    )
    expected = _normalized(horse_name)
    return [
        profile
        for profile in candidates
        if expected in {_normalized(name) for name in _profile_names(profile)}
    ]


def _strong_identity_profiles(identity: dict[str, Any]) -> list[HorseProfile]:
    profiles = (
        HorseProfile.objects.select_related("primary_term")
        .prefetch_related("primary_term__source_aliases")
        .filter(
            birth_date__year=identity["birth_year"],
            sire_text__iexact=identity["sire_name"],
            dam_text__iexact=identity["dam_name"],
        )
        .order_by("id")
    )
    expected_name = _normalized(identity["horse_name"])
    return [
        profile
        for profile in profiles
        if expected_name in {_normalized(name) for name in _profile_names(profile)}
    ]


def build_profile_mapping_snapshot(identity: dict[str, Any]) -> dict[str, Any]:
    reviewed = _identity(identity, context="mapping snapshot")
    name_matches = _name_match_profiles(reviewed["horse_name"])
    strong_matches = _strong_identity_profiles(reviewed)
    data = {
        "identity_key": deterministic_identity_key(reviewed),
        "name_match_profiles": [
            {"profile_id": profile.id, "snapshot_sha256": build_profile_snapshot(profile)["sha256"]}
            for profile in name_matches
        ],
        "strong_identity_profiles": [
            {"profile_id": profile.id, "snapshot_sha256": build_profile_snapshot(profile)["sha256"]}
            for profile in strong_matches
        ],
    }
    return {
        "schema_version": "p0-horse-profile-mapping-snapshot.v1",
        "sha256": _digest(data),
        "data": data,
    }


def _review_metadata(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{context} review metadata is required")
    for field in ("reviewed_by", "approved_at", "decision_source_reference"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            _fail(f"{context}.{field} is required")
    try:
        approved_at = datetime.fromisoformat(value["approved_at"].replace("Z", "+00:00"))
    except ValueError:
        _fail(f"{context}.approved_at is invalid")
    if approved_at.utcoffset() is None:
        _fail(f"{context}.approved_at must include timezone")
    return value


def _validate_reviewer(reviewer_id: Any):
    if isinstance(reviewer_id, bool) or not isinstance(reviewer_id, int):
        _fail("reviewer_id is required")
    reviewer = get_user_model().objects.filter(pk=reviewer_id).first()
    if reviewer is None or not reviewer.is_active or not reviewer.is_superuser:
        _fail("reviewer must exist and be an active superuser")
    return reviewer


def _validate_mapping_reviewer(reviewer_id: Any):
    if isinstance(reviewer_id, bool) or not isinstance(reviewer_id, int):
        _fail("mapping reviewer_id is required")
    reviewer = get_user_model().objects.filter(pk=reviewer_id).first()
    if (
        reviewer is None
        or not reviewer.is_active
        or not (reviewer.is_staff or reviewer.is_superuser)
    ):
        _fail("mapping reviewer must exist and be active staff or superuser")
    return reviewer


def _record_source_name(record: dict[str, Any], horse: dict[str, Any]) -> str:
    explicit = str(record.get("source_name") or "").strip()
    if explicit:
        return explicit
    source_url = str(record.get("source_url") or "").strip()
    host_name = SOURCE_HOST_NAMES.get((urlsplit(source_url).hostname or "").lower())
    return host_name or str((horse.get("source") or {}).get("name") or "").strip()


def _reviewed_race_name(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    explicit = str(record.get("race_name") or "").strip()
    if explicit:
        return explicit, {}
    source_url = str(record.get("source_url") or "").strip()
    parsed = urlsplit(source_url)
    if (parsed.hostname or "").lower() not in {"racing.hkjc.com", "www.hkjc.com"}:
        _fail("race record without a race name is only supported for reviewed HKJC local result URLs")
    query = parse_qs(parsed.query, keep_blank_values=False)
    race_date = str(record.get("race_date") or "").strip()
    racecourse = str((query.get("Racecourse") or query.get("racecourse") or [""])[0]).strip()
    race_number = str((query.get("RaceNo") or query.get("raceno") or [""])[0]).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", race_date):
        _fail("reviewed HKJC local result label requires an exact date")
    if racecourse and race_number:
        label = f"HKJC local result {race_date} {racecourse} R{race_number}"
    else:
        source_record_key = str(record.get("source_record_key") or "").strip()
        record_racecourse = str(record.get("racecourse") or "").strip()
        if not source_record_key or not record_racecourse or "horseid" not in query:
            _fail(
                "reviewed HKJC horse record label requires racecourse, "
                "source_record_key and horseid evidence"
            )
        label = (
            f"HKJC horse record {race_date} {record_racecourse} "
            f"{source_record_key}"
        )
    return label, {
        "derived_race_name": {
            "value": label,
            "conversion_rule": "derived_hkjc_local_result_label_v1",
            "semantics": "local snapshot label; not an official race title",
            "source_url": source_url,
        }
    }


def _stable_record_key(record: dict[str, Any]) -> str:
    return _digest(
        {
            key: record.get(key, "")
            for key in (
                "external_result_id",
                "external_race_id",
                "race_date",
                "race_name",
                "racecourse",
                "race_number",
                "distance_text",
                "finish_position",
                "result_status",
                "start_status",
                "source_name",
                "source_url",
            )
        }
    )


def _canonical_batch_race_key(record: dict[str, Any]) -> str:
    race_date = str(record.get("race_date") or "")
    racecourse = _normalized(record.get("racecourse"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", race_date) or not racecourse:
        return ""
    race_name = _normalized(record.get("race_name"))
    if race_name:
        raw = ("race-facts", race_date, racecourse, race_name)
    else:
        source_record_key = _normalized(record.get("source_record_key"))
        if not source_record_key:
            return ""
        raw = ("source-record", race_date, racecourse, source_record_key)
    return hashlib.sha256("|".join(raw).encode("utf-8")).hexdigest()


def _validate_unique_records(records: list[dict[str, Any]], *, context: str) -> None:
    stable_keys: set[str] = set()
    source_ids: set[tuple[str, str, str]] = set()
    canonical_keys: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            _fail(f"{context} race record {index} is invalid")
        _require_url(record.get("source_url"), context=f"{context} race record {index}")
        _validate_urls_recursive(
            record.get("source_refs") or {},
            context=f"{context} race record {index}.source_refs",
        )
        if not str(record.get("source_name") or "").strip():
            _fail(f"{context} race record {index} source_name is required")
        stable_key = _stable_record_key(record)
        if stable_key in stable_keys:
            _fail(f"{context} duplicate race stable record key")
        stable_keys.add(stable_key)
        source = _normalized(record.get("source_name"))
        for field in ("external_result_id", "external_race_id"):
            external_id = str(record.get(field) or "").strip()
            if not external_id:
                continue
            source_key = (source, field, external_id)
            if source_key in source_ids:
                _fail(f"{context} duplicate race source-bound ID")
            source_ids.add(source_key)
        canonical_key = _canonical_batch_race_key(record)
        if not canonical_key:
            _fail(f"{context} race record {index} lacks an explicit canonical race key")
        if canonical_key in canonical_keys:
            _fail(f"{context} duplicate race canonical key")
        canonical_keys.add(canonical_key)


def _normalized_records(horse: dict[str, Any], *, context: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    career = horse.get("career")
    if not isinstance(career, dict) or not isinstance(career.get("records"), list):
        _fail(f"{context} career.records is required")
    enriched = []
    for record in career["records"]:
        if not isinstance(record, dict):
            _fail(f"{context} contains an invalid race record")
        item = deepcopy(record)
        item["source_name"] = _record_source_name(item, horse)
        item["source_url"] = _require_url(item.get("source_url"), context=f"{context} race record")
        race_name, derivation = _reviewed_race_name(item)
        item["race_name"] = race_name
        if (
            _normalized(item["source_name"]) == "hkjc"
            and str(item.get("source_record_key") or "").strip()
        ):
            raw_payload = dict(item.get("raw_payload") or {})
            raw_payload["reviewed_source_identity"] = {
                "legacy_external_race_id": str(
                    item.get("external_race_id") or ""
                ),
                "external_result_id": str(item["source_record_key"]),
                "conversion_rule": "hkjc_source_record_key_identity_v1",
            }
            item["raw_payload"] = raw_payload
            item["external_result_id"] = str(item["source_record_key"])
            item["external_race_id"] = ""
        if derivation:
            raw_payload = dict(item.get("raw_payload") or {})
            raw_payload.update(derivation)
            item["raw_payload"] = raw_payload
        enriched.append(item)
    normalized = normalize_p0_horse_race_records(
        enriched,
        source_start_count=career.get("official_or_source_start_count"),
        official_start_count_source=str(career.get("official_start_count_source") or ""),
        official_start_count_source_url=str(career.get("official_start_count_source_url") or ""),
        official_start_count_verified_at=str(career.get("official_start_count_verified_at") or ""),
        record_authority_status=str(career.get("record_authority_status") or ""),
    )
    records = normalized["race_records"]
    _validate_unique_records(records, context=context)
    career_history = normalized["career_history"]
    if career.get("career_collection_status") != "complete" or career_history["status"] != "complete":
        _fail(f"{context} career is not strict complete")
    if career_history["record_authority_status"] != HorseCareerRecordAuthorityStatus.SOURCE_RECORDS_VERIFIED:
        _fail(f"{context} career authority is not source_records_verified")
    if len(records) != len(career["records"]):
        _fail(f"{context} race record normalization changed the reviewed record count")
    return records, career_history


def _validate_authority_chain(
    research: dict[str, Any],
    authority: dict[str, Any],
    *,
    authority_sha256: str,
) -> None:
    if authority.get("schema_version") != AUTHORITY_SCHEMA:
        _fail("authority manifest schema is invalid")
    if authority.get("review_status") != "approved":
        _fail("authority manifest is not approved")
    _review_metadata(authority, context="authority manifest")
    application = research.get("career_authority_review_application")
    if not isinstance(application, dict):
        _fail("research v3 authority application is missing")
    if application.get("review_artifact_sha256") != authority_sha256:
        _fail("research v3 authority manifest SHA chain mismatch")
    input_binding = authority.get("input")
    if not isinstance(input_binding, dict) or input_binding.get("sha256") != application.get("input_sha256"):
        _fail("research v3 authority input SHA chain mismatch")
    research_us = {
        deterministic_identity_key(_identity(horse.get("identity"), context="research US horse")): horse
        for horse in research.get("horses", [])
        if horse.get("region") == "united_states"
    }
    authority_rows = authority.get("horses")
    if not isinstance(authority_rows, list):
        _fail("authority manifest horses are invalid")
    authority_us: dict[str, dict[str, Any]] = {}
    for row in authority_rows:
        if not isinstance(row, dict):
            _fail("authority manifest horse row is invalid")
        key = deterministic_identity_key(_identity(row.get("identity"), context="authority horse"))
        if key in authority_us:
            _fail("authority manifest contains duplicate identity")
        authority_us[key] = row
    if set(research_us) != set(authority_us):
        _fail("authority manifest does not cover the exact research US identities")
    if application.get("approved_horse_count") != len(research_us):
        _fail("authority application approved horse count mismatch")
    for key, horse in research_us.items():
        if authority_us[key].get("record_count") != len((horse.get("career") or {}).get("records") or []):
            _fail("authority manifest record count drift")


def validate_frozen_p0_research_inputs(
    *,
    research_v3_path: str | Path,
    authority_manifest_path: str | Path,
    authority_manifest_sha256: str,
) -> dict[str, int]:
    research_input = _load_json_once(research_v3_path, label="research v3")
    authority_input = _load_json_once(
        authority_manifest_path,
        label="authority manifest",
        expected_sha256=authority_manifest_sha256,
    )
    return _validate_frozen_p0_research_payloads(
        research_input.payload,
        authority_input.payload,
        authority_sha256=authority_input.sha256,
    )


def _validate_frozen_p0_research_payloads(
    research: dict[str, Any],
    authority: dict[str, Any],
    *,
    authority_sha256: str,
) -> dict[str, int]:
    if research.get("schema_version") != RESEARCH_SCHEMA:
        _fail("research v3 schema is invalid")
    horses = research.get("horses")
    if not isinstance(horses, list) or not horses:
        _fail("research v3 horses are required")
    _validate_authority_chain(
        research,
        authority,
        authority_sha256=authority_sha256,
    )
    identity_keys: set[str] = set()
    record_count = actual_start_count = nonstarter_count = 0
    for index, horse in enumerate(horses):
        if not isinstance(horse, dict):
            _fail(f"research horse row {index} is invalid")
        identity = _identity(horse.get("identity"), context=f"research horse {index}")
        horse["identity"] = identity
        identity_key = deterministic_identity_key(identity)
        if identity_key in identity_keys:
            _fail("research contains duplicate identity")
        identity_keys.add(identity_key)
        records, _ = _normalized_records(horse, context=identity["horse_name"])
        record_count += len(records)
        actual_start_count += sum(
            record.get("start_status") == "started" for record in records
        )
        nonstarter_count += sum(
            record.get("start_status") == "did_not_start"
            for record in records
        )
    return {
        "horse_count": len(horses),
        "race_record_count": record_count,
        "actual_start_count": actual_start_count,
        "nonstarter_count": nonstarter_count,
    }


def _incoming_profile_values(horse: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    identity = horse["identity"]
    basic = horse.get("basic_profile")
    if not isinstance(basic, dict):
        _fail(f"{identity['horse_name']} basic_profile is required")
    completion = decision.get("completion_decision")
    _review_metadata(completion, context=f"{identity['horse_name']} completion decision")
    racing_status = completion.get("racing_career_status")
    if racing_status not in {"active", "retired"}:
        _fail(f"{identity['horse_name']} completion decision racing_career_status is invalid")
    synced_through = str(completion.get("records_synced_through") or "")
    try:
        date.fromisoformat(synced_through)
    except ValueError:
        _fail(f"{identity['horse_name']} completion decision records_synced_through is invalid")
    values = {
        "original_name": identity["horse_name"],
        "english_name": identity["horse_name"],
        "country": basic.get("country"),
        "sex": basic.get("sex"),
        "color": basic.get("color"),
        "birth_date": basic.get("birth_date"),
        "owner_name": basic.get("owner_name"),
        "trainer_name": basic.get("trainer_name"),
        "breeder_name": basic.get("breeder_name"),
        "racing_career_status": racing_status,
        "records_synced_through": synced_through,
    }
    for field in ("country", "sex", "color", "birth_date", "owner_name", "trainer_name", "breeder_name"):
        if values[field] in ("", None):
            _fail(f"{identity['horse_name']} basic_profile.{field} is required")
    if int(str(values["birth_date"])[:4]) != identity["birth_year"]:
        _fail(f"{identity['horse_name']} birth year conflicts with basic profile")
    return values


def _incoming_pedigree_values(horse: dict[str, Any]) -> dict[str, Any]:
    identity = horse["identity"]
    pedigree = horse.get("pedigree")
    if not isinstance(pedigree, dict):
        _fail(f"{identity['horse_name']} pedigree is required")
    result = {
        "sire_text": pedigree.get("sire"),
        "dam_text": pedigree.get("dam"),
        "sire_sire_text": pedigree.get("sire_sire"),
        "sire_dam_text": pedigree.get("sire_dam"),
        "dam_sire_text": pedigree.get("dam_sire"),
        "dam_dam_text": pedigree.get("dam_dam"),
    }
    if any(not isinstance(value, str) or not value.strip() for value in result.values()):
        _fail(f"{identity['horse_name']} pedigree is incomplete")
    if _normalized(result["sire_text"]) != _normalized(identity["sire_name"]) or _normalized(
        result["dam_text"]
    ) != _normalized(identity["dam_name"]):
        _fail(f"{identity['horse_name']} pedigree conflicts with identity")
    return result


def _validate_module_reviews(decision: dict[str, Any], *, horse_name: str) -> dict[str, Any]:
    reviews = decision.get("module_reviews")
    if not isinstance(reviews, dict):
        _fail(f"{horse_name} module reviews are required")
    normalized: dict[str, Any] = {}
    for module in REQUIRED_COMPLETION_MODULES:
        review = reviews.get(module)
        _review_metadata(review, context=f"{horse_name} module {module}")
        if review.get("status") != "approved":
            _fail(f"{horse_name} module {module} must be approved")
        confidence = review.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, int) or confidence < MIN_FORMAL_CONFIDENCE:
            _fail(f"{horse_name} module {module} confidence must be at least {MIN_FORMAL_CONFIDENCE}")
        if review.get("conflict") or review.get("failure_reason"):
            _fail(f"{horse_name} module {module} contains a conflict")
        normalized[module] = review
    return normalized


def _validate_mapping_decision(
    horse: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    identity = horse["identity"]
    horse_name = identity["horse_name"]
    if decision.get("identity") != identity:
        _fail(f"{horse_name} mapping identity mismatch")
    _review_metadata(decision.get("decision_evidence"), context=f"{horse_name} mapping decision")
    current_mapping_snapshot = build_profile_mapping_snapshot(identity)
    if decision.get("database_mapping_snapshot") != current_mapping_snapshot:
        _fail(f"{horse_name} database mapping snapshot drift")
    decision_name = decision.get("decision")
    if decision_name not in {"bind_existing", "create_new"}:
        _fail(f"{horse_name} mapping decision must be bind_existing or create_new")
    result = {
        "decision": decision_name,
        "database_mapping_snapshot": current_mapping_snapshot,
        "decision_evidence": decision["decision_evidence"],
        "module_reviews": _validate_module_reviews(decision, horse_name=horse_name),
        "completion_decision": decision.get("completion_decision"),
    }
    profile_values = _incoming_profile_values(horse, decision)
    pedigree_values = _incoming_pedigree_values(horse)
    if decision_name == "create_new":
        strong_ids = [
            row["profile_id"]
            for row in current_mapping_snapshot["data"]["strong_identity_profiles"]
        ]
        if strong_ids:
            _fail(f"{horse_name} create_new is blocked by an existing strong identity")
        return result

    profile_id = decision.get("profile_id")
    if isinstance(profile_id, bool) or not isinstance(profile_id, int):
        _fail(f"{horse_name} bind_existing profile_id is required")
    profile = HorseProfile.objects.filter(pk=profile_id).first()
    if profile is None:
        _fail(f"{horse_name} bind_existing profile_id does not exist")
    current_profile_snapshot = build_profile_snapshot(profile)
    if decision.get("profile_snapshot") != current_profile_snapshot:
        _fail(f"{horse_name} profile snapshot drift")
    name_evidence = str(decision.get("name_evidence") or "").strip()
    if _normalized(name_evidence) != _normalized(horse_name) or _normalized(name_evidence) not in {
        _normalized(name) for name in _profile_names(profile)
    }:
        _fail(f"{horse_name} bind_existing name/alias evidence is invalid")
    name_match_ids = {
        row["profile_id"]
        for row in current_mapping_snapshot["data"]["name_match_profiles"]
    }
    if profile_id not in name_match_ids:
        _fail(f"{horse_name} selected profile is not in the name/alias snapshot")
    rejected_ids = decision.get("rejected_profile_ids") or []
    if set(rejected_ids) != name_match_ids - {profile_id}:
        _fail(f"{horse_name} rejected profile IDs must explicitly cover every other name match")
    if rejected_ids and not str(decision.get("rejection_reason") or "").strip():
        _fail(f"{horse_name} rejected profiles require a reason")
    strong_ids = {
        row["profile_id"]
        for row in current_mapping_snapshot["data"]["strong_identity_profiles"]
    }
    if strong_ids and strong_ids != {profile_id}:
        _fail(f"{horse_name} duplicate strong identity conflict")
    locks = profile.manual_lock_flags or {}
    for field, incoming in {**profile_values, **pedigree_values}.items():
        if not locks.get(field):
            continue
        current = getattr(profile, field)
        if field in {"birth_date", "records_synced_through"}:
            current = current.isoformat() if current else None
        if current != incoming:
            _fail(f"{horse_name} manual lock conflicts with reviewed payload: {field}")
    result.update(
        {
            "profile_id": profile_id,
            "profile_snapshot": current_profile_snapshot,
            "name_evidence": name_evidence,
            "rejected_profile_ids": rejected_ids,
            "rejection_reason": str(decision.get("rejection_reason") or ""),
        }
    )
    return result


def _major_wins(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "external_result_id": record.get("external_result_id", ""),
            "external_race_id": record.get("external_race_id", ""),
            "race_date": record.get("race_date"),
            "race_name": record.get("race_name"),
            "source_url": record.get("source_url"),
        }
        for record in records
        if record.get("result_status") == HorseRaceResultStatus.WON
        or record.get("is_major_win")
    ]


def _artifact_row(
    horse: dict[str, Any],
    decision: dict[str, Any],
    *,
    research_v3_sha256: str,
    authority_manifest_sha256: str,
    mapping_decisions_sha256: str,
) -> dict[str, Any]:
    identity = horse["identity"]
    source = horse.get("source")
    if not isinstance(source, dict):
        _fail(f"{identity['horse_name']} source is required")
    source_url = _require_url(source.get("url"), context=f"{identity['horse_name']} source")
    for evidence_key in (
        "candidate",
        "source",
        "source_evidence",
        "basic_profile_field_evidence",
        "pedigree_field_evidence",
    ):
        _validate_urls_recursive(
            horse.get(evidence_key) or {},
            context=f"{identity['horse_name']}.{evidence_key}",
        )
    for evidence in horse.get("source_evidence") or []:
        if isinstance(evidence, dict) and evidence.get("source_url"):
            _require_url(evidence["source_url"], context=f"{identity['horse_name']} source evidence")
    records, career_history = _normalized_records(
        horse,
        context=identity["horse_name"],
    )
    profile_payload = _incoming_profile_values(horse, decision)
    if decision["decision"] == "create_new":
        profile_payload["racing_region"] = horse.get("region")
    pedigree_payload = _incoming_pedigree_values(horse)
    aliases = [
        item
        for item in horse.get("aliases") or []
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    if not aliases:
        aliases = [{"name": identity["horse_name"], "language": "en", "is_original": True}]
    career_history["gap_reasons"] = []
    career_history["source_refs"] = {
        "research_v3_sha256": research_v3_sha256,
        "authority_manifest_sha256": authority_manifest_sha256,
        "identity_key": deterministic_identity_key(identity),
    }
    candidate_evidence = dict(horse.get("candidate") or {})
    reviewed_region = horse.get("region")
    candidate_region = candidate_evidence.get("sample_region")
    if candidate_region and candidate_region != reviewed_region:
        _fail(f"{identity['horse_name']} candidate sample region conflicts with research region")
    candidate_evidence["sample_region"] = reviewed_region
    return {
        "identity": identity,
        "deterministic_identity_key": deterministic_identity_key(identity),
        "resolution": decision,
        "reviewed": True,
        "source_name": "reviewed_p0_horse_completion_v3",
        "source_url": source_url,
        "profile_payload": profile_payload,
        "pedigree_payload": pedigree_payload,
        "race_records_payload": records,
        "career_history": career_history,
        "major_wins_payload": _major_wins(records),
        "aliases_payload": aliases,
        "module_reviews": decision["module_reviews"],
        "evidence": {
            "research_v3_sha256": research_v3_sha256,
            "authority_manifest_sha256": authority_manifest_sha256,
            "mapping_decisions_sha256": mapping_decisions_sha256,
            "candidate": candidate_evidence,
            "source": source,
            "source_evidence": horse.get("source_evidence") or [],
            "basic_profile_field_evidence": horse.get(
                "basic_profile_field_evidence"
            )
            or [],
            "pedigree_field_evidence": horse.get("pedigree_field_evidence")
            or [],
            "origin": "reviewed major-race P0 candidate batch",
        },
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    records = [record for row in rows for record in row["race_records_payload"]]
    return {
        "horse_count": len(rows),
        "bind_existing_count": sum(row["resolution"]["decision"] == "bind_existing" for row in rows),
        "create_new_count": sum(row["resolution"]["decision"] == "create_new" for row in rows),
        "race_record_count": len(records),
        "actual_start_count": sum(record.get("start_status") == "started" for record in records),
        "nonstarter_count": sum(record.get("start_status") == "did_not_start" for record in records),
        "unconfirmed_count": sum(record.get("start_status") == "unconfirmed" for record in records),
        "p0_source_count": len(rows),
        "required_module_count": len(rows) * len(REQUIRED_COMPLETION_MODULES),
    }


def prepare_reviewed_p0_completion_artifact(
    *,
    research_v3_path: str | Path,
    authority_manifest_path: str | Path,
    authority_manifest_sha256: str,
    profile_mapping_decisions_path: str | Path | None,
    reviewer_id: int,
    prepared_by: str = "codex",
    prepared_at: str | None = None,
) -> dict[str, Any]:
    if profile_mapping_decisions_path is None:
        _fail("profile mapping decisions artifact is required")
    reviewer = _validate_reviewer(reviewer_id)
    research_input = _load_json_once(research_v3_path, label="research v3")
    authority_input = _load_json_once(
        authority_manifest_path,
        label="authority manifest",
        expected_sha256=authority_manifest_sha256,
    )
    mapping_input = _load_json_once(
        profile_mapping_decisions_path,
        label="profile mapping decisions",
    )
    research = research_input.payload
    authority = authority_input.payload
    mapping = mapping_input.payload
    _validate_frozen_p0_research_payloads(
        research,
        authority,
        authority_sha256=authority_input.sha256,
    )
    horses = research["horses"]
    research_sha = research_input.sha256
    authority_sha = authority_input.sha256
    _validate_authority_chain(research, authority, authority_sha256=authority_sha)

    mapping_sha = mapping_input.sha256
    if mapping.get("schema_version") != MAPPING_SCHEMA or mapping.get("review_status") != "approved":
        _fail("profile mapping decisions must be an independently approved mapping artifact")
    _review_metadata(mapping, context="profile mapping decisions")
    mapping_reviewer = _validate_mapping_reviewer(mapping.get("reviewer_id"))
    if mapping.get("research_v3_sha256") != research_sha:
        _fail("profile mapping decisions research v3 SHA binding mismatch")
    mapping_rows = mapping.get("rows")
    if not isinstance(mapping_rows, list):
        _fail("profile mapping decisions rows are invalid")

    research_by_key: dict[str, dict[str, Any]] = {}
    for horse in horses:
        if not isinstance(horse, dict):
            _fail("research horse row is invalid")
        identity = _identity(horse.get("identity"), context="research horse")
        horse["identity"] = identity
        key = deterministic_identity_key(identity)
        if key in research_by_key:
            _fail("research contains duplicate identity")
        research_by_key[key] = horse
    mapping_by_key: dict[str, dict[str, Any]] = {}
    for row in mapping_rows:
        if not isinstance(row, dict):
            _fail("profile mapping decision row is invalid")
        identity = _identity(row.get("identity"), context="mapping row")
        row["identity"] = identity
        key = deterministic_identity_key(identity)
        if key in mapping_by_key:
            _fail("profile mapping decisions contain duplicate identity")
        mapping_by_key[key] = row
    if set(research_by_key) != set(mapping_by_key):
        _fail("profile mapping decisions do not cover the exact research identities")
    production_snapshot_payload = [
        {
            "identity_key": key,
            "database_mapping_snapshot": mapping_by_key[key].get(
                "database_mapping_snapshot"
            ),
        }
        for key in sorted(mapping_by_key)
    ]
    if mapping.get("production_snapshot_sha256") != _digest(
        production_snapshot_payload
    ):
        _fail("profile mapping decisions production snapshot SHA binding mismatch")

    reviewed_rows = []
    bound_profile_ids: set[int] = set()
    for key, horse in research_by_key.items():
        decision = _validate_mapping_decision(horse, mapping_by_key[key])
        if decision.get("profile_id") in bound_profile_ids:
            _fail("one profile_id cannot be bound to multiple reviewed identities")
        if decision.get("profile_id"):
            bound_profile_ids.add(decision["profile_id"])
        reviewed_rows.append(
            _artifact_row(
                horse,
                decision,
                research_v3_sha256=research_sha,
                authority_manifest_sha256=authority_sha,
                mapping_decisions_sha256=mapping_sha,
            )
        )
    summary = _summary(reviewed_rows)
    artifact = {
        "schema_version": ARTIFACT_SCHEMA,
        "completion_policy_version": FULL_PROFILE_COMPLETENESS_POLICY_VERSION,
        "commit_artifact_compatible": True,
        "reviewed": True,
        "release_status": "candidate_pending_independent_release",
        "reviewer_id": reviewer.id,
        "reviewer_snapshot": {
            "id": reviewer.id,
            "username": reviewer.get_username(),
            "is_active": reviewer.is_active,
            "is_superuser": reviewer.is_superuser,
        },
        "mapping_reviewer_snapshot": {
            "id": mapping_reviewer.id,
            "username": mapping_reviewer.get_username(),
            "is_active": mapping_reviewer.is_active,
            "is_staff": mapping_reviewer.is_staff,
            "is_superuser": mapping_reviewer.is_superuser,
        },
        "prepared_by": str(prepared_by or "codex"),
        "prepared_at": str(prepared_at or timezone.now().isoformat()),
        "production_snapshot_sha256": mapping["production_snapshot_sha256"],
        "inputs": {
            "research_v3": {"path": str(research_v3_path), "sha256": research_sha},
            "authority_manifest": {
                "path": str(authority_manifest_path),
                "sha256": authority_sha,
            },
            "profile_mapping_decisions": {
                "path": str(profile_mapping_decisions_path),
                "sha256": mapping_sha,
            },
        },
        "summary": summary,
        "expected_actions": {},
        "rows": reviewed_rows,
    }
    simulation = _simulate(artifact, artifact_sha256="0" * 64)
    artifact["expected_actions"] = {
        "profile_creates": simulation["planned_profile_creates"],
        "profile_updates": simulation["planned_profile_updates"],
        "race_record_creates": simulation["planned_race_record_creates"],
        "race_record_updates": simulation["planned_race_record_updates"],
        "existing_race_records": simulation["existing_race_records"],
        "p0_source_upserts": simulation["planned_p0_source_upserts"],
        "module_audits": simulation["planned_module_audits"],
    }
    return artifact


def _load_artifact(path: str | Path, expected_sha256: str) -> tuple[dict[str, Any], str]:
    artifact_input = _load_json_once(
        path,
        label="reviewed artifact",
        expected_sha256=expected_sha256,
    )
    actual_sha = artifact_input.sha256
    artifact = artifact_input.payload
    if artifact.get("schema_version") != ARTIFACT_SCHEMA:
        _fail("reviewed artifact schema is invalid")
    if artifact.get("commit_artifact_compatible") is not True or artifact.get("reviewed") is not True:
        _fail("reviewed artifact is not commit compatible")
    if artifact.get("release_status") != "candidate_pending_independent_release":
        _fail("reviewed artifact is not a pending independent-release candidate")
    reviewer = _validate_reviewer(artifact.get("reviewer_id"))
    reviewer_snapshot = artifact.get("reviewer_snapshot")
    if reviewer_snapshot != {
        "id": reviewer.id,
        "username": reviewer.get_username(),
        "is_active": reviewer.is_active,
        "is_superuser": reviewer.is_superuser,
    }:
        _fail("reviewer snapshot drift")
    rows = artifact.get("rows")
    if not isinstance(rows, list) or not rows:
        _fail("reviewed artifact rows are required")
    if artifact.get("summary") != _summary(rows):
        _fail("reviewed artifact summary drift")
    inputs = artifact.get("inputs")
    if not isinstance(inputs, dict):
        _fail("reviewed artifact input bindings are missing")
    loaded_inputs: dict[str, FrozenJsonInput] = {}
    for key in (
        "research_v3",
        "authority_manifest",
        "profile_mapping_decisions",
    ):
        binding = inputs.get(key)
        if not isinstance(binding, dict):
            _fail(f"reviewed artifact {key} binding is missing")
        loaded_inputs[key] = _load_json_once(
            binding.get("path"),
            label=f"reviewed artifact {key}",
            expected_sha256=str(binding.get("sha256") or ""),
        )
    _validate_frozen_p0_research_payloads(
        loaded_inputs["research_v3"].payload,
        loaded_inputs["authority_manifest"].payload,
        authority_sha256=loaded_inputs["authority_manifest"].sha256,
    )
    mapping = loaded_inputs["profile_mapping_decisions"].payload
    if mapping.get("schema_version") != MAPPING_SCHEMA:
        _fail("reviewed artifact profile mapping decisions schema drift")
    mapping_reviewer = _validate_mapping_reviewer(mapping.get("reviewer_id"))
    if artifact.get("mapping_reviewer_snapshot") != {
        "id": mapping_reviewer.id,
        "username": mapping_reviewer.get_username(),
        "is_active": mapping_reviewer.is_active,
        "is_staff": mapping_reviewer.is_staff,
        "is_superuser": mapping_reviewer.is_superuser,
    }:
        _fail("mapping reviewer snapshot drift")
    if mapping.get("research_v3_sha256") != loaded_inputs["research_v3"].sha256:
        _fail("reviewed artifact profile mapping decisions research SHA drift")
    if mapping.get("production_snapshot_sha256") != artifact.get(
        "production_snapshot_sha256"
    ):
        _fail("reviewed artifact production snapshot SHA drift")
    return artifact, actual_sha


def _validate_rolling_release_ledger(
    release: dict[str, Any],
    release_sha256: str,
    *,
    release_manifest_path: str | Path,
    candidate: dict[str, Any] | None = None,
    candidate_sha256: str = "",
    artifact_sha256: str = "",
) -> None:
    """Rolling-batch approval channel: append-only ledger binding.

    The repository allowlist stays reserved for the first 50-horse batch.
    Rolling batches instead bind the release manifest SHA to an entry in the
    batch append-only approvals ledger recorded at approval time.
    """
    ledger_value = str(release.get("approvals_ledger_path") or "").strip()
    if not ledger_value:
        _fail(
            "production release manifest SHA is not in the repository trusted "
            "allowlist and no approvals ledger is declared"
        )
    ledger_path = Path(ledger_value)
    if ledger_path.is_symlink() or not ledger_path.is_file():
        _fail("production release approvals ledger is not a regular file")
    if ledger_path.name != "approvals_ledger.jsonl":
        _fail("production release approvals ledger filename is invalid")
    release_dir = Path(release_manifest_path).resolve().parent
    if ledger_path.resolve().parent != release_dir.parent:
        _fail(
            "production release approvals ledger must live in the batch state "
            "directory of the release manifest"
        )
    from stable.services.p0_horse_completion_batch import (
        P0HorseBatchError,
        read_approvals_ledger,
    )

    try:
        entries = read_approvals_ledger(ledger_path.parent)
    except P0HorseBatchError as exc:
        _fail(f"production release approvals ledger is invalid: {exc}")
    approval_index = None
    for index, entry in enumerate(entries):
        if (
            entry.get("event") == "release_approved"
            and entry.get("release_manifest_sha256") == release_sha256
        ):
            approval_index = index
            break
    if approval_index is None:
        _fail(
            "production release manifest SHA has no release_approved entry in the "
            "batch approvals ledger"
        )
    if candidate is None:
        return
    prepared_index = next(
        (
            index
            for index, entry in enumerate(entries[:approval_index])
            if entry.get("event") == "release_candidate_prepared"
            and entry.get("batch_id") == candidate.get("batch_id")
            and entry.get("region") == candidate.get("region")
            and entry.get("release_candidate_sha256") == candidate_sha256
            and entry.get("artifact_sha256") == artifact_sha256
        ),
        None,
    )
    if prepared_index is None:
        _fail(
            "production release candidate has no preceding "
            "release_candidate_prepared evidence"
        )
    for entry in entries[approval_index + 1 :]:
        if entry.get("event") != "release_superseded":
            continue
        if (
            entry.get("old_release_manifest_sha256") == release_sha256
            or entry.get("old_release_candidate_sha256")
            == candidate_sha256
        ):
            _fail("production release manifest was superseded")


def _validate_release_candidate_scope(scope: Any) -> None:
    if not isinstance(scope, dict) or set(scope) != {
        "existing_profiles",
        "create_new_identities",
    }:
        _fail("production release candidate publish scope structure is invalid")
    existing = scope["existing_profiles"]
    create_new = scope["create_new_identities"]
    if not isinstance(existing, list) or not isinstance(create_new, list):
        _fail("production release candidate publish scope collections are invalid")
    existing_dispositions = {
        "attempt_publish_after_commit",
        "skip_already_published",
        "block_hidden",
        "block_manual_lock",
    }
    for item in existing:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "profile_id",
                "review_status",
                "hidden",
                "manual_lock",
                "disposition",
            }
            or isinstance(item["profile_id"], bool)
            or not isinstance(item["profile_id"], int)
            or not isinstance(item["hidden"], bool)
            or not isinstance(item["manual_lock"], bool)
            or item["disposition"] not in existing_dispositions
        ):
            _fail("production release candidate existing-profile scope is invalid")
    for item in create_new:
        if (
            not isinstance(item, dict)
            or set(item)
            != {"deterministic_identity_key", "horse_name", "disposition"}
            or not str(item["deterministic_identity_key"] or "").strip()
            or not str(item["horse_name"] or "").strip()
            or item["disposition"] != "attempt_publish_after_commit"
        ):
            _fail("production release candidate new-identity scope is invalid")


def _artifact_has_exact_committed_run(
    artifact_path: str | Path,
    artifact_sha256: str,
) -> bool:
    runs = HorseProfileCompletionRun.objects.filter(
        status=HorseCompletionRunStatus.COMMITTED,
        artifact_path=str(artifact_path),
    ).only("parameters")
    return any(
        (run.parameters or {}).get("artifact_sha256") == artifact_sha256
        for run in runs
    )


def _load_and_validate_release_candidate(
    *,
    release: dict[str, Any],
    release_manifest_path: str | Path,
    candidate_sha256: str,
    artifact: dict[str, Any],
    artifact_path: str | Path,
    artifact_sha256: str,
    expected_release_bindings: dict[str, str],
) -> dict[str, Any]:
    from stable.services.p0_horse_completion_batch import (
        BatchRunState,
        P0_HORSE_BATCH_SCHEMA_VERSION,
        P0HorseBatchError,
        _manifest_sha256,
    )

    release_dir = Path(release_manifest_path).resolve().parent
    region = str(release.get("region") or "").strip()
    if not region:
        _fail("production release manifest region is missing")
    candidate_path = release_dir / (
        f"release_candidate_{region}_{candidate_sha256}.json"
    )
    candidate_input = _load_json_once(
        candidate_path,
        label="production release candidate",
        expected_sha256=candidate_sha256,
    )
    candidate = candidate_input.payload
    batch_dir = release_dir.parent
    batch_manifest = _load_json_once(
        batch_dir / "batch_manifest.json",
        label="production release batch manifest",
    ).payload
    if (
        batch_manifest.get("schema_version")
        != P0_HORSE_BATCH_SCHEMA_VERSION
        or batch_manifest.get("batch_sha256")
        != _manifest_sha256(batch_manifest)
    ):
        _fail("production release batch manifest schema or internal SHA is invalid")
    batch_status = batch_manifest.get("status")
    if batch_status == "abandoned":
        _fail("production release batch manifest is abandoned")
    if batch_status not in {"approved", "committed"}:
        _fail("production release batch manifest status is invalid")
    candidate_bindings = candidate.get("bindings")
    expected_candidate_binding_keys = {
        "batch_manifest_sha256",
        "combined_candidates_sha256",
        *expected_release_bindings,
    }
    if (
        not isinstance(candidate_bindings, dict)
        or set(candidate_bindings) != expected_candidate_binding_keys
        or any(
            candidate_bindings.get(key) != value
            for key, value in expected_release_bindings.items()
        )
        or not SHA256_RE.fullmatch(
            str(candidate_bindings.get("batch_manifest_sha256") or "")
        )
        or not SHA256_RE.fullmatch(
            str(candidate_bindings.get("combined_candidates_sha256") or "")
        )
    ):
        _fail("production release candidate bindings do not match the artifact")
    _validate_release_candidate_scope(
        candidate.get("auto_first_publish_scope")
    )
    if (
        candidate.get("schema_version")
        != "p0_horse_production_release_candidate.v1"
        or candidate.get("completion_policy_version")
        != FULL_PROFILE_COMPLETENESS_POLICY_VERSION
        or candidate.get("completion_policy_version")
        != artifact.get("completion_policy_version")
        or candidate.get("status")
        != "pending_independent_release_approval"
        or candidate.get("batch_id") != batch_manifest.get("batch_id")
        or candidate.get("region") != region
        or candidate.get("executor_reviewer_id")
        != release.get("executor_reviewer_id")
        or candidate.get("executor_reviewer_id") != artifact.get("reviewer_id")
        or candidate.get("artifact_prepared_at") != artifact.get("prepared_at")
        or candidate.get("expected_actions") != artifact.get("expected_actions")
    ):
        _fail("production release candidate metadata does not match the artifact")
    try:
        state = BatchRunState.read(batch_dir)
    except P0HorseBatchError as exc:
        _fail(f"production release candidate state is invalid: {exc}")
    if state.batch_id != batch_manifest.get("batch_id"):
        _fail("production release candidate state batch does not match")
    if state.stage == "abandoned":
        _fail("production release candidate state is abandoned")
    history = state.artifacts.get(
        f"release_candidate:{region}:{candidate_sha256}"
    )
    frozen_artifact_path = Path(
        str((history or {}).get("artifact_path") or "")
    )
    if not isinstance(history, dict):
        _fail("production release candidate has no matching frozen state history")
    if (
        Path(str(history.get("path") or "")).resolve()
        != candidate_path.resolve()
        or history.get("sha256") != candidate_sha256
    ):
        _fail(
            "production release candidate state path or SHA does not match"
        )
    if (
        not str(history.get("artifact_path") or "").strip()
        or str(artifact_path) != str(history.get("artifact_path"))
        or history.get("artifact_sha256") != artifact_sha256
    ):
        _fail("production release candidate artifact state does not match")
    if history.get("publish_scope") != candidate.get(
        "auto_first_publish_scope"
    ):
        _fail("production release candidate publish scope state does not match")
    _load_json_once(
        frozen_artifact_path,
        label="production release candidate artifact",
        expected_sha256=artifact_sha256,
    )
    if not _artifact_has_exact_committed_run(
        frozen_artifact_path,
        artifact_sha256,
    ):
        if (
            batch_manifest.get("batch_sha256")
            != candidate_bindings["batch_manifest_sha256"]
        ):
            _fail("production release batch manifest binding drift")
        combined_sha256 = hashlib.sha256(
            _read_regular_file_once(
                batch_dir / "artifact" / "combined_candidates.jsonl",
                label="production release combined candidates",
            )
        ).hexdigest()
        if combined_sha256 != candidate_bindings["combined_candidates_sha256"]:
            _fail("production release combined candidates binding drift")
    return candidate


def _load_and_validate_release_manifest(
    *,
    release_manifest_path: str | Path,
    release_manifest_sha256: str,
    artifact: dict[str, Any],
    artifact_path: str | Path,
    artifact_sha256: str,
    release_input: FrozenJsonInput | None = None,
) -> FrozenJsonInput:
    if release_input is None:
        release_input = _load_json_once(
            release_manifest_path,
            label="production release manifest",
            expected_sha256=release_manifest_sha256,
        )
    release = release_input.payload
    release_schema = release.get("schema_version")
    if release_schema not in {RELEASE_MANIFEST_SCHEMA, RELEASE_MANIFEST_SCHEMA_V2}:
        _fail("production release manifest schema is invalid")
    if (
        release_schema == RELEASE_MANIFEST_SCHEMA_V2
        and artifact.get("completion_policy_version")
        != FULL_PROFILE_COMPLETENESS_POLICY_VERSION
    ):
        _fail("reviewed artifact completion policy version is stale")
    approved_by = str(release.get("approved_by") or "").strip()
    approved_at = str(release.get("approved_at") or "").strip()
    decision_reference = str(release.get("decision_reference") or "").strip()
    if not all((approved_by, approved_at, decision_reference)):
        _fail("production release manifest approval metadata is incomplete")
    try:
        parsed_approved_at = datetime.fromisoformat(
            approved_at.replace("Z", "+00:00")
        )
    except ValueError:
        _fail("production release manifest approved_at is invalid")
    if parsed_approved_at.utcoffset() is None:
        _fail("production release manifest approved_at must include timezone")
    executor_reviewer_id = release.get("executor_reviewer_id")
    reviewer = _validate_reviewer(executor_reviewer_id)
    if executor_reviewer_id != artifact.get("reviewer_id"):
        _fail("production release manifest executor reviewer mismatch")
    if _normalized(approved_by) == _normalized(reviewer.get_username()):
        _fail("production release approver must be separate from the DB executor")
    bindings = release.get("bindings")
    if not isinstance(bindings, dict):
        _fail("production release manifest bindings are missing")
    inputs = artifact["inputs"]
    expected_bindings = {
        "research_v3_sha256": inputs["research_v3"]["sha256"],
        "authority_manifest_sha256": inputs["authority_manifest"]["sha256"],
        "profile_mapping_decisions_sha256": inputs[
            "profile_mapping_decisions"
        ]["sha256"],
        "production_snapshot_sha256": artifact["production_snapshot_sha256"],
        "final_artifact_sha256": artifact_sha256,
    }
    if release_schema == RELEASE_MANIFEST_SCHEMA_V2:
        release_candidate_sha256 = str(
            bindings.get("release_candidate_sha256") or ""
        ).strip()
        if not release_candidate_sha256:
            _fail("production release manifest candidate binding is missing")
        expected_bindings["release_candidate_sha256"] = release_candidate_sha256
    if bindings != expected_bindings:
        _fail("production release manifest bindings do not match the candidate artifact")
    candidate = None
    if release_schema == RELEASE_MANIFEST_SCHEMA_V2:
        candidate = _load_and_validate_release_candidate(
            release=release,
            release_manifest_path=release_manifest_path,
            candidate_sha256=release_candidate_sha256,
            artifact=artifact,
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256,
            expected_release_bindings={
                key: value
                for key, value in expected_bindings.items()
                if key != "release_candidate_sha256"
            },
        )
    if (
        release_schema == RELEASE_MANIFEST_SCHEMA_V2
        or release_input.sha256
        not in TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256
    ):
        _validate_rolling_release_ledger(
            release,
            release_input.sha256,
            release_manifest_path=release_manifest_path,
            candidate=candidate,
            candidate_sha256=(
                release_candidate_sha256
                if release_schema == RELEASE_MANIFEST_SCHEMA_V2
                else ""
            ),
            artifact_sha256=artifact_sha256,
        )
    return release_input


def _already_applied_profile(row: dict[str, Any], artifact_sha256: str) -> HorseProfile | None:
    identity_key = row["deterministic_identity_key"]
    for profile in _strong_identity_profiles(row["identity"]):
        batches = (profile.source_refs or {}).get("p0_reviewed_batches") or {}
        if isinstance(batches, dict) and batches.get(identity_key) == artifact_sha256:
            return profile
    return None


def _profile_matches_payload(profile: HorseProfile, row: dict[str, Any]) -> bool:
    for field, expected in {**row["profile_payload"], **row["pedigree_payload"]}.items():
        if field == "racing_region" and row["resolution"]["decision"] == "bind_existing":
            continue
        actual = getattr(profile, field)
        if isinstance(actual, date):
            actual = actual.isoformat()
        if actual != expected:
            return False
    return True


def _profile_records_match_payload(
    profile: HorseProfile,
    records: list[dict[str, Any]],
) -> bool:
    if profile.race_records.count() != len(records):
        return False
    compared_fields = (
        "race_name",
        "race_year",
        "race_date_precision",
        "race_name_normalized",
        "race_region",
        "race_number",
        "grade_text",
        "normalized_grade",
        "racecourse",
        "distance_text",
        "distance_meters",
        "surface",
        "race_type_text",
        "horse_number",
        "barrier",
        "jockey_name",
        "carried_weight",
        "finish_time",
        "prize_text",
        "finish_position",
        "result_status",
        "start_status",
        "is_overseas",
        "is_major_win",
        "source_name",
        "source_url",
    )
    for payload in records:
        idempotency = record_idempotency_key(profile, payload)
        canonical = canonical_race_key(profile, payload)
        identity_query = Q(
            horse_profile=profile,
            idempotency_key=idempotency,
        )
        if canonical:
            identity_query |= Q(
                horse_profile=profile,
                canonical_race_key=canonical,
            )
        record = HorseRaceRecord.objects.filter(identity_query).first()
        if record is None:
            return False
        if (
            record.race_date.isoformat() if record.race_date else None
        ) != payload.get("race_date"):
            return False
        for field in compared_fields:
            expected = payload.get(field)
            if field == "race_year":
                expected = expected or None
            elif field == "distance_meters":
                expected = expected or None
            elif field == "grade_text":
                expected = payload.get("grade_text", payload.get("normalized_grade", ""))
            elif field in {"is_overseas", "is_major_win"}:
                expected = bool(expected)
            elif expected is None:
                expected = ""
            if getattr(record, field) != expected:
                return False
    return True


def _resolve_current_profile(
    row: dict[str, Any],
    *,
    artifact_sha256: str,
    lock: bool,
) -> tuple[HorseProfile | None, bool]:
    resolution = row.get("resolution")
    if not isinstance(resolution, dict):
        _fail("artifact row resolution is invalid")
    applied = _already_applied_profile(row, artifact_sha256)
    if applied is not None:
        if not _profile_matches_payload(applied, row) or not _profile_records_match_payload(
            applied,
            row["race_records_payload"],
        ):
            _fail(f"{row['identity']['horse_name']} applied profile drift")
        if lock:
            applied = HorseProfile.objects.select_for_update().get(pk=applied.pk)
        return applied, True
    if resolution.get("decision") == "create_new":
        current_mapping = build_profile_mapping_snapshot(row["identity"])
        if current_mapping != resolution.get("database_mapping_snapshot"):
            _fail(f"{row['identity']['horse_name']} create_new database snapshot drift")
        return None, False
    profile_id = resolution.get("profile_id")
    queryset = HorseProfile.objects.select_for_update() if lock else HorseProfile.objects
    profile = queryset.filter(pk=profile_id).first()
    if profile is None:
        _fail(f"{row['identity']['horse_name']} bound profile is missing")
    if build_profile_snapshot(profile) != resolution.get("profile_snapshot"):
        _fail(f"{row['identity']['horse_name']} bound profile snapshot drift")
    if build_profile_mapping_snapshot(row["identity"]) != resolution.get("database_mapping_snapshot"):
        _fail(f"{row['identity']['horse_name']} database mapping snapshot drift")
    return profile, False


def _validate_artifact_row(
    row: dict[str, Any],
    *,
    artifact_sha256: str,
    lock: bool,
) -> tuple[HorseProfile | None, bool]:
    if not isinstance(row, dict) or row.get("reviewed") is not True:
        _fail("artifact row must be reviewed")
    identity = _identity(row.get("identity"), context="artifact row")
    if row.get("deterministic_identity_key") != deterministic_identity_key(identity):
        _fail(f"{identity['horse_name']} deterministic identity key drift")
    _require_url(row.get("source_url"), context=f"{identity['horse_name']} artifact source")
    reviews = row.get("module_reviews")
    if not isinstance(reviews, dict):
        _fail(f"{identity['horse_name']} module reviews are missing")
    for module in REQUIRED_COMPLETION_MODULES:
        review = reviews.get(module)
        _review_metadata(review, context=f"{identity['horse_name']} module {module}")
        if review.get("status") != "approved" or int(review.get("confidence") or 0) < MIN_FORMAL_CONFIDENCE:
            _fail(f"{identity['horse_name']} module {module} is not formally approved")
    records = row.get("race_records_payload")
    if not isinstance(records, list):
        _fail(f"{identity['horse_name']} race records are invalid")
    _validate_unique_records(records, context=identity["horse_name"])
    career = row.get("career_history")
    if not isinstance(career, dict) or career.get("status") != "complete":
        _fail(f"{identity['horse_name']} career history is not complete")
    if career.get("record_authority_status") != HorseCareerRecordAuthorityStatus.SOURCE_RECORDS_VERIFIED:
        _fail(f"{identity['horse_name']} record authority is not approved")
    if career.get("collected_start_count") != sum(record.get("start_status") == "started" for record in records):
        _fail(f"{identity['horse_name']} collected start count drift")
    profile, already_applied = _resolve_current_profile(
        row,
        artifact_sha256=artifact_sha256,
        lock=lock,
    )
    return profile, already_applied


def _planned_record_actions(profile: HorseProfile | None, records: list[dict[str, Any]]) -> dict[str, int]:
    if profile is None:
        return {"creates": len(records), "updates": 0, "existing": 0}
    creates = updates = existing = 0
    for record in records:
        idempotency = record_idempotency_key(profile, record)
        canonical = canonical_race_key(profile, record)
        identity_query = Q(
            horse_profile=profile,
            idempotency_key=idempotency,
        )
        if canonical:
            identity_query |= Q(
                horse_profile=profile,
                canonical_race_key=canonical,
            )
        current = HorseRaceRecord.objects.filter(identity_query).first()
        if current is None:
            creates += 1
        else:
            expected = {
                "race_name": record.get("race_name", ""),
                "race_date": record.get("race_date"),
                "racecourse": record.get("racecourse", ""),
                "result_status": record.get("result_status", ""),
                "start_status": record.get("start_status", ""),
                "source_url": record.get("source_url", ""),
            }
            current_values = {
                "race_name": current.race_name,
                "race_date": current.race_date.isoformat() if current.race_date else None,
                "racecourse": current.racecourse,
                "result_status": current.result_status,
                "start_status": current.start_status,
                "source_url": current.source_url,
            }
            if expected == current_values:
                existing += 1
            else:
                updates += 1
    return {"creates": creates, "updates": updates, "existing": existing}


def _simulate(artifact: dict[str, Any], *, artifact_sha256: str, lock: bool = False) -> dict[str, Any]:
    report = {
        "validated_horse_count": 0,
        "planned_profile_creates": 0,
        "planned_profile_updates": 0,
        "planned_race_record_creates": 0,
        "planned_race_record_updates": 0,
        "existing_race_records": 0,
        "planned_p0_source_upserts": 0,
        "planned_module_audits": 0,
        "planned_metadata_reconciliations": 0,
        "already_applied_profiles": 0,
        "database_write_count": 0,
    }
    seen_identity_keys: set[str] = set()
    seen_profile_ids: set[int] = set()
    for row in artifact["rows"]:
        identity_key = row.get("deterministic_identity_key")
        if identity_key in seen_identity_keys:
            _fail("artifact contains duplicate identity")
        seen_identity_keys.add(identity_key)
        profile, already_applied = _validate_artifact_row(
            row,
            artifact_sha256=artifact_sha256,
            lock=lock,
        )
        if profile and profile.id in seen_profile_ids:
            _fail("artifact resolves multiple identities to one profile")
        if profile:
            seen_profile_ids.add(profile.id)
        report["validated_horse_count"] += 1
        report["already_applied_profiles"] += int(already_applied)
        if already_applied:
            completion_run = _find_completion_run(artifact_sha256)
            if completion_run is None:
                _fail("applied profile is missing its completion run")
            report["planned_metadata_reconciliations"] += int(
                _p0_source_region_requires_reconcile(
                    row=row,
                    profile=profile,
                    artifact_sha256=artifact_sha256,
                    completion_run=completion_run,
                )
            )
        else:
            report["planned_profile_creates"] += int(profile is None)
            report["planned_profile_updates"] += int(profile is not None)
            report["planned_p0_source_upserts"] += 1
            report["planned_module_audits"] += len(REQUIRED_COMPLETION_MODULES)
        actions = _planned_record_actions(profile, row["race_records_payload"])
        report["planned_race_record_creates"] += actions["creates"]
        report["planned_race_record_updates"] += actions["updates"]
        report["existing_race_records"] += actions["existing"]
    return report


def dry_run_reviewed_p0_completion_artifact(
    *,
    artifact_path: str | Path,
    artifact_sha256: str,
    release_manifest_path: str | Path,
    release_manifest_sha256: str,
) -> dict[str, Any]:
    with _production_release_execution_window(
        release_manifest_path=release_manifest_path,
        release_manifest_sha256=release_manifest_sha256,
    ) as release_input:
        return _dry_run_reviewed_p0_completion_artifact_locked(
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256,
            release_manifest_path=release_manifest_path,
            release_manifest_sha256=release_manifest_sha256,
            release_input=release_input,
        )


def _dry_run_reviewed_p0_completion_artifact_locked(
    *,
    artifact_path: str | Path,
    artifact_sha256: str,
    release_manifest_path: str | Path,
    release_manifest_sha256: str,
    release_input: FrozenJsonInput,
) -> dict[str, Any]:
    artifact, actual_sha = _load_artifact(artifact_path, artifact_sha256)
    release_input = _load_and_validate_release_manifest(
        release_manifest_path=release_manifest_path,
        release_manifest_sha256=release_manifest_sha256,
        artifact=artifact,
        artifact_path=artifact_path,
        artifact_sha256=actual_sha,
        release_input=release_input,
    )
    report = _simulate(artifact, artifact_sha256=actual_sha)
    _assert_expected_actions(artifact, report, phase="dry-run")
    report.update(
        {
            "schema_version": "p0-horse-reviewed-completion-dry-run.v1",
            "artifact_sha256": actual_sha,
            "release_manifest_sha256": release_input.sha256,
            "dry_run": True,
            "commit_table_lock_plan": {
                "database": "postgresql_only",
                "mode": COMMIT_IDENTITY_TABLE_LOCK_MODE,
                "timeout_ms": COMMIT_IDENTITY_TABLE_LOCK_TIMEOUT_MS,
                "tables": list(COMMIT_IDENTITY_TABLE_LOCKS),
                "blocks_writes": True,
                "dry_run_lock_acquired": False,
            },
        }
    )
    return report


def _assert_expected_actions(
    artifact: dict[str, Any],
    report: dict[str, Any],
    *,
    phase: str,
) -> None:
    if report["already_applied_profiles"]:
        if report["already_applied_profiles"] != report["validated_horse_count"]:
            _fail(f"{phase} contains a partially applied batch")
        return
    actual_actions = {
        "profile_creates": report["planned_profile_creates"],
        "profile_updates": report["planned_profile_updates"],
        "race_record_creates": report["planned_race_record_creates"],
        "race_record_updates": report["planned_race_record_updates"],
        "existing_race_records": report["existing_race_records"],
        "p0_source_upserts": report["planned_p0_source_upserts"],
        "module_audits": report["planned_module_audits"],
    }
    if actual_actions != artifact.get("expected_actions"):
        _fail(f"{phase} expected action drift")


def _lock_identity_keys(rows: list[dict[str, Any]]) -> None:
    if connection.vendor != "postgresql":
        return
    lock_ids = _identity_lock_keys(rows)
    with connection.cursor() as cursor:
        for lock_id in lock_ids:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])


def _identity_lock_keys(rows: list[dict[str, Any]]) -> list[int]:
    return sorted(
        {
            int(row["deterministic_identity_key"][:16], 16) - (1 << 63)
            for row in rows
        }
    )


def _acquire_identity_session_locks(rows: list[dict[str, Any]]) -> list[int]:
    if connection.vendor != "postgresql":
        return []
    lock_ids = _identity_lock_keys(rows)
    with connection.cursor() as cursor:
        for lock_id in lock_ids:
            cursor.execute("SELECT pg_advisory_lock(%s)", [lock_id])
    return lock_ids


def _release_identity_session_locks(lock_ids: list[int]) -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        for lock_id in reversed(lock_ids):
            cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])


@contextmanager
def _identity_session_lock_scope(rows: list[dict[str, Any]]):
    lock_ids = _acquire_identity_session_locks(rows)
    try:
        yield
    finally:
        _release_identity_session_locks(lock_ids)


def _begin_commit_isolation() -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")


def _lock_commit_identity_tables() -> None:
    if connection.vendor != "postgresql":
        return
    quoted_tables = ", ".join(
        connection.ops.quote_name(table_name)
        for table_name in COMMIT_IDENTITY_TABLE_LOCKS
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"SET LOCAL lock_timeout = '{COMMIT_IDENTITY_TABLE_LOCK_TIMEOUT_MS}ms'"
        )
        cursor.execute(
            f"LOCK TABLE {quoted_tables} IN "
            f"{COMMIT_IDENTITY_TABLE_LOCK_MODE} MODE"
        )


def _mapping_snapshot_matches_idempotent_apply(
    expected: dict[str, Any],
    current: dict[str, Any],
    *,
    profile_id: int,
) -> bool:
    if (
        expected.get("schema_version") != current.get("schema_version")
    ):
        return False
    expected_data = expected.get("data") or {}
    current_data = current.get("data") or {}
    list_fields = {"name_match_profiles", "strong_identity_profiles"}
    if {
        key: value for key, value in expected_data.items() if key not in list_fields
    } != {
        key: value for key, value in current_data.items() if key not in list_fields
    }:
        return False
    for field in ("name_match_profiles", "strong_identity_profiles"):
        expected_rows = {
            item["profile_id"]: item
            for item in expected_data.get(field, [])
        }
        current_rows = {
            item["profile_id"]: item
            for item in current_data.get(field, [])
        }
        expected_ids = set(expected_rows)
        current_ids = set(current_rows)
        if current_ids != expected_ids | {profile_id}:
            return False
        for other_id in expected_ids - {profile_id}:
            if expected_rows[other_id] != current_rows.get(other_id):
                return False
    return True


def _rescan_locked_identity_mapping_snapshots(
    artifact: dict[str, Any],
    *,
    artifact_sha256: str,
) -> int:
    rows = artifact.get("rows")
    if not isinstance(rows, list) or not rows:
        _fail("reviewed artifact rows are required for locked identity rescan")
    seen_keys: set[str] = set()
    for row in rows:
        identity = _identity(
            row.get("identity"),
            context="locked artifact identity rescan",
        )
        identity_key = deterministic_identity_key(identity)
        if row.get("deterministic_identity_key") != identity_key:
            _fail("locked artifact deterministic identity key drift")
        if identity_key in seen_keys:
            _fail("locked artifact contains duplicate four-field identity")
        seen_keys.add(identity_key)
        resolution = row.get("resolution")
        if not isinstance(resolution, dict):
            _fail("locked artifact mapping resolution is missing")
        current_snapshot = build_profile_mapping_snapshot(identity)
        if resolution.get("database_mapping_snapshot") != current_snapshot:
            already_applied = _already_applied_profile(row, artifact_sha256)
            if already_applied is None or not _mapping_snapshot_matches_idempotent_apply(
                resolution["database_mapping_snapshot"],
                current_snapshot,
                profile_id=already_applied.id,
            ):
                _fail(
                    f"{identity['horse_name']} locked database mapping snapshot drift"
                )
    return len(rows)


def _select_or_create_term(row: dict[str, Any]) -> tuple[TermEntry, bool]:
    identity = row["identity"]
    horse_name = identity["horse_name"]
    matching_term_ids = list(
        TermEntry.objects
        .filter(
            Q(term_type=TermType.HORSE)
            & (
                Q(source_ja__iexact=horse_name)
                | Q(target_zh__iexact=horse_name)
                | Q(source_aliases__text__iexact=horse_name)
            )
        )
        .distinct()
        .values_list("id", flat=True)
    )
    terms = list(
        TermEntry.objects.select_for_update()
        .filter(id__in=matching_term_ids)
        .order_by("id")
    )
    available = [term for term in terms if not hasattr(term, "horse_profile")]
    if len(available) > 1:
        _fail(f"{horse_name} has multiple unbound matching terms")
    if available:
        return available[0], False
    language = "en"
    for alias in row.get("aliases_payload") or []:
        candidate = str(alias.get("language") or "").strip()
        if candidate in SourceLanguage.values:
            language = candidate
            break
    term = TermEntry.objects.create(
        term_type=TermType.HORSE,
        source_language=language,
        racing_region=row["profile_payload"].get("racing_region", ""),
        source_ja=horse_name,
        target_zh="",
        translation_status=TermTranslationStatus.PENDING,
        notes="Created by reviewed P0 50-horse production artifact",
        is_active=True,
    )
    return term, True


def _create_profile(row: dict[str, Any]) -> HorseProfile:
    term, _ = _select_or_create_term(row)
    return HorseProfile.objects.create(
        primary_term=term,
        original_name=row["identity"]["horse_name"],
        english_name=row["identity"]["horse_name"],
        racing_region=row["profile_payload"].get("racing_region", "japan"),
    )


def _apply_aliases(profile: HorseProfile, aliases: list[dict[str, Any]]) -> None:
    for alias in aliases:
        text = str(alias.get("name") or "").strip()
        if not text or _normalized(text) == _normalized(profile.primary_term.source_ja):
            continue
        language = str(alias.get("language") or profile.primary_term.source_language)
        if language not in SourceLanguage.values:
            language = profile.primary_term.source_language
        TermAlias.objects.get_or_create(
            term=profile.primary_term,
            source_language=language,
            text=text,
        )


def _apply_artifact_row(
    *,
    row: dict[str, Any],
    profile: HorseProfile,
    reviewer_id: int,
    artifact_sha256: str,
    completion_run: HorseProfileCompletionRun,
) -> dict[str, Any]:
    applied_row = {
        **deepcopy(row),
        "profile_id": profile.id,
        "reviewed": True,
    }
    summary = apply_reviewed_completion_artifact(
        {
            "reviewed": True,
            "reviewer_id": reviewer_id,
            "rows": [applied_row],
        },
        commit=True,
    )
    skip_total = sum(
        value
        for key, value in summary.items()
        if key.startswith("skipped_") and isinstance(value, int)
    )
    if skip_total or summary.get("manual_lock_skipped"):
        _fail(f"{row['identity']['horse_name']} formal apply was skipped or hit a manual lock")
    profile.refresh_from_db()
    _apply_aliases(profile, row.get("aliases_payload") or [])
    identity_key = row["deterministic_identity_key"]
    source_refs = dict(profile.source_refs or {})
    batches = dict(source_refs.get("p0_reviewed_batches") or {})
    batches[identity_key] = artifact_sha256
    # A profile that passed a human-reviewed batch commit earns verified
    # identity provenance: all of its current identity keys may satisfy the
    # BASIC publish gate (see services/horse_profile_publish.py).
    existing_keys = [str(key) for key in source_refs.get("horse_identity_keys") or []]
    verified_keys = list(source_refs.get("horse_identity_verified_keys") or [])
    verified_folded = {str(key).casefold() for key in verified_keys}
    for key in existing_keys:
        if key.casefold() not in verified_folded:
            verified_keys.append(key.casefold())
            verified_folded.add(key.casefold())
    source_refs.update(
        {
            "p0_reviewed_identity": {
                **row["identity"],
                "deterministic_identity_key": identity_key,
            },
            "p0_reviewed_batches": batches,
        }
    )
    if verified_keys:
        source_refs["horse_identity_verified_keys"] = verified_keys
    profile.source_refs = source_refs
    profile.save(update_fields=["source_refs", "updated_at"])
    _apply_p0_source_metadata(
        row=row,
        profile=profile,
        reviewer_id=reviewer_id,
        artifact_sha256=artifact_sha256,
        completion_run=completion_run,
    )
    HorseProfileDataCandidate.objects.filter(
        profile=profile,
        source_name=row["source_name"],
        status=HorseProfileCandidateStatus.APPLIED,
        completion_run__isnull=True,
    ).update(completion_run=completion_run)
    claimed_record_ids = summary.get("claimed_race_record_ids") or []
    HorseRaceRecord.objects.filter(
        horse_profile=profile,
        id__in=claimed_record_ids,
        completion_run__isnull=True,
    ).update(completion_run=completion_run)
    evaluation = evaluate_full_profile_completeness(profile)
    if not evaluation.is_complete:
        _fail(
            f"{row['identity']['horse_name']} is not strict complete after apply: "
            f"{evaluation.blocking_reasons}"
        )
    return summary


def _reviewed_source_region(row: dict[str, Any]) -> str:
    candidate = (row.get("evidence") or {}).get("candidate") or {}
    region = str(candidate.get("sample_region") or "").strip()
    if region not in RacingRegion.values or region == RacingRegion.OTHER:
        _fail(f"{row['identity']['horse_name']} reviewed sample region is invalid")
    return region


def _apply_p0_source_metadata(
    *,
    row: dict[str, Any],
    profile: HorseProfile,
    reviewer_id: int,
    artifact_sha256: str,
    completion_run: HorseProfileCompletionRun,
) -> bool:
    source = HorseP0Source.objects.get(
        profile=profile,
        source_type=HorseP0SourceType.MANUAL,
    )
    expected = {
        "completion_run": completion_run,
        "racing_region": _reviewed_source_region(row),
        "evidence_summary": "Reviewed major-race P0 candidate batch completion",
        "evidence_payload": {
            **row["evidence"],
            "artifact_sha256": artifact_sha256,
            "reviewer_id": reviewer_id,
            "identity": row["identity"],
            "deterministic_identity_key": row["deterministic_identity_key"],
        },
        "metadata": {
            "batch_kind": "reviewed_p0_horse_completion",
            "authority_semantics": (
                "US combined sources inherit only the frozen v3 approval; "
                "they are not Equibase official per-race records."
            ),
        },
        "status": HorseP0SourceStatus.ACTIVE,
    }
    changed_fields = [
        field for field, value in expected.items() if getattr(source, field) != value
    ]
    if not changed_fields:
        return False
    for field, value in expected.items():
        setattr(source, field, value)
    source.save(update_fields=[*changed_fields, "updated_at"])
    return True


def _idempotent_p0_source(
    *,
    row: dict[str, Any],
    profile: HorseProfile,
    artifact_sha256: str,
    completion_run: HorseProfileCompletionRun,
) -> HorseP0Source:
    source = HorseP0Source.objects.get(
        profile=profile,
        source_type=HorseP0SourceType.MANUAL,
    )
    if source.status != HorseP0SourceStatus.ACTIVE:
        _fail(f"{row['identity']['horse_name']} P0 source was revoked after apply")
    if (
        source.completion_run_id != completion_run.id
        or (source.evidence_payload or {}).get("artifact_sha256") != artifact_sha256
    ):
        _fail(f"{row['identity']['horse_name']} P0 source belongs to a newer review")
    return source


def _p0_source_region_requires_reconcile(
    *,
    row: dict[str, Any],
    profile: HorseProfile,
    artifact_sha256: str,
    completion_run: HorseProfileCompletionRun,
) -> bool:
    source = _idempotent_p0_source(
        row=row,
        profile=profile,
        artifact_sha256=artifact_sha256,
        completion_run=completion_run,
    )
    return source.racing_region != _reviewed_source_region(row)


def _reconcile_p0_source_region(
    *,
    row: dict[str, Any],
    profile: HorseProfile,
    artifact_sha256: str,
    completion_run: HorseProfileCompletionRun,
) -> bool:
    source = _idempotent_p0_source(
        row=row,
        profile=profile,
        artifact_sha256=artifact_sha256,
        completion_run=completion_run,
    )
    expected_region = _reviewed_source_region(row)
    if source.racing_region == expected_region:
        return False
    source.racing_region = expected_region
    source.save(update_fields=["racing_region", "updated_at"])
    return True


def _previous_success_summary(artifact_sha256: str) -> dict[str, Any] | None:
    logs = TaskExecutionLog.objects.filter(
        task_name="apply_reviewed_p0_horse_completion",
        status=TaskStatus.SUCCESS,
    ).order_by("id")
    for log in logs:
        payload = log.payload or {}
        summary = payload.get("summary")
        if payload.get("artifact_sha256") == artifact_sha256 and isinstance(
            summary, dict
        ):
            return summary
    return None


def _find_completion_run(artifact_sha256: str) -> HorseProfileCompletionRun | None:
    for run in HorseProfileCompletionRun.objects.order_by("id"):
        if (run.parameters or {}).get("artifact_sha256") == artifact_sha256:
            return run
    return None


def _completion_run(artifact_path: str | Path, artifact_sha256: str, reviewer_id: int) -> HorseProfileCompletionRun:
    existing = _find_completion_run(artifact_sha256)
    if existing is not None:
        return HorseProfileCompletionRun.objects.select_for_update().get(
            pk=existing.pk
        )
    return HorseProfileCompletionRun.objects.create(
        name=f"Reviewed P0 horse completion {artifact_sha256[:12]}",
        status=HorseCompletionRunStatus.RUNNING,
        dry_run=False,
        regions=[],
        parameters={"artifact_sha256": artifact_sha256},
        artifact_path=str(artifact_path),
        source_names=["reviewed_p0_horse_completion_v3"],
        started_at=timezone.now(),
        operated_by_id=reviewer_id,
    )


def _after_task_execution_log_created_for_test() -> None:
    """Patch point for transaction rollback tests; never controlled at runtime."""


def _commit_reviewed_p0_completion_artifact_locked(
    *,
    artifact_path: str | Path,
    artifact_sha256: str,
    release_manifest_path: str | Path,
    release_manifest_sha256: str,
    confirm_reviewed_artifact: bool,
    release_input: FrozenJsonInput,
) -> dict[str, Any]:
    if not confirm_reviewed_artifact:
        _fail("commit requires --confirm-reviewed-artifact")
    if release_input.payload.get("schema_version") != RELEASE_MANIFEST_SCHEMA_V2:
        _fail("legacy v1 release is read-only and cannot be committed")
    artifact, actual_sha = _load_artifact(artifact_path, artifact_sha256)
    release_input = _load_and_validate_release_manifest(
        release_manifest_path=release_manifest_path,
        release_manifest_sha256=release_manifest_sha256,
        artifact=artifact,
        artifact_path=artifact_path,
        artifact_sha256=actual_sha,
        release_input=release_input,
    )
    reviewer = _validate_reviewer(artifact["reviewer_id"])
    with _identity_session_lock_scope(artifact["rows"]), transaction.atomic():
        _begin_commit_isolation()
        _lock_commit_identity_tables()
        locked_identity_rescan_count = _rescan_locked_identity_mapping_snapshots(
            artifact,
            artifact_sha256=actual_sha,
        )
        reviewer = (
            get_user_model().objects.select_for_update().filter(pk=reviewer.id).first()
        )
        if reviewer is None or not reviewer.is_active or not reviewer.is_superuser:
            _fail("reviewer snapshot drift during commit")
        simulation = _simulate(artifact, artifact_sha256=actual_sha, lock=True)
        _assert_expected_actions(artifact, simulation, phase="commit")
        completion_run = _completion_run(artifact_path, actual_sha, reviewer.id)
        run_was_committed = (
            completion_run.status == HorseCompletionRunStatus.COMMITTED
        )
        aggregate = {
            "race_records_created": 0,
            "race_records_updated": 0,
            "race_records_existing": 0,
        }
        strict_complete_count = 0
        metadata_reconciled_count = 0
        for row in artifact["rows"]:
            profile, already_applied = _resolve_current_profile(
                row,
                artifact_sha256=actual_sha,
                lock=True,
            )
            if already_applied:
                evaluation = evaluate_full_profile_completeness(profile)
                if not evaluation.is_complete:
                    _fail(f"{row['identity']['horse_name']} idempotent profile is no longer strict complete")
                metadata_reconciled_count += int(
                    _reconcile_p0_source_region(
                        row=row,
                        profile=profile,
                        artifact_sha256=actual_sha,
                        completion_run=completion_run,
                    )
                )
                strict_complete_count += 1
                continue
            if profile is None:
                profile = _create_profile(row)
            row_summary = _apply_artifact_row(
                row=row,
                profile=profile,
                reviewer_id=reviewer.id,
                artifact_sha256=actual_sha,
                completion_run=completion_run,
            )
            row_summary = row_summary or {}
            for key in aggregate:
                aggregate[key] += int(row_summary.get(key) or 0)
            strict_complete_count += 1
        result = {
            **simulation,
            **aggregate,
            "strict_complete_count": strict_complete_count,
            "artifact_sha256": actual_sha,
            "release_manifest_sha256": release_input.sha256,
            "locked_identity_rescan_count": locked_identity_rescan_count,
            "metadata_reconciled_count": metadata_reconciled_count,
            "commit_table_lock": {
                "mode": COMMIT_IDENTITY_TABLE_LOCK_MODE,
                "timeout_ms": COMMIT_IDENTITY_TABLE_LOCK_TIMEOUT_MS,
                "tables": list(COMMIT_IDENTITY_TABLE_LOCKS),
            },
            "database_write_count": (
                simulation["planned_profile_creates"]
                + simulation["planned_profile_updates"]
                + aggregate["race_records_created"]
                + aggregate["race_records_updated"]
                + simulation["planned_p0_source_upserts"]
                + simulation["planned_module_audits"]
                + metadata_reconciled_count
            ),
        }
        completed_at = timezone.now()
        completion_run.status = HorseCompletionRunStatus.COMMITTED
        if run_was_committed:
            original_summary = _previous_success_summary(actual_sha)
            if original_summary is None:
                _fail("committed run is missing its successful task log")
            completion_run.summary = {
                **original_summary,
                "last_idempotent_verification": {
                    **result,
                    "verified_at": completed_at.isoformat(),
                },
            }
        else:
            completion_run.summary = result
        completion_run.finished_at = completed_at
        completion_run.save(
            update_fields=["status", "summary", "finished_at", "updated_at"]
        )
        TaskExecutionLog.objects.create(
            task_name="apply_reviewed_p0_horse_completion",
            status=TaskStatus.SUCCESS,
            payload={
                "artifact_path": str(artifact_path),
                "artifact_sha256": actual_sha,
                "release_manifest_sha256": release_input.sha256,
                "reviewer_id": reviewer.id,
                "summary": result,
            },
            detail=(
                f"Reviewed P0 completion committed: "
                f"{strict_complete_count}/{len(artifact['rows'])} strict complete"
            ),
            finished_at=timezone.now(),
        )
        _after_task_execution_log_created_for_test()
        return result


def commit_reviewed_p0_completion_artifact(
    *,
    artifact_path: str | Path,
    artifact_sha256: str,
    release_manifest_path: str | Path,
    release_manifest_sha256: str,
    confirm_reviewed_artifact: bool,
) -> dict[str, Any]:
    with _production_release_execution_window(
        release_manifest_path=release_manifest_path,
        release_manifest_sha256=release_manifest_sha256,
    ) as release_input:
        return _commit_reviewed_p0_completion_artifact_locked(
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256,
            release_manifest_path=release_manifest_path,
            release_manifest_sha256=release_manifest_sha256,
            confirm_reviewed_artifact=confirm_reviewed_artifact,
            release_input=release_input,
        )


def write_prepared_artifact_directory(
    *,
    output_directory: str | Path,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    output = Path(output_directory)
    if output.exists():
        _fail("prepare output directory must be new")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent)
    )
    try:
        artifact_path = temporary / "reviewed_p0_horse_completion_artifact.json"
        artifact_path.write_bytes(
            json.dumps(
                artifact,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8")
            + b"\n"
        )
        artifact_sha = sha256_file(artifact_path)
        manifest = {
            "schema_version": "p0-horse-reviewed-completion-package.v1",
            "artifact": {
                "path": artifact_path.name,
                "sha256": artifact_sha,
            },
            "summary": artifact["summary"],
            "release_status": artifact["release_status"],
            "trusted_release_manifest_required": True,
            "database_write_count": 0,
        }
        manifest_path = temporary / "manifest.json"
        manifest_path.write_bytes(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8")
            + b"\n"
        )
        temporary.rename(output)
    except Exception:
        for child in temporary.iterdir():
            child.unlink()
        temporary.rmdir()
        raise
    return {
        "output_directory": str(output),
        "artifact_path": str(output / artifact_path.name),
        "artifact_sha256": artifact_sha,
        "manifest_path": str(output / manifest_path.name),
        "manifest_sha256": sha256_file(output / manifest_path.name),
    }

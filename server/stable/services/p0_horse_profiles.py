from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Max, Q, Value, When
from django.utils import timezone

from stable.models import (
    HorseIdentityConflict,
    HorseIdentityConflictStatus,
    HorseCareerHistoryStatus,
    HorseCareerRecordAuthorityStatus,
    HorseP0Source,
    HorseP0SourceStatus,
    HorseP0SourceType,
    HorseProfile,
    HorseProfileCandidateStatus,
    HorseProfileCompleteness,
    HorseProfileDataCandidate,
    HorseProfileModule,
    HorseProfileStatus,
    ArticleHorseLinkStatus,
    HorseRaceRecord,
    HorseRaceResultStatus,
    HorseRacingCareerStatus,
    RaceEvent,
    RaceEventResult,
    RaceEventRunner,
    RaceGrade,
    RaceRunnerStatus,
    RacingRegion,
    SourceLanguage,
    TermEntry,
    TermTranslationStatus,
    TermType,
)
from stable.services.horse_profiles import PEDIGREE_TEXT_FIELDS, update_completeness
from stable.services.horse_race_records import (
    has_official_start_count_evidence,
    has_ambiguous_legacy_race_record,
    parse_record_date,
    refresh_career_history_completeness,
    upsert_race_record,
    valid_http_url,
)
from stable.services.term_maintenance import write_csv_artifact, write_json_artifact


P0_REGIONS = {
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.UNITED_KINGDOM,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
}
P0_MAJOR_RACE_GRADES = {
    RaceGrade.G1,
    RaceGrade.G2,
    RaceGrade.G3,
    RaceGrade.JG1,
    RaceGrade.JG2,
    RaceGrade.JG3,
    RaceGrade.JPN1,
    RaceGrade.JPN2,
    RaceGrade.JPN3,
}
BASIC_PROFILE_REQUIRED_FIELDS = (
    "country",
    "sex",
    "color",
    "birth_date",
    "owner_name",
    "trainer_name",
    "breeder_name",
)
REQUIRED_COMPLETION_MODULES = (
    HorseProfileModule.PROFILE,
    HorseProfileModule.PEDIGREE,
    HorseProfileModule.RACE_RECORD,
    HorseProfileModule.MAJOR_WINS,
)
MODULE_REVIEW_ALIASES = {
    HorseProfileModule.PROFILE: ("profile", "basic_profile"),
    HorseProfileModule.PEDIGREE: ("pedigree",),
    HorseProfileModule.RACE_RECORD: ("race_record", "race_records", "race_history"),
    HorseProfileModule.MAJOR_WINS: ("major_wins",),
    HorseProfileModule.ALIASES: ("aliases",),
}
MIN_APPROVED_CONFIDENCE = 80
P0_CANDIDATE_ARTIFACT_VERSION = "1.1"
GENERIC_SOURCE_NAMESPACES = {
    "database",
    "media",
    "news",
    "official",
    "source",
    "unknown",
    "web",
}
SOURCE_NAMESPACE_ALIASES = {
    "equibase": "equibase",
    "equibase_pdf_chart": "equibase",
    "equibase_yearbook": "equibase",
    "france_galop": "france_galop",
    "geny": "geny",
    "hkjc": "hkjc",
    "hkjc_local_results": "hkjc",
    "hkjc_official_result_page": "hkjc",
    "horse_racing_nation": "horse_racing_nation",
    "horse_racing_nation_track_day": "horse_racing_nation",
    "irishracing": "irishracing",
    "irishracing_historical_result": "irishracing",
    "jbis": "jbis",
    "jra": "jra",
    "jra_official_result_page": "jra",
    "keiba_go_jp": "keiba_go_jp",
    "keiba_go_jp_deba_table": "keiba_go_jp",
    "keiba_go_jp_race_mark_table": "keiba_go_jp",
    "netkeiba": "netkeiba",
    "netkeiba_result": "netkeiba",
    "nsa": "nsa",
    "nsa_official_result_pdf": "nsa",
    "sporting_life": "sporting_life",
    "sporting_life_result_detail": "sporting_life",
    "zeturf": "zeturf",
    "zeturf_race_detail": "zeturf",
    "zone_turf": "zone_turf",
    "zone_turf_historical_result": "zone_turf",
    "zone_turf_horse_history": "zone_turf",
    "zone_turf_race_detail": "zone_turf",
}


@dataclass
class P0QueueItem:
    profile_id: int
    profile: HorseProfile
    region: str
    reasons: list[str] = field(default_factory=list)
    source_ids: list[int] = field(default_factory=list)


@dataclass
class FullProfileEvaluation:
    profile_id: int
    is_complete: bool
    blocking_reasons: list[str]
    missing_fields: list[str]


def _source_language_for_region(region: str) -> str:
    return SourceLanguage.JAPANESE if region == RacingRegion.JAPAN else SourceLanguage.ENGLISH


def _source_url_from_payload(*payloads: dict | None) -> str:
    def first_http_url(value: Any) -> str:
        if isinstance(value, str):
            candidate = value.strip()
            parsed = urlparse(candidate)
            return candidate if parsed.scheme in {"http", "https"} and parsed.netloc else ""
        if isinstance(value, dict):
            for key in (
                "primary",
                "source_url",
                "url",
                "official",
                "result",
                "runner",
                "profile",
                "horse_profile_url",
                "detail_url",
            ):
                candidate = first_http_url(value.get(key))
                if candidate:
                    return candidate
            for nested in value.values():
                candidate = first_http_url(nested)
                if candidate:
                    return candidate
        if isinstance(value, (list, tuple)):
            for nested in value:
                candidate = first_http_url(nested)
                if candidate:
                    return candidate
        return ""

    for payload in payloads:
        candidate = first_http_url(payload)
        if candidate:
            return candidate
    return ""


def _display_snapshot_from_term(term: TermEntry) -> dict[str, str]:
    return {
        "display_name_zh": term.target_zh if term.has_translation else "",
        "original_name": term.source_ja,
        "english_name": term.source_ja if term.source_language == SourceLanguage.ENGLISH else "",
        "japanese_name": term.source_ja if term.source_language == SourceLanguage.JAPANESE else "",
        "racing_region": term.racing_region or RacingRegion.JAPAN,
    }


def _normalized_regions(regions: Iterable[str] | None) -> list[str]:
    region_list = list(dict.fromkeys(regions or sorted(P0_REGIONS)))
    invalid_regions = sorted(set(region_list) - P0_REGIONS)
    if invalid_regions:
        raise ValueError(
            f"P0 horse profiles only support these regions: {', '.join(sorted(P0_REGIONS))}; "
            f"invalid: {', '.join(invalid_regions)}"
        )
    return region_list


def _profile_identity_keys(profile: HorseProfile) -> set[str]:
    refs = profile.source_refs if isinstance(profile.source_refs, dict) else {}
    values = refs.get("horse_identity_keys", [])
    if isinstance(values, str):
        values = [values]
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def _identity_index() -> dict[str, set[int]]:
    index: dict[str, set[int]] = {}
    for profile in HorseProfile.objects.only("id", "source_refs"):
        for key in _profile_identity_keys(profile):
            index.setdefault(key, set()).add(profile.id)
    return index


def _matched_identity_profile_ids(identity_keys: set[str], identity_index: dict[str, set[int]]) -> set[int]:
    matched_profile_ids: set[int] = set()
    for key in identity_keys:
        matched_profile_ids.update(identity_index.get(key, set()))
    return matched_profile_ids


def _source_namespace(*payloads: dict | None) -> str:
    generic_fallback = ""

    def find_namespace(value: Any) -> str:
        nonlocal generic_fallback
        if isinstance(value, dict):
            for key in (
                "source_key",
                "source_kind",
                "provider",
                "adapter",
                "source_name",
                "source",
            ):
                candidate = str(value.get(key) or "").strip().casefold()
                if candidate in GENERIC_SOURCE_NAMESPACES:
                    generic_fallback = generic_fallback or candidate
                    continue
                if candidate:
                    return SOURCE_NAMESPACE_ALIASES.get(candidate, candidate)
            for nested in value.values():
                candidate = find_namespace(nested)
                if candidate:
                    return candidate
        if isinstance(value, (list, tuple)):
            for nested in value:
                candidate = find_namespace(nested)
                if candidate:
                    return candidate
        return ""

    for payload in payloads:
        namespace = find_namespace(payload)
        if namespace:
            return namespace
    source_url = _source_url_from_payload(*payloads)
    hostname = (urlparse(source_url).hostname or "").strip().casefold().removeprefix("www.")
    domain_namespaces = {
        "equibase.com": "equibase",
        "france-galop.com": "france_galop",
        "geny.com": "geny",
        "hkjc.com": "hkjc",
        "horseracingnation.com": "horse_racing_nation",
        "irishracing.com": "irishracing",
        "jbis.or.jp": "jbis",
        "jra.go.jp": "jra",
        "keiba.go.jp": "keiba_go_jp",
        "nationalsteeplechase.com": "nsa",
        "netkeiba.com": "netkeiba",
        "racingpost.com": "racing_post",
        "sportinglife.com": "sporting_life",
        "zeturf.fr": "zeturf",
        "zone-turf.fr": "zone_turf",
    }
    for domain, namespace in domain_namespaces.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return namespace
    return generic_fallback or hostname


def _participant_identity_keys(*payloads: dict | None) -> set[str]:
    fallback_namespace = _source_namespace(*payloads)
    identity_keys: set[str] = set()
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        namespace = _source_namespace(payload) or fallback_namespace
        if (
            namespace in GENERIC_SOURCE_NAMESPACES
            and fallback_namespace
            and fallback_namespace not in GENERIC_SOURCE_NAMESPACES
        ):
            namespace = fallback_namespace
        if not namespace:
            continue
        for key in ("external_horse_id", "horse_id", "horseId", "id_horse"):
            value = str(payload.get(key) or "").strip()
            if value:
                identity_keys.add(f"{namespace}:{value}".casefold())
    return identity_keys


def _runner_external_identity_key(
    runner: RaceEventRunner | None,
    event: RaceEvent,
) -> str:
    if runner is None:
        return ""
    external_runner_id = str(
        runner.external_runner_id or ""
    ).strip()
    if not external_runner_id:
        return ""
    namespace = _source_namespace(
        runner.source_refs,
        runner.raw_payload,
        event.source_refs,
    )
    if not namespace:
        namespace = "race_event_runner"
    return f"{namespace}:{external_runner_id}".casefold()


def _external_runner_identity_keys(
    *payloads: dict | None,
) -> set[str]:
    fallback_namespace = _source_namespace(*payloads)
    identity_keys: set[str] = set()
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        namespace = _source_namespace(payload) or fallback_namespace
        if not namespace:
            continue
        external_runner_id = str(
            payload.get("external_runner_id") or ""
        ).strip()
        if external_runner_id:
            identity_keys.add(
                f"{namespace}:{external_runner_id}".casefold()
            )
    return identity_keys


def _participant_external_runner_identity_keys(
    *,
    runner: RaceEventRunner | None,
    result: RaceEventResult | None,
    event: RaceEvent,
) -> set[str]:
    identity_keys = _external_runner_identity_keys(
        result.source_refs if result else None,
        result.raw_payload if result else None,
        runner.source_refs if runner else None,
        runner.raw_payload if runner else None,
        event.source_refs,
    )
    runner_key = _runner_external_identity_key(runner, event)
    if runner_key:
        identity_keys.add(runner_key)
    return identity_keys


def _participant_record_identity_keys(
    *,
    runner: RaceEventRunner | None,
    result: RaceEventResult | None,
    event: RaceEvent,
) -> set[str]:
    identity_keys = _participant_identity_keys(
        result.source_refs if result else None,
        result.raw_payload if result else None,
        runner.source_refs if runner else None,
        runner.raw_payload if runner else None,
        event.source_refs,
    )
    identity_keys.update(
        _participant_external_runner_identity_keys(
            runner=runner,
            result=result,
            event=event,
        )
    )
    return identity_keys


def _normalized_horse_number(value: Any) -> str:
    horse_number = str(value or "").strip()
    if horse_number:
        return str(int(horse_number)) if horse_number.isdigit() else horse_number.casefold()
    return ""


def _record_identity_keys(record: RaceEventRunner | RaceEventResult, event: RaceEvent) -> set[str]:
    return _participant_record_identity_keys(
        runner=record if isinstance(record, RaceEventRunner) else None,
        result=record if isinstance(record, RaceEventResult) else None,
        event=event,
    )


def _participant_key(
    *,
    runner: RaceEventRunner | None,
    result: RaceEventResult | None,
    event: RaceEvent,
    name_is_unique: bool,
) -> str:
    external_runner_identity_keys = (
        _participant_external_runner_identity_keys(
            runner=runner,
            result=result,
            event=event,
        )
    )
    if external_runner_identity_keys:
        digest = hashlib.sha256(
            "|".join(
                sorted(external_runner_identity_keys)
            ).encode("utf-8")
        ).hexdigest()
        return f"identity:{digest}"
    horse_number = _normalized_horse_number(
        (result.horse_number if result else "") or (runner.horse_number if runner else "")
    )
    if horse_number:
        return f"number:{horse_number}"
    identity_keys = _participant_identity_keys(
        result.source_refs if result else None,
        result.raw_payload if result else None,
        runner.source_refs if runner else None,
        runner.raw_payload if runner else None,
        event.source_refs,
    )
    if identity_keys:
        digest = hashlib.sha256("|".join(sorted(identity_keys)).encode("utf-8")).hexdigest()
        return f"identity:{digest}"
    name = ((result.horse_name if result else "") or (runner.horse_name if runner else "")).strip()
    if name_is_unique:
        return f"name:{_normalize_identity_name(name)}"
    if runner:
        return f"runner:{runner.pk}"
    return f"result:{result.pk}"


def _event_participants(event: RaceEvent) -> list[dict[str, Any]]:
    runners = [runner for runner in event.runners.all() if (runner.horse_name or "").strip()]
    results = [result for result in event.results.all() if (result.horse_name or "").strip()]
    participants = [{"runner": runner, "result": None} for runner in runners]

    def unmatched_indexes() -> list[int]:
        return [index for index, participant in enumerate(participants) if participant["result"] is None]

    for result in results:
        candidates: list[int] = []
        result_number = _normalized_horse_number(result.horse_number)
        if result_number:
            candidates = [
                index
                for index in unmatched_indexes()
                if _normalized_horse_number(participants[index]["runner"].horse_number) == result_number
            ]
        if len(candidates) != 1:
            result_identities = _record_identity_keys(result, event)
            candidates = (
                [
                    index
                    for index in unmatched_indexes()
                    if result_identities & _record_identity_keys(participants[index]["runner"], event)
                ]
                if result_identities
                else []
            )
            if len(candidates) == 1:
                runner = participants[candidates[0]]["runner"]
                runner_number = _normalized_horse_number(runner.horse_number)
                if result_number and runner_number and result_number != runner_number:
                    participants[candidates[0]]["result"] = result
                    participants[candidates[0]]["pairing_conflict"] = {
                        "reason": "conflicting_horse_numbers",
                        "runner_number": runner_number,
                        "result_number": result_number,
                        "runner_id": runner.pk,
                        "result_id": result.pk,
                        "identity_keys": sorted(result_identities),
                    }
                    continue
        if len(candidates) != 1:
            result_name = _normalize_identity_name(result.horse_name)
            candidates = [
                index
                for index in unmatched_indexes()
                if _normalize_identity_name(participants[index]["runner"].horse_name) == result_name
                and (
                    not result_number
                    or not _normalized_horse_number(participants[index]["runner"].horse_number)
                )
            ]
        if len(candidates) == 1:
            participants[candidates[0]]["result"] = result
        else:
            participants.append({"runner": None, "result": result})

    identity_members: dict[str, list[int]] = {}
    participant_numbers: dict[int, str] = {}
    for index, participant in enumerate(participants):
        runner = participant["runner"]
        result = participant["result"]
        horse_number = _normalized_horse_number(
            (result.horse_number if result else "") or (runner.horse_number if runner else "")
        )
        if not horse_number:
            continue
        participant_numbers[index] = horse_number
        identity_keys = _participant_record_identity_keys(
            runner=runner,
            result=result,
            event=event,
        )
        for identity_key in identity_keys:
            identity_members.setdefault(identity_key, []).append(index)

    parent = {index: index for indexes in identity_members.values() for index in indexes}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for member_indexes in identity_members.values():
        unique_indexes = list(dict.fromkeys(member_indexes))
        for member_index in unique_indexes[1:]:
            union(unique_indexes[0], member_index)

    connected_members: dict[int, list[int]] = {}
    for index in parent:
        connected_members.setdefault(find(index), []).append(index)

    merged_indexes: set[int] = set()
    for member_indexes in connected_members.values():
        member_indexes = sorted(member_indexes)
        horse_numbers = sorted({participant_numbers[index] for index in member_indexes})
        if len(horse_numbers) <= 1:
            continue
        component_identity_keys = sorted(
            identity_key
            for identity_key, indexes in identity_members.items()
            if set(indexes) & set(member_indexes)
        )
        primary_index = member_indexes[0]
        conflict_members = [participants[index] for index in member_indexes]
        participants[primary_index]["pairing_conflict"] = {
            "reason": "same_source_identity_multiple_horse_numbers",
            "identity_key": component_identity_keys[0],
            "identity_keys": component_identity_keys,
            "horse_numbers": horse_numbers,
            "runner_ids": sorted(
                member["runner"].pk for member in conflict_members if member["runner"] is not None
            ),
            "result_ids": sorted(
                member["result"].pk for member in conflict_members if member["result"] is not None
            ),
        }
        participants[primary_index]["conflict_members"] = conflict_members
        merged_indexes.update(member_indexes[1:])
    if merged_indexes:
        participants = [participant for index, participant in enumerate(participants) if index not in merged_indexes]

    for participant in participants:
        pairing_conflict = participant.get("pairing_conflict")
        if not pairing_conflict:
            continue
        conflict_members = participant.get("conflict_members")
        if not conflict_members:
            conflict_members = []
            if participant.get("runner") is not None:
                conflict_members.append({"runner": participant["runner"], "result": None})
            if participant.get("result") is not None:
                conflict_members.append({"runner": None, "result": participant["result"]})
            participant["conflict_members"] = conflict_members
        member_evidence = []
        source_urls = []
        horse_numbers = set(pairing_conflict.get("horse_numbers") or [])
        for member in conflict_members:
            runner = member.get("runner")
            result = member.get("result")
            horse_number = _normalized_horse_number(
                (result.horse_number if result else "") or (runner.horse_number if runner else "")
            )
            source_url = _source_url_from_payload(
                result.source_refs if result else None,
                result.raw_payload if result else None,
                runner.source_refs if runner else None,
                runner.raw_payload if runner else None,
            )
            if horse_number:
                horse_numbers.add(horse_number)
            if source_url and source_url not in source_urls:
                source_urls.append(source_url)
            member_evidence.append(
                {
                    "horse_number": horse_number,
                    "horse_name": (
                        (result.horse_name if result else "") or (runner.horse_name if runner else "")
                    ),
                    "runner_id": runner.pk if runner else None,
                    "result_id": result.pk if result else None,
                    "source_url": source_url,
                }
            )
        pairing_conflict["horse_numbers"] = sorted(horse_numbers)
        pairing_conflict["members"] = member_evidence
        pairing_conflict["source_urls"] = source_urls

    name_counts: dict[str, int] = {}
    for participant in participants:
        name = (
            (participant["result"].horse_name if participant["result"] else "")
            or (participant["runner"].horse_name if participant["runner"] else "")
        )
        normalized_name = _normalize_identity_name(name)
        name_counts[normalized_name] = name_counts.get(normalized_name, 0) + 1
    for participant in participants:
        runner = participant["runner"]
        result = participant["result"]
        name = ((result.horse_name if result else "") or (runner.horse_name if runner else "")).strip()
        participant["name"] = name
        participant["participant_key"] = _participant_key(
            runner=runner,
            result=result,
            event=event,
            name_is_unique=name_counts.get(_normalize_identity_name(name), 0) == 1,
        )
    return participants


def _source_participant_identity_keys(source: HorseP0Source) -> set[str]:
    evidence = source.evidence_payload if isinstance(source.evidence_payload, dict) else {}
    values = evidence.get("horse_identity_keys") or []
    if isinstance(values, str):
        values = [values]
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def _resolved_conflict_member(participant: dict[str, Any], horse_number: str) -> dict[str, Any] | None:
    normalized_number = _normalized_horse_number(horse_number)
    for member in participant.get("conflict_members") or []:
        runner = member.get("runner")
        result = member.get("result")
        member_number = _normalized_horse_number(
            (result.horse_number if result else "") or (runner.horse_number if runner else "")
        )
        if member_number == normalized_number:
            return member
    return None


def _matching_participant_sources(
    sources: Iterable[HorseP0Source],
    *,
    participant_key: str,
    runner: RaceEventRunner | None,
    result: RaceEventResult | None,
    identity_keys: set[str],
) -> list[HorseP0Source]:
    matches: dict[int, HorseP0Source] = {}
    for source in sources:
        if source.status != HorseP0SourceStatus.ACTIVE:
            continue
        if source.participant_key == participant_key:
            matches[source.id] = source
            continue
        if result and source.race_result_id == result.id:
            matches[source.id] = source
            continue
        if runner and source.race_runner_id == runner.id:
            matches[source.id] = source
            continue
        if identity_keys and identity_keys & _source_participant_identity_keys(source):
            source_number = (
                source.participant_key.removeprefix("number:")
                if source.participant_key.startswith("number:")
                else ""
            )
            incoming_number = (
                participant_key.removeprefix("number:")
                if participant_key.startswith("number:")
                else ""
            )
            if source_number and incoming_number and source_number != incoming_number:
                continue
            matches[source.id] = source
    return sorted(matches.values(), key=lambda source: (source.observed_at, source.id), reverse=True)


def _normalize_identity_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _term_identity_names(term: TermEntry) -> set[str]:
    values = {
        term.source_ja,
        term.target_zh,
        *(term.aliases_ja or []),
        *(term.aliases_zh or []),
    }
    values.update(alias.text for alias in term.source_aliases.all() if alias.is_active)
    return {_normalize_identity_name(value) for value in values if _normalize_identity_name(value)}


def _horse_name_identity_index() -> dict[str, set[int]]:
    index: dict[str, set[int]] = {}
    terms = TermEntry.objects.filter(term_type=TermType.HORSE, is_active=True).prefetch_related("source_aliases")
    for term in terms:
        for name in _term_identity_names(term):
            index.setdefault(name, set()).add(term.id)
    return index


def _payload_value(payloads: Iterable[dict | None], keys: tuple[str, ...]) -> Any:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
    return None


def _participant_pedigree_identity(*payloads: dict | None) -> tuple[str, str, int | None]:
    payload_list = list(payloads)
    sire_name = str(_payload_value(payload_list, ("sire_name", "father_name", "sire", "father")) or "").strip()
    dam_name = str(_payload_value(payload_list, ("dam_name", "mother_name", "dam", "mother")) or "").strip()
    birth_year_value = _payload_value(payload_list, ("birth_year", "year_of_birth"))
    if birth_year_value in (None, ""):
        birth_date_value = str(_payload_value(payload_list, ("birth_date", "date_of_birth")) or "")
        birth_year_value = birth_date_value[:4] if len(birth_date_value) >= 4 else None
    try:
        birth_year = int(birth_year_value) if birth_year_value not in (None, "") else None
    except (TypeError, ValueError):
        birth_year = None
    return sire_name, dam_name, birth_year


def _identity_name_matches(
    incoming_name: str,
    *,
    profile_text: str,
    profile_term: TermEntry | None,
    name_index: dict[str, set[int]],
) -> bool:
    incoming_normalized = _normalize_identity_name(incoming_name)
    if not incoming_normalized:
        return False
    if incoming_normalized == _normalize_identity_name(profile_text):
        return True
    incoming_term_ids = name_index.get(incoming_normalized, set())
    if profile_term and profile_term.id in incoming_term_ids:
        return True
    if profile_term and incoming_normalized in _term_identity_names(profile_term):
        return True
    profile_text_term_ids = name_index.get(_normalize_identity_name(profile_text), set())
    return bool(incoming_term_ids & profile_text_term_ids)


def _matched_pedigree_identity_profile_ids(
    *,
    horse_name: str,
    sire_name: str,
    dam_name: str,
    birth_year: int | None,
    name_index: dict[str, set[int]],
) -> set[int]:
    if not all((horse_name, sire_name, dam_name, birth_year)):
        return set()
    horse_term_ids = name_index.get(_normalize_identity_name(horse_name), set())
    queryset = HorseProfile.objects.select_related("primary_term", "sire_term", "dam_term").filter(
        birth_date__year=birth_year
    )
    if horse_term_ids:
        queryset = queryset.filter(primary_term_id__in=horse_term_ids)
    else:
        queryset = queryset.filter(
            Q(original_name__iexact=horse_name)
            | Q(english_name__iexact=horse_name)
            | Q(japanese_name__iexact=horse_name)
            | Q(display_name_zh__iexact=horse_name)
        )
    matched: set[int] = set()
    for profile in queryset:
        if not _identity_name_matches(
            sire_name,
            profile_text=profile.sire_text,
            profile_term=profile.sire_term,
            name_index=name_index,
        ):
            continue
        if not _identity_name_matches(
            dam_name,
            profile_text=profile.dam_text,
            profile_term=profile.dam_term,
            name_index=name_index,
        ):
            continue
        matched.add(profile.id)
    return matched


def _matching_name_profiles(horse_name: str, name_index: dict[str, set[int]]) -> list[HorseProfile]:
    term_ids = name_index.get(_normalize_identity_name(horse_name), set())
    queryset = HorseProfile.objects.select_related("primary_term")
    if term_ids:
        return list(queryset.filter(primary_term_id__in=term_ids).order_by("id"))
    return list(
        queryset.filter(
            Q(original_name__iexact=horse_name)
            | Q(english_name__iexact=horse_name)
            | Q(japanese_name__iexact=horse_name)
            | Q(display_name_zh__iexact=horse_name)
        ).order_by("id")
    )


def _pedigree_profile_identity_index(
    name_index: dict[str, set[int]],
) -> dict[tuple[int, str], list[dict[str, Any]]]:
    term_names: dict[int, set[str]] = {}
    for normalized_name, term_ids in name_index.items():
        for term_id in term_ids:
            term_names.setdefault(term_id, set()).add(normalized_name)
    index: dict[tuple[int, str], list[dict[str, Any]]] = {}
    profiles = (
        HorseProfile.objects.filter(birth_date__isnull=False)
        .select_related("primary_term", "sire_term", "dam_term")
        .only(
            "id",
            "birth_date",
            "display_name_zh",
            "original_name",
            "english_name",
            "japanese_name",
            "primary_term_id",
            "sire_text",
            "sire_term_id",
            "dam_text",
            "dam_term_id",
        )
    )
    for profile in profiles.iterator(chunk_size=500):
        horse_names = {
            _normalize_identity_name(value)
            for value in (
                profile.display_name_zh,
                profile.original_name,
                profile.english_name,
                profile.japanese_name,
            )
            if _normalize_identity_name(value)
        }
        horse_names.update(term_names.get(profile.primary_term_id, set()))
        sire_names = {
            _normalize_identity_name(profile.sire_text)
        } if _normalize_identity_name(profile.sire_text) else set()
        dam_names = {
            _normalize_identity_name(profile.dam_text)
        } if _normalize_identity_name(profile.dam_text) else set()
        if profile.sire_term_id:
            sire_names.update(term_names.get(profile.sire_term_id, set()))
        if profile.dam_term_id:
            dam_names.update(term_names.get(profile.dam_term_id, set()))
        row = {
            "profile_id": profile.id,
            "sire_names": sire_names,
            "dam_names": dam_names,
        }
        for horse_name in horse_names:
            index.setdefault((profile.birth_date.year, horse_name), []).append(row)
    return index


def _matched_pedigree_profile_ids_from_index(
    *,
    horse_name: str,
    sire_name: str,
    dam_name: str,
    birth_year: int | None,
    pedigree_index: dict[tuple[int, str], list[dict[str, Any]]],
) -> set[int]:
    if not all((horse_name, sire_name, dam_name, birth_year)):
        return set()
    normalized_sire = _normalize_identity_name(sire_name)
    normalized_dam = _normalize_identity_name(dam_name)
    return {
        row["profile_id"]
        for row in pedigree_index.get(
            (int(birth_year), _normalize_identity_name(horse_name)),
            [],
        )
        if normalized_sire in row["sire_names"] and normalized_dam in row["dam_names"]
    }


def _record_identity_conflict(
    *,
    profiles: Iterable[HorseProfile],
    terms: Iterable[TermEntry],
    event: RaceEvent,
    horse_name: str,
    horse_number: str,
    source_url: str,
    identity_status: str,
    identity_keys: set[str],
    pedigree_identity: tuple[str, str, int | None],
    pairing_conflict: dict | None = None,
) -> HorseIdentityConflict:
    evidence = {
        "race_event_id": event.id,
        "horse_name": horse_name,
        "horse_number": horse_number,
        "identity_status": identity_status,
        "horse_identity_keys": sorted(identity_keys),
        "sire_name": pedigree_identity[0],
        "dam_name": pedigree_identity[1],
        "birth_year": pedigree_identity[2],
    }
    if pairing_conflict:
        evidence["pairing_conflict"] = pairing_conflict
    fingerprint_evidence = dict(evidence)
    if pairing_conflict:
        fingerprint_evidence["pairing_conflict"] = {
            key: pairing_conflict.get(key)
            for key in (
                "reason",
                "identity_key",
                "horse_numbers",
                "runner_ids",
                "result_ids",
                "runner_number",
                "result_number",
                "runner_id",
                "result_id",
                "identity_keys",
            )
            if pairing_conflict.get(key) not in (None, "", [])
        }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    conflict, created = HorseIdentityConflict.objects.get_or_create(
        fingerprint=fingerprint,
        defaults={
            "status": HorseIdentityConflictStatus.PENDING,
            "race_event": event,
            "horse_name": horse_name,
            "horse_number": horse_number,
            "source_url": source_url,
            "identity_keys": sorted(identity_keys),
            "sire_name": pedigree_identity[0],
            "dam_name": pedigree_identity[1],
            "birth_year": pedigree_identity[2],
            "evidence_payload": evidence,
        },
    )
    if not created:
        conflict.race_event = event
        conflict.horse_name = horse_name
        conflict.horse_number = horse_number
        conflict.source_url = source_url
        conflict.identity_keys = sorted(identity_keys)
        conflict.sire_name = pedigree_identity[0]
        conflict.dam_name = pedigree_identity[1]
        conflict.birth_year = pedigree_identity[2]
        conflict.evidence_payload = evidence
        conflict.observed_at = timezone.now()
        conflict.save(
            update_fields=[
                "race_event",
                "horse_name",
                "horse_number",
                "source_url",
                "identity_keys",
                "sire_name",
                "dam_name",
                "birth_year",
                "evidence_payload",
                "observed_at",
                "updated_at",
            ]
        )
    conflict.candidate_profiles.set(profiles)
    conflict.candidate_terms.set(terms)
    return conflict


def _remember_profile_identity_keys(
    profile: HorseProfile,
    identity_keys: set[str],
    identity_index: dict[str, set[int]],
) -> None:
    if not identity_keys:
        return
    existing = _profile_identity_keys(profile)
    merged = existing | identity_keys
    if merged != existing:
        source_refs = dict(profile.source_refs or {})
        source_refs["horse_identity_keys"] = sorted(merged)
        profile.source_refs = source_refs
        profile.save(update_fields=["source_refs", "updated_at"])
    for key in merged:
        identity_index.setdefault(key, set()).add(profile.id)


def _find_or_create_horse_term(
    *,
    horse_name: str,
    region: str,
    identity_keys: set[str],
    identity_index: dict[str, set[int]],
    name_index: dict[str, set[int]],
    distinct_event_participant: bool = False,
) -> tuple[TermEntry | None, bool, str]:
    source_language = _source_language_for_region(region)
    matched_profile_ids = _matched_identity_profile_ids(identity_keys, identity_index)
    if len(matched_profile_ids) == 1:
        profile = HorseProfile.objects.select_related("primary_term").get(pk=next(iter(matched_profile_ids)))
        return profile.primary_term, False, "matched_external_identity"
    if len(matched_profile_ids) > 1:
        return None, False, "ambiguous_external_identity"

    name_term_ids = name_index.get(_normalize_identity_name(horse_name), set())
    matches = list(
        TermEntry.objects.filter(term_type=TermType.HORSE, is_active=True, id__in=name_term_ids)
        .distinct()
        .order_by("-priority", "id")
    )
    if matches and not distinct_event_participant:
        matching_profiles = {
            profile.primary_term_id: profile
            for profile in HorseProfile.objects.filter(primary_term_id__in=[term.id for term in matches]).only(
                "id", "primary_term_id", "source_refs"
            )
        }
        matching_identity_sets = [
            _profile_identity_keys(matching_profiles[term.id])
            for term in matches
            if term.id in matching_profiles
        ]
        incoming_namespaces = {key.split(":", 1)[0] for key in identity_keys if ":" in key}
        all_name_matches_identified_by_same_source = (
            identity_keys
            and len(matching_identity_sets) == len(matches)
            and all(keys for keys in matching_identity_sets)
            and all(
                incoming_namespaces & {key.split(":", 1)[0] for key in keys if ":" in key}
                for keys in matching_identity_sets
            )
        )
        if not all_name_matches_identified_by_same_source:
            return None, False, "ambiguous_name_without_external_identity"
    term = TermEntry.objects.create(
        term_type=TermType.HORSE,
        source_language=source_language,
        racing_region=region,
        source_ja=horse_name,
        target_zh="",
        translation_status=TermTranslationStatus.PENDING,
        priority=0,
        is_active=True,
        notes="p0_major_race_participant_auto_created",
    )
    return term, True, "created_pending_identity"


def _find_or_create_profile_for_term(term: TermEntry) -> tuple[HorseProfile, bool]:
    try:
        return term.horse_profile, False
    except HorseProfile.DoesNotExist:
        profile = HorseProfile.objects.create(primary_term=term, **_display_snapshot_from_term(term))
        return profile, True


def _upsert_p0_source(
    *,
    profile: HorseProfile,
    source_type: str,
    term: TermEntry | None = None,
    race_event: RaceEvent | None = None,
    race_result: RaceEventResult | None = None,
    race_runner: RaceEventRunner | None = None,
    horse_name: str = "",
    participant_key: str = "",
    source_url: str = "",
    evidence_summary: str = "",
    evidence_payload: dict | None = None,
    racing_region: str = "",
    previous_sources: Iterable[HorseP0Source] = (),
) -> tuple[HorseP0Source, bool]:
    defaults = {
        "status": HorseP0SourceStatus.ACTIVE,
        "term": term,
        "race_result": race_result,
        "race_runner": race_runner,
        "racing_region": racing_region or (race_event.country_region if race_event else profile.racing_region),
        "race_grade": race_event.normalized_grade if race_event else "",
        "source_url": source_url,
        "evidence_summary": evidence_summary,
        "evidence_payload": evidence_payload or {},
        "observed_at": timezone.now(),
        "revoked_at": None,
        "revoked_reason": "",
    }
    if source_type == HorseP0SourceType.TERM_ACTIVE_WITH_ZH:
        source, created = HorseP0Source.objects.update_or_create(
            profile=profile,
            source_type=source_type,
            term=term,
            defaults=defaults,
        )
    elif source_type == HorseP0SourceType.MANUAL:
        source, created = HorseP0Source.objects.update_or_create(
            profile=profile,
            source_type=source_type,
            defaults={**defaults, "horse_name": horse_name},
        )
    else:
        active_source = HorseP0Source.objects.filter(
            source_type=source_type,
            race_event=race_event,
            participant_key=participant_key,
            status=HorseP0SourceStatus.ACTIVE,
        ).first()
        for previous_source in previous_sources:
            if active_source and previous_source.id == active_source.id:
                continue
            if previous_source.profile_id == profile.id and active_source is None:
                previous_source.participant_key = participant_key
                previous_source.save(update_fields=["participant_key", "updated_at"])
                active_source = previous_source
                continue
            previous_source.status = HorseP0SourceStatus.REVOKED
            previous_source.revoked_at = timezone.now()
            previous_source.revoked_reason = (
                "participant key was upgraded"
                if previous_source.profile_id == profile.id
                else "participant identity was corrected to another horse profile"
            )
            previous_source.save(update_fields=["status", "revoked_at", "revoked_reason", "updated_at"])
        if active_source and active_source.profile_id != profile.id:
            active_source.status = HorseP0SourceStatus.REVOKED
            active_source.revoked_at = timezone.now()
            active_source.revoked_reason = "participant identity was corrected to another horse profile"
            active_source.save(update_fields=["status", "revoked_at", "revoked_reason", "updated_at"])
        source, created = HorseP0Source.objects.update_or_create(
            source_type=source_type,
            race_event=race_event,
            participant_key=participant_key,
            status=HorseP0SourceStatus.ACTIVE,
            defaults={**defaults, "profile": profile, "horse_name": horse_name},
        )
    return source, created


def _reopen_identity_conflict(
    conflict: HorseIdentityConflict,
    *,
    reason: str,
) -> None:
    evidence_payload = dict(conflict.evidence_payload or {})
    evidence_payload["resolution_failure"] = {
        "reason": reason,
        "horse_number": conflict.resolved_horse_number,
        "observed_at": timezone.now().isoformat(),
    }
    conflict.status = HorseIdentityConflictStatus.PENDING
    conflict.resolved_profile = None
    conflict.resolved_horse_number = ""
    conflict.resolved_at = None
    conflict.resolved_by = None
    conflict.evidence_payload = evidence_payload
    conflict.save(
        update_fields=[
            "status",
            "resolved_profile",
            "resolved_horse_number",
            "resolved_at",
            "resolved_by",
            "evidence_payload",
            "updated_at",
        ]
    )


def sync_p0_horse_sources(
    *,
    commit: bool = False,
    regions: Iterable[str] | None = None,
    reconcile: bool = False,
) -> dict[str, Any]:
    scoped_regions = list(regions) if regions is not None else None
    region_list = _normalized_regions(scoped_regions)
    summary = {
        "created_profiles": 0,
        "created_terms": 0,
        "created_sources": 0,
        "updated_sources": 0,
        "term_sources": 0,
        "major_race_sources": 0,
        "ambiguous_participants": 0,
        "missing_source_url_participants": 0,
        "revoked_sources": 0,
    }
    if not commit:
        summary["dry_run"] = True
        term_candidates = TermEntry.objects.filter(term_type=TermType.HORSE, is_active=True).exclude(target_zh="")
        if scoped_regions is not None:
            term_candidates = term_candidates.filter(racing_region__in=region_list)
        summary["term_candidates"] = term_candidates.count()
        summary["major_race_candidates"] = _major_race_events(region_list).count()
        summary["reconcile"] = reconcile
        return summary

    with transaction.atomic():
        seen_managed_source_ids: set[int] = set()
        identity_index = _identity_index()
        name_index = _horse_name_identity_index()
        term_queryset = TermEntry.objects.select_for_update().filter(
            term_type=TermType.HORSE,
            is_active=True,
            translation_status=TermTranslationStatus.TRANSLATED,
        )
        if scoped_regions is not None:
            term_queryset = term_queryset.filter(racing_region__in=region_list)
        term_queryset = term_queryset.exclude(target_zh="").order_by("-priority", "id")
        for term in term_queryset:
            profile, profile_created = _find_or_create_profile_for_term(term)
            source, source_created = _upsert_p0_source(
                profile=profile,
                source_type=HorseP0SourceType.TERM_ACTIVE_WITH_ZH,
                term=term,
                horse_name=term.source_ja,
                source_url="",
                evidence_summary="active horse term with translated Chinese name",
                evidence_payload={"term_id": term.id, "target_zh": term.target_zh},
            )
            seen_managed_source_ids.add(source.id)
            summary["term_sources"] += 1
            summary["created_profiles"] += int(profile_created)
            summary["created_sources"] += int(source_created)
            summary["updated_sources"] += int(not source_created)

        for event in _major_race_events(region_list).prefetch_related("runners", "results"):
            event_sources = list(
                HorseP0Source.objects.select_for_update()
                .filter(
                    source_type=HorseP0SourceType.MAJOR_RACE_PARTICIPANT,
                    race_event=event,
                    status=HorseP0SourceStatus.ACTIVE,
                )
                .select_related("profile__primary_term")
                .order_by("-observed_at", "-id")
            )
            for participant in _event_participants(event):
                normalized_name = participant["name"]
                runner = participant["runner"]
                result = participant["result"]
                participant_key = participant["participant_key"]
                horse_number = str((result.horse_number if result else "") or (runner.horse_number if runner else "") or "").strip()
                source_url = _source_url_from_payload(
                    result.source_refs if result else None,
                    runner.source_refs if runner else None,
                    event.source_refs,
                )
                pairing_conflict = participant.get("pairing_conflict") or {}
                if not source_url:
                    source_url = next(iter(pairing_conflict.get("source_urls") or []), "")
                identity_keys = _participant_record_identity_keys(
                    runner=runner,
                    result=result,
                    event=event,
                )
                existing_sources = _matching_participant_sources(
                    event_sources,
                    participant_key=participant_key,
                    runner=runner,
                    result=result,
                    identity_keys=identity_keys,
                )
                if not source_url:
                    summary["missing_source_url_participants"] += 1
                    seen_managed_source_ids.update(source.id for source in existing_sources)
                    if not pairing_conflict:
                        continue
                pedigree_identity = _participant_pedigree_identity(
                    result.source_refs if result else None,
                    result.raw_payload if result else None,
                    runner.source_refs if runner else None,
                    runner.raw_payload if runner else None,
                    event.source_refs,
                )
                same_name_event_source_exists = HorseP0Source.objects.filter(
                    source_type=HorseP0SourceType.MAJOR_RACE_PARTICIPANT,
                    race_event=event,
                    horse_name__iexact=normalized_name,
                    status=HorseP0SourceStatus.ACTIVE,
                ).exclude(participant_key=participant_key).exists()
                name_profiles = _matching_name_profiles(normalized_name, name_index)
                matched_profile_ids = _matched_identity_profile_ids(identity_keys, identity_index)
                pedigree_profile_ids = _matched_pedigree_identity_profile_ids(
                    horse_name=normalized_name,
                    sire_name=pedigree_identity[0],
                    dam_name=pedigree_identity[1],
                    birth_year=pedigree_identity[2],
                    name_index=name_index,
                )
                if pairing_conflict:
                    term = None
                    term_created = False
                    identity_status = "conflicting_horse_numbers"
                elif len(matched_profile_ids) > 1:
                    term = None
                    term_created = False
                    identity_status = "ambiguous_external_identity"
                elif len(matched_profile_ids) == 1:
                    matched_profile = HorseProfile.objects.select_related("primary_term").get(
                        pk=next(iter(matched_profile_ids))
                    )
                    term = matched_profile.primary_term
                    term_created = False
                    identity_status = "matched_external_identity"
                elif len(pedigree_profile_ids) > 1:
                    term = None
                    term_created = False
                    identity_status = "ambiguous_pedigree_identity"
                elif len(pedigree_profile_ids) == 1:
                    matched_profile = HorseProfile.objects.select_related("primary_term").get(
                        pk=next(iter(pedigree_profile_ids))
                    )
                    term = matched_profile.primary_term
                    term_created = False
                    identity_status = "matched_name_sire_dam_birth_year"
                elif len(existing_sources) == 1 and (
                    not identity_keys or not _profile_identity_keys(existing_sources[0].profile)
                ) and (len(name_profiles) <= 1 or same_name_event_source_exists):
                    term = existing_sources[0].profile.primary_term
                    term_created = False
                    identity_status = "matched_existing_event_source"
                elif (
                    (len(existing_sources) > 1 or len(name_profiles) > 1)
                    and not identity_keys
                    and not same_name_event_source_exists
                ):
                    term = None
                    term_created = False
                    identity_status = "ambiguous_same_name_profiles"
                else:
                    term, term_created, identity_status = _find_or_create_horse_term(
                        horse_name=normalized_name,
                        region=event.country_region,
                        identity_keys=identity_keys,
                        identity_index=identity_index,
                        name_index=name_index,
                        distinct_event_participant=same_name_event_source_exists,
                    )
                if term is None:
                    summary["ambiguous_participants"] += 1
                    seen_managed_source_ids.update(source.id for source in existing_sources)
                    conflict_profiles = {profile.id: profile for profile in name_profiles}
                    conflict_profiles.update({source.profile_id: source.profile for source in existing_sources})
                    unresolved_profile_ids = matched_profile_ids | pedigree_profile_ids
                    if unresolved_profile_ids:
                        conflict_profiles.update(
                            {
                                profile.id: profile
                                for profile in HorseProfile.objects.filter(id__in=unresolved_profile_ids)
                            }
                        )
                    conflict_term_ids = set(name_index.get(_normalize_identity_name(normalized_name), set()))
                    conflict_term_ids.update(profile.primary_term_id for profile in conflict_profiles.values())
                    conflict = _record_identity_conflict(
                        profiles=conflict_profiles.values(),
                        terms=TermEntry.objects.filter(id__in=conflict_term_ids),
                        event=event,
                        horse_name=normalized_name,
                        horse_number=horse_number,
                        source_url=source_url,
                        identity_status=identity_status,
                        identity_keys=identity_keys,
                        pedigree_identity=pedigree_identity,
                        pairing_conflict=pairing_conflict,
                    )
                    if (
                        conflict.status == HorseIdentityConflictStatus.RESOLVED
                        and conflict.resolved_profile_id
                    ):
                        if pairing_conflict:
                            selected_member = _resolved_conflict_member(
                                participant,
                                conflict.resolved_horse_number,
                            )
                            if selected_member is None:
                                _reopen_identity_conflict(
                                    conflict,
                                    reason="resolved_member_missing",
                                )
                                continue
                            runner = selected_member.get("runner")
                            result = selected_member.get("result")
                            normalized_name = (
                                (result.horse_name if result else "")
                                or (runner.horse_name if runner else "")
                            ).strip()
                            horse_number = conflict.resolved_horse_number
                            participant_key = f"number:{_normalized_horse_number(horse_number)}"
                            source_url = _source_url_from_payload(
                                result.source_refs if result else None,
                                result.raw_payload if result else None,
                                runner.source_refs if runner else None,
                                runner.raw_payload if runner else None,
                                event.source_refs,
                            )
                            if not source_url:
                                _reopen_identity_conflict(
                                    conflict,
                                    reason="resolved_member_missing_source_url",
                                )
                                continue
                            identity_keys = _participant_identity_keys(
                                result.source_refs if result else None,
                                result.raw_payload if result else None,
                                runner.source_refs if runner else None,
                                runner.raw_payload if runner else None,
                                event.source_refs,
                            )
                            existing_sources = _matching_participant_sources(
                                event_sources,
                                participant_key=participant_key,
                                runner=runner,
                                result=result,
                                identity_keys=identity_keys,
                            )
                        profile = HorseProfile.objects.select_related("primary_term").get(
                            pk=conflict.resolved_profile_id
                        )
                        term = profile.primary_term
                        term_created = False
                        identity_status = "matched_resolved_identity_conflict"
                    else:
                        continue
                profile, profile_created = _find_or_create_profile_for_term(term)
                _remember_profile_identity_keys(profile, identity_keys, identity_index)
                source, source_created = _upsert_p0_source(
                    profile=profile,
                    source_type=HorseP0SourceType.MAJOR_RACE_PARTICIPANT,
                    term=term,
                    race_event=event,
                    race_result=result,
                    race_runner=runner,
                    horse_name=normalized_name,
                    participant_key=participant_key,
                    source_url=source_url,
                    evidence_summary=f"{event.original_name} {event.year} {event.normalized_grade}",
                    evidence_payload={
                        "race_event_id": event.id,
                        "race_result_id": result.id if result else None,
                        "race_runner_id": runner.id if runner else None,
                        "horse_number": horse_number,
                        "finish_position": result.finish_position if result else None,
                        "identity_status": identity_status,
                        "horse_identity_keys": sorted(identity_keys),
                    },
                    racing_region=event.country_region,
                    previous_sources=existing_sources,
                )
                if source not in event_sources:
                    event_sources.append(source)
                seen_managed_source_ids.add(source.id)
                summary["major_race_sources"] += 1
                summary["created_terms"] += int(term_created)
                if term_created:
                    name_index.setdefault(_normalize_identity_name(normalized_name), set()).add(term.id)
                summary["created_profiles"] += int(profile_created)
                summary["created_sources"] += int(source_created)
                summary["updated_sources"] += int(not source_created)
        if reconcile:
            stale_sources = HorseP0Source.objects.filter(
                source_type__in=(HorseP0SourceType.TERM_ACTIVE_WITH_ZH, HorseP0SourceType.MAJOR_RACE_PARTICIPANT),
                status=HorseP0SourceStatus.ACTIVE,
                racing_region__in=region_list,
            ).exclude(pk__in=seen_managed_source_ids)
            summary["revoked_sources"] = stale_sources.update(
                status=HorseP0SourceStatus.REVOKED,
                revoked_at=timezone.now(),
                revoked_reason="P0 source no longer present in the latest complete synchronization",
                updated_at=timezone.now(),
            )
    summary["reconcile"] = reconcile
    return summary


def _major_race_events(regions: Iterable[str] | None = None):
    return RaceEvent.objects.filter(
        country_region__in=_normalized_regions(regions),
        normalized_grade__in=P0_MAJOR_RACE_GRADES,
    ).order_by(
        "country_region",
        "local_date",
        "id",
    )


def _candidate_identity(
    *,
    event: RaceEvent,
    participant: dict[str, Any],
    identity_index: dict[str, set[int]],
    pedigree_index: dict[tuple[int, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    runner = participant["runner"]
    result = participant["result"]
    horse_name = participant["name"]
    payloads = (
        result.source_refs if result else None,
        result.raw_payload if result else None,
        runner.source_refs if runner else None,
        runner.raw_payload if runner else None,
        event.source_refs,
    )
    identity_keys = _participant_identity_keys(*payloads)
    pedigree_identity = _participant_pedigree_identity(*payloads)
    matched_profile_ids = _matched_identity_profile_ids(identity_keys, identity_index)
    pedigree_profile_ids = _matched_pedigree_profile_ids_from_index(
        horse_name=horse_name,
        sire_name=pedigree_identity[0],
        dam_name=pedigree_identity[1],
        birth_year=pedigree_identity[2],
        pedigree_index=pedigree_index,
    )
    profile_ids = matched_profile_ids | pedigree_profile_ids
    pairing_conflict = participant.get("pairing_conflict") or {}
    if pairing_conflict:
        identity_status = "runner_result_pairing_conflict"
        candidate_key = f"conflict:event:{event.id}:{participant['participant_key']}"
    elif len(matched_profile_ids) > 1:
        identity_status = "external_identity_conflict"
        digest = hashlib.sha256("|".join(sorted(identity_keys)).encode("utf-8")).hexdigest()
        candidate_key = f"conflict:external:{digest}"
    elif len(pedigree_profile_ids) > 1:
        identity_status = "pedigree_identity_conflict"
        candidate_key = f"conflict:pedigree:{event.id}:{participant['participant_key']}"
    elif (
        matched_profile_ids
        and pedigree_profile_ids
        and matched_profile_ids != pedigree_profile_ids
    ):
        identity_status = "external_pedigree_identity_conflict"
        candidate_key = f"conflict:evidence:{event.id}:{participant['participant_key']}"
    elif len(profile_ids) == 1:
        identity_status = (
            "matched_existing_profile_multiple_evidence"
            if matched_profile_ids and pedigree_profile_ids
            else "matched_existing_profile_external"
            if matched_profile_ids
            else "matched_existing_profile_pedigree"
        )
        candidate_key = f"profile:{next(iter(profile_ids))}"
    elif identity_keys:
        identity_status = "strong_external_identity"
        digest = hashlib.sha256("|".join(sorted(identity_keys)).encode("utf-8")).hexdigest()
        candidate_key = f"external:{digest}"
    elif all((horse_name, pedigree_identity[0], pedigree_identity[1], pedigree_identity[2])):
        identity_status = "strong_pedigree_identity"
        raw_key = "|".join(
            (
                _normalize_identity_name(horse_name),
                _normalize_identity_name(pedigree_identity[0]),
                _normalize_identity_name(pedigree_identity[1]),
                str(pedigree_identity[2]),
            )
        )
        candidate_key = f"pedigree:{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()}"
    else:
        # A name is not a horse identity. Keep weak observations separate until
        # a profile source supplies an external ID or full pedigree identity.
        identity_status = "needs_identity_enrichment"
        candidate_key = f"observation:event:{event.id}:{participant['participant_key']}"
    pedigree_key = ""
    if all((horse_name, pedigree_identity[0], pedigree_identity[1], pedigree_identity[2])):
        pedigree_key = "|".join(
            (
                _normalize_identity_name(horse_name),
                _normalize_identity_name(pedigree_identity[0]),
                _normalize_identity_name(pedigree_identity[1]),
                str(pedigree_identity[2]),
            )
        )
    return {
        "candidate_key": candidate_key,
        "identity_status": identity_status,
        "identity_keys": sorted(identity_keys),
        "matched_profile_ids": sorted(profile_ids),
        "sire_name": pedigree_identity[0],
        "dam_name": pedigree_identity[1],
        "birth_year": pedigree_identity[2],
        "pedigree_key": pedigree_key,
        "pairing_conflict": pairing_conflict,
        "source_namespace": _source_namespace(*payloads),
        "source_url": _source_url_from_payload(*payloads),
    }


def _canonicalize_candidate_identities(identities: list[dict[str, Any]]) -> None:
    parents: dict[str, str] = {}

    def find(token: str) -> str:
        parents.setdefault(token, token)
        if parents[token] != token:
            parents[token] = find(parents[token])
        return parents[token]

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    identity_tokens: list[list[str]] = []
    for identity in identities:
        identity["direct_identity_status"] = identity["identity_status"]
        if identity["pairing_conflict"]:
            identity_tokens.append([])
            continue
        tokens = [
            *(f"external:{key}" for key in identity["identity_keys"]),
            *(f"profile:{profile_id}" for profile_id in identity["matched_profile_ids"]),
        ]
        if identity["pedigree_key"]:
            pedigree_digest = hashlib.sha256(
                identity["pedigree_key"].encode("utf-8")
            ).hexdigest()
            tokens.append(f"pedigree:{pedigree_digest}")
        identity_tokens.append(tokens)
        for token in tokens:
            find(token)
        for token in tokens[1:]:
            union(tokens[0], token)

    components: dict[str, set[str]] = {}
    for token in parents:
        components.setdefault(find(token), set()).add(token)

    for identity, tokens in zip(identities, identity_tokens):
        if not tokens:
            continue
        component = components[find(tokens[0])]
        external_keys = sorted(
            token.removeprefix("external:")
            for token in component
            if token.startswith("external:")
        )
        profile_ids = sorted(
            int(token.removeprefix("profile:"))
            for token in component
            if token.startswith("profile:")
        )
        pedigree_tokens = sorted(
            token for token in component if token.startswith("pedigree:")
        )
        identity["identity_keys"] = external_keys
        identity["matched_profile_ids"] = profile_ids
        component_digest = hashlib.sha256(
            "|".join(sorted(component)).encode("utf-8")
        ).hexdigest()
        if len(profile_ids) > 1 or len(pedigree_tokens) > 1:
            identity["identity_status"] = (
                identity["direct_identity_status"]
                if "conflict" in identity["direct_identity_status"]
                else "connected_identity_evidence_conflict"
            )
            identity["candidate_key"] = f"conflict:component:{component_digest}"
        elif profile_ids:
            profile_id = profile_ids[0]
            if external_keys and pedigree_tokens:
                identity["identity_status"] = "matched_existing_profile_multiple_evidence"
            elif external_keys:
                identity["identity_status"] = "matched_existing_profile_external"
            else:
                identity["identity_status"] = "matched_existing_profile_pedigree"
            identity["candidate_key"] = f"profile:{profile_id}"
        elif external_keys:
            identity["identity_status"] = "strong_external_identity"
            identity["candidate_key"] = f"external:{component_digest}"
        else:
            identity["identity_status"] = "strong_pedigree_identity"
            identity["candidate_key"] = pedigree_tokens[0]


def _identity_name_evidence_key(
    value: str,
    name_index: dict[str, set[int]],
) -> tuple[str, tuple[int, ...] | str] | None:
    normalized = _normalize_identity_name(value)
    if not normalized:
        return None
    term_ids = tuple(sorted(name_index.get(normalized, set())))
    return ("term", term_ids) if term_ids else ("text", normalized)


def _participant_observation(
    *,
    event: RaceEvent,
    participant: dict[str, Any],
    identity: dict[str, Any],
) -> dict[str, Any]:
    runner = participant["runner"]
    result = participant["result"]
    runner_status = str(runner.running_status if runner else "")
    result_status = str(result.running_status if result else "")
    nonstarter_statuses = {RaceRunnerStatus.SCRATCHED, RaceRunnerStatus.WITHDRAWN}
    if result_status in nonstarter_statuses or runner_status in nonstarter_statuses:
        participation_status = "nonstarter"
    elif (
        result_status == RaceRunnerStatus.UNKNOWN
        or runner_status == RaceRunnerStatus.UNKNOWN
    ):
        participation_status = "unconfirmed"
    elif result is not None:
        participation_status = "actual_start"
    else:
        participation_status = "declared_entry"
    return {
        "candidate_key": identity["candidate_key"],
        "identity_status": identity["identity_status"],
        "event_region": event.country_region,
        "event_id": event.id,
        "event_year": event.year,
        "event_date": event.local_date.isoformat() if event.local_date else "",
        "event_name": event.original_name,
        "event_chinese_name": event.chinese_name,
        "race_grade": event.normalized_grade,
        "racecourse": event.racecourse,
        "horse_name": participant["name"],
        "horse_number": str(
            (result.horse_number if result else "")
            or (runner.horse_number if runner else "")
            or ""
        ),
        "participant_key": participant["participant_key"],
        "participation_status": participation_status,
        "runner_id": runner.id if runner else None,
        "result_id": result.id if result else None,
        "finish_position": result.finish_position if result else None,
        "runner_status": runner_status,
        "source_namespace": identity["source_namespace"],
        "source_url": identity["source_url"],
        "identity_keys": identity["identity_keys"],
        "matched_profile_ids": identity["matched_profile_ids"],
        "sire_name": identity["sire_name"],
        "dam_name": identity["dam_name"],
        "birth_year": identity["birth_year"],
        "pairing_conflict": identity["pairing_conflict"],
    }


def _finalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    source_urls = sorted(candidate.pop("_source_urls"))
    source_namespaces = sorted(candidate.pop("_source_namespaces"))
    identity_keys = sorted(candidate.pop("_identity_keys"))
    matched_profile_ids = sorted(candidate.pop("_matched_profile_ids"))
    aliases = sorted(candidate.pop("_names"))
    event_regions = sorted(candidate.pop("_event_regions"))
    event_ids = sorted(candidate.pop("_event_ids"))
    grades = sorted(candidate.pop("_grades"))
    name_counts = candidate.pop("_name_counts")
    sire_evidence = candidate.pop("_sire_evidence")
    dam_evidence = candidate.pop("_dam_evidence")
    birth_year_evidence = candidate.pop("_birth_year_evidence")
    horse_name = sorted(name_counts, key=lambda name: (-name_counts[name], name.casefold()))[0]
    identity_statuses = candidate.pop("_identity_statuses")
    if (
        len(sire_evidence) > 1
        or len(dam_evidence) > 1
        or len(birth_year_evidence) > 1
    ):
        identity_statuses.add("pedigree_evidence_conflict")
    conflict_statuses = sorted(status for status in identity_statuses if "conflict" in status)
    if conflict_statuses:
        identity_status = conflict_statuses[0]
        review_status = "identity_conflict"
    elif identity_statuses and all(
        status.startswith("matched_existing_profile") for status in identity_statuses
    ):
        identity_status = (
            next(iter(identity_statuses))
            if len(identity_statuses) == 1
            else "matched_existing_profile_multiple_evidence"
        )
        review_status = (
            "ready_for_profile_resolution" if source_urls else "missing_source_url"
        )
    elif len(identity_statuses) == 1:
        identity_status = next(iter(identity_statuses))
        if not source_urls:
            review_status = "missing_source_url"
        elif identity_status == "needs_identity_enrichment":
            review_status = "needs_identity_enrichment"
        else:
            review_status = "ready_for_profile_resolution"
    else:
        identity_status = "mixed_identity_evidence"
        review_status = "identity_conflict"
    return {
        **candidate,
        "horse_name": horse_name,
        "aliases": aliases,
        "event_regions": event_regions,
        "event_ids": event_ids,
        "race_grades": grades,
        "source_urls": source_urls,
        "source_namespace": source_namespaces[0] if len(source_namespaces) == 1 else "",
        "source_namespaces": source_namespaces,
        "identity_keys": identity_keys,
        "matched_profile_ids": matched_profile_ids,
        "sire_name": next(iter(sire_evidence.values()), ""),
        "dam_name": next(iter(dam_evidence.values()), ""),
        "birth_year": next(iter(birth_year_evidence), None),
        "identity_status": identity_status,
        "review_status": review_status,
    }


def build_p0_participant_candidate_artifact(
    *,
    regions: Iterable[str] | None = None,
    sample_per_region: int = 10,
) -> dict[str, Any]:
    if sample_per_region <= 0:
        raise ValueError("sample_per_region must be greater than zero")
    region_list = _normalized_regions(regions)
    identity_index = _identity_index()
    name_index = _horse_name_identity_index()
    pedigree_index = _pedigree_profile_identity_index(name_index)
    observations: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    candidate_map: dict[str, dict[str, Any]] = {}
    event_counts: Counter[str] = Counter()
    runner_counts: Counter[str] = Counter()
    result_counts: Counter[str] = Counter()

    events = _major_race_events(region_list).prefetch_related("runners", "results")
    for event in events.iterator(chunk_size=100):
        event_counts[event.country_region] += 1
        runner_counts[event.country_region] += len(event.runners.all())
        result_counts[event.country_region] += len(event.results.all())
        for participant in _event_participants(event):
            identity = _candidate_identity(
                event=event,
                participant=participant,
                identity_index=identity_index,
                pedigree_index=pedigree_index,
            )
            observation = _participant_observation(
                event=event,
                participant=participant,
                identity=identity,
            )
            identities.append(identity)
            observations.append(observation)

    _canonicalize_candidate_identities(identities)
    for observation, identity in zip(observations, identities):
        observation["candidate_key"] = identity["candidate_key"]
        observation["identity_status"] = identity["identity_status"]
        observation["identity_keys"] = identity["identity_keys"]
        observation["matched_profile_ids"] = identity["matched_profile_ids"]
        candidate = candidate_map.setdefault(
            identity["candidate_key"],
            {
                "candidate_key": identity["candidate_key"],
                "evidence_count": 0,
                "actual_start_evidence_count": 0,
                "declared_entry_evidence_count": 0,
                "nonstarter_evidence_count": 0,
                "unconfirmed_evidence_count": 0,
                "result_evidence_count": 0,
                "first_event_date": "",
                "last_event_date": "",
                "latest_event_id": None,
                "latest_event_name": "",
                "latest_event_grade": "",
                "_source_urls": set(),
                "_source_namespaces": set(),
                "_identity_keys": set(),
                "_matched_profile_ids": set(),
                "_names": set(),
                "_event_regions": set(),
                "_event_ids": set(),
                "_grades": set(),
                "_identity_statuses": set(),
                "_name_counts": Counter(),
                "_sire_evidence": {},
                "_dam_evidence": {},
                "_birth_year_evidence": set(),
            },
        )
        candidate["evidence_count"] += 1
        candidate[f"{observation['participation_status']}_evidence_count"] += 1
        candidate["result_evidence_count"] += int(observation["result_id"] is not None)
        candidate["_names"].add(observation["horse_name"])
        candidate["_name_counts"][observation["horse_name"]] += 1
        candidate["_event_regions"].add(observation["event_region"])
        candidate["_event_ids"].add(observation["event_id"])
        candidate["_grades"].add(observation["race_grade"])
        candidate["_identity_statuses"].add(identity["identity_status"])
        candidate["_identity_keys"].update(identity["identity_keys"])
        candidate["_matched_profile_ids"].update(identity["matched_profile_ids"])
        if identity["source_url"]:
            candidate["_source_urls"].add(identity["source_url"])
        if identity["source_namespace"]:
            candidate["_source_namespaces"].add(identity["source_namespace"])
        sire_key = _identity_name_evidence_key(identity["sire_name"], name_index)
        dam_key = _identity_name_evidence_key(identity["dam_name"], name_index)
        if sire_key:
            candidate["_sire_evidence"].setdefault(sire_key, identity["sire_name"])
        if dam_key:
            candidate["_dam_evidence"].setdefault(dam_key, identity["dam_name"])
        if identity["birth_year"]:
            candidate["_birth_year_evidence"].add(identity["birth_year"])
        event_date = observation["event_date"]
        if event_date and (
            not candidate["first_event_date"] or event_date < candidate["first_event_date"]
        ):
            candidate["first_event_date"] = event_date
        if not candidate["last_event_date"] or event_date >= candidate["last_event_date"]:
            candidate["last_event_date"] = event_date
            candidate["latest_event_id"] = observation["event_id"]
            candidate["latest_event_name"] = observation["event_name"]
            candidate["latest_event_grade"] = observation["race_grade"]

    candidates = sorted(
        (_finalize_candidate(candidate) for candidate in candidate_map.values()),
        key=lambda row: (row["event_regions"], row["horse_name"].casefold(), row["candidate_key"]),
    )
    sample_rows: list[dict[str, Any]] = []
    status_priority = {
        "ready_for_profile_resolution": 0,
        "needs_identity_enrichment": 1,
        "missing_source_url": 2,
        "identity_conflict": 3,
    }
    selected_candidate_keys: set[str] = set()
    for region in region_list:
        region_candidates = [row for row in candidates if region in row["event_regions"]]
        region_candidates.sort(
            key=lambda row: (
                status_priority.get(row["review_status"], 9),
                -int(row["actual_start_evidence_count"] > 0),
                -row["result_evidence_count"],
                row["nonstarter_evidence_count"],
                row["unconfirmed_evidence_count"],
                -(
                    date.fromisoformat(row["last_event_date"]).toordinal()
                    if row["last_event_date"]
                    else 0
                ),
                row["horse_name"].casefold(),
                row["candidate_key"],
            ),
            reverse=False,
        )
        selected_region_candidates: list[dict[str, Any]] = []
        selected_region_names: set[str] = set()
        for candidate in region_candidates:
            normalized_name = _normalize_identity_name(candidate["horse_name"])
            if candidate["candidate_key"] in selected_candidate_keys:
                continue
            if (
                candidate["review_status"] == "needs_identity_enrichment"
                and normalized_name
                and normalized_name in selected_region_names
            ):
                continue
            selected_region_candidates.append(candidate)
            selected_candidate_keys.add(candidate["candidate_key"])
            if normalized_name:
                selected_region_names.add(normalized_name)
            if len(selected_region_candidates) >= sample_per_region:
                break
        for rank, candidate in enumerate(selected_region_candidates, start=1):
            sample_rows.append(
                {
                    "sample_region": region,
                    "sample_rank": rank,
                    **candidate,
                    "reviewed": False,
                    "review_decision": "",
                    "review_notes": "",
                }
            )

    region_summaries = {}
    for region in region_list:
        region_candidates = [row for row in candidates if region in row["event_regions"]]
        region_observations = [row for row in observations if row["event_region"] == region]
        region_sample = [row for row in sample_rows if row["sample_region"] == region]
        region_summaries[region] = {
            "eligible_event_count": event_counts[region],
            "runner_row_count": runner_counts[region],
            "result_row_count": result_counts[region],
            "participant_observation_count": len(region_observations),
            "candidate_count": len(region_candidates),
            "ready_for_profile_resolution_count": sum(
                row["review_status"] == "ready_for_profile_resolution"
                for row in region_candidates
            ),
            "needs_identity_enrichment_count": sum(
                row["review_status"] == "needs_identity_enrichment"
                for row in region_candidates
            ),
            "identity_conflict_count": sum(
                row["review_status"] == "identity_conflict" for row in region_candidates
            ),
            "missing_source_url_count": sum(
                row["review_status"] == "missing_source_url" for row in region_candidates
            ),
            "sample_count": len(region_sample),
            "sample_ready_count": sum(
                row["review_status"] == "ready_for_profile_resolution"
                for row in region_sample
            ),
        }
    return {
        "artifact_type": "p0_horse_participant_candidates",
        "schema_version": P0_CANDIDATE_ARTIFACT_VERSION,
        "generated_at": timezone.now().isoformat(),
        "read_only": True,
        "regions": region_list,
        "eligible_grades": sorted(P0_MAJOR_RACE_GRADES),
        "sample_per_region": sample_per_region,
        "selection_policy": {
            "cross_event_merge": "existing profile, external source identity, or complete name+sire+dam+birth_year only",
            "name_only_merge": False,
            "sample_order": "identity readiness, actual-start evidence, result evidence, nonstarter count, stable name/key",
            "sample_uniqueness": "candidate key is globally unique; duplicate normalized names are suppressed only for weak identity observations",
        },
        "summary": {
            "eligible_event_count": sum(event_counts.values()),
            "runner_row_count": sum(runner_counts.values()),
            "result_row_count": sum(result_counts.values()),
            "participant_observation_count": len(observations),
            "candidate_count": len(candidates),
            "sample_count": len(sample_rows),
            "unique_sample_candidate_count": len(
                {row["candidate_key"] for row in sample_rows}
            ),
            "regions": region_summaries,
        },
        "candidates": candidates,
        "observations": observations,
        "sample_rows": sample_rows,
    }


def write_p0_participant_candidate_artifacts(
    artifact: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, str]:
    output = Path(output_dir)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"candidate artifact output directory is not empty: {output}")
    write_json_artifact(output / "p0_participant_candidates.json", artifact)
    write_json_artifact(output / "summary.json", artifact["summary"])
    sample_fields = [
        "sample_region",
        "sample_rank",
        "candidate_key",
        "horse_name",
        "aliases",
        "identity_status",
        "review_status",
        "matched_profile_ids",
        "identity_keys",
        "source_namespace",
        "source_namespaces",
        "source_urls",
        "event_regions",
        "evidence_count",
        "actual_start_evidence_count",
        "declared_entry_evidence_count",
        "nonstarter_evidence_count",
        "unconfirmed_evidence_count",
        "result_evidence_count",
        "last_event_date",
        "latest_event_id",
        "latest_event_name",
        "latest_event_grade",
        "sire_name",
        "dam_name",
        "birth_year",
        "reviewed",
        "review_decision",
        "review_notes",
    ]
    write_csv_artifact(
        output / "p0_participant_sample_review.csv",
        artifact["sample_rows"],
        sample_fields,
    )
    observations_path = output / "p0_participant_observations.jsonl"
    observations_path.parent.mkdir(parents=True, exist_ok=True)
    observations_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in artifact["observations"]
        ),
        encoding="utf-8",
    )
    artifact_paths = {
        "candidates": output / "p0_participant_candidates.json",
        "summary": output / "summary.json",
        "sample_review_csv": output / "p0_participant_sample_review.csv",
        "observations_jsonl": observations_path,
    }
    manifest = {
        "artifact_type": "p0_horse_participant_candidate_manifest",
        "schema_version": P0_CANDIDATE_ARTIFACT_VERSION,
        "generated_at": artifact["generated_at"],
        "read_only": True,
        "files": {
            name: {
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for name, path in artifact_paths.items()
        },
    }
    manifest_path = write_json_artifact(output / "manifest.json", manifest)
    return {
        **{name: str(path) for name, path in artifact_paths.items()},
        "manifest": str(manifest_path),
    }


def build_p0_completion_queue(
    *,
    regions: Iterable[str] | None = None,
    limit_per_region: int | None = None,
    profile_ids: Iterable[int] | None = None,
) -> dict[str, list[P0QueueItem]]:
    region_list = _normalized_regions(regions)
    result: dict[str, list[P0QueueItem]] = {region: [] for region in region_list}
    profile_filters = Q(
        racing_region__in=region_list,
        p0_sources__status=HorseP0SourceStatus.ACTIVE,
    )
    if profile_ids is not None:
        profile_filters &= Q(id__in=list(profile_ids))
    recent_news_cutoff = timezone.now() - timedelta(days=30)
    freshness_cutoff = active_record_freshness_cutoff()
    profiles = (
        HorseProfile.objects.filter(profile_filters)
        .select_related("primary_term")
        .annotate(
            manual_source_count=Count(
                "p0_sources",
                filter=Q(
                    p0_sources__status=HorseP0SourceStatus.ACTIVE,
                    p0_sources__source_type=HorseP0SourceType.MANUAL,
                ),
                distinct=True,
            ),
            major_source_count=Count(
                "p0_sources",
                filter=Q(
                    p0_sources__status=HorseP0SourceStatus.ACTIVE,
                    p0_sources__source_type=HorseP0SourceType.MAJOR_RACE_PARTICIPANT,
                ),
                distinct=True,
            ),
            candidate_attention_count=Count(
                "data_candidates",
                filter=Q(
                    data_candidates__status__in=(
                        HorseProfileCandidateStatus.PENDING,
                        HorseProfileCandidateStatus.CONFLICT,
                    )
                ),
                distinct=True,
            ),
            recent_article_count=Count(
                "article_links",
                filter=Q(
                    article_links__status__in=(
                        ArticleHorseLinkStatus.AUTO,
                        ArticleHorseLinkStatus.MANUAL,
                    ),
                    article_links__article__published_to_web_at__gte=recent_news_cutoff,
                ),
                distinct=True,
            ),
            latest_race_date=Max("race_records__race_date"),
            external_identity_priority=Case(
                When(source_refs__horse_identity_keys=[], then=Value(1)),
                When(source_refs__horse_identity_keys="", then=Value(1)),
                When(source_refs__horse_identity_keys__isnull=False, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            completion_priority=Case(
                When(completeness_status=HorseProfileCompleteness.EMPTY, then=Value(0)),
                When(completeness_status=HorseProfileCompleteness.PROFILE_ONLY, then=Value(1)),
                When(completeness_status=HorseProfileCompleteness.PARTIAL_PEDIGREE, then=Value(2)),
                When(completeness_status=HorseProfileCompleteness.COMPLETE_PEDIGREE_2GEN, then=Value(3)),
                When(
                    completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL,
                    racing_career_status__in=(
                        HorseRacingCareerStatus.ACTIVE,
                        HorseRacingCareerStatus.RETIRED,
                    ),
                    records_synced_through__isnull=True,
                    then=Value(4),
                ),
                When(
                    completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL,
                    racing_career_status=HorseRacingCareerStatus.ACTIVE,
                    records_synced_through__lt=freshness_cutoff,
                    then=Value(4),
                ),
                When(
                    completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL,
                    racing_career_status=HorseRacingCareerStatus.RETIRED,
                    records_synced_through__lt=F("latest_race_date"),
                    then=Value(4),
                ),
                When(
                    completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL,
                    racing_career_status=HorseRacingCareerStatus.UNKNOWN,
                    then=Value(4),
                ),
                default=Value(5),
                output_field=IntegerField(),
            ),
        )
        .distinct()
        .order_by(
            "racing_region",
            "completion_priority",
            "-manual_source_count",
            "-candidate_attention_count",
            "-recent_article_count",
            "-major_source_count",
            "external_identity_priority",
            "-primary_term__priority",
            "id",
        )
    )
    for profile in profiles:
        region = profile.racing_region
        if limit_per_region is not None and len(result[region]) >= limit_per_region:
            continue
        evaluation = evaluate_full_profile_completeness(profile)
        reasons = ["p0_source"]
        if profile.manual_source_count:
            reasons.append("manual_source")
        if profile.major_source_count:
            reasons.append(f"major_race_sources:{profile.major_source_count}")
        if profile.candidate_attention_count:
            reasons.append(f"candidate_attention:{profile.candidate_attention_count}")
        if profile.recent_article_count:
            reasons.append(f"recent_articles:{profile.recent_article_count}")
        if profile.external_identity_priority == 0:
            reasons.append("external_identity")
        if not evaluation.is_complete:
            reasons.extend(evaluation.blocking_reasons[:6])
        source_ids = list(
            HorseP0Source.objects.filter(profile=profile, status=HorseP0SourceStatus.ACTIVE).values_list("id", flat=True)
        )
        result[region].append(P0QueueItem(profile_id=profile.id, profile=profile, region=region, reasons=reasons, source_ids=source_ids))
    return result


def evaluate_full_profile_completeness(
    profile: HorseProfile,
    *,
    as_of: date | None = None,
    require_review: bool = True,
) -> FullProfileEvaluation:
    missing_fields: list[str] = []
    blocking_reasons: list[str] = []

    if not HorseP0Source.objects.filter(profile=profile, status=HorseP0SourceStatus.ACTIVE).exists():
        blocking_reasons.append("p0_source")

    if not (profile.display_name_zh or profile.original_name or profile.english_name or profile.japanese_name):
        blocking_reasons.append("display_name")

    for field_name in BASIC_PROFILE_REQUIRED_FIELDS:
        if not getattr(profile, field_name):
            missing_fields.append(f"basic_facts.{field_name}")
    for field_name in PEDIGREE_TEXT_FIELDS:
        if not (getattr(profile, field_name) or "").strip():
            missing_fields.append(f"pedigree.{field_name}")
    blocking_reasons.extend(missing_fields)

    race_records = profile.race_records.all()
    if not race_records.exists():
        blocking_reasons.append("race_history.empty")
    elif getattr(settings, "HORSE_PROFILE_COMPLETION_REQUIRE_SOURCE_URL", True) and race_records.filter(
        Q(source_name="") | Q(source_url="")
    ).exists():
        blocking_reasons.append("race_history.source_url")

    if profile.career_history_status != HorseCareerHistoryStatus.COMPLETE:
        blocking_reasons.append(f"race_history.career_status.{profile.career_history_status}")
    if profile.official_or_source_start_count is None:
        blocking_reasons.append("race_history.source_start_count")
    elif profile.collected_start_count != profile.official_or_source_start_count:
        blocking_reasons.append("race_history.start_count_mismatch")
    if not has_official_start_count_evidence(profile):
        blocking_reasons.append("race_history.source_start_count_evidence")
    if profile.career_history_gap_count:
        blocking_reasons.append("race_history.gaps")
    if (
        profile.career_record_authority_status
        != HorseCareerRecordAuthorityStatus.SOURCE_RECORDS_VERIFIED
    ):
        blocking_reasons.append(
            "race_history.record_authority_status."
            f"{profile.career_record_authority_status}"
        )

    if not race_records.filter(Q(result_status=HorseRaceResultStatus.WON) | Q(is_major_win=True)).exists():
        blocking_reasons.append("major_wins")

    if profile.racing_career_status == HorseRacingCareerStatus.UNKNOWN:
        blocking_reasons.append("racing_career_status.unknown")
    elif profile.racing_career_status in {HorseRacingCareerStatus.ACTIVE, HorseRacingCareerStatus.RETIRED}:
        if not profile.records_synced_through:
            blocking_reasons.append("race_history.records_synced_through")
        elif profile.racing_career_status == HorseRacingCareerStatus.ACTIVE:
            freshness_cutoff = active_record_freshness_cutoff(as_of=as_of)
            if profile.records_synced_through < freshness_cutoff:
                blocking_reasons.append("race_history.sync_window_stale")
        elif profile.racing_career_status == HorseRacingCareerStatus.RETIRED:
            latest_race_date = race_records.exclude(race_date__isnull=True).order_by("-race_date").values_list("race_date", flat=True).first()
            if latest_race_date and profile.records_synced_through < latest_race_date:
                blocking_reasons.append("race_history.sync_window_stale")

    if require_review:
        if not profile.full_profile_reviewed_by_id:
            blocking_reasons.append("review.reviewer")
        if not profile.full_profile_reviewed_at:
            blocking_reasons.append("review.reviewed_at")
        for module in REQUIRED_COMPLETION_MODULES:
            latest_candidate = (
                profile.data_candidates.filter(module=module)
                .exclude(status=HorseProfileCandidateStatus.IGNORED)
                .order_by("-fetched_at", "-id")
                .first()
            )
            if not latest_candidate or latest_candidate.status != HorseProfileCandidateStatus.APPLIED:
                blocking_reasons.append(f"review.module.{module}")
            elif (
                getattr(settings, "HORSE_PROFILE_COMPLETION_REQUIRE_SOURCE_URL", True)
                and module in {HorseProfileModule.PROFILE, HorseProfileModule.PEDIGREE}
                and not valid_http_url(latest_candidate.source_url)
            ):
                blocking_reasons.append(f"review.module.{module}.source_url")

    is_complete = not blocking_reasons
    return FullProfileEvaluation(
        profile_id=profile.id,
        is_complete=is_complete,
        blocking_reasons=blocking_reasons,
        missing_fields=missing_fields,
    )


def active_record_freshness_cutoff(*, as_of: date | None = None) -> date:
    freshness_days = max(int(getattr(settings, "HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS", 1)), 0)
    return (as_of or timezone.localdate()) - timedelta(days=freshness_days)


def _apply_profile_payload(profile: HorseProfile, payload: dict, *, manual_lock_flags: dict) -> tuple[list[str], list[str]]:
    changed: list[str] = []
    locked: list[str] = []
    allowed_fields = (
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
    for field_name in allowed_fields:
        if field_name not in payload:
            continue
        if manual_lock_flags.get(field_name):
            locked.append(field_name)
            continue
        value = payload[field_name]
        if field_name in {"birth_date", "records_synced_through"}:
            value = parse_record_date(value)
        if getattr(profile, field_name) != value:
            setattr(profile, field_name, value)
            changed.append(field_name)
    return changed, locked


def _apply_pedigree_payload(profile: HorseProfile, payload: dict, *, manual_lock_flags: dict) -> tuple[list[str], list[str]]:
    changed: list[str] = []
    locked: list[str] = []
    for field_name in PEDIGREE_TEXT_FIELDS:
        if field_name not in payload:
            continue
        if manual_lock_flags.get(field_name):
            locked.append(field_name)
            continue
        value = payload[field_name] or ""
        if getattr(profile, field_name) != value:
            setattr(profile, field_name, value)
            changed.append(field_name)
    return changed, locked


def _module_review(row: dict, module: str) -> dict[str, Any]:
    reviews = row.get("module_reviews") or {}
    for key in MODULE_REVIEW_ALIASES[module]:
        value = reviews.get(key)
        if isinstance(value, str):
            return {"status": value}
        if isinstance(value, dict):
            return value
    return {}


def _module_payload(row: dict, module: str) -> Any:
    if module == HorseProfileModule.PROFILE:
        return row.get("profile_payload") or {}
    if module == HorseProfileModule.PEDIGREE:
        return row.get("pedigree_payload") or {}
    if module == HorseProfileModule.RACE_RECORD:
        return row.get("race_history_payload") or row.get("race_records_payload") or []
    if module == HorseProfileModule.MAJOR_WINS:
        return row.get("major_wins_payload") or []
    return row.get("aliases_payload") or []


def _review_module_payload_error(module: str, payload: Any) -> str:
    if module == HorseProfileModule.PROFILE:
        if not isinstance(payload, dict):
            return "invalid_profile_payload"
        for field_name in (
            "country",
            "sex",
            "color",
            "owner_name",
            "trainer_name",
            "breeder_name",
        ):
            if field_name in payload and not isinstance(
                payload[field_name], str
            ):
                return f"invalid_profile_field:{field_name}"
        birth_date_value = payload.get("birth_date")
        if (
            birth_date_value not in ("", None)
            and parse_record_date(birth_date_value) is None
        ):
            return "invalid_profile_field:birth_date"
    elif module == HorseProfileModule.PEDIGREE:
        if not isinstance(payload, dict):
            return "invalid_pedigree_payload"
        for field_name in PEDIGREE_TEXT_FIELDS:
            if field_name in payload and not isinstance(
                payload[field_name], str
            ):
                return f"invalid_pedigree_field:{field_name}"
    elif module == HorseProfileModule.RACE_RECORD:
        if not isinstance(payload, list):
            return "invalid_race_records_payload"
        for index, record in enumerate(payload):
            if not isinstance(record, dict):
                return f"invalid_race_record:{index}"
            result_status = record.get("result_status")
            if (
                result_status not in ("", None)
                and result_status not in HorseRaceResultStatus.values
            ):
                return f"invalid_race_result_status:{index}"
    return ""


def _career_count_evidence_group(
    career_payload: dict[str, Any],
) -> dict[str, Any]:
    count = career_payload.get("official_or_source_start_count")
    source = str(
        career_payload.get("official_start_count_source") or ""
    ).strip()
    source_url = str(
        career_payload.get("official_start_count_source_url") or ""
    ).strip()
    raw_verified_at = career_payload.get(
        "official_start_count_verified_at"
    )
    if isinstance(raw_verified_at, datetime):
        verified_at = raw_verified_at
    elif isinstance(raw_verified_at, str):
        try:
            verified_at = datetime.fromisoformat(
                raw_verified_at.replace("Z", "+00:00")
            )
        except ValueError:
            verified_at = None
    else:
        verified_at = None
    complete = (
        isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
        and bool(source)
        and valid_http_url(source_url)
        and verified_at is not None
        and timezone.is_aware(verified_at)
    )
    if not complete:
        return {
            "official_or_source_start_count": None,
            "official_start_count_source": "",
            "official_start_count_source_url": "",
            "official_start_count_verified_at": None,
        }
    return {
        "official_or_source_start_count": count,
        "official_start_count_source": source,
        "official_start_count_source_url": source_url,
        "official_start_count_verified_at": verified_at,
    }


def _review_fingerprint(*, profile_id: int, module: str, payload: Any, source_url: str, review: dict) -> str:
    raw = json.dumps(
        {
            "profile_id": profile_id,
            "module": module,
            "payload": payload,
            "source_url": source_url,
            "review": review,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _save_module_audit(
    *,
    profile: HorseProfile,
    module: str,
    module_payload: Any,
    review: dict,
    source_name: str,
    source_url: str,
    status: str,
    reviewer_id: int,
    diff_payload: dict,
    row: dict,
) -> bool:
    def json_safe(value: Any) -> Any:
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                default=lambda item: item.isoformat()
                if isinstance(item, (date, datetime))
                else str(item),
            )
        )

    fingerprint = _review_fingerprint(
        profile_id=profile.id,
        module=module,
        payload=module_payload,
        source_url=source_url,
        review=review,
    )
    existing = HorseProfileDataCandidate.objects.filter(
        profile=profile,
        module=module,
        source_name=source_name,
        status=status,
    )
    if any((candidate.candidate_payload or {}).get("review_fingerprint") == fingerprint for candidate in existing):
        return False
    HorseProfileDataCandidate.objects.create(
        profile=profile,
        module=module,
        source_name=source_name,
        source_url=source_url,
        status=status,
        confidence=int(review.get("confidence") or row.get("confidence") or 100),
        candidate_payload=json_safe(
            {
                "review_fingerprint": fingerprint,
                "payload": module_payload,
                "review": review,
            }
        ),
        diff_payload=json_safe(diff_payload),
        raw_payload=json_safe(row),
        applied_by_id=reviewer_id,
        applied_at=timezone.now(),
        result_summary=f"module_review={review.get('status') or 'unknown'}",
    )
    return True


def apply_reviewed_completion_artifact(payload: dict, *, commit: bool = False) -> dict[str, Any]:
    summary = {
        "applied_profiles": 0,
        "race_records_created": 0,
        "race_records_adopted": 0,
        "race_records_updated": 0,
        "race_records_existing": 0,
        "claimed_race_record_ids": [],
        "manual_lock_skipped": 0,
        "skipped_unreviewed": 0,
        "skipped_unreviewed_modules": 0,
        "skipped_low_confidence_modules": 0,
        "skipped_conflict_modules": 0,
        "ignored_modules": 0,
        "skipped_missing_source_url": 0,
        "skipped_missing_reviewer": 0,
    }
    rows = payload.get("rows", [])
    if not payload.get("reviewed"):
        summary["skipped_unreviewed"] = len(rows)
        return summary
    reviewer_id = payload.get("reviewer_id")
    reviewer = get_user_model().objects.filter(pk=reviewer_id).first() if reviewer_id else None
    if reviewer is None:
        summary["skipped_missing_reviewer"] = len(rows)
        return summary
    if not commit:
        summary["dry_run"] = True
        return summary

    with transaction.atomic():
        for row in rows:
            if row.get("reviewed") is not True:
                summary["skipped_unreviewed"] += 1
                continue
            profile = HorseProfile.objects.select_for_update().get(pk=row["profile_id"])
            changed_fields: list[str] = []
            locked_fields: list[str] = []
            source_name = str(row.get("source_name") or "p0_completion_artifact")
            source_url = str(row.get("source_url") or "")
            approved_modules: set[str] = set()
            row_changed = False

            for module in (*REQUIRED_COMPLETION_MODULES, HorseProfileModule.ALIASES):
                review = _module_review(row, module)
                review_status = str(review.get("status") or "").strip().lower()
                module_payload = _module_payload(row, module)
                if module == HorseProfileModule.ALIASES and not review:
                    continue
                if review_status in {"ignore", "ignored"}:
                    summary["ignored_modules"] += 1
                    _save_module_audit(
                        profile=profile,
                        module=module,
                        module_payload=module_payload,
                        review=review,
                        source_name=source_name,
                        source_url=source_url,
                        status=HorseProfileCandidateStatus.IGNORED,
                        reviewer_id=reviewer.id,
                        diff_payload={
                            "ignored": True,
                            "reason": str(review.get("reason") or "").strip(),
                        },
                        row=row,
                    )
                    continue
                if review_status != "approved":
                    summary["skipped_unreviewed_modules"] += 1
                    if review_status == "conflict":
                        summary["skipped_conflict_modules"] += 1
                        row_changed |= _save_module_audit(
                            profile=profile,
                            module=module,
                            module_payload=module_payload,
                            review=review,
                            source_name=source_name,
                            source_url=source_url,
                            status=HorseProfileCandidateStatus.CONFLICT,
                            reviewer_id=reviewer.id,
                            diff_payload={"conflict": True},
                            row=row,
                        )
                    continue
                confidence = int(review.get("confidence") or row.get("confidence") or 100)
                if confidence < MIN_APPROVED_CONFIDENCE:
                    summary["skipped_low_confidence_modules"] += 1
                    continue
                if review.get("failure_reason") or review.get("conflict"):
                    summary["skipped_conflict_modules"] += 1
                    conflict_reason = review.get("conflict") or review.get("failure_reason")
                    row_changed |= _save_module_audit(
                        profile=profile,
                        module=module,
                        module_payload=module_payload,
                        review={**review, "conflict": conflict_reason},
                        source_name=source_name,
                        source_url=source_url,
                        status=HorseProfileCandidateStatus.CONFLICT,
                        reviewer_id=reviewer.id,
                        diff_payload={"conflict": conflict_reason},
                        row=row,
                    )
                    continue
                if getattr(settings, "HORSE_PROFILE_COMPLETION_REQUIRE_SOURCE_URL", True):
                    if not valid_http_url(source_url):
                        summary["skipped_missing_source_url"] += 1
                        continue
                    if module == HorseProfileModule.RACE_RECORD and any(
                        not str(record.get("source_name") or "").strip()
                        or not valid_http_url(record.get("source_url"))
                        for record in module_payload
                    ):
                        summary["skipped_missing_source_url"] += 1
                        continue
                payload_error = _review_module_payload_error(
                    module,
                    module_payload,
                )
                if payload_error:
                    summary["skipped_conflict_modules"] += 1
                    row_changed |= _save_module_audit(
                        profile=profile,
                        module=module,
                        module_payload=module_payload,
                        review={**review, "conflict": payload_error},
                        source_name=source_name,
                        source_url=source_url,
                        status=HorseProfileCandidateStatus.CONFLICT,
                        reviewer_id=reviewer.id,
                        diff_payload={"conflict": payload_error},
                        row=row,
                    )
                    continue
                if module == HorseProfileModule.RACE_RECORD and any(
                    has_ambiguous_legacy_race_record(profile, record) for record in module_payload
                ):
                    summary["skipped_conflict_modules"] += 1
                    row_changed |= _save_module_audit(
                        profile=profile,
                        module=module,
                        module_payload=module_payload,
                        review={**review, "conflict": "ambiguous_legacy_race_record"},
                        source_name=source_name,
                        source_url=source_url,
                        status=HorseProfileCandidateStatus.CONFLICT,
                        reviewer_id=reviewer.id,
                        diff_payload={"conflict": "ambiguous_legacy_race_record"},
                        row=row,
                    )
                    continue

                approved_modules.add(module)
                diff_payload: dict[str, Any] = {}
                if module == HorseProfileModule.PROFILE:
                    before = {key: getattr(profile, key) for key in module_payload if hasattr(profile, key)}
                    module_changed, module_locked = _apply_profile_payload(
                        profile,
                        module_payload,
                        manual_lock_flags=profile.manual_lock_flags or {},
                    )
                    changed_fields.extend(module_changed)
                    locked_fields.extend(module_locked)
                    diff_payload = {
                        key: {"before": before.get(key), "after": getattr(profile, key)}
                        for key in module_changed
                    }
                elif module == HorseProfileModule.PEDIGREE:
                    before = {key: getattr(profile, key) for key in module_payload if hasattr(profile, key)}
                    module_changed, module_locked = _apply_pedigree_payload(
                        profile,
                        module_payload,
                        manual_lock_flags=profile.manual_lock_flags or {},
                    )
                    changed_fields.extend(module_changed)
                    locked_fields.extend(module_locked)
                    diff_payload = {
                        key: {"before": before.get(key), "after": getattr(profile, key)}
                        for key in module_changed
                    }
                elif module == HorseProfileModule.RACE_RECORD:
                    record_diffs: list[dict[str, Any]] = []
                    for record_payload in module_payload:
                        upsert = upsert_race_record(profile, record_payload)
                        summary["claimed_race_record_ids"].append(upsert.record.id)
                        summary_key = "race_records_existing" if upsert.action == "unchanged" else f"race_records_{upsert.action}"
                        summary[summary_key] += 1
                        if upsert.action != "unchanged":
                            changed_fields.append("race_records")
                            record_diffs.append(
                                {
                                    "record_id": upsert.record.id,
                                    "action": upsert.action,
                                    "before": {key: item["before"] for key, item in upsert.diff.items()},
                                    "after": {key: item["after"] for key, item in upsert.diff.items()},
                                }
                            )
                    diff_payload = {"records": record_diffs}
                elif module == HorseProfileModule.MAJOR_WINS:
                    diff_payload = {
                        "derived_record_ids": list(
                            profile.race_records.filter(
                                Q(result_status=HorseRaceResultStatus.WON) | Q(is_major_win=True)
                            ).values_list("id", flat=True)
                        )
                    }
                else:
                    diff_payload = {"aliases": "reviewed_without_automatic_write"}

                candidate_created = _save_module_audit(
                    profile=profile,
                    module=module,
                    module_payload=module_payload,
                    review=review,
                    source_name=source_name,
                    source_url=source_url,
                    status=HorseProfileCandidateStatus.APPLIED,
                    reviewer_id=reviewer.id,
                    diff_payload=diff_payload,
                    row=row,
                )
                row_changed |= bool(candidate_created or diff_payload.get("records") or changed_fields)

            if HorseProfileModule.RACE_RECORD in approved_modules:
                career_payload = row.get("career_history") or {}
                refresh_kwargs: dict[str, Any] = {}
                record_authority_status = career_payload.get(
                    "record_authority_status"
                )
                if (
                    record_authority_status
                    not in HorseCareerRecordAuthorityStatus.values
                ):
                    record_authority_status = (
                        HorseCareerRecordAuthorityStatus.UNKNOWN
                    )
                refresh_kwargs["record_authority_status"] = (
                    record_authority_status
                )
                refresh_kwargs.update(
                    _career_count_evidence_group(career_payload)
                )
                if "gap_reasons" in career_payload:
                    refresh_kwargs["gap_reasons"] = career_payload.get("gap_reasons") or []
                if "source_refs" in career_payload:
                    refresh_kwargs["source_refs"] = career_payload.get("source_refs") or {}
                if career_payload:
                    refresh_kwargs["verified_at"] = timezone.now()
                refresh_career_history_completeness(profile, **refresh_kwargs)

            if valid_http_url(source_url) and approved_modules:
                source_refs = dict(profile.source_refs or {})
                if source_refs.get("p0_completion") != source_url:
                    source_refs["p0_completion"] = source_url
                    profile.source_refs = source_refs
                    changed_fields.append("source_refs")
                source, source_created = _upsert_p0_source(
                    profile=profile,
                    source_type=HorseP0SourceType.MANUAL,
                    term=profile.primary_term,
                    horse_name=profile.original_name or profile.english_name or profile.japanese_name or profile.display_name,
                    source_url=source_url,
                    evidence_summary="reviewed P0 completion artifact",
                    evidence_payload={"artifact_source_url": source_url, "reviewer_id": reviewer.id},
                )
                if source_created:
                    changed_fields.append("p0_source")

            summary["manual_lock_skipped"] += len(locked_fields)
            data_evaluation = evaluate_full_profile_completeness(profile, require_review=False)
            if set(REQUIRED_COMPLETION_MODULES).issubset(approved_modules) and data_evaluation.is_complete:
                if not profile.full_profile_reviewed_at:
                    profile.full_profile_reviewed_at = timezone.now()
                    changed_fields.append("full_profile_reviewed_at")
                if profile.full_profile_reviewed_by_id != reviewer.id:
                    profile.full_profile_reviewed_by = reviewer
                    changed_fields.append("full_profile_reviewed_by")
            evaluation = evaluate_full_profile_completeness(profile)
            if evaluation.is_complete:
                if profile.completeness_status != HorseProfileCompleteness.COMPLETE_PROFILE_FULL:
                    profile.completeness_status = HorseProfileCompleteness.COMPLETE_PROFILE_FULL
                    changed_fields.append("completeness_status")
                if profile.review_status == HorseProfileStatus.DRAFT:
                    profile.review_status = HorseProfileStatus.READY
                    changed_fields.append("review_status")
            else:
                previous_completeness = profile.completeness_status
                update_completeness(profile, save=False)
                if profile.completeness_status != previous_completeness:
                    changed_fields.append("completeness_status")

            if changed_fields:
                profile.save()
            if changed_fields or (row_changed and approved_modules):
                summary["applied_profiles"] += 1
    return summary


def mark_profile_completion_ready(profile: HorseProfile, *, reviewer=None) -> dict[str, Any]:
    if reviewer is None:
        return {"status": "blocked", "blocking_reasons": ["review.reviewer"]}
    evaluation = evaluate_full_profile_completeness(profile, require_review=False)
    if not evaluation.is_complete:
        return {"status": "blocked", "blocking_reasons": evaluation.blocking_reasons}
    source_url = str((profile.source_refs or {}).get("p0_completion") or "")
    if not source_url:
        return {"status": "blocked", "blocking_reasons": ["review.source_url"]}
    for module in REQUIRED_COMPLETION_MODULES:
        _save_module_audit(
            profile=profile,
            module=module,
            module_payload={"manual_review": True},
            review={"status": "approved", "confidence": 100},
            source_name="manual_profile_review",
            source_url=source_url,
            status=HorseProfileCandidateStatus.APPLIED,
            reviewer_id=reviewer.id,
            diff_payload={"manual_review": True},
            row={"profile_id": profile.id, "reviewed": True, "reviewer_id": reviewer.id},
        )
    profile.completeness_status = HorseProfileCompleteness.COMPLETE_PROFILE_FULL
    if profile.review_status != HorseProfileStatus.PUBLISHED:
        profile.review_status = HorseProfileStatus.READY
    profile.full_profile_reviewed_at = timezone.now()
    profile.full_profile_reviewed_by = reviewer
    profile.save(
        update_fields=[
            "completeness_status",
            "review_status",
            "full_profile_reviewed_at",
            "full_profile_reviewed_by",
            "updated_at",
        ]
    )
    return {"status": "ready_for_manual_publish", "blocking_reasons": []}


def complete_p0_horse_profiles(*args, **kwargs) -> dict[str, Any]:
    return {"status": "not_started", "message": "P0 completion adapters are only run from management commands or reviewed artifacts."}

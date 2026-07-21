from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils import timezone

from stable.models import (
    HorseCareerRecordAuthorityStatus,
    HorseCareerHistoryStatus,
    HorseProfile,
    HorseRaceDatePrecision,
    HorseRaceRecord,
    HorseRaceResultStatus,
    HorseRaceStartStatus,
    RaceEventResult,
)


class AmbiguousLegacyRaceRecordError(ValueError):
    pass


class DuplicateRaceRecordError(ValueError):
    pass


@dataclass
class RaceRecordUpsertResult:
    record: HorseRaceRecord
    action: str
    diff: dict[str, dict[str, Any]]


@dataclass
class CareerHistoryEvaluation:
    profile_id: int
    status: str
    official_or_source_start_count: int | None
    collected_start_count: int
    linked_race_event_count: int
    unlinked_race_record_count: int
    overseas_start_count: int
    deduplicated_source_record_count: int
    gap_count: int
    gap_reasons: list[str]


_UNSET = object()
_ACTUAL_START_RESULTS = {
    HorseRaceResultStatus.WON,
    HorseRaceResultStatus.PLACED,
    HorseRaceResultStatus.UNPLACED,
    HorseRaceResultStatus.DID_NOT_FINISH,
    HorseRaceResultStatus.DISQUALIFIED,
}
_NON_START_RESULTS = {
    HorseRaceResultStatus.SCRATCHED,
    HorseRaceResultStatus.WITHDRAWN,
}
_OFFICIAL_COUNT_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


def parse_record_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _normalize_identity_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", " ", normalized)


def canonical_race_key(profile: HorseProfile, payload: dict) -> str:
    event_id = payload.get("event_id")
    if event_id:
        raw = f"{profile.id}|event|{event_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    race_date = parse_record_date(payload.get("race_date"))
    racecourse = _normalize_identity_text(payload.get("racecourse"))
    if not race_date or not racecourse:
        return ""

    race_number = _normalize_identity_text(payload.get("race_number"))
    if race_number:
        raw = f"{profile.id}|venue-slot|{race_date.isoformat()}|{racecourse}|{race_number}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    race_name = _normalize_identity_text(payload.get("race_name_normalized") or payload.get("race_name"))
    distance = payload.get("distance_meters") or _normalize_identity_text(payload.get("distance_text"))
    if not race_name or not distance:
        return ""
    raw = f"{profile.id}|race-facts|{race_date.isoformat()}|{racecourse}|{race_name}|{distance}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolved_start_status(payload: dict) -> str:
    explicit = str(payload.get("start_status") or "")
    if explicit in HorseRaceStartStatus.values:
        return explicit
    result_status = payload.get("result_status", HorseRaceResultStatus.UNKNOWN)
    if result_status in _ACTUAL_START_RESULTS:
        return HorseRaceStartStatus.STARTED
    if result_status in _NON_START_RESULTS:
        return HorseRaceStartStatus.DID_NOT_START
    return HorseRaceStartStatus.UNCONFIRMED


def _resolved_date_precision(payload: dict) -> str:
    explicit = str(payload.get("race_date_precision") or "")
    if explicit in HorseRaceDatePrecision.values:
        return explicit
    if parse_record_date(payload.get("race_date")):
        return HorseRaceDatePrecision.EXACT
    if payload.get("race_year"):
        return HorseRaceDatePrecision.YEAR
    return HorseRaceDatePrecision.UNKNOWN


def _source_evidence(payload: dict) -> dict[str, Any]:
    evidence = {
        "source_name": str(payload.get("source_name") or "").strip(),
        "source_url": str(payload.get("source_url") or "").strip(),
        "external_horse_id": str(payload.get("external_horse_id") or "").strip(),
        "external_race_id": str(payload.get("external_race_id") or "").strip(),
        "external_result_id": str(payload.get("external_result_id") or "").strip(),
        "race_name": str(payload.get("race_name") or "").strip(),
        "racecourse": str(payload.get("racecourse") or "").strip(),
        "distance_text": str(payload.get("distance_text") or "").strip(),
    }
    if isinstance(payload.get("raw_payload"), dict):
        evidence["raw_payload"] = payload["raw_payload"]
    return {key: value for key, value in evidence.items() if value not in ("", None, {})}


def _source_evidence_key(evidence: dict) -> str:
    source_name = str(evidence.get("source_name") or "").casefold()
    source_url = str(evidence.get("source_url") or "").strip()
    identity = {"source_name": source_name, "source_url": source_url}
    if not source_url:
        identity.update(
            {
                "external_horse_id": evidence.get("external_horse_id", ""),
                "external_race_id": evidence.get("external_race_id", ""),
                "external_result_id": evidence.get("external_result_id", ""),
            }
        )
    return json.dumps(identity, ensure_ascii=True, sort_keys=True)


def _merge_source_refs(record: HorseRaceRecord | None, payload: dict) -> dict[str, Any]:
    merged = dict(record.source_refs or {}) if record and isinstance(record.source_refs, dict) else {}
    incoming_refs = payload.get("source_refs")
    if isinstance(incoming_refs, dict):
        for key, value in incoming_refs.items():
            if key != "sources":
                merged[key] = value

    sources = [item for item in merged.get("sources", []) if isinstance(item, dict)]
    if record and not sources and (record.source_name or record.source_url):
        sources.append(
            {
                "source_name": record.source_name,
                "source_url": record.source_url,
                "distance_text": record.distance_text,
            }
        )
    if isinstance(incoming_refs, dict):
        sources.extend(item for item in incoming_refs.get("sources", []) if isinstance(item, dict))
    sources.append(_source_evidence(payload))

    deduplicated: dict[str, dict] = {}
    for source in sources:
        if not source:
            continue
        key = _source_evidence_key(source)
        if key in deduplicated:
            deduplicated[key].update({name: value for name, value in source.items() if value not in ("", None)})
        else:
            deduplicated[key] = dict(source)
    merged["sources"] = list(deduplicated.values())
    return merged


def record_idempotency_key(profile: HorseProfile, payload: dict) -> str:
    external_id = str(
        payload.get("external_result_id")
        or payload.get("external_race_id")
        or payload.get("idempotency_key")
        or ""
    ).strip()
    source_identity = str(payload.get("source_name") or "").strip().casefold()
    if external_id:
        raw = f"{profile.id}|external|{source_identity}|{external_id}"
    else:
        raw = "|".join(
            [
                str(profile.id),
                source_identity,
                str(payload.get("race_date") or payload.get("race_year") or ""),
                str(payload.get("race_name") or ""),
                str(payload.get("racecourse") or ""),
                str(payload.get("source_url") or ""),
            ]
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _inherit_external_identity(record: HorseRaceRecord, payload: dict) -> dict:
    identity_payload = dict(payload)
    if identity_payload.get("external_result_id") or identity_payload.get("external_race_id"):
        return identity_payload
    for evidence in (record.raw_payload, record.source_refs):
        if not isinstance(evidence, dict):
            continue
        for key in ("external_result_id", "external_race_id"):
            value = evidence.get(key)
            if value:
                identity_payload[key] = value
                identity_payload["source_name"] = record.source_name or identity_payload.get("source_name", "")
                return identity_payload
    return identity_payload


def _external_identity_value(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(
        payload.get("external_result_id")
        or payload.get("external_race_id")
        or payload.get("idempotency_key")
        or ""
    ).strip()


def _external_identity_values(payload: dict) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    return {
        str(payload.get(key) or "").strip()
        for key in ("external_result_id", "external_race_id", "idempotency_key")
        if str(payload.get(key) or "").strip()
    }


def _evidence_source_name(*payloads: dict) -> str:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in ("source", "source_name", "provider", "adapter"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
    return ""


def _record_source_name(record: HorseRaceRecord) -> str:
    return str(record.source_name or "").strip() or _evidence_source_name(
        record.raw_payload,
        record.source_refs,
    )


def _legacy_external_identity_matches(profile: HorseProfile, payload: dict) -> list[HorseRaceRecord]:
    external_id = _external_identity_value(payload)
    if not external_id:
        return []
    source_name = str(payload.get("source_name") or "").strip()
    queryset = HorseRaceRecord.objects.filter(horse_profile=profile, idempotency_key="").order_by("id")
    matches = []
    for record in queryset.iterator():
        record_source_name = _record_source_name(record)
        if source_name and record_source_name.casefold() != source_name.casefold():
            continue
        if any(
            _external_identity_value(evidence) == external_id
            for evidence in (record.raw_payload, record.source_refs)
        ):
            matches.append(record)
            if len(matches) == 2:
                break
    return matches


def _source_evidence_identity_matches(profile: HorseProfile, payload: dict) -> list[HorseRaceRecord]:
    external_ids = _external_identity_values(payload)
    source_name = str(payload.get("source_name") or "").strip().casefold()
    if not external_ids or not source_name:
        return []
    matches: list[HorseRaceRecord] = []
    for record in HorseRaceRecord.objects.filter(horse_profile=profile).order_by("id").iterator():
        evidence_items = [record.raw_payload, record.source_refs]
        if isinstance(record.source_refs, dict):
            evidence_items.extend(record.source_refs.get("sources", []))
        for evidence in evidence_items:
            if not isinstance(evidence, dict):
                continue
            evidence_source = _evidence_source_name(evidence).casefold()
            if evidence_source != source_name:
                continue
            if _external_identity_values(evidence) & external_ids:
                matches.append(record)
                break
        if len(matches) == 2:
            break
    return matches


def _legacy_race_record_matches(profile: HorseProfile, payload: dict) -> list[HorseRaceRecord]:
    queryset = HorseRaceRecord.objects.filter(
        horse_profile=profile,
        idempotency_key="",
        race_name=payload.get("race_name", ""),
    )
    race_date = parse_record_date(payload.get("race_date"))
    if race_date:
        queryset = queryset.filter(race_date=race_date)
    elif payload.get("race_year"):
        queryset = queryset.filter(race_year=payload.get("race_year"))
    for field_name in ("racecourse", "source_name", "source_url"):
        value = payload.get(field_name)
        if value:
            lookup = f"{field_name}__iexact" if field_name == "source_name" else field_name
            queryset = queryset.filter(**{lookup: value})
    return list(queryset.order_by("id")[:2])


def has_ambiguous_legacy_race_record(profile: HorseProfile, payload: dict) -> bool:
    key = record_idempotency_key(profile, payload)
    if HorseRaceRecord.objects.filter(horse_profile=profile, idempotency_key=key).exists():
        return False
    external_matches = _legacy_external_identity_matches(profile, payload)
    if external_matches:
        return len(external_matches) > 1
    return len(_legacy_race_record_matches(profile, payload)) > 1


def _race_record_values(payload: dict) -> dict[str, Any]:
    values = {
        "race_name": payload.get("race_name", ""),
        "race_year": payload.get("race_year") or None,
        "race_date": parse_record_date(payload.get("race_date")),
        "race_date_precision": _resolved_date_precision(payload),
        "race_name_normalized": payload.get("race_name_normalized", ""),
        "race_region": payload.get("race_region", ""),
        "race_number": payload.get("race_number", ""),
        "grade_text": payload.get("grade_text", payload.get("normalized_grade", "")),
        "normalized_grade": payload.get("normalized_grade", ""),
        "racecourse": payload.get("racecourse", ""),
        "distance_text": payload.get("distance_text", ""),
        "distance_meters": payload.get("distance_meters") or None,
        "surface": payload.get("surface", ""),
        "race_type_text": payload.get("race_type_text", ""),
        "horse_number": payload.get("horse_number", ""),
        "barrier": payload.get("barrier", ""),
        "jockey_name": payload.get("jockey_name", ""),
        "carried_weight": payload.get("carried_weight", ""),
        "finish_time": payload.get("finish_time", ""),
        "prize_text": payload.get("prize_text", ""),
        "finish_position": payload.get("finish_position", ""),
        "result_status": payload.get("result_status", HorseRaceResultStatus.UNKNOWN),
        "start_status": _resolved_start_status(payload),
        "is_overseas": bool(payload.get("is_overseas", False)),
        "is_major_win": bool(payload.get("is_major_win", False)),
        "source_name": payload.get("source_name", ""),
        "source_url": payload.get("source_url", ""),
        "raw_payload": payload.get("raw_payload", payload),
    }
    if "event_id" in payload:
        values["event_id"] = payload.get("event_id") or None
    if "result_id" in payload:
        values["result_id"] = payload.get("result_id") or None
    if "major_win_order" in payload:
        values["major_win_order"] = payload.get("major_win_order") or 0
    return values


def valid_http_url(value: Any) -> bool:
    try:
        _OFFICIAL_COUNT_URL_VALIDATOR(str(value or "").strip())
    except ValidationError:
        return False
    return True


def _record_has_source_evidence(record: HorseRaceRecord) -> bool:
    if record.source_name and valid_http_url(record.source_url):
        return True
    refs = record.source_refs if isinstance(record.source_refs, dict) else {}
    return any(
        str(source.get("source_name") or "").strip()
        and valid_http_url(source.get("source_url"))
        for source in refs.get("sources", [])
        if isinstance(source, dict)
    )


def has_official_start_count_evidence(profile: HorseProfile) -> bool:
    if not str(profile.official_start_count_source or "").strip():
        return False
    if not valid_http_url(
        profile.official_start_count_source_url
    ):
        return False
    verified_at = profile.official_start_count_verified_at
    if isinstance(verified_at, str):
        try:
            verified_at = datetime.fromisoformat(
                verified_at.replace("Z", "+00:00")
            )
        except ValueError:
            return False
    return isinstance(verified_at, datetime) and timezone.is_aware(verified_at)


def refresh_career_history_completeness(
    profile: HorseProfile,
    *,
    official_or_source_start_count: int | None | object = _UNSET,
    official_start_count_source: str | object = _UNSET,
    official_start_count_source_url: str | object = _UNSET,
    official_start_count_verified_at: Any = _UNSET,
    record_authority_status: str | object = _UNSET,
    gap_reasons: list[str] | None = None,
    source_refs: dict | None = None,
    verified_at: Any = _UNSET,
    save: bool = True,
) -> CareerHistoryEvaluation:
    if official_or_source_start_count is not _UNSET:
        profile.official_or_source_start_count = official_or_source_start_count
    if official_start_count_source is not _UNSET:
        profile.official_start_count_source = str(
            official_start_count_source or ""
        ).strip()
    if official_start_count_source_url is not _UNSET:
        profile.official_start_count_source_url = str(
            official_start_count_source_url or ""
        ).strip()
    if official_start_count_verified_at is not _UNSET:
        profile.official_start_count_verified_at = (
            official_start_count_verified_at
        )
    if record_authority_status is not _UNSET:
        if record_authority_status not in HorseCareerRecordAuthorityStatus.values:
            raise ValueError(
                f"unsupported career record authority status: {record_authority_status}"
            )
        profile.career_record_authority_status = record_authority_status
    if source_refs is not None:
        profile.career_history_source_refs = source_refs
    if verified_at is not _UNSET:
        profile.career_history_last_verified_at = verified_at
    elif official_or_source_start_count is not _UNSET:
        profile.career_history_last_verified_at = timezone.now()

    records = list(profile.race_records.all())
    collected = sum(1 for record in records if record.start_status == HorseRaceStartStatus.STARTED)
    linked = sum(1 for record in records if record.event_id)
    unlinked = len(records) - linked
    overseas = sum(
        1
        for record in records
        if record.start_status == HorseRaceStartStatus.STARTED and record.is_overseas
    )
    deduplicated = 0
    for record in records:
        refs = record.source_refs if isinstance(record.source_refs, dict) else {}
        sources = [source for source in refs.get("sources", []) if isinstance(source, dict)]
        deduplicated += max(len(sources) - 1, 0)

    retained_reasons = (
        list(gap_reasons)
        if gap_reasons is not None
        else [
            str(reason)
            for reason in (profile.career_history_gap_reasons or [])
            if str(reason).startswith(("source:", "manual:"))
        ]
    )
    computed_reasons: list[str] = []
    computed_gap_count = 0
    unconfirmed_count = 0
    for record in records:
        if record.start_status == HorseRaceStartStatus.UNCONFIRMED:
            computed_reasons.append(f"record:{record.id}:start_status_unconfirmed")
            computed_gap_count += 1
            unconfirmed_count += 1
        if not record.race_date or record.race_date_precision != HorseRaceDatePrecision.EXACT:
            computed_reasons.append(f"record:{record.id}:race_date_incomplete")
            computed_gap_count += 1
        if not record.race_name.strip():
            computed_reasons.append(f"record:{record.id}:race_name_missing")
            computed_gap_count += 1
        if not record.racecourse.strip():
            computed_reasons.append(f"record:{record.id}:racecourse_missing")
            computed_gap_count += 1
        if not _record_has_source_evidence(record):
            computed_reasons.append(f"record:{record.id}:source_evidence_missing")
            computed_gap_count += 1

    source_total = profile.official_or_source_start_count
    if source_total is None:
        computed_reasons.append("source_total_unknown")
        computed_gap_count += 1
    elif collected < source_total:
        missing_count = source_total - collected
        computed_reasons.append(f"source_start_count_missing:{missing_count}")
        computed_gap_count += missing_count
    elif collected > source_total:
        extra_count = collected - source_total
        computed_reasons.append(f"source_start_count_exceeded:{extra_count}")
        computed_gap_count += extra_count
    if source_total is not None:
        if not str(profile.official_start_count_source or "").strip():
            computed_reasons.append("official_start_count_source_missing")
        if not valid_http_url(
            profile.official_start_count_source_url
        ):
            computed_reasons.append("official_start_count_source_url_missing")
        verified_at = profile.official_start_count_verified_at
        if isinstance(verified_at, str):
            try:
                verified_at = datetime.fromisoformat(
                    verified_at.replace("Z", "+00:00")
                )
            except ValueError:
                verified_at = None
        if not (
            isinstance(verified_at, datetime)
            and timezone.is_aware(verified_at)
        ):
            computed_reasons.append(
                "official_start_count_verified_at_missing"
            )

    authority_reasons: list[str] = []
    if (
        profile.career_record_authority_status
        == HorseCareerRecordAuthorityStatus.COUNT_ALIGNED_RECORDS_UNVERIFIED
    ):
        authority_reasons.append(
            "official_count_aligned_per_record_authority_pending:"
            f"{profile.official_start_count_source or 'unknown'}"
        )
    elif (
        profile.career_record_authority_status
        == HorseCareerRecordAuthorityStatus.SOURCE_BLOCKED
    ):
        authority_reasons.append(
            "official_per_record_source_blocked:"
            f"{profile.official_start_count_source or 'unknown'}"
        )
    elif (
        profile.career_record_authority_status
        != HorseCareerRecordAuthorityStatus.SOURCE_RECORDS_VERIFIED
    ):
        authority_reasons.append("per_record_authority_unknown")
    reasons = list(
        dict.fromkeys(
            [*retained_reasons, *computed_reasons, *authority_reasons]
        )
    )
    gap_count = len(retained_reasons) + computed_gap_count
    if not records and source_total is None:
        status = HorseCareerHistoryStatus.NOT_STARTED
    elif (
        source_total is not None
        and collected == source_total
        and gap_count == 0
        and not reasons
    ):
        status = HorseCareerHistoryStatus.COMPLETE
    elif collected > (source_total if source_total is not None else collected) or unconfirmed_count:
        status = HorseCareerHistoryStatus.NEEDS_REVIEW
    else:
        status = HorseCareerHistoryStatus.PARTIAL

    profile.career_history_status = status
    profile.collected_start_count = collected
    profile.linked_race_event_count = linked
    profile.unlinked_race_record_count = unlinked
    profile.overseas_start_count = overseas
    profile.deduplicated_source_record_count = deduplicated
    profile.career_history_gap_count = gap_count
    profile.career_history_gap_reasons = reasons
    if save:
        profile.save(
            update_fields=[
                "official_or_source_start_count",
                "official_start_count_source",
                "official_start_count_source_url",
                "official_start_count_verified_at",
                "career_record_authority_status",
                "career_history_status",
                "collected_start_count",
                "linked_race_event_count",
                "unlinked_race_record_count",
                "overseas_start_count",
                "deduplicated_source_record_count",
                "career_history_gap_count",
                "career_history_gap_reasons",
                "career_history_source_refs",
                "career_history_last_verified_at",
                "updated_at",
            ]
        )
    return CareerHistoryEvaluation(
        profile_id=profile.id,
        status=status,
        official_or_source_start_count=source_total,
        collected_start_count=collected,
        linked_race_event_count=linked,
        unlinked_race_record_count=unlinked,
        overseas_start_count=overseas,
        deduplicated_source_record_count=deduplicated,
        gap_count=gap_count,
        gap_reasons=reasons,
    )


def _cross_source_value(record: HorseRaceRecord, field_name: str, value: Any) -> Any:
    current = getattr(record, field_name)
    if field_name == "source_refs":
        return value
    if field_name == "is_overseas":
        return bool(current or value)
    if field_name in {"event_id", "result_id", "canonical_race_key"}:
        return value or current
    if field_name == "start_status":
        return value if current == HorseRaceStartStatus.UNCONFIRMED else current
    if field_name == "result_status":
        return value if current == HorseRaceResultStatus.UNKNOWN else current
    if current not in ("", None, False):
        return current
    return value


def _apply_record_values(
    record: HorseRaceRecord,
    values: dict[str, Any],
    *,
    cross_source: bool,
) -> dict[str, dict[str, Any]]:
    diff: dict[str, dict[str, Any]] = {}
    for field_name, value in values.items():
        if cross_source:
            value = _cross_source_value(record, field_name, value)
        current = getattr(record, field_name)
        if current != value:
            diff[field_name] = {"before": current, "after": value}
            setattr(record, field_name, value)
    return diff


def upsert_race_record(
    profile: HorseProfile,
    payload: dict,
    *,
    record: HorseRaceRecord | None = None,
) -> RaceRecordUpsertResult:
    payload = dict(payload)
    if not str(payload.get("race_name") or "").strip():
        raise ValueError("race_name is required")
    if not str(payload.get("source_name") or "").strip():
        raise ValueError("source_name is required")
    if not str(payload.get("source_url") or "").strip():
        raise ValueError("source_url is required")

    if payload.get("result_id"):
        result = RaceEventResult.objects.only("event_id").get(pk=payload["result_id"])
        if payload.get("event_id") and int(payload["event_id"]) != result.event_id:
            raise ValueError("result does not belong to event")
        payload.setdefault("event_id", result.event_id)

    key_payload = _inherit_external_identity(record, payload) if record is not None else payload
    key = record_idempotency_key(profile, key_payload)
    canonical_key = canonical_race_key(profile, payload)
    values = _race_record_values(payload)
    if record is not None:
        if record.horse_profile_id != profile.id:
            raise ValueError("race record does not belong to this horse profile")
        if HorseRaceRecord.objects.filter(horse_profile=profile, idempotency_key=key).exclude(pk=record.pk).exists():
            raise DuplicateRaceRecordError("another race record already uses this idempotency key")
        source_evidence_matches = [
            match for match in _source_evidence_identity_matches(profile, key_payload) if match.pk != record.pk
        ]
        if source_evidence_matches:
            raise DuplicateRaceRecordError("another race record already uses this source identity")
        if canonical_key and HorseRaceRecord.objects.filter(
            horse_profile=profile,
            canonical_race_key=canonical_key,
        ).exclude(pk=record.pk).exists():
            raise DuplicateRaceRecordError("another race record already uses this canonical race key")
        external_legacy_matches = [
            match
            for match in _legacy_external_identity_matches(profile, key_payload)
            if match.pk != record.pk
        ]
        if external_legacy_matches:
            raise DuplicateRaceRecordError("another legacy race record uses this external identity")
        legacy_matches = [match for match in _legacy_race_record_matches(profile, payload) if match.pk != record.pk]
        if legacy_matches:
            raise DuplicateRaceRecordError("another legacy race record matches this payload")
        values["source_refs"] = record.source_refs
        values["raw_payload"] = record.raw_payload
        values["canonical_race_key"] = canonical_key or record.canonical_race_key
        diff: dict[str, dict[str, Any]] = {}
        if record.idempotency_key != key:
            diff["idempotency_key"] = {"before": record.idempotency_key, "after": key}
            record.idempotency_key = key
        diff.update(_apply_record_values(record, values, cross_source=False))
        if diff:
            record.save()
        refresh_career_history_completeness(profile)
        return RaceRecordUpsertResult(record=record, action="updated" if diff else "unchanged", diff=diff)

    idempotent_record = HorseRaceRecord.objects.filter(horse_profile=profile, idempotency_key=key).first()
    source_evidence_records = _source_evidence_identity_matches(profile, payload)
    if len(source_evidence_records) > 1:
        raise DuplicateRaceRecordError("source identity resolves to multiple race records")
    source_evidence_record = source_evidence_records[0] if source_evidence_records else None
    canonical_record = None
    if canonical_key:
        canonical_record = HorseRaceRecord.objects.filter(
            horse_profile=profile,
            canonical_race_key=canonical_key,
        ).first()
    if canonical_record is None and payload.get("event_id"):
        fact_payload = dict(payload)
        fact_payload.pop("event_id", None)
        fact_payload.pop("result_id", None)
        fact_key = canonical_race_key(profile, fact_payload)
        if fact_key:
            canonical_record = HorseRaceRecord.objects.filter(
                horse_profile=profile,
                canonical_race_key=fact_key,
            ).first()
    identity_records = {
        candidate.pk: candidate
        for candidate in (idempotent_record, source_evidence_record, canonical_record)
        if candidate is not None
    }
    if len(identity_records) > 1:
        raise DuplicateRaceRecordError("source identity and canonical identity resolve to different records")
    record = next(iter(identity_records.values()), None)
    action = "unchanged"
    if record is not None and not record.idempotency_key:
        record.idempotency_key = key
        action = "adopted"
    if record is None:
        if has_ambiguous_legacy_race_record(profile, payload):
            raise AmbiguousLegacyRaceRecordError("multiple legacy race records match this payload")
        legacy_matches = _legacy_external_identity_matches(profile, payload)
        if not legacy_matches:
            legacy_matches = _legacy_race_record_matches(profile, payload)
        record = legacy_matches[0] if len(legacy_matches) == 1 else None
        if record is not None:
            record.idempotency_key = key
            action = "adopted"
        else:
            values["source_refs"] = _merge_source_refs(None, payload)
            values["canonical_race_key"] = canonical_key
            record = HorseRaceRecord.objects.create(
                horse_profile=profile,
                idempotency_key=key,
                **values,
            )
            refresh_career_history_completeness(profile)
            return RaceRecordUpsertResult(record=record, action="created", diff={})

    incoming_source = str(payload.get("source_name") or "").strip().casefold()
    existing_source = _record_source_name(record).casefold()
    cross_source = bool(incoming_source and existing_source and incoming_source != existing_source)
    values["source_refs"] = _merge_source_refs(record, payload)
    values["canonical_race_key"] = canonical_key or record.canonical_race_key
    diff = _apply_record_values(record, values, cross_source=cross_source)
    if diff or action == "adopted":
        record.save()
        if action != "adopted":
            action = "updated"
    refresh_career_history_completeness(profile)
    return RaceRecordUpsertResult(record=record, action=action, diff=diff)

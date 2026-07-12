from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

from stable.models import HorseProfile, HorseRaceRecord, HorseRaceResultStatus


class AmbiguousLegacyRaceRecordError(ValueError):
    pass


class DuplicateRaceRecordError(ValueError):
    pass


@dataclass
class RaceRecordUpsertResult:
    record: HorseRaceRecord
    action: str
    diff: dict[str, dict[str, Any]]


def parse_record_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


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


def _race_record_values(payload: dict, *, preserve_source_evidence: bool = False) -> dict[str, Any]:
    values = {
        "race_name": payload.get("race_name", ""),
        "race_year": payload.get("race_year") or None,
        "race_date": parse_record_date(payload.get("race_date")),
        "grade_text": payload.get("grade_text", payload.get("normalized_grade", "")),
        "normalized_grade": payload.get("normalized_grade", ""),
        "racecourse": payload.get("racecourse", ""),
        "distance_text": payload.get("distance_text", ""),
        "surface": payload.get("surface", ""),
        "finish_position": payload.get("finish_position", ""),
        "result_status": payload.get("result_status", HorseRaceResultStatus.UNKNOWN),
        "is_major_win": bool(payload.get("is_major_win", False)),
        "source_name": payload.get("source_name", ""),
        "source_url": payload.get("source_url", ""),
    }
    if not preserve_source_evidence:
        values["source_refs"] = payload.get("source_refs", {})
        values["raw_payload"] = payload.get("raw_payload", payload)
    if "event_id" in payload:
        values["event_id"] = payload.get("event_id") or None
    if "major_win_order" in payload:
        values["major_win_order"] = payload.get("major_win_order") or 0
    return values


def upsert_race_record(
    profile: HorseProfile,
    payload: dict,
    *,
    record: HorseRaceRecord | None = None,
) -> RaceRecordUpsertResult:
    if not str(payload.get("race_name") or "").strip():
        raise ValueError("race_name is required")
    if not str(payload.get("source_name") or "").strip():
        raise ValueError("source_name is required")
    if not str(payload.get("source_url") or "").strip():
        raise ValueError("source_url is required")
    if has_ambiguous_legacy_race_record(profile, payload):
        raise AmbiguousLegacyRaceRecordError("multiple legacy race records match this payload")

    key_payload = _inherit_external_identity(record, payload) if record is not None else payload
    key = record_idempotency_key(profile, key_payload)
    values = _race_record_values(payload, preserve_source_evidence=record is not None)
    if record is not None:
        if record.horse_profile_id != profile.id:
            raise ValueError("race record does not belong to this horse profile")
        if HorseRaceRecord.objects.filter(horse_profile=profile, idempotency_key=key).exclude(pk=record.pk).exists():
            raise DuplicateRaceRecordError("another race record already uses this idempotency key")
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
        diff: dict[str, dict[str, Any]] = {}
        if record.idempotency_key != key:
            diff["idempotency_key"] = {"before": record.idempotency_key, "after": key}
            record.idempotency_key = key
        for field_name, value in values.items():
            current = getattr(record, field_name)
            if current != value:
                diff[field_name] = {"before": current, "after": value}
                setattr(record, field_name, value)
        if diff:
            record.save()
        return RaceRecordUpsertResult(record=record, action="updated" if diff else "unchanged", diff=diff)

    record = HorseRaceRecord.objects.filter(horse_profile=profile, idempotency_key=key).first()
    action = "unchanged"
    if record is None:
        legacy_matches = _legacy_external_identity_matches(profile, payload)
        if not legacy_matches:
            legacy_matches = _legacy_race_record_matches(profile, payload)
        record = legacy_matches[0] if len(legacy_matches) == 1 else None
        if record is not None:
            record.idempotency_key = key
            action = "adopted"
        else:
            record = HorseRaceRecord.objects.create(horse_profile=profile, idempotency_key=key, **values)
            return RaceRecordUpsertResult(record=record, action="created", diff={})

    diff: dict[str, dict[str, Any]] = {}
    for field_name, value in values.items():
        current = getattr(record, field_name)
        if current != value:
            diff[field_name] = {"before": current, "after": value}
            setattr(record, field_name, value)
    if diff or action == "adopted":
        record.save()
        if action != "adopted":
            action = "updated"
    return RaceRecordUpsertResult(record=record, action=action, diff=diff)

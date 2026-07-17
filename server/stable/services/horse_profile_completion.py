from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from stable.models import (
    ExternalDataSource,
    ExternalHorse,
    ExternalHorseAlias,
    HorseCompletionFailureReason,
    HorseProfile,
    HorseProfileCandidateStatus,
    HorseProfileCompleteness,
    HorseProfileDataCandidate,
    HorseProfileModule,
    RacingRegion,
    TaskExecutionLog,
    TaskStatus,
)
from stable.services.horse_profiles import (
    PEDIGREE_TEXT_FIELDS,
    build_candidate_diff,
    calculate_completeness,
    save_data_candidate,
    update_completeness,
)
from stable.services.term_maintenance import write_csv_artifact, write_json_artifact


SOURCE_BY_REGION = {
    RacingRegion.JAPAN: [ExternalDataSource.NETKEIBA],
    RacingRegion.HONG_KONG: [ExternalDataSource.HKJC],
    RacingRegion.UNITED_KINGDOM: [ExternalDataSource.SPORTING_LIFE],
    RacingRegion.FRANCE: [ExternalDataSource.GENY_FRANCE, ExternalDataSource.FRANCE_GALOP],
    RacingRegion.UNITED_STATES: [ExternalDataSource.HORSE_RACING_NATION],
    RacingRegion.OTHER: [],
}

FAILURE_KEYS = [
    HorseCompletionFailureReason.NO_EXTERNAL_MATCH,
    HorseCompletionFailureReason.AMBIGUOUS_MATCH,
    HorseCompletionFailureReason.SOURCE_UNAVAILABLE,
    HorseCompletionFailureReason.RATE_LIMITED,
    HorseCompletionFailureReason.MISSING_PEDIGREE_FIELDS,
    HorseCompletionFailureReason.PROFILE_ONLY,
    HorseCompletionFailureReason.MANUAL_LOCK_SKIPPED,
    HorseCompletionFailureReason.NOT_ATTEMPTED,
]


@dataclass
class CompletionOptions:
    regions: list[str] | None = None
    limit: int | None = None
    output_dir: str | Path = "runtime/horse_profile_completion"
    request_interval_seconds: float = 8.0
    cache_dir: str | Path = "runtime/horse_profile_completion/cache"


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip().casefold()


def _display_normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


def _profile_names(profile: HorseProfile) -> list[str]:
    values = [
        profile.display_name_zh,
        profile.original_name,
        profile.english_name,
        profile.japanese_name,
        profile.primary_term.source_ja,
        profile.primary_term.target_zh,
    ]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _profile_display_names(profile: HorseProfile) -> list[str]:
    values = [
        profile.display_name_zh,
        profile.original_name,
        profile.english_name,
        profile.japanese_name,
        profile.primary_term.source_ja,
        profile.primary_term.target_zh,
    ]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _display_normalize(value)
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _raw_payload_value(raw_payload: dict, *keys: str) -> str:
    for key in keys:
        value = raw_payload.get(key)
        if value:
            return str(value).strip()
    return ""


def _pedigree_from_external_horse(horse: ExternalHorse) -> dict[str, str]:
    raw = horse.raw_payload if isinstance(horse.raw_payload, dict) else {}
    return {
        "sire_text": horse.father_name or _raw_payload_value(raw, "sire", "father", "father_name", "sire_name"),
        "dam_text": horse.mother_name or _raw_payload_value(raw, "dam", "mother", "mother_name", "dam_name"),
        "sire_sire_text": _raw_payload_value(raw, "sire_sire", "father_father", "sire_sire_name"),
        "sire_dam_text": _raw_payload_value(raw, "sire_dam", "father_mother", "sire_dam_name"),
        "dam_sire_text": _raw_payload_value(raw, "dam_sire", "mother_father", "dam_sire_name"),
        "dam_dam_text": _raw_payload_value(raw, "dam_dam", "mother_mother", "dam_dam_name"),
    }


def _profile_payload_from_external_horse(horse: ExternalHorse) -> dict[str, Any]:
    return {
        "country": horse.country,
        "sex": horse.sex,
        "color": horse.color,
        "birth_date": horse.birth_date.isoformat() if horse.birth_date else None,
        "owner_name": horse.owner_name,
        "trainer_name": horse.trainer_name,
        "source_refs": {
            "source": horse.source,
            "external_horse_id": horse.horse_id,
            "fetched_at": horse.fetched_at.isoformat() if horse.fetched_at else "",
        },
    }


def _source_url(horse: ExternalHorse) -> str:
    raw = horse.raw_payload if isinstance(horse.raw_payload, dict) else {}
    for key in ("source_url", "horse_profile_url", "url"):
        if raw.get(key):
            return str(raw[key])
    return ""


def _matches_for_profile(profile: HorseProfile, sources: list[str]) -> list[ExternalHorse]:
    names = _profile_names(profile)
    display_names = _profile_display_names(profile)
    if not names or not sources:
        return []
    aliases = (
        ExternalHorseAlias.objects.filter(source__in=sources)
        .filter(racing_region=profile.racing_region)
        .annotate(normalized_key=Lower("normalized_name"))
        .filter(normalized_key__in=names)
        .select_related("horse")
        .order_by("-confidence", "-last_seen_at", "external_horse_id")
    )
    horses: dict[int, ExternalHorse] = {}
    for alias in aliases:
        if alias.horse_id:
            horses[alias.horse_id] = alias.horse
    if not horses:
        horses_qs = ExternalHorse.objects.filter(source__in=sources, racing_region=profile.racing_region)
        horses_qs = horses_qs.annotate(normalized_key=Lower("normalized_horse_name"), horse_name_key=Lower("horse_name")).filter(
            Q(normalized_key__in=names) | Q(horse_name_key__in=names) | Q(horse_name__in=display_names)
        )
        for horse in horses_qs.order_by("-last_seen_at", "id"):
            horses[horse.pk] = horse
    return list(horses.values())


def _completion_status(pedigree_payload: dict[str, str], profile_payload: dict[str, Any]) -> tuple[str, str]:
    if all((pedigree_payload.get(field) or "").strip() for field in PEDIGREE_TEXT_FIELDS):
        return HorseProfileCompleteness.COMPLETE_PEDIGREE_2GEN, ""
    if any((pedigree_payload.get(field) or "").strip() for field in PEDIGREE_TEXT_FIELDS):
        return HorseProfileCompleteness.PARTIAL_PEDIGREE, HorseCompletionFailureReason.MISSING_PEDIGREE_FIELDS
    if any(value for key, value in profile_payload.items() if key != "source_refs"):
        return HorseProfileCompleteness.PROFILE_ONLY, HorseCompletionFailureReason.PROFILE_ONLY
    return HorseCompletionFailureReason.NO_EXTERNAL_MATCH, HorseCompletionFailureReason.NO_EXTERNAL_MATCH


def _career_history_snapshot(profile: HorseProfile) -> dict[str, Any]:
    return {
        "status": profile.career_history_status,
        "official_or_source_start_count": profile.official_or_source_start_count,
        "collected_start_count": profile.collected_start_count,
        "deduplicated_source_record_count": profile.deduplicated_source_record_count,
        "gap_count": profile.career_history_gap_count,
        "gap_reasons": profile.career_history_gap_reasons or [],
        "linked_race_event_count": profile.linked_race_event_count,
        "unlinked_race_record_count": profile.unlinked_race_record_count,
        "overseas_start_count": profile.overseas_start_count,
        "last_verified_at": (
            profile.career_history_last_verified_at.isoformat()
            if profile.career_history_last_verified_at
            else ""
        ),
    }


def _career_history_review_columns(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "career_history_status": snapshot["status"],
        "official_or_source_start_count": snapshot["official_or_source_start_count"],
        "collected_start_count": snapshot["collected_start_count"],
        "deduplicated_source_record_count": snapshot["deduplicated_source_record_count"],
        "career_history_gap_count": snapshot["gap_count"],
        "linked_race_event_count": snapshot["linked_race_event_count"],
        "unlinked_race_record_count": snapshot["unlinked_race_record_count"],
        "overseas_start_count": snapshot["overseas_start_count"],
    }


def plan_profile_completion(options: CompletionOptions | None = None) -> dict[str, Any]:
    options = options or CompletionOptions()
    queryset = HorseProfile.objects.select_related("primary_term").filter(primary_term__is_active=True)
    if options.regions:
        queryset = queryset.filter(racing_region__in=options.regions)
    queryset = queryset.order_by("racing_region", "id")
    if options.limit:
        queryset = queryset[: options.limit]
    rows: list[dict[str, Any]] = []
    region_summary: dict[str, dict[str, int]] = {}
    for profile in queryset:
        region = profile.racing_region or RacingRegion.OTHER
        summary = region_summary.setdefault(region, {"total": 0, "complete": 0, "partial": 0, "profile_only": 0, "unmatched": 0, "ambiguous": 0, "source_unavailable": 0, "rate_limited": 0})
        summary["total"] += 1
        sources = SOURCE_BY_REGION.get(region, [])
        if not sources:
            row = _row_for_failure(profile, HorseCompletionFailureReason.SOURCE_UNAVAILABLE, "地区暂无可用 adapter/source")
            rows.append(row)
            summary["source_unavailable"] += 1
            continue
        matches = _matches_for_profile(profile, sources)
        if not matches:
            row = _row_for_failure(profile, HorseCompletionFailureReason.NO_EXTERNAL_MATCH, "未在本地外部马匹索引中命中")
            rows.append(row)
            summary["unmatched"] += 1
            continue
        if len(matches) > 1:
            row = _row_for_failure(profile, HorseCompletionFailureReason.AMBIGUOUS_MATCH, "同一马匹命中多个外部候选", matches=matches)
            rows.append(row)
            summary["ambiguous"] += 1
            continue
        horse = matches[0]
        pedigree_payload = _pedigree_from_external_horse(horse)
        profile_payload = _profile_payload_from_external_horse(horse)
        completion_status, failure_reason = _completion_status(pedigree_payload, profile_payload)
        if completion_status == HorseProfileCompleteness.COMPLETE_PEDIGREE_2GEN:
            summary["complete"] += 1
        elif completion_status == HorseProfileCompleteness.PARTIAL_PEDIGREE:
            summary["partial"] += 1
        elif completion_status == HorseProfileCompleteness.PROFILE_ONLY:
            summary["profile_only"] += 1
        else:
            summary["unmatched"] += 1
        career_history = _career_history_snapshot(profile)
        row = {
            "profile_id": profile.pk,
            "display_name": profile.display_name,
            "racing_region": region,
            "source": horse.source,
            "external_horse_id": horse.horse_id,
            "source_url": _source_url(horse),
            "confidence": 95,
            "completion_status": completion_status,
            "failure_reason": failure_reason,
            "missing_fields": [field for field in PEDIGREE_TEXT_FIELDS if not (pedigree_payload.get(field) or "").strip()],
            "profile_payload": profile_payload,
            "pedigree_payload": pedigree_payload,
            "source_evidence": {
                "external_horse_id": horse.horse_id,
                "horse_name": horse.horse_name,
                "horse_name_en": horse.horse_name_en,
                "horse_name_zh_hant": horse.horse_name_zh_hant,
            },
            "career_history": career_history,
            **_career_history_review_columns(career_history),
            "reviewed": False,
        }
        rows.append(row)
    summary_payload = _summary(rows, region_summary)
    return {
        "artifact_type": "horse_profile_completion_plan",
        "generated_at": timezone.now().isoformat(),
        "dry_run": True,
        "options": {
            "regions": options.regions or [],
            "limit": options.limit,
            "request_interval_seconds": options.request_interval_seconds,
            "cache_dir": str(options.cache_dir),
        },
        "summary": summary_payload,
        "rows": rows,
    }


def _row_for_failure(profile: HorseProfile, reason: str, message: str, *, matches: list[ExternalHorse] | None = None) -> dict[str, Any]:
    career_history = _career_history_snapshot(profile)
    return {
        "profile_id": profile.pk,
        "display_name": profile.display_name,
        "racing_region": profile.racing_region,
        "source": "",
        "external_horse_id": "",
        "source_url": "",
        "confidence": 0,
        "completion_status": reason,
        "failure_reason": reason,
        "missing_fields": list(PEDIGREE_TEXT_FIELDS),
        "profile_payload": {},
        "pedigree_payload": {},
        "source_evidence": {
            "message": message,
            "matches": [{"source": item.source, "external_horse_id": item.horse_id, "horse_name": item.horse_name} for item in matches or []],
        },
        "career_history": career_history,
        **_career_history_review_columns(career_history),
        "reviewed": False,
    }


def _summary(rows: list[dict[str, Any]], region_summary: dict[str, dict[str, int]]) -> dict[str, Any]:
    total = len(rows)
    complete = sum(1 for row in rows if row.get("completion_status") == HorseProfileCompleteness.COMPLETE_PEDIGREE_2GEN)
    partial = sum(1 for row in rows if row.get("completion_status") == HorseProfileCompleteness.PARTIAL_PEDIGREE)
    failure_distribution = {key: 0 for key in FAILURE_KEYS}
    for row in rows:
        reason = row.get("failure_reason") or ""
        if reason in failure_distribution:
            failure_distribution[reason] += 1
    regions = {}
    for region, stats in region_summary.items():
        region_total = stats.get("total", 0)
        region_complete = stats.get("complete", 0)
        region_rows = [row for row in rows if row.get("racing_region") == region]
        regions[region] = {
            **stats,
            "not_complete": region_total - region_complete,
            "complete_ratio": round(region_complete / region_total, 4) if region_total else 0,
            "not_complete_ratio": round((region_total - region_complete) / region_total, 4) if region_total else 0,
            "career_history": {
                "source_start_count_total": sum(
                    int((row.get("career_history") or {}).get("official_or_source_start_count") or 0)
                    for row in region_rows
                ),
                "source_start_count_unknown_profiles": sum(
                    1
                    for row in region_rows
                    if (row.get("career_history") or {}).get("official_or_source_start_count") is None
                ),
                "collected_start_count_total": sum(
                    int((row.get("career_history") or {}).get("collected_start_count") or 0)
                    for row in region_rows
                ),
                "deduplicated_source_record_count_total": sum(
                    int((row.get("career_history") or {}).get("deduplicated_source_record_count") or 0)
                    for row in region_rows
                ),
                "gap_count_total": sum(
                    int((row.get("career_history") or {}).get("gap_count") or 0)
                    for row in region_rows
                ),
            },
        }
    return {
        "total": total,
        "complete_pedigree_2gen": complete,
        "partial_pedigree": partial,
        "not_complete": total - complete,
        "complete_ratio": round(complete / total, 4) if total else 0,
        "not_complete_ratio": round((total - complete) / total, 4) if total else 0,
        "failure_distribution": failure_distribution,
        "career_history": {
            "source_start_count_total": sum(
                int((row.get("career_history") or {}).get("official_or_source_start_count") or 0)
                for row in rows
            ),
            "collected_start_count_total": sum(
                int((row.get("career_history") or {}).get("collected_start_count") or 0)
                for row in rows
            ),
            "source_start_count_unknown_profiles": sum(
                1
                for row in rows
                if (row.get("career_history") or {}).get("official_or_source_start_count") is None
            ),
            "deduplicated_source_record_count_total": sum(
                int((row.get("career_history") or {}).get("deduplicated_source_record_count") or 0)
                for row in rows
            ),
            "gap_count_total": sum(
                int((row.get("career_history") or {}).get("gap_count") or 0)
                for row in rows
            ),
            "complete_profile_count": sum(
                1 for row in rows if (row.get("career_history") or {}).get("status") == "complete"
            ),
        },
        "regions": regions,
    }


def write_completion_artifacts(plan: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    output = Path(output_dir)
    rows = plan.get("rows") or []
    write_json_artifact(output / "horse_profile_completion_plan.json", plan)
    write_json_artifact(output / "summary.json", plan.get("summary") or {})
    write_csv_artifact(
        output / "horse_profile_completion_review.csv",
        rows,
        [
            "profile_id",
            "display_name",
            "racing_region",
            "source",
            "external_horse_id",
            "source_url",
            "confidence",
            "completion_status",
            "failure_reason",
            "missing_fields",
            "career_history_status",
            "official_or_source_start_count",
            "collected_start_count",
            "deduplicated_source_record_count",
            "career_history_gap_count",
            "linked_race_event_count",
            "unlinked_race_record_count",
            "overseas_start_count",
            "reviewed",
        ],
    )
    return {
        "plan": str(output / "horse_profile_completion_plan.json"),
        "summary": str(output / "summary.json"),
        "review_csv": str(output / "horse_profile_completion_review.csv"),
    }


def load_completion_artifact(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("artifact_type") != "horse_profile_completion_plan":
        raise ValueError("不是 horse profile completion plan artifact")
    if not payload.get("rows"):
        raise ValueError("artifact 中没有 rows")
    return payload


def apply_completion_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or []
    applied = skipped = candidates = conflicts = manual_lock_skipped = 0
    with transaction.atomic():
        for row in rows:
            profile = HorseProfile.objects.select_for_update().filter(pk=row.get("profile_id")).first()
            if profile is None:
                skipped += 1
                continue
            if row.get("failure_reason") == HorseCompletionFailureReason.AMBIGUOUS_MATCH:
                save_data_candidate(
                    profile=profile,
                    module=HorseProfileModule.PROFILE,
                    source_name=row.get("source") or "ambiguous",
                    source_url=row.get("source_url") or "",
                    candidate_payload=row,
                    raw_payload=row.get("source_evidence") or {},
                    confidence=0,
                )
                candidates += 1
                conflicts += 1
                continue
            if row.get("confidence", 0) < 90 or row.get("failure_reason") in {
                HorseCompletionFailureReason.NO_EXTERNAL_MATCH,
                HorseCompletionFailureReason.SOURCE_UNAVAILABLE,
                HorseCompletionFailureReason.RATE_LIMITED,
            }:
                skipped += 1
                continue
            profile_payload = row.get("profile_payload") or {}
            pedigree_payload = row.get("pedigree_payload") or {}
            fields = {}
            fields.update(profile_payload)
            fields.update(pedigree_payload)
            diff_payload = {
                "profile": build_candidate_diff(profile, HorseProfileModule.PROFILE, profile_payload),
                "pedigree": build_candidate_diff(profile, HorseProfileModule.PEDIGREE, pedigree_payload),
            }
            updated_fields = []
            for field, value in fields.items():
                if field == "source_refs":
                    value = {**(profile.source_refs or {}), "horse_profile_completion": value}
                if field not in {field.name for field in HorseProfile._meta.fields}:
                    continue
                if (profile.manual_lock_flags or {}).get(field):
                    manual_lock_skipped += 1
                    continue
                if value in (None, ""):
                    continue
                if getattr(profile, field, None) != value:
                    setattr(profile, field, value)
                    updated_fields.append(field)
            if updated_fields:
                profile.completeness_status = calculate_completeness(profile)
                profile.save(update_fields=[*updated_fields, "completeness_status", "updated_at"])
                applied += 1
                HorseProfileDataCandidate.objects.create(
                    profile=profile,
                    module=HorseProfileModule.PEDIGREE,
                    source_name=row.get("source") or "completion",
                    source_url=row.get("source_url") or "",
                    status=HorseProfileCandidateStatus.APPLIED,
                    confidence=row.get("confidence") or 0,
                    candidate_payload=fields,
                    diff_payload=diff_payload,
                    raw_payload=row.get("source_evidence") or {},
                    applied_at=timezone.now(),
                    result_summary=f"commit artifact applied fields={updated_fields}",
                )
            else:
                skipped += 1
    summary = {
        "applied": applied,
        "skipped": skipped,
        "candidates": candidates,
        "conflicts": conflicts,
        "manual_lock_skipped": manual_lock_skipped,
    }
    TaskExecutionLog.objects.create(
        task_name="horse_profile_completion_apply",
        status=TaskStatus.SUCCESS,
        payload=summary,
        detail=f"马匹补全 artifact 写入完成：{summary}",
        finished_at=timezone.now(),
    )
    return summary

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventDataQuality,
    RaceEventResult,
    RaceEventRunner,
    RaceEventStatus,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesName,
    RaceSeriesRelation,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.race_event_public_cache import invalidate_public_race_cache


INVENTORY_SCHEMA_VERSION = "1.0"
TARGET_START_YEAR = 1984
SUPPORTED_REGIONS = {
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.UNITED_KINGDOM,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
}
SOURCE_AUTHORITY_RANKS = {
    "reference": 10,
    "third_party": 20,
    "third_party_database": 30,
    "high_trust_database": 30,
    "third_party_high_access": 30,
    "official_archive": 40,
    "official": 50,
    "official_current": 50,
}
ACCOUNTED_RESOLUTIONS = {
    HistoricalRaceResolutionStatus.IMPORTED,
    HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE,
}
REQUIRED_ARTIFACTS = {
    "series_candidates",
    "series_conflicts",
    "annual_targets",
    "annual_targets_review",
    "gap_ledger",
    "summary",
}
MAPPING_REQUIRED_ARTIFACTS = {"mapping_candidates", "mapping_review", "mapping_conflicts", "summary"}
HISTORICAL_PUBLICATION_MANIFEST_SCHEMA_VERSION = "historical-race-publication/v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UNSTABLE_SERIES_KEY_RE = re.compile(r"(?:^|[-_])(?:19|20)\d{2}(?:[-_]\d{1,2}(?:[-_]\d{1,2})?)?(?:$|[-_])")
ALLOWED_RESOLUTION_TRANSITIONS = {
    HistoricalRaceResolutionStatus.PENDING: {
        HistoricalRaceResolutionStatus.PENDING,
        HistoricalRaceResolutionStatus.READY,
        HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE,
        HistoricalRaceResolutionStatus.IDENTITY_REVIEW_REQUIRED,
        HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE,
    },
    HistoricalRaceResolutionStatus.READY: {
        HistoricalRaceResolutionStatus.READY,
        HistoricalRaceResolutionStatus.PENDING,
        HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE,
        HistoricalRaceResolutionStatus.IDENTITY_REVIEW_REQUIRED,
        HistoricalRaceResolutionStatus.IMPORTED,
    },
    HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE: {
        HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE,
        HistoricalRaceResolutionStatus.PENDING,
        HistoricalRaceResolutionStatus.READY,
        HistoricalRaceResolutionStatus.IDENTITY_REVIEW_REQUIRED,
        HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE,
    },
    HistoricalRaceResolutionStatus.IDENTITY_REVIEW_REQUIRED: {
        HistoricalRaceResolutionStatus.IDENTITY_REVIEW_REQUIRED,
        HistoricalRaceResolutionStatus.PENDING,
        HistoricalRaceResolutionStatus.READY,
        HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE,
        HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE,
    },
    HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE: {
        HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE,
        HistoricalRaceResolutionStatus.PENDING,
    },
    HistoricalRaceResolutionStatus.IMPORTED: {HistoricalRaceResolutionStatus.IMPORTED},
}
IMPORTED_TARGET_MATERIAL_FIELDS = (
    "expectation_status",
    "original_name",
    "chinese_name",
    "grade_text",
    "normalized_grade",
    "racecourse",
    "surface",
    "distance_text",
    "local_date",
)


class InventoryValidationError(ValueError):
    pass


class HistoricalPublicationBlockedError(InventoryValidationError):
    pass


@dataclass(frozen=True)
class ArtifactIdentity:
    path: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class HistoricalPublicationManifest:
    path: Path
    sha256: str
    target_ids: tuple[int, ...]
    artifact_sha256_by_target: dict[int, str]


@dataclass(frozen=True)
class HistoricalPublicationFacts:
    confirmed_result_event_ids: frozenset[int]
    runner_event_ids: frozenset[int]
    runner_provenance_missing_event_ids: frozenset[int]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def file_identity(path: str | Path, *, relative_to: str | Path | None = None) -> ArtifactIdentity:
    source = Path(path)
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    identity_path = str(source.relative_to(relative_to)) if relative_to else str(source)
    return ArtifactIdentity(path=identity_path, size=size, sha256=digest.hexdigest())


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _value_identity(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return canonical_json(value)


def _series_name_identity(value: str) -> str:
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = re.sub(r"\s*\(\s*[HR]\s*\)\s*$", "", value, flags=re.I)
    value = re.sub(r"\bH\.?\s+(?=(?:Stp|Hurdle)\b)", "", value, flags=re.I)
    value = re.sub(r"(?:\s+[SHR]\.?)\s*$", "", value, flags=re.I)
    punctuation_spaced = "".join(" " if unicodedata.category(char)[0] in {"P", "S"} else char for char in value)
    ascii_value = unicodedata.normalize("NFKD", punctuation_spaced).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.casefold()))


def sanitize_structured_row_evidence(payload: dict[str, Any], *, max_bytes: int = 64 * 1024) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InventoryValidationError("row evidence must be an object")

    def inspect(value: Any, path: str) -> None:
        if isinstance(value, (bytes, bytearray, memoryview)):
            raise InventoryValidationError(f"row evidence contains binary document data: {path}")
        if isinstance(value, str):
            lowered = value.lstrip().casefold()
            if lowered.startswith("%pdf") or "<html" in lowered or "<!doctype html" in lowered:
                raise InventoryValidationError(f"row evidence contains a full document: {path}")
            return
        if isinstance(value, dict):
            for key, child in value.items():
                inspect(child, f"{path}.{key}")
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                inspect(child, f"{path}[{index}]")

    inspect(payload, "row")
    encoded = canonical_json(payload).encode("utf-8")
    if len(encoded) > max_bytes:
        raise InventoryValidationError(
            f"row evidence exceeds structured payload limit: {len(encoded)} > {max_bytes}"
        )
    return json.loads(encoded.decode("utf-8"))


def merge_authoritative_fields(
    candidates: Iterable[dict[str, Any]],
    *,
    existing_fields: dict[str, Any] | None = None,
    existing_provenance: dict[str, dict[str, Any]] | None = None,
    manual_locks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge field candidates by authority; conflicts at the winning tier block."""

    existing_fields = dict(existing_fields or {})
    existing_provenance = dict(existing_provenance or {})
    manual_locks = dict(manual_locks or {})
    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        authority = str(candidate.get("source_authority") or "").strip()
        if authority not in SOURCE_AUTHORITY_RANKS:
            raise InventoryValidationError(f"unsupported source authority: {authority or '<empty>'}")
        source = {
            "source_authority": authority,
            "source_id": str(candidate.get("source_id") or ""),
            "source_url": str(candidate.get("source_url") or ""),
            "snapshot_sha256": str(candidate.get("snapshot_sha256") or ""),
            "parser_version": str(candidate.get("parser_version") or ""),
        }
        fields = candidate.get("fields")
        if not isinstance(fields, dict):
            raise InventoryValidationError("candidate fields must be an object")
        for field, value in fields.items():
            if not _is_blank(value):
                by_field[str(field)].append({"value": value, **source})

    merged = dict(existing_fields)
    provenance = dict(existing_provenance)
    conflicts: list[dict[str, Any]] = []
    lower_authority_disagreements: list[dict[str, Any]] = []
    skipped_manual: list[dict[str, Any]] = []
    for field, values in sorted(by_field.items()):
        if manual_locks.get(field) and not _is_blank(existing_fields.get(field)):
            skipped_manual.append({"field": field, "existing": existing_fields[field], "candidates": values})
            continue

        existing_value = existing_fields.get(field)
        existing_source = existing_provenance.get(field) or {}
        existing_authority = str(existing_source.get("source_authority") or "")
        if not _is_blank(existing_value) and existing_authority in SOURCE_AUTHORITY_RANKS:
            values.append({"value": existing_value, **existing_source, "is_existing": True})

        winning_rank = max(SOURCE_AUTHORITY_RANKS[item["source_authority"]] for item in values)
        winners = [item for item in values if SOURCE_AUTHORITY_RANKS[item["source_authority"]] == winning_rank]
        winner_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in winners:
            winner_groups[_value_identity(item["value"])].append(item)
        if len(winner_groups) > 1:
            conflicts.append({"field": field, "rank": winning_rank, "candidates": winners})
            continue

        winner = winners[0]
        merged[field] = winner["value"]
        provenance[field] = {key: value for key, value in winner.items() if key != "value" and key != "is_existing"}
        for item in values:
            if _value_identity(item["value"]) == _value_identity(winner["value"]):
                continue
            if SOURCE_AUTHORITY_RANKS[item["source_authority"]] < winning_rank:
                lower_authority_disagreements.append(
                    {"field": field, "selected": winner, "lower_authority_candidate": item}
                )

    return {
        "fields": merged,
        "field_provenance": provenance,
        "conflicts": conflicts,
        "lower_authority_disagreements": lower_authority_disagreements,
        "skipped_manual": skipped_manual,
        "blocked": bool(conflicts),
    }


def relation_cycle_path(from_series_id: int, to_series_id: int) -> list[int]:
    if from_series_id == to_series_id:
        return [from_series_id, to_series_id]
    adjacency: dict[int, list[int]] = defaultdict(list)
    for source_id, target_id in RaceSeriesRelation.objects.filter(
        review_status=RaceSeriesReviewStatus.APPROVED
    ).values_list("from_series_id", "to_series_id"):
        adjacency[source_id].append(target_id)
    queue: deque[tuple[int, list[int]]] = deque([(to_series_id, [to_series_id])])
    visited = {to_series_id}
    while queue:
        node, path = queue.popleft()
        for next_node in adjacency[node]:
            if next_node == from_series_id:
                return [from_series_id, *path, from_series_id]
            if next_node not in visited:
                visited.add(next_node)
                queue.append((next_node, [*path, next_node]))
    return []


def validate_series_relation(relation: RaceSeriesRelation) -> None:
    relation.full_clean()
    if relation.from_series_id and relation.to_series_id:
        cycle = relation_cycle_path(relation.from_series_id, relation.to_series_id)
        if cycle:
            raise ValidationError({"to_series": f"赛事系列关系会形成循环：{' -> '.join(map(str, cycle))}"})


def validate_series_name_period(name: RaceSeriesName) -> None:
    name.full_clean()
    normalized = " ".join(name.text.casefold().split())
    start = name.valid_from_year or 0
    end = name.valid_to_year or 9999
    overlaps = RaceSeriesName.objects.filter(
        series=name.series,
        source_language=name.source_language,
        normalized_text=normalized,
    ).exclude(pk=name.pk)
    for existing in overlaps:
        existing_start = existing.valid_from_year or 0
        existing_end = existing.valid_to_year or 9999
        if max(start, existing_start) <= min(end, existing_end):
            raise ValidationError({"valid_from_year": f"名称有效期与记录 {existing.pk} 重叠。"})


def propose_series_mapping(*, name: str, region: str, year: int, fuzzy_threshold: float = 0.88) -> dict[str, Any]:
    normalized = " ".join(str(name).casefold().split())
    approved_series = list(
        RaceSeries.objects.filter(
            country_region=region,
            review_status=RaceSeriesReviewStatus.APPROVED,
        )
    )
    names = RaceSeriesName.objects.select_related("series").filter(
        series__country_region=region,
        series__review_status=RaceSeriesReviewStatus.APPROVED,
    )
    valid_names = [
        item
        for item in names
        if (not item.valid_from_year or item.valid_from_year <= year)
        and (not item.valid_to_year or item.valid_to_year >= year)
    ]
    exact_series = {item.series for item in valid_names if item.normalized_text == normalized}
    exact_series.update(
        series
        for series in approved_series
        if " ".join(series.canonical_name_original.casefold().split()) == normalized
    )
    if len(exact_series) == 1:
        matched = next(iter(exact_series))
        return {
            "status": "matched",
            "series_key": matched.key,
            "match_type": "exact_historical_name",
            "confidence": 1.0,
        }
    if len(exact_series) > 1:
        return {
            "status": HistoricalRaceResolutionStatus.IDENTITY_REVIEW_REQUIRED,
            "reason": "ambiguous_exact_name",
            "candidates": sorted(series.key for series in exact_series),
        }
    fuzzy = []
    for item in valid_names:
        score = SequenceMatcher(None, normalized, item.normalized_text).ratio()
        if score >= fuzzy_threshold:
            fuzzy.append({"series_key": item.series.key, "score": round(score, 4), "name": item.text})
    for series in approved_series:
        score = SequenceMatcher(None, normalized, " ".join(series.canonical_name_original.casefold().split())).ratio()
        if score >= fuzzy_threshold:
            fuzzy.append(
                {"series_key": series.key, "score": round(score, 4), "name": series.canonical_name_original}
            )
    fuzzy_by_series: dict[str, dict[str, Any]] = {}
    for candidate in fuzzy:
        current = fuzzy_by_series.get(candidate["series_key"])
        if current is None or candidate["score"] > current["score"]:
            fuzzy_by_series[candidate["series_key"]] = candidate
    return {
        "status": HistoricalRaceResolutionStatus.IDENTITY_REVIEW_REQUIRED,
        "reason": "fuzzy_match_requires_review" if fuzzy else "no_authoritative_mapping",
        "candidates": sorted(fuzzy_by_series.values(), key=lambda item: (-item["score"], item["series_key"])),
    }


def validate_permanent_unavailable_evidence(evidence: dict[str, Any]) -> None:
    if not isinstance(evidence, dict):
        raise ValidationError("永久不可得证据必须为对象。")
    official = evidence.get("official_archive")
    independent = evidence.get("independent_source")
    if not isinstance(official, dict) or not isinstance(independent, dict):
        raise ValidationError("永久不可得必须同时具备官方档案和独立可信来源证据。")
    required = {"url", "checked_at", "query_scope", "snapshot_sha256"}
    for label, item in (("official_archive", official), ("independent_source", independent)):
        missing = sorted(key for key in required if not str(item.get(key) or "").strip())
        if missing:
            raise ValidationError(f"{label} 缺少证据字段：{', '.join(missing)}")
        if urlparse(str(item["url"])).scheme not in {"http", "https"}:
            raise ValidationError(f"{label} URL 无效。")
    official_identity = str(official.get("source_identity") or urlparse(str(official["url"])).netloc).casefold()
    independent_identity = str(
        independent.get("source_identity") or urlparse(str(independent["url"])).netloc
    ).casefold()
    if not official_identity or official_identity == independent_identity:
        raise ValidationError("两份永久不可得证据必须来自相互独立的信息源。")


def validate_resolution_transition(
    target: HistoricalRaceEventTarget,
    new_resolution: str,
    *,
    permanent_evidence: dict[str, Any] | None = None,
) -> None:
    current = target.resolution_status or HistoricalRaceResolutionStatus.PENDING
    if new_resolution not in ALLOWED_RESOLUTION_TRANSITIONS.get(current, set()):
        raise ValidationError(
            {"resolution_status": f"不允许从 {current} 直接转换到 {new_resolution}。"}
        )
    if new_resolution == HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE:
        validate_permanent_unavailable_evidence(permanent_evidence or target.permanent_unavailable_evidence)


def transition_target_resolution(
    target: HistoricalRaceEventTarget,
    new_resolution: str,
    *,
    actor=None,
    reason: str,
    artifact_sha256: str = "",
    permanent_evidence: dict[str, Any] | None = None,
) -> HistoricalRaceEventTarget:
    validate_resolution_transition(target, new_resolution, permanent_evidence=permanent_evidence)
    before = target.resolution_status
    if new_resolution == HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE:
        if actor is None:
            raise ValidationError("批准永久不可得必须记录操作人。")
        target.permanent_unavailable_evidence = permanent_evidence or {}
        target.permanent_unavailable_approved_by = actor
        target.permanent_unavailable_approved_at = timezone.now()
    elif before == HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE:
        target.permanent_unavailable_evidence = {}
        target.permanent_unavailable_approved_by = None
        target.permanent_unavailable_approved_at = None
    target.resolution_status = new_resolution
    target.artifact_sha256 = artifact_sha256 or target.artifact_sha256
    target.last_checked_at = timezone.now()
    target.full_clean()
    target.save()
    OperationLog.objects.create(
        admin=actor,
        action_type="historical_target_resolution_transition",
        target_type="historical_race_event_target",
        target_id=str(target.pk),
        detail=canonical_json(
            {
                "before": before,
                "after": new_resolution,
                "reason": reason,
                "artifact_sha256": artifact_sha256,
            }
        ),
    )
    return target


def target_is_accounted(target: HistoricalRaceEventTarget | dict[str, Any]) -> bool:
    expectation = (
        target.expectation_status if isinstance(target, HistoricalRaceEventTarget) else target["expectation_status"]
    )
    resolution = (
        target.resolution_status if isinstance(target, HistoricalRaceEventTarget) else target["resolution_status"]
    )
    return expectation in {
        HistoricalRaceExpectationStatus.NOT_HELD,
        HistoricalRaceExpectationStatus.NOT_DUE,
    } or resolution in ACCOUNTED_RESOLUTIONS


def expectation_status_for_date(
    *,
    target_year: int,
    local_date: date | None,
    today: date | None = None,
    result_grace_days: int = 7,
) -> str:
    today = today or timezone.localdate()
    if result_grace_days < 0:
        raise InventoryValidationError("result grace days must be non-negative")
    if local_date is not None:
        return (
            HistoricalRaceExpectationStatus.NOT_DUE
            if today <= local_date + timedelta(days=result_grace_days)
            else HistoricalRaceExpectationStatus.HELD
        )
    return (
        HistoricalRaceExpectationStatus.NOT_DUE
        if target_year >= today.year
        else HistoricalRaceExpectationStatus.HELD
    )


def inventory_summary(targets: Iterable[HistoricalRaceEventTarget | dict[str, Any]]) -> dict[str, Any]:
    rows = list(targets)
    expectation_counts = Counter(
        row.expectation_status if isinstance(row, HistoricalRaceEventTarget) else row["expectation_status"]
        for row in rows
    )
    resolution_counts = Counter(
        row.resolution_status if isinstance(row, HistoricalRaceEventTarget) else row["resolution_status"]
        for row in rows
    )
    accounted = sum(1 for row in rows if target_is_accounted(row))
    complete = sum(
        1
        for row in rows
        if (
            row.resolution_status if isinstance(row, HistoricalRaceEventTarget) else row["resolution_status"]
        )
        == HistoricalRaceResolutionStatus.IMPORTED
    )
    denominator = len(rows)
    breakdowns: dict[str, dict[str, int]] = {
        "country_region": defaultdict(int),
        "decade": defaultdict(int),
        "series": defaultdict(int),
    }
    for row in rows:
        if isinstance(row, HistoricalRaceEventTarget):
            region = row.country_region
            year = row.year
            series_key = row.race_series.key
        else:
            region = str(row.get("country_region") or "unknown")
            year = int(row.get("year") or 0)
            series_key = str(row.get("series_key") or "unknown")
        breakdowns["country_region"][region] += 1
        breakdowns["decade"][f"{(year // 10) * 10}s" if year else "unknown"] += 1
        breakdowns["series"][series_key] += 1
    return {
        "target_count": denominator,
        "accounted_count": accounted,
        "data_complete_count": complete,
        "accounted_rate": accounted / denominator if denominator else 1.0,
        "data_complete_rate": complete / denominator if denominator else 1.0,
        "expectation_counts": dict(sorted(expectation_counts.items())),
        "resolution_counts": dict(sorted(resolution_counts.items())),
        "breakdowns": {
            key: dict(sorted(values.items())) for key, values in breakdowns.items()
        },
    }


def iter_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InventoryValidationError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise InventoryValidationError(f"JSONL row must be an object at {path}:{line_number}")
            yield payload


def _normalize_inventory_record(record: dict[str, Any], *, source_kind: str) -> dict[str, Any]:
    series_key = str(record.get("series_key") or "").strip()
    region = str(record.get("country_region") or record.get("region") or "").strip()
    if not series_key:
        raise InventoryValidationError("inventory row is missing series_key")
    if region not in SUPPORTED_REGIONS:
        raise InventoryValidationError(f"unsupported inventory region: {region or '<empty>'}")
    try:
        year = int(record["year"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InventoryValidationError(f"inventory row has invalid year: {record.get('year')}") from exc
    if year < TARGET_START_YEAR:
        raise InventoryValidationError(f"inventory row is earlier than {TARGET_START_YEAR}: {series_key}/{year}")
    expectation = str(record.get("expectation_status") or HistoricalRaceExpectationStatus.HELD)
    resolution = str(record.get("resolution_status") or HistoricalRaceResolutionStatus.PENDING)
    if expectation not in HistoricalRaceExpectationStatus.values:
        raise InventoryValidationError(f"unsupported expectation status: {expectation}")
    if resolution not in HistoricalRaceResolutionStatus.values:
        raise InventoryValidationError(f"unsupported resolution status: {resolution}")
    source_refs = dict(record.get("source_refs")) if isinstance(record.get("source_refs"), dict) else {}
    for key in ("season_label", "source_scope", "discipline"):
        if record.get(key) not in (None, ""):
            source_refs.setdefault(key, record[key])
    return {
        "series_key": series_key,
        "country_region": region,
        "year": year,
        "canonical_name_original": str(record.get("canonical_name_original") or record.get("original_name") or "").strip(),
        "chinese_name": str(record.get("chinese_name") or "").strip(),
        "founded_year": record.get("founded_year"),
        "ended_year": record.get("ended_year"),
        "series_status": str(record.get("series_status") or "unknown"),
        "expectation_status": expectation,
        "resolution_status": resolution,
        "original_name": str(record.get("original_name") or "").strip(),
        "grade_text": str(record.get("grade_text") or "").strip(),
        "normalized_grade": str(record.get("normalized_grade") or "").strip(),
        "racecourse": str(record.get("racecourse") or "").strip(),
        "surface": str(record.get("surface") or "").strip(),
        "distance_text": str(record.get("distance_text") or "").strip(),
        "local_date": str(record.get("local_date") or "").strip(),
        "module_statuses": record.get("module_statuses") if isinstance(record.get("module_statuses"), dict) else {},
        "field_provenance": record.get("field_provenance") if isinstance(record.get("field_provenance"), dict) else {},
        "source_refs": source_refs,
        "source_kind": source_kind,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _prepare_artifact_output(output: Path, *, label: str) -> None:
    if output.exists() and any(output.iterdir()):
        raise InventoryValidationError(f"{label} output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)


def build_inventory_artifact(
    *,
    catalog_paths: Iterable[str | Path],
    timeline_paths: Iterable[str | Path],
    output_dir: str | Path,
) -> dict[str, Any]:
    catalog_paths = tuple(catalog_paths)
    timeline_paths = tuple(timeline_paths)
    output = Path(output_dir)
    _prepare_artifact_output(output, label="inventory")
    target_rows: dict[tuple[str, int], dict[str, Any]] = {}
    series_rows: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []

    for source_kind, paths in (("catalog", catalog_paths), ("timeline", timeline_paths)):
        for path in paths:
            for raw in iter_jsonl(path):
                row = _normalize_inventory_record(raw, source_kind=source_kind)
                key = row["series_key"]
                existing_series = series_rows.get(key)
                series_candidate = {
                    "key": key,
                    "country_region": row["country_region"],
                    "canonical_name_original": row["canonical_name_original"],
                    "chinese_name": row["chinese_name"],
                    "founded_year": row["founded_year"],
                    "ended_year": row["ended_year"],
                    "status": row["series_status"],
                    "review_status": RaceSeriesReviewStatus.PENDING,
                    "source_refs": row["source_refs"],
                }
                if existing_series is None:
                    series_rows[key] = series_candidate
                elif existing_series["country_region"] != row["country_region"]:
                    conflicts.append(
                        {
                            "conflict_type": "series_region_conflict",
                            "series_key": key,
                            "year": row["year"],
                            "existing": existing_series["country_region"],
                            "candidate": row["country_region"],
                        }
                    )
                elif (
                    existing_series["canonical_name_original"]
                    and row["canonical_name_original"]
                    and _series_name_identity(existing_series["canonical_name_original"])
                    != _series_name_identity(row["canonical_name_original"])
                ):
                    conflicts.append(
                        {
                            "conflict_type": "series_canonical_name_conflict",
                            "series_key": key,
                            "year": row["year"],
                            "existing": existing_series["canonical_name_original"],
                            "candidate": row["canonical_name_original"],
                        }
                    )
                elif not existing_series["canonical_name_original"] and row["canonical_name_original"]:
                    existing_series["canonical_name_original"] = row["canonical_name_original"]

                target_key = (key, row["year"])
                existing_target = target_rows.get(target_key)
                if existing_target is None or (existing_target["source_kind"] == "catalog" and source_kind == "timeline"):
                    target_rows[target_key] = row
                elif canonical_json(existing_target) != canonical_json(row):
                    conflicts.append(
                        {
                            "conflict_type": "annual_target_conflict",
                            "series_key": key,
                            "year": row["year"],
                            "existing": canonical_json(existing_target),
                            "candidate": canonical_json(row),
                        }
                    )

    sorted_series = [series_rows[key] for key in sorted(series_rows)]
    sorted_targets = [target_rows[key] for key in sorted(target_rows, key=lambda item: (target_rows[item]["country_region"], item[1], item[0]))]
    series_path = output / "series_candidates.jsonl"
    conflict_path = output / "series_conflicts.csv"
    targets_path = output / "annual_targets.jsonl"
    review_path = output / "annual_targets_review.csv"
    gaps_path = output / "gap_ledger.csv"
    summary_path = output / "summary.json"
    _write_jsonl(series_path, sorted_series)
    _write_csv(
        conflict_path,
        conflicts,
        ["conflict_type", "series_key", "year", "existing", "candidate"],
    )
    _write_jsonl(targets_path, sorted_targets)
    review_rows = [
        {
            "country_region": row["country_region"],
            "year": row["year"],
            "series_key": row["series_key"],
            "original_name": row["original_name"],
            "expectation_status": row["expectation_status"],
            "resolution_status": row["resolution_status"],
            "operator_decision": "",
            "operator_notes": "",
        }
        for row in sorted_targets
    ]
    _write_csv(
        review_path,
        review_rows,
        [
            "country_region",
            "year",
            "series_key",
            "original_name",
            "expectation_status",
            "resolution_status",
            "operator_decision",
            "operator_notes",
        ],
    )
    gap_rows = [
        row
        for row in review_rows
        if not target_is_accounted(row)
        and row["resolution_status"] != HistoricalRaceResolutionStatus.READY
    ]
    _write_csv(
        gaps_path,
        gap_rows,
        ["country_region", "year", "series_key", "original_name", "expectation_status", "resolution_status"],
    )
    summary = inventory_summary(sorted_targets)
    summary.update({"series_count": len(sorted_series), "conflict_count": len(conflicts)})
    _write_json(summary_path, summary)

    artifact_paths = {
        "series_candidates": series_path,
        "series_conflicts": conflict_path,
        "annual_targets": targets_path,
        "annual_targets_review": review_path,
        "gap_ledger": gaps_path,
        "summary": summary_path,
    }
    manifest = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "generated_at": timezone.now().isoformat(),
        "artifacts": {
            name: file_identity(path, relative_to=output).as_dict() for name, path in artifact_paths.items()
        },
        "inputs": [
            file_identity(path).as_dict() for path in [*catalog_paths, *timeline_paths]
        ],
    }
    manifest_path = output / "manifest.json"
    _write_json(manifest_path, manifest)
    approval_path = output / "approval.json"
    _write_json(
        approval_path,
        {
            "schema_version": INVENTORY_SCHEMA_VERSION,
            "status": "pending",
            "manifest_identity": file_identity(manifest_path, relative_to=output).as_dict(),
            "approved_by": "",
            "approved_at": "",
        },
    )
    return {
        "output_dir": str(output),
        "manifest": str(manifest_path),
        "approval": str(approval_path),
        **summary,
    }


def _artifact_path(root: Path, relative: Any, *, label: str) -> Path:
    text = str(relative or "").strip()
    path = root / text
    candidate = path.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise InventoryValidationError(f"{label} is outside artifact directory: {text}") from exc
    return path


def validate_inventory_artifact(artifact_dir: str | Path, approval_path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(artifact_dir)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise InventoryValidationError("inventory manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        raise InventoryValidationError("inventory manifest schema is unsupported")
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    missing = sorted(REQUIRED_ARTIFACTS - set(artifacts))
    if missing:
        raise InventoryValidationError(f"inventory manifest is incomplete: {', '.join(missing)}")
    for name, expected in artifacts.items():
        if not isinstance(expected, dict):
            raise InventoryValidationError(f"inventory artifact identity is invalid: {name}")
        path = _artifact_path(root, expected.get("path"), label=f"inventory artifact {name}")
        if not path.is_file():
            raise InventoryValidationError(f"inventory artifact is missing: {name}")
        actual = file_identity(path, relative_to=root).as_dict()
        if actual != expected:
            raise InventoryValidationError(f"inventory artifact changed after manifest: {name}")

    approval = json.loads(Path(approval_path).read_text(encoding="utf-8"))
    actual_manifest = file_identity(manifest_path, relative_to=root).as_dict()
    if approval.get("manifest_identity") != actual_manifest:
        raise InventoryValidationError("inventory approval does not match manifest")
    if approval.get("status") != "approved":
        raise InventoryValidationError("inventory artifact is not approved")
    if not str(approval.get("approved_by") or "").strip() or not str(approval.get("approved_at") or "").strip():
        raise InventoryValidationError("inventory approval is missing operator evidence")
    return manifest, approval


def _parse_optional_date(value: Any):
    if not value:
        return None
    return datetime.fromisoformat(str(value)).date()


def commit_inventory_artifact(*, artifact_dir: str | Path, approval_path: str | Path) -> dict[str, int]:
    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        raise InventoryValidationError("historical race backfill is disabled")
    root = Path(artifact_dir)
    manifest, approval = validate_inventory_artifact(root, approval_path)
    manifest_sha = file_identity(root / "manifest.json", relative_to=root).sha256
    conflicts_path = _artifact_path(
        root,
        manifest["artifacts"]["series_conflicts"]["path"],
        label="series conflicts",
    )
    with conflicts_path.open("r", encoding="utf-8-sig", newline="") as handle:
        if any(True for _ in csv.DictReader(handle)):
            raise InventoryValidationError("inventory has unresolved series conflicts")

    series_created = 0
    series_updated = 0
    targets_created = 0
    targets_updated = 0
    approver = get_user_model().objects.filter(username=str(approval["approved_by"])).first()
    if approver is None:
        raise InventoryValidationError("inventory approver account does not exist")
    with transaction.atomic():
        series_by_key: dict[str, RaceSeries] = {}
        series_path = _artifact_path(
            root,
            manifest["artifacts"]["series_candidates"]["path"],
            label="series candidates",
        )
        for row in iter_jsonl(series_path):
            defaults = {
                "country_region": row["country_region"],
                "canonical_name_original": row["canonical_name_original"],
                "chinese_name": row.get("chinese_name", ""),
                "founded_year": row.get("founded_year"),
                "ended_year": row.get("ended_year"),
                "status": row.get("status", "unknown"),
                "review_status": RaceSeriesReviewStatus.APPROVED,
                "source_refs": row.get("source_refs") or {},
            }
            existing_series = RaceSeries.objects.select_for_update().filter(key=row["key"]).first()
            if existing_series and existing_series.country_region != row["country_region"]:
                raise InventoryValidationError(f"existing series region conflict: {row['key']}")
            if existing_series and existing_series.review_status == RaceSeriesReviewStatus.REJECTED:
                raise InventoryValidationError(f"existing series was rejected: {row['key']}")
            if existing_series is None:
                series = RaceSeries.objects.create(key=row["key"], **defaults)
                created = True
                changed = False
            else:
                series = existing_series
                locked = dict(series.manual_lock_flags or {})
                update_fields = []
                for field, value in defaults.items():
                    if locked.get(field) and not _is_blank(getattr(series, field)):
                        continue
                    if getattr(series, field) != value:
                        setattr(series, field, value)
                        update_fields.append(field)
                series.full_clean()
                if update_fields:
                    series.save(update_fields=set(update_fields))
                created = False
                changed = bool(update_fields)
            series.full_clean()
            series_by_key[series.key] = series
            series_created += int(created)
            series_updated += int(changed)

        targets_path = _artifact_path(
            root,
            manifest["artifacts"]["annual_targets"]["path"],
            label="annual targets",
        )
        for row in iter_jsonl(targets_path):
            series = series_by_key.get(row["series_key"]) or RaceSeries.objects.get(key=row["series_key"])
            defaults = {
                "country_region": series.country_region,
                "expectation_status": row["expectation_status"],
                "resolution_status": row["resolution_status"],
                "original_name": row.get("original_name", ""),
                "chinese_name": row.get("chinese_name", ""),
                "grade_text": row.get("grade_text", ""),
                "normalized_grade": row.get("normalized_grade", ""),
                "racecourse": row.get("racecourse", ""),
                "surface": row.get("surface", ""),
                "distance_text": row.get("distance_text", ""),
                "local_date": _parse_optional_date(row.get("local_date")),
                "module_statuses": row.get("module_statuses") or {},
                "field_provenance": row.get("field_provenance") or {},
                "source_refs": row.get("source_refs") or {},
                "artifact_sha256": manifest_sha,
            }
            existing = (
                HistoricalRaceEventTarget.objects.select_for_update()
                .filter(race_series=series, year=row["year"])
                .first()
            )
            if existing and existing.resolution_status == HistoricalRaceResolutionStatus.IMPORTED:
                material_changes = {
                    field: {"existing": getattr(existing, field), "candidate": defaults[field]}
                    for field in IMPORTED_TARGET_MATERIAL_FIELDS
                    if getattr(existing, field) != defaults[field]
                }
                if material_changes:
                    raise InventoryValidationError(
                        "imported target facts changed; use an approved correction batch: "
                        + ", ".join(sorted(material_changes))
                    )
                defaults["resolution_status"] = HistoricalRaceResolutionStatus.IMPORTED
                defaults["event"] = existing.event
                defaults["module_statuses"] = existing.module_statuses
                defaults["field_provenance"] = existing.field_provenance
            elif existing and existing.resolution_status == HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE:
                material_changes = {
                    field: {"existing": getattr(existing, field), "candidate": defaults[field]}
                    for field in IMPORTED_TARGET_MATERIAL_FIELDS
                    if getattr(existing, field) != defaults[field]
                }
                if material_changes:
                    raise InventoryValidationError(
                        "permanently unavailable target facts changed; reopen it explicitly: "
                        + ", ".join(sorted(material_changes))
                    )
                defaults["resolution_status"] = HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE
                defaults["module_statuses"] = existing.module_statuses
                defaults["field_provenance"] = existing.field_provenance
            if existing is None:
                target = HistoricalRaceEventTarget.objects.create(
                    race_series=series,
                    year=row["year"],
                    **defaults,
                )
                created = True
                changed = False
            else:
                target = existing
                update_fields = []
                for field, value in defaults.items():
                    if getattr(target, field) != value:
                        setattr(target, field, value)
                        update_fields.append(field)
                target.full_clean()
                if update_fields:
                    target.save(update_fields=set(update_fields))
                created = False
                changed = bool(update_fields)
            target.full_clean()
            targets_created += int(created)
            targets_updated += int(changed)

        OperationLog.objects.get_or_create(
            action_type="historical_inventory_commit",
            target_type="historical_race_inventory",
            target_id=manifest_sha[:64],
            defaults={
                "admin": approver,
                "detail": canonical_json(
                    {
                        "manifest_sha256": manifest_sha,
                        "series_created": series_created,
                        "series_updated": series_updated,
                        "targets_created": targets_created,
                        "targets_updated": targets_updated,
                    }
                )
            },
        )
    return {
        "series_created": series_created,
        "series_updated": series_updated,
        "targets_created": targets_created,
        "targets_updated": targets_updated,
    }


def _mapping_key_for_event(event, override: dict[str, Any] | None) -> tuple[str, str, str]:
    override = override or {}
    if override:
        proposed = str(override.get("series_key") or "").strip()
        status = str(override.get("status") or "").strip()
        if status == "approved" and proposed:
            return proposed, status, "operator_override"
        return proposed, "review_required", "invalid_operator_override"
    legacy = str(event.series_key or "").strip()
    if not legacy:
        fallback = slugify(event.original_name or event.chinese_name)[:140]
        return f"{event.country_region}-{fallback}", "review_required", "missing_legacy_series_key"
    if UNSTABLE_SERIES_KEY_RE.search(legacy):
        return legacy, "review_required", "year_or_date_in_legacy_key"
    return legacy, "approved", "stable_legacy_key"


def build_existing_event_mapping_artifact(
    *,
    output_dir: str | Path,
    year: int = 2026,
    overrides_path: str | Path | None = None,
) -> dict[str, Any]:
    from stable.models import RaceEvent

    output = Path(output_dir)
    _prepare_artifact_output(output, label="mapping")
    overrides: dict[str, Any] = {}
    if overrides_path:
        payload = json.loads(Path(overrides_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise InventoryValidationError("mapping overrides must be an object keyed by event id")
        overrides = payload

    events = list(RaceEvent.objects.filter(year=year).order_by("country_region", "slug", "id"))
    rows: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    by_legacy_key: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for event in events:
        by_legacy_key[(event.country_region, str(event.series_key or ""))].append(event)
    duplicate_event_ids = {
        event.id
        for grouped in by_legacy_key.values()
        if len(grouped) > 1
        for event in grouped
    }
    for event in events:
        proposed, status, reason = _mapping_key_for_event(event, overrides.get(str(event.id)))
        if event.id in duplicate_event_ids and reason != "operator_override":
            status = "review_required"
            reason = "duplicate_legacy_key_in_year"
        row = {
            "event_id": event.id,
            "year": event.year,
            "slug": event.slug,
            "legacy_series_key": event.series_key,
            "proposed_series_key": proposed,
            "country_region": event.country_region,
            "canonical_name_original": event.original_name,
            "chinese_name": event.chinese_name,
            "status": status,
            "reason": reason,
            "event_snapshot_sha256": hashlib.sha256(
                canonical_json(
                    {
                        "id": event.id,
                        "year": event.year,
                        "slug": event.slug,
                        "series_key": event.series_key,
                        "country_region": event.country_region,
                        "original_name": event.original_name,
                        "chinese_name": event.chinese_name,
                    }
                ).encode("utf-8")
            ).hexdigest(),
        }
        rows.append(row)
        if status != "approved":
            conflicts.append(
                {
                    "conflict_type": reason,
                    "event_id": event.id,
                    "year": event.year,
                    "slug": event.slug,
                    "legacy_series_key": event.series_key,
                    "proposed_series_key": proposed,
                    "related_event_id": "",
                }
            )

    for index, left in enumerate(rows):
        left_name = " ".join(str(left["canonical_name_original"]).casefold().split())
        for right in rows[index + 1 :]:
            if left["country_region"] != right["country_region"]:
                continue
            if left["proposed_series_key"] == right["proposed_series_key"]:
                continue
            if left["reason"] == "operator_override" and right["reason"] == "operator_override":
                continue
            right_name = " ".join(str(right["canonical_name_original"]).casefold().split())
            if left_name and right_name and SequenceMatcher(None, left_name, right_name).ratio() >= 0.94:
                conflicts.append(
                    {
                        "conflict_type": "similar_name_different_key",
                        "event_id": left["event_id"],
                        "year": year,
                        "slug": left["slug"],
                        "legacy_series_key": left["legacy_series_key"],
                        "proposed_series_key": left["proposed_series_key"],
                        "related_event_id": right["event_id"],
                    }
                )

    candidates_path = output / "mapping_candidates.jsonl"
    review_path = output / "mapping_review.csv"
    conflicts_path = output / "mapping_conflicts.csv"
    summary_path = output / "summary.json"
    _write_jsonl(candidates_path, rows)
    _write_csv(
        review_path,
        rows,
        [
            "event_id",
            "year",
            "slug",
            "legacy_series_key",
            "proposed_series_key",
            "country_region",
            "canonical_name_original",
            "chinese_name",
            "status",
            "reason",
        ],
    )
    _write_csv(
        conflicts_path,
        conflicts,
        [
            "conflict_type",
            "event_id",
            "year",
            "slug",
            "legacy_series_key",
            "proposed_series_key",
            "related_event_id",
        ],
    )
    summary = {
        "year": year,
        "event_count": len(rows),
        "approved_count": sum(row["status"] == "approved" for row in rows),
        "review_required_count": sum(row["status"] != "approved" for row in rows),
        "conflict_count": len(conflicts),
        "region_counts": dict(sorted(Counter(row["country_region"] for row in rows).items())),
    }
    _write_json(summary_path, summary)
    artifact_paths = {
        "mapping_candidates": candidates_path,
        "mapping_review": review_path,
        "mapping_conflicts": conflicts_path,
        "summary": summary_path,
    }
    manifest = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "artifact_type": "existing_race_event_series_mapping",
        "generated_at": timezone.now().isoformat(),
        "artifacts": {
            name: file_identity(path, relative_to=output).as_dict() for name, path in artifact_paths.items()
        },
        "inputs": {
            "year": year,
            "overrides": file_identity(overrides_path).as_dict() if overrides_path else None,
        },
    }
    manifest_path = output / "manifest.json"
    _write_json(manifest_path, manifest)
    approval_path = output / "approval.json"
    _write_json(
        approval_path,
        {
            "schema_version": INVENTORY_SCHEMA_VERSION,
            "status": "pending",
            "manifest_identity": file_identity(manifest_path, relative_to=output).as_dict(),
            "approved_by": "",
            "approved_at": "",
        },
    )
    return {"output_dir": str(output), "manifest": str(manifest_path), "approval": str(approval_path), **summary}


def validate_mapping_artifact(artifact_dir: str | Path, approval_path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(artifact_dir)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise InventoryValidationError("mapping manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != INVENTORY_SCHEMA_VERSION
        or manifest.get("artifact_type") != "existing_race_event_series_mapping"
    ):
        raise InventoryValidationError("unexpected mapping artifact type")
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    missing = sorted(MAPPING_REQUIRED_ARTIFACTS - set(artifacts))
    if missing:
        raise InventoryValidationError(f"mapping manifest is incomplete: {', '.join(missing)}")
    for name, expected in artifacts.items():
        if not isinstance(expected, dict):
            raise InventoryValidationError(f"mapping artifact identity is invalid: {name}")
        path = _artifact_path(root, expected.get("path"), label=f"mapping artifact {name}")
        actual = file_identity(path, relative_to=root).as_dict()
        if actual != expected:
            raise InventoryValidationError(f"mapping artifact changed after manifest: {name}")
    approval = json.loads(Path(approval_path).read_text(encoding="utf-8"))
    if approval.get("manifest_identity") != file_identity(manifest_path, relative_to=root).as_dict():
        raise InventoryValidationError("mapping approval does not match manifest")
    if approval.get("status") != "approved" or not str(approval.get("approved_by") or "").strip() or not str(
        approval.get("approved_at") or ""
    ).strip():
        raise InventoryValidationError("mapping artifact is not approved with operator evidence")
    return manifest, approval


def commit_existing_event_mapping(*, artifact_dir: str | Path, approval_path: str | Path) -> dict[str, int]:
    from stable.models import RaceEvent

    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        raise InventoryValidationError("historical race backfill is disabled")
    root = Path(artifact_dir)
    manifest, approval = validate_mapping_artifact(root, approval_path)
    rows = list(
        iter_jsonl(
            _artifact_path(
                root,
                manifest["artifacts"]["mapping_candidates"]["path"],
                label="mapping candidates",
            )
        )
    )
    if any(row.get("status") != "approved" for row in rows):
        raise InventoryValidationError("mapping has unresolved review-required rows")
    conflicts_path = _artifact_path(
        root,
        manifest["artifacts"]["mapping_conflicts"]["path"],
        label="mapping conflicts",
    )
    with conflicts_path.open("r", encoding="utf-8-sig", newline="") as handle:
        if any(True for _ in csv.DictReader(handle)):
            raise InventoryValidationError("mapping has unresolved conflicts")
    manifest_sha = file_identity(root / "manifest.json", relative_to=root).sha256
    series_created = 0
    events_bound = 0
    approver = get_user_model().objects.filter(username=str(approval["approved_by"])).first()
    if approver is None:
        raise InventoryValidationError("mapping approver account does not exist")
    with transaction.atomic():
        for row in rows:
            event = RaceEvent.objects.select_for_update().get(pk=row["event_id"])
            current_snapshot = hashlib.sha256(
                canonical_json(
                    {
                        "id": event.id,
                        "year": event.year,
                        "slug": event.slug,
                        "series_key": event.series_key,
                        "country_region": event.country_region,
                        "original_name": event.original_name,
                        "chinese_name": event.chinese_name,
                    }
                ).encode("utf-8")
            ).hexdigest()
            idempotent_core_match = (
                event.year == int(row["year"])
                and event.slug == row["slug"]
                and event.country_region == row["country_region"]
                and event.original_name == row["canonical_name_original"]
                and event.chinese_name == row["chinese_name"]
                and event.series_key in {row["legacy_series_key"], row["proposed_series_key"]}
                and event.race_series_id
                and event.race_series.key == row["proposed_series_key"]
            )
            if current_snapshot != row["event_snapshot_sha256"] and not idempotent_core_match:
                raise InventoryValidationError(f"RaceEvent changed after mapping approval: {event.pk}")
            series, created = RaceSeries.objects.get_or_create(
                key=row["proposed_series_key"],
                defaults={
                    "country_region": event.country_region,
                    "canonical_name_original": event.original_name,
                    "chinese_name": event.chinese_name,
                    "review_status": RaceSeriesReviewStatus.APPROVED,
                    "source_refs": {"mapping_manifest_sha256": manifest_sha, "seed_event_id": event.pk},
                },
            )
            if series.country_region != event.country_region:
                raise InventoryValidationError(f"mapping series region conflict: {series.key}")
            if series.review_status == RaceSeriesReviewStatus.REJECTED:
                raise InventoryValidationError(f"mapping series was rejected: {series.key}")
            if not created and series.review_status != RaceSeriesReviewStatus.APPROVED:
                series.review_status = RaceSeriesReviewStatus.APPROVED
                series.save(update_fields={"review_status"})
            series_created += int(created)
            if event.race_series_id != series.id:
                event.race_series = series
                event.save(update_fields={"race_series"})
                events_bound += 1
        OperationLog.objects.get_or_create(
            action_type="historical_series_mapping_commit",
            target_type="race_series_mapping",
            target_id=manifest_sha,
            defaults={
                "admin": approver,
                "detail": canonical_json(
                    {"manifest_sha256": manifest_sha, "series_created": series_created, "events_bound": events_bound}
                ),
            },
        )
    return {"series_created": series_created, "events_bound": events_bound}


def load_historical_publication_manifest(
    manifest_path: str | Path,
    *,
    expected_sha256: str,
) -> HistoricalPublicationManifest:
    path = Path(manifest_path)
    expected_sha256 = str(expected_sha256 or "").strip().lower()
    if not SHA256_RE.fullmatch(expected_sha256):
        raise InventoryValidationError("expected manifest SHA-256 must be 64 lowercase hexadecimal characters")
    actual_sha256 = file_identity(path).sha256
    if actual_sha256 != expected_sha256:
        raise InventoryValidationError(
            f"manifest SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryValidationError(f"publication manifest is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InventoryValidationError("publication manifest root must be an object")
    if payload.get("schema_version") != HISTORICAL_PUBLICATION_MANIFEST_SCHEMA_VERSION:
        raise InventoryValidationError(
            "publication manifest schema_version must be "
            f"{HISTORICAL_PUBLICATION_MANIFEST_SCHEMA_VERSION}"
        )
    raw_target_ids = payload.get("target_ids")
    if not isinstance(raw_target_ids, list) or not raw_target_ids:
        raise InventoryValidationError("publication manifest target_ids must be a non-empty list")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in raw_target_ids):
        raise InventoryValidationError("publication manifest target_ids must contain positive integers")
    if len(raw_target_ids) != len(set(raw_target_ids)):
        raise InventoryValidationError("publication manifest target_ids 包含重复目标")

    artifact_by_target: dict[int, str] = {}
    raw_targets = payload.get("targets")
    if isinstance(raw_targets, list):
        for row in raw_targets:
            if not isinstance(row, dict):
                raise InventoryValidationError("publication manifest targets rows must be objects")
            target_id = row.get("target_id")
            artifact_sha256 = str(row.get("artifact_sha256") or "").strip().lower()
            if isinstance(target_id, bool) or not isinstance(target_id, int) or target_id <= 0:
                raise InventoryValidationError("publication manifest target_id must be a positive integer")
            if target_id in artifact_by_target:
                raise InventoryValidationError(f"publication manifest targets 包含重复目标: {target_id}")
            if not SHA256_RE.fullmatch(artifact_sha256):
                raise InventoryValidationError(
                    f"publication manifest artifact_sha256 is invalid for target {target_id}"
                )
            artifact_by_target[target_id] = artifact_sha256
    else:
        raw_mapping = payload.get("target_artifact_sha256")
        if not isinstance(raw_mapping, dict):
            raise InventoryValidationError(
                "publication manifest must provide targets or target_artifact_sha256"
            )
        for raw_target_id, raw_artifact_sha256 in raw_mapping.items():
            try:
                target_id = int(raw_target_id)
            except (TypeError, ValueError) as exc:
                raise InventoryValidationError(
                    f"publication manifest target id is invalid: {raw_target_id}"
                ) from exc
            artifact_sha256 = str(raw_artifact_sha256 or "").strip().lower()
            if target_id <= 0 or not SHA256_RE.fullmatch(artifact_sha256):
                raise InventoryValidationError(
                    f"publication manifest artifact_sha256 is invalid for target {target_id}"
                )
            artifact_by_target[target_id] = artifact_sha256
    if set(raw_target_ids) != set(artifact_by_target):
        raise InventoryValidationError(
            "publication manifest target_ids and artifact_sha256 rows must 完整对应"
        )
    return HistoricalPublicationManifest(
        path=path,
        sha256=actual_sha256,
        target_ids=tuple(raw_target_ids),
        artifact_sha256_by_target=artifact_by_target,
    )


def _load_historical_publication_targets(
    manifest: HistoricalPublicationManifest,
    *,
    lock: bool,
) -> list[HistoricalRaceEventTarget]:
    queryset = HistoricalRaceEventTarget.objects.filter(pk__in=manifest.target_ids).select_related("race_series")
    if lock:
        queryset = queryset.select_for_update()
    targets_by_id = {target.pk: target for target in queryset}
    missing_ids = [target_id for target_id in manifest.target_ids if target_id not in targets_by_id]
    if missing_ids:
        raise InventoryValidationError(
            "publication manifest targets do not exist: " + ", ".join(str(value) for value in missing_ids)
        )
    targets = [targets_by_id[target_id] for target_id in manifest.target_ids]
    for target in targets:
        expected_artifact_sha256 = manifest.artifact_sha256_by_target[target.pk]
        if target.artifact_sha256 != expected_artifact_sha256:
            raise InventoryValidationError(
                "target artifact_sha256 changed after manifest: "
                f"{target.pk} expected {expected_artifact_sha256}, got {target.artifact_sha256}"
            )

    event_ids = [target.event_id for target in targets if target.event_id]
    event_queryset = RaceEvent.objects.filter(pk__in=event_ids)
    if lock:
        event_queryset = event_queryset.select_for_update()
    events_by_id = {event.pk: event for event in event_queryset}
    for target in targets:
        if target.event_id:
            target._state.fields_cache["event"] = events_by_id.get(target.event_id)
    return targets


def _historical_publication_facts(
    event_ids: Iterable[int],
    *,
    lock: bool,
) -> HistoricalPublicationFacts:
    event_ids = tuple(sorted(set(event_ids)))
    result_queryset = RaceEventResult.objects.filter(event_id__in=event_ids)
    runner_queryset = RaceEventRunner.objects.filter(event_id__in=event_ids)
    if lock:
        result_queryset = result_queryset.select_for_update()
        runner_queryset = runner_queryset.select_for_update()
    confirmed_result_event_ids = {
        event_id
        for event_id, is_confirmed in result_queryset.values_list("event_id", "is_confirmed")
        if is_confirmed
    }
    runner_event_ids: set[int] = set()
    runner_provenance_missing_event_ids: set[int] = set()
    for event_id, source_refs in runner_queryset.values_list("event_id", "source_refs"):
        runner_event_ids.add(event_id)
        source_refs = source_refs or {}
        if not (
            source_refs.get("derived_from_results")
            or source_refs.get("racecard_url")
            or source_refs.get("source_cache_identity")
        ):
            runner_provenance_missing_event_ids.add(event_id)
    return HistoricalPublicationFacts(
        confirmed_result_event_ids=frozenset(confirmed_result_event_ids),
        runner_event_ids=frozenset(runner_event_ids),
        runner_provenance_missing_event_ids=frozenset(runner_provenance_missing_event_ids),
    )


def historical_publication_blockers(
    target: HistoricalRaceEventTarget,
    *,
    facts: HistoricalPublicationFacts | None = None,
) -> list[str]:
    blockers: list[str] = []
    event = target.event
    if target.race_series.review_status != RaceSeriesReviewStatus.APPROVED:
        blockers.append("series_identity_not_approved")
    if target.resolution_status != HistoricalRaceResolutionStatus.IMPORTED:
        blockers.append("target_not_imported")
    if event is None:
        return [*blockers, "race_event_missing"]
    if event.race_series_id != target.race_series_id or event.year != target.year:
        blockers.append("annual_identity_mismatch")
    if not event.original_name or not event.country_region or not event.source_refs:
        blockers.append("basic_identity_or_source_missing")
    if target.expectation_status == HistoricalRaceExpectationStatus.CANCELLED or event.status == RaceEventStatus.CANCELLED:
        evidence = target.source_refs or {}
        if not evidence.get("scheduled_evidence") or not evidence.get("cancellation_evidence"):
            blockers.append("cancellation_evidence_missing")
        return sorted(set(blockers))
    if event.status != RaceEventStatus.FINISHED:
        blockers.append("race_not_finished")
    if facts is None:
        if not event.results.filter(is_confirmed=True).exists():
            blockers.append("confirmed_results_missing")
        runners = list(event.runners.all())
        if not runners:
            blockers.append("runners_missing")
        elif any(
            not (
                (runner.source_refs or {}).get("derived_from_results")
                or (runner.source_refs or {}).get("racecard_url")
                or (runner.source_refs or {}).get("source_cache_identity")
            )
            for runner in runners
        ):
            blockers.append("runner_provenance_missing")
    else:
        if event.pk not in facts.confirmed_result_event_ids:
            blockers.append("confirmed_results_missing")
        if event.pk not in facts.runner_event_ids:
            blockers.append("runners_missing")
        elif event.pk in facts.runner_provenance_missing_event_ids:
            blockers.append("runner_provenance_missing")
    return sorted(set(blockers))


def _historical_publication_report(
    manifest: HistoricalPublicationManifest,
    targets: list[HistoricalRaceEventTarget],
    *,
    facts: HistoricalPublicationFacts,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    eligible_count = 0
    already_published_count = 0
    for target in targets:
        event = target.event
        blockers = historical_publication_blockers(target, facts=facts)
        blocker_counts.update(blockers)
        already_published = bool(
            not blockers
            and event
            and event.visibility_status == RaceEventVisibility.PUBLISHED
            and event.data_quality_status == RaceEventDataQuality.COMPLETE
        )
        if blockers:
            status = "blocked"
        elif already_published:
            status = "already_published"
            eligible_count += 1
            already_published_count += 1
        else:
            status = "eligible"
            eligible_count += 1
        rows.append(
            {
                "target_id": target.pk,
                "event_id": target.event_id,
                "artifact_sha256": manifest.artifact_sha256_by_target[target.pk],
                "status": status,
                "blockers": blockers,
                "visibility_status": event.visibility_status if event else None,
                "data_quality_status": event.data_quality_status if event else None,
            }
        )
    return {
        "mode": "dry_run",
        "manifest_sha256": manifest.sha256,
        "summary": {
            "target_count": len(targets),
            "eligible_count": eligible_count,
            "blocked_count": len(targets) - eligible_count,
            "already_published_count": already_published_count,
            "blocker_counts": dict(sorted(blocker_counts.items())),
        },
        "targets": rows,
    }


def dry_run_historical_publication(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    manifest = load_historical_publication_manifest(
        manifest_path,
        expected_sha256=expected_manifest_sha256,
    )
    targets = _load_historical_publication_targets(manifest, lock=False)
    facts = _historical_publication_facts(
        (target.event_id for target in targets if target.event_id),
        lock=False,
    )
    return _historical_publication_report(manifest, targets, facts=facts)


def _historical_publication_verifier(
    targets: list[HistoricalRaceEventTarget],
) -> dict[str, Any]:
    event_ids = [target.event_id for target in targets if target.event_id]
    states = {
        event_id: (visibility_status, data_quality_status)
        for event_id, visibility_status, data_quality_status in RaceEvent.objects.filter(
            pk__in=event_ids
        ).values_list("pk", "visibility_status", "data_quality_status")
    }
    rows: list[dict[str, Any]] = []
    error_count = 0
    for target in targets:
        state = states.get(target.event_id)
        published = bool(state and state[0] == RaceEventVisibility.PUBLISHED)
        complete = bool(state and state[1] == RaceEventDataQuality.COMPLETE)
        errors = []
        if not published:
            errors.append("not_published")
        if not complete:
            errors.append("not_complete")
        error_count += len(errors)
        rows.append(
            {
                "target_id": target.pk,
                "event_id": target.event_id,
                "published": published,
                "complete": complete,
                "errors": errors,
            }
        )
    return {
        "ok": error_count == 0,
        "checked_count": len(targets),
        "error_count": error_count,
        "targets": rows,
    }


def verify_historical_publication(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    manifest = load_historical_publication_manifest(
        manifest_path,
        expected_sha256=expected_manifest_sha256,
    )
    targets = _load_historical_publication_targets(manifest, lock=False)
    return {
        "mode": "verify",
        "manifest_sha256": manifest.sha256,
        "verifier": _historical_publication_verifier(targets),
    }


def apply_historical_publication(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    actor,
) -> dict[str, Any]:
    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        raise InventoryValidationError("HISTORICAL_RACE_BACKFILL_ENABLED must be true for publication apply")
    if getattr(settings, "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK", False):
        raise InventoryValidationError("HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK must be false for publication apply")
    if actor is None or not getattr(actor, "pk", None):
        raise InventoryValidationError("publication apply requires an actor")
    manifest = load_historical_publication_manifest(
        manifest_path,
        expected_sha256=expected_manifest_sha256,
    )
    published_count = 0
    with transaction.atomic():
        targets = _load_historical_publication_targets(manifest, lock=True)
        facts = _historical_publication_facts(
            (target.event_id for target in targets if target.event_id),
            lock=True,
        )
        report = _historical_publication_report(manifest, targets, facts=facts)
        if report["summary"]["blocked_count"]:
            raise HistoricalPublicationBlockedError(
                "历史赛事发布阻断: "
                + canonical_json(
                    {
                        "blocked_count": report["summary"]["blocked_count"],
                        "blocker_counts": report["summary"]["blocker_counts"],
                    }
                )
            )
        events_to_update: list[RaceEvent] = []
        publication_logs: list[OperationLog] = []
        event_ids = [target.event_id for target in targets if target.event_id]
        existing_log_event_ids = set(
            OperationLog.objects.filter(
                action_type="historical_race_publication",
                target_type="race_event",
                target_id__in=[str(value) for value in event_ids],
            ).values_list("target_id", flat=True)
        )
        for target, row in zip(targets, report["targets"], strict=True):
            if row["status"] == "already_published":
                continue
            event = target.event
            event.data_quality_status = RaceEventDataQuality.COMPLETE
            event.visibility_status = RaceEventVisibility.PUBLISHED
            events_to_update.append(event)
            row["status"] = "published"
            row["visibility_status"] = RaceEventVisibility.PUBLISHED
            row["data_quality_status"] = RaceEventDataQuality.COMPLETE
            published_count += 1
            if str(event.pk) not in existing_log_event_ids:
                publication_logs.append(
                    OperationLog(
                        admin=actor,
                        action_type="historical_race_publication",
                        target_type="race_event",
                        target_id=str(event.pk),
                        detail=canonical_json(
                            {
                                "target_id": target.pk,
                                "artifact_sha256": manifest.artifact_sha256_by_target[target.pk],
                                "manifest_sha256": manifest.sha256,
                                "expectation_status": target.expectation_status,
                            }
                        ),
                    )
                )
        if events_to_update:
            RaceEvent.objects.bulk_update(
                events_to_update,
                ["data_quality_status", "visibility_status"],
                batch_size=1000,
            )
        if publication_logs:
            OperationLog.objects.bulk_create(publication_logs, batch_size=1000)
        verifier = _historical_publication_verifier(targets)
        if not verifier["ok"]:
            raise InventoryValidationError("historical publication verifier failed inside transaction")
        report["mode"] = "apply"
        report["summary"]["published_count"] = published_count
        report["verifier"] = verifier
        if published_count:
            transaction.on_commit(invalidate_public_race_cache)
    return report


def publish_historical_target(
    target: HistoricalRaceEventTarget,
    *,
    actor,
    publication_scope: dict[str, Any],
) -> RaceEvent:
    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        raise InventoryValidationError("historical race backfill is disabled")
    approved_ids = {int(value) for value in publication_scope.get("target_ids") or []}
    artifact_sha256 = str(publication_scope.get("artifact_sha256") or "")
    if target.pk not in approved_ids or not artifact_sha256 or artifact_sha256 != target.artifact_sha256:
        raise InventoryValidationError("target is outside the approved publication scope")
    with transaction.atomic():
        locked_target = (
            HistoricalRaceEventTarget.objects.select_for_update()
            .select_related("race_series")
            .get(pk=target.pk)
        )
        blockers = historical_publication_blockers(locked_target)
        if blockers:
            raise InventoryValidationError(f"historical publication blocked: {', '.join(blockers)}")
        locked_event = locked_target.event
        locked_event.data_quality_status = RaceEventDataQuality.COMPLETE
        locked_event.visibility_status = RaceEventVisibility.PUBLISHED
        locked_event.save(update_fields={"data_quality_status", "visibility_status"})
        OperationLog.objects.create(
            admin=actor,
            action_type="historical_race_publication",
            target_type="race_event",
            target_id=str(locked_event.pk),
            detail=canonical_json(
                {
                    "target_id": target.pk,
                    "artifact_sha256": artifact_sha256,
                    "expectation_status": target.expectation_status,
                }
            ),
        )
    return locked_event

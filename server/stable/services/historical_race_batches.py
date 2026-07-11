from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from django.db import transaction
from django.db.models import Count

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventDataQuality,
    RaceEventStatus,
    RaceEventVisibility,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.historical_race_inventory import InventoryValidationError, canonical_json


STANDARD_REGION_BATCH_LIMIT = 50
MAX_REGION_PROGRESS_LEAD = 100
FIRST_ACCEPTANCE_TARGETS_PER_REGION = 9
FIRST_ACCEPTANCE_SERIES_PER_REGION = 3
FIRST_ACCEPTANCE_TOTAL_MIN = 40
FIRST_ACCEPTANCE_TOTAL_MAX = 50


def historical_event_slug(target: HistoricalRaceEventTarget) -> str:
    prefix = f"{target.country_region}-"
    stable_key = target.race_series.key
    base = stable_key if stable_key.startswith(prefix) else f"{prefix}{stable_key}"
    suffix = f"-{target.year}"
    return f"{base[: 160 - len(suffix)]}{suffix}"


def materialize_historical_event(target: HistoricalRaceEventTarget, *, actor=None) -> RaceEvent | None:
    if target.expectation_status in {
        HistoricalRaceExpectationStatus.NOT_HELD,
        HistoricalRaceExpectationStatus.NOT_DUE,
    }:
        if target.event_id:
            raise InventoryValidationError("not-held/not-due target must not have a RaceEvent")
        return None
    if target.race_series.review_status != RaceSeriesReviewStatus.APPROVED:
        raise InventoryValidationError("target series is not approved")
    if target.resolution_status not in {
        HistoricalRaceResolutionStatus.READY,
        HistoricalRaceResolutionStatus.IMPORTED,
    }:
        raise InventoryValidationError("target is not ready for RaceEvent materialization")
    if not target.original_name or not target.racecourse or not target.source_refs:
        raise InventoryValidationError("target is missing source-backed basic identity")
    slug = historical_event_slug(target)
    conflict = RaceEvent.objects.filter(year=target.year, slug=slug).exclude(race_series=target.race_series).first()
    if conflict:
        raise InventoryValidationError(f"historical slug conflict: {target.year}/{slug}")
    with transaction.atomic():
        locked = HistoricalRaceEventTarget.objects.select_for_update().select_related("race_series", "event").get(pk=target.pk)
        event = locked.event or RaceEvent.objects.filter(race_series=locked.race_series, year=locked.year).first()
        created = event is None
        if event is None:
            event = RaceEvent.objects.create(
                race_series=locked.race_series,
                year=locked.year,
                slug=slug,
                series_key=locked.race_series.key,
                original_name=locked.original_name,
                chinese_name=locked.chinese_name or locked.race_series.chinese_name or locked.original_name,
                country_region=locked.country_region,
                racecourse=locked.racecourse,
                grade_text=locked.grade_text,
                normalized_grade=locked.normalized_grade,
                surface=locked.surface,
                distance_text=locked.distance_text,
                local_date=locked.local_date,
                status=(
                    RaceEventStatus.CANCELLED
                    if locked.expectation_status == HistoricalRaceExpectationStatus.CANCELLED
                    else RaceEventStatus.FINISHED
                ),
                visibility_status=RaceEventVisibility.DRAFT,
                data_quality_status=RaceEventDataQuality.INCOMPLETE,
                source_refs={
                    **(locked.source_refs or {}),
                    "historical_target_id": locked.pk,
                    "inventory_artifact_sha256": locked.artifact_sha256,
                },
            )
        if locked.event_id != event.pk:
            locked.event = event
            locked.save(update_fields={"event"})
        OperationLog.objects.get_or_create(
            action_type="historical_race_event_materialized",
            target_type="race_event",
            target_id=str(event.pk),
            defaults={
                "admin": actor,
                "detail": canonical_json(
                    {"target_id": locked.pk, "created": created, "artifact_sha256": locked.artifact_sha256}
                ),
            },
        )
    return event


def target_identity(target: HistoricalRaceEventTarget) -> dict[str, Any]:
    event = target.event
    payload = {
        "target_id": target.pk,
        "series_key": target.race_series.key,
        "year": target.year,
        "country_region": target.country_region,
        "expectation_status": target.expectation_status,
        "resolution_status": target.resolution_status,
        "event_id": target.event_id,
        "slug": event.slug if event else "",
        "artifact_sha256": target.artifact_sha256,
        "original_name": target.original_name,
        "chinese_name": target.chinese_name,
        "grade_text": target.grade_text,
        "normalized_grade": target.normalized_grade,
        "racecourse": target.racecourse,
        "surface": target.surface,
        "distance_text": target.distance_text,
        "local_date": target.local_date.isoformat() if target.local_date else "",
        "module_statuses": target.module_statuses,
        "field_provenance": target.field_provenance,
        "source_refs": target.source_refs,
        "event_input": (
            {
                "original_name": event.original_name,
                "chinese_name": event.chinese_name,
                "country_region": event.country_region,
                "racecourse": event.racecourse,
                "grade_text": event.grade_text,
                "normalized_grade": event.normalized_grade,
                "surface": event.surface,
                "distance_text": event.distance_text,
                "status": event.status,
                "local_date": event.local_date.isoformat() if event.local_date else "",
                "source_refs": event.source_refs,
            }
            if event
            else {}
        ),
    }
    payload["target_sha256"] = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return payload


def _closest_by_year(targets: list[HistoricalRaceEventTarget], anchor: int) -> HistoricalRaceEventTarget | None:
    return min(targets, key=lambda target: (abs(target.year - anchor), target.year, target.pk)) if targets else None


def select_first_acceptance_targets(
    *,
    series_keys_by_region: dict[str, list[str]],
    current_year: int,
) -> list[HistoricalRaceEventTarget]:
    selected: list[HistoricalRaceEventTarget] = []
    anchors = (1988, 2000, current_year - 1)
    for region in sorted(region for region in RacingRegion.values if region not in {RacingRegion.OTHER}):
        series_keys = list(dict.fromkeys(series_keys_by_region.get(region) or []))
        if len(series_keys) != FIRST_ACCEPTANCE_SERIES_PER_REGION:
            raise InventoryValidationError(f"{region} first acceptance requires exactly 3 series")
        candidates = list(
            HistoricalRaceEventTarget.objects.select_related("race_series", "event")
            .filter(
                country_region=region,
                race_series__key__in=series_keys,
                race_series__review_status=RaceSeriesReviewStatus.APPROVED,
                resolution_status=HistoricalRaceResolutionStatus.READY,
                expectation_status__in=[
                    HistoricalRaceExpectationStatus.HELD,
                    HistoricalRaceExpectationStatus.CANCELLED,
                ],
                event__isnull=False,
            )
            .order_by("year", "race_series__key", "id")
        )
        by_series: dict[str, list[HistoricalRaceEventTarget]] = defaultdict(list)
        for target in candidates:
            by_series[target.race_series.key].append(target)
        region_selected: list[HistoricalRaceEventTarget] = []
        for series_key in series_keys:
            rows = by_series.get(series_key) or []
            if not rows:
                raise InventoryValidationError(f"{region}/{series_key} has no real ready targets")
            for anchor in anchors:
                candidate = _closest_by_year(rows, anchor)
                if candidate and candidate not in region_selected:
                    region_selected.append(candidate)
        for anchor in anchors:
            if not any(abs(target.year - anchor) <= (5 if anchor != current_year - 1 else 3) for target in region_selected):
                pool = [target for target in candidates if target not in region_selected]
                candidate = _closest_by_year(pool, anchor)
                if candidate:
                    region_selected.append(candidate)
        if len(region_selected) < FIRST_ACCEPTANCE_TARGETS_PER_REGION:
            for candidate in candidates:
                if candidate not in region_selected:
                    region_selected.append(candidate)
                if len(region_selected) == FIRST_ACCEPTANCE_TARGETS_PER_REGION:
                    break
        region_selected = sorted(region_selected, key=lambda target: (target.year, target.race_series.key))[
            :FIRST_ACCEPTANCE_TARGETS_PER_REGION
        ]
        if len(region_selected) != FIRST_ACCEPTANCE_TARGETS_PER_REGION:
            raise InventoryValidationError(f"{region} cannot supply 9 first-acceptance targets")
        if len({target.race_series.key for target in region_selected}) != FIRST_ACCEPTANCE_SERIES_PER_REGION:
            raise InventoryValidationError(f"{region} first acceptance does not cover 3 series")
        if not any(1984 <= target.year <= 1994 for target in region_selected):
            raise InventoryValidationError(f"{region} first acceptance misses the 1980s/early era")
        if not any(1995 <= target.year <= 2005 for target in region_selected):
            raise InventoryValidationError(f"{region} first acceptance misses the around-2000 era")
        if not any(target.year >= current_year - 3 for target in region_selected):
            raise InventoryValidationError(f"{region} first acceptance misses the recent era")
        selected.extend(region_selected)
    if not FIRST_ACCEPTANCE_TOTAL_MIN <= len(selected) <= FIRST_ACCEPTANCE_TOTAL_MAX:
        raise InventoryValidationError(f"first acceptance total is outside 40-50: {len(selected)}")
    return selected


def accounted_progress_by_region() -> dict[str, int]:
    progress = dict.fromkeys(
        [region for region in RacingRegion.values if region != RacingRegion.OTHER],
        0,
    )
    rows = HistoricalRaceEventTarget.objects.filter(
        expectation_status__in=[
            HistoricalRaceExpectationStatus.HELD,
            HistoricalRaceExpectationStatus.CANCELLED,
        ]
    ).filter(
        resolution_status__in=[
            HistoricalRaceResolutionStatus.IMPORTED,
            HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE,
        ]
    )
    progress.update(
        {
            row["country_region"]: row["count"]
            for row in rows.values("country_region").annotate(count=Count("id"))
        }
    )
    return progress


def validate_standard_batch(
    targets: Iterable[HistoricalRaceEventTarget],
    *,
    approved_region_limit: int = STANDARD_REGION_BATCH_LIMIT,
    current_progress: dict[str, int] | None = None,
) -> list[HistoricalRaceEventTarget]:
    rows = list(targets)
    counts = Counter(target.country_region for target in rows)
    if approved_region_limit <= 0:
        raise InventoryValidationError("approved region limit must be positive")
    over = {region: count for region, count in counts.items() if count > approved_region_limit}
    if over:
        raise InventoryValidationError(f"historical region batch limit exceeded: {dict(sorted(over.items()))}")
    progress = dict(current_progress or {})
    for region, count in counts.items():
        progress[region] = progress.get(region, 0) + count
    all_regions = [region for region in RacingRegion.values if region != RacingRegion.OTHER]
    values = [progress.get(region, 0) for region in all_regions]
    if values and max(values) - min(values) > MAX_REGION_PROGRESS_LEAD:
        raise InventoryValidationError("historical region progress lead exceeds 100 standard targets")
    for target in rows:
        if target.resolution_status != HistoricalRaceResolutionStatus.READY or target.event_id is None:
            raise InventoryValidationError(f"target is outside ready approved ledger scope: {target.pk}")
    return rows


def write_batch_snapshot(
    targets: Iterable[HistoricalRaceEventTarget],
    *,
    output_path: str | Path,
    inventory_manifest_sha256: str,
) -> dict[str, Any]:
    rows = [target_identity(target) for target in targets]
    payload = {
        "schema_version": "1.0",
        "inventory_manifest_sha256": inventory_manifest_sha256,
        "target_count": len(rows),
        "region_counts": dict(sorted(Counter(row["country_region"] for row in rows).items())),
        "targets": rows,
    }
    payload["snapshot_sha256"] = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload

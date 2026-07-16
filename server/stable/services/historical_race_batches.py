from __future__ import annotations

import hashlib
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
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
from stable.services.historical_race_inventory import (
    InventoryValidationError,
    canonical_json,
    file_identity,
)


STANDARD_REGION_BATCH_LIMIT = 250
MAX_REGION_PROGRESS_LEAD = 100
FIRST_ACCEPTANCE_TARGETS_PER_REGION = 9
FIRST_ACCEPTANCE_SERIES_PER_REGION = 3
FIRST_ACCEPTANCE_TOTAL_MIN = 40
FIRST_ACCEPTANCE_TOTAL_MAX = 50
SELECTION_SNAPSHOT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class ImmutableSelectionSnapshot:
    source_path: Path
    raw_bytes: bytes
    payload: dict[str, Any]
    targets_by_id: dict[int, dict[str, Any]]


def read_immutable_selection_snapshot(
    path: str | Path,
    *,
    inventory_manifest_sha256: str,
) -> ImmutableSelectionSnapshot:
    source = Path(path)
    try:
        raw_bytes = source.read_bytes()
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryValidationError("historical selection snapshot is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SELECTION_SNAPSHOT_SCHEMA_VERSION:
        raise InventoryValidationError("historical selection snapshot schema is invalid")
    if payload.get("inventory_manifest_sha256") != inventory_manifest_sha256:
        raise InventoryValidationError("historical selection snapshot inventory mismatch")
    claimed_snapshot_sha = str(payload.get("snapshot_sha256") or "")
    snapshot_payload = dict(payload)
    snapshot_payload.pop("snapshot_sha256", None)
    actual_snapshot_sha = hashlib.sha256(canonical_json(snapshot_payload).encode("utf-8")).hexdigest()
    if claimed_snapshot_sha != actual_snapshot_sha:
        raise InventoryValidationError("historical selection snapshot SHA is invalid")
    rows = payload.get("targets")
    if not isinstance(rows, list) or not rows:
        raise InventoryValidationError("historical selection snapshot has no targets")
    targets_by_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise InventoryValidationError("historical selection snapshot target identity is invalid")
        try:
            target_id = int(row["target_id"])
            year = int(row["year"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InventoryValidationError("historical selection snapshot target identity is invalid") from exc
        if (
            target_id <= 0
            or year <= 0
            or target_id in targets_by_id
            or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("target_sha256") or ""))
            or not str(row.get("series_key") or "").strip()
            or not str(row.get("country_region") or "").strip()
            or row.get("artifact_sha256") != inventory_manifest_sha256
        ):
            raise InventoryValidationError("historical selection snapshot target identity is invalid")
        targets_by_id[target_id] = row
    if int(payload.get("target_count", -1)) != len(targets_by_id):
        raise InventoryValidationError("historical selection snapshot target count is inconsistent")
    expected_region_counts = dict(
        sorted(Counter(str(row["country_region"]) for row in targets_by_id.values()).items())
    )
    if "region_counts" in payload and payload.get("region_counts") != expected_region_counts:
        raise InventoryValidationError("historical selection snapshot region counts are inconsistent")
    return ImmutableSelectionSnapshot(
        source_path=source,
        raw_bytes=raw_bytes,
        payload=payload,
        targets_by_id=targets_by_id,
    )


def validate_selection_snapshot_target_identities(
    snapshots: Iterable[ImmutableSelectionSnapshot],
    *,
    inventory_manifest_sha256: str,
) -> set[int]:
    expected_by_id: dict[int, dict[str, Any]] = {}
    for snapshot in snapshots:
        if snapshot.payload.get("inventory_manifest_sha256") != inventory_manifest_sha256:
            raise InventoryValidationError("historical selection snapshot inventory mismatch")
        for target_id, row in snapshot.targets_by_id.items():
            previous = expected_by_id.get(target_id)
            stable_identity = (row["series_key"], int(row["year"]), row["country_region"])
            if previous is not None and stable_identity != (
                previous["series_key"],
                int(previous["year"]),
                previous["country_region"],
            ):
                raise InventoryValidationError("historical selection snapshot target identity is invalid")
            expected_by_id[target_id] = row
    if not expected_by_id:
        return set()
    current = {
        target.pk: target
        for target in HistoricalRaceEventTarget.objects.select_related("race_series").filter(
            pk__in=expected_by_id,
            artifact_sha256=inventory_manifest_sha256,
        )
    }
    if set(current) != set(expected_by_id):
        raise InventoryValidationError("historical selection snapshot target identity is invalid")
    for target_id, row in expected_by_id.items():
        target = current[target_id]
        if (
            target.race_series.key != row["series_key"]
            or target.year != int(row["year"])
            or target.country_region != row["country_region"]
        ):
            raise InventoryValidationError("historical selection snapshot target identity is invalid")
    return set(expected_by_id)


def historical_event_slug(target: HistoricalRaceEventTarget) -> str:
    prefix = f"{target.country_region}-"
    stable_key = target.race_series.key
    base = stable_key if stable_key.startswith(prefix) else f"{prefix}{stable_key}"
    suffix = f"-{target.year}"
    return f"{base[: 160 - len(suffix)]}{suffix}"


def _locked_historical_target(target_id: int):
    # event is nullable; joining it here makes PostgreSQL reject FOR UPDATE.
    return (
        HistoricalRaceEventTarget.objects.select_for_update()
        .select_related("race_series")
        .filter(pk=target_id)
    )


def materialize_historical_event(target: HistoricalRaceEventTarget, *, actor=None) -> RaceEvent | None:
    if target.expectation_status == HistoricalRaceExpectationStatus.NOT_HELD:
        if target.event_id:
            raise InventoryValidationError("not-held target must not have a RaceEvent")
        return None
    if target.expectation_status == HistoricalRaceExpectationStatus.NOT_DUE:
        if not target.event_id:
            return None
        event = RaceEvent.objects.select_related("race_series").get(pk=target.event_id)
        if (
            event.race_series_id != target.race_series_id
            or event.year != target.year
            or event.country_region != target.country_region
            or event.status not in {RaceEventStatus.SCHEDULED, RaceEventStatus.POSTPONED}
        ):
            raise InventoryValidationError("not-due target existing RaceEvent identity/status mismatch")
        return event
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
        locked = _locked_historical_target(target.pk).get()
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


def write_event_input_csvs(
    targets: Iterable[HistoricalRaceEventTarget], *, output_dir: str | Path
) -> dict[str, Any]:
    rows_by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    targets = list(targets)
    for target in targets:
        if target.resolution_status != HistoricalRaceResolutionStatus.READY or not target.event_id:
            raise InventoryValidationError("event input target must be ready and materialized")
        event = target.event
        identity = target_identity(target)
        rows_by_region[target.country_region].append(
            {
                "target_id": target.pk,
                "target_sha256": identity["target_sha256"],
                "inventory_artifact_sha256": target.artifact_sha256,
                "year": event.year,
                "slug": event.slug,
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
                "source_refs": canonical_json(event.source_refs or {}),
            }
        )
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "target_id",
        "target_sha256",
        "inventory_artifact_sha256",
        "year",
        "slug",
        "original_name",
        "chinese_name",
        "country_region",
        "racecourse",
        "grade_text",
        "normalized_grade",
        "surface",
        "distance_text",
        "status",
        "local_date",
        "source_refs",
    ]
    files: dict[str, str] = {}
    for region, rows in sorted(rows_by_region.items()):
        path = root / f"events_{region}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sorted(rows, key=lambda row: (int(row["year"]), row["slug"])))
        files[region] = str(path)
    return {"target_count": len(targets), "region_count": len(files), "files": files}


def _closest_by_year(targets: list[HistoricalRaceEventTarget], anchor: int) -> HistoricalRaceEventTarget | None:
    return min(targets, key=lambda target: (abs(target.year - anchor), target.year, target.pk)) if targets else None


def select_first_acceptance_targets(
    *,
    series_keys_by_region: dict[str, list[str]],
    anchors: tuple[int, int, int] | None = None,
    current_year: int | None = None,
    require_ready: bool = True,
    required_target_ids: Iterable[int] | None = None,
) -> list[HistoricalRaceEventTarget]:
    selected: list[HistoricalRaceEventTarget] = []
    if anchors is None:
        if current_year is None:
            raise InventoryValidationError("first acceptance requires explicit anchors")
        anchors = (1988, 2000, current_year - 1)
    if len(anchors) != 3 or len(set(anchors)) != 3:
        raise InventoryValidationError("first acceptance requires 3 unique anchors")
    fixed_ids = {int(value) for value in required_target_ids or []}
    if required_target_ids is not None and len(fixed_ids) != FIRST_ACCEPTANCE_TARGETS_PER_REGION * 5:
        raise InventoryValidationError("post-discovery acceptance must use the same target ids")
    for region in sorted(region for region in RacingRegion.values if region not in {RacingRegion.OTHER}):
        series_keys = list(dict.fromkeys(series_keys_by_region.get(region) or []))
        if len(series_keys) != FIRST_ACCEPTANCE_SERIES_PER_REGION:
            raise InventoryValidationError(f"{region} first acceptance requires exactly 3 series")
        queryset = HistoricalRaceEventTarget.objects.select_related("race_series", "event").filter(
                country_region=region,
                race_series__key__in=series_keys,
                race_series__review_status=RaceSeriesReviewStatus.APPROVED,
                expectation_status__in=[
                    HistoricalRaceExpectationStatus.HELD,
                    HistoricalRaceExpectationStatus.CANCELLED,
                ],
            )
        if require_ready:
            queryset = queryset.filter(
                resolution_status=HistoricalRaceResolutionStatus.READY,
                event__isnull=False,
            )
        else:
            queryset = queryset.filter(
                resolution_status=HistoricalRaceResolutionStatus.PENDING,
                event__isnull=True,
            )
        if required_target_ids is not None:
            queryset = queryset.filter(pk__in=fixed_ids)
        candidates = list(queryset.order_by("year", "race_series__key", "id"))
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
        for index, anchor in enumerate(anchors):
            tolerance = 3 if index == len(anchors) - 1 else 5
            if not any(abs(target.year - anchor) <= tolerance for target in region_selected):
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
        for index, anchor in enumerate(anchors):
            tolerance = 3 if index == len(anchors) - 1 else 5
            if not any(abs(target.year - anchor) <= tolerance for target in region_selected):
                raise InventoryValidationError(f"{region} first acceptance misses anchor {anchor}")
        selected.extend(region_selected)
    if not FIRST_ACCEPTANCE_TOTAL_MIN <= len(selected) <= FIRST_ACCEPTANCE_TOTAL_MAX:
        raise InventoryValidationError(f"first acceptance total is outside 40-50: {len(selected)}")
    if required_target_ids is not None and {target.pk for target in selected} != fixed_ids:
        raise InventoryValidationError("post-discovery acceptance must use the same target ids")
    return selected


def accounted_progress_by_region(
    *, year_start: int | None = None, year_end: int | None = None
) -> dict[str, int]:
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
    if year_start is not None:
        rows = rows.filter(year__gte=year_start)
    if year_end is not None:
        rows = rows.filter(year__lte=year_end)
    progress.update(
        {
            row["country_region"]: row["count"]
            for row in rows.values("country_region").annotate(count=Count("id"))
        }
    )
    return progress


def _validate_region_limit_and_progress(
    counts: Counter,
    *,
    approved_region_limit: int,
    current_progress: dict[str, int],
    progress_regions: Iterable[str] | None = None,
) -> None:
    if approved_region_limit <= 0 or approved_region_limit > STANDARD_REGION_BATCH_LIMIT:
        raise InventoryValidationError(
            f"approved region limit must be between 1 and {STANDARD_REGION_BATCH_LIMIT}"
        )
    over = {region: count for region, count in counts.items() if count > approved_region_limit}
    if over:
        raise InventoryValidationError(f"historical region batch limit exceeded: {dict(sorted(over.items()))}")
    progress = dict(current_progress)
    for region, count in counts.items():
        progress[region] = progress.get(region, 0) + count
    compared_regions = (
        [region for region in RacingRegion.values if region != RacingRegion.OTHER]
        if progress_regions is None
        else sorted(set(progress_regions))
    )
    values = [progress.get(region, 0) for region in compared_regions]
    if values and max(values) - min(values) > MAX_REGION_PROGRESS_LEAD:
        raise InventoryValidationError("historical region progress lead exceeds 100 standard targets")


def _eligible_pending_band_targets(
    *,
    year_start: int,
    year_end: int,
    inventory_manifest_sha256: str,
    excluded_target_ids: Iterable[int] | None = None,
):
    queryset = HistoricalRaceEventTarget.objects.filter(
        year__gte=year_start,
        year__lte=year_end,
        artifact_sha256=inventory_manifest_sha256,
        race_series__review_status=RaceSeriesReviewStatus.APPROVED,
        expectation_status__in=[
            HistoricalRaceExpectationStatus.HELD,
            HistoricalRaceExpectationStatus.CANCELLED,
        ],
        resolution_status=HistoricalRaceResolutionStatus.PENDING,
        event__isnull=True,
    )
    excluded_ids = {int(target_id) for target_id in excluded_target_ids or []}
    return queryset.exclude(pk__in=excluded_ids) if excluded_ids else queryset


def _counts_by_region(queryset) -> dict[str, int]:
    return {
        row["country_region"]: row["count"]
        for row in queryset.values("country_region").annotate(count=Count("id"))
    }


def _unfinished_regions_after_selection(
    eligible_counts: dict[str, int],
    selected_counts: Counter,
) -> set[str]:
    return {
        region
        for region, eligible_count in eligible_counts.items()
        if eligible_count - selected_counts.get(region, 0) > 0
    }


def select_historical_band_batch_targets(
    *,
    year_start: int,
    year_end: int,
    inventory_manifest_sha256: str,
    region_limit: int = STANDARD_REGION_BATCH_LIMIT,
    excluded_target_ids: Iterable[int] | None = None,
) -> list[HistoricalRaceEventTarget]:
    if year_start > year_end:
        raise InventoryValidationError("historical year band start must not exceed end")
    if not re.fullmatch(r"[0-9a-f]{64}", str(inventory_manifest_sha256 or "")):
        raise InventoryValidationError("historical inventory manifest SHA is invalid")
    if region_limit <= 0 or region_limit > STANDARD_REGION_BATCH_LIMIT:
        raise InventoryValidationError(
            f"historical region limit must be between 1 and {STANDARD_REGION_BATCH_LIMIT}"
        )
    excluded_ids = {int(target_id) for target_id in excluded_target_ids or []}
    eligible = _eligible_pending_band_targets(
        year_start=year_start,
        year_end=year_end,
        inventory_manifest_sha256=inventory_manifest_sha256,
        excluded_target_ids=excluded_ids,
    )
    eligible_counts = _counts_by_region(eligible)
    selected: list[HistoricalRaceEventTarget] = []
    for region in sorted(region for region in RacingRegion.values if region != RacingRegion.OTHER):
        queryset = (
            eligible.select_related("race_series", "event")
            .filter(country_region=region)
            .order_by("-year", "race_series__key", "id")
        )
        selected.extend(list(queryset[:region_limit]))
    selected_counts = Counter(target.country_region for target in selected)
    _validate_region_limit_and_progress(
        selected_counts,
        approved_region_limit=region_limit,
        current_progress=accounted_progress_by_region(year_start=year_start, year_end=year_end),
        progress_regions=_unfinished_regions_after_selection(eligible_counts, selected_counts),
    )
    return selected


def write_band_batch_artifact(
    targets: Iterable[HistoricalRaceEventTarget],
    *,
    output_dir: str | Path,
    inventory_manifest_sha256: str,
    year_start: int,
    year_end: int,
    approved_region_limit: int = STANDARD_REGION_BATCH_LIMIT,
    exclusion_snapshots: Iterable[ImmutableSelectionSnapshot] | None = None,
) -> dict[str, Any]:
    rows = list(targets)
    exclusions = list(exclusion_snapshots or [])
    excluded_ids = validate_selection_snapshot_target_identities(
        exclusions,
        inventory_manifest_sha256=inventory_manifest_sha256,
    )
    if not rows:
        raise InventoryValidationError("historical band batch has no pending targets")
    if len({target.pk for target in rows}) != len(rows):
        raise InventoryValidationError("historical band batch contains duplicate targets")
    if {target.pk for target in rows} & excluded_ids:
        raise InventoryValidationError("historical band batch selection intersects exclusion snapshots")
    for target in rows:
        if not year_start <= target.year <= year_end:
            raise InventoryValidationError(f"target is outside historical year band: {target.pk}")
        if target.artifact_sha256 != inventory_manifest_sha256:
            raise InventoryValidationError(f"target inventory manifest mismatch: {target.pk}")
        if target.race_series.review_status != RaceSeriesReviewStatus.APPROVED:
            raise InventoryValidationError(f"target series is not approved: {target.pk}")
        if target.expectation_status not in {
            HistoricalRaceExpectationStatus.HELD,
            HistoricalRaceExpectationStatus.CANCELLED,
        }:
            raise InventoryValidationError(f"target is not due for detail crawl: {target.pk}")
        if target.resolution_status != HistoricalRaceResolutionStatus.PENDING or target.event_id is not None:
            raise InventoryValidationError(f"target is not pending and unmaterialized: {target.pk}")
    eligible = _eligible_pending_band_targets(
        year_start=year_start,
        year_end=year_end,
        inventory_manifest_sha256=inventory_manifest_sha256,
        excluded_target_ids=excluded_ids,
    )
    eligible_counts = _counts_by_region(eligible)
    selected_counts = Counter(target.country_region for target in rows)
    progress_guard_regions = _unfinished_regions_after_selection(eligible_counts, selected_counts)
    _validate_region_limit_and_progress(
        selected_counts,
        approved_region_limit=approved_region_limit,
        current_progress=accounted_progress_by_region(year_start=year_start, year_end=year_end),
        progress_regions=progress_guard_regions,
    )
    root = Path(output_dir)
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise InventoryValidationError(f"historical band artifact output already exists: {root}") from exc
    snapshot_path = root / "selection_snapshot.json"
    snapshot = write_batch_snapshot(
        rows,
        output_path=snapshot_path,
        inventory_manifest_sha256=inventory_manifest_sha256,
    )
    exclusion_artifacts: dict[str, dict[str, Any]] = {}
    if exclusions:
        exclusion_root = root / "exclusions"
        exclusion_root.mkdir()
        for index, exclusion in enumerate(exclusions, start=1):
            copied_path = exclusion_root / f"selection-{index:03d}.json"
            copied_path.write_bytes(exclusion.raw_bytes)
            exclusion_artifacts[f"excluded_selection_snapshot_{index:03d}"] = file_identity(
                copied_path,
                relative_to=root,
            ).as_dict()
    review_path = root / "expected_targets_review.csv"
    review_fields = [
        "target_id",
        "country_region",
        "year",
        "series_key",
        "original_name",
        "chinese_name",
        "racecourse",
        "grade_text",
        "expectation_status",
        "resolution_status",
        "operator_decision",
        "operator_notes",
    ]
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=review_fields)
        writer.writeheader()
        for target in rows:
            writer.writerow(
                {
                    "target_id": target.pk,
                    "country_region": target.country_region,
                    "year": target.year,
                    "series_key": target.race_series.key,
                    "original_name": target.original_name,
                    "chinese_name": target.chinese_name,
                    "racecourse": target.racecourse,
                    "grade_text": target.grade_text,
                    "expectation_status": target.expectation_status,
                    "resolution_status": target.resolution_status,
                    "operator_decision": "",
                    "operator_notes": "",
                }
            )
    pending = HistoricalRaceEventTarget.objects.filter(
        year__gte=year_start,
        year__lte=year_end,
        artifact_sha256=inventory_manifest_sha256,
        race_series__review_status=RaceSeriesReviewStatus.APPROVED,
        expectation_status__in=[
            HistoricalRaceExpectationStatus.HELD,
            HistoricalRaceExpectationStatus.CANCELLED,
        ],
        resolution_status=HistoricalRaceResolutionStatus.PENDING,
        event__isnull=True,
    )
    available_counts = {
        row["country_region"]: row["count"]
        for row in pending.values("country_region").annotate(count=Count("id"))
    }
    excluded_pending_counts = {
        row["country_region"]: row["count"]
        for row in pending.filter(pk__in=excluded_ids).values("country_region").annotate(count=Count("id"))
    }
    summary = {
        "schema_version": "1.0",
        "year_band": {"start": year_start, "end": year_end},
        "approved_region_limit": approved_region_limit,
        "inventory_manifest_sha256": inventory_manifest_sha256,
        "target_count": len(rows),
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "selected_by_region": dict(sorted(selected_counts.items())),
        "available_pending_by_region": dict(sorted(available_counts.items())),
        "eligible_pending_by_region": dict(sorted(eligible_counts.items())),
        "excluded_snapshot_count": len(exclusions),
        "excluded_target_count": len(excluded_ids),
        "excluded_pending_by_region": dict(sorted(excluded_pending_counts.items())),
        "remaining_pending_by_region": {
            region: available_counts.get(region, 0) - selected_counts.get(region, 0)
            for region in sorted(region for region in RacingRegion.values if region != RacingRegion.OTHER)
        },
        "progress_guard_regions": sorted(progress_guard_regions),
        "accounted_by_region": accounted_progress_by_region(year_start=year_start, year_end=year_end),
    }
    summary_path = root / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year_band": summary["year_band"],
        "approved_region_limit": approved_region_limit,
        "inventory_manifest_sha256": inventory_manifest_sha256,
        "target_count": len(rows),
        "artifacts": {
            "selection_snapshot": file_identity(snapshot_path, relative_to=root).as_dict(),
            "expected_targets_review": file_identity(review_path, relative_to=root).as_dict(),
            "summary": file_identity(summary_path, relative_to=root).as_dict(),
            **exclusion_artifacts,
        },
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    approval = {
        "status": "pending",
        "approved_by": "",
        "approved_at": "",
        "approved_target_ids": [],
        "manifest_identity": file_identity(manifest_path, relative_to=root).as_dict(),
    }
    approval_path = root / "approval.json"
    approval_path.write_text(
        json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "output_dir": str(root),
        "manifest": str(manifest_path),
        "approval": str(approval_path),
        **summary,
    }


def validate_standard_batch(
    targets: Iterable[HistoricalRaceEventTarget],
    *,
    approved_region_limit: int = STANDARD_REGION_BATCH_LIMIT,
    current_progress: dict[str, int] | None = None,
) -> list[HistoricalRaceEventTarget]:
    rows = list(targets)
    counts = Counter(target.country_region for target in rows)
    _validate_region_limit_and_progress(
        counts,
        approved_region_limit=approved_region_limit,
        current_progress=dict(current_progress or {}),
    )
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
        "schema_version": SELECTION_SNAPSHOT_SCHEMA_VERSION,
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

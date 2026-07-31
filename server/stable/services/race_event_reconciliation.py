from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import shutil
import stat
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import connection, transaction
from django.db.models import Count, Q
from django.utils import timezone

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventDataCandidate,
    RaceEventHistoryWinner,
    RaceEventResult,
    RaceEventRunner,
    RaceEventStatus,
)
from stable.services.race_event_years import event_edition_year


SCHEMA_VERSION = "1.0"
LINKABLE_NOT_DUE_STATUSES = {RaceEventStatus.SCHEDULED, RaceEventStatus.POSTPONED}
LINKABLE_HELD_STATUSES = {
    RaceEventStatus.SCHEDULED,
    RaceEventStatus.RUNNING,
    RaceEventStatus.FINISHED,
    RaceEventStatus.POSTPONED,
}


class RaceEventReconciliationError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedReconciliationArtifacts:
    root: Path
    manifest: dict[str, Any]
    manifest_bytes: bytes
    artifact_bytes: dict[str, bytes]


@dataclass
class PreparedLedgerOutput:
    destination: Path
    temporary: Path
    descriptor: int
    published: bool = False


def _json_default(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_regular_file_bytes(path: Path, *, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RaceEventReconciliationError(f"cannot safely open {label}: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RaceEventReconciliationError(f"{label} must be a regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _parse_json_object_bytes(payload_bytes: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(payload_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RaceEventReconciliationError(f"invalid JSON artifact: {label}") from exc
    if not isinstance(payload, dict):
        raise RaceEventReconciliationError(f"JSON artifact must be an object: {label}")
    return payload


def _set_repeatable_read_snapshot() -> None:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")


def _file_identity(path: Path, *, relative_to: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "size": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _identity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"payload": payload, "sha256": _sha256_bytes(_canonical_bytes(payload))}


def target_identity(target: HistoricalRaceEventTarget) -> dict[str, Any]:
    payload = {
        "id": target.pk,
        "race_series_id": target.race_series_id,
        "series_key": target.race_series.key,
        "series_country_region": target.race_series.country_region,
        "series_review_status": target.race_series.review_status,
        "year": target.year,
        "country_region": target.country_region,
        "expectation_status": target.expectation_status,
        "resolution_status": target.resolution_status,
        "event_id": target.event_id,
        "original_name": target.original_name,
        "chinese_name": target.chinese_name,
        "grade_text": target.grade_text,
        "normalized_grade": target.normalized_grade,
        "racecourse": target.racecourse,
        "surface": target.surface,
        "distance_text": target.distance_text,
        "local_date": target.local_date,
        "module_statuses": target.module_statuses or {},
        "field_provenance": target.field_provenance or {},
        "source_refs": target.source_refs or {},
        "artifact_sha256": target.artifact_sha256,
    }
    return _identity(payload)


def event_identity(event: RaceEvent) -> dict[str, Any]:
    payload = {
        "id": event.pk,
        "race_series_id": event.race_series_id,
        "series_key": event.race_series.key if event.race_series_id else event.series_key,
        "series_country_region": (
            event.race_series.country_region if event.race_series_id else None
        ),
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
        "eligibility_text": event.eligibility_text,
        "race_datetime": event.race_datetime,
        "timezone_name": event.timezone_name,
        "local_date": event.local_date,
        "local_start_time": event.local_start_time,
        "priority": event.priority,
        "status": event.status,
        "visibility_status": event.visibility_status,
        "data_quality_status": event.data_quality_status,
        "is_featured": event.is_featured,
        "result_confirmed_at": event.result_confirmed_at,
        "source_refs": event.source_refs or {},
        "manual_lock_flags": event.manual_lock_flags or {},
    }
    return _identity(payload)


def event_detail_snapshot(event: RaceEvent) -> dict[str, int]:
    return {
        "runner_count": event.runners.count(),
        "result_count": event.results.count(),
        "confirmed_result_count": event.results.filter(is_confirmed=True).count(),
        "history_winner_count": event.history_winners.count(),
        "data_candidate_count": event.data_candidates.count(),
        "article_link_count": event.article_links.count(),
    }


def _normalized_names(*values: str) -> set[str]:
    return {" ".join(str(value or "").casefold().split()) for value in values if str(value or "").strip()}


def _status_is_compatible(target: HistoricalRaceEventTarget, event: RaceEvent) -> bool:
    if target.expectation_status == HistoricalRaceExpectationStatus.NOT_HELD:
        return False
    if target.expectation_status == HistoricalRaceExpectationStatus.NOT_DUE:
        return event.status in LINKABLE_NOT_DUE_STATUSES
    if target.expectation_status == HistoricalRaceExpectationStatus.CANCELLED:
        return event.status == RaceEventStatus.CANCELLED
    return event.status in LINKABLE_HELD_STATUSES


def _classification(
    target: HistoricalRaceEventTarget,
    *,
    events_by_series_year: dict[tuple[int, int], list[RaceEvent]],
    events_by_year_name: dict[tuple[int, str], list[RaceEvent]],
    event_owner_by_id: dict[int, int],
) -> dict[str, Any]:
    target_id = target_identity(target)
    base = {
        "target_id": target.pk,
        "target_identity": target_id,
        "country_region": target.country_region,
        "year": target.year,
        "series_id": target.race_series_id,
        "series_key": target.race_series.key,
        "expectation_status": target.expectation_status,
        "resolution_status": target.resolution_status,
        "before_event_id": target.event_id,
        "event_id": None,
        "candidate_event_identity": None,
        "reason": "",
        "candidate_event_ids": [],
    }
    if target.event_id:
        event = target.event
        base["event_id"] = event.pk
        base["candidate_event_identity"] = event_identity(event)
        if (
            event.race_series_id != target.race_series_id
            or event_edition_year(event) != target.year
            or event.country_region != target.country_region
            or target.race_series.country_region != target.country_region
        ):
            base.update(classification="identity_conflict", reason="linked_identity_mismatch")
        elif not _status_is_compatible(target, event):
            base.update(classification="status_conflict", reason="linked_status_incompatible")
        else:
            base.update(classification="already_linked")
        return base

    if target.expectation_status == HistoricalRaceExpectationStatus.NOT_HELD:
        base.update(classification="status_conflict", reason="not_held_target")
        return base

    candidates = events_by_series_year.get((target.race_series_id, target.year), [])
    if len(candidates) > 1:
        base.update(
            classification="identity_conflict",
            reason="ambiguous_series_year_match",
            candidate_event_ids=sorted(event.pk for event in candidates),
        )
        return base
    if len(candidates) == 1:
        event = candidates[0]
        base["event_id"] = event.pk
        base["candidate_event_ids"] = [event.pk]
        base["candidate_event_identity"] = event_identity(event)
        owner_id = event_owner_by_id.get(event.pk)
        if owner_id and owner_id != target.pk:
            base.update(classification="identity_conflict", reason="event_already_owned")
        elif (
            event.country_region != target.country_region
            or target.race_series.country_region != target.country_region
            or event.race_series.country_region != event.country_region
            or event_edition_year(event) != target.year
        ):
            base.update(classification="identity_conflict", reason="series_year_region_mismatch")
        elif not _status_is_compatible(target, event):
            base.update(classification="status_conflict", reason="status_incompatible")
        else:
            base.update(classification="exact_link")
        return base

    target_names = _normalized_names(
        target.original_name,
        target.chinese_name,
        target.race_series.canonical_name_original,
        target.race_series.chinese_name,
    )
    name_matches: dict[int, RaceEvent] = {}
    for name in target_names:
        for event in events_by_year_name.get((target.year, name), []):
            name_matches[event.pk] = event
    if name_matches:
        candidate_ids = sorted(name_matches)
        base["candidate_event_ids"] = candidate_ids
        base.update(
            classification="identity_conflict",
            reason="ambiguous_name_match" if len(candidate_ids) > 1 else "series_mismatch",
        )
        return base
    base.update(classification="missing_event", reason="no_series_year_event")
    return base


def classify_historical_race_event_targets(
    targets: Iterable[HistoricalRaceEventTarget] | None = None,
) -> list[dict[str, Any]]:
    if targets is None:
        target_rows = list(
            HistoricalRaceEventTarget.objects.select_related("race_series", "event", "event__race_series")
            .all()
            .order_by("id")
        )
    else:
        target_ids = sorted({int(target.pk) for target in targets})
        target_rows = list(
            HistoricalRaceEventTarget.objects.select_related("race_series", "event", "event__race_series")
            .filter(pk__in=target_ids)
            .order_by("id")
        )
    all_events = list(RaceEvent.objects.select_related("race_series").all().order_by("id"))
    by_series_year: dict[tuple[int, int], list[RaceEvent]] = defaultdict(list)
    by_year_name: dict[tuple[int, str], list[RaceEvent]] = defaultdict(list)
    for event in all_events:
        edition_year = event_edition_year(event)
        if event.race_series_id:
            by_series_year[(event.race_series_id, edition_year)].append(event)
        for name in _normalized_names(event.original_name, event.chinese_name):
            by_year_name[(edition_year, name)].append(event)
    owner_by_event = dict(
        HistoricalRaceEventTarget.objects.exclude(event_id=None).values_list("event_id", "id")
    )
    return [
        _classification(
            target,
            events_by_series_year=by_series_year,
            events_by_year_name=by_year_name,
            event_owner_by_id=owner_by_event,
        )
        for target in target_rows
    ]


def _single_target_classification(target: HistoricalRaceEventTarget) -> dict[str, Any]:
    events = list(
        RaceEvent.objects.select_related("race_series")
        .filter(race_series_id=target.race_series_id)
        .filter(
            Q(edition_year=target.year)
            | Q(edition_year__isnull=True, year=target.year)
        )
        .order_by("id")
    )
    by_series_year = {(target.race_series_id, target.year): events}
    by_year_name: dict[tuple[int, str], list[RaceEvent]] = defaultdict(list)
    target_names = _normalized_names(
        target.original_name,
        target.chinese_name,
        target.race_series.canonical_name_original,
        target.race_series.chinese_name,
    )
    if not events:
        for event in (
            RaceEvent.objects.select_related("race_series")
            .filter(
                Q(edition_year=target.year)
                | Q(edition_year__isnull=True, year=target.year)
            )
            .order_by("id")
        ):
            for name in _normalized_names(event.original_name, event.chinese_name) & target_names:
                by_year_name[(event_edition_year(event), name)].append(event)
    owner_by_event = dict(
        HistoricalRaceEventTarget.objects.exclude(event_id=None).values_list("event_id", "id")
    )
    return _classification(
        target,
        events_by_series_year=by_series_year,
        events_by_year_name=by_year_name,
        event_owner_by_id=owner_by_event,
    )


def adopt_existing_race_event_for_target(
    *,
    target_id: int,
    expected_target_sha256: str | None = None,
    expected_event_id: int | None = None,
    expected_event_sha256: str | None = None,
    actor=None,
    manifest_sha256: str = "",
) -> dict[str, Any]:
    with transaction.atomic():
        return _adopt_existing_race_event_for_target(
            target_id=target_id,
            expected_target_sha256=expected_target_sha256,
            expected_event_id=expected_event_id,
            expected_event_sha256=expected_event_sha256,
            actor=actor,
            manifest_sha256=manifest_sha256,
        )


def _adopt_existing_race_event_for_target(
    *,
    target_id: int,
    expected_target_sha256: str | None = None,
    expected_event_id: int | None = None,
    expected_event_sha256: str | None = None,
    actor=None,
    manifest_sha256: str = "",
) -> dict[str, Any]:
        target = (
            HistoricalRaceEventTarget.objects.select_for_update()
            .select_related("race_series", "event", "event__race_series")
            .get(pk=target_id)
        )
        current_target_identity = target_identity(target)
        if expected_target_sha256 and current_target_identity["sha256"] != expected_target_sha256:
            raise RaceEventReconciliationError(f"target identity drift: {target_id}")
        classification = _single_target_classification(target)
        if classification["classification"] == "already_linked":
            if expected_event_id and target.event_id != expected_event_id:
                raise RaceEventReconciliationError(f"already-linked event mismatch: {target_id}")
            return {"status": "already_linked", "target_id": target.pk, "event_id": target.event_id}
        if classification["classification"] != "exact_link":
            raise RaceEventReconciliationError(
                f"target is not an exact link: {target_id} {classification['classification']} {classification['reason']}"
            )
        event_id = int(classification["event_id"])
        if expected_event_id and event_id != expected_event_id:
            raise RaceEventReconciliationError(f"candidate event drift: {target_id}")
        event = RaceEvent.objects.select_for_update().select_related("race_series").get(pk=event_id)
        current_event_identity = event_identity(event)
        if expected_event_sha256 and current_event_identity["sha256"] != expected_event_sha256:
            raise RaceEventReconciliationError(f"event identity drift: {event_id}")
        before = current_target_identity
        target.event = event
        target.save(update_fields={"event"})
        after = target_identity(target)
        detail_snapshot = event_detail_snapshot(event)
        OperationLog.objects.create(
            admin=actor,
            action_type="race_event_target_reconciled",
            target_type="historical_race_event_target",
            target_id=str(target.pk),
            detail=json.dumps(
                {
                    "manifest_sha256": manifest_sha256,
                    "event_id": event.pk,
                    "before_target_sha256": before["sha256"],
                    "after_target_sha256": after["sha256"],
                    "event_sha256": current_event_identity["sha256"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        return {
            "status": "linked",
            "target_id": target.pk,
            "event_id": event.pk,
            "old_event_id": before["payload"]["event_id"],
            "before_target_identity": before,
            "after_target_identity": after,
            "event_identity": current_event_identity,
            "event_detail_snapshot": detail_snapshot,
        }


def reconcile_historical_race_event_targets(*, actor=None) -> dict[str, Any]:
    records = classify_historical_race_event_targets()
    linked: list[int] = []
    conflicts: list[dict[str, Any]] = []
    for record in records:
        if record["classification"] == "exact_link":
            result = adopt_existing_race_event_for_target(
                target_id=record["target_id"],
                expected_target_sha256=record["target_identity"]["sha256"],
                expected_event_id=record["event_id"],
                expected_event_sha256=record["candidate_event_identity"]["sha256"],
                actor=actor,
            )
            if result["status"] == "linked":
                linked.append(record["target_id"])
        elif record["classification"] in {"identity_conflict", "status_conflict"}:
            conflicts.append(record)
    return {"linked_target_ids": linked, "conflicts": conflicts, "classifications": records}


def _result_is_complete(target: HistoricalRaceEventTarget, event: RaceEvent) -> bool:
    results = list(event.results.all())
    return bool(
        event.status == RaceEventStatus.FINISHED
        and target.resolution_status == HistoricalRaceResolutionStatus.IMPORTED
        and (target.module_statuses or {}).get("results") == "complete"
        and event.result_confirmed_at
        and results
        and all(result.is_confirmed for result in results)
    )


def _layer_tier(target: HistoricalRaceEventTarget) -> str:
    if target.expectation_status == HistoricalRaceExpectationStatus.NOT_DUE:
        return "not_due"
    if target.expectation_status == HistoricalRaceExpectationStatus.NOT_HELD:
        return "not_held"
    if target.expectation_status == HistoricalRaceExpectationStatus.CANCELLED:
        return "cancelled"
    if target.event_id is None:
        return "missing_event"
    if _result_is_complete(target, target.event):
        return "complete"
    return "linked_partial"


def _coverage_layer(targets: list[HistoricalRaceEventTarget]) -> dict[str, Any]:
    tiers: dict[str, list[int]] = defaultdict(list)
    by_region: dict[str, Counter] = defaultdict(Counter)
    for target in targets:
        tier = _layer_tier(target)
        tiers[tier].append(target.pk)
        by_region[target.country_region][tier] += 1
        by_region[target.country_region]["denominator"] += 1
    tier_counts = {tier: len(ids) for tier, ids in sorted(tiers.items())}
    return {
        "denominator": len(targets),
        "coverage_counts": tier_counts,
        "coverage_event_ids": {tier: ids for tier, ids in sorted(tiers.items())},
        "complete_count": tier_counts.get("complete", 0),
        "not_due_count": tier_counts.get("not_due", 0),
        "missing_event_count": tier_counts.get("missing_event", 0),
        "by_region": {region: dict(sorted(counts.items())) for region, counts in sorted(by_region.items())},
        "conservation_ok": sum(tier_counts.values()) == len(targets),
    }


def _event_expected_at(event: RaceEvent) -> datetime | None:
    if event.race_datetime:
        value = event.race_datetime
        if timezone.is_naive(value):
            value = timezone.make_aware(value, dt_timezone.utc)
        return value.astimezone(dt_timezone.utc)
    if not event.local_date:
        return None
    try:
        zone = ZoneInfo(event.timezone_name or "UTC")
    except ZoneInfoNotFoundError:
        zone = dt_timezone.utc
    local_value = datetime.combine(event.local_date, event.local_start_time or time(23, 59, 59), tzinfo=zone)
    return local_value.astimezone(dt_timezone.utc)


def build_layered_race_event_coverage_report(
    *,
    as_of: datetime,
    result_grace: timedelta = timedelta(hours=2),
) -> dict[str, Any]:
    if timezone.is_naive(as_of):
        raise RaceEventReconciliationError("as_of must be timezone-aware")
    if result_grace < timedelta(0):
        raise RaceEventReconciliationError("result_grace must not be negative")
    targets = list(
        HistoricalRaceEventTarget.objects.select_related("race_series", "event")
        .prefetch_related("event__results")
        .all()
        .order_by("id")
    )
    historical = [target for target in targets if target.year <= 2024]
    current = [target for target in targets if target.year >= 2025]
    result_buckets: dict[str, list[int]] = defaultdict(list)
    result_candidate_event_ids = [target.event_id for target in targets if target.event_id]
    by_region: dict[str, Counter] = defaultdict(Counter)
    for target in targets:
        if not target.event_id:
            continue
        event = target.event
        if event.status == RaceEventStatus.CANCELLED:
            result_buckets["cancelled"].append(event.pk)
            continue
        if event.status == RaceEventStatus.POSTPONED:
            result_buckets["postponed"].append(event.pk)
            continue
        expected_at = _event_expected_at(event)
        if expected_at is None or as_of < expected_at:
            result_buckets["future"].append(event.pk)
            continue
        if as_of <= expected_at + result_grace:
            result_buckets["grace_period"].append(event.pk)
            continue
        if _result_is_complete(target, event):
            tier = "complete"
        elif event.results.all():
            tier = "incomplete"
        else:
            tier = "awaiting_result"
        result_buckets[tier].append(event.pk)
        by_region[target.country_region][tier] += 1
        by_region[target.country_region]["denominator"] += 1
    denominator = sum(len(result_buckets[tier]) for tier in ("complete", "incomplete", "awaiting_result"))
    all_result_bucket_names = (
        "complete",
        "incomplete",
        "awaiting_result",
        "grace_period",
        "future",
        "cancelled",
        "postponed",
    )
    all_bucket_event_ids = [
        event_id for bucket in all_result_bucket_names for event_id in result_buckets[bucket]
    ]
    result = {
        "denominator": denominator,
        "complete_count": len(result_buckets["complete"]),
        "complete_event_ids": result_buckets["complete"],
        "incomplete_count": len(result_buckets["incomplete"]),
        "incomplete_event_ids": result_buckets["incomplete"],
        "awaiting_result_count": len(result_buckets["awaiting_result"]),
        "awaiting_result_event_ids": result_buckets["awaiting_result"],
        "missing_count": len(result_buckets["incomplete"]) + len(result_buckets["awaiting_result"]),
        "grace_period_count": len(result_buckets["grace_period"]),
        "grace_period_event_ids": result_buckets["grace_period"],
        "future_count": len(result_buckets["future"]),
        "future_event_ids": result_buckets["future"],
        "cancelled_count": len(result_buckets["cancelled"]),
        "cancelled_event_ids": result_buckets["cancelled"],
        "postponed_count": len(result_buckets["postponed"]),
        "postponed_event_ids": result_buckets["postponed"],
        "excluded_status_counts": {
            status: len(result_buckets[status])
            for status in (RaceEventStatus.CANCELLED, RaceEventStatus.POSTPONED)
            if result_buckets[status]
        },
        "candidate_count": len(result_candidate_event_ids),
        "candidate_event_ids": result_candidate_event_ids,
        "by_region": {region: dict(sorted(counts.items())) for region, counts in sorted(by_region.items())},
        "conservation_ok": (
            len(all_bucket_event_ids) == len(result_candidate_event_ids)
            and len(set(all_bucket_event_ids)) == len(all_bucket_event_ids)
            and set(all_bucket_event_ids) == set(result_candidate_event_ids)
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of.astimezone(dt_timezone.utc).isoformat(),
        "result_grace_seconds": int(result_grace.total_seconds()),
        "historical": _coverage_layer(historical),
        "current": _coverage_layer(current),
        "result": result,
    }


def database_conservation_snapshot() -> dict[str, Any]:
    def counts_by(queryset, field: str) -> dict[str, int]:
        return {
            str(row[field]): row["count"]
            for row in queryset.values(field).annotate(count=Count("id")).order_by(field)
        }

    return {
        "target_count": HistoricalRaceEventTarget.objects.count(),
        "target_expectation_counts": counts_by(HistoricalRaceEventTarget.objects, "expectation_status"),
        "target_resolution_counts": counts_by(HistoricalRaceEventTarget.objects, "resolution_status"),
        "event_count": RaceEvent.objects.count(),
        "event_status_counts": counts_by(RaceEvent.objects, "status"),
        "event_visibility_counts": counts_by(RaceEvent.objects, "visibility_status"),
        "event_data_quality_counts": counts_by(RaceEvent.objects, "data_quality_status"),
        "event_featured_count": RaceEvent.objects.filter(is_featured=True).count(),
        "event_result_confirmed_count": RaceEvent.objects.exclude(result_confirmed_at=None).count(),
        "runner_count": RaceEventRunner.objects.count(),
        "result_count": RaceEventResult.objects.count(),
        "confirmed_result_count": RaceEventResult.objects.filter(is_confirmed=True).count(),
        "history_winner_count": RaceEventHistoryWinner.objects.count(),
        "data_candidate_count": RaceEventDataCandidate.objects.count(),
    }


def _write_review_files(root: Path, records: list[dict[str, Any]]) -> None:
    review_rows = [record for record in records if record["classification"] not in {"exact_link", "already_linked"}]
    fields = [
        "target_id",
        "country_region",
        "year",
        "series_key",
        "classification",
        "reason",
        "event_id",
        "candidate_event_ids",
    ]
    with (root / "review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in review_rows:
            writer.writerow({**{field: row.get(field, "") for field in fields}, "candidate_event_ids": json.dumps(row["candidate_event_ids"])})
    body = "\n".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row.get(field, '')))}</td>" for field in fields) + "</tr>"
        for row in review_rows
    )
    page = (
        "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
        "<title>赛事覆盖关联审核</title><body><h1>赛事覆盖关联审核</h1><table border=\"1\">"
        "<thead><tr>"
        + "".join(f"<th>{html.escape(field)}</th>" for field in fields)
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></body></html>\n"
    )
    (root / "review.html").write_text(page, encoding="utf-8")


def export_race_event_coverage_reconciliation(
    *,
    output_dir: str | Path,
    as_of: datetime,
    result_grace: timedelta = timedelta(hours=2),
) -> dict[str, Any]:
    destination = Path(output_dir)
    if destination.exists():
        raise RaceEventReconciliationError(f"artifact output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        with transaction.atomic():
            _set_repeatable_read_snapshot()
            records = classify_historical_race_event_targets()
            report = build_layered_race_event_coverage_report(as_of=as_of, result_grace=result_grace)
            baseline = database_conservation_snapshot()
            target_ids = [record["target_id"] for record in records]
            if (
                len(target_ids) != baseline["target_count"]
                or report["historical"]["denominator"] + report["current"]["denominator"]
                != baseline["target_count"]
                or not report["historical"]["conservation_ok"]
                or not report["current"]["conservation_ok"]
                or not report["result"]["conservation_ok"]
            ):
                raise RaceEventReconciliationError("export database/report conservation mismatch")
            with (temporary / "reconciliation.jsonl").open("wb") as handle:
                for record in records:
                    handle.write(_canonical_bytes(record))
            (temporary / "coverage_report.json").write_bytes(_canonical_bytes(report))
            _write_review_files(temporary, records)
            artifact_names = ["reconciliation.jsonl", "coverage_report.json", "review.csv", "review.html"]
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "generated_at": timezone.now().astimezone(dt_timezone.utc).isoformat(),
                "as_of": as_of.astimezone(dt_timezone.utc).isoformat(),
                "result_grace_seconds": int(result_grace.total_seconds()),
                "target_ids": target_ids,
                "classification_counts": dict(sorted(Counter(record["classification"] for record in records).items())),
                "database_baseline": baseline,
                "artifacts": {
                    name: _file_identity(temporary / name, relative_to=temporary) for name in artifact_names
                },
            }
            manifest_bytes = _canonical_bytes(manifest)
            (temporary / "manifest.json").write_bytes(manifest_bytes)
        manifest_sha256 = _sha256_bytes(manifest_bytes)
        approval_template = {
            "schema_version": SCHEMA_VERSION,
            "status": "pending",
            "approved_by": "",
            "approved_at": "",
            "manifest_sha256": manifest_sha256,
        }
        approval_bytes = _canonical_bytes(approval_template)
        (temporary / "approval.json").write_bytes(approval_bytes)
        os.rename(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "output_dir": str(destination),
        "manifest_sha256": manifest_sha256,
        "approval_sha256": _sha256_bytes(approval_bytes),
        "classification_counts": manifest["classification_counts"],
    }


def _load_and_verify_manifest(root: Path, expected_sha256: str) -> VerifiedReconciliationArtifacts:
    if root.is_symlink():
        raise RaceEventReconciliationError("artifact directory must not be a symlink")
    manifest_path = root / "manifest.json"
    manifest_bytes = _read_regular_file_bytes(manifest_path, label="manifest")
    if _sha256_bytes(manifest_bytes) != expected_sha256:
        raise RaceEventReconciliationError("manifest SHA-256 mismatch")
    manifest = _parse_json_object_bytes(manifest_bytes, label="manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RaceEventReconciliationError("unsupported reconciliation manifest schema")
    artifacts = manifest.get("artifacts")
    required_artifacts = {"reconciliation.jsonl", "coverage_report.json", "review.csv", "review.html"}
    if not isinstance(artifacts, dict) or set(artifacts) != required_artifacts:
        raise RaceEventReconciliationError("manifest artifact set is incomplete or unexpected")
    target_ids = manifest.get("target_ids")
    if (
        not isinstance(target_ids, list)
        or not all(isinstance(target_id, int) and target_id > 0 for target_id in target_ids)
        or target_ids != sorted(set(target_ids))
    ):
        raise RaceEventReconciliationError("manifest target IDs must be a sorted unique list")
    artifact_bytes: dict[str, bytes] = {}
    bound_paths: set[str] = set()
    for name, identity in artifacts.items():
        if not isinstance(identity, dict) or identity.get("path") != name or name in bound_paths:
            raise RaceEventReconciliationError("manifest artifact key/path binding mismatch")
        bound_paths.add(name)
        payload_bytes = _read_regular_file_bytes(root / name, label=f"artifact {name}")
        if len(payload_bytes) != identity.get("size") or _sha256_bytes(payload_bytes) != identity.get("sha256"):
            raise RaceEventReconciliationError(f"manifest artifact identity mismatch: {name}")
        artifact_bytes[name] = payload_bytes
    return VerifiedReconciliationArtifacts(root, manifest, manifest_bytes, artifact_bytes)


def _load_and_verify_approval(
    *,
    approval_path: Path,
    expected_approval_sha256: str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    approval_bytes = _read_regular_file_bytes(approval_path, label="approval")
    if _sha256_bytes(approval_bytes) != expected_approval_sha256:
        raise RaceEventReconciliationError("approval SHA-256 mismatch")
    approval = _parse_json_object_bytes(approval_bytes, label="approval")
    if (
        approval.get("schema_version") != SCHEMA_VERSION
        or approval.get("status") != "approved"
        or not str(approval.get("approved_by") or "").strip()
        or not str(approval.get("approved_at") or "").strip()
        or approval.get("manifest_sha256") != expected_manifest_sha256
    ):
        raise RaceEventReconciliationError("approval is incomplete or binds a different manifest")
    try:
        approved_at = datetime.fromisoformat(str(approval["approved_at"]).replace("Z", "+00:00"))
        if approved_at.tzinfo is None or approved_at.utcoffset() is None:
            raise ValueError("approval timestamp lacks timezone")
    except ValueError as exc:
        raise RaceEventReconciliationError("approval timestamp is invalid") from exc
    return approval


def _read_reconciliation_records(payload_bytes: bytes) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(payload_bytes.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RaceEventReconciliationError(f"invalid reconciliation row: {line_number}") from exc
        if not isinstance(row, dict):
            raise RaceEventReconciliationError(f"invalid reconciliation row: {line_number}")
        records.append(row)
    return records


def _verify_loaded_artifacts(
    loaded: VerifiedReconciliationArtifacts, *, require_applied_links: bool = False
) -> dict[str, Any]:
    manifest = loaded.manifest
    errors: list[str] = []
    current = database_conservation_snapshot()
    if current != manifest.get("database_baseline"):
        errors.append("database target/event/detail/visibility/status conservation mismatch")
    records = _read_reconciliation_records(loaded.artifact_bytes["reconciliation.jsonl"])
    if [row.get("target_id") for row in records] != manifest.get("target_ids"):
        errors.append("manifest target IDs do not match reconciliation rows")
    if require_applied_links:
        for row in records:
            if row.get("classification") != "exact_link":
                continue
            target = HistoricalRaceEventTarget.objects.filter(pk=row["target_id"]).first()
            if target is None or target.event_id != row.get("event_id"):
                errors.append(f"target link mismatch: {row.get('target_id')}")
    return {"ok": not errors, "error_count": len(errors), "errors": errors, "current_snapshot": current}


def verify_race_event_coverage_reconciliation(
    *,
    artifact_dir: str | Path,
    expected_manifest_sha256: str,
    require_applied_links: bool = False,
) -> dict[str, Any]:
    root = Path(artifact_dir)
    loaded = _load_and_verify_manifest(root, expected_manifest_sha256)
    return _verify_loaded_artifacts(loaded, require_applied_links=require_applied_links)


def _prepare_rollback_ledger(path: Path) -> PreparedLedgerOutput:
    if os.path.lexists(path):
        raise RaceEventReconciliationError(f"rollback ledger already exists: {path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
    except OSError as exc:
        raise RaceEventReconciliationError(f"rollback ledger cannot be prepared: {path}") from exc
    return PreparedLedgerOutput(path, Path(temporary_name), descriptor)


def _cleanup_prepared_ledger(prepared: PreparedLedgerOutput, *, remove_published: bool = False) -> None:
    try:
        os.close(prepared.descriptor)
    except OSError:
        pass
    prepared.temporary.unlink(missing_ok=True)
    if remove_published and prepared.published:
        prepared.destination.unlink(missing_ok=True)


def _publish_prepared_ledger(prepared: PreparedLedgerOutput, rows: list[dict[str, Any]]) -> str:
    payload = b"".join(_canonical_bytes(row) for row in rows)
    try:
        os.ftruncate(prepared.descriptor, 0)
        os.lseek(prepared.descriptor, 0, os.SEEK_SET)
        offset = 0
        while offset < len(payload):
            offset += os.write(prepared.descriptor, payload[offset:])
        os.fsync(prepared.descriptor)
        temporary_stat = os.lstat(prepared.temporary)
        descriptor_stat = os.fstat(prepared.descriptor)
        if (
            not stat.S_ISREG(temporary_stat.st_mode)
            or (temporary_stat.st_dev, temporary_stat.st_ino)
            != (descriptor_stat.st_dev, descriptor_stat.st_ino)
        ):
            raise RaceEventReconciliationError("rollback ledger temporary file changed")
        os.link(prepared.temporary, prepared.destination, follow_symlinks=False)
        prepared.published = True
        prepared.temporary.unlink()
        directory_fd = os.open(prepared.destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except (OSError, RaceEventReconciliationError) as exc:
        if isinstance(exc, RaceEventReconciliationError):
            raise
        raise RaceEventReconciliationError(
            f"rollback ledger cannot be published: {prepared.destination}"
        ) from exc
    return _sha256_bytes(payload)


def apply_race_event_coverage_reconciliation(
    *,
    artifact_dir: str | Path,
    expected_manifest_sha256: str,
    approval_path: str | Path,
    expected_approval_sha256: str,
    rollback_path: str | Path | None = None,
    actor=None,
) -> dict[str, Any]:
    root = Path(artifact_dir)
    loaded = _load_and_verify_manifest(root, expected_manifest_sha256)
    _load_and_verify_approval(
        approval_path=Path(approval_path),
        expected_approval_sha256=expected_approval_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    records = _read_reconciliation_records(loaded.artifact_bytes["reconciliation.jsonl"])
    ledger_path = Path(rollback_path) if rollback_path else root / "rollback.jsonl"
    prepared = _prepare_rollback_ledger(ledger_path)
    rollback_rows: list[dict[str, Any]] = []
    try:
        with transaction.atomic():
            _set_repeatable_read_snapshot()
            preflight = _verify_loaded_artifacts(loaded)
            if not preflight["ok"]:
                raise RaceEventReconciliationError("database baseline drift before apply")
            for row in records:
                if row.get("classification") != "exact_link":
                    continue
                result = _adopt_existing_race_event_for_target(
                    target_id=int(row["target_id"]),
                    expected_target_sha256=str(row["target_identity"]["sha256"]),
                    expected_event_id=int(row["event_id"]),
                    expected_event_sha256=str(row["candidate_event_identity"]["sha256"]),
                    actor=actor,
                    manifest_sha256=expected_manifest_sha256,
                )
                if result["status"] == "linked":
                    rollback_rows.append(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "manifest_sha256": expected_manifest_sha256,
                            "target_id": result["target_id"],
                            "event_id": result["event_id"],
                            "old_event_id": result["old_event_id"],
                            "before_target_identity": result["before_target_identity"],
                            "after_target_identity": result["after_target_identity"],
                            "event_identity": result["event_identity"],
                            "event_detail_snapshot": result["event_detail_snapshot"],
                        }
                    )
            verification = _verify_loaded_artifacts(loaded, require_applied_links=True)
            if not verification["ok"]:
                raise RaceEventReconciliationError(
                    "post-apply verifier failed: " + "; ".join(verification["errors"])
                )
            rollback_sha256 = _publish_prepared_ledger(prepared, rollback_rows)
    except Exception:
        _cleanup_prepared_ledger(prepared, remove_published=True)
        raise
    else:
        _cleanup_prepared_ledger(prepared)
    return {
        "linked_count": len(rollback_rows),
        "linked_target_ids": [row["target_id"] for row in rollback_rows],
        "rollback_path": str(ledger_path),
        "rollback_sha256": rollback_sha256,
        "verification": verification,
    }


def rollback_race_event_coverage_reconciliation(
    *,
    artifact_dir: str | Path,
    expected_manifest_sha256: str,
    approval_path: str | Path,
    expected_approval_sha256: str,
    rollback_path: str | Path,
    expected_rollback_sha256: str,
    actor=None,
) -> dict[str, Any]:
    root = Path(artifact_dir)
    loaded = _load_and_verify_manifest(root, expected_manifest_sha256)
    _load_and_verify_approval(
        approval_path=Path(approval_path),
        expected_approval_sha256=expected_approval_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    ledger_bytes = _read_regular_file_bytes(Path(rollback_path), label="rollback ledger")
    if _sha256_bytes(ledger_bytes) != expected_rollback_sha256:
        raise RaceEventReconciliationError("rollback ledger SHA-256 mismatch")
    rows = _read_reconciliation_records(ledger_bytes)
    if any(row.get("manifest_sha256") != expected_manifest_sha256 for row in rows):
        raise RaceEventReconciliationError("rollback ledger binds a different manifest")
    target_ids = [int(row["target_id"]) for row in rows]
    event_ids = [int(row["event_id"]) for row in rows]
    if len(target_ids) != len(set(target_ids)):
        raise RaceEventReconciliationError("rollback ledger contains duplicate targets")
    rolled_back: list[int] = []
    with transaction.atomic():
        _set_repeatable_read_snapshot()
        targets = {
            target.pk: target
            for target in HistoricalRaceEventTarget.objects.select_for_update()
            .select_related("race_series")
            .filter(pk__in=target_ids)
            .order_by("pk")
        }
        events = {
            event.pk: event
            for event in RaceEvent.objects.select_for_update()
            .select_related("race_series")
            .filter(pk__in=event_ids)
            .order_by("pk")
        }
        if len(targets) != len(set(target_ids)) or len(events) != len(set(event_ids)):
            raise RaceEventReconciliationError("rollback ledger row no longer exists")
        for row in rows:
            target = targets[int(row["target_id"])]
            if target.event_id != row["event_id"] or target_identity(target)["sha256"] != row["after_target_identity"]["sha256"]:
                raise RaceEventReconciliationError(f"target changed after reconciliation: {target.pk}")
            event = events[int(row["event_id"])]
            if event_identity(event)["sha256"] != row["event_identity"]["sha256"]:
                raise RaceEventReconciliationError(f"event changed after reconciliation: {event.pk}")
            if event_detail_snapshot(event) != row["event_detail_snapshot"]:
                raise RaceEventReconciliationError(f"event detail changed after reconciliation: {event.pk}")
        for row in reversed(rows):
            target = targets[int(row["target_id"])]
            event = events[int(row["event_id"])]
            target.event_id = row["old_event_id"]
            target.save(update_fields={"event"})
            if target_identity(target)["sha256"] != row["before_target_identity"]["sha256"]:
                raise RaceEventReconciliationError(f"rollback target identity mismatch: {target.pk}")
            OperationLog.objects.create(
                admin=actor,
                action_type="race_event_target_reconciliation_rolled_back",
                target_type="historical_race_event_target",
                target_id=str(target.pk),
                detail=json.dumps(
                    {"manifest_sha256": expected_manifest_sha256, "event_id": event.pk},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
            rolled_back.append(target.pk)
        verification = _verify_loaded_artifacts(loaded)
        if not verification["ok"]:
            raise RaceEventReconciliationError(
                "post-rollback verifier failed: " + "; ".join(verification["errors"])
            )
    return {"rolled_back_count": len(rolled_back), "rolled_back_target_ids": rolled_back, "verification": verification}

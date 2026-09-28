"""按批准 manifest 应用周期赛历 diff（new/changed/cancelled/uncovered）。

门禁范式照 materialize_dated_race_targets：
- manifest（schema 1.0）声明 regions、years、diff_artifact{path, sha256} 与
  approval{approved_by, approved_at}；diff_artifact.path 相对 manifest 所在目录解析；
- dry-run 全量预演不落库；apply 逐行事务；verify 复核应用结果一致性；
- apply 需 HISTORICAL_RACE_BACKFILL_ENABLED 且执行人必须是 manifest 审批人；
- fail closed：manifest sha 漂移、diff 行锚定失败、diff 行 before/after 与库内
  当前值都不一致（快照过期）、空选择集、new 行缺 series_key。

桶语义（diff 行由 runtime/tools/diff_race_calendar.py 产出）：
- new：创建 HistoricalRaceEventTarget（PENDING/held，artifact_sha256=diff 批次 sha，
  source_refs 带 diff 证据）；series 不存在则创建 RaceSeries（review_status=PENDING，
  不自动批准）；local_date 已知且 series 已 APPROVED 且日期不跨届时，复用
  materialize_*_historical_event 服务物化 draft；
- changed：仅更新未物化或 event 未开赛（status=scheduled 且 local_date 未过）的
  target/event 三个 diff 字段，逐字段 before/after 写 OperationLog；已完赛/跨年
  改期一律拒绝并记入拒绝清单；
- cancelled：不自动删除；仅未物化 target 的 expectation_status → cancelled；
  已物化的记 review_required；
- uncovered / unchanged：只记录不动作。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventStatus,
    RaceSeries,
    RaceSeriesReviewStatus,
)
from stable.services.historical_race_batches import (
    _locked_historical_target,
    materialize_historical_event,
    materialize_scheduled_historical_event,
)
from stable.services.historical_race_inventory import (
    SUPPORTED_REGIONS,
    InventoryValidationError,
    canonical_json,
    iter_jsonl,
)


MANIFEST_SCHEMA_VERSION = "1.0"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ALLOWED_REGIONS = tuple(sorted(SUPPORTED_REGIONS))
DIFF_BUCKETS = ("new", "changed", "unchanged", "cancelled", "uncovered")
ACTIONABLE_BUCKETS = ("new", "changed", "cancelled")
DIFF_FIELDS = ("local_date", "racecourse", "grade_text")

ACTION_CREATE_TARGET = "create_target"
ACTION_MATERIALIZE_SCHEDULED = "materialize_scheduled"
ACTION_MATERIALIZE_FINISHED = "materialize_finished"
ACTION_UPDATE_TARGET_EVENT = "update_target_event"
ACTION_MARK_CANCELLED = "mark_cancelled"
ACTION_REVIEW_REQUIRED = "review_required"
ACTION_REJECTED = "rejected"
ACTION_RECORD_ONLY = "record_only"
ACTION_UNCHANGED = "unchanged"
ACTION_NOOP_ALREADY_PRESENT = "noop_already_present"
ACTION_NOOP_ALREADY_APPLIED = "noop_already_applied"
ACTION_NOOP_ALREADY_CANCELLED = "noop_already_cancelled"


@dataclass(frozen=True)
class RefreshManifest:
    path: Path
    sha256: str
    regions: tuple[str, ...]
    years: tuple[int, ...]
    diff_artifact_path: Path
    diff_artifact_sha256: str
    approved_by: str
    approved_at: str


def _load_manifest(path_value: str, *, expected_sha256: str) -> RefreshManifest:
    expected = str(expected_sha256 or "").strip().lower()
    if not SHA256_RE.fullmatch(expected):
        raise InventoryValidationError(
            "expected manifest SHA-256 must be 64 lowercase hexadecimal characters"
        )
    path = Path(path_value)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InventoryValidationError(f"race calendar refresh manifest cannot be read: {exc}") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise InventoryValidationError(
            f"manifest SHA-256 mismatch: expected {expected}, got {actual}"
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryValidationError(f"race calendar refresh manifest is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InventoryValidationError("race calendar refresh manifest root must be an object")
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise InventoryValidationError(
            f"race calendar refresh manifest schema_version must be {MANIFEST_SCHEMA_VERSION}"
        )
    regions = payload.get("regions")
    allowed = set(ALLOWED_REGIONS)
    if (
        not isinstance(regions, list)
        or not regions
        or len(set(regions)) != len(regions)
        or any(not isinstance(region, str) or region not in allowed for region in regions)
    ):
        raise InventoryValidationError(
            "race calendar refresh manifest regions must be a non-empty subset of: "
            + ", ".join(ALLOWED_REGIONS)
        )
    years = payload.get("years")
    if (
        not isinstance(years, list)
        or not years
        or len(set(years)) != len(years)
        or any(isinstance(year, bool) or not isinstance(year, int) or year <= 0 or year > 9999 for year in years)
    ):
        raise InventoryValidationError(
            "race calendar refresh manifest years must be a non-empty list of unique valid years"
        )
    diff_artifact = payload.get("diff_artifact")
    if not isinstance(diff_artifact, dict):
        raise InventoryValidationError("race calendar refresh manifest diff_artifact is missing")
    diff_sha = str(diff_artifact.get("sha256") or "").strip().lower()
    if not SHA256_RE.fullmatch(diff_sha):
        raise InventoryValidationError("race calendar refresh manifest diff_artifact.sha256 is invalid")
    raw_diff_path = Path(str(diff_artifact.get("path") or "").strip())
    if not str(diff_artifact.get("path") or "").strip():
        raise InventoryValidationError("race calendar refresh manifest diff_artifact.path is missing")
    diff_path = raw_diff_path if raw_diff_path.is_absolute() else (path.parent / raw_diff_path)
    approval = payload.get("approval")
    if not isinstance(approval, dict):
        raise InventoryValidationError("race calendar refresh manifest approval is missing operator evidence")
    approved_by = str(approval.get("approved_by") or "").strip()
    approved_at = str(approval.get("approved_at") or "").strip()
    if not approved_by or not approved_at:
        raise InventoryValidationError("race calendar refresh manifest approval is missing operator evidence")
    for label, value in (("approval.approved_at", approved_at), ("generated_at", payload.get("generated_at"))):
        try:
            datetime.fromisoformat(str(value or ""))
        except ValueError as exc:
            raise InventoryValidationError(f"race calendar refresh manifest {label} is invalid") from exc
    return RefreshManifest(
        path=path,
        sha256=actual,
        regions=tuple(sorted(regions)),
        years=tuple(sorted(years)),
        diff_artifact_path=diff_path,
        diff_artifact_sha256=diff_sha,
        approved_by=approved_by,
        approved_at=approved_at,
    )


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _norm_date_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        from datetime import date

        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise InventoryValidationError(f"diff row has invalid local_date: {text}") from exc


def _load_diff_rows(manifest: RefreshManifest) -> list[dict[str, Any]]:
    try:
        raw = manifest.diff_artifact_path.read_bytes()
    except OSError as exc:
        raise InventoryValidationError(f"diff artifact cannot be read: {exc}") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != manifest.diff_artifact_sha256:
        raise InventoryValidationError(
            f"diff artifact SHA-256 mismatch: expected {manifest.diff_artifact_sha256}, got {actual}"
        )
    rows: list[dict[str, Any]] = []
    for row in iter_jsonl(manifest.diff_artifact_path):
        bucket = str(row.get("bucket") or "")
        if bucket not in DIFF_BUCKETS:
            raise InventoryValidationError(f"diff row bucket is invalid: {bucket!r}")
        region = str(row.get("country_region") or "").strip()
        if not region:
            raise InventoryValidationError("diff row is missing country_region")
        year = row.get("year")
        if isinstance(year, bool) or not isinstance(year, int) or year <= 0:
            raise InventoryValidationError("diff row has invalid year")
        series_key = str(row.get("series_key") or "").strip()
        if bucket == "new" and not series_key:
            raise InventoryValidationError(
                "new diff row is missing series_key; series_match_hint 需人工并键后再入 manifest"
            )
        normalized = {
            "bucket": bucket,
            "country_region": region,
            "year": year,
            "series_key": series_key,
            "evidence": dict(row.get("evidence")) if isinstance(row.get("evidence"), dict) else {},
        }
        if bucket == "new":
            for field in (
                "racecourse",
                "grade_text",
                "original_name",
                "canonical_name_original",
                "surface",
                "distance_text",
            ):
                normalized[field] = _norm_text(row.get(field))
            normalized["local_date"] = _norm_date_text(row.get("local_date"))
        elif bucket == "changed":
            before = row.get("before")
            after = row.get("after")
            if not isinstance(before, dict) or not isinstance(after, dict):
                raise InventoryValidationError("changed diff row requires before/after objects")
            normalized["before"] = {
                "local_date": _norm_date_text(before.get("local_date")),
                "racecourse": _norm_text(before.get("racecourse")),
                "grade_text": _norm_text(before.get("grade_text")),
                "expectation_status": _norm_text(before.get("expectation_status")) or "held",
            }
            normalized["after"] = {
                "local_date": _norm_date_text(after.get("local_date")),
                "racecourse": _norm_text(after.get("racecourse")),
                "grade_text": _norm_text(after.get("grade_text")),
                "original_name": _norm_text(after.get("original_name")),
            }
        elif bucket in {"cancelled", "uncovered"}:
            existing = row.get("existing")
            if not isinstance(existing, dict):
                raise InventoryValidationError(f"{bucket} diff row requires an existing object")
            normalized["existing"] = {
                "local_date": _norm_date_text(existing.get("local_date")),
                "racecourse": _norm_text(existing.get("racecourse")),
                "grade_text": _norm_text(existing.get("grade_text")),
                "expectation_status": _norm_text(existing.get("expectation_status")),
                "resolution_status": _norm_text(existing.get("resolution_status")),
            }
            normalized["reason"] = str(row.get("reason") or "")
        rows.append(normalized)
    if not rows:
        raise InventoryValidationError("diff artifact has no rows")
    return rows


def _scope_rows(manifest: RefreshManifest, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    scoped = []
    out_of_scope = 0
    for row in rows:
        if row["country_region"] in manifest.regions and row["year"] in manifest.years:
            scoped.append(row)
        else:
            out_of_scope += 1
    return scoped, out_of_scope


def _target_field_values(target: HistoricalRaceEventTarget) -> dict[str, str]:
    return {
        "local_date": target.local_date.isoformat() if target.local_date else "",
        "racecourse": _norm_text(target.racecourse),
        "grade_text": _norm_text(target.grade_text),
    }


def _anchor_target(row: dict[str, Any]) -> HistoricalRaceEventTarget:
    series = RaceSeries.objects.filter(key=row["series_key"]).first()
    if series is None:
        raise InventoryValidationError(
            f"diff row series anchor is missing: {row['series_key']}/{row['year']}"
        )
    if series.country_region != row["country_region"]:
        raise InventoryValidationError(
            f"diff row series region mismatch: {row['series_key']} "
            f"({series.country_region} != {row['country_region']})"
        )
    target = (
        HistoricalRaceEventTarget.objects.select_related("race_series", "event")
        .filter(race_series=series, year=row["year"])
        .exclude(resolution_status=HistoricalRaceResolutionStatus.SUPERSEDED)
        .first()
    )
    if target is None:
        raise InventoryValidationError(
            f"diff row target anchor is missing: {row['series_key']}/{row['year']}"
        )
    return target


def _event_updatable(event: RaceEvent | None, *, today) -> bool:
    if event is None:
        return True
    return (
        event.status == RaceEventStatus.SCHEDULED
        and (event.local_date is None or event.local_date >= today)
    )


def _plan_new(row: dict[str, Any], *, today) -> dict[str, Any]:
    if not row["original_name"] and not row["canonical_name_original"]:
        raise InventoryValidationError(f"new diff row is missing a name: {row['series_key']}")
    if not row["racecourse"]:
        raise InventoryValidationError(f"new diff row is missing racecourse: {row['series_key']}")
    series = RaceSeries.objects.filter(key=row["series_key"]).first()
    if series is not None:
        if series.country_region != row["country_region"]:
            raise InventoryValidationError(
                f"new diff row conflicts with existing series region: {row['series_key']}"
            )
        if series.review_status == RaceSeriesReviewStatus.REJECTED:
            raise InventoryValidationError(f"new diff row series was rejected: {row['series_key']}")
    target = None
    if series is not None:
        target = (
            HistoricalRaceEventTarget.objects.select_related("race_series", "event")
            .filter(race_series=series, year=row["year"])
            .exclude(resolution_status=HistoricalRaceResolutionStatus.SUPERSEDED)
            .first()
        )
    planned = {
        "bucket": "new",
        "country_region": row["country_region"],
        "year": row["year"],
        "series_key": row["series_key"],
        "target_id": target.pk if target else None,
        "event_id": target.event_id if target else None,
        "series_exists": series is not None,
        "target_exists": target is not None,
        "reason": "",
    }
    incoming_values = {
        "local_date": row["local_date"],
        "racecourse": row["racecourse"],
        "grade_text": row["grade_text"],
    }
    if target is not None:
        if target.expectation_status != HistoricalRaceExpectationStatus.HELD:
            raise InventoryValidationError(
                f"new diff row target expectation drifted: {target.pk}"
            )
        if _target_field_values(target) != incoming_values:
            raise InventoryValidationError(
                f"new diff row target fields drifted from incoming: {target.pk}"
            )
    materializable = (
        row["local_date"]
        and series is not None
        and series.review_status == RaceSeriesReviewStatus.APPROVED
    )
    if materializable and int(row["local_date"][:4]) != row["year"]:
        # 跨年物化需要已批准跨年证据，refresh 不自动携带
        materializable = False
        planned["reason"] = "cross_year_requires_evidence"
    if target is not None and target.event_id is not None:
        planned["action"] = ACTION_NOOP_ALREADY_PRESENT
    elif materializable and (target is None or target.event_id is None):
        planned["action"] = (
            ACTION_MATERIALIZE_SCHEDULED
            if row["local_date"] > today.isoformat()
            else ACTION_MATERIALIZE_FINISHED
        )
    elif target is not None:
        planned["action"] = ACTION_NOOP_ALREADY_PRESENT
        if not row["local_date"]:
            planned["reason"] = "undated"
        elif not planned["reason"]:
            planned["reason"] = "series_not_approved"
    else:
        planned["action"] = ACTION_CREATE_TARGET
        if not row["local_date"]:
            planned["reason"] = "undated"
        elif not planned["reason"]:
            planned["reason"] = "series_not_approved"
    return planned


def _plan_changed(row: dict[str, Any], *, today) -> dict[str, Any]:
    target = _anchor_target(row)
    before = {field: row["before"][field] for field in DIFF_FIELDS}
    after = {field: row["after"][field] for field in DIFF_FIELDS}
    planned = {
        "bucket": "changed",
        "country_region": row["country_region"],
        "year": row["year"],
        "series_key": row["series_key"],
        "target_id": target.pk,
        "event_id": target.event_id,
        "reason": "",
        "changes": {
            field: {"before": before[field], "after": after[field]}
            for field in DIFF_FIELDS
            if before[field] != after[field]
        },
    }
    current = _target_field_values(target)
    if target.expectation_status != row["before"]["expectation_status"]:
        raise InventoryValidationError(
            f"changed diff row expectation drifted for target: {target.pk}"
        )
    if current == after:
        planned["action"] = ACTION_NOOP_ALREADY_APPLIED
        return planned
    if current != before:
        raise InventoryValidationError(
            f"changed diff row matches neither before nor after for target: {target.pk}"
        )
    event = target.event
    if not _event_updatable(event, today=today):
        planned["action"] = ACTION_REJECTED
        planned["reason"] = "event_already_run"
        return planned
    if after["local_date"] and int(after["local_date"][:4]) != target.year:
        planned["action"] = ACTION_REJECTED
        planned["reason"] = "cross_year_move_requires_manual_review"
        return planned
    planned["action"] = ACTION_UPDATE_TARGET_EVENT
    return planned


def _plan_cancelled(row: dict[str, Any], *, today) -> dict[str, Any]:
    target = _anchor_target(row)
    planned = {
        "bucket": "cancelled",
        "country_region": row["country_region"],
        "year": row["year"],
        "series_key": row["series_key"],
        "target_id": target.pk,
        "event_id": target.event_id,
        "reason": "",
    }
    if target.expectation_status == HistoricalRaceExpectationStatus.CANCELLED:
        planned["action"] = ACTION_NOOP_ALREADY_CANCELLED
        return planned
    if target.expectation_status != HistoricalRaceExpectationStatus.HELD:
        raise InventoryValidationError(
            f"cancelled diff row expectation drifted for target: {target.pk}"
        )
    if target.event_id is not None:
        planned["action"] = ACTION_REVIEW_REQUIRED
        planned["reason"] = "event_materialized"
        return planned
    planned["action"] = ACTION_MARK_CANCELLED
    return planned


def _plan_rows(
    manifest: RefreshManifest,
    scoped: list[dict[str, Any]],
    *,
    out_of_scope: int,
    today,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    planned_rows: list[dict[str, Any]] = []
    for row in scoped:
        if row["bucket"] == "unchanged":
            planned_rows.append(
                {
                    "bucket": "unchanged",
                    "country_region": row["country_region"],
                    "year": row["year"],
                    "series_key": row["series_key"],
                    "target_id": None,
                    "event_id": None,
                    "action": ACTION_UNCHANGED,
                    "reason": "",
                }
            )
        elif row["bucket"] == "uncovered":
            planned_rows.append(
                {
                    "bucket": "uncovered",
                    "country_region": row["country_region"],
                    "year": row["year"],
                    "series_key": row["series_key"],
                    "target_id": None,
                    "event_id": None,
                    "action": ACTION_RECORD_ONLY,
                    "reason": row.get("reason", ""),
                }
            )
        elif row["bucket"] == "new":
            planned_rows.append(_plan_new(row, today=today))
        elif row["bucket"] == "changed":
            planned_rows.append(_plan_changed(row, today=today))
        else:
            planned_rows.append(_plan_cancelled(row, today=today))
    if not any(row["bucket"] in ACTIONABLE_BUCKETS for row in planned_rows):
        raise InventoryValidationError(
            "race calendar refresh selection is empty for manifest scope"
        )
    row_counts = Counter(row["bucket"] for row in planned_rows)
    row_counts["out_of_scope"] = out_of_scope
    return planned_rows, dict(sorted(row_counts.items()))


def _apply_new(
    manifest: RefreshManifest,
    row: dict[str, Any],
    planned: dict[str, Any],
    *,
    actor,
    today,
) -> dict[str, Any]:
    result = dict(planned)
    with transaction.atomic():
        series = RaceSeries.objects.select_for_update().filter(key=row["series_key"]).first()
        series_created = False
        if series is None:
            series = RaceSeries(
                key=row["series_key"],
                country_region=row["country_region"],
                canonical_name_original=row["canonical_name_original"] or row["original_name"],
                review_status=RaceSeriesReviewStatus.PENDING,
                source_refs={"calendar_refresh": _evidence_payload(manifest, row)},
            )
            series.full_clean()
            series.save()
            series_created = True
        elif series.country_region != row["country_region"]:
            raise InventoryValidationError(
                f"new diff row conflicts with existing series region: {row['series_key']}"
            )
        elif series.review_status == RaceSeriesReviewStatus.REJECTED:
            raise InventoryValidationError(f"new diff row series was rejected: {row['series_key']}")
        target = (
            _locked_historical_target_select(series, row["year"])
        )
        target_created = False
        if target is None:
            local_date = _parse_date(row["local_date"])
            target = HistoricalRaceEventTarget(
                race_series=series,
                year=row["year"],
                country_region=row["country_region"],
                expectation_status=HistoricalRaceExpectationStatus.HELD,
                resolution_status=HistoricalRaceResolutionStatus.PENDING,
                original_name=row["original_name"] or row["canonical_name_original"],
                grade_text=row["grade_text"],
                racecourse=row["racecourse"],
                surface=row["surface"],
                distance_text=row["distance_text"],
                local_date=local_date,
                source_refs={"calendar_refresh": _evidence_payload(manifest, row)},
                artifact_sha256=manifest.diff_artifact_sha256,
            )
            target.full_clean()
            target.save()
            target_created = True
        else:
            if target.expectation_status != HistoricalRaceExpectationStatus.HELD:
                raise InventoryValidationError(
                    f"new diff row target expectation drifted: {target.pk}"
                )
            if _target_field_values(target) != {
                "local_date": row["local_date"],
                "racecourse": row["racecourse"],
                "grade_text": row["grade_text"],
            }:
                raise InventoryValidationError(
                    f"new diff row target fields drifted from incoming: {target.pk}"
                )
        event = None
        materializable = (
            target.event_id is None
            and target.local_date is not None
            and series.review_status == RaceSeriesReviewStatus.APPROVED
            and target.local_date.year == target.year
        )
        if materializable:
            if target.resolution_status == HistoricalRaceResolutionStatus.PENDING:
                target.resolution_status = HistoricalRaceResolutionStatus.READY
                target.save(update_fields={"resolution_status"})
            if target.local_date > today:
                event = materialize_scheduled_historical_event(target, actor=actor)
            else:
                event = materialize_historical_event(target, actor=actor)
            target.refresh_from_db()
        result.update(
            {
                "target_id": target.pk,
                "event_id": target.event_id,
                "series_created": series_created,
                "target_created": target_created,
                "event_id_materialized": event.pk if event else None,
            }
        )
        if event is not None:
            result["action"] = (
                ACTION_MATERIALIZE_SCHEDULED
                if target.local_date > today
                else ACTION_MATERIALIZE_FINISHED
            )
        elif target_created:
            result["action"] = ACTION_CREATE_TARGET
        else:
            result["action"] = ACTION_NOOP_ALREADY_PRESENT
    return result


def _locked_historical_target_select(series: RaceSeries, year: int):
    return (
        HistoricalRaceEventTarget.objects.select_for_update()
        .select_related("race_series")
        .filter(race_series=series, year=year)
        .exclude(resolution_status=HistoricalRaceResolutionStatus.SUPERSEDED)
        .first()
    )


def _parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def _evidence_payload(manifest: RefreshManifest, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_sha256": manifest.sha256,
        "diff_artifact_sha256": manifest.diff_artifact_sha256,
        "bucket": row["bucket"],
        "evidence": row.get("evidence", {}),
    }


def _apply_changed(
    manifest: RefreshManifest,
    row: dict[str, Any],
    planned: dict[str, Any],
    *,
    actor,
    today,
) -> dict[str, Any]:
    result = dict(planned)
    with transaction.atomic():
        target = _locked_historical_target(planned["target_id"]).get()
        if target.event_id:
            event = RaceEvent.objects.select_for_update().get(pk=target.event_id)
        else:
            event = None
        after = {field: row["after"][field] for field in DIFF_FIELDS}
        before = {field: row["before"][field] for field in DIFF_FIELDS}
        current = _target_field_values(target)
        if target.expectation_status != row["before"]["expectation_status"]:
            raise InventoryValidationError(
                f"changed diff row expectation drifted for target: {target.pk}"
            )
        if current == after:
            result["action"] = ACTION_NOOP_ALREADY_APPLIED
            return result
        if current != before:
            raise InventoryValidationError(
                f"changed diff row matches neither before nor after for target: {target.pk}"
            )
        if not _event_updatable(event, today=today):
            result["action"] = ACTION_REJECTED
            result["reason"] = "event_already_run"
            return result
        if after["local_date"] and int(after["local_date"][:4]) != target.year:
            result["action"] = ACTION_REJECTED
            result["reason"] = "cross_year_move_requires_manual_review"
            return result
        event_changes: dict[str, Any] = {}
        target.local_date = _parse_date(after["local_date"])
        target.racecourse = after["racecourse"]
        target.grade_text = after["grade_text"]
        source_refs = dict(target.source_refs or {})
        source_refs["calendar_refresh"] = {
            **_evidence_payload(manifest, row),
            "changes": planned["changes"],
        }
        target.source_refs = source_refs
        target.save(update_fields={"local_date", "racecourse", "grade_text", "source_refs"})
        if event is not None:
            event_changes = {
                field: {"before": getattr(event, field), "after": after[field]}
                for field in DIFF_FIELDS
            }
            event.local_date = _parse_date(after["local_date"])
            event.racecourse = after["racecourse"]
            event.grade_text = after["grade_text"]
            event_update_fields = {"local_date", "racecourse", "grade_text"}
            if event.local_date is not None and event.year != event.local_date.year:
                # 跨年拒绝规则保证此时 after 年份 == 届次年
                event.year = event.local_date.year
                event_update_fields.add("year")
            event.save(update_fields=event_update_fields)
            for field in DIFF_FIELDS:
                value = getattr(event, field)
                event_changes[field]["after"] = value.isoformat() if field == "local_date" and value else value
                before_value = event_changes[field]["before"]
                event_changes[field]["before"] = (
                    before_value.isoformat() if field == "local_date" and before_value else before_value
                )
        OperationLog.objects.create(
            admin=actor,
            action_type="race_calendar_refresh_updated",
            target_type="historical_race_event_target",
            target_id=str(target.pk),
            detail=canonical_json(
                {
                    "manifest_sha256": manifest.sha256,
                    "diff_artifact_sha256": manifest.diff_artifact_sha256,
                    "target_id": target.pk,
                    "event_id": event.pk if event else None,
                    "series_key": row["series_key"],
                    "year": row["year"],
                    "changes": planned["changes"],
                    "event_changes": event_changes,
                }
            ),
        )
        result["event_id"] = event.pk if event else None
    return result


def _apply_cancelled(
    manifest: RefreshManifest,
    row: dict[str, Any],
    planned: dict[str, Any],
    *,
    actor,
) -> dict[str, Any]:
    result = dict(planned)
    with transaction.atomic():
        target = _locked_historical_target(planned["target_id"]).get()
        if target.expectation_status == HistoricalRaceExpectationStatus.CANCELLED:
            result["action"] = ACTION_NOOP_ALREADY_CANCELLED
            return result
        if target.expectation_status != HistoricalRaceExpectationStatus.HELD:
            raise InventoryValidationError(
                f"cancelled diff row expectation drifted for target: {target.pk}"
            )
        if target.event_id is not None:
            result["action"] = ACTION_REVIEW_REQUIRED
            result["reason"] = "event_materialized"
            return result
        target.expectation_status = HistoricalRaceExpectationStatus.CANCELLED
        target.save(update_fields={"expectation_status"})
        OperationLog.objects.create(
            admin=actor,
            action_type="race_calendar_refresh_cancelled",
            target_type="historical_race_event_target",
            target_id=str(target.pk),
            detail=canonical_json(
                {
                    "manifest_sha256": manifest.sha256,
                    "diff_artifact_sha256": manifest.diff_artifact_sha256,
                    "target_id": target.pk,
                    "series_key": row["series_key"],
                    "year": row["year"],
                    "reason": row.get("reason", ""),
                }
            ),
        )
    return result


def _summarize(
    planned_rows: list[dict[str, Any]],
    row_counts: dict[str, int],
) -> dict[str, Any]:
    action_counts = Counter(row["action"] for row in planned_rows)
    return {
        "row_counts": row_counts,
        "action_counts": dict(sorted(action_counts.items())),
        "series_created": sum(1 for row in planned_rows if row.get("series_created")),
        "targets_created": sum(1 for row in planned_rows if row.get("target_created")),
        "events_materialized": sum(1 for row in planned_rows if row.get("event_id_materialized")),
        "updated_count": action_counts.get(ACTION_UPDATE_TARGET_EVENT, 0),
        "cancelled_count": action_counts.get(ACTION_MARK_CANCELLED, 0),
        "review_required_count": action_counts.get(ACTION_REVIEW_REQUIRED, 0),
        "rejected_count": action_counts.get(ACTION_REJECTED, 0),
    }


def _verify_row(row: dict[str, Any], *, today) -> dict[str, Any]:
    checked = {
        "bucket": row["bucket"],
        "series_key": row["series_key"],
        "year": row["year"],
        "country_region": row["country_region"],
        "target_id": None,
        "checked": row["bucket"] in ACTIONABLE_BUCKETS,
        "errors": [],
    }
    if not checked["checked"]:
        return checked
    series = RaceSeries.objects.filter(key=row["series_key"]).first()
    target = None
    if series is not None:
        target = (
            HistoricalRaceEventTarget.objects.select_related("race_series", "event")
            .filter(race_series=series, year=row["year"])
            .exclude(resolution_status=HistoricalRaceResolutionStatus.SUPERSEDED)
            .first()
        )
    if target is None:
        checked["errors"].append("target_missing")
        return checked
    checked["target_id"] = target.pk
    if row["bucket"] == "new":
        expected = {
            "local_date": row["local_date"],
            "racecourse": row["racecourse"],
            "grade_text": row["grade_text"],
        }
        if _target_field_values(target) != expected:
            checked["errors"].append("field_mismatch")
        if target.expectation_status != HistoricalRaceExpectationStatus.HELD:
            checked["errors"].append("expectation_mismatch")
        should_materialize = (
            target.local_date is not None
            and target.local_date.year == target.year
            and target.race_series.review_status == RaceSeriesReviewStatus.APPROVED
        )
        if should_materialize:
            event = target.event
            if event is None or target.resolution_status != HistoricalRaceResolutionStatus.READY:
                checked["errors"].append("event_missing")
            else:
                expected_status = (
                    RaceEventStatus.SCHEDULED if target.local_date > today else RaceEventStatus.FINISHED
                )
                if event.status != expected_status or event.local_date != target.local_date:
                    checked["errors"].append("event_mismatch")
        elif target.event_id is not None:
            checked["errors"].append("unexpected_materialization")
    elif row["bucket"] == "changed":
        after = {field: row["after"][field] for field in DIFF_FIELDS}
        if _target_field_values(target) == after:
            return checked
        event = target.event
        legitimately_rejected = not _event_updatable(event, today=today) or (
            after["local_date"] and int(after["local_date"][:4]) != target.year
        )
        if not legitimately_rejected:
            checked["errors"].append("changed_not_applied")
    else:  # cancelled
        if target.expectation_status == HistoricalRaceExpectationStatus.CANCELLED:
            return checked
        if target.event_id is None:
            checked["errors"].append("cancelled_not_applied")
    return checked


def _verify_rows(rows: list[dict[str, Any]], *, today) -> dict[str, Any]:
    checked_rows = [_verify_row(row, today=today) for row in rows]
    error_count = sum(len(row["errors"]) for row in checked_rows)
    return {
        "ok": error_count == 0,
        "checked_count": sum(1 for row in checked_rows if row["checked"]),
        "error_count": error_count,
        "rows": checked_rows,
    }


def _report(
    manifest: RefreshManifest,
    *,
    mode: str,
    rows: list[dict[str, Any]],
    row_counts: dict[str, int],
    verifier: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = {
        "mode": mode,
        "manifest_sha256": manifest.sha256,
        "diff_artifact_sha256": manifest.diff_artifact_sha256,
        "regions": list(manifest.regions),
        "years": list(manifest.years),
        "generated_at": timezone.now().isoformat(),
        "summary": _summarize(rows, row_counts),
        "rows": rows,
    }
    if verifier is not None:
        payload["verifier"] = verifier
    return payload


def _load_and_plan(manifest: RefreshManifest, *, today) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    diff_rows = _load_diff_rows(manifest)
    scoped, out_of_scope = _scope_rows(manifest, diff_rows)
    planned_rows, row_counts = _plan_rows(manifest, scoped, out_of_scope=out_of_scope, today=today)
    return scoped, planned_rows, row_counts


def _dry_run_report(manifest: RefreshManifest) -> dict[str, Any]:
    _, planned_rows, row_counts = _load_and_plan(manifest, today=timezone.localdate())
    return _report(manifest, mode="dry-run", rows=planned_rows, row_counts=row_counts, verifier=None)


def _apply_report(manifest: RefreshManifest, *, actor) -> dict[str, Any]:
    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        raise InventoryValidationError("historical race backfill is disabled")
    today = timezone.localdate()
    scoped_rows, planned_rows, row_counts = _load_and_plan(manifest, today=today)
    results: list[dict[str, Any]] = []
    for planned, diff_row in zip(planned_rows, scoped_rows, strict=True):
        if planned["action"] in {ACTION_UNCHANGED, ACTION_RECORD_ONLY}:
            results.append(planned)
            continue
        if planned["bucket"] == "new":
            results.append(_apply_new(manifest, diff_row, planned, actor=actor, today=today))
        elif planned["bucket"] == "changed":
            results.append(_apply_changed(manifest, diff_row, planned, actor=actor, today=today))
        elif planned["bucket"] == "cancelled":
            results.append(_apply_cancelled(manifest, diff_row, planned, actor=actor))
        else:
            results.append(planned)
    OperationLog.objects.get_or_create(
        action_type="race_calendar_refresh_applied",
        target_type="race_calendar_refresh_manifest",
        target_id=manifest.sha256,
        defaults={
            "admin": actor,
            "detail": canonical_json(
                {
                    "manifest_sha256": manifest.sha256,
                    "diff_artifact_sha256": manifest.diff_artifact_sha256,
                    "regions": list(manifest.regions),
                    "years": list(manifest.years),
                    "summary": _summarize(results, row_counts),
                    "rows": [
                        {
                            "bucket": row["bucket"],
                            "action": row["action"],
                            "series_key": row["series_key"],
                            "year": row["year"],
                            "target_id": row["target_id"],
                            "event_id": row["event_id"],
                        }
                        for row in results
                    ],
                }
            ),
        },
    )
    verifier = _verify_rows(scoped_rows, today=today)
    if not verifier["ok"]:
        raise InventoryValidationError("race calendar refresh verifier failed after apply")
    return _report(manifest, mode="apply", rows=results, row_counts=row_counts, verifier=verifier)


def _verify_report(manifest: RefreshManifest) -> dict[str, Any]:
    today = timezone.localdate()
    scoped_rows, planned_rows, row_counts = _load_and_plan(manifest, today=today)
    verifier = _verify_rows(scoped_rows, today=today)
    return _report(manifest, mode="verify", rows=planned_rows, row_counts=row_counts, verifier=verifier)


class Command(BaseCommand):
    help = "按批准 manifest 应用周期赛历 diff（dry-run/apply/verify）"

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=("dry-run", "apply", "verify"))
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--expected-manifest-sha256", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--actor-username")

    def _actor(self, username: str | None):
        if not username:
            raise CommandError("apply 模式必须提供 --actor-username")
        user_model = get_user_model()
        lookup = {user_model.USERNAME_FIELD: username}
        try:
            return user_model._default_manager.get(**lookup)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"执行人不存在：{username}") from exc

    def _write_output(self, output_path: str | Path, result: dict) -> dict[str, object]:
        path = Path(output_path)
        if path.exists():
            raise CommandError(f"输出文件已存在，拒绝覆盖：{path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
        ).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "path": str(path),
            "size": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }

    def handle(self, *args, **options):
        output = Path(options["output"])
        if output.exists():
            raise CommandError(f"输出文件已存在，拒绝覆盖：{output}")
        try:
            manifest = _load_manifest(
                options["manifest"],
                expected_sha256=options["expected_manifest_sha256"],
            )
            if options["mode"] == "dry-run":
                result = _dry_run_report(manifest)
            elif options["mode"] == "verify":
                result = _verify_report(manifest)
            else:
                actor = self._actor(options["actor_username"])
                if actor.get_username() != manifest.approved_by:
                    raise CommandError(
                        f"apply 执行人必须与 manifest 审批人一致：{manifest.approved_by}"
                    )
                result = _apply_report(manifest, actor=actor)
        except (OSError, ValueError, InventoryValidationError) as exc:
            raise CommandError(str(exc)) from exc
        identity = self._write_output(output, result)
        self.stdout.write(
            json.dumps(
                {
                    "mode": options["mode"],
                    "manifest_sha256": manifest.sha256,
                    "output": identity,
                    "summary": result.get("summary"),
                    "verifier": {
                        "ok": result.get("verifier", {}).get("ok"),
                        "checked_count": result.get("verifier", {}).get("checked_count"),
                        "error_count": result.get("verifier", {}).get("error_count"),
                    }
                    if "verifier" in result
                    else None,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

"""把已带官方日期的库存 target 按批准 manifest 批量物化为 RaceEvent 草稿。

门禁范式照 publish_historical_race_targets：
- manifest（schema 1.0）声明 inventory_artifact_sha256、regions（白名单子集）、
  years、approval{approved_by, approved_at} 与生成时间；
- dry-run 只做选择与预检不落库；apply 逐 target 事务物化；verify 复核绑定与身份；
- --output 原子写 JSON 结果，已存在则拒绝覆盖。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventStatus,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.historical_race_batches import (
    _locked_historical_target,
    historical_event_slug,
    materialize_historical_event,
    materialize_scheduled_historical_event,
    target_identity,
)
from stable.services.historical_race_inventory import (
    InventoryValidationError,
    canonical_json,
)
from stable.services.race_event_years import (
    event_edition_year,
    historical_event_identity,
)


MANIFEST_SCHEMA_VERSION = "1.0"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
# 本命令只服务赛历 timeline 直接带日期的新地区库存；五地区 1984 链路仍走 date-discovery
ALLOWED_REGIONS = (
    RacingRegion.IRELAND,
    RacingRegion.AUSTRALIA,
    RacingRegion.GERMANY,
    RacingRegion.MIDDLE_EAST,
)

ACTION_MATERIALIZE_FINISHED = "materialize_finished"
ACTION_MATERIALIZE_SCHEDULED = "materialize_scheduled"
ACTION_CLAIM_EXISTING = "claim_existing"
ACTION_SKIP_NOT_DUE = "skip_not_due"
ACTION_SKIP_NOT_HELD = "skip_not_held"
ACTION_EXPECT_EVENT = "expect_event"


@dataclass(frozen=True)
class DatedTargetManifest:
    path: Path
    sha256: str
    inventory_artifact_sha256: str
    regions: tuple[str, ...]
    years: tuple[int, ...]
    approved_by: str
    approved_at: str


def _load_manifest(path_value: str, *, expected_sha256: str) -> DatedTargetManifest:
    expected = str(expected_sha256 or "").strip().lower()
    if not SHA256_RE.fullmatch(expected):
        raise InventoryValidationError(
            "expected manifest SHA-256 must be 64 lowercase hexadecimal characters"
        )
    path = Path(path_value)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InventoryValidationError(f"dated target manifest cannot be read: {exc}") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise InventoryValidationError(
            f"manifest SHA-256 mismatch: expected {expected}, got {actual}"
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryValidationError(f"dated target manifest is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InventoryValidationError("dated target manifest root must be an object")
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise InventoryValidationError(
            f"dated target manifest schema_version must be {MANIFEST_SCHEMA_VERSION}"
        )
    inventory_sha = str(payload.get("inventory_artifact_sha256") or "").strip().lower()
    if not SHA256_RE.fullmatch(inventory_sha):
        raise InventoryValidationError("dated target manifest inventory_artifact_sha256 is invalid")
    regions = payload.get("regions")
    allowed = set(ALLOWED_REGIONS)
    if (
        not isinstance(regions, list)
        or not regions
        or len(set(regions)) != len(regions)
        or any(not isinstance(region, str) or region not in allowed for region in regions)
    ):
        raise InventoryValidationError(
            "dated target manifest regions must be a non-empty subset of: "
            + ", ".join(sorted(allowed))
        )
    years = payload.get("years")
    if (
        not isinstance(years, list)
        or not years
        or len(set(years)) != len(years)
        or any(isinstance(year, bool) or not isinstance(year, int) or year <= 0 or year > 9999 for year in years)
    ):
        raise InventoryValidationError(
            "dated target manifest years must be a non-empty list of unique valid years"
        )
    approval = payload.get("approval")
    if not isinstance(approval, dict):
        raise InventoryValidationError("dated target manifest approval is missing operator evidence")
    approved_by = str(approval.get("approved_by") or "").strip()
    approved_at = str(approval.get("approved_at") or "").strip()
    if not approved_by or not approved_at:
        raise InventoryValidationError("dated target manifest approval is missing operator evidence")
    for label, value in (("approval.approved_at", approved_at), ("generated_at", payload.get("generated_at"))):
        try:
            datetime.fromisoformat(str(value or ""))
        except ValueError as exc:
            raise InventoryValidationError(f"dated target manifest {label} is invalid") from exc
    return DatedTargetManifest(
        path=path,
        sha256=actual,
        inventory_artifact_sha256=inventory_sha,
        regions=tuple(sorted(regions)),
        years=tuple(sorted(years)),
        approved_by=approved_by,
        approved_at=approved_at,
    )


def _scope_targets(manifest: DatedTargetManifest) -> list[HistoricalRaceEventTarget]:
    # manifest 声明的批次全集：库存 sha + 地区 + 年份 + 已有日期；expectation 在分类中处理
    return list(
        HistoricalRaceEventTarget.objects.select_related("race_series")
        .filter(
            artifact_sha256=manifest.inventory_artifact_sha256,
            country_region__in=manifest.regions,
            year__in=manifest.years,
            local_date__isnull=False,
        )
        .order_by("country_region", "year", "race_series__key", "pk")
    )


def _classify_scope_target(target: HistoricalRaceEventTarget, *, today) -> str:
    if target.expectation_status == HistoricalRaceExpectationStatus.NOT_HELD:
        if target.event_id is not None:
            raise InventoryValidationError(f"not-held target must not have a RaceEvent: {target.pk}")
        return ACTION_SKIP_NOT_HELD
    if target.expectation_status not in {
        HistoricalRaceExpectationStatus.HELD,
        HistoricalRaceExpectationStatus.CANCELLED,
        HistoricalRaceExpectationStatus.NOT_DUE,
    }:
        raise InventoryValidationError(
            f"target expectation is outside dated materialization scope: {target.pk}"
        )
    if target.race_series.review_status != RaceSeriesReviewStatus.APPROVED:
        raise InventoryValidationError(f"target series is not approved: {target.pk}")
    if target.resolution_status == HistoricalRaceResolutionStatus.PENDING:
        if target.event_id is not None:
            raise InventoryValidationError(
                f"target has an event bound while still pending: {target.pk}"
            )
        if target.expectation_status == HistoricalRaceExpectationStatus.NOT_DUE:
            # not_due 不做 READY 转换也不创建 event，保持既有物化语义
            return ACTION_SKIP_NOT_DUE
        return ACTION_MATERIALIZE_SCHEDULED if target.local_date > today else ACTION_MATERIALIZE_FINISHED
    if target.resolution_status in {
        HistoricalRaceResolutionStatus.READY,
        HistoricalRaceResolutionStatus.IMPORTED,
    }:
        if target.event_id is None:
            raise InventoryValidationError(
                f"target claims materialization without an event: {target.pk}"
            )
        return ACTION_CLAIM_EXISTING
    raise InventoryValidationError(
        f"target resolution is outside dated materialization scope: "
        f"{target.pk} ({target.resolution_status})"
    )


def _plan_scope(manifest: DatedTargetManifest, *, today) -> list[tuple[HistoricalRaceEventTarget, str]]:
    plan = [(target, _classify_scope_target(target, today=today)) for target in _scope_targets(manifest)]
    # 空选择集 fail closed；not_held 行只是信息记录，不算有效选择
    if not any(action != ACTION_SKIP_NOT_HELD for _, action in plan):
        raise InventoryValidationError(
            "dated target materialization selection is empty for manifest scope"
        )
    return plan


def _base_row(target: HistoricalRaceEventTarget, action: str) -> dict[str, Any]:
    return {
        "target_id": target.pk,
        "series_key": target.race_series.key,
        "country_region": target.country_region,
        "year": target.year,
        "local_date": target.local_date.isoformat() if target.local_date else None,
        "expectation_status": target.expectation_status,
        "resolution_status": target.resolution_status,
        "action": action,
        "event_id": target.event_id,
        "created": None,
        "target_sha256_before": target_identity(target)["target_sha256"],
        "target_sha256_after": None,
    }


def _matching_event_query(locked: HistoricalRaceEventTarget):
    # 与物化函数的认领查询保持一致：同系列 + 同届次年
    return RaceEvent.objects.filter(race_series=locked.race_series).filter(
        Q(edition_year=locked.year) | Q(edition_year__isnull=True, year=locked.year)
    )


def _assert_unchanged(
    manifest: DatedTargetManifest,
    target: HistoricalRaceEventTarget,
    locked: HistoricalRaceEventTarget,
) -> None:
    # 锁定行重验，防止选择后与加锁之间发生漂移
    if locked.artifact_sha256 != manifest.inventory_artifact_sha256:
        raise InventoryValidationError(f"target artifact sha changed during materialization: {target.pk}")
    if locked.country_region != target.country_region or locked.year != target.year:
        raise InventoryValidationError(f"target identity changed during materialization: {target.pk}")
    if locked.expectation_status != target.expectation_status:
        raise InventoryValidationError(f"target expectation changed during materialization: {target.pk}")
    if locked.local_date is None or locked.local_date != target.local_date:
        raise InventoryValidationError(f"target local_date changed during materialization: {target.pk}")
    if locked.race_series.review_status != RaceSeriesReviewStatus.APPROVED:
        raise InventoryValidationError(f"target series is not approved: {target.pk}")


def _materialize_target(
    manifest: DatedTargetManifest,
    target: HistoricalRaceEventTarget,
    action: str,
    *,
    actor,
    today,
) -> dict[str, Any]:
    with transaction.atomic():
        locked = _locked_historical_target(target.pk).get()
        _assert_unchanged(manifest, target, locked)
        if (
            locked.resolution_status != HistoricalRaceResolutionStatus.PENDING
            or locked.event_id is not None
        ):
            raise InventoryValidationError(
                f"target is no longer pending/unmaterialized: {target.pk}"
            )
        sha_before = target_identity(locked)["target_sha256"]
        created = not _matching_event_query(locked).exists()
        locked.resolution_status = HistoricalRaceResolutionStatus.READY
        locked.save(update_fields={"resolution_status"})
        if locked.local_date > today:
            event = materialize_scheduled_historical_event(locked, actor=actor)
        else:
            event = materialize_historical_event(locked, actor=actor)
        locked.refresh_from_db()
        row = _base_row(locked, action)
        row.update(
            {
                "event_id": event.pk,
                "created": created,
                "target_sha256_before": sha_before,
                "target_sha256_after": target_identity(locked)["target_sha256"],
            }
        )
        return row


def _claim_existing_target(
    manifest: DatedTargetManifest,
    target: HistoricalRaceEventTarget,
    *,
    actor,
    today,
) -> dict[str, Any]:
    with transaction.atomic():
        locked = _locked_historical_target(target.pk).get()
        _assert_unchanged(manifest, target, locked)
        if (
            locked.resolution_status
            not in {
                HistoricalRaceResolutionStatus.READY,
                HistoricalRaceResolutionStatus.IMPORTED,
            }
            or locked.event_id is None
        ):
            raise InventoryValidationError(
                f"target is no longer materialized for claim: {target.pk}"
            )
        sha_before = target_identity(locked)["target_sha256"]
        if locked.expectation_status == HistoricalRaceExpectationStatus.NOT_DUE or locked.local_date <= today:
            event = materialize_historical_event(locked, actor=actor)
        else:
            event = materialize_scheduled_historical_event(locked, actor=actor)
        locked.refresh_from_db()
        row = _base_row(locked, ACTION_CLAIM_EXISTING)
        row.update(
            {
                "event_id": event.pk,
                "created": False,
                "target_sha256_before": sha_before,
                "target_sha256_after": target_identity(locked)["target_sha256"],
            }
        )
        return row


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    action_counts = Counter(row["action"] for row in rows)
    by_region: dict[str, Counter] = defaultdict(Counter)
    by_year: dict[int, Counter] = defaultdict(Counter)
    for row in rows:
        by_region[row["country_region"]][row["action"]] += 1
        by_year[row["year"]][row["action"]] += 1
    return {
        "scope_count": len(rows),
        "selected_count": sum(1 for row in rows if row["action"] != ACTION_SKIP_NOT_HELD),
        "action_counts": dict(sorted(action_counts.items())),
        "by_region": {
            region: dict(sorted(counts.items())) for region, counts in sorted(by_region.items())
        },
        "by_year": {
            str(year): dict(sorted(counts.items())) for year, counts in sorted(by_year.items())
        },
        "created_count": sum(1 for row in rows if row.get("created") is True),
        "claimed_count": sum(1 for row in rows if row["action"] == ACTION_CLAIM_EXISTING),
    }


def _verify_row(target: HistoricalRaceEventTarget, *, today) -> tuple[dict[str, Any], bool]:
    # 返回 (核对行, 是否计入选择集)；verify 不抛异常，问题记入 errors
    base = {
        "target_id": target.pk,
        "series_key": target.race_series.key,
        "country_region": target.country_region,
        "year": target.year,
        "local_date": target.local_date.isoformat() if target.local_date else None,
        "expectation_status": target.expectation_status,
        "resolution_status": target.resolution_status,
        "event_id": target.event_id,
        "checked": False,
        "errors": [],
        "mismatched_fields": [],
    }
    if target.expectation_status == HistoricalRaceExpectationStatus.NOT_HELD:
        return {**base, "action": ACTION_SKIP_NOT_HELD}, False
    if (
        target.expectation_status == HistoricalRaceExpectationStatus.NOT_DUE
        and target.event_id is None
    ):
        return {**base, "action": ACTION_SKIP_NOT_DUE}, True
    row = {**base, "action": ACTION_EXPECT_EVENT, "checked": True}
    event = RaceEvent.objects.filter(pk=target.event_id).first() if target.event_id else None
    if event is None:
        row["errors"].append("event_missing")
        return row, True
    try:
        identity = historical_event_identity(target, target.local_date)
    except ValidationError:
        row["errors"].append("identity_invalid")
        return row, True
    public_year = int(identity["public_year"])
    checks = (
        ("race_series", event.race_series_id == target.race_series_id),
        ("edition_year", event_edition_year(event) == target.year),
        ("year", event.year == public_year),
        ("slug", event.slug == historical_event_slug(target, public_year=public_year)),
        ("country_region", event.country_region == target.country_region),
    )
    row["mismatched_fields"] = sorted(field for field, ok in checks if not ok)
    if row["mismatched_fields"]:
        row["errors"].append("identity_mismatch")
    if target.expectation_status == HistoricalRaceExpectationStatus.CANCELLED:
        expected_statuses = {RaceEventStatus.CANCELLED}
    elif target.expectation_status == HistoricalRaceExpectationStatus.NOT_DUE:
        expected_statuses = {RaceEventStatus.SCHEDULED, RaceEventStatus.POSTPONED}
    elif target.local_date and target.local_date > today:
        expected_statuses = {RaceEventStatus.SCHEDULED}
    else:
        expected_statuses = {RaceEventStatus.FINISHED}
    if event.status not in expected_statuses:
        row["errors"].append("status_mismatch")
    return row, True


def _verify_scope(manifest: DatedTargetManifest, *, today) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    selected = 0
    for target in _scope_targets(manifest):
        row, counts = _verify_row(target, today=today)
        rows.append(row)
        selected += int(counts)
    if selected == 0:
        raise InventoryValidationError(
            "dated target materialization selection is empty for manifest scope"
        )
    checked_rows = [row for row in rows if row["checked"]]
    error_count = sum(len(row["errors"]) for row in checked_rows)
    return {
        "ok": error_count == 0,
        "checked_count": len(checked_rows),
        "error_count": error_count,
        "targets": rows,
    }


def _report(
    manifest: DatedTargetManifest,
    *,
    mode: str,
    rows: list[dict[str, Any]],
    verifier: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = {
        "mode": mode,
        "manifest_sha256": manifest.sha256,
        "inventory_artifact_sha256": manifest.inventory_artifact_sha256,
        "regions": list(manifest.regions),
        "years": list(manifest.years),
        "generated_at": timezone.now().isoformat(),
        "summary": _summarize(rows),
        "targets": rows,
    }
    if verifier is not None:
        payload["verifier"] = verifier
    return payload


def _dry_run_report(manifest: DatedTargetManifest) -> dict[str, Any]:
    today = timezone.localdate()
    rows = [_base_row(target, action) for target, action in _plan_scope(manifest, today=today)]
    return _report(manifest, mode="dry-run", rows=rows, verifier=None)


def _apply_report(manifest: DatedTargetManifest, *, actor) -> dict[str, Any]:
    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        raise InventoryValidationError("historical race backfill is disabled")
    today = timezone.localdate()
    plan = _plan_scope(manifest, today=today)
    rows: list[dict[str, Any]] = []
    for target, action in plan:
        if action == ACTION_SKIP_NOT_HELD:
            rows.append(_base_row(target, action))
        elif action == ACTION_SKIP_NOT_DUE:
            rows.append(_base_row(target, action))
        elif action == ACTION_CLAIM_EXISTING:
            rows.append(_claim_existing_target(manifest, target, actor=actor, today=today))
        else:
            rows.append(_materialize_target(manifest, target, action, actor=actor, today=today))
    OperationLog.objects.get_or_create(
        action_type="dated_race_targets_materialized",
        target_type="dated_race_target_manifest",
        target_id=manifest.sha256,
        defaults={
            "admin": actor,
            "detail": canonical_json(
                {
                    "manifest_sha256": manifest.sha256,
                    "inventory_artifact_sha256": manifest.inventory_artifact_sha256,
                    "regions": list(manifest.regions),
                    "years": list(manifest.years),
                    "summary": _summarize(rows),
                    "targets": [
                        {"target_id": row["target_id"], "event_id": row["event_id"], "action": row["action"]}
                        for row in rows
                    ],
                }
            ),
        },
    )
    verifier = _verify_scope(manifest, today=today)
    if not verifier["ok"]:
        raise InventoryValidationError("dated target materialization verifier failed after apply")
    return _report(manifest, mode="apply", rows=rows, verifier=verifier)


def _verify_report(manifest: DatedTargetManifest) -> dict[str, Any]:
    verifier = _verify_scope(manifest, today=timezone.localdate())
    return _report(manifest, mode="verify", rows=verifier["targets"], verifier=verifier)


class Command(BaseCommand):
    help = "按批准 manifest 把带官方日期的库存 target 批量物化为 RaceEvent 草稿（dry-run/apply/verify）"

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
                        "apply 执行人必须与 manifest 审批人一致：" f"{manifest.approved_by}"
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

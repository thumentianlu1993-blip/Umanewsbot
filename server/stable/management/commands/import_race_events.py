from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from django.utils.text import slugify

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceResolutionStatus,
    RaceEvent,
    RaceEventAlias,
    RaceEventDataQuality,
    RaceEventPriority,
    RaceEventStatus,
    RaceEventVisibility,
    SourceLanguage,
    TaskExecutionLog,
    TaskStatus,
)
from stable.services.historical_race_batches import (
    historical_event_slug,
    materialize_historical_event,
    target_identity,
)
from stable.services.historical_race_inventory import InventoryValidationError
from stable.services.race_event_reconciliation import (
    RaceEventReconciliationError,
    adopt_existing_race_event_for_target,
)
from stable.services.race_events import apply_race_event_normalization


REQUIRED_FIELDS = {"year", "original_name", "chinese_name", "country_region", "racecourse", "grade_text", "surface"}
DESCRIPTOR_IDENTITY_FIELDS = {
    "target_id",
    "target_sha256",
    "inventory_artifact_sha256",
}
PROTECTED_CURRENT_YEAR_SCOPE_START = 2026
SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class CurrentYearDescriptorContext:
    cutoff_date: date
    protected_scope_year: int
    targets_by_id: dict[int, dict]
    descriptor_sha256: str
    inventory_artifact_sha256: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json_object(path: Path, *, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommandError(f"{label} 无法读取或不是合法 JSON：{path}") from exc
    if not isinstance(payload, dict):
        raise CommandError(f"{label} 必须是 JSON 对象：{path}")
    return payload


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_identity(identity: object, *, base: Path, root: Path, label: str) -> Path:
    if not isinstance(identity, dict):
        raise CommandError(f"{label} identity 缺失")
    relative = identity.get("path")
    expected_size = identity.get("size")
    expected_sha = identity.get("sha256")
    if (
        not isinstance(relative, str)
        or not relative
        or Path(relative).is_absolute()
        or not isinstance(expected_size, int)
        or not isinstance(expected_sha, str)
    ):
        raise CommandError(f"{label} identity 字段非法")
    candidate = base / relative
    cursor = base
    for part in Path(relative).parts:
        if part == "..":
            cursor = cursor.parent
        elif part != ".":
            cursor = cursor / part
            if cursor.is_symlink():
                raise CommandError(f"{label} identity 路径不得经过符号链接")
    resolved = candidate.resolve()
    if not _is_within(resolved, root) or not resolved.is_file():
        raise CommandError(f"{label} identity 路径越界或文件不存在")
    actual_size = resolved.stat().st_size
    actual_sha = _sha256(resolved)
    if actual_size != expected_size or actual_sha != expected_sha:
        raise CommandError(f"{label} identity 的 SHA 或 size 已漂移")
    return resolved


def _same_content_identity(first: object, second: object) -> bool:
    return isinstance(first, dict) and isinstance(second, dict) and all(
        first.get(key) == second.get(key) for key in ("size", "sha256")
    )


def _validate_current_year_descriptor(
    *,
    csv_path: Path,
    descriptor_path: Path,
    approval_path: Path,
    approved_cutoff: date,
) -> CurrentYearDescriptorContext:
    descriptor_path = descriptor_path.expanduser().resolve()
    approval_path = approval_path.expanduser().resolve()
    if not descriptor_path.is_file() or descriptor_path.is_symlink():
        raise CommandError("current-year descriptor 文件不存在或为符号链接")
    if not approval_path.is_file() or approval_path.is_symlink():
        raise CommandError("current-year approval 文件不存在或为符号链接")
    descriptor = _load_json_object(descriptor_path, label="current-year descriptor")
    if descriptor.get("schema_version") != "1.0" or descriptor.get("artifact_kind") != "due_only":
        raise CommandError("current-year descriptor 必须声明 artifact_kind=due_only")
    try:
        descriptor_cutoff = date.fromisoformat(str(descriptor.get("cutoff_date") or ""))
    except ValueError as exc:
        raise CommandError("current-year descriptor cutoff_date 非法") from exc
    if descriptor_cutoff != approved_cutoff:
        raise CommandError("descriptor cutoff does not match approved cutoff")
    raw_scope_year = descriptor.get("protected_scope_year", descriptor_cutoff.year)
    if (
        not isinstance(raw_scope_year, int)
        or isinstance(raw_scope_year, bool)
        or raw_scope_year < PROTECTED_CURRENT_YEAR_SCOPE_START
        or raw_scope_year != descriptor_cutoff.year
    ):
        raise CommandError("current-year descriptor protected scope year 非法")
    protected_scope_year = raw_scope_year

    classified_dir = descriptor_path.parent
    shard_root = classified_dir.parent.resolve()
    classified_manifest_path = _resolve_identity(
        descriptor.get("classified_manifest"),
        base=classified_dir,
        root=shard_root,
        label="classified manifest",
    )
    if classified_manifest_path.parent != classified_dir:
        raise CommandError("classified manifest 必须位于 descriptor 目录")
    declared_inputs = {}
    for key in ("selection", "source_catalog", "request_manifest", "parse_manifest"):
        declared_inputs[key] = _resolve_identity(
            descriptor.get(key), base=classified_dir, root=shard_root, label=key
        )
    apply_artifacts = descriptor.get("apply_artifacts")
    if not isinstance(apply_artifacts, dict) or not apply_artifacts:
        raise CommandError("current-year descriptor 没有 due-only apply artifact")
    resolved_apply_artifacts = {
        name: _resolve_identity(
            artifact,
            base=classified_dir,
            root=classified_dir,
            label=f"apply artifact {name}",
        )
        for name, artifact in apply_artifacts.items()
    }
    resolved_csv = csv_path.expanduser().resolve()
    if resolved_csv not in resolved_apply_artifacts.values():
        raise CommandError("current-year CSV 路径未由 descriptor 声明")

    classified_manifest = _load_json_object(
        classified_manifest_path, label="classified manifest"
    )
    if classified_manifest.get("cutoff_date") != approved_cutoff.isoformat():
        raise CommandError("classified manifest cutoff does not match approved cutoff")
    manifest_scope_year = classified_manifest.get("protected_scope_year")
    if manifest_scope_year is not None and manifest_scope_year != protected_scope_year:
        raise CommandError("classified manifest protected scope year 与 descriptor 不一致")
    manifest_inputs = classified_manifest.get("inputs")
    if not isinstance(manifest_inputs, dict):
        raise CommandError("classified manifest inputs 缺失")
    for key in declared_inputs:
        if not _same_content_identity(manifest_inputs.get(key), descriptor.get(key)):
            raise CommandError(f"classified manifest {key} identity 与 descriptor 不一致")
    manifest_apply = classified_manifest.get("apply_artifacts")
    if manifest_apply != apply_artifacts:
        raise CommandError("classified manifest due CSV identity 与 descriptor 不一致")

    request_manifest = _load_json_object(
        declared_inputs["request_manifest"], label="request manifest"
    )
    parse_manifest = _load_json_object(
        declared_inputs["parse_manifest"], label="parse manifest"
    )
    for key in ("selection", "source_catalog"):
        if not _same_content_identity(request_manifest.get(key), descriptor.get(key)):
            raise CommandError(f"request manifest {key} identity 与 descriptor 不一致")
        if not _same_content_identity(parse_manifest.get(key), descriptor.get(key)):
            raise CommandError(f"parse manifest {key} identity 与 descriptor 不一致")
    if not _same_content_identity(
        parse_manifest.get("request_manifest"), descriptor.get("request_manifest")
    ):
        raise CommandError("parse manifest request identity 与 descriptor 不一致")

    selection = _load_json_object(declared_inputs["selection"], label="selection snapshot")
    selection_rows = selection.get("targets")
    if not isinstance(selection_rows, list) or not selection_rows:
        raise CommandError("selection snapshot targets 缺失")
    targets_by_id: dict[int, dict] = {}
    inventory_identities: set[str] = set()
    for selected in selection_rows:
        if not isinstance(selected, dict):
            raise CommandError("selection snapshot target identity 非法")
        try:
            target_id = int(selected["target_id"])
            target_year = int(selected["year"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CommandError("selection snapshot target identity 非法") from exc
        target_sha = str(selected.get("target_sha256") or "")
        inventory_sha = str(
            selected.get("inventory_artifact_sha256")
            or selected.get("artifact_sha256")
            or ""
        )
        if (
            target_id <= 0
            or target_id in targets_by_id
            or target_year != protected_scope_year
            or not str(selected.get("series_key") or "").strip()
            or not str(selected.get("country_region") or "").strip()
            or not SHA256_RE.fullmatch(target_sha)
            or not SHA256_RE.fullmatch(inventory_sha)
        ):
            raise CommandError("selection snapshot target identity 非法")
        targets_by_id[target_id] = {
            **selected,
            "target_id": target_id,
            "year": target_year,
            "target_sha256": target_sha,
            "inventory_artifact_sha256": inventory_sha,
        }
        inventory_identities.add(inventory_sha)
    if len(inventory_identities) != 1:
        raise CommandError("selection snapshot inventory SHA 不唯一")

    approval = _load_json_object(approval_path, label="current-year approval")
    if (
        approval.get("status") != "approved"
        or not str(approval.get("approved_by") or "").strip()
        or not str(approval.get("approved_at") or "").strip()
    ):
        raise CommandError("current-year approval 未获有效批准")
    if approval.get("cutoff_date") != approved_cutoff.isoformat():
        raise CommandError("approval cutoff does not match approved cutoff")
    approval_scope_year = approval.get("protected_scope_year")
    if approval_scope_year is not None and approval_scope_year != protected_scope_year:
        raise CommandError("approval protected scope year 与 descriptor 不一致")
    if approval.get("descriptor_sha256") != _sha256(descriptor_path):
        raise CommandError("approval descriptor SHA identity 已漂移")
    if approval.get("classified_manifest_sha256") != _sha256(classified_manifest_path):
        raise CommandError("approval classified manifest SHA identity 已漂移")
    return CurrentYearDescriptorContext(
        cutoff_date=descriptor_cutoff,
        protected_scope_year=protected_scope_year,
        targets_by_id=targets_by_id,
        descriptor_sha256=_sha256(descriptor_path),
        inventory_artifact_sha256=next(iter(inventory_identities)),
    )


def _parse_bool(value: str, default: bool = False) -> bool:
    value = (value or "").strip()
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on", "y"}


def _parse_aliases(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    if value.startswith("["):
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            raise CommandError("aliases JSON 必须是数组")
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in value.replace(";", "|").split("|") if item.strip()]


def _parse_json(value: str) -> dict:
    value = (value or "").strip()
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise CommandError("JSON 字段必须是对象")
    return parsed


def _parse_datetime(value: str):
    value = (value or "").strip()
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise CommandError(f"race_datetime 格式应为 ISO datetime，实际为：{value}")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _parse_time(value: str):
    value = (value or "").strip()
    if not value:
        return None
    parsed = parse_time(value)
    if parsed is None:
        raise CommandError(f"local_start_time 格式应为 HH:MM[:SS]，实际为：{value}")
    return parsed


def _parse_date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    parsed = parse_date(value)
    if parsed is None:
        raise CommandError(f"local_date 格式应为 YYYY-MM-DD，实际为：{value}")
    return parsed


def _format_validation_error(error: ValidationError) -> str:
    if hasattr(error, "message_dict"):
        parts = []
        for field, messages in error.message_dict.items():
            parts.append(f"{field}: {'; '.join(str(message) for message in messages)}")
        return "；".join(parts)
    return "；".join(str(message) for message in error.messages)


def _parse_event_row(row: dict, *, line_number: int) -> tuple[int, str, dict, list[str], str]:
    try:
        original_name = (row.get("original_name") or "").strip()
        chinese_name = (row.get("chinese_name") or "").strip()
        year = int(row["year"])
        slug = (row.get("slug") or "").strip() or slugify(original_name, allow_unicode=False) or f"race-{year}"
        defaults = {
            "series_key": (row.get("series_key") or "").strip() or slug,
            "original_name": original_name,
            "chinese_name": chinese_name,
            "country_region": (row.get("country_region") or "").strip(),
            "racecourse": (row.get("racecourse") or "").strip(),
            "grade_text": (row.get("grade_text") or "").strip(),
            "normalized_grade": (row.get("normalized_grade") or "").strip(),
            "surface": (row.get("surface") or "").strip(),
            "distance_text": (row.get("distance_text") or "").strip(),
            "eligibility_text": (row.get("eligibility_text") or "").strip(),
            "race_datetime": _parse_datetime(row.get("race_datetime") or ""),
            "timezone_name": (row.get("timezone_name") or "").strip() or "Asia/Tokyo",
            "local_date": _parse_date(row.get("local_date") or ""),
            "local_start_time": _parse_time(row.get("local_start_time") or ""),
            "priority": (row.get("priority") or RaceEventPriority.P1).strip(),
            "status": (row.get("status") or RaceEventStatus.SCHEDULED).strip(),
            "visibility_status": (row.get("visibility_status") or RaceEventVisibility.PUBLISHED).strip(),
            "data_quality_status": (row.get("data_quality_status") or RaceEventDataQuality.PARTIAL).strip(),
            "is_featured": _parse_bool(row.get("is_featured") or "", default=False),
            "source_refs": _parse_json(row.get("source_refs") or ""),
            "notes": (row.get("notes") or "").strip(),
        }
        aliases = _parse_aliases(row.get("aliases") or "")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CommandError(f"第 {line_number} 行解析失败：{exc}") from exc

    event = RaceEvent(year=year, slug=slug, **defaults)
    try:
        event.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as exc:
        raise CommandError(f"第 {line_number} 行字段校验失败：{_format_validation_error(exc)}") from exc

    alias_language = (row.get("alias_language") or "").strip()
    if alias_language and alias_language not in SourceLanguage.values:
        raise CommandError(f"第 {line_number} 行 alias_language 非法：{alias_language}")
    return year, slug, defaults, aliases, alias_language


def _descriptor_row_target_id(row: dict, *, line_number: int) -> int:
    missing = [field for field in DESCRIPTOR_IDENTITY_FIELDS if not str(row.get(field) or "").strip()]
    if missing:
        raise CommandError(
            f"第 {line_number} 行缺少 descriptor target identity：{', '.join(sorted(missing))}"
        )
    try:
        target_id = int(row["target_id"])
    except (TypeError, ValueError) as exc:
        raise CommandError(f"第 {line_number} 行 target_id 非法") from exc
    if target_id <= 0:
        raise CommandError(f"第 {line_number} 行 target_id 非法")
    if not SHA256_RE.fullmatch(str(row["target_sha256"])):
        raise CommandError(f"第 {line_number} 行 target_sha256 非法")
    if not SHA256_RE.fullmatch(str(row["inventory_artifact_sha256"])):
        raise CommandError(f"第 {line_number} 行 inventory SHA 非法")
    return target_id


def _apply_current_year_descriptor_rows(
    *,
    path: Path,
    rows: list[dict],
    parsed_rows: list[tuple[int, str, dict, list[str], str]],
    context: CurrentYearDescriptorContext,
    dry_run: bool,
) -> tuple[int, int, int]:
    created = 0
    adopted = 0
    alias_count = 0
    seen_target_ids: set[int] = set()
    try:
        with transaction.atomic():
            for line_number, (row, parsed) in enumerate(
                zip(rows, parsed_rows), start=2
            ):
                year, slug, defaults, aliases, alias_language = parsed
                target_id = _descriptor_row_target_id(row, line_number=line_number)
                if target_id in seen_target_ids:
                    raise CommandError(f"第 {line_number} 行 target_id 重复")
                seen_target_ids.add(target_id)
                selected = context.targets_by_id.get(target_id)
                if selected is None:
                    raise CommandError(f"第 {line_number} 行 target 不在批准 selection 中")
                target = (
                    HistoricalRaceEventTarget.objects.select_for_update()
                    .select_related("race_series")
                    .get(pk=target_id)
                )
                row_target_sha = str(row["target_sha256"])
                row_inventory_sha = str(row["inventory_artifact_sha256"])
                if (
                    row_target_sha != selected["target_sha256"]
                    or row_inventory_sha
                    != selected["inventory_artifact_sha256"]
                    or row_inventory_sha != context.inventory_artifact_sha256
                    or target.artifact_sha256 != row_inventory_sha
                    or target_identity(target)["target_sha256"] != row_target_sha
                ):
                    raise CommandError(f"第 {line_number} 行 target identity 已漂移")
                selected_series_key = str(selected["series_key"])
                selected_region = str(selected["country_region"])
                row_series_key = str(row.get("series_key") or selected_series_key)
                if (
                    year != context.protected_scope_year
                    or year != target.year
                    or year != int(selected["year"])
                    or row_series_key != selected_series_key
                    or target.race_series.key != selected_series_key
                    or defaults["country_region"] != selected_region
                    or target.country_region != selected_region
                    or target.race_series.country_region != selected_region
                ):
                    raise CommandError(f"第 {line_number} 行 year/series/region 身份不一致")
                if (
                    target.resolution_status != HistoricalRaceResolutionStatus.PENDING
                    or target.event_id is not None
                ):
                    raise CommandError(f"第 {line_number} 行 target 不是 pending/unmaterialized")
                expected_slug = historical_event_slug(target)
                if slug != expected_slug:
                    raise CommandError(
                        f"第 {line_number} 行 slug 与 target 不一致：{slug} != {expected_slug}"
                    )
                existing_event = (
                    RaceEvent.objects.select_related("race_series")
                    .filter(race_series=target.race_series, year=year)
                    .first()
                )
                if RaceEvent.objects.filter(year=year, slug=slug).exclude(
                    pk=existing_event.pk if existing_event else None
                ).exists():
                    raise CommandError(f"第 {line_number} 行 slug conflict：{year}/{slug}")

                target.original_name = defaults["original_name"]
                target.chinese_name = defaults["chinese_name"]
                target.grade_text = defaults["grade_text"]
                target.normalized_grade = defaults["normalized_grade"]
                target.racecourse = defaults["racecourse"]
                target.surface = defaults["surface"]
                target.distance_text = defaults["distance_text"]
                target.local_date = defaults["local_date"]
                target.source_refs = defaults["source_refs"]
                target.resolution_status = HistoricalRaceResolutionStatus.READY
                target.last_checked_at = timezone.now()
                try:
                    target.full_clean()
                except ValidationError as exc:
                    raise CommandError(
                        f"第 {line_number} 行 target 校验失败：{_format_validation_error(exc)}"
                    ) from exc
                target.save(
                    update_fields={
                        "original_name",
                        "chinese_name",
                        "grade_text",
                        "normalized_grade",
                        "racecourse",
                        "surface",
                        "distance_text",
                        "local_date",
                        "source_refs",
                        "resolution_status",
                        "last_checked_at",
                    }
                )
                if existing_event is not None:
                    try:
                        adopt_existing_race_event_for_target(
                            target_id=target.pk,
                            expected_event_id=existing_event.pk,
                        )
                    except RaceEventReconciliationError as exc:
                        raise CommandError(
                            f"第 {line_number} 行 existing event 无法安全采用：{exc}"
                        ) from exc
                    target.refresh_from_db(fields={"event"})
                    event = existing_event
                    adopted += 1
                else:
                    event = materialize_historical_event(target)
                    created += 1
                if (
                    event is None
                    or event.race_series_id != target.race_series_id
                    or event.year != target.year
                    or (existing_event is None and event.slug != expected_slug)
                ):
                    raise CommandError(f"第 {line_number} 行 materialized event 身份不一致")
                if existing_event is None:
                    event.visibility_status = RaceEventVisibility.DRAFT
                    event.data_quality_status = RaceEventDataQuality.INCOMPLETE
                    event.is_featured = False
                    event.save(
                        update_fields={
                            "visibility_status",
                            "data_quality_status",
                            "is_featured",
                        }
                    )
                apply_race_event_normalization(event)
                for alias in aliases:
                    if not RaceEventAlias.objects.filter(
                        event=event, source_language=alias_language, text=alias
                    ).exists():
                        RaceEventAlias.objects.create(
                            event=event,
                            source_language=alias_language,
                            text=alias,
                            alias_type="alias",
                            source="csv",
                            is_active=True,
                        )
                        alias_count += 1
            TaskExecutionLog.objects.create(
                task_name="import_race_events",
                status=TaskStatus.SUCCESS,
                payload={
                    "csv": str(path),
                    "created": created,
                    "adopted": adopted,
                    "updated": 0,
                    "alias_count": alias_count,
                    "descriptor_sha256": context.descriptor_sha256,
                    "inventory_artifact_sha256": context.inventory_artifact_sha256,
                    "protected_scope_year": context.protected_scope_year,
                    "cutoff_date": context.cutoff_date.isoformat(),
                },
                detail=(
                    "年度赛事 descriptor CSV 导入完成："
                    f"created={created} adopted={adopted} updated=0 aliases={alias_count}"
                ),
                started_at=timezone.now(),
                finished_at=timezone.now(),
            )
            if dry_run:
                transaction.set_rollback(True)
    except HistoricalRaceEventTarget.DoesNotExist as exc:
        raise CommandError("descriptor target 不存在") from exc
    except InventoryValidationError as exc:
        raise CommandError(f"descriptor materialization 失败：{exc}") from exc
    return created, adopted, alias_count


class Command(BaseCommand):
    help = "从 CSV 导入或更新年度赛事日历种子。"

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True, help="CSV 文件路径。")
        parser.add_argument("--dry-run", action="store_true", help="只校验和输出统计，不写入数据库。")
        parser.add_argument(
            "--current-year-descriptor",
            help="当前年度正式导入必须提供的 due-only apply_descriptor.json。",
        )
        parser.add_argument(
            "--current-year-approval",
            help="批准 descriptor 与截止日的 apply_approval.json。",
        )
        parser.add_argument(
            "--approved-cutoff-date",
            help="当前年度批准截止日，必须与 descriptor、approval 完全一致。",
        )

    def handle(self, *args, **options):
        path = Path(options["csv"]).expanduser()
        if not path.exists():
            raise CommandError(f"CSV 文件不存在：{path}")
        created = 0
        updated = 0
        adopted = 0
        alias_count = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"CSV 缺少字段：{', '.join(sorted(missing))}")
            rows = list(reader)
        descriptor_options = (
            options.get("current_year_descriptor"),
            options.get("current_year_approval"),
            options.get("approved_cutoff_date"),
        )
        contains_protected_scope = False
        for row in rows:
            try:
                contains_protected_scope = contains_protected_scope or int(
                    str(row.get("year") or "").strip()
                ) >= PROTECTED_CURRENT_YEAR_SCOPE_START
            except ValueError:
                pass
        if contains_protected_scope and not all(descriptor_options):
            raise CommandError(
                "current-year CSV 必须通过 descriptor、approval 与 approved cutoff 正式导入"
            )
        if any(descriptor_options) and not all(descriptor_options):
            raise CommandError(
                "current-year descriptor、approval 与 approved cutoff 必须同时提供"
            )
        descriptor_context = None
        if all(descriptor_options):
            try:
                approved_cutoff = date.fromisoformat(options["approved_cutoff_date"])
            except ValueError as exc:
                raise CommandError("approved cutoff 必须是 YYYY-MM-DD") from exc
            if approved_cutoff > timezone.localdate():
                raise CommandError("approved cutoff 不得晚于 today（未来日期）")
            descriptor_context = _validate_current_year_descriptor(
                csv_path=path,
                descriptor_path=Path(options["current_year_descriptor"]),
                approval_path=Path(options["current_year_approval"]),
                approved_cutoff=approved_cutoff,
            )
        parsed_rows = [
            _parse_event_row(row, line_number=index)
            for index, row in enumerate(rows, start=2)
        ]
        if descriptor_context is not None:
            for index, (row, parsed) in enumerate(zip(rows, parsed_rows), start=2):
                local_date = parsed[2]["local_date"]
                if (
                    parsed[0] != descriptor_context.protected_scope_year
                    or parsed[2]["status"] != RaceEventStatus.FINISHED
                    or local_date is None
                    or local_date > descriptor_context.cutoff_date
                ):
                    raise CommandError(
                        f"第 {index} 行不是批准截止日前的 due_event，禁止正式导入"
                    )
                parsed[2]["visibility_status"] = RaceEventVisibility.DRAFT
                parsed[2]["data_quality_status"] = RaceEventDataQuality.INCOMPLETE
                parsed[2]["is_featured"] = False
            created, adopted, alias_count = _apply_current_year_descriptor_rows(
                path=path,
                rows=rows,
                parsed_rows=parsed_rows,
                context=descriptor_context,
                dry_run=options["dry_run"],
            )
            if options["dry_run"]:
                self.stdout.write(
                    f"dry-run 通过：将处理 {len(parsed_rows)} 条赛事记录。"
                )
                return
            self.stdout.write(
                self.style.SUCCESS(
                    "年度赛事导入完成："
                    f"created={created} adopted={adopted} updated=0 aliases={alias_count}"
                )
            )
            return
        if options["dry_run"]:
            self.stdout.write(f"dry-run 通过：将处理 {len(parsed_rows)} 条赛事记录。")
            return
        with transaction.atomic():
            for year, slug, defaults, aliases, alias_language in parsed_rows:
                event, was_created = RaceEvent.objects.update_or_create(
                    year=year, slug=slug, defaults=defaults
                )
                apply_race_event_normalization(event)
                for alias in aliases:
                    RaceEventAlias.objects.update_or_create(
                        event=event,
                        source_language=alias_language,
                        text=alias,
                        defaults={
                            "alias_type": "alias",
                            "source": "csv",
                            "is_active": True,
                        },
                    )
                    alias_count += 1
                created += int(was_created)
                updated += int(not was_created)
            TaskExecutionLog.objects.create(
                task_name="import_race_events",
                status=TaskStatus.SUCCESS,
                payload={
                    "csv": str(path),
                    "created": created,
                    "updated": updated,
                    "alias_count": alias_count,
                },
                detail=(
                    "年度赛事 CSV 导入完成："
                    f"created={created} updated={updated} aliases={alias_count}"
                ),
                started_at=timezone.now(),
                finished_at=timezone.now(),
            )
        self.stdout.write(self.style.SUCCESS(f"年度赛事导入完成：created={created} updated={updated} aliases={alias_count}"))

from __future__ import annotations

import csv
import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from django.utils.text import slugify

from stable.models import (
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


REQUIRED_FIELDS = {"year", "original_name", "chinese_name", "country_region", "racecourse", "grade_text", "surface"}


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


class Command(BaseCommand):
    help = "从 CSV 导入或更新年度赛事日历种子。"

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True, help="CSV 文件路径。")
        parser.add_argument("--dry-run", action="store_true", help="只校验和输出统计，不写入数据库。")

    def handle(self, *args, **options):
        path = Path(options["csv"]).expanduser()
        if not path.exists():
            raise CommandError(f"CSV 文件不存在：{path}")
        created = 0
        updated = 0
        alias_count = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"CSV 缺少字段：{', '.join(sorted(missing))}")
            rows = list(reader)
        parsed_rows = [
            _parse_event_row(row, line_number=index)
            for index, row in enumerate(rows, start=2)
        ]
        if options["dry_run"]:
            self.stdout.write(f"dry-run 通过：将处理 {len(parsed_rows)} 条赛事记录。")
            return
        for year, slug, defaults, aliases, alias_language in parsed_rows:
            event, was_created = RaceEvent.objects.update_or_create(year=year, slug=slug, defaults=defaults)
            for alias in aliases:
                RaceEventAlias.objects.update_or_create(
                    event=event,
                    source_language=alias_language,
                    text=alias,
                    defaults={"alias_type": "alias", "source": "csv", "is_active": True},
                )
                alias_count += 1
            created += int(was_created)
            updated += int(not was_created)
        TaskExecutionLog.objects.create(
            task_name="import_race_events",
            status=TaskStatus.SUCCESS,
            payload={"csv": str(path), "created": created, "updated": updated, "alias_count": alias_count},
            detail=f"年度赛事 CSV 导入完成：created={created} updated={updated} aliases={alias_count}",
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        self.stdout.write(self.style.SUCCESS(f"年度赛事导入完成：created={created} updated={updated} aliases={alias_count}"))

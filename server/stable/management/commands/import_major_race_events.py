from __future__ import annotations

import csv
import json
from datetime import date, time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.models import MajorRaceEvent
from stable.services.production_windows import update_major_race_boost_window


def _parse_bool(value: str, default: bool = True) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise CommandError(f"local_date 格式应为 YYYY-MM-DD，实际为：{value}") from exc


def _parse_time(value: str) -> time | None:
    value = value.strip()
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(f"local_start_time 格式应为 HH:MM[:SS]，实际为：{value}") from exc


def _parse_aliases(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    if value.startswith("["):
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            raise CommandError("aliases JSON 必须是数组")
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in value.replace(";", "|").split("|") if item.strip()]


class Command(BaseCommand):
    help = "从 CSV 导入或更新重要赛事升频窗口"

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True, help="CSV 文件路径")

    def handle(self, *args, **options):
        path = Path(options["csv"])
        if not path.exists():
            raise CommandError(f"CSV 文件不存在：{path}")
        created = 0
        updated = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"name", "year", "racing_region", "race_grade", "local_date", "timezone_name"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"CSV 缺少字段：{', '.join(sorted(missing))}")
            for row in reader:
                name = (row.get("name") or "").strip()
                normalized_name = (row.get("normalized_name") or "").strip() or name
                if not name or not normalized_name:
                    raise CommandError("name / normalized_name 不能为空")
                defaults = {
                    "name": name,
                    "external_id": (row.get("external_id") or "").strip(),
                    "aliases": _parse_aliases(row.get("aliases") or ""),
                    "timezone_name": (row.get("timezone_name") or "").strip(),
                    "local_date": _parse_date(row.get("local_date") or ""),
                    "local_start_time": _parse_time(row.get("local_start_time") or ""),
                    "is_active": _parse_bool(row.get("is_active") or "", default=True),
                    "notes": (row.get("notes") or "").strip(),
                }
                event, was_created = MajorRaceEvent.objects.update_or_create(
                    normalized_name=normalized_name,
                    year=int(row["year"]),
                    racing_region=(row.get("racing_region") or "").strip(),
                    race_grade=(row.get("race_grade") or "").strip(),
                    defaults=defaults,
                )
                update_major_race_boost_window(event)
                if was_created:
                    created += 1
                else:
                    updated += 1
        self.stdout.write(self.style.SUCCESS(f"重要赛事导入完成：created={created} updated={updated}"))

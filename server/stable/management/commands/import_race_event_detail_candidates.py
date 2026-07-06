from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.models import RaceEvent, RaceEventModule
from stable.services.race_events import apply_data_candidate, save_data_candidate


MODULES_ALLOWING_BATCH_IMPORT = {
    RaceEventModule.RUNNERS,
    RaceEventModule.RESULTS,
    RaceEventModule.HISTORY_WINNERS,
}


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CommandError(f"第 {line_number} 行不是合法 JSON：{exc}") from exc
            if not isinstance(record, dict):
                raise CommandError(f"第 {line_number} 行必须是 JSON 对象")
            record["_line_number"] = line_number
            records.append(record)
    return records


def _normalize_module_payload(module: str, payload) -> dict:
    if module not in MODULES_ALLOWING_BATCH_IMPORT:
        raise CommandError(f"暂不支持批量导入模块：{module}")
    if isinstance(payload, list):
        payload = {"items": payload}
    if not isinstance(payload, dict):
        raise CommandError(f"{module} payload 必须是对象或数组")
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise CommandError(f"{module}.items 必须是数组")
    if any(not isinstance(item, dict) for item in items):
        raise CommandError(f"{module}.items 内每一项必须是对象")
    return payload


def _validate_record(record: dict) -> tuple[RaceEvent, str, dict[str, dict], str]:
    line_number = record.get("_line_number")
    year = record.get("year")
    slug = str(record.get("slug") or "").strip()
    if not year or not slug:
        raise CommandError(f"第 {line_number} 行缺少 year 或 slug")
    try:
        event = RaceEvent.objects.get(year=int(year), slug=slug)
    except RaceEvent.DoesNotExist as exc:
        raise CommandError(f"第 {line_number} 行找不到赛事：year={year} slug={slug}") from exc

    modules = record.get("modules")
    if not isinstance(modules, dict) or not modules:
        raise CommandError(f"第 {line_number} 行 modules 必须是非空对象")
    normalized_modules = {
        str(module): _normalize_module_payload(str(module), payload)
        for module, payload in modules.items()
    }
    source_url = str(record.get("source_url") or "")
    return event, str(record.get("source_name") or "json"), normalized_modules, source_url


class Command(BaseCommand):
    help = "从 JSONL 批量导入赛事出走表、赛果和历届冠军候选，可选择立即应用到正式表。"

    def add_arguments(self, parser):
        parser.add_argument("--jsonl", required=True, help="候选 JSONL 文件路径。每行一场赛事。")
        parser.add_argument("--dry-run", action="store_true", help="只校验，不写入候选池或正式表。")
        parser.add_argument("--apply", action="store_true", help="保存候选后立即应用到正式表。")
        parser.add_argument("--confidence", type=int, default=90, help="候选默认置信度。")

    def handle(self, *args, **options):
        path = Path(options["jsonl"]).expanduser()
        if not path.exists():
            raise CommandError(f"JSONL 文件不存在：{path}")

        records = _read_jsonl(path)
        parsed = [_validate_record(record) for record in records]

        event_count = len(parsed)
        module_count = sum(len(modules) for _, _, modules, _ in parsed)
        item_count_by_module: dict[str, int] = {}
        for _, _, modules, _ in parsed:
            for module, payload in modules.items():
                item_count_by_module[module] = item_count_by_module.get(module, 0) + len(payload.get("items", []))

        if options["dry_run"]:
            self.stdout.write(
                "dry-run 通过："
                f"events={event_count} modules={module_count} items={json.dumps(item_count_by_module, ensure_ascii=False)}"
            )
            return

        candidate_count = 0
        applied_count = 0
        for event, source_name, modules, source_url in parsed:
            raw_payload = {
                "year": event.year,
                "slug": event.slug,
                "source_name": source_name,
                "source_url": source_url,
                "modules": modules,
            }
            for module, module_payload in modules.items():
                candidate = save_data_candidate(
                    event=event,
                    module=module,
                    source_name=source_name,
                    source_url=source_url,
                    candidate_payload=module_payload,
                    raw_payload=raw_payload,
                    confidence=options["confidence"],
                )
                candidate_count += 1
                if options["apply"]:
                    apply_data_candidate(candidate)
                    applied_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"导入完成：events={event_count} candidates={candidate_count} applied={applied_count} "
                f"items={json.dumps(item_count_by_module, ensure_ascii=False)}"
            )
        )

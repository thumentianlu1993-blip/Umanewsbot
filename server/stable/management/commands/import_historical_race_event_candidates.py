from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_importer import (
    apply_historical_target_candidate,
    validate_historical_target_candidate,
)
from stable.services.historical_race_inventory import InventoryValidationError


class Command(BaseCommand):
    help = "按年度原子 scope 导入已批准的历史赛事详情候选。"

    def add_arguments(self, parser):
        parser.add_argument("--jsonl", required=True)
        parser.add_argument("--expected-sha256", required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if options["dry_run"] == options["apply"]:
            raise CommandError("必须且只能选择 --dry-run 或 --apply。")
        path = Path(options["jsonl"])
        if not path.is_file():
            raise CommandError(f"候选文件不存在：{path}")
        raw = path.read_bytes()
        actual_sha = hashlib.sha256(raw).hexdigest()
        if actual_sha != str(options["expected_sha256"]).lower():
            raise CommandError(
                f"candidate_sha256_mismatch: expected={options['expected_sha256']} actual={actual_sha}"
            )
        if options["apply"] and not settings.HISTORICAL_RACE_BACKFILL_ENABLED:
            raise CommandError("historical race backfill is disabled")
        records = []
        for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CommandError(f"第 {line_number} 行不是合法 JSON：{exc}") from exc
            required = {
                "target_id",
                "target_sha256",
                "inventory_artifact_sha256",
                "source_name",
                "source_url",
                "modules",
            }
            if not isinstance(record, dict) or required - set(record):
                raise CommandError(f"第 {line_number} 行缺少字段：{sorted(required - set(record or {}))}")
            if not isinstance(record["modules"], dict):
                raise CommandError(f"第 {line_number} 行 modules 必须是对象")
            records.append(record)
        if options["dry_run"]:
            for record in records:
                try:
                    validate_historical_target_candidate(
                        target_id=int(record["target_id"]),
                        expected_target_sha256=str(record["target_sha256"]),
                        inventory_artifact_sha256=str(record["inventory_artifact_sha256"]),
                        modules=record["modules"],
                    )
                except (InventoryValidationError, ObjectDoesNotExist, ValueError) as exc:
                    raise CommandError(f"年度 scope {record['target_id']} 校验失败：{exc}") from exc
            self.stdout.write(f"dry-run 通过：scopes={len(records)} candidate_sha256={actual_sha}")
            return
        applied = 0
        for record in records:
            try:
                apply_historical_target_candidate(
                    target_id=int(record["target_id"]),
                    expected_target_sha256=str(record["target_sha256"]),
                    inventory_artifact_sha256=str(record["inventory_artifact_sha256"]),
                    source_name=str(record["source_name"]),
                    source_url=str(record["source_url"]),
                    modules=record["modules"],
                )
            except (InventoryValidationError, ObjectDoesNotExist, ValueError) as exc:
                raise CommandError(f"年度 scope {record['target_id']} 导入失败：{exc}") from exc
            applied += 1
        self.stdout.write(self.style.SUCCESS(f"历史赛事导入完成：scopes={applied} candidate_sha256={actual_sha}"))

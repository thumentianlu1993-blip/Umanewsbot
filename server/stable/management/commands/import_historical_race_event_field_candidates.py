from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_importer import (
    apply_authoritative_event_field_batch,
    validate_authoritative_event_field_batch,
)
from stable.services.historical_race_inventory import InventoryValidationError


class Command(BaseCommand):
    help = "按整文件SHA锁定的JSONL批次dry-run或原子更新历史年度赛事权威基础字段。"

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
        try:
            for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise InventoryValidationError(
                        f"authoritative field row must be an object: line={line_number}"
                    )
                records.append(payload)
            if options["apply"]:
                result = apply_authoritative_event_field_batch(
                    records,
                    candidate_sha256=actual_sha,
                )
                mode = "apply"
            else:
                result = validate_authoritative_event_field_batch(records)
                mode = "dry_run"
        except (InventoryValidationError, json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                {"mode": mode, "candidate_sha256": actual_sha, **result},
                ensure_ascii=False,
                sort_keys=True,
            )
        )

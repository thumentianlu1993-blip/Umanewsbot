from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_date_discovery import build_provider_discovery_candidates
from stable.services.historical_race_inventory import InventoryValidationError, canonical_json


class Command(BaseCommand):
    help = "把五地区来源记录映射到不可变历史赛事selection snapshot。"

    def add_arguments(self, parser):
        parser.add_argument("--provider-jsonl", action="append", required=True)
        parser.add_argument("--selection-snapshot", required=True)
        parser.add_argument("--inventory-manifest-sha256", required=True)
        parser.add_argument("--output-jsonl", required=True)
        parser.add_argument("--issues-json", required=True)

    def handle(self, *args, **options):
        rows = []
        try:
            for source in options["provider_jsonl"]:
                with Path(source).open(encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if not line.strip():
                            continue
                        payload = json.loads(line)
                        if not isinstance(payload, dict):
                            raise CommandError(f"来源记录必须是对象：{source}:{line_number}")
                        rows.append(payload)
            result = build_provider_discovery_candidates(
                provider_rows=rows,
                selection_snapshot_path=options["selection_snapshot"],
                inventory_manifest_sha256=options["inventory_manifest_sha256"],
            )
            output_path = Path(options["output_jsonl"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "".join(canonical_json(row) + "\n" for row in result["candidate_rows"]),
                encoding="utf-8",
            )
            issues_path = Path(options["issues_json"])
            issues_path.parent.mkdir(parents=True, exist_ok=True)
            issues_path.write_text(
                json.dumps(result["issues"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except (InventoryValidationError, json.JSONDecodeError, OSError, TypeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                {
                    "candidate_count": len(result["candidate_rows"]),
                    "issue_count": len(result["issues"]),
                    "output_jsonl": str(output_path),
                    "issues_json": str(issues_path),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

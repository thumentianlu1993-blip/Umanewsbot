from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_date_discovery import (
    apply_date_source_discovery_artifact,
    build_date_source_discovery_artifact,
)
from stable.services.historical_race_inventory import InventoryValidationError


class Command(BaseCommand):
    help = "从离线候选生成历史赛事日期/直接来源artifact，或提交已批准artifact。"

    def add_arguments(self, parser):
        parser.add_argument("--candidate-jsonl")
        parser.add_argument("--selection-snapshot")
        parser.add_argument("--output-dir")
        parser.add_argument("--inventory-manifest-sha256")
        parser.add_argument("--source-cache-manifest")
        parser.add_argument("--request-ledger")
        parser.add_argument("--artifact-dir")
        parser.add_argument("--approval")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        try:
            if options["commit"]:
                if options["candidate_jsonl"] or options["output_dir"]:
                    raise CommandError("commit只能读取既有artifact，不能同时重新生成输入。")
                if not options["artifact_dir"] or not options["approval"]:
                    raise CommandError("commit需要--artifact-dir和--approval。")
                result = apply_date_source_discovery_artifact(
                    artifact_dir=options["artifact_dir"],
                    approval_path=options["approval"],
                )
            else:
                required = (
                    "candidate_jsonl",
                    "selection_snapshot",
                    "output_dir",
                    "inventory_manifest_sha256",
                    "source_cache_manifest",
                    "request_ledger",
                )
                missing = [name for name in required if not options[name]]
                if missing:
                    raise CommandError(f"只读生成阶段缺少参数：{', '.join(missing)}")
                rows = []
                with Path(options["candidate_jsonl"]).open(encoding="utf-8") as handle:
                    for line in handle:
                        if line.strip():
                            rows.append(json.loads(line))
                result = build_date_source_discovery_artifact(
                    candidate_rows=rows,
                    selection_snapshot_path=options["selection_snapshot"],
                    output_dir=options["output_dir"],
                    inventory_manifest_sha256=options["inventory_manifest_sha256"],
                    source_cache_manifest_path=options["source_cache_manifest"],
                    request_ledger_path=options["request_ledger"],
                )
        except (InventoryValidationError, json.JSONDecodeError, OSError, TypeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))

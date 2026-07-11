from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_inventory import (
    InventoryValidationError,
    build_inventory_artifact,
    commit_inventory_artifact,
)


class Command(BaseCommand):
    help = "从离线逐年目录和系列 timeline 生成历史赛事总账 artifact，或提交已批准 artifact。"

    def add_arguments(self, parser):
        parser.add_argument("--catalog-jsonl", action="append", default=[])
        parser.add_argument("--timeline-jsonl", action="append", default=[])
        parser.add_argument("--output-dir")
        parser.add_argument("--artifact-dir")
        parser.add_argument("--approval")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        try:
            if options["commit"]:
                if options["catalog_jsonl"] or options["timeline_jsonl"] or options["output_dir"]:
                    raise CommandError("commit 只能读取既有 artifact，不能同时重新生成输入。")
                if not options["artifact_dir"] or not options["approval"]:
                    raise CommandError("commit 需要 --artifact-dir 和 --approval。")
                result = commit_inventory_artifact(
                    artifact_dir=Path(options["artifact_dir"]),
                    approval_path=Path(options["approval"]),
                )
            else:
                if options["artifact_dir"] or options["approval"]:
                    raise CommandError("只读生成阶段请使用 --catalog-jsonl、--timeline-jsonl 和 --output-dir。")
                if not options["output_dir"]:
                    raise CommandError("只读生成阶段需要 --output-dir。")
                if not options["catalog_jsonl"]:
                    raise CommandError("至少需要一个 --catalog-jsonl 逐年目录输入。")
                result = build_inventory_artifact(
                    catalog_paths=options["catalog_jsonl"],
                    timeline_paths=options["timeline_jsonl"],
                    output_dir=Path(options["output_dir"]),
                )
        except InventoryValidationError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))

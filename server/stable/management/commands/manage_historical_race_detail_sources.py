from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_detail_sources import (
    apply_detail_source_artifact,
    build_detail_source_artifact,
    check_detail_source_artifact,
)
from stable.services.historical_race_inventory import InventoryValidationError


class Command(BaseCommand):
    help = "生成、校验或提交历史赛事详情补充来源artifact。"

    def add_arguments(self, parser):
        parser.add_argument("--candidate-jsonl", action="append")
        parser.add_argument("--source-cache-manifest", action="append")
        parser.add_argument("--output-dir")
        parser.add_argument("--artifact-dir")
        parser.add_argument("--approval")
        parser.add_argument("--check", action="store_true")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        try:
            if options["check"] and options["commit"]:
                raise CommandError("--check与--commit不能同时使用。")
            if options["check"] or options["commit"]:
                if options["candidate_jsonl"] or options["source_cache_manifest"] or options["output_dir"]:
                    raise CommandError("校验/提交只能读取既有artifact，不能同时重新生成。")
                if not options["artifact_dir"] or not options["approval"]:
                    raise CommandError("校验/提交需要--artifact-dir和--approval。")
                function = apply_detail_source_artifact if options["commit"] else check_detail_source_artifact
                result = function(
                    artifact_dir=options["artifact_dir"],
                    approval_path=options["approval"],
                )
            else:
                if not options["candidate_jsonl"] or not options["source_cache_manifest"] or not options["output_dir"]:
                    raise CommandError("生成阶段需要--candidate-jsonl、--source-cache-manifest和--output-dir。")
                result = build_detail_source_artifact(
                    candidate_jsonl_paths=options["candidate_jsonl"],
                    source_cache_manifest_paths=options["source_cache_manifest"],
                    output_dir=options["output_dir"],
                )
        except (InventoryValidationError, OSError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))

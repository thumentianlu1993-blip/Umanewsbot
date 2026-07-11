from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_inventory import (
    InventoryValidationError,
    build_existing_event_mapping_artifact,
    commit_existing_event_mapping,
)


class Command(BaseCommand):
    help = "为现有年度 RaceEvent 生成稳定系列 mapping artifact，或提交已批准 mapping。"

    def add_arguments(self, parser):
        parser.add_argument("--output-dir")
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--overrides-json")
        parser.add_argument("--artifact-dir")
        parser.add_argument("--approval")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        try:
            if options["commit"]:
                if options["output_dir"] or options["overrides_json"]:
                    raise CommandError("commit 只能读取既有 mapping artifact。")
                if not options["artifact_dir"] or not options["approval"]:
                    raise CommandError("commit 需要 --artifact-dir 和 --approval。")
                result = commit_existing_event_mapping(
                    artifact_dir=options["artifact_dir"],
                    approval_path=options["approval"],
                )
            else:
                if not options["output_dir"]:
                    raise CommandError("只读 mapping 需要 --output-dir。")
                if options["artifact_dir"] or options["approval"]:
                    raise CommandError("只读 mapping 不接受 --artifact-dir 或 --approval。")
                result = build_existing_event_mapping_artifact(
                    output_dir=options["output_dir"],
                    year=options["year"],
                    overrides_path=options["overrides_json"],
                )
        except InventoryValidationError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))

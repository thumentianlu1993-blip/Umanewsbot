from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_catalog_adapters import build_catalog_candidate_artifact
from stable.services.historical_race_inventory import InventoryValidationError


class Command(BaseCommand):
    help = "离线校验五地区历史赛事目录 cache manifest，并生成标准 catalog/timeline 候选。"

    def add_arguments(self, parser):
        parser.add_argument("--source-manifest", action="append", default=[])
        parser.add_argument("--output-dir", required=True)

    def handle(self, *args, **options):
        try:
            result = build_catalog_candidate_artifact(
                manifest_paths=options["source_manifest"],
                output_dir=options["output_dir"],
            )
        except InventoryValidationError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))

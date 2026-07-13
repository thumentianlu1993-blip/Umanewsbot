from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_batches import (
    select_historical_band_batch_targets,
    write_band_batch_artifact,
)
from stable.services.historical_race_inventory import InventoryValidationError


class Command(BaseCommand):
    help = "从已批准历史总账生成一个五地区年代带标准批次artifact。"

    def add_arguments(self, parser):
        parser.add_argument("--year-start", required=True, type=int)
        parser.add_argument("--year-end", required=True, type=int)
        parser.add_argument("--region-limit", type=int, default=50)
        parser.add_argument("--inventory-manifest-sha256", required=True)
        parser.add_argument("--output-dir", required=True)

    def handle(self, *args, **options):
        try:
            targets = select_historical_band_batch_targets(
                year_start=options["year_start"],
                year_end=options["year_end"],
                inventory_manifest_sha256=options["inventory_manifest_sha256"],
                region_limit=options["region_limit"],
            )
            result = write_band_batch_artifact(
                targets,
                output_dir=options["output_dir"],
                inventory_manifest_sha256=options["inventory_manifest_sha256"],
                year_start=options["year_start"],
                year_end=options["year_end"],
            )
        except (InventoryValidationError, OSError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))

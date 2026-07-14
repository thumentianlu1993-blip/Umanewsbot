from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_batches import (
    read_immutable_selection_snapshot,
    select_historical_band_batch_targets,
    validate_selection_snapshot_target_identities,
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
        parser.add_argument("--exclude-selection-snapshot", action="append", default=[])
        parser.add_argument("--output-dir", required=True)

    def handle(self, *args, **options):
        try:
            exclusions = [
                read_immutable_selection_snapshot(
                    path,
                    inventory_manifest_sha256=options["inventory_manifest_sha256"],
                )
                for path in options["exclude_selection_snapshot"]
            ]
            excluded_target_ids = validate_selection_snapshot_target_identities(
                exclusions,
                inventory_manifest_sha256=options["inventory_manifest_sha256"],
            )
            targets = select_historical_band_batch_targets(
                year_start=options["year_start"],
                year_end=options["year_end"],
                inventory_manifest_sha256=options["inventory_manifest_sha256"],
                region_limit=options["region_limit"],
                excluded_target_ids=excluded_target_ids,
            )
            result = write_band_batch_artifact(
                targets,
                output_dir=options["output_dir"],
                inventory_manifest_sha256=options["inventory_manifest_sha256"],
                year_start=options["year_start"],
                year_end=options["year_end"],
                exclusion_snapshots=exclusions,
            )
        except (InventoryValidationError, OSError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))

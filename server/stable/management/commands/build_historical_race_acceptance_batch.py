from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_batches import (
    select_first_acceptance_targets,
    write_batch_snapshot,
)
from stable.services.historical_race_inventory import InventoryValidationError


class Command(BaseCommand):
    help = "从已批准历史总账生成分阶段首批验收target快照。"

    def add_arguments(self, parser):
        parser.add_argument("--series-selection", required=True)
        parser.add_argument("--anchors", required=True)
        parser.add_argument("--inventory-manifest-sha256", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--post-discovery", action="store_true")
        parser.add_argument("--required-target-ids")

    def handle(self, *args, **options):
        try:
            series_selection = json.loads(Path(options["series_selection"]).read_text(encoding="utf-8"))
            if not isinstance(series_selection, dict):
                raise InventoryValidationError("series selection must be an object keyed by region")
            try:
                anchors = tuple(int(value.strip()) for value in options["anchors"].split(","))
            except ValueError as exc:
                raise InventoryValidationError("anchors must be comma-separated years") from exc
            required_ids = None
            if options["post_discovery"]:
                if not options["required_target_ids"]:
                    raise InventoryValidationError("post-discovery selection requires target id file")
                required_payload = json.loads(Path(options["required_target_ids"]).read_text(encoding="utf-8"))
                required_ids = (
                    required_payload.get("target_ids")
                    if isinstance(required_payload, dict)
                    else required_payload
                )
                if not isinstance(required_ids, list):
                    raise InventoryValidationError("required target id file must contain a list")
            targets = select_first_acceptance_targets(
                series_keys_by_region=series_selection,
                anchors=anchors,
                require_ready=options["post_discovery"],
                required_target_ids=required_ids,
            )
            payload = write_batch_snapshot(
                targets,
                output_path=options["output"],
                inventory_manifest_sha256=options["inventory_manifest_sha256"],
            )
        except (InventoryValidationError, json.JSONDecodeError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                {
                    "output": options["output"],
                    "target_count": payload["target_count"],
                    "snapshot_sha256": payload["snapshot_sha256"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

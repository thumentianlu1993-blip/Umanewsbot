from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.models import HistoricalRaceEventTarget
from stable.services.historical_race_batches import write_event_input_csvs
from stable.services.historical_race_inventory import InventoryValidationError


class Command(BaseCommand):
    help = "把已批准且已materialize的历史target导出为各地区详情adapter标准CSV。"

    def add_arguments(self, parser):
        parser.add_argument("--target-ids-json", required=True)
        parser.add_argument("--output-dir", required=True)

    def handle(self, *args, **options):
        try:
            payload = json.loads(Path(options["target_ids_json"]).read_text(encoding="utf-8"))
            target_ids = payload.get("approved_target_ids") if isinstance(payload, dict) else payload
            if (
                not isinstance(target_ids, list)
                or not target_ids
                or not all(isinstance(value, int) for value in target_ids)
                or len(target_ids) != len(set(target_ids))
            ):
                raise InventoryValidationError("event input target ids are invalid")
            targets = list(
                HistoricalRaceEventTarget.objects.select_related("race_series", "event")
                .filter(pk__in=target_ids)
                .order_by("country_region", "year", "pk")
            )
            if {target.pk for target in targets} != set(target_ids):
                raise InventoryValidationError("event input target ids are incomplete")
            result = write_event_input_csvs(targets, output_dir=options["output_dir"])
        except (InventoryValidationError, json.JSONDecodeError, OSError, TypeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services.race_result_recovery_inventory import (
    RecoveryInventoryError,
    build_recovery_inventory,
    write_immutable_inventory,
)


class Command(BaseCommand):
    help = "生成只读、不可覆盖的赛事赛果恢复双层 inventory。"

    def add_arguments(self, parser):
        parser.add_argument("--start-date", required=True)
        parser.add_argument("--end-date", required=True)
        parser.add_argument("--as-of", required=True)
        parser.add_argument(
            "--expected-event-ids",
            required=True,
            help="逗号分隔的已审批 RaceEvent ID。",
        )
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            start_date = date.fromisoformat(options["start_date"])
            end_date = date.fromisoformat(options["end_date"])
            as_of = datetime.fromisoformat(
                options["as_of"].replace("Z", "+00:00")
            )
            if timezone.is_naive(as_of):
                raise ValueError("as-of must include a timezone")
            expected_ids = [
                int(value)
                for value in options["expected_event_ids"].split(",")
                if value.strip()
            ]
            if not expected_ids:
                raise ValueError("expected event IDs are empty")
            output = Path(options["output"])
            artifact = build_recovery_inventory(
                start_date=start_date,
                end_date=end_date,
                as_of=as_of,
                expected_event_ids=expected_ids,
            )
            identity = write_immutable_inventory(artifact, output)
        except (ValueError, RecoveryInventoryError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                {
                    "status": "created",
                    "event_row_count": len(artifact["event_rows"]),
                    "race_group_count": len(artifact["race_groups"]),
                    **identity,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

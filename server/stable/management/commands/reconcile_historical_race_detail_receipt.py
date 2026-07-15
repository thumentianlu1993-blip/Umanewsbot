from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_detail_chunk_import import (
    HistoricalRaceDetailChunkError,
    reconcile_historical_race_detail_receipt,
)


class Command(BaseCommand):
    help = "在确认无业务写入后，将 STARTED 历史详情 receipt 标记为 ABANDONED。"

    def add_arguments(self, parser):
        parser.add_argument("--receipt-id", required=True)
        parser.add_argument("--runner-run-id", required=True)
        parser.add_argument("--approved-by", required=True)
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        try:
            report = reconcile_historical_race_detail_receipt(
                receipt_id=options["receipt_id"],
                runner_run_id=options["runner_run_id"],
                approved_by=options["approved_by"],
                reason=options["reason"],
            )
        except HistoricalRaceDetailChunkError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))

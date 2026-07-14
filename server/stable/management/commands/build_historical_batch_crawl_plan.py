from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_batch_pipeline import (
    HistoricalBatchPipelineError,
    build_historical_batch_shard_plan,
)


class Command(BaseCommand):
    help = "从已批准的 stage descriptor 原子生成一个正式 historical crawl shard plan。"

    def add_arguments(self, parser):
        parser.add_argument("--descriptor", required=True)
        parser.add_argument("--shard-id", required=True)
        parser.add_argument("--output-dir", required=True)

    def handle(self, *args, **options):
        try:
            result = build_historical_batch_shard_plan(
                descriptor_path=options["descriptor"],
                shard_id=options["shard_id"],
                output_dir=options["output_dir"],
            )
        except (HistoricalBatchPipelineError, OSError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))

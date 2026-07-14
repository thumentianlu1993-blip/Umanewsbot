from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_batch_pipeline import HistoricalBatchPipelineError
from stable.services.historical_batch_verifier import (
    verify_historical_batch_stage,
    write_verification_report,
)


class Command(BaseCommand):
    help = "在数据库只读事务中逐 target 验收历史赛事 date/detail-source/final 阶段。"

    def add_arguments(self, parser):
        parser.add_argument("--stage", required=True, choices=("date", "detail-source", "final"))
        parser.add_argument("--artifact-dir", required=True)
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            report = verify_historical_batch_stage(
                stage=options["stage"], artifact_dir=options["artifact_dir"]
            )
            write_verification_report(options["output"], report)
        except (HistoricalBatchPipelineError, OSError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if report["error_count"]:
            raise CommandError(
                f"historical batch stage verification failed: errors={report['error_count']}"
            )

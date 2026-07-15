from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_detail_chunk_import import (
    HistoricalRaceDetailChunkError,
    verify_historical_race_detail_chunk,
)


class Command(BaseCommand):
    help = "只读核验一份已完成的历史赛事详情 chunk。"

    def add_arguments(self, parser):
        parser.add_argument("--bundle-dir", required=True)
        parser.add_argument("--chunk-manifest", required=True)
        parser.add_argument("--approval", required=True)
        parser.add_argument("--expected-bundle-sha256", required=True)
        parser.add_argument("--expected-chunk-sha256", required=True)
        parser.add_argument("--expected-approval-sha256", required=True)
        parser.add_argument("--runner-run-id", required=True)

    def handle(self, *args, **options):
        try:
            report = verify_historical_race_detail_chunk(
                bundle_dir=options["bundle_dir"],
                chunk_manifest_path=options["chunk_manifest"],
                approval_path=options["approval"],
                expected_bundle_sha256=options["expected_bundle_sha256"],
                expected_chunk_sha256=options["expected_chunk_sha256"],
                expected_approval_sha256=options["expected_approval_sha256"],
                runner_run_id=options["runner_run_id"],
            )
        except HistoricalRaceDetailChunkError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if report["error_count"]:
            raise CommandError(f"historical detail chunk verification failed: {report['error_count']}")

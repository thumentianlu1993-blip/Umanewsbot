from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_race_detail_chunk_import import (
    HistoricalRaceDetailChunkError,
    import_historical_race_detail_chunk,
)


class Command(BaseCommand):
    help = "原子 dry-run 或导入一份已批准的历史赛事详情 chunk。"

    def add_arguments(self, parser):
        parser.add_argument("--bundle-dir", required=True)
        parser.add_argument("--chunk-manifest", required=True)
        parser.add_argument("--approval", required=True)
        parser.add_argument("--expected-bundle-sha256", required=True)
        parser.add_argument("--expected-chunk-sha256", required=True)
        parser.add_argument("--expected-approval-sha256", required=True)
        parser.add_argument("--runner-run-id", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            report = import_historical_race_detail_chunk(
                bundle_dir=options["bundle_dir"],
                chunk_manifest_path=options["chunk_manifest"],
                approval_path=options["approval"],
                expected_bundle_sha256=options["expected_bundle_sha256"],
                expected_chunk_sha256=options["expected_chunk_sha256"],
                expected_approval_sha256=options["expected_approval_sha256"],
                runner_run_id=options["runner_run_id"],
                dry_run=options["dry_run"],
            )
        except HistoricalRaceDetailChunkError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))

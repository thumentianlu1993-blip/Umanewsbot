from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.p0_horse_completion_batch import P0HorseBatchError
from stable.services.p0_horse_participant_release import (
    prepare_participant_release_bridge,
)


class Command(BaseCommand):
    help = (
        "把 participant completion 精确桥接为待模块审核的 P0 release draft；"
        "不访问网络或数据库"
    )

    def add_arguments(self, parser):
        parser.add_argument("--batch-index", required=True)
        parser.add_argument("--execution-ledger", required=True)
        parser.add_argument("--completion-manifest", required=True)
        parser.add_argument("--candidates", required=True)
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            result = prepare_participant_release_bridge(
                batch_index_path=options["batch_index"],
                execution_ledger_path=options["execution_ledger"],
                completion_manifest_path=options["completion_manifest"],
                candidates_path=options["candidates"],
                output_dir=options["output"],
            )
        except P0HorseBatchError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))

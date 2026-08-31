from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.racing_api_horse_staging import (
    RacingApiStagingError,
    apply_targeted_materialization,
    dry_run_targeted_materialization,
)


class Command(BaseCommand):
    help = (
        "校验 The Racing API targeted-horse materialization，并整批 dry-run "
        "或在单一事务中写入 External staging。"
    )

    def add_arguments(self, parser):
        parser.add_argument("--materialization-dir", type=Path, required=True)
        parser.add_argument("--approved-manifest-sha256", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--allow-write", action="store_true")

    def handle(self, *args, **options):
        if options["allow_write"] and not options["apply"]:
            raise CommandError("--allow-write 只能与 --apply 同时使用。")
        try:
            if options["apply"]:
                report = apply_targeted_materialization(
                    options["materialization_dir"],
                    approved_manifest_sha256=options[
                        "approved_manifest_sha256"
                    ],
                    allow_write=options["allow_write"],
                )
            else:
                report = dry_run_targeted_materialization(
                    options["materialization_dir"],
                    approved_manifest_sha256=options[
                        "approved_manifest_sha256"
                    ],
                )
        except RacingApiStagingError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        )

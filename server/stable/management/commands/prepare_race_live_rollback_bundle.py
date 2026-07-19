from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_events import prepare_race_live_rollback_bundle


class Command(BaseCommand):
    help = "为已公开 provisional event 只读生成 root-owned rollback bundle。"

    def add_arguments(self, parser):
        parser.add_argument("--event-id", type=int, required=True)
        parser.add_argument("--reviewed-release-image-id", required=True)
        parser.add_argument("--filtered-env-sha256", required=True)
        parser.add_argument("--approved-commit", required=True)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--output-root", required=True)

    def handle(self, *args, **options):
        try:
            result = prepare_race_live_rollback_bundle(
                event_id=options["event_id"],
                reviewed_release_image_id=options[
                    "reviewed_release_image_id"
                ],
                filtered_env_sha256=options["filtered_env_sha256"],
                approved_commit=options["approved_commit"],
                run_id=options["run_id"],
                output_root=options["output_root"],
            )
        except (OSError, TypeError, ValueError, PermissionError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

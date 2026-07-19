from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_live_publication_transition import (
    RaceLivePublicationTransitionError,
    prepare_race_live_publication_transition_bundle,
)


class Command(BaseCommand):
    help = "从单赛事 shadow 数据库快照安全生成 promotion/disable/restore bundle"

    def add_arguments(self, parser):
        parser.add_argument("--event-id", required=True, type=int)
        parser.add_argument("--approved-commit", required=True)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--output-root")

    def handle(self, *args, **options):
        try:
            result = prepare_race_live_publication_transition_bundle(
                event_id=options["event_id"],
                approved_commit=options["approved_commit"],
                run_id=options["run_id"],
                output_root=options["output_root"],
            )
        except (OSError, RaceLivePublicationTransitionError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

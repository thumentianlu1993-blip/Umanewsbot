from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stable.services.race_live_manual_official_evidence import (
    RaceLiveManualOfficialEvidenceError,
    prepare_race_live_manual_official_evidence,
)
from stable.services.race_live_publication_transition import (
    RaceLivePublicationTransitionError,
    _parse_json,
    _read_safe_file,
)


class Command(BaseCommand):
    help = "从人工录入的最小客观 JSON 离线生成 BHA manual evidence receipt"

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--output-root")

    def handle(self, *args, **options):
        try:
            _, data = _read_safe_file(options["input"])
            submission = _parse_json(data, "manual evidence input")
            result = prepare_race_live_manual_official_evidence(
                submission=submission,
                output_root=(
                    options["output_root"]
                    or settings.RACE_LIVE_PUBLICATION_ARTIFACT_ROOT
                ),
                run_id=options["run_id"],
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RaceLivePublicationTransitionError,
            RaceLiveManualOfficialEvidenceError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

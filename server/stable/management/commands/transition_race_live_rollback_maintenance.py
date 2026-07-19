from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_events import (
    load_race_live_rollback_manifest,
    transition_race_live_rollback_maintenance,
)


class Command(BaseCommand):
    help = "校验并以单事务 CAS 将四层 race-live policy 进入 maintenance-off。"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--expected-manifest-sha256", required=True)
        parser.add_argument("--expected-approved-commit", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm", default="")

    def handle(self, *args, **options):
        try:
            manifest = load_race_live_rollback_manifest(
                manifest_path=options["manifest"],
                expected_manifest_sha256=options[
                    "expected_manifest_sha256"
                ],
                expected_approved_commit=options[
                    "expected_approved_commit"
                ],
            )
            if options["apply"] and options["confirm"] != manifest[
                "maintenance_confirmation"
            ]:
                raise PermissionError("maintenance confirmation mismatch")
            result = transition_race_live_rollback_maintenance(
                manifest=manifest,
                expected_manifest_sha256=options[
                    "expected_manifest_sha256"
                ],
                expected_approved_commit=options[
                    "expected_approved_commit"
                ],
                apply=options["apply"],
            )
        except (OSError, TypeError, ValueError, PermissionError) as exc:
            raise CommandError(str(exc)) from exc
        if result.get("ok") is not True:
            raise CommandError(result.get("reason", "maintenance rejected"))
        self.stdout.write(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

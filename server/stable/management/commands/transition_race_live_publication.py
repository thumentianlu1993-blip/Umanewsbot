from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_live_publication_transition import (
    RaceLivePublicationTransitionError,
    apply_race_live_publication_transition,
    dry_run_race_live_publication_transition,
    load_race_live_publication_transition_manifest,
    verify_race_live_publication_transition,
)


class Command(BaseCommand):
    help = "按受审 manifest dry-run/apply/verify 单赛事准实时发布 transition"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--expected-manifest-sha256", required=True)
        parser.add_argument("--expected-approved-commit", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm-apply", action="store_true")
        parser.add_argument("--verify", action="store_true")

    def handle(self, *args, **options):
        if options["apply"] and options["verify"]:
            raise CommandError("--apply 与 --verify 不能组合使用")
        if options["confirm_apply"] and not options["apply"]:
            raise CommandError("--confirm-apply 只能与 --apply 组合使用")
        if options["apply"] and not options["confirm_apply"]:
            raise CommandError("--apply 必须显式同时传入 --confirm-apply")
        try:
            manifest = load_race_live_publication_transition_manifest(
                manifest_path=options["manifest"],
                expected_manifest_sha256=options[
                    "expected_manifest_sha256"
                ],
                expected_approved_commit=options[
                    "expected_approved_commit"
                ],
            )
            if options["apply"]:
                result = apply_race_live_publication_transition(manifest)
            elif options["verify"]:
                result = verify_race_live_publication_transition(manifest)
                if not result["ok"]:
                    raise RaceLivePublicationTransitionError(
                        "verify 失败：" + ";".join(result["errors"])
                    )
            else:
                result = dry_run_race_live_publication_transition(manifest)
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

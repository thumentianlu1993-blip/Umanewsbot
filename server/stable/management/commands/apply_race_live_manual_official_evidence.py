from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_live_manual_official_evidence import (
    RaceLiveManualOfficialEvidenceError,
    apply_race_live_manual_official_evidence,
    dry_run_race_live_manual_official_evidence,
    load_race_live_manual_official_evidence,
)
from stable.services.race_live_publication_transition import (
    RaceLivePublicationTransitionError,
    load_race_live_publication_transition_manifest,
)


class Command(BaseCommand):
    help = "dry-run/apply BHA manual official evidence receipt；不访问网络"

    def add_arguments(self, parser):
        parser.add_argument("--receipt", required=True)
        parser.add_argument("--expected-receipt-sha256", required=True)
        parser.add_argument("--expected-approved-commit", required=True)
        parser.add_argument("--disable-manifest")
        parser.add_argument("--expected-disable-manifest-sha256")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm-apply", action="store_true")

    def handle(self, *args, **options):
        if options["confirm_apply"] and not options["apply"]:
            raise CommandError("--confirm-apply 只能与 --apply 组合使用")
        if options["apply"] and not options["confirm_apply"]:
            raise CommandError("--apply 必须显式同时传入 --confirm-apply")
        if bool(options["disable_manifest"]) != bool(
            options["expected_disable_manifest_sha256"]
        ):
            raise CommandError(
                "--disable-manifest 与 --expected-disable-manifest-sha256 必须同时提供"
            )
        try:
            receipt = load_race_live_manual_official_evidence(
                receipt_path=options["receipt"],
                expected_receipt_sha256=options[
                    "expected_receipt_sha256"
                ],
                expected_approved_commit=options[
                    "expected_approved_commit"
                ],
            )
            disable_manifest = None
            if options["disable_manifest"]:
                disable_manifest = (
                    load_race_live_publication_transition_manifest(
                        manifest_path=options["disable_manifest"],
                        expected_manifest_sha256=options[
                            "expected_disable_manifest_sha256"
                        ],
                        expected_approved_commit=options[
                            "expected_approved_commit"
                        ],
                    )
                )
            if options["apply"]:
                result = apply_race_live_manual_official_evidence(
                    receipt=receipt,
                    receipt_sha256=options[
                        "expected_receipt_sha256"
                    ],
                    disable_manifest=disable_manifest,
                )
            else:
                result = dry_run_race_live_manual_official_evidence(
                    receipt=receipt,
                    receipt_sha256=options[
                        "expected_receipt_sha256"
                    ],
                    disable_manifest=disable_manifest,
                )
        except (
            OSError,
            RaceLiveManualOfficialEvidenceError,
            RaceLivePublicationTransitionError,
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

"""Verify, disarm, or atomically activate the reviewed canary cohort."""

from __future__ import annotations

import sys

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_event_lifecycle_canary import (
    CanaryError, load_canary_manifest_bytes, parse_canary_event_ids,
    read_bounded_manifest_stdin,
    verify_or_mutate_canary,
)


class Command(BaseCommand):
    help = "verify/activate/disarm lifecycle enforce canary"

    def add_arguments(self, parser):
        parser.add_argument("--manifest-stdin", action="store_true")
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--expected-commit", required=True)
        parser.add_argument("--expected-event-ids", required=True)
        parser.add_argument("--phase", choices=("inactive", "active"), required=True)
        parser.add_argument("--activate", action="store_true")
        parser.add_argument("--disarm", action="store_true")

    def handle(self, **options):
        if not options["manifest_stdin"]:
            raise CommandError("必须使用 --manifest-stdin")
        try:
            stream = getattr(sys.stdin, "buffer", sys.stdin)
            raw = read_bounded_manifest_stdin(stream)
            manifest = load_canary_manifest_bytes(
                raw,
                expected_raw_sha256=options["manifest_sha256"],
                expected_commit=options["expected_commit"],
            )
            expected_event_ids = parse_canary_event_ids(
                options["expected_event_ids"]
            )
            if manifest.event_ids != expected_event_ids:
                raise CanaryError("manifest event IDs 与独立授权范围不匹配")
            if options["activate"] and options["disarm"]:
                raise CanaryError("--activate 与 --disarm 不可同时使用")
            if options["activate"] and options["phase"] != "active":
                raise CanaryError("--activate 必须配合 --phase active")
            if options["disarm"] and options["phase"] != "inactive":
                raise CanaryError("--disarm 必须配合 --phase inactive")
            result = verify_or_mutate_canary(
                manifest,
                expected_state=options["phase"],
                activate=options["activate"],
                disarm=options["disarm"],
            )
        except CanaryError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"outcome={result.outcome} events={','.join(map(str, result.event_ids))} "
            f"activation_id={result.activation_id}"
        ))

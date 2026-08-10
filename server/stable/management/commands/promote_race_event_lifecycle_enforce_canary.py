"""Promote the exact canary controls while lifecycle is strictly false/off."""

from __future__ import annotations

import sys

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_event_lifecycle_canary import (
    CanaryError, load_canary_manifest_bytes, promote_canary,
    parse_canary_event_ids, read_bounded_manifest_stdin,
)


class Command(BaseCommand):
    help = "dry-run/apply lifecycle enforce canary promotion"

    def add_arguments(self, parser):
        parser.add_argument("--manifest-stdin", action="store_true")
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--expected-commit", required=True)
        parser.add_argument("--expected-event-ids", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm-enforce-canary", action="store_true")

    def handle(self, **options):
        if not options["manifest_stdin"]:
            raise CommandError("必须使用 --manifest-stdin")
        if options["apply"] and not options["confirm_enforce_canary"]:
            raise CommandError("--apply 必须同时提供 --confirm-enforce-canary")
        try:
            stream = getattr(sys.stdin, "buffer", sys.stdin)
            raw = read_bounded_manifest_stdin(stream)
            manifest = load_canary_manifest_bytes(
                raw,
                expected_raw_sha256=options["manifest_sha256"],
                expected_commit=options["expected_commit"],
                require_apply_fresh=options["apply"],
            )
            expected_event_ids = parse_canary_event_ids(
                options["expected_event_ids"]
            )
            if manifest.event_ids != expected_event_ids:
                raise CanaryError("manifest event IDs 与独立授权范围不匹配")
            result = promote_canary(manifest, apply=options["apply"])
        except CanaryError as exc:
            raise CommandError(str(exc)) from exc
        label = "APPLY" if options["apply"] else "DRY-RUN"
        self.stdout.write(self.style.SUCCESS(
            f"[{label}] outcome={result.outcome} events={','.join(map(str, result.event_ids))}"
        ))

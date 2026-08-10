"""Read-only preparation of a strict two-event lifecycle enforce canary."""

from __future__ import annotations

import hashlib
import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_event_lifecycle_canary import CanaryError, build_canary_artifact
from stable.services.race_event_lifecycle_enrollment import _canonical_bytes, write_enrollment_artifacts


class Command(BaseCommand):
    help = "只读生成两场 lifecycle enforce canary manifest"

    def add_arguments(self, parser):
        parser.add_argument("--event-ids", nargs="+", required=True)
        parser.add_argument("--approved-commit", required=True)
        parser.add_argument("--output-dir", required=True)

    def handle(self, **options):
        try:
            event_ids = [int(item) for item in options["event_ids"]]
            manifest = build_canary_artifact(
                event_ids=event_ids,
                approved_commit=options["approved_commit"],
            )
            data = json.loads(manifest)
            summary = _canonical_bytes({
                "schema_version": 1,
                "event_count": 2,
                "event_ids": event_ids,
                "approved_commit": data["approved_commit"],
                "apply_expires_at": data["apply_expires_at"],
                "runtime_valid_until": data["runtime_valid_until"],
                "manifest_content_sha256": data["content_sha256"],
                "manifest_raw_sha256": hashlib.sha256(manifest).hexdigest(),
            })
            write_enrollment_artifacts(
                options["output_dir"], manifest_bytes=manifest, summary_bytes=summary
            )
        except (CanaryError, OSError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"已生成 lifecycle enforce canary artifact：events={','.join(map(str, event_ids))}"
        ))

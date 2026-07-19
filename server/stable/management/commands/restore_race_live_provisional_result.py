from __future__ import annotations

import json
import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services.race_events import restore_last_provisional_result


class Command(BaseCommand):
    help = "按冻结 manifest 原子恢复最后已发布的 provisional 投影。"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--expected-manifest-sha256", required=True)

    def handle(self, *args, **options):
        try:
            manifest_bytes = Path(options["manifest"]).read_bytes()
            if (
                hashlib.sha256(manifest_bytes).hexdigest()
                != options["expected_manifest_sha256"]
            ):
                raise ValueError("manifest SHA-256 漂移")
            payload = json.loads(manifest_bytes)
            decision = restore_last_provisional_result(
                event_id=payload["event_id"],
                expected_current_revision_id=payload[
                    "expected_current_revision_id"
                ],
                expected_provisional_revision_id=payload[
                    "expected_provisional_revision_id"
                ],
                planned_policy_snapshot=payload[
                    "planned_policy_snapshot"
                ],
                expected_allowlist_version=payload[
                    "expected_allowlist_version"
                ],
                expected_publication_id=payload[
                    "expected_publication_id"
                ],
                expected_tracking_lock_version=payload[
                    "expected_tracking_lock_version"
                ],
                expected_manifest_sha256=options[
                    "expected_manifest_sha256"
                ],
                now=timezone.now(),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError("rollback manifest 不合法") from exc
        if decision.allowed is not True:
            raise CommandError(decision.reason)
        self.stdout.write(
            self.style.SUCCESS(
                f"restored revision_id={decision.revision_id}"
            )
        )

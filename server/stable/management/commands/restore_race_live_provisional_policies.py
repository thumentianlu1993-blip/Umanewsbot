from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services.race_events import (
    restore_race_live_provisional_policies,
)


class Command(BaseCommand):
    help = "按冻结 manifest 分阶段 CAS 恢复 provisional publication policies。"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--expected-manifest-sha256", required=True)
        parser.add_argument(
            "--phase",
            choices=("coarse", "event"),
            required=True,
        )

    def handle(self, *args, **options):
        try:
            manifest_bytes = Path(options["manifest"]).read_bytes()
            if (
                hashlib.sha256(manifest_bytes).hexdigest()
                != options["expected_manifest_sha256"]
            ):
                raise ValueError("manifest SHA-256 漂移")
            payload = json.loads(manifest_bytes)
            if (
                "schema_version" in payload
                and "expected_current_revision_id" not in payload
            ):
                raise ValueError(
                    "generated manifest 缺少 current revision"
                )
            decision = restore_race_live_provisional_policies(
                event_id=payload["event_id"],
                planned_policy_snapshot=payload[
                    "planned_policy_snapshot"
                ],
                phase=options["phase"],
                expected_provisional_revision_id=payload[
                    "expected_provisional_revision_id"
                ],
                expected_allowlist_version=payload[
                    "expected_allowlist_version"
                ],
                expected_publication_id=payload[
                    "expected_publication_id"
                ],
                expected_manifest_sha256=options[
                    "expected_manifest_sha256"
                ],
                now=timezone.now(),
                expected_tracking_lock_version=payload.get(
                    "expected_tracking_lock_version"
                ),
                expected_current_revision_id=payload.get(
                    "expected_current_revision_id"
                ),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError("rollback manifest 不合法") from exc
        if decision.allowed is not True:
            raise CommandError(decision.reason)
        self.stdout.write(
            self.style.SUCCESS(
                f"{decision.reason} event_id={payload['event_id']}"
            )
        )

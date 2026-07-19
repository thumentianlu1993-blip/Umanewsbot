from __future__ import annotations

import json
import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from stable.services.race_events import (
    validate_race_live_provisional_rollback_target,
)


class Command(BaseCommand):
    help = "只读验证准实时 provisional 回滚目标。"

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
            event_id = payload["event_id"]
            provisional_revision_id = payload[
                "expected_provisional_revision_id"
            ]
            if (
                "schema_version" in payload
                and "expected_current_revision_id" not in payload
            ):
                raise ValueError(
                    "generated manifest 缺少 current revision"
                )
            current_revision_id = payload.get(
                "expected_current_revision_id"
            )
            planned_policy_snapshot = payload["planned_policy_snapshot"]
            expected_allowlist_version = payload[
                "expected_allowlist_version"
            ]
            expected_publication_id = payload["expected_publication_id"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError("rollback manifest 不合法") from exc
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL TRANSACTION READ ONLY")
            decision = validate_race_live_provisional_rollback_target(
                event_id=event_id,
                now=timezone.now(),
                expected_provisional_revision_id=provisional_revision_id,
                planned_policy_snapshot=planned_policy_snapshot,
                expected_allowlist_version=expected_allowlist_version,
                expected_publication_id=expected_publication_id,
                expected_tracking_lock_version=payload.get(
                    "expected_tracking_lock_version"
                ),
                expected_current_revision_id=current_revision_id,
            )
            if decision.allowed is not True:
                raise CommandError(decision.reason)
        self.stdout.write(
            self.style.SUCCESS(
                f"valid revision_id={decision.revision_id}"
            )
        )

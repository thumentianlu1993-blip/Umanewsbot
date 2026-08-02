from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_result_recovery_projection import (
    RecoveryLedgerError,
    verify_recovery_ledger,
)


class Command(BaseCommand):
    help = "Verify immutable per-event race-result recovery ledgers."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--ledger-root", required=True)

    def handle(self, *args, **options):
        manifest_path = Path(options["manifest"])
        try:
            content = manifest_path.read_bytes()
        except OSError as exc:
            raise CommandError(f"manifest unreadable: {exc}") from exc
        if hashlib.sha256(content).hexdigest() != options["manifest_sha256"]:
            raise CommandError("manifest sha256 mismatch")
        try:
            manifest = json.loads(content)
        except ValueError as exc:
            raise CommandError("manifest is not valid JSON") from exc
        event_ids = [item.get("event_id") for item in manifest.get("events", [])]
        if not event_ids or len(event_ids) != len(set(event_ids)):
            raise CommandError("manifest event scope is empty or duplicated")

        root = Path(options["ledger_root"])
        reports = []
        for event_id in event_ids:
            matches = sorted(
                root.glob(
                    f"event-{event_id}-{options['manifest_sha256']}-*.json"
                )
            )
            if len(matches) != 1:
                raise CommandError(
                    f"event {event_id} must have exactly one apply ledger"
                )
            try:
                report = verify_recovery_ledger(matches[0])
            except RecoveryLedgerError as exc:
                raise CommandError(
                    f"event {event_id} ledger invalid: {exc.reason_code}"
                ) from exc
            reports.append(report)
        ok = all(item["status"] == "applied" for item in reports)
        summary = {
            "ok": ok,
            "manifest_sha256": options["manifest_sha256"],
            "event_count": len(event_ids),
            "events": reports,
        }
        self.stdout.write(
            json.dumps(summary, ensure_ascii=False, sort_keys=True)
        )
        if not ok:
            raise CommandError("recovery verification failed")

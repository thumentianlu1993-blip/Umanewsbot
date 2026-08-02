"""Historical backfill of ArticleRaceLink via the existing auto-association.

Default dry-run mode: for each event in scope, run the real
``associate_articles_for_event`` matching inside a transaction that is
rolled back, and emit a deterministic manifest of what WOULD be written.

  python manage.py backfill_article_race_links --dry-run

Apply mode (requires the dry-run manifest SHA-256):

  python manage.py backfill_article_race_links --apply --expected-sha256 <sha>

Apply first re-runs the full dry-run pass and verifies the manifest digest
BEFORE anything is written; a scope-data drift aborts the batch with zero
writes.  Each event's writes are committed in their own transaction.

Scope filters select events by local_date window (relative to today),
region, or a single event id.  The command only creates/updates
ArticleRaceLink rows through the reviewed ``associate_articles_for_event``
service; it never touches articles, events, exposures, or deliveries.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from stable.models import RaceEvent
from stable.services.operations import log_operation
from stable.services.race_events import associate_articles_for_event

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill ArticleRaceLink via auto-association (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", default=True)
        parser.add_argument("--apply", action="store_true", default=False)
        parser.add_argument(
            "--expected-sha256",
            type=str,
            default="",
            help="Expected SHA-256 of the dry-run manifest. Required with --apply.",
        )
        parser.add_argument("--days-back", type=int, default=120)
        parser.add_argument("--days-forward", type=int, default=60)
        parser.add_argument("--region", type=str, default="")
        parser.add_argument("--event-id", type=int, default=0)
        parser.add_argument("--date-window-days", type=int, default=14)
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit the number of events processed (0 = unlimited).",
        )

    def handle(self, *args, **options):
        apply_mode = options.get("apply", False)
        expected_sha256 = options.get("expected_sha256", "")
        stdout = options.get("stdout") or self.stdout
        date_window_days = options.get("date_window_days", 14)

        events = list(self._scope_events(options))

        # Pass 1: always a rolled-back dry-run to build the manifest digest.
        results, totals = self._run_pass(events, date_window_days=date_window_days, write=False)
        manifest = {
            "scope": {
                "days_back": options.get("days_back", 120),
                "days_forward": options.get("days_forward", 60),
                "region": options.get("region", ""),
                "event_id": options.get("event_id", 0),
                "date_window_days": date_window_days,
                "limit": options.get("limit", 0),
            },
            "events_processed": len(results),
            "totals": totals,
            "results": results,
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

        if apply_mode:
            if not expected_sha256:
                raise CommandError("--expected-sha256 is required with --apply")
            if manifest_sha256 != expected_sha256:
                raise CommandError(
                    f"Manifest SHA-256 mismatch: expected {expected_sha256}, got {manifest_sha256}. "
                    "The scope data drifted since the dry-run. Re-run --dry-run and review. "
                    "Nothing was written."
                )
            # Pass 2: real writes (only after the digest verified).
            results, totals = self._run_pass(events, date_window_days=date_window_days, write=True)
            log_operation(
                action_type="backfill_article_race_links",
                target_type="article_race_link",
                target_id=f"batch:{manifest_sha256[:16]}",
                detail=(
                    f"Backfill applied: {len(results)} events, "
                    f"created={totals['created']} updated={totals['updated']} "
                    f"sha256={manifest_sha256}"
                ),
            )

        output = {
            "mode": "apply" if apply_mode else "dry_run",
            "manifest_sha256": manifest_sha256,
            "events_processed": len(results),
            "totals": totals,
            "results": results,
        }
        stdout.write(json.dumps(output, ensure_ascii=False, indent=2))
        stdout.write(
            f"\n{'Apply' if apply_mode else 'Dry-run'} complete: "
            f"{len(results)} events, created={totals['created']}, "
            f"updated={totals['updated']}. SHA-256: {manifest_sha256}"
        )

    @staticmethod
    def _run_pass(events, *, date_window_days: int, write: bool):
        """Run association for every event; each event is one transaction.

        With ``write=False`` the transaction is rolled back after matching,
        so the pass produces accurate counts without persisting anything.
        """
        results: list[dict[str, Any]] = []
        totals = {"created": 0, "updated": 0, "skipped_removed": 0, "skipped_manual": 0}
        for event in events:
            with transaction.atomic():
                result = associate_articles_for_event(
                    event, date_window_days=date_window_days,
                )
                if not write:
                    transaction.set_rollback(True)
            entry = {
                "event_id": event.pk,
                "event": f"{event.year} {event.chinese_name}",
                "created": result["created"],
                "updated": result["updated"],
                "skipped_removed": result.get("skipped_removed", 0),
                "skipped_manual": result.get("skipped_manual", 0),
            }
            results.append(entry)
            for key in totals:
                totals[key] += entry[key]
        return results, totals

    @staticmethod
    def _scope_events(options):
        event_id = options.get("event_id", 0)
        queryset = RaceEvent.objects.all().order_by("local_date", "id")
        if event_id:
            queryset = queryset.filter(pk=event_id)
        else:
            today = timezone.localdate()
            start = today - timedelta(days=options.get("days_back", 120))
            end = today + timedelta(days=options.get("days_forward", 60))
            queryset = queryset.filter(local_date__gte=start, local_date__lte=end)
        region = (options.get("region") or "").strip()
        if region:
            queryset = queryset.filter(country_region=region)
        limit = options.get("limit", 0)
        if limit > 0:
            queryset = queryset[:limit]
        return queryset

"""
Historical backfill command for RaceNewsExposure.

Default dry-run mode: scans publicly-visible articles with race links and
outputs a deterministic manifest.

  python manage.py backfill_race_exposure --dry-run

Apply mode (requires a validated manifest):

  python manage.py backfill_race_exposure --apply --manifest '<json-list>'

This command does NOT modify article body, published_to_web_at, QQ deliveries,
or duplicate_of relationships.
"""

from __future__ import annotations

import hashlib
import json
import logging
from io import StringIO
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from stable.models import (
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    NewsArticle,
    RaceEvent,
    RaceNewsAngle,
    RaceNewsExposure,
    RaceNewsExposureChannel,
    RaceNewsExposureStatus,
)
from stable.services.operations import log_operation

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Historical backfill of RaceNewsExposure records (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", default=True)
        parser.add_argument("--apply", action="store_true", default=False)
        parser.add_argument("--manifest", type=str, default="")
        parser.add_argument(
            "--expected-sha256",
            type=str,
            default="",
            help="Expected SHA-256 of the manifest. Required with --apply.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit the number of articles scanned (0 = unlimited).",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", True)
        apply_mode = options.get("apply", False)
        manifest_value = options.get("manifest", "")
        expected_sha256 = options.get("expected_sha256", "")
        limit = options.get("limit", 0)
        stdout = options.get("stdout") or self.stdout
        stderr = options.get("stderr") or self.stderr

        # Accept manifest as either a JSON string or a Python list (from test)
        if isinstance(manifest_value, str) and manifest_value.strip():
            try:
                manifest = json.loads(manifest_value)
            except (json.JSONDecodeError, TypeError) as e:
                raise CommandError(f"Invalid manifest JSON: {e}")
        elif isinstance(manifest_value, list):
            manifest = manifest_value
        else:
            manifest = []

        # Only enter apply path when --apply is explicitly passed AND a manifest is provided
        if apply_mode and manifest:
            if not expected_sha256:
                raise CommandError("--expected-sha256 is required with --apply")
            self._apply(manifest, expected_sha256=expected_sha256, stdout=stdout, stderr=stderr)
            return

        if manifest and not apply_mode:
            stdout.write(
                "WARNING: --manifest provided without --apply. "
                "Running dry-run instead. Pass --apply to apply the manifest.\n"
            )

        self._dry_run(limit=limit, stdout=stdout)

    # ------------------------------------------------------------------
    # Dry-run
    # ------------------------------------------------------------------

    def _dry_run(self, *, limit: int = 0, stdout=None):
        """Scan all public articles with a manual or auto race link and output
        a deterministic manifest of suggested exposures.

        Low-confidence auto links are included in the scan but dropped by
        ``_resolve_identity`` (confidence threshold), so the manifest only
        contains entries whose identity actually resolves.
        """
        stdout = stdout or self.stdout
        articles = NewsArticle.objects.filter(
            workflow_status="published",
            published_to_web_at__isnull=False,
            race_links__status__in=[
                ArticleRaceLinkStatus.MANUAL,
                ArticleRaceLinkStatus.AUTO,
            ],
        ).distinct().order_by("id")

        if limit > 0:
            articles = articles[:limit]

        manifest: list[dict[str, Any]] = []
        seen: set[tuple[int, int]] = set()  # (article_id, event_id) uniqueness

        for article in articles:
            try:
                identity = self._resolve_identity(article)
            except Exception:
                continue
            if identity is None:
                continue

            event_id = identity["event_id"]
            key = (article.id, event_id)
            if key in seen:
                continue
            seen.add(key)

            # Suggest slot 1 for comprehensive_result angle
            suggested_angle = "comprehensive_result"
            suggested_slot = 1
            suggested_reason = "historical_backfill"

            manifest.append({
                "article_id": article.id,
                "event_id": event_id,
                "slot": suggested_slot,
                "angle": suggested_angle,
                "reason": suggested_reason,
                "channel": "homepage",
                "scope_key": "site",
            })

        # Compute manifest digest
        manifest_bytes = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

        output = {
            "manifest_sha256": manifest_sha256,
            "entry_count": len(manifest),
            "manifest": manifest,
        }

        stdout.write(json.dumps(output, ensure_ascii=False, indent=2))
        stdout.write(
            f"\nDry-run complete: {len(manifest)} entries. "
            f"Manifest SHA-256: {manifest_sha256}"
        )

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _apply(self, manifest, expected_sha256="", stdout=None, stderr=None):
        """Apply a previously-generated manifest.

        Validates uniqueness, manifest SHA-256 consistency against
        *expected_sha256*, identity drift (FATAL — batch rejected),
        then wraps the entire apply in a single transaction.
        Writes an OperationLog on success.
        """
        stdout = stdout or self.stdout
        stderr = stderr or self.stderr
        if isinstance(manifest, str):
            try:
                manifest = json.loads(manifest)
            except (json.JSONDecodeError, TypeError) as e:
                raise CommandError(f"Invalid manifest JSON: {e}")

        if not isinstance(manifest, list):
            raise CommandError("Manifest must be a list")

        # --- Pre-flight: duplicate check ---
        seen_keys: set[tuple[int, int]] = set()
        for entry in manifest:
            key = (entry["article_id"], entry["event_id"])
            if key in seen_keys:
                msg = (
                    f"Rejecting manifest: duplicate entry for "
                    f"article_id={entry['article_id']} event_id={entry['event_id']}"
                )
                stderr.write(msg + "\n")
                raise CommandError(msg)
            seen_keys.add(key)

        # --- Pre-flight: SHA-256 consistency ---
        manifest_bytes = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
        actual_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        if expected_sha256 and actual_sha256 != expected_sha256:
            raise CommandError(
                f"Manifest SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}. "
                "The manifest has been modified or tampered with. Rejecting entire batch."
            )
        stdout.write(f"Manifest SHA-256: {actual_sha256}\n")

        # --- Pre-flight: identity drift (fatal — entire batch) ---
        drift_entries: list[dict] = []
        for entry in manifest:
            article_id = entry["article_id"]
            event_id = entry["event_id"]
            try:
                article = NewsArticle.objects.get(pk=article_id)
            except NewsArticle.DoesNotExist:
                drift_entries.append({"article_id": article_id, "reason": "article_not_found"})
                continue
            identity = self._resolve_identity(article)
            if identity is None or identity["event_id"] != event_id:
                drift_entries.append({
                    "article_id": article_id,
                    "expected_event_id": event_id,
                    "actual_identity": identity,
                })

        if drift_entries:
            for de in drift_entries:
                stdout.write(
                    f"FATAL: identity drift for article {de['article_id']}: "
                    f"{de.get('reason', de.get('actual_identity'))}\n"
                )
            raise CommandError(
                f"Identity drift detected for {len(drift_entries)} entries. "
                "Entire batch rejected. Fix and retry."
            )

        # --- Apply: single atomic batch ---
        written = 0
        skipped = 0

        try:
            with transaction.atomic():
                if isinstance(manifest, str):
                    manifest = json.loads(manifest)
                for entry in manifest:
                    article_id = entry["article_id"]
                    event_id = entry["event_id"]
                    slot = entry.get("slot", 1)
                    angle = entry.get("angle", "other")
                    channel = entry.get("channel", "homepage")
                    scope_key = entry.get("scope_key", "site")
                    reason = entry.get("reason", "historical_backfill")

                    article = NewsArticle.objects.get(pk=article_id)
                    event = RaceEvent.objects.get(pk=event_id)

                    # get_or_create handles uniqueness at the DB level.
                    # If an IntegrityError occurs (e.g. constraint violation
                    # from a different event/channel/scope/article combo),
                    # let it propagate — do NOT swallow. The outer
                    # transaction.atomic() will roll back the entire batch.
                    _, created = RaceNewsExposure.objects.get_or_create(
                        event=event,
                        article=article,
                        channel=channel,
                        scope_key=scope_key,
                        slot=slot,
                        defaults={
                            "status": RaceNewsExposureStatus.ACTIVE,
                            "angle": angle,
                            "policy_version": "backfill-v1",
                            "reason": reason,
                            "activated_at": timezone.now(),
                        },
                    )
                    if created:
                        written += 1
                    else:
                        skipped += 1
        except Exception:
            # If anything inside the atomic block raises, the whole batch rolls back
            raise

        log_operation(
            action_type="backfill_race_exposure",
            target_type="race_news_exposure",
            target_id=f"batch:{actual_sha256[:16]}",
            detail=(
                f"Backfill applied: {written} written, {skipped} skipped, "
                f"manifest_sha256={actual_sha256}"
            ),
        )

        stdout.write(
            f"Apply complete: {written} written, {skipped} skipped.\n"
        )

    # ------------------------------------------------------------------
    # Identity resolution (simplified version)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_identity(article: NewsArticle) -> dict | None:
        """Identity resolution shared with the runtime exposure service.

        Delegates to ``race_news_exposure.resolve_race_identity`` so that
        AUTO links get the same confidence threshold AND the same
        year/region context validation (``_validate_identity_context``) as
        the live path — the backfill must not accept identities the runtime
        resolver would reject.
        """
        from stable.services.race_news_exposure import resolve_race_identity
        return resolve_race_identity(article)

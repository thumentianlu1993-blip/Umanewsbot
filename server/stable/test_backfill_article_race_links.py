"""Tests for the backfill_article_race_links management command."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from io import StringIO

from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from stable.models import (
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    NewsArticle,
    RaceEvent,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    WorkflowStatus,
)


def _event(**kwargs) -> RaceEvent:
    today = timezone.localdate()
    defaults = {
        "year": 2026,
        "slug": "goodwood-cup",
        "original_name": "Goodwood Cup",
        "chinese_name": "古活杯",
        "country_region": RacingRegion.UNITED_KINGDOM,
        "racecourse": "Goodwood",
        "grade_text": "G1",
        "surface": "turf",
        "local_date": today,
    }
    defaults.update(kwargs)
    return RaceEvent.objects.create(**defaults)


def _article(title: str, **kwargs) -> NewsArticle:
    now = timezone.now()
    defaults = {
        "source_site": SourceSite.SPORTING_LIFE,
        "source_mode": SourceMode.LATEST,
        "racing_region": RacingRegion.UNITED_KINGDOM,
        "source_language": SourceLanguage.ENGLISH,
        "source_article_id": f"bf-{title}",
        "title_ja": title,
        "translated_title_zh": title,
        "title_zh": title,
        "body_ja_raw": f"{title} body",
        "body_ja_normalized": f"{title} body",
        "published_at": now,
        "published_to_web_at": now,
        "workflow_status": WorkflowStatus.PUBLISHED,
        "score_total": 80,
    }
    defaults.update(kwargs)
    return NewsArticle.objects.create(**defaults)


class BackfillArticleRaceLinksTests(TestCase):
    def _run(self, **options):
        from stable.management.commands.backfill_article_race_links import Command

        out = StringIO()
        cmd = Command()
        cmd.handle(stdout=out, **options)
        # Output is pretty-printed JSON followed by a single summary line.
        return json.loads(out.getvalue().rsplit("\n", 1)[0])

    def test_dry_run_writes_nothing(self):
        event = _event()
        _article("Goodwood Cup result: Scandinavia wins")
        output = self._run(dry_run=True, apply=False, expected_sha256="",
                           days_back=120, days_forward=60, region="",
                           event_id=0, date_window_days=14, limit=0)
        self.assertEqual(output["mode"], "dry_run")
        self.assertEqual(output["totals"]["created"], 1)
        self.assertEqual(ArticleRaceLink.objects.count(), 0, "dry-run must not write")

    def test_apply_requires_expected_sha(self):
        _event()
        _article("Goodwood Cup result: Scandinavia wins")
        from stable.management.commands.backfill_article_race_links import Command
        with self.assertRaises(CommandError):
            Command().handle(stdout=StringIO(), dry_run=False, apply=True, expected_sha256="",
                             days_back=120, days_forward=60, region="",
                             event_id=0, date_window_days=14, limit=0)

    def test_apply_writes_links_and_is_verified(self):
        event = _event()
        article = _article("Goodwood Cup result: Scandinavia wins")
        dry = self._run(dry_run=True, apply=False, expected_sha256="",
                        days_back=120, days_forward=60, region="",
                        event_id=0, date_window_days=14, limit=0)
        applied = self._run(dry_run=False, apply=True, expected_sha256=dry["manifest_sha256"],
                            days_back=120, days_forward=60, region="",
                            event_id=0, date_window_days=14, limit=0)
        self.assertEqual(applied["mode"], "apply")
        link = ArticleRaceLink.objects.get(event=event, article=article)
        self.assertEqual(link.status, ArticleRaceLinkStatus.AUTO)
        self.assertGreaterEqual(link.confidence, 70)

    def test_apply_rejects_drift_before_writing(self):
        _event()
        _article("Goodwood Cup result: Scandinavia wins")
        dry = self._run(dry_run=True, apply=False, expected_sha256="",
                        days_back=120, days_forward=60, region="",
                        event_id=0, date_window_days=14, limit=0)
        # Drift: new matching article appears after the dry-run
        _article("Goodwood Cup preview: Trawlerman", source_article_id="bf-drift")
        from stable.management.commands.backfill_article_race_links import Command
        with self.assertRaises(CommandError):
            Command().handle(stdout=StringIO(), dry_run=False, apply=True,
                             expected_sha256=dry["manifest_sha256"],
                             days_back=120, days_forward=60, region="",
                             event_id=0, date_window_days=14, limit=0)
        self.assertEqual(ArticleRaceLink.objects.count(), 0, "drifted apply must not write")

    def test_event_id_scope(self):
        event = _event()
        other = _event(slug="king-george", chinese_name="英皇锦标",
                       original_name="King George VI And Queen Elizabeth Stakes")
        _article("Goodwood Cup result")
        _article("英皇锦标赛果")
        output = self._run(dry_run=True, apply=False, expected_sha256="",
                           days_back=120, days_forward=60, region="",
                           event_id=event.pk, date_window_days=14, limit=0)
        self.assertEqual(output["events_processed"], 1)
        self.assertEqual(output["results"][0]["event_id"], event.pk)

import json
import tempfile
import time
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from stable.models import (
    AutomationStatus,
    NewsArticle,
    NotificationLog,
    NotificationType,
    ProductionWindow,
    ProductionWindowKind,
    ProductionWindowMode,
    RacingRegion,
    ReviewMode,
    RiskLevel,
    SourceLanguage,
    SourceMode,
    SourceSite,
    WindowCandidateDecision,
    WorkflowStatus,
)
from stable.services.automation import mark_publish_ready
from stable.services.publishing_windows import (
    build_candidate_pool,
    publish_ready_age_payload,
    select_publish_candidates,
)
from stable.services.publish_readiness import publish_ready_age_summary
from stable.services.publish_ready_backlog import (
    apply_publish_ready_backlog_manifest,
    build_publish_ready_backlog_manifest,
    seal_publish_ready_backlog_review,
)
from stable.services.validation import ValidationOutcome, apply_validation_outcome


class PublishReadyTransitionTests(TestCase):
    def _article(self, **overrides) -> NewsArticle:
        now = timezone.now()
        payload = {
            "source_site": SourceSite.TDN,
            "source_mode": SourceMode.LATEST,
            "source_language": SourceLanguage.ENGLISH,
            "source_article_id": f"ready-{NewsArticle.objects.count()}",
            "title_ja": "Ready article",
            "body_ja_raw": "Body",
            "published_at": now,
            "source_url": f"https://example.com/{NewsArticle.objects.count()}",
        }
        payload.update(overrides)
        return NewsArticle.objects.create(**payload)

    def test_non_ready_transition_sets_publish_ready_at(self):
        article = self._article()
        ready_at = timezone.now() - timedelta(minutes=5)

        mark_publish_ready(article, ready_at=ready_at)

        article.refresh_from_db()
        self.assertEqual(article.automation_status, AutomationStatus.PUBLISH_READY)
        self.assertEqual(article.review_mode, ReviewMode.AUTO)
        self.assertEqual(article.risk_level, RiskLevel.LOW)
        self.assertEqual(article.publish_ready_at, ready_at)

    def test_repeated_mark_does_not_refresh_existing_timestamp(self):
        original = timezone.now() - timedelta(hours=2)
        article = self._article(
            automation_status=AutomationStatus.PUBLISH_READY,
            publish_ready_at=original,
        )

        mark_publish_ready(article, ready_at=timezone.now())

        article.refresh_from_db()
        self.assertEqual(article.publish_ready_at, original)

    def test_repeated_validation_does_not_backfill_legacy_null_timestamp(self):
        article = self._article(
            automation_status=AutomationStatus.PUBLISH_READY,
            publish_ready_at=None,
        )
        outcome = ValidationOutcome(True, "passed", {}, [])

        apply_validation_outcome(article, outcome)

        article.refresh_from_db()
        self.assertIsNone(article.publish_ready_at)

    def test_explicit_reviewed_refresh_updates_timestamp(self):
        original = timezone.now() - timedelta(days=4)
        refreshed = timezone.now()
        article = self._article(
            automation_status=AutomationStatus.PUBLISH_READY,
            publish_ready_at=original,
        )
        outcome = ValidationOutcome(True, "reviewed", {}, [])

        apply_validation_outcome(
            article,
            outcome,
            ready_at=refreshed,
            refresh_ready_at=True,
        )

        article.refresh_from_db()
        self.assertEqual(article.publish_ready_at, refreshed)


class PublishCandidateLaneTests(TestCase):
    def _article(self, *, now, **overrides) -> NewsArticle:
        sequence = NewsArticle.objects.count()
        payload = {
            "source_site": SourceSite.HKJC_NEWS,
            "source_mode": SourceMode.LATEST,
            "source_language": SourceLanguage.ENGLISH,
            "source_article_id": f"lane-{sequence}",
            "racing_region": RacingRegion.HONG_KONG,
            "title_ja": f"Lane article {sequence}",
            "body_ja_raw": "Body " * 30,
            "title_zh": f"候选 {sequence}",
            "summary_zh": f"摘要 {sequence}",
            "body_zh": "正文。" * 30,
            "published_at": now - timedelta(hours=8),
            "first_seen_at": now - timedelta(hours=8),
            "source_url": f"https://example.com/lane-{sequence}",
            "workflow_status": WorkflowStatus.PENDING_EDIT,
            "review_mode": ReviewMode.AUTO,
            "automation_status": AutomationStatus.PUBLISH_READY,
            "publish_ready_at": now - timedelta(hours=1),
            "score_total": 85,
            "quality_score": 80,
        }
        payload.update(overrides)
        return NewsArticle.objects.create(**payload)

    def _window(self, *, now) -> ProductionWindow:
        return ProductionWindow.objects.create(
            kind=ProductionWindowKind.PUBLISH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            scope_key=f"region:hong_kong:{ProductionWindow.objects.count()}",
            window_start=now - timedelta(minutes=15),
            window_end=now,
        )

    def _settings(self, **overrides):
        values = {
            "MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS": [RacingRegion.HONG_KONG],
            "MULTIREGION_PUBLISH_BACKLOG_ENABLED": True,
            "MULTIREGION_PUBLISH_BACKLOG_ALLOWED_REGIONS": [RacingRegion.HONG_KONG],
            "MULTIREGION_PUBLISH_BACKLOG_AUTO_HOURS": 24,
            "MULTIREGION_PUBLISH_BACKLOG_REVIEW_HOURS": 72,
            "MULTIREGION_PUBLISH_REALTIME_SCAN_LIMIT": 200,
            "MULTIREGION_PUBLISH_BACKLOG_SCAN_LIMIT": 200,
            "MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY": 60,
        }
        values.update(overrides)
        return self.settings(**values)

    def test_old_first_seen_recent_ready_enters_backlog_lane(self):
        now = timezone.now()
        article = self._article(now=now)
        with self._settings():
            result = select_publish_candidates(RacingRegion.HONG_KONG, window=self._window(now=now), now=now)

        self.assertEqual(result.selected, [article])
        decision = WindowCandidateDecision.objects.get(article=article)
        self.assertEqual(decision.payload["candidate_channels"], ["backlog"])
        self.assertEqual(decision.payload["publish_ready_age_tier"], "auto")

    def test_backlog_switch_off_preserves_old_realtime_behavior(self):
        now = timezone.now()
        self._article(now=now)
        with self._settings(MULTIREGION_PUBLISH_BACKLOG_ENABLED=False):
            result = select_publish_candidates(RacingRegion.HONG_KONG, window=self._window(now=now), now=now)

        self.assertEqual(result.selected, [])
        self.assertEqual(result.pool["backlog_loaded"], 0)

    def test_same_article_in_both_lanes_is_evaluated_once(self):
        now = timezone.now()
        article = self._article(now=now, first_seen_at=now - timedelta(minutes=30))
        with self._settings():
            result = select_publish_candidates(RacingRegion.HONG_KONG, window=self._window(now=now), now=now)

        self.assertEqual(result.selected, [article])
        self.assertEqual(result.pool["realtime_loaded"], 1)
        self.assertEqual(result.pool["backlog_loaded"], 1)
        self.assertEqual(result.pool["merged_count"], 1)
        self.assertEqual(
            WindowCandidateDecision.objects.get(article=article).payload["candidate_channels"],
            ["backlog", "realtime"],
        )

    def test_expired_ready_candidate_is_never_selected_from_realtime(self):
        now = timezone.now()
        article = self._article(
            now=now,
            first_seen_at=now - timedelta(minutes=30),
            publish_ready_at=now - timedelta(hours=25),
        )
        with self._settings():
            result = select_publish_candidates(RacingRegion.HONG_KONG, window=self._window(now=now), now=now)

        self.assertEqual(result.selected, [])
        decision = WindowCandidateDecision.objects.get(article=article)
        self.assertEqual(decision.reason, "publish_ready_manual_review")
        self.assertEqual(decision.payload["publish_ready_age_tier"], "manual_review")

    def test_each_lane_is_bounded_and_reports_truncation(self):
        now = timezone.now()
        for sequence in range(3):
            self._article(
                now=now,
                source_article_id=f"bounded-{sequence}",
                first_seen_at=now - timedelta(minutes=sequence + 1),
                score_total=90 - sequence,
            )
        with self._settings(
            MULTIREGION_PUBLISH_REALTIME_SCAN_LIMIT=2,
            MULTIREGION_PUBLISH_BACKLOG_SCAN_LIMIT=2,
        ):
            pool = build_candidate_pool(RacingRegion.HONG_KONG, now=now)

        self.assertEqual(pool.summary["realtime_loaded"], 2)
        self.assertTrue(pool.summary["realtime_truncated"])
        self.assertEqual(pool.summary["backlog_loaded"], 2)
        self.assertTrue(pool.summary["backlog_truncated"])
        self.assertLessEqual(len(pool.articles), 2)

    def test_equal_score_prefers_article_that_became_ready_earlier(self):
        now = timezone.now()
        older = self._article(
            now=now,
            source_article_id="tie-older",
            publish_ready_at=now - timedelta(hours=8),
        )
        self._article(
            now=now,
            source_article_id="tie-newer",
            publish_ready_at=now - timedelta(hours=1),
        )
        with self._settings(MULTIREGION_PUBLISH_REGION_WINDOW_MAX=1):
            result = select_publish_candidates(RacingRegion.HONG_KONG, window=self._window(now=now), now=now)

        self.assertEqual(result.selected, [older])

    def test_age_boundaries_are_inclusive_only_on_the_safer_side(self):
        now = timezone.now()
        at_24h = self._article(now=now, source_article_id="at-24h", publish_ready_at=now - timedelta(hours=24))
        after_24h = self._article(
            now=now,
            source_article_id="after-24h",
            publish_ready_at=now - timedelta(hours=24, microseconds=1),
        )
        at_72h = self._article(now=now, source_article_id="at-72h", publish_ready_at=now - timedelta(hours=72))
        after_72h = self._article(
            now=now,
            source_article_id="after-72h",
            publish_ready_at=now - timedelta(hours=72, microseconds=1),
        )
        with self._settings():
            tiers = [
                publish_ready_age_payload(article, now=now)["publish_ready_age_tier"]
                for article in (at_24h, after_24h, at_72h, after_72h)
            ]

        self.assertEqual(tiers, ["auto", "manual_review", "manual_review", "expired"])

    def test_thousand_row_backlog_pool_stays_bounded_and_fast(self):
        now = timezone.now()
        articles = []
        for sequence in range(1000):
            articles.append(
                NewsArticle(
                    source_site=SourceSite.TDN,
                    source_mode=SourceMode.LATEST,
                    source_language=SourceLanguage.ENGLISH,
                    source_article_id=f"perf-{sequence}",
                    racing_region=RacingRegion.JAPAN,
                    title_ja=f"Performance {sequence}",
                    body_ja_raw="Body " * 30,
                    title_zh=f"性能候选 {sequence}",
                    summary_zh=f"摘要 {sequence}",
                    body_zh="正文。" * 30,
                    published_at=now - timedelta(hours=8),
                    first_seen_at=now - timedelta(hours=8),
                    source_url=f"https://example.com/perf-{sequence}",
                    workflow_status=WorkflowStatus.PENDING_EDIT,
                    review_mode=ReviewMode.AUTO,
                    automation_status=AutomationStatus.PUBLISH_READY,
                    publish_ready_at=now - timedelta(hours=2),
                    score_total=80,
                    quality_score=80,
                )
            )
        NewsArticle.objects.bulk_create(articles)

        started = time.monotonic()
        with self._settings(
            MULTIREGION_PUBLISH_BACKLOG_ALLOWED_REGIONS=[RacingRegion.JAPAN],
            MULTIREGION_PUBLISH_BACKLOG_SCAN_LIMIT=200,
        ), CaptureQueriesContext(connection) as queries:
            pool = build_candidate_pool(RacingRegion.JAPAN, now=now)
        elapsed = time.monotonic() - started

        self.assertEqual(len(pool.articles), 200)
        self.assertTrue(pool.summary["backlog_truncated"])
        self.assertLessEqual(len(queries), 2)
        self.assertLess(elapsed, 2.0)

    def test_age_summary_separates_auto_review_expired_and_legacy(self):
        now = timezone.now()
        self._article(now=now, source_article_id="age-auto", publish_ready_at=now - timedelta(hours=2))
        self._article(now=now, source_article_id="age-review", publish_ready_at=now - timedelta(hours=48))
        self._article(now=now, source_article_id="age-expired", publish_ready_at=now - timedelta(hours=80))
        self._article(now=now, source_article_id="age-legacy", publish_ready_at=None)

        with self._settings():
            summary = publish_ready_age_summary(NewsArticle.objects.all(), now=now)

        self.assertEqual(summary["auto_0_24h"], 1)
        self.assertEqual(summary["review_24_72h"], 1)
        self.assertEqual(summary["expired_over_72h"], 1)
        self.assertEqual(summary["legacy_missing"], 1)
        self.assertGreaterEqual(summary["oldest_age_minutes"], 80 * 60)

    def test_stale_ready_alert_has_reason_specific_cooldown(self):
        from stable.tasks import detect_automation_anomalies_task

        now = timezone.now()
        self._article(now=now, source_article_id="stale-alert", publish_ready_at=now - timedelta(hours=30))
        with self._settings(AUTOMATION_ENABLED=True, AUTOMATION_ENABLE_EMAIL=False):
            first = detect_automation_anomalies_task.run()
            second = detect_automation_anomalies_task.run()

        alerts = NotificationLog.objects.filter(
            type=NotificationType.BACKLOG,
            payload_summary__icontains="stale_publish_ready_review",
        )
        self.assertIn(NotificationType.BACKLOG, first["notifications"])
        self.assertNotIn(NotificationType.BACKLOG, second["notifications"])
        self.assertEqual(alerts.count(), 4)

    def test_manifest_dry_run_is_zero_write_and_defaults_to_keep_manual(self):
        now = timezone.now()
        article = self._article(now=now, publish_ready_at=None)
        before = {
            "updated_at": article.updated_at,
            "article_count": NewsArticle.objects.count(),
            "qq_count": article.qq_push_deliveries.count(),
        }

        with self._settings():
            manifest = build_publish_ready_backlog_manifest(now=now)

        article.refresh_from_db()
        self.assertEqual(len(manifest["articles"]), 1)
        self.assertEqual(manifest["articles"][0]["article_id"], article.id)
        self.assertEqual(manifest["articles"][0]["review_action"], "keep_manual")
        self.assertEqual(article.updated_at, before["updated_at"])
        self.assertEqual(NewsArticle.objects.count(), before["article_count"])
        self.assertEqual(article.qq_push_deliveries.count(), before["qq_count"])
        self.assertNotIn("Body Body", json.dumps(manifest, ensure_ascii=False))

    def test_reviewed_manifest_keep_manual_locks_but_writes_nothing(self):
        now = timezone.now()
        article = self._article(now=now, publish_ready_at=None)
        with self._settings():
            pending = build_publish_ready_backlog_manifest(now=now)
            reviewed = seal_publish_ready_backlog_review(
                pending,
                decisions={},
                reviewer="test-reviewer",
                now=now,
            )
            result = apply_publish_ready_backlog_manifest(
                reviewed,
                expected_sha256=reviewed["manifest_sha256"],
                now=now,
            )

        article.refresh_from_db()
        self.assertEqual(result["kept_manual_count"], 1)
        self.assertIsNone(article.publish_ready_at)
        self.assertIsNone(article.published_to_web_at)
        self.assertEqual(article.qq_push_deliveries.count(), 0)

    def test_reviewed_manifest_skips_content_drift(self):
        now = timezone.now()
        article = self._article(now=now, publish_ready_at=None)
        with self._settings():
            pending = build_publish_ready_backlog_manifest(now=now)
            reviewed = seal_publish_ready_backlog_review(
                pending,
                decisions={str(article.id): "revalidate_refresh_ready"},
                reviewer="test-reviewer",
                now=now,
            )
        article.title_zh = "审核后内容发生变化"
        article.save(update_fields=["title_zh", "updated_at"])

        result = apply_publish_ready_backlog_manifest(
            reviewed,
            expected_sha256=reviewed["manifest_sha256"],
            now=now,
        )

        article.refresh_from_db()
        self.assertEqual(result["outcomes"][0]["status"], "skipped")
        self.assertTrue(result["outcomes"][0]["reason"].startswith("drift:"))
        self.assertIsNone(article.publish_ready_at)

    def test_reviewed_manifest_discard_is_audited_and_idempotent(self):
        now = timezone.now()
        article = self._article(now=now, publish_ready_at=None)
        with self._settings():
            pending = build_publish_ready_backlog_manifest(now=now)
            reviewed = seal_publish_ready_backlog_review(
                pending,
                decisions={str(article.id): "discard_ignored"},
                reviewer="test-reviewer",
                now=now,
            )
            first = apply_publish_ready_backlog_manifest(
                reviewed,
                expected_sha256=reviewed["manifest_sha256"],
                now=now,
            )
            second = apply_publish_ready_backlog_manifest(
                reviewed,
                expected_sha256=reviewed["manifest_sha256"],
                now=now,
            )

        article.refresh_from_db()
        recovery = article.decision_reason["publish_ready_recovery"]
        self.assertEqual(first["discarded_count"], 1)
        self.assertEqual(second["already_applied_count"], 1)
        self.assertEqual(article.workflow_status, WorkflowStatus.IGNORED)
        self.assertEqual(article.review_mode, ReviewMode.IGNORED)
        self.assertEqual(article.automation_status, AutomationStatus.IGNORED)
        self.assertEqual(article.ignored_at, now)
        self.assertEqual(recovery["manifest_sha256"], reviewed["manifest_sha256"])
        self.assertEqual(recovery["reviewer"], "test-reviewer")
        self.assertEqual(recovery["action"], "discard_ignored")
        self.assertIsNone(article.published_to_web_at)
        self.assertEqual(article.qq_push_deliveries.count(), 0)

        with self._settings():
            followup = build_publish_ready_backlog_manifest(now=now)
        self.assertEqual(followup["articles"], [])

    def test_reviewed_revalidation_only_refreshes_ready_time_and_is_idempotent(self):
        now = timezone.now()
        article = self._article(now=now, publish_ready_at=now - timedelta(hours=80))
        with self._settings():
            pending = build_publish_ready_backlog_manifest(now=now)
            reviewed = seal_publish_ready_backlog_review(
                pending,
                decisions={str(article.id): "revalidate_refresh_ready"},
                reviewer="test-reviewer",
                now=now,
            )
        outcome = ValidationOutcome(True, "review passed", {}, [])

        with patch("stable.services.publish_ready_backlog.validate_rewrite", return_value=outcome):
            first = apply_publish_ready_backlog_manifest(
                reviewed,
                expected_sha256=reviewed["manifest_sha256"],
                now=now,
            )
            second = apply_publish_ready_backlog_manifest(
                reviewed,
                expected_sha256=reviewed["manifest_sha256"],
                now=now,
            )

        article.refresh_from_db()
        self.assertEqual(first["refreshed_count"], 1)
        self.assertEqual(second["outcomes"][0]["status"], "already_applied")
        self.assertEqual(article.publish_ready_at, now)
        self.assertIsNone(article.published_to_web_at)
        self.assertNotEqual(article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(article.qq_push_deliveries.count(), 0)

    def test_management_dry_run_refuses_to_overwrite_manifest(self):
        now = timezone.now()
        self._article(now=now, publish_ready_at=None)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "manifest.json"
            stdout = StringIO()
            with self._settings():
                call_command("reconcile_publish_ready_backlog", "--output", str(output), stdout=stdout)
                with self.assertRaises(CommandError):
                    call_command("reconcile_publish_ready_backlog", "--output", str(output), stdout=StringIO())

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["database_writes"], 0)
            self.assertTrue(output.is_file())

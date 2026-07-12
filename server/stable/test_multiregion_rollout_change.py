from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse

from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    NewsArticle,
    NewsArticleRelatedRegion,
    ProductionWindow,
    ProductionWindowKind,
    ProductionWindowMode,
    PublishedByMode,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    RacingRegion,
    ReviewMode,
    SourceLanguage,
    SourceMode,
    SourceSite,
    WindowCandidateDecision,
    WorkflowStatus,
)


UTC = dt_timezone.utc
NOW = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)


def published_article(**overrides) -> NewsArticle:
    values = {
        "source_site": SourceSite.TDN,
        "source_mode": SourceMode.LATEST,
        "source_article_id": f"rollout-{NewsArticle.objects.count()}",
        "source_url": f"https://example.com/rollout/{NewsArticle.objects.count()}",
        "racing_region": RacingRegion.UNITED_KINGDOM,
        "source_language": SourceLanguage.ENGLISH,
        "title_ja": "Cross-region racing news",
        "body_ja_raw": "Cross-region racing news body " * 20,
        "body_ja_normalized": "Cross-region racing news body " * 20,
        "title_zh": "跨地区赛马新闻",
        "summary_zh": "跨地区摘要",
        "body_zh": "跨地区正文。" * 30,
        "published_at": NOW,
        "first_seen_at": NOW,
        "last_seen_at": NOW,
        "published_at_verified": True,
        "published_to_web_at": NOW,
        "auto_publish_at": NOW,
        "translation_status": ArticleTranslationStatus.TRANSLATED,
        "workflow_status": WorkflowStatus.PUBLISHED,
        "review_mode": ReviewMode.AUTO,
        "automation_status": AutomationStatus.AUTO_PUBLISHED,
        "published_by_mode": PublishedByMode.AUTO,
        "attribution_status": "applied",
        "score_total": 90,
        "quality_score": 90,
        "rewrite_confidence": 90,
    }
    values.update(overrides)
    return NewsArticle.objects.create(**values)


def window(kind: str, region: str) -> ProductionWindow:
    return ProductionWindow.objects.create(
        kind=kind,
        mode=ProductionWindowMode.DAILY,
        racing_region=region,
        scope_key=f"{kind}:{region}",
        window_start=NOW,
        window_end=NOW + timedelta(minutes=15),
    )


class SingleArticleVisibilityTests(TestCase):
    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="web_test_groups",
    )
    def test_related_region_page_returns_one_article_with_stable_pagination(self):
        article = published_article()
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="test")
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.JAPAN, source="test")

        first = self.client.get("/", {"region": RacingRegion.FRANCE, "page": 1})
        second = self.client.get("/", {"region": RacingRegion.FRANCE, "page": 1})

        self.assertEqual(first.status_code, 200)
        self.assertContains(first, article.title_zh)
        self.assertEqual(first.content, second.content)
        self.assertEqual(NewsArticle.objects.filter(pk=article.pk).count(), 1)

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="shadow",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
    )
    def test_related_queries_are_ineffective_outside_enforce(self):
        article = published_article()
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="legacy")

        response = self.client.get("/", {"region": RacingRegion.FRANCE})

        self.assertNotContains(response, article.title_zh)

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="web_test_groups",
        MULTIREGION_PUBLISH_REGION_WINDOW_MAX=5,
        MULTIREGION_PUBLISH_REGION_WINDOW_MIN=1,
        MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY=60,
    )
    def test_related_region_visibility_never_consumes_second_publish_quota(self):
        from stable.services.publishing_windows import select_publish_candidates

        article = published_article(
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            published_to_web_at=None,
            auto_publish_at=None,
            automation_status=AutomationStatus.PUBLISH_READY,
            published_by_mode="",
        )
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="test")
        france_window = window(ProductionWindowKind.PUBLISH, RacingRegion.FRANCE)

        result = select_publish_candidates(RacingRegion.FRANCE, window=france_window, now=NOW)

        self.assertEqual(result.selected, [])
        decision = WindowCandidateDecision.objects.get(window=france_window, article=article)
        self.assertEqual(decision.reason, "related_region_waiting_primary_region")


class SingleQQDeliveryTests(TestCase):
    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="web_test_groups",
        QQ_PUSH_SCOPE="all_public",
    )
    def test_primary_and_related_match_create_only_one_article_target_delivery(self):
        from stable.services.qq_auto_push import ensure_qq_push_deliveries

        article = published_article(racing_region=RacingRegion.FRANCE)
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.UNITED_KINGDOM, source="test")
        target = PushTarget.objects.create(
            name="France and UK group",
            group_id="france-uk",
            allowed_regions=[RacingRegion.FRANCE, RacingRegion.UNITED_KINGDOM],
            is_active=True,
        )

        ensure_qq_push_deliveries(article, targets=[target])
        ensure_qq_push_deliveries(article, targets=[target])

        self.assertEqual(QQPushDelivery.objects.filter(article=article, target=target).count(), 1)

    def test_database_constraint_rejects_duplicate_article_target_delivery(self):
        article = published_article()
        target = PushTarget.objects.create(name="Target", group_id="target")
        QQPushDelivery.objects.create(article=article, target=target, status=QQPushDeliveryStatus.PENDING)

        with self.assertRaises(IntegrityError):
            QQPushDelivery.objects.create(article=article, target=target, status=QQPushDeliveryStatus.PENDING)

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="web_test_groups",
        QQ_PUSH_SCOPE="all_public",
    )
    def test_test_group_stage_keeps_formal_qq_targets_on_primary_region_only(self):
        from stable.services.qq_auto_push import should_push_news_to_qq

        article = published_article(racing_region=RacingRegion.UNITED_KINGDOM)
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="test")
        formal = PushTarget.objects.create(
            name="Formal France",
            group_id="formal-france",
            allowed_regions=[RacingRegion.FRANCE],
        )
        test_group = PushTarget.objects.create(
            name="Test France",
            group_id="test-france",
            allowed_regions=[RacingRegion.FRANCE],
            multiregion_test_enabled=True,
        )

        self.assertFalse(should_push_news_to_qq(article, target=formal).allowed)
        self.assertTrue(should_push_news_to_qq(article, target=test_group).allowed)

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="formal_groups",
        QQ_PUSH_SCOPE="all_public",
    )
    def test_formal_group_stage_enables_related_regions_for_all_targets(self):
        from stable.services.qq_auto_push import should_push_news_to_qq

        article = published_article(racing_region=RacingRegion.UNITED_KINGDOM)
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="test")
        target = PushTarget.objects.create(
            name="Formal France",
            group_id="formal-france-all",
            allowed_regions=[RacingRegion.FRANCE],
        )

        self.assertTrue(should_push_news_to_qq(article, target=target).allowed)


class BackfillSideEffectTests(TestCase):
    def test_recent_attribution_backfill_preserves_publish_and_qq_state(self):
        from stable.services.attribution_runs import commit_attribution_run, create_attribution_dry_run

        article = published_article(racing_region=RacingRegion.UNITED_STATES)
        target = PushTarget.objects.create(name="Existing target", group_id="existing")
        delivery = QQPushDelivery.objects.create(
            article=article,
            target=target,
            status=QQPushDeliveryStatus.SENT,
            sent_at=NOW,
            message_id="existing-message",
        )
        before = (article.published_to_web_at, article.auto_publish_at, delivery.status, delivery.message_id)
        run = create_attribution_dry_run([article], rule_version="multiregion-v2", gold_version="gold-v1", metrics={"qualified": True})

        commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)

        article.refresh_from_db()
        delivery.refresh_from_db()
        after = (article.published_to_web_at, article.auto_publish_at, delivery.status, delivery.message_id)
        self.assertEqual(after, before)
        self.assertEqual(QQPushDelivery.objects.filter(article=article, target=target).count(), 1)


class MultiregionOperationsViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="password", is_staff=True)
        self.normal = User.objects.create_user("normal", password="password")

    def test_non_staff_cannot_open_region_operations(self):
        self.client.force_login(self.normal)

        response = self.client.get(reverse("console-region-production"))

        self.assertEqual(response.status_code, 403)

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="shadow",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=False,
    )
    def test_staff_view_shows_mode_quality_run_and_rollout_stage(self):
        from stable.models import MultiregionAttributionRun

        MultiregionAttributionRun.objects.create(
            mode="dry_run",
            status="completed",
            rule_version="v2",
            gold_version="gold-v1",
            metrics={"qualified": False, "no_go_reasons": ["region_accuracy"]},
            manifest_sha256="a" * 64,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("console-region-production"))

        self.assertContains(response, "shadow")
        self.assertContains(response, "gold-v1")
        self.assertContains(response, "no-go")
        self.assertContains(response, "相关地区查询：关闭")

    def test_operations_view_ignores_newer_time_repair_run(self):
        from stable.models import MultiregionAttributionRun

        MultiregionAttributionRun.objects.create(
            mode="dry_run",
            status="completed",
            rule_version="multiregion-v2",
            gold_version="gold-v1",
            gold_snapshot_sha256="c" * 64,
            metrics={"qualified": True},
            manifest_sha256="a" * 64,
        )
        MultiregionAttributionRun.objects.create(
            mode="dry_run",
            status="completed",
            selectors={"kind": "france_galop_published_at_repair"},
            manifest_sha256="b" * 64,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("console-region-production"))

        self.assertContains(response, "gold-v1")
        self.assertContains(response, "go")

    def test_failure_rows_include_direct_article_or_task_links(self):
        article = published_article(
            workflow_status=WorkflowStatus.TRANSLATION_FAILED,
            automation_status=AutomationStatus.FAILED,
            translation_status=ArticleTranslationStatus.FAILED,
            translation_error_category="transient_provider_unavailable",
            translation_next_retry_at=NOW + timedelta(minutes=5),
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("console-region-production"), {"region": RacingRegion.UNITED_KINGDOM})

        self.assertContains(response, "translation_retry_waiting")
        self.assertContains(response, reverse("admin:stable_newsarticle_change", args=[article.id]))

    def test_region_operations_query_count_is_bounded_for_large_failure_set(self):
        for index in range(250):
            published_article(
                source_article_id=f"large-failure-{index}",
                source_url=f"https://example.com/large-failure/{index}",
                workflow_status=WorkflowStatus.TRANSLATION_FAILED,
                automation_status=AutomationStatus.FAILED,
                translation_status=ArticleTranslationStatus.FAILED,
                translation_error_category="transient_provider_unavailable",
                translation_next_retry_at=NOW + timedelta(minutes=5),
            )
        self.client.force_login(self.staff)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                reverse("console-region-production"),
                {"region": RacingRegion.UNITED_KINGDOM},
            )

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 45)


class ProductionReasonTests(TestCase):
    def test_zero_reason_classifier_distinguishes_all_new_failure_layers(self):
        from stable.services.production_observability import classify_zero_output_reasons

        cases = [
            ({"search_missed_latest": 1}, "search_missed_latest"),
            ({"published_at_unverified": 1}, "published_at_unverified"),
            ({"translation_retry_waiting": 1}, "translation_retry_waiting"),
            ({"translation_retry_exhausted": 1}, "translation_retry_exhausted"),
            ({"attribution_needs_review": 1}, "attribution_needs_review"),
            ({"related_region_visible": 1}, "related_region_visible"),
        ]
        for counts, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(expected, classify_zero_output_reasons(counts))

    def test_france_summary_keeps_every_pipeline_layer_separate(self):
        from stable.services.production_observability import summarize_france_pipeline

        report = summarize_france_pipeline(
            source_candidates=12,
            deduped_articles=10,
            translated=8,
            attributed=7,
            gate_passed=6,
            selected=5,
            web_published=5,
            qq_delivered=3,
        )

        self.assertEqual(
            report.counts,
            {
                "source_candidates": 12,
                "deduped_articles": 10,
                "translated": 8,
                "attributed": 7,
                "gate_passed": 6,
                "selected": 5,
                "web_published": 5,
                "qq_delivered": 3,
            },
        )
        self.assertEqual(report.losses["dedupe"], 2)
        self.assertEqual(report.losses["translation"], 2)
        self.assertEqual(report.losses["qq"], 2)

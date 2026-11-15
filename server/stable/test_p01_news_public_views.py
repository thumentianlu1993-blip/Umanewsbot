"""T27/T28/T36：所有公开入口使用精确稿件回执。"""
from django.test import TransactionTestCase
from stable.models import NewsPublicationReceipt
from stable.services.ingestion import upsert_article_from_draft
from stable.test_p01_news_workflow import WorkflowFixture, workflow_draft


class ReceiptViewTests(WorkflowFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.public_settings = self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True, ALLOWED_HOSTS=["testserver"])
        self.public_settings.enable()
        self.addCleanup(self.public_settings.disable)
        self.finish()
        self.first = NewsPublicationReceipt.objects.get(run=self.run)
        article = upsert_article_from_draft(workflow_draft("30")).article
        second_run = self.finish(article.active_news_run)
        self.second = NewsPublicationReceipt.objects.get(run=second_run)

    def test_independent_urls_and_legacy_anchor_resolve_exact_text(self):
        first = self.client.get(self.article.public_path)
        second = self.client.get(self.second.public_path)
        self.assertEqual(second.status_code, 200)
        self.assertContains(first, "奖金为27。")
        self.assertNotContains(first, "奖金为30。")
        self.assertContains(second, "奖金为30。")
        self.assertContains(second, self.first.public_path)
        self.assertIn("no-store", second["Cache-Control"])

    def test_withdrawn_first_never_redirects_legacy_url_to_second(self):
        NewsPublicationReceipt.objects.filter(pk=self.first.pk).update(visibility="withdrawn")
        self.assertEqual(self.client.get(self.article.public_path).status_code, 404)
        self.assertEqual(self.client.get(self.first.public_path).status_code, 404)
        self.assertEqual(self.client.get(self.second.public_path).status_code, 200)

    def test_feed_uses_both_receipts_and_returns_generation(self):
        from stable.services.news_feed import create_snapshot
        create_snapshot(with_features=True)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-News-Generation", response)
        self.assertContains(response, self.first.public_path)
        self.assertContains(response, self.second.public_path)

    def test_no_ready_snapshot_is_explicitly_unavailable(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 503)

    def test_manual_headline_binds_exact_receipt_and_preserves_cancel_version(self):
        from django.contrib.auth import get_user_model
        from stable.models import HomepageHeadlineSelection
        from stable.services.editorial_headlines import set_manual_headline, cancel_manual_headline
        user = get_user_model().objects.create_superuser("headline-editor", "fixture@example.invalid", "fixture")
        first = set_manual_headline(self.article.pk, user=user, expected_version=0)
        selection = HomepageHeadlineSelection.objects.get(slot="homepage_primary")
        self.assertEqual(selection.receipt_id, self.first.pk)
        second = set_manual_headline(self.article.pk, receipt_id=self.second.pk, user=user, expected_version=first["version"])
        selection.refresh_from_db()
        self.assertEqual(selection.receipt_id, self.second.pk)
        self.assertGreater(second["version"], first["version"])
        cancel_manual_headline(user=user, expected_version=second["version"])
        selection.refresh_from_db()
        self.assertIsNone(selection.article_id)
        self.assertIsNone(selection.receipt_id)

    def test_recommendation_uses_current_receipt_instead_of_original_anchor(self):
        from django.contrib.auth import get_user_model
        from stable.models import HomepageHeadlineRecommendation
        from stable.services.news_feed import create_snapshot
        from stable.services.editorial_headlines import generate_headline_recommendation, accept_headline_recommendation
        user = get_user_model().objects.create_superuser("recommend-editor", "fixture@example.invalid", "fixture")
        create_snapshot(with_features=True)
        result = generate_headline_recommendation(user=user)
        self.assertIsNotNone(result)
        recommendation = HomepageHeadlineRecommendation.objects.get(pk=result["id"])
        self.assertEqual(recommendation.receipt_id, self.second.pk)

    def test_legacy_detail_links_to_independent_new_stories(self):
        from stable.models import NewsArticle, NewsPublicEntry
        from django.utils import timezone
        legacy = NewsArticle.objects.create(source_site="jra", source_mode="official", source_article_id="old-detail",
            title_ja="旧新闻", title_zh="旧新闻", summary_zh="旧新闻摘要", body_zh="旧新闻正文", published_at=timezone.now(),
            source_url="https://fixture.invalid/legacy", workflow_status="published", published_to_web_at=timezone.now(), racing_region="france")
        from stable.services.news_feed import save_legacy_publication
        save_legacy_publication(legacy)
        response = self.client.get(legacy.public_path)
        self.assertContains(response, self.second.public_path)

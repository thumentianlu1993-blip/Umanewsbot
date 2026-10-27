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
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-News-Generation", response)
        self.assertContains(response, self.first.public_path)
        self.assertContains(response, self.second.public_path)

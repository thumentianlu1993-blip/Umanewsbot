"""T07/T10/T20/T26–T28/T35：独立稿件和唯一网页提交。"""
from copy import deepcopy
from unittest.mock import patch
from django.test import TransactionTestCase
from stable.models import NewsArticle, NewsPublicationReceipt, NewsPublicEntry
from stable.services.ingestion import upsert_article_from_draft
from stable.services.news_pipeline import process_news_run, publish_news_web
from stable.test_p01_news_workflow import WorkflowFixture, workflow_draft


class PublicationTests(WorkflowFixture, TransactionTestCase):
    def publish_first(self):
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True):
            self.finish()
        self.assertEqual(self.run.state, "published", self.run.reason)
        return NewsPublicationReceipt.objects.get(run=self.run)

    def test_first_receipt_matches_reviewed_full_text_without_external_messages(self):
        with patch("stable.services.qq_auto_push.enqueue_qq_auto_push_for_article") as qq, patch("stable.tasks.send_notification_task") as notifications:
            receipt = self.publish_first()
        self.article.refresh_from_db()
        self.assertEqual(receipt.content["body"], self.run.translation_snapshot["body"])
        self.assertEqual(self.article.effective_body, receipt.content["body"])
        self.assertEqual(NewsPublicEntry.objects.get(receipt=receipt).article_id, self.article.pk)
        qq.assert_not_called()
        notifications.delay.assert_not_called()
        notifications.run.assert_not_called()

    def test_same_url_update_creates_new_story_and_keeps_original_unchanged(self):
        first = self.publish_first()
        before = NewsArticle.objects.values().get(pk=self.article.pk)
        frozen = deepcopy(first.content)
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True):
            article = upsert_article_from_draft(workflow_draft("30")).article
            second_run = self.finish(article.active_news_run)
        self.assertEqual(second_run.state, "published", second_run.reason)
        after = NewsArticle.objects.values().get(pk=self.article.pk)
        for field in ("title_ja", "body_ja_raw", "body_ja_normalized", "original_content_html", "title_zh", "body_zh", "summary_zh", "published_at", "published_to_web_at", "source_url", "public_slug"):
            self.assertEqual(before[field], after[field], field)
        first.refresh_from_db()
        second = NewsPublicationReceipt.objects.get(run=second_run)
        self.assertEqual(first.content, frozen)
        self.assertEqual(second.previous_receipt_id, first.pk)
        self.assertIn("30", second.content["body"])
        self.assertNotEqual(first.public_path, second.public_path)
        self.assertEqual(NewsPublicEntry.objects.filter(article=article).count(), 2)

    def test_repeated_same_fact_does_not_create_a_second_public_story(self):
        self.publish_first()
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True):
            article = upsert_article_from_draft(workflow_draft("27")).article
            duplicate = self.finish(article.active_news_run)
        self.assertEqual(duplicate.state, "duplicate", duplicate.reason)
        self.assertEqual(NewsPublicationReceipt.objects.count(), 1)

    def test_changed_target_after_audit_cannot_be_published(self):
        self.finish()
        self.assertEqual(self.run.state, "shadow", self.run.reason)
        changed = {**self.run.translation_snapshot, "body": "未审核的新正文"}
        self.run.translation_snapshot = changed
        self.run.state = "ready"
        self.run.save(update_fields=["state", "translation_snapshot"])
        with self.settings(NEWS_QUALITY_MODE="enforce", NEWS_QUALITY_FEED_ENABLED=True):
            publish_news_web(self.run.pk)
        self.assertFalse(NewsPublicationReceipt.objects.exists())
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "review")

    def test_shadow_direct_writer_never_publishes(self):
        self.finish()
        publish_news_web(self.run.pk)
        self.assertFalse(NewsPublicationReceipt.objects.exists())

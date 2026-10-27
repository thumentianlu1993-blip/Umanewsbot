"""P01 回归：版本、单写入、费用、独立公开稿（T16–T30）。"""
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from django.apps import apps

from stable.models import NewsArticle, WorkflowStatus
from stable.services.automation import publish_article_automatically


class LegacyWriterFenceTests(SimpleTestCase):
    @override_settings(NEWS_QUALITY_MODE="off")
    def test_paused_pipeline_never_falls_back_to_legacy_publication(self):
        article = NewsArticle(workflow_status=WorkflowStatus.PENDING_TRANSLATION)
        article.active_news_run_id = 123
        article.save = Mock()
        with patch("stable.services.automation.log_automation"), patch(
            "stable.services.qq_auto_push.enqueue_qq_auto_push_for_article"
        ) as qq:
            publish_article_automatically(article)
        self.assertEqual(article.workflow_status, WorkflowStatus.PENDING_TRANSLATION)
        article.save.assert_not_called()
        qq.assert_not_called()


class PipelineSchemaTests(SimpleTestCase):
    def test_independent_versions_and_persistent_discovery_are_registered(self):
        names = {model.__name__ for model in apps.get_app_config("stable").get_models()}
        expected = {
            "NewsProcessingRun", "NewsStageAttempt", "NewsModelBudget",
            "NewsEditorialEvent", "NewsPublicationReceipt", "NewsFeedSnapshot",
            "NewsDiscoveryObservation", "NewsPublicEntry",
        }
        self.assertFalse(expected - names, f"缺少持久化合同: {sorted(expected - names)}")

    def test_article_has_durable_owner_even_when_feature_is_off(self):
        fields = {field.name for field in NewsArticle._meta.fields}
        self.assertTrue({"active_news_run", "news_generation"} <= fields)


from django.test import TestCase
from django.utils import timezone
from stable.models import NewsProcessingRun
from stable.services.ingestion import upsert_article_from_draft
from stable.test_france_news_freshness_change import draft_for


class SourceRevisionFenceTests(TestCase):
    def setUp(self):
        self.article = upsert_article_from_draft(draft_for()).article
        self.run = NewsProcessingRun.objects.create(
            article=self.article, input_sha="a" * 64, policy_sha="b" * 64,
            expected_article_sha="c" * 64, primary_region="france",
            source_snapshot={"title": self.article.title_ja, "body": self.article.body_ja_raw},
        )
        self.article.active_news_run = self.run
        self.article.workflow_status = WorkflowStatus.PUBLISHED
        self.article.title_zh = "旧稿标题"
        self.article.body_zh = "旧稿全文"
        self.article.published_to_web_at = timezone.now()
        self.article.save()

    @override_settings(NEWS_QUALITY_MODE="off")
    def test_recrawl_preserves_published_source_and_creates_independent_revision(self):
        before = NewsArticle.objects.values().get(pk=self.article.pk)
        draft = draft_for()
        draft.title_ja = "Corrected official news"
        draft.body_ja_raw = draft.body_ja_normalized = "A new material correction about a different horse."
        upsert_article_from_draft(draft)
        after = NewsArticle.objects.values().get(pk=self.article.pk)
        for field in ("title_ja", "body_ja_raw", "body_ja_normalized", "title_zh", "body_zh", "published_at", "published_to_web_at", "source_url"):
            self.assertEqual(before[field], after[field], field)
        latest = self.article.news_runs.order_by("-id").first()
        self.assertNotEqual(latest.pk, self.run.pk)
        self.assertEqual(latest.source_snapshot["body"], draft.body_ja_raw)

    def test_manual_legacy_publish_does_not_republish_or_notify(self):
        from stable.tasks import publish_article
        with patch("stable.services.qq_auto_push.enqueue_qq_auto_push_for_article") as qq, patch("stable.tasks.dispatch_task"), patch("stable.tasks.log_operation"):
            old_time = self.article.published_to_web_at
            publish_article(self.article, None)
        self.article.refresh_from_db()
        self.assertEqual(self.article.published_to_web_at, old_time)
        qq.assert_not_called()

    def test_old_rewrite_result_cannot_change_effective_body(self):
        from stable.services.rewriting import RewriteResult, apply_rewrite_result
        apply_rewrite_result(self.article, RewriteResult("旁路标题", "旁路摘要", "旁路正文", 99, {}))
        self.article.refresh_from_db()
        self.assertEqual(self.article.effective_body, "旧稿全文")

    def test_old_translation_result_cannot_change_effective_body(self):
        from stable.services.translation import TranslationResult
        self.article.apply_translation_result(TranslationResult("旁路标题", "旁路正文", "旁路摘要", {}), force=True)
        self.article.save()
        self.article.refresh_from_db()
        self.assertEqual(self.article.effective_body, "旧稿全文")

    def test_old_ready_transition_cannot_requalify_pipeline_article(self):
        from stable.services.automation import mark_publish_ready, is_ready_for_auto_publish
        mark_publish_ready(self.article)
        self.article.refresh_from_db()
        self.assertNotEqual(self.article.automation_status, "publish_ready")
        self.assertFalse(is_ready_for_auto_publish(self.article))

    def test_stale_orm_instance_cannot_bypass_persisted_owner(self):
        self.article.active_news_run_id = None
        with patch("stable.services.automation.log_automation"), patch("stable.services.qq_auto_push.enqueue_qq_auto_push_for_article") as qq:
            publish_article_automatically(self.article)
        qq.assert_not_called()

    @override_settings(NEWS_QUALITY_MODE="off")
    def test_edit_api_creates_review_target_and_leaves_public_body_unchanged(self):
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from stable.views import article_update_api
        editor = get_user_model().objects.create_user("p01-editor", is_staff=True)
        request = RequestFactory().post("/", data='{"title_zh":"修订标题","body_zh":"修订全文","summary_zh":"修订摘要"}', content_type="application/json")
        request.user = editor
        response = article_update_api(request, self.article.pk)
        self.assertEqual(response.status_code, 200)
        self.article.refresh_from_db()
        self.assertEqual(self.article.body_zh, "旧稿全文")
        self.assertEqual(self.article.active_news_run.manual_target["body"], "修订全文")

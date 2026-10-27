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

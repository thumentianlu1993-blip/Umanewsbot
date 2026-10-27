"""P01 回归：版本、单写入、费用、独立公开稿（T16–T30）。"""
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

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

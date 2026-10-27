"""T31：详情解析失败的候选仍计入发现分母。"""
from unittest.mock import Mock, patch
from django.test import TestCase, override_settings
from django.utils import timezone
from stable.models import NewsSource, NewsArticle, NewsDiscoveryObservation
from stable.adapters.base import SourceArticleStub
from stable.tasks import _crawl_international_source


class DiscoveryDenominatorTests(TestCase):
    def setUp(self):
        self.source = NewsSource.objects.create(name="Fixture TDN", source_site="tdn", source_mode="latest", adapter_key="tdn", racing_region="united_states", production_approved=True)
        self.stubs = [SourceArticleStub(source_site="tdn", source_mode="latest", source_article_id=str(i), source_url=f"https://fixture.invalid/news/{i}", title_ja=f"Story {i}", published_at=timezone.now()) for i in range(3)]

    def test_three_detail_failures_remain_three_candidates_without_articles(self):
        adapter = Mock()
        adapter.fetch_listing.return_value = self.stubs
        adapter.fetch_detail.side_effect = ValueError("template changed")
        with override_settings(NEWS_QUALITY_MODE="shadow", NEWS_QUALITY_POLICY={"source_ids": [self.source.pk]}), patch.dict("stable.tasks.INTERNATIONAL_ADAPTERS", {"tdn": lambda: adapter}):
            _crawl_international_source(self.source)
        self.assertEqual(NewsArticle.objects.count(), 0)
        observations = NewsDiscoveryObservation.objects.filter(kind="stub")
        self.assertEqual(observations.count(), 3)
        self.assertEqual(set(observations.values_list("outcome", flat=True)), {"failed"})
        self.assertTrue(all(row.reason and row.item_key for row in observations))

    def test_listing_failure_retains_source_window_gap(self):
        adapter = Mock()
        adapter.fetch_listing.side_effect = RuntimeError("listing unavailable")
        with override_settings(NEWS_QUALITY_MODE="shadow", NEWS_QUALITY_POLICY={"source_ids": [self.source.pk]}), patch.dict("stable.tasks.INTERNATIONAL_ADAPTERS", {"tdn": lambda: adapter}):
            with self.assertRaises(RuntimeError):
                _crawl_international_source(self.source)
        observation = NewsDiscoveryObservation.objects.filter(kind="source_window").first()
        self.assertIsNotNone(observation)
        self.assertEqual(observation.outcome, "failed")
        self.assertIsNone(observation.article_id)

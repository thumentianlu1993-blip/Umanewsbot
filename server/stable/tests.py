from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from stable.adapters.jra import JRAAdapter
from stable.adapters.netkeiba import NetkeibaAdapter
from stable.models import NewsArticle, PushTarget, SourceMode, SourceSite, TermEntry
from stable.services.pushing import build_push_message, push_article_to_targets
from stable.services.terms import resolve_terms


class TermResolverTests(TestCase):
    def test_resolve_terms_prefers_active_entries(self):
        TermEntry.objects.create(
            term_type="horse",
            source_ja="ソダシ",
            target_zh="白毛马 苏打希",
            aliases_ja=["Sodashi"],
            priority=10,
        )
        matches = resolve_terms("ソダシが勝利した", limit=10)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].target_zh, "白毛马 苏打希")


class AdapterTests(TestCase):
    def test_netkeiba_listing_parse(self):
        fragment = """
        <div><a href="https://news.netkeiba.com/?pid=news_view&no=1" title="テスト記事" class="ArticleLink fc">
        <div class="NewsTxtBox"><h2 class="NewsTitle">テスト記事</h2>
        <ul class="Nk_DataList"><li class="Time">1時間前</li><li class="Comment">3</li><li class="Chumoku">8</li></ul>
        </div></a></div>
        """
        payload = "(" + __import__("json").dumps(fragment) + ")"
        with patch("stable.adapters.netkeiba.get_bytes", return_value=payload):
            items = NetkeibaAdapter().fetch_listing(SourceMode.LATEST, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_article_id, "1")
        self.assertEqual(items[0].comment_count, 3)

    def test_jra_listing_parse(self):
        html = """
        <div class="news_unit"><h2>2026年3月25日（水曜）</h2>
        <ul class="news_line_list"><li><a href="/news/202603/032503.html"><div class="txt">エイシンワンドの競走馬登録抹消</div></a></li></ul>
        </div>
        """
        with patch("stable.adapters.jra.get_bytes", return_value=html):
            items = JRAAdapter().fetch_listing(SourceMode.OFFICIAL, "202603")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_site, SourceSite.JRA)
        self.assertEqual(items[0].title_ja, "エイシンワンドの競走馬登録抹消")


class PushTests(TestCase):
    def setUp(self):
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="1",
            title_ja="原文标题",
            title_zh="中文标题",
            body_ja_raw="原文正文",
            body_ja_normalized="原文正文",
            body_zh="中文正文",
            push_summary_zh="中文摘要",
            published_at=timezone.now(),
            source_url="https://example.com/article/1",
        )
        self.target = PushTarget.objects.create(name="测试群", group_id="10001", is_default=True)

    def test_build_push_message_contains_source_url(self):
        text, image_url = build_push_message(self.article)
        self.assertIn("中文标题", text)
        self.assertIn("https://example.com/article/1", text)
        self.assertIsNone(image_url)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_push_article_success(self):
        with patch("stable.services.pushing.BotPusher.send_group_message", return_value={"status": "ok"}):
            logs = push_article_to_targets(self.article, [self.target])
        self.assertEqual(len(logs), 1)
        logs[0].refresh_from_db()
        self.article.refresh_from_db()
        self.assertEqual(logs[0].status, "success")
        self.assertEqual(self.article.status, "pushed")

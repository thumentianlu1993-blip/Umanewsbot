"""T01/T02：日本适配器完整 HTML 证据和疑似推广块的有界复核。"""
from unittest.mock import patch
from django.test import SimpleTestCase
from stable.adapters.base import SourceArticleStub
from stable.adapters.jra import JRAAdapter
from stable.adapters.netkeiba import NetkeibaAdapter
from stable.services import news_content
from stable.services.news_content import clean_source


class SourceEvidenceTests(SimpleTestCase):
    def test_japanese_adapters_preserve_original_html_in_canonical_input(self):
        cases = [
            (JRAAdapter(), "stable.adapters.jra.get_bytes", '<h1>JRA</h1><h1>公式発表</h1><div class="news_title"><span class="date">2026年10月27日</span></div><div class="news_body"><p>本文</p></div>', "https://www.jra.go.jp/news/202610/102701.html"),
            (NetkeibaAdapter(), "stable.adapters.netkeiba.get_bytes", '<h1 class="News_Title">記事</h1><span class="News_Data_Time">2026年10月27日 12:00</span><div class="News_Txt"><p>本文</p></div>', "123"),
        ]
        for adapter, target, html, url in cases:
            with self.subTest(adapter=adapter.source_site), patch(target, return_value=html):
                detail = adapter.fetch_detail(url)
                stub = SourceArticleStub(source_site=adapter.source_site, source_article_id="fixture", source_url=url, title_ja="title", source_mode="official", published_at=detail.published_at)
                draft = adapter.normalize_source_payload(stub, detail)
                self.assertEqual(draft.original_content_html, html)
                self.assertTrue(draft.metadata.get("published_at_evidence"))

    def test_suspicious_text_is_kept_until_bounded_review(self):
        snapshot = {"source_site": "jra", "title": "Title", "html": '<div class="news_body"><p>The horse won.</p><p>Subscribe now for offers</p><blockquote>He said subscribe now for offers.</blockquote></div>'}
        clean = clean_source(snapshot)
        self.assertEqual(clean.get("suspicious_block_ids"), ["b1"])
        self.assertIn("Subscribe", clean["blocks"][1]["text"])
        reviewed = news_content.validate_body_review(clean, {"decisions": [{"id": "b1", "decision": "remove", "reason": "subscription box"}]})
        self.assertEqual([row["id"] for row in reviewed["blocks"]], ["b0", "b2"])
        self.assertIn("said subscribe", reviewed["blocks"][1]["text"])
        with self.assertRaises(news_content.ContentBlocked):
            news_content.validate_body_review(clean, {"decisions": [{"id": "b0", "decision": "remove", "reason": "malicious"}]})

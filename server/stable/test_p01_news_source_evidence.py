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


class InternationalSourceRepairTests(SimpleTestCase):
    """来源诊断的最小DOM反例；合成夹具不冒充真实缓存。"""
    def detail(self, adapter, markup, url=None):
        return adapter.parse_detail_html(markup, url=url or adapter.base_url + 'sample')

    def draft(self, adapter, detail):
        from datetime import datetime, timezone
        stub = SourceArticleStub(adapter.source_site, 'latest', 'sample', adapter.base_url + 'sample',
                                 'Sample', datetime(2026, 10, 27, 15, tzinfo=timezone.utc))
        return adapter.normalize_source_payload(stub, detail)

    def test_scmp_selects_body_not_recommendation_and_removes_chrome(self):
        from stable.adapters.international import SCMPRacingAdapter
        html = '<h1>Fownes targets dirt meeting</h1><article><p>Unrelated recommended story</p></article><div class="article-body clearfix"><p>Fownes rates his runners highly.</p><div class="article-body-comment">Comments 0</div><div class="advert_wrapper">Advertisement</div></div>'
        detail = self.detail(SCMPRacingAdapter(), html)
        self.assertEqual(detail.body_ja_normalized, 'Fownes rates his runners highly.')
        clean = clean_source({'source_site': 'scmp_racing', 'title': detail.title_ja, 'html': html})
        self.assertEqual([b['text'] for b in clean['blocks']], ['Fownes rates his runners highly.'])

    def test_scmp_ambiguous_missing_or_paywalled_body_is_not_success(self):
        from stable.adapters.international import SCMPRacingAdapter
        from stable.services.news_content import ContentBlocked
        cases = [('<article><p>Recommendation</p></article>', 'selector_not_found'),
                 ('<div class="article-body">One</div><div class="article-body">Two</div>', 'selector_not_found'),
                 ('<div class="article-body"><p>Preview</p><div class="paywall">Subscribe to continue</div></div>', 'body_access_restricted')]
        for markup, status in cases:
            with self.subTest(status=status):
                detail = self.detail(SCMPRacingAdapter(), '<h1>Title</h1>' + markup)
                self.assertEqual(detail.body_ja_raw, '')
                self.assertEqual(detail.metadata['body_parse_status'], status)
                with self.assertRaises(ContentBlocked):
                    clean_source({'source_site': 'scmp_racing', 'title': 'Title', 'html': markup})

    def test_hkjc_author_date_is_hong_kong_time_not_dropdown_date(self):
        from stable.adapters.international import HKJCRacingNewsAdapter
        from datetime import datetime, timezone
        adapter = HKJCRacingNewsAdapter()
        detail = self.detail(adapter, '<h1>Title</h1><div class="dropdown-news-date">28/10/2026</div><p class="horses-racing-news-author">By Author<br>27/10/2026 14:49</p><div class="horses-racing-news-content"><p>Body</p></div>')
        self.assertEqual(detail.published_at, datetime(2026, 10, 27, 6, 49, tzinfo=timezone.utc))
        self.assertTrue(self.draft(adapter, detail).metadata['published_at_verified'])
        self.assertEqual(detail.metadata['published_at_evidence']['timezone'], 'Asia/Hong_Kong')

    def test_jsonld_uses_current_article_publication_not_modified_or_related_date(self):
        import json
        from datetime import datetime, timezone
        from stable.adapters.international import SportingLifeAdapter, SkySportsRacingAdapter, TDNAdapter
        for adapter in (SportingLifeAdapter(), SkySportsRacingAdapter(), TDNAdapter()):
            url = adapter.base_url + 'sample'
            nodes = [ {'@type': 'NewsArticle', 'url': adapter.base_url + 'related', 'datePublished': '2026-10-27T00:00:00Z'},
                      {'@type': 'NewsArticle', 'mainEntityOfPage': {'@id': url}, 'datePublished': '2026-10-12T11:06:34.535Z', 'dateModified': '2026-10-27T10:00:00Z'} ]
            with self.subTest(source=adapter.source_site):
                detail = self.detail(adapter, '<h1>Title</h1><script type="application/ld+json">' + json.dumps({'@graph': nodes}) + '</script>', url)
                self.assertEqual(detail.published_at, datetime(2026, 10, 12, 11, 6, 34, 535000, tzinfo=timezone.utc))
                self.assertTrue(detail.metadata['published_at_verified'])
                self.assertIn('datePublished', detail.metadata['published_at_evidence']['selector'])

    def test_missing_or_invalid_date_explicitly_unverified(self):
        from stable.adapters.international import SportingLifeAdapter
        adapter = SportingLifeAdapter()
        for markup in ('', '<time datetime="2026-99-99T25:00">bad</time>', '<script type="application/ld+json">broken</script>', '<meta property="article:modified_time" content="2026-10-27T10:00:00Z">'):
            with self.subTest(markup=markup):
                draft = self.draft(adapter, self.detail(adapter, '<h1>Title</h1>' + markup))
                self.assertFalse(draft.metadata.get('published_at_verified', True))
                self.assertFalse(draft.metadata['published_at_evidence']['verified'])

    def test_date_only_is_not_minute_verified_and_local_timezone_obeys_dst(self):
        from datetime import datetime, timezone
        from stable.adapters.international import FranceGalopEnglishNewsAdapter, SportingLifeAdapter
        for adapter in (FranceGalopEnglishNewsAdapter(), SportingLifeAdapter()):
            with self.subTest(source=adapter.source_site):
                detail = self.detail(adapter, '<h1>Title</h1><time datetime="2026-07-12">12 July</time>')
                self.assertIsNotNone(detail.published_at)
                self.assertFalse(self.draft(adapter, detail).metadata['published_at_verified'])
                self.assertEqual(detail.metadata['published_at_evidence']['precision'], 'date')
        adapter = SportingLifeAdapter()
        detail = self.detail(adapter, '<h1>Title</h1><time datetime="2026-07-12T15:30:00">Date</time>')
        self.assertEqual(detail.published_at, datetime(2026, 7, 12, 14, 30, tzinfo=timezone.utc))

    def test_conflicting_current_article_dates_are_not_verified(self):
        from stable.adapters.international import SportingLifeAdapter
        adapter = SportingLifeAdapter()
        markup = '<script type="application/ld+json">[{"@type":"NewsArticle","url":"https://www.sportinglife.com/sample","datePublished":"2026-10-27T10:00:00Z"},{"@type":"NewsArticle","url":"https://www.sportinglife.com/sample","datePublished":"2026-10-26T10:00:00Z"}]</script>'
        draft = self.draft(adapter, self.detail(adapter, '<h1>Title</h1>' + markup))
        self.assertFalse(draft.metadata['published_at_verified'])
        self.assertEqual(draft.metadata['published_at_evidence']['reason'], 'conflicting_publication_dates')

    def test_sporting_life_wrapping_tile_links_and_deduplication(self):
        from stable.adapters.international import SportingLifeAdapter
        adapter = SportingLifeAdapter()
        html = '<a data-testid="article-link-primary" href="/racing/news/aintree-update/235068"><div><h2>Aintree update</h2><span>1h ago</span></div></a><a href="/racing/news/aintree-update/235068">Duplicate</a><a href="/racing/news">News</a><a href="https://evil.invalid/racing/news/injected/1">Bad</a>'
        stubs = adapter.parse_listing_html(html, url=adapter.listing_url(1), mode='latest')
        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].title_ja, 'Aintree update')
        self.assertFalse(stubs[0].metadata.get('published_at_verified', True))

    def test_sporting_life_empty_or_unrecognized_list_is_failure(self):
        from stable.adapters.international import SportingLifeAdapter
        adapter = SportingLifeAdapter()
        for html in ('<html>Challenge page</html>', '<a href="/racing/news">News</a>'):
            with self.subTest(html=html), self.assertRaisesRegex(ValueError, 'listing_no_candidates'):
                adapter.parse_listing_html(html, url=adapter.listing_url(1))

    def test_tdn_region_is_article_evidence_not_discovery_configuration(self):
        from stable.adapters.international import TDNAdapter, TDNFranceBroadKeywordAdapter
        cases = [('Post Five For Forever Young In Breeders\' Cup Classic', 'The draw is at Del Mar.', 'united_states'),
                 ('Slightly Set for Dundalk Debut', 'The race takes place in Ireland.', 'other'),
                 ('Arqana announces November sale', 'The auction takes place in Deauville.', 'france'),
                 ('A new appointment', 'Details are pending.', 'other')]
        for adapter in (TDNAdapter(), TDNFranceBroadKeywordAdapter()):
            for title, body, region in cases:
                with self.subTest(source=adapter.source_site, title=title):
                    detail = self.detail(adapter, '<h1>' + title + '</h1><div class="entry-content"><p>' + body + '</p></div>')
                    draft = self.draft(adapter, detail)
                    self.assertEqual(draft.racing_region, region)
                    self.assertTrue(draft.metadata['region_evidence']['reason'])
                    self.assertNotEqual(draft.metadata['region_evidence']['reason'], 'source_region')

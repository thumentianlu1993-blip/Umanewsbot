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
        detail = self.detail(adapter, '<h1>Title</h1><div class="dropdown-news-date">28/10/2026</div><div class="content-news-list"><div class="horses-racing-news-title-header"><p class="horses-racing-news-author">By Author<br>27/10/2026 14:49</p></div><div class="horses-racing-news-content"><p>Body</p></div></div>')
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
                detail = self.detail(adapter, '<h1>Title</h1><script type="application/ld+json">{"@type":"Article","headline":"Title","datePublished":"2026-07-12"}</script>')
                self.assertIsNotNone(detail.published_at)
                self.assertFalse(self.draft(adapter, detail).metadata['published_at_verified'])
                self.assertEqual(detail.metadata['published_at_evidence']['precision'], 'date')
        adapter = SportingLifeAdapter()
        detail = self.detail(adapter, '<h1>Title</h1><script type="application/ld+json">{"@type":"Article","headline":"Title","datePublished":"2026-07-12T15:30:00"}</script>')
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


from django.test import TestCase, override_settings


@override_settings(NEWS_QUALITY_MODE='off', MULTIREGION_ATTRIBUTION_MODE='enforce', MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE='new_articles')
class InternationalSourceIngestionTests(TestCase):
    def test_tdn_unknown_region_stays_reviewable_and_manual_lock_survives_refetch(self):
        from stable.adapters.international import TDNAdapter
        from stable.models import NewsSource, AttributionStatus
        from stable.services.ingestion import upsert_article_from_draft
        from django.utils import timezone
        source = NewsSource.objects.create(name='TEST source', source_site='tdn', source_mode='latest', racing_region='united_states', adapter_key='tdn')
        adapter = TDNAdapter()
        stub = SourceArticleStub('tdn', 'latest', 'TEST-unknown', 'https://www.thoroughbreddailynews.com/unknown/', 'A new appointment', timezone.now())
        detail = adapter.parse_detail_html('<h1>A new appointment</h1><div class="entry-content"><p>Details are pending.</p></div>', url=stub.source_url)
        draft = adapter.normalize_source_payload(stub, detail)
        with patch('stable.services.ingestion.find_builtin_source', return_value=source):
            article = upsert_article_from_draft(draft).article
            article.refresh_from_db()
            self.assertEqual(article.racing_region, 'other')
            self.assertEqual(article.attribution_status, AttributionStatus.NEEDS_REVIEW)
            self.assertIn('region_evidence', article.translation_metadata)
            article.attribution_locked = True
            article.racing_region = 'france'
            article.save()
            article = upsert_article_from_draft(draft).article
            self.assertEqual(article.racing_region, 'france')

    def test_verified_detail_time_and_body_survive_ingestion_and_snapshot(self):
        from stable.adapters.international import SCMPRacingAdapter
        from stable.services.ingestion import upsert_article_from_draft
        from stable.services.news_pipeline import source_snapshot
        from django.utils import timezone
        adapter = SCMPRacingAdapter()
        url = 'https://www.scmp.com/sport/racing/article/1/sample'
        stub = SourceArticleStub('scmp_racing', 'latest', 'TEST-1', url, 'Title', timezone.now())
        html = '<h1>Title</h1><script type="application/ld+json">{"@type":"NewsArticle","url":"' + url + '","datePublished":"2026-10-27T19:35:21+08:00"}</script><article><p>Wrong</p></article><div class="article-body"><p>Correct body.</p></div>'
        detail = adapter.parse_detail_html(html, url=url)
        with patch('stable.services.ingestion.find_builtin_source', return_value=None):
            article = upsert_article_from_draft(adapter.normalize_source_payload(stub, detail)).article
        snapshot = source_snapshot(article)
        self.assertEqual(snapshot['body'], 'Correct body.')
        self.assertEqual(snapshot['source_time'], '2026-10-27T11:35:21+00:00')
        self.assertTrue(snapshot['time_verified'])
        self.assertEqual(snapshot['time_evidence']['selector'], 'jsonld:datePublished')


class SourceReviewBoundaryTests(SimpleTestCase):
    def test_modified_recommended_or_unscoped_time_is_not_verified(self):
        from stable.adapters.international import SportingLifeAdapter
        from datetime import datetime, timezone
        adapter = SportingLifeAdapter()
        url = 'https://www.sportinglife.com/racing/news/sample/123'
        stub = SourceArticleStub('sporting_life', 'latest', '123', url, 'Title', datetime(2026, 10, 27, tzinfo=timezone.utc))
        for markup in ('<time itemprop="dateModified" datetime="2026-10-27T10:00:00Z">Updated</time>',
                       '<div class="related-articles"><time datetime="2026-10-27T10:00:00Z">Other story</time></div>',
                       '<time datetime="2026-10-27T10:00:00Z">Unknown semantic</time>',
                       '<article class="article-card"><h2>Other story</h2><time itemprop="datePublished" datetime="2026-10-27T10:00:00Z">Other</time></article>'):
            with self.subTest(markup=markup):
                detail = adapter.parse_detail_html('<h1>Title</h1>' + markup, url=url)
                draft = adapter.normalize_source_payload(stub, detail)
                self.assertFalse(draft.metadata['published_at_verified'])
                self.assertIsNone(detail.published_at)

    def test_scmp_root_access_markers_block_both_paths(self):
        from stable.adapters.international import SCMPRacingAdapter
        from stable.services.news_content import ContentBlocked
        for attrs in ('class="article-body" data-paywall="true"', 'class="article-body paywall"', 'class="article-body subscription-required"'):
            with self.subTest(attrs=attrs):
                html = '<h1>Title</h1><div ' + attrs + '><p>Preview</p></div>'
                detail = SCMPRacingAdapter().parse_detail_html(html, url='https://www.scmp.com/sport/racing/article/1/test')
                self.assertEqual(detail.metadata['body_parse_status'], 'body_access_restricted')
                self.assertFalse(detail.body_ja_raw)
                with self.assertRaisesRegex(ContentBlocked, 'body_access_restricted'):
                    clean_source({'source_site': 'scmp_racing', 'title': 'Title', 'html': html})


class SourceRegionRolloutProtectionTests(TestCase):
    @override_settings(NEWS_QUALITY_MODE='off')
    def test_existing_region_and_applied_links_survive_off_shadow_and_new_only(self):
        from stable.adapters.international import TDNAdapter
        from stable.models import NewsSource, NewsArticle, NewsArticleRelatedRegion
        from stable.services.ingestion import upsert_article_from_draft
        from django.utils import timezone
        source = NewsSource.objects.create(name='TEST source', source_site='tdn', source_mode='latest', racing_region='united_states', adapter_key='tdn')
        adapter = TDNAdapter()
        for mode in ('off', 'shadow', 'enforce'):
            with self.subTest(mode=mode), override_settings(MULTIREGION_ATTRIBUTION_MODE=mode, MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE='new_articles'):
                url = 'https://www.thoroughbreddailynews.com/test-' + mode + '/'
                applied = {'primary_region': 'united_states', 'reason': 'prior_approved', 'related_regions': ['japan']}
                article = NewsArticle.objects.create(source_site='tdn', source_mode='latest', source_article_id='TEST-' + mode,
                    source_config=source, source_url=url, title_ja='Old title', body_ja_raw='Old body', body_ja_normalized='Old body',
                    racing_region='united_states', source_language='en', published_at=timezone.now(), attribution_summary={'applied': applied}, attribution_status='applied')
                NewsArticleRelatedRegion.objects.create(article=article, region='japan', source='manual', is_manual=True)
                stub = SourceArticleStub('tdn', 'latest', article.source_article_id, url, 'France Galop update', timezone.now())
                detail = adapter.parse_detail_html('<h1>France Galop update</h1><div class="entry-content"><p>New programme in France.</p></div>', url=url)
                draft = adapter.normalize_source_payload(stub, detail)
                with patch('stable.services.ingestion.find_builtin_source', return_value=source):
                    upsert_article_from_draft(draft)
                article.refresh_from_db()
                self.assertEqual(article.racing_region, 'united_states')
                self.assertEqual(article.attribution_summary['applied'], applied)
                self.assertEqual(list(article.related_region_links.values_list('region', flat=True)), ['japan'])

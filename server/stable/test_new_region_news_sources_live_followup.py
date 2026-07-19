from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone

from django.test import SimpleTestCase

from stable.adapters.base import SourceArticleStub
from stable.adapters.international import (
    IrishRacingNewsAdapter,
    RacingNSWNewsAdapter,
    RTERacingAdapter,
    SaudiPressAgencyHorseRacingAdapter,
    TasracingNewsAdapter,
)
from stable.management.commands.probe_international_news_sources import (
    _finalize_probe_contract,
)
from stable.models import RacingRegion, SourceSite
from stable.services.news_attribution import preview_content_scoped_region
from stable.services.source_permissions import (
    INTERNAL_ONLY_USAGE_SCOPE,
    SOURCE_PERMISSION_REGISTRY,
    TECHNICAL_ACCESS_ACCEPTED,
    TECHNICAL_ACCESS_BLOCKED,
)
from stable.services.sources import BUILTIN_SOURCE_DEFINITIONS


class LiveFollowupRegistryTests(SimpleTestCase):
    def test_probe_runtime_block_overrides_accepted_registry_preset(self):
        result = {
            "source": "rte_racing",
            "status": "deferred",
            "deferred_reason": "access_limited",
        }

        _finalize_probe_contract(result, RTERacingAdapter())

        self.assertEqual(result["technical_status"], TECHNICAL_ACCESS_BLOCKED)
        self.assertEqual(result["technical_access"], TECHNICAL_ACCESS_BLOCKED)
        self.assertEqual(result["effective_production_status"], "production_blocked")

    def test_confirmed_live_statuses_are_registered_fail_closed(self):
        accepted = {
            SourceSite.RTE_RACING,
            SourceSite.IRISHRACING_NEWS,
            SourceSite.DUBAI_RACING_CLUB,
            SourceSite.SPA_HORSE_RACING,
            SourceSite.JUST_HORSE_RACING,
            SourceSite.THE_STRAIGHT,
            SourceSite.RACING_NSW_NEWS,
            SourceSite.TASRACING_NEWS,
            SourceSite.JCSA_NEWS,
            SourceSite.RACING_VICTORIA_NEWS,
            SourceSite.BLOODHORSE,
            SourceSite.HORSE_RACING_NATION,
            SourceSite.SKY_SPORTS_RACING,
            SourceSite.SPORTING_LIFE,
            SourceSite.BHA,
            SourceSite.TDN,
        }
        blocked = {
            SourceSite.HRI_NEWS,
            SourceSite.WOODBINE_NEWS,
            SourceSite.EMIRATES_RACING_AUTHORITY,
            SourceSite.CANADIAN_THOROUGHBRED,
            SourceSite.ASSINIBOIA_DOWNS_NEWS,
            SourceSite.THE_NATIONAL_RACING,
            SourceSite.ARAB_NEWS_RACING,
            SourceSite.PAULICK_REPORT,
        }

        for source_site in accepted:
            with self.subTest(source_site=source_site, expected="accepted"):
                self.assertIn(source_site, SOURCE_PERMISSION_REGISTRY)
                if source_site not in SOURCE_PERMISSION_REGISTRY:
                    continue
                self.assertEqual(
                    SOURCE_PERMISSION_REGISTRY[source_site].technical_access,
                    TECHNICAL_ACCESS_ACCEPTED,
                )
        for source_site in blocked:
            with self.subTest(source_site=source_site, expected="blocked"):
                self.assertIn(source_site, SOURCE_PERMISSION_REGISTRY)
                if source_site not in SOURCE_PERMISSION_REGISTRY:
                    continue
                self.assertEqual(
                    SOURCE_PERMISSION_REGISTRY[source_site].technical_access,
                    TECHNICAL_ACCESS_BLOCKED,
                )

        for source_site, record in SOURCE_PERMISSION_REGISTRY.items():
            with self.subTest(source_site=source_site, contract="internal_only"):
                self.assertEqual(record.usage_scope, INTERNAL_ONLY_USAGE_SCOPE)
                self.assertIs(record.public_publish_allowed, False)


class LiveFollowupCurrentStructureFixtureTests(SimpleTestCase):
    @staticmethod
    def _rss_stub(adapter, *, url: str, title: str) -> SourceArticleStub:
        published_at = datetime(2026, 7, 20, 0, 30, tzinfo=dt_timezone.utc)
        return SourceArticleStub(
            source_site=adapter.source_site,
            source_mode=adapter.source_mode,
            source_article_id=adapter._article_id(url),
            source_url=url,
            title_ja=title,
            published_at=published_at,
            metadata={
                "published_at_verified": True,
                "published_at_evidence": {
                    "source": "rss",
                    "raw": "Mon, 20 Jul 2026 00:30:00 +0000",
                    "timezone": adapter.local_timezone,
                    "precision": "second",
                    "parser_version": adapter.parser_version,
                    "verified": True,
                },
            },
        )

    def test_irishracing_current_listing_and_detail_structure(self):
        adapter = IrishRacingNewsAdapter()
        listing = """
        <div class="row clrbox newsitemdate">Sun 19th Jul 2026</div>
        <div class="row clrbox newitemrow">
          <div class="news-item hiliterow">
            <a href="/news/fixture-story/266070">
              <h4>Curragh fixture report</h4>
            </a>
            <p class="news-stamp"><em>5:15pm</em></p>
          </div>
        </div>
        """

        stubs = adapter.parse_listing_html(
            listing,
            url="https://www.irishracing.com/news",
            mode=adapter.source_mode,
        )

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].title_ja, "Curragh fixture report")
        self.assertEqual(
            stubs[0].published_at.isoformat(),
            "2026-07-19T16:15:00+00:00",
        )
        detail = adapter.parse_detail_html(
            """
            <html><head>
              <meta property="og:title" content="Curragh fixture report">
              <meta property="article:published_time"
                    content="2026-07-19T17:15:00+01:00">
            </head><body>
              <div id="reportbody">
                <p>Stable synthetic racing paragraph for parser coverage.</p>
              </div>
            </body></html>
            """,
            url=stubs[0].source_url,
        )
        draft = adapter.normalize_source_payload(stubs[0], detail)
        self.assertIn("synthetic racing paragraph", draft.body_ja_normalized)

    def test_spa_current_search_api_and_detail_payload(self):
        adapter = SaudiPressAgencyHorseRacingAdapter()
        listing_payload = json.dumps(
            {
                "data": [
                    {
                        "uuid": "abc123def0",
                        "sharable_link": "spa.gov.sa/en/abc123def0",
                        "title": "Saudi Cup horse racing update",
                        "content": "Horse racing at King Abdulaziz Racecourse.",
                        "published_at": 1784505600,
                        "locale": "en",
                    },
                    {
                        "uuid": "camel00001",
                        "sharable_link": "spa.gov.sa/en/camel00001",
                        "title": "Camel festival update",
                        "content": "Camel event.",
                        "published_at": 1784505600,
                        "locale": "en",
                    },
                ],
                "pagination": {"total": 2},
                "message": "success",
            }
        )

        try:
            stubs = adapter.parse_listing_html(
                listing_payload,
                url=(
                    "https://portalapi.spa.gov.sa/api/v1/news/search"
                    "?title=horse%20racing&exact_search=0&by_latest=0"
                    "&start=0&rows=10&l=en"
                ),
                mode=adapter.source_mode,
            )
        except ValueError:
            stubs = []

        self.assertEqual(len(stubs), 1)
        self.assertEqual(
            stubs[0].source_url,
            "https://www.spa.gov.sa/en/abc123def0",
        )
        self.assertTrue(adapter._topic_allowed("", stubs[0].source_url))
        detail_payload = {
            "props": {
                "pageProps": {
                    "newsDetails": {
                        "uuid": "abc123def0",
                        "title": "Saudi Cup horse racing update",
                        "content": (
                            "<p>Stable synthetic Saudi racing body.</p>"
                        ),
                        "published_at": 1784505600,
                    }
                }
            }
        }
        detail = adapter.parse_detail_html(
            (
                "<script id='__NEXT_DATA__' type='application/json'>"
                f"{json.dumps(detail_payload)}"
                "</script>"
            ),
            url=stubs[0].source_url,
        )
        draft = adapter.normalize_source_payload(stubs[0], detail)
        self.assertIn("synthetic Saudi racing body", draft.body_ja_normalized)
        self.assertEqual(
            draft.metadata["published_at_evidence"]["precision"],
            "second",
        )

    def test_racing_nsw_current_oxygen_body_structure(self):
        adapter = RacingNSWNewsAdapter()
        url = (
            "https://www.racingnsw.com.au/news/country-news/"
            "fixture-racing-report/"
        )
        stub = self._rss_stub(
            adapter,
            url=url,
            title="Fixture racing report",
        )

        detail = adapter.parse_detail_html(
            """
            <html><head>
              <meta property="og:title" content="Fixture racing report">
            </head><body>
              <div class="ct-inner-content">
                <div class="ct-code-block">
                  <p>Stable synthetic New South Wales racing body.</p>
                </div>
              </div>
            </body></html>
            """,
            url=url,
        )
        self.assertTrue(detail.body_ja_normalized)
        draft = adapter.normalize_source_payload(stub, detail)

        self.assertIn(
            "synthetic New South Wales racing body",
            draft.body_ja_normalized,
        )

    def test_racing_nsw_listing_excludes_tips_and_preview_items(self):
        adapter = RacingNSWNewsAdapter()
        listing = """
        <rss version="2.0"><channel>
          <item>
            <title>Neil Evans tips preview for Wagga Monday</title>
            <link>https://www.racingnsw.com.au/news/country-news/neil-evans-tips-preview-for-wagga-monday-2/</link>
            <guid>nsw-tips-preview</guid>
            <pubDate>Sun, 19 Jul 2026 16:30:00 +1000</pubDate>
          </item>
          <item>
            <title>Country championships programme confirmed</title>
            <link>https://www.racingnsw.com.au/news/country-news/country-championships-programme-confirmed/</link>
            <guid>nsw-country-news</guid>
            <pubDate>Sun, 19 Jul 2026 16:20:00 +1000</pubDate>
          </item>
        </channel></rss>
        """

        stubs = adapter.parse_listing_html(
            listing,
            url="https://www.racingnsw.com.au/feed/",
            mode=adapter.source_mode,
        )

        self.assertEqual(
            [stub.title_ja for stub in stubs],
            ["Country championships programme confirmed"],
        )

    def test_racing_nsw_normalization_rejects_tips_and_keeps_specific_rss_title(self):
        adapter = RacingNSWNewsAdapter()
        legitimate_url = (
            "https://www.racingnsw.com.au/news/country-news/"
            "country-championships-programme-confirmed/"
        )
        legitimate_stub = self._rss_stub(
            adapter,
            url=legitimate_url,
            title="Country championships programme confirmed",
        )
        generic_detail = adapter.parse_detail_html(
            """
            <html><head>
              <meta property="og:title" content="Latest News">
            </head><body>
              <div class="ct-inner-content">
                <div class="ct-code-block">
                  <p>Stable synthetic country championships body.</p>
                </div>
              </div>
            </body></html>
            """,
            url=legitimate_url,
        )

        with self.subTest(contract="generic_title_fallback"):
            draft = adapter.normalize_source_payload(
                legitimate_stub,
                generic_detail,
            )
            self.assertEqual(
                draft.title_ja,
                "Country championships programme confirmed",
            )

        tips_url = (
            "https://www.racingnsw.com.au/news/country-news/"
            "neil-evans-tips-preview-for-wagga-monday-2/"
        )
        tips_stub = self._rss_stub(
            adapter,
            url=tips_url,
            title="Neil Evans tips preview for Wagga Monday",
        )
        with self.subTest(contract="normalized_tips_filter"):
            with self.assertRaisesRegex(
                ValueError,
                "source_topic_filtered",
            ):
                adapter.normalize_source_payload(
                    tips_stub,
                    generic_detail,
                )

    def test_tasracing_current_hubspot_body_structure(self):
        adapter = TasracingNewsAdapter()
        url = "https://tasracing.com.au/news/fixture-thoroughbred-report"
        stub = self._rss_stub(
            adapter,
            url=url,
            title="Tasmanian thoroughbred fixture report",
        )

        detail = adapter.parse_detail_html(
            """
            <html><body>
              <main id="main-content">
                <div class="single-blog-body news">
                  <h2>Tasmanian thoroughbred fixture report</h2>
                  <div class="blog-content reveal">
                    <p>Stable synthetic thoroughbred racing body.</p>
                  </div>
                </div>
              </main>
            </body></html>
            """,
            url=url,
        )
        self.assertTrue(detail.body_ja_normalized)
        draft = adapter.normalize_source_payload(stub, detail)

        self.assertIn(
            "synthetic thoroughbred racing body",
            draft.body_ja_normalized,
        )


class LiveFollowupDefinitionAndPreviewTests(SimpleTestCase):
    THIRD_BATCH_ADAPTER_KEYS = {
        "rte_racing",
        "irishracing_news",
        "canadian_thoroughbred",
        "assiniboia_downs_news",
        "dubai_racing_club",
        "the_national_racing",
        "spa_horse_racing",
        "arab_news_racing",
        "just_horse_racing",
        "the_straight",
        "racing_nsw_news",
        "tasracing_news",
    }

    def test_third_batch_definitions_remain_disabled_and_unapproved(self):
        definitions = {
            str(item["adapter_key"]): item
            for item in BUILTIN_SOURCE_DEFINITIONS
            if str(item.get("adapter_key") or "") in self.THIRD_BATCH_ADAPTER_KEYS
        }

        self.assertEqual(set(definitions), self.THIRD_BATCH_ADAPTER_KEYS)
        for adapter_key, definition in definitions.items():
            with self.subTest(adapter_key=adapter_key):
                self.assertIs(definition["enabled"], False)
                self.assertIs(definition["production_approved"], False)

    def test_aggregate_preview_uses_strong_signals_or_source_fallback(self):
        cases = (
            (
                "Curragh confirms Irish Oaks field",
                "The classic will be staged at the Curragh.",
                RacingRegion.UNITED_KINGDOM,
                RacingRegion.IRELAND,
            ),
            (
                "Woodbine updates Canadian runners",
                "The field assembles at Woodbine.",
                RacingRegion.UNITED_STATES,
                RacingRegion.CANADA,
            ),
            (
                "Stable reports a routine training update",
                "No racecourse or country signal is present.",
                RacingRegion.UNITED_KINGDOM,
                RacingRegion.UNITED_KINGDOM,
            ),
        )

        for title, lead, source_region, expected_region in cases:
            with self.subTest(title=title):
                preview = preview_content_scoped_region(
                    title=title,
                    lead=lead,
                    source_region=source_region,
                )
                self.assertEqual(preview.primary_region, expected_region)

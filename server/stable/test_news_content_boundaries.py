from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from stable.adapters.base import CanonicalNewsDraft, SourceArticleDetail, SourceArticleStub
from stable.adapters.international import (
    HorseRacingNationAdapter,
    SponichiAdapter,
    SportingLifeAdapter,
    TDNAdapter,
)
from stable.models import (
    ArticleTranslationStatus,
    CrawlJob,
    NewsArticle,
    NewsSnapshot,
    NewsSource,
    OperationLog,
    PublishedByMode,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TaskStatus,
    WorkflowStatus,
)
from stable.services.sources import sync_builtin_sources
from stable.services.translation import OpenAICompatibleTranslationProvider
from stable.tasks import _crawl_international_source, translate_article_task


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "news_content_boundaries"


def fixture_html(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


class InternationalNewsContentBoundaryTests(TestCase):
    def test_hrn_removes_role_dialog_without_clipping_surrounding_article_blocks(self):
        detail = HorseRacingNationAdapter().parse_detail_html(
            fixture_html("hrn_race_video_dialog.html"),
            url="https://www.horseracingnation.com/news/saratoga_race_preview_123",
        )

        self.assertEqual(detail.metadata["body_parse_status"], "ok")
        self.assertEqual(detail.metadata["body_selector"], ".article-body")
        self.assertNotIn("Last race replay", detail.body_ja_raw)
        self.assertNotIn("modal-title", detail.body_ja_raw)

        expected_blocks = (
            "The opening paragraph explains why the favorite has improved.",
            "Race shape",
            "Race Video is also the name of a legitimate section discussed in this sentence.",
            "The inside runner should press the pace.",
            "The closer needs a clean trip.",
            "Post",
            "Patient Runner",
            "The rider said the colt is ready for the assignment.",
            "The 3 × 2 exercise was completed before the final paragraph confirmed the plan.",
        )
        positions = [detail.body_ja_raw.index(block) for block in expected_blocks]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(detail.body_ja_raw.count("Race Video"), 1)
        self.assertIn("3 × 2 exercise", detail.body_ja_raw)
        self.assertEqual(
            detail.metadata["body_cleaning"]["removed_rules"]["hrn_structured_noise"],
            1,
        )

    def test_non_hrn_role_dialog_is_not_removed_by_hrn_specific_rule(self):
        detail = TDNAdapter().parse_detail_html(
            """
            <html><head><meta property="og:title" content="Dialog semantics in an article"></head>
            <body><article>
              <p>The first paragraph remains.</p>
              <div role="dialog"><p>Quoted dialog belongs to this non-HRN source.</p></div>
              <p>The final paragraph remains.</p>
            </article></body></html>
            """,
            url="https://www.thoroughbreddailynews.com/dialog-semantics/",
        )

        self.assertIn("Quoted dialog belongs to this non-HRN source.", detail.body_ja_raw)
        self.assertNotIn(
            "hrn_structured_noise",
            detail.metadata["body_cleaning"]["removed_rules"],
        )

    def test_hrn_9623_extracts_only_trusted_article_body(self):
        detail = HorseRacingNationAdapter().parse_detail_html(
            fixture_html("hrn_9623.html"),
            url=(
                "https://www.horseracingnation.com/news/"
                "Sire_profile_Pavel_is_a_surprising_summer_success_story_123"
            ),
        )

        self.assertEqual(detail.metadata["body_parse_status"], "ok")
        self.assertEqual(detail.metadata["body_selector"], ".article-body")
        self.assertTrue(detail.body_ja_raw.startswith("Pavel's first runners"))
        self.assertTrue(detail.body_ja_raw.endswith("autumn racing begins."))
        for framework_text in (
            "Trending",
            "CCA Oaks analysis",
            "Head to head",
            "Log in",
            "Sign up for free",
            "By Horse Racing Nation staff",
            "Related Pages",
            "Top Stories",
        ):
            self.assertNotIn(framework_text, detail.body_ja_raw)

    def test_hrn_preserves_legitimate_structure_and_same_word_facts_in_dom_order(self):
        detail = HorseRacingNationAdapter().parse_detail_html(
            fixture_html("hrn_9623.html"),
            url="https://www.horseracingnation.com/news/example_123",
        )
        ordered_text = (
            "Pavel's first runners",
            "A patient route to stud",
            "The young horses have shown speed",
            "Three juveniles won on dirt",
            "Two more placed on turf",
            "Runner",
            "Summer Promise",
            "First",
            "Fair odds were available before the race",
            "owners can sign up for the yearling inspection",
            "The next crop will be watched closely",
        )

        positions = [detail.body_ja_raw.index(text) for text in ordered_text]
        self.assertEqual(positions, sorted(positions))

    def test_hrn_missing_trusted_container_fails_closed_without_main_fallback(self):
        detail = HorseRacingNationAdapter().parse_detail_html(
            """
            <html><head><meta property="og:title" content="Layout drift"></head><body>
              <main><div class="ticker">Trending</div><a href="/login">Log in</a></main>
            </body></html>
            """,
            url="https://www.horseracingnation.com/news/layout_drift_123",
        )

        self.assertEqual(detail.body_ja_raw, "")
        self.assertEqual(detail.body_ja_normalized, "")
        self.assertEqual(detail.metadata["body_parse_status"], "selector_not_found")
        self.assertEqual(detail.metadata["body_selector"], "")

    def test_hrn_normal_article_counterexample_keeps_complete_first_and_last_blocks(self):
        detail = HorseRacingNationAdapter().parse_detail_html(
            fixture_html("hrn_normal_article.html"),
            url="https://www.horseracingnation.com/news/autumn_campaign_123",
        )

        self.assertTrue(detail.body_ja_raw.startswith("The trainer opened the season"))
        self.assertIn("The next target", detail.body_ja_raw)
        self.assertIn("We will let the horse tell us", detail.body_ja_raw)
        self.assertIn("A quiet week at the farm", detail.body_ja_raw)
        self.assertIn("One final breeze before entry day", detail.body_ja_raw)
        self.assertTrue(detail.body_ja_raw.endswith("full campaign remains intact."))

    def test_hrn_clean_body_is_the_translation_prompt_source(self):
        detail = HorseRacingNationAdapter().parse_detail_html(
            fixture_html("hrn_9623.html"),
            url="https://www.horseracingnation.com/news/example_123",
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.HORSE_RACING_NATION,
            source_mode=SourceMode.LATEST,
            source_article_id="hrn-translation-input",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            title_ja=detail.title_ja,
            body_ja_raw=detail.body_ja_raw,
            body_ja_normalized=detail.body_ja_normalized,
            original_content_html=detail.original_content_html,
            published_at=timezone.now(),
            source_url="https://www.horseracingnation.com/news/example_123",
        )
        prompt = OpenAICompatibleTranslationProvider(
            api_key="test",
            base_url="https://example.com/v1",
        )._build_prompt(article, [], [])

        self.assertIn("Pavel's first runners", prompt)
        self.assertIn("The next crop will be watched closely", prompt)
        self.assertNotIn("Related Pages", prompt)
        self.assertNotIn("Sign up for free", prompt)

    def test_sponichi_extracts_component_title_and_body_without_page_shell(self):
        detail = SponichiAdapter().parse_detail_html(
            """
            <html><head>
              <meta property="og:title" content="浜中 武豊の快挙に花 - スポニチ Sponichi Annex ギャンブル">
            </head><body><main><article>
              <header data-component="article-header">
                <div class="copyright-link">スポニチアネックス取材班</div>
                <h1 class="heading">浜中 武豊の快挙に花</h1>
                <p data-component="date-format">[ 2026年7月13日 05:30 ]</p>
              </header>
              <div data-component="article-body">
                <figure><img src="photo.webp"><figcaption>記念うちわ Photo By スポニチ</figcaption></figure>
                <!-- google_ad_section_start(name=s1) -->
                <!-- 前文 -->
                <p>武豊を祝うため、浜中俊は特製うちわを用意していた。</p>
                <p>浜中は「ちょっと気まずかったです」と笑った。</p>
                <p>浦和競馬の出走表とスポニチ予想がコンビニ各社で1枚200円で販売中。詳しくはhttps://www.e-printservice.net/content_detail/spopriへ。</p>
                <!-- google_ad_section_end(name=s1) -->
                <div id="article_more_area"><a href="/articles/full.html">続きを表示</a></div>
                <div id="login_article_more_area">ログインして続きを読む</div>
              </div>
              <div data-component="article-links">スポニチ記者の予想が最大3か月無料！</div>
              <section>ギャンブルのニュース ニュース一覧を見る</section>
            </article></main></body></html>
            """,
            url="https://www.sponichi.co.jp/gamble/news/2026/07/13/kiji/example.html",
        )

        self.assertEqual(detail.title_ja, "浜中 武豊の快挙に花")
        self.assertIn("特製うちわを用意", detail.body_ja_raw)
        self.assertIn("ちょっと気まずかった", detail.body_ja_raw)
        self.assertNotIn("Sponichi Annex", detail.title_ja)
        self.assertNotIn("ギャンブル", detail.title_ja)
        self.assertNotIn("Photo By", detail.body_ja_raw)
        self.assertNotIn("google_ad_section", detail.body_ja_raw)
        self.assertNotIn("前文", detail.body_ja_raw)
        self.assertNotIn("スポニチ予想", detail.body_ja_raw)
        self.assertNotIn("e-printservice.net", detail.body_ja_raw)
        self.assertNotIn("続きを表示", detail.body_ja_raw)
        self.assertNotIn("ログインして続きを読む", detail.body_ja_raw)
        self.assertNotIn("スポニチ記者の予想", detail.body_ja_raw)
        self.assertNotIn("ニュース一覧", detail.body_ja_raw)
        self.assertEqual(detail.metadata["body_selector"], "[data-component='article-body']")
        self.assertEqual(
            detail.metadata["body_cleaning"]["removed_rules"]["sponichi_structured_noise"],
            3,
        )

    def test_sponichi_listing_rejects_boatrace_substring_and_keeps_horse_racing(self):
        stubs = SponichiAdapter().parse_listing_html(
            """
            <ul class="tab-contents">
              <li><a href="/gamble/news/2026/07/13/kiji/20260713s00053000001000c.html">【津ボート BOATRACE】地元3Vへ真っ向勝負</a></li>
              <li><a href="/gamble/news/2026/07/13/kiji/20260713s00004000002000c.html">イクイノックス産駒が落札</a></li>
              <li><a href="/gamble/news/2026/07/13/kiji/20260713s00004200003000c.html">【次走】ルガル、スプリンターズSへ</a></li>
              <li><a href="/gamble/news/2026/07/13/kiji/20260713b00004000004000c.html">【動画】豪華な誘導馬が登場</a></li>
            </ul>
            """,
            url="https://www.sponichi.co.jp/gamble/",
            mode=SourceMode.LATEST,
        )

        self.assertEqual(len(stubs), 3)
        self.assertTrue(all("s00053" not in stub.source_url for stub in stubs))
        self.assertEqual(
            {stub.source_url.split("/")[-1][8:15] for stub in stubs},
            {"s000040", "s000042", "b000040"},
        )

    def test_sporting_life_8086_extracts_only_real_article_body(self):
        detail = SportingLifeAdapter().parse_detail_html(
            fixture_html("sporting_life_8086.html"),
            url="https://www.sportinglife.com/racing/news/david-ord-tribute-to-graham-bradley/233144",
        )

        self.assertIn("Graham Bradley always had time", detail.body_ja_raw)
        self.assertIn("the years roll on", detail.body_ja_raw)
        self.assertIn("Graham Bradley celebrates at Cheltenham", detail.body_ja_raw)
        self.assertNotIn("Fast Results", detail.body_ja_raw)
        self.assertNotIn("Premium banner", detail.body_ja_raw)
        self.assertNotIn("Share Tweet", detail.body_ja_raw)
        self.assertNotIn("Safer Gambling", detail.body_ja_raw)
        self.assertEqual(detail.metadata["body_parse_status"], "ok")
        self.assertIn("Article__ArticleBody", detail.metadata["body_selector"])

    def test_sporting_life_removes_production_social_button_component(self):
        detail = SportingLifeAdapter().parse_detail_html(
            """<html><head><meta property="og:title" content="Tribute"></head><body>
            <div class="Article__ArticleBody-sc-production"><p>Real tribute body.</p>
            <div class="ArticleSocialMediaButtons__StyledInnerContainer-sc-production"><div>Share</div><div>Tweet</div><div>Email</div></div></div>
            </body></html>""",
            url="https://www.sportinglife.com/racing/news/tribute/233144",
        )

        self.assertEqual(detail.body_ja_raw, "Real tribute body.")
        self.assertEqual(detail.metadata["body_cleaning"]["removed_rules"]["structured_noise"], 1)

    def test_sporting_life_8267_removes_betting_noise_but_keeps_exceptions(self):
        detail = SportingLifeAdapter().parse_detail_html(
            fixture_html("sporting_life_8267.html"),
            url="https://www.sportinglife.com/racing/news/weather-set-fair-for-go-racing-in-yorkshire-summer-festival/233189",
        )

        self.assertIn("Sky Bet Go Racing In Yorkshire Summer Festival", detail.body_ja_raw)
        self.assertIn("Blue Horizon is 7/2", detail.body_ja_raw)
        self.assertIn("forecast is dry and warm", detail.body_ja_raw)
        self.assertIn("the popular summer festival covers nine days", detail.body_ja_raw)
        self.assertIn("Friday July 24 – York Music Showcase", detail.body_ja_raw)
        self.assertNotIn("£100 charity bet", detail.body_ja_raw)
        self.assertNotIn("Charity Tipping Challenge", detail.body_ja_raw)
        self.assertNotIn("winning tipster", detail.body_ja_raw)
        self.assertNotIn("Backed by Sky Bet", detail.body_ja_raw)
        self.assertNotIn("BOOK NOW", detail.body_ja_raw)
        self.assertNotIn("claim £30 in free bets", detail.body_ja_raw)
        self.assertNotIn("More from Sporting Life", detail.body_ja_raw)
        self.assertNotIn("gambling problem", detail.body_ja_raw)
        self.assertGreaterEqual(detail.metadata["body_cleaning"]["removed_count"], 3)
        self.assertIn("betting_promotion", detail.metadata["body_cleaning"]["removed_rules"])

    def test_schedule_translation_line_coverage_is_not_mistaken_for_truncation(self):
        provider = OpenAICompatibleTranslationProvider(api_key="test", base_url="https://example.com/v1")
        source = "\n\n".join(
            [
                "The festival returns this week.",
                "The programme runs for nine days.",
                "Full list of racecourses and dates",
                *[
                    f"Friday July {day} - Racecourse {day} family programme with live music and a full afternoon card"
                    for day in range(17, 27)
                ],
            ]
        )
        complete = "\n".join(
            [
                "赛马节本周回归，活动为期九天。",
                "完整赛马场及日期列表：",
                *[f"7月{day}日周五 - 第{day}赛马场" for day in range(17, 27)],
            ]
        )

        self.assertFalse(provider._looks_incomplete(source, complete))

    def test_schedule_translation_missing_tail_lines_is_still_incomplete(self):
        provider = OpenAICompatibleTranslationProvider(api_key="test", base_url="https://example.com/v1")
        source = "\n\n".join(
            [
                "The festival returns this week.",
                "The programme runs for nine days.",
                "Full list of racecourses and dates",
                *[
                    f"Friday July {day} - Racecourse {day} family programme with live music and a full afternoon card"
                    for day in range(17, 27)
                ],
            ]
        )
        truncated = "\n".join(
            [
                "赛马节本周回归。",
                "完整赛马场及日期列表：",
                *[f"7月{day}日周五 - 第{day}赛马场" for day in range(17, 21)],
            ]
        )

        self.assertTrue(provider._looks_incomplete(source, truncated))

    def test_sporting_life_minified_sibling_blocks_are_cleaned_independently(self):
        detail = SportingLifeAdapter().parse_detail_html(
            """<html><head><meta property="og:title" content="Festival preview"></head><body>
            <div class="Article__ArticleBody-sc-production-8267"><div>
            <p>The Sky Bet Go Racing In Yorkshire Summer Festival returns this week.</p><p>Blue Horizon is 7/2 for the feature race.</p><p>Each person is given a £100 charity bet for the meeting.</p><h2>More from Sporting Life</h2><p>Free bets and safer gambling.</p>
            </div></div></body></html>""",
            url="https://www.sportinglife.com/racing/news/festival-preview/233189",
        )

        self.assertEqual(detail.metadata["body_parse_status"], "ok")
        self.assertIn("Sky Bet Go Racing In Yorkshire Summer Festival", detail.body_ja_raw)
        self.assertIn("Blue Horizon is 7/2", detail.body_ja_raw)
        self.assertNotIn("charity bet", detail.body_ja_raw)
        self.assertNotIn("More from Sporting Life", detail.body_ja_raw)
        self.assertNotIn("Free bets", detail.body_ja_raw)

    def test_sporting_life_removes_standalone_bookmaker_redirect_url(self):
        detail = SportingLifeAdapter().parse_detail_html(
            """<html><head><meta property="og:title" content="Oaks preview"></head><body>
            <div class="Article__ArticleBody-sc-production"><p>The Sky Bet Oaks favourite is 7/2.</p>
            <p>The trainer expects her to stay the trip.</p>
            <a href="https://ads.skybet.com/redirect.aspx?pid=123">https://ads.skybet.com/redirect.aspx?pid=123</a></div>
            </body></html>""",
            url="https://www.sportinglife.com/racing/news/oaks-preview/233195",
        )

        self.assertIn("Sky Bet Oaks favourite is 7/2", detail.body_ja_raw)
        self.assertIn("expects her to stay the trip", detail.body_ja_raw)
        self.assertNotIn("ads.skybet.com", detail.body_ja_raw)
        self.assertEqual(detail.metadata["body_cleaning"]["removed_rules"]["standalone_url"], 1)

    def test_tdn_8316_removes_results_cta_and_tail(self):
        detail = TDNAdapter().parse_detail_html(
            fixture_html("tdn_8316.html"),
            url="https://www.thoroughbreddailynews.com/charity-event/",
        )

        self.assertIn("event brought together owners", detail.body_ja_raw)
        self.assertIn("programme will return next year", detail.body_ja_raw)
        self.assertNotIn("complete list of results", detail.body_ja_raw)
        self.assertNotIn("Read Today's Paper", detail.body_ja_raw)
        self.assertIn("tdn_results_cta", detail.metadata["body_cleaning"]["removed_rules"])

    def test_tdn_8318_removes_leading_editor_note_and_link_only_paragraph(self):
        detail = TDNAdapter().parse_detail_html(
            fixture_html("tdn_8318.html"),
            url="https://www.thoroughbreddailynews.com/promising-juvenile/",
        )

        self.assertNotIn("Editor's Note", detail.body_ja_raw)
        self.assertNotIn("click here", detail.body_ja_raw)
        self.assertIn("more than enough time", detail.body_ja_raw)
        self.assertIn("paper trail in the formbook", detail.body_ja_raw)
        self.assertNotIn("Read Today's Paper", detail.body_ja_raw)

    def test_tdn_editor_note_link_without_click_here_is_removed(self):
        detail = TDNAdapter().parse_detail_html(
            """<html><head><meta property="og:title" content="Guild statement"></head><body>
            <span itemprop="articleBody"><p>Editor's Note: The following is an edited press release.</p><p>To view July 12 interview with the racing officials.</p><p>The Guild will continue its safety work.</p></span>
            </body></html>""",
            url="https://www.thoroughbreddailynews.com/guild-statement/",
        )

        self.assertEqual(detail.body_ja_raw, "The Guild will continue its safety work.")
        self.assertEqual(detail.metadata["body_cleaning"]["removed_rules"]["tdn_editor_note"], 1)
        self.assertEqual(detail.metadata["body_cleaning"]["removed_rules"]["tdn_leading_link"], 1)

    def test_tdn_strips_link_cta_sentences_but_keeps_event_facts(self):
        detail = TDNAdapter().parse_detail_html(
            """<html><head><meta property="og:title" content="Fund event"></head><body>
            <span itemprop="articleBody"><p>The silent auction closes at 9 p.m. To view auction items, click here.</p>
            <p>Tickets are available for $50, including the buffet and one drink.</p>
            <p>To purchase tickets, click here. To sign up as a sponsor, click here.</p></span>
            </body></html>""",
            url="https://www.thoroughbreddailynews.com/fund-event/",
        )

        self.assertIn("silent auction closes at 9 p.m.", detail.body_ja_raw)
        self.assertIn("Tickets are available for $50", detail.body_ja_raw)
        self.assertNotIn("click here", detail.body_ja_raw.lower())
        self.assertNotIn("sign up as a sponsor", detail.body_ja_raw.lower())
        self.assertEqual(detail.metadata["body_cleaning"]["removed_rules"]["link_cta"], 3)

    def test_missing_trusted_body_selector_never_falls_back_to_page_body(self):
        detail = SportingLifeAdapter().parse_detail_html(
            "<html><head><title>Navigation shell</title></head><body><nav>Fast Results</nav><footer>Terms</footer></body></html>",
            url="https://www.sportinglife.com/racing/news/layout-drift/999999",
        )

        self.assertEqual(detail.body_ja_raw, "")
        self.assertEqual(detail.body_ja_normalized, "")
        self.assertEqual(detail.metadata["body_parse_status"], "selector_not_found")
        self.assertNotIn("Fast Results", detail.body_ja_raw)

    def test_body_that_is_empty_after_cleaning_stays_empty(self):
        detail = TDNAdapter().parse_detail_html(
            """
            <html><body><span itemprop="articleBody">
              <p>Editor's Note: magazine-only introduction.</p>
              <p>Read Today's Paper</p>
            </span></body></html>
            """,
            url="https://www.thoroughbreddailynews.com/template-only/",
        )

        self.assertEqual(detail.body_ja_raw, "")
        self.assertEqual(detail.metadata["body_parse_status"], "empty_after_cleaning")

    def test_cleaning_metadata_is_a_summary_and_does_not_copy_html(self):
        html = fixture_html("tdn_8316.html")
        adapter = TDNAdapter()
        detail = adapter.parse_detail_html(html, url="https://www.thoroughbreddailynews.com/charity-event/")
        serialized_metadata = json.dumps(detail.metadata)

        self.assertEqual(detail.original_content_html, html)
        self.assertNotIn("<!doctype html>", serialized_metadata)
        self.assertNotIn("original_content_html", detail.metadata)
        self.assertIsInstance(detail.metadata["body_cleaning"]["removed_rules"], dict)


@override_settings(AUTO_TRANSLATE_ON_INGEST=True, AUTO_TRANSLATE_SYNC=True, TERM_DISCOVERY_ENABLED=True)
class InternationalNewsBodyParseGateTests(TestCase):
    def setUp(self):
        sync_builtin_sources()
        self.source = NewsSource.objects.get(
            source_site=SourceSite.HORSE_RACING_NATION,
            source_mode=SourceMode.LATEST,
        )

    def _stub(self, suffix: str) -> SourceArticleStub:
        return SourceArticleStub(
            source_site=SourceSite.HORSE_RACING_NATION,
            source_mode=SourceMode.LATEST,
            source_article_id=f"hrn-{suffix}",
            source_url=f"https://www.horseracingnation.com/news/{suffix}_123",
            title_ja=f"HRN {suffix}",
            published_at=timezone.now(),
        )

    def _draft(self, stub: SourceArticleStub, *, status: str, body: str) -> CanonicalNewsDraft:
        return CanonicalNewsDraft(
            source_site=SourceSite.HORSE_RACING_NATION,
            source_mode=SourceMode.LATEST,
            source_article_id=stub.source_article_id,
            source_url=stub.source_url,
            title_ja=stub.title_ja,
            body_ja_raw=body,
            body_ja_normalized=body,
            published_at=stub.published_at,
            images=[],
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            original_content_html=f"<main>{stub.source_article_id}</main>",
            metadata={"body_parse_status": status, "body_selector": ".article-body" if status == "ok" else ""},
        )

    def test_invalid_detail_bodies_are_rejected_before_upsert_and_other_articles_continue(self):
        selector_stub = self._stub("selector-missing")
        empty_stub = self._stub("empty-after-cleaning")
        good_stub = self._stub("good-body")
        drafts = {
            selector_stub.source_url: self._draft(selector_stub, status="selector_not_found", body=""),
            empty_stub.source_url: self._draft(empty_stub, status="empty_after_cleaning", body=""),
            good_stub.source_url: self._draft(good_stub, status="ok", body="A complete article body."),
        }
        article = NewsArticle.objects.create(
            source_site=SourceSite.HORSE_RACING_NATION,
            source_mode=SourceMode.LATEST,
            source_article_id="upsert-result",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Good article",
            body_ja_raw="A complete article body.",
            body_ja_normalized="A complete article body.",
            published_at=timezone.now(),
            source_url=good_stub.source_url,
        )

        class FakeAdapter:
            skipped_items = []
            last_listing_query_errors = []

            def fetch_listing(self, mode, page):
                return [selector_stub, empty_stub, good_stub]

            def fetch_detail(self, source_url):
                draft = drafts[source_url]
                return SourceArticleDetail(
                    title_ja=draft.title_ja,
                    body_ja_raw=draft.body_ja_raw,
                    body_ja_normalized=draft.body_ja_normalized,
                    published_at=draft.published_at,
                    images=[],
                    original_content_html=draft.original_content_html,
                    metadata=draft.metadata,
                )

            def normalize_source_payload(self, stub, detail):
                return drafts[stub.source_url]

        with patch("stable.tasks.INTERNATIONAL_ADAPTERS", {self.source.adapter_key: FakeAdapter}), patch(
            "stable.tasks.upsert_article_from_draft", return_value=(article, True)
        ) as upsert, patch("stable.tasks._discover_terms_after_ingest") as discover, patch(
            "stable.tasks._auto_translate_article_after_ingest"
        ) as translate:
            result = _crawl_international_source(self.source)

        self.assertEqual(upsert.call_count, 1)
        self.assertEqual(discover.call_count, 1)
        self.assertEqual(translate.call_count, 1)
        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["skipped_count"], 2)
        self.assertEqual(result["source_summary"]["detail_failures"], 2)
        job = CrawlJob.objects.get(pk=result["crawl_job_id"])
        self.assertEqual(job.status, TaskStatus.SUCCESS)
        self.assertEqual(
            (job.fail_count, "detail_failures=2" in job.error_message),
            (0, True),
        )
        self.assertIn("parse failed", job.error_message)

    def test_invalid_repeat_detail_does_not_update_existing_article_html_metadata_or_snapshot(self):
        bad_stub = self._stub("existing-bad")
        good_stub = self._stub("new-good")
        article = NewsArticle.objects.create(
            source_site=SourceSite.HORSE_RACING_NATION,
            source_mode=SourceMode.LATEST,
            source_article_id=bad_stub.source_article_id,
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Original title",
            body_ja_raw="Original clean body.",
            body_ja_normalized="Original clean body.",
            original_content_html="<div class='article-body'>Original clean body.</div>",
            translation_metadata={"existing": "metadata"},
            published_at=timezone.now(),
            source_url=bad_stub.source_url,
        )
        bad_draft = self._draft(bad_stub, status="selector_not_found", body="")
        bad_draft.original_content_html = "<main>Changed shell only</main>"
        bad_draft.metadata["layout"] = "drifted"
        good_draft = self._draft(good_stub, status="ok", body="New complete body.")
        drafts = {bad_stub.source_url: bad_draft, good_stub.source_url: good_draft}

        class FakeAdapter:
            skipped_items = []
            last_listing_query_errors = []

            def fetch_listing(self, mode, page):
                return [bad_stub, good_stub]

            def fetch_detail(self, source_url):
                draft = drafts[source_url]
                return SourceArticleDetail(
                    title_ja=draft.title_ja,
                    body_ja_raw=draft.body_ja_raw,
                    body_ja_normalized=draft.body_ja_normalized,
                    published_at=draft.published_at,
                    images=[],
                    original_content_html=draft.original_content_html,
                    metadata=draft.metadata,
                )

            def normalize_source_payload(self, stub, detail):
                return drafts[stub.source_url]

        with patch("stable.tasks.INTERNATIONAL_ADAPTERS", {self.source.adapter_key: FakeAdapter}), patch(
            "stable.tasks._discover_terms_after_ingest"
        ), patch("stable.tasks._auto_translate_article_after_ingest"):
            result = _crawl_international_source(self.source)

        article.refresh_from_db()
        self.assertEqual(article.title_ja, "Original title")
        self.assertEqual(article.body_ja_raw, "Original clean body.")
        self.assertEqual(article.original_content_html, "<div class='article-body'>Original clean body.</div>")
        self.assertEqual(article.translation_metadata, {"existing": "metadata"})
        self.assertFalse(NewsSnapshot.objects.filter(article=article).exists())
        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["seen_count"], 0)
        self.assertEqual(result["skipped_count"], 1)


class RepairArticleContentBoundariesCommandTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="production-8316",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Breeders' Cup Charity Event Raises Funds",
            body_ja_raw="Old body with complete list of results and Read Today's Paper.",
            body_ja_normalized="Old body with complete list of results and Read Today's Paper.",
            original_content_html=fixture_html("tdn_8316.html"),
            translated_title_zh="旧标题",
            translated_body_zh="旧译文",
            title_zh="人工旧标题",
            body_zh="人工旧译文",
            manually_edited_fields=["title_zh", "body_zh"],
            published_at=timezone.now(),
            published_to_web_at=timezone.now(),
            source_url="https://www.thoroughbreddailynews.com/charity-event/",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_by_mode=PublishedByMode.AUTO,
        )

    @staticmethod
    def _parse_metadata_sha256(detail: SourceArticleDetail) -> str:
        persisted_metadata = {
            "body_parse_status": detail.metadata.get("body_parse_status", ""),
            "body_selector": detail.metadata.get("body_selector", ""),
            "body_cleaning": detail.metadata.get("body_cleaning", {}),
        }
        canonical = json.dumps(
            persisted_metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _manifest_args(self, *articles: NewsArticle) -> tuple[str, str]:
        rows = []
        for article in articles:
            article.refresh_from_db()
            detail = TDNAdapter().parse_detail_html(article.original_content_html, url=article.source_url)
            if article.source_site == SourceSite.SPONICHI:
                detail = SponichiAdapter().parse_detail_html(article.original_content_html, url=article.source_url)
            rows.append(
                {
                    "article_id": article.id,
                    "decision": "repair_source_body",
                    "updated_at": article.updated_at.isoformat(),
                    "original_content_html_sha256": hashlib.sha256(
                        article.original_content_html.encode("utf-8")
                    ).hexdigest(),
                    "before_body_sha256": hashlib.sha256(article.body_ja_raw.encode("utf-8")).hexdigest(),
                    "after_body_sha256": hashlib.sha256(detail.body_ja_raw.encode("utf-8")).hexdigest(),
                    "after_title_sha256": hashlib.sha256(detail.title_ja.encode("utf-8")).hexdigest(),
                    "after_body_normalized_sha256": hashlib.sha256(
                        detail.body_ja_normalized.encode("utf-8")
                    ).hexdigest(),
                    "after_parse_metadata_sha256": self._parse_metadata_sha256(detail),
                }
            )
        payload = {
            "schema_version": 2,
            "source_site": articles[0].source_site,
            "articles": rows,
        }
        path = Path(self.temp_dir.name) / "approved-manifest.json"
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        path.write_bytes(raw)
        return str(path), hashlib.sha256(raw).hexdigest()

    def test_command_requires_explicit_article_ids(self):
        with self.assertRaises(CommandError):
            call_command("repair_article_content_boundaries")

    def test_dry_run_reports_hashes_without_writing(self):
        before_body = self.article.body_ja_raw
        before_metadata = dict(self.article.translation_metadata)
        expected_detail = TDNAdapter().parse_detail_html(
            self.article.original_content_html,
            url=self.article.source_url,
        )
        expected_updated_at = self.article.updated_at.isoformat()
        expected_html_sha256 = hashlib.sha256(self.article.original_content_html.encode("utf-8")).hexdigest()
        expected_before_body_sha256 = hashlib.sha256(before_body.encode("utf-8")).hexdigest()
        expected_after_body_sha256 = hashlib.sha256(expected_detail.body_ja_raw.encode("utf-8")).hexdigest()
        expected_after_title_sha256 = hashlib.sha256(expected_detail.title_ja.encode("utf-8")).hexdigest()
        expected_after_body_normalized_sha256 = hashlib.sha256(
            expected_detail.body_ja_normalized.encode("utf-8")
        ).hexdigest()
        expected_after_parse_metadata_sha256 = self._parse_metadata_sha256(expected_detail)
        expected_effective_body_sha256 = hashlib.sha256(self.article.effective_body.encode("utf-8")).hexdigest()
        expected_status_fields = {
            "workflow_status": self.article.workflow_status,
            "translation_status": self.article.translation_status,
            "automation_status": self.article.automation_status,
            "effective_body_layer": "manual_body_zh",
            "effective_body_sha256": expected_effective_body_sha256,
            "manually_edited_fields": ["title_zh", "body_zh"],
            "has_rewrite_body": False,
            "qq_delivery_count": 0,
            "published_to_web_at": self.article.published_to_web_at.isoformat(),
            "before_body_start_excerpt": before_body[:160],
            "before_body_end_excerpt": before_body[-160:],
            "after_body_start_excerpt": expected_detail.body_ja_raw[:160],
            "after_body_end_excerpt": expected_detail.body_ja_raw[-160:],
        }
        self.assertFalse(QQPushDelivery.objects.filter(article=self.article).exists())
        out = StringIO()

        call_command("repair_article_content_boundaries", "--article-id", str(self.article.id), stdout=out)

        payload = json.loads(out.getvalue())
        self.assertEqual(payload["mode"], "dry_run")
        row = payload["articles"][0]
        self.assertEqual(row["article_id"], self.article.id)
        self.assertEqual(row["body_parse_status"], "ok")
        self.assertIn("updated_at", row)
        self.assertEqual(row["updated_at"], expected_updated_at)
        self.assertEqual(row["original_content_html_sha256"], expected_html_sha256)
        self.assertEqual(row["before_body_sha256"], expected_before_body_sha256)
        self.assertEqual(row["after_body_sha256"], expected_after_body_sha256)
        self.assertEqual(row["after_title_sha256"], expected_after_title_sha256)
        self.assertIn("after_body_normalized_sha256", row)
        self.assertEqual(row["after_body_normalized_sha256"], expected_after_body_normalized_sha256)
        self.assertIn("after_parse_metadata_sha256", row)
        self.assertEqual(row["after_parse_metadata_sha256"], expected_after_parse_metadata_sha256)
        self.assertNotEqual(row["before_body_sha256"], row["after_body_sha256"])
        self.assertIn("length_delta", row)
        self.assertEqual(row["length_delta"], row["after_length"] - row["before_length"])
        self.assertTrue(
            set(expected_status_fields).issubset(row),
            f"missing dry-run audit fields: {sorted(set(expected_status_fields) - set(row))}",
        )
        for field_name, expected_value in expected_status_fields.items():
            self.assertEqual(row[field_name], expected_value, field_name)
        self.article.refresh_from_db()
        self.assertEqual(self.article.body_ja_raw, before_body)
        self.assertEqual(self.article.translation_metadata, before_metadata)
        self.assertFalse(OperationLog.objects.filter(action_type="article_content_boundary_repaired").exists())

    def test_commit_updates_only_source_body_and_audit_metadata(self):
        before_workflow = self.article.workflow_status
        before_published_at = self.article.published_to_web_at
        before_title_zh = self.article.title_zh
        before_body_zh = self.article.body_zh

        manifest_path, manifest_sha256 = self._manifest_args(self.article)
        call_command(
            "repair_article_content_boundaries",
            "--article-id",
            str(self.article.id),
            "--manifest",
            manifest_path,
            "--manifest-sha256",
            manifest_sha256,
            "--commit",
            stdout=StringIO(),
        )

        self.article.refresh_from_db()
        self.assertIn("event brought together owners", self.article.body_ja_raw)
        self.assertNotIn("complete list of results", self.article.body_ja_raw)
        self.assertEqual(self.article.workflow_status, before_workflow)
        self.assertEqual(self.article.published_to_web_at, before_published_at)
        self.assertEqual(self.article.title_zh, before_title_zh)
        self.assertEqual(self.article.body_zh, before_body_zh)
        self.assertEqual(
            self.article.translation_metadata["content_boundary_repair"]["body_parse_status"],
            "ok",
        )
        self.assertTrue(
            OperationLog.objects.filter(
                action_type="article_content_boundary_repaired",
                target_type="article",
                target_id=str(self.article.id),
            ).exists()
        )
        self.assertFalse(QQPushDelivery.objects.filter(article=self.article).exists())

    def test_commit_rejects_selector_failure_without_partial_write(self):
        manifest_path, manifest_sha256 = self._manifest_args(self.article)
        self.article.original_content_html = "<html><body><nav>TDN shell</nav></body></html>"
        self.article.save(update_fields=["original_content_html", "updated_at"])
        before_body = self.article.body_ja_raw

        with self.assertRaises(CommandError):
            call_command(
                "repair_article_content_boundaries",
                "--article-id",
                str(self.article.id),
                "--manifest",
                manifest_path,
                "--manifest-sha256",
                manifest_sha256,
                "--commit",
                stdout=StringIO(),
            )

        self.article.refresh_from_db()
        self.assertEqual(self.article.body_ja_raw, before_body)
        self.assertFalse(OperationLog.objects.filter(action_type="article_content_boundary_repaired").exists())

    def test_sponichi_commit_repairs_source_title_and_body_from_saved_html(self):
        article = NewsArticle.objects.create(
            source_site=SourceSite.SPONICHI,
            source_mode=SourceMode.LATEST,
            source_article_id="sponichi-boundary-repair",
            racing_region=RacingRegion.JAPAN,
            source_language=SourceLanguage.JAPANESE,
            title_ja="本当の見出し - スポニチ Sponichi Annex ギャンブル",
            body_ja_raw="記事 スポニチアネックス取材班 ニュース一覧を見る",
            body_ja_normalized="記事 スポニチアネックス取材班 ニュース一覧を見る",
            original_content_html="""
            <html><head><meta property="og:title" content="本当の見出し - スポニチ Sponichi Annex ギャンブル"></head>
            <body><article>
              <header data-component="article-header"><h1>本当の見出し</h1></header>
              <div data-component="article-body">
                <figure><figcaption>Photo By スポニチ</figcaption></figure>
                <p>これが保存済みHTMLから復元する本当の本文です。</p>
                <div id="article_more_area">続きを表示</div>
              </div>
              <section>ギャンブルのニュース一覧を見る</section>
            </article></body></html>
            """,
            translated_title_zh="旧标题",
            translated_body_zh="旧译文",
            published_at=timezone.now(),
            source_url="https://www.sponichi.co.jp/gamble/news/example.html",
            workflow_status=WorkflowStatus.PENDING_REVIEW,
        )

        out = StringIO()
        manifest_path, manifest_sha256 = self._manifest_args(article)
        call_command(
            "repair_article_content_boundaries",
            "--article-id",
            str(article.id),
            "--manifest",
            manifest_path,
            "--manifest-sha256",
            manifest_sha256,
            "--commit",
            stdout=out,
        )

        payload = json.loads(out.getvalue())["articles"][0]
        article.refresh_from_db()
        self.assertEqual(article.title_ja, "本当の見出し")
        self.assertEqual(article.body_ja_raw, "これが保存済みHTMLから復元する本当の本文です。")
        self.assertNotIn("ギャンブル", article.body_ja_raw)
        self.assertTrue(payload["title_changed"])
        self.assertTrue(payload["changed"])
        self.assertEqual(payload["body_selector"], "[data-component='article-body']")
        self.assertEqual(
            article.translation_metadata["content_boundary_repair"]["after_title"],
            "本当の見出し",
        )

    def test_commit_requires_exact_manifest_file_sha_before_any_write(self):
        manifest_path, manifest_sha256 = self._manifest_args(self.article)
        before_body = self.article.body_ja_raw

        with self.assertRaises(CommandError):
            call_command(
                "repair_article_content_boundaries",
                "--article-id",
                str(self.article.id),
                "--manifest",
                manifest_path,
                "--manifest-sha256",
                "0" * len(manifest_sha256),
                "--commit",
                stdout=StringIO(),
            )

        self.article.refresh_from_db()
        self.assertEqual(self.article.body_ja_raw, before_body)
        self.assertFalse(OperationLog.objects.filter(action_type="article_content_boundary_repaired").exists())

    def test_commit_rejects_legacy_manifest_without_all_persisted_output_hashes(self):
        manifest_path, _manifest_sha256 = self._manifest_args(self.article)
        path = Path(manifest_path)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["schema_version"] = 1
        for row in manifest["articles"]:
            row.pop("after_title_sha256")
            row.pop("after_body_normalized_sha256")
            row.pop("after_parse_metadata_sha256")
        raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        path.write_bytes(raw)
        legacy_sha256 = hashlib.sha256(raw).hexdigest()
        before = (
            self.article.title_ja,
            self.article.body_ja_raw,
            self.article.body_ja_normalized,
            dict(self.article.translation_metadata),
        )

        with self.assertRaises(CommandError):
            call_command(
                "repair_article_content_boundaries",
                "--article-id",
                str(self.article.id),
                "--manifest",
                str(path),
                "--manifest-sha256",
                legacy_sha256,
                "--commit",
                stdout=StringIO(),
            )

        self.article.refresh_from_db()
        self.assertEqual(
            (
                self.article.title_ja,
                self.article.body_ja_raw,
                self.article.body_ja_normalized,
                self.article.translation_metadata,
            ),
            before,
        )
        self.assertFalse(OperationLog.objects.filter(action_type="article_content_boundary_repaired").exists())

    def test_manifest_rejects_drift_in_each_persisted_parser_output(self):
        manifest_path, manifest_sha256 = self._manifest_args(self.article)
        before = (
            self.article.title_ja,
            self.article.body_ja_raw,
            self.article.body_ja_normalized,
            dict(self.article.translation_metadata),
        )

        def mutate_title(detail):
            detail.title_ja = f"{detail.title_ja} changed after approval"

        def mutate_normalized_body(detail):
            detail.body_ja_normalized = f"{detail.body_ja_normalized}\nnormalized drift"

        def mutate_parse_metadata(detail):
            detail.metadata = {
                **detail.metadata,
                "body_selector": "span[data-review-drift='true']",
            }

        for label, mutator in (
            ("title", mutate_title),
            ("normalized_body", mutate_normalized_body),
            ("parse_metadata", mutate_parse_metadata),
        ):
            with self.subTest(output=label):
                class DriftedTDNAdapter:
                    def parse_detail_html(self, html, *, url):
                        detail = TDNAdapter().parse_detail_html(html, url=url)
                        mutator(detail)
                        return detail

                with patch(
                    "stable.management.commands.repair_article_content_boundaries.INTERNATIONAL_ADAPTERS",
                    {SourceSite.TDN: DriftedTDNAdapter},
                ), self.assertRaises(CommandError):
                    call_command(
                        "repair_article_content_boundaries",
                        "--article-id",
                        str(self.article.id),
                        "--manifest",
                        manifest_path,
                        "--manifest-sha256",
                        manifest_sha256,
                        "--commit",
                        stdout=StringIO(),
                    )

                self.article.refresh_from_db()
                self.assertEqual(
                    (
                        self.article.title_ja,
                        self.article.body_ja_raw,
                        self.article.body_ja_normalized,
                        self.article.translation_metadata,
                    ),
                    before,
                )
                self.assertFalse(
                    OperationLog.objects.filter(action_type="article_content_boundary_repaired").exists()
                )

    def test_manifest_input_drift_rolls_back_entire_approved_batch(self):
        second = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="production-8316-second",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Second approved article",
            body_ja_raw="Second old body with Read Today's Paper.",
            body_ja_normalized="Second old body with Read Today's Paper.",
            original_content_html=fixture_html("tdn_8316.html"),
            published_at=timezone.now(),
            source_url="https://www.thoroughbreddailynews.com/charity-event-second/",
        )
        manifest_path, manifest_sha256 = self._manifest_args(self.article, second)
        first_before = self.article.body_ja_raw
        second.body_ja_raw = "Drift after approval."
        second.body_ja_normalized = second.body_ja_raw
        second.save(update_fields=["body_ja_raw", "body_ja_normalized", "updated_at"])

        with self.assertRaises(CommandError):
            call_command(
                "repair_article_content_boundaries",
                "--article-id",
                str(self.article.id),
                "--article-id",
                str(second.id),
                "--manifest",
                manifest_path,
                "--manifest-sha256",
                manifest_sha256,
                "--commit",
                stdout=StringIO(),
            )

        self.article.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.article.body_ja_raw, first_before)
        self.assertEqual(second.body_ja_raw, "Drift after approval.")
        self.assertFalse(OperationLog.objects.filter(action_type="article_content_boundary_repaired").exists())


class HorseRacingNationHistoricalBoundaryScanTests(TestCase):
    def _article(
        self,
        suffix: str,
        *,
        html: str,
        body: str,
        body_zh: str = "",
        rewrite_body_zh: str = "",
        manually_edited_fields: list[str] | None = None,
    ) -> NewsArticle:
        return NewsArticle.objects.create(
            source_site=SourceSite.HORSE_RACING_NATION,
            source_mode=SourceMode.LATEST,
            source_article_id=f"historical-{suffix}",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            title_ja=f"Historical {suffix}",
            body_ja_raw=body,
            body_ja_normalized=body,
            original_content_html=html,
            body_zh=body_zh,
            rewrite_body_zh=rewrite_body_zh,
            manually_edited_fields=manually_edited_fields or [],
            published_at=timezone.now(),
            source_url=f"https://www.horseracingnation.com/news/historical_{suffix}_123",
        )

    def _scan(self, *, after_id: int = 0, max_id: int, limit: int = 100) -> dict:
        out = StringIO()
        call_command(
            "repair_article_content_boundaries",
            "--source-site",
            SourceSite.HORSE_RACING_NATION,
            "--after-id",
            str(after_id),
            "--max-id",
            str(max_id),
            "--limit",
            str(limit),
            stdout=out,
        )
        return json.loads(out.getvalue())

    def test_read_only_scan_is_stably_bounded_and_reports_hashes_without_side_effects(self):
        first = self._article("first", html=fixture_html("hrn_9623.html"), body="Polluted old body")
        second = self._article("second", html=fixture_html("hrn_normal_article.html"), body="Another old body")
        frozen_max_id = second.id
        later = self._article("later", html=fixture_html("hrn_9623.html"), body="Must stay outside scope")
        target = PushTarget.objects.create(name="Historical scan audit", group_id="hrn-scan-audit")
        QQPushDelivery.objects.create(
            article=first,
            target=target,
            status=QQPushDeliveryStatus.SENT,
            message_id="existing-hrn-delivery",
            sent_at=timezone.now(),
        )
        before = {
            article.id: (article.updated_at, article.body_ja_raw, article.translation_metadata)
            for article in (first, second, later)
        }

        payload = self._scan(max_id=frozen_max_id, limit=10)

        self.assertEqual(payload["mode"], "scan")
        self.assertEqual(payload["scope"]["source_site"], SourceSite.HORSE_RACING_NATION)
        self.assertEqual(payload["scope"]["after_id"], 0)
        self.assertEqual(payload["scope"]["max_id"], frozen_max_id)
        self.assertEqual(payload["scope"]["limit"], 10)
        self.assertEqual([row["article_id"] for row in payload["articles"]], [first.id, second.id])
        rows = {row["article_id"]: row for row in payload["articles"]}
        for row in payload["articles"]:
            required_status_fields = {
                "workflow_status",
                "translation_status",
                "automation_status",
                "qq_delivery_count",
                "before_length",
                "after_length",
                "length_delta",
            }
            self.assertTrue(
                required_status_fields.issubset(row),
                f"missing scan status fields: {sorted(required_status_fields - set(row))}",
            )
            self.assertRegex(row["original_content_html_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(row["before_body_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(row["after_body_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(row["effective_body_sha256"], r"^[0-9a-f]{64}$")
            article = first if row["article_id"] == first.id else second
            detail = HorseRacingNationAdapter().parse_detail_html(
                article.original_content_html,
                url=article.source_url,
            )
            self.assertEqual(row["before_length"], len(article.body_ja_raw))
            self.assertEqual(row["after_length"], len(detail.body_ja_raw))
            self.assertEqual(row["length_delta"], len(detail.body_ja_raw) - len(article.body_ja_raw))
            self.assertEqual(row["workflow_status"], article.workflow_status)
            self.assertEqual(row["translation_status"], article.translation_status)
            self.assertEqual(row["automation_status"], article.automation_status)
            self.assertNotIn("original_content_html", row)
            self.assertNotIn("body_ja_raw", row)
        self.assertEqual(rows[first.id]["qq_delivery_count"], 1)
        self.assertEqual(rows[second.id]["qq_delivery_count"], 0)
        for article in (first, second, later):
            article.refresh_from_db()
            self.assertEqual(
                (article.updated_at, article.body_ja_raw, article.translation_metadata),
                before[article.id],
            )
        self.assertFalse(OperationLog.objects.exists())
        self.assertEqual(QQPushDelivery.objects.filter(article=first).count(), 1)
        self.assertFalse(QQPushDelivery.objects.filter(article=second).exists())

    def test_scan_accounts_for_missing_selector_changed_and_unchanged_without_dropping_scope(self):
        missing = self._article("missing", html="", body="Old body")
        selector_failure = self._article("selector", html="<main>Navigation only</main>", body="Old shell body")
        empty_after_cleaning = self._article(
            "empty",
            html="<div class='article-body'><nav>Structured navigation only</nav></div>",
            body="Old shell body",
        )
        changed = self._article("changed", html=fixture_html("hrn_9623.html"), body="Polluted old body")
        parsed = HorseRacingNationAdapter().parse_detail_html(
            fixture_html("hrn_normal_article.html"),
            url="https://www.horseracingnation.com/news/historical_unchanged_123",
        )
        unchanged = self._article(
            "unchanged",
            html=fixture_html("hrn_normal_article.html"),
            body=parsed.body_ja_raw,
        )

        payload = self._scan(max_id=unchanged.id)

        self.assertEqual(
            [row["article_id"] for row in payload["articles"]],
            [missing.id, selector_failure.id, empty_after_cleaning.id, changed.id, unchanged.id],
        )
        rows = {row["article_id"]: row for row in payload["articles"]}
        self.assertEqual(payload["counts"]["missing_original_html"], 1)
        self.assertEqual(payload["counts"]["selector_not_found"], 1)
        self.assertIn("empty_after_cleaning", payload["counts"])
        self.assertEqual(payload["counts"]["empty_after_cleaning"], 1)
        self.assertEqual(payload["counts"]["changed"], 1)
        self.assertEqual(payload["counts"]["unchanged"], 1)
        self.assertEqual(rows[empty_after_cleaning.id]["body_parse_status"], "empty_after_cleaning")
        self.assertEqual(rows[empty_after_cleaning.id]["status"], "empty_after_cleaning")

    def test_scan_rejects_unsupported_source_invalid_limit_and_commit_combination(self):
        article = self._article("bounds", html=fixture_html("hrn_9623.html"), body="Old body")
        invalid_calls = (
            ("--source-site", SourceSite.TDN, "--after-id", "0", "--max-id", str(article.id), "--limit", "10"),
            (
                "--source-site",
                SourceSite.HORSE_RACING_NATION,
                "--after-id",
                "0",
                "--max-id",
                str(article.id),
                "--limit",
                "0",
            ),
            (
                "--source-site",
                SourceSite.HORSE_RACING_NATION,
                "--after-id",
                "0",
                "--max-id",
                str(article.id),
                "--limit",
                "501",
            ),
            (
                "--source-site",
                SourceSite.HORSE_RACING_NATION,
                "--after-id",
                "0",
                "--max-id",
                str(article.id),
                "--limit",
                "10",
                "--commit",
            ),
        )
        for command_args in invalid_calls:
            with self.subTest(command_args=command_args), self.assertRaises(CommandError):
                call_command("repair_article_content_boundaries", *command_args, stdout=StringIO())

        article.refresh_from_db()
        self.assertEqual(article.body_ja_raw, "Old body")
        self.assertFalse(OperationLog.objects.exists())

    def test_scan_reports_manual_and_rewrite_effective_layers_without_overwriting_them(self):
        manual = self._article(
            "manual",
            html=fixture_html("hrn_9623.html"),
            body="Old body",
            body_zh="人工正文",
            manually_edited_fields=["body_zh"],
        )
        rewrite = self._article(
            "rewrite",
            html=fixture_html("hrn_9623.html"),
            body="Old body",
            body_zh="机器翻译",
            rewrite_body_zh="机器改写正文",
        )

        payload = self._scan(max_id=rewrite.id)
        rows = {row["article_id"]: row for row in payload["articles"]}

        self.assertEqual(rows[manual.id]["effective_body_layer"], "manual_body_zh")
        self.assertEqual(rows[manual.id]["manually_edited_fields"], ["body_zh"])
        self.assertEqual(rows[rewrite.id]["effective_body_layer"], "rewrite_body_zh")
        self.assertTrue(rows[rewrite.id]["has_rewrite_body"])
        manual.refresh_from_db()
        rewrite.refresh_from_db()
        self.assertEqual(manual.body_zh, "人工正文")
        self.assertEqual(rewrite.rewrite_body_zh, "机器改写正文")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, AUTOMATION_ENABLED=False)
class ForcePublishedArticleTranslationTests(TestCase):
    def setUp(self):
        self.published_to_web_at = timezone.now()
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="force-translation-published",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Updated source title",
            body_ja_raw="Updated source body.",
            body_ja_normalized="Updated source body.",
            translated_title_zh="旧机器标题",
            translated_body_zh="旧机器正文",
            translated_summary_zh="旧机器摘要",
            title_zh="人工旧标题",
            body_zh="人工旧正文",
            summary_zh="人工旧摘要",
            push_summary_zh="人工旧推送摘要",
            manually_edited_fields=["title_zh", "body_zh", "summary_zh", "push_summary_zh"],
            translation_status=ArticleTranslationStatus.TRANSLATED,
            published_at=timezone.now(),
            published_to_web_at=self.published_to_web_at,
            source_url="https://www.thoroughbreddailynews.com/force-translation/",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_by_mode=PublishedByMode.AUTO,
        )
        target = PushTarget.objects.create(name="Existing delivery", group_id="content-boundary-existing")
        self.delivery = QQPushDelivery.objects.create(
            article=self.article,
            target=target,
            status=QQPushDeliveryStatus.SENT,
            message_id="existing-message",
            sent_at=timezone.now(),
        )

    def _result(self):
        return type(
            "Result",
            (),
            {
                "title_zh": "修复后标题",
                "body_zh": "修复后的干净正文",
                "push_summary_zh": "修复后摘要",
                "metadata": {"provider": "test", "model": "test-model"},
            },
        )()

    def test_force_task_overwrites_approved_copy_without_republishing(self):
        with patch("stable.tasks.translate_article", return_value=self._result()):
            translate_article_task.run(self.article.id, force=True)

        self.article.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual(self.article.title_zh, "修复后标题")
        self.assertEqual(self.article.body_zh, "修复后的干净正文")
        self.assertEqual(self.article.summary_zh, "修复后摘要")
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(self.article.published_to_web_at, self.published_to_web_at)
        self.assertEqual(self.delivery.message_id, "existing-message")
        self.assertEqual(QQPushDelivery.objects.filter(article=self.article).count(), 1)

    def test_translate_news_force_flag_is_explicit_and_runs_synchronously(self):
        with patch("stable.tasks.translate_article", return_value=self._result()):
            call_command(
                "translate_news",
                "--article-id",
                str(self.article.id),
                "--sync",
                "--force",
                stdout=StringIO(),
            )

        self.article.refresh_from_db()
        self.assertEqual(self.article.body_zh, "修复后的干净正文")
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(QQPushDelivery.objects.filter(article=self.article).count(), 1)

    def test_translate_news_force_requires_explicit_id_and_sync(self):
        with self.assertRaises(CommandError):
            call_command("translate_news", "--pending", "--sync", "--force", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "translate_news",
                "--article-id",
                str(self.article.id),
                "--force",
                stdout=StringIO(),
            )

    def test_translate_news_force_rejects_missing_explicit_id_before_work(self):
        with patch("stable.tasks.translate_article") as translate:
            with self.assertRaises(CommandError):
                call_command(
                    "translate_news",
                    "--article-id",
                    str(self.article.id),
                    "--article-id",
                    "999999",
                    "--sync",
                    "--force",
                    stdout=StringIO(),
                )

        translate.assert_not_called()

    def test_translate_news_force_treats_skipped_task_as_failure(self):
        self.article.translation_status = ArticleTranslationStatus.TRANSLATING
        self.article.save(update_fields=["translation_status", "updated_at"])

        with self.assertRaises(CommandError):
            call_command(
                "translate_news",
                "--article-id",
                str(self.article.id),
                "--sync",
                "--force",
                stdout=StringIO(),
                stderr=StringIO(),
            )

        self.article.refresh_from_db()
        self.assertEqual(self.article.body_zh, "人工旧正文")

    @override_settings(AUTOMATION_ENABLED=True)
    def test_force_published_translation_does_not_dispatch_automation(self):
        with patch("stable.tasks.translate_article", return_value=self._result()), patch(
            "stable.tasks.dispatch_task"
        ) as dispatch:
            translate_article_task.run(self.article.id, force=True)

        dispatch.assert_not_called()

    def test_translate_news_force_failure_returns_command_error(self):
        with patch("stable.tasks.translate_article", side_effect=RuntimeError("provider unavailable")):
            with self.assertRaises(CommandError):
                call_command(
                    "translate_news",
                    "--article-id",
                    str(self.article.id),
                    "--sync",
                    "--force",
                    stdout=StringIO(),
                    stderr=StringIO(),
                )

        self.article.refresh_from_db()
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(self.article.body_zh, "人工旧正文")
        self.assertIsNone(self.article.translation_next_retry_at)

    def test_force_translation_failure_keeps_existing_public_copy(self):
        with patch("stable.tasks.translate_article", side_effect=RuntimeError("provider unavailable")):
            with self.assertRaises(RuntimeError):
                translate_article_task.run(self.article.id, force=True)

        self.article.refresh_from_db()
        self.assertEqual(self.article.title_zh, "人工旧标题")
        self.assertEqual(self.article.body_zh, "人工旧正文")
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(self.article.published_to_web_at, self.published_to_web_at)
        self.assertEqual(QQPushDelivery.objects.filter(article=self.article).count(), 1)

    def test_force_translation_does_not_consume_automatic_retry_budget(self):
        self.article.translation_status = ArticleTranslationStatus.FAILED
        self.article.translation_retry_count = 2
        self.article.translation_next_retry_at = timezone.now() + timedelta(minutes=10)
        self.article.save(
            update_fields=[
                "translation_status",
                "translation_retry_count",
                "translation_next_retry_at",
                "updated_at",
            ]
        )

        with patch("stable.tasks.translate_article", side_effect=RuntimeError("provider unavailable")):
            with self.assertRaises(RuntimeError):
                translate_article_task.run(self.article.id, force=True)

        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_retry_count, 2)
        self.assertIsNone(self.article.translation_next_retry_at)
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)

"""
Tests for the "Simplify Public Navigation and Attribution" change.

These tests assert the NEW expected behavior:
- No region tabs on the public news feed (unified view)
- ?region=xxx on news feed redirects to / (stripping region param)
- No source attribution (source_note, source_language, source_url) on public pages
- No "原站热度" text on the homepage
- Horse index: no region tabs, ?region=xxx redirects to /horses/
- Race calendar region filter still works
- Database fields preserved after public request

Because the implementation has NOT been done, ALL of these tests should FAIL (RED).
"""

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from stable.models import (
    HorseProfile,
    HorseProfileStatus,
    HorseProfileCompleteness,
    NewsArticle,
    NewsImage,
    NewsSnapshot,
    ArticleHorseLink,
    ArticleHorseLinkStatus,
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    RaceEvent,
    RaceEventVisibility,
    RaceEventStatus,
    RaceEventPriority,
    RacingRegion,
    SourceLanguage,
    SourceSite,
    SourceMode,
    WorkflowStatus,
    HorseFollow,
    TermEntry,
    TermType,
)


class PublicNavigationAndAttributionTests(TestCase):
    """Tests for the simplified public navigation and attribution."""

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def make_article(
        self,
        source_article_id: str,
        title: str,
        *,
        workflow_status: str = WorkflowStatus.PUBLISHED,
        published_to_web_at=None,
        published_at=None,
        score_total: int = 0,
        race_priority: str = "",
        has_cover: bool = False,
        source_mode: str = SourceMode.LATEST,
        racing_region: str = RacingRegion.JAPAN,
        source_language: str = SourceLanguage.JAPANESE,
        source_site: str = SourceSite.NETKEIBA,
        source_note: str = "netkeiba",
        source_url: str | None = None,
        tags: list[str] | None = None,
    ) -> NewsArticle:
        published_at = published_at or timezone.now()
        article = NewsArticle.objects.create(
            source_site=source_site,
            source_mode=source_mode,
            racing_region=racing_region,
            source_language=source_language,
            source_article_id=source_article_id,
            title_ja=title,
            translated_title_zh=title,
            title_zh=title,
            body_ja_raw=f"{title} 原文",
            body_ja_normalized=f"{title} 原文",
            translated_body_zh=f"{title} 正文",
            body_zh=f"{title} 正文",
            translated_summary_zh=f"{title} 摘要",
            summary_zh=f"{title} 摘要",
            published_at=published_at,
            source_url=source_url or f"https://example.com/{source_article_id}",
            workflow_status=workflow_status,
            published_to_web_at=published_to_web_at if published_to_web_at is not None else published_at,
            source_note=source_note,
            tags_json=tags or ["赛马"],
            score_total=score_total,
            decision_reason={"signals": {"race_priority": race_priority}} if race_priority else {},
        )
        if has_cover:
            NewsImage.objects.create(
                article=article,
                original_url=f"https://example.com/images/{source_article_id}.jpg",
                caption_zh=title,
            )
        return article

    def make_profile(
        self,
        *,
        display_name_zh: str = "测试马",
        original_name: str = "Test Horse",
        english_name: str = "Test Horse",
        racing_region: str = RacingRegion.JAPAN,
        country: str = "日本",
        completeness_status: str = HorseProfileCompleteness.EMPTY,
        review_status: str = HorseProfileStatus.PUBLISHED,
    ) -> HorseProfile:
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            source_ja=original_name,
            target_zh=display_name_zh,
            racing_region=racing_region,
            is_active=True,
        )
        return HorseProfile.objects.create(
            primary_term=term,
            display_name_zh=display_name_zh,
            original_name=original_name,
            english_name=english_name,
            racing_region=racing_region,
            country=country,
            completeness_status=completeness_status,
            review_status=review_status,
        )

    # -----------------------------------------------------------------------
    # T01: Unified news feed (all regions together)
    # -----------------------------------------------------------------------

    def test_unified_news_feed_shows_all_regions_together(self):
        """The aggregate feed should show articles from all regions together."""
        now = timezone.now()
        self.make_article("jp-feed-1", "日本新闻A", racing_region=RacingRegion.JAPAN, published_to_web_at=now)
        self.make_article("hk-feed-1", "香港新闻B", racing_region=RacingRegion.HONG_KONG, published_to_web_at=now - timedelta(minutes=1))
        self.make_article("us-feed-1", "美国新闻C", racing_region=RacingRegion.UNITED_STATES, published_to_web_at=now - timedelta(minutes=2))
        # Draft should not appear
        self.make_article(
            "draft-feed-1", "草稿新闻",
            workflow_status=WorkflowStatus.PENDING_EDIT,
            published_to_web_at=now - timedelta(minutes=3),
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        # All published articles appear regardless of region
        self.assertContains(response, "日本新闻A")
        self.assertContains(response, "香港新闻B")
        self.assertContains(response, "美国新闻C")
        # Draft articles are hidden
        self.assertNotContains(response, "草稿新闻")

    # -----------------------------------------------------------------------
    # T03: Old region URL redirects on news feed
    # -----------------------------------------------------------------------

    def test_old_region_url_redirects_to_root(self):
        """/?region=japan should permanently redirect to /."""
        now = timezone.now()
        self.make_article("redirect-1", "重定向测试", published_to_web_at=now)

        for region_value in (RacingRegion.JAPAN, RacingRegion.HONG_KONG, "unknown", ""):
            with self.subTest(region=region_value):
                response = self.client.get("/", {"region": region_value})
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response["Location"], "/")

    def test_region_url_with_page_preserves_page_param(self):
        """/?region=hong_kong&page=2 should redirect to /?page=2."""
        now = timezone.now()
        for index in range(14):
            self.make_article(
                f"hk-redirect-page-{index}", f"分页测试 {index}",
                racing_region=RacingRegion.HONG_KONG,
                published_to_web_at=now - timedelta(minutes=index),
            )

        response = self.client.get("/", {"region": RacingRegion.HONG_KONG, "page": 2})

        self.assertEqual(response.status_code, 301)
        self.assertIn("page=2", response["Location"])
        self.assertNotIn("region", response["Location"])

    def test_unified_feed_page_two_works_without_region(self):
        """/?page=2 should work and pagination links should not contain region."""
        now = timezone.now()
        for index in range(14):
            self.make_article(f"unified-page-{index}", f"统一分页测试 {index}", published_to_web_at=now - timedelta(minutes=index))

        response = self.client.get("/", {"page": 2})

        self.assertEqual(response.status_code, 200)
        # Pagination links should NOT contain region parameter
        self.assertNotContains(response, "region=")

    # -----------------------------------------------------------------------
    # T05: News card hides source/region attributes
    # -----------------------------------------------------------------------

    def test_news_card_hides_source_and_region(self):
        """Article cards on the feed should not show source_note, region label, or source language."""
        now = timezone.now()
        self.make_article(
            "card-hidden",
            "隐藏来源卡片测试",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            source_note="netkeiba",
            published_to_web_at=now,
        )

        response = self.client.get("/")

        # Should NOT contain source_note
        self.assertNotContains(response, "netkeiba")
        # Should NOT contain region display label ("中国香港")
        self.assertNotContains(response, "中国香港")
        # Should NOT contain source language
        self.assertNotContains(response, "英文")
        # Should still show title
        self.assertContains(response, "隐藏来源卡片测试")
        # Should still show detail link
        self.assertContains(response, "/news/")

    # -----------------------------------------------------------------------
    # T06: Headline hides source/region
    # -----------------------------------------------------------------------

    def test_headline_hides_source_and_region(self):
        """The headline section should not show source_note or region labels."""
        now = timezone.now()
        self.make_article(
            "headline-hidden",
            "头条来源隐藏测试",
            racing_region=RacingRegion.JAPAN,
            source_language=SourceLanguage.JAPANESE,
            source_note="JRA",
            has_cover=True,
            score_total=100,
            published_to_web_at=now,
        )

        response = self.client.get("/")

        # Should NOT contain source_note or source_site in the headline
        self.assertNotContains(response, "JRA")
        # Should NOT contain the region display ("日本")
        self.assertNotContains(response, "日本")
        # Content should still render
        self.assertContains(response, "头条来源隐藏测试")

    # -----------------------------------------------------------------------
    # T07: Hot list hides "原站热度"
    # -----------------------------------------------------------------------

    def test_hot_list_hides_upstream_heat_label(self):
        """The hot list should not show '原站热度' text."""
        now = timezone.now()
        hot = self.make_article("hot-hidden", "热门榜隐藏测试", published_to_web_at=now)
        NewsSnapshot.objects.create(
            article=hot,
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.ACCESS,
            rank=1,
            comment_count=18,
            attention_count=4,
            captured_at=now,
        )

        response = self.client.get("/")

        self.assertNotContains(response, "原站热度")

    # -----------------------------------------------------------------------
    # T08: Detail page hides all source attribution
    # -----------------------------------------------------------------------

    def test_detail_hides_source_attribution(self):
        """Article detail should not show source_url, source-box, region, or language."""
        article = self.make_article(
            "detail-no-source",
            "无来源详情",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            source_note="netkeiba",
            source_site=SourceSite.NETKEIBA,
            source_url="https://example.com/detail-no-source",
            published_to_web_at=timezone.now(),
        )

        response = self.client.get(article.public_path)

        # No source_url links
        self.assertNotContains(response, article.source_url)
        # No source-box section
        self.assertNotContains(response, "source-box")
        # No region display
        self.assertNotContains(response, "美国")
        # No language display
        self.assertNotContains(response, "英文")
        # No source note
        self.assertNotContains(response, "netkeiba")
        # Title, body, publish time should still render
        self.assertContains(response, "无来源详情")
        self.assertContains(response, "无来源详情 正文")
        # publish time should be visible
        self.assertContains(response, "发布")

    # -----------------------------------------------------------------------
    # T09: Footer does not generate region links
    # -----------------------------------------------------------------------

    def test_footer_does_not_contain_region_urls(self):
        """The footer should not contain '/?region=' links or list source names."""
        response = self.client.get("/")

        # No region-based links in the footer
        self.assertNotContains(response, '/?region=')
        # Should not list specific source names
        self.assertNotContains(response, "netkeiba")
        self.assertNotContains(response, "JRA")
        self.assertNotContains(response, "HKJC")

    # -----------------------------------------------------------------------
    # T12a: Database fields preserved after public request
    # -----------------------------------------------------------------------

    def test_database_fields_preserved_after_public_feed_request(self):
        """Internal fields like source_site, source_note, racing_region should be unchanged after a GET to /."""
        article = self.make_article(
            "db-preserve-feed", "数据库字段保留测试",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            source_site=SourceSite.NETKEIBA,
            source_note="netkeiba",
            source_url="https://db-preserve.example.com",
            published_to_web_at=timezone.now(),
        )

        self.client.get("/")
        article.refresh_from_db()

        self.assertEqual(article.source_site, SourceSite.NETKEIBA)
        self.assertEqual(article.source_note, "netkeiba")
        self.assertEqual(article.racing_region, RacingRegion.HONG_KONG)
        self.assertEqual(article.source_language, SourceLanguage.ENGLISH)
        self.assertEqual(article.source_url, "https://db-preserve.example.com")

    def test_database_fields_preserved_after_public_detail_request(self):
        """Internal fields should be unchanged after a GET to article detail."""
        article = self.make_article(
            "db-preserve-detail", "数据库字段保留测试详情",
            racing_region=RacingRegion.JAPAN,
            source_language=SourceLanguage.JAPANESE,
            source_site=SourceSite.JRA,
            source_note="JRA",
            source_url="https://db-preserve-detail.example.com",
            published_to_web_at=timezone.now(),
        )

        self.client.get(article.public_path)
        article.refresh_from_db()

        self.assertEqual(article.source_site, SourceSite.JRA)
        self.assertEqual(article.source_note, "JRA")
        self.assertEqual(article.racing_region, RacingRegion.JAPAN)
        self.assertEqual(article.source_language, SourceLanguage.JAPANESE)
        self.assertEqual(article.source_url, "https://db-preserve-detail.example.com")

    # -----------------------------------------------------------------------
    # T14: Horse index no region tabs
    # -----------------------------------------------------------------------

    def test_horse_index_has_no_region_tabs(self):
        """The horse index page should not have region tab navigation.
        Horse cards may still show racing region text — that is expected."""
        self.make_profile()

        response = self.client.get(reverse("public-horse-index"))

        self.assertEqual(response.status_code, 200)
        # No region-tabs nav element
        self.assertNotContains(response, "class=\"region-tabs\"")
        # Search form has no hidden region input
        self.assertNotContains(response, "name=\"region\"")
        # Region label is present on the horse card (design requires it)
        self.assertContains(response, "class=\"region-label\"")

    # -----------------------------------------------------------------------
    # T15: Horse old region URL redirects
    # -----------------------------------------------------------------------

    def test_horse_region_url_redirects(self):
        """/horses/?region=japan should redirect to /horses/."""
        self.make_profile()

        for region_value in (RacingRegion.JAPAN, "unknown"):
            with self.subTest(region=region_value):
                response = self.client.get(reverse("public-horse-index"), {"region": region_value})
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response["Location"], reverse("public-horse-index"))

    # -----------------------------------------------------------------------
    # T16: Horse redirect preserves other params
    # -----------------------------------------------------------------------

    def test_horse_region_redirect_preserves_other_params(self):
        """/horses/?region=france&q=Star&page=2 should redirect to /horses/?q=Star&page=2."""
        self.make_profile()

        response = self.client.get(
            reverse("public-horse-index"),
            {"region": RacingRegion.FRANCE, "q": "Star", "page": 2},
        )

        self.assertEqual(response.status_code, 301)
        self.assertIn("q=Star", response["Location"])
        self.assertIn("page=2", response["Location"])
        self.assertNotIn("region", response["Location"])

    # -----------------------------------------------------------------------
    # T17: Unified horse list (different regions together)
    # -----------------------------------------------------------------------

    def test_unified_horse_list_shows_all_regions(self):
        """Horse index should show profiles from all regions together."""
        self.make_profile(
            display_name_zh="日本马A",
            original_name="Japan Horse A",
            racing_region=RacingRegion.JAPAN,
            country="日本",
        )
        self.make_profile(
            display_name_zh="香港马B",
            original_name="HK Horse B",
            racing_region=RacingRegion.HONG_KONG,
            country="中国香港",
        )
        self.make_profile(
            display_name_zh="美国马C",
            original_name="US Horse C",
            racing_region=RacingRegion.UNITED_STATES,
            country="美国",
        )
        # Draft horse should not appear
        self.make_profile(
            display_name_zh="草稿马",
            original_name="Draft Horse",
            review_status=HorseProfileStatus.DRAFT,
        )

        response = self.client.get(reverse("public-horse-index"))

        self.assertContains(response, "日本马A")
        self.assertContains(response, "香港马B")
        self.assertContains(response, "美国马C")
        self.assertNotContains(response, "草稿马")

    # -----------------------------------------------------------------------
    # T19: Horse follow/unfollow still works (region-free)
    # -----------------------------------------------------------------------

    def test_horse_follow_preserves_next_without_region(self):
        """POST to follow should redirect to `next` param without adding region."""
        profile = self.make_profile()
        next_url = reverse("public-horse-index")

        response = self.client.post(
            reverse("public-horse-follow", args=[profile.id]),
            {"include_descendants": "1", "next": next_url},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], next_url)
        self.assertNotIn("region", response["Location"])

    def test_horse_unfollow_preserves_next_without_region(self):
        """POST to unfollow should redirect to `next` param without adding region."""
        profile = self.make_profile()
        next_url = reverse("public-horse-index")

        response = self.client.post(
            reverse("public-horse-follow", args=[profile.id]),
            {"intent": "unfollow", "next": next_url},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], next_url)
        self.assertNotIn("region", response["Location"])

    # -----------------------------------------------------------------------
    # T20: Horse detail shows country and racing_region
    # -----------------------------------------------------------------------

    def test_horse_detail_shows_country_in_basic_info(self):
        """Horse detail should show country in the '基础资料' section."""
        profile = self.make_profile(
            display_name_zh="测试马匹",
            country="法国",
            racing_region=RacingRegion.FRANCE,
        )

        response = self.client.get(reverse("public-horse-detail", args=[profile.id]))

        # Country shown in 基础资料 section
        self.assertContains(response, "国家/地区")
        self.assertContains(response, "法国")

    def test_horse_detail_shows_racing_region_in_hero(self):
        """Horse detail should show racing_region in the hero section."""
        profile = self.make_profile(
            display_name_zh="法国赛马",
            racing_region=RacingRegion.FRANCE,
            country="法国",
        )

        response = self.client.get(reverse("public-horse-detail", args=[profile.id]))

        # racing_region shown in hero (get_racing_region_display = "法国")
        self.assertContains(response, "法国")
        # Hero shows the racing region label
        self.assertContains(response, "horse-hero-kicker")

    # -----------------------------------------------------------------------
    # T21: Race calendar region filter still works
    # -----------------------------------------------------------------------

    def test_race_calendar_region_filter_still_works(self):
        """GET /races/?region=france should return 200 (not redirected)."""
        self.make_profile()

        response = self.client.get(reverse("public-race-calendar"), {"region": RacingRegion.FRANCE})

        # Race calendar should still allow region filtering
        self.assertEqual(response.status_code, 200)

    # -----------------------------------------------------------------------
    # T05_horse: Horse index pagination uses unified list
    # -----------------------------------------------------------------------

    def test_horse_index_pagination_uses_unified_list_after_legacy_region_redirect(self):
        """Horse index pagination should work across all regions, and old region URLs should redirect."""
        # Create 25+ profiles across different regions
        for index in range(20):
            self.make_profile(
                display_name_zh=f"日本马{index}",
                original_name=f"Japan Horse {index}",
                racing_region=RacingRegion.JAPAN,
                country="日本",
            )
        for index in range(10):
            self.make_profile(
                display_name_zh=f"香港马{index}",
                original_name=f"HK Horse {index}",
                racing_region=RacingRegion.HONG_KONG,
                country="中国香港",
            )

        # GET /horses/ without region - should show all 30 profiles paginated
        first_page = self.client.get(reverse("public-horse-index"))
        self.assertEqual(first_page.status_code, 200)

        # GET /horses/?region=japan - should redirect
        redirect_response = self.client.get(reverse("public-horse-index"), {"region": RacingRegion.JAPAN})
        self.assertEqual(redirect_response.status_code, 301)
        self.assertEqual(redirect_response["Location"], reverse("public-horse-index"))

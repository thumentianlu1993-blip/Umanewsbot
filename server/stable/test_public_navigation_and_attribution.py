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

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

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

    @patch("stable.views._race_calendar_queryset")
    def test_race_calendar_redirects_malformed_crawler_query_before_database_work(
        self,
        calendar_queryset,
    ):
        response = self.client.get(
            f"{reverse('public-race-calendar')}?tab=all&grade=g1%C2%AEion%3Dfrance&tracking=meta"
        )

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], f"{reverse('public-race-calendar')}?tab=all")
        calendar_queryset.assert_not_called()

    def test_race_calendar_filter_links_only_copy_normalized_values(self):
        response = self.client.get(
            reverse("public-race-calendar"),
            {"tab": "all", "grade": "invalid-grade", "region": "invalid-region"},
        )

        self.assertEqual(response.status_code, 200)
        urls = [
            response.context["all_tab_url"],
            response.context["key_tab_url"],
            *(tab["url"] for tab in response.context["region_tabs"]),
            *(tab["url"] for tab in response.context["grade_tabs"]),
            *(tab["url"] for tab in response.context["when_tabs"]),
        ]
        self.assertTrue(all("invalid-grade" not in url for url in urls))
        self.assertTrue(all("invalid-region" not in url for url in urls))

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


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class PublicNavCurrentLocationTests(TestCase):
    """真实页面导航语义候选；D016只准备源码，不把静态检查称作RED。

    每次GET先核HTTP、固定链接和原active映射，再检查新语义。只限制
    关注cookie和HorseFollow无写，允许CSRF cookie正常产生；不输出token/HTML。
    """

    def setUp(self):
        self.serial = 0

    def _profile(self, *, hidden=False):
        self.serial += 1
        term = TermEntry(
            term_type=TermType.HORSE, source_language=SourceLanguage.JAPANESE,
            source_ja=f"D016 Synthetic Horse {self.serial}",
            target_zh=f"导航合成马{self.serial}", racing_region=RacingRegion.JAPAN,
        )
        term.full_clean()
        term.save()
        profile = HorseProfile(
            primary_term=term, display_name_zh=term.target_zh,
            original_name=term.source_ja, racing_region=RacingRegion.JAPAN,
            review_status=HorseProfileStatus.HIDDEN if hidden else HorseProfileStatus.PUBLISHED,
        )
        profile.full_clean()
        profile.save()
        return profile

    def _event(self, *, hidden=False):
        self.serial += 1
        day = timezone.localdate() + timedelta(days=1)
        event = RaceEvent(
            year=day.year, edition_year=day.year, slug=f"d016-navigation-{self.serial}",
            original_name=f"D016 Synthetic Race {self.serial}",
            chinese_name=f"导航合成赛{self.serial}", country_region=RacingRegion.JAPAN,
            racecourse="D016 Synthetic Park", grade_text="G1", surface="turf",
            local_date=day,
            visibility_status=RaceEventVisibility.HIDDEN if hidden else RaceEventVisibility.PUBLISHED,
        )
        event.full_clean()
        event.save()
        return event

    def _article(self):
        self.serial += 1
        now = timezone.now()
        article = NewsArticle(
            source_site=SourceSite.NETKEIBA, source_mode=SourceMode.LATEST,
            source_article_id=f"d016-navigation-{self.serial}",
            source_url=f"https://example.com/d016/{self.serial}",
            title_ja="D016 Synthetic News", title_zh="导航合成新闻",
            translated_title_zh="导航合成新闻", body_ja_raw="Synthetic body",
            body_ja_normalized="Synthetic body", body_zh="导航合成正文",
            translated_body_zh="导航合成正文", published_at=now,
            published_to_web_at=now, workflow_status=WorkflowStatus.PUBLISHED,
        )
        article.full_clean()
        article.save()
        return article

    def _read(self, url, *, status=200):
        from stable.services.horse_profiles import FOLLOW_COOKIE_NAME

        before = list(HorseFollow.objects.order_by("pk").values())
        cookie = self.client.cookies.get(FOLLOW_COOKIE_NAME)
        cookie_before = cookie.value if cookie is not None else None
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, "前件：真实GET状态不符")
        after = list(HorseFollow.objects.order_by("pk").values())
        self.assertTrue(before == after, "GET改变HorseFollow行/字段/归属")
        self.assertFalse(FOLLOW_COOKIE_NAME in response.cookies,
                         "GET不应新建/替换关注cookie；允许正常CSRF cookie")
        cookie = self.client.cookies.get(FOLLOW_COOKIE_NAME)
        cookie_after = cookie.value if cookie is not None else None
        self.assertTrue(cookie_before == cookie_after, "GET旋转/创建关注cookie")
        return response

    @staticmethod
    def _parse_menus(html):
        from html.parser import HTMLParser

        class Menus(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.menus = []
                self.stack = []
                self.current = None
                self.link = None

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if tag == "nav":
                    self.stack.append(self.current)
                    if values.get("aria-label") in {"公开站点导航", "移动端导航"}:
                        self.current = {"attrs": values, "links": []}
                        self.menus.append(self.current)
                    else:
                        self.current = None
                elif tag == "a" and self.current is not None:
                    self.link = {"attrs": values, "pairs": attrs, "text": ""}

            def handle_data(self, data):
                if self.link is not None:
                    self.link["text"] += data

            def handle_endtag(self, tag):
                if tag == "a" and self.link is not None:
                    self.current["links"].append(self.link)
                    self.link = None
                elif tag == "nav" and self.stack:
                    self.current = self.stack.pop()

        parser = Menus()
        parser.feed(html)
        return parser.menus

    def _menus(self, url, *, section, route, empty_context=None, expected_query=None):
        response = self._read(url)
        self.assertEqual(response.resolver_match.url_name, route,
                         "前件：必须到达预期真实路由")
        if empty_context is not None:
            self.assertEqual(len(response.context[empty_context]), 0,
                             "前件：指定空态必须由真实context确认")
        if expected_query is not None:
            self.assertTrue(response.context["filters"]["q"] == expected_query,
                            "前件：真实搜索条件必须保留")
        menus = self._parse_menus(response.content.decode("utf-8"))
        self.assertEqual(len(menus), 2, "前件：两个导航区域必须均存在")
        urls = [reverse("public-news-feed"), reverse("public-race-calendar"),
                reverse("public-horse-index"), reverse("public-horse-follows")]
        selected = None if section is None else {
            "home": urls[0], "races": urls[1], "horses": urls[2], "follows": urls[3],
        }[section]
        expected = {
            "公开站点导航": ("site-nav", ["首页", "赛事日历", "马匹", "我的关注"]),
            "移动端导航": ("mobile-tabbar", ["首页", "赛事", "马匹", "关注"]),
        }
        result = {}
        for label, (css_class, texts) in expected.items():
            found = [menu for menu in menus if menu["attrs"].get("aria-label") == label]
            self.assertEqual(len(found), 1, "前件：导航区域不能重复/缺失")
            menu = found[0]
            self.assertTrue(css_class in menu["attrs"].get("class", "").split())
            self.assertEqual(len(menu["links"]), 4, "前件：原四链接保留")
            actual = [(link["attrs"].get("href"), " ".join(link["text"].split()))
                      for link in menu["links"]]
            self.assertTrue(actual == list(zip(urls, texts)), "前件：固定导航文字/href不符")
            for link, href in zip(menu["links"], urls):
                self.assertEqual(len(link["pairs"]), len(link["attrs"]),
                                 "导航链接不能含重复HTML属性")
                wanted = ["active"] if href == selected else []
                self.assertTrue(link["attrs"].get("class", "").split() == wanted,
                                "前件：原active映射不符；期望来自固定route而非class")
            result[label] = menu
        return result

    def _current(self, menu, expected_href):
        marked = [link for link in menu["links"] if "aria-current" in link["attrs"]]
        if expected_href is None:
            self.assertFalse(marked, "回归：新闻详情原无当前频道，不新增映射")
        else:
            self.assertEqual(len(marked), 1, "业务 RED：已知频道必须唯一指定当前项")
            self.assertTrue(marked[0]["attrs"].get("href") == expected_href
                            and marked[0]["attrs"].get("aria-current") == "location",
                            "业务 RED：当前频道需要正确对象的aria-current=location")

    def _both_current(self, menus, expected_href):
        self._current(menus["公开站点导航"], expected_href)
        self._current(menus["移动端导航"], expected_href)

    def test_empty_follow_header_requires_current_location(self):
        url = reverse("public-horse-follows")
        menus = self._menus(url, section="follows", route="public-horse-follows",
                            empty_context="follows")
        self._current(menus["公开站点导航"], url)

    def test_empty_follow_mobile_requires_current_location(self):
        url = reverse("public-horse-follows")
        menus = self._menus(url, section="follows", route="public-horse-follows",
                            empty_context="follows")
        self._current(menus["移动端导航"], url)

    def test_empty_home_has_current_home_in_both_menus(self):
        url = reverse("public-news-feed")
        menus = self._menus(url, section="home", route="public-news-feed")
        self._both_current(menus, url)

    def test_empty_horse_index_has_current_horses_in_both_menus(self):
        url = reverse("public-horse-index")
        menus = self._menus(url, section="horses", route="public-horse-index",
                            empty_context="horse_profiles")
        self._both_current(menus, url)

    def test_horse_search_empty_keeps_current_horses(self):
        from urllib.parse import urlencode

        self._profile()
        url = reverse("public-horse-index")
        menus = self._menus(url + "?" + urlencode({"q": "D016-no-match"}),
                            section="horses", route="public-horse-index",
                            empty_context="horse_profiles", expected_query="D016-no-match")
        self._both_current(menus, url)

    def test_calendar_canonical_get_has_current_races(self):
        url = reverse("public-race-calendar")
        menus = self._menus(url + "?tab=all", section="races", route="public-race-calendar")
        self._both_current(menus, url)

    def test_published_horse_detail_has_current_horses(self):
        profile = self._profile()
        menus = self._menus(profile.public_path, section="horses", route="public-horse-detail")
        self._both_current(menus, reverse("public-horse-index"))

    def test_published_race_detail_has_current_races(self):
        event = self._event()
        menus = self._menus(event.public_path, section="races", route="public-race-detail")
        self._both_current(menus, reverse("public-race-calendar"))

    def test_legacy_race_path_redirects_then_has_current_races(self):
        from urllib.parse import urlsplit

        event = self._event()
        old_path = event.public_path
        event.slug += "-canonical"
        event.full_clean()
        event.save()
        redirect = self._read(old_path, status=301)
        target = redirect["Location"]
        parsed = urlsplit(target)
        self.assertTrue(not parsed.scheme and not parsed.netloc
                        and parsed.path == event.public_path,
                        "前件：真实旧路径301必须指向本赛事canonical")
        menus = self._menus(target, section="races", route="public-race-detail")
        self._both_current(menus, reverse("public-race-calendar"))

    def test_article_detail_keeps_both_menus_without_current_item(self):
        article = self._article()
        menus = self._menus(article.public_path, section=None, route="public-article-detail")
        self._both_current(menus, None)

    def test_hidden_horse_and_race_details_are_404(self):
        profile = self._profile(hidden=True)
        event = self._event(hidden=True)
        self._read(profile.public_path, status=404)
        self._read(event.public_path, status=404)

    def test_follow_get_preserves_rows_and_follower_cookie(self):
        from stable.services.horse_profiles import (
            FOLLOW_COOKIE_NAME, follow_horse, signed_follow_token, token_hash_from_cookie,
        )

        profile = self._profile()
        cookie = signed_follow_token()
        token_hash = token_hash_from_cookie(cookie)
        self.assertTrue(bool(token_hash), "前件：真实关注producer/decoder")
        follow_horse(token_hash, profile, include_descendants=True)
        self.assertEqual(HorseFollow.objects.count(), 1, "前件：既有关注行必须实际存在")
        self.client.cookies[FOLLOW_COOKIE_NAME] = cookie
        self._menus(reverse("public-horse-follows"), section="follows", route="public-horse-follows")

    def test_calendar_query_redirect_is_precondition_before_race_marker(self):
        url = reverse("public-race-calendar")
        redirect = self._read(url + "?tab=all&grade=g1%C2%AEion%3Dfrance&tracking=meta", status=301)
        self.assertTrue(redirect["Location"] == url + "?tab=all",
                        "前件：既有canonical301目标不符")
        menus = self._menus(redirect["Location"], section="races", route="public-race-calendar")
        self._both_current(menus, url)

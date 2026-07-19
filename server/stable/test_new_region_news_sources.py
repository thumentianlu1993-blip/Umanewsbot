from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.auth import get_user_model
from django.contrib.admin.sites import AdminSite
from django.forms.models import model_to_dict
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable.adapters.base import (
    CanonicalNewsDraft,
    SourceArticleDetail,
    SourceArticleStub,
)
from stable.adapters.international import (
    FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS,
    FIRST_VERSION_INTERNATIONAL_PROBES,
    INTERNATIONAL_ADAPTERS,
)
from stable.admin import RaceEventAdmin
from stable.forms import HorseProfileForm, RaceEventForm
from stable.models import (
    AttributionStatus,
    AutomationStatus,
    CrawlJob,
    HorseProfile,
    NewsArticle,
    NewsSnapshot,
    NewsSource,
    ProductionWindow,
    ProductionWindowKind,
    ProductionWindowMode,
    ProductionWindowStatus,
    PushTarget,
    RaceEvent,
    RacingRegion,
    ReviewMode,
    SourceErrorCategory,
    SourceKind,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TaskStatus,
    TermEntry,
    TermType,
    WorkflowStatus,
)
from stable.services.automation import is_ready_for_auto_publish
from stable.services.historical_race_inventory import (
    SUPPORTED_REGIONS as HISTORICAL_RACE_REGIONS,
)
from stable.services.ingestion import upsert_article_from_draft
from stable.services.multiregion import PRODUCTION_REGIONS
from stable.services.news_attribution import (
    SUPPORTED_REGIONS as NEWS_ATTRIBUTION_REGIONS,
    infer_article_attribution,
)
from stable.services.p0_horse_profiles import P0_REGIONS
from stable.services.qq_auto_push import should_push_news_to_qq
from stable.services.regions import RACE_EVENT_FORM_REGIONS
from stable.services.sources import BUILTIN_SOURCE_DEFINITIONS, sync_builtin_sources
from stable.services.http import DEFAULT_HEADERS, get_bounded_html, get_bytes
from stable.tasks import (
    _crawl_international_source,
    _http_status_code_from_exception,
    crawl_news_source_task,
)


OLD_STRUCTURED_DATA_REGIONS = {
    "japan",
    "hong_kong",
    "united_kingdom",
    "france",
    "united_states",
}
NEW_NEWS_REGIONS = {
    "ireland",
    "canada",
    "united_arab_emirates",
    "saudi_arabia",
    "australia",
}
EXPECTED_REGION_LABELS = {
    "ireland": "爱尔兰",
    "canada": "加拿大",
    "united_arab_emirates": "阿联酋",
    "saudi_arabia": "沙特阿拉伯",
    "australia": "澳大利亚",
}
EXPECTED_SOURCE_SITES = {
    "hri_news",
    "woodbine_news",
    "emirates_racing_authority",
    "jcsa_news",
    "racing_victoria_news",
}
EXPECTED_SOURCES = {
    "hri_news": ("hri_news", "ireland"),
    "woodbine_news": ("woodbine_news", "canada"),
    "emirates_racing_authority": (
        "emirates_racing_authority",
        "united_arab_emirates",
    ),
    "jcsa_news": ("jcsa_news", "saudi_arabia"),
    "racing_victoria_news": ("racing_victoria_news", "australia"),
}
EXPECTED_SOURCE_ENDPOINTS = {
    "hri_news": {
        "homepage_url": "https://www.hri.ie/news-and-media",
        "feed_url": "https://www.hri.ie/news-and-media",
        "permission": "blocked",
    },
    "woodbine_news": {
        "homepage_url": "https://woodbine.com/news/",
        "feed_url": "https://woodbine.com/news/",
        "permission": "blocked",
    },
    "emirates_racing_authority": {
        "homepage_url": "https://emiratesracing.com/news/",
        "feed_url": "https://emiratesracing.com/news/",
        "permission": "blocked",
    },
    "jcsa_news": {
        "homepage_url": "https://jcsa.sa/en/news/",
        "feed_url": "https://jcsa.sa/api/news/en/0/12",
        "permission": "unknown",
    },
    "racing_victoria_news": {
        "homepage_url": "https://www.racingvictoria.com.au/news",
        "feed_url": "https://www.racingvictoria.com.au/sitemap.xml",
        "permission": "unknown",
    },
}
ADAPTER_CASES = {
    "hri_news": {
        "listing_url": "https://www.hri.ie/news-and-media",
        "article_path": "/news/details/sample-one",
        "timezone": "Europe/Dublin",
    },
    "woodbine_news": {
        "listing_url": "https://woodbine.com/news/",
        "article_path": "/woodbine-news/sample-one",
        "timezone": "America/Toronto",
    },
    "emirates_racing_authority": {
        "listing_url": "https://emiratesracing.com/news/",
        "article_path": "/news/sample-one",
        "timezone": "Asia/Dubai",
    },
    "jcsa_news": {
        "listing_url": "https://jcsa.sa/api/news/en/0/12",
        "article_path": "/en/news/sample-one",
        "timezone": "Asia/Riyadh",
    },
    "racing_victoria_news": {
        "listing_url": "https://www.racingvictoria.com.au/sitemap.xml",
        "article_path": "/news/2026/07/18/sample-one",
        "timezone": "Australia/Melbourne",
    },
}


def _tab_values(tabs) -> set[str]:
    return {
        str(item.get("value", "") if isinstance(item, dict) else item[0])
        for item in tabs
        if (item.get("value", "") if isinstance(item, dict) else item[0])
    }


def _listing_fixture(article_path: str, *, listing_url: str) -> str:
    if listing_url.endswith("/sitemap.xml"):
        article_url = urljoin(listing_url, article_path)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>{article_url}?utm_source=contract</loc></url>
              <url><loc>{article_url}-two?utm_medium=email</loc></url>
              <url><loc>{article_url}?utm_source=duplicate</loc></url>
              <url><loc>https://example.net/news/2026/07/18/external</loc></url>
            </urlset>
        """
    return f"""
        <html><body>
          <nav><a href="/about">About us</a></nav>
          <section class="listing media-list">
            <article class="news-item article-card">
              <a href="{article_path}?utm_source=contract#top">
                Sample championship report
              </a>
            </article>
            <article class="news-item article-card">
              <a href="{article_path}-two?utm_medium=email">
                Second racing report
              </a>
            </article>
            <article class="news-item article-card">
              <a href="{article_path}?utm_source=duplicate">
                Duplicate tracking URL
              </a>
            </article>
            <article class="news-item article-card">
              <a href="https://example.net/news/external">External story</a>
            </article>
          </section>
        </body></html>
    """


def _detail_fixture(
    raw_time: str | None,
    *,
    adapter_key: str = "",
) -> str:
    if adapter_key == "racing_victoria_news":
        return _rv_next_data_fixture(
            article_date=raw_time or "",
            title="Sample championship report",
            body_html=(
                "<p>The first material paragraph contains racing news.</p>"
                "<p>The second material paragraph confirms the result.</p>"
            ),
        )
    if raw_time and adapter_key == "jcsa_news":
        time_html = (
            '<div class="text-black-body font-inter text-small-body">'
            f"{raw_time}</div>"
        )
    elif raw_time:
        time_html = (
            f'<time class="date published" datetime="{raw_time}">{raw_time}</time>'
        )
    else:
        time_html = ""
    return f"""
        <html>
          <head><meta property="og:title" content="Sample championship report"></head>
          <body>
            <main>
              <article class="article-body entry-content content content-area">
                <h1 class="article-title">Sample championship report</h1>
                <div class="author byline">By Ada Editor</div>
                {time_html}
                <p>The first material paragraph contains racing news.</p>
                <p>The second material paragraph confirms the result.</p>
                <aside class="related">Related stories should not be copied.</aside>
                <div class="betting">Bet now with a promotional offer.</div>
                <footer>Copyright footer should not be copied.</footer>
              </article>
            </main>
          </body>
        </html>
    """


class NewRegionIdentityTests(TestCase):
    def test_five_regions_have_independent_persistent_choices(self):
        choices = dict(RacingRegion.choices)

        self.assertTrue(
            NEW_NEWS_REGIONS.issubset(choices),
            f"RacingRegion 缺少新地区：{sorted(NEW_NEWS_REGIONS - set(choices))}",
        )
        self.assertNotIn("middle_east", choices)
        for value, label in EXPECTED_REGION_LABELS.items():
            self.assertEqual(choices[value], label)
            self.assertLessEqual(len(value), 32)
        self.assertEqual(len(choices), len(set(choices)))

    def test_news_regions_expand_without_expanding_horse_or_race_data(self):
        expected_news_production = OLD_STRUCTURED_DATA_REGIONS | NEW_NEWS_REGIONS
        self.assertEqual(set(PRODUCTION_REGIONS), expected_news_production)
        self.assertEqual(
            set(NEWS_ATTRIBUTION_REGIONS),
            expected_news_production | {"other"},
        )
        self.assertEqual(set(P0_REGIONS), OLD_STRUCTURED_DATA_REGIONS)
        self.assertEqual(set(HISTORICAL_RACE_REGIONS), OLD_STRUCTURED_DATA_REGIONS)

        from stable import views

        self.assertTrue(
            hasattr(views, "PUBLIC_NEWS_REGION_TABS"),
            "新闻和马匹仍共用 PUBLIC_REGION_TABS，缺少 PUBLIC_NEWS_REGION_TABS",
        )
        self.assertTrue(
            hasattr(views, "PUBLIC_HORSE_REGION_TABS"),
            "新闻和马匹仍共用 PUBLIC_REGION_TABS，缺少 PUBLIC_HORSE_REGION_TABS",
        )
        news_tabs = _tab_values(views.PUBLIC_NEWS_REGION_TABS)
        horse_tabs = _tab_values(views.PUBLIC_HORSE_REGION_TABS)
        self.assertEqual(news_tabs, expected_news_production)
        self.assertEqual(horse_tabs, OLD_STRUCTURED_DATA_REGIONS)
        self.assertTrue(NEW_NEWS_REGIONS.isdisjoint(horse_tabs))

    def test_five_source_sites_and_adapter_keys_are_registered(self):
        site_values = set(SourceSite.values)
        self.assertTrue(
            EXPECTED_SOURCE_SITES.issubset(site_values),
            f"SourceSite 缺少：{sorted(EXPECTED_SOURCE_SITES - site_values)}",
        )
        self.assertTrue(
            EXPECTED_SOURCE_SITES.issubset(INTERNATIONAL_ADAPTERS),
            "国际 adapter registry 未注册全部五个新来源",
        )


class NewRegionSourceDefinitionTests(TestCase):
    def test_builtin_definitions_have_correct_identity_and_default_off(self):
        definitions = {
            str(item["adapter_key"]): item
            for item in BUILTIN_SOURCE_DEFINITIONS
            if str(item.get("adapter_key", "")) in EXPECTED_SOURCES
        }
        self.assertEqual(set(definitions), set(EXPECTED_SOURCES))
        for adapter_key, (source_site, region) in EXPECTED_SOURCES.items():
            with self.subTest(adapter_key=adapter_key):
                definition = definitions[adapter_key]
                self.assertEqual(str(definition["source_site"]), source_site)
                self.assertEqual(str(definition["racing_region"]), region)
                self.assertEqual(str(definition["source_mode"]), SourceMode.OFFICIAL)
                self.assertEqual(str(definition["source_language"]), SourceLanguage.ENGLISH)
                self.assertEqual(str(definition["language"]), SourceLanguage.ENGLISH)
                self.assertFalse(definition["enabled"])
                expected_endpoint = EXPECTED_SOURCE_ENDPOINTS[adapter_key]
                for field_name in ("homepage_url", "feed_url"):
                    with self.subTest(
                        adapter_key=adapter_key,
                        field=field_name,
                    ):
                        self.assertEqual(
                            str(definition[field_name]),
                            expected_endpoint[field_name],
                        )
                with self.subTest(
                    adapter_key=adapter_key,
                    field="permission_note",
                ):
                    self.assertIn(
                        (
                            "automation_permission_status="
                            f"{expected_endpoint['permission']}"
                        ),
                        str(definition.get("notes") or ""),
                    )

    def test_source_sync_creates_five_independent_sources_default_off(self):
        sync_builtin_sources()

        sources = NewsSource.objects.filter(adapter_key__in=EXPECTED_SOURCES)
        self.assertEqual(sources.count(), 5)
        for source in sources:
            with self.subTest(adapter_key=source.adapter_key):
                expected_site, expected_region = EXPECTED_SOURCES[source.adapter_key]
                self.assertEqual(source.source_site, expected_site)
                self.assertEqual(source.racing_region, expected_region)
                self.assertEqual(source.source_mode, SourceMode.OFFICIAL)
                self.assertEqual(source.source_language, SourceLanguage.ENGLISH)
                self.assertFalse(source.enabled)
                self.assertFalse(source.production_approved)


class LegacyOtherModelFormRegressionTests(TestCase):
    def test_race_event_form_preserves_legacy_other_when_editing_notes(self):
        event = RaceEvent.objects.create(
            year=2026,
            slug="legacy-other-race",
            series_key="legacy-other-race",
            original_name="Legacy Other Race",
            chinese_name="旧其他地区赛事",
            country_region=RacingRegion.OTHER,
            racecourse="Legacy Course",
            grade_text="Listed",
            surface="turf",
        )
        data = model_to_dict(event, fields=RaceEventForm.Meta.fields)
        data.update(
            {
                "country_region": RacingRegion.OTHER,
                "notes": "仅修改备注",
            }
        )

        form = RaceEventForm(data=data, instance=event)

        self.assertTrue(form.is_valid(), form.errors.as_json())
        saved = form.save()
        self.assertEqual(saved.country_region, RacingRegion.OTHER)
        self.assertEqual(saved.notes, "仅修改备注")

    def test_horse_profile_form_preserves_legacy_other_when_editing_review_notes(self):
        primary_term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.OTHER,
            source_ja="Legacy Other Horse",
            target_zh="旧其他地区马匹",
        )
        profile = HorseProfile.objects.create(
            primary_term=primary_term,
            display_name_zh="旧其他地区马匹",
            original_name="Legacy Other Horse",
            racing_region=RacingRegion.OTHER,
        )
        data = model_to_dict(profile, fields=HorseProfileForm.Meta.fields)
        data.update(
            {
                "racing_region": RacingRegion.OTHER,
                "review_notes": "仅修改审核备注",
                "locked_fields": [],
            }
        )

        form = HorseProfileForm(data=data, instance=profile)

        self.assertTrue(form.is_valid(), form.errors.as_json())
        saved = form.save()
        self.assertEqual(saved.racing_region, RacingRegion.OTHER)
        self.assertEqual(saved.review_notes, "仅修改审核备注")


class RaceEventAdminFormRegressionTests(TestCase):
    def test_admin_country_region_choices_stay_with_race_form_scope(self):
        request = RequestFactory().get("/admin/stable/raceevent/add/")
        request.user = get_user_model().objects.create_superuser(
            username="race-event-admin-fixture",
            email="race-event-admin@example.test",
            password="test-password",
        )
        model_admin = RaceEventAdmin(RaceEvent, AdminSite())

        form_class = model_admin.get_form(request)
        actual_regions = [
            str(value)
            for value, _label in form_class.base_fields[
                "country_region"
            ].choices
            if str(value)
        ]
        expected_regions = [str(value) for value in RACE_EVENT_FORM_REGIONS]

        with self.subTest(contract="legacy_other_visible"):
            self.assertIn(RacingRegion.OTHER, actual_regions)
        with self.subTest(contract="exact_race_form_scope"):
            self.assertEqual(actual_regions, expected_regions)
        with self.subTest(contract="news_only_regions_excluded"):
            self.assertTrue(
                NEW_NEWS_REGIONS.isdisjoint(actual_regions),
                f"RaceEventAdmin 不得暴露新闻专属地区："
                f"{sorted(NEW_NEWS_REGIONS.intersection(actual_regions))}",
            )


class NewRegionAdapterContractTests(TestCase):
    def _adapter(self, adapter_key: str):
        self.assertIn(
            adapter_key,
            INTERNATIONAL_ADAPTERS,
            f"缺少 adapter registry key: {adapter_key}",
        )
        return INTERNATIONAL_ADAPTERS[adapter_key]()

    def _detail_or_failure(self, adapter, fixture: str, *, url: str):
        try:
            return adapter.parse_detail_html(fixture, url=url)
        except Exception as exc:
            self.fail(
                f"{adapter.source_site} 合同详情 fixture 不应抛异常：{exc}"
            )

    def test_each_adapter_parses_only_canonical_internal_listing_items(self):
        for adapter_key, case in ADAPTER_CASES.items():
            with self.subTest(adapter_key=adapter_key):
                adapter = self._adapter(adapter_key)
                html = _listing_fixture(
                    case["article_path"],
                    listing_url=case["listing_url"],
                )
                stubs = adapter.parse_listing_html(
                    html,
                    url=case["listing_url"],
                    mode=SourceMode.OFFICIAL,
                )

                self.assertEqual(len(stubs), 2)
                self.assertTrue(all(str(stub.source_site) == adapter_key for stub in stubs))
                self.assertTrue(all(str(stub.source_mode) == SourceMode.OFFICIAL for stub in stubs))
                self.assertTrue(all("utm_" not in stub.source_url for stub in stubs))
                self.assertTrue(all("#" not in stub.source_url for stub in stubs))
                self.assertTrue(all(stub.published_at is None for stub in stubs))
                repeated = adapter.parse_listing_html(
                    html,
                    url=case["listing_url"],
                    mode=SourceMode.OFFICIAL,
                )
                self.assertEqual(
                    [stub.source_article_id for stub in stubs],
                    [stub.source_article_id for stub in repeated],
                )

    def test_each_adapter_parses_detail_body_author_and_verified_local_time(self):
        raw_time = "2026-07-18T09:30:00"
        for adapter_key, case in ADAPTER_CASES.items():
            with self.subTest(adapter_key=adapter_key):
                adapter = self._adapter(adapter_key)
                article_url = urljoin(case["listing_url"], case["article_path"])
                detail = self._detail_or_failure(
                    adapter,
                    _detail_fixture(raw_time, adapter_key=adapter_key),
                    url=article_url,
                )

                expected_utc = (
                    datetime(2026, 7, 18, 9, 30, tzinfo=ZoneInfo(case["timezone"]))
                    .astimezone(dt_timezone.utc)
                )
                self.assertEqual(detail.title_ja, "Sample championship report")
                self.assertIn("first material paragraph", detail.body_ja_normalized)
                self.assertIn("second material paragraph", detail.body_ja_normalized)
                self.assertNotIn("Related stories", detail.body_ja_normalized)
                self.assertNotIn("Bet now", detail.body_ja_normalized)
                self.assertNotIn("Copyright footer", detail.body_ja_normalized)
                self.assertEqual(detail.published_at, expected_utc)
                self.assertEqual(
                    detail.metadata.get("author"),
                    "" if adapter_key == "racing_victoria_news" else "By Ada Editor",
                )
                self.assertIs(detail.metadata.get("published_at_verified"), True)
                evidence = detail.metadata.get("published_at_evidence") or {}
                self.assertEqual(evidence.get("raw"), raw_time)
                self.assertEqual(evidence.get("timezone"), case["timezone"])
                self.assertEqual(evidence.get("precision"), "minute")
                self.assertTrue(evidence.get("parser_version"))
                self.assertIs(evidence.get("verified"), True)

    def test_each_adapter_marks_date_only_as_local_noon(self):
        raw_date = "2026-07-18"
        for adapter_key, case in ADAPTER_CASES.items():
            with self.subTest(adapter_key=adapter_key):
                adapter = self._adapter(adapter_key)
                detail = self._detail_or_failure(
                    adapter,
                    _detail_fixture(raw_date, adapter_key=adapter_key),
                    url=case["listing_url"],
                )
                expected_utc = (
                    datetime(2026, 7, 18, 12, 0, tzinfo=ZoneInfo(case["timezone"]))
                    .astimezone(dt_timezone.utc)
                )
                evidence = detail.metadata.get("published_at_evidence") or {}
                self.assertEqual(detail.published_at, expected_utc)
                self.assertEqual(evidence.get("precision"), "date")
                self.assertEqual(evidence.get("timezone"), case["timezone"])
                self.assertIs(evidence.get("verified"), True)

    def test_each_adapter_rejects_detail_without_trusted_published_time(self):
        for adapter_key, case in ADAPTER_CASES.items():
            with self.subTest(adapter_key=adapter_key):
                adapter = self._adapter(adapter_key)
                source_url = urljoin(
                    case["listing_url"],
                    case["article_path"],
                )
                stub = SourceArticleStub(
                    source_site=adapter.source_site,
                    source_mode=SourceMode.OFFICIAL,
                    source_article_id=f"{adapter_key}-missing-time",
                    source_url=source_url,
                    title_ja="Missing time fixture",
                    published_at=None,
                )
                with self.assertRaisesRegex(
                    (ValueError, RuntimeError),
                    "missing_published_at",
                ):
                    detail = adapter.parse_detail_html(
                        _detail_fixture(None, adapter_key=adapter_key),
                        url=stub.source_url,
                    )
                    adapter.normalize_source_payload(stub, detail)


def _source_for_outcome_test(adapter_key: str) -> NewsSource:
    return NewsSource.objects.create(
        name=f"{adapter_key} source",
        homepage_url="https://fixture.example/",
        feed_url="https://fixture.example/news/",
        source_type="builtin",
        language=SourceLanguage.ENGLISH,
        racing_region="ireland",
        source_language=SourceLanguage.ENGLISH,
        source_kind=SourceKind.OFFICIAL,
        adapter_key=adapter_key,
        source_site=f"{adapter_key}_site",
        source_mode=SourceMode.OFFICIAL,
        enabled=False,
        production_approved=False,
    )


class _EmptyListingAdapter:
    skipped_items: list[str] = []
    last_listing_query_errors: list[dict] = []

    def fetch_listing(self, mode, page):
        return []


class _AllDetailsFailedAdapter(_EmptyListingAdapter):
    def fetch_listing(self, mode, page):
        return [
            SimpleNamespace(
                source_url="https://fixture.example/news/broken",
            )
        ]

    def fetch_detail(self, source_url):
        raise ValueError("detail selector failed")


class _DuplicateAdapter(_EmptyListingAdapter):
    def __init__(self):
        self.source_site = "duplicate_outcome_site"

    def fetch_listing(self, mode, page):
        return [
            SourceArticleStub(
                source_site=self.source_site,
                source_mode=SourceMode.OFFICIAL,
                source_article_id="duplicate-1",
                source_url="https://fixture.example/news/duplicate-1",
                title_ja="Existing story",
                published_at=datetime(2026, 7, 18, 9, tzinfo=dt_timezone.utc),
            )
        ]

    def fetch_detail(self, source_url):
        return SourceArticleDetail(
            title_ja="Existing story",
            body_ja_raw="Existing body",
            body_ja_normalized="Existing body",
            published_at=datetime(2026, 7, 18, 9, tzinfo=dt_timezone.utc),
            images=[],
            metadata={
                "published_at_verified": True,
                "published_at_evidence": {
                    "raw": "2026-07-18T09:00:00Z",
                    "timezone": "UTC",
                    "precision": "minute",
                    "parser_version": "fixture-v1",
                    "verified": True,
                },
            },
        )

    def normalize_source_payload(self, stub, detail):
        return CanonicalNewsDraft(
            source_site=self.source_site,
            source_mode=SourceMode.OFFICIAL,
            source_article_id=stub.source_article_id,
            source_url=stub.source_url,
            title_ja=detail.title_ja,
            body_ja_raw=detail.body_ja_raw,
            body_ja_normalized=detail.body_ja_normalized,
            published_at=detail.published_at,
            images=[],
            racing_region="ireland",
            source_language=SourceLanguage.ENGLISH,
            source_kind=SourceKind.OFFICIAL,
            metadata=detail.metadata,
        )


class NewRegionCrawlOutcomeTests(TestCase):
    def test_http_200_empty_listing_is_failed_as_empty_listing(self):
        source = _source_for_outcome_test("empty_outcome")
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {"empty_outcome": _EmptyListingAdapter},
        ):
            with self.assertRaisesRegex(RuntimeError, "empty_listing"):
                _crawl_international_source(source)

        job = CrawlJob.objects.get(source=source)
        self.assertEqual(job.status, TaskStatus.FAILED)
        self.assertIn("empty_listing", job.error_message)
        self.assertEqual(NewsArticle.objects.count(), 0)

    def test_nonempty_listing_with_no_parsable_details_is_all_details_failed(self):
        source = _source_for_outcome_test("details_failed_outcome")
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {"details_failed_outcome": _AllDetailsFailedAdapter},
        ):
            with self.assertRaisesRegex(RuntimeError, "all_details_failed"):
                _crawl_international_source(source)

        job = CrawlJob.objects.get(source=source)
        self.assertEqual(job.status, TaskStatus.FAILED)
        self.assertIn("all_details_failed", job.error_message)
        self.assertEqual(NewsArticle.objects.count(), 0)

    def test_all_duplicates_is_successful_zero_new(self):
        source = _source_for_outcome_test("duplicate_outcome")
        NewsArticle.objects.create(
            source_config=source,
            source_site="duplicate_outcome_site",
            source_mode=SourceMode.OFFICIAL,
            racing_region="ireland",
            source_language=SourceLanguage.ENGLISH,
            source_article_id="duplicate-1",
            title_ja="Existing story",
            body_ja_raw="Existing body",
            body_ja_normalized="Existing body",
            published_at=datetime(2026, 7, 18, 9, tzinfo=dt_timezone.utc),
            source_url="https://fixture.example/news/duplicate-1",
        )
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {"duplicate_outcome": _DuplicateAdapter},
        ):
            result = _crawl_international_source(source)

        self.assertEqual(result["new_count"], 0)
        self.assertEqual(result["seen_count"], 1)
        self.assertEqual(result["source_summary"]["duplicates"], 1)
        job = CrawlJob.objects.get(source=source)
        self.assertEqual(job.status, TaskStatus.SUCCESS)


class _ProbeAdapter:
    source_site = "hri_news"
    source_mode = SourceMode.OFFICIAL
    racing_region = "ireland"
    source_language = SourceLanguage.ENGLISH
    adapter_version = "fixture-adapter-v1"
    parser_version = "fixture-parser-v1"
    automation_permission_status = "unknown"
    last_listing_http_status = 200
    last_listing_final_url = "https://www.hri.ie/news-and-media"
    last_listing_query_errors: list[dict] = []

    def listing_url(self, page, mode=None):
        return "https://www.hri.ie/news-and-media"

    def fetch_listing(self, mode, page):
        return [
            SourceArticleStub(
                source_site=self.source_site,
                source_mode=SourceMode.OFFICIAL,
                source_article_id="probe-1",
                source_url="https://www.hri.ie/news-and-media/probe-1",
                title_ja="Probe story",
                published_at=datetime(2026, 7, 18, 9, tzinfo=dt_timezone.utc),
            )
        ]

    def fetch_detail(self, source_url):
        return SourceArticleDetail(
            title_ja="Probe story",
            body_ja_raw="A sufficiently parsed probe body.",
            body_ja_normalized="A sufficiently parsed probe body.",
            published_at=datetime(2026, 7, 18, 9, tzinfo=dt_timezone.utc),
            images=[],
            original_content_html="<article>probe</article>",
            metadata={
                "published_at_verified": True,
                "published_at_evidence": {
                    "raw": "2026-07-18T10:00:00+01:00",
                    "timezone": "Europe/Dublin",
                    "precision": "minute",
                    "parser_version": self.parser_version,
                    "verified": True,
                },
            },
        )


class _ApprovedProbeAdapter(_ProbeAdapter):
    automation_permission_status = "approved"


class _FailingProbeAdapter(_ProbeAdapter):
    def fetch_listing(self, mode, page):
        raise RuntimeError("probe fixture failure")


class NewRegionProbeContractTests(TestCase):
    def _run_probe(self, adapter_class) -> dict:
        before = {
            "sources": NewsSource.objects.count(),
            "jobs": CrawlJob.objects.count(),
            "articles": NewsArticle.objects.count(),
            "windows": ProductionWindow.objects.count(),
        }
        stdout = io.StringIO()
        with mock.patch.dict(
            "stable.management.commands.probe_international_news_sources.INTERNATIONAL_ADAPTERS",
            {"hri_news": adapter_class},
        ):
            call_command(
                "probe_international_news_sources",
                source=["hri_news"],
                limit=1,
                json=True,
                stdout=stdout,
            )
        after = {
            "sources": NewsSource.objects.count(),
            "jobs": CrawlJob.objects.count(),
            "articles": NewsArticle.objects.count(),
            "windows": ProductionWindow.objects.count(),
        }
        self.assertEqual(after, before)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(len(payload), 1)
        return payload[0]

    def _assert_common_probe_schema(self, result: dict):
        required = {
            "source_key",
            "http_status",
            "final_url",
            "listing_url",
            "technical_status",
            "automation_permission_status",
            "effective_production_status",
            "adapter_version",
            "parser_version",
            "reviewed_at",
            "artifact_sha256",
            "parse_quality",
        }
        self.assertTrue(
            required.issubset(result),
            f"probe schema 缺少字段：{sorted(required - set(result))}",
        )
        self.assertEqual(result["source_key"], "hri_news")
        self.assertEqual(result["technical_status"], "accepted")
        self.assertRegex(result["artifact_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(result["reviewed_at"])

    def test_technical_acceptance_with_unknown_permission_is_blocked(self):
        result = self._run_probe(_ProbeAdapter)
        self._assert_common_probe_schema(result)
        self.assertEqual(result["automation_permission_status"], "unknown")
        self.assertEqual(result["effective_production_status"], "production_blocked")

    def test_only_approved_permission_is_effectively_eligible(self):
        result = self._run_probe(_ApprovedProbeAdapter)
        self._assert_common_probe_schema(result)
        self.assertEqual(result["automation_permission_status"], "approved")
        self.assertEqual(result["effective_production_status"], "eligible")

    def test_probe_rejects_detail_limit_over_two(self):
        with self.assertRaises(CommandError):
            call_command(
                "probe_international_news_sources",
                source=["hri_news"],
                limit=3,
                json=True,
                stdout=io.StringIO(),
            )

    def test_default_probe_matrices_exclude_new_sources_but_explicit_registry_keeps_them(self):
        default_keys = {key for key, _mode in FIRST_VERSION_INTERNATIONAL_PROBES}
        self.assertTrue(EXPECTED_SOURCE_SITES.isdisjoint(default_keys))
        self.assertTrue(
            EXPECTED_SOURCE_SITES.isdisjoint(FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        )
        self.assertTrue(EXPECTED_SOURCE_SITES.issubset(INTERNATIONAL_ADAPTERS))

    def test_human_output_prints_full_contract_for_success_and_error(self):
        for adapter_class, expected_technical in (
            (_ProbeAdapter, "accepted"),
            (_FailingProbeAdapter, "deferred"),
        ):
            with self.subTest(adapter=adapter_class.__name__):
                stdout = io.StringIO()
                with mock.patch.dict(
                    "stable.management.commands.probe_international_news_sources.INTERNATIONAL_ADAPTERS",
                    {"hri_news": adapter_class},
                ):
                    call_command(
                        "probe_international_news_sources",
                        source=["hri_news"],
                        limit=1,
                        stdout=stdout,
                    )
                output = stdout.getvalue()
                self.assertIn(f"technical_status={expected_technical}", output)
                self.assertIn("automation_permission_status=unknown", output)
                self.assertIn(
                    "effective_production_status=production_blocked",
                    output,
                )
                self.assertIn("adapter_version=fixture-adapter-v1", output)
                self.assertIn("parser_version=fixture-parser-v1", output)
                self.assertIn("reviewed_at=", output)
                self.assertRegex(output, r"artifact_sha256=[0-9a-f]{64}")


def _article_for_attribution(
    *,
    source_site: str,
    source_region: str,
    title: str,
    body: str,
) -> tuple[NewsArticle, NewsSource]:
    source = NewsSource(
        name=f"{source_site} fixture",
        homepage_url="https://fixture.example/",
        feed_url="https://fixture.example/news/",
        language=SourceLanguage.ENGLISH,
        racing_region=source_region,
        source_language=SourceLanguage.ENGLISH,
        source_kind=SourceKind.NEWS,
        adapter_key=source_site,
        source_site=source_site,
        source_mode=SourceMode.OFFICIAL,
        enabled=False,
        production_approved=False,
    )
    article = NewsArticle(
        source_site=source_site,
        source_mode=SourceMode.OFFICIAL,
        racing_region=source_region,
        source_language=SourceLanguage.ENGLISH,
        source_article_id=f"{source_site}-fixture",
        title_ja=title,
        body_ja_raw=body,
        body_ja_normalized=body,
        published_at=timezone.now(),
        source_url="https://fixture.example/news/fixture",
    )
    return article, source


class NewRegionAttributionTests(TestCase):
    def _infer(self, **kwargs):
        article, source = _article_for_attribution(**kwargs)
        return infer_article_attribution(article, source_config=source)

    def test_uk_source_reporting_irish_derby_is_ireland(self):
        result = self._infer(
            source_site="sporting_life",
            source_region="united_kingdom",
            title="Irish Derby at the Curragh produces a new champion",
            body="The field met at the Curragh for the Irish Derby.",
        )
        self.assertEqual(result.primary_region, "ireland")
        self.assertNotEqual(result.primary_region, "united_kingdom")

    def test_irish_source_reporting_cheltenham_is_uk_with_ireland_related(self):
        result = self._infer(
            source_site="hri_news",
            source_region="ireland",
            title="Irish-trained contender travels to Cheltenham",
            body="The Irish trainer sends the horse to the Cheltenham Festival.",
        )
        self.assertEqual(result.primary_region, "united_kingdom")
        self.assertIn("ireland", result.related_regions)

    def test_irish_source_foreign_ascot_does_not_match_hri_inside_thrilling(self):
        result = self._infer(
            source_site="hri_news",
            source_region="ireland",
            title="Royal Ascot result",
            body="Thrilling finish at Ascot",
        )
        self.assertEqual(result.primary_region, RacingRegion.UNITED_KINGDOM)
        self.assertNotIn(RacingRegion.IRELAND, result.related_regions)

    def test_global_source_reporting_woodbine_is_canada(self):
        result = self._infer(
            source_site="tdn",
            source_region="united_states",
            title="Woodbine Mile and King's Plate stars return",
            body="The Canadian races take place at Woodbine.",
        )
        self.assertEqual(result.primary_region, "canada")
        self.assertNotEqual(result.primary_region, "united_states")

    def test_canadian_source_reporting_breeders_cup_is_us_with_canada_related(self):
        result = self._infer(
            source_site="woodbine_news",
            source_region="canada",
            title="Canadian runner heads to the Breeders' Cup",
            body="The Woodbine-based runner travels south for the Breeders' Cup.",
        )
        self.assertEqual(result.primary_region, "united_states")
        self.assertIn("canada", result.related_regions)

    def test_uae_and_saudi_are_independent_and_conflicts_require_review(self):
        uae = self._infer(
            source_site="tdn",
            source_region="united_states",
            title="Dubai World Cup at Meydan attracts elite field",
            body="Meydan hosts the Dubai World Cup.",
        )
        saudi = self._infer(
            source_site="tdn",
            source_region="united_states",
            title="Saudi Cup returns to King Abdulaziz Racecourse",
            body="Riyadh stages the Saudi Cup.",
        )
        conflict = self._infer(
            source_site="tdn",
            source_region="united_states",
            title="Dubai World Cup and Saudi Cup centres both announced",
            body="Meydan and King Abdulaziz Racecourse are equally central.",
        )

        self.assertEqual(uae.primary_region, "united_arab_emirates")
        self.assertEqual(saudi.primary_region, "saudi_arabia")
        self.assertNotEqual(uae.primary_region, saudi.primary_region)
        self.assertEqual(conflict.status, AttributionStatus.NEEDS_REVIEW)
        self.assertIn("conflicting_event_centres", conflict.conflict_reasons)
        self.assertNotIn(
            "middle_east",
            {uae.primary_region, saudi.primary_region, *conflict.related_regions},
        )

    def test_australian_events_are_not_out_of_scope(self):
        for title in (
            "Melbourne Cup field assembles at Flemington",
            "The Everest contenders arrive at Randwick",
        ):
            with self.subTest(title=title):
                result = self._infer(
                    source_site="tdn",
                    source_region="united_states",
                    title=title,
                    body="Australian racing officials confirmed the programme.",
                )
                self.assertEqual(result.primary_region, "australia")
                self.assertNotEqual(result.reason, "out_of_scope_title_region")

    def test_australian_source_reporting_royal_ascot_has_australia_related(self):
        result = self._infer(
            source_site="racing_victoria_news",
            source_region="australia",
            title="Australian sprinter set for Royal Ascot",
            body="The Racing Victoria runner travels to Ascot.",
        )
        self.assertEqual(result.primary_region, "united_kingdom")
        self.assertIn("australia", result.related_regions)

    def test_japanese_uae_and_saudi_strong_signals_use_formal_regions(self):
        cases = (
            (
                "ドバイワールドカップはメイダン競馬場で開催",
                "アラブ首長国連邦の主催者が発表した。",
                RacingRegion.UNITED_ARAB_EMIRATES,
            ),
            (
                "サウジカップはリヤドで開催",
                "サウジアラビアの主催者が発表した。",
                RacingRegion.SAUDI_ARABIA,
            ),
        )
        for title, body, expected in cases:
            with self.subTest(expected=expected):
                result = self._infer(
                    source_site=SourceSite.SPONICHI,
                    source_region=RacingRegion.JAPAN,
                    title=title,
                    body=body,
                )
                self.assertEqual(result.primary_region, expected)
                self.assertNotIn(
                    result.primary_region,
                    {RacingRegion.JAPAN, RacingRegion.OTHER},
                )


@override_settings(
    MULTIREGION_ATTRIBUTION_MODE="off",
    MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="off",
    NEW_REGION_NEWS_ATTRIBUTION_CANDIDATES_ENABLED=True,
    NEW_REGION_NEWS_ATTRIBUTION_CANDIDATE_SOURCES=["hri_news"],
    MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["ireland"],
    MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=["hri_news:official"],
)
class ModeOffCandidateGateTests(TestCase):
    def test_source_scoped_candidate_keeps_source_region_and_blocks_publish_and_qq(self):
        NewsSource.objects.create(
            name="HRI fixture source",
            homepage_url="https://www.hri.ie/",
            feed_url="https://www.hri.ie/news-and-media",
            language=SourceLanguage.ENGLISH,
            racing_region="ireland",
            source_language=SourceLanguage.ENGLISH,
            source_kind=SourceKind.OFFICIAL,
            adapter_key="hri_news",
            source_site="hri_news",
            source_mode=SourceMode.OFFICIAL,
            enabled=False,
            production_approved=False,
        )
        published_at = datetime(2026, 7, 18, 9, tzinfo=dt_timezone.utc)
        draft = CanonicalNewsDraft(
            source_site="hri_news",
            source_mode=SourceMode.OFFICIAL,
            source_article_id="hri-cheltenham-1",
            source_url="https://www.hri.ie/news-and-media/hri-cheltenham-1",
            title_ja="Irish-trained contender travels to Cheltenham",
            body_ja_raw="The Irish trainer sends the horse to the Cheltenham Festival.",
            body_ja_normalized="The Irish trainer sends the horse to the Cheltenham Festival.",
            published_at=published_at,
            images=[],
            racing_region="ireland",
            source_language=SourceLanguage.ENGLISH,
            source_kind=SourceKind.OFFICIAL,
            metadata={
                "author": "HRI",
                "published_at_verified": True,
                "published_at_evidence": {
                    "raw": "2026-07-18T10:00:00+01:00",
                    "timezone": "Europe/Dublin",
                    "precision": "minute",
                    "parser_version": "hri-v1",
                    "verified": True,
                },
            },
        )

        article, created = upsert_article_from_draft(draft)

        self.assertTrue(created)
        self.assertEqual(article.racing_region, "ireland")
        self.assertFalse(article.related_region_links.exists())
        candidate = (article.attribution_summary or {}).get("review_candidate") or {}
        self.assertEqual(candidate.get("primary_region"), "united_kingdom")
        self.assertEqual(candidate.get("related_regions"), ["ireland"])
        self.assertTrue(candidate.get("rule_version"))
        self.assertIsNotNone(candidate.get("confidence"))
        self.assertFalse(article.attribution_locked)
        blocker_codes = {
            str(issue.get("code", ""))
            for issue in (article.gate_issues or [])
            if issue.get("severity") == "blocker"
        }
        self.assertIn("region_review_required", blocker_codes)
        self.assertTrue(
            article.review_mode == ReviewMode.MANUAL
            or article.automation_status == AutomationStatus.MANUAL_REVIEW_REQUIRED
        )

        article.title_zh = "切尔滕纳姆跨境报道"
        article.summary_zh = "已准备摘要"
        article.body_zh = "已准备正文"
        article.review_mode = ReviewMode.AUTO
        article.automation_status = AutomationStatus.PUBLISH_READY
        self.assertFalse(is_ready_for_auto_publish(article))

        article.workflow_status = WorkflowStatus.PUBLISHED
        article.published_to_web_at = timezone.now()
        qq_decision = should_push_news_to_qq(article, scope="all_public")
        self.assertFalse(qq_decision.allowed)
        self.assertIn(
            qq_decision.reason,
            {"has_blocker", "region_review_required"},
        )


class _BoundedResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        url: str = "https://www.hri.ie/news-and-media",
        content_type: str = "text/html; charset=utf-8",
        body: bytes = b"<html><body>Racing news</body></html>",
        location: str = "",
        content_length: str | None = None,
    ):
        self.status_code = status_code
        self.url = url
        self.encoding = "utf-8"
        self.headers = {"Content-Type": content_type}
        if location:
            self.headers["Location"] = location
        if content_length is not None:
            self.headers["Content-Length"] = content_length
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        del chunk_size
        yield self._body

    def close(self):
        return None


class NewRegionBoundedHttpTests(TestCase):
    def _session(self, *responses):
        session = mock.Mock()
        session.get.side_effect = list(responses)
        return session

    def test_success_uses_fixed_limits_and_returns_final_html(self):
        session = self._session(_BoundedResponse())
        with mock.patch("stable.services.http.requests.Session", return_value=session):
            result = get_bounded_html(
                "https://www.hri.ie/news-and-media",
                allowed_hosts=("www.hri.ie", "hri.ie"),
            )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.final_url, "https://www.hri.ie/news-and-media")
        self.assertIn("Racing news", result.text)
        session.get.assert_called_once()
        self.assertEqual(session.get.call_args.kwargs["timeout"], (5, 15))
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
        self.assertTrue(session.get.call_args.kwargs["stream"])

    def test_initial_and_redirect_hosts_are_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "host_not_allowed"):
            get_bounded_html(
                "https://example.net/news",
                allowed_hosts=("www.hri.ie",),
            )

        session = self._session(
            _BoundedResponse(
                status_code=302,
                location="https://example.net/login",
            )
        )
        with mock.patch("stable.services.http.requests.Session", return_value=session):
            with self.assertRaisesRegex(ValueError, "host_not_allowed"):
                get_bounded_html(
                    "https://www.hri.ie/news-and-media",
                    allowed_hosts=("www.hri.ie",),
                )

    def test_redirect_budget_is_three(self):
        redirects = [
            _BoundedResponse(
                status_code=302,
                location=f"/news/redirect-{index}",
                url=f"https://www.hri.ie/news/redirect-{index - 1}",
            )
            for index in range(1, 5)
        ]
        session = self._session(*redirects)
        with mock.patch("stable.services.http.requests.Session", return_value=session):
            with self.assertRaisesRegex(ValueError, "too_many_redirects"):
                get_bounded_html(
                    "https://www.hri.ie/news-and-media",
                    allowed_hosts=("www.hri.ie",),
                )
        self.assertEqual(session.get.call_count, 4)

    def test_non_html_oversized_and_login_pages_are_rejected(self):
        cases = (
            (
                _BoundedResponse(content_type="application/pdf"),
                "non_html",
            ),
            (
                _BoundedResponse(content_length=str(2 * 1024 * 1024 + 1)),
                "response_too_large",
            ),
            (
                _BoundedResponse(body=b"<html><body>Verify you are human CAPTCHA</body></html>"),
                "login_or_captcha",
            ),
        )
        for response, expected in cases:
            with self.subTest(expected=expected):
                session = self._session(response)
                with mock.patch("stable.services.http.requests.Session", return_value=session):
                    with self.assertRaisesRegex(ValueError, expected):
                        get_bounded_html(
                            "https://www.hri.ie/news-and-media",
                            allowed_hosts=("www.hri.ie",),
                        )

    def test_non_200_non_redirect_statuses_are_rejected(self):
        for status_code in (206, 300, 304):
            with self.subTest(status_code=status_code):
                session = self._session(
                    _BoundedResponse(status_code=status_code)
                )
                with mock.patch(
                    "stable.services.http.requests.Session",
                    return_value=session,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "unexpected_status",
                    ):
                        get_bounded_html(
                            "https://www.hri.ie/news-and-media",
                            allowed_hosts=("www.hri.ie",),
                        )


class NewRegionPublishedTimeEvidenceTests(TestCase):
    def _draft(self, *, published_at, verified, evidence_source):
        return CanonicalNewsDraft(
            source_site=SourceSite.HRI_NEWS,
            source_mode=SourceMode.OFFICIAL,
            source_article_id="hri-time-evidence",
            source_url="https://www.hri.ie/news-and-media/hri-time-evidence",
            title_ja="HRI verified time",
            body_ja_raw="Verified body",
            body_ja_normalized="Verified body",
            published_at=published_at,
            images=[],
            racing_region=RacingRegion.IRELAND,
            source_language=SourceLanguage.ENGLISH,
            source_kind=SourceKind.OFFICIAL,
            metadata={
                "published_at_verified": verified,
                "published_at_evidence": {
                    "source": evidence_source,
                    "raw": published_at.isoformat(),
                    "timezone": "Europe/Dublin",
                    "precision": "minute",
                    "parser_version": "hri-news-v1",
                    "verified": verified,
                },
            },
        )

    def test_verified_article_time_is_not_downgraded_but_snapshot_keeps_attempt_evidence(self):
        sync_builtin_sources()
        verified_time = datetime(2026, 7, 18, 8, 30, tzinfo=dt_timezone.utc)
        fallback_time = datetime(2026, 7, 19, 8, 30, tzinfo=dt_timezone.utc)
        article = upsert_article_from_draft(
            self._draft(
                published_at=verified_time,
                verified=True,
                evidence_source="detail",
            )
        ).article
        upsert_article_from_draft(
            self._draft(
                published_at=fallback_time,
                verified=False,
                evidence_source="fallback",
            )
        )

        article.refresh_from_db()
        latest_snapshot = NewsSnapshot.objects.filter(article=article).latest("id")
        self.assertEqual(article.published_at, verified_time)
        self.assertTrue(article.published_at_verified)
        self.assertEqual(article.published_at_evidence["source"], "detail")
        self.assertEqual(
            latest_snapshot.snapshot_metadata["published_at_evidence"]["source"],
            "fallback",
        )


class NewRegionPublicSurfaceTests(TestCase):
    def test_news_accepts_new_regions_but_horse_and_race_resolvers_reject_them(self):
        news = self.client.get(
            reverse("public-news-feed"),
            {"region": RacingRegion.UNITED_ARAB_EMIRATES},
        )
        self.assertEqual(news.status_code, 200)
        self.assertEqual(news.context["active_region"], RacingRegion.UNITED_ARAB_EMIRATES)
        self.assertContains(news, "中东")
        self.assertContains(news, "阿联酋")
        self.assertContains(news, "沙特阿拉伯")

        horse = self.client.get(
            reverse("public-horse-index"),
            {"region": RacingRegion.CANADA},
        )
        self.assertEqual(horse.status_code, 200)
        self.assertEqual(horse.context["filters"]["region"], "")
        self.assertNotContains(horse, "加拿大")

        race = self.client.get(
            reverse("public-race-calendar"),
            {"region": RacingRegion.AUSTRALIA},
        )
        self.assertEqual(race.status_code, 200)
        self.assertEqual(race.context["filters"]["region"], "")
        self.assertNotContains(race, "澳大利亚")


class NewRegionManualPublishGateTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="new-region-editor",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(self.user)

    def _article(self, *, locked: bool, gate_issues: list[dict], candidate: bool):
        return NewsArticle.objects.create(
            source_site=SourceSite.HRI_NEWS,
            source_mode=SourceMode.OFFICIAL,
            source_article_id=f"manual-publish-{locked}-{candidate}-{len(gate_issues)}",
            racing_region=RacingRegion.IRELAND,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Manual publish gate",
            title_zh="人工发布门禁",
            summary_zh="摘要",
            body_ja_raw="Body",
            body_ja_normalized="Body",
            body_zh="正文",
            published_at=timezone.now(),
            source_url="https://www.hri.ie/news-and-media/manual-publish-gate",
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            attribution_locked=locked,
            attribution_summary=(
                {"review_candidate": {"primary_region": RacingRegion.IRELAND}}
                if candidate
                else {}
            ),
            gate_issues=gate_issues,
        )

    def test_manual_publish_rejects_unlocked_candidate_and_region_blocker_without_mutation(self):
        cases = (
            self._article(locked=False, gate_issues=[], candidate=True),
            self._article(
                locked=True,
                candidate=False,
                gate_issues=[
                    {
                        "code": "region_review_required",
                        "severity": "blocker",
                        "message": "地区待审核",
                    }
                ],
            ),
        )
        for article in cases:
            with self.subTest(article_id=article.pk):
                response = self.client.post(
                    reverse("console-article-editor", args=[article.pk]),
                    {
                        "intent": "publish",
                        "publish_without_cover": "1",
                        "racing_region": article.racing_region,
                        "related_regions_present": "1",
                        "content_category": "news",
                        # 同一次 publish POST 不能把“锁定”勾选当作已经完成过
                        # 独立地区确认；必须先保存确认，再另行发布。
                        "attribution_locked": "on",
                        "title_zh": article.title_zh,
                        "summary_zh": article.summary_zh,
                        "body_zh": article.body_zh,
                        "source_note": "",
                        "editor_notes": "",
                        "tags_text": "",
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "地区归属")
                article.refresh_from_db()
                self.assertEqual(article.workflow_status, WorkflowStatus.PENDING_REVIEW)
                self.assertIsNone(article.published_to_web_at)


class NewRegionQQGateTests(TestCase):
    def _public_article(self, *, region: str, source_site: str, locked: bool = True):
        return NewsArticle.objects.create(
            source_site=source_site,
            source_mode=SourceMode.OFFICIAL,
            source_article_id=f"{source_site}-{region}",
            racing_region=region,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Public regional story",
            title_zh="地区公开稿",
            summary_zh="摘要",
            body_ja_raw="Body",
            body_ja_normalized="Body",
            body_zh="正文",
            published_at=timezone.now(),
            source_url=f"https://fixture.example/{source_site}/{region}",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
            attribution_locked=locked,
        )

    def test_explicit_subscription_all_public_and_high_value_are_independent_gates(self):
        canada = self._public_article(
            region=RacingRegion.CANADA,
            source_site=SourceSite.WOODBINE_NEWS,
        )
        united_states = self._public_article(
            region=RacingRegion.UNITED_STATES,
            source_site=SourceSite.TDN,
        )
        target = PushTarget.objects.create(
            name="加拿大组",
            group_id="canada-group",
            allowed_regions=[RacingRegion.CANADA],
            push_scope="all_public",
        )

        self.assertTrue(should_push_news_to_qq(canada, target=target).allowed)
        self.assertEqual(
            should_push_news_to_qq(united_states, target=target).reason,
            "region_not_allowed",
        )
        self.assertEqual(
            should_push_news_to_qq(canada, scope="high_value_only", target=target).reason,
            "not_high_value",
        )

    def test_empty_subscription_defaults_to_japan_and_manual_lock_is_independent(self):
        canada = self._public_article(
            region=RacingRegion.CANADA,
            source_site=SourceSite.WOODBINE_NEWS,
            locked=False,
        )
        canada.attribution_summary = {
            "review_candidate": {"primary_region": RacingRegion.CANADA}
        }
        canada.save(update_fields=["attribution_summary", "updated_at"])
        target = PushTarget.objects.create(
            name="旧群",
            group_id="legacy-group",
            allowed_regions=[],
            push_scope="all_public",
        )

        self.assertEqual(
            should_push_news_to_qq(canada, target=target).reason,
            "region_review_required",
        )
        canada.attribution_locked = True
        canada.save(update_fields=["attribution_locked", "updated_at"])
        self.assertEqual(
            should_push_news_to_qq(canada, target=target).reason,
            "region_not_allowed",
        )


HRI_REAL_LISTING_FIXTURE = """
<html><body><section class="news-list">
  <article><a href="/news/details/derby&nbsp;winner’s-return?utm_source=fixture#top">
    Derby winner returns
  </a></article>
  <article><a href="/news-and-media/not-a-real-detail">Legacy landing page</a></article>
</section></body></html>
"""

HRI_REAL_DETAIL_FIXTURE = """
<html><body><main><article>
  <h1>Derby winner returns</h1>
  <div class="date">Saturday, 20 June 2026</div>
  <div class="article-body"><p>The winner returns to the Curragh.</p></div>
</article></main></body></html>
"""

WOODBINE_REAL_LISTING_FIXTURE = """
<html><body><section>
  <article><a href="/news/">News landing</a></article>
  <article><a href="/blog/handicapping-notes">Blog notes</a></article>
  <article><a href="/woodbine-news/kings-plate-preview">King's Plate preview</a></article>
</section></body></html>
"""

WOODBINE_META_DETAIL_FIXTURE = """
<html><head>
  <meta property="article:published_time" content="2026-06-12T14:30:00-04:00">
</head><body><article>
  <h1>King's Plate preview</h1>
  <div class="entry-content"><p>Woodbine's main article paragraph.</p></div>
</article></body></html>
"""

WOODBINE_JSONLD_DETAIL_FIXTURE = """
<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"NewsArticle",
 "headline":"Woodbine Oaks report","datePublished":"2026-06-12T13:15:00-04:00"}
</script></head><body><article>
  <h1>Woodbine Oaks report</h1>
  <div class="entry-content"><p>Only the entry content is the article body.</p></div>
</article></body></html>
"""

ERA_JSONLD_DETAIL_FIXTURE = """
<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Article",
 "headline":"Meydan season update","datePublished":"2026-06-12T14:30:00+04:00"}
</script></head><body><article>
  <h1>Meydan season update</h1>
  <div class="article-body"><p>The official season update from Meydan.</p></div>
</article></body></html>
"""

ERA_VISIBLE_DATE_DETAIL_FIXTURE = """
<html><body><main><article>
  <h1>Dubai racing update</h1>
  <div class="date">12 June 2026</div>
  <div class="article-body"><p>The visible date is the only date evidence.</p></div>
</article></main></body></html>
"""

JCSA_REAL_LISTING_FIXTURE = """
<article class="news-card">
  <a href="/en/news/20260323_arc_videos">ARC videos</a>
</article>
"""

JCSA_REAL_DETAIL_FIXTURE = """
<html><body><main>
  <h1>ARC videos</h1>
  <div class="text-black-body font-inter text-small-body">
    Sunday, 22nd March 2026, 5:00pm
  </div>
  <div class="content-area"><p>The JCSA official article body.</p></div>
</main></body></html>
"""

RV_SITEMAP_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.racingvictoria.com.au/news/2026/06/18/older-report</loc></url>
  <url><loc>https://www.racingvictoria.com.au/news/2026/06/20/feature-report</loc></url>
  <url><loc>https://www.racingvictoria.com.au/news/notices/2026/06/21/stewards-notice</loc></url>
  <url><loc>https://www.racingvictoria.com.au/news/videos/2026/06/22/video-report</loc></url>
  <url><loc>https://www.racingvictoria.com.au/news/undated-report</loc></url>
</urlset>
"""


def _rv_next_data_fixture(
    *,
    article_date: str = "2026-06-20T10:00:00+10:00",
    title: str = "Feature report",
    body_html: str = "<p>The winner came home strongly.</p>",
) -> str:
    payload = {
        "props": {
            "pageProps": {
                "layoutData": {
                    "sitecore": {
                        "route": {
                            "fields": {
                                "Title": {"value": title},
                                "ArticleDate": {
                                    "value": article_date
                                },
                            },
                            "placeholders": {
                                "headless-main": [
                                    {
                                        "componentName": "RichText",
                                        "fields": {
                                            "Text": {
                                                "value": (
                                                    '<div class="ck-content">'
                                                    f"{body_html}"
                                                    "</div>"
                                                )
                                            }
                                        },
                                    },
                                    {
                                        "componentName": "DCAArticleList",
                                        "fields": {
                                            "Text": {
                                                "value": "<p>Recommended story must stay out.</p>"
                                            }
                                        },
                                    },
                                ],
                                "headless-footer": [
                                    {
                                        "componentName": "RichText",
                                        "fields": {
                                            "Text": {
                                                "value": "<p>Copyright footer must stay out.</p>"
                                            }
                                        },
                                    }
                                ],
                            },
                        }
                    }
                }
            }
        }
    }
    return (
        "<html><body><div id=\"__next\"></div>"
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}"
        "</script></body></html>"
    )


class NewRegionRealStructureFixtureTests(TestCase):
    def _detail_or_failure(self, adapter, fixture: str, url: str):
        try:
            return adapter.parse_detail_html(fixture, url=url)
        except Exception as exc:
            self.fail(f"{adapter.source_site} 真实详情 fixture 不应抛异常：{exc}")

    def test_hri_real_path_long_date_and_unicode_url_are_canonical(self):
        adapter = INTERNATIONAL_ADAPTERS["hri_news"]()
        stubs = adapter.parse_listing_html(
            HRI_REAL_LISTING_FIXTURE,
            url="https://www.hri.ie/news-and-media",
            mode=SourceMode.OFFICIAL,
        )
        self.assertEqual(len(stubs), 1)
        parsed = urlsplit(stubs[0].source_url)
        self.assertTrue(parsed.path.startswith("/news/details/"))
        self.assertIn("%C2%A0", parsed.path)
        self.assertIn("%E2%80%99", parsed.path)
        self.assertNotIn("\xa0", parsed.path)
        self.assertNotIn("&nbsp;", stubs[0].source_url)
        self.assertEqual(parsed.query, "")
        self.assertEqual(parsed.fragment, "")

        detail = self._detail_or_failure(
            adapter,
            HRI_REAL_DETAIL_FIXTURE,
            stubs[0].source_url,
        )
        self.assertEqual(
            detail.published_at,
            datetime(2026, 6, 20, 11, 0, tzinfo=dt_timezone.utc),
        )
        evidence = detail.metadata["published_at_evidence"]
        self.assertEqual(evidence["raw"], "Saturday, 20 June 2026")
        self.assertEqual(evidence["timezone"], "Europe/Dublin")
        self.assertEqual(evidence["precision"], "date")

    def test_woodbine_listing_and_structured_detail_contracts(self):
        adapter = INTERNATIONAL_ADAPTERS["woodbine_news"]()
        stubs = adapter.parse_listing_html(
            WOODBINE_REAL_LISTING_FIXTURE,
            url="https://woodbine.com/news/",
            mode=SourceMode.OFFICIAL,
        )
        self.assertEqual(
            [urlsplit(item.source_url).path for item in stubs],
            ["/woodbine-news/kings-plate-preview"],
        )

        cases = (
            (
                WOODBINE_META_DETAIL_FIXTURE,
                "https://woodbine.com/woodbine-news/kings-plate-preview",
                datetime(2026, 6, 12, 18, 30, tzinfo=dt_timezone.utc),
                "Woodbine's main article paragraph.",
            ),
            (
                WOODBINE_JSONLD_DETAIL_FIXTURE,
                "https://woodbine.com/woodbine-news/woodbine-oaks-report",
                datetime(2026, 6, 12, 17, 15, tzinfo=dt_timezone.utc),
                "Only the entry content is the article body.",
            ),
        )
        for fixture, url, expected_time, expected_body in cases:
            with self.subTest(url=url):
                detail = self._detail_or_failure(adapter, fixture, url)
                self.assertEqual(detail.published_at, expected_time)
                self.assertIn(expected_body, detail.body_ja_normalized)
                self.assertEqual(detail.metadata["body_selector"], ".entry-content")

    def test_era_jsonld_and_visible_long_date_are_both_supported(self):
        adapter = INTERNATIONAL_ADAPTERS["emirates_racing_authority"]()
        cases = (
            (
                ERA_JSONLD_DETAIL_FIXTURE,
                datetime(2026, 6, 12, 10, 30, tzinfo=dt_timezone.utc),
                "minute",
            ),
            (
                ERA_VISIBLE_DATE_DETAIL_FIXTURE,
                datetime(2026, 6, 12, 8, 0, tzinfo=dt_timezone.utc),
                "date",
            ),
        )
        for fixture, expected_time, expected_precision in cases:
            with self.subTest(expected_precision=expected_precision):
                detail = self._detail_or_failure(
                    adapter,
                    fixture,
                    "https://emiratesracing.com/news/season-update",
                )
                self.assertEqual(detail.published_at, expected_time)
                self.assertEqual(
                    detail.metadata["published_at_evidence"]["precision"],
                    expected_precision,
                )

    def test_jcsa_uses_public_fragment_endpoint_and_ordinal_local_time(self):
        adapter = INTERNATIONAL_ADAPTERS["jcsa_news"]()
        self.assertEqual(
            adapter.listing_url(1, mode=SourceMode.OFFICIAL),
            "https://jcsa.sa/api/news/en/0/12",
        )
        stubs = adapter.parse_listing_html(
            JCSA_REAL_LISTING_FIXTURE,
            url="https://jcsa.sa/api/news/en/0/12",
            mode=SourceMode.OFFICIAL,
        )
        self.assertEqual(len(stubs), 1)
        self.assertEqual(
            urlsplit(stubs[0].source_url).path,
            "/en/news/20260323_arc_videos",
        )
        detail = self._detail_or_failure(
            adapter,
            JCSA_REAL_DETAIL_FIXTURE,
            stubs[0].source_url,
        )
        self.assertEqual(detail.title_ja, "ARC videos")
        self.assertEqual(
            detail.published_at,
            datetime(2026, 3, 22, 14, 0, tzinfo=dt_timezone.utc),
        )
        evidence = detail.metadata["published_at_evidence"]
        self.assertEqual(
            evidence["raw"],
            "Sunday, 22nd March 2026, 5:00pm",
        )
        self.assertEqual(evidence["precision"], "minute")
        self.assertIn("JCSA official article body", detail.body_ja_normalized)
        self.assertEqual(detail.metadata["body_selector"], ".content-area")

    def test_racing_victoria_sitemap_and_next_data_boundaries(self):
        adapter = INTERNATIONAL_ADAPTERS["racing_victoria_news"]()
        self.assertEqual(
            adapter.listing_url(1, mode=SourceMode.OFFICIAL),
            "https://www.racingvictoria.com.au/sitemap.xml",
        )
        stubs = adapter.parse_listing_html(
            RV_SITEMAP_FIXTURE,
            url="https://www.racingvictoria.com.au/sitemap.xml",
            mode=SourceMode.OFFICIAL,
        )
        self.assertEqual(
            [urlsplit(item.source_url).path for item in stubs],
            [
                "/news/2026/06/20/feature-report",
                "/news/2026/06/18/older-report",
            ],
        )

        detail = self._detail_or_failure(
            adapter,
            _rv_next_data_fixture(),
            "https://www.racingvictoria.com.au/news/2026/06/20/feature-report",
        )
        self.assertEqual(detail.title_ja, "Feature report")
        self.assertEqual(
            detail.published_at,
            datetime(2026, 6, 20, 0, 0, tzinfo=dt_timezone.utc),
        )
        self.assertIn("winner came home strongly", detail.body_ja_normalized)
        self.assertNotIn("Recommended story", detail.body_ja_normalized)
        self.assertNotIn("Copyright footer", detail.body_ja_normalized)
        self.assertEqual(
            detail.metadata["published_at_evidence"]["raw"],
            "2026-06-20T10:00:00+10:00",
        )


class NewRegionPermissionMatrixTests(TestCase):
    def test_exact_permission_matrix_is_fail_closed_even_when_technically_accepted(self):
        from stable.management.commands.probe_international_news_sources import (
            _finalize_probe_contract,
        )

        expected = {
            "hri_news": "blocked",
            "woodbine_news": "blocked",
            "emirates_racing_authority": "blocked",
            "jcsa_news": "unknown",
            "racing_victoria_news": "unknown",
        }
        for source_key, permission in expected.items():
            with self.subTest(source_key=source_key):
                adapter = INTERNATIONAL_ADAPTERS[source_key]()
                result = {
                    "source": source_key,
                    "status": "accepted",
                    "deferred_reason": "",
                }
                _finalize_probe_contract(result, adapter)
                self.assertEqual(
                    result["effective_production_status"],
                    "production_blocked",
                )
                self.assertEqual(
                    adapter.automation_permission_status,
                    permission,
                )
                self.assertEqual(
                    result["automation_permission_status"],
                    permission,
                )


class NewRegionRequestIsolationTests(TestCase):
    HTML_TYPES = {"text/html", "application/xhtml+xml"}
    XML_TYPES = {"text/xml", "application/xml"}

    def _bounded_result(self, *, text: str, final_url: str, content_type: str):
        return SimpleNamespace(
            text=text,
            final_url=final_url,
            status_code=200,
            content_type=content_type,
            content_length=len(text.encode("utf-8")),
            redirect_count=0,
        )

    def test_new_adapters_use_identifiable_ua_and_isolate_xml_to_rv_sitemap(self):
        listing_fixtures = {
            "hri_news": HRI_REAL_LISTING_FIXTURE,
            "woodbine_news": WOODBINE_REAL_LISTING_FIXTURE,
            "emirates_racing_authority": "<html><body></body></html>",
            "jcsa_news": JCSA_REAL_LISTING_FIXTURE,
            "racing_victoria_news": RV_SITEMAP_FIXTURE,
        }
        detail_fixtures = {
            "hri_news": HRI_REAL_DETAIL_FIXTURE,
            "woodbine_news": WOODBINE_META_DETAIL_FIXTURE,
            "emirates_racing_authority": ERA_VISIBLE_DATE_DETAIL_FIXTURE,
            "jcsa_news": JCSA_REAL_DETAIL_FIXTURE,
            "racing_victoria_news": _rv_next_data_fixture(),
        }
        for source_key in EXPECTED_SOURCE_SITES:
            with self.subTest(source_key=source_key, request="listing"):
                adapter = INTERNATIONAL_ADAPTERS[source_key]()
                listing_url = adapter.listing_url(1, mode=SourceMode.OFFICIAL)
                content_type = (
                    "application/xml"
                    if source_key == "racing_victoria_news"
                    else "text/html"
                )
                result = self._bounded_result(
                    text=listing_fixtures[source_key],
                    final_url=listing_url,
                    content_type=content_type,
                )
                with mock.patch(
                    "stable.adapters.international.get_bounded_html",
                    return_value=result,
                ) as bounded:
                    try:
                        adapter.fetch_listing(SourceMode.OFFICIAL, 1)
                    except Exception:
                        # 本测试只锁定请求边界；真实结构解析由独立 fixture 用例负责。
                        pass
                kwargs = bounded.call_args.kwargs
                user_agent = str(kwargs.get("user_agent") or "")
                self.assertRegex(user_agent.casefold(), r"umanews|umafans\.run")
                self.assertNotRegex(
                    user_agent.casefold(),
                    r"mozilla|chrome|safari|firefox|edge",
                )
                expected_types = set(self.HTML_TYPES)
                if source_key == "racing_victoria_news":
                    expected_types.update(self.XML_TYPES)
                self.assertEqual(
                    set(kwargs.get("accepted_content_types") or ()),
                    expected_types,
                )

            with self.subTest(source_key=source_key, request="detail"):
                adapter = INTERNATIONAL_ADAPTERS[source_key]()
                detail_path = {
                    "jcsa_news": "/en/news/20260323_arc_videos",
                    "racing_victoria_news": (
                        "/news/2026/06/20/request-isolation"
                    ),
                }.get(source_key, "/news/details/fixture")
                detail_url = urljoin(adapter.base_url, detail_path)
                result = self._bounded_result(
                    text=detail_fixtures[source_key],
                    final_url=detail_url,
                    content_type="text/html",
                )
                with mock.patch(
                    "stable.adapters.international.get_bounded_html",
                    return_value=result,
                ) as bounded:
                    try:
                        adapter.fetch_detail(detail_url)
                    except Exception:
                        pass
                kwargs = bounded.call_args.kwargs
                self.assertEqual(
                    set(kwargs.get("accepted_content_types") or ()),
                    self.HTML_TYPES,
                )
                self.assertTrue(kwargs.get("user_agent"))

    def test_bounded_helper_default_and_legacy_get_bytes_contract_are_unchanged(self):
        html_response = _BoundedResponse()
        bounded_session = mock.Mock()
        bounded_session.get.return_value = html_response
        with mock.patch(
            "stable.services.http.requests.Session",
            return_value=bounded_session,
        ):
            get_bounded_html(
                "https://www.hri.ie/news-and-media",
                allowed_hosts=("www.hri.ie",),
            )
        self.assertEqual(
            bounded_session.get.call_args.kwargs["headers"],
            DEFAULT_HEADERS,
        )

        legacy_response = mock.Mock()
        legacy_response.text = "<html>legacy detail</html>"
        legacy_response.content = b"<html>legacy detail</html>"
        with mock.patch(
            "stable.services.http.requests.get",
            return_value=legacy_response,
        ) as request_get:
            self.assertEqual(
                get_bytes(
                    "https://www.sportinglife.com/racing/news/legacy",
                    encoding="utf-8",
                ),
                "<html>legacy detail</html>",
            )
        self.assertEqual(request_get.call_args.kwargs["headers"], DEFAULT_HEADERS)
        self.assertEqual(request_get.call_args.kwargs["timeout"], 15)

        legacy_adapter = INTERNATIONAL_ADAPTERS["sporting_life"]()
        with mock.patch(
            "stable.adapters.international.get_bytes",
            return_value=(
                "<html><body><article><h1>Legacy</h1>"
                "<time datetime=\"2026-06-20T10:00:00+00:00\"></time>"
                "<p>Legacy body.</p></article></body></html>"
            ),
        ) as legacy_get_bytes:
            legacy_adapter.fetch_detail(
                "https://www.sportinglife.com/racing/news/legacy"
            )
        legacy_get_bytes.assert_called_once_with(
            "https://www.sportinglife.com/racing/news/legacy",
            encoding="utf-8",
        )

    def test_xml_requires_explicit_acceptance(self):
        default_session = mock.Mock()
        default_session.get.return_value = _BoundedResponse(
            url="https://www.racingvictoria.com.au/sitemap.xml",
            content_type="application/xml",
            body=RV_SITEMAP_FIXTURE.encode("utf-8"),
        )
        with mock.patch(
            "stable.services.http.requests.Session",
            return_value=default_session,
        ):
            with self.assertRaisesRegex(ValueError, "non_html"):
                get_bounded_html(
                    "https://www.racingvictoria.com.au/sitemap.xml",
                    allowed_hosts=("www.racingvictoria.com.au",),
                )

        explicit_session = mock.Mock()
        explicit_session.get.return_value = _BoundedResponse(
            url="https://www.racingvictoria.com.au/sitemap.xml",
            content_type="application/xml",
            body=RV_SITEMAP_FIXTURE.encode("utf-8"),
        )
        with mock.patch(
            "stable.services.http.requests.Session",
            return_value=explicit_session,
        ):
            try:
                response = get_bounded_html(
                    "https://www.racingvictoria.com.au/sitemap.xml",
                    allowed_hosts=("www.racingvictoria.com.au",),
                    accepted_content_types=(
                        "text/html",
                        "application/xhtml+xml",
                        "text/xml",
                        "application/xml",
                    ),
                )
            except Exception as exc:
                self.fail(f"显式允许的 RV sitemap XML 不应失败：{exc}")
        self.assertEqual(response.content_type, "application/xml")


class _StructuredHttpFixtureError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        final_url: str,
        legacy_response: bool = False,
    ):
        super().__init__(f"bounded_http_unexpected_status:{status_code}")
        self.status_code = status_code
        self.final_url = final_url
        if legacy_response:
            self.response = SimpleNamespace(status_code=status_code)


class NewRegionStructuredHttpFailureTests(TestCase):
    def test_helper_exposes_status_and_final_url_for_403_and_429(self):
        for status_code in (403, 429):
            with self.subTest(status_code=status_code):
                final_url = (
                    f"https://www.racingvictoria.com.au/news/status-{status_code}"
                )
                session = mock.Mock()
                session.get.return_value = _BoundedResponse(
                    status_code=status_code,
                    url=final_url,
                )
                with mock.patch(
                    "stable.services.http.requests.Session",
                    return_value=session,
                ):
                    with self.assertRaises(Exception) as caught:
                        get_bounded_html(
                            final_url,
                            allowed_hosts=("www.racingvictoria.com.au",),
                        )
                self.assertEqual(
                    getattr(caught.exception, "status_code", None),
                    status_code,
                )
                self.assertEqual(
                    getattr(caught.exception, "final_url", ""),
                    final_url,
                )

    def test_adapter_and_probe_preserve_403_and_429_metadata(self):
        cases = (
            ("jcsa_news", 403, "https://jcsa.sa/api/news/en/0/12"),
            (
                "racing_victoria_news",
                429,
                "https://www.racingvictoria.com.au/sitemap.xml",
            ),
        )
        for source_key, status_code, final_url in cases:
            with self.subTest(source_key=source_key, layer="adapter"):
                adapter = INTERNATIONAL_ADAPTERS[source_key]()
                failure = _StructuredHttpFixtureError(
                    status_code=status_code,
                    final_url=final_url,
                )
                with mock.patch(
                    "stable.adapters.international.get_bounded_html",
                    side_effect=failure,
                ):
                    with self.assertRaises(_StructuredHttpFixtureError):
                        adapter.fetch_listing(SourceMode.OFFICIAL, 1)
                self.assertEqual(adapter.last_listing_http_status, status_code)
                self.assertEqual(adapter.last_listing_final_url, final_url)

            with self.subTest(source_key=source_key, layer="probe"):
                stdout = io.StringIO()
                failure = _StructuredHttpFixtureError(
                    status_code=status_code,
                    final_url=final_url,
                )
                with mock.patch(
                    "stable.adapters.international.get_bounded_html",
                    side_effect=failure,
                ):
                    call_command(
                        "probe_international_news_sources",
                        source=[source_key],
                        limit=1,
                        json=True,
                        stdout=stdout,
                    )
                result = json.loads(stdout.getvalue())[0]
                self.assertEqual(result["http_status"], status_code)
                self.assertEqual(result["final_url"], final_url)
                self.assertEqual(result["technical_status"], "blocked")
                self.assertEqual(result["deferred_reason"], "access_limited")

    def test_task_status_extractor_supports_structured_exceptions(self):
        structured = _StructuredHttpFixtureError(
            status_code=429,
            final_url="https://fixture.example/status-429",
        )
        self.assertEqual(_http_status_code_from_exception(structured), 429)

    def test_task_status_extractor_keeps_legacy_response_compatibility(self):
        legacy = _StructuredHttpFixtureError(
            status_code=403,
            final_url="https://fixture.example/status-403",
            legacy_response=True,
        )
        self.assertEqual(_http_status_code_from_exception(legacy), 403)

    @override_settings(
        MULTIREGION_CRAWL_FAILURES_TO_BACKOFF=1,
        MULTIREGION_CRAWL_BLOCKED_BACKOFF_MINUTES=360,
        MULTIREGION_CRAWL_BACKOFF_MINUTES=60,
    )
    def test_crawl_task_persists_blocked_failure_diagnostics_and_360_backoff(self):
        for status_code, expected_category in (
            (403, SourceErrorCategory.HTTP_403),
            (429, SourceErrorCategory.HTTP_429),
        ):
            with self.subTest(status_code=status_code):
                adapter_key = f"fixture_http_{status_code}"
                final_url = f"https://fixture.example/status-{status_code}"
                failure = _StructuredHttpFixtureError(
                    status_code=status_code,
                    final_url=final_url,
                )

                class FailingAdapter:
                    automation_permission_status = "approved"

                    def __init__(self):
                        self.skipped_items = []

                    def fetch_listing(self, mode, page):
                        del mode, page
                        raise failure

                source = NewsSource.objects.create(
                    name=f"HTTP {status_code} fixture",
                    homepage_url="https://fixture.example/",
                    feed_url=final_url,
                    language=SourceLanguage.ENGLISH,
                    racing_region=RacingRegion.IRELAND,
                    source_language=SourceLanguage.ENGLISH,
                    source_kind=SourceKind.OFFICIAL,
                    adapter_key=adapter_key,
                    source_mode=SourceMode.OFFICIAL,
                    enabled=False,
                    production_approved=False,
                    crawl_interval_minutes=15,
                )
                started_at = timezone.now()
                window = ProductionWindow.objects.create(
                    kind=ProductionWindowKind.CRAWL,
                    mode=ProductionWindowMode.DAILY,
                    racing_region=RacingRegion.IRELAND,
                    source=source,
                    scope_key=f"http-fixture:{status_code}",
                    window_start=started_at,
                    window_end=started_at + timedelta(minutes=15),
                    status=ProductionWindowStatus.RUNNING,
                )

                with mock.patch.dict(
                    INTERNATIONAL_ADAPTERS,
                    {adapter_key: FailingAdapter},
                ):
                    with self.assertRaises(_StructuredHttpFixtureError):
                        crawl_news_source_task.run(source.id, window.id)

                source.refresh_from_db()
                window.refresh_from_db()
                job = CrawlJob.objects.filter(source=source).latest("id")
                assertions = {
                    "category": (
                        source.last_error_category,
                        expected_category,
                    ),
                    "window_status": (
                        window.status,
                        ProductionWindowStatus.FAILED,
                    ),
                    "payload_category": (
                        window.result_payload.get("error_category"),
                        expected_category,
                    ),
                    "payload_http_status": (
                        window.result_payload.get("http_status"),
                        status_code,
                    ),
                    "payload_final_url": (
                        window.result_payload.get("final_url"),
                        final_url,
                    ),
                    "crawl_job_status": (
                        job.status,
                        TaskStatus.FAILED,
                    ),
                }
                for label, (actual, expected) in assertions.items():
                    with self.subTest(status_code=status_code, field=label):
                        self.assertEqual(actual, expected)
                with self.subTest(status_code=status_code, field="backoff"):
                    self.assertIsNotNone(source.backoff_until)
                    self.assertAlmostEqual(
                        (
                            source.backoff_until - source.last_crawl_at
                        ).total_seconds()
                        / 60,
                        360,
                        delta=0.1,
                    )
                with self.subTest(status_code=status_code, field="job_visible"):
                    self.assertIn(
                        f"unexpected_status:{status_code}",
                        job.error_message,
                    )


class NewRegionFixtureSecretSafetyTests(TestCase):
    def test_new_region_code_docs_and_fixtures_contain_no_graphql_credentials(self):
        repo_root = Path(__file__).resolve().parents[2]
        targets = [
            repo_root / "server/stable/adapters/international.py",
            repo_root / "server/stable/services/http.py",
            repo_root / "server/stable/tasks.py",
            Path(__file__).resolve(),
            *sorted(
                (repo_root / "docs/changes/add-new-region-news-sources").glob(
                    "*.md"
                )
            ),
        ]
        graphql_credential = re.compile(
            r"(?is)graphql.{0,100}(?:api[_-]?key|token|secret)"
            r"\s*[:=]\s*[\"'][A-Za-z0-9_./+{}=-]{16,}[\"']"
        )
        known_secret_prefix = re.compile(
            r"(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|"
            r"xox[baprs]-[A-Za-z0-9-]{20,}|AIza[A-Za-z0-9_-]{20,})"
        )
        violations: list[str] = []
        for path in targets:
            text = path.read_text(encoding="utf-8")
            if graphql_credential.search(text) or known_secret_prefix.search(text):
                violations.append(str(path.relative_to(repo_root)))
        self.assertEqual(
            violations,
            [],
            f"新地区代码/fixture 不得保存 GraphQL key 或疑似硬编码密钥：{violations}",
        )

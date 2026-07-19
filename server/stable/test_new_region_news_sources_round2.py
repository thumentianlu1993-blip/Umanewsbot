from __future__ import annotations

import importlib
import inspect
import io
import json
from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase, override_settings

from stable.adapters.base import (
    CanonicalNewsDraft,
    SourceArticleDetail,
    SourceArticleStub,
    SourceImageDraft,
)
from stable.adapters.international import (
    HRINewsAdapter,
    INTERNATIONAL_ADAPTERS,
    JCSANewsAdapter,
    RacingVictoriaNewsAdapter,
    SportingLifeAdapter,
    TDNAdapter,
    TDNFranceBroadKeywordAdapter,
    TDNFranceKeywordAdapter,
)
from stable.models import (
    CrawlJob,
    NewsArticle,
    NewsSnapshot,
    NewsSource,
    ProductionWindow,
    ProductionWindowKind,
    ProductionWindowMode,
    ProductionWindowStatus,
    RacingRegion,
    SourceKind,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TaskStatus,
    TranslationRun,
)
from stable.services.http import get_bounded_html
from stable.services.ingestion import upsert_article_from_draft
from stable.services.source_polling import select_due_enabled_news_sources
from stable.tasks import (
    _crawl_international_source,
    crawl_enabled_news_sources_task,
    crawl_news_source_task,
)


FIXED_CRAWLED_AT = datetime(2026, 7, 19, 0, 30, tzinfo=dt_timezone.utc)


def _field(value, name: str, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _decision(value) -> str:
    return str(_field(value, "decision", _field(value, "status", "")) or "")


def _result_metadata(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    as_metadata = getattr(value, "as_metadata", None)
    if callable(as_metadata):
        return dict(as_metadata())
    return {
        key: getattr(value, key)
        for key in (
            "decision",
            "status",
            "reason",
            "crawled_at",
            "source_timezone",
            "published_local_date",
            "crawled_local_date",
            "date_difference_days",
        )
        if hasattr(value, key)
    }


class Round2ContractTestCase(TestCase):
    def require_symbol(self, module_name: str, symbol_name: str):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            self.fail(
                f"目标能力尚未实现：无法导入 {module_name}（{exc}）"
            )
        symbol = getattr(module, symbol_name, None)
        if symbol is None:
            self.fail(f"目标能力尚未实现：{module_name}.{symbol_name} 不存在")
        return symbol

    def bounded_html(self, url: str, *, budget, kind: str):
        try:
            return get_bounded_html(
                url,
                allowed_hosts={"round2.example"},
                before_transport_get=lambda callback_kind, callback_url: budget.consume(
                    callback_kind,
                    callback_url,
                ),
                request_kind=kind,
            )
        except TypeError as exc:
            if "before_transport_get" in str(exc) or "request_kind" in str(exc):
                self.fail(
                    "目标能力尚未实现：有界 transport 尚未在每个 session.get 前接收请求预算 callback"
                )
            raise

    def request_budget(
        self,
        canonical_source_site: str,
        *,
        listing_limit: int = 1,
        detail_limit: int = 2,
    ):
        budget_class = self.require_symbol(
            "stable.services.source_permissions",
            "SourceRequestBudget",
        )
        try:
            return budget_class(
                canonical_source_site=canonical_source_site,
                listing_limit=listing_limit,
                detail_limit=detail_limit,
            )
        except TypeError as exc:
            self.fail(f"SourceRequestBudget 构造协议不符合获批设计：{exc}")

    def classify(
        self,
        *,
        published_at: datetime | None,
        crawled_at: datetime = FIXED_CRAWLED_AT,
        timezone_name: str = "Europe/Dublin",
        precision: str | None = "date",
        evidence_verified: bool = True,
        draft_verified: bool = True,
    ):
        classifier = self.require_symbol(
            "stable.services.news_candidate_freshness",
            "classify_candidate_freshness",
        )
        evidence = {
            "raw": published_at.isoformat() if published_at else "",
            "timezone": timezone_name,
            "precision": precision,
            "parser_version": "round2-test-v1",
            "verified": evidence_verified,
        }
        if precision is None:
            evidence.pop("precision")
        return classifier(
            published_at=published_at,
            published_at_evidence=evidence,
            published_at_verified=draft_verified,
            crawled_at=crawled_at,
        )


class DateOnlyCandidateFreshnessTests(Round2ContractTestCase):
    def test_date_only_absolute_day_difference_zero_one_two_and_future(self):
        dublin = ZoneInfo("Europe/Dublin")
        cases = (
            (datetime(2026, 7, 19, 12, tzinfo=dublin), "candidate_date_within_one_day", 0),
            (datetime(2026, 7, 18, 12, tzinfo=dublin), "candidate_date_within_one_day", 1),
            (datetime(2026, 7, 17, 12, tzinfo=dublin), "historical_date_outside_one_day", 2),
            (datetime(2026, 7, 20, 12, tzinfo=dublin), "candidate_date_within_one_day", 1),
            (datetime(2026, 7, 21, 12, tzinfo=dublin), "historical_date_outside_one_day", 2),
        )
        for published_at, expected, expected_difference in cases:
            with self.subTest(published_at=published_at.isoformat()):
                result = self.classify(published_at=published_at)
                self.assertEqual(_decision(result), expected)
                self.assertEqual(
                    _field(result, "date_difference_days"),
                    expected_difference,
                )

    def test_all_five_source_timezones_use_local_dates_and_dst(self):
        cases = (
            ("Europe/Dublin", datetime(2026, 7, 19, 0, 30)),
            ("America/Toronto", datetime(2026, 7, 19, 0, 30)),
            ("Asia/Dubai", datetime(2026, 7, 19, 0, 30)),
            ("Asia/Riyadh", datetime(2026, 7, 19, 0, 30)),
            ("Australia/Melbourne", datetime(2026, 1, 15, 0, 30)),
        )
        for timezone_name, crawl_local_naive in cases:
            with self.subTest(timezone=timezone_name):
                zone = ZoneInfo(timezone_name)
                crawl_local = crawl_local_naive.replace(tzinfo=zone)
                published_local = (crawl_local - timedelta(days=1)).replace(
                    hour=12,
                    minute=0,
                )
                result = self.classify(
                    published_at=published_local.astimezone(dt_timezone.utc),
                    crawled_at=crawl_local.astimezone(dt_timezone.utc),
                    timezone_name=timezone_name,
                )
                metadata = _result_metadata(result)
                self.assertEqual(_decision(result), "candidate_date_within_one_day")
                self.assertEqual(metadata["source_timezone"], timezone_name)
                self.assertEqual(
                    str(metadata["published_local_date"]),
                    published_local.date().isoformat(),
                )
                self.assertEqual(
                    str(metadata["crawled_local_date"]),
                    crawl_local.date().isoformat(),
                )
                self.assertEqual(metadata["date_difference_days"], 1)

        self.assertEqual(
            datetime(2026, 7, 19, tzinfo=ZoneInfo("Europe/Dublin")).utcoffset(),
            timedelta(hours=1),
        )
        self.assertEqual(
            datetime(2026, 7, 19, tzinfo=ZoneInfo("America/Toronto")).utcoffset(),
            timedelta(hours=-4),
        )
        self.assertEqual(
            datetime(2026, 1, 15, tzinfo=ZoneInfo("Australia/Melbourne")).utcoffset(),
            timedelta(hours=11),
        )

    def test_date_only_local_noon_does_not_enter_six_hour_path(self):
        dublin_noon = datetime(
            2026,
            7,
            18,
            12,
            tzinfo=ZoneInfo("Europe/Dublin"),
        )
        date_only = self.classify(published_at=dublin_noon)
        self.assertEqual(_decision(date_only), "candidate_date_within_one_day")
        self.assertEqual(_field(date_only, "date_difference_days"), 1)

        for precision in ("minute", "second"):
            with self.subTest(precision=precision):
                precise = self.classify(
                    published_at=dublin_noon,
                    precision=precision,
                )
                self.assertEqual(_decision(precise), "precise_time_not_applicable")
                self.assertIsNone(_field(precise, "date_difference_days"))

    def test_missing_unknown_unverified_naive_and_invalid_timezone_fail_closed(self):
        aware = datetime(2026, 7, 18, 11, tzinfo=dt_timezone.utc)
        unresolved_cases = (
            ("missing_published_at", {"published_at": None}),
            ("missing_precision", {"published_at": aware, "precision": None}),
            ("unknown_precision", {"published_at": aware, "precision": "dayish"}),
            (
                "evidence_unverified",
                {"published_at": aware, "evidence_verified": False},
            ),
            ("draft_unverified", {"published_at": aware, "draft_verified": False}),
            (
                "naive_published_at",
                {"published_at": aware.replace(tzinfo=None)},
            ),
            (
                "naive_crawled_at",
                {
                    "published_at": aware,
                    "crawled_at": FIXED_CRAWLED_AT.replace(tzinfo=None),
                },
            ),
        )
        for label, kwargs in unresolved_cases:
            with self.subTest(case=label):
                result = self.classify(**kwargs)
                self.assertEqual(_decision(result), "freshness_unresolved")
                self.assertTrue(str(_field(result, "reason", "")))

        for timezone_name in ("", "Mars/Olympus_Mons"):
            with self.subTest(timezone=timezone_name or "<empty>"):
                result = self.classify(
                    published_at=aware,
                    timezone_name=timezone_name,
                )
                self.assertEqual(_decision(result), "freshness_unresolved")
                self.assertEqual(
                    _field(result, "reason"),
                    "invalid_published_timezone",
                )


class ContentScopedPreviewTests(Round2ContractTestCase):
    def preview(self, title: str, lead: str, source_region: str):
        preview = self.require_symbol(
            "stable.services.news_attribution",
            "preview_content_scoped_region",
        )
        return preview(
            title=title,
            lead=lead,
            source_region=source_region,
        )

    def test_irish_oaks_and_woodbine_oaks_are_new_region_targets(self):
        cases = (
            (
                "Irish Oaks field assembles at the Curragh",
                "The Irish Classic is staged at the Curragh.",
                RacingRegion.UNITED_KINGDOM,
                RacingRegion.IRELAND,
            ),
            (
                "Woodbine Oaks returns to Ontario",
                "The Canadian fillies line up at Woodbine.",
                RacingRegion.UNITED_STATES,
                RacingRegion.CANADA,
            ),
        )
        for title, lead, source_region, expected in cases:
            with self.subTest(title=title):
                result = self.preview(title, lead, source_region)
                self.assertEqual(_field(result, "primary_region"), expected)
                self.assertNotEqual(_field(result, "status"), "needs_review")
                self.assertGreaterEqual(int(_field(result, "confidence", 0)), 80)

    def test_plain_uk_and_us_articles_are_not_new_region_targets(self):
        cases = (
            (
                "Royal Ascot card takes shape",
                "The feature is staged at Ascot.",
                RacingRegion.UNITED_KINGDOM,
                RacingRegion.UNITED_KINGDOM,
            ),
            (
                "Kentucky Derby preparations continue",
                "The field works at Churchill Downs.",
                RacingRegion.UNITED_STATES,
                RacingRegion.UNITED_STATES,
            ),
        )
        for title, lead, source_region, expected in cases:
            with self.subTest(title=title):
                result = self.preview(title, lead, source_region)
                self.assertEqual(_field(result, "primary_region"), expected)

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="off",
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="off",
        MULTIREGION_CONTENT_SCOPED_CANDIDATES_ENABLED=True,
        MULTIREGION_CONTENT_SCOPED_CANDIDATE_SOURCES=["round2_fixture"],
    )
    def test_mode_off_uses_shared_preview_only_for_strong_target_and_dedupes(self):
        source = _make_source(
            adapter_key="round2_fixture",
            source_site="round2_fixture",
            racing_region=RacingRegion.UNITED_KINGDOM,
            enabled=True,
            production_approved=True,
        )
        positive_preview = self.preview(
            "Irish Oaks field assembles at the Curragh",
            "The Irish Classic is staged at the Curragh.",
            RacingRegion.UNITED_KINGDOM,
        )
        negative_preview = self.preview(
            "Royal Ascot card takes shape",
            "The feature is staged at Ascot.",
            RacingRegion.UNITED_KINGDOM,
        )

        positive = _draft(
            article_id="candidate-positive",
            title="Irish Oaks field assembles at the Curragh",
            published_at=datetime(2026, 7, 18, 11, tzinfo=dt_timezone.utc),
            precision="date",
            source_region=RacingRegion.UNITED_KINGDOM,
        )
        negative = _draft(
            article_id="candidate-negative",
            title="Royal Ascot card takes shape",
            published_at=datetime(2026, 7, 18, 11, tzinfo=dt_timezone.utc),
            precision="date",
            source_region=RacingRegion.UNITED_KINGDOM,
        )

        positive_result = upsert_article_from_draft(
            positive,
            attribution_preview=positive_preview,
        )
        negative_result = upsert_article_from_draft(
            negative,
            attribution_preview=negative_preview,
        )
        duplicate_result = upsert_article_from_draft(
            positive,
            attribution_preview=positive_preview,
        )

        positive_article = positive_result.article
        negative_article = negative_result.article
        self.assertTrue(positive_result.created)
        self.assertTrue(negative_result.created)
        self.assertFalse(duplicate_result.created)
        self.assertEqual(NewsArticle.objects.count(), 2)
        self.assertEqual(
            positive_article.racing_region,
            RacingRegion.UNITED_KINGDOM,
        )
        candidate = (positive_article.attribution_summary or {}).get(
            "review_candidate",
            {},
        )
        self.assertEqual(candidate.get("primary_region"), RacingRegion.IRELAND)
        self.assertIn(
            "region_review_required",
            {
                item.get("code")
                for item in (positive_article.gate_issues or [])
            },
        )
        self.assertNotIn(
            "review_candidate",
            negative_article.attribution_summary or {},
        )
        self.assertNotIn(
            "region_review_required",
            {
                item.get("code")
                for item in (negative_article.gate_issues or [])
            },
        )
        self.assertEqual(source.articles.count(), 2)


class CanonicalSourcePermissionTests(Round2ContractTestCase):
    def resolve(self, adapter):
        resolver = self.require_symbol(
            "stable.services.source_permissions",
            "resolve_source_permission",
        )
        return resolver(adapter)

    def test_tdn_canonical_wrappers_share_accepted_internal_only_contract(self):
        class IrelandAlias(TDNFranceKeywordAdapter):
            source_site = "tdn_ireland_alias"
            canonical_source_site = "tdn"
            automation_permission_status = "approved"

        for adapter in (
            TDNAdapter(),
            TDNFranceKeywordAdapter(),
            TDNFranceBroadKeywordAdapter(),
            IrelandAlias(),
        ):
            with self.subTest(adapter=adapter.__class__.__name__):
                result = self.resolve(adapter)
                self.assertEqual(_field(result, "canonical_source_site"), "tdn")
                self.assertEqual(_field(result, "status"), "accepted")
                self.assertEqual(
                    _field(result, "reason"),
                    "internal_only_technical_access",
                )
                self.assertIs(_field(result, "allowed"), True)
                self.assertIs(
                    _field(_field(result, "record"), "public_publish_allowed"),
                    False,
                )

    def test_newly_verified_and_registered_aggregate_sources_are_accepted(self):
        for adapter in (JCSANewsAdapter(), RacingVictoriaNewsAdapter()):
            with self.subTest(adapter=adapter.__class__.__name__):
                result = self.resolve(adapter)
                self.assertEqual(_field(result, "status"), "accepted")
                self.assertEqual(
                    _field(result, "reason"),
                    "internal_only_technical_access",
                )

        aggregate = self.resolve(SportingLifeAdapter())
        self.assertEqual(
            _field(aggregate, "status"),
            "accepted",
        )
        self.assertEqual(
            _field(aggregate, "reason"),
            "internal_only_technical_access",
        )


class _NeverFetchBlockedHRIAlias(HRINewsAdapter):
    fetch_listing_calls = 0

    def fetch_listing(self, mode, page):
        type(self).fetch_listing_calls += 1
        raise AssertionError("技术 blocked 来源不应调用 fetch_listing")


class PermissionPreflightIntegrationTests(Round2ContractTestCase):
    def setUp(self):
        _NeverFetchBlockedHRIAlias.fetch_listing_calls = 0

    def test_blocked_probe_stops_before_listing_fetch(self):
        stdout = io.StringIO()
        with mock.patch.dict(
            "stable.management.commands.probe_international_news_sources.INTERNATIONAL_ADAPTERS",
            {"hri_news": _NeverFetchBlockedHRIAlias},
        ):
            call_command(
                "probe_international_news_sources",
                source=["hri_news"],
                limit=1,
                json=True,
                stdout=stdout,
            )

        self.assertEqual(_NeverFetchBlockedHRIAlias.fetch_listing_calls, 0)
        payload = json.loads(stdout.getvalue())[0]
        self.assertEqual(
            payload.get("deferred_reason"),
            "technical_access_blocked",
        )
        self.assertEqual(payload.get("technical_status"), "not_probed")
        self.assertEqual(payload.get("automation_permission_status"), "blocked")
        self.assertEqual(payload.get("effective_production_status"), "production_blocked")
        self.assertEqual(payload.get("request_count"), 0)

    def test_blocked_direct_crawl_stops_before_listing_fetch(self):
        source = _make_source(
            adapter_key="round2_blocked_hri",
            source_site=SourceSite.HRI_NEWS,
            racing_region=RacingRegion.IRELAND,
            enabled=True,
            production_approved=True,
        )
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {"round2_blocked_hri": _NeverFetchBlockedHRIAlias},
        ):
            with self.assertRaisesRegex(
                Exception,
                "technical_access_blocked",
            ):
                _crawl_international_source(source)

        self.assertEqual(_NeverFetchBlockedHRIAlias.fetch_listing_calls, 0)
        job = CrawlJob.objects.get(source=source)
        self.assertEqual(job.status, TaskStatus.FAILED)
        self.assertIn("technical_access_blocked", job.error_message)
        self.assertEqual(NewsArticle.objects.count(), 0)
        self.assertEqual(NewsSnapshot.objects.count(), 0)
        self.assertEqual(TranslationRun.objects.count(), 0)

    def test_enabled_but_unapproved_source_is_not_polled_or_directly_fetched(self):
        class UnapprovedAdapter:
            source_site = "round2_unapproved"
            canonical_source_site = "round2_unapproved"
            fetch_listing_calls = 0

            def fetch_listing(self, mode, page):
                type(self).fetch_listing_calls += 1
                raise AssertionError("未生产批准来源不应联网")

        source = _make_source(
            adapter_key="round2_unapproved",
            source_site="round2_unapproved",
            racing_region=RacingRegion.CANADA,
            enabled=True,
            production_approved=False,
        )
        selection = select_due_enabled_news_sources(
            allowed_regions={RacingRegion.CANADA},
            allowed_sources={str(source.id)},
            max_sources=10,
        )
        self.assertNotIn(source.id, [item.source.id for item in selection.selected])
        skipped = {item.source.id: item.reason for item in selection.skipped}
        self.assertEqual(skipped.get(source.id), "production_not_approved")

        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {"round2_unapproved": UnapprovedAdapter},
        ):
            with self.assertRaisesRegex(Exception, "source_not_production_approved"):
                _crawl_international_source(source)
        self.assertEqual(UnapprovedAdapter.fetch_listing_calls, 0)

    def test_registered_aggregate_production_approved_source_remains_selected(self):
        source = _make_source(
            adapter_key="sporting_life",
            source_site="sporting_life",
            racing_region=RacingRegion.UNITED_KINGDOM,
            enabled=True,
            production_approved=True,
        )
        selection = select_due_enabled_news_sources(
            allowed_regions={RacingRegion.UNITED_KINGDOM},
            allowed_sources={str(source.id)},
            max_sources=10,
        )
        selected = {item.source.id: item.reason for item in selection.selected}
        self.assertIn(source.id, selected)
        self.assertIn("internal_only_technical_access", selected[source.id])


def _make_source(
    *,
    adapter_key: str,
    source_site: str,
    racing_region: str,
    enabled: bool,
    production_approved: bool,
) -> NewsSource:
    return NewsSource.objects.create(
        name=f"{adapter_key} round2 source",
        homepage_url="https://round2.example/",
        feed_url="https://round2.example/news/",
        source_type="builtin",
        language=SourceLanguage.ENGLISH,
        racing_region=racing_region,
        source_language=SourceLanguage.ENGLISH,
        source_kind=SourceKind.MEDIA,
        adapter_key=adapter_key,
        source_site=source_site,
        source_mode=SourceMode.OFFICIAL,
        enabled=enabled,
        production_approved=production_approved,
        crawl_interval_minutes=15,
    )


def _preview_payload(preview) -> dict:
    return {
        "primary_region": _field(preview, "primary_region"),
        "related_regions": list(_field(preview, "related_regions", []) or []),
        "reason": _field(preview, "reason", ""),
        "evidence": dict(_field(preview, "evidence", {}) or {}),
        "status": _field(preview, "status", ""),
        "confidence": _field(preview, "confidence"),
        "rule_version": _field(preview, "rule_version", ""),
    }


def _draft(
    *,
    article_id: str,
    title: str,
    published_at: datetime | None,
    precision: str | None,
    source_region: str = RacingRegion.UNITED_KINGDOM,
    verified: bool = True,
    timezone_name: str = "Europe/Dublin",
    preview=None,
    source_site: str = "round2_fixture",
) -> CanonicalNewsDraft:
    evidence = {
        "raw": published_at.isoformat() if published_at else "",
        "timezone": timezone_name,
        "precision": precision,
        "parser_version": "round2-fixture-v1",
        "verified": verified,
    }
    if precision is None:
        evidence.pop("precision")
    metadata = {
        "published_at_verified": verified,
        "published_at_evidence": evidence,
    }
    if preview is not None:
        metadata["content_scoped_region_preview"] = _preview_payload(preview)
    return CanonicalNewsDraft(
        source_site=source_site,
        canonical_source_site=source_site,
        source_mode=SourceMode.OFFICIAL,
        source_article_id=article_id,
        source_url=f"https://round2.example/news/{article_id}",
        title_ja=title,
        body_ja_raw=f"{title}. Fixture body.",
        body_ja_normalized=f"{title}. Fixture body.",
        published_at=published_at,
        images=[],
        racing_region=source_region,
        source_language=SourceLanguage.ENGLISH,
        source_kind=SourceKind.MEDIA,
        metadata=metadata,
    )


class _FreshnessBatchAdapter:
    source_site = "round2_fixture"
    canonical_source_site = "round2_fixture"
    source_mode = SourceMode.OFFICIAL
    source_language = SourceLanguage.ENGLISH
    racing_region = RacingRegion.UNITED_KINGDOM
    automation_permission_status = "approved"
    skipped_items: list[str] = []
    last_listing_query_errors: list[dict] = []
    specs: tuple[dict, ...] = ()

    def fetch_listing(self, mode, page):
        del page
        return [
            SourceArticleStub(
                source_site=self.source_site,
                source_mode=mode,
                source_article_id=item["article_id"],
                source_url=f"https://round2.example/news/{item['article_id']}",
                title_ja=item["title"],
                published_at=item["published_at"],
                metadata={},
            )
            for item in self.specs
        ]

    def fetch_detail(self, source_url):
        item = next(
            item
            for item in self.specs
            if source_url.endswith(f"/{item['article_id']}")
        )
        evidence = {
            "raw": item["published_at"].isoformat(),
            "timezone": item.get("timezone", "Europe/Dublin"),
            "precision": item.get("precision"),
            "parser_version": "round2-batch-v1",
            "verified": item.get("verified", True),
        }
        if item.get("precision") is None:
            evidence.pop("precision")
        return SourceArticleDetail(
            title_ja=item["title"],
            body_ja_raw=f"{item['title']}. Fixture body.",
            body_ja_normalized=f"{item['title']}. Fixture body.",
            published_at=item["published_at"],
            images=[],
            metadata={
                "published_at_verified": item.get("verified", True),
                "published_at_evidence": evidence,
            },
        )

    def normalize_source_payload(self, stub, detail):
        return CanonicalNewsDraft(
            source_site=self.source_site,
            canonical_source_site=self.canonical_source_site,
            source_mode=stub.source_mode,
            source_article_id=stub.source_article_id,
            source_url=stub.source_url,
            title_ja=detail.title_ja,
            body_ja_raw=detail.body_ja_raw,
            body_ja_normalized=detail.body_ja_normalized,
            published_at=detail.published_at,
            images=[],
            racing_region=self.racing_region,
            source_language=self.source_language,
            source_kind=SourceKind.MEDIA,
            metadata=dict(detail.metadata),
        )


class _MixedFreshnessAdapter(_FreshnessBatchAdapter):
    specs = (
        {
            "article_id": "candidate-date",
            "title": "Irish Oaks field assembles at the Curragh",
            "published_at": datetime(2026, 7, 18, 11, tzinfo=dt_timezone.utc),
            "precision": "date",
        },
        {
            "article_id": "historical-date",
            "title": "Woodbine Oaks returns to Ontario",
            "published_at": datetime(2026, 7, 16, 16, tzinfo=dt_timezone.utc),
            "precision": "date",
            "timezone": "America/Toronto",
        },
        {
            "article_id": "missing-evidence",
            "title": "Irish Oaks update from the Curragh",
            "published_at": FIXED_CRAWLED_AT,
            "precision": None,
            "verified": False,
        },
        {
            "article_id": "invalid-timezone",
            "title": "Woodbine Oaks runners arrive in Ontario",
            "published_at": datetime(2026, 7, 18, 16, tzinfo=dt_timezone.utc),
            "precision": "date",
            "timezone": "Mars/Olympus_Mons",
        },
        {
            "article_id": "precise-time",
            "title": "Irish Oaks draw confirmed at the Curragh",
            "published_at": datetime(2026, 7, 18, 23, tzinfo=dt_timezone.utc),
            "precision": "minute",
        },
    )


class _AllHistoricalAdapter(_FreshnessBatchAdapter):
    specs = (
        {
            "article_id": "historical-one",
            "title": "Irish Oaks archive from the Curragh",
            "published_at": datetime(2026, 7, 16, 11, tzinfo=dt_timezone.utc),
            "precision": "date",
        },
        {
            "article_id": "historical-two",
            "title": "Woodbine Oaks archive from Ontario",
            "published_at": datetime(2026, 7, 15, 16, tzinfo=dt_timezone.utc),
            "precision": "date",
            "timezone": "America/Toronto",
        },
    )


class _AllUnresolvedAdapter(_FreshnessBatchAdapter):
    specs = (
        {
            "article_id": "unresolved-missing",
            "title": "Irish Oaks update from the Curragh",
            "published_at": FIXED_CRAWLED_AT,
            "precision": None,
            "verified": False,
        },
        {
            "article_id": "unresolved-zone",
            "title": "Woodbine Oaks update from Ontario",
            "published_at": datetime(2026, 7, 18, 16, tzinfo=dt_timezone.utc),
            "precision": "date",
            "timezone": "Mars/Olympus_Mons",
        },
    )


class _TwoDetailFailuresAdapter(_FreshnessBatchAdapter):
    specs = (
        {
            "article_id": "detail-failure-one",
            "title": "First synthetic detail failure",
            "published_at": FIXED_CRAWLED_AT,
            "precision": "minute",
        },
        {
            "article_id": "detail-failure-two",
            "title": "Second synthetic detail failure",
            "published_at": FIXED_CRAWLED_AT,
            "precision": "minute",
        },
    )

    def fetch_detail(self, source_url):
        raise ValueError(f"synthetic_detail_failure:{source_url}")


@override_settings(
    MULTIREGION_ATTRIBUTION_MODE="off",
    MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="off",
    MULTIREGION_CONTENT_SCOPED_CANDIDATES_ENABLED=True,
    MULTIREGION_CONTENT_SCOPED_CANDIDATE_SOURCES=["round2_fixture"],
    AUTO_TRANSLATE_ON_INGEST=True,
    TERM_DISCOVERY_ENABLED=True,
)
class CandidateFreshnessCrawlTests(Round2ContractTestCase):
    def make_source(self, adapter_key: str) -> NewsSource:
        return _make_source(
            adapter_key=adapter_key,
            source_site=adapter_key,
            racing_region=RacingRegion.UNITED_KINGDOM,
            enabled=True,
            production_approved=True,
        )

    def crawl(self, source, adapter_class):
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {source.adapter_key: adapter_class},
        ), mock.patch(
            "stable.tasks.preflight_source_access",
            create=True,
            return_value=SimpleNamespace(
                allowed=True,
                status="approved",
                reason="permission_approved",
                canonical_source_site="round2_fixture",
            ),
        ):
            try:
                return _crawl_international_source(
                    source,
                    crawled_at=FIXED_CRAWLED_AT,
                )
            except TypeError as exc:
                if "crawled_at" in str(exc):
                    self.fail(
                        "目标能力尚未实现：_crawl_international_source 尚不接受固定 crawled_at"
                    )
                raise

    def test_mixed_batch_filters_before_upsert_and_persists_fixed_metadata(self):
        source = self.make_source("round2_mixed")
        with mock.patch(
            "stable.tasks.upsert_article_from_draft",
            wraps=upsert_article_from_draft,
        ) as upsert_spy, mock.patch(
            "stable.tasks._discover_terms_after_ingest",
            return_value=None,
        ) as terms_spy, mock.patch(
            "stable.tasks._auto_translate_article_after_ingest",
            return_value=None,
        ) as translate_spy, mock.patch(
            "stable.tasks._ranked_revival_after_source_elevation",
            return_value=None,
        ) as revival_spy, mock.patch(
            "stable.tasks._qq_push_after_source_elevation",
            return_value=None,
        ) as qq_spy:
            result = self.crawl(source, _MixedFreshnessAdapter)

        self.assertEqual(result["new_count"], 2)
        self.assertEqual(upsert_spy.call_count, 2)
        upserted_ids = {
            call.args[0].source_article_id
            for call in upsert_spy.call_args_list
        }
        self.assertEqual(upserted_ids, {"candidate-date", "precise-time"})
        self.assertEqual(terms_spy.call_count, 2)
        self.assertEqual(translate_spy.call_count, 2)
        revival_spy.assert_not_called()
        qq_spy.assert_not_called()
        self.assertEqual(NewsArticle.objects.count(), 2)
        self.assertEqual(NewsSnapshot.objects.count(), 2)
        self.assertFalse(
            NewsArticle.objects.filter(
                source_article_id__in={
                    "historical-date",
                    "missing-evidence",
                    "invalid-timezone",
                }
            ).exists()
        )

        summary = result["source_summary"]
        self.assertEqual(
            set(
                (
                    "candidate_date_within_one_day",
                    "historical_date_outside_one_day",
                    "precise_time_not_applicable",
                    "published_at_missing",
                    "invalid_published_timezone",
                    "freshness_unresolved",
                )
            )
            - set(summary),
            set(),
        )
        self.assertEqual(summary["candidate_date_within_one_day"], 1)
        self.assertEqual(summary["historical_date_outside_one_day"], 1)
        self.assertEqual(summary["precise_time_not_applicable"], 1)
        self.assertEqual(summary["published_at_missing"], 1)
        self.assertEqual(summary["invalid_published_timezone"], 1)
        self.assertEqual(summary["freshness_unresolved"], 1)

        article = NewsArticle.objects.get(source_article_id="candidate-date")
        metadata = article.translation_metadata["candidate_freshness"]
        snapshot_metadata = article.snapshots.get().snapshot_metadata[
            "candidate_freshness"
        ]
        self.assertEqual(metadata, snapshot_metadata)
        self.assertEqual(
            metadata["decision"],
            "candidate_date_within_one_day",
        )
        self.assertEqual(metadata["crawled_at"], FIXED_CRAWLED_AT.isoformat())
        self.assertEqual(metadata["source_timezone"], "Europe/Dublin")
        self.assertEqual(metadata["date_difference_days"], 1)
        preview = article.translation_metadata["content_scoped_region_preview"]
        self.assertEqual(preview["primary_region"], RacingRegion.IRELAND)

    def test_all_historical_is_successful_zero_new_without_side_effects(self):
        source = self.make_source("round2_all_historical")
        with mock.patch(
            "stable.tasks.upsert_article_from_draft",
            wraps=upsert_article_from_draft,
        ) as upsert_spy, mock.patch(
            "stable.tasks._discover_terms_after_ingest",
        ) as terms_spy, mock.patch(
            "stable.tasks._auto_translate_article_after_ingest",
        ) as translate_spy, mock.patch(
            "stable.tasks._ranked_revival_after_source_elevation",
        ) as revival_spy, mock.patch(
            "stable.tasks._qq_push_after_source_elevation",
        ) as qq_spy:
            result = self.crawl(source, _AllHistoricalAdapter)

        self.assertEqual(result["new_count"], 0)
        self.assertEqual(result["seen_count"], 0)
        self.assertEqual(
            result["source_summary"]["historical_date_outside_one_day"],
            2,
        )
        upsert_spy.assert_not_called()
        terms_spy.assert_not_called()
        translate_spy.assert_not_called()
        revival_spy.assert_not_called()
        qq_spy.assert_not_called()
        self.assertEqual(NewsArticle.objects.count(), 0)
        self.assertEqual(NewsSnapshot.objects.count(), 0)
        self.assertEqual(TranslationRun.objects.count(), 0)
        job = CrawlJob.objects.get(source=source)
        self.assertEqual(job.status, TaskStatus.SUCCESS)

    def test_all_unresolved_fails_with_stable_reason_before_upsert(self):
        source = self.make_source("round2_all_unresolved")
        with mock.patch(
            "stable.tasks.upsert_article_from_draft",
            wraps=upsert_article_from_draft,
        ) as upsert_spy:
            with self.assertRaisesRegex(
                RuntimeError,
                "all_candidates_unresolved",
            ):
                self.crawl(source, _AllUnresolvedAdapter)

        upsert_spy.assert_not_called()
        self.assertEqual(NewsArticle.objects.count(), 0)
        self.assertEqual(NewsSnapshot.objects.count(), 0)
        job = CrawlJob.objects.get(source=source)
        self.assertEqual(job.status, TaskStatus.FAILED)
        self.assertIn("all_candidates_unresolved", job.error_message)

    def test_all_details_failed_job_counts_each_real_detail_error(self):
        source = self.make_source("round2_two_detail_failures")
        with self.assertRaisesRegex(
            RuntimeError,
            "all_details_failed",
        ):
            self.crawl(source, _TwoDetailFailuresAdapter)

        job = CrawlJob.objects.get(source=source)
        self.assertEqual(job.status, TaskStatus.FAILED)
        self.assertEqual(
            job.fail_count,
            2,
            "all_details_failed 必须记录真实 detail_errors 数，不能退化为 seen_count=0",
        )
        self.assertEqual(NewsArticle.objects.count(), 0)
        self.assertEqual(NewsSnapshot.objects.count(), 0)

    def test_success_window_includes_full_source_summary(self):
        success_source = self.make_source("round2_window_success")
        start = FIXED_CRAWLED_AT.replace(minute=15)
        success_window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source=success_source,
            scope_key="round2:success",
            window_start=start,
            window_end=start + timedelta(minutes=15),
            status=ProductionWindowStatus.RUNNING,
        )
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {"round2_window_success": _MixedFreshnessAdapter},
        ), mock.patch(
            "stable.tasks.preflight_source_access",
            create=True,
            return_value=SimpleNamespace(
                allowed=True,
                status="approved",
                reason="permission_approved",
                canonical_source_site="round2_fixture",
            ),
        ), mock.patch(
            "stable.tasks.timezone.now",
            return_value=FIXED_CRAWLED_AT,
        ), mock.patch(
            "stable.tasks._discover_terms_after_ingest",
            return_value=None,
        ), mock.patch(
            "stable.tasks._auto_translate_article_after_ingest",
            return_value=None,
        ):
            crawl_news_source_task.run(success_source.id, success_window.id)

        success_window.refresh_from_db()
        self.assertEqual(success_window.status, ProductionWindowStatus.SUCCEEDED)
        if "source_summary" not in success_window.result_payload:
            self.fail(
                "目标能力尚未实现：成功 crawl window payload 缺少 source_summary"
            )
        success_summary = success_window.result_payload["source_summary"]
        self.assertEqual(success_summary["candidate_date_within_one_day"], 1)
        self.assertEqual(success_summary["historical_date_outside_one_day"], 1)
        self.assertEqual(success_summary["freshness_unresolved"], 1)

    def test_unresolved_failure_window_includes_summary_and_stable_category(self):
        start = FIXED_CRAWLED_AT.replace(minute=15)
        failure_source = self.make_source("round2_window_unresolved")
        failure_window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source=failure_source,
            scope_key="round2:failure",
            window_start=start,
            window_end=start + timedelta(minutes=15),
            status=ProductionWindowStatus.RUNNING,
        )
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {"round2_window_unresolved": _AllUnresolvedAdapter},
        ), mock.patch(
            "stable.tasks.preflight_source_access",
            create=True,
            return_value=SimpleNamespace(
                allowed=True,
                status="approved",
                reason="permission_approved",
                canonical_source_site="round2_fixture",
            ),
        ), mock.patch(
            "stable.tasks.timezone.now",
            return_value=FIXED_CRAWLED_AT,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "all_candidates_unresolved",
            ):
                crawl_news_source_task.run(
                    failure_source.id,
                    failure_window.id,
                )

        failure_window.refresh_from_db()
        self.assertEqual(failure_window.status, ProductionWindowStatus.FAILED)
        if "source_summary" not in failure_window.result_payload:
            self.fail(
                "目标能力尚未实现：失败 crawl window payload 缺少 source_summary"
            )
        self.assertEqual(
            failure_window.result_payload["error_category"],
            "all_candidates_unresolved",
        )
        failure_summary = failure_window.result_payload["source_summary"]
        self.assertEqual(failure_summary["freshness_unresolved"], 2)
        self.assertEqual(failure_summary["historical_date_outside_one_day"], 0)


@dataclass(frozen=True)
class _FrozenPreviewFixture:
    target_region: str
    confidence: int
    needs_review: bool
    evidence: dict
    related_regions: tuple[str, ...] = ()
    reason: str = "round2_fixture"
    rule_version: str = "round2-fixture-v1"

    @property
    def primary_region(self) -> str:
        return self.target_region

    @property
    def status(self) -> str:
        return "accepted" if not self.needs_review else "needs_review"


class _SingleDraftAdapter:
    source_site = "round2_fixture"
    canonical_source_site = "round2_fixture"
    source_mode = SourceMode.OFFICIAL
    source_language = SourceLanguage.ENGLISH
    racing_region = RacingRegion.UNITED_KINGDOM
    automation_permission_status = "approved"
    skipped_items: list[str] = []
    last_listing_query_errors: list[dict] = []
    draft: CanonicalNewsDraft | None = None

    def fetch_listing(self, mode, page):
        del page
        assert self.draft is not None
        return [
            SourceArticleStub(
                source_site=self.source_site,
                source_mode=mode,
                source_article_id=self.draft.source_article_id,
                source_url=self.draft.source_url,
                title_ja=self.draft.title_ja,
                published_at=self.draft.published_at,
                metadata={},
            )
        ]

    def fetch_detail(self, source_url):
        del source_url
        assert self.draft is not None
        return SourceArticleDetail(
            title_ja=self.draft.title_ja,
            body_ja_raw=self.draft.body_ja_raw,
            body_ja_normalized=self.draft.body_ja_normalized,
            published_at=self.draft.published_at,
            images=[],
            metadata=dict(self.draft.metadata),
        )

    def normalize_source_payload(self, stub, detail):
        del stub, detail
        assert self.draft is not None
        return self.draft


@override_settings(
    MULTIREGION_ATTRIBUTION_MODE="off",
    MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="off",
    MULTIREGION_CONTENT_SCOPED_CANDIDATES_ENABLED=True,
    MULTIREGION_CONTENT_SCOPED_CANDIDATE_SOURCES=[
        SourceSite.SPORTING_LIFE,
        SourceSite.BLOODHORSE,
        "round2_fixture",
    ],
    AUTO_TRANSLATE_ON_INGEST=False,
    TERM_DISCOVERY_ENABLED=False,
)
class ContentScopedFreshnessIntegrationTests(Round2ContractTestCase):
    def crawl(self, source, adapter_class):
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {source.adapter_key: adapter_class},
        ), mock.patch(
            "stable.tasks.preflight_source_access",
            create=True,
            return_value=SimpleNamespace(
                allowed=True,
                status="approved",
                reason="permission_approved",
                canonical_source_site=adapter_class.canonical_source_site,
            ),
        ):
            try:
                return _crawl_international_source(
                    source,
                    crawled_at=FIXED_CRAWLED_AT,
                )
            except TypeError as exc:
                if "crawled_at" in str(exc):
                    self.fail(
                        "目标能力尚未实现：target/legacy 集成路径尚不接受固定 crawled_at"
                    )
                raise

    def adapter_for(self, name: str, draft: CanonicalNewsDraft):
        return type(
            name,
            (_SingleDraftAdapter,),
            {
                "source_site": draft.source_site,
                "canonical_source_site": draft.canonical_source_site,
                "racing_region": draft.racing_region,
                "draft": draft,
            },
        )

    def test_same_canonical_uk_us_target_missing_time_stops_before_upsert(self):
        cases = (
            (
                "round2_irish_missing",
                SourceSite.SPORTING_LIFE,
                RacingRegion.UNITED_KINGDOM,
                RacingRegion.IRELAND,
                "Irish Oaks field assembles at the Curragh",
            ),
            (
                "round2_canada_missing",
                SourceSite.BLOODHORSE,
                RacingRegion.UNITED_STATES,
                RacingRegion.CANADA,
                "Woodbine Oaks returns to Ontario",
            ),
        )
        for adapter_key, source_site, source_region, target_region, title in cases:
            with self.subTest(target_region=target_region):
                source = _make_source(
                    adapter_key=adapter_key,
                    source_site=source_site,
                    racing_region=source_region,
                    enabled=True,
                    production_approved=True,
                )
                draft = _draft(
                    article_id=f"{adapter_key}-article",
                    title=title,
                    published_at=FIXED_CRAWLED_AT,
                    precision=None,
                    verified=False,
                    source_region=source_region,
                    source_site=source_site,
                )
                adapter = self.adapter_for(
                    f"{adapter_key.title()}Adapter",
                    draft,
                )
                preview = _FrozenPreviewFixture(
                    target_region=target_region,
                    confidence=95,
                    needs_review=False,
                    evidence={"event": title},
                )
                with mock.patch(
                    "stable.tasks.preview_content_scoped_region",
                    create=True,
                    return_value=preview,
                ), mock.patch(
                    "stable.tasks.upsert_article_from_draft",
                    wraps=upsert_article_from_draft,
                ) as upsert_spy:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "all_candidates_unresolved",
                    ):
                        self.crawl(source, adapter)
                upsert_spy.assert_not_called()
                self.assertFalse(
                    NewsArticle.objects.filter(
                        source_article_id=draft.source_article_id,
                    ).exists()
                )

    def test_same_canonical_ordinary_uk_us_missing_time_keeps_legacy_upsert(self):
        preview_class = self.require_symbol(
            "stable.services.news_attribution",
            "AttributionPreview",
        )
        cases = (
            (
                "round2_plain_uk_missing",
                SourceSite.SPORTING_LIFE,
                RacingRegion.UNITED_KINGDOM,
                "Royal Ascot card takes shape",
            ),
            (
                "round2_plain_us_missing",
                SourceSite.BLOODHORSE,
                RacingRegion.UNITED_STATES,
                "Kentucky Derby preparations continue",
            ),
        )
        for adapter_key, source_site, source_region, title in cases:
            with self.subTest(source_region=source_region):
                source = _make_source(
                    adapter_key=adapter_key,
                    source_site=source_site,
                    racing_region=source_region,
                    enabled=True,
                    production_approved=True,
                )
                draft = _draft(
                    article_id=f"{adapter_key}-article",
                    title=title,
                    published_at=FIXED_CRAWLED_AT,
                    precision=None,
                    verified=False,
                    source_region=source_region,
                    source_site=source_site,
                )
                adapter = self.adapter_for(
                    f"{adapter_key.title()}Adapter",
                    draft,
                )
                preview = preview_class(
                    target_region=source_region,
                    confidence=90,
                    needs_review=False,
                    evidence={"source_region": source_region},
                )
                with mock.patch(
                    "stable.tasks.preview_content_scoped_region",
                    create=True,
                    return_value=preview,
                ), mock.patch(
                    "stable.tasks.upsert_article_from_draft",
                    wraps=upsert_article_from_draft,
                ) as upsert_spy:
                    result = self.crawl(source, adapter)
                self.assertEqual(result["new_count"], 1)
                self.assertEqual(upsert_spy.call_count, 1)
                self.assertTrue(
                    NewsArticle.objects.filter(
                        source_article_id=draft.source_article_id,
                    ).exists()
                )

    def test_preview_is_immutable_computed_once_and_passed_by_identity(self):
        preview_class = self.require_symbol(
            "stable.services.news_attribution",
            "AttributionPreview",
        )
        preview = preview_class(
            target_region=RacingRegion.IRELAND,
            confidence=96,
            needs_review=False,
            evidence={"event": "irish_oaks", "location": "curragh"},
        )
        with self.assertRaises(FrozenInstanceError):
            preview.confidence = 1

        source = _make_source(
            adapter_key="round2_preview_identity",
            source_site=SourceSite.SPORTING_LIFE,
            racing_region=RacingRegion.UNITED_KINGDOM,
            enabled=True,
            production_approved=True,
        )
        draft = _draft(
            article_id="preview-identity",
            title="Irish Oaks field assembles at the Curragh",
            published_at=datetime(2026, 7, 18, 11, tzinfo=dt_timezone.utc),
            precision="date",
            source_region=RacingRegion.UNITED_KINGDOM,
            source_site=SourceSite.SPORTING_LIFE,
        )
        adapter = self.adapter_for("PreviewIdentityAdapter", draft)
        with mock.patch(
            "stable.tasks.preview_content_scoped_region",
            create=True,
            return_value=preview,
        ) as preview_spy, mock.patch(
            "stable.tasks.upsert_article_from_draft",
            wraps=upsert_article_from_draft,
        ) as upsert_spy, mock.patch(
            "stable.services.ingestion.apply_article_attribution",
            wraps=importlib.import_module(
                "stable.services.news_attribution"
            ).apply_article_attribution,
        ) as attribution_spy:
            self.crawl(source, adapter)

        self.assertEqual(preview_spy.call_count, 1)
        self.assertEqual(upsert_spy.call_count, 1)
        self.assertIs(
            upsert_spy.call_args.kwargs.get("attribution_preview"),
            preview,
        )
        self.assertEqual(attribution_spy.call_count, 1)
        self.assertIs(
            attribution_spy.call_args.kwargs.get("attribution_preview"),
            preview,
        )

    def test_content_scoped_allowlist_requires_explicit_preview_before_writes(self):
        draft = _draft(
            article_id="missing-explicit-preview",
            title="Irish Oaks field assembles at the Curragh",
            published_at=datetime(2026, 7, 18, 11, tzinfo=dt_timezone.utc),
            precision="date",
            source_region=RacingRegion.UNITED_KINGDOM,
            source_site="round2_fixture",
        )
        with self.assertRaisesRegex(
            Exception,
            "attribution_preview_required",
        ):
            upsert_article_from_draft(draft)
        self.assertEqual(NewsArticle.objects.count(), 0)
        self.assertEqual(NewsSnapshot.objects.count(), 0)

    def test_forged_metadata_preview_cannot_replace_explicit_preview_before_side_effects(self):
        draft = _draft(
            article_id="forged-metadata-preview",
            title="Irish Oaks field assembles at the Curragh",
            published_at=datetime(2026, 7, 18, 11, tzinfo=dt_timezone.utc),
            precision="date",
            source_region=RacingRegion.UNITED_KINGDOM,
            source_site="round2_fixture",
        )
        draft.metadata["content_scoped_region_preview"] = {
            "primary_region": RacingRegion.IRELAND,
            "related_regions": [],
            "reason": "forged_high_confidence",
            "evidence": {"event": {"keywords": ["irish oaks", "curragh"]}},
            "status": "applied",
            "confidence": 100,
            "rule_version": "forged-review-bypass",
        }
        draft.images = [
            SourceImageDraft(
                original_url="https://round2.example/forged-cover.jpg",
                caption_ja="must not be downloaded",
            )
        ]

        caught = None
        with mock.patch(
            "stable.services.ingestion.download_image",
            return_value="/tmp/forged-cover.jpg",
        ) as download_spy:
            try:
                upsert_article_from_draft(draft)
            except Exception as exc:  # 目标合同必须在任何副作用前进入此分支。
                caught = exc

        with self.subTest(contract="explicit_preview_required"):
            self.assertIsNotNone(caught)
            self.assertRegex(
                str(caught or ""),
                "attribution_preview_required",
            )
        with self.subTest(contract="no_image_or_file_side_effect"):
            download_spy.assert_not_called()
        with self.subTest(contract="no_article_write"):
            self.assertEqual(NewsArticle.objects.count(), 0)
        with self.subTest(contract="no_snapshot_write"):
            self.assertEqual(NewsSnapshot.objects.count(), 0)

    def test_exact_real_attribution_result_is_accepted_for_allowlisted_ingestion(self):
        result_class = self.require_symbol(
            "stable.services.news_attribution",
            "AttributionResult",
        )
        attribution_result = result_class(
            primary_region=RacingRegion.IRELAND,
            related_regions=[],
            reason="content_scoped_result_fixture",
            evidence={"event": {"keywords": ["irish oaks", "curragh"]}},
            status="applied",
            confidence=96,
            rule_version="round2-result-fixture-v1",
        )
        self.assertIs(type(attribution_result), result_class)
        draft = _draft(
            article_id="exact-real-attribution-result",
            title="Irish Oaks field assembles at the Curragh",
            published_at=datetime(2026, 7, 18, 11, tzinfo=dt_timezone.utc),
            precision="date",
            source_region=RacingRegion.UNITED_KINGDOM,
            source_site="round2_fixture",
        )

        caught = None
        upsert_result = None
        try:
            upsert_result = upsert_article_from_draft(
                draft,
                attribution_preview=attribution_result,
            )
        except Exception as exc:  # RED 必须收敛为目标 assertion failure，而非 ERROR。
            caught = exc

        with self.subTest(contract="exact_result_is_allowed"):
            self.assertIsNone(
                caught,
                "allowlisted ingestion 必须接受 exact real AttributionResult",
            )
        if caught is not None:
            return

        self.assertIsNotNone(upsert_result)
        self.assertTrue(upsert_result.created)
        candidate = (
            upsert_result.article.attribution_summary or {}
        ).get("review_candidate", {})
        self.assertEqual(candidate.get("primary_region"), RacingRegion.IRELAND)

    def test_direct_apply_rejects_fake_preview_and_result_before_write_side_effects(
        self,
    ):
        attribution_module = importlib.import_module(
            "stable.services.news_attribution"
        )
        apply_attribution = attribution_module.apply_article_attribution
        preview_class = self.require_symbol(
            "stable.services.news_attribution",
            "AttributionPreview",
        )
        result_class = self.require_symbol(
            "stable.services.news_attribution",
            "AttributionResult",
        )
        source = _make_source(
            adapter_key="round2_fixture",
            source_site="round2_fixture",
            racing_region=RacingRegion.UNITED_KINGDOM,
            enabled=True,
            production_approved=True,
        )
        tracked_fields = (
            "attribution_summary",
            "attribution_status",
            "attribution_confidence",
            "attribution_rule_version",
            "attribution_locked",
            "gate_issues",
            "review_mode",
            "automation_status",
            "content_category",
        )

        for label, exact_class in (
            ("fake_preview", preview_class),
            ("fake_result", result_class),
        ):
            article = NewsArticle.objects.create(
                source_config=source,
                source_site="round2_fixture",
                source_mode=SourceMode.OFFICIAL,
                source_article_id=f"direct-apply-{label}",
                source_url=f"https://round2.example/news/direct-apply-{label}",
                racing_region=RacingRegion.UNITED_KINGDOM,
                source_language=SourceLanguage.ENGLISH,
                title_ja="Irish Oaks field assembles at the Curragh",
                body_ja_raw="The Irish Classic is staged at the Curragh.",
                body_ja_normalized="The Irish Classic is staged at the Curragh.",
                published_at=FIXED_CRAWLED_AT,
            )
            fake = mock.Mock(spec=exact_class)
            fake.primary_region = RacingRegion.IRELAND
            fake.related_regions = ()
            fake.reason = f"forged_{label}"
            fake.evidence = {
                "event": {"keywords": ["irish oaks", "curragh"]},
                "forged": True,
            }
            fake.status = "applied"
            fake.confidence = 100
            fake.rule_version = f"forged-{label}-v1"
            fake.content_category = "news"
            self.assertIsInstance(
                fake,
                exact_class,
                "测试替身必须能伪造 isinstance，才能锁定 exact type 边界",
            )
            before = {
                field: getattr(article, field)
                for field in tracked_fields
            }
            caught = None
            with mock.patch(
                "stable.services.news_attribution._save_content_scoped_review_candidate",
                wraps=attribution_module._save_content_scoped_review_candidate,
            ) as candidate_save_spy, mock.patch.object(
                article,
                "save",
                wraps=article.save,
            ) as article_save_spy:
                try:
                    apply_attribution(
                        article,
                        source_config=source,
                        is_new_article=True,
                        attribution_preview=fake,
                    )
                except Exception as exc:  # 目标合同必须在任何副作用前进入此分支。
                    caught = exc

            after_memory = {
                field: getattr(article, field)
                for field in tracked_fields
            }
            after_database = NewsArticle.objects.values(*tracked_fields).get(
                pk=article.pk,
            )
            with self.subTest(case=label, contract="fake_is_rejected"):
                self.assertIsNotNone(caught)
                self.assertRegex(
                    str(caught or ""),
                    "^attribution_preview_required$",
                )
            with self.subTest(
                case=label,
                contract="candidate_save_helper_not_called",
            ):
                candidate_save_spy.assert_not_called()
            with self.subTest(case=label, contract="article_save_not_called"):
                article_save_spy.assert_not_called()
            with self.subTest(
                case=label,
                contract="article_fields_unchanged",
            ):
                self.assertEqual(
                    {
                        "memory": after_memory,
                        "database": after_database,
                    },
                    {
                        "memory": before,
                        "database": before,
                    },
                )

    def test_non_none_fake_preview_is_rejected_before_side_effects(self):
        preview_class = self.require_symbol(
            "stable.services.news_attribution",
            "AttributionPreview",
        )
        fake_preview = mock.Mock(spec=preview_class)
        fake_preview.target_region = RacingRegion.IRELAND
        fake_preview.primary_region = RacingRegion.IRELAND
        fake_preview.confidence = 100
        fake_preview.needs_review = False
        fake_preview.status = "applied"
        fake_preview.evidence = {
            "event": {"keywords": ["irish oaks", "curragh"]},
            "forged": True,
        }
        fake_preview.related_regions = ()
        fake_preview.reason = "forged_preview_object"
        fake_preview.rule_version = "forged-preview-v1"
        fake_preview.content_category = "news"
        self.assertIsInstance(
            fake_preview,
            preview_class,
            "该回归专门覆盖可伪造 __class__/spec、能绕过浅层 isinstance 的 fake",
        )

        draft = _draft(
            article_id="non-none-fake-preview",
            title="Irish Oaks field assembles at the Curragh",
            published_at=datetime(2026, 7, 18, 11, tzinfo=dt_timezone.utc),
            precision="date",
            source_region=RacingRegion.UNITED_KINGDOM,
            source_site="round2_fixture",
        )
        draft.images = [
            SourceImageDraft(
                original_url="https://round2.example/fake-preview-cover.jpg",
                caption_ja="must not be downloaded",
            )
        ]

        caught = None
        with mock.patch(
            "stable.services.ingestion.download_image",
            return_value="/tmp/fake-preview-cover.jpg",
        ) as download_spy:
            try:
                upsert_article_from_draft(
                    draft,
                    attribution_preview=fake_preview,
                )
            except Exception as exc:  # 精确合同要求在任何副作用前进入此分支。
                caught = exc

        with self.subTest(contract="real_preview_instance_required"):
            self.assertIsNotNone(caught)
            self.assertRegex(
                str(caught or ""),
                "attribution_preview_required",
            )
        with self.subTest(contract="no_image_or_file_side_effect"):
            download_spy.assert_not_called()
        with self.subTest(contract="no_article_write"):
            self.assertEqual(NewsArticle.objects.count(), 0)
        with self.subTest(contract="no_snapshot_write"):
            self.assertEqual(NewsSnapshot.objects.count(), 0)


class AttributionPreviewImmutabilityTests(Round2ContractTestCase):
    def test_evidence_and_related_regions_are_deeply_immutable(self):
        preview_class = self.require_symbol(
            "stable.services.news_attribution",
            "AttributionPreview",
        )
        source_evidence = {
            "event": {
                "keywords": ["irish oaks", "curragh"],
                "scores": [95, 90],
            }
        }
        source_related = [RacingRegion.UNITED_KINGDOM]
        preview = preview_class(
            target_region=RacingRegion.IRELAND,
            confidence=96,
            needs_review=False,
            evidence=source_evidence,
            related_regions=source_related,
        )

        source_evidence["event"]["keywords"].append("external mutation")
        source_related.append(RacingRegion.CANADA)
        with self.subTest(contract="defensive_deep_copy"):
            self.assertEqual(
                tuple(preview.evidence["event"]["keywords"]),
                ("irish oaks", "curragh"),
            )
            self.assertEqual(
                preview.related_regions,
                (RacingRegion.UNITED_KINGDOM,),
            )

        with self.subTest(contract="nested_mapping_immutable"):
            with self.assertRaises((TypeError, AttributeError)):
                preview.evidence["event"]["new_key"] = "mutation"
        with self.subTest(contract="nested_sequence_immutable"):
            with self.assertRaises((TypeError, AttributeError)):
                preview.evidence["event"]["keywords"].append("mutation")
        with self.subTest(contract="related_regions_immutable"):
            with self.assertRaises((TypeError, AttributeError)):
                preview.related_regions.append(RacingRegion.CANADA)


class _FakeHttpResponse:
    def __init__(
        self,
        status_code: int,
        *,
        url: str = "https://round2.example/news",
        location: str = "",
        body: bytes = b"<html><body>fixture</body></html>",
    ):
        self.status_code = status_code
        self.url = url
        self.encoding = "utf-8"
        self.headers = {}
        if location:
            self.headers["Location"] = location
        if status_code == 200:
            self.headers.update(
                {
                    "Content-Type": "text/html; charset=utf-8",
                    "Content-Length": str(len(body)),
                }
            )
        self._body = body

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        del chunk_size
        yield self._body

    def close(self):
        return None


class SourceRequestBudgetTransportTests(Round2ContractTestCase):
    def test_exhausted_adapter_request_preserves_previous_succeeded_ledger_entry(self):
        budget = self.request_budget("jcsa_news")
        adapter = JCSANewsAdapter()
        adapter.attach_request_budget(budget)
        session = mock.Mock()
        session.get.return_value = _FakeHttpResponse(
            200,
            url="https://jcsa.sa/api/news/en/0/12",
        )
        with mock.patch(
            "stable.services.http.requests.Session",
            return_value=session,
        ):
            adapter._bounded_html(
                "https://jcsa.sa/api/news/en/0/12",
                request_kind="listing",
            )
            self.assertEqual(len(budget.ledger), 1)
            self.assertEqual(budget.ledger[0]["status"], "succeeded")

            with self.assertRaisesRegex(
                Exception,
                "source_request_budget_exhausted",
            ):
                adapter._bounded_html(
                    "https://jcsa.sa/api/news/en/0/12",
                    request_kind="listing",
                )

        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(len(budget.ledger), 1)
        self.assertEqual(
            budget.ledger[0]["status"],
            "succeeded",
            "预算耗尽没有新增 attempt，不得把上一条 succeeded 误标为 failed",
        )

    def test_exhausted_adapter_request_preserves_previous_failed_ledger_entry(self):
        budget = self.request_budget("jcsa_news")
        adapter = JCSANewsAdapter()
        adapter.attach_request_budget(budget)
        session = mock.Mock()
        session.get.return_value = _FakeHttpResponse(
            503,
            url="https://jcsa.sa/api/news/en/0/12",
        )
        with mock.patch(
            "stable.services.http.requests.Session",
            return_value=session,
        ):
            with self.assertRaisesRegex(
                Exception,
                "bounded_http_unexpected_status",
            ):
                adapter._bounded_html(
                    "https://jcsa.sa/api/news/en/0/12",
                    request_kind="listing",
                )
            self.assertEqual(len(budget.ledger), 1)
            self.assertEqual(budget.ledger[0]["status"], "failed")
            failed_attempt = dict(budget.ledger[0])

            with self.assertRaisesRegex(
                Exception,
                "source_request_budget_exhausted",
            ):
                adapter._bounded_html(
                    "https://jcsa.sa/api/news/en/0/12",
                    request_kind="listing",
                )

        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(len(budget.ledger), 1)
        self.assertEqual(
            budget.ledger[0],
            failed_attempt,
            "预算耗尽没有新 transport hop，不得改写上一条 failed ledger",
        )

    def test_redirect_next_hop_exhaustion_preserves_redirected_ledger_entry(self):
        budget = self.request_budget("jcsa_news")
        adapter = JCSANewsAdapter()
        adapter.attach_request_budget(budget)
        session = mock.Mock()
        session.get.return_value = _FakeHttpResponse(
            302,
            url="https://jcsa.sa/api/news/en/0/12",
            location="/api/news/en/12/12",
        )
        with mock.patch(
            "stable.services.http.requests.Session",
            return_value=session,
        ):
            with self.assertRaisesRegex(
                Exception,
                "source_request_budget_exhausted",
            ):
                adapter._bounded_html(
                    "https://jcsa.sa/api/news/en/0/12",
                    request_kind="listing",
                )

        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(len(budget.ledger), 1)
        self.assertEqual(
            budget.ledger[0]["status"],
            "redirected",
            "redirect 次跳在 transport 前耗尽，没有新增 attempt，不得覆盖上一跳状态",
        )

    def test_listing_redirect_and_failed_response_consume_actual_get(self):
        redirect_budget = self.request_budget("jcsa_news")
        redirect_session = mock.Mock()
        redirect_session.get.side_effect = [
            _FakeHttpResponse(
                302,
                location="/redirected",
                url="https://round2.example/news",
            ),
            _FakeHttpResponse(200, url="https://round2.example/redirected"),
        ]
        with mock.patch(
            "stable.services.http.requests.Session",
            return_value=redirect_session,
        ):
            with self.assertRaisesRegex(
                Exception,
                "source_request_budget_exhausted",
            ):
                self.bounded_html(
                    "https://round2.example/news",
                    budget=redirect_budget,
                    kind="listing",
                )
        self.assertEqual(redirect_session.get.call_count, 1)

        failed_budget = self.request_budget("racing_victoria_news")
        failed_session = mock.Mock()
        failed_session.get.return_value = _FakeHttpResponse(
            503,
            url="https://round2.example/news",
        )
        with mock.patch(
            "stable.services.http.requests.Session",
            return_value=failed_session,
        ):
            with self.assertRaisesRegex(Exception, "bounded_http_unexpected_status"):
                self.bounded_html(
                    "https://round2.example/news",
                    budget=failed_budget,
                    kind="listing",
                )
            with self.assertRaisesRegex(
                Exception,
                "source_request_budget_exhausted",
            ):
                self.bounded_html(
                    "https://round2.example/news",
                    budget=failed_budget,
                    kind="listing",
                )
        self.assertEqual(failed_session.get.call_count, 1)

    def test_detail_redirect_uses_two_gets_then_exhaustion_adds_none(self):
        budget = self.request_budget("jcsa_news")
        session = mock.Mock()
        session.get.side_effect = [
            _FakeHttpResponse(
                302,
                location="/detail/final",
                url="https://round2.example/detail/start",
            ),
            _FakeHttpResponse(
                200,
                url="https://round2.example/detail/final",
            ),
        ]
        with mock.patch(
            "stable.services.http.requests.Session",
            return_value=session,
        ):
            response = self.bounded_html(
                "https://round2.example/detail/start",
                budget=budget,
                kind="detail",
            )
            self.assertEqual(response.redirect_count, 1)
            self.assertEqual(session.get.call_count, 2)
            with self.assertRaisesRegex(
                Exception,
                "source_request_budget_exhausted",
            ):
                self.bounded_html(
                    "https://round2.example/detail/third",
                    budget=budget,
                    kind="detail",
                )
        self.assertEqual(session.get.call_count, 2)

    def test_blocked_zero_budget_and_two_sources_are_isolated(self):
        blocked = self.request_budget(
            "tdn",
            listing_limit=0,
            detail_limit=0,
        )
        blocked_session = mock.Mock()
        with mock.patch(
            "stable.services.http.requests.Session",
            return_value=blocked_session,
        ):
            with self.assertRaisesRegex(
                Exception,
                "source_request_budget_exhausted",
            ):
                self.bounded_html(
                    "https://round2.example/news",
                    budget=blocked,
                    kind="listing",
                )
        blocked_session.get.assert_not_called()

        first = self.request_budget("jcsa_news")
        second = self.request_budget("racing_victoria_news")
        sessions = []
        for budget in (first, second):
            session = mock.Mock()
            session.get.return_value = _FakeHttpResponse(200)
            sessions.append(session)
            with mock.patch(
                "stable.services.http.requests.Session",
                return_value=session,
            ):
                self.bounded_html(
                    "https://round2.example/news",
                    budget=budget,
                    kind="listing",
                )
        self.assertEqual([session.get.call_count for session in sessions], [1, 1])
        self.assertIsNot(first.ledger, second.ledger)
        self.assertEqual(len(first.ledger), 1)
        self.assertEqual(len(second.ledger), 1)


class ScheduledPermissionBoundaryTests(Round2ContractTestCase):
    def test_managed_registry_is_exact_and_tdn_aliases_resolve_canonically(self):
        managed = self.require_symbol(
            "stable.services.source_permissions",
            "MANAGED_PERMISSION_SOURCES",
        )
        self.assertEqual(
            set(managed),
            {
                SourceSite.HRI_NEWS,
                SourceSite.WOODBINE_NEWS,
                SourceSite.EMIRATES_RACING_AUTHORITY,
                SourceSite.JCSA_NEWS,
                SourceSite.RACING_VICTORIA_NEWS,
                SourceSite.TDN,
            },
        )
        resolver = self.require_symbol(
            "stable.services.source_permissions",
            "resolve_source_permission",
        )
        for adapter in (
            TDNAdapter(),
            TDNFranceKeywordAdapter(),
            TDNFranceBroadKeywordAdapter(),
        ):
            with self.subTest(adapter=adapter.__class__.__name__):
                decision = resolver(adapter)
                self.assertEqual(
                    _field(decision, "canonical_source_site"),
                    SourceSite.TDN,
                )

    def test_technically_blocked_direct_source_is_zero_request_for_both_flag_values(self):
        source = _make_source(
            adapter_key="round2_blocked_hri",
            source_site=SourceSite.HRI_NEWS,
            racing_region=RacingRegion.IRELAND,
            enabled=True,
            production_approved=True,
        )
        for flag_enabled in (False, True):
            with self.subTest(flag_enabled=flag_enabled), self.settings(
                NEWS_SOURCE_PERMISSION_PREFLIGHT_ENFORCEMENT_ENABLED=flag_enabled,
            ):
                _NeverFetchBlockedHRIAlias.fetch_listing_calls = 0
                with mock.patch.dict(
                    INTERNATIONAL_ADAPTERS,
                    {source.adapter_key: _NeverFetchBlockedHRIAlias},
                ):
                    with self.assertRaisesRegex(
                        Exception,
                        "technical_access_blocked",
                    ):
                        crawl_news_source_task.run(source.id)
                self.assertEqual(
                    _NeverFetchBlockedHRIAlias.fetch_listing_calls,
                    0,
                )
                job = CrawlJob.objects.filter(source=source).order_by(
                    "-id"
                ).first()
                self.assertIsNotNone(job)
                self.assertEqual(job.status, TaskStatus.FAILED)
                self.assertIn(
                    "technical_access_blocked",
                    job.error_message,
                )

    @override_settings(
        NEWS_SOURCE_PERMISSION_PREFLIGHT_ENFORCEMENT_ENABLED=False,
    )
    def test_forged_window_id_does_not_relax_technical_block(self):
        source = _make_source(
            adapter_key="round2_forged_window_hri",
            source_site=SourceSite.HRI_NEWS,
            racing_region=RacingRegion.IRELAND,
            enabled=True,
            production_approved=True,
        )
        start = FIXED_CRAWLED_AT.replace(minute=15)
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.UNITED_STATES,
            source=source,
            scope_key="round2:forged-window",
            window_start=start,
            window_end=start + timedelta(minutes=15),
            status=ProductionWindowStatus.RUNNING,
        )
        _NeverFetchBlockedHRIAlias.fetch_listing_calls = 0
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {source.adapter_key: _NeverFetchBlockedHRIAlias},
        ):
            with self.assertRaisesRegex(
                Exception,
                "technical_access_blocked",
            ):
                crawl_news_source_task.run(source.id, window.id)
        self.assertEqual(_NeverFetchBlockedHRIAlias.fetch_listing_calls, 0)
        self.assertEqual(NewsArticle.objects.count(), 0)
        self.assertEqual(NewsSnapshot.objects.count(), 0)
        self.assertEqual(TranslationRun.objects.count(), 0)

    @override_settings(
        NEWS_SOURCE_POLL_ENABLED=True,
        NEWS_SOURCE_POLL_MAX_SOURCES=10,
        NEWS_SOURCE_PERMISSION_PREFLIGHT_ENFORCEMENT_ENABLED=False,
    )
    def test_flag_off_automatic_selection_set_is_exact_and_dispatches_scheduled_task(self):
        legacy = _make_source(
            adapter_key="sporting_life",
            source_site=SourceSite.SPORTING_LIFE,
            racing_region=RacingRegion.UNITED_KINGDOM,
            enabled=True,
            production_approved=True,
        )
        managed = _make_source(
            adapter_key="tdn",
            source_site=SourceSite.TDN,
            racing_region=RacingRegion.UNITED_STATES,
            enabled=True,
            production_approved=True,
        )
        allowed_ids = {str(legacy.id), str(managed.id)}
        baseline = select_due_enabled_news_sources(
            max_sources=10,
            allowed_sources=allowed_ids,
        )
        expected_ids = [item.source.id for item in baseline.selected]
        scheduled_task = self.require_symbol(
            "stable.tasks",
            "crawl_scheduled_news_source_task",
        )
        forbidden = {
            "origin",
            "bypass",
            "permission_policy",
            "scheduled_policy",
        }
        self.assertEqual(
            forbidden.intersection(inspect.signature(scheduled_task.run).parameters),
            set(),
        )

        with self.settings(
            NEWS_SOURCE_POLL_ALLOWED_SOURCES=sorted(allowed_ids),
        ), mock.patch(
            "stable.tasks.dispatch_task",
            return_value=SimpleNamespace(id="round2-dispatch"),
        ) as dispatch_spy:
            result = crawl_enabled_news_sources_task.run()

        self.assertEqual(result["triggered_source_ids"], expected_ids)
        self.assertEqual(
            [call.args[1] for call in dispatch_spy.call_args_list],
            expected_ids,
        )
        self.assertTrue(
            all(
                call.args[0] is scheduled_task
                for call in dispatch_spy.call_args_list
            )
        )

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=["france"],
        MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES=15,
        NEWS_SOURCE_PERMISSION_PREFLIGHT_ENFORCEMENT_ENABLED=False,
    )
    def test_flag_off_production_window_dispatches_internal_scheduled_task_for_tdn_family(
        self,
    ):
        source = _make_source(
            adapter_key="tdn_france",
            source_site=SourceSite.TDN_FRANCE,
            racing_region=RacingRegion.FRANCE,
            enabled=True,
            production_approved=True,
        )
        scheduled_task = self.require_symbol(
            "stable.tasks",
            "crawl_scheduled_news_source_task",
        )
        public_task = self.require_symbol(
            "stable.tasks",
            "crawl_news_source_task",
        )
        scheduler_task = self.require_symbol(
            "stable.tasks",
            "crawl_production_sources_window_task",
        )
        selection = SimpleNamespace(
            selected=[
                SimpleNamespace(
                    source=source,
                    reason="never_run",
                )
            ],
            skipped=[],
        )
        with mock.patch(
            "stable.tasks.select_production_sources",
            return_value=selection,
        ), mock.patch(
            "stable.tasks.dispatch_task",
            return_value=SimpleNamespace(id="round2-window-dispatch"),
        ) as dispatch_spy:
            result = scheduler_task.run(
                now_iso="2026-07-19T00:17:00+00:00",
            )

        self.assertEqual(result["triggered_source_ids"], [source.id])
        dispatch_spy.assert_called_once()
        dispatched_args = dispatch_spy.call_args.args
        self.assertIs(
            dispatched_args[0],
            scheduled_task,
            "production-window scheduler 必须复用内部 scheduled policy，不能调用 public direct task",
        )
        self.assertIsNot(dispatched_args[0], public_task)
        window = ProductionWindow.objects.get(
            kind=ProductionWindowKind.CRAWL,
            source=source,
        )
        self.assertEqual(
            dispatched_args,
            (scheduled_task, source.id, window.id),
            "production window 必须把已 claim 的精确 window_id 交给 scheduled task",
        )
        self.assertEqual(window.status, ProductionWindowStatus.RUNNING)
        self.assertEqual(window.reason_summary, "dispatched")

    @override_settings(
        NEWS_SOURCE_PERMISSION_PREFLIGHT_ENFORCEMENT_ENABLED=False,
    )
    def test_explicit_scheduled_window_binding_is_validated_before_side_effects(
        self,
    ):
        source = _make_source(
            adapter_key="sporting_life",
            source_site=SourceSite.SPORTING_LIFE,
            racing_region=RacingRegion.UNITED_KINGDOM,
            enabled=True,
            production_approved=True,
        )
        other_source = _make_source(
            adapter_key="sky_sports_racing",
            source_site=SourceSite.SKY_SPORTS_RACING,
            racing_region=RacingRegion.UNITED_KINGDOM,
            enabled=True,
            production_approved=True,
        )
        start = FIXED_CRAWLED_AT.replace(minute=0)
        wrong_source_window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=other_source.racing_region,
            source=other_source,
            scope_key="round2:invalid-binding-source",
            window_start=start,
            window_end=start + timedelta(minutes=15),
            status=ProductionWindowStatus.RUNNING,
            reason_summary="wrong-source-sentinel",
            result_payload={"sentinel": "wrong-source"},
        )
        wrong_kind_window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.PUBLISH,
            mode=ProductionWindowMode.DAILY,
            racing_region=source.racing_region,
            source=source,
            scope_key="round2:invalid-binding-kind",
            window_start=start + timedelta(minutes=15),
            window_end=start + timedelta(minutes=30),
            status=ProductionWindowStatus.RUNNING,
            reason_summary="wrong-kind-sentinel",
            result_payload={"sentinel": "wrong-kind"},
        )
        non_running_window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=source.racing_region,
            source=source,
            scope_key="round2:invalid-binding-status",
            window_start=start + timedelta(minutes=30),
            window_end=start + timedelta(minutes=45),
            status=ProductionWindowStatus.PENDING,
            reason_summary="non-running-sentinel",
            result_payload={"sentinel": "non-running"},
        )
        invalid_cases = (
            ("missing", max(ProductionWindow.objects.values_list("id", flat=True)) + 999),
            ("wrong_source", wrong_source_window.id),
            ("wrong_kind", wrong_kind_window.id),
            ("non_running", non_running_window.id),
        )
        scheduled_task = self.require_symbol(
            "stable.tasks",
            "crawl_scheduled_news_source_task",
        )
        window_fields = (
            "id",
            "source_id",
            "kind",
            "status",
            "reason_summary",
            "result_payload",
            "last_error",
            "finished_at",
            "attempt_count",
        )
        windows_before = list(
            ProductionWindow.objects.order_by("id").values(*window_fields)
        )
        source_health_fields = (
            "id",
            "last_crawl_at",
            "last_crawl_status",
            "last_crawl_message",
            "last_error_category",
            "failure_streak",
            "success_streak",
            "backoff_until",
        )
        source_health_before = list(
            NewsSource.objects.order_by("id").values(*source_health_fields)
        )

        with mock.patch(
            "stable.tasks.sync_builtin_sources",
        ) as sync_spy, mock.patch(
            "stable.tasks._log_start",
        ) as log_spy, mock.patch(
            "stable.tasks._crawl_international_source_core",
        ) as crawl_core_spy, mock.patch(
            "stable.tasks.record_source_crawl_result",
        ) as health_spy, mock.patch(
            "stable.tasks._finish_crawl_window",
        ) as finish_window_spy:
            for label, window_id in invalid_cases:
                with self.subTest(case=label):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "^invalid_scheduled_crawl_window$",
                    ):
                        scheduled_task.run(source.id, window_id)

        sync_spy.assert_not_called()
        log_spy.assert_not_called()
        crawl_core_spy.assert_not_called()
        health_spy.assert_not_called()
        finish_window_spy.assert_not_called()
        self.assertEqual(CrawlJob.objects.count(), 0)
        self.assertEqual(
            list(ProductionWindow.objects.order_by("id").values(*window_fields)),
            windows_before,
        )
        self.assertEqual(
            list(
                NewsSource.objects.order_by("id").values(*source_health_fields)
            ),
            source_health_before,
        )

    @override_settings(
        NEWS_SOURCE_PERMISSION_PREFLIGHT_ENFORCEMENT_ENABLED=False,
    )
    def test_scheduled_success_closes_explicit_window_with_source_summary(self):
        source = _make_source(
            adapter_key="sporting_life",
            source_site=SourceSite.SPORTING_LIFE,
            racing_region=RacingRegion.UNITED_KINGDOM,
            enabled=True,
            production_approved=True,
        )
        target_start = FIXED_CRAWLED_AT.replace(minute=0)
        target_window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=source.racing_region,
            source=source,
            scope_key="round2:scheduled-success-target",
            window_start=target_start,
            window_end=target_start + timedelta(minutes=15),
            status=ProductionWindowStatus.RUNNING,
        )
        decoy_window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=source.racing_region,
            source=source,
            scope_key="round2:scheduled-success-decoy",
            window_start=target_start + timedelta(minutes=15),
            window_end=target_start + timedelta(minutes=30),
            status=ProductionWindowStatus.RUNNING,
        )
        expected_summary = {
            "candidate_date_within_one_day": 1,
            "historical_date_outside_one_day": 0,
            "freshness_unresolved": 0,
        }
        result = {
            "new_count": 1,
            "seen_count": 0,
            "crawl_job_id": 321,
            "ranked_revival_results": [],
            "source_summary": expected_summary,
        }
        scheduled_task = self.require_symbol(
            "stable.tasks",
            "crawl_scheduled_news_source_task",
        )
        with mock.patch(
            "stable.tasks._crawl_international_source_core",
            return_value=result,
        ):
            try:
                actual = scheduled_task.run(source.id, target_window.id)
            except TypeError as exc:
                self.fail(
                    "F1: crawl_scheduled_news_source_task 必须显式接受 window_id，"
                    f"当前调用失败：{exc}"
                )

        self.assertEqual(actual, result)
        target_window.refresh_from_db()
        decoy_window.refresh_from_db()
        self.assertEqual(target_window.status, ProductionWindowStatus.SUCCEEDED)
        self.assertEqual(
            target_window.result_payload.get("source_summary"),
            expected_summary,
        )
        self.assertEqual(decoy_window.status, ProductionWindowStatus.RUNNING)

    @override_settings(
        NEWS_SOURCE_PERMISSION_PREFLIGHT_ENFORCEMENT_ENABLED=False,
    )
    def test_scheduled_failure_closes_explicit_window_with_error_summary(self):
        source = _make_source(
            adapter_key="sporting_life",
            source_site=SourceSite.SPORTING_LIFE,
            racing_region=RacingRegion.UNITED_KINGDOM,
            enabled=True,
            production_approved=True,
        )
        start = FIXED_CRAWLED_AT.replace(minute=0)
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=source.racing_region,
            source=source,
            scope_key="round2:scheduled-failure",
            window_start=start,
            window_end=start + timedelta(minutes=15),
            status=ProductionWindowStatus.RUNNING,
        )
        expected_summary = {
            "candidate_date_within_one_day": 0,
            "historical_date_outside_one_day": 0,
            "freshness_unresolved": 2,
        }
        failure = RuntimeError("all_candidates_unresolved")
        failure.error_category = "all_candidates_unresolved"
        failure.source_summary = expected_summary
        scheduled_task = self.require_symbol(
            "stable.tasks",
            "crawl_scheduled_news_source_task",
        )
        try:
            with mock.patch(
                "stable.tasks._crawl_international_source_core",
                side_effect=failure,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "all_candidates_unresolved",
                ):
                    scheduled_task.run(source.id, window.id)
        except TypeError as exc:
            self.fail(
                "F1: scheduled failure path 必须显式接受 window_id，"
                f"当前调用失败：{exc}"
            )

        window.refresh_from_db()
        self.assertEqual(window.status, ProductionWindowStatus.FAILED)
        self.assertEqual(
            window.result_payload.get("error_category"),
            "all_candidates_unresolved",
        )
        self.assertEqual(
            window.result_payload.get("source_summary"),
            expected_summary,
        )

    @override_settings(
        NEWS_SOURCE_PERMISSION_PREFLIGHT_ENFORCEMENT_ENABLED=False,
    )
    def test_flag_off_tdn_scheduled_policy_keeps_public_publish_blocked(self):
        source = _make_source(
            adapter_key="round2_flag_off_tdn",
            source_site=SourceSite.TDN,
            racing_region=RacingRegion.UNITED_STATES,
            enabled=True,
            production_approved=True,
        )
        start = FIXED_CRAWLED_AT.replace(minute=0)
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=source.racing_region,
            source=source,
            scope_key="round2:flag-off-tdn",
            window_start=start,
            window_end=start + timedelta(minutes=15),
            status=ProductionWindowStatus.RUNNING,
        )
        scheduled_result = {
            "new_count": 0,
            "seen_count": 0,
            "crawl_job_id": None,
            "ranked_revival_results": [],
            "source_summary": {"permission_reason": "scheduled_flag_off_compat"},
        }
        scheduled_task = self.require_symbol(
            "stable.tasks",
            "crawl_scheduled_news_source_task",
        )
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {source.adapter_key: TDNAdapter},
        ), mock.patch(
            "stable.tasks._crawl_international_source_core",
            return_value=scheduled_result,
        ) as scheduled_core:
            try:
                scheduled_task.run(source.id, window.id)
            except TypeError as exc:
                self.fail(
                    "F1: flag-off TDN scheduled policy 必须接受精确 window_id，"
                    f"当前调用失败：{exc}"
                )

        self.assertIs(
            scheduled_core.call_args.kwargs.get("permission_preflight_enforced"),
            False,
        )
        window.refresh_from_db()
        self.assertEqual(window.status, ProductionWindowStatus.SUCCEEDED)
        permission = self.require_symbol(
            "stable.services.source_permissions",
            "resolve_source_permission",
        )(TDNAdapter())
        self.assertEqual(_field(permission, "status"), "accepted")
        self.assertIs(
            _field(_field(permission, "record"), "public_publish_allowed"),
            False,
        )


class _UnknownBudgetUnsupportedAdapter(JCSANewsAdapter):
    supports_research_request_budget = False
    fetch_listing_calls = 0

    def fetch_listing(self, mode, page):
        del mode, page
        type(self).fetch_listing_calls += 1
        raise AssertionError("不支持 budget hook 的 unknown 来源不得联网")


class IsolationAuditTests(Round2ContractTestCase):
    def test_unknown_unsupported_probe_has_zero_business_writes(self):
        permissions = importlib.import_module(
            "stable.services.source_permissions"
        )
        unknown_record = permissions.SourcePermissionRecord(
            canonical_source_site=SourceSite.JCSA_NEWS,
            technical_access="unknown",
            usage_scope="internal_only",
            public_publish_allowed=False,
            terms_risk="fixture unknown technical status",
            allowed_hosts=("jcsa.sa", "www.jcsa.sa"),
            evidence_url="https://jcsa.sa/en/news/",
            reviewed_at="2026-07-20",
        )
        before = {
            "sources": NewsSource.objects.count(),
            "jobs": CrawlJob.objects.count(),
            "articles": NewsArticle.objects.count(),
            "snapshots": NewsSnapshot.objects.count(),
            "windows": ProductionWindow.objects.count(),
            "translations": TranslationRun.objects.count(),
        }
        _UnknownBudgetUnsupportedAdapter.fetch_listing_calls = 0
        stdout = io.StringIO()
        with mock.patch.dict(
            "stable.management.commands.probe_international_news_sources.INTERNATIONAL_ADAPTERS",
            {"jcsa_news": _UnknownBudgetUnsupportedAdapter},
        ), mock.patch.dict(
            permissions.SOURCE_PERMISSION_REGISTRY,
            {SourceSite.JCSA_NEWS: unknown_record},
        ), mock.patch(
            "stable.tasks._auto_translate_article_after_ingest",
        ) as translate_spy:
            try:
                call_command(
                    "probe_international_news_sources",
                    source=["jcsa_news"],
                    limit=1,
                    json=True,
                    research_mode=True,
                    stdout=stdout,
                )
            except TypeError as exc:
                if "research_mode" in str(exc):
                    self.fail(
                        "目标能力尚未实现：unknown probe 缺少显式 research_mode"
                    )
                raise

        payload = json.loads(stdout.getvalue())[0]
        self.assertEqual(
            payload.get("deferred_reason"),
            "research_budget_unsupported",
        )
        self.assertEqual(payload.get("request_count"), 0)
        self.assertEqual(_UnknownBudgetUnsupportedAdapter.fetch_listing_calls, 0)
        translate_spy.assert_not_called()
        after = {
            "sources": NewsSource.objects.count(),
            "jobs": CrawlJob.objects.count(),
            "articles": NewsArticle.objects.count(),
            "snapshots": NewsSnapshot.objects.count(),
            "windows": ProductionWindow.objects.count(),
            "translations": TranslationRun.objects.count(),
        }
        self.assertEqual(after, before)

    @override_settings(
        NEWS_SOURCE_PERMISSION_PREFLIGHT_ENFORCEMENT_ENABLED=False,
    )
    def test_new_isolation_blocked_hri_has_zero_body_html_translation_and_legacy_reads(self):
        source = _make_source(
            adapter_key="round2_isolation_hri",
            source_site=SourceSite.HRI_NEWS,
            racing_region=RacingRegion.IRELAND,
            enabled=True,
            production_approved=True,
        )
        legacy_reader = mock.Mock(
            side_effect=AssertionError("旧 TDN 隔离证据不得读取或重新处理"),
        )
        _NeverFetchBlockedHRIAlias.fetch_listing_calls = 0
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {source.adapter_key: _NeverFetchBlockedHRIAlias},
        ), mock.patch(
            "stable.tasks.read_legacy_tdn_evidence",
            create=True,
            new=legacy_reader,
        ):
            with self.assertRaisesRegex(
                Exception,
                "technical_access_blocked",
            ):
                _crawl_international_source(source)

        legacy_reader.assert_not_called()
        self.assertEqual(_NeverFetchBlockedHRIAlias.fetch_listing_calls, 0)
        self.assertEqual(NewsArticle.objects.count(), 0)
        self.assertEqual(
            NewsArticle.objects.exclude(body_ja_raw="").count(),
            0,
        )
        self.assertEqual(
            NewsArticle.objects.exclude(original_content_html="").count(),
            0,
        )
        self.assertEqual(NewsSnapshot.objects.count(), 0)
        self.assertEqual(TranslationRun.objects.count(), 0)
        job = CrawlJob.objects.get(source=source)
        self.assertEqual(job.status, TaskStatus.FAILED)
        self.assertIn("technical_access_blocked", job.error_message)

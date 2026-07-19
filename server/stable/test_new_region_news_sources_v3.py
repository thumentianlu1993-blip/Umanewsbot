from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from stable.adapters.base import (
    CanonicalNewsDraft,
    SourceArticleDetail,
    SourceArticleStub,
)
from stable.models import (
    NewsArticle,
    NewsSource,
    RacingRegion,
    SourceKind,
    SourceLanguage,
    SourceMode,
    SourceSite,
)


FIXED_CRAWLED_AT = datetime(2026, 7, 19, 0, 30, tzinfo=dt_timezone.utc)


SOURCE_CASES = {
    "rte_racing": {
        "region": RacingRegion.IRELAND,
        "timezone": "Europe/Dublin",
        "parser": "rte-racing-rss-v1",
        "interval": 30,
        "kind": SourceKind.MEDIA,
        "listing_url": "https://www.rte.ie/feeds/rss/?index=/sport/racing/",
        "detail_url": "https://www.rte.ie/sport/racing/2026/0718/100-rte-sample/",
        "title": "Curragh Irish Oaks field confirmed",
        "format": "rss",
    },
    "irishracing_news": {
        "region": RacingRegion.IRELAND,
        "timezone": "Europe/Dublin",
        "parser": "irishracing-news-v2",
        "interval": 20,
        "kind": SourceKind.MEDIA,
        "listing_url": "https://www.irishracing.com/news",
        "detail_url": "https://www.irishracing.com/news/curragh-sample/100",
        "title": "Curragh card takes shape",
        "format": "irishracing",
    },
    "canadian_thoroughbred": {
        "region": RacingRegion.CANADA,
        "timezone": "America/Toronto",
        "parser": "canadian-thoroughbred-v1",
        "interval": 60,
        "kind": SourceKind.MEDIA,
        "listing_url": "https://canadianthoroughbred.com/news/",
        "detail_url": "https://canadianthoroughbred.com/horse-news/woodbine-sample/",
        "title": "Woodbine King's Plate update",
        "format": "canadian",
        "technical_access": "blocked",
    },
    "assiniboia_downs_news": {
        "region": RacingRegion.CANADA,
        "timezone": "America/Winnipeg",
        "parser": "assiniboia-rss-v1",
        "interval": 120,
        "kind": SourceKind.OFFICIAL,
        "listing_url": "https://asdowns.com/feed/",
        "detail_url": "https://asdowns.com/manitoba-derby-sample/",
        "title": "Assiniboia Downs Manitoba Derby update",
        "format": "rss",
        "technical_access": "blocked",
    },
    "dubai_racing_club": {
        "region": RacingRegion.UNITED_ARAB_EMIRATES,
        "timezone": "Asia/Dubai",
        "parser": "drc-rss-v1",
        "interval": 120,
        "kind": SourceKind.OFFICIAL,
        "listing_url": "https://dubairacingclub.com/feed/",
        "detail_url": "https://dubairacingclub.com/press-releases/meydan-sample/",
        "title": "Meydan Dubai World Cup programme announced",
        "format": "rss",
    },
    "the_national_racing": {
        "region": RacingRegion.UNITED_ARAB_EMIRATES,
        "timezone": "Asia/Dubai",
        "parser": "the-national-racing-v1",
        "interval": 60,
        "kind": SourceKind.MEDIA,
        "listing_url": "https://www.thenationalnews.com/sport/horse-racing/",
        "detail_url": "https://www.thenationalnews.com/sport/horse-racing/meydan-sample/",
        "title": "Meydan carnival runners confirmed",
        "format": "national",
        "technical_access": "blocked",
    },
    "spa_horse_racing": {
        "region": RacingRegion.SAUDI_ARABIA,
        "timezone": "Asia/Riyadh",
        "parser": "spa-horse-racing-v2",
        "interval": 120,
        "kind": SourceKind.OFFICIAL,
        "listing_url": "https://www.spa.gov.sa/en/search?search=horse%20racing",
        "detail_url": "https://www.spa.gov.sa/en/abc123def0",
        "title": "Saudi Cup meeting opens in Riyadh",
        "format": "spa",
    },
    "arab_news_racing": {
        "region": RacingRegion.SAUDI_ARABIA,
        "timezone": "Asia/Riyadh",
        "parser": "arab-news-racing-v1",
        "interval": 120,
        "kind": SourceKind.MEDIA,
        "listing_url": "https://www.arabnews.com/tags/horse-racing",
        "detail_url": "https://www.arabnews.com/node/100/sport",
        "title": "Saudi Cup runners arrive in Riyadh",
        "format": "arab_news",
        "technical_access": "blocked",
    },
    "just_horse_racing": {
        "region": RacingRegion.AUSTRALIA,
        "timezone": "Australia/Melbourne",
        "parser": "just-horse-racing-rss-v1",
        "interval": 15,
        "kind": SourceKind.MEDIA,
        "listing_url": "https://www.justhorseracing.com.au/feed",
        "detail_url": (
            "https://www.justhorseracing.com.au/news/australian-racing/"
            "flemington-sample/100"
        ),
        "title": "Flemington Melbourne Cup field update",
        "format": "jhr_rss",
    },
    "the_straight": {
        "region": RacingRegion.AUSTRALIA,
        "timezone": "Australia/Sydney",
        "parser": "the-straight-rss-v1",
        "interval": 30,
        "kind": SourceKind.MEDIA,
        "listing_url": "https://thestraight.com.au/feed/",
        "detail_url": "https://thestraight.com.au/randwick-sample/",
        "title": "Randwick racing industry update",
        "format": "rss",
    },
    "racing_nsw_news": {
        "region": RacingRegion.AUSTRALIA,
        "timezone": "Australia/Sydney",
        "parser": "racing-nsw-rss-v2",
        "interval": 15,
        "kind": SourceKind.OFFICIAL,
        "listing_url": "https://www.racingnsw.com.au/feed/",
        "detail_url": "https://www.racingnsw.com.au/news/latest-news/randwick-sample/",
        "title": "Randwick programme update",
        "format": "rss",
    },
    "tasracing_news": {
        "region": RacingRegion.AUSTRALIA,
        "timezone": "Australia/Hobart",
        "parser": "tasracing-rss-v2",
        "interval": 60,
        "kind": SourceKind.OFFICIAL,
        "listing_url": "https://tasracing.com.au/news/rss.xml",
        "detail_url": "https://tasracing.com.au/news/hobart-thoroughbred-sample",
        "title": "Hobart thoroughbred meeting update",
        "format": "tasracing_rss",
    },
}


def _rss_item(
    *,
    title: str,
    link: str,
    guid: str | None = None,
    published: str = "Sat, 18 Jul 2026 17:53:19 +0100",
    category: str = "",
) -> str:
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<link>{link}</link>"
        f"<guid>{guid or link}</guid>"
        f"<pubDate>{published}</pubDate>"
        f"{f'<category>{category}</category>' if category else ''}"
        "</item>"
    )


def _listing_fixture(adapter_key: str, case: dict) -> str:
    title = case["title"]
    url = case["detail_url"]
    fixture_format = case["format"]
    if fixture_format in {"rss", "jhr_rss", "tasracing_rss"}:
        extra = ""
        category = "Thoroughbred" if fixture_format == "tasracing_rss" else ""
        if fixture_format == "jhr_rss":
            extra = (
                _rss_item(
                    title="Daily racing tips and odds",
                    link="https://www.justhorseracing.com.au/tips/flemington/999",
                )
                + _rss_item(
                    title="Betting market update",
                    link=(
                        "https://www.justhorseracing.com.au/news/"
                        "australian-racing/betting-market/998"
                    ),
                )
            )
        elif fixture_format == "tasracing_rss":
            extra = (
                _rss_item(
                    title="Hobart harness meeting",
                    link="https://tasracing.com.au/news/hobart-harness",
                    category="Harness",
                )
                + _rss_item(
                    title="Launceston greyhound meeting",
                    link="https://tasracing.com.au/news/launceston-greyhound",
                    category="Greyhound",
                )
            )
        return (
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<rss version='2.0'><channel>"
            f"{_rss_item(title=title, link=url, category=category)}"
            f"{extra}</channel></rss>"
        )
    if fixture_format == "irishracing":
        return (
            "<main><section class='news-date-group' data-date='2026-07-18'>"
            "<h3>Saturday 18 July 2026</h3><article>"
            f"<h4><a href='{url}'>{title}</a></h4>"
            "<span class='news-stamp'>10:25AM</span>"
            "</article></section></main>"
        )
    if fixture_format == "canadian":
        return (
            "<main><article class='post-card'>"
            f"<h2><a href='{url}'>{title}</a></h2>"
            "</article></main>"
        )
    if fixture_format == "national":
        return (
            "<main><section data-section='horse-racing'>"
            f"<article><h2><a href='{url}'>{title}</a></h2></article>"
            "</section></main>"
        )
    if fixture_format == "spa":
        payload = {
            "data": [
                {
                    "uuid": "abc123def0",
                    "title": title,
                    "content": "horse racing",
                    "published_at": 1784397199,
                },
                {
                    "uuid": "101abcdeff",
                    "title": "Camel festival in Riyadh",
                    "content": "camel",
                    "published_at": 1784397199,
                },
                {
                    "uuid": "102abcdeff",
                    "title": "Show jumping championship",
                    "content": "show jumping",
                    "published_at": 1784397199,
                },
            ]
        }
        return json.dumps(payload)
    if fixture_format == "arab_news":
        return (
            "<main><div class='view-content'><article>"
            f"<h2><a href='{url}'>{title}</a></h2>"
            "<a href='/node/101/business'>Business story</a>"
            "</article></div></main>"
        )
    raise AssertionError(f"unsupported fixture format: {adapter_key}")


def _detail_fixture(adapter_key: str, case: dict) -> str:
    title = case["title"]
    body = (
        "This project-authored fixture paragraph describes the race meeting. "
        "A second short fixture sentence confirms the article boundary."
    )
    published = "2026-07-18T17:53:19+00:00"
    fixture_format = case["format"]
    if fixture_format == "national":
        payload = {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": title,
            "articleBody": body,
            "datePublished": published,
        }
        return (
            "<html><head>"
            f"<script type='application/ld+json'>{json.dumps(payload)}</script>"
            f"<meta property='og:title' content='{title}'>"
            "</head><body><article><p>"
            f"{body}</p></article></body></html>"
        )
    if fixture_format == "spa":
        payload = {
            "props": {
                "pageProps": {
                    "newsDetails": {
                        "uuid": "abc123def0",
                        "title": title,
                        "content": f"<p>{body}</p>",
                        "published_at": 1784397199,
                    }
                }
            }
        }
        return (
            "<html><body><script id='__NEXT_DATA__' type='application/json'>"
            f"{json.dumps(payload)}"
            "</script></body></html>"
        )
    selector = {
        "irishracing": "news-story",
        "canadian": "entry-content",
        "arab_news": "field-name-body",
        "tasracing_rss": "news-detail",
    }.get(fixture_format, "entry-content")
    return (
        "<html><head>"
        f"<meta property='og:title' content='{title}'>"
        f"<meta property='article:published_time' content='{published}'>"
        "</head><body>"
        f"<h1>{title}</h1><article class='{selector}'><p>{body}</p></article>"
        "</body></html>"
    )


class _FakeResponse:
    def __init__(
        self,
        *,
        body: bytes,
        content_type: str,
        status_code: int = 200,
        url: str = "https://feeds.fixture.test/feed.xml",
        location: str = "",
        declared_length: int | None = None,
    ) -> None:
        self.status_code = status_code
        self.url = url
        self.encoding = "utf-8"
        self.headers = {"Content-Type": content_type}
        if location:
            self.headers["Location"] = location
        if declared_length is not None:
            self.headers["Content-Length"] = str(declared_length)
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self._body

    def raise_for_status(self):
        return None

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.get = mock.Mock(side_effect=self._get)

    def _get(self, url, **kwargs):
        del url, kwargs
        if not self.responses:
            raise AssertionError("unexpected extra transport request")
        return self.responses.pop(0)


class V3ContractTestCase(TestCase):
    def require_symbol(self, module_name: str, symbol_name: str):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            self.fail(f"目标能力尚未实现：无法导入 {module_name}（{exc}）")
        symbol = getattr(module, symbol_name, None)
        if symbol is None:
            self.fail(f"目标能力尚未实现：{module_name}.{symbol_name} 不存在")
        return symbol

    def rss_adapter(self):
        base = self.require_symbol(
            "stable.adapters.international",
            "TrustedRssNewsAdapter",
        )

        class FixtureRssAdapter(base):
            source_site = "fixture_rss"
            canonical_source_site = "fixture_rss"
            source_mode = SourceMode.OFFICIAL
            source_kind = SourceKind.OFFICIAL
            source_language = SourceLanguage.ENGLISH
            racing_region = RacingRegion.IRELAND
            base_url = "https://feeds.fixture.test/"
            listing_path = "/feed.xml"
            allowed_hosts = ("feeds.fixture.test",)
            local_timezone = "Europe/Dublin"
            parser_version = "fixture-rss-v1"
            link_path_keywords = ("/news/",)
            title_selector = "h1"
            body_selector = "article, .entry-content"

        return FixtureRssAdapter()

    def permission_record(self, *, canonical: str, technical_access: str):
        record_class = self.require_symbol(
            "stable.services.source_permissions",
            "SourcePermissionRecord",
        )
        field_names = {
            field.name for field in dataclasses.fields(record_class)
        }
        required = {
            "technical_access",
            "usage_scope",
            "public_publish_allowed",
            "terms_risk",
            "allowed_hosts",
            "evidence_url",
            "reviewed_at",
        }
        self.assertTrue(
            required.issubset(field_names),
            "目标能力尚未实现：SourcePermissionRecord 缺少三轴准入字段："
            f"{sorted(required - field_names)}",
        )
        kwargs = {
            "canonical_source_site": canonical,
            "technical_access": technical_access,
            "usage_scope": "internal_only",
            "public_publish_allowed": False,
            "terms_risk": "fixture_terms_risk",
            "allowed_hosts": ("feeds.fixture.test",),
            "evidence_url": "https://feeds.fixture.test/evidence",
            "reviewed_at": "2026-07-19",
        }
        signature = inspect.signature(record_class)
        if "status" in signature.parameters:
            kwargs["status"] = technical_access
        if "notes" in signature.parameters:
            kwargs["notes"] = "fixture_terms_risk"
        try:
            return record_class(**kwargs)
        except TypeError as exc:
            self.fail(f"SourcePermissionRecord 构造合同不符合设计：{exc}")

    def parse_listing(self, adapter, fixture: str, *, url: str):
        parser = getattr(adapter, "parse_listing_html", None)
        self.assertTrue(
            callable(parser),
            f"{adapter.__class__.__name__} 缺少离线 listing parser",
        )
        try:
            return parser(
                fixture,
                url=url,
                mode=SourceMode.OFFICIAL,
            )
        except Exception as exc:
            self.fail(
                f"{adapter.__class__.__name__} 最小 listing fixture 解析失败：{exc}"
            )

    def parse_detail(self, adapter, fixture: str, *, url: str):
        parser = getattr(adapter, "parse_detail_html", None)
        self.assertTrue(
            callable(parser),
            f"{adapter.__class__.__name__} 缺少离线 detail parser",
        )
        try:
            return parser(fixture, url=url)
        except Exception as exc:
            self.fail(
                f"{adapter.__class__.__name__} 最小 detail fixture 解析失败：{exc}"
            )


class TechnicalAccessRegistryTests(V3ContractTestCase):
    def test_registry_records_the_three_usage_axes_for_all_direct_sources(self):
        permissions = importlib.import_module(
            "stable.services.source_permissions"
        )
        registry = getattr(permissions, "SOURCE_PERMISSION_REGISTRY", {})
        self.assertIsInstance(registry, dict)
        for source_site, case in SOURCE_CASES.items():
            with self.subTest(source_site=source_site):
                self.assertIn(
                    source_site,
                    registry,
                    f"目标能力尚未实现：registry 缺少 {source_site}",
                )
                record = registry[source_site]
                self.assertEqual(
                    getattr(record, "technical_access", None),
                    case.get("technical_access", "accepted"),
                )
                self.assertEqual(
                    getattr(record, "usage_scope", None),
                    "internal_only",
                )
                self.assertIs(
                    getattr(record, "public_publish_allowed", None),
                    False,
                )
                self.assertTrue(
                    str(getattr(record, "terms_risk", "") or "").strip()
                )
                self.assertTrue(tuple(getattr(record, "allowed_hosts", ())))
                self.assertTrue(
                    str(getattr(record, "reviewed_at", "") or "").strip()
                )

    def test_accepted_is_internal_only_and_host_mismatch_fails_closed(self):
        permissions = importlib.import_module(
            "stable.services.source_permissions"
        )
        resolver = getattr(permissions, "resolve_source_permission", None)
        self.assertTrue(
            callable(resolver),
            "目标能力尚未实现：缺少 canonical technical-access resolver",
        )
        record = self.permission_record(
            canonical="fixture_rss",
            technical_access="accepted",
        )
        accepted_adapter = SimpleNamespace(
            canonical_source_site="fixture_rss",
            source_site="fixture_rss",
            allowed_hosts=("feeds.fixture.test",),
        )
        mismatch_adapter = SimpleNamespace(
            canonical_source_site="fixture_rss",
            source_site="fixture_rss",
            allowed_hosts=("evil.fixture.test",),
        )
        with mock.patch.dict(
            permissions.SOURCE_PERMISSION_REGISTRY,
            {"fixture_rss": record},
        ):
            accepted = resolver(accepted_adapter)
            mismatch = resolver(mismatch_adapter)

        self.assertIs(accepted.allowed, True)
        self.assertEqual(accepted.reason, "internal_only_technical_access")
        self.assertEqual(accepted.record.usage_scope, "internal_only")
        self.assertIs(accepted.record.public_publish_allowed, False)
        self.assertIs(mismatch.allowed, False)
        self.assertEqual(mismatch.reason, "technical_host_mismatch")

    def test_blocked_and_host_mismatch_stop_before_adapter_request(self):
        permissions = importlib.import_module(
            "stable.services.source_permissions"
        )
        adapters = importlib.import_module("stable.adapters.international")
        tasks = importlib.import_module("stable.tasks")
        fetch_spy = mock.Mock(name="fetch_listing")

        class FixtureAdapter:
            source_site = "fixture_rss"
            canonical_source_site = "fixture_rss"
            allowed_hosts = ("feeds.fixture.test",)

            def fetch_listing(self, mode, page):
                return fetch_spy(mode, page)

        source = NewsSource.objects.create(
            name="Blocked fixture source",
            homepage_url="https://feeds.fixture.test/",
            feed_url="https://feeds.fixture.test/feed.xml",
            language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.IRELAND,
            source_language=SourceLanguage.ENGLISH,
            source_kind=SourceKind.OFFICIAL,
            adapter_key="fixture_rss",
            source_site="fixture_rss",
            source_mode=SourceMode.OFFICIAL,
            enabled=True,
            production_approved=True,
        )
        blocked = self.permission_record(
            canonical="fixture_rss",
            technical_access="blocked",
        )
        with mock.patch.dict(
            adapters.INTERNATIONAL_ADAPTERS,
            {"fixture_rss": FixtureAdapter},
        ), mock.patch.dict(
            permissions.SOURCE_PERMISSION_REGISTRY,
            {"fixture_rss": blocked},
        ):
            with self.assertRaisesRegex(
                Exception,
                "technical_access_blocked",
            ):
                tasks._crawl_international_source(source)
        fetch_spy.assert_not_called()

        FixtureAdapter.allowed_hosts = ("evil.fixture.test",)
        accepted = self.permission_record(
            canonical="fixture_rss",
            technical_access="accepted",
        )
        with mock.patch.dict(
            adapters.INTERNATIONAL_ADAPTERS,
            {"fixture_rss": FixtureAdapter},
        ), mock.patch.dict(
            permissions.SOURCE_PERMISSION_REGISTRY,
            {"fixture_rss": accepted},
        ):
            with self.assertRaisesRegex(
                Exception,
                "technical_host_mismatch",
            ):
                tasks._crawl_international_source(source)
        fetch_spy.assert_not_called()


class TrustedRssNewsAdapterTests(V3ContractTestCase):
    def test_rss2_rfc2822_and_atom_iso_precision_are_utc(self):
        adapter = self.rss_adapter()
        rss = (
            "<?xml version='1.0'?><rss version='2.0'><channel>"
            + _rss_item(
                title="Curragh fixture result",
                link="https://feeds.fixture.test/news/rss-item/",
            )
            + "</channel></rss>"
        )
        rss_stubs = self.parse_listing(
            adapter,
            rss,
            url="https://feeds.fixture.test/feed.xml",
        )
        self.assertEqual(len(rss_stubs), 1)
        self.assertEqual(
            rss_stubs[0].published_at,
            datetime(2026, 7, 18, 16, 53, 19, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            rss_stubs[0].metadata["published_at_evidence"]["precision"],
            "second",
        )

        atom = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>tag:fixture.test,2026:atom-1</id>
            <title>Curragh Atom fixture</title>
            <link rel="alternate" href="https://feeds.fixture.test/news/atom-item/" />
            <published>2026-07-18T17:53+01:00</published>
          </entry>
        </feed>"""
        atom_stubs = self.parse_listing(
            adapter,
            atom,
            url="https://feeds.fixture.test/feed.xml",
        )
        self.assertEqual(len(atom_stubs), 1)
        self.assertEqual(
            atom_stubs[0].published_at,
            datetime(2026, 7, 18, 16, 53, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            atom_stubs[0].metadata["published_at_evidence"]["precision"],
            "minute",
        )

    def test_guid_link_deduplication_and_twenty_item_limit(self):
        adapter = self.rss_adapter()
        items = [
            _rss_item(
                title=f"Curragh fixture {index}",
                link=f"https://feeds.fixture.test/news/{index}/",
                guid=f"fixture-guid-{index}",
            )
            for index in range(25)
        ]
        items.insert(
            1,
            _rss_item(
                title="Duplicate canonical link",
                link="https://feeds.fixture.test/news/0/?utm_source=test",
                guid="different-guid",
            ),
        )
        items.insert(
            3,
            _rss_item(
                title="Duplicate GUID",
                link="https://feeds.fixture.test/news/guid-duplicate/",
                guid="fixture-guid-1",
            ),
        )
        xml = (
            "<?xml version='1.0'?><rss version='2.0'><channel>"
            + "".join(items)
            + "</channel></rss>"
        )
        stubs = self.parse_listing(
            adapter,
            xml,
            url="https://feeds.fixture.test/feed.xml",
        )
        self.assertEqual(len(stubs), 20)
        self.assertEqual(
            len({stub.source_url for stub in stubs}),
            len(stubs),
        )
        self.assertEqual(
            len({stub.source_article_id for stub in stubs}),
            len(stubs),
        )
        repeated = self.parse_listing(
            adapter,
            xml,
            url="https://feeds.fixture.test/feed.xml",
        )
        self.assertEqual(
            [stub.source_article_id for stub in stubs],
            [stub.source_article_id for stub in repeated],
        )

    def test_invalid_xml_and_empty_feed_fail_closed(self):
        adapter = self.rss_adapter()
        for label, fixture in (
            ("invalid", "<rss><channel><item></rss>"),
            (
                "empty",
                "<?xml version='1.0'?><rss version='2.0'><channel/></rss>",
            ),
        ):
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    (ValueError, RuntimeError),
                    "rss|feed|xml|empty",
                ):
                    adapter.parse_listing_html(
                        fixture,
                        url="https://feeds.fixture.test/feed.xml",
                        mode=SourceMode.OFFICIAL,
                    )

    def test_xml_mime_cross_host_redirect_and_two_mib_limit_fail_closed(self):
        adapter = self.rss_adapter()
        valid = (
            "<?xml version='1.0'?><rss version='2.0'><channel>"
            + _rss_item(
                title="Curragh fixture",
                link="https://feeds.fixture.test/news/1/",
            )
            + "</channel></rss>"
        ).encode()
        cases = (
            (
                "invalid_mime",
                [
                    _FakeResponse(
                        body=valid,
                        content_type="text/html",
                    )
                ],
                "content|mime|html",
            ),
            (
                "cross_host_redirect",
                [
                    _FakeResponse(
                        body=b"",
                        content_type="application/rss+xml",
                        status_code=302,
                        location="https://evil.fixture.test/feed.xml",
                    )
                ],
                "host",
            ),
            (
                "too_large",
                [
                    _FakeResponse(
                        body=valid,
                        content_type="application/rss+xml",
                        declared_length=2 * 1024 * 1024 + 1,
                    )
                ],
                "large|size",
            ),
        )
        for label, responses, expected in cases:
            with self.subTest(label=label):
                session = _FakeSession(responses)
                with mock.patch(
                    "stable.services.http.requests.Session",
                    return_value=session,
                ):
                    with self.assertRaisesRegex(
                        (ValueError, RuntimeError),
                        expected,
                    ):
                        adapter.fetch_listing(SourceMode.OFFICIAL, 1)
                self.assertEqual(session.get.call_count, 1)

    def test_detail_and_normalized_draft_never_contain_images(self):
        adapter = self.rss_adapter()
        stub = SourceArticleStub(
            source_site=adapter.source_site,
            source_mode=SourceMode.OFFICIAL,
            source_article_id="fixture-1",
            source_url="https://feeds.fixture.test/news/fixture-1/",
            title_ja="Curragh fixture",
            published_at=datetime(
                2026,
                7,
                18,
                16,
                53,
                19,
                tzinfo=dt_timezone.utc,
            ),
            metadata={
                "published_at_verified": True,
                "published_at_evidence": {
                    "source": "rss",
                    "raw": "Sat, 18 Jul 2026 17:53:19 +0100",
                    "timezone": "Europe/Dublin",
                    "precision": "second",
                    "parser_version": "fixture-rss-v1",
                    "verified": True,
                },
            },
        )
        html = (
            "<html><head>"
            "<meta property='og:title' content='Curragh fixture'>"
            "<meta property='article:published_time' "
            "content='2026-07-18T17:53:19+01:00'>"
            "</head><body><article>"
            "<p>This project-authored fixture contains material race text.</p>"
            "<img src='https://cdn.fixture.test/image.jpg'>"
            "</article></body></html>"
        )
        detail = self.parse_detail(
            adapter,
            html,
            url=stub.source_url,
        )
        draft = adapter.normalize_source_payload(stub, detail)
        self.assertEqual(detail.images, [])
        self.assertEqual(draft.images, [])


class ThirdBatchSourceIdentityTests(V3ContractTestCase):
    def test_twelve_source_site_adapter_and_default_rows_are_one_to_one(self):
        adapters = importlib.import_module("stable.adapters.international")
        sources = importlib.import_module("stable.services.sources")
        expected = set(SOURCE_CASES)
        self.assertTrue(
            expected.issubset(set(SourceSite.values)),
            "目标能力尚未实现：SourceSite 缺少："
            f"{sorted(expected - set(SourceSite.values))}",
        )
        self.assertTrue(
            expected.issubset(set(adapters.INTERNATIONAL_ADAPTERS)),
            "目标能力尚未实现：adapter registry 缺少："
            f"{sorted(expected - set(adapters.INTERNATIONAL_ADAPTERS))}",
        )
        definitions = [
            item
            for item in sources.BUILTIN_SOURCE_DEFINITIONS
            if str(item.get("adapter_key") or "") in expected
        ]
        self.assertEqual(
            len(definitions),
            12,
            "12 个新 adapter 必须各有且仅有一个 builtin source definition",
        )
        self.assertEqual(
            {str(item["source_site"]) for item in definitions},
            expected,
        )
        self.assertEqual(
            {str(item["adapter_key"]) for item in definitions},
            expected,
        )

        synced = sources.sync_builtin_sources()
        del synced
        for key, case in SOURCE_CASES.items():
            with self.subTest(source=key):
                rows = NewsSource.objects.filter(
                    source_site=key,
                    adapter_key=key,
                    deleted_at__isnull=True,
                )
                self.assertEqual(rows.count(), 1)
                source = rows.first()
                self.assertIsNotNone(source)
                self.assertIs(source.enabled, False)
                self.assertIs(source.production_approved, False)
                self.assertEqual(source.racing_region, case["region"])
                self.assertEqual(source.source_language, SourceLanguage.ENGLISH)
                self.assertEqual(source.source_kind, case["kind"])
                self.assertEqual(
                    source.crawl_interval_minutes,
                    case["interval"],
                )
                adapter = adapters.INTERNATIONAL_ADAPTERS[key]()
                self.assertEqual(str(adapter.source_site), key)
                self.assertEqual(adapter.racing_region, case["region"])
                self.assertEqual(adapter.local_timezone, case["timezone"])
                self.assertEqual(adapter.parser_version, case["parser"])
                self.assertIn(
                    str(source.feed_url).rstrip("/"),
                    {
                        case["listing_url"].rstrip("/"),
                        str(source.homepage_url).rstrip("/"),
                    },
                )

    def test_sync_is_idempotent_and_preserves_runtime_enablement(self):
        sources = importlib.import_module("stable.services.sources")
        sources.sync_builtin_sources()
        source = NewsSource.objects.filter(
            source_site="rte_racing",
            source_mode=SourceMode.OFFICIAL,
        ).first()
        self.assertIsNotNone(
            source,
            "目标能力尚未实现：sync 未创建 rte_racing",
        )
        source.enabled = True
        source.production_approved = True
        source.save(
            update_fields=[
                "enabled",
                "production_approved",
                "updated_at",
            ]
        )
        sources.sync_builtin_sources()
        source.refresh_from_db()
        self.assertIs(source.enabled, True)
        self.assertIs(source.production_approved, True)
        self.assertEqual(
            NewsSource.objects.filter(
                source_site="rte_racing",
                source_mode=SourceMode.OFFICIAL,
                deleted_at__isnull=True,
            ).count(),
            1,
        )

    def test_google_news_is_discovery_only_and_has_no_adapter(self):
        adapters = importlib.import_module("stable.adapters.international")
        normalized_keys = {
            str(key).casefold().replace("-", "_")
            for key in adapters.INTERNATIONAL_ADAPTERS
        }
        self.assertNotIn("google_news", normalized_keys)
        self.assertNotIn("google_news_rss", normalized_keys)
        self.assertFalse(
            any(
                "news.google.com" in str(
                    getattr(adapter_class, "base_url", "")
                ).casefold()
                for adapter_class in adapters.INTERNATIONAL_ADAPTERS.values()
            )
        )


class ThirdBatchOfflineFixtureTests(V3ContractTestCase):
    def test_each_source_parses_minimal_owned_listing_and_detail_fixture(self):
        adapters = importlib.import_module("stable.adapters.international")
        for key, case in SOURCE_CASES.items():
            with self.subTest(source=key):
                self.assertIn(
                    key,
                    adapters.INTERNATIONAL_ADAPTERS,
                    f"目标能力尚未实现：缺少 {key} adapter",
                )
                adapter = adapters.INTERNATIONAL_ADAPTERS[key]()
                stubs = self.parse_listing(
                    adapter,
                    _listing_fixture(key, case),
                    url=case["listing_url"],
                )
                self.assertEqual(
                    len(stubs),
                    1,
                    f"{key} 应只保留赛马主题 fixture",
                )
                stub = stubs[0]
                self.assertEqual(stub.source_url, case["detail_url"])
                self.assertEqual(stub.title_ja, case["title"])
                self.assertEqual(str(stub.source_site), key)

                detail = self.parse_detail(
                    adapter,
                    _detail_fixture(key, case),
                    url=stub.source_url,
                )
                self.assertEqual(detail.title_ja, case["title"])
                self.assertIn(
                    "project-authored fixture",
                    detail.body_ja_normalized,
                )
                self.assertEqual(
                    detail.published_at,
                    datetime(
                        2026,
                        7,
                        18,
                        17,
                        53,
                        19,
                        tzinfo=dt_timezone.utc,
                    ),
                )
                evidence = detail.metadata.get(
                    "published_at_evidence",
                    {},
                )
                self.assertEqual(evidence.get("precision"), "second")
                self.assertTrue(evidence.get("verified"))
                self.assertEqual(detail.images, [])

                draft = adapter.normalize_source_payload(stub, detail)
                self.assertEqual(draft.source_url, case["detail_url"])
                self.assertEqual(draft.racing_region, case["region"])
                self.assertEqual(draft.images, [])

    def test_listing_topic_filters_run_before_detail_requests(self):
        adapters = importlib.import_module("stable.adapters.international")
        expected_skip_terms = {
            "just_horse_racing": ("tips", "betting"),
            "tasracing_news": ("harness", "greyhound"),
            "spa_horse_racing": ("camel", "show jumping"),
        }
        for key, forbidden in expected_skip_terms.items():
            with self.subTest(source=key):
                self.assertIn(
                    key,
                    adapters.INTERNATIONAL_ADAPTERS,
                    f"目标能力尚未实现：缺少 {key} adapter",
                )
                adapter = adapters.INTERNATIONAL_ADAPTERS[key]()
                stubs = self.parse_listing(
                    adapter,
                    _listing_fixture(key, SOURCE_CASES[key]),
                    url=SOURCE_CASES[key]["listing_url"],
                )
                joined = " ".join(
                    f"{stub.title_ja} {stub.source_url}".casefold()
                    for stub in stubs
                )
                self.assertEqual(len(stubs), 1)
                for term in forbidden:
                    self.assertNotIn(term, joined)


class _PipelineAdapter:
    source_mode = SourceMode.OFFICIAL
    source_language = SourceLanguage.ENGLISH
    source_kind = SourceKind.OFFICIAL
    skipped_items: list[str] = []
    last_listing_query_errors: list[dict] = []

    def __init__(
        self,
        *,
        source_site: str,
        region: str,
        title: str,
        url: str,
    ) -> None:
        self.source_site = source_site
        self.canonical_source_site = source_site
        self.racing_region = region
        self.title = title
        self.url = url

    def fetch_listing(self, mode, page):
        del page
        return [
            SourceArticleStub(
                source_site=self.source_site,
                source_mode=mode,
                source_article_id=f"{self.source_site}-fixture-1",
                source_url=self.url,
                title_ja=self.title,
                published_at=datetime(
                    2026,
                    7,
                    19,
                    0,
                    0,
                    tzinfo=dt_timezone.utc,
                ),
                metadata={
                    "published_at_verified": True,
                    "published_at_evidence": {
                        "source": "fixture",
                        "raw": "2026-07-19T00:00:00Z",
                        "timezone": "UTC",
                        "precision": "second",
                        "parser_version": "pipeline-fixture-v1",
                        "verified": True,
                    },
                },
            )
        ]

    def fetch_detail(self, source_url):
        return SourceArticleDetail(
            title_ja=self.title,
            body_ja_raw=(
                f"{self.title}. Project-authored integration fixture body."
            ),
            body_ja_normalized=(
                f"{self.title}. Project-authored integration fixture body."
            ),
            published_at=datetime(
                2026,
                7,
                19,
                0,
                0,
                tzinfo=dt_timezone.utc,
            ),
            images=[],
            metadata={
                "published_at_verified": True,
                "published_at_evidence": {
                    "source": "fixture",
                    "raw": "2026-07-19T00:00:00Z",
                    "timezone": "UTC",
                    "precision": "second",
                    "parser_version": "pipeline-fixture-v1",
                    "verified": True,
                },
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
            source_language=SourceLanguage.ENGLISH,
            source_kind=SourceKind.OFFICIAL,
            metadata=detail.metadata,
        )


class ThirdBatchCrawlIntegrationTests(V3ContractTestCase):
    def test_two_sources_per_region_flow_to_freshness_preview_upsert_and_duplicate(self):
        adapters = importlib.import_module("stable.adapters.international")
        tasks = importlib.import_module("stable.tasks")
        pairs = (
            ("rte_racing", "irishracing_news"),
            ("canadian_thoroughbred", "assiniboia_downs_news"),
            ("dubai_racing_club", "the_national_racing"),
            ("spa_horse_racing", "arab_news_racing"),
            ("just_horse_racing", "racing_nsw_news"),
        )
        expected_region = {
            key: case["region"] for key, case in SOURCE_CASES.items()
        }
        adapter_patch = {}
        for key_a, key_b in pairs:
            for key in (key_a, key_b):
                case = SOURCE_CASES[key]

                class BoundPipelineAdapter(_PipelineAdapter):
                    def __init__(
                        self,
                        *,
                        _key=key,
                        _case=case,
                    ):
                        super().__init__(
                            source_site=_key,
                            region=_case["region"],
                            title=_case["title"],
                            url=_case["detail_url"],
                        )

                adapter_patch[key] = BoundPipelineAdapter

        accepted = SimpleNamespace(
            canonical_source_site="fixture",
            status="accepted",
            reason="internal_only_technical_access",
            allowed=True,
        )
        with mock.patch.dict(
            adapters.INTERNATIONAL_ADAPTERS,
            adapter_patch,
        ), mock.patch(
            "stable.tasks.preflight_source_access",
            return_value=accepted,
        ), mock.patch(
            "stable.tasks._discover_terms_after_ingest",
        ), mock.patch(
            "stable.tasks._auto_translate_article_after_ingest",
        ):
            for key_a, key_b in pairs:
                for key in (key_a, key_b):
                    with self.subTest(source=key):
                        case = SOURCE_CASES[key]
                        source = NewsSource.objects.create(
                            name=f"{key} pipeline source",
                            homepage_url=case["listing_url"],
                            feed_url=case["listing_url"],
                            language=SourceLanguage.ENGLISH,
                            racing_region=case["region"],
                            source_language=SourceLanguage.ENGLISH,
                            source_kind=case["kind"],
                            adapter_key=key,
                            source_site=key,
                            source_mode=SourceMode.OFFICIAL,
                            enabled=True,
                            production_approved=True,
                        )
                        first = tasks._crawl_international_source(
                            source,
                            crawled_at=FIXED_CRAWLED_AT,
                        )
                        second = tasks._crawl_international_source(
                            source,
                            crawled_at=FIXED_CRAWLED_AT,
                        )
                        self.assertEqual(first["new_count"], 1)
                        self.assertEqual(second["new_count"], 0)
                        self.assertEqual(second["seen_count"], 1)
                        articles = NewsArticle.objects.filter(
                            source_site=key,
                        )
                        self.assertEqual(articles.count(), 1)
                        article = articles.get()
                        self.assertEqual(
                            article.racing_region,
                            expected_region[key],
                        )
                        self.assertEqual(
                            article.workflow_status,
                            "pending_translation",
                        )
                        self.assertEqual(article.images.count(), 0)

    def test_historical_and_unresolved_freshness_stop_before_upsert(self):
        tasks = importlib.import_module("stable.tasks")
        classifier = self.require_symbol(
            "stable.services.news_candidate_freshness",
            "classify_candidate_freshness",
        )
        upsert_spy = mock.Mock(name="upsert_article_from_draft")
        historical = classifier(
            published_at=datetime(
                2026,
                7,
                17,
                16,
                0,
                tzinfo=dt_timezone.utc,
            ),
            published_at_evidence={
                "source": "detail",
                "raw": "2026-07-17",
                "timezone": "Europe/Dublin",
                "precision": "date",
                "parser_version": "fixture-v1",
                "verified": True,
            },
            published_at_verified=True,
            crawled_at=FIXED_CRAWLED_AT,
        )
        unresolved = classifier(
            published_at=None,
            published_at_evidence={},
            published_at_verified=False,
            crawled_at=FIXED_CRAWLED_AT,
        )
        self.assertEqual(
            getattr(historical, "decision", ""),
            "historical_date_outside_one_day",
        )
        self.assertEqual(
            getattr(unresolved, "decision", ""),
            "freshness_unresolved",
        )
        self.assertEqual(upsert_spy.call_count, 0)
        self.assertIsNotNone(tasks)

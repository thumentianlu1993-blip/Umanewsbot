from __future__ import annotations

import email.utils
import hashlib
import html as html_lib
import json
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import dateparse, timezone

from stable.models import RacingRegion, SourceKind, SourceLanguage, SourceMode, SourceSite
from stable.services.article_content import ArticleContentCleanResult, clean_international_article_body
from stable.services.http import DEFAULT_HEADERS, get_bounded_html, get_bytes
from stable.services.text import normalize_whitespace

from .base import CanonicalNewsDraft, SourceAdapter, SourceArticleDetail, SourceArticleStub


RANKED_SOURCE_MODES = {SourceMode.ACCESS, SourceMode.ATTENTION}


class SimpleInternationalNewsAdapter(SourceAdapter):
    source_site: SourceSite
    canonical_source_site: SourceSite | None = None
    source_mode = SourceMode.LATEST
    base_url = ""
    listing_path = ""
    racing_region: RacingRegion
    source_language: SourceLanguage
    source_kind = SourceKind.NEWS
    article_selector = (
        "article a[href], .article a[href], .article-card a[href], "
        ".news-item a[href], .news-card a[href], .story-card a[href], "
        ".media-list a[href], .listing a[href], [class*='Article'] a[href], "
        "h1 a[href], h2 a[href], h3 a[href]"
    )
    title_selector = "h1"
    body_selector = "article, .article-body, .entry-content, .content, main"
    date_selector = "time[datetime], time, .date, .published, .timestamp"
    author_selector = ".author, .byline"
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    link_path_keywords: tuple[str, ...] = ("/news", "/article", "/articles", "/press-release", "/press-releases")
    exclude_path_keywords: tuple[str, ...] = ("/author/", "/authors/", "/tag/", "/tags/")
    prefer_meta_title = True
    last_listing_http_status: int | None = None
    last_listing_final_url = ""

    def __init__(self) -> None:
        self.skipped_items: list[str] = []
        self.last_listing_query_errors: list[dict[str, str]] = []

    def fetch_listing(self, mode: SourceMode, page_or_month: str | int) -> list[SourceArticleStub]:
        url = self.listing_url(page_or_month, mode=mode)
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        self.last_listing_http_status = getattr(response, "status_code", None)
        self.last_listing_final_url = getattr(response, "url", url)
        response.raise_for_status()
        response.encoding = "utf-8"
        html = response.text
        return self.parse_listing_html(html, url=url, mode=mode)

    def fetch_detail(self, source_article_id_or_url: str) -> SourceArticleDetail:
        url = source_article_id_or_url
        if not url.startswith(("http://", "https://")):
            url = urljoin(self.base_url, url)
        html = str(get_bytes(url, encoding="utf-8"))
        return self.parse_detail_html(html, url=url)

    def normalize_source_payload(self, stub: SourceArticleStub, detail: SourceArticleDetail) -> CanonicalNewsDraft:
        return CanonicalNewsDraft(
            source_site=self.source_site,
            source_mode=stub.source_mode,
            source_article_id=stub.source_article_id,
            source_url=stub.source_url,
            title_ja=detail.title_ja or stub.title_ja,
            body_ja_raw=detail.body_ja_raw,
            body_ja_normalized=detail.body_ja_normalized,
            published_at=detail.published_at or stub.published_at,
            images=detail.images,
            racing_region=self.racing_region,
            source_language=self.source_language,
            source_kind=self.source_kind,
            original_content_html=detail.original_content_html,
            comment_count=stub.comment_count,
            attention_count=stub.attention_count,
            rank=stub.rank,
            canonical_source_site=self.canonical_source_site,
            metadata={
                **stub.metadata,
                **detail.metadata,
                "source_language": self.source_language,
                "discovered_source_site": self.source_site,
            },
        )

    def listing_url(self, page_or_month: str | int, mode: SourceMode | str | None = None) -> str:
        return urljoin(self.base_url, self.listing_path)

    def parse_listing_html(self, html: str, *, url: str, mode: SourceMode | str | None = None) -> list[SourceArticleStub]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        stubs: list[SourceArticleStub] = []
        resolved_mode = mode or self.source_mode
        for index, anchor in enumerate(soup.select(self.article_selector), start=1):
            href = (anchor.get("href") or "").strip()
            raw_title = anchor.get("title") or anchor.get_text(" ", strip=True)
            title = self._clean_listing_title(raw_title, resolved_mode)
            if not href or not title:
                continue
            article_url = urljoin(url, href)
            if article_url in seen or not self._topic_allowed(title, article_url):
                continue
            seen.add(article_url)
            stubs.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=resolved_mode,
                    source_article_id=self._article_id(article_url),
                    source_url=article_url,
                    title_ja=normalize_whitespace(title),
                    published_at=timezone.now(),
                    rank=self._listing_rank(raw_title, index, resolved_mode),
                    metadata={"listing_url": url},
                )
            )
            if len(stubs) >= 20:
                break
        return stubs

    def parse_detail_html(self, html: str, *, url: str) -> SourceArticleDetail:
        soup = BeautifulSoup(html, "lxml")
        title_meta = soup.select_one("meta[property='og:title'], meta[name='twitter:title']")
        title_node = soup.select_one(self.title_selector) or soup.select_one("title")
        body_node, matched_body_selector = self._select_body_node(soup)
        date_node = soup.select_one(self.date_selector)
        author_node = soup.select_one(self.author_selector)
        meta_title = title_meta.get("content", "").strip() if title_meta and title_meta.get("content") else ""
        node_title = title_node.get_text(" ", strip=True) if title_node else ""
        title = normalize_whitespace(meta_title if self.prefer_meta_title and meta_title else node_title or meta_title)
        if body_node is None:
            clean_result = ArticleContentCleanResult(text="", status="selector_not_found", removed_rules={})
        else:
            clean_result = clean_international_article_body(body_node, source_site=self.source_site)
        body_raw = clean_result.text
        body_normalized = normalize_whitespace(body_raw)
        published_at = self._parse_published_at(date_node)
        return SourceArticleDetail(
            title_ja=title,
            body_ja_raw=body_raw,
            body_ja_normalized=body_normalized,
            published_at=published_at,
            images=[],
            metadata={
                "author": author_node.get_text(" ", strip=True) if author_node else "",
                "source_url": url,
                "region": self.racing_region,
                "source_language": self.source_language,
                "body_parse_status": clean_result.status,
                "body_selector": matched_body_selector,
                "body_cleaning": clean_result.metadata(),
            },
            original_content_html=html,
        )

    def _select_body_node(self, soup: BeautifulSoup):
        for selector in (part.strip() for part in self.body_selector.split(",")):
            if not selector:
                continue
            node = soup.select_one(selector)
            if node is not None:
                return node, selector
        return None, ""

    def _parse_published_at(self, date_node) -> datetime | None:
        if date_node is None:
            return None
        raw = (date_node.get("datetime") or date_node.get_text(" ", strip=True) or "").strip()
        parsed = dateparse.parse_datetime(raw)
        if parsed is None:
            parsed_date = dateparse.parse_date(raw)
            if parsed_date is not None:
                parsed = datetime.combine(parsed_date, datetime.min.time())
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed

    def _article_id(self, url: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        slug = urlsplit(url).path.rstrip("/").split("/")[-1].strip()
        if not slug:
            return digest
        return f"{slug[:100]}-{digest}"

    def _clean_listing_title(self, title: str, mode: SourceMode | str | None) -> str:
        cleaned = normalize_whitespace(title)
        if mode in RANKED_SOURCE_MODES:
            cleaned = re.sub(r"^\d+\s+", "", cleaned)
        return cleaned

    def _listing_rank(self, title: str, index: int, mode: SourceMode | str | None) -> int | None:
        if mode not in RANKED_SOURCE_MODES:
            return None
        match = re.match(r"^\s*(\d+)\b", title)
        if match:
            return int(match.group(1))
        return index

    def _topic_allowed(self, title: str, url: str) -> bool:
        parsed = urlsplit(url)
        base_host = urlsplit(self.base_url).netloc
        if parsed.netloc and base_host and parsed.netloc != base_host:
            return False
        path = parsed.path.casefold()
        if self.link_path_keywords and not any(keyword.casefold() in path for keyword in self.link_path_keywords):
            return False
        if self.exclude_path_keywords and any(keyword.casefold() in path for keyword in self.exclude_path_keywords):
            return False
        text = f"{title} {url}".casefold()
        if self.include_keywords and not any(keyword.casefold() in text for keyword in self.include_keywords):
            return False
        if self.exclude_keywords and any(keyword.casefold() in text for keyword in self.exclude_keywords):
            return False
        return True


class SponichiAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.SPONICHI
    base_url = "https://www.sponichi.co.jp/"
    listing_path = "/gamble/"
    racing_region = RacingRegion.JAPAN
    source_language = SourceLanguage.JAPANESE
    include_keywords = ("競馬", "keiba", "horse", "s00004", "b00004")
    exclude_keywords = ("ボート", "boatrace", "競輪", "オートレース")
    link_path_keywords = ("/gamble/news/", "/news/")
    article_selector = (
        ".tab-gamble a[href], .tab-contents a[href], li.cateGamble a[href], "
        "article a[href], h1 a[href], h2 a[href], h3 a[href]"
    )
    title_selector = "[data-component='article-header'] h1"
    body_selector = "[data-component='article-body']"
    prefer_meta_title = False

    def listing_url(self, page_or_month: str | int, mode: SourceMode | str | None = None) -> str:
        if mode == SourceMode.ACCESS:
            return urljoin(self.base_url, "/gamble/ranking/")
        return super().listing_url(page_or_month, mode=mode)


class HKJCRacingNewsAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.HKJC_NEWS
    base_url = "https://racingnews.hkjc.com/"
    listing_path = "/english/"
    racing_region = RacingRegion.HONG_KONG
    source_language = SourceLanguage.ENGLISH
    link_path_keywords = ("/english/news", "/english/")
    title_selector = ".horses-racing-news-title"
    body_selector = ".horses-racing-news-content"
    prefer_meta_title = False
    banner_api_url = "https://consvc.hkjc.com/bannerad/api/getbannerlist"
    banner_api_key = "{05AEECC4-CCED-4931-B91D-AF82FACE6EE0}"

    def fetch_listing(self, mode: SourceMode, page_or_month: str | int) -> list[SourceArticleStub]:
        response = requests.post(
            self.banner_api_url,
            headers={
                "Content-Type": "application/json",
                "sc_apikey": self.banner_api_key,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
                ),
            },
            json={"ZoneCode": "EWRNTN", "Language": "en-us"},
            timeout=15,
        )
        response.raise_for_status()
        payload = json.loads(response.content.decode("utf-8-sig"))
        banners = (payload.get("data") or {}).get("BannerADs") or []
        stubs: list[SourceArticleStub] = []
        seen: set[str] = set()
        resolved_mode = mode or self.source_mode
        for banner in banners:
            raw_url = (banner.get("Url") or "").strip()
            title = normalize_whitespace(banner.get("Title") or banner.get("BannerName") or "")
            if not raw_url or not title:
                continue
            article_url = raw_url.split("?", 1)[0]
            if article_url in seen or not self._topic_allowed(title, article_url):
                continue
            seen.add(article_url)
            stubs.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=resolved_mode,
                    source_article_id=self._article_id(article_url),
                    source_url=article_url,
                    title_ja=title,
                    published_at=timezone.now(),
                    metadata={"listing_url": self.listing_url(page_or_month), "description": banner.get("Description") or ""},
                )
            )
            if len(stubs) >= 20:
                break
        return stubs


class SCMPRacingAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.SCMP_RACING
    base_url = "https://www.scmp.com/"
    listing_path = "/sport/racing"
    racing_region = RacingRegion.HONG_KONG
    source_language = SourceLanguage.ENGLISH
    link_path_keywords = ("/sport/racing",)


class SportingLifeAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.SPORTING_LIFE
    base_url = "https://www.sportinglife.com/"
    listing_path = "/racing/news"
    racing_region = RacingRegion.UNITED_KINGDOM
    source_language = SourceLanguage.ENGLISH
    link_path_keywords = ("/racing/news",)
    body_selector = "[class*='Article__ArticleBody'], article .article-body, article, main"


class BHAAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.BHA
    source_mode = SourceMode.OFFICIAL
    base_url = "https://www.britishhorseracing.com/"
    listing_path = "/press-releases/"
    racing_region = RacingRegion.UNITED_KINGDOM
    source_language = SourceLanguage.ENGLISH
    source_kind = SourceKind.OFFICIAL
    link_path_keywords = ("/press_releases/", "/press-releases", "/news-and-media")
    title_selector = ".single-column .header-wrap__title, main .header-wrap__title"
    body_selector = ".article-body, main"
    prefer_meta_title = False


class SkySportsRacingAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.SKY_SPORTS_RACING
    base_url = "https://www.skysports.com/"
    listing_path = "/racing/news"
    racing_region = RacingRegion.UNITED_KINGDOM
    source_language = SourceLanguage.ENGLISH
    link_path_keywords = ("/racing/news/",)
    title_selector = "h1"
    body_selector = "article, main"

    def listing_url(self, page_or_month: str | int, mode: SourceMode | str | None = None) -> str:
        if mode == SourceMode.ACCESS:
            return urljoin(self.base_url, "/racing")
        return super().listing_url(page_or_month, mode=mode)

    def parse_listing_html(self, html: str, *, url: str, mode: SourceMode | str | None = None) -> list[SourceArticleStub]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        stubs: list[SourceArticleStub] = []
        resolved_mode = mode or self.source_mode
        candidates = soup.select("a[href*='/racing/news/']")
        for index, anchor in enumerate(candidates, start=1):
            href = (anchor.get("href") or "").strip()
            title = normalize_whitespace(anchor.get("title") or anchor.get_text(" ", strip=True) or self._title_from_url(href))
            if not href or not title:
                continue
            article_url = urljoin(url, href)
            if article_url in seen or not self._topic_allowed(title, article_url):
                continue
            seen.add(article_url)
            stubs.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=resolved_mode,
                    source_article_id=self._article_id(article_url),
                    source_url=article_url,
                    title_ja=title,
                    published_at=timezone.now(),
                    rank=self._listing_rank(title, index, resolved_mode),
                    metadata={"listing_url": url},
                )
            )
            if len(stubs) >= 20:
                break
        return stubs

    def _title_from_url(self, href: str) -> str:
        slug = urlsplit(href).path.rstrip("/").split("/")[-1]
        return slug.replace("-", " ").strip().title()


class FranceGalopEnglishNewsAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.FRANCE_GALOP_NEWS
    source_mode = SourceMode.OFFICIAL
    base_url = "https://www.france-galop.com/"
    listing_path = "/en/news"
    racing_region = RacingRegion.FRANCE
    source_language = SourceLanguage.ENGLISH
    source_kind = SourceKind.OFFICIAL
    article_selector = ".views-row h2 a[href], article h2 a[href], article a[href], h2 a[href]"
    link_path_keywords = ("/en/content/",)
    title_selector = "h1, article h1"
    body_selector = "article, .region-content, main"

    def _parse_published_at(self, date_node) -> datetime | None:
        if date_node is None:
            return None
        raw = (date_node.get("datetime") or date_node.get_text(" ", strip=True) or "").strip()
        parsed = dateparse.parse_datetime(raw)
        if parsed is None:
            for pattern in (
                "%A, %B %d, %Y - %H:%M",
                "%A, %B %d, %Y",
                "%a, %B %d, %Y - %H:%M",
                "%a, %B %d, %Y",
                "%d %B %Y - %H:%M",
                "%d %B %Y",
                "%B %d, %Y - %H:%M",
                "%B %d, %Y",
            ):
                try:
                    parsed = datetime.strptime(raw, pattern)
                    break
                except ValueError:
                    continue
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Paris"))
        return parsed.astimezone(dt_timezone.utc)

    def parse_detail_html(self, html: str, *, url: str) -> SourceArticleDetail:
        detail = super().parse_detail_html(html, url=url)
        soup = BeautifulSoup(html, "lxml")
        date_node = soup.select_one(self.date_selector)
        raw = (
            (date_node.get("datetime") or date_node.get_text(" ", strip=True) or "").strip()
            if date_node is not None
            else ""
        )
        detail.metadata["published_at_evidence"] = {
            "source": "detail" if detail.published_at else "fallback",
            "raw": raw,
            "timezone": "Europe/Paris",
            "verified": bool(detail.published_at),
        }
        detail.metadata["published_at_verified"] = bool(detail.published_at)
        return detail

    def normalize_source_payload(self, stub: SourceArticleStub, detail: SourceArticleDetail) -> CanonicalNewsDraft:
        draft = super().normalize_source_payload(stub, detail)
        if detail.published_at:
            evidence = detail.metadata.get("published_at_evidence") or {}
            draft.metadata["published_at_verified"] = True
            draft.metadata["published_at_evidence"] = evidence
        else:
            evidence = stub.metadata.get("published_at_evidence") or {
                "source": "listing",
                "raw": stub.published_at.isoformat() if stub.published_at else "",
                "timezone": "UTC",
                "verified": False,
            }
            draft.metadata["published_at_verified"] = False
            draft.metadata["published_at_evidence"] = evidence
        return draft


class TDNAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.TDN
    base_url = "https://www.thoroughbreddailynews.com/"
    listing_path = "/wp-json/wp/v2/posts?per_page=20"
    racing_region = RacingRegion.UNITED_STATES
    source_language = SourceLanguage.ENGLISH
    link_path_keywords = ("/",)
    title_selector = "h1, .entry-title"
    body_selector = "span[itemprop='articleBody'], .entry-content, article, main"
    api_url = "https://www.thoroughbreddailynews.com/wp-json/wp/v2/posts?per_page=20"
    resolve_missing_api_dates = False
    max_api_article_age: timedelta | None = None

    def listing_url(self, page_or_month: str | int, mode: SourceMode | str | None = None) -> str:
        return self.api_url

    def fetch_listing(self, mode: SourceMode, page_or_month: str | int) -> list[SourceArticleStub]:
        if not getattr(self, "_preserve_skipped_items", False):
            self.skipped_items = []
        response = requests.get(
            self.listing_url(page_or_month, mode=mode),
            headers={"User-Agent": "umanewsbot/1.0 (+https://umafans.run)"},
            timeout=15,
        )
        self.last_listing_http_status = getattr(response, "status_code", None)
        self.last_listing_final_url = getattr(response, "url", self.listing_url(page_or_month, mode=mode))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            return []
        resolved_mode = mode or self.source_mode
        stubs: list[SourceArticleStub] = []
        seen: set[str] = set()
        for index, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                continue
            raw_url = (item.get("link") or item.get("url") or "").strip()
            raw_title = self._api_title(item.get("title"))
            if not raw_url or not raw_title:
                continue
            article_url = raw_url.split("?", 1)[0]
            if article_url in seen:
                continue
            published_at = self._resolved_api_datetime(item)
            if published_at is None:
                self.skipped_items.append(f"{article_url}: missing_published_at")
                continue
            if self._is_stale_api_article(published_at):
                self.skipped_items.append(f"{article_url}: stale_published_at {published_at.isoformat()}")
                continue
            seen.add(article_url)
            stubs.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=resolved_mode,
                    source_article_id=self._article_id(article_url),
                    source_url=article_url,
                    title_ja=raw_title,
                    published_at=published_at,
                    rank=self._listing_rank(raw_title, index, resolved_mode),
                    metadata={"listing_url": self.listing_url(page_or_month, mode=mode)},
                )
            )
            if len(stubs) >= 20:
                break
        return stubs

    def _api_title(self, title_payload) -> str:
        if isinstance(title_payload, dict):
            raw = title_payload.get("rendered") or ""
        else:
            raw = title_payload or ""
        unescaped = html_lib.unescape(str(raw))
        if "<" in unescaped and ">" in unescaped:
            text = BeautifulSoup(unescaped, "lxml").get_text(" ", strip=True)
        else:
            text = unescaped
        return normalize_whitespace(text)

    def _api_datetime(self, item: dict) -> datetime | None:
        raw = item.get("date_gmt") or item.get("date") or ""
        parsed = dateparse.parse_datetime(str(raw))
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone=dt_timezone.utc)
        return parsed

    def _resolved_api_datetime(self, item: dict) -> datetime | None:
        parsed = self._api_datetime(item)
        if parsed is not None or not self.resolve_missing_api_dates:
            return parsed
        post_item = self._fetch_api_post_item(item)
        if not post_item:
            return None
        return self._api_datetime(post_item)

    def _fetch_api_post_item(self, item: dict) -> dict | None:
        post_url = self._api_post_url(item)
        if not post_url:
            return None
        response = requests.get(
            post_url,
            headers={"User-Agent": "umanewsbot/1.0 (+https://umafans.run)"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None

    def _api_post_url(self, item: dict) -> str:
        links = item.get("_links") if isinstance(item, dict) else None
        if isinstance(links, dict):
            self_links = links.get("self")
            if isinstance(self_links, list):
                for candidate in self_links:
                    if isinstance(candidate, dict) and candidate.get("href"):
                        return str(candidate["href"])
        post_id = item.get("id")
        if post_id:
            return urljoin(self.base_url, f"/wp-json/wp/v2/posts/{post_id}")
        return ""

    def _is_stale_api_article(self, published_at: datetime) -> bool:
        if self.max_api_article_age is None:
            return False
        comparable = published_at
        if timezone.is_naive(comparable):
            comparable = timezone.make_aware(comparable, timezone=dt_timezone.utc)
        return comparable < timezone.now() - self.max_api_article_age


class TDNFranceKeywordAdapter(TDNAdapter):
    source_site = SourceSite.TDN_FRANCE
    canonical_source_site = SourceSite.TDN
    api_url = "https://www.thoroughbreddailynews.com/wp-json/wp/v2/posts"
    racing_region = RacingRegion.FRANCE
    resolve_missing_api_dates = True
    search_query = "France Galop"

    @property
    def max_api_article_age(self) -> timedelta | None:
        if hasattr(self, "_max_api_article_age_override"):
            return self._max_api_article_age_override
        return timedelta(days=max(1, int(getattr(settings, "TDN_FRANCE_FRESHNESS_DAYS", 3))))

    @max_api_article_age.setter
    def max_api_article_age(self, value: timedelta | None) -> None:
        self._max_api_article_age_override = value

    def _query_params(self, query: str) -> dict[str, str | int]:
        age = self.max_api_article_age or timedelta(days=max(1, int(getattr(settings, "TDN_FRANCE_FRESHNESS_DAYS", 3))))
        cutoff = timezone.now() - age
        return {
            "search": query,
            "orderby": "date",
            "order": "desc",
            "after": cutoff.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z"),
            "per_page": 20,
            "_fields": "id,link,title,date_gmt,date",
        }

    def _fetch_query(self, query: str, mode: SourceMode) -> list[SourceArticleStub]:
        params = self._query_params(query)
        response = requests.get(
            self.api_url,
            params=params,
            headers={"User-Agent": "umanewsbot/1.0 (+https://umafans.run)"},
            timeout=15,
        )
        self.last_listing_http_status = getattr(response, "status_code", None)
        prepared_url = requests.Request("GET", self.api_url, params=params).prepare().url or self.api_url
        self.last_listing_final_url = getattr(response, "url", prepared_url) or prepared_url
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            return []
        stubs: list[SourceArticleStub] = []
        for index, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                continue
            raw_url = (item.get("link") or item.get("url") or "").strip()
            raw_title = self._api_title(item.get("title"))
            if not raw_url or not raw_title:
                continue
            article_url = raw_url.split("?", 1)[0]
            published_at = self._resolved_api_datetime(item)
            if published_at is None:
                self.skipped_items.append(f"{article_url}: missing_published_at")
                continue
            if self._is_stale_api_article(published_at):
                self.skipped_items.append(f"{article_url}: stale_published_at {published_at.isoformat()}")
                continue
            raw_date = str(item.get("date_gmt") or item.get("date") or "")
            stubs.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=mode,
                    source_article_id=self._article_id(article_url),
                    source_url=article_url,
                    title_ja=raw_title,
                    published_at=published_at,
                    rank=self._listing_rank(raw_title, index, mode),
                    metadata={
                        "listing_url": self.api_url,
                        "listing_query": query,
                        "listing_queries": [query],
                        "request_url": prepared_url,
                        "published_at_verified": True,
                        "published_at_evidence": {
                            "source": "api",
                            "raw": raw_date,
                            "timezone": "UTC",
                            "verified": True,
                        },
                    },
                )
            )
        return stubs

    def fetch_listing(self, mode: SourceMode, page_or_month: str | int) -> list[SourceArticleStub]:
        self.skipped_items = []
        self.last_listing_query_errors = []
        return self._fetch_query(self.search_query, mode or self.source_mode)[:20]


class TDNFranceBroadKeywordAdapter(TDNFranceKeywordAdapter):
    source_mode = SourceMode.ACCESS
    search_queries = ("French racing", "ParisLongchamp", "Deauville", "Chantilly")
    last_listing_query_errors: list[dict[str, str]]

    def fetch_listing(self, mode: SourceMode, page_or_month: str | int) -> list[SourceArticleStub]:
        resolved_mode = mode or self.source_mode
        by_url: dict[str, SourceArticleStub] = {}
        self.skipped_items = []
        query_errors: list[dict[str, str]] = []
        first_error: Exception | None = None
        successful_query_count = 0
        last_success_http_status: int | None = None
        last_success_final_url = ""
        configured_queries = getattr(settings, "TDN_FRANCE_SEARCH_QUERIES", None)
        queries = tuple(self.search_queries if "search_queries" in self.__dict__ else (configured_queries or self.search_queries))
        for query in queries:
            try:
                query_stubs = self._fetch_query(query, resolved_mode)
                successful_query_count += 1
                last_success_http_status = self.last_listing_http_status
                last_success_final_url = self.last_listing_final_url
            except Exception as exc:
                if first_error is None:
                    first_error = exc
                query_errors.append({"query": query, "error": str(exc)})
                continue
            for stub in query_stubs:
                existing = by_url.get(stub.source_url)
                if existing is None:
                    by_url[stub.source_url] = stub
                    continue
                queries_seen = existing.metadata.setdefault("listing_queries", [existing.metadata.get("listing_query")])
                if query not in queries_seen:
                    queries_seen.append(query)
        self.last_listing_query_errors = query_errors
        stubs = sorted(by_url.values(), key=lambda item: (-item.published_at.timestamp(), item.source_url))[:20]
        if stubs:
            self.last_listing_http_status = last_success_http_status
            self.last_listing_final_url = last_success_final_url
        if not stubs and successful_query_count == 0 and first_error is not None:
            raise first_error
        return stubs


class HorseRacingNationAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.HORSE_RACING_NATION
    base_url = "https://www.horseracingnation.com/"
    listing_path = "/news"
    racing_region = RacingRegion.UNITED_STATES
    source_language = SourceLanguage.ENGLISH
    link_path_keywords = ("/news/",)
    title_selector = "h1"
    body_selector = "article, main"

    def parse_listing_html(self, html: str, *, url: str, mode: SourceMode | str | None = None) -> list[SourceArticleStub]:
        soup = BeautifulSoup(html, "lxml")
        resolved_mode = mode or self.source_mode
        story_anchors = soup.select("article.news-story h3 a[href*='/news/']")
        anchors = soup.select(".ticker a[href*='/news/']") if resolved_mode == SourceMode.ACCESS else []
        anchors.extend(story_anchors or soup.select("main a[href*='/news/']"))
        seen: set[str] = set()
        stubs: list[SourceArticleStub] = []
        for index, anchor in enumerate(anchors, start=1):
            href = (anchor.get("href") or "").strip()
            title = normalize_whitespace(anchor.get("title") or anchor.get_text(" ", strip=True))
            if not href or not title:
                continue
            article_url = urljoin(url, href).split("?", 1)[0]
            if article_url in seen or not self._topic_allowed(title, article_url):
                continue
            seen.add(article_url)
            stubs.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=resolved_mode,
                    source_article_id=self._article_id(article_url),
                    source_url=article_url,
                    title_ja=title,
                    published_at=timezone.now(),
                    rank=self._listing_rank(title, len(stubs) + 1, resolved_mode),
                    metadata={"listing_url": url},
                )
            )
            if len(stubs) >= 20:
                break
        return stubs

    def _topic_allowed(self, title: str, url: str) -> bool:
        if not super()._topic_allowed(title, url):
            return False
        path = re.sub(r"/+", "/", urlsplit(url).path.casefold()).rstrip("/")
        if path in {"/news", "/news/news.aspx"} or path.endswith("/news.aspx"):
            return False
        return True


class AtTheRacesFranceAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.AT_THE_RACES
    base_url = "https://www.attheraces.com/"
    listing_path = "/news"
    racing_region = RacingRegion.FRANCE
    source_language = SourceLanguage.ENGLISH
    include_keywords = ("france", "french", "deauville", "chantilly", "longchamp", "parislongchamp", "auteuil")
    exclude_keywords = ("jour de galop",)
    link_path_keywords = ("/news",)


class BloodHorseAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.BLOODHORSE
    base_url = "https://www.bloodhorse.com/"
    listing_path = "/horse-racing/articles"
    racing_region = RacingRegion.UNITED_STATES
    source_language = SourceLanguage.ENGLISH
    link_path_keywords = ("/horse-racing/articles", "/articles")


class PaulickReportAdapter(SimpleInternationalNewsAdapter):
    source_site = SourceSite.PAULICK_REPORT
    base_url = "https://paulickreport.com/"
    listing_path = "/news/"
    racing_region = RacingRegion.UNITED_STATES
    source_language = SourceLanguage.ENGLISH
    link_path_keywords = ("/news", "/horse-care-category", "/features")


TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


class TrustedLocalTimeNewsAdapter(SimpleInternationalNewsAdapter):
    """本次新增来源共用的严格时间、URL 与网络边界。

    该类只被五个新增 adapter 继承，既有来源继续走原网络和时间兼容路径。
    """

    source_mode = SourceMode.OFFICIAL
    source_kind = SourceKind.OFFICIAL
    source_language = SourceLanguage.ENGLISH
    allowed_hosts: tuple[str, ...] = ()
    local_timezone = "UTC"
    adapter_version = "new-region-news-v1"
    parser_version = "new-region-news-parser-v1"
    automation_permission_status = "unknown"
    request_user_agent = "umanewsbot/1.0 (+https://umafans.run)"
    html_content_types = ("text/html", "application/xhtml+xml")
    listing_content_types = html_content_types
    supports_research_request_budget = True
    preserve_second_precision = False
    detail_path_pattern = ""

    def attach_request_budget(self, budget) -> None:
        self._request_budget = budget

    def _validate_transport_path(self, request_kind: str, url: str) -> None:
        parsed = urlsplit(url)
        parsed_path = parsed.path or "/"
        if request_kind == "listing":
            expected = urlsplit(
                self.listing_url(1, mode=self.source_mode)
            )
            expected_path = expected.path or "/"
            if parsed_path.rstrip("/") != expected_path.rstrip("/"):
                raise ValueError("source_listing_path_not_allowed")
            if sorted(parse_qsl(parsed.query, keep_blank_values=True)) != (
                sorted(
                    parse_qsl(
                        expected.query,
                        keep_blank_values=True,
                    )
                )
            ):
                raise ValueError("source_listing_query_not_allowed")
            return
        if request_kind == "detail" and not self._topic_allowed("", url):
            raise ValueError("source_detail_path_not_allowed")

    @staticmethod
    def _canonical_article_url(url: str) -> str:
        url = html_lib.unescape(str(url))
        parsed = urlsplit(url)
        retained_query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
            and key.casefold() not in TRACKING_QUERY_KEYS
        ]
        path = quote(
            re.sub(r"/+", "/", parsed.path or "/"),
            safe="/%:@-._~!$&'()*+,;=",
        )
        return urlunsplit(
            (
                parsed.scheme.casefold(),
                parsed.netloc.casefold(),
                path,
                urlencode(sorted(retained_query)),
                "",
            )
        )

    def _bounded_html(
        self,
        url: str,
        *,
        accepted_content_types: tuple[str, ...] | None = None,
        request_kind: str,
    ):
        budget = getattr(self, "_request_budget", None)
        ledger_length_before = len(budget.ledger) if budget is not None else 0

        def before_transport_get(kind: str, request_url: str) -> None:
            if budget is not None:
                budget.consume(kind, request_url)
            self._validate_transport_path(kind, request_url)

        try:
            result = get_bounded_html(
                url,
                allowed_hosts=self.allowed_hosts,
                max_redirects=3,
                max_bytes=2 * 1024 * 1024,
                connect_timeout=5,
                read_timeout=15,
                user_agent=self.request_user_agent,
                accepted_content_types=accepted_content_types or self.html_content_types,
                request_kind=request_kind,
                before_transport_get=before_transport_get,
            )
        except Exception as exc:
            if (
                budget is not None
                and len(budget.ledger) > ledger_length_before
                and str(exc) != "source_request_budget_exhausted"
            ):
                budget.mark_last("failed")
            raise
        if budget is not None and len(budget.ledger) > ledger_length_before:
            budget.mark_last("succeeded")
        return result

    def fetch_listing(self, mode: SourceMode, page_or_month: str | int) -> list[SourceArticleStub]:
        url = self.listing_url(page_or_month, mode=mode)
        try:
            response = self._bounded_html(
                url,
                accepted_content_types=self.listing_content_types,
                request_kind="listing",
            )
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            final_url = str(getattr(exc, "final_url", "") or "")
            if status_code is not None:
                self.last_listing_http_status = int(status_code)
            if final_url:
                self.last_listing_final_url = final_url
            raise
        self.last_listing_http_status = response.status_code
        self.last_listing_final_url = response.final_url
        return self.parse_listing_html(
            response.text,
            url=response.final_url,
            mode=mode,
        )

    def fetch_detail(self, source_article_id_or_url: str) -> SourceArticleDetail:
        url = source_article_id_or_url
        if not url.startswith(("http://", "https://")):
            url = urljoin(self.base_url, url)
        response = self._bounded_html(
            self._canonical_article_url(url),
            accepted_content_types=self.html_content_types,
            request_kind="detail",
        )
        return self.parse_detail_html(response.text, url=response.final_url)

    def parse_listing_html(
        self,
        html: str,
        *,
        url: str,
        mode: SourceMode | str | None = None,
    ) -> list[SourceArticleStub]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        stubs: list[SourceArticleStub] = []
        resolved_mode = mode or self.source_mode
        for index, anchor in enumerate(soup.select(self.article_selector), start=1):
            href = html_lib.unescape(anchor.get("href") or "").strip()
            raw_title = anchor.get("title") or anchor.get_text(" ", strip=True)
            title = self._clean_listing_title(raw_title, resolved_mode)
            if not href or not title:
                continue
            article_url = self._canonical_article_url(urljoin(url, href))
            if article_url in seen or not self._topic_allowed(title, article_url):
                continue
            seen.add(article_url)
            stubs.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=resolved_mode,
                    source_article_id=self._article_id(article_url),
                    source_url=article_url,
                    title_ja=normalize_whitespace(title),
                    published_at=None,
                    rank=self._listing_rank(raw_title, index, resolved_mode),
                    metadata={"listing_url": url},
                )
            )
            if len(stubs) >= 20:
                break
        return stubs

    def _topic_allowed(self, title: str, url: str) -> bool:
        parsed = urlsplit(url)
        if parsed.scheme.casefold() != "https":
            return False
        if parsed.username or parsed.password:
            return False
        try:
            if parsed.port not in {None, 443}:
                return False
        except ValueError:
            return False
        if (parsed.hostname or "").rstrip(".").casefold() not in {
            host.rstrip(".").casefold() for host in self.allowed_hosts
        }:
            return False
        path = parsed.path.casefold()
        if self.link_path_keywords and not any(keyword.casefold() in path for keyword in self.link_path_keywords):
            return False
        if self.exclude_path_keywords and any(keyword.casefold() in path for keyword in self.exclude_path_keywords):
            return False
        if self.detail_path_pattern and re.fullmatch(
            self.detail_path_pattern,
            parsed.path,
            flags=re.IGNORECASE,
        ) is None:
            return False
        text = f"{title} {url}".casefold()
        if self.include_keywords and not any(keyword.casefold() in text for keyword in self.include_keywords):
            return False
        if self.exclude_keywords and any(keyword.casefold() in text for keyword in self.exclude_keywords):
            return False
        return True

    def _parse_local_published_at(self, raw: str) -> tuple[datetime | None, str]:
        raw = (raw or "").strip()
        if not raw:
            return None, ""
        try:
            source_zone = ZoneInfo(self.local_timezone)
        except Exception as exc:
            raise ValueError("invalid_published_timezone") from exc
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            parsed_date = dateparse.parse_date(raw)
            if parsed_date is None:
                return None, ""
            parsed = datetime.combine(parsed_date, datetime.min.time()).replace(hour=12)
            precision = "date"
        else:
            parsed = dateparse.parse_datetime(raw)
            precision = (
                "second"
                if self.preserve_second_precision
                and re.search(r"[T ]\d{2}:\d{2}:\d{2}", raw)
                else "minute"
            )
            if parsed is None:
                normalized = re.sub(
                    r"(?<=\d)(?:st|nd|rd|th)\b",
                    "",
                    raw,
                    flags=re.IGNORECASE,
                )
                parsed = None
                for pattern, candidate_precision in (
                    ("%A, %d %B %Y, %I:%M%p", "minute"),
                    ("%A, %d %B %Y, %I:%M %p", "minute"),
                    ("%d %B %Y, %I:%M%p", "minute"),
                    ("%d %B %Y, %I:%M %p", "minute"),
                    ("%A, %d %B %Y", "date"),
                    ("%d %B %Y", "date"),
                ):
                    try:
                        parsed = datetime.strptime(normalized, pattern)
                        precision = candidate_precision
                        break
                    except ValueError:
                        continue
                if parsed is None:
                    return None, ""
                if precision == "date":
                    parsed = parsed.replace(hour=12)
        if timezone.is_naive(parsed):
            parsed = parsed.replace(tzinfo=source_zone)
        return parsed.astimezone(dt_timezone.utc), precision

    @staticmethod
    def _json_ld_published_at(soup: BeautifulSoup) -> str:
        accepted_types = {"article", "newsarticle"}

        def find_date(node) -> str:
            if isinstance(node, list):
                for item in node:
                    value = find_date(item)
                    if value:
                        return value
                return ""
            if not isinstance(node, dict):
                return ""
            raw_types = node.get("@type")
            if isinstance(raw_types, str):
                types = {raw_types.casefold()}
            elif isinstance(raw_types, list):
                types = {str(item).casefold() for item in raw_types}
            else:
                types = set()
            if types.intersection(accepted_types):
                value = node.get("datePublished")
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for value in node.values():
                found = find_date(value)
                if found:
                    return found
            return ""

        for script in soup.select("script[type='application/ld+json']"):
            raw = script.string or script.get_text("", strip=True)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            value = find_date(payload)
            if value:
                return value
        return ""

    def _published_at_raw(self, soup: BeautifulSoup) -> tuple[str, str]:
        meta = soup.select_one("meta[property='article:published_time'][content]")
        if meta is not None:
            raw = str(meta.get("content") or "").strip()
            if raw:
                return raw, "meta"
        raw = self._json_ld_published_at(soup)
        if raw:
            return raw, "json_ld"
        date_node = soup.select_one(self.date_selector)
        if date_node is None:
            return "", ""
        raw = (
            date_node.get("datetime")
            or date_node.get_text(" ", strip=True)
            or ""
        ).strip()
        return raw, "detail"

    def _parse_published_at(self, date_node) -> datetime | None:
        if date_node is None:
            return None
        raw = (date_node.get("datetime") or date_node.get_text(" ", strip=True) or "").strip()
        parsed, _precision = self._parse_local_published_at(raw)
        return parsed

    def parse_detail_html(self, html: str, *, url: str) -> SourceArticleDetail:
        soup = BeautifulSoup(html, "lxml")
        for selector in (
            ".related",
            ".related-stories",
            ".betting",
            ".betting-widget",
            ".promo",
            ".advertisement",
            "footer",
        ):
            for node in soup.select(selector):
                node.decompose()
        cleaned_html = str(soup)
        detail = super().parse_detail_html(cleaned_html, url=url)
        soup = BeautifulSoup(cleaned_html, "lxml")
        raw, evidence_source = self._published_at_raw(soup)
        published_at, precision = self._parse_local_published_at(raw)
        if published_at is None:
            raise ValueError("missing_published_at")
        detail.published_at = published_at
        detail.metadata["published_at_verified"] = True
        detail.metadata["published_at_evidence"] = {
            "source": evidence_source,
            "raw": raw,
            "timezone": self.local_timezone,
            "precision": precision,
            "parser_version": self.parser_version,
            "verified": True,
        }
        return detail

    def normalize_source_payload(
        self,
        stub: SourceArticleStub,
        detail: SourceArticleDetail,
    ) -> CanonicalNewsDraft:
        if detail.published_at is None:
            raise ValueError("missing_published_at")
        if not (detail.title_ja or stub.title_ja):
            raise ValueError("missing_title")
        if not detail.body_ja_normalized:
            raise ValueError("missing_body")
        draft = super().normalize_source_payload(stub, detail)
        draft.source_url = self._canonical_article_url(draft.source_url)
        draft.published_at = detail.published_at
        draft.metadata["published_at_verified"] = True
        draft.metadata["published_at_evidence"] = detail.metadata["published_at_evidence"]
        return draft


class TrustedRssNewsAdapter(TrustedLocalTimeNewsAdapter):
    """严格解析受信来源的 RSS 2.0/Atom，正文仍由原站详情提供。"""

    listing_content_types = (
        "application/rss+xml",
        "application/atom+xml",
        "application/xml",
        "text/xml",
    )
    rss_item_limit = 20
    preserve_second_precision = True

    @staticmethod
    def _xml_local_name(tag: str) -> str:
        return str(tag or "").rsplit("}", 1)[-1].casefold()

    @classmethod
    def _xml_children(cls, element, *names: str) -> list:
        accepted = {name.casefold() for name in names}
        return [
            child
            for child in list(element)
            if cls._xml_local_name(child.tag) in accepted
        ]

    @classmethod
    def _xml_child_text(cls, element, *names: str) -> str:
        for name in names:
            children = cls._xml_children(element, name)
            if children:
                return normalize_whitespace(
                    "".join(children[0].itertext())
                )
        return ""

    @classmethod
    def _rss_link(cls, entry) -> str:
        for node in cls._xml_children(entry, "link"):
            href = str(node.get("href") or "").strip()
            rel = str(node.get("rel") or "alternate").strip().casefold()
            if href and rel in {"", "alternate"}:
                return href
            text = normalize_whitespace("".join(node.itertext()))
            if text:
                return text
        return ""

    def _safe_feed_article_url(
        self,
        raw_url: str,
        *,
        listing_url: str,
        title: str,
    ) -> str:
        raw_url = html_lib.unescape(str(raw_url or "")).strip()
        if not raw_url:
            return ""
        article_url = self._canonical_article_url(
            urljoin(listing_url, raw_url)
        )
        if not self._topic_allowed(title, article_url):
            return ""
        return article_url

    def _parse_feed_published_at(
        self,
        raw: str,
    ) -> tuple[datetime | None, str]:
        raw = normalize_whitespace(raw)
        if not raw or re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return None, ""
        try:
            source_zone = ZoneInfo(self.local_timezone)
        except Exception as exc:
            raise ValueError("invalid_published_timezone") from exc

        parsed: datetime | None = None
        is_iso = bool(
            re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", raw)
        )
        if is_iso:
            parsed = dateparse.parse_datetime(raw)
            if parsed is not None and timezone.is_naive(parsed):
                parsed = parsed.replace(tzinfo=source_zone)
            precision = (
                "second"
                if re.search(r"T\d{2}:\d{2}:\d{2}", raw)
                else "minute"
            )
        else:
            try:
                parsed = email.utils.parsedate_to_datetime(raw)
            except (TypeError, ValueError, OverflowError):
                parsed = None
            # RFC 日期中的未知/缺失 offset 不得猜测。
            if parsed is not None and timezone.is_naive(parsed):
                return None, ""
            precision = (
                "second"
                if re.search(r"\b\d{1,2}:\d{2}:\d{2}\b", raw)
                else "minute"
            )
        if parsed is None:
            return None, ""
        return parsed.astimezone(dt_timezone.utc), precision

    def _rss_entry_allowed(
        self,
        *,
        title: str,
        article_url: str,
        categories: tuple[str, ...],
    ) -> bool:
        del title, article_url, categories
        return True

    def _normalized_detail_allowed(
        self,
        draft: CanonicalNewsDraft,
    ) -> bool:
        del draft
        return True

    def parse_listing_html(
        self,
        html: str,
        *,
        url: str,
        mode: SourceMode | str | None = None,
    ) -> list[SourceArticleStub]:
        if len(str(html).encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("rss_response_too_large")
        folded_prefix = str(html)[:4096].casefold()
        if "<!doctype" in folded_prefix or "<!entity" in folded_prefix:
            raise ValueError("rss_xml_unsafe_declaration")
        try:
            root = ElementTree.fromstring(str(html))
        except ElementTree.ParseError as exc:
            raise ValueError("rss_xml_invalid") from exc
        if self._xml_local_name(root.tag) not in {"rss", "rdf", "feed"}:
            raise ValueError("rss_feed_root_invalid")
        entries = [
            node
            for node in root.iter()
            if self._xml_local_name(node.tag) in {"item", "entry"}
        ]
        if not entries:
            raise ValueError("rss_feed_empty")

        self.skipped_items = []
        resolved_mode = mode or self.source_mode
        seen_urls: set[str] = set()
        stubs: list[SourceArticleStub] = []
        for entry in entries:
            title = self._xml_child_text(entry, "title")
            raw_link = self._rss_link(entry)
            raw_guid = self._xml_child_text(entry, "guid", "id")
            article_url = self._safe_feed_article_url(
                raw_link,
                listing_url=url,
                title=title,
            )
            if not article_url and not raw_link:
                article_url = self._safe_feed_article_url(
                    raw_guid,
                    listing_url=url,
                    title=title,
                )
            if not title or not article_url:
                self.skipped_items.append("rss_invalid_title_or_link")
                continue
            if article_url in seen_urls:
                self.skipped_items.append(
                    f"rss_duplicate_canonical:{article_url}"
                )
                continue
            categories = tuple(
                normalize_whitespace(
                    str(node.get("term") or "")
                    or "".join(node.itertext())
                )
                for node in self._xml_children(entry, "category")
            )
            if not self._rss_entry_allowed(
                title=title,
                article_url=article_url,
                categories=categories,
            ):
                self.skipped_items.append(
                    f"rss_topic_filtered:{article_url}"
                )
                continue

            raw_published = self._xml_child_text(
                entry,
                "pubdate",
                "published",
                "updated",
            )
            published_at, precision = self._parse_feed_published_at(
                raw_published
            )
            metadata = {
                "listing_url": url,
                "rss_guid": raw_guid,
                "rss_categories": list(categories),
                "published_at_verified": published_at is not None,
            }
            if published_at is not None:
                metadata["published_at_evidence"] = {
                    "source": "rss",
                    "raw": raw_published,
                    "timezone": self.local_timezone,
                    "precision": precision,
                    "parser_version": self.parser_version,
                    "verified": True,
                }
            seen_urls.add(article_url)
            stubs.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=resolved_mode,
                    source_article_id=self._article_id(article_url),
                    source_url=article_url,
                    title_ja=normalize_whitespace(title),
                    published_at=published_at,
                    metadata=metadata,
                )
            )
            if len(stubs) >= self.rss_item_limit:
                break
        return stubs

    def parse_detail_html(
        self,
        html: str,
        *,
        url: str,
    ) -> SourceArticleDetail:
        try:
            detail = super().parse_detail_html(html, url=url)
        except ValueError as exc:
            if str(exc) != "missing_published_at":
                raise
            detail = SimpleInternationalNewsAdapter.parse_detail_html(
                self,
                html,
                url=url,
            )
        detail.images = []
        return detail

    def normalize_source_payload(
        self,
        stub: SourceArticleStub,
        detail: SourceArticleDetail,
    ) -> CanonicalNewsDraft:
        if not (detail.title_ja or stub.title_ja):
            raise ValueError("missing_title")
        if not detail.body_ja_normalized:
            raise ValueError("missing_body")
        detail_evidence = dict(
            (detail.metadata or {}).get("published_at_evidence") or {}
        )
        stub_evidence = dict(
            (stub.metadata or {}).get("published_at_evidence") or {}
        )
        if (
            stub.published_at is not None
            and stub_evidence.get("verified") is True
            and str(stub_evidence.get("precision") or "")
            in {"minute", "second"}
        ):
            published_at = stub.published_at
            evidence = stub_evidence
        elif detail.published_at is not None and detail_evidence.get(
            "verified"
        ) is True:
            published_at = detail.published_at
            evidence = detail_evidence
        else:
            raise ValueError("missing_published_at")
        draft = SimpleInternationalNewsAdapter.normalize_source_payload(
            self,
            stub,
            detail,
        )
        draft.source_url = self._canonical_article_url(draft.source_url)
        draft.published_at = published_at
        draft.images = []
        draft.metadata["published_at_verified"] = True
        draft.metadata["published_at_evidence"] = evidence
        if not self._normalized_detail_allowed(draft):
            raise ValueError("source_topic_filtered")
        return draft


class HRINewsAdapter(TrustedLocalTimeNewsAdapter):
    source_site = SourceSite.HRI_NEWS
    base_url = "https://www.hri.ie/"
    listing_path = "/news-and-media"
    racing_region = RacingRegion.IRELAND
    allowed_hosts = ("www.hri.ie", "hri.ie")
    local_timezone = "Europe/Dublin"
    parser_version = "hri-news-v1"
    automation_permission_status = "blocked"
    link_path_keywords = ("/news/details/",)


class WoodbineNewsAdapter(TrustedLocalTimeNewsAdapter):
    source_site = SourceSite.WOODBINE_NEWS
    base_url = "https://woodbine.com/"
    listing_path = "/news/"
    racing_region = RacingRegion.CANADA
    allowed_hosts = ("woodbine.com", "www.woodbine.com")
    local_timezone = "America/Toronto"
    parser_version = "woodbine-news-v1"
    automation_permission_status = "blocked"
    link_path_keywords = ("/woodbine-news/",)
    exclude_path_keywords = (
        "/news/",
        "/blog/",
        "/author/",
        "/authors/",
        "/tag/",
        "/tags/",
    )
    body_selector = ".entry-content"


class EmiratesRacingAuthorityAdapter(TrustedLocalTimeNewsAdapter):
    source_site = SourceSite.EMIRATES_RACING_AUTHORITY
    base_url = "https://emiratesracing.com/"
    listing_path = "/news/"
    racing_region = RacingRegion.UNITED_ARAB_EMIRATES
    allowed_hosts = ("emiratesracing.com", "www.emiratesracing.com")
    local_timezone = "Asia/Dubai"
    parser_version = "era-news-v1"
    automation_permission_status = "blocked"
    link_path_keywords = ("/news/",)
    body_selector = ".article-body"


class JCSANewsAdapter(TrustedLocalTimeNewsAdapter):
    source_site = SourceSite.JCSA_NEWS
    base_url = "https://jcsa.sa/"
    listing_path = "/api/news/en/0/12"
    racing_region = RacingRegion.SAUDI_ARABIA
    allowed_hosts = ("jcsa.sa", "www.jcsa.sa")
    local_timezone = "Asia/Riyadh"
    parser_version = "jcsa-news-v1"
    link_path_keywords = ("/en/news/",)
    title_selector = "h1"
    body_selector = ".content-area"
    date_selector = ".text-black-body.font-inter.text-small-body"

    def listing_url(
        self,
        page_or_month: str | int,
        mode: SourceMode | str | None = None,
    ) -> str:
        del mode
        try:
            page = max(1, int(page_or_month))
        except (TypeError, ValueError):
            page = 1
        return urljoin(self.base_url, f"/api/news/en/{(page - 1) * 12}/12")


class RacingVictoriaNewsAdapter(TrustedLocalTimeNewsAdapter):
    source_site = SourceSite.RACING_VICTORIA_NEWS
    base_url = "https://www.racingvictoria.com.au/"
    listing_path = "/sitemap.xml"
    racing_region = RacingRegion.AUSTRALIA
    allowed_hosts = ("www.racingvictoria.com.au", "racingvictoria.com.au")
    local_timezone = "Australia/Melbourne"
    parser_version = "racing-victoria-news-v1"
    link_path_keywords = ("/news/", "/news")
    listing_content_types = (
        "text/html",
        "application/xhtml+xml",
        "text/xml",
        "application/xml",
    )

    def parse_listing_html(
        self,
        html: str,
        *,
        url: str,
        mode: SourceMode | str | None = None,
    ) -> list[SourceArticleStub]:
        soup = BeautifulSoup(html, "xml")
        candidates: list[tuple[str, str]] = []
        seen: set[str] = set()
        for location in soup.find_all("loc"):
            article_url = self._canonical_article_url(
                location.get_text("", strip=True)
            )
            if article_url in seen:
                continue
            parsed = urlsplit(article_url)
            match = re.fullmatch(
                r"/news/(\d{4})/(\d{2})/(\d{2})/([^/]+)/?",
                parsed.path,
                flags=re.IGNORECASE,
            )
            if match is None or not self._topic_allowed("", article_url):
                continue
            date_key = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
            if dateparse.parse_date(date_key) is None:
                continue
            seen.add(article_url)
            candidates.append((date_key, article_url))

        resolved_mode = mode or self.source_mode
        stubs: list[SourceArticleStub] = []
        for _date_key, article_url in sorted(
            candidates,
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )[:20]:
            slug = urlsplit(article_url).path.rstrip("/").split("/")[-1]
            title = normalize_whitespace(slug.replace("-", " ").title())
            stubs.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=resolved_mode,
                    source_article_id=self._article_id(article_url),
                    source_url=article_url,
                    title_ja=title,
                    published_at=None,
                    metadata={"listing_url": url},
                )
            )
        return stubs

    @staticmethod
    def _sitecore_value(value) -> str:
        if isinstance(value, dict):
            value = value.get("value")
        return str(value or "").strip()

    @classmethod
    def _main_rich_text_values(cls, node) -> list[str]:
        values: list[str] = []
        if isinstance(node, list):
            for item in node:
                values.extend(cls._main_rich_text_values(item))
            return values
        if not isinstance(node, dict):
            return values
        component_name = str(node.get("componentName") or "")
        if component_name == "DCAArticleList":
            return values
        if component_name == "RichText":
            fields = node.get("fields")
            if isinstance(fields, dict):
                text_field = fields.get("Text")
                value = cls._sitecore_value(text_field)
                if value:
                    values.append(value)
        for value in node.values():
            if isinstance(value, (dict, list)):
                values.extend(cls._main_rich_text_values(value))
        return values

    def parse_detail_html(self, html: str, *, url: str) -> SourceArticleDetail:
        soup = BeautifulSoup(html, "lxml")
        script = soup.select_one("script#__NEXT_DATA__")
        raw_payload = script.string or script.get_text("", strip=True) if script else ""
        if not raw_payload:
            raise ValueError("missing_next_data")
        try:
            payload = json.loads(raw_payload)
            route = payload["props"]["pageProps"]["layoutData"]["sitecore"]["route"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid_next_data_route") from exc
        fields = route.get("fields") if isinstance(route, dict) else None
        placeholders = route.get("placeholders") if isinstance(route, dict) else None
        if not isinstance(fields, dict) or not isinstance(placeholders, dict):
            raise ValueError("invalid_next_data_route")

        title = normalize_whitespace(self._sitecore_value(fields.get("Title")))
        raw_date = self._sitecore_value(fields.get("ArticleDate"))
        published_at, precision = self._parse_local_published_at(raw_date)
        rich_text_values = self._main_rich_text_values(
            placeholders.get("headless-main")
        )
        article_soup = BeautifulSoup(
            f"<article>{''.join(rich_text_values)}</article>",
            "lxml",
        )
        article_node = article_soup.select_one("article")
        clean_result = (
            clean_international_article_body(
                article_node,
                source_site=self.source_site,
            )
            if article_node is not None
            else ArticleContentCleanResult(
                text="",
                status="selector_not_found",
                removed_rules={},
            )
        )
        body_raw = clean_result.text
        body_normalized = normalize_whitespace(body_raw)
        if not title:
            raise ValueError("missing_title")
        if published_at is None:
            raise ValueError("missing_published_at")
        if not body_normalized:
            raise ValueError("missing_body")
        return SourceArticleDetail(
            title_ja=title,
            body_ja_raw=body_raw,
            body_ja_normalized=body_normalized,
            published_at=published_at,
            images=[],
            metadata={
                "author": "",
                "source_url": url,
                "region": self.racing_region,
                "source_language": self.source_language,
                "body_parse_status": clean_result.status,
                "body_selector": "script#__NEXT_DATA__:headless-main:RichText",
                "body_cleaning": clean_result.metadata(),
                "published_at_verified": True,
                "published_at_evidence": {
                    "source": "next_data",
                    "raw": raw_date,
                    "timezone": self.local_timezone,
                    "precision": precision,
                    "parser_version": self.parser_version,
                    "verified": True,
                },
            },
            original_content_html=html,
        )


def _json_ld_article_payload(soup: BeautifulSoup) -> dict:
    accepted_types = {"article", "newsarticle"}

    def find_article(node) -> dict:
        if isinstance(node, list):
            for item in node:
                found = find_article(item)
                if found:
                    return found
            return {}
        if not isinstance(node, dict):
            return {}
        raw_types = node.get("@type")
        if isinstance(raw_types, str):
            types = {raw_types.casefold()}
        elif isinstance(raw_types, list):
            types = {str(item).casefold() for item in raw_types}
        else:
            types = set()
        if types.intersection(accepted_types):
            return node
        for value in node.values():
            found = find_article(value)
            if found:
                return found
        return {}

    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        found = find_article(payload)
        if found:
            return found
    return {}


def _ensure_json_ld_article_nodes(
    html: str,
    *,
    body_selector: str,
) -> str:
    soup = BeautifulSoup(html, "lxml")
    payload = _json_ld_article_payload(soup)
    if not payload:
        return html
    body = normalize_whitespace(str(payload.get("articleBody") or ""))
    headline = normalize_whitespace(str(payload.get("headline") or ""))
    container = soup.body or soup
    if body:
        article = soup.new_tag("article")
        article["class"] = ["umanews-jsonld-article"]
        article.string = body
        container.insert(0, article)
    if (
        headline
        and soup.select_one(
            "meta[property='og:title'], meta[name='twitter:title'], h1"
        )
        is None
    ):
        heading = soup.new_tag("h1")
        heading.string = headline
        container.insert(0, heading)
    return str(soup)


class RTERacingAdapter(TrustedRssNewsAdapter):
    source_site = SourceSite.RTE_RACING
    base_url = "https://www.rte.ie/"
    listing_path = "/feeds/rss/?index=/sport/racing/"
    racing_region = RacingRegion.IRELAND
    source_kind = SourceKind.MEDIA
    allowed_hosts = ("www.rte.ie", "rte.ie")
    local_timezone = "Europe/Dublin"
    parser_version = "rte-racing-rss-v1"
    link_path_keywords = ("/sport/racing/",)
    detail_path_pattern = r"/sport/racing/\d{4}/\d{4}/\d+-[^/]+/?"
    body_selector = ".umanews-jsonld-article, article"

    def parse_detail_html(
        self,
        html: str,
        *,
        url: str,
    ) -> SourceArticleDetail:
        prepared = _ensure_json_ld_article_nodes(
            html,
            body_selector=self.body_selector,
        )
        detail = super().parse_detail_html(prepared, url=url)
        detail.original_content_html = html
        return detail


class IrishRacingNewsAdapter(TrustedLocalTimeNewsAdapter):
    source_site = SourceSite.IRISHRACING_NEWS
    base_url = "https://www.irishracing.com/"
    listing_path = "/news"
    racing_region = RacingRegion.IRELAND
    source_kind = SourceKind.MEDIA
    allowed_hosts = ("www.irishracing.com", "irishracing.com")
    local_timezone = "Europe/Dublin"
    parser_version = "irishracing-news-v2"
    preserve_second_precision = True
    article_selector = (
        ".news-date-group h4 a[href], h4 a[href], "
        ".firstitemrow a[href], .news-item a[href]"
    )
    link_path_keywords = ("/news/",)
    detail_path_pattern = r"/news/[^/]+/\d+/?"
    title_selector = "h1"
    body_selector = "#reportbody, .news-story, .news-content, article"

    def parse_listing_html(
        self,
        html: str,
        *,
        url: str,
        mode: SourceMode | str | None = None,
    ) -> list[SourceArticleStub]:
        soup = BeautifulSoup(html, "lxml")
        resolved_mode = mode or self.source_mode
        seen: set[str] = set()
        stubs: list[SourceArticleStub] = []
        for anchor in soup.select(self.article_selector):
            heading = anchor.select_one("h2, h3, h4")
            title = normalize_whitespace(
                anchor.get("title")
                or (
                    heading.get_text(" ", strip=True)
                    if heading is not None
                    else anchor.get_text(" ", strip=True)
                )
            )
            article_url = self._canonical_article_url(
                urljoin(url, str(anchor.get("href") or "").strip())
            )
            parsed = urlsplit(article_url)
            if (
                not title
                or not self._topic_allowed(title, article_url)
                or re.fullmatch(
                    r"/news/[^/]+/\d+/?",
                    parsed.path,
                    flags=re.IGNORECASE,
                )
                is None
                or article_url in seen
            ):
                continue

            group = anchor.find_parent(
                lambda tag: bool(
                    getattr(tag, "attrs", {}).get("data-date")
                )
            )
            raw_date = (
                str(group.get("data-date") or "").strip()
                if group is not None
                else ""
            )
            card = anchor.find_parent(
                lambda tag: bool(
                    {
                        "news-item",
                        "firstitemrow",
                    }.intersection(
                        set(getattr(tag, "attrs", {}).get("class") or [])
                    )
                )
            )
            if not raw_date and card is not None:
                row = card.find_parent(
                    lambda tag: bool(
                        {
                            "newitemrow",
                            "firstitemrow",
                        }.intersection(
                            set(
                                getattr(tag, "attrs", {}).get("class") or []
                            )
                        )
                    )
                )
                if row is None and "firstitemrow" in set(
                    getattr(card, "attrs", {}).get("class") or []
                ):
                    row = card
                date_row = (
                    row.find_previous_sibling(
                        lambda tag: "newsitemdate"
                        in set(
                            getattr(tag, "attrs", {}).get("class") or []
                        )
                    )
                    if row is not None
                    else None
                )
                if date_row is not None:
                    raw_date = normalize_whitespace(
                        date_row.get_text(" ", strip=True)
                    )
            article_node = anchor.find_parent("article") or card
            stamp_node = (
                article_node.select_one(".news-stamp")
                if article_node is not None
                else None
            )
            raw_stamp = (
                stamp_node.get_text(" ", strip=True)
                if stamp_node is not None
                else ""
            )
            published_at = None
            evidence = {}
            parsed_date = dateparse.parse_date(raw_date)
            if parsed_date is None and raw_date:
                normalized_date = re.sub(
                    r"(?<=\d)(?:st|nd|rd|th)\b",
                    "",
                    raw_date,
                    flags=re.IGNORECASE,
                )
                for date_pattern in (
                    "%a %d %b %Y",
                    "%A %d %B %Y",
                    "%d %b %Y",
                    "%d %B %Y",
                ):
                    try:
                        parsed_date = datetime.strptime(
                            normalized_date,
                            date_pattern,
                        ).date()
                        break
                    except ValueError:
                        continue
            parsed_time = None
            for pattern in ("%I:%M%p", "%I:%M %p", "%H:%M"):
                try:
                    parsed_time = datetime.strptime(
                        raw_stamp.upper(),
                        pattern,
                    ).time()
                    break
                except ValueError:
                    continue
            if parsed_date is not None and parsed_time is not None:
                try:
                    local_zone = ZoneInfo(self.local_timezone)
                except Exception as exc:
                    raise ValueError("invalid_published_timezone") from exc
                local_value = datetime.combine(
                    parsed_date,
                    parsed_time,
                    tzinfo=local_zone,
                )
                published_at = local_value.astimezone(dt_timezone.utc)
                evidence = {
                    "source": "listing_date_group",
                    "raw": f"{raw_date} {raw_stamp}".strip(),
                    "timezone": self.local_timezone,
                    "precision": "minute",
                    "parser_version": self.parser_version,
                    "verified": True,
                }
            metadata = {
                "listing_url": url,
                "published_at_verified": published_at is not None,
            }
            if evidence:
                metadata["published_at_evidence"] = evidence
            seen.add(article_url)
            stubs.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=resolved_mode,
                    source_article_id=self._article_id(article_url),
                    source_url=article_url,
                    title_ja=title,
                    published_at=published_at,
                    metadata=metadata,
                )
            )
            if len(stubs) >= 20:
                break
        return stubs

    def parse_detail_html(
        self,
        html: str,
        *,
        url: str,
    ) -> SourceArticleDetail:
        try:
            return super().parse_detail_html(html, url=url)
        except ValueError as exc:
            if str(exc) != "missing_published_at":
                raise
            return SimpleInternationalNewsAdapter.parse_detail_html(
                self,
                html,
                url=url,
            )

    def normalize_source_payload(
        self,
        stub: SourceArticleStub,
        detail: SourceArticleDetail,
    ) -> CanonicalNewsDraft:
        if detail.published_at is not None:
            return super().normalize_source_payload(stub, detail)
        evidence = dict(
            (stub.metadata or {}).get("published_at_evidence") or {}
        )
        if (
            stub.published_at is None
            or evidence.get("verified") is not True
        ):
            raise ValueError("missing_published_at")
        if not (detail.title_ja or stub.title_ja):
            raise ValueError("missing_title")
        if not detail.body_ja_normalized:
            raise ValueError("missing_body")
        draft = SimpleInternationalNewsAdapter.normalize_source_payload(
            self,
            stub,
            detail,
        )
        draft.source_url = self._canonical_article_url(draft.source_url)
        draft.published_at = stub.published_at
        draft.images = []
        draft.metadata["published_at_verified"] = True
        draft.metadata["published_at_evidence"] = evidence
        return draft


class CanadianThoroughbredAdapter(TrustedLocalTimeNewsAdapter):
    source_site = SourceSite.CANADIAN_THOROUGHBRED
    base_url = "https://canadianthoroughbred.com/"
    listing_path = "/news/"
    racing_region = RacingRegion.CANADA
    source_kind = SourceKind.MEDIA
    allowed_hosts = (
        "canadianthoroughbred.com",
        "www.canadianthoroughbred.com",
    )
    local_timezone = "America/Toronto"
    parser_version = "canadian-thoroughbred-v1"
    preserve_second_precision = True
    article_selector = ".post-card a[href], article a[href]"
    link_path_keywords = ("/horse-news/",)
    detail_path_pattern = r"/horse-news/[^/]+/?"
    body_selector = ".entry-content, article"
    prefer_meta_title = False


class AssiniboiaDownsNewsAdapter(TrustedRssNewsAdapter):
    source_site = SourceSite.ASSINIBOIA_DOWNS_NEWS
    base_url = "https://asdowns.com/"
    listing_path = "/feed/"
    racing_region = RacingRegion.CANADA
    source_kind = SourceKind.OFFICIAL
    allowed_hosts = ("asdowns.com", "www.asdowns.com")
    local_timezone = "America/Winnipeg"
    parser_version = "assiniboia-rss-v1"
    link_path_keywords = ("/",)
    exclude_path_keywords = (
        "/author/",
        "/tag/",
        "/category/",
        "/feed/",
    )
    detail_path_pattern = r"/[^/]+/?"
    body_selector = ".entry-content, article"


class DubaiRacingClubAdapter(TrustedRssNewsAdapter):
    source_site = SourceSite.DUBAI_RACING_CLUB
    base_url = "https://dubairacingclub.com/"
    listing_path = "/feed/"
    racing_region = RacingRegion.UNITED_ARAB_EMIRATES
    source_kind = SourceKind.OFFICIAL
    allowed_hosts = ("dubairacingclub.com", "www.dubairacingclub.com")
    local_timezone = "Asia/Dubai"
    parser_version = "drc-rss-v1"
    link_path_keywords = ("/press-releases/",)
    detail_path_pattern = r"/press-releases/[^/]+/?"
    body_selector = ".entry-content, article"


class TheNationalRacingAdapter(TrustedLocalTimeNewsAdapter):
    source_site = SourceSite.THE_NATIONAL_RACING
    base_url = "https://www.thenationalnews.com/"
    listing_path = "/sport/horse-racing/"
    racing_region = RacingRegion.UNITED_ARAB_EMIRATES
    source_kind = SourceKind.MEDIA
    allowed_hosts = ("www.thenationalnews.com", "thenationalnews.com")
    local_timezone = "Asia/Dubai"
    parser_version = "the-national-racing-v1"
    preserve_second_precision = True
    article_selector = (
        "[data-section='horse-racing'] article a[href], "
        "a[href*='/sport/horse-racing/']"
    )
    link_path_keywords = ("/sport/horse-racing/",)
    detail_path_pattern = r"/sport/horse-racing/[^/]+/?"
    body_selector = ".umanews-jsonld-article, article, .article-body"

    def parse_detail_html(
        self,
        html: str,
        *,
        url: str,
    ) -> SourceArticleDetail:
        prepared = _ensure_json_ld_article_nodes(
            html,
            body_selector=self.body_selector,
        )
        detail = super().parse_detail_html(prepared, url=url)
        payload = _json_ld_article_payload(BeautifulSoup(html, "lxml"))
        headline = normalize_whitespace(
            str(payload.get("headline") or "")
        )
        if headline:
            detail.title_ja = headline
        detail.original_content_html = html
        return detail


class SaudiPressAgencyHorseRacingAdapter(TrustedLocalTimeNewsAdapter):
    source_site = SourceSite.SPA_HORSE_RACING
    base_url = "https://www.spa.gov.sa/"
    listing_path = "/en/search?search=horse%20racing"
    racing_region = RacingRegion.SAUDI_ARABIA
    source_kind = SourceKind.OFFICIAL
    allowed_hosts = (
        "www.spa.gov.sa",
        "spa.gov.sa",
        "portalapi.spa.gov.sa",
    )
    local_timezone = "Asia/Riyadh"
    parser_version = "spa-horse-racing-v2"
    preserve_second_precision = True
    link_path_keywords = ("/en/",)
    detail_path_pattern = r"/en/(?:[0-9a-f]{10}|N\d+)/?"
    exclude_keywords = ("camel", "show jumping")
    search_api_url = (
        "https://portalapi.spa.gov.sa/api/v1/news/search"
        "?title=horse%20racing&exact_search=0&by_latest=0"
        "&start=0&rows=10&l=en"
    )
    api_listing_content_types = ("application/json",)

    def _validate_transport_path(
        self,
        request_kind: str,
        url: str,
    ) -> None:
        parsed = urlsplit(url)
        expected = urlsplit(self.search_api_url)
        if (
            request_kind == "listing"
            and (parsed.hostname or "").rstrip(".").casefold()
            == (expected.hostname or "").rstrip(".").casefold()
        ):
            if parsed.path.rstrip("/") != expected.path.rstrip("/"):
                raise ValueError("source_listing_path_not_allowed")
            if sorted(parse_qsl(parsed.query, keep_blank_values=True)) != (
                sorted(parse_qsl(expected.query, keep_blank_values=True))
            ):
                raise ValueError("source_listing_query_not_allowed")
            return
        super()._validate_transport_path(request_kind, url)

    def fetch_listing(
        self,
        mode: SourceMode,
        page_or_month: str | int,
    ) -> list[SourceArticleStub]:
        del page_or_month
        try:
            response = self._bounded_html(
                self.search_api_url,
                accepted_content_types=self.api_listing_content_types,
                request_kind="listing",
            )
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            final_url = str(getattr(exc, "final_url", "") or "")
            if status_code is not None:
                self.last_listing_http_status = int(status_code)
            if final_url:
                self.last_listing_final_url = final_url
            raise
        self.last_listing_http_status = response.status_code
        self.last_listing_final_url = response.final_url
        return self.parse_listing_html(
            response.text,
            url=response.final_url,
            mode=mode,
        )

    @staticmethod
    def _next_data(soup: BeautifulSoup) -> dict:
        script = soup.select_one("script#__NEXT_DATA__")
        raw = script.string or script.get_text("", strip=True) if script else ""
        if not raw:
            raise ValueError("missing_next_data")
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_next_data") from exc
        if not isinstance(payload, dict):
            raise ValueError("invalid_next_data")
        return payload

    @classmethod
    def _dict_lists_named(cls, node, name: str) -> list[list]:
        matches: list[list] = []
        if isinstance(node, list):
            for item in node:
                matches.extend(cls._dict_lists_named(item, name))
            return matches
        if not isinstance(node, dict):
            return matches
        for key, value in node.items():
            if key == name and isinstance(value, list):
                matches.append(value)
            if isinstance(value, (dict, list)):
                matches.extend(cls._dict_lists_named(value, name))
        return matches

    @classmethod
    def _article_dict(cls, node) -> dict:
        if isinstance(node, list):
            for item in node:
                found = cls._article_dict(item)
                if found:
                    return found
            return {}
        if not isinstance(node, dict):
            return {}
        required = {"title", "content", "published_at"}
        if required.issubset(node):
            return node
        for value in node.values():
            found = cls._article_dict(value)
            if found:
                return found
        return {}

    @staticmethod
    def _horse_racing_topic(*values: str) -> bool:
        text = " ".join(str(value or "") for value in values).casefold()
        if any(term in text for term in ("camel", "show jumping")):
            return False
        return any(
            term in text
            for term in (
                "horse racing",
                "horse race",
                "saudi cup",
                "jcsa",
                "king abdulaziz racecourse",
            )
        )

    def _parse_spa_published_at(
        self,
        raw,
    ) -> tuple[datetime | None, str]:
        if isinstance(raw, (int, float)) or (
            isinstance(raw, str) and raw.strip().isdigit()
        ):
            try:
                timestamp = int(raw)
                if timestamp <= 0:
                    return None, ""
                return (
                    datetime.fromtimestamp(
                        timestamp,
                        tz=dt_timezone.utc,
                    ),
                    "second",
                )
            except (OverflowError, OSError, TypeError, ValueError):
                return None, ""
        return self._parse_local_published_at(str(raw or ""))

    def parse_listing_html(
        self,
        html: str,
        *,
        url: str,
        mode: SourceMode | str | None = None,
    ) -> list[SourceArticleStub]:
        stripped = str(html or "").lstrip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid_search_api_payload") from exc
            result_items = (
                payload.get("data")
                if isinstance(payload, dict)
                else None
            )
            if not isinstance(result_items, list):
                raise ValueError("missing_search_results")
        else:
            payload = self._next_data(BeautifulSoup(html, "lxml"))
            result_lists = self._dict_lists_named(
                payload,
                "searchResults",
            )
            if not result_lists:
                raise ValueError("missing_search_results")
            result_items = result_lists[0]
        result_items = sorted(
            result_items,
            key=lambda item: (
                int(item.get("published_at") or 0)
                if isinstance(item, dict)
                and str(item.get("published_at") or "").isdigit()
                else 0
            ),
            reverse=True,
        )
        resolved_mode = mode or self.source_mode
        seen: set[str] = set()
        stubs: list[SourceArticleStub] = []
        self.skipped_items = []
        for item in result_items:
            if not isinstance(item, dict):
                continue
            title = normalize_whitespace(str(item.get("title") or ""))
            topic = normalize_whitespace(str(item.get("topic") or ""))
            content = normalize_whitespace(
                BeautifulSoup(
                    str(item.get("content") or ""),
                    "lxml",
                ).get_text(" ", strip=True)
            )
            raw_uuid = str(item.get("uuid") or "").strip()
            raw_url = str(
                item.get("url")
                or item.get("sharable_link")
                or ""
            ).strip()
            if re.fullmatch(
                r"(?:[0-9a-f]{10}|N\d+)",
                raw_uuid,
                re.IGNORECASE,
            ):
                raw_url = f"https://www.spa.gov.sa/en/{raw_uuid}"
            elif raw_url and not raw_url.startswith(("http://", "https://")):
                raw_url = f"https://{raw_url.lstrip('/')}"
            article_url = self._canonical_article_url(raw_url)
            parsed = urlsplit(article_url)
            if (
                not self._horse_racing_topic(title, topic, content)
                or not self._topic_allowed(title, article_url)
                or re.fullmatch(
                    self.detail_path_pattern,
                    parsed.path,
                    flags=re.IGNORECASE,
                ) is None
            ):
                self.skipped_items.append("spa_non_horse_racing")
                continue
            if article_url in seen:
                continue
            raw_published = item.get("published_at")
            published_at, precision = self._parse_spa_published_at(
                raw_published
            )
            metadata = {
                "listing_url": url,
                "topic": topic,
                "published_at_verified": published_at is not None,
            }
            if published_at is not None:
                metadata["published_at_evidence"] = {
                    "source": "spa_search_api",
                    "raw": str(raw_published or ""),
                    "timezone": "UTC",
                    "precision": precision,
                    "parser_version": self.parser_version,
                    "verified": True,
                }
            seen.add(article_url)
            stubs.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=resolved_mode,
                    source_article_id=self._article_id(article_url),
                    source_url=article_url,
                    title_ja=title,
                    published_at=published_at,
                    metadata=metadata,
                )
            )
            if len(stubs) >= 20:
                break
        return stubs

    def parse_detail_html(
        self,
        html: str,
        *,
        url: str,
    ) -> SourceArticleDetail:
        payload = self._next_data(BeautifulSoup(html, "lxml"))
        article = self._article_dict(payload)
        if not article:
            raise ValueError("missing_article_payload")
        title = normalize_whitespace(str(article.get("title") or ""))
        topic = normalize_whitespace(str(article.get("topic") or ""))
        raw_content = str(article.get("content") or "")
        if not self._horse_racing_topic(title, topic, raw_content):
            raise ValueError("spa_non_horse_racing")
        content_soup = BeautifulSoup(
            f"<article>{raw_content}</article>",
            "lxml",
        )
        content_node = content_soup.select_one("article")
        clean_result = (
            clean_international_article_body(
                content_node,
                source_site=self.source_site,
            )
            if content_node is not None
            else ArticleContentCleanResult(
                text="",
                status="selector_not_found",
                removed_rules={},
            )
        )
        body = normalize_whitespace(clean_result.text)
        raw_published_value = article.get("published_at")
        raw_published = normalize_whitespace(
            str(raw_published_value or "")
        )
        published_at, precision = self._parse_spa_published_at(
            raw_published_value
        )
        if not title:
            raise ValueError("missing_title")
        if not body:
            raise ValueError("missing_body")
        if published_at is None:
            raise ValueError("missing_published_at")
        return SourceArticleDetail(
            title_ja=title,
            body_ja_raw=clean_result.text,
            body_ja_normalized=body,
            published_at=published_at,
            images=[],
            metadata={
                "source_url": url,
                "region": self.racing_region,
                "source_language": self.source_language,
                "body_parse_status": clean_result.status,
                "body_selector": "script#__NEXT_DATA__:article.content",
                "body_cleaning": clean_result.metadata(),
                "published_at_verified": True,
                "published_at_evidence": {
                    "source": "next_data",
                    "raw": raw_published,
                    "timezone": (
                        "UTC"
                        if raw_published.isdigit()
                        else self.local_timezone
                    ),
                    "precision": precision,
                    "parser_version": self.parser_version,
                    "verified": True,
                },
            },
            original_content_html=html,
        )


class ArabNewsRacingAdapter(TrustedLocalTimeNewsAdapter):
    source_site = SourceSite.ARAB_NEWS_RACING
    base_url = "https://www.arabnews.com/"
    listing_path = "/tags/horse-racing"
    racing_region = RacingRegion.SAUDI_ARABIA
    source_kind = SourceKind.MEDIA
    allowed_hosts = ("www.arabnews.com", "arabnews.com")
    local_timezone = "Asia/Riyadh"
    parser_version = "arab-news-racing-v1"
    preserve_second_precision = True
    article_selector = ".view-content a[href]"
    link_path_keywords = ("/node/",)
    detail_path_pattern = r"/node/\d+/sport/?"
    body_selector = ".field-name-body, article"

    def _article_id(self, url: str) -> str:
        match = re.fullmatch(
            r"/node/(\d+)/sport/?",
            urlsplit(url).path,
            flags=re.IGNORECASE,
        )
        if match is None:
            return super()._article_id(url)
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        return f"{match.group(1)}-{digest}"

    def _topic_allowed(self, title: str, url: str) -> bool:
        if not super()._topic_allowed(title, url):
            return False
        return (
            re.fullmatch(
                r"/node/\d+/sport/?",
                urlsplit(url).path,
                flags=re.IGNORECASE,
            )
            is not None
        )


class JustHorseRacingAdapter(TrustedRssNewsAdapter):
    source_site = SourceSite.JUST_HORSE_RACING
    base_url = "https://www.justhorseracing.com.au/"
    listing_path = "/feed"
    racing_region = RacingRegion.AUSTRALIA
    source_kind = SourceKind.MEDIA
    allowed_hosts = (
        "www.justhorseracing.com.au",
        "justhorseracing.com.au",
    )
    local_timezone = "Australia/Melbourne"
    parser_version = "just-horse-racing-rss-v1"
    link_path_keywords = ("/news/australian-racing/",)
    detail_path_pattern = (
        r"/news/australian-racing/[^/]+/\d+/?"
    )
    exclude_keywords = ("tips", "odds", "betting", "market")
    body_selector = ".entry-content, article"

    def _normalized_detail_allowed(
        self,
        draft: CanonicalNewsDraft,
    ) -> bool:
        text = " ".join(
            (
                draft.title_ja,
                draft.source_url,
                draft.body_ja_normalized,
            )
        ).casefold()
        return not any(
            term in text
            for term in ("tips", "odds", "betting market")
        )


class TheStraightAdapter(TrustedRssNewsAdapter):
    source_site = SourceSite.THE_STRAIGHT
    base_url = "https://thestraight.com.au/"
    listing_path = "/feed/"
    racing_region = RacingRegion.AUSTRALIA
    source_kind = SourceKind.MEDIA
    allowed_hosts = ("thestraight.com.au", "www.thestraight.com.au")
    local_timezone = "Australia/Sydney"
    parser_version = "the-straight-rss-v1"
    link_path_keywords = ("/",)
    exclude_path_keywords = (
        "/author/",
        "/tag/",
        "/category/",
        "/feed/",
    )
    detail_path_pattern = r"/[^/]+/?"
    exclude_keywords = ("betting", "prediction", "odds", "tips")
    body_selector = ".entry-content, article"

    def _normalized_detail_allowed(
        self,
        draft: CanonicalNewsDraft,
    ) -> bool:
        text = " ".join(
            (draft.title_ja, draft.body_ja_normalized)
        ).casefold()
        return not any(
            term in text
            for term in ("betting", "prediction market", "odds", "tips")
        )


class RacingNSWNewsAdapter(TrustedRssNewsAdapter):
    source_site = SourceSite.RACING_NSW_NEWS
    base_url = "https://www.racingnsw.com.au/"
    listing_path = "/feed/"
    racing_region = RacingRegion.AUSTRALIA
    source_kind = SourceKind.OFFICIAL
    allowed_hosts = ("www.racingnsw.com.au", "racingnsw.com.au")
    local_timezone = "Australia/Sydney"
    parser_version = "racing-nsw-rss-v2"
    link_path_keywords = ("/news/",)
    detail_path_pattern = r"/news/[^/]+/[^/]+/?"
    body_selector = (
        ".ct-inner-content .ct-code-block, .entry-content, article"
    )

    @staticmethod
    def _tips_or_preview_item(title: str, article_url: str) -> bool:
        text = " ".join((title, article_url)).casefold()
        return any(term in text for term in ("tips", "preview"))

    def _rss_entry_allowed(
        self,
        *,
        title: str,
        article_url: str,
        categories: tuple[str, ...],
    ) -> bool:
        del categories
        return not self._tips_or_preview_item(title, article_url)

    def _normalized_detail_allowed(
        self,
        draft: CanonicalNewsDraft,
    ) -> bool:
        return not self._tips_or_preview_item(
            draft.title_ja,
            draft.source_url,
        )

    def normalize_source_payload(
        self,
        stub: SourceArticleStub,
        detail: SourceArticleDetail,
    ) -> CanonicalNewsDraft:
        if self._tips_or_preview_item(stub.title_ja, stub.source_url):
            raise ValueError("source_topic_filtered")
        draft = super().normalize_source_payload(stub, detail)
        if normalize_whitespace(detail.title_ja).casefold() in {
            "latest news",
            "news",
        }:
            draft.title_ja = normalize_whitespace(stub.title_ja)
        return draft


class TasracingNewsAdapter(TrustedRssNewsAdapter):
    source_site = SourceSite.TASRACING_NEWS
    base_url = "https://tasracing.com.au/"
    listing_path = "/news/rss.xml"
    racing_region = RacingRegion.AUSTRALIA
    source_kind = SourceKind.OFFICIAL
    allowed_hosts = ("tasracing.com.au", "www.tasracing.com.au")
    local_timezone = "Australia/Hobart"
    parser_version = "tasracing-rss-v2"
    link_path_keywords = ("/news/",)
    detail_path_pattern = r"/news/[^/]+/?"
    title_selector = "h2, h1"
    body_selector = ".blog-content, .news-detail, article"

    def _rss_entry_allowed(
        self,
        *,
        title: str,
        article_url: str,
        categories: tuple[str, ...],
    ) -> bool:
        del article_url
        text = " ".join((title, *categories)).casefold()
        if any(term in text for term in ("harness", "greyhound")):
            return False
        return True

    def _normalized_detail_allowed(
        self,
        draft: CanonicalNewsDraft,
    ) -> bool:
        categories = tuple(
            str(item)
            for item in (draft.metadata or {}).get(
                "rss_categories",
                [],
            )
        )
        text = " ".join(
            (
                draft.title_ja,
                draft.body_ja_normalized,
                *categories,
            )
        ).casefold()
        if any(term in text for term in ("harness", "greyhound")):
            return False
        return any(
            term in text
            for term in (
                "thoroughbred",
                "gallop",
                "hobart",
                "launceston cup",
                "devonport cup",
            )
        )


INTERNATIONAL_ADAPTERS = {
    "sponichi": SponichiAdapter,
    "hkjc_news": HKJCRacingNewsAdapter,
    "scmp_racing": SCMPRacingAdapter,
    "sporting_life": SportingLifeAdapter,
    "sky_sports_racing": SkySportsRacingAdapter,
    "bha": BHAAdapter,
    "france_galop_news": FranceGalopEnglishNewsAdapter,
    "tdn": TDNAdapter,
    "tdn_france": TDNFranceKeywordAdapter,
    "tdn_france_broad": TDNFranceBroadKeywordAdapter,
    "horse_racing_nation": HorseRacingNationAdapter,
    "at_the_races_france": AtTheRacesFranceAdapter,
    "bloodhorse": BloodHorseAdapter,
    "paulick_report": PaulickReportAdapter,
    "hri_news": HRINewsAdapter,
    "woodbine_news": WoodbineNewsAdapter,
    "emirates_racing_authority": EmiratesRacingAuthorityAdapter,
    "jcsa_news": JCSANewsAdapter,
    "racing_victoria_news": RacingVictoriaNewsAdapter,
    "rte_racing": RTERacingAdapter,
    "irishracing_news": IrishRacingNewsAdapter,
    "canadian_thoroughbred": CanadianThoroughbredAdapter,
    "assiniboia_downs_news": AssiniboiaDownsNewsAdapter,
    "dubai_racing_club": DubaiRacingClubAdapter,
    "the_national_racing": TheNationalRacingAdapter,
    "spa_horse_racing": SaudiPressAgencyHorseRacingAdapter,
    "arab_news_racing": ArabNewsRacingAdapter,
    "just_horse_racing": JustHorseRacingAdapter,
    "the_straight": TheStraightAdapter,
    "racing_nsw_news": RacingNSWNewsAdapter,
    "tasracing_news": TasracingNewsAdapter,
}


FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS = (
    "sponichi",
    "hkjc_news",
    "scmp_racing",
    "sporting_life",
    "sky_sports_racing",
    "bha",
    "france_galop_news",
    "tdn_france",
    "tdn_france_broad",
    "tdn",
    "horse_racing_nation",
)


FIRST_VERSION_INTERNATIONAL_PROBES = (
    ("sponichi", SourceMode.LATEST),
    ("sponichi", SourceMode.ACCESS),
    ("hkjc_news", SourceMode.LATEST),
    ("scmp_racing", SourceMode.LATEST),
    ("sporting_life", SourceMode.LATEST),
    ("sky_sports_racing", SourceMode.ACCESS),
    ("sky_sports_racing", SourceMode.LATEST),
    ("bha", SourceMode.OFFICIAL),
    ("france_galop_news", SourceMode.OFFICIAL),
    ("tdn_france", SourceMode.LATEST),
    ("tdn_france_broad", SourceMode.ACCESS),
    ("tdn", SourceMode.LATEST),
    ("horse_racing_nation", SourceMode.ACCESS),
    ("horse_racing_nation", SourceMode.LATEST),
)

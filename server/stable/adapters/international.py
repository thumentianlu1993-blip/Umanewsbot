from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from django.utils import dateparse, timezone

from stable.models import RacingRegion, SourceKind, SourceLanguage, SourceMode, SourceSite
from stable.services.http import DEFAULT_HEADERS, get_bytes
from stable.services.text import extract_article_text, normalize_whitespace

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
        body_node = soup.select_one(self.body_selector) or soup.body
        date_node = soup.select_one(self.date_selector)
        author_node = soup.select_one(self.author_selector)
        meta_title = title_meta.get("content", "").strip() if title_meta and title_meta.get("content") else ""
        node_title = title_node.get_text(" ", strip=True) if title_node else ""
        title = normalize_whitespace(meta_title if self.prefer_meta_title and meta_title else node_title or meta_title)
        body_raw = extract_article_text(body_node)
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
            },
            original_content_html=html,
        )

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
    include_keywords = ("競馬", "keiba", "race", "horse", "s000040")
    link_path_keywords = ("/gamble/news/", "/news/")
    article_selector = (
        ".tab-gamble a[href], .tab-contents a[href], li.cateGamble a[href], "
        "article a[href], h1 a[href], h2 a[href], h3 a[href]"
    )

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
    api_url = "https://www.thoroughbreddailynews.com/wp-json/wp/v2/search?search=France%20Galop&per_page=20"
    racing_region = RacingRegion.FRANCE
    resolve_missing_api_dates = True
    max_api_article_age = timedelta(days=3)


class TDNFranceBroadKeywordAdapter(TDNFranceKeywordAdapter):
    source_mode = SourceMode.ACCESS
    search_queries = ("French racing", "ParisLongchamp", "Deauville", "Chantilly")
    last_listing_query_errors: list[dict[str, str]]

    def listing_url(self, page_or_month: str | int, mode: SourceMode | str | None = None) -> str:
        return "https://www.thoroughbreddailynews.com/wp-json/wp/v2/search?search=French%20racing&per_page=20"

    def fetch_listing(self, mode: SourceMode, page_or_month: str | int) -> list[SourceArticleStub]:
        resolved_mode = mode or self.source_mode
        stubs: list[SourceArticleStub] = []
        seen: set[str] = set()
        self.skipped_items = []
        query_errors: list[dict[str, str]] = []
        first_error: Exception | None = None
        successful_query_count = 0
        last_success_http_status: int | None = None
        last_success_final_url = ""
        self._preserve_skipped_items = True
        try:
            for query in self.search_queries:
                self.api_url = (
                    "https://www.thoroughbreddailynews.com/wp-json/wp/v2/search?"
                    f"search={requests.utils.quote(query)}&per_page=20"
                )
                try:
                    query_stubs = super().fetch_listing(resolved_mode, page_or_month)
                    successful_query_count += 1
                    last_success_http_status = self.last_listing_http_status
                    last_success_final_url = self.last_listing_final_url
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
                    query_errors.append({"query": query, "error": str(exc)})
                    continue
                for stub in query_stubs:
                    if stub.source_url in seen:
                        continue
                    seen.add(stub.source_url)
                    stub.metadata["listing_query"] = query
                    stubs.append(stub)
                    if len(stubs) >= 20:
                        self.last_listing_query_errors = query_errors
                        self.last_listing_http_status = last_success_http_status
                        self.last_listing_final_url = last_success_final_url
                        return stubs
        finally:
            self._preserve_skipped_items = False
        self.last_listing_query_errors = query_errors
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
    body_selector = "article, main, body"

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

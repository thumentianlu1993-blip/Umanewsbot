from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from django.utils import timezone

from stable.models import SourceMode, SourceSite
from stable.services.http import get_bytes
from stable.services.text import extract_article_text, normalize_whitespace

from .base import CanonicalNewsDraft, SourceAdapter, SourceArticleDetail, SourceArticleStub, SourceImageDraft


BASE_URL = "https://www.jra.go.jp"
TOKYO_TZ = ZoneInfo("Asia/Tokyo")


class JRAAdapter(SourceAdapter):
    source_site = SourceSite.JRA

    def __init__(self) -> None:
        self.skipped_items: list[str] = []

    def fetch_listing(self, mode: SourceMode, page_or_month: str | int) -> list[SourceArticleStub]:
        month = str(page_or_month)
        year_hint = self._year_hint_from_month(month)
        html = str(get_bytes(f"{BASE_URL}/news/{month}/", encoding="shift_jis"))
        soup = BeautifulSoup(html, "lxml")
        articles: list[SourceArticleStub] = []
        for news_unit in soup.select(".news_unit"):
            heading = news_unit.select_one("h2")
            if not heading:
                continue
            heading_text = heading.get_text(" ", strip=True)
            try:
                published_at = self._parse_heading_date(heading_text, year_hint=year_hint)
            except ValueError as exc:
                self.skipped_items.append(f"{heading_text}: {exc}")
                continue
            for anchor in news_unit.select("ul.news_line_list li a[href]"):
                href = anchor.get("href", "").strip()
                if not href.startswith("/news/"):
                    continue
                title_node = anchor.select_one(".txt")
                title = title_node.get_text(" ", strip=True) if title_node else anchor.get_text(" ", strip=True)
                article_url = urljoin(BASE_URL, href)
                articles.append(
                    SourceArticleStub(
                        source_site=self.source_site,
                        source_mode=SourceMode.OFFICIAL,
                        source_article_id=href,
                        source_url=article_url,
                        title_ja=title,
                        published_at=published_at,
                        metadata={"month": month},
                    )
                )
        return articles

    def fetch_detail(self, source_article_id_or_url: str) -> SourceArticleDetail:
        url = source_article_id_or_url
        if url.startswith("/"):
            url = urljoin(BASE_URL, url)
        html = str(get_bytes(url, encoding="shift_jis"))
        soup = BeautifulSoup(html, "lxml")
        title = soup.find_all("h1")[1].get_text(" ", strip=True)
        published_text = soup.select_one(".news_title .date").get_text(" ", strip=True)
        published_at = self._parse_heading_date(
            published_text,
            year_hint=self._year_hint_from_url(url),
            source_url=url,
        )
        body_node = soup.select_one(".news_body")
        body_raw = extract_article_text(body_node)
        body_normalized = normalize_whitespace(body_raw)
        images: list[SourceImageDraft] = []
        for index, item in enumerate(soup.select(".img_line_list .item"), start=0):
            img = item.select_one("img")
            if not img:
                continue
            caption = item.select_one(".cap")
            images.append(
                SourceImageDraft(
                    original_url=urljoin(url, img.get("src", "").strip()),
                    caption_ja=caption.get_text(" ", strip=True) if caption else "",
                    sort_order=index,
                )
            )
        return SourceArticleDetail(
            title_ja=title,
            body_ja_raw=body_raw,
            body_ja_normalized=body_normalized,
            published_at=published_at,
            images=images,
            metadata={"publisher": "JRA"},
        )

    def normalize_source_payload(self, stub: SourceArticleStub, detail: SourceArticleDetail) -> CanonicalNewsDraft:
        return CanonicalNewsDraft(
            source_site=self.source_site,
            source_mode=SourceMode.OFFICIAL,
            source_article_id=stub.source_article_id,
            source_url=stub.source_url,
            title_ja=detail.title_ja or stub.title_ja,
            body_ja_raw=detail.body_ja_raw,
            body_ja_normalized=detail.body_ja_normalized,
            published_at=detail.published_at or stub.published_at,
            images=detail.images,
            metadata={**stub.metadata, **detail.metadata},
        )

    def _parse_heading_date(self, text: str, *, year_hint: int | None = None, source_url: str = "") -> datetime:
        normalized = text.replace("（", "(").replace("）", ")")
        date_part = normalized.split("(")[0].strip()
        match = re.search(r"(?:(?P<year>\d{4})年)?(?P<month>\d{1,2})月(?P<day>\d{1,2})日", date_part)
        if not match:
            location = f" ({source_url})" if source_url else ""
            raise ValueError(f"unsupported JRA date format: {text}{location}")
        year = int(match.group("year") or year_hint or timezone.now().astimezone(TOKYO_TZ).year)
        month = int(match.group("month"))
        day = int(match.group("day"))
        dt = datetime(year, month, day, tzinfo=TOKYO_TZ)
        if not match.group("year") and not year_hint:
            today = timezone.now().astimezone(TOKYO_TZ).date()
            if dt.date() > today + timedelta(days=7):
                dt = datetime(year - 1, month, day, tzinfo=TOKYO_TZ)
        return dt.astimezone(timezone.get_current_timezone())

    def _year_hint_from_month(self, value: str) -> int | None:
        match = re.match(r"(?P<year>\d{4})(?P<month>\d{2})$", value)
        return int(match.group("year")) if match else None

    def _year_hint_from_url(self, value: str) -> int | None:
        match = re.search(r"/news/(?P<year>\d{4})(?P<month>\d{2})/", value)
        return int(match.group("year")) if match else None

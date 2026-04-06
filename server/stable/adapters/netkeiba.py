from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from django.utils import timezone

from stable.models import SourceMode, SourceSite
from stable.services.http import get_bytes
from stable.services.text import normalize_whitespace

from .base import CanonicalNewsDraft, SourceAdapter, SourceArticleDetail, SourceArticleStub, SourceImageDraft


TOKYO_TZ = ZoneInfo("Asia/Tokyo")
BASE_URL = "https://news.netkeiba.com/"
MOBILE_URL = "https://news.sp.netkeiba.com/"
RANK_TYPE_MAP = {
    SourceMode.LATEST: 4,
    SourceMode.ACCESS: 2,
    SourceMode.ATTENTION: 3,
}


class NetkeibaAdapter(SourceAdapter):
    source_site = SourceSite.NETKEIBA

    def fetch_listing(self, mode: SourceMode, page_or_month: str | int) -> list[SourceArticleStub]:
        params = {
            "pid": "api_get_news_rank",
            "input": "UTF-8",
            "output": "jsonp",
            "show_id": "NewsBacknumberList",
            "rank_type": str(RANK_TYPE_MAP[mode]),
            "category_id": "3",
            "subcategory_id": "",
            "limit": "20",
            "page": str(page_or_month),
            "pager_type": "pager",
            "pager_url": "",
            "template_prefix": "main",
            "_pid_suffix": "",
        }
        raw = str(get_bytes(BASE_URL, params=params, encoding="utf-8")).strip()
        if raw.startswith("(") and raw.endswith(")"):
            raw = raw[1:-1]
        fragment = json.loads(raw)
        soup = BeautifulSoup(fragment, "lxml")
        articles: list[SourceArticleStub] = []
        for index, anchor in enumerate(soup.select("a.ArticleLink"), start=1):
            href = anchor.get("href", "").strip()
            article_id = href.split("no=")[-1] if "no=" in href else href
            title = anchor.get("title", "").strip()
            info_box = anchor.select_one(".Nk_DataList")
            time_text = ""
            comment_count = None
            attention_count = None
            if info_box:
                time_node = info_box.select_one(".Time")
                comment_node = info_box.select_one(".Comment")
                attention_node = info_box.select_one(".Chumoku")
                time_text = time_node.get_text(" ", strip=True) if time_node else ""
                comment_count = int(comment_node.get_text(strip=True)) if comment_node and comment_node.get_text(strip=True).isdigit() else None
                attention_count = int(attention_node.get_text(strip=True)) if attention_node and attention_node.get_text(strip=True).isdigit() else None
            published_at = self._parse_relative_time(time_text)
            articles.append(
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=mode,
                    source_article_id=article_id,
                    source_url=href,
                    title_ja=title,
                    published_at=published_at,
                    rank=index if mode in {SourceMode.ACCESS, SourceMode.ATTENTION} else None,
                    comment_count=comment_count,
                    attention_count=attention_count,
                    metadata={"time_text": time_text},
                )
            )
        return articles

    def fetch_detail(self, source_article_id_or_url: str) -> SourceArticleDetail:
        article_id = source_article_id_or_url.split("no=")[-1]
        params = {"pid": "news_view", "no": article_id}
        html = str(get_bytes(MOBILE_URL, params=params, encoding="utf-8"))
        soup = BeautifulSoup(html, "lxml")
        title = soup.select_one(".News_Title").get_text(" ", strip=True)
        published_text = soup.select_one(".News_Data_Time").get_text(" ", strip=True)
        published_at = self._parse_absolute_time(published_text)
        body_node = soup.select_one(".News_Txt")
        body_raw = body_node.get_text("\n", strip=True) if body_node else ""
        body_normalized = normalize_whitespace(body_raw)
        images: list[SourceImageDraft] = []
        for index, image_box in enumerate(soup.select(".News_Photo_Box_02"), start=0):
            img = image_box.select_one("img")
            if not img:
                continue
            caption = image_box.select_one(".Caption")
            images.append(
                SourceImageDraft(
                    original_url=img.get("src", "").strip(),
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
            metadata={"publisher": self._extract_publisher(soup)},
        )

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
            comment_count=stub.comment_count,
            attention_count=stub.attention_count,
            rank=stub.rank,
            metadata={**stub.metadata, **detail.metadata},
        )

    def _parse_relative_time(self, value: str) -> datetime:
        now = timezone.now().astimezone(TOKYO_TZ)
        if "時間前" in value:
            dt = now - timedelta(hours=int(value.split("時間前")[0] or 0))
        elif "分前" in value:
            dt = now - timedelta(minutes=int(value.split("分前")[0] or 0))
        else:
            dt = now
        return dt.astimezone(timezone.get_current_timezone())

    def _parse_absolute_time(self, value: str) -> datetime:
        match = re.search(r"(\d{4})年(\d{2})月(\d{2})日.*?(\d{2}):(\d{2})", value)
        if not match:
            return timezone.now()
        year, month, day, hour, minute = [int(item) for item in match.groups()]
        return datetime(year, month, day, hour, minute, tzinfo=TOKYO_TZ).astimezone(timezone.get_current_timezone())

    def _extract_publisher(self, soup: BeautifulSoup) -> str:
        img = soup.select_one(".Info img")
        return img.get("alt", "").strip() if img else "netkeiba"

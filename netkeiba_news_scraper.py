#!/usr/bin/env python3
"""Scrape news list pages from netkeiba and optionally fetch article details.

Examples:
    python netkeiba_news_scraper.py
    python netkeiba_news_scraper.py --start-page 1 --end-page 3 --with-detail
    python netkeiba_news_scraper.py --output result.json --delay 1.0
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Optional


BASE_URL = "https://news.netkeiba.com/"
MOBILE_BASE_URL = "https://news.sp.netkeiba.com/"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
}


@dataclass
class NewsItem:
    no: str
    title: str
    url: str
    time_text: str = ""
    comment_count: Optional[int] = None
    attention_count: Optional[int] = None
    image_url: str = ""
    summary: str = ""
    detail: Optional[dict] = None


def fetch_bytes(url: str, params: Optional[dict] = None) -> bytes:
    if params:
        query = urllib.parse.urlencode(params)
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def fetch_text(
    url: str,
    params: Optional[dict] = None,
    *,
    encoding: Optional[str] = None,
) -> str:
    data = fetch_bytes(url, params)
    if encoding:
        return data.decode(encoding, errors="replace")
    return data.decode("utf-8", errors="replace")


def fetch_backnumber_fragment(page: int, rank_type: int = 4, category_id: int = 3) -> str:
    params = {
        "pid": "api_get_news_rank",
        "input": "UTF-8",
        "output": "jsonp",
        "show_id": "NewsBacknumberList",
        "rank_type": str(rank_type),
        "category_id": str(category_id),
        "subcategory_id": "",
        "limit": "20",
        "page": str(page),
        "pager_type": "pager",
        "pager_url": "",
        "template_prefix": "main",
        "_pid_suffix": "",
    }
    raw = fetch_text(BASE_URL, params, encoding="utf-8").strip()
    if raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1]
    fragment = json.loads(raw)
    return fragment


def extract_no(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    return query.get("no", [""])[0]


def parse_int(value: str) -> Optional[int]:
    value = value.strip()
    if value.isdigit():
        return int(value)
    return None


class ListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[NewsItem] = []
        self._current: Optional[NewsItem] = None
        self._capture: Optional[str] = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr = dict(attrs)
        class_attr = attr.get("class", "")
        if tag == "a" and "ArticleLink" in class_attr:
            url = html.unescape(attr.get("href", ""))
            title = html.unescape(attr.get("title", "")).strip()
            self._current = NewsItem(no=extract_no(url), title=title, url=url)
        elif self._current and tag == "h2" and "NewsTitle" in class_attr:
            self._capture = "title"
            self._text_parts = []
        elif self._current and tag == "p" and "NewsTxt" in class_attr:
            self._capture = "summary"
            self._text_parts = []
        elif self._current and tag == "li" and "Time" in class_attr:
            self._capture = "time_text"
            self._text_parts = []
        elif self._current and tag == "li" and "Comment" in class_attr:
            self._capture = "comment_count"
            self._text_parts = []
        elif self._current and tag == "li" and "Chumoku" in class_attr:
            self._capture = "attention_count"
            self._text_parts = []
        elif self._current and tag == "img" and "Image" in class_attr and not self._current.image_url:
            self._current.image_url = html.unescape(attr.get("src", ""))

    def handle_endtag(self, tag: str) -> None:
        if not self._current:
            return
        if self._capture and tag in {"h2", "p", "li"}:
            value = "".join(self._text_parts).strip()
            if self._capture == "title" and value:
                self._current.title = value
            elif self._capture == "summary":
                self._current.summary = value
            elif self._capture == "time_text":
                self._current.time_text = value
            elif self._capture == "comment_count":
                self._current.comment_count = parse_int(value)
            elif self._capture == "attention_count":
                self._current.attention_count = parse_int(value)
            self._capture = None
            self._text_parts = []
        if tag == "a" and self._current:
            self.items.append(self._current)
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text_parts.append(data)


class DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.source = ""
        self.published_at = ""
        self.image_url = ""
        self.body_parts: list[str] = []
        self._capture: Optional[str] = None
        self._title_parts: list[str] = []
        self._time_parts: list[str] = []
        self._source_parts: list[str] = []
        self._inside_body = False
        self._inside_photo = False
        self._inside_info = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr = dict(attrs)
        class_attr = attr.get("class", "")
        if tag == "h1" and "News_Title" in class_attr:
            self._capture = "title"
            self._title_parts = []
        elif tag == "div" and "News_Txt_Box" in class_attr:
            self._inside_body = True
        elif tag == "div" and "News_Photo_Box_02" in class_attr:
            self._inside_photo = True
        elif tag == "div" and "Info" in class_attr:
            self._inside_info = True
        elif tag == "p" and "News_Data_Time" in class_attr:
            self._capture = "published_at"
            self._time_parts = []
        elif tag == "p" and "Source" in class_attr:
            self._capture = "source"
            self._source_parts = []
        elif self._inside_info and tag == "img" and not self.source:
            self.source = html.unescape(attr.get("alt", "")).strip()
        elif self._inside_photo and tag == "img" and not self.image_url:
            self.image_url = html.unescape(attr.get("src", ""))
        elif self._inside_body and tag == "br":
            self.body_parts.append("\n")
        elif self._inside_body and tag == "a":
            href = html.unescape(attr.get("href", ""))
            if href:
                self.body_parts.append("")

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "title" and tag == "h1":
            self.title = "".join(self._title_parts).strip()
            self._capture = None
        elif self._capture == "published_at" and tag == "p":
            self.published_at = "".join(self._time_parts).strip()
            self._capture = None
        elif self._capture == "source" and tag == "p":
            self.source = "".join(self._source_parts).strip()
            self._capture = None
        elif tag == "div" and self._inside_body:
            self._inside_body = False
        elif tag == "div" and self._inside_photo:
            self._inside_photo = False
        elif tag == "div" and self._inside_info:
            self._inside_info = False

    def handle_data(self, data: str) -> None:
        if self._capture == "title":
            self._title_parts.append(data)
        elif self._capture == "published_at":
            self._time_parts.append(data)
        elif self._capture == "source":
            self._source_parts.append(data)
        elif self._inside_body:
            self.body_parts.append(data)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def parse_list_html(fragment: str) -> list[NewsItem]:
    parser = ListParser()
    parser.feed(fragment)
    seen: set[str] = set()
    items: list[NewsItem] = []
    for item in parser.items:
        if item.no and item.no not in seen:
            seen.add(item.no)
            items.append(item)
    return items


def fetch_news_detail(no: str) -> dict:
    params = {"pid": "news_view", "no": no}
    html_text = fetch_text(MOBILE_BASE_URL, params, encoding="utf-8")
    parser = DetailParser()
    parser.feed(html_text)
    body = normalize_whitespace("".join(parser.body_parts))
    if not parser.published_at:
        match = re.search(r'"datePublished":\s*"([^"]+)"', html_text)
        if match:
            parser.published_at = match.group(1)
    return {
        "title": parser.title,
        "published_at": parser.published_at,
        "source": parser.source,
        "image_url": parser.image_url,
        "body": body,
        "mobile_url": f"{MOBILE_BASE_URL}?pid=news_view&no={no}",
    }


def scrape_pages(
    start_page: int,
    end_page: int,
    *,
    with_detail: bool,
    delay: float,
) -> list[NewsItem]:
    all_items: list[NewsItem] = []
    for page in range(start_page, end_page + 1):
        fragment = fetch_backnumber_fragment(page)
        page_items = parse_list_html(fragment)
        if with_detail:
            for item in page_items:
                if delay:
                    time.sleep(delay)
                item.detail = fetch_news_detail(item.no)
        all_items.extend(page_items)
        print(f"[page {page}] fetched {len(page_items)} items", file=sys.stderr)
        if delay and page != end_page:
            time.sleep(delay)
    return all_items


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape netkeiba backnumber news pages.")
    parser.add_argument("--start-page", type=int, default=1, help="Start page number. Default: 1")
    parser.add_argument("--end-page", type=int, default=1, help="End page number. Default: 1")
    parser.add_argument(
        "--with-detail",
        action="store_true",
        help="Fetch each article's detail page from the mobile site.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between requests in seconds. Default: 0.5",
    )
    parser.add_argument(
        "--output",
        default="netkeiba_news.json",
        help="Output JSON file path. Default: netkeiba_news.json",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.start_page < 1 or args.end_page < args.start_page:
        parser.error("page range is invalid")

    items = scrape_pages(
        args.start_page,
        args.end_page,
        with_detail=args.with_detail,
        delay=max(args.delay, 0.0),
    )

    result = {
        "source": "https://news.netkeiba.com/?pid=news_backnumber&page=1",
        "start_page": args.start_page,
        "end_page": args.end_page,
        "count": len(items),
        "items": [asdict(item) for item in items],
    }
    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print(f"Saved {len(items)} items to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

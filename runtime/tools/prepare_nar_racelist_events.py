#!/usr/bin/env python3
"""NAR ダートグレード年度赛事列表 → import_race_events 契约的 events CSV。

解析 keiba.go.jp 年度 racelist 页（/dirtgraderace/{year}/racelist/index.html）：
月份分节 + li.js-item（日期、等级 class、赛事名、马场/距离/发走时刻、racecard 链接）。
默认只输出地方一级赛 Jpn1（grade class `jpn1`）；可用 --grades 扩展（如 jpn1,g1）。

纪律：解析不到任何赛事即失败；日期/时刻缺失留空而不猜；
source_refs 记录 racelist 与 racecard URL；不写数据库。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from bs4 import BeautifulSoup  # noqa: E402

from race_event_request_budget import before_network_request  # noqa: E402
from race_event_safe_http import fetch_https, validate_https_url  # noqa: E402
from race_event_source_cache import write_source_cache  # noqa: E402

RACELIST_URL = "https://www.keiba.go.jp/dirtgraderace/{year}/racelist/index.html"
KEIBA_BASE = "https://www.keiba.go.jp"
GRADE_MAP = {
    "g1": ("G1", "GⅠ"),
    "g2": ("G2", "GⅡ"),
    "g3": ("G3", "GⅢ"),
    "jpn1": ("JPN1", "JpnⅠ"),
    "jpn2": ("JPN2", "JpnⅡ"),
    "jpn3": ("JPN3", "JpnⅢ"),
}
DATE_RE = re.compile(r"^(\d{1,2})月(\d{1,2})日")
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})発走")
DISTANCE_RE = re.compile(r"(\d{3,4})m")
COURSE_RE = re.compile(r"^(\S+?)\s*[左右直]")

EVENT_FIELDS = [
    "year",
    "original_name",
    "chinese_name",
    "country_region",
    "racecourse",
    "grade_text",
    "normalized_grade",
    "surface",
    "distance_text",
    "eligibility_text",
    "race_datetime",
    "timezone_name",
    "local_date",
    "local_start_time",
    "priority",
    "status",
    "visibility_status",
    "data_quality_status",
    "is_featured",
    "source_refs",
    "notes",
    "aliases",
    "alias_language",
]


def _fetch_page(url: str, path: Path, *, allow_network: bool, timeout: int) -> bytes:
    validate_https_url(url, allowed_hosts=("keiba.go.jp",))
    if path.exists():
        return path.read_bytes()
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    before_network_request(url)
    body, _response = fetch_https(
        url,
        allowed_hosts=("keiba.go.jp",),
        timeout=timeout,
        headers={"User-Agent": "UmaFansBot/1.0", "Accept-Language": "ja,en;q=0.8"},
    )
    write_source_cache(path, body, source_url=url)
    return body


def _parse_racelist(html: str, *, year: int) -> list[dict]:
    """解析全年列表，返回含全等级序号（ordinal，1 起）的全部赛事。"""
    soup = BeautifulSoup(html, "html.parser")
    events = []
    ordinal = 0
    for month_block in soup.select("div.month"):
        heading = month_block.find(["h3", "h2"])
        heading_text = heading.get_text(strip=True) if heading else ""
        month_match = re.search(r"(\d{1,2})月", heading_text)
        if not month_match:
            continue
        month = int(month_match.group(1))
        for item in month_block.select("li.js-item"):
            grade_tag = item.find("h4")
            link = item.find("a", href=True)
            if not grade_tag or not link:
                continue
            grade_class = next(
                (key for key in GRADE_MAP if key in set(grade_tag.get("class", []))),
                None,
            )
            if grade_class is None:
                continue
            ordinal += 1
            texts = [p.get_text(strip=True) for p in item.find_all("p")]
            date_text = texts[0] if texts else ""
            course_text = texts[-1] if texts else ""
            date_match = DATE_RE.match(date_text)
            if not date_match:
                continue
            local_date = date(year, month, int(date_match.group(2))).isoformat()
            time_match = TIME_RE.search(course_text)
            distance_match = DISTANCE_RE.search(course_text)
            course_match = COURSE_RE.match(course_text)
            normalized_grade, grade_text = GRADE_MAP[grade_class]
            events.append(
                {
                    "original_name": grade_tag.get_text(strip=True),
                    "local_date": local_date,
                    "ordinal": ordinal,
                    "slug": f"nar-dirt-{year}-{month:02d}{int(date_match.group(2)):02d}-{ordinal:02d}",
                    "local_start_time": (
                        f"{int(time_match.group(1)):02d}:{time_match.group(2)}" if time_match else ""
                    ),
                    "racecourse": course_match.group(1) if course_match else "",
                    "distance_text": f"{distance_match.group(1)}m" if distance_match else "",
                    "grade_text": grade_text,
                    "normalized_grade": normalized_grade,
                    "grade_key": grade_class,
                    "detail_url": link["href"],
                }
            )
    return events


def prepare_racelist_events(args) -> dict:
    grades = {part.strip().casefold() for part in str(args.grades).split(",") if part.strip()}
    unknown = grades - set(GRADE_MAP)
    if unknown:
        raise ValueError(f"未知等级筛选：{sorted(unknown)}")
    year = int(args.year)
    as_of = str(getattr(args, "as_of_date", "") or date.today().isoformat())

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if getattr(args, "racelist_html", ""):
        html_path = Path(args.racelist_html)
        body = html_path.read_bytes()
        source_url = str(html_path)
    else:
        source_url = RACELIST_URL.format(year=year)
        html_path = output_path.parent / "sources" / f"nar_racelist_{year}.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        body = _fetch_page(
            source_url,
            html_path,
            allow_network=bool(getattr(args, "allow_network", False)),
            timeout=int(getattr(args, "timeout_seconds", 30)),
        )

    events = _parse_racelist(body.decode("utf-8", errors="replace"), year=year)
    scoped = [event for event in events if event["grade_key"] in grades]
    if not scoped:
        raise RuntimeError(f"NAR 年度列表页没有解析到任何目标等级赛事：{source_url}")

    chinese_map: dict[str, str] = {}
    chinese_map_path = str(getattr(args, "chinese_map", "") or "")
    if chinese_map_path:
        with Path(chinese_map_path).open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                name = (row.get("original_name") or "").strip()
                if name:
                    chinese_map[name] = (row.get("chinese_name") or "").strip()

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["slug", *EVENT_FIELDS])
        writer.writeheader()
        for event in scoped:
            detail_url = event["detail_url"]
            if detail_url.startswith("/"):
                detail_url = f"{KEIBA_BASE}{detail_url}"
            writer.writerow(
                {
                    "slug": event["slug"],
                    "year": year,
                    "original_name": event["original_name"],
                    "chinese_name": chinese_map.get(event["original_name"], ""),
                    "country_region": "japan",
                    "racecourse": event["racecourse"],
                    "grade_text": event["grade_text"],
                    "normalized_grade": event["normalized_grade"],
                    "surface": "dirt",
                    "distance_text": event["distance_text"],
                    "eligibility_text": "",
                    "race_datetime": "",
                    "timezone_name": "Asia/Tokyo",
                    "local_date": event["local_date"],
                    "local_start_time": event["local_start_time"],
                    "priority": "P1",
                    "status": "finished" if event["local_date"] <= as_of else "scheduled",
                    "visibility_status": "published",
                    "data_quality_status": "partial",
                    "is_featured": "",
                    "source_refs": json.dumps(
                        {"list": RACELIST_URL.format(year=year), "detail": detail_url, "source_provider": "nar"},
                        ensure_ascii=False,
                    ),
                    "notes": "",
                    "aliases": "",
                    "alias_language": "",
                }
            )
    return {
        "source": source_url,
        "year": year,
        "grades": sorted(grades),
        "events": len(scoped),
        "events_all_grades": len(events),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--grades", default="jpn1", help="逗号分隔，如 jpn1 或 jpn1,g1")
    parser.add_argument("--output", required=True)
    parser.add_argument("--racelist-html", default="", help="离线页面路径（默认按年份抓官方页）")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--as-of-date", default="", help="status 判定基准日（默认今天）")
    parser.add_argument("--chinese-map", default="", help="可选：original_name,chinese_name 映射 CSV")
    args = parser.parse_args()
    summary = prepare_racelist_events(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

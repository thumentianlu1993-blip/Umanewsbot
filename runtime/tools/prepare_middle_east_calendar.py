#!/usr/bin/env python3
"""中东地区赛历解析：Dubai Racing Carnival PDF 文本、ERA 整日场头、JCSA 赛日卡。

产出 calendar timeline 行（JSONL），schema 对齐 prepare_racing_australia_graded_catalog.py
的 FIELDS 并补充 season_label / race_number。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date as date_type
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup


ALLOWED_HOSTS = (
    "drcwebblob.blob.core.windows.net",
    "dubairacingclub.com",
    "www.dubairacingclub.com",
    "meydanracing.com",
    "www.meydanracing.com",
    "emiratesracing.com",
    "www.emiratesracing.com",
    "jcsa.sa",
    "www.jcsa.sa",
)

# timeline 行字段（对齐 racing_australia graded catalog schema，另加 race_number 与 source_refs 证据）
FIELDS = (
    "record_type", "country_region", "country", "year", "series_key",
    "canonical_name_original", "original_name", "source_race_name",
    "grade_text", "racecourse", "local_date", "distance_text", "surface",
    "expectation_status", "source_scope", "discipline", "race_number",
    "raw_source_cache_path", "raw_source_cache_sha256", "raw_source_url",
    "season_label", "source_refs",
)

WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
MONTHS = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}
WEEKDAY_RE = "|".join(WEEKDAYS)
DAY_HEADER_RE = re.compile(
    rf"^(?P<weekday>{WEEKDAY_RE}),\s+(?P<day>\d{{1,2}})\s+(?P<month>[A-Z]+)\s+(?P<year>\d{{4}})(?:\s+(?P<label>.*))?$"
)
DAY_HEADER_INTERLEAVED_RE = re.compile(
    rf"^(?P<weekday>{WEEKDAY_RE}),\s+(?P<day>\d{{1,2}})\s+(?P<month>[A-Z0-9]+)\s+(?P<year>\d{{4}})(?:\s+(?P<label>.*))?$"
)
DRC_RACE_RE = re.compile(
    r"^(?P<name>.+?)\s+-\s+(?:(?P<sex>Fillies(?:\s+&\s+Mares)?)\s+)?Group\s+(?P<grade>[123])\s+"
    r"(?P<age>\dYO\+?)\s+(?P<distance>\d+)m\s+(?P<surface>Dirt|Turf)\s+AED\s+(?P<prize>[\d,]+)\s*$"
)
# 2025-26 Carnival 官方口径：16 赛日 = G1×2/G2×10/G3×12
DRC_EXPECTED_COUNTS = {"2025-2026": {"days": 16, "G1": 2, "G2": 10, "G3": 12}}
DRC_RACECOURSE = "Meydan"

ERA_HEADING_RE = re.compile(r"^Race\s+(\d+)\s+-\s+(?P<name>.+)$")
ERA_TRACK_ICON_RE = re.compile(r"/assets/tracks/(?P<course>[a-z0-9-]+?)--(?P<distance>\d+)m")
ERA_RACECOURSE_NAMES = {"meydan": "Meydan", "jebel-ali": "Jebel Ali"}
ERA_ARABIAN_DISCIPLINES = {"purebred arabian"}

JCSA_RACECOURSE = "King Abdulaziz Racetrack"
# 沙特杯赛制国际赛清单；级别以 ICS 2026 认定为准（卡面 info 行可能缺级别，如 Red Sea Turf）
SAUDI_INTERNATIONAL_RACES = (
    {"key": "custodian-of-the-two-holy-mosques-cup", "canonical": "Custodian of the Two Holy Mosques Cup",
     "tokens": {"custodian", "two", "holy", "mosques", "cup"}, "grade": "G3"},
    {"key": "saudi-cup", "canonical": "Saudi Cup",
     "tokens": {"saudi", "cup"}, "grade": "G1"},
    {"key": "neom-turf-cup", "canonical": "Neom Turf Cup",
     "tokens": {"neom", "turf", "cup"}, "grade": "G1"},
    {"key": "riyadh-dirt-sprint", "canonical": "Riyadh Dirt Sprint",
     "tokens": {"riyadh", "dirt", "sprint"}, "grade": "G2"},
    {"key": "1351-turf-sprint", "canonical": "1351 Turf Sprint",
     "tokens": {"1351", "turf", "sprint"}, "grade": "G2"},
    {"key": "red-sea-turf", "canonical": "Red Sea Turf",
     "tokens": {"red", "sea", "turf"}, "grade": "G2"},
    {"key": "saudi-derby", "canonical": "Saudi Derby",
     "tokens": {"saudi", "derby"}, "grade": "G3"},
)

COUNTRY_SUFFIX_RE = re.compile(r"\s*\([A-Z]{2,3}\)\s*$")


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timeline_row(**kwargs) -> dict:
    row = {field: "" for field in FIELDS}
    row["source_refs"] = {}
    row.update(kwargs)
    return row


# ---------------------------------------------------------------- DRC PDF 文本


def _collapse_doubled_line(line: str) -> str:
    """叠字去重：PDF 加粗叠印导致每个字符连续重复两次，折叠相邻重复对。"""
    return re.sub(r"(.)\1", r"\1", line)


def _parse_drc_day_header(line: str) -> tuple[date_type | None, str]:
    """识别赛日头，返回 (日期, 赛日标签)。依次尝试：正常、日历网格数字交织、叠字。"""
    match = DAY_HEADER_RE.match(line)
    if match and match.group("month") in MONTHS:
        parsed = date_type(int(match.group("year")), MONTHS[match.group("month")], int(match.group("day")))
        return parsed, _collapse(match.group("label") or "")
    interleaved = DAY_HEADER_INTERLEAVED_RE.match(line)
    if interleaved:
        month = re.sub(r"\d", "", interleaved.group("month"))
        if month in MONTHS:
            parsed = date_type(int(interleaved.group("year")), month and MONTHS[month], int(interleaved.group("day")))
            return parsed, _collapse(interleaved.group("label") or "")
    collapsed = _collapse_doubled_line(line)
    if collapsed != line:
        deduped = DAY_HEADER_RE.match(collapsed)
        if deduped and deduped.group("month") in MONTHS:
            parsed = date_type(int(deduped.group("year")), MONTHS[deduped.group("month")], int(deduped.group("day")))
            return parsed, _collapse(deduped.group("label") or "")
    return None, ""


def parse_drc_schedule_text(text: str, *, season: str) -> list[dict]:
    """解析 Dubai Racing Carnival 赛历 PDF 文本，只产 Group 1/2/3 行（Listed 跳过）。"""
    rows: list[dict] = []
    days: set[str] = set()
    current_date: date_type | None = None
    current_day_label = ""
    for raw_line in text.splitlines():
        line = _collapse(raw_line)
        if not line or line.startswith("===== PAGE"):
            continue
        parsed_date, day_label = _parse_drc_day_header(line)
        if parsed_date is not None:
            current_date = parsed_date
            current_day_label = day_label
            days.add(parsed_date.isoformat())
            continue
        race = DRC_RACE_RE.match(line)
        if race is None:
            continue
        if current_date is None:
            raise RuntimeError(f"DRC 赛行缺少赛日头上下文：{line}")
        name = _collapse(race.group("name"))
        grade = f"G{race.group('grade')}"
        rows.append(
            _timeline_row(
                record_type="timeline",
                country_region="middle_east",
                country="uae",
                year=current_date.year,
                series_key=f"uae-{_slugify(name)}",
                canonical_name_original=name,
                original_name=name,
                source_race_name=line,
                grade_text=grade,
                racecourse=DRC_RACECOURSE,
                local_date=current_date.isoformat(),
                distance_text=race.group("distance"),
                surface=race.group("surface").lower(),
                expectation_status="scheduled",
                source_scope="drc_carnival_race_schedule",
                discipline="flat",
                season_label=season,
                source_refs={
                    "source_language": "en",
                    "conditions": race.group("age") + (" " + race.group("sex") if race.group("sex") else ""),
                    "prize_text": f"AED {race.group('prize')}",
                    "day_label": current_day_label,
                },
            )
        )
    expected = DRC_EXPECTED_COUNTS.get(season)
    if expected is not None:
        grade_counts = {grade: sum(row["grade_text"] == grade for row in rows) for grade in ("G1", "G2", "G3")}
        actual = {"days": len(days), **grade_counts}
        if actual != expected:
            raise RuntimeError(f"DRC {season} 计数自校验失败：{actual} != {expected}")
    return rows


# ---------------------------------------------------------------- ERA 整日场头


def _era_header_blocks(html: str) -> list[tuple[str, str, object]]:
    soup = BeautifulSoup(html, "lxml")
    blocks = []
    for h2 in soup.find_all("h2", class_="racecard__heading"):
        heading = _collapse(h2.get_text(" ", strip=True))
        match = ERA_HEADING_RE.match(heading)
        if match:
            blocks.append((match.group(1), _collapse(match.group("name")), h2.parent))
    return blocks


def parse_era_day_headers(html: str, *, date: str) -> list[dict]:
    """从 ERA /ajax/racecard-results-all 整日页提取 Group 1/2/3 场头。

    阿拉伯马赛事（如 Dubai Kahayla Classic）ICS UAE 章节不收录，跳过。
    """
    date_type.fromisoformat(date)
    rows: list[dict] = []
    for race_number, source_name, container in _era_header_blocks(html):
        items = [
            _collapse(node.get_text(" ", strip=True))
            for node in container.select(".racecard__stats-list--primary .racecard__stats-list-item")
        ]
        grade = next((item for item in items if re.fullmatch(r"Group [123]", item)), "")
        if not grade:
            continue
        discipline_raw = next(
            (item for item in items if item.lower() in {"thoroughbred", "purebred arabian"}), ""
        )
        if discipline_raw.lower() in ERA_ARABIAN_DISCIPLINES:
            continue
        surface = next((item for item in items if item in {"DIRT", "TURF"}), "").lower()
        track_icon = container.find("img", src=ERA_TRACK_ICON_RE)
        icon_match = ERA_TRACK_ICON_RE.search(track_icon["src"]) if track_icon else None
        racecourse = ""
        distance = ""
        if icon_match:
            course_key = icon_match.group("course")
            racecourse = ERA_RACECOURSE_NAMES.get(course_key, course_key.replace("-", " ").title())
            distance = icon_match.group("distance")
        canonical = re.split(r"\s+Sponsored by\s+", source_name, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        rows.append(
            _timeline_row(
                record_type="timeline",
                country_region="middle_east",
                country="uae",
                year=int(date[:4]),
                series_key=f"uae-{_slugify(canonical)}",
                canonical_name_original=canonical,
                original_name=canonical,
                source_race_name=source_name,
                grade_text=grade.replace("Group ", "G"),
                racecourse=racecourse,
                local_date=date,
                distance_text=distance,
                surface=surface,
                expectation_status="held",
                source_scope="era_racecard_results_all",
                discipline="flat",
                race_number=race_number,
                source_refs={
                    "source_language": "en",
                    "race_time": next((item for item in items if re.fullmatch(r"\d{2}:\d{2}", item)), ""),
                    "conditions": next((item for item in items if item.lower().startswith("for ")), ""),
                    "prize_text": next((item for item in items if item.startswith("AED")), ""),
                    "discipline_raw": discipline_raw,
                },
            )
        )
    return rows


# ---------------------------------------------------------------- JCSA 赛日卡


def _name_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (value or "").lower()))


def _match_saudi_international_race(card_name: str) -> dict | None:
    tokens = _name_tokens(card_name)
    for race in SAUDI_INTERNATIONAL_RACES:
        if race["tokens"] <= tokens:
            return race
    return None


def jcsa_missing_international_races(rows: list[dict]) -> list[str]:
    """清单赛事缺席名单：写进 summary 供人工挂账，不 raise。"""
    found = {row["series_key"] for row in rows}
    return [race["canonical"] for race in SAUDI_INTERNATIONAL_RACES if f"saudi-{race['key']}" not in found]


def parse_jcsa_meeting_card(html: str, *, date: str) -> list[dict]:
    """解析 JCSA /api/meeting-info/en/{yyyymmdd}/0/All/False 赛日卡，只保留国际赛清单赛事。"""
    date_type.fromisoformat(date)
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    for item in soup.find_all("li", class_="meeting-info-item"):
        link = item.find("a", href=re.compile(r"^/en/races/\d{8}/\d+$"))
        headings = item.find_all("h3")
        if link is None or len(headings) < 2:
            continue
        race_number = re.sub(r"\D", "", headings[0].get_text(strip=True))
        card_name = _collapse(headings[1].get_text(" ", strip=True))
        race = _match_saudi_international_race(card_name)
        if race is None:
            continue
        stats: dict[str, str] = {}
        for img in item.select(".meeting-info-detail img"):
            kind = Path(urlparse(img.get("src") or "").path).stem
            holder = img.find_parent("div")
            text = _collapse(holder.get_text(" ", strip=True)) if holder else ""
            if kind and text:
                stats[kind] = text
        info = stats.get("info", "")
        distance_match = re.search(r"(\d+)m\s+(Dirt|Turf)", info)
        distance = distance_match.group(1) if distance_match else ""
        surface = distance_match.group(2).lower() if distance_match else ""
        held = any(node.get_text(strip=True) == "Results" for node in item.select(".meeting-info-summary div"))
        rows.append(
            _timeline_row(
                record_type="timeline",
                country_region="middle_east",
                country="saudi_arabia",
                year=int(date[:4]),
                series_key=f"saudi-{race['key']}",
                canonical_name_original=race["canonical"],
                original_name=race["canonical"],
                source_race_name=card_name,
                grade_text=race["grade"],
                racecourse=JCSA_RACECOURSE,
                local_date=date,
                distance_text=distance,
                surface=surface,
                expectation_status="held" if held else "scheduled",
                source_scope="jcsa_meeting_info",
                discipline="flat",
                race_number=race_number,
                source_refs={
                    "source_language": "en",
                    "race_time": stats.get("clock", ""),
                    "prize_text": stats.get("money", ""),
                    "info_raw": info,
                    "grade_source": "ics_whitelist",
                },
            )
        )
    rows.sort(key=lambda row: int(row["race_number"] or 0))
    keys = [row["series_key"] for row in rows]
    if len(keys) != len(set(keys)):
        raise RuntimeError("JCSA 赛日卡白名单匹配出现重复 series_key")
    return rows


# ---------------------------------------------------------------- CLI


def _parse_source(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise RuntimeError(f"来源必须使用 URL=PATH 形式：{spec}")
    # URL 可能自带 query 等号（?date=...），按最后一个等号切分
    url, raw_path = spec.rsplit("=", 1)
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise RuntimeError(f"来源 URL 不在中东白名单内：{url}")
    path = Path(raw_path).resolve(strict=True)
    if not path.is_file():
        raise RuntimeError(f"来源文件不存在：{path}")
    return url, path


def _enrich_source_identity(rows: list[dict], *, url: str, path: Path) -> None:
    for row in rows:
        row["raw_source_cache_path"] = str(path)
        row["raw_source_cache_sha256"] = _sha256(path)
        row["raw_source_url"] = url


def _drc_season_from_source(url: str, path: Path) -> str:
    match = re.search(r"(20\d{2})-(20\d{2})", f"{url} {path.name}")
    if not match:
        raise RuntimeError(f"无法从 DRC 来源推断赛季：{url}")
    return f"{match.group(1)}-{match.group(2)}"


def _era_date_from_url(url: str) -> str:
    date = (parse_qs(urlparse(url).query).get("date") or [""])[0]
    date_type.fromisoformat(date)
    return date


def _jcsa_date_from_url(url: str) -> str:
    match = re.search(r"/api/meeting-info/(?:en|ar)/(\d{8})/", urlparse(url).path)
    if not match:
        raise RuntimeError(f"JCSA 来源 URL 缺少会议日期：{url}")
    raw = match.group(1)
    return date_type(int(raw[:4]), int(raw[4:6]), int(raw[6:8])).isoformat()


def build_timeline(args) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    summary = {
        "source": "middle_east_calendar",
        "sources": [],
        "row_counts": {},
        "jcsa_missing_international_races": [],
    }
    for spec in args.drc_txt or []:
        url, path = _parse_source(spec)
        season = _drc_season_from_source(url, path)
        parsed = parse_drc_schedule_text(path.read_text(encoding="utf-8"), season=season)
        _enrich_source_identity(parsed, url=url, path=path)
        rows.extend(parsed)
        summary["sources"].append({"kind": "drc", "url": url, "path": str(path), "season": season})
        summary["row_counts"][f"drc:{season}"] = len(parsed)
    for spec in args.era_html or []:
        url, path = _parse_source(spec)
        date = _era_date_from_url(url)
        parsed = parse_era_day_headers(path.read_text(encoding="utf-8"), date=date)
        _enrich_source_identity(parsed, url=url, path=path)
        rows.extend(parsed)
        summary["sources"].append({"kind": "era", "url": url, "path": str(path), "date": date})
        summary["row_counts"][f"era:{date}"] = len(parsed)
    for spec in args.jcsa_html or []:
        url, path = _parse_source(spec)
        date = _jcsa_date_from_url(url)
        parsed = parse_jcsa_meeting_card(path.read_text(encoding="utf-8"), date=date)
        _enrich_source_identity(parsed, url=url, path=path)
        rows.extend(parsed)
        missing = jcsa_missing_international_races(parsed)
        summary["jcsa_missing_international_races"].extend(
            {"date": date, "race_name": name} for name in missing
        )
        summary["sources"].append({"kind": "jcsa", "url": url, "path": str(path), "date": date})
        summary["row_counts"][f"jcsa:{date}"] = len(parsed)
    rows.sort(key=lambda row: (row["local_date"], row["country"], int(row["race_number"] or 0), row["series_key"]))
    jsonl_path = output_dir / "middle_east_calendar_timeline.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary["rows"] = len(rows)
    summary["output"] = str(jsonl_path)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drc-txt", action="append", help="DRC 赛历 PDF 文本，URL=PATH，可多个")
    parser.add_argument("--era-html", action="append", help="ERA 整日场头页，URL=PATH，可多个")
    parser.add_argument("--jcsa-html", action="append", help="JCSA 赛日卡，URL=PATH，可多个")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(build_timeline(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

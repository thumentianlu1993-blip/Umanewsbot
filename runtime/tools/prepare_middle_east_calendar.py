#!/usr/bin/env python3
"""中东地区赛历解析：Dubai Racing Carnival PDF 文本/手册网格、ERA 整日场头、JCSA 赛日卡。

产出 calendar timeline 行（JSONL），schema 对齐 prepare_racing_australia_graded_catalog.py
的 FIELDS 并补充 season_label / race_number。series_key 使用 ICS 基线同口径的
国家全名前缀（united-arab-emirates-* / saudi-arabia-*）。
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
# 手册赛程网格使用缩写月份（FRIDAY• 8 NOV 2024）
MONTHS_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
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
# Carnival 官方口径自校验（PDF/手册均载明 "consists of 16 race meetings"）：
# 2024-25 = 2025-26 = 16 赛日，G1×2/G2×10/G3×12
DRC_EXPECTED_COUNTS = {
    "2024-2025": {"days": 16, "G1": 2, "G2": 10, "G3": 12},
    "2025-2026": {"days": 16, "G1": 2, "G2": 10, "G3": 12},
}
DRC_RACECOURSE = "Meydan"

# 手册赛程网格（词坐标 JSONL）解析常量：列内词距 ~2pt，列间距 ~130pt
GRID_WORD_GAP = 20.0
GRID_LINE_TOP_TOLERANCE = 3.0
GRID_COL_TOLERANCE = 12.0
GRID_DAY_HEADER_RE = re.compile(
    r"^(?P<weekday>FRIDAY|SATURDAY)•\s*(?P<day>\d{1,2})\s+(?P<month>[A-Z]+)\s+(?P<year>\d{4})$"
)
GRID_GROUP_RE = re.compile(r"^(?P<name>.+?)\s*\(Group\s+(?P<grade>[123])\)\s*(?P<trail>.*)$")
GRID_COND_RE = re.compile(
    r"^(?P<age>\dYO\+?)\s*\|\s*(?P<distance>\d+)m\s*\|\s*(?P<surface>Dirt|Turf)\s*\|\s*AED\s*(?P<prize>[\d,]+)$"
)

ERA_HEADING_RE = re.compile(r"^Race\s+(\d+)\s+-\s+(?P<name>.+)$")
ERA_TRACK_ICON_RE = re.compile(r"/assets/tracks/(?P<course>[a-z0-9-]+?)--(?P<distance>\d+)m")
ERA_RACECOURSE_NAMES = {"meydan": "Meydan", "jebel-ali": "Jebel Ali"}
ERA_ARABIAN_DISCIPLINES = {"purebred arabian"}

JCSA_RACECOURSE = "King Abdulaziz Racetrack"
# 沙特杯赛制国际赛清单（身份白名单）。级别不从本表取：年代不同级别会变
# （如 Neom Turf Cup 2025=G2 / 2026=G1），一律以卡面级别字样为准
SAUDI_INTERNATIONAL_RACES = (
    {"key": "custodian-of-the-two-holy-mosques-cup", "canonical": "Custodian of the Two Holy Mosques Cup",
     "tokens": {"custodian", "two", "holy", "mosques", "cup"}},
    {"key": "saudi-cup", "canonical": "Saudi Cup",
     "tokens": {"saudi", "cup"}},
    {"key": "neom-turf-cup", "canonical": "Neom Turf Cup",
     "tokens": {"neom", "turf", "cup"}},
    {"key": "riyadh-dirt-sprint", "canonical": "Riyadh Dirt Sprint",
     "tokens": {"riyadh", "dirt", "sprint"}},
    {"key": "1351-turf-sprint", "canonical": "1351 Turf Sprint",
     "tokens": {"1351", "turf", "sprint"}},
    {"key": "red-sea-turf", "canonical": "Red Sea Turf",
     "tokens": {"red", "sea", "turf"}},
    {"key": "saudi-derby", "canonical": "Saudi Derby",
     "tokens": {"saudi", "derby"}},
)
# 同名国内赛/阿拉伯马赛事排除：如 "The Custodian of the Two Holy Mosques Cup (Local Gr.1)"
JCSA_EXCLUDE_RE = re.compile(r"\(Local|\(Domestic|Purebred Arabian", re.IGNORECASE)
# 卡面级别字样：2025 年为前缀（"G1 Saudi Cup"、"( Gr.3) ..."），2026 年为后缀（"Saudi Cup (G1)"）
JCSA_NAME_GRADE_RES = (
    re.compile(r"\(\s*Group\s+([123])\s*\)"),
    re.compile(r"\(\s*G\s*([123])\s*\)"),
    re.compile(r"^G([123])\s"),
    re.compile(r"^\(\s*Gr\.?\s*([123])\s*\)"),
)
JCSA_INFO_GRADE_RE = re.compile(r"(?<!Domestic )Group ([123])")

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


def _check_drc_counts(rows: list[dict], days: set[str], *, season: str) -> None:
    expected = DRC_EXPECTED_COUNTS.get(season)
    if expected is None:
        return
    grade_counts = {grade: sum(row["grade_text"] == grade for row in rows) for grade in ("G1", "G2", "G3")}
    actual = {"days": len(days), **grade_counts}
    if actual != expected:
        raise RuntimeError(f"DRC {season} 计数自校验失败：{actual} != {expected}")


def _drc_timeline_row(*, name, grade, race_date, distance, surface, conditions, prize_text,
                      season, day_label, source_kind, source_race_name) -> dict:
    return _timeline_row(
        record_type="timeline",
        country_region="middle_east",
        country="uae",
        year=race_date.year,
        series_key=f"united-arab-emirates-{_slugify(name)}",
        canonical_name_original=name,
        original_name=name,
        source_race_name=source_race_name,
        grade_text=grade,
        racecourse=DRC_RACECOURSE,
        local_date=race_date.isoformat(),
        distance_text=distance,
        surface=surface.lower(),
        expectation_status="held",
        source_scope="official_calendar",
        discipline="flat",
        season_label=season,
        source_refs={
            "source_language": "en",
            "source_kind": source_kind,
            "conditions": conditions,
            "prize_text": prize_text,
            "day_label": day_label,
        },
    )


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
        rows.append(
            _drc_timeline_row(
                name=name,
                grade=f"G{race.group('grade')}",
                race_date=current_date,
                distance=race.group("distance"),
                surface=race.group("surface"),
                conditions=race.group("age") + (" " + race.group("sex") if race.group("sex") else ""),
                prize_text=f"AED {race.group('prize')}",
                season=season,
                day_label=current_day_label,
                source_kind="drc_carnival_race_schedule",
                source_race_name=line,
            )
        )
    _check_drc_counts(rows, days, season=season)
    return rows


# ---------------------------------------------------------- DRC 手册赛程网格


def _grid_lines(words: list[dict]) -> list[list[dict]]:
    """按 (page, top) 聚词成行（top 容差 3pt，兼容同一赛日头行内微小纵向偏移）。"""
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda w: (w["page"], w["top"], w["x0"])):
        if lines and lines[-1][0]["page"] == word["page"] and abs(lines[-1][0]["top"] - word["top"]) <= GRID_LINE_TOP_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def _grid_segments(line_words: list[dict]) -> list[tuple[float, str]]:
    """行内按词间距 >20pt 切段，返回 [(起始 x0, 文本)]。"""
    segments: list[tuple[float, str]] = []
    for word in sorted(line_words, key=lambda w: w["x0"]):
        if segments and word["x0"] - segments[-1][2] <= GRID_WORD_GAP:
            segments[-1][1] += " " + word["text"]
            segments[-1][2] = word["x1"]
        else:
            segments.append([word["x0"], word["text"], word["x1"]])
    return [(seg[0], seg[1]) for seg in segments]


def parse_drc_brochure_grid(grid_text: str, *, season: str) -> list[dict]:
    """解析 Carnival 手册赛程网格（pdfplumber 词坐标 JSONL），只产 Group 1/2/3 行。

    网格为三列赛日布局：赛日头段（FRIDAY• 8 NOV 2024）定义列锚点，后续段按起始 x0
    归入最近左侧锚点列；每列内部 Group 赛名段与其条件段严格交替，缺条件段即 fail closed。
    """
    words = [json.loads(line) for line in grid_text.splitlines() if line.strip()]
    blocks: list[dict] = []
    for line_words in _grid_lines(words):
        segments = _grid_segments(line_words)
        headers = []
        for x0, text in segments:
            match = GRID_DAY_HEADER_RE.match(text)
            month = match.group("month") if match else ""
            month_number = MONTHS.get(month) or MONTHS_ABBR.get(month)
            if match and month_number:
                parsed = date_type(int(match.group("year")), month_number, int(match.group("day")))
                headers.append({"x0": x0, "date": parsed})
        if headers:
            blocks.append({"columns": headers, "segments": []})
        elif blocks:
            blocks[-1]["segments"].extend(segments)
    rows: list[dict] = []
    days: set[str] = set()
    for block in blocks:
        anchors = sorted(column["x0"] for column in block["columns"])
        streams: dict[float, list[str]] = {anchor: [] for anchor in anchors}
        for x0, text in block["segments"]:
            eligible = [anchor for anchor in anchors if anchor <= x0 + GRID_COL_TOLERANCE]
            if not eligible:
                continue
            streams[max(eligible)].append(text)
        for column in block["columns"]:
            race_date = column["date"]
            days.add(race_date.isoformat())
            pending: re.Match | None = None
            for text in streams[column["x0"]]:
                group = GRID_GROUP_RE.match(text)
                if group is not None:
                    if pending is not None:
                        raise RuntimeError(f"网格赛名段缺少条件段：{pending.group(0)} @ {race_date}")
                    pending = group
                    continue
                if pending is None:
                    continue
                condition = GRID_COND_RE.match(text)
                if condition is None:
                    raise RuntimeError(f"网格赛名段缺少条件段：{pending.group(0)} @ {race_date}，后续段：{text}")
                name = _collapse(pending.group("name"))
                trail = pending.group("trail").lstrip("- ").strip()
                conditions = condition.group("age") + (" " + trail if trail else "")
                rows.append(
                    _drc_timeline_row(
                        name=name,
                        grade=f"G{pending.group('grade')}",
                        race_date=race_date,
                        distance=condition.group("distance"),
                        surface=condition.group("surface"),
                        conditions=conditions,
                        prize_text=f"AED {condition.group('prize')}",
                        season=season,
                        day_label="",
                        source_kind="drc_carnival_brochure_grid",
                        source_race_name=pending.group(0),
                    )
                )
                pending = None
            if pending is not None:
                raise RuntimeError(f"网格赛名段缺少条件段：{pending.group(0)} @ {race_date}")
    _check_drc_counts(rows, days, season=season)
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


def _era_season_label(date: str) -> str:
    """ERA 整日页归 UAE 赛季： DWC/Carnival 赛季跨年至次年 3-4 月（如 2025-04-05 -> 2024-2025）。"""
    parsed = date_type.fromisoformat(date)
    if parsed.month <= 6:
        return f"{parsed.year - 1}-{parsed.year}"
    return f"{parsed.year}-{parsed.year + 1}"


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
                series_key=f"united-arab-emirates-{_slugify(canonical)}",
                canonical_name_original=canonical,
                original_name=canonical,
                source_race_name=source_name,
                grade_text=grade.replace("Group ", "G"),
                racecourse=racecourse,
                local_date=date,
                distance_text=distance,
                surface=surface,
                expectation_status="held",
                source_scope="official_calendar",
                discipline="flat",
                race_number=race_number,
                season_label=_era_season_label(date),
                source_refs={
                    "source_language": "en",
                    "source_kind": "era_racecard_results_all",
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
    if JCSA_EXCLUDE_RE.search(card_name):
        return None
    tokens = _name_tokens(card_name)
    # 按词数从多到少匹配：避免 "... (Saudi Cup 2025 Qualifier)" 被 saudi-cup 抢占
    for race in sorted(SAUDI_INTERNATIONAL_RACES, key=lambda item: -len(item["tokens"])):
        if race["tokens"] <= tokens:
            return race
    return None


def _jcsa_grade(card_name: str, info: str) -> tuple[str, str] | tuple[None, None]:
    """级别只取卡面证据：名称字样优先，其次 info 行（排除 Domestic Group）。

    无任何国际分级标记时返回 (None, None)：资格预赛（如 "Riyadh Dirt Sprint
    Qualifier"）与无级别场次借此与国际清单赛区分。
    """
    for pattern in JCSA_NAME_GRADE_RES:
        match = pattern.search(card_name)
        if match:
            return f"G{match.group(1)}", "card_name"
    match = JCSA_INFO_GRADE_RE.search(info)
    if match:
        return f"G{match.group(1)}", "card_info"
    return None, None


def jcsa_missing_international_races(rows: list[dict]) -> list[str]:
    """清单赛事缺席名单：写进 summary 供人工挂账，不 raise。"""
    found = {row["series_key"] for row in rows}
    return [race["canonical"] for race in SAUDI_INTERNATIONAL_RACES if f"saudi-arabia-{race['key']}" not in found]


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
        grade, grade_source = _jcsa_grade(card_name, info)
        if grade is None:
            # 无国际分级标记：资格预赛/无级别场次不属国际清单赛，由 missing 清单挂账
            continue
        rows.append(
            _timeline_row(
                record_type="timeline",
                country_region="middle_east",
                country="saudi_arabia",
                year=int(date[:4]),
                series_key=f"saudi-arabia-{race['key']}",
                canonical_name_original=race["canonical"],
                original_name=race["canonical"],
                source_race_name=card_name,
                grade_text=grade,
                racecourse=JCSA_RACECOURSE,
                local_date=date,
                distance_text=distance,
                surface=surface,
                expectation_status="held" if held else "scheduled",
                source_scope="official_calendar",
                discipline="flat",
                race_number=race_number,
                source_refs={
                    "source_language": "en",
                    "source_kind": "jcsa_meeting_info",
                    "race_time": stats.get("clock", ""),
                    "prize_text": stats.get("money", ""),
                    "info_raw": info,
                    "grade_source": grade_source,
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
    for spec in args.drc_grid or []:
        url, path = _parse_source(spec)
        season = _drc_season_from_source(url, path)
        parsed = parse_drc_brochure_grid(path.read_text(encoding="utf-8"), season=season)
        _enrich_source_identity(parsed, url=url, path=path)
        rows.extend(parsed)
        summary["sources"].append({"kind": "drc_grid", "url": url, "path": str(path), "season": season})
        summary["row_counts"][f"drc_grid:{season}"] = len(parsed)
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
    parser.add_argument("--drc-grid", action="append", help="DRC 手册赛程网格词坐标 JSONL，URL=PATH，可多个")
    parser.add_argument("--era-html", action="append", help="ERA 整日场头页，URL=PATH，可多个")
    parser.add_argument("--jcsa-html", action="append", help="JCSA 赛日卡，URL=PATH，可多个")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(build_timeline(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

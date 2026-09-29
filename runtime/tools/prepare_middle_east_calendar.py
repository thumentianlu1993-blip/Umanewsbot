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
# 2026-27 Race Schedule Grid 为单页「赛日×距离」矩阵，17 列 = 16 个 Carnival 赛日 + DWC 赛日同版
# （DRC 官网："The 2026–2027 season features 16 thrilling meetings"）：
# Carnival G1×2/G2×10/G3×11 + DWC 赛日 G1×5/G2×3，合计 G1×7/G2×13/G3×11
# （纯血马 Group 赛口径，网格底部 Purebred Arabian 区不收录）。
DRC_EXPECTED_COUNTS = {
    "2024-2025": {"days": 16, "G1": 2, "G2": 10, "G3": 12},
    "2025-2026": {"days": 16, "G1": 2, "G2": 10, "G3": 12},
    "2026-2027": {"days": 17, "G1": 7, "G2": 13, "G3": 11},
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

# DRC Race Schedule Grid（2026-27 起）：单页「赛日列 × 距离带」矩阵的解析常量。
# 单元格文字为居中字母间距排版，相邻列同距离带的行纵向交错约 2.9pt；
# 表面不在文本中，由单元格底色编码（橙=dirt，两种绿色阶=turf）。
SCHEDULE_GRID_TOP_TOLERANCE = 1.6
SCHEDULE_GRID_GAP_SPLIT = 6.0
SCHEDULE_GRID_AXIS_X_MAX = 1005.0  # 右侧纵轴距离标签起点（左轴按 x0<70 滤除）
SCHEDULE_GRID_BAND_LABEL_X_MAX = 70.0
SCHEDULE_GRID_BAND_AMBIGUITY_MARGIN = 4.0
SCHEDULE_GRID_BAND_MAX_OFFSET = 40.0
SCHEDULE_GRID_SURFACE_COLORS = {
    (1.0, 0.753, 0.0): "dirt",
    (0.663, 0.855, 0.455): "turf",
    (0.573, 0.816, 0.314): "turf",
}
SCHEDULE_GRID_DATE_RE = re.compile(r"^(\d{2})-(Nov|Dec|Jan|Feb|Mar)$")
SCHEDULE_GRID_DAY_LABELS = ("Festive Friday", "Fashion Friday", "Emirates Super Saturday", "Dubai World Cup")
SCHEDULE_GRID_GRADE_RE = re.compile(r"^\((?:Group ([123])|Gr\.?\s?([123]))\)$")
SCHEDULE_GRID_LISTED_RE = re.compile(r"^\(Listed\)$")
SCHEDULE_GRID_PRIZE_RE = re.compile(r"^(?:AED|\$)\s?[\d.,]+$")
SCHEDULE_GRID_COND_RE = re.compile(
    r"^(?:\dYO'?s?\+?|Fillies(?: & Mares)?|Hcp\b.*|Benchmark\b.*|Maiden\b.*|Cond\.?\b.*|Purebred\b.*)$"
)
SCHEDULE_GRID_BAND_LABEL_RE = re.compile(r"^\d{3,4}$")

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
        # expectation 词表（held=应举办/cancelled/not_due/not_held）不含 scheduled；
        # 未来赛事的 scheduled 形态由物化层按 local_date > today 派生（event.status=scheduled + draft）
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


# ---------------------------------------------------------- DRC Race Schedule Grid


def _schedule_grid_segments(chars: list[dict]) -> list[dict]:
    """字符 -> 行（top 容差 1.6pt，分开相邻列约 2.9pt 的纵向交错）-> 段（行内间隔 >6pt 切段）。"""
    lines: list[list[dict]] = []
    for char in sorted(chars, key=lambda c: (c["page"], c["top"], c["x0"])):
        if (
            lines
            and lines[-1][0]["page"] == char["page"]
            and abs(lines[-1][0]["top"] - char["top"]) <= SCHEDULE_GRID_TOP_TOLERANCE
        ):
            lines[-1].append(char)
        else:
            lines.append([char])
    segments: list[dict] = []
    for line_chars in lines:
        run: list[dict] = []
        prev = None
        for char in sorted(line_chars, key=lambda c: c["x0"]):
            if prev is not None and run and char["x0"] - prev["x1"] > SCHEDULE_GRID_GAP_SPLIT:
                text = _collapse("".join(c["text"] for c in run))
                if text:
                    segments.append({"top": run[0]["top"], "x0": run[0]["x0"], "x1": run[-1]["x1"], "text": text})
                run = []
            run.append(char)
            prev = char
        if run:
            text = _collapse("".join(c["text"] for c in run))
            if text:
                segments.append({"top": run[0]["top"], "x0": run[0]["x0"], "x1": run[-1]["x1"], "text": text})
    return segments


def _schedule_grid_surface(rects: list[dict], segment: dict) -> str:
    """单元格表面取赛名行锚点处底色；无填充或未知颜色均 fail closed（不臆造 surface）。"""
    px, py = segment["x0"] + 2.0, segment["top"] + 1.0
    hits = [
        r for r in rects
        if r["x0"] <= px <= r["x1"] and r["top"] <= py <= r["bottom"]
    ]
    if not hits:
        raise RuntimeError(f"Group 赛单元格无底色填充证据：{segment['text']!r} @ top={segment['top']}")
    surfaces = set()
    unknown = set()
    for hit in hits:
        color = hit["color"]
        key = (color,) if isinstance(color, (int, float)) else tuple(color)
        if key in SCHEDULE_GRID_SURFACE_COLORS:
            surfaces.add(SCHEDULE_GRID_SURFACE_COLORS[key])
        else:
            unknown.add(key)
    if len(surfaces) == 1:
        return next(iter(surfaces))
    raise RuntimeError(f"Group 赛单元格底色无法判定表面：{segment['text']!r} colors={sorted(map(str, unknown))}")


def parse_drc_schedule_grid(payload: str, *, season: str) -> list[dict]:
    """解析 DRC Race Schedule Grid 派生对象 JSONL（kind=char/rect 行），只产纯血马 Group 1/2/3 行。

    结构：列头三行（马场名 Meydan 定列中心 / 日期 dd-Mmm / Turf rail 位置），左右纵轴为距离带
    标签；单元格纵向堆叠 赛名[/条件]/(Group N|GrN|Listed)/奖金，以奖金行收尾；网格底部为
    Purebred Arabian 区（ICS UAE 章节不收录阿拉伯马，整体排除）；TBA 空格不产行。
    """
    chars: list[dict] = []
    rects: list[dict] = []
    for raw_line in payload.splitlines():
        if not raw_line.strip():
            continue
        obj = json.loads(raw_line)
        if obj["kind"] == "char":
            chars.append(obj)
        elif obj["kind"] == "rect":
            rects.append(obj)
    if not chars:
        raise RuntimeError("Race Schedule Grid 派生对象为空")
    segments = _schedule_grid_segments(chars)

    # 列中心：马场名列头行；每个列必须有唯一赛日日期
    centers = sorted((s["x0"] + s["x1"]) / 2 for s in segments if s["text"] == "Meydan" and 70 < s["top"] < 80)
    if len(centers) < 2:
        raise RuntimeError(f"Race Schedule Grid 列头不足：{len(centers)} 列")

    def _nearest_center(x: float) -> int:
        return min(range(len(centers)), key=lambda i: abs(centers[i] - x))

    day_dates: dict[int, date_type] = {}
    start_year = int(season.split("-")[0])
    for seg in segments:
        match = SCHEDULE_GRID_DATE_RE.match(seg["text"])
        if not match or seg["top"] >= 100:
            continue
        month = MONTHS_ABBR[match.group(2).upper()]
        year = start_year if month >= 9 else start_year + 1
        index = _nearest_center((seg["x0"] + seg["x1"]) / 2)
        parsed = date_type(year, month, int(match.group(1)))
        if index in day_dates and day_dates[index] != parsed:
            raise RuntimeError(f"赛日列日期冲突：{day_dates[index]} vs {parsed}")
        day_dates[index] = parsed
    missing = [i for i in range(len(centers)) if i not in day_dates]
    if missing:
        raise RuntimeError(f"赛日列缺少日期头：列索引 {missing}")

    day_labels: dict[int, str] = {}
    for seg in segments:
        if 55 < seg["top"] < 75 and seg["text"] in SCHEDULE_GRID_DAY_LABELS:
            day_labels[_nearest_center((seg["x0"] + seg["x1"]) / 2)] = seg["text"]

    # Purebred Arabian 区起点：左轴 "Pure Arabian" 标签；找不到说明版式变化，fail closed
    arabian_marks = [s["top"] for s in segments if s["x0"] < 70 and s["top"] > 700 and re.search(r"arabian", s["text"], re.IGNORECASE)]
    if not arabian_marks:
        raise RuntimeError("Race Schedule Grid 缺少 Purebred Arabian 区标签，无法确定排除带")
    arabian_top = min(arabian_marks) - 12.0

    # 距离带：左轴数字标签
    bands = sorted(
        (s["top"], s["text"]) for s in segments
        if SCHEDULE_GRID_BAND_LABEL_RE.match(s["text"]) and s["x0"] < SCHEDULE_GRID_BAND_LABEL_X_MAX and s["top"] < arabian_top
    )
    if len(bands) < 2:
        raise RuntimeError(f"Race Schedule Grid 距离带标签不足：{len(bands)}")

    def _band_of(cell: list[dict]) -> str:
        center = (cell[0]["top"] + cell[-1]["top"]) / 2
        nearest = sorted(bands, key=lambda band: abs(band[0] - center))[:2]
        if abs(nearest[0][0] - center) > SCHEDULE_GRID_BAND_MAX_OFFSET:
            raise RuntimeError(f"单元格纵向中心距最近距离带过远：{cell[0]['text']!r} center={center}")
        if len(nearest) == 2 and abs(nearest[1][0] - center) - abs(nearest[0][0] - center) < SCHEDULE_GRID_BAND_AMBIGUITY_MARGIN:
            raise RuntimeError(f"单元格距离带归属歧义：{cell[0]['text']!r} center={center} bands={nearest}")
        return nearest[0][1]

    # 单元格：列内按 top 堆叠，奖金行收尾；TBA 为独立空格
    by_column: dict[int, list[dict]] = {i: [] for i in range(len(centers))}
    for seg in segments:
        if 95 < seg["top"] < arabian_top and 70 < seg["x0"] < SCHEDULE_GRID_AXIS_X_MAX:
            by_column[_nearest_center((seg["x0"] + seg["x1"]) / 2)].append(seg)

    rows: list[dict] = []
    for index, column in enumerate(centers):
        cells: list[list[dict]] = []
        pending: list[dict] = []
        for seg in sorted(by_column[index], key=lambda s: s["top"]):
            if seg["text"] == "TBA":
                continue
            pending.append(seg)
            if SCHEDULE_GRID_PRIZE_RE.match(seg["text"]):
                cells.append(pending)
                pending = []
        if any(SCHEDULE_GRID_GRADE_RE.match(s["text"]) or SCHEDULE_GRID_LISTED_RE.match(s["text"]) for s in pending):
            raise RuntimeError(f"分级赛单元格缺少奖金行收尾：{[s['text'] for s in pending]} @ {day_dates[index]}")
        for cell in cells:
            texts = [s["text"] for s in cell]
            listed = any(SCHEDULE_GRID_LISTED_RE.match(text) for text in texts)
            grades = [i for i, text in enumerate(texts) if SCHEDULE_GRID_GRADE_RE.match(text)]
            if listed:
                if grades:
                    raise RuntimeError(f"单元格同时出现 Listed 与 Group 级别：{texts} @ {day_dates[index]}")
                continue  # Listed 不产行
            if not grades:
                continue  # Hcp/Benchmark/Maiden/Cond 等未分级单元格
            if len(grades) > 1:
                raise RuntimeError(f"单元格出现多个级别行：{texts} @ {day_dates[index]}")
            grade_index = grades[0]
            tail = texts[grade_index + 1:-1]
            if tail:
                raise RuntimeError(f"级别行与奖金行之间存在多余行：{texts} @ {day_dates[index]}")
            name_parts = [text for text in texts[:grade_index] if not SCHEDULE_GRID_COND_RE.match(text)]
            conditions = [text for text in texts[:grade_index] if SCHEDULE_GRID_COND_RE.match(text)]
            if not name_parts:
                raise RuntimeError(f"Group 赛单元格缺少赛名：{texts} @ {day_dates[index]}")
            name = " ".join(name_parts)
            grade_match = SCHEDULE_GRID_GRADE_RE.match(texts[grade_index])
            grade = f"G{grade_match.group(1) or grade_match.group(2)}"
            rows.append(
                _drc_timeline_row(
                    name=name,
                    grade=grade,
                    race_date=day_dates[index],
                    distance=_band_of(cell),
                    surface=_schedule_grid_surface(rects, cell[0]),
                    conditions=" ".join(conditions),
                    prize_text=texts[-1],
                    season=season,
                    day_label=day_labels.get(index, ""),
                    source_kind="drc_carnival_race_schedule_grid",
                    source_race_name=" / ".join(texts),
                )
            )
    _check_drc_counts(rows, set(day_dates.values()), season=season)
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
                expectation_status="held",
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
                    "results_link_present": held,
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
    for spec in args.drc_schedule_grid or []:
        url, path = _parse_source(spec)
        season = _drc_season_from_source(url, path)
        parsed = parse_drc_schedule_grid(path.read_text(encoding="utf-8"), season=season)
        _enrich_source_identity(parsed, url=url, path=path)
        rows.extend(parsed)
        summary["sources"].append({"kind": "drc_schedule_grid", "url": url, "path": str(path), "season": season})
        summary["row_counts"][f"drc_schedule_grid:{season}"] = len(parsed)
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
    parser.add_argument("--drc-schedule-grid", action="append", help="DRC Race Schedule Grid 字符+底色 JSONL，URL=PATH，可多个")
    parser.add_argument("--era-html", action="append", help="ERA 整日场头页，URL=PATH，可多个")
    parser.add_argument("--jcsa-html", action="append", help="JCSA 赛日卡，URL=PATH，可多个")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(build_timeline(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

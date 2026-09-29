#!/usr/bin/env python3
"""从 HRI 官方 Pattern Book 文本（pdfplumber 提取）生成爱尔兰赛历 timeline 行。

支持两类年册：
- 平地 Flat Pattern Book 的 "GROUP 1, 2 & 3 RACES <year> (N)" 索引节；
- 障碍 National Hunt Pattern 年册（跨年赛季）的 GRADED/LISTED 各节。

行格式（锚定行首 Mon DD，右侧锚定级别/途程/奖金）：
    Jun 29 Curragh Irish Derby 3 C&F Gr 1 12f 1,250,000
    Nov 21 Punchestown Morgiana Hurdle 4+ Gr 1 16f+ 150,000

计数自校验：平地按 EXPECTED_COUNTS / EXPECTED_GRADE1_COUNTS 与节首 (N) 双重核对；
障碍按每个节首 (N) 逐节核对。任何不匹配都 fail closed（raise）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


PARSER_VERSION = "hri-pattern-calendar.v2"

ALLOWED_URL_HOSTS = {"hri-ras.ie", "www.hri-ras.ie", "web.archive.org"}

# 已核验年份的平地 GROUP 1, 2 & 3 索引行数与 Gr 1 行数；未登记年份 fail closed。
EXPECTED_COUNTS = {2025: 72, 2026: 72}
EXPECTED_GRADE1_COUNTS = {2025: 13, 2026: 14}

FIELDS = (
    "record_type", "country_region", "country", "year", "series_key",
    "canonical_name_original", "original_name", "grade_text", "racecourse",
    "local_date", "distance_text", "surface", "expectation_status",
    "source_scope", "discipline", "season_label",
    "raw_source_cache_path", "raw_source_cache_sha256", "raw_source_url",
    "source_refs",
)

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# 爱尔兰现役赛马场（按名字长度倒序匹配，保证 Gowran Park / Down Royal 先于单词场名）。
IRISH_TRACKS = sorted(
    {
        "Ballinrobe", "Bellewstown", "Clonmel", "Cork", "Curragh", "Down Royal",
        "Downpatrick", "Dundalk", "Fairyhouse", "Galway", "Gowran Park",
        "Kilbeggan", "Killarney", "Laytown", "Leopardstown", "Limerick",
        "Listowel", "Naas", "Navan", "Punchestown", "Roscommon", "Sligo",
        "Thurles", "Tipperary", "Tramore", "Wexford",
    },
    key=len,
    reverse=True,
)

FLAT_HEADER_RE = re.compile(r"^GROUP 1, 2 & 3 RACES (\d{4}) \((\d+)\)$")
# 索引/总览节标题（用于终止 GROUP 节作用域），例如：
#   LISTED RACES 2025 (59) / PREMIER HANDICAPS 2025 (41)
#   2-Y-O GROUP RACES, LISTED RACES & PREMIER NURSERIES 2025 (32)
SECTION_END_RE = re.compile(r"^[-A-Z0-9 ,.&'/]+ \d{4}(?:/\d{4})? \(\d+\)$")
NH_SECTION_RE = re.compile(
    r"^(?P<section>GRADED(?:/LISTED)? [A-Z ]*?) - NATIONAL HUNT "
    r"(?P<season>\d{4}/\d{4}) \((?P<count>\d+)\)$"
)

_ROW_ANCHORS = (
    r"^(?:(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(?P<day>\d{1,2})"
    r"|(?P<day_first>\d{1,2})\s+(?P<month_first>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))\s+"
    r"(?P<body>\S.*?)"
)
_ROW_TAIL = (
    r"(?:\s+(?P<ebf>EBF))?"
    r"\s+(?P<age>\d{2}|\d{1,2}\+?)"
    r"(?:\s+(?P<sex>[A-Z](?:&[A-Z])?))?"
    r"\s+(?P<grade>Gr\s+[123]|Listed)"
    r"\s+(?P<dist>\d+f\+?)"
    r"\s+(?P<stakes>[\d,]+)$"
)
FLAT_ROW_RE = re.compile(_ROW_ANCHORS + _ROW_TAIL)
# 障碍年册在 RACE NAME 与 EBF 之间多一个 NOV 列（Y=新手赛）。
NH_ROW_RE = re.compile(
    _ROW_ANCHORS + r"(?:\s+(?P<novice>Y))?" + _ROW_TAIL
)

SURFACE_NOTE = (
    "surface not stated in HRI pattern book; left blank per inventory rules "
    "(Dundalk stages all-weather racing, do not assume turf)"
)


class CalendarError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise CalendarError(f"source text must be a regular non-symlink file: {path}")
    return path.resolve(strict=True)


def parse_source(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise CalendarError("source must use URL=PATH")
    url, raw_path = spec.split("=", 1)
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or (parsed.hostname or "") not in ALLOWED_URL_HOSTS:
        raise CalendarError("source URL is outside the HRI allowlist")
    return url.strip(), _regular(Path(raw_path))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _split_track(body: str, *, line: str) -> tuple[str, str]:
    for track in IRISH_TRACKS:
        if body == track or body.startswith(track + " "):
            name = body[len(track):].strip()
            if not name:
                break
            return track, name
    raise CalendarError(f"unrecognized racecourse in row: {line!r}")


def _parse_row(line: str, pattern: re.Pattern) -> dict | None:
    match = pattern.match(line)
    if not match:
        return None
    track, name = _split_track(match.group("body").strip(), line=line)
    month_text = match.group("month") or match.group("month_first")
    day_text = match.group("day") or match.group("day_first")
    return {
        "month": MONTHS[month_text],
        "day": int(day_text),
        "racecourse": track,
        "race_name": name,
        "novice": bool(match.groupdict().get("novice")),
        "ebf": bool(match.group("ebf")),
        "age_text": match.group("age"),
        "sex_text": match.group("sex") or "",
        "grade_text": re.sub(r"\s+", " ", match.group("grade")),
        "distance_text": match.group("dist"),
        "stakes_raw": match.group("stakes"),
        "line_raw": line,
    }


def _timeline_row(parsed: dict, *, year: int, discipline: str, season_label: str, source: dict | None) -> dict:
    try:
        local_date = datetime(year, parsed["month"], parsed["day"]).date().isoformat()
    except ValueError as exc:
        raise CalendarError(f"invalid calendar date in row: {parsed['line_raw']!r}") from exc
    source_refs = {
        "distance_unit": "furlong",
        "stakes_raw": parsed["stakes_raw"],
        "stakes_currency": "EUR",
        "age_text": parsed["age_text"],
        "sex_text": parsed["sex_text"],
        "ebf": parsed["ebf"],
        "surface_note": SURFACE_NOTE,
        "section": parsed.get("section", ""),
        "line_raw": parsed["line_raw"],
    }
    if parsed.get("novice"):
        source_refs["novice"] = True
    if parsed.get("race_category"):
        source_refs["race_category"] = parsed["race_category"]
    return {
        "record_type": "timeline",
        "country_region": "ireland",
        "country": "ireland",
        "year": str(year),
        "series_key": f"ireland-{_slug(parsed['race_name'])}",
        "canonical_name_original": parsed["race_name"],
        "original_name": parsed["race_name"],
        "grade_text": parsed["grade_text"],
        "racecourse": parsed["racecourse"],
        "local_date": local_date,
        "distance_text": parsed["distance_text"],
        "surface": "",
        "expectation_status": "held",
        "source_scope": "official_calendar",
        "discipline": discipline,
        "season_label": season_label,
        "raw_source_cache_path": (source or {}).get("cache_path", ""),
        "raw_source_cache_sha256": (source or {}).get("sha256", ""),
        "raw_source_url": (source or {}).get("url", ""),
        "source_refs": source_refs,
    }


def parse_flat_pattern_text(text: str, *, year: int, source: dict | None = None) -> list[dict]:
    """解析平地 Pattern Book 的 GROUP 1, 2 & 3 索引节，返回 <year> 年的 timeline 行。"""
    if year not in EXPECTED_COUNTS:
        raise CalendarError(f"unregistered flat pattern year: {year}")
    rows = []
    header_count = None
    in_section = False
    section_seen = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not in_section:
            header = FLAT_HEADER_RE.match(line)
            if header:
                header_year = int(header.group(1))
                if header_year != year:
                    raise CalendarError(
                        f"flat pattern header year {header_year} != requested {year}"
                    )
                header_count = int(header.group(2))
                in_section = True
                section_seen = True
            continue
        if SECTION_END_RE.match(line):
            break
        parsed = _parse_row(line, FLAT_ROW_RE)
        if parsed is None:
            # 页码、列头、跨页悬挂残行（如 "Jun "）在此跳过
            continue
        parsed["section"] = f"GROUP 1, 2 & 3 RACES {year}"
        rows.append(_timeline_row(parsed, year=year, discipline="flat", season_label="", source=source))
    if not section_seen or header_count is None:
        raise CalendarError(f"GROUP 1, 2 & 3 RACES {year} section not found")
    if len(rows) != header_count:
        raise CalendarError(f"flat pattern row count {len(rows)} != header count {header_count}")
    if len(rows) != EXPECTED_COUNTS[year]:
        raise CalendarError(f"flat pattern row count {len(rows)} != expected {EXPECTED_COUNTS[year]}")
    grade1 = sum(row["grade_text"] == "Gr 1" for row in rows)
    if grade1 != EXPECTED_GRADE1_COUNTS[year]:
        raise CalendarError(f"flat pattern Gr 1 count {grade1} != expected {EXPECTED_GRADE1_COUNTS[year]}")
    return rows


def _default_year_map(season_label: str) -> dict[int, int]:
    """赛季默认公历年映射：5-12 月归首年、1-4 月归次年。

    仅用于非 5 月行；5 月在 Part 1 属首年、Part 2 属次年，必须以
    extract_nh_date_evidence 的正文日期证据为准（见 parse_nh_pattern_text）。
    依据：2026/2027 Part 1 年册正文页明确写有 SATURDAY, 9TH MAY, 2026 等日期，
    且 Galway Hurdle 固定在 Galway 节周四（2026-07-30）。
    """
    match = re.fullmatch(r"(\d{4})/(\d{4})", season_label)
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise CalendarError(f"invalid season label: {season_label!r}")
    first = int(match.group(1))
    return {**{month: first for month in range(5, 13)}, **{month: first + 1 for month in range(1, 5)}}


EVIDENCE_MONTHS = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}

NH_DATE_EVIDENCE_RE = re.compile(
    r"\b(?P<weekday>MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),\s+"
    r"(?P<day>\d{1,2})(?:ST|ND|RD|TH)\s+"
    r"(?P<month>JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)"
    r",\s+(?P<year>\d{4})\b"
)


def extract_nh_date_evidence(text: str) -> dict[tuple[int, int], int]:
    """从正文页 "SATURDAY, 9TH MAY, 2026" 行提取 (month, day) -> year 证据。

    星期与公历日期必须真实一致（防御 pdfplumber 栏错位）；同一 (month, day)
    出现两个年份时 fail closed。
    """
    evidence: dict[tuple[int, int], int] = {}
    for match in NH_DATE_EVIDENCE_RE.finditer(text):
        month = EVIDENCE_MONTHS[match.group("month")]
        day = int(match.group("day"))
        year = int(match.group("year"))
        try:
            actual_weekday = datetime(year, month, day).strftime("%A").upper()
        except ValueError as exc:
            raise CalendarError(f"invalid NH date evidence: {match.group(0)!r}") from exc
        if actual_weekday != match.group("weekday"):
            raise CalendarError(f"NH date evidence weekday mismatch: {match.group(0)!r}")
        key = (month, day)
        if key in evidence and evidence[key] != year:
            raise CalendarError(
                f"conflicting NH date evidence for month={month} day={day}: "
                f"{evidence[key]} vs {year}"
            )
        evidence[key] = year
    return evidence


def _nh_category(section: str) -> str:
    label = section.lower()
    if "handicap" in label and "steeplechase" in label:
        return "handicap_steeplechase"
    if "handicap" in label and "hurdle" in label:
        return "handicap_hurdle"
    if "steeplechase" in label:
        return "steeplechase"
    if "hurdle" in label:
        return "hurdle"
    if "bumper" in label:
        return "bumper"
    return "other"


def parse_nh_pattern_text(
    text: str, *, season_label: str, year_map: dict, date_map: dict | None = None,
    source: dict | None = None,
) -> list[dict]:
    """解析障碍 Pattern 年册（跨年赛季）的 GRADED/LISTED 各节。

    年份归属：5 月行必须命中正文日期证据（Part 1 属首年、Part 2 属次年）；
    其余月份用 year_map，且若正文证据存在则不得与之矛盾。
    """
    match = re.fullmatch(r"(\d{4})/(\d{4})", season_label)
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise CalendarError(f"invalid season label: {season_label!r}")
    season_first = int(match.group(1))
    season_years = {season_first, season_first + 1}
    if not year_map:
        year_map = _default_year_map(season_label)
    if date_map is None:
        date_map = extract_nh_date_evidence(text)
    rows = []
    sections_seen = 0
    current_count = None
    current_rows = 0
    current_section = ""

    def _close_section() -> None:
        if current_count is not None and current_rows != current_count:
            raise CalendarError(
                f"NH section {current_section!r} row count {current_rows} != header count {current_count}"
            )

    def _resolve_year(parsed: dict) -> int:
        month = parsed["month"]
        day = parsed["day"]
        if month == 5:
            if (month, day) not in date_map:
                raise CalendarError(
                    f"May row requires NH body date evidence: {parsed['line_raw']!r}"
                )
            return date_map[(month, day)]
        if month not in year_map:
            raise CalendarError(f"month {month} missing from NH year map: {parsed['line_raw']!r}")
        year = int(year_map[month])
        evidence_year = date_map.get((month, day))
        if evidence_year is not None and evidence_year != year:
            raise CalendarError(
                f"NH date evidence contradicts season year map: {parsed['line_raw']!r} "
                f"evidence={evidence_year} map={year}"
            )
        return year

    for raw_line in text.splitlines():
        line = raw_line.strip()
        header = NH_SECTION_RE.match(line)
        if header:
            _close_section()
            if header.group("season") != season_label:
                raise CalendarError(
                    f"NH booklet season {header.group('season')} != requested {season_label}"
                )
            sections_seen += 1
            current_count = int(header.group("count"))
            current_rows = 0
            current_section = header.group("section")
            continue
        if current_count is None:
            continue
        parsed = _parse_row(line, NH_ROW_RE)
        if parsed is None:
            continue
        year = _resolve_year(parsed)
        if year not in season_years:
            raise CalendarError(
                f"NH row year {year} outside season {season_label}: {parsed['line_raw']!r}"
            )
        parsed["section"] = current_section
        parsed["race_category"] = _nh_category(current_section)
        rows.append(
            _timeline_row(
                parsed,
                year=year,
                discipline="jump",
                season_label=season_label,
                source=source,
            )
        )
        current_rows += 1
    _close_section()
    if sections_seen == 0:
        raise CalendarError(f"no NATIONAL HUNT {season_label} section found")
    return rows


def _detect_flat_year(text: str) -> int:
    for line in text.splitlines():
        header = FLAT_HEADER_RE.match(line.strip())
        if header:
            return int(header.group(1))
    raise CalendarError("flat pattern GROUP header not found")


def _detect_nh_season(text: str) -> str:
    seasons = set()
    for line in text.splitlines():
        header = NH_SECTION_RE.match(line.strip())
        if header:
            seasons.add(header.group("season"))
    if len(seasons) != 1:
        raise CalendarError(f"NH booklet season identity is not unique: {sorted(seasons)}")
    return seasons.pop()


def build_rows(flat_sources: list[tuple[str, Path]], nh_sources: list[tuple[str, Path]]) -> tuple[list[dict], dict]:
    rows = []
    flat_counts = {}
    nh_counts = {}
    for url, path in flat_sources:
        text = path.read_text(encoding="utf-8")
        year = _detect_flat_year(text)
        source = {"url": url, "cache_path": str(path), "sha256": _sha256(path)}
        parsed = parse_flat_pattern_text(text, year=year, source=source)
        if str(year) in flat_counts:
            raise CalendarError(f"duplicate flat pattern source for year {year}")
        flat_counts[str(year)] = len(parsed)
        rows.extend(parsed)
    for url, path in nh_sources:
        text = path.read_text(encoding="utf-8")
        season = _detect_nh_season(text)
        source = {"url": url, "cache_path": str(path), "sha256": _sha256(path)}
        parsed = parse_nh_pattern_text(text, season_label=season, year_map=_default_year_map(season), source=source)
        nh_counts[season] = nh_counts.get(season, 0) + len(parsed)
        rows.extend(parsed)
    keys = [(row["series_key"], row["local_date"], row["racecourse"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise CalendarError("duplicate (series_key, local_date, racecourse) identity in calendar rows")
    rows.sort(key=lambda row: (row["local_date"], row["series_key"]))
    summary = {"flat_counts": flat_counts, "nh_counts": nh_counts, "row_count": len(rows)}
    return rows, summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flat-txt", action="append", default=[], help="URL=PATH；平地年册文本，可重复")
    parser.add_argument("--nh-txt", action="append", default=[], help="URL=PATH；障碍年册文本，可重复")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        flat_sources = [parse_source(spec) for spec in args.flat_txt]
        nh_sources = [parse_source(spec) for spec in args.nh_txt]
        if not flat_sources and not nh_sources:
            raise CalendarError("at least one --flat-txt or --nh-txt source is required")
        rows, summary = build_rows(flat_sources, nh_sources)
        if not rows:
            raise CalendarError("calendar produced no rows")
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = output_dir / "hri_pattern_calendar.jsonl"
        temporary = jsonl_path.with_name(f".{jsonl_path.name}.{os.getpid()}.tmp")
        with temporary.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, jsonl_path)
        summary.update(
            {
                "parser_version": PARSER_VERSION,
                "output_sha256": _sha256(jsonl_path),
                "sources": [
                    {"url": url, "cache_path": str(path), "sha256": _sha256(path)}
                    for url, path in flat_sources + nh_sources
                ],
            }
        )
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except (CalendarError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

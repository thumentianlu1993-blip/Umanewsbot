#!/usr/bin/env python3
"""Deutscher Galopp 官方赛历解析：renntermine PDF 文本 + Wayback ergebnisse 快照 -> timeline 行。

输入来源：
- renntermine PDF 提取文本（官方赛历，下一年度计划，级别记号 I/II/III/L）
- web.archive.org 上的 ergebnisse 页面快照（已结束赛季，accordion 内 Gruppe I/II/III 行）

输出 calendar_timeline_candidate.jsonl + summary.json，供历史赛事目录 inventory 使用。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup


PARSER_VERSION = "deutscher-galopp-calendar.v1"
ALLOWED_HOSTS = ("deutscher-galopp.de", "web.archive.org")

# timeline 行字段（对齐 racing_australia graded catalog 的 schema，另加 source_refs 记录推断依据）
FIELDS = (
    "record_type", "country_region", "country", "year", "series_key",
    "canonical_name_original", "original_name",
    "grade_text", "racecourse", "local_date",
    "distance_text", "surface", "expectation_status", "source_scope",
    "discipline", "season_label",
    "raw_source_cache_path", "raw_source_cache_sha256", "raw_source_url",
    "source_refs",
)

# 官方赛历的分级赛数量自校验（不允许空成功或静默缺数）
EXPECTED_COUNTS = {2026: {"G1": 7, "G2": 9, "G3": 26}}

# 命名赛事对账清单：PDF 文本提取损坏导致级别记号丢失时，按规范赛事名兜底修复
KNOWN_GRADE_BY_NAME = {
    "Grosser Preis der Badischen Wirtschaft": "G2",
}

# PDF 文本提取的已知字符级粘连/错字修复（不改变语义；级别仍由对账清单给出）
TEXT_REPAIRS = (
    ("Baden-BadGernosser", "Baden-Baden Grosser"),
    ("WirtschaIfIt)", "Wirtschaft)"),
)

GRADE_BY_TOKEN = {"I": "G1", "II": "G2", "III": "G3"}

# renntermine 文本中出现的全部马场（多词马场优先匹配）
RACECOURSES = (
    "Baden-Baden", "Bad Harzburg", "Berlin-Hoppegarten", "Hoppegarten",
    "Düsseldorf", "Dortmund", "Mülheim", "Mannheim", "Köln", "Zweibrücken",
    "Magdeburg", "München", "Krefeld", "Hannover", "Leipzig", "Halle",
    "Hassloch", "Dresden", "Hamburg", "Cuxhaven", "Saarbrücken", "Erbach",
    "Quakenbrück", "Billigheim", "Honzrath",
)

MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
    "August", "September", "Oktober", "November", "Dezember",
)

_MONTH_HEADER_RE = re.compile(rf"^({'|'.join(MONTHS)})\s+(.*)$")
_HOLIDAY_RE = re.compile(r"^\([^)]*\)\s+(?=(?:So|Mo|Di|Mi|Do|Fr|Sa)\.\s)")
_DATE_RE = re.compile(r"^(?:So|Mo|Di|Mi|Do|Fr|Sa)\.\s*(\d{2})\.(\d{2})\.\s*(.*)$")
_IGNORABLE_RE = re.compile(r"^(?:RENNTERMINE\s+\d{4}|Stand:|\*)")
# 分级/表列赛行：名称 级别 年龄[性别] 距离 m
_RACE_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<grade>I{1,3}|L)\s+(?P<age>[234]\+?)"
    r"\s*(?P<sex>H\.?\+S\.|S\.?)?\s+(?P<dist>\d{3,4})\s*m$"
)
# 无级别记号的赛行（缺陷行兜底；Auktionsrennen 等拍卖赛年龄写作 2j./3j.，不会落入此模式）
_GRADELESS_RACE_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<age>[234]\+?)"
    r"\s*(?P<sex>H\.?\+S\.|S\.?)?\s+(?P<dist>\d{3,4})\s*m$"
)
_AUKTIONSRENNEN_RE = re.compile(r"^Auktionsrennen\s+[23]j\.\s+\d{3,4}\s*m$")

# 冠名前缀（去冠名得到 canonical_name_original；长前缀优先）
SPONSOR_PREFIXES = (
    "Comer Group International ", "Japan Racing Association ",
    "Mehl Mülhens Stiftung ", "Renate und Albrecht Woeste - ",
    "Großer Preis der BBF Gruppe - ", "Casino Baden-Baden ",
    "Sparkasse KölnBonn - ", "Sparkasse KölnBonn ", "WETTSTAR.de - ", "WETTSTAR.de ",
    "Westminster ", "T.v.Zastrow ", "T. von Zastrow ",
    "Brunner - ", "Brunner ", "Kronimus ", "Kalkmann ", "Coolmore ",
    "Henkel-", "Henkel ", "IDEE ",
)
# 冠名中缀（如 Grosser Preis von Lotto Hamburg / Grosser Allianz Preis von Bayern）
SPONSOR_INFIX_RE = re.compile(r"\s+(?:Allianz|Lotto)\s+")
_ORDINAL_PREFIX_RE = re.compile(r"^\d+\.\s+")
_ORDINAL_INFIX_RE = re.compile(r"\b\d+\.\s+")
_BETTING_POOL_SUFFIX_RE = re.compile(r"\s+-\s+V\d+[/\-]\d+\s*$")
_EX_NAME_RE = re.compile(r"\(ex\s+([^)]+)\)\s*$")

_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


class CalendarError(ValueError):
    pass


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


def _slugify(value: str) -> str:
    """与 prepare_tjcis_ics_catalog.stable_series_key 同款 slug：camelCase 拆分 +
    标点/符号空格化 + NFKD ascii 化（ü->u），保证同名赛事 series_key 与 ICS 基线一致。"""
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value or "")
    punctuation_spaced = "".join(
        " " if unicodedata.category(char)[0] in {"P", "S"} else char for char in value
    )
    ascii_value = unicodedata.normalize("NFKD", punctuation_spaced).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-") or "race"


def _normalize_key(value: str) -> str:
    value = (value or "").lower()
    for src, dst in _UMLAUTS.items():
        value = value.replace(src, dst)
    return re.sub(r"[^a-z0-9]+", "", value)


def _canonical_name(original: str) -> str:
    """去冠名：优先 (ex X) 形态取原名，再去前缀/中缀冠名。"""
    name = _collapse(original)
    ex_match = _EX_NAME_RE.search(name)
    if ex_match:
        return _collapse(ex_match.group(1))
    for prefix in SPONSOR_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    name = SPONSOR_INFIX_RE.sub(" ", name)
    return _collapse(name)


def _known_grade_lookup(name: str) -> tuple[str, str] | None:
    """缺陷行兜底：对账清单中规范名的内容词（≥5 字符）全部出现于提取名时视为同一赛事。"""
    name_key = _normalize_key(name)
    matches = []
    for known_name, grade in KNOWN_GRADE_BY_NAME.items():
        tokens = [t for t in re.split(r"[^a-z0-9]+", _normalize_key_words(known_name)) if len(t) >= 5]
        if tokens and all(token in name_key for token in tokens):
            matches.append((known_name, grade))
    if len(matches) > 1:
        raise CalendarError(f"KNOWN_GRADE_BY_NAME 匹配不唯一：{name!r} -> {matches!r}")
    return matches[0] if matches else None


def _normalize_key_words(value: str) -> str:
    value = (value or "").lower()
    for src, dst in _UMLAUTS.items():
        value = value.replace(src, dst)
    return re.sub(r"[^a-z0-9]+", " ", value)


def _match_racecourse(text: str) -> tuple[str, str]:
    """从行首匹配马场（长名优先），返回 (course, rest)；未匹配返回 ("", text)。"""
    for course in sorted(RACECOURSES, key=len, reverse=True):
        if text == course:
            return course, ""
        if text.startswith(course + " "):
            return course, text[len(course):].strip()
    return "", text


def _timeline_row(
    *,
    year: int,
    local_date: str,
    racecourse: str,
    original_name: str,
    canonical_name: str,
    grade_text: str,
    distance_text: str,
    source_refs: dict,
) -> dict:
    # inventory 校验不允许 held + 空 surface（historical_race_catalog_adapters._surface
    # 仅对非 held 允许空白），德国平地分级赛均为草地，推断 turf 并在 source_refs 注明
    refs = {
        "source_language": "de",
        "surface_inferred": "turf",
        "surface_note": "来源未标注场地；德国平地分级赛均为草地，推断为 turf",
        **source_refs,
    }
    return {
        "record_type": "timeline",
        "country_region": "germany",
        "country": "germany",
        "year": year,
        "series_key": f"germany-{_slugify(canonical_name)}",
        "canonical_name_original": canonical_name,
        "original_name": original_name,
        "grade_text": grade_text,
        "racecourse": racecourse,
        "local_date": local_date,
        "distance_text": distance_text,
        "surface": "turf",
        "expectation_status": "held",
        "source_scope": "official_calendar",
        "discipline": "flat",
        "season_label": "",
        "raw_source_cache_path": "",
        "raw_source_cache_sha256": "",
        "raw_source_url": "",
        "source_refs": refs,
    }


def parse_renntermine_text(text: str, *, year: int) -> list[dict]:
    """解析 Deutscher Galopp renntermine PDF 提取文本，产出当年 G1/G2/G3 timeline 行。

    行格式：`April So. 05.04. Hoppegarten Altano-Rennen L 4+ 2800 m`；
    多日多赛时续行无日期/马场前缀（继承上一行）。I/II/III -> G1/G2/G3，L（Listed）不产出。
    """
    rows: list[dict] = []
    current_date: date | None = None
    current_course = ""
    for line_number, raw_line in enumerate((text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line or _IGNORABLE_RE.match(line):
            continue
        for src, dst in TEXT_REPAIRS:
            line = line.replace(src, dst)
        month_match = _MONTH_HEADER_RE.match(line)
        if month_match:
            line = month_match.group(2).strip()
        line = _HOLIDAY_RE.sub("", line)
        date_match = _DATE_RE.match(line)
        if date_match:
            day, month, rest = int(date_match.group(1)), int(date_match.group(2)), date_match.group(3).strip()
            try:
                current_date = date(year, month, day)
            except ValueError as exc:
                raise CalendarError(f"第 {line_number} 行日期无效：{raw_line!r}") from exc
            course, rest = _match_racecourse(rest)
            if course:
                current_course = course
            if not rest:
                continue  # 纯赛马日（无分级赛）
            line = rest
        else:
            if current_date is None:
                raise CalendarError(f"第 {line_number} 行缺少日期上下文：{raw_line!r}")
            course, rest = _match_racecourse(line)
            if course:
                current_course = course
                if not rest:
                    continue  # 续行仅切换马场
                line = rest
        if not current_course:
            raise CalendarError(f"第 {line_number} 行缺少马场：{raw_line!r}")
        if _AUKTIONSRENNEN_RE.match(line):
            continue  # 拍卖赛不是分级/表列赛
        race_match = _RACE_RE.match(line)
        grade_repaired = False
        if race_match:
            token = race_match.group("grade")
            if token == "L":
                continue  # Listed 不产出
            grade = GRADE_BY_TOKEN[token]
            name = _collapse(race_match.group("name"))
            age_text = race_match.group("age")
            sex_text = race_match.group("sex") or ""
            distance_text = race_match.group("dist")
        else:
            gradeless = _GRADELESS_RACE_RE.match(line)
            if not gradeless:
                raise CalendarError(f"第 {line_number} 行无法解析：{raw_line!r}")
            name = _collapse(gradeless.group("name"))
            age_text = gradeless.group("age")
            sex_text = gradeless.group("sex") or ""
            distance_text = gradeless.group("dist")
            known = _known_grade_lookup(name)
            if known is None:
                raise CalendarError(f"第 {line_number} 行缺少级别记号且不在对账清单：{raw_line!r}")
            known_name, grade = known
            grade_repaired = True
        canonical = _canonical_name(name)
        if grade_repaired:
            # 缺陷行名称已被提取损坏，规范名以 KNOWN_GRADE_BY_NAME 的键为准
            canonical = known_name
        rows.append(
            _timeline_row(
                year=year,
                local_date=current_date.isoformat(),
                racecourse=current_course,
                original_name=name,
                canonical_name=canonical,
                grade_text=grade,
                distance_text=distance_text,
                source_refs={
                    "grade_token_raw": race_match.group("grade") if race_match else "",
                    "grade_repaired_from_known_list": grade_repaired,
                    "age_text": age_text,
                    "sex_text": sex_text,
                    "raw_line": raw_line.strip(),
                },
            )
        )
    if not rows:
        raise CalendarError(f"renntermine 文本没有解析出任何分级赛（year={year}）")
    counts = {"G1": 0, "G2": 0, "G3": 0}
    for row in rows:
        counts[row["grade_text"]] += 1
    expected = EXPECTED_COUNTS.get(year)
    if expected and counts != expected:
        raise CalendarError(f"renntermine {year} 分级赛计数不符：解析 {counts} != 预期 {expected}")
    series_keys = [row["series_key"] for row in rows]
    if len(series_keys) != len(set(series_keys)):
        raise CalendarError("renntermine 解析结果 series_key 重复")
    rows.sort(key=lambda row: (row["local_date"], row["racecourse"], row["series_key"]))
    return rows


_SNAPSHOT_HEADER_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})\s+(.+)$")
_SNAPSHOT_GRADE_RE = re.compile(r"\bGruppe\s+(I{1,3})\b")
_SNAPSHOT_DISTANCE_RE = re.compile(r"(\d{1,2}(?:\.\d{3})+|\d{3,4})\s*m\b")


def _snapshot_race_name(raw_title: str) -> tuple[str, str]:
    """返回 (original_name 原样, canonical 去冠名/去届数/去投注池后缀)。"""
    original = _collapse(raw_title)
    name = _BETTING_POOL_SUFFIX_RE.sub("", original)
    name = _ORDINAL_PREFIX_RE.sub("", name)
    canonical = _canonical_name(name)
    canonical = _ORDINAL_INFIX_RE.sub("", canonical)
    canonical = _BETTING_POOL_SUFFIX_RE.sub("", canonical)
    return original, _collapse(canonical)


def parse_ergebnisse_snapshot(html: str, *, year: int) -> list[dict]:
    """解析 Wayback 快照中的 ergebnisse accordion（div.elementAccordion）。

    分组头 `DD.MM.YY 马场`，赛行提取 Gruppe I/II/III -> G1/G2/G3；无 Gruppe 标注的跳过。
    只产出解析年份等于 year 的行。
    """
    soup = BeautifulSoup(html or "", "lxml")
    accordion = soup.select_one("div.elementAccordion")
    if accordion is None:
        raise CalendarError("快照中不存在 div.elementAccordion")
    rows: list[dict] = []
    current: tuple[str, str] | None = None  # (iso_date, racecourse)
    for node in accordion.find_all(["h3", "div"]):
        classes = node.get("class") or []
        if node.name == "h3" and "accordionHeader" in classes:
            header = _collapse(node.get_text(" ", strip=True))
            match = _SNAPSHOT_HEADER_RE.match(header)
            if not match:
                raise CalendarError(f"ergebnisse 分组头无法解析：{header!r}")
            day, month, yy = int(match.group(1)), int(match.group(2)), int(match.group(3))
            full_year = (year // 100) * 100 + yy
            if full_year - year > 50:
                full_year -= 100
            try:
                parsed = date(full_year, month, day)
            except ValueError as exc:
                raise CalendarError(f"ergebnisse 分组头日期无效：{header!r}") from exc
            current = (parsed.isoformat(), _collapse(match.group(4)))
            continue
        if node.name != "div" or "accordionElementOuter" not in classes:
            continue
        if current is None:
            raise CalendarError("ergebnisse 赛行缺少分组头")
        local_date, racecourse = current
        if int(local_date[:4]) != year:
            continue
        ausschreibung_node = node.select_one("div.accordionAusschreibung")
        titel_node = node.select_one("div.accordionTitel")
        if ausschreibung_node is None or titel_node is None:
            continue
        ausschreibung = _collapse(ausschreibung_node.get_text(" ", strip=True))
        grade_match = _SNAPSHOT_GRADE_RE.search(ausschreibung)
        if not grade_match:
            continue  # 无 Gruppe 标注的赛行跳过（Ausgleich 等让赛不是分级赛）
        distance_match = _SNAPSHOT_DISTANCE_RE.search(ausschreibung)
        if not distance_match:
            raise CalendarError(f"ergebnisse 赛行缺少距离：{ausschreibung!r}")
        number_node = node.select_one("div.accordionRennNrInner")
        link_node = node.select_one("a.accordionLink")
        original, canonical = _snapshot_race_name(titel_node.get_text(" ", strip=True))
        if not canonical:
            raise CalendarError(f"ergebnisse 赛行名称为空：{titel_node.get_text(' ', strip=True)!r}")
        rows.append(
            _timeline_row(
                year=year,
                local_date=local_date,
                racecourse=racecourse,
                original_name=original,
                canonical_name=canonical,
                grade_text=GRADE_BY_TOKEN[grade_match.group(1)],
                distance_text=distance_match.group(1).replace(".", ""),
                source_refs={
                    "grade_label": f"Gruppe {grade_match.group(1)}",
                    "grade_repaired_from_known_list": False,
                    "race_number": _collapse(number_node.get_text(" ", strip=True)) if number_node else "",
                    "detail_href": link_node.get("href") or "" if link_node else "",
                },
            )
        )
    if not rows:
        raise CalendarError(f"ergebnisse 快照没有解析出 {year} 年任何分级赛")
    keys = [row["series_key"] for row in rows]
    if len(keys) != len(set(keys)):
        raise CalendarError("ergebnisse 快照解析结果 series_key 重复")
    rows.sort(key=lambda row: (row["local_date"], row["racecourse"], row["series_key"]))
    return rows


def _parse_source(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise CalendarError("来源必须使用 URL=PATH 格式")
    url, raw_path = spec.split("=", 1)
    url = url.strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not host:
        raise CalendarError(f"来源 URL 必须是 https：{url!r}")
    if not any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_HOSTS):
        raise CalendarError(f"来源 URL 不在白名单内：{url!r}")
    path = Path(raw_path)
    if path.is_symlink() or not path.is_file():
        raise CalendarError(f"来源文件不存在或非普通文件：{raw_path}")
    return url, path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dedupe_key(row: dict) -> tuple[str, str, str]:
    return (
        row["local_date"],
        _normalize_key(row["racecourse"]),
        _normalize_key(row["original_name"]),
    )


def prepare_calendar(args) -> dict:
    sources = []
    all_rows: list[dict] = []
    for kind, specs, parser, encoding in (
        ("renntermine_txt", args.renntermine_txt or [], parse_renntermine_text, "utf-8"),
        ("ergebnisse_html", args.ergebnisse_html or [], parse_ergebnisse_snapshot, "utf-8"),
    ):
        for spec in specs:
            url, path = _parse_source(spec)
            parsed = parser(path.read_text(encoding=encoding, errors="replace"), year=args.year)
            sha256 = _sha256(path)
            for row in parsed:  # 来源信息注入 raw_source_* 字段
                row["raw_source_cache_path"] = str(path)
                row["raw_source_cache_sha256"] = sha256
                row["raw_source_url"] = url
            sources.append({"kind": kind, "url": url, "path": str(path),
                            "sha256": sha256, "rows": len(parsed)})
            all_rows.extend(parsed)
    if not sources:
        raise CalendarError("至少需要一路 --renntermine-txt 或 --ergebnisse-html 来源")
    # 多份快照/多份 PDF 之间的重复赛事去重
    seen = set()
    deduped = []
    duplicates_skipped = 0
    for row in all_rows:
        key = _dedupe_key(row)
        if key in seen:
            duplicates_skipped += 1
            continue
        seen.add(key)
        deduped.append(row)
    deduped.sort(key=lambda row: (row["local_date"], row["racecourse"], row["series_key"]))
    if not deduped:
        raise CalendarError("全部来源解析后没有任何 timeline 行")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "calendar_timeline_candidate.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in deduped:
            ordered = {field: row[field] for field in FIELDS}
            handle.write(json.dumps(ordered, ensure_ascii=False) + "\n")
    grade_counts = {"G1": 0, "G2": 0, "G3": 0}
    for row in deduped:
        grade_counts[row["grade_text"]] += 1
    summary = {
        "parser_version": PARSER_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": args.year,
        "row_count": len(deduped),
        "grade_counts": grade_counts,
        "duplicates_skipped": duplicates_skipped,
        "by_source_kind": {
            "renntermine_txt": sum(s["rows"] for s in sources if s["kind"] == "renntermine_txt"),
            "ergebnisse_html": sum(s["rows"] for s in sources if s["kind"] == "ergebnisse_html"),
        },
        "sources": sources,
        "output": str(jsonl_path),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renntermine-txt", action="append", default=[],
                        help="URL=PATH，renntermine PDF 提取文本，可多次")
    parser.add_argument("--ergebnisse-html", action="append", default=[],
                        help="URL=PATH，Wayback ergebnisse 快照 HTML，可多次")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    summary = prepare_calendar(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

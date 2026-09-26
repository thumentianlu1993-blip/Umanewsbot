#!/usr/bin/env python3
"""赛事日历对账：生产 RaceEvent 导出 vs TJCIS/ICS 应办全集（2025+）。

只读分析工具，不写数据库、不触网：
- 输入生产导出 CSV（race_events + 可选 aliases）与 prepare_tjcis_ics_catalog 的 derived 目录；
- 按地区 + ICS 年度窗口匹配（南半球/跨年赛季按 ICS 年度口径映射 local_date）；
- 输出 gap_ledger.json（按地区×年度汇总）与 gap_review.csv（逐场明细）；
- 缺场、疑似重复、年份错位、缺赛果全部显式列出，不做静默归并。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

# ICS 年度 -> 该地区赛事实际 local_date 所属窗口（含端点，YYYY-MM-DD）。
# 南半球/跨年赛季：ICS 年度 Y 的书收录 Y-1 下半年至 Y 年中结束的赛季。
SEASON_WINDOWS = {
    "hong_kong": lambda y: (date(y - 1, 9, 1), date(y, 7, 31)),
    "australia": lambda y: (date(y - 1, 8, 1), date(y, 7, 31)),
    "middle_east": lambda y: (date(y - 1, 10, 1), date(y, 5, 31)),
}
IN_SCOPE_GRADES = {"G1", "G2", "G3", "JPN1"}
DOMESTIC_ONLY_GRADES = {"JPN2", "JPN3", "LOCAL_GRADE"}


def _normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"\([^)]*\)", " ", text)
    # 法国官方名为 "Prix …" 前缀，ICS 习惯省略；障碍赛 ICS 名带 Hurdle/Stp 类型后缀而官方名不带
    text = re.sub(r"^prix\s+(?:(?:de|du|des|la|le|l)\s+)?", "", text, flags=re.I)
    text = re.sub(r"(?:\s+(?:hurdle|hurdles|steeplechase|steeple chase|chase|stp\.?))+\s*$", "", text, flags=re.I)
    text = re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", text)
    return text


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None


def _ics_year_for(region: str, local_date: date | None, fallback_year: int) -> int:
    """生产赛事实际日期对应的 ICS 年度（跨年赛季地区按赛季归属）。"""
    if local_date is None:
        return fallback_year
    if region in SEASON_WINDOWS:
        for ics_year in (fallback_year, fallback_year + 1, fallback_year - 1):
            start, end = SEASON_WINDOWS[region](ics_year)
            if start <= local_date <= end:
                return ics_year
    return local_date.year


def _load_ics_rows(derived_dir: Path, years: list[int]) -> list[dict]:
    rows = []
    for region_dir in sorted(derived_dir.iterdir()):
        if not region_dir.is_dir():
            continue
        for year in years:
            path = region_dir / f"{year}.csv"
            if not path.is_file():
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    if row.get("record_type") != "catalog":
                        continue
                    rows.append(
                        {
                            "region": row["country"],
                            "year": int(row["year"]),
                            "series_key": row["series_key"],
                            "name": row["original_name"],
                            "canonical": row.get("canonical_name_original") or row["original_name"],
                            "grade": row["grade_text"],
                            "racecourse": row.get("racecourse", ""),
                            "discipline": row.get("discipline", ""),
                            "norm": _normalize_name(row["original_name"]),
                            "norm_canonical": _normalize_name(row.get("canonical_name_original") or ""),
                        }
                    )
    return rows


def _load_production_events(path: Path) -> list[dict]:
    events = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("id"):
                continue
            events.append(
                {
                    "id": row["id"],
                    "year": int(row["year"]),
                    "slug": row.get("slug", ""),
                    "series_key": row.get("series_key", ""),
                    "original_name": row.get("original_name", ""),
                    "chinese_name": row.get("chinese_name", ""),
                    "region": row.get("country_region", ""),
                    "racecourse": row.get("racecourse", ""),
                    "grade": row.get("normalized_grade", "") or row.get("grade_text", ""),
                    "local_date": _parse_date(row.get("local_date", "")),
                    "status": row.get("status", ""),
                    "visibility_status": row.get("visibility_status", ""),
                    "result_count": int(row.get("result_count") or 0),
                    "norm": _normalize_name(row.get("original_name", "")),
                    "norm_zh": _normalize_name(row.get("chinese_name", "")),
                }
            )
    return events


def _load_aliases(path: Path | None) -> dict[str, list[str]]:
    aliases: dict[str, list[str]] = defaultdict(list)
    if not path or not path.is_file():
        return aliases
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            normalized = _normalize_name(row.get("text", ""))
            if row.get("event_id") and normalized:
                aliases[row["event_id"]].append(normalized)
    return aliases


def reconcile(events: list[dict], ics_rows: list[dict], aliases: dict[str, list[str]], *, as_of: date) -> dict:
    ics_by_region_year: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in ics_rows:
        ics_by_region_year[(row["region"], row["year"])].append(row)

    matched_ics: set[int] = set()
    review_rows: list[dict] = []
    matched_pairs: list[tuple[dict, dict, str]] = []

    for event in events:
        region = event["region"]
        ics_year = _ics_year_for(region, event["local_date"], event["year"])
        candidates = ics_by_region_year.get((region, ics_year), [])
        # 跨年映射失败时回退到生产 year 本身对应的桶，避免漏报
        if not candidates and ics_year != event["year"]:
            candidates = ics_by_region_year.get((region, event["year"]), [])

        match = None
        match_type = ""
        if event["series_key"]:
            for row in candidates:
                if row["series_key"] == event["series_key"]:
                    match, match_type = row, "series_key"
                    break
        if match is None and event["norm"]:
            for row in candidates:
                if event["norm"] in {row["norm"], row["norm_canonical"]}:
                    match, match_type = row, "name"
                    break
        if match is None:
            event_aliases = set(aliases.get(event["id"], [])) | {event["norm_zh"]}
            for row in candidates:
                if event_aliases & {row["norm"], row["norm_canonical"]}:
                    match, match_type = row, "alias"
                    break

        quality_issues = []
        if event["local_date"] and event["year"] != event["local_date"].year:
            quality_issues.append("year_mismatch_review")
        if event["status"] == "finished" and event["result_count"] == 0:
            quality_issues.append("finished_without_results")
        if event["status"] == "scheduled" and event["local_date"] and event["local_date"] < as_of:
            quality_issues.append("stuck_scheduled")

        if match is not None:
            matched_ics.add(id(match))
            matched_pairs.append((event, match, match_type))
            if quality_issues:
                review_rows.append(_review_row(event, match, match_type, ";".join(quality_issues)))
        else:
            issue = ";".join([_unmatched_reason(event), *quality_issues])
            review_rows.append(_review_row(event, None, "none", issue))

    missing = []
    for row in ics_rows:
        if id(row) not in matched_ics:
            missing.append(row)
            review_rows.append(
                {
                    "kind": "missing_in_production",
                    "region": row["region"],
                    "ics_year": row["year"],
                    "ics_series_key": row["series_key"],
                    "ics_name": row["name"],
                    "ics_grade": row["grade"],
                    "ics_racecourse": row["racecourse"],
                    "production_id": "",
                    "production_name": "",
                    "production_year": "",
                    "production_status": "",
                    "production_result_count": "",
                    "match_type": "",
                    "issue": "missing_in_production",
                }
            )

    duplicate_pairs: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for event, match, _match_type in matched_pairs:
        duplicate_pairs[(match["region"], match["year"], match["series_key"])].append(event)
    for (region, year, series_key), group in sorted(duplicate_pairs.items()):
        if len(group) < 2:
            continue
        # 同日重叠才是疑似重复；不同日期说明是 ICS 同键归并下的不同场次（如 Newbury 多场 Gold Cup 让赛），属正常
        by_date: dict[str, list[dict]] = defaultdict(list)
        for event in group:
            by_date[str(event["local_date"])] .append(event)
        has_same_day_overlap = any(len(members) > 1 for members in by_date.values())
        if not has_same_day_overlap:
            continue
        for event in group:
            if len(by_date[str(event["local_date"])]) > 1:
                review_rows.append(
                    _review_row(event, {"series_key": series_key, "name": "", "grade": "", "racecourse": "", "year": year, "region": region}, "duplicate", "duplicate_same_day_events_for_ics_row")
                )

    summary: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for row in ics_rows:
        bucket = summary[row["region"]][str(row["year"])]
        bucket["expected"] += 1
        if id(row) in matched_ics:
            bucket["matched"] += 1
        else:
            bucket["missing_in_production"] += 1
    for event in events:
        ics_year = _ics_year_for(event["region"], event["local_date"], event["year"])
        bucket = summary[event["region"]][str(ics_year)]
        bucket["production_events"] += 1

    return {
        "summary": {region: dict(years) for region, years in sorted(summary.items())},
        "ics_row_count": len(ics_rows),
        "production_event_count": len(events),
        "missing_in_production": len(missing),
        "review_rows": review_rows,
    }


def _unmatched_reason(event: dict) -> str:
    grade = (event["grade"] or "").upper()
    if grade in DOMESTIC_ONLY_GRADES or grade.startswith("JPN"):
        return "production_only_domestic_grade"
    if grade and grade not in IN_SCOPE_GRADES:
        return f"production_grade_out_of_scope:{event['grade']}"
    return "production_not_matched_to_ics"


def _review_row(event: dict, match: dict | None, match_type: str, issue: str) -> dict:
    return {
        "kind": "production_event",
        "region": event["region"],
        "ics_year": match["year"] if match else "",
        "ics_series_key": match["series_key"] if match else "",
        "ics_name": match["name"] if match else "",
        "ics_grade": match["grade"] if match else "",
        "ics_racecourse": match["racecourse"] if match else "",
        "production_id": event["id"],
        "production_name": event["original_name"] or event["chinese_name"],
        "production_year": event["year"],
        "production_status": event["status"],
        "production_result_count": event["result_count"],
        "match_type": match_type,
        "issue": issue,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-csv", required=True)
    parser.add_argument("--aliases-csv", default="")
    parser.add_argument("--ics-derived-dir", required=True)
    parser.add_argument("--years", required=True, help="如 2025-2026")
    parser.add_argument("--as-of-date", default=date.today().isoformat(), help="stuck_scheduled 判定的基准日期")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    year_parts = args.years.split("-")
    years = list(range(int(year_parts[0]), int(year_parts[-1]) + 1))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    events = _load_production_events(Path(args.production_csv))
    ics_rows = _load_ics_rows(Path(args.ics_derived_dir), years)
    aliases = _load_aliases(Path(args.aliases_csv) if args.aliases_csv else None)

    result = reconcile(events, ics_rows, aliases, as_of=date.fromisoformat(args.as_of_date))
    review_rows = result.pop("review_rows")

    ledger_path = output_dir / "gap_ledger.json"
    ledger_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    review_path = output_dir / "gap_review.csv"
    fieldnames = [
        "kind", "region", "ics_year", "ics_series_key", "ics_name", "ics_grade", "ics_racecourse",
        "production_id", "production_name", "production_year", "production_status",
        "production_result_count", "match_type", "issue",
    ]
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)

    print(f"ics_rows={result['ics_row_count']} production_events={result['production_event_count']} "
          f"missing_in_production={result['missing_in_production']} review_rows={len(review_rows)}")
    print(f"ledger={ledger_path} review={review_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

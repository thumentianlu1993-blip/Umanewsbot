#!/usr/bin/env python3
"""ICS 缺口行 vs 生产导出的逐场核验：区分"真实缺场"与"身份未挂接"。

输入：对账工具产出的 gap_review.csv（missing_in_production 行）、生产赛事导出 CSV、
生产别名导出 CSV。按（规范化名称+马场，必要时别名）在生产侧找同年候选：
- 同年同场存在 → exists_same_year（不是缺场，是身份挂接问题）
- 同年同名不同场 → review_name_course_mismatch
- 无候选 → truly_missing
输出 verified_gaps.csv（逐场分类 + 命中证据），不写数据库、不触网。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)
    text = re.sub(r"(?:\s+(?:hurdle|hurdles|steeplechase|steeple chase|chase|stp\.?|s\.?|stakes|h\.?))+\s*$", "", text)
    text = re.sub(r"^prix\s+(?:(?:de|du|des|la|le|l)\s+)?", "", text)
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", text)


def _normalize_course(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^a-z\u3040-\u30ff\u3400-\u9fff]+", "", text)


def verify_gaps(*, review_csv: Path, production_csv: Path, aliases_csv: Path | None, ics_year: str) -> dict:
    events = []
    with production_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("id"):
                continue
            events.append(row)
    aliases: dict[str, list[str]] = defaultdict(list)
    if aliases_csv and aliases_csv.is_file():
        with aliases_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("event_id"):
                    aliases[row["event_id"]].append(_normalize(row.get("text", "")))

    missing = [
        row
        for row in csv.DictReader(review_csv.open("r", encoding="utf-8-sig", newline=""))
        if row.get("issue") == "missing_in_production" and row.get("ics_year") == ics_year
    ]

    by_region: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        by_region[event.get("country_region", "")].append(event)

    out_rows = []
    counts = {"exists_same_year": 0, "exists_different_course": 0, "truly_missing": 0, "review_name_course_mismatch": 0}
    for row in missing:
        region = row["region"]
        name_key = _normalize(row["ics_name"])
        course_key = _normalize_course(row["ics_racecourse"])
        candidates = []
        for event in by_region.get(region, []):
            if str(event.get("year") or "") != ics_year:
                continue
            names = {_normalize(event.get("original_name", "")), _normalize(event.get("chinese_name", ""))}
            names.update(aliases.get(event["id"], []))
            if name_key and name_key in names:
                candidates.append(event)
        if not candidates:
            out_rows.append(
                {
                    "region": region,
                    "ics_year": ics_year,
                    "ics_name": row["ics_name"],
                    "ics_grade": row["ics_grade"],
                    "ics_racecourse": row["ics_racecourse"],
                    "series_key": row.get("ics_series_key", ""),
                    "classification": "truly_missing",
                    "production_event_id": "",
                    "production_name": "",
                    "production_date": "",
                    "production_course": "",
                }
            )
            counts["truly_missing"] += 1
            continue
        same_course = [
            event
            for event in candidates
            if course_key and _normalize_course(event.get("racecourse", "")) == course_key
        ]
        chosen = same_course or candidates
        classification = "exists_same_year" if same_course else "exists_different_course"
        counts[classification] += 1
        for event in chosen:
            out_rows.append(
                {
                    "region": region,
                    "ics_year": ics_year,
                    "ics_name": row["ics_name"],
                    "ics_grade": row["ics_grade"],
                    "ics_racecourse": row["ics_racecourse"],
                    "series_key": row.get("ics_series_key", ""),
                    "classification": classification,
                    "production_event_id": event["id"],
                    "production_name": event.get("original_name", ""),
                    "production_date": event.get("local_date", ""),
                    "production_course": event.get("racecourse", ""),
                }
            )
    return {
        "ics_year": ics_year,
        "missing_rows": len(missing),
        "counts": counts,
        "rows": out_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-csv", required=True)
    parser.add_argument("--production-csv", required=True)
    parser.add_argument("--aliases-csv", default="")
    parser.add_argument("--ics-year", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = verify_gaps(
        review_csv=Path(args.review_csv),
        production_csv=Path(args.production_csv),
        aliases_csv=Path(args.aliases_csv) if args.aliases_csv else None,
        ics_year=args.ics_year,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result["rows"][0].keys()) if result["rows"] else ["region"])
        writer.writeheader()
        writer.writerows(result["rows"])
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

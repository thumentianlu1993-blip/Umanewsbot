#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from prepare_uk_sportinglife_race_detail_candidates import (
    SL_BASE_URL,
    _download,
    _parse_detail_page,
    _slugify,
    _source_filename,
)


GAP_RACES = [
    {
        "slug": "uk-bha-jump-2026-0310-033",
        "actual_date": "2026-03-12",
        "actual_course": "Cheltenham",
        "race_id": 899895,
        "race_name": "Close Brothers Mares' Hurdle (Registered As The David Nicholson Mares' Hurdle) (Grade 1) (GBB Race)",
    },
    {
        "slug": "uk-bha-jump-2026-0311-037",
        "actual_date": "2026-03-11",
        "actual_course": "Cheltenham",
        "race_id": 900310,
        "race_name": "Weatherbys Champion Bumper (In Memory Of Sir Johnny Weatherby) (Standard Open NH Flat Race) (Grade 1) (GBB Race)",
    },
    {
        "slug": "uk-bha-jump-2026-0415-060",
        "actual_date": "2026-04-15",
        "actual_course": "Haydock",
        "race_id": 912216,
        "race_name": "Unibet Silver Trophy Handicap Chase (Grade 2 Limited Handicap) (GBB Race)",
    },
    {
        "slug": "uk-bha-flat-2026-0530-030",
        "actual_date": "2026-05-30",
        "actual_course": "Carlisle",
        "race_id": 920112,
        "race_name": "Betway Lester Piggott Fillies' Stakes (Fillies' And Mares' Group 3)",
    },
    {
        "slug": "uk-bha-flat-2026-0618-048",
        "actual_date": "2026-06-20",
        "actual_course": "Royal Ascot",
        "race_id": 923457,
        "race_name": "Norfolk Stakes (Group 2)",
    },
    {
        "slug": "uk-bha-flat-2026-0704-057",
        "actual_date": "2026-07-04",
        "actual_course": "Newmarket",
        "race_id": 926083,
        "race_name": "Betway Lancashire Oaks (Fillies' & Mares' Group 2)",
    },
]


def _read_events(paths: list[Path]) -> dict[str, dict]:
    events: dict[str, dict] = {}
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                events[row["slug"]] = row
    return events


def _detail_url(item: dict) -> str:
    return (
        f"{SL_BASE_URL}/racing/results/{item['actual_date']}/"
        f"{_slugify(item['actual_course'])}/{item['race_id']}/{_slugify(item['race_name'])}"
    )


def prepare_candidates(args) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    events = _read_events([Path(path) for path in args.events_csv])
    jsonl_path = output_dir / "uk_sportinglife_gap_detail_candidates_2026.jsonl"
    review_path = output_dir / "uk_sportinglife_gap_detail_review_2026.csv"
    summary = {
        "source": "sporting_life_gap_result_detail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "skipped": [],
        "errors": [],
    }
    review_rows = []
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for item in GAP_RACES:
            event = events.get(item["slug"])
            if not event:
                summary["errors"].append({"slug": item["slug"], "error": "missing_event_csv_row"})
                continue
            url = _detail_url(item)
            try:
                html = _download(
                    url,
                    source_dir / _source_filename("source_sl_detail", str(item["race_id"])),
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                )
                runners, results, metadata = _parse_detail_page(html, source_url=url)
            except Exception as exc:
                summary["errors"].append({"slug": item["slug"], "url": url, "error": str(exc)})
                if args.fail_fast:
                    raise
                continue
            if not runners or not results:
                skipped = {
                    "slug": item["slug"],
                    "url": url,
                    "reason": "empty_detail",
                    "runners": len(runners),
                    "results": len(results),
                    "race_title": metadata.get("race_title", ""),
                }
                summary["skipped"].append(skipped)
                if args.fail_fast:
                    raise RuntimeError(f"empty Sporting Life detail parse: {skipped}")
                continue
            record = {
                "year": int(event["year"]),
                "slug": item["slug"],
                "source_name": "sporting_life_gap",
                "source_url": url,
                "modules": {"runners": {"items": runners}, "results": {"items": results}},
                "metadata": {**metadata, "actual_date": item["actual_date"], "actual_course": item["actual_course"]},
            }
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["runner_items"] += len(runners)
            summary["result_items"] += len(results)
            review_rows.append(
                {
                    "slug": item["slug"],
                    "original_name": event["original_name"],
                    "actual_date": item["actual_date"],
                    "actual_course": item["actual_course"],
                    "source_url": url,
                    "runners": len(runners),
                    "results": len(results),
                    "winner": results[0]["horse_name"] if results else "",
                    "race_title": metadata.get("race_title", ""),
                }
            )
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "actual_date", "actual_course", "source_url", "runners", "results", "winner", "race_title"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate UK 2026 gap runner/result candidates from specific Sporting Life race ids.")
    parser.add_argument("--events-csv", nargs="+", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare_candidates(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

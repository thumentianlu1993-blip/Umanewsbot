#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from race_event_request_budget import before_network_request
from race_event_source_cache import write_source_cache_text

from prepare_uk_sportinglife_race_detail_candidates import (
    SL_BASE_URL,
    _next_data,
    _slugify,
    _source_filename,
    _strip_country_suffix,
)


def _read_review_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                slug = row.get("slug") or ""
                source_url = row.get("source_url") or ""
                if not slug or not source_url or slug in seen:
                    continue
                seen.add(slug)
                rows.append(row)
    return rows


def _race_id_from_url(url: str) -> str:
    match = re.search(r"/racing/results/\d{4}-\d{2}-\d{2}/[^/]+/(\d+)/", url)
    return match.group(1) if match else ""


def _cached_html(
    url: str,
    *,
    race_id: str,
    source_dir: Path,
    reuse_source_dirs: list[Path],
    allow_network: bool,
    timeout: int,
    sleep_seconds: float,
) -> str:
    filename = _source_filename("source_sl_history", race_id or url)
    path = source_dir / filename
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    detail_filename = _source_filename("source_sl_detail", race_id)
    for reuse_dir in reuse_source_dirs:
        reuse_path = reuse_dir / detail_filename
        if reuse_path.exists():
            text = reuse_path.read_text(encoding="utf-8", errors="replace")
            write_source_cache_text(path, text, source_url=f"reuse:{reuse_path}")
            return text
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if sleep_seconds > 0:
        import time

        time.sleep(sleep_seconds)
    before_network_request(url)
    result = subprocess.run(
        [
            "curl",
            "-L",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            str(timeout),
            "-A",
            "UmaFansBot/1.0 (+https://umafans.run; low-frequency history import)",
            url,
        ],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"下载失败 exit={result.returncode}: {stderr}")
    text = result.stdout.decode("utf-8", errors="replace")
    write_source_cache_text(path, text, source_url=url)
    return text


def _race_year_from_summary(summary: dict) -> int | None:
    meeting = summary.get("meeting_summary") or {}
    date_text = str(meeting.get("date") or "")
    try:
        return int(date_text[:4])
    except ValueError:
        return None


def _winner_from_ride(ride: dict, *, winner_year: int, source_url: str, source_kind: str) -> dict | None:
    horse = ride.get("horse") or {}
    horse_name = _strip_country_suffix(str(horse.get("name") or ""))
    if not horse_name:
        return None
    race_summary = ride.get("race_summary") or {}
    meeting_summary = ride.get("meeting_summary") or {}
    meeting_date = meeting_summary.get("date") or race_summary.get("date") or ""
    racecourse = ((meeting_summary.get("course") or {}).get("name") or "") or race_summary.get("course_name") or ""
    return {
        "winner_year": winner_year,
        "horse_name": horse_name,
        "jockey_name": ((ride.get("jockey") or {}).get("name") or ""),
        "trainer_name": ((ride.get("trainer") or {}).get("name") or ""),
        "finish_time": str((race_summary or {}).get("winning_time") or ""),
        "margin": str(ride.get("finish_distance") or ""),
        "source_refs": {
            "primary": source_url,
            "source_language": "en",
            "source_kind": source_kind,
            "sporting_life_race_id": (race_summary.get("race_summary_reference") or {}).get("id"),
            "sporting_life_ride_id": (ride.get("ride_reference") or {}).get("id"),
            "official_race_name": race_summary.get("name") or "",
            "meeting_date": meeting_date,
            "racecourse": racecourse,
            "horse_id": (horse.get("horse_reference") or {}).get("id"),
            "horse_slug": horse.get("slug") or "",
            "horse_name_raw": horse.get("name") or "",
        },
    }


def _current_winner(race: dict, *, winner_year: int, source_url: str) -> dict | None:
    for ride in race.get("rides") or []:
        try:
            if int(ride.get("finish_position") or 0) == 1:
                race_summary = race.get("race_summary") or {}
                enriched = {**ride, "race_summary": race_summary}
                return _winner_from_ride(
                    enriched,
                    winner_year=winner_year,
                    source_url=source_url,
                    source_kind="sporting_life_result_detail_history_current",
                )
        except (TypeError, ValueError):
            continue
    return None


def _previous_url(winner: dict) -> tuple[str, str, int | None]:
    race_summary = winner.get("race_summary") or {}
    race_id = str((race_summary.get("race_summary_reference") or {}).get("id") or "")
    meeting_summary = winner.get("meeting_summary") or {}
    date_text = str(meeting_summary.get("date") or "")
    course = ((meeting_summary.get("course") or {}).get("name") or "")
    race_name = race_summary.get("name") or ""
    if not race_id or not date_text:
        return "", "", None
    url = (
        f"{SL_BASE_URL}/racing/results/{date_text}/"
        f"{_slugify(course)}/{race_id}/{_slugify(race_name)}"
    )
    return urljoin(SL_BASE_URL, url), race_id, _race_year_from_summary(winner)


def _walk_history(
    source_url: str,
    *,
    min_year: int,
    source_dir: Path,
    reuse_source_dirs: list[Path],
    allow_network: bool,
    timeout: int,
    sleep_seconds: float,
    max_depth: int,
) -> tuple[list[dict], list[dict]]:
    items: dict[int, dict] = {}
    diagnostics: list[dict] = []
    url = source_url
    race_id = _race_id_from_url(url)
    depth = 0
    seen_urls: set[str] = set()
    while url and url not in seen_urls and depth <= max_depth:
        seen_urls.add(url)
        try:
            html = _cached_html(
                url,
                race_id=race_id,
                source_dir=source_dir,
                reuse_source_dirs=reuse_source_dirs,
                allow_network=allow_network,
                timeout=timeout,
                sleep_seconds=sleep_seconds,
            )
            race = _next_data(html)["props"]["pageProps"]["race"]
        except Exception as exc:
            diagnostics.append({"url": url, "error": str(exc)})
            break
        current_year = None
        summary = race.get("race_summary") or {}
        date_text = str(summary.get("date") or "")
        if date_text[:4].isdigit():
            current_year = int(date_text[:4])
        if current_year and current_year >= min_year:
            current = _current_winner(race, winner_year=current_year, source_url=url)
            if current:
                items[current_year] = current
        previous = (race.get("last_years_winners") or [])
        if not previous:
            break
        prev_winner = previous[0]
        prev_url, prev_race_id, prev_year = _previous_url(prev_winner)
        if prev_year and prev_year >= min_year:
            item = _winner_from_ride(
                prev_winner,
                winner_year=prev_year,
                source_url=url,
                source_kind="sporting_life_previous_winners",
            )
            if item:
                item["source_refs"]["previous_race_url"] = prev_url
                items[prev_year] = item
        if prev_year is not None and prev_year <= min_year:
            break
        url = prev_url
        race_id = prev_race_id
        depth += 1
    return [items[year] for year in sorted(items, reverse=True)], diagnostics


def prepare_candidates(args) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    reuse_source_dirs = [Path(path) for path in args.reuse_source_dir]
    rows = _read_review_rows([Path(path) for path in args.review_csv])
    if args.limit:
        rows = rows[: args.limit]

    jsonl_path = output_dir / "uk_sportinglife_history_winner_candidates_2026.jsonl"
    review_path = output_dir / "uk_sportinglife_history_winner_review_2026.csv"
    summary = {
        "source": "sporting_life_previous_winners_chain",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": len(rows),
        "events": 0,
        "history_items": 0,
        "events_without_history": 0,
        "events_skipped_partial": 0,
        "skipped": [],
        "errors": [],
    }
    review_rows = []
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for row in rows:
            items, diagnostics = _walk_history(
                row["source_url"],
                min_year=args.min_year,
                source_dir=source_dir,
                reuse_source_dirs=reuse_source_dirs,
                allow_network=args.allow_network,
                timeout=args.timeout_seconds,
                sleep_seconds=args.sleep_seconds,
                max_depth=args.max_depth,
            )
            for diagnostic in diagnostics:
                summary["errors"].append({"slug": row["slug"], **diagnostic})
            if not items:
                summary["events_without_history"] += 1
                continue
            if diagnostics and not args.allow_partial_history:
                summary["events_skipped_partial"] += 1
                summary["skipped"].append(
                    {
                        "slug": row["slug"],
                        "reason": "partial_history_chain",
                        "history_items": len(items),
                        "diagnostics": diagnostics,
                    }
                )
                continue
            record = {
                "year": 2026,
                "slug": row["slug"],
                "source_name": "sporting_life_previous_winners_chain",
                "source_url": row["source_url"],
                "modules": {"history_winners": {"items": items}},
                "metadata": {
                    "source_kind": "sporting_life_previous_winners_chain",
                    "history_scope": f"{args.min_year}-2026_via_previous_winners_chain",
                    "partial_history": bool(diagnostics),
                    "diagnostics": diagnostics,
                },
            }
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["history_items"] += len(items)
            review_rows.append(
                {
                    "slug": row["slug"],
                    "original_name": row.get("original_name", ""),
                    "history_count": len(items),
                    "first_year": min(item["winner_year"] for item in items),
                    "latest_year": max(item["winner_year"] for item in items),
                    "latest_winner": items[0]["horse_name"],
                    "source_url": row["source_url"],
                }
            )
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "history_count", "first_year", "latest_year", "latest_winner", "source_url"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate UK 2026 historical winner candidates from Sporting Life previous-winners chains.")
    parser.add_argument("--review-csv", nargs="+", required=True)
    parser.add_argument("--reuse-source-dir", nargs="*", default=[])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-year", type=int, default=2020)
    parser.add_argument("--max-depth", type=int, default=8)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-partial-history", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    args = parser.parse_args()
    print(json.dumps(prepare_candidates(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

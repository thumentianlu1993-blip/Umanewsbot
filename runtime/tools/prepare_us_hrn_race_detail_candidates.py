#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from race_event_request_budget import before_network_request
from race_event_safe_http import fetch_https, validate_https_url
from race_event_source_cache import write_source_cache_text

from bs4 import BeautifulSoup


HRN_BASE_URL = "https://entries.horseracingnation.com"


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _norm(value: str) -> str:
    value = value.lower()
    value = value.replace("&", " and ")
    value = re.sub(r"\bstakes\b", "s", value)
    value = re.sub(r"\bstake\b", "s", value)
    value = re.sub(r"\bs\.\b", "s", value)
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def _event_match_keys(value: str) -> list[str]:
    keys = []
    raw = value or ""
    variants = [raw]
    variants.append(re.sub(r"\s*\([^)]*\)", "", raw))
    variants.append(re.sub(r"\s*\[[^]]*\]", "", raw))
    variants.append(re.split(r"\s+PRESENTED BY\s+", raw, flags=re.IGNORECASE)[0])
    variants.append(re.split(r"\s+AT\s+", raw, flags=re.IGNORECASE)[0])
    for variant in variants:
        key = _norm(variant)
        if key and key not in keys:
            keys.append(key)
    return keys


def _race_no_from_chart_url(source_refs: dict) -> str:
    chart_url = source_refs.get("chart_url") or ""
    match = re.search(r"[?&]RACE=(\d+)", chart_url, re.IGNORECASE)
    return match.group(1) if match else ""


def _download(url: str, path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> str:
    validate_https_url(url, allowed_hosts=("horseracingnation.com",))
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    before_network_request(url)
    body, _response = fetch_https(
        url,
        allowed_hosts=("horseracingnation.com",),
        timeout=timeout,
        headers={"User-Agent": "umanewsbot/1.0 (+https://umafans.run; low-frequency race detail import)"},
    )
    text = body.decode("utf-8", errors="replace")
    write_source_cache_text(path, text, source_url=url)
    return text


def _slug_filename(prefix: str, value: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return f"{prefix}_{key[-120:]}.html"


def _read_events(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _approved_result_url(event: dict, *, provider: str) -> str:
    try:
        source_refs = json.loads(event.get("source_refs") or "{}")
    except (TypeError, json.JSONDecodeError):
        return ""
    evidence = (((source_refs.get("detail_discovery") or {}).get("urls") or {}).get("result_url") or {})
    if evidence.get("source_provider") != provider:
        return ""
    return str(evidence.get("url") or "").strip()


def _track_links_from_date_page(html: str, *, source_url: str, race_date: str) -> dict[str, dict]:
    soup = BeautifulSoup(html, "lxml")
    links: dict[str, dict] = {}
    pattern = re.compile(rf"/entries-results/([^/]+)/{re.escape(race_date)}")
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        match = pattern.search(href)
        if not match:
            continue
        track_name = _collapse(anchor.get_text(" ", strip=True))
        if not track_name:
            continue
        links[_norm(track_name)] = {
            "track_name": track_name,
            "track_slug": match.group(1),
            "url": urljoin(source_url, href),
        }
    return links


def _match_track(track_links: dict[str, dict], racecourse: str) -> dict | None:
    key = _norm(racecourse)
    if key in track_links:
        return track_links[key]
    for link_key, value in track_links.items():
        if key and (key in link_key or link_key in key):
            return value
    aliases = {
        "belmontatthebiga": "biga",
        "belmontpark": "biga",
        "aqueduct": "aqueduct",
        "churchilldowns": "churchilldowns",
        "santaanitapark": "santaanita",
        "losalamitosracecourse": "losalamitosday",
    }
    alias = aliases.get(key)
    if alias:
        for link_key, value in track_links.items():
            if alias in link_key:
                return value
    return None


try:
    from stable.race_reference_parsers.horse_racing_nation import (
        _parse_track_day as _shared_parse_track_day,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
    from stable.race_reference_parsers.horse_racing_nation import (
        _parse_track_day as _shared_parse_track_day,
    )


def _parse_track_day(html: str, *, source_url: str) -> list[dict]:
    """Keep the historical CLI on the same parse-only implementation."""
    return _shared_parse_track_day(html, source_url=source_url)


def prepare_candidates(args) -> dict:
    events = [
        event
        for event in _read_events(Path(args.events_csv))
        if event.get("status") == "finished"
    ]
    if args.limit:
        events = events[: args.limit]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    jsonl_path = output_dir / "us_hrn_detail_candidates_2026.jsonl"
    review_csv_path = output_dir / "us_hrn_detail_review_2026.csv"

    summary = {
        "source": "horse_racing_nation_track_day",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "date_pages": 0,
        "track_pages": 0,
        "skipped": [],
        "errors": [],
    }
    date_cache: dict[str, dict[str, dict]] = {}
    track_cache: dict[str, list[dict]] = {}
    review_rows = []

    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for event in events:
            race_date = event.get("local_date") or ""
            racecourse = event.get("racecourse") or ""
            if not race_date or not racecourse:
                summary["skipped"].append({"slug": event["slug"], "reason": "missing_date_or_racecourse"})
                continue
            try:
                track_url = _approved_result_url(event, provider="us_hrn")
                if track_url:
                    match = re.search(r"/entries-results/([^/]+)/\d{4}-\d{2}-\d{2}", track_url)
                    track = {
                        "track_name": racecourse,
                        "track_slug": match.group(1) if match else _norm(racecourse),
                        "url": track_url,
                    }
                else:
                    if race_date not in date_cache:
                        date_url = f"{HRN_BASE_URL}/entries-results/{race_date}"
                        date_html = _download(
                            date_url,
                            source_dir / _slug_filename("source_hrn_date", race_date),
                            allow_network=args.allow_network,
                            timeout=args.timeout_seconds,
                            sleep_seconds=args.sleep_seconds,
                        )
                        date_cache[race_date] = _track_links_from_date_page(date_html, source_url=date_url, race_date=race_date)
                        summary["date_pages"] += 1
                    track = _match_track(date_cache[race_date], racecourse)
                    if track is None:
                        summary["skipped"].append({"slug": event["slug"], "reason": "track_not_found", "race_date": race_date, "racecourse": racecourse})
                        continue
                    track_url = track["url"]
                if track_url not in track_cache:
                    track_html = _download(
                        track_url,
                        source_dir / _slug_filename("source_hrn_track", f"{track['track_slug']}_{race_date}"),
                        allow_network=args.allow_network,
                        timeout=args.timeout_seconds,
                        sleep_seconds=args.sleep_seconds,
                    )
                    track_cache[track_url] = _parse_track_day(track_html, source_url=track_url)
                    summary["track_pages"] += 1
                source_refs = json.loads(event.get("source_refs") or "{}")
                chart_race_no = _race_no_from_chart_url(source_refs)
                candidates = []
                if chart_race_no:
                    candidates = [race for race in track_cache[track_url] if race["race_no"] == chart_race_no]
                if not candidates:
                    event_keys = _event_match_keys(event["original_name"])
                    candidates = [
                        race
                        for race in track_cache[track_url]
                        if any(key and key in _norm(race["race_meta"]) for key in event_keys)
                    ]
                if not candidates:
                    summary["skipped"].append(
                        {
                            "slug": event["slug"],
                            "reason": "race_name_not_found",
                            "track_url": track_url,
                            "original_name": event["original_name"],
                            "available_races": [race["race_title"] for race in track_cache[track_url]],
                        }
                    )
                    continue
                parsed = candidates[0]
                if not parsed["runners"]:
                    summary["skipped"].append({"slug": event["slug"], "reason": "no_runner_rows", "track_url": track_url})
                    continue
            except Exception as exc:
                summary["errors"].append({"slug": event.get("slug"), "error": str(exc)})
                if args.fail_fast:
                    raise
                continue

            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": "horse_racing_nation",
                "source_url": track_url,
                "modules": {
                    "runners": {"items": parsed["runners"]},
                    "results": {"items": parsed["results"]},
                },
                "metadata": {
                    "track_name": track["track_name"],
                    "track_slug": track["track_slug"],
                    "race_no": parsed["race_no"],
                    "race_title": parsed["race_title"],
                    "race_meta": parsed["race_meta"],
                    "row_count": len(parsed["runners"]),
                    "result_count": len(parsed["results"]),
                    "result_scope": "HRN payout rows plus Also rans order; no official margins/times.",
                },
            }
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["runner_items"] += len(parsed["runners"])
            summary["result_items"] += len(parsed["results"])
            review_rows.append(
                {
                    "slug": event["slug"],
                    "original_name": event["original_name"],
                    "racecourse": racecourse,
                    "source_url": track_url,
                    "race_no": parsed["race_no"],
                    "runners": len(parsed["runners"]),
                    "results": len(parsed["results"]),
                    "winner": parsed["results"][0]["horse_name"] if parsed["results"] else "",
                    "race_title": parsed["race_title"],
                    "race_meta": parsed["race_meta"],
                }
            )

    with review_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "racecourse", "source_url", "race_no", "runners", "results", "winner", "race_title", "race_meta"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate US 2026 runner/result candidate JSONL from Horse Racing Nation track-day pages.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare_candidates(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from race_event_request_budget import before_network_request
from race_event_source_cache import write_source_cache_text

from bs4 import BeautifulSoup


HRN_BASE_URL = "https://entries.horseracingnation.com"
COUNTRY_SUFFIX_RE = re.compile(r"\s*[\(\（][A-Z]{2,3}[\)\）]\s*$")
SPEED_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")
RACE_HEADING_RE = re.compile(r"Race\s*#\s*(\d+)(?:,\s*([0-9:]+\s*[AP]M))?", re.IGNORECASE)


def _text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


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


def _display_horse_name(value: str) -> str:
    value = _collapse(value)
    value = SPEED_SUFFIX_RE.sub("", value).strip()
    value = COUNTRY_SUFFIX_RE.sub("", value).strip()
    return value


def _split_trainer_jockey(value: str) -> tuple[str, str]:
    value = _collapse(value)
    if not value:
        return "", ""
    # HRN renders trainer and jockey in a single text cell. Keep the raw cell in
    # source_refs; this heuristic gives usable display fields without claiming
    # official separation when names have particles or initials.
    parts = value.split()
    if len(parts) <= 3:
        return value, ""
    return " ".join(parts[:-2]), " ".join(parts[-2:])


def _trainer_jockey_from_cell(cell) -> tuple[str, str, str]:
    parts = [_text(part) for part in cell.find_all("p", recursive=False) if _text(part)]
    raw = _text(cell)
    if len(parts) >= 2:
        return parts[0], parts[1], raw
    trainer, jockey = _split_trainer_jockey(raw)
    return trainer, jockey, raw


def _download(url: str, path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    request = Request(url, headers={"User-Agent": "umanewsbot/1.0 (+https://umafans.run; low-frequency race detail import)"})
    before_network_request(url)
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
    text = body.decode("utf-8", errors="replace")
    write_source_cache_text(path, text, source_url=url)
    return text


def _slug_filename(prefix: str, value: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return f"{prefix}_{key[-120:]}.html"


def _read_events(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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


def _race_meta_after_heading(heading) -> str:
    node = heading.find_next_sibling()
    while node is not None:
        if getattr(node, "name", None) == "div" and "row" in (node.get("class") or []):
            text = _collapse(node.get_text(" ", strip=True))
            if text:
                return text
        node = node.find_next_sibling()
    return ""


def _race_title_from_meta(meta: str) -> str:
    parts = [part.strip() for part in meta.split(",")]
    if len(parts) >= 3:
        title = parts[2]
    else:
        title = meta
    title = title.split("Purse:", 1)[0].strip()
    title = title.split("|", 1)[0].strip()
    return _collapse(title)


def _horse_name_from_entry_cell(cell) -> tuple[str, str, str]:
    link = cell.find("a", href=True)
    raw = _collapse(link.get_text(" ", strip=True) if link else cell.get_text(" ", strip=True))
    href = link["href"] if link else ""
    return _display_horse_name(raw), raw, href


def _parse_entries(table, *, source_url: str, race_no: str, race_meta: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for index, tr in enumerate(table.find_all("tr"), start=1):
        cells = tr.find_all(["td", "th"], recursive=False)
        if len(cells) < 6:
            continue
        horse_name, raw_horse_name, horse_url = _horse_name_from_entry_cell(cells[2])
        if not horse_name:
            continue
        horse_number = _text(cells[1])
        dedupe_key = (horse_number, horse_name, horse_url)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        trainer, jockey, trainer_jockey_raw = _trainer_jockey_from_cell(cells[3])
        rows.append(
            {
                "sort_order": len(rows) + 1,
                "horse_number": horse_number,
                "barrier": "",
                "horse_name": horse_name,
                "jockey_name": jockey,
                "trainer_name": trainer,
                "odds_value": _text(cells[5]),
                "running_status": "declared",
                "source_refs": {
                    "primary": source_url,
                    "source_language": "en",
                    "source_kind": "horse_racing_nation_track_day",
                    "hrn_race_no": race_no,
                    "hrn_race_meta": race_meta,
                    "horse_name_raw": raw_horse_name,
                    "horse_url": horse_url,
                    "trainer_jockey_raw": trainer_jockey_raw,
                },
            }
        )
    return rows


def _parse_payout_results(table) -> list[str]:
    names: list[str] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"], recursive=False)
        if len(cells) < 2:
            continue
        raw = _text(cells[0])
        if not raw or raw.lower().startswith("runner"):
            continue
        if raw.startswith("*"):
            continue
        names.append(_display_horse_name(raw))
    return names


def _parse_also_rans(after_node) -> list[str]:
    if after_node is None:
        return []
    for text_node in after_node.find_all_next(string=lambda value: value and "Also rans:" in value):
        value = _collapse(str(text_node))
        value = value.split("Also rans:", 1)[1].strip()
        value = value.split("Pool", 1)[0].strip()
        return [_display_horse_name(name.strip()) for name in value.split(",") if name.strip()]
    return []


def _parse_track_day(html: str, *, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    races: list[dict] = []
    for heading in soup.find_all("h2"):
        heading_text = _text(heading)
        match = RACE_HEADING_RE.search(heading_text)
        if not match:
            continue
        race_no = match.group(1)
        start_time = match.group(2) or ""
        race_meta = _race_meta_after_heading(heading)
        race_title = _race_title_from_meta(race_meta)
        entries_table = heading.find_next("table", class_=lambda classes: classes and "table-entries" in classes)
        if entries_table is None:
            continue
        payout_table = entries_table.find_next("table", class_=lambda classes: classes and "table-payouts" in classes)
        runners = _parse_entries(entries_table, source_url=source_url, race_no=race_no, race_meta=race_meta)
        payout_names = _parse_payout_results(payout_table) if payout_table else []
        also_rans = _parse_also_rans(payout_table) if payout_table else []
        result_names: list[str] = []
        for name in payout_names + also_rans:
            if name and name not in result_names:
                result_names.append(name)
        by_name = {runner["horse_name"]: runner for runner in runners}
        results = []
        for position, horse_name in enumerate(result_names, start=1):
            runner = by_name.get(horse_name)
            if runner is None:
                continue
            results.append(
                {
                    "finish_position": position,
                    "horse_number": runner["horse_number"],
                    "barrier": runner["barrier"],
                    "horse_name": runner["horse_name"],
                    "jockey_name": runner["jockey_name"],
                    "trainer_name": runner["trainer_name"],
                    "odds_value": runner.get("odds_value", ""),
                    "running_status": runner.get("running_status", "declared"),
                    "is_confirmed": True,
                    "source_refs": {
                        **runner["source_refs"],
                        "official_finish_position": position,
                        "hrn_result_source": "payout_table_plus_also_rans",
                    },
                }
            )
        races.append(
            {
                "race_no": race_no,
                "start_time": start_time,
                "race_meta": race_meta,
                "race_title": race_title,
                "race_title_key": _norm(race_title),
                "runners": runners,
                "results": results,
            }
        )
    return races


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

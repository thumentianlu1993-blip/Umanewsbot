#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from race_event_request_budget import before_network_request
from race_event_safe_http import fetch_https, validate_https_url
from race_event_source_cache import write_source_cache_text

from bs4 import BeautifulSoup


BASE_URL = "https://www.zeturf.fr"
COUNTRY_SUFFIX_RE = re.compile(r"\s*[\(\（][A-Z]{2,3}[\)\）]\s*$")
STOPWORDS = {
    "al",
    "arc",
    "barriere",
    "by",
    "coolmore",
    "d",
    "darley",
    "de",
    "des",
    "du",
    "emirates",
    "et",
    "fonds",
    "france",
    "groupe",
    "hong",
    "khan",
    "la",
    "le",
    "les",
    "l",
    "longines",
    "pmu",
    "pool",
    "prix",
    "qatar",
    "racing",
    "saint",
    "shadwell",
    "studs",
    "sumbe",
    "the",
    "world",
    # Venue words commonly appear in French race titles and cause false positives
    # between multiple races on the same card.
    "auteuil",
    "chantilly",
    "cloud",
    "compiegne",
    "criterium",
    "deauville",
    "longchamp",
    "paris",
}

ZETURF_SERIES_ALIASES = {
    "france-chantilly-g-p-de": ("Grand Prix de Chantilly",),
    "france-paris-g-p-de": ("Grand Prix de Paris",),
}


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _ascii(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in value if not unicodedata.combining(char))


def _slugify(value: str) -> str:
    value = _ascii(value).lower().replace("&", " et ")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "race"


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii(value).lower())


def _tokens(value: str) -> set[str]:
    value = _ascii(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    tokens = set()
    for token in value.split():
        if len(token) <= 2 or token in STOPWORDS or token.isdigit():
            continue
        tokens.add(token)
    return tokens


def _strip_country_suffix(value: str) -> str:
    return COUNTRY_SUFFIX_RE.sub("", _collapse(value).replace("(NP)", "")).strip()


def _download(url: str, path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> str:
    validate_https_url(url, allowed_hosts={"zeturf.fr"})
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    before_network_request(url)
    body, _response_meta = fetch_https(
        url,
        allowed_hosts={"zeturf.fr"},
        timeout=timeout,
        headers={"User-Agent": "umanewsbot/1.0 (+https://umafans.run; low-frequency race detail import)"},
    )
    text = body.decode("utf-8", errors="replace")
    write_source_cache_text(path, text, source_url=url)
    return text


def _title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    node = soup.find("title")
    return _collapse(node.get_text(" ", strip=True) if node else "")


def _title_parts(title: str) -> dict[str, str]:
    match = re.match(r"(\d{2})/(\d{2})/(\d{4})\s+-\s+(.+?)\s+-\s+(.+?):", title)
    if not match:
        return {"date": "", "venue": "", "race_name": ""}
    return {
        "date": f"{match.group(3)}-{match.group(2)}-{match.group(1)}",
        "venue": _collapse(match.group(4)),
        "race_name": _collapse(match.group(5)),
    }


def _venue_match(expected: str, actual: str) -> bool:
    expected_key = _key(expected)
    actual_key = _key(actual)
    aliases = {
        "parislongchamp": {"parislongchamp", "longchamp"},
        "saintcloud": {"saintcloud"},
    }
    if expected_key == actual_key:
        return True
    if actual_key in aliases.get(expected_key, set()):
        return True
    return bool(expected_key and actual_key and (expected_key in actual_key or actual_key in expected_key))


def _race_match(expected: str, actual: str) -> bool:
    expected_key = _key(expected)
    actual_key = _key(actual)
    if expected_key and (expected_key in actual_key or actual_key in expected_key):
        return True
    expected_tokens = _tokens(expected)
    actual_tokens = _tokens(actual)
    if not expected_tokens or not actual_tokens:
        return False
    overlap = len(expected_tokens & actual_tokens)
    if len(expected_tokens) <= 2:
        return expected_tokens <= actual_tokens
    return overlap >= max(2, round(len(expected_tokens) * 0.67))


def _event_match_names(event: dict) -> list[str]:
    names = [str(event.get("original_name") or "").strip()]
    try:
        source_refs = json.loads(event.get("source_refs") or "{}")
    except (TypeError, json.JSONDecodeError):
        source_refs = {}
    calendar_name = str((source_refs.get("calendar_discovery") or {}).get("race_name") or "").strip()
    if calendar_name:
        names.append(calendar_name)
    slug = str(event.get("slug") or "")
    for series_key, aliases in ZETURF_SERIES_ALIASES.items():
        if series_key.casefold() in slug.casefold():
            names.extend(aliases)
    return list(dict.fromkeys(name for name in names if name))


def _race_matches_event(event: dict, actual: str) -> bool:
    return any(_race_match(name, actual) for name in _event_match_names(event))


def _zeturf_url(event: dict, *, r_number: int, c_number: int) -> str:
    course_slug = _slugify(event.get("racecourse") or "")
    race_slug = _slugify(event.get("original_name") or "")
    return f"{BASE_URL}/fr/course-du-jour/{event['local_date']}/R{r_number}C{c_number}-{course_slug}-{race_slug}"


def _read_events(
    path: Path,
    *,
    recovery_mode: bool = False,
) -> list[dict]:
    events = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") == "finished" or (
                recovery_mode and row.get("status") == "scheduled"
            ):
                events.append(row)
    return events


def _filter_events(events: list[dict], *, start_date: str, end_date: str) -> list[dict]:
    filtered = []
    for event in events:
        race_date = event.get("local_date") or ""
        if start_date and race_date < start_date:
            continue
        if end_date and race_date > end_date:
            continue
        filtered.append(event)
    return filtered


def _cell_text(node, selector: str) -> str:
    found = node.select_one(selector)
    return _collapse(found.get_text(" ", strip=True) if found else "")


def _horse_name(node) -> str:
    horse_node = node.select_one(".horse-name")
    value = (
        horse_node.get("title")
        if horse_node and horse_node.get("title")
        else (horse_node.get_text(" ", strip=True) if horse_node else "")
    )
    return _strip_country_suffix(value)


def _parse_finish_position(value: str) -> int:
    match = re.search(r"\d+", value or "")
    return int(match.group(0)) if match else 0


def _parse_page(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    soup = BeautifulSoup(html, "lxml")
    runners = []
    runner_by_number = {}
    runner_table = soup.select_one("table.table-runners")
    if runner_table:
        for tr in runner_table.select("tbody tr[data-runner]"):
            number = _cell_text(tr, "td.numero")
            horse_name = _horse_name(tr)
            if not horse_name:
                continue
            jockey = _cell_text(tr, ".second-line .jockey")
            trainer = ""
            for trainer_node in tr.select(".second-line > span"):
                if "jockey" not in (trainer_node.get("class") or []):
                    trainer = _collapse(trainer_node.get_text(" ", strip=True))
                    break
            running_status = "withdrawn" if tr.select_one(".non-partant") or "(NP)" in tr.get_text(" ", strip=True) else "declared"
            source_refs = {
                "primary": source_url,
                "source_language": "fr",
                "source_kind": "zeturf_race_detail",
                "horse_id": (tr.select_one("a.horse-name") or {}).get("data-runner", "") if tr.select_one("a.horse-name") else "",
                "horse_name_raw": horse_name,
            }
            row = {
                "sort_order": len(runners) + 1,
                "horse_number": number,
                "barrier": _cell_text(tr, "td.corde"),
                "horse_name": horse_name,
                "jockey_name": jockey,
                "trainer_name": trainer,
                "carried_weight": _cell_text(tr, "td.weight"),
                "odds_value": _cell_text(tr, "td.cote"),
                "running_status": running_status,
                "source_refs": source_refs,
            }
            runners.append(row)
            if number:
                runner_by_number[number] = row

    results = []
    arrival = soup.select_one("#arriveeTab table")
    if arrival:
        for tr in arrival.select("tbody tr[data-runner]"):
            cells = tr.find_all("td")
            if len(cells) < 4:
                continue
            official_position = _parse_finish_position(cells[0].get_text(" ", strip=True))
            if official_position <= 0:
                continue
            number = _collapse(cells[1].get_text(" ", strip=True))
            horse_name = _horse_name(cells[2]) or (runner_by_number.get(number) or {}).get("horse_name", "")
            if not horse_name:
                continue
            base = runner_by_number.get(number) or {}
            results.append(
                {
                    "finish_position": len(results) + 1,
                    "horse_number": number,
                    "barrier": base.get("barrier", ""),
                    "horse_name": horse_name,
                    "jockey_name": _cell_text(cells[3], "a.jockey") or base.get("jockey_name", ""),
                    "trainer_name": base.get("trainer_name", ""),
                    "carried_weight": base.get("carried_weight", ""),
                    "finish_time": "",
                    "margin": _collapse(cells[-1].get_text(" ", strip=True)) if cells else "",
                    "odds_value": _collapse(cells[-2].get_text(" ", strip=True)) if len(cells) >= 2 else "",
                    "running_status": "declared",
                    "is_confirmed": True,
                    "source_refs": {
                        **(base.get("source_refs") or {}),
                        "primary": source_url,
                        "official_finish_position": official_position,
                    },
                }
            )
    metadata = _title_parts(_title(html))
    metadata.update({"row_count": len(runners), "result_count": len(results)})
    return runners, results, metadata


def _discover_event_pages(events: list[dict], source_dir: Path, args) -> tuple[dict[str, dict], list[dict]]:
    by_date = defaultdict(list)
    for event in events:
        by_date[event["local_date"]].append(event)
    matched: dict[str, dict] = {}
    skipped = []
    for race_date, date_events in sorted(by_date.items()):
        unmatched = {event["slug"]: event for event in date_events}
        target_courses = {event["racecourse"] for event in date_events}
        candidate_rs = []
        probe_event = date_events[0]
        for r_number in range(1, args.max_r + 1):
            url = _zeturf_url(probe_event, r_number=r_number, c_number=1)
            cache_path = source_dir / f"source_zt_{race_date}_R{r_number}C1.html"
            try:
                html = _download(url, cache_path, allow_network=args.allow_network, timeout=args.timeout_seconds, sleep_seconds=args.sleep_seconds)
            except Exception as exc:
                skipped.append({"date": race_date, "reason": "probe_failed", "r": r_number, "error": str(exc)})
                continue
            parts = _title_parts(_title(html))
            if parts["date"] != race_date:
                continue
            if any(_venue_match(course, parts["venue"]) for course in target_courses):
                candidate_rs.append(r_number)
        for r_number in candidate_rs:
            if not unmatched:
                break
            for c_number in range(1, args.max_c + 1):
                if not unmatched:
                    break
                sample_event = next(iter(unmatched.values()), date_events[0])
                url = _zeturf_url(sample_event, r_number=r_number, c_number=c_number)
                cache_path = source_dir / f"source_zt_{race_date}_R{r_number}C{c_number}.html"
                try:
                    html = _download(url, cache_path, allow_network=args.allow_network, timeout=args.timeout_seconds, sleep_seconds=args.sleep_seconds)
                except Exception as exc:
                    skipped.append({"date": race_date, "reason": "race_page_failed", "r": r_number, "c": c_number, "error": str(exc)})
                    continue
                parts = _title_parts(_title(html))
                if parts["date"] != race_date:
                    continue
                for slug, event in list(unmatched.items()):
                    if not _venue_match(event["racecourse"], parts["venue"]):
                        continue
                    if not _race_matches_event(event, parts["race_name"]):
                        continue
                    matched[slug] = {
                        "event": event,
                        "url": url,
                        "html": html,
                        "r": r_number,
                        "c": c_number,
                        "title": _title(html),
                    }
                    unmatched.pop(slug, None)
                    break
        for event in unmatched.values():
            skipped.append({"slug": event["slug"], "date": race_date, "racecourse": event["racecourse"], "name": event["original_name"], "reason": "race_not_found"})
    return matched, skipped


def prepare_candidates(args) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    events = _read_events(
        Path(args.events_csv),
        recovery_mode=bool(getattr(args, "recovery_mode", False)),
    )
    events = _filter_events(events, start_date=args.start_date, end_date=args.end_date)
    if args.limit:
        events = events[: args.limit]
    matched, skipped = _discover_event_pages(events, source_dir, args)
    jsonl_path = output_dir / "france_zeturf_detail_candidates_2026.jsonl"
    review_path = output_dir / "france_zeturf_detail_review_2026.csv"
    summary = {
        "source": "zeturf_race_detail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": len(events),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "skipped": skipped,
        "errors": [],
    }
    review_rows = []
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for slug, item in sorted(matched.items(), key=lambda kv: kv[1]["event"]["local_date"]):
            event = item["event"]
            try:
                runners, results, metadata = _parse_page(item["html"], source_url=item["url"])
            except Exception as exc:
                summary["errors"].append({"slug": slug, "error": str(exc)})
                if args.fail_fast:
                    raise
                continue
            if not runners:
                summary["skipped"].append({"slug": slug, "reason": "no_runner_rows", "source_url": item["url"]})
                continue
            record = {
                "year": int(event["year"]),
                "slug": slug,
                "source_name": "zeturf",
                "source_url": item["url"],
                "modules": {"runners": {"items": runners}, "results": {"items": results}},
                "metadata": {**metadata, "zeturf_r": item["r"], "zeturf_c": item["c"], "title": item["title"]},
            }
            if str(event.get("event_id") or "").strip():
                record["event_id"] = int(event["event_id"])
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["runner_items"] += len(runners)
            summary["result_items"] += len(results)
            review_rows.append(
                {
                    "slug": slug,
                    "original_name": event["original_name"],
                    "racecourse": event["racecourse"],
                    "local_date": event["local_date"],
                    "source_url": item["url"],
                    "runners": len(runners),
                    "results": len(results),
                    "winner": results[0]["horse_name"] if results else "",
                    "title": item["title"],
                }
            )
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "racecourse", "local_date", "source_url", "runners", "results", "winner", "title"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate France 2026 runner/result candidate JSONL from ZEturf race pages.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--recovery-mode", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--max-r", type=int, default=12)
    parser.add_argument("--max-c", type=int, default=16)
    parser.add_argument("--timeout-seconds", type=int, default=25)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare_candidates(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

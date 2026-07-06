#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


SL_BASE_URL = "https://www.sportinglife.com"
COUNTRY_SUFFIX_RE = re.compile(r"\s*[\(\（][A-Z]{2,3}[\)\）]\s*$")


def _text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _norm(value: str) -> str:
    value = (value or "").lower().replace("&", " and ")
    value = re.sub(r"[()']", " ", value)
    value = re.sub(r"\bregistered as\b", " ", value)
    value = re.sub(r"\bpresented by\b.*$", " ", value)
    value = re.sub(r"\bsponsored by\b.*$", " ", value)
    value = re.sub(r"\bstakes\b", "s", value)
    value = re.sub(r"\bstake\b", "s", value)
    value = re.sub(r"\bnovices?\b", "nov", value)
    value = re.sub(r"\bhurdle\b", "hdle", value)
    value = re.sub(r"\bhandicap\b", "hcap", value)
    value = re.sub(r"\bgrade\s*[123]\b", " ", value)
    value = re.sub(r"\bgroup\s*[123]\b", " ", value)
    value = re.sub(r"\bgbb\b", " ", value)
    value = re.sub(r"\brace\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


TOKEN_STOPWORDS = {
    "a",
    "and",
    "as",
    "at",
    "class",
    "for",
    "gbb",
    "grade",
    "group",
    "race",
    "registered",
    "sponsored",
    "the",
}


def _name_tokens(value: str) -> set[str]:
    value = (value or "").lower().replace("&", " and ")
    value = re.sub(r"[()']", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    tokens = []
    for token in value.split():
        if token in TOKEN_STOPWORDS or token.isdigit():
            continue
        token = {
            "hdle": "hurdle",
            "hurdles": "hurdle",
            "nov": "novices",
            "novice": "novices",
            "chases": "chase",
            "stakes": "stake",
        }.get(token, token)
        tokens.append(token)
    return set(tokens)


def _event_match_keys(value: str) -> list[str]:
    keys = []
    variants = [value or ""]
    variants.append(re.sub(r"\([^)]*\)", "", value or ""))
    variants.append(re.split(r"\s+PRESENTED BY\s+", value or "", flags=re.IGNORECASE)[0])
    variants.append(re.split(r"\s+SPONSORED BY\s+", value or "", flags=re.IGNORECASE)[0])
    for variant in variants:
        key = _norm(variant)
        if key and key not in keys:
            keys.append(key)
    return keys


def _strip_country_suffix(value: str) -> str:
    return COUNTRY_SUFFIX_RE.sub("", _collapse(value)).strip()


def _download(url: str, path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    request = Request(url, headers={"User-Agent": "umanewsbot/1.0 (+https://umafans.run; low-frequency race detail import)"})
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
    text = body.decode("utf-8", errors="replace")
    path.write_text(text, encoding="utf-8")
    return text


def _source_filename(prefix: str, value: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return f"{prefix}_{key[-120:]}.html"


def _slugify(value: str) -> str:
    value = (value or "").lower().replace("&", " and ")
    value = re.sub(r"[()']", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


def _next_data(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        raise RuntimeError("Sporting Life 页面缺少 __NEXT_DATA__")
    return json.loads(script.string)


def _read_events(paths: list[Path]) -> list[dict]:
    events: list[dict] = []
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("status") == "finished":
                    events.append(row)
    return events


def _course_match(event_course: str, sl_course: str) -> bool:
    event_key = _norm(event_course)
    sl_key = _norm(sl_course)
    aliases = {
        "epsom": "epsomdowns",
        "epsomdowns": "epsom",
        "kemptonpark": "kempton",
        "sandownpark": "sandown",
        "haydockpark": "haydock",
        "lingfieldpark": "lingfield",
        "newmarket": "newmarket",
        "newcastle": "newcastle",
    }
    if event_key == sl_key:
        return True
    if aliases.get(event_key) == sl_key or aliases.get(sl_key) == event_key:
        return True
    return bool(event_key and sl_key and (event_key in sl_key or sl_key in event_key))


def _race_url_map(html: str) -> dict[int, str]:
    soup = BeautifulSoup(html, "lxml")
    urls: dict[int, str] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        match = re.search(r"/racing/results/\d{4}-\d{2}-\d{2}/[^/]+/(\d+)/", href)
        if match:
            urls[int(match.group(1))] = urljoin(SL_BASE_URL, href)
    return urls


def _summary_races(date_html: str) -> tuple[list[dict], dict[int, str]]:
    data = _next_data(date_html)
    meetings = data["props"]["pageProps"].get("meetings") or []
    races = []
    for meeting in meetings:
        for race in meeting.get("races") or []:
            races.append(race)
    return races, _race_url_map(date_html)


def _find_race_summary(event: dict, races: list[dict]) -> dict | None:
    event_keys = _event_match_keys(event["original_name"])
    candidates = [
        race
        for race in races
        if _course_match(event.get("racecourse") or "", race.get("course_name") or "")
    ]
    for race in candidates:
        race_key = _norm(race.get("name") or "")
        if any(key and (key in race_key or race_key in key) for key in event_keys):
            return race
    event_tokens = _name_tokens(event["original_name"])
    if not event_tokens:
        return None
    grade = (event.get("normalized_grade") or "").upper()
    scored = []
    for race in candidates:
        race_name = race.get("name") or ""
        if grade and grade not in race_name.upper().replace("GRADE ", "G").replace("GROUP ", "G"):
            continue
        race_tokens = _name_tokens(race_name)
        overlap = len(event_tokens & race_tokens)
        if overlap < min(2, len(event_tokens)):
            continue
        event_key = event_keys[0] if event_keys else _norm(event["original_name"])
        race_key = _norm(race_name)
        ratio = SequenceMatcher(None, event_key, race_key).ratio()
        coverage = overlap / max(len(event_tokens), 1)
        race_coverage = overlap / max(len(race_tokens), 1)
        scored.append((coverage * 0.45 + race_coverage * 0.35 + ratio * 0.2, overlap, ratio, race))
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    if scored and scored[0][0] >= 0.42:
        return scored[0][3]
    return None


def _person_name(value) -> str:
    if isinstance(value, dict):
        return value.get("name") or value.get("display_name") or ""
    return str(value or "")


def _odds(ride: dict) -> str:
    betting = ride.get("betting")
    if isinstance(betting, dict):
        return str(betting.get("current_odds") or "")
    return ""


def _runner_status(ride: dict) -> str:
    status = str(ride.get("ride_status") or "").upper()
    if status in {"NONRUNNER", "NON_RUNNER"}:
        return "withdrawn"
    if status in {"RUNNER"}:
        return "declared"
    return "unknown"


def _parse_detail_page(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    race = _next_data(html)["props"]["pageProps"]["race"]
    summary = race.get("race_summary") or {}
    runners = []
    result_rows = []
    for ride in race.get("rides") or []:
        horse = ride.get("horse") or {}
        horse_name = _strip_country_suffix(str(horse.get("name") or ""))
        if not horse_name:
            continue
        finish_position = ride.get("finish_position")
        try:
            finish_position_int = int(finish_position)
        except (TypeError, ValueError):
            finish_position_int = 0
        source_refs = {
            "primary": source_url,
            "source_language": "en",
            "source_kind": "sporting_life_result_detail",
            "sporting_life_race_id": (summary.get("race_summary_reference") or {}).get("id"),
            "horse_id": (horse.get("horse_reference") or {}).get("id"),
            "horse_slug": horse.get("slug") or "",
            "horse_name_raw": horse.get("name") or "",
            "ride_status": ride.get("ride_status") or "",
            "ride_description": ride.get("ride_description") or "",
        }
        row = {
            "sort_order": len(runners) + 1,
            "horse_number": str(ride.get("cloth_number") or ""),
            "barrier": str(ride.get("draw_number") or ""),
            "horse_name": horse_name,
            "jockey_name": _person_name(ride.get("jockey")),
            "trainer_name": _person_name(ride.get("trainer")),
            "carried_weight": str(ride.get("handicap") or ""),
            "odds_value": _odds(ride),
            "running_status": _runner_status(ride),
            "finish_position": finish_position_int,
            "finish_time": summary.get("winning_time") if finish_position_int == 1 else "",
            "margin": str(ride.get("finish_distance") or ""),
            "source_refs": source_refs,
        }
        runners.append(
            {
                "sort_order": row["sort_order"],
                "horse_number": row["horse_number"],
                "barrier": row["barrier"],
                "horse_name": row["horse_name"],
                "jockey_name": row["jockey_name"],
                "trainer_name": row["trainer_name"],
                "carried_weight": row["carried_weight"],
                "odds_value": row["odds_value"],
                "running_status": row["running_status"],
                "source_refs": row["source_refs"],
            }
        )
        if row["running_status"] == "declared" and finish_position_int > 0:
            result_rows.append(row)

    results = []
    for sort_position, row in enumerate(sorted(result_rows, key=lambda item: item["finish_position"]), start=1):
        results.append(
            {
                "finish_position": sort_position,
                "horse_number": row["horse_number"],
                "barrier": row["barrier"],
                "horse_name": row["horse_name"],
                "jockey_name": row["jockey_name"],
                "trainer_name": row["trainer_name"],
                "carried_weight": row["carried_weight"],
                "finish_time": row["finish_time"],
                "margin": row["margin"],
                "odds_value": row["odds_value"],
                "running_status": row["running_status"],
                "is_confirmed": True,
                "source_refs": {**row["source_refs"], "official_finish_position": row["finish_position"]},
            }
        )
    return runners, results, {
        "race_title": summary.get("name") or "",
        "race_id": (summary.get("race_summary_reference") or {}).get("id"),
        "race_stage": summary.get("race_stage") or "",
        "row_count": len(runners),
        "result_count": len(results),
    }


def prepare_candidates(args) -> dict:
    events = _read_events([Path(path) for path in args.events_csv])
    if args.limit:
        events = events[: args.limit]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    jsonl_path = output_dir / "uk_sportinglife_detail_candidates_2026.jsonl"
    review_csv_path = output_dir / "uk_sportinglife_detail_review_2026.csv"
    summary = {
        "source": "sporting_life_result_detail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "date_pages": 0,
        "detail_pages": 0,
        "skipped": [],
        "errors": [],
    }
    date_cache: dict[str, tuple[list[dict], dict[int, str]]] = {}
    review_rows = []
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for event in events:
            race_date = event.get("local_date") or ""
            if not race_date:
                summary["skipped"].append({"slug": event["slug"], "reason": "missing_date"})
                continue
            try:
                if race_date not in date_cache:
                    date_url = f"{SL_BASE_URL}/racing/results/{race_date}"
                    date_html = _download(
                        date_url,
                        source_dir / _source_filename("source_sl_results", race_date),
                        allow_network=args.allow_network,
                        timeout=args.timeout_seconds,
                        sleep_seconds=args.sleep_seconds,
                    )
                    date_cache[race_date] = _summary_races(date_html)
                    summary["date_pages"] += 1
                races, urls = date_cache[race_date]
                race_summary = _find_race_summary(event, races)
                if race_summary is None:
                    summary["skipped"].append({"slug": event["slug"], "reason": "race_not_found", "date": race_date, "racecourse": event.get("racecourse"), "name": event.get("original_name")})
                    continue
                race_id = int((race_summary.get("race_summary_reference") or {}).get("id") or 0)
                detail_url = urls.get(race_id)
                if not detail_url:
                    detail_url = (
                        f"{SL_BASE_URL}/racing/results/{race_date}/"
                        f"{_slugify(race_summary.get('course_name') or event.get('racecourse') or '')}/"
                        f"{race_id}/{_slugify(race_summary.get('name') or event.get('original_name') or '')}"
                    )
                detail_html = _download(
                    detail_url,
                    source_dir / _source_filename("source_sl_detail", str(race_id)),
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                )
                summary["detail_pages"] += 1
                runners, results, metadata = _parse_detail_page(detail_html, source_url=detail_url)
                if not runners:
                    summary["skipped"].append({"slug": event["slug"], "reason": "no_runner_rows", "detail_url": detail_url})
                    continue
            except Exception as exc:
                summary["errors"].append({"slug": event.get("slug"), "error": str(exc)})
                if args.fail_fast:
                    raise
                continue
            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": "sporting_life",
                "source_url": detail_url,
                "modules": {"runners": {"items": runners}, "results": {"items": results}},
                "metadata": metadata,
            }
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["runner_items"] += len(runners)
            summary["result_items"] += len(results)
            review_rows.append(
                {
                    "slug": event["slug"],
                    "original_name": event["original_name"],
                    "racecourse": event.get("racecourse", ""),
                    "source_url": detail_url,
                    "runners": len(runners),
                    "results": len(results),
                    "winner": results[0]["horse_name"] if results else "",
                    "race_title": metadata["race_title"],
                }
            )
    with review_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "racecourse", "source_url", "runners", "results", "winner", "race_title"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate UK 2026 runner/result candidate JSONL from Sporting Life result pages.")
    parser.add_argument("--events-csv", nargs="+", required=True)
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

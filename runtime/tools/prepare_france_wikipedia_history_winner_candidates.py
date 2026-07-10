#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from race_event_request_budget import before_network_request

from bs4 import BeautifulSoup


WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE = "https://en.wikipedia.org/wiki/{title}"
USER_AGENT = "UmaFansBot/1.0 (+https://umafans.run; low-frequency history import)"


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clean_cell(value: str) -> str:
    value = re.sub(r"\[[^\]]+\]", "", value or "")
    value = value.replace("\xa0", " ")
    return _collapse(value)


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def _query_from_series(series_key: str, original_name: str) -> str:
    value = unicodedata.normalize("NFKC", original_name or "")
    value = value.replace("’", "'")
    value = re.sub(r"\bL\s*'\s*", "L'", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+-\s*", "-", value)
    value = re.sub(r"\bCHANTILL\s+Y\b", "CHANTILLY", value, flags=re.IGNORECASE)
    value = re.sub(r"\bL\s+YS\b", "LYS", value, flags=re.IGNORECASE)
    value = re.sub(r"\bO'REILL\s+Y\b", "O'REILLY", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*-\s*FONDS EUROPEEN DE L'?ELEVAGE.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+LONGINES$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+HONG KONG JOCKEY CLUB$", "", value, flags=re.IGNORECASE)
    for prefix in [
        "QATAR",
        "EMIRATES",
        "KRA",
        "DARLEY",
        "ARC",
        "SKY SPORTS RACING",
        "THE AGA KHAN STUDS",
        "LUCIEN BARRIERE",
        "RACING TV",
    ]:
        value = re.sub(rf"^{re.escape(prefix)}\s+", "", value, flags=re.IGNORECASE)
    match = re.search(r"\bPRIX\b.+$", value, flags=re.IGNORECASE)
    if match:
        value = match.group(0)
    value = re.sub(r"\s+", " ", value).strip()
    words = []
    for word in value.split():
        if word.upper() in {"DE", "DU", "DES", "LA", "LE", "LES", "D'"}:
            words.append(word.lower())
        elif word.upper().startswith("D'") and len(word) > 2:
            words.append("d'" + word[2:].capitalize())
        else:
            words.append(word.capitalize())
    return " ".join(words)


def _request_text(url: str, cache_path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> str:
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{cache_path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    before_network_request(url)
    with urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
    cache_path.write_text(text, encoding="utf-8")
    return text


def _cache_name(prefix: str, value: str, suffix: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return f"{prefix}_{key[-120:]}.{suffix}"


def _search_title(query: str, source_dir: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> tuple[str, str]:
    url = f"{WIKI_API}?{urlencode({'action': 'query', 'list': 'search', 'srsearch': query, 'format': 'json', 'srlimit': 5})}"
    text = _request_text(url, source_dir / _cache_name("source_wiki_search", query, "json"), allow_network=allow_network, timeout=timeout, sleep_seconds=sleep_seconds)
    data = json.loads(text)
    expected = _norm(query)
    best_title = ""
    for item in data.get("query", {}).get("search", []):
        title = item.get("title") or ""
        title_norm = _norm(title)
        if title_norm == expected or expected in title_norm or title_norm in expected:
            best_title = title
            break
    if not best_title:
        return "", ""
    page_url = WIKI_PAGE.format(title=quote(best_title.replace(" ", "_")))
    return best_title, page_url


def _parse_winner_tables(html: str, *, page_url: str, min_year: int, max_year: int) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items: dict[int, dict] = {}
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [_clean_cell(cell.get_text(" ", strip=True)).lower() for cell in rows[0].find_all(["th", "td"])]
        if not headers:
            continue
        if "year" not in headers or "winner" not in headers:
            continue
        year_idx = headers.index("year")
        winner_idx = headers.index("winner")
        jockey_idx = headers.index("jockey") if "jockey" in headers else None
        trainer_idx = headers.index("trainer") if "trainer" in headers else None
        time_idx = headers.index("time") if "time" in headers else None
        for tr in rows[1:]:
            cells = [_clean_cell(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
            if len(cells) <= max(year_idx, winner_idx):
                continue
            year_match = re.search(r"\d{4}", cells[year_idx])
            if not year_match:
                continue
            year = int(year_match.group(0))
            if year < min_year or year > max_year:
                continue
            winner = cells[winner_idx]
            if not winner or "no race" in winner.lower() or "not run" in winner.lower():
                continue
            items[year] = {
                "winner_year": year,
                "horse_name": winner,
                "jockey_name": cells[jockey_idx] if jockey_idx is not None and len(cells) > jockey_idx else "",
                "trainer_name": cells[trainer_idx] if trainer_idx is not None and len(cells) > trainer_idx else "",
                "finish_time": cells[time_idx] if time_idx is not None and len(cells) > time_idx else "",
                "margin": "",
                "source_refs": {
                    "primary": page_url,
                    "source_language": "en",
                    "source_kind": "wikipedia_winners_table",
                },
            }
    return [items[year] for year in sorted(items, reverse=True)]


def _read_events(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_current_history(path: Path) -> dict[str, list[dict]]:
    current: dict[str, list[dict]] = {}
    if not path:
        return current
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            slug = record.get("slug") or ""
            items = ((record.get("modules") or {}).get("history_winners") or {}).get("items") or []
            if slug and items:
                current[slug] = items
    return current


def _merge_items(wiki_items: list[dict], current_items: list[dict]) -> list[dict]:
    merged = {item["winner_year"]: item for item in wiki_items if item.get("winner_year")}
    for item in current_items:
        if item.get("winner_year"):
            merged[int(item["winner_year"])] = item
    return [merged[year] for year in sorted(merged, reverse=True)]


def prepare(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    source_dir = output_dir / "sources"
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(exist_ok=True)
    events = _read_events(Path(args.events_csv))
    if args.limit:
        events = events[: args.limit]
    current_history = _read_current_history(Path(args.current_history_jsonl)) if args.current_history_jsonl else {}

    jsonl_path = output_dir / "france_wikipedia_history_winner_candidates_2026.jsonl"
    review_path = output_dir / "france_wikipedia_history_winner_review_2026.csv"
    unmatched_path = output_dir / "france_wikipedia_history_winner_unmatched_2026.csv"
    summary = {
        "source": "wikipedia_winners_table",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": len(events),
        "events": 0,
        "history_items": 0,
        "events_without_history": 0,
        "events_skipped_partial": 0,
        "skipped": [],
        "errors": [],
    }
    review_rows = []
    unmatched_rows = []
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for event in events:
            query = _query_from_series(event.get("series_key") or "", event.get("original_name") or "")
            diagnostics = []
            try:
                title, page_url = _search_title(query, source_dir, allow_network=args.allow_network, timeout=args.timeout_seconds, sleep_seconds=args.sleep_seconds)
                if not title:
                    raise RuntimeError("wikipedia_search_no_match")
                html = _request_text(
                    page_url,
                    source_dir / _cache_name("source_wiki_page", title, "html"),
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                )
                wiki_items = _parse_winner_tables(html, page_url=page_url, min_year=args.min_year, max_year=2026)
            except Exception as exc:
                diagnostics.append({"slug": event.get("slug"), "query": query, "error": str(exc)})
                summary["errors"].extend(diagnostics)
                wiki_items = []
                title = ""
                page_url = ""
            items = _merge_items(wiki_items, current_history.get(event["slug"], []))
            if not items:
                summary["events_without_history"] += 1
                unmatched_rows.append({"slug": event["slug"], "original_name": event.get("original_name", ""), "query": query, "wiki_title": title, "source_url": page_url})
                continue
            if diagnostics and not args.allow_partial_history:
                summary["events_skipped_partial"] += 1
                summary["skipped"].append(
                    {
                        "slug": event["slug"],
                        "reason": "partial_wikipedia_history",
                        "history_items": len(items),
                        "diagnostics": diagnostics,
                    }
                )
                continue
            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": "wikipedia_winners_table",
                "source_url": page_url,
                "modules": {"history_winners": {"items": items}},
                "metadata": {
                    "source_kind": "wikipedia_winners_table",
                    "wiki_title": title,
                    "query": query,
                    "partial_history": bool(diagnostics),
                    "diagnostics": diagnostics,
                },
            }
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["history_items"] += len(items)
            review_rows.append(
                {
                    "slug": event["slug"],
                    "original_name": event.get("original_name", ""),
                    "history_count": len(items),
                    "first_year": min(item["winner_year"] for item in items),
                    "latest_year": max(item["winner_year"] for item in items),
                    "latest_winner": items[0]["horse_name"],
                    "wiki_title": title,
                    "source_url": page_url,
                }
            )
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "history_count", "first_year", "latest_year", "latest_winner", "wiki_title", "source_url"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    with unmatched_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "query", "wiki_title", "source_url"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unmatched_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate France 2026 historical winner candidates from Wikipedia winners tables plus confirmed current winners.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--current-history-jsonl", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-year", type=int, default=2020)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-partial-history", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    args = parser.parse_args()
    print(json.dumps(prepare(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

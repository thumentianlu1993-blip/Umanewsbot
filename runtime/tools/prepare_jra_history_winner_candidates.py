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
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from race_event_request_budget import before_network_request
from race_event_source_cache import write_source_cache

from bs4 import BeautifulSoup


JRA_BASE_URL = "https://www.jra.go.jp"
JRA_HISTORY_URL = "https://www.jra.go.jp/datafile/seiseki/replay/{year}/jyusyo.html"

MANUAL_SERIES_ALIASES = {
    "大阪杯": ["産経大阪杯"],
    "弥生賞ディープインパクト記念": ["弥生賞"],
    "チャレンジC": ["朝日チャレンジC"],
    "阪神牝馬S": ["サンケイスポーツ杯阪神牝馬S"],
}

GRADE_PREFIX_RE = re.compile(r"^(?:J・)?G[ⅠⅡⅢI]{1,3}\s+")


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _decode_jra_html(body: bytes) -> str:
    return body.decode("cp932", errors="replace")


def _normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("ステークス", "S")
    value = value.replace("カップ", "C")
    value = value.replace("トロフィー", "T")
    value = GRADE_PREFIX_RE.sub("", value)
    value = re.sub(r"[\s　・\-.（）()]+", "", value)
    return value.upper()


def _clean_race_name(value: str) -> str:
    return GRADE_PREFIX_RE.sub("", _collapse(unicodedata.normalize("NFKC", value or ""))).strip()


def _cell_lines(cell) -> list[str]:
    if cell is None:
        return []
    for br in cell.find_all("br"):
        br.replace_with("\n")
    text = cell.get_text("\n", strip=True)
    lines = []
    for line in text.splitlines():
        value = _collapse(line)
        if not value:
            continue
        if value.startswith("注記") or value.startswith("※") or value == "同着":
            continue
        lines.append(value)
    return lines


def _download(url: str, path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> bytes:
    if path.exists():
        return path.read_bytes()
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    request = Request(url, headers={"User-Agent": "UmaFansBot/1.0 (+https://umafans.run; low-frequency history import)"})
    before_network_request(url)
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
    write_source_cache(path, body, source_url=url)
    return body


def _find_history_table(soup: BeautifulSoup):
    for table in reversed(soup.find_all("table")):
        header = table.find("tr")
        if not header:
            continue
        header_text = _collapse(header.get_text(" ", strip=True))
        if ("月/日" in header_text or "月日" in header_text) and all(label in header_text for label in ["レース名", "優勝馬", "騎手"]):
            return table
    return None


def _header_indexes(table) -> dict[str, int]:
    header = table.find("tr")
    cells = header.find_all(["th", "td"]) if header else []
    labels = [_collapse(cell.get_text(" ", strip=True)) for cell in cells]
    indexes = {}
    for index, label in enumerate(labels):
        normalized = label.replace("/", "")
        if normalized in {"月日"}:
            indexes["date"] = index
        elif label == "レース名":
            indexes["race_name"] = index
        elif label in {"場", "競馬場"}:
            indexes["racecourse"] = index
        elif label == "コース":
            indexes["course"] = index
        elif label == "優勝馬":
            indexes["winner"] = index
        elif label == "騎手":
            indexes["jockey"] = index
        elif label == "結果":
            indexes["result"] = index
    required = {"race_name", "racecourse", "course", "winner", "jockey", "result"}
    if not required <= set(indexes):
        raise RuntimeError(f"JRA 重賞一覧表の表頭を解釈できません：labels={labels}")
    return indexes


def _parse_history_year(body: bytes, *, year: int, source_url: str) -> list[dict]:
    soup = BeautifulSoup(_decode_jra_html(body), "lxml")
    table = _find_history_table(soup)
    if table is None:
        raise RuntimeError(f"JRA 重賞一覧表が見つかりません：{source_url}")
    indexes = _header_indexes(table)
    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) <= max(indexes.values()):
            continue
        race_name = _clean_race_name(cells[indexes["race_name"]].get_text(" ", strip=True))
        winners = _cell_lines(cells[indexes["winner"]])
        jockeys = _cell_lines(cells[indexes["jockey"]])
        if not race_name or not winners:
            continue
        result_link = ""
        link = cells[indexes["result"]].find("a", href=True)
        if link:
            result_link = urljoin(source_url, link["href"])
        if len(jockeys) < len(winners):
            jockeys.extend([""] * (len(winners) - len(jockeys)))
        elif len(jockeys) > len(winners) and len(winners) == 1:
            jockeys = [" / ".join(jockeys)]
        rows.append(
            {
                "winner_year": year,
                "race_name": race_name,
                "race_key": _normalize_name(race_name),
                "racecourse": _collapse(cells[indexes["racecourse"]].get_text(" ", strip=True)),
                "course": _collapse(cells[indexes["course"]].get_text(" ", strip=True)),
                "winners": winners,
                "jockeys": jockeys[: len(winners)],
                "source_url": result_link or source_url,
                "list_url": source_url,
            }
        )
    return rows


def _read_jra_events(path: Path) -> list[dict]:
    events = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("country_region") or "") != "japan":
                continue
            events.append(row)
    return events


def _event_match_keys(event: dict) -> set[str]:
    values = [event.get("original_name") or "", event.get("chinese_name") or ""]
    aliases = re.split(r"[|,]", event.get("aliases") or "")
    values.extend(aliases)
    values.extend(MANUAL_SERIES_ALIASES.get(event.get("original_name") or "", []))
    keys = {_normalize_name(value) for value in values if value}
    return {key for key in keys if key}


def _history_item(row: dict) -> dict:
    winners = row["winners"]
    jockeys = row["jockeys"]
    source_refs = {
        "primary": row["source_url"],
        "list_url": row["list_url"],
        "source_language": "ja",
        "source_kind": "jra_official_graded_race_list_history",
        "official_race_name": row["race_name"],
        "racecourse": row["racecourse"],
        "course": row["course"],
    }
    if len(winners) > 1:
        source_refs["dead_heat_winners"] = [
            {"horse_name": horse, "jockey_name": jockeys[index] if index < len(jockeys) else ""}
            for index, horse in enumerate(winners)
        ]
    return {
        "winner_year": row["winner_year"],
        "horse_name": " / ".join(winners),
        "jockey_name": " / ".join(jockey for jockey in jockeys if jockey),
        "trainer_name": "",
        "finish_time": "",
        "margin": "",
        "source_refs": source_refs,
    }


def _read_detail_winners(path: Path) -> dict[str, dict]:
    winners = {}
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            results = ((record.get("modules") or {}).get("results") or {}).get("items") or []
            winner = next((item for item in results if int(item.get("finish_position") or 0) == 1), None)
            if winner:
                winners[str(record.get("slug") or "")] = winner
    return winners


def _enrich_current_winner(items: list[dict], *, event: dict, detail_winner: dict | None) -> list[dict]:
    if not detail_winner:
        return items
    current = next((item for item in items if int(item.get("winner_year") or 0) == int(event["year"])), None)
    if current is None or _normalize_name(current.get("horse_name") or "") != _normalize_name(detail_winner.get("horse_name") or ""):
        return items
    for field in ["jockey_name", "trainer_name", "finish_time", "margin"]:
        if not current.get(field) and detail_winner.get(field):
            current[field] = detail_winner[field]
    current.setdefault("source_refs", {})["current_result"] = (detail_winner.get("source_refs") or {}).get("primary", "")
    return items


def prepare(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)

    events = _read_jra_events(Path(args.events_csv))
    detail_winners = _read_detail_winners(Path(args.detail_jsonl))
    event_keys = {event["slug"]: _event_match_keys(event) for event in events}
    rows_by_key: dict[str, list[dict]] = defaultdict(list)
    downloaded_years = []
    errors = []

    for year in range(args.start_year, args.end_year + 1):
        url = JRA_HISTORY_URL.format(year=year)
        source_path = source_dir / f"source_jra_history_{year}.html"
        try:
            body = _download(url, source_path, allow_network=args.allow_network, timeout=args.timeout_seconds, sleep_seconds=args.sleep_seconds)
            rows = _parse_history_year(body, year=year, source_url=url)
        except Exception as exc:
            errors.append({"year": year, "url": url, "error": str(exc)})
            if args.fail_fast:
                raise
            continue
        downloaded_years.append(year)
        for row in rows:
            rows_by_key[row["race_key"]].append(row)

    jsonl_path = output_dir / "jra_history_winner_candidates_2026.jsonl"
    review_path = output_dir / "jra_history_winner_review_2026.csv"
    unmatched_path = output_dir / "jra_history_winner_unmatched_2026.csv"
    summary = {
        "source": "jra_official_graded_race_list_history",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": len(events),
        "events": 0,
        "history_items": 0,
        "downloaded_years": downloaded_years,
        "events_skipped_partial": 0,
        "skipped": [],
        "unmatched_events": 0,
        "errors": errors,
    }

    review_rows = []
    unmatched_rows = []
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for event in events:
            matched_rows = []
            matched_keys = []
            for key in sorted(event_keys[event["slug"]]):
                rows = rows_by_key.get(key, [])
                if rows:
                    matched_rows.extend(rows)
                    matched_keys.append(key)
            by_year: dict[int, dict] = {}
            for row in matched_rows:
                # Keep one official row per year. JRA rows already merge dead-heats
                # inside the winner cell for a single race.
                by_year.setdefault(int(row["winner_year"]), row)
            items = [_history_item(row) for _, row in sorted(by_year.items(), reverse=True)]
            items = _enrich_current_winner(
                items,
                event=event,
                detail_winner=detail_winners.get(event["slug"]),
            )
            if not items:
                summary["unmatched_events"] += 1
                unmatched_rows.append(
                    {
                        "slug": event["slug"],
                        "original_name": event["original_name"],
                        "aliases": event.get("aliases") or "",
                        "match_keys": "|".join(sorted(event_keys[event["slug"]])),
                    }
                )
                continue
            if errors and not args.allow_partial_history:
                summary["events_skipped_partial"] += 1
                summary["skipped"].append(
                    {
                        "slug": event["slug"],
                        "reason": "partial_year_range",
                        "history_items": len(items),
                        "downloaded_years": downloaded_years,
                        "errors": errors,
                    }
                )
                continue
            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": "jra_official_graded_race_list_history",
                "source_url": JRA_HISTORY_URL.format(year=args.end_year),
                "modules": {"history_winners": {"items": items}},
                "metadata": {
                    "matched_keys": matched_keys,
                    "year_range": [args.start_year, args.end_year],
                    "source_kind": "jra_official_graded_race_list_history",
                    "partial_history": bool(errors),
                    "diagnostics": errors,
                },
            }
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["history_items"] += len(items)
            review_rows.append(
                {
                    "slug": event["slug"],
                    "original_name": event["original_name"],
                    "history_count": len(items),
                    "first_year": min(item["winner_year"] for item in items),
                    "latest_year": max(item["winner_year"] for item in items),
                    "latest_winner": items[0]["horse_name"],
                    "matched_keys": "|".join(matched_keys),
                }
            )

    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "history_count", "first_year", "latest_year", "latest_winner", "matched_keys"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    with unmatched_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "aliases", "match_keys"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unmatched_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JRA 2026 race historical winner candidates from official graded-race lists.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--detail-jsonl", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start-year", type=int, default=2002)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-partial-history", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

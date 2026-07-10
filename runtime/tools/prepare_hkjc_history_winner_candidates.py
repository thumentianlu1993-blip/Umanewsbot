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

from bs4 import BeautifulSoup

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover
    OpenCC = None


HKJC_BASE_URL = "https://racing.hkjc.com"
SEASON_RACES_API = "https://racing.hkjc.com/contentAsset/api/getSeasonRaces"
COUNTRY_SUFFIX_RE = re.compile(r"\s*[\(\（][A-Z]{2,3}[\)\）]\s*$")
HKJC_HORSE_CODE_RE = re.compile(r"\s*[\(\（][A-Z]\d{3}[\)\）]\s*$")
FINISH_POSITION_RE = re.compile(r"^(\d+)")
SPONSOR_PREFIXES = ("花旗銀行", "富衛保險", "渣打", "中銀香港", "浪琴", "寶馬", "東方表行")


def _converter():
    return OpenCC("t2s") if OpenCC is not None else None


def _to_simplified(value: str, converter) -> str:
    value = _collapse(value)
    return converter.convert(value) if converter is not None and value else value


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _text(node) -> str:
    if node is None:
        return ""
    return _collapse(node.get_text(" ", strip=True))


def _strip_country_suffix(value: str) -> str:
    value = HKJC_HORSE_CODE_RE.sub("", value).strip()
    return COUNTRY_SUFFIX_RE.sub("", value).strip()


def _normalize_name(value: str) -> str:
    value = _collapse(value)
    value = value.replace("（", "(").replace("）", ")")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"^(?:一級賽|二級賽|三級賽|G1|G2|G3)[-：:\s]*", "", value)
    value = value.replace("(讓賽)", "")
    for prefix in SPONSOR_PREFIXES:
        if value.startswith(prefix) and len(value) > len(prefix) + 2:
            value = value[len(prefix) :]
    return value


def _event_keys(row: dict) -> set[str]:
    values = [row.get("original_name") or "", row.get("chinese_name") or ""]
    values.extend(re.split(r"[|,]", row.get("aliases") or ""))
    keys = {_normalize_name(value) for value in values if value}
    return {key for key in keys if key}


def _cache_name(prefix: str, key: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").lower()
    return f"{prefix}_{safe[-120:]}.html"


def _download(url: str, path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    request = Request(
        url,
        headers={
            "User-Agent": "UmaFansBot/1.0 (+https://umafans.run; low-frequency history import)",
            "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
        },
    )
    before_network_request(url)
    with urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
    path.write_text(text, encoding="utf-8")
    return text


def _post_json(url: str, payload: dict, path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "User-Agent": "UmaFansBot/1.0 (+https://umafans.run; low-frequency history import)",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
        },
        method="POST",
    )
    before_network_request(url, method="POST")
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _parse_finish(value: str) -> tuple[int | None, str]:
    value = value.strip()
    match = FINISH_POSITION_RE.match(value)
    if not match:
        return None, ""
    return int(match.group(1)), value[match.end() :].strip()


def _parse_local_result_winner(html: str, *, source_url: str, race_name_hant: str, converter) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    result_table = None
    for table in soup.find_all("table"):
        headers = [_text(cell) for cell in table.select("tr:first-child th, tr:first-child td")]
        if "名次" in headers and "馬號" in headers and "馬名" in headers:
            result_table = table
            break
    if result_table is None:
        raise RuntimeError(f"HKJC 单场赛果页没有找到完整成绩表：{source_url}")
    for tr in result_table.select("tr")[1:]:
        cells = [_text(cell) for cell in tr.find_all(["td", "th"], recursive=False)]
        if len(cells) < 11:
            continue
        official_position, finish_suffix_hant = _parse_finish(cells[0])
        if official_position != 1:
            continue
        horse_name_hant = _strip_country_suffix(cells[2])
        if not horse_name_hant:
            continue
        return {
            "horse_name": _to_simplified(horse_name_hant, converter),
            "jockey_name": _to_simplified(cells[3], converter),
            "trainer_name": _to_simplified(cells[4], converter),
            "finish_time": _to_simplified(cells[10], converter) if len(cells) > 10 else "",
            "margin": _to_simplified(finish_suffix_hant, converter),
            "source_refs": {
                "primary": source_url,
                "source_language": "zh-hant",
                "source_kind": "hkjc_pattern_races_history_result",
                "official_race_name": race_name_hant,
                "hkjc_finish_position_text": cells[0],
                "horse_name_hant": horse_name_hant,
                "jockey_name_hant": cells[3],
                "trainer_name_hant": cells[4],
            },
        }
    return None


def _read_events(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _season_rows(seasons: list[str], source_dir: Path, args: argparse.Namespace) -> tuple[list[dict], list[dict]]:
    rows = []
    errors = []
    for season in seasons:
        try:
            data = _post_json(
                SEASON_RACES_API,
                {"lang": "zh-hk", "season": season},
                source_dir / f"source_hkjc_season_races_{season}.json",
                allow_network=args.allow_network,
                timeout=args.timeout_seconds,
                sleep_seconds=args.sleep_seconds,
            )
            for item in ((data.get("data") or {}).get("raceList") or []):
                race_name = ((item.get("raceName") or {}).get("value") or "").strip()
                race_url = ((item.get("raceURL") or {}).get("value") or "").strip()
                if not race_name or not race_url:
                    continue
                rows.append(
                    {
                        "season": season,
                        "race_name": race_name,
                        "race_key": _normalize_name(race_name),
                        "race_url": urljoin(HKJC_BASE_URL, race_url),
                        "race_date_value": (item.get("raceDate") or {}).get("dateValue"),
                    }
                )
        except Exception as exc:
            errors.append({"season": season, "error": str(exc)})
            if args.fail_fast:
                raise
    return rows, errors


def _winner_year_from_url(url: str) -> int | None:
    match = re.search(r"[?&]RaceDate=(\d{4})/", url, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"[?&]racedate=(\d{4})/", url, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def prepare(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    converter = _converter()

    events = [row for row in _read_events(Path(args.events_csv)) if row.get("country_region") == "hong_kong"]
    season_rows, errors = _season_rows(args.seasons.split(","), source_dir, args)
    rows_by_key: dict[str, list[dict]] = {}
    for row in season_rows:
        rows_by_key.setdefault(row["race_key"], []).append(row)

    jsonl_path = output_dir / "hkjc_history_winner_candidates_2026.jsonl"
    review_path = output_dir / "hkjc_history_winner_review_2026.csv"
    unmatched_path = output_dir / "hkjc_history_winner_unmatched_2026.csv"
    summary = {
        "source": "hkjc_pattern_races_history_result",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": len(events),
        "events": 0,
        "history_items": 0,
        "season_rows": len(season_rows),
        "events_without_history": 0,
        "events_skipped_partial": 0,
        "skipped": [],
        "errors": errors,
    }
    review_rows = []
    unmatched_rows = []

    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for event in events:
            keys = _event_keys(event)
            matched = []
            matched_keys = []
            for key in sorted(keys):
                if key in rows_by_key:
                    matched.extend(rows_by_key[key])
                    matched_keys.append(key)
            by_year: dict[int, dict] = {}
            for row in matched:
                year = _winner_year_from_url(row["race_url"])
                if year is None:
                    continue
                html = _download(
                    row["race_url"],
                    source_dir / _cache_name("source_hkjc_history_result", row["race_url"]),
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                )
                winner = _parse_local_result_winner(html, source_url=row["race_url"], race_name_hant=row["race_name"], converter=converter)
                if winner:
                    by_year[year] = {"winner_year": year, **winner}
            items = [by_year[year] for year in sorted(by_year, reverse=True)]
            if not items:
                summary["events_without_history"] += 1
                unmatched_rows.append(
                    {
                        "slug": event["slug"],
                        "original_name": event["original_name"],
                        "match_keys": "|".join(sorted(keys)),
                    }
                )
                continue
            if errors and not args.allow_partial_history:
                summary["events_skipped_partial"] += 1
                summary["skipped"].append(
                    {
                        "slug": event["slug"],
                        "reason": "partial_season_range",
                        "history_items": len(items),
                        "seasons": args.seasons.split(","),
                        "errors": errors,
                    }
                )
                continue
            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": "hkjc_pattern_races_history_result",
                "source_url": SEASON_RACES_API,
                "modules": {"history_winners": {"items": items}},
                "metadata": {
                    "source_kind": "hkjc_pattern_races_history_result",
                    "seasons": args.seasons.split(","),
                    "matched_keys": matched_keys,
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
        fieldnames = ["slug", "original_name", "match_keys"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unmatched_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HKJC 2026 local pattern-race historical winner candidates from official key races API and result pages.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seasons", default="2223,2324,2425,2526")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-partial-history", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

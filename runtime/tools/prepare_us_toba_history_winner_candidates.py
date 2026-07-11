#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from race_event_request_budget import before_network_request
from race_event_source_cache import write_source_cache_text

from bs4 import BeautifulSoup


TOBA_URL = "https://toba.org/graded-stakes/{year}-races/"
COUNTRY_SUFFIX_RE = re.compile(r"\s*[\(\（][A-Z]{2,3}[\)\）]\s*$")
GRADE_VALUES = {"G1", "G2", "G3", "1", "2", "3", "GRADE I", "GRADE II", "GRADE III", "GI", "GII", "GIII"}
SPONSOR_PREFIXES = (
    "FANDUEL TV",
    "FANDUEL",
    "FASIG-TIPTON",
    "RESORTS WORLD CASINO",
    "CAESARS SPORTSBOOK",
    "CAESARDS SPORTSBOOK",
    "MINT",
    "AGS",
    "AINSWORTH",
    "EXACTA SYSTEMS",
    "KTDF",
    "DK HORSE",
    "SPENDTHRIFT FARM",
    "SPENDTHRIFT",
    "LIGHT & WONDER",
    "BLACKWOOD",
    "RESOLUTE RACING",
    "NETJETS",
    "JOHN DEERE",
    "NEVER DAY DIE",
    "BIG ASS FANS",
    "ARISTOCRAT",
)


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _strip_country_suffix(value: str) -> str:
    return COUNTRY_SUFFIX_RE.sub("", _collapse(value)).strip()


def _normalize_name(value: str) -> str:
    value = _collapse(value).upper()
    value = re.sub(r"\((?:FORMERLY|FORMERLY KNOWN AS)[^)]+\)", "", value, flags=re.IGNORECASE)
    value = value.replace("STAKES", "S.")
    value = re.sub(r"\bSTK\.?\b", "S.", value)
    value = value.replace("’", "'")
    value = re.sub(r"\bPRESENTED BY\b.*$", "", value)
    value = re.sub(r"\bSPONSORED BY\b.*$", "", value)
    for prefix in SPONSOR_PREFIXES:
        if value.startswith(prefix + " "):
            value = value[len(prefix) + 1 :]
    value = re.sub(r"\bS\.$", "S", value)
    value = re.sub(r"\bINVITATIONAL\b", "", value)
    value = re.sub(r"[^A-Z0-9]+", "", value)
    return value


def _name_variants(value: str) -> set[str]:
    variants = {_normalize_name(value)}
    raw = _collapse(value).upper()
    formerly = re.search(r"\((?:FORMERLY|FORMERLY KNOWN AS)\s+([^)]+)\)", raw, flags=re.IGNORECASE)
    if formerly:
        variants.add(_normalize_name(formerly.group(1)))
    for prefix in SPONSOR_PREFIXES:
        if raw.startswith(prefix + " "):
            variants.add(_normalize_name(raw[len(prefix) + 1 :]))
    expanded = set(variants)
    for key in variants:
        if key.endswith("S") and len(key) > 4:
            expanded.add(key[:-1])
        if key.endswith("H") and len(key) > 4:
            expanded.add(key[:-1] + "S")
            expanded.add(key[:-1])
    return {key for key in expanded if key}


def _event_keys(row: dict) -> set[str]:
    values = [row.get("original_name") or "", row.get("chinese_name") or ""]
    values.extend(re.split(r"[|,]", row.get("aliases") or ""))
    keys = set()
    for value in values:
        if value:
            keys.update(_name_variants(value))
    return {key for key in keys if key}


def _download(url: str, path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    request = Request(url, headers={"User-Agent": "UmaFansBot/1.0 (+https://umafans.run; low-frequency history import)"})
    before_network_request(url)
    with urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
    write_source_cache_text(path, text, source_url=url)
    return text


def _header_index(headers: list[str], names: set[str]) -> int | None:
    normalized = [header.strip().lower() for header in headers]
    for index, header in enumerate(normalized):
        if header in names:
            return index
    return None


def _parse_toba_year(html: str, *, year: int, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError(f"TOBA table not found: {source_url}")
    rows = table.find_all("tr")
    if not rows:
        return []
    headers = [_collapse(cell.get_text(" ", strip=True)) for cell in rows[0].find_all(["th", "td"])]
    stake_idx = _header_index(headers, {"stake", "stakes"})
    winner_idx = _header_index(headers, {"winner"})
    grade_idx = _header_index(headers, {"gr", "grade", "status"})
    date_idx = _header_index(headers, {"date"})
    track_idx = _header_index(headers, {"track"})
    if stake_idx is None or winner_idx is None or grade_idx is None:
        raise RuntimeError(f"TOBA header not understood for {year}: {headers}")
    parsed = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"], recursive=False)
        values = [_collapse(cell.get_text(" ", strip=True)) for cell in cells]
        if len(values) <= max(stake_idx, winner_idx, grade_idx):
            continue
        grade = values[grade_idx].upper().replace("GRADE ", "G")
        if grade not in GRADE_VALUES:
            continue
        winner = _strip_country_suffix(values[winner_idx])
        if not winner or winner.lower() in {"not run", "not yet run", "canceled", "cancelled"}:
            continue
        stake = values[stake_idx]
        link = ""
        if cells[winner_idx].find("a", href=True):
            link = cells[winner_idx].find("a", href=True)["href"]
        elif tr.find("a", href=True):
            link = tr.find("a", href=True)["href"]
        parsed.append(
            {
                "winner_year": year,
                "race_name": stake,
                "race_key": _normalize_name(stake),
                "race_keys": sorted(_name_variants(stake)),
                "horse_name": winner,
                "grade": values[grade_idx],
                "track": values[track_idx] if track_idx is not None and len(values) > track_idx else "",
                "race_date": values[date_idx] if date_idx is not None and len(values) > date_idx else "",
                "chart_url": link,
                "source_url": source_url,
            }
        )
    return parsed


def _history_item(row: dict) -> dict:
    return {
        "winner_year": row["winner_year"],
        "horse_name": row["horse_name"],
        "jockey_name": "",
        "trainer_name": "",
        "finish_time": "",
        "margin": "",
        "source_refs": {
            "primary": row["source_url"],
            "chart_url": row["chart_url"],
            "source_language": "en",
            "source_kind": "toba_american_graded_stakes_history",
            "official_race_name": row["race_name"],
            "grade": row["grade"],
            "track": row["track"],
            "race_date": row["race_date"],
        },
    }


def _read_events(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def prepare(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    years = [int(value.strip()) for value in args.years.split(",") if value.strip()]

    rows_by_key: dict[str, list[dict]] = {}
    errors = []
    for year in years:
        url = TOBA_URL.format(year=year)
        try:
            html = _download(url, source_dir / f"source_toba_{year}_graded_stakes.html", allow_network=args.allow_network, timeout=args.timeout_seconds, sleep_seconds=args.sleep_seconds)
            rows = _parse_toba_year(html, year=year, source_url=url)
        except Exception as exc:
            errors.append({"year": year, "error": str(exc)})
            if args.fail_fast:
                raise
            continue
        for row in rows:
            for key in row.get("race_keys") or [row["race_key"]]:
                rows_by_key.setdefault(key, []).append(row)

    events = [row for row in _read_events(Path(args.events_csv)) if row.get("country_region") == "united_states"]
    jsonl_path = output_dir / "us_toba_history_winner_candidates_2026.jsonl"
    review_path = output_dir / "us_toba_history_winner_review_2026.csv"
    unmatched_path = output_dir / "us_toba_history_winner_unmatched_2026.csv"
    summary = {
        "source": "toba_american_graded_stakes_history",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": len(events),
        "events": 0,
        "history_items": 0,
        "events_without_history": 0,
        "events_skipped_partial": 0,
        "skipped": [],
        "errors": errors,
    }
    review_rows = []
    unmatched_rows = []
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for event in events:
            matched_rows = []
            matched_keys = []
            for key in sorted(_event_keys(event)):
                rows = rows_by_key.get(key) or []
                if rows:
                    matched_rows.extend(rows)
                    matched_keys.append(key)
            by_year: dict[int, dict] = {}
            for row in matched_rows:
                by_year.setdefault(int(row["winner_year"]), row)
            items = [_history_item(by_year[year]) for year in sorted(by_year, reverse=True)]
            if not items:
                summary["events_without_history"] += 1
                unmatched_rows.append({"slug": event["slug"], "original_name": event["original_name"], "keys": "|".join(sorted(_event_keys(event)))})
                continue
            if errors and not args.allow_partial_history:
                summary["events_skipped_partial"] += 1
                summary["skipped"].append(
                    {
                        "slug": event["slug"],
                        "reason": "partial_year_range",
                        "history_items": len(items),
                        "years": years,
                        "errors": errors,
                    }
                )
                continue
            jsonl.write(
                json.dumps(
                    {
                        "year": int(event["year"]),
                        "slug": event["slug"],
                        "source_name": "toba_american_graded_stakes_history",
                        "source_url": TOBA_URL.format(year=max(years)),
                        "modules": {"history_winners": {"items": items}},
                        "metadata": {
                            "source_kind": "toba_american_graded_stakes_history",
                            "years": years,
                            "matched_keys": matched_keys,
                            "partial_history": bool(errors),
                            "diagnostics": errors,
                        },
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
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
        fieldnames = ["slug", "original_name", "keys"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unmatched_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate US 2026 graded race historical winner candidates from TOBA annual graded stakes pages.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--years", default="2023,2024,2025,2026")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-partial-history", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

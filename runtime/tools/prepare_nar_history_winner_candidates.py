#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from race_event_request_budget import before_network_request

from bs4 import BeautifulSoup


USER_AGENT = "UmaFansBot/1.0 (+https://umafans.run; low-frequency history import)"


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _text(node) -> str:
    if node is None:
        return ""
    return _collapse(node.get_text(" ", strip=True))


def _download(url: str, path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    before_network_request(url)
    with urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
    path.write_text(text, encoding="utf-8")
    return text


def _cache_name(prefix: str, url: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]+", "_", url).strip("_").lower()
    return f"{prefix}_{key[-120:]}.html"


def _read_events(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _source_refs(row: dict) -> dict:
    raw = row.get("source_refs") or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _introduction_url(detail_url: str) -> str:
    if not detail_url:
        return ""
    return detail_url.replace("/racecard.html", "/introduction.html")


def _racecard_url(detail_url: str) -> str:
    if not detail_url:
        return ""
    return detail_url.replace("/introduction.html", "/racecard.html")


def _race_year_from_result_url(url: str) -> int | None:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    raw_date = (params.get("k_raceDate") or params.get("k_racedate") or [""])[0]
    match = re.match(r"(\d{4})[/%]", raw_date)
    return int(match.group(1)) if match else None


def _past_result_links(introduction_html: str, introduction_url: str) -> list[tuple[int, str]]:
    soup = BeautifulSoup(introduction_html, "html.parser")
    links: list[tuple[int, str]] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "TodayRaceInfo/RaceMarkTable" not in href:
            continue
        absolute = urljoin(introduction_url, href)
        if absolute in seen:
            continue
        year = _race_year_from_result_url(absolute)
        if year is None:
            continue
        seen.add(absolute)
        links.append((year, absolute))
    return links


def _racecard_link_from_detail(detail_html: str, detail_url: str) -> str:
    soup = BeautifulSoup(detail_html, "html.parser")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "TodayRaceInfo/DebaTable" in href:
            return urljoin(detail_url, href)
    return ""


def _result_link_from_deba(deba_html: str, deba_url: str) -> str:
    soup = BeautifulSoup(deba_html, "html.parser")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "TodayRaceInfo/RaceMarkTable" in href:
            return urljoin(deba_url, href)
    return ""


def _parse_result_winner(result_html: str, *, source_url: str, winner_year: int, race_name: str) -> dict | None:
    soup = BeautifulSoup(result_html, "html.parser")
    table = soup.select_one("section.gradeTable table")
    if table is None:
        raise RuntimeError(f"NAR 成绩页没有找到成绩主表：{source_url}")
    for tr in table.select("tr.tBorder"):
        cells = tr.find_all(["td", "th"], recursive=False)
        if len(cells) < 16:
            continue
        finish_text = _text(cells[0])
        if finish_text != "1":
            continue
        horse_name = _text(cells[3])
        if not horse_name:
            continue
        return {
            "winner_year": winner_year,
            "horse_name": horse_name,
            "jockey_name": _text(cells[7]),
            "trainer_name": _text(cells[8]),
            "finish_time": _text(cells[10]),
            "margin": _text(cells[11]),
            "source_refs": {
                "primary": source_url,
                "source_language": "ja",
                "source_kind": "keiba_go_jp_dirt_graded_history_result",
                "official_race_name": race_name,
                "nar_finish_position_text": finish_text,
            },
        }
    return None


def _current_result_link(row: dict, detail_url: str, source_dir: Path, args: argparse.Namespace) -> str:
    if row.get("status") != "finished":
        return ""
    racecard_url = _racecard_url(detail_url)
    if not racecard_url:
        return ""
    racecard_html = _download(
        racecard_url,
        source_dir / _cache_name("source_nar_current_racecard", racecard_url),
        allow_network=args.allow_network,
        timeout=args.timeout_seconds,
        sleep_seconds=args.sleep_seconds,
    )
    deba_url = _racecard_link_from_detail(racecard_html, racecard_url)
    if not deba_url:
        return ""
    deba_html = _download(
        deba_url,
        source_dir / _cache_name("source_nar_current_deba", deba_url),
        allow_network=args.allow_network,
        timeout=args.timeout_seconds,
        sleep_seconds=args.sleep_seconds,
    )
    return _result_link_from_deba(deba_html, deba_url)


def prepare(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)

    jsonl_path = output_dir / "nar_history_winner_candidates_2026.jsonl"
    review_path = output_dir / "nar_history_winner_review_2026.csv"
    unmatched_path = output_dir / "nar_history_winner_unmatched_2026.csv"
    errors = []
    review_rows = []
    unmatched_rows = []
    summary = {
        "source": "keiba_go_jp_dirt_graded_history_result",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": 0,
        "events": 0,
        "history_items": 0,
        "events_with_current_year": 0,
        "events_without_history": 0,
        "events_skipped_partial": 0,
        "skipped": [],
        "errors": errors,
    }

    rows = [row for row in _read_events(Path(args.events_csv)) if row.get("country_region") == "japan"]
    summary["events_requested"] = len(rows)

    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for row in rows:
            slug = row["slug"]
            race_name = row["original_name"]
            refs = _source_refs(row)
            detail_url = refs.get("detail") or refs.get("primary") or ""
            intro_url = _introduction_url(detail_url)
            by_year: dict[int, dict] = {}
            matched_urls: list[str] = []
            diagnostics = []
            try:
                if intro_url:
                    intro_html = _download(
                        intro_url,
                        source_dir / _cache_name("source_nar_history_intro", intro_url),
                        allow_network=args.allow_network,
                        timeout=args.timeout_seconds,
                        sleep_seconds=args.sleep_seconds,
                    )
                    for year, result_url in _past_result_links(intro_html, intro_url):
                        result_html = _download(
                            result_url,
                            source_dir / _cache_name("source_nar_history_result", result_url),
                            allow_network=args.allow_network,
                            timeout=args.timeout_seconds,
                            sleep_seconds=args.sleep_seconds,
                        )
                        item = _parse_result_winner(result_html, source_url=result_url, winner_year=year, race_name=race_name)
                        if item:
                            by_year[year] = item
                            matched_urls.append(result_url)
                current_url = _current_result_link(row, detail_url, source_dir, args)
                if current_url:
                    result_html = _download(
                        current_url,
                        source_dir / _cache_name("source_nar_current_result", current_url),
                        allow_network=args.allow_network,
                        timeout=args.timeout_seconds,
                        sleep_seconds=args.sleep_seconds,
                    )
                    item = _parse_result_winner(result_html, source_url=current_url, winner_year=int(row["year"]), race_name=race_name)
                    if item:
                        by_year[int(row["year"])] = item
                        matched_urls.append(current_url)
                        summary["events_with_current_year"] += 1
            except Exception as exc:
                diagnostics.append({"slug": slug, "original_name": race_name, "error": str(exc)})
                errors.extend(diagnostics)
                if args.fail_fast:
                    raise

            items = [by_year[year] for year in sorted(by_year, reverse=True)]
            if not items:
                summary["events_without_history"] += 1
                unmatched_rows.append({"slug": slug, "original_name": race_name, "detail_url": detail_url, "introduction_url": intro_url})
                continue
            if diagnostics and not args.allow_partial_history:
                summary["events_skipped_partial"] += 1
                summary["skipped"].append(
                    {
                        "slug": slug,
                        "reason": "partial_history_chain",
                        "history_items": len(items),
                        "matched_urls": matched_urls[:10],
                        "diagnostics": diagnostics,
                    }
                )
                continue
            record = {
                "year": int(row["year"]),
                "slug": slug,
                "source_name": "keiba_go_jp_dirt_graded_history_result",
                "source_url": intro_url or detail_url,
                "modules": {"history_winners": {"items": items}},
                "metadata": {
                    "source_kind": "keiba_go_jp_dirt_graded_history_result",
                    "history_scope": "official_past_5_years_plus_current_result_when_finished",
                    "matched_urls": matched_urls[:10],
                    "partial_history": bool(diagnostics),
                    "diagnostics": diagnostics,
                },
            }
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["history_items"] += len(items)
            review_rows.append(
                {
                    "slug": slug,
                    "original_name": race_name,
                    "status": row.get("status") or "",
                    "history_count": len(items),
                    "first_year": min(item["winner_year"] for item in items),
                    "latest_year": max(item["winner_year"] for item in items),
                    "latest_winner": items[0]["horse_name"],
                    "has_2026": "yes" if any(item["winner_year"] == 2026 for item in items) else "no",
                    "source_url": intro_url or detail_url,
                }
            )

    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "status", "history_count", "first_year", "latest_year", "latest_winner", "has_2026", "source_url"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    with unmatched_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "detail_url", "introduction_url"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unmatched_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate NAR 2026 dirt graded race historical winner candidates from official keiba.go.jp pages.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-partial-history", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

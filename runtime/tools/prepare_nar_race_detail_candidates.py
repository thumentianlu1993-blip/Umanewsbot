#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from race_event_request_budget import before_network_request
from race_event_source_cache import write_source_cache_text

from bs4 import BeautifulSoup


KEIBA_BASE_URL = "https://www.keiba.go.jp"


def _text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _download(url: str, path: Path, *, allow_network: bool, timeout: int) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    request = Request(url, headers={"User-Agent": "UmaFansBot/1.0"})
    before_network_request(url)
    with urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
    write_source_cache_text(path, text, source_url=url)
    return text


def _slug_filename(prefix: str, url: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]+", "_", url).strip("_").lower()
    return f"{prefix}_{key[-110:]}.html"


def _read_events(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _should_fetch_results(event: dict, *, recovery_mode: bool = False) -> bool:
    return event.get("status") == "finished" or (
        recovery_mode and event.get("status") == "scheduled"
    )


def _racecard_link_from_detail(detail_html: str, detail_url: str) -> str:
    soup = BeautifulSoup(detail_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "TodayRaceInfo/DebaTable" in href:
            return urljoin(detail_url, href)
    return ""


def _detail_url_candidates(
    detail_url: str,
    *,
    recovery_mode: bool,
) -> list[str]:
    candidates = [detail_url]
    if recovery_mode and detail_url.endswith("/introduction.html"):
        candidates.append(urljoin(detail_url, "racecard.html"))
    return candidates


def _result_link_from_deba(deba_html: str, deba_url: str) -> str:
    soup = BeautifulSoup(deba_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "TodayRaceInfo/RaceMarkTable" in href:
            return urljoin(deba_url, href)
    return ""


def _parse_odds_popularity(value: str) -> tuple[str, str]:
    odds = ""
    popularity = ""
    parts = [part.strip() for part in value.split() if part.strip()]
    if parts:
        odds = parts[0]
    match = re.search(r"(\d+)人気", value)
    if match:
        popularity = match.group(1)
    return odds, popularity


def _parse_finish_position(value: str) -> int | None:
    value = value.strip()
    return int(value) if value.isdigit() else None


def _runner_status_from_finish_position(value: str) -> str:
    value = value.strip()
    if not value:
        return "unknown"
    if value in {"取消", "出走取消"}:
        return "withdrawn"
    if value in {"除外", "競走除外"}:
        return "scratched"
    if value in {"中止", "失格"}:
        return "unknown"
    return "declared"


def _parse_result_page(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("section.gradeTable table")
    if table is None:
        raise RuntimeError(f"NAR 结果页没有找到成绩主表：{source_url}")
    runners: list[dict] = []
    result_rows: list[dict] = []
    for index, tr in enumerate(table.select("tr.tBorder"), start=1):
        cells = tr.find_all(["td", "th"], recursive=False)
        if len(cells) < 16:
            continue
        finish_text = _text(cells[0])
        odds = _text(cells[15])
        popularity = _text(cells[14])
        source_refs = {
            "primary": source_url,
            "source_language": "ja",
            "source_kind": "keiba_go_jp_race_mark_table",
            "nar_finish_position_text": finish_text,
        }
        row = {
            "sort_order": index,
            "finish_position_text": finish_text,
            "official_finish_position": _parse_finish_position(finish_text),
            "barrier": _text(cells[1]),
            "horse_number": _text(cells[2]),
            "horse_name": _text(cells[3]),
            "jockey_name": _text(cells[7]),
            "trainer_name": _text(cells[8]),
            "carried_weight": _text(cells[6]),
            "finish_time": _text(cells[10]),
            "margin": _text(cells[11]),
            "popularity": popularity,
            "odds_value": odds,
            "running_status": _runner_status_from_finish_position(finish_text),
            "source_refs": source_refs,
        }
        if not row["horse_name"]:
            continue
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
                "popularity": row["popularity"],
                "running_status": row["running_status"],
                "source_refs": row["source_refs"],
            }
        )
        if row["official_finish_position"] is not None:
            result_rows.append(row)

    results: list[dict] = []
    for result_order, row in enumerate(result_rows, start=1):
        results.append(
            {
                "finish_position": result_order,
                "horse_number": row["horse_number"],
                "barrier": row["barrier"],
                "horse_name": row["horse_name"],
                "jockey_name": row["jockey_name"],
                "trainer_name": row["trainer_name"],
                "carried_weight": row["carried_weight"],
                "finish_time": row["finish_time"],
                "margin": row["margin"],
                "odds_value": row["odds_value"],
                "popularity": row["popularity"],
                "running_status": row["running_status"],
                "is_confirmed": True,
                "source_refs": {
                    **row["source_refs"],
                    "official_finish_position": row["official_finish_position"],
                },
            }
        )
    return runners, results, {"row_count": len(runners), "result_count": len(results)}


def _parse_deba_page(html: str, *, source_url: str) -> tuple[list[dict], dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("section.cardTable table")
    if table is None:
        raise RuntimeError(f"NAR 出馬表页没有找到主表：{source_url}")
    runners: list[dict] = []
    for index, tr in enumerate(table.select("tr.tBorder"), start=1):
        cells = tr.find_all(["td", "th"], recursive=False)
        if len(cells) < 5:
            continue
        odds, popularity = _parse_odds_popularity(_text(cells[4]))
        horse_name = _text(cells[2])
        if not horse_name:
            continue
        runners.append(
            {
                "sort_order": index,
                "horse_number": _text(cells[1]),
                "barrier": _text(cells[0]),
                "horse_name": horse_name,
                "jockey_name": _text(cells[3]),
                "trainer_name": "",
                "carried_weight": "",
                "odds_value": odds,
                "popularity": popularity,
                "running_status": "declared",
                "source_refs": {
                    "primary": source_url,
                    "source_language": "ja",
                    "source_kind": "keiba_go_jp_deba_table",
                },
            }
        )
    return runners, {"row_count": len(runners)}


def prepare_candidates(args) -> dict:
    events = _read_events(Path(args.events_csv))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    jsonl_path = output_dir / "nar_detail_candidates_2026.jsonl"
    review_csv_path = output_dir / "nar_detail_review_2026.csv"
    summary = {
        "source": "keiba_go_jp_deba_and_race_mark_tables",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "skipped": [],
        "errors": [],
    }
    review_rows = []

    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for event in events:
            if args.limit and summary["events"] >= args.limit:
                break
            source_refs = json.loads(event.get("source_refs") or "{}")
            detail_url = source_refs.get("detail") or ""
            if not detail_url:
                summary["skipped"].append({"slug": event["slug"], "reason": "missing_detail_url"})
                continue
            try:
                deba_url = ""
                attempted_detail_urls = []
                for candidate_detail_url in _detail_url_candidates(
                    detail_url,
                    recovery_mode=bool(
                        getattr(args, "recovery_mode", False)
                    ),
                ):
                    attempted_detail_urls.append(candidate_detail_url)
                    detail_html = _download(
                        candidate_detail_url,
                        source_dir
                        / _slug_filename(
                            "source_nar_detail",
                            candidate_detail_url,
                        ),
                        allow_network=args.allow_network,
                        timeout=args.timeout_seconds,
                    )
                    deba_url = _racecard_link_from_detail(
                        detail_html,
                        candidate_detail_url,
                    )
                    if deba_url:
                        detail_url = candidate_detail_url
                        break
                if not deba_url:
                    summary["skipped"].append(
                        {
                            "slug": event["slug"],
                            "reason": "racecard_not_published",
                            "detail_url": detail_url,
                            "attempted_detail_urls": attempted_detail_urls,
                        }
                    )
                    continue
                deba_html = _download(
                    deba_url,
                    source_dir / _slug_filename("source_nar_deba", deba_url),
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                )
                result_url = _result_link_from_deba(deba_html, deba_url)
                runners: list[dict]
                results: list[dict] = []
                if _should_fetch_results(
                    event,
                    recovery_mode=bool(getattr(args, "recovery_mode", False)),
                ) and result_url:
                    result_html = _download(
                        result_url,
                        source_dir / _slug_filename("source_nar_result", result_url),
                        allow_network=args.allow_network,
                        timeout=args.timeout_seconds,
                    )
                    runners, results, metadata = _parse_result_page(result_html, source_url=result_url)
                    modules = {
                        "runners": {"items": runners},
                        "results": {"items": results},
                    }
                    data_source_url = result_url
                else:
                    runners, metadata = _parse_deba_page(deba_html, source_url=deba_url)
                    modules = {"runners": {"items": runners}}
                    data_source_url = deba_url
                if not runners:
                    summary["skipped"].append({"slug": event["slug"], "reason": "no_runner_rows", "detail_url": detail_url})
                    continue
            except Exception as exc:
                summary["errors"].append({"slug": event["slug"], "detail_url": detail_url, "error": str(exc)})
                if args.fail_fast:
                    raise
                continue

            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": "keiba_go_jp",
                "source_url": data_source_url,
                "modules": modules,
                "metadata": metadata,
            }
            if str(event.get("event_id") or "").strip():
                record["event_id"] = int(event["event_id"])
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["runner_items"] += len(runners)
            summary["result_items"] += len(results)
            review_rows.append(
                {
                    "slug": event["slug"],
                    "original_name": event["original_name"],
                    "status": event["status"],
                    "source_url": data_source_url,
                    "runners": len(runners),
                    "results": len(results),
                    "winner": results[0]["horse_name"] if results else "",
                    "winner_jockey": results[0]["jockey_name"] if results else "",
                }
            )

    with review_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "status", "source_url", "runners", "results", "winner", "winner_jockey"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate NAR 2026 runner/result candidate JSONL from keiba.go.jp official pages.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--recovery-mode", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare_candidates(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

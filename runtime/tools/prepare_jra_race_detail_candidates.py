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

from bs4 import BeautifulSoup


JRA_BASE_URL = "https://www.jra.go.jp"
JRA_RESULT_RE = re.compile(r"/datafile/seiseki/(?:replay/2026/\d{3}|g1/[^\"']+/result/[^\"']+2026)\.html")
WAKU_RE = re.compile(r"枠(\d+)")


def _text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _decode_jra_html(body: bytes) -> str:
    return body.decode("cp932", errors="replace")


def _download(url: str, path: Path, *, allow_network: bool, timeout: int) -> bytes:
    if path.exists():
        return path.read_bytes()
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    request = Request(url, headers={"User-Agent": "UmaFansBot/1.0"})
    before_network_request(url)
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
    path.write_bytes(body)
    return body


def _extract_result_links(list_html_path: Path) -> list[str]:
    raw = list_html_path.read_bytes()
    try:
        list_html = raw.decode("utf-8")
    except UnicodeDecodeError:
        list_html = _decode_jra_html(raw)
    soup = BeautifulSoup(list_html, "html.parser")
    links = []
    for href in (a.get("href") for a in soup.find_all("a", href=True)):
        if JRA_RESULT_RE.search(href):
            links.append(urljoin(JRA_BASE_URL, href))
    seen = set()
    unique_links = []
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        unique_links.append(link)
    return unique_links


def _source_filename(source_url: str) -> str:
    path = source_url.split("?", 1)[0].rstrip("/")
    replay_match = re.search(r"/replay/2026/(\d{3})\.html$", path)
    if replay_match:
        return f"source_jra_2026_{replay_match.group(1)}.html"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_").lower()
    return f"source_jra_{slug[-80:]}.html"


def _read_finished_events(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            row
            for row in reader
            if (row.get("status") or "").strip() == "finished"
        ]


def _parse_barrier(cell) -> str:
    if cell is None:
        return ""
    alt_text = " ".join(img.get("alt", "") for img in cell.find_all("img"))
    match = WAKU_RE.search(alt_text)
    if match:
        return match.group(1)
    return _text(cell)


def _parse_finish_position(value: str) -> int | None:
    value = value.strip()
    if not value.isdigit():
        return None
    return int(value)


def _runner_status_from_finish_position(value: str) -> str:
    value = value.strip()
    if value == "取消":
        return "withdrawn"
    if value == "除外":
        return "scratched"
    if value == "中止":
        return "unknown"
    return "declared"


def _parse_detail_page(body: bytes, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    soup = BeautifulSoup(_decode_jra_html(body), "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError(f"JRA 结果页没有找到主表：{source_url}")

    header = _text(soup.select_one(".race_header"))
    race_title = _text(soup.select_one(".race_title"))
    rows: list[dict] = []
    for index, tr in enumerate(table.find_all("tr")[1:], start=1):
        cells = {
            "place": tr.find("td", class_="place"),
            "waku": tr.find("td", class_="waku"),
            "num": tr.find("td", class_="num"),
            "horse": tr.find("td", class_="horse"),
            "weight": tr.find("td", class_="weight"),
            "jockey": tr.find("td", class_="jockey"),
            "time": tr.find("td", class_="time"),
            "margin": tr.find("td", class_="margin"),
            "trainer": tr.find("td", class_="trainer"),
            "pop": tr.find("td", class_="pop"),
        }
        horse_name = _text(cells["horse"])
        if not horse_name:
            continue
        finish_position_text = _text(cells["place"])
        row = {
            "sort_order": index,
            "finish_position_text": finish_position_text,
            "finish_position": _parse_finish_position(finish_position_text),
            "barrier": _parse_barrier(cells["waku"]),
            "horse_number": _text(cells["num"]),
            "horse_name": horse_name,
            "jockey_name": _text(cells["jockey"]),
            "trainer_name": _text(cells["trainer"]),
            "carried_weight": _text(cells["weight"]),
            "finish_time": _text(cells["time"]),
            "margin": _text(cells["margin"]),
            "popularity": _text(cells["pop"]),
            "running_status": _runner_status_from_finish_position(finish_position_text),
            "source_refs": {
                "primary": source_url,
                "source_language": "ja",
                "source_kind": "jra_official_result_page",
                "jra_finish_position_text": finish_position_text,
            },
        }
        rows.append(row)

    runners = []
    results = []
    result_order = 0
    for row in rows:
        runners.append(
            {
                "sort_order": row["sort_order"],
                "horse_number": row["horse_number"],
                "barrier": row["barrier"],
                "horse_name": row["horse_name"],
                "jockey_name": row["jockey_name"],
                "trainer_name": row["trainer_name"],
                "carried_weight": row["carried_weight"],
                "popularity": row["popularity"],
                "running_status": row["running_status"],
                "source_refs": row["source_refs"],
            }
        )
        if row["finish_position"] is None:
            continue
        result_order += 1
        source_refs = {
            **row["source_refs"],
            "official_finish_position": row["finish_position"],
        }
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
                "popularity": row["popularity"],
                "running_status": row["running_status"],
                "is_confirmed": True,
                "source_refs": source_refs,
            }
        )
    metadata = {
        "race_header": header,
        "race_title": race_title,
        "row_count": len(rows),
        "result_count": len(results),
    }
    return runners, results, metadata


def prepare_candidates(args) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    finished_events = _read_finished_events(Path(args.events_csv))
    result_links = _extract_result_links(Path(args.source_html))
    if len(result_links) < len(finished_events):
        raise RuntimeError(f"结果页链接不足：links={len(result_links)} finished_events={len(finished_events)}")
    if args.limit:
        finished_events = finished_events[: args.limit]

    jsonl_path = output_dir / "jra_detail_candidates_2026.jsonl"
    review_csv_path = output_dir / "jra_detail_review_2026.csv"
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)

    summary = {
        "source": "jra_official_result_pages",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "errors": [],
    }
    review_rows = []
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for index, event in enumerate(finished_events):
            source_url = result_links[index]
            source_path = source_dir / _source_filename(source_url)
            try:
                body = _download(source_url, source_path, allow_network=args.allow_network, timeout=args.timeout_seconds)
                runners, results, metadata = _parse_detail_page(body, source_url=source_url)
            except Exception as exc:
                summary["errors"].append({"slug": event["slug"], "source_url": source_url, "error": str(exc)})
                if args.fail_fast:
                    raise
                continue
            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": "jra_official_result_page",
                "source_url": source_url,
                "modules": {
                    "runners": {"items": runners},
                    "results": {"items": results},
                },
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
                    "source_url": source_url,
                    "runners": len(runners),
                    "results": len(results),
                    "winner": results[0]["horse_name"] if results else "",
                    "winner_jockey": results[0]["jockey_name"] if results else "",
                    "race_title": metadata["race_title"],
                }
            )

    with review_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "source_url", "runners", "results", "winner", "winner_jockey", "race_title"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JRA 2026 runner/result candidate JSONL from official result pages.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--source-html", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    summary = prepare_candidates(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

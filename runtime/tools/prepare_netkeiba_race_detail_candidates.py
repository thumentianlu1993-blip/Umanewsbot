#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from race_event_request_budget import before_network_request
from race_event_safe_http import fetch_https, validate_https_url
from race_event_source_cache import write_source_cache


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node is not None else ""


def _decode_source(body: bytes) -> str:
    head = body[:4096].lower()
    encoding = "euc-jp" if b"charset=euc-jp" in head else "utf-8"
    return body.decode(encoding, errors="replace")


def _approved_result_url(event: dict) -> str:
    try:
        source_refs = json.loads(event.get("source_refs") or "{}")
    except (TypeError, json.JSONDecodeError):
        return ""
    evidence = (((source_refs.get("detail_discovery") or {}).get("urls") or {}).get("result_url") or {})
    if evidence.get("source_provider") != "netkeiba":
        return ""
    return str(evidence.get("url") or "").strip()


def read_cached_source(url: str, *, manifest_path: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if manifest.get("schema_version") != "1.0" or not isinstance(files, dict):
        raise RuntimeError("netkeiba source cache manifest is invalid")
    identities = [identity for identity in files.values() if identity.get("source_url") == url]
    if len(identities) != 1:
        raise RuntimeError(f"netkeiba source cache identity is missing or duplicated: {url}")
    identity = identities[0]
    root = manifest_path.parent.resolve()
    source = (root / str(identity.get("path") or "")).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("netkeiba source cache path escapes manifest directory") from exc
    if not source.is_file():
        raise RuntimeError(f"netkeiba source cache file is missing: {source}")
    body = source.read_bytes()
    if len(body) != int(identity.get("size") or -1) or hashlib.sha256(body).hexdigest() != identity.get("sha256"):
        raise RuntimeError(f"netkeiba source cache identity changed: {source}")
    return _decode_source(body)


def _link_value(cell, pattern: str) -> tuple[str, str]:
    link = cell.find("a", href=re.compile(pattern)) if cell is not None else None
    return (_text(link or cell), str(link.get("href") or "") if link else "")


def _runner_status(finish_text: str) -> str:
    if finish_text.isdigit():
        return "declared"
    if "取消" in finish_text:
        return "withdrawn"
    if "除外" in finish_text:
        return "scratched"
    if "中止" in finish_text:
        return "did_not_finish"
    return "unknown"


def parse_netkeiba_result_page(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.race_table_01")
    if table is None:
        raise RuntimeError(f"netkeiba result table is missing: {source_url}")
    title = _text(soup.select_one(".mainrace_data h1") or soup.select_one("h1"))
    parsed_rows: list[dict] = []
    for source_order, tr in enumerate(table.find_all("tr")[1:], start=1):
        cells = tr.find_all("td")
        if len(cells) < 19:
            continue
        finish_text = _text(cells[0])
        horse_number = _text(cells[2])
        horse_name, horse_url = _link_value(cells[3], r"/horse/")
        jockey_name, jockey_url = _link_value(cells[6], r"/jockey/")
        trainer_cell = next((cell for cell in cells if cell.find("a", href=re.compile(r"/trainer/"))), None)
        trainer_name, trainer_url = _link_value(trainer_cell, r"/trainer/")
        if not horse_name or not horse_number:
            continue
        try:
            sort_order = int(horse_number)
        except ValueError:
            sort_order = source_order
        source_refs = {
            "primary": source_url,
            "source_kind": "netkeiba_result",
            "source_language": "ja",
            "official_finish_position": int(finish_text) if finish_text.isdigit() else None,
            "finish_position_text": finish_text,
            "frame_number": _text(cells[1]),
            "sex_age": _text(cells[4]),
            "body_weight": _text(cells[18]),
            "horse_url": horse_url,
            "jockey_url": jockey_url,
            "trainer_url": trainer_url,
            "passing_order": _text(cells[14]) if len(cells) > 14 else "",
            "final_section": _text(cells[15]) if len(cells) > 15 else "",
        }
        parsed_rows.append(
            {
                "sort_order": sort_order,
                "source_order": source_order,
                "horse_number": horse_number,
                "barrier": _text(cells[1]),
                "horse_name": horse_name,
                "jockey_name": jockey_name,
                "trainer_name": re.sub(r"^\[[^]]+\]", "", trainer_name).strip(),
                "carried_weight": _text(cells[5]),
                "finish_time": _text(cells[7]),
                "margin": _text(cells[8]),
                "odds_value": _text(cells[16]) if len(cells) > 16 else "",
                "running_status": _runner_status(finish_text),
                "source_refs": source_refs,
            }
        )
    if not parsed_rows:
        raise RuntimeError(f"netkeiba result table has no runner rows: {source_url}")
    runners = [
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
        for row in sorted(parsed_rows, key=lambda item: (item["sort_order"], item["source_order"]))
    ]
    finished = sorted(
        (row for row in parsed_rows if row["source_refs"]["official_finish_position"] is not None),
        key=lambda item: (item["source_refs"]["official_finish_position"], item["source_order"]),
    )
    results = [
        {
            "finish_position": index,
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
            "source_refs": row["source_refs"],
        }
        for index, row in enumerate(finished, start=1)
    ]
    return runners, results, {"race_title": title, "row_count": len(runners), "result_count": len(results)}


def _download(url: str, path: Path, *, allow_network: bool, timeout: int) -> str:
    validate_https_url(url, allowed_hosts=("netkeiba.com",))
    if path.exists():
        return _decode_source(path.read_bytes())
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    before_network_request(url)
    body, _response = fetch_https(
        url,
        allowed_hosts=("netkeiba.com",),
        timeout=timeout,
        headers={"User-Agent": "UmaFansBot/1.0 (+https://umafans.run; historical race detail)"},
    )
    write_source_cache(path, body, source_url=url)
    return _decode_source(body)


def prepare_candidates(args) -> dict:
    with Path(args.events_csv).open(encoding="utf-8-sig", newline="") as handle:
        events = [row for row in csv.DictReader(handle) if row.get("status") == "finished"]
    if args.limit:
        events = events[: args.limit]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    candidates_path = output_dir / "netkeiba_detail_candidates.jsonl"
    review_path = output_dir / "netkeiba_detail_review.csv"
    manifest_path = Path(args.source_cache_manifest) if args.source_cache_manifest else None
    summary = {
        "source": "netkeiba_result",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "cache_pages": 0,
        "network_pages": 0,
        "skipped": [],
        "errors": [],
    }
    review_rows = []
    with candidates_path.open("w", encoding="utf-8") as output:
        for event in events:
            try:
                source_url = _approved_result_url(event)
                if not source_url:
                    summary["skipped"].append({"slug": event["slug"], "reason": "approved_netkeiba_result_url_missing"})
                    continue
                if manifest_path:
                    html = read_cached_source(source_url, manifest_path=manifest_path)
                    summary["cache_pages"] += 1
                else:
                    race_id = source_url.rstrip("/").rsplit("/", 1)[-1]
                    html = _download(
                        source_url,
                        source_dir / f"source_netkeiba_{race_id}.html",
                        allow_network=args.allow_network,
                        timeout=args.timeout_seconds,
                    )
                    summary["network_pages"] += 1
                runners, results, metadata = parse_netkeiba_result_page(html, source_url=source_url)
            except Exception as exc:
                summary["errors"].append({"slug": event.get("slug"), "error": str(exc)})
                if args.fail_fast:
                    raise
                continue
            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": "netkeiba",
                "source_url": source_url,
                "modules": {"runners": {"items": runners}, "results": {"items": results}},
                "metadata": metadata,
            }
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["runner_items"] += len(runners)
            summary["result_items"] += len(results)
            review_rows.append(
                {
                    "slug": event["slug"],
                    "source_url": source_url,
                    "runners": len(runners),
                    "results": len(results),
                    "winner": results[0]["horse_name"] if results else "",
                    "race_title": metadata["race_title"],
                }
            )
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["slug", "source_url", "runners", "results", "winner", "race_title"])
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate historical JRA detail candidates from netkeiba result pages.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-cache-manifest")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare_candidates(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

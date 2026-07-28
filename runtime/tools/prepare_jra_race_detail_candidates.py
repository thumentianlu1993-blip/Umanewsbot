#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from historical_race_detail_http import controlled_http_get
from race_event_request_budget import before_network_request
from race_event_source_cache import write_source_cache
from jra_legacy_replay_detail_parser import try_parse_jra_legacy_replay_detail

from bs4 import BeautifulSoup


JRA_BASE_URL = "https://www.jra.go.jp"
JRA_RESULT_LIST_URL = (
    "https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html"
)
JRA_RESULT_RE = re.compile(r"/datafile/seiseki/(?:replay/2026/\d{3}|g1/[^\"']+/result/[^\"']+2026)\.html")
WAKU_RE = re.compile(r"枠(\d+)")
STRUCTURED_DISTANCE_RE = re.compile(
    r"(?<!\d)(\d{1,2}(?:,\d{3})|\d{3,4})\s*(?:m|メートル)(?![A-Za-z])",
    re.IGNORECASE,
)


def _text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _decode_jra_html(body: bytes) -> str:
    return body.decode("cp932", errors="replace")


def _canonical_structured_distance(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    match = STRUCTURED_DISTANCE_RE.search(normalized)
    if match is None:
        return ""
    return f"{match.group(1).replace(',', '')}m"


def _structured_distance_text(soup: BeautifulSoup) -> str:
    for selector in (".raceKyoriTrack", ".cell.course"):
        for node in soup.select(selector):
            distance = _canonical_structured_distance(_text(node))
            if distance:
                return distance
    for node in soup.select("td.gray12"):
        normalized = unicodedata.normalize("NFKC", _text(node))
        if re.fullmatch(r"\d{3,4}\s*m", normalized, re.IGNORECASE):
            return _canonical_structured_distance(normalized)
    return ""


def _download(
    url: str,
    path: Path,
    *,
    allow_network: bool,
    timeout: int,
    request_context: dict | None = None,
) -> bytes:
    if path.exists():
        return path.read_bytes()
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if not isinstance(request_context, dict):
        raise RuntimeError("JRA 网络请求缺少 runner v2 受控请求上下文")
    body = controlled_http_get(
        url,
        policy=request_context.get("request_policy"),
        shard_id=request_context.get("shard_id"),
        shard_state_path=request_context.get("shard_state_path"),
        host_state_root=request_context.get("host_state_root"),
        timeout=timeout,
        headers={"User-Agent": "UmaFansBot/1.0"},
        before_request=before_network_request,
    )
    write_source_cache(path, body, source_url=url)
    return body


def _request_context_from_args(args) -> dict | None:
    if not bool(getattr(args, "allow_network", False)):
        return None
    policy_path = str(getattr(args, "request_policy", "") or "")
    shard_id = str(getattr(args, "request_shard_id", "") or "")
    shard_state = str(getattr(args, "request_state", "") or "")
    host_state_root = str(getattr(args, "host_state_root", "") or "")
    if not all((policy_path, shard_id, shard_state, host_state_root)):
        raise RuntimeError("JRA 网络模式必须提供 request policy、shard identity 与 host state")
    try:
        policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("JRA request policy 无法读取") from exc
    return {
        "request_policy": policy,
        "shard_id": shard_id,
        "shard_state_path": shard_state,
        "host_state_root": host_state_root,
    }


def _normalize_match_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"[^0-9A-Za-z\u3040-\u30ff\u3400-\u9fff]+", "", value).casefold()


def _extract_result_entries(list_html_path: Path) -> list[dict[str, str]]:
    raw = list_html_path.read_bytes()
    try:
        list_html = raw.decode("utf-8")
    except UnicodeDecodeError:
        list_html = _decode_jra_html(raw)
    soup = BeautifulSoup(list_html, "html.parser")
    entries = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if JRA_RESULT_RE.search(href):
            row = anchor.find_parent("tr")
            entries.append(
                {
                    "source_url": urljoin(JRA_BASE_URL, href),
                    "row_text": _text(row),
                }
            )
    seen = set()
    unique_entries = []
    for entry in entries:
        source_url = entry["source_url"]
        if source_url in seen:
            continue
        seen.add(source_url)
        unique_entries.append(entry)
    return unique_entries


def _match_result_links(list_html_path: Path, events: list[dict]) -> list[str]:
    entries = _extract_result_entries(list_html_path)
    matched_links = []
    for event in events:
        names = [event.get("original_name") or ""]
        names.extend((event.get("aliases") or "").split("|"))
        keys = {_normalize_match_text(name) for name in names if _normalize_match_text(name)}
        matches = [
            entry["source_url"]
            for entry in entries
            if any(key in _normalize_match_text(entry["row_text"]) for key in keys)
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"JRA 结果页匹配数量异常：slug={event.get('slug')} matches={len(matches)}"
            )
        matched_links.append(matches[0])
    return matched_links


def _source_filename(source_url: str) -> str:
    path = source_url.split("?", 1)[0].rstrip("/")
    replay_match = re.search(r"/replay/2026/(\d{3})\.html$", path)
    if replay_match:
        return f"source_jra_2026_{replay_match.group(1)}.html"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_").lower()
    return f"source_jra_{slug[-80:]}.html"


def _read_finished_events(
    csv_path: Path,
    *,
    recovery_mode: bool = False,
) -> list[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        accepted_statuses = (
            {"scheduled", "finished"}
            if recovery_mode
            else {"finished"}
        )
        return [
            row
            for row in reader
            if (row.get("status") or "").strip() in accepted_statuses
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
        return "pulled_up"
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
        "distance_text": _structured_distance_text(soup),
        "row_count": len(rows),
        "result_count": len(results),
    }
    if runners and results:
        return runners, results, metadata

    legacy = try_parse_jra_legacy_replay_detail(body, source_url=source_url)
    if legacy is not None:
        return legacy
    raise RuntimeError(f"JRA result page has no complete rows: {source_url}")


def prepare_candidates(args) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    finished_events = _read_finished_events(
        Path(args.events_csv),
        recovery_mode=bool(getattr(args, "recovery_mode", False)),
    )
    if args.limit:
        finished_events = finished_events[: args.limit]
    request_context = _request_context_from_args(args)
    source_html = Path(args.source_html)
    _download(
        JRA_RESULT_LIST_URL,
        source_html,
        allow_network=args.allow_network,
        timeout=args.timeout_seconds,
        request_context=request_context,
    )
    result_links = _match_result_links(source_html, finished_events)

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
                body = _download(
                    source_url,
                    source_path,
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    request_context=request_context,
                )
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
    parser.add_argument("--recovery-mode", action="store_true")
    parser.add_argument("--request-policy")
    parser.add_argument("--request-shard-id")
    parser.add_argument("--request-state")
    parser.add_argument("--host-state-root")
    args = parser.parse_args()
    summary = prepare_candidates(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

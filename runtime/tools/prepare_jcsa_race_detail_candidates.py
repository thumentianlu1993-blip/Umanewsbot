#!/usr/bin/env python3
"""从 JCSA（jcsa.sa）meeting-info 赛果接口生成沙特赛事逐马候选。

页面形态：/api/meeting-info/en/{yyyymmdd}/{raceNo}/Results/True 返回单场结果表片段，
表头 Place | Horse Name | Age & Sex | Weight (KG) | Rating | Time | Margin | Prize Money (USD)，
马名单元格内联 J <骑师> T <练马师> O <马主> 链接。片段不含赛名与赔率。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from race_event_request_budget import before_network_request
from race_event_safe_http import SafeHttpError, fetch_https, validate_https_url
from race_event_source_cache import write_source_cache_text


ALLOWED_HOSTS = ("jcsa.sa", "www.jcsa.sa")
PROVIDER = "jcsa"
SOURCE_NAME = "jcsa_meeting_results"
# JCSA 赛果接口片段无马场字段；沙特杯赛制固定在利雅得 King Abdulaziz Racetrack
JCSA_RACECOURSE = "King Abdulaziz Racetrack"
COUNTRY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,3})\)\s*$")
URL_RE = re.compile(r"/api/meeting-info/(?:en|ar)/(?P<date>\d{8})/(?P<race>\d+)/Results/", re.IGNORECASE)
GENERIC_NAME_TOKENS = {"and", "by", "cup", "group", "presented", "race", "stakes", "the"}


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _strip_country_suffix(value: str) -> tuple[str, str]:
    match = COUNTRY_SUFFIX_RE.search(value or "")
    if match:
        return COUNTRY_SUFFIX_RE.sub("", value).strip(), match.group(1)
    return _collapse(value), ""


def _ordinal_position(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+)(?:st|nd|rd|th)?\s*", value or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _name_tokens(value: str) -> set[str]:
    tokens = {token for token in re.split(r"[^a-z0-9]+", (value or "").lower()) if token and not token.isdigit()}
    return tokens - GENERIC_NAME_TOKENS


def _page_matches_event(event: dict, metadata: dict) -> bool:
    """守卫：JCSA 结果片段无赛名，核验日期；片段带赛名时再核名。"""
    if not metadata.get("local_date"):
        return False
    if str(event.get("local_date") or "") != str(metadata.get("local_date") or ""):
        return False
    race_title = str(metadata.get("race_title") or "")
    if race_title:
        expected = _name_tokens(str(event.get("original_name") or ""))
        actual = _name_tokens(race_title)
        return bool(expected and actual and expected <= actual)
    return True


def _url_metadata(source_url: str) -> dict:
    match = URL_RE.search(urlparse(source_url).path)
    if not match:
        raise RuntimeError(f"JCSA 来源 URL 无法识别日期与场次：{source_url}")
    raw_date = match.group("date")
    local_date = datetime.strptime(raw_date, "%Y%m%d").date().isoformat()
    return {"local_date": local_date, "race_number": str(int(match.group("race")))}


def _parse_horse_cell(cell) -> dict:
    horse_anchor = cell.find("a", href=re.compile(r"^/en/horses/"))
    if horse_anchor is None:
        return {}
    horse_name_raw = _collapse(horse_anchor.get("title") or horse_anchor.get_text(" ", strip=True))
    horse_name, country_code = _strip_country_suffix(horse_name_raw)
    jockey_anchor = cell.find("a", href=re.compile(r"^/en/jockeys/"))
    trainer_anchor = cell.find("a", href=re.compile(r"^/en/trainers/"))
    owner_anchor = cell.find("a", href=re.compile(r"^/en/owners/"))
    return {
        "horse_name": horse_name,
        "horse_name_raw": horse_name_raw,
        "country_code": country_code,
        "horse_url": horse_anchor.get("href") or "",
        "jockey_name": _collapse(jockey_anchor.get_text(" ", strip=True)) if jockey_anchor else "",
        "jockey_url": (jockey_anchor.get("href") or "") if jockey_anchor else "",
        "trainer_name": _collapse(trainer_anchor.get_text(" ", strip=True)) if trainer_anchor else "",
        "trainer_url": (trainer_anchor.get("href") or "") if trainer_anchor else "",
        "owner_name": _collapse(owner_anchor.get_text(" ", strip=True)) if owner_anchor else "",
        "owner_url": (owner_anchor.get("href") or "") if owner_anchor else "",
    }


def _parse_results_page(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    metadata = _url_metadata(source_url)
    metadata["racecourse"] = JCSA_RACECOURSE
    metadata["race_title"] = ""
    soup = BeautifulSoup(html, "lxml")
    table = None
    for candidate in soup.find_all("table"):
        head = _collapse(candidate.find("thead").get_text(" ", strip=True)) if candidate.find("thead") else ""
        if "Place" in head and "Horse Name" in head:
            table = candidate
            break
    runners: list[dict] = []
    results: list[dict] = []
    for row in table.select("tbody tr.meeting-info-horse-item") if table else []:
        tds = row.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        horse = _parse_horse_cell(tds[2])
        if not horse.get("horse_name"):
            continue
        finish_raw = _collapse(tds[0].get_text(" ", strip=True))
        finish_position = _ordinal_position(finish_raw)
        age_sex = _collapse(tds[3].get_text(" ", strip=True)) if len(tds) > 3 else ""
        weight = _collapse(tds[4].get_text(" ", strip=True)) if len(tds) > 4 else ""
        rating = _collapse(tds[5].get_text(" ", strip=True)) if len(tds) > 5 else ""
        finish_time = _collapse(tds[6].get_text(" ", strip=True)) if len(tds) > 6 else ""
        margin = _collapse(tds[7].get_text(" ", strip=True)) if len(tds) > 7 else ""
        prize = _collapse(tds[8].get_text(" ", strip=True)) if len(tds) > 8 else ""
        if margin == "-":
            margin = ""
        if finish_time == "-":
            finish_time = ""
        source_refs = {
            "primary": source_url,
            "source_language": "en",
            "source_kind": "jcsa_meeting_result",
            "horse_url": horse["horse_url"],
            "horse_name_raw": horse["horse_name_raw"],
            "country_code": horse["country_code"],
            "finish_position_raw": finish_raw,
            "owner_name": horse["owner_name"],
            "owner_url": horse["owner_url"],
            "jockey_url": horse["jockey_url"],
            "trainer_url": horse["trainer_url"],
            "age_sex": age_sex,
            "rating": rating,
            "prize_money": prize,
        }
        runner = {
            "horse_number": "",
            "barrier": "",
            "horse_name": horse["horse_name"],
            "jockey_name": horse["jockey_name"],
            "trainer_name": horse["trainer_name"],
            "carried_weight": weight,
            "odds_value": "",
            "running_status": "declared" if finish_position > 0 else "unknown",
            "source_refs": source_refs,
        }
        runners.append(runner)
        if finish_position > 0:
            results.append(
                {
                    **runner,
                    "finish_position": finish_position,
                    "official_finish_position": finish_position,
                    "finish_time": finish_time,
                    "margin": margin,
                    "is_confirmed": True,
                    "source_refs": {**source_refs, "official_finish_position": finish_position},
                }
            )
    if not runners:
        raise RuntimeError("JCSA 页面缺少实际出走")
    if not results:
        raise RuntimeError("JCSA 页面缺少正式名次")
    # JCSA 结果页不公布马号：保持表序（稳定排序），有马号时按数值排序
    for index, row in enumerate(runners):
        row["_table_order"] = index
    runners.sort(key=lambda row: (int(row["horse_number"]), 0) if row["horse_number"].isdigit() else (9999, row["_table_order"]))
    for index, row in enumerate(runners, start=1):
        row["sort_order"] = index
        row.pop("_table_order", None)
    results.sort(key=lambda row: row["finish_position"])
    metadata["winning_time"] = results[0]["finish_time"]
    metadata["row_count"] = len(runners)
    metadata["result_count"] = len(results)
    return runners, results, metadata


def _approved_result_url(event: dict) -> str:
    try:
        source_refs = json.loads(event.get("source_refs") or "{}")
    except (TypeError, json.JSONDecodeError):
        return ""
    discovery = source_refs.get("detail_discovery") or {}
    evidence = ((discovery.get("urls") or {}).get("result_url") or {})
    if evidence.get("source_provider") == PROVIDER:
        return str(evidence.get("url") or "").strip()
    for supplemental in discovery.get("approved_detail_sources") or []:
        if isinstance(supplemental, dict) and supplemental.get("source_provider") == PROVIDER:
            return str(supplemental.get("url") or "").strip()
    return ""


def _download(url: str, path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> str:
    validate_https_url(url, allowed_hosts=ALLOWED_HOSTS)
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    before_network_request(url)
    body, _response = fetch_https(
        url,
        allowed_hosts=ALLOWED_HOSTS,
        timeout=timeout,
        headers={"User-Agent": "umanewsbot/1.0 (+https://umafans.run; low-frequency race detail import)"},
    )
    html = body.decode("utf-8", errors="replace")
    write_source_cache_text(path, html, source_url=url)
    return html


def _read_events(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows.extend(row for row in csv.DictReader(handle) if row.get("status") == "finished")
    return rows


def _read_source_map(path: str) -> dict[tuple[int, str], str]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("sources") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise RuntimeError("JCSA source map must be a list or contain sources")
    mapped = {}
    for row in rows:
        key = (int(row.get("year") or 0), str(row.get("slug") or ""))
        if key in mapped:
            raise RuntimeError(f"duplicate JCSA source mapping: {key}")
        if str(row.get("source_provider") or "") != PROVIDER:
            raise RuntimeError(f"unsupported JCSA provider: {row.get('source_provider')}")
        url = str(row.get("source_url") or "")
        validate_https_url(url, allowed_hosts=ALLOWED_HOSTS)
        mapped[key] = url
    return mapped


def prepare_candidates(args) -> dict:
    events = _read_events([Path(path) for path in args.events_csv])
    if args.limit:
        events = events[: args.limit]
    source_map = _read_source_map(args.source_map_json)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    jsonl_path = output_dir / "jcsa_detail_candidates.jsonl"
    review_path = output_dir / "jcsa_detail_review.csv"
    summary = {
        "source": SOURCE_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": len(events),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "skipped": [],
        "errors": [],
    }
    review_rows = []
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for event in events:
            url = _approved_result_url(event) or source_map.get((int(event["year"]), event["slug"]), "")
            if not url:
                summary["skipped"].append({"slug": event["slug"], "reason": "missing_approved_or_mapped_url"})
                continue
            try:
                html = _download(
                    url,
                    source_dir / f"source_jcsa_{event['year']}_{event['slug']}.html",
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                )
                runners, results, metadata = _parse_results_page(html, source_url=url)
                if not _page_matches_event(event, metadata):
                    raise RuntimeError("JCSA 页面日期与目标赛事不一致")
            except Exception as exc:
                summary["errors"].append({"slug": event.get("slug"), "error": str(exc)})
                if args.fail_fast:
                    raise
                continue
            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": SOURCE_NAME,
                "source_url": url,
                "modules": {"runners": {"items": runners}, "results": {"items": results}},
                "metadata": metadata,
            }
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["runner_items"] += len(runners)
            summary["result_items"] += len(results)
            review_rows.append(
                {
                    "year": event["year"],
                    "slug": event["slug"],
                    "source_provider": PROVIDER,
                    "source_url": url,
                    "runners": len(runners),
                    "results": len(results),
                    "winner": results[0]["horse_name"],
                    "race_title": metadata.get("race_title", ""),
                }
            )
    fieldnames = ["year", "slug", "source_provider", "source_url", "runners", "results", "winner", "race_title"]
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-csv", action="append", required=True)
    parser.add_argument("--source-map-json", default="")
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

#!/usr/bin/env python3
"""从 Racing Australia 全天赛果页 / Just Horse Racing 单场赛果页生成澳洲赛事 runner/result 候选。

两个 provider 共用同一种 race-strip-fields 表结构：

- racing_australia：`Results.aspx?Key={YYYYMonDD},{STATE},{Venue}` 全天多赛页，
  每场 = `table.race-title` + 紧随的 `table.race-strip-fields`，必须用 race_number
  （参数或 source_url 的 `#race-N` / `RaceNo=N`）选定目标场；退赛马 Finish 列为空。
  超过保留期时页面只显示 "Results for this meeting are not currently available."，
  此时抛出 MeetingResultsUnavailableError（reason=retention_window_expired，供上游挂账）。
- just_horse_racing：justhorseracing.com.au 单场赛果页，同构 race-strip-fields；
  退赛马标 SCR；部分页面（如 Melbourne Cup）没有 Starting Price 列，odds_value 为空；
  并列名次（dead-heat）时多行共享同一 finish_position/official_finish_position。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from race_event_request_budget import before_network_request
from race_event_safe_http import fetch_https, validate_https_url
from race_event_source_cache import write_source_cache_text


ALLOWED_HOSTS = (
    "racingaustralia.horse",
    "www.racingaustralia.horse",
    "justhorseracing.com.au",
    "www.justhorseracing.com.au",
)
PROVIDER_SOURCE_NAMES = {
    "racing_australia": "racing_australia_results",
    "just_horse_racing": "just_horse_racing_results",
}
RESULTS_UNAVAILABLE_TEXT = "Results for this meeting are not currently available"
COUNTRY_SUFFIX_RE = re.compile(r"\s*\([A-Z]{2,3}\)\s*$")
RA_RACE_TITLE_RE = re.compile(
    r"^Race\s+(?P<number>\d+)\s*-\s*"
    r"(?:(?P<time>\d{1,2}:\d{2}\s*[AP]M)\s+)?"
    r"(?P<title>.*?)\s*(?:\((?P<distance>[\d,]+)\s*METRES\))?\s*$",
    re.IGNORECASE,
)
RA_RACE_NO_QUERY_RE = re.compile(r"[?&]raceno=(?P<number>\d+)", re.IGNORECASE)
RA_RACE_NO_FRAGMENT_RE = re.compile(r"[#&]race-?(?P<number>\d+)", re.IGNORECASE)
RA_RACE_TIME_RE = re.compile(r"\bTime:\s*(?P<time>\d+:\d{2}(?:\.\d+)?)")
JHR_IDENTITY_RE = re.compile(
    r"The\s+(?P<race>.+?)\s+was raced at\s+(?P<course>[A-Za-z][A-Za-z' \-]*?)\s+racecourse on\s+"
    r"(?P<date>[A-Za-z]+,\s*\d{1,2}\s+[A-Za-z]+\s+\d{4})"
)
STRIP_HEADER_ALIASES = {
    "finish": "finish",
    "no.": "number",
    "horse": "horse",
    "trainer": "trainer",
    "jockey": "jockey",
    "margin": "margin",
    "bar.": "barrier",
    "weight": "weight",
    "penalty": "penalty",
    "starting price": "starting_price",
}
GENERIC_NAME_TOKENS = {
    "and",
    "handicap",
    "race",
    "stake",
    "stakes",
    "the",
}


class MeetingResultsUnavailableError(RuntimeError):
    """RA 页面明确提示该会议赛果暂不可用（超过 RA 免费页面保留期）。"""

    reason = "retention_window_expired"


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _strip_country_suffix(value: str) -> str:
    return COUNTRY_SUFFIX_RE.sub("", _collapse(value)).strip()


def _numeric_sort(value: str) -> tuple[int, str]:
    match = re.search(r"\d+", value or "")
    return (int(match.group(0)) if match else 9999, value or "")


def _name_tokens(value: str) -> set[str]:
    value = (value or "").lower().replace("&", " and ")
    value = re.sub(r"\[[^]]*]|\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    tokens = {token for token in value.split() if not token.isdigit()}
    return tokens - GENERIC_NAME_TOKENS


def _course_match(expected: str, actual: str) -> bool:
    key = lambda value: re.sub(r"[^a-z0-9]+", "", (value or "").lower())
    aliases = {"thevalley": "mooneevalley"}
    expected_key = aliases.get(key(expected).replace("royal", ""), key(expected).replace("royal", ""))
    actual_key = aliases.get(key(actual).replace("royal", ""), key(actual).replace("royal", ""))
    return bool(
        expected_key
        and actual_key
        and (expected_key == actual_key or expected_key in actual_key or actual_key in expected_key)
    )


def _page_matches_event(event: dict, metadata: dict) -> bool:
    if str(event.get("local_date") or "") != str(metadata.get("local_date") or ""):
        return False
    if not _course_match(str(event.get("racecourse") or ""), str(metadata.get("racecourse") or "")):
        return False
    expected_tokens = _name_tokens(str(event.get("original_name") or ""))
    actual_tokens = _name_tokens(str(metadata.get("race_title") or ""))
    if not expected_tokens or not actual_tokens:
        return False
    if expected_tokens <= actual_tokens:
        return True
    # 官方事件名常带赞助商前缀（Lexus Melbourne Cup），页面用净名（Melbourne Cup）：
    # 页面净名至少 2 个区别性 token 且全部落入事件名时放行
    return len(actual_tokens) >= 2 and actual_tokens <= expected_tokens


def _approved_result_url(event: dict, *, provider: str) -> str:
    try:
        source_refs = json.loads(event.get("source_refs") or "{}")
    except (TypeError, json.JSONDecodeError):
        return ""
    discovery = source_refs.get("detail_discovery") or {}
    evidence = ((discovery.get("urls") or {}).get("result_url") or {})
    if evidence.get("source_provider") == provider:
        return str(evidence.get("url") or "").strip()
    for supplemental in discovery.get("approved_detail_sources") or []:
        if isinstance(supplemental, dict) and supplemental.get("source_provider") == provider:
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


def _normalize_race_number(value: str) -> str:
    match = re.search(r"\d+", str(value or ""))
    return str(int(match.group(0))) if match else ""


def _race_number_from_url(source_url: str) -> str:
    match = RA_RACE_NO_QUERY_RE.search(source_url) or RA_RACE_NO_FRAGMENT_RE.search(source_url)
    return str(int(match.group("number"))) if match else ""


def _parse_ra_meeting_header(soup: BeautifulSoup) -> dict[str, str]:
    top = soup.find("div", class_="top")
    h2 = top.find("h2") if top else None
    if h2 is None:
        raise RuntimeError("Racing Australia 页面缺少会议头（div.top h2）")
    date_node = h2.find("span", class_="race-venue-date")
    date_text = _collapse(date_node.get_text(" ", strip=True) if date_node else "")
    try:
        local_date = datetime.strptime(date_text, "%A, %d %B %Y").date()
    except ValueError as exc:
        raise RuntimeError(f"Racing Australia 会议日期无法识别：{date_text!r}") from exc
    venue_text = _collapse(h2.get_text(" ", strip=True))
    if date_text:
        venue_text = _collapse(venue_text.replace(date_text, ""))
    racecourse = venue_text.split(":", 1)[0].strip()
    if not racecourse:
        raise RuntimeError("Racing Australia 会议头缺少马场名")
    return {"racecourse": racecourse, "local_date": local_date.isoformat()}


def _column(cells: list[str], header: dict[str, int], name: str) -> str:
    index = header.get(name)
    if index is None or index >= len(cells):
        return ""
    return cells[index]


def _parse_strip_rows(
    strip,
    *,
    source_url: str,
    source_kind: str,
    race_number: str,
) -> tuple[list[dict], list[dict]]:
    header_row = strip.find("tr")
    header: dict[str, int] = {}
    if header_row is not None:
        for index, cell in enumerate(header_row.find_all(["th", "td"])):
            key = STRIP_HEADER_ALIASES.get(_collapse(cell.get_text(" ", strip=True)).lower())
            if key:
                header[key] = index
    if "finish" not in header or "horse" not in header:
        raise RuntimeError("race-strip-fields 表头无法识别（缺 Finish/Horse 列）")
    runners: list[dict] = []
    result_rows: list[tuple[int, str, dict]] = []
    rows = header_row.find_next_siblings("tr") if header_row is not None else []
    for tr in rows:
        cells = [_collapse(cell.get_text(" ", strip=True)) for cell in tr.find_all("td")]
        if not cells or not any(cells):
            continue
        finish_text = _column(cells, header, "finish")
        horse_cell = tr.find("td", class_="horse")
        horse_name_raw = _collapse(
            horse_cell.get_text(" ", strip=True) if horse_cell else _column(cells, header, "horse")
        )
        horse_name = _strip_country_suffix(horse_name_raw)
        if not horse_name:
            raise RuntimeError("race-strip-fields 数据行缺少马名")
        finish_upper = finish_text.upper()
        official_position = None
        if finish_upper in ("", "SCR", "SB"):
            # RA 退赛马 Finish 为空或 SB（闸前退出）；Just Horse Racing 标 SCR
            running_status = "scratched"
        elif finish_upper == "DQ":
            # 取消资格：完成出赛但页面不公布数字名次，不臆造 official_finish_position
            running_status = "unknown"
        else:
            match = re.match(r"^(\d+)", finish_text)
            if not match:
                raise RuntimeError(f"race-strip-fields 行 Finish 文本无法识别：{finish_text!r}")
            official_position = int(match.group(1))
            running_status = "declared"
        horse_link = horse_cell.find("a", href=True) if horse_cell else None
        source_refs = {
            "primary": source_url,
            "source_language": "en",
            "source_kind": source_kind,
            "horse_url": (horse_link["href"] if horse_link else ""),
            "horse_name_raw": horse_name_raw,
            "finish_position_raw": finish_text,
            "penalty_text": _column(cells, header, "penalty"),
            "race_number": race_number,
        }
        runner = {
            "horse_number": _column(cells, header, "number"),
            "barrier": _column(cells, header, "barrier"),
            "horse_name": horse_name,
            "jockey_name": _column(cells, header, "jockey"),
            "trainer_name": _column(cells, header, "trainer"),
            "carried_weight": _column(cells, header, "weight"),
            "odds_value": _column(cells, header, "starting_price"),
            "running_status": running_status,
            "source_refs": source_refs,
        }
        runners.append(runner)
        if official_position is not None:
            result_rows.append((official_position, _column(cells, header, "margin"), runner))
    runners.sort(key=lambda row: _numeric_sort(row["horse_number"]))
    for index, row in enumerate(runners, start=1):
        row["sort_order"] = index
    result_rows.sort(key=lambda item: (item[0], _numeric_sort(item[2]["horse_number"])))
    results = []
    for official_position, margin, runner in result_rows:
        results.append(
            {
                **runner,
                "finish_position": official_position,
                "official_finish_position": official_position,
                "finish_time": "",
                "margin": margin,
                "is_confirmed": True,
                "source_refs": {**runner["source_refs"], "official_finish_position": official_position},
            }
        )
    return runners, results


def _parse_results_page(
    html: str, *, source_url: str, race_number: str = ""
) -> tuple[list[dict], list[dict], dict]:
    """解析 RA 全天多赛页，返回 race_number 选定场次的 (runners, results, metadata)。"""
    soup = BeautifulSoup(html, "html.parser")
    if RESULTS_UNAVAILABLE_TEXT in soup.get_text(" ", strip=True):
        raise MeetingResultsUnavailableError(
            "Racing Australia 页面提示该会议赛果暂不可用（retention window 缺口）"
        )
    meeting = _parse_ra_meeting_header(soup)
    races = []
    for title_table in soup.find_all("table", class_="race-title"):
        th = title_table.find("th")
        span = th.find("span") if th else None
        headline = _collapse(span.get_text(" ", strip=True) if span else "")
        match = RA_RACE_TITLE_RE.match(headline)
        if not match:
            continue
        strip = title_table.find_next("table", class_="race-strip-fields")
        if strip is None:
            raise RuntimeError(f"Racing Australia Race {match.group('number')} 缺少 race-strip-fields 表")
        time_match = RA_RACE_TIME_RE.search(title_table.get_text(" ", strip=True))
        races.append(
            {
                "number": str(int(match.group("number"))),
                "title": _collapse(match.group("title")),
                "distance": (match.group("distance") or "").replace(",", ""),
                "race_time": time_match.group("time") if time_match else "",
                "headline": headline,
                "strip": strip,
            }
        )
    if not races:
        raise RuntimeError("Racing Australia 页面缺少 race-title/race-strip-fields 结构")
    number = _normalize_race_number(race_number) or _race_number_from_url(source_url)
    if not number:
        raise RuntimeError(
            "Racing Australia 全天赛果页必须通过 race_number 参数或 source_url 锚点指定目标场次"
        )
    selected = next((race for race in races if race["number"] == number), None)
    if selected is None:
        available = ", ".join(race["number"] for race in races)
        raise RuntimeError(f"Racing Australia 页面没有 Race {number}（可用场次：{available}）")
    runners, results = _parse_strip_rows(
        selected["strip"],
        source_url=source_url,
        source_kind="racing_australia_results",
        race_number=number,
    )
    if not runners or not results:
        raise RuntimeError("Racing Australia 页面缺少实际出走或正式名次")
    metadata = {
        **meeting,
        "race_number": number,
        "race_title": selected["title"],
        "distance_text": selected["distance"],
        "race_time": selected["race_time"],
        "page_title": selected["headline"],
        "available_race_numbers": [race["number"] for race in races],
        "source_kind": "racing_australia_results",
        "row_count": len(runners),
        "result_count": len(results),
    }
    return runners, results, metadata


def _parse_just_horse_racing_page(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    """解析 justhorseracing.com.au 单场赛果页。"""
    soup = BeautifulSoup(html, "html.parser")
    strip = soup.find("table", class_="race-strip-fields")
    if strip is None:
        raise RuntimeError("Just Horse Racing 页面缺少 race-strip-fields 赛果表")
    identity = None
    for paragraph in soup.find_all("p"):
        identity = JHR_IDENTITY_RE.search(_collapse(paragraph.get_text(" ", strip=True)))
        if identity:
            break
    if identity is None:
        raise RuntimeError("Just Horse Racing 页面缺少赛事身份句（was raced at ... racecourse on ...）")
    try:
        local_date = datetime.strptime(_collapse(identity.group("date")), "%A, %d %B %Y").date()
    except ValueError as exc:
        raise RuntimeError(f"Just Horse Racing 赛事日期无法识别：{identity.group('date')!r}") from exc
    runners, results = _parse_strip_rows(
        strip,
        source_url=source_url,
        source_kind="just_horse_racing_results",
        race_number="",
    )
    if not runners or not results:
        raise RuntimeError("Just Horse Racing 页面缺少实际出走或正式名次")
    h1 = soup.find("h1")
    metadata = {
        "racecourse": _collapse(identity.group("course")),
        "local_date": local_date.isoformat(),
        "race_title": _collapse(identity.group("race")),
        "race_number": "",
        "distance_text": "",
        "race_time": "",
        "page_title": _collapse(h1.get_text(" ", strip=True) if h1 else ""),
        "source_kind": "just_horse_racing_results",
        "row_count": len(runners),
        "result_count": len(results),
    }
    return runners, results, metadata


def _read_events(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows.extend(row for row in csv.DictReader(handle) if row.get("status") == "finished")
    return rows


def _read_source_map(path: str) -> dict[tuple[int, str], dict]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("sources") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise RuntimeError("Australia source map must be a list or contain sources")
    mapped = {}
    for row in rows:
        key = (int(row.get("year") or 0), str(row.get("slug") or ""))
        if key in mapped:
            raise RuntimeError(f"duplicate Australia source mapping: {key}")
        provider = str(row.get("source_provider") or "")
        if provider not in PROVIDER_SOURCE_NAMES:
            raise RuntimeError(f"unsupported Australia source provider: {provider}")
        url = str(row.get("source_url") or "")
        validate_https_url(url, allowed_hosts=ALLOWED_HOSTS)
        mapped[key] = {
            "provider": provider,
            "url": url,
            "race_number": str(row.get("race_number") or "").strip(),
        }
    return mapped


def prepare_candidates(args) -> dict:
    events = _read_events([Path(path) for path in args.events_csv])
    if args.limit:
        events = events[: args.limit]
    source_map = _read_source_map(args.source_map_json)
    default_provider = str(getattr(args, "source_provider", "") or "")
    if default_provider and default_provider not in PROVIDER_SOURCE_NAMES:
        raise RuntimeError(f"unsupported Australia source provider: {default_provider}")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    review_path = output_dir / "australia_detail_review.csv"
    summary = {
        "source": "australia_race_detail_candidates",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": len(events),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "skipped": [],
        "errors": [],
    }
    review_rows = []
    jsonl_handles = {}
    try:
        for event in events:
            key = (int(event["year"]), event["slug"])
            mapped = source_map.get(key)
            region = str(event.get("country_region") or "")
            if region and region != "australia":
                summary["skipped"].append({"slug": event.get("slug"), "reason": "unsupported_region"})
                continue
            provider = (mapped or {}).get("provider") or default_provider
            if not provider:
                summary["skipped"].append({"slug": event.get("slug"), "reason": "missing_provider"})
                continue
            if provider not in PROVIDER_SOURCE_NAMES:
                raise RuntimeError(f"unsupported Australia source provider: {provider}")
            url = _approved_result_url(event, provider=provider) or (mapped or {}).get("url", "")
            if not url:
                summary["skipped"].append({"slug": event.get("slug"), "reason": "missing_approved_or_mapped_url"})
                continue
            race_number = (mapped or {}).get("race_number") or str(event.get("race_number") or "").strip()
            try:
                html = _download(
                    url,
                    source_dir / f"source_{provider}_{event['year']}_{event['slug']}.html",
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                )
                if provider == "racing_australia":
                    runners, results, metadata = _parse_results_page(
                        html, source_url=url, race_number=race_number
                    )
                else:
                    runners, results, metadata = _parse_just_horse_racing_page(html, source_url=url)
                if not _page_matches_event(event, metadata):
                    raise RuntimeError("页面日期、马场或赛名与目标赛事不一致")
            except Exception as exc:
                entry = {"slug": event.get("slug"), "error": str(exc)}
                reason = getattr(exc, "reason", None)
                if reason:
                    entry["reason"] = str(reason)
                summary["errors"].append(entry)
                if args.fail_fast:
                    raise
                continue
            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": PROVIDER_SOURCE_NAMES[provider],
                "source_url": url,
                "modules": {"runners": {"items": runners}, "results": {"items": results}},
                "metadata": metadata,
            }
            if provider not in jsonl_handles:
                jsonl_handles[provider] = (output_dir / f"{provider}_detail_candidates.jsonl").open(
                    "w", encoding="utf-8"
                )
            jsonl_handles[provider].write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["runner_items"] += len(runners)
            summary["result_items"] += len(results)
            review_rows.append(
                {
                    "year": event["year"],
                    "slug": event["slug"],
                    "source_provider": provider,
                    "source_url": url,
                    "race_number": metadata.get("race_number", ""),
                    "runners": len(runners),
                    "results": len(results),
                    "winner": results[0]["horse_name"],
                    "race_title": metadata["race_title"],
                }
            )
    finally:
        for handle in jsonl_handles.values():
            handle.close()
    fieldnames = [
        "year", "slug", "source_provider", "source_url", "race_number",
        "runners", "results", "winner", "race_title",
    ]
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
    parser.add_argument("--source-provider", choices=sorted(PROVIDER_SOURCE_NAMES), default="")
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

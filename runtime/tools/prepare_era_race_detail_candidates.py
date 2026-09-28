#!/usr/bin/env python3
"""从 Emirates Racing Authority（emiratesracing.com）赛果页生成 UAE 赛事逐马候选。

页面形态：
- 整日页 /ajax/racecard-results-all?date=YYYY-MM-DD：9 个场块，每块 = h2 场头 + 结果表
- 单场页 /ajax/racecard-results?date=YYYY-MM-DD&race=N：仅结果表，无场头
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from race_event_request_budget import before_network_request
from race_event_safe_http import SafeHttpError, fetch_https, validate_https_url
from race_event_source_cache import write_source_cache_text


ALLOWED_HOSTS = ("emiratesracing.com", "www.emiratesracing.com")
PROVIDER = "era"
SOURCE_NAME = "era_racecard_results"
COUNTRY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,3})\)\s*$")
HEADING_RE = re.compile(r"^Race\s+(\d+)\s+-\s+(?P<name>.+)$")
TRACK_ICON_RE = re.compile(r"/assets/tracks/(?P<course>[a-z0-9-]+?)--(?P<distance>\d+)m")
TITLE_RE = re.compile(r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})\s+-\s+(?P<course>.+)$")
RACECOURSE_NAMES = {"meydan": "Meydan", "jebel-ali": "Jebel Ali"}
GENERIC_NAME_TOKENS = {
    "and", "by", "for", "group", "race", "sponsored", "stake", "stakes", "the",
}


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _strip_country_suffix(value: str) -> tuple[str, str]:
    match = COUNTRY_SUFFIX_RE.search(value or "")
    if match:
        return COUNTRY_SUFFIX_RE.sub("", value).strip(), match.group(1)
    return _collapse(value), ""


def _numeric_sort(value: str) -> tuple[int, str]:
    match = re.search(r"\d+", value or "")
    return (int(match.group(0)) if match else 9999, value or "")


def _name_tokens(value: str) -> set[str]:
    value = (value or "").lower().replace("&", " and ")
    value = re.sub(r"\[[^]]*]|\([^)]*\)", " ", value)
    tokens = {token for token in re.split(r"[^a-z0-9]+", value) if token and not token.isdigit()}
    return tokens - GENERIC_NAME_TOKENS


def _course_match(expected: str, actual: str) -> bool:
    key = lambda value: re.sub(r"[^a-z0-9]+", "", (value or "").lower())
    expected_key, actual_key = key(expected), key(actual)
    return bool(expected_key and actual_key and (expected_key == actual_key or expected_key in actual_key or actual_key in expected_key))


def _page_matches_event(event: dict, metadata: dict) -> bool:
    """守卫：日期 + 马场 + 赛名 token 匹配；赛名缺失时无法核验，fail closed。"""
    if str(event.get("local_date") or "") != str(metadata.get("local_date") or ""):
        return False
    if not metadata.get("local_date"):
        return False
    racecourse = str(metadata.get("racecourse") or "")
    if racecourse and not _course_match(str(event.get("racecourse") or ""), racecourse):
        return False
    expected_tokens = _name_tokens(str(event.get("original_name") or ""))
    actual_tokens = _name_tokens(str(metadata.get("race_title") or ""))
    return bool(expected_tokens and actual_tokens and expected_tokens <= actual_tokens)


def _label_value(grid, label: str) -> str:
    for item in grid.select(".racecard-table__main-grid-item"):
        strong = item.find("strong")
        if strong and _collapse(strong.get_text(" ", strip=True)).rstrip(":") == label:
            holder = strong.find_parent("div").find_next_sibling("div")
            return _collapse(holder.get_text(" ", strip=True)) if holder else ""
    return ""


def _linked_name(grid, label: str, href_part: str) -> tuple[str, str]:
    for item in grid.select(".racecard-table__main-grid-item"):
        strong = item.find("strong")
        if strong and _collapse(strong.get_text(" ", strip=True)).rstrip(":") == label:
            anchor = item.find("a", href=re.compile(re.escape(href_part)))
            if anchor is not None:
                return _collapse(anchor.get_text(" ", strip=True)), anchor.get("href") or ""
            holder = strong.find_parent("div").find_next_sibling("div")
            return (_collapse(holder.get_text(" ", strip=True)) if holder else ""), ""
    return "", ""


def _parse_runner_row(row, *, soup, source_url: str) -> dict | None:
    horse_anchor = row.select_one(".racecard-table__horse-name a")
    if horse_anchor is None:
        return None
    horse_name_raw = _collapse(horse_anchor.get_text(" ", strip=True))
    horse_name, country_code = _strip_country_suffix(horse_name_raw)
    if not horse_name:
        return None
    tds = row.find_all("td", recursive=False)
    position_td = tds[0] if tds else None
    badge = position_td.select_one(".number-badge") if position_td else None
    finish_raw = _collapse(badge.get_text(" ", strip=True) if badge else "")
    finish_match = re.fullmatch(r"\d+", finish_raw)
    finish_position = int(finish_raw) if finish_match else 0
    margin_td = row.find("td", class_=lambda c: c and "text-nowrap" in c.split())
    margin = _collapse(margin_td.get_text(" ", strip=True)) if margin_td else ""
    if margin == "-":
        margin = ""
    silks = row.select_one("a.racecard-table__silks-wrapper")
    saddle = row.select_one(".racecard-table__saddle-cloth-number")
    stall = row.select_one(".racecard-table__stall-number")
    barrier = _collapse(stall.get_text(" ", strip=True)) if stall else ""
    barrier = barrier.strip("()")
    profile = ""
    horse_cell = horse_anchor.parent
    profile_node = horse_cell.find_next_sibling("div") if horse_cell else None
    if profile_node is not None:
        profile = _collapse(profile_node.get_text(" ", strip=True))
    sire = row.select_one('.racecard-table__sire-dam [data-bs-title="Sire"]')
    dam = row.select_one('.racecard-table__sire-dam [data-bs-title="Dam"]')
    grid = row.select_one(".racecard-table__main-grid")
    jockey, jockey_url = _linked_name(grid, "Jockey", "/jockeys/") if grid else ("", "")
    trainer, trainer_url = _linked_name(grid, "Trainer", "/trainers/") if grid else ("", "")
    weight = _label_value(grid, "Weight") if grid else ""
    finish_time = _label_value(grid, "Time") if grid else ""
    rating = _label_value(grid, "Rating") if grid else ""
    odds_value = ""
    starting_price_text = _label_value(grid, "Starting price") if grid else ""
    hidden_tds = [td for td in tds if not td.get("class")]
    hidden_sp = hidden_tds[-1] if hidden_tds else None
    if hidden_sp is not None:
        odds_value = _collapse(hidden_sp.get("data-sort") or hidden_sp.get_text(" ", strip=True))
    if not odds_value:
        odds_value = starting_price_text
    comment = ""
    trigger = row.find(attrs={"data-micromodal-trigger": re.compile(r"^reader-comments-")})
    if trigger is not None:
        modal = row.find("div", id=trigger["data-micromodal-trigger"]) or soup.find(
            "div", id=trigger["data-micromodal-trigger"]
        )
        if modal is not None:
            comment_node = modal.select_one(".ms-sm-3")
            comment = _collapse(comment_node.get_text(" ", strip=True)) if comment_node else ""
    source_refs = {
        "primary": source_url,
        "source_language": "en",
        "source_kind": "era_racecard_result",
        "horse_url": horse_anchor.get("href") or "",
        "horse_name_raw": horse_name_raw,
        "country_code": country_code,
        "finish_position_raw": finish_raw,
        "owner_name": _collapse(silks.get("data-bs-title") or "") if silks else "",
        "owner_url": (silks.get("href") or "") if silks else "",
        "jockey_url": jockey_url,
        "trainer_url": trainer_url,
        "horse_profile_raw": profile,
        "sire_name": _collapse(sire.get_text(" ", strip=True)) if sire else "",
        "dam_name": _collapse(dam.get_text(" ", strip=True)) if dam else "",
        "rating": rating,
        "starting_price_raw": starting_price_text,
        "reader_comment": comment,
    }
    return {
        "horse_number": _collapse(saddle.get_text(" ", strip=True)) if saddle else "",
        "barrier": barrier,
        "horse_name": horse_name,
        "jockey_name": jockey,
        "trainer_name": trainer,
        "carried_weight": weight,
        "odds_value": odds_value,
        "running_status": "declared" if finish_position > 0 else "unknown",
        "source_refs": source_refs,
        "_finish_position": finish_position,
        "_finish_time": finish_time,
        "_margin": margin,
    }


def _block_metadata(container, *, heading_name: str, race_number: str) -> dict:
    metadata = {"race_number": race_number, "race_title": heading_name}
    if container is None:
        return metadata
    items = [
        _collapse(node.get_text(" ", strip=True))
        for node in container.select(".racecard__stats-list--primary .racecard__stats-list-item")
    ]
    metadata["race_time"] = next((item for item in items if re.fullmatch(r"\d{2}:\d{2}", item)), "")
    metadata["grade_text"] = next((item for item in items if re.fullmatch(r"Group [123]|Listed", item)), "")
    metadata["conditions"] = next((item for item in items if item.lower().startswith("for ")), "")
    metadata["discipline"] = next(
        (item for item in items if item.lower() in {"thoroughbred", "purebred arabian"}), ""
    )
    surface = next((item for item in items if item in {"DIRT", "TURF"}), "")
    metadata["surface"] = surface.lower()
    metadata["prize_text"] = next((item for item in items if item.startswith("AED")), "")
    track_icon = container.find("img", src=TRACK_ICON_RE)
    icon_match = TRACK_ICON_RE.search(track_icon["src"]) if track_icon else None
    if icon_match:
        course_key = icon_match.group("course")
        metadata["racecourse"] = RACECOURSE_NAMES.get(course_key, course_key.replace("-", " ").title())
        metadata["distance_text"] = f"{icon_match.group('distance')}m"
    return metadata


def _page_header_metadata(soup) -> dict:
    title = _collapse(soup.title.get_text(" ", strip=True) if soup.title else "")
    match = TITLE_RE.search(title)
    if not match:
        return {}
    try:
        parsed_date = datetime.strptime(
            f"{match.group('day')} {match.group('month')} {match.group('year')}", "%d %b %Y"
        ).date()
    except ValueError:
        return {}
    return {"local_date": parsed_date.isoformat(), "racecourse": _collapse(match.group("course"))}


def _parse_results_all_page(html: str, *, source_url: str, race_number: str) -> tuple[list[dict], list[dict], dict]:
    race_number = str(race_number or "").strip()
    if not race_number.isdigit() or int(race_number) < 1:
        raise RuntimeError(f"ERA 解析缺少有效场次号：{race_number or '<empty>'}")
    soup = BeautifulSoup(html, "lxml")
    date_param = (parse_qs(urlparse(source_url).query).get("date") or [""])[0]
    metadata: dict = {"local_date": date_param, "racecourse": "", "race_title": ""}
    metadata.update({key: value for key, value in _page_header_metadata(soup).items() if not metadata.get(key)})
    container = None
    table = None
    heading_name = ""
    headings = soup.find_all("h2", class_="racecard__heading")
    if headings:
        for h2 in headings:
            match = HEADING_RE.match(_collapse(h2.get_text(" ", strip=True)))
            if match and int(match.group(1)) == int(race_number):
                heading_name = _collapse(match.group("name"))
                container = h2.parent
                table_div = container.find_next_sibling("div", class_="racecard-table")
                table = table_div.find("table", class_="racecard-table__table--results") if table_div else None
                break
        else:
            raise RuntimeError(f"ERA 整日页缺少场次 Race {race_number}")
    else:
        # 单场 ajax 页：无场头，直接取唯一结果表
        table = soup.find("table", class_="racecard-table__table--results")
    metadata.update(_block_metadata(container, heading_name=heading_name, race_number=str(int(race_number))))
    runners: list[dict] = []
    results: list[dict] = []
    for row in table.select("tbody tr.racecard-table__tr") if table else []:
        parsed = _parse_runner_row(row, soup=soup, source_url=source_url)
        if parsed is None:
            continue
        finish_position = parsed.pop("_finish_position")
        finish_time = parsed.pop("_finish_time")
        margin = parsed.pop("_margin")
        runners.append(parsed)
        if finish_position > 0:
            results.append(
                {
                    **parsed,
                    "finish_position": finish_position,
                    "official_finish_position": finish_position,
                    "finish_time": finish_time,
                    "margin": margin,
                    "is_confirmed": True,
                    "source_refs": {**parsed["source_refs"], "official_finish_position": finish_position},
                }
            )
    runners.sort(key=lambda row: _numeric_sort(row["horse_number"]))
    for index, row in enumerate(runners, start=1):
        row["sort_order"] = index
    results.sort(key=lambda row: (row["finish_position"], _numeric_sort(row["horse_number"])))
    # 展示名次唯一化（并列保留在 official_finish_position），满足 (event, finish_position) 唯一约束
    for display_position, row in enumerate(results, start=1):
        row["finish_position"] = display_position
    if not runners:
        raise RuntimeError(f"ERA 页面缺少实际出走（race={race_number}）")
    if not results:
        raise RuntimeError(f"ERA 页面缺少正式名次（race={race_number}）")
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


def _race_number_for_event(event: dict, url: str) -> str:
    race_param = (parse_qs(urlparse(url).query).get("race") or [""])[0]
    if race_param.isdigit():
        return race_param
    try:
        source_refs = json.loads(event.get("source_refs") or "{}")
    except (TypeError, json.JSONDecodeError):
        source_refs = {}
    race_number = str((source_refs.get("detail_discovery") or {}).get("race_number") or "")
    if race_number.isdigit():
        return race_number
    raise RuntimeError(f"ERA 事件缺少 race_number（slug={event.get('slug')}）")


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
        raise RuntimeError("ERA source map must be a list or contain sources")
    mapped = {}
    for row in rows:
        key = (int(row.get("year") or 0), str(row.get("slug") or ""))
        if key in mapped:
            raise RuntimeError(f"duplicate ERA source mapping: {key}")
        if str(row.get("source_provider") or "") != PROVIDER:
            raise RuntimeError(f"unsupported ERA provider: {row.get('source_provider')}")
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
    jsonl_path = output_dir / "era_detail_candidates.jsonl"
    review_path = output_dir / "era_detail_review.csv"
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
                race_number = _race_number_for_event(event, url)
                html = _download(
                    url,
                    source_dir / f"source_era_{event['year']}_{event['slug']}.html",
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                )
                runners, results, metadata = _parse_results_all_page(html, source_url=url, race_number=race_number)
                if not _page_matches_event(event, metadata):
                    raise RuntimeError("ERA 页面日期、场地或赛事名与目标不一致")
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

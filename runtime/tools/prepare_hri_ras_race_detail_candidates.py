#!/usr/bin/env python3
"""从 HRI 官方赛果页（www.hri-ras.ie/results/race-result/）生成爱尔兰赛事出走/名次候选。

页面结构（2025-06-29 Curragh Irish Derby 样本）：
- 头部：p.race-course 场地、p.date 日期、div.race-details 内 h2 赛名（含级别）、
  Race Time / Off Time / 途程 / 出走数 / 奖金段；
- 每匹出走马一个 div.panel-heading.panel-race-card（名次、负磅距、马号、马名、档位、
  R: 骑师、T: 练马师、负磅 9-2），其后 div.panel-collapse 详情（年龄/性别、血统、
  马主、Tote Win/Place、走位评论）。
HRI 页面无 SP 赔率：odds_value 取 Tote Win 数值，并在 source_refs 标注 odds_kind=tote。
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
from race_event_safe_http import fetch_https, validate_https_url
from race_event_source_cache import write_source_cache_text


ALLOWED_HOSTS = ("www.hri-ras.ie",)
PROVIDER = "hri_ras"
SOURCE_NAME = "hri_ras_result"
REGION_PROVIDERS = {"ireland": PROVIDER}

COUNTRY_SUFFIX_RE = re.compile(r"\s*\([A-Z]{2,3}\)\s*$")
ORDINAL_RE = re.compile(r"^\s*(\d+)(?:st|nd|rd|th)?\s*$", re.IGNORECASE)
WEIGHT_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
DISTANCE_RE = re.compile(r"^(?=\d)(?:\d+m\s*)?(?:\d+(?:\s?\d+/\d+)?f)?\+?$")
RAN_RE = re.compile(r"^(\d+)\s*ran$", re.IGNORECASE)
GENERIC_NAME_TOKENS = {
    "and",
    "chase",
    "grade",
    "group",
    "handicap",
    "hurdle",
    "novices",
    "race",
    "showcase",
    "stake",
    "stakes",
    "the",
}


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _strip_country_suffix(value: str) -> str:
    return COUNTRY_SUFFIX_RE.sub("", _collapse(value)).strip()


def _ordinal_position(value: str) -> int:
    match = ORDINAL_RE.fullmatch(value or "")
    return int(match.group(1)) if match else 0


def _numeric_sort(value: str) -> tuple[int, str]:
    match = re.search(r"\d+", value or "")
    return (int(match.group(0)) if match else 9999, value or "")


def _text_after_prefix(node, prefix: str) -> str:
    text = _collapse(node.get_text(" ", strip=True) if node else "")
    return _collapse(re.sub(rf"^{re.escape(prefix)}\s*", "", text))


def _parse_header_date(value: str) -> str:
    # 形如 "Sunday, 29th Jun 2025"
    text = _collapse(value)
    text = re.sub(r"^[A-Za-z]+,\s*", "", text)
    text = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    return datetime.strptime(text, "%d %b %Y").date().isoformat()


def _parse_race_header(soup: BeautifulSoup, *, source_url: str) -> dict:
    course_node = soup.select_one("p.race-course")
    date_node = soup.select_one("p.date")
    title_node = soup.select_one("div.race-details h2")
    if course_node is None or date_node is None or title_node is None:
        raise RuntimeError("HRI 赛果页缺少场地、日期或赛名头部")
    metadata = {
        "racecourse": _collapse(course_node.get_text(" ", strip=True)),
        "local_date": _parse_header_date(date_node.get_text(" ", strip=True)),
        "race_title": _collapse(title_node.get_text(" ", strip=True)),
        "race_time": "",
        "off_time": "",
        "distance_text": "",
        "ran_count": None,
        "going": "",
        "purse_text": "",
        "registered_name": "",
        "venue_code": "",
    }
    if not metadata["racecourse"] or not metadata["race_title"]:
        raise RuntimeError("HRI 赛果页头部字段为空")
    details = soup.select_one("div.race-details")
    if details is not None:
        for li in details.select("li"):
            text = _collapse(li.get_text(" ", strip=True))
            if text.startswith("Race Time:"):
                metadata["race_time"] = _text_after_prefix(li, "Race Time:")
            elif text.startswith("Off Time:"):
                metadata["off_time"] = _text_after_prefix(li, "Off Time:")
            else:
                strong = li.find("strong")
                strong_text = _collapse(strong.get_text(" ", strip=True)) if strong else ""
                ran = RAN_RE.match(strong_text)
                if ran:
                    metadata["ran_count"] = int(ran.group(1))
                elif strong_text and DISTANCE_RE.match(strong_text):
                    metadata["distance_text"] = strong_text
        purse = details.find("p")
        if purse is not None:
            metadata["purse_text"] = _collapse(purse.get_text(" ", strip=True))
            registered = REGISTERED_NAME_RE.search(metadata["purse_text"])
            metadata["registered_name"] = _collapse(registered.group(1)) if registered else ""
    for strong in soup.find_all("strong"):
        if strong.get_text(" ", strip=True).upper().startswith("GOING"):
            em = strong.find("em")
            metadata["going"] = _collapse(em.get_text(" ", strip=True)) if em else ""
            break
    query = parse_qs(urlparse(source_url).query)
    url_date = (query.get("date") or [""])[0]
    if url_date:
        if url_date != metadata["local_date"]:
            raise RuntimeError(
                f"HRI 页面日期 {metadata['local_date']} 与 URL date={url_date} 不一致"
            )
    metadata["venue_code"] = (query.get("venue") or [""])[0]
    return metadata


def _find_detail_panel(soup: BeautifulSoup, heading) -> object:
    heading_id = heading.get("id") or ""
    match = re.fullmatch(r"headRaceCard(\d+)", heading_id)
    if match:
        return soup.find("div", id=f"detailRaceCard{match.group(1)}")
    return heading.find_next_sibling("div", class_="panel-collapse")


def _parse_heading(heading) -> dict:
    place_node = heading.select_one("span.place")
    place_b = place_node.find("b") if place_node else None
    finish_raw = _collapse(place_b.get_text(" ", strip=True)) if place_b else ""
    place_full = _collapse(place_node.get_text(" ", strip=True)) if place_node else ""
    margin = ""
    if finish_raw and place_full.startswith(finish_raw):
        margin = _collapse(place_full[len(finish_raw):].lstrip("-– "))
    horse_number = ""
    horse_name_raw = ""
    barrier = ""
    jockey_name = ""
    trainer_name = ""
    carried_weight = ""
    for li in heading.select("ul.race-card-ext li"):
        text = _collapse(li.get_text(" ", strip=True))
        b = li.find("b")
        b_text = _collapse(b.get_text(" ", strip=True)) if b else ""
        number_match = re.match(r"^(\d+)\.\s*(.*)$", b_text)
        strong = li.find("strong")
        if number_match and b.find("span") is not None:
            horse_number = number_match.group(1)
            horse_name_raw = _collapse(b.find("span").get_text(" ", strip=True))
        elif strong is not None and "Drawn" in strong.get_text():
            barrier = _text_after_prefix(li, "Drawn:")
        elif b_text == "R:":
            span = li.find("span")
            jockey_name = _collapse(span.get_text(" ", strip=True)) if span else _text_after_prefix(li, "R:")
        elif b_text.startswith("T:"):
            trainer_name = _text_after_prefix(li, "T:")
        elif b is not None and WEIGHT_RE.match(b_text):
            carried_weight = WEIGHT_RE.sub(r"\1-\2", b_text)
    return {
        "finish_raw": finish_raw,
        "margin": margin,
        "horse_number": horse_number,
        "horse_name_raw": horse_name_raw,
        "barrier": barrier,
        "jockey_name": jockey_name,
        "trainer_name": trainer_name,
        "carried_weight": carried_weight,
    }


def _parse_detail_panel(detail) -> dict:
    info = {
        "age_text": "",
        "color_sex_raw": [],
        "breeding_text": "",
        "rating_text": "",
        "horse_url": "",
        "owner_name": "",
        "tote_win_raw": "",
        "tote_place_raw": "",
        "comment_text": "",
    }
    if detail is None:
        return info
    first_ul = detail.select_one("ul.list-inline")
    if first_ul is not None:
        for li in first_ul.find_all("li", recursive=False):
            strong = li.find("strong")
            if strong is None:
                breeding = _collapse(li.get_text(" ", strip=True))
                if breeding:
                    info["breeding_text"] = breeding
                continue
            strong_text = _collapse(strong.get_text(" ", strip=True))
            age_match = re.fullmatch(r"(\d+)\s*YO", strong_text, flags=re.IGNORECASE)
            if age_match:
                info["age_text"] = age_match.group(1)
            elif re.fullmatch(r"[A-Z]", strong_text):
                info["color_sex_raw"].append(strong_text)
    for b in detail.find_all("b"):
        label = _collapse(b.get_text(" ", strip=True))
        li = b.find_parent("li")
        if label == "Horse:" and li is not None:
            anchor = li.find("a", href=True)
            info["horse_url"] = anchor["href"] if anchor else ""
        elif label == "Owner:" and li is not None:
            anchor = li.find("a")
            info["owner_name"] = _collapse(anchor.get_text(" ", strip=True)) if anchor else _text_after_prefix(li, "Owner:")
    for strong in detail.find_all("strong"):
        label = _collapse(strong.get_text(" ", strip=True))
        li = strong.find_parent("li")
        if label == "Rating:" and li is not None:
            info["rating_text"] = _text_after_prefix(li, "Rating:")
        elif label == "Win:" and li is not None:
            info["tote_win_raw"] = _text_after_prefix(li, "Win:")
        elif label == "Place:" and li is not None:
            info["tote_place_raw"] = _text_after_prefix(li, "Place:")
    comment_b = detail.find("b", string=re.compile(r"^\s*Comment:"))
    if comment_b is not None:
        paragraph = comment_b.find_parent("p")
        if paragraph is not None:
            info["comment_text"] = _text_after_prefix(paragraph, "Comment:")
    return info


def _tote_value(raw: str) -> str:
    match = re.search(r"([\d.]+)", raw or "")
    return match.group(1) if match else ""


NON_FINISH_STATUS = {
    "n.r.": "non_runner",
    "nr": "non_runner",
    "p.u.": "pulled_up",
    "pu": "pulled_up",
    "fell": "fell",
    "f": "fell",
    "u.r.": "unseated_rider",
    "ur": "unseated_rider",
    "b.d.": "did_not_finish",
    "bd": "did_not_finish",
    "s.u.": "did_not_finish",
    "su": "did_not_finish",
    "r.o.": "did_not_finish",
    "ro": "did_not_finish",
    "r.f.": "refused",
    "d.s.q.": "disqualified",
    "dq": "disqualified",
}
REGISTERED_NAME_RE = re.compile(r"\(\s*Registered as\s+(?:the\s+)?([^)]+?)\s*\)", re.IGNORECASE)


def _running_status(finish_raw: str) -> str:
    if _ordinal_position(finish_raw) > 0:
        return "finished"
    marker = re.sub(r"\s+", "", (finish_raw or "").lower())
    status = NON_FINISH_STATUS.get(marker) or NON_FINISH_STATUS.get(marker.rstrip("."))
    if status is None:
        raise RuntimeError(f"HRI 页面出现未登记的非名次标记：{finish_raw!r}")
    return status


def _parse_result_page(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    soup = BeautifulSoup(html, "lxml")
    metadata = _parse_race_header(soup, source_url=source_url)
    runners = []
    result_rows = []
    for heading in soup.select("div.panel-heading.panel-race-card"):
        parsed = _parse_heading(heading)
        if not parsed["horse_number"] or not parsed["horse_name_raw"]:
            continue
        detail = _parse_detail_panel(_find_detail_panel(soup, heading))
        horse_name = _strip_country_suffix(parsed["horse_name_raw"])
        if not horse_name:
            continue
        finish_position = _ordinal_position(parsed["finish_raw"])
        running_status = _running_status(parsed["finish_raw"])
        source_refs = {
            "primary": source_url,
            "source_language": "en",
            "source_kind": SOURCE_NAME,
            "horse_url": detail["horse_url"],
            "horse_name_raw": parsed["horse_name_raw"],
            "finish_position_raw": parsed["finish_raw"],
            "margin_raw": parsed["margin"],
            "odds_kind": "tote",
            "tote_win_raw": detail["tote_win_raw"],
            "tote_place_raw": detail["tote_place_raw"],
            "age_text": detail["age_text"],
            "color_sex_raw": detail["color_sex_raw"],
            "breeding_text": detail["breeding_text"],
            "rating_text": detail["rating_text"],
            "owner_name": detail["owner_name"],
            "comment_text": detail["comment_text"],
        }
        base = {
            "horse_number": parsed["horse_number"],
            "barrier": parsed["barrier"],
            "horse_name": horse_name,
            "jockey_name": parsed["jockey_name"],
            "trainer_name": parsed["trainer_name"],
            "carried_weight": parsed["carried_weight"],
            "odds_value": _tote_value(detail["tote_win_raw"]),
            "running_status": running_status,
            "source_refs": source_refs,
        }
        runners.append(base)
        if finish_position > 0:
            result_rows.append(
                {
                    **base,
                    "finish_position": finish_position,
                    "finish_time": "",
                    "margin": parsed["margin"],
                    "is_confirmed": True,
                    "source_refs": {**source_refs, "official_finish_position": finish_position},
                }
            )
    if not runners:
        raise RuntimeError("HRI 赛果页没有解析到出走马面板")
    if not result_rows:
        raise RuntimeError("HRI 赛果页没有解析到正式名次")
    runners.sort(key=lambda row: _numeric_sort(row["horse_number"]))
    for index, row in enumerate(runners, start=1):
        row["sort_order"] = index
    results = sorted(result_rows, key=lambda row: (row["finish_position"], _numeric_sort(row["horse_number"])))
    for display_position, row in enumerate(results, start=1):
        official_position = row["finish_position"]
        row["finish_position"] = display_position
        row["official_finish_position"] = official_position
    metadata.update({"row_count": len(runners), "result_count": len(results)})
    if metadata.get("ran_count") is not None and metadata["ran_count"] != len(result_rows):
        raise RuntimeError(
            f"HRI 页面标注 {metadata['ran_count']} 匹完赛，实际解析名次 {len(result_rows)} 匹"
        )
    return runners, results, metadata


def _name_tokens(value: str) -> set[str]:
    value = (value or "").lower().replace("&", " and ")
    value = re.sub(r"\[[^]]*]|\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    tokens = {token for token in value.split() if not token.isdigit()}
    return tokens - GENERIC_NAME_TOKENS


def _course_match(expected: str, actual: str) -> bool:
    key = lambda value: re.sub(r"[^a-z0-9]+", "", (value or "").lower())
    expected_key = key(expected)
    actual_key = key(actual)
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
    if not expected_tokens:
        return False
    candidates = [str(metadata.get("race_title") or "")]
    registered_name = str(metadata.get("registered_name") or "")
    if registered_name:
        candidates.append(registered_name)
    return any(expected_tokens <= _name_tokens(candidate) for candidate in candidates if candidate)


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
        raise RuntimeError("HRI source map must be a list or contain sources")
    mapped = {}
    for row in rows:
        key = (int(row.get("year") or 0), str(row.get("slug") or ""))
        if key in mapped:
            raise RuntimeError(f"duplicate HRI source mapping: {key}")
        provider = str(row.get("source_provider") or "")
        if provider != PROVIDER:
            raise RuntimeError(f"unsupported HRI provider: {provider}")
        url = str(row.get("source_url") or "")
        validate_https_url(url, allowed_hosts=ALLOWED_HOSTS)
        mapped[key] = {"provider": provider, "url": url}
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
    jsonl_path = output_dir / "hri_ras_detail_candidates.jsonl"
    review_path = output_dir / "hri_ras_detail_review.csv"
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
            key = (int(event["year"]), event["slug"])
            mapped = source_map.get(key)
            provider = (mapped or {}).get("provider") or REGION_PROVIDERS.get(event.get("country_region") or "")
            if not provider:
                summary["skipped"].append({"slug": event["slug"], "reason": "unsupported_region"})
                continue
            url = _approved_result_url(event, provider=provider) or (mapped or {}).get("url", "")
            if not url:
                summary["skipped"].append({"slug": event["slug"], "reason": "missing_approved_or_mapped_url"})
                continue
            try:
                html = _download(
                    url,
                    source_dir / f"source_hri_ras_{event['year']}_{event['slug']}.html",
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                )
                runners, results, metadata = _parse_result_page(html, source_url=url)
                if not _page_matches_event(event, metadata):
                    raise RuntimeError("HRI 页面日期、场地或赛事名与目标不一致")
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
                    "source_provider": provider,
                    "source_url": url,
                    "runners": len(runners),
                    "results": len(results),
                    "horse_number_1": next((row["horse_name"] for row in runners if row["horse_number"] == "1"), ""),
                    "winner": results[0]["horse_name"],
                    "race_title": metadata["race_title"],
                }
            )
    fieldnames = [
        "year", "slug", "source_provider", "source_url", "runners", "results",
        "horse_number_1", "winner", "race_title",
    ]
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Ireland historical runner and result candidates from HRI.")
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

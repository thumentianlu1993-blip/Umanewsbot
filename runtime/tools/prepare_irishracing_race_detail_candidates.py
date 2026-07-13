#!/usr/bin/env python3
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


ALLOWED_HOSTS = ("irishracing.com",)
PROVIDER_SOURCE_NAMES = {
    "uk_irishracing": "irishracing_uk",
    "france_irishracing": "irishracing_france",
}
REGION_PROVIDERS = {
    "united_kingdom": "uk_irishracing",
    "france": "france_irishracing",
}
COUNTRY_SUFFIX_RE = re.compile(r"\s*\([A-Z]{2,3}\)\s*$")
TITLE_RE = re.compile(
    r"Race Result\s+(?P<course>.*?),\s+[A-Za-z]+,\s+"
    r"(?P<day>\d+)(?:st|nd|rd|th)?\s+(?P<month>[A-Za-z]+),\s+"
    r"(?P<year>\d{4}),\s+(?P<title>.*)$",
    re.IGNORECASE,
)
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
    if "Information Not Available" in html:
        raise RuntimeError("IrishRacing 页面没有可用的逐马赛果")
    write_source_cache_text(path, html, source_url=url)
    return html


def _parse_title(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title = _collapse(soup.title.get_text(" ", strip=True) if soup.title else "")
    match = TITLE_RE.search(title)
    if not match:
        raise RuntimeError("IrishRacing 页面标题无法识别")
    day = int(match.group("day"))
    parsed_date = datetime.strptime(
        f"{day} {match.group('month')} {match.group('year')}", "%d %b %Y"
    ).date()
    race_title = re.split(r"\s+of\s+(?:\u00a3|\u20ac|&pound;|&euro;)", match.group("title"), maxsplit=1)[0]
    race_title = re.split(r"\s+\d+-y-o\b", race_title, maxsplit=1)[0]
    return {
        "racecourse": _collapse(match.group("course")),
        "local_date": parsed_date.isoformat(),
        "race_title": _collapse(race_title),
        "page_title": title,
    }


def _name_tokens(value: str) -> set[str]:
    value = (value or "").lower().replace("&", " and ")
    value = re.sub(r"\[[^]]*]|\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    aliases = {"s": "stake", "stp": "chase", "novice": "novices", "hdle": "hurdle"}
    tokens = {aliases.get(token, token) for token in value.split() if not token.isdigit()}
    return tokens - GENERIC_NAME_TOKENS


def _course_match(expected: str, actual: str) -> bool:
    key = lambda value: re.sub(r"[^a-z0-9]+", "", (value or "").lower())
    expected_key = key(expected).replace("royal", "")
    actual_key = key(actual).replace("royal", "")
    aliases = {"parislongchamp": "longchamp", "saintcloud": "saintcloud"}
    expected_key = aliases.get(expected_key, expected_key)
    actual_key = aliases.get(actual_key, actual_key)
    return bool(expected_key and actual_key and (expected_key == actual_key or expected_key in actual_key or actual_key in expected_key))


def _page_matches_event(event: dict, metadata: dict) -> bool:
    if str(event.get("local_date") or "") != str(metadata.get("local_date") or ""):
        return False
    if not _course_match(str(event.get("racecourse") or ""), str(metadata.get("racecourse") or "")):
        return False
    expected_tokens = _name_tokens(str(event.get("original_name") or ""))
    actual_tokens = _name_tokens(str(metadata.get("race_title") or ""))
    return bool(expected_tokens and expected_tokens <= actual_tokens)


def _ordinal_position(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+)(?:st|nd|rd|th)?\s*", value or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _horse_number(node) -> str:
    race_links = node.select_one(".racelinks[sn]")
    return _collapse(race_links.get("sn", "") if race_links else "")


def _numeric_sort(value: str) -> tuple[int, str]:
    match = re.search(r"\d+", value or "")
    return (int(match.group(0)) if match else 9999, value or "")


def _parse_result_page(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    soup = BeautifulSoup(html, "lxml")
    metadata = _parse_title(html)
    runners = []
    result_rows = []
    for line in soup.select(".runner-line"):
        horse_anchor = line.select_one(".runner a[href^='/horse/']")
        if horse_anchor is None:
            continue
        horse_name_raw = _collapse(horse_anchor.get_text(" ", strip=True))
        horse_name = _strip_country_suffix(horse_name_raw)
        if not horse_name:
            continue
        finish_raw = _collapse((line.select_one(".sn") or line).get_text(" ", strip=True))
        finish_position = _ordinal_position(finish_raw)
        margin = _collapse(line.select_one(".extdist").get_text(" ", strip=True) if line.select_one(".extdist") else "")
        runner_node = line.select_one(".runner")
        runner_text = _collapse(runner_node.get_text(" ", strip=True) if runner_node else "")
        profile = ""
        strong_nodes = runner_node.find_all("strong", recursive=False) if runner_node else []
        if strong_nodes:
            profile = _collapse(strong_nodes[0].get_text(" ", strip=True))
        weight_match = re.search(r"(\d+-\d+)\s*$", profile)
        draw_match = re.search(r"\(Drawn\s+([^)]*)\)", runner_text, flags=re.IGNORECASE)
        odds_match = re.search(r"\bSP\s+([^\s<]+)", runner_text, flags=re.IGNORECASE)
        horse_number = _horse_number(line)
        jockey_node = line.select_one(".jockey")
        trainer_node = line.select_one(".trainer")
        source_refs = {
            "primary": source_url,
            "source_language": "en",
            "source_kind": "irishracing_historical_result",
            "horse_url": horse_anchor.get("href") or "",
            "horse_name_raw": horse_name_raw,
            "finish_position_raw": finish_raw,
        }
        base = {
            "horse_number": horse_number,
            "barrier": _collapse(draw_match.group(1) if draw_match else ""),
            "horse_name": horse_name,
            "jockey_name": _collapse(jockey_node.get_text(" ", strip=True) if jockey_node else ""),
            "trainer_name": _collapse(trainer_node.get_text(" ", strip=True) if trainer_node else ""),
            "carried_weight": weight_match.group(1) if weight_match else "",
            "odds_value": _collapse(odds_match.group(1) if odds_match else ""),
            "running_status": "declared",
            "source_refs": source_refs,
        }
        runners.append(base)
        if finish_position > 0:
            result_rows.append(
                {
                    **base,
                    "finish_position": finish_position,
                    "finish_time": "",
                    "margin": margin,
                    "is_confirmed": True,
                    "source_refs": {**source_refs, "official_finish_position": finish_position},
                }
            )
    runners.sort(key=lambda row: _numeric_sort(row["horse_number"]))
    for index, row in enumerate(runners, start=1):
        row["sort_order"] = index
    results = sorted(result_rows, key=lambda row: (row["finish_position"], _numeric_sort(row["horse_number"])))
    for display_position, row in enumerate(results, start=1):
        official_position = row["finish_position"]
        row["finish_position"] = display_position
        row["official_finish_position"] = official_position
    metadata.update({"row_count": len(runners), "result_count": len(results)})
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
        raise RuntimeError("IrishRacing source map must be a list or contain sources")
    mapped = {}
    for row in rows:
        key = (int(row.get("year") or 0), str(row.get("slug") or ""))
        if key in mapped:
            raise RuntimeError(f"duplicate IrishRacing source mapping: {key}")
        provider = str(row.get("source_provider") or "")
        if provider not in PROVIDER_SOURCE_NAMES:
            raise RuntimeError(f"unsupported IrishRacing provider: {provider}")
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
    jsonl_path = output_dir / "irishracing_detail_candidates.jsonl"
    review_path = output_dir / "irishracing_detail_review.csv"
    summary = {
        "source": "irishracing_historical_result",
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
            expected_provider = REGION_PROVIDERS.get(event.get("country_region") or "")
            if provider != expected_provider:
                raise RuntimeError(
                    f"IrishRacing provider region mismatch for {key}: {provider} != {expected_provider}"
                )
            url = _approved_result_url(event, provider=provider) or (mapped or {}).get("url", "")
            if not url:
                summary["skipped"].append({"slug": event["slug"], "reason": "missing_approved_or_mapped_url"})
                continue
            try:
                html = _download(
                    url,
                    source_dir / f"source_irishracing_{event['year']}_{event['slug']}.html",
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                )
                runners, results, metadata = _parse_result_page(html, source_url=url)
                if not _page_matches_event(event, metadata):
                    raise RuntimeError("IrishRacing 页面日期、场地或赛事名与目标不一致")
                if not runners or not results:
                    raise RuntimeError("IrishRacing 页面缺少实际出走或正式名次")
            except Exception as exc:
                summary["errors"].append({"slug": event.get("slug"), "error": str(exc)})
                if args.fail_fast:
                    raise
                continue
            source_name = PROVIDER_SOURCE_NAMES[provider]
            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": source_name,
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
    parser = argparse.ArgumentParser(description="Generate UK/France historical runner and result candidates from IrishRacing.")
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

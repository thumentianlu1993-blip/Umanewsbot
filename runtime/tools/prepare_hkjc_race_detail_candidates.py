#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from race_event_request_budget import before_network_request

from bs4 import BeautifulSoup

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover - local fallback for environments without OpenCC
    OpenCC = None


COUNTRY_SUFFIX_RE = re.compile(r"\s*[\(\（][A-Z]{2,3}[\)\）]\s*$")
HKJC_HORSE_CODE_RE = re.compile(r"\s*[\(\（][A-Z]\d{3}[\)\）]\s*$")
RACE_NO_RE = re.compile(r"第\s*(\d+)\s*場")
REPLAY_NO_RE = re.compile(r"[?&]no=(\d+)")
FINISH_POSITION_RE = re.compile(r"^(\d+)")


def _text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _converter():
    if OpenCC is None:
        return None
    return OpenCC("t2s")


def _to_simplified(value: str, converter) -> str:
    value = value.strip()
    if not value:
        return ""
    if converter is None:
        return value
    return converter.convert(value)


def _strip_country_suffix(value: str) -> str:
    value = HKJC_HORSE_CODE_RE.sub("", value).strip()
    return COUNTRY_SUFFIX_RE.sub("", value).strip()


def _normalize_title(value: str) -> str:
    value = value.replace("（", "(").replace("）", ")")
    value = value.replace("「", '"').replace("」", '"')
    value = re.sub(r"\s+", "", value)
    return value


def _download(url: str, path: Path, *, allow_network: bool, timeout: int) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    request = Request(
        url,
        headers={
            "User-Agent": "UmaFansBot/1.0",
            "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
        },
    )
    before_network_request(url)
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
    text = body.decode("utf-8", errors="replace")
    path.write_text(text, encoding="utf-8")
    return text


def _source_filename(url: str) -> str:
    racecourse = ""
    racedate = ""
    race_no = ""
    racecourse_match = re.search(r"[?&]Racecourse=([^&]+)", url)
    racedate_match = re.search(r"[?&]racedate=([^&]+)", url)
    race_no_match = re.search(r"[?&]RaceNo=([^&]+)", url)
    if racecourse_match:
        racecourse = racecourse_match.group(1)
    if racedate_match:
        racedate = racedate_match.group(1).replace("%2F", "/").replace("/", "-")
    if race_no_match:
        race_no = race_no_match.group(1)
    if racecourse and racedate and race_no:
        return f"source_hkjc_localresults_{racedate}_{racecourse}_{race_no}.html"
    if racecourse and racedate:
        return f"source_hkjc_results_{racedate}_{racecourse}.html"
    key = re.sub(r"[^A-Za-z0-9]+", "_", url).strip("_").lower()
    return f"source_hkjc_results_{key[-100:]}.html"


def _read_events(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _extract_race_title(block) -> str:
    text = _text(block)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.split("全方位賽事重溫", 1)[0].strip()
    text = RACE_NO_RE.sub("", text, count=1).strip()
    return text


def _extract_race_no(block) -> str:
    match = RACE_NO_RE.search(_text(block))
    if match:
        return match.group(1)
    for link in block.find_all("a", href=True):
        replay_match = REPLAY_NO_RE.search(link["href"])
        if replay_match:
            return str(int(replay_match.group(1)))
    return ""


def _parse_finish(value: str) -> tuple[int | None, str]:
    value = value.strip()
    match = FINISH_POSITION_RE.match(value)
    if not match:
        return None, ""
    position = int(match.group(1))
    suffix = value[match.end() :].strip()
    return position, suffix


def _runner_status_from_finish_text(value: str) -> str:
    if value.strip().upper() == "WV":
        return "withdrawn"
    if any(token in value for token in ("退出", "退賽", "取消")):
        return "withdrawn"
    if "除外" in value:
        return "scratched"
    if "失格" in value or "未完成" in value:
        return "unknown"
    return "declared"


def _parse_race_block(block, *, source_url: str, converter) -> dict:
    table = block.select_one("table.result")
    if table is None:
        raise RuntimeError("HKJC race block missing result table")
    race_no = _extract_race_no(block)
    race_title_hant = _extract_race_title(block)
    rows: list[dict] = []
    for index, tr in enumerate(table.select("tr")[1:], start=1):
        cells = [_text(cell) for cell in tr.find_all(["td", "th"], recursive=False)]
        if len(cells) < 7:
            continue
        horse_name_hant = _strip_country_suffix(cells[2])
        if not horse_name_hant:
            continue
        official_position, finish_suffix_hant = _parse_finish(cells[0])
        source_refs = {
            "primary": source_url,
            "source_language": "zh-hant",
            "source_kind": "hkjc_results_all",
            "hkjc_race_no": race_no,
            "hkjc_race_title": race_title_hant,
            "hkjc_finish_position_text": cells[0],
            "horse_name_hant": horse_name_hant,
            "jockey_name_hant": cells[3],
            "trainer_name_hant": cells[4],
        }
        row = {
            "sort_order": index,
            "finish_position_text": cells[0],
            "official_finish_position": official_position,
            "horse_number": cells[1],
            "horse_name": _to_simplified(horse_name_hant, converter),
            "jockey_name": _to_simplified(cells[3], converter),
            "trainer_name": _to_simplified(cells[4], converter),
            "carried_weight": cells[5],
            "barrier": cells[6],
            "finish_time": "",
            "margin": _to_simplified(finish_suffix_hant, converter),
            "running_status": _runner_status_from_finish_text(cells[0]),
            "source_refs": source_refs,
        }
        rows.append(row)

    runners = []
    result_rows = []
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
                "running_status": row["running_status"],
                "source_refs": row["source_refs"],
            }
        )
        if row["official_finish_position"] is not None:
            result_rows.append(row)

    results = []
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
                "running_status": row["running_status"],
                "is_confirmed": True,
                "source_refs": {
                    **row["source_refs"],
                    "official_finish_position": row["official_finish_position"],
                },
            }
        )
    return {
        "race_no": race_no,
        "race_title_hant": race_title_hant,
        "race_title_key": _normalize_title(race_title_hant),
        "runners": runners,
        "results": results,
    }


def _localresults_url(result_source: str, race_no: str) -> str:
    parsed = urlparse(result_source)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["RaceNo"] = [str(int(race_no))]
    new_query = urlencode({key: values[-1] for key, values in query.items()})
    return urlunparse((parsed.scheme, parsed.netloc, "/zh-hk/local/information/localresults", "", new_query, ""))


def _parse_local_result_page(html: str, *, source_url: str, race_no: str, race_title_hant: str, converter) -> tuple[list[dict], list[dict], dict]:
    soup = BeautifulSoup(html, "html.parser")
    result_table = None
    for table in soup.find_all("table"):
        headers = [_text(cell) for cell in table.select("tr:first-child th, tr:first-child td")]
        if "名次" in headers and "馬號" in headers and "馬名" in headers and "完成 時間" in headers:
            result_table = table
            break
    if result_table is None:
        raise RuntimeError(f"HKJC 单场赛果页没有找到完整成绩表：{source_url}")

    rows: list[dict] = []
    for index, tr in enumerate(result_table.select("tr")[1:], start=1):
        cells = [_text(cell) for cell in tr.find_all(["td", "th"], recursive=False)]
        if len(cells) < 12:
            continue
        horse_name_hant = _strip_country_suffix(cells[2])
        if not horse_name_hant:
            continue
        official_position, finish_suffix_hant = _parse_finish(cells[0])
        margin_hant = cells[8]
        if finish_suffix_hant and not margin_hant:
            margin_hant = finish_suffix_hant
        source_refs = {
            "primary": source_url,
            "source_language": "zh-hant",
            "source_kind": "hkjc_local_results",
            "hkjc_race_no": race_no,
            "hkjc_race_title": race_title_hant,
            "hkjc_finish_position_text": cells[0],
            "horse_name_hant": horse_name_hant,
            "jockey_name_hant": cells[3],
            "trainer_name_hant": cells[4],
            "body_weight": cells[6],
            "running_positions": cells[9],
        }
        row = {
            "sort_order": index,
            "finish_position_text": cells[0],
            "official_finish_position": official_position,
            "horse_number": cells[1],
            "horse_name": _to_simplified(horse_name_hant, converter),
            "jockey_name": _to_simplified(cells[3], converter),
            "trainer_name": _to_simplified(cells[4], converter),
            "carried_weight": cells[5],
            "barrier": cells[7],
            "margin": _to_simplified(margin_hant, converter),
            "finish_time": cells[10],
            "odds_value": cells[11],
            "running_status": _runner_status_from_finish_text(cells[0]),
            "source_refs": source_refs,
        }
        rows.append(row)

    runners = []
    result_rows = []
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
                "odds_value": row["odds_value"],
                "running_status": row["running_status"],
                "source_refs": row["source_refs"],
            }
        )
        if row["official_finish_position"] is not None:
            result_rows.append(row)

    results = []
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
                "running_status": row["running_status"],
                "is_confirmed": True,
                "source_refs": {
                    **row["source_refs"],
                    "official_finish_position": row["official_finish_position"],
                },
            }
        )
    return runners, results, {"row_count": len(runners), "result_count": len(results)}


def _parse_results_all_page(html: str, *, source_url: str, converter) -> dict[str, dict]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.select("div.race_result div.f_fs13.margin_top15")
    races: dict[str, dict] = {}
    for block in blocks:
        if block.select_one("table.result") is None:
            continue
        parsed = _parse_race_block(block, source_url=source_url, converter=converter)
        if not parsed["runners"]:
            continue
        races[parsed["race_title_key"]] = parsed
    if not races:
        raise RuntimeError(f"HKJC 赛果页没有解析到任何比赛：{source_url}")
    return races


def prepare_candidates(args) -> dict:
    events = [event for event in _read_events(Path(args.events_csv)) if event.get("status") == "finished"]
    if args.limit:
        events = events[: args.limit]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    jsonl_path = output_dir / "hkjc_detail_candidates_2026.jsonl"
    review_csv_path = output_dir / "hkjc_detail_review_2026.csv"
    converter = _converter()

    summary = {
        "source": "hkjc_results_all_zh_hk",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "source_pages": 0,
        "skipped": [],
        "errors": [],
    }
    page_cache: dict[str, dict[str, dict]] = {}
    review_rows = []

    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for event in events:
            try:
                source_refs = json.loads(event.get("source_refs") or "{}")
                result_source = source_refs.get("result_source") or ""
                result_title = source_refs.get("result_title") or ""
                if not result_source or not result_title:
                    summary["skipped"].append({"slug": event["slug"], "reason": "missing_result_source_or_title"})
                    continue
                if result_source not in page_cache:
                    html = _download(
                        result_source,
                        source_dir / _source_filename(result_source),
                        allow_network=args.allow_network,
                        timeout=args.timeout_seconds,
                    )
                    page_cache[result_source] = _parse_results_all_page(html, source_url=result_source, converter=converter)
                    summary["source_pages"] += 1
                title_key = _normalize_title(result_title)
                parsed = page_cache[result_source].get(title_key)
                if parsed is None:
                    available_titles = [race["race_title_hant"] for race in page_cache[result_source].values()]
                    summary["errors"].append(
                        {
                            "slug": event["slug"],
                            "result_source": result_source,
                            "result_title": result_title,
                            "reason": "result_title_not_found",
                            "available_titles": available_titles,
                        }
                    )
                    if args.fail_fast:
                        raise RuntimeError(f"HKJC result title not found: {event['slug']} {result_title}")
                    continue
                local_url = _localresults_url(result_source, parsed["race_no"])
                local_html = _download(
                    local_url,
                    source_dir / _source_filename(local_url),
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                )
                runners, results, local_metadata = _parse_local_result_page(
                    local_html,
                    source_url=local_url,
                    race_no=parsed["race_no"],
                    race_title_hant=parsed["race_title_hant"],
                    converter=converter,
                )
                if not runners:
                    summary["skipped"].append({"slug": event["slug"], "reason": "no_runner_rows", "result_source": result_source})
                    continue
            except Exception as exc:
                summary["errors"].append({"slug": event.get("slug"), "error": str(exc)})
                if args.fail_fast:
                    raise
                continue

            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": "hkjc_results_all_zh_hk",
                "source_url": local_url,
                "modules": {
                    "runners": {"items": runners},
                    "results": {"items": results},
                },
                "metadata": {
                    "race_no": parsed["race_no"],
                    "race_title_hant": parsed["race_title_hant"],
                    "result_title": result_title,
                    "row_count": local_metadata["row_count"],
                    "result_count": local_metadata["result_count"],
                },
            }
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["runner_items"] += len(runners)
            summary["result_items"] += len(results)
            review_rows.append(
                {
                    "slug": event["slug"],
                    "original_name": event["original_name"],
                    "chinese_name": event.get("chinese_name", ""),
                    "source_url": local_url,
                    "race_no": parsed["race_no"],
                    "runners": len(runners),
                    "results": len(results),
                    "winner": results[0]["horse_name"] if results else "",
                    "winner_jockey": results[0]["jockey_name"] if results else "",
                    "race_title_hant": parsed["race_title_hant"],
                }
            )

    with review_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "slug",
            "original_name",
            "chinese_name",
            "source_url",
            "race_no",
            "runners",
            "results",
            "winner",
            "winner_jockey",
            "race_title_hant",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HKJC 2026 runner/result candidate JSONL from official zh-HK results pages.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare_candidates(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

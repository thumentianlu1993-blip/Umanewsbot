#!/usr/bin/env python3
"""Deutscher Galopp 赛果详情页 -> 历史赛事 runners/results 候选。

页面结构（www.deutscher-galopp.de/gr/renntage/rennen.php?...）：
- 结果表：页面中表头为 `Pl. | Name | Nr. | Box | Abstand | Gewinn | Besitzer | Trainer | Reiter | Gew. | Quote`
  的 table.display.dataTable；表尾单行 `Quoten zu 1 €: ... ZEIT DES RENNENS: ... STARTER: n NICHTSTARTER: ...`
- 出赛表：表头为 `Nr. | Name | Box | Alter | Besitzer | Trainer | Reiter | Gew. | Quote` 的
  dataTableSortable；退赛马 Quote 列为 `NS`

runners = 出赛表全部报名马（NS 马 running_status="non_runner"）；
results = 结果表有名次的行（缺 Pl. 的未完赛行进 runners 不进 results）。
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


ALLOWED_HOSTS = ("www.deutscher-galopp.de",)
PROVIDER = "deutscher_galopp"
SOURCE_NAME = "deutscher_galopp_result"
REGION_PROVIDERS = {"germany": PROVIDER}

COUNTRY_SUFFIX_RE = re.compile(r"\s*\([A-Z]{2,3}\)")
# 出赛表马名尾部的性别/状态角色后缀（表尾 NICHTSTARTER 不带这些后缀）
ROLE_SUFFIX_RE = re.compile(r"\s+(?:O|H|St|Sb|Skl|Bl|N|Hl|W)\.$")
TITLE_RE = re.compile(
    r"^(?P<race_title>.+),\s+(?P<racecourse>[^,]+?)\s+"
    r"(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})\s+-\s+Deutscher\s+Galopp\s*$"
)
RACE_TIME_RE = re.compile(r"ZEIT DES RENNENS:\s*([0-9:,]+)")
START_TIME_RE = re.compile(r"STARTZEIT:\s*([0-9:]+)")
STARTERS_RE = re.compile(r"STARTER:\s*(\d+)")
NON_STARTERS_RE = re.compile(r"NICHTSTARTER:\s*(.+?)\s*$")

# 守卫模糊匹配时忽略的德/英通用词
GENERIC_NAME_TOKENS = {
    "allianz", "am", "an", "auf", "aus", "bei", "cup", "das", "de", "dem",
    "den", "der", "des", "die", "ein", "eine", "einer", "fuer", "fur",
    "gross", "grosser", "gruppe", "im", "international", "mit", "preis",
    "rennen", "stutenrennen", "und", "von", "vom", "zu", "zum", "zur",
}
_UMLAUTS = {"ä": "a", "ö": "o", "ü": "u", "ß": "ss"}


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


def _strip_country_suffix(value: str) -> str:
    return _collapse(COUNTRY_SUFFIX_RE.sub("", value or ""))


def _normalize_horse_name(value: str) -> str:
    return _collapse(ROLE_SUFFIX_RE.sub("", _strip_country_suffix(value)))


def _decimal_de(value: str) -> str:
    """德国小数逗号 -> 小数点：'60,0 kg' -> '60.0'，'2,9' -> '2.9'。"""
    text = _collapse(value)
    text = re.sub(r"\s*kg\s*$", "", text, flags=re.IGNORECASE)
    text = text.replace(".", "").replace(",", ".") if re.search(r"\d\.\d{3}", text) else text.replace(",", ".")
    return text


def _numeric_sort(value: str) -> tuple[int, str]:
    match = re.search(r"\d+", value or "")
    return (int(match.group(0)) if match else 9999, value or "")


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


def _parse_title(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title = _collapse(soup.title.get_text(" ", strip=True) if soup.title else "")
    match = TITLE_RE.match(title)
    if not match:
        raise RuntimeError("Deutscher Galopp 页面标题无法识别")
    return {
        "racecourse": _collapse(match.group("racecourse")),
        "local_date": f"{match.group('year')}-{match.group('month')}-{match.group('day')}",
        "race_title": _collapse(match.group("race_title")),
        "page_title": title,
    }


def _find_table(soup, *, first_header: str, required_headers: set[str]):
    for table in soup.find_all("table"):
        headers = {_collapse(th.get_text(" ", strip=True)) for th in table.find_all("th")}
        header_list = [_collapse(th.get_text(" ", strip=True)) for th in table.find_all("th")]
        if header_list and header_list[0] == first_header and required_headers <= headers:
            return table
    return None


def _row_cells(tr) -> list[str]:
    return [_collapse(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]


def _horse_url(tr) -> str:
    anchor = tr.find("a", href=re.compile(r"^/gr/pferd/"))
    return anchor.get("href") or "" if anchor else ""


def _parse_footer(text: str) -> dict:
    """结果表尾行：Quoten... ZEIT DES RENNENS: 2:29,02 STARTZEIT: 15:25 STARTER: 6 NICHTSTARTER: a, b."""
    collapsed = _collapse(text)
    info = {"race_time": "", "start_time": "", "starters": "", "non_starter_names": []}
    time_match = RACE_TIME_RE.search(collapsed)
    if time_match:
        info["race_time"] = time_match.group(1)
    start_match = START_TIME_RE.search(collapsed)
    if start_match:
        info["start_time"] = start_match.group(1)
    starters_match = STARTERS_RE.search(collapsed)
    if starters_match:
        info["starters"] = starters_match.group(1)
    non_starters_match = NON_STARTERS_RE.search(collapsed)
    if non_starters_match:
        raw = non_starters_match.group(1).rstrip(".")
        if raw and raw.lower() not in {"keine", "keiner"}:
            info["non_starter_names"] = [_collapse(name) for name in raw.split(",") if _collapse(name)]
    return info


def _parse_result_page(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    soup = BeautifulSoup(html, "lxml")
    metadata = _parse_title(html)
    result_table = _find_table(soup, first_header="Pl.", required_headers={"Abstand", "Quote", "Reiter"})
    entry_table = _find_table(soup, first_header="Nr.", required_headers={"Alter", "Quote", "Reiter"})
    if result_table is None or entry_table is None:
        raise RuntimeError("Deutscher Galopp 页面缺少结果表或出赛表")

    footer_info = {"race_time": "", "start_time": "", "starters": "", "non_starter_names": []}
    runners: dict[str, dict] = {}
    result_rows = []
    did_not_finish_numbers = set()

    # 出赛表 -> runners（NS 马 non_runner）
    entry_row_count = 0
    for tr in entry_table.find_all("tr"):
        cells = _row_cells(tr)
        if not cells or cells[0] == "Nr.":
            continue
        if len(cells) == 1:  # 表尾汇总行（如 '6 Starter - 2 Nichtstarter (Nr. 5,7)'）
            continue
        if len(cells) != 9:
            raise RuntimeError(f"出赛表行列数异常：{cells!r}")
        number, name_raw, box, age, owner, trainer, jockey, weight, odds = cells
        if not number.isdigit():
            continue
        entry_row_count += 1
        horse_name = _normalize_horse_name(name_raw)
        if not horse_name:
            raise RuntimeError(f"出赛表行缺少马名：{cells!r}")
        is_non_runner = odds.upper() == "NS"
        runners[number] = {
            "horse_number": number,
            "barrier": box,
            "horse_name": horse_name,
            "jockey_name": jockey,
            "trainer_name": trainer,
            "carried_weight": _decimal_de(weight),
            "odds_value": "" if is_non_runner else _decimal_de(odds),
            "running_status": "non_runner" if is_non_runner else "declared",
            "sort_order": 0,
            "source_refs": {
                "primary": source_url,
                "source_language": "de",
                "source_kind": "deutscher_galopp_result",
                "horse_url": _horse_url(tr),
                "horse_name_raw": name_raw,
                "odds_raw": odds,
                "weight_raw": weight,
                "age_text": age,
                "owner_raw": owner,
            },
        }
    if entry_row_count == 0:
        raise RuntimeError("Deutscher Galopp 出赛表没有任何报名马行")

    # 结果表 -> results（有名次）；缺 Pl. 的行视为未完赛，只更新 runner 状态
    for tr in result_table.find_all("tr"):
        cells = _row_cells(tr)
        if not cells or cells[0] == "Pl.":
            continue
        if len(cells) == 1:  # 表尾行
            footer_info = _parse_footer(cells[0])
            continue
        if len(cells) != 11:
            raise RuntimeError(f"结果表行列数异常：{cells!r}")
        place, name_raw, number, box, margin, prize, owner, trainer, jockey, weight, odds = cells
        horse_name = _normalize_horse_name(name_raw)
        if not horse_name:
            raise RuntimeError(f"结果表行缺少马名：{cells!r}")
        position_match = re.fullmatch(r"(\d+)\.", place)
        if not position_match:
            if number in runners:
                runners[number]["running_status"] = "did_not_finish"
                did_not_finish_numbers.add(number)
            continue
        finish_position = int(position_match.group(1))
        base = runners.get(number)
        if base is None:
            base = {
                "horse_number": number,
                "barrier": box,
                "horse_name": horse_name,
                "jockey_name": jockey,
                "trainer_name": trainer,
                "carried_weight": _decimal_de(weight),
                "odds_value": _decimal_de(odds),
                "running_status": "declared",
                "sort_order": 0,
                "source_refs": {
                    "primary": source_url,
                    "source_language": "de",
                    "source_kind": "deutscher_galopp_result",
                    "horse_url": _horse_url(tr),
                    "horse_name_raw": name_raw,
                    "odds_raw": odds,
                    "weight_raw": weight,
                    "age_text": "",
                    "owner_raw": owner,
                },
            }
            runners[number] = base
        result_rows.append(
            {
                **base,
                "finish_position": finish_position,
                "official_finish_position": finish_position,
                "finish_time": "",
                "margin": margin,
                "is_confirmed": True,
                "source_refs": {**base["source_refs"], "official_finish_position": finish_position},
            }
        )

    if not runners:
        raise RuntimeError("Deutscher Galopp 页面缺少实际出走名单")
    if not result_rows:
        raise RuntimeError("Deutscher Galopp 页面缺少正式名次")

    # 完整性自校验：表尾 STARTER / NICHTSTARTER 与解析结果一致（fail closed）
    starters_declared = footer_info["starters"]
    if starters_declared:
        started = len(result_rows) + len(did_not_finish_numbers)
        if int(starters_declared) != started:
            raise RuntimeError(f"出走头数不一致：表尾 STARTER={starters_declared}，解析={started}")
    if footer_info["non_starter_names"]:
        parsed_non_runners = {
            row["horse_name"] for row in runners.values() if row["running_status"] == "non_runner"
        }
        footer_names = {_normalize_horse_name(name) for name in footer_info["non_starter_names"]}
        if footer_names != parsed_non_runners:
            raise RuntimeError(
                f"退赛马不一致：表尾 NICHTSTARTER={sorted(footer_names)}，解析={sorted(parsed_non_runners)}"
            )

    ordered_runners = sorted(runners.values(), key=lambda row: _numeric_sort(row["horse_number"]))
    for index, row in enumerate(ordered_runners, start=1):
        row["sort_order"] = index
    result_rows.sort(key=lambda row: (row["finish_position"], _numeric_sort(row["horse_number"])))
    # 展示名次唯一化（并列保留在 official_finish_position），满足 (event, finish_position) 唯一约束
    for display_position, row in enumerate(result_rows, start=1):
        row["finish_position"] = display_position
    metadata.update(
        {
            "row_count": len(ordered_runners),
            "result_count": len(result_rows),
            "race_time": footer_info["race_time"],
            "start_time": footer_info["start_time"],
            "starters": footer_info["starters"],
            "non_starter_names": footer_info["non_starter_names"],
        }
    )
    return ordered_runners, result_rows, metadata


def _name_tokens(value: str) -> set[str]:
    value = (value or "").lower()
    for src, dst in _UMLAUTS.items():
        value = value.replace(src, dst)
    value = re.sub(r"\[[^]]*]|\([^)]*\)", " ", value)
    value = re.sub(r"\bv\d+/\d+\b", " ", value)
    tokens = set()
    for token in re.split(r"[^a-z0-9]+", value):
        if not token or token.isdigit():
            continue
        if token.endswith(".") or re.fullmatch(r"\d+\.", token):
            continue
        token = token.rstrip(".")
        # ICS 缩写与官方全称的别名（T.v.Zastrow ≡ T. von Zastrow；别名先于通用词过滤，
        # 使两侧同归通用词集合）
        token = {"v": "von"}.get(token, token)
        if token in GENERIC_NAME_TOKENS:
            continue
        tokens.add(token)
    tokens.discard("")
    return tokens


def _course_match(expected: str, actual: str) -> bool:
    def key(value: str) -> str:
        value = (value or "").lower()
        for src, dst in _UMLAUTS.items():
            value = value.replace(src, dst)
        return re.sub(r"[^a-z0-9]+", "", value)

    expected_key, actual_key = key(expected), key(actual)
    aliases = {"hoppegarten": "berlinhoppegarten"}
    expected_key = aliases.get(expected_key, expected_key)
    actual_key = aliases.get(actual_key, actual_key)
    return bool(
        expected_key and actual_key
        and (expected_key == actual_key or expected_key in actual_key or actual_key in expected_key)
    )


def _page_matches_event(event: dict, metadata: dict) -> bool:
    if str(event.get("local_date") or "") != str(metadata.get("local_date") or ""):
        return False
    if not _course_match(str(event.get("racecourse") or ""), str(metadata.get("racecourse") or "")):
        return False
    expected_tokens = _name_tokens(str(event.get("original_name") or ""))
    actual_tokens = _name_tokens(str(metadata.get("race_title") or ""))
    return bool(expected_tokens and expected_tokens <= actual_tokens)


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
        raise RuntimeError("Deutscher Galopp source map 必须是列表或包含 sources 字段")
    mapped = {}
    for row in rows:
        key = (int(row.get("year") or 0), str(row.get("slug") or ""))
        if key in mapped:
            raise RuntimeError(f"duplicate Deutscher Galopp source mapping: {key}")
        provider = str(row.get("source_provider") or "")
        if provider != PROVIDER:
            raise RuntimeError(f"unsupported Deutscher Galopp provider: {provider}")
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
    jsonl_path = output_dir / "deutscher_galopp_detail_candidates.jsonl"
    review_path = output_dir / "deutscher_galopp_detail_review.csv"
    summary = {
        "source": "deutscher_galopp_result",
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
            if (event.get("country_region") or "") != "germany":
                summary["skipped"].append({"slug": event["slug"], "reason": "unsupported_region"})
                continue
            mapped = source_map.get(key)
            url = _approved_result_url(event) or (mapped or {}).get("url", "")
            if not url:
                summary["skipped"].append({"slug": event["slug"], "reason": "missing_approved_or_mapped_url"})
                continue
            try:
                html = _download(
                    url,
                    source_dir / f"source_deutscher_galopp_{event['year']}_{event['slug']}.html",
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                )
                runners, results, metadata = _parse_result_page(html, source_url=url)
                if not _page_matches_event(event, metadata):
                    raise RuntimeError("Deutscher Galopp 页面日期、场地或赛事名与目标不一致")
                if not runners or not results:
                    raise RuntimeError("Deutscher Galopp 页面缺少实际出走或正式名次")
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
    parser = argparse.ArgumentParser(description="Generate Germany historical runner and result candidates from Deutscher Galopp.")
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

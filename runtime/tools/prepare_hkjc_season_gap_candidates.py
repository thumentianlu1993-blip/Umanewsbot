#!/usr/bin/env python3
"""香港 2025/26 马季前半段（9-12 月）缺口赛事的 HKJC 官方详情候选生成器。

输入 ICS/生产对账确认的 pending 目标清单（含期望日期与匹配用繁中标题），
从 HKJC 官方 resultsall 日汇总页定位场次 RaceNo，再抓 localresults 单场完整赛果，
产出详情候选 JSONL（模块为 {"items": [...], "is_complete": true} 的导入器契约）、
目标日期更新 CSV 与人工复核 CSV；`bind_candidates` 在取得生产 target_sha256/
inventory_artifact_sha256 后生成可交给 `import_historical_race_event_candidates` 的最终 JSONL。

纪律：复用 `prepare_hkjc_race_detail_candidates` 的解析器与限速/HTTPS 白名单；
缓存缺失且未显式允许网络时 fail closed；标题不匹配、等级后缀不一致、页面为空
均只记录不伪造；证据页保留 SHA-256，实抓时记录重定向后的 final_url。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from prepare_hkjc_race_detail_candidates import (  # noqa: E402
    _converter,
    _localresults_url,
    _normalize_title,
    _parse_local_result_page,
    _parse_results_all_page,
    _source_filename,
)
from race_event_request_budget import before_network_request  # noqa: E402
from race_event_safe_http import fetch_https, validate_https_url  # noqa: E402
from race_event_source_cache import write_source_cache_text  # noqa: E402

RESULTS_ALL_URL = (
    "https://racing.hkjc.com/zh-hk/local/information/resultsall"
    "?racedate={racedate}&Racecourse={racecourse}"
)
SOURCE_NAME = "hkjc_results_all_zh_hk"
TARGET_UPDATE_FIELDS = (
    "target_id",
    "original_name",
    "local_date",
    "racecourse",
    "race_no",
    "race_title_hant",
    "distance_text",
    "surface",
    "grade_hint",
    "source_urls",
    "page_sha256",
)
REVIEW_FIELDS = (
    "target_id",
    "original_name",
    "status",
    "reason",
    "match_title",
    "race_no",
    "runners",
    "results",
)

GRADE_HINT = {"一": "G1", "二": "G2", "三": "G3"}
GRADE_SEGMENT_RE = re.compile(r"^([一二三])級賽$")
DISTANCE_SEGMENT_RE = re.compile(r"^\d+米$")
SURFACE_SEGMENTS = {"草地": "turf", "泥地": "dirt", "全天候": "synthetic"}
TRACK_SEGMENT_RE = re.compile(r'^"[^"]*"\s*賽道$')
CLASS_SEGMENT_RE = re.compile(r"^第?[一二三四五]班$")
RATING_BAND_SEGMENT_RE = re.compile(r"^\(\d+-\d+\)$")
HANDICAP_SUFFIX_RE = re.compile(r"\s*(?:[（(]讓賽[）)]|[（(]H\)|（让赛）|\(让赛\))\s*$")
HKJC_HOSTS = ("hkjc.com",)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_targets(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"target_id", "original_name", "normalized_grade", "local_date", "racecourse"}
    for index, row in enumerate(rows, start=2):
        missing = [field for field in required if not str(row.get(field) or "").strip()]
        if missing:
            raise ValueError(f"目标 CSV 第 {index} 行缺少字段：{missing}")
    return rows


def _results_all_url(local_date: str, racecourse_code: str) -> str:
    return RESULTS_ALL_URL.format(
        racedate=local_date.replace("-", "%2F"),
        racecourse=racecourse_code,
    )


def _racecourse_code(value: str) -> str:
    normalized = re.sub(r"\s+", "", (value or "").casefold())
    if normalized in {"shatin", "沙田"}:
        return "ST"
    if normalized in {"happyvalley", "跑马地", "跑馬地"}:
        return "HV"
    raise ValueError(f"未知 HKJC 马场代码：{value}")


def _clean_day_title(title_hant: str) -> dict:
    """剥离日汇总页标题前缀元数据（等级/距离/场地/赛道/班次/评分段）与队尾让赛标记。"""
    grade_hint = ""
    distance = ""
    surface = ""
    segments = [segment.strip() for segment in (title_hant or "").split(" - ")]
    idx = 0
    while idx < len(segments):
        segment = segments[idx]
        grade_match = GRADE_SEGMENT_RE.match(segment)
        if grade_match:
            grade_hint = GRADE_HINT.get(grade_match.group(1), "")
            idx += 1
            continue
        if DISTANCE_SEGMENT_RE.fullmatch(segment):
            distance = segment
            idx += 1
            continue
        if segment in SURFACE_SEGMENTS:
            surface = SURFACE_SEGMENTS[segment]
            idx += 1
            continue
        if (
            TRACK_SEGMENT_RE.fullmatch(segment)
            or CLASS_SEGMENT_RE.fullmatch(segment)
            or RATING_BAND_SEGMENT_RE.fullmatch(segment)
        ):
            idx += 1
            continue
        break
    cleaned = " - ".join(segments[idx:]).strip() or (title_hant or "").strip()
    cleaned = HANDICAP_SUFFIX_RE.sub("", cleaned).strip() or cleaned
    return {
        "title": cleaned,
        "grade_hint": grade_hint,
        "distance_text": distance,
        "surface": surface,
    }


def _match_race(day_races: dict[str, dict], target: dict) -> tuple[dict | None, str]:
    """按净标题匹配当日赛事；返回 (parsed, reason)。

    匹配键顺序确定：先 match_title_hant 后 original_name；精确优先，唯一后缀次之。
    页面标题带等级前缀且与目标等级不一致时拒绝（grade_mismatch）。
    """
    wanted_grade = (target.get("normalized_grade") or "").strip().upper()
    for race in day_races.values():
        meta = _clean_day_title(race["race_title_hant"])
        race["race_title_clean"] = meta["title"]
        race["race_title_key_clean"] = _normalize_title(meta["title"])
        race["grade_hint"] = meta["grade_hint"]
        race["distance_text"] = meta["distance_text"]
        race["surface"] = meta["surface"]

    wanted_keys = []
    for key in (target.get("match_title_hant"), target.get("original_name")):
        normalized = _normalize_title(key or "")
        if normalized and normalized not in wanted_keys:
            wanted_keys.append(normalized)

    matched: dict | None = None
    for key in wanted_keys:
        hits = [race for race in day_races.values() if race["race_title_key_clean"] == key]
        if len(hits) > 1:
            return None, "race_title_ambiguous"
        if hits:
            matched = hits[0]
            break
    if matched is None:
        for key in wanted_keys:
            hits = [
                race
                for race in day_races.values()
                if race["race_title_key_clean"].endswith(key)
            ]
            if len(hits) > 1:
                return None, "race_title_ambiguous"
            if hits:
                matched = hits[0]
                break
    if matched is None:
        return None, "race_title_not_matched"
    if wanted_grade and matched.get("grade_hint") and matched["grade_hint"] != wanted_grade:
        return None, "grade_mismatch"
    return matched, ""


def _fetch_text(url: str, path: Path, *, allow_network: bool, timeout: int) -> tuple[str, str]:
    """返回 (文本, final_url)。缓存命中时 final_url 为空（不重新验证重定向）。"""
    validate_https_url(url, allowed_hosts=HKJC_HOSTS)
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace"), ""
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{path}")
    before_network_request(url)
    body, response = fetch_https(
        url,
        allowed_hosts=HKJC_HOSTS,
        timeout=timeout,
        headers={
            "User-Agent": "UmaFansBot/1.0",
            "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
        },
    )
    text = body.decode("utf-8", errors="replace")
    write_source_cache_text(path, text, source_url=url)
    return text, str(response.get("final_url") or url)


def prepare_gap_candidates(args) -> dict:
    targets = _read_targets(Path(args.targets_csv))
    if args.limit:
        targets = targets[: args.limit]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    converter = _converter()

    summary = {
        "source": SOURCE_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "targets": len(targets),
        "events_prepared": 0,
        "runner_items": 0,
        "result_items": 0,
        "source_pages": 0,
        "errors": [],
    }
    jsonl_path = output_dir / "hkjc_gap_detail_candidates.jsonl"
    updates_path = output_dir / "target_updates.csv"
    review_path = output_dir / "hkjc_gap_review.csv"

    day_page_cache: dict[str, tuple[dict[str, dict], str, str]] = {}
    candidate_rows: list[dict] = []
    update_rows: list[dict] = []
    review_rows: list[dict] = []

    def record_error(target: dict, reason: str, detail: str = "", available: list[str] | None = None) -> None:
        summary["errors"].append(
            {
                "target_id": str(target.get("target_id") or ""),
                "original_name": target.get("original_name", ""),
                "reason": reason,
                "detail": detail[:300],
                "available_titles": available or [],
            }
        )
        review_rows.append(
            {
                "target_id": str(target.get("target_id") or ""),
                "original_name": target.get("original_name", ""),
                "status": "failed",
                "reason": reason,
                "match_title": "",
                "race_no": "",
                "runners": 0,
                "results": 0,
            }
        )

    for target in targets:
        target_id = str(target["target_id"]).strip()
        try:
            course_code = _racecourse_code(target["racecourse"])
            day_url = _results_all_url(target["local_date"], course_code)
            if day_url not in day_page_cache:
                try:
                    html, day_final_url = _fetch_text(
                        day_url,
                        source_dir / _source_filename(day_url),
                        allow_network=args.allow_network,
                        timeout=args.timeout_seconds,
                    )
                except Exception as exc:
                    raise RuntimeError(f"source_fetch_failed: {exc}") from exc
                summary["source_pages"] += 1
                try:
                    parsed_day = _parse_results_all_page(html, source_url=day_url, converter=converter)
                except Exception as exc:
                    raise RuntimeError(f"source_parse_failed: {exc}") from exc
                day_page_cache[day_url] = (parsed_day, _sha256_text(html), day_final_url)
            day_races, day_sha, day_final_url = day_page_cache[day_url]
            available = [item["race_title_hant"] for item in day_races.values()]

            race, reason = _match_race(day_races, target)
            if race is None:
                record_error(target, reason, available=available)
                continue

            race_no = str(race["race_no"] or "").strip()
            if not race_no:
                record_error(target, "race_no_missing", available=available)
                continue

            local_url = _localresults_url(day_url, race_no)
            try:
                local_html, local_final_url = _fetch_text(
                    local_url,
                    source_dir / _source_filename(local_url),
                    allow_network=args.allow_network,
                    timeout=args.timeout_seconds,
                )
            except Exception as exc:
                raise RuntimeError(f"source_fetch_failed: {exc}") from exc
            summary["source_pages"] += 1
            try:
                runners, results, _meta = _parse_local_result_page(
                    local_html,
                    source_url=local_url,
                    race_no=race_no,
                    race_title_hant=race["race_title_hant"],
                    converter=converter,
                )
            except Exception as exc:
                raise RuntimeError(f"source_parse_failed: {exc}") from exc
            if not runners or not results:
                record_error(target, "empty_runners_or_results", available=available)
                continue

            candidate_rows.append(
                {
                    "target_id": int(target_id),
                    "source_name": SOURCE_NAME,
                    "source_url": local_url,
                    "fetched_at": summary["generated_at"],
                    "modules": {
                        "runners": {"items": runners, "is_complete": True},
                        "results": {
                            "items": results,
                            "is_complete": True,
                        },
                    },
                    "evidence": {
                        "pages": [
                            {
                                "url": day_url,
                                "final_url": day_final_url,
                                "sha256": day_sha,
                            },
                            {
                                "url": local_url,
                                "final_url": local_final_url,
                                "sha256": _sha256_text(local_html),
                            },
                        ],
                        "race_no": race_no,
                        "race_title_hant": race["race_title_hant"],
                        "race_title_clean": race["race_title_clean"],
                        "grade_text": target["normalized_grade"],
                        "grade_hint": race["grade_hint"],
                        "distance_text": race["distance_text"],
                        "surface": race["surface"],
                    },
                }
            )
            update_rows.append(
                {
                    "target_id": target_id,
                    "original_name": target["original_name"],
                    "local_date": target["local_date"],
                    "racecourse": target["racecourse"],
                    "race_no": race_no,
                    "race_title_hant": race["race_title_hant"],
                    "distance_text": race["distance_text"],
                    "surface": race["surface"],
                    "grade_hint": race["grade_hint"],
                    "source_urls": f"{day_url} | {local_url}",
                    "page_sha256": f"{day_sha} | {_sha256_text(local_html)}",
                }
            )
            review_rows.append(
                {
                    "target_id": target_id,
                    "original_name": target["original_name"],
                    "status": "prepared",
                    "reason": "",
                    "match_title": race["race_title_hant"],
                    "race_no": race_no,
                    "runners": len(runners),
                    "results": len(results),
                }
            )
            summary["events_prepared"] += 1
            summary["runner_items"] += len(runners)
            summary["result_items"] += len(results)
        except Exception as exc:
            reason = str(exc)
            if reason.startswith("source_parse_failed"):
                code = "source_parse_failed"
            elif reason.startswith(("source_fetch_failed", "缺少缓存")):
                code = "source_fetch_failed"
            else:
                code = "prepare_failed"
            record_error(target, code, detail=reason)

    if candidate_rows:
        with jsonl_path.open("w", encoding="utf-8") as handle:
            for row in candidate_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        with updates_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=TARGET_UPDATE_FIELDS)
            writer.writeheader()
            writer.writerows(update_rows)

    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(review_rows)

    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def bind_candidates(output_dir: Path, binding_path: Path) -> Path:
    """把详情候选绑定到生产 target_sha256 / inventory_artifact_sha256，生成最终导入 JSONL。"""
    from bind_historical_gap_candidates import bind_candidate_rows

    output_dir = Path(output_dir)
    candidates_path = output_dir / "hkjc_gap_detail_candidates.jsonl"
    if not candidates_path.is_file():
        raise ValueError(f"候选文件不存在（可能全部目标失败）：{candidates_path}")
    binding = json.loads(Path(binding_path).read_text(encoding="utf-8"))
    rows = bind_candidate_rows(candidates_path, binding)
    bound_path = output_dir / "hkjc_gap_import_candidates.jsonl"
    with bound_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return bound_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--binding-json", default="", help="提供时执行绑定，生成最终导入 JSONL")
    args = parser.parse_args()
    summary = prepare_gap_candidates(args)
    if args.binding_json:
        bound = bind_candidates(Path(args.output_dir), Path(args.binding_json))
        print(f"bound: {bound}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

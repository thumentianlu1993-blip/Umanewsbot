#!/usr/bin/env python3
"""官方赛历 timeline 与既有目标快照的周期 diff 工具。

输入：
- 新抓官方赛历 timeline 行（JSONL，schema 同各地区 prepare_*_calendar 产物）；
- 既有目标快照（CSV 或 JSONL 导出，字段：series_key/year/country_region/
  local_date/racecourse/grade_text/expectation_status/resolution_status，
  名称列为可选、用于 new 行的模糊身份提示）。

输出五类桶（逐行含证据字段）：
- new：官方有、既有无（同 region 同 year 无该 series_key）；series_key 在快照
  全库（同 region）不存在或入参缺省时，附 series_match_hint 模糊候选供身份映射，
  不擅自并键；
- changed：同 series_key+year 但 local_date/racecourse/grade_text 有差异
  （逐字段 before/after）；
- unchanged：同 series_key+year 且三个 diff 字段一致；
- cancelled：既有 expectation=held 且（未物化或已物化未开赛）、官方新版无，
  且该 (region, year) scope 经 --covers 声明确认被官方来源全集覆盖；
- uncovered：无法安全判取消的既有行（scope 未声明覆盖或状态不可取消），只记录。

计数自校验：changed/unchanged 每行覆盖一对（incoming+existing）输入行，
new/cancelled/uncovered 每行覆盖一条；守恒式为
incoming + existing_in_scope == new + 2*(changed+unchanged) + cancelled + uncovered，
不匹配或空输入一律 fail closed（raise CalendarDiffError）。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from historical_race_calendar_common import (
    CalendarArtifactError,
    atomic_publish_directory,
    canonical_bytes,
    file_identity,
)


SCHEMA_VERSION = "1.0"
DIFF_FIELDS = ("local_date", "racecourse", "grade_text")
BUCKETS = ("new", "changed", "unchanged", "cancelled", "uncovered")
# 取消判定的既有状态白名单之外一律降级 uncovered；已物化行仅在未开赛时可判取消
CANCELLABLE_EXPECTATION = "held"
NON_CANCELLABLE_RESOLUTIONS = {"permanently_unavailable", "superseded"}
MATERIALIZED_RESOLUTIONS = {"ready", "imported"}
HINT_MIN_SCORE = 0.72
HINT_LIMIT = 3
_EXISTING_REQUIRED_FIELDS = (
    "series_key",
    "country_region",
    "year",
    "expectation_status",
    "resolution_status",
)


class CalendarDiffError(CalendarArtifactError):
    pass


def _norm_text(value) -> str:
    return " ".join(str(value or "").split())


def _norm_date(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise CalendarDiffError(f"invalid ISO local_date: {text}") from exc


def _norm_year(value) -> int:
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise CalendarDiffError(f"invalid year: {value!r}") from exc
    if year <= 0 or year > 9999:
        raise CalendarDiffError(f"invalid year: {value!r}")
    return year


def _norm_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def parse_covers(values) -> set[tuple[str, int]]:
    covers: set[tuple[str, int]] = set()
    for raw in values or ():
        text = str(raw or "").strip()
        match = re.fullmatch(r"([A-Za-z0-9_]+):(\d{4})", text)
        if not match:
            raise CalendarDiffError(f"invalid coverage scope (expect REGION:YEAR): {text!r}")
        scope = (match.group(1), int(match.group(2)))
        if scope in covers:
            raise CalendarDiffError(f"duplicate coverage scope: {text}")
        covers.add(scope)
    return covers


def render_scope(scope: tuple[str, int]) -> str:
    return f"{scope[0]}:{scope[1]}"


def normalize_incoming_row(row: dict, *, source: dict) -> dict:
    if not isinstance(row, dict):
        raise CalendarDiffError("incoming timeline row must be an object")
    record_type = str(row.get("record_type") or "timeline")
    if record_type != "timeline":
        raise CalendarDiffError(f"incoming row is not a timeline record: {record_type}")
    region = _norm_text(row.get("country_region"))
    if not region:
        raise CalendarDiffError("incoming timeline row is missing country_region")
    year = _norm_year(row.get("year"))
    expectation = _norm_text(row.get("expectation_status")) or "held"
    return {
        "country_region": region,
        "year": year,
        "series_key": _norm_text(row.get("series_key")),
        "local_date": _norm_date(row.get("local_date")),
        "racecourse": _norm_text(row.get("racecourse")),
        "grade_text": _norm_text(row.get("grade_text")),
        "original_name": _norm_text(row.get("original_name")),
        "canonical_name_original": _norm_text(row.get("canonical_name_original")),
        "surface": _norm_text(row.get("surface")),
        "distance_text": _norm_text(row.get("distance_text")),
        "expectation_status": expectation,
        "evidence": dict(source),
    }


def normalize_existing_row(row: dict) -> dict:
    if not isinstance(row, dict):
        raise CalendarDiffError("existing snapshot row must be an object")
    missing = [
        field
        for field in _EXISTING_REQUIRED_FIELDS
        if not _norm_text(row.get(field)) and field != "year"
    ]
    if missing:
        raise CalendarDiffError(f"existing snapshot row is missing fields: {', '.join(missing)}")
    year = _norm_year(row.get("year"))
    return {
        "series_key": _norm_text(row.get("series_key")),
        "country_region": _norm_text(row.get("country_region")),
        "year": year,
        "local_date": _norm_date(row.get("local_date")),
        "racecourse": _norm_text(row.get("racecourse")),
        "grade_text": _norm_text(row.get("grade_text")),
        "expectation_status": _norm_text(row.get("expectation_status")),
        "resolution_status": _norm_text(row.get("resolution_status")),
        "original_name": _norm_text(row.get("original_name")),
        "canonical_name_original": _norm_text(row.get("canonical_name_original")),
    }


def _incoming_matchable(row: dict) -> bool:
    return bool(row["series_key"]) and row["expectation_status"] == "held"


def _cancellable(row: dict, *, today: date) -> bool:
    if row["expectation_status"] != CANCELLABLE_EXPECTATION:
        return False
    if row["resolution_status"] in NON_CANCELLABLE_RESOLUTIONS:
        return False
    if row["resolution_status"] in MATERIALIZED_RESOLUTIONS:
        # 已物化未开赛才可判取消；local_date 已过视为已完赛
        return not row["local_date"] or row["local_date"] >= today.isoformat()
    return True


def _field_values(row: dict) -> dict:
    return {field: row.get(field, "") for field in DIFF_FIELDS}


def _series_match_hints(new_row: dict, candidates: list[dict]) -> list[dict]:
    """按名称/键模糊给出身份映射候选；只提示不并键。"""
    name_identity = _norm_name(new_row["original_name"] or new_row["canonical_name_original"])
    key_identity = _norm_name(new_row["series_key"])
    hints: dict[str, dict] = {}
    for candidate in candidates:
        best_score = 0.0
        matched_on = ""
        if name_identity:
            for text in (candidate["original_name"], candidate["canonical_name_original"]):
                candidate_identity = _norm_name(text)
                if not candidate_identity:
                    continue
                score = SequenceMatcher(None, name_identity, candidate_identity).ratio()
                if score > best_score:
                    best_score = score
                    matched_on = "name"
        if key_identity and candidate["series_key"]:
            score = SequenceMatcher(None, key_identity, _norm_name(candidate["series_key"])).ratio()
            if score > best_score:
                best_score = score
                matched_on = "key"
        if best_score >= HINT_MIN_SCORE:
            hints[candidate["series_key"]] = {
                "series_key": candidate["series_key"],
                "score": round(best_score, 4),
                "matched_on": matched_on,
            }
    return sorted(hints.values(), key=lambda item: (-item["score"], item["series_key"]))[:HINT_LIMIT]


def compute_diff(
    *,
    incoming_rows,
    existing_rows,
    covers,
    today: date | None = None,
    source: dict | None = None,
) -> list[dict]:
    """对原始 timeline 行与既有快照行分类。返回五桶 diff 行（确定性排序）。"""
    today = today or date.today()
    default_source = {"source_url": "", "source_path": "", "source_sha256": ""}
    incoming = [
        normalize_incoming_row(row, source=source or default_source) for row in incoming_rows
    ]
    existing = [normalize_existing_row(row) for row in existing_rows]
    if not incoming:
        raise CalendarDiffError("incoming timeline is empty")
    if not existing:
        raise CalendarDiffError("existing snapshot is empty")
    return _diff_normalized(incoming, existing, covers=set(covers or set()), today=today)


def summarize(
    rows: list[dict],
    *,
    incoming_count: int,
    existing_count: int,
    existing_in_scope_count: int,
    covers: set[tuple[str, int]],
    today: date,
) -> dict:
    counts = {bucket: 0 for bucket in BUCKETS}
    by_scope: dict[str, dict[str, int]] = {}
    for row in rows:
        counts[row["bucket"]] += 1
        scope = render_scope((row["country_region"], row["year"]))
        scope_counts = by_scope.setdefault(scope, {bucket: 0 for bucket in BUCKETS})
        scope_counts[row["bucket"]] += 1
    input_rows = incoming_count + existing_in_scope_count
    weighted = (
        counts["new"] + 2 * (counts["changed"] + counts["unchanged"]) + counts["cancelled"] + counts["uncovered"]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "today": today.isoformat(),
        "covers": sorted(render_scope(scope) for scope in covers),
        "counts": {
            "incoming_rows": incoming_count,
            "existing_rows": existing_count,
            "existing_in_scope_rows": existing_in_scope_count,
            "existing_out_of_scope_rows": existing_count - existing_in_scope_count,
            "diff_rows": len(rows),
            "buckets": counts,
        },
        "by_scope": {scope: by_scope[scope] for scope in sorted(by_scope)},
        "conservation": {
            "input_rows": input_rows,
            "weighted_bucket_rows": weighted,
            "ok": input_rows == weighted,
        },
    }


def _read_jsonl(path: Path) -> list[dict]:
    if path.is_symlink() or not path.is_file():
        raise CalendarDiffError(f"input is not a regular file: {path}")
    rows = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CalendarDiffError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise CalendarDiffError(f"JSONL row must be an object at {path}:{line_number}")
            rows.append(payload)
    return rows


def _read_existing(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        if path.is_symlink() or not path.is_file():
            raise CalendarDiffError(f"existing snapshot is not a regular file: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    return _read_jsonl(path)


def parse_incoming_spec(value: str) -> tuple[str, Path]:
    text = str(value or "")
    if "=" not in text:
        raise CalendarDiffError(f"--incoming must be URL=PATH: {text!r}")
    url, _, raw_path = text.partition("=")
    url = url.strip()
    if not re.fullmatch(r"https://[^/\s]+(?:\S*)", url):
        raise CalendarDiffError(f"--incoming URL must be a credentialess HTTPS URL: {url!r}")
    path = Path(raw_path.strip())
    if not path.is_file() or path.is_symlink():
        raise CalendarDiffError(f"--incoming path is not a regular file: {path}")
    return url, path


def generate_diff(
    *,
    incoming,
    existing_path,
    covers,
    today: date | None = None,
    output_dir,
) -> dict:
    """文件级入口：读取输入、分类、原子发布 calendar_diff.jsonl + summary.json。"""
    today = today or date.today()
    covers = set(covers or set())
    sources = []
    normalized_incoming: list[dict] = []
    for url, path in incoming:
        identity = file_identity(Path(path))
        source = {
            "source_url": url,
            "source_path": identity["path"],
            "source_sha256": identity["sha256"],
        }
        sources.append({"url": url, **identity, "rows": 0})
        rows = _read_jsonl(Path(path))
        sources[-1]["rows"] = len(rows)
        normalized_incoming.extend(
            normalize_incoming_row(row, source=source) for row in rows
        )
    existing_path = Path(existing_path)
    existing_identity = file_identity(existing_path)
    existing_raw = _read_existing(existing_path)
    normalized_existing = [normalize_existing_row(row) for row in existing_raw]

    if not normalized_incoming:
        raise CalendarDiffError("incoming timeline is empty")
    if not normalized_existing:
        raise CalendarDiffError("existing snapshot is empty")

    scopes = covers | {
        (row["country_region"], row["year"]) for row in normalized_incoming
    }
    scoped_existing_count = sum(
        1 for row in normalized_existing if (row["country_region"], row["year"]) in scopes
    )
    rows = _diff_normalized(
        normalized_incoming,
        normalized_existing,
        covers=covers,
        today=today,
    )
    summary = summarize(
        rows,
        incoming_count=len(normalized_incoming),
        existing_count=len(normalized_existing),
        existing_in_scope_count=scoped_existing_count,
        covers=covers,
        today=today,
    )
    summary["inputs"] = {
        "incoming": sources,
        "existing": {**existing_identity, "rows": len(normalized_existing)},
    }

    output = Path(output_dir)
    if output.exists() or output.is_symlink():
        raise CalendarDiffError(f"diff output directory already exists: {output}")

    def writer(root: Path) -> None:
        diff_path = root / "calendar_diff.jsonl"
        with diff_path.open("wb") as handle:
            for row in rows:
                handle.write(canonical_bytes(row))
        summary["artifacts"] = {
            "calendar_diff": file_identity(diff_path, relative_to=root)
        }
        (root / "summary.json").write_bytes(canonical_bytes(summary))

    atomic_publish_directory(output, writer)
    return summary


def _diff_normalized(
    incoming: list[dict],
    existing: list[dict],
    *,
    covers: set[tuple[str, int]],
    today: date,
) -> list[dict]:
    """对已完成 normalize 的行分类（generate_diff 与 compute_diff 共用）。"""
    incoming_by_identity: dict[tuple[str, str, int], dict] = {}
    for row in incoming:
        if not _incoming_matchable(row):
            continue
        identity = (row["country_region"], row["series_key"], row["year"])
        if identity in incoming_by_identity:
            raise CalendarDiffError(
                "duplicate incoming identity: " + "/".join(map(str, identity))
            )
        incoming_by_identity[identity] = row
    existing_by_identity: dict[tuple[str, str, int], dict] = {}
    series_universe: dict[str, dict[str, dict]] = {}
    for row in existing:
        identity = (row["country_region"], row["series_key"], row["year"])
        if identity in existing_by_identity:
            raise CalendarDiffError(
                "duplicate existing identity: " + "/".join(map(str, identity))
            )
        existing_by_identity[identity] = row
        series_universe.setdefault(row["country_region"], {}).setdefault(row["series_key"], row)

    scopes = covers | {(row["country_region"], row["year"]) for row in incoming}
    scoped_existing = [
        row for row in existing if (row["country_region"], row["year"]) in scopes
    ]

    rows: list[dict] = []
    matched_existing: set[tuple[str, str, int]] = set()
    for identity, incoming_row in sorted(incoming_by_identity.items()):
        existing_row = existing_by_identity.get(identity)
        if existing_row is None:
            continue
        matched_existing.add(identity)
        before = _field_values(existing_row)
        after = _field_values(incoming_row)
        changes = {
            field: {"before": before[field], "after": after[field]}
            for field in DIFF_FIELDS
            if before[field] != after[field]
        }
        base = {
            "country_region": identity[0],
            "year": identity[2],
            "series_key": identity[1],
            "evidence": dict(incoming_row["evidence"]),
        }
        if changes:
            rows.append(
                {
                    **base,
                    "bucket": "changed",
                    "before": {
                        **before,
                        "expectation_status": existing_row["expectation_status"],
                        "resolution_status": existing_row["resolution_status"],
                    },
                    "after": {
                        **after,
                        "original_name": incoming_row["original_name"],
                        "canonical_name_original": incoming_row["canonical_name_original"],
                    },
                    "changes": changes,
                }
            )
        else:
            rows.append({**base, "bucket": "unchanged", "values": before})

    for row in incoming:
        identity = (row["country_region"], row["series_key"], row["year"])
        if _incoming_matchable(row) and identity in matched_existing:
            continue
        known_series = row["series_key"] in series_universe.get(row["country_region"], {})
        hint = []
        if not known_series:
            hint = _series_match_hints(
                row, list(series_universe.get(row["country_region"], {}).values())
            )
        rows.append(
            {
                "bucket": "new",
                "country_region": row["country_region"],
                "year": row["year"],
                "series_key": row["series_key"],
                "local_date": row["local_date"],
                "racecourse": row["racecourse"],
                "grade_text": row["grade_text"],
                "original_name": row["original_name"],
                "canonical_name_original": row["canonical_name_original"],
                "surface": row["surface"],
                "distance_text": row["distance_text"],
                "expectation_status": "held",
                "series_match_hint": hint,
                "evidence": dict(row["evidence"]),
            }
        )

    for row in scoped_existing:
        identity = (row["country_region"], row["series_key"], row["year"])
        if identity in matched_existing:
            continue
        base = {
            "country_region": row["country_region"],
            "year": row["year"],
            "series_key": row["series_key"],
            "existing": {
                **_field_values(row),
                "expectation_status": row["expectation_status"],
                "resolution_status": row["resolution_status"],
            },
        }
        if (row["country_region"], row["year"]) not in covers:
            rows.append({**base, "bucket": "uncovered", "reason": "scope_not_covered"})
        elif not _cancellable(row, today=today):
            rows.append({**base, "bucket": "uncovered", "reason": "state_not_cancellable"})
        else:
            rows.append(
                {
                    **base,
                    "bucket": "cancelled",
                    "reason": "absent_from_covered_official_calendar",
                }
            )

    bucket_order = {bucket: index for index, bucket in enumerate(BUCKETS)}
    rows.sort(
        key=lambda row: (
            row["country_region"],
            row["year"],
            row["series_key"],
            bucket_order[row["bucket"]],
        )
    )
    counts = {bucket: 0 for bucket in BUCKETS}
    for row in rows:
        counts[row["bucket"]] += 1
    input_rows = len(incoming) + len(scoped_existing)
    weighted = (
        counts["new"] + 2 * (counts["changed"] + counts["unchanged"]) + counts["cancelled"] + counts["uncovered"]
    )
    if input_rows != weighted:
        raise CalendarDiffError(
            f"diff count conservation failed: input={input_rows} weighted_buckets={weighted}"
        )
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="官方赛历 timeline 与既有目标快照 diff（calendar_diff.jsonl + summary.json）"
    )
    parser.add_argument(
        "--incoming",
        action="append",
        required=True,
        metavar="URL=PATH",
        help="官方赛历 timeline JSONL（可多个），URL 为该文件的官方来源证据",
    )
    parser.add_argument("--existing", required=True, help="既有目标快照（CSV 或 JSONL）")
    parser.add_argument(
        "--covers",
        action="append",
        default=[],
        metavar="REGION:YEAR",
        help="声明官方来源全集覆盖的 scope（可多个）；未声明 scope 的缺失行只降级 uncovered",
    )
    parser.add_argument("--today", default="", help="判定基准日 YYYY-MM-DD（默认今日）")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)

    incoming = [parse_incoming_spec(value) for value in args.incoming]
    covers = parse_covers(args.covers)
    today = date.fromisoformat(args.today) if args.today.strip() else date.today()
    summary = generate_diff(
        incoming=incoming,
        existing_path=args.existing,
        covers=covers,
        today=today,
        output_dir=args.output_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from .checkpoint import merge_stage, run_checkpointed, store_for
from .collector import Collector, HttpClient, resolve_base_url
from .core import (
    ENGLISH_OPTIONAL_REGIONS, PARSER_VERSION, REGION_OUTPUT, SAFE_STOP_EXIT_CODE,
    SCHEMA_VERSION, TARGET_JAPAN_GRADES, TARGET_STANDARD_GRADES, HorseSeed,
    ParticipantRow, atomic_write_json, atomic_write_text, keys_sha256,
    load_region_overrides, sha256_bytes, utc_now_iso, write_csv,
)


def load_manifest(root: Path) -> tuple[dict[str, Any], str]:
    path = root / "run_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "year", "cutoff", "base_url", "race_urls", "race_urls_sha256",
        "region_overrides_sha256", "created_at",
    }
    missing = sorted(required - set(manifest))
    if missing: raise ValueError(f"run manifest missing fields: {missing}")
    if keys_sha256(manifest["race_urls"]) != manifest["race_urls_sha256"]:
        raise ValueError("run manifest URL digest drift")
    return manifest, sha256_bytes(path.read_bytes())


def race_records(root: Path, manifest_sha: str, race_urls: list[str]) -> list[dict[str, Any]]:
    return store_for(
        root, stage="races_merged", manifest_sha=manifest_sha, keys=race_urls,
        shard_index=None, shard_count=1,
    ).records()


def build_horse_seeds(records: list[dict[str, Any]]) -> dict[str, HorseSeed]:
    seeds: dict[str, HorseSeed] = {}
    for record in records:
        if record.get("status") != "success" or not record.get("included"): continue
        for row in record.get("rows", []):
            key = str(row["horse_lookup_key"])
            seed = seeds.setdefault(key, HorseSeed(key=key, region=str(row["region"])))
            seed.display_names.add(str(row["horse_display_name"])); seed.race_urls.add(str(row["race_url"]))
            seed.participant_occurrences += 1
    return seeds


def finalize(root: Path, *, fail_on_missing_english: bool) -> int:
    manifest, manifest_sha = load_manifest(root); race_urls = list(manifest["race_urls"])
    races = race_records(root, manifest_sha, race_urls); seeds = build_horse_seeds(races)
    profile_keys = sorted(seeds)
    profile_store = store_for(
        root, stage="profiles_merged", manifest_sha=manifest_sha, keys=profile_keys,
        shard_index=None, shard_count=1,
    )
    profiles = {record["key"]: record for record in profile_store.records()}
    if set(profiles) != set(profile_keys): raise ValueError("profile coverage is incomplete")

    rows: list[dict[str, Any]] = []; source_manifest: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []; included_races: set[str] = set()
    for record in races:
        if record.get("source"): source_manifest.append(record["source"])
        if record.get("status") != "success":
            errors.append({"stage": "races", "key": record["key"],
                           "error_code": record.get("error_code", record.get("status", "")),
                           "error": record.get("error", "")})
            continue
        if not record.get("included"): continue
        included_races.add(record["key"])
        for raw in record.get("rows", []):
            row = dict(raw); profile = profiles[row["horse_lookup_key"]]
            row.update({
                "horse_profile_url": profile.get("profile_url", ""),
                "horse_original_name": profile.get("original_name", ""),
                "horse_birth_year": profile.get("birth_year", ""),
                "horse_name_zh": profile.get("name_zh", ""),
                "horse_name_ja": profile.get("name_ja", ""),
                "horse_name_en": profile.get("name_en", ""),
            })
            row["english_name_required"] = row["region"] not in ENGLISH_OPTIONAL_REGIONS
            row["english_name_missing"] = bool(row["english_name_required"] and not row["horse_name_en"])
            rows.append(row)
    for record in profiles.values():
        if record.get("status") in {"retryable_error", "permanent_error"}:
            errors.append({"stage": "profiles", "key": record["key"],
                           "error_code": record.get("error_code", record.get("status", "")),
                           "error": record.get("error", "")})

    rows.sort(key=lambda item: (
        item["race_date"], item["region"], item["race_url"],
        item["finish_position"] if item["finish_position"] is not None else 9999,
        item["horse_display_name"],
    ))
    final_dir = root / "final"; final_dir.mkdir(parents=True, exist_ok=True)
    year = int(manifest["year"])
    participant_fields = list(ParticipantRow.__dataclass_fields__)
    write_csv(final_dir / f"race_participants_{year}.csv", rows, participant_fields)

    occurrences = Counter(row["horse_lookup_key"] for row in rows); horse_rows: list[dict[str, Any]] = []
    for key in profile_keys:
        profile = profiles[key]; seed = seeds[key]
        english_required = seed.region not in ENGLISH_OPTIONAL_REGIONS
        english_missing = english_required and not profile.get("name_en", "")
        horse_rows.append({
            "horse_key": key, "region": seed.region, "region_label": REGION_OUTPUT[seed.region],
            "horse_name_zh": profile.get("name_zh", ""), "horse_name_ja": profile.get("name_ja", ""),
            "horse_name_en": profile.get("name_en", ""), "display_names": "|".join(sorted(seed.display_names)),
            "original_name": profile.get("original_name", ""), "birth_year": profile.get("birth_year", ""),
            "profile_url": profile.get("profile_url", ""), "profile_status": profile.get("status", ""),
            "name_quality_status": "missing_required_english" if english_missing else profile.get("name_quality_status", "complete"),
            "english_name_required": english_required, "english_name_missing": english_missing,
            "graded_race_count": len(seed.race_urls), "participant_occurrences": occurrences[key],
        })
    horse_rows.sort(key=lambda item: (
        item["region"], item["horse_name_en"] or item["horse_name_zh"] or item["horse_name_ja"] or item["display_names"]
    ))
    horse_fields = list(horse_rows[0]) if horse_rows else [
        "horse_key", "region", "region_label", "horse_name_zh", "horse_name_ja", "horse_name_en",
        "display_names", "original_name", "birth_year", "profile_url", "profile_status",
        "name_quality_status", "english_name_required", "english_name_missing",
        "graded_race_count", "participant_occurrences",
    ]
    write_csv(final_dir / f"horse_name_mapping_{year}.csv", horse_rows, horse_fields)
    review_rows = [item for item in horse_rows if item["english_name_missing"] or item["profile_status"] in {
        "not_found", "ambiguous", "retryable_error"
    }]
    write_csv(final_dir / f"name_review_queue_{year}.csv", review_rows, horse_fields)
    atomic_write_text(final_dir / "source_manifest.jsonl", "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
        for item in sorted(source_manifest, key=lambda item: item.get("url", ""))
    ))
    atomic_write_json(final_dir / "errors.json", sorted(errors, key=lambda item: (item["stage"], item["key"])))

    races_by_region: dict[str, set[str]] = defaultdict(set)
    for row in rows: races_by_region[row["region"]].add(row["race_url"])
    missing_required_english = sum(bool(item["english_name_missing"]) for item in horse_rows)
    summary = {
        "artifact_type": "umafans_graded_race_participants",
        "scope": {
            "year": year, "cutoff_inclusive": manifest["cutoff"],
            "regions": [REGION_OUTPUT[key] for key in REGION_OUTPUT],
            "japan_grades": sorted(TARGET_JAPAN_GRADES),
            "other_region_grades": sorted(TARGET_STANDARD_GRADES),
            "participant_definition": "actual starters including DNF/PU/F/UR/BD/DSQ; excluding scratch/withdrawn/non-runner",
            "coverage_basis": "UmaFans current public data-quality-complete race sitemap and result pages",
            "completeness_warning": "This artifact does not independently prove external global catalog completeness.",
        },
        "counts": {
            "included_races": len(included_races), "participant_rows": len(rows),
            "unique_horses": len(horse_rows),
            "races_by_region": {REGION_OUTPUT[key]: len(value) for key, value in sorted(races_by_region.items())},
            "rows_by_result_status": dict(sorted(Counter(row["result_status"] for row in rows).items())),
            "missing_required_english": missing_required_english,
            "name_review_queue": len(review_rows), "errors": len(errors),
        },
        "quality": {
            "english_name_contract_passed": missing_required_english == 0,
            "quality_gate_passed": missing_required_english == 0 and not errors,
        },
        "files": [
            f"race_participants_{year}.csv", f"horse_name_mapping_{year}.csv",
            f"name_review_queue_{year}.csv", "source_manifest.jsonl", "errors.json", "summary.json", "README.md",
        ],
        "completed_at": utc_now_iso(),
    }
    atomic_write_json(final_dir / "summary.json", summary)
    atomic_write_text(final_dir / "README.md", f"""# {year} 年重赏参赛马与三语马名

- 年份：{year}
- 截止日期（含）：{manifest['cutoff']}
- 入围赛事：{len(included_races)}
- 参赛记录：{len(rows)}
- 去重马匹：{len(horse_rows)}
- 非日本/香港缺失英文名：{missing_required_english}

本结果基于 UmaFans 当前公开且 data-quality-complete 的赛事页，不等于独立证明外部赛事目录完整。
本任务未使用 Wikipedia 或 Wikidata，也未写入生产数据库。
""")
    return 2 if fail_on_missing_english and missing_required_english else 0


def run_stage(args: argparse.Namespace) -> int:
    root = Path(args.output_dir); root.mkdir(parents=True, exist_ok=True)
    cutoff = date.fromisoformat(args.cutoff) if args.cutoff else date(args.year, 12, 31)
    if cutoff.year != args.year: raise SystemExit("--cutoff must be in --year")
    overrides = load_region_overrides(args.region_overrides)
    override_sha = sha256_bytes(Path(args.region_overrides).read_bytes()) if args.region_overrides else ""

    if args.stage == "discover":
        manifest_path = root / "run_manifest.json"
        if manifest_path.exists() and not args.refresh_discovery:
            existing, _ = load_manifest(root)
            if int(existing["year"]) != args.year or existing["cutoff"] != cutoff.isoformat() or existing.get("region_overrides_sha256", "") != override_sha:
                raise ValueError("existing run manifest scope differs from CLI")
            print(f"Reusing {len(existing['race_urls'])} discovered race URLs for {args.year}", flush=True)
            return 0
        client = HttpClient(delay=args.delay, timeout=args.timeout, user_agent=args.user_agent)
        base_url = resolve_base_url(client, args.base_url)
        collector = Collector(base_url=base_url, client=client, year=args.year, cutoff=cutoff, region_overrides=overrides)
        race_urls = collector.discover_race_urls()
        if args.max_races: race_urls = race_urls[:args.max_races]
        atomic_write_json(manifest_path, {
            "schema_version": SCHEMA_VERSION, "parser_version": PARSER_VERSION,
            "year": args.year, "cutoff": cutoff.isoformat(), "base_url": base_url,
            "requested_base_url": args.base_url, "race_urls": race_urls,
            "race_urls_sha256": keys_sha256(race_urls), "region_overrides_sha256": override_sha,
            "created_at": utc_now_iso(), "http_request_count": client.request_count,
        })
        print(f"Discovered {len(race_urls)} race URLs for {args.year}", flush=True); return 0

    manifest, manifest_sha = load_manifest(root)
    if int(manifest["year"]) != args.year or manifest["cutoff"] != cutoff.isoformat():
        raise ValueError("CLI scope differs from run manifest")
    if manifest.get("region_overrides_sha256", "") != override_sha:
        raise ValueError("region override file differs from run manifest")
    race_urls = list(manifest["race_urls"])

    if args.stage == "races":
        client = HttpClient(delay=args.delay, timeout=args.timeout, user_agent=args.user_agent)
        collector = Collector(base_url=manifest["base_url"], client=client, year=args.year, cutoff=cutoff, region_overrides=overrides)
        store = store_for(root, stage="races", manifest_sha=manifest_sha, keys=race_urls,
                          shard_index=args.shard_index, shard_count=args.shard_count)
        progress = run_checkpointed(
            race_urls, store=store, process=collector.parse_race_page, resume=args.resume,
            start_index=args.start_index, limit=args.limit, time_budget_seconds=args.time_budget_seconds,
            checkpoint_every=args.checkpoint_every, request_counter=lambda: client.request_count,
        )
        return SAFE_STOP_EXIT_CODE if progress["safe_stopped"] else 0
    if args.stage == "merge_races":
        merge_stage(root, source_stage="races", target_stage="races_merged",
                    manifest_sha=manifest_sha, keys=race_urls, shard_count=args.shard_count)
        return 0

    races = race_records(root, manifest_sha, race_urls); seeds = build_horse_seeds(races); profile_keys = sorted(seeds)
    if args.stage == "profiles":
        client = HttpClient(delay=args.delay, timeout=args.timeout, user_agent=args.user_agent)
        collector = Collector(base_url=manifest["base_url"], client=client, year=args.year, cutoff=cutoff, region_overrides=overrides)
        store = store_for(root, stage="profiles", manifest_sha=manifest_sha, keys=profile_keys,
                          shard_index=args.shard_index, shard_count=args.shard_count)
        progress = run_checkpointed(
            profile_keys, store=store, process=lambda key: collector.find_profile(key, seeds[key]),
            resume=args.resume, start_index=args.start_index, limit=args.limit,
            time_budget_seconds=args.time_budget_seconds, checkpoint_every=args.checkpoint_every,
            request_counter=lambda: client.request_count,
        )
        return SAFE_STOP_EXIT_CODE if progress["safe_stopped"] else 0
    if args.stage == "merge_profiles":
        merge_stage(root, source_stage="profiles", target_stage="profiles_merged",
                    manifest_sha=manifest_sha, keys=profile_keys, shard_count=args.shard_count)
        return 0
    if args.stage == "finalize":
        return finalize(root, fail_on_missing_english=args.fail_on_missing_required_english)
    raise ValueError(f"unsupported stage: {args.stage}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=(
        "discover", "races", "merge_races", "profiles", "merge_profiles", "finalize",
    ))
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--cutoff", default="", help="Inclusive YYYY-MM-DD; defaults to YEAR-12-31")
    parser.add_argument("--base-url", default="https://umafans.run")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--region-overrides", default="")
    parser.add_argument("--delay", type=float, default=0.12); parser.add_argument("--timeout", type=float, default=40.0)
    parser.add_argument("--user-agent", default="UmaFansResearch/2.0 (graded race participant names; read-only research)")
    parser.add_argument("--max-races", type=int, default=0); parser.add_argument("--refresh-discovery", action="store_true")
    parser.add_argument("--resume", action="store_true"); parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0); parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1); parser.add_argument("--time-budget-seconds", type=float, default=0)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--fail-on-missing-required-english", action="store_true")
    args = parser.parse_args(argv)
    if not 1900 <= args.year <= date.today().year: parser.error("--year must be between 1900 and the current year")
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count: parser.error("invalid shard parameters")
    if not args.output_dir: args.output_dir = f"runtime/research/output/graded-race-participants/{args.year}"
    return args

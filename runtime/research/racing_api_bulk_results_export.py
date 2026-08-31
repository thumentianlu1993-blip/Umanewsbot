#!/usr/bin/env python3
"""按单日/单地区导出 TRA 赛果，并与受控目标赛事账本离线对账。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Mapping

from racing_api_horse_export import (
    REGION_CODES,
    RacingApiClient,
    RacingApiError,
    RecordingClient,
    SAFE_STOP_EXIT_CODE,
    _atomic_write,
    _enabled,
    _race_matches_target,
    _reject_duplicate_json_keys,
    _reject_non_finite_json_constant,
    _require_empty_output,
    _sha256_path,
    _validate_result_page,
    add_exclusive_account_budget_args,
    add_openapi_fingerprint_args,
    build_endpoint,
    build_exclusive_account_budget,
    canonical_json,
    combine_result_pages,
    normalize_space,
    load_openapi_fingerprint,
    openapi_contract_manifest,
    runner_disposition,
)


SHA256_RE = re.compile(r"[0-9a-f]{64}$")


def fetch_bulk_range(
    client: object,
    *,
    start_date: str,
    end_date: str,
    country_region: str,
    max_pages: int,
) -> dict:
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    region_code = REGION_CODES.get(country_region)
    if not region_code:
        raise ValueError("unsupported country region")
    pages = []
    skip = 0
    total: int | None = None
    while total is None or skip < total:
        if len(pages) >= max_pages:
            raise ValueError(f"bulk results page ceiling exceeded: {max_pages}")
        url = build_endpoint(
            "bulk_results",
            start_date=start_date,
            end_date=end_date,
            region=region_code,
            limit=100,
            skip=skip,
        )
        payload = client.request_json(url)
        if not isinstance(payload, Mapping):
            raise ValueError("bulk results response must be an object")
        rows, observed_total = _validate_result_page(
            payload,
            expected_skip=skip,
            expected_total=total,
        )
        pages.append(dict(payload))
        total = observed_total
        skip += len(rows)
        if not rows:
            break
    return combine_result_pages(pages)


def fetch_bulk_partition(
    client: object,
    *,
    local_date: str,
    country_region: str,
    max_pages: int,
) -> dict:
    """Backward-compatible one-day wrapper around the range paginator."""

    return fetch_bulk_range(
        client,
        start_date=local_date,
        end_date=local_date,
        country_region=country_region,
        max_pages=max_pages,
    )


def _participant_rows(target_key: str, race: Mapping[str, object]) -> tuple[list[dict], int]:
    participants = []
    excluded = 0
    runners = race.get("runners")
    if not isinstance(runners, list):
        raise ValueError("race runners must be a list")
    for runner in runners:
        if not isinstance(runner, Mapping):
            raise ValueError("runner must be an object")
        disposition = runner_disposition(runner.get("position"))
        if disposition == "unresolved":
            raise ValueError(f"unresolved runner status: {runner.get('position')!r}")
        if disposition == "non_runner":
            excluded += 1
            continue
        participants.append(
            {
                "target_key": target_key,
                "race_id": normalize_space(race.get("race_id")),
                "horse_id": normalize_space(runner.get("horse_id")),
                "horse_name": normalize_space(runner.get("horse")),
                "reported_position": normalize_space(runner.get("position")),
                "participant_status": disposition,
                "runner": dict(runner),
            }
        )
    return participants, excluded


def reconcile_partition(
    *,
    targets: Iterable[Mapping[str, object]],
    races: Iterable[Mapping[str, object]],
) -> dict:
    target_rows = [dict(target) for target in targets]
    race_rows = [dict(race) for race in races]
    seen_target_keys: set[str] = set()
    mappings = []
    participants = []
    gaps = []
    excluded_non_runner_count = 0
    for target in target_rows:
        target_key = normalize_space(target.get("target_key"))
        if not target_key or target_key in seen_target_keys:
            raise ValueError("target_key must be present and unique")
        seen_target_keys.add(target_key)
        candidates = [race for race in race_rows if _race_matches_target(target, race)]
        if len(candidates) != 1:
            gaps.append(
                {
                    "target_key": target_key,
                    "reason": (
                        "race_candidate_missing" if not candidates else "race_candidate_ambiguous"
                    ),
                    "candidate_race_ids": sorted(
                        normalize_space(race.get("race_id")) for race in candidates
                    ),
                }
            )
            continue
        race = candidates[0]
        target_participants, excluded = _participant_rows(target_key, race)
        participants.extend(target_participants)
        excluded_non_runner_count += excluded
        mappings.append(
            {
                "target_key": target_key,
                "race_id": normalize_space(race.get("race_id")),
                "race_payload_sha256": hashlib.sha256(
                    canonical_json(race).encode("utf-8")
                ).hexdigest(),
                "actual_starter_count": len(target_participants),
                "excluded_non_runner_count": excluded,
            }
        )
    return {
        "schema_version": "bulk-result-reconciliation.v1",
        "status": "complete" if not gaps else "needs_review",
        "target_count": len(target_rows),
        "mapped_targets": len(mappings),
        "participant_count": len(participants),
        "excluded_non_runner_count": excluded_non_runner_count,
        "mappings": sorted(mappings, key=lambda row: row["target_key"]),
        "participants": sorted(
            participants,
            key=lambda row: (row["target_key"], row["race_id"], row["horse_id"]),
        ),
        "gaps": sorted(gaps, key=lambda row: row["target_key"]),
    }


def _load_targets(
    target_path: Path,
    *,
    approved_target_sha256: str,
    target_manifest_path: Path,
    approved_target_manifest_sha256: str,
    local_date: str,
    country_region: str,
) -> tuple[list[dict], dict]:
    manifest_resolved = target_manifest_path.resolve(strict=True)
    if target_manifest_path.is_symlink() or not manifest_resolved.is_file():
        raise ValueError("target ledger manifest must be a regular non-symlink file")
    manifest_sha = _sha256_path(manifest_resolved)
    if (
        not SHA256_RE.fullmatch(approved_target_manifest_sha256)
        or manifest_sha != approved_target_manifest_sha256
    ):
        raise ValueError("approved target ledger manifest SHA-256 mismatch")
    try:
        target_manifest = json.loads(
            manifest_resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_finite_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid target ledger manifest") from exc
    marker = manifest_resolved.parent / "COMPLETE"
    target_identity = target_manifest.get("target_ledger") if isinstance(target_manifest, dict) else None
    blocking_conflicts = (
        target_manifest.get("blocking_source_count_conflicts")
        if isinstance(target_manifest, dict)
        else None
    )
    if blocking_conflicts is None and isinstance(target_manifest, dict):
        blocking_conflicts = target_manifest.get("source_count_conflicts")
    if (
        not isinstance(target_manifest, dict)
        or target_manifest.get("schema_version") != "graded-horse-target-ledger.v1"
        or target_manifest.get("status") != "complete"
        or target_manifest.get("completion_marker") != "COMPLETE"
        or target_manifest.get("database_writes") != 0
        or not isinstance(blocking_conflicts, list)
        or blocking_conflicts
        or not isinstance(target_identity, Mapping)
        or marker.is_symlink()
        or not marker.is_file()
        or marker.read_text(encoding="ascii").strip() != manifest_sha
    ):
        raise ValueError("target ledger is not COMPLETE for the selected scope")
    resolved = target_path.resolve(strict=True)
    if target_path.is_symlink() or not resolved.is_file():
        raise ValueError("target ledger must be a regular non-symlink file")
    actual_sha = _sha256_path(resolved)
    expected_target_path = manifest_resolved.parent / str(target_identity.get("path") or "")
    try:
        expected_target_path = expected_target_path.resolve(strict=True)
        expected_target_path.relative_to(manifest_resolved.parent.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError("target ledger manifest path escapes artifact") from exc
    if (
        not SHA256_RE.fullmatch(approved_target_sha256)
        or actual_sha != approved_target_sha256
        or target_identity.get("sha256") != actual_sha
        or resolved != expected_target_path
    ):
        raise ValueError("approved target ledger SHA-256 mismatch")
    targets = []
    for line_number, line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_non_finite_json_constant,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid target JSONL at line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"target row must be an object at line {line_number}")
        if (
            str(row.get("local_date") or "") == local_date
            and row.get("country_region") == country_region
        ):
            targets.append(row)
    if not targets:
        raise ValueError("target ledger has no rows for requested partition")
    return targets, {
        "path": str(resolved),
        "sha256": actual_sha,
        "size": resolved.stat().st_size,
        "partition_rows": len(targets),
    }


def run_bulk_partition_artifact(
    *,
    target_path: Path,
    approved_target_sha256: str,
    target_manifest_path: Path,
    approved_target_manifest_sha256: str,
    output_dir: Path,
    client: object,
    local_date: str,
    country_region: str,
    max_pages: int,
    openapi_fingerprint_identity: Mapping[str, object],
) -> dict:
    openapi_contract = openapi_contract_manifest(openapi_fingerprint_identity)
    _require_empty_output(output_dir)
    targets, target_identity = _load_targets(
        target_path,
        approved_target_sha256=approved_target_sha256,
        target_manifest_path=target_manifest_path,
        approved_target_manifest_sha256=approved_target_manifest_sha256,
        local_date=local_date,
        country_region=country_region,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    recording = RecordingClient(client)
    combined = fetch_bulk_partition(
        recording,
        local_date=local_date,
        country_region=country_region,
        max_pages=max_pages,
    )
    reconciliation = reconcile_partition(targets=targets, races=combined["races"])
    response_files = []
    for index, response in enumerate(recording.responses, 1):
        path = output_dir / "cache" / f"response-{index:04d}.json"
        _atomic_write(path, f"{canonical_json(response)}\n".encode("utf-8"))
        response_files.append(
            {
                "path": str(path.relative_to(output_dir)),
                "sha256": _sha256_path(path),
                "size": path.stat().st_size,
                "url": response["url"],
            }
        )
    normalized = {
        **reconciliation,
        "database_writes": 0,
        "partition": {"local_date": local_date, "country_region": country_region},
        "provider": {
            key: combined[key]
            for key in ("provider_row_count", "unique_race_count", "page_count")
        },
        "races": combined["races"],
    }
    normalized_path = output_dir / "normalized" / "bulk-result-reconciliation.json"
    _atomic_write(normalized_path, f"{canonical_json(normalized)}\n".encode("utf-8"))
    manifest = {
        "schema_version": "bulk-result-run.v1",
        "status": reconciliation["status"],
        "completion_marker": (
            "COMPLETE" if reconciliation["status"] == "complete" else "PREPARED"
        ),
        "database_writes": 0,
        "openapi_contract": openapi_contract,
        "partition": {"local_date": local_date, "country_region": country_region},
        "target_ledger": target_identity,
        "target_ledger_manifest": {
            "path": str(target_manifest_path.resolve(strict=True)),
            "sha256": approved_target_manifest_sha256,
            "size": target_manifest_path.resolve(strict=True).stat().st_size,
        },
        "request_ceiling": getattr(client, "request_ceiling", None),
        "max_pages": max_pages,
        "request_count": getattr(client, "request_count", len(recording.responses)),
        "request_ledger": list(getattr(client, "request_ledger", [])),
        "responses": response_files,
        "normalized": {
            "path": str(normalized_path.relative_to(output_dir)),
            "sha256": _sha256_path(normalized_path),
            "size": normalized_path.stat().st_size,
        },
        "summary": {
            key: reconciliation[key]
            for key in (
                "target_count",
                "mapped_targets",
                "participant_count",
                "excluded_non_runner_count",
            )
        },
        "gap_count": len(reconciliation["gaps"]),
    }
    manifest_path = output_dir / "run-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    _atomic_write(
        output_dir / manifest["completion_marker"],
        f"{_sha256_path(manifest_path)}\n".encode("ascii"),
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-ledger", type=Path, required=True)
    parser.add_argument("--approved-target-sha256", required=True)
    parser.add_argument("--target-ledger-manifest", type=Path, required=True)
    parser.add_argument("--approved-target-ledger-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--local-date", required=True)
    parser.add_argument(
        "--country-region",
        choices=sorted(REGION_CODES),
        required=True,
    )
    parser.add_argument("--max-pages", type=int, required=True)
    parser.add_argument("--request-ceiling", type=int, required=True)
    parser.add_argument("--allow-network", action="store_true")
    add_openapi_fingerprint_args(parser)
    add_exclusive_account_budget_args(parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.allow_network or not _enabled(
        os.environ.get("RACING_API_HORSE_EXPORT_NETWORK_ENABLED")
    ):
        raise SystemExit(
            "network requires --allow-network and RACING_API_HORSE_EXPORT_NETWORK_ENABLED=true"
        )
    if args.max_pages < 1 or args.request_ceiling != args.max_pages:
        raise SystemExit("request ceiling must exactly equal max-pages for one partition")
    try:
        openapi_fingerprint_identity = load_openapi_fingerprint(
            args.openapi_fingerprint,
            args.approved_openapi_fingerprint_sha256,
        )
        account_budget = build_exclusive_account_budget(args)
        client = RacingApiClient(
            username=os.environ.get("RACING_API_USERNAME", ""),
            password=os.environ.get("RACING_API_PASSWORD", ""),
            request_ceiling=args.request_ceiling,
            min_interval_seconds=0,
            account_budget=account_budget,
        )
        manifest = run_bulk_partition_artifact(
            target_path=args.target_ledger,
            approved_target_sha256=args.approved_target_sha256,
            target_manifest_path=args.target_ledger_manifest,
            approved_target_manifest_sha256=args.approved_target_ledger_manifest_sha256,
            output_dir=args.output_dir,
            client=client,
            local_date=args.local_date,
            country_region=args.country_region,
            max_pages=args.max_pages,
            openapi_fingerprint_identity=openapi_fingerprint_identity,
        )
    except (RacingApiError, OSError, ValueError) as exc:
        print(f"safe-stop: {exc}", file=sys.stderr)
        return SAFE_STOP_EXIT_CODE
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

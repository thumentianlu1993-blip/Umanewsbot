#!/usr/bin/env python3
"""One-request, artifact-only probe for the `/v1/results` historical entitlement."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from datetime import date
from pathlib import Path

from racing_api_horse_export import (
    RacingApiAuthError,
    RacingApiClient,
    RacingApiError,
    REGION_CODES,
    SAFE_STOP_EXIT_CODE,
    _atomic_write,
    _enabled,
    _validate_result_page,
    add_exclusive_account_budget_args,
    add_openapi_fingerprint_args,
    build_endpoint,
    build_exclusive_account_budget,
    load_openapi_fingerprint,
    openapi_contract_manifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ValueError("fresh entitlement probe output is required")
    path.mkdir(mode=0o700, parents=True)
    if stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) & 0o077:
        raise ValueError("entitlement probe output must be private")
    return path.resolve(strict=True)


def _write_json(path: Path, value: object) -> None:
    _atomic_write(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def probe(
    *,
    client: RacingApiClient,
    local_date: str,
    country_region: str,
    output_dir: Path,
    openapi_fingerprint_identity: dict,
) -> dict:
    date.fromisoformat(local_date)
    output = _new_output(output_dir)
    url = build_endpoint(
        "bulk_results",
        start_date=local_date,
        end_date=local_date,
        region=REGION_CODES[country_region],
        limit=100,
        skip=0,
    )
    try:
        payload = client.request_json(url)
        if not isinstance(payload, dict):
            raise ValueError("historical result probe returned no JSON object")
        rows, total = _validate_result_page(payload, expected_skip=0, expected_total=None)
    except Exception as exc:
        failure = {
            "schema_version": "racing-api-historical-results-entitlement-probe.v1",
            "status": "not_entitled" if isinstance(exc, RacingApiAuthError) else "safe_stopped",
            "database_writes": 0,
            "local_date": local_date,
            "country_region": country_region,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "request_count": client.request_count,
            "request_ledger": client.request_ledger,
            "openapi_contract": openapi_contract_manifest(openapi_fingerprint_identity),
        }
        failure_path = output / "probe-result.json"
        _write_json(failure_path, failure)
        _atomic_write(output / "SAFE_STOPPED", f"{_sha256(failure_path)}\n".encode("ascii"))
        raise

    response_path = output / "response.json"
    _write_json(response_path, payload)
    result = {
        "schema_version": "racing-api-historical-results-entitlement-probe.v1",
        "status": "entitled",
        "database_writes": 0,
        "local_date": local_date,
        "country_region": country_region,
        "request_count": client.request_count,
        "request_ledger": client.request_ledger,
        "response": {
            "path": response_path.name,
            "sha256": _sha256(response_path),
            "size": response_path.stat().st_size,
            "row_count": len(rows),
            "reported_total": total,
        },
        "openapi_contract": openapi_contract_manifest(openapi_fingerprint_identity),
    }
    result_path = output / "probe-result.json"
    _write_json(result_path, result)
    _atomic_write(output / "COMPLETE", f"{_sha256(result_path)}\n".encode("ascii"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-date", required=True)
    parser.add_argument(
        "--country-region",
        choices=("france", "ireland", "united_kingdom", "united_states"),
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--request-ceiling", type=int, required=True)
    parser.add_argument("--allow-network", action="store_true")
    add_openapi_fingerprint_args(parser)
    add_exclusive_account_budget_args(parser)
    args = parser.parse_args()
    if (
        not args.allow_network
        or not _enabled(os.environ.get("RACING_API_HORSE_EXPORT_NETWORK_ENABLED"))
        or args.request_ceiling != 1
        or args.account_request_ceiling != 1
    ):
        raise SystemExit("probe requires both network gates and exact one-request ceilings")
    try:
        fingerprint = load_openapi_fingerprint(
            args.openapi_fingerprint, args.approved_openapi_fingerprint_sha256
        )
        budget = build_exclusive_account_budget(args)
        client = RacingApiClient(
            username=os.environ.get("RACING_API_USERNAME", ""),
            password=os.environ.get("RACING_API_PASSWORD", ""),
            request_ceiling=1,
            min_interval_seconds=0,
            max_attempts=1,
            account_budget=budget,
        )
        result = probe(
            client=client,
            local_date=args.local_date,
            country_region=args.country_region,
            output_dir=args.output_dir,
            openapi_fingerprint_identity=fingerprint,
        )
    except (OSError, RacingApiError, ValueError) as exc:
        print(f"safe-stop: {exc}", file=sys.stderr)
        return SAFE_STOP_EXIT_CODE
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

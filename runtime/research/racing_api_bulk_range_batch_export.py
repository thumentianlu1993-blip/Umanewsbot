#!/usr/bin/env python3
"""Artifact-only TRA bulk range batch runner core; no standalone network entry point."""

from __future__ import annotations

import hashlib
import json
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from audit_racing_api_bulk_partition_readiness import MAX_BULK_PAGES_PER_RANGE
from prepare_held_winner_seed_extension import (
    _atomic_write,
    _read_json,
    _read_jsonl,
    _regular,
    _require_sha,
    canonical_json,
    sha256_path,
)
from prepare_racing_api_bulk_range_batch_plan import (
    BATCH_SCHEMA_VERSION,
    SCHEMA_VERSION as PLAN_SCHEMA_VERSION,
)
from racing_api_bulk_results_export import reconcile_partition
from racing_api_horse_export import (
    REGION_CODES,
    _reject_duplicate_json_keys,
    _reject_non_finite_json_constant,
    _validate_result_page,
    build_endpoint,
    combine_result_pages,
    openapi_contract_manifest,
    payload_sha256,
)


RUN_SCHEMA_VERSION = "racing-api-bulk-range-batch-run.v2"
DEFINITION_SCHEMA_VERSION = "racing-api-bulk-range-batch-definition.v1"
CHECKPOINT_SCHEMA_VERSION = "racing-api-bulk-range-batch-checkpoint.v1"


def _read_strict_json(path: Path, *, label: str) -> dict:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    try:
        value = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_finite_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    _atomic_write(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _flatten_ranges(batch: Mapping[str, object]) -> list[dict]:
    ranges = []
    for unit in batch["region_year_units"]:
        for date_range in unit["ranges"]:
            ranges.append(
                {
                    "ordinal": len(ranges) + 1,
                    "country_region": batch["country_region"],
                    "year": unit["year"],
                    "start_date": date_range["start_date"],
                    "end_date": date_range["end_date"],
                    "max_pages": date_range["max_pages_protocol_ceiling"],
                }
            )
    if len(ranges) != batch["date_range_count"]:
        raise ValueError("batch date range flattening drift")
    return ranges


def _batch_definition(
    *,
    batch: Mapping[str, object],
    plan_identity: Mapping[str, object],
    openapi_contract: Mapping[str, object],
) -> dict:
    return {
        "schema_version": DEFINITION_SCHEMA_VERSION,
        "database_writes": 0,
        "batch_id": batch["batch_id"],
        "request_ceiling": batch["request_ceiling"],
        "plan": dict(plan_identity),
        "openapi_contract": dict(openapi_contract),
        "ranges": _flatten_ranges(batch),
    }


def _initial_checkpoint(definition_sha256: str) -> dict:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "status": "running",
        "definition_sha256": definition_sha256,
        "cumulative_request_count": 0,
        "pages": [],
        "attempt_request_ledgers": [],
        "last_error": None,
    }


def _validate_checkpoint_pages(
    *,
    output_dir: Path,
    definition: Mapping[str, object],
    checkpoint: Mapping[str, object],
) -> tuple[dict[int, list[dict]], list[dict]]:
    ranges = definition.get("ranges")
    receipts = checkpoint.get("pages")
    attempt_ledgers = checkpoint.get("attempt_request_ledgers")
    cumulative = checkpoint.get("cumulative_request_count")
    if (
        checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or checkpoint.get("status") not in {"running", "safe_stopped", "complete"}
        or checkpoint.get("definition_sha256")
        != sha256_path(output_dir / "batch-definition.json")
        or not isinstance(ranges, list)
        or not isinstance(receipts, list)
        or not isinstance(attempt_ledgers, list)
        or isinstance(cumulative, bool)
        or not isinstance(cumulative, int)
        or not 0 <= cumulative <= int(definition.get("request_ceiling") or -1)
    ):
        raise ValueError("bulk range checkpoint contract drift")
    pages_by_range: dict[int, list[dict]] = {int(row["ordinal"]): [] for row in ranges}
    expected_range = 1
    expected_page = 1
    expected_skip = 0
    expected_total = None
    referenced = set()
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise ValueError("bulk range checkpoint page receipt must be an object")
        range_ordinal = receipt.get("range_ordinal")
        page_ordinal = receipt.get("page_ordinal")
        if range_ordinal != expected_range or page_ordinal != expected_page:
            raise ValueError("bulk range checkpoint page sequence drift")
        if not 1 <= int(range_ordinal) <= len(ranges):
            raise ValueError("bulk range checkpoint range ordinal drift")
        range_row = ranges[range_ordinal - 1]
        if not 1 <= int(page_ordinal) <= int(range_row["max_pages"]):
            raise ValueError("bulk range checkpoint page ceiling drift")
        relative = Path(str(receipt.get("path") or ""))
        expected_relative = Path("cache") / (
            f"range-{range_ordinal:04d}-page-{page_ordinal:04d}.json"
        )
        if relative != expected_relative or relative.is_absolute():
            raise ValueError("bulk range checkpoint page path drift")
        path = output_dir / relative
        try:
            path.resolve(strict=True).relative_to(output_dir)
        except (OSError, ValueError) as exc:
            raise ValueError("bulk range checkpoint page escapes output") from exc
        wrapper = _read_strict_json(path, label="bulk range checkpoint response")
        expected_url = build_endpoint(
            "bulk_results",
            start_date=range_row["start_date"],
            end_date=range_row["end_date"],
            region=REGION_CODES[str(range_row["country_region"])],
            limit=100,
            skip=expected_skip,
        )
        payload = wrapper.get("payload")
        if (
            receipt.get("sha256") != sha256_path(path)
            or receipt.get("size") != path.stat().st_size
            or receipt.get("url") != expected_url
            or wrapper.get("url") != expected_url
            or wrapper.get("allow_not_found") is not False
            or wrapper.get("not_found") is not False
            or not str(wrapper.get("captured_at") or "")
            or not isinstance(payload, Mapping)
        ):
            raise ValueError("bulk range checkpoint response identity drift")
        rows, observed_total = _validate_result_page(
            payload,
            expected_skip=expected_skip,
            expected_total=expected_total,
        )
        range_complete = expected_skip + len(rows) >= observed_total or not rows
        if (
            receipt.get("skip") != expected_skip
            or receipt.get("total") != observed_total
            or receipt.get("row_count") != len(rows)
            or receipt.get("range_complete") is not range_complete
        ):
            raise ValueError("bulk range checkpoint pagination receipt drift")
        pages_by_range[range_ordinal].append(dict(payload))
        referenced.add(str(relative))
        if range_complete:
            expected_range += 1
            expected_page = 1
            expected_skip = 0
            expected_total = None
        else:
            expected_page += 1
            expected_skip += len(rows)
            expected_total = observed_total
    cache_root = output_dir / "cache"
    observed = (
        {
            str(path.relative_to(output_dir))
            for path in cache_root.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        if cache_root.exists()
        else set()
    )
    if observed != referenced:
        raise ValueError("bulk range checkpoint cache member set drift")
    for attempt in attempt_ledgers:
        if (
            not isinstance(attempt, Mapping)
            or attempt.get("status") not in {"safe_stopped", "complete"}
            or isinstance(attempt.get("request_count"), bool)
            or not isinstance(attempt.get("request_count"), int)
            or not isinstance(attempt.get("request_ledger"), list)
            or attempt.get("request_count") != len(attempt.get("request_ledger"))
        ):
            raise ValueError("bulk range checkpoint attempt ledger drift")
    if sum(int(row["request_count"]) for row in attempt_ledgers) != cumulative:
        raise ValueError("bulk range checkpoint cumulative request count drift")
    if len(receipts) > cumulative:
        raise ValueError("bulk range checkpoint pages exceed request count")
    checkpoint_status = checkpoint["status"]
    if checkpoint_status == "complete" and (
        expected_range != len(ranges) + 1
        or not attempt_ledgers
        or attempt_ledgers[-1]["status"] != "complete"
    ):
        raise ValueError("complete bulk range checkpoint is incomplete")
    if checkpoint_status == "safe_stopped" and (
        not attempt_ledgers or attempt_ledgers[-1]["status"] != "safe_stopped"
    ):
        raise ValueError("safe-stopped bulk range checkpoint attempt drift")
    allowed_members = {
        "batch-definition.json",
        "checkpoint.json",
        *referenced,
    }
    observed_members = {
        str(path.relative_to(output_dir))
        for path in output_dir.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if observed_members != allowed_members:
        raise ValueError("bulk range checkpoint member set drift")
    return pages_by_range, [dict(row) for row in receipts]


def _initialize_or_resume_checkpoint(
    *,
    output_dir: Path,
    definition: dict,
    resume: bool,
    prior_request_count: int,
) -> tuple[dict, dict[int, list[dict]], list[dict]]:
    if resume:
        root = output_dir.resolve(strict=True)
        if output_dir.is_symlink() or not root.is_dir():
            raise ValueError("bulk range output must be a regular directory")
        if stat.S_IMODE(root.stat().st_mode) & 0o077:
            raise ValueError("bulk range output directory must be private")
        observed_definition = _read_strict_json(
            root / "batch-definition.json", label="bulk range batch definition"
        )
        if observed_definition != definition:
            raise ValueError("bulk range batch definition drift")
        checkpoint = _read_strict_json(
            root / "checkpoint.json", label="bulk range checkpoint"
        )
        pages_by_range, receipts = _validate_checkpoint_pages(
            output_dir=root,
            definition=observed_definition,
            checkpoint=checkpoint,
        )
        if checkpoint["status"] != "safe_stopped":
            raise ValueError("bulk range resume requires safe-stopped checkpoint")
        if checkpoint["cumulative_request_count"] != prior_request_count:
            raise ValueError("bulk range prior request count does not bind checkpoint")
        checkpoint["status"] = "running"
        checkpoint["last_error"] = None
        _write_json(root / "checkpoint.json", checkpoint)
        return checkpoint, pages_by_range, receipts
    if prior_request_count != 0:
        raise ValueError("fresh bulk range run cannot have prior requests")
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("range batch output directory must not already exist")
    output_dir.mkdir(parents=True, mode=0o700)
    output_dir.chmod(0o700)
    _write_json(output_dir / "batch-definition.json", definition)
    checkpoint = _initial_checkpoint(sha256_path(output_dir / "batch-definition.json"))
    _write_json(output_dir / "checkpoint.json", checkpoint)
    return checkpoint, {int(row["ordinal"]): [] for row in definition["ranges"]}, []


def _fetch_ranges_with_checkpoint(
    *,
    client: object,
    output_dir: Path,
    definition: Mapping[str, object],
    checkpoint: dict,
    pages_by_range: dict[int, list[dict]],
    receipts: list[dict],
    prior_request_count: int,
) -> dict:
    request_count_before = int(getattr(client, "request_count", 0))
    attempt_ledger_before = len(getattr(client, "request_ledger", []))
    try:
        for range_row in definition["ranges"]:
            ordinal = int(range_row["ordinal"])
            pages = pages_by_range[ordinal]
            if pages and (
                sum(len(page["results"]) for page in pages) >= pages[-1]["total"]
                or not pages[-1]["results"]
            ):
                continue
            skip = sum(len(page["results"]) for page in pages)
            total = pages[-1]["total"] if pages else None
            while total is None or skip < total:
                if len(pages) >= int(range_row["max_pages"]):
                    raise ValueError(
                        f"bulk results page ceiling exceeded: {range_row['max_pages']}"
                    )
                url = build_endpoint(
                    "bulk_results",
                    start_date=range_row["start_date"],
                    end_date=range_row["end_date"],
                    region=REGION_CODES[str(range_row["country_region"])],
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
                page_ordinal = len(pages) + 1
                wrapper = {
                    "url": url,
                    "allow_not_found": False,
                    "not_found": False,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "payload": dict(payload),
                }
                path = output_dir / "cache" / (
                    f"range-{ordinal:04d}-page-{page_ordinal:04d}.json"
                )
                _write_json(path, wrapper)
                range_complete = skip + len(rows) >= observed_total or not rows
                receipt = {
                    "range_ordinal": ordinal,
                    "page_ordinal": page_ordinal,
                    "path": str(path.relative_to(output_dir)),
                    "sha256": sha256_path(path),
                    "size": path.stat().st_size,
                    "url": url,
                    "skip": skip,
                    "total": observed_total,
                    "row_count": len(rows),
                    "range_complete": range_complete,
                }
                pages.append(dict(payload))
                receipts.append(receipt)
                checkpoint.update(
                    status="running",
                    pages=receipts,
                    cumulative_request_count=prior_request_count
                    + int(getattr(client, "request_count", request_count_before))
                    - request_count_before,
                    last_error=None,
                )
                _write_json(output_dir / "checkpoint.json", checkpoint)
                total = observed_total
                skip += len(rows)
                if not rows:
                    break
        races_by_id: dict[str, dict] = {}
        summaries = []
        for range_row in definition["ranges"]:
            combined = combine_result_pages(
                pages_by_range[int(range_row["ordinal"])]
            )
            for race in combined["races"]:
                race_id = str(race["race_id"])
                existing = races_by_id.get(race_id)
                if existing is not None:
                    qualifier = (
                        "conflict"
                        if payload_sha256(existing) != payload_sha256(race)
                        else "duplicate"
                    )
                    raise ValueError(
                        f"race payload {qualifier} across ranges: {race_id}"
                    )
                races_by_id[race_id] = dict(race)
            summaries.append(
                {
                    "country_region": range_row["country_region"],
                    "year": range_row["year"],
                    "start_date": range_row["start_date"],
                    "end_date": range_row["end_date"],
                    "provider_row_count": combined["provider_row_count"],
                    "unique_race_count": combined["unique_race_count"],
                    "page_count": combined["page_count"],
                }
            )
        attempt_count = (
            int(getattr(client, "request_count", request_count_before))
            - request_count_before
        )
        attempt_request_ledger = list(getattr(client, "request_ledger", []))[
            attempt_ledger_before:
        ]
        if attempt_count != len(attempt_request_ledger):
            raise ValueError("bulk range client request ledger count drift")
    except Exception as exc:
        attempt_count = (
            int(getattr(client, "request_count", request_count_before))
            - request_count_before
        )
        checkpoint["attempt_request_ledgers"].append(
            {
                "status": "safe_stopped",
                "request_count": attempt_count,
                "request_ledger": list(getattr(client, "request_ledger", []))[
                    attempt_ledger_before:
                ],
            }
        )
        checkpoint.update(
            status="safe_stopped",
            pages=receipts,
            cumulative_request_count=prior_request_count + attempt_count,
            last_error={"type": type(exc).__name__, "message": str(exc)},
        )
        _write_json(output_dir / "checkpoint.json", checkpoint)
        raise
    checkpoint["attempt_request_ledgers"].append(
        {
            "status": "complete",
            "request_count": attempt_count,
            "request_ledger": attempt_request_ledger,
        }
    )
    checkpoint.update(
        status="complete",
        pages=receipts,
        cumulative_request_count=prior_request_count + attempt_count,
        last_error=None,
    )
    _write_json(output_dir / "checkpoint.json", checkpoint)

    return {
        "races": [races_by_id[key] for key in sorted(races_by_id)],
        "range_summaries": summaries,
        "response_receipts": receipts,
        "provider_row_count": sum(row["provider_row_count"] for row in summaries),
        "unique_race_count": len(races_by_id),
        "page_count": sum(row["page_count"] for row in summaries),
        "request_count": checkpoint["cumulative_request_count"],
        "request_ledger": [
            item
            for attempt in checkpoint["attempt_request_ledgers"]
            for item in attempt["request_ledger"]
        ],
    }


def _path_within(root: Path, relative: object, *, label: str) -> Path:
    value = str(relative or "")
    if not value or Path(value).is_absolute():
        raise ValueError(f"{label} path is invalid")
    try:
        path = (root / value).resolve(strict=True)
        path.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} path escapes artifact") from exc
    return _regular(path, label=label)


def load_planned_batch(
    plan_root: Path,
    *,
    expected_manifest_sha256: str,
    expected_plan_sha256: str,
    batch_id: str,
) -> tuple[dict, list[dict], dict]:
    root = plan_root.resolve(strict=True)
    if plan_root.is_symlink() or not root.is_dir():
        raise ValueError("batch plan root must be a regular directory")
    manifest_path = _regular(root / "batch-plan-manifest.json", label="batch plan manifest")
    manifest = _read_json(manifest_path, label="batch plan manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, expected_manifest_sha256, label="batch plan manifest")
    marker = _regular(root / "PREPARED", label="batch plan PREPARED marker")
    identity = manifest.get("batch_plan")
    counts = manifest.get("counts")
    parameters = manifest.get("parameters")
    if (
        manifest.get("schema_version") != PLAN_SCHEMA_VERSION
        or manifest.get("status") != "PROPOSED_NOT_APPROVED"
        or manifest.get("approval") is not False
        or manifest.get("execution_ready") is not False
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or not isinstance(identity, Mapping)
        or not isinstance(counts, Mapping)
        or not isinstance(parameters, Mapping)
        or parameters.get("max_pages_per_range") != MAX_BULK_PAGES_PER_RANGE
        or parameters.get("max_concurrent_batches") != 1
        or parameters.get("exclusive_account_proof_required_per_batch") is not True
        or parameters.get("exact_g3_required_per_batch") is not True
    ):
        raise ValueError("batch plan manifest contract drift")
    plan_path = _path_within(root, identity.get("path"), label="batch plan")
    plan_sha = sha256_path(plan_path)
    _require_sha(plan_sha, expected_plan_sha256, label="batch plan")
    batches = _read_jsonl(plan_path, label="batch plan")
    if (
        identity.get("sha256") != plan_sha
        or identity.get("size") != plan_path.stat().st_size
        or identity.get("rows") != len(batches)
        or counts.get("batches") != len(batches)
    ):
        raise ValueError("batch plan identity drift")

    total_targets = 0
    total_units = 0
    total_ranges = 0
    total_ceiling = 0
    selected = []
    for ordinal, batch in enumerate(batches, 1):
        units = batch.get("region_year_units")
        ledger = batch.get("target_ledger")
        if (
            batch.get("schema_version") != BATCH_SCHEMA_VERSION
            or batch.get("ordinal") != ordinal
            or not str(batch.get("batch_id") or "")
            or batch.get("approval_status") != "proposed_not_approved"
            or batch.get("execution_ready") is not False
            or not isinstance(units, list)
            or not units
            or not isinstance(ledger, Mapping)
            or batch.get("region_year_unit_count") != len(units)
            or batch.get("date_range_count")
            != sum(int(unit.get("range_count") or 0) for unit in units)
            or batch.get("request_ceiling")
            != int(batch.get("date_range_count") or 0) * MAX_BULK_PAGES_PER_RANGE
        ):
            raise ValueError(f"batch plan row {ordinal} contract drift")
        total_targets += int(batch.get("target_count") or 0)
        total_units += len(units)
        total_ranges += int(batch["date_range_count"])
        total_ceiling += int(batch["request_ceiling"])
        if batch["batch_id"] == batch_id:
            selected.append(batch)
    if (
        counts.get("targets") != total_targets
        or counts.get("region_year_units") != total_units
        or counts.get("date_ranges") != total_ranges
        or counts.get("protocol_request_ceiling") != total_ceiling
        or len(selected) != 1
    ):
        raise ValueError("batch plan totals or selected batch drift")
    batch = selected[0]
    target_path = _path_within(
        root, batch["target_ledger"].get("path"), label="batch target ledger"
    )
    target_rows = _read_jsonl(target_path, label="batch target ledger")
    target_keys = sorted(str(row.get("target_key") or "") for row in target_rows)
    if (
        "" in target_keys
        or len(target_keys) != len(set(target_keys))
        or batch["target_ledger"].get("sha256") != sha256_path(target_path)
        or batch["target_ledger"].get("size") != target_path.stat().st_size
        or batch["target_ledger"].get("rows") != len(target_rows)
        or batch.get("target_count") != len(target_rows)
        or batch.get("target_keys_sha256")
        != hashlib.sha256(("\n".join(target_keys) + "\n").encode("utf-8")).hexdigest()
        or any(row.get("country_region") != batch.get("country_region") for row in target_rows)
        or any(
            not int(batch["year_start"]) <= int(row.get("year") or 0) <= int(batch["year_end"])
            for row in target_rows
        )
    ):
        raise ValueError("batch target ledger identity drift")
    return batch, target_rows, {
        "root": str(root),
        "manifest_sha256": manifest_sha,
        "plan_sha256": plan_sha,
        "target_ledger": {
            "path": str(target_path),
            "sha256": sha256_path(target_path),
            "size": target_path.stat().st_size,
            "rows": len(target_rows),
        },
        "parameters": dict(parameters),
    }


def run_bulk_range_batch_artifact(
    *,
    plan_root: Path,
    expected_plan_manifest_sha256: str,
    expected_batch_plan_sha256: str,
    batch_id: str,
    output_dir: Path,
    client: object,
    openapi_fingerprint_identity: Mapping[str, object],
    resume: bool = False,
    prior_request_count: int = 0,
) -> dict:
    batch, targets, plan_identity = load_planned_batch(
        plan_root,
        expected_manifest_sha256=expected_plan_manifest_sha256,
        expected_plan_sha256=expected_batch_plan_sha256,
        batch_id=batch_id,
    )
    openapi_contract = openapi_contract_manifest(openapi_fingerprint_identity)
    definition = _batch_definition(
        batch=batch,
        plan_identity=plan_identity,
        openapi_contract=openapi_contract,
    )
    if (
        isinstance(prior_request_count, bool)
        or not isinstance(prior_request_count, int)
        or not 0 <= prior_request_count < batch["request_ceiling"]
    ):
        raise ValueError("prior request count is invalid")
    remaining_ceiling = batch["request_ceiling"] - prior_request_count
    if getattr(client, "request_ceiling", None) != remaining_ceiling:
        raise ValueError("client request ceiling does not equal remaining batch ceiling")
    if (
        getattr(client, "request_count", None) != 0
        or getattr(client, "request_ledger", None) != []
    ):
        raise ValueError("bulk range attempt requires a fresh client")
    checkpoint, pages_by_range, receipts = _initialize_or_resume_checkpoint(
        output_dir=output_dir,
        definition=definition,
        resume=resume,
        prior_request_count=prior_request_count,
    )
    output_dir = output_dir.resolve(strict=True)
    fetched = _fetch_ranges_with_checkpoint(
        client=client,
        output_dir=output_dir,
        definition=definition,
        checkpoint=checkpoint,
        pages_by_range=pages_by_range,
        receipts=receipts,
        prior_request_count=prior_request_count,
    )
    reconciliation = reconcile_partition(targets=targets, races=fetched["races"])
    response_files = fetched["response_receipts"]
    normalized = {
        **reconciliation,
        "database_writes": 0,
        "batch_id": batch_id,
        "provider": {
            key: fetched[key]
            for key in ("provider_row_count", "unique_race_count", "page_count")
        },
        "range_summaries": fetched["range_summaries"],
        "races": fetched["races"],
    }
    normalized_path = output_dir / "normalized" / "bulk-range-reconciliation.json"
    _atomic_write(normalized_path, (canonical_json(normalized) + "\n").encode("utf-8"))
    reconciliation_status = reconciliation["status"]
    status = (
        "complete"
        if reconciliation_status == "complete"
        else "complete_with_gaps"
    )
    marker = "COMPLETE"
    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": status,
        "reconciliation_status": reconciliation_status,
        "completion_marker": marker,
        "database_writes": 0,
        "batch": {key: value for key, value in batch.items() if key != "region_year_units"},
        "range_units": batch["region_year_units"],
        "plan": plan_identity,
        "openapi_contract": openapi_contract,
        "request_ceiling": batch["request_ceiling"],
        "request_count": fetched["request_count"],
        "request_ledger": fetched["request_ledger"],
        "responses": response_files,
        "batch_definition": {
            "path": "batch-definition.json",
            "sha256": sha256_path(output_dir / "batch-definition.json"),
            "size": (output_dir / "batch-definition.json").stat().st_size,
            "schema_version": DEFINITION_SCHEMA_VERSION,
        },
        "checkpoint": {
            "path": "checkpoint.json",
            "sha256": sha256_path(output_dir / "checkpoint.json"),
            "size": (output_dir / "checkpoint.json").stat().st_size,
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "status": "complete",
            "cumulative_request_count": fetched["request_count"],
        },
        "normalized": {
            "path": str(normalized_path.relative_to(output_dir)),
            "sha256": sha256_path(normalized_path),
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
    manifest_path = output_dir / "batch-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    _atomic_write(output_dir / marker, (sha256_path(manifest_path) + "\n").encode("ascii"))
    return manifest


if __name__ == "__main__":
    raise SystemExit(
        "no standalone network entry point; use the reviewed bulk execution ledger wrapper"
    )

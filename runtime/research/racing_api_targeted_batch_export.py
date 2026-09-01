#!/usr/bin/env python3
"""可断点续跑的 targeted-horse seed 批次编排器。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Mapping

from racing_api_content_pool import ContentAddressedPool, POOL_SCHEMA_VERSION
from racing_api_horse_export import (
    RacingApiClient,
    RacingApiError,
    RacingApiSemanticGap,
    SAFE_STOP_EXIT_CODE,
    _atomic_write,
    _enabled,
    _reject_duplicate_json_keys,
    _reject_non_finite_json_constant,
    _require_empty_output,
    _sha256_path,
    add_exclusive_account_budget_args,
    add_openapi_fingerprint_args,
    build_exclusive_account_budget,
    canonical_json,
    load_openapi_fingerprint,
    openapi_contract_manifest,
    run_targeted_seed_artifact,
)


SHA256_RE = re.compile(r"[0-9a-f]{64}$")


class BatchRequestCache:
    """Deduplicate identical GETs within one bounded batch process.

    The wrapped client remains the authority for request ceilings, account-level
    throttling, retries and ledgers.  Cache entries never survive a process
    restart; resume therefore keeps the conservative request ceiling for all
    remaining seeds.
    """

    def __init__(self, client: object):
        self.client = client
        self._responses: dict[tuple[str, bool], object] = {}
        self.hit_count = 0

    def __getattr__(self, name: str):
        return getattr(self.client, name)

    def request_json(self, url: str, *, allow_not_found: bool = False):
        key = (url, allow_not_found)
        if key in self._responses:
            self.hit_count += 1
            return copy.deepcopy(self._responses[key])
        payload = self.client.request_json(url, allow_not_found=allow_not_found)
        self._responses[key] = copy.deepcopy(payload)
        return copy.deepcopy(payload)

    @property
    def entry_count(self) -> int:
        return len(self._responses)


def targeted_request_ceiling(
    *,
    seed_count: int,
    max_search_candidates: int,
    max_results_pages_per_horse: int,
    max_parent_profiles: int,
    content_pool_schema_version: str = POOL_SCHEMA_VERSION,
) -> int:
    values = (
        seed_count,
        max_search_candidates,
        max_results_pages_per_horse,
        max_parent_profiles,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("targeted batch limits must be integers")
    if seed_count < 0 or max_search_candidates < 1 or max_results_pages_per_horse < 1:
        raise ValueError("targeted batch limits are invalid")
    if not 0 <= max_parent_profiles <= 2:
        raise ValueError("max_parent_profiles must be between 0 and 2")
    if content_pool_schema_version != POOL_SCHEMA_VERSION:
        raise ValueError("content pool schema version drift")
    per_seed = (
        1
        + max_search_candidates * max_results_pages_per_horse
        + 2
        + 2 * max_parent_profiles
    )
    return seed_count * per_seed


def seed_request_ceiling(
    seed: Mapping[str, object],
    *,
    max_search_candidates: int,
    max_results_pages_per_horse: int,
    max_parent_profiles: int,
) -> int:
    schema_version = seed.get("schema_version")
    if schema_version in {"targeted-horse-seed.v1", "targeted-horse-seed.v2"}:
        return targeted_request_ceiling(
            seed_count=1,
            max_search_candidates=max_search_candidates,
            max_results_pages_per_horse=max_results_pages_per_horse,
            max_parent_profiles=max_parent_profiles,
        )
    if schema_version in {
        "targeted-runner-stable-id-seed.v1",
        "targeted-runner-stable-id-seed.v2",
    }:
        return max_results_pages_per_horse + 2 + 2 * max_parent_profiles
    raise ValueError("targeted seed contract drift")


def batch_request_ceiling(
    seeds: list[Mapping[str, object]],
    *,
    max_search_candidates: int,
    max_results_pages_per_horse: int,
    max_parent_profiles: int,
) -> int:
    return sum(
        seed_request_ceiling(
            seed,
            max_search_candidates=max_search_candidates,
            max_results_pages_per_horse=max_results_pages_per_horse,
            max_parent_profiles=max_parent_profiles,
        )
        for seed in seeds
    )


def _load_seed_ledger(path: Path, approved_sha256: str) -> tuple[list[dict], dict]:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError("seed ledger must be a regular non-symlink file")
    actual_sha = _sha256_path(resolved)
    if not SHA256_RE.fullmatch(approved_sha256) or actual_sha != approved_sha256:
        raise ValueError("approved seed ledger SHA-256 mismatch")
    seeds = []
    seen_ids = set()
    for line_number, line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            seed = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_non_finite_json_constant,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid seed JSONL at line {line_number}") from exc
        if not isinstance(seed, dict) or seed.get("schema_version") not in {
            "targeted-horse-seed.v1",
            "targeted-horse-seed.v2",
            "targeted-runner-stable-id-seed.v1",
            "targeted-runner-stable-id-seed.v2",
        }:
            raise ValueError(f"targeted seed contract drift at line {line_number}")
        seed_id = str(seed.get("seed_id") or "").strip()
        if not seed_id or seed_id in seen_ids:
            raise ValueError("seed_id must be present and unique")
        if seed.get("schema_version") == "targeted-horse-seed.v2":
            target = seed.get("target")
            if not isinstance(target, Mapping) or any(
                not str(target.get(field) or "").strip()
                for field in (
                    "year",
                    "edition_year",
                    "country_region",
                    "canonical_name_original",
                    "racecourse",
                    "grade_text",
                    "discipline",
                )
            ):
                raise ValueError(f"v2 targeted seed identity drift at line {line_number}")
        seen_ids.add(seed_id)
        seeds.append(seed)
    if not seeds:
        raise ValueError("seed ledger is empty")
    return seeds, {
        "path": str(resolved),
        "sha256": actual_sha,
        "size": resolved.stat().st_size,
        "rows": len(seeds),
    }


def _read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required batch file is missing: {path.name}")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_finite_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid batch JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"batch JSON root must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    _atomic_write(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _definition_parameters(
    *,
    max_search_candidates: int,
    max_results_pages_per_horse: int,
    max_parent_profiles: int,
    openapi_fingerprint_identity: Mapping[str, object],
) -> dict:
    return {
        "max_search_candidates": max_search_candidates,
        "max_results_pages_per_horse": max_results_pages_per_horse,
        "max_parent_profiles": max_parent_profiles,
        "content_pool_schema_version": POOL_SCHEMA_VERSION,
        "openapi_contract": openapi_contract_manifest(openapi_fingerprint_identity),
    }


def _initialize_batch(
    *,
    output_dir: Path,
    seeds: list[dict],
    ledger_identity: dict,
    parameters: dict,
) -> tuple[dict, dict]:
    _require_empty_output(output_dir)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_dir.chmod(0o700)
    seed_entries = []
    for ordinal, seed in enumerate(seeds, 1):
        payload = f"{canonical_json(seed)}\n".encode("utf-8")
        seed_digest = hashlib.sha256(payload).hexdigest()
        relative = Path("seeds") / f"{ordinal:05d}-{seed_digest[:12]}.json"
        path = output_dir / relative
        _atomic_write(path, payload)
        seed_entries.append(
            {
                "ordinal": ordinal,
                "seed_id": seed["seed_id"],
                "path": str(relative),
                "sha256": seed_digest,
                "size": len(payload),
            }
        )
    definition = {
        "schema_version": "targeted-horse-batch-definition.v1",
        "database_writes": 0,
        "seed_ledger": ledger_identity,
        "parameters": parameters,
        "seeds": seed_entries,
    }
    _write_json(output_dir / "batch-definition.json", definition)
    checkpoint = {
        "schema_version": "targeted-horse-batch-checkpoint.v1",
        "status": "running",
        "completed": {},
        "gaps": {},
        "last_error": None,
    }
    _write_json(output_dir / "checkpoint.json", checkpoint)
    return definition, checkpoint


def _load_existing_batch(
    *,
    output_dir: Path,
    ledger_identity: dict,
    parameters: dict,
) -> tuple[dict, dict]:
    root = output_dir.resolve(strict=True)
    if output_dir.is_symlink() or not root.is_dir():
        raise ValueError("batch output must be a non-symlink directory")
    definition = _read_json(root / "batch-definition.json")
    checkpoint = _read_json(root / "checkpoint.json")
    if (
        definition.get("schema_version") != "targeted-horse-batch-definition.v1"
        or definition.get("seed_ledger") != ledger_identity
        or definition.get("parameters") != parameters
    ):
        raise ValueError("batch definition drift")
    entries = definition.get("seeds")
    if not isinstance(entries, list):
        raise ValueError("batch seed definitions are missing")
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("batch seed definition must be an object")
        path = root / str(entry.get("path") or "")
        try:
            path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise ValueError("batch seed path escapes output root") from exc
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != entry.get("size")
            or _sha256_path(path) != entry.get("sha256")
        ):
            raise ValueError("batch seed identity mismatch")
    completed = checkpoint.get("completed")
    gaps = checkpoint.get("gaps", {})
    if (
        checkpoint.get("schema_version") != "targeted-horse-batch-checkpoint.v1"
        or not isinstance(completed, dict)
        or not isinstance(gaps, dict)
        or set(completed) & set(gaps)
    ):
        raise ValueError("batch checkpoint drift")
    checkpoint["gaps"] = gaps
    for seed_id, receipt in completed.items():
        if not isinstance(receipt, Mapping):
            raise ValueError("batch completion receipt must be an object")
        artifact_dir = root / str(receipt.get("artifact_dir") or "")
        try:
            artifact_dir.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise ValueError("batch receipt path escapes output root") from exc
        manifest_path = artifact_dir / "run-manifest.json"
        complete_path = artifact_dir / "COMPLETE"
        if (
            artifact_dir.is_symlink()
            or not manifest_path.is_file()
            or not complete_path.is_file()
            or _sha256_path(manifest_path) != receipt.get("manifest_sha256")
            or complete_path.read_text(encoding="ascii").strip() != receipt.get("manifest_sha256")
        ):
            raise ValueError(f"completed seed artifact identity mismatch: {seed_id}")
    for seed_id, receipt in gaps.items():
        if not isinstance(receipt, Mapping):
            raise ValueError("batch gap receipt must be an object")
        artifact_dir = root / str(receipt.get("artifact_dir") or "")
        try:
            artifact_dir.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise ValueError("batch gap path escapes output root") from exc
        failure_path = artifact_dir / "run-failure.json"
        failed_path = artifact_dir / "FAILED"
        if (
            artifact_dir.is_symlink()
            or not failure_path.is_file()
            or not failed_path.is_file()
            or _sha256_path(failure_path) != receipt.get("failure_sha256")
            or failed_path.read_text(encoding="ascii").strip()
            != receipt.get("failure_sha256")
            or receipt.get("gap_code") != "target_occurrence_identity_unresolved"
        ):
            raise ValueError(f"gap seed artifact identity mismatch: {seed_id}")
    return definition, checkpoint


def run_targeted_batch_artifact(
    *,
    seed_ledger_path: Path,
    approved_seed_ledger_sha256: str,
    output_dir: Path,
    client: object,
    max_search_candidates: int,
    max_results_pages_per_horse: int,
    max_parent_profiles: int,
    openapi_fingerprint_identity: Mapping[str, object],
    resume: bool = False,
) -> dict:
    seeds, ledger_identity = _load_seed_ledger(
        seed_ledger_path,
        approved_seed_ledger_sha256,
    )
    parameters = _definition_parameters(
        max_search_candidates=max_search_candidates,
        max_results_pages_per_horse=max_results_pages_per_horse,
        max_parent_profiles=max_parent_profiles,
        openapi_fingerprint_identity=openapi_fingerprint_identity,
    )
    if resume:
        definition, checkpoint = _load_existing_batch(
            output_dir=output_dir,
            ledger_identity=ledger_identity,
            parameters=parameters,
        )
    else:
        definition, checkpoint = _initialize_batch(
            output_dir=output_dir,
            seeds=seeds,
            ledger_identity=ledger_identity,
            parameters=parameters,
        )
    completed = checkpoint["completed"]
    gaps = checkpoint["gaps"]
    if (
        len(completed) + len(gaps) == len(seeds)
        and (output_dir / "COMPLETE").is_file()
    ):
        manifest_path = output_dir / "batch-manifest.json"
        complete_path = output_dir / "COMPLETE"
        final_manifest = _read_json(manifest_path)
        pool_identity = final_manifest.get("content_pool")
        pool_manifest_path = output_dir / "content-pool-manifest.json"
        if (
            complete_path.is_symlink()
            or complete_path.read_text(encoding="ascii").strip()
            != _sha256_path(manifest_path)
            or not isinstance(pool_identity, dict)
            or pool_identity.get("path") != pool_manifest_path.name
            or pool_identity.get("sha256") != _sha256_path(pool_manifest_path)
        ):
            raise ValueError("batch COMPLETE marker does not bind final manifest")
        return {**final_manifest, "status": "replayed", "database_writes": 0}
    content_pool = ContentAddressedPool(output_dir / "objects")
    remaining = [
        entry
        for entry in definition["seeds"]
        if entry["seed_id"] not in completed and entry["seed_id"] not in gaps
    ]
    seeds_by_id = {seed["seed_id"]: seed for seed in seeds}
    expected_ceiling = batch_request_ceiling(
        [seeds_by_id[entry["seed_id"]] for entry in remaining],
        max_search_candidates=max_search_candidates,
        max_results_pages_per_horse=max_results_pages_per_horse,
        max_parent_profiles=max_parent_profiles,
    )
    if getattr(client, "request_ceiling", None) != expected_ceiling:
        raise ValueError(
            f"client request ceiling must exactly match remaining batch plan: {expected_ceiling}"
        )
    request_count_before = int(getattr(client, "request_count", 0))
    cached_client = BatchRequestCache(client)
    try:
        for entry in remaining:
            seed_id = entry["seed_id"]
            attempt_root = output_dir / "attempts" / f"{entry['ordinal']:05d}-{entry['sha256'][:12]}"
            attempt_number = len(list(attempt_root.glob("attempt-*"))) + 1 if attempt_root.exists() else 1
            artifact_dir = attempt_root / f"attempt-{attempt_number:03d}"
            try:
                manifest = run_targeted_seed_artifact(
                    seed_path=output_dir / entry["path"],
                    approved_seed_sha256=entry["sha256"],
                    output_dir=artifact_dir,
                    client=cached_client,
                    max_search_candidates=max_search_candidates,
                    max_results_pages_per_horse=max_results_pages_per_horse,
                    max_parent_profiles=max_parent_profiles,
                    openapi_fingerprint_identity=openapi_fingerprint_identity,
                    content_pool=content_pool,
                )
            except RacingApiSemanticGap as exc:
                failure_path = artifact_dir / "run-failure.json"
                failed_path = artifact_dir / "FAILED"
                failure_sha = _sha256_path(failure_path)
                if (
                    not failed_path.is_file()
                    or failed_path.read_text(encoding="ascii").strip()
                    != failure_sha
                ):
                    raise ValueError("semantic gap failure artifact drift") from exc
                gaps[seed_id] = {
                    "artifact_dir": str(artifact_dir.relative_to(output_dir)),
                    "failure_sha256": failure_sha,
                    "seed_sha256": entry["sha256"],
                    "gap_code": exc.code,
                }
                checkpoint.update(
                    status="running",
                    completed=completed,
                    gaps=gaps,
                    last_error=None,
                )
                _write_json(output_dir / "checkpoint.json", checkpoint)
                continue
            manifest_path = artifact_dir / "run-manifest.json"
            completed[seed_id] = {
                "artifact_dir": str(artifact_dir.relative_to(output_dir)),
                "manifest_sha256": _sha256_path(manifest_path),
                "seed_sha256": entry["sha256"],
                "horse_id": manifest["result_summary"]["horse_id"],
            }
            checkpoint.update(
                status="running",
                completed=completed,
                gaps=gaps,
                last_error=None,
            )
            _write_json(output_dir / "checkpoint.json", checkpoint)
    except Exception as exc:
        checkpoint.update(
            status="safe_stopped",
            completed=completed,
            gaps=gaps,
            last_error={"type": type(exc).__name__, "message": str(exc)},
        )
        _write_json(output_dir / "checkpoint.json", checkpoint)
        raise
    request_count_after = int(getattr(client, "request_count", request_count_before))
    pool_manifest = content_pool.snapshot()
    pool_manifest_path = output_dir / "content-pool-manifest.json"
    _write_json(pool_manifest_path, pool_manifest)
    final_manifest = {
        "schema_version": "targeted-horse-batch-run.v1",
        "status": "complete" if not gaps else "complete_with_gaps",
        "database_writes": 0,
        "seed_ledger": ledger_identity,
        "parameters": parameters,
        "planned_seed_count": len(seeds),
        "completed_seed_count": len(completed),
        "gap_seed_count": len(gaps),
        "gaps": gaps,
        "request_ceiling": expected_ceiling,
        "request_count": request_count_after - request_count_before,
        "request_cache": {
            "scope": "single_batch_process_only",
            "entry_count": cached_client.entry_count,
            "hit_count": cached_client.hit_count,
            "persistent_across_resume": False,
        },
        "completed": completed,
        "content_pool": {
            "path": pool_manifest_path.name,
            "sha256": _sha256_path(pool_manifest_path),
            "size": pool_manifest_path.stat().st_size,
            "object_count": pool_manifest["object_count"],
            "entry_count": pool_manifest["entry_count"],
        },
    }
    _write_json(output_dir / "batch-manifest.json", final_manifest)
    checkpoint.update(
        status=final_manifest["status"],
        completed=completed,
        gaps=gaps,
        last_error=None,
    )
    _write_json(output_dir / "checkpoint.json", checkpoint)
    _atomic_write(
        output_dir / "COMPLETE",
        f"{_sha256_path(output_dir / 'batch-manifest.json')}\n".encode("ascii"),
    )
    return final_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-ledger", type=Path, required=True)
    parser.add_argument("--approved-seed-ledger-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-search-candidates", type=int, default=10)
    parser.add_argument("--max-results-pages-per-horse", type=int, default=5)
    parser.add_argument("--max-parent-profiles", type=int, default=2)
    parser.add_argument("--request-ceiling", type=int, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--batch-plan-root", type=Path, required=True)
    parser.add_argument("--approved-plan-manifest-sha256", required=True)
    parser.add_argument("--approved-batch-plan-sha256", required=True)
    parser.add_argument("--execution-ledger", type=Path, required=True)
    parser.add_argument("--g3-approval-root", type=Path, required=True)
    parser.add_argument("--approved-g3-manifest-sha256", required=True)
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
    try:
        openapi_fingerprint_identity = load_openapi_fingerprint(
            args.openapi_fingerprint,
            args.approved_openapi_fingerprint_sha256,
        )
    except (OSError, ValueError) as exc:
        print(f"safe-stop: {exc}", file=sys.stderr)
        return SAFE_STOP_EXIT_CODE
    username = os.environ.get("RACING_API_USERNAME", "")
    password = os.environ.get("RACING_API_PASSWORD", "")
    if not username or not password:
        print("safe-stop: Racing API credentials are required", file=sys.stderr)
        return SAFE_STOP_EXIT_CODE
    try:
        from racing_api_targeted_batch_execution_ledger import (
            claim_batch_execution,
            complete_batch_execution,
            mark_batch_safe_stopped,
        )
    except ImportError as exc:  # pragma: no cover - packaging/runtime failure
        print(f"safe-stop: execution ledger module unavailable: {exc}", file=sys.stderr)
        return SAFE_STOP_EXIT_CODE

    plan_args = {
        "plan_root": args.batch_plan_root,
        "expected_plan_manifest_sha256": args.approved_plan_manifest_sha256,
        "expected_batch_plan_sha256": args.approved_batch_plan_sha256,
        "execution_ledger_path": args.execution_ledger,
    }
    claim = None
    account_budget = None
    client = None
    try:
        claim = claim_batch_execution(
            **plan_args,
            approval_root=args.g3_approval_root,
            approved_g3_manifest_sha256=args.approved_g3_manifest_sha256,
            exclusive_proof_path=args.exclusive_account_proof,
            exclusive_proof_sha256=args.exclusive_account_proof_sha256,
            seed_ledger_path=args.seed_ledger,
            output_dir=args.output_dir,
            account_budget_root=args.account_budget_root,
            credential_alias=args.credential_alias,
            account_scope_id=args.account_scope_id,
            account_scope_manifest_sha256=args.account_scope_manifest_sha256,
            request_ceiling=args.request_ceiling,
            account_request_ceiling=args.account_request_ceiling,
            max_search_candidates=args.max_search_candidates,
            max_results_pages_per_horse=args.max_results_pages_per_horse,
            max_parent_profiles=args.max_parent_profiles,
            openapi_fingerprint_path=args.openapi_fingerprint,
            approved_openapi_fingerprint_sha256=args.approved_openapi_fingerprint_sha256,
            resume=args.resume,
        )
        account_budget = build_exclusive_account_budget(args)
        client = RacingApiClient(
            username=username,
            password=password,
            request_ceiling=args.request_ceiling,
            min_interval_seconds=0,
            account_budget=account_budget,
        )
        manifest = run_targeted_batch_artifact(
            seed_ledger_path=args.seed_ledger,
            approved_seed_ledger_sha256=args.approved_seed_ledger_sha256,
            output_dir=args.output_dir,
            client=client,
            max_search_candidates=args.max_search_candidates,
            max_results_pages_per_horse=args.max_results_pages_per_horse,
            max_parent_profiles=args.max_parent_profiles,
            openapi_fingerprint_identity=openapi_fingerprint_identity,
            resume=args.resume,
        )
    except (RacingApiError, OSError, ValueError) as exc:
        if claim is not None:
            account_state = args.account_budget_root / "account-budget.json"
            request_count = int(getattr(client, "request_count", 0))
            try:
                if account_budget is not None:
                    request_count = int(account_budget.snapshot()["request_count"])
                mark_batch_safe_stopped(
                    **plan_args,
                    claim_token=claim["claim_token"],
                    request_count=request_count,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    account_budget_state_path=(account_state if account_state.exists() else None),
                )
            except (OSError, ValueError) as ledger_exc:
                print(
                    f"safe-stop ledger recording failed: {ledger_exc}",
                    file=sys.stderr,
                )
        print(f"safe-stop: {exc}", file=sys.stderr)
        return SAFE_STOP_EXIT_CODE
    try:
        completed = complete_batch_execution(
            **plan_args,
            claim_token=claim["claim_token"],
            batch_manifest_path=args.output_dir / "batch-manifest.json",
        )
    except (OSError, ValueError) as exc:
        print(
            "safe-stop: network artifact is complete but execution-ledger completion "
            f"must be repaired without replay: {exc}",
            file=sys.stderr,
        )
        return SAFE_STOP_EXIT_CODE
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "batch_id": completed["batch_id"],
                "completed_seed_count": manifest["completed_seed_count"],
                "request_count": manifest["request_count"],
                "total_request_count": completed["total_request_count"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

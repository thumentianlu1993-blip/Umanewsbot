#!/usr/bin/env python3
"""Audit the exact COMPLETE-bulk-run to stable-ledger postprocess frontier.

Every completed bulk batch must bind exactly one deterministic child stable
ledger before the frozen bulk-plan batch set can be merged globally.  This command is
read-only: it performs no network requests, creates no files, and writes no
database rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping


RESEARCH_ROOT = Path(__file__).resolve().parent
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))

from build_stable_id_reconciliation_coverage import (  # noqa: E402
    _bulk_component,
    _stable_occurrences,
)
from prepare_held_census_tra_reconciliation import (  # noqa: E402
    load_stable_runner_ledger,
)
from prepare_held_winner_seed_extension import (  # noqa: E402
    canonical_json,
    sha256_path,
)
from racing_api_bulk_range_execution_ledger import (  # noqa: E402
    _load_execution_ledger_read_only,
    _load_plan,
)


SCHEMA_VERSION = "racing-api-bulk-stable-postprocess-readiness.v1"


class BulkStablePostprocessReadinessError(ValueError):
    pass


def _stable_parent(path: Path) -> tuple[Path, list[Path]]:
    if not path.is_absolute():
        raise BulkStablePostprocessReadinessError(
            "stable ledger parent must be an absolute path"
        )
    if path.is_symlink():
        raise BulkStablePostprocessReadinessError(
            "stable ledger parent must not be a symlink"
        )
    if not path.exists():
        return path, []
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise BulkStablePostprocessReadinessError(
            "stable ledger parent must be a directory"
        )
    members = list(resolved.iterdir())
    for member in members:
        if member.is_symlink() or not member.is_dir():
            raise BulkStablePostprocessReadinessError(
                "stable ledger parent contains an unexpected member"
            )
    return resolved, members


def _completed_bulk_source(entry: Mapping[str, object]) -> dict:
    root = Path(str(entry.get("output_dir") or "")).resolve(strict=True)
    return {
        "root": str(root),
        "manifest_sha256": str(entry.get("batch_manifest_sha256") or ""),
        "batch_id": str(entry.get("batch_id") or ""),
    }


def audit_bulk_stable_postprocess_readiness(
    *,
    plan_root: Path,
    expected_plan_manifest_sha256: str,
    expected_batch_plan_sha256: str,
    execution_ledger_path: Path,
    stable_ledger_parent: Path,
) -> dict:
    """Return a replay-validated, zero-write postprocess frontier."""

    try:
        plan = _load_plan(
            plan_root=plan_root,
            expected_manifest_sha256=expected_plan_manifest_sha256,
            expected_plan_sha256=expected_batch_plan_sha256,
        )
        ledger = _load_execution_ledger_read_only(execution_ledger_path, plan)
        stable_parent, members = _stable_parent(stable_ledger_parent)
    except (OSError, TypeError, ValueError) as exc:
        raise BulkStablePostprocessReadinessError(str(exc)) from exc

    completed = ledger["completed"]
    completed_by_batch = {
        str(entry["batch_id"]): entry for entry in completed
    }
    member_by_batch = {member.name: member for member in members}
    if len(member_by_batch) != len(members):
        raise BulkStablePostprocessReadinessError(
            "stable ledger child identity is duplicated"
        )
    unexpected = sorted(set(member_by_batch) - set(completed_by_batch))
    if unexpected:
        raise BulkStablePostprocessReadinessError(
            "stable ledger parent contains a child outside completed bulk batches: "
            + ", ".join(unexpected)
        )

    validated = []
    missing = []
    for entry in completed:
        batch_id = str(entry["batch_id"])
        stable_root = member_by_batch.get(batch_id)
        if stable_root is None:
            missing.append(entry)
            continue
        manifest_path = stable_root / "manifest.json"
        try:
            manifest_sha = sha256_path(manifest_path)
            stable_rows, stable_identity = load_stable_runner_ledger(
                stable_root,
                approved_manifest_sha256=manifest_sha,
            )
            source_bulk_run = stable_identity.get("source_bulk_run")
            expected_source = _completed_bulk_source(entry)
            if (
                stable_identity.get("source_route") != "bulk_results"
                or not isinstance(source_bulk_run, Mapping)
                or source_bulk_run.get("root") != expected_source["root"]
                or source_bulk_run.get("manifest_sha256")
                != expected_source["manifest_sha256"]
                or source_bulk_run.get("batch_id") != expected_source["batch_id"]
            ):
                raise BulkStablePostprocessReadinessError(
                    "stable ledger does not bind its completed bulk receipt"
                )
            stable_occurrences = _stable_occurrences(stable_rows)
            binding_rows, component = _bulk_component(
                Path(expected_source["root"]),
                expected_manifest_sha256=expected_source["manifest_sha256"],
                allowed_stable_identities={
                    (stable_identity["root"], stable_identity["manifest_sha256"])
                },
                merged_occurrences=stable_occurrences,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise BulkStablePostprocessReadinessError(
                f"stable ledger validation failed for {batch_id}: {exc}"
            ) from exc
        if (
            component.get("source_stable_runner_ledger") != stable_identity
            or component.get("binding_rows") != len(binding_rows)
            or len(binding_rows) != len(stable_occurrences)
        ):
            raise BulkStablePostprocessReadinessError(
                f"stable ledger conservation drift for {batch_id}"
            )
        validated.append(
            {
                "ordinal": entry["ordinal"],
                "batch_id": batch_id,
                "bulk_run_root": expected_source["root"],
                "bulk_run_manifest_sha256": expected_source["manifest_sha256"],
                "stable_ledger_root": stable_identity["root"],
                "stable_ledger_manifest_sha256": stable_identity[
                    "manifest_sha256"
                ],
                "stable_horse_rows": stable_identity["stable_horse_rows"],
                "actual_starter_occurrence_count": len(binding_rows),
            }
        )

    plan_batch_count = len(plan["batches"])
    active = ledger.get("active")
    if missing:
        status = "stable_postprocess_required"
    elif len(completed) == plan_batch_count and active is None:
        status = "ready_for_global_stable_merge"
    else:
        status = "waiting_for_bulk_completion"

    next_postprocess = None
    if missing:
        entry = missing[0]
        batch_id = str(entry["batch_id"])
        output_root = stable_parent / batch_id
        next_postprocess = {
            "ordinal": entry["ordinal"],
            "batch_id": batch_id,
            "argv": [
                "python3",
                "runtime/research/build_bulk_target_runner_stable_id_ledger.py",
                "--bulk-run-dir",
                str(Path(str(entry["output_dir"])).resolve(strict=True)),
                "--approved-bulk-run-manifest-sha256",
                str(entry["batch_manifest_sha256"]),
                "--output-dir",
                str(output_root),
            ],
        }

    merge_inputs = None
    if status == "ready_for_global_stable_merge":
        merge_inputs = [
            {
                "stable_runner_ledger_root": row["stable_ledger_root"],
                "approved_stable_runner_manifest_sha256": row[
                    "stable_ledger_manifest_sha256"
                ],
            }
            for row in validated
        ]

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "network_requests": 0,
        "database_writes": 0,
        "plan": {
            "root": str(plan["root"]),
            "manifest_sha256": plan["manifest_sha256"],
            "batch_plan_sha256": plan["plan_sha256"],
            "batch_count": plan_batch_count,
        },
        "execution_ledger": {
            "path": str(execution_ledger_path.resolve(strict=True)),
            "sha256": sha256_path(execution_ledger_path.resolve(strict=True)),
            "completed_batches": len(completed),
            "active_batch_id": (
                str(active.get("batch_id") or "")
                if isinstance(active, Mapping)
                else None
            ),
        },
        "stable_ledger_parent": str(stable_parent),
        "counts": {
            "planned_batches": plan_batch_count,
            "completed_bulk_batches": len(completed),
            "validated_stable_ledgers": len(validated),
            "missing_stable_ledgers": len(missing),
        },
        "validated_stable_ledgers": validated,
        "missing_batch_ids": [str(entry["batch_id"]) for entry in missing],
        "next_postprocess": next_postprocess,
        "global_merge_inputs": merge_inputs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-root", type=Path, required=True)
    parser.add_argument("--expected-plan-manifest-sha256", required=True)
    parser.add_argument("--expected-batch-plan-sha256", required=True)
    parser.add_argument("--execution-ledger", type=Path, required=True)
    parser.add_argument("--stable-ledger-parent", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = audit_bulk_stable_postprocess_readiness(
            plan_root=args.plan_root,
            expected_plan_manifest_sha256=args.expected_plan_manifest_sha256,
            expected_batch_plan_sha256=args.expected_batch_plan_sha256,
            execution_ledger_path=args.execution_ledger,
            stable_ledger_parent=args.stable_ledger_parent,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(f"safe-stop: {exc}", file=sys.stderr)
        return 75
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

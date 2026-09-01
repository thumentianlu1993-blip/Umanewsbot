#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL object required at {path}:{line_number}")
        rows.append(value)
    return rows


def _jsonl_bytes(rows: Iterable[Mapping[str, object]]) -> bytes:
    return b"".join(_canonical_bytes(dict(row)) for row in rows)


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o600)


def _identity(path: Path, *, rows: int | None = None) -> dict:
    result = {
        "path": path.name,
        "sha256": _sha256_path(path),
        "size": path.stat().st_size,
    }
    if rows is not None:
        result["rows"] = rows
    return result


def _validate_source_seed_root(root: Path) -> tuple[dict, str, list[dict]]:
    manifest_path = root / "seed-ledger-manifest.json"
    manifest = _read_json(manifest_path)
    manifest_sha = _sha256_path(manifest_path)
    if (
        manifest.get("schema_version") != "targeted-horse-seed-ledger.v1"
        or manifest.get("status") != "complete"
        or manifest.get("database_writes") != 0
        or manifest.get("network_requests") != 0
        or (root / "COMPLETE").read_text(encoding="ascii").strip() != manifest_sha
    ):
        raise ValueError("source approved seed root contract drift")
    ledger_path = root / "targeted-horse-seeds.jsonl"
    ledger = manifest.get("seed_ledger")
    rows = _read_jsonl(ledger_path)
    if (
        not isinstance(ledger, dict)
        or ledger.get("sha256") != _sha256_path(ledger_path)
        or ledger.get("size") != ledger_path.stat().st_size
        or ledger.get("rows") != len(rows)
        or manifest.get("seed_count") != len(rows)
    ):
        raise ValueError("source approved seed ledger identity drift")
    return manifest, manifest_sha, rows


def _profile_fallback_seed(row: Mapping[str, object]) -> dict:
    result = dict(row)
    target = result.get("target")
    if (
        result.get("schema_version") != "targeted-horse-seed.v2"
        or result.get("source_authority") != "human_reviewed_reference"
        or str(result.get("expected_finish_position")) != "1"
        or not isinstance(target, dict)
        or target.get("year") != target.get("edition_year")
    ):
        raise ValueError(f"seed is not an eligible reviewed winner anchor: {result.get('seed_id')}")
    result["allow_profile_only_if_target_missing"] = True
    return result


def _new_temp_root(destination: Path) -> Path:
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"fresh output path required: {destination}")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    path.chmod(0o700)
    return path


def prepare(
    *,
    source_seed_root: Path,
    source_plan_root: Path,
    output_seed_root: Path,
    output_plan_root: Path,
    decision_source_reference: str,
    reviewed_by: str,
) -> dict:
    source_seed_manifest, source_seed_manifest_sha, source_rows = _validate_source_seed_root(
        source_seed_root
    )
    source_plan_manifest_path = source_plan_root / "batch-plan-manifest.json"
    source_plan_manifest = _read_json(source_plan_manifest_path)
    source_plan_manifest_sha = _sha256_path(source_plan_manifest_path)
    if (
        source_plan_manifest.get("schema_version") != "racing-api-targeted-batch-plan.v1"
        or source_plan_manifest.get("status") != "PROPOSED_NOT_APPROVED"
        or (source_plan_root / "PREPARED").read_text(encoding="ascii").strip()
        != source_plan_manifest_sha
    ):
        raise ValueError("source targeted plan contract drift")

    transformed_rows = [_profile_fallback_seed(row) for row in source_rows]
    transformed_by_id = {str(row.get("seed_id") or ""): row for row in transformed_rows}
    if "" in transformed_by_id or len(transformed_by_id) != len(transformed_rows):
        raise ValueError("source seed IDs are absent or duplicated")

    seed_tmp = _new_temp_root(output_seed_root)
    plan_tmp = _new_temp_root(output_plan_root)
    try:
        seed_ledger_path = seed_tmp / "targeted-horse-seeds.jsonl"
        anchor_path = seed_tmp / "anchor-evidence.jsonl"
        _write(seed_ledger_path, _jsonl_bytes(transformed_rows))
        _write(anchor_path, (source_seed_root / "anchor-evidence.jsonl").read_bytes())
        reviewed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        decision = {
            "schema_version": "pre-2005-profile-fallback-approval-decision.v1",
            "decision": "approve",
            "approval_scope": "EXACT_REVIEWED_WINNER_SEEDS_PROFILE_ONLY_IF_TARGET_OCCURRENCE_MISSING",
            "decision_source_reference": decision_source_reference,
            "reviewed_by": reviewed_by,
            "reviewed_at": reviewed_at,
            "source_seed_manifest_sha256": source_seed_manifest_sha,
            "source_seed_ledger_sha256": source_seed_manifest["seed_ledger"]["sha256"],
            "transformation": "add allow_profile_only_if_target_missing=true only",
            "approved_seed_count": len(transformed_rows),
            "network_authority": "per-batch G3 approval and fresh exclusive proof still required",
            "database_writes": 0,
        }
        decision_path = seed_tmp / "approval-decision.json"
        _write(decision_path, _canonical_bytes(decision))
        seed_manifest = {
            "schema_version": "targeted-horse-seed-ledger.v1",
            "status": "complete",
            "database_writes": 0,
            "network_requests": 0,
            "network_execution_approved": False,
            "source_authority": "human_reviewed_reference",
            "seed_count": len(transformed_rows),
            "seed_ledger": _identity(seed_ledger_path, rows=len(transformed_rows)),
            "anchor_evidence": _identity(anchor_path, rows=len(transformed_rows)),
            "approval_decision": _identity(decision_path),
            "source_seed_artifact": {
                "root": str(source_seed_root.resolve()),
                "manifest_sha256": source_seed_manifest_sha,
                "ledger_sha256": source_seed_manifest["seed_ledger"]["sha256"],
            },
            "profile_fallback_policy": {
                "allowed": True,
                "condition": "reviewed winner anchor plus unique exact-name provider profile and no target occurrence",
                "identity_guessing_allowed": False,
                "unresolved_identity_outcome": "target_occurrence_identity_unresolved semantic gap",
            },
        }
        seed_manifest_path = seed_tmp / "seed-ledger-manifest.json"
        _write(seed_manifest_path, _canonical_bytes(seed_manifest))
        seed_manifest_sha = _sha256_path(seed_manifest_path)
        _write(seed_tmp / "COMPLETE", f"{seed_manifest_sha}\n".encode("ascii"))

        source_plan_path = source_plan_root / "batch-plan.jsonl"
        source_plan_rows = _read_jsonl(source_plan_path)
        if source_plan_manifest["batch_plan"]["sha256"] != _sha256_path(source_plan_path):
            raise ValueError("source targeted batch-plan identity drift")
        plan_rows: list[dict] = []
        seen_seed_ids: set[str] = set()
        for ordinal, source_batch in enumerate(source_plan_rows, 1):
            source_batch_seed_path = source_plan_root / source_batch["seed_ledger"]["path"]
            batch_source_rows = _read_jsonl(source_batch_seed_path)
            batch_rows = []
            for source_row in batch_source_rows:
                seed_id = str(source_row.get("seed_id") or "")
                transformed = transformed_by_id.get(seed_id)
                if transformed is None or seed_id in seen_seed_ids:
                    raise ValueError(f"plan seed identity drift: {seed_id}")
                batch_rows.append(transformed)
                seen_seed_ids.add(seed_id)
            relative = Path("seed-ledgers") / source_batch_seed_path.name
            batch_seed_path = plan_tmp / relative
            _write(batch_seed_path, _jsonl_bytes(batch_rows))
            batch = dict(source_batch)
            batch["not_before_offset_minutes"] = (ordinal - 1) * 5
            batch["seed_ledger"] = {
                "path": str(relative),
                "rows": len(batch_rows),
                "sha256": _sha256_path(batch_seed_path),
                "size": batch_seed_path.stat().st_size,
            }
            plan_rows.append(batch)
        if seen_seed_ids != set(transformed_by_id):
            raise ValueError("targeted plan does not conserve every transformed seed")
        plan_path = plan_tmp / "batch-plan.jsonl"
        _write(plan_path, _jsonl_bytes(plan_rows))
        plan_manifest = dict(source_plan_manifest)
        plan_manifest["parameters"] = dict(source_plan_manifest["parameters"])
        plan_manifest["parameters"]["spacing_minutes"] = 5
        plan_manifest["counts"] = dict(source_plan_manifest["counts"])
        plan_manifest["counts"]["schedule_span_minutes"] = max(0, (len(plan_rows) - 1) * 5)
        plan_manifest["batch_plan"] = _identity(plan_path, rows=len(plan_rows))
        plan_manifest["seed_artifact"] = {
            "root": str(output_seed_root.resolve()),
            "rows": len(transformed_rows),
            "manifest_sha256": seed_manifest_sha,
            "ledger_sha256": _sha256_path(seed_ledger_path),
            "source_manifest_sha256": source_seed_manifest_sha,
        }
        plan_manifest["profile_fallback_amendment"] = {
            "decision_sha256": _sha256_path(decision_path),
            "source_plan_manifest_sha256": source_plan_manifest_sha,
            "spacing_minutes": 5,
            "semantic_gap_code": "target_occurrence_identity_unresolved",
        }
        plan_manifest_path = plan_tmp / "batch-plan-manifest.json"
        _write(plan_manifest_path, _canonical_bytes(plan_manifest))
        plan_manifest_sha = _sha256_path(plan_manifest_path)
        _write(plan_tmp / "PREPARED", f"{plan_manifest_sha}\n".encode("ascii"))

        os.replace(seed_tmp, output_seed_root)
        os.replace(plan_tmp, output_plan_root)
        return {
            "status": "complete",
            "database_writes": 0,
            "network_requests": 0,
            "seed_count": len(transformed_rows),
            "batch_count": len(plan_rows),
            "seed_root": str(output_seed_root),
            "seed_manifest_sha256": seed_manifest_sha,
            "seed_ledger_sha256": _sha256_path(output_seed_root / "targeted-horse-seeds.jsonl"),
            "plan_root": str(output_plan_root),
            "plan_manifest_sha256": plan_manifest_sha,
            "batch_plan_sha256": _sha256_path(output_plan_root / "batch-plan.jsonl"),
        }
    except BaseException:
        shutil.rmtree(seed_tmp, ignore_errors=True)
        shutil.rmtree(plan_tmp, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-seed-root", type=Path, required=True)
    parser.add_argument("--source-plan-root", type=Path, required=True)
    parser.add_argument("--output-seed-root", type=Path, required=True)
    parser.add_argument("--output-plan-root", type=Path, required=True)
    parser.add_argument("--decision-source-reference", required=True)
    parser.add_argument("--reviewed-by", default="project-owner")
    args = parser.parse_args()
    result = prepare(
        source_seed_root=args.source_seed_root,
        source_plan_root=args.source_plan_root,
        output_seed_root=args.output_seed_root,
        output_plan_root=args.output_plan_root,
        decision_source_reference=args.decision_source_reference,
        reviewed_by=args.reviewed_by,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

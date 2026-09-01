#!/usr/bin/env python3
"""Merge exact audited organizer-official winner seeds into a COMPLETE seed ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Mapping


BASE_SCHEMA = "targeted-horse-seed-ledger.v1"
AUDIT_SCHEMAS = {
    "france-galop-bulletin-occurrence-audit.v1",
    "hri-graded-winner-candidate-audit.v1",
}
SEED_SCHEMAS = {"targeted-horse-seed.v1", "targeted-horse-seed.v2"}
GAP_SCHEMA = "graded-winner-anchor-gap.v1"
SHA_RE = re.compile(r"[0-9a-f]{64}")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path: Path, *, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    return resolved


def _json(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(_regular(path, label=label).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _jsonl(path: Path, *, label: str) -> list[dict]:
    rows = []
    try:
        for line_number, line in enumerate(
            _regular(path, label=label).read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{label} row {line_number} is not an object")
            rows.append(row)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    return rows


def _identity(root: Path, value: object, *, label: str) -> tuple[Path, list[dict]]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} identity is missing")
    relative = str(value.get("path") or "")
    if not relative or Path(relative).is_absolute():
        raise ValueError(f"{label} path is invalid")
    path = _regular(root / relative, label=label)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes its artifact root") from exc
    rows = _jsonl(path, label=label)
    if (
        not SHA_RE.fullmatch(str(value.get("sha256") or ""))
        or sha256_path(path) != value.get("sha256")
        or path.stat().st_size != value.get("size")
        or len(rows) != value.get("rows")
    ):
        raise ValueError(f"{label} identity mismatch")
    return path, rows


def _atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def load_base(root: Path, *, approved_manifest_sha256: str) -> tuple[dict, list[dict], list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("base seed root must be a regular directory")
    manifest_path = _regular(resolved / "seed-ledger-manifest.json", label="base manifest")
    manifest = _json(manifest_path, label="base manifest")
    manifest_sha = sha256_path(manifest_path)
    marker = _regular(resolved / "COMPLETE", label="base marker")
    if (
        manifest_sha != approved_manifest_sha256
        or not SHA_RE.fullmatch(approved_manifest_sha256)
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != BASE_SCHEMA
        or manifest.get("status") != "complete"
        or manifest.get("completion_marker") != "COMPLETE"
        or manifest.get("database_writes") != 0
        or manifest.get("network_requests") != 0
    ):
        raise ValueError("base seed artifact contract drift")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ValueError("base outputs are missing")
    _seed_path, seeds = _identity(
        resolved, outputs.get("targeted-horse-seeds.jsonl"), label="base seeds"
    )
    _gap_path, gaps = _identity(
        resolved, outputs.get("semantic-gaps.jsonl"), label="base gaps"
    )
    if (
        any(row.get("schema_version") not in SEED_SCHEMAS for row in seeds)
        or any(row.get("schema_version") != GAP_SCHEMA for row in gaps)
        or len({str(row.get("seed_id") or "") for row in seeds}) != len(seeds)
        or "" in {str(row.get("seed_id") or "") for row in seeds}
        or len({str(row.get("target_key") or "") for row in gaps}) != len(gaps)
    ):
        raise ValueError("base seed/gap row contract drift")
    return manifest, seeds, gaps, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "seed_ledger_sha256": sha256_path(resolved / "targeted-horse-seeds.jsonl"),
        "semantic_gaps_sha256": sha256_path(resolved / "semantic-gaps.jsonl"),
    }


def load_audit(root: Path, *, approved_manifest_sha256: str) -> tuple[list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("audit root must be a regular directory")
    manifest_path = _regular(resolved / "audit-manifest.json", label="audit manifest")
    manifest = _json(manifest_path, label="audit manifest")
    manifest_sha = sha256_path(manifest_path)
    marker = _regular(resolved / "AUDITED_REFERENCE_ONLY", label="audit marker")
    proposal = manifest.get("targeted_seed_proposals")
    if (
        not SHA_RE.fullmatch(approved_manifest_sha256)
        or manifest_sha != approved_manifest_sha256
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") not in AUDIT_SCHEMAS
        or manifest.get("status") != "reference_only_target_review_required"
        or manifest.get("completion_marker") != "AUDITED_REFERENCE_ONLY"
        or manifest.get("approval") is not False
        or manifest.get("database_writes") != 0
        or manifest.get("racing_api_requests") != 0
        or not isinstance(proposal, Mapping)
        or proposal.get("runnable") is not False
    ):
        raise ValueError("official audit contract drift")
    path, rows = _identity(resolved, proposal, label="official seed proposals")
    target_keys = []
    for row in rows:
        target = row.get("target")
        target_key = str(target.get("target_key") or "") if isinstance(target, Mapping) else ""
        if (
            row.get("schema_version") != "targeted-horse-seed.v2"
            or row.get("source_authority") != "organizer_official"
            or row.get("expected_finish_position") != "1"
            or row.get("allow_profile_only_if_target_missing") is not True
            or not target_key
        ):
            raise ValueError("official seed proposal row contract drift")
        target_keys.append(target_key)
    if len(target_keys) != len(set(target_keys)):
        raise ValueError("official audit contains duplicate targets")
    return rows, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "proposal_sha256": sha256_path(path),
        "proposal_rows": len(rows),
        "source_proposal": manifest.get("source_proposal"),
    }


def merge(
    *,
    base_root: Path,
    approved_base_manifest_sha256: str,
    audits: list[tuple[Path, str]],
    output_dir: Path,
) -> dict:
    if output_dir.exists():
        raise ValueError("output directory must not already exist")
    base, seeds, gaps, base_identity = load_base(
        base_root, approved_manifest_sha256=approved_base_manifest_sha256
    )
    gaps_by_key = {str(row["target_key"]): row for row in gaps}
    supplements = []
    audit_identities = []
    selected_keys = set()
    for root, approved_sha in audits:
        rows, identity = load_audit(root, approved_manifest_sha256=approved_sha)
        audit_identities.append(identity)
        for row in rows:
            target_key = str(row["target"]["target_key"])
            if target_key not in gaps_by_key:
                continue
            if target_key in selected_keys:
                raise ValueError("official audits overlap on one semantic gap")
            gap = gaps_by_key[target_key]
            target = row["target"]
            if (
                target.get("country_region") != gap.get("country_region")
                or int(target.get("edition_year") or 0) != int(gap.get("year") or 0)
            ):
                raise ValueError("official seed target does not conserve the semantic gap")
            selected_keys.add(target_key)
            supplements.append(row)
    if not supplements:
        raise ValueError("official audits do not resolve any base semantic gap")
    combined = seeds + sorted(supplements, key=lambda row: str(row["target"]["target_key"]))
    remaining = [row for row in gaps if str(row["target_key"]) not in selected_keys]
    seed_ids = [str(row.get("seed_id") or "") for row in combined]
    if not all(seed_ids) or len(seed_ids) != len(set(seed_ids)):
        raise ValueError("merged seed IDs are missing or duplicated")
    output_dir.mkdir(parents=True, mode=0o700)
    seed_path = output_dir / "targeted-horse-seeds.jsonl"
    gap_path = output_dir / "semantic-gaps.jsonl"
    _atomic(seed_path, "".join(canonical_json(row) + "\n" for row in combined).encode())
    _atomic(gap_path, "".join(canonical_json(row) + "\n" for row in remaining).encode())
    by_region = Counter(str(row["target"]["country_region"]) for row in combined)
    by_source = Counter(str(row.get("source_authority") or "") for row in combined)
    identities = {
        "targeted-horse-seeds.jsonl": {
            "path": seed_path.name,
            "rows": len(combined),
            "sha256": sha256_path(seed_path),
            "size": seed_path.stat().st_size,
        },
        "semantic-gaps.jsonl": {
            "path": gap_path.name,
            "rows": len(remaining),
            "sha256": sha256_path(gap_path),
            "size": gap_path.stat().st_size,
        },
    }
    base_counts = dict(base.get("counts") or {})
    source_counts = Counter(
        {str(key): int(value) for key, value in dict(base_counts.get("by_source") or {}).items()}
    )
    source_counts["france_galop_organizer_official"] += len(supplements)
    base_counts.update(
        {
            "by_region": dict(sorted(by_region.items())),
            "by_source": dict(sorted(source_counts.items())),
            "by_source_authority": dict(sorted(by_source.items())),
            "covered_target_occurrences": int(base_counts.get("covered_target_occurrences") or 0)
            + len(supplements),
            "physical_winner_seeds": len(combined),
            "semantic_gaps": len(remaining),
            "supplemental_organizer_official_seeds": len(supplements),
            "target_occurrences": int(base_counts.get("target_occurrences") or 0),
        }
    )
    if base_counts["covered_target_occurrences"] + len(remaining) != base_counts["target_occurrences"]:
        raise ValueError("merged target occurrence conservation failed")
    manifest = {
        **base,
        "artifact_schema_version": "graded-winner-targeted-seed-artifact.v1",
        "schema_version": BASE_SCHEMA,
        "status": "complete",
        "completion_marker": "COMPLETE",
        "coverage_status": "complete" if not remaining else "complete_with_gaps",
        "database_writes": 0,
        "network_requests": 0,
        "seed_count": len(combined),
        "counts": base_counts,
        "outputs": identities,
        "seed_ledger": identities["targeted-horse-seeds.jsonl"],
        "base_seed_artifact": base_identity,
        "supplemental_official_audits": audit_identities,
        "generator": {
            "path": Path(__file__).name,
            "sha256": sha256_path(Path(__file__).resolve()),
        },
    }
    manifest_path = output_dir / "seed-ledger-manifest.json"
    _atomic(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
    )
    _atomic(output_dir / "COMPLETE", (sha256_path(manifest_path) + "\n").encode("ascii"))
    return manifest


def _audit_binding(value: str) -> tuple[Path, str]:
    try:
        root, sha = value.rsplit("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("audit binding must be ROOT=SHA256") from exc
    if not root or not SHA_RE.fullmatch(sha):
        raise argparse.ArgumentTypeError("audit binding must contain an exact SHA-256")
    return Path(root), sha


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-root", type=Path, required=True)
    parser.add_argument("--approved-base-manifest-sha256", required=True)
    parser.add_argument("--audit", action="append", type=_audit_binding, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = merge(
        base_root=args.base_root,
        approved_base_manifest_sha256=args.approved_base_manifest_sha256,
        audits=args.audit,
        output_dir=args.output_dir,
    )
    print(canonical_json(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build an exact runnable delta across one or more COMPLETE seed artifacts.

Target catalogue keys are the primary occurrence identity.  When a catalogue
key intentionally has multiple physical occurrences (for example split US
divisions), every row must carry a distinct source occurrence ID and the delta
is computed at that finer grain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping


MANIFEST_SCHEMA = "targeted-horse-seed-ledger.v1"
SEED_SCHEMAS = {"targeted-horse-seed.v1", "targeted-horse-seed.v2"}
SHA_RE = re.compile(r"[0-9a-f]{64}$")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _regular(path: Path, *, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    return resolved


def _object(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(_regular(path, label=label).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _rows(path: Path, *, label: str) -> list[dict]:
    rows = []
    try:
        for number, line in enumerate(
            _regular(path, label=label).read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            target = row.get("target") if isinstance(row, Mapping) else None
            if (
                not isinstance(row, dict)
                or row.get("schema_version") not in SEED_SCHEMAS
                or not str(row.get("seed_id") or "")
                or not str(row.get("name") or "")
                or not isinstance(target, Mapping)
                or not str(target.get("target_key") or "")
                or not str(target.get("country_region") or "")
            ):
                raise ValueError(f"{label} row {number} contract drift")
            rows.append(row)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSONL") from exc
    return rows


def load_seed_artifact(root: Path, approved_sha: str) -> tuple[list[dict], dict, dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("seed root must be a regular directory")
    manifest_path = _regular(resolved / "seed-ledger-manifest.json", label="seed manifest")
    marker = _regular(resolved / "COMPLETE", label="seed COMPLETE marker")
    manifest = _object(manifest_path, label="seed manifest")
    manifest_sha = sha256_path(manifest_path)
    ledger_identity = manifest.get("seed_ledger")
    if (
        not SHA_RE.fullmatch(approved_sha)
        or manifest_sha != approved_sha
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != MANIFEST_SCHEMA
        or manifest.get("status") != "complete"
        or manifest.get("completion_marker") != "COMPLETE"
        or manifest.get("database_writes") != 0
        or manifest.get("network_requests") != 0
        or not isinstance(ledger_identity, Mapping)
    ):
        raise ValueError("seed artifact contract drift")
    relative = str(ledger_identity.get("path") or "")
    if not relative or Path(relative).is_absolute():
        raise ValueError("seed ledger identity path is invalid")
    ledger_path = _regular(resolved / relative, label="seed ledger")
    try:
        ledger_path.relative_to(resolved)
    except ValueError as exc:
        raise ValueError("seed ledger escapes artifact root") from exc
    rows = _rows(ledger_path, label="seed ledger")
    seed_ids = [str(row["seed_id"]) for row in rows]
    if (
        not rows
        or len(seed_ids) != len(set(seed_ids))
        or ledger_identity.get("sha256") != sha256_path(ledger_path)
        or ledger_identity.get("size") != ledger_path.stat().st_size
        or ledger_identity.get("rows") != len(rows)
        or manifest.get("seed_count") != len(rows)
    ):
        raise ValueError("seed ledger identity drift")
    identity = {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "ledger_sha256": sha256_path(ledger_path),
        "rows": len(rows),
    }
    return rows, manifest, identity


def _binding(value: str) -> tuple[Path, str]:
    try:
        root, sha = value.rsplit("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("binding must be ROOT=SHA256") from exc
    if not root or not SHA_RE.fullmatch(sha):
        raise argparse.ArgumentTypeError("binding must contain an exact SHA-256")
    return Path(root), sha


def _occurrence_id(row: Mapping[str, object]) -> str:
    return str(row.get("source_occurrence_id") or "").strip()


def _dedupe_candidate_rows(rows: list[dict]) -> list[dict]:
    by_target: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_target[str(row["target"]["target_key"])].append(row)
    result = []
    for target_key in sorted(by_target):
        group = by_target[target_key]
        if len(group) == 1:
            result.extend(group)
            continue
        by_occurrence = {}
        for row in group:
            occurrence = _occurrence_id(row)
            if not occurrence:
                raise ValueError("multi-occurrence target is missing source_occurrence_id")
            previous = by_occurrence.setdefault(occurrence, row)
            if canonical_json(previous) != canonical_json(row):
                raise ValueError("candidate occurrence identity has conflicting rows")
        result.extend(by_occurrence[key] for key in sorted(by_occurrence))
    return result


def extract(
    *,
    candidates: list[tuple[Path, str]],
    already_scheduled: list[tuple[Path, str]],
    output_dir: Path,
) -> dict:
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("output directory must not already exist")
    if not candidates:
        raise ValueError("at least one candidate seed artifact is required")

    candidate_rows = []
    candidate_identities = []
    candidate_manifests = []
    for root, sha in candidates:
        rows, manifest, identity = load_seed_artifact(root, sha)
        candidate_rows.extend(rows)
        candidate_manifests.append(manifest)
        candidate_identities.append(identity)
    candidate_rows = _dedupe_candidate_rows(candidate_rows)

    scheduled_rows = []
    scheduled_identities = []
    for root, sha in already_scheduled:
        rows, _manifest, identity = load_seed_artifact(root, sha)
        scheduled_rows.extend(rows)
        scheduled_identities.append(identity)
    scheduled_rows = _dedupe_candidate_rows(scheduled_rows) if scheduled_rows else []
    scheduled_by_target: dict[str, list[dict]] = defaultdict(list)
    for row in scheduled_rows:
        scheduled_by_target[str(row["target"]["target_key"])].append(row)

    candidate_by_target: dict[str, list[dict]] = defaultdict(list)
    for row in candidate_rows:
        candidate_by_target[str(row["target"]["target_key"])].append(row)
    delta = []
    skipped = 0
    for target_key in sorted(candidate_by_target):
        group = candidate_by_target[target_key]
        prior = scheduled_by_target.get(target_key, [])
        if not prior:
            delta.extend(group)
            continue
        if len(group) == 1 and len(prior) == 1:
            skipped += 1
            continue
        prior_occurrences = {_occurrence_id(row) for row in prior}
        if "" in prior_occurrences or any(not _occurrence_id(row) for row in group):
            raise ValueError("physical occurrence delta cannot be proven from source occurrence IDs")
        for row in group:
            if _occurrence_id(row) in prior_occurrences:
                skipped += 1
            else:
                delta.append(row)
    if not delta:
        raise ValueError("candidate artifacts add no unscheduled target occurrence")
    delta.sort(
        key=lambda row: (
            str(row["target"].get("country_region") or ""),
            int(row["target"].get("edition_year") or row["target"].get("year") or 0),
            str(row["target"].get("target_key") or ""),
            _occurrence_id(row),
        )
    )
    seed_ids = [str(row["seed_id"]) for row in delta]
    if len(seed_ids) != len(set(seed_ids)):
        raise ValueError("execution delta contains duplicate seed IDs")

    output_dir.mkdir(parents=True, mode=0o700)
    ledger_path = output_dir / "targeted-horse-seeds.jsonl"
    _atomic(ledger_path, "".join(canonical_json(row) + "\n" for row in delta).encode())
    ledger_identity = {
        "path": ledger_path.name,
        "rows": len(delta),
        "sha256": sha256_path(ledger_path),
        "size": ledger_path.stat().st_size,
    }
    regions = Counter(str(row["target"]["country_region"]) for row in delta)
    target_ledgers = {
        str(manifest.get("target_ledger_sha256") or "")
        for manifest in candidate_manifests
        if manifest.get("target_ledger_sha256")
    }
    manifest = {
        "artifact_schema_version": "targeted-horse-seed-execution-delta.v1",
        "schema_version": MANIFEST_SCHEMA,
        "status": "complete",
        "completion_marker": "COMPLETE",
        "coverage_status": "candidate_occurrence_delta_complete",
        "database_writes": 0,
        "network_requests": 0,
        "seed_count": len(delta),
        "seed_ledger": ledger_identity,
        "outputs": {"targeted-horse-seeds.jsonl": ledger_identity},
        "counts": {
            "candidate_occurrences": len(candidate_rows),
            "already_scheduled_occurrences": len(scheduled_rows),
            "skipped_existing_occurrences": skipped,
            "physical_winner_seeds": len(delta),
            "by_region": dict(sorted(regions.items())),
        },
        "candidate_seed_artifacts": candidate_identities,
        "already_scheduled_seed_artifacts": scheduled_identities,
        "target_ledger_sha256": next(iter(target_ledgers)) if len(target_ledgers) == 1 else None,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", action="append", type=_binding, required=True)
    parser.add_argument("--already-scheduled", action="append", type=_binding, default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        canonical_json(
            extract(
                candidates=args.candidate,
                already_scheduled=args.already_scheduled,
                output_dir=args.output_dir,
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Extract only newly merged organizer-official targeted horse seeds."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from merge_official_targeted_horse_seed_supplements import (
    canonical_json,
    load_base,
    sha256_path,
)


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


def extract(
    *,
    merged_root: Path,
    approved_merged_manifest_sha256: str,
    output_dir: Path,
) -> dict:
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("output directory must not already exist")
    merged, merged_seeds, _remaining, merged_identity = load_base(
        merged_root,
        approved_manifest_sha256=approved_merged_manifest_sha256,
    )
    base_identity = merged.get("base_seed_artifact")
    if not isinstance(base_identity, dict):
        raise ValueError("merged artifact has no exact base seed binding")
    base_root = Path(str(base_identity.get("root") or ""))
    base_manifest_sha = str(base_identity.get("manifest_sha256") or "")
    _base, base_seeds, _base_gaps, verified_base_identity = load_base(
        base_root,
        approved_manifest_sha256=base_manifest_sha,
    )
    if verified_base_identity != base_identity:
        raise ValueError("merged artifact base seed binding drift")

    base_ids = {str(row.get("seed_id") or "") for row in base_seeds}
    merged_ids = {str(row.get("seed_id") or "") for row in merged_seeds}
    if not base_ids or not base_ids <= merged_ids:
        raise ValueError("merged artifact does not conserve every base seed")
    delta = [row for row in merged_seeds if str(row.get("seed_id") or "") not in base_ids]
    expected_delta = int(
        (merged.get("counts") or {}).get("supplemental_organizer_official_seeds") or 0
    )
    if (
        not delta
        or len(delta) != expected_delta
        or any(row.get("source_authority") != "organizer_official" for row in delta)
        or len({str(row["target"]["target_key"]) for row in delta}) != len(delta)
    ):
        raise ValueError("organizer-official seed delta contract drift")

    delta.sort(key=lambda row: str(row["target"]["target_key"]))
    output_dir.mkdir(parents=True, mode=0o700)
    ledger_path = output_dir / "targeted-horse-seeds.jsonl"
    _atomic(ledger_path, "".join(canonical_json(row) + "\n" for row in delta).encode())
    ledger_identity = {
        "path": ledger_path.name,
        "rows": len(delta),
        "sha256": sha256_path(ledger_path),
        "size": ledger_path.stat().st_size,
    }
    by_region = Counter(str(row["target"]["country_region"]) for row in delta)
    manifest = {
        "artifact_schema_version": "official-targeted-horse-seed-delta.v1",
        "schema_version": "targeted-horse-seed-ledger.v1",
        "status": "complete",
        "completion_marker": "COMPLETE",
        "coverage_status": "supplement_delta_complete",
        "database_writes": 0,
        "network_requests": 0,
        "seed_count": len(delta),
        "seed_ledger": ledger_identity,
        "outputs": {"targeted-horse-seeds.jsonl": ledger_identity},
        "counts": {
            "physical_winner_seeds": len(delta),
            "by_region": dict(sorted(by_region.items())),
        },
        "source_merged_artifact": merged_identity,
        "source_base_artifact": verified_base_identity,
        "target_manifest_sha256": merged.get("target_manifest_sha256"),
        "target_ledger_sha256": merged.get("target_ledger_sha256"),
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
    parser.add_argument("--merged-root", type=Path, required=True)
    parser.add_argument("--approved-merged-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    print(canonical_json(extract(**vars(parse_args()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

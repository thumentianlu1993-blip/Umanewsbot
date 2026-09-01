#!/usr/bin/env python3
"""Independently audit a France Galop bulletin occurrence proposal.

The audit emits one official winner-anchor seed proposal per held race.  These
rows intentionally use the existing ``targeted-horse-seed.v2`` contract, but
the audit marker is ``AUDITED_REFERENCE_ONLY`` while the target ledger remains
PREPARED.  No Racing API request and no database write occurs here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

RESEARCH_ROOT = Path(__file__).resolve().parent
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))

from audit_legacy_historical_detail_bundle import (
    canonical_json,
    load_target_artifact,
    sha256_path,
)


SOURCE_SCHEMA_VERSION = "france-galop-bulletin-occurrence-proposal.v1"
AUDIT_SCHEMA_VERSION = "france-galop-bulletin-occurrence-audit.v1"
OCCURRENCE_SCHEMA_VERSION = "graded-race-occurrence.v1"
NAME_SEED_SCHEMA_VERSION = "racing-api-horse-name-seed.v1"
TARGETED_SEED_SCHEMA_VERSION = "targeted-horse-seed.v2"
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
HORSE_PREFIX_RE = re.compile(r"^\d+\s+")
COUNTRY_SUFFIX_RE = re.compile(r"^(.*?)\s*\(([A-Z]{2,3})\)\s*$")
AUDIT_TOOL_PATH = Path(__file__).resolve()


def _atomic_write(path: Path, body: bytes) -> None:
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


def _read_json(path: Path, *, label: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    return payload


def _bound_member(root: Path, identity: object, *, label: str) -> Path:
    if not isinstance(identity, Mapping):
        raise ValueError(f"{label} identity is missing")
    relative = str(identity.get("path") or "")
    if not relative or Path(relative).is_absolute():
        raise ValueError(f"{label} path is invalid")
    path = root / relative
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} path escapes source root") from exc
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} is not a regular file")
    if (
        not SHA256_RE.fullmatch(str(identity.get("sha256") or ""))
        or sha256_path(resolved) != identity.get("sha256")
        or resolved.stat().st_size != identity.get("size")
    ):
        raise ValueError(f"{label} identity mismatch")
    return resolved


def _read_jsonl(path: Path, *, label: str) -> list[dict]:
    rows = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{label} row {line_number} is not an object")
            rows.append(row)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    return rows


def _targeted_seed(occurrence: dict, target: dict) -> dict:
    winner = occurrence.get("anchor_horse_name")
    starters = occurrence.get("starters")
    if not isinstance(starters, list) or not isinstance(winner, str) or not winner.strip():
        raise ValueError("occurrence winner/starter contract is invalid")
    winner_rows = [
        row
        for row in starters
        if isinstance(row, Mapping)
        and row.get("horse_name") == winner
        and row.get("finish_position") == 1
    ]
    if len(winner_rows) != 1:
        raise ValueError("occurrence does not contain exactly one winner anchor")
    source = occurrence.get("source_evidence")
    if not isinstance(source, Mapping):
        raise ValueError("occurrence source evidence is missing")
    country_match = COUNTRY_SUFFIX_RE.fullmatch(winner.strip())
    name = country_match.group(1).strip() if country_match else winner.strip()
    seed = {
        "schema_version": TARGETED_SEED_SCHEMA_VERSION,
        "seed_id": (
            "france-galop-winner-"
            + hashlib.sha256(str(occurrence["target_key"]).encode("utf-8")).hexdigest()[:20]
        ),
        "name": name,
        "expected_finish_position": "1",
        "source_authority": "organizer_official",
        "source_url": source["source_url"],
        "source_payload_sha256": source["sha256"],
        "source_occurrence_id": str(occurrence["occurrence_key"]),
        "allow_profile_only_if_target_missing": True,
        "target": {
            "year": int(target["year"]),
            "edition_year": int(target["year"]),
            "target_key": str(occurrence["target_key"]),
            "country_region": "france",
            "local_date": occurrence["local_date"],
            "canonical_name_original": target["canonical_name_original"],
            "race_name_aliases": sorted(
                {
                    str(target.get("original_name") or "").strip(),
                    str(occurrence.get("race_name") or "").strip(),
                }
                - {""}
            ),
            "racecourse": target["racecourse"],
            "racecourse_aliases": sorted(
                {
                    str(target.get("racecourse") or "").strip(),
                    str(occurrence.get("racecourse") or "").strip(),
                }
                - {""}
            ),
            "grade_text": occurrence["normalized_grade"],
            "discipline": target["discipline"],
        },
    }
    if country_match:
        seed["country_suffix"] = country_match.group(2)
    return seed


def build_targeted_seed_proposals(
    occurrences: list[dict], *, targets_by_key: dict[str, dict]
) -> list[dict]:
    seeds = []
    seen = set()
    for occurrence in sorted(occurrences, key=lambda row: row["target_key"]):
        target_key = str(occurrence.get("target_key") or "")
        target = targets_by_key.get(target_key)
        if target is None or target_key in seen:
            raise ValueError("occurrence target is missing or duplicated")
        seen.add(target_key)
        seeds.append(_targeted_seed(occurrence, target))
    if not seeds:
        raise ValueError("no official occurrence can become a targeted seed proposal")
    return seeds


def audit_proposal(*, proposal_root: Path, output_dir: Path) -> dict:
    if proposal_root.is_symlink():
        raise ValueError("proposal root must not be a symlink")
    root = proposal_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("proposal root must be a directory")
    if output_dir.exists() and (
        output_dir.is_symlink() or not output_dir.is_dir() or any(output_dir.iterdir())
    ):
        raise ValueError("audit output must be absent or empty")

    manifest_path = root / "proposal-manifest.json"
    manifest = _read_json(manifest_path, label="proposal manifest")
    marker_path = root / "PREPARED"
    if (
        marker_path.is_symlink()
        or not marker_path.is_file()
        or marker_path.read_text(encoding="ascii").strip() != sha256_path(manifest_path)
        or manifest.get("schema_version") != SOURCE_SCHEMA_VERSION
        or manifest.get("completion_marker") != "PREPARED"
        or manifest.get("approval") is not False
        or manifest.get("database_writes") != 0
        or manifest.get("racing_api_requests") != 0
    ):
        raise ValueError("proposal manifest/marker contract is invalid")

    target_root = Path(str((manifest.get("target_artifact") or {}).get("root") or ""))
    target_rows, target_identity = load_target_artifact(target_root)
    if target_identity != manifest.get("target_artifact"):
        raise ValueError("proposal target artifact identity drift")
    targets_by_key = {str(row.get("target_key") or ""): row for row in target_rows}
    if len(targets_by_key) != len(target_rows):
        raise ValueError("target ledger contains duplicate keys")
    parser_identity = manifest.get("parser")
    if not isinstance(parser_identity, Mapping):
        raise ValueError("proposal parser identity is missing")
    parser_path = Path(str(parser_identity.get("tool_path") or ""))
    if (
        parser_path.is_symlink()
        or not parser_path.is_file()
        or sha256_path(parser_path) != parser_identity.get("tool_sha256")
        or parser_identity.get("pdf_library") != "pdfplumber"
        or not str(parser_identity.get("pdf_library_version") or "").strip()
    ):
        raise ValueError("proposal parser identity drift")

    outputs = manifest.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ValueError("proposal outputs are missing")
    occurrence_path = _bound_member(root, outputs.get("occurrences"), label="occurrences")
    name_seed_path = _bound_member(root, outputs.get("horse_name_seeds"), label="name seeds")
    unmatched_path = _bound_member(root, outputs.get("unmatched_targets"), label="unmatched targets")
    occurrences = _read_jsonl(occurrence_path, label="occurrences")
    name_seeds = _read_jsonl(name_seed_path, label="name seeds")
    unmatched = _read_jsonl(unmatched_path, label="unmatched targets")
    if any(
        not isinstance(outputs.get(label), Mapping)
        or outputs[label].get("rows") != len(rows)
        for label, rows in (
            ("occurrences", occurrences),
            ("horse_name_seeds", name_seeds),
            ("unmatched_targets", unmatched),
        )
    ):
        raise ValueError("proposal output row counts drift")

    source_cache_manifest = _read_json(
        root / "sources/source_cache_manifest.json", label="source cache manifest"
    )
    cache_files = source_cache_manifest.get("files")
    if (
        source_cache_manifest.get("schema_version") != "1.0"
        or Path(str(source_cache_manifest.get("root") or "")).resolve()
        != (root / "sources").resolve()
        or not isinstance(cache_files, Mapping)
    ):
        raise ValueError("source cache manifest contract is invalid")
    declared_sources = [manifest.get("official_index"), *((manifest.get("bulletins") or {}).get("sources") or [])]
    for index, source in enumerate(declared_sources):
        if not isinstance(source, Mapping):
            raise ValueError("declared source identity is invalid")
        parsed = urlparse(str(source.get("source_url") or ""))
        if parsed.scheme != "https" or parsed.hostname not in {
            "france-galop.com",
            "www.france-galop.com",
        }:
            raise ValueError("declared source URL is not France Galop HTTPS")
        source_path = Path(str(source.get("cache_path") or ""))
        try:
            source_path.resolve(strict=True).relative_to(root / "sources")
        except (OSError, ValueError) as exc:
            raise ValueError("declared source path escapes source cache") from exc
        if (
            source_path.is_symlink()
            or sha256_path(source_path) != source.get("sha256")
            or source_path.stat().st_size != source.get("size")
        ):
            raise ValueError(f"declared source identity mismatch at index {index}")
        relative = str(source_path.resolve().relative_to((root / "sources").resolve()))
        cache_identity = cache_files.get(relative)
        if (
            not isinstance(cache_identity, Mapping)
            or cache_identity.get("sha256") != source.get("sha256")
            or cache_identity.get("source_url") != source.get("source_url")
        ):
            raise ValueError("declared source is not bound by source cache manifest")

    bulletin_summary = manifest.get("bulletins") or {}
    fetch_errors = bulletin_summary.get("fetch_errors") or []
    for item in fetch_errors:
        error_path = root / "sources" / f"{item['filename']}.fetch-error.json"
        error = _read_json(error_path, label="persistent fetch error")
        if (
            error.get("source_url") != item.get("source_url")
            or error.get("http_status") not in {404, 410}
            or error != {
                key: item[key]
                for key in ("source_url", "http_status", "reason", "observed_at")
            }
        ):
            raise ValueError("persistent fetch-error evidence drift")
    if (
        bulletin_summary.get("discovered")
        != bulletin_summary.get("cached_and_verified")
        + bulletin_summary.get("persistent_fetch_errors")
    ):
        raise ValueError("official bulletin source conservation failed")

    occurrence_keys = set()
    target_keys = set()
    observed_names: dict[str, dict] = {}
    actual_starters = 0
    for occurrence in occurrences:
        if occurrence.get("schema_version") != OCCURRENCE_SCHEMA_VERSION:
            raise ValueError("occurrence schema drift")
        occurrence_key = str(occurrence.get("occurrence_key") or "")
        target_key = str(occurrence.get("target_key") or "")
        starters = occurrence.get("starters")
        if (
            not occurrence_key
            or occurrence_key in occurrence_keys
            or not target_key
            or target_key in target_keys
            or target_key not in targets_by_key
            or occurrence.get("source_status") != "held"
            or not isinstance(starters, list)
            or occurrence.get("actual_starter_count") != len(starters)
        ):
            raise ValueError("occurrence identity/conservation drift")
        occurrence_keys.add(occurrence_key)
        target_keys.add(target_key)
        target = targets_by_key[target_key]
        source_course = str(occurrence.get("racecourse") or "").strip()
        target_course = str(target.get("racecourse") or "").strip()
        relation = occurrence.get("racecourse_relation")
        if (
            not source_course
            or occurrence.get("target_racecourse") != target_course
            or relation
            != (
                "matched_target_default"
                if re.sub(r"\W+", "", source_course.casefold())
                == re.sub(r"\W+", "", target_course.casefold())
                else "official_result_overrides_target_default"
            )
        ):
            raise ValueError("occurrence racecourse relation drift")
        actual_starters += len(starters)
        for starter in starters:
            if not isinstance(starter, Mapping):
                raise ValueError("starter row is invalid")
            horse_name = str(starter.get("horse_name") or "").strip()
            search_name = str(starter.get("horse_name_search") or "").strip()
            if not horse_name or not search_name or HORSE_PREFIX_RE.match(horse_name):
                raise ValueError("starter name contains an invalid form prefix")
            key = re.sub(r"\W+", "", search_name.casefold())
            bucket = observed_names.setdefault(
                key,
                {"source_names": set(), "occurrence_keys": set(), "target_keys": set()},
            )
            bucket["source_names"].add(horse_name)
            bucket["occurrence_keys"].add(occurrence_key)
            bucket["target_keys"].add(target_key)
    if actual_starters != manifest.get("actual_starters"):
        raise ValueError("manifest actual starter count drift")

    for seed in name_seeds:
        if (
            seed.get("schema_version") != NAME_SEED_SCHEMA_VERSION
            or seed.get("identity_status") != "query_seed_only"
        ):
            raise ValueError("name seed schema/identity drift")
        name = str(seed.get("source_name_raw") or "").strip()
        variants = seed.get("search_variants")
        if not name or HORSE_PREFIX_RE.match(name) or not isinstance(variants, list):
            raise ValueError("name seed contains an invalid form prefix")
    if len(name_seeds) != manifest.get("unique_name_query_seeds"):
        raise ValueError("unique name seed count drift")

    proposals = build_targeted_seed_proposals(occurrences, targets_by_key=targets_by_key)
    review_required = list(manifest.get("review_required") or [])
    if target_identity.get("reviewed_complete"):
        review_required = [
            item
            for item in review_required
            if item != "resolve target-ledger source-count conflicts"
        ]
    output_dir.mkdir(parents=True, exist_ok=True)
    proposal_path = output_dir / "targeted-horse-seed-proposals.jsonl"
    _atomic_write(
        proposal_path,
        "".join(canonical_json(row) + "\n" for row in proposals).encode("utf-8"),
    )
    audit = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "reference_only_target_review_required",
        "completion_marker": "AUDITED_REFERENCE_ONLY",
        "approval": False,
        "database_writes": 0,
        "racing_api_requests": 0,
        "source_proposal": {
            "root": str(root),
            "manifest_sha256": sha256_path(manifest_path),
            "manifest_size": manifest_path.stat().st_size,
        },
        "target_artifact": target_identity,
        "auditor": {
            "tool_path": str(AUDIT_TOOL_PATH),
            "tool_sha256": sha256_path(AUDIT_TOOL_PATH),
        },
        "counts": {
            "held_occurrences": len(occurrences),
            "actual_starters": actual_starters,
            "unique_name_query_seeds": len(name_seeds),
            "unmatched_targets": len(unmatched),
            "winner_anchor_seed_proposals": len(proposals),
        },
        "targeted_seed_proposals": {
            "path": proposal_path.name,
            "rows": len(proposals),
            "sha256": sha256_path(proposal_path),
            "size": proposal_path.stat().st_size,
            "runnable": False,
            "reason": "organizer-official supplements require an exact approved gap-only merge",
        },
        "request_strategy": {
            "phase_1": "one official winner anchor per held race recovers the TRA race and all runner hrs_* IDs",
            "phase_2": "deduplicate stable hrs_* IDs and export every runner profile/career by ID",
            "bulk_results_12_month_dependency": False,
        },
        "review_required": review_required,
    }
    audit_path = output_dir / "audit-manifest.json"
    _atomic_write(
        audit_path,
        (json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    _atomic_write(
        output_dir / "AUDITED_REFERENCE_ONLY",
        f"{sha256_path(audit_path)}\n".encode("ascii"),
    )
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = audit_proposal(proposal_root=args.proposal_root, output_dir=args.output_dir)
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

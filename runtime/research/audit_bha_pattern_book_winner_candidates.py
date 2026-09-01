#!/usr/bin/env python3
"""Audit frozen BHA Pattern Book candidates and emit exact target-bound v2 seeds."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

RESEARCH_ROOT = Path(__file__).resolve().parent
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))

from audit_legacy_historical_detail_bundle import (
    canonical_json,
    load_target_artifact,
    sha256_path,
)
from prepare_bha_pattern_book_winner_candidates import (
    extract_pdf_text,
    parse_pattern_book,
)

SOURCE_SCHEMA = "bha-pattern-book-winner-candidate-proposal.v1"
AUDIT_SCHEMA = "bha-pattern-book-winner-candidate-audit.v1"
CANDIDATE_SCHEMA = "bha-pattern-book-winner-candidate.v1"
SHA_RE = re.compile(r"[0-9a-f]{64}")
ALLOWED_HOSTS = {"media.britishhorseracing.com"}


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


def _json(path: Path, *, label: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _rows(root: Path, identity: object, *, label: str) -> list[dict]:
    if not isinstance(identity, Mapping):
        raise ValueError(f"{label} identity is missing")
    relative = str(identity.get("path") or "")
    if not relative or Path(relative).is_absolute():
        raise ValueError(f"{label} path is invalid")
    path = (root / relative).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes proposal root") from exc
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    if (
        path.is_symlink()
        or not path.is_file()
        or not SHA_RE.fullmatch(str(identity.get("sha256") or ""))
        or sha256_path(path) != identity.get("sha256")
        or path.stat().st_size != identity.get("size")
        or len(rows) != identity.get("rows")
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise ValueError(f"{label} identity drift")
    return rows


def _official_url(value: object) -> str:
    url = str(value or "")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
    ):
        raise ValueError("BHA source URL is not organizer-official HTTPS")
    return url


def _seed(candidate: dict, target: dict) -> dict:
    winner = candidate["winner"]
    source = candidate["source_evidence"]
    target_key = str(candidate["target_key"])
    seed = {
        "schema_version": "targeted-horse-seed.v2",
        "seed_id": "bha-pattern-winner-"
        + hashlib.sha256(target_key.encode()).hexdigest()[:20],
        "name": str(winner["horse_name"]),
        "expected_finish_position": "1",
        "source_authority": "organizer_official",
        "source_url": _official_url(source["source_url"]),
        "source_payload_sha256": source["sha256"],
        "source_occurrence_id": (
            f"bha-pattern:{source['sha256']}:{candidate['page_number']}:"
            f"{candidate['block_number']}:{candidate['edition_year']}"
        ),
        "allow_profile_only_if_target_missing": True,
        "target": {
            "year": int(target["year"]),
            "edition_year": int(target["year"]),
            "target_key": target_key,
            "country_region": "united_kingdom",
            "local_date": str(target.get("local_date") or ""),
            "canonical_name_original": target["canonical_name_original"],
            "race_name_aliases": sorted(
                {
                    str(target.get("original_name") or "").strip(),
                    *[str(value).strip() for value in candidate["race_name_aliases"]],
                }
                - {""}
            ),
            "racecourse": target["racecourse"],
            "racecourse_aliases": [str(target.get("racecourse") or "")],
            "grade_text": candidate["normalized_grade"],
            "discipline": target["discipline"],
        },
    }
    if winner.get("country_suffix"):
        seed["country_suffix"] = winner["country_suffix"]
    if len(candidate.get("co_winners") or []) > 1:
        seed["winner_selection_note"] = (
            "official book lists joint winners; first source-order winner is a sufficient "
            "race anchor and all runners are recovered from the resolved race"
        )
    return seed


def audit(*, proposal_root: Path, output_dir: Path) -> dict:
    root = proposal_root.resolve(strict=True)
    if proposal_root.is_symlink() or not root.is_dir():
        raise ValueError("proposal root must be a regular directory")
    if output_dir.exists():
        raise ValueError("audit output must not already exist")
    manifest_path = root / "proposal-manifest.json"
    manifest = _json(manifest_path, label="proposal manifest")
    manifest_sha = sha256_path(manifest_path)
    marker = root / "PREPARED"
    if (
        marker.is_symlink()
        or not marker.is_file()
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != SOURCE_SCHEMA
        or manifest.get("status") != "PROPOSED_NOT_APPROVED"
        or manifest.get("completion_marker") != "PREPARED"
        or manifest.get("approval") is not False
        or manifest.get("database_writes") != 0
        or manifest.get("racing_api_requests") != 0
    ):
        raise ValueError("BHA proposal contract drift")
    target_root = Path(str((manifest.get("target_artifact") or {}).get("root") or ""))
    target_rows, target_identity = load_target_artifact(target_root)
    if target_identity != manifest.get("target_artifact"):
        raise ValueError("BHA target artifact drift")
    targets = {str(row["target_key"]): row for row in target_rows}
    outputs = manifest.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ValueError("BHA proposal outputs are missing")
    candidates = _rows(root, outputs.get("candidates"), label="candidates")
    _rows(root, outputs.get("unmatched"), label="unmatched")
    parser = manifest.get("parser")
    parser_path = RESEARCH_ROOT / str((parser or {}).get("path") or "")
    if (
        not isinstance(parser, Mapping)
        or parser_path.is_symlink()
        or not parser_path.is_file()
        or sha256_path(parser_path) != parser.get("sha256")
        or parser.get("pdf_library") != "pypdf"
    ):
        raise ValueError("BHA parser identity drift")
    reparsed = {}
    for source in manifest.get("sources") or []:
        if not isinstance(source, Mapping):
            raise ValueError("BHA source identity is invalid")
        _official_url(source.get("source_url"))
        cache_path = Path(str(source.get("cache_path") or ""))
        try:
            cache_path.resolve(strict=True).relative_to(root / "sources")
        except (OSError, ValueError) as exc:
            raise ValueError("BHA source cache escapes proposal") from exc
        if (
            cache_path.is_symlink()
            or not cache_path.is_file()
            or sha256_path(cache_path) != source.get("sha256")
            or cache_path.stat().st_size != source.get("size")
        ):
            raise ValueError("BHA source identity drift")
        for row in parse_pattern_book(
            extract_pdf_text(cache_path),
            discipline=str(source["discipline"]),
            source_evidence=dict(source),
        ):
            key = (
                source["sha256"],
                row["edition_year"],
                row["discipline"],
                row["block_number"],
            )
            if key in reparsed:
                raise ValueError("BHA frozen source identity is duplicated")
            reparsed[key] = row
    seeds = []
    seen = set()
    for candidate in candidates:
        target_key = str(candidate.get("target_key") or "")
        target = targets.get(target_key)
        source = candidate.get("source_evidence")
        key = (
            str((source or {}).get("sha256") or ""),
            candidate.get("edition_year"),
            candidate.get("discipline"),
            candidate.get("block_number"),
        )
        frozen = reparsed.get(key)
        if (
            candidate.get("schema_version") != CANDIDATE_SCHEMA
            or target is None
            or target_key in seen
            or target.get("country_region") != "united_kingdom"
            or int(target.get("year") or 0) != int(candidate.get("edition_year") or 0)
            or target.get("grade_text") != candidate.get("normalized_grade")
            or frozen is None
            or frozen["winner"] != candidate.get("winner")
            or frozen["race_name_aliases"] != candidate.get("race_name_aliases")
            or frozen["match_name_aliases"] != candidate.get("match_name_aliases")
            or frozen["normalized_grade"] != candidate.get("normalized_grade")
        ):
            raise ValueError("BHA candidate/frozen source contract drift")
        seen.add(target_key)
        seeds.append(_seed(candidate, target))
    if not seeds:
        raise ValueError("BHA audit has no exact target-bound seed")
    output_dir.mkdir(parents=True, mode=0o700)
    seed_path = output_dir / "targeted-horse-seed-proposals.jsonl"
    _atomic(seed_path, "".join(canonical_json(row) + "\n" for row in seeds).encode())
    proposal_identity = {
        "path": seed_path.name,
        "rows": len(seeds),
        "sha256": sha256_path(seed_path),
        "size": seed_path.stat().st_size,
        "runnable": False,
    }
    audit_manifest = {
        "schema_version": AUDIT_SCHEMA,
        "status": "reference_only_target_review_required",
        "completion_marker": "AUDITED_REFERENCE_ONLY",
        "approval": False,
        "database_writes": 0,
        "racing_api_requests": 0,
        "source_proposal": {"root": str(root), "manifest_sha256": manifest_sha},
        "target_artifact": target_identity,
        "counts": {"winner_anchor_seed_proposals": len(seeds)},
        "targeted_seed_proposals": proposal_identity,
    }
    audit_path = output_dir / "audit-manifest.json"
    _atomic(
        audit_path,
        (json.dumps(audit_manifest, indent=2, sort_keys=True) + "\n").encode(),
    )
    _atomic(
        output_dir / "AUDITED_REFERENCE_ONLY",
        (sha256_path(audit_path) + "\n").encode("ascii"),
    )
    return audit_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        canonical_json(
            audit(proposal_root=args.proposal_root, output_dir=args.output_dir)
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

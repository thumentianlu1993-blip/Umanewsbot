#!/usr/bin/env python3
"""Freeze every unmatched HRI official graded result as a targeted seed.

The HRI proposal deliberately leaves organizer-official results unmatched when
the reviewed target catalogue cannot identify a unique series alias.  Those
results are nevertheless actual held races.  This offline builder conserves
them by their official result URL/date/course/grade and winner, so Racing API
can recover the exact race and every starter without guessing a catalogue key.
"""

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
from urllib.parse import urlsplit


PROPOSAL_SCHEMA = "hri-graded-winner-candidate-proposal.v1"
AUDIT_SCHEMA = "hri-graded-winner-candidate-audit.v1"
UNMATCHED_SCHEMA = "hri-graded-result-unmatched.v1"
SEED_SCHEMA = "targeted-horse-seed.v2"
MANIFEST_SCHEMA = "targeted-horse-seed-ledger.v1"
SHA_RE = re.compile(r"[0-9a-f]{64}$")
GRADE_RE = re.compile(r"\((Grade|Group)\s*([123])\)", re.IGNORECASE)
ALLOWED_HOSTS = {"hri.ie", "www.hri.ie"}


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


def _json(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(_regular(path, label=label).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _jsonl(path: Path, *, label: str) -> list[dict]:
    rows = []
    try:
        for number, line in enumerate(
            _regular(path, label=label).read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{label} row {number} is not an object")
            rows.append(row)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSONL") from exc
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
        raise ValueError(f"{label} escapes proposal root") from exc
    rows = _jsonl(path, label=label)
    if (
        not SHA_RE.fullmatch(str(value.get("sha256") or ""))
        or sha256_path(path) != value.get("sha256")
        or path.stat().st_size != value.get("size")
        or len(rows) != value.get("rows")
    ):
        raise ValueError(f"{label} identity drift")
    return path, rows


def _official_url(value: object) -> str:
    url = str(value or "")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("HRI official URL is invalid")
    return parsed.geturl()


def _source_identity(root: Path, expected_sha: str, *, name: str, schema: str) -> tuple[Path, dict]:
    manifest_path = _regular(root / name, label=name)
    manifest_sha = sha256_path(manifest_path)
    marker_name = "PREPARED" if name == "proposal-manifest.json" else "AUDITED_REFERENCE_ONLY"
    marker = _regular(root / marker_name, label=marker_name)
    manifest = _json(manifest_path, label=name)
    if (
        not SHA_RE.fullmatch(expected_sha)
        or manifest_sha != expected_sha
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("schema_version") != schema
        or manifest.get("database_writes") != 0
        or manifest.get("racing_api_requests") != 0
    ):
        raise ValueError(f"{name} contract drift")
    return manifest_path, manifest


def _seed(row: Mapping[str, object]) -> dict:
    winner = row.get("winner")
    source = row.get("source_evidence")
    if not isinstance(winner, Mapping) or not isinstance(source, Mapping):
        raise ValueError("HRI unmatched winner/source evidence is missing")
    winner_name = " ".join(str(winner.get("horse_name") or "").split())
    race_name = " ".join(str(row.get("race_name") or "").split())
    racecourse = " ".join(str(row.get("racecourse") or "").split())
    local_date = str(row.get("local_date") or "")
    edition_year = int(row.get("edition_year") or 0)
    grade_match = GRADE_RE.search(race_name)
    result_url = _official_url(row.get("result_url"))
    source_url = _official_url(source.get("source_url"))
    source_sha = str(source.get("sha256") or "")
    if (
        row.get("schema_version") != UNMATCHED_SCHEMA
        or not winner_name
        or not racecourse
        or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", local_date)
        or not 2021 <= edition_year <= 2025
        or not local_date.startswith(str(edition_year))
        or grade_match is None
        or not SHA_RE.fullmatch(source_sha)
        or winner.get("finish_position") != 1
    ):
        raise ValueError("HRI unmatched official result contract drift")
    normalized_grade = f"G{grade_match.group(2)}"
    if str(row.get("normalized_grade") or "") != normalized_grade:
        raise ValueError("HRI official grade normalization drift")
    discipline = "jumps" if grade_match.group(1).casefold() == "grade" else "flat"
    occurrence_digest = hashlib.sha256(result_url.encode("utf-8")).hexdigest()
    canonical_name = GRADE_RE.sub("", race_name).strip(" -")
    return {
        "schema_version": SEED_SCHEMA,
        "seed_id": f"hri-held-{occurrence_digest[:20]}",
        "name": winner_name,
        "expected_finish_position": "1",
        "source_authority": "organizer_official",
        "source_url": result_url,
        "source_payload_sha256": source_sha,
        "source_occurrence_id": f"hri:{local_date}:{result_url}",
        "allow_profile_only_if_target_missing": True,
        "target": {
            "year": edition_year,
            "edition_year": edition_year,
            "target_key": f"ireland:{edition_year}:hri-held-{occurrence_digest[:20]}:{discipline}",
            "country_region": "ireland",
            "local_date": local_date,
            "canonical_name_original": canonical_name,
            "race_name_aliases": sorted({canonical_name, race_name}),
            "racecourse": racecourse,
            "racecourse_aliases": [racecourse],
            "grade_text": normalized_grade,
            "discipline": discipline,
            "organizer_result_url": result_url,
            "organizer_date_page_url": source_url,
            "allow_unique_structured_name_mismatch": True,
        },
    }


def prepare(
    *,
    proposal_root: Path,
    approved_proposal_manifest_sha256: str,
    audit_root: Path,
    approved_audit_manifest_sha256: str,
    output_dir: Path,
) -> dict:
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("output directory must not already exist")
    proposal_root = proposal_root.resolve(strict=True)
    audit_root = audit_root.resolve(strict=True)
    proposal_path, proposal = _source_identity(
        proposal_root,
        approved_proposal_manifest_sha256,
        name="proposal-manifest.json",
        schema=PROPOSAL_SCHEMA,
    )
    audit_path, audit = _source_identity(
        audit_root,
        approved_audit_manifest_sha256,
        name="audit-manifest.json",
        schema=AUDIT_SCHEMA,
    )
    source_proposal = audit.get("source_proposal")
    if (
        proposal.get("status") != "PROPOSED_NOT_APPROVED"
        or proposal.get("approval") is not False
        or audit.get("status") != "reference_only_target_review_required"
        or audit.get("approval") is not False
        or not isinstance(source_proposal, Mapping)
        or Path(str(source_proposal.get("root") or "")).resolve() != proposal_root
        or source_proposal.get("manifest_sha256") != approved_proposal_manifest_sha256
    ):
        raise ValueError("HRI proposal/audit binding drift")
    outputs = proposal.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ValueError("HRI proposal outputs are missing")
    unmatched_path, unmatched = _identity(
        proposal_root, outputs.get("unmatched"), label="HRI unmatched official results"
    )
    counts = proposal.get("counts")
    audit_counts = audit.get("counts")
    if (
        not isinstance(counts, Mapping)
        or not isinstance(audit_counts, Mapping)
        or counts.get("unmatched_official_results") != len(unmatched)
        or audit_counts.get("unmatched_official_results") != len(unmatched)
        or int(counts.get("matched_targets") or 0) + len(unmatched)
        != int(counts.get("official_graded_results") or 0)
    ):
        raise ValueError("HRI official result conservation drift")

    seeds = [_seed(row) for row in unmatched]
    seed_ids = [row["seed_id"] for row in seeds]
    occurrence_ids = [row["source_occurrence_id"] for row in seeds]
    if len(seed_ids) != len(set(seed_ids)) or len(occurrence_ids) != len(set(occurrence_ids)):
        raise ValueError("HRI official result identity is duplicated")
    seeds.sort(key=lambda row: (row["target"]["local_date"], row["source_occurrence_id"]))

    output_dir.mkdir(parents=True, mode=0o700)
    ledger_path = output_dir / "targeted-horse-seeds.jsonl"
    _atomic(ledger_path, "".join(canonical_json(row) + "\n" for row in seeds).encode())
    ledger_identity = {
        "path": ledger_path.name,
        "rows": len(seeds),
        "sha256": sha256_path(ledger_path),
        "size": ledger_path.stat().st_size,
    }
    by_year = Counter(int(row["target"]["year"]) for row in seeds)
    manifest = {
        "artifact_schema_version": "hri-unmatched-official-targeted-seeds.v1",
        "schema_version": MANIFEST_SCHEMA,
        "status": "complete",
        "completion_marker": "COMPLETE",
        "coverage_status": "all_verified_hri_results_seeded",
        "database_writes": 0,
        "network_requests": 0,
        "seed_count": len(seeds),
        "seed_ledger": ledger_identity,
        "outputs": {"targeted-horse-seeds.jsonl": ledger_identity},
        "counts": {
            "official_graded_results": int(counts["official_graded_results"]),
            "catalogue_matched_official_results": int(counts["matched_targets"]),
            "direct_official_occurrence_seeds": len(seeds),
            "unaccounted_official_results": 0,
            "physical_winner_seeds": len(seeds),
            "by_region": {"ireland": len(seeds)},
            "by_year": {str(key): value for key, value in sorted(by_year.items())},
        },
        "source_proposal": {
            "root": str(proposal_root),
            "manifest_sha256": sha256_path(proposal_path),
            "unmatched_sha256": sha256_path(unmatched_path),
        },
        "source_audit": {
            "root": str(audit_root),
            "manifest_sha256": sha256_path(audit_path),
        },
        "target_manifest_sha256": (proposal.get("target_artifact") or {}).get(
            "manifest_sha256"
        ),
        "target_ledger_sha256": (proposal.get("target_artifact") or {}).get("ledger_sha256"),
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
    parser.add_argument("--proposal-root", type=Path, required=True)
    parser.add_argument("--approved-proposal-manifest-sha256", required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--approved-audit-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    print(canonical_json(prepare(**vars(parse_args()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

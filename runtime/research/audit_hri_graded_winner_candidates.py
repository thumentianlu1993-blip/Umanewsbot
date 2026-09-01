#!/usr/bin/env python3
"""Independently audit HRI official graded-winner candidates and emit v2 seeds."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from audit_legacy_historical_detail_bundle import canonical_json, load_target_artifact, sha256_path


SOURCE_SCHEMA = "hri-graded-winner-candidate-proposal.v1"
AUDIT_SCHEMA = "hri-graded-winner-candidate-audit.v1"
CANDIDATE_SCHEMA = "hri-graded-winner-candidate.v1"
SHA_RE = re.compile(r"[0-9a-f]{64}")
GRADE_RE = re.compile(r"\((?:Grade|Group)\s*([123])\)", re.IGNORECASE)
COUNTRY_RE = re.compile(r"\s*\(([A-Z]{2,3})\)\s*$")
ALLOWED_HOSTS = {"hri.ie", "www.hri.ie"}


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


def _jsonl(path: Path, *, label: str) -> list[dict]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    rows = []
    try:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{label} row {number} is not an object")
            rows.append(row)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    return rows


def _bound(root: Path, identity: object, *, label: str) -> tuple[Path, list[dict]]:
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
    rows = _jsonl(path, label=label)
    if (
        not SHA_RE.fullmatch(str(identity.get("sha256") or ""))
        or sha256_path(path) != identity.get("sha256")
        or path.stat().st_size != identity.get("size")
        or len(rows) != identity.get("rows")
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
    ):
        raise ValueError("HRI source URL is not organizer-official HTTPS")
    return url


def _winner_from_frozen_page(path: Path, *, result_url: str, race_name: str) -> str:
    soup = BeautifulSoup(path.read_bytes(), "lxml")
    matches = []
    for item in soup.select(".race-result-item"):
        link = item.select_one("h2 a")
        if link is None:
            continue
        candidate_url = urljoin("https://www.hri.ie", str(link.get("href") or ""))
        candidate_name = " ".join(link.get_text(" ", strip=True).split())
        if candidate_url != result_url or candidate_name != race_name:
            continue
        winners = []
        for tr in item.select("tbody tr"):
            cells = [" ".join(td.get_text(" ", strip=True).split()) for td in tr.select("td")]
            if len(cells) >= 4 and re.match(r"1(?:st)?$", cells[0], re.IGNORECASE):
                winners.append(cells[3])
        if len(winners) != 1:
            raise ValueError("HRI frozen page does not contain exactly one winner")
        matches.append(winners[0])
    if len(matches) != 1:
        raise ValueError("HRI candidate race is not unique in its frozen page")
    match = COUNTRY_RE.search(matches[0])
    return matches[0][: match.start()].strip() if match else matches[0].strip()


def _seed(candidate: dict, target: dict) -> dict:
    winner = candidate.get("winner")
    source = candidate.get("source_evidence")
    if not isinstance(winner, Mapping) or not isinstance(source, Mapping):
        raise ValueError("HRI candidate winner/source is missing")
    name = str(winner.get("horse_name") or "").strip()
    target_key = str(candidate.get("target_key") or "")
    source_url = _official_url(source.get("source_url"))
    result_url = _official_url(candidate.get("result_url"))
    if not name or not target_key:
        raise ValueError("HRI winner name or target key is missing")
    seed = {
        "schema_version": "targeted-horse-seed.v2",
        "seed_id": "hri-winner-" + hashlib.sha256(target_key.encode()).hexdigest()[:20],
        "name": name,
        "expected_finish_position": "1",
        "source_authority": "organizer_official",
        "source_url": result_url,
        "source_payload_sha256": source["sha256"],
        "source_occurrence_id": f"hri:{candidate['local_date']}:{result_url}",
        "allow_profile_only_if_target_missing": True,
        "target": {
            "year": int(target["year"]),
            "edition_year": int(target["year"]),
            "target_key": target_key,
            "country_region": "ireland",
            "local_date": candidate["local_date"],
            "canonical_name_original": target["canonical_name_original"],
            "race_name_aliases": sorted(
                {
                    str(target.get("original_name") or "").strip(),
                    str(candidate.get("race_name") or "").strip(),
                }
                - {""}
            ),
            "racecourse": target["racecourse"],
            "racecourse_aliases": sorted(
                {str(target.get("racecourse") or ""), str(candidate.get("racecourse") or "")}
                - {""}
            ),
            "grade_text": candidate["normalized_grade"],
            "discipline": target["discipline"],
        },
        "source_date_page_url": source_url,
    }
    country = str(winner.get("country_suffix") or "")
    if country:
        seed["country_suffix"] = country
    return seed


def audit(*, proposal_root: Path, output_dir: Path) -> dict:
    root = proposal_root.resolve(strict=True)
    if proposal_root.is_symlink() or not root.is_dir():
        raise ValueError("proposal root must be a regular directory")
    if output_dir.exists():
        raise ValueError("audit output directory must not already exist")
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
        raise ValueError("HRI proposal contract drift")
    target_root = Path(str((manifest.get("target_artifact") or {}).get("root") or ""))
    target_rows, target_identity = load_target_artifact(target_root)
    if target_identity != manifest.get("target_artifact"):
        raise ValueError("HRI proposal target artifact drift")
    targets = {str(row["target_key"]): row for row in target_rows}
    outputs = manifest.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ValueError("HRI proposal outputs are missing")
    _candidate_path, candidates = _bound(root, outputs.get("candidates"), label="candidates")
    _unmatched_path, _unmatched = _bound(root, outputs.get("unmatched"), label="unmatched")
    seeds = []
    seen = set()
    for candidate in candidates:
        target_key = str(candidate.get("target_key") or "")
        target = targets.get(target_key)
        source = candidate.get("source_evidence")
        winner = candidate.get("winner")
        if (
            candidate.get("schema_version") != CANDIDATE_SCHEMA
            or target is None
            or target_key in seen
            or target.get("country_region") != "ireland"
            or int(target.get("year") or 0) != int(candidate.get("edition_year") or 0)
            or target.get("grade_text") != candidate.get("normalized_grade")
            or not isinstance(source, Mapping)
            or source.get("source_authority") != "organizer_official"
            or source.get("source_provider") != "horse_racing_ireland"
            or not isinstance(winner, Mapping)
            or int(winner.get("finish_position") or 0) != 1
        ):
            raise ValueError("HRI candidate/target contract drift")
        seen.add(target_key)
        cache_path = Path(str(source.get("cache_path") or ""))
        _official_url(source.get("source_url"))
        if (
            cache_path.is_symlink()
            or not cache_path.is_file()
            or sha256_path(cache_path) != source.get("sha256")
            or cache_path.stat().st_size != source.get("size")
        ):
            raise ValueError("HRI candidate source identity drift")
        frozen_winner = _winner_from_frozen_page(
            cache_path,
            result_url=_official_url(candidate.get("result_url")),
            race_name=str(candidate.get("race_name") or ""),
        )
        if frozen_winner != str(winner.get("horse_name") or ""):
            raise ValueError("HRI candidate winner drift")
        seeds.append(_seed(candidate, target))
    output_dir.mkdir(parents=True, mode=0o700)
    seed_path = output_dir / "targeted-horse-seed-proposals.jsonl"
    _atomic(seed_path, "".join(canonical_json(row) + "\n" for row in seeds).encode())
    proposal_identity = {
        "path": seed_path.name,
        "rows": len(seeds),
        "sha256": sha256_path(seed_path),
        "size": seed_path.stat().st_size,
        "runnable": False,
        "reason": "organizer-official supplements require an exact approved gap-only merge",
    }
    result = {
        "schema_version": AUDIT_SCHEMA,
        "status": "reference_only_target_review_required",
        "completion_marker": "AUDITED_REFERENCE_ONLY",
        "approval": False,
        "database_writes": 0,
        "racing_api_requests": 0,
        "source_proposal": {
            "root": str(root),
            "manifest_sha256": manifest_sha,
            "manifest_size": manifest_path.stat().st_size,
        },
        "target_artifact": target_identity,
        "counts": {
            "audited_candidates": len(seeds),
            "unmatched_official_results": int(
                (manifest.get("counts") or {}).get("unmatched_official_results") or 0
            ),
        },
        "targeted_seed_proposals": proposal_identity,
        "auditor": {"path": Path(__file__).name, "sha256": sha256_path(Path(__file__))},
    }
    audit_path = output_dir / "audit-manifest.json"
    _atomic(
        audit_path,
        (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
    )
    _atomic(
        output_dir / "AUDITED_REFERENCE_ONLY",
        (sha256_path(audit_path) + "\n").encode("ascii"),
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    print(canonical_json(audit(**vars(parse_args()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

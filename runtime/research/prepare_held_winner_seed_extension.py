#!/usr/bin/env python3
"""Prepare a non-executable winner-seed extension for all reviewed held targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from collections import Counter
from math import ceil
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


SCHEMA_VERSION = "held-winner-seed-extension-proposal.v1"
TARGET_SCHEMA_VERSION = "graded-horse-target-ledger.v1"
HELD_SCHEMA_VERSION = "reviewed-occurrence-consolidation.v1"
SEED_MANIFEST_SCHEMA_VERSION = "targeted-horse-seed-ledger.v1"
SEED_SCHEMA_VERSION = "targeted-horse-seed.v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
PAREN_COUNTRY_RE = re.compile(r"^(?P<name>.+?)\s+\((?P<country>[A-Z]{2,3})\)$")
TRAILING_COUNTRY_RE = re.compile(r"^(?P<name>.+?)\s+(?P<country>[A-Z]{2,3})$")
COUNTRY_CODES = {
    "ARG", "AUS", "BRZ", "CAN", "CHI", "FR", "GB", "GER", "IRE", "ITY",
    "JPN", "NZ", "SAF", "SPA", "USA", "URU",
}


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def _read_json(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(_regular(path, label=label).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _read_jsonl(path: Path, *, label: str) -> list[dict]:
    rows = []
    try:
        for line_number, line in enumerate(
            _regular(path, label=label).read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{label} row {line_number} must be an object")
            rows.append(row)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    return rows


def _require_sha(actual: str, approved: str, *, label: str) -> None:
    if not SHA256_RE.fullmatch(approved) or actual != approved:
        raise ValueError(f"{label} SHA-256 mismatch")


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


def _normalize_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _split_country(value: object) -> tuple[str, str]:
    text = " ".join(str(value or "").strip().split())
    for pattern in (PAREN_COUNTRY_RE, TRAILING_COUNTRY_RE):
        match = pattern.fullmatch(text)
        if match and match.group("country") in COUNTRY_CODES:
            return match.group("name").strip(), match.group("country")
    return text, ""


def _target_seed_id(target_key: str) -> str:
    return f"legacy-winner-{sha256_bytes(target_key.encode('utf-8'))[:20]}"


def _seed_edition_year(seed: Mapping[str, object]) -> int:
    target = seed.get("target")
    if not isinstance(target, Mapping):
        raise ValueError("seed target is missing")
    value = target.get("edition_year")
    if value is None:
        value = target.get("year")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("seed edition year is invalid") from exc


def load_target_artifact(
    root: Path,
    *,
    approved_manifest_sha256: str,
    approved_ledger_sha256: str,
) -> tuple[dict[str, dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("target root must be a regular directory")
    manifest_path = resolved / "target-ledger-manifest.json"
    manifest = _read_json(manifest_path, label="target manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, approved_manifest_sha256, label="target manifest")
    marker = _regular(resolved / "COMPLETE", label="target marker")
    ledger_identity = manifest.get("target_ledger")
    if (
        manifest.get("schema_version") != TARGET_SCHEMA_VERSION
        or manifest.get("status") != "complete"
        or manifest.get("completion_marker") != "COMPLETE"
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or not isinstance(ledger_identity, Mapping)
    ):
        raise ValueError("target artifact is not reviewed COMPLETE")
    ledger_path = resolved / str(ledger_identity.get("path") or "")
    rows = _read_jsonl(ledger_path, label="target ledger")
    ledger_sha = sha256_path(ledger_path)
    _require_sha(ledger_sha, approved_ledger_sha256, label="target ledger")
    if ledger_identity.get("sha256") != ledger_sha or ledger_identity.get("rows") != len(rows):
        raise ValueError("target ledger identity drift")
    by_key = {str(row.get("target_key") or ""): row for row in rows}
    if "" in by_key or len(by_key) != len(rows):
        raise ValueError("target keys are missing or duplicated")
    return by_key, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "ledger_sha256": ledger_sha,
        "rows": len(rows),
    }


def load_held_proposal(
    root: Path,
    *,
    approved_manifest_sha256: str,
    approved_ledger_sha256: str,
    target_identity: Mapping[str, object],
) -> tuple[list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("held proposal root must be a regular directory")
    manifest_path = resolved / "proposal-manifest.json"
    manifest = _read_json(manifest_path, label="held proposal manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, approved_manifest_sha256, label="held proposal manifest")
    marker = _regular(resolved / "PREPARED", label="held proposal marker")
    output = (manifest.get("outputs") or {}).get("held-occurrences.jsonl")
    target = manifest.get("target_artifact")
    if (
        manifest.get("schema_version") != HELD_SCHEMA_VERSION
        or manifest.get("status") != "PREPARED_NOT_EXECUTABLE"
        or manifest.get("execution_ready") is not False
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or not isinstance(output, Mapping)
        or not isinstance(target, Mapping)
        or target.get("manifest_sha256") != target_identity.get("manifest_sha256")
        or target.get("ledger_sha256") != target_identity.get("ledger_sha256")
    ):
        raise ValueError("held proposal contract drift")
    ledger_path = resolved / "held-occurrences.jsonl"
    rows = _read_jsonl(ledger_path, label="held occurrence ledger")
    ledger_sha = sha256_path(ledger_path)
    _require_sha(ledger_sha, approved_ledger_sha256, label="held occurrence ledger")
    if output.get("sha256") != ledger_sha or output.get("rows") != len(rows):
        raise ValueError("held occurrence identity drift")
    keys = [str(row.get("target_key") or "") for row in rows]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise ValueError("held targets are missing or duplicated")
    return rows, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "ledger_sha256": ledger_sha,
        "rows": len(rows),
        "execution_ready": False,
    }


def load_existing_seed_artifact(
    root: Path,
    *,
    approved_manifest_sha256: str,
    approved_ledger_sha256: str,
    target_identity: Mapping[str, object],
) -> tuple[dict[str, dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("existing seed root must be a regular directory")
    manifest_path = resolved / "seed-ledger-manifest.json"
    manifest = _read_json(manifest_path, label="existing seed manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, approved_manifest_sha256, label="existing seed manifest")
    marker = _regular(resolved / "COMPLETE", label="existing seed marker")
    identity = manifest.get("seed_ledger")
    if (
        manifest.get("schema_version") != SEED_MANIFEST_SCHEMA_VERSION
        or manifest.get("status") != "complete"
        or manifest.get("completion_marker") != "COMPLETE"
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or manifest.get("target_manifest_sha256") != target_identity.get("manifest_sha256")
        or manifest.get("target_ledger_sha256") != target_identity.get("ledger_sha256")
        or not isinstance(identity, Mapping)
    ):
        raise ValueError("existing seed artifact contract drift")
    ledger_path = resolved / "targeted-horse-seeds.jsonl"
    rows = _read_jsonl(ledger_path, label="existing seed ledger")
    ledger_sha = sha256_path(ledger_path)
    _require_sha(ledger_sha, approved_ledger_sha256, label="existing seed ledger")
    if identity.get("sha256") != ledger_sha or identity.get("rows") != len(rows):
        raise ValueError("existing seed identity drift")
    by_id = {str(row.get("seed_id") or ""): row for row in rows}
    if "" in by_id or len(by_id) != len(rows) or any(
        row.get("schema_version") != SEED_SCHEMA_VERSION for row in rows
    ):
        raise ValueError("existing seed rows drift")
    return by_id, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "ledger_sha256": ledger_sha,
        "rows": len(rows),
    }


def _safe_source(source: Mapping[str, object]) -> tuple[str, str]:
    url = str(source.get("source_url") or "")
    parsed = urlsplit(url)
    source_sha = str(source.get("sha256") or "")
    cache_path = Path(str(source.get("cache_path") or ""))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or not SHA256_RE.fullmatch(source_sha)
        or not cache_path.is_file()
        or cache_path.is_symlink()
        or sha256_path(cache_path) != source_sha
        or cache_path.stat().st_size != source.get("size")
    ):
        raise ValueError("new winner source evidence drift")
    return url, source_sha


def _validate_existing_seed(
    seed: Mapping[str, object],
    target: Mapping[str, object],
    occurrence: Mapping[str, object],
) -> bool:
    """校验旧 seed 的赛事身份，并返回其冠军名是否仍与当前 held 证据一致。"""

    expected_target = seed.get("target")
    if (
        not isinstance(expected_target, Mapping)
        or expected_target.get("country_region") != occurrence.get("country_region")
        or str(expected_target.get("local_date") or "") != str(occurrence.get("local_date") or "")
        or str(expected_target.get("grade_text") or "") != str(occurrence.get("normalized_grade") or "")
        or str(expected_target.get("discipline") or "") != str(occurrence.get("discipline") or "")
        or int(expected_target.get("edition_year", target.get("year"))) != int(target.get("year"))
        or str(seed.get("expected_finish_position") or "") != "1"
    ):
        raise ValueError("existing seed does not reconcile to held target")
    anchor_name, _anchor_country = _split_country(occurrence.get("anchor_horse_name"))
    seed_name, _seed_country = _split_country(seed.get("name"))
    if not anchor_name or not seed_name:
        raise ValueError("existing seed or held winner name is missing")
    return _normalize_name(seed_name) == _normalize_name(anchor_name)


def _new_seed(target_key: str, target: Mapping[str, object], occurrence: Mapping[str, object]) -> dict:
    starters = occurrence.get("starters")
    source = occurrence.get("source_evidence")
    anchor = str(occurrence.get("anchor_horse_name") or "").strip()
    if not isinstance(starters, list) or not isinstance(source, Mapping) or not anchor:
        raise ValueError("new held target has no official starter evidence")
    winners = [row for row in starters if isinstance(row, Mapping) and row.get("finish_position") == 1]
    if (
        len(winners) != 1
        or _normalize_name(winners[0].get("horse_name")) != _normalize_name(anchor)
        or source.get("source_authority") != "organizer_official"
        or source.get("source_provider") != "france_galop"
        or occurrence.get("country_region") != "france"
    ):
        raise ValueError("new winner candidate is not uniquely organizer-official")
    source_url, source_sha = _safe_source(source)
    name, country_suffix = _split_country(anchor)
    local_date = str(occurrence.get("local_date") or "")
    if not name or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", local_date):
        raise ValueError("new winner name or date is invalid")
    race_names = list(
        dict.fromkeys(
            value
            for value in (
                target.get("original_name"),
                target.get("canonical_name_original"),
                occurrence.get("race_name"),
            )
            if value
        )
    )
    racecourses = list(
        dict.fromkeys(
            value for value in (occurrence.get("racecourse"), target.get("racecourse")) if value
        )
    )
    seed = {
        "schema_version": SEED_SCHEMA_VERSION,
        "seed_id": f"held-winner-{sha256_bytes(target_key.encode('utf-8'))[:20]}",
        "name": name,
        "expected_finish_position": "1",
        "source_authority": "organizer_official",
        "source_url": source_url,
        "source_payload_sha256": source_sha,
        "target": {
            "year": int(local_date[:4]),
            "edition_year": int(target["year"]),
            "country_region": occurrence["country_region"],
            "local_date": local_date,
            "canonical_name_original": target["canonical_name_original"],
            "race_name_aliases": race_names,
            "racecourse": occurrence["racecourse"],
            "racecourse_aliases": racecourses,
            "grade_text": occurrence["normalized_grade"],
            "discipline": occurrence["discipline"],
        },
    }
    if country_suffix:
        seed["country_suffix"] = country_suffix
    return seed


def build_proposal(
    *,
    targets: Mapping[str, dict],
    target_identity: dict,
    occurrences: list[dict],
    held_identity: dict,
    existing_seeds: Mapping[str, dict],
    existing_seed_identity: dict,
    output_dir: Path,
) -> dict:
    if output_dir.exists():
        raise ValueError("output directory must not already exist")
    output_dir.mkdir(parents=True, mode=0o700)
    bindings = []
    candidates = []
    combined = []
    consumed_existing = set()
    reused_existing_count = 0
    replacement_count = 0
    for occurrence in sorted(occurrences, key=lambda row: str(row["target_key"])):
        target_key = str(occurrence["target_key"])
        target = targets.get(target_key)
        if target is None:
            raise ValueError("held occurrence target is absent from COMPLETE target ledger")
        legacy_seed_id = _target_seed_id(target_key)
        existing = existing_seeds.get(legacy_seed_id)
        if existing is not None:
            consumed_existing.add(legacy_seed_id)
            existing_sha = sha256_bytes(canonical_json(existing).encode("utf-8"))
            if _validate_existing_seed(existing, target, occurrence):
                reused_existing_count += 1
                combined.append(dict(existing))
                bindings.append(
                    {
                        "target_key": target_key,
                        "seed_id": legacy_seed_id,
                        "seed_sha256": existing_sha,
                        "disposition": "reuse_existing_complete_seed",
                    }
                )
            else:
                replacement = _new_seed(target_key, target, occurrence)
                replacement_count += 1
                candidates.append(
                    {
                        "target_key": target_key,
                        "seed": replacement,
                        "disposition": "replace_conflicting_existing_seed",
                        "replaced_seed_id": legacy_seed_id,
                        "replaced_seed_sha256": existing_sha,
                        "replaced_winner_name": str(existing.get("name") or ""),
                        "authoritative_winner_name": str(
                            occurrence.get("anchor_horse_name") or ""
                        ),
                    }
                )
                combined.append(replacement)
                bindings.append(
                    {
                        "target_key": target_key,
                        "seed_id": legacy_seed_id,
                        "seed_sha256": existing_sha,
                        "replacement_seed_id": replacement["seed_id"],
                        "replacement_seed_sha256": sha256_bytes(
                            canonical_json(replacement).encode("utf-8")
                        ),
                        "disposition": "replace_conflicting_existing_seed",
                    }
                )
        else:
            seed = _new_seed(target_key, target, occurrence)
            candidates.append(
                {
                    "target_key": target_key,
                    "seed": seed,
                    "disposition": "add_missing_organizer_official_seed",
                }
            )
            combined.append(seed)
    if consumed_existing != set(existing_seeds):
        raise ValueError("existing COMPLETE seeds are not a strict subset of held targets")
    if len(combined) != len(occurrences) or len({row["seed_id"] for row in combined}) != len(combined):
        raise ValueError("combined held seed conservation drift")
    region_counts = Counter(str(row["target"]["country_region"]) for row in combined)
    grade_counts = Counter(str(row["target"]["grade_text"]) for row in combined)
    discipline_counts = Counter(str(row["target"]["discipline"]) for row in combined)
    group_counts = Counter(
        (
            str(row["target"]["country_region"]),
            _seed_edition_year(row),
        )
        for row in combined
    )
    members = {
        "existing-seed-bindings.jsonl": bindings,
        "new-seed-candidates.jsonl": candidates,
        "all-held-targeted-horse-seeds.jsonl": combined,
    }
    identities = {}
    for filename, rows in members.items():
        path = output_dir / filename
        body = b"".join((canonical_json(row) + "\n").encode("utf-8") for row in rows)
        _atomic_write(path, body)
        identities[filename] = {
            "path": filename,
            "rows": len(rows),
            "size": len(body),
            "sha256": sha256_path(path),
        }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PREPARED_NOT_EXECUTABLE",
        "approval": False,
        "execution_ready": False,
        "network_requests": 0,
        "database_writes": 0,
        "generator": {
            "path": Path(__file__).name,
            "sha256": sha256_path(Path(__file__).resolve()),
        },
        "target_artifact": target_identity,
        "held_proposal": held_identity,
        "existing_seed_artifact": existing_seed_identity,
        "counts": {
            "held_targets": len(occurrences),
            "reused_complete_seeds": reused_existing_count,
            "replacement_organizer_official_candidates": replacement_count,
            "new_organizer_official_candidates": len(candidates) - replacement_count,
            "review_candidates_total": len(candidates),
            "combined_seed_candidates": len(combined),
            "by_region": dict(sorted(region_counts.items())),
            "by_grade": dict(sorted(grade_counts.items())),
            "by_discipline": dict(sorted(discipline_counts.items())),
        },
        "non_executable_request_projection": {
            "per_seed_request_ceiling": 16,
            "total_request_ceiling": len(combined) * 16,
            "batch_size_cap": 20,
            "region_edition_year_groups": len(group_counts),
            "projected_batches": sum(ceil(count / 20) for count in group_counts.values()),
            "min_interval_ms": 250,
            "max_requests_per_second": 4,
            "spacing_minutes": 30,
            "max_concurrent_batches": 1,
            "projection_only": True,
        },
        "outputs": identities,
        "execution_blockers": [
            "new and replacement organizer-official winner candidates require exact independent approval",
            "the combined seed ledger is PREPARED and cannot enter a network batch",
            "each future batch still requires fresh exclusive-account proof and exact G3",
        ],
        "completion_marker": "PREPARED",
    }
    manifest_path = output_dir / "proposal-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "PREPARED", (sha256_path(manifest_path) + "\n").encode("ascii"))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--approved-target-manifest-sha256", required=True)
    parser.add_argument("--approved-target-ledger-sha256", required=True)
    parser.add_argument("--held-proposal-root", type=Path, required=True)
    parser.add_argument("--approved-held-manifest-sha256", required=True)
    parser.add_argument("--approved-held-ledger-sha256", required=True)
    parser.add_argument("--existing-seed-root", type=Path, required=True)
    parser.add_argument("--approved-existing-seed-manifest-sha256", required=True)
    parser.add_argument("--approved-existing-seed-ledger-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    targets, target_identity = load_target_artifact(
        args.target_root,
        approved_manifest_sha256=args.approved_target_manifest_sha256,
        approved_ledger_sha256=args.approved_target_ledger_sha256,
    )
    occurrences, held_identity = load_held_proposal(
        args.held_proposal_root,
        approved_manifest_sha256=args.approved_held_manifest_sha256,
        approved_ledger_sha256=args.approved_held_ledger_sha256,
        target_identity=target_identity,
    )
    existing_seeds, existing_seed_identity = load_existing_seed_artifact(
        args.existing_seed_root,
        approved_manifest_sha256=args.approved_existing_seed_manifest_sha256,
        approved_ledger_sha256=args.approved_existing_seed_ledger_sha256,
        target_identity=target_identity,
    )
    manifest = build_proposal(
        targets=targets,
        target_identity=target_identity,
        occurrences=occurrences,
        held_identity=held_identity,
        existing_seeds=existing_seeds,
        existing_seed_identity=existing_seed_identity,
        output_dir=args.output_dir,
    )
    print(canonical_json(manifest["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

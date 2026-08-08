#!/usr/bin/env python3
"""离线审计分级赛参赛马七文件 artifact，不连接网络或数据库。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


REQUIRED_FILES = {
    "README.md",
    "errors.json",
    "horse_name_review_queue_{year}.csv",
    "horse_names_{year}.csv",
    "race_participants_{year}.csv",
    "source_manifest.jsonl",
    "summary.json",
}


class AuditError(ValueError):
    """Artifact 不满足离线审计合同。"""


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AuditError(f"invalid JSONL at {path.name}:{line_number}") from exc
    return rows


def race_identity(row: dict[str, Any]) -> str:
    url = str(row.get("race_url") or row.get("url") or "").strip()
    if url:
        parsed = urlsplit(url)
        if parsed.scheme and parsed.netloc and parsed.path:
            query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
            return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", query, ""))
    slug = str(row.get("slug") or "").strip()
    if slug:
        return slug
    raise AuditError("race row lacks race_url/url/slug identity")


def race_path_alias(row: dict[str, Any]) -> str:
    url = str(row.get("race_url") or row.get("url") or "").strip()
    if url:
        path = urlsplit(url).path.rstrip("/")
        if path:
            return path.rsplit("/", 1)[-1]
    return str(row.get("slug") or "").strip()


def counter_dict(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(value for value in values if value).items()))


def expected_names(year: int) -> set[str]:
    return {name.format(year=year) for name in REQUIRED_FILES}


def verify_file_set(root: Path, year: int) -> dict[str, str]:
    actual = {path.name for path in root.iterdir() if path.is_file()}
    expected = expected_names(year)
    if actual != expected:
        raise AuditError(
            f"artifact file set mismatch: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )
    return {name: sha256_file(root / name) for name in sorted(actual)}


def verify_expected_digests(actual: dict[str, str], expected_path: Path | None) -> None:
    if expected_path is None:
        return
    expected = read_json(expected_path)
    if not isinstance(expected, dict) or set(expected) != set(actual):
        raise AuditError("expected digest manifest must contain exactly the seven artifact filenames")
    mismatches = {
        name: {"expected": str(expected[name]), "actual": actual[name]}
        for name in actual
        if str(expected[name]) != actual[name]
    }
    if mismatches:
        raise AuditError(f"artifact digest mismatch: {json.dumps(mismatches, sort_keys=True)}")


def audit_artifact(
    root: Path,
    *,
    year: int,
    expected_digests: Path | None = None,
    production_snapshot: Path | None = None,
) -> dict[str, Any]:
    if not root.is_dir():
        raise AuditError(f"artifact root is not a directory: {root}")
    file_digests = verify_file_set(root, year)
    verify_expected_digests(file_digests, expected_digests)

    summary = read_json(root / "summary.json")
    if summary.get("year") != year:
        raise AuditError(f"summary year mismatch: expected={year}, actual={summary.get('year')}")
    participants = read_csv(root / f"race_participants_{year}.csv")
    horses = read_csv(root / f"horse_names_{year}.csv")
    review = read_csv(root / f"horse_name_review_queue_{year}.csv")
    errors = read_json(root / "errors.json")
    manifest = read_jsonl(root / "source_manifest.jsonl")
    if not isinstance(errors, list):
        raise AuditError("errors.json must be a JSON array")

    race_ids = {race_identity(row) for row in participants}
    manifest_race_ids = {race_identity(row) for row in manifest}
    if race_ids != manifest_race_ids:
        raise AuditError(
            f"participant/manifest race identity mismatch: "
            f"participant_only={sorted(race_ids - manifest_race_ids)}, "
            f"manifest_only={sorted(manifest_race_ids - race_ids)}"
        )

    actual_counts = {
        "errors": len(errors),
        "included_participant_rows": len(participants),
        "included_races": len(race_ids),
        "unique_horses": len(horses),
        "profile_ambiguous": sum(row.get("profile_resolution_state") == "ambiguous" for row in horses),
        "profile_not_found": sum(row.get("profile_resolution_state") == "not_found" for row in horses),
        "profile_resolved": sum(row.get("profile_resolution_state") == "resolved" for row in horses),
        "profile_unresolved": sum(row.get("profile_resolution_state") == "unresolved" for row in horses),
        "required_english_complete": sum(row.get("required_english_status") == "complete" for row in horses),
        "required_english_missing": sum(row.get("required_english_status") == "missing" for row in horses),
    }
    summary_counts = summary.get("counts") or {}
    mismatches = {
        key: {"summary": summary_counts.get(key), "actual": value}
        for key, value in actual_counts.items()
        if summary_counts.get(key) != value
    }
    if mismatches:
        raise AuditError(f"summary count mismatch: {json.dumps(mismatches, sort_keys=True)}")

    races_by_region: dict[str, set[str]] = defaultdict(set)
    for row in participants:
        races_by_region[row.get("region", "")].add(race_identity(row))

    result: dict[str, Any] = {
        "artifact": {
            "file_count": len(file_digests),
            "file_sha256": file_digests,
            "outcome": summary.get("outcome"),
            "year": year,
        },
        "counts": actual_counts,
        "errors": {
            "by_code": counter_dict(str(row.get("error_code") or "") for row in errors),
            "by_stage": counter_dict(str(row.get("stage") or "") for row in errors),
        },
        "horses": {
            "profile_state_by_region": {},
            "required_english_by_region": {},
        },
        "participants": {
            "rows_by_region": counter_dict(row.get("region", "") for row in participants),
            "races_by_region": {key: len(value) for key, value in sorted(races_by_region.items())},
        },
    }

    profile_by_region: dict[str, Counter[str]] = defaultdict(Counter)
    english_by_region: dict[str, Counter[str]] = defaultdict(Counter)
    for row in horses:
        regions = [value.strip() for value in row.get("regions", "").split(",") if value.strip()]
        for region in regions:
            profile_by_region[region][row.get("profile_resolution_state", "")] += 1
            english_by_region[region][row.get("required_english_status", "")] += 1
    result["horses"]["profile_state_by_region"] = {
        region: dict(sorted(counts.items())) for region, counts in sorted(profile_by_region.items())
    }
    result["horses"]["required_english_by_region"] = {
        region: dict(sorted(counts.items())) for region, counts in sorted(english_by_region.items())
    }

    if len(review) != len({row.get("horse_key") for row in review}):
        raise AuditError("review queue contains duplicate horse_key values")
    result["counts"]["review_queue"] = len(review)

    if production_snapshot is not None:
        snapshot = read_json(production_snapshot)
        events = snapshot.get("events") if isinstance(snapshot, dict) else None
        if not isinstance(events, list):
            raise AuditError("production snapshot must contain an events array")
        alias_candidates: dict[str, set[str]] = defaultdict(set)
        for row in participants:
            alias_candidates[race_path_alias(row)].add(race_identity(row))
        unique_aliases = {
            alias: next(iter(identities))
            for alias, identities in alias_candidates.items()
            if alias and len(identities) == 1
        }
        production_labels: dict[str, str] = {}
        for row in events:
            identity = race_identity(row)
            label = identity
            if not (row.get("race_url") or row.get("url")):
                label = str(row.get("slug") or identity)
                identity = unique_aliases.get(label, identity)
            production_labels[identity] = label
        production_ids = set(production_labels)
        result["production_diff"] = {
            "artifact_only": sorted(race_ids - production_ids),
            "production_only": sorted(production_labels[item] for item in production_ids - race_ids),
            "shared": len(race_ids & production_ids),
        }

    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--expected-file-digests", type=Path)
    parser.add_argument("--production-snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = audit_artifact(
            args.artifact_root,
            year=args.year,
            expected_digests=args.expected_file_digests,
            production_snapshot=args.production_snapshot,
        )
    except (AuditError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"artifact audit failed: {exc}") from exc
    payload = canonical_json_bytes(result)
    if args.output:
        args.output.write_bytes(payload)
    else:
        print(payload.decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

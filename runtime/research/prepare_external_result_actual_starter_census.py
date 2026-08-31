#!/usr/bin/env python3
"""Prepare a non-executable actual-starter census from one frozen result page.

The tool is intentionally retrospective and offline.  It binds an exact manual
result capture and an exact TRA stable-runner ledger, then proves only a
one-to-one name/finish-position comparison for one target occurrence.  The
candidate ``hrs_*`` crosswalk remains unapproved and the census itself never
assigns a provider horse ID.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Mapping


from capture_netkeiba_manual_result_reference import (
    SCHEMA_VERSION as CAPTURE_SCHEMA_VERSION,
    ResultParser,
    parse_result,
)
from prepare_held_winner_seed_extension import (
    _atomic_write,
    _normalize_name,
    _read_json,
    _read_jsonl,
    _regular,
    _require_sha,
    _split_country,
    canonical_json,
    sha256_path,
)


SCHEMA_VERSION = "external-result-actual-starter-census-proposal.v1"
CROSSWALK_SCHEMA_VERSION = "external-result-tra-runner-crosswalk-candidate.v1"
STARTER_SCHEMA_VERSION = "held-actual-starter-occurrence.v1"
SUMMARY_SCHEMA_VERSION = "held-actual-starter-target-summary.v1"
STABLE_LEDGER_SCHEMAS = {
    "target-runner-stable-id-ledger.v1": "targeted-runner-stable-id-seed.v1",
    "target-runner-stable-id-ledger.v2": "targeted-runner-stable-id-seed.v2",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
SEED_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{7,127}$")
TARGET_KEY_RE = re.compile(r"ireland:(?P<year>\d{4}):(?P<series>[a-z0-9-]+):flat$")
NETKEIBA_URL_RE = re.compile(r"https://en\.netkeiba\.com/db/race/[A-Za-z0-9]+/$")


def _output_identity(path: Path, rows: list[dict]) -> dict:
    body = b"".join((canonical_json(row) + "\n").encode("utf-8") for row in rows)
    _atomic_write(path, body)
    return {
        "path": path.name,
        "rows": len(rows),
        "size": len(body),
        "sha256": sha256_path(path),
    }


def _bound_member(
    root: Path,
    identity: object,
    *,
    label: str,
    expected_path: str,
) -> Path:
    if not isinstance(identity, Mapping) or identity.get("path") != expected_path:
        raise ValueError(f"{label} identity is missing or has an unexpected path")
    path = _regular(root / expected_path, label=label)
    if not path.is_relative_to(root):
        raise ValueError(f"{label} escapes capture root")
    if (
        sha256_path(path) != identity.get("sha256")
        or path.stat().st_size != identity.get("size")
    ):
        raise ValueError(f"{label} identity drift")
    return path


def _load_capture(
    root: Path,
    *,
    expected_manifest_sha256: str,
    expected_reference_sha256: str,
    expected_source_sha256: str,
) -> tuple[dict, bytes, dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("manual capture root must be a regular directory")
    manifest_path = _regular(resolved / "capture-manifest.json", label="capture manifest")
    manifest = _read_json(manifest_path, label="capture manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, expected_manifest_sha256, label="capture manifest")
    marker = _regular(resolved / "PREPARED", label="capture marker")
    if (
        manifest.get("schema_version") != CAPTURE_SCHEMA_VERSION
        or manifest.get("status") != "PROPOSED_NOT_APPROVED"
        or manifest.get("completion_marker") != "PREPARED"
        or manifest.get("approval") is not False
        or marker.read_text(encoding="ascii").strip() != manifest_sha
    ):
        raise ValueError("manual capture contract drift")
    reference_path = _bound_member(
        resolved,
        manifest.get("reference"),
        label="winner reference",
        expected_path="winner-reference.json",
    )
    _require_sha(sha256_path(reference_path), expected_reference_sha256, label="winner reference")
    reference = _read_json(reference_path, label="winner reference")
    source_identity = manifest.get("source")
    if not isinstance(source_identity, Mapping) or source_identity.get("path") != "result.html":
        raise ValueError("capture source identity is missing")
    source_path = _regular(resolved / "sources" / "result.html", label="captured result page")
    source_sha = sha256_path(source_path)
    _require_sha(source_sha, expected_source_sha256, label="captured result page")
    source = reference.get("source")
    result = reference.get("result")
    source_url = str(source.get("url") or "") if isinstance(source, Mapping) else ""
    try:
        referenced_cache_path = Path(str(source.get("cache_path") or "")).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("winner reference source path is unavailable") from exc
    if (
        reference.get("schema_version") != CAPTURE_SCHEMA_VERSION
        or reference.get("status") != "proposed_not_approved"
        or reference.get("source_authority") != "human_reviewed_reference"
        or reference.get("systematic_reuse_approved") is not False
        or not isinstance(result, Mapping)
        or not NETKEIBA_URL_RE.fullmatch(source_url)
        or referenced_cache_path != source_path
        or source.get("sha256") != source_sha
        or source.get("size") != source_path.stat().st_size
        or source_identity.get("sha256") != source_sha
        or source_identity.get("size") != source_path.stat().st_size
        or source_identity.get("source_url") != source_url
    ):
        raise ValueError("winner reference and capture source disagree")
    body = source_path.read_bytes()
    try:
        expected_date = date.fromisoformat(str(result.get("local_date") or ""))
    except ValueError as exc:
        raise ValueError("winner reference date is invalid") from exc
    parsed = parse_result(
        body,
        expected_race_name=str(result.get("race_name") or ""),
        expected_date=expected_date,
        expected_grade=str(result.get("grade_text") or ""),
        expected_winner=str(result.get("winner_name") or ""),
    )
    if canonical_json(parsed) != canonical_json(dict(result)):
        raise ValueError("winner reference no longer matches the frozen parser result")
    return reference, body, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "reference_sha256": sha256_path(reference_path),
        "source_sha256": source_sha,
        "source_size": source_path.stat().st_size,
        "source_url": source_url,
        "original_capture_network_requests": manifest.get("network_requests"),
        "status": manifest["status"],
        "systematic_reuse_approved": False,
    }


def _parse_actual_starters(body: bytes) -> list[dict]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("captured result page is not UTF-8") from exc
    parser = ResultParser()
    parser.feed(text)
    table_rows = [row for row in parser.rows if row and row[0].strip().isdigit()]
    if not table_rows:
        raise ValueError("captured result table has no numeric finish rows")
    output = []
    positions = []
    horse_numbers = []
    names = []
    for row in table_rows:
        if len(row) < 15:
            raise ValueError("captured result row is too short for the reviewed parser contract")
        position = int(row[0].strip())
        horse_number = row[2].strip()
        horse_name = " ".join(row[3].split())
        if position <= 0 or not horse_number or not horse_name:
            raise ValueError("captured starter identity is incomplete")
        positions.append(position)
        horse_numbers.append(horse_number)
        names.append(_normalize_name(horse_name))
        output.append(
            {
                "source_order": position,
                "source_runner_key": f"netkeiba_finish:{position}:horse_number:{horse_number}",
                "horse_number": horse_number,
                "draw": "",
                "horse_name": horse_name,
                "jockey_name": row[6].strip(),
                "trainer_name": row[14].strip(),
                "carried_weight": row[5].strip(),
                "odds_value": row[11].strip(),
                "running_status": "finished",
                "source_reported_finish_position": str(position),
                "source_finish_status": "",
                "margin": row[8].strip(),
            }
        )
    if (
        positions != list(range(1, len(output) + 1))
        or len(horse_numbers) != len(set(horse_numbers))
        or "" in names
        or len(names) != len(set(names))
    ):
        raise ValueError("captured result positions, numbers, or names are not one-to-one")
    return output


def _stable_occurrences(
    stable_rows: list[dict],
    *,
    source_targeted_seed_id: str,
) -> tuple[list[dict], dict]:
    observed = []
    for stable in stable_rows:
        horse_id = str(stable.get("horse_id") or "")
        matches = [
            occurrence
            for occurrence in stable.get("target_occurrences", [])
            if isinstance(occurrence, Mapping)
            and occurrence.get("source_targeted_seed_id") == source_targeted_seed_id
        ]
        if len(matches) > 1:
            raise ValueError("stable horse has duplicate occurrences for the source seed")
        if matches:
            occurrence = dict(matches[0])
            occurrence["horse_id"] = horse_id
            observed.append(occurrence)
    if not observed:
        raise ValueError("stable runner ledger has no occurrence for the source seed")
    targets = {canonical_json(row.get("target")) for row in observed}
    race_ids = {str(row.get("race_id") or "") for row in observed}
    race_payloads = {str(row.get("target_race_payload_sha256") or "") for row in observed}
    if (
        len(targets) != 1
        or len(race_ids) != 1
        or "" in race_ids
        or len(race_payloads) != 1
        or any(not SHA256_RE.fullmatch(value) for value in race_payloads)
    ):
        raise ValueError("stable source-seed occurrence identity is inconsistent")
    target = observed[0].get("target")
    if not isinstance(target, Mapping):
        raise ValueError("stable source-seed target is missing")
    return observed, dict(target)


def _load_stable_runner_ledger(
    root: Path,
    *,
    expected_manifest_sha256: str,
) -> tuple[list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("stable runner ledger root must be a regular directory")
    manifest_path = _regular(resolved / "manifest.json", label="stable runner manifest")
    manifest = _read_json(manifest_path, label="stable runner manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, expected_manifest_sha256, label="stable runner manifest")
    marker = _regular(resolved / "COMPLETE", label="stable runner marker")
    identity = manifest.get("seed_ledger")
    expected_row_schema = STABLE_LEDGER_SCHEMAS.get(str(manifest.get("schema_version") or ""))
    if (
        expected_row_schema is None
        or manifest.get("status") != "complete"
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or not isinstance(identity, Mapping)
    ):
        raise ValueError("stable runner ledger contract drift")
    relative = str(identity.get("path") or "")
    if Path(relative).name != relative:
        raise ValueError("stable runner ledger path is invalid")
    ledger_path = _regular(resolved / relative, label="stable runner ledger")
    rows = _read_jsonl(ledger_path, label="stable runner ledger")
    if (
        sha256_path(ledger_path) != identity.get("sha256")
        or ledger_path.stat().st_size != identity.get("size")
        or len(rows) != identity.get("rows")
        or any(row.get("schema_version") != expected_row_schema for row in rows)
    ):
        raise ValueError("stable runner ledger identity drift")
    return rows, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "schema_version": manifest["schema_version"],
        "stable_horse_rows": len(rows),
        "source_target_occurrence_count": manifest.get("source_target_occurrence_count"),
        "unique_target_race_count": manifest.get("unique_target_race_count"),
    }


def _candidate_crosswalk(
    source_rows: list[dict],
    stable_occurrences: list[dict],
    *,
    source_targeted_seed_id: str,
    capture_identity: Mapping[str, object],
    stable_identity: Mapping[str, object],
) -> list[dict]:
    by_key: dict[tuple[str, str], list[dict]] = {}
    for occurrence in stable_occurrences:
        plain_name, country = _split_country(occurrence.get("source_runner_name"))
        key = (_normalize_name(plain_name), str(occurrence.get("source_runner_position") or ""))
        by_key.setdefault(key, []).append({**occurrence, "source_runner_country": country})
    output = []
    matched_horse_ids = set()
    for row in source_rows:
        key = (_normalize_name(row["horse_name"]), row["source_reported_finish_position"])
        matches = by_key.get(key, [])
        if len(matches) != 1:
            raise ValueError("frozen result starter is not a unique name/position TRA match")
        match = matches[0]
        horse_id = str(match.get("horse_id") or "")
        if horse_id in matched_horse_ids:
            raise ValueError("TRA horse ID is duplicated in candidate crosswalk")
        matched_horse_ids.add(horse_id)
        output.append(
            {
                "schema_version": CROSSWALK_SCHEMA_VERSION,
                "status": "candidate_requires_independent_approval",
                "source_targeted_seed_id": source_targeted_seed_id,
                "horse_name": row["horse_name"],
                "source_finish_position": row["source_reported_finish_position"],
                "candidate_provider_horse_id": horse_id,
                "tra_runner_name": match["source_runner_name"],
                "tra_runner_country": match["source_runner_country"],
                "tra_runner_finish_position": str(match["source_runner_position"]),
                "race_id": match["race_id"],
                "source_runner_payload_sha256": match["source_runner_payload_sha256"],
                "target_race_payload_sha256": match["target_race_payload_sha256"],
                "capture_source_sha256": capture_identity["source_sha256"],
                "stable_runner_manifest_sha256": stable_identity["manifest_sha256"],
                "comparison": "unique_normalized_name_without_country_suffix_and_exact_finish_position",
                "provider_horse_id_assigned": False,
            }
        )
    if len(output) != len(stable_occurrences) or len(matched_horse_ids) != len(stable_occurrences):
        raise ValueError("frozen result and TRA runner counts do not conserve")
    return sorted(output, key=lambda row: int(row["source_finish_position"]))


def build_proposal(
    *,
    capture_root: Path,
    expected_capture_manifest_sha256: str,
    expected_reference_sha256: str,
    expected_source_sha256: str,
    stable_runner_ledger_root: Path,
    expected_stable_runner_manifest_sha256: str,
    source_targeted_seed_id: str,
    target_key: str,
    output_dir: Path,
) -> dict:
    target_match = TARGET_KEY_RE.fullmatch(target_key)
    if not target_match or not SEED_ID_RE.fullmatch(source_targeted_seed_id):
        raise ValueError("Ireland target key or source seed ID is invalid")
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("output directory must not already exist")
    reference, body, capture_identity = _load_capture(
        capture_root,
        expected_manifest_sha256=expected_capture_manifest_sha256,
        expected_reference_sha256=expected_reference_sha256,
        expected_source_sha256=expected_source_sha256,
    )
    stable_rows, stable_identity = _load_stable_runner_ledger(
        stable_runner_ledger_root,
        expected_manifest_sha256=expected_stable_runner_manifest_sha256,
    )
    stable_occurrences, target = _stable_occurrences(
        stable_rows,
        source_targeted_seed_id=source_targeted_seed_id,
    )
    result = reference["result"]
    if (
        target.get("country_region") != "ireland"
        or target.get("discipline") != "flat"
        or target.get("local_date") != result.get("local_date")
        or target.get("grade_text") != result.get("grade_text")
        or int(target.get("year") or 0) != int(target_match.group("year"))
        or not str(target.get("canonical_name_original") or "").strip()
        or not str(target.get("racecourse") or "").strip()
    ):
        raise ValueError("frozen result and stable target identity disagree")
    source_rows = _parse_actual_starters(body)
    if len(source_rows) != result.get("parsed_result_rows"):
        raise ValueError("frozen result starter count disagrees with winner reference")
    crosswalk = _candidate_crosswalk(
        source_rows,
        stable_occurrences,
        source_targeted_seed_id=source_targeted_seed_id,
        capture_identity=capture_identity,
        stable_identity=stable_identity,
    )
    source_url = str(capture_identity["source_url"])
    occurrence_key = (
        f"ireland:{result['local_date']}:netkeiba:"
        f"{hashlib.sha256(source_url.encode('utf-8')).hexdigest()[:20]}"
    )
    census_rows = []
    for row in source_rows:
        starter_key_material = canonical_json(
            {
                "occurrence_key": occurrence_key,
                "source_runner_key": row["source_runner_key"],
                "horse_name": row["horse_name"],
            }
        ).encode("utf-8")
        census_rows.append(
            {
                "schema_version": STARTER_SCHEMA_VERSION,
                "starter_occurrence_key": (
                    "external-starter-" + hashlib.sha256(starter_key_material).hexdigest()[:24]
                ),
                "target_key": target_key,
                "occurrence_key": occurrence_key,
                "series_key": target_match.group("series"),
                "country_region": "ireland",
                "edition_year": int(target_match.group("year")),
                "local_date": result["local_date"],
                "race_name": result["race_name"],
                "racecourse": target["racecourse"],
                "grade": result["grade_text"],
                "discipline": "flat",
                "source_order": row["source_order"],
                "source_runner_key": row["source_runner_key"],
                "horse_number": row["horse_number"],
                "draw": row["draw"],
                "horse_name": row["horse_name"],
                "jockey_name": row["jockey_name"],
                "trainer_name": row["trainer_name"],
                "carried_weight": row["carried_weight"],
                "odds_value": row["odds_value"],
                "running_status": row["running_status"],
                "finish_position": int(row["source_reported_finish_position"]),
                "source_finish_status": row["source_finish_status"],
                "margin": row["margin"],
                "actual_start": True,
                "actual_start_evidence": "reviewed_post_race_result_reference",
                "source_provider": "netkeiba_en",
                "source_authority": "human_reviewed_reference",
                "source_url": source_url,
                "source_payload_sha256": capture_identity["source_sha256"],
                "provider_horse_id": None,
                "horse_identity_status": "candidate_crosswalk_requires_independent_approval",
            }
        )
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "target_key": target_key,
        "occurrence_key": occurrence_key,
        "country_region": "ireland",
        "edition_year": int(target_match.group("year")),
        "local_date": result["local_date"],
        "grade": result["grade_text"],
        "discipline": "flat",
        "source_provider": "netkeiba_en",
        "source_authority": "human_reviewed_reference",
        "source_payload_sha256": capture_identity["source_sha256"],
        "parser_contract": "manual-netkeiba-result-reference.v1.numeric-finish-rows",
        "actual_starter_count": len(census_rows),
        "excluded_withdrawn_count": 0,
        "running_status_counts": {"finished": len(census_rows)},
        "provider_horse_ids_assigned": 0,
        "identity_status": "candidate_crosswalk_requires_independent_approval",
    }
    output_dir.mkdir(parents=True, mode=0o700)
    outputs = {
        "actual-starter-census.jsonl": _output_identity(
            output_dir / "actual-starter-census.jsonl", census_rows
        ),
        "target-summary.jsonl": _output_identity(
            output_dir / "target-summary.jsonl", [summary]
        ),
        "candidate-crosswalk.jsonl": _output_identity(
            output_dir / "candidate-crosswalk.jsonl", crosswalk
        ),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PREPARED_NOT_EXECUTABLE",
        "completion_marker": "PREPARED",
        "execution_ready": False,
        "approval": False,
        "network_requests": 0,
        "database_writes": 0,
        "source_targeted_seed_id": source_targeted_seed_id,
        "target_key": target_key,
        "capture": capture_identity,
        "stable_runner_ledger": stable_identity,
        "target": target,
        "counts": {
            "actual_starter_occurrences": len(census_rows),
            "candidate_crosswalk_rows": len(crosswalk),
            "provider_horse_ids_assigned": 0,
            "unmatched_source_rows": 0,
            "unmatched_tra_rows": 0,
        },
        "generator": {
            "path": Path(__file__).name,
            "sha256": sha256_path(Path(__file__).resolve()),
            "capture_parser_path": "capture_netkeiba_manual_result_reference.py",
            "capture_parser_sha256": sha256_path(
                Path(__file__).with_name("capture_netkeiba_manual_result_reference.py")
            ),
        },
        "outputs": outputs,
        "identity_contract": {
            "same_name_rows_merged": False,
            "cross_language_rows_merged": False,
            "provider_horse_ids_assigned": 0,
            "candidate_comparison": "unique normalized name without country suffix plus exact finish position",
        },
        "execution_blockers": [
            "manual source capture explicitly disallows systematic reuse",
            "candidate hrs_* crosswalk requires independent exact-SHA approval",
            "this proposal does not approve held seed extension or TRA reconciliation",
            "future enrichment still requires a fresh exclusive-account proof and exact execution gate",
        ],
    }
    manifest_path = output_dir / "proposal-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "PREPARED", (sha256_path(manifest_path) + "\n").encode("ascii"))
    return manifest


def load_proposal(
    root: Path,
    *,
    expected_manifest_sha256: str,
) -> tuple[list[dict], list[dict], dict]:
    """Load one immutable prepared proposal for later readiness audits."""

    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("external census proposal root must be a regular directory")
    manifest_path = _regular(resolved / "proposal-manifest.json", label="external census manifest")
    manifest = _read_json(manifest_path, label="external census manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, expected_manifest_sha256, label="external census manifest")
    marker = _regular(resolved / "PREPARED", label="external census marker")
    outputs = manifest.get("outputs")
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("status") != "PREPARED_NOT_EXECUTABLE"
        or manifest.get("execution_ready") is not False
        or manifest.get("approval") is not False
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or not isinstance(outputs, Mapping)
    ):
        raise ValueError("external census proposal contract drift")
    loaded = {}
    for filename in (
        "actual-starter-census.jsonl",
        "target-summary.jsonl",
        "candidate-crosswalk.jsonl",
    ):
        identity = outputs.get(filename)
        if not isinstance(identity, Mapping) or identity.get("path") != filename:
            raise ValueError("external census output identity is missing")
        path = _regular(resolved / filename, label=filename)
        rows = _read_jsonl(path, label=filename)
        if (
            sha256_path(path) != identity.get("sha256")
            or path.stat().st_size != identity.get("size")
            or len(rows) != identity.get("rows")
        ):
            raise ValueError("external census output identity drift")
        loaded[filename] = rows
    starters = loaded["actual-starter-census.jsonl"]
    crosswalk = loaded["candidate-crosswalk.jsonl"]
    summaries = loaded["target-summary.jsonl"]
    if (
        not starters
        or len(starters) != len(crosswalk)
        or len(summaries) != 1
        or any(row.get("schema_version") != STARTER_SCHEMA_VERSION for row in starters)
        or any(row.get("schema_version") != CROSSWALK_SCHEMA_VERSION for row in crosswalk)
        or summaries[0].get("schema_version") != SUMMARY_SCHEMA_VERSION
        or manifest.get("counts", {}).get("actual_starter_occurrences") != len(starters)
        or manifest.get("counts", {}).get("candidate_crosswalk_rows") != len(crosswalk)
    ):
        raise ValueError("external census row conservation drift")
    return starters, crosswalk, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "source_targeted_seed_id": manifest.get("source_targeted_seed_id"),
        "target_key": manifest.get("target_key"),
        "stable_runner_manifest_sha256": (
            manifest.get("stable_runner_ledger") or {}
        ).get("manifest_sha256"),
        "starter_rows": len(starters),
        "candidate_crosswalk_rows": len(crosswalk),
        "status": manifest["status"],
        "approval": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--expected-capture-manifest-sha256", required=True)
    parser.add_argument("--expected-reference-sha256", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--stable-runner-ledger-root", type=Path, required=True)
    parser.add_argument("--expected-stable-runner-manifest-sha256", required=True)
    parser.add_argument("--source-targeted-seed-id", required=True)
    parser.add_argument("--target-key", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    try:
        manifest = build_proposal(**vars(parse_args()))
    except (OSError, TypeError, ValueError) as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 1
    print(canonical_json(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

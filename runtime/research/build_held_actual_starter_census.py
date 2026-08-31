#!/usr/bin/env python3
"""Build a non-executable actual-starter census from reviewed held evidence.

The census deliberately preserves one row per race occurrence.  It does not
deduplicate horses by name and it never assigns a The Racing API horse ID.
Those identity operations require a later, evidence-bound API reconciliation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


RESEARCH_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = WORKTREE_ROOT / "server"
for import_root in (RESEARCH_ROOT, SERVER_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from prepare_held_winner_seed_extension import (  # noqa: E402
    _atomic_write,
    _read_json,
    _read_jsonl,
    _regular,
    _require_sha,
    canonical_json,
    load_held_proposal,
    load_target_artifact,
    sha256_bytes,
    sha256_path,
)
from stable.race_reference_parsers import decode_html, reference_runners  # noqa: E402
from stable.race_reference_parsers.sporting_life import (  # noqa: E402
    PARSER_VERSION as SPORTING_LIFE_PARSER_VERSION,
    parse_reference_page as parse_sporting_life_reference,
)
from stable.race_reference_parsers.zeturf import (  # noqa: E402
    PARSER_VERSION as ZETURF_PARSER_VERSION,
    parse_legacy_page as parse_zeturf_legacy,
)


SCHEMA_VERSION = "held-actual-starter-census.v1"
STARTER_SCHEMA_VERSION = "held-actual-starter-occurrence.v1"
SUMMARY_SCHEMA_VERSION = "held-actual-starter-target-summary.v1"
WAYBACK_SCHEMA_VERSION = "wayback-occurrence-owner-approval.v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}$")
SPORTING_LIFE_URL_RE = re.compile(
    r"^/racing/results/(?P<date>\d{4}-\d{2}-\d{2})/"
    r"[^/]+/(?P<race_id>[1-9]\d*)/[^/]+/?$"
)
ZETURF_URL_RE = re.compile(
    r"^/fr/course-du-jour/(?P<date>\d{4}-\d{2}-\d{2})/"
    r"R(?P<meeting>[1-9]\d*)C(?P<race>[1-9]\d*)-[^/]+/?$"
)
ACTUAL_SEMANTIC_STATUSES = {
    "declared",
    "brought_down",
    "did_not_finish",
    "fell",
    "pulled_up",
    "refused",
    "unseated_rider",
    "disqualified",
}
ALL_SEMANTIC_STATUSES = ACTUAL_SEMANTIC_STATUSES | {"withdrawn"}


def _write_jsonl(path: Path, rows: list[dict]) -> dict:
    body = b"".join((canonical_json(row) + "\n").encode("utf-8") for row in rows)
    _atomic_write(path, body)
    return {
        "path": path.name,
        "rows": len(rows),
        "size": len(body),
        "sha256": sha256_path(path),
    }


def _safe_source(
    occurrence: Mapping[str, object],
    *,
    provider: str,
) -> tuple[dict, bytes]:
    source = occurrence.get("source_evidence")
    if not isinstance(source, Mapping):
        raise ValueError("occurrence source evidence is missing")
    source_url = str(source.get("source_url") or "")
    parsed = urlsplit(source_url)
    allowed_hosts = {
        "sporting_life": {"sportinglife.com", "www.sportinglife.com"},
        "zeturf": {"zeturf.fr", "www.zeturf.fr"},
        "france_galop": {"france-galop.com", "www.france-galop.com"},
        "sky_sports": {"web.archive.org"},
    }
    source_sha = str(source.get("sha256") or "")
    source_path = Path(str(source.get("cache_path") or ""))
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold() not in allowed_hosts[provider]
        or parsed.username
        or parsed.password
        or parsed.fragment
        or not SHA256_RE.fullmatch(source_sha)
        or not source_path.is_file()
        or source_path.is_symlink()
    ):
        raise ValueError("occurrence source evidence is unsafe")
    resolved = source_path.resolve(strict=True)
    raw = resolved.read_bytes()
    if (
        hashlib.sha256(raw).hexdigest() != source_sha
        or len(raw) != source.get("size")
        or str(occurrence.get("calendar_source_url") or source_url) != source_url
    ):
        raise ValueError("occurrence source payload identity drift")
    if provider != "sky_sports" and (
        source.get("source_provider") != provider
        or source.get("source_authority")
        not in {"human_reviewed_reference", "organizer_official"}
    ):
        raise ValueError("occurrence source provider or authority drift")
    return {
        "provider": provider,
        "authority": str(
            source.get("source_authority")
            or (occurrence.get("urls") or {}).get("result_url", {}).get("source_authority")
            or "human_reviewed_reference"
        ),
        "url": source_url,
        "payload_sha256": source_sha,
        "cache_path": str(resolved),
    }, raw


def load_wayback_approval(
    root: Path,
    *,
    approved_manifest_sha256: str,
    target_identity: Mapping[str, object],
) -> tuple[dict, list[dict], dict]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("Wayback approval root must be a regular directory")
    manifest_path = resolved / "approval-manifest.json"
    manifest = _read_json(manifest_path, label="Wayback approval manifest")
    manifest_sha = sha256_path(manifest_path)
    _require_sha(manifest_sha, approved_manifest_sha256, label="Wayback approval manifest")
    marker = _regular(resolved / "APPROVED", label="Wayback approval marker")
    outputs = manifest.get("outputs")
    target = manifest.get("target_artifact")
    if (
        manifest.get("schema_version") != WAYBACK_SCHEMA_VERSION
        or manifest.get("status") != "approved"
        or manifest.get("completion_marker") != "APPROVED"
        or marker.read_text(encoding="ascii").strip() != manifest_sha
        or not isinstance(outputs, Mapping)
        or not isinstance(target, Mapping)
        or target.get("manifest_sha256") != target_identity.get("manifest_sha256")
        or target.get("ledger_sha256") != target_identity.get("ledger_sha256")
    ):
        raise ValueError("Wayback approval contract drift")
    loaded: dict[str, list[dict] | dict] = {}
    for filename, label, jsonl in (
        ("approved-occurrence.jsonl", "Wayback approved occurrence", True),
        ("actual-starters.jsonl", "Wayback actual starters", True),
        ("approved-review.json", "Wayback approved review", False),
    ):
        identity = outputs.get(filename)
        if not isinstance(identity, Mapping):
            raise ValueError("Wayback approval output identity is missing")
        path = resolved / filename
        rows = _read_jsonl(path, label=label) if jsonl else _read_json(path, label=label)
        row_count = len(rows) if isinstance(rows, list) else 1
        if (
            sha256_path(path) != identity.get("sha256")
            or path.stat().st_size != identity.get("size")
            or row_count != identity.get("rows")
        ):
            raise ValueError("Wayback approval output identity drift")
        loaded[filename] = rows
    occurrences = loaded["approved-occurrence.jsonl"]
    starters = loaded["actual-starters.jsonl"]
    if (
        not isinstance(occurrences, list)
        or len(occurrences) != 1
        or not isinstance(starters, list)
        or not starters
        or manifest.get("actual_starter_count") != len(starters)
    ):
        raise ValueError("Wayback approved starter conservation drift")
    return occurrences[0], starters, {
        "root": str(resolved),
        "manifest_sha256": manifest_sha,
        "actual_starters_sha256": outputs["actual-starters.jsonl"]["sha256"],
        "actual_starter_rows": len(starters),
        "status": "approved",
    }


def _validate_target(
    target: Mapping[str, object],
    occurrence: Mapping[str, object],
) -> None:
    if (
        target.get("target_key") != occurrence.get("target_key")
        or target.get("country_region") != occurrence.get("country_region")
        or target.get("discipline") != occurrence.get("discipline")
        or target.get("grade_text") != occurrence.get("normalized_grade")
        or int(target.get("year") or 0) != int(occurrence.get("edition_year") or 0)
        or not DATE_RE.fullmatch(str(occurrence.get("local_date") or ""))
    ):
        raise ValueError("held occurrence disagrees with reviewed target")


def _common_status(running_status: str, finish_position: str) -> str:
    if running_status == "declared":
        return "finished" if finish_position else "actual_starter_result_unclassified"
    return running_status


def _filter_semantic_runners(runners: list[dict]) -> tuple[list[dict], int]:
    if not runners:
        raise ValueError("semantic runner list is empty")
    keys = []
    actual = []
    withdrawn = 0
    for row in runners:
        status = str(row.get("running_status") or "")
        key = str(row.get("source_runner_key") or "")
        name = str(row.get("horse_name") or "").strip()
        if status not in ALL_SEMANTIC_STATUSES:
            raise ValueError(f"unsupported semantic runner status: {status or 'empty'}")
        if not key or not name:
            raise ValueError("semantic runner identity is missing")
        keys.append(key)
        if status == "withdrawn":
            withdrawn += 1
        else:
            actual.append(dict(row))
    if len(keys) != len(set(keys)):
        raise ValueError("semantic runner keys are duplicated")
    if not actual:
        raise ValueError("semantic runner list has no actual starters")
    return actual, withdrawn


def _parse_reference_occurrence(
    occurrence: Mapping[str, object],
    *,
    provider: str,
) -> tuple[list[dict], int, str, dict]:
    source, raw = _safe_source(occurrence, provider=provider)
    source_url = source["url"]
    path = urlsplit(source_url).path
    local_date = str(occurrence.get("local_date") or "")
    if provider == "sporting_life":
        match = SPORTING_LIFE_URL_RE.fullmatch(path)
        if match is None or match.group("date") != local_date:
            raise ValueError("Sporting Life URL/date identity drift")
        parsed = parse_sporting_life_reference(
            raw,
            source_url,
            {"race_id": int(match.group("race_id"))},
        )
        if (
            parsed.get("race", {}).get("local_date") != local_date
            or parsed.get("completeness", {}).get("race_identity") != "complete"
            or parsed.get("completeness", {}).get("runners") != "complete"
        ):
            raise ValueError("Sporting Life parser did not prove the reviewed race runners")
        semantic = parsed["runners"]
        parser_contract = f"sporting_life.{SPORTING_LIFE_PARSER_VERSION}"
    else:
        match = ZETURF_URL_RE.fullmatch(path)
        if match is None or match.group("date") != local_date:
            raise ValueError("ZEturf URL/date identity drift")
        legacy_runners, results, metadata = parse_zeturf_legacy(
            decode_html(raw),
            source_url=source_url,
        )
        if metadata.get("date") != local_date:
            raise ValueError("ZEturf page title date disagrees with reviewed occurrence")
        semantic = reference_runners(legacy_runners, results)
        parser_contract = f"zeturf.{ZETURF_PARSER_VERSION}.reviewed-url-legacy-payload"
    actual, withdrawn = _filter_semantic_runners(semantic)
    old_names = set(str(value) for value in occurrence.get("actual_starter_names") or [])
    actual_names = set(str(row["horse_name"]) for row in actual)
    if not old_names or not old_names.issubset(actual_names):
        raise ValueError("semantic census lost a previously reviewed placed starter")
    anchor = str(occurrence.get("anchor_horse_name") or "")
    if anchor not in actual_names:
        raise ValueError("semantic census lost the reviewed winner anchor")
    return actual, withdrawn, parser_contract, source


def _france_starters(occurrence: Mapping[str, object]) -> tuple[list[dict], int, str, dict]:
    source, _raw = _safe_source(occurrence, provider="france_galop")
    starters = occurrence.get("starters")
    if (
        occurrence.get("country_region") != "france"
        or source["authority"] != "organizer_official"
        or not isinstance(starters, list)
        or not starters
        or occurrence.get("actual_starter_count") != len(starters)
    ):
        raise ValueError("France Galop actual-starter list contract drift")
    output = []
    keys = []
    for row in starters:
        if not isinstance(row, Mapping):
            raise ValueError("France Galop starter row is invalid")
        name = str(row.get("horse_name") or "").strip()
        try:
            source_order = int(row.get("source_order"))
        except (TypeError, ValueError) as exc:
            raise ValueError("France Galop starter source order is invalid") from exc
        if not name or source_order <= 0:
            raise ValueError("France Galop starter identity is missing")
        finish_position = row.get("finish_position")
        if finish_position is not None and (
            isinstance(finish_position, bool)
            or not isinstance(finish_position, int)
            or finish_position <= 0
        ):
            raise ValueError("France Galop starter finish position is invalid")
        finish_status = str(row.get("finish_status") or "")
        if finish_position:
            running_status = "finished"
        elif finish_status == "ARR":
            running_status = "pulled_up"
        elif finish_status.casefold() in {"tbé", "tbe"} or re.search(
            r"\btbé\s*$", str(row.get("raw_first_line") or ""), flags=re.IGNORECASE
        ):
            running_status = "fell"
        else:
            running_status = "actual_starter_result_unclassified"
        key = f"france_galop_order:{source_order}"
        keys.append(key)
        output.append(
            {
                "source_runner_key": key,
                "source_order": source_order,
                "horse_number": "",
                "draw": "",
                "horse_name": name,
                "jockey_name": "",
                "trainer_name": "",
                "carried_weight": "",
                "odds_value": "",
                "running_status": running_status,
                "source_reported_finish_position": str(finish_position or ""),
                "source_finish_status": finish_status,
                "margin": "",
            }
        )
    if len(keys) != len(set(keys)):
        raise ValueError("France Galop starter source orders are duplicated")
    if str(occurrence.get("anchor_horse_name") or "") not in {
        row["horse_name"] for row in output
    }:
        raise ValueError("France Galop starter list lost the reviewed winner anchor")
    return output, 0, "france_galop.reviewed-official-actual-starter-list", source


def _wayback_starters(
    occurrence: Mapping[str, object],
    *,
    approved_occurrence: Mapping[str, object],
    approved_starters: list[dict],
) -> tuple[list[dict], int, str, dict]:
    if canonical_json(occurrence) != canonical_json(approved_occurrence):
        raise ValueError("held Wayback occurrence is not the exact approved occurrence")
    source, _raw = _safe_source(occurrence, provider="sky_sports")
    output = []
    keys = []
    for index, row in enumerate(approved_starters, start=1):
        name = str(row.get("horse_name") or "").strip()
        number = str(row.get("horse_number") or "").strip()
        position = row.get("finish_position")
        finish_status = str(row.get("finish_status") or "")
        if not name or not number:
            raise ValueError("Wayback approved starter identity is missing")
        if position is not None and (
            isinstance(position, bool) or not isinstance(position, int) or position <= 0
        ):
            raise ValueError("Wayback approved finish position is invalid")
        if position:
            running_status = "finished"
        elif finish_status == "PU":
            running_status = "pulled_up"
        else:
            raise ValueError("Wayback approved nonfinish status is unsupported")
        key = f"sky_sports_number:{number}"
        keys.append(key)
        output.append(
            {
                "source_runner_key": key,
                "source_order": index,
                "horse_number": number,
                "draw": "",
                "horse_name": name,
                "jockey_name": "",
                "trainer_name": "",
                "carried_weight": "",
                "odds_value": "",
                "running_status": running_status,
                "source_reported_finish_position": str(position or ""),
                "source_finish_status": finish_status,
                "margin": "",
            }
        )
    if len(keys) != len(set(keys)):
        raise ValueError("Wayback approved horse numbers are duplicated")
    if str(occurrence.get("anchor_horse_name") or "") not in {
        row["horse_name"] for row in output
    }:
        raise ValueError("Wayback approved starters lost the reviewed winner anchor")
    return output, 0, "sky_sports.owner-approved-wayback-actual-starters", source


def _starter_row(
    occurrence: Mapping[str, object],
    runner: Mapping[str, object],
    *,
    source: Mapping[str, object],
    source_order: int,
) -> dict:
    target_key = str(occurrence["target_key"])
    occurrence_key = str(occurrence["occurrence_key"])
    source_runner_key = str(runner["source_runner_key"])
    starter_key_basis = {
        "target_key": target_key,
        "occurrence_key": occurrence_key,
        "source_provider": source["provider"],
        "source_runner_key": source_runner_key,
    }
    finish_position = str(runner.get("source_reported_finish_position") or "")
    running_status = str(runner.get("running_status") or "")
    return {
        "schema_version": STARTER_SCHEMA_VERSION,
        "starter_occurrence_key": (
            "held-starter-" + sha256_bytes(canonical_json(starter_key_basis).encode("utf-8"))[:24]
        ),
        "target_key": target_key,
        "occurrence_key": occurrence_key,
        "series_key": occurrence["series_key"],
        "edition_year": occurrence["edition_year"],
        "country_region": occurrence["country_region"],
        "discipline": occurrence["discipline"],
        "grade": occurrence["normalized_grade"],
        "local_date": occurrence["local_date"],
        "race_name": occurrence["race_name"],
        "racecourse": occurrence["racecourse"],
        "source_order": source_order,
        "source_runner_key": source_runner_key,
        "horse_name": runner["horse_name"],
        "horse_number": str(runner.get("horse_number") or ""),
        "draw": str(runner.get("draw") or ""),
        "jockey_name": str(runner.get("jockey_name") or ""),
        "trainer_name": str(runner.get("trainer_name") or ""),
        "carried_weight": str(runner.get("carried_weight") or ""),
        "odds_value": str(runner.get("odds_value") or ""),
        "finish_position": int(finish_position) if finish_position else None,
        "source_finish_status": str(runner.get("source_finish_status") or ""),
        "running_status": _common_status(running_status, finish_position)
        if running_status in ACTUAL_SEMANTIC_STATUSES
        else running_status,
        "margin": str(runner.get("margin") or ""),
        "actual_start": True,
        "actual_start_evidence": "reviewed_post_race_runner_or_official_starter_list",
        "source_provider": source["provider"],
        "source_authority": source["authority"],
        "source_url": source["url"],
        "source_payload_sha256": source["payload_sha256"],
        "provider_horse_id": None,
        "horse_identity_status": "requires_the_racing_api_occurrence_reconciliation",
    }


def build_census(
    *,
    targets: Mapping[str, dict],
    target_identity: dict,
    occurrences: list[dict],
    held_identity: dict,
    wayback_occurrence: Mapping[str, object],
    wayback_starters: list[dict],
    wayback_identity: dict,
    output_dir: Path,
) -> dict:
    if output_dir.exists():
        raise ValueError("output directory must not already exist")
    output_dir.mkdir(parents=True, mode=0o700)
    all_rows = []
    summaries = []
    target_keys = set()
    for occurrence in sorted(occurrences, key=lambda row: str(row.get("target_key") or "")):
        target_key = str(occurrence.get("target_key") or "")
        target = targets.get(target_key)
        if target is None or target_key in target_keys:
            raise ValueError("held target is absent or duplicated")
        target_keys.add(target_key)
        _validate_target(target, occurrence)
        evidence = occurrence.get("source_evidence")
        evidence_provider = evidence.get("source_provider") if isinstance(evidence, Mapping) else None
        if evidence_provider in {"sporting_life", "zeturf"}:
            runners, withdrawn, parser_contract, source = _parse_reference_occurrence(
                occurrence,
                provider=str(evidence_provider),
            )
        elif evidence_provider == "france_galop":
            runners, withdrawn, parser_contract, source = _france_starters(occurrence)
        elif occurrence.get("occurrence_key") == wayback_occurrence.get("occurrence_key"):
            runners, withdrawn, parser_contract, source = _wayback_starters(
                occurrence,
                approved_occurrence=wayback_occurrence,
                approved_starters=wayback_starters,
            )
        else:
            raise ValueError("held occurrence source provider is unsupported")
        rows = [
            _starter_row(
                occurrence,
                runner,
                source=source,
                source_order=int(runner.get("source_order") or index),
            )
            for index, runner in enumerate(runners, start=1)
        ]
        row_keys = [row["starter_occurrence_key"] for row in rows]
        if len(row_keys) != len(set(row_keys)):
            raise ValueError("starter occurrence keys are duplicated within a target")
        statuses = Counter(row["running_status"] for row in rows)
        summaries.append(
            {
                "schema_version": SUMMARY_SCHEMA_VERSION,
                "target_key": target_key,
                "occurrence_key": occurrence["occurrence_key"],
                "country_region": occurrence["country_region"],
                "edition_year": occurrence["edition_year"],
                "local_date": occurrence["local_date"],
                "grade": occurrence["normalized_grade"],
                "discipline": occurrence["discipline"],
                "source_provider": source["provider"],
                "source_authority": source["authority"],
                "source_payload_sha256": source["payload_sha256"],
                "parser_contract": parser_contract,
                "actual_starter_count": len(rows),
                "excluded_withdrawn_count": withdrawn,
                "running_status_counts": dict(sorted(statuses.items())),
                "provider_horse_ids_assigned": 0,
                "identity_status": "requires_the_racing_api_occurrence_reconciliation",
            }
        )
        all_rows.extend(rows)
    if target_keys != {str(row.get("target_key") or "") for row in occurrences}:
        raise ValueError("held target conservation drift")
    all_keys = [row["starter_occurrence_key"] for row in all_rows]
    if len(all_keys) != len(set(all_keys)):
        raise ValueError("starter occurrence keys are globally duplicated")
    by_region = Counter(row["country_region"] for row in all_rows)
    by_provider = Counter(row["source_provider"] for row in all_rows)
    by_grade = Counter(row["grade"] for row in all_rows)
    by_discipline = Counter(row["discipline"] for row in all_rows)
    by_status = Counter(row["running_status"] for row in all_rows)
    identities = {
        "held-actual-starter-census.jsonl": _write_jsonl(
            output_dir / "held-actual-starter-census.jsonl", all_rows
        ),
        "target-summaries.jsonl": _write_jsonl(
            output_dir / "target-summaries.jsonl", summaries
        ),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PREPARED_NOT_EXECUTABLE",
        "execution_ready": False,
        "approval": False,
        "network_requests": 0,
        "database_writes": 0,
        "generator": {
            "path": Path(__file__).name,
            "sha256": sha256_path(Path(__file__).resolve()),
        },
        "target_artifact": target_identity,
        "held_proposal": held_identity,
        "wayback_approval": wayback_identity,
        "counts": {
            "held_targets": len(summaries),
            "actual_starter_occurrences": len(all_rows),
            "excluded_withdrawals": sum(row["excluded_withdrawn_count"] for row in summaries),
            "unique_exact_name_strings_recall_only_not_horse_identities": len(
                {str(row["horse_name"]) for row in all_rows}
            ),
            "by_region": dict(sorted(by_region.items())),
            "by_provider": dict(sorted(by_provider.items())),
            "by_grade": dict(sorted(by_grade.items())),
            "by_discipline": dict(sorted(by_discipline.items())),
            "by_running_status": dict(sorted(by_status.items())),
        },
        "identity_contract": {
            "unit": "one actual starter in one reviewed race occurrence",
            "same_name_rows_merged": False,
            "cross_language_rows_merged": False,
            "source_runner_keys_are_not_the_racing_api_horse_ids": True,
            "provider_horse_ids_assigned": 0,
            "next_required_step": "The Racing API occurrence/date/result reconciliation before profile export",
        },
        "outputs": identities,
        "execution_blockers": [
            "census rows are occurrence evidence, not stable horse identities",
            "no row may enter a profile batch until The Racing API occurrence reconciliation assigns a provider horse ID",
            "a future network batch still requires an approved rate plan and fresh exclusive-account proof",
        ],
        "completion_marker": "PREPARED",
    }
    manifest_path = output_dir / "census-manifest.json"
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
    parser.add_argument("--wayback-approval-root", type=Path, required=True)
    parser.add_argument("--approved-wayback-manifest-sha256", required=True)
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
    wayback_occurrence, wayback_starters, wayback_identity = load_wayback_approval(
        args.wayback_approval_root,
        approved_manifest_sha256=args.approved_wayback_manifest_sha256,
        target_identity=target_identity,
    )
    manifest = build_census(
        targets=targets,
        target_identity=target_identity,
        occurrences=occurrences,
        held_identity=held_identity,
        wayback_occurrence=wayback_occurrence,
        wayback_starters=wayback_starters,
        wayback_identity=wayback_identity,
        output_dir=args.output_dir,
    )
    print(canonical_json(manifest["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

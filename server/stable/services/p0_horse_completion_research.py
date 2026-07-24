"""Deterministic research-v3 converter and approval write-back for rolling batches.

Bridges the rolling batch crawl artifact into the existing reviewed commit
chain: ``build_region_research_v3`` converts batch payloads into the
``p0-horse-research.v3`` shape as a pure function (same input bytes always
produce the same output), and ``build_region_approval_bundle`` records the
human module-approval decision as mapping decisions + an authority manifest
that ``prepare_reviewed_p0_completion_artifact`` consumes unchanged.

US rolling batches are deliberately fail-closed here: the frozen-batch US
combined-source approval does not extend to rolling batches, so an approved
US authority manifest must come from the dedicated review flow.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from stable.services.p0_horse_completion_batch import (
    BatchRunState,
    P0_HORSE_BATCH_MANIFEST_FILENAME,
    P0HorseBatchError,
    _append_approvals_ledger,
    _utcnow_iso,
    load_batch_manifest,
    read_approvals_ledger,
)
from stable.services.p0_horse_profiles import (
    FULL_PROFILE_COMPLETENESS_POLICY_VERSION,
    REQUIRED_COMPLETION_MODULES,
)
from stable.services.p0_horse_production_apply import (
    MIN_FORMAL_CONFIDENCE,
    build_profile_mapping_snapshot,
    build_profile_snapshot,
    deterministic_identity_key,
)
from stable.services.p0_horse_production_apply import _digest as _apply_digest

RESEARCH_SCHEMA = "p0-horse-research.v3"
MAPPING_SCHEMA = "p0-horse-profile-mapping-decisions.v1"
AUTHORITY_SCHEMA = "p0-horse-us-career-source-authority-review.v1"


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_canonical(path: Path, payload: Any) -> str:
    content = _canonical_bytes(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(content)
    tmp_path.replace(path)
    return _sha256_bytes(content)


def _valid_http_url(value: Any) -> bool:
    text = str(value or "").strip()
    return text.startswith("https://") or text.startswith("http://")


def _payload_source(payload: dict[str, Any]) -> dict[str, Any]:
    evidence = [
        item
        for item in payload.get("source_evidence") or []
        if isinstance(item, dict)
    ]
    url = next(
        (str(item.get("source_url")).strip() for item in evidence if _valid_http_url(item.get("source_url"))),
        "",
    )
    name = str(payload.get("source_name") or "").strip()
    if not name and evidence:
        name = str(evidence[0].get("source_name") or "").strip()
    return {
        "name": name,
        "url": url,
        "external_horse_id": str(payload.get("external_horse_id") or "").strip(),
    }


def _payload_profile_id(candidate_key: str) -> int | None:
    prefix = "profile:"
    if candidate_key.startswith(prefix):
        try:
            return int(candidate_key[len(prefix) :])
        except ValueError:
            return None
    return None


def convert_payload_to_research_horse(payload: dict[str, Any]) -> dict[str, Any]:
    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    career_history = (
        payload.get("career_history")
        if isinstance(payload.get("career_history"), dict)
        else {}
    )
    region = str(payload.get("region") or "")
    return {
        "identity": {
            "horse_name": str(identity.get("horse_name") or "").strip(),
            "sire_name": str(identity.get("sire_name") or "").strip(),
            "dam_name": str(identity.get("dam_name") or "").strip(),
            "birth_year": identity.get("birth_year"),
        },
        "region": region,
        "source": _payload_source(payload),
        "candidate": {
            "candidate_key": payload.get("candidate_key", ""),
            "sample_region": region,
            "profile_id": _payload_profile_id(str(payload.get("candidate_key") or "")),
        },
        "source_evidence": payload.get("source_evidence") or [],
        "basic_profile": payload.get("basic_profile") or {},
        "basic_profile_field_evidence": payload.get("basic_profile_field_evidence") or [],
        "pedigree": payload.get("pedigree") or {},
        "pedigree_field_evidence": payload.get("pedigree_field_evidence") or [],
        "aliases": payload.get("aliases") or [],
        "career": {
            "records": payload.get("race_records") or [],
            "career_collection_status": (
                "complete"
                if career_history.get("status") == "complete"
                else "incomplete"
            ),
            "official_or_source_start_count": career_history.get(
                "official_or_source_start_count"
            ),
            "official_start_count_source": career_history.get(
                "official_start_count_source", ""
            ),
            "official_start_count_source_url": career_history.get(
                "official_start_count_source_url", ""
            ),
            "official_start_count_verified_at": career_history.get(
                "official_start_count_verified_at", ""
            ),
            "record_authority_status": career_history.get(
                "record_authority_status", ""
            ),
        },
        "confidence": int(payload.get("confidence") or 0),
    }


def build_region_research_v3(
    artifact_dir: str | Path,
    *,
    region: str,
) -> dict[str, Any]:
    """Pure converter: batch combined candidates -> research v3 (per region).

    Blocked payloads (any failure_reason) are excluded; they belong to the
    review exception page and the blocker pool, never to research input.
    """
    combined_path = Path(artifact_dir) / "combined_candidates.jsonl"
    try:
        lines = combined_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise P0HorseBatchError(
            f"batch combined candidates are unreadable: {combined_path}"
        ) from exc
    horses: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload.get("region") != region:
            continue
        if payload.get("failure_reason"):
            continue
        horses.append(convert_payload_to_research_horse(payload))
    horses.sort(
        key=lambda horse: deterministic_identity_key(horse["identity"])
    )
    combined_sha = _sha256_bytes(combined_path.read_bytes())
    return {
        "schema_version": RESEARCH_SCHEMA,
        "generated_from": {
            "kind": "p0-horse-completion-batch",
            "region": region,
            "combined_candidates_sha256": combined_sha,
        },
        "horses": horses,
    }


def write_region_research(
    research: dict[str, Any],
    *,
    output_dir: str | Path,
    region: str,
) -> tuple[Path, str]:
    path = Path(output_dir) / f"research_v3_{region}.json"
    sha = _write_canonical(path, research)
    return path, sha


def _derive_records_synced_through(approved_at: str) -> str:
    """Sync-through marker for rolling batches: the human approval date.

    For active horses the strict gate requires a fresh sync window, and for
    retired horses it requires coverage at least through the latest race
    date; the approval date (immediately after the batch fetch) satisfies
    both truthfully. Deriving from the max race date would silently mark
    stale sync windows as fresh.
    """
    return approved_at[:10]


def build_region_approval_bundle(
    *,
    research_path: str | Path,
    region: str,
    reviewer,
    output_dir: str | Path,
    batch_dir: str | Path,
    racing_career_status: str = "active",
    decision_source_reference: str = "p0-horse-completion-batch",
    now=None,
) -> dict[str, Any]:
    """Record the human module approval as commit-chain inputs.

    Produces the mapping decisions document and (empty-US) authority manifest
    for one region, rewrites the research file with the authority application
    binding, and appends the approvals ledger entry. US horses fail closed:
    rolling US batches require a separately approved authority manifest.
    """
    if racing_career_status not in ("active", "retired"):
        raise P0HorseBatchError("racing_career_status must be active or retired")
    research_file = Path(research_path)
    try:
        draft_bytes = research_file.read_bytes()
        research = json.loads(draft_bytes)
    except (OSError, ValueError) as exc:
        raise P0HorseBatchError(f"research v3 is unreadable: {research_file}") from exc
    if research.get("schema_version") != RESEARCH_SCHEMA:
        raise P0HorseBatchError("research v3 schema is invalid")
    if research.get("career_authority_review_application"):
        raise P0HorseBatchError(
            "research v3 already carries an authority application; regenerate it"
        )
    draft_sha = _sha256_bytes(draft_bytes)
    horses = research.get("horses") or []
    us_horses = [horse for horse in horses if horse.get("region") == "united_states"]
    if us_horses:
        raise P0HorseBatchError(
            "US rolling batches require a separately approved authority manifest; "
            "the frozen-batch US combined-source approval does not extend to rolling batches"
        )

    approved_at = _utcnow_iso(now)
    reviewer_name = reviewer.get_username()
    review_metadata = {
        "reviewed_by": reviewer_name,
        "approved_at": approved_at,
        "decision_source_reference": str(decision_source_reference),
    }
    synced_through = _derive_records_synced_through(approved_at)

    rows: list[dict[str, Any]] = []
    for horse in horses:
        identity = horse["identity"]
        confidence = int(horse.get("confidence") or 0)
        if confidence < MIN_FORMAL_CONFIDENCE:
            raise P0HorseBatchError(
                f"{identity.get('horse_name')} confidence {confidence} is below "
                f"{MIN_FORMAL_CONFIDENCE}; exclude it from the batch instead"
            )
        snapshot = build_profile_mapping_snapshot(identity)
        name_matches = snapshot["data"]["name_match_profiles"]
        if len(name_matches) > 1:
            raise P0HorseBatchError(
                f"{identity.get('horse_name')} has multiple name-match profiles; "
                "resolve the identity conflict before approval"
            )
        module_reviews = {
            module: {
                "status": "approved",
                "confidence": confidence,
                **review_metadata,
            }
            for module in REQUIRED_COMPLETION_MODULES
        }
        completion_decision = {
            "racing_career_status": racing_career_status,
            "records_synced_through": synced_through,
            **review_metadata,
        }
        row: dict[str, Any] = {
            "identity": identity,
            "decision_evidence": dict(review_metadata),
            "module_reviews": module_reviews,
            "completion_decision": completion_decision,
            "database_mapping_snapshot": snapshot,
        }
        if name_matches:
            profile_id = name_matches[0]["profile_id"]
            from stable.models import HorseProfile

            profile = HorseProfile.objects.filter(pk=profile_id).first()
            if profile is None:
                raise P0HorseBatchError(
                    f"name-match profile {profile_id} no longer exists"
                )
            row.update(
                {
                    "decision": "bind_existing",
                    "profile_id": profile_id,
                    "profile_snapshot": build_profile_snapshot(profile),
                    "name_evidence": identity["horse_name"],
                    "rejected_profile_ids": [],
                    "rejection_reason": "",
                }
            )
        else:
            row.update({"decision": "create_new", "profile_id": None})
        rows.append(row)

    production_snapshot_payload = [
        {
            "identity_key": deterministic_identity_key(row["identity"]),
            "database_mapping_snapshot": row["database_mapping_snapshot"],
        }
        for row in sorted(
            rows,
            key=lambda row: deterministic_identity_key(row["identity"]),
        )
    ]

    out_dir = Path(output_dir)
    authority = {
        "schema_version": AUTHORITY_SCHEMA,
        "review_status": "approved",
        **review_metadata,
        "input": {
            "kind": "p0-horse-completion-batch-research-draft",
            "path": str(research_file),
            "sha256": draft_sha,
        },
        "horses": [],
    }
    authority_path = out_dir / f"authority_manifest_{region}.json"
    authority_sha = _write_canonical(authority_path, authority)

    research["career_authority_review_application"] = {
        "review_artifact_sha256": authority_sha,
        "input_sha256": draft_sha,
        "approved_horse_count": 0,
    }
    final_research_sha = _write_canonical(research_file, research)

    mapping = {
        "schema_version": MAPPING_SCHEMA,
        "review_status": "approved",
        "reviewer_id": reviewer.id,
        **review_metadata,
        "research_v3_sha256": final_research_sha,
        "production_snapshot_sha256": _apply_digest(production_snapshot_payload),
        "rows": rows,
    }
    mapping_path = out_dir / f"mapping_decisions_{region}.json"
    mapping_sha = _write_canonical(mapping_path, mapping)

    ledger_entry = {
        "event": "region_modules_approved",
        "region": region,
        "research_sha256": final_research_sha,
        "mapping_sha256": mapping_sha,
        "authority_sha256": authority_sha,
        "reviewer": reviewer_name,
        "approved_at": approved_at,
        "horse_count": len(rows),
    }
    _append_approvals_ledger(Path(batch_dir), ledger_entry)

    return {
        "research_path": research_file,
        "research_sha256": final_research_sha,
        "mapping_path": mapping_path,
        "mapping_sha256": mapping_sha,
        "mapping": mapping,
        "authority_path": authority_path,
        "authority_sha256": authority_sha,
        "authority": authority,
        "horse_count": len(rows),
    }


RELEASE_MANIFEST_SCHEMA = "p0_horse_production_release_manifest.v1"
RELEASE_MANIFEST_SCHEMA_V2 = "p0_horse_production_release_manifest.v2"


def build_region_release_manifest(
    *,
    artifact_path: str | Path,
    artifact_sha256: str,
    bundle: dict[str, Any],
    reviewer,
    approved_by: str,
    batch_dir: str | Path,
    region: str,
    decision_reference: str = "p0-horse-completion-batch",
    release_candidate_path: str | Path | None = None,
    release_candidate_sha256: str | None = None,
    expected_publish_scope: dict[str, Any] | None = None,
    superseded_releases: list[dict[str, Any]] | None = None,
    now=None,
) -> dict[str, Any]:
    """Create the rolling-batch release manifest after artifact preparation.

    The release manifest binds the exact five-tuple of SHAs the commit chain
    revalidates, and its own SHA is recorded in the batch approvals ledger
    (the rolling-batch replacement for the repository trusted allowlist).
    ``approved_by`` must be a different person than the DB executor reviewer.
    """
    candidate_sha = str(release_candidate_sha256 or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", candidate_sha):
        raise P0HorseBatchError(
            "rolling release manifest requires an exact release candidate SHA-256"
        )
    batch_root = Path(batch_dir)
    approval_dir = batch_root / "approval"
    candidate_file = Path(str(release_candidate_path or ""))
    expected_candidate_path = (
        approval_dir / f"release_candidate_{region}_{candidate_sha}.json"
    )
    try:
        candidate_mode = candidate_file.lstat().st_mode
    except OSError as exc:
        raise P0HorseBatchError("release candidate file is unreadable") from exc
    if (
        candidate_file.is_symlink()
        or not stat.S_ISREG(candidate_mode)
        or candidate_file.absolute() != expected_candidate_path.absolute()
    ):
        raise P0HorseBatchError(
            "release candidate must be the immutable regular file for this batch"
        )
    try:
        candidate_bytes = candidate_file.read_bytes()
        candidate = json.loads(candidate_bytes)
    except (OSError, ValueError) as exc:
        raise P0HorseBatchError("release candidate file is unreadable") from exc
    if (
        not isinstance(candidate, dict)
        or _sha256_bytes(candidate_bytes) != candidate_sha
    ):
        raise P0HorseBatchError("release candidate SHA-256 mismatch")

    artifact_file = Path(artifact_path)
    try:
        artifact_bytes = artifact_file.read_bytes()
        artifact = json.loads(artifact_bytes)
    except (OSError, ValueError) as exc:
        raise P0HorseBatchError(f"commit artifact is unreadable: {artifact_file}") from exc
    actual_sha = _sha256_bytes(artifact_bytes)
    if actual_sha != artifact_sha256:
        raise P0HorseBatchError("commit artifact SHA-256 mismatch")
    manifest = load_batch_manifest(
        batch_root / P0_HORSE_BATCH_MANIFEST_FILENAME
    )
    approved_by_text = str(approved_by or "").strip()
    if not approved_by_text:
        raise P0HorseBatchError("release manifest requires approved_by")
    if approved_by_text.casefold() == reviewer.get_username().casefold():
        raise P0HorseBatchError(
            "release approver must be separate from the DB executor reviewer"
        )
    inputs = artifact.get("inputs") or {}
    bindings = {
        "research_v3_sha256": (inputs.get("research_v3") or {}).get("sha256"),
        "authority_manifest_sha256": (inputs.get("authority_manifest") or {}).get("sha256"),
        "profile_mapping_decisions_sha256": (
            inputs.get("profile_mapping_decisions") or {}
        ).get("sha256"),
        "production_snapshot_sha256": artifact.get("production_snapshot_sha256"),
        "final_artifact_sha256": artifact_sha256,
    }
    if not all(bindings.values()):
        raise P0HorseBatchError("commit artifact inputs are incomplete for release binding")
    if bindings["research_v3_sha256"] != bundle["research_sha256"]:
        raise P0HorseBatchError("release binding research SHA does not match the approval bundle")
    if bindings["authority_manifest_sha256"] != bundle["authority_sha256"]:
        raise P0HorseBatchError("release binding authority SHA does not match the approval bundle")
    if bindings["profile_mapping_decisions_sha256"] != bundle["mapping_sha256"]:
        raise P0HorseBatchError("release binding mapping SHA does not match the approval bundle")

    research = {}
    try:
        research = json.loads(Path(bundle["research_path"]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise P0HorseBatchError("release candidate research is unreadable") from exc
    combined_sha = (
        (research.get("generated_from") or {}).get(
            "combined_candidates_sha256"
        )
    )
    candidate_bindings = candidate.get("bindings") or {}
    expected_candidate_bindings = {
        "batch_manifest_sha256": candidate_bindings.get(
            "batch_manifest_sha256"
        ),
        "combined_candidates_sha256": combined_sha,
        **bindings,
    }
    state = BatchRunState.read(batch_root)
    history = state.artifacts.get(
        f"release_candidate:{region}:{candidate_sha}"
    )
    ledger_path = batch_root / "approvals_ledger.jsonl"
    ledger_entries = read_approvals_ledger(batch_root)
    prepared_event_matches = any(
        event.get("event") == "release_candidate_prepared"
        and event.get("batch_id") == manifest["batch_id"]
        and event.get("region") == region
        and event.get("release_candidate_sha256") == candidate_sha
        and event.get("artifact_sha256") == artifact_sha256
        for event in ledger_entries
    )
    if (
        not isinstance(history, dict)
        or history.get("path") != str(candidate_file)
        or history.get("sha256") != candidate_sha
        or history.get("artifact_path") != str(artifact_file)
        or history.get("artifact_sha256") != artifact_sha256
        or history.get("publish_scope") != expected_publish_scope
        or not prepared_event_matches
    ):
        raise P0HorseBatchError(
            "release candidate has no matching frozen batch evidence"
        )
    if (
        candidate.get("schema_version")
        != "p0_horse_production_release_candidate.v1"
        or candidate.get("completion_policy_version")
        != FULL_PROFILE_COMPLETENESS_POLICY_VERSION
        or candidate.get("completion_policy_version")
        != artifact.get("completion_policy_version")
        or candidate.get("status")
        != "pending_independent_release_approval"
        or candidate.get("batch_id") != manifest["batch_id"]
        or candidate.get("region") != region
        or candidate.get("executor_reviewer_id") != reviewer.id
        or candidate.get("artifact_prepared_at") != artifact.get("prepared_at")
        or candidate_bindings != expected_candidate_bindings
        or candidate.get("expected_actions") != artifact.get("expected_actions")
        or candidate.get("auto_first_publish_scope")
        != expected_publish_scope
    ):
        raise P0HorseBatchError(
            "release candidate does not match the release context"
        )
    current_batch_sha = manifest.get("batch_sha256")
    if (
        manifest.get("status") != "committed"
        and candidate_bindings.get("batch_manifest_sha256")
        != current_batch_sha
    ):
        raise P0HorseBatchError(
            "release candidate batch manifest binding drifted"
        )

    bindings["release_candidate_sha256"] = candidate_sha
    schema_version = RELEASE_MANIFEST_SCHEMA_V2
    history_key = f"release_candidate:{region}:{candidate_sha}"
    pending_release = history.get("pending_release")
    recorded_release_path = history.get("release_path")
    if isinstance(pending_release, dict):
        release_path = Path(str(pending_release.get("path") or ""))
        release_sha = str(pending_release.get("sha256") or "")
        release = pending_release.get("release")
    elif recorded_release_path:
        release_path = Path(str(recorded_release_path))
        release_sha = str(history.get("release_sha256") or "")
        release = None
    else:
        approved_at = _utcnow_iso(now)
        release = {
            "schema_version": schema_version,
            "approved_by": approved_by_text,
            "approved_at": approved_at,
            "decision_reference": str(decision_reference),
            "executor_reviewer_id": reviewer.id,
            "region": region,
            "approvals_ledger_path": str(ledger_path),
            "bindings": bindings,
        }
        release_bytes = _canonical_bytes(release) + b"\n"
        release_sha = _sha256_bytes(release_bytes)
        release_path = approval_dir / (
            f"release_manifest_{region}_{release_sha}.json"
        )
        history = {
            **history,
            "pending_release": {
                "path": str(release_path),
                "sha256": release_sha,
                "release": release,
            },
        }
        state.artifacts[history_key] = history
        state.write()

    expected_release_keys = {
        "schema_version",
        "approved_by",
        "approved_at",
        "decision_reference",
        "executor_reviewer_id",
        "region",
        "approvals_ledger_path",
        "bindings",
    }
    if release is None:
        try:
            release = json.loads(release_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise P0HorseBatchError(
                "existing release manifest is unreadable"
            ) from exc
    try:
        approved_at_value = datetime.fromisoformat(
            str(release.get("approved_at") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise P0HorseBatchError(
            "existing release manifest approval time is invalid"
        ) from exc
    expected_release = {
        "schema_version": schema_version,
        "approved_by": approved_by_text,
        "approved_at": release.get("approved_at"),
        "decision_reference": str(decision_reference),
        "executor_reviewer_id": reviewer.id,
        "region": region,
        "approvals_ledger_path": str(ledger_path),
        "bindings": bindings,
    }
    if (
        set(release) != expected_release_keys
        or approved_at_value.tzinfo is None
        or approved_at_value.utcoffset() is None
        or release != expected_release
    ):
        raise P0HorseBatchError(
            "existing release manifest does not match the signing contract"
        )
    expected_release_path = approval_dir / (
        f"release_manifest_{region}_{release_sha}.json"
    )
    if release_path.absolute() != expected_release_path.absolute():
        raise P0HorseBatchError("release manifest path does not match its SHA")

    if os.path.lexists(release_path):
        try:
            release_mode = release_path.lstat().st_mode
            release_bytes = release_path.read_bytes()
        except OSError as exc:
            raise P0HorseBatchError(
                "existing release manifest is unreadable"
            ) from exc
        if release_path.is_symlink() or not stat.S_ISREG(release_mode):
            raise P0HorseBatchError(
                "existing release manifest must be a regular file"
            )
        if (
            _sha256_bytes(release_bytes) != release_sha
            or release_bytes != _canonical_bytes(release) + b"\n"
        ):
            raise P0HorseBatchError(
                "existing release manifest filename SHA does not match bytes"
            )
    else:
        pending_path = approval_dir / (
            f".release_manifest_{region}_{candidate_sha}.pending"
        )
        written_sha = _write_canonical(pending_path, release)
        if written_sha != release_sha:
            pending_path.unlink(missing_ok=True)
            raise P0HorseBatchError("release manifest signing bytes drifted")
        os.replace(pending_path, release_path)

    superseded_releases = superseded_releases or []
    for old_release in superseded_releases:
        if old_release.get("candidate_sha256") == candidate_sha:
            continue
        old_release_sha = str(old_release.get("sha256") or "")
        supersede_event = {
            "event": "release_superseded",
            "region": region,
            "old_release_candidate_sha256": old_release[
                "candidate_sha256"
            ],
            "old_release_manifest_sha256": old_release_sha,
            "new_release_candidate_sha256": candidate_sha,
            "new_release_manifest_sha256": release_sha,
        }
        if not any(
            entry.get("event") == "release_superseded"
            and entry.get("old_release_manifest_sha256")
            == old_release_sha
            for entry in read_approvals_ledger(batch_root)
        ):
            _append_approvals_ledger(batch_root, supersede_event)

    ledger_entries = read_approvals_ledger(batch_root)
    matching_approvals = [
        entry
        for entry in ledger_entries
        if entry.get("event") == "release_approved"
        and entry.get("release_manifest_sha256") == release_sha
    ]
    for entry in matching_approvals:
        if (
            entry.get("region") != region
            or entry.get("approved_by") != approved_by_text
            or entry.get("approved_at") != release["approved_at"]
            or entry.get("decision_reference")
            != str(decision_reference)
        ):
            raise P0HorseBatchError(
                "release approval ledger does not match the signed manifest"
            )
    if not matching_approvals:
        _append_approvals_ledger(
            batch_root,
            {
                "event": "release_approved",
                "region": region,
                "release_manifest_sha256": release_sha,
                "approved_by": approved_by_text,
                "approved_at": release["approved_at"],
                "decision_reference": str(decision_reference),
            },
        )
    return {
        "release_path": release_path,
        "release_sha256": release_sha,
        "release": release,
    }

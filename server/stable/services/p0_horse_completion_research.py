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
from pathlib import Path
from typing import Any

from stable.services.p0_horse_completion_batch import (
    P0HorseBatchError,
    _utcnow_iso,
)
from stable.services.p0_horse_profiles import REQUIRED_COMPLETION_MODULES
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

    ledger_path = Path(batch_dir) / "approvals_ledger.jsonl"
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
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ledger_entry, ensure_ascii=False, sort_keys=True) + "\n")

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
    now=None,
) -> dict[str, Any]:
    """Create the rolling-batch release manifest after artifact preparation.

    The release manifest binds the exact five-tuple of SHAs the commit chain
    revalidates, and its own SHA is recorded in the batch approvals ledger
    (the rolling-batch replacement for the repository trusted allowlist).
    ``approved_by`` must be a different person than the DB executor reviewer.
    """
    artifact_file = Path(artifact_path)
    try:
        artifact_bytes = artifact_file.read_bytes()
        artifact = json.loads(artifact_bytes)
    except (OSError, ValueError) as exc:
        raise P0HorseBatchError(f"commit artifact is unreadable: {artifact_file}") from exc
    actual_sha = _sha256_bytes(artifact_bytes)
    if actual_sha != artifact_sha256:
        raise P0HorseBatchError("commit artifact SHA-256 mismatch")
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

    approved_at = _utcnow_iso(now)
    ledger_path = Path(batch_dir) / "approvals_ledger.jsonl"
    release = {
        "schema_version": RELEASE_MANIFEST_SCHEMA,
        "approved_by": approved_by_text,
        "approved_at": approved_at,
        "decision_reference": str(decision_reference),
        "executor_reviewer_id": reviewer.id,
        "region": region,
        "approvals_ledger_path": str(ledger_path),
        "bindings": bindings,
    }
    release_path = Path(batch_dir) / "approval" / f"release_manifest_{region}.json"
    release_sha = _write_canonical(release_path, release)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "event": "release_approved",
                    "region": region,
                    "release_manifest_sha256": release_sha,
                    "approved_by": approved_by_text,
                    "approved_at": approved_at,
                    "decision_reference": str(decision_reference),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
    return {
        "release_path": release_path,
        "release_sha256": release_sha,
        "release": release,
    }

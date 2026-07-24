"""Region commit stage for rolling P0 horse completion batches.

Serial-window guarded commit: dry-run -> commit -> automatic idempotent
re-verification for one region of a rolling batch, reusing the existing
reviewed-artifact chain. Writes the batch checkpoint pointer and in-flight
profile list into the completion run record.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from stable.services.p0_horse_completion_batch import (
    AUTO_FIRST_PUBLISH_LEDGER_SCHEMA_V2,
    BatchRunState,
    P0HorseBatchError,
    _append_approvals_ledger,
    _utcnow_iso,
    batch_execution_window,
    batch_serial_window,
    load_batch_manifest,
    read_approvals_ledger,
)
from stable.services.p0_horse_completion_research import (
    _write_canonical,
    build_region_release_manifest,
)
from stable.services.p0_horse_profiles import (
    FULL_PROFILE_COMPLETENESS_POLICY_VERSION,
)
from stable.services.p0_horse_production_apply import (
    P0ReviewedArtifactError,
    commit_reviewed_p0_completion_artifact,
    dry_run_reviewed_p0_completion_artifact,
    prepare_reviewed_p0_completion_artifact,
)

RELEASE_CANDIDATE_SCHEMA = "p0_horse_production_release_candidate.v1"

# Keep the private alias for narrow tests and older internal imports while the
# lock contract itself lives in the batch service.
_serial_window = batch_serial_window


def _region_bundle(state: BatchRunState, region: str) -> dict[str, Any]:
    bundle = state.artifacts.get(f"bundle:{region}")
    if not isinstance(bundle, dict):
        raise P0HorseBatchError(
            f"batch has no recorded approval bundle for region {region}"
        )
    return bundle


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise P0HorseBatchError(f"release input is unreadable: {path}") from exc


def _validate_immutable_file(
    path: Path,
    *,
    label: str,
    expected_sha256: str,
) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise P0HorseBatchError(f"{label} is unreadable") from exc
    if path.is_symlink() or not stat.S_ISREG(mode):
        raise P0HorseBatchError(f"{label} must be an immutable regular file")
    if _sha256_file(path) != expected_sha256:
        raise P0HorseBatchError(f"{label} SHA-256 mismatch")


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise P0HorseBatchError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise P0HorseBatchError(f"{label} must contain an object")
    return payload


def _build_auto_first_publish_scope(artifact: dict[str, Any]) -> dict[str, Any]:
    """Freeze publish targets from reviewed artifact rows, never the batch."""
    from stable.models import HorseProfile, HorseProfileStatus
    from stable.services.horse_profile_publish import AUTO_PUBLISH_LOCK_KEY

    existing: list[dict[str, Any]] = []
    create_new: list[dict[str, Any]] = []
    for row in artifact.get("rows") or []:
        resolution = row.get("resolution") or {}
        decision = resolution.get("decision")
        if decision == "create_new":
            create_new.append(
                {
                    "deterministic_identity_key": row[
                        "deterministic_identity_key"
                    ],
                    "horse_name": str((row.get("identity") or {}).get("horse_name") or ""),
                    "disposition": "attempt_publish_after_commit",
                }
            )
            continue
        if decision != "bind_existing":
            raise P0HorseBatchError("artifact publish scope has an invalid resolution")
        profile_id = resolution.get("profile_id")
        profile = HorseProfile.objects.filter(pk=profile_id).first()
        if profile is None:
            raise P0HorseBatchError(
                f"artifact publish scope profile {profile_id} is missing"
            )
        hidden = bool(
            profile.review_status == HorseProfileStatus.HIDDEN
            or profile.hidden_at is not None
        )
        manual_lock = bool(
            (profile.manual_lock_flags or {}).get(AUTO_PUBLISH_LOCK_KEY)
        )
        if profile.review_status == HorseProfileStatus.PUBLISHED:
            disposition = "skip_already_published"
        elif hidden:
            disposition = "block_hidden"
        elif manual_lock:
            disposition = "block_manual_lock"
        else:
            disposition = "attempt_publish_after_commit"
        existing.append(
            {
                "profile_id": profile.id,
                "review_status": profile.review_status,
                "hidden": hidden,
                "manual_lock": manual_lock,
                "disposition": disposition,
            }
        )
    return {
        "existing_profiles": sorted(existing, key=lambda item: item["profile_id"]),
        "create_new_identities": sorted(
            create_new, key=lambda item: item["deterministic_identity_key"]
        ),
    }


def _ledger_has_event(
    batch_dir: Path,
    *,
    event: str,
    field: str,
    value: str,
) -> bool:
    for entry in read_approvals_ledger(batch_dir):
        if entry.get("event") == event and entry.get(field) == value:
            return True
    return False


def _candidate_history_key(region: str, candidate_sha: str) -> str:
    return f"release_candidate:{region}:{candidate_sha}"


def _artifact_was_committed(artifact_path: Path, artifact_sha: str) -> bool:
    from stable.models import HorseCompletionRunStatus, HorseProfileCompletionRun

    runs = HorseProfileCompletionRun.objects.filter(
        status=HorseCompletionRunStatus.COMMITTED,
        artifact_path=str(artifact_path),
    ).only("summary")
    return any(
        (run.summary or {}).get("artifact_sha256") == artifact_sha
        for run in runs
    )


def _release_manifests_for_region(
    batch_dir: Path, region: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    approved_shas: set[str] = set()
    for entry in read_approvals_ledger(batch_dir):
        if entry.get("event") == "release_approved":
            approved_shas.add(
                str(entry.get("release_manifest_sha256") or "")
            )
    for path in sorted(
        (batch_dir / "approval").glob(f"release_manifest_{region}_*.json")
    ):
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise P0HorseBatchError("release manifest is unreadable") from exc
        match = re.fullmatch(
            rf"release_manifest_{re.escape(region)}_([0-9a-f]{{64}})\.json",
            path.name,
        )
        if path.is_symlink() or not stat.S_ISREG(mode) or match is None:
            raise P0HorseBatchError(
                "release manifest must be an immutable regular file"
            )
        path_sha = _sha256_file(path)
        if path_sha != match.group(1):
            raise P0HorseBatchError(
                "release manifest filename SHA does not match bytes"
            )
        if path_sha not in approved_shas:
            continue
        payload = _read_json(path, label="release manifest")
        bindings = payload.get("bindings") or {}
        if (
            payload.get("schema_version")
            != "p0_horse_production_release_manifest.v2"
            or not bindings.get("release_candidate_sha256")
        ):
            continue
        records.append(
            {
                "path": path,
                "sha256": path_sha,
                "candidate_sha256": bindings["release_candidate_sha256"],
                "artifact_sha256": bindings.get("final_artifact_sha256"),
                "payload": payload,
            }
        )
    return records


def _snapshot_input(
    source_path: Path,
    *,
    snapshot_dir: Path,
    label: str,
    expected_sha256: str,
) -> dict[str, str]:
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise P0HorseBatchError(f"bundle input is unreadable: {source_path}") from exc
    actual_sha = hashlib.sha256(source_bytes).hexdigest()
    if actual_sha != expected_sha256:
        raise P0HorseBatchError(f"bundle {label} SHA changed before snapshot")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_dir_mode = snapshot_dir.lstat().st_mode
    except OSError as exc:
        raise P0HorseBatchError("snapshot directory is unreadable") from exc
    if snapshot_dir.is_symlink() or not stat.S_ISDIR(snapshot_dir_mode):
        raise P0HorseBatchError("snapshot directory must be a real directory")
    snapshot_path = snapshot_dir / f"{label}_{actual_sha}.json"

    def validate_existing() -> None:
        try:
            mode = snapshot_path.lstat().st_mode
        except OSError as exc:
            raise P0HorseBatchError(
                f"immutable {label} snapshot is unreadable"
            ) from exc
        if snapshot_path.is_symlink() or not stat.S_ISREG(mode):
            raise P0HorseBatchError(
                f"immutable {label} snapshot must be a regular file"
            )
        try:
            existing_bytes = snapshot_path.read_bytes()
        except OSError as exc:
            raise P0HorseBatchError(
                f"immutable {label} snapshot is unreadable"
            ) from exc
        if existing_bytes != source_bytes:
            raise P0HorseBatchError(f"immutable {label} snapshot drifted")

    if os.path.lexists(snapshot_path):
        validate_existing()
    else:
        pending_path = snapshot_dir / (
            f".{label}_{actual_sha}.{os.getpid()}.pending"
        )
        try:
            with pending_path.open("xb") as handle:
                handle.write(source_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(pending_path, snapshot_path)
            except FileExistsError:
                validate_existing()
            except OSError as exc:
                raise P0HorseBatchError(
                    f"immutable {label} snapshot cannot be published"
                ) from exc
        finally:
            pending_path.unlink(missing_ok=True)
    return {"path": str(snapshot_path), "sha256": actual_sha}


def _snapshot_bundle_paths(snapshot_bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "research_path": snapshot_bundle["research"]["path"],
        "research_sha256": snapshot_bundle["research"]["sha256"],
        "mapping_path": snapshot_bundle["mapping"]["path"],
        "mapping_sha256": snapshot_bundle["mapping"]["sha256"],
        "authority_path": snapshot_bundle["authority"]["path"],
        "authority_sha256": snapshot_bundle["authority"]["sha256"],
    }


def prepare_p0_horse_batch_release_candidate(
    manifest_path: str | Path,
    *,
    region: str,
    reviewer,
    state_dir: str | Path,
) -> dict[str, Any]:
    """Serialize release preparation against commit and abandon."""
    batch_dir = Path(manifest_path).parent
    with batch_execution_window(batch_dir):
        return _prepare_p0_horse_batch_release_candidate_locked(
            manifest_path,
            region=region,
            reviewer=reviewer,
            state_dir=state_dir,
        )


def _prepare_p0_horse_batch_release_candidate_locked(
    manifest_path: str | Path,
    *,
    region: str,
    reviewer,
    state_dir: str | Path,
) -> dict[str, Any]:
    """Freeze the reviewed commit plan without approval or business writes."""
    batch_dir = Path(manifest_path).parent
    combined_path = batch_dir / "artifact" / "combined_candidates.jsonl"
    with _serial_window(Path(state_dir)):
        manifest = load_batch_manifest(manifest_path)
        state = BatchRunState.read(batch_dir)
        if manifest.get("status") == "committed":
            raise P0HorseBatchError(
                "batch run is already committed; release preparation is forbidden"
            )
        if manifest.get("status") == "abandoned" or state.stage == "abandoned":
            raise P0HorseBatchError("batch run was abandoned; start a new batch")
        bundle = _region_bundle(state, region)
        combined_sha = _sha256_file(combined_path)
        research = _read_json(bundle["research_path"], label="bundle research v3")
        if (
            (research.get("generated_from") or {}).get(
                "combined_candidates_sha256"
            )
            != combined_sha
        ):
            raise P0HorseBatchError(
                f"bundle research was generated from a stale combined artifact for "
                f"region {region}; re-run prepare and the approval bundle"
            )
        mapping = _read_json(
            bundle["mapping_path"], label="profile mapping decisions"
        )
        frozen_prepared_at = str(mapping.get("approved_at") or "").strip()
        if not frozen_prepared_at:
            raise P0HorseBatchError("mapping approval time is missing")
        actual_authority_sha = _sha256_file(Path(bundle["authority_path"]))
        try:
            artifact = prepare_reviewed_p0_completion_artifact(
                research_v3_path=bundle["research_path"],
                authority_manifest_path=bundle["authority_path"],
                authority_manifest_sha256=actual_authority_sha,
                profile_mapping_decisions_path=bundle["mapping_path"],
                reviewer_id=reviewer.id,
                prepared_at=frozen_prepared_at,
            )
        except P0ReviewedArtifactError as exc:
            raise P0HorseBatchError(
                "bundle inputs are invalid for release preparation"
            ) from exc
        artifact_inputs = artifact.get("inputs") or {}
        actual_bundle_bindings = {
            "research_v3_sha256": (
                artifact_inputs.get("research_v3") or {}
            ).get("sha256"),
            "authority_manifest_sha256": (
                artifact_inputs.get("authority_manifest") or {}
            ).get("sha256"),
            "profile_mapping_decisions_sha256": (
                artifact_inputs.get("profile_mapping_decisions") or {}
            ).get("sha256"),
        }
        declared_bundle_bindings = {
            "research_v3_sha256": bundle["research_sha256"],
            "authority_manifest_sha256": bundle["authority_sha256"],
            "profile_mapping_decisions_sha256": bundle["mapping_sha256"],
        }
        for field, actual_sha in actual_bundle_bindings.items():
            if actual_sha != declared_bundle_bindings[field]:
                raise P0HorseBatchError(
                    f"bundle {field} SHA does not match the artifact input"
                )
        approval_dir = batch_dir / "approval"
        snapshot_dir = approval_dir / "input_snapshots"
        snapshot_bundle = {
            "research": _snapshot_input(
                Path(bundle["research_path"]),
                snapshot_dir=snapshot_dir,
                label="research_v3",
                expected_sha256=actual_bundle_bindings[
                    "research_v3_sha256"
                ],
            ),
            "mapping": _snapshot_input(
                Path(bundle["mapping_path"]),
                snapshot_dir=snapshot_dir,
                label="profile_mapping_decisions",
                expected_sha256=actual_bundle_bindings[
                    "profile_mapping_decisions_sha256"
                ],
            ),
            "authority": _snapshot_input(
                Path(bundle["authority_path"]),
                snapshot_dir=snapshot_dir,
                label="authority_manifest",
                expected_sha256=actual_bundle_bindings[
                    "authority_manifest_sha256"
                ],
            ),
        }
        snapshot_paths = _snapshot_bundle_paths(snapshot_bundle)
        try:
            artifact = prepare_reviewed_p0_completion_artifact(
                research_v3_path=snapshot_paths["research_path"],
                authority_manifest_path=snapshot_paths["authority_path"],
                authority_manifest_sha256=snapshot_paths["authority_sha256"],
                profile_mapping_decisions_path=snapshot_paths["mapping_path"],
                reviewer_id=reviewer.id,
                prepared_at=frozen_prepared_at,
            )
        except P0ReviewedArtifactError as exc:
            raise P0HorseBatchError(
                "immutable bundle snapshots are invalid"
            ) from exc
        approval_dir.mkdir(parents=True, exist_ok=True)
        artifact_pending = approval_dir / f".commit_artifact_{region}.pending"
        artifact_sha = _write_canonical(artifact_pending, artifact)
        artifact_path = approval_dir / (
            f"commit_artifact_{region}_{artifact_sha}.json"
        )
        if artifact_path.exists():
            artifact_pending.unlink(missing_ok=True)
            if _sha256_file(artifact_path) != artifact_sha:
                raise P0HorseBatchError("immutable commit artifact drifted")
        bindings = {
            "batch_manifest_sha256": manifest["batch_sha256"],
            "combined_candidates_sha256": combined_sha,
            **actual_bundle_bindings,
            "production_snapshot_sha256": artifact[
                "production_snapshot_sha256"
            ],
            "final_artifact_sha256": artifact_sha,
        }
        candidate = {
            "schema_version": RELEASE_CANDIDATE_SCHEMA,
            "completion_policy_version": (
                FULL_PROFILE_COMPLETENESS_POLICY_VERSION
            ),
            "status": "pending_independent_release_approval",
            "batch_id": manifest["batch_id"],
            "region": region,
            "executor_reviewer_id": reviewer.id,
            "artifact_prepared_at": frozen_prepared_at,
            "bindings": bindings,
            "expected_actions": artifact["expected_actions"],
            "auto_first_publish_scope": _build_auto_first_publish_scope(artifact),
        }
        candidate_pending = approval_dir / f".release_candidate_{region}.pending"
        candidate_sha = _write_canonical(candidate_pending, candidate)
        candidate_path = approval_dir / (
            f"release_candidate_{region}_{candidate_sha}.json"
        )
        if candidate_path.exists():
            candidate_pending.unlink(missing_ok=True)
            if _sha256_file(candidate_path) != candidate_sha:
                raise P0HorseBatchError("immutable release candidate drifted")
        for old_release in _release_manifests_for_region(batch_dir, region):
            if old_release["candidate_sha256"] == candidate_sha:
                continue
            old_artifact_path = approval_dir / (
                f"commit_artifact_{region}_{old_release['artifact_sha256']}.json"
            )
            if _artifact_was_committed(
                old_artifact_path, old_release["artifact_sha256"]
            ):
                artifact_pending.unlink(missing_ok=True)
                candidate_pending.unlink(missing_ok=True)
                raise P0HorseBatchError(
                    "a different approved candidate was already committed; "
                    "only its idempotent recovery is allowed"
                )
        if artifact_pending.exists():
            os.replace(artifact_pending, artifact_path)
        if candidate_pending.exists():
            os.replace(candidate_pending, candidate_path)
        if not _ledger_has_event(
            batch_dir,
            event="release_candidate_prepared",
            field="release_candidate_sha256",
            value=candidate_sha,
        ):
            _append_approvals_ledger(
                batch_dir,
                {
                    "event": "release_candidate_prepared",
                    "batch_id": manifest["batch_id"],
                    "region": region,
                    "release_candidate_sha256": candidate_sha,
                    "artifact_sha256": artifact_sha,
                },
            )
        history_key = _candidate_history_key(region, candidate_sha)
        history = {
            **(state.artifacts.get(history_key) or {}),
            "path": str(candidate_path),
            "sha256": candidate_sha,
            "artifact_path": str(artifact_path),
            "artifact_sha256": artifact_sha,
            "publish_scope": candidate["auto_first_publish_scope"],
            "snapshot_bundle": snapshot_bundle,
        }
        state.artifacts[history_key] = history
        state.artifacts[f"release_candidate:{region}"] = history
        state.write()
    return {
        "region": region,
        "release_candidate_path": str(candidate_path),
        "release_candidate_sha256": candidate_sha,
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact_sha,
        "expected_actions": candidate["expected_actions"],
        "auto_first_publish_scope": candidate["auto_first_publish_scope"],
    }


def _regions_pending_commit_or_publish(
    manifest: dict[str, Any], state: BatchRunState
) -> list[str]:
    """Regions not fully done: the batch reaches the committed terminal state
    only when every region has BOTH a verified commit and a completed publish
    stage (a region without a publish stage must never be silently dropped).
    """
    return [
        manifest_region
        for manifest_region in manifest.get("regions") or []
        if f"commit:{manifest_region}" not in state.completed_stages
        or f"publish:{manifest_region}" not in state.completed_stages
    ]


def _completed_region_replay_result(
    *,
    state: BatchRunState,
    manifest: dict[str, Any],
    batch_dir: Path,
    region: str,
    reviewer,
    approved_by: str,
    release_candidate_sha256: str,
    candidate: dict[str, Any],
    candidate_record: dict[str, Any],
    artifact_path: Path,
    artifact_sha: str,
) -> dict[str, Any]:
    """Validate frozen commit/publish evidence and return without any DB write."""
    from stable.models import (
        HorseCompletionRunStatus,
        HorseP0Source,
        HorseProfileCompletionRun,
    )

    commit_stage = f"commit:{region}"
    publish_stage = f"publish:{region}"
    if publish_stage not in state.completed_stages:
        raise P0HorseBatchError(
            f"region {region} commit already completed but publish did not; "
            "ordinary commit cannot recover publish state, use --retry-publish"
        )
    commit_report = state.artifacts.get(commit_stage)
    publish_report = state.artifacts.get(publish_stage)
    required_publish_report_fields = {
        "published",
        "skipped_already_published",
        "blocked",
        "published_profile_ids",
        "errors",
        "profile_ids",
        "frozen_exclusions",
        "frozen_exclusion_counts",
    }
    if (
        not isinstance(commit_report, dict)
        or not isinstance(publish_report, dict)
        or not required_publish_report_fields.issubset(publish_report)
        or publish_report.get("errors") != []
    ):
        raise P0HorseBatchError(
            f"region {region} completed commit/publish checkpoint is missing "
            "or invalid; manual audit recovery is required"
        )
    verification = commit_report.get("idempotent_verification")
    planned_remaining = (
        verification.get("planned_remaining")
        if isinstance(verification, dict)
        else None
    )
    expected_planned_keys = {
        "planned_profile_creates",
        "planned_profile_updates",
        "planned_race_record_creates",
        "planned_race_record_updates",
        "planned_module_audits",
    }
    candidate_scope = candidate.get("auto_first_publish_scope")
    publish_counts = (
        publish_report.get("published"),
        publish_report.get("skipped_already_published"),
        publish_report.get("blocked"),
    )
    release_path = Path(str(commit_report.get("release_path") or ""))
    release_sha = str(commit_report.get("release_sha256") or "")
    expected_commit_fields = {
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact_sha,
        "release_path": str(candidate_record.get("release_path") or ""),
        "release_sha256": str(candidate_record.get("release_sha256") or ""),
        "release_candidate_sha256": release_candidate_sha256,
        "publish_scope": candidate_scope,
    }
    if (
        state.batch_id != manifest.get("batch_id")
        or candidate.get("batch_id") != manifest.get("batch_id")
        or (candidate.get("bindings") or {}).get("final_artifact_sha256")
        != artifact_sha
        or candidate_record.get("artifact_path") != str(artifact_path)
        or candidate_record.get("artifact_sha256") != artifact_sha
        or candidate_record.get("publish_scope") != candidate_scope
        or not isinstance(candidate_scope, dict)
        or not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in publish_counts
        )
        or not isinstance(publish_report.get("published_profile_ids"), list)
        or not isinstance(publish_report.get("profile_ids"), list)
        or not isinstance(publish_report.get("frozen_exclusions"), list)
        or not isinstance(publish_report.get("frozen_exclusion_counts"), dict)
        or any(
            commit_report.get(field) != expected
            for field, expected in expected_commit_fields.items()
        )
        or not isinstance(verification, dict)
        or verification.get("passed") is not True
        or verification.get("artifact_sha256") != artifact_sha
        or not isinstance(planned_remaining, dict)
        or set(planned_remaining) != expected_planned_keys
        or not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in planned_remaining.values()
        )
        or any(planned_remaining.values())
    ):
        raise P0HorseBatchError(
            f"region {region} frozen commit checkpoint is invalid; "
            "manual audit recovery is required"
        )
    _validate_immutable_file(
        artifact_path,
        label="completed commit artifact",
        expected_sha256=artifact_sha,
    )
    _validate_immutable_file(
        release_path,
        label="completed release filename SHA",
        expected_sha256=release_sha,
    )
    if release_path.name != f"release_manifest_{region}_{release_sha}.json":
        raise P0HorseBatchError(
            f"region {region} frozen release filename is invalid; "
            "manual audit recovery is required"
        )
    release = _read_json(release_path, label="completed release manifest")
    release_bindings = release.get("bindings") or {}
    if (
        release.get("schema_version")
        != "p0_horse_production_release_manifest.v2"
        or release.get("region") != region
        or release.get("executor_reviewer_id") != reviewer.id
        or release.get("approved_by") != str(approved_by or "").strip()
        or release_bindings.get("release_candidate_sha256")
        != release_candidate_sha256
        or release_bindings.get("final_artifact_sha256") != artifact_sha
    ):
        raise P0HorseBatchError(
            f"region {region} frozen release manifest is invalid; "
            "manual audit recovery is required"
        )

    ledger = read_approvals_ledger(batch_dir)
    prepared_events = [
        entry
        for entry in ledger
        if entry.get("event") == "release_candidate_prepared"
        and entry.get("batch_id") == manifest["batch_id"]
        and entry.get("region") == region
        and entry.get("release_candidate_sha256")
        == release_candidate_sha256
    ]
    approved_events = [
        entry
        for entry in ledger
        if entry.get("event") == "release_approved"
        and entry.get("region") == region
        and entry.get("release_manifest_sha256") == release_sha
    ]
    publish_events = [
        entry
        for entry in ledger
        if entry.get("event") == "auto_first_publish"
        and entry.get("batch_id") == manifest["batch_id"]
        and entry.get("region") == region
        and entry.get("artifact_sha256") == artifact_sha
    ]
    expected_publish_event = {
        "event_schema": AUTO_FIRST_PUBLISH_LEDGER_SCHEMA_V2,
        "published": publish_report["published"],
        "skipped_already_published": publish_report[
            "skipped_already_published"
        ],
        "blocked": publish_report["blocked"],
        "published_profile_ids": publish_report["published_profile_ids"],
        "frozen_exclusions": publish_report["frozen_exclusions"],
        "frozen_exclusion_counts": publish_report[
            "frozen_exclusion_counts"
        ],
    }
    if (
        len(prepared_events) != 1
        or prepared_events[0].get("artifact_sha256") != artifact_sha
        or len(approved_events) != 1
        or len(publish_events) != 1
        or any(
            publish_events[0].get(field) != expected
            for field, expected in expected_publish_event.items()
        )
    ):
        raise P0HorseBatchError(
            f"region {region} frozen publish ledger evidence is missing or "
            "does not match; manual audit recovery is required"
        )
    completion_run = next(
        (
            run
            for run in HorseProfileCompletionRun.objects.filter(
                status=HorseCompletionRunStatus.COMMITTED,
                artifact_path=str(artifact_path),
            ).order_by("-id")
            if (run.summary or {}).get("artifact_sha256") == artifact_sha
        ),
        None,
    )
    if completion_run is None:
        raise P0HorseBatchError(
            f"region {region} committed completion run is missing; "
            "manual audit recovery is required"
        )
    existing_scope = candidate_scope.get("existing_profiles") or []
    create_scope = candidate_scope.get("create_new_identities") or []
    expected_profile_ids = {
        int(item["profile_id"])
        for item in existing_scope
        if item.get("disposition") == "attempt_publish_after_commit"
    }
    wanted_keys = {
        item["deterministic_identity_key"]
        for item in create_scope
        if item.get("disposition") == "attempt_publish_after_commit"
    }
    for source in HorseP0Source.objects.filter(
        completion_run=completion_run,
    ).select_related("profile"):
        batches = (source.profile.source_refs or {}).get(
            "p0_reviewed_batches"
        ) or {}
        if any(batches.get(key) == artifact_sha for key in wanted_keys):
            expected_profile_ids.add(source.profile_id)
    expected_frozen_exclusions = [
        {
            "target_type": "existing_profile",
            "profile_id": int(item["profile_id"]),
            "disposition": item.get("disposition"),
        }
        for item in existing_scope
        if item.get("disposition") != "attempt_publish_after_commit"
    ]
    expected_frozen_exclusions.extend(
        {
            "target_type": "create_new_identity",
            "deterministic_identity_key": item.get(
                "deterministic_identity_key"
            ),
            "disposition": item.get("disposition"),
        }
        for item in create_scope
        if item.get("disposition") != "attempt_publish_after_commit"
    )
    expected_frozen_counts = {
        disposition: sum(
            item["disposition"] == disposition
            for item in expected_frozen_exclusions
        )
        for disposition in sorted(
            {
                item["disposition"]
                for item in expected_frozen_exclusions
                if item.get("disposition")
            }
        )
    }
    if (
        publish_report["profile_ids"] != sorted(expected_profile_ids)
        or publish_report["frozen_exclusions"]
        != expected_frozen_exclusions
        or publish_report["frozen_exclusion_counts"]
        != expected_frozen_counts
        or publish_report["published"]
        != len(publish_report["published_profile_ids"])
        or (
            publish_report["published"]
            + publish_report["skipped_already_published"]
            + publish_report["blocked"]
        )
        != len(expected_profile_ids)
        or not set(publish_report["published_profile_ids"]).issubset(
            expected_profile_ids
        )
    ):
        raise P0HorseBatchError(
            f"region {region} frozen publish checkpoint does not match "
            "candidate scope; manual audit recovery is required"
        )
    return {
        "region": region,
        "artifact_sha256": artifact_sha,
        "release_sha256": release_sha,
        "dry_run": dict(planned_remaining),
        "commit_report": {"status": "committed"},
        "idempotent_verification": verification,
        "auto_first_publish": json.loads(json.dumps(publish_report)),
        "completion_run_id": completion_run.id,
    }


def commit_p0_horse_batch_region(
    manifest_path: str | Path,
    *,
    region: str,
    reviewer,
    approved_by: str,
    release_candidate_sha256: str,
    state_dir: str | Path,
    confirm_reviewed_artifact: bool = False,
    now=None,
) -> dict[str, Any]:
    """Serialize the complete approval-to-publish execution for one batch."""
    batch_dir = Path(manifest_path).parent
    with batch_execution_window(batch_dir):
        return _commit_p0_horse_batch_region_locked(
            manifest_path,
            region=region,
            reviewer=reviewer,
            approved_by=approved_by,
            release_candidate_sha256=release_candidate_sha256,
            state_dir=state_dir,
            confirm_reviewed_artifact=confirm_reviewed_artifact,
            now=now,
        )


def _commit_p0_horse_batch_region_locked(
    manifest_path: str | Path,
    *,
    region: str,
    reviewer,
    approved_by: str,
    release_candidate_sha256: str,
    state_dir: str | Path,
    confirm_reviewed_artifact: bool = False,
    now=None,
) -> dict[str, Any]:
    """Prepare -> release -> dry-run -> commit -> idempotent re-verify."""
    if not confirm_reviewed_artifact:
        raise P0HorseBatchError("region commit requires --confirm-reviewed-artifact")
    release_candidate_sha256 = str(release_candidate_sha256 or "").strip()
    if not release_candidate_sha256:
        raise P0HorseBatchError("region commit requires a release candidate SHA-256")
    batch_dir = Path(manifest_path).parent
    combined_path = batch_dir / "artifact" / "combined_candidates.jsonl"
    with _serial_window(Path(state_dir)):
        state = BatchRunState.read(batch_dir)
        if state.stage == "abandoned":
            raise P0HorseBatchError("batch run was abandoned; start a new batch")
        previous_commit = state.artifacts.get(f"commit:{region}")
        candidate_record = state.artifacts.get(
            _candidate_history_key(region, release_candidate_sha256)
        ) or {}
        candidate_path = Path(str(candidate_record.get("path") or ""))
        if candidate_record.get("sha256") != release_candidate_sha256:
            raise P0HorseBatchError("release candidate SHA-256 mismatch")
        _validate_immutable_file(
            candidate_path,
            label="release candidate",
            expected_sha256=release_candidate_sha256,
        )
        candidate = _read_json(candidate_path, label="release candidate")
        if (
            candidate.get("schema_version") != RELEASE_CANDIDATE_SCHEMA
            or candidate.get("completion_policy_version")
            != FULL_PROFILE_COMPLETENESS_POLICY_VERSION
            or candidate.get("status") != "pending_independent_release_approval"
            or candidate.get("region") != region
            or candidate.get("executor_reviewer_id") != reviewer.id
        ):
            raise P0HorseBatchError("release candidate metadata is invalid")
        if _ledger_has_event(
            batch_dir,
            event="release_superseded",
            field="old_release_candidate_sha256",
            value=release_candidate_sha256,
        ):
            raise P0HorseBatchError(
                "release candidate was superseded by a newer authorization"
            )
        commit_stage = f"commit:{region}"
        repeated_completed_commit = (
            commit_stage in state.completed_stages
            and isinstance(previous_commit, dict)
            and previous_commit.get("release_candidate_sha256")
            == release_candidate_sha256
        )
        artifact_sha = str(
            (candidate.get("bindings") or {}).get("final_artifact_sha256") or ""
        )
        artifact_path = Path(
            str(
                candidate_record.get("artifact_path")
                or (
                    batch_dir
                    / "approval"
                    / f"commit_artifact_{region}_{artifact_sha}.json"
                )
            )
        )
        manifest = load_batch_manifest(manifest_path)
        if repeated_completed_commit:
            return _completed_region_replay_result(
                state=state,
                manifest=manifest,
                batch_dir=batch_dir,
                region=region,
                reviewer=reviewer,
                approved_by=approved_by,
                release_candidate_sha256=release_candidate_sha256,
                candidate=candidate,
                candidate_record=candidate_record,
                artifact_path=artifact_path,
                artifact_sha=artifact_sha,
            )
        releases = _release_manifests_for_region(batch_dir, region)
        artifact_committed = _artifact_was_committed(artifact_path, artifact_sha)
        snapshot_bundle = candidate_record.get("snapshot_bundle")
        if not isinstance(snapshot_bundle, dict):
            raise P0HorseBatchError(
                "release candidate is missing immutable input snapshots"
            )
        bundle = _snapshot_bundle_paths(snapshot_bundle)
        if artifact_committed:
            combined_sha = str(
                (candidate.get("bindings") or {}).get(
                    "combined_candidates_sha256"
                )
                or ""
            )
        else:
            try:
                combined_sha = hashlib.sha256(
                    combined_path.read_bytes()
                ).hexdigest()
            except OSError as exc:
                raise P0HorseBatchError(
                    f"batch combined candidates are unreadable: {combined_path}"
                ) from exc
            research = _read_json(
                bundle["research_path"],
                label="candidate research snapshot",
            )
            research_combined_sha = (
                (research.get("generated_from") or {}).get(
                    "combined_candidates_sha256"
                )
            )
            if research_combined_sha != combined_sha:
                raise P0HorseBatchError(
                    f"candidate research was generated from a stale combined "
                    f"artifact for region {region}"
                )
        manifest = load_batch_manifest(manifest_path)
        for old_release in releases:
            if old_release["candidate_sha256"] == release_candidate_sha256:
                continue
            old_artifact_path = batch_dir / "approval" / (
                f"commit_artifact_{region}_{old_release['artifact_sha256']}.json"
            )
            if _artifact_was_committed(
                old_artifact_path, old_release["artifact_sha256"]
            ):
                raise P0HorseBatchError(
                    "a different approved candidate was already committed; "
                    "only its idempotent recovery is allowed"
                )
        static_bindings = {
            "batch_manifest_sha256": (
                (candidate.get("bindings") or {}).get("batch_manifest_sha256")
                if artifact_committed and manifest.get("status") == "committed"
                else manifest["batch_sha256"]
            ),
            "combined_candidates_sha256": combined_sha,
            "research_v3_sha256": _sha256_file(Path(bundle["research_path"])),
            "authority_manifest_sha256": _sha256_file(
                Path(bundle["authority_path"])
            ),
            "profile_mapping_decisions_sha256": _sha256_file(
                Path(bundle["mapping_path"])
            ),
        }
        for field, value in static_bindings.items():
            if (candidate.get("bindings") or {}).get(field) != value:
                raise P0HorseBatchError(
                    "release candidate bindings drifted; prepare a new candidate"
                )
        if artifact_committed:
            if _sha256_file(artifact_path) != artifact_sha:
                raise P0HorseBatchError("approved commit artifact SHA-256 mismatch")
            artifact = _read_json(artifact_path, label="approved commit artifact")
            artifact_tmp_path = None
        else:
            try:
                artifact = prepare_reviewed_p0_completion_artifact(
                    research_v3_path=bundle["research_path"],
                    authority_manifest_path=bundle["authority_path"],
                    authority_manifest_sha256=bundle["authority_sha256"],
                    profile_mapping_decisions_path=bundle["mapping_path"],
                    reviewer_id=reviewer.id,
                    prepared_at=candidate.get("artifact_prepared_at"),
                )
            except P0ReviewedArtifactError as exc:
                raise P0HorseBatchError(
                    "release candidate bindings drifted; prepare a new candidate"
                ) from exc
            artifact_tmp_path = batch_dir / "approval" / (
                f".commit_artifact_{region}_{artifact_sha}.pending"
            )
            artifact_sha = _write_canonical(artifact_tmp_path, artifact)
        expected_candidate = {
            "schema_version": RELEASE_CANDIDATE_SCHEMA,
            "completion_policy_version": (
                FULL_PROFILE_COMPLETENESS_POLICY_VERSION
            ),
            "status": "pending_independent_release_approval",
            "batch_id": manifest["batch_id"],
            "region": region,
            "executor_reviewer_id": reviewer.id,
            "artifact_prepared_at": candidate.get("artifact_prepared_at"),
            "bindings": {
                **static_bindings,
                "production_snapshot_sha256": artifact[
                    "production_snapshot_sha256"
                ],
                "final_artifact_sha256": artifact_sha,
            },
            "expected_actions": artifact["expected_actions"],
            "auto_first_publish_scope": _build_auto_first_publish_scope(artifact),
        }
        if not artifact_committed and candidate != expected_candidate:
            artifact_tmp_path.unlink(missing_ok=True)
            raise P0HorseBatchError(
                "release candidate bindings drifted; prepare a new candidate"
            )
        if (
            isinstance(previous_commit, dict)
            and previous_commit.get("artifact_sha256")
            and previous_commit["artifact_sha256"] != artifact_sha
        ):
            if artifact_tmp_path is not None:
                artifact_tmp_path.unlink(missing_ok=True)
            raise P0HorseBatchError(
                f"region {region} was already committed with a different artifact; "
                "content fixes must start a new batch"
            )
        if artifact_tmp_path is not None:
            artifact_tmp_path.unlink(missing_ok=True)
            if _sha256_file(artifact_path) != artifact_sha:
                raise P0HorseBatchError("immutable commit artifact drifted")
        release = build_region_release_manifest(
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha,
            bundle=bundle,
            reviewer=reviewer,
            approved_by=approved_by,
            batch_dir=batch_dir,
            region=region,
            release_candidate_path=candidate_path,
            release_candidate_sha256=release_candidate_sha256,
            expected_publish_scope=candidate[
                "auto_first_publish_scope"
            ],
            superseded_releases=[
                old_release
                for old_release in releases
                if old_release["candidate_sha256"]
                != release_candidate_sha256
            ],
            now=now,
        )
        history_key = _candidate_history_key(region, release_candidate_sha256)
        history = {
            **candidate_record,
            "path": str(candidate_path),
            "sha256": release_candidate_sha256,
            "artifact_path": str(artifact_path),
            "artifact_sha256": artifact_sha,
            "publish_scope": candidate["auto_first_publish_scope"],
            "release_path": str(release["release_path"]),
            "release_sha256": release["release_sha256"],
        }
        state.artifacts[history_key] = history
        if (
            state.artifacts.get(f"release_candidate:{region}", {}).get("sha256")
            == release_candidate_sha256
        ):
            state.artifacts[f"release_candidate:{region}"] = history
        state.write()
    # Database work deliberately runs without the batch file lock. The apply
    # transaction and its row locks must finish before checkpoint persistence
    # takes the shared file lock again.
    dry_run_report = dry_run_reviewed_p0_completion_artifact(
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha,
        release_manifest_path=release["release_path"],
        release_manifest_sha256=release["release_sha256"],
    )
    commit_report = commit_reviewed_p0_completion_artifact(
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha,
        release_manifest_path=release["release_path"],
        release_manifest_sha256=release["release_sha256"],
        confirm_reviewed_artifact=True,
    )
    verification = dry_run_reviewed_p0_completion_artifact(
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha,
        release_manifest_path=release["release_path"],
        release_manifest_sha256=release["release_sha256"],
    )

    planned_keys = (
        "planned_profile_creates",
        "planned_profile_updates",
        "planned_race_record_creates",
        "planned_race_record_updates",
        "planned_module_audits",
    )
    planned_remaining = {
        key: int(verification.get(key) or 0) for key in planned_keys
    }
    verification_summary = {
        "verified_at": _utcnow_iso(now),
        "artifact_sha256": artifact_sha,
        "planned_remaining": planned_remaining,
        "passed": not any(planned_remaining.values()),
    }

    from stable.models import HorseProfileCompletionRun

    completion_run = (
        HorseProfileCompletionRun.objects.filter(artifact_path=str(artifact_path))
        .order_by("-id")
        .first()
    )
    with _serial_window(Path(state_dir)):
        # Merge into the latest state: bundle/prepare-release may have written
        # valid fields after the database transaction completed.
        state = BatchRunState.read(batch_dir)
        if state.stage == "abandoned":
            raise P0HorseBatchError(
                "batch run was abandoned; commit checkpoint is forbidden"
            )
        if completion_run is not None:
            completion_run.refresh_from_db()
            manifest = load_batch_manifest(manifest_path)
            parameters = dict(completion_run.parameters or {})
            parameters["p0_batch"] = {
                "batch_id": manifest["batch_id"],
                "batch_manifest_sha256": manifest["batch_sha256"],
                "region": region,
                "publish_scope": candidate["auto_first_publish_scope"],
                "state_dir": str(batch_dir),
            }
            completion_run.parameters = parameters
            summary = dict(completion_run.summary or {})
            summary["idempotent_verification"] = verification_summary
            completion_run.summary = summary
            completion_run.save(
                update_fields=["parameters", "summary", "updated_at"]
            )

        state.artifacts[f"commit:{region}"] = {
            "artifact_path": str(artifact_path),
            "artifact_sha256": artifact_sha,
            "release_path": str(release["release_path"]),
            "release_sha256": release["release_sha256"],
            "release_candidate_sha256": release_candidate_sha256,
            "publish_scope": candidate["auto_first_publish_scope"],
            "idempotent_verification": verification_summary,
        }
        stage_name = f"commit:{region}"
        if stage_name not in state.completed_stages:
            state.completed_stages.append(stage_name)
        state.write()

    if not verification_summary["passed"]:
        raise P0HorseBatchError(
            f"idempotent re-verification failed for region {region}: "
            f"{planned_remaining}"
        )

    from stable.services.p0_horse_completion_batch import (
        mark_batch_manifest_status,
    )

    manifest = load_batch_manifest(manifest_path)
    publish_report = _run_region_publish(
        manifest,
        batch_dir=batch_dir,
        state_dir=Path(state_dir),
        region=region,
        artifact_sha=artifact_sha,
        reviewer=reviewer,
        completion_run=completion_run,
        publish_scope=candidate["auto_first_publish_scope"],
    )

    with _serial_window(Path(state_dir)):
        state = BatchRunState.read(batch_dir)
        if not _regions_pending_commit_or_publish(manifest, state):
            mark_batch_manifest_status(manifest_path, status="committed")
    return {
        "region": region,
        "artifact_sha256": artifact_sha,
        "release_sha256": release["release_sha256"],
        "dry_run": {
            key: int(dry_run_report.get(key) or 0) for key in planned_keys
        },
        "commit_report": {
            "status": commit_report.get("status", "committed"),
        },
        "idempotent_verification": verification_summary,
        "auto_first_publish": publish_report,
        "completion_run_id": completion_run.id if completion_run else None,
    }


def _run_region_publish(
    manifest: dict[str, Any],
    *,
    batch_dir: Path,
    state_dir: Path,
    region: str,
    artifact_sha: str,
    reviewer,
    completion_run,
    publish_scope: dict[str, Any],
) -> dict[str, Any]:
    """Auto first publish for one committed region (publish-p0-horses-basic-tier).

    Publish set covers only targets frozen in the release candidate. On per-profile
    errors the report is recorded without a completed publish stage, so the
    batch cannot reach the committed terminal state until
    ``retry_region_publish`` completes the step.
    """
    from stable.models import HorseP0Source, HorseProfile
    from stable.services.horse_profile_publish import auto_publish_profiles
    from stable.services.p0_horse_completion_batch import _append_approvals_ledger
    with _serial_window(state_dir):
        boundary_state = BatchRunState.read(batch_dir)
        if boundary_state.stage == "abandoned":
            raise P0HorseBatchError(
                "batch run was abandoned; automatic publish is forbidden"
            )

    existing_scope = publish_scope.get("existing_profiles") or []
    create_scope = publish_scope.get("create_new_identities") or []
    region_profile_ids = {
        int(item["profile_id"])
        for item in existing_scope
        if item.get("disposition") == "attempt_publish_after_commit"
    }
    frozen_exclusions = [
        {
            "target_type": "existing_profile",
            "profile_id": int(item["profile_id"]),
            "disposition": item.get("disposition"),
        }
        for item in existing_scope
        if item.get("disposition") != "attempt_publish_after_commit"
    ]
    frozen_exclusions.extend(
        {
            "target_type": "create_new_identity",
            "deterministic_identity_key": item.get(
                "deterministic_identity_key"
            ),
            "disposition": item.get("disposition"),
        }
        for item in create_scope
        if item.get("disposition") != "attempt_publish_after_commit"
    )
    if completion_run is not None:
        wanted_keys = {
            item["deterministic_identity_key"]
            for item in create_scope
            if item.get("disposition") == "attempt_publish_after_commit"
        }
        for source in HorseP0Source.objects.filter(
            completion_run=completion_run,
        ).select_related("profile"):
            batches = (source.profile.source_refs or {}).get(
                "p0_reviewed_batches"
            ) or {}
            if any(batches.get(key) == artifact_sha for key in wanted_keys):
                region_profile_ids.add(source.profile_id)
    publish_report = auto_publish_profiles(
        sorted(region_profile_ids),
        user=reviewer,
        note=(
            f"auto first publish: batch {manifest['batch_id']} region {region} "
            f"artifact {artifact_sha[:12]}"
        ),
    )
    publish_report["profile_ids"] = sorted(region_profile_ids)
    publish_report["frozen_exclusions"] = frozen_exclusions
    publish_report["frozen_exclusion_counts"] = {
        disposition: sum(
            item["disposition"] == disposition
            for item in frozen_exclusions
        )
        for disposition in sorted(
            {
                item["disposition"]
                for item in frozen_exclusions
                if item.get("disposition")
            }
        )
    }
    publish_stage = f"publish:{region}"
    succeeded = not publish_report["errors"]
    with _serial_window(state_dir):
        state = BatchRunState.read(batch_dir)
        # Keep the cumulative published set across retry attempts so the
        # checkpoint preserves the full audit picture.
        previous = state.artifacts.get(publish_stage) or {}
        prior_ids = (
            previous.get("cumulative_published_profile_ids")
            or previous.get("published_profile_ids")
            or []
        )
        if prior_ids:
            publish_report["cumulative_published_profile_ids"] = list(
                dict.fromkeys(
                    [*prior_ids, *publish_report["published_profile_ids"]]
                )
            )
        state.artifacts[publish_stage] = publish_report
        if succeeded:
            if publish_stage not in state.completed_stages:
                state.completed_stages.append(publish_stage)
            state.errors = [
                entry
                for entry in state.errors
                if entry.get("stage") != publish_stage
            ]
        else:
            state.errors.append(
                {
                    "stage": publish_stage,
                    "errors": publish_report["errors"],
                    "recorded_at": _utcnow_iso(),
                }
            )
        state.write()
        if succeeded:
            _append_approvals_ledger(
                batch_dir,
                {
                    "event": "auto_first_publish",
                    "event_schema": AUTO_FIRST_PUBLISH_LEDGER_SCHEMA_V2,
                    "batch_id": manifest["batch_id"],
                    "region": region,
                    "artifact_sha256": artifact_sha,
                    "published": publish_report["published"],
                    "skipped_already_published": publish_report[
                        "skipped_already_published"
                    ],
                    "blocked": publish_report["blocked"],
                    "published_profile_ids": publish_report[
                        "published_profile_ids"
                    ],
                    "frozen_exclusions": publish_report[
                        "frozen_exclusions"
                    ],
                    "frozen_exclusion_counts": publish_report[
                        "frozen_exclusion_counts"
                    ],
                    "at": _utcnow_iso(),
                },
            )
            if completion_run is not None:
                completion_run.refresh_from_db()
                summary = dict(completion_run.summary or {})
                summary["auto_first_publish"] = publish_report
                completion_run.summary = summary
                completion_run.save(
                    update_fields=["summary", "updated_at"]
                )
    if not succeeded:
        raise P0HorseBatchError(
            f"auto first publish failed for region {region}: "
            f"{publish_report['errors']}"
        )
    return publish_report


def retry_region_publish(
    manifest_path: str | Path,
    *,
    region: str,
    reviewer,
) -> dict[str, Any]:
    """Serialize publish recovery against commit and abandon."""
    batch_dir = Path(manifest_path).parent
    with batch_execution_window(batch_dir):
        return _retry_region_publish_locked(
            manifest_path,
            region=region,
            reviewer=reviewer,
        )


def _retry_region_publish_locked(
    manifest_path: str | Path,
    *,
    region: str,
    reviewer,
) -> dict[str, Any]:
    """Re-run only the publish step of a region whose commit succeeded but
    whose auto first publish recorded errors. Does not re-validate or re-apply
    the reviewed artifact (that path intentionally fails closed on drift).
    """
    from stable.models import HorseProfileCompletionRun
    from stable.services.p0_horse_completion_batch import (
        load_batch_manifest,
        mark_batch_manifest_status,
    )

    batch_dir = Path(manifest_path).parent
    state_dir = batch_dir.parent
    with _serial_window(state_dir):
        state = BatchRunState.read(batch_dir)
    commit_stage = f"commit:{region}"
    if commit_stage not in state.completed_stages:
        raise P0HorseBatchError(
            f"region {region} has no successful commit; retry-publish requires "
            "a verified commit first"
        )
    publish_stage = f"publish:{region}"
    if publish_stage in state.completed_stages:
        raise P0HorseBatchError(
            f"region {region} publish already completed; nothing to retry"
        )
    commit_artifact = state.artifacts.get(commit_stage) or {}
    artifact_sha = str(commit_artifact.get("artifact_sha256") or "")
    if not artifact_sha:
        raise P0HorseBatchError(f"region {region} commit artifact is missing")
    verification = commit_artifact.get("idempotent_verification") or {}
    if verification.get("passed") is not True:
        raise P0HorseBatchError(
            f"region {region} commit has no passed idempotent verification; "
            "publishing is forbidden before verification passes"
        )
    if (
        "publish_scope" not in commit_artifact
        or not isinstance(commit_artifact["publish_scope"], dict)
    ):
        raise P0HorseBatchError(
            f"region {region} commit state is missing publish_scope; "
            "manual audit recovery is required"
        )
    manifest = load_batch_manifest(manifest_path)
    completion_run = (
        HorseProfileCompletionRun.objects.filter(
            artifact_path=str(commit_artifact.get("artifact_path") or "")
        )
        .order_by("-id")
        .first()
    )
    publish_report = _run_region_publish(
        manifest,
        batch_dir=batch_dir,
        state_dir=state_dir,
        region=region,
        artifact_sha=artifact_sha,
        reviewer=reviewer,
        completion_run=completion_run,
        publish_scope=commit_artifact["publish_scope"],
    )
    with _serial_window(state_dir):
        state = BatchRunState.read(batch_dir)
        if not _regions_pending_commit_or_publish(manifest, state):
            mark_batch_manifest_status(manifest_path, status="committed")
    return {
        "region": region,
        "auto_first_publish": publish_report,
        "completion_run_id": completion_run.id if completion_run else None,
    }

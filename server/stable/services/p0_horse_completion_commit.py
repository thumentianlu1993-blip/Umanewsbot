"""Region commit stage for rolling P0 horse completion batches.

Serial-window guarded commit: dry-run -> commit -> automatic idempotent
re-verification for one region of a rolling batch, reusing the existing
reviewed-artifact chain. Writes the batch checkpoint pointer and in-flight
profile list into the completion run record.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from stable.services.p0_horse_completion_batch import (
    BatchRunState,
    P0HorseBatchError,
    _utcnow_iso,
)
from stable.services.p0_horse_completion_research import (
    _write_canonical,
    build_region_release_manifest,
)
from stable.services.p0_horse_production_apply import (
    commit_reviewed_p0_completion_artifact,
    dry_run_reviewed_p0_completion_artifact,
    prepare_reviewed_p0_completion_artifact,
)

SERIAL_WINDOW_LOCK_NAME = "serial-window.lock"


@contextmanager
def _serial_window(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / SERIAL_WINDOW_LOCK_NAME
    with lock_path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise P0HorseBatchError(
                "another batch is inside the serial prepare-commit window"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _region_bundle(state: BatchRunState, region: str) -> dict[str, Any]:
    bundle = state.artifacts.get(f"bundle:{region}")
    if not isinstance(bundle, dict):
        raise P0HorseBatchError(
            f"batch has no recorded approval bundle for region {region}"
        )
    return bundle


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


def commit_p0_horse_batch_region(
    manifest_path: str | Path,
    *,
    region: str,
    reviewer,
    approved_by: str,
    state_dir: str | Path,
    confirm_reviewed_artifact: bool = False,
    now=None,
) -> dict[str, Any]:
    """Prepare -> release -> dry-run -> commit -> idempotent re-verify."""
    if not confirm_reviewed_artifact:
        raise P0HorseBatchError("region commit requires --confirm-reviewed-artifact")
    batch_dir = Path(manifest_path).parent
    state = BatchRunState.read(batch_dir)
    if state.stage == "abandoned":
        raise P0HorseBatchError("batch run was abandoned; start a new batch")
    bundle = _region_bundle(state, region)
    combined_path = batch_dir / "artifact" / "combined_candidates.jsonl"
    try:
        combined_sha = hashlib.sha256(combined_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise P0HorseBatchError(
            f"batch combined candidates are unreadable: {combined_path}"
        ) from exc
    try:
        research = json.loads(Path(bundle["research_path"]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise P0HorseBatchError("bundle research v3 is unreadable") from exc
    research_combined_sha = (
        (research.get("generated_from") or {}).get("combined_candidates_sha256")
    )
    if research_combined_sha != combined_sha:
        raise P0HorseBatchError(
            f"bundle research was generated from a stale combined artifact for "
            f"region {region}; re-run prepare and the approval bundle"
        )
    previous_commit = state.artifacts.get(f"commit:{region}")
    with _serial_window(Path(state_dir)):
        artifact = prepare_reviewed_p0_completion_artifact(
            research_v3_path=bundle["research_path"],
            authority_manifest_path=bundle["authority_path"],
            authority_manifest_sha256=bundle["authority_sha256"],
            profile_mapping_decisions_path=bundle["mapping_path"],
            reviewer_id=reviewer.id,
        )
        artifact_path = batch_dir / "approval" / f"commit_artifact_{region}.json"
        artifact_tmp_path = artifact_path.with_suffix(".json.pending")
        artifact_sha = _write_canonical(artifact_tmp_path, artifact)
        if (
            isinstance(previous_commit, dict)
            and previous_commit.get("artifact_sha256")
            and previous_commit["artifact_sha256"] != artifact_sha
        ):
            artifact_tmp_path.unlink(missing_ok=True)
            raise P0HorseBatchError(
                f"region {region} was already committed with a different artifact; "
                "content fixes must start a new batch"
            )
        os.replace(artifact_tmp_path, artifact_path)
        release = build_region_release_manifest(
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha,
            bundle=bundle,
            reviewer=reviewer,
            approved_by=approved_by,
            batch_dir=batch_dir,
            region=region,
            now=now,
        )
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
    if completion_run is not None:
        from stable.services.p0_horse_completion_batch import (
            load_batch_manifest as _load_manifest_for_run,
        )

        manifest = _load_manifest_for_run(manifest_path)
        parameters = dict(completion_run.parameters or {})
        parameters["p0_batch"] = {
            "batch_id": manifest["batch_id"],
            "batch_manifest_sha256": manifest["batch_sha256"],
            "region": region,
            "profile_ids": [
                horse["profile_id"]
                for horse in manifest.get("horses") or []
                if horse.get("region") == region
            ],
            "state_dir": str(batch_dir),
        }
        completion_run.parameters = parameters
        summary = dict(completion_run.summary or {})
        summary["idempotent_verification"] = verification_summary
        completion_run.summary = summary
        completion_run.save(update_fields=["parameters", "summary", "updated_at"])

    state.artifacts[f"commit:{region}"] = {
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact_sha,
        "release_path": str(release["release_path"]),
        "release_sha256": release["release_sha256"],
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
        load_batch_manifest,
        mark_batch_manifest_status,
    )

    manifest = load_batch_manifest(manifest_path)
    publish_report = _run_region_publish(
        manifest,
        batch_dir=batch_dir,
        state=state,
        region=region,
        artifact_sha=artifact_sha,
        reviewer=reviewer,
        completion_run=completion_run,
    )

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
    state: BatchRunState,
    region: str,
    artifact_sha: str,
    reviewer,
    completion_run,
) -> dict[str, Any]:
    """Auto first publish for one committed region (publish-p0-horses-basic-tier).

    Publish set covers the manifest's region profiles plus profiles created
    by the run (create_new rows are not in the manifest). On per-profile
    errors the report is recorded without a completed publish stage, so the
    batch cannot reach the committed terminal state until
    ``retry_region_publish`` completes the step.
    """
    from stable.models import HorseP0Source, HorseProfile
    from stable.services.horse_profile_publish import auto_publish_profiles
    from stable.services.p0_horse_completion_batch import _append_approvals_ledger

    region_profile_ids = {
        horse["profile_id"]
        for horse in manifest.get("horses") or []
        if horse.get("region") == region
    }
    if completion_run is not None:
        region_profile_ids.update(
            HorseP0Source.objects.filter(
                completion_run=completion_run,
            ).values_list("profile_id", flat=True)
        )
    publish_report = auto_publish_profiles(
        HorseProfile.objects.select_for_update()
        .filter(pk__in=region_profile_ids)
        .order_by("id"),
        user=reviewer,
        note=(
            f"auto first publish: batch {manifest['batch_id']} region {region} "
            f"artifact {artifact_sha[:12]}"
        ),
    )
    publish_report["profile_ids"] = sorted(region_profile_ids)
    publish_stage = f"publish:{region}"
    # Keep the cumulative published set across retry attempts so the checkpoint
    # preserves the full audit picture, not just the last attempt's.
    previous = state.artifacts.get(publish_stage) or {}
    prior_ids = previous.get("published_profile_ids") or []
    if prior_ids:
        publish_report["cumulative_published_profile_ids"] = list(
            dict.fromkeys([*prior_ids, *publish_report["published_profile_ids"]])
        )
    state.artifacts[publish_stage] = publish_report
    succeeded = not publish_report["errors"]
    if succeeded:
        if publish_stage not in state.completed_stages:
            state.completed_stages.append(publish_stage)
        # a successful publish (inline or via retry) resolves earlier failures
        state.errors = [
            entry for entry in state.errors if entry.get("stage") != publish_stage
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
                "batch_id": manifest["batch_id"],
                "region": region,
                "artifact_sha256": artifact_sha,
                "published": publish_report["published"],
                "skipped_already_published": publish_report["skipped_already_published"],
                "blocked": publish_report["blocked"],
                "published_profile_ids": publish_report["published_profile_ids"],
                "at": _utcnow_iso(),
            },
        )
        if completion_run is not None:
            summary = dict(completion_run.summary or {})
            summary["auto_first_publish"] = publish_report
            completion_run.summary = summary
            completion_run.save(update_fields=["summary", "updated_at"])
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
        state=state,
        region=region,
        artifact_sha=artifact_sha,
        reviewer=reviewer,
        completion_run=completion_run,
    )
    # publish succeeded: drop the recorded publish error entries
    state.errors = [
        entry for entry in state.errors if entry.get("stage") != publish_stage
    ]
    state.write()
    if not _regions_pending_commit_or_publish(manifest, state):
        mark_batch_manifest_status(manifest_path, status="committed")
    return {
        "region": region,
        "auto_first_publish": publish_report,
        "completion_run_id": completion_run.id if completion_run else None,
    }

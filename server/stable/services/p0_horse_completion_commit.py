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
        artifact_sha = _write_canonical(artifact_path, artifact)
        if (
            isinstance(previous_commit, dict)
            and previous_commit.get("artifact_sha256")
            and previous_commit["artifact_sha256"] != artifact_sha
        ):
            raise P0HorseBatchError(
                f"region {region} was already committed with a different artifact; "
                "content fixes must start a new batch"
            )
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
    remaining_regions = [
        manifest_region
        for manifest_region in manifest.get("regions") or []
        if f"commit:{manifest_region}" not in state.completed_stages
    ]
    if not remaining_regions:
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
        "completion_run_id": completion_run.id if completion_run else None,
    }

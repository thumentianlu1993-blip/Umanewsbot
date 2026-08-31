from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from stable.services.historical_calendar_release_b_schema import (
    check_release_b_schema_compatibility,
    check_initial_install_schema_compatibility,
    collect_live_production_audit,
)
from stable.models import (
    ExternalDataImportLock,
    ExternalDataImportRun,
    HistoricalBatchRun,
    HorseProfileCompletionRun,
    RaceResultReviewRun,
)


HANDOFF_SCHEMA_VERSION = "migration-history-repair-preflight/v4"
PARTIAL_LEAF_SETS = {
    (
        "stable.0068_race_data_sync_pipeline_a_field_audit",
        "stable.0070_horse_identity_evidence_commit_receipt",
    ),
    (
        "stable.0069_race_data_sync_pipeline_a_ledger_guards",
        "stable.0070_horse_identity_evidence_commit_receipt",
    ),
}
REPAIR_LEAF_SETS = PARTIAL_LEAF_SETS | {
    ("stable.0070_horse_identity_evidence_commit_receipt",),
}
PREVIOUS_FINAL_LEAF_SET = (
    "stable.0075_race_data_source_priority_and_reported_position",
)
RECOVERABLE_FORWARD_PARTIAL_LEAF_SET = (
    "stable.0076_alter_externaldataimporterror_racing_region_and_more",
)
FINAL_LEAF_SET = (
    "stable.0077_racing_api_horse_identity_staging",
)
LEGACY_FINAL_LEAF_SETS = {
    ("stable.0071_historical_calendar_release_b",),
    ("stable.0072_add_extended_racing_regions",),
    ("stable.0073_lifecycle_enforce_registry",),
    ("stable.0074_race_data_sync_r0_control_plane",),
    PREVIOUS_FINAL_LEAF_SET,
}
ORDINARY_RELEASE_LEAF_SETS = LEGACY_FINAL_LEAF_SETS | {
    RECOVERABLE_FORWARD_PARTIAL_LEAF_SET,
    FINAL_LEAF_SET,
}
INITIAL_INSTALL_LEAF_SET = ("stable.0067_historical_calendar_release_a",)
RELEASE_0077_MIGRATION_NAME = "0077_racing_api_horse_identity_staging"
RELEASE_0077_RECOVERY_MANIFEST_SCHEMA = (
    "release-0077-verified-backup-recovery/v1"
)


def _lower_hex(value: str, *, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def release_0077_recovery_binding(
    *,
    preflight: dict[str, Any],
    candidate_commit: str,
    candidate_image_id: str,
    artifact_path: str,
    handoff_action: str,
    manifest_path: str = "",
    manifest_sha256: str = "",
    origin_handoff_sha256: str = "",
) -> dict[str, Any]:
    """Return the SHA-bound 0077 recovery admission carried by a handoff.

    A deploy artifact created before writers stop is admission-only.  It may
    stop/drain services, but the release task must consume a second no-clobber
    artifact whose manifest fields are bound.  A 0076 manual-release is a
    recovery entry and therefore never gets the admission-only exception.
    """

    values = (manifest_path, manifest_sha256, origin_handoff_sha256)
    if any(values) and not all(values):
        raise ValueError("0077 recovery manifest binding is incomplete")
    plan = preflight.get("migration_plan") or []
    crosses_0077 = RELEASE_0077_MIGRATION_NAME in plan
    leaf_set = tuple(sorted(preflight.get("migration_leaf_set") or []))
    if not all(values):
        if crosses_0077 and handoff_action == "manual-release":
            raise ValueError(
                "0077 manual release requires the original release-bound recovery manifest"
            )
        return {
            "release_0077_recovery_binding_mode": (
                "admission-only"
                if crosses_0077 and handoff_action == "deploy"
                else "not-required"
            ),
            "release_0077_recovery_manifest_path": None,
            "release_0077_recovery_manifest_sha256": None,
            "release_0077_recovery_origin_handoff_sha256": None,
        }

    if not crosses_0077 or handoff_action not in {"deploy", "manual-release"}:
        raise ValueError("0077 recovery manifest is not valid for this handoff")
    if handoff_action == "deploy" and leaf_set != PREVIOUS_FINAL_LEAF_SET:
        raise ValueError("bound 0077 deploy requires exact starting leaf 0075")
    if (
        handoff_action == "manual-release"
        and leaf_set != RECOVERABLE_FORWARD_PARTIAL_LEAF_SET
    ):
        raise ValueError("bound 0077 manual release requires exact partial leaf 0076")
    if not _lower_hex(candidate_commit, length=40):
        raise ValueError("0077 recovery candidate commit is invalid")
    if not _lower_hex(manifest_sha256, length=64) or not _lower_hex(
        origin_handoff_sha256, length=64
    ):
        raise ValueError("0077 recovery manifest SHA binding is invalid")
    manifest = Path(manifest_path)
    artifact = Path(artifact_path)
    if (
        not manifest.is_absolute()
        or manifest.name != f"{candidate_commit}.json"
        or manifest.parent.name != "release-0077-recovery"
        or not artifact.is_absolute()
        or manifest.parent.parent not in artifact.parents
    ):
        raise ValueError("0077 recovery manifest path is not canonical")
    manifest_errors = _verify_release_0077_recovery_manifest(
        path=manifest,
        expected_sha256=manifest_sha256,
        expected_candidate_commit=candidate_commit,
        expected_candidate_image_id=candidate_image_id,
        expected_database_identity_sha256=(
            preflight.get("database_identity_sha256") or ""
        ),
        expected_origin_handoff_sha256=origin_handoff_sha256,
    )
    if manifest_errors:
        raise ValueError(
            "0077 recovery manifest verification failed: "
            + ",".join(manifest_errors)
        )
    return {
        "release_0077_recovery_binding_mode": "bound",
        "release_0077_recovery_manifest_path": str(manifest),
        "release_0077_recovery_manifest_sha256": manifest_sha256,
        "release_0077_recovery_origin_handoff_sha256": origin_handoff_sha256,
    }


def authorize_handoff_action(
    *, leaf_set: list[str], action: str, restricted_marker_ok: bool,
    active_marker_present: bool = False,
) -> dict[str, Any]:
    leaves = tuple(sorted(leaf_set))
    if active_marker_present and action != "forward-resume":
        return {"ok": False, "requires_restricted_marker": True}
    if action == "initial-install":
        return {
            "ok": leaves == INITIAL_INSTALL_LEAF_SET and not active_marker_present,
            "requires_restricted_marker": True,
        }
    if leaves == RECOVERABLE_FORWARD_PARTIAL_LEAF_SET:
        return {
            # 0076 can only be completed by the stopped-service manual-release
            # entry, which verifies HEAD == candidate image revision.  A fresh
            # deploy could rebuild/switch candidates after the partial commit,
            # while the older restricted-marker protocol does not bind 0076.
            "ok": action == "manual-release",
            "requires_restricted_marker": False,
        }
    if action == "forward-resume":
        return {"ok": restricted_marker_ok, "requires_restricted_marker": True}
    # This release is forward-only.  Returning to PR #133 / leaf 0075 requires
    # the separately authorized, release-bound verified backup restore; no
    # migration handoff may turn a generic code rollback into that recovery.
    if action == "rollback":
        return {
            "ok": False,
            "requires_restricted_marker": False,
        }
    if leaves in PARTIAL_LEAF_SETS:
        return {"ok": False, "requires_restricted_marker": True}
    return {
        "ok": action in {"deploy", "manual-release"},
        "requires_restricted_marker": False,
    }


def collect_writer_activity() -> dict[str, Any]:
    counts = {
        "external_import_locks": ExternalDataImportLock.objects.filter(
            locked_by_run__isnull=False
        ).count(),
        "external_import_started": ExternalDataImportRun.objects.filter(
            status="started"
        ).count(),
        "historical_batches_running": HistoricalBatchRun.objects.filter(
            status="running"
        ).count(),
        "horse_p0_runs_running": HorseProfileCompletionRun.objects.filter(
            status="running"
        ).count(),
        "race_result_reviews_claimed": RaceResultReviewRun.objects.filter(
            status="claimed"
        ).count(),
    }
    flags = {
        name: os.environ.get(name, "false").strip().lower()
        for name in (
            "RACE_LIVE_SCHEDULER_ENABLED",
            "RACE_LIVE_MONITOR_ENABLED",
            "RACE_DATA_SYNC_ENABLED",
            "RACE_DATA_SYNC_SCHEDULER_ENABLED",
            "RACE_DATA_SYNC_ALLOW_NETWORK",
            "RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED",
            "RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED",
            "RACE_DATA_SYNC_RACECARD_APPLY_ENABLED",
            "RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED",
            "RACE_DATA_SYNC_RESULT_APPLY_ENABLED",
            "RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED",
            "RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED",
            "HISTORICAL_RACE_BACKFILL_ENABLED",
            "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK",
        )
    }
    flags_ok = all(value in {"", "0", "false", "off", "no"} for value in flags.values())
    return {"ok": not any(counts.values()) and flags_ok, "counts": counts, "flags": flags}


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    return json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_artifact_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def production_audit_policy_for_leaf_set(
    leaf_set: list[str], *, repair_intent: bool = False
) -> str:
    return (
        "reviewed-static"
        if repair_intent or tuple(sorted(leaf_set)) in REPAIR_LEAF_SETS
        else "live-handoff"
    )


def collect_handoff_preflight(*, repair_intent: bool = False) -> dict[str, Any]:
    initial = check_release_b_schema_compatibility(
        direction="forward", enforce_production_audit=False
    )
    policy = production_audit_policy_for_leaf_set(
        initial["migration_leaf_set"], repair_intent=repair_intent
    )
    if not initial["ok"]:
        result = initial
    elif policy == "reviewed-static":
        result = check_release_b_schema_compatibility(
            direction="forward", enforce_production_audit=True
        )
    else:
        result = initial
        result["production_audit_live"] = collect_live_production_audit()
        result["production_audit_ok"] = True
        result["production_audit_drift_fields"] = []
    result["production_audit_policy"] = policy
    return result


def collect_initial_install_preflight() -> dict[str, Any]:
    return check_initial_install_schema_compatibility()


def build_preflight_artifact(
    *,
    preflight: dict[str, Any],
    candidate_commit: str,
    candidate_image_id: str,
    compose_file: str,
    deployment_lock_token_sha256: str,
    artifact_path: str,
    handoff_action: str,
    release_0077_recovery_manifest_path: str = "",
    release_0077_recovery_manifest_sha256: str = "",
    release_0077_recovery_origin_handoff_sha256: str = "",
) -> dict[str, Any]:
    live = preflight.get("production_audit_live") or {}
    writer_activity = collect_writer_activity()
    if not writer_activity["ok"]:
        raise ValueError("application writer activity is not quiescent")
    recovery_origin_action = (
        "initial-install"
        if handoff_action == "initial-install"
        or preflight.get("recovery_origin_action") == "initial-install"
        else "migration-history-repair"
    )
    recovery_binding = release_0077_recovery_binding(
        preflight=preflight,
        candidate_commit=candidate_commit,
        candidate_image_id=candidate_image_id,
        artifact_path=artifact_path,
        handoff_action=handoff_action,
        manifest_path=release_0077_recovery_manifest_path,
        manifest_sha256=release_0077_recovery_manifest_sha256,
        origin_handoff_sha256=release_0077_recovery_origin_handoff_sha256,
    )
    payload: dict[str, Any] = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "candidate_commit": candidate_commit,
        "candidate_image_id": candidate_image_id,
        "database_identity_sha256": preflight["database_identity_sha256"],
        "compose_file": compose_file,
        "deployment_lock_token_sha256": deployment_lock_token_sha256,
        "artifact_path": artifact_path,
        "handoff_action": handoff_action,
        "recovery_intent_mode": (
            "required"
            if handoff_action in {"forward-resume", "initial-install"}
            or tuple(sorted(preflight.get("migration_leaf_set", [])))
            in REPAIR_LEAF_SETS
            else "not-required"
        ),
        "recovery_origin_action": recovery_origin_action,
        "recovery_origin_catalog_sha256": (
            preflight.get("recovery_origin_catalog_sha256")
            or (preflight.get("catalog_sha256") if recovery_origin_action == "initial-install" else None)
        ),
        "recovery_origin_rows_sha256": (
            preflight.get("recovery_origin_rows_sha256")
            or (preflight.get("rows_sha256") if recovery_origin_action == "initial-install" else None)
        ),
        "recovery_origin_data_state": (
            preflight.get("recovery_origin_data_state")
            or (preflight.get("initial_install_data_state") if recovery_origin_action == "initial-install" else None)
        ),
        "recovery_origin_legacy_counts": (
            preflight.get("recovery_origin_legacy_counts")
            or (preflight.get("initial_install_legacy_counts") if recovery_origin_action == "initial-install" else None)
        ),
        "receipt_rows_sha256": live.get("receipt_rows_sha256"),
        "operation_log_rows_sha256": live.get("operation_log_rows_sha256"),
        "operation_log_fk_sha256": live.get("operation_log_fk_sha256"),
        "preflight": preflight,
        "writer_activity": writer_activity,
        **recovery_binding,
    }
    payload["artifact_sha256"] = canonical_artifact_sha256(payload)
    return payload


def _open_trusted_parent(path: Path) -> tuple[int | None, list[str]]:
    errors: list[str] = []
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        parent_fd = os.open(path.parent, flags)
    except OSError:
        try:
            if stat.S_ISLNK(path.parent.lstat().st_mode):
                return None, ["parent_symlink"]
        except OSError:
            pass
        return None, ["parent_untrusted"]
    info = os.fstat(parent_fd)
    if not stat.S_ISDIR(info.st_mode):
        errors.append("parent_not_directory")
    if info.st_uid != os.getuid():
        errors.append("parent_owner")
    if stat.S_IMODE(info.st_mode) != 0o700:
        errors.append("parent_mode")
    if errors:
        os.close(parent_fd)
        return None, errors
    return parent_fd, []


def _publish_trusted_json(*, path: Path, payload: dict[str, Any]) -> None:
    parent_fd, errors = _open_trusted_parent(path)
    if errors or parent_fd is None:
        raise ValueError("untrusted artifact parent: " + ",".join(errors))
    if path.name in {"", ".", ".."}:
        os.close(parent_fd)
        raise ValueError("invalid artifact basename")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
        try:
            encoded = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:  # pragma: no cover - defensive OS failure
                    raise OSError("short artifact write")
                remaining = remaining[written:]
            os.fsync(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError("artifact is not a user-owned regular file")
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("artifact mode is not 0600")
        finally:
            os.close(fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _open_trusted_json(
    path: Path,
) -> tuple[dict[str, Any] | None, int | None, int | None, list[str]]:
    """Open and parse a trusted JSON file while retaining its object identity."""
    parent_fd, errors = _open_trusted_parent(path)
    if errors or parent_fd is None:
        return None, None, None, errors
    fd: int | None = None
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path.name, flags, dir_fd=parent_fd)
        except OSError:
            try:
                if stat.S_ISLNK(path.lstat().st_mode):
                    errors.append("symlink")
                else:
                    errors.append("missing_or_untrusted")
            except OSError:
                errors.append("missing_or_untrusted")
            raise ValueError
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            errors.append("not_regular")
        if info.st_uid != os.getuid():
            errors.append("owner")
        if stat.S_IMODE(info.st_mode) != 0o600:
            errors.append("mode")
        if errors:
            raise ValueError
        try:
            with os.fdopen(os.dup(fd), "r", encoding="utf-8") as stream:
                payload = json.load(stream)
            if not isinstance(payload, dict):
                raise ValueError
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            errors.append("invalid_json")
            raise ValueError
        return payload, parent_fd, fd, []
    except ValueError:
        if fd is not None:
            os.close(fd)
        os.close(parent_fd)
        return None, None, None, sorted(set(errors))


def _read_trusted_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    payload, parent_fd, fd, errors = _open_trusted_json(path)
    if payload is None:
        return None, errors
    assert parent_fd is not None and fd is not None
    try:
        return payload, []
    finally:
        os.close(fd)
        os.close(parent_fd)


def _read_trusted_json_and_sha256(
    path: Path,
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    payload, parent_fd, fd, errors = _open_trusted_json(path)
    if payload is None:
        return None, None, errors
    assert parent_fd is not None and fd is not None
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        return payload, digest.hexdigest(), []
    finally:
        os.close(fd)
        os.close(parent_fd)


def _verify_release_0077_recovery_manifest(
    *,
    path: Path,
    expected_sha256: str,
    expected_candidate_commit: str,
    expected_candidate_image_id: str,
    expected_database_identity_sha256: str,
    expected_origin_handoff_sha256: str,
) -> list[str]:
    payload, actual_sha256, errors = _read_trusted_json_and_sha256(path)
    if payload is None:
        return [f"trust:{error}" for error in errors]
    checks = {
        "schema_version": RELEASE_0077_RECOVERY_MANIFEST_SCHEMA,
        "candidate_commit": expected_candidate_commit,
        "candidate_image_id": expected_candidate_image_id,
        "database_identity_sha256": expected_database_identity_sha256,
        "origin_handoff_sha256": expected_origin_handoff_sha256,
        "source_leaf": PREVIOUS_FINAL_LEAF_SET[0],
    }
    if actual_sha256 != expected_sha256:
        errors.append("sha256")
    for key, expected in checks.items():
        if payload.get(key) != expected:
            errors.append(f"binding:{key}")
    image_id = payload.get("candidate_image_id")
    if not (
        isinstance(image_id, str)
        and image_id.startswith("sha256:")
        and _lower_hex(image_id.removeprefix("sha256:"), length=64)
    ):
        errors.append("candidate_image_id")
    backup_path = payload.get("backup_path")
    if not isinstance(backup_path, str) or not Path(backup_path).is_absolute():
        errors.append("backup_path")
    for key in ("backup_sha256", "pg_restore_list_sha256"):
        if not _lower_hex(payload.get(key), length=64):
            errors.append(key)
    for key in ("backup_size_bytes", "pg_restore_list_line_count"):
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(key)
    created_at = payload.get("created_at_utc")
    if not isinstance(created_at, str) or not created_at.endswith("Z"):
        errors.append("created_at_utc")
    return sorted(set(errors))


def publish_preflight_artifact(*, path: Path, payload: dict[str, Any]) -> None:
    _publish_trusted_json(path=path, payload=payload)


def verify_preflight_artifact(
    *, path: Path, expected_artifact_sha256: str, expected_bindings: dict[str, Any]
) -> dict[str, Any]:
    payload, errors = _read_trusted_json(path)
    if payload is not None:
        actual = canonical_artifact_sha256(payload)
        if payload.get("artifact_sha256") != actual or actual != expected_artifact_sha256:
            errors.append("sha256")
        if payload.get("schema_version") != HANDOFF_SCHEMA_VERSION:
            errors.append("schema_version")
        for key, expected in expected_bindings.items():
            if payload.get(key) != expected:
                errors.append(f"binding:{key}")
        try:
            recovery_binding = release_0077_recovery_binding(
                preflight=payload.get("preflight") or {},
                candidate_commit=payload.get("candidate_commit") or "",
                candidate_image_id=payload.get("candidate_image_id") or "",
                artifact_path=payload.get("artifact_path") or "",
                handoff_action=payload.get("handoff_action") or "",
                manifest_path=(
                    payload.get("release_0077_recovery_manifest_path") or ""
                ),
                manifest_sha256=(
                    payload.get("release_0077_recovery_manifest_sha256") or ""
                ),
                origin_handoff_sha256=(
                    payload.get("release_0077_recovery_origin_handoff_sha256")
                    or ""
                ),
            )
        except ValueError:
            errors.append("release_0077_recovery_binding")
        else:
            for key, expected in recovery_binding.items():
                if payload.get(key) != expected:
                    errors.append(f"binding:{key}")
    return {"ok": not errors, "errors": sorted(set(errors)), "payload": payload}


def verify_closed_state(
    *, path: Path, expected_artifact_sha256: str, expected_bindings: dict[str, Any]
) -> dict[str, Any]:
    trust = verify_preflight_artifact(
        path=path,
        expected_artifact_sha256=expected_artifact_sha256,
        expected_bindings=expected_bindings,
    )
    if not trust["ok"]:
        return {"ok": False, "artifact_errors": trust["errors"], "drift_fields": []}
    fresh = (
        collect_initial_install_preflight()
        if trust["payload"].get("recovery_origin_action") == "initial-install"
        else collect_handoff_preflight()
    )
    if not fresh.get("ok"):
        return {
            "ok": False,
            "artifact_errors": [],
            "drift_fields": fresh.get("drift_paths", []),
            "drift_paths": fresh.get("drift_paths", []),
            "database_vendor": fresh.get("database_vendor"),
            "migration_leaf_set": fresh.get("migration_leaf_set", []),
            "migration_plan": fresh.get("migration_plan", []),
        }
    expected = trust["payload"]["preflight"]
    writer_activity = collect_writer_activity()
    drift = [
        field
        for field in (
            "schema_version",
            "applied_nodes",
            "migration_leaf_set",
            "migration_plan",
            "candidate_post_target_migrations",
            "migration_graph_target_exclusive",
            "unknown_applied_migrations",
            "database_identity_sha256",
            "rows_sha256",
            "catalog_sha256",
            "production_audit_live",
        )
        if fresh.get(field) != expected.get(field)
    ]
    return {
        "ok": fresh.get("ok") is True and writer_activity["ok"] and not drift,
        "artifact_errors": [],
        "drift_fields": drift,
        "migration_leaf_set": fresh.get("migration_leaf_set", []),
        "migration_plan": fresh.get("migration_plan", []),
        "writer_activity": writer_activity,
    }


def validate_restricted_recovery(
    *, leaf_set: list[str], marker: dict[str, Any] | None,
    expected_binding: dict[str, Any], action: str
) -> dict[str, Any]:
    partial = tuple(sorted(leaf_set)) in PARTIAL_LEAF_SETS
    if not partial:
        return {"ok": marker is None, "restricted": False}
    marker_origin = tuple(sorted((marker or {}).get("initial_leaf_set", [])))
    bindings_ok = (
        bool(marker)
        and marker.get("marker_sha256") == _marker_sha256(marker)
        and marker_origin == ("stable.0070_horse_identity_evidence_commit_receipt",)
        and all(marker.get(key) == value for key, value in expected_binding.items())
    )
    return {
        "ok": action == "forward-resume" and bindings_ok,
        "restricted": True,
    }


def _marker_sha256(marker: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in marker.items() if key != "marker_sha256"}
    return hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_restricted_recovery_marker(
    *, binding: dict[str, Any], leaf_set: list[str]
) -> dict[str, Any]:
    initial_leaf_set = sorted(leaf_set)
    initial = tuple(initial_leaf_set)
    if initial not in {
        ("stable.0070_horse_identity_evidence_commit_receipt",),
        INITIAL_INSTALL_LEAF_SET,
    }:
        raise ValueError("restricted recovery intent has an unreviewed origin")
    required = {
        "candidate_commit",
        "candidate_image_id",
        "artifact_sha256",
        "database_identity_sha256",
    }
    missing = sorted(required - set(binding))
    if missing:
        raise ValueError("restricted recovery binding missing: " + ",".join(missing))
    origin_action = binding.get("origin_action", "migration-history-repair")
    if initial == INITIAL_INSTALL_LEAF_SET and origin_action != "initial-install":
        raise ValueError("initial-install marker requires exact origin action")
    if initial != INITIAL_INSTALL_LEAF_SET and origin_action == "initial-install":
        raise ValueError("initial-install origin requires exact 0067")
    marker = {
        "schema_version": (
            "migration-history-repair-restricted-recovery/v2"
            if origin_action == "initial-install"
            else "migration-history-repair-restricted-recovery/v1"
        ),
        **binding,
        "action": "forward-resume",
        "initial_leaf_set": initial_leaf_set,
        "migration_leaf_set": initial_leaf_set,
    }
    marker["marker_sha256"] = _marker_sha256(marker)
    return marker


def publish_restricted_recovery_marker(*, path: Path, marker: dict[str, Any]) -> None:
    if marker.get("marker_sha256") != _marker_sha256(marker):
        raise ValueError("invalid restricted marker SHA")
    _publish_trusted_json(path=path, payload=marker)


def restricted_marker_origin_action(*, path: Path) -> str | None:
    """Read only a self-authenticated origin hint; binding checks still follow."""
    marker, errors = _read_trusted_json(path)
    if marker is None or errors or marker.get("marker_sha256") != _marker_sha256(marker):
        return None
    if (
        marker.get("schema_version")
        == "migration-history-repair-restricted-recovery/v2"
        and marker.get("initial_leaf_set") == list(INITIAL_INSTALL_LEAF_SET)
        and marker.get("origin_action") == "initial-install"
        and marker.get("allowed_recovery_action") == "forward-resume"
    ):
        return "initial-install"
    return None


def verify_restricted_recovery_marker(
    *, path: Path, expected_binding: dict[str, Any], expected_leaf_set: list[str]
) -> dict[str, Any]:
    marker, errors = _read_trusted_json(path)
    if marker is None:
        return {"ok": False, "errors": errors, "marker": None}
    errors.extend(
        _restricted_marker_validation_errors(
            marker=marker,
            expected_binding=expected_binding,
            expected_leaf_set=expected_leaf_set,
        )
    )
    return {"ok": not errors, "errors": sorted(set(errors)), "marker": marker}


def _restricted_marker_validation_errors(
    *,
    marker: dict[str, Any],
    expected_binding: dict[str, Any],
    expected_leaf_set: list[str],
) -> list[str]:
    errors: list[str] = []
    schema_version = marker.get("schema_version")
    if schema_version not in {
        "migration-history-repair-restricted-recovery/v1",
        "migration-history-repair-restricted-recovery/v2",
    }:
        errors.append("schema_version")
    if marker.get("marker_sha256") != _marker_sha256(marker):
        errors.append("marker_sha256")
    for key, value in expected_binding.items():
        if marker.get(key) != value:
            errors.append(f"binding:{key}")
    initial_leaf_set = marker.get("initial_leaf_set")
    if initial_leaf_set != sorted(expected_leaf_set):
        errors.append("initial_leaf_set")
    if marker.get("migration_leaf_set") != initial_leaf_set:
        errors.append("migration_leaf_set")
    expected_initial = tuple(sorted(expected_leaf_set))
    if expected_initial not in {
        ("stable.0070_horse_identity_evidence_commit_receipt",),
        INITIAL_INSTALL_LEAF_SET,
    }:
        errors.append("not_initial_state")
    if expected_initial == INITIAL_INSTALL_LEAF_SET:
        if schema_version != "migration-history-repair-restricted-recovery/v2":
            errors.append("schema_version")
        if marker.get("origin_action") != "initial-install":
            errors.append("origin_action")
        if marker.get("allowed_recovery_action") != "forward-resume":
            errors.append("allowed_recovery_action")
        if not marker.get("initial_catalog_sha256"):
            errors.append("initial_catalog_sha256")
        if not marker.get("initial_rows_sha256"):
            errors.append("initial_rows_sha256")
        if marker.get("initial_install_data_state") not in {"empty", "legacy-compatible"}:
            errors.append("initial_install_data_state")
        legacy_counts = marker.get("initial_legacy_counts")
        if not isinstance(legacy_counts, dict) or set(legacy_counts) != {
            "race_events", "historical_targets"
        }:
            errors.append("initial_legacy_counts")
    elif marker.get("origin_action") == "initial-install":
        errors.append("origin_action")
    if marker.get("action") != "forward-resume":
        errors.append("action")
    return sorted(set(errors))


def verify_restricted_marker_for_live_state(
    *, path: Path, expected_binding: dict[str, Any], live_leaf_set: list[str]
) -> dict[str, Any]:
    marker, errors = _read_trusted_json(path)
    if marker is None:
        return {"ok": False, "errors": errors, "marker": None}
    marker_leaf = marker.get("initial_leaf_set", [])
    errors.extend(
        _restricted_marker_validation_errors(
            marker=marker,
            expected_binding=expected_binding,
            expected_leaf_set=marker_leaf,
        )
    )
    live = tuple(sorted(live_leaf_set))
    marker_state = tuple(sorted(marker_leaf))
    if marker_state == INITIAL_INSTALL_LEAF_SET:
        allowed_live_states = {
            INITIAL_INSTALL_LEAF_SET,
            ("stable.0070_horse_identity_evidence_commit_receipt",),
            (
                "stable.0068_race_data_sync_pipeline_a_field_audit",
                "stable.0070_horse_identity_evidence_commit_receipt",
            ),
            (
                "stable.0069_race_data_sync_pipeline_a_ledger_guards",
                "stable.0070_horse_identity_evidence_commit_receipt",
            ),
            *LEGACY_FINAL_LEAF_SETS,
            RECOVERABLE_FORWARD_PARTIAL_LEAF_SET,
            FINAL_LEAF_SET,
        }
    else:
        allowed_live_states = REPAIR_LEAF_SETS | {
            *LEGACY_FINAL_LEAF_SETS,
            RECOVERABLE_FORWARD_PARTIAL_LEAF_SET,
            FINAL_LEAF_SET,
        }
        if marker_state != ("stable.0070_horse_identity_evidence_commit_receipt",):
            errors.append("marker_not_initial")
    if live not in allowed_live_states:
        errors.append("unsafe_live_state")
    return {"ok": not errors, "errors": sorted(set(errors)), "marker": marker}


def _same_trusted_marker_object(info: os.stat_result, trusted: os.stat_result) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == trusted.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == stat.S_IMODE(trusted.st_mode) == 0o600
        and info.st_dev == trusted.st_dev
        and info.st_ino == trusted.st_ino
    )


def _rename_noreplace(
    *, parent_fd: int, source_name: str, destination_name: str
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    destination = os.fsencode(destination_name)
    if sys.platform.startswith("linux"):
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise OSError(errno.ENOTSUP, "renameat2(RENAME_NOREPLACE) unavailable")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(parent_fd, source, parent_fd, destination, 1)
    elif sys.platform == "darwin":
        rename = getattr(libc, "renameatx_np", None)
        if rename is None:
            raise OSError(errno.ENOTSUP, "renameatx_np(RENAME_EXCL) unavailable")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(parent_fd, source, parent_fd, destination, 0x00000004)
    else:
        raise OSError(errno.ENOTSUP, "atomic no-replace rename unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination_name)


def find_completed_restricted_recovery_marker(
    *,
    path: Path,
    expected_binding: dict[str, Any],
    expected_file_identity: tuple[int, int] | None = None,
) -> Path | None:
    parent_fd, errors = _open_trusted_parent(path)
    if parent_fd is None or errors:
        raise ValueError("untrusted restricted marker parent")
    try:
        names = os.listdir(parent_fd)
    finally:
        os.close(parent_fd)
    matches: list[Path] = []
    for name in names:
        if not (
            name.startswith("restricted-recovery.completed.")
            and name.endswith(".json")
        ):
            continue
        completed = path.parent / name
        marker, read_errors = _read_trusted_json(completed)
        if marker is None or read_errors:
            continue
        expected_name = (
            f"restricted-recovery.completed.{marker.get('marker_sha256', '')}.json"
        )
        validation_errors = _restricted_marker_validation_errors(
            marker=marker,
            expected_binding=expected_binding,
            expected_leaf_set=marker.get("initial_leaf_set", []),
        )
        if name == expected_name and not validation_errors:
            if expected_file_identity is not None:
                info = completed.stat(follow_symlinks=False)
                if (info.st_dev, info.st_ino) != expected_file_identity:
                    continue
            matches.append(completed)
    if len(matches) > 1:
        raise ValueError("multiple completed restricted recovery markers")
    return matches[0] if matches else None


def trusted_restricted_marker_identity(
    *, path: Path, expected_binding: dict[str, Any]
) -> tuple[int, int]:
    marker, parent_fd, marker_fd, errors = _open_trusted_json(path)
    if marker is None:
        raise ValueError("untrusted restricted marker: " + ",".join(errors))
    assert parent_fd is not None and marker_fd is not None
    try:
        validation_errors = _restricted_marker_validation_errors(
            marker=marker,
            expected_binding=expected_binding,
            expected_leaf_set=marker.get("initial_leaf_set", []),
        )
        if validation_errors:
            raise ValueError("restricted marker verification failed")
        info = os.fstat(marker_fd)
        return info.st_dev, info.st_ino
    finally:
        os.close(marker_fd)
        os.close(parent_fd)


def complete_restricted_recovery_marker(
    *,
    path: Path,
    expected_binding: dict[str, Any],
    expected_file_identity: tuple[int, int] | None = None,
) -> Path:
    transition_path = path.parent / "restricted-recovery.transition.json"
    active_exists = os.path.lexists(path)
    transition_exists = os.path.lexists(transition_path)
    if active_exists and transition_exists:
        raise ValueError("active and transition marker conflict")
    if not active_exists and not transition_exists:
        completed = find_completed_restricted_recovery_marker(
            path=path,
            expected_binding=expected_binding,
            expected_file_identity=expected_file_identity,
        )
        if completed is not None:
            return completed
    source_path = transition_path if transition_exists else path
    marker, parent_fd, marker_fd, errors = _open_trusted_json(source_path)
    if marker is None:
        raise ValueError("untrusted restricted marker: " + ",".join(errors))
    assert parent_fd is not None and marker_fd is not None
    leaf_set = marker.get("initial_leaf_set", [])
    validation_errors = _restricted_marker_validation_errors(
        marker=marker,
        expected_binding=expected_binding,
        expected_leaf_set=leaf_set,
    )
    if validation_errors:
        os.close(marker_fd)
        os.close(parent_fd)
        raise ValueError("restricted marker verification failed")
    completed_name = f"restricted-recovery.completed.{marker['marker_sha256']}.json"
    trusted_info = os.fstat(marker_fd)
    if expected_file_identity is not None and (
        trusted_info.st_dev,
        trusted_info.st_ino,
    ) != expected_file_identity:
        os.close(marker_fd)
        os.close(parent_fd)
        raise ValueError("marker inode changed after ensure")
    try:
        if not transition_exists:
            try:
                os.stat(
                    transition_path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise ValueError("transition marker collision")
            active_info = os.stat(
                path.name, dir_fd=parent_fd, follow_symlinks=False
            )
            if not _same_trusted_marker_object(active_info, trusted_info):
                raise ValueError("marker inode changed before transition")
            _rename_noreplace(
                parent_fd=parent_fd,
                source_name=path.name,
                destination_name=transition_path.name,
            )
            os.fsync(parent_fd)
            moved_info = os.stat(
                transition_path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            if not _same_trusted_marker_object(moved_info, trusted_info):
                try:
                    os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    _rename_noreplace(
                        parent_fd=parent_fd,
                        source_name=transition_path.name,
                        destination_name=path.name,
                    )
                    os.fsync(parent_fd)
                raise ValueError("marker inode changed during transition")

        transition_info = os.stat(
            transition_path.name, dir_fd=parent_fd, follow_symlinks=False
        )
        if not _same_trusted_marker_object(transition_info, trusted_info):
            raise ValueError("transition marker inode changed")
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("active marker appeared during transition")
        try:
            completed_info = os.stat(
                completed_name, dir_fd=parent_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            completed_info = None
        if completed_info is not None:
            raise ValueError("completed marker collision")

        transition_info = os.stat(
            transition_path.name, dir_fd=parent_fd, follow_symlinks=False
        )
        if not _same_trusted_marker_object(transition_info, trusted_info):
            raise ValueError("transition marker inode changed before completion")
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("active marker appeared before completion")
        _rename_noreplace(
            parent_fd=parent_fd,
            source_name=transition_path.name,
            destination_name=completed_name,
        )
        os.fsync(parent_fd)
        completed_info = os.stat(
            completed_name, dir_fd=parent_fd, follow_symlinks=False
        )
        if not _same_trusted_marker_object(completed_info, trusted_info):
            try:
                os.stat(
                    transition_path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                _rename_noreplace(
                    parent_fd=parent_fd,
                    source_name=completed_name,
                    destination_name=transition_path.name,
                )
                os.fsync(parent_fd)
            raise ValueError("marker inode changed during completion")
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("active marker appeared after completion")
        try:
            os.stat(
                transition_path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise ValueError("transition marker remained after completion")
    finally:
        os.close(marker_fd)
        os.close(parent_fd)
    return path.parent / completed_name

"""Small shared 0079 artifact contract, usable by both host and Django.

This module owns no database, Docker, locks or service operations. The existing
release coordinator and one-shot migration owner remain responsible for them.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

SOURCE_LEAF = "stable.0078_externalhorse_profile_snapshot"
TARGET_LEAF = "stable.0079_multisource_race_enrollment"
HANDOFF_SCHEMA = "multisource-release-preflight/v1"
MANIFEST_SCHEMA = "release-0079-verified-backup-recovery/v1"
INTENT_SCHEMA = "release-0079-prepared-intent/v1"
MARKER_SCHEMA = "multisource-release-restricted-recovery/v1"
MIGRATION_CONTRACT_SHA256 = (
    "ecf3a74cb2706dea1ac059473017debc4cdda8f4b82fcc768182003a81b5870a"
)
SERVICES = ("web", "worker", "beat", "race_live_worker", "race_sync_v2_worker", "nginx")
WRITER_FLAGS = (
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
    "RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED",
    "RACE_DATA_MULTISOURCE_APPLY_ENABLED",
    "RACE_DATA_COVERAGE_ALERTS_ENABLED",
    "RACE_DATA_SYNC_PRE_RACE_REFRESH_ENABLED",
    "RACE_DATA_SYNC_JRA_PRE_RACE_ENABLED",
    "HISTORICAL_RACE_BACKFILL_ENABLED",
    "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK",
)
BINDING_FIELDS = (
    "release_0079_recovery_manifest_path",
    "release_0079_recovery_manifest_sha256",
    "release_0079_recovery_origin_handoff_sha256",
    "release_0079_intent_path",
    "release_0079_intent_sha256",
)


def marker_binding(artifact: dict) -> dict:
    if artifact.get("release_0079_recovery_binding_mode") != "bound":
        raise ValueError("0079 DDL marker requires a bound closed-state handoff")
    return {
        **{
            key: artifact[key]
            for key in (
                "candidate_commit",
                "candidate_image_id",
                "database_identity_sha256",
            )
        },
        "artifact_sha256": artifact["release_0079_recovery_origin_handoff_sha256"],
        "origin_action": "release-0079",
        "action": "forward-resume",
        "target_leaf_set": [TARGET_LEAF],
        "migration_contract_sha256": MIGRATION_CONTRACT_SHA256,
        "release_0079_manifest_sha256": artifact[
            "release_0079_recovery_manifest_sha256"
        ],
        "release_0079_intent_sha256": artifact["release_0079_intent_sha256"],
    }


def completed_marker(directory: Path, binding: dict) -> tuple[Path, dict] | None:
    """Find only an exact bound 0079 completion, never the latest receipt."""
    matches = []
    for path in directory.glob("restricted-recovery.completed.*.json"):
        payload, identity = read_json(path)
        if any(payload.get(key) != value for key, value in binding.items()):
            continue
        unsigned = {
            key: value for key, value in payload.items() if key != "marker_sha256"
        }
        if payload.get("schema_version") != MARKER_SCHEMA or digest(
            unsigned
        ) != payload.get("marker_sha256"):
            raise ValueError("0079 completion receipt is invalid")
        if (
            path.name
            != f"restricted-recovery.completed.{payload['marker_sha256']}.json"
        ):
            raise ValueError("0079 completion receipt filename mismatch")
        if payload.get("initial_leaf_set") not in (
            [SOURCE_LEAF],
            [TARGET_LEAF],
        ) or payload.get("target_leaf_set") != [TARGET_LEAF]:
            raise ValueError("0079 completion receipt generation mismatch")
        matches.append((path, identity))
    if len(matches) > 1:
        raise ValueError("multiple 0079 completion receipts")
    if matches and any(
        os.path.lexists(directory / name)
        for name in ("restricted-recovery.json", "restricted-recovery.transition.json")
    ):
        raise ValueError("active marker conflicts with 0079 completion")
    return matches[0] if matches else None


from stable.services.release_0078_recovery import (
    encoded as encoded,
    digest,
    hex_value,
    _parent as _parent,
    file_evidence,
    read_json,
    publish_once as publish_once,
)


def migration_contract() -> str:
    directory = Path(__file__).resolve().parent.parent / "migrations"
    manifest = "".join(
        f"{path.relative_to(directory).as_posix()}:{hashlib.sha256(path.read_bytes()).hexdigest()}\n"
        for path in sorted(directory.rglob("*.py"))
    )
    actual = hashlib.sha256(manifest.encode()).hexdigest()
    if actual != MIGRATION_CONTRACT_SHA256:
        raise ValueError("0079 migration file/content contract drift")
    return actual


def validate_admission_state(payload: dict) -> None:
    """Shared host/container checks for the only two reviewed source states."""
    preflight = payload.get("preflight") or {}
    leaves = preflight.get("migration_leaf_set")
    if leaves not in ([SOURCE_LEAF], [TARGET_LEAF]):
        raise ValueError("0079 handoff has an unsupported source leaf")
    plan = [TARGET_LEAF.split(".", 1)[1]] if leaves == [SOURCE_LEAF] else []
    if preflight.get("ok") is not True or preflight.get("migration_plan") != plan:
        raise ValueError("0079 handoff plan is not exact")
    if preflight.get("database_identity_sha256") != payload.get(
        "database_identity_sha256"
    ):
        raise ValueError("0079 handoff database identity is inconsistent")
    if (payload.get("writer_activity") or {}).get("ok") is not True:
        raise ValueError("0079 handoff has active writers")


def verify_admission(path: Path, sha: str, bindings: dict) -> dict:
    payload, _ = read_json(path)
    unsigned = {
        key: value for key, value in payload.items() if key != "artifact_sha256"
    }
    if (
        not hex_value(sha)
        or payload.get("artifact_sha256") != sha
        or digest(unsigned) != sha
    ):
        raise ValueError("0079 handoff SHA mismatch")
    expected = {
        "schema_version": HANDOFF_SCHEMA,
        "target_leaf_set": [TARGET_LEAF],
        "migration_contract_sha256": migration_contract(),
        **bindings,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("0079 handoff binding mismatch")
    validate_admission_state(payload)
    return payload


def verify_manifest(path: Path, sha: str, bindings: dict) -> dict:
    payload, _ = read_json(path, sha)
    expected = {
        "schema_version": MANIFEST_SCHEMA,
        "target_leaf": TARGET_LEAF,
        "migration_contract_sha256": migration_contract(),
        **bindings,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("0079 backup manifest binding mismatch")
    if (
        path.name != "manifest.json"
        or path.parent.name != payload.get("release_id")
        or path.parent.parent.name != "release-0079-recovery"
    ):
        raise ValueError("0079 backup manifest path is not canonical")
    if not hex_value(payload.get("release_id")) or payload.get(
        "release_id"
    ) != payload.get("origin_handoff_sha256"):
        raise ValueError("0079 release ID is not origin-bound")
    if not hex_value(payload.get("effective_compose_sha256")):
        raise ValueError("0079 effective Compose binding missing")
    source = payload.get("source_leaf")
    if source not in {SOURCE_LEAF, TARGET_LEAF} or payload.get("operation") != (
        "upgrade" if source == SOURCE_LEAF else "same-schema"
    ):
        raise ValueError("0079 backup source/operation mismatch")
    backup = Path(payload.get("backup_path") or "")
    if backup.parent != path.parent / "backup":
        raise ValueError("0079 backup is outside its release directory")
    _, evidence = file_evidence(backup)
    if evidence != payload.get("backup_file") or not evidence["size"]:
        raise ValueError("0079 backup bytes or file identity changed")
    if (
        not hex_value(payload.get("pg_restore_list_sha256"))
        or type(payload.get("pg_restore_list_line_count")) is not int
        or payload["pg_restore_list_line_count"] <= 0
    ):
        raise ValueError("0079 backup TOC proof is invalid")
    return payload


def verify_intent(
    path: Path, sha: str, bindings: dict, *, active_required: bool = True
) -> tuple[dict, dict]:
    payload, identity = read_json(path, sha)
    expected = {"schema_version": INTENT_SCHEMA, **bindings}
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("0079 prepared intent binding mismatch")
    if (
        path.name != "intent.json"
        or path.parent.name != payload.get("release_id")
        or path.parent.parent.name != "release-0079-recovery"
    ):
        raise ValueError("0079 prepared intent path is not canonical")
    manifest = verify_manifest(
        path.parent / "manifest.json",
        payload.get("manifest_sha256", ""),
        {
            key: payload.get(key)
            for key in (
                "release_id",
                "candidate_commit",
                "candidate_image_id",
                "database_identity_sha256",
                "compose_file",
                "origin_handoff_sha256",
            )
        },
    )
    services = payload.get("restore_services")
    if (
        not isinstance(services, dict)
        or set(services) != set(SERVICES)
        or any(type(value) is not bool for value in services.values())
    ):
        raise ValueError("0079 service restore intent is invalid")
    if services != manifest.get("restore_services") or payload.get(
        "config_sha256"
    ) != manifest.get("config_sha256"):
        raise ValueError("0079 restore intent differs from preparation proof")
    if payload.get("source_leaf") != manifest["source_leaf"]:
        raise ValueError("0079 intent source differs from backup")
    if not hex_value(payload.get("initial_lock_sha256")) or not hex_value(
        payload.get("config_sha256")
    ):
        raise ValueError("0079 preparation provenance is invalid")
    if active_required:
        pointer, _ = read_json(path.parent.parent / "active.json")
        if pointer != {
            "release_id": payload["release_id"],
            "intent_path": str(path),
            "intent_file": identity,
        }:
            raise ValueError("0079 active pointer identity mismatch")
    return payload, manifest


def recovery_binding(
    *,
    preflight: dict,
    candidate_commit: str,
    candidate_image_id: str,
    manifest_path: str = "",
    manifest_sha256: str = "",
    origin_handoff_sha256: str = "",
    intent_path: str = "",
    intent_sha256: str = "",
) -> dict:
    values = (
        manifest_path,
        manifest_sha256,
        origin_handoff_sha256,
        intent_path,
        intent_sha256,
    )
    if any(values) and not all(values):
        raise ValueError("0079 recovery binding is incomplete")
    result = dict(zip(BINDING_FIELDS, (value or None for value in values)))
    result["release_0079_recovery_binding_mode"] = (
        "bound" if all(values) else "admission-only"
    )
    if not all(values):
        return result
    intent, manifest = verify_intent(
        Path(intent_path),
        intent_sha256,
        {
            "candidate_commit": candidate_commit,
            "candidate_image_id": candidate_image_id,
            "database_identity_sha256": preflight.get("database_identity_sha256"),
            "origin_handoff_sha256": origin_handoff_sha256,
        },
    )
    if (
        Path(manifest_path) != Path(intent_path).parent / "manifest.json"
        or manifest_sha256 != intent["manifest_sha256"]
    ):
        raise ValueError("0079 handoff manifest differs from prepared intent")
    if preflight.get("migration_leaf_set") not in (
        [manifest["source_leaf"]],
        [TARGET_LEAF],
    ):
        raise ValueError("0079 recovery source leaf drift")
    return result

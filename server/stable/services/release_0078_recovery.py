"""Small shared 0078 artifact contract, usable by both host and Django.

This module owns no database, Docker, locks or service operations. The existing
release coordinator and one-shot migration owner remain responsible for them.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path


SOURCE_LEAF = "stable.0077_racing_api_horse_identity_staging"
TARGET_LEAF = "stable.0078_externalhorse_profile_snapshot"
HANDOFF_SCHEMA = "migration-history-repair-preflight/v5"
MANIFEST_SCHEMA = "release-0078-verified-backup-recovery/v1"
INTENT_SCHEMA = "release-0078-prepared-intent/v1"
MARKER_SCHEMA = "migration-history-repair-restricted-recovery/v3"
MIGRATION_CONTRACT_SHA256 = "50c421f3167a8c2c8f1613a0597ad7ee196c249fc18bf7eed0de7b9cd2f80906"
SERVICES = ("web", "worker", "beat", "race_live_worker", "race_sync_v2_worker", "nginx")
BINDING_FIELDS = (
    "release_0078_recovery_manifest_path", "release_0078_recovery_manifest_sha256",
    "release_0078_recovery_origin_handoff_sha256", "release_0078_intent_path", "release_0078_intent_sha256",
)


def marker_binding(artifact: dict) -> dict:
    if artifact.get("release_0078_recovery_binding_mode") != "bound":
        raise ValueError("0078 DDL marker requires a bound closed-state handoff")
    return {
        **{key: artifact[key] for key in ("candidate_commit", "candidate_image_id", "database_identity_sha256")},
        "artifact_sha256": artifact["release_0078_recovery_origin_handoff_sha256"],
        "origin_action": "release-0078", "action": "forward-resume",
        "target_leaf_set": [TARGET_LEAF], "migration_contract_sha256": MIGRATION_CONTRACT_SHA256,
        "release_0078_manifest_sha256": artifact["release_0078_recovery_manifest_sha256"],
        "release_0078_intent_sha256": artifact["release_0078_intent_sha256"],
    }


def completed_marker(directory: Path, binding: dict) -> tuple[Path, dict] | None:
    """Find only an exact bound 0078 completion, never the latest receipt."""
    matches = []
    for path in directory.glob("restricted-recovery.completed.*.json"):
        payload, identity = read_json(path)
        if any(payload.get(key) != value for key, value in binding.items()):
            continue
        unsigned = {key: value for key, value in payload.items() if key != "marker_sha256"}
        if payload.get("schema_version") != MARKER_SCHEMA or digest(unsigned) != payload.get("marker_sha256"):
            raise ValueError("0078 completion receipt is invalid")
        if path.name != f"restricted-recovery.completed.{payload['marker_sha256']}.json":
            raise ValueError("0078 completion receipt filename mismatch")
        if payload.get("initial_leaf_set") not in ([SOURCE_LEAF], [TARGET_LEAF]) or payload.get("target_leaf_set") != [TARGET_LEAF]:
            raise ValueError("0078 completion receipt generation mismatch")
        matches.append((path, identity))
    if len(matches) > 1:
        raise ValueError("multiple 0078 completion receipts")
    if matches and any(os.path.lexists(directory / name) for name in ("restricted-recovery.json", "restricted-recovery.transition.json")):
        raise ValueError("active marker conflicts with 0078 completion")
    return matches[0] if matches else None


def encoded(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(payload: dict) -> str:
    return hashlib.sha256(encoded(payload)).hexdigest()


def hex_value(value: object, size: int = 64) -> bool:
    return isinstance(value, str) and len(value) == size and all(c in "0123456789abcdef" for c in value)


def migration_contract() -> str:
    directory = Path(__file__).resolve().parent.parent / "migrations"
    manifest = "".join(
        f"{path.relative_to(directory).as_posix()}:{hashlib.sha256(path.read_bytes()).hexdigest()}\n"
        for path in sorted(directory.rglob("*.py"))
    )
    actual = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    if actual != MIGRATION_CONTRACT_SHA256:
        raise ValueError("0078 migration file/content contract drift")
    return actual


def _parent(path: Path) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("artifact path must be absolute and normalized")
    # Walk by directory descriptor: checking symlinks then opening an absolute
    # path leaves a redirect window. Only the owner/root may replace ancestors;
    # the root-owned sticky /tmp boundary is also safe for owner-only children.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if info.st_uid not in {0, os.getuid()} or (info.st_mode & 0o022 and not sticky_root):
                raise ValueError("artifact ancestor is writable by another user")
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("artifact parent must be user-owned mode 0700")
    except BaseException:
        os.close(fd)
        raise
    return fd


def file_evidence(path: Path, *, json_file: bool = False) -> tuple[bytes, dict]:
    """Hash the opened object, not a later lookup of its pathname."""
    parent_fd = _parent(path)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("artifact must be a user-owned mode-0600 regular file")
            if json_file and info.st_size > 1024 * 1024:
                raise ValueError("artifact JSON exceeds size limit")
            sha = hashlib.sha256()
            chunks = []
            while chunk := os.read(fd, 1024 * 1024):
                sha.update(chunk)
                if json_file:
                    chunks.append(chunk)
            after = os.fstat(fd)
            named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or identity != (named.st_dev, named.st_ino, named.st_size, named.st_mtime_ns):
                raise ValueError("artifact changed while being read")
            return b"".join(chunks), {
                "sha256": sha.hexdigest(), "size": info.st_size,
                "device": info.st_dev, "inode": info.st_ino,
            }
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def read_json(path: Path, expected_sha: str = "") -> tuple[dict, dict]:
    raw, evidence = file_evidence(path, json_file=True)
    if expected_sha and (not hex_value(expected_sha) or evidence["sha256"] != expected_sha):
        raise ValueError("artifact SHA-256 mismatch")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("artifact JSON must be an object")
    return payload, evidence


def publish_once(path: Path, payload: dict) -> dict:
    """Atomic, no-clobber publication; an identical retry keeps the inode."""
    expected = encoded(payload)
    if os.path.lexists(path):
        _, evidence = read_json(path, hashlib.sha256(expected).hexdigest())
        return evidence
    parent_fd = _parent(path)
    tmp_name = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".0078-", dir=path.parent)
        tmp_name = Path(tmp).name
        with os.fdopen(fd, "wb") as stream:
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp_name, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
        os.fsync(parent_fd)
    finally:
        if tmp_name is not None:
            os.unlink(tmp_name, dir_fd=parent_fd)
        os.close(parent_fd)
    return read_json(path, hashlib.sha256(expected).hexdigest())[1]


def validate_admission_state(payload: dict) -> None:
    """Shared host/container checks for the only two reviewed source states."""
    preflight = payload.get("preflight") or {}
    leaves = preflight.get("migration_leaf_set")
    if leaves not in ([SOURCE_LEAF], [TARGET_LEAF]):
        raise ValueError("0078 handoff has an unsupported source leaf")
    plan = [TARGET_LEAF.split(".", 1)[1]] if leaves == [SOURCE_LEAF] else []
    if preflight.get("ok") is not True or preflight.get("migration_plan") != plan:
        raise ValueError("0078 handoff plan is not exact")
    if preflight.get("database_identity_sha256") != payload.get("database_identity_sha256"):
        raise ValueError("0078 handoff database identity is inconsistent")
    if (payload.get("writer_activity") or {}).get("ok") is not True:
        raise ValueError("0078 handoff has active writers")


def verify_admission(path: Path, sha: str, bindings: dict) -> dict:
    payload, _ = read_json(path)
    unsigned = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    if not hex_value(sha) or payload.get("artifact_sha256") != sha or digest(unsigned) != sha:
        raise ValueError("0078 handoff SHA mismatch")
    expected = {
        "schema_version": HANDOFF_SCHEMA, "target_leaf_set": [TARGET_LEAF],
        "migration_contract_sha256": migration_contract(), **bindings,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("0078 handoff binding mismatch")
    validate_admission_state(payload)
    return payload


def verify_manifest(path: Path, sha: str, bindings: dict) -> dict:
    payload, _ = read_json(path, sha)
    expected = {
        "schema_version": MANIFEST_SCHEMA, "target_leaf": TARGET_LEAF,
        "migration_contract_sha256": migration_contract(), **bindings,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("0078 backup manifest binding mismatch")
    if path.name != "manifest.json" or path.parent.name != payload.get("release_id") or path.parent.parent.name != "release-0078-recovery":
        raise ValueError("0078 backup manifest path is not canonical")
    if not hex_value(payload.get("release_id")) or payload.get("release_id") != payload.get("origin_handoff_sha256"):
        raise ValueError("0078 release ID is not origin-bound")
    source = payload.get("source_leaf")
    if source not in {SOURCE_LEAF, TARGET_LEAF} or payload.get("operation") != ("upgrade" if source == SOURCE_LEAF else "same-schema"):
        raise ValueError("0078 backup source/operation mismatch")
    backup = Path(payload.get("backup_path") or "")
    if backup.parent != path.parent / "backup":
        raise ValueError("0078 backup is outside its release directory")
    _, evidence = file_evidence(backup)
    if evidence != payload.get("backup_file") or not evidence["size"]:
        raise ValueError("0078 backup bytes or file identity changed")
    if not hex_value(payload.get("pg_restore_list_sha256")) or type(payload.get("pg_restore_list_line_count")) is not int or payload["pg_restore_list_line_count"] <= 0:
        raise ValueError("0078 backup TOC proof is invalid")
    return payload


def verify_intent(path: Path, sha: str, bindings: dict, *, active_required: bool = True) -> tuple[dict, dict]:
    payload, identity = read_json(path, sha)
    expected = {"schema_version": INTENT_SCHEMA, **bindings}
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("0078 prepared intent binding mismatch")
    if path.name != "intent.json" or path.parent.name != payload.get("release_id") or path.parent.parent.name != "release-0078-recovery":
        raise ValueError("0078 prepared intent path is not canonical")
    manifest = verify_manifest(
        path.parent / "manifest.json", payload.get("manifest_sha256", ""),
        {key: payload.get(key) for key in (
            "release_id", "candidate_commit", "candidate_image_id", "database_identity_sha256",
            "compose_file", "origin_handoff_sha256",
        )},
    )
    services = payload.get("restore_services")
    if not isinstance(services, dict) or set(services) != set(SERVICES) or any(type(value) is not bool for value in services.values()):
        raise ValueError("0078 service restore intent is invalid")
    if services != manifest.get("restore_services") or payload.get("config_sha256") != manifest.get("config_sha256"):
        raise ValueError("0078 restore intent differs from preparation proof")
    if payload.get("source_leaf") != manifest["source_leaf"]:
        raise ValueError("0078 intent source differs from backup")
    if not hex_value(payload.get("initial_lock_sha256")) or not hex_value(payload.get("config_sha256")):
        raise ValueError("0078 preparation provenance is invalid")
    if active_required:
        pointer, _ = read_json(path.parent.parent / "active.json")
        if pointer != {"release_id": payload["release_id"], "intent_path": str(path), "intent_file": identity}:
            raise ValueError("0078 active pointer identity mismatch")
    return payload, manifest


def recovery_binding(*, preflight: dict, candidate_commit: str, candidate_image_id: str,
                     manifest_path: str = "", manifest_sha256: str = "",
                     origin_handoff_sha256: str = "", intent_path: str = "", intent_sha256: str = "") -> dict:
    values = (manifest_path, manifest_sha256, origin_handoff_sha256, intent_path, intent_sha256)
    if any(values) and not all(values):
        raise ValueError("0078 recovery binding is incomplete")
    result = dict(zip(BINDING_FIELDS, (value or None for value in values)))
    result["release_0078_recovery_binding_mode"] = "bound" if all(values) else "admission-only"
    if not all(values):
        return result
    intent, manifest = verify_intent(Path(intent_path), intent_sha256, {
        "candidate_commit": candidate_commit, "candidate_image_id": candidate_image_id,
        "database_identity_sha256": preflight.get("database_identity_sha256"),
        "origin_handoff_sha256": origin_handoff_sha256,
    })
    if Path(manifest_path) != Path(intent_path).parent / "manifest.json" or manifest_sha256 != intent["manifest_sha256"]:
        raise ValueError("0078 handoff manifest differs from prepared intent")
    if preflight.get("migration_leaf_set") not in ([manifest["source_leaf"]], [TARGET_LEAF]):
        raise ValueError("0078 recovery source leaf drift")
    return result

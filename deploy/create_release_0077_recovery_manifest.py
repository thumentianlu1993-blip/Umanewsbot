#!/usr/bin/env python3
"""Create one no-clobber recovery manifest for the forward-only 0077 release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "release-0077-verified-backup-recovery/v1"
SOURCE_LEAF = "stable.0075_race_data_source_priority_and_reported_position"


def _lower_hex(value: str, *, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_regular(path: Path, *, mode: int, label: str) -> os.stat_result:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError(f"{label} must be a user-owned regular file")
    if stat.S_IMODE(info.st_mode) != mode:
        raise ValueError(f"{label} mode must be {mode:04o}")
    return info


def _trusted_parent(path: Path) -> int:
    if path.parent.is_symlink():
        raise ValueError("manifest parent must not be a symlink")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        parent_fd = os.open(path.parent, flags)
    except OSError as exc:
        raise ValueError("manifest parent is unavailable") from exc
    info = os.fstat(parent_fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        os.close(parent_fd)
        raise ValueError("manifest parent must be a user-owned mode-0700 directory")
    return parent_fd


def _publish(path: Path, payload: dict[str, object]) -> str:
    parent_fd = _trusted_parent(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    try:
        fd = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
        try:
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError("short manifest write")
                remaining = remaining[written:]
            os.fsync(fd)
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise ValueError("published manifest trust check failed")
        finally:
            os.close(fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return hashlib.sha256(encoded).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--candidate-image-id", required=True)
    parser.add_argument("--database-identity-sha256", required=True)
    parser.add_argument("--origin-handoff-sha256", required=True)
    parser.add_argument("--backup-path", required=True)
    parser.add_argument("--backup-sha256", required=True)
    parser.add_argument("--pg-restore-container-id", default="")
    parser.add_argument("--source-leaf", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    output = Path(args.output_path)
    backup = Path(args.backup_path)
    if not output.is_absolute() or output.name != f"{args.candidate_commit}.json":
        raise ValueError("manifest output path is not candidate-bound")
    if output.parent.name != "release-0077-recovery":
        raise ValueError("manifest output path is not canonical")
    if os.path.lexists(output):
        raise ValueError("manifest output already exists")
    if not _lower_hex(args.candidate_commit, length=40):
        raise ValueError("candidate commit must be a lowercase 40-character OID")
    if not args.candidate_image_id.startswith("sha256:") or not _lower_hex(
        args.candidate_image_id.removeprefix("sha256:"), length=64
    ):
        raise ValueError("candidate image ID must be an exact sha256 digest")
    for label, value in (
        ("database identity", args.database_identity_sha256),
        ("origin handoff", args.origin_handoff_sha256),
        ("backup", args.backup_sha256),
    ):
        if not _lower_hex(value, length=64):
            raise ValueError(f"{label} SHA-256 is invalid")
    if args.source_leaf != SOURCE_LEAF:
        raise ValueError("0077 recovery source leaf must be exact 0075")
    if not backup.is_absolute():
        raise ValueError("backup path must be absolute")
    backup_info = _trusted_regular(backup, mode=0o600, label="backup")
    actual_backup_sha256 = _sha256_file(backup)
    if actual_backup_sha256 != args.backup_sha256:
        raise ValueError("backup SHA-256 mismatch")
    restore_command = ["pg_restore", "--list", str(backup)]
    restore_stdin = subprocess.DEVNULL
    backup_stream = None
    if args.pg_restore_container_id:
        if not all(
            character.isalnum() or character in "_.-"
            for character in args.pg_restore_container_id
        ) or len(args.pg_restore_container_id) > 128:
            raise ValueError("pg_restore container ID is invalid")
        restore_command = [
            "docker",
            "exec",
            "-i",
            args.pg_restore_container_id,
            "pg_restore",
            "--list",
        ]
        backup_stream = backup.open("rb")
        restore_stdin = backup_stream
    try:
        restore_list = subprocess.run(
            restore_command,
            stdin=restore_stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("pg_restore --list validation failed") from exc
    finally:
        if backup_stream is not None:
            backup_stream.close()
    if not restore_list.strip():
        raise ValueError("pg_restore --list returned an empty catalog")
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "candidate_commit": args.candidate_commit,
        "candidate_image_id": args.candidate_image_id,
        "database_identity_sha256": args.database_identity_sha256,
        "origin_handoff_sha256": args.origin_handoff_sha256,
        "source_leaf": args.source_leaf,
        "backup_path": str(backup),
        "backup_sha256": actual_backup_sha256,
        "backup_size_bytes": backup_info.st_size,
        "pg_restore_list_sha256": hashlib.sha256(restore_list).hexdigest(),
        "pg_restore_list_line_count": len(restore_list.splitlines()),
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    manifest_sha256 = _publish(output, payload)
    print(
        json.dumps(
            {"manifest_path": str(output), "manifest_sha256": manifest_sha256},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

#!/usr/bin/env python3
"""Create and idempotently complete a content-bound rollback control state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path


def canonical_bytes(payload: dict) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "state_sha256"}
    return json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def trusted_digest(path: Path, *, expected_mode: int) -> str:
    parent_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        parent_flags |= os.O_NOFOLLOW
    parent_fd = os.open(path.parent, parent_flags)
    try:
        parent_info = os.fstat(parent_fd)
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != os.getuid()
            or stat.S_IMODE(parent_info.st_mode) != 0o700
        ):
            raise ValueError(f"untrusted control parent: {path.parent}")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path.name, flags, dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != expected_mode
            ):
                raise ValueError(f"untrusted control file: {path}")
            digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            after = os.fstat(fd)
            if (info.st_dev, info.st_ino, info.st_size) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
            ):
                raise ValueError(f"control file changed during read: {path}")
            return digest.hexdigest()
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def create_main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-path", required=True)
    parser.add_argument("--compose-file", required=True)
    parser.add_argument("--control-dir", required=True)
    parser.add_argument("--control-image-id", required=True)
    parser.add_argument("--control-override", required=True)
    parser.add_argument("--initiating-artifact-path", required=True)
    parser.add_argument("--initiating-artifact-sha256", required=True)
    parser.add_argument("--initiating-database-identity-sha256", required=True)
    parser.add_argument("--initiating-lock-token-sha256", required=True)
    parser.add_argument("--recovery-intent-mode", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--target-image-id", required=True)
    parser.add_argument("--target-image-tag", required=True)
    args = parser.parse_args(argv)

    state_path = Path(args.state_path)
    control_dir = Path(args.control_dir)
    directory_info = control_dir.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(directory_info.st_mode)
        or directory_info.st_uid != os.getuid()
        or stat.S_IMODE(directory_info.st_mode) != 0o700
    ):
        raise ValueError("untrusted rollback control directory")
    files = {
        "application_release": (control_dir / "application-release.sh", 0o500),
        "control_state_creator": (control_dir / "create-control-state.py", 0o500),
        "control_state_verifier": (control_dir / "verify-control-state.py", 0o500),
        "preflight": (control_dir / "preflight.sh", 0o500),
        "release_tasks": (control_dir / "release-tasks.sh", 0o500),
        "resume_rollback": (control_dir / "resume-rollback-release.sh", 0o500),
        "compose_override": (Path(args.control_override), 0o400),
    }
    control_files = {
        name: {
            "mode": format(mode, "04o"),
            "path": str(path),
            "sha256": trusted_digest(path, expected_mode=mode),
        }
        for name, (path, mode) in files.items()
    }
    payload = {
        "schema_version": "rollback-control-state/v1",
        "compose_file": args.compose_file,
        "control_dir": str(control_dir),
        "control_files": control_files,
        "control_image_id": args.control_image_id,
        "control_override": args.control_override,
        "initiating_artifact_path": args.initiating_artifact_path,
        "initiating_artifact_sha256": args.initiating_artifact_sha256,
        "initiating_database_identity_sha256": args.initiating_database_identity_sha256,
        "initiating_lock_token_sha256": args.initiating_lock_token_sha256,
        "recovery_intent_mode": args.recovery_intent_mode,
        "target_commit": args.target_commit,
        "target_image_id": args.target_image_id,
        "target_image_tag": args.target_image_tag,
    }
    payload["state_sha256"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"

    parent_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        parent_flags |= os.O_NOFOLLOW
    parent_fd = os.open(state_path.parent, parent_flags)
    try:
        parent_info = os.fstat(parent_fd)
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != os.getuid()
            or stat.S_IMODE(parent_info.st_mode) != 0o700
        ):
            raise ValueError("untrusted rollback state parent")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(state_path.name, flags, 0o600, dir_fd=parent_fd)
        try:
            view = memoryview(encoded)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write publishing rollback control state")
                view = view[written:]
            os.fsync(fd)
        except Exception:
            try:
                os.unlink(state_path.name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    print(payload["state_sha256"])


def complete_main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-path", required=True)
    parser.add_argument("--completed-path", required=True)
    parser.add_argument("--expected-state-sha256", required=True)
    args = parser.parse_args(argv)
    state_path = Path(args.state_path)
    completed_path = Path(args.completed_path)
    if state_path.parent != completed_path.parent:
        raise ValueError("rollback state completion must stay in one directory")

    parent_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        parent_flags |= os.O_NOFOLLOW
    parent_fd = os.open(state_path.parent, parent_flags)
    try:
        parent_info = os.fstat(parent_fd)
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != os.getuid()
            or stat.S_IMODE(parent_info.st_mode) != 0o700
        ):
            raise ValueError("untrusted rollback state parent")

        def read_state(name: str) -> tuple[bytes, os.stat_result]:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(name, flags, dir_fd=parent_fd)
            try:
                before = os.fstat(fd)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != os.getuid()
                    or stat.S_IMODE(before.st_mode) != 0o600
                ):
                    raise ValueError("untrusted rollback control receipt")
                chunks = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(fd)
                if (before.st_dev, before.st_ino, before.st_size) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                ):
                    raise ValueError("rollback control receipt changed during read")
                raw = b"".join(chunks)
                payload = json.loads(raw.decode("utf-8"))
                actual = hashlib.sha256(canonical_bytes(payload)).hexdigest()
                if (
                    payload.get("state_sha256") != actual
                    or actual != args.expected_state_sha256
                ):
                    raise ValueError("rollback control receipt SHA mismatch")
                return raw, before
            finally:
                os.close(fd)

        active_exists = os.path.lexists(state_path)
        completed_exists = os.path.lexists(completed_path)
        if completed_exists:
            completed_raw, completed_info = read_state(completed_path.name)
            if not active_exists:
                print("already-completed")
                return
            active_raw, active_info = read_state(state_path.name)
            if (
                active_raw != completed_raw
                or (active_info.st_dev, active_info.st_ino)
                != (completed_info.st_dev, completed_info.st_ino)
            ):
                raise FileExistsError("completed rollback control receipt collision")
            os.unlink(state_path.name, dir_fd=parent_fd)
            os.fsync(parent_fd)
            print("completed")
            return
        if not active_exists:
            raise FileNotFoundError("active rollback control state is missing")
        _active_raw, active_info = read_state(state_path.name)
        os.link(
            state_path.name,
            completed_path.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        os.fsync(parent_fd)
        _completed_raw, completed_info = read_state(completed_path.name)
        if (active_info.st_dev, active_info.st_ino) != (
            completed_info.st_dev,
            completed_info.st_ino,
        ):
            raise ValueError("completed rollback control receipt identity mismatch")
        os.unlink(state_path.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        print("completed")
    finally:
        os.close(parent_fd)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "complete":
        complete_main(sys.argv[2:])
    else:
        create_main(sys.argv[1:])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verify a rollback control receipt and its complete pinned file catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path


def _trusted_read(path: Path, expected_mode: int) -> bytes:
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
            raise ValueError("untrusted rollback control parent")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path.name, flags, dir_fd=parent_fd)
        try:
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != expected_mode
            ):
                raise ValueError("untrusted rollback control file")
            chunks: list[bytes] = []
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
                raise ValueError("rollback control file changed during read")
            return b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} is malformed")
    return value


def verify(args: argparse.Namespace) -> dict:
    state_path = Path(args.state_path).absolute()
    marker_root = state_path.parent
    raw_state = _trusted_read(state_path, 0o600)
    state = json.loads(raw_state.decode("utf-8"))
    if not isinstance(state, dict):
        raise ValueError("rollback control state must be an object")
    unsigned = {key: value for key, value in state.items() if key != "state_sha256"}
    canonical = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    state_sha256 = _digest(state.get("state_sha256"), "rollback control state SHA")
    if state_sha256 != hashlib.sha256(canonical).hexdigest():
        raise ValueError("rollback control state SHA mismatch")
    if args.expected_state_sha256 and state_sha256 != args.expected_state_sha256:
        raise ValueError("rollback control state attempt identity mismatch")
    if state.get("schema_version") != "rollback-control-state/v1":
        raise ValueError("rollback control state schema mismatch")
    if (
        state.get("compose_file") != args.compose_file
        or state.get("target_commit") != args.target_commit
        or state.get("target_image_id") != args.target_image_id
        or state.get("initiating_artifact_sha256") != args.artifact_sha256
    ):
        raise ValueError("rollback control state binding mismatch")

    mode = state.get("recovery_intent_mode")
    if mode not in {"required", "not-required"}:
        raise ValueError("rollback control state recovery mode mismatch")
    if args.recovery_intent_mode and mode != args.recovery_intent_mode:
        raise ValueError("rollback control state recovery mode mismatch")

    control_dir_value = state.get("control_dir")
    if not isinstance(control_dir_value, str) or "\n" in control_dir_value:
        raise ValueError("rollback control directory binding mismatch")
    control_dir = Path(control_dir_value).absolute()
    try:
        relative_control_dir = control_dir.relative_to(marker_root)
    except ValueError as error:
        raise ValueError("rollback control directory is outside repair runtime") from error
    if len(relative_control_dir.parts) != 1 or not relative_control_dir.name.startswith(
        "rollback-control."
    ):
        raise ValueError("rollback control directory is outside repair runtime")
    directory_info = control_dir.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(directory_info.st_mode)
        or directory_info.st_uid != os.getuid()
        or stat.S_IMODE(directory_info.st_mode) != 0o700
    ):
        raise ValueError("untrusted rollback control directory")

    expected = {
        "application_release": (control_dir / "application-release.sh", 0o500),
        "control_state_creator": (control_dir / "create-control-state.py", 0o500),
        "control_state_verifier": (control_dir / "verify-control-state.py", 0o500),
        "preflight": (control_dir / "preflight.sh", 0o500),
        "release_tasks": (control_dir / "release-tasks.sh", 0o500),
        "resume_rollback": (control_dir / "resume-rollback-release.sh", 0o500),
        "compose_override": (control_dir / "compose-control.yml", 0o400),
    }
    control_files = state.get("control_files")
    if not isinstance(control_files, dict) or set(control_files) != set(expected):
        raise ValueError("rollback control file catalog mismatch")
    for name, (path, expected_mode) in expected.items():
        binding = control_files.get(name)
        if (
            not isinstance(binding, dict)
            or binding.get("path") != str(path)
            or binding.get("mode") != format(expected_mode, "04o")
        ):
            raise ValueError("rollback control file binding mismatch")
        if binding.get("sha256") != hashlib.sha256(
            _trusted_read(path, expected_mode)
        ).hexdigest():
            raise ValueError("rollback control file SHA mismatch")

    override = str(expected["compose_override"][0])
    if state.get("control_override") != override:
        raise ValueError("rollback control override binding mismatch")
    target_tag = state.get("target_image_tag")
    if (
        not isinstance(target_tag, str)
        or not target_tag.startswith("umanewsbot:rollback-target-")
        or "\n" in target_tag
    ):
        raise ValueError("rollback target tag is invalid")
    control_image_id = state.get("control_image_id")
    if not isinstance(control_image_id, str) or not control_image_id.startswith("sha256:"):
        raise ValueError("rollback control image id is invalid")
    artifact_path = state.get("initiating_artifact_path")
    if not isinstance(artifact_path, str) or "\n" in artifact_path:
        raise ValueError("initiating rollback artifact path is invalid")
    artifact = Path(artifact_path).absolute()
    try:
        relative_artifact = artifact.relative_to(marker_root / "preflight")
    except ValueError as error:
        raise ValueError("initiating rollback artifact path is invalid") from error
    if len(relative_artifact.parts) != 2 or relative_artifact.name != "preflight.json":
        raise ValueError("initiating rollback artifact path is invalid")

    return {
        "state_sha256": state_sha256,
        "control_dir": str(control_dir),
        "resume_path": str(expected["resume_rollback"][0]),
        "recovery_intent_mode": mode,
        "control_image_id": control_image_id,
        "control_override": override,
        "target_image_tag": target_tag,
        "initiating_artifact_path": str(artifact),
        "initiating_database_identity_sha256": _digest(
            state.get("initiating_database_identity_sha256"),
            "rollback database identity SHA",
        ),
        "initiating_lock_token_sha256": _digest(
            state.get("initiating_lock_token_sha256"), "rollback lock token SHA"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-path", required=True)
    parser.add_argument("--compose-file", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--target-image-id", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--expected-state-sha256")
    parser.add_argument("--recovery-intent-mode")
    args = parser.parse_args()
    _digest(args.artifact_sha256, "rollback artifact SHA")
    if args.expected_state_sha256:
        _digest(args.expected_state_sha256, "expected rollback state SHA")
    result = verify(args)
    for key in (
        "state_sha256",
        "control_dir",
        "resume_path",
        "recovery_intent_mode",
        "control_image_id",
        "control_override",
        "target_image_tag",
        "initiating_artifact_path",
        "initiating_database_identity_sha256",
        "initiating_lock_token_sha256",
    ):
        print(result[key])


if __name__ == "__main__":
    main()

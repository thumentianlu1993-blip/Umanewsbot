#!/usr/bin/env python3
"""Create a deterministic, read-only identity for the current Git review target."""

from __future__ import annotations

import base64
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
from typing import Any


CHUNK_SIZE = 1024 * 1024


class FingerprintError(RuntimeError):
    """The review target could not be fingerprinted safely."""


def git(*args: str, cwd: Path) -> bytes:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise FingerprintError(
            f"git {' '.join(args)} failed with exit {exc.returncode}: {detail}"
        ) from exc


def git_input(*args: str, cwd: Path, input_bytes: bytes) -> bytes:
    """Run a plumbing command with stdin without allowing optional Git locks."""
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            env=environment,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise FingerprintError(
            f"git {' '.join(args)} failed with exit {exc.returncode}: {detail}"
        ) from exc


def reject_external_clean_filters(root: Path) -> None:
    """Reject Git-visible paths with a configured clean-filter attribute."""
    raw_paths = git(
        "ls-files", "-z", "--cached", "--others", "--exclude-standard", cwd=root
    )
    paths = [path for path in raw_paths.split(b"\0") if path]
    if not paths:
        return
    attributes = git_input(
        "check-attr",
        "-z",
        "--stdin",
        "filter",
        cwd=root,
        input_bytes=b"\0".join(paths) + b"\0",
    )
    fields = attributes.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) != len(paths) * 3:
        raise FingerprintError("git check-attr returned malformed filter records")
    for raw_path, attribute, value in zip(fields[0::3], fields[1::3], fields[2::3]):
        if attribute != b"filter":
            raise FingerprintError("git check-attr returned an unexpected attribute")
        if value not in {b"unspecified", b"unset"}:
            relative = safe_relative_path(raw_path)
            rendered = value.decode("utf-8", errors="replace")
            raise FingerprintError(
                f"external Git clean filter is not allowed for {relative!r}: {rendered}"
            )


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        stat.S_IMODE(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def safe_relative_path(raw_path: bytes) -> str:
    path = os.fsdecode(raw_path)
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise FingerprintError(f"unsafe untracked path from git status: {path!r}")
    return path


def status_records(raw_status: bytes) -> list[bytes]:
    return [record for record in raw_status.split(b"\0") if record]


def untracked_leaves(raw_status: bytes) -> list[str]:
    leaves = []
    for record in status_records(raw_status):
        if record.startswith(b"? "):
            raw_path = record[2:]
            path = safe_relative_path(raw_path)
            if raw_path.endswith(b"/"):
                raise FingerprintError(
                    f"untracked directory leaf {path!r} cannot be reviewed safely; "
                    "explicitly add it to the review scope, move it out, or review it separately"
                )
            leaves.append(path)
    return sorted(set(leaves), key=os.fsencode)


def manifest_paths(leaves: list[str]) -> list[str]:
    paths: set[str] = set()
    for leaf in leaves:
        pure = PurePosixPath(leaf)
        parts = pure.parts
        for end in range(1, len(parts) + 1):
            paths.add(PurePosixPath(*parts[:end]).as_posix())
    return sorted(paths, key=os.fsencode)


def mode_text(value: os.stat_result) -> str:
    return f"{stat.S_IMODE(value.st_mode):04o}"


def regular_digest(path: Path, before: os.stat_result) -> str:
    if not hasattr(os, "O_NOFOLLOW"):
        raise FingerprintError("O_NOFOLLOW is required for a safe snapshot")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise FingerprintError(f"cannot safely open regular file {os.fspath(path)!r}: {exc}") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or identity(opened) != identity(before):
            raise FingerprintError(f"path changed while opening: {os.fspath(path)!r}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
        if identity(os.fstat(fd)) != identity(before):
            raise FingerprintError(f"path changed while hashing: {os.fspath(path)!r}")
        return digest.hexdigest()
    finally:
        os.close(fd)


def regular_bytes(path: Path, before: os.stat_result) -> bytes:
    """Read a regular file without following links and fence its identity."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise FingerprintError("O_NOFOLLOW is required for a safe snapshot")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise FingerprintError(f"cannot safely open regular file {os.fspath(path)!r}: {exc}") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or identity(opened) != identity(before):
            raise FingerprintError(f"path changed while opening: {os.fspath(path)!r}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
        if identity(os.fstat(fd)) != identity(before):
            raise FingerprintError(f"path changed while hashing: {os.fspath(path)!r}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def content_manifest(root: Path, raw_status: bytes) -> list[dict[str, str]]:
    """Describe every current Git-visible leaf using Git tree semantics."""
    summary = summarize_status(raw_status)
    if summary["conflict_count"]:
        raise FingerprintError("conflicted index/worktree cannot be fingerprinted")
    tracked_raw = git("ls-files", "-z", "--cached", cwd=root)
    tracked = {safe_relative_path(path) for path in tracked_raw.split(b"\0") if path}
    paths = sorted(tracked | set(untracked_leaves(raw_status)), key=os.fsencode)
    manifest: list[dict[str, str]] = []
    for relative in paths:
        path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            before = os.lstat(path)
        except FileNotFoundError:
            # A deleted tracked file is not present in the candidate tree.
            continue
        except OSError as exc:
            raise FingerprintError(f"cannot lstat content leaf {relative!r}: {exc}") from exc
        if stat.S_ISREG(before.st_mode):
            content = regular_bytes(path, before)
            mode = "100755" if stat.S_IMODE(before.st_mode) & 0o111 else "100644"
            oid_raw = git_input(
                "hash-object", "--no-filters", "--stdin", cwd=root, input_bytes=content
            )
        elif stat.S_ISLNK(before.st_mode):
            try:
                target = os.readlink(path)
            except OSError as exc:
                raise FingerprintError(f"cannot read symlink {relative!r}: {exc}") from exc
            content = os.fsencode(target)
            mode = "120000"
            oid_raw = git_input(
                "hash-object", "--no-filters", "--stdin", cwd=root, input_bytes=content
            )
        else:
            raise FingerprintError(
                f"unsupported Git-visible file type for content leaf: {relative!r}"
            )
        try:
            after = os.lstat(path)
        except OSError as exc:
            raise FingerprintError(f"cannot re-lstat content leaf {relative!r}: {exc}") from exc
        if identity(after) != identity(before):
            raise FingerprintError(f"content leaf changed during snapshot: {relative!r}")
        oid = oid_raw.decode("ascii").strip()
        if not oid or any(character not in "0123456789abcdef" for character in oid):
            raise FingerprintError(f"git hash-object returned an invalid object id: {relative!r}")
        manifest.append({"blob_oid": oid, "mode": mode, "path": relative, "type": "blob"})
    return manifest


def snapshot_path(root: Path, relative: str) -> dict[str, str]:
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise FingerprintError(f"cannot lstat {relative!r}: {exc}") from exc

    entry = {"path": relative, "mode": mode_text(before)}
    if stat.S_ISREG(before.st_mode):
        entry.update(type="regular", sha256=regular_digest(path, before))
    elif stat.S_ISLNK(before.st_mode):
        try:
            target = os.readlink(path)
        except OSError as exc:
            raise FingerprintError(f"cannot read symlink {relative!r}: {exc}") from exc
        entry.update(type="symlink", target=target)
    elif stat.S_ISDIR(before.st_mode):
        entry.update(type="directory")
    else:
        raise FingerprintError(f"unsupported file type for untracked path: {relative!r}")

    try:
        after = os.lstat(path)
    except OSError as exc:
        raise FingerprintError(f"cannot re-lstat {relative!r}: {exc}") from exc
    if identity(after) != identity(before):
        raise FingerprintError(f"path changed during snapshot: {relative!r}")
    return entry


def snapshot_manifest(root: Path, leaves: list[str]) -> list[dict[str, str]]:
    """Snapshot every leaf and ancestor against one repository-wide identity fence."""
    paths = manifest_paths(leaves)
    identities: dict[str, tuple[int, int, int, int, int, int, int]] = {}
    for relative in paths:
        try:
            identities[relative] = identity(
                os.lstat(root.joinpath(*PurePosixPath(relative).parts))
            )
        except OSError as exc:
            raise FingerprintError(f"cannot pre-lstat {relative!r}: {exc}") from exc

    manifest: list[dict[str, str]] = []
    for relative in paths:
        entry = snapshot_path(root, relative)
        try:
            after = os.lstat(root.joinpath(*PurePosixPath(relative).parts))
        except OSError as exc:
            raise FingerprintError(f"cannot verify {relative!r}: {exc}") from exc
        if identity(after) != identities[relative]:
            raise FingerprintError(
                f"untracked manifest changed during complete snapshot: {relative!r}"
            )
        manifest.append(entry)
    return manifest


def summarize_status(raw_status: bytes) -> dict[str, Any]:
    branch_headers: list[str] = []
    tracked_count = 0
    staged_count = 0
    unstaged_count = 0
    conflict_count = 0
    untracked_count = 0
    records = status_records(raw_status)
    index = 0
    while index < len(records):
        record = records[index]
        if record.startswith(b"# "):
            branch_headers.append(record.decode("utf-8", errors="surrogateescape"))
        elif record.startswith((b"1 ", b"2 ")):
            tracked_count += 1
            fields = record.split(b" ", 2)
            if len(fields) < 2 or len(fields[1]) != 2:
                raise FingerprintError("malformed tracked record in git status")
            if fields[1][0:1] != b".":
                staged_count += 1
            if fields[1][1:2] != b".":
                unstaged_count += 1
            if record.startswith(b"2 "):
                index += 1
                if index >= len(records):
                    raise FingerprintError("rename record is missing its original path")
        elif record.startswith(b"u "):
            tracked_count += 1
            conflict_count += 1
            staged_count += 1
            unstaged_count += 1
        elif record.startswith(b"? "):
            untracked_count += 1
        elif record.startswith(b"! "):
            continue
        else:
            raise FingerprintError("unknown record in git status --porcelain=v2")
        index += 1
    return {
        "branch_headers": branch_headers,
        "conflict_count": conflict_count,
        "staged_change_count": staged_count,
        "tracked_change_count": tracked_count,
        "unstaged_change_count": unstaged_count,
        "untracked_leaf_count": untracked_count,
    }


def resolve_commit(root: Path, value: str, label: str) -> str:
    raw = git("rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}", cwd=root)
    oid = raw.decode("ascii").strip()
    if not oid:
        raise FingerprintError(f"{label} resolved to an empty object id")
    return oid


def review_scope(
    root: Path, *, base: str | None, commit: str | None
) -> tuple[dict[str, str], tuple[str, ...]]:
    if base is not None:
        base_oid = resolve_commit(root, base, "base")
        head_oid = resolve_commit(root, "HEAD", "HEAD")
        merge_base = git("merge-base", head_oid, base_oid, cwd=root).decode("ascii").strip()
        if not merge_base:
            raise FingerprintError("git merge-base returned an empty object id")
        return (
            {
                "base_oid": base_oid,
                "base_input": base,
                "head_oid": head_oid,
                "kind": "base",
                "merge_base_oid": merge_base,
                "resolved_base_oid": base_oid,
            },
            ("diff", "--binary", merge_base, head_oid, "--"),
        )
    if commit is not None:
        commit_oid = resolve_commit(root, commit, "commit")
        return (
            {
                "commit_input": commit,
                "commit_oid": commit_oid,
                "kind": "commit",
            },
            ("diff-tree", "--binary", "--root", "-p", commit_oid, "--"),
        )
    return ({"kind": "uncommitted"}, ("diff", "--binary", "HEAD", "--"))


def build_payload(
    start: Path, *, base: str | None = None, commit: str | None = None
) -> dict[str, Any]:
    root_raw = git("rev-parse", "--show-toplevel", cwd=start).rstrip(b"\n")
    if not root_raw:
        raise FingerprintError("git rev-parse returned an empty repository root")
    root = Path(os.fsdecode(root_raw))
    reject_external_clean_filters(root)

    scope, diff_command = review_scope(root, base=base, commit=commit)
    head_raw = git("rev-parse", "HEAD", cwd=root)
    status_raw = git(
        "status",
        "--porcelain=v2",
        "--branch",
        "-z",
        "--untracked-files=all",
        cwd=root,
    )
    status_summary = summarize_status(status_raw)
    if scope["kind"] in {"base", "commit"} and any(
        status_summary[key]
        for key in (
            "conflict_count",
            "staged_change_count",
            "tracked_change_count",
            "unstaged_change_count",
            "untracked_leaf_count",
        )
    ):
        raise FingerprintError(
            f"{scope['kind']} review requires a completely clean worktree "
            "(ignored files are excluded); use --uncommitted for local changes"
        )
    diff_raw = git(*diff_command, cwd=root)
    leaves = untracked_leaves(status_raw)
    manifest = snapshot_manifest(root, leaves)
    git_content_manifest = content_manifest(root, status_raw)

    head_after = git("rev-parse", "HEAD", cwd=root)
    status_after = git(
        "status",
        "--porcelain=v2",
        "--branch",
        "-z",
        "--untracked-files=all",
        cwd=root,
    )
    diff_after = git(*diff_command, cwd=root)
    if (head_after, status_after, diff_after) != (head_raw, status_raw, diff_raw):
        raise FingerprintError("repository changed during complete snapshot")
    manifest_sha256 = hashlib.sha256(canonical_json(manifest)).hexdigest()
    content_manifest_sha256 = hashlib.sha256(canonical_json(git_content_manifest)).hexdigest()

    summary = status_summary
    summary.update(
        {
            "head": head_raw.decode("ascii").strip(),
            "content_manifest_sha256": content_manifest_sha256,
            "status_porcelain_v2_sha256": hashlib.sha256(status_raw).hexdigest(),
            "tracked_diff_sha256": hashlib.sha256(diff_raw).hexdigest(),
            "untracked_manifest_sha256": manifest_sha256,
        }
    )
    return {
        "content_manifest": git_content_manifest,
        "content_manifest_sha256": content_manifest_sha256,
        "head_raw_base64": base64.b64encode(head_raw).decode("ascii"),
        "status_porcelain_v2_branch_z_base64": base64.b64encode(status_raw).decode("ascii"),
        "review_scope": scope,
        "summary": summary,
        "tracked_diff_sha256": summary["tracked_diff_sha256"],
        "untracked_manifest": manifest,
        "untracked_manifest_sha256": manifest_sha256,
        "version": 4,
    }


def build_stable_payload(
    start: Path, *, base: str | None = None, commit: str | None = None
) -> dict[str, Any]:
    first = build_payload(start, base=base, commit=commit)
    second = build_payload(start, base=base, commit=commit)
    if canonical_json(first) != canonical_json(second):
        raise FingerprintError(
            "could not obtain a stable snapshot from two consecutive complete snapshots"
        )
    return second


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a stable, read-only identity for a Git review target."
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--base", help="base ref or object id for a branch/base review")
    scope.add_argument("--commit", help="commit ref or object id for a commit review")
    arguments = parser.parse_args()
    try:
        payload = build_stable_payload(
            Path.cwd(), base=arguments.base, commit=arguments.commit
        )
        encoded = canonical_json(payload)
        summary = canonical_json(payload["summary"])
    except (FingerprintError, OSError, UnicodeError, ValueError) as exc:
        print(f"review_fingerprint: {exc}", file=sys.stderr)
        return 1
    print("CANONICAL_PAYLOAD " + encoded.decode("ascii"))
    print("FINGERPRINT_SHA256 " + hashlib.sha256(encoded).hexdigest())
    print("SUMMARY " + summary.decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

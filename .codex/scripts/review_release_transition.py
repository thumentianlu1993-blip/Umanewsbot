#!/usr/bin/env python3
"""Read-only verification for review-approved Git representation transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from review_fingerprint import (
    FingerprintError,
    canonical_json,
    git,
    resolve_commit,
    safe_relative_path,
    summarize_status,
)


class TransitionError(RuntimeError):
    """A release representation does not match the approved content."""


def repository_root(start: Path) -> Path:
    raw = git("rev-parse", "--show-toplevel", cwd=start).rstrip(b"\n")
    if not raw:
        raise TransitionError("git returned an empty repository root")
    return Path(os.fsdecode(raw))


def require_sha256(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise TransitionError("approved content hash must be a lowercase SHA-256")
    return value


def manifest_hash(entries: list[dict[str, str]]) -> str:
    return hashlib.sha256(canonical_json(entries)).hexdigest()


def git_entry(mode: str, object_type: str, oid: str, raw_path: bytes) -> dict[str, str]:
    path = safe_relative_path(raw_path)
    if mode not in {"100644", "100755", "120000"} or object_type != "blob":
        raise TransitionError(
            f"unsupported Git entry for release content: {path!r} {mode} {object_type}"
        )
    if not oid or set(oid) == {"0"} or any(char not in "0123456789abcdef" for char in oid):
        raise TransitionError(f"invalid Git object id for release content: {path!r}")
    return {"blob_oid": oid, "mode": mode, "path": path, "type": "blob"}


def index_manifest(root: Path) -> list[dict[str, str]]:
    records = [record for record in git("ls-files", "--stage", "-z", cwd=root).split(b"\0") if record]
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        try:
            metadata, raw_path = record.split(b"\t", 1)
            raw_mode, raw_oid, raw_stage = metadata.split(b" ")
            mode = raw_mode.decode("ascii")
            oid = raw_oid.decode("ascii")
            stage = raw_stage.decode("ascii")
        except (ValueError, UnicodeError) as exc:
            raise TransitionError("malformed git ls-files --stage record") from exc
        if stage != "0":
            raise TransitionError("index contains a conflict/non-stage-zero entry")
        entry = git_entry(mode, "blob", oid, raw_path)
        if entry["path"] in seen:
            raise TransitionError(f"duplicate index path: {entry['path']!r}")
        seen.add(entry["path"])
        entries.append(entry)
    return sorted(entries, key=lambda entry: os.fsencode(entry["path"]))


def commit_manifest(root: Path, commit: str) -> list[dict[str, str]]:
    records = [record for record in git("ls-tree", "-r", "-z", commit, cwd=root).split(b"\0") if record]
    entries: list[dict[str, str]] = []
    for record in records:
        try:
            metadata, raw_path = record.split(b"\t", 1)
            raw_mode, raw_type, raw_oid = metadata.split(b" ")
            mode = raw_mode.decode("ascii")
            object_type = raw_type.decode("ascii")
            oid = raw_oid.decode("ascii")
        except (ValueError, UnicodeError) as exc:
            raise TransitionError("malformed git ls-tree record") from exc
        entries.append(git_entry(mode, object_type, oid, raw_path))
    return sorted(entries, key=lambda entry: os.fsencode(entry["path"]))


def status_summary(root: Path) -> dict[str, object]:
    raw = git(
        "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all", cwd=root
    )
    return summarize_status(raw)


def verify_index(root: Path, parent_input: str, expected_hash: str) -> dict[str, str]:
    parent = resolve_commit(root, parent_input, "approved parent")
    head = resolve_commit(root, "HEAD", "HEAD")
    if head != parent:
        raise TransitionError(f"HEAD {head} is not approved parent {parent}")
    summary = status_summary(root)
    if summary["conflict_count"] or summary["unstaged_change_count"] or summary["untracked_leaf_count"]:
        raise TransitionError("index transition requires no conflicts, unstaged changes, or untracked files")
    actual_hash = manifest_hash(index_manifest(root))
    if actual_hash != require_sha256(expected_hash):
        raise TransitionError(
            f"index content hash {actual_hash} does not match approved content hash {expected_hash}"
        )
    return {"approved_content_hash": expected_hash, "approved_parent": parent, "head": head}


def verify_commit(
    root: Path, parent_input: str, expected_hash: str, commit_input: str
) -> dict[str, str]:
    parent = resolve_commit(root, parent_input, "approved parent")
    commit = resolve_commit(root, commit_input, "release commit")
    head = resolve_commit(root, "HEAD", "HEAD")
    if head != commit:
        raise TransitionError(f"HEAD {head} is not release commit {commit}")
    lineage = git("rev-list", "--parents", "-n", "1", commit, cwd=root).decode("ascii").split()
    if len(lineage) != 2 or lineage[0] != commit or lineage[1] != parent:
        raise TransitionError("release commit must be an ordinary single-parent child of approved parent")
    actual_hash = manifest_hash(commit_manifest(root, commit))
    if actual_hash != require_sha256(expected_hash):
        raise TransitionError(
            f"commit tree content hash {actual_hash} does not match approved content hash {expected_hash}"
        )
    summary = status_summary(root)
    if any(
        summary[key]
        for key in (
            "conflict_count", "staged_change_count", "tracked_change_count",
            "unstaged_change_count", "untracked_leaf_count",
        )
    ):
        raise TransitionError("commit transition requires a clean index and worktree")
    return {
        "approved_content_hash": expected_hash,
        "approved_parent": parent,
        "commit_oid": commit,
    }


def verify_remote(root: Path, remote: str, ref: str, expected_oid: str) -> dict[str, str]:
    if not ref.startswith("refs/") or any(character.isspace() for character in ref):
        raise TransitionError("remote ref must be an explicit full refs/... name")
    if not re.fullmatch(r"[0-9a-f]+", expected_oid):
        raise TransitionError("expected remote object id is invalid")
    raw = git("ls-remote", "--refs", remote, ref, cwd=root)
    rows = [row for row in raw.decode("ascii").splitlines() if row]
    if len(rows) != 1:
        raise TransitionError(f"remote ref query returned {len(rows)} rows, expected exactly one")
    try:
        actual_oid, actual_ref = rows[0].split("\t", 1)
    except ValueError as exc:
        raise TransitionError("malformed git ls-remote row") from exc
    if actual_ref != ref or actual_oid != expected_oid:
        raise TransitionError(
            f"remote {remote} {ref} is {actual_oid}, expected {expected_oid}"
        )
    return {"expected_oid": expected_oid, "ref": ref, "remote": remote}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    index = subparsers.add_parser("index")
    index.add_argument("--approved-parent", required=True)
    index.add_argument("--approved-content-hash", required=True)
    commit = subparsers.add_parser("commit")
    commit.add_argument("--approved-parent", required=True)
    commit.add_argument("--approved-content-hash", required=True)
    commit.add_argument("--commit", required=True)
    remote = subparsers.add_parser("remote")
    remote.add_argument("--remote", required=True)
    remote.add_argument("--ref", required=True)
    remote.add_argument("--expected-oid", required=True)
    args = parser.parse_args()
    try:
        root = repository_root(Path.cwd())
        if args.command == "index":
            result = verify_index(root, args.approved_parent, args.approved_content_hash)
            marker = "INDEX_TRANSITION_OK"
        elif args.command == "commit":
            result = verify_commit(
                root, args.approved_parent, args.approved_content_hash, args.commit
            )
            marker = "COMMIT_TRANSITION_OK"
        else:
            result = verify_remote(root, args.remote, args.ref, args.expected_oid)
            marker = "REMOTE_TRANSITION_OK"
    except (FingerprintError, TransitionError, OSError, UnicodeError, ValueError) as exc:
        print(f"review_release_transition: {exc}", file=sys.stderr)
        return 1
    print(marker + " " + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

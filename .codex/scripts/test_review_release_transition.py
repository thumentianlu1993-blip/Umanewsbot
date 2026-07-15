#!/usr/bin/env python3
"""End-to-end tests for the read-only review-to-release transition verifier."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT_DIR = Path(__file__).resolve().parent
FINGERPRINT = SCRIPT_DIR / "review_fingerprint.py"
VERIFIER = SCRIPT_DIR / "review_release_transition.py"


class ReviewReleaseTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.repo = root / "repo"
        self.remote = root / "remote.git"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Transition Test")
        self.git("config", "user.email", "transition@example.invalid")
        (self.repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("commit", "-qm", "baseline")
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "origin", "HEAD:refs/heads/main")
        self.parent = self.oid("HEAD")
        (self.repo / "tracked.txt").write_text("approved\n", encoding="utf-8")
        (self.repo / "new.txt").write_text("new\n", encoding="utf-8")
        self.approved = self.fingerprint()
        self.content_hash = self.approved["content_manifest_sha256"]

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=check,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def oid(self, value: str) -> str:
        return self.git("rev-parse", value).stdout.decode("ascii").strip()

    def fingerprint(self) -> dict:
        result = subprocess.run(
            [sys.executable, str(FINGERPRINT)], cwd=self.repo, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        return json.loads(result.stdout.splitlines()[0].removeprefix("CANONICAL_PAYLOAD "))

    def verify(self, *args: str, success: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(VERIFIER), *args], cwd=self.repo, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if success and result.returncode:
            self.fail(f"verifier failed: {result.stderr}")
        if not success:
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("", result.stdout)
        return result

    def index_args(self) -> tuple[str, ...]:
        return (
            "index", "--approved-parent", self.parent,
            "--approved-content-hash", self.content_hash,
        )

    def stage_approved(self) -> None:
        self.git("add", "-A")

    def commit_approved(self) -> str:
        self.stage_approved()
        self.verify(*self.index_args())
        self.git("commit", "-qm", "approved")
        return self.oid("HEAD")

    def test_full_uncommitted_stage_commit_push_transition(self) -> None:
        self.stage_approved()
        index_result = self.verify(*self.index_args())
        self.assertIn("INDEX_TRANSITION_OK", index_result.stdout)
        commit = self.commit_after_already_staged()
        commit_result = self.verify(
            "commit", "--approved-parent", self.parent,
            "--approved-content-hash", self.content_hash, "--commit", commit,
        )
        self.assertIn(commit, commit_result.stdout)
        self.verify(
            "remote", "--remote", "origin", "--ref", "refs/heads/main",
            "--expected-oid", self.parent,
        )
        self.git("push", "-q", "origin", f"{commit}:refs/heads/main")
        remote_result = self.verify(
            "remote", "--remote", "origin", "--ref", "refs/heads/main",
            "--expected-oid", commit,
        )
        self.assertIn("REMOTE_TRANSITION_OK", remote_result.stdout)

    def test_index_allows_staging_after_unchanged_pre_stage_fingerprint(self) -> None:
        before_stage = self.fingerprint()
        self.assertEqual(self.parent, before_stage["summary"]["head"])
        self.assertEqual(self.content_hash, before_stage["content_manifest_sha256"])

        self.stage_approved()
        staged = self.fingerprint()
        self.assertNotEqual(self.approved, staged)
        self.assertEqual(self.content_hash, staged["content_manifest_sha256"])
        result = self.verify(*self.index_args())
        self.assertIn("INDEX_TRANSITION_OK", result.stdout)

    def commit_after_already_staged(self) -> str:
        self.git("commit", "-qm", "approved")
        return self.oid("HEAD")

    def test_index_rejects_staged_extra_content(self) -> None:
        self.stage_approved()
        (self.repo / "extra.txt").write_text("extra\n", encoding="utf-8")
        self.git("add", "extra.txt")
        self.verify(*self.index_args(), success=False)

    def test_index_rejects_omitted_content(self) -> None:
        self.git("add", "tracked.txt")
        self.verify(*self.index_args(), success=False)

    def test_index_rejects_content_changed_after_approval(self) -> None:
        (self.repo / "tracked.txt").write_text("changed again\n", encoding="utf-8")
        self.stage_approved()
        self.verify(*self.index_args(), success=False)

    def test_index_rejects_unstaged_or_untracked_worktree(self) -> None:
        self.stage_approved()
        (self.repo / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
        self.verify(*self.index_args(), success=False)

    def test_commit_rejects_wrong_parent(self) -> None:
        commit = self.commit_approved()
        self.verify(
            "commit", "--approved-parent", commit,
            "--approved-content-hash", self.content_hash, "--commit", commit,
            success=False,
        )

    def test_commit_rejects_tree_content_mismatch(self) -> None:
        self.stage_approved()
        (self.repo / "extra.txt").write_text("extra\n", encoding="utf-8")
        self.git("add", "extra.txt")
        self.git("commit", "-qm", "wrong tree")
        commit = self.oid("HEAD")
        self.verify(
            "commit", "--approved-parent", self.parent,
            "--approved-content-hash", self.content_hash, "--commit", commit,
            success=False,
        )

    def test_commit_rejects_dirty_worktree(self) -> None:
        commit = self.commit_approved()
        (self.repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        self.verify(
            "commit", "--approved-parent", self.parent,
            "--approved-content-hash", self.content_hash, "--commit", commit,
            success=False,
        )

    def test_remote_rejects_unexpected_oid(self) -> None:
        commit = self.commit_approved()
        self.verify(
            "remote", "--remote", "origin", "--ref", "refs/heads/main",
            "--expected-oid", commit, success=False,
        )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Contract tests for the read-only review fingerprint helper."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


HELPER = Path(__file__).with_name("review_fingerprint.py")


class ReviewFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name)
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "Fingerprint Test")
        self.run_git("config", "user.email", "fingerprint@example.invalid")
        self.run_git("config", "core.filemode", "true")
        (self.repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        self.run_git("add", "tracked.txt")
        self.run_git("commit", "-qm", "baseline")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_git(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def fingerprint(
        self, *arguments: str, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            [sys.executable, str(HELPER), *arguments],
            cwd=self.repo,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check and result.returncode:
            self.fail(
                f"fingerprint failed with {result.returncode}: "
                f"{result.stderr.decode(errors='replace')}"
            )
        return result

    def load_helper(self):
        spec = importlib.util.spec_from_file_location("review_fingerprint", HELPER)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def payload(self, result: subprocess.CompletedProcess[bytes]) -> tuple[dict, str]:
        lines = result.stdout.decode("ascii").splitlines()
        self.assertEqual(3, len(lines), lines)
        self.assertTrue(lines[0].startswith("CANONICAL_PAYLOAD "))
        self.assertTrue(lines[1].startswith("FINGERPRINT_SHA256 "))
        self.assertTrue(lines[2].startswith("SUMMARY "))
        payload_bytes = lines[0].removeprefix("CANONICAL_PAYLOAD ").encode("ascii")
        fingerprint = lines[1].removeprefix("FINGERPRINT_SHA256 ")
        self.assertEqual(hashlib.sha256(payload_bytes).hexdigest(), fingerprint)
        payload = json.loads(payload_bytes)
        self.assertEqual(payload["summary"], json.loads(lines[2].removeprefix("SUMMARY ")))
        return payload, fingerprint

    def test_output_is_deterministic_and_preserves_raw_status_identity(self) -> None:
        nested = self.repo / "new dir"
        nested.mkdir()
        (nested / "file.txt").write_text("untracked\n", encoding="utf-8")

        first = self.fingerprint()
        second = self.fingerprint()
        self.assertEqual(first.stdout, second.stdout)
        payload, _ = self.payload(first)
        raw_status = self.run_git(
            "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all"
        ).stdout
        self.assertEqual(
            raw_status,
            base64.b64decode(payload["status_porcelain_v2_branch_z_base64"]),
        )
        self.assertEqual(1, payload["summary"]["untracked_leaf_count"])
        self.assertEqual(0, payload["summary"]["tracked_change_count"])
        manifest = {entry["path"]: entry for entry in payload["untracked_manifest"]}
        self.assertEqual("directory", manifest["new dir"]["type"])
        self.assertEqual("regular", manifest["new dir/file.txt"]["type"])

    def test_tracked_diff_hash_matches_git_diff_binary_head(self) -> None:
        (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        payload, _ = self.payload(self.fingerprint())
        diff = self.run_git("diff", "--binary", "HEAD", "--").stdout
        self.assertEqual(hashlib.sha256(diff).hexdigest(), payload["tracked_diff_sha256"])
        self.assertEqual(1, payload["summary"]["tracked_change_count"])

    def test_uncommitted_payload_records_git_visible_content_manifest(self) -> None:
        (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        (self.repo / "new.txt").write_text("new\n", encoding="utf-8")
        payload, _ = self.payload(self.fingerprint())
        entries = {entry["path"]: entry for entry in payload["content_manifest"]}
        self.assertEqual({"new.txt", "tracked.txt"}, set(entries))
        self.assertEqual("100644", entries["tracked.txt"]["mode"])
        self.assertEqual("blob", entries["tracked.txt"]["type"])
        self.assertRegex(entries["tracked.txt"]["blob_oid"], r"^[0-9a-f]+$")
        encoded = json.dumps(
            payload["content_manifest"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(), payload["content_manifest_sha256"]
        )
        self.assertEqual(
            payload["content_manifest_sha256"],
            payload["summary"]["content_manifest_sha256"],
        )

    def test_git_blob_oids_are_computed_without_writing_repository_objects(self) -> None:
        (self.repo / "tracked.txt").write_text("not stored\n", encoding="utf-8")
        (self.repo / "new.txt").write_text("also not stored\n", encoding="utf-8")
        before = self.run_git("count-objects", "-v").stdout
        self.fingerprint()
        after = self.run_git("count-objects", "-v").stdout
        self.assertEqual(before, after)

    def test_external_clean_filter_is_rejected_without_execution(self) -> None:
        marker = self.repo / "filter-executed"
        driver = f"sh -c 'touch {marker}; cat'"
        self.run_git("config", "filter.observable.clean", driver)
        self.run_git("config", "filter.observable.required", "true")
        (self.repo / ".gitattributes").write_text(
            "tracked.txt filter=observable\n", encoding="utf-8"
        )

        result = self.fingerprint(check=False)

        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertIn(b"filter", result.stderr)
        self.assertFalse(marker.exists(), "clean filter executed during fingerprinting")

    def test_uncommitted_conflict_fails_closed(self) -> None:
        self.run_git("checkout", "-qb", "other")
        (self.repo / "tracked.txt").write_text("other\n", encoding="utf-8")
        self.run_git("commit", "-qam", "other")
        self.run_git("checkout", "-q", "-")
        (self.repo / "tracked.txt").write_text("master\n", encoding="utf-8")
        self.run_git("commit", "-qam", "master")
        merge = subprocess.run(
            ["git", "merge", "other"], cwd=self.repo, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertNotEqual(0, merge.returncode)
        result = self.fingerprint(check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn(b"conflict", result.stderr)

    def test_tracked_rename_porcelain_v2_record_is_supported(self) -> None:
        (self.repo / "tracked.txt").rename(self.repo / "renamed.txt")
        self.run_git("add", "-A")
        payload, _ = self.payload(self.fingerprint())
        self.assertEqual(1, payload["summary"]["tracked_change_count"])
        self.assertEqual(1, payload["summary"]["staged_change_count"])

    def test_fingerprint_changes_for_tracked_content_and_executable_mode(self) -> None:
        _, baseline = self.payload(self.fingerprint())
        (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        _, content_changed = self.payload(self.fingerprint())
        self.assertNotEqual(baseline, content_changed)
        os.chmod(self.repo / "tracked.txt", 0o755)
        _, mode_changed = self.payload(self.fingerprint())
        self.assertNotEqual(content_changed, mode_changed)

    def test_fingerprint_changes_for_untracked_content_mode_and_directory_mode(self) -> None:
        directory = self.repo / "untracked"
        directory.mkdir(mode=0o755)
        leaf = directory / "leaf.txt"
        leaf.write_text("one\n", encoding="utf-8")
        _, first = self.payload(self.fingerprint())

        leaf.write_text("two\n", encoding="utf-8")
        _, content_changed = self.payload(self.fingerprint())
        self.assertNotEqual(first, content_changed)

        os.chmod(leaf, 0o755)
        _, file_mode_changed = self.payload(self.fingerprint())
        self.assertNotEqual(content_changed, file_mode_changed)

        os.chmod(directory, 0o700)
        _, directory_mode_changed = self.payload(self.fingerprint())
        self.assertNotEqual(file_mode_changed, directory_mode_changed)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are required")
    def test_symlink_target_is_hashed_but_target_contents_are_not_followed(self) -> None:
        outside = Path(self.tempdir.name + "-outside")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        outside.write_text("secret one\n", encoding="utf-8")
        link = self.repo / "link"
        link.symlink_to(outside)

        payload, first = self.payload(self.fingerprint())
        manifest = {entry["path"]: entry for entry in payload["untracked_manifest"]}
        self.assertEqual("symlink", manifest["link"]["type"])
        self.assertEqual(os.fspath(outside), manifest["link"]["target"])

        outside.write_text("secret two\n", encoding="utf-8")
        _, outside_changed = self.payload(self.fingerprint())
        self.assertEqual(first, outside_changed)

        link.unlink()
        link.symlink_to(self.repo / "different-target")
        _, target_changed = self.payload(self.fingerprint())
        self.assertNotEqual(first, target_changed)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO support is required")
    def test_special_untracked_file_type_fails_closed(self) -> None:
        fifo = self.repo / "unsafe.fifo"
        os.mkfifo(fifo)
        module = self.load_helper()
        with self.assertRaisesRegex(module.FingerprintError, "unsupported file type"):
            module.snapshot_path(self.repo, "unsafe.fifo")

    def test_git_commands_disable_optional_repository_locks(self) -> None:
        module = self.load_helper()
        completed = subprocess.CompletedProcess(
            args=["git", "status"], returncode=0, stdout=b"", stderr=b""
        )
        with mock.patch.object(module.subprocess, "run", return_value=completed) as run:
            module.git("status", cwd=self.repo)
        environment = run.call_args.kwargs["env"]
        self.assertEqual("0", environment["GIT_OPTIONAL_LOCKS"])

    def test_running_outside_git_repository_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(HELPER)],
                cwd=directory,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)

    def test_single_invocation_requires_two_identical_complete_snapshots(self) -> None:
        module = self.load_helper()
        first = {"version": 2, "summary": {"head": "first"}}
        second = {"version": 2, "summary": {"head": "second"}}
        with mock.patch.object(module, "build_payload", side_effect=[first, second]) as build:
            with self.assertRaisesRegex(module.FingerprintError, "snapshot"):
                module.build_stable_payload(self.repo)
        self.assertEqual(2, build.call_count)

    def test_change_after_first_untracked_file_snapshot_fails_closed(self) -> None:
        first_leaf = self.repo / "a.txt"
        second_leaf = self.repo / "b.txt"
        first_leaf.write_text("a\n", encoding="utf-8")
        second_leaf.write_text("before\n", encoding="utf-8")
        module = self.load_helper()
        original = module.snapshot_path
        changed = False

        def mutate_after_first(root: Path, relative: str):
            nonlocal changed
            entry = original(root, relative)
            if relative == "a.txt" and not changed:
                second_leaf.write_text("after\n", encoding="utf-8")
                changed = True
            return entry

        with mock.patch.object(module, "snapshot_path", side_effect=mutate_after_first):
            with self.assertRaisesRegex(module.FingerprintError, "snapshot"):
                module.build_stable_payload(self.repo)

    def test_tracked_and_status_change_after_first_file_snapshot_fails_closed(self) -> None:
        (self.repo / "a.txt").write_text("a\n", encoding="utf-8")
        module = self.load_helper()
        original = module.snapshot_path
        changed = False

        def mutate_tracked(root: Path, relative: str):
            nonlocal changed
            entry = original(root, relative)
            if not changed:
                (self.repo / "tracked.txt").write_text("changed after status\n", encoding="utf-8")
                (self.repo / "late.txt").write_text("late untracked\n", encoding="utf-8")
                changed = True
            return entry

        with mock.patch.object(module, "snapshot_path", side_effect=mutate_tracked):
            with self.assertRaisesRegex(module.FingerprintError, "snapshot"):
                module.build_stable_payload(self.repo)

    def test_base_scope_records_immutable_oids_and_merge_base(self) -> None:
        baseline = self.run_git("rev-parse", "HEAD").stdout.decode("ascii").strip()
        (self.repo / "tracked.txt").write_text("branch change\n", encoding="utf-8")
        self.run_git("add", "tracked.txt")
        self.run_git("commit", "-qm", "branch change")

        payload, _ = self.payload(self.fingerprint("--base", baseline))
        scope = payload["review_scope"]
        self.assertEqual("base", scope["kind"])
        self.assertEqual(baseline, scope["base_input"])
        self.assertEqual(baseline, scope["resolved_base_oid"])
        self.assertEqual(baseline, scope["merge_base_oid"])
        diff = self.run_git("diff", "--binary", baseline, "HEAD", "--").stdout
        self.assertEqual(hashlib.sha256(diff).hexdigest(), payload["tracked_diff_sha256"])

    def test_base_and_commit_scopes_fail_closed_for_dirty_tracked_file(self) -> None:
        baseline = self.run_git("rev-parse", "HEAD").stdout.decode("ascii").strip()
        (self.repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        for arguments in (("--base", baseline), ("--commit", baseline)):
            with self.subTest(arguments=arguments):
                result = self.fingerprint(*arguments, check=False)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(b"", result.stdout)
                self.assertIn(b"clean worktree", result.stderr)

    def test_base_and_commit_scopes_fail_closed_for_staged_change(self) -> None:
        baseline = self.run_git("rev-parse", "HEAD").stdout.decode("ascii").strip()
        (self.repo / "tracked.txt").write_text("staged\n", encoding="utf-8")
        self.run_git("add", "tracked.txt")
        for arguments in (("--base", baseline), ("--commit", baseline)):
            with self.subTest(arguments=arguments):
                result = self.fingerprint(*arguments, check=False)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(b"", result.stdout)
                self.assertIn(b"clean worktree", result.stderr)

    def test_base_and_commit_scopes_fail_closed_for_untracked_file(self) -> None:
        baseline = self.run_git("rev-parse", "HEAD").stdout.decode("ascii").strip()
        (self.repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        for arguments in (("--base", baseline), ("--commit", baseline)):
            with self.subTest(arguments=arguments):
                result = self.fingerprint(*arguments, check=False)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(b"", result.stdout)
                self.assertIn(b"clean worktree", result.stderr)

    def test_base_scope_ignores_ignored_files_and_hashes_merge_base_to_head(self) -> None:
        baseline = self.run_git("rev-parse", "HEAD").stdout.decode("ascii").strip()
        (self.repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        self.run_git("add", ".gitignore")
        self.run_git("commit", "-qm", "ignore local evidence")
        (self.repo / "tracked.txt").write_text("committed branch change\n", encoding="utf-8")
        self.run_git("add", "tracked.txt")
        self.run_git("commit", "-qm", "branch change")
        (self.repo / "ignored.txt").write_text("ignored\n", encoding="utf-8")

        payload, _ = self.payload(self.fingerprint("--base", baseline))
        merge_base = self.run_git("merge-base", "HEAD", baseline).stdout.decode("ascii").strip()
        self.assertEqual(baseline, payload["review_scope"]["base_oid"])
        self.assertEqual(merge_base, payload["review_scope"]["merge_base_oid"])
        diff = self.run_git("diff", "--binary", merge_base, "HEAD", "--").stdout
        self.assertEqual(hashlib.sha256(diff).hexdigest(), payload["tracked_diff_sha256"])

    def test_moving_base_ref_is_resolved_into_payload(self) -> None:
        baseline = self.run_git("rev-parse", "HEAD").stdout.decode("ascii").strip()
        self.run_git("branch", "review-base", baseline)
        payload, _ = self.payload(self.fingerprint("--base", "review-base"))
        self.assertEqual("review-base", payload["review_scope"]["base_input"])
        self.assertEqual(baseline, payload["review_scope"]["resolved_base_oid"])

    def test_commit_scope_records_resolved_commit_oid(self) -> None:
        commit = self.run_git("rev-parse", "HEAD").stdout.decode("ascii").strip()
        payload, _ = self.payload(self.fingerprint("--commit", "HEAD"))
        self.assertEqual(
            {
                "commit_input": "HEAD",
                "commit_oid": commit,
                "kind": "commit",
            },
            payload["review_scope"],
        )
        diff = self.run_git(
            "diff-tree", "--binary", "--root", "-p", commit, "--"
        ).stdout
        self.assertEqual(hashlib.sha256(diff).hexdigest(), payload["tracked_diff_sha256"])

    def test_untracked_nested_git_repository_directory_leaf_fails_closed(self) -> None:
        nested = self.repo / "nested-repo"
        nested.mkdir()
        subprocess.run(
            ["git", "init", "-q"],
            cwd=nested,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (nested / "inside.txt").write_text("inside\n", encoding="utf-8")
        result = self.fingerprint(check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertIn(b"untracked directory leaf", result.stderr)


if __name__ == "__main__":
    unittest.main()

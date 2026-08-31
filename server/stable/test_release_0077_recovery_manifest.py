from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/create_release_0077_recovery_manifest.py"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Release0077RecoveryManifestTests(SimpleTestCase):
    maxDiff = None

    def _fixture(self, root: Path) -> dict[str, object]:
        runtime = root / "runtime" / "migration_history_repair"
        manifest_dir = runtime / "release-0077-recovery"
        artifact_dir = runtime / "preflight" / "before.test"
        manifest_dir.mkdir(parents=True, mode=0o700)
        artifact_dir.mkdir(parents=True, mode=0o700)
        manifest_dir.chmod(0o700)
        artifact_dir.chmod(0o700)
        backup = root / "backup.dump"
        backup.write_bytes(b"PGDMP-test-backup")
        backup.chmod(0o600)
        fake_bin = root / "bin"
        fake_bin.mkdir(mode=0o700)
        pg_restore = fake_bin / "pg_restore"
        pg_restore.write_text(
            "#!/bin/sh\n"
            "test \"${1:-}\" = --list || exit 71\n"
            "test \"${2:-}\" = \"$EXPECTED_BACKUP\" || exit 72\n"
            "printf '%s\\n' '; Archive created at test' '1; 0 0 TABLE public example owner'\n",
            encoding="utf-8",
        )
        pg_restore.chmod(0o700)
        commit = "a" * 40
        return {
            "runtime": runtime,
            "manifest": manifest_dir / f"{commit}.json",
            "artifact": artifact_dir / "preflight.json",
            "backup": backup,
            "fake_bin": fake_bin,
            "commit": commit,
            "image": "sha256:" + "b" * 64,
            "database": "c" * 64,
            "origin": "d" * 64,
        }

    def _run_creator(self, fixture: dict[str, object], *, backup_sha256: str | None = None):
        backup = fixture["backup"]
        assert isinstance(backup, Path)
        fake_bin = fixture["fake_bin"]
        assert isinstance(fake_bin, Path)
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--output-path",
                str(fixture["manifest"]),
                "--candidate-commit",
                str(fixture["commit"]),
                "--candidate-image-id",
                str(fixture["image"]),
                "--database-identity-sha256",
                str(fixture["database"]),
                "--origin-handoff-sha256",
                str(fixture["origin"]),
                "--backup-path",
                str(backup),
                "--backup-sha256",
                backup_sha256 or _sha256(backup),
                "--source-leaf",
                "stable.0075_race_data_source_priority_and_reported_position",
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "EXPECTED_BACKUP": str(backup),
            },
            text=True,
            capture_output=True,
            check=False,
        )

    def test_creator_publishes_exact_backup_bound_mode_0600_manifest(self):
        with TemporaryDirectory() as tmp:
            fixture = self._fixture(Path(tmp))
            result = self._run_creator(fixture)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = fixture["manifest"]
            assert isinstance(manifest, Path)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            output = json.loads(result.stdout)
            self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
            self.assertEqual(output["manifest_path"], str(manifest))
            self.assertEqual(output["manifest_sha256"], _sha256(manifest))
            self.assertEqual(payload["backup_path"], str(fixture["backup"]))
            self.assertEqual(payload["backup_sha256"], _sha256(fixture["backup"]))
            self.assertEqual(payload["pg_restore_list_line_count"], 2)
            self.assertEqual(payload["candidate_commit"], fixture["commit"])
            self.assertEqual(payload["origin_handoff_sha256"], fixture["origin"])

    def test_creator_fails_before_publish_for_wrong_backup_sha(self):
        with TemporaryDirectory() as tmp:
            fixture = self._fixture(Path(tmp))
            result = self._run_creator(fixture, backup_sha256="e" * 64)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("backup SHA-256 mismatch", result.stderr)
            self.assertFalse(Path(fixture["manifest"]).exists())

    def test_binding_reads_and_authenticates_manifest_bytes_and_fields(self):
        from stable.services.historical_calendar_release_b_handoff import (
            release_0077_recovery_binding,
        )

        with TemporaryDirectory() as tmp:
            fixture = self._fixture(Path(tmp))
            created = self._run_creator(fixture)
            self.assertEqual(created.returncode, 0, created.stderr)
            manifest = Path(fixture["manifest"])
            preflight = {
                "migration_leaf_set": [
                    "stable.0075_race_data_source_priority_and_reported_position"
                ],
                "migration_plan": [
                    "0076_alter_externaldataimporterror_racing_region_and_more",
                    "0077_racing_api_horse_identity_staging",
                ],
                "database_identity_sha256": fixture["database"],
            }
            result = release_0077_recovery_binding(
                preflight=preflight,
                candidate_commit=str(fixture["commit"]),
                candidate_image_id=str(fixture["image"]),
                artifact_path=str(fixture["artifact"]),
                handoff_action="deploy",
                manifest_path=str(manifest),
                manifest_sha256=_sha256(manifest),
                origin_handoff_sha256=str(fixture["origin"]),
            )
            self.assertEqual(result["release_0077_recovery_binding_mode"], "bound")

            manifest.chmod(0o700)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["origin_handoff_sha256"] = "f" * 64
            manifest.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            manifest.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "manifest"):
                release_0077_recovery_binding(
                    preflight=preflight,
                    candidate_commit=str(fixture["commit"]),
                    candidate_image_id=str(fixture["image"]),
                    artifact_path=str(fixture["artifact"]),
                    handoff_action="deploy",
                    manifest_path=str(manifest),
                    manifest_sha256=_sha256(manifest),
                    origin_handoff_sha256=str(fixture["origin"]),
                )

    def test_release_orchestration_rebinds_only_after_web_stop_and_before_migrate(self):
        application = (ROOT / "deploy/run_application_release.sh").read_text(
            encoding="utf-8"
        )
        preflight = (
            ROOT / "deploy/run_historical_calendar_release_b_preflight.sh"
        ).read_text(encoding="utf-8")
        docker_release = (ROOT / "deploy/docker/run-release-tasks.sh").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            application.index('echo "release: stopping web"'),
            application.index("release: binding closed-state 0077 recovery handoff"),
        )
        self.assertLess(
            application.index("release: binding closed-state 0077 recovery handoff"),
            application.index('echo "release: running the bounded release task phases"'),
        )
        self.assertIn("create_release_0077_recovery_manifest.py", application)
        self.assertIn("--release-0077-recovery-manifest-path", preflight)
        self.assertIn("--release-0077-recovery-manifest-path", docker_release)

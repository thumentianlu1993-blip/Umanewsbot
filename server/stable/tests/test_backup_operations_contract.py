"""Executable contracts for the production database backup path."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[3]
BACKUP = ROOT / "deploy" / "backup_db.sh"
RESTORE = ROOT / "deploy" / "restore_db.sh"
UPLOAD = ROOT / "deploy" / "upload_backup_to_oss.py"
PROMOTE = ROOT / "deploy" / "promote_lifecycle_enforce_registry.sh"
ENV_EXAMPLE = ROOT / ".env.example"


FAKE_DOCKER = r"""#!/bin/sh
set -eu
printf 'docker %s\n' "$*" >> "${FAKE_DOCKER_LOG:?}"
case " $* " in
  *" compose version "*) exit 0 ;;
  *" pg_dump "*)
    [ "${FAKE_PGDUMP_FAIL:-0}" = 0 ] || exit 23
    printf 'PGDMP-test-archive\n'
    ;;
  *" pg_restore -l "*)
    payload="$(cat)"
    [ "$payload" = 'PGDMP-test-archive' ] || exit 24
    printf '1; 0 0 DATABASE - test\n'
    ;;
  *" pg_restore --clean "*)
    payload="$(cat)"
    [ "$payload" = 'PGDMP-test-archive' ] || exit 26
    ;;
  *) exit 25 ;;
esac
"""


FAKE_OSS2 = r"""class Auth:
    def __init__(self, *args):
        pass

class _Result:
    status = 200
    etag = 'fake-etag'
    content_length = int(__import__('os').environ.get('FAKE_REMOTE_SIZE', '0'))

class Bucket:
    def __init__(self, *args):
        pass
    def put_object(self, key, fp):
        fp.read()
        return _Result()
    def head_object(self, key):
        return _Result()
"""


class ProductionBackupOperationsContracts(SimpleTestCase):
    def _run_backup(
        self,
        *,
        fail_dump: bool = False,
        compose_file: str = "docker-compose.prod.lowcost.yml",
        include_compose_contract: bool = True,
    ):
        temp = TemporaryDirectory()
        root = Path(temp.name)
        (root / "deploy" / "docker").mkdir(parents=True)
        (root / "bin").mkdir()
        shutil.copy2(BACKUP, root / "deploy" / "backup_db.sh")
        shutil.copy2(
            ROOT / "deploy" / "docker" / "compose-wrapper.sh",
            root / "deploy" / "docker" / "compose-wrapper.sh",
        )
        (root / compose_file).write_text(
            "services: {}\n", encoding="utf-8"
        )
        compose_contract = (
            f"COMPOSE_FILE={compose_file}\nEXPECTED_COMPOSE_PROJECT=reviewed-prod\n"
            if include_compose_contract
            else ""
        )
        (root / ".env").write_text(
            "POSTGRES_DB=test_db\n"
            "POSTGRES_USER=test_user\n"
            "POSTGRES_PASSWORD=test-password\n"
            "POSTGRES_HOST=db\n"
            "POSTGRES_PORT=5432\n"
            "BACKUP_TARGET=oss\n"
            + compose_contract,
            encoding="utf-8",
        )
        fake_docker = root / "bin" / "docker"
        fake_docker.write_text(FAKE_DOCKER, encoding="utf-8")
        fake_docker.chmod(0o755)
        log = root / "docker.log"
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{root / 'bin'}:{env['PATH']}",
                "FAKE_DOCKER_LOG": str(log),
                "FAKE_PGDUMP_FAIL": "1" if fail_dump else "0",
                # Explicit caller choice must override BACKUP_TARGET=oss in .env.
                "BACKUP_TARGET": "local",
            }
        )
        result = subprocess.run(
            ["sh", str(root / "deploy" / "backup_db.sh")],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        return temp, root, result, log

    def test_backup_uses_compose_db_custom_archive_and_atomic_publish(self):
        temp, root, result, log = self._run_backup()
        self.addCleanup(temp.cleanup)
        self.assertEqual(result.returncode, 0, result.stderr)
        created = [
            line.removeprefix("Backup created: ")
            for line in result.stdout.splitlines()
            if line.startswith("Backup created: ")
        ]
        self.assertEqual(len(created), 1, result.stdout)
        archive = root / created[0]
        self.assertEqual(archive.suffix, ".dump")
        self.assertEqual(archive.read_bytes(), b"PGDMP-test-archive\n")
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
        self.assertFalse(list(archive.parent.glob("*.tmp.*")))
        calls = log.read_text(encoding="utf-8")
        project_args = (
            "compose -f docker-compose.prod.lowcost.yml "
            "--project-directory "
        )
        self.assertIn(project_args, calls)
        self.assertIn("--project-name reviewed-prod exec -T db pg_dump", calls)
        self.assertIn("--project-name reviewed-prod exec -T db pg_restore -l", calls)
        self.assertNotIn("docker run", calls)
        self.assertNotIn("Uploaded to OSS", result.stdout)

    def test_failed_dump_leaves_no_final_or_temporary_archive(self):
        temp, root, result, _log = self._run_backup(fail_dump=True)
        self.addCleanup(temp.cleanup)
        self.assertNotEqual(result.returncode, 0)
        backup_dir = root / "backups" / "db"
        self.assertFalse(list(backup_dir.iterdir()))

    def test_rds_backup_uses_isolated_postgres_client_with_exported_password(self):
        temp, _root, result, log = self._run_backup(
            compose_file="docker-compose.prod.yml"
        )
        self.addCleanup(temp.cleanup)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = log.read_text(encoding="utf-8")
        self.assertIn(
            "docker run --rm -e PGPASSWORD postgres:16 pg_dump",
            calls,
        )
        self.assertIn("docker run --rm -i postgres:16 pg_restore -l", calls)
        self.assertNotIn("test-password", calls)

    def test_backup_requires_explicit_deployment_mode_before_docker(self):
        temp, _root, result, log = self._run_backup(
            include_compose_contract=False
        )
        self.addCleanup(temp.cleanup)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("COMPOSE_FILE is required", result.stderr)
        self.assertFalse(log.exists())

    def test_backup_scripts_are_executable_for_reviewed_wrappers(self):
        self.assertTrue(os.access(BACKUP, os.X_OK))
        self.assertTrue(os.access(RESTORE, os.X_OK))

    def test_custom_archive_restore_uses_compose_db_and_fail_closed_options(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "deploy" / "docker").mkdir(parents=True)
            (root / "bin").mkdir()
            shutil.copy2(RESTORE, root / "deploy" / "restore_db.sh")
            shutil.copy2(
                ROOT / "deploy" / "docker" / "compose-wrapper.sh",
                root / "deploy" / "docker" / "compose-wrapper.sh",
            )
            (root / "docker-compose.prod.lowcost.yml").write_text(
                "services: {}\n", encoding="utf-8"
            )
            (root / ".env").write_text(
                "POSTGRES_DB=test_db\nPOSTGRES_USER=test_user\n"
                "COMPOSE_FILE=docker-compose.prod.lowcost.yml\n"
                "EXPECTED_COMPOSE_PROJECT=reviewed-prod\n",
                encoding="utf-8",
            )
            archive = root / "backup.dump"
            archive.write_bytes(b"PGDMP-test-archive\n")
            fake_docker = root / "bin" / "docker"
            fake_docker.write_text(FAKE_DOCKER, encoding="utf-8")
            fake_docker.chmod(0o755)
            log = root / "docker.log"
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{root / 'bin'}:{env['PATH']}",
                    "FAKE_DOCKER_LOG": str(log),
                }
            )
            result = subprocess.run(
                ["sh", str(root / "deploy" / "restore_db.sh"), str(archive)],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text(encoding="utf-8")
            self.assertIn(
                "--project-name reviewed-prod exec -T db "
                "pg_restore --clean --if-exists --exit-on-error --single-transaction",
                calls,
            )
            self.assertNotIn("docker run", calls)

    def test_rds_custom_archive_restore_uses_isolated_postgres_client(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "deploy" / "docker").mkdir(parents=True)
            (root / "bin").mkdir()
            shutil.copy2(RESTORE, root / "deploy" / "restore_db.sh")
            shutil.copy2(
                ROOT / "deploy" / "docker" / "compose-wrapper.sh",
                root / "deploy" / "docker" / "compose-wrapper.sh",
            )
            (root / "docker-compose.prod.yml").write_text(
                "services: {}\n", encoding="utf-8"
            )
            (root / ".env").write_text(
                "POSTGRES_DB=test_db\nPOSTGRES_USER=test_user\n"
                "POSTGRES_PASSWORD=test-password\nPOSTGRES_HOST=rds.example\n"
                "POSTGRES_PORT=5432\nCOMPOSE_FILE=docker-compose.prod.yml\n"
                "EXPECTED_COMPOSE_PROJECT=reviewed-prod\n",
                encoding="utf-8",
            )
            archive = root / "backup.dump"
            archive.write_bytes(b"PGDMP-test-archive\n")
            fake_docker = root / "bin" / "docker"
            fake_docker.write_text(FAKE_DOCKER, encoding="utf-8")
            fake_docker.chmod(0o755)
            log = root / "docker.log"
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{root / 'bin'}:{env['PATH']}",
                    "FAKE_DOCKER_LOG": str(log),
                }
            )
            result = subprocess.run(
                ["sh", str(root / "deploy" / "restore_db.sh"), str(archive)],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text(encoding="utf-8")
            self.assertIn("docker run --rm -i postgres:16 pg_restore -l", calls)
            self.assertIn(
                "docker run --rm -i -e PGPASSWORD postgres:16 pg_restore --clean",
                calls,
            )
            self.assertNotIn("test-password", calls)

    def test_upload_verifies_remote_object_size(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "oss2.py").write_text(FAKE_OSS2, encoding="utf-8")
            archive = root / "sample.dump"
            archive.write_bytes(b"verified-archive")
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": str(root),
                    "OSS_ACCESS_KEY_ID": "test-id",
                    "OSS_ACCESS_KEY_SECRET": "test-secret",
                    "OSS_BUCKET_NAME": "test-bucket",
                    "OSS_ENDPOINT": "https://oss-cn-hongkong.aliyuncs.com",
                    "OSS_BACKUP_PREFIX": "db_backups",
                    "FAKE_REMOTE_SIZE": str(archive.stat().st_size),
                }
            )
            ok = subprocess.run(
                [sys.executable, str(UPLOAD), str(archive)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("OSS upload verified", ok.stdout)

            env["FAKE_REMOTE_SIZE"] = "1"
            mismatch = subprocess.run(
                [sys.executable, str(UPLOAD), str(archive)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("size mismatch", mismatch.stdout + mismatch.stderr)

    def test_registry_promotion_revalidates_dump_for_both_deployment_modes(self):
        source = PROMOTE.read_text(encoding="utf-8")
        dump_branch = source[source.index("*.dump)") : source.index("*.gz)")]
        self.assertIn('docker-compose.prod.lowcost.yml)', dump_branch)
        self.assertIn('docker-compose.prod.yml)', dump_branch)
        self.assertIn('compose_mutation exec -T db pg_restore -l', dump_branch)
        self.assertIn('docker run --rm -i postgres:16 pg_restore -l', dump_branch)
        self.assertNotRegex(dump_branch, r"(?m)^\s*pg_restore -l")

    def test_example_declares_rds_compose_mode_and_reviewed_project(self):
        source = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("COMPOSE_FILE=docker-compose.prod.yml", source)
        self.assertIn("EXPECTED_COMPOSE_PROJECT=umanewsbot", source)

    def test_oss_upload_uses_reviewed_app_image_not_host_python(self):
        source = BACKUP.read_text(encoding="utf-8")
        self.assertNotIn("python3 ./deploy/upload_backup_to_oss.py", source)
        self.assertIn("run --rm --no-deps -T", source)
        self.assertIn("/app/deploy/upload_backup_to_oss.py", source)
        self.assertIn(":/run/umanews-backup.dump:ro", source)

    def test_example_uses_resolvable_hong_kong_oss_endpoint(self):
        source = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("OSS_ENDPOINT=https://oss-cn-hongkong.aliyuncs.com", source)
        self.assertNotIn("OSS_ENDPOINT=https://oss-hk.aliyuncs.com", source)

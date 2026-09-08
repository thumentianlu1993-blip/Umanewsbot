"""真实 PostgreSQL 16 迁移/恢复测试，仅允许专用 CI 的回环数据库。"""

from __future__ import annotations

import os
import hashlib
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from io import StringIO
from unittest import TestCase, skipUnless

import psycopg
from psycopg import sql
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.recorder import MigrationRecorder
from django.core.management import call_command

from stable.services import historical_calendar_release_b_schema as schema
from stable.services import release_0078_recovery as recovery


M77 = ("stable", "0077_racing_api_horse_identity_staging")
M78 = ("stable", "0078_externalhorse_profile_snapshot")
ENABLED = os.environ.get("RELEASE_0078_TEST_POSTGRES") == "1"


@skipUnless(ENABLED, "requires the isolated PostgreSQL 16 contract job")
class Release0078PostgresTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if connection.vendor != "postgresql" or connection.settings_dict["HOST"] != "127.0.0.1":
            raise RuntimeError("0078 tests only accept the dedicated loopback PostgreSQL service")
        cls.original_name = connection.settings_dict["NAME"]
        if cls.original_name != "release_0078_ci":
            raise RuntimeError("0078 tests require the explicit release_0078_ci database")
        cls.params = dict(host="127.0.0.1", port=connection.settings_dict["PORT"],
                          user=connection.settings_dict["USER"], password=connection.settings_dict["PASSWORD"])
        cls.admin = psycopg.connect(dbname=cls.original_name, autocommit=True, **cls.params)
        if cls.admin.info.server_version // 10000 != 16:
            raise RuntimeError("0078 catalog contract must be measured on PostgreSQL 16")
        cls.template = "test_0078_template_" + uuid.uuid4().hex
        cls.admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.template)))
        connection.close()
        connection.settings_dict["NAME"] = cls.template
        try:
            MigrationExecutor(connection).migrate([M77])
        finally:
            connection.close()
            connection.settings_dict["NAME"] = cls.original_name

    @classmethod
    def tearDownClass(cls):
        connection.close()
        connection.settings_dict["NAME"] = cls.original_name
        cls.admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.template)))
        cls.admin.close()
        super().tearDownClass()

    def setUp(self):
        self.name = "test_0078_case_" + uuid.uuid4().hex
        self.admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(self.name), sql.Identifier(self.template)))
        connection.close()
        connection.settings_dict["NAME"] = self.name
        self.targets = [self.name]

    def tearDown(self):
        connection.close()
        connection.settings_dict["NAME"] = self.original_name
        for name in self.targets:
            self.assertTrue(name.startswith("test_0078_"))
            self.admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))

    def column(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT format_type(a.atttypid, a.atttypmod), a.attnotnull,
                       a.attidentity, a.attgenerated, pg_get_expr(d.adbin, d.adrelid)
                FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
                WHERE n.nspname='public' AND c.relname='stable_externalhorse'
                  AND a.attname='profile_snapshot' AND NOT a.attisdropped
            """)
            return cursor.fetchall()

    def test_real_upgrade_catalog_defaults_and_irreversibility(self):
        self.assertEqual(self.column(), [])
        executor = MigrationExecutor(connection)
        self.assertEqual([(m.name, backwards) for m, backwards in executor.migration_plan([M78])], [(M78[1], False)])
        old_apps = executor.loader.project_state([M77]).apps
        horse = old_apps.get_model("stable", "ExternalHorse").objects.create(source="the_racing_api", horse_id="test-0078-1", horse_name="合成测试马")
        executor.migrate([M78])
        self.assertEqual(self.column(), [("jsonb", True, "", "", None)])
        self.assertIn(M78, MigrationRecorder(connection).applied_migrations())
        self.assertEqual(MigrationExecutor(connection).migration_plan([M78]), [])
        self.assertEqual(schema.validate_externalhorse_profile_snapshot_catalog_contract(
            contract=schema.collect_postgresql_catalog_contract(), migration_applied=True), [])
        apps = MigrationExecutor(connection).loader.project_state([M78]).apps
        model = apps.get_model("stable", "ExternalHorse")
        self.assertEqual(model.objects.get(pk=horse.pk).profile_snapshot, {})
        with self.assertRaises(IrreversibleError):
            MigrationExecutor(connection).migrate([M77])
        self.assertEqual(self.column(), [("jsonb", True, "", "", None)])
        self.assertIn(M78, MigrationRecorder(connection).applied_migrations())

    def test_lock_timeout_keeps_0077_atomic_and_retry_succeeds(self):
        blocker = psycopg.connect(dbname=self.name, **self.params)
        try:
            blocker.execute("LOCK TABLE stable_externalhorse IN ACCESS SHARE MODE")
            started = time.monotonic()
            with self.assertRaises(Exception) as caught:
                MigrationExecutor(connection).migrate([M78])
            self.assertIn("lock timeout", str(caught.exception).lower())
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, 4.5)
            self.assertLess(elapsed, 20)
            self.assertEqual(self.column(), [])
            self.assertNotIn(M78, MigrationRecorder(connection).applied_migrations())
        finally:
            blocker.rollback()
            blocker.close()
        MigrationExecutor(connection).migrate([M78])
        self.assertEqual(self.column(), [("jsonb", True, "", "", None)])

    def test_real_v5_handoff_commands_migrate_and_archive_exact_0078_receipt(self):
        """No mocked management commands, schema collector, or DDL owner."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            marker = directory / "restricted-recovery.json"
            origin_path = directory / "admission.json"
            candidate, image = "b" * 40, "sha256:" + "c" * 64
            db_identity = schema._database_identity_sha256()
            common = {"candidate_commit": candidate, "candidate_image_id": image,
                      "compose_file": "docker-compose.prod.yml", "deployment_lock_token_sha256": "e" * 64,
                      "restricted_marker_path": str(marker), "expected_database_identity_sha256": db_identity}
            before = schema.check_release_b_schema_compatibility(direction="forward")
            self.assertTrue(before["ok"], before)
            self.assertEqual(before["migration_leaf_set"], ["stable.0077_racing_api_horse_identity_staging"])
            call_command("create_historical_calendar_release_b_handoff", action="deploy",
                         output_path=str(origin_path), stdout=StringIO(), **common)
            origin, _ = recovery.read_json(origin_path)
            release_id = origin["artifact_sha256"]
            release_root = directory / "release-0078-recovery"
            release_root.mkdir(mode=0o700)
            release = release_root / release_id
            release.mkdir(mode=0o700)
            backup_dir = release / "backup"
            backup_dir.mkdir(mode=0o700)
            backup = backup_dir / "synthetic-0077.dump"
            self.pg("pg_dump", "--format=custom", "--file", backup, self.name)
            backup.chmod(0o600)
            toc = self.pg("pg_restore", "--list", backup).stdout
            bindings = {"release_id": release_id, "origin_handoff_sha256": release_id,
                        "candidate_commit": candidate, "candidate_image_id": image,
                        "database_identity_sha256": db_identity, "compose_file": "docker-compose.prod.yml"}
            restore = {name: False for name in ("web", "worker", "beat", "race_live_worker", "race_sync_v2_worker", "nginx")}
            manifest = {"schema_version": "release-0078-verified-backup-recovery/v1", **bindings,
                        "source_leaf": "stable.0077_racing_api_horse_identity_staging",
                        "target_leaf": "stable.0078_externalhorse_profile_snapshot", "operation": "upgrade",
                        "migration_contract_sha256": "50c421f3167a8c2c8f1613a0597ad7ee196c249fc18bf7eed0de7b9cd2f80906",
                        "backup_path": str(backup), "backup_file": recovery.file_evidence(backup)[1],
                        "pg_restore_list_sha256": hashlib.sha256(toc).hexdigest(), "pg_restore_list_line_count": len(toc.splitlines()),
                        "restore_services": restore, "config_sha256": "f" * 64, "initial_lock_sha256": "e" * 64,
                        "compose_project": "isolated0078",
                        "writer_flags": origin["writer_activity"]["flags"]}
            manifest_path = release / "manifest.json"
            manifest_sha = recovery.publish_once(manifest_path, manifest)["sha256"]
            intent_path = release / "intent.json"
            intent = {"schema_version": "release-0078-prepared-intent/v1", **bindings,
                      "manifest_sha256": manifest_sha, "origin_handoff_path": str(origin_path),
                      "source_leaf": manifest["source_leaf"], "restore_services": restore,
                      "config_sha256": "f" * 64, "initial_lock_sha256": "e" * 64}
            intent_file = recovery.publish_once(intent_path, intent)
            recovery.publish_once(release_root / "active.json", {"release_id": release_id, "intent_path": str(intent_path), "intent_file": intent_file})
            fields = {"release_0078_recovery_manifest_path": str(manifest_path),
                      "release_0078_recovery_manifest_sha256": manifest_sha,
                      "release_0078_recovery_origin_handoff_sha256": release_id,
                      "release_0078_intent_path": str(intent_path), "release_0078_intent_sha256": intent_file["sha256"]}
            closed_path = directory / "closed.json"
            self.assertFalse(marker.exists())
            call_command("create_historical_calendar_release_b_handoff", action="forward-resume",
                         output_path=str(closed_path), provenance_artifact_sha256=release_id,
                         stdout=StringIO(), **common, **fields)
            closed, _ = recovery.read_json(closed_path)
            command_common = {"artifact_path": str(closed_path), "artifact_sha256": closed["artifact_sha256"],
                              "candidate_commit": candidate, "candidate_image_id": image,
                              "database_identity_sha256": db_identity}
            call_command("verify_historical_calendar_release_b_handoff", stdout=StringIO(), **command_common,
                         compose_file="docker-compose.prod.yml", deployment_lock_token_sha256="e" * 64, **fields)
            output = StringIO()
            call_command("ensure_historical_calendar_recovery_intent", stdout=output, **command_common,
                         marker_path=str(marker), provenance_artifact_sha256=release_id, attempt_mode="required")
            result = json.loads(output.getvalue())
            ddl_marker, _ = recovery.read_json(marker)
            self.assertEqual(ddl_marker["schema_version"], "migration-history-repair-restricted-recovery/v3")
            self.assertEqual(ddl_marker["initial_leaf_set"], ["stable.0077_racing_api_horse_identity_staging"])
            MigrationExecutor(connection).migrate([M78])
            after = schema.check_release_b_schema_compatibility(direction="forward")
            self.assertTrue(after["ok"], after)
            self.assertEqual(after["migration_plan"], [])
            call_command("complete_historical_calendar_restricted_recovery", stdout=StringIO(), **command_common,
                         marker_path=str(marker), provenance_artifact_sha256=release_id, attempt_mode="required",
                         expected_marker_device=result["marker_device"], expected_marker_inode=result["marker_inode"])
            self.assertFalse(marker.exists())
            receipt = recovery.completed_marker(directory, recovery.marker_binding(closed))
            self.assertIsNotNone(receipt)
            self.assertTrue((release_root / "active.json").exists(), "schema completion precedes host service restoration")

    def pg(self, command, *args, check=True):
        env = {**os.environ, "PGHOST": "127.0.0.1", "PGPORT": str(self.params["port"]),
               "PGUSER": self.params["user"], "PGPASSWORD": self.params["password"]}
        return subprocess.run([command, *map(str, args)], env=env, capture_output=True, check=check)

    def empty_restore(self, dump):
        name = "test_0078_restore_" + uuid.uuid4().hex
        self.admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        self.targets.append(name)
        self.pg("pg_restore", "--clean", "--if-exists", "--exit-on-error", "--single-transaction", "--dbname", name, dump)
        return name

    def test_custom_dump_restores_synthetic_data_and_0077_0078_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_dump, new_dump = Path(tmp) / "0077.dump", Path(tmp) / "0078.dump"
            self.pg("pg_dump", "--format=custom", "--file", old_dump, self.name)
            MigrationExecutor(connection).migrate([M78])
            apps = MigrationExecutor(connection).loader.project_state([M78]).apps
            horse_model = apps.get_model("stable", "ExternalHorse")
            snapshot = {"source": "synthetic", "name": "恢复验证", "pedigree": {"sire": "test-parent"}}
            horse = horse_model.objects.create(source="the_racing_api", horse_id="restore-0078", horse_name="恢复验证", profile_snapshot=snapshot)
            # Preserve an existing FK relationship, not only a JSON scalar.
            alias_model = apps.get_model("stable", "ExternalHorseAlias")
            alias_model.objects.create(source="the_racing_api", external_horse_id="restore-0078", horse_id=horse.pk, name_ja="合成别名", normalized_name="synthetic-alias")
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM django_migrations")
                recorder_count = cursor.fetchone()[0]
            self.pg("pg_dump", "--format=custom", "--file", new_dump, self.name)
            new_name = self.empty_restore(new_dump)
            with psycopg.connect(dbname=new_name, **self.params) as restored:
                self.assertEqual(restored.execute("SELECT profile_snapshot FROM stable_externalhorse WHERE horse_id='restore-0078'").fetchone()[0], snapshot)
                self.assertEqual(restored.execute("SELECT count(*) FROM stable_externalhorsealias a JOIN stable_externalhorse h ON a.horse_id=h.id WHERE h.horse_id='restore-0078'").fetchone()[0], 1)
                self.assertEqual(restored.execute("SELECT count(*) FROM django_migrations").fetchone()[0], recorder_count)
                self.assertEqual(restored.execute("SELECT count(*) FROM django_migrations WHERE app='stable' AND name=%s", [M78[1]]).fetchone()[0], 1)
            old_name = self.empty_restore(old_dump)
            with psycopg.connect(dbname=old_name, **self.params) as restored:
                self.assertEqual(restored.execute("SELECT count(*) FROM information_schema.columns WHERE table_name='stable_externalhorse' AND column_name='profile_snapshot'").fetchone()[0], 0)
                self.assertEqual(restored.execute("SELECT count(*) FROM django_migrations WHERE app='stable' AND name=%s", [M78[1]]).fetchone()[0], 0)
            broken = Path(tmp) / "broken.dump"
            broken.write_bytes(new_dump.read_bytes()[:64])
            result = self.pg("pg_restore", "--exit-on-error", "--single-transaction", "--dbname", new_name, broken, check=False)
            self.assertNotEqual(result.returncode, 0)
            with psycopg.connect(dbname=new_name, **self.params) as restored:
                self.assertEqual(restored.execute("SELECT profile_snapshot FROM stable_externalhorse WHERE horse_id='restore-0078'").fetchone()[0], snapshot)

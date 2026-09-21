"""0079发布合同：精确代际、catalog篡改与原子升级。"""

import copy
import json
import os
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
from stable.management.commands import release_0079_schema as command
from django.test import SimpleTestCase, TransactionTestCase
from django.db import connection, DatabaseError
from django.db.migrations.executor import MigrationExecutor
from stable.services import release_0079_recovery as c
from stable.services import release_0078_recovery as old
from stable.services import release_0079_schema as schema


class Release79ContractTests(SimpleTestCase):
    def test_source_target_contract_is_exact_and_old_generation_still_refuses(self):
        self.assertEqual(c.migration_contract(), c.MIGRATION_CONTRACT_SHA256)
        with self.assertRaisesMessage(
            ValueError, "0078 migration file/content contract drift"
        ):
            old.migration_contract()
        for leaf, plan in [
            (c.SOURCE_LEAF, [c.TARGET_LEAF.split(".", 1)[1]]),
            (c.TARGET_LEAF, []),
        ]:
            value = {
                "database_identity_sha256": "b" * 64,
                "preflight": {
                    "ok": True,
                    "migration_leaf_set": [leaf],
                    "migration_plan": plan,
                    "database_identity_sha256": "b" * 64,
                },
                "writer_activity": {"ok": True},
            }
            c.validate_admission_state(value)
            for mutation in [
                ("migration_leaf_set", [old.SOURCE_LEAF]),
                ("migration_plan", ["other"]),
            ]:
                bad = copy.deepcopy(value)
                bad["preflight"][mutation[0]] = mutation[1]
                with self.assertRaises(ValueError):
                    c.validate_admission_state(bad)

    def test_all_v2_and_preview_writers_are_closed_by_control_containers(self):
        self.assertTrue(set(old.WRITER_FLAGS).issubset(c.WRITER_FLAGS))
        self.assertTrue(
            {
                "RACE_DATA_MULTISOURCE_APPLY_ENABLED",
                "RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED",
                "RACE_DATA_COVERAGE_ALERTS_ENABLED",
                "RACE_DATA_SYNC_JRA_PRE_RACE_ENABLED",
                "RACE_DATA_SYNC_PRE_RACE_REFRESH_ENABLED",
            }.issubset(c.WRITER_FLAGS)
        )

    def test_new_catalog_rejects_schema_permission_and_identity_drift(self):
        target = json.loads(schema.CATALOG_FILE.read_text())["target"]
        cases = [
            ("columns", 0, "not_null", False),
            ("constraints", 0, "validated", False),
            ("indexes", 0, "valid", False),
            ("tables", 0, "row_security", True),
            ("sequences", 0, "increment", 7),
            ("internal_triggers", 0, "enabled", "D"),
        ]
        with patch.object(
            schema.legacy,
            "validate_postgresql_catalog_contract",
            return_value={"drift_paths": []},
        ):
            for table, index, field, value in cases:
                bad = copy.deepcopy(target)
                bad[table][index][field] = value
                with self.subTest(table=table):
                    self.assertTrue(
                        schema.validate_catalog(
                            old_catalog={"columns": []},
                            delta=bad,
                            applied_nodes={c.TARGET_LEAF},
                        )
                    )
            self.assertEqual(
                schema.validate_catalog(
                    old_catalog={"columns": []},
                    delta=target,
                    applied_nodes={c.TARGET_LEAF},
                ),
                [],
            )

    def test_restore_check_normalization_accepts_only_exact_reviewed_equivalence(self):
        for row in json.loads(schema.CATALOG_FILE.read_text())["target"]["constraints"]:
            if row["name"] not in (
                "race_data_enroll_state_valid",
                "race_sync_binding_state",
            ):
                continue
            restored = {
                **row,
                "definition": row["definition"]
                .replace("::character varying", "::character varying::text")
                .replace("]::text[]", "]"),
            }
            self.assertEqual(schema.normalize_restored_checks([restored]), [row])
            for expression in (
                restored["definition"].replace(" = ", " <> "),
                restored["definition"].replace("'retired'", "'rogue'"),
            ):
                wrong = {**restored, "definition": expression}
                self.assertEqual(schema.normalize_restored_checks([wrong]), [wrong])

    def test_unknown_columns_are_not_removed_by_old_catalog_projection(self):
        target = json.loads(schema.CATALOG_FILE.read_text())["target"]
        columns = [
            {"table_name": schema.ENROLLMENT, "column_name": x}
            for x in [*schema.NEW_COLUMNS, "rogue_column"]
        ]
        original = copy.deepcopy(columns)
        with patch.object(
            schema.legacy,
            "validate_postgresql_catalog_contract",
            return_value={"drift_paths": ["old.drift"]},
        ) as validator:
            self.assertIn(
                "old.drift",
                schema.validate_catalog(
                    old_catalog={"columns": columns},
                    delta=target,
                    applied_nodes={c.TARGET_LEAF},
                ),
            )
        self.assertEqual(
            validator.call_args.kwargs["contract"]["columns"],
            [{"table_name": schema.ENROLLMENT, "column_name": "rogue_column"}],
        )
        self.assertEqual(columns, original)

    def test_old_artifact_protocol_is_never_accepted_as_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            value = {
                "schema_version": old.HANDOFF_SCHEMA,
                "target_leaf_set": [old.TARGET_LEAF],
            }
            value["artifact_sha256"] = c.digest(value)
            p = root / "handoff.json"
            c.publish_once(p, value)
            with self.assertRaisesMessage(ValueError, "0079 handoff binding mismatch"):
                c.verify_admission(p, value["artifact_sha256"], {})

    def test_read_write_file_safety_stays_shared_with_reviewed_old_contract(self):
        self.assertIs(c.read_json, old.read_json)
        self.assertIs(c.publish_once, old.publish_once)
        self.assertIs(c.file_evidence, old.file_evidence)


class Release79ComposeTests(SimpleTestCase):
    def test_effective_configuration_freezes_non_boolean_scope_and_mounts(self):
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "release79_config_test", root / "deploy/release_0079.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = dict(
            name="isolated0079",
            services={
                k: dict(
                    environment={
                        "RACE_LIVE_ENABLED_REGIONS": "britain",
                        "RACE_DATA_SYNC_SOURCE_REGISTRY_SHA256": "a" * 64,
                    },
                    volumes=[{"source": "/isolated/runtime", "target": "/app/runtime"}],
                )
                for k in c.SERVICES
                if k != "nginx"
            },
        )
        with patch.object(
            module, "compose", return_value=json.dumps(config)
        ), patch.object(module, "config_sha", return_value="b" * 64):
            project, flags, effective = module.release_config({})
            manifest = dict(
                compose_project=project,
                writer_flags=flags,
                effective_compose_sha256=effective,
                config_sha256="b" * 64,
            )
            module.verify_release_config({}, manifest)
        for key, value in (
            ("RACE_LIVE_ENABLED_REGIONS", "britain,ireland"),
            ("RACE_DATA_SYNC_SOURCE_REGISTRY_SHA256", "c" * 64),
        ):
            changed = copy.deepcopy(config)
            for service in changed["services"].values():
                service["environment"][key] = value
            with self.subTest(key=key), patch.object(
                module, "compose", return_value=json.dumps(changed)
            ), patch.object(module, "config_sha", return_value="b" * 64):
                with self.assertRaisesMessage(
                    ValueError, "effective Compose/configuration differs"
                ):
                    module.verify_release_config({}, manifest)
        changed = copy.deepcopy(config)
        changed["services"]["web"]["volumes"][0]["source"] = "/different/runtime"
        with patch.object(
            module, "compose", return_value=json.dumps(changed)
        ), patch.object(module, "config_sha", return_value="b" * 64):
            with self.assertRaises(ValueError):
                module.verify_release_config({}, manifest)


class Release79ArtifactTests(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "release-0079-recovery"
        self.root.mkdir(mode=0o700)
        self.release_id = "a" * 64
        self.directory = self.root / self.release_id
        self.directory.mkdir(mode=0o700)
        backup_dir = self.directory / "backup"
        backup_dir.mkdir(mode=0o700)
        self.backup = backup_dir / "synthetic.dump"
        self.backup.write_bytes(b"synthetic; actual PG16 restore tested separately")
        self.backup.chmod(0o600)
        self.bound = dict(
            release_id=self.release_id,
            origin_handoff_sha256=self.release_id,
            candidate_commit="b" * 40,
            candidate_image_id="sha256:" + "c" * 64,
            database_identity_sha256="d" * 64,
            compose_file="docker-compose.prod.lowcost.yml",
        )
        self.services = {s: s in {"web", "worker", "beat", "nginx"} for s in c.SERVICES}
        self.manifest = dict(
            schema_version=c.MANIFEST_SCHEMA,
            **self.bound,
            source_leaf=c.SOURCE_LEAF,
            target_leaf=c.TARGET_LEAF,
            operation="upgrade",
            migration_contract_sha256=c.MIGRATION_CONTRACT_SHA256,
            backup_path=str(self.backup),
            backup_file=c.file_evidence(self.backup)[1],
            pg_restore_list_sha256="e" * 64,
            pg_restore_list_line_count=3,
            restore_services=self.services,
            config_sha256="f" * 64,
            initial_lock_sha256="1" * 64,
            compose_project="isolated0079",
            effective_compose_sha256="2" * 64,
        )
        self.path = self.directory / "manifest.json"
        self.sha = c.publish_once(self.path, self.manifest)["sha256"]

    def test_manifest_binds_bytes_file_identity_source_and_candidate(self):
        c.verify_manifest(self.path, self.sha, self.bound)
        for key, value in (
            ("database_identity_sha256", "0" * 64),
            ("candidate_commit", "0" * 40),
            ("source_leaf", c.TARGET_LEAF),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                c.verify_manifest(self.path, self.sha, {**self.bound, key: value})
        replacement = self.backup.with_suffix(".replacement")
        replacement.write_bytes(self.backup.read_bytes())
        replacement.chmod(0o600)
        os.replace(replacement, self.backup)
        with self.assertRaisesMessage(
            ValueError, "backup bytes or file identity changed"
        ):
            c.verify_manifest(self.path, self.sha, self.bound)

    def test_intent_active_pointer_is_immutable_and_source_bound(self):
        payload = dict(
            schema_version=c.INTENT_SCHEMA,
            **self.bound,
            manifest_sha256=self.sha,
            source_leaf=c.SOURCE_LEAF,
            restore_services=self.services,
            config_sha256="f" * 64,
            initial_lock_sha256="1" * 64,
        )
        path = self.directory / "intent.json"
        identity = c.publish_once(path, payload)
        c.publish_once(
            self.root / "active.json",
            dict(
                release_id=self.release_id, intent_path=str(path), intent_file=identity
            ),
        )
        c.verify_intent(path, identity["sha256"], self.bound)
        replacement = path.with_suffix(".replacement")
        c.publish_once(replacement, payload)
        os.replace(replacement, path)
        with self.assertRaisesMessage(ValueError, "active pointer identity mismatch"):
            c.verify_intent(path, identity["sha256"], self.bound)

    def test_same_schema_backup_still_required_and_old_manifest_rejected(self):
        self.path.unlink()
        value = {
            **self.manifest,
            "source_leaf": c.TARGET_LEAF,
            "operation": "same-schema",
        }
        sha = c.publish_once(self.path, value)["sha256"]
        c.verify_manifest(self.path, sha, self.bound)
        self.backup.unlink()
        with self.assertRaises((OSError, ValueError)):
            c.verify_manifest(self.path, sha, self.bound)
        with self.assertRaises(ValueError):
            c.verify_manifest(self.path, sha, {"schema_version": old.MANIFEST_SCHEMA})


class Release79MarkerTests(SimpleTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root.chmod(0o700)
        self.path = self.root / "restricted-recovery.json"
        self.manifest = {"source_leaf": c.SOURCE_LEAF}
        self.live = {"migration_leaf_set": [c.SOURCE_LEAF]}
        self.artifact = {
            "release_0079_recovery_binding_mode": "bound",
            "candidate_commit": "a" * 40,
            "candidate_image_id": "sha256:" + "b" * 64,
            "database_identity_sha256": "c" * 64,
            "release_0079_recovery_origin_handoff_sha256": "d" * 64,
            "release_0079_recovery_manifest_sha256": "e" * 64,
            "release_0079_intent_sha256": "f" * 64,
        }
        self.stack.enter_context(
            patch.object(
                command,
                "verify_artifact",
                return_value=(self.artifact, self.live, self.manifest),
            )
        )
        self.stack.enter_context(
            patch.object(command, "marker_path", return_value=self.path)
        )
        self.command = command.Command()

    def ensure(self):
        result = self.command.perform("ensure")
        return result["marker_device"], result["marker_inode"]

    def test_source_upgrade_complete_and_receipt_resume(self):
        identity = self.ensure()
        self.assertEqual(self.ensure(), identity)
        self.live["migration_leaf_set"] = [c.TARGET_LEAF]
        self.command.perform("complete", expected_identity=identity)
        self.assertFalse(self.path.exists())
        self.assertIsNotNone(
            c.completed_marker(self.root, c.marker_binding(self.artifact))
        )
        with self.assertRaisesMessage(ValueError, "completion already exists"):
            self.ensure()

    def test_lost_marker_after_ddl_is_rejected(self):
        self.live["migration_leaf_set"] = [c.TARGET_LEAF]
        with self.assertRaisesMessage(
            ValueError, "missing marker after source leaf changed"
        ):
            self.ensure()
        self.assertFalse(self.path.exists())

    def test_same_schema_release_has_its_own_valid_source(self):
        self.manifest["source_leaf"] = c.TARGET_LEAF
        self.live["migration_leaf_set"] = [c.TARGET_LEAF]
        self.command.perform("complete", expected_identity=self.ensure())
        self.assertIsNotNone(
            c.completed_marker(self.root, c.marker_binding(self.artifact))
        )

    def test_same_content_inode_replacement_cannot_complete(self):
        identity = self.ensure()
        replacement = self.root / "replacement.json"
        c.publish_once(replacement, c.read_json(self.path)[0])
        os.replace(replacement, self.path)
        self.live["migration_leaf_set"] = [c.TARGET_LEAF]
        with self.assertRaisesMessage(ValueError, "marker changed since ensure"):
            self.command.perform("complete", expected_identity=identity)
        self.assertTrue(self.path.exists())

    def test_completion_requires_identity_and_exact_target(self):
        identity = self.ensure()
        with self.assertRaisesMessage(ValueError, "exact target schema"):
            self.command.perform("complete", expected_identity=identity)
        self.live["migration_leaf_set"] = [c.TARGET_LEAF]
        with self.assertRaisesMessage(ValueError, "requires ensure marker identity"):
            self.command.perform("complete")

    def test_source_mismatch_and_another_release_marker_are_rejected(self):
        self.ensure()
        self.manifest["source_leaf"] = c.TARGET_LEAF
        with self.assertRaisesMessage(
            ValueError, "source differs from original backup"
        ):
            self.ensure()
        self.manifest["source_leaf"] = c.SOURCE_LEAF
        self.artifact["release_0079_intent_sha256"] = "1" * 64
        with self.assertRaisesMessage(ValueError, "differs from this release"):
            self.ensure()


class Release79PostgresTests(TransactionTestCase):
    databases = {"default"}

    def test_atomic_upgrade_retries_after_lock_timeout_and_validates_real_catalog(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires isolated PostgreSQL")
        import psycopg

        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA release79_upgrade_test")
            cursor.execute("SET search_path TO release79_upgrade_test")
        blocker = None
        try:
            source = ("stable", c.SOURCE_LEAF.split(".", 1)[1])
            target = ("stable", c.TARGET_LEAF.split(".", 1)[1])
            executor = MigrationExecutor(connection)
            executor.migrate([source])
            self.assertEqual(
                schema.schema_state()["migration_leaf_set"], [c.SOURCE_LEAF]
            )
            state = executor.loader.project_state([source]).apps
            event = state.get_model("stable", "RaceEvent").objects.create(
                slug="release79-defaults", original_name="Release test", year=2026
            )
            identity = state.get_model(
                "stable", "RaceResultSourceIdentity"
            ).objects.create(event=event, source_key="the_racing_api")
            enrollment = state.get_model(
                "stable", "RaceDataSyncEnrollment"
            ).objects.create(
                event=event,
                source_identity=identity,
                state="enrolled",
                enrollment_generation=3,
                projection_owner_generation=4,
            )
            db = connection.settings_dict
            self.assertIn(db["HOST"], ("127.0.0.1", "localhost", "::1"))
            self.assertTrue(db["NAME"].startswith("test_"))
            pg_bin = Path("/opt/homebrew/opt/postgresql@16/bin")
            dump = shutil.which("pg_dump") or str(pg_bin / "pg_dump")
            restore = shutil.which("pg_restore") or str(pg_bin / "pg_restore")
            pg_env = {**os.environ, "PGPASSWORD": db["PASSWORD"]}
            pg_args = ["-h", db["HOST"], "-p", str(db["PORT"]), "-U", db["USER"]]
            snapshot = subprocess.run(
                [
                    dump,
                    *pg_args,
                    "-Fc",
                    "--no-owner",
                    "--no-acl",
                    "-n",
                    "release79_upgrade_test",
                    db["NAME"],
                ],
                env=pg_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            ).stdout
            self.assertTrue(snapshot.startswith(b"PGDMP"))
            blocker = psycopg.connect(
                dbname=db["NAME"],
                user=db["USER"],
                password=db["PASSWORD"],
                host=db["HOST"],
                port=db["PORT"],
            )
            blocker.execute(
                "LOCK TABLE release79_upgrade_test.stable_racedatasyncenrollment IN ACCESS EXCLUSIVE MODE"
            )
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout='100ms'")
            with self.assertRaises(DatabaseError):
                MigrationExecutor(connection).migrate([target])
            blocker.rollback()
            blocker.close()
            blocker = None
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout='5s'")
            self.assertEqual(
                schema.schema_state()["migration_leaf_set"], [c.SOURCE_LEAF]
            )
            MigrationExecutor(connection).migrate([target])
            self.assertEqual(
                schema.schema_state()["migration_leaf_set"], [c.TARGET_LEAF]
            )
            MigrationExecutor(connection).migrate([target])
            self.assertEqual(schema.schema_state()["migration_plan"], [])
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT authority_version,source_set_generation,source_set_digest,source_set_manifest,enrollment_generation,projection_owner_generation FROM stable_racedatasyncenrollment WHERE id=%s",
                    [enrollment.pk],
                )
                self.assertEqual(cursor.fetchone(), (1, 0, "", "{}", 3, 4))
                cursor.execute(
                    "ALTER TABLE stable_raceeventidentitykey DROP CONSTRAINT uq_race_identity_key"
                )
            with self.assertRaisesMessage(ValueError, "0079 catalog drift"):
                schema.schema_state()
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE stable_raceeventidentitykey ADD CONSTRAINT uq_race_identity_key UNIQUE(namespace,key_sha256)"
                )
            self.assertTrue(schema.schema_state()["ok"])
            for table in ("stable_raceeventidentitykey", "stable_raceevent"):
                with connection.cursor() as cursor:
                    cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER ALL")
                try:
                    with self.assertRaisesMessage(ValueError, "0079 catalog drift"):
                        schema.schema_state()
                finally:
                    with connection.cursor() as cursor:
                        cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER ALL")
            self.assertTrue(schema.schema_state()["ok"])
            # 在隔离schema真实还原原0078备份，验证老登记及代际，不触及生产。
            with connection.cursor() as cursor:
                cursor.execute("SET search_path TO public")
                cursor.execute("DROP SCHEMA release79_upgrade_test CASCADE")
            subprocess.run(
                [
                    restore,
                    *pg_args,
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                    "-d",
                    db["NAME"],
                ],
                env=pg_env,
                input=snapshot,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            with connection.cursor() as cursor:
                cursor.execute("SET search_path TO release79_upgrade_test")
                cursor.execute(
                    "SELECT enrollment_generation,projection_owner_generation FROM stable_racedatasyncenrollment WHERE id=%s",
                    [enrollment.pk],
                )
                self.assertEqual(cursor.fetchone(), (3, 4))
            self.assertEqual(
                schema.schema_state()["migration_leaf_set"], [c.SOURCE_LEAF]
            )
            MigrationExecutor(connection).migrate([target])
            self.assertTrue(schema.schema_state()["ok"])
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO django_migrations(app,name,applied) VALUES('stable','0080_unknown',now())"
                )
            with self.assertRaises(ValueError):
                schema.schema_state()
        finally:
            if blocker is not None:
                blocker.rollback()
                blocker.close()
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout='0'")
                cursor.execute("SET search_path TO public")
                cursor.execute("DROP SCHEMA release79_upgrade_test CASCADE")

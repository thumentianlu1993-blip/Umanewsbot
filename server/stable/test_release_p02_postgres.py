"""真实PG16的P02迁移与崩溃测试；恢复凭据夹具仅用于测试DDL入口。"""

from datetime import date
import json
import os
from pathlib import Path
import tempfile
import shutil
import socket
import subprocess
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg import sql
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings

from stable.services import release_p02_recovery as c
from stable.services import release_p02_schema as schema
from stable.services import release_p02_executor as engine


class InjectedCrash(RuntimeError):
    pass


class ReleaseP02PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        conf = connection.settings_dict
        if (connection.vendor != "postgresql" or conf["HOST"] != "127.0.0.1"
                or not (conf["NAME"] in {"bounded_ci", "release_p02_catalog_source"}
                        or conf["NAME"].startswith("test_"))):
            raise RuntimeError("P02 tests require an isolated loopback test database")
        cls.original = conf["NAME"]
        cls.params = {"host": conf["HOST"], "port": conf["PORT"], "user": conf["USER"], "password": conf["PASSWORD"]}
        cls.admin = psycopg.connect(dbname="postgres", autocommit=True, **cls.params)
        cls.template = "test_p02_template_" + uuid.uuid4().hex
        cls.admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.template)))
        connection.close()
        conf["NAME"] = cls.template
        try:
            executor = MigrationExecutor(connection)
            targets = [n for n in executor.loader.graph.leaf_nodes() if n[0] != "stable"]
            targets.append(("stable", c.SOURCE))
            executor.migrate(targets)
            apps = executor.loader.project_state(targets).apps
            event = apps.get_model("stable", "RaceEvent").objects.create(
                year=2026, slug="p02-synthetic", original_name="P02合成恢复测试", local_date=date(2026, 10, 1))
            source = apps.get_model("stable", "RaceResultSourceIdentity").objects.create(event=event, source_key="test", external_race_id="synthetic")
            apps.get_model("stable", "RaceResultObservation").objects.create(source_identity=source,
                parser_version="synthetic", raw_sha256="1" * 64, normalized_sha256="2" * 64,
                result_phase="official", normalized_payload={"synthetic": True})
            schema.state()
        finally:
            connection.close()
            conf["NAME"] = cls.original

    @classmethod
    def tearDownClass(cls):
        connection.close()
        connection.settings_dict["NAME"] = cls.original
        cls.admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.template)))
        cls.admin.close()
        super().tearDownClass()

    def setUp(self):
        self.name = "test_p02_case_" + uuid.uuid4().hex
        self.admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(self.name), sql.Identifier(self.template)))
        connection.close()
        connection.settings_dict["NAME"] = self.name
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name).resolve()
        self.directory.chmod(0o700)
        self.flags = override_settings(**{key: False for key in engine.WRITER_FLAGS}, RACE_LIFECYCLE_V2_EVENT_IDS=())
        self.flags.enable()
        self.initial = schema.state()
        self.bindings = {
            "candidate_commit": "a" * 40, "candidate_image_id": "sha256:" + "b" * 64,
            "database_identity_sha256": self.initial["database_identity_sha256"],
            "config_sha256": "d" * 64, "migration_contract_sha256": c.migration_contract(),
        }
        self.prepare_test_receipts()

    def tearDown(self):
        self.flags.disable()
        connection.close()
        connection.settings_dict["NAME"] = self.original
        self.admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.name)))
        self.temp.cleanup()

    def prepare_test_receipts(self):
        # 明确合成：真实pg_dump/restore由独立恢复测试覆盖，不伪装成生产证明。
        backup_dir = c.private_directory(self.directory / "backup")
        identity = c.write_artifact(self.directory / "intent.json", kind="intent", **self.bindings,
            source=c.SOURCE, migration_plan=list(c.STEPS), backup_directory=str(backup_dir),
            source_catalog_sha256=self.initial["catalog_sha256"],
            p02_write=False, p02_delivery=False, cohort=[])
        self.intent_sha = identity["sha256"]
        counts_sha = c.digest(schema.counts())
        closed = c.write_artifact(self.directory / "closed.json", kind="closed", intent_sha=self.intent_sha,
            services_stopped=True, clients=0, source_counts_sha256=counts_sha,
            source_catalog_sha256=self.initial["catalog_sha256"], source_security_sha256=schema.security_snapshot())
        files = {}
        for name in ("database.dump", "roles.sql", "config.tar", "assets.tar", "images.tar"):
            path = backup_dir / name
            path.write_bytes(b"explicitly synthetic unit test artifact")
            path.chmod(0o600)
            files[name] = c.file_evidence(path)[1]
        backup = c.write_artifact(self.directory / "backup.json", kind="backup", intent_sha=self.intent_sha,
            source_catalog_sha256=self.initial["catalog_sha256"], source_counts_sha256=counts_sha,
            closed_sha256=closed["sha256"], files=files,
            restore={"status": "verified", "catalog_sha256": self.initial["catalog_sha256"],
                     "counts_sha256": counts_sha, "database_identity_sha256": "e" * 64, "security_sha256": schema.security_snapshot()})
        c.write_artifact(self.directory / "handoff.json", kind="handoff", intent_sha=self.intent_sha,
            backup_sha256=backup["sha256"], closed_sha256=closed["sha256"])

    def apply(self, **kwargs):
        return engine.apply(self.directory, self.intent_sha, self.bindings, **kwargs)

    def test_six_atomic_steps_preserve_old_observations_and_repeat_is_noop(self):
        result = self.apply()
        self.assertEqual(result["status"], "schema-complete")
        self.assertEqual(len(result["timings"]), 6)
        with connection.cursor() as q:
            q.execute("SELECT acquisition_key,normalized_payload FROM stable_raceresultobservation")
            key, payload = q.fetchone()
            self.assertEqual(key, "")
            self.assertEqual(json.loads(payload) if isinstance(payload, str) else payload, {"synthetic": True})
        self.assertEqual(self.apply()["timings"], [])

    def test_unmarked_forward_migration_cannot_be_adopted(self):
        MigrationExecutor(connection).migrate([("stable", c.STEPS[0])])
        with self.assertRaisesRegex(ValueError, "original step intent"):
            self.apply()
        self.assertFalse((self.directory / "schema-complete.json").exists())

    def test_wrong_database_identity_does_not_write_any_step(self):
        self.bindings["database_identity_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "binding"):
            self.apply()
        self.assertEqual(schema.state()["prefix"], 0)
        self.assertFalse((self.directory / "step-1.json").exists())

    def test_resident_client_and_other_coordinator_are_rejected(self):
        other = psycopg.connect(dbname=self.name, autocommit=True, **self.params)
        try:
            with self.assertRaisesRegex(ValueError, "other database clients"):
                self.apply()
            other.execute("SELECT pg_advisory_lock(%s)", (engine.LOCK_KEY,))
            with self.assertRaisesRegex(ValueError, "already holds"):
                self.apply()
        finally:
            other.close()
        self.assertEqual(schema.state()["prefix"], 0)

    def test_backup_byte_tamper_is_detected_before_ddl(self):
        path = self.directory / "backup/database.dump"
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "backup bytes"):
            self.apply()
        self.assertEqual(schema.state()["prefix"], 0)

    def test_missing_restore_proof_is_not_replaced_by_toc_success(self):
        path = self.directory / "backup.json"
        value = json.loads(path.read_text())
        value["restore"] = {"toc_ok": True}
        path.write_bytes(c.encoded(value))
        with self.assertRaisesRegex(ValueError, "complete isolated restore"):
            self.apply()
        self.assertEqual(schema.state()["prefix"], 0)

    def test_catalog_extra_column_and_disabled_trigger_are_rejected(self):
        with connection.cursor() as q:
            q.execute("ALTER TABLE stable_raceresultobservation ADD COLUMN unreviewed text")
        with self.assertRaisesRegex(ValueError, "catalog drift"):
            self.apply()
        with connection.cursor() as q:
            q.execute("ALTER TABLE stable_raceresultobservation DROP COLUMN unreviewed")
        self.apply()
        with connection.cursor() as q:
            q.execute("ALTER TABLE stable_racelifecyclereceipt DISABLE TRIGGER lifecycle_evidence_immutable")
        with self.assertRaisesRegex(ValueError, "catalog drift"):
            self.apply()

    def test_changed_function_body_is_rejected_even_with_same_trigger_name(self):
        self.apply()
        with connection.cursor() as q:
            q.execute("CREATE OR REPLACE FUNCTION stable_lifecycle_evidence_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$")
        with self.assertRaisesRegex(ValueError, "catalog drift"):
            schema.state()

    def test_each_control_writer_flag_and_cohort_blocks_ddl(self):
        for key in engine.WRITER_FLAGS:
            with self.subTest(flag=key), override_settings(**{key: True}), self.assertRaisesRegex(ValueError, "enabled writer"):
                self.apply()
        with override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(1,)), self.assertRaisesRegex(ValueError, "empty cohort"):
            self.apply()

    def test_actual_ddl_lock_timeout_rolls_back_only_current_step(self):
        blocker = None
        def block(stage):
            nonlocal blocker
            if stage == "before-5":
                blocker = psycopg.connect(dbname=self.name, **self.params)
                blocker.execute("LOCK TABLE stable_raceresultobservation IN ACCESS EXCLUSIVE MODE")
        try:
            from django.db import OperationalError
            with self.assertRaises(OperationalError):
                self.apply(checkpoint=block)
        finally:
            if blocker:
                blocker.close()
        self.assertEqual(schema.state()["prefix"], 4)
        self.assertFalse((self.directory / "step-5-complete.json").exists())
        self.apply()
        self.assertEqual(schema.state()["prefix"], 6)

    def test_same_row_count_mutation_after_backup_is_rejected(self):
        with connection.cursor() as q:
            q.execute("UPDATE stable_raceresultobservation SET parser_version='changed'")
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.apply()
        self.assertFalse((self.directory / "step-1.json").exists())

    def test_permission_mutation_after_backup_is_rejected(self):
        with connection.cursor() as q:
            q.execute("GRANT SELECT ON stable_raceresultobservation TO PUBLIC")
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.apply()
        self.assertFalse((self.directory / "step-1.json").exists())

    def test_recorder_sequence_cannot_reissue_existing_id(self):
        with connection.cursor() as q:
            q.execute("SELECT setval('django_migrations_id_seq', (SELECT max(id) FROM django_migrations), false)")
        with self.assertRaisesRegex(ValueError, "recorder sequence"):
            schema.counts()

    def test_null_and_empty_function_acl_are_distinct(self):
        with connection.cursor() as q:
            q.execute("CREATE FUNCTION public.p02_test_acl() RETURNS integer LANGUAGE sql AS 'SELECT 1'")
        before = schema.security_snapshot()
        with connection.cursor() as q:
            q.execute("REVOKE ALL ON FUNCTION public.p02_test_acl() FROM PUBLIC")
            q.execute("REVOKE ALL ON FUNCTION public.p02_test_acl() FROM CURRENT_USER")
        self.assertNotEqual(schema.security_snapshot(), before)

    def test_role_inherit_and_set_options_are_in_security_snapshot(self):
        role = "pgapp_" + uuid.uuid4().hex
        member = "pgworker_" + uuid.uuid4().hex
        self.admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        self.admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(member)))
        try:
            self.admin.execute(sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET TRUE").format(sql.Identifier(role), sql.Identifier(member)))
            role_state = schema.security_state()
            self.assertIn(role, [r["rolname"] for r in role_state["roles"]])
            self.assertIn("pg_read_all_stats", [r["rolname"] for r in role_state["roles"]])
            self.assertEqual([r["grantor"] for r in role_state["membership"] if r["role"] == role], [self.params["user"]])
            before = schema.security_snapshot()
            self.admin.execute(sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(sql.Identifier(role), sql.Identifier(member)))
            after_inherit = schema.security_snapshot()
            self.assertNotEqual(before, after_inherit)
            self.admin.execute(sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET FALSE").format(sql.Identifier(role), sql.Identifier(member)))
            self.assertNotEqual(after_inherit, schema.security_snapshot())
        finally:
            self.admin.execute(sql.SQL("DROP ROLE {}, {}").format(sql.Identifier(role), sql.Identifier(member)))

    def test_real_dump_restore_preserves_roles_permissions_data_and_catalog(self):
        from stable.management.commands.release_p02 import security_snapshot
        role = "pgapp_restore_" + uuid.uuid4().hex
        member = "pgworker_restore_" + uuid.uuid4().hex
        self.admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        with connection.cursor() as q:
            quoted = connection.ops.quote_name(role)
            q.execute(f"GRANT SELECT ON stable_raceresultobservation TO {quoted}")
            q.execute(f"ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO {quoted}")
        self.admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(member)))
        self.admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(role), sql.Identifier(member)))
        source_security = schema.security_state()
        source = {"catalog": schema.state()["catalog_sha256"], "counts": c.digest(schema.counts()),
                  "security": security_snapshot(), "identity": schema.database_identity()}
        saved = dict(connection.settings_dict)
        started = False
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            restore_admin = schema.bootstrap_role()
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            binaries = {name: shutil.which(name) for name in ("initdb", "pg_ctl", "pg_dump", "pg_dumpall", "pg_restore", "psql")}
            self.assertTrue(all(binaries.values()), "isolated PG16 runtime must include backup/restore tools")
            def run(name, *args, env=None):
                result = subprocess.run([binaries[name], *map(str, args)], capture_output=True,
                    timeout=120, env=env or os.environ)
                if result.returncode:
                    errors = [line.split("ERROR:", 1)[1] for line in result.stderr.decode().splitlines() if "ERROR:" in line]
                    raise RuntimeError(name + ": " + ";".join(errors))
                return result
            original_args = ["-h", "127.0.0.1", "-p", saved["PORT"], "-U", saved["USER"]]
            restore_args = ["-h", "127.0.0.1", "-p", str(port), "-U", restore_admin]
            try:
                run("initdb", "-D", root / "pg", "--encoding=UTF8", "--locale=C", "-U", restore_admin, "--auth=trust")
                run("pg_ctl", "-D", root / "pg", "-l", root / "pg.log", "-o", f"-h 127.0.0.1 -p {port} -k {root}", "start")
                started = True
                env = {**os.environ, "PGPASSWORD": saved["PASSWORD"]}
                run("pg_dump", *original_args, "-d", self.name, "-Fc", "--create", "-f", root / "database.dump", env=env)
                run("pg_dumpall", *original_args, "--roles-only", "-f", root / "roles.sql", env=env)
                (root / "restore-roles.sql").write_bytes(c.restore_roles_sql((root / "roles.sql").read_bytes(), restore_admin))
                run("psql", *restore_args, "-X", "-v", "ON_ERROR_STOP=1", "-d", "postgres", "-f", root / "restore-roles.sql")
                run("pg_restore", *restore_args, "--exit-on-error", "--create", "--role", saved["USER"], "-d", "postgres", root / "database.dump")
                connection.close()
                connection.settings_dict.update(PORT=str(port), USER=restore_admin, PASSWORD="")
                with patch.dict(os.environ, {}):
                    self.assertEqual(schema.state()["catalog_sha256"], source["catalog"])
                    self.assertEqual(c.digest(schema.counts()), source["counts"])
                    restored_security = schema.security_state()
                    for key in source_security:
                        self.assertEqual(c.digest(restored_security[key]), c.digest(source_security[key]), key)
                    self.assertEqual(security_snapshot(), source["security"])
                    self.assertNotEqual(schema.database_identity(), source["identity"])
                # 从恢复库继续跑同一六步DDL，混合原始/恢复约束表达式也必须通过。
                for step in c.STEPS:
                    MigrationExecutor(connection).migrate([("stable", step)])
                    schema.state()
            finally:
                connection.close()
                connection.settings_dict.clear()
                connection.settings_dict.update(saved)
                if started:
                    run("pg_ctl", "-D", root / "pg", "-m", "fast", "stop")
                with connection.cursor() as q:
                    q.execute(f"DROP OWNED BY {quoted}")
                self.admin.execute(sql.SQL("DROP ROLE {}, {}").format(sql.Identifier(role), sql.Identifier(member)))


def crash_test(stage, index):
    def test(self):
        def crash(observed):
            if observed == f"{stage}-{index}":
                raise InjectedCrash(observed)
        with self.assertRaises(InjectedCrash):
            self.apply(checkpoint=crash)
        expected = index if stage in {"committed", "receipted"} else index - 1
        self.assertEqual(schema.state()["prefix"], expected)
        self.assertFalse((self.directory / "schema-complete.json").exists())
        self.apply()
        self.assertEqual(schema.state()["prefix"], 6)
        self.assertEqual(c.verify_journal(self.directory, self.intent_sha, 6), 6)
    return test


for _stage in ("before", "inside", "committed", "receipted"):
    for _index in range(1, 7):
        setattr(ReleaseP02PostgresTests, f"test_crash_{_stage}_{_index}", crash_test(_stage, _index))

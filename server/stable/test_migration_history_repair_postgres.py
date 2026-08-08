from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.core.management import CommandError, call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase, TransactionTestCase

from stable.services.historical_calendar_release_b_schema import (
    check_initial_install_schema_compatibility,
    check_release_b_schema_compatibility,
    collect_live_production_audit,
    collect_postgresql_catalog_contract,
    validate_postgresql_catalog_contract,
)
from stable.services.historical_calendar_release_b_handoff import (
    build_preflight_artifact,
    build_restricted_recovery_marker,
    publish_preflight_artifact,
    publish_restricted_recovery_marker,
)


M0067 = ("stable", "0067_historical_calendar_release_a")
M0068 = ("stable", "0068_race_data_sync_pipeline_a_field_audit")
M0069 = ("stable", "0069_race_data_sync_pipeline_a_ledger_guards")
M0070 = ("stable", "0070_horse_identity_evidence_commit_receipt")
M0071 = ("stable", "0071_historical_calendar_release_b")
POSTGRES = connection.vendor == "postgresql"


def _executor() -> MigrationExecutor:
    return MigrationExecutor(connection)


def _stable_plan(executor: MigrationExecutor) -> list[str]:
    return [
        migration.name
        for migration, backwards in executor.migration_plan([M0071])
        if migration.app_label == "stable" and not backwards and migration.name >= "0068"
    ]


@skipUnless(POSTGRES, "requires PostgreSQL pg_catalog and transactional DDL")
class MigrationHistoryRepairPostgresMigrationTests(TransactionTestCase):
    reset_sequences = False

    def tearDown(self):
        # Never leave the shared Django test database at a partial migration leaf.
        _executor().migrate([M0071])
        super().tearDown()

    def test_initial_install_exact_origin_and_monotonic_prefixes_have_exact_catalogs(self):
        _executor().migrate([M0067])
        origin = check_initial_install_schema_compatibility()
        self.assertTrue(origin["ok"], origin)
        self.assertTrue(origin["initial_install_origin"])
        self.assertEqual(
            origin["migration_plan"],
            [M0070[1], M0068[1], M0069[1], M0071[1]],
        )

        _executor().migrate([M0068, M0070])
        after_0068 = check_initial_install_schema_compatibility()
        self.assertTrue(after_0068["ok"], after_0068)
        self.assertEqual(
            after_0068["migration_leaf_set"],
            [f"{M0068[0]}.{M0068[1]}", f"{M0070[0]}.{M0070[1]}"],
        )

        _executor().migrate([M0069, M0070])
        partial = check_initial_install_schema_compatibility()
        self.assertTrue(partial["ok"], partial)
        self.assertEqual(
            partial["migration_leaf_set"],
            [f"{M0069[0]}.{M0069[1]}", f"{M0070[0]}.{M0070[1]}"],
        )

        _executor().migrate([M0071])
        final = check_initial_install_schema_compatibility()
        self.assertTrue(final["ok"], final)

    def test_missing_early_dependency_record_is_structured_and_command_fails(self):
        _executor().migrate([M0070])
        recorder = MigrationRecorder(connection)
        early = ("stable", "0066_add_term_consistency_manifest")
        recorder.record_unapplied(*early)
        try:
            result = check_release_b_schema_compatibility(direction="forward")
            self.assertFalse(result["ok"])
            self.assertFalse(result["migration_history_consistent"])
            self.assertIn("migration.history_consistency", result["drift_paths"])
            self.assertEqual(result["migration_leaf_set"], [])
            output = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "check_historical_calendar_release_b_schema",
                    direction="forward",
                    json_output=True,
                    stdout=output,
                )
            payload = json.loads(output.getvalue())
            self.assertIn("migration.history_consistency", payload["drift_paths"])
        finally:
            recorder.record_applied(*early)

    def test_pre0071_legacy_event_partial_index_contract_rejects_wrong_objects(self):
        _executor().migrate([M0067])
        drop = "DROP INDEX IF EXISTS uq_race_event_series_year"
        drop_constraint = (
            "ALTER TABLE stable_raceevent "
            "DROP CONSTRAINT IF EXISTS uq_race_event_series_year"
        )
        restore = (
            "CREATE UNIQUE INDEX uq_race_event_series_year "
            "ON stable_raceevent USING btree (race_series_id, year) "
            "WHERE race_series_id IS NOT NULL"
        )
        cases = (
            (
                "same_name_ordinary_index",
                "CREATE INDEX uq_race_event_series_year ON stable_raceevent (race_series_id, year)",
            ),
            (
                "wrong_columns",
                "CREATE UNIQUE INDEX uq_race_event_series_year ON stable_raceevent (year, race_series_id) WHERE race_series_id IS NOT NULL",
            ),
            (
                "wrong_predicate",
                "CREATE UNIQUE INDEX uq_race_event_series_year ON stable_raceevent (race_series_id, year) WHERE year IS NOT NULL",
            ),
            (
                "same_name_table_constraint",
                "ALTER TABLE stable_raceevent ADD CONSTRAINT uq_race_event_series_year UNIQUE (race_series_id, year)",
            ),
            ("missing", None),
        )
        try:
            for name, create in cases:
                with self.subTest(name=name), connection.cursor() as cursor:
                    cursor.execute(drop_constraint)
                    cursor.execute(drop)
                    if create:
                        cursor.execute(create)
                    result = check_initial_install_schema_compatibility()
                    self.assertFalse(result["ok"])
                    self.assertIn("0071.legacy_event_index", result["drift_paths"])
                    cursor.execute(drop_constraint)
                    cursor.execute(drop)
                    cursor.execute(restore)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(drop_constraint)
                cursor.execute(drop)
                cursor.execute(restore)

    def test_pre0071_legacy_target_constraint_and_backing_index_are_exact(self):
        _executor().migrate([M0067])
        drop_constraint = (
            "ALTER TABLE stable_historicalraceeventtarget "
            "DROP CONSTRAINT IF EXISTS uq_historical_target_series_year"
        )
        drop_index = "DROP INDEX IF EXISTS uq_historical_target_series_year"
        restore = (
            "ALTER TABLE stable_historicalraceeventtarget "
            "ADD CONSTRAINT uq_historical_target_series_year "
            "UNIQUE (race_series_id, year)"
        )
        cases = (
            (
                "same_name_ordinary_index",
                "CREATE UNIQUE INDEX uq_historical_target_series_year ON stable_historicalraceeventtarget (race_series_id, year)",
            ),
            (
                "wrong_column_order_constraint",
                "ALTER TABLE stable_historicalraceeventtarget ADD CONSTRAINT uq_historical_target_series_year UNIQUE (year, race_series_id)",
            ),
            ("missing", None),
        )
        try:
            for name, create in cases:
                with self.subTest(name=name), connection.cursor() as cursor:
                    cursor.execute(drop_constraint)
                    cursor.execute(drop_index)
                    if create:
                        cursor.execute(create)
                    result = check_initial_install_schema_compatibility()
                    self.assertFalse(result["ok"])
                    expected = (
                        "0071.legacy_target_constraint"
                        if name != "missing"
                        else "0071.legacy_target_constraint"
                    )
                    self.assertIn(expected, result["drift_paths"])
                    cursor.execute(drop_constraint)
                    cursor.execute(drop_index)
                    cursor.execute(restore)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(drop_constraint)
                cursor.execute(drop_index)
                cursor.execute(restore)

    def test_initial_install_empty_receipt_artifact_marker_migrate_and_atomic_completion(self):
        _executor().migrate([M0067])
        preflight = check_initial_install_schema_compatibility()
        self.assertTrue(preflight["ok"], preflight)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            artifact_path = root / "preflight.json"
            marker_path = root / "restricted-recovery.json"
            artifact = build_preflight_artifact(
                preflight=preflight,
                candidate_commit="a" * 40,
                candidate_image_id="sha256:" + "b" * 64,
                compose_file="docker-compose.prod.lowcost.yml",
                deployment_lock_token_sha256="c" * 64,
                artifact_path=str(artifact_path),
                handoff_action="initial-install",
            )
            publish_preflight_artifact(path=artifact_path, payload=artifact)
            ensure_out = StringIO()
            call_command(
                "ensure_historical_calendar_recovery_intent",
                marker_path=str(marker_path),
                artifact_path=str(artifact_path),
                artifact_sha256=artifact["artifact_sha256"],
                candidate_commit="a" * 40,
                candidate_image_id="sha256:" + "b" * 64,
                database_identity_sha256=preflight["database_identity_sha256"],
                attempt_mode="required",
                stdout=ensure_out,
            )
            identity = json.loads(ensure_out.getvalue())
            self.assertTrue(marker_path.exists())

            _executor().migrate([M0071])
            self.assertEqual(collect_live_production_audit()["receipt_count"], 0)
            complete_out = StringIO()
            call_command(
                "complete_historical_calendar_restricted_recovery",
                marker_path=str(marker_path),
                artifact_path=str(artifact_path),
                artifact_sha256=artifact["artifact_sha256"],
                provenance_artifact_sha256=artifact["artifact_sha256"],
                candidate_commit="a" * 40,
                candidate_image_id="sha256:" + "b" * 64,
                database_identity_sha256=preflight["database_identity_sha256"],
                attempt_mode="required",
                expected_marker_device=identity["marker_device"],
                expected_marker_inode=identity["marker_inode"],
                stdout=complete_out,
            )
            completed = Path(json.loads(complete_out.getvalue())["completed_marker"])
            self.assertFalse(marker_path.exists())
            self.assertTrue(completed.exists())

    def test_repair_origin_with_empty_receipts_fails_reviewed_static_completion(self):
        _executor().migrate([M0067])
        _executor().migrate([M0070])
        preflight = check_release_b_schema_compatibility(direction="forward")
        self.assertTrue(preflight["ok"], preflight)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            artifact_path = root / "preflight.json"
            marker_path = root / "restricted-recovery.json"
            artifact = build_preflight_artifact(
                preflight=preflight,
                candidate_commit="a" * 40,
                candidate_image_id="sha256:" + "b" * 64,
                compose_file="docker-compose.prod.lowcost.yml",
                deployment_lock_token_sha256="c" * 64,
                artifact_path=str(artifact_path),
                handoff_action="forward-resume",
            )
            publish_preflight_artifact(path=artifact_path, payload=artifact)
            marker = build_restricted_recovery_marker(
                binding={
                    "candidate_commit": "a" * 40,
                    "candidate_image_id": "sha256:" + "b" * 64,
                    "artifact_sha256": artifact["artifact_sha256"],
                    "database_identity_sha256": preflight["database_identity_sha256"],
                },
                leaf_set=[f"{M0070[0]}.{M0070[1]}"],
            )
            publish_restricted_recovery_marker(path=marker_path, marker=marker)
            info = marker_path.stat()
            _executor().migrate([M0071])
            output = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "complete_historical_calendar_restricted_recovery",
                    marker_path=str(marker_path), artifact_path=str(artifact_path),
                    artifact_sha256=artifact["artifact_sha256"],
                    provenance_artifact_sha256=artifact["artifact_sha256"],
                    candidate_commit="a" * 40,
                    candidate_image_id="sha256:" + "b" * 64,
                    database_identity_sha256=preflight["database_identity_sha256"],
                    attempt_mode="required",
                    expected_marker_device=info.st_dev,
                    expected_marker_inode=info.st_ino,
                    stdout=output,
                )
            payload = json.loads(output.getvalue())
            self.assertFalse(payload["ok"])
            self.assertIn("receipt_count", payload["production_audit_drift_fields"])
            self.assertTrue(marker_path.exists())

    def test_initial_artifact_with_repair_origin_marker_is_rejected(self):
        _executor().migrate([M0067])
        preflight = check_initial_install_schema_compatibility()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            artifact_path = root / "preflight.json"
            marker_path = root / "restricted-recovery.json"
            artifact = build_preflight_artifact(
                preflight=preflight,
                candidate_commit="a" * 40,
                candidate_image_id="sha256:" + "b" * 64,
                compose_file="docker-compose.prod.lowcost.yml",
                deployment_lock_token_sha256="c" * 64,
                artifact_path=str(artifact_path),
                handoff_action="initial-install",
            )
            publish_preflight_artifact(path=artifact_path, payload=artifact)
            _executor().migrate([M0070])
            repair_marker = build_restricted_recovery_marker(
                binding={
                    "candidate_commit": "a" * 40,
                    "candidate_image_id": "sha256:" + "b" * 64,
                    "artifact_sha256": artifact["artifact_sha256"],
                    "database_identity_sha256": preflight["database_identity_sha256"],
                },
                leaf_set=[f"{M0070[0]}.{M0070[1]}"],
            )
            publish_restricted_recovery_marker(path=marker_path, marker=repair_marker)
            info = marker_path.stat()
            _executor().migrate([M0071])
            with self.assertRaisesRegex(CommandError, "artifact/marker binding mismatch"):
                call_command(
                    "complete_historical_calendar_restricted_recovery",
                    marker_path=str(marker_path), artifact_path=str(artifact_path),
                    artifact_sha256=artifact["artifact_sha256"],
                    provenance_artifact_sha256=artifact["artifact_sha256"],
                    candidate_commit="a" * 40,
                    candidate_image_id="sha256:" + "b" * 64,
                    database_identity_sha256=preflight["database_identity_sha256"],
                    attempt_mode="required",
                    expected_marker_device=info.st_dev,
                    expected_marker_inode=info.st_ino,
                )
            self.assertTrue(marker_path.exists())

    def test_legacy_receipt_branch_runs_only_0068_0069_0071_and_preserves_rows(self):
        _executor().migrate([M0067])
        executor = _executor()
        executor.migrate([M0070])
        state_apps = executor.loader.project_state([M0070]).apps
        OperationLog = state_apps.get_model("stable", "OperationLog")
        Receipt = state_apps.get_model(
            "stable", "HorseIdentityEvidenceCommitReceipt"
        )
        operation = OperationLog.objects.create(
            action_type="migration_fixture",
            target_type="horse_identity",
            target_id="1",
            detail="legacy receipt branch",
        )
        Receipt.objects.create(
            approved_sha256="a" * 64,
            artifact_sha256="b" * 64,
            approved_by="postgres-fixture",
            approved_profile_ids=[1],
            before_after={"before": None, "after": 1},
            evidence_summary={"fixture": True},
            result_payload={"ok": True},
            operation_log_id=operation.pk,
        )
        before = collect_live_production_audit()

        executor = _executor()
        self.assertEqual(
            _stable_plan(executor),
            [M0068[1], M0069[1], M0071[1]],
        )
        self.assertNotIn(M0070[1], _stable_plan(executor))
        executor.migrate([M0071])

        self.assertEqual(collect_live_production_audit(), before)
        executor = _executor()
        self.assertEqual(_stable_plan(executor), [])
        applied = {
            f"{app}.{name}"
            for app, name in executor.loader.applied_migrations
            if app == "stable"
        }
        catalog = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(),
            applied_nodes=applied,
        )
        self.assertTrue(catalog["ok"], catalog["drift_paths"])

    def test_fresh_install_creates_receipt_once_and_second_plan_is_empty(self):
        _executor().migrate([("stable", None)])
        executor = _executor()
        executor.migrate([M0071])
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = current_schema()
                   AND c.relname = 'stable_horseidentityevidencecommitreceipt'
                   AND c.relkind = 'r'
                """
            )
            self.assertEqual(cursor.fetchone()[0], 1)
        self.assertEqual(_stable_plan(_executor()), [])

    def test_partial_states_have_exact_forward_plans_and_catalog(self):
        _executor().migrate([M0067])
        _executor().migrate([M0068, M0070])
        executor = _executor()
        self.assertEqual(_stable_plan(executor), [M0069[1], M0071[1]])
        applied = {
            f"{app}.{name}"
            for app, name in executor.loader.applied_migrations
            if app == "stable"
        }
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(), applied_nodes=applied
        )
        self.assertTrue(result["ok"], result["drift_paths"])

        executor.migrate([M0069, M0070])
        executor = _executor()
        self.assertEqual(_stable_plan(executor), [M0071[1]])
        applied = {
            f"{app}.{name}"
            for app, name in executor.loader.applied_migrations
            if app == "stable"
        }
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(), applied_nodes=applied
        )
        self.assertTrue(result["ok"], result["drift_paths"])


@skipUnless(POSTGRES, "requires PostgreSQL pg_catalog and transactional DDL")
class MigrationHistoryRepairPostgresCatalogDriftTests(TestCase):
    def setUp(self):
        super().setUp()
        self._restore_sid = connection.savepoint()

    def tearDown(self):
        # Explicitly restore destructive catalog fixtures before Django's outer
        # TestCase transaction cleanup so a failed assertion cannot poison the
        # shared PostgreSQL test schema.
        connection.savepoint_rollback(self._restore_sid)
        super().tearDown()

    def _applied(self) -> set[str]:
        return {
            f"{app}.{name}"
            for app, name in _executor().loader.applied_migrations
            if app == "stable"
        }

    def test_receipt_constraint_and_index_sets_match_fresh_postgresql(self):
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(),
            applied_nodes=self._applied(),
        )
        self.assertTrue(result["ok"], result["drift_paths"])
        self.assertNotIn("0070.constraint_set", result["drift_paths"])
        self.assertNotIn("0070.index_set", result["drift_paths"])

    def test_extra_receipt_check_constraint_is_rejected(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE stable_horseidentityevidencecommitreceipt "
                "ADD CONSTRAINT receipt_unreviewed_approved_by_check "
                "CHECK (approved_by <> '')"
            )
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(),
            applied_nodes=self._applied(),
        )
        self.assertFalse(result["ok"])
        self.assertIn("0070.constraint_set", result["drift_paths"])

    def test_extra_receipt_unique_constraint_is_rejected(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE stable_horseidentityevidencecommitreceipt "
                "ADD CONSTRAINT receipt_unreviewed_artifact_unique "
                "UNIQUE (artifact_sha256)"
            )
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(),
            applied_nodes=self._applied(),
        )
        self.assertFalse(result["ok"])
        self.assertIn("0070.constraint_set", result["drift_paths"])
        self.assertIn("0070.index_set", result["drift_paths"])

    def test_extra_receipt_index_is_rejected(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE INDEX receipt_unreviewed_artifact_idx "
                "ON stable_horseidentityevidencecommitreceipt (artifact_sha256)"
            )
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(),
            applied_nodes=self._applied(),
        )
        self.assertFalse(result["ok"])
        self.assertIn("0070.index_set", result["drift_paths"])

    def test_invalid_index_state_is_rejected(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pg_index
                   SET indisvalid = false
                 WHERE indexrelid = 'uq_race_event_series_edition'::regclass
                """
            )
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(),
            applied_nodes=self._applied(),
        )
        self.assertFalse(result["ok"])
        self.assertIn("0071.uq_race_event_series_edition", result["drift_paths"])

    def test_unready_index_state_is_rejected(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pg_index
                   SET indisready = false
                 WHERE indexrelid = 'uq_hist_target_active_series_year'::regclass
                """
            )
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(),
            applied_nodes=self._applied(),
        )
        self.assertFalse(result["ok"])
        self.assertIn("0071.uq_hist_target_active_series_year", result["drift_paths"])

    def test_non_live_index_state_is_rejected(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pg_index
                   SET indislive = false
                 WHERE indexrelid = 'uq_race_event_series_edition'::regclass
                """
            )
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(),
            applied_nodes=self._applied(),
        )
        self.assertFalse(result["ok"])
        self.assertIn("0071.uq_race_event_series_edition", result["drift_paths"])

    def test_unvalidated_receipt_fk_is_rejected(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE pg_constraint
                   SET convalidated = false
                 WHERE conrelid =
                       'stable_horseidentityevidencecommitreceipt'::regclass
                   AND contype = 'f'
                """
            )
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(),
            applied_nodes=self._applied(),
        )
        self.assertFalse(result["ok"])
        self.assertIn("0070.operation_log_fk", result["drift_paths"])

    def test_recorder_schema_mismatch_is_rejected(self):
        applied = self._applied() - {"stable.0069_race_data_sync_pipeline_a_ledger_guards"}
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(), applied_nodes=applied
        )
        self.assertFalse(result["ok"])
        self.assertIn("0069.object_presence", result["drift_paths"])

    def test_recorded_0070_missing_table_is_structured_drift_before_live_audit(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP TABLE stable_horseidentityevidencecommitreceipt CASCADE"
            )
        result = check_release_b_schema_compatibility(
            direction="forward", enforce_production_audit=True
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["receipt_audit_safe"])
        self.assertIsNone(result["production_audit_live"])
        self.assertIn("0070.table_presence", result["drift_paths"])

        output = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "check_historical_calendar_release_b_schema",
                direction="forward",
                enforce_production_audit=True,
                json_output=True,
                stdout=output,
            )
        payload = json.loads(output.getvalue().strip())
        self.assertFalse(payload["ok"])
        self.assertIn("0070.table_presence", payload["drift_paths"])

    def test_recorded_0070_missing_column_is_structured_drift_before_live_audit(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE stable_horseidentityevidencecommitreceipt "
                "DROP COLUMN artifact_sha256 CASCADE"
            )
        result = check_release_b_schema_compatibility(
            direction="forward", enforce_production_audit=True
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["receipt_audit_safe"])
        self.assertIsNone(result["production_audit_live"])
        self.assertIn("0070.columns", result["drift_paths"])

    def test_recorded_0070_wrong_column_type_is_structured_before_live_audit(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE stable_horseidentityevidencecommitreceipt "
                "ALTER COLUMN artifact_sha256 TYPE text"
            )
        result = check_release_b_schema_compatibility(
            direction="forward", enforce_production_audit=True
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["receipt_audit_safe"])
        self.assertIsNone(result["production_audit_live"])
        self.assertIn("0070.column_semantics", result["drift_paths"])

    def test_weakened_release_b_partial_index_predicates_are_rejected(self):
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX uq_race_event_series_edition")
            cursor.execute(
                """
                CREATE UNIQUE INDEX uq_race_event_series_edition
                    ON stable_raceevent (race_series_id, edition_year)
                 WHERE ((edition_year IS NOT NULL)
                    AND (race_series_id IS NOT NULL) AND false)
                """
            )
            cursor.execute("DROP INDEX uq_hist_target_active_series_year")
            cursor.execute(
                """
                CREATE UNIQUE INDEX uq_hist_target_active_series_year
                    ON stable_historicalraceeventtarget (race_series_id, year)
                 WHERE ((NOT (resolution_status = 'superseded')) OR true)
                """
            )
        result = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(),
            applied_nodes=self._applied(),
        )
        self.assertFalse(result["ok"])
        self.assertIn("0071.uq_race_event_series_edition", result["drift_paths"])
        self.assertIn("0071.uq_hist_target_active_series_year", result["drift_paths"])

    def test_release_b_unique_indexes_on_wrong_table_are_rejected_and_restored(self):
        wrong_table = "migration_repair_wrong_index_owner"
        with connection.cursor() as cursor:
            try:
                cursor.execute("DROP INDEX uq_race_event_series_edition")
                cursor.execute("DROP INDEX uq_hist_target_active_series_year")
                cursor.execute(
                    f"""
                    CREATE TABLE {wrong_table} (
                        race_series_id bigint,
                        edition_year smallint,
                        year smallint,
                        resolution_status varchar(32)
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE UNIQUE INDEX uq_race_event_series_edition
                        ON {wrong_table} (race_series_id, edition_year)
                     WHERE ((edition_year IS NOT NULL)
                        AND (race_series_id IS NOT NULL))
                    """
                )
                cursor.execute(
                    f"""
                    CREATE UNIQUE INDEX uq_hist_target_active_series_year
                        ON {wrong_table} (race_series_id, year)
                     WHERE (NOT (resolution_status = 'superseded'))
                    """
                )
                result = validate_postgresql_catalog_contract(
                    contract=collect_postgresql_catalog_contract(),
                    applied_nodes=self._applied(),
                )
                self.assertFalse(result["ok"])
                self.assertIn(
                    "0071.uq_race_event_series_edition", result["drift_paths"]
                )
                self.assertIn(
                    "0071.uq_hist_target_active_series_year",
                    result["drift_paths"],
                )
            finally:
                cursor.execute("DROP INDEX IF EXISTS uq_race_event_series_edition")
                cursor.execute(
                    "DROP INDEX IF EXISTS uq_hist_target_active_series_year"
                )
                cursor.execute(f"DROP TABLE IF EXISTS {wrong_table}")
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX uq_race_event_series_edition
                        ON stable_raceevent (race_series_id, edition_year)
                     WHERE ((edition_year IS NOT NULL)
                        AND (race_series_id IS NOT NULL))
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX uq_hist_target_active_series_year
                        ON stable_historicalraceeventtarget (race_series_id, year)
                     WHERE (NOT (resolution_status = 'superseded'))
                    """
                )
        restored = validate_postgresql_catalog_contract(
            contract=collect_postgresql_catalog_contract(),
            applied_nodes=self._applied(),
        )
        self.assertTrue(restored["ok"], restored)

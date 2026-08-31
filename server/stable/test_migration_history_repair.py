from __future__ import annotations

import json
import os
import shutil
import subprocess
import stat
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import OperationalError, connection
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase, TestCase


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = (
    ROOT
    / "docs"
    / "changes"
    / "repair-production-migration-history"
    / "production_audit.json"
)

M0067 = ("stable", "0067_historical_calendar_release_a")
M0068 = ("stable", "0068_race_data_sync_pipeline_a_field_audit")
M0069 = ("stable", "0069_race_data_sync_pipeline_a_ledger_guards")
M0070 = ("stable", "0070_horse_identity_evidence_commit_receipt")
M0071 = ("stable", "0071_historical_calendar_release_b")
M0072 = ("stable", "0072_add_extended_racing_regions")
M0073 = ("stable", "0073_lifecycle_enforce_registry")
M0074 = ("stable", "0074_race_data_sync_r0_control_plane")
M0075 = ("stable", "0075_race_data_source_priority_and_reported_position")
M0076 = ("stable", "0076_alter_externaldataimporterror_racing_region_and_more")
M0077 = ("stable", "0077_racing_api_horse_identity_staging")


def _stable_plan(loader: MigrationLoader, applied: set[tuple[str, str]]) -> list[str]:
    return [
        name
        for app, name in loader.graph.forwards_plan(M0072)
        if app == "stable" and (app, name) not in applied and name >= "0068"
    ]


class MigrationHistoryRepair0075ReleaseContractTests(TestCase):
    """0075 must extend the reviewed ordinary-release leaf contract."""

    def test_0072_has_exact_forward_plan_to_0073_and_0073_is_final(self):
        from stable.services.historical_calendar_release_b_schema import (
            ALLOWED_FORWARD_STATES,
            TARGET,
        )

        self.assertEqual(TARGET, M0077)
        self.assertEqual(
            ALLOWED_FORWARD_STATES[(f"{M0072[0]}.{M0072[1]}",)],
            [M0073[1], M0074[1], M0075[1], M0076[1], M0077[1]],
        )
        self.assertEqual(
            ALLOWED_FORWARD_STATES[(f"{M0073[0]}.{M0073[1]}",)],
            [M0074[1], M0075[1], M0076[1], M0077[1]],
        )
        self.assertEqual(
            ALLOWED_FORWARD_STATES[(f"{M0074[0]}.{M0074[1]}",)],
            [M0075[1], M0076[1], M0077[1]],
        )
        self.assertEqual(
            ALLOWED_FORWARD_STATES[(f"{M0075[0]}.{M0075[1]}",)],
            [M0076[1], M0077[1]],
        )
        self.assertEqual(
            ALLOWED_FORWARD_STATES[(f"{M0076[0]}.{M0076[1]}",)],
            [M0077[1]],
        )
        self.assertEqual(
            ALLOWED_FORWARD_STATES[(f"{M0077[0]}.{M0077[1]}",)],
            [],
        )

    def test_handoff_final_boundary_advances_from_0072_to_0073(self):
        from stable.services.historical_calendar_release_b_handoff import (
            FINAL_LEAF_SET,
            PREVIOUS_FINAL_LEAF_SET,
        )

        self.assertEqual(PREVIOUS_FINAL_LEAF_SET, (f"{M0075[0]}.{M0075[1]}",))
        self.assertEqual(FINAL_LEAF_SET, (f"{M0077[0]}.{M0077[1]}",))

    def test_preflight_accepts_both_pre_migration_and_current_leaf(self):
        preflight = (
            ROOT / "deploy/run_historical_calendar_release_b_preflight.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("stable.0072_add_extended_racing_regions)", preflight)
        self.assertIn("stable.0073_lifecycle_enforce_registry)", preflight)
        self.assertIn("stable.0074_race_data_sync_r0_control_plane)", preflight)
        self.assertIn(
            "stable.0075_race_data_source_priority_and_reported_position)",
            preflight,
        )
        self.assertIn(
            "stable.0076_alter_externaldataimporterror_racing_region_and_more)",
            preflight,
        )
        self.assertIn("stable.0077_racing_api_horse_identity_staging)", preflight)

    def test_every_initial_install_prefix_includes_0073(self):
        from stable.services.historical_calendar_release_b_schema import (
            INITIAL_INSTALL_FORWARD_STATES,
        )

        for leaf_set, plan in INITIAL_INSTALL_FORWARD_STATES.items():
            with self.subTest(leaf_set=leaf_set):
                if leaf_set != (f"{M0077[0]}.{M0077[1]}",):
                    self.assertEqual(plan[-1], M0077[1])

    def test_generic_rollback_contract_carries_0073(self):
        for relative in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            self.assertIn(
                "RELEASE_B_EXPECTED_MIGRATION_LEAF_SET="
                "stable.0077_racing_api_horse_identity_staging",
                (ROOT / relative).read_text(encoding="utf-8"),
            )
        self.assertIn(
            "EXPECTED_LEAF=stable.0077_racing_api_horse_identity_staging",
            (ROOT / "deploy/resume_rollback_control_state.sh").read_text(
                encoding="utf-8"
            ),
        )
        verifier = (
            ROOT / "deploy/verify_rollback_target_migration.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"server/stable/migrations/0073_lifecycle_enforce_registry.py"',
            verifier,
        )
        self.assertIn(
            '"server/stable/migrations/0074_race_data_sync_r0_control_plane.py"',
            verifier,
        )
        self.assertIn(
            '"server/stable/migrations/0075_race_data_source_priority_and_reported_position.py"',
            verifier,
        )
        self.assertIn(
            '"server/stable/migrations/0076_alter_externaldataimporterror_racing_region_and_more.py"',
            verifier,
        )
        self.assertIn(
            '"server/stable/migrations/0077_racing_api_horse_identity_staging.py"',
            verifier,
        )
        allowlist = json.loads(
            (ROOT / "deploy/reviewed_release_b_rollback_migrations.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            allowlist["required_migrations"][-1]["migration_path"],
            "server/stable/migrations/0077_racing_api_horse_identity_staging.py",
        )

    def test_0073_catalog_contract_validates_tables_fks_constraints_and_indexes(self):
        from stable.services import historical_calendar_release_b_schema as schema

        self.assertTrue(
            hasattr(schema, "validate_lifecycle_registry_catalog_contract"),
            "0073 catalog validator is missing",
        )
        valid = self._valid_0073_catalog_contract()
        self.assertEqual(
            schema.validate_lifecycle_registry_catalog_contract(
                contract=valid, migration_applied=True
            ),
            [],
        )
        for section, name in (
            ("constraints", "uq_lifecycle_registry_event"),
            ("indexes", "lifecycle_member_state_idx"),
        ):
            drifted = json.loads(json.dumps(valid))
            drifted[section] = [
                row for row in drifted[section] if row["name"] != name
            ]
            with self.subTest(section=section, name=name):
                self.assertTrue(
                    schema.validate_lifecycle_registry_catalog_contract(
                        contract=drifted, migration_applied=True
                    )
                )

    def test_0073_catalog_contract_rejects_wrong_active_predicate(self):
        from stable.services import historical_calendar_release_b_schema as schema

        drifted = self._valid_0073_catalog_contract()
        active = next(
            row
            for row in drifted["indexes"]
            if row["name"] == "uq_lifecycle_registry_active"
        )
        active["predicate"] = "NOT is_active"
        self.assertIn(
            "0073.active_unique",
            schema.validate_lifecycle_registry_catalog_contract(
                contract=drifted, migration_applied=True
            ),
        )

    def test_0073_catalog_contract_rejects_column_semantic_drift(self):
        from stable.services import historical_calendar_release_b_schema as schema

        for table_suffix, column_name, field, value, expected_drift in (
            ("registry", "state", "type", "character varying(1)", "0073.registry_column_semantics"),
            ("membership", "event_id", "not_null", False, "0073.membership_column_semantics"),
            ("registry", "id", "identity", "", "0073.registry_id_identity"),
            ("membership", "id", "default_expr", "nextval('wrong')", "0073.membership_column_defaults"),
        ):
            drifted = self._valid_0073_catalog_contract()
            row = next(
                item
                for item in drifted["columns"]
                if item["table_name"].endswith(table_suffix)
                and item["column_name"] == column_name
            )
            row[field] = value
            with self.subTest(table=table_suffix, column=column_name, field=field):
                self.assertIn(
                    expected_drift,
                    schema.validate_lifecycle_registry_catalog_contract(
                        contract=drifted, migration_applied=True
                    ),
                )

    @staticmethod
    def _valid_0073_catalog_contract():
        registry = "stable_raceeventlifecycleenforceregistry"
        membership = "stable_raceeventlifecycleenforcemembership"
        registry_columns = {
            "id", "created_at", "updated_at", "root_sha256", "generation",
            "membership_sha256", "member_count", "state", "is_active",
            "activation_id", "approved_commit", "selector_scope", "scope_sha256",
            "census_cutoff", "apply_expires_at", "runtime_valid_until",
            "artifact_receipt", "activated_at", "retired_at", "predecessor_id",
        }
        membership_columns = {
            "id", "created_at", "updated_at", "state", "entry_sha256",
            "source_enrollment_sha256", "schedule_generation", "schedule_hash",
            "country_region", "timezone_name", "frozen_snapshot", "event_id",
            "registry_id",
        }
        registry_semantics = {
            "id": ("bigint", True),
            "created_at": ("timestamp with time zone", True),
            "updated_at": ("timestamp with time zone", True),
            "root_sha256": ("character varying(64)", True),
            "generation": ("bigint", True),
            "membership_sha256": ("character varying(64)", True),
            "member_count": ("integer", True),
            "state": ("character varying(16)", True),
            "is_active": ("boolean", True),
            "activation_id": ("character varying(64)", True),
            "approved_commit": ("character varying(40)", True),
            "selector_scope": ("jsonb", True),
            "scope_sha256": ("character varying(64)", True),
            "census_cutoff": ("timestamp with time zone", True),
            "apply_expires_at": ("timestamp with time zone", True),
            "runtime_valid_until": ("timestamp with time zone", True),
            "artifact_receipt": ("jsonb", True),
            "activated_at": ("timestamp with time zone", False),
            "retired_at": ("timestamp with time zone", False),
            "predecessor_id": ("bigint", False),
        }
        membership_semantics = {
            "id": ("bigint", True),
            "created_at": ("timestamp with time zone", True),
            "updated_at": ("timestamp with time zone", True),
            "state": ("character varying(16)", True),
            "entry_sha256": ("character varying(64)", True),
            "source_enrollment_sha256": ("character varying(64)", True),
            "schedule_generation": ("bigint", True),
            "schedule_hash": ("character varying(64)", True),
            "country_region": ("character varying(32)", True),
            "timezone_name": ("character varying(64)", True),
            "frozen_snapshot": ("jsonb", True),
            "event_id": ("bigint", True),
            "registry_id": ("bigint", True),
        }
        columns = [
            {
                "table_name": table,
                "column_name": name,
                "type": column_type,
                "not_null": not_null,
                "identity": "d" if name == "id" else "",
                "default_expr": "",
            }
            for table, semantics in (
                (registry, registry_semantics),
                (membership, membership_semantics),
            )
            for name, (column_type, not_null) in semantics.items()
        ]
        constraints = [
            {"name": "registry_pk", "table_name": registry, "type": "p", "validated": True, "columns": ["id"], "target_table": "", "target_columns": [], "delete_action": " ", "deferrable": False, "initially_deferred": False},
            {"name": "registry_root_key", "table_name": registry, "type": "u", "validated": True, "columns": ["root_sha256"], "target_table": "", "target_columns": [], "delete_action": " ", "deferrable": False, "initially_deferred": False},
            {"name": "registry_generation_key", "table_name": registry, "type": "u", "validated": True, "columns": ["generation"], "target_table": "", "target_columns": [], "delete_action": " ", "deferrable": False, "initially_deferred": False},
            {"name": "registry_predecessor_fk", "table_name": registry, "type": "f", "validated": True, "columns": ["predecessor_id"], "target_table": registry, "target_columns": ["id"], "delete_action": "a", "deferrable": True, "initially_deferred": True},
            {"name": "membership_pk", "table_name": membership, "type": "p", "validated": True, "columns": ["id"], "target_table": "", "target_columns": [], "delete_action": " ", "deferrable": False, "initially_deferred": False},
            {"name": "uq_lifecycle_registry_event", "table_name": membership, "type": "u", "validated": True, "columns": ["registry_id", "event_id"], "target_table": "", "target_columns": [], "delete_action": " ", "deferrable": False, "initially_deferred": False},
            {"name": "membership_event_fk", "table_name": membership, "type": "f", "validated": True, "columns": ["event_id"], "target_table": "stable_raceevent", "target_columns": ["id"], "delete_action": "a", "deferrable": True, "initially_deferred": True},
            {"name": "membership_registry_fk", "table_name": membership, "type": "f", "validated": True, "columns": ["registry_id"], "target_table": registry, "target_columns": ["id"], "delete_action": "a", "deferrable": True, "initially_deferred": True},
        ]
        indexes = [
            {"name": "uq_lifecycle_registry_active", "table_name": registry, "method": "btree", "unique": True, "valid": True, "ready": True, "live": True, "columns": ["is_active"], "predicate": "is_active"},
            {"name": "lifecycle_reg_state_gen_idx", "table_name": registry, "method": "btree", "unique": False, "valid": True, "ready": True, "live": True, "columns": ["state", "generation"], "predicate": ""},
            {"name": "lifecycle_member_reg_evt_idx", "table_name": membership, "method": "btree", "unique": False, "valid": True, "ready": True, "live": True, "columns": ["registry_id", "event_id"], "predicate": ""},
            {"name": "lifecycle_member_state_idx", "table_name": membership, "method": "btree", "unique": False, "valid": True, "ready": True, "live": True, "columns": ["registry_id", "state", "event_id"], "predicate": ""},
        ]
        return {"columns": columns, "constraints": constraints, "indexes": indexes}


class MigrationHistoryRepairGraphRedTests(TestCase):
    """RED: the candidate graph must describe the already-applied receipt branch."""

    def test_production_like_0067_0070_history_is_consistent_and_plan_is_exact(self):
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        # Model a real recorder: every dependency through 0067 is applied,
        # receipt 0070 is applied, and only the 0068/0069 branch is absent.
        applied = set(loader.graph.forwards_plan(M0067)) | {M0070}

        with patch(
            "django.db.migrations.loader.MigrationRecorder.applied_migrations",
            return_value=applied,
        ):
            try:
                loader.check_consistent_history(connection)
            except InconsistentMigrationHistory as exc:  # pragma: no cover - RED path
                self.fail(f"production-like recorder must be legal: {exc}")

        self.assertEqual(
            _stable_plan(loader, applied),
            [M0068[1], M0069[1], M0071[1], M0072[1]],
        )
        self.assertNotIn(M0070[1], _stable_plan(loader, applied))

    def test_recovery_leaf_sets_have_exact_forward_plans(self):
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        cases = (
            ({M0067, M0070}, [M0068[1], M0069[1], M0071[1], M0072[1]]),
            ({M0067, M0068, M0070}, [M0069[1], M0071[1], M0072[1]]),
            ({M0067, M0068, M0069, M0070}, [M0071[1], M0072[1]]),
            ({M0067, M0068, M0069, M0070, M0071}, [M0072[1]]),
            ({M0067, M0068, M0069, M0070, M0071, M0072}, []),
        )
        for applied, expected in cases:
            with self.subTest(applied=sorted(applied)):
                self.assertEqual(_stable_plan(loader, applied), expected)


class MigrationHistoryRepairLeafSetRedTests(TestCase):
    """RED: leaf sets are complete sets, never comma-delimited alternatives."""

    def test_management_command_accepts_repeated_complete_leaf_set(self):
        from io import StringIO

        output = StringIO()
        with patch(
            "stable.services.historical_calendar_release_b_schema."
            "MigrationRecorder.applied_migrations",
            return_value={M0067, M0068, M0070},
        ), patch(
            "stable.services.historical_calendar_release_b_schema.database_vendor_contract",
            return_value={"ok": True, "expected": "postgresql", "actual": "postgresql"},
        ), patch(
            "stable.services.historical_calendar_release_b_schema."
            "MigrationLoader.check_consistent_history"
        ), patch(
            "stable.services.historical_calendar_release_b_schema._postgres_catalog_state",
            return_value={"ok": True, "drift_paths": [], "catalog_sha256": "c" * 64},
        ):
            call_command(
                "check_historical_calendar_release_b_schema",
                direction="forward",
                json_output=True,
                expected_migration_leaf_set=[
                    f"{M0068[0]}.{M0068[1]}",
                    f"{M0070[0]}.{M0070[1]}",
                ],
                stdout=output,
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(
            payload["schema_version"], "migration-history-repair-preflight/v3"
        )
        self.assertEqual(
            payload["migration_leaf_set"],
            [f"{M0068[0]}.{M0068[1]}", f"{M0070[0]}.{M0070[1]}"],
        )
        self.assertEqual(
            payload["migration_plan"],
            [
                M0069[1], M0071[1], M0072[1], M0073[1], M0074[1],
                M0075[1], M0076[1], M0077[1],
            ],
        )
        self.assertTrue(payload["migration_state_allowed"])

    def test_illegal_partial_leaf_set_fails_closed(self):
        from io import StringIO

        output = StringIO()
        with patch(
            "stable.services.historical_calendar_release_b_schema."
            "MigrationRecorder.applied_migrations",
            return_value={M0067, M0068},
        ), patch(
            "stable.services.historical_calendar_release_b_schema.database_vendor_contract",
            return_value={"ok": True, "expected": "postgresql", "actual": "postgresql"},
        ), patch(
            "stable.services.historical_calendar_release_b_schema."
            "MigrationLoader.check_consistent_history"
        ), patch(
            "stable.services.historical_calendar_release_b_schema._postgres_catalog_state",
            return_value={"ok": True, "drift_paths": [], "catalog_sha256": "c" * 64},
        ), self.assertRaises(CommandError):
            call_command(
                "check_historical_calendar_release_b_schema",
                direction="forward",
                json_output=True,
                expected_migration_leaf_set=[f"{M0068[0]}.{M0068[1]}"],
                stdout=output,
            )
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["migration_state_allowed"])


class MigrationHistoryRepairBaselineRedTests(SimpleTestCase):
    def _baseline(self) -> dict:
        return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    def _live(self) -> dict:
        from stable.services.historical_calendar_release_b_schema import (
            AUDIT_FIELDS,
        )

        baseline = self._baseline()
        return {field: baseline[field] for field in AUDIT_FIELDS}

    def test_reviewed_baseline_accepts_only_an_exact_live_match(self):
        from stable.services.historical_calendar_release_b_schema import (
            compare_production_audit_baseline,
        )

        result = compare_production_audit_baseline(
            expected=self._baseline(), live=self._live()
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["drift_fields"], [])

    def test_receipt_operation_log_and_fk_drift_are_independent_failures(self):
        from stable.services.historical_calendar_release_b_schema import (
            compare_production_audit_baseline,
        )

        for field in (
            "receipt_rows_sha256",
            "operation_log_rows_sha256",
            "operation_log_fk_sha256",
        ):
            live = self._live()
            live[field] = "0" * 64
            with self.subTest(field=field):
                result = compare_production_audit_baseline(
                    expected=self._baseline(), live=live
                )
                self.assertFalse(result["ok"])
                self.assertEqual(result["drift_fields"], [field])

    def test_database_identity_drift_is_an_independent_failure(self):
        from stable.services.historical_calendar_release_b_schema import (
            compare_production_audit_baseline,
        )

        live = self._live()
        live["database_identity_sha256"] = "0" * 64
        result = compare_production_audit_baseline(
            expected=self._baseline(), live=live
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["drift_fields"], ["database_identity_sha256"])

    def test_static_production_baseline_is_only_enforced_for_repair_leaf_sets(self):
        from stable.services.historical_calendar_release_b_handoff import (
            production_audit_policy_for_leaf_set,
        )

        repair_states = (
            [f"{M0070[0]}.{M0070[1]}"],
            [f"{M0068[0]}.{M0068[1]}", f"{M0070[0]}.{M0070[1]}"],
            [f"{M0069[0]}.{M0069[1]}", f"{M0070[0]}.{M0070[1]}"],
        )
        for leaf_set in repair_states:
            self.assertEqual(production_audit_policy_for_leaf_set(leaf_set), "reviewed-static")
        self.assertEqual(
            production_audit_policy_for_leaf_set([f"{M0072[0]}.{M0072[1]}"]),
            "live-handoff",
        )
        self.assertEqual(
            production_audit_policy_for_leaf_set(
                [f"{M0072[0]}.{M0072[1]}"], repair_intent=True
            ),
            "reviewed-static",
        )

    def test_final_forward_resume_still_enforces_reviewed_static_audit(self):
        from stable.services.historical_calendar_release_b_handoff import (
            collect_handoff_preflight,
        )

        initial = {
            "ok": True,
            "migration_leaf_set": [f"{M0072[0]}.{M0072[1]}"],
        }
        enforced = {**initial, "production_audit_ok": False}
        with patch(
            "stable.services.historical_calendar_release_b_handoff."
            "check_release_b_schema_compatibility",
            side_effect=[initial, enforced],
        ) as check:
            result = collect_handoff_preflight(repair_intent=True)
        self.assertEqual(result["production_audit_policy"], "reviewed-static")
        self.assertFalse(result["production_audit_ok"])
        self.assertEqual(check.call_count, 2)

    def test_b_to_b_preflight_freezes_live_receipts_without_static_seven_row_gate(self):
        from stable.services.historical_calendar_release_b_handoff import (
            collect_handoff_preflight,
        )

        initial = {
            "ok": True,
            "migration_leaf_set": [f"{M0072[0]}.{M0072[1]}"],
            "production_audit_live": None,
        }
        live = {"receipt_count": 9, "receipt_rows_sha256": "a" * 64}
        with patch(
            "stable.services.historical_calendar_release_b_handoff."
            "check_release_b_schema_compatibility",
            return_value=initial,
        ) as check, patch(
            "stable.services.historical_calendar_release_b_handoff."
            "collect_live_production_audit",
            return_value=live,
        ):
            result = collect_handoff_preflight()
        check.assert_called_once_with(
            direction="forward", enforce_production_audit=False
        )
        self.assertEqual(result["production_audit_policy"], "live-handoff")
        self.assertEqual(result["production_audit_live"], live)

    def test_unsafe_catalog_stops_handoff_before_live_receipt_collection(self):
        from stable.services.historical_calendar_release_b_handoff import (
            collect_handoff_preflight,
        )

        initial = {
            "ok": False,
            "migration_leaf_set": [f"{M0070[0]}.{M0070[1]}"],
            "catalog_ok": False,
            "catalog_drift_paths": ["0070.table_presence"],
            "drift_paths": ["0070.table_presence"],
            "production_audit_live": None,
        }
        with patch(
            "stable.services.historical_calendar_release_b_handoff."
            "check_release_b_schema_compatibility",
            return_value=initial,
        ) as check, patch(
            "stable.services.historical_calendar_release_b_handoff."
            "collect_live_production_audit"
        ) as collect_audit:
            result = collect_handoff_preflight()
        self.assertFalse(result["ok"])
        self.assertEqual(result["drift_paths"], ["0070.table_presence"])
        check.assert_called_once_with(
            direction="forward", enforce_production_audit=False
        )
        collect_audit.assert_not_called()

    def test_schema_check_validates_catalog_before_any_orm_or_live_audit(self):
        from stable.services.historical_calendar_release_b_schema import (
            check_release_b_schema_compatibility,
        )

        state = {
            "applied_nodes": [f"{M0070[0]}.{M0070[1]}"],
            "migration_leaf_set": [f"{M0070[0]}.{M0070[1]}"],
            "migration_plan": [M0068[1], M0069[1], M0071[1], M0072[1]],
            "unknown_applied_migrations": [],
            "migration_graph_known": True,
            "migration_state_allowed": True,
            "expected_plan_for_leaf_set": [
                M0068[1], M0069[1], M0071[1], M0072[1]
            ],
        }
        catalog_state = {
            "ok": False,
            "drift_paths": ["0070.columns"],
            "catalog_sha256": "c" * 64,
        }
        with patch(
            "stable.services.historical_calendar_release_b_schema._migration_state",
            return_value=state,
        ), patch(
            "stable.services.historical_calendar_release_b_schema.collect_postgresql_catalog_contract",
            return_value={"checked": True},
        ), patch(
            "stable.services.historical_calendar_release_b_schema._postgres_catalog_state",
            return_value=catalog_state,
        ), patch(
            "stable.services.historical_calendar_release_b_schema._event_conflicts"
        ) as event_conflicts, patch(
            "stable.services.historical_calendar_release_b_schema._target_conflicts"
        ) as target_conflicts, patch(
            "stable.services.historical_calendar_release_b_schema.collect_live_production_audit"
        ) as collect_audit:
            result = check_release_b_schema_compatibility(
                direction="forward",
                enforce_production_audit=True,
                allow_nonproduction_database=True,
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["receipt_audit_safe"])
        self.assertEqual(result["drift_paths"], ["0070.columns"])
        self.assertIsNone(result["production_audit_live"])
        event_conflicts.assert_not_called()
        target_conflicts.assert_not_called()
        collect_audit.assert_not_called()

    def test_database_operational_error_is_not_reclassified_as_schema_drift(self):
        from stable.services.historical_calendar_release_b_schema import (
            check_release_b_schema_compatibility,
        )

        with patch(
            "stable.services.historical_calendar_release_b_schema._migration_state",
            side_effect=OperationalError("connection lost"),
        ), self.assertRaisesRegex(OperationalError, "connection lost"):
            check_release_b_schema_compatibility(
                direction="forward", allow_nonproduction_database=True
            )

    def test_inconsistent_full_history_is_structured_before_leaf_or_plan(self):
        from django.db.migrations.exceptions import InconsistentMigrationHistory
        from stable.services.historical_calendar_release_b_schema import (
            _migration_state,
        )

        with patch(
            "stable.services.historical_calendar_release_b_schema.MigrationLoader"
        ) as loader_class, patch(
            "stable.services.historical_calendar_release_b_schema."
            "MigrationRecorder.applied_migrations"
        ) as applied:
            loader_class.return_value.check_consistent_history.side_effect = (
                InconsistentMigrationHistory(
                    "Migration stable.0067 is applied before dependency stable.0066"
                )
            )
            first = _migration_state()
            second = _migration_state()
        self.assertFalse(first["migration_history_consistent"])
        self.assertEqual(first, second)
        self.assertEqual(first["migration_leaf_set"], [])
        self.assertEqual(
            first["migration_history_consistency_detail"]["error"],
            "InconsistentMigrationHistory",
        )
        self.assertRegex(
            first["migration_history_consistency_detail"]["message_sha256"],
            r"^[0-9a-f]{64}$",
        )
        applied.assert_not_called()

    def test_management_command_emits_json_then_command_error_for_schema_drift(self):
        result = {
            "ok": False,
            "migration_leaf_set": [f"{M0070[0]}.{M0070[1]}"],
            "database_identity_sha256": "d" * 64,
            "catalog_ok": False,
            "catalog_drift_paths": ["0070.table_presence"],
            "drift_paths": ["0070.table_presence"],
            "production_audit_live": None,
        }
        output = StringIO()
        with patch(
            "stable.management.commands.check_historical_calendar_release_b_schema."
            "check_release_b_schema_compatibility",
            return_value=result,
        ), self.assertRaises(CommandError):
            call_command(
                "check_historical_calendar_release_b_schema",
                direction="forward",
                enforce_production_audit=True,
                json_output=True,
                stdout=output,
            )
        payload = json.loads(output.getvalue().strip())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["drift_paths"], ["0070.table_presence"])

    def test_non_postgresql_fails_before_migration_or_catalog_reads(self):
        from stable.services.historical_calendar_release_b_schema import (
            check_release_b_schema_compatibility,
        )

        with patch(
            "stable.services.historical_calendar_release_b_schema.database_vendor_contract",
            return_value={"ok": False, "expected": "postgresql", "actual": "sqlite"},
        ), patch(
            "stable.services.historical_calendar_release_b_schema._migration_state"
        ) as migration_state, patch(
            "stable.services.historical_calendar_release_b_schema.collect_postgresql_catalog_contract"
        ) as collect_catalog:
            result = check_release_b_schema_compatibility(direction="forward")
        self.assertFalse(result["ok"])
        self.assertEqual(result["drift_paths"], ["database.vendor"])
        self.assertEqual(
            result["database_vendor"],
            {"ok": False, "expected": "postgresql", "actual": "sqlite"},
        )
        self.assertFalse(result["schema_checks_complete"])
        migration_state.assert_not_called()
        collect_catalog.assert_not_called()

    def test_unchecked_catalog_never_succeeds_by_default(self):
        from stable.services.historical_calendar_release_b_schema import (
            validate_postgresql_catalog_contract,
        )

        result = validate_postgresql_catalog_contract(
            contract={"vendor": "postgresql", "checked": False},
            applied_nodes=set(),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["drift_paths"], ["database.catalog_checked"])

    def test_vendor_management_command_emits_json_then_command_error(self):
        output = StringIO()
        with patch(
            "stable.management.commands.check_production_database_vendor."
            "database_vendor_contract",
            return_value={"ok": False, "expected": "postgresql", "actual": "sqlite"},
        ), self.assertRaises(CommandError):
            call_command("check_production_database_vendor", stdout=output)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["drift_paths"], ["database.vendor"])
        self.assertEqual(payload["database_vendor"]["actual"], "sqlite")

    def test_initial_install_uses_exact_0067_catalog_gate_without_static_audit(self):
        from stable.services.historical_calendar_release_b_schema import (
            check_initial_install_schema_compatibility,
        )

        state = {
            "applied_nodes": ["stable.0067_historical_calendar_release_a"],
            "migration_leaf_set": ["stable.0067_historical_calendar_release_a"],
            "migration_plan": [
                M0070[1], M0068[1], M0069[1], M0071[1], M0072[1],
                M0073[1], M0074[1], M0075[1], M0076[1], M0077[1],
            ],
            "unknown_applied_migrations": [],
            "migration_graph_known": True,
            "migration_state_allowed": False,
            "expected_plan_for_leaf_set": None,
        }
        with patch(
            "stable.services.historical_calendar_release_b_schema.database_vendor_contract",
            return_value={"ok": True, "expected": "postgresql", "actual": "postgresql"},
        ), patch(
            "stable.services.historical_calendar_release_b_schema._migration_state",
            return_value=state,
        ), patch(
            "stable.services.historical_calendar_release_b_schema.collect_postgresql_catalog_contract",
            return_value={"vendor": "postgresql", "checked": True},
        ), patch(
            "stable.services.historical_calendar_release_b_schema._postgres_catalog_state",
            return_value={"ok": True, "drift_paths": [], "catalog_sha256": "f" * 64},
        ), patch(
            "stable.services.historical_calendar_release_b_schema._event_conflicts",
            return_value=[],
        ), patch(
            "stable.services.historical_calendar_release_b_schema._target_conflicts",
            return_value=[],
        ), patch(
            "stable.services.historical_calendar_release_b_schema._initial_legacy_counts",
            return_value={"race_events": 0, "historical_targets": 0},
        ), patch(
            "stable.services.historical_calendar_release_b_schema.collect_live_production_audit"
        ) as static_audit:
            result = check_initial_install_schema_compatibility()
        self.assertTrue(result["ok"])
        self.assertTrue(result["initial_install_origin"])
        self.assertEqual(
            result["production_audit_policy"],
            "initial-install-legacy-compatible",
        )
        self.assertIsNone(result["production_audit_live"])
        self.assertEqual(result["initial_install_data_state"], "empty")
        static_audit.assert_not_called()


class MigrationHistoryRepairCatalogRedTests(SimpleTestCase):
    def test_release_b_unique_indexes_require_exact_schema_and_table_owner(self):
        from stable.services.historical_calendar_release_b_schema import (
            validate_release_b_index_owner,
        )

        for index_name, table_name in (
            ("uq_race_event_series_edition", "stable_raceevent"),
            (
                "uq_hist_target_active_series_year",
                "stable_historicalraceeventtarget",
            ),
        ):
            with self.subTest(index_name=index_name):
                self.assertTrue(
                    validate_release_b_index_owner(
                        index_name=index_name,
                        schema_name="public",
                        table_name=table_name,
                        expected_schema_name="public",
                    )
                )
                self.assertFalse(
                    validate_release_b_index_owner(
                        index_name=index_name,
                        schema_name="shadow",
                        table_name=table_name,
                        expected_schema_name="public",
                    )
                )
                self.assertFalse(
                    validate_release_b_index_owner(
                        index_name=index_name,
                        schema_name="public",
                        table_name="migration_repair_wrong_index_owner",
                        expected_schema_name="public",
                    )
                )

    def test_release_b_partial_index_predicates_require_exact_semantics(self):
        from stable.services.historical_calendar_release_b_schema import (
            validate_release_b_partial_index_predicate,
        )

        event = "((edition_year IS NOT NULL) AND (race_series_id IS NOT NULL))"
        target = "(NOT ((resolution_status)::text = 'superseded'::text))"
        self.assertTrue(
            validate_release_b_partial_index_predicate(
                index_name="uq_race_event_series_edition", predicate=event
            )
        )
        self.assertTrue(
            validate_release_b_partial_index_predicate(
                index_name="uq_hist_target_active_series_year", predicate=target
            )
        )
        for predicate in (
            f"({event}) AND false",
            event.replace("race_series_id", "id"),
            event.replace(" AND ", " OR "),
        ):
            self.assertFalse(
                validate_release_b_partial_index_predicate(
                    index_name="uq_race_event_series_edition", predicate=predicate
                )
            )
        for predicate in (
            f"({target}) OR true",
            target.replace("resolution_status", "source_status"),
            target.replace("NOT ", ""),
        ):
            self.assertFalse(
                validate_release_b_partial_index_predicate(
                    index_name="uq_hist_target_active_series_year",
                    predicate=predicate,
                )
            )

    def test_decision_check_requires_the_exact_allowed_semantic_set(self):
        from stable.services.historical_calendar_release_b_schema import (
            validate_decision_check_definition,
        )

        exact = (
            "CHECK ((((decision)::text = ''::text) OR "
            "((decision)::text = ANY "
            "((ARRAY['applied'::character varying, "
            "'replayed'::character varying, 'needs_review'::character varying, "
            "'rejected'::character varying])::text[]))))"
        )
        weakened = exact.replace(
            "'rejected'::character varying",
            "'rejected'::character varying, 'approved'::character varying",
        )
        self.assertTrue(validate_decision_check_definition(exact))
        self.assertFalse(validate_decision_check_definition(weakened))
        self.assertFalse(
            validate_decision_check_definition(
                exact.replace("'needs_review'::character varying, ", "")
            )
        )
        self.assertFalse(
            validate_decision_check_definition(
                exact.replace("decision", "other_decision")
            )
        )
        self.assertFalse(
            validate_decision_check_definition(exact.replace(" OR ", " AND "))
        )

    def test_guard_function_requires_one_exact_no_argument_signature(self):
        from stable.services.historical_calendar_release_b_schema import (
            validate_guard_function_contract,
        )

        exact = {
            "name": "stable_reject_race_field_change_mutation",
            "identity_arguments": "",
            "language": "plpgsql",
            "return_type": "trigger",
            "volatility": "v",
            "security_definer": False,
            "body_sha256": "2598a9fa2f8512b79d7a2ed5bfc09bbe09cb2f1e319fbdf713588325c7e467dd",
        }
        self.assertTrue(validate_guard_function_contract([exact]))
        overload = {**exact, "identity_arguments": "input_id bigint"}
        self.assertFalse(validate_guard_function_contract([exact, overload]))
        self.assertFalse(validate_guard_function_contract([overload]))

    def test_catalog_digest_detects_semantic_drift_not_just_object_names(self):
        from stable.services.historical_calendar_release_b_schema import (
            compare_catalog_contract,
        )

        expected = {
            "receipt_fk": {
                "columns": ["operation_log_id"],
                "target": "stable_operationlog(id)",
                "delete_action": "NO ACTION",
                "deferrable": True,
                "initially_deferred": True,
                "validated": True,
            },
            "receipt_index": {
                "method": "btree",
                "columns": ["approved_sha256", "varchar_pattern_ops"],
                "predicate": None,
            },
            "receipt_sequence": {
                "owned_by": "stable_horseidentityevidencecommitreceipt.id",
                "column_default": "nextval",
                "increment": 1,
                "cycle": False,
            },
            "ledger_trigger": {
                "timing": "BEFORE",
                "events": ["UPDATE", "DELETE"],
                "row_level": True,
                "function": "stable_reject_race_field_change_mutation",
                "function_body_sha256": "a" * 64,
            },
            "release_b_unique": {
                "method": "btree",
                "columns": ["race_series_id", "edition_year"],
                "predicate": "race_series_id IS NOT NULL AND edition_year IS NOT NULL",
            },
        }
        for path, replacement in (
            (("receipt_fk", "delete_action"), "CASCADE"),
            (("receipt_index", "method"), "hash"),
            (("receipt_sequence", "owned_by"), None),
            (("ledger_trigger", "events"), ["UPDATE"]),
            (("release_b_unique", "predicate"), "edition_year IS NOT NULL"),
        ):
            live = json.loads(json.dumps(expected))
            live[path[0]][path[1]] = replacement
            with self.subTest(path=path):
                result = compare_catalog_contract(expected=expected, live=live)
                self.assertFalse(result["ok"])
                self.assertIn(".".join(path), result["drift_paths"])


class MigrationHistoryRepairArtifactRedTests(SimpleTestCase):
    def _write_artifact(self, root: Path) -> tuple[Path, str, dict]:
        from stable.services.historical_calendar_release_b_handoff import (
            HANDOFF_SCHEMA_VERSION,
            canonical_artifact_sha256,
            release_0077_recovery_binding,
        )

        path = root / "before.json"
        payload = {
            "schema_version": HANDOFF_SCHEMA_VERSION,
            "candidate_commit": "a" * 40,
            "candidate_image_id": "sha256:" + "b" * 64,
            "database_identity_sha256": "c" * 64,
            "compose_file": "docker-compose.prod.lowcost.yml",
            "deployment_lock_token_sha256": "d" * 64,
            "artifact_path": str(path),
            "handoff_action": "deploy",
            "preflight": {
                "migration_leaf_set": [],
                "migration_plan": [],
            },
            "receipt_rows_sha256": "e" * 64,
            "operation_log_rows_sha256": "f" * 64,
            "operation_log_fk_sha256": "1" * 64,
        }
        payload.update(
            release_0077_recovery_binding(
                preflight=payload["preflight"],
                candidate_commit=payload["candidate_commit"],
                candidate_image_id=payload["candidate_image_id"],
                artifact_path=payload["artifact_path"],
                handoff_action=payload["handoff_action"],
            )
        )
        payload["artifact_sha256"] = canonical_artifact_sha256(payload)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        path.chmod(0o600)
        return path, payload["artifact_sha256"], payload

    def test_artifact_requires_regular_owned_mode_0600_file_and_exact_sha(self):
        from stable.services.historical_calendar_release_b_handoff import (
            verify_preflight_artifact,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, digest, payload = self._write_artifact(root)
            expected = {
                key: payload[key]
                for key in (
                    "candidate_commit",
                    "candidate_image_id",
                    "database_identity_sha256",
                    "compose_file",
                    "deployment_lock_token_sha256",
                )
            }
            self.assertTrue(
                verify_preflight_artifact(
                    path=path,
                    expected_artifact_sha256=digest,
                    expected_bindings=expected,
                )["ok"]
            )
            path.chmod(0o644)
            self.assertFalse(
                verify_preflight_artifact(
                    path=path,
                    expected_artifact_sha256=digest,
                    expected_bindings=expected,
                )["ok"]
            )
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

    def test_symlinked_artifact_is_rejected(self):
        from stable.services.historical_calendar_release_b_handoff import (
            verify_preflight_artifact,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, digest, payload = self._write_artifact(root)
            link = root / "link.json"
            link.symlink_to(path)
            result = verify_preflight_artifact(
                path=link,
                expected_artifact_sha256=digest,
                expected_bindings={"candidate_commit": payload["candidate_commit"]},
            )
            self.assertFalse(result["ok"])
            self.assertIn("symlink", result["errors"])

    def test_symlinked_or_swapped_parent_is_rejected(self):
        from stable.services.historical_calendar_release_b_handoff import (
            verify_preflight_artifact,
        )

        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            trusted = base / "trusted"
            trusted.mkdir(mode=0o700)
            path, digest, payload = self._write_artifact(trusted)
            moved = base / "moved"
            trusted.rename(moved)
            trusted.symlink_to(moved, target_is_directory=True)
            result = verify_preflight_artifact(
                path=path,
                expected_artifact_sha256=digest,
                expected_bindings={"candidate_commit": payload["candidate_commit"]},
            )
            self.assertFalse(result["ok"])
            self.assertIn("parent_symlink", result["errors"])

    def test_artifact_publish_is_no_clobber(self):
        from stable.services.historical_calendar_release_b_handoff import (
            publish_preflight_artifact,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, _digest, payload = self._write_artifact(root)
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                publish_preflight_artifact(path=path, payload=payload)
            self.assertEqual(path.read_bytes(), before)

    def test_each_binding_drift_is_rejected(self):
        from stable.services.historical_calendar_release_b_handoff import (
            verify_preflight_artifact,
        )

        with TemporaryDirectory() as tmp:
            path, digest, payload = self._write_artifact(Path(tmp))
            for key in (
                "candidate_commit",
                "candidate_image_id",
                "database_identity_sha256",
                "compose_file",
                "deployment_lock_token_sha256",
            ):
                with self.subTest(key=key):
                    result = verify_preflight_artifact(
                        path=path,
                        expected_artifact_sha256=digest,
                        expected_bindings={key: "drift"},
                    )
                    self.assertFalse(result["ok"])
                    self.assertIn(f"binding:{key}", result["errors"])

    def test_artifact_only_command_authenticates_original_lock_binding_without_live_preflight(self):
        from stable.services.historical_calendar_release_b_handoff import (
            canonical_artifact_sha256,
        )

        with TemporaryDirectory() as tmp:
            path, _digest, payload = self._write_artifact(Path(tmp))
            payload["artifact_path"] = str(path)
            payload["artifact_sha256"] = canonical_artifact_sha256(payload)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            output = StringIO()
            with patch(
                "stable.management.commands."
                "verify_historical_calendar_release_b_handoff.verify_closed_state",
                side_effect=AssertionError("artifact-only must not run live checks"),
            ), patch(
                "stable.management.commands."
                "verify_historical_calendar_release_b_handoff.database_vendor_contract",
                return_value={"ok": True, "expected": "postgresql", "actual": "postgresql"},
            ):
                call_command(
                    "verify_historical_calendar_release_b_handoff",
                    artifact_only=True,
                    artifact_path=str(path),
                    artifact_sha256=payload["artifact_sha256"],
                    candidate_commit=payload["candidate_commit"],
                    candidate_image_id=payload["candidate_image_id"],
                    database_identity_sha256=payload[
                        "database_identity_sha256"
                    ],
                    compose_file=payload["compose_file"],
                    deployment_lock_token_sha256=payload[
                        "deployment_lock_token_sha256"
                    ],
                    stdout=output,
                )
            self.assertTrue(json.loads(output.getvalue())["ok"])

    def test_release_task_verifies_exact_handoff_immediately_before_migrate(self):
        script = (ROOT / "deploy/docker/run-release-tasks.sh").read_text(encoding="utf-8")
        verifier = script.index("verify_historical_calendar_release_b_handoff")
        migrate = script.index("manage.py migrate --noinput")
        self.assertLess(verifier, migrate)
        between = script[verifier:migrate]
        self.assertNotIn("collectstatic", between)
        self.assertIn("RELEASE_B_PREFLIGHT_ARTIFACT_PATH", script)
        self.assertIn("RELEASE_B_PREFLIGHT_ARTIFACT_SHA256", script)

    def test_closed_state_drift_exits_before_any_migrate_invocation(self):
        script = (ROOT / "deploy/docker/run-release-tasks.sh").read_text(encoding="utf-8")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            container = root / "container"
            (container / "server").mkdir(parents=True)
            artifact = root / "before.json"
            artifact.write_text(
                '{"handoff_action":"deploy","recovery_intent_mode":"required"}\n',
                encoding="utf-8",
            )
            rewritten = script.replace("/app", str(container))
            script_path = root / "run-release-tasks.sh"
            script_path.write_text(rewritten, encoding="utf-8")
            script_path.chmod(0o755)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            call_log = root / "calls.log"
            fake_python = fake_bin / "python"
            fake_python.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$REPAIR_CALL_LOG\"\n"
                "case \" $* \" in\n"
                "  *verify_historical_calendar_release_b_handoff*) exit 23 ;;\n"
                "esac\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            result = subprocess.run(
                ["sh", str(script_path)],
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "REPAIR_CALL_LOG": str(call_log),
                    "RELEASE_B_PREFLIGHT_ARTIFACT_PATH": str(artifact),
                    "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256": "a" * 64,
                },
                text=True,
                capture_output=True,
                check=False,
            )
            calls = call_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertTrue(
            any("verify_historical_calendar_release_b_handoff" in call for call in calls),
            calls,
        )
        self.assertFalse(any(" migrate " in f" {call} " for call in calls), calls)


@skipUnless(
    os.environ.get("RUN_MIGRATION_REPAIR_DOCKER_CONTRACT") == "true"
    and shutil.which("docker"),
    "set RUN_MIGRATION_REPAIR_DOCKER_CONTRACT=true for the real image contract",
)
class MigrationHistoryRepairDockerImageContractTests(SimpleTestCase):
    def test_candidate_image_contains_only_the_exact_reviewed_audit_file(self):
        tag = "umanews-migration-repair-audit-contract:local"
        build = subprocess.run(
            [
                "docker",
                "build",
                "-t",
                tag,
                "--build-arg",
                "UMANEWS_RELEASE_COMMIT=" + "0" * 40,
                ".",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
        self.assertEqual(build.returncode, 0, build.stderr[-4000:])
        code = (
            "from pathlib import Path; import django; django.setup(); "
            "from stable.services.historical_calendar_release_b_schema import "
            "AUDIT_PATH, load_reviewed_production_audit; "
            "expected=Path('/app/docs/changes/repair-production-migration-history/production_audit.json'); "
            "assert AUDIT_PATH == expected; "
            "files=sorted(str(p.relative_to('/app/docs')) for p in Path('/app/docs').rglob('*') if p.is_file()); "
            "assert files == ['changes/repair-production-migration-history/production_audit.json'], files; "
            "assert load_reviewed_production_audit()['database_identity_sha256'] == "
            "'a986cc11149981c54e9d4915ad35e7c46e9382584d6670c8f950eceda26e471c'"
        )
        read = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-e",
                "DJANGO_SETTINGS_MODULE=app.settings",
                "--entrypoint",
                "python",
                tag,
                "-c",
                code,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(read.returncode, 0, read.stderr)


class MigrationHistoryRepairRestrictedRecoveryRedTests(SimpleTestCase):
    def _run_no_intent_ensure(
        self,
        *,
        artifact_leaf_set: list[str],
        live_leaf_set: list[str],
    ) -> str:
        command = (
            "stable.management.commands."
            "ensure_historical_calendar_recovery_intent"
        )
        payload = {
            "recovery_intent_mode": "not-required",
            "handoff_action": "deploy",
            "preflight": {"migration_leaf_set": artifact_leaf_set},
        }
        live = {
            "ok": True,
            "migration_leaf_set": live_leaf_set,
            "database_identity_sha256": "d" * 64,
        }
        with TemporaryDirectory() as tmp, patch(
            f"{command}.database_vendor_contract",
            return_value={
                "ok": True,
                "expected": "postgresql",
                "actual": "postgresql",
            },
        ), patch(
            f"{command}.verify_preflight_artifact",
            return_value={"ok": True, "payload": payload},
        ), patch(
            f"{command}.collect_handoff_preflight", return_value=live
        ):
            root = Path(tmp)
            root.chmod(0o700)
            output = StringIO()
            call_command(
                "ensure_historical_calendar_recovery_intent",
                marker_path=str(root / "restricted-recovery.json"),
                artifact_path=str(root / "preflight.json"),
                artifact_sha256="1" * 64,
                candidate_commit="a" * 40,
                candidate_image_id="sha256:" + "b" * 64,
                database_identity_sha256="d" * 64,
                attempt_mode="not-required",
                stdout=output,
            )
            self.assertFalse((root / "restricted-recovery.json").exists())
            return output.getvalue()

    def test_no_intent_accepts_artifact_bound_0073_starting_leaf(self):
        leaf = f"{M0073[0]}.{M0073[1]}"
        output = self._run_no_intent_ensure(
            artifact_leaf_set=[leaf], live_leaf_set=[leaf]
        )
        self.assertIn('"status": "not-required"', output)
        self.assertIn(leaf, output)

    def test_no_intent_rejects_live_starting_leaf_drift(self):
        with self.assertRaisesRegex(CommandError, "starting leaf drift"):
            self._run_no_intent_ensure(
                artifact_leaf_set=[f"{M0073[0]}.{M0073[1]}"],
                live_leaf_set=[f"{M0074[0]}.{M0074[1]}"],
            )

    def test_no_intent_rejects_unreviewed_artifact_bound_leaf(self):
        with self.assertRaisesRegex(CommandError, "reviewed ordinary starting leaf"):
            self._run_no_intent_ensure(
                artifact_leaf_set=["stable.9999_unreviewed"],
                live_leaf_set=["stable.9999_unreviewed"],
            )

    def _initial_install_marker(self, path: Path):
        from stable.services.historical_calendar_release_b_handoff import (
            build_restricted_recovery_marker,
            publish_restricted_recovery_marker,
        )

        binding = {
            "candidate_commit": "a" * 40,
            "candidate_image_id": "sha256:" + "b" * 64,
            "artifact_sha256": "c" * 64,
            "database_identity_sha256": "d" * 64,
            "origin_action": "initial-install",
            "allowed_recovery_action": "forward-resume",
            "initial_catalog_sha256": "e" * 64,
            "initial_rows_sha256": "f" * 64,
            "initial_install_data_state": "empty",
            "initial_legacy_counts": {"race_events": 0, "historical_targets": 0},
            "initiating_action": "initial-install",
        }
        marker = build_restricted_recovery_marker(
            binding=binding,
            leaf_set=["stable.0067_historical_calendar_release_a"],
        )
        publish_restricted_recovery_marker(path=path, marker=marker)
        return marker, binding

    def test_initial_install_marker_accepts_only_reviewed_monotonic_prefixes(self):
        from stable.services.historical_calendar_release_b_handoff import (
            verify_restricted_marker_for_live_state,
        )

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "restricted-recovery.json"
            _marker, binding = self._initial_install_marker(path)
            expected = {**binding, "action": "forward-resume"}
            for leaf_set in (
                ["stable.0067_historical_calendar_release_a"],
                ["stable.0070_horse_identity_evidence_commit_receipt"],
                [
                    "stable.0068_race_data_sync_pipeline_a_field_audit",
                    "stable.0070_horse_identity_evidence_commit_receipt",
                ],
                [
                    "stable.0069_race_data_sync_pipeline_a_ledger_guards",
                    "stable.0070_horse_identity_evidence_commit_receipt",
                ],
                ["stable.0071_historical_calendar_release_b"],
            ):
                with self.subTest(leaf_set=leaf_set):
                    self.assertTrue(verify_restricted_marker_for_live_state(
                        path=path,
                        expected_binding=expected,
                        live_leaf_set=leaf_set,
                    )["ok"])
            for unsafe in (
                ["stable.0068_race_data_sync_pipeline_a_field_audit"],
                ["stable.0069_race_data_sync_pipeline_a_ledger_guards"],
            ):
                self.assertFalse(verify_restricted_marker_for_live_state(
                    path=path,
                    expected_binding=expected,
                    live_leaf_set=unsafe,
                )["ok"])

    def test_initial_install_marker_rejects_wrong_candidate_and_ordinary_deploy(self):
        from stable.services.historical_calendar_release_b_handoff import (
            authorize_handoff_action,
            verify_restricted_marker_for_live_state,
        )

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "restricted-recovery.json"
            _marker, binding = self._initial_install_marker(path)
            wrong = {**binding, "candidate_commit": "0" * 40, "action": "forward-resume"}
            self.assertFalse(verify_restricted_marker_for_live_state(
                path=path,
                expected_binding=wrong,
                live_leaf_set=["stable.0070_horse_identity_evidence_commit_receipt"],
            )["ok"])
            self.assertFalse(authorize_handoff_action(
                leaf_set=["stable.0071_historical_calendar_release_b"],
                action="deploy",
                restricted_marker_ok=False,
                active_marker_present=True,
            )["ok"])

    def test_initial_install_final_state_completes_the_required_marker(self):
        from stable.services.historical_calendar_release_b_handoff import (
            complete_restricted_recovery_marker,
        )

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "restricted-recovery.json"
            marker, binding = self._initial_install_marker(path)
            completed = complete_restricted_recovery_marker(
                path=path,
                expected_binding={**binding, "action": "forward-resume"},
            )
            self.assertFalse(path.exists())
            self.assertTrue(completed.exists())
            self.assertIn(marker["marker_sha256"], completed.name)

    def _completion_artifact_payload(self, origin="initial-install"):
        return {
            "recovery_origin_action": origin,
            "recovery_origin_catalog_sha256": "e" * 64,
            "recovery_origin_rows_sha256": "f" * 64,
            "recovery_origin_data_state": "empty",
            "recovery_origin_legacy_counts": {
                "race_events": 0,
                "historical_targets": 0,
            },
        }


    @staticmethod
    def _valid_contract():
        snapshot = "stable_racedatasnapshotlease"
        checkpoint = "stable_raceeventliveprovidercheckpoint"
        enrollment = "stable_racedatasyncenrollment"
        source = "stable_raceresultsourceidentity"
        projection = "stable_raceeventprojectioncontrol"
        column_names = {
            snapshot: {
                "id", "created_at", "updated_at", "cache_key", "state",
                "owner_token", "lease_generation", "lease_expires_at",
                "artifact_sha256", "manifest_data", "retry_after", "error_code",
            },
            checkpoint: {
                "id", "created_at", "updated_at", "source_key", "data_kind",
                "next_poll_at", "last_attempt_at", "last_success_at",
                "last_observation_hash", "last_source_updated_at",
                "consecutive_failures", "circuit_reason", "stale_at",
                "contract_digest", "registry_digest", "lock_version", "tracking_id",
            },
            enrollment: {
                "id", "created_at", "updated_at", "state",
                "standing_policy_digest", "route_digest", "event_snapshot_sha256",
                "projection_owner_generation", "enrollment_generation",
                "manifest_sha256", "entry_sha256", "reason_code", "effective_at",
                "retired_at", "event_id", "source_identity_id",
            },
            source: {"region_code", "identity_namespace"},
            projection: {"write_owner"},
        }
        column_semantics = {
            snapshot: {
                "id": ("bigint", True),
                "created_at": ("timestamp with time zone", True),
                "updated_at": ("timestamp with time zone", True),
                "cache_key": ("character varying(255)", True),
                "state": ("character varying(16)", True),
                "owner_token": ("character varying(64)", True),
                "lease_generation": ("bigint", True),
                "lease_expires_at": ("timestamp with time zone", False),
                "artifact_sha256": ("character varying(64)", True),
                "manifest_data": ("jsonb", True),
                "retry_after": ("timestamp with time zone", False),
                "error_code": ("character varying(64)", True),
            },
            checkpoint: {
                "id": ("bigint", True),
                "created_at": ("timestamp with time zone", True),
                "updated_at": ("timestamp with time zone", True),
                "source_key": ("character varying(64)", True),
                "data_kind": ("character varying(16)", True),
                "next_poll_at": ("timestamp with time zone", False),
                "last_attempt_at": ("timestamp with time zone", False),
                "last_success_at": ("timestamp with time zone", False),
                "last_observation_hash": ("character varying(64)", True),
                "last_source_updated_at": ("timestamp with time zone", False),
                "consecutive_failures": ("integer", True),
                "circuit_reason": ("character varying(64)", True),
                "stale_at": ("timestamp with time zone", False),
                "contract_digest": ("character varying(64)", True),
                "registry_digest": ("character varying(64)", True),
                "lock_version": ("bigint", True),
                "tracking_id": ("bigint", True),
            },
            enrollment: {
                "id": ("bigint", True),
                "created_at": ("timestamp with time zone", True),
                "updated_at": ("timestamp with time zone", True),
                "state": ("character varying(16)", True),
                "standing_policy_digest": ("character varying(64)", True),
                "route_digest": ("character varying(64)", True),
                "event_snapshot_sha256": ("character varying(64)", True),
                "projection_owner_generation": ("bigint", True),
                "enrollment_generation": ("bigint", True),
                "manifest_sha256": ("character varying(64)", True),
                "entry_sha256": ("character varying(64)", True),
                "reason_code": ("character varying(64)", True),
                "effective_at": ("timestamp with time zone", False),
                "retired_at": ("timestamp with time zone", False),
                "event_id": ("bigint", True),
                "source_identity_id": ("bigint", True),
            },
            source: {
                "region_code": ("character varying(32)", True),
                "identity_namespace": ("character varying(64)", True),
            },
            projection: {"write_owner": ("character varying(16)", True)},
        }
        columns = []
        for table, names in column_names.items():
            for name in sorted(names):
                column_type, not_null = column_semantics[table][name]
                columns.append({
                    "table_name": table,
                    "column_name": name,
                    "type": column_type,
                    "not_null": not_null,
                    "identity": "d" if name == "id" else "",
                    "default_expr": "",
                })

        def constraint(table, name, kind, columns, target="", definition=""):
            return {
                "table_name": table,
                "name": name,
                "type": kind,
                "validated": True,
                "deferrable": bool(target),
                "initially_deferred": bool(target),
                "definition": definition,
                "target_table": target,
                "columns": columns,
                "target_columns": ["id"] if target else [],
                "delete_action": "a" if target else " ",
            }

        constraints = [
            constraint(snapshot, "snapshot_pk", "p", ["id"]),
            constraint(snapshot, "snapshot_cache_unique", "u", ["cache_key"]),
            constraint(checkpoint, "checkpoint_pk", "p", ["id"]),
            constraint(checkpoint, "uq_race_data_ckpt_route_kind", "u", ["tracking_id", "source_key", "data_kind"]),
            constraint(checkpoint, "checkpoint_tracking_fk", "f", ["tracking_id"], "stable_raceeventlivetracking"),
            constraint(enrollment, "enrollment_pk", "p", ["id"]),
            constraint(enrollment, "enrollment_event_unique", "u", ["event_id"]),
            constraint(enrollment, "enrollment_event_fk", "f", ["event_id"], "stable_raceevent"),
            constraint(enrollment, "enrollment_source_fk", "f", ["source_identity_id"], source),
            constraint(source, "uq_race_srcid_route_external", "u", ["source_key", "region_code", "identity_namespace", "external_race_id"]),
            constraint(source, "uq_race_srcid_event_route", "u", ["event_id", "source_key", "region_code", "identity_namespace"]),
            constraint(
                snapshot,
                "race_data_snapshot_state_valid",
                "c",
                ["state"],
                definition=(
                    "CHECK (state = ANY (ARRAY['claimed', 'complete', 'failed']))"
                ),
            ),
            constraint(
                snapshot,
                "race_data_snapshot_generation_gte1",
                "c",
                ["lease_generation"],
                definition="CHECK (lease_generation >= 1)",
            ),
            constraint(
                snapshot,
                "race_data_snapshot_state_shape",
                "c",
                ["state", "owner_token", "lease_expires_at"],
                definition=(
                    "CHECK ((state = 'claimed' AND owner_token > '' AND "
                    "lease_expires_at IS NOT NULL AND artifact_sha256 = '' AND "
                    "retry_after IS NULL AND error_code = '') OR "
                    "(state = 'complete' AND owner_token = '' AND "
                    "lease_expires_at IS NOT NULL AND artifact_sha256 > '' AND "
                    "retry_after IS NULL AND error_code = '') OR "
                    "(state = 'failed' AND owner_token = '' AND "
                    "lease_expires_at IS NULL AND artifact_sha256 = '' AND "
                    "retry_after IS NOT NULL AND error_code > ''))"
                ),
            ),
            constraint(
                checkpoint,
                "race_data_ckpt_kind_valid",
                "c",
                ["data_kind"],
                definition=(
                    "CHECK (data_kind = ANY "
                    "(ARRAY['race_time', 'racecard', 'result']))"
                ),
            ),
            constraint(
                enrollment,
                "race_data_enroll_state_valid",
                "c",
                ["state"],
                definition=(
                    "CHECK (state = ANY "
                    "(ARRAY['proposed', 'enrolled', 'paused', 'retired']))"
                ),
            ),
            constraint(
                enrollment,
                "race_data_enroll_gen_gte1",
                "c",
                ["enrollment_generation"],
                definition="CHECK (enrollment_generation >= 1)",
            ),
            constraint(
                projection,
                "race_projection_owner_valid",
                "c",
                ["write_owner"],
                definition=(
                    "CHECK (write_owner = ANY "
                    "(ARRAY['unmanaged', 'historical', 'live', 'data_sync', "
                    "'manual_paused']))"
                ),
            ),
        ]

        def index(name, table, columns):
            return {
                "name": name,
                "table_name": table,
                "method": "btree",
                "unique": False,
                "valid": True,
                "ready": True,
                "live": True,
                "columns": columns,
                "predicate": "",
            }

        return {
            "columns": columns,
            "constraints": constraints,
            "indexes": [
                index("race_data_snapshot_lease_idx", snapshot, ["state", "lease_expires_at"]),
                index("race_data_ckpt_due_idx", checkpoint, ["next_poll_at", "tracking_id"]),
                index("race_data_enroll_state_evt_idx", enrollment, ["state", "event_id"]),
            ],
        }

    def test_valid_0074_catalog_is_accepted(self):
        from stable.services.historical_calendar_release_b_schema import (
            validate_race_data_sync_r0_catalog_contract,
        )

        self.assertEqual(
            validate_race_data_sync_r0_catalog_contract(
                contract=self._valid_contract(), migration_applied=True
            ),
            [],
        )

    def test_identity_or_owner_contract_drift_is_rejected(self):
        from stable.services.historical_calendar_release_b_schema import (
            validate_race_data_sync_r0_catalog_contract,
        )

        contract = self._valid_contract()
        contract["columns"] = [
            row
            for row in contract["columns"]
            if not (
                row["table_name"] == "stable_raceresultsourceidentity"
                and row["column_name"] == "identity_namespace"
            )
        ]
        owner = next(
            row
            for row in contract["constraints"]
            if row["name"] == "race_projection_owner_valid"
        )
        owner["definition"] = "CHECK write_owner IN (unmanaged, live)"
        drift = validate_race_data_sync_r0_catalog_contract(
            contract=contract, migration_applied=True
        )
        self.assertIn("0074.identity_scope_columns", drift)
        self.assertIn("0074.projection_owner_check", drift)

    def test_initial_completion_uses_origin_bound_audit_not_reviewed_static(self):
        command = (
            "stable.management.commands."
            "complete_historical_calendar_restricted_recovery"
        )
        marker = {
            "origin_action": "initial-install",
            "initial_install_data_state": "empty",
            "initial_legacy_counts": {"race_events": 0, "historical_targets": 0},
        }
        live = {
            "ok": True,
            "migration_leaf_set": [f"{M0077[0]}.{M0077[1]}"],
            "database_identity_sha256": "d" * 64,
        }
        with TemporaryDirectory() as tmp:
            marker_path = Path(tmp) / "restricted-recovery.json"
            marker_path.write_text("{}", encoding="utf-8")
            marker_path.chmod(0o600)
            with patch(
                f"{command}.database_vendor_contract",
                return_value={"ok": True, "expected": "postgresql", "actual": "postgresql"},
            ), patch(
                f"{command}.verify_preflight_artifact",
                return_value={"ok": True, "payload": self._completion_artifact_payload()},
            ), patch(
                f"{command}.verify_restricted_marker_for_live_state",
                return_value={"ok": True, "marker": marker},
            ), patch(
                f"{command}.collect_initial_install_preflight", return_value=live
            ) as initial_preflight, patch(
                f"{command}.collect_handoff_preflight"
            ) as reviewed_static, patch(
                f"{command}.collect_initial_install_completion_audit",
                return_value={"ok": True, "drift_paths": []},
            ) as initial_audit, patch(
                f"{command}.complete_restricted_recovery_marker",
                return_value=Path(tmp) / "completed.json",
            ):
                call_command(
                    "complete_historical_calendar_restricted_recovery",
                    marker_path=str(marker_path),
                    artifact_path=str(Path(tmp) / "preflight.json"),
                    artifact_sha256="1" * 64,
                    provenance_artifact_sha256="c" * 64,
                    candidate_commit="a" * 40,
                    candidate_image_id="sha256:" + "b" * 64,
                    database_identity_sha256="d" * 64,
                    attempt_mode="required",
                    expected_marker_device=1,
                    expected_marker_inode=2,
                    stdout=StringIO(),
                )
            initial_preflight.assert_called_once_with()
            reviewed_static.assert_not_called()
            initial_audit.assert_called_once()

    def test_completion_rejects_artifact_marker_origin_mismatch(self):
        command = (
            "stable.management.commands."
            "complete_historical_calendar_restricted_recovery"
        )
        with TemporaryDirectory() as tmp:
            marker_path = Path(tmp) / "restricted-recovery.json"
            marker_path.write_text("{}", encoding="utf-8")
            with patch(
                f"{command}.database_vendor_contract",
                return_value={"ok": True, "expected": "postgresql", "actual": "postgresql"},
            ), patch(
                f"{command}.verify_preflight_artifact",
                return_value={"ok": True, "payload": self._completion_artifact_payload()},
            ), patch(
                f"{command}.verify_restricted_marker_for_live_state",
                return_value={"ok": True, "marker": {"origin_action": "migration-history-repair"}},
            ), self.assertRaisesRegex(CommandError, "origin mismatch"):
                call_command(
                    "complete_historical_calendar_restricted_recovery",
                    marker_path=str(marker_path), artifact_path=str(Path(tmp) / "a.json"),
                    artifact_sha256="1" * 64, provenance_artifact_sha256="c" * 64,
                    candidate_commit="a" * 40, candidate_image_id="sha256:" + "b" * 64,
                    database_identity_sha256="d" * 64, attempt_mode="required",
                    expected_marker_device=1, expected_marker_inode=2,
                )

    def test_repair_origin_with_empty_receipts_still_uses_reviewed_static_and_fails(self):
        command = (
            "stable.management.commands."
            "complete_historical_calendar_restricted_recovery"
        )
        with TemporaryDirectory() as tmp:
            marker_path = Path(tmp) / "restricted-recovery.json"
            marker_path.write_text("{}", encoding="utf-8")
            repair_payload = self._completion_artifact_payload("migration-history-repair")
            with patch(
                f"{command}.database_vendor_contract",
                return_value={"ok": True, "expected": "postgresql", "actual": "postgresql"},
            ), patch(
                f"{command}.verify_preflight_artifact",
                return_value={"ok": True, "payload": repair_payload},
            ), patch(
                f"{command}.verify_restricted_marker_for_live_state",
                return_value={"ok": True, "marker": {}},
            ), patch(
                f"{command}.collect_handoff_preflight",
                return_value={
                    "ok": False,
                    "migration_leaf_set": [f"{M0071[0]}.{M0071[1]}"],
                    "database_identity_sha256": "d" * 64,
                    "drift_paths": ["production_audit.receipt_count"],
                },
            ) as reviewed_static, patch(
                f"{command}.collect_initial_install_preflight"
            ) as initial_preflight, self.assertRaises(CommandError):
                call_command(
                    "complete_historical_calendar_restricted_recovery",
                    marker_path=str(marker_path), artifact_path=str(Path(tmp) / "a.json"),
                    artifact_sha256="1" * 64, provenance_artifact_sha256="c" * 64,
                    candidate_commit="a" * 40, candidate_image_id="sha256:" + "b" * 64,
                    database_identity_sha256="d" * 64, attempt_mode="required",
                    expected_marker_device=1, expected_marker_inode=2,
                    stdout=StringIO(),
                )
            reviewed_static.assert_called_once_with(repair_intent=True)
            initial_preflight.assert_not_called()

    def test_completion_rejects_a_different_live_database_identity(self):
        live = {
            "ok": True,
            "migration_leaf_set": [f"{M0072[0]}.{M0072[1]}"],
            "database_identity_sha256": "0" * 64,
        }
        with patch(
            "stable.management.commands."
            "complete_historical_calendar_restricted_recovery."
            "collect_handoff_preflight",
            return_value=live,
        ), patch(
            "stable.management.commands."
            "complete_historical_calendar_restricted_recovery."
            "complete_restricted_recovery_marker",
        ) as complete, patch(
            "stable.management.commands."
            "complete_historical_calendar_restricted_recovery."
            "verify_preflight_artifact",
            return_value={
                "ok": True,
                "payload": {"recovery_origin_action": "migration-history-repair"},
            },
        ), patch(
            "stable.management.commands."
            "complete_historical_calendar_restricted_recovery.database_vendor_contract",
            return_value={"ok": True, "expected": "postgresql", "actual": "postgresql"},
        ), self.assertRaises(CommandError):
            call_command(
                "complete_historical_calendar_restricted_recovery",
                marker_path="/tmp/not-read.json",
                artifact_path="/tmp/preflight.json",
                artifact_sha256="e" * 64,
                attempt_mode="not-required",
                expected_marker_device=1,
                expected_marker_inode=2,
                provenance_artifact_sha256="a" * 64,
                candidate_commit="b" * 40,
                candidate_image_id="sha256:" + "c" * 64,
                database_identity_sha256="d" * 64,
            )
        complete.assert_not_called()

    def test_required_completion_cannot_noop_after_marker_deletion(self):
        live = {
            "ok": True,
            "migration_leaf_set": [f"{M0077[0]}.{M0077[1]}"],
            "database_identity_sha256": "d" * 64,
        }
        with TemporaryDirectory() as tmp, patch(
            "stable.management.commands."
            "complete_historical_calendar_restricted_recovery."
            "collect_handoff_preflight",
            return_value=live,
        ), patch(
            "stable.management.commands."
            "complete_historical_calendar_restricted_recovery."
            "verify_preflight_artifact",
            return_value={
                "ok": True,
                "payload": {"recovery_origin_action": "migration-history-repair"},
            },
        ), patch(
            "stable.management.commands."
            "complete_historical_calendar_restricted_recovery.database_vendor_contract",
            return_value={"ok": True, "expected": "postgresql", "actual": "postgresql"},
        ):
            root = Path(tmp)
            common = {
                "marker_path": str(root / "restricted-recovery.json"),
                "artifact_path": str(root / "preflight.json"),
                "artifact_sha256": "e" * 64,
                "provenance_artifact_sha256": "a" * 64,
                "candidate_commit": "b" * 40,
                "candidate_image_id": "sha256:" + "c" * 64,
                "database_identity_sha256": "d" * 64,
            }
            with self.assertRaisesRegex(CommandError, "required completion marker is missing"):
                call_command(
                    "complete_historical_calendar_restricted_recovery",
                    attempt_mode="required",
                    expected_marker_device=1,
                    expected_marker_inode=2,
                    **common,
                )
            out = StringIO()
            call_command(
                "complete_historical_calendar_restricted_recovery",
                attempt_mode="not-required",
                stdout=out,
                **common,
            )
            self.assertIn('"status": "not-required"', out.getvalue())

    def test_partial_state_requires_bound_restricted_recovery_marker(self):
        from stable.services.historical_calendar_release_b_handoff import (
            build_restricted_recovery_marker,
            validate_restricted_recovery,
        )

        binding = {
            "candidate_commit": "a" * 40,
            "candidate_image_id": "sha256:" + "b" * 64,
            "artifact_sha256": "c" * 64,
            "database_identity_sha256": "d" * 64,
        }
        for leaf_set in (
            [f"{M0068[0]}.{M0068[1]}", f"{M0070[0]}.{M0070[1]}"],
            [f"{M0069[0]}.{M0069[1]}", f"{M0070[0]}.{M0070[1]}"],
        ):
            with self.subTest(leaf_set=leaf_set):
                marker = build_restricted_recovery_marker(
                    binding=binding, leaf_set=[f"{M0070[0]}.{M0070[1]}"]
                )
                self.assertFalse(
                    validate_restricted_recovery(
                        leaf_set=leaf_set,
                        marker=None,
                        expected_binding=binding,
                        action="deploy",
                    )["ok"]
                )
                self.assertTrue(
                    validate_restricted_recovery(
                        leaf_set=leaf_set,
                        marker=marker,
                        expected_binding=binding,
                        action="forward-resume",
                    )["ok"]
                )
                drifted = {**marker, "artifact_sha256": "0" * 64}
                self.assertFalse(
                    validate_restricted_recovery(
                        leaf_set=leaf_set,
                        marker=drifted,
                        expected_binding=binding,
                        action="forward-resume",
                    )["ok"]
                )

    def test_marker_uses_dedicated_canonical_trust_and_state_binding(self):
        from stable.services.historical_calendar_release_b_handoff import (
            _rename_noreplace,
            build_restricted_recovery_marker,
            complete_restricted_recovery_marker,
            publish_restricted_recovery_marker,
            verify_restricted_recovery_marker,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "restricted.json"
            binding = {
                "candidate_commit": "a" * 40,
                "candidate_image_id": "sha256:" + "b" * 64,
                "artifact_sha256": "c" * 64,
                "database_identity_sha256": "d" * 64,
            }
            leaf_set = [f"{M0070[0]}.{M0070[1]}"]
            marker = build_restricted_recovery_marker(
                binding={**binding, "initiating_action": "deploy"},
                leaf_set=leaf_set,
            )
            self.assertEqual(marker["action"], "forward-resume")
            self.assertEqual(marker["initiating_action"], "deploy")
            self.assertEqual(marker["database_identity_sha256"], "d" * 64)
            self.assertEqual(marker["initial_leaf_set"], leaf_set)
            publish_restricted_recovery_marker(path=path, marker=marker)
            self.assertTrue(
                verify_restricted_recovery_marker(
                    path=path, expected_binding=binding, expected_leaf_set=leaf_set
                )["ok"]
            )
            completed = complete_restricted_recovery_marker(
                path=path, expected_binding=binding
            )
            self.assertFalse(path.exists())
            self.assertTrue(completed.is_file())
            self.assertEqual(stat.S_IMODE(completed.stat().st_mode), 0o600)
            self.assertEqual(
                complete_restricted_recovery_marker(
                    path=path, expected_binding=binding
                ),
                completed,
            )
            # Simulate death after the atomic active -> transition rename.
            path = root / "restricted-idempotent.json"
            publish_restricted_recovery_marker(path=path, marker=marker)
            completed_name = root / f"restricted-recovery.completed.{marker['marker_sha256']}.json"
            completed.unlink()
            transition = root / "restricted-recovery.transition.json"
            real_rename = _rename_noreplace
            rename_calls = 0

            def die_after_transition(**kwargs):
                nonlocal rename_calls
                rename_calls += 1
                result = real_rename(**kwargs)
                if rename_calls == 1:
                    raise OSError("simulated crash after transition rename")
                return result

            with patch(
                "stable.services.historical_calendar_release_b_handoff._rename_noreplace",
                side_effect=die_after_transition,
            ), self.assertRaisesRegex(OSError, "simulated crash"):
                complete_restricted_recovery_marker(
                    path=path, expected_binding=binding
                )
            self.assertFalse(path.exists())
            self.assertTrue(transition.is_file())
            retried = complete_restricted_recovery_marker(
                path=path, expected_binding=binding
            )
            self.assertEqual(retried, completed_name)
            self.assertFalse(path.exists())
            self.assertFalse(transition.exists())
            self.assertTrue(completed_name.is_file())
            # A same-UID replacement after authenticated read but before the
            # first rename must be restored at active rather than completed.
            completed_name.unlink()
            path = root / "restricted-race.json"
            publish_restricted_recovery_marker(path=path, marker=marker)
            replacement = root / "replacement.json"
            replacement_bytes = b'{"replacement":true}'
            replacement.write_bytes(replacement_bytes)
            replacement.chmod(0o600)
            real_rename = _rename_noreplace
            race_rename_calls = 0

            def replace_before_transition(**kwargs):
                nonlocal race_rename_calls
                race_rename_calls += 1
                if race_rename_calls == 1:
                    os.replace(replacement, path)
                return real_rename(**kwargs)

            with patch(
                "stable.services.historical_calendar_release_b_handoff._rename_noreplace",
                side_effect=replace_before_transition,
            ), self.assertRaisesRegex(ValueError, "marker inode changed"):
                complete_restricted_recovery_marker(
                    path=path, expected_binding=binding
                )
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), replacement_bytes)
            self.assertEqual(
                list(root.glob("restricted-recovery.completed.*.json")), []
            )
            self.assertFalse(transition.exists())
            # Recreate for the tamper branch below.
            path = root / "restricted-2.json"
            publish_restricted_recovery_marker(path=path, marker=marker)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["migration_leaf_set"] = [f"{M0069[0]}.{M0069[1]}", f"{M0070[0]}.{M0070[1]}"]
            path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            path.chmod(0o600)
            result = verify_restricted_recovery_marker(
                path=path, expected_binding=binding, expected_leaf_set=leaf_set
            )
            self.assertFalse(result["ok"])
            self.assertIn("marker_sha256", result["errors"])

    def test_marker_transition_slot_conflicts_and_late_active_race_fail_closed(self):
        from stable.services.historical_calendar_release_b_handoff import (
            _publish_trusted_json,
            _rename_noreplace,
            build_restricted_recovery_marker,
            complete_restricted_recovery_marker,
            publish_restricted_recovery_marker,
        )

        binding = {
            "candidate_commit": "a" * 40,
            "candidate_image_id": "sha256:" + "b" * 64,
            "artifact_sha256": "c" * 64,
            "database_identity_sha256": "d" * 64,
        }
        marker = build_restricted_recovery_marker(
            binding={**binding, "initiating_action": "deploy"},
            leaf_set=[f"{M0070[0]}.{M0070[1]}"],
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "restricted-recovery.json"
            transition = root / "restricted-recovery.transition.json"
            publish_restricted_recovery_marker(path=active, marker=marker)
            publish_restricted_recovery_marker(path=transition, marker=marker)
            with self.assertRaisesRegex(ValueError, "active and transition"):
                complete_restricted_recovery_marker(
                    path=active, expected_binding=binding
                )
            self.assertTrue(active.exists())
            self.assertTrue(transition.exists())

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "restricted-recovery.json"
            transition = root / "restricted-recovery.transition.json"
            forged = {**marker, "candidate_commit": "0" * 40}
            forged["marker_sha256"] = marker["marker_sha256"]
            _publish_trusted_json(path=transition, payload=forged)
            with self.assertRaisesRegex(ValueError, "verification failed"):
                complete_restricted_recovery_marker(
                    path=active, expected_binding=binding
                )
            self.assertTrue(transition.exists())

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "restricted-recovery.json"
            publish_restricted_recovery_marker(path=active, marker=marker)
            replacement_bytes = b'{"late-replacement":true}'
            real_rename = _rename_noreplace
            rename_calls = 0

            def create_active_before_final_rename(**kwargs):
                nonlocal rename_calls
                rename_calls += 1
                if rename_calls == 2:
                    active.write_bytes(replacement_bytes)
                    active.chmod(0o600)
                return real_rename(**kwargs)

            with patch(
                "stable.services.historical_calendar_release_b_handoff._rename_noreplace",
                side_effect=create_active_before_final_rename,
            ), patch(
                "stable.services.historical_calendar_release_b_handoff.os.unlink",
                side_effect=AssertionError("transition must not use path unlink"),
            ), self.assertRaisesRegex(ValueError, "active marker appeared"):
                complete_restricted_recovery_marker(
                    path=active, expected_binding=binding
                )
            self.assertEqual(active.read_bytes(), replacement_bytes)
            self.assertEqual(
                len(list(root.glob("restricted-recovery.completed.*.json"))), 1
            )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "restricted-recovery.json"
            publish_restricted_recovery_marker(path=active, marker=marker)
            ensured = active.stat(follow_symlinks=False)
            replacement = root / "same-content-replacement.json"
            publish_restricted_recovery_marker(path=replacement, marker=marker)
            os.replace(replacement, active)
            replacement_bytes = active.read_bytes()
            with self.assertRaisesRegex(ValueError, "inode changed after ensure"):
                complete_restricted_recovery_marker(
                    path=active,
                    expected_binding=binding,
                    expected_file_identity=(ensured.st_dev, ensured.st_ino),
                )
            self.assertEqual(active.read_bytes(), replacement_bytes)
            self.assertFalse((root / "restricted-recovery.transition.json").exists())
            self.assertEqual(
                list(root.glob("restricted-recovery.completed.*.json")), []
            )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "restricted-recovery.json"
            transition = root / "restricted-recovery.transition.json"
            completed = root / (
                f"restricted-recovery.completed.{marker['marker_sha256']}.json"
            )
            publish_restricted_recovery_marker(path=active, marker=marker)
            marker_bytes = active.read_bytes()
            destination_bytes = b'{"concurrent-completed-destination":true}'
            real_rename = _rename_noreplace
            calls = 0

            def create_completed_concurrently(**kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    completed.write_bytes(destination_bytes)
                    completed.chmod(0o600)
                return real_rename(**kwargs)

            with patch(
                "stable.services.historical_calendar_release_b_handoff._rename_noreplace",
                side_effect=create_completed_concurrently,
            ), self.assertRaises(FileExistsError):
                complete_restricted_recovery_marker(
                    path=active, expected_binding=binding
                )
            self.assertFalse(active.exists())
            self.assertEqual(transition.read_bytes(), marker_bytes)
            self.assertEqual(completed.read_bytes(), destination_bytes)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "restricted-recovery.json"
            transition = root / "restricted-recovery.transition.json"
            publish_restricted_recovery_marker(path=active, marker=marker)
            active_bytes = active.read_bytes()
            destination_bytes = b'{"concurrent-destination":true}'
            real_rename = _rename_noreplace
            calls = 0

            def create_destination_concurrently(**kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    transition.write_bytes(destination_bytes)
                    transition.chmod(0o600)
                return real_rename(**kwargs)

            with patch(
                "stable.services.historical_calendar_release_b_handoff._rename_noreplace",
                side_effect=create_destination_concurrently,
            ), self.assertRaises(FileExistsError):
                complete_restricted_recovery_marker(
                    path=active, expected_binding=binding
                )
            self.assertEqual(active.read_bytes(), active_bytes)
            self.assertEqual(transition.read_bytes(), destination_bytes)
            self.assertEqual(
                list(root.glob("restricted-recovery.completed.*.json")), []
            )

    def test_release_wrapper_passes_explicit_handoff_and_repair_binding(self):
        script = (ROOT / "deploy/run_release_tasks.sh").read_text(encoding="utf-8")
        for name in (
            "RELEASE_B_PREFLIGHT_ARTIFACT_PATH",
            "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256",
            "EXPECTED_CANDIDATE_COMMIT",
            "EXPECTED_CANDIDATE_IMAGE_ID",
            "RESTRICTED_RECOVERY_MARKER_PATH",
        ):
            self.assertIn(name, script)

    def test_only_verified_forward_resume_preserves_provenance_environment(self):
        ordinary_entries = (
            "deploy/deploy.sh",
            "deploy/deploy_lowcost.sh",
            "deploy/manual_release.sh",
            "deploy/rollback.sh",
            "deploy/rollback_lowcost.sh",
            "deploy/run_historical_initial_install_release.sh",
        )
        for relative in ordinary_entries:
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(
                "unset RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256",
                text,
                relative,
            )
        resume = (
            ROOT / "deploy/resume_migration_history_repair.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256="$RELEASE_B_PREFLIGHT_ARTIFACT_SHA256"',
            resume,
        )
        pinned = (ROOT / "deploy/resume_rollback_control_state.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256="$INITIATING_ARTIFACT_SHA256"',
            pinned,
        )


class MigrationHistoryRepairOperationsContractRedTests(TestCase):
    def test_rollback_exports_database_identity_from_fresh_artifact(self):
        for relative in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn('EXPECTED_PRODUCTION_DB_IDENTITY_SHA256="$(sed', text)
            self.assertIn(
                "export RELEASE_B_PREFLIGHT_ARTIFACT_SHA256 EXPECTED_CANDIDATE_COMMIT EXPECTED_CANDIDATE_IMAGE_ID EXPECTED_PRODUCTION_DB_IDENTITY_SHA256",
                text,
            )

    def test_partial_leaf_requires_marker_bound_forward_resume_action(self):
        from stable.services.historical_calendar_release_b_handoff import (
            authorize_handoff_action,
        )

        partial = [f"{M0068[0]}.{M0068[1]}", f"{M0070[0]}.{M0070[1]}"]
        for action in ("deploy", "manual-release", "rollback"):
            self.assertFalse(
                authorize_handoff_action(
                    leaf_set=partial, action=action, restricted_marker_ok=False
                )["ok"]
            )
        self.assertFalse(
            authorize_handoff_action(
                leaf_set=partial,
                action="forward-resume",
                restricted_marker_ok=False,
            )["ok"]
        )
        self.assertTrue(
            authorize_handoff_action(
                leaf_set=partial,
                action="forward-resume",
                restricted_marker_ok=True,
            )["ok"]
        )

    def test_active_marker_blocks_all_ordinary_actions_even_at_final_leaf(self):
        from stable.services.historical_calendar_release_b_handoff import (
            authorize_handoff_action,
        )

        final = [f"{M0072[0]}.{M0072[1]}"]
        for action in ("deploy", "manual-release", "rollback"):
            with self.subTest(action=action):
                self.assertFalse(
                    authorize_handoff_action(
                        leaf_set=final,
                        action=action,
                        restricted_marker_ok=False,
                        active_marker_present=True,
                    )["ok"]
                )

        initial = [f"{M0070[0]}.{M0070[1]}"]
        self.assertTrue(
            authorize_handoff_action(
                leaf_set=initial,
                action="forward-resume",
                restricted_marker_ok=True,
                active_marker_present=True,
            )["ok"]
        )
        self.assertFalse(
            authorize_handoff_action(
                leaf_set=initial,
                action="deploy",
                restricted_marker_ok=True,
                active_marker_present=True,
            )["ok"]
        )

    def test_create_handoff_command_cannot_bypass_active_final_marker(self):
        live = {
            "ok": True,
            "migration_leaf_set": [f"{M0072[0]}.{M0072[1]}"],
            "database_identity_sha256": "d" * 64,
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "restricted-recovery.json"
            marker.write_text("{}", encoding="utf-8")
            marker.chmod(0o600)
            for action in ("deploy", "manual-release", "rollback"):
                output = root / f"{action}.json"
                with self.subTest(action=action), patch(
                    "stable.management.commands."
                    "create_historical_calendar_release_b_handoff."
                    "collect_handoff_preflight",
                    return_value=live,
                ), self.assertRaises(CommandError):
                    call_command(
                        "create_historical_calendar_release_b_handoff",
                        output_path=str(output),
                        candidate_commit="a" * 40,
                        candidate_image_id="sha256:" + "b" * 64,
                        compose_file="docker-compose.prod.lowcost.yml",
                        deployment_lock_token_sha256="c" * 64,
                        action=action,
                        restricted_marker_path=str(marker),
                    )
                self.assertFalse(output.exists())

    def test_active_partial_marker_can_authorize_exact_final_boundary_only(self):
        from stable.services.historical_calendar_release_b_handoff import (
            build_restricted_recovery_marker,
            publish_restricted_recovery_marker,
            verify_restricted_marker_for_live_state,
        )

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "restricted.json"
            binding = {
                "candidate_commit": "a" * 40,
                "candidate_image_id": "sha256:" + "b" * 64,
                "artifact_sha256": "c" * 64,
                "database_identity_sha256": "d" * 64,
                "action": "forward-resume",
            }
            marker_leaf = [f"{M0070[0]}.{M0070[1]}"]
            marker = build_restricted_recovery_marker(
                binding=binding, leaf_set=marker_leaf
            )
            publish_restricted_recovery_marker(path=path, marker=marker)
            final = [f"{M0072[0]}.{M0072[1]}"]
            self.assertTrue(
                verify_restricted_marker_for_live_state(
                    path=path, expected_binding=binding, live_leaf_set=final
                )["ok"]
            )
            forged = {**binding, "candidate_commit": "0" * 40}
            self.assertFalse(
                verify_restricted_marker_for_live_state(
                    path=path, expected_binding=forged, live_leaf_set=final
                )["ok"]
            )
            unsafe = [f"{M0067[0]}.{M0067[1]}"]
            self.assertFalse(
                verify_restricted_marker_for_live_state(
                    path=path, expected_binding=binding, live_leaf_set=unsafe
                )["ok"]
            )
    def test_normal_deploy_does_not_hardcode_pre_repair_leaf(self):
        for relative in ("deploy/deploy.sh", "deploy/deploy_lowcost.sh"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn(
                "RELEASE_B_EXPECTED_MIGRATION_LEAF_SET=stable.0070_",
                text,
                relative,
            )

    def test_manual_release_generates_fresh_handoff_under_its_lock(self):
        text = (ROOT / "deploy/manual_release.sh").read_text(encoding="utf-8")
        lock = text.index("deployment_lock.sh acquire")
        handoff = text.index("run_historical_calendar_release_b_preflight.sh")
        release = text.index("run_release_tasks.sh")
        self.assertLess(lock, handoff)
        self.assertLess(handoff, release)
        self.assertIn("mktemp -d", text)
        self.assertIn("RELEASE_B_PREFLIGHT_ARTIFACT_SHA256", text)

    def test_resume_uses_old_artifact_only_as_provenance_then_creates_fresh_handoff(self):
        text = (ROOT / "deploy/resume_migration_history_repair.sh").read_text(
            encoding="utf-8"
        )
        marker = text.index("verify_historical_calendar_restricted_recovery")
        fresh = text.index("run_historical_calendar_release_b_preflight.sh")
        release = text.index("run_application_release.sh")
        self.assertLess(marker, fresh)
        self.assertLess(fresh, release)
        self.assertIn("RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256", text)

    def test_restricted_marker_transitions_at_successful_migrate_boundary(self):
        text = (ROOT / "deploy/docker/run-release-tasks.sh").read_text(
            encoding="utf-8"
        )
        migrate = text.index("manage.py migrate --noinput")
        transition = text.index("complete_historical_calendar_restricted_recovery")
        collectstatic = text.index("manage.py collectstatic --noinput")
        self.assertLess(migrate, transition)
        self.assertLess(transition, collectstatic)
        self.assertNotIn("--if-present", text)
        self.assertIn('--attempt-mode="$RESTRICTED_RECOVERY_ATTEMPT_MODE"', text)
        self.assertIn('--artifact-path="$RELEASE_B_PREFLIGHT_ARTIFACT_PATH"', text)

    def test_active_recovery_intent_is_persisted_immediately_before_migrate(self):
        text = (ROOT / "deploy/docker/run-release-tasks.sh").read_text(
            encoding="utf-8"
        )
        verifier = text.index("verify_historical_calendar_release_b_handoff")
        intent = text.index("ensure_historical_calendar_recovery_intent")
        migrate = text.index("manage.py migrate --noinput")
        self.assertLess(verifier, intent)
        self.assertLess(intent, migrate)
        between = text[intent:migrate]
        self.assertNotIn("collectstatic", between)
        self.assertNotIn("record_historical_calendar", text)

    def test_migrate_failure_leaves_preexisting_intent_without_post_failure_record(self):
        script = (ROOT / "deploy/docker/run-release-tasks.sh").read_text(
            encoding="utf-8"
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            container = root / "container"
            (container / "server").mkdir(parents=True)
            artifact = root / "fresh.json"
            artifact.write_text(
                '{"handoff_action":"deploy","recovery_intent_mode":"required"}\n',
                encoding="utf-8",
            )
            script_path = root / "run.sh"
            script_path.write_text(script.replace("/app", str(container)), encoding="utf-8")
            script_path.chmod(0o755)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            log = root / "calls.log"
            fake_python = fake_bin / "python"
            fake_python.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$REPAIR_CALL_LOG\"\n"
                "case \" $* \" in *ensure_historical_calendar_recovery_intent*) printf '%s\\n' '{\"marker_device\": 1, \"marker_inode\": 2}' ;; esac\n"
                "case \" $* \" in *' migrate --noinput '*) exit 47 ;; esac\nexit 0\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            result = subprocess.run(
                ["sh", str(script_path)],
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "REPAIR_CALL_LOG": str(log),
                    "RELEASE_B_PREFLIGHT_ARTIFACT_PATH": str(artifact),
                    "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256": "a" * 64,
                    "RESTRICTED_RECOVERY_MARKER_PATH": str(root / "marker.json"),
                    "RESTRICTED_RECOVERY_ATTEMPT_MODE": "required",
                    "EXPECTED_CANDIDATE_COMMIT": "c" * 40,
                    "EXPECTED_CANDIDATE_IMAGE_ID": "sha256:" + "d" * 64,
                },
                text=True,
                capture_output=True,
                check=False,
            )
            calls = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(result.returncode, 47)
        intent = next(i for i, call in enumerate(calls) if "ensure_historical_calendar_recovery_intent" in call)
        migrate = next(i for i, call in enumerate(calls) if "migrate --noinput" in call)
        self.assertLess(intent, migrate)
        self.assertFalse(any("record_historical_calendar" in call for call in calls))

    def test_normal_release_ignores_stale_provenance_and_uses_fresh_artifact(self):
        script = (ROOT / "deploy/docker/run-release-tasks.sh").read_text(
            encoding="utf-8"
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            container = root / "container"
            (container / "server").mkdir(parents=True)
            artifact = root / "fresh.json"
            artifact.write_text(
                '{"handoff_action":"deploy","recovery_intent_mode":"required"}\n',
                encoding="utf-8",
            )
            script_path = root / "run.sh"
            script_path.write_text(
                script.replace("/app", str(container)), encoding="utf-8"
            )
            script_path.chmod(0o755)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            log = root / "calls.log"
            fake_python = fake_bin / "python"
            fake_python.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$REPAIR_CALL_LOG\"\n"
                "case \" $* \" in *ensure_historical_calendar_recovery_intent*) printf '%s\\n' '{\"marker_device\": 1, \"marker_inode\": 2}' ;; esac\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            result = subprocess.run(
                ["sh", str(script_path)],
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "REPAIR_CALL_LOG": str(log),
                    "RELEASE_B_PREFLIGHT_ARTIFACT_PATH": str(artifact),
                    "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256": "a" * 64,
                    "RESTRICTED_RECOVERY_MARKER_PATH": str(root / "marker.json"),
                    "RESTRICTED_RECOVERY_ATTEMPT_MODE": "required",
                    "RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256": "b" * 64,
                    "EXPECTED_CANDIDATE_COMMIT": "c" * 40,
                    "EXPECTED_CANDIDATE_IMAGE_ID": "sha256:" + "d" * 64,
                },
                text=True,
                capture_output=True,
                check=False,
            )
            calls = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(result.returncode, 0, result.stderr)
        intent = next(
            call
            for call in calls
            if "ensure_historical_calendar_recovery_intent" in call
        )
        migrate_index = next(
            i for i, call in enumerate(calls) if "migrate --noinput" in call
        )
        complete_index = next(
            i
            for i, call in enumerate(calls)
            if "complete_historical_calendar_restricted_recovery" in call
        )
        self.assertIn("--provenance-artifact-sha256=", intent)
        self.assertNotIn("b" * 64, intent)
        self.assertIn(
            f"--provenance-artifact-sha256={'a' * 64}",
            calls[complete_index],
        )
        self.assertLess(
            next(
                i
                for i, call in enumerate(calls)
                if "ensure_historical_calendar_recovery_intent" in call
            ),
            migrate_index,
        )
        self.assertLess(migrate_index, complete_index)

    def test_collectstatic_failure_occurs_after_restricted_marker_transition(self):
        script = (ROOT / "deploy/docker/run-release-tasks.sh").read_text(
            encoding="utf-8"
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            container = root / "container"
            (container / "server").mkdir(parents=True)
            artifact = root / "fresh.json"
            artifact.write_text(
                '{"handoff_action":"forward-resume","recovery_intent_mode":"required"}\n',
                encoding="utf-8",
            )
            script_path = root / "run.sh"
            script_path.write_text(script.replace("/app", str(container)), encoding="utf-8")
            script_path.chmod(0o755)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            log = root / "calls.log"
            fake_python = fake_bin / "python"
            fake_python.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$REPAIR_CALL_LOG\"\n"
                "case \" $* \" in *ensure_historical_calendar_recovery_intent*) printf '%s\\n' '{\"marker_device\": 1, \"marker_inode\": 2}' ;; esac\n"
                "case \" $* \" in *collectstatic*) exit 31 ;; esac\nexit 0\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            result = subprocess.run(
                ["sh", str(script_path)],
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "REPAIR_CALL_LOG": str(log),
                    "RELEASE_B_PREFLIGHT_ARTIFACT_PATH": str(artifact),
                    "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256": "a" * 64,
                    "RESTRICTED_RECOVERY_ACTIVE": "true",
                    "RESTRICTED_RECOVERY_MARKER_PATH": str(root / "marker.json"),
                    "RESTRICTED_RECOVERY_ATTEMPT_MODE": "required",
                    "RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256": "b" * 64,
                    "EXPECTED_CANDIDATE_COMMIT": "c" * 40,
                    "EXPECTED_CANDIDATE_IMAGE_ID": "sha256:" + "d" * 64,
                },
                text=True,
                capture_output=True,
                check=False,
            )
            calls = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(result.returncode, 31)
        transition = next(i for i, call in enumerate(calls) if "complete_historical_calendar_restricted_recovery" in call)
        collectstatic = next(i for i, call in enumerate(calls) if "collectstatic" in call)
        self.assertLess(transition, collectstatic)

    def test_writer_gate_uses_real_historical_backfill_flags(self):
        from stable.services.historical_calendar_release_b_handoff import (
            collect_writer_activity,
        )

        race_data_flags = (
            "RACE_DATA_SYNC_ENABLED",
            "RACE_DATA_SYNC_SCHEDULER_ENABLED",
            "RACE_DATA_SYNC_ALLOW_NETWORK",
            "RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED",
            "RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED",
            "RACE_DATA_SYNC_RACECARD_APPLY_ENABLED",
            "RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED",
            "RACE_DATA_SYNC_RESULT_APPLY_ENABLED",
            "RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED",
            "RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED",
        )
        with patch.dict(
            os.environ,
            {
                **{name: "false" for name in race_data_flags},
                "HISTORICAL_RACE_BACKFILL_ENABLED": "false",
                "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK": "false",
            },
            clear=False,
        ):
            result = collect_writer_activity()
        for name in race_data_flags:
            self.assertIn(name, result["flags"])
        self.assertIn("HISTORICAL_RACE_BACKFILL_ENABLED", result["flags"])
        self.assertIn("HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK", result["flags"])
        self.assertNotIn("HISTORICAL_NETWORK_ENABLED", result["flags"])

    def test_shell_contracts_have_no_eval_or_grep_marker_parser(self):
        for relative in (
            "deploy/run_release_tasks.sh",
            "deploy/run_application_release.sh",
            "deploy/resume_migration_history_repair.sh",
            "deploy/smoke_migration_history_repair_old_image.sh",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("eval ", text, relative)
        resume = (ROOT / "deploy/resume_migration_history_repair.sh").read_text(encoding="utf-8")
        self.assertIn("verify_historical_calendar_restricted_recovery", resume)
        self.assertNotIn("grep -Fq", resume)
        lock = resume.index("deployment_lock.sh acquire")
        marker_verify = resume.index("verify_historical_calendar_restricted_recovery")
        forward = resume.index("run_application_release.sh")
        self.assertLess(lock, marker_verify)
        self.assertLess(marker_verify, forward)

    def test_old_image_smoke_checks_real_flags_and_all_write_kinds(self):
        text = (ROOT / "deploy/smoke_migration_history_repair_old_image.sh").read_text(encoding="utf-8")
        self.assertIn("HISTORICAL_RACE_BACKFILL_ENABLED=false", text)
        self.assertIn("HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false", text)
        self.assertNotIn("HISTORICAL_NETWORK_ENABLED", text)
        self.assertNotIn("pg_stat_user_tables", text)
        self.assertIn("NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT", text)
        self.assertIn("default_transaction_read_only = on", text)
        self.assertIn("REVOKE ALL ON ALL TABLES", text)
        self.assertIn("REVOKE INSERT, UPDATE, DELETE, TRUNCATE", text)
        self.assertIn("REVOKE USAGE, UPDATE ON ALL SEQUENCES", text)
        self.assertIn("REVOKE CREATE ON SCHEMA", text)
        self.assertIn("REVOKE CREATE ON DATABASE", text)
        self.assertIn("REVOKE TEMPORARY ON DATABASE", text)
        self.assertIn("current_setting('\\''transaction_read_only'\\'')", text)
        self.assertIn("insert into django_migrations", text)
        self.assertIn("old-image-db-read-only-verified", text)
        self.assertIn("before_audit_digest", text)
        self.assertIn("after_audit_digest", text)
        self.assertIn("docker logs", text)
        self.assertNotIn("common_env=", text)
        self.assertIn(r"\getenv smoke_password SMOKE_ROLE_PASSWORD", text)
        self.assertNotIn("PASSWORD '$SMOKE_APP_PASSWORD'", text)
        self.assertIn("old-image-role-auth-verified", text)
        role_auth = text.index("old-image-role-auth-verified")
        self.assertLess(role_auth, text.index("before_audit_digest="))
        self.assertLess(role_auth, text.index("run_old_image rm"))
        self.assertIn('-h 127.0.0.1 -U "$SMOKE_APP_ROLE"', text)

    def test_old_image_smoke_auth_failure_is_before_any_old_image_start(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            log = root / "docker.log"
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                "#!/bin/sh\n"
                "printf 'docker %s\\n' \"$*\" >> \"$SMOKE_TEST_LOG\"\n"
                "case \"${1:-}\" in\n"
                "  inspect) printf '%s\\n' true ;;\n"
                "  image) printf '%s\\n' sha256:pinned-old ;;\n"
                "  exec)\n"
                "    case \" $* \" in\n"
                "      *\" -h 127.0.0.1 \"*) echo 'FATAL: password authentication failed' >&2; exit 2 ;;\n"
                "      *\"select name from django_migrations\"*)\n"
                "        printf '%s\\n' 0068_race_data_sync_pipeline_a_field_audit 0070_horse_identity_evidence_commit_receipt ;;\n"
                "    esac ;;\n"
                "  run) echo 'old image unexpectedly started' >&2; exit 97 ;;\n"
                "esac\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            secret = "must-not-appear-in-command-log"
            result = subprocess.run(
                ["sh", str(ROOT / "deploy/smoke_migration_history_repair_old_image.sh")],
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "SMOKE_TEST_LOG": str(log),
                    "MIGRATION_REPAIR_SMOKE_ACK": "isolated-ephemeral-postgres",
                    "EXPECTED_PARTIAL_STATE": "0068-only",
                    "PINNED_OLD_IMAGE_ID": "sha256:pinned-old",
                    "POSTGRES_PASSWORD": secret,
                },
                text=True,
                capture_output=True,
                check=False,
            )
            calls = log.read_text(encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("role authentication failed before startup", result.stderr)
        self.assertNotIn("docker run ", calls)
        self.assertNotIn(secret, calls)

    def test_lock_hash_path_matches_lock_implementation(self):
        lock = (ROOT / "deploy/deployment_lock.sh").read_text(encoding="utf-8")
        preflight = (ROOT / "deploy/run_historical_calendar_release_b_preflight.sh").read_text(encoding="utf-8")
        release = (ROOT / "deploy/run_release_tasks.sh").read_text(encoding="utf-8")
        self.assertIn('$LOCK_DIR/token_sha256', lock)
        self.assertIn('/token_sha256', preflight)
        self.assertIn('/token_sha256', release)

    def test_release_b_preflight_allowlists_current_0072_leaf(self):
        preflight = (
            ROOT / "deploy/run_historical_calendar_release_b_preflight.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "stable.0072_add_extended_racing_regions)", preflight
        )
        self.assertIn(
            "--expected-migration-leaf-set=stable.0072_add_extended_racing_regions",
            preflight,
        )

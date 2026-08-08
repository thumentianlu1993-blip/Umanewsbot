from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


UTC = timezone.utc


def _fixture_rows() -> tuple[list[dict], list[dict]]:
    receipts = [
        {
            "id": 1,
            "created_at": datetime(2026, 8, 2, 5, 7, 40, 911578, tzinfo=UTC),
            "updated_at": datetime(2026, 8, 2, 5, 7, 40, 911596, tzinfo=UTC),
            "approved_sha256": "a" * 64,
            "artifact_sha256": "b" * 64,
            "approved_by": "fixture",
            "approved_profile_ids": [2, 1],
            "before_after": {"before": None, "after": {"id": 1}},
            "evidence_summary": {"ok": True},
            "result_payload": {"written": 1},
            "operation_log_id": 108491,
        }
    ]
    operations = [
        {
            "id": 108491,
            "action_type": "p0_horse_identity_evidence_commit",
            "target_type": "horse_identity_evidence",
            "target_id": "1",
            "detail": "fixture",
            "created_at": datetime(2026, 8, 2, 5, 7, 40, 904321, tzinfo=UTC),
            "admin_id": None,
        }
    ]
    return receipts, operations


class ProductionAuditCanonicalizationRedTests(SimpleTestCase):
    def test_fixed_named_rows_match_the_runtime_audit_representation(self):
        from stable.services.historical_calendar_release_b_schema import (
            build_production_audit_from_rows,
        )

        receipts, operations = _fixture_rows()
        audit = build_production_audit_from_rows(
            receipts=receipts,
            operations=operations,
            database_identity_sha256="d" * 64,
        )
        self.assertEqual(
            audit,
            {
                "canonicalization_version": "named-object-scalar-fk/v1",
                "database_identity_sha256": "d" * 64,
                "receipt_count": 1,
                "receipt_rows_sha256": (
                    "473feb6d5d62a91909f8765185941776e"
                    "a37772e8c50ea0b62a83a05c602f650"
                ),
                "receipt_ids": [1],
                "operation_log_count": 1,
                "operation_log_rows_sha256": (
                    "f64d2c1bb966bf2cbefe757a0d25efc0"
                    "2ab1305a3e7752159e925b367406ce1d"
                ),
                "operation_log_ids": [108491],
                "operation_log_fk_sha256": (
                    "03bad88b02cd5eb9833a421285bd79cb"
                    "6cedb9577da8c8b5be01c3d994d11a23"
                ),
                "operation_log_fk_ids": [108491],
                "time_bounds": {
                    "receipt_created_at": {
                        "min": "2026-08-02T05:07:40.911578Z",
                        "max": "2026-08-02T05:07:40.911578Z",
                    },
                    "receipt_updated_at": {
                        "min": "2026-08-02T05:07:40.911596Z",
                        "max": "2026-08-02T05:07:40.911596Z",
                    },
                    "operation_log_created_at": {
                        "min": "2026-08-02T05:07:40.904321Z",
                        "max": "2026-08-02T05:07:40.904321Z",
                    },
                },
            },
        )

    def test_legacy_positional_rows_and_nested_fk_do_not_match_named_runtime(self):
        from stable.services.historical_calendar_release_b_schema import (
            _digest,
            build_production_audit_from_rows,
            compare_production_audit_baseline,
        )

        receipts, operations = _fixture_rows()
        live = build_production_audit_from_rows(
            receipts=receipts,
            operations=operations,
            database_identity_sha256="d" * 64,
        )
        positional_receipts = [list(row.values()) for row in receipts]
        positional_operations = [list(row.values()) for row in operations]
        legacy = {
            **live,
            "receipt_rows_sha256": _digest(positional_receipts),
            "operation_log_rows_sha256": _digest(positional_operations),
            "operation_log_fk_sha256": _digest([[108491]]),
        }
        result = compare_production_audit_baseline(expected=legacy, live=live)
        self.assertEqual(
            result["drift_fields"],
            [
                "receipt_rows_sha256",
                "operation_log_rows_sha256",
                "operation_log_fk_sha256",
            ],
        )

    def test_identity_lists_reject_missing_extra_and_wrong_order(self):
        from stable.services.historical_calendar_release_b_schema import (
            build_production_audit_from_rows,
            compare_production_audit_baseline,
        )

        receipts, operations = _fixture_rows()
        live = build_production_audit_from_rows(
            receipts=receipts,
            operations=operations,
            database_identity_sha256="d" * 64,
        )
        for field, replacement in (
            ("receipt_ids", []),
            ("receipt_ids", [1, 2]),
            ("operation_log_fk_ids", [108491, 108492]),
        ):
            expected = {**live, field: replacement}
            with self.subTest(field=field, replacement=replacement):
                result = compare_production_audit_baseline(expected=expected, live=live)
                self.assertEqual(result["drift_fields"], [field])

        for field, ordered in (
            ("receipt_ids", [1, 2]),
            ("operation_log_ids", [108491, 108492]),
            ("operation_log_fk_ids", [108491, 108492]),
        ):
            ordered_live = {**live, field: ordered}
            expected = {**ordered_live, field: list(reversed(ordered))}
            with self.subTest(field=field, replacement="wrong-order"):
                result = compare_production_audit_baseline(
                    expected=expected, live=ordered_live
                )
                self.assertEqual(result["drift_fields"], [field])

        expected = {
            **live,
            "time_bounds": {
                **live["time_bounds"],
                "receipt_updated_at": {"min": None, "max": None},
            },
        }
        result = compare_production_audit_baseline(expected=expected, live=live)
        self.assertEqual(result["drift_fields"], ["time_bounds"])

    def test_generator_accepts_only_the_exact_repair_recorder_state(self):
        from stable.services.historical_calendar_release_b_schema import (
            validate_production_audit_recorder_state,
        )

        expected = {
            ("stable", "0067_historical_calendar_release_a"),
            ("stable", "0070_horse_identity_evidence_commit_receipt"),
        }
        known = expected | {
            ("stable", "0068_race_data_sync_pipeline_a_field_audit"),
            ("stable", "0069_race_data_sync_pipeline_a_ledger_guards"),
            ("stable", "0071_historical_calendar_release_b"),
        }
        self.assertEqual(
            validate_production_audit_recorder_state(
                recorded_nodes=expected, known_nodes=known
            ),
            [
                "stable.0067_historical_calendar_release_a",
                "stable.0070_horse_identity_evidence_commit_receipt",
            ],
        )
        invalid_states = (
            expected - {("stable", "0067_historical_calendar_release_a")},
            expected | {("stable", "0068_race_data_sync_pipeline_a_field_audit")},
            expected | {("stable", "0071_historical_calendar_release_b")},
            expected | {("stable", "9999_unknown")},
        )
        for recorded in invalid_states:
            with self.subTest(recorded=sorted(recorded)), self.assertRaises(ValueError):
                validate_production_audit_recorder_state(
                    recorded_nodes=recorded, known_nodes=known
                )

    def test_loader_rejects_old_or_incomplete_baseline_contract(self):
        from stable.services.historical_calendar_release_b_schema import (
            load_reviewed_production_audit,
        )

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "migration-history-repair-production-audit/v1",
                        "canonicalization_version": "named-object-scalar-fk/v1",
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "stable.services.historical_calendar_release_b_schema.AUDIT_PATH",
                path,
            ), self.assertRaises(ValueError):
                load_reviewed_production_audit()

    def test_generator_command_prints_one_canonical_json_payload(self):
        payload = {
            "schema_version": "migration-history-repair-production-audit/v2",
            "canonicalization_version": "named-object-scalar-fk/v1",
            "captured_at": "2026-08-08T11:10:27Z",
            "database_identity_sha256": "d" * 64,
        }
        output = StringIO()
        with patch(
            "stable.management.commands.generate_migration_history_production_audit."
            "capture_reviewed_production_audit",
            return_value=payload,
        ) as capture:
            call_command(
                "generate_migration_history_production_audit", stdout=output
            )
        capture.assert_called_once_with()
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        self.assertEqual(output.getvalue(), encoded + "\n")
        self.assertEqual(
            hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            hashlib.sha256(
                output.getvalue().rstrip("\n").encode("utf-8")
            ).hexdigest(),
        )

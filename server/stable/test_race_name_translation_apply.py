import hashlib
import importlib.util
import json
import resource
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.db import DatabaseError, IntegrityError, connection, connections, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from stable.models import (
    HistoricalRaceEventTarget,
    OperationLog,
    RaceEvent,
    RaceSeries,
    RacingRegion,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
APPLY_PATH = REPO_ROOT / "runtime/tools/apply_race_name_translation_manifest.py"
VERIFY_PATH = REPO_ROOT / "runtime/tools/verify_race_name_translation_manifest.py"


def load_apply_module():
    spec = importlib.util.spec_from_file_location("race_name_translation_apply", APPLY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_verify_module():
    spec = importlib.util.spec_from_file_location("race_name_translation_verify", VERIFY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RaceNameTranslationApplyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.apply = load_apply_module()
        cls.verify = load_verify_module()

    def setUp(self):
        self.series = RaceSeries.objects.create(
            key="japan-test-stakes",
            country_region=RacingRegion.JAPAN,
            canonical_name_original="Test Stakes",
            chinese_name="",
        )
        self.event = RaceEvent.objects.create(
            year=2025,
            slug="test-stakes-2025",
            series_key=self.series.key,
            original_name="Test Stakes",
            chinese_name="Test Stakes",
            country_region=RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G3",
            surface="turf",
            race_series=self.series,
        )

    def build_plan(self):
        series_before = self.apply.canonical_model_row(self.series)
        event_before = self.apply.canonical_model_row(self.event)
        return {
            "schemaVersion": "race-name-translation-rollback-before.v3",
            "sourceManifestSha256": "a" * 64,
            "eventScope": {
                "series": [
                    {
                        "seriesId": self.series.id,
                        "beforeRowSha256": series_before["rowSha256"],
                    }
                ],
                "events": [
                    {
                        "eventId": self.event.id,
                        "raceSeriesId": self.series.id,
                        "beforeRowSha256": event_before["rowSha256"],
                    }
                ],
            },
            "series": [
                {
                    "seriesId": self.series.id,
                    "before": series_before,
                    "after": {"chineseName": "测试锦标"},
                }
            ],
            "events": [
                {
                    "eventId": self.event.id,
                    "actionType": "translate",
                    "before": event_before,
                    "after": {"chineseName": "测试锦标"},
                }
            ],
            "historicalTargets": [],
        }

    def rollback_audit_context(self, batch_id):
        return {
            "batchId": batch_id,
            "bundleIndexSha256": "1" * 64,
            "bundleContentSha256": "4" * 64,
            "toolSha256": "5" * 64,
            "verifierSha256": "6" * 64,
            "manifestSha256": "7" * 64,
            "rollbackSha256": "2" * 64,
            "productionBeforeSha256": "3" * 64,
            "dryRunSha256": "8" * 64,
        }

    def test_canonical_model_row_covers_every_concrete_field(self):
        snapshot = self.apply.canonical_model_row(self.event)
        expected = sorted(field.attname for field in self.event._meta.concrete_fields)
        self.assertEqual(sorted(snapshot["fields"]), expected)
        self.assertEqual(
            snapshot["rowSha256"],
            self.apply.sha256_json(snapshot["fields"]),
        )

    def test_verify_only_performs_full_cas_without_writes(self):
        result = self.apply.execute_plan(
            self.build_plan(),
            commit=False,
            audit_context={"batchId": "a" * 32},
        )
        self.assertEqual(result["seriesCount"], 1)
        self.assertEqual(result["eventCount"], 1)
        self.series.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.series.chinese_name, "")
        self.assertEqual(self.event.chinese_name, "Test Stakes")
        self.assertEqual(OperationLog.objects.count(), 0)

    def test_production_count_guard_requires_supplemental_event(self):
        self.apply._assert_production_target_counts(
            {
                "series": [{}] * 1300,
                "events": [{}] * 8883,
            }
        )
        with self.assertRaisesRegex(
            self.apply.ApplyError,
            "production target counts must be 1300/8883",
        ):
            self.apply._assert_production_target_counts(
                {
                    "series": [{}] * 1300,
                    "events": [{}] * 8664,
                }
            )

    def test_commit_is_atomic_and_creates_exactly_one_audit_log(self):
        result = self.apply.execute_plan(
            self.build_plan(),
            commit=True,
            audit_context={
                "batchId": "a" * 32,
                "operator": "mentianlu_via_codex",
                "manifestSha256": "a" * 64,
            },
        )
        self.assertEqual(result["identityCorrectionCount"], 0)
        self.series.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.series.chinese_name, "测试锦标")
        self.assertEqual(self.event.chinese_name, "测试锦标")
        log = OperationLog.objects.get()
        self.assertEqual(log.action_type, "race_name_translations_applied")
        self.assertEqual(log.target_type, "race_name_translation_batch")
        self.assertEqual(log.target_id, "a" * 32)
        self.assertEqual(json.loads(log.detail)["operator"], "mentianlu_via_codex")

    def test_any_concrete_field_drift_blocks_entire_batch(self):
        plan = self.build_plan()
        self.event.racecourse = "Kyoto"
        self.event.save(update_fields={"racecourse"})
        with self.assertRaisesRegex(self.apply.ApplyError, "full-row CAS"):
            self.apply.execute_plan(
                plan,
                commit=True,
                audit_context={"batchId": "a" * 32},
            )
        self.series.refresh_from_db()
        self.assertEqual(self.series.chinese_name, "")
        self.assertEqual(OperationLog.objects.count(), 0)

    def test_complete_series_event_scope_blocks_new_fallback_event(self):
        plan = self.build_plan()
        RaceEvent.objects.create(
            year=2026,
            slug="test-stakes-2026",
            series_key=self.series.key,
            original_name="Test Stakes",
            chinese_name="Test Stakes",
            country_region=RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G3",
            surface="turf",
            race_series=self.series,
        )
        with self.assertRaisesRegex(
            self.apply.ApplyError,
            "complete series scope mismatch",
        ):
            self.apply.execute_plan(
                plan,
                commit=True,
                audit_context={"batchId": "e" * 32},
            )
        self.series.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.series.chinese_name, "")
        self.assertEqual(self.event.chinese_name, "Test Stakes")
        self.assertEqual(OperationLog.objects.count(), 0)

    def test_complete_series_scope_blocks_non_action_parent_drift(self):
        plan = self.build_plan()
        source_only = RaceSeries.objects.create(
            key="japan-source-only",
            country_region=RacingRegion.JAPAN,
            canonical_name_original="Source Only",
            chinese_name="",
        )
        plan["eventScope"]["series"].append(
            {
                "seriesId": source_only.id,
                "beforeRowSha256": self.apply.canonical_model_row(source_only)[
                    "rowSha256"
                ],
            }
        )
        source_only.key = "japan-source-only-drifted"
        source_only.save(update_fields={"key"})
        with self.assertRaisesRegex(
            self.apply.ApplyError,
            "RaceSeries event-scope full-row CAS mismatch",
        ):
            self.apply.execute_plan(
                plan,
                commit=True,
                audit_context={"batchId": "h" * 32},
            )
        self.series.refresh_from_db()
        self.assertEqual(self.series.chinese_name, "")
        self.assertEqual(OperationLog.objects.count(), 0)

    def test_non_action_parent_drift_blocks_verifier_and_rollback(self):
        plan = self.build_plan()
        source_only = RaceSeries.objects.create(
            key="japan-source-after-apply",
            country_region=RacingRegion.JAPAN,
            canonical_name_original="Source After Apply",
            chinese_name="",
        )
        plan["eventScope"]["series"].append(
            {
                "seriesId": source_only.id,
                "beforeRowSha256": self.apply.canonical_model_row(source_only)[
                    "rowSha256"
                ],
            }
        )
        context = self.rollback_audit_context("i" * 32)
        self.apply.execute_plan(plan, commit=True, audit_context=context)
        source_only.key = "japan-source-after-apply-drifted"
        source_only.save(update_fields={"key"})

        with self.assertRaisesRegex(
            self.verify.VerificationError,
            "RaceSeries event-scope full-row CAS mismatch",
        ):
            self.verify.verify_database(
                plan,
                batch_id="i" * 32,
                mode="applied",
            )
        with self.assertRaisesRegex(
            self.apply.ApplyError,
            "RaceSeries event-scope full-row CAS mismatch",
        ):
            self.apply.execute_rollback(plan, audit_context=context)
        self.series.refresh_from_db()
        self.assertEqual(self.series.chinese_name, "测试锦标")
        self.assertFalse(
            OperationLog.objects.filter(
                action_type="race_name_translations_rolled_back",
                target_id="i" * 32,
            ).exists()
        )

    def test_audit_failure_rolls_back_all_business_writes(self):
        with patch.object(OperationLog.objects, "create", side_effect=RuntimeError("audit failed")):
            with self.assertRaisesRegex(RuntimeError, "audit failed"):
                self.apply.execute_plan(
                    self.build_plan(),
                    commit=True,
                    audit_context={"batchId": "a" * 32},
                )
        self.series.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.series.chinese_name, "")
        self.assertEqual(self.event.chinese_name, "Test Stakes")

    def test_repeated_commit_does_not_create_second_log(self):
        plan = self.build_plan()
        context = {"batchId": "a" * 32}
        self.apply.execute_plan(plan, commit=True, audit_context=context)
        with self.assertRaisesRegex(self.apply.ApplyError, "already applied"):
            self.apply.execute_plan(plan, commit=True, audit_context=context)
        self.assertEqual(
            OperationLog.objects.filter(
                action_type="race_name_translations_applied",
                target_id="a" * 32,
            ).count(),
            1,
        )

    def test_independent_verifier_and_object_rollback(self):
        plan = self.build_plan()
        context = self.rollback_audit_context("a" * 32)
        self.apply.execute_plan(plan, commit=True, audit_context=context)
        applied = self.verify.verify_database(
            plan,
            batch_id="a" * 32,
            mode="applied",
        )
        self.assertEqual(applied["seriesCount"], 1)
        apply_detail = json.loads(
            OperationLog.objects.get(
                action_type="race_name_translations_applied"
            ).detail
        )
        self.series.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(
            self.series.updated_at.isoformat().replace("+00:00", "Z"),
            apply_detail["appliedAt"],
        )
        self.assertEqual(
            self.event.updated_at.isoformat().replace("+00:00", "Z"),
            apply_detail["appliedAt"],
        )
        self.apply.execute_rollback(plan, audit_context=context)
        rolled_back = self.verify.verify_database(
            plan,
            batch_id="a" * 32,
            mode="rolled-back",
            expected_rollback_artifact_sha256="2" * 64,
        )
        self.assertEqual(rolled_back["eventCount"], 1)
        self.series.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.series.chinese_name, "")
        self.assertEqual(self.event.chinese_name, "Test Stakes")
        self.assertEqual(
            OperationLog.objects.filter(
                action_type="race_name_translations_rolled_back"
            ).count(),
            1,
        )
        detail = json.loads(
            OperationLog.objects.get(
                action_type="race_name_translations_rolled_back"
            ).detail
        )
        self.assertEqual(detail["rollbackSha256"], "2" * 64)
        self.assertEqual(
            detail["rollbackAfterAggregateSha256"],
            rolled_back["snapshotSha256"],
        )
        self.assertEqual(
            self.series.updated_at.isoformat().replace("+00:00", "Z"),
            detail["rolledBackAt"],
        )
        self.assertEqual(
            self.event.updated_at.isoformat().replace("+00:00", "Z"),
            detail["rolledBackAt"],
        )
        with self.assertRaisesRegex(
            self.verify.VerificationError,
            "rollback artifact SHA mismatch",
        ):
            self.verify.verify_database(
                plan,
                batch_id="a" * 32,
                mode="rolled-back",
                expected_rollback_artifact_sha256="c" * 64,
            )

    def test_independent_verifier_rejects_stale_bundle_operation_log(self):
        plan = self.build_plan()
        context = self.rollback_audit_context("f" * 32)
        self.apply.execute_plan(plan, commit=True, audit_context=context)

        self.verify.verify_database(
            plan,
            batch_id="f" * 32,
            mode="applied",
            expected_audit_identity={
                field: context[field]
                for field in (
                    "bundleIndexSha256",
                    "bundleContentSha256",
                    "toolSha256",
                    "verifierSha256",
                    "manifestSha256",
                    "productionBeforeSha256",
                    "dryRunSha256",
                    "rollbackSha256",
                )
            },
        )
        with self.assertRaisesRegex(
            self.verify.VerificationError,
            "OperationLog bundle identity mismatch: bundleIndexSha256",
        ):
            self.verify.verify_database(
                plan,
                batch_id="f" * 32,
                mode="applied",
                expected_audit_identity={
                    "bundleIndexSha256": "9" * 64,
                },
            )

    def test_compact_execution_plan_applies_verifies_and_rolls_back(self):
        plan = self.build_plan()
        plan["schemaVersion"] = "race-name-translation-execution-plan.v1"
        mutable_by_kind = {
            "series": {"chinese_name", "updated_at"},
            "events": {
                "chinese_name",
                "race_series_id",
                "series_key",
                "updated_at",
            },
            "historicalTargets": {"race_series_id", "updated_at"},
        }
        restore_by_kind = {
            "series": {"chinese_name"},
            "events": {"chinese_name", "race_series_id", "series_key"},
            "historicalTargets": {"race_series_id"},
        }
        for kind, rows in (
            ("series", plan["series"]),
            ("events", plan["events"]),
            ("historicalTargets", plan["historicalTargets"]),
        ):
            for row in rows:
                before = row.pop("before")
                fields = before["fields"]
                row["beforeRowSha256"] = before["rowSha256"]
                row["stableFieldsSha256"] = self.apply.sha256_json(
                    {
                        key: value
                        for key, value in fields.items()
                        if key not in mutable_by_kind[kind]
                    }
                )
                row["restore"] = {
                    key: fields[key] for key in restore_by_kind[kind]
                }

        context = self.rollback_audit_context("9" * 32)
        self.apply.execute_plan(plan, commit=True, audit_context=context)
        self.verify.verify_database(
            plan,
            batch_id="9" * 32,
            mode="applied",
        )
        self.apply.execute_rollback(plan, audit_context=context)
        rolled_back = self.verify.verify_database(
            plan,
            batch_id="9" * 32,
            mode="rolled-back",
            expected_rollback_artifact_sha256="2" * 64,
        )

        self.assertEqual(rolled_back["eventCount"], 1)
        self.series.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.series.chinese_name, "")
        self.assertEqual(self.event.chinese_name, "Test Stakes")

    def test_rollback_rejects_different_bundle_identity_before_writes(self):
        plan = self.build_plan()
        context = self.rollback_audit_context("b" * 32)
        self.apply.execute_plan(plan, commit=True, audit_context=context)
        wrong_context = {
            **context,
            "bundleIndexSha256": "4" * 64,
        }
        with self.assertRaisesRegex(
            self.apply.ApplyError,
            "rollback bundle identity mismatch: bundleIndexSha256",
        ):
            self.apply.execute_rollback(plan, audit_context=wrong_context)
        self.series.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.series.chinese_name, "测试锦标")
        self.assertEqual(self.event.chinese_name, "测试锦标")
        self.assertFalse(
            OperationLog.objects.filter(
                action_type="race_name_translations_rolled_back",
                target_id="b" * 32,
            ).exists()
        )

    def test_rollback_verifier_accepts_exact_before_name_with_handicap_marker(self):
        self.event.chinese_name = "京成杯秋季让赛"
        self.event.save(update_fields={"chinese_name"})
        plan = self.build_plan()
        context = self.rollback_audit_context("d" * 32)

        self.apply.execute_plan(plan, commit=True, audit_context=context)
        self.verify.verify_database(
            plan,
            batch_id="d" * 32,
            mode="applied",
        )
        self.apply.execute_rollback(plan, audit_context=context)
        rolled_back = self.verify.verify_database(
            plan,
            batch_id="d" * 32,
            mode="rolled-back",
            expected_rollback_artifact_sha256="2" * 64,
        )

        self.assertEqual(rolled_back["eventCount"], 1)
        self.event.refresh_from_db()
        self.assertEqual(self.event.chinese_name, "京成杯秋季让赛")

    def test_rollback_after_state_drift_is_rejected(self):
        plan = self.build_plan()
        context = self.rollback_audit_context("a" * 32)
        self.apply.execute_plan(plan, commit=True, audit_context=context)
        RaceEvent.objects.filter(pk=self.event.pk).update(racecourse="Kyoto")
        with self.assertRaisesRegex(self.apply.ApplyError, "after-state full-row CAS"):
            self.apply.execute_rollback(plan, audit_context=context)
        self.series.refresh_from_db()
        self.assertEqual(self.series.chinese_name, "测试锦标")
        self.assertEqual(
            OperationLog.objects.filter(
                action_type="race_name_translations_rolled_back"
            ).count(),
            0,
        )

    def test_identity_correction_updates_verifies_and_rolls_back_linked_target(self):
        destination = RaceSeries.objects.create(
            key="hong-kong-destination",
            country_region=RacingRegion.HONG_KONG,
            canonical_name_original="Destination Stakes",
            chinese_name="",
        )
        self.series.country_region = RacingRegion.HONG_KONG
        self.series.save(update_fields={"country_region"})
        self.event.country_region = RacingRegion.HONG_KONG
        self.event.save(update_fields={"country_region"})
        target = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=self.event.year,
            country_region=RacingRegion.HONG_KONG,
            original_name=self.event.original_name,
            event=self.event,
        )
        plan = self.build_plan()
        plan["events"][0]["actionType"] = "reassign_series_and_translate"
        plan["events"][0]["after"].update(
            {
                "raceSeriesId": destination.id,
                "seriesKey": destination.key,
            }
        )
        plan["eventScope"]["series"].append(
            {
                "seriesId": destination.id,
                "beforeRowSha256": self.apply.canonical_model_row(destination)[
                    "rowSha256"
                ],
            }
        )
        plan["historicalTargets"] = [
            {
                "historicalTargetId": target.id,
                "eventId": self.event.id,
                "before": self.apply.canonical_model_row(target),
                "after": {"raceSeriesId": destination.id},
            }
        ]
        context = self.rollback_audit_context("e" * 32)
        result = self.apply.execute_plan(plan, commit=True, audit_context=context)
        self.assertEqual(result["historicalTargetCount"], 1)
        self.event.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(self.event.race_series_id, destination.id)
        self.assertEqual(target.race_series_id, destination.id)
        verified = self.verify.verify_database(
            plan,
            batch_id="e" * 32,
            mode="applied",
        )
        self.assertEqual(verified["historicalTargetCount"], 1)
        self.apply.execute_rollback(plan, audit_context=context)
        self.verify.verify_database(
            plan,
            batch_id="e" * 32,
            mode="rolled-back",
        )
        self.event.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(self.event.race_series_id, self.series.id)
        self.assertEqual(target.race_series_id, self.series.id)

    def test_identity_correction_rejects_missing_linked_target_plan(self):
        plan = self.build_plan()
        plan["events"][0]["actionType"] = "reassign_series_and_translate"
        plan["events"][0]["after"].update(
            {
                "raceSeriesId": self.series.id,
                "seriesKey": self.series.key,
            }
        )
        with self.assertRaisesRegex(
            self.apply.ApplyError,
            "historical target/correction event set mismatch",
        ):
            self.apply.execute_plan(
                plan,
                commit=False,
                audit_context={"batchId": "f" * 32},
            )

    def test_bundle_member_tamper_is_rejected_before_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            members = [
                "apply_race_name_translation_manifest.py",
                "verify_race_name_translation_manifest.py",
                "input-lock.json",
                "normalized-input.json",
                "manifest.json",
                "production-before.json",
                "dry-run.json",
                "rollback-before.json",
                "execution-metadata.json",
                "execution-plan.json",
                "artifact-index.json",
            ]
            files = []
            for member in members:
                payload = f"{member}\n".encode()
                (directory / member).write_bytes(payload)
                files.append(
                    {
                        "file": member,
                        "sizeBytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
            content = {
                "schemaVersion": "race-name-translation-bundle-index.v1",
                "files": files,
            }
            content["contentSha256"] = self.apply.sha256_json(content)
            index_path = directory / "bundle-index.json"
            index_path.write_text(json.dumps(content, ensure_ascii=False) + "\n")
            expected = hashlib.sha256(index_path.read_bytes()).hexdigest()
            self.apply.verify_bundle(directory, expected)
            (directory / "manifest.json").write_text("tampered\n")
            with self.assertRaisesRegex(self.apply.ApplyError, "bundle member"):
                self.apply.verify_bundle(directory, expected)

    def test_execution_inputs_do_not_expand_large_snapshot_or_dry_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest_sha = "a" * 64
            production_sha = "b" * 64
            dry_run_sha = "c" * 64
            rollback_sha = "d" * 64
            execution_plan = {
                "schemaVersion": "race-name-translation-execution-plan.v1",
                "sourceRollbackContentSha256": rollback_sha,
                "series": [],
                "events": [],
                "historicalTargets": [],
            }
            execution_plan_sha = self.apply.sha256_json(execution_plan)
            execution_plan["contentSha256"] = execution_plan_sha
            (directory / "production-before.json").write_text(
                "intentionally not parsed",
                encoding="utf-8",
            )
            (directory / "dry-run.json").write_text(
                "intentionally not parsed",
                encoding="utf-8",
            )
            (directory / "execution-metadata.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": "race-name-translation-execution-metadata.v1",
                        "manifestContentSha256": manifest_sha,
                        "productionBeforeSecondSha256": production_sha,
                        "dryRunContentSha256": dry_run_sha,
                        "dryRunApplyReady": True,
                        "dryRunBlockerCount": 0,
                        "rollbackContentSha256": rollback_sha,
                        "executionPlanContentSha256": execution_plan_sha,
                        "manifestFileSha256": "e" * 64,
                        "productionBeforeFileSha256": "f" * 64,
                        "dryRunFileSha256": "1" * 64,
                        "rollbackFileSha256": "2" * 64,
                    }
                ),
                encoding="utf-8",
            )
            (directory / "rollback-before.json").write_text(
                "intentionally not parsed",
                encoding="utf-8",
            )
            (directory / "execution-plan.json").write_text(
                json.dumps(execution_plan),
                encoding="utf-8",
            )

            metadata, plan = self.apply._load_execution_inputs(directory)

            self.assertEqual(metadata["dryRunContentSha256"], dry_run_sha)
            self.assertEqual(plan["contentSha256"], execution_plan_sha)


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL 16")
class RaceNameTranslationApplyPostgresTests(TransactionTestCase):
    reset_sequences = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.apply = load_apply_module()

    def make_series(self, key, chinese_name=""):
        return RaceSeries.objects.create(
            key=key,
            country_region=RacingRegion.JAPAN,
            canonical_name_original=key,
            chinese_name=chinese_name,
        )

    def make_event(self, series, *, year, slug, name):
        return RaceEvent.objects.create(
            year=year,
            slug=slug,
            series_key=series.key,
            original_name=name,
            chinese_name=name,
            country_region=RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G3",
            surface="turf",
            race_series=series,
        )

    def plan_for(self, series, event, *, event_after=None):
        correction = bool(event_after and "raceSeriesId" in event_after)
        scope_series_ids = sorted(
            {
                series.id,
                *(
                    [int(event_after["raceSeriesId"])]
                    if correction
                    else []
                ),
            }
        )
        scope_events = list(
            RaceEvent.objects.filter(
                race_series_id__in=scope_series_ids
            ).order_by("id")
        )
        scope_series = list(
            RaceSeries.objects.filter(id__in=scope_series_ids).order_by("id")
        )
        historical_target = (
            HistoricalRaceEventTarget.objects.filter(event=event).first()
            if correction
            else None
        )
        return {
            "schemaVersion": "race-name-translation-rollback-before.v3",
            "sourceManifestSha256": "b" * 64,
            "eventScope": {
                "series": [
                    {
                        "seriesId": scope_series_row.id,
                        "beforeRowSha256": self.apply.canonical_model_row(
                            scope_series_row
                        )["rowSha256"],
                    }
                    for scope_series_row in scope_series
                ],
                "events": [
                    {
                        "eventId": scope_event.id,
                        "raceSeriesId": scope_event.race_series_id,
                        "beforeRowSha256": self.apply.canonical_model_row(scope_event)[
                            "rowSha256"
                        ],
                    }
                    for scope_event in scope_events
                ],
            },
            "series": [
                {
                    "seriesId": series.id,
                    "before": self.apply.canonical_model_row(series),
                    "after": {"chineseName": "测试锦标"},
                }
            ],
            "events": [
                {
                    "eventId": event.id,
                    "actionType": (
                        "reassign_series_and_translate"
                        if correction
                        else "translate"
                    ),
                    "before": self.apply.canonical_model_row(event),
                    "after": event_after or {"chineseName": "测试锦标"},
                }
            ],
            "historicalTargets": (
                [
                    {
                        "historicalTargetId": historical_target.id,
                        "eventId": event.id,
                        "before": self.apply.canonical_model_row(
                            historical_target
                        ),
                        "after": {
                            "raceSeriesId": int(event_after["raceSeriesId"])
                        },
                    }
                ]
                if historical_target is not None
                else []
            ),
        }

    def test_postgres_lock_timeout_is_bounded_and_atomic(self):
        series = self.make_series("japan-pg-lock")
        event = self.make_event(
            series, year=2025, slug="pg-lock-2025", name="PG Lock Stakes"
        )
        plan = self.plan_for(series, event)
        locked = threading.Event()
        release = threading.Event()
        errors = []

        def hold_lock():
            try:
                with transaction.atomic(using="default"):
                    RaceEvent.objects.select_for_update().get(pk=event.pk)
                    locked.set()
                    release.wait(timeout=15)
            except Exception as exc:  # pragma: no cover - diagnostic path
                errors.append(exc)
            finally:
                connections["default"].close()

        thread = threading.Thread(target=hold_lock)
        thread.start()
        self.assertTrue(locked.wait(timeout=5))
        started = time.monotonic()
        try:
            with self.assertRaises(DatabaseError):
                self.apply.execute_plan(
                    plan,
                    commit=True,
                    audit_context={"batchId": "b" * 32},
                )
        finally:
            release.set()
            thread.join(timeout=10)
        elapsed = time.monotonic() - started
        self.assertFalse(errors)
        self.assertLess(elapsed, 10)
        series.refresh_from_db()
        self.assertEqual(series.chinese_name, "")
        self.assertEqual(OperationLog.objects.count(), 0)

    def test_postgres_conditional_unique_conflict_rolls_back(self):
        source = self.make_series("japan-pg-source")
        target = self.make_series("japan-pg-target")
        event = self.make_event(
            source, year=2025, slug="pg-source-2025", name="PG Source Stakes"
        )
        HistoricalRaceEventTarget.objects.create(
            race_series=source,
            year=event.year,
            country_region=RacingRegion.JAPAN,
            original_name=event.original_name,
            event=event,
        )
        self.make_event(
            target, year=2025, slug="pg-target-2025", name="PG Target Stakes"
        )
        plan = self.plan_for(
            source,
            event,
            event_after={
                "chineseName": "测试锦标",
                "raceSeriesId": target.id,
                "seriesKey": target.key,
            },
        )
        with self.assertRaises(IntegrityError):
            self.apply.execute_plan(
                plan,
                commit=True,
                audit_context={"batchId": "c" * 32},
            )
        source.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(source.chinese_name, "")
        self.assertEqual(event.race_series_id, source.id)
        self.assertEqual(OperationLog.objects.count(), 0)

    def test_postgres_historical_target_series_year_conflict_is_rejected(self):
        source = self.make_series("japan-pg-target-source")
        destination = self.make_series("japan-pg-target-destination")
        event = self.make_event(
            source,
            year=2025,
            slug="pg-target-source-2025",
            name="PG Target Source Stakes",
        )
        linked_target = HistoricalRaceEventTarget.objects.create(
            race_series=source,
            year=event.year,
            country_region=RacingRegion.JAPAN,
            original_name=event.original_name,
            event=event,
        )
        HistoricalRaceEventTarget.objects.create(
            race_series=destination,
            year=event.year,
            country_region=RacingRegion.JAPAN,
            original_name="Destination target",
        )
        plan = self.plan_for(
            source,
            event,
            event_after={
                "chineseName": "测试锦标",
                "raceSeriesId": destination.id,
                "seriesKey": destination.key,
            },
        )
        with self.assertRaisesRegex(
            self.apply.ApplyError,
            "destination series/year conflict",
        ):
            self.apply.execute_plan(
                plan,
                commit=True,
                audit_context={"batchId": "g" * 32},
            )
        event.refresh_from_db()
        linked_target.refresh_from_db()
        self.assertEqual(event.race_series_id, source.id)
        self.assertEqual(linked_target.race_series_id, source.id)
        self.assertEqual(OperationLog.objects.count(), 0)

    def test_postgres_production_scale_query_time_and_memory_bounds(self):
        series_rows = [
            RaceSeries(
                key=f"japan-perf-{index}",
                country_region=RacingRegion.JAPAN,
                canonical_name_original=f"Performance {index}",
                chinese_name="",
            )
            for index in range(1300)
        ]
        RaceSeries.objects.bulk_create(series_rows, batch_size=500)
        series_rows = list(
            RaceSeries.objects.filter(key__startswith="japan-perf-").order_by("id")
        )
        events = []
        for index in range(8883):
            series = series_rows[index % len(series_rows)]
            year = 2000 + index // len(series_rows)
            events.append(
                RaceEvent(
                    year=year,
                    slug=f"perf-{index}",
                    series_key=series.key,
                    original_name=f"Performance Stakes {index}",
                    chinese_name=f"Performance Stakes {index}",
                    country_region=RacingRegion.JAPAN,
                    racecourse="Tokyo",
                    grade_text="G3",
                    surface="turf",
                    race_series=series,
                )
            )
        RaceEvent.objects.bulk_create(events, batch_size=500)
        events = list(
            RaceEvent.objects.filter(slug__startswith="perf-").order_by("id")
        )
        plan = {
            "schemaVersion": "race-name-translation-rollback-before.v3",
            "sourceManifestSha256": "d" * 64,
            "eventScope": {
                "series": [
                    {
                        "seriesId": row.id,
                        "beforeRowSha256": self.apply.canonical_model_row(row)[
                            "rowSha256"
                        ],
                    }
                    for row in series_rows
                ],
                "events": [
                    {
                        "eventId": row.id,
                        "raceSeriesId": row.race_series_id,
                        "beforeRowSha256": self.apply.canonical_model_row(row)[
                            "rowSha256"
                        ],
                    }
                    for row in events
                ],
            },
            "series": [
                {
                    "seriesId": row.id,
                    "before": self.apply.canonical_model_row(row),
                    "after": {"chineseName": f"性能锦标{index}"},
                }
                for index, row in enumerate(series_rows)
            ],
            "events": [
                {
                    "eventId": row.id,
                    "actionType": "translate",
                    "before": self.apply.canonical_model_row(row),
                    "after": {"chineseName": f"性能锦标{index}"},
                }
                for index, row in enumerate(events)
            ],
            "historicalTargets": [],
        }
        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        started = time.monotonic()
        with CaptureQueriesContext(connection) as queries:
            result = self.apply.execute_plan(
                plan,
                commit=True,
                audit_context={"batchId": "d" * 32},
            )
        elapsed = time.monotonic() - started
        rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_units = 1 if sys.platform == "darwin" else 1024
        rss_delta_bytes = max(0, rss_after - rss_before) * rss_units
        self.assertEqual(result["seriesCount"], 1300)
        self.assertEqual(result["eventCount"], 8883)
        self.assertLessEqual(len(queries), 40)
        self.assertLessEqual(elapsed, 60)
        self.assertLessEqual(rss_delta_bytes, 256 * 1024 * 1024)
        print(
            json.dumps(
                {
                    "postgresPerformance": {
                        "queryCount": len(queries),
                        "elapsedSeconds": round(elapsed, 3),
                        "rssDeltaBytes": rss_delta_bytes,
                    }
                },
                sort_keys=True,
            )
        )

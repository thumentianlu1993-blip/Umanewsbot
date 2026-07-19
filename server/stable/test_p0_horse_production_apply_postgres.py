from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management.color import no_style
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature

from stable import test_p0_horse_production_apply as apply_test_helpers
from stable.models import (
    HorseP0Source,
    HorseProfile,
    HorseProfileCompletionRun,
    HorseProfileDataCandidate,
    HorseRaceRecord,
    TaskExecutionLog,
    TermAlias,
    TermEntry,
)
from stable.services import p0_horse_production_apply as production_apply
from stable.services.p0_horse_production_apply import (
    _begin_commit_isolation,
    _lock_identity_keys,
    commit_reviewed_p0_completion_artifact,
    sha256_file,
)


class P0HorseProductionApplyPostgresTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL; SQLite is not concurrency evidence")
        self.reviewer = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="unused",
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.helper = apply_test_helpers.P0HorseProductionApplyTests(
            methodName="test_dry_run_performs_validation_and_writes_nothing"
        )
        self.helper.reviewer = self.reviewer
        self.helper.root = self.root
        with connection.cursor() as cursor:
            for sql in connection.ops.sequence_reset_sql(
                no_style(),
                [TermEntry, HorseProfile, HorseRaceRecord],
            ):
                cursor.execute(sql)
        self.baseline_term_alias_count = TermAlias.objects.count()

    def tearDown(self):
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()
        super().tearDown()

    @skipUnlessDBFeature("supports_transactions")
    def test_serializable_transaction_and_advisory_identity_lock_use_postgres(self):
        row = {
            "deterministic_identity_key": "1" * 64,
            "identity": {
                "horse_name": "Concurrent Horse",
                "sire_name": "Concurrent Sire",
                "dam_name": "Concurrent Dam",
                "birth_year": 2020,
            },
        }
        with transaction.atomic():
            _begin_commit_isolation()
            _lock_identity_keys([row])
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                self.assertEqual(cursor.fetchone()[0], "serializable")
                cursor.execute(
                    """
                    SELECT count(*)
                    FROM pg_locks
                    WHERE pid = pg_backend_pid()
                      AND locktype = 'advisory'
                      AND granted
                    """
                )
                self.assertGreaterEqual(cursor.fetchone()[0], 1)

    def test_commit_table_lock_sql_precedes_mapping_rescan_and_writes(self):
        horse = self.helper._horse(0)
        artifact_path, artifact = self.helper._prepare(
            [horse],
            [{"decision": "create_new"}],
        )
        release_path, release_sha = self.helper._release(artifact_path, artifact)
        statements = []

        def capture_sql(execute, sql, params, many, context):
            statements.append(" ".join(sql.split()))
            return execute(sql, params, many, context)

        with mock.patch(
            "stable.services.p0_horse_production_apply."
            "TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256",
            (release_sha,),
        ), connection.execute_wrapper(capture_sql):
            commit_reviewed_p0_completion_artifact(
                artifact_path=artifact_path,
                artifact_sha256=sha256_file(artifact_path),
                release_manifest_path=release_path,
                release_manifest_sha256=release_sha,
                confirm_reviewed_artifact=True,
            )

        isolation_index = next(
            index
            for index, sql in enumerate(statements)
            if sql.startswith("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        )
        table_lock_index = next(
            index for index, sql in enumerate(statements) if sql.startswith("LOCK TABLE")
        )
        self.assertIn('"stable_termentry"', statements[table_lock_index])
        self.assertIn('"stable_termalias"', statements[table_lock_index])
        self.assertIn('"stable_horseprofile"', statements[table_lock_index])
        self.assertIn(
            "IN SHARE ROW EXCLUSIVE MODE",
            statements[table_lock_index],
        )
        rescan_index = next(
            index
            for index, sql in enumerate(statements[table_lock_index + 1 :], table_lock_index + 1)
            if sql.startswith("SELECT") and "stable_horseprofile" in sql
        )
        first_insert_index = next(
            index
            for index, sql in enumerate(statements)
            if sql.startswith("INSERT INTO")
        )
        self.assertLess(isolation_index, table_lock_index)
        self.assertLess(table_lock_index, rescan_index)
        self.assertLess(rescan_index, first_insert_index)

    def test_non_cooperating_term_insert_waits_for_commit_table_lock_release(self):
        lock_ready = threading.Event()
        release_lock = threading.Event()
        writer_started = threading.Event()
        writer_finished = threading.Event()
        errors = []

        def locker():
            close_old_connections()
            try:
                with transaction.atomic():
                    _begin_commit_isolation()
                    production_apply._lock_commit_identity_tables()
                    lock_ready.set()
                    release_lock.wait(timeout=10)
            except Exception as exc:  # pragma: no cover - asserted after join
                errors.append(exc)
            finally:
                close_old_connections()

        def writer():
            close_old_connections()
            try:
                lock_ready.wait(timeout=10)
                writer_started.set()
                TermEntry.objects.create(
                    term_type="horse",
                    source_language="en",
                    source_ja="Non-cooperating writer",
                    target_zh="",
                    translation_status="pending",
                    is_active=True,
                )
                writer_finished.set()
            except Exception as exc:  # pragma: no cover - asserted after join
                errors.append(exc)
            finally:
                close_old_connections()

        locker_thread = threading.Thread(target=locker)
        writer_thread = threading.Thread(target=writer)
        locker_thread.start()
        writer_thread.start()
        self.assertTrue(lock_ready.wait(timeout=10))
        self.assertTrue(writer_started.wait(timeout=10))
        time.sleep(0.25)
        self.assertFalse(writer_finished.is_set())
        release_lock.set()
        locker_thread.join(timeout=10)
        writer_thread.join(timeout=10)
        self.assertFalse(errors)
        self.assertTrue(writer_finished.is_set())
        self.assertTrue(
            TermEntry.objects.filter(source_ja="Non-cooperating writer").exists()
        )

    def test_concurrent_same_artifact_commit_creates_one_identity(self):
        horse = self.helper._horse(0)
        artifact_path, artifact = self.helper._prepare(
            [horse],
            [{"decision": "create_new"}],
        )
        release_path, release_sha = self.helper._release(artifact_path, artifact)
        artifact_sha = sha256_file(artifact_path)
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                results.append(
                    commit_reviewed_p0_completion_artifact(
                        artifact_path=artifact_path,
                        artifact_sha256=artifact_sha,
                        release_manifest_path=release_path,
                        release_manifest_sha256=release_sha,
                        confirm_reviewed_artifact=True,
                    )
                )
            except Exception as exc:  # pragma: no cover - asserted after join
                errors.append(exc)
            finally:
                close_old_connections()

        with mock.patch(
            "stable.services.p0_horse_production_apply."
            "TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256",
            (release_sha,),
        ):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        self.assertEqual(HorseProfile.objects.count(), 1)
        self.assertEqual(TermEntry.objects.filter(term_type="horse").count(), 1)
        self.assertEqual(HorseRaceRecord.objects.count(), 2)
        self.assertEqual(TaskExecutionLog.objects.count(), 2)

    def test_commit_exception_rolls_back_entire_artifact(self):
        horses = [self.helper._horse(0), self.helper._horse(1)]
        artifact_path, artifact = self.helper._prepare(
            horses,
            [{"decision": "create_new"}, {"decision": "create_new"}],
        )
        release_path, release_sha = self.helper._release(artifact_path, artifact)
        real_apply = production_apply._apply_artifact_row
        apply_calls = 0
        first_row_state_before_failure = {}

        def apply_first_row_then_fail_second(**kwargs):
            nonlocal apply_calls
            apply_calls += 1
            if apply_calls == 1:
                return real_apply(**kwargs)
            first_row_state_before_failure.update(self._apply_business_counts())
            raise RuntimeError("postgres rollback probe")

        with mock.patch(
            "stable.services.p0_horse_production_apply."
            "TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256",
            (release_sha,),
        ), mock.patch(
            "stable.services.p0_horse_production_apply._apply_artifact_row",
            side_effect=apply_first_row_then_fail_second,
        ), self.assertRaisesRegex(RuntimeError, "postgres rollback probe"):
            commit_reviewed_p0_completion_artifact(
                artifact_path=artifact_path,
                artifact_sha256=sha256_file(artifact_path),
                release_manifest_path=release_path,
                release_manifest_sha256=release_sha,
                confirm_reviewed_artifact=True,
            )
        self.assertEqual(apply_calls, 2)
        self.assertEqual(
            first_row_state_before_failure,
            {
                # The second row resolves create_new before entering the patched
                # apply call, so its profile/term are also partial writes.
                "profiles": 2,
                "horse_terms": 2,
                "race_records": 2,
                "p0_sources": 1,
                "module_candidates": 4,
                "completion_runs": 1,
                "task_logs": 0,
            },
        )
        self._assert_all_apply_business_tables_empty()

    def test_exception_after_task_log_creation_rolls_back_log_and_business_rows(self):
        horse = self.helper._horse(0)
        artifact_path, artifact = self.helper._prepare(
            [horse],
            [{"decision": "create_new"}],
        )
        release_path, release_sha = self.helper._release(artifact_path, artifact)
        state_after_log_create = {}

        def fail_after_log_create():
            state_after_log_create.update(self._apply_business_counts())
            raise RuntimeError("post-log rollback probe")

        with mock.patch(
            "stable.services.p0_horse_production_apply."
            "TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256",
            (release_sha,),
        ), mock.patch(
            "stable.services.p0_horse_production_apply."
            "_after_task_execution_log_created_for_test",
            side_effect=fail_after_log_create,
        ), self.assertRaisesRegex(RuntimeError, "post-log rollback probe"):
            commit_reviewed_p0_completion_artifact(
                artifact_path=artifact_path,
                artifact_sha256=sha256_file(artifact_path),
                release_manifest_path=release_path,
                release_manifest_sha256=release_sha,
                confirm_reviewed_artifact=True,
            )
        self.assertEqual(
            state_after_log_create,
            {
                "profiles": 1,
                "horse_terms": 1,
                "race_records": 2,
                "p0_sources": 1,
                "module_candidates": 4,
                "completion_runs": 1,
                "task_logs": 1,
            },
        )
        self._assert_all_apply_business_tables_empty()

    def _apply_business_counts(self):
        return {
            "profiles": HorseProfile.objects.count(),
            "horse_terms": TermEntry.objects.filter(term_type="horse").count(),
            "race_records": HorseRaceRecord.objects.count(),
            "p0_sources": HorseP0Source.objects.count(),
            "module_candidates": HorseProfileDataCandidate.objects.count(),
            "completion_runs": HorseProfileCompletionRun.objects.count(),
            "task_logs": TaskExecutionLog.objects.count(),
        }

    def _assert_all_apply_business_tables_empty(self):
        self.assertEqual(HorseProfile.objects.count(), 0)
        self.assertEqual(TermEntry.objects.filter(term_type="horse").count(), 0)
        self.assertEqual(
            TermAlias.objects.count(),
            self.baseline_term_alias_count,
        )
        self.assertEqual(HorseRaceRecord.objects.count(), 0)
        self.assertEqual(HorseP0Source.objects.count(), 0)
        self.assertEqual(HorseProfileDataCandidate.objects.count(), 0)
        self.assertEqual(HorseProfileCompletionRun.objects.count(), 0)
        self.assertEqual(TaskExecutionLog.objects.count(), 0)

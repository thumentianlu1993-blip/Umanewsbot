from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management.color import no_style
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature

from stable import test_p0_horse_production_apply as apply_test_helpers
from stable.models import HorseProfile, HorseRaceRecord, TaskExecutionLog, TermEntry
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
        with mock.patch(
            "stable.services.p0_horse_production_apply."
            "TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256",
            (release_sha,),
        ), mock.patch(
            "stable.services.p0_horse_production_apply._apply_artifact_row",
            side_effect=[None, RuntimeError("postgres rollback probe")],
        ), self.assertRaisesRegex(RuntimeError, "postgres rollback probe"):
            commit_reviewed_p0_completion_artifact(
                artifact_path=artifact_path,
                artifact_sha256=sha256_file(artifact_path),
                release_manifest_path=release_path,
                release_manifest_sha256=release_sha,
                confirm_reviewed_artifact=True,
            )
        self.assertEqual(HorseProfile.objects.count(), 0)
        self.assertEqual(TermEntry.objects.filter(term_type="horse").count(), 0)
        self.assertEqual(HorseRaceRecord.objects.count(), 0)
        self.assertEqual(TaskExecutionLog.objects.count(), 0)

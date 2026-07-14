from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from unittest import skipUnless

from django.db import DatabaseError, IntegrityError, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase

from stable.models import (
    HistoricalBatchPhase,
    HistoricalBatchRun,
    HistoricalBatchRunEvent,
    RaceEvent,
    RaceEventSurface,
    RaceEventVisibility,
    RacingRegion,
)
from stable.services.historical_batch_runner import (
    RunnerLeaseError,
    acquire_runner_lease,
    create_runner_run,
    heartbeat_runner_lease,
    release_runner_lease,
)


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
class HistoricalBatchRunnerPostgresTests(TransactionTestCase):
    reset_sequences = True

    def _run(self, root: Path, suffix: str) -> HistoricalBatchRun:
        run_root = root / suffix
        run_root.mkdir()
        plan = run_root / "plan.json"
        plan.write_text("{}\n", encoding="utf-8")
        return create_runner_run(
            run_id=f"postgres-{suffix}",
            batch_id="2016-2025-batch-006-postgres",
            phase=HistoricalBatchPhase.CRAWL,
            artifact_root=str(run_root),
            plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
            image_id="sha256:" + "1" * 64,
            image_revision="a" * 40,
        )

    def test_database_phase_constraint_rejects_network_and_write_together(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HistoricalBatchRun.objects.create(
                    run_id="postgres-invalid-permissions",
                    batch_id="2016-2025-batch-006-postgres",
                    phase=HistoricalBatchPhase.CRAWL,
                    network_enabled=True,
                    write_enabled=True,
                    artifact_root="/tmp/invalid",
                    plan_sha256="a" * 64,
                    image_id="sha256:" + "1" * 64,
                    image_revision="a" * 40,
                )

    def test_database_trigger_makes_audit_events_append_only(self):
        with TemporaryDirectory() as tmp:
            run = self._run(Path(tmp), "append-only")
            event = HistoricalBatchRunEvent.objects.create(run=run, event_type="proof", detail={})
            with self.assertRaises(DatabaseError):
                HistoricalBatchRunEvent.objects.filter(pk=event.pk).update(event_type="tampered")
            with self.assertRaises(DatabaseError):
                HistoricalBatchRunEvent.objects.filter(pk=event.pk).delete()
            self.assertEqual(HistoricalBatchRunEvent.objects.get(pk=event.pk).event_type, "proof")

    def test_database_trigger_prevents_runner_visibility_changes(self):
        event = RaceEvent.objects.create(
            year=2025,
            slug="postgres-visibility-guard",
            original_name="PostgreSQL Visibility Guard",
            chinese_name="PostgreSQL公开状态门禁",
            country_region=RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET application_name = 'umanews-historical-runner:postgres-test:apply'")
            with self.assertRaises(DatabaseError):
                RaceEvent.objects.filter(pk=event.pk).update(
                    visibility_status=RaceEventVisibility.PUBLISHED
                )
            event.refresh_from_db()
            self.assertEqual(event.visibility_status, RaceEventVisibility.DRAFT)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET application_name = ''")

    def test_database_trigger_prevents_runner_race_event_deletes(self):
        event = RaceEvent.objects.create(
            year=2025,
            slug="postgres-delete-guard",
            original_name="PostgreSQL Delete Guard",
            chinese_name="PostgreSQL删除门禁",
            country_region=RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET application_name = 'umanews-historical-runner:postgres-test:apply'")
            with self.assertRaises(DatabaseError):
                RaceEvent.objects.filter(pk=event.pk).delete()
            self.assertTrue(RaceEvent.objects.filter(pk=event.pk).exists())
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET application_name = ''")

    def test_twenty_connections_cannot_create_two_global_lease_owners(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = [self._run(root, f"contender-{index}") for index in range(20)]
            all_attempted = Event()
            counter_lock = Lock()
            attempt_count = 0

            def contend(run_pk: int, index: int) -> bool:
                nonlocal attempt_count
                close_old_connections()
                lease = None
                acquired = False
                try:
                    competing_run = HistoricalBatchRun.objects.get(pk=run_pk)
                    lease = acquire_runner_lease(
                        run=competing_run,
                        owner_token=f"owner-{index}",
                        lock_path=root / "global.lock",
                    )
                    acquired = True
                except RunnerLeaseError:
                    pass
                finally:
                    with counter_lock:
                        attempt_count += 1
                        if attempt_count == len(runs):
                            all_attempted.set()
                    if acquired:
                        try:
                            self.assertTrue(all_attempted.wait(timeout=10))
                        finally:
                            release_runner_lease(
                                run=competing_run,
                                owner_token=f"owner-{index}",
                            )
                            lease.close()
                    connections.close_all()
                return acquired

            with ThreadPoolExecutor(max_workers=len(runs)) as pool:
                futures = [pool.submit(contend, run.pk, index) for index, run in enumerate(runs)]
                results = [future.result(timeout=20) for future in futures]
            self.assertEqual(sum(results), 1)

    def test_heartbeat_refreshes_the_180_second_lease(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = self._run(root, "heartbeat")
            lease = acquire_runner_lease(
                run=run,
                owner_token="heartbeat-owner",
                lock_path=root / "heartbeat.lock",
            )
            try:
                heartbeat_runner_lease(run=run, owner_token="heartbeat-owner")
                run.refresh_from_db()
                self.assertIsNotNone(run.heartbeat_at)
                self.assertIsNotNone(run.lease_expires_at)
                lease_age = (run.lease_expires_at - run.heartbeat_at).total_seconds()
                self.assertGreaterEqual(lease_age, 179)
                self.assertLessEqual(lease_age, 180)
            finally:
                release_runner_lease(run=run, owner_token="heartbeat-owner")
                lease.close()

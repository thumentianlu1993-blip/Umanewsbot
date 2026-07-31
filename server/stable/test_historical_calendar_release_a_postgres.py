"""Release A 的真实 PostgreSQL migration、约束与并发验收。

仅在隔离 PostgreSQL 数据库中运行。并发用 PostgreSQL advisory lock 的实际
``pg_locks`` 等待状态作为同步证据，不以固定 sleep 猜测锁已建立。
"""

from __future__ import annotations

import threading
import time
from datetime import date
from queue import Queue
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from stable.models import (
    HistoricalRaceCalendarMaintenanceGate,
    HistoricalRaceCalendarRepairReceipt,
    RaceEvent,
    RaceEventPublicPath,
    RaceEventPublicPathKind,
)
from stable.services.historical_race_calendar_admission import (
    HistoricalCalendarWriteBlocked,
    assert_historical_calendar_write_admitted,
    enter_historical_calendar_maintenance,
    exit_historical_calendar_maintenance,
)


MIGRATE_FROM = [("stable", "0066_add_term_consistency_manifest")]
MIGRATE_TO = [("stable", "0067_historical_calendar_release_a")]
LOCK_TIMEOUT_SECONDS = 10


def _event_payload(slug: str, **overrides):
    values = {
        "year": 2025,
        "edition_year": 2025,
        "slug": slug,
        "original_name": f"PostgreSQL {slug}",
        "chinese_name": "PostgreSQL 验收赛事",
        "country_region": "hong_kong",
        "racecourse": "Sha Tin",
        "grade_text": "G1",
        "surface": "turf",
        "local_date": date(2025, 1, 1),
    }
    values.update(overrides)
    return values


def _thread_connection_cleanup():
    connections.close_all()


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
class HistoricalCalendarReleaseAMigrationPostgresTests(TransactionTestCase):
    """真实执行 0066→0067→0066，并在 tearDown 恢复 Release A。"""

    reset_sequences = True

    def _migrate(self, targets):
        started = time.monotonic()
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        elapsed = time.monotonic() - started
        print(
            f"ACCEPTANCE_METRIC migration={'/'.join(name for _, name in targets)} "
            f"wall_seconds={elapsed:.3f}"
        )
        self.assertLess(elapsed, 180, "migration wall time exceeds blocker threshold")
        return executor.loader.project_state(targets).apps, elapsed

    def tearDown(self):
        self._migrate(MIGRATE_TO)
        super().tearDown()

    def test_0066_to_0067_backfill_schema_and_reverse(self):
        old_apps, down_elapsed = self._migrate(MIGRATE_FROM)
        OldRaceEvent = old_apps.get_model("stable", "RaceEvent")
        event = OldRaceEvent.objects.create(
            year=2024,
            slug="release-a-migration",
            original_name="Release A Migration",
            chinese_name="Release A 迁移",
            country_region="hong_kong",
            racecourse="Sha Tin",
            grade_text="G1",
            surface="turf",
            local_date=date(2024, 1, 1),
        )

        new_apps, up_elapsed = self._migrate(MIGRATE_TO)
        NewRaceEvent = new_apps.get_model("stable", "RaceEvent")
        PublicPath = new_apps.get_model("stable", "RaceEventPublicPath")
        Gate = new_apps.get_model("stable", "HistoricalRaceCalendarMaintenanceGate")
        Receipt = new_apps.get_model("stable", "HistoricalRaceCalendarRepairReceipt")
        migrated = NewRaceEvent.objects.get(pk=event.pk)
        self.assertEqual(migrated.edition_year, 2024)
        self.assertTrue(
            PublicPath.objects.filter(
                event_id=event.pk,
                year=2024,
                slug="release-a-migration",
                path_kind="canonical",
            ).exists()
        )
        self.assertEqual(Gate._meta.get_field("manifest_sha256").max_length, 64)
        self.assertTrue(Receipt._meta.get_field("manifest_sha256").unique)
        self.assertEqual(
            PublicPath._meta.get_field("event").remote_field.on_delete.__name__,
            "CASCADE",
        )
        self.assertLess(up_elapsed, 60, "Release A forward migration exceeds PASS threshold")
        self.assertLess(down_elapsed, 60, "Release A reverse migration exceeds PASS threshold")

        old_again_apps, _ = self._migrate(MIGRATE_FROM)
        OldAgainEvent = old_again_apps.get_model("stable", "RaceEvent")
        self.assertTrue(OldAgainEvent.objects.filter(pk=event.pk).exists())
        self.assertNotIn(
            "edition_year",
            {field.name for field in OldAgainEvent._meta.get_fields()},
        )
        with connection.cursor() as cursor:
            table_names = set(connection.introspection.table_names(cursor))
        self.assertNotIn(PublicPath._meta.db_table, table_names)
        self.assertNotIn(Gate._meta.db_table, table_names)
        self.assertNotIn(Receipt._meta.db_table, table_names)


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
class HistoricalCalendarReleaseAConcurrencyPostgresTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="pg-calendar-actor")

    def _wait_for_ungranted_advisory_lock(self, backend_pid: int) -> float:
        started = time.monotonic()
        deadline = started + LOCK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_locks
                        WHERE pid = %s AND locktype = 'advisory' AND NOT granted
                    )
                    """,
                    [backend_pid],
                )
                if cursor.fetchone()[0]:
                    waited = time.monotonic() - started
                    print(
                        "ACCEPTANCE_METRIC gate_exclusive_lock_observed "
                        f"wait_seconds={waited:.3f}"
                    )
                    return waited
            time.sleep(0.02)
        self.fail("exclusive gate transition never entered PostgreSQL advisory-lock wait")

    def test_gate_waits_for_admitted_writer_and_queued_writer_rechecks(self):
        writer_holds_shared = threading.Event()
        release_first_writer = threading.Event()
        gate_attempting = threading.Event()
        gate_entered = threading.Event()
        release_gate_transaction = threading.Event()
        second_writer_started = threading.Event()
        results = Queue()
        gate_pid = Queue()

        def first_writer():
            _thread_connection_cleanup()
            try:
                with transaction.atomic():
                    assert_historical_calendar_write_admitted()
                    RaceEvent.objects.create(**_event_payload("first-admitted-writer"))
                    writer_holds_shared.set()
                    if not release_first_writer.wait(LOCK_TIMEOUT_SECONDS):
                        raise TimeoutError("first writer release timed out")
                results.put(("first_writer", "committed"))
            except Exception as exc:  # pragma: no cover - reported by assertion
                results.put(("first_writer", type(exc).__name__))
            finally:
                _thread_connection_cleanup()

        def gate_transition():
            _thread_connection_cleanup()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    gate_pid.put(cursor.fetchone()[0])
                gate_attempting.set()
                with transaction.atomic():
                    gate = enter_historical_calendar_maintenance(
                        manifest_sha256="a" * 64,
                        action_scope_sha256="b" * 64,
                        actor=get_user_model().objects.get(pk=self.actor.pk),
                    )
                    gate_entered.set()
                    if not release_gate_transaction.wait(LOCK_TIMEOUT_SECONDS):
                        raise TimeoutError("gate transaction release timed out")
                results.put(("gate", gate.pk))
            except Exception as exc:  # pragma: no cover - reported by assertion
                results.put(("gate", type(exc).__name__))
            finally:
                _thread_connection_cleanup()

        def second_writer():
            _thread_connection_cleanup()
            second_writer_started.set()
            try:
                with transaction.atomic():
                    RaceEvent.objects.create(**_event_payload("queued-new-writer"))
                results.put(("second_writer", "committed"))
            except HistoricalCalendarWriteBlocked:
                results.put(("second_writer", "blocked"))
            except Exception as exc:  # pragma: no cover - reported by assertion
                results.put(("second_writer", type(exc).__name__))
            finally:
                _thread_connection_cleanup()

        first = threading.Thread(target=first_writer, name="calendar-first-writer")
        gate_thread = threading.Thread(target=gate_transition, name="calendar-gate")
        queued = threading.Thread(target=second_writer, name="calendar-queued-writer")
        first.start()
        self.assertTrue(writer_holds_shared.wait(LOCK_TIMEOUT_SECONDS))
        gate_thread.start()
        self.assertTrue(gate_attempting.wait(LOCK_TIMEOUT_SECONDS))
        pid = gate_pid.get(timeout=LOCK_TIMEOUT_SECONDS)
        observed_wait = self._wait_for_ungranted_advisory_lock(pid)
        self.assertLess(observed_wait, 5, "lock wait observability exceeds PASS threshold")
        self.assertFalse(gate_entered.is_set())

        queued.start()
        self.assertTrue(second_writer_started.wait(LOCK_TIMEOUT_SECONDS))
        release_first_writer.set()
        self.assertTrue(gate_entered.wait(LOCK_TIMEOUT_SECONDS))
        self.assertTrue(first.is_alive() or RaceEvent.objects.filter(slug="first-admitted-writer").exists())
        release_gate_transaction.set()

        for thread in (first, gate_thread, queued):
            thread.join(LOCK_TIMEOUT_SECONDS)
            self.assertFalse(thread.is_alive(), f"{thread.name} deadlocked")

        outcomes = dict(results.get_nowait() for _ in range(3))
        self.assertEqual(outcomes["first_writer"], "committed")
        self.assertIsInstance(outcomes["gate"], int)
        self.assertEqual(outcomes["second_writer"], "blocked")
        self.assertTrue(RaceEvent.objects.filter(slug="first-admitted-writer").exists())
        self.assertFalse(RaceEvent.objects.filter(slug="queued-new-writer").exists())

        gate = HistoricalRaceCalendarMaintenanceGate.objects.get(pk=outcomes["gate"])
        exit_historical_calendar_maintenance(
            gate=gate,
            actor=self.actor,
            manifest_sha256="a" * 64,
            action_scope_sha256="b" * 64,
        )
        RaceEvent.objects.create(**_event_payload("writer-after-gate-exit"))
        self.assertTrue(RaceEvent.objects.filter(slug="writer-after-gate-exit").exists())


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
class HistoricalCalendarReleaseAConstraintPostgresTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="pg-constraint-actor")

    def test_path_collision_rolls_back_event_identity_and_registry(self):
        first = RaceEvent.objects.create(**_event_payload("reserved-path"))
        first.slug = "reserved-path-renamed"
        first.save(update_fields={"slug"})
        second = RaceEvent.objects.create(**_event_payload("second-path"))

        with self.assertRaises(IntegrityError):
            second.slug = "reserved-path"
            second.save(update_fields={"slug"})

        second.refresh_from_db()
        self.assertEqual(second.slug, "second-path")
        self.assertTrue(
            RaceEventPublicPath.objects.filter(
                event=second,
                slug="second-path",
                path_kind=RaceEventPublicPathKind.CANONICAL,
            ).exists()
        )
        self.assertFalse(
            RaceEventPublicPath.objects.filter(
                event=second, slug="reserved-path"
            ).exists()
        )

    def test_delete_cascades_paths_and_active_gate_rejects_delete(self):
        event = RaceEvent.objects.create(**_event_payload("delete-cascade"))
        RaceEventPublicPath.objects.create(
            event=event,
            year=2024,
            slug="delete-cascade-legacy",
            path_kind=RaceEventPublicPathKind.LEGACY,
        )
        event_id = event.pk
        event.delete()
        self.assertFalse(RaceEvent.objects.filter(pk=event_id).exists())
        self.assertFalse(RaceEventPublicPath.objects.filter(event_id=event_id).exists())

        protected = RaceEvent.objects.create(**_event_payload("delete-protected"))
        gate = enter_historical_calendar_maintenance(
            manifest_sha256="c" * 64,
            action_scope_sha256="d" * 64,
            actor=self.actor,
        )
        with self.assertRaises(HistoricalCalendarWriteBlocked):
            protected.delete()
        self.assertTrue(RaceEvent.objects.filter(pk=protected.pk).exists())
        self.assertTrue(RaceEventPublicPath.objects.filter(event=protected).exists())
        exit_historical_calendar_maintenance(
            gate=gate,
            actor=self.actor,
            manifest_sha256="c" * 64,
            action_scope_sha256="d" * 64,
        )

    def test_receipt_and_active_gate_exactly_once_constraints(self):
        receipt_values = {
            "manifest_sha256": "e" * 64,
            "approval_sha256": "f" * 64,
            "action_scope_sha256": "1" * 64,
            "actor": self.actor,
            "rollback_sha256": "2" * 64,
            "applied_at": timezone.now(),
        }
        HistoricalRaceCalendarRepairReceipt.objects.create(**receipt_values)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HistoricalRaceCalendarRepairReceipt.objects.create(**receipt_values)

        enter_historical_calendar_maintenance(
            manifest_sha256="3" * 64,
            action_scope_sha256="4" * 64,
            actor=self.actor,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HistoricalRaceCalendarMaintenanceGate.objects.create(
                    manifest_sha256="5" * 64,
                    action_scope_sha256="6" * 64,
                    actor=self.actor,
                    status="active",
                    entered_at=timezone.now(),
                )

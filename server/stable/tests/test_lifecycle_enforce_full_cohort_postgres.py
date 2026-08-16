"""PostgreSQL/integration RED contracts for full-cohort runtime safety."""

from __future__ import annotations

import importlib
import hashlib
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.db import connection, connections
from django.db import transaction
from django.test import TransactionTestCase, override_settings

from stable.services.race_event_lifecycle_enrollment import _schedule_hash
from stable.test_race_event_lifecycle import _make_control, _make_event
from stable.tasks import (
    advance_race_event_lifecycle_task,
    scan_due_race_event_lifecycle_task,
)


def _service(testcase):
    try:
        return importlib.import_module("stable.services.race_event_lifecycle_enforce")
    except ModuleNotFoundError as exc:
        testcase.fail(
            "目标能力缺失：full-cohort runtime service 尚未实现"
        )
        raise AssertionError from exc


def _models(testcase):
    try:
        return (
            apps.get_model("stable", "RaceEventLifecycleEnforceRegistry"),
            apps.get_model("stable", "RaceEventLifecycleEnforceMembership"),
        )
    except LookupError as exc:
        testcase.fail("目标能力缺失：registry/membership 模型尚未实现")
        raise AssertionError from exc


class FullCohortIntegrationContracts(TransactionTestCase):
    reset_sequences = True

    def _active_registry(self, *, member_count: int, due_at: datetime):
        Registry, Membership = _models(self)
        registry = Registry.objects.create(
            root_sha256="a" * 64, generation=1,
            membership_sha256="b" * 64, member_count=member_count,
            state="active", is_active=True, activation_id="c" * 64,
            approved_commit="d" * 40, selector_scope={}, scope_sha256="e" * 64,
            census_cutoff=due_at - timedelta(days=1),
            apply_expires_at=due_at + timedelta(days=1),
            runtime_valid_until=due_at + timedelta(days=35),
        )
        events = []
        for index in range(member_count):
            event = _make_event(
                slug=f"page-{index}", race_datetime=due_at,
                local_date=due_at.date(),
            )
            control = _make_control(
                event, mode="enforce", next_refresh_at=due_at,
                schedule_generation=1,
            )
            control.enrollment_manifest_sha256 = "f" * 64
            control.manifest_data = {
                "schema_version": 2,
                "enrollment_schedule_hash": _schedule_hash(event),
                "allowed_us_zones": [],
            }
            control.save()
            Membership.objects.create(
                registry=registry, event=event, entry_sha256=f"{index + 1:064x}",
                source_enrollment_sha256="f" * 64, schedule_generation=1,
                schedule_hash=_schedule_hash(event), country_region="japan",
                timezone_name="Asia/Tokyo",
            )
            events.append(event)
        return registry, events

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=True,
        RACE_EVENT_LIFECYCLE_MODE="enforce",
        RACE_EVENT_LIFECYCLE_BATCH_SIZE=100,
    )
    def test_250_members_are_claimed_in_100_100_50_disjoint_pages(self):
        _service(self)
        now = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
        registry, _ = self._active_registry(member_count=250, due_at=now)
        pages = []
        dispatched = []
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
            RACE_EVENT_LIFECYCLE_BATCH_SIZE=100,
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256="",
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS="",
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=registry.root_sha256,
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=(
                registry.membership_sha256
            ),
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=250,
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=(
                registry.activation_id
            ),
        ), patch("stable.tasks.timezone.now", return_value=now), patch(
            "stable.tasks.advance_race_event_lifecycle_task.apply_async",
            side_effect=lambda **kwargs: dispatched.append(kwargs["kwargs"]),
        ):
            for _ in range(4):
                start = len(dispatched)
                result = scan_due_race_event_lifecycle_task()
                self.assertEqual(result["claimed"], result["dispatched"])
                pages.append(
                    {item["event_id"] for item in dispatched[start:]}
                )
        self.assertEqual([len(page) for page in pages], [100, 100, 50, 0])
        self.assertEqual(len(set().union(*pages)), 250)
        for left_index, left in enumerate(pages):
            for right in pages[left_index + 1 :]:
                self.assertFalse(left & right)
        self.assertTrue(dispatched)
        self.assertTrue(
            all(
                item["expected_registry_root_sha256"] == registry.root_sha256
                and item["expected_registry_membership_sha256"] == registry.membership_sha256
                and item["expected_registry_member_count"] == registry.member_count
                and item["expected_registry_activation_id"] == registry.activation_id
                for item in dispatched
            ),
            "every queued task must be bound to the exact active registry",
        )

    def test_postgres_scanner_shared_barrier_blocks_registry_activation_exclusive_lock(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL advisory-lock proof requires PostgreSQL")
        lifecycle = importlib.import_module("stable.services.race_event_lifecycle")
        enforce = _service(self)
        shared_acquired = threading.Event()
        release_shared = threading.Event()
        exclusive_acquired = threading.Event()
        errors = []

        def scanner_connection():
            connections.close_all()
            try:
                with transaction.atomic():
                    lifecycle._acquire_registry_shared_advisory_lock()
                    shared_acquired.set()
                    if not release_shared.wait(timeout=10):
                        raise AssertionError("shared lock release timed out")
            except Exception as exc:
                errors.append(repr(exc))
            finally:
                connections.close_all()

        def activation_connection():
            connections.close_all()
            try:
                if not shared_acquired.wait(timeout=10):
                    raise AssertionError("shared lock acquisition timed out")
                with transaction.atomic():
                    enforce._advisory_lock()
                    exclusive_acquired.set()
            except Exception as exc:
                errors.append(repr(exc))
            finally:
                connections.close_all()

        scanner = threading.Thread(target=scanner_connection)
        activation = threading.Thread(target=activation_connection)
        scanner.start()
        activation.start()
        self.assertTrue(shared_acquired.wait(timeout=10))
        self.assertFalse(
            exclusive_acquired.wait(timeout=0.25),
            "activation exclusive lock crossed a live scanner shared barrier",
        )
        release_shared.set()
        scanner.join(timeout=10)
        activation.join(timeout=10)
        self.assertFalse(scanner.is_alive() or activation.is_alive())
        self.assertTrue(exclusive_acquired.is_set())
        self.assertEqual(errors, [])

    def test_queued_task_rejects_any_registry_trust_root_drift_without_writes(self):
        now = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
        registry, events = self._active_registry(member_count=1, due_at=now)
        event = events[0]
        cases = (
            {"expected_registry_root_sha256": "9" * 64},
            {"expected_registry_membership_sha256": "8" * 64},
            {"expected_registry_member_count": 2},
            {"expected_registry_activation_id": "7" * 64},
        )
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=registry.root_sha256,
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=registry.membership_sha256,
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=registry.member_count,
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=registry.activation_id,
        ), patch("stable.tasks.timezone.now", return_value=now):
            base = {
                "event_id": event.id,
                "expected_generation": 1,
                "attempt_token": "",
                "expected_runtime_enabled": True,
                "expected_runtime_mode": "enforce",
                "expected_registry_root_sha256": registry.root_sha256,
                "expected_registry_membership_sha256": registry.membership_sha256,
                "expected_registry_member_count": registry.member_count,
                "expected_registry_activation_id": registry.activation_id,
            }
            for changed in cases:
                result = advance_race_event_lifecycle_task(**{**base, **changed})
                self.assertEqual(
                    result["reason"], "lifecycle_registry_runtime_config_mismatch"
                )
                event.refresh_from_db()
                self.assertEqual(event.status, "scheduled")

    def test_registry_task_preserves_service_noop_reason_code(self):
        now = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
        registry, events = self._active_registry(member_count=1, due_at=now)
        event = events[0]
        type(event).objects.filter(pk=event.pk).update(
            manual_lock_flags={"operator": True}
        )
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256=registry.root_sha256,
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256=registry.membership_sha256,
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT=registry.member_count,
            RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID=registry.activation_id,
        ), patch("stable.tasks.timezone.now", return_value=now):
            result = advance_race_event_lifecycle_task(
                event_id=event.id, expected_generation=1, attempt_token="",
                expected_runtime_enabled=True, expected_runtime_mode="enforce",
                expected_registry_root_sha256=registry.root_sha256,
                expected_registry_membership_sha256=registry.membership_sha256,
                expected_registry_member_count=registry.member_count,
                expected_registry_activation_id=registry.activation_id,
            )
        self.assertTrue(result["processed"])
        self.assertEqual(result["action"], "noop")
        self.assertEqual(result["reason_code"], "registry_event_manual_lock")

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_stale_task_after_off_or_registry_rotation_does_zero_write(self):
        service = _service(self)
        now = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
        registry, events = self._active_registry(member_count=1, due_at=now)
        event = events[0]
        before = event.status
        result = service.apply_registry_lifecycle_decision(
            event_id=event.id,
            expected_generation=1,
            now=now,
            expected_registry_root_sha256=registry.root_sha256,
            expected_registry_membership_sha256=registry.membership_sha256,
            expected_registry_member_count=registry.member_count,
            expected_registry_activation_id=registry.activation_id,
            expected_runtime_enabled=True,
            expected_runtime_mode="enforce",
        )
        event.refresh_from_db()
        self.assertEqual(result.reason_code, "lifecycle_disabled_mid_flight")
        self.assertEqual(event.status, before)

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=True,
        RACE_EVENT_LIFECYCLE_MODE="enforce",
    )
    def test_per_event_apply_uses_shared_rotation_barrier_without_root_row_lock(self):
        service = _service(self)
        Registry, _ = _models(self)
        now = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
        registry, events = self._active_registry(member_count=1, due_at=now)
        with patch.object(service, "_advisory_shared_lock") as shared_lock, patch.object(
            Registry.objects,
            "select_for_update",
            side_effect=AssertionError("per-event apply must not lock the root row"),
        ):
            result = service.apply_registry_lifecycle_decision(
                event_id=events[0].id,
                expected_generation=1,
                now=now,
                expected_registry_root_sha256=registry.root_sha256,
                expected_registry_membership_sha256=registry.membership_sha256,
                expected_registry_member_count=registry.member_count,
                expected_registry_activation_id=registry.activation_id,
                expected_runtime_enabled=True,
                expected_runtime_mode="enforce",
            )
        shared_lock.assert_called_once_with()
        self.assertNotEqual(result.reason_code, "registry_root_stale")

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=True,
        RACE_EVENT_LIFECYCLE_MODE="enforce",
    )
    def test_stale_task_for_retired_predecessor_root_does_zero_write(self):
        service = _service(self)
        Registry, _ = _models(self)
        now = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
        predecessor, events = self._active_registry(member_count=1, due_at=now)
        predecessor.is_active = False
        predecessor.state = "retired"
        predecessor.save(update_fields=("is_active", "state", "updated_at"))
        Registry.objects.create(
            root_sha256="1" * 64, generation=2, predecessor=predecessor,
            membership_sha256="2" * 64, member_count=0, state="active",
            is_active=True, activation_id="3" * 64, approved_commit="d" * 40,
            selector_scope={}, scope_sha256="4" * 64,
            census_cutoff=now, apply_expires_at=now + timedelta(days=1),
            runtime_valid_until=now + timedelta(days=35),
        )
        result = service.apply_registry_lifecycle_decision(
            event_id=events[0].id, expected_generation=1, now=now,
            expected_registry_root_sha256=predecessor.root_sha256,
            expected_registry_membership_sha256=predecessor.membership_sha256,
            expected_registry_member_count=predecessor.member_count,
            expected_registry_activation_id=predecessor.activation_id,
            expected_runtime_enabled=True, expected_runtime_mode="enforce",
        )
        events[0].refresh_from_db()
        self.assertEqual(result.reason_code, "registry_root_stale")
        self.assertEqual(events[0].status, "scheduled")

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_concurrent_same_registry_promotion_is_applied_plus_replay(self):
        # The test body is a real two-connection race on PostgreSQL. SQLite
        # cannot prove row/advisory lock behavior, so only this case is skipped.
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL concurrency proof requires PostgreSQL")
        service = _service(self)
        Registry, Membership = _models(self)
        now = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
        event_ids = []
        enrollment_sha_by_event = {}
        for index in range(3):
            race_at = now + timedelta(days=1, hours=index)
            event = _make_event(
                slug=f"pg-promote-{index}", race_datetime=race_at,
                local_date=race_at.date(),
            )
            control = _make_control(event, mode="shadow", next_refresh_at=race_at)
            control.enrollment_manifest_sha256 = ("1" if index == 0 else "2") * 64
            control.manifest_data = {
                "schema_version": 2,
                "enrollment_schedule_hash": _schedule_hash(event),
                "allowed_us_zones": [],
            }
            control.save()
            event_ids.append(event.id)
            enrollment_sha_by_event[event.id] = control.enrollment_manifest_sha256
        scope = service.build_registry_selector_scope(
            kind="datetime_7d_canary", cutoff=now,
            window_end=now + timedelta(days=7), limit=20,
            predecessor_carry_forward=True,
        )
        raw = service.build_registry_artifact(
            event_ids=event_ids,
            enrollment_sha_by_event=enrollment_sha_by_event,
            approved_commit="d" * 40, generation=1,
            selector_scope=scope, now=now,
        )
        manifest = service.load_registry_manifest_bytes(
            raw, expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
            expected_commit="d" * 40, now=now,
        )
        barrier = threading.Barrier(2)
        outcomes = []
        errors = []

        def worker():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                outcomes.append(service.promote_registry(manifest, apply=True).outcome)
            except Exception as exc:  # surfaced below; never silently swallowed
                errors.append(repr(exc))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertCountEqual(outcomes, ["applied", "replay"])
        self.assertEqual(Registry.objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 3)

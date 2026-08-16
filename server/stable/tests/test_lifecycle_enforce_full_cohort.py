"""Load-bearing RED contracts for the full lifecycle enforce registry.

These tests intentionally import the new service lazily so the pre-implementation
suite is collected successfully and fails with an explicit capability assertion.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from django.apps import apps
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.core.management import call_command
from django.db.models.deletion import ProtectedError

from stable.services.race_event_lifecycle_enrollment import _schedule_hash
from stable.models import RaceEventLifecycleControl
from stable.test_race_event_lifecycle import _make_control, _make_event


OID = "a" * 40
ENROLLMENT_A = "1" * 64
ENROLLMENT_B = "2" * 64


def _service(testcase: TestCase):
    try:
        return importlib.import_module(
            "stable.services.race_event_lifecycle_enforce"
        )
    except ModuleNotFoundError as exc:
        testcase.fail(
            "目标能力缺失：尚未实现 full-cohort registry service "
            "stable.services.race_event_lifecycle_enforce"
        )
        raise AssertionError from exc


def _models(testcase: TestCase):
    try:
        return (
            apps.get_model("stable", "RaceEventLifecycleEnforceRegistry"),
            apps.get_model("stable", "RaceEventLifecycleEnforceMembership"),
        )
    except LookupError as exc:
        testcase.fail(
            "目标能力缺失：尚未新增 registry/membership 结构化模型"
        )
        raise AssertionError from exc


class FullCohortRegistryModelContracts(TestCase):
    def test_only_one_registry_can_be_active_and_membership_is_unique(self):
        Registry, Membership = _models(self)
        first = Registry.objects.create(
            root_sha256="3" * 64,
            generation=1,
            membership_sha256="4" * 64,
            member_count=1,
            state="active",
            is_active=True,
            activation_id="5" * 64,
            approved_commit=OID,
            selector_scope={},
            scope_sha256="6" * 64,
            census_cutoff=datetime(2026, 8, 11, tzinfo=timezone.utc),
            apply_expires_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
            runtime_valid_until=datetime(2026, 9, 10, tzinfo=timezone.utc),
        )
        event = _make_event(slug="registry-unique", local_date=datetime(2026, 8, 12).date())
        fields = dict(
            registry=first,
            event=event,
            entry_sha256="7" * 64,
            source_enrollment_sha256=ENROLLMENT_A,
            schedule_generation=1,
            schedule_hash=_schedule_hash(event),
            country_region="japan",
            timezone_name="Asia/Tokyo",
        )
        Membership.objects.create(**fields)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Membership.objects.create(**fields)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Registry.objects.create(
                    root_sha256="8" * 64,
                    generation=2,
                    membership_sha256="9" * 64,
                    member_count=0,
                    state="active",
                    is_active=True,
                    activation_id="a" * 64,
                    approved_commit=OID,
                    selector_scope={},
                    scope_sha256="b" * 64,
                    census_cutoff=datetime(2026, 8, 11, tzinfo=timezone.utc),
                    apply_expires_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
                    runtime_valid_until=datetime(2026, 9, 10, tzinfo=timezone.utc),
                )

        with self.assertRaises(ProtectedError):
            event.delete()


class FullCohortArtifactAndSelectorContracts(TestCase):
    def setUp(self):
        self.service = None
        self.cutoff = datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)

    def svc(self):
        if self.service is None:
            self.service = _service(self)
        return self.service

    def _eligible(self, *, slug: str, at: datetime, priority="P2", featured=False):
        event = _make_event(
            slug=slug,
            race_datetime=at,
            local_date=at.date(),
            priority=priority,
            is_featured=featured,
        )
        control = _make_control(event, mode="shadow", next_refresh_at=at)
        control.enrollment_manifest_sha256 = ENROLLMENT_A
        control.manifest_data = {
            "schema_version": 2,
            "enrollment_schedule_hash": _schedule_hash(event),
            "allowed_us_zones": [],
        }
        control.save()
        type(event).objects.filter(pk=event.pk).update(
            created_at=self.cutoff - timedelta(seconds=2),
            updated_at=self.cutoff - timedelta(seconds=1),
        )
        event.refresh_from_db()
        return event

    def test_registry_accepts_three_members_and_multiple_enrollment_roots(self):
        service = self.svc()
        events = [
            self._eligible(slug=f"multi-root-{i}", at=self.cutoff + timedelta(hours=i + 1))
            for i in range(3)
        ]
        scope = service.build_registry_selector_scope(
            kind="datetime_7d_canary",
            cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=7),
            limit=20,
            predecessor_carry_forward=True,
        )
        raw = service.build_registry_artifact(
            event_ids=[event.id for event in events],
            enrollment_sha_by_event={
                events[0].id: ENROLLMENT_A,
                events[1].id: ENROLLMENT_B,
                events[2].id: ENROLLMENT_B,
            },
            approved_commit=OID,
            generation=1,
            selector_scope=scope,
            now=self.cutoff,
        )
        manifest = service.load_registry_manifest_bytes(
            raw,
            expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
            expected_commit=OID,
            now=self.cutoff,
        )
        self.assertEqual(manifest.event_ids, tuple(sorted(event.id for event in events)))

        self.assertEqual(
            set(manifest.enrollment_sha_by_event.values()),
            {ENROLLMENT_A, ENROLLMENT_B},
        )

        malformed = json.loads(raw)
        malformed["events"]["0"] = malformed["events"].pop(
            str(events[0].id)
        )
        malformed.pop("content_sha256")
        from stable.services.race_event_lifecycle_enrollment import _canonical_bytes
        malformed["content_sha256"] = hashlib.sha256(
            _canonical_bytes(malformed)
        ).hexdigest()
        malformed_raw = _canonical_bytes(malformed)
        with self.assertRaises(service.RegistryError):
            service.load_registry_manifest_bytes(
                malformed_raw,
                expected_raw_sha256=hashlib.sha256(malformed_raw).hexdigest(),
                expected_commit=OID,
                now=self.cutoff,
            )

        invalid_full = json.loads(raw)
        invalid_full["selector_scope"].update(
            {
                "kind": "full_eligible",
                "window_end": None,
                "require_datetime": False,
                "limit": 1,
            }
        )
        invalid_full["scope_sha256"] = service.scope_sha256(
            invalid_full["selector_scope"]
        )
        invalid_full.pop("content_sha256")
        invalid_full["content_sha256"] = hashlib.sha256(
            _canonical_bytes(invalid_full)
        ).hexdigest()
        invalid_full_raw = _canonical_bytes(invalid_full)
        with self.assertRaisesRegex(service.RegistryError, "limit=None"):
            service.load_registry_manifest_bytes(
                invalid_full_raw,
                expected_raw_sha256=hashlib.sha256(invalid_full_raw).hexdigest(),
                expected_commit=OID,
                now=self.cutoff,
            )

        invalid_scope = dict(scope, unexpected=True)
        with self.assertRaises(service.RegistryError):
            service.select_registry_candidates(scope=invalid_scope)

    def test_artifact_builder_rejects_payload_larger_than_loader_limit(self):
        service = self.svc()
        events = [
            self._eligible(
                slug=f"oversized-artifact-{index}",
                at=self.cutoff + timedelta(hours=index),
            )
            for index in range(1, 4)
        ]
        event_ids = [event.id for event in events]
        enrollment = {event_id: ENROLLMENT_A for event_id in event_ids}
        scope = service.build_registry_selector_scope(
            kind="datetime_7d_canary",
            cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=7),
            limit=20,
            predecessor_carry_forward=True,
        )
        raw = service.build_registry_artifact(
            event_ids=event_ids,
            enrollment_sha_by_event=enrollment,
            approved_commit=OID,
            generation=1,
            selector_scope=scope,
            now=self.cutoff,
        )
        with patch.object(service, "MAX_ARTIFACT_BYTES", len(raw) - 1):
            with self.assertRaisesRegex(service.RegistryError, "artifact.*超限"):
                service.build_registry_artifact(
                    event_ids=event_ids,
                    enrollment_sha_by_event=enrollment,
                    approved_commit=OID,
                    generation=1,
                    selector_scope=scope,
                    now=self.cutoff,
                )

    def test_scope_is_canonical_and_sha_covers_every_selector_field(self):
        service = self.svc()
        kwargs = dict(
            kind="no_time_canary",
            cutoff=self.cutoff,
            window_end=None,
            explicit_event_ids=[9, 3, 9, 5],
            limit=None,
            predecessor_carry_forward=True,
        )
        first = service.build_registry_selector_scope(**kwargs)
        second = service.build_registry_selector_scope(
            **{**kwargs, "explicit_event_ids": [5, 9, 3]}
        )
        self.assertEqual(first, second)
        self.assertEqual(first["explicit_event_ids"], [3, 5, 9])
        required = {
            "kind", "cutoff", "window_end", "start_inclusive", "end_inclusive",
            "require_datetime", "explicit_event_ids", "limit", "order_by",
            "predecessor_carry_forward",
        }
        self.assertEqual(set(first), required)
        digest = service.scope_sha256(first)
        changed = dict(first, limit=1)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertNotEqual(digest, service.scope_sha256(changed))
        canonical = json.dumps(first, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(digest, hashlib.sha256(canonical).hexdigest())
        with self.assertRaisesRegex(self.svc().RegistryError, "limit=None"):
            self.svc().build_registry_selector_scope(
                kind="full_eligible", cutoff=self.cutoff, window_end=None,
                limit=1, predecessor_carry_forward=True,
            )
        for kind, days, invalid_limit in (
            ("datetime_7d_canary", 7, None),
            ("datetime_7d_canary", 7, 19),
            ("datetime_30d", 30, None),
            ("datetime_30d", 30, 101),
        ):
            with self.subTest(kind=kind, invalid_limit=invalid_limit), self.assertRaisesRegex(
                self.svc().RegistryError, "limit"
            ):
                self.svc().build_registry_selector_scope(
                    kind=kind, cutoff=self.cutoff,
                    window_end=self.cutoff + timedelta(days=days),
                    limit=invalid_limit, predecessor_carry_forward=True,
                )

    def test_selector_includes_p2_non_featured_and_stably_truncates_equal_times(self):
        service = self.svc()
        same_at = self.cutoff + timedelta(days=1)
        events = [
            self._eligible(slug=f"stable-order-{i}", at=same_at)
            for i in range(105)
        ]
        scope = service.build_registry_selector_scope(
            kind="datetime_30d",
            cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=30),
            limit=100,
            predecessor_carry_forward=True,
        )
        census = service.select_registry_candidates(scope=scope)
        expected = sorted(event.id for event in events)[:100]
        self.assertEqual(list(census.included_event_ids), expected)
        self.assertEqual(census.inspected, 105)
        self.assertEqual(
            census.included + census.blocked_by_reason + census.blocked_by_scope,
            census.inspected,
        )

    def test_cutoff_snapshot_excludes_late_eligibility_change_and_reports_successor(self):
        service = self.svc()
        event = self._eligible(
            slug="cutoff-drift",
            at=self.cutoff + timedelta(days=1),
        )
        # A mutation after the frozen census cannot silently change generation 1.
        event.updated_at = self.cutoff + timedelta(seconds=1)
        event.save(update_fields=("updated_at",))
        scope = service.build_registry_selector_scope(
            kind="full_eligible", cutoff=self.cutoff, window_end=None,
            limit=None, predecessor_carry_forward=True,
        )
        census = service.select_registry_candidates(scope=scope)
        self.assertNotIn(event.id, census.included_event_ids)
        self.assertIn(event.id, census.successor_pending_event_ids)

    def test_missing_control_remains_in_frozen_scope_as_enrollment_required(self):
        event = _make_event(
            slug="missing-control-enrollment-required",
            race_datetime=self.cutoff + timedelta(days=1),
            local_date=(self.cutoff + timedelta(days=1)).date(),
            priority="P2",
            is_featured=False,
        )
        type(event).objects.filter(pk=event.pk).update(
            created_at=self.cutoff - timedelta(seconds=2),
            updated_at=self.cutoff - timedelta(seconds=1),
        )
        scope = self.svc().build_registry_selector_scope(
            kind="full_eligible", cutoff=self.cutoff, window_end=None,
            limit=None, predecessor_carry_forward=True,
        )
        census = self.svc().select_registry_candidates(scope=scope)
        self.assertIn(event.id, census.included_event_ids)
        self.assertIn(event.id, census.enrollment_required_event_ids)
        self.assertNotIn("missing_control", census.reason_counts)

    def test_datetime_selection_is_truncated_by_time_then_emits_canonical_ids(self):
        late = self._eligible(
            slug="canonical-id-late", at=self.cutoff + timedelta(days=2)
        )
        early = self._eligible(
            slug="canonical-id-early", at=self.cutoff + timedelta(days=1)
        )
        scope = self.svc().build_registry_selector_scope(
            kind="datetime_7d_canary", cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=7), limit=20,
            predecessor_carry_forward=True,
        )
        census = self.svc().select_registry_candidates(scope=scope)
        self.assertEqual(census.included_event_ids, tuple(sorted((late.id, early.id))))

    def test_carry_forward_false_does_not_inherit_predecessor(self):
        predecessor = self._eligible(
            slug="no-carry-predecessor", at=self.cutoff + timedelta(days=31)
        )
        scope = self.svc().build_registry_selector_scope(
            kind="datetime_30d", cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=30), limit=100,
            predecessor_carry_forward=False,
        )
        census = self.svc().select_registry_candidates(
            scope=scope, predecessor_event_ids=[predecessor.id]
        )
        self.assertNotIn(predecessor.id, census.included_event_ids)

    def test_only_running_predecessor_is_carried_across_rotation(self):
        running_predecessor = self._eligible(
            slug="running-predecessor", at=self.cutoff + timedelta(hours=1)
        )
        running_newcomer = self._eligible(
            slug="running-newcomer", at=self.cutoff + timedelta(hours=2)
        )
        finished_predecessor = self._eligible(
            slug="finished-predecessor", at=self.cutoff + timedelta(hours=3)
        )
        type(running_predecessor).objects.filter(
            pk__in=(running_predecessor.pk, running_newcomer.pk)
        ).update(status="running", updated_at=self.cutoff - timedelta(seconds=1))
        type(finished_predecessor).objects.filter(pk=finished_predecessor.pk).update(
            status="finished", updated_at=self.cutoff - timedelta(seconds=1)
        )
        scope = self.svc().build_registry_selector_scope(
            kind="datetime_7d_canary", cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=7), limit=20,
            predecessor_carry_forward=True,
        )
        census = self.svc().select_registry_candidates(
            scope=scope,
            predecessor_event_ids=[running_predecessor.id, finished_predecessor.id],
        )
        self.assertIn(running_predecessor.id, census.included_event_ids)
        self.assertNotIn(running_newcomer.id, census.included_event_ids)
        self.assertNotIn(finished_predecessor.id, census.included_event_ids)

    def test_prepare_uses_generation_time_not_past_cutoff_and_rejects_future_cutoff(self):
        event = self._eligible(
            slug="prepare-generation-clock",
            at=self.cutoff + timedelta(hours=1),
        )
        generated_at = self.cutoff + timedelta(hours=10)
        with TemporaryDirectory() as tmp, patch(
            "stable.management.commands.prepare_race_event_lifecycle_enforce_registry.timezone.now",
            return_value=generated_at,
        ):
            output = Path(tmp) / "registry.json"
            call_command(
                "prepare_race_event_lifecycle_enforce_registry",
                scope_kind="datetime_7d_canary", cutoff=self.cutoff.isoformat(),
                limit=20, approved_commit=OID, generation=1,
                output=str(output),
            )
            artifact = json.loads(output.read_bytes())
            self.assertEqual(
                datetime.fromisoformat(artifact["generated_at"]), generated_at
            )
            self.assertEqual(
                datetime.fromisoformat(artifact["apply_expires_at"]),
                generated_at + timedelta(hours=24),
            )
            self.assertEqual(
                datetime.fromisoformat(artifact["runtime_valid_until"]),
                generated_at + timedelta(days=35),
            )
            with self.assertRaisesRegex(Exception, "future|未来|晚于"):
                call_command(
                    "prepare_race_event_lifecycle_enforce_registry",
                    scope_kind="datetime_7d_canary",
                    cutoff=(generated_at + timedelta(seconds=1)).isoformat(),
                    limit=20, approved_commit=OID, generation=1,
                    output=str(Path(tmp) / "future.json"),
                )

    def test_prepare_command_emits_canonical_census_and_20_event_batches_without_writes(self):
        events = []
        for index in range(21):
            at = self.cutoff + timedelta(days=1, minutes=index)
            event = _make_event(
                slug=f"prepare-enrollment-{index}", race_datetime=at,
                local_date=at.date(), priority="P2", is_featured=False,
            )
            type(event).objects.filter(pk=event.pk).update(
                created_at=self.cutoff - timedelta(seconds=2),
                updated_at=self.cutoff - timedelta(seconds=1),
            )
            events.append(event)
        Registry, Membership = _models(self)
        before = (Registry.objects.count(), Membership.objects.count(), RaceEventLifecycleControl.objects.count())
        with TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            census_path = Path(tmp) / "census.json"
            plan_path = Path(tmp) / "enrollment-plan.json"
            stdout = StringIO()
            call_command(
                "prepare_race_event_lifecycle_enforce_registry",
                scope_kind="full_eligible",
                cutoff=self.cutoff.isoformat(),
                approved_commit=OID,
                generation=1,
                output=str(registry_path),
                census_output=str(census_path),
                enrollment_plan_output=str(plan_path),
                stdout=stdout,
            )
            self.assertFalse(registry_path.exists())
            census_raw = census_path.read_bytes()
            plan_raw = plan_path.read_bytes()
            self.assertEqual(census_raw, self.svc().canonical_artifact_bytes(json.loads(census_raw)))
            self.assertEqual(plan_raw, self.svc().canonical_artifact_bytes(json.loads(plan_raw)))
            plan = json.loads(plan_raw)
            self.assertEqual([len(batch["event_ids"]) for batch in plan["batches"]], [20, 1])
            self.assertEqual(
                sorted(event_id for batch in plan["batches"] for event_id in batch["event_ids"]),
                sorted(event.id for event in events),
            )
            self.assertIn("status=enrollment_required", stdout.getvalue())
        self.assertEqual(
            (Registry.objects.count(), Membership.objects.count(), RaceEventLifecycleControl.objects.count()),
            before,
        )

    def test_prepare_us_enrollment_requires_reviewed_allowlist_and_emits_direct_command(self):
        at = self.cutoff + timedelta(days=1)
        event = _make_event(
            slug="prepare-us-allowlist", race_datetime=at,
            local_date=at.date(), country_region="united_states",
            timezone_name="America/New_York", priority="P2", is_featured=False,
        )
        type(event).objects.filter(pk=event.pk).update(
            created_at=self.cutoff - timedelta(seconds=2),
            updated_at=self.cutoff - timedelta(seconds=1),
        )
        with TemporaryDirectory() as tmp:
            blocked_registry = Path(tmp) / "blocked-registry.json"
            blocked_plan = Path(tmp) / "blocked-plan.json"
            stdout = StringIO()
            call_command(
                "prepare_race_event_lifecycle_enforce_registry",
                scope_kind="full_eligible", cutoff=self.cutoff.isoformat(),
                approved_commit=OID, generation=1,
                output=str(blocked_registry),
                enrollment_plan_output=str(blocked_plan), stdout=stdout,
            )
            blocked = json.loads(blocked_plan.read_bytes())
            self.assertEqual(blocked["batches"], [])
            self.assertEqual(
                blocked["blocked_pending_us_allowlist_event_ids"], [event.id]
            )
            self.assertIn("status=blocked_pending_us_allowlist", stdout.getvalue())

            ready_registry = Path(tmp) / "ready-registry.json"
            ready_plan = Path(tmp) / "ready-plan.json"
            call_command(
                "prepare_race_event_lifecycle_enforce_registry",
                scope_kind="full_eligible", cutoff=self.cutoff.isoformat(),
                approved_commit=OID, generation=1,
                output=str(ready_registry),
                enrollment_plan_output=str(ready_plan),
                allowed_us_zone=[
                    f"{event.id}=America/New_York",
                    f"{event.id}=America/Los_Angeles",
                ],
            )
            ready = json.loads(ready_plan.read_bytes())
            self.assertEqual(ready["blocked_pending_us_allowlist_event_ids"], [])
            command = ready["batches"][0]["prepare_command"]
            self.assertEqual(command["command"], "prepare_race_event_lifecycle_enrollment")
            self.assertEqual(command["event_ids"], [str(event.id)])
            self.assertEqual(command["approved_commit"], OID)
            self.assertEqual(
                command["allowed_us_zone"],
                [
                    f"{event.id}=America/Los_Angeles",
                    f"{event.id}=America/New_York",
                ],
            )
            self.assertEqual(
                command["output_dir"],
                f"{ready_registry}.enrollment-batches/batch-0001",
            )

    def test_prepare_fails_before_writing_any_artifact_when_registry_output_exists(self):
        with TemporaryDirectory() as tmp:
            registry = Path(tmp) / "registry.json"
            census = Path(tmp) / "census.json"
            plan = Path(tmp) / "plan.json"
            registry.write_bytes(b"do-not-overwrite")
            with self.assertRaisesRegex(Exception, "已存在|exists"):
                call_command(
                    "prepare_race_event_lifecycle_enforce_registry",
                    scope_kind="full_eligible", cutoff=self.cutoff.isoformat(),
                    approved_commit=OID, generation=1,
                    output=str(registry), census_output=str(census),
                    enrollment_plan_output=str(plan),
                )
            self.assertEqual(registry.read_bytes(), b"do-not-overwrite")
            self.assertFalse(census.exists())
            self.assertFalse(plan.exists())

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_predecessor_is_carried_forward_and_legacy_canary_evidence_is_preserved(self):
        service = self.svc()
        predecessor = self._eligible(
            slug="predecessor-outside-window",
            at=self.cutoff + timedelta(days=31),
        )
        newcomer = self._eligible(
            slug="successor-inside-window",
            at=self.cutoff + timedelta(days=2),
        )
        predecessor_control = predecessor.lifecycle_control
        predecessor_control.manifest_data["enforce_canary"] = {
            "raw_sha256": "9" * 64,
            "activation_state": "inactive",
            "activation_id": "8" * 64,
        }
        predecessor_control.save(update_fields=("manifest_data", "updated_at"))
        legacy_evidence = predecessor_control.manifest_data["enforce_canary"].copy()

        scope = service.build_registry_selector_scope(
            kind="datetime_30d", cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=30), limit=100,
            predecessor_carry_forward=True,
        )
        census = service.select_registry_candidates(
            scope=scope,
            predecessor_event_ids=[predecessor.id],
        )
        self.assertEqual(
            list(census.included_event_ids),
            [predecessor.id, newcomer.id],
            "a still-eligible predecessor is not silently truncated by the new window",
        )
        raw = service.build_registry_artifact(
            event_ids=census.included_event_ids,
            enrollment_sha_by_event={
                predecessor.id: ENROLLMENT_A,
                newcomer.id: ENROLLMENT_A,
            },
            approved_commit=OID,
            generation=2,
            predecessor_root_sha256="7" * 64,
            selector_scope=scope,
            now=self.cutoff,
        )
        manifest = service.load_registry_manifest_bytes(
            raw,
            expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
            expected_commit=OID,
            now=self.cutoff,
        )
        self.assertEqual(manifest.predecessor_root_sha256, "7" * 64)
        Registry, _ = _models(self)
        Registry.objects.create(
            root_sha256="7" * 64, generation=1,
            membership_sha256="6" * 64, member_count=0,
            state="retired", is_active=False, activation_id="",
            approved_commit=OID,
            selector_scope={"kind": "datetime_30d"}, scope_sha256="5" * 64,
            census_cutoff=self.cutoff,
            apply_expires_at=self.cutoff + timedelta(days=1),
            runtime_valid_until=self.cutoff + timedelta(days=35),
        )
        result = service.promote_registry(manifest, apply=True)
        self.assertEqual(result.outcome, "applied")
        predecessor_control.refresh_from_db()
        self.assertEqual(
            predecessor_control.manifest_data["enforce_canary"],
            legacy_evidence,
            "registry promotion must not rewrite historical canary provenance",
        )


class FullCohortRuntimeContracts(TestCase):
    def test_single_event_membership_validation_is_constant_query_count(self):
        service = _service(self)
        Registry, Membership = _models(self)

        def build_registry(size: int, generation: int):
            registry = Registry.objects.create(
                root_sha256=f"{generation:064x}", generation=generation,
                membership_sha256=f"{generation + 10:064x}", member_count=size,
                state="active", is_active=True,
                activation_id=f"{generation + 20:064x}", approved_commit=OID,
                selector_scope={}, scope_sha256=f"{generation + 30:064x}",
                census_cutoff=datetime(2026, 8, 11, tzinfo=timezone.utc),
                apply_expires_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
                runtime_valid_until=datetime(2026, 9, 10, tzinfo=timezone.utc),
            )
            target = None
            for index in range(size):
                event = _make_event(
                    slug=f"o1-{generation}-{index}",
                    local_date=datetime(2026, 8, 12).date(),
                )
                Membership.objects.create(
                    registry=registry, event=event, entry_sha256=f"{index + 100:064x}",
                    source_enrollment_sha256=ENROLLMENT_A, schedule_generation=1,
                    schedule_hash=_schedule_hash(event), country_region="japan",
                    timezone_name="Asia/Tokyo",
                )
                target = target or event
            return registry, target

        query_counts = []
        for generation, size in enumerate((1, 201, 1001), start=1):
            registry, target = build_registry(size, generation)
            with CaptureQueriesContext(connection) as queries:
                result = service.validate_active_registry_membership(
                    event_id=target.id,
                    root_sha256=registry.root_sha256,
                    membership_sha256=registry.membership_sha256,
                    member_count=registry.member_count,
                    activation_id=registry.activation_id,
                )
            self.assertTrue(result.valid)
            query_counts.append(len(queries))
            sql = "\n".join(query["sql"] for query in queries)
            self.assertNotIn(" IN (", sql.upper())
            registry.delete()
        self.assertLessEqual(max(query_counts), 6)
        self.assertLessEqual(
            max(query_counts) - min(query_counts), 1,
            f"per-event validation query count drifted with cohort size: {query_counts}",
        )

    def test_scanner_cannot_claim_membership_from_retired_root(self):
        from stable.services.race_event_lifecycle import claim_due_lifecycle_controls

        Registry, Membership = _models(self)
        now = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
        registry = Registry.objects.create(
            root_sha256="a" * 64, generation=1,
            membership_sha256="b" * 64, member_count=1,
            state="retired", is_active=False, activation_id="c" * 64,
            approved_commit=OID, selector_scope={}, scope_sha256="d" * 64,
            census_cutoff=now - timedelta(days=1),
            apply_expires_at=now + timedelta(days=1),
            runtime_valid_until=now + timedelta(days=35),
        )
        event = _make_event(
            slug="retired-root-not-claimable", race_datetime=now,
            local_date=now.date(),
        )
        _make_control(event, mode="enforce", next_refresh_at=now)
        Membership.objects.create(
            registry=registry, event=event, entry_sha256="e" * 64,
            source_enrollment_sha256=ENROLLMENT_A, schedule_generation=1,
            schedule_hash=_schedule_hash(event), country_region="japan",
            timezone_name="Asia/Tokyo",
        )
        with patch(
            "stable.services.race_event_lifecycle._acquire_registry_shared_advisory_lock"
        ) as barrier:
            self.assertEqual(
                claim_due_lifecycle_controls(
                    now=now, batch_size=100, ttl_seconds=240,
                    enforce_registry_id=registry.id,
                ),
                [],
            )
        barrier.assert_called_once_with()
        with patch(
            "stable.services.race_event_lifecycle._acquire_registry_shared_advisory_lock"
        ) as legacy_barrier:
            claim_due_lifecycle_controls(
                now=now, batch_size=100, ttl_seconds=240,
                enforce_event_ids=(),
            )
        legacy_barrier.assert_not_called()


class FullCohortPromotionBatchContracts(TestCase):
    def setUp(self):
        self.service = _service(self)
        self.cutoff = datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)

    def _event(self, index: int):
        at = self.cutoff + timedelta(days=1, minutes=index)
        event = _make_event(
            slug=f"promotion-batch-{index}", race_datetime=at,
            local_date=at.date(), priority="P2", is_featured=False,
        )
        control = _make_control(event, mode="shadow", next_refresh_at=at)
        control.enrollment_manifest_sha256 = ENROLLMENT_A
        control.manifest_data = {
            "schema_version": 2,
            "enrollment_schedule_hash": _schedule_hash(event),
            "allowed_us_zones": [],
        }
        control.save()
        type(event).objects.filter(pk=event.pk).update(
            created_at=self.cutoff - timedelta(seconds=2),
            updated_at=self.cutoff - timedelta(seconds=1),
        )
        event.refresh_from_db()
        return event

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_promotion_resumes_in_batches_and_incomplete_registry_cannot_activate(self):
        Registry, Membership = _models(self)
        events = [self._event(index) for index in range(101)]
        predecessor = Registry.objects.create(
            root_sha256="a" * 64, generation=4,
            membership_sha256="b" * 64, member_count=0,
            state="retired", is_active=False, approved_commit=OID,
            selector_scope={"kind": "full_eligible"}, scope_sha256="c" * 64,
            census_cutoff=self.cutoff,
            apply_expires_at=self.cutoff + timedelta(days=1),
            runtime_valid_until=self.cutoff + timedelta(days=35),
        )
        scope = self.service.build_registry_selector_scope(
            kind="full_eligible", cutoff=self.cutoff, window_end=None,
            limit=None, predecessor_carry_forward=True,
        )
        raw = self.service.build_registry_artifact(
            event_ids=[event.id for event in events],
            enrollment_sha_by_event={event.id: ENROLLMENT_A for event in events},
            approved_commit=OID, generation=5,
            predecessor_root_sha256=predecessor.root_sha256,
            selector_scope=scope,
            now=self.cutoff,
        )
        manifest = self.service.load_registry_manifest_bytes(
            raw, expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
            expected_commit=OID, now=self.cutoff,
        )
        first = self.service.promote_registry(manifest, apply=True)
        self.assertEqual(first.outcome, "partial")
        self.assertEqual(Membership.objects.count(), 100)
        with self.assertRaisesRegex(self.service.RegistryError, "完整|membership"):
            self.service.activate_registry(
                manifest, activation_id="9" * 64
            )
        second = self.service.promote_registry(manifest, apply=True)
        self.assertEqual(second.outcome, "applied")
        self.assertEqual(Membership.objects.count(), 101)
        self.assertEqual(Registry.objects.count(), 2)
        replay = self.service.promote_registry(manifest, apply=True)
        self.assertEqual(replay.outcome, "replay")

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_promotion_dry_run_validates_the_entire_cohort_not_one_apply_batch(self):
        events = [self._event(index) for index in range(3)]
        scope = self.service.build_registry_selector_scope(
            kind="datetime_7d_canary", cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=7),
            limit=20, predecessor_carry_forward=True,
        )
        raw = self.service.build_registry_artifact(
            event_ids=[event.id for event in events],
            enrollment_sha_by_event={event.id: ENROLLMENT_A for event in events},
            approved_commit=OID, generation=1, selector_scope=scope,
            now=self.cutoff,
        )
        manifest = self.service.load_registry_manifest_bytes(
            raw, expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
            expected_commit=OID, now=self.cutoff,
        )
        type(events[-1]).objects.filter(pk=events[-1].pk).update(
            race_datetime=events[-1].race_datetime + timedelta(hours=1)
        )
        with self.assertRaisesRegex(self.service.RegistryError, "漂移"):
            self.service.promote_registry(manifest, apply=False, batch_size=1)

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_promotion_rejects_orphan_or_non_incrementing_predecessor(self):
        Registry, _ = _models(self)
        event = self._event(1)
        scope = self.service.build_registry_selector_scope(
            kind="datetime_30d", cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=30),
            limit=100, predecessor_carry_forward=True,
        )

        def manifest_for(generation, predecessor_root):
            raw = self.service.build_registry_artifact(
                event_ids=[event.id],
                enrollment_sha_by_event={event.id: ENROLLMENT_A},
                approved_commit=OID, generation=generation,
                predecessor_root_sha256=predecessor_root,
                selector_scope=scope, now=self.cutoff,
            )
            return self.service.load_registry_manifest_bytes(
                raw, expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
                expected_commit=OID, now=self.cutoff,
            )

        with self.assertRaisesRegex(self.service.RegistryError, "不存在"):
            self.service.promote_registry(
                manifest_for(2, "8" * 64), apply=True
            )
        predecessor = Registry.objects.create(
            root_sha256="7" * 64, generation=1,
            membership_sha256="6" * 64, member_count=0,
            state="retired", is_active=False, approved_commit=OID,
            selector_scope={"kind": "datetime_30d"}, scope_sha256="5" * 64,
            census_cutoff=self.cutoff,
            apply_expires_at=self.cutoff + timedelta(days=1),
            runtime_valid_until=self.cutoff + timedelta(days=35),
        )
        with self.assertRaisesRegex(self.service.RegistryError, r"predecessor \+ 1"):
            self.service.promote_registry(
                manifest_for(3, predecessor.root_sha256), apply=True
            )
        orphan_successor = manifest_for(2, predecessor.root_sha256)
        self.assertEqual(
            self.service.promote_registry(orphan_successor, apply=True).outcome,
            "applied",
        )
        with self.assertRaisesRegex(self.service.RegistryError, "active predecessor CAS"):
            self.service.activate_registry(
                orphan_successor, activation_id="9" * 64
            )

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_7d_to_30d_requires_same_event_t_and_t_plus_30_registry_proof(self):
        Registry, Membership = _models(self)
        Transition = apps.get_model("stable", "RaceEventLifecycleTransition")
        event = self._event(1)
        predecessor = Registry.objects.create(
            root_sha256="3" * 64, generation=1,
            membership_sha256="4" * 64, member_count=1,
            state="active", is_active=True, activation_id="5" * 64,
            approved_commit=OID,
            selector_scope={"kind": "datetime_7d_canary"}, scope_sha256="6" * 64,
            census_cutoff=self.cutoff,
            apply_expires_at=self.cutoff + timedelta(days=1),
            runtime_valid_until=self.cutoff + timedelta(days=35),
        )
        Membership.objects.create(
            registry=predecessor, event=event, entry_sha256="7" * 64,
            source_enrollment_sha256=ENROLLMENT_A, schedule_generation=1,
            schedule_hash=_schedule_hash(event), country_region="japan",
            timezone_name="Asia/Tokyo",
        )
        scope = self.service.build_registry_selector_scope(
            kind="datetime_30d", cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=30), limit=100,
            predecessor_carry_forward=True,
        )
        raw = self.service.build_registry_artifact(
            event_ids=[event.id],
            enrollment_sha_by_event={event.id: ENROLLMENT_A},
            approved_commit=OID, generation=2,
            predecessor_root_sha256=predecessor.root_sha256,
            selector_scope=scope, now=self.cutoff,
        )
        manifest = self.service.load_registry_manifest_bytes(
            raw, expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
            expected_commit=OID, now=self.cutoff,
        )
        with self.assertRaisesRegex(self.service.RegistryError, r"T/T\+30"):
            self.service.promote_registry(manifest, apply=True)
        for index, (from_status, to_status, reason) in enumerate((
            ("scheduled", "running", "time_reached_race_datetime"),
            ("running", "finished", "time_t_plus_30"),
        )):
            Transition.objects.create(
                event=event, from_status=from_status, to_status=to_status,
                reason_code=reason, effective_at=self.cutoff + timedelta(hours=index),
                record_kind="applied", dedupe_key=f"proof-{index}",
                schedule_generation=1,
                metadata={"enforce_registry": {"root_sha256": predecessor.root_sha256}},
            )
        self.assertEqual(
            self.service.promote_registry(manifest, apply=True).outcome,
            "applied",
        )

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_active_verify_and_replay_accept_real_t_and_t_plus_30_progress(self):
        event = self._event(1)
        scope = self.service.build_registry_selector_scope(
            kind="datetime_7d_canary", cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=7), limit=20,
            predecessor_carry_forward=True,
        )
        raw = self.service.build_registry_artifact(
            event_ids=[event.id],
            enrollment_sha_by_event={event.id: ENROLLMENT_A},
            approved_commit=OID, generation=1,
            selector_scope=scope, now=self.cutoff,
        )
        manifest = self.service.load_registry_manifest_bytes(
            raw, expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
            expected_commit=OID, now=self.cutoff,
        )
        self.assertEqual(
            self.service.promote_registry(manifest, apply=True).outcome,
            "applied",
        )
        activation_id = "9" * 64
        self.service.activate_registry(manifest, activation_id=activation_id)
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
        ):
            RaceEventLifecycleControl.objects.filter(event=event).update(
                enrollment_manifest_sha256=ENROLLMENT_B
            )
            enrollment_drift = self.service.apply_registry_lifecycle_decision(
                event_id=event.id, expected_generation=1,
                now=event.race_datetime,
                expected_registry_root_sha256=manifest.raw_sha256,
                expected_registry_membership_sha256=manifest.data["membership_sha256"],
                expected_registry_member_count=manifest.data["member_count"],
                expected_registry_activation_id=activation_id,
                expected_runtime_enabled=True, expected_runtime_mode="enforce",
            )
            self.assertEqual(
                enrollment_drift.reason_code, "registry_membership_drift"
            )
            control = RaceEventLifecycleControl.objects.get(event=event)
            control.enrollment_manifest_sha256 = ENROLLMENT_A
            control.manifest_data = {
                **control.manifest_data,
                "allowed_us_zones": ["America/Chicago"],
            }
            control.save(
                update_fields=(
                    "enrollment_manifest_sha256",
                    "manifest_data",
                    "updated_at",
                )
            )
            from stable.services.race_event_lifecycle import (
                apply_race_lifecycle_decision as lower_apply,
            )
            event_manager = type(event).objects
            with patch.object(
                event_manager,
                "select_for_update",
                wraps=event_manager.select_for_update,
            ) as lock_event, patch.object(
                self.service,
                "_schedule_hash",
                wraps=self.service._schedule_hash,
            ) as schedule_hash, patch(
                "stable.services.race_event_lifecycle.apply_race_lifecycle_decision",
                wraps=lower_apply,
            ) as delegated_apply:
                schedule_hash.side_effect = lambda locked: (
                    self.fail("registry drift validation read event before row lock")
                    if not lock_event.called
                    else _schedule_hash(locked)
                )
                running = self.service.apply_registry_lifecycle_decision(
                    event_id=event.id, expected_generation=1,
                    now=event.race_datetime,
                    expected_registry_root_sha256=manifest.raw_sha256,
                    expected_registry_membership_sha256=manifest.data["membership_sha256"],
                    expected_registry_member_count=manifest.data["member_count"],
                    expected_registry_activation_id=activation_id,
                    expected_runtime_enabled=True, expected_runtime_mode="enforce",
                )
            self.assertTrue(
                lock_event.called,
                "registry drift validation must hold the event row lock",
            )
            self.assertIsNone(
                delegated_apply.call_args.kwargs["allowed_us_zones"],
                "runtime authorization must use the frozen membership allowlist",
            )
            self.assertEqual(running.action, "applied")
            finished = self.service.apply_registry_lifecycle_decision(
                event_id=event.id, expected_generation=1,
                now=event.race_datetime + timedelta(minutes=30),
                expected_registry_root_sha256=manifest.raw_sha256,
                expected_registry_membership_sha256=manifest.data["membership_sha256"],
                expected_registry_member_count=manifest.data["member_count"],
                expected_registry_activation_id=activation_id,
                expected_runtime_enabled=True, expected_runtime_mode="enforce",
            )
            self.assertEqual(finished.action, "applied")
        event.refresh_from_db()
        self.assertEqual(event.status, "finished")
        verified = self.service.verify_registry_state(
            manifest, expected_state="active",
            expected_activation_id=activation_id,
        )
        self.assertEqual(verified.outcome, "verified_active")
        replay = self.service.activate_registry(
            manifest, activation_id=activation_id
        )
        self.assertEqual(replay.outcome, "replay")
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
        ):
            type(event).objects.filter(pk=event.pk).update(
                manual_lock_flags={"review": True}
            )
            blocked = self.service.apply_registry_lifecycle_decision(
                event_id=event.id, expected_generation=1,
                now=event.race_datetime + timedelta(hours=1),
                expected_registry_root_sha256=manifest.raw_sha256,
                expected_registry_membership_sha256=manifest.data["membership_sha256"],
                expected_registry_member_count=manifest.data["member_count"],
                expected_registry_activation_id=activation_id,
                expected_runtime_enabled=True, expected_runtime_mode="enforce",
            )
            self.assertEqual(blocked.reason_code, "registry_event_manual_lock")
            type(event).objects.filter(pk=event.pk).update(
                manual_lock_flags={}, visibility_status="draft"
            )
            blocked = self.service.apply_registry_lifecycle_decision(
                event_id=event.id, expected_generation=1,
                now=event.race_datetime + timedelta(hours=1),
                expected_registry_root_sha256=manifest.raw_sha256,
                expected_registry_membership_sha256=manifest.data["membership_sha256"],
                expected_registry_member_count=manifest.data["member_count"],
                expected_registry_activation_id=activation_id,
                expected_runtime_enabled=True, expected_runtime_mode="enforce",
            )
            self.assertEqual(blocked.reason_code, "registry_event_not_published")
            type(event).objects.filter(pk=event.pk).update(
                visibility_status="published"
            )
            RaceEventLifecycleControl.objects.filter(event=event).update(
                manual_pause_reason="review"
            )
            blocked = self.service.apply_registry_lifecycle_decision(
                event_id=event.id, expected_generation=1,
                now=event.race_datetime + timedelta(hours=1),
                expected_registry_root_sha256=manifest.raw_sha256,
                expected_registry_membership_sha256=manifest.data["membership_sha256"],
                expected_registry_member_count=manifest.data["member_count"],
                expected_registry_activation_id=activation_id,
                expected_runtime_enabled=True, expected_runtime_mode="enforce",
            )
            self.assertEqual(blocked.reason_code, "registry_control_manual_pause")

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_running_predecessor_rotates_without_losing_t_plus_30_followup(self):
        Registry, Membership = _models(self)
        event = self._event(1)
        predecessor = Registry.objects.create(
            root_sha256="3" * 64, generation=1,
            membership_sha256="4" * 64, member_count=1,
            state="active", is_active=True, activation_id="5" * 64,
            approved_commit=OID,
            selector_scope={"kind": "datetime_7d_canary"}, scope_sha256="6" * 64,
            census_cutoff=self.cutoff,
            apply_expires_at=self.cutoff + timedelta(days=1),
            runtime_valid_until=self.cutoff + timedelta(days=35),
        )
        Membership.objects.create(
            registry=predecessor, event=event, entry_sha256="7" * 64,
            source_enrollment_sha256=ENROLLMENT_A, schedule_generation=1,
            schedule_hash=_schedule_hash(event), country_region="japan",
            timezone_name="Asia/Tokyo",
        )
        type(event).objects.filter(pk=event.pk).update(
            status="running", updated_at=self.cutoff - timedelta(seconds=1)
        )
        control = event.lifecycle_control
        control.mode = "enforce"
        control.next_refresh_at = event.race_datetime + timedelta(minutes=30)
        control.save(update_fields=("mode", "next_refresh_at", "updated_at"))
        scope = self.service.build_registry_selector_scope(
            kind="datetime_7d_canary", cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=7), limit=20,
            predecessor_carry_forward=True,
        )
        census = self.service.select_registry_candidates(
            scope=scope, predecessor_event_ids=[event.id]
        )
        self.assertEqual(census.included_event_ids, (event.id,))
        raw = self.service.build_registry_artifact(
            event_ids=census.included_event_ids,
            enrollment_sha_by_event={event.id: ENROLLMENT_A},
            approved_commit=OID, generation=2,
            predecessor_root_sha256=predecessor.root_sha256,
            selector_scope=scope, now=self.cutoff,
        )
        manifest = self.service.load_registry_manifest_bytes(
            raw, expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
            expected_commit=OID, now=self.cutoff,
        )
        self.assertEqual(self.service.promote_registry(manifest, apply=True).outcome, "applied")
        self.assertEqual(
            self.service.verify_registry_state(
                manifest, expected_state="inactive"
            ).outcome,
            "verified_inactive",
        )
        self.service.activate_registry(manifest, activation_id="9" * 64)
        event.refresh_from_db()
        control.refresh_from_db()
        self.assertEqual(event.status, "running")
        self.assertEqual(
            control.next_refresh_at, event.race_datetime + timedelta(minutes=30)
        )

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_successor_activation_downgrades_every_out_of_scope_enforce_control(self):
        Registry, Membership = _models(self)
        keep, dropped, newcomer = (self._event(index) for index in range(3))
        predecessor = Registry.objects.create(
            root_sha256="3" * 64, generation=1,
            membership_sha256="4" * 64, member_count=2,
            state="active", is_active=True, activation_id="5" * 64,
            approved_commit=OID,
            selector_scope={"kind": "datetime_7d_canary"}, scope_sha256="6" * 64,
            census_cutoff=self.cutoff,
            apply_expires_at=self.cutoff + timedelta(days=1),
            runtime_valid_until=self.cutoff + timedelta(days=35),
        )
        for event in (keep, dropped):
            Membership.objects.create(
                registry=predecessor, event=event, entry_sha256=f"{event.id:064x}",
                source_enrollment_sha256=ENROLLMENT_A, schedule_generation=1,
                schedule_hash=_schedule_hash(event), country_region="japan",
                timezone_name="Asia/Tokyo",
            )
            control = event.lifecycle_control
            control.mode = "enforce"
            control.claim_token = "stale-claim"
            control.claim_generation = 2
            control.claim_expires_at = self.cutoff + timedelta(hours=1)
            control.manifest_data["enforce_canary"] = {"historical": True}
            control.manifest_data["enforce_registry"] = {
                "root_sha256": predecessor.root_sha256,
                "activation_state": "active",
            }
            control.save()
        type(dropped).objects.filter(pk=dropped.pk).update(
            visibility_status="draft",
            updated_at=self.cutoff - timedelta(seconds=1),
        )
        dropped.refresh_from_db()
        scope = self.service.build_registry_selector_scope(
            kind="datetime_7d_canary", cutoff=self.cutoff,
            window_end=self.cutoff + timedelta(days=7),
            explicit_event_ids=[], limit=20, predecessor_carry_forward=True,
        )
        raw = self.service.build_registry_artifact(
            event_ids=[keep.id, newcomer.id],
            enrollment_sha_by_event={keep.id: ENROLLMENT_A, newcomer.id: ENROLLMENT_A},
            approved_commit=OID, generation=2,
            predecessor_root_sha256=predecessor.root_sha256,
            selector_scope=scope, now=self.cutoff,
        )
        manifest = self.service.load_registry_manifest_bytes(
            raw, expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
            expected_commit=OID, now=self.cutoff,
        )
        self.assertEqual(self.service.promote_registry(manifest, apply=True).outcome, "applied")
        self.service.activate_registry(manifest, activation_id="9" * 64)
        keep.lifecycle_control.refresh_from_db()
        self.assertEqual(
            keep.lifecycle_control.claim_token,
            "",
            "claims issued under the predecessor root must not survive rotation",
        )
        dropped.lifecycle_control.refresh_from_db()
        control = dropped.lifecycle_control
        self.assertEqual(control.mode, "shadow")
        self.assertEqual(control.claim_token, "")
        self.assertIsNone(control.next_refresh_at)
        self.assertNotIn("enforce_registry", control.manifest_data)
        self.assertEqual(control.manifest_data["enforce_canary"], {"historical": True})

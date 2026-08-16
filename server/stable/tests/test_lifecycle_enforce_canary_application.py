from __future__ import annotations

import hashlib
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone as django_timezone

from stable.models import OperationLog, RaceEventLifecycleControl
from stable.tasks import (
    advance_race_event_lifecycle_task,
    scan_due_race_event_lifecycle_task,
)
from stable.services.race_event_lifecycle import apply_race_lifecycle_decision
from stable.services.race_event_lifecycle_canary import (
    CanaryError,
    build_canary_artifact,
    load_canary_manifest_bytes,
    promote_canary,
    verify_or_mutate_canary,
)
from stable.services.race_event_lifecycle_enrollment import _schedule_hash
from stable.test_race_event_lifecycle import _make_control, _make_event


OID = "d" * 40
ENROLLMENT_SHA = "e" * 64


class LifecycleEnforceCanaryApplicationTests(TestCase):
    def setUp(self):
        self.generated_at = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
        self.race_times = (
            self.generated_at + timedelta(hours=12),
            self.generated_at + timedelta(hours=14),
        )
        self.events = []
        for index, race_at in enumerate(self.race_times, start=1):
            event = _make_event(
                slug=f"canary-app-{index}",
                race_datetime=race_at,
                local_date=race_at.date(),
            )
            control = _make_control(
                event, mode="shadow", next_refresh_at=race_at,
                schedule_generation=3,
            )
            control.enrollment_manifest_sha256 = ENROLLMENT_SHA
            control.manifest_data = {
                "schema_version": 2,
                "content_sha256": "f" * 64,
                "enrollment_schedule_hash": _schedule_hash(event),
                "allowed_us_zones": [],
            }
            control.save()
            self.events.append(event)
        self.event_ids = [event.id for event in self.events]
        self.raw = build_canary_artifact(
            event_ids=self.event_ids,
            approved_commit=OID,
            now=self.generated_at,
        )
        self.raw_sha = hashlib.sha256(self.raw).hexdigest()
        self.manifest = load_canary_manifest_bytes(
            self.raw,
            expected_raw_sha256=self.raw_sha,
            expected_commit=OID,
            now=self.generated_at,
            require_apply_fresh=True,
        )

    def _activate(self):
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=False,
            RACE_EVENT_LIFECYCLE_MODE="off",
        ):
            result = promote_canary(self.manifest, apply=True)
        self.assertEqual(result.outcome, "applied")
        ids = ",".join(map(str, self.event_ids))
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=self.raw_sha,
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=ids,
        ):
            return verify_or_mutate_canary(
                self.manifest, expected_state="active", activate=True
            )

    def test_manifest_locks_two_events_and_both_deadlines(self):
        self.assertEqual(self.manifest.event_ids, tuple(self.event_ids))
        self.assertEqual(
            self.manifest.data["apply_expires_at"],
            (self.generated_at + timedelta(hours=24)).isoformat(),
        )
        self.assertEqual(
            self.manifest.data["runtime_valid_until"],
            (max(self.race_times) + timedelta(hours=24, minutes=30)).isoformat(),
        )
        with self.assertRaises(CanaryError):
            build_canary_artifact(
                event_ids=self.event_ids[:1], approved_commit=OID,
                now=self.generated_at,
            )

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_promotion_is_atomic_audited_and_idempotent(self):
        first = promote_canary(self.manifest, apply=True)
        self.assertEqual(first.outcome, "applied")
        controls = list(RaceEventLifecycleControl.objects.filter(
            event_id__in=self.event_ids
        ).order_by("event_id"))
        self.assertEqual([item.mode for item in controls], ["enforce", "enforce"])
        self.assertEqual(
            [item.manifest_data["enforce_canary"]["activation_state"] for item in controls],
            ["inactive", "inactive"],
        )
        self.assertEqual(
            OperationLog.objects.filter(
                action_type="lifecycle_enforce_canary_applied",
                target_id=self.raw_sha,
            ).count(), 1,
        )
        updated = [item.updated_at for item in controls]
        replay = promote_canary(self.manifest, apply=True)
        self.assertEqual(replay.outcome, "replay")
        self.assertEqual(
            list(RaceEventLifecycleControl.objects.filter(
                event_id__in=self.event_ids
            ).order_by("event_id").values_list("updated_at", flat=True)),
            updated,
        )
        self.assertEqual(OperationLog.objects.filter(
            action_type="lifecycle_enforce_canary_applied"
        ).count(), 1)

    def test_activation_shared_entropy_and_runtime_applies_only_once(self):
        activated = self._activate()
        self.assertEqual(activated.outcome, "activated")
        self.assertRegex(activated.activation_id, r"^[0-9a-f]{64}$")
        ids = ",".join(map(str, self.event_ids))
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=self.raw_sha,
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=ids,
        ):
            from django.db import transaction
            with transaction.atomic():
                result = apply_race_lifecycle_decision(
                    event_id=self.event_ids[0], expected_generation=3,
                    now=self.race_times[0], mode="enforce",
                    expected_canary_sha256=self.raw_sha,
                    expected_canary_event_ids=ids,
                    expected_canary_activation_id=activated.activation_id,
                )
            self.assertEqual(result.action, "applied")
            with transaction.atomic():
                duplicate = apply_race_lifecycle_decision(
                    event_id=self.event_ids[0], expected_generation=3,
                    now=self.race_times[0], mode="enforce",
                    expected_canary_sha256=self.raw_sha,
                    expected_canary_event_ids=ids,
                    expected_canary_activation_id=activated.activation_id,
                )
            self.assertEqual(duplicate.action, "noop")
        self.events[0].refresh_from_db()
        self.assertEqual(self.events[0].status, "running")

    def test_schedule_generation_drift_fails_closed(self):
        activated = self._activate()
        control = RaceEventLifecycleControl.objects.get(event_id=self.event_ids[0])
        control.schedule_generation += 1
        control.save(update_fields=("schedule_generation", "updated_at"))
        ids = ",".join(map(str, self.event_ids))
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=self.raw_sha,
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=ids,
        ):
            from django.db import transaction
            with transaction.atomic():
                result = apply_race_lifecycle_decision(
                    event_id=self.event_ids[0], expected_generation=4,
                    now=self.race_times[0], mode="enforce",
                    expected_canary_sha256=self.raw_sha,
                    expected_canary_event_ids=ids,
                    expected_canary_activation_id=activated.activation_id,
                )
        self.assertEqual(result.action, "noop")
        self.assertEqual(result.reason_code, "canary_control_invalid")

    def test_global_enforce_keeps_out_of_cohort_shadow_control_in_shadow(self):
        activated = self._activate()
        now = self.generated_at + timedelta(hours=1)
        other = _make_event(
            slug="canary-outside-shadow",
            race_datetime=now,
            local_date=now.date(),
        )
        _make_control(
            other,
            mode="shadow",
            schedule_generation=1,
            next_refresh_at=now,
        )
        ids = ",".join(map(str, self.event_ids))
        dispatched: list[dict] = []
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=self.raw_sha,
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=ids,
        ), patch(
            "stable.tasks.timezone.now", return_value=now
        ), patch(
            "stable.tasks.advance_race_event_lifecycle_task.apply_async",
            side_effect=lambda **kwargs: dispatched.append(kwargs["kwargs"]),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                scan = scan_due_race_event_lifecycle_task()
            self.assertEqual(scan["claimed"], 1)
            self.assertEqual(len(dispatched), 1)
            result = advance_race_event_lifecycle_task(**dispatched[0])

        other.refresh_from_db()
        self.assertEqual(result["action"], "proposed")
        self.assertEqual(other.status, "scheduled")

    def test_global_enforce_scanner_never_claims_out_of_cohort_enforce_control(self):
        self._activate()
        now = self.generated_at + timedelta(hours=1)
        outside = _make_event(
            slug="canary-outside-enforce",
            race_datetime=now,
            local_date=now.date(),
        )
        outside_control = _make_control(
            outside,
            mode="enforce",
            schedule_generation=1,
            next_refresh_at=now,
        )
        ids = ",".join(map(str, self.event_ids))
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=self.raw_sha,
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=ids,
        ), patch("stable.tasks.timezone.now", return_value=now), patch(
            "stable.tasks.advance_race_event_lifecycle_task.apply_async"
        ) as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                result = scan_due_race_event_lifecycle_task()

        outside_control.refresh_from_db()
        self.assertEqual(result["claimed"], 0)
        self.assertEqual(outside_control.claim_token, "")
        self.assertEqual(outside_control.claim_generation, 0)
        dispatch.assert_not_called()

    def test_canary_can_be_disarmed_and_reactivated_after_legal_progress(self):
        activated = self._activate()
        ids = ",".join(map(str, self.event_ids))
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=self.raw_sha,
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=ids,
        ):
            from django.db import transaction
            with transaction.atomic():
                applied = apply_race_lifecycle_decision(
                    event_id=self.event_ids[0],
                    expected_generation=3,
                    now=self.race_times[0],
                    mode="enforce",
                    expected_canary_sha256=self.raw_sha,
                    expected_canary_event_ids=ids,
                    expected_canary_activation_id=activated.activation_id,
                )
        self.assertEqual(applied.action, "applied")

        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=False,
            RACE_EVENT_LIFECYCLE_MODE="off",
        ):
            disarmed = verify_or_mutate_canary(
                self.manifest, expected_state="inactive", disarm=True
            )
        self.assertEqual(disarmed.outcome, "disarmed")

        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=self.raw_sha,
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=ids,
        ):
            reactivated = verify_or_mutate_canary(
                self.manifest, expected_state="active", activate=True
            )
        self.assertEqual(reactivated.outcome, "activated")
        self.assertNotEqual(reactivated.activation_id, activated.activation_id)

    def test_expired_manifest_is_accepted_only_for_closed_runtime_disarm(self):
        self._activate()
        ids = ",".join(map(str, self.event_ids))

        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=False,
            RACE_EVENT_LIFECYCLE_MODE="off",
        ), patch(
            "sys.stdin", SimpleNamespace(buffer=BytesIO(self.raw))
        ), self.assertRaisesMessage(CommandError, "canary runtime 已过期"):
            call_command(
                "verify_race_event_lifecycle_enforce_canary",
                "--manifest-stdin",
                "--manifest-sha256",
                self.raw_sha,
                "--expected-commit",
                OID,
                "--expected-event-ids",
                ids,
                "--phase",
                "inactive",
            )

        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=False,
            RACE_EVENT_LIFECYCLE_MODE="off",
        ), patch(
            "sys.stdin", SimpleNamespace(buffer=BytesIO(self.raw))
        ):
            call_command(
                "verify_race_event_lifecycle_enforce_canary",
                "--manifest-stdin",
                "--manifest-sha256",
                self.raw_sha,
                "--expected-commit",
                OID,
                "--expected-event-ids",
                ids,
                "--phase",
                "inactive",
                "--disarm",
            )

        replay_stdout = StringIO()
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=False,
            RACE_EVENT_LIFECYCLE_MODE="off",
        ), patch(
            "sys.stdin", SimpleNamespace(buffer=BytesIO(self.raw))
        ):
            call_command(
                "verify_race_event_lifecycle_enforce_canary",
                "--manifest-stdin",
                "--manifest-sha256",
                self.raw_sha,
                "--expected-commit",
                OID,
                "--expected-event-ids",
                ids,
                "--phase",
                "inactive",
                "--disarm",
                stdout=replay_stdout,
            )
        self.assertIn("outcome=replay", replay_stdout.getvalue())

        controls = RaceEventLifecycleControl.objects.filter(
            event_id__in=self.event_ids
        ).order_by("event_id")
        self.assertEqual(
            [
                control.manifest_data["enforce_canary"]["activation_state"]
                for control in controls
            ],
            ["inactive", "inactive"],
        )

    def test_reactivation_rejects_status_changed_without_canary_transition(self):
        self._activate()
        event = self.events[0]
        event.status = "running"
        event.save(update_fields=("status", "updated_at"))

        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=False,
            RACE_EVENT_LIFECYCLE_MODE="off",
        ), self.assertRaises(CanaryError):
            verify_or_mutate_canary(
                self.manifest, expected_state="inactive", disarm=True
            )


class LifecycleEnforceCanaryCommandFlowTests(TestCase):
    def setUp(self):
        now = django_timezone.now()
        self.event_ids: list[int] = []
        for index, offset in enumerate((12, 14), start=1):
            race_at = now + timedelta(hours=offset)
            event = _make_event(
                slug=f"canary-command-{index}",
                race_datetime=race_at,
                local_date=race_at.date(),
            )
            control = _make_control(
                event,
                mode="shadow",
                schedule_generation=5,
                next_refresh_at=race_at,
            )
            control.enrollment_manifest_sha256 = ENROLLMENT_SHA
            control.manifest_data = {
                "schema_version": 2,
                "content_sha256": "f" * 64,
                "enrollment_schedule_hash": _schedule_hash(event),
                "allowed_us_zones": [],
            }
            control.save()
            self.event_ids.append(event.id)

    def _stdin(self, raw: bytes):
        return patch("sys.stdin", SimpleNamespace(buffer=BytesIO(raw)))

    def test_prepare_promote_verify_activate_commands_share_exact_stdin_contract(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "canary-artifact"
            stdout = StringIO()
            call_command(
                "prepare_race_event_lifecycle_enforce_canary",
                "--event-ids",
                *map(str, self.event_ids),
                "--approved-commit",
                OID,
                "--output-dir",
                str(output),
                stdout=stdout,
            )
            raw = (output / "manifest.json").read_bytes()

        raw_sha = hashlib.sha256(raw).hexdigest()
        ids = ",".join(map(str, self.event_ids))
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=False,
            RACE_EVENT_LIFECYCLE_MODE="off",
        ), self._stdin(raw):
            call_command(
                "promote_race_event_lifecycle_enforce_canary",
                "--manifest-stdin",
                "--manifest-sha256",
                raw_sha,
                "--expected-commit",
                OID,
                "--expected-event-ids",
                ids,
                "--apply",
                "--confirm-enforce-canary",
            )
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=False,
            RACE_EVENT_LIFECYCLE_MODE="off",
        ), self._stdin(raw):
            call_command(
                "verify_race_event_lifecycle_enforce_canary",
                "--manifest-stdin",
                "--manifest-sha256",
                raw_sha,
                "--expected-commit",
                OID,
                "--expected-event-ids",
                ids,
                "--phase",
                "inactive",
            )
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="enforce",
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=raw_sha,
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=ids,
        ), self._stdin(raw):
            call_command(
                "verify_race_event_lifecycle_enforce_canary",
                "--manifest-stdin",
                "--manifest-sha256",
                raw_sha,
                "--expected-commit",
                OID,
                "--expected-event-ids",
                ids,
                "--phase",
                "active",
                "--activate",
            )

        controls = RaceEventLifecycleControl.objects.filter(
            event_id__in=self.event_ids
        ).order_by("event_id")
        evidence = [control.manifest_data["enforce_canary"] for control in controls]
        self.assertEqual(evidence[0], evidence[1])
        self.assertEqual(evidence[0]["activation_state"], "active")
        self.assertRegex(evidence[0]["activation_id"], r"^[0-9a-f]{64}$")

    def test_promote_command_rejects_manifest_event_ids_before_any_write(self):
        raw = build_canary_artifact(
            event_ids=self.event_ids,
            approved_commit=OID,
        )
        raw_sha = hashlib.sha256(raw).hexdigest()
        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=False,
            RACE_EVENT_LIFECYCLE_MODE="off",
        ), self._stdin(raw), self.assertRaises(CommandError):
            call_command(
                "promote_race_event_lifecycle_enforce_canary",
                "--manifest-stdin",
                "--manifest-sha256",
                raw_sha,
                "--expected-commit",
                OID,
                "--expected-event-ids",
                "186,187",
                "--apply",
                "--confirm-enforce-canary",
            )
        self.assertEqual(
            list(
                RaceEventLifecycleControl.objects.filter(
                    event_id__in=self.event_ids
                ).values_list("mode", flat=True)
            ),
            ["shadow", "shadow"],
        )

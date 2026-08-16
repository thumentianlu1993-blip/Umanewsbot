"""Load-bearing RED tests for the lifecycle enforce canary boundary.

These tests deliberately exercise existing public seams.  They do not import a
not-yet-created canary module, so the initial RED is caused by unsafe current
behaviour (or a missing reviewed shell contract), not test collection failure.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from stable import models as stable_models
from stable.tasks import scan_due_race_event_lifecycle_task
from stable.test_race_event_lifecycle import _apply, _make_control, _make_event


ROOT = Path(__file__).resolve().parents[3]
MODE_SWITCH = ROOT / "deploy/switch_lifecycle_mode.sh"
CANARY_SHA = "a" * 64
ACTIVATION_ID = "b" * 64


def _active_canary_evidence(event_ids: list[int]) -> dict:
    return {
        "schema_version": 1,
        "raw_sha256": CANARY_SHA,
        "content_sha256": "c" * 64,
        "event_ids": event_ids,
        "approved_commit": "d" * 40,
        "runtime_valid_until": "2026-08-12T00:00:00+00:00",
        "activation_state": "active",
        "activation_id": ACTIVATION_ID,
        "activated_at": "2026-08-10T00:00:00+00:00",
    }


class LifecycleEnforceCanaryRuntimeRedTests(TestCase):
    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=True,
        RACE_EVENT_LIFECYCLE_MODE="enforce",
        RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=CANARY_SHA,
        RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS="9001,9002",
    )
    def test_out_of_scope_forged_enforce_cannot_update_public_status(self):
        """A self-consistent control is insufficient without env cohort trust."""
        race_at = datetime(2026, 8, 10, 2, 0, tzinfo=dt_timezone.utc)
        event = _make_event(slug="forged-out-of-scope", race_datetime=race_at)
        control = _make_control(event, mode="enforce", schedule_generation=4)
        control.manifest_data = {
            "enrollment_schedule_hash": "e" * 64,
            "enforce_canary": _active_canary_evidence([event.id, 9999]),
        }
        control.save(update_fields=("manifest_data", "updated_at"))

        result = _apply(
            event,
            expected_generation=4,
            now=race_at,
            mode="enforce",
        )

        event.refresh_from_db()
        self.assertEqual(result.action, "noop")
        self.assertEqual(result.reason_code, "canary_event_out_of_scope")
        self.assertEqual(event.status, "scheduled")
        self.assertFalse(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event,
                record_kind=stable_models.RaceEventLifecycleTransitionKind.APPLIED,
            ).exists()
        )

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=True,
        RACE_EVENT_LIFECYCLE_MODE="enforce",
        RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=CANARY_SHA,
    )
    def test_inactive_two_event_canary_is_not_claimed_by_scanner(self):
        """Web/worker enforce before atomic activation must remain write inert."""
        now = datetime(2026, 8, 10, 3, 0, tzinfo=dt_timezone.utc)
        events = [
            _make_event(
                slug=f"inactive-canary-{index}",
                race_datetime=now - timedelta(minutes=1),
            )
            for index in range(2)
        ]
        event_ids = [event.id for event in events]
        inactive = _active_canary_evidence(event_ids)
        inactive.update(
            activation_state="inactive",
            activation_id="",
            activated_at=None,
        )
        for event in events:
            control = _make_control(
                event,
                mode="enforce",
                next_refresh_at=now - timedelta(seconds=1),
            )
            control.manifest_data = {"enforce_canary": inactive}
            control.save(update_fields=("manifest_data", "updated_at"))

        with override_settings(
            RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=",".join(
                str(event_id) for event_id in event_ids
            )
        ), patch(
            "stable.tasks.timezone.now", return_value=now
        ), patch(
            "stable.tasks.advance_race_event_lifecycle_task.apply_async"
        ) as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                result = scan_due_race_event_lifecycle_task()

        self.assertEqual(result["claimed"], 0)
        self.assertEqual(result["dispatched"], 0)
        dispatch.assert_not_called()
        self.assertFalse(
            stable_models.RaceEventLifecycleControl.objects.filter(
                event_id__in=event_ids,
                claim_token__gt="",
            ).exists()
        )


class LifecycleEnforceCanaryModeSwitchRedTests(SimpleTestCase):
    def test_true_enforce_requires_independent_manifest_trust_and_staged_order(self):
        source = MODE_SWITCH.read_text(encoding="utf-8")

        self.assertIn("true/enforce", source)
        self.assertIn("EXPECTED_CANARY_EVENT_IDS", source)
        self.assertIn("RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256", source)
        self.assertIn("RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS", source)
        self.assertIn("--manifest-stdin", source)

        # The success path must not recreate web and worker together: web is
        # the bounded-stdin verifier before worker and activation are allowed.
        enable_path = source[source.index('if [ "$TARGET_LIFECYCLE_ENABLED" = "true" ]'):]
        web_only = enable_path.index(
            "compose_mutation up -d --no-deps --force-recreate web\n"
        )
        db_verify = enable_path.index("--manifest-stdin", web_only)
        worker_only = enable_path.index(
            "compose_mutation up -d --no-deps --force-recreate worker\n",
            db_verify,
        )
        activation = enable_path.index("activate", worker_only)
        beat = enable_path.index(
            "compose_mutation up -d --no-deps --force-recreate beat",
            activation,
        )
        self.assertLess(web_only, db_verify)
        self.assertLess(db_verify, worker_only)
        self.assertLess(worker_only, activation)
        self.assertLess(activation, beat)

    def test_false_off_recovery_clears_both_canary_trust_root_keys(self):
        source = MODE_SWITCH.read_text(encoding="utf-8")
        recovery = source[source.index("recover_off() {"):source.index("on_exit() {")]

        self.assertIn('rewrite_env_off "$CANONICAL_ENV_FILE"', recovery)
        self.assertIn('rewrite_env_off "$ACTIVE_RELEASE_ENV_FILE"', recovery)
        self.assertIn(
            'rewrite_env "$1" false off "" "" "" "" "" ""',
            recovery,
            "false/off helper must clear both legacy values and all four registry values",
        )
        for key in (
            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256",
            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS",
            "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256",
            "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256",
            "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT",
            "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID",
        ):
            self.assertIn(key, source)

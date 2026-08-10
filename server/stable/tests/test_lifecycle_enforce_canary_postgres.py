"""PostgreSQL concurrency proof for global canary promotion serialization."""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta, timezone

from django.db import connection, connections
from django.test import TransactionTestCase, override_settings

from stable.models import RaceEventLifecycleControl
from stable.services.race_event_lifecycle_canary import (
    CanaryError,
    build_canary_artifact,
    load_canary_manifest_bytes,
    promote_canary,
)
from stable.services.race_event_lifecycle_enrollment import _schedule_hash
from stable.test_race_event_lifecycle import _make_control, _make_event


class LifecycleEnforceCanaryPostgresTests(TransactionTestCase):
    reset_sequences = True

    def _manifest(self, *, prefix: str, hour: int):
        generated_at = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
        event_ids: list[int] = []
        for index in range(2):
            race_at = generated_at + timedelta(hours=hour + index)
            event = _make_event(
                slug=f"{prefix}-{index}",
                race_datetime=race_at,
                local_date=race_at.date(),
            )
            control = _make_control(
                event,
                mode="shadow",
                schedule_generation=3,
                next_refresh_at=race_at,
            )
            control.enrollment_manifest_sha256 = "e" * 64
            control.manifest_data = {
                "schema_version": 2,
                "content_sha256": "f" * 64,
                "enrollment_schedule_hash": _schedule_hash(event),
                "allowed_us_zones": [],
            }
            control.save()
            event_ids.append(event.id)
        raw = build_canary_artifact(
            event_ids=event_ids,
            approved_commit="d" * 40,
            now=generated_at,
        )
        return load_canary_manifest_bytes(
            raw,
            expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
            expected_commit="d" * 40,
            now=generated_at,
            require_apply_fresh=True,
        )

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_different_cohorts_cannot_both_promote(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL")

        manifests = (
            self._manifest(prefix="canary-pg-a", hour=12),
            self._manifest(prefix="canary-pg-b", hour=16),
        )
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        errors: list[str] = []

        def worker(manifest):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                result = promote_canary(manifest, apply=True)
                outcomes.append(result.outcome)
            except CanaryError as exc:
                errors.append(str(exc))
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=worker, args=(manifest,))
            for manifest in manifests
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(outcomes, ["applied"])
        self.assertEqual(len(errors), 1)
        self.assertIn("范围外 enforce control", errors[0])
        self.assertEqual(
            RaceEventLifecycleControl.objects.filter(mode="enforce").count(),
            2,
        )

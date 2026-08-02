"""PostgreSQL-only concurrency contract for lifecycle enrollment.

SQLite execution must skip this test.  It cannot provide evidence for the
row-lock ordering and cross-connection visibility used by atomic v2 apply.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.db import connection, connections
from django.test import TransactionTestCase
from django.utils import timezone as django_timezone

from stable.models import RaceEvent, RaceEventLifecycleControl
from stable.services.race_event_lifecycle_enrollment import (
    EnrollmentError,
    apply_enrollment,
    build_enrollment_artifacts,
    load_enrollment_manifest,
)


APPROVED_COMMIT = "a" * 40


def _pg_only(test_method):
    def wrapper(self, *args, **kwargs):
        if connection.vendor != "postgresql":
            self.skipTest("requires isolated PostgreSQL")
        return test_method(self, *args, **kwargs)

    return wrapper


def _close_thread_connections() -> None:
    connections.close_all()


def _make_event(*, slug: str) -> RaceEvent:
    return RaceEvent.objects.create(
        year=2026,
        slug=slug,
        original_name="PG Enrollment Test",
        chinese_name="PG 纳管测试",
        country_region="japan",
        racecourse="Test",
        grade_text="G1",
        normalized_grade="G1",
        surface="turf",
        status="scheduled",
        priority="P0",
        visibility_status="published",
        timezone_name="Asia/Tokyo",
        local_date=django_timezone.localdate() + timedelta(days=1),
    )


class RaceEventLifecycleEnrollmentPostgresTests(TransactionTestCase):
    @_pg_only
    def test_two_concurrent_applies_create_one_complete_control_set(self):
        first = _make_event(slug="pg-enrollment-first")
        second = _make_event(slug="pg-enrollment-second")
        generated_at = django_timezone.now()
        manifest_bytes, _ = build_enrollment_artifacts(
            event_ids=[second.pk, first.pk],
            approved_commit=APPROVED_COMMIT,
            now=generated_at,
        )
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_bytes(manifest_bytes)
            raw_sha = hashlib.sha256(manifest_bytes).hexdigest()
            manifest = load_enrollment_manifest(
                manifest_path,
                expected_raw_sha256=raw_sha,
                expected_commit=APPROVED_COMMIT,
                now=generated_at,
            )

            barrier = threading.Barrier(2)
            outcomes: list[dict[int, str]] = []
            controlled_conflicts: list[str] = []
            unexpected_errors: list[str] = []

            def apply_worker() -> None:
                _close_thread_connections()
                try:
                    barrier.wait(timeout=10)
                    result = apply_enrollment(manifest)
                    outcomes.append(dict(result.outcomes))
                except EnrollmentError as exc:
                    message = str(exc)
                    if "control" in message or "冲突" in message:
                        controlled_conflicts.append(message)
                    else:
                        unexpected_errors.append(
                            f"{type(exc).__name__}: {message}"
                        )
                except Exception as exc:  # pragma: no cover - evidence path
                    unexpected_errors.append(
                        f"{type(exc).__name__}: {exc}"
                    )
                finally:
                    _close_thread_connections()

            first_thread = threading.Thread(target=apply_worker)
            second_thread = threading.Thread(target=apply_worker)
            first_thread.start()
            second_thread.start()
            first_thread.join(timeout=15)
            second_thread.join(timeout=15)

            self.assertFalse(first_thread.is_alive(), "first apply deadlocked")
            self.assertFalse(second_thread.is_alive(), "second apply deadlocked")
            self.assertEqual(
                unexpected_errors, [], f"unexpected thread errors: {unexpected_errors}"
            )
            self.assertEqual(
                len(outcomes) + len(controlled_conflicts),
                2,
                f"missing apply result: outcomes={outcomes} "
                f"controlled_conflicts={controlled_conflicts}",
            )
            self.assertTrue(
                any(
                    set(result.values()) == {"would_create"}
                    for result in outcomes
                ),
                f"neither apply created the batch: {outcomes}",
            )
            if len(outcomes) == 2:
                self.assertTrue(
                    any(set(result.values()) == {"replay"} for result in outcomes),
                    f"second successful apply was not replay: {outcomes}",
                )

        _close_thread_connections()
        controls = list(
            RaceEventLifecycleControl.objects.order_by("event_id").values(
                "event_id",
                "mode",
                "schedule_generation",
                "enrollment_manifest_sha256",
            )
        )
        self.assertEqual(
            controls,
            [
                {
                    "event_id": first.pk,
                    "mode": "shadow",
                    "schedule_generation": 1,
                    "enrollment_manifest_sha256": raw_sha,
                },
                {
                    "event_id": second.pk,
                    "mode": "shadow",
                    "schedule_generation": 1,
                    "enrollment_manifest_sha256": raw_sha,
                },
            ],
        )

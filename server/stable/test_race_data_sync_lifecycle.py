from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.test import TestCase, override_settings

from stable import models
from stable.services.race_data_sync_lifecycle import (
    advance_due_data_sync_lifecycle,
    decide_data_sync_lifecycle,
)
from stable.tasks import advance_race_data_sync_lifecycle_task


NOW = datetime(2026, 8, 28, 4, 0, tzinfo=dt_timezone.utc)
SHA = "a" * 64


class RaceDataSyncLifecycleTests(TestCase):
    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="data-sync-lifecycle",
            original_name="Data Sync Lifecycle",
            chinese_name="赛事同步生命周期",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW + timedelta(minutes=1),
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.SCHEDULED,
        )
        models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
            owner_generation=1,
        )
        models.RaceEventLiveTracking.objects.create(
            event=self.event,
            tracking_enabled=True,
        )
        source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the-racing-api-v1",
            external_race_id="jp-20260828-11",
        )
        models.RaceDataSyncEnrollment.objects.create(
            event=self.event,
            source_identity=source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest=SHA,
            route_digest=SHA,
            event_snapshot_sha256=SHA,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256=SHA,
            entry_sha256=SHA,
        )
        self.lifecycle = models.RaceEventLifecycleControl.objects.create(
            event=self.event,
            mode=models.RaceEventLifecycleMode.ENFORCE,
            schedule_generation=1,
            next_refresh_at=self.event.race_datetime,
        )

    def test_time_rules_move_scheduled_to_running_then_finished(self):
        first = advance_due_data_sync_lifecycle(
            now=NOW + timedelta(minutes=1),
            batch_size=10,
        )
        self.assertEqual(first["transitioned"], 1)
        self.event.refresh_from_db()
        self.lifecycle.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.RUNNING)
        self.assertEqual(
            self.lifecycle.next_refresh_at,
            self.event.race_datetime + timedelta(minutes=30),
        )

        second = advance_due_data_sync_lifecycle(
            now=NOW + timedelta(minutes=31),
            batch_size=10,
        )
        self.assertEqual(second["transitioned"], 1)
        self.event.refresh_from_db()
        self.lifecycle.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.FINISHED)
        self.assertIsNone(self.lifecycle.next_refresh_at)
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertEqual(tracking.state, models.RaceEventLiveState.AWAITING_RESULT)
        self.assertEqual(
            list(
                models.RaceEventLifecycleTransition.objects.filter(
                    event=self.event
                ).values_list("to_status", flat=True)
            ),
            [models.RaceEventStatus.RUNNING, models.RaceEventStatus.FINISHED],
        )

    def test_dry_run_is_zero_write(self):
        result = advance_due_data_sync_lifecycle(
            now=NOW + timedelta(minutes=1),
            batch_size=10,
            dry_run=True,
        )
        self.assertEqual(result["transitioned"], 1)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, models.RaceEventStatus.SCHEDULED)
        self.assertFalse(models.RaceEventLifecycleTransition.objects.exists())

    def test_postponed_event_is_rechecked_without_forced_transition(self):
        self.event.status = models.RaceEventStatus.POSTPONED
        self.event.save(update_fields=("status",))
        decision = decide_data_sync_lifecycle(
            event=self.event,
            now=NOW + timedelta(days=1),
        )
        self.assertEqual(decision.reason_code, "postponed_awaiting_schedule")
        self.assertEqual(decision.next_refresh_at, NOW + timedelta(days=1, hours=12))

    @override_settings(
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
        RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
        RACE_DATA_SYNC_SELECTOR_BATCH_SIZE=10,
    )
    def test_celery_entrypoint_is_controlled_by_data_sync_flags(self):
        self.lifecycle.next_refresh_at = NOW
        self.lifecycle.save(update_fields=("next_refresh_at",))
        result = advance_race_data_sync_lifecycle_task()
        self.assertTrue(result["enabled"])
        self.assertEqual(result["status"], "complete")

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase

from stable import models
from stable.services.race_data_sync_alerts import (
    monitor_data_sync_result_slo,
    stage_data_sync_result_overdue_alert,
)
from stable.tasks import deliver_race_live_alert_task


NOW = datetime(2026, 8, 28, 8, 0, tzinfo=dt_timezone.utc)


class RaceDataSyncResultSloAlertTests(TestCase):
    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="data-sync-t30",
            original_name="T30 Cup",
            chinese_name="T30杯",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW,
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.RUNNING,
        )
        source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            external_race_id="t30-race",
        )
        models.RaceDataSyncEnrollment.objects.create(
            event=self.event,
            source_identity=source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest="a" * 64,
            route_digest="b" * 64,
            event_snapshot_sha256="c" * 64,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256="d" * 64,
            entry_sha256="e" * 64,
            effective_at=NOW,
        )

    def test_alert_is_not_staged_before_t30(self):
        incident_id = stage_data_sync_result_overdue_alert(
            event_id=self.event.pk,
            now=NOW + timedelta(minutes=29, seconds=59),
            reason_code="result_not_found",
        )

        self.assertIsNone(incident_id)
        self.assertFalse(models.RaceLiveAlertIncident.objects.exists())

    def test_monitor_stages_one_deduplicated_non_dispatching_incident(self):
        first = monitor_data_sync_result_slo(
            now=NOW + timedelta(minutes=30)
        )
        second = monitor_data_sync_result_slo(
            now=NOW + timedelta(minutes=31)
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(second, ())
        incident = models.RaceLiveAlertIncident.objects.get(pk=first[0])
        self.assertEqual(incident.scope_type, "data_sync_event")
        self.assertEqual(
            incident.alert_type,
            models.RaceLiveAlertType.PROVISIONAL_OVERDUE,
        )
        self.assertEqual(incident.status, models.RaceLiveAlertIncidentStatus.OPEN)
        self.assertIsNone(incident.next_attempt_at)
        self.assertEqual(incident.delivery_attempts, 0)
        self.assertEqual(models.RaceLiveAlertIncident.objects.count(), 1)

        delivery = deliver_race_live_alert_task.run(incident.pk)
        incident.refresh_from_db()
        self.assertFalse(delivery["delivered"])
        self.assertEqual(
            delivery["reason"], "data_sync_incident_non_dispatching"
        )
        self.assertEqual(incident.status, models.RaceLiveAlertIncidentStatus.OPEN)
        self.assertEqual(incident.delivery_attempts, 0)

    def test_existing_open_incident_does_not_starve_later_overdue_event(self):
        later = models.RaceEvent.objects.create(
            year=2026,
            slug="data-sync-t31",
            original_name="T31 Cup",
            chinese_name="T31杯",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G2",
            normalized_grade=models.RaceGrade.G2,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW + timedelta(minutes=1),
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.RUNNING,
        )
        source = models.RaceResultSourceIdentity.objects.create(
            event=later,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            external_race_id="t31-race",
        )
        models.RaceDataSyncEnrollment.objects.create(
            event=later,
            source_identity=source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest="a" * 64,
            route_digest="b" * 64,
            event_snapshot_sha256="c" * 64,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256="d" * 64,
            entry_sha256="f" * 64,
            effective_at=NOW,
        )

        first = monitor_data_sync_result_slo(
            now=NOW + timedelta(minutes=31), batch_size=1
        )
        second = monitor_data_sync_result_slo(
            now=NOW + timedelta(minutes=31), batch_size=1
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first, second)
        self.assertEqual(
            set(
                models.RaceLiveAlertIncident.objects.values_list(
                    "scope_key", flat=True
                )
            ),
            {str(self.event.pk), str(later.pk)},
        )

    def test_cancelled_and_postponed_events_do_not_stage(self):
        for status in (
            models.RaceEventStatus.CANCELLED,
            models.RaceEventStatus.POSTPONED,
        ):
            with self.subTest(status=status):
                self.event.status = status
                self.event.save(update_fields=("status", "updated_at"))
                self.assertEqual(
                    monitor_data_sync_result_slo(
                        now=NOW + timedelta(minutes=30)
                    ),
                    (),
                )
                self.assertFalse(models.RaceLiveAlertIncident.objects.exists())

    def test_confirmed_result_resolves_existing_incident(self):
        incident_ids = monitor_data_sync_result_slo(
            now=NOW + timedelta(minutes=30)
        )
        self.assertEqual(len(incident_ids), 1)
        self.event.result_confirmed_at = NOW + timedelta(minutes=31)
        self.event.status = models.RaceEventStatus.FINISHED
        self.event.save(
            update_fields=("result_confirmed_at", "status", "updated_at")
        )

        self.assertEqual(
            monitor_data_sync_result_slo(now=NOW + timedelta(minutes=31)),
            (),
        )
        incident = models.RaceLiveAlertIncident.objects.get(pk=incident_ids[0])
        self.assertEqual(
            incident.status, models.RaceLiveAlertIncidentStatus.RESOLVED
        )
        self.assertEqual(incident.resolved_at, NOW + timedelta(minutes=31))

    def test_confirmed_result_does_not_stage(self):
        self.event.result_confirmed_at = NOW + timedelta(minutes=20)
        self.event.save(update_fields=("result_confirmed_at", "updated_at"))

        incident_ids = monitor_data_sync_result_slo(
            now=NOW + timedelta(minutes=30)
        )

        self.assertEqual(incident_ids, ())

    def test_resolved_event_without_active_incident_is_not_rescanned(self):
        self.event.result_confirmed_at = NOW + timedelta(minutes=20)
        self.event.status = models.RaceEventStatus.FINISHED
        self.event.save(
            update_fields=("result_confirmed_at", "status", "updated_at")
        )

        with patch(
            "stable.services.race_data_sync_alerts._resolve_data_sync_event_incidents"
        ) as resolver:
            incident_ids = monitor_data_sync_result_slo(
                now=NOW + timedelta(minutes=30), batch_size=1
            )

        self.assertEqual(incident_ids, ())
        resolver.assert_not_called()

    def test_unresolved_older_incident_does_not_starve_resolved_incident(self):
        older_incident_id = monitor_data_sync_result_slo(
            now=NOW + timedelta(minutes=30), batch_size=1
        )[0]
        resolved_event = models.RaceEvent.objects.create(
            year=2026,
            slug="data-sync-resolved-later",
            original_name="Resolved Later Cup",
            chinese_name="稍后恢复杯",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G2",
            normalized_grade=models.RaceGrade.G2,
            surface=models.RaceEventSurface.TURF,
            race_datetime=NOW,
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 8, 28),
            status=models.RaceEventStatus.FINISHED,
            result_confirmed_at=NOW + timedelta(minutes=31),
        )
        source = models.RaceResultSourceIdentity.objects.create(
            event=resolved_event,
            source_key="the_racing_api",
            region_code="japan_jra",
            identity_namespace="the_racing_api-race-v1",
            external_race_id="resolved-later-race",
        )
        models.RaceDataSyncEnrollment.objects.create(
            event=resolved_event,
            source_identity=source,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest="a" * 64,
            route_digest="b" * 64,
            event_snapshot_sha256="c" * 64,
            projection_owner_generation=1,
            enrollment_generation=1,
            manifest_sha256="d" * 64,
            entry_sha256="f" * 64,
            effective_at=NOW,
        )
        resolved_incident = models.RaceLiveAlertIncident.objects.create(
            dedupe_key="f" * 64,
            alert_type=models.RaceLiveAlertType.PROVISIONAL_OVERDUE,
            scope_type="data_sync_event",
            scope_key=str(resolved_event.pk),
            reference_version="data-sync-t30:resolved-later",
            status=models.RaceLiveAlertIncidentStatus.OPEN,
            deadline_at=NOW + timedelta(minutes=30),
            opened_at=NOW + timedelta(minutes=30),
            last_seen_at=NOW + timedelta(minutes=30),
            details={"event_id": resolved_event.pk},
        )

        self.assertEqual(
            monitor_data_sync_result_slo(
                now=NOW + timedelta(minutes=31), batch_size=1
            ),
            (),
        )

        self.assertEqual(
            models.RaceLiveAlertIncident.objects.get(pk=older_incident_id).status,
            models.RaceLiveAlertIncidentStatus.OPEN,
        )
        resolved_incident.refresh_from_db()
        self.assertEqual(
            resolved_incident.status,
            models.RaceLiveAlertIncidentStatus.RESOLVED,
        )

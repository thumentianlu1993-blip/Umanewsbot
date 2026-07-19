from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from stable import models
from stable import tasks
from stable.services import race_events


class RaceLiveAlertIncidentSchemaTests(SimpleTestCase):
    def _model(self):
        model = getattr(models, "RaceLiveAlertIncident", None)
        self.assertIsNotNone(
            model,
            "RaceLiveAlertIncident 持久告警模型尚未实现",
        )
        return model

    def test_alert_incident_records_scope_dedupe_and_delivery_lease(self):
        model = self._model()
        fields = {field.name: field for field in model._meta.get_fields()}
        required = {
            "alert_type",
            "scope_type",
            "scope_key",
            "reference_version",
            "dedupe_key",
            "status",
            "deadline_at",
            "opened_at",
            "resolved_at",
            "last_seen_at",
            "next_attempt_at",
            "delivery_attempts",
            "delivery_token",
            "delivery_lease_expires_at",
            "alert_sent_at",
            "last_error_code",
            "details",
        }
        self.assertTrue(required.issubset(fields))
        self.assertTrue(fields["dedupe_key"].unique)

    def test_alert_types_cover_all_predeployment_sla_failures(self):
        alert_type = getattr(models, "RaceLiveAlertType", None)
        self.assertIsNotNone(
            alert_type,
            "RaceLiveAlertType choices 尚未实现",
        )
        self.assertTrue(
            {
                "provisional_overdue",
                "official_overdue",
                "source_failures",
                "pagination_overflow",
                "host_circuit",
                "queue_age",
            }.issubset(set(alert_type.values))
        )


class RaceLiveSlaMonitorTaskContractTests(SimpleTestCase):
    def test_monitor_is_default_off_and_has_a_once_per_minute_beat_entry(self):
        self.assertTrue(
            hasattr(settings, "RACE_LIVE_MONITOR_ENABLED"),
            "RACE_LIVE_MONITOR_ENABLED 设置尚未实现",
        )
        self.assertIs(settings.RACE_LIVE_MONITOR_ENABLED, False)
        schedule = settings.CELERY_BEAT_SCHEDULE.get("monitor-race-live-sla")
        self.assertIsNotNone(schedule)
        self.assertEqual(
            schedule["task"],
            "stable.tasks.monitor_race_live_sla_task",
        )
        self.assertEqual(schedule["schedule"].minute, set(range(60)))

    def test_monitor_is_a_separate_task(self):
        self.assertTrue(
            callable(getattr(tasks, "monitor_race_live_sla_task", None)),
            "SLA monitor task 尚未实现",
        )

    def test_delivery_is_a_separate_task(self):
        self.assertTrue(
            callable(getattr(tasks, "deliver_race_live_alert_task", None)),
            "SLA alert delivery task 尚未实现",
        )

    def test_delivery_has_an_explicit_lease_claim_service(self):
        self.assertTrue(
            callable(
                getattr(
                    race_events,
                    "claim_race_live_alert_delivery",
                    None,
                )
            ),
            "alert delivery lease claim 尚未实现",
        )

    def test_delivery_has_an_explicit_token_cas_completion_service(self):
        self.assertTrue(
            callable(
                getattr(
                    race_events,
                    "complete_race_live_alert_delivery",
                    None,
                )
            ),
            "alert delivery token/CAS completion 尚未实现",
        )

    def test_failed_delivery_retry_schedule_is_one_five_fifteen_minutes(self):
        delay = getattr(
            race_events,
            "calculate_race_live_alert_retry_delay",
            None,
        )
        self.assertTrue(
            callable(delay),
            "alert delivery retry planner 尚未实现",
        )
        self.assertEqual(delay(attempt_number=1), timedelta(minutes=1))
        self.assertEqual(delay(attempt_number=2), timedelta(minutes=5))
        self.assertEqual(delay(attempt_number=3), timedelta(minutes=15))
        self.assertIsNone(delay(attempt_number=4))


class RaceLiveAlertDeliveryLeaseBehaviorTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def test_expired_lease_can_be_reclaimed_and_old_token_cannot_complete(self):
        incident = models.RaceLiveAlertIncident.objects.create(
            alert_type=models.RaceLiveAlertType.PROVISIONAL_OVERDUE,
            scope_type="event",
            scope_key="100",
            reference_version="tracking-v1",
            dedupe_key="a" * 64,
            status=models.RaceLiveAlertIncidentStatus.OPEN,
            opened_at=self.NOW,
            last_seen_at=self.NOW,
            next_attempt_at=self.NOW,
        )

        first = race_events.claim_race_live_alert_delivery(
            incident_id=incident.pk,
            now=self.NOW,
            lease_seconds=120,
        )
        second = race_events.claim_race_live_alert_delivery(
            incident_id=incident.pk,
            now=self.NOW + timedelta(seconds=121),
            lease_seconds=120,
        )
        stale = race_events.complete_race_live_alert_delivery(
            incident_id=incident.pk,
            delivery_token=first.delivery_token,
            now=self.NOW + timedelta(seconds=122),
            delivered=True,
        )
        current = race_events.complete_race_live_alert_delivery(
            incident_id=incident.pk,
            delivery_token=second.delivery_token,
            now=self.NOW + timedelta(seconds=122),
            delivered=True,
        )

        self.assertIs(first.claimed, True)
        self.assertIs(second.claimed, True)
        self.assertNotEqual(first.delivery_token, second.delivery_token)
        self.assertIs(stale.applied, False)
        self.assertEqual(stale.reason, "delivery_token_mismatch")
        self.assertIs(current.applied, True)
        incident.refresh_from_db()
        self.assertEqual(
            incident.status,
            models.RaceLiveAlertIncidentStatus.SENT,
        )
        self.assertEqual(incident.delivery_attempts, 2)


class RaceLiveSlaIncidentBehaviorTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def _tracking(self, *, slug: str, **overrides):
        event = models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=slug,
            chinese_name=slug,
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=self.NOW + timedelta(hours=1),
        )
        values = {
            "event": event,
            "tracking_enabled": True,
            "state": models.RaceEventLiveState.SCHEDULED,
            "next_poll_at": self.NOW + timedelta(minutes=1),
        }
        values.update(overrides)
        return models.RaceEventLiveTracking.objects.create(**values)

    def test_provisional_overdue_dedupes_across_unrelated_lock_versions(self):
        tracking = self._tracking(
            slug="sla-provisional-dedupe",
            state=models.RaceEventLiveState.AWAITING_RESULT,
        )
        tracking.event.race_datetime = self.NOW - timedelta(minutes=20)
        tracking.event.save(update_fields=("race_datetime", "updated_at"))

        first = race_events.stage_race_live_sla_alerts(
            now=self.NOW,
            enabled_regions=(models.RacingRegion.JAPAN,),
        )
        models.RaceLiveAlertIncident.objects.filter(pk=first[0]).update(
            status=models.RaceLiveAlertIncidentStatus.SENT,
        )
        tracking.lock_version += 1
        tracking.save(update_fields=("lock_version", "updated_at"))
        second = race_events.stage_race_live_sla_alerts(
            now=self.NOW + timedelta(minutes=1),
            enabled_regions=(models.RacingRegion.JAPAN,),
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(
            models.RaceLiveAlertIncident.objects.get(
                pk=first[0]
            ).details["event_name"],
            tracking.event.chinese_name,
        )
        self.assertEqual(second, ())
        self.assertEqual(
            models.RaceLiveAlertIncident.objects.filter(
                alert_type=models.RaceLiveAlertType.PROVISIONAL_OVERDUE,
            ).count(),
            1,
        )

    def test_source_failure_dedupes_one_failure_episode(self):
        tracking = self._tracking(
            slug="sla-source-failure-dedupe",
            consecutive_failures=3,
            last_success_at=self.NOW - timedelta(minutes=10),
        )

        first = race_events.stage_race_live_sla_alerts(
            now=self.NOW,
            enabled_regions=(models.RacingRegion.JAPAN,),
        )
        models.RaceLiveAlertIncident.objects.filter(pk=first[0]).update(
            status=models.RaceLiveAlertIncidentStatus.SENT,
        )
        tracking.consecutive_failures = 4
        tracking.lock_version += 1
        tracking.save(
            update_fields=(
                "consecutive_failures",
                "lock_version",
                "updated_at",
            )
        )
        second = race_events.stage_race_live_sla_alerts(
            now=self.NOW + timedelta(minutes=1),
            enabled_regions=(models.RacingRegion.JAPAN,),
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(second, ())
        self.assertEqual(
            models.RaceLiveAlertIncident.objects.filter(
                alert_type=models.RaceLiveAlertType.SOURCE_FAILURES,
            ).count(),
            1,
        )

    def test_queue_age_alerts_due_unclaimed_rows_not_active_claims(self):
        due = self._tracking(
            slug="sla-queue-due",
            next_poll_at=self.NOW - timedelta(minutes=4),
            last_attempt_at=self.NOW - timedelta(minutes=10),
        )
        active = self._tracking(
            slug="sla-queue-active",
            next_poll_at=self.NOW - timedelta(minutes=4),
            last_attempt_at=self.NOW - timedelta(minutes=10),
            active_attempt_token="active-token",
            claim_generation=2,
            claim_expires_at=self.NOW + timedelta(minutes=1),
        )

        staged = race_events.stage_race_live_sla_alerts(
            now=self.NOW,
            enabled_regions=(models.RacingRegion.JAPAN,),
        )

        self.assertEqual(len(staged), 1)
        incident = models.RaceLiveAlertIncident.objects.get(pk=staged[0])
        self.assertEqual(
            incident.alert_type,
            models.RaceLiveAlertType.QUEUE_AGE,
        )
        self.assertEqual(incident.scope_key, str(due.event_id))
        self.assertNotEqual(incident.scope_key, str(active.event_id))

    @override_settings(
        RACE_LIVE_ALERT_NOTIFY_EMAILS=("754652181@qq.com",),
        DEFAULT_FROM_EMAIL="alerts@example.test",
    )
    def test_delivery_uses_five_minute_lease_and_dynamic_event_context(self):
        incident = models.RaceLiveAlertIncident.objects.create(
            alert_type=models.RaceLiveAlertType.OFFICIAL_OVERDUE,
            scope_type="event",
            scope_key="123",
            reference_version="official:1:jra-v1",
            dedupe_key="b" * 64,
            status=models.RaceLiveAlertIncidentStatus.OPEN,
            opened_at=self.NOW,
            last_seen_at=self.NOW,
            details={
                "region": models.RacingRegion.JAPAN,
                "event_id": 123,
                "event_name": "日本G1验收赛",
                "official_route": "jra_manual_verification",
            },
        )

        with (
            patch(
                "stable.tasks.timezone.now",
                return_value=self.NOW,
            ),
            patch(
                "stable.tasks.claim_race_live_alert_delivery",
                wraps=race_events.claim_race_live_alert_delivery,
            ) as claim,
            patch("stable.tasks.send_mail", return_value=1) as send_mail,
        ):
            result = tasks.deliver_race_live_alert_task.run(incident.pk)

        claim.assert_called_once_with(
            incident_id=incident.pk,
            now=self.NOW,
            lease_seconds=300,
        )
        subject, body = send_mail.call_args.args[:2]
        rendered = f"{subject}\n{body}"
        for expected in (
            "123",
            "日本G1验收赛",
            models.RacingRegion.JAPAN,
            "jra_manual_verification",
            str(incident.pk),
        ):
            self.assertIn(expected, rendered)
        self.assertIs(result["delivered"], True)

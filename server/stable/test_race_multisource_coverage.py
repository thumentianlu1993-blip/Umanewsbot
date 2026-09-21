from datetime import timedelta
from django.test import TestCase, override_settings
from stable import models
from stable import test_race_multisource_identity as fixtures
from stable.services.race_data_sync_enrollment import build_multisource_coverage
from stable.services.race_data_sync_alerts import stage_multisource_coverage_incidents


@override_settings(RACE_DATA_COVERAGE_ALERTS_ENABLED=True)
class CoverageTests(TestCase):
    def setUp(self):
        fixtures.IdentityTests.setUp(self)

    def test_unenrolled_overdue_alert_dedup_and_outside_window_persistence(self):
        self.event.race_datetime = fixtures.NOW - timedelta(hours=1)
        self.event.save()
        for _ in range(2):
            coverage = build_multisource_coverage(now=fixtures.NOW, policy=self.policy)
            self.assertEqual(coverage["counts"], {"enrollment_missing": 1})
            self.assertEqual(sum(coverage["counts"].values()), coverage["total"])
            stage_multisource_coverage_incidents(
                coverage=coverage, policy=self.policy, now=fixtures.NOW
            )
        self.assertEqual(models.RaceLiveAlertIncident.objects.count(), 1)
        later = fixtures.NOW + timedelta(days=8)
        coverage = build_multisource_coverage(now=later, policy=self.policy)
        self.assertEqual(coverage["total"], 0)
        stage_multisource_coverage_incidents(
            coverage=coverage, policy=self.policy, now=later
        )
        self.assertNotEqual(
            models.RaceLiveAlertIncident.objects.get().status, "resolved"
        )
        self.event.result_confirmed_at = fixtures.NOW
        self.event.save()
        stage_multisource_coverage_incidents(
            coverage=build_multisource_coverage(now=fixtures.NOW, policy=self.policy),
            policy=self.policy,
            now=fixtures.NOW,
        )
        self.assertEqual(models.RaceLiveAlertIncident.objects.get().status, "resolved")

    def test_unknown_date_classification_and_cancelled_resolution(self):
        self.event.local_date = None
        self.event.save()
        coverage = build_multisource_coverage(now=fixtures.NOW, policy=self.policy)
        self.assertEqual(coverage["counts"], {"missing_date": 1})
        stage_multisource_coverage_incidents(
            coverage=coverage, policy=self.policy, now=fixtures.NOW
        )
        self.assertEqual(models.RaceLiveAlertIncident.objects.count(), 0)

    def test_unknown_calendar_fields_preserve_existing_incident(self):
        self.event.race_datetime = None
        self.event.local_date = fixtures.NOW.date() - timedelta(days=1)
        self.event.save()
        stage_multisource_coverage_incidents(
            coverage=build_multisource_coverage(now=fixtures.NOW, policy=self.policy),
            policy=self.policy,
            now=fixtures.NOW,
        )
        incident = models.RaceLiveAlertIncident.objects.get()
        initial_status = incident.status
        for timezone_name, local_date, classification in (
            ("", self.event.local_date, "missing_timezone"),
            ("Invalid/Zone", self.event.local_date, "missing_timezone"),
            ("Asia/Tokyo", None, "missing_date"),
        ):
            with self.subTest(classification=classification, timezone=timezone_name):
                self.event.timezone_name = timezone_name
                self.event.local_date = local_date
                self.event.save()
                coverage = build_multisource_coverage(
                    now=fixtures.NOW, policy=self.policy
                )
                self.assertEqual(coverage["counts"], {classification: 1})
                stage_multisource_coverage_incidents(
                    coverage=coverage, policy=self.policy, now=fixtures.NOW
                )
                incident.refresh_from_db()
                self.assertEqual(incident.status, initial_status)
                self.assertIsNone(incident.resolved_at)
        self.event.status = "cancelled"
        self.event.save()
        stage_multisource_coverage_incidents(
            coverage=build_multisource_coverage(now=fixtures.NOW, policy=self.policy),
            policy=self.policy,
            now=fixtures.NOW,
        )
        incident.refresh_from_db()
        self.assertEqual(incident.status, "resolved")

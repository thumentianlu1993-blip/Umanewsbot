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

    def test_explicit_enabled_p02_cohort_keeps_distant_dates_in_coverage(self):
        for day in (fixtures.NOW.date() - timedelta(days=19),
                    fixtures.NOW.date() + timedelta(days=90)):
            with self.subTest(day=day):
                self.event.local_date = day
                self.event.save(update_fields=("local_date",))
                with override_settings(RACE_LIFECYCLE_V2_WRITE_ENABLED=True,
                                       RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,)):
                    report = build_multisource_coverage(now=fixtures.NOW, policy=self.policy)
                    self.assertEqual(report["counts"], {"enrollment_missing": 1})
                for enabled, ids in ((False, (self.event.pk,)), (True, ())):
                    with override_settings(RACE_LIFECYCLE_V2_WRITE_ENABLED=enabled,
                                           RACE_LIFECYCLE_V2_EVENT_IDS=ids):
                        self.assertEqual(build_multisource_coverage(
                            now=fixtures.NOW, policy=self.policy)["total"], 0)

    def test_distant_p02_cohort_preserves_pause_and_visibility_checks(self):
        self.event.local_date = fixtures.NOW.date() + timedelta(days=90)
        self.event.manual_lock_flags = {"runners": True}
        self.event.save()
        with override_settings(RACE_LIFECYCLE_V2_WRITE_ENABLED=True,
                               RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,)):
            self.assertEqual(build_multisource_coverage(
                now=fixtures.NOW, policy=self.policy)["counts"], {"manual_pause": 1})
            self.event.visibility_status = "draft"
            self.event.save(update_fields=("visibility_status",))
            self.assertEqual(build_multisource_coverage(
                now=fixtures.NOW, policy=self.policy)["total"], 0)

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

    def stage(self, now=fixtures.NOW):
        stage_multisource_coverage_incidents(
            coverage=build_multisource_coverage(now=now, policy=self.policy),
            policy=self.policy,
            now=now,
        )

    def open_issues(self):
        return set(
            models.RaceLiveAlertIncident.objects.exclude(status="resolved")
            .values_list("details__issue", flat=True)
        )

    def test_lifecycle_not_advanced_issue_staged_after_t5(self):
        # T+5 前不触发：仍按 enrollment_missing 口径。
        self.event.race_datetime = fixtures.NOW - timedelta(minutes=4)
        self.event.save()
        self.stage()
        self.assertEqual(self.open_issues(), {"enrollment_missing"})
        # T+5 后仍 scheduled：转 lifecycle_not_advanced，旧 issue 由 stale 清理 resolve。
        self.event.race_datetime = fixtures.NOW - timedelta(minutes=6)
        self.event.save()
        self.stage()
        self.assertEqual(self.open_issues(), {"lifecycle_not_advanced"})
        # 越过 T+30 仍未转态：lifecycle_not_advanced 优先于 result_overdue。
        self.event.race_datetime = fixtures.NOW - timedelta(minutes=45)
        self.event.save()
        self.stage()
        self.assertEqual(self.open_issues(), {"lifecycle_not_advanced"})
        incidents = models.RaceLiveAlertIncident.objects.exclude(status="resolved")
        self.assertEqual(incidents.count(), 1)
        incident = incidents.get()
        self.assertEqual(incident.alert_type, "official_overdue")
        self.assertIsNone(incident.next_attempt_at)

    def test_lifecycle_not_advanced_resolves_on_status_change(self):
        self.event.race_datetime = fixtures.NOW - timedelta(minutes=6)
        self.event.save()
        self.stage()
        lifecycle = models.RaceLiveAlertIncident.objects.get()
        self.assertEqual(lifecycle.details["issue"], "lifecycle_not_advanced")
        # 转态 running：lifecycle issue 条件不再成立，stale 清理将其 resolve。
        self.event.status = "running"
        self.event.save()
        self.stage()
        lifecycle.refresh_from_db()
        self.assertEqual(lifecycle.status, "resolved")
        self.assertEqual(lifecycle.resolved_at, fixtures.NOW)
        self.assertEqual(self.open_issues(), {"enrollment_missing"})
        # 终态 confirmed：既有 resolve 分支清掉全部未决 incident。
        self.event.status = "finished"
        self.event.result_confirmed_at = fixtures.NOW
        self.event.save()
        self.stage()
        self.assertFalse(
            models.RaceLiveAlertIncident.objects.exclude(status="resolved").exists()
        )

    def test_manual_pause_never_stages_lifecycle_issue(self):
        self.event.race_datetime = fixtures.NOW - timedelta(minutes=45)
        self.event.manual_lock_flags = {"race_datetime": True}
        self.event.save()
        self.stage()
        self.assertFalse(models.RaceLiveAlertIncident.objects.exists())
        self.event.manual_lock_flags = {}
        self.event.save()
        models.RaceEventLifecycleControl.objects.create(
            event=self.event, manual_pause_reason="ops hold"
        )
        self.stage()
        self.assertFalse(models.RaceLiveAlertIncident.objects.exists())

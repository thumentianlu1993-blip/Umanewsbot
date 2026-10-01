from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from stable import models
from stable.services.race_public_coverage import (
    build_public_race_coverage,
    reconcile_public_race_coverage,
    deliver_coverage_digest,
)

NOW = datetime(2026, 10, 2, 0, tzinfo=timezone.utc)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RACE_LIVE_ALERT_NOTIFY_EMAILS=("ops@example.test",),
    RACE_DATA_COVERAGE_ALERTS_ENABLED=True,
)
class PublicCoverageTests(TestCase):
    def test_mixed_confirmed_and_unconfirmed_results_keep_gap_open(self):
        event = self.event(status="finished")
        models.RaceEventResult.objects.create(
            event=event, finish_position=1, horse_name="A", is_confirmed=True
        )
        models.RaceEventResult.objects.create(
            event=event, finish_position=2, horse_name="B", is_confirmed=False
        )
        reconcile_public_race_coverage(now=NOW)
        self.assertEqual(
            models.RaceLiveAlertIncident.objects.get(
                scope_type="data_sync_event"
            ).status,
            "open",
        )

    def test_policy_outage_after_recovery_sends_again(self):
        from stable.services.race_data_sync_alerts import (
            stage_multisource_policy_incident,
            resolve_multisource_policy_incident,
        )

        stage_multisource_policy_incident(now=NOW, reason="expired")
        self.assertTrue(deliver_coverage_digest(now=NOW)["delivered"])
        resolve_multisource_policy_incident(now=NOW + timedelta(minutes=5))
        stage_multisource_policy_incident(
            now=NOW + timedelta(hours=1), reason="expired_again"
        )
        self.assertTrue(
            deliver_coverage_digest(now=NOW + timedelta(hours=1))["delivered"]
        )

    def test_confirmed_but_hidden_live_result_is_a_publication_gap(self):
        from types import SimpleNamespace

        event = self.event(status="finished", result_confirmed_at=NOW)
        models.RaceEventProjectionControl.objects.create(
            event=event,
            write_owner="data_sync",
            owner_generation=1,
            owner_manifest_sha256="a" * 64,
        )
        models.RaceEventResult.objects.create(
            event=event, finish_position=1, horse_name="A", is_confirmed=True
        )
        with patch(
            "stable.services.race_public_coverage.resolve_race_live_public_read",
            return_value=SimpleNamespace(
                visible=False, reason="data_sync_enrollment_policy_drift"
            ),
        ):
            row = build_public_race_coverage(now=NOW)["entries"][0]
        self.assertEqual(row["issue"], "publication_blocked")

    def test_legacy_slo_cannot_close_full_coverage_publication_gap(self):
        from stable.services.race_data_sync_alerts import (
            _resolve_data_sync_event_incidents,
        )

        event = self.event()
        reconcile_public_race_coverage(now=NOW)
        _resolve_data_sync_event_incidents(event_id=event.pk, now=NOW)
        self.assertEqual(
            models.RaceLiveAlertIncident.objects.get(scope_key=str(event.pk)).status,
            "open",
        )

    def test_confirmation_timestamp_without_rows_and_scheduled_rows_are_gaps(self):
        self.event(status="finished", result_confirmed_at=NOW)
        scheduled = self.event(status="scheduled")
        models.RaceEventResult.objects.create(
            event=scheduled, finish_position=1, horse_name="A", is_confirmed=True
        )
        self.assertTrue(
            all(row["issue"] for row in build_public_race_coverage(now=NOW)["entries"])
        )

    def event(self, **kw):
        count = models.RaceEvent.objects.count()
        defaults = dict(
            year=2026,
            slug=f"coverage-{count}",
            original_name=f"Race {count}",
            country_region="ireland",
            racecourse="Curragh",
            local_date=NOW.date() - timedelta(days=15),
            timezone_name="Europe/Dublin",
            visibility_status="published",
            status="scheduled",
        )
        return models.RaceEvent.objects.create(**(defaults | kw))

    def test_all_dates_and_regions_remain_in_denominator_without_network(self):
        old = self.event()
        unknown = self.event(local_date=None)
        future = self.event(local_date=NOW.date() + timedelta(days=60))
        self.event(visibility_status="draft")
        report = build_public_race_coverage(now=NOW)
        self.assertEqual(report["total"], 3)
        rows = {r["event_id"]: r for r in report["entries"]}
        self.assertEqual(rows[old.pk]["issue"], "time_unknown_overdue")
        self.assertEqual(rows[unknown.pk]["issue"], "missing_date")
        self.assertEqual(rows[future.pk]["classification"], "awaiting_source_window")
        self.assertTrue(all(r["next_action"] for r in rows.values()))
        self.assertEqual(sum(report["counts"].values()), 3)

    def test_canonical_duplicate_is_excluded(self):
        canonical, duplicate = self.event(), self.event()
        models.RaceEventProductCanonicalLink.objects.create(
            canonical_event=canonical,
            duplicate_event=duplicate,
            is_active=True,
            identity_sha256="b" * 64,
            manifest_sha256="c" * 64,
            approved_at=NOW,
            approved_by=get_user_model().objects.create_user(username="reviewer"),
        )
        self.assertEqual(build_public_race_coverage(now=NOW)["total"], 1)

    def test_missing_timezone_and_partial_results_do_not_count_as_confirmed(self):
        event = self.event(timezone_name="Bad/Zone")
        models.RaceEventResult.objects.create(
            event=event, finish_position=1, horse_name="Draft", is_confirmed=False
        )
        row = build_public_race_coverage(now=NOW)["entries"][0]
        self.assertEqual(row["issue"], "missing_timezone")
        self.assertIsNone(row["next_poll_at"])

    def test_old_confirmed_history_is_not_reported_as_result_gap(self):
        event = self.event(status="finished")
        models.RaceEventResult.objects.create(
            event=event, finish_position=1, horse_name="Winner", is_confirmed=True
        )
        row = build_public_race_coverage(now=NOW)["entries"][0]
        self.assertEqual(row["classification"], "confirmed")
        self.assertEqual(row["issue"], "")

    def test_monitor_reuses_old_incident_and_does_not_write_race(self):
        event = self.event()
        updated = event.updated_at
        incident = models.RaceLiveAlertIncident.objects.create(
            alert_type="provisional_overdue",
            scope_type="data_sync_event",
            scope_key=str(event.pk),
            dedupe_key="a" * 64,
            opened_at=NOW - timedelta(days=10),
        )
        reconcile_public_race_coverage(now=NOW)
        reconcile_public_race_coverage(now=NOW + timedelta(minutes=5))
        self.assertEqual(
            models.RaceLiveAlertIncident.objects.filter(
                scope_type="data_sync_event"
            ).count(),
            1,
        )
        incident.refresh_from_db()
        self.assertEqual(incident.details["issue"], "time_unknown_overdue")
        self.assertTrue(incident.details["next_action"])
        event.refresh_from_db()
        self.assertEqual(event.updated_at, updated)

    def test_resolved_withdrawn_and_reopened_incidents(self):
        event = self.event()
        reconcile_public_race_coverage(now=NOW)
        incident = models.RaceLiveAlertIncident.objects.get(
            scope_type="data_sync_event"
        )
        event.visibility_status = "draft"
        event.save()
        reconcile_public_race_coverage(now=NOW + timedelta(minutes=5))
        incident.refresh_from_db()
        self.assertEqual(incident.status, "resolved")
        event.visibility_status = "published"
        event.save()
        reconcile_public_race_coverage(now=NOW + timedelta(minutes=10))
        incident.refresh_from_db()
        self.assertEqual(incident.status, "open")
        self.assertIsNone(incident.alert_sent_at)

    def test_digest_one_mail_dedup_success_and_next_action(self):
        for _ in range(3):
            self.event()
        reconcile_public_race_coverage(now=NOW)
        result = deliver_coverage_digest(now=NOW)
        self.assertTrue(result["delivered"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("下一步", mail.outbox[0].body)
        self.assertEqual(
            models.RaceLiveAlertIncident.objects.filter(
                scope_type="data_sync_event", alert_sent_at__isnull=False
            ).count(),
            3,
        )
        self.assertFalse(
            deliver_coverage_digest(now=NOW + timedelta(minutes=5))["delivered"]
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_smtp_failure_retries_without_false_sent_receipt(self):
        self.event()
        reconcile_public_race_coverage(now=NOW)
        with patch(
            "stable.services.race_public_coverage.send_mail",
            side_effect=OSError("smtp"),
        ):
            self.assertFalse(deliver_coverage_digest(now=NOW)["delivered"])
        self.assertFalse(
            models.RaceLiveAlertIncident.objects.filter(
                alert_sent_at__isnull=False
            ).exists()
        )
        self.assertTrue(
            deliver_coverage_digest(now=NOW + timedelta(hours=1))["delivered"]
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_resolution_during_send_cannot_be_overwritten_by_receipt(self):
        event = self.event()
        reconcile_public_race_coverage(now=NOW)

        def send(*args, **kwargs):
            event.status = "cancelled"
            event.save()
            reconcile_public_race_coverage(now=NOW + timedelta(seconds=1))
            return 1

        with patch("stable.services.race_public_coverage.send_mail", side_effect=send):
            deliver_coverage_digest(now=NOW)
        self.assertEqual(
            models.RaceLiveAlertIncident.objects.get(
                scope_type="data_sync_event"
            ).status,
            "resolved",
        )

    def test_admin_requires_model_view_permission_and_is_read_only(self):
        self.event()
        user = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.client.force_login(user)
        url = reverse("admin:stable_raceevent_coverage")
        self.assertEqual(self.client.get(url).status_code, 403)
        from django.contrib.auth.models import Permission

        user.user_permissions.add(Permission.objects.get(codename="view_raceevent"))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "下一步")
        self.assertFalse(models.RaceLiveAlertIncident.objects.exists())

    def test_active_digest_lease_prevents_second_sender(self):
        self.event()
        reconcile_public_race_coverage(now=NOW)

        def send(*args, **kwargs):
            self.assertEqual(
                deliver_coverage_digest(now=NOW)["reason"], "delivery_lease_active"
            )
            return 1

        with patch(
            "stable.services.race_public_coverage.send_mail", side_effect=send
        ) as sender:
            self.assertTrue(deliver_coverage_digest(now=NOW)["delivered"])
        self.assertEqual(sender.call_count, 1)


from concurrent.futures import ThreadPoolExecutor
from threading import Event
from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from unittest import skipUnless


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL concurrency")
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RACE_LIVE_ALERT_NOTIFY_EMAILS=("ops@example.test",),
    RACE_DATA_COVERAGE_ALERTS_ENABLED=True,
)
class PublicCoverageConcurrencyTests(TransactionTestCase):
    def test_overlapping_census_skips_without_blocking_or_writes(self):
        acquired, release = Event(), Event()

        def hold_lock():
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_advisory_xact_lock(%s)", [714020261002]
                        )
                    acquired.set()
                    if not release.wait(10):
                        raise AssertionError("lock test timed out")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            worker = pool.submit(hold_lock)
            try:
                self.assertTrue(acquired.wait(5))
                self.assertEqual(
                    reconcile_public_race_coverage(now=NOW)["skipped"], "monitor_busy"
                )
                self.assertFalse(models.RaceLiveAlertIncident.objects.exists())
            finally:
                release.set()
                worker.result(timeout=10)

    def test_concurrent_digest_uses_single_lease(self):
        from stable.services.race_data_sync_alerts import (
            stage_multisource_policy_incident,
        )

        stage_multisource_policy_incident(now=NOW, reason="expired")
        sending, release = Event(), Event()

        def smtp(*args, **kwargs):
            sending.set()
            if not release.wait(10):
                raise AssertionError("SMTP test timed out")
            return 1

        def deliver():
            try:
                return deliver_coverage_digest(now=NOW)
            finally:
                connections.close_all()

        with patch(
            "stable.services.race_public_coverage.send_mail", side_effect=smtp
        ) as send, ThreadPoolExecutor(max_workers=1) as pool:
            worker = pool.submit(deliver)
            try:
                self.assertTrue(sending.wait(5))
                self.assertFalse(deliver_coverage_digest(now=NOW)["delivered"])
            finally:
                release.set()
            self.assertTrue(worker.result(timeout=10)["delivered"])
            self.assertEqual(send.call_count, 1)

from datetime import timedelta
from django.test import TestCase, override_settings
from stable import models
from stable.services.race_data_sync_control import calculate_multisource_next_poll
from stable.test_race_multisource_identity import NOW


@override_settings(RACE_LIFECYCLE_V2_WRITE_ENABLED=True)
class LifecycleScheduleTests(TestCase):
    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026, slug="schedule", original_name="Schedule", normalized_grade="G1",
            country_region="japan", race_datetime=NOW - timedelta(days=3),
            local_date=(NOW - timedelta(days=3)).date(), timezone_name="Asia/Tokyo", status="finished")
        self.control = models.RaceEventLifecycleControl.objects.create(
            event=self.event, first_result_confirmed_at=NOW - timedelta(days=3),
            correction_until=NOW + timedelta(days=4))
        config = override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,))
        config.enable()
        self.addCleanup(config.disable)

    def test_daily_full_review_does_not_delay_change_discovery(self):
        self.assertEqual(calculate_multisource_next_poll(event=self.event, kind="result", now=NOW),
                         NOW + timedelta(seconds=60))
        self.event.normalized_grade = "G2"
        self.assertEqual(calculate_multisource_next_poll(event=self.event, kind="result", now=NOW),
                         NOW + timedelta(seconds=120))

    def test_unconfirmed_overdue_race_stays_in_discovery_and_seven_days_is_from_confirmation(self):
        self.event.status = "running"
        self.event.race_datetime = NOW - timedelta(days=10)
        self.event.local_date = self.event.race_datetime.date()
        self.control.first_result_confirmed_at = None
        self.control.correction_until = None
        self.control.save()
        self.assertEqual(calculate_multisource_next_poll(event=self.event, kind="result", now=NOW),
                         NOW + timedelta(seconds=60))

    def test_exact_confirmation_window_end_stops_automatic_discovery(self):
        for kind in ("result", "racecard", "race_time"):
            self.assertIsNone(calculate_multisource_next_poll(
                event=self.event, kind=kind, now=self.control.correction_until))

    def test_clock_alone_never_finishes_or_starts_cohort_event(self):
        from stable.services.race_data_sync_lifecycle import decide_data_sync_lifecycle
        for status in ('scheduled', 'running'):
            self.event.status = status
            self.event.race_datetime = NOW - timedelta(hours=1)
            decision = decide_data_sync_lifecycle(event=self.event, now=NOW)
            self.assertEqual(decision.to_status, '', '计划时间错误地变成真实赛事事实')

    def test_cancelled_only_keeps_daily_schedule_recovery(self):
        self.event.status = 'cancelled'
        self.assertIsNone(calculate_multisource_next_poll(event=self.event, kind='result', now=NOW))
        self.assertEqual(calculate_multisource_next_poll(event=self.event, kind='race_time', now=NOW), NOW + timedelta(days=1))

    def test_postponed_race_retains_timely_discovery(self):
        self.event.status='postponed'
        self.event.race_datetime=None
        for kind in ('race_time', 'racecard', 'result'):
            self.assertEqual(calculate_multisource_next_poll(event=self.event, kind=kind, now=NOW), NOW+timedelta(seconds=60))

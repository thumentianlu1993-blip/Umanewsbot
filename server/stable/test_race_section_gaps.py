from datetime import date, datetime, timedelta, timezone as tz
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase
from stable import models
from stable.services.race_data_sync_policy import calculate_next_poll_at
from stable.services.race_data_sync_providers import _result_payload
from stable.services.race_events import apply_data_candidate
from stable.views import _public_race_status_label

NOW = datetime(2026, 9, 17, 3, tzinfo=tz.utc)


class SectionRegressionTests(SimpleTestCase):
    def test_distant_racecard_uses_three_hours(self):
        self.assertEqual(calculate_next_poll_at(
            data_kind='racecard', now=NOW, race_datetime=NOW + timedelta(days=4)
        ), NOW + timedelta(hours=3))

    def test_same_day_time_uses_ten_minutes(self):
        self.assertEqual(calculate_next_poll_at(
            data_kind='race_time', now=NOW, race_datetime=NOW + timedelta(hours=3)
        ), NOW + timedelta(minutes=10))

    def test_past_date_is_not_pre_race(self):
        event = models.RaceEvent(status='scheduled', local_date=date(2026, 9, 16), timezone_name='Asia/Tokyo')
        with patch('django.utils.timezone.now', return_value=NOW):
            self.assertEqual(_public_race_status_label(event, date(2026, 9, 17)), '赛期已过，资料待补')

    def test_result_payload_does_not_invent_terminal_status(self):
        event = Mock()
        event.runners.filter.return_value.order_by.return_value = []
        payload = _result_payload(normalized_race={
            'participants': [], 'external_race_id': 'race-1', 'off_time': NOW.isoformat(),
            'course': 'Test', 'race_name': 'Test',
        }, region='japan_jra', event=event, source_key='the_racing_api')
        self.assertEqual(payload['race_status'], '')


class CandidateBypassTests(TestCase):
    def test_jra_preview_cannot_use_generic_apply(self):
        event = models.RaceEvent.objects.create(year=2026, slug='preview', chinese_name='测试赛', local_date=date(2026, 9, 20))
        for module in ('runners', 'basic'):
            with self.subTest(module=module):
                candidate = models.RaceEventDataCandidate.objects.create(
                    event=event, module=module, source_name='jra_pre_race_v1',
                    candidate_payload={'items': [{'horse_name': '仅展示'}]},
                    raw_payload={'jra_pre_race_v1': {'validated': True}},
                )
                with self.assertRaisesRegex(ValueError, 'jra_pre_race'):
                    apply_data_candidate(candidate)
                self.assertEqual(event.runners.count(), 0)

class CalendarFilterTests(TestCase):
    def make(self, slug, **kw):
        return models.RaceEvent.objects.create(year=2026,slug=slug,chinese_name=slug,
            visibility_status='published',timezone_name='Asia/Tokyo',**kw)

    def test_upcoming_excludes_past_and_running(self):
        from stable.views import _public_race_calendar_base_queryset
        old=self.make('old',status='scheduled',local_date=date(2026,9,16))
        future=self.make('future',status='scheduled',local_date=date(2026,9,18))
        self.make('running',status='running',local_date=date(2026,9,17))
        with patch('django.utils.timezone.now',return_value=NOW):
            qs=_public_race_calendar_base_queryset({'year':'','tab':'all','region':'','grade':'','when':'upcoming'},today=NOW.date())
            self.assertEqual(list(qs.values_list('pk',flat=True)),[future.pk])

    def test_finished_requires_actual_confirmed_results(self):
        from stable.views import _public_race_calendar_base_queryset
        self.make('empty',status='finished',local_date=date(2026,9,16))
        with patch('django.utils.timezone.now',return_value=NOW):
            qs=_public_race_calendar_base_queryset({'year':'','tab':'all','region':'','grade':'','when':'finished'},today=NOW.date())
            self.assertEqual(qs.count(),0)

    def test_home_finished_without_evidence_shows_pending(self):
        from stable.views import _public_today_races
        self.make('pending-today',status='finished',local_date=NOW.date())
        with patch('django.utils.timezone.now', return_value=NOW):
            entries, _ = _public_today_races()
        self.assertEqual(entries[0]['status_label'], '赛果待确认')

    def test_missing_revision_does_not_leak_data_sync_confirmed_rows(self):
        from stable.views import _finished_race_queryset
        event=self.make('missing-revision',status='finished',local_date=NOW.date())
        models.RaceEventProjectionControl.objects.create(event=event,write_owner='data_sync')
        models.RaceEventResult.objects.create(event=event,horse_name='Old',finish_position=1,is_confirmed=True)
        self.assertFalse(_finished_race_queryset(models.RaceEvent.objects.all(), NOW).exists())

    def test_relative_day_uses_race_timezone(self):
        event=models.RaceEvent(status='scheduled',local_date=date(2026,9,17),timezone_name='America/New_York')
        with patch('django.utils.timezone.now',return_value=NOW):
            self.assertEqual(_public_race_status_label(event,NOW.date()),'明天')

    def test_audit_reports_bounded_unmanaged_gap_without_writes(self):
        from stable.management.commands.audit_race_data_sync import section_gaps
        old=self.make('audit-old',status='scheduled',local_date=date(2026,9,16))
        report=section_gaps(NOW)
        self.assertEqual(report['expired_unmanaged']['event_ids'],[old.pk])
        old.refresh_from_db()
        self.assertEqual(old.status,'scheduled')

    def test_detail_overview_uses_public_status(self):
        cases = (
            ('expired-detail', 'scheduled', '赛期已过，资料待补'),
            ('pending-detail', 'finished', '赛果待确认'),
        )
        for slug, status, label in cases:
            with self.subTest(status=status):
                event = self.make(slug, status=status, local_date=date(2026, 9, 16))
                with patch('django.utils.timezone.now', return_value=NOW):
                    response = self.client.get(event.public_path)
                self.assertContains(response, f'<span>状态</span><b>{label}</b>', html=True)

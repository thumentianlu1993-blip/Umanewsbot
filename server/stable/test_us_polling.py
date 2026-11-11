"""美国赛日刷新与七天更正的隔离时钟测试。"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from stable.services.race_data_sync_control import calculate_multisource_next_poll
from stable.services.race_pre_race import _finish_locked

NOW = datetime(2026,11,7,18,0,tzinfo=timezone.utc)


def event(**kw):
    return SimpleNamespace(country_region='united_states', timezone_name='America/New_York',
        **dict(dict(status='scheduled', local_date=date(2026,11,7), race_datetime=None,
             result_confirmed_at=None, priority='P1', source_refs={}), **kw))


class USPollingTests(SimpleTestCase):
    def test_race_day_five_or_ten_minutes_without_guessed_off_time(self):
        for priority, minutes in [('P0',5),('P1',5),('P2',10)]:
            for kind in ['racecard', 'result']:
                self.assertEqual(calculate_multisource_next_poll(event=event(priority=priority), kind=kind, now=NOW), NOW+timedelta(minutes=minutes))

    def test_confirmed_date_only_results_continue_seven_days(self):
        e=event(result_confirmed_at=NOW)
        self.assertEqual(calculate_multisource_next_poll(event=e,kind='result',now=NOW), NOW+timedelta(hours=6))
        self.assertIsNotNone(calculate_multisource_next_poll(event=e,kind='result',now=NOW+timedelta(days=7)))
        self.assertIsNone(calculate_multisource_next_poll(event=e,kind='result',now=NOW+timedelta(days=8)))

    def test_known_off_time_stops_at_seven_days_and_never_polls_past_horizon(self):
        e=event(race_datetime=NOW, result_confirmed_at=NOW)
        last=NOW+timedelta(days=7,minutes=-10)
        self.assertEqual(calculate_multisource_next_poll(event=e,kind='result',now=last), NOW+timedelta(days=7))
        self.assertIsNone(calculate_multisource_next_poll(event=e,kind='result',now=NOW+timedelta(days=7)))

    def test_pre_race_completion_uses_us_cadence_instead_of_ten_minute_slot(self):
        for priority, minutes in [('P1',5),('P2',10)]:
            e=event(priority=priority,source_refs={'pre_race_checks': {'us_pre_race_v1': {'last_attempt_at':NOW.isoformat()}}})
            with patch('stable.services.race_pre_race._save_state') as save:
                _finish_locked(e, {'source':'us_pre_race_v1'}, NOW+timedelta(seconds=25))
            self.assertEqual(datetime.fromisoformat(save.call_args.args[2]['next_poll_at']), NOW+timedelta(minutes=minutes))

    def test_local_midnight_enters_fast_tier_and_failed_request_retries(self):
        before=datetime(2026,11,7,4,59,tzinfo=timezone.utc)
        self.assertEqual(calculate_multisource_next_poll(event=event(),kind='racecard',now=before),datetime(2026,11,7,5,tzinfo=timezone.utc))
        with patch('stable.services.race_pre_race._save_state') as save:
            _finish_locked(event(), {'source':'us_pre_race_v1'}, NOW, reason='timeout')
        self.assertEqual(save.call_args.args[2]['failures'], 1)
        self.assertEqual(save.call_args.args[2]['reason'], 'timeout')

    def test_us_beat_dispatches_every_minute_and_defaults_closed(self):
        from app.settings import build_race_data_sync_beat_schedule
        closed=build_race_data_sync_beat_schedule(scheduler_enabled=True)
        self.assertNotIn('discover-us-pre-race',closed)
        opened=build_race_data_sync_beat_schedule(scheduler_enabled=True,us_pre_race_enabled=True)
        entry=opened['discover-us-pre-race']
        self.assertEqual(entry['schedule'].minute,set(range(60)))
        self.assertEqual(entry['options']['queue'],'race_sync_v2')

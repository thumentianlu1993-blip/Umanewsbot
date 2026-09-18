from stable.test_pre_race_refresh import (REFRESH_FLAGS, FLAGS, NOW, URL, FIXTURES, NYRA_URL, SL_URL, pre, models, event)
from stable.test_pre_race_refresh import BoundRefreshTests as _Bound, BeijingContractTests as _Beijing
from datetime import datetime, date, timedelta, timezone as tz
from unittest.mock import patch
from django.test import TestCase, override_settings
from stable.services import race_pre_race_refresh as refresh

@override_settings(**REFRESH_FLAGS)
class ReviewedCardRetentionTests(TestCase):
    setUp = _Bound.setUp
    def prime(self):
        claim=pre.claim_pre_race(event_id=self.e.pk,source=pre.REFRESH,now=self.now)
        claim['binding']=refresh.binding_for(self.e)
        self.assertTrue(refresh.complete_refresh(claim,html=(FIXTURES/'nyra.html').read_text(),url=NYRA_URL,now=self.now))
        self.e.refresh_from_db()

    def test_binding_change_retains_card_and_next_claim_can_replace_it(self):
        self.prime()
        self.e.source_refs.pop('pre_race_refresh_binding');self.e.save()
        with patch('django.utils.timezone.now',return_value=self.now):
            self.assertContains(self.client.get(self.e.public_path),'退赛',count=3)
        later=self.now+timedelta(minutes=10)
        claim=pre.claim_pre_race(event_id=self.e.pk,source=pre.REFRESH,now=later);claim['binding']=refresh.binding_for(self.e)
        self.assertTrue(refresh.complete_refresh(claim,html=(FIXTURES/'sl-491.html').read_text(),url=SL_URL,now=later))
        self.e.refresh_from_db()
        self.assertEqual(sum(r.running_status=='scratched' for r in refresh.public_refresh_preview(self.e,now=later)['rows']),3)

    def test_managed_waiting_for_canonical_keeps_latest_card(self):
        self.prime()
        models.RaceEventProjectionControl.objects.create(event=self.e,write_owner='data_sync')
        with patch('django.utils.timezone.now',return_value=self.now):
            self.assertContains(self.client.get(self.e.public_path),'退赛',count=3)

class ReviewDynamicTests(TestCase):
    def test_zero_fractional_not_fresh(self):
        row=dict(horse_number='1',horse_name='A',odds_value='0/1',odds_format='fractional',odds_kind='current')
        items=refresh.stamp_dynamic_items([row],[],now=NOW,source_url=URL)
        self.assertFalse(items[0]['odds_value']);self.assertFalse(items[0]['odds_observed_at'])

    def test_cross_source_missing_price_clears_old_price(self):
        old=dict(horse_number='1',horse_name='A',odds_value='4.2',odds_format='decimal',odds_kind='current',odds_observed_at=NOW.isoformat(),source_refs={'primary':SL_URL})
        row=dict(horse_number='1',horse_name='A')
        items=refresh.stamp_dynamic_items([row],[old],now=NOW,source_url=NYRA_URL)
        self.assertFalse(items[0]['odds_value']);self.assertFalse(items[0]['odds_observed_at'])

    @override_settings(**FLAGS)
    def test_worker_and_serial_source_delay_keep_next_beat_slot(self):
        e=event();e.local_date=NOW.date();e.save()
        for index,minute in enumerate((18,29)):
            claim=pre.claim_pre_race(event_id=e.pk,source=pre.JRA,now=NOW.replace(minute=minute))
            self.assertIsNotNone(claim)
            pre.finish_pre_race(claim,now=NOW.replace(minute=minute,second=45))
            e.refresh_from_db()
            self.assertEqual(pre._dt(pre._state(e,pre.JRA)['next_poll_at']),NOW.replace(minute=27 if index==0 else 37))

class ReviewAnchorTests(TestCase):
    make = _Beijing.make
    def test_forty_earlier_races_cannot_hide_today_and_both_directions_reach_all(self):
        for i in range(40):self.make(f'old{i}',timezone_name='Asia/Shanghai',race_datetime=None)
        today=self.make('anchor',timezone_name='Asia/Shanghai',local_date=date(2026,9,19),race_datetime=None)
        now=datetime(2026,9,18,18,tzinfo=tz.utc)
        def ids(r):return [e.pk for g in r.context['groups'] for e in g['events']]
        with patch('django.utils.timezone.now',return_value=now):
            first=self.client.get('/races/',{'tab':'all'})
            self.assertIn(today.pk,ids(first))
            seen=set(ids(first))
            for direction in ('previous_url','next_url'):
                current=first
                for _ in range(3):
                    if not current.context[direction]:break
                    current=self.client.get(current.context[direction]);seen.update(ids(current))
            self.assertEqual(seen,set(models.RaceEvent.objects.values_list('pk',flat=True)))

class ReviewIdentityClockTests(TestCase):
    def test_same_source_id_matches_name_variation_but_rejects_id_or_number_change(self):
        old=dict(horse_number='1',horse_name='Alpha',running_status='scratched',source_refs={'primary':SL_URL,'horse_id':'123'})
        row=dict(horse_number='1',horse_name='Alpha Updated',source_refs={'horse_id':'123'})
        self.assertEqual(refresh.stamp_dynamic_items([row],[old],now=NOW,source_url=SL_URL)[0]['running_status'],'scratched')
        for wrong in (dict(horse_number='1',horse_name='Alpha',source_refs={'horse_id':'456'}),dict(horse_number='2',horse_name='Alpha',source_refs={'horse_id':'123'})):
            with self.assertRaises(ValueError):refresh.stamp_dynamic_items([wrong],[old],now=NOW,source_url=SL_URL)

    @override_settings(**REFRESH_FLAGS)
    def test_identical_price_check_advances_checked_but_not_changed(self):
        _Bound.setUp(self)
        html=(FIXTURES/'nyra.html').read_text()
        for tick in (self.now,self.now+timedelta(minutes=10)):
            with patch('stable.services.race_pre_race_refresh.fetch_bound_html',return_value=html):
                self.assertEqual(refresh.discover_bound_pre_race(now=tick,clock=lambda:tick)['checked'],1)
        self.e.refresh_from_db();state=pre._state(self.e,pre.REFRESH)
        self.assertEqual(pre._dt(state['last_checked_at']),self.now+timedelta(minutes=10))
        self.assertEqual(pre._dt(state['last_changed_at']),self.now)

class ReviewMidnightTests(TestCase):
    @override_settings(**FLAGS)
    def test_delayed_first_tick_after_local_midnight_uses_new_tier(self):
        from zoneinfo import ZoneInfo
        e=event();local=datetime.combine(e.local_date,datetime.min.time(),tzinfo=ZoneInfo('Asia/Tokyo'))
        now=local+timedelta(minutes=1)
        claim=pre.claim_pre_race(event_id=e.pk,source=pre.JRA,now=now)
        pre.finish_pre_race(claim,now=now+timedelta(seconds=5))
        e.refresh_from_db()
        self.assertEqual(pre._dt(pre._state(e,pre.JRA)['next_poll_at']),local+timedelta(minutes=7))

class ReviewUnknownYearTests(TestCase):
    make = _Beijing.make

    def test_unknown_year_remains_discoverable_but_known_crossyear_uses_beijing_only(self):
        from stable.services.race_event_public_cache import public_race_calendar_years,invalidate_public_race_cache
        old=self.make('unknown-1984',year=1984,local_date=date(1984,7,1),local_start_time=None,race_datetime=None,timezone_name='Europe/Paris')
        cross=self.make('known-crossyear',local_date=date(2026,12,31),race_datetime=datetime(2026,12,31,21,14,tzinfo=tz.utc))
        self.make('hidden-draft',year=1983,local_date=date(1983,7,1),race_datetime=None,visibility_status='draft')
        invalidate_public_race_cache()
        self.assertEqual(public_race_calendar_years(),[2027,1984])
        page=self.client.get('/races/',{'tab':'all','year':'1984'})
        self.assertContains(page,old.public_path);self.assertContains(page,'北京时间待定')
        self.assertNotContains(self.client.get('/races/',{'tab':'all','year':'2026'}),cross.public_path)
        self.assertContains(self.client.get('/races/',{'tab':'all','year':'2027'}),cross.public_path)

    def test_known_first_and_unknown_41_rows_page_forward_and_backward(self):
        from datetime import time
        known=self.make('known-1984',year=1984,local_date=date(1984,7,1),local_start_time=time(14),race_datetime=datetime(1984,7,1,12,tzinfo=tz.utc),timezone_name='Europe/Paris')
        for i in range(41):self.make(f'unknown-{i}',year=1984,local_date=date(1984,7,1),local_start_time=None,race_datetime=None)
        def ids(r):return [e.pk for g in r.context['groups'] for e in g['events']]
        first=self.client.get('/races/',{'tab':'all','year':'1984'})
        second=self.client.get(first.context['next_url'])
        self.assertEqual(ids(first)[0],known.pk)
        self.assertEqual(ids(first)+ids(second),list(models.RaceEvent.objects.order_by('pk').values_list('pk',flat=True)))
        self.assertEqual(ids(self.client.get(second.context['previous_url'])),ids(first))

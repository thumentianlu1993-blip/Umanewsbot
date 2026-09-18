"""公开北京赛时与持续赛前更新的行为回归（禁止真实网络）。"""
from datetime import date, datetime, time, timedelta, timezone as tz
from unittest.mock import patch
from django.test import TestCase, override_settings
from stable import models
from stable.services import race_information_display as display, race_pre_race as pre
from stable.test_race_pre_race import FLAGS, HTML, URL, NOW, event

class BeijingContractTests(TestCase):
    def make(self, slug='us', **kw):
        values=dict(year=2026,slug=slug,chinese_name=slug,original_name=slug,visibility_status='published',
            local_date=date(2026,9,18),local_start_time=time(16,14),timezone_name='America/New_York',
            race_datetime=datetime(2026,9,18,20,14,tzinfo=tz.utc),eligibility_text='3U 3UP R D L')
        values.update(kw)
        return models.RaceEvent.objects.create(**values)

    def test_beijing_only_on_both_display_flag_paths(self):
        e=self.make()
        for flag in (False,True):
            with override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=flag), patch('django.utils.timezone.now',return_value=datetime(2026,9,18,18,tzinfo=tz.utc)):
                r=self.client.get(e.public_path)
                self.assertContains(r,'2026-09-19')
                self.assertContains(r,'04:14')
                self.assertNotContains(r,'America/New_York')
                self.assertNotContains(r,'当地时间')
                self.assertNotContains(r,'参赛条件')

    def test_sql_and_python_contract_and_conflicts(self):
        from stable.services.race_public_time import annotate_public_time, public_time
        self.make()
        self.make('hk',race_datetime=None,timezone_name='Asia/Shanghai')
        self.make('unknown',race_datetime=None,timezone_name='America/New_York')
        self.make('conflict',local_start_time=time(15,14))
        self.make('badzone',timezone_name='Invalid/Zone')
        self.make('dateonly',race_datetime=None,local_start_time=None,timezone_name='Asia/Shanghai')
        for e in annotate_public_time(models.RaceEvent.objects.all()):
            expected=public_time(e)
            self.assertEqual((e.public_date,e.public_start_time),(expected.day,expected.clock),e.slug)
        self.assertIsNone(public_time(models.RaceEvent.objects.get(slug='conflict')).day)

    def test_calendar_sort_cross_year_filter_and_cursor(self):
        self.make('us')
        self.make('hk',timezone_name='Asia/Shanghai',local_date=date(2026,9,19),local_start_time=time(2),race_datetime=datetime(2026,9,18,18,tzinfo=tz.utc))
        r=self.client.get('/races/',{'year':'2026','tab':'all'})
        events=[e for g in r.context['groups'] for e in g['events']]
        self.assertEqual([e.slug for e in events],['hk','us'])
        e=self.make('newyear',local_date=date(2026,12,31),race_datetime=datetime(2026,12,31,21,14,tzinfo=tz.utc))
        # New York winter is UTC-5.
        r=self.client.get('/races/',{'year':'2027','tab':'all'})
        self.assertContains(r,'newyear')
        self.assertEqual(e.year,2026)

@override_settings(**{**FLAGS,'RACE_DATA_SYNC_ENABLED_FIELDS':(*FLAGS['RACE_DATA_SYNC_ENABLED_FIELDS'],'participants.status','participants.odds','participants.popularity')})
class DynamicJraTests(TestCase):
    def setUp(self):self.event=event()
    def test_parse_and_show_scratch_odds_and_stop_preserves_last_card(self):
        html=HTML.replace('<td class="num"></td>','<td class="num">1</td>').replace('</tr>','<td class="odds"><span class="odds">4.2</span><span class="rank">2</span></td><td class="status">取消</td></tr>')
        claim=pre.claim_pre_race(event_id=self.event.pk,source=pre.JRA,now=NOW)
        pre.complete_jra(claim,html=html,url=URL,now=NOW)
        self.event.refresh_from_db()
        row=pre.public_jra_preview(self.event,now=NOW)['rows'][0]
        self.assertEqual(row.running_status,'scratched')
        self.assertEqual(row.odds_value,'') # scratches cannot show actionable odds
        with override_settings(RACE_DATA_SYNC_JRA_PRE_RACE_ENABLED=False):
            self.assertIsNotNone(pre.public_jra_preview(self.event,now=NOW))
    def test_completed_seconds_do_not_skip_next_tick(self):
        self.event.local_date=NOW.date();self.event.save()
        claim=pre.claim_pre_race(event_id=self.event.pk,source=pre.JRA,now=NOW.replace(minute=27))
        pre.finish_pre_race(claim,now=NOW.replace(minute=27,second=7))
        self.event.refresh_from_db()
        self.assertLessEqual(pre._dt(pre._state(self.event,pre.JRA)['next_poll_at']),NOW.replace(minute=37))

class DynamicFreshnessTests(TestCase):
    def test_old_price_not_revived_by_missing_price_or_old_source_clock(self):
        from stable.services.race_pre_race_refresh import stamp_dynamic_items, dynamic_rows
        e=event();e.local_date=NOW.date()
        old=[dict(horse_name='A',horse_number='1',running_status='declared',odds_value='4.2',odds_kind='current',odds_format='decimal',odds_observed_at=NOW.isoformat())]
        later=NOW+timedelta(minutes=30)
        for fresh in [dict(horse_name='A',horse_number='1',running_status='declared'),dict(**{k:v for k,v in old[0].items() if k!='odds_observed_at'},odds_source_at=NOW.isoformat())]:
            items=stamp_dynamic_items([fresh],old,now=later,source_url=URL)
            self.assertEqual(items[0]['odds_observed_at'],NOW.isoformat())
            with override_settings(**{**FLAGS,'RACE_DATA_SYNC_ENABLED_FIELDS':(*FLAGS['RACE_DATA_SYNC_ENABLED_FIELDS'],'participants.odds','participants.status')}):
                self.assertEqual(dynamic_rows(e,items,now=later)[0].odds_value,'')
    def test_scratches_sticky_and_partial_roster_rejected(self):
        from stable.services.race_pre_race_refresh import stamp_dynamic_items
        old=[dict(horse_name='A',horse_number='1',running_status='scratched'),dict(horse_name='B',horse_number='2',running_status='declared')]
        fresh=[dict(horse_name='A',horse_number='1',running_status='declared'),old[1]]
        self.assertEqual(stamp_dynamic_items(fresh,old,now=NOW,source_url=URL)[0]['running_status'],'scratched')
        with self.assertRaises(ValueError):stamp_dynamic_items(fresh[:1],old,now=NOW,source_url=URL)

from pathlib import Path
from types import SimpleNamespace
FIXTURES=Path(__file__).parent/'tests/fixtures/pre_race_refresh'
NYRA_URL='https://www.nyra.com/belmont/racing/entries/?day=2026-09-18&limit=entries&race=5'
SL_URL='https://www.sportinglife.com/racing/racecards/2026-09-18/belmont-park/racecard/939662/race-5-jockey-club-gold-cup-stakes-grade-1'

class SourceParserTests(TestCase):
    def test_real_nyra_three_scratches(self):
        from stable.services.race_pre_race_sources import parse_bound_card
        e=SimpleNamespace(local_date=date(2026,9,18),timezone_name='America/New_York')
        items=parse_bound_card((FIXTURES/'nyra.html').read_text(),event=e,url=NYRA_URL)['items']
        self.assertEqual(len(items),7)
        self.assertEqual([r['horse_number'] for r in items if r['running_status']=='scratched'],['3','5','6'])
        self.assertEqual(items[-1]['horse_name'],'Forever Young')
    def test_existing_sporting_zeturf_and_nar_fixtures(self):
        from stable.services.race_pre_race_sources import parse_bound_card
        cases=[('sl-491.html',SL_URL,date(2026,9,18),'America/New_York','Belmont Park',7),
            ('zt-770.html','https://www.zeturf.fr/fr/course-du-jour/2026-09-19/R1C3-chantilly-prix-eclipse',date(2026,9,19),'Europe/Paris','Chantilly',7),
            ('nar.html','https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_babaCode=22&k_raceDate=2026%2F09%2F22&k_raceNo=11',date(2026,9,22),'Asia/Tokyo','金沢',12)]
        for filename,url,day,zone,course,count in cases:
            with self.subTest(filename=filename):
                e=SimpleNamespace(local_date=day,timezone_name=zone,racecourse=course)
                items=parse_bound_card((FIXTURES/filename).read_text(),event=e,url=url)['items']
                self.assertEqual(len(items),count)
                self.assertTrue(all(r['horse_number'] for r in items))
    def test_truncated_wrong_date_and_unsafe_urls(self):
        from stable.services.race_pre_race_sources import parse_bound_card
        from stable.services.race_pre_race_refresh import validate_bound_url
        e=SimpleNamespace(local_date=date(2026,9,18),timezone_name='America/New_York')
        html=(FIXTURES/'nyra.html').read_text()
        for body in (html[:-7],html.replace('Friday, September 18','Saturday, September 19')):
            with self.assertRaises(ValueError):parse_bound_card(body,event=e,url=NYRA_URL)
        for url in (NYRA_URL.replace('www.nyra.com','127.0.0.1'),NYRA_URL+'&redirect=https://evil.test',NYRA_URL.replace('www.nyra.com','user@www.nyra.com'),SL_URL+'?next=x'):
            with self.assertRaises(ValueError):validate_bound_url(url)

REFRESH_FLAGS={**FLAGS,'RACE_DATA_SYNC_PRE_RACE_REFRESH_ENABLED':True,'RACE_DATA_SYNC_ENABLED_REGIONS':('united_states',),
    'RACE_DATA_SYNC_ENABLED_FIELDS':tuple(pre.PUBLIC_FIELDS.values())}
@override_settings(**REFRESH_FLAGS)
class BoundRefreshTests(TestCase):
    def setUp(self):
        from stable.services.race_pre_race_sources import parse_bound_card
        from stable.services.race_pre_race_refresh import _digest
        self.now=datetime(2026,9,18,18,tzinfo=tz.utc)
        self.e=models.RaceEvent.objects.create(year=2026,slug='gold',original_name='JOCKEY CLUB GOLD CUP S.',chinese_name='赛马会金杯',visibility_status='published',country_region='united_states',racecourse='贝蒙园',timezone_name='America/New_York',local_date=date(2026,9,18),local_start_time=time(16,14),race_datetime=datetime(2026,9,18,20,14,tzinfo=tz.utc))
        items=parse_bound_card((FIXTURES/'sl-491.html').read_text(),event=self.e,url=SL_URL)['items']
        self.original=models.RaceEventDataCandidate.objects.create(event=self.e,module='runners',source_name=pre.REVIEWED_PRE_RACE,source_url=SL_URL,candidate_payload={'items':items},fetched_at=self.now-timedelta(hours=12),raw_payload={pre.REVIEWED_PRE_RACE:dict(validated=True,baseline=pre.baseline(self.e),authority='human_reviewed_reference',stage='numbered',row_count=len(items),items_sha256=_digest(items))})
        self.e.source_refs={'pre_race_refresh_binding':dict(url=NYRA_URL,baseline=pre.baseline(self.e),reviewed_candidate_id=self.original.pk)};self.e.save()
    def test_two_due_ticks_actual_public_changes_and_old_candidate_immutable(self):
        from stable.services.race_pre_race_refresh import discover_bound_pre_race,public_refresh_preview
        html=(FIXTURES/'nyra.html').read_text()
        for tick in (self.now,self.now+timedelta(minutes=10)):
            with patch('stable.services.race_pre_race_refresh.fetch_bound_html',return_value=html) as fetch:
                out=discover_bound_pre_race(now=tick,clock=lambda:tick)
                self.assertEqual(out['checked'],1);fetch.assert_called_once()
        self.e.refresh_from_db()
        preview=public_refresh_preview(self.e,now=self.now+timedelta(minutes=10))
        self.assertEqual([r.horse_number for r in preview['rows'] if r.running_status=='scratched'],['3','5','6'])
        self.assertTrue(preview['rows'][0].odds_value)
        self.original.refresh_from_db();self.assertEqual(self.original.candidate_payload['items'][2]['running_status'],'declared')
        with override_settings(RACE_DATA_SYNC_PRE_RACE_REFRESH_ENABLED=False),patch('django.utils.timezone.now',return_value=self.now+timedelta(minutes=10)):
            response=self.client.get(self.e.public_path)
            self.assertContains(response,'退赛',count=3)
            self.assertNotContains(response,'人工核验')
            self.assertContains(response,'出马表')
        self.assertFalse(self.e.runners.exists())
    def test_stop_during_fetch_and_managed_handoff_no_write(self):
        from stable.services.race_pre_race_refresh import binding_for,complete_refresh,discover_bound_pre_race
        claim=pre.claim_pre_race(event_id=self.e.pk,source=pre.REFRESH,now=self.now);claim['binding']=binding_for(self.e)
        with override_settings(RACE_DATA_SYNC_PRE_RACE_REFRESH_ENABLED=False):
            self.assertFalse(complete_refresh(claim,html=(FIXTURES/'nyra.html').read_text(),url=NYRA_URL,now=self.now))
        models.RaceEventProjectionControl.objects.create(event=self.e,write_owner='data_sync')
        with patch('stable.services.race_pre_race_refresh.fetch_bound_html') as fetch:
            self.assertEqual(discover_bound_pre_race(now=self.now,clock=lambda:self.now)['attempted'],0);fetch.assert_not_called()
        self.assertEqual(self.e.data_candidates.count(),1)
    def test_auto_candidate_generic_apply_rejected_and_old_lease_rejected(self):
        from stable.services.race_pre_race_refresh import binding_for,complete_refresh
        from stable.services.race_events import apply_data_candidate
        claim=pre.claim_pre_race(event_id=self.e.pk,source=pre.REFRESH,now=self.now);claim['binding']=binding_for(self.e)
        self.assertFalse(complete_refresh(claim,html=(FIXTURES/'nyra.html').read_text(),url=NYRA_URL,now=self.now+timedelta(seconds=121)))
        newer=pre.claim_pre_race(event_id=self.e.pk,source=pre.REFRESH,now=self.now+timedelta(seconds=121));newer['binding']=binding_for(self.e)
        self.assertTrue(complete_refresh(newer,html=(FIXTURES/'nyra.html').read_text(),url=NYRA_URL,now=self.now+timedelta(seconds=122)))
        c=self.e.data_candidates.get(source_name=pre.REFRESH);c.source_name='renamed';c.save()
        with self.assertRaisesRegex(ValueError,'controlled_path'):apply_data_candidate(c)

class CalendarPagingTests(BeijingContractTests):
    def test_default_window_overflow_is_reachable_and_bad_cursor_returns_default(self):
        from urllib.parse import urlsplit,parse_qs
        from django.core import signing
        now=datetime(2026,9,18,18,tzinfo=tz.utc)
        for i in range(41):self.make(f'r{i}',timezone_name='Asia/Shanghai',local_date=date(2026,9,19),local_start_time=time(4,i),race_datetime=datetime(2026,9,18,20,i,tzinfo=tz.utc))
        self.make('tomorrow',timezone_name='Asia/Shanghai',local_date=date(2026,9,20),local_start_time=time(4),race_datetime=datetime(2026,9,19,20,tzinfo=tz.utc))
        self.make('ancient',timezone_name='Asia/Shanghai',local_date=date(2020,1,1),local_start_time=time(4),race_datetime=datetime(2019,12,31,20,tzinfo=tz.utc),year=2020)
        def ids(r):return [e.pk for g in r.context['groups'] for e in g['events']]
        with patch('django.utils.timezone.now',return_value=now):
            first=self.client.get('/races/',{'tab':'all'})
            current=first;seen=ids(first)
            for _ in range(5):
                url=current.context['next_url']
                if not url:break
                current=self.client.get(url);seen+=ids(current)
            self.assertEqual(len(seen),len(set(seen)))
            self.assertEqual(set(seen),set(models.RaceEvent.objects.exclude(slug='ancient').values_list('pk',flat=True)))
            self.assertContains(self.client.get(first.context['previous_url']),'ancient')
            for token in ('invalid',signing.dumps({'v':1},salt='stable.public-race-calendar.cursor.v1')):
                r=self.client.get('/races/',{'tab':'all','cursor':token,'direction':'future'})
                self.assertEqual(ids(r),ids(first))

class AdditionalDynamicTests(TestCase):
    def test_shared_snapshot_keeps_actual_price_observation_time(self):
        from stable.services.race_pre_race_refresh import stamp_dynamic_items
        row=dict(horse_number='1',horse_name='A',odds_value='4.2',odds_kind='current',odds_format='decimal')
        later=NOW+timedelta(minutes=2)
        items=stamp_dynamic_items([row],[],now=later,observed_at=NOW,source_url=URL)
        self.assertEqual(items[0]['odds_observed_at'],NOW.isoformat())
    @override_settings(**REFRESH_FLAGS)
    def test_refresh_http_shares_budget_no_redirect_and_preserves_snapshot_time(self):
        from stable.services.race_pre_race_refresh import fetch_bound_html
        # Mock only transport; run the shared fetch callback and host reservation path.
        from unittest.mock import MagicMock
        response=MagicMock();response.status_code=200;response.headers={'Content-Type':'text/html'}
        response.iter_content.return_value=[b'<html><body></body></html>'];response.__enter__.return_value=response
        reservation=SimpleNamespace(reserved=True,reservation_version=1)
        captured=[]
        def shared(**kw):
            captured.append(kw)
            return kw['fetcher']()[0],'a'*64
        with patch('stable.services.race_data_sync_providers._get_or_fetch_shared_snapshot',side_effect=shared),patch('stable.services.race_events.ensure_race_live_host_budget_floor'),patch('stable.services.race_events.reserve_race_live_host_request',return_value=reservation),patch('stable.services.race_events.record_race_live_host_outcome'),patch('requests.get',return_value=response) as get,patch('django.utils.timezone.now',return_value=NOW):
            page=fetch_bound_html(NYRA_URL,now=NOW,region='united_states')
            self.assertEqual(page.observed_at,NOW)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertEqual(captured[0]['provider'],'nyra')
            self.assertEqual(captured[0]['region'],'united_states')
    @override_settings(**FLAGS)
    def test_jra_stopped_claim_cannot_revive_when_reenabled(self):
        e=event();claim=pre.claim_pre_race(event_id=e.pk,source=pre.JRA,now=NOW)
        with override_settings(RACE_DATA_SYNC_JRA_PRE_RACE_ENABLED=False):self.assertFalse(pre.complete_jra(claim,html=HTML,url=URL,now=NOW))
        self.assertFalse(pre.complete_jra(claim,html=HTML,url=URL,now=NOW))

class PollOutcomeTests(TestCase):
    def test_identity_miss_is_recorded_without_claiming_card_freshness_or_failure_backoff(self):
        e=event()
        claim=pre.claim_pre_race(event_id=e.pk,source=pre.TRA,now=NOW)
        pre.finish_pre_race(claim,now=NOW+timedelta(seconds=7),outcome_reason='course_not_found')
        e.refresh_from_db();state=pre._state(e,pre.TRA)
        self.assertEqual(state['reason'],'course_not_found')
        self.assertEqual(state['failures'],0)
        self.assertEqual(pre._dt(state['next_poll_at']),NOW+timedelta(hours=3,minutes=-3))
        self.assertFalse(pre._state(e,pre.REFRESH))

class RacingPostContractTests(TestCase):
    def test_observed_dom_contract_and_forecast_not_live(self):
        from stable.services.race_pre_race_sources import parse_bound_card
        e=SimpleNamespace(local_date=date(2026,9,19),timezone_name='America/New_York')
        for eid,rid,count in [(494,928918,9),(495,928919,11)]:
            html=(FIXTURES/f'rp-{eid}.html').read_text();url=f'https://www.racingpost.com/racecards/578/parx/2026-09-19/{rid}/'
            rows=parse_bound_card(html,event=e,url=url)['items']
            self.assertEqual(len(rows),count)
            self.assertEqual(rows[0]['odds_kind'],'forecast')
            self.assertEqual(rows[0]['odds_value'],'15/2')
            self.assertEqual(rows[1]['odds_value'],'')
            with self.assertRaises(ValueError):parse_bound_card(html.replace(f'race-id={rid}/','race-id=1/'),event=e,url=url)

class BeijingEdgeTests(TestCase):
    def test_dst_crossyear_missing_and_invalid_input_contract(self):
        from stable.services.race_public_time import public_time,annotate_public_time
        values=[
            (date(2026,11,1),time(1,30),'America/New_York',datetime(2026,11,1,5,30,tzinfo=tz.utc)),
            (date(2026,11,1),time(1,30),'America/New_York',datetime(2026,11,1,6,30,tzinfo=tz.utc)),
            (date(2026,3,8),time(2,30),'America/New_York',None),
            (date(2026,12,31),time(23),'Asia/Shanghai',None),
            (date(1990,1,1),time(23),'Asia/Shanghai',None),
            (date(2026,9,18),None,'Asia/Tokyo',None),
        ]
        for i,(day,clock,zone,instant) in enumerate(values):
            e=models.RaceEvent.objects.create(year=day.year,slug=f'edge{i}',local_date=day,local_start_time=clock,timezone_name=zone,race_datetime=instant)
            actual=annotate_public_time(models.RaceEvent.objects.filter(pk=e.pk)).get()
            stamp=public_time(e)
            self.assertEqual((actual.public_date,actual.public_start_time),(stamp.day,stamp.clock))
        first=public_time(models.RaceEvent.objects.get(slug='edge0'));second=public_time(models.RaceEvent.objects.get(slug='edge1'))
        self.assertEqual(first.clock,time(13,30));self.assertEqual(second.clock,time(14,30))
        self.assertIsNone(public_time({'race_datetime':datetime(2026,9,18),'timezone_name':'Asia/Shanghai'}).instant)
    def test_day_only_kept_last_and_null_group_has_forward_backward_paging(self):
        from stable.services.race_calendar import encode_race_calendar_cursor
        factory=BeijingContractTests.make
        early=factory(self,'early',timezone_name='Asia/Shanghai',local_date=date(2026,9,19),local_start_time=time(3),race_datetime=datetime(2026,9,18,19,tzinfo=tz.utc))
        late=factory(self,'unknown-time',timezone_name='Asia/Shanghai',local_date=date(2026,9,19),local_start_time=None,race_datetime=None)
        unknown=factory(self,'unknown-day',local_start_time=None,race_datetime=None)
        filters=dict(tab='all',region='',year='',q='unknown',grade='',when='')
        cursor=encode_race_calendar_cursor(unknown,filters=filters)
        r=self.client.get('/races/',{**filters,'cursor':cursor,'direction':'past'})
        self.assertEqual([e.pk for g in r.context['groups'] for e in g['events']],[late.pk])

class SportingLiveContractTests(TestCase):
    """上线预演发现的真实来源合同：UTC日期、退赛后的有效出走数。"""
    def card(self, *, source_day='2026-09-18', ride_count=4):
        import json
        from stable.race_reference_parsers.sporting_life import _next_data
        payload=_next_data((FIXTURES/'sl-491.html').read_text())
        race=payload['props']['pageProps']['race']
        race['race_summary'].update(date=source_day,ride_count=ride_count)
        for ride in race['rides']:
            ride['ride_status']='NONRUNNER' if ride['cloth_number'] in (3,5,6) else 'RUNNER'
        return '<html><body><script id="__NEXT_DATA__" type="application/json">'+json.dumps(payload)+'</script></body></html>'
    def test_active_count_keeps_all_seven_rows_and_three_scratches(self):
        from stable.services.race_pre_race_sources import parse_bound_card
        e=SimpleNamespace(local_date=date(2026,9,18),timezone_name='America/New_York')
        rows=parse_bound_card(self.card(),event=e,url=SL_URL)['items']
        self.assertEqual(len(rows),7)
        self.assertEqual([r['horse_number'] for r in rows if r['running_status']=='scratched'],['3','5','6'])
    def test_source_utc_day_may_be_next_day_with_exact_event_instant(self):
        from stable.services.race_pre_race_sources import parse_bound_card
        e=SimpleNamespace(local_date=date(2026,9,18),timezone_name='America/New_York',race_datetime=datetime(2026,9,19,0,36,tzinfo=tz.utc))
        rows=parse_bound_card(self.card(source_day='2026-09-19',ride_count=7),event=e,url=SL_URL)['items']
        self.assertEqual(len(rows),7)
        for instant in (None,datetime(2026,9,18,20,14,tzinfo=tz.utc)):
            e.race_datetime=instant
            with self.assertRaises(ValueError):parse_bound_card(self.card(source_day='2026-09-19',ride_count=7),event=e,url=SL_URL)
    def test_inconsistent_count_remains_rejected(self):
        from stable.services.race_pre_race_sources import parse_bound_card
        e=SimpleNamespace(local_date=date(2026,9,18),timezone_name='America/New_York')
        with self.assertRaises(ValueError):parse_bound_card(self.card(ride_count=5),event=e,url=SL_URL)


@override_settings(**REFRESH_FLAGS,
    RACE_DATA_RAW_MAX_COMPRESSED_BYTES=2*1024*1024,
    RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8*1024*1024,
    RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=1024*1024*1024,
    RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=512,
    RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=1024*1024*1024,
    RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=512*1024*1024,
    RACE_DATA_RAW_MIN_FREE_DISK_BYTES=1,
    RACE_DATA_RAW_CLEANUP_MAX_ROWS=100,
    RACE_DATA_RAW_CLEANUP_MAX_BYTES=64*1024*1024,
    RACE_DATA_RAW_HOLD_ALERT_BYTES=256*1024*1024)
class LongBoundSourceIntegrationTests(TestCase):
    def setUp(self):
        BoundRefreshTests.setUp(self)

    def test_long_source_url_runs_real_snapshot_pipeline_and_keeps_cache_isolation(self):
        import tempfile
        from unittest.mock import MagicMock
        from stable.services.race_pre_race_refresh import discover_bound_pre_race, fetch_bound_html, public_refresh_preview
        # Production URLs were 140/154 characters; the original fixture was exactly 128.
        long_url=SL_URL+'-extended-source-title'
        self.assertGreater(len(long_url),128)
        self.original.source_url=long_url;self.original.save(update_fields=['source_url'])
        self.e.source_refs={};self.e.save(update_fields=['source_refs'])
        body=SportingLiveContractTests().card().encode()
        response=MagicMock(status_code=200,headers={'Content-Type':'text/html'})
        response.__enter__.return_value=response;response.iter_content.return_value=[body]
        with tempfile.TemporaryDirectory() as root, override_settings(RACE_DATA_RAW_ARTIFACT_ROOTS=(root,)), patch('requests.get',return_value=response) as get, patch('django.utils.timezone.now',return_value=self.now):
            outcome=discover_bound_pre_race(now=self.now,clock=lambda:self.now)
            self.assertEqual(outcome,{'checked':1,'attempted':1})
            first=fetch_bound_html(long_url,now=self.now,region='united_states')
            self.assertEqual(get.call_count,1)
            self.assertEqual(first.observed_at,self.now)
            # An alternate long URL must not reuse the first URL's payload.
            with patch('django.utils.timezone.now',return_value=self.now+timedelta(seconds=3)):
                fetch_bound_html(long_url+'-another',now=self.now+timedelta(seconds=3),region='united_states')
            self.assertEqual(get.call_count,2)
            self.assertEqual(get.call_args.args[0],long_url+'-another')
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertEqual(models.RaceDataSnapshotLease.objects.filter(state='complete').count(),2)
            ledger=models.RaceDataTransportCapacityLedger.objects.get(provider='sporting_life',region_code='united_states',usage_date=self.now.date())
            self.assertEqual(ledger.request_count,2)
        self.e.refresh_from_db()
        rows=public_refresh_preview(self.e,now=self.now)['rows']
        self.assertEqual(len(rows),7)
        self.assertEqual([r.horse_number for r in rows if r.running_status=='scratched'],['3','5','6'])
        candidate=self.e.data_candidates.get(source_name=pre.REFRESH)
        self.assertEqual(candidate.source_url,long_url)
        self.assertEqual(candidate.raw_payload[pre.REFRESH]['binding']['url'],long_url)

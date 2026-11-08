"""HKJC 真实来源回归；所有输入为离线固定页面。"""
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from django.test import SimpleTestCase
from stable.services.race_data_source_adapters import SourceRoute, parse_hkjc_observation

ROOT = Path(__file__).parent / 'fixtures/hkjc_automation'
NOW = datetime(2026, 11, 8, 17, tzinfo=timezone.utc)


def route():
    return SourceRoute(dict(provider='hkjc', operator='hkjc', region='hong_kong',
        identity_namespace='hkjc-race-v1', allowed_hosts=['racing.hkjc.com', 'campaigns.hkjc.com'],
        allowed_path_prefixes=['/en-us/local/information/', '/racing-event-hub-hkir/en/'],
        venue_aliases={'hkjc:ST':['Sha Tin','沙田'], 'hkjc:HV':['Happy Valley','跑马地']},
        timezone='Asia/Hong_Kong', parser_version='test', valid_from='2026-01-01T00:00:00Z', valid_until='2028-01-01T00:00:00Z'), 'a'*64)


class HKJCRealSourceTests(SimpleTestCase):
    def result(self, file='result.html', day='2026/11/08'):
        return parse_hkjc_observation((ROOT/file).read_text(),
            url=f'https://racing.hkjc.com/en-us/local/information/localresults?racedate={day}&Racecourse=ST&RaceNo=8',
            route=route(), now=NOW)

    def test_result_incident_table_is_not_another_result_table(self):
        value=self.result()
        self.assertEqual(len(value['roster']),13)
        self.assertIn("LADIES' PURSE",value['raw_names'][0])
        self.assertTrue(value['roster'][0]['carried_weight'].endswith('lb'))
        self.assertTrue(value['roster'][0]['odds_value'])

    def test_withdrawal_is_retained_without_finish_position(self):
        value=self.result('result-withdrawn.html','2026/10/19')
        withdrawn=next(r for r in value['roster'] if r['number']=='4')
        self.assertEqual(withdrawn['status'],'withdrawn')
        self.assertIsNone(withdrawn['reported_finish_position'])
        self.assertEqual(len(value['roster']),12)

    def test_card_has_real_time_and_excludes_standby_and_repeated_header(self):
        value=parse_hkjc_observation((ROOT/'card.html').read_text(),
            url='https://racing.hkjc.com/en-us/local/information/racecard?racedate=2026/11/08&Racecourse=ST&RaceNo=8',
            route=route(),now=NOW)
        self.assertEqual(len(value['roster']),13)
        self.assertFalse(value['result_phase'])
        self.assertTrue(value['off_time'].endswith('+08:00'))

    def test_nominations_validate_date_total_and_country_counts(self):
        from stable.services.hkjc_sources import parse_nominations
        event=SimpleNamespace(local_date=date(2026,12,13),original_name='LONGINES Hong Kong Cup',chinese_name='',racecourse='Sha Tin')
        page=(ROOT/'nominations.html').read_text()
        value=parse_nominations(page,event=event,url='https://campaigns.hkjc.com/racing-event-hub-hkir/en/hkcup-racing-info')
        self.assertEqual(value['stage'],'registration')
        self.assertEqual(len(value['items']),72)
        self.assertTrue(all(not r['horse_number'] and not r['barrier'] for r in value['items']))
        for broken in [page.replace('Entries: 72','Entries: 73'),page.replace('AUS (2)','AUS (3)'),page.replace('13 Dec 2026','13 Dec 2025')]:
            with self.subTest():
                with self.assertRaises(ValueError):parse_nominations(broken,event=event,url='https://campaigns.hkjc.com/racing-event-hub-hkir/en/hkcup-racing-info')

    def test_source_code_is_not_limited_to_acceptance_year(self):
        from stable.services.hkjc_sources import parse_nominations
        page=(ROOT/'nominations.html').read_text().replace('2026','2027')
        event=SimpleNamespace(local_date=date(2027,12,13),original_name='LONGINES Hong Kong Cup',chinese_name='',racecourse='Sha Tin')
        value=parse_nominations(page,event=event,url='https://campaigns.hkjc.com/racing-event-hub-hkir/en/hkcup-racing-info')
        self.assertEqual(len(value['items']),72)

    def test_result_missing_row_or_wrong_meeting_is_rejected(self):
        from bs4 import BeautifulSoup
        page=(ROOT/'result.html').read_text()
        soup=BeautifulSoup(page,'html.parser')
        soup.select_one('table.draggable').select('tbody tr')[-1].decompose()
        base='https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/11/08&Racecourse=ST&RaceNo=8'
        for raw,url in [(str(soup),base),(page,base.replace('RaceNo=8','RaceNo=7')),
                        (page,base.replace('Racecourse=ST','Racecourse=HV'))]:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):parse_hkjc_observation(raw,url=url,route=route(),now=NOW)

    def test_full_day_results_are_discovery_only(self):
        from stable.services.hkjc_sources import meeting_races
        rows=meeting_races((ROOT/'meeting-results.html').read_text(),
            url='https://racing.hkjc.com/en-us/local/information/resultsall?racedate=2026/11/08&Racecourse=ST')
        self.assertEqual(len(rows),11)
        selected=[r for r in rows if 'LADIES' in r['description']]
        self.assertEqual([r['race_number'] for r in selected],['8'])
        self.assertIn('localresults?',selected[0]['url'])
        self.assertTrue(all('roster' not in r for r in rows))

    def test_expired_card_does_not_reuse_other_day(self):
        with self.assertRaises(ValueError):
            parse_hkjc_observation((ROOT/'card-expired.html').read_text(),
                url='https://racing.hkjc.com/en-us/local/information/racecard?racedate=2026/09/06&Racecourse=ST&RaceNo=3',
                route=route(),now=NOW)

    def test_local_entries_keep_reserves_without_inventing_numbers(self):
        from stable.services.hkjc_sources import parse_entries
        event=SimpleNamespace(local_date=date(2026,11,11),original_name='B HANDICAP',chinese_name='',racecourse='Happy Valley')
        value=parse_entries((ROOT/'entries.html').read_text(),event=event,
            url='https://racing.hkjc.com/en-us/local/information/entries?racedate=2026/11/11&Racecourse=HV&View=All')
        self.assertEqual(value['stage'],'registration')
        self.assertEqual(len(value['items']),19)
        self.assertEqual(sum(r['source_refs']['selection_status']=='reserve' for r in value['items']),7)
        self.assertTrue(all(not r['horse_number'] and not r['barrier'] for r in value['items']))

    def test_automatic_result_discovery_uses_full_race_detail(self):
        from stable.services.hkjc_sources import discover_result_url
        event=SimpleNamespace(local_date=date(2026,11,8),original_name="Sa Sa Ladies’ Purse (H)",chinese_name='',racecourse='Sha Tin')
        url=discover_result_url(event=event,route=route(),now=NOW,
            fetcher=lambda *a,**kw:(ROOT/'meeting-results.html').read_text())
        self.assertTrue(url.endswith('RaceNo=8'))
        self.assertIn('localresults',url)

    def test_automatic_nomination_fallback_after_explicit_not_published(self):
        from stable.services.hkjc_pre_race import fetch_hkjc_pre_race
        r=route();r.payload['discovery_urls']=['https://campaigns.hkjc.com/racing-event-hub-hkir/en/']
        event=SimpleNamespace(local_date=date(2026,12,13),original_name='LONGINES Hong Kong Cup',chinese_name='',racecourse='Sha Tin')
        def fetch(url,**kwargs):
            if '/racecard?' in url:return (ROOT/'card-expired.html').read_text()
            if '/entries?' in url:return (ROOT/'entries-unpublished.html').read_text()
            if url.endswith('hkcup-racing-info'):return (ROOT/'nominations.html').read_text()
            return '<a href="hkcup-racing-info">Cup</a>'
        url,page,payload=fetch_hkjc_pre_race(event=event,route=r,now=NOW,fetcher=fetch)
        self.assertEqual(len(payload['items']),72)
        self.assertEqual(payload['stage'],'registration')
        def broken(url,**kwargs):
            return '<html>503 Service Unavailable</html>' if '/entries?' in url else fetch(url,**kwargs)
        with self.assertRaisesMessage(ValueError,'hkjc_entries_page_missing'):
            fetch_hkjc_pre_race(event=event,route=r,now=NOW,fetcher=broken)

    def test_pattern_schedule_keeps_happy_valley_january_cup(self):
        from unittest.mock import patch,MagicMock
        from stable.services.hkjc_sources import parse_pattern_schedule
        document=MagicMock();document.__enter__.return_value.pages=[SimpleNamespace(extract_text=lambda:
            'SCHEDULE OF RACES Race Date\n06/01/27 January Cup (H) G3 4,200,000 3yo+ 1800 07/12/26')]
        with patch('pdfplumber.open',return_value=document):rows=parse_pattern_schedule(b'fixture')
        self.assertEqual(rows[0]['racecourse'],'Happy Valley')


from django.test import TestCase, override_settings
from stable.test_race_pre_race import FLAGS


@override_settings(**{**FLAGS, 'RACE_DATA_SYNC_HKJC_PRE_RACE_ENABLED':True,
    'RACE_DATA_SYNC_HKJC_PRE_RACE_DAYS':45,'RACE_DATA_SYNC_ENABLED_PROVIDERS':('hkjc',),
    'RACE_DATA_SYNC_ENABLED_REGIONS':('hong_kong',)})
class HKJCPreviewWorkflowTests(TestCase):
    def setUp(self):
        from stable import models
        self.event=models.RaceEvent.objects.create(year=2026,slug='hkjc-cup-test',
            original_name='LONGINES Hong Kong Cup',country_region='hong_kong',racecourse='Sha Tin',
            local_date=date(2026,12,13),timezone_name='Asia/Hong_Kong',status='scheduled',visibility_status='published')

    def test_claim_store_public_preview_and_unchanged_replay(self):
        from stable.services import race_pre_race as pre
        from stable.services.hkjc_pre_race import complete, public_hkjc_preview
        from stable.services.hkjc_sources import parse_nominations
        from datetime import timedelta
        url='https://campaigns.hkjc.com/racing-event-hub-hkir/en/hkcup-racing-info'
        page=(ROOT/'nominations.html').read_text();payload=parse_nominations(page,event=self.event,url=url)
        for now in (NOW,NOW+timedelta(hours=4)):
            claim=pre.claim_pre_race(event_id=self.event.pk,source='hkjc_pre_race_v1',now=now)
            self.assertIsNotNone(claim)
            self.assertTrue(complete(claim,payload=payload,url=url,page=page,route=route(),now=now))
        self.event.refresh_from_db()
        preview=public_hkjc_preview(self.event,now=NOW+timedelta(hours=4))
        self.assertEqual(preview['label'],'报名名单')
        self.assertEqual(len(preview['rows']),72)
        self.assertEqual(self.event.data_candidates.count(),1)
        self.assertFalse(self.event.runners.exists())

    def test_disabled_claim_and_stale_or_finished_preview_are_hidden(self):
        from stable.services import race_pre_race as pre
        from stable.services.hkjc_pre_race import public_hkjc_preview
        with override_settings(RACE_DATA_SYNC_HKJC_PRE_RACE_ENABLED=False):
            self.assertIsNone(pre.claim_pre_race(event_id=self.event.pk,source='hkjc_pre_race_v1',now=NOW))
        self.event.status='finished';self.event.save()
        self.assertIsNone(public_hkjc_preview(self.event,now=NOW))

    def test_registration_replaced_by_numbered_and_never_downgraded(self):
        from datetime import timedelta
        from stable.services import race_pre_race as pre
        from stable.services.hkjc_pre_race import complete,public_hkjc_preview
        from stable.services.hkjc_sources import parse_nominations
        url='https://campaigns.hkjc.com/racing-event-hub-hkir/en/hkcup-racing-info'
        page=(ROOT/'nominations.html').read_text();registration=parse_nominations(page,event=self.event,url=url)
        card=parse_hkjc_observation((ROOT/'card.html').read_text(),url='https://racing.hkjc.com/en-us/local/information/racecard?racedate=2026/11/08&Racecourse=ST&RaceNo=8',route=route(),now=NOW)
        numbered=dict(stage='numbered',items=[dict(horse_name=r['horse_name'],horse_number=r['number'],
            barrier=r['barrier'],jockey_name=r['jockey_name'],trainer_name=r['trainer_name'],carried_weight=r['carried_weight'],running_status=r['status']) for r in card['roster']])
        for index,payload in enumerate((registration,numbered,registration)):
            now=NOW+timedelta(hours=index*4)
            claim=pre.claim_pre_race(event_id=self.event.pk,source='hkjc_pre_race_v1',now=now)
            self.assertEqual(complete(claim,payload=payload,url=url,page=page,route=route(),now=now),index!=2)
        self.event.refresh_from_db()
        preview=public_hkjc_preview(self.event,now=now)
        self.assertEqual(len(preview['rows']),13)
        self.assertEqual(self.event.data_candidates.count(),2)
        self.event.original_name='Different race';self.event.save()
        self.assertIsNone(public_hkjc_preview(self.event,now=now))

    def test_hkjc_result_bound_path_accepts_independent_incident_roster(self):
        from stable.services.race_data_source_adapters import fetch_bound_observation
        self.event.local_date=date(2026,11,8);self.event.original_name="THE SA SA LADIES' PURSE (HANDICAP)"
        self.event.save()
        url='https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/11/08&Racecourse=ST&RaceNo=8'
        value=fetch_bound_observation(event=self.event,route=route(),now=NOW,url_hint=url,
            fetcher=lambda *a,**kw:(ROOT/'result.html').read_text())
        self.assertTrue(value['roster_complete'])
        self.assertEqual(value['roster_evidence']['row_count'],13)

    def test_manual_lock_blocks_candidate_and_expired_lease_cannot_commit(self):
        from datetime import timedelta
        from stable.services import race_pre_race as pre
        from stable.services.hkjc_pre_race import complete
        self.event.manual_lock_flags={'runners':True};self.event.save()
        claim=pre.claim_pre_race(event_id=self.event.pk,source='hkjc_pre_race_v1',now=NOW)
        self.assertFalse(complete(claim,payload={'stage':'registration'},url='https://racing.hkjc.com',page='',route=route(),now=NOW))
        self.assertEqual(self.event.data_candidates.count(),0)
        self.event.manual_lock_flags={};self.event.save()
        claim=pre.claim_pre_race(event_id=self.event.pk,source='hkjc_pre_race_v1',now=NOW+timedelta(hours=4))
        self.assertFalse(complete(claim,payload={'stage':'registration'},url='https://racing.hkjc.com',page='',route=route(),now=NOW+timedelta(hours=4,minutes=3)))

    def test_registration_cannot_be_applied_as_formal_runners_in_console(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        from stable import models
        user=get_user_model().objects.create_superuser(username='hkjc-test',password='synthetic-local-only')
        self.client.force_login(user)
        candidate=models.RaceEventDataCandidate.objects.create(event=self.event,module='runners',
            source_name='hkjc_pre_race_v1',raw_payload={'hkjc_pre_race_v1':{'validated':True}},
            candidate_payload={'items':[{'horse_name':'Entry without official number'}]})
        self.client.post(reverse('console-race-event-apply-candidate',args=[candidate.pk]))
        candidate.refresh_from_db()
        self.assertEqual(candidate.status,'pending')
        self.assertFalse(self.event.runners.exists())

    def test_only_numbered_official_card_can_seed_source_identity(self):
        from stable import models
        from stable.services.race_pre_race import baseline
        from stable.services.race_source_identity import seed_evidence
        candidate=models.RaceEventDataCandidate.objects.create(event=self.event,module='runners',
            source_name='hkjc_pre_race_v1',source_url='https://racing.hkjc.com/en-us/local/information/racecard?racedate=2026/12/13&Racecourse=ST&RaceNo=8',
            raw_payload={'hkjc_pre_race_v1':{'validated':True,'baseline':baseline(self.event),'stage':'registration','raw_sha256':'a'*64}},
            candidate_payload={'items':[{'horse_name':'Example','horse_number':'1'}]})
        self.assertIsNone(seed_evidence(self.event,route=route()))
        candidate.raw_payload['hkjc_pre_race_v1']['stage']='numbered';candidate.save()
        self.assertIsNotNone(seed_evidence(self.event,route=route()))

    def test_identity_discovery_keeps_card_when_result_not_yet_published(self):
        from datetime import timedelta
        from stable.services.race_data_source_adapters import fetch_bound_observation
        self.event.local_date=date(2026,11,8);self.event.original_name="THE SA SA LADIES' PURSE (HANDICAP)";self.event.save()
        url='https://racing.hkjc.com/en-us/local/information/racecard?racedate=2026/11/08&Racecourse=ST&RaceNo=8'
        requested=[]
        def fetch(url,**kwargs):
            requested.append(url)
            return (ROOT/'card.html').read_text() if '/racecard?' in url else '<html>No information.</html>'
        value=fetch_bound_observation(event=self.event,route=route(),now=NOW-timedelta(hours=12),url_hint=url,fetcher=fetch)
        self.assertEqual(value['result_phase'],'')
        self.assertEqual(len(value['roster']),13)
        self.assertFalse(any('/localresults?' in u for u in requested))

    def test_new_undated_local_entries_replace_dated_international_nominations(self):
        from datetime import timedelta
        from stable.services import race_pre_race as pre
        from stable.services.hkjc_pre_race import complete
        from stable.services.hkjc_sources import parse_nominations
        url='https://campaigns.hkjc.com/racing-event-hub-hkir/en/hkcup-racing-info'
        page=(ROOT/'nominations.html').read_text();payload=parse_nominations(page,event=self.event,url=url)
        for index,value in enumerate((payload,{'stage':'registration','items':payload['items'][:1]})):
            now=NOW+timedelta(hours=4*index);claim=pre.claim_pre_race(event_id=self.event.pk,source='hkjc_pre_race_v1',now=now)
            self.assertTrue(complete(claim,payload=value,url=url,page=page,route=route(),now=now))
        self.assertEqual(self.event.data_candidates.count(),2)

    def test_disabled_hkjc_feature_preserves_generic_four_day_window(self):
        from stable.services.race_pre_race import pre_race_days
        self.assertEqual(pre_race_days(self.event),45)
        with override_settings(RACE_DATA_SYNC_HKJC_PRE_RACE_ENABLED=False):
            self.assertEqual(pre_race_days(self.event),4)

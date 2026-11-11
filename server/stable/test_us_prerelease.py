"""美国发布前补齐：官方出马文件的独立计数及障碍赛字段。"""
from pathlib import Path
import json
from unittest import TestCase

from stable.services import us_prerace_documents as docs

FIX = Path(__file__).parent / 'fixtures' / 'us_prerelease'


class USOvernightTests(TestCase):
    def card(self, filename, day, venue, number):
        return docs.parse_overnight((FIX / filename).read_bytes(), local_date=day,
            venue=venue, race_number=number, source_url=next(x["url"] for x in json.loads((FIX / "provenance.json").read_text()) if x["file"] == filename))

    def test_grand_national_numbers_include_scratched_six(self):
        card = self.card('nsa-entry-Far-Hills-Final-Overnight-2.pdf', '2026-10-17', 'FH', 5)
        self.assertEqual(card['declared_count'], 8)
        self.assertTrue(card['roster_complete'])
        self.assertEqual(card['source_stage'], 'declared_overnight')
        horse = next(x for x in card['runners'] if x['horse_name'] == 'ZANAHIYR (IRE)')
        self.assertEqual(horse['entry_number'], 7)
        self.assertEqual(horse['trainer_name'], 'Elliott, Gordon')
        self.assertEqual(horse['carried_weight'], '156 lb')
        self.assertEqual(card['off_time'], '2026-10-17T16:05:00-04:00')

    def test_montpelier_count_and_name(self):
        card = self.card('nsa-entry-Montpelier-Overnight-.pdf', '2026-11-07', 'MTP', 7)
        self.assertEqual(card['declared_count'], 6)
        self.assertEqual(card['runners'][0]['horse_name'], 'FOXY WALK (IRE)')
        self.assertEqual(card['runners'][-1]['horse_name'], 'BELLARMINE HALL')

    def test_saratoga_and_colonial_profiles(self):
        a = self.card('nsa-entry-Saratoga-September-2.pdf', '2026-09-02', 'SAR', 1)
        self.assertEqual(a['declared_count'], 7)
        self.assertEqual(a['runners'][0]['horse_name'], 'Mr Percy (IRE)')
        b = self.card('nsa-entry-09.03.26-Overnight.pdf', '2026-09-03', 'CNL', 3)
        self.assertEqual(b['declared_count'], 7)
        self.assertTrue(all(x['trainer_name'] for x in b['runners']))

    def test_churchill_stakes_overnight(self):
        a = self.card('churchill-1107-overnight.pdf', '2026-11-07', 'CD', 8)
        self.assertEqual(a['declared_count'], 8)
        self.assertIn('RIVER CITY', a['conditions_raw'])
        self.assertEqual(a['runners'][-1]['entry_number'], 8)

    def test_wrong_day_track_or_race_rejected(self):
        for day, venue, n in [('2026-10-18', 'FH', 5), ('2026-10-17', 'MTP', 5), ('2026-10-17', 'FH', 20)]:
            with self.assertRaises(ValueError):
                self.card('nsa-entry-Far-Hills-Final-Overnight-2.pdf', day, venue, n)


class USSteeplechaseTests(TestCase):
    CASES = [
        ('SAR2026090201.pdf','nsa-entry-Saratoga-September-2.pdf','nsa-result-Saratoga-September-2-Results-.pdf',7),
        ('CNL2026090303.pdf','nsa-entry-09.03.26-Overnight.pdf','nsa-result-September-3-results-.pdf',6),
        ('FX2026100406.pdf','nsa-entry-Foxfield-Overnight-Tuesday.pdf','nsa-result-October-4-results.pdf',9),
        ('FH2026101703.pdf','nsa-entry-Far-Hills-Final-Overnight-2.pdf','nsa-result-Far-Hills-Results.pdf',6),
        ('FH2026101705.pdf','nsa-entry-Far-Hills-Final-Overnight-2.pdf','nsa-result-Far-Hills-Results.pdf',7),
        ('GRM2026102404.pdf','nsa-entry-International-Gold-Cup-Overnight.pdf','nsa-result-International-Gold-Cup-results-Updated.pdf',7),
        ('MTP2026110707.pdf','nsa-entry-Montpelier-Overnight-.pdf','nsa-result-Montpelier-results-2026.pdf',6),
    ]

    def bundle(self, case):
        import re
        from stable.services.us_nsa_sources import parse_results
        from stable.services.us_steeplechase_results import merge_steeplechase
        chart,card,result,_ = case
        m=re.match(r'([A-Z]+)(\d{4})(\d{2})(\d{2})(\d{2})',chart)
        identity=dict(track=m[1],date=f'{m[2]}-{m[3]}-{m[4]}',race_number=int(m[5]))
        urls={x['file']:x['url'] for x in json.loads((FIX/'provenance.json').read_text()) if 'url' in x}
        official=next(x for x in parse_results((FIX/result).read_bytes(),url=urls[result])['items'] if x['race_number']==str(identity['race_number']))
        entry=docs.parse_overnight((FIX/card).read_bytes(),local_date=identity['date'],venue=identity['track'],race_number=identity['race_number'],source_url=urls[card])
        return merge_steeplechase((FIX/chart).read_bytes(),identity,official,entry)

    def test_all_seven_rosters_and_official_statuses(self):
        for case in self.CASES:
            with self.subTest(chart=case[0]):
                result=self.bundle(case)
                self.assertEqual(result['runner_count'],case[3])
                self.assertTrue(result['roster_complete'])
                self.assertTrue(all(x['program_number'] for x in result['runners']))
                self.assertTrue(all(x['margin_availability']!='missing' for x in result['runners']))
        result=self.bundle(self.CASES[-1])
        horse=next(x for x in result['runners'] if x['horse_name']=="SCORPION'S REVENGE (IRE)")
        self.assertEqual((horse['placing'],horse['status']),(5,'finished'))
        self.assertEqual(horse['margin_to_previous'],'92 1/4')
        self.assertIsNone(horse['odds_net'])
        self.assertEqual(horse['odds_availability'],'not_applicable_no_pool')

    def test_official_overnight_basic_fields_are_not_dropped(self):
        for case in self.CASES:
            result=self.bundle(case)
            self.assertEqual(result['catalogue']['age_condition'],'4U')
            self.assertTrue(result['catalogue']['purse_raw'].startswith('$'))
            self.assertTrue(result['catalogue']['distance_text'].endswith('miles'))
        self.assertEqual(self.bundle(self.CASES[0])['catalogue']['distance_text'],'2 3/8 miles')
        self.assertEqual(self.bundle(self.CASES[5])['catalogue']['distance_text'],'about 2 1/8 miles')
        self.assertEqual(self.bundle(self.CASES[1])['catalogue']['sex_condition'],'F&M')

    def test_camden_contract_reaches_overnight_and_result_merge(self):
        # 合成Camden页眉 + 既有真实NSA版式；不宣称未来Colonial Cup原件已发布。
        from copy import deepcopy
        from types import SimpleNamespace
        from unittest.mock import patch,MagicMock
        import pdfplumber
        from stable.services.us_flat_results import parse_chart
        from stable.services.us_nsa_sources import parse_results
        from stable.services.us_steeplechase_results import merge_steeplechase
        case=self.CASES[4];raw=(FIX/case[1]).read_bytes()
        with pdfplumber.open(FIX/case[1]) as pdf:
            lines=[deepcopy(line) for page in pdf.pages for line in page.extract_text_lines(x_tolerance=1.5)]
        for line in lines:line['text']=line['text'].replace('FAR HILLS','CAMDEN').replace('FARHILLS','CAMDEN')
        document=MagicMock();document.__enter__.return_value=SimpleNamespace(pages=[SimpleNamespace(extract_text_lines=lambda **kw:lines)])
        with patch('stable.services.us_prerace_documents.pdfplumber.open',return_value=document):
            card=docs.parse_overnight(raw,local_date='2026-10-17',venue='CAM',race_number=5,source_url='https://nationalsteeplechase.com/wp-content/uploads/2026/10/camden-synthetic.pdf')
        identity=dict(track='FH',date='2026-10-17',race_number=5)
        chart=parse_chart((FIX/case[0]).read_bytes(),identity)
        official=next(r for r in parse_results((FIX/case[2]).read_bytes(),url='fixture')['items'] if r['race_number']=='5')
        official['venue']='Camden';identity['track']='CAM'
        with patch('stable.services.us_steeplechase_results.parse_chart',return_value=chart):
            value=merge_steeplechase((FIX/case[0]).read_bytes(),identity,official,card)
        self.assertEqual((value['venue'],value['runner_count']),('CAM',7))
        self.assertEqual(value['gaps'],[])

    def test_grand_national_betting_and_scratches(self):
        result=self.bundle(self.CASES[4])
        horse=next(x for x in result['runners'] if x['horse_name']=='ZANAHIYR (IRE)')
        self.assertEqual((horse['program_number'],horse['post_position']),(7,6))
        self.assertEqual(horse['odds_net'],'5.50')
        self.assertEqual(result['scratches'][0]['program_number'],6)
        self.assertEqual(result['gaps'],[])

    def test_before_final_card_withdrawals_do_not_reuse_old_numbers(self):
        from stable.services.us_steeplechase_results import resolve_prior_card_scratches
        value=self.bundle(self.CASES[2])
        prior=docs.parse_overnight((FIX/'nsa-extra-Revised-Foxfield-Overnight-Monday-.pdf').read_bytes(),
            local_date='2026-10-04',venue='FX',race_number=6)
        resolved=resolve_prior_card_scratches(value,prior)
        self.assertEqual(resolved['gaps'],[])
        self.assertTrue(resolved['fields_complete'])
        self.assertEqual({r['prior_entry_number'] for r in resolved['scratches']},{1,5})
        self.assertTrue(all(r['program_number'] is None for r in resolved['scratches']))
        self.assertTrue(all(r['number_availability']=='withdrawn_before_final_overnight' for r in resolved['scratches']))

    def test_demotion_preserves_physical_order(self):
        result=self.bundle(self.CASES[2])
        horse=next(x for x in result['runners'] if x['horse_name']=='TWO PAST EIGHT (GB)')
        self.assertEqual((horse['finish_position'],horse['placing']),(1,2))
        winner=result['runners'][0]
        self.assertEqual(winner['horse_name'],'LYDFORD (GB)')
        self.assertEqual(winner['margin_to_previous'],'head')
        self.assertEqual(result['margin_semantics'],'behind_previous_physical_finisher')


class USNominationTests(TestCase):
    def test_keeneland_count_and_compressed_owner_trainer(self):
        value=docs.parse_stakes_nominations((FIX/'keeneland-bryan-noms.pdf').read_bytes(),
            local_date='2026-10-24',race_name='The Bryan Station')
        self.assertEqual(value['declared_count'],29)
        row=next(x for x in value['items'] if x['horse_name']=='GREENWICH VILLAGE')
        self.assertEqual(row['trainer_name'],'Bob Baffert')
        self.assertIn('Catherine Donovan',row['owner_name'])
        self.assertEqual(value['source_stage'],'nominations')
        self.assertFalse(any(x['horse_number'] for x in value['items']))

    def test_del_mar_trainer_is_structured(self):
        from types import SimpleNamespace
        from datetime import date
        from stable.services.us_racing_sources import parse_del_mar_nominations
        p=Path(__file__).parent/'fixtures'/'us_automation'/'dmtc-bob-hope-noms.pdf'
        value=parse_del_mar_nominations(p.read_bytes(),url='https://www.dmtc.com/racing/stakes/nominations/2026',
            event=SimpleNamespace(local_date=date(2026,11,15),original_name='Bob Hope Stakes',racecourse='Del Mar',timezone_name='America/Los_Angeles'))
        self.assertTrue(all(x['trainer_name'] for x in value['items']))
        self.assertNotIn('structured_trainer',value['gaps'])


class USDelMarCompletenessTests(TestCase):
    def test_overnight_independently_confirms_html_card(self):
        from types import SimpleNamespace
        from datetime import date
        from stable.services.us_racing_sources import parse_del_mar_card
        root=Path(__file__).parent/'fixtures'/'us_automation'
        event=SimpleNamespace(local_date=date(2026,11,8),original_name='Betty Grable Stakes',chinese_name='',racecourse='Del Mar',timezone_name='America/Los_Angeles')
        card=parse_del_mar_card((root/'dmtc-entries-final.html').read_bytes(),url='https://www.dmtc.com/racing/entries/2026-11-08',event=event)
        overnight=docs.parse_overnight((FIX/'dmtc-overnight-20261108.pdf').read_bytes(),local_date='2026-11-08',venue='DMR',race_number=8)
        result=docs.confirm_del_mar_roster(card,overnight)
        self.assertTrue(result['roster_complete'])
        self.assertNotIn('independent_roster_count',result['gaps'])
        overnight['runners'].pop()
        with self.assertRaises(ValueError):
            docs.confirm_del_mar_roster(card,overnight)


class USInventoryTests(TestCase):
    def test_two_same_named_races_cannot_share_write_target(self):
        from stable.services.us_race_inventory import reconcile_inventory
        rows=[dict(candidate_key=str(n),grade='G3',race_name='Glen Cove S.',local_date='2026-10-25',venue='BEL',source_race_id=str(n)) for n in (5,8)]
        event=dict(id=547,year=2026,original_name='Glen Cove S.',local_date='2026-10-25',source_refs={'track_code':'BEL'})
        r=reconcile_inventory({'items':rows,'unresolved':[]},[],[event],start='2026-09-01',end='2026-12-31')
        self.assertEqual(r['target_count'],2)
        self.assertEqual(r['action_counts'],{'split_occurrences_required':2})
        self.assertTrue(all(x['write_event_id'] is None for x in r['targets']))

    def test_existing_undated_is_updated_and_not_run_is_outside_window(self):
        from stable.services.us_race_inventory import reconcile_inventory
        rows=[dict(candidate_key='a',grade='G3',race_name='River City S.',local_date='2026-11-07',venue='CD')]
        annual=[dict(candidate_key='b',grade='G2',race_name='Woodward S.',local_date=None,venue='BEL',year=2026)]
        event=dict(id=595,year=2026,original_name='River City S.',local_date=None,source_refs={'track_code':'CD'})
        r=reconcile_inventory({'items':rows,'unresolved':annual},[],[event],start='2026-09-01',end='2026-12-31')
        self.assertEqual(r['targets'][0]['action'],'update_existing')
        self.assertTrue(r['targets'][0]['date_change'])
        self.assertEqual(r['target_count'],1)
        self.assertEqual(len(r['annual_not_run']),1)


class USNSACollectionTests(TestCase):
    def test_discovered_far_hills_two_graded_results_are_complete(self):
        from datetime import date,datetime,timezone
        from unittest.mock import Mock
        import hashlib
        from stable.services.us_prerelease_collection import collect_nsa
        files={x['url']:(FIX/x['file']).read_bytes() for x in json.loads((FIX/'provenance.json').read_text()) if 'url' in x}
        other=Path(__file__).parent/'fixtures'
        files['https://nationalsteeplechase.com/racing/']=(other/'us_automation/nsa-racing.html').read_bytes()
        from stable.services.us_source_collection import nsa_directory
        listing=nsa_directory(files['https://nationalsteeplechase.com/racing/'],start=date(2026,10,17),end=date(2026,10,17))
        for url in listing['books']:files[url]=(other/'us_automation/nsa-fall.pdf').read_bytes()
        files['https://www1.drf.com/StakesResults/MainMenu.do']=(FIX/'drf-all-stakes.html').read_bytes()
        store=Mock();store.now=datetime(2026,11,11,tzinfo=timezone.utc)
        def get(url):
            body=files[url]
            return dict(url=url,body=body,sha256=hashlib.sha256(body).hexdigest(),fetched_at=store.now.isoformat())
        store.get.side_effect=get
        report=collect_nsa(store,start=date(2026,10,17),end=date(2026,10,17))
        self.assertEqual(report['errors'],[])
        self.assertEqual(len(report['results']),2)
        self.assertEqual(sum(r['runner_count'] for r in report['results']),13)
        self.assertTrue(all(r['fields_complete'] for r in report['results']))


class USScopeIsolationTests(TestCase):
    def test_unknown_ordinary_race_status_does_not_block_graded_scope(self):
        from stable.services.us_nsa_sources import parse_results
        raw=(FIX/'nsa-va-fall.pdf').read_bytes()
        with self.assertRaisesRegex(ValueError,'us_nsa_unknown_status'):
            parse_results(raw,url='https://nationalsteeplechase.com/wp-content/uploads/2026/10/VA-Fall-2026.pdf')
        value=parse_results(raw,url='https://nationalsteeplechase.com/wp-content/uploads/2026/10/VA-Fall-2026.pdf',graded_only=True)
        self.assertEqual(value['items'],[])
        self.assertTrue(value['excluded_non_graded_races'])


class USSportingCardTests(TestCase):
    def test_directory_uses_local_day_for_midnight_races(self):
        from datetime import date
        from stable.services.us_prerelease_collection import sporting_card_directory
        rows=sporting_card_directory((FIX/'sl-cards-today.html').read_bytes(),start=date(2026,11,11),end=date(2026,11,11))
        race=next(r for r in rows if r['track']=='RP' and r['race_number']==1)
        self.assertEqual(race['date'],'2026-11-11')
        self.assertIn('/2026-11-11/remington-park/racecard/948649/',race['url'])
        self.assertEqual({r['track'] for r in rows},{'CD','RP','PEN','MNR','CT','MVR','IND'})

    def test_live_card_fields_and_cross_midnight(self):
        for filename,track,number,count,time in [
            ('sl-churchill-livecard.html','CD',1,7,'2026-11-11T13:00:00-05:00'),
            ('sl-remington-livecard.html','RP',1,10,'2026-11-11T18:30:00-06:00')]:
            card=docs.parse_sporting_card((FIX/filename).read_bytes(),dict(track=track,date='2026-11-11',race_number=number))
            self.assertEqual(card['source_stage'],'declared_card')
            self.assertEqual(card['declared_count'],count)
            self.assertEqual(card['off_time'],time)
            self.assertTrue(all(r['carried_weight'].endswith(' lb') and r['jockey_name'] and r['trainer_name'] for r in card['runners']))
            self.assertFalse(card['gaps'])

    def test_historical_card_cannot_count_as_live_prerace(self):
        card=docs.parse_sporting_card((FIX/'sl-river-card.html').read_bytes(),dict(track='CD',date='2026-11-07',race_number=8))
        self.assertEqual(card['source_stage'],'historical_card')
        self.assertEqual((card['declared_count'],card['active_count']),(8,6))
        self.assertEqual(sum(r['running_status']=='scratched' for r in card['runners']),2)
        self.assertTrue(all(r['odds_stage']=='historical' for r in card['runners']))

    def test_wrong_race_and_truncated_roster_rejected(self):
        from stable.services.us_flat_results import next_data
        raw=(FIX/'sl-river-card.html').read_bytes()
        with self.assertRaises(ValueError):
            docs.parse_sporting_card(raw,dict(track='CD',date='2026-11-07',race_number=7))
        data=next_data(raw);data['race']['rides'].pop(0)
        raw=('<script id="__NEXT_DATA__">'+json.dumps({'props':{'pageProps':data}})+'</script>').encode()
        with self.assertRaisesRegex(ValueError,'count'):
            docs.parse_sporting_card(raw,dict(track='CD',date='2026-11-07',race_number=8))


class USNYRACardTests(TestCase):
    def test_equipment_between_weight_and_age_is_not_lost(self):
        card=docs.parse_nyra_card((FIX/'nyra-hopeful.html').read_bytes(),
            dict(track='SAR',date='2026-09-06',race_number=10))
        horse=next(x for x in card['runners'] if x['horse_name']=='Flight Command')
        self.assertEqual((horse['carried_weight'],horse['age'],horse['sex']),('122 lb',2,'C'))
        self.assertEqual(horse['equipment_raw'],'B')
        self.assertEqual(card['declared_count'],8)
        card=docs.parse_nyra_card((FIX/'nyra-jockey-club-gold-cup.html').read_bytes(),
            dict(track='BEL',date='2026-09-18',race_number=5))
        self.assertEqual(card['runners'][0]['equipment_raw'],'O')

    def test_division_has_independent_owner_count_and_scratches(self):
        card=docs.parse_nyra_card((FIX/'nyra-glen-cove-5.html').read_bytes(),
            dict(track='BEL',date='2026-10-25',race_number=5))
        self.assertEqual((card['declared_count'],card['active_count']),(10,8))
        self.assertEqual(card['off_time'],'2026-10-25T15:25:00-04:00')
        self.assertEqual(card['runners'][0]['horse_name'],'Light Won Up')
        self.assertEqual(card['runners'][0]['running_status'],'scratched')
        self.assertEqual(card['runners'][0]['trainer_name'],"Doug F. O'Neill")
        self.assertTrue(all(r['post_position'] is None for r in card['runners']))

    def test_wrong_date_and_same_named_other_division_rejected(self):
        raw=(FIX/'nyra-glen-cove-5.html').read_bytes()
        for day,n in [('2026-10-24',5),('2026-10-25',8)]:
            with self.assertRaises(ValueError):
                docs.parse_nyra_card(raw,dict(track='BEL',date=day,race_number=n))


class USFinalRosterTests(TestCase):
    def test_completed_race_uses_verified_final_roster_without_early_nominations(self):
        result=json.loads((FIX/'verified-final-roster.json').read_text())
        target=dict(candidate_key=result['candidate_key'],local_date='2026-09-19',venue='PRX',source_race_id='14',field_size_raw='10')
        roster=docs.final_result_roster(result,target)
        self.assertEqual(roster['source_stage'],'final_result_roster')
        self.assertEqual((roster['active_count'],roster['declared_count']),(10,11))
        self.assertEqual(roster['scratches'][0]['horse_name'],'Zihnal')
        self.assertTrue(roster['roster_complete'])
        self.assertFalse(roster['pre_race_snapshot'])

    def test_incomplete_or_different_race_cannot_satisfy_final_roster(self):
        result=json.loads((FIX/'verified-final-roster.json').read_text())
        target=dict(candidate_key=result['candidate_key'],local_date='2026-09-19',venue='PRX',source_race_id='13',field_size_raw='10')
        with self.assertRaises(ValueError):docs.final_result_roster(result,target)
        target['source_race_id']='14';result['runners'].pop()
        with self.assertRaises(ValueError):docs.final_result_roster(result,target)


class USRacingPreraceTests(TestCase):
    def test_public_preliminary_lists_are_not_final_cards(self):
        for filename,name,venue,day,count in [
            ('commonwealth-turf','COMMONWEALTH TURF S.','CD','2026-11-21',18),
            ('pebbles','PEBBLES S.','BEL','2026-11-21',19),
            ('manila','MANILA S.','BEL','2026-11-22',18)]:
            value=docs.parse_usracing_prerace((FIX/('usracing-'+filename+'.html')).read_bytes(),
                dict(race_name=name,venue=venue,local_date=day,grade='G3'))
            self.assertEqual(value['source_stage'],'preliminary_field')
            self.assertEqual(value['published_count'],count)
            self.assertFalse(value['final_roster_complete'])
            self.assertTrue(all(r['horse_name'] and r['trainer_name'] for r in value['items']))
            self.assertTrue(all(not r['horse_number'] and not r['jockey_name'] for r in value['items']))

    def test_explicit_pending_is_not_empty_success_or_wrong_year(self):
        target=dict(race_name='NATIVE DIVER S.',venue='DMR',local_date='2026-11-21',grade='G3')
        raw=(FIX/'usracing-native-diver.html').read_bytes()
        value=docs.parse_usracing_prerace(raw,target)
        self.assertEqual(value['source_stage'],'not_published')
        self.assertEqual(value['items'],[])
        target['local_date']='2025-11-21'
        with self.assertRaises(ValueError):docs.parse_usracing_prerace(raw,target)

    def test_directory_discovers_actual_links_without_guessing(self):
        from stable.services.us_prerelease_collection import usracing_directory
        targets=[dict(candidate_key='1',race_name='COMMONWEALTH TURF S.',venue='CD',local_date='2026-11-21'),
                 dict(candidate_key='2',race_name='CLARK S.',venue='CD',local_date='2026-11-27')]
        found=usracing_directory((FIX/'usracing-graded-schedule.html').read_bytes(),targets)
        self.assertEqual(found,{'1':'https://usracing.com/commonwealth-turf-stakes'})


class USPrereleaseRegressionTests(TestCase):
    def collect(self, targets, *, now='2026-11-07T12:00:00+00:00', live=(), extra=None, calendar=None):
        from datetime import date,datetime
        from unittest.mock import Mock,patch
        from stable.services.us_prerelease_collection import collect_prerace
        from stable.services.us_racing_sources import catalogue
        store=Mock(now=datetime.fromisoformat(now))
        def get(url):
            body=(extra or {}).get(url,b'')
            return dict(url=url,body=body,sha256='a'*64,fetched_at=now)
        store.get.side_effect=get
        with patch('stable.services.us_racing_sources.parse_toba_calendar',return_value=calendar or catalogue(targets)), \
             patch('stable.services.us_source_collection.del_mar_nominations_directory',return_value=[]), \
             patch('stable.services.us_prerelease_collection.sporting_card_directory',return_value=list(live)):
            value=collect_prerace(store,start=date(2026,11,7),end=date(2026,11,7),
                flat_report=dict(start='2026-11-07',end='2026-11-07',results=[],sources=[]))
        return value,store

    def target(self, name='RIVER CITY S.', number='8', venue='CD'):
        return dict(candidate_key='river',provider='toba',venue=venue,local_date='2026-11-07',
            race_name=name,source_race_id=number,grade='G3')

    def test_conflicting_calendar_stays_in_denominator_and_blocks(self):
        a=self.target();b=dict(a,grade='G2')
        report,_=self.collect([a,b])
        self.assertEqual(report['counts']['targets'],1)
        self.assertEqual(report['acceptance'],'coverage_gaps')
        self.assertTrue(any(x['reason']=='us_calendar_source_conflict' for x in report['targets'][0]['errors']))
        from stable.services.us_race_inventory import reconcile_inventory
        from stable.services.us_racing_sources import catalogue
        inv=reconcile_inventory(catalogue([a,b]),[],[],start='2026-11-07',end='2026-11-07')
        self.assertEqual(inv['target_count'],1)
        self.assertEqual(inv['targets'][0]['action'],'source_conflict')
        self.assertIsNone(inv['targets'][0]['write_event_id'])

    def test_same_day_declared_card_does_not_require_final_results(self):
        identity=dict(track='CD',date='2026-11-07',race_number=8,race_name='RIVER CITY S.',url='https://www.sportinglife.com/racing/racecards/2026-11-07/churchill-downs/racecard/948111/river-city')
        from stable.services.us_flat_results import next_data
        data=next_data((FIX/'sl-river-card.html').read_bytes());data['race']['race_summary']['race_stage']='RACECARD'
        raw=('<script id="__NEXT_DATA__">'+json.dumps({'props':{'pageProps':data}})+'</script>').encode()
        value,_=self.collect([self.target()],live=[identity],extra={identity['url']:raw})
        self.assertFalse(value['targets'][0]['errors'])
        self.assertEqual(value['acceptance'],'observable_sources_passed_with_pending')

    def test_incomplete_card_blocks_coverage(self):
        from stable.services.us_flat_results import next_data
        data=next_data((FIX/'sl-river-card.html').read_bytes())
        next(r for r in data['race']['rides'] if r['ride_status']=='RUNNER')['trainer']={}
        raw=('<script id="__NEXT_DATA__">'+json.dumps({'props':{'pageProps':data}})+'</script>').encode()
        identity=dict(track='CD',date='2026-11-07',race_number=8,race_name='RIVER CITY S.',url='https://www.sportinglife.com/racing/racecards/2026-11-07/churchill-downs/racecard/948111/river-city')
        value,_=self.collect([self.target()],live=[identity],extra={identity['url']:raw})
        self.assertTrue(any(x['reason']=='us_card_fields_incomplete' for x in value['targets'][0]['errors']))
        self.assertEqual(value['acceptance'],'coverage_gaps')

    def test_empty_unrelated_churchill_directory_does_not_block(self):
        value,store=self.collect([self.target(venue='PRX')])
        self.assertEqual(value['errors'],[])
        self.assertEqual(value['acceptance'],'observable_sources_passed_with_pending')
        self.assertNotIn('https://www.churchilldowns.com/overnights/',[c.args[0] for c in store.get.call_args_list])

    def test_churchill_discovered_pdf_collected_and_identity_checked(self):
        url='https://www.kentuckyderby.com/wp-content/uploads/sites/3/2026/11/11.7-overnight.pdf'
        extra={'https://www.churchilldowns.com/overnights/':f'<a href="{url}">11/7</a>'.encode(),url:(FIX/'churchill-1107-overnight.pdf').read_bytes()}
        value,store=self.collect([self.target()],extra=extra)
        self.assertIn(url,[c.args[0] for c in store.get.call_args_list])
        self.assertEqual(value['targets'][0]['card_status'],'provisional_available')
        self.assertEqual(value['documents'][0]['data']['declared_count'],8)
        self.assertEqual(value['acceptance'],'observable_sources_passed_with_pending')
        discovered,_=self.collect([self.target(number='')],extra=extra)
        self.assertEqual(discovered['documents'][0]['data']['race_number'],8)
        wrong,_=self.collect([self.target(name='WRONG STAKES')],extra=extra)
        self.assertEqual(wrong['acceptance'],'coverage_gaps')

    def test_overnight_cannot_mask_missing_age_and_draw(self):
        from stable.services.us_flat_results import next_data
        data=next_data((FIX/'sl-river-card.html').read_bytes())
        data['race']['race_summary']['race_stage']='RACECARD'
        row=next(r for r in data['race']['rides'] if r['ride_status']=='RUNNER')
        row['horse']['age']=None;row['draw_number']=None
        raw=('<script id="__NEXT_DATA__">'+json.dumps({'props':{'pageProps':data}})+'</script>').encode()
        identity=dict(track='CD',date='2026-11-07',race_number=8,race_name='RIVER CITY S.',url='https://www.sportinglife.com/racing/racecards/2026-11-07/churchill-downs/racecard/948111/river-city')
        url='https://www.kentuckyderby.com/wp-content/uploads/sites/3/2026/11/11.7-overnight.pdf'
        extra={identity['url']:raw,'https://www.churchilldowns.com/overnights/':f'<a href="{url}">11/7</a>'.encode(),url:(FIX/'churchill-1107-overnight.pdf').read_bytes()}
        value,_=self.collect([self.target()],live=[identity],extra=extra)
        self.assertEqual(value['acceptance'],'coverage_gaps')
        overnight=next(d['data'] for d in value['documents'] if d['data']['source_stage']=='declared_overnight')
        self.assertFalse(overnight['fields_complete'])
        self.assertTrue(overnight['roster_complete'])

class USNSAPreviewTests(TestCase):
    def test_discovers_actual_race_number_from_named_overnight(self):
        from stable.services.us_prerelease_collection import nsa_target_card
        raw=(FIX/'nsa-entry-Far-Hills-Final-Overnight-2.pdf').read_bytes()
        target=dict(provider='nsa',venue='FH',local_date='2026-10-17',race_name='American Grand National',
            source_race_id='104',book_race_id='104')
        value=nsa_target_card(raw,target)
        self.assertEqual(value['race_number'],5)
        self.assertEqual(value['declared_count'],8)
        self.assertEqual(value['source_stage'],'declared_overnight')
        self.assertEqual(value['runners'][0]['entry_number'],1)
        for change in [{'race_name':'Grand National'}, {'local_date':'2026-10-18'}, {'venue':'MTP'}]:
            with self.assertRaises(ValueError):nsa_target_card(raw,{**target,**change})

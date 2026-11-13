"""英国付费来源的字段语义和名单反例；合成数据，不访问网络。"""
from copy import deepcopy
from unittest import TestCase
from stable.services.uk_sources import parse_card, parse_result


def card():
    return dict(race_id='rac_123',date='2026-10-30',region='GB',course='Newmarket',
        race_name='Example Stakes (Group 3)',off_dt='2026-10-30T14:20:00+00:00',
        type='Flat',pattern='Group 3',distance='1m4f',distance_f='12',going='Good',
        surface='Turf',age_band='3yo+',sex_restriction='',prize='£42,532',prize_currency='GBP',
        field_size='2',race_status='result',is_abandoned=False,runners=[
            dict(horse_id='hrs_1',horse='Example One',number='1',draw='3',lbs='132',jockey='J One',trainer='T One'),
            dict(horse_id='hrs_2',horse='Example Two',number='2',draw='1',lbs='135',jockey='J Two',trainer='T Two'),
            dict(horse_id='hrs_3',horse='Example Three',number='NR',draw='2',lbs='132',jockey='J Three',trainer='T Three')])


def result():
    return dict(race_id='rac_123',date='2026-10-30',region='GB',course='Newmarket',
        race_name='Example Stakes (Group 3)',off_dt='2026-10-30T14:20:00+00:00',
        type='Flat',pattern='Group 3',dist='1m4f',dist_m='2414',going='Good',surface='Turf',
        winning_time_detail='2m 35.89s',non_runners='Example Three',runners=[
            dict(horse_id='hrs_1',horse='Example One (GB)',number='1',draw='3',weight_lbs='132',
                 jockey='J One',trainer='T One',position='1',time='2:35.89',btn='0',ovr_btn='0',sp='2/1F',sp_dec='3.00'),
            dict(horse_id='hrs_2',horse='Example Two (IRE)',number='2',draw='1',weight_lbs='135',
                 jockey='J Two',trainer='T Two',position='2',time='2:36.10',btn='1.5',ovr_btn='1.5',sp='5/1',sp_dec='6.00')])


class UKSourceTests(TestCase):
    def test_card_quotes_keep_bookmaker_and_do_not_replace_result_sp(self):
        raw=card();raw['runners'][0]['odds']=[{'bookmaker':'Other','decimal':'5.5'},
            {'bookmaker':'Bet365','decimal':'4.25','fractional':'13/4','updated':'2026-10-30 12:00:00'}]
        row=parse_card(raw)['roster'][0]
        self.assertEqual(row['odds_value'],'4.25')
        self.assertEqual(row['field_provenance']['odds_source'],'TRA / Bet365')
        self.assertEqual(parse_result(result(),card=raw)['roster'][0]['field_provenance']['win_odds'],'3.00')
        raw['runners'][0]['odds']=[{'bookmaker':'Other','decimal':'SP'}]
        self.assertEqual(parse_card(raw)['roster'][0]['odds_value'],'')


    def test_complete_result_includes_nr_and_retains_units(self):
        race=parse_result(result(),card=card())
        self.assertEqual(len(race['roster']),3)
        self.assertEqual(race['roster'][0]['carried_weight'],'132 lb')
        self.assertEqual(race['roster'][1]['margin'],'1.5')
        self.assertEqual(race['roster'][1]['field_provenance']['margin_basis'],'behind_previous')
        self.assertEqual(race['roster'][0]['field_provenance']['win_odds'],'3.00')
        nr=race['roster'][2]
        self.assertEqual((nr['external_runner_id'],nr['status'],nr['number']),('hrs_3','non_runner',''))
        self.assertIn('non_runner_number_missing:hrs_3',race['gaps'])
        self.assertEqual(race['result_phase'],'official')

    def test_prize_is_winner_amount_not_total(self):
        race=parse_card(card())
        self.assertEqual(race['metadata']['winner_prize_amount'],'42532')
        self.assertNotIn('prize_amount',race['metadata'])

    def test_missing_or_duplicate_runner_rejected(self):
        for change in ('missing','duplicate','extra'):
            r=result()
            if change=='missing':r['runners'].pop()
            if change=='duplicate':r['runners'][1]=deepcopy(r['runners'][0])
            if change=='extra':r['runners'][1]['horse_id']='hrs_4'
            with self.subTest(change=change),self.assertRaises(ValueError):parse_result(r,card=card())

    def test_identity_date_venue_name_conflict_rejected(self):
        for key,value in [('race_id','rac_999'),('date','2026-10-29'),('course','Newbury'),('region','IRE')]:
            r=result();r[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):parse_result(r,card=card())
        r=result();r['runners'][0]['horse']='Other Horse'
        with self.assertRaises(ValueError):parse_result(r,card=card())

    def test_nr_text_must_match_card(self):
        r=result();r['non_runners']='Different Horse'
        with self.assertRaises(ValueError):parse_result(r,card=card())

    def test_non_finishers_and_dead_heat_are_explicit(self):
        r=result();r['runners'][1]['position']='PU';r['runners'][1]['time']='';r['runners'][1]['btn']=''
        race=parse_result(r,card=card());self.assertEqual(race['roster'][1]['status'],'pulled_up')
        r=result();r['runners'][1]['position']='1'
        self.assertEqual([x['status'] for x in parse_result(r,card=card())['roster'][:2]],['dead_heat','dead_heat'])
        r['runners'][1]['position']='XYZ'
        with self.assertRaises(ValueError):parse_result(r,card=card())

    def test_card_phase_and_count_are_not_guessed(self):
        c=card();c['field_size']='3'
        with self.assertRaises(ValueError):parse_card(c)
        c=card();c['race_status']='entries'
        with self.assertRaises(ValueError):parse_card(c)
        c=card();c['is_abandoned']=True
        with self.assertRaises(ValueError):parse_card(c)

    def test_timezone_must_match_british_day(self):
        c=card();c['off_dt']='2026-10-30T14:20:00'
        with self.assertRaises(ValueError):parse_card(c)
        c=card();c['off_dt']='2026-10-29T23:20:00+00:00'
        with self.assertRaises(ValueError):parse_card(c)

    def test_entry_preview_does_not_become_final_card(self):
        from stable.services.uk_sources import parse_preview
        c=card();c['race_status']='entry';c['field_size']='3'
        for row in c['runners']:row.update(number='',lbs='',draw='0',jockey='')
        preview=parse_preview(c)
        self.assertEqual(preview['stage'],'nominations')
        self.assertFalse(preview['roster_complete'])
        self.assertEqual(len(preview['roster']),3)
        self.assertTrue(all(not x['number'] for x in preview['roster']))
        with self.assertRaises(ValueError):parse_card(c)

    def test_supplement_numbers_requires_same_whole_field(self):
        from stable.services.uk_sources import supplement_numbers
        race=parse_result(result(),card=card())
        sl=dict(race_summary=dict(date='2026-10-30',time='14:20',course_name='Newmarket',
            race_stage='WEIGHEDIN',ride_count=2),rides=[
                dict(horse={'name':'Example One'},cloth_number=1,ride_status='RUNNER',finish_position=1),
                dict(horse={'name':'Example Two'},cloth_number=2,ride_status='RUNNER',finish_position=2),
                dict(horse={'name':'Example Three'},cloth_number=3,ride_status='NONRUNNER')])
        source=dict(url='https://www.sportinglife.com/racing/results/2026-10-30/newmarket/123/example',sha256='a'*64)
        merged=supplement_numbers(race,sl,source=source)
        self.assertEqual(merged['gaps'],[])
        self.assertEqual(merged['roster'][2]['number'],'3')
        self.assertEqual(race['roster'][2]['number'],'')
        for key,value in [('date','2026-10-29'),('time','14:30'),('course_name','Newbury')]:
            bad=deepcopy(sl);bad['race_summary'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):supplement_numbers(race,bad,source=source)
        bad=deepcopy(sl);bad['rides'][0]['horse']['name']='Other Horse'
        with self.assertRaises(ValueError):supplement_numbers(race,bad,source=source)

    def test_sporting_life_uses_utc_during_bst(self):
        from stable.services.uk_sources import supplement_numbers
        c=card();r=result()
        for x in (c,r):x.update(date='2026-09-05',off_dt='2026-09-05T15:20:00+01:00',course='Kempton (AW)')
        race=parse_result(r,card=c)
        sl=dict(race_summary=dict(date='2026-09-05',time='14:20',course_name='Kempton',race_stage='WEIGHEDIN',ride_count=2),rides=[
            dict(horse={'name':'Example One'},cloth_number=1,ride_status='RUNNER',finish_position=1),
            dict(horse={'name':'Example Two'},cloth_number=2,ride_status='RUNNER',finish_position=2),
            dict(horse={'name':'Example Three'},cloth_number=3,ride_status='NONRUNNER')])
        source=dict(url='https://www.sportinglife.com/racing/results/2026-09-05/kempton/123/example',sha256='a'*64)
        self.assertEqual(supplement_numbers(race,sl,source=source)['gaps'],[])

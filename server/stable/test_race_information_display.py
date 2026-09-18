from django.test import SimpleTestCase, override_settings
from stable.models import RaceEvent


class DisplayEntryTests(SimpleTestCase):
    @override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=True)
    def test_grade_badge_uses_standard_case_and_preserves_jump_grade(self):
        self.assertEqual(RaceEvent(grade_text='JpnⅡ', normalized_grade='JPN2').grade_badge_label, 'Jpn2')
        self.assertEqual(RaceEvent(grade_text='J・GⅢ').grade_badge_label, 'J-G3')

    @override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=True)
    def test_imperial_distance_has_chinese_units_and_metric(self):
        self.assertEqual(RaceEvent(distance_text='1 mile').display_distance_text, '1英里（约1609米）')

    @override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=False)
    def test_disabled_flag_keeps_legacy_distance(self):
        self.assertEqual(RaceEvent(distance_text='1 mile').display_distance_text, '1 mile')


class StrictParserTests(SimpleTestCase):
    def test_grade_variants_and_conflicts(self):
        from stable.services.race_field_normalization import parse_display_grade as parse
        for raw, expected in [('Grade1','G1'), ('Group II','G2'), ('GIII','G3'), ('JpnII','Jpn2'),
                              ('J・GⅢ','J-G3'), ('重赏 G1','G1'), ('Listed','L'), ('Open','OP')]:
            with self.subTest(raw=raw):
                self.assertEqual(parse(raw).text, expected)
        for raw in ['G1 G2','G10','JpnIIII','G1 Handicap','香港一级赛']:
            self.assertEqual(parse(raw).text, '待核实')
        self.assertEqual(parse('G2', normalized_grade='G1').state, 'conflict')

    def test_distance_exact_conversion_full_consumption_and_idempotence(self):
        from stable.services.race_field_normalization import parse_display_distance as parse
        cases = [('１６００メートル','', '1600米'), ('1.6公里','', '1600米'),
                 ('1600m','meter','1600米'), ('1m 2f','mile','1.25英里（约2012米）'),
                 ('1m 110y','mile','1英里330英尺（约1710米）'),
                 ('1 1/16 mile','','1英里330英尺（约1710米）'),
                 ('1½ miles','','1.5英里（约2414米）'), ('10ft','','10英尺（约3米）'),
                 ('6fur','','0.75英里（约1207米）'), ('约1英里','','约1英里（约1609米）')]
        for raw,hint,expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parse(raw,unit_hint=hint).text, expected)
                self.assertEqual(parse(expected).text, expected)
        for bad in ['1600m','9','1m 2f','0米','-1米','NaN米','1/0英里','1mile garbage',
                    '1 mile 2米','1mile 1mile','1英里（约1600米）','a'*513]:
            with self.subTest(bad=bad):
                self.assertIn(parse(bad).state, {'unknown','conflict'})
        self.assertEqual(parse('1mile',official_metric_meters=1600).state,'conflict')
        self.assertNotEqual(parse('1m',unit_hint='meter').input_sha256,parse('1m',unit_hint='mile').input_sha256)

    def test_age_time_weight_and_odds(self):
        from stable.services.race_field_normalization import (parse_display_eligibility, parse_display_time,
            parse_display_weight,parse_display_odds,parse_display_margin)
        plus=parse_display_eligibility('3yo+')
        fixed=parse_display_eligibility('3yo')
        self.assertEqual((plus.min_age,plus.max_age,plus.age_open_ended,plus.text),(3,None,True,'3岁及以上'))
        self.assertEqual((fixed.min_age,fixed.max_age,fixed.age_open_ended,fixed.text),(3,3,False,'3岁'))
        self.assertEqual(parse_display_eligibility('3yo+ unknown').state,'unknown')
        self.assertEqual(parse_display_time('1:32.50').text,'1分32.50秒')
        self.assertEqual(parse_display_time('1:62').state,'unknown')
        self.assertEqual(parse_display_weight('126lb').text,'126磅（约57.2千克）')
        self.assertEqual(parse_display_weight('57').state,'unknown')
        self.assertEqual(parse_display_odds('5/2',odds_format='fractional').text,'5/2（分数）')
        self.assertEqual(parse_display_odds('2.5').state,'unknown')
        self.assertEqual(parse_display_margin('1½ lengths').text,'1.5马身')

    def test_time_zone_and_dst(self):
        from stable.services.race_information_display import event_fields
        from datetime import date,time,datetime,timezone
        field=event_fields({'local_date':date(2026,9,18),'local_start_time':time(15,40),'timezone_name':'Asia/Tokyo'})
        self.assertIn('北京时间2026-09-18 14:40',field['time'].text)
        field=event_fields({'local_date':date(2026,10,25),'local_start_time':time(1,30),'timezone_name':'Europe/London'})
        self.assertEqual(field['time'].reason_code,'dst_ambiguous_or_missing')
        field=event_fields({'local_date':date(2026,9,18),'local_start_time':time(15,40),'timezone_name':'Asia/Tokyo',
                            'race_datetime':datetime(2026,9,18,0,tzinfo=timezone.utc)})
        self.assertEqual(field['time'].state,'conflict')

    def test_recorded_jra_fixture_weight_units(self):
        from pathlib import Path
        from bs4 import BeautifulSoup
        from stable.services.race_field_normalization import parse_display_weight
        fixture=Path(__file__).parent/'fixtures/jra_pre_race/all_comers_declared.html'
        soup=BeautifulSoup(fixture.read_bytes().decode('cp932'),'html.parser')
        weights=[node.get_text(' ',strip=True) for node in soup.select('td.jockey .weight')]
        self.assertEqual(len(weights),13)
        for weight in weights:
            self.assertEqual(parse_display_weight(weight).state,'normalized')

    def test_offline_iso_time_inputs_and_bad_types(self):
        from stable.services.race_information_display import event_fields
        from stable.services.race_field_normalization import parse_display_distance
        fields=event_fields({'local_date':'2026-09-18','local_start_time':'15:40:00','timezone_name':'Asia/Tokyo'})
        self.assertIn('14:40',fields['time'].text)
        self.assertEqual(event_fields({'local_date':'not-a-date'})['date'].state,'unknown')
        self.assertEqual(parse_display_distance('1600m',unit_hint=None).state,'unknown')

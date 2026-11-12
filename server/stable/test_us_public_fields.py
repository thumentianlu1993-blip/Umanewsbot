"""线上美国赛事真实原值的展示回归；纯函数，不访问网络/数据库。"""
from unittest import TestCase
from stable.services.race_field_normalization import (
    parse_display_distance, parse_display_time, parse_display_odds,
)


class USPublicFieldTests(TestCase):
    def test_presque_isle_explicit_synthetic_distance(self):
        self.assertEqual(parse_display_distance('6.5f synthetic').state, 'normalized')
        self.assertIn('1308', parse_display_distance('6.5f synthetic').text)
        self.assertNotEqual(parse_display_distance('芝 6.5f synthetic').state, 'normalized')
        self.assertNotEqual(parse_display_distance('6.5f unknown').state, 'normalized')

    def test_del_mar_explicit_elapsed_time(self):
        self.assertEqual(parse_display_time('1m 23.54s').text, '1分23.54秒')
        self.assertEqual(parse_display_time('59.02s').text, '59.02秒')
        for raw in ['1m 63.54s', '1m 23.54s extra', '83.54', '0m 0s']:
            self.assertIn(parse_display_time(raw).state, {'unknown','conflict'})

    def test_us_net_odds_requires_explicit_contract(self):
        self.assertEqual(parse_display_odds('4.06', odds_format='us_net').text, '4.06（美国净赔率）')
        self.assertEqual(parse_display_odds('4.06').state, 'unknown')
        self.assertEqual(parse_display_odds('1/3', odds_format='us_net').state, 'unknown')

    def test_surface_and_race_kind_are_independent(self):
        from types import SimpleNamespace
        from stable.services.race_information_display import event_fields
        event = SimpleNamespace(country_region='united_states', surface='jumps', normalized_race_type='hurdle',
            source_refs={'us_race_metadata': {'surface': 'turf', 'race_kind': 'hurdle', 'going': 'muddy', 'going_raw': 'muddy (Sealed)'}})
        fields = event_fields(event)
        self.assertEqual(fields['surface'].text, '草地')
        self.assertEqual(fields['race_type'].state, 'normalized')
        event.manual_lock_flags={'surface':True};event.surface='dirt'
        self.assertEqual(event_fields(event)['surface'].text,'泥地')
        event.manual_lock_flags={}
        self.assertIn('Sealed', fields['going'].text)
        event.surface = 'dirt'; event.normalized_race_type = 'flat'; event.source_refs = {}
        self.assertEqual(event_fields(event)['race_type'].text, '平地')

    def test_announced_purse_keeps_stage_until_actual_replaces_it(self):
        from types import SimpleNamespace
        from decimal import Decimal
        from stable.services.race_information_display import event_fields
        event=SimpleNamespace(country_region='united_states',status='scheduled',prize_amount=Decimal('300000'),prize_currency='USD',
            source_refs={'us_pre_race_schedule':{'prize_stage':'announced','prize_amount':'300000','prize_currency':'USD'}})
        self.assertIn('计划',event_fields(event)['prize'].text)
        event.status='finished'
        self.assertIn('计划',event_fields(event)['prize'].text)
        event.source_refs['us_pre_race_schedule']['prize_stage']='superseded_by_result'
        self.assertNotIn('计划',event_fields(event)['prize'].text)

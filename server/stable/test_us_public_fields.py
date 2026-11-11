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

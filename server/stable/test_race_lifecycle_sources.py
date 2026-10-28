"""P02 T01/T02：地区准入不能省略澳德及 AE/SA，也不扩大中东范围。"""
from django.test import SimpleTestCase

from stable.services.race_data_source_adapters import parse_multisource_policy
from stable.test_race_multisource_identity import NOW, policy_payload


class LifecycleRegionTests(SimpleTestCase):
    def test_nine_region_routes_preserve_country_scope(self):
        for region, country, tz in (
            ('australia', 'australia', 'Australia/Sydney'),
            ('germany', 'germany', 'Europe/Berlin'),
            ('united_arab_emirates', 'middle_east', 'Asia/Dubai'),
            ('saudi_arabia', 'middle_east', 'Asia/Riyadh'),
        ):
            with self.subTest(region=region):
                raw = policy_payload(provider='reference', region=region)
                raw['routes'][0].update(country_region=country, timezone=tz)
                try:
                    parsed = parse_multisource_policy(raw, now=NOW)
                except ValueError as exc:
                    self.fail(f'目标地区无法进入受控来源流程: {region}: {exc}')
                self.assertEqual(parsed.routes[0].country_region, country)
                from stable.services.race_data_sync_pipeline import _EVENT_REGIONS_BY_CONTRACT_REGION
                self.assertIn(country, _EVENT_REGIONS_BY_CONTRACT_REGION.get(region, ()), '名单 writer 未接入地区映射')

    def test_unnamed_middle_east_or_other_countries_remain_rejected(self):
        for region in ('middle_east', 'qatar', 'bahrain'):
            with self.subTest(region=region), self.assertRaises(ValueError):
                parse_multisource_policy(policy_payload(region=region), now=NOW)

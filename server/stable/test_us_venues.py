from pathlib import Path
from unittest import TestCase
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from stable.services.us_racing_sources import parse_toba_calendar


class USVenueTests(TestCase):
    def test_entire_annual_catalogue_has_venue_timezone(self):
        from stable.services.us_flat_results import VENUES
        raw = (Path(__file__).parent/'fixtures/us_automation/toba.html').read_bytes()
        annual = parse_toba_calendar(raw, url='https://toba.org/graded-stakes/2026-races/')
        for row in annual['items'] + annual['unresolved']:
            self.assertIn(row['venue'], VENUES)
            ZoneInfo(VENUES[row['venue']][2])

    def test_tracks_across_four_zones_and_dst(self):
        from stable.services.us_flat_results import VENUES
        for code, winter, summer in [('SA', -8, -7), ('KD', -6, -5), ('SUN', -7, -6), ('SAR', -5, -4)]:
            zone = ZoneInfo(VENUES[code][2])
            self.assertEqual(datetime(2026,1,1,tzinfo=zone).utcoffset().total_seconds(), winter*3600)
            self.assertEqual(datetime(2026,7,1,tzinfo=zone).utcoffset().total_seconds(), summer*3600)
        self.assertEqual(datetime(2026,9,6,0,30,tzinfo=timezone.utc).astimezone(ZoneInfo(VENUES['DMR'][2])).date().isoformat(), '2026-09-05')

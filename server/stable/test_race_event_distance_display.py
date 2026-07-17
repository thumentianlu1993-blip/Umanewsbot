from django.test import SimpleTestCase

from stable.models import RaceEvent, RaceEventSurface, RacingRegion


class RaceEventDistanceDisplayTests(SimpleTestCase):
    def event(self, distance_text, region, surface=RaceEventSurface.TURF):
        return RaceEvent(
            year=2026,
            original_name="Test Race",
            chinese_name="测试赛事",
            country_region=region,
            racecourse="Test",
            grade_text="G1",
            surface=surface,
            distance_text=distance_text,
        )

    def test_non_numeric_distance_is_preserved(self):
        event = self.event("1m 2f", RacingRegion.UNITED_KINGDOM)
        self.assertEqual(event.display_distance_text, "1m 2f")

    def test_metric_regions_append_meters_to_numeric_distance(self):
        for region in (RacingRegion.JAPAN, RacingRegion.HONG_KONG, RacingRegion.FRANCE):
            with self.subTest(region=region):
                event = self.event("2400", region)
                self.assertEqual(event.display_distance_text, "2400米")

    def test_united_states_appends_furlongs_to_numeric_distance(self):
        event = self.event("9", RacingRegion.UNITED_STATES)
        self.assertEqual(event.display_distance_text, "9f")

    def test_united_kingdom_uses_surface_specific_unit(self):
        flat = self.event("6", RacingRegion.UNITED_KINGDOM)
        jumps = self.event("3.00", RacingRegion.UNITED_KINGDOM, RaceEventSurface.JUMPS)

        self.assertEqual(flat.display_distance_text, "6f")
        self.assertEqual(jumps.display_distance_text, "3m")

    def test_numeric_trailing_zeroes_are_removed(self):
        event = self.event("2.50", RacingRegion.UNITED_KINGDOM, RaceEventSurface.JUMPS)
        self.assertEqual(event.display_distance_text, "2.5m")

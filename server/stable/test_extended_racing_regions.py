from django.test import SimpleTestCase

from .models import RacingRegion


class ExtendedRacingRegionTests(SimpleTestCase):
    def test_new_regions_are_first_class_choices(self):
        self.assertEqual(RacingRegion.AUSTRALIA, "australia")
        self.assertEqual(RacingRegion.GERMANY, "germany")
        self.assertEqual(RacingRegion.MIDDLE_EAST, "middle_east")
        choices = dict(RacingRegion.choices)
        self.assertEqual(choices["australia"], "澳大利亚")
        self.assertEqual(choices["germany"], "德国")
        self.assertEqual(choices["middle_east"], "中东")

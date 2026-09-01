from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_france_wikipedia_history_winner_candidates.py")
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("wikipedia_history_winners", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class WikipediaWinnerQueryTests(unittest.TestCase):
    def test_adds_region_specific_race_queries(self):
        france = MODULE._query_candidates(
            {
                "country_region": "france",
                "series_key": "france-rothschild",
                "original_name": "Rothschild",
            }
        )
        ireland = MODULE._query_candidates(
            {
                "country_region": "ireland",
                "series_key": "ireland-fort-leney-novice-stp",
                "original_name": "Fort Leney Novice Stp.",
            }
        )
        united_states = MODULE._query_candidates(
            {
                "country_region": "united_states",
                "series_key": "united-states-test",
                "original_name": "Test",
            }
        )
        united_kingdom = MODULE._query_candidates(
            {
                "country_region": "united_kingdom",
                "series_key": "united-kingdom-gold-cup-ascot-flat-20-turf",
                "original_name": "Gold Cup",
            }
        )
        self.assertIn("Prix Rothschild horse race", france)
        self.assertIn("Fort Leney Novice Chase horse race", ireland)
        self.assertIn("Test Stakes horse race", united_states)
        self.assertIn("Ascot Gold Cup horse race", united_kingdom)

    def test_title_match_ignores_discovery_suffix_but_not_identity(self):
        self.assertTrue(MODULE._title_matches("Prix Rothschild", ["Rothschild horse race"]))
        self.assertTrue(
            MODULE._title_matches("Prix Jean et Louis Romanet", ["Prix Jean Romanet"])
        )
        self.assertTrue(MODULE._title_matches("Test Stakes", ["Test Stakes horse race"]))
        self.assertFalse(
            MODULE._title_matches("Prix Marcel Boussac", ["Prix Rothschild horse race"])
        )


if __name__ == "__main__":
    unittest.main()

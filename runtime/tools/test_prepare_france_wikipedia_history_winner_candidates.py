from __future__ import annotations

import importlib.util
import csv
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


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

    def test_search_result_match_accepts_registered_and_sponsored_renames(self):
        self.assertTrue(
            MODULE._search_result_matches(
                "Betfair Chase",
                "A British horse race whose registered title is the <span>Lancashire Chase</span>.",
                ["Lancashire Chase", "Lancashire Chase horse race"],
                region="united_kingdom",
            )
        )
        self.assertTrue(
            MODULE._search_result_matches(
                "Dooley Insurance Group Champion Novice Chase",
                "An Irish horse race formerly called the Ellier Developments Novice Chase.",
                ["The Ellier Novice Chase", "The Ellier Novice Chase horse race"],
                region="ireland",
            )
        )
        self.assertTrue(
            MODULE._search_result_matches(
                "Tingle Creek Chase",
                "A Grade 1 National Hunt steeplechase horse race.",
                ["Tingle Creek Trophy Chase", "Tingle Creek Trophy Chase horse race"],
                region="united_kingdom",
            )
        )

    def test_search_result_match_rejects_same_name_in_wrong_country(self):
        self.assertFalse(
            MODULE._search_result_matches(
                "Concorde Stakes",
                "An Australian Thoroughbred horse race.",
                ["Concorde Stakes", "Concorde Stakes horse race"],
                region="ireland",
            )
        )
        self.assertFalse(
            MODULE._search_result_matches(
                "Diamond Stakes (Japan)",
                "A Japanese Thoroughbred horse race.",
                ["Diamond Stakes", "Diamond Stakes horse race"],
                region="ireland",
            )
        )
        self.assertTrue(
            MODULE._search_result_matches(
                "Concorde Stakes",
                "An Irish flat horse race at Tipperary Racecourse.",
                ["Concorde Stakes", "Concorde Stakes horse race"],
                region="ireland",
            )
        )

    def test_search_result_match_rejects_unrelated_horse_page(self):
        self.assertFalse(
            MODULE._search_result_matches(
                "Silviniaco Conti",
                "The horse won the Lancashire Chase in 2012 and 2014.",
                ["Lancashire Chase", "Lancashire Chase horse race"],
                region="united_kingdom",
            )
        )
        self.assertFalse(
            MODULE._search_result_matches(
                "Sword Dancer",
                "A racehorse who finished second in the Preakness Stakes.",
                ["Sword Dancer Stakes", "Sword Dancer Stakes horse race"],
                region="united_states",
            )
        )

    def test_reuses_frozen_current_record_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = root / "events.csv"
            with events.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["year", "slug", "series_key", "original_name", "country_region"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "year": 2020,
                        "slug": "france-known",
                        "series_key": "france-known",
                        "original_name": "Known",
                        "country_region": "france",
                    }
                )
            current = root / "current.jsonl"
            current.write_text(
                json.dumps(
                    {
                        "year": 2020,
                        "slug": "france-known",
                        "source_name": "wikipedia_winners_table",
                        "source_url": "https://en.wikipedia.org/wiki/Prix_Known",
                        "modules": {
                            "history_winners": {
                                "items": [{"winner_year": 2020, "horse_name": "Known Winner"}]
                            }
                        },
                        "metadata": {"wiki_title": "Prix Known"},
                    },
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            current_sources = root / "current-sources"
            MODULE.write_source_cache_text(
                current_sources / "source_wiki_page_prix_known.html",
                "<html>frozen official reference</html>",
                source_url="https://en.wikipedia.org/wiki/Prix_Known",
            )
            args = Namespace(
                output_dir=str(root / "output"),
                events_csv=str(events),
                current_history_jsonl=str(current),
                current_source_dir=str(current_sources),
                limit=0,
                allow_network=False,
                timeout_seconds=20,
                sleep_seconds=0.0,
                min_year=2005,
                allow_partial_history=False,
            )
            with mock.patch.object(MODULE, "_request_text") as request:
                result = MODULE.prepare(args)
            request.assert_not_called()
            self.assertEqual(result["events"], 1)
            self.assertEqual(result["history_items"], 1)


if __name__ == "__main__":
    unittest.main()

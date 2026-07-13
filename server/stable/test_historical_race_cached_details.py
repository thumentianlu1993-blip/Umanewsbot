from __future__ import annotations

import importlib.util
from pathlib import Path

from django.test import SimpleTestCase


TOOL = Path(__file__).resolve().parents[2] / "runtime/tools/prepare_cached_historical_race_details.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("cached_historical_details", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CachedHistoricalRaceDetailTests(SimpleTestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_equibase_yearbook_keeps_scratches_and_orders_runners_by_number(self):
        html = r'''
        <script>
        race["starters"] = new Array();
        race["starters"][0] = new Object();
        race["starters"][0]["programnumber"] = "7";
        race["starters"][0]["postposition"] = 5;
        race["starters"][0]["officialposition"] = 1;
        race["starters"][0]["odds"] = 350;
        race["starters"][0]["horse"]["name"] = "Winner";
        race["starters"][0]["jockey"]["firstname"] = "Jose";
        race["starters"][0]["jockey"]["lastname"] = "Ortiz";
        race["starters"][0]["trainer"]["firstname"] = "Jane";
        race["starters"][0]["trainer"]["lastname"] = "Doe";
        race["starters"][1] = new Object();
        race["starters"][1]["programnumber"] = "1";
        race["starters"][1]["postposition"] = 2;
        race["starters"][1]["officialposition"] = 1;
        race["starters"][1]["horse"]["name"] = "Runner Up";
        race["scratches"] = new Array();
        race["scratches"][0] = new Object();
        race["scratches"][0]["programnumber"] = "4";
        race["scratches"][0]["horse"]["name"] = "Did Not Run";
        race["scratches"][0]["scratchreason"] = "Veterinarian";
        race["scratches"][1] = new Object();
        race["scratches"][1]["programnumber"] = "SCR";
        race["scratches"][1]["horse"]["name"] = "Also Scratched";
        </script>
        '''

        runners, results, metadata = self.tool.parse_equibase_yearbook(html, source_url="https://example.test")

        self.assertEqual([row["horse_number"] for row in runners], ["1", "4", "7", "SCR-2"])
        self.assertEqual([row["running_status"] for row in runners], ["declared", "scratched", "declared", "scratched"])
        self.assertEqual([row["horse_name"] for row in results], ["Winner", "Runner Up"])
        self.assertEqual([row["finish_position"] for row in results], [1, 2])
        self.assertEqual([row["official_finish_position"] for row in results], [1, 1])
        self.assertEqual(results[0]["jockey_name"], "Jose Ortiz")
        self.assertEqual(metadata, {"runner_count": 4, "result_count": 2, "scratch_count": 2})

    def test_equibase_yearbook_rejects_empty_runner_data(self):
        with self.assertRaisesMessage(RuntimeError, "no starters"):
            self.tool.parse_equibase_yearbook("<html></html>", source_url="https://example.test")

    def test_nsa_pdf_columns_preserve_faller_without_result_position(self):
        def word(text, x0, top):
            return {"text": text, "x0": x0, "top": top}

        words = [
            word("01", 15, 180), word("WINNER", 49, 180), word("(IRE)", 90, 180),
            word("150", 194, 180), word("Mullins,", 214, 180), word("D", 250, 180),
            word("Owner", 297, 180), word("Keri", 423, 180), word("Brion", 445, 180),
            word("90,000", 538, 180),
            word("F", 15, 192), word("FALLER", 49, 192), word("152", 194, 192),
            word("Procter,", 214, 192), word("F", 250, 192), word("Owner", 297, 192),
            word("Jack", 423, 192), word("Fisher", 445, 192), word("0", 558, 192),
        ]

        runners, results, metadata = self.tool.parse_nsa_words(words, source_url="https://example.test/result.pdf")

        self.assertEqual([row["horse_name"] for row in runners], ["WINNER (IRE)", "FALLER"])
        self.assertEqual([row["running_status"] for row in runners], ["declared", "unknown"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["jockey_name"], "D Mullins")
        self.assertEqual(results[0]["trainer_name"], "Keri Brion")
        self.assertEqual(metadata, {"runner_count": 2, "result_count": 1, "non_finish_count": 1})

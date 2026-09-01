from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_hri_graded_winner_candidates.py")
SPEC = importlib.util.spec_from_file_location("prepare_hri_graded_winners", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


HTML = b"""
<p class="h3 text-primary"><a>Leopardstown</a></p>
<div class="race-result-item">
  <h2><a href="/results/race-result/?date=2025-02-01&race=1315&venue=LP">
    The Nathaniel Lacy &amp; Partners Solicitors Novice Hurdle (Grade 1)
  </a></h2>
  <table><tbody>
    <tr><td><strong>1st</strong></td><td></td><td>1</td><td>Final Demand (IRE)</td></tr>
    <tr><td><strong>2nd</strong></td><td>12 L</td><td>10</td><td>Wingmen</td></tr>
  </tbody></table>
</div>
"""


class HriOfficialWinnerTests(unittest.TestCase):
    def test_parses_organizer_official_graded_winner(self):
        rows = MODULE.parse_date_page(
            HTML,
            local_date="2025-02-01",
            source_evidence={
                "source_url": "https://www.hri.ie/results?date=2025-02-01",
                "sha256": "a" * 64,
            },
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["normalized_grade"], "G1")
        self.assertEqual(rows[0]["racecourse"], "Leopardstown")
        self.assertEqual(rows[0]["winner"]["horse_name"], "Final Demand")
        self.assertEqual(rows[0]["winner"]["country_suffix"], "IRE")

    def test_matches_sponsored_hri_title_to_registered_target(self):
        result = MODULE.parse_date_page(
            HTML,
            local_date="2025-02-01",
            source_evidence={
                "source_url": "https://www.hri.ie/results?date=2025-02-01",
                "sha256": "a" * 64,
            },
        )[0]
        target = {
            "target_key": "ireland:2025:ireland-golden-cygnet-novice-hurdle:jumps",
            "series_key": "ireland-golden-cygnet-novice-hurdle",
            "year": 2025,
            "country_region": "ireland",
            "grade_text": "G1",
            "racecourse": "Leopardstown",
            "canonical_name_original": "Golden Cygnet Novice Hurdle",
            "original_name": "Golden Cygnet Novice Hurdle [Nathaniel Lacy & Partners]",
        }

        matched, diagnostics = MODULE.match_target(result, [target])

        self.assertEqual(matched["target_key"], target["target_key"])
        self.assertGreaterEqual(diagnostics[0]["overlap"], 4)

    def test_rejects_same_grade_and_name_at_wrong_course(self):
        result = MODULE.parse_date_page(
            HTML,
            local_date="2025-02-01",
            source_evidence={
                "source_url": "https://www.hri.ie/results?date=2025-02-01",
                "sha256": "a" * 64,
            },
        )[0]
        target = {
            "target_key": "ireland:2025:wrong:jumps",
            "year": 2025,
            "country_region": "ireland",
            "grade_text": "G1",
            "racecourse": "Fairyhouse",
            "canonical_name_original": "Nathaniel Lacy Novice Hurdle",
            "original_name": "Nathaniel Lacy Novice Hurdle",
        }

        matched, diagnostics = MODULE.match_target(result, [target])

        self.assertIsNone(matched)
        self.assertEqual(diagnostics, [])


if __name__ == "__main__":
    unittest.main()

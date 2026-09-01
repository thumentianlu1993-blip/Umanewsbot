from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("audit_hri_graded_winner_candidates.py")
SPEC = importlib.util.spec_from_file_location("audit_hri_graded_winners", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


HTML = """
<div class="race-result-item">
  <h2><a href="/results/race-result/?date=2025-02-01&amp;race=1315&amp;venue=LP">
    The Nathaniel Lacy Novice Hurdle (Grade 1)
  </a></h2>
  <table><tbody>
    <tr><td>1st</td><td></td><td>1</td><td>Final Demand (IRE)</td></tr>
    <tr><td>2nd</td><td>12 L</td><td>2</td><td>Wingmen</td></tr>
  </tbody></table>
</div>
"""


class HriAuditTests(unittest.TestCase):
    def test_rechecks_winner_from_frozen_official_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.html"
            path.write_text(HTML, encoding="utf-8")
            winner = MODULE._winner_from_frozen_page(
                path,
                result_url=(
                    "https://www.hri.ie/results/race-result/"
                    "?date=2025-02-01&race=1315&venue=LP"
                ),
                race_name="The Nathaniel Lacy Novice Hurdle (Grade 1)",
            )

        self.assertEqual(winner, "Final Demand")

    def test_seed_is_target_key_bound_and_profile_fallback_enabled(self):
        candidate = {
            "target_key": "ireland:2025:golden-cygnet:jumps",
            "local_date": "2025-02-01",
            "edition_year": 2025,
            "race_name": "The Nathaniel Lacy Novice Hurdle (Grade 1)",
            "racecourse": "Leopardstown",
            "normalized_grade": "G1",
            "result_url": (
                "https://www.hri.ie/results/race-result/"
                "?date=2025-02-01&race=1315&venue=LP"
            ),
            "winner": {
                "horse_name": "Final Demand",
                "country_suffix": "IRE",
                "finish_position": 1,
            },
            "source_evidence": {
                "source_url": "https://www.hri.ie/results?date=2025-02-01",
                "sha256": "a" * 64,
            },
        }
        target = {
            "target_key": candidate["target_key"],
            "year": 2025,
            "canonical_name_original": "Golden Cygnet Novice Hurdle",
            "original_name": "Golden Cygnet Novice Hurdle [Nathaniel Lacy]",
            "racecourse": "Leopardstown",
            "discipline": "jumps",
        }

        seed = MODULE._seed(candidate, target)

        self.assertEqual(seed["schema_version"], "targeted-horse-seed.v2")
        self.assertEqual(seed["target"]["target_key"], candidate["target_key"])
        self.assertTrue(seed["allow_profile_only_if_target_missing"])
        self.assertEqual(seed["country_suffix"], "IRE")


if __name__ == "__main__":
    unittest.main()

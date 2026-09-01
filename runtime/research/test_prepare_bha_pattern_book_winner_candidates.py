from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("prepare_bha_pattern_book_winner_candidates.py")
SPEC = importlib.util.spec_from_file_location("prepare_bha_pattern_book", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


FLAT = """
[[BHA_PAGE_0037]]
TO CLOSE BY NOON ON APRIL 7th
NEWBURY
Saturday, April 12th
THE DUBAI DUTY FREE STAKES (CLASS 1)
(Registered as the Fred Darling Stakes)
(Group 3)
TOTAL PRIZE FUND £85,000
HORSE NAME AGE/WEIGHT JOCKEY TRAINER SP RNRS
2024 Folgaria (IRE) 3-9-2 Hollie Doyle Marco Botti 5/1 6
2023 Remarquee 3-9-2 Rob Hornby Ralph Beckett 7/2 12
2022 Wild Beauty 3-9-0 William Buick Charlie Appleby 3/1 12
2021 Alcohol Free (IRE) 3-9-0 Oisin Murphy Andrew Balding 9/4 17
"""

JUMP = """
[[BHA_PAGE_0039]]
TO CLOSE BY NOON ON NOVEMBER 4th
with supplementary entries on November 17th
HAYDOCK PARK
Saturday, November 22nd
THE BETFAIR STEEPLE CHASE (CLASS 1) (Grade 1)
(Registered as The LANCASHIRE STEEPLE CHASE) (GBB RACE)
TOTAL PRIZE FUND £200,000
HORSE NAME AGE/WEIGHT JOCKEY TRAINER SP RNRS
2024/2025 Royale Pagaille (FR) 10-11-10 Charlie Deutsch Venetia Williams 11/4 7
2023/2024 Royale Pagaille (FR) 9-11-10 Charlie Deutsch Venetia Williams 5/1 4
2022/2023 Protektorat (FR) 7-11-10 Harry Skelton Dan Skelton 15/2 5
*2021/2022 Not So Sleepy 9-11-7 Jonathan Burke Hughie Morrison 18/1 6
*2021/2022 Epatante (FR) 7-11-0 Aidan Coleman Nicky Henderson 11/8 6
"""

OLD_JUMP = """
[[BHA_PAGE_0023]]
CLOSED ON MAY4 th 2020
HAYDOCK PARK
Saturday,M ay 9th
THE PERTEMPS NETWORK SWINTON HANDICAP HURDLE RACE (CLASS 1)
(Grade 3)
HORSE NAME AGE/WEIGHT JOCKEY TRAINER SP RNRS
2020/2021 Abandoned
2019/2020 Le Patriote (FR) 7-11-12 Sam Twiston-Davies Richard Newland 20/1 17
2018/2019 Silver Streak (IRE) 5-10-2 Adam Wedge Evan Williams 13/2 16
2017/2018 John Constable (IRE) 6-11-2 Davy Russell Evan Williams 5/1 17
2016/2017 Drop Out Joe 8-10-3 Graham Watters Charlie Longsdon 20/1 19
"""


class BhaPatternBookTests(unittest.TestCase):
    def test_flat_book_emits_four_years_and_registered_alias(self):
        rows = MODULE.parse_pattern_book(
            FLAT,
            discipline="flat",
            source_evidence={"sha256": "a" * 64},
        )

        self.assertEqual(
            [row["edition_year"] for row in rows], [2021, 2022, 2023, 2024]
        )
        self.assertIn("Fred Darling Stakes", rows[0]["race_name_aliases"])
        self.assertEqual(rows[-1]["winner"]["horse_name"], "Folgaria")
        self.assertEqual(rows[-1]["winner"]["country_suffix"], "IRE")
        self.assertEqual(rows[0]["page_number"], 37)

    def test_jump_season_maps_to_calendar_year_for_autumn_race(self):
        rows = MODULE.parse_pattern_book(
            JUMP,
            discipline="jumps",
            source_evidence={"sha256": "b" * 64},
        )

        self.assertEqual(
            [row["edition_year"] for row in rows], [2021, 2022, 2023, 2024]
        )
        self.assertEqual(rows[-1]["winner"]["horse_name"], "Royale Pagaille")
        self.assertEqual(len(rows[0]["co_winners"]), 2)
        self.assertEqual(rows[0]["winner"]["horse_name"], "Not So Sleepy")

    def test_matches_registered_name_and_course_park_variant(self):
        result = MODULE.parse_pattern_book(
            JUMP,
            discipline="jumps",
            source_evidence={"sha256": "b" * 64},
        )[-1]
        target = {
            "target_key": "united_kingdom:2024:lancashire-steeple-chase:jumps",
            "series_key": "lancashire-steeple-chase",
            "year": 2024,
            "country_region": "united_kingdom",
            "discipline": "jumps",
            "grade_text": "G1",
            "racecourse": "Haydock",
            "canonical_name_original": "Lancashire Stp.",
            "original_name": "Lancashire Stp. [Betfair]",
        }

        matched, diagnostics = MODULE.match_target(result, [target])

        self.assertEqual(matched["target_key"], target["target_key"])
        self.assertEqual(diagnostics[0]["overlap"], 3)

    def test_global_target_conflict_keeps_only_unique_higher_confidence_block(self):
        base = {
            "target_key": "united_kingdom:2024:example:flat",
            "schema_version": MODULE.CANDIDATE_SCHEMA,
            "block_number": 1,
            "match_diagnostics": [
                {
                    "target_key": "united_kingdom:2024:example:flat",
                    "score": 1.0,
                    "overlap": 2,
                    "exact_tokens": True,
                    "scheduled_course_matches_target_default": True,
                }
            ],
        }
        lower = {
            **base,
            "block_number": 2,
            "match_diagnostics": [
                {
                    **base["match_diagnostics"][0],
                    "exact_tokens": False,
                }
            ],
        }

        resolved, rejected = MODULE.resolve_global_target_conflicts([lower, base], [])

        self.assertEqual(resolved, [base])
        self.assertEqual(
            rejected[0]["match_rejection"], "duplicate_target_lower_confidence"
        )

    def test_old_jump_book_handles_ocr_spaced_month_and_closed_on_heading(self):
        rows = MODULE.parse_pattern_book(
            OLD_JUMP,
            discipline="jumps",
            source_evidence={"sha256": "c" * 64},
        )

        self.assertEqual(
            [row["edition_year"] for row in rows], [2017, 2018, 2019, 2020]
        )
        self.assertEqual(rows[0]["winner"]["horse_name"], "Drop Out Joe")


if __name__ == "__main__":
    unittest.main()

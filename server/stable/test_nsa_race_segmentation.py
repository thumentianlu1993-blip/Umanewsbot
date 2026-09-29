from __future__ import annotations

import importlib.util
from pathlib import Path

from django.test import SimpleTestCase


TOOL_PATH = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "prepare_cached_historical_race_details.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("cached_details_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _word(text, x0, top):
    return {"text": text, "x0": x0, "top": top}


def _row(order, horse, top, *, purse="0"):
    """构造一行 NSA 结果词流（与真实列位一致）。"""
    return [
        _word(order, 15, top),
        *([_word(part, 49 + i * 40, top) for i, part in enumerate(horse.split())]),
        _word("150", 194, top),
        _word("Rider,", 214, top), _word("J", 250, top),
        _word("Owner", 297, top),
        _word("Trainer", 423, top),
        _word(purse, 538, top),
    ]


TWO_RACE_WORDS = [
    # 头部
    _word("National", 50, 19), _word("Steeplechase", 120, 19), _word("Association", 220, 19),
    _word("Race", 50, 35), _word("Results", 100, 35), _word("Report", 160, 35),
    _word("Colonial", 50, 50), _word("Cup", 110, 50),
    # 1st Race： maiden hurdle
    _word("1st", 50, 138), _word("Race", 80, 138),
    _word("Maiden", 50, 139), _word("Hurdle.", 110, 139),
    *_row("01", "FIRST WINNER", 150, purse="18,000"),
    *_row("02", "FIRST SECOND", 161, purse="5,400"),
    # 2nd Race：Colonial Cup 目标场
    _word("2nd", 50, 252), _word("Race", 80, 252),
    _word("The", 50, 253), _word("Colonial", 70, 253), _word("Cup", 130, 253),
    _word("Stakes.", 170, 253),
    *_row("01", "CUP WINNER", 265, purse="30,000"),
    *_row("PU", "CUP PULLED", 276, purse="0"),
]


class NsaRaceSegmentationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_tool()

    def test_without_marker_keeps_legacy_flat_behavior(self):
        runners, results, meta = self.module.parse_nsa_words(TWO_RACE_WORDS, source_url="https://example.test/x.pdf")
        self.assertEqual(len(runners), 4)
        self.assertEqual(len(results), 3)

    def test_marker_by_race_name_selects_only_target_section(self):
        runners, results, meta = self.module.parse_nsa_words(
            TWO_RACE_WORDS, source_url="https://example.test/x.pdf", race_marker="Colonial Cup"
        )
        self.assertEqual([r["horse_name"] for r in runners], ["CUP WINNER", "CUP PULLED"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["horse_name"], "CUP WINNER")

    def test_marker_by_ordinal_section(self):
        runners, results, meta = self.module.parse_nsa_words(
            TWO_RACE_WORDS, source_url="https://example.test/x.pdf", race_marker="2nd Race"
        )
        self.assertEqual([r["horse_name"] for r in runners], ["CUP WINNER", "CUP PULLED"])

    def test_marker_not_found_fails_closed(self):
        with self.assertRaises(RuntimeError):
            self.module.parse_nsa_words(TWO_RACE_WORDS, source_url="https://example.test/x.pdf", race_marker="不存在")

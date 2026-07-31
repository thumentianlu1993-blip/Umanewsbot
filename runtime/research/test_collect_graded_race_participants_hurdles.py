#!/usr/bin/env python3
"""年度参赛马 collector 的无马号跨栏赛 RED 合同。

fixture 全部离线且已脱敏，只验证 participant identity，不访问公网或 Django。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("collect_graded_race_participants.py")


def load_collector(testcase: unittest.TestCase):
    testcase.assertTrue(
        SCRIPT_PATH.is_file(),
        "目标入口 runtime/research/collect_graded_race_participants.py 不存在",
    )
    spec = importlib.util.spec_from_file_location(
        "graded_race_participants_hurdle_red", SCRIPT_PATH
    )
    testcase.assertIsNotNone(spec)
    testcase.assertIsNotNone(spec.loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def result_row(
    *,
    position: str,
    number: str,
    name: str,
    profile_id: int | None,
) -> dict[str, str]:
    return {
        "raw_finish_status": position,
        "horse_number": number,
        "horse_display_name": name,
        "profile_url": (
            f"https://umafans.run/horses/{profile_id}/"
            if profile_id is not None
            else ""
        ),
    }


class HurdleHorseNumberContractTests(unittest.TestCase):
    def test_all_supported_missing_number_placeholders_normalize_to_empty(self):
        collector = load_collector(self)
        self.assertTrue(
            hasattr(collector, "normalize_horse_number"),
            "collector 必须提供 identity/output 共用的 normalize_horse_number",
        )

        for raw in ("", "-", "–", "—"):
            with self.subTest(raw=raw):
                self.assertEqual(collector.normalize_horse_number(raw), "")

    def test_two_dash_number_horses_with_distinct_profiles_are_both_preserved(self):
        collector = load_collector(self)
        rows = [
            result_row(
                position="1",
                number="-",
                name="Hurdle Runner Alpha",
                profile_id=91001,
            ),
            result_row(
                position="2",
                number="-",
                name="Hurdle Runner Beta",
                profile_id=91002,
            ),
        ]

        parsed = collector.parse_result_rows(rows)

        self.assertEqual(
            [row["horse_display_name"] for row in parsed["occurrences"]],
            ["Hurdle Runner Alpha", "Hurdle Runner Beta"],
        )
        self.assertEqual(
            [row["horse_number"] for row in parsed["occurrences"]],
            ["", ""],
        )

    def test_smithwick_style_all_dash_fixture_completes_without_number_conflict(self):
        collector = load_collector(self)
        rows = [
            result_row(
                position=str(position),
                number="-",
                name=f"Smithwick Fixture Horse {position}",
                profile_id=92000 + position,
            )
            for position in range(1, 6)
        ]

        parsed = collector.parse_result_rows(rows)

        self.assertEqual(parsed["result_rows_with_horse"], 5)
        self.assertEqual(len(parsed["occurrences"]), 5)
        self.assertEqual(
            [row["horse_number"] for row in parsed["occurrences"]],
            [""] * 5,
        )
        self.assertEqual(
            len({row["profile_url"] for row in parsed["occurrences"]}),
            5,
        )

    def test_each_dash_variant_is_normalized_before_identity_and_output(self):
        collector = load_collector(self)
        rows = [
            result_row(
                position=str(position),
                number=number,
                name=f"Placeholder Horse {position}",
                profile_id=93000 + position,
            )
            for position, number in enumerate(("", "-", "–", "—"), start=1)
        ]

        parsed = collector.parse_result_rows(rows)

        self.assertEqual(len(parsed["occurrences"]), 4)
        self.assertEqual(
            [row["horse_number"] for row in parsed["occurrences"]],
            [""] * 4,
        )

    def test_alphanumeric_number_1a_is_not_treated_as_placeholder(self):
        collector = load_collector(self)

        parsed = collector.parse_result_rows(
            [
                result_row(
                    position="1",
                    number="1A",
                    name="Coupled Entry Alpha",
                    profile_id=94001,
                )
            ]
        )

        self.assertEqual(parsed["occurrences"][0]["horse_number"], "1A")

    def test_same_real_number_for_different_horses_still_fails_closed(self):
        collector = load_collector(self)
        rows = [
            result_row(
                position="1",
                number="7",
                name="Number Conflict Alpha",
                profile_id=95001,
            ),
            result_row(
                position="2",
                number="7",
                name="Number Conflict Beta",
                profile_id=95002,
            ),
        ]

        with self.assertRaisesRegex(ValueError, "horse number identity conflict: 7"):
            collector.parse_result_rows(rows)

    def test_missing_number_without_profile_uses_normalized_full_name(self):
        collector = load_collector(self)
        rows = [
            result_row(
                position="1",
                number="—",
                name="Name Fallback Alpha",
                profile_id=None,
            ),
            result_row(
                position="2",
                number="–",
                name="Name Fallback Beta",
                profile_id=None,
            ),
        ]

        parsed = collector.parse_result_rows(rows)

        self.assertEqual(
            [row["horse_display_name"] for row in parsed["occurrences"]],
            ["Name Fallback Alpha", "Name Fallback Beta"],
        )
        self.assertEqual(
            [row["horse_number"] for row in parsed["occurrences"]],
            ["", ""],
        )

    def test_missing_number_same_normalized_name_without_profile_is_ambiguous(self):
        collector = load_collector(self)
        rows = [
            result_row(
                position="1",
                number="",
                name="Ambiguous Hurdle Horse",
                profile_id=None,
            ),
            result_row(
                position="2",
                number="-",
                name="  Ambiguous   Hurdle Horse  ",
                profile_id=None,
            ),
        ]

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            collector.parse_result_rows(rows)


if __name__ == "__main__":
    unittest.main()

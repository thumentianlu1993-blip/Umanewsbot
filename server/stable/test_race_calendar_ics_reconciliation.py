from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase


TOOL_PATH = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "reconcile_race_calendar_vs_ics.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("reconcile_race_calendar_vs_ics_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _ics_row(region, year, series_key, name, grade="G1"):
    tool = _load_tool()
    return {
        "region": region,
        "year": year,
        "series_key": series_key,
        "name": name,
        "canonical": name,
        "grade": grade,
        "racecourse": "Sha Tin",
        "discipline": "flat",
        "norm": tool._normalize_name(name),
        "norm_canonical": tool._normalize_name(name),
    }


def _event(**overrides):
    tool = _load_tool()
    base = {
        "id": "1",
        "year": 2025,
        "slug": "hong-kong-cup",
        "series_key": "hong-kong-hong-kong-cup",
        "original_name": "Hong Kong Cup",
        "chinese_name": "香港杯",
        "region": "hong_kong",
        "racecourse": "Sha Tin",
        "grade": "G1",
        "local_date": date(2025, 12, 14),
        "status": "finished",
        "visibility_status": "published",
        "result_count": 12,
        "norm": tool._normalize_name("Hong Kong Cup"),
        "norm_zh": tool._normalize_name("香港杯"),
    }
    base.update(overrides)
    return base


class ReconcileRaceCalendarVsIcsTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_tool()

    def test_series_key_match_and_summary(self):
        ics = [_ics_row("hong_kong", 2026, "hong-kong-hong-kong-cup", "Hong Kong Cup")]
        events = [_event()]

        result = self.module.reconcile(events, ics, {}, as_of=date(2026, 9, 27))

        self.assertEqual(result["missing_in_production"], 0)
        self.assertEqual(result["summary"]["hong_kong"]["2026"], {"expected": 1, "matched": 1, "production_events": 1})

    def test_missing_in_production_is_reported(self):
        ics = [_ics_row("ireland", 2025, "ireland-irish-champion", "Irish Champion S.")]

        result = self.module.reconcile([], ics, {}, as_of=date(2026, 9, 27))

        self.assertEqual(result["missing_in_production"], 1)
        self.assertEqual(result["summary"]["ireland"]["2025"]["missing_in_production"], 1)

    def test_southern_season_maps_december_date_to_next_ics_year(self):
        # 香港 2025-12-14 属于 2025/26 马季，对应 ICS 2026 年度
        self.assertEqual(self.module._ics_year_for("hong_kong", date(2025, 12, 14), 2025), 2026)
        # 澳洲 2026-03 属于 2025/26 赛季，对应 ICS 2026 年度
        self.assertEqual(self.module._ics_year_for("australia", date(2026, 3, 15), 2026), 2026)
        # 北半球按日历年
        self.assertEqual(self.module._ics_year_for("france", date(2025, 10, 5), 2025), 2025)

    def test_year_mismatch_and_missing_results_are_flagged(self):
        # 香港 2024-12-08 属于 2024/25 马季，对应 ICS 2025 年度
        ics = [_ics_row("hong_kong", 2025, "hong-kong-hong-kong-cup", "Hong Kong Cup")]
        # 马季错位：实际 2024-12-08 举办却记为 year=2025
        events = [_event(year=2025, local_date=date(2024, 12, 8), result_count=0)]

        result = self.module.reconcile(events, ics, {}, as_of=date(2026, 9, 27))

        issues = {row["issue"] for row in result["review_rows"]}
        self.assertTrue(any("year_mismatch_review" in issue for issue in issues))
        self.assertTrue(any("finished_without_results" in issue for issue in issues))

    def test_unmatched_event_keeps_quality_issues(self):
        events = [_event(id="7", series_key="", original_name="", norm="", year=2025, local_date=date(2024, 12, 8), result_count=0)]

        result = self.module.reconcile(events, [], {}, as_of=date(2026, 9, 27))

        issue = result["review_rows"][0]["issue"]
        self.assertIn("production_not_matched_to_ics", issue)
        self.assertIn("year_mismatch_review", issue)
        self.assertIn("finished_without_results", issue)

    def test_alias_match_uses_aliases_export(self):
        ics = [_ics_row("japan", 2025, "japan-japan-cup", "Japan Cup")]
        events = [
            _event(
                id="9",
                region="japan",
                series_key="",
                original_name="ジャパンカップ",
                norm=self.module._normalize_name("ジャパンカップ"),
                local_date=date(2025, 11, 30),
            )
        ]
        aliases = {"9": [self.module._normalize_name("Japan Cup")]}

        result = self.module.reconcile(events, ics, aliases, as_of=date(2026, 9, 27))

        self.assertEqual(result["missing_in_production"], 0)
        self.assertEqual(result["review_rows"], [])

    def test_duplicate_production_events_for_same_ics_row_are_flagged(self):
        ics = [_ics_row("hong_kong", 2026, "hong-kong-hong-kong-cup", "Hong Kong Cup")]
        events = [_event(id="1"), _event(id="2", slug="hong-kong-cup-old")]

        result = self.module.reconcile(events, ics, {}, as_of=date(2026, 9, 27))

        dup_issues = [row for row in result["review_rows"] if row["issue"] == "duplicate_same_day_events_for_ics_row"]
        self.assertEqual(len(dup_issues), 2)

    def test_same_series_distinct_dates_are_not_flagged_as_duplicates(self):
        # ICS 同键归并的多场不同日期比赛（如 Newbury 全年多场 Gold Cup 让赛）不是重复
        ics = [_ics_row("united_kingdom", 2025, "united-kingdom-gold-cup-stp", "Gold Cup H. Stp.")]
        events = [
            _event(id="1", region="united_kingdom", series_key="united-kingdom-gold-cup-stp", local_date=date(2025, 2, 8)),
            _event(id="2", region="united_kingdom", series_key="united-kingdom-gold-cup-stp", local_date=date(2025, 11, 29)),
        ]

        result = self.module.reconcile(events, ics, {}, as_of=date(2026, 9, 27))

        self.assertFalse([row for row in result["review_rows"] if "duplicate" in row["issue"]])

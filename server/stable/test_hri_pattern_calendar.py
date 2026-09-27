"""HRI 官方赛历（平地 / 障碍 Pattern Book 文本）解析测试。

被测模块：runtime/tools/prepare_hri_pattern_calendar.py
fixture：server/stable/fixtures/hri/ 下由 pdfplumber 从官方 PDF 摘录的文本。
测试中禁止访问网络。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "hri"

FLAT_2025_URL = "https://www.hri-ras.ie/getmedia/27b1d146-9bba-4c0d-978a-efa82f2b9ebf/2025-FlatPattBook.pdf"
FLAT_2026_URL = "https://www.hri-ras.ie/getmedia/9101de16-0d77-430d-a30d-9b5458c93c35/2026-FlatPattBook.pdf"
NH_URL = "https://www.hri-ras.ie/getmedia/40a844be-2112-426b-a688-2a870c7f5bc2/2026-2027-NHPatternBooklet-Part1.pdf"

# NH 2026/2027 赛季 Part 1 覆盖 5-12 月（正文页证实 SATURDAY, 9TH MAY, 2026），
# 1-4 月归赛季次年（Part 2，不在本 fixture 内）。
NH_YEAR_MAP = {**{month: 2026 for month in range(5, 13)}, **{month: 2027 for month in range(1, 5)}}


def _load_module():
    path = TOOLS / "prepare_hri_pattern_calendar.py"
    spec = importlib.util.spec_from_file_location("prepare_hri_pattern_calendar_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class HriFlatPatternBookTests(SimpleTestCase):
    """平地 Pattern Book 的 GROUP 1, 2 & 3 索引节解析。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_module()
        cls.text_2025 = (FIXTURES / "hri_2025_flat_pattern_book_excerpt.txt").read_text(encoding="utf-8")
        cls.text_2026 = (FIXTURES / "hri_2026_flat_pattern_book_excerpt.txt").read_text(encoding="utf-8")
        cls.rows_2025 = cls.module.parse_flat_pattern_text(cls.text_2025, year=2025)
        cls.rows_2026 = cls.module.parse_flat_pattern_text(cls.text_2026, year=2026)

    def test_2025_group_section_row_count(self):
        self.assertEqual(len(self.rows_2025), 72)

    def test_2026_group_section_row_count(self):
        self.assertEqual(len(self.rows_2026), 72)

    def test_2025_grade1_count(self):
        self.assertEqual(sum(row["grade_text"] == "Gr 1" for row in self.rows_2025), 13)

    def test_2026_grade1_count(self):
        self.assertEqual(sum(row["grade_text"] == "Gr 1" for row in self.rows_2026), 14)

    def test_only_group_grades_are_collected(self):
        # fixture 在索引节后保留 LISTED 节与总览页行，均不得进入结果
        for row in self.rows_2025 + self.rows_2026:
            self.assertIn(row["grade_text"], ("Gr 1", "Gr 2", "Gr 3"))
            self.assertNotIn(row["racecourse"], ("CU", "NS", "TP", "LP", "DK", "FH"))

    def test_irish_derby_2025_row(self):
        row = next(row for row in self.rows_2025 if row["series_key"] == "ireland-irish-derby")
        self.assertEqual(row["local_date"], "2025-06-29")
        self.assertEqual(row["racecourse"], "Curragh")
        self.assertEqual(row["canonical_name_original"], "Irish Derby")
        self.assertEqual(row["grade_text"], "Gr 1")
        self.assertEqual(row["distance_text"], "12f")
        self.assertEqual(row["discipline"], "flat")
        self.assertEqual(row["source_scope"], "official_calendar")
        self.assertEqual(row["country_region"], "ireland")
        self.assertEqual(row["year"], "2025")
        self.assertEqual(row["record_type"], "calendar")
        self.assertEqual(row["expectation_status"], "held")
        self.assertEqual(row["source_refs"]["distance_unit"], "furlong")
        self.assertEqual(row["source_refs"]["stakes_raw"], "1,250,000")
        self.assertEqual(row["source_refs"]["age_text"], "3")
        self.assertEqual(row["source_refs"]["sex_text"], "C&F")

    def test_irish_champion_stakes_2025_row(self):
        row = next(row for row in self.rows_2025 if row["series_key"] == "ireland-irish-champion-stakes")
        self.assertEqual(row["local_date"], "2025-09-13")
        self.assertEqual(row["racecourse"], "Leopardstown")
        self.assertEqual(row["grade_text"], "Gr 1")
        self.assertEqual(row["distance_text"], "10f")

    def test_distance_text_keeps_furlong_plus_suffix(self):
        row = next(row for row in self.rows_2025 if row["series_key"] == "ireland-gold-cup")
        self.assertEqual(row["local_date"], "2025-05-25")
        self.assertEqual(row["distance_text"], "10f+")
        self.assertEqual(row["source_refs"]["distance_unit"], "furlong")

    def test_surface_blank_with_source_note(self):
        # 官方年册不标注场地类型（Dundalk 为全天候场），surface 留空并注明
        for row in self.rows_2025:
            self.assertEqual(row["surface"], "")
            self.assertIn("surface", row["source_refs"]["surface_note"])

    def test_dangling_page_break_fragment_produces_no_phantom_row(self):
        anchor = "Jun 29 Curragh Irish Derby 3 C&F Gr 1 12f 1,250,000"
        self.assertIn(anchor, self.text_2025)
        for fragment in ("Jun \n", "Jun 28\n"):
            mutated = self.text_2025.replace(anchor, fragment + anchor)
            rows = self.module.parse_flat_pattern_text(mutated, year=2025)
            self.assertEqual(len(rows), 72)
            self.assertIn("ireland-irish-derby", {row["series_key"] for row in rows})

    def test_missing_row_fails_count_self_check(self):
        anchor = "Jun 29 Curragh Irish Derby 3 C&F Gr 1 12f 1,250,000\n"
        mutated = self.text_2025.replace(anchor, "")
        with self.assertRaisesRegex(Exception, "72"):
            self.module.parse_flat_pattern_text(mutated, year=2025)

    def test_unknown_year_fails_closed(self):
        with self.assertRaises(Exception):
            self.module.parse_flat_pattern_text(self.text_2025, year=2024)

    def test_header_year_mismatch_raises(self):
        with self.assertRaises(Exception):
            self.module.parse_flat_pattern_text(self.text_2025, year=2026)

    def test_series_key_date_pairs_are_unique(self):
        keys = [(row["series_key"], row["local_date"], row["racecourse"]) for row in self.rows_2025]
        self.assertEqual(len(keys), len(set(keys)))


class HriNationalHuntPatternBookTests(SimpleTestCase):
    """障碍 Pattern 年册（跨年赛季）解析。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_module()
        cls.text = (FIXTURES / "hri_2026_2027_nh_pattern_booklet_part1_excerpt.txt").read_text(encoding="utf-8")
        cls.rows = cls.module.parse_nh_pattern_text(
            cls.text, season_label="2026/2027", year_map=dict(NH_YEAR_MAP)
        )

    def test_total_row_count_matches_section_headers(self):
        # 3 bumpers + 29 hurdles + 27 steeplechases + 9 handicap hurdles + 12 handicap chases
        self.assertEqual(len(self.rows), 80)

    def test_all_rows_are_jump_discipline(self):
        for row in self.rows:
            self.assertEqual(row["discipline"], "jump")
            self.assertEqual(row["season_label"], "2026/2027")
            self.assertEqual(row["source_scope"], "official_calendar")

    def test_morgiana_hurdle_row(self):
        row = next(row for row in self.rows if row["series_key"] == "ireland-morgiana-hurdle")
        self.assertEqual(row["local_date"], "2026-11-21")
        self.assertEqual(row["racecourse"], "Punchestown")
        self.assertEqual(row["grade_text"], "Gr 1")
        self.assertEqual(row["distance_text"], "16f+")
        self.assertEqual(row["source_refs"]["stakes_raw"], "150,000")

    def test_july_maps_to_season_first_year(self):
        # Galway Hurdle 固定在 Galway 节周四：2026-07-30 为周四
        # 年册全名为 "Galway Hurdle Handicap Hurdle"（GRADED HANDICAP HURDLES 节）
        row = next(row for row in self.rows if "galway-hurdle" in row["series_key"])
        self.assertEqual(row["local_date"], "2026-07-30")
        self.assertEqual(row["racecourse"], "Galway")
        self.assertEqual(row["grade_text"], "Gr 3")

    def test_may_maps_to_season_first_year(self):
        # 年册正文页写明 SATURDAY, 9TH MAY, 2026
        row = next(row for row in self.rows if "tourist-attraction" in row["series_key"])
        self.assertEqual(row["local_date"], "2026-05-09")
        self.assertEqual(row["racecourse"], "Killarney")
        self.assertEqual(row["grade_text"], "Listed")

    def test_bumper_row_with_age_range(self):
        row = next(row for row in self.rows if "mucklemeg" in row["series_key"])
        self.assertEqual(row["local_date"], "2026-10-02")
        self.assertEqual(row["racecourse"], "Gowran Park")
        self.assertEqual(row["distance_text"], "16f")

    def test_listed_rows_keep_listed_grade(self):
        listed = [row for row in self.rows if row["grade_text"] == "Listed"]
        self.assertGreater(len(listed), 0)

    def test_year_map_missing_month_raises(self):
        broken = {month: 2026 for month in range(6, 13)}
        with self.assertRaises(Exception):
            self.module.parse_nh_pattern_text(self.text, season_label="2026/2027", year_map=broken)

    def test_season_label_mismatch_raises(self):
        with self.assertRaises(Exception):
            self.module.parse_nh_pattern_text(self.text, season_label="2025/2026", year_map=dict(NH_YEAR_MAP))

    def test_section_count_mismatch_raises(self):
        anchor = "Nov 21 Punchestown Morgiana Hurdle 4+ Gr 1 16f+ 150,000\n"
        self.assertIn(anchor, self.text)
        with self.assertRaises(Exception):
            self.module.parse_nh_pattern_text(
                self.text.replace(anchor, ""), season_label="2026/2027", year_map=dict(NH_YEAR_MAP)
            )


class HriPatternCalendarCliTests(SimpleTestCase):
    """CLI：URL=PATH 白名单校验与 JSONL 产出。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_module()

    def _argv(self, output_dir: Path):
        return [
            "--flat-txt", f"{FLAT_2025_URL}={FIXTURES / 'hri_2025_flat_pattern_book_excerpt.txt'}",
            "--flat-txt", f"{FLAT_2026_URL}={FIXTURES / 'hri_2026_flat_pattern_book_excerpt.txt'}",
            "--nh-txt", f"{NH_URL}={FIXTURES / 'hri_2026_2027_nh_pattern_booklet_part1_excerpt.txt'}",
            "--output-dir", str(output_dir),
        ]

    def test_cli_writes_jsonl_with_provenance(self):
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            rc = self.module.main(self._argv(output_dir))
            self.assertEqual(rc, 0)
            jsonl = output_dir / "hri_pattern_calendar.jsonl"
            rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 72 + 72 + 80)
            for row in rows:
                self.assertEqual(len(row["raw_source_cache_sha256"]), 64)
                self.assertTrue(row["raw_source_url"].startswith("https://"))
                self.assertTrue(row["raw_source_cache_path"])
            derby = next(row for row in rows if row["series_key"] == "ireland-irish-derby" and row["year"] == "2025")
            self.assertEqual(derby["raw_source_url"], FLAT_2025_URL)
            morgiana = next(row for row in rows if row["series_key"] == "ireland-morgiana-hurdle")
            self.assertEqual(morgiana["raw_source_url"], NH_URL)
            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["flat_counts"], {"2025": 72, "2026": 72})
            self.assertEqual(summary["nh_counts"], {"2026/2027": 80})
            self.assertEqual(summary["row_count"], 224)

    def test_cli_rejects_url_outside_allowlist(self):
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            argv = [
                "--flat-txt", f"https://evil.example/2025.txt={FIXTURES / 'hri_2025_flat_pattern_book_excerpt.txt'}",
                "--output-dir", str(output_dir),
            ]
            self.assertEqual(self.module.main(argv), 1)
            self.assertFalse((output_dir / "hri_pattern_calendar.jsonl").exists())

    def test_cli_rejects_plain_http(self):
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            argv = [
                "--flat-txt", f"http://www.hri-ras.ie/2025.txt={FIXTURES / 'hri_2025_flat_pattern_book_excerpt.txt'}",
                "--output-dir", str(output_dir),
            ]
            self.assertEqual(self.module.main(argv), 1)

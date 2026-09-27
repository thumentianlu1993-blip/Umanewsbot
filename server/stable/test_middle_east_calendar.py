"""中东（UAE + 沙特）赛历解析测试：DRC Carnival PDF 文本、ERA 整日场头、JCSA 赛日卡。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "middle_east"


def _load(name: str):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location(f"{path.stem}_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class DrcScheduleTextTests(SimpleTestCase):
    """Dubai Racing Carnival 2025-26 PDF 文本解析。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load("prepare_middle_east_calendar.py")

    def test_doubled_char_day_header_is_cleaned(self):
        # 叠字赛日头：PDF 加粗叠印导致每个字符重复两次
        text = (
            "FFRRIIDDAAYY,, 55 DDEECCEEMMBBEERR 22002255\n"
            "Al Garhoud Sprint - Listed 3YO+ 1200m Dirt AED 500,000\n"
            "Test Stakes - Group 3 3YO+ 1600m Dirt AED 700,000\n"
        )
        rows = self.module.parse_drc_schedule_text(text, season="2099-2100")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["local_date"], "2025-12-05")
        self.assertEqual(rows[0]["year"], 2025)

    def test_calendar_grid_interleaved_day_header_is_cleaned(self):
        # 日历网格数字交织进月份词：JA2NU8ARY -> JANUARY
        text = (
            "FRIDAY, 2 JA2NU8ARY 2026\n"
            "Dubawi Stakes - Group 3 4YO+ 1200m Dirt AED 700,000\n"
            "Zabeel Mile - Group 2 4YO+ 1600m Turf AED 850,000\n"
        )
        rows = self.module.parse_drc_schedule_text(text, season="2099-2100")
        self.assertEqual([row["local_date"] for row in rows], ["2026-01-02", "2026-01-02"])
        self.assertEqual(rows[0]["grade_text"], "G3")
        self.assertEqual(rows[1]["grade_text"], "G2")

    def test_full_fixture_counts_and_year_attribution(self):
        rows = self.module.parse_drc_schedule_text(
            _fixture("drc_carnival_2025-2026_schedule_text_layout.txt"), season="2025-2026"
        )
        # 2025-26 Carnival 16 赛日 = G1×2/G2×10/G3×12（其中 8 天有 Group 赛）
        self.assertEqual(len(rows), 24)
        grade_counts = {grade: sum(row["grade_text"] == grade for row in rows) for grade in ("G1", "G2", "G3")}
        self.assertEqual(grade_counts, {"G1": 2, "G2": 10, "G3": 12})
        self.assertEqual(len({row["local_date"] for row in rows}), 8)
        # 跨年归年：2025-11/12 月赛归 2025，2026 年 1-3 月归 2026
        by_name = {row["canonical_name_original"]: row for row in rows}
        self.assertEqual(by_name["Al Maktoum Mile"]["year"], 2025)
        self.assertEqual(by_name["Al Maktoum Mile"]["local_date"], "2025-12-19")
        challenge = by_name["Al Maktoum Challenge"]
        self.assertEqual(challenge["year"], 2026)
        self.assertEqual(challenge["local_date"], "2026-01-23")
        self.assertEqual(challenge["grade_text"], "G1")
        self.assertEqual(challenge["distance_text"], "1900")
        self.assertEqual(challenge["surface"], "dirt")
        self.assertEqual(challenge["racecourse"], "Meydan")
        self.assertEqual(challenge["series_key"], "uae-al-maktoum-challenge")
        self.assertEqual(challenge["country"], "uae")
        self.assertEqual(challenge["country_region"], "middle_east")
        self.assertEqual(challenge["season_label"], "2025-2026")
        self.assertEqual(challenge["record_type"], "timeline")
        # Listed 与条件赛/让赛不产行
        self.assertNotIn("Dubai Creek Mile", by_name)
        self.assertNotIn("Al Bastakiya", by_name)
        # 叠字赛日（12-05）与交织赛日（01-02）的 Group 行归属正确
        self.assertEqual(by_name["Dubawi Stakes"]["local_date"], "2026-01-02")
        # 雌马限定赛：名称不吞入 Fillies 后缀
        self.assertEqual(by_name["UAE Oaks"]["grade_text"], "G3")
        self.assertEqual(by_name["UAE Oaks"]["local_date"], "2026-02-20")

    def test_count_self_check_raises_on_mismatch(self):
        text = _fixture("drc_carnival_2025-2026_schedule_text_layout.txt")
        # 删掉一条 Group 行后计数自校验必须 fail closed
        broken = text.replace(
            "Al Maktoum Challenge - Group 1 4YO+ 1900m Dirt AED 3,680,000",
            "Al Maktoum Challenge - Listed 4YO+ 1900m Dirt AED 3,680,000",
        )
        self.assertNotEqual(broken, text)
        with self.assertRaises(RuntimeError):
            self.module.parse_drc_schedule_text(broken, season="2025-2026")

    def test_count_self_check_raises_on_missing_race_day(self):
        text = _fixture("drc_carnival_2025-2026_schedule_text_layout.txt")
        # 删掉一个无 Group 赛的赛日头，16 赛日计数校验同样 fail closed
        broken = text.replace("FRIDAY, 13 MARCH 2026", "REMOVED DAY HEADER")
        self.assertNotEqual(broken, text)
        with self.assertRaises(RuntimeError):
            self.module.parse_drc_schedule_text(broken, season="2025-2026")


class EraDayHeaderTests(SimpleTestCase):
    """ERA 整日页场头解析（DWC 赛日 2026-03-28）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load("prepare_middle_east_calendar.py")

    def test_dwc_day_headers(self):
        rows = self.module.parse_era_day_headers(
            _fixture("era_ajax_racecard-results-all_2026-03-28.html"), date="2026-03-28"
        )
        # 9 场中 Dubai Kahayla Classic 为阿拉伯马 G1，ICS UAE 章节不含阿拉伯马赛事，跳过
        self.assertEqual(len(rows), 8)
        grade_counts = {grade: sum(row["grade_text"] == grade for row in rows) for grade in ("G1", "G2", "G3")}
        self.assertEqual(grade_counts, {"G1": 5, "G2": 3, "G3": 0})
        names = {row["canonical_name_original"] for row in rows}
        self.assertNotIn("Dubai Kahayla Classic", names)
        by_name = {row["canonical_name_original"]: row for row in rows}
        dwc = by_name["Dubai World Cup"]
        self.assertEqual(dwc["local_date"], "2026-03-28")
        self.assertEqual(dwc["grade_text"], "G1")
        self.assertEqual(dwc["surface"], "dirt")
        self.assertEqual(dwc["distance_text"], "2000")
        self.assertEqual(dwc["racecourse"], "Meydan")
        self.assertEqual(dwc["series_key"], "uae-dubai-world-cup")
        self.assertEqual(dwc["year"], 2026)
        self.assertEqual(dwc["expectation_status"], "held")
        self.assertEqual(dwc["discipline"], "flat")
        self.assertEqual(dwc["source_race_name"], "Dubai World Cup Sponsored by Emirates Airline")
        sheema = by_name["Longines Dubai Sheema Classic"]
        self.assertEqual(sheema["grade_text"], "G1")
        self.assertEqual(sheema["surface"], "turf")


class JcsaMeetingCardTests(SimpleTestCase):
    """JCSA 赛日卡白名单过滤（沙特杯赛日 2026-02-14）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load("prepare_middle_east_calendar.py")

    def test_whitelist_filters_to_international_races(self):
        rows = self.module.parse_jcsa_meeting_card(
            _fixture("jcsa_api_meeting-info_en_20260214_0_All_False.html"), date="2026-02-14"
        )
        # 9 场中仅 7 场国际赛清单内的 6 场保留（COTHM Cup 缺席）
        self.assertEqual(len(rows), 6)
        by_key = {row["series_key"]: row for row in rows}
        self.assertEqual(
            sorted(by_key),
            [
                "saudi-1351-turf-sprint",
                "saudi-neom-turf-cup",
                "saudi-red-sea-turf",
                "saudi-riyadh-dirt-sprint",
                "saudi-saudi-cup",
                "saudi-saudi-derby",
            ],
        )
        cup = by_key["saudi-saudi-cup"]
        self.assertEqual(cup["canonical_name_original"], "Saudi Cup")
        self.assertEqual(cup["grade_text"], "G1")
        self.assertEqual(cup["surface"], "dirt")
        self.assertEqual(cup["distance_text"], "1800")
        self.assertEqual(cup["racecourse"], "King Abdulaziz Racetrack")
        self.assertEqual(cup["local_date"], "2026-02-14")
        self.assertEqual(cup["country"], "saudi_arabia")
        self.assertEqual(cup["expectation_status"], "held")
        self.assertEqual(cup["source_race_name"], "Saudi Cup (G1)")
        # 级别以 ICS 认定为准：Red Sea Turf 卡面 info 行无级别字样，仍为 G2
        self.assertEqual(by_key["saudi-red-sea-turf"]["grade_text"], "G2")
        self.assertEqual(by_key["saudi-red-sea-turf"]["surface"], "turf")
        self.assertEqual(by_key["saudi-neom-turf-cup"]["grade_text"], "G1")
        self.assertEqual(by_key["saudi-saudi-derby"]["grade_text"], "G3")
        # 阿拉伯马 G1 与非清单赛事不产出
        names = [row["source_race_name"] for row in rows]
        self.assertFalse(any("Obaiyah" in name for name in names))
        self.assertFalse(any("Asian Racing Federation" in name for name in names))
        self.assertFalse(any("Tuwaiq" in name for name in names))

    def test_absent_whitelist_races_reported_not_raised(self):
        rows = self.module.parse_jcsa_meeting_card(
            _fixture("jcsa_api_meeting-info_en_20260214_0_All_False.html"), date="2026-02-14"
        )
        missing = self.module.jcsa_missing_international_races(rows)
        self.assertEqual(missing, ["Custodian of the Two Holy Mosques Cup"])

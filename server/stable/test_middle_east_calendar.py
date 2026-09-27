"""中东（UAE + 沙特）赛历解析测试：DRC Carnival PDF 文本/手册网格、ERA 整日场头、JCSA 赛日卡。"""

from __future__ import annotations

import importlib.util
import json
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


def _grid_word(page, top, x0, x1, text):
    return json.dumps({"page": page, "top": top, "x0": x0, "x1": x1, "text": text})


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
        # series_key 与 ICS 基线同名赛事一致：国家全名前缀
        self.assertEqual(challenge["series_key"], "united-arab-emirates-al-maktoum-challenge")
        self.assertEqual(challenge["country"], "uae")
        self.assertEqual(challenge["country_region"], "middle_east")
        self.assertEqual(challenge["season_label"], "2025-2026")
        self.assertEqual(challenge["record_type"], "timeline")
        # 赛季已完赛：held + 统一 source_scope
        self.assertEqual(challenge["expectation_status"], "held")
        self.assertEqual(challenge["source_scope"], "official_calendar")
        self.assertEqual(challenge["source_refs"]["source_kind"], "drc_carnival_race_schedule")
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


class DrcBrochureGridTests(SimpleTestCase):
    """Dubai Racing Carnival 2024-25 手册赛程网格（词坐标 JSONL）解析。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load("prepare_middle_east_calendar.py")

    def _parse(self, text, season="2024-2025"):
        return self.module.parse_drc_brochure_grid(text, season=season)

    def test_synthetic_minimal_grid(self):
        lines = [
            _grid_word(1, 100.0, 25.0, 50.0, "FRIDAY•"),
            _grid_word(1, 100.0, 52.0, 56.0, "8"),
            _grid_word(1, 100.0, 57.0, 70.0, "NOV"),
            _grid_word(1, 100.0, 71.0, 85.0, "2024"),
            _grid_word(1, 100.0, 157.0, 182.0, "FRIDAY•"),
            _grid_word(1, 100.0, 183.0, 190.0, "22"),
            _grid_word(1, 100.0, 191.0, 204.0, "NOV"),
            _grid_word(1, 100.0, 205.0, 219.0, "2024"),
            _grid_word(1, 112.0, 25.0, 37.0, "Hcp"),
            _grid_word(1, 112.0, 39.0, 56.0, "80-100"),
            _grid_word(1, 112.0, 157.0, 170.0, "Test"),
            _grid_word(1, 112.0, 171.0, 190.0, "Stakes"),
            _grid_word(1, 112.0, 191.0, 212.0, "(Group"),
            _grid_word(1, 112.0, 213.0, 220.0, "2)"),
            _grid_word(1, 124.0, 25.0, 40.0, "3YO+"),
            _grid_word(1, 124.0, 42.0, 44.0, "|"),
            _grid_word(1, 124.0, 46.0, 60.0, "1200m"),
            _grid_word(1, 124.0, 62.0, 64.0, "|"),
            _grid_word(1, 124.0, 66.0, 76.0, "Dirt"),
            _grid_word(1, 124.0, 78.0, 80.0, "|"),
            _grid_word(1, 124.0, 82.0, 90.0, "AED"),
            _grid_word(1, 124.0, 92.0, 110.0, "250,000"),
            _grid_word(1, 124.0, 157.0, 170.0, "4YO+"),
            _grid_word(1, 124.0, 172.0, 174.0, "|"),
            _grid_word(1, 124.0, 176.0, 190.0, "1600m"),
            _grid_word(1, 124.0, 192.0, 194.0, "|"),
            _grid_word(1, 124.0, 196.0, 210.0, "Turf"),
            _grid_word(1, 124.0, 212.0, 214.0, "|"),
            _grid_word(1, 124.0, 216.0, 228.0, "AED"),
            _grid_word(1, 124.0, 230.0, 250.0, "850,000"),
        ]
        rows = self._parse("\n".join(lines), season="2099-2100")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["canonical_name_original"], "Test Stakes")
        self.assertEqual(row["local_date"], "2024-11-22")
        self.assertEqual(row["year"], 2024)
        self.assertEqual(row["grade_text"], "G2")
        self.assertEqual(row["distance_text"], "1600")
        self.assertEqual(row["surface"], "turf")
        self.assertEqual(row["racecourse"], "Meydan")
        self.assertEqual(row["series_key"], "united-arab-emirates-test-stakes")
        self.assertEqual(row["expectation_status"], "held")
        self.assertEqual(row["source_scope"], "official_calendar")
        self.assertEqual(row["source_refs"]["source_kind"], "drc_carnival_brochure_grid")
        self.assertEqual(row["source_refs"]["prize_text"], "AED 850,000")

    def test_overflow_line_assigns_to_correct_day(self):
        # 长名列溢出下一列锚点右侧时，段仍按起始 x 归列（真实页 12 的 Nad Al Sheba Turf Sprint 行形态）
        lines = [
            _grid_word(1, 100.0, 28.0, 52.0, "FRIDAY•"),
            _grid_word(1, 100.0, 54.0, 61.0, "21"),
            _grid_word(1, 100.0, 62.0, 74.0, "FEB"),
            _grid_word(1, 100.0, 75.0, 89.0, "2025"),
            _grid_word(1, 100.0, 158.0, 192.0, "SATURDAY•"),
            _grid_word(1, 100.0, 193.0, 197.0, "1"),
            _grid_word(1, 100.0, 198.0, 212.0, "MAR"),
            _grid_word(1, 100.0, 213.0, 227.0, "2025"),
            _grid_word(1, 100.0, 290.0, 315.0, "FRIDAY•"),
            _grid_word(1, 100.0, 316.0, 320.0, "7"),
            _grid_word(1, 100.0, 321.0, 334.0, "MAR"),
            _grid_word(1, 100.0, 335.0, 349.0, "2025"),
            # 列2 长名 "Nad Al Sheba Turf Sprint (Group 3)" 溢出到 x1=258，列3 段 "Hcp 60-80" 从 287 开始
            _grid_word(1, 112.0, 25.0, 37.0, "Balanchine"),
            _grid_word(1, 112.0, 38.0, 55.0, "(Group"),
            _grid_word(1, 112.0, 56.0, 60.0, "2)"),
            _grid_word(1, 112.0, 155.0, 167.0, "Nad"),
            _grid_word(1, 112.0, 168.0, 175.0, "Al"),
            _grid_word(1, 112.0, 176.0, 195.0, "Sheba"),
            _grid_word(1, 112.0, 196.0, 209.0, "Turf"),
            _grid_word(1, 112.0, 210.0, 229.0, "Sprint"),
            _grid_word(1, 112.0, 230.0, 250.0, "(Group"),
            _grid_word(1, 112.0, 251.0, 258.0, "3)"),
            _grid_word(1, 112.0, 287.0, 299.0, "Hcp"),
            _grid_word(1, 112.0, 300.0, 317.0, "60-80"),
            _grid_word(1, 124.0, 25.0, 40.0, "4YO+"),
            _grid_word(1, 124.0, 42.0, 44.0, "|"),
            _grid_word(1, 124.0, 46.0, 60.0, "1800m"),
            _grid_word(1, 124.0, 62.0, 64.0, "|"),
            _grid_word(1, 124.0, 66.0, 76.0, "Turf"),
            _grid_word(1, 124.0, 78.0, 80.0, "|"),
            _grid_word(1, 124.0, 82.0, 90.0, "AED"),
            _grid_word(1, 124.0, 92.0, 112.0, "850,000"),
            _grid_word(1, 124.0, 155.0, 170.0, "3YO+"),
            _grid_word(1, 124.0, 172.0, 174.0, "|"),
            _grid_word(1, 124.0, 176.0, 190.0, "1000m"),
            _grid_word(1, 124.0, 192.0, 194.0, "|"),
            _grid_word(1, 124.0, 196.0, 210.0, "Turf"),
            _grid_word(1, 124.0, 212.0, 214.0, "|"),
            _grid_word(1, 124.0, 216.0, 228.0, "AED"),
            _grid_word(1, 124.0, 230.0, 252.0, "1,200,000"),
        ]
        rows = self._parse("\n".join(lines), season="2099-2100")
        by_name = {row["canonical_name_original"]: row for row in rows}
        self.assertEqual(by_name["Nad Al Sheba Turf Sprint"]["local_date"], "2025-03-01")
        self.assertEqual(by_name["Nad Al Sheba Turf Sprint"]["grade_text"], "G3")
        self.assertEqual(by_name["Nad Al Sheba Turf Sprint"]["distance_text"], "1000")
        self.assertEqual(by_name["Balanchine"]["local_date"], "2025-02-21")
        self.assertEqual(by_name["Balanchine"]["grade_text"], "G2")

    def test_pending_race_without_condition_fails_closed(self):
        lines = [
            _grid_word(1, 100.0, 25.0, 50.0, "FRIDAY•"),
            _grid_word(1, 100.0, 52.0, 56.0, "8"),
            _grid_word(1, 100.0, 57.0, 70.0, "NOV"),
            _grid_word(1, 100.0, 71.0, 85.0, "2024"),
            _grid_word(1, 112.0, 25.0, 60.0, "Ghost"),
            _grid_word(1, 112.0, 61.0, 80.0, "Stakes"),
            _grid_word(1, 112.0, 82.0, 104.0, "(Group"),
            _grid_word(1, 112.0, 105.0, 110.0, "3)"),
            _grid_word(1, 124.0, 25.0, 60.0, "Another"),
            _grid_word(1, 124.0, 61.0, 80.0, "Race"),
        ]
        with self.assertRaises(RuntimeError):
            self._parse("\n".join(lines), season="2099-2100")

    def test_full_fixture_counts(self):
        rows = self._parse(_fixture("drc_carnival_brochure_2024-2025_grid_words.jsonl"))
        # 2024-25 Carnival 官方口径：16 赛日（手册 "consists of 16 race meetings"），G1×2/G2×10/G3×12
        self.assertEqual(len(rows), 24)
        grade_counts = {grade: sum(row["grade_text"] == grade for row in rows) for grade in ("G1", "G2", "G3")}
        self.assertEqual(grade_counts, {"G1": 2, "G2": 10, "G3": 12})
        self.assertEqual(len({row["local_date"] for row in rows}), 8)

    def test_full_fixture_day_assignment(self):
        rows = self._parse(_fixture("drc_carnival_brochure_2024-2025_grid_words.jsonl"))
        by_name = {row["canonical_name_original"]: row for row in rows}
        # 2024 年部分（Festive Friday 2024-12-20）
        self.assertEqual(by_name["Al Maktoum Mile"]["local_date"], "2024-12-20")
        self.assertEqual(by_name["Al Maktoum Mile"]["year"], 2024)
        self.assertEqual(by_name["Al Maktoum Mile"]["grade_text"], "G2")
        self.assertEqual(by_name["Al Maktoum Mile"]["distance_text"], "1600")
        self.assertEqual(by_name["Al Maktoum Mile"]["surface"], "dirt")
        self.assertEqual(by_name["Al Rashidiya"]["local_date"], "2024-12-20")
        # 2025 年 1-3 月部分
        self.assertEqual(by_name["Dubawi Stakes"]["local_date"], "2025-01-03")
        self.assertEqual(by_name["Zabeel Mile"]["local_date"], "2025-01-03")
        cape = by_name["Cape Verdi"]
        self.assertEqual(cape["local_date"], "2025-01-17")
        self.assertEqual(cape["source_refs"]["conditions"], "4YO+ Fillies & Mares")
        fashion_friday = [
            "Blue Point Sprint", "Al Shindagha Sprint", "Al Fahidi Fort", "Firebreak Stakes",
            "UAE 2000 Guineas", "Jebel Hatta", "Al Maktoum Challenge", "Al Khail Trophy",
        ]
        for name in fashion_friday:
            self.assertEqual(by_name[name]["local_date"], "2025-01-24", name)
        self.assertEqual(by_name["Jebel Hatta"]["grade_text"], "G1")
        self.assertEqual(by_name["Jebel Hatta"]["surface"], "turf")
        self.assertEqual(by_name["Dubai Millennium Stakes"]["local_date"], "2025-01-31")
        self.assertEqual(by_name["Dubai Millennium Stakes"]["grade_text"], "G3")
        self.assertEqual(by_name["Dubai Millennium Stakes"]["distance_text"], "2000")
        self.assertEqual(by_name["Balanchine"]["local_date"], "2025-02-21")
        self.assertEqual(by_name["Uae Oaks"]["local_date"], "2025-02-21")
        self.assertEqual(by_name["Nad Al Sheba Trophy"]["local_date"], "2025-02-21")
        super_saturday = [
            "Nad Al Sheba Turf Sprint", "Mahab Al Shimaal", "Burj Nahaar",
            "Singspiel Stakes", "Al Maktoum Classic", "Dubai City Of Gold",
        ]
        for name in super_saturday:
            self.assertEqual(by_name[name]["local_date"], "2025-03-01", name)
        self.assertEqual(by_name["Al Maktoum Classic"]["distance_text"], "2000")
        # 手册印 2400m（ICS 与 2025-26 赛历 PDF 为 2410m）：来源差异如实保留，交对账 review
        self.assertEqual(by_name["Dubai City Of Gold"]["distance_text"], "2400")
        self.assertEqual(by_name["Ras Al Khor"]["local_date"], "2025-03-07")
        self.assertEqual(by_name["Ras Al Khor"]["surface"], "turf")
        # schema 抽查
        mile = by_name["Al Maktoum Mile"]
        self.assertEqual(mile["series_key"], "united-arab-emirates-al-maktoum-mile")
        self.assertEqual(mile["record_type"], "timeline")
        self.assertEqual(mile["season_label"], "2024-2025")
        self.assertEqual(mile["expectation_status"], "held")
        self.assertEqual(mile["source_scope"], "official_calendar")
        self.assertEqual(mile["racecourse"], "Meydan")

    def test_count_self_check_raises_when_page_dropped(self):
        # 删掉第 12 页全部词（4 个赛日），16 赛日计数校验 fail closed
        kept = [
            line for line in _fixture("drc_carnival_brochure_2024-2025_grid_words.jsonl").splitlines()
            if json.loads(line)["page"] != 12
        ]
        with self.assertRaises(RuntimeError):
            self._parse("\n".join(kept))


class EraDayHeaderTests(SimpleTestCase):
    """ERA 整日页场头解析（DWC 赛日 2025-04-05 与 2026-03-28）。"""

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
        self.assertEqual(dwc["series_key"], "united-arab-emirates-dubai-world-cup")
        self.assertEqual(dwc["year"], 2026)
        self.assertEqual(dwc["expectation_status"], "held")
        self.assertEqual(dwc["discipline"], "flat")
        self.assertEqual(dwc["source_scope"], "official_calendar")
        self.assertEqual(dwc["source_refs"]["source_kind"], "era_racecard_results_all")
        self.assertEqual(dwc["source_race_name"], "Dubai World Cup Sponsored by Emirates Airline")
        # DWC 赛日属 Carnival 赛季收官：2026-03-28 -> 2025-2026
        self.assertEqual(dwc["season_label"], "2025-2026")
        sheema = by_name["Longines Dubai Sheema Classic"]
        self.assertEqual(sheema["grade_text"], "G1")
        self.assertEqual(sheema["surface"], "turf")

    def test_dwc_2025_day_headers(self):
        rows = self.module.parse_era_day_headers(
            _fixture("era_ajax_racecard-results-all_2025-04-05.html"), date="2025-04-05"
        )
        # DWC 2025 赛日 9 场中 8 场纯血马 Group 赛：G1×5 / G2×3
        self.assertEqual(len(rows), 8)
        grade_counts = {grade: sum(row["grade_text"] == grade for row in rows) for grade in ("G1", "G2", "G3")}
        self.assertEqual(grade_counts, {"G1": 5, "G2": 3, "G3": 0})
        by_name = {row["canonical_name_original"]: row for row in rows}
        derby = by_name["UAE Derby"]
        self.assertEqual(derby["local_date"], "2025-04-05")
        self.assertEqual(derby["year"], 2025)
        self.assertEqual(derby["grade_text"], "G2")
        self.assertEqual(derby["distance_text"], "1900")
        self.assertEqual(derby["surface"], "dirt")
        self.assertEqual(derby["series_key"], "united-arab-emirates-uae-derby")
        gold_cup = by_name["Dubai Gold Cup"]
        self.assertEqual(gold_cup["grade_text"], "G2")
        self.assertEqual(gold_cup["distance_text"], "3200")
        self.assertEqual(gold_cup["surface"], "turf")
        self.assertEqual(by_name["Dubai World Cup"]["grade_text"], "G1")
        # DWC 2025 赛日归 2024-2025 赛季
        self.assertEqual(derby["season_label"], "2024-2025")


class JcsaMeetingCardTests(SimpleTestCase):
    """JCSA 赛日卡白名单过滤（沙特杯赛日与 COTHM 杯资格赛日）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load("prepare_middle_east_calendar.py")

    def test_whitelist_filters_to_international_races(self):
        rows = self.module.parse_jcsa_meeting_card(
            _fixture("jcsa_api_meeting-info_en_20260214_0_All_False.html"), date="2026-02-14"
        )
        # 9 场中仅 7 场国际赛清单内的 6 场保留（COTHM Cup 不在沙特杯赛日卡上）
        self.assertEqual(len(rows), 6)
        by_key = {row["series_key"]: row for row in rows}
        self.assertEqual(
            sorted(by_key),
            [
                "saudi-arabia-1351-turf-sprint",
                "saudi-arabia-neom-turf-cup",
                "saudi-arabia-red-sea-turf",
                "saudi-arabia-riyadh-dirt-sprint",
                "saudi-arabia-saudi-cup",
                "saudi-arabia-saudi-derby",
            ],
        )
        cup = by_key["saudi-arabia-saudi-cup"]
        self.assertEqual(cup["canonical_name_original"], "Saudi Cup")
        self.assertEqual(cup["grade_text"], "G1")
        self.assertEqual(cup["surface"], "dirt")
        self.assertEqual(cup["distance_text"], "1800")
        self.assertEqual(cup["racecourse"], "King Abdulaziz Racetrack")
        self.assertEqual(cup["local_date"], "2026-02-14")
        self.assertEqual(cup["country"], "saudi_arabia")
        self.assertEqual(cup["expectation_status"], "held")
        self.assertEqual(cup["source_scope"], "official_calendar")
        self.assertEqual(cup["source_refs"]["source_kind"], "jcsa_meeting_info")
        self.assertEqual(cup["source_race_name"], "Saudi Cup (G1)")
        self.assertEqual(cup["source_refs"]["grade_source"], "card_name")
        # Red Sea Turf 卡面 info 行无级别字样，但名称带 (G2) 后缀
        self.assertEqual(by_key["saudi-arabia-red-sea-turf"]["grade_text"], "G2")
        self.assertEqual(by_key["saudi-arabia-red-sea-turf"]["surface"], "turf")
        self.assertEqual(by_key["saudi-arabia-neom-turf-cup"]["grade_text"], "G1")
        self.assertEqual(by_key["saudi-arabia-saudi-derby"]["grade_text"], "G3")
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

    def test_2025_saudi_cup_day_card_grades_from_card_name(self):
        rows = self.module.parse_jcsa_meeting_card(
            _fixture("jcsa_api_meeting-info_en_20250222_0_All_False.html"), date="2025-02-22"
        )
        self.assertEqual(len(rows), 6)
        by_key = {row["series_key"]: row for row in rows}
        # 2025 卡面级别为前缀 "G1/G2/G3"：Neom Turf Cup 2025 年为 G2（ICS 2025 口径），不能套 2026 白名单 G1
        neom = by_key["saudi-arabia-neom-turf-cup"]
        self.assertEqual(neom["grade_text"], "G2")
        self.assertEqual(neom["source_refs"]["grade_source"], "card_name")
        self.assertEqual(neom["distance_text"], "2100")
        self.assertEqual(neom["surface"], "turf")
        self.assertEqual(by_key["saudi-arabia-saudi-cup"]["grade_text"], "G1")
        self.assertEqual(by_key["saudi-arabia-saudi-derby"]["grade_text"], "G3")
        self.assertEqual(by_key["saudi-arabia-riyadh-dirt-sprint"]["grade_text"], "G2")
        self.assertEqual(by_key["saudi-arabia-1351-turf-sprint"]["grade_text"], "G2")
        # Red Sea Turf 2025 卡面名称带 G2 前缀
        red_sea = by_key["saudi-arabia-red-sea-turf"]
        self.assertEqual(red_sea["grade_text"], "G2")
        self.assertEqual(red_sea["distance_text"], "3000")
        for row in rows:
            self.assertEqual(row["expectation_status"], "held")
            self.assertEqual(row["year"], 2025)

    def test_2025_friday_card_has_no_international_races(self):
        rows = self.module.parse_jcsa_meeting_card(
            _fixture("jcsa_api_meeting-info_en_20250221_0_All_False.html"), date="2025-02-21"
        )
        self.assertEqual(rows, [])
        missing = self.module.jcsa_missing_international_races(rows)
        self.assertEqual(len(missing), 7)

    def test_2025_cothm_qualifier_day_excludes_domestic_namesakes(self):
        rows = self.module.parse_jcsa_meeting_card(
            _fixture("jcsa_api_meeting-info_en_20250125_0_All_False.html"), date="2025-01-25"
        )
        # 仅 R10 国际 G3 COTHM Cup 入选；R9 "(Local Gr.1)" 同名国内赛必须排除
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["series_key"], "saudi-arabia-custodian-of-the-two-holy-mosques-cup")
        self.assertEqual(row["canonical_name_original"], "Custodian of the Two Holy Mosques Cup")
        self.assertEqual(row["grade_text"], "G3")
        self.assertEqual(row["distance_text"], "1800")
        self.assertEqual(row["surface"], "dirt")
        self.assertEqual(row["race_number"], "10")
        self.assertEqual(row["expectation_status"], "held")
        self.assertIn("Saudi Cup 2025 Qualifier", row["source_race_name"])

    def test_2026_cothm_qualifier_day_group_suffix_grade(self):
        rows = self.module.parse_jcsa_meeting_card(
            _fixture("jcsa_api_meeting-info_en_20260117_0_All_False.html"), date="2026-01-17"
        )
        # R8 "(Group 3)" 后缀级别；R7 "(Domestic Group 1)" 同名国内赛排除
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["series_key"], "saudi-arabia-custodian-of-the-two-holy-mosques-cup")
        self.assertEqual(row["grade_text"], "G3")
        self.assertEqual(row["source_refs"]["grade_source"], "card_name")
        self.assertEqual(row["race_number"], "8")
        self.assertEqual(row["distance_text"], "1800")
        self.assertEqual(row["surface"], "dirt")

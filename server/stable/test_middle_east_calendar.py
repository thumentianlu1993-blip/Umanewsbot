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


def _grid_obj_char(page, top, x0, x1, text):
    return json.dumps({"kind": "char", "page": page, "top": top, "x0": x0, "x1": x1, "text": text})


def _grid_obj_rect(page, top, bottom, x0, x1, color):
    return json.dumps({"kind": "rect", "page": page, "top": top, "bottom": bottom, "x0": x0, "x1": x1, "color": color})


def _grid_text_chars(page, top, x0, text, char_width=2.5, spacing=0.5, space_width=1.3, space_gap=2.2):
    """生成字母间距排版的字符对象（对齐真实网格 PDF：空格也是字符，词内字符间隔 ≤0.5pt）。"""
    lines = []
    x = x0
    for ch in text:
        if ch == " ":
            lines.append(_grid_obj_char(page, top, round(x, 2), round(x + space_width, 2), " "))
            x += space_width + space_gap
            continue
        lines.append(_grid_obj_char(page, top, round(x, 2), round(x + char_width, 2), ch))
        x += char_width + spacing
    return lines


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


class DrcScheduleGridTests(SimpleTestCase):
    """Dubai Racing Carnival 2026-27 Race Schedule Grid（赛日×距离单页矩阵，字符+底色 JSONL）解析。

    夹具为全量单页派生对象（网格仅一页，无法按页裁剪；对齐 2024-25 手册夹具保留全部网格页的原则）。
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load("prepare_middle_east_calendar.py")

    def _parse(self, text, season="2026-2027"):
        return self.module.parse_drc_schedule_grid(text, season=season)

    def _synthetic_grid(self):
        """两列最小网格：06-Nov（G2 dirt）+ 01-Jan（Gr3 turf），各带一个未分级单元格。"""
        lines = [
            # 列头：马场名行定列中心，日期行定赛日
            _grid_obj_char(1, 74.2, 95.4, 115.2, "Meydan"),
            _grid_obj_char(1, 74.2, 150.8, 170.6, "Meydan"),
            _grid_obj_char(1, 82.9, 97.3, 114.6, "06-Nov"),
            _grid_obj_char(1, 82.9, 152.2, 169.4, "01-Jan"),
            # 左轴距离带标签
            _grid_obj_char(1, 310.5, 53.4, 65.0, "1600"),
            _grid_obj_char(1, 414.8, 53.4, 65.0, "1800"),
            # 底部 Purebred Arabian 区标签（排除带起点）
            _grid_obj_char(1, 735.9, 46.6, 55.3, "Pure Arabian"),
            # 单元格底色：橙=dirt，绿=turf
            _grid_obj_rect(1, 282.0, 308.0, 90.0, 125.0, [1.0, 0.753, 0.0]),
            _grid_obj_rect(1, 282.0, 308.0, 145.0, 180.0, [0.663, 0.855, 0.455]),
        ]
        # col0：Test Mile Stakes (Group 2) AED 1.000.000 @ 1600 带
        lines += _grid_text_chars(1, 288.9, 92.0, "Test Mile Stakes")
        lines += _grid_text_chars(1, 294.5, 95.0, "(Group 2)")
        lines += _grid_text_chars(1, 300.2, 93.0, "AED 1.000.000")
        # col0：未分级让赛（无赛名、无级别，不产行）
        lines += _grid_text_chars(1, 410.1, 97.0, "Hcp 80-100")
        lines += _grid_text_chars(1, 415.7, 96.0, "AED 250,000")
        # col1：Test Turf Stakes (Gr3) AED 700.000 @ 1600 带（级别变体 Gr3）
        lines += _grid_text_chars(1, 288.9, 147.0, "Test Turf Stakes")
        lines += _grid_text_chars(1, 294.5, 152.0, "(Gr3)")
        lines += _grid_text_chars(1, 300.2, 149.0, "AED 700.000")
        # col1：Listed 不产行
        lines += _grid_text_chars(1, 410.1, 148.0, "Test Listed")
        lines += _grid_text_chars(1, 415.7, 150.0, "(Listed)")
        lines += _grid_text_chars(1, 421.4, 149.0, "AED 500.000")
        return "\n".join(lines)

    def test_synthetic_minimal_grid(self):
        rows = self._parse(self._synthetic_grid(), season="2099-2100")
        self.assertEqual(len(rows), 2)
        first, second = rows
        # 跨年归年：11 月归赛季起年，1 月归赛季终年
        self.assertEqual(first["local_date"], "2099-11-06")
        self.assertEqual(first["year"], 2099)
        self.assertEqual(second["local_date"], "2100-01-01")
        self.assertEqual(second["year"], 2100)
        # 表面来自单元格底色（橙=dirt / 绿=turf），不在文本中
        self.assertEqual(first["surface"], "dirt")
        self.assertEqual(second["surface"], "turf")
        # 级别变体 (Gr3) 与标准 (Group 2) 等价
        self.assertEqual(first["grade_text"], "G2")
        self.assertEqual(second["grade_text"], "G3")
        self.assertEqual(first["distance_text"], "1600")
        self.assertEqual(first["source_refs"]["prize_text"], "AED 1.000.000")
        self.assertEqual(first["series_key"], "united-arab-emirates-test-mile-stakes")
        self.assertEqual(first["racecourse"], "Meydan")
        self.assertEqual(first["record_type"], "timeline")
        self.assertEqual(first["country"], "uae")
        self.assertEqual(first["country_region"], "middle_east")
        self.assertEqual(first["season_label"], "2099-2100")
        self.assertEqual(first["source_scope"], "official_calendar")
        self.assertEqual(first["source_refs"]["source_kind"], "drc_carnival_race_schedule_grid")
        # expectation 词表无 scheduled（held=应举办）；未来赛事的 scheduled 由物化层按日期派生
        self.assertEqual(first["expectation_status"], "held")

    def test_full_fixture_counts_and_days(self):
        rows = self._parse(_fixture("drc_carnival_2026-2027_schedule_grid_objects.jsonl"))
        # 官方口径：网格 17 列 = 16 个 Carnival 赛日 + DWC 赛日同版（"16 thrilling meetings" 见 DRC 官网）；
        # 逐格人工复核（analyze_grid 输出）：Carnival G1×2/G2×10/G3×11 + DWC 赛日 G1×5/G2×3 = G1×7/G2×13/G3×11；
        # 17 个赛日列的计数自校验在工具内 fail-closed，此处断言 9 个含 Group 赛的赛日
        self.assertEqual(len(rows), 31)
        grade_counts = {grade: sum(row["grade_text"] == grade for row in rows) for grade in ("G1", "G2", "G3")}
        self.assertEqual(grade_counts, {"G1": 7, "G2": 13, "G3": 11})
        self.assertEqual(len({row["local_date"] for row in rows}), 9)
        self.assertEqual(
            sorted({row["local_date"] for row in rows}),
            [
                "2026-12-18", "2027-01-01", "2027-01-15", "2027-01-22", "2027-01-29",
                "2027-02-19", "2027-02-27", "2027-03-05", "2027-03-27",
            ],
        )

    def test_full_fixture_year_attribution_and_status(self):
        rows = self._parse(_fixture("drc_carnival_2026-2027_schedule_grid_objects.jsonl"))
        # 2026 年 11-12 月仅 Festive Friday 两场 Group 赛；其余 29 行归 2027
        rows_2026 = [row for row in rows if row["year"] == 2026]
        self.assertEqual(len(rows_2026), 2)
        self.assertEqual({row["canonical_name_original"] for row in rows_2026}, {"Al Maktoum Mile", "Al Rashidiya"})
        self.assertEqual({row["local_date"] for row in rows_2026}, {"2026-12-18"})
        self.assertEqual(sum(row["year"] == 2027 for row in rows), 29)
        # 赛季未开赛但 expectation 口径为 held（应举办；词表无 scheduled）；
        # 物化层按 local_date > today 产 scheduled 草稿，见阶段 3d 物化报告
        self.assertTrue(all(row["expectation_status"] == "held" for row in rows))

    def test_full_fixture_spot_checks(self):
        rows = self._parse(_fixture("drc_carnival_2026-2027_schedule_grid_objects.jsonl"))
        by_name = {row["canonical_name_original"]: row for row in rows}
        # DWC 赛日 2027-03-27（官方公告周六，与网格列头一致）
        dwc = by_name["Dubai World Cup"]
        self.assertEqual(dwc["local_date"], "2027-03-27")
        self.assertEqual(dwc["grade_text"], "G1")
        self.assertEqual(dwc["distance_text"], "2000")
        self.assertEqual(dwc["surface"], "dirt")
        self.assertEqual(dwc["source_refs"]["prize_text"], "$12,000,000")
        self.assertEqual(dwc["source_refs"]["day_label"], "Dubai World Cup")
        self.assertEqual(dwc["series_key"], "united-arab-emirates-dubai-world-cup")
        sheema = by_name["Dubai Sheema Classic"]
        self.assertEqual(sheema["grade_text"], "G1")
        self.assertEqual(sheema["distance_text"], "2410")
        self.assertEqual(sheema["surface"], "turf")
        self.assertEqual(by_name["Al Quoz Sprint"]["surface"], "turf")
        self.assertEqual(by_name["Al Quoz Sprint"]["distance_text"], "1200")
        self.assertEqual(by_name["UAE Derby"]["source_refs"]["conditions"], "3YO's")
        self.assertEqual(by_name["UAE Derby"]["surface"], "dirt")
        # Fashion Friday 2027-01-22：8 场 Group 赛（与 2024-25/2025-26 同构）
        fashion = [row for row in rows if row["local_date"] == "2027-01-22"]
        self.assertEqual(len(fashion), 8)
        self.assertEqual({row["source_refs"]["day_label"] for row in fashion}, {"Fashion Friday"})
        jebel = by_name["Jebel Hatta"]
        self.assertEqual(jebel["grade_text"], "G1")
        self.assertEqual(jebel["surface"], "turf")
        self.assertEqual(jebel["source_refs"]["prize_text"], "AED 1.850.000")
        # (Gr3) 级别变体
        khail = by_name["Al Khail Trophy"]
        self.assertEqual(khail["grade_text"], "G3")
        self.assertEqual(khail["distance_text"], "2810")
        self.assertEqual(khail["surface"], "turf")
        # Emirates Super Saturday = 2027-02-27（周六），6 场 Group 赛
        super_sat = [row for row in rows if row["local_date"] == "2027-02-27"]
        self.assertEqual(len(super_sat), 6)
        self.assertEqual({row["source_refs"]["day_label"] for row in super_sat}, {"Emirates Super Saturday"})
        self.assertEqual(by_name["Dubai City of Gold"]["distance_text"], "2410")
        # 雌马限定条件保留在 conditions，不进赛名
        self.assertEqual(by_name["Cape Verdi"]["source_refs"]["conditions"], "Fillies & Mares")
        self.assertEqual(by_name["Balanchine"]["source_refs"]["conditions"], "Fillies & Mares")
        # Festive Friday 标签归 2026-12-18
        self.assertEqual(by_name["Al Maktoum Mile"]["source_refs"]["day_label"], "Festive Friday")
        # 2026-27 官方程序取消 UAE Oaks（2025-26 为 G3）：网格中无此行，命名差异交人工复核
        self.assertNotIn("UAE Oaks", by_name)

    def test_count_self_check_raises_on_missing_race(self):
        # 删掉 Jebel Hatta 的级别行字符：该单元格不再产行，G1 计数 6 != 7 fail closed
        kept = []
        for line in _fixture("drc_carnival_2026-2027_schedule_grid_objects.jsonl").splitlines():
            obj = json.loads(line)
            if obj["kind"] == "char" and 414.5 <= obj["top"] <= 416.5 and 534.0 <= obj["x0"] <= 560.0:
                continue
            kept.append(line)
        with self.assertRaises(RuntimeError):
            self._parse("\n".join(kept))

    def test_missing_day_header_fails_closed(self):
        # 删掉 12-Mar 列日期：该 Meydan 列无赛日头，结构不完整 fail closed
        kept = []
        for line in _fixture("drc_carnival_2026-2027_schedule_grid_objects.jsonl").splitlines():
            obj = json.loads(line)
            if obj["kind"] == "char" and obj["top"] < 100 and 908.0 <= obj["x0"] <= 930.0:
                continue
            kept.append(line)
        with self.assertRaises(RuntimeError):
            self._parse("\n".join(kept))

    def test_missing_surface_fill_fails_closed(self):
        # 删掉 Jebel Hatta 单元格底色：Group 赛无表面证据 fail closed（不允许臆造 surface）
        kept = []
        for line in _fixture("drc_carnival_2026-2027_schedule_grid_objects.jsonl").splitlines():
            obj = json.loads(line)
            if (
                obj["kind"] == "rect"
                and obj["top"] <= 412.0 <= obj["bottom"]
                and obj["x0"] <= 538.0 <= obj["x1"]
            ):
                continue
            kept.append(line)
        with self.assertRaises(RuntimeError):
            self._parse("\n".join(kept))


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

    def test_future_card_without_results_marker_stays_held(self):
        # 未来赛日卡无 Results 标记：expectation 词表无 scheduled，
        # 应举办口径恒为 held，scheduled 形态由物化层按日期派生
        html = _fixture("jcsa_api_meeting-info_en_20260214_0_All_False.html")
        self.assertIn("Results", html)
        mutated = html.replace("Results", "Entries")
        self.assertNotEqual(mutated, html)
        rows = self.module.parse_jcsa_meeting_card(mutated, date="2027-02-06")
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["expectation_status"], "held")
            self.assertFalse(row["source_refs"]["results_link_present"])

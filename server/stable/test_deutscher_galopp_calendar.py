"""Deutscher Galopp 官方赛历（renntermine PDF 文本 + Wayback ergebnisse 快照）解析测试。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "deutscher_galopp"


def _load():
    path = TOOLS / "prepare_deutscher_galopp_calendar.py"
    spec = importlib.util.spec_from_file_location(f"{path.stem}_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _renntermine_text() -> str:
    return (FIXTURES / "renntermine2026.txt").read_text(encoding="utf-8")


def _ergebnisse_html() -> str:
    return (FIXTURES / "wb_ergebnisse_20250908_excerpt.html").read_text(encoding="utf-8")


class RenntermineTextTests(SimpleTestCase):
    """renntermine 2026 PDF 提取文本解析。"""

    def setUp(self):
        self.module = _load()

    def test_full_calendar_grade_counts(self):
        rows = self.module.parse_renntermine_text(_renntermine_text(), year=2026)
        counts = {"G1": 0, "G2": 0, "G3": 0}
        for row in rows:
            counts[row["grade_text"]] += 1
        self.assertEqual(counts, {"G1": 7, "G2": 9, "G3": 26})
        self.assertEqual(len(rows), 42)

    def test_grosser_preis_von_baden_row(self):
        rows = self.module.parse_renntermine_text(_renntermine_text(), year=2026)
        row = next(r for r in rows if r["canonical_name_original"] == "Grosser Preis von Baden")
        self.assertEqual(row["record_type"], "timeline")
        self.assertEqual(row["country_region"], "germany")
        self.assertEqual(row["year"], 2026)
        self.assertEqual(row["series_key"], "germany-grosser-preis-von-baden")
        self.assertEqual(row["local_date"], "2026-09-06")
        self.assertEqual(row["racecourse"], "Baden-Baden")
        self.assertEqual(row["original_name"], "Grosser Preis von Baden")
        self.assertEqual(row["grade_text"], "G1")
        self.assertEqual(row["distance_text"], "2400")
        self.assertEqual(row["discipline"], "flat")
        self.assertEqual(row["expectation_status"], "held")
        self.assertEqual(row["source_scope"], "official_calendar")
        self.assertEqual(row["season_label"], "")

    def test_preis_der_diana_sponsor_stripped(self):
        rows = self.module.parse_renntermine_text(_renntermine_text(), year=2026)
        row = next(r for r in rows if r["canonical_name_original"] == "Preis der Diana")
        self.assertEqual(row["original_name"], "Henkel Preis der Diana")
        self.assertEqual(row["local_date"], "2026-08-02")
        self.assertEqual(row["racecourse"], "Düsseldorf")
        self.assertEqual(row["grade_text"], "G1")
        self.assertEqual(row["distance_text"], "2200")
        self.assertEqual(row["series_key"], "germany-preis-der-diana")

    def test_continuation_line_inherits_date_and_course(self):
        # 「Brunner Oettingen-Rennen」是 06.09. Baden-Baden 主行后的续行（无日期/马场前缀）
        rows = self.module.parse_renntermine_text(_renntermine_text(), year=2026)
        row = next(r for r in rows if r["canonical_name_original"] == "Oettingen-Rennen")
        self.assertEqual(row["local_date"], "2026-09-06")
        self.assertEqual(row["racecourse"], "Baden-Baden")
        self.assertEqual(row["grade_text"], "G2")
        self.assertEqual(row["distance_text"], "1600")

    def test_continuation_line_with_new_course(self):
        # 「Hannover …」样式的续行自带马场前缀，仅继承日期
        rows = self.module.parse_renntermine_text(_renntermine_text(), year=2026)
        row = next(r for r in rows if r["canonical_name_original"] == "German 2000 Guineas")
        self.assertEqual(row["original_name"], "Coolmore German 2000 Guineas")
        self.assertEqual(row["local_date"], "2026-05-25")
        self.assertEqual(row["racecourse"], "Köln")
        self.assertEqual(row["grade_text"], "G2")

    def test_grade_token_mapping(self):
        rows = self.module.parse_renntermine_text(_renntermine_text(), year=2026)
        by_name = {r["canonical_name_original"]: r["grade_text"] for r in rows}
        self.assertEqual(by_name["Deutsches Derby"], "G1")  # I
        self.assertEqual(by_name["Union-Rennen"], "G2")  # II
        self.assertEqual(by_name["Schwarzgold-Rennen"], "G3")  # III

    def test_known_defect_line_repaired_via_known_grade_list(self):
        # 已知缺陷行：Baden-BadGernosser 粘连 + IfIt 吞掉 II，
        # 由 KNOWN_GRADE_BY_NAME 对账清单兜底给出 G2 与规范名
        rows = self.module.parse_renntermine_text(_renntermine_text(), year=2026)
        row = next(r for r in rows if r["local_date"] == "2026-06-07" and r["grade_text"] == "G2")
        self.assertEqual(row["racecourse"], "Baden-Baden")
        self.assertEqual(row["canonical_name_original"], "Grosser Preis der Badischen Wirtschaft")
        self.assertIn("Tattersalls", row["original_name"])
        self.assertEqual(row["distance_text"], "2200")
        self.assertTrue(row["source_refs"]["grade_repaired_from_known_list"])

    def test_count_mismatch_raises(self):
        # 删掉一条 G3 续行后计数自校验必须失败（不允许空成功/静默缺数）
        text = _renntermine_text().replace("Sprint Trophy III 3+ 1400 m\n", "")
        self.assertNotEqual(text, _renntermine_text())
        with self.assertRaises(Exception) as ctx:
            self.module.parse_renntermine_text(text, year=2026)
        self.assertIn("G3", str(ctx.exception))

    def test_empty_text_raises(self):
        with self.assertRaises(Exception):
            self.module.parse_renntermine_text("", year=2026)

    def test_unknown_gradeless_race_raises(self):
        text = "RENNTERMINE 2026\nApril So. 05.04. Hoppegarten Phantasie-Rennen 4+ 2800 m\n"
        with self.assertRaises(Exception):
            self.module.parse_renntermine_text(text, year=2026)

    def test_listed_races_not_emitted(self):
        rows = self.module.parse_renntermine_text(_renntermine_text(), year=2026)
        self.assertFalse(any("Altano" in r["original_name"] for r in rows))
        self.assertFalse(any("Auktionsrennen" in r["original_name"] for r in rows))

    def test_surface_inferred_turf_with_note(self):
        # PDF 无场地信息；inventory 不允许 held+空 surface，因此推断 turf 并注明
        rows = self.module.parse_renntermine_text(_renntermine_text(), year=2026)
        for row in rows:
            self.assertEqual(row["surface"], "turf")
            self.assertEqual(row["source_refs"]["surface_inferred"], "turf")


class ErgebnisseSnapshotTests(SimpleTestCase):
    """Wayback ergebnisse accordion 快照解析（2025 赛季）。"""

    def setUp(self):
        self.module = _load()

    def test_extracts_graded_rows(self):
        rows = self.module.parse_ergebnisse_snapshot(_ergebnisse_html(), year=2025)
        self.assertEqual(len(rows), 7)
        counts = {"G1": 0, "G2": 0, "G3": 0}
        for row in rows:
            counts[row["grade_text"]] += 1
        self.assertEqual(counts, {"G1": 4, "G2": 2, "G3": 1})

    def test_grosser_preis_von_baden_2025(self):
        rows = self.module.parse_ergebnisse_snapshot(_ergebnisse_html(), year=2025)
        row = next(r for r in rows if "Grosser Preis von Baden" in r["original_name"])
        self.assertEqual(row["local_date"], "2025-09-07")
        self.assertEqual(row["racecourse"], "Baden-Baden")
        self.assertEqual(row["grade_text"], "G1")
        self.assertEqual(row["distance_text"], "2400")
        self.assertEqual(row["record_type"], "timeline")
        self.assertEqual(row["expectation_status"], "held")
        self.assertEqual(row["source_scope"], "official_calendar")

    def test_diana_and_dallmayr_rows(self):
        rows = self.module.parse_ergebnisse_snapshot(_ergebnisse_html(), year=2025)
        diana = next(r for r in rows if "Diana" in r["original_name"])
        self.assertEqual((diana["local_date"], diana["racecourse"], diana["grade_text"], diana["distance_text"]),
                         ("2025-08-03", "Düsseldorf", "G1", "2200"))
        dallmayr = next(r for r in rows if "Dallmayr" in r["original_name"])
        self.assertEqual((dallmayr["local_date"], dallmayr["racecourse"], dallmayr["grade_text"]),
                         ("2025-07-27", "München", "G1"))

    def test_ungraded_rows_skipped(self):
        rows = self.module.parse_ergebnisse_snapshot(_ergebnisse_html(), year=2025)
        self.assertFalse(any(r["racecourse"] == "Quakenbrück" for r in rows))
        self.assertFalse(any("Ausgleich" in r["original_name"] for r in rows))

    def test_empty_snapshot_raises(self):
        with self.assertRaises(Exception):
            self.module.parse_ergebnisse_snapshot(
                "<html><body><div class=\"elementAccordion\"></div></body></html>", year=2025
            )


class CalendarCliTests(SimpleTestCase):
    """CLI 层：URL 白名单、raw_source 注入、快照去重、JSONL/summary 输出。"""

    def setUp(self):
        self.module = _load()

    def _args(self, tmp: str, **overrides) -> SimpleNamespace:
        defaults = {
            "renntermine_txt": [],
            "ergebnisse_html": [],
            "year": 2026,
            "output_dir": tmp,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_prepare_renntermine_writes_jsonl_and_summary(self):
        with TemporaryDirectory() as tmp:
            url = "https://www.deutscher-galopp.de/downloads/renntermine2026.pdf"
            args = self._args(tmp, renntermine_txt=[f"{url}={FIXTURES / 'renntermine2026.txt'}"], year=2026)
            summary = self.module.prepare_calendar(args)
            self.assertEqual(summary["row_count"], 42)
            self.assertEqual(summary["grade_counts"], {"G1": 7, "G2": 9, "G3": 26})
            jsonl = Path(tmp) / "calendar_timeline_candidate.jsonl"
            rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 42)
            expected_sha = hashlib.sha256((FIXTURES / "renntermine2026.txt").read_bytes()).hexdigest()
            for row in rows:
                self.assertEqual(row["raw_source_url"], url)
                self.assertEqual(row["raw_source_cache_sha256"], expected_sha)
                self.assertTrue(row["raw_source_cache_path"])
            self.assertTrue((Path(tmp) / "summary.json").exists())

    def test_prepare_ergebnisse_dedupes_across_snapshots(self):
        with TemporaryDirectory() as tmp:
            fixture = FIXTURES / "wb_ergebnisse_20250908_excerpt.html"
            url1 = "https://web.archive.org/web/20250908/https://www.deutscher-galopp.de/gr/ergebnisse.php"
            url2 = "https://web.archive.org/web/20250910/https://www.deutscher-galopp.de/gr/ergebnisse.php"
            args = self._args(
                tmp,
                ergebnisse_html=[f"{url1}={fixture}", f"{url2}={fixture}"],
                year=2025,
            )
            summary = self.module.prepare_calendar(args)
            self.assertEqual(summary["row_count"], 7)
            self.assertEqual(summary["duplicates_skipped"], 7)
            rows = [json.loads(line) for line in (Path(tmp) / "calendar_timeline_candidate.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 7)

    def test_rejects_http_url(self):
        with TemporaryDirectory() as tmp:
            args = self._args(
                tmp,
                renntermine_txt=[f"http://www.deutscher-galopp.de/x.pdf={FIXTURES / 'renntermine2026.txt'}"],
            )
            with self.assertRaises(Exception):
                self.module.prepare_calendar(args)

    def test_rejects_non_allowlisted_host(self):
        with TemporaryDirectory() as tmp:
            args = self._args(
                tmp,
                renntermine_txt=[f"https://attacker.example/x.pdf={FIXTURES / 'renntermine2026.txt'}"],
            )
            with self.assertRaises(Exception):
                self.module.prepare_calendar(args)

    def test_missing_source_file_raises(self):
        with TemporaryDirectory() as tmp:
            args = self._args(
                tmp,
                renntermine_txt=["https://www.deutscher-galopp.de/x.pdf=/nonexistent/renntermine.txt"],
            )
            with self.assertRaises(Exception):
                self.module.prepare_calendar(args)

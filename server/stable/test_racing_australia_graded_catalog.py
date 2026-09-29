"""Racing Australia G1-G3 日历年目录工具的回归测试。

样本来自 2026-09-27 真实赛季页探测（runtime/race_calendar_nine_regions/detail_probe_20260927），
裁剪后存于 fixtures/australia/：

- ra_group_listed_2024-2025.html：2024-25 赛季，日期格式 %d-%b-%y，venue 为代码（FLEM），
  Listed=L、Restricted=LR。
- ra_group_listed_2025-2026.html：2025-26 赛季，日期格式 %d/%b/%Y，venue 为全名
  （Flemington），Listed=LR、Restricted=RL。
- ra_group_listed_404.html：赛季不存在时 RA 返回的 404 错误页。
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "australia"
URL_2024_2025 = "https://racingaustralia.horse/arb/Group_ListedRaceDates/2024-2025.aspx"
URL_2025_2026 = "https://racingaustralia.horse/arb/Group_ListedRaceDates/2025-2026.aspx"
URL_2023_2024 = "https://racingaustralia.horse/arb/Group_ListedRaceDates/2023-2024.aspx"


def _load():
    path = TOOLS / "prepare_racing_australia_graded_catalog.py"
    spec = importlib.util.spec_from_file_location(f"{path.stem}_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _write_source(root: Path, fixture: str, name: str | None = None) -> Path:
    """把 fixture 复制到受控的 source/australia/ 缓存目录。"""
    target_dir = root / "source" / "australia"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (name or fixture)
    target.write_bytes((FIXTURES / fixture).read_bytes())
    return target


class RacingAustraliaGradedCatalogParseTests(SimpleTestCase):
    def setUp(self):
        self.module = _load()

    def test_2024_25_fixture_parses_dash_dates_and_venue_codes(self):
        rows = self.module.parse_rows(URL_2024_2025, FIXTURES / "ra_group_listed_2024-2025.html", year=2025)

        self.assertEqual(len(rows), 5)
        standish = next(row for row in rows if row["provider_group_id"] == "480")
        self.assertEqual(standish["local_date"], "2025-01-11")
        self.assertEqual(standish["grade_text"], "G3")
        self.assertEqual(standish["racecourse"], "Flemington")
        self.assertEqual(standish["source_venue_key"], "FLEM")
        self.assertEqual(standish["canonical_name_original"], "STANDISH HANDICAP")
        self.assertEqual(standish["source_race_name"], "STANDISH HANDICAP")
        self.assertEqual(standish["distance_text"], "1200")
        self.assertEqual(standish["series_key"], "australia-ra-480-2025-01-11")
        valley = next(row for row in rows if row["provider_group_id"] == "559")
        self.assertEqual(valley["racecourse"], "The Valley")
        self.assertEqual(valley["local_date"], "2025-01-25")
        self.assertEqual(valley["grade_text"], "G2")
        ascot = next(row for row in rows if row["provider_group_id"] == "44")
        self.assertEqual(ascot["racecourse"], "Ascot")
        self.assertEqual(ascot["source_state"], "WA")

    def test_2024_25_fixture_filters_other_calendar_year(self):
        rows = self.module.parse_rows(URL_2024_2025, FIXTURES / "ra_group_listed_2024-2025.html", year=2024)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["local_date"], "2024-08-03")
        self.assertEqual(rows[0]["canonical_name_original"], "AURIE'S STAR HANDICAP")

    def test_2025_26_fixture_parses_slash_dates_and_full_venue_names(self):
        rows = self.module.parse_rows(URL_2025_2026, FIXTURES / "ra_group_listed_2025-2026.html", year=2025)

        self.assertEqual(len(rows), 6)
        aurie = next(row for row in rows if row["provider_group_id"] == "693")
        self.assertEqual(aurie["local_date"], "2025-08-02")
        self.assertEqual(aurie["grade_text"], "G3")
        self.assertEqual(aurie["racecourse"], "Flemington")
        self.assertEqual(aurie["source_venue_key"], "Flemington")
        self.assertEqual(aurie["distance_text"], "1200")
        winx = next(row for row in rows if row["provider_group_id"] == "534")
        self.assertEqual(winx["racecourse"], "Royal Randwick")
        self.assertEqual(winx["grade_text"], "G1")
        self.assertEqual(winx["local_date"], "2025-08-23")
        moir = next(row for row in rows if row["provider_group_id"] == "363")
        self.assertEqual(moir["racecourse"], "The Valley")

    def test_only_group_grades_are_produced(self):
        rows_24 = self.module.parse_rows(URL_2024_2025, FIXTURES / "ra_group_listed_2024-2025.html", year=2025)
        rows_25 = self.module.parse_rows(URL_2025_2026, FIXTURES / "ra_group_listed_2025-2026.html", year=2025)
        rows = rows_24 + rows_25

        self.assertEqual({row["grade_text"] for row in rows}, {"G1", "G2", "G3"})
        # fixture 中的 L/LR/RL 行一律不产出
        self.assertNotIn("621", [row["provider_group_id"] for row in rows])  # Listed(L)
        self.assertNotIn("749", [row["provider_group_id"] for row in rows])  # Restricted(LR)
        self.assertNotIn("137", [row["provider_group_id"] for row in rows])  # Listed(LR)
        self.assertNotIn("939", [row["provider_group_id"] for row in rows])  # Restricted(RL)
        # 2026 日历年行也不进入 2025 目录
        self.assertNotIn("332-2026", [row["series_key"] for row in rows])
        self.assertTrue(all(row["local_date"].startswith("2025-") for row in rows))

    def test_unknown_venue_is_kept_verbatim_and_recorded(self):
        html = (
            "<html><body><table class='tableizer-table restricted-listed'>"
            "<tr class='tableizer-firstrow'><th>Meeting Date</th><th>R ID</th><th>Grp</th><th>Grp</th>"
            "<th>State</th><th>Club</th><th>Venue</th><th>PRA Seasonal Race Name </th><th>Dist.</th>"
            "<th> Prizemoney </th><th>Age</th><th>Sex</th><th> </th><th>Registered Race Name</th></tr>"
            "<tr><td>01-Mar-25</td><td>9999</td><td>2</td><td>G2</td><td>VIC</td><td>XXCLUB</td>"
            "<td>XXXX</td><td>TEST RACE</td><td>1400</td><td> $300,000 </td><td>O</td><td>O</td>"
            "<td>WFA</td><td>TEST RACE</td></tr></table></body></html>"
        )
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "synthetic.html"
            source.write_text(html, encoding="utf-8")
            unknown = set()
            rows = self.module.parse_rows(URL_2024_2025, source, year=2025, unknown_venues=unknown)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["racecourse"], "XXXX")
        self.assertEqual(rows[0]["source_venue_key"], "XXXX")
        self.assertEqual(unknown, {"XXXX"})

    def test_404_error_page_is_rejected(self):
        with self.assertRaisesMessage(self.module.CatalogError, "404"):
            self.module.parse_rows(
                "https://racingaustralia.horse/arb/Group_ListedRaceDates/2026-2027.aspx",
                FIXTURES / "ra_group_listed_404.html",
                year=2026,
            )

    def test_page_without_season_table_is_rejected(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "plain.html"
            source.write_text("<html><body><p>no table here</p></body></html>", encoding="utf-8")
            with self.assertRaises(self.module.CatalogError):
                self.module.parse_rows(URL_2024_2025, source, year=2025)


class RacingAustraliaGradedCatalogFlowTests(SimpleTestCase):
    def setUp(self):
        self.module = _load()

    def _run_main(self, *argv: str) -> int:
        with patch.object(sys, "argv", ["prepare_racing_australia_graded_catalog.py", *argv]):
            return self.module.main()

    def test_main_stitches_two_adjacent_seasons_into_calendar_year(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = _write_source(root, "ra_group_listed_2024-2025.html")
            source_b = _write_source(root, "ra_group_listed_2025-2026.html")
            output = root / "catalog.jsonl.csv"
            printed = []
            with patch("builtins.print", side_effect=lambda *a, **k: printed.append(a)):
                rc = self._run_main(
                    "--year", "2025",
                    "--source", f"{URL_2024_2025}={source_a}",
                    "--source", f"{URL_2025_2026}={source_b}",
                    "--output", str(output),
                )

            self.assertEqual(rc, 0)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 11)
            self.assertTrue(all(row["local_date"].startswith("2025-") for row in rows))
            # 上半年来自 2024-25 赛季页，下半年来自 2025-26 赛季页：两季拼接覆盖完整日历年
            self.assertEqual(rows[0]["local_date"], "2025-01-01")
            self.assertEqual(rows[0]["raw_source_url"], URL_2024_2025)
            self.assertEqual(rows[-1]["local_date"], "2025-09-13")
            self.assertEqual(rows[-1]["raw_source_url"], URL_2025_2026)
            self.assertEqual(rows[-1]["canonical_name_original"], "MAKYBE DIVA STAKES")
            self.assertEqual(len({row["series_key"] for row in rows}), len(rows))
            self.assertTrue(all(row["country_region"] == "australia" for row in rows))
            summary = json.loads(printed[0][0])
            self.assertEqual(summary["row_count"], 11)
            self.assertEqual(summary["grade_counts"], {"G1": 4, "G2": 3, "G3": 4})
            self.assertEqual(summary["unknown_venues"], [])

    def test_main_rejects_non_adjacent_season_urls(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = _write_source(root, "ra_group_listed_2024-2025.html")
            source_b = _write_source(root, "ra_group_listed_2025-2026.html")
            rc = self._run_main(
                "--year", "2025",
                "--source", f"{URL_2023_2024}={source_a}",
                "--source", f"{URL_2025_2026}={source_b}",
                "--output", str(root / "out.csv"),
            )
            self.assertEqual(rc, 1)

    def test_main_rejects_same_season_twice(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = _write_source(root, "ra_group_listed_2024-2025.html")
            source_b = _write_source(root, "ra_group_listed_2024-2025.html", name="copy.html")
            rc = self._run_main(
                "--year", "2025",
                "--source", f"{URL_2024_2025}={source_a}",
                "--source", f"{URL_2024_2025}={source_b}",
                "--output", str(root / "out.csv"),
            )
            self.assertEqual(rc, 1)

    def test_main_rejects_404_source_page(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = _write_source(root, "ra_group_listed_2024-2025.html")
            source_b = _write_source(root, "ra_group_listed_404.html", name="ra_group_listed_2025-2026.html")
            rc = self._run_main(
                "--year", "2025",
                "--source", f"{URL_2024_2025}={source_a}",
                "--source", f"{URL_2025_2026}={source_b}",
                "--output", str(root / "out.csv"),
            )
            self.assertEqual(rc, 1)

    def test_main_rejects_season_without_in_year_rows(self):
        # 2024-25 赛季页只有 2024 日历年行时，2025 目录必须 fail closed，而不是默默只产出下半年
        html = (
            "<html><body><table class='tableizer-table restricted-listed'>"
            "<tr class='tableizer-firstrow'><th>Meeting Date</th><th>R ID</th><th>Grp</th><th>Grp</th>"
            "<th>State</th><th>Club</th><th>Venue</th><th>PRA Seasonal Race Name </th><th>Dist.</th>"
            "<th> Prizemoney </th><th>Age</th><th>Sex</th><th> </th><th>Registered Race Name</th></tr>"
            "<tr><td>03-Aug-24</td><td>693</td><td>3</td><td>G3</td><td>VIC</td><td>VRC</td>"
            "<td>FLEM</td><td>AURIE'S STAR HANDICAP</td><td>1200</td><td> $201,300 </td><td>O</td>"
            "<td>O</td><td>Hcp</td><td>AURIE'S STAR HANDICAP</td></tr></table></body></html>"
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = _write_source(root, "ra_group_listed_2024-2025.html")
            source_a.write_text(html, encoding="utf-8")
            source_b = _write_source(root, "ra_group_listed_2025-2026.html")
            rc = self._run_main(
                "--year", "2025",
                "--source", f"{URL_2024_2025}={source_a}",
                "--source", f"{URL_2025_2026}={source_b}",
                "--output", str(root / "out.csv"),
            )
            self.assertEqual(rc, 1)

    def test_parse_source_rejects_non_ra_host_and_plain_http(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "page.html"
            source.write_text("<html></html>", encoding="utf-8")
            for url in (
                "https://example.com/arb/Group_ListedRaceDates/2024-2025.aspx",
                "http://racingaustralia.horse/arb/Group_ListedRaceDates/2024-2025.aspx",
                "https://racingaustralia.horse.evil.example/arb/2024-2025.aspx",
            ):
                with self.subTest(url=url), self.assertRaises(self.module.CatalogError):
                    self.module.parse_source(f"{url}={source}")

    def test_validate_adjacent_seasons_rejects_url_without_season_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = _write_source(root, "ra_group_listed_2024-2025.html")
            source_b = _write_source(root, "ra_group_listed_2025-2026.html")
            with self.assertRaises(self.module.CatalogError):
                self.module.validate_adjacent_seasons(
                    [
                        ("https://racingaustralia.horse/arb/Group_ListedRaceDates/latest.aspx", source_a),
                        (URL_2025_2026, source_b),
                    ],
                    year=2025,
                )

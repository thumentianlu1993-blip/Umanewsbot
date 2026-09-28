"""Deutscher Galopp 赛果详情页 parser 与候选生成工具测试。"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "deutscher_galopp"

GPB_URL = "https://www.deutscher-galopp.de/gr/renntage/rennen.php?id=1358156&d=20250907&s=R"
DIANA_URL = "https://www.deutscher-galopp.de/gr/renntage/rennen.php?id=1357001&d=20250803&s=R"


def _load():
    path = TOOLS / "prepare_deutscher_galopp_race_detail_candidates.py"
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


def _minimal_page(*, result_rows: str, entry_rows: str, footer: str = "", entry_footer: str = "") -> str:
    """构造最小合法页面骨架，用于边界行为测试。"""
    return f"""<!DOCTYPE html>
<html><head><title>Test-Rennen, Baden-Baden 07.09.2025 - Deutscher Galopp</title></head><body>
<table class="display dataTable">
<thead><tr><th>Pl.</th><th>Name</th><th>Nr.</th><th>Box</th><th>Abstand</th><th>Gewinn</th><th>Besitzer</th><th>Trainer</th><th>Reiter</th><th>Gew.</th><th>Quote</th></tr></thead>
<tbody>{result_rows}{footer}</tbody>
</table>
<table class="display dataTable dataTableSortable">
<thead><tr><th>Nr.</th><th>Name</th><th>Box</th><th>Alter</th><th>Besitzer</th><th>Trainer</th><th>Reiter</th><th>Gew.</th><th>Quote</th></tr></thead>
<tbody>{entry_rows}{entry_footer}</tbody>
</table>
</body></html>"""


class ResultPageParseTests(SimpleTestCase):
    """_parse_result_page 契约测试（真实页面裁剪 fixture）。"""

    def setUp(self):
        self.module = _load()

    def test_gpb_runner_and_result_counts(self):
        html = _fixture("dg_20250907_baden-baden_r8_gpb.html")
        runners, results, metadata = self.module._parse_result_page(html, source_url=GPB_URL)
        self.assertEqual(len(runners), 8)
        self.assertEqual(len(results), 6)
        self.assertEqual(metadata["row_count"], 8)
        self.assertEqual(metadata["result_count"], 6)

    def test_gpb_metadata(self):
        html = _fixture("dg_20250907_baden-baden_r8_gpb.html")
        _runners, _results, metadata = self.module._parse_result_page(html, source_url=GPB_URL)
        self.assertEqual(metadata["racecourse"], "Baden-Baden")
        self.assertEqual(metadata["local_date"], "2025-09-07")
        self.assertEqual(metadata["race_title"], "WETTSTAR.de - 155. Grosser Preis von Baden - V4/2")
        self.assertEqual(metadata["race_time"], "2:29,02")

    def test_gpb_winner_full_fields(self):
        html = _fixture("dg_20250907_baden-baden_r8_gpb.html")
        runners, results, _metadata = self.module._parse_result_page(html, source_url=GPB_URL)
        winner = results[0]
        self.assertEqual(winner["finish_position"], 1)
        self.assertEqual(winner["official_finish_position"], 1)
        self.assertEqual(winner["horse_name"], "Goliath")
        self.assertEqual(winner["horse_number"], "4")
        self.assertEqual(winner["barrier"], "8")
        self.assertEqual(winner["jockey_name"], "Clement Lecoeuvre")
        self.assertEqual(winner["trainer_name"], "Francis-Henri Graffard/Frankreich")
        self.assertEqual(winner["carried_weight"], "60.0")  # 德国小数逗号 60,0 kg 转换
        self.assertEqual(winner["odds_value"], "2.9")  # 2,9 转换
        self.assertEqual(winner["margin"], "sicher")  # 德语头马距离原样保留
        self.assertEqual(winner["finish_time"], "")
        self.assertIs(winner["is_confirmed"], True)
        self.assertEqual(winner["source_refs"]["primary"], GPB_URL)
        self.assertEqual(winner["source_refs"]["source_language"], "de")
        self.assertEqual(winner["source_refs"]["official_finish_position"], 1)
        self.assertTrue(winner["source_refs"]["horse_url"].startswith("/gr/pferd/"))
        # winner 也必须在 runners 中且字段一致
        runner = next(r for r in runners if r["horse_number"] == "4")
        self.assertEqual(runner["horse_name"], "Goliath")
        self.assertEqual(runner["running_status"], "declared")

    def test_gpb_non_runners(self):
        html = _fixture("dg_20250907_baden-baden_r8_gpb.html")
        runners, results, _metadata = self.module._parse_result_page(html, source_url=GPB_URL)
        non_runners = {r["horse_name"]: r for r in runners if r["running_status"] == "non_runner"}
        self.assertEqual(sorted(non_runners), ["Hochkönig", "Rebel's Romance"])
        # 国别后缀已去除
        self.assertEqual(non_runners["Rebel's Romance"]["odds_value"], "")
        self.assertFalse(any(r["horse_name"] in non_runners for r in results))

    def test_gpb_runner_sorting_and_country_suffix(self):
        html = _fixture("dg_20250907_baden-baden_r8_gpb.html")
        runners, results, _metadata = self.module._parse_result_page(html, source_url=GPB_URL)
        self.assertEqual([r["horse_number"] for r in runners], [str(n) for n in range(1, 9)])
        self.assertEqual([r["sort_order"] for r in runners], list(range(1, 9)))
        names = {r["horse_name"] for r in runners}
        self.assertIn("Dubai Honour", names)  # (IRE) 去除
        self.assertIn("Cold Heart", names)  # (BRZ) 去除
        self.assertFalse(any("(" in name for name in names))
        last = results[-1]
        self.assertEqual(last["horse_name"], "Cold Heart")
        self.assertEqual(last["finish_position"], 6)
        self.assertEqual(last["margin"], "17 Längen")

    def test_diana_counts_and_winner(self):
        html = _fixture("dg_20250803_duesseldorf_r5_diana.html")
        runners, results, metadata = self.module._parse_result_page(html, source_url=DIANA_URL)
        self.assertEqual(len(runners), 15)
        self.assertEqual(len(results), 14)
        winner = results[0]
        self.assertEqual(winner["horse_name"], "Nicoreni")
        self.assertEqual(winner["odds_value"], "14.6")
        self.assertEqual(winner["jockey_name"], "Leon Wolff")
        self.assertEqual(winner["trainer_name"], "Peter Schiergen")
        self.assertEqual(winner["carried_weight"], "58.0")
        self.assertEqual(metadata["racecourse"], "Düsseldorf")
        self.assertEqual(metadata["local_date"], "2025-08-03")
        self.assertEqual(metadata["race_time"], "2:14,85")
        non_runners = [r for r in runners if r["running_status"] == "non_runner"]
        self.assertEqual([r["horse_name"] for r in non_runners], ["Kiamba"])
        # 德语距离表述原样保留
        margins = {r["horse_name"]: r["margin"] for r in results}
        self.assertEqual(margins["Nyra"], "kurzer Kopf")
        self.assertEqual(margins["Innora"], "1/2 Länge")

    def test_missing_finish_position_row_goes_to_runners_only(self):
        # 结果表中缺 Pl. 的行（未完赛）容错：进 runners 不进 results
        html = _minimal_page(
            result_rows=(
                "<tr><td>1.</td><td>Sieger</td><td>1</td><td>2</td><td>sicher</td><td>10.000 €</td>"
                "<td>Owner A</td><td>Trainer A</td><td>Jockey A</td><td>60,0 kg</td><td>2,0</td></tr>"
                "<tr><td></td><td>Abreiter</td><td>2</td><td>5</td><td></td><td></td>"
                "<td>Owner B</td><td>Trainer B</td><td>Jockey B</td><td>58,0 kg</td><td>7,5</td></tr>"
            ),
            entry_rows=(
                "<tr><td>1</td><td>Sieger</td><td>2</td><td>4</td><td>Owner A</td><td>Trainer A</td><td>Jockey A</td><td>60,0 kg</td><td>2,0</td></tr>"
                "<tr><td>2</td><td>Abreiter</td><td>5</td><td>5</td><td>Owner B</td><td>Trainer B</td><td>Jockey B</td><td>58,0 kg</td><td>7,5</td></tr>"
            ),
        )
        runners, results, _metadata = self.module._parse_result_page(html, source_url=GPB_URL)
        self.assertEqual(len(runners), 2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["horse_name"], "Sieger")
        dnf = next(r for r in runners if r["horse_name"] == "Abreiter")
        self.assertEqual(dnf["running_status"], "did_not_finish")

    def test_empty_results_raise(self):
        html = _minimal_page(
            result_rows="",
            entry_rows=(
                "<tr><td>1</td><td>Sieger</td><td>2</td><td>4</td><td>Owner A</td><td>Trainer A</td><td>Jockey A</td><td>60,0 kg</td><td>2,0</td></tr>"
            ),
        )
        with self.assertRaises(Exception):
            self.module._parse_result_page(html, source_url=GPB_URL)

    def test_empty_runners_raise(self):
        html = _minimal_page(
            result_rows=(
                "<tr><td>1.</td><td>Sieger</td><td>1</td><td>2</td><td>sicher</td><td>10.000 €</td>"
                "<td>Owner A</td><td>Trainer A</td><td>Jockey A</td><td>60,0 kg</td><td>2,0</td></tr>"
            ),
            entry_rows="",
        )
        with self.assertRaises(Exception):
            self.module._parse_result_page(html, source_url=GPB_URL)

    def test_unparseable_title_raises(self):
        html = "<html><head><title>irrelevant</title></head><body></body></html>"
        with self.assertRaises(Exception):
            self.module._parse_result_page(html, source_url=GPB_URL)


class PageMatchGuardTests(SimpleTestCase):
    def setUp(self):
        self.module = _load()
        html = _fixture("dg_20250907_baden-baden_r8_gpb.html")
        _r, _res, self.metadata = self.module._parse_result_page(html, source_url=GPB_URL)

    def test_matches_event(self):
        event = {
            "local_date": "2025-09-07",
            "racecourse": "Baden-Baden",
            "original_name": "Grosser Preis von Baden",
        }
        self.assertTrue(self.module._page_matches_event(event, self.metadata))

    def test_rejects_wrong_date(self):
        event = {
            "local_date": "2025-09-06",
            "racecourse": "Baden-Baden",
            "original_name": "Grosser Preis von Baden",
        }
        self.assertFalse(self.module._page_matches_event(event, self.metadata))

    def test_rejects_wrong_course(self):
        event = {
            "local_date": "2025-09-07",
            "racecourse": "Hoppegarten",
            "original_name": "Grosser Preis von Baden",
        }
        self.assertFalse(self.module._page_matches_event(event, self.metadata))

    def test_rejects_wrong_name(self):
        event = {
            "local_date": "2025-09-07",
            "racecourse": "Baden-Baden",
            "original_name": "Preis der Diana",
        }
        self.assertFalse(self.module._page_matches_event(event, self.metadata))


class DownloadGuardTests(SimpleTestCase):
    def setUp(self):
        self.module = _load()

    def test_rejects_http_url(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(Exception):
                self.module._download(
                    "http://www.deutscher-galopp.de/gr/renntage/rennen.php?id=1",
                    Path(tmp) / "x.html",
                    allow_network=False,
                    timeout=5,
                    sleep_seconds=0,
                )

    def test_rejects_non_allowlisted_host(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(Exception):
                self.module._download(
                    "https://attacker.example/rennen.php?id=1",
                    Path(tmp) / "x.html",
                    allow_network=True,
                    timeout=5,
                    sleep_seconds=0,
                )

    def test_missing_cache_without_allow_network_raises(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(Exception) as ctx:
                self.module._download(
                    GPB_URL,
                    Path(tmp) / "missing.html",
                    allow_network=False,
                    timeout=5,
                    sleep_seconds=0,
                )
            self.assertIn("缺少缓存", str(ctx.exception))


class PrepareCandidatesTests(SimpleTestCase):
    def setUp(self):
        self.module = _load()

    def _events_csv(self, path: Path) -> Path:
        rows = [
            {
                "year": "2025",
                "slug": "germany-grosser-preis-von-baden",
                "country_region": "germany",
                "local_date": "2025-09-07",
                "racecourse": "Baden-Baden",
                "original_name": "Grosser Preis von Baden",
                "status": "finished",
                "source_refs": "",
            },
            {
                "year": "2025",
                "slug": "germany-preis-der-diana",
                "country_region": "germany",
                "local_date": "2025-08-03",
                "racecourse": "Düsseldorf",
                "original_name": "Henkel Preis der Diana",
                "status": "finished",
                "source_refs": "",
            },
            {
                "year": "2025",
                "slug": "germany-deutsches-derby",
                "country_region": "germany",
                "local_date": "2025-07-06",
                "racecourse": "Hamburg",
                "original_name": "Deutsches Derby",
                "status": "scheduled",  # 非 finished 必须跳过
                "source_refs": "",
            },
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def _source_map(self, path: Path, *, diana_url: str = DIANA_URL) -> Path:
        payload = [
            {"year": 2025, "slug": "germany-grosser-preis-von-baden",
             "source_provider": "deutscher_galopp", "source_url": GPB_URL},
            {"year": 2025, "slug": "germany-preis-der-diana",
             "source_provider": "deutscher_galopp", "source_url": diana_url},
        ]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _args(self, tmp: Path, **overrides) -> SimpleNamespace:
        events = self._events_csv(tmp / "events.csv")
        source_map = self._source_map(tmp / "source_map.json", **( {"diana_url": overrides.pop("diana_url")} if "diana_url" in overrides else {}))
        defaults = {
            "events_csv": [str(events)],
            "source_map_json": str(source_map),
            "output_dir": str(tmp / "out"),
            "allow_network": False,
            "limit": 0,
            "timeout_seconds": 5,
            "sleep_seconds": 0,
            "fail_fast": False,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _seed_cache(self, tmp: Path) -> None:
        source_dir = tmp / "out" / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "source_deutscher_galopp_2025_germany-grosser-preis-von-baden.html").write_text(
            _fixture("dg_20250907_baden-baden_r8_gpb.html"), encoding="utf-8"
        )
        (source_dir / "source_deutscher_galopp_2025_germany-preis-der-diana.html").write_text(
            _fixture("dg_20250803_duesseldorf_r5_diana.html"), encoding="utf-8"
        )

    def test_prepare_candidates_end_to_end(self):
        with TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._seed_cache(tmp)
            args = self._args(tmp)
            summary = self.module.prepare_candidates(args)
            self.assertEqual(summary["events"], 2)
            self.assertEqual(summary["runner_items"], 8 + 15)
            self.assertEqual(summary["result_items"], 6 + 14)
            self.assertEqual(summary["errors"], [])
            jsonl = tmp / "out" / "deutscher_galopp_detail_candidates.jsonl"
            records = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 2)
            record = next(r for r in records if r["slug"] == "germany-grosser-preis-von-baden")
            self.assertEqual(record["source_name"], "deutscher_galopp_result")
            self.assertEqual(record["source_url"], GPB_URL)
            self.assertEqual(record["year"], 2025)
            self.assertEqual(record["metadata"]["racecourse"], "Baden-Baden")
            self.assertEqual(record["modules"]["results"]["items"][0]["horse_name"], "Goliath")
            review = tmp / "out" / "deutscher_galopp_detail_review.csv"
            with review.open(encoding="utf-8-sig", newline="") as handle:
                review_rows = list(csv.DictReader(handle))
            self.assertEqual(len(review_rows), 2)
            self.assertTrue((tmp / "out" / "summary.json").exists())

    def _break_diana_date(self, tmp: Path) -> None:
        events_path = tmp / "events.csv"
        with events_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[1]["local_date"] = "2025-08-04"
        with events_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_page_mismatch_collects_error_without_raising(self):
        with TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._seed_cache(tmp)
            args = self._args(tmp)
            # Diana 事件的日期改成与页面不一致，守卫必须拦截并记入 errors
            self._break_diana_date(tmp)
            summary = self.module.prepare_candidates(args)
            self.assertEqual(summary["events"], 1)
            self.assertEqual(len(summary["errors"]), 1)
            self.assertEqual(summary["errors"][0]["slug"], "germany-preis-der-diana")

    def test_fail_fast_reraises(self):
        with TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._seed_cache(tmp)
            args = self._args(tmp, fail_fast=True)
            self._break_diana_date(tmp)
            with self.assertRaises(Exception):
                self.module.prepare_candidates(args)


DERBY_URL = "https://www.deutscher-galopp.de/gr/renntage/rennen.php?id=1355793&d=20250706&s=R"
STUTENPREIS_URL = "https://www.deutscher-galopp.de/gr/renntage/rennen.php?id=1363220&d=20260905&s=R"


class NonStarterNameNormalizationTests(SimpleTestCase):
    """2025-07-06 Hamburg Deutsches Derby：表尾 NICHTSTARTER 无角色后缀，出赛表马名带后缀。"""

    def setUp(self):
        self.module = _load()
        self.runners, self.results, self.metadata = self.module._parse_result_page(
            _fixture("dg_20250706_hamburg_deutsches_derby.html"), source_url=DERBY_URL
        )

    def test_non_starter_suffix_mismatch_no_longer_rejected(self):
        # 表尾 NICHTSTARTER: Juwelier；出赛表为 "Juwelier (IRE) O."
        non_runners = [row for row in self.runners if row["running_status"] == "non_runner"]
        self.assertEqual([row["horse_name"] for row in non_runners], ["Juwelier"])

    def test_winner_hochkoenig(self):
        self.assertEqual(self.results[0]["horse_name"], "Hochkönig")
        self.assertEqual(self.metadata["race_time"], "2:37,10")

    def test_runner_names_strip_role_suffix_and_country(self):
        for row in self.runners:
            self.assertNotRegex(row["horse_name"], r"\s\([A-Z]{2,3}\)$")
            self.assertNotRegex(row["horse_name"], r"\s(?:O|H|St|Sb|Skl|Bl|N|Hl|W)\.$")


class NameTokenAliasTests(SimpleTestCase):
    """2026-09-05 Baden-Baden T. von Zastrow Stutenpreis：ICS 名 "T.v.Zastrow" 的 v≈von 别名。"""

    def setUp(self):
        self.module = _load()
        self.runners, self.results, self.metadata = self.module._parse_result_page(
            _fixture("dg_20260905_baden-baden_stutenpreis.html"), source_url=STUTENPREIS_URL
        )

    def test_v_von_token_alias(self):
        # "von" 是德语通用词会被过滤；别名使 ICS 缩写与官方全称归一到同一集合
        expected = self.module._name_tokens("T.v.Zastrow Stutenpreis")
        official = self.module._name_tokens("T. von Zastrow Stutenpreis")
        self.assertEqual(expected, {"t", "zastrow", "stutenpreis"})
        self.assertEqual(expected, official)

    def test_page_guard_accepts_ics_spelling(self):
        event = {
            "local_date": "2026-09-05",
            "racecourse": "Baden-Baden",
            "original_name": "T.v.Zastrow Stutenpreis",
        }
        self.assertTrue(self.module._page_matches_event(event, self.metadata))
        self.assertFalse(
            self.module._page_matches_event(
                {**event, "original_name": "Grosser Preis von Baden"}, self.metadata
            )
        )

    def test_stutenpreis_results_parsed(self):
        self.assertGreaterEqual(len(self.results), 5)
        self.assertTrue(self.results[0]["horse_name"])


class DeadHeatDisplayPositionTests(SimpleTestCase):
    """2025-07-06 Deutsches Derby 第 4 名并列（Path of Soldier / Enzian）：

    finish_position 必须展示唯一化（1..N 连续），official_finish_position 保留官方并列，
    以满足 stable_raceeventresult 的 (event, finish_position) 唯一约束。
    """

    def setUp(self):
        self.module = _load()
        _runners, self.results, _meta = self.module._parse_result_page(
            _fixture("dg_20250706_hamburg_deutsches_derby.html"), source_url=DERBY_URL
        )

    def test_finish_positions_are_unique_display_positions(self):
        display = [row["finish_position"] for row in self.results]
        self.assertEqual(display, list(range(1, len(self.results) + 1)))

    def test_dead_heat_pair_keeps_official_position(self):
        dead_heat = [row for row in self.results if row["official_finish_position"] == 4]
        self.assertEqual(
            sorted(row["horse_name"] for row in dead_heat), ["Enzian", "Path of Soldier"]
        )
        self.assertNotIn(5, {row["official_finish_position"] for row in self.results})

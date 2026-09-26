from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.test import SimpleTestCase


TOOL_PATH = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "prepare_nar_racelist_events.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("prepare_nar_racelist_events_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


FIXTURE_HTML = """
<html><body>
<div class="month"><h3 class="h">2025年4月</h3><ul>
<li class="js-item"><a href="/dirtgraderace/2025/0409_kawasakikinen/racecard.html"><p>4月9日(水)</p><h4 class="jpn1">川崎記念</h4><p>川崎 左2100m 20:10発走</p></a></li>
<li class="js-item"><a href="/dirtgraderace/2025/0403_hyogo-jyoai/racecard.html"><p>4月3日(木)</p><h4 class="jpn2">兵庫女王盃</h4><p>園田 右1870m 16:05発走</p></a></li>
</ul></div>
<div class="month"><h3 class="h">2025年12月</h3><ul>
<li class="js-item"><a href="/dirtgraderace/2025/1229_tokyodaishoten/racecard.html"><p>12月29日(月)</p><h4 class="g1">東京大賞典</h4><p>大井 右2000m 16:05発走</p></a></li>
<li class="js-item"><a href="/dirtgraderace/2025/1217_zen-nipponnisaiyushun/racecard.html"><p>12月17日(水)</p><h4 class="jpn1">全日本2歳優駿</h4><p>川崎 左1600m 20:10発走</p></a></li>
</ul></div>
</body></html>
"""


def _args(html_path: Path, out: Path, **overrides):
    base = {
        "racelist_html": str(html_path),
        "year": 2025,
        "grades": "jpn1",
        "output": str(out),
        "allow_network": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class NarRacelistEventsTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_tool()

    def test_jpn1_only_filter_and_field_mapping(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = root / "racelist.html"
            html_path.write_text(FIXTURE_HTML, encoding="utf-8")
            out = root / "events.csv"

            summary = module.prepare_racelist_events(_args(html_path, out))

            self.assertEqual(summary["events"], 2)
            rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
            self.assertEqual(len(rows), 2)
            kawasaki, zennippon = rows
            self.assertEqual(kawasaki["original_name"], "川崎記念")
            self.assertEqual(kawasaki["normalized_grade"], "JPN1")
            self.assertEqual(kawasaki["grade_text"], "JpnⅠ")
            self.assertEqual(kawasaki["local_date"], "2025-04-09")
            self.assertEqual(kawasaki["local_start_time"], "20:10")
            self.assertEqual(kawasaki["racecourse"], "川崎")
            self.assertEqual(kawasaki["distance_text"], "2100m")
            self.assertEqual(kawasaki["surface"], "dirt")
            self.assertEqual(kawasaki["country_region"], "japan")
            self.assertEqual(kawasaki["status"], "finished")
            self.assertEqual(kawasaki["year"], "2025")
            # slug 序号按全年全等级列表排序（与 2026 生产 nar-dirt-YYYY-MMDD-NN 约定一致）
            self.assertEqual(kawasaki["slug"], "nar-dirt-2025-0409-01")
            self.assertEqual(zennippon["slug"], "nar-dirt-2025-1217-04")
            self.assertIn("0409_kawasakikinen", kawasaki["source_refs"])
            self.assertEqual(zennippon["original_name"], "全日本2歳優駿")
            self.assertEqual(zennippon["local_date"], "2025-12-17")

    def test_chinese_name_map_is_applied(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = root / "racelist.html"
            html_path.write_text(FIXTURE_HTML, encoding="utf-8")
            chinese_map = root / "chinese.csv"
            chinese_map.write_text("original_name,chinese_name\n川崎記念,川崎纪念\n", encoding="utf-8")
            out = root / "events.csv"

            module.prepare_racelist_events(_args(html_path, out, chinese_map=str(chinese_map)))

            rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
            self.assertEqual(rows[0]["chinese_name"], "川崎纪念")
            self.assertEqual(rows[1]["chinese_name"], "")


    def test_g1_excluded_from_jpn1_scope_but_included_on_request(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = root / "racelist.html"
            html_path.write_text(FIXTURE_HTML, encoding="utf-8")
            out = root / "events.csv"

            summary = module.prepare_racelist_events(_args(html_path, out, grades="jpn1,g1"))

            names = [row["original_name"] for row in csv.DictReader(out.open(encoding="utf-8-sig"))]
            self.assertEqual(summary["events"], 3)
            self.assertIn("東京大賞典", names)
            self.assertNotIn("兵庫女王盃", names)

    def test_unparseable_page_fails_closed(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = root / "racelist.html"
            html_path.write_text("<html><body>empty</body></html>", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                module.prepare_racelist_events(_args(html_path, root / "events.csv"))

from __future__ import annotations

import importlib.util
from pathlib import Path

from django.test import SimpleTestCase


TOOL_PATH = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "prepare_jra_race_detail_candidates.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("prepare_jra_race_detail_candidates_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class JraRaceDetailYearParameterTests(SimpleTestCase):
    """--year 参数化：默认 2026 保持现状，--year 2025 切换列表页/结果页/缓存文件名。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_tool()

    def test_default_year_remains_2026(self):
        module = self.module
        self.assertIn("/replay/2026/jyusyo.html", module._result_list_url(2026))
        self.assertTrue(
            module._result_url_re(2026).search("/datafile/seiseki/replay/2026/073.html")
        )
        self.assertFalse(
            module._result_url_re(2026).search("/datafile/seiseki/replay/2025/073.html")
        )
        self.assertEqual(
            module._source_filename("https://www.jra.go.jp/datafile/seiseki/replay/2026/073.html", 2026),
            "source_jra_2026_073.html",
        )

    def test_year_2025_switches_list_url_result_regex_and_cache_name(self):
        module = self.module
        self.assertIn("/replay/2025/jyusyo.html", module._result_list_url(2025))
        self.assertTrue(
            module._result_url_re(2025).search("/datafile/seiseki/replay/2025/073.html")
        )
        self.assertTrue(
            module._result_url_re(2025).search("/datafile/seiseki/g1/nakayama_daishogai/result/daishogai2025.html")
        )
        self.assertFalse(
            module._result_url_re(2025).search("/datafile/seiseki/replay/2026/073.html")
        )
        self.assertEqual(
            module._source_filename("https://www.jra.go.jp/datafile/seiseki/replay/2025/073.html", 2025),
            "source_jra_2025_073.html",
        )

    def test_module_constants_keep_2026_backward_compatibility(self):
        module = self.module
        self.assertIn("2026", module.JRA_RESULT_LIST_URL)
        self.assertIn("2026", module.JRA_RESULT_RE.pattern)

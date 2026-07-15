from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


TOOL = Path(__file__).resolve().parents[2] / "runtime/tools/prepare_cached_historical_race_details.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures/race_event_crawl/jra_replay_2005_99_legacy.html"
SOURCE_URL = "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"


def load_tool():
    spec = importlib.util.spec_from_file_location("cached_historical_jra_legacy_details", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_runtime_tool(name: str):
    path = TOOL.parent / name
    spec = importlib.util.spec_from_file_location(f"{path.stem}_jra_distance_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOL.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def fixture_bytes() -> bytes:
    return FIXTURE.read_text(encoding="utf-8").encode("cp932")


class HistoricalJRALegacyDetailTests(SimpleTestCase):
    def setUp(self):
        self.tool = load_tool()
        self.runner = load_runtime_tool("historical_race_detail_runner_v2.py")

    def _modern_result_page(self, distance_html: str) -> bytes:
        return (
            "<html><body>"
            "<table><tr><th>result</th></tr><tr>"
            '<td class="place">1</td><td class="waku">1</td>'
            '<td class="num">1</td><td class="horse">テストホース</td>'
            '<td class="weight">55.0</td><td class="jockey">テスト騎手</td>'
            '<td class="time">1:34.5</td><td class="margin"></td>'
            '<td class="trainer">テスト調教師</td><td class="pop">1</td>'
            "</tr></table>"
            f"{distance_html}</body></html>"
        ).encode("cp932")

    def test_structured_distance_formats_feed_validation_when_event_distance_is_empty(self):
        cases = (
            ('<table><tr><td class="gray12">１６００ｍ</td></tr></table>', "1600m"),
            ('<div class="raceKyoriTrack">コース&nbsp;1400m 芝・右 外</div>', "1400m"),
            (
                '<div class="cell course"><span class="cap">コース：</span>'
                '1,400<span class="unit">メートル</span>'
                '<span class="detail">（芝・左）</span></div>',
                "1400m",
            ),
        )
        for distance_html, expected in cases:
            with self.subTest(distance_html=distance_html):
                _runners, _results, metadata = self.tool.parse_jra_detail(
                    self._modern_result_page(distance_html),
                    source_url=SOURCE_URL,
                )
                distance, provenance = self.runner._distance_for_validation(
                    {"distance_text": ""},
                    {"metadata": metadata, "source_url": SOURCE_URL},
                )

                self.assertEqual(metadata["distance_text"], expected)
                self.assertEqual(distance, expected)
                self.assertEqual(provenance["source"], "parsed.metadata.distance_text")

    def test_page_without_structured_distance_does_not_guess_from_race_name(self):
        body = self._modern_result_page(
            '<th class="header3">第１６回 ＮＨＫマイルカップ</th>'
        )

        _runners, _results, metadata = self.tool.parse_jra_detail(
            body,
            source_url=SOURCE_URL,
        )

        self.assertEqual(metadata["distance_text"], "")

    def test_2005_legacy_replay_page_parses_all_results_and_matching_runners(self):
        runners, results, _metadata = self.tool.parse_jra_detail(
            fixture_bytes(),
            source_url=SOURCE_URL,
        )

        self.assertEqual(len(results), 11)
        self.assertTrue(runners)
        runner_keys = {(row["horse_number"], row["horse_name"]) for row in runners}
        result_keys = {(row["horse_number"], row["horse_name"]) for row in results}
        self.assertTrue(result_keys.issubset(runner_keys))
        self.assertTrue(any(row["finish_position"] == 1 for row in results))

    def test_cached_prepare_never_marks_zero_row_jra_detail_complete(self):
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            cache_path = root / "jra-replay-2005-99.html"
            cache_path.write_bytes(fixture_bytes())
            events_path = root / "events.csv"
            with events_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["year", "slug", "source_refs"])
                writer.writeheader()
                writer.writerow(
                    {
                        "year": "2005",
                        "slug": "daily-hai-nisai-stakes-2005",
                        "source_refs": json.dumps(
                            {
                                "detail_discovery": {
                                    "urls": {
                                        "result_url": {
                                            "source_provider": "jra",
                                            "url": SOURCE_URL,
                                        }
                                    }
                                }
                            }
                        ),
                    }
                )
            manifest_path = root / "source_cache_manifest.json"
            body = cache_path.read_bytes()
            manifest_path.write_text(
                json.dumps(
                    {
                        "files": {
                            cache_path.name: {
                                "path": cache_path.name,
                                "size": len(body),
                                "sha256": hashlib.sha256(body).hexdigest(),
                                "source_url": SOURCE_URL,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            prepared = self.tool.prepare(event_paths=[events_path], manifest_path=manifest_path)

        self.assertEqual(prepared["gaps"], [])
        self.assertEqual(len(prepared["records"]), 1)
        record = prepared["records"][0]
        for module_name in ("runners", "results"):
            module = record["modules"][module_name]
            self.assertFalse(
                module["is_complete"] and not module["items"],
                f"{module_name} must not be zero-row complete",
            )

"""ERA（阿联酋 emiratesracing.com）赛果详情解析测试。"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "middle_east"
ALL_DAY_URL = "https://emiratesracing.com/ajax/racecard-results-all?date=2026-03-28"
R9_URL = "https://emiratesracing.com/ajax/racecard-results?date=2026-03-28&race=9"


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


class EraResultsPageTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load("prepare_era_race_detail_candidates.py")

    def test_single_race_page_runner_fields(self):
        runners, results, metadata = self.module._parse_results_all_page(
            _fixture("era_ajax_racecard-results_2026-03-28_r9.html"),
            source_url=R9_URL,
            race_number="9",
        )
        self.assertEqual(len(runners), 9)
        self.assertEqual(len(results), 9)
        # runners 按鞍布号数值排序：1 号 FOREVER YOUNG 排第一
        self.assertEqual([row["horse_number"] for row in runners], ["1", "2", "3", "4", "5", "6", "7", "8", "9"])
        self.assertEqual([row["sort_order"] for row in runners], list(range(1, 10)))
        self.assertEqual(runners[0]["horse_name"], "FOREVER YOUNG")
        self.assertEqual(runners[0]["barrier"], "6")
        # 头马行：MAGNITUDE
        winner = results[0]
        self.assertEqual(winner["finish_position"], 1)
        self.assertEqual(winner["official_finish_position"], 1)
        self.assertEqual(winner["horse_name"], "MAGNITUDE")
        self.assertEqual(winner["horse_number"], "2")
        self.assertEqual(winner["barrier"], "1")
        self.assertEqual(winner["jockey_name"], "Jose Ortiz")
        self.assertEqual(winner["trainer_name"], "Steve Asmussen")
        self.assertEqual(winner["carried_weight"], "57")
        self.assertEqual(winner["odds_value"], "10")
        self.assertEqual(winner["finish_time"], "2:04.38")
        self.assertEqual(winner["margin"], "")
        self.assertTrue(winner["is_confirmed"])
        # source_refs：原始马名（含国别后缀）、马链接、评语、official_finish_position
        refs = winner["source_refs"]
        self.assertEqual(refs["primary"], R9_URL)
        self.assertEqual(refs["horse_name_raw"], "MAGNITUDE (USA)")
        self.assertEqual(refs["country_code"], "USA")
        self.assertEqual(refs["horse_url"], "https://emiratesracing.com/horses/h-76516")
        self.assertEqual(refs["official_finish_position"], 1)
        self.assertIn("Dictated, kicked 400m out", refs["reader_comment"])
        # 第二名：FOREVER YOUNG 差距 0.98L、热门 SP 纯值 1.60
        second = results[1]
        self.assertEqual(second["horse_name"], "FOREVER YOUNG")
        self.assertEqual(second["jockey_name"], "Ryusei Sakai")
        self.assertEqual(second["trainer_name"], "Yoshito Yahagi")
        self.assertEqual(second["margin"], "0.98L")
        self.assertEqual(second["odds_value"], "1.60")
        self.assertEqual(second["finish_time"], "2:04.55")
        self.assertEqual(second["source_refs"]["country_code"], "JPN")
        # 马主来自彩衣 tooltip
        self.assertEqual(winner["source_refs"]["owner_name"], "Winchell Thoroughbreds, LLC")
        # 单场 ajax 页无场头：赛名留空，日期来自 URL
        self.assertEqual(metadata["local_date"], "2026-03-28")
        self.assertEqual(metadata["race_number"], "9")
        self.assertEqual(metadata["race_title"], "")
        self.assertEqual(metadata["row_count"], 9)
        self.assertEqual(metadata["result_count"], 9)

    def test_multi_race_page_selects_race_by_number(self):
        html = _fixture("era_ajax_racecard-results-all_2026-03-28_races8_9.html")
        runners, results, metadata = self.module._parse_results_all_page(
            html, source_url=ALL_DAY_URL, race_number="9"
        )
        self.assertEqual(len(runners), 9)
        self.assertEqual(results[0]["horse_name"], "MAGNITUDE")
        self.assertEqual(metadata["race_title"], "Dubai World Cup Sponsored by Emirates Airline")
        self.assertEqual(metadata["grade_text"], "Group 1")
        self.assertEqual(metadata["surface"], "dirt")
        self.assertEqual(metadata["prize_text"], "AED 12,000,000")
        self.assertEqual(metadata["distance_text"], "2000m")
        self.assertEqual(metadata["racecourse"], "Meydan")
        self.assertEqual(metadata["race_time"], "20:45")
        self.assertEqual(metadata["local_date"], "2026-03-28")

        runners8, results8, metadata8 = self.module._parse_results_all_page(
            html, source_url=ALL_DAY_URL, race_number="8"
        )
        self.assertEqual(len(runners8), 6)
        self.assertEqual(results8[0]["horse_name"], "CALANDAGAN")
        self.assertEqual(metadata8["race_title"], "Longines Dubai Sheema Classic")

    def test_race_number_not_found_raises(self):
        with self.assertRaises(RuntimeError):
            self.module._parse_results_all_page(
                _fixture("era_ajax_racecard-results-all_2026-03-28_races8_9.html"),
                source_url=ALL_DAY_URL,
                race_number="3",
            )

    def test_empty_table_raises(self):
        html = """
        <h2 class="racecard__heading order-lg-1 mb-3">Race 9 - Dubai World Cup Sponsored by Emirates Airline</h2>
        <div class="racecard-table" data-table-wrapper>
          <table class="racecard-table__table racecard-table__table--results">
            <tbody class="racecard-table__tbody"></tbody>
          </table>
        </div>
        """
        with self.assertRaises(RuntimeError):
            self.module._parse_results_all_page(html, source_url=ALL_DAY_URL, race_number="9")

    def test_page_matches_event_guard(self):
        metadata = {
            "racecourse": "Meydan",
            "local_date": "2026-03-28",
            "race_title": "Dubai World Cup Sponsored by Emirates Airline",
        }
        self.assertTrue(
            self.module._page_matches_event(
                {"racecourse": "Meydan", "local_date": "2026-03-28", "original_name": "Dubai World Cup"},
                metadata,
            )
        )
        self.assertFalse(
            self.module._page_matches_event(
                {"racecourse": "Meydan", "local_date": "2026-03-27", "original_name": "Dubai World Cup"},
                metadata,
            )
        )
        self.assertFalse(
            self.module._page_matches_event(
                {"racecourse": "Meydan", "local_date": "2026-03-28", "original_name": "Dubai Turf"},
                metadata,
            )
        )
        # 场头缺赛名时无法核验，fail closed
        self.assertFalse(
            self.module._page_matches_event(
                {"racecourse": "Meydan", "local_date": "2026-03-28", "original_name": "Dubai World Cup"},
                {**metadata, "race_title": ""},
            )
        )


class EraCandidateFlowTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load("prepare_era_race_detail_candidates.py")

    def _write_events(self, root: Path, rows: list[dict]) -> Path:
        path = root / "events.csv"
        fieldnames = ["year", "slug", "status", "local_date", "racecourse", "original_name", "source_refs"]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def _event(self, **overrides) -> dict:
        event = {
            "year": "2026",
            "slug": "uae-dubai-world-cup-2026",
            "status": "finished",
            "local_date": "2026-03-28",
            "racecourse": "Meydan",
            "original_name": "Dubai World Cup",
            "source_refs": json.dumps(
                {
                    "detail_discovery": {
                        "race_number": "9",
                        "urls": {
                            "result_url": {
                                "url": ALL_DAY_URL,
                                "source_provider": "era",
                            }
                        },
                    }
                }
            ),
        }
        event.update(overrides)
        return event

    def test_main_flow_writes_candidates(self):
        html = _fixture("era_ajax_racecard-results-all_2026-03-28_races8_9.html")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_events(root, [self._event()])
            args = SimpleNamespace(
                events_csv=[str(events)],
                source_map_json="",
                output_dir=str(root / "out"),
                allow_network=False,
                limit=0,
                timeout_seconds=10,
                sleep_seconds=0,
                fail_fast=True,
            )
            with patch.object(self.module, "_download", return_value=html) as download:
                summary = self.module.prepare_candidates(args)
            self.assertEqual(summary["events"], 1)
            self.assertEqual(summary["runner_items"], 9)
            self.assertEqual(summary["result_items"], 9)
            self.assertEqual(summary["errors"], [])
            self.assertEqual(download.call_args.args[0], ALL_DAY_URL)
            records = [
                json.loads(line)
                for line in (root / "out" / "era_detail_candidates.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["source_name"], "era_racecard_results")
            self.assertEqual(record["source_url"], ALL_DAY_URL)
            self.assertEqual(record["metadata"]["race_title"], "Dubai World Cup Sponsored by Emirates Airline")
            results = record["modules"]["results"]["items"]
            self.assertEqual(results[0]["horse_name"], "MAGNITUDE")
            review = (root / "out" / "era_detail_review.csv").read_text(encoding="utf-8-sig")
            self.assertIn("MAGNITUDE", review)

    def test_main_flow_collects_identity_mismatch_as_error(self):
        html = _fixture("era_ajax_racecard-results-all_2026-03-28_races8_9.html")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_events(root, [self._event(original_name="Dubai Turf")])
            args = SimpleNamespace(
                events_csv=[str(events)],
                source_map_json="",
                output_dir=str(root / "out"),
                allow_network=False,
                limit=0,
                timeout_seconds=10,
                sleep_seconds=0,
                fail_fast=False,
            )
            with patch.object(self.module, "_download", return_value=html):
                summary = self.module.prepare_candidates(args)
            self.assertEqual(summary["events"], 0)
            self.assertEqual(len(summary["errors"]), 1)
            self.assertEqual(summary["errors"][0]["slug"], "uae-dubai-world-cup-2026")

    def test_download_rejects_unapproved_host(self):
        with TemporaryDirectory() as tmp:
            cached = Path(tmp) / "cached.html"
            cached.write_text("cached", encoding="utf-8")
            with self.assertRaises(self.module.SafeHttpError):
                self.module._download(
                    "https://attacker.example/ajax/racecard-results-all?date=2026-03-28",
                    cached,
                    allow_network=False,
                    timeout=10,
                    sleep_seconds=0,
                )

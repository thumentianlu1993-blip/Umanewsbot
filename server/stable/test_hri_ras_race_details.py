"""HRI 官方赛果页（hri-ras.ie race-result）解析与候选生成测试。

被测模块：runtime/tools/prepare_hri_ras_race_detail_candidates.py
fixture：server/stable/fixtures/hri/hri_result_2025-06-29_curragh_r1610_irish_derby.html
（2025 年爱尔兰德比，10 匹出走）。测试中禁止访问网络。
"""
from __future__ import annotations

import importlib.util
import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "hri"
FIXTURE_HTML = FIXTURES / "hri_result_2025-06-29_curragh_r1610_irish_derby.html"
SOURCE_URL = "https://www.hri-ras.ie/results/race-result/?date=2025-06-29&race=1610&venue=CU"


def _load_module():
    path = TOOLS / "prepare_hri_ras_race_detail_candidates.py"
    spec = importlib.util.spec_from_file_location("prepare_hri_ras_race_detail_candidates_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class HriRasResultPageParseTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_module()
        cls.html = FIXTURE_HTML.read_text(encoding="utf-8")
        cls.runners, cls.results, cls.metadata = cls.module._parse_result_page(
            cls.html, source_url=SOURCE_URL
        )

    def test_ten_runners_and_ten_results(self):
        self.assertEqual(len(self.runners), 10)
        self.assertEqual(len(self.results), 10)
        self.assertEqual(self.metadata["row_count"], 10)
        self.assertEqual(self.metadata["result_count"], 10)

    def test_metadata_from_header_and_url(self):
        self.assertEqual(self.metadata["racecourse"], "Curragh")
        self.assertEqual(self.metadata["local_date"], "2025-06-29")
        self.assertEqual(self.metadata["race_title"], "The Dubai Duty Free Irish Derby (Group 1)")
        self.assertEqual(self.metadata["venue_code"], "CU")
        self.assertEqual(self.metadata["race_time"], "2:29.1")
        self.assertEqual(self.metadata["distance_text"], "1m4f")

    def test_winner_fields(self):
        winner = self.results[0]
        self.assertEqual(winner["finish_position"], 1)
        self.assertEqual(winner["official_finish_position"], 1)
        self.assertEqual(winner["horse_name"], "Lambourn")
        self.assertEqual(winner["horse_number"], "2")
        self.assertEqual(winner["barrier"], "5")
        self.assertEqual(winner["jockey_name"], "R.L. Moore")
        self.assertEqual(winner["trainer_name"], "A.P.O'Brien")
        self.assertEqual(winner["carried_weight"], "9-2")
        self.assertEqual(winner["margin"], "")
        self.assertEqual(winner["finish_time"], "")
        self.assertTrue(winner["is_confirmed"])
        self.assertEqual(winner["source_refs"]["primary"], SOURCE_URL)
        self.assertEqual(winner["source_refs"]["source_language"], "en")
        self.assertEqual(winner["source_refs"]["official_finish_position"], 1)
        self.assertIn("hid=", winner["source_refs"]["horse_url"])

    def test_finish_order_and_margins(self):
        names = [row["horse_name"] for row in self.results]
        self.assertEqual(
            names[:3], ["Lambourn", "Serious Contender", "Lazy Griff"]
        )
        self.assertEqual(names[-1], "Pride Of Arras")
        self.assertEqual([row["finish_position"] for row in self.results], list(range(1, 11)))
        second = self.results[1]
        self.assertEqual(second["margin"], "¾ lengths")
        self.assertEqual(second["jockey_name"], "G.M. Ryan")
        fourth = self.results[3]
        self.assertEqual(fourth["horse_name"], "Tennessee Stud")
        self.assertEqual(fourth["margin"], "Neck")

    def test_runners_sorted_by_horse_number_with_sort_order(self):
        self.assertEqual([row["horse_number"] for row in self.runners][:3], ["1", "2", "3"])
        self.assertEqual([row["sort_order"] for row in self.runners], list(range(1, 11)))
        first = self.runners[0]
        self.assertEqual(first["horse_name"], "Green Impact")
        self.assertEqual(first["jockey_name"], "S. Foley")

    def test_country_suffix_stripped_from_horse_name(self):
        row = next(row for row in self.runners if row["horse_number"] == "3")
        self.assertEqual(row["horse_name"], "Lazy Griff")
        self.assertEqual(row["source_refs"]["horse_name_raw"], "Lazy Griff (GER)")

    def test_tote_odds_only_winner_has_win_value(self):
        winner = next(row for row in self.runners if row["horse_name"] == "Lambourn")
        self.assertEqual(winner["odds_value"], "1.62")
        self.assertEqual(winner["source_refs"]["odds_kind"], "tote")
        self.assertEqual(winner["source_refs"]["tote_win_raw"], "€1.62")
        runner_up = next(row for row in self.runners if row["horse_name"] == "Serious Contender")
        self.assertEqual(runner_up["odds_value"], "")
        self.assertEqual(runner_up["source_refs"]["odds_kind"], "tote")
        self.assertEqual(runner_up["source_refs"]["tote_place_raw"], "€5.30")

    def test_all_runners_declared(self):
        for row in self.runners:
            self.assertEqual(row["running_status"], "declared")

    def test_url_date_mismatch_raises(self):
        bad_url = "https://www.hri-ras.ie/results/race-result/?date=2025-06-30&race=1610&venue=CU"
        with self.assertRaises(Exception):
            self.module._parse_result_page(self.html, source_url=bad_url)

    def test_empty_page_raises(self):
        with self.assertRaises(Exception):
            self.module._parse_result_page(
                "<html><body><div class='race-card'></div></body></html>", source_url=SOURCE_URL
            )

    def test_panels_without_finish_positions_raise(self):
        html = """
        <p class="race-course"><a href="#">Curragh</a></p>
        <p class="date">Sunday, 29th Jun 2025</p>
        <div class="inner race-details"><h2>Test Race</h2></div>
        <div class="panel panel-default">
          <div class="panel-heading panel-race-card" role="tab" id="headRaceCard1">
            <h5 class="panel-title"><a>
              <span class="place"><b>PU</b></span>
              <ul class="list-inline race-card-ext">
                <li><b>1. <span>Test Horse</span></b></li>
                <li><strong>Drawn:</strong> 2</li>
                <li><b>R:</b>&nbsp;<span>J. Doe</span></li>
                <li><b>T: </b>T. Trainer</li>
                <li><b>9 - 0</b></li>
              </ul>
            </a></h5>
          </div>
          <div id="detailRaceCard1" class="panel-collapse collapse">
            <div class="panel-body"></div>
          </div>
        </div>
        """
        with self.assertRaises(Exception):
            self.module._parse_result_page(html, source_url=SOURCE_URL)

    def test_page_matches_event_guard(self):
        event = {
            "local_date": "2025-06-29",
            "racecourse": "Curragh",
            "original_name": "Irish Derby",
        }
        self.assertTrue(self.module._page_matches_event(event, self.metadata))
        self.assertFalse(
            self.module._page_matches_event({**event, "local_date": "2025-06-28"}, self.metadata)
        )
        self.assertFalse(
            self.module._page_matches_event({**event, "racecourse": "Leopardstown"}, self.metadata)
        )
        self.assertFalse(
            self.module._page_matches_event({**event, "original_name": "Irish Oaks"}, self.metadata)
        )

    def test_allowed_hosts_restricted_to_hri_ras(self):
        self.assertEqual(self.module.ALLOWED_HOSTS, ("www.hri-ras.ie",))
        with self.assertRaisesRegex(Exception, "allowlist"):
            self.module.validate_https_url(
                "https://evil.example/results/race-result/", allowed_hosts=self.module.ALLOWED_HOSTS
            )


class HriRasPrepareCandidatesTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_module()
        cls.html = FIXTURE_HTML.read_text(encoding="utf-8")

    def _event_row(self, **overrides):
        row = {
            "year": "2025",
            "slug": "irish-derby",
            "status": "finished",
            "country_region": "ireland",
            "local_date": "2025-06-29",
            "racecourse": "Curragh",
            "original_name": "Irish Derby",
            "source_refs": json.dumps(
                {
                    "detail_discovery": {
                        "urls": {
                            "result_url": {
                                "url": SOURCE_URL,
                                "source_provider": "hri_ras",
                            }
                        }
                    }
                }
            ),
        }
        row.update(overrides)
        return row

    def _write_events_csv(self, path: Path, rows: list[dict]):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def _args(self, output_dir: Path, events_csv: Path, **overrides):
        defaults = {
            "events_csv": [str(events_csv)],
            "source_map_json": "",
            "output_dir": str(output_dir),
            "allow_network": False,
            "limit": 0,
            "timeout_seconds": 30,
            "sleep_seconds": 0.0,
            "fail_fast": False,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_offline_cached_run_produces_candidates(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_csv = root / "events.csv"
            self._write_events_csv(events_csv, [self._event_row()])
            output_dir = root / "out"
            source_dir = output_dir / "sources"
            source_dir.mkdir(parents=True)
            (source_dir / "source_hri_ras_2025_irish-derby.html").write_text(self.html, encoding="utf-8")

            summary = self.module.prepare_candidates(self._args(output_dir, events_csv))

            self.assertEqual(summary["events"], 1)
            self.assertEqual(summary["runner_items"], 10)
            self.assertEqual(summary["result_items"], 10)
            self.assertEqual(summary["errors"], [])
            records = [
                json.loads(line)
                for line in (output_dir / "hri_ras_detail_candidates.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["source_name"], "hri_ras_result")
            self.assertEqual(record["source_url"], SOURCE_URL)
            runners = record["modules"]["runners"]["items"]
            results = record["modules"]["results"]["items"]
            self.assertEqual(len(runners), 10)
            self.assertEqual(len(results), 10)
            self.assertEqual(results[0]["horse_name"], "Lambourn")
            self.assertEqual(record["metadata"]["local_date"], "2025-06-29")
            review_rows = list(
                csv.DictReader((output_dir / "hri_ras_detail_review.csv").open(encoding="utf-8-sig"))
            )
            self.assertEqual(review_rows[0]["winner"], "Lambourn")
            summary_doc = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary_doc["events"], 1)

    def test_missing_cache_without_network_records_error(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_csv = root / "events.csv"
            self._write_events_csv(events_csv, [self._event_row()])
            output_dir = root / "out"

            summary = self.module.prepare_candidates(self._args(output_dir, events_csv))

            self.assertEqual(summary["events"], 0)
            self.assertEqual(len(summary["errors"]), 1)

    def test_fail_fast_raises_on_first_error(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_csv = root / "events.csv"
            self._write_events_csv(events_csv, [self._event_row()])
            with self.assertRaises(Exception):
                self.module.prepare_candidates(
                    self._args(root / "out", events_csv, fail_fast=True)
                )

    def test_non_finished_events_are_skipped(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_csv = root / "events.csv"
            self._write_events_csv(events_csv, [self._event_row(status="scheduled")])
            output_dir = root / "out"

            summary = self.module.prepare_candidates(self._args(output_dir, events_csv))

            self.assertEqual(summary["events"], 0)
            self.assertEqual(summary["errors"], [])
            records = (output_dir / "hri_ras_detail_candidates.jsonl").read_text(encoding="utf-8")
            self.assertEqual(records.strip(), "")

    def test_page_event_mismatch_records_error(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_csv = root / "events.csv"
            self._write_events_csv(events_csv, [self._event_row(local_date="2025-06-28")])
            output_dir = root / "out"
            source_dir = output_dir / "sources"
            source_dir.mkdir(parents=True)
            (source_dir / "source_hri_ras_2025_irish-derby.html").write_text(self.html, encoding="utf-8")

            summary = self.module.prepare_candidates(self._args(output_dir, events_csv))

            self.assertEqual(summary["events"], 0)
            self.assertEqual(len(summary["errors"]), 1)

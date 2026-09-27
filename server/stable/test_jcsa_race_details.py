"""JCSA（沙特 jcsa.sa）赛果详情解析测试。"""

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
SAUDI_CUP_URL = "https://jcsa.sa/api/meeting-info/en/20260214/9/Results/True"


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


class JcsaResultsPageTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load("prepare_jcsa_race_detail_candidates.py")

    def test_saudi_cup_results_fields(self):
        runners, results, metadata = self.module._parse_results_page(
            _fixture("jcsa_api_meeting-info_en_20260214_9_Results_True.html"),
            source_url=SAUDI_CUP_URL,
        )
        # 14 出走，13 个正式名次（Star Of Wonder 无名次）
        self.assertEqual(len(runners), 14)
        self.assertEqual(len(results), 13)
        self.assertEqual(metadata["local_date"], "2026-02-14")
        self.assertEqual(metadata["race_number"], "9")
        self.assertEqual(metadata["racecourse"], "King Abdulaziz Racetrack")
        self.assertEqual(metadata["winning_time"], "1:51.027")
        self.assertEqual(metadata["row_count"], 14)
        self.assertEqual(metadata["result_count"], 13)

        winner = results[0]
        self.assertEqual(winner["finish_position"], 1)
        self.assertEqual(winner["official_finish_position"], 1)
        # 马名国别后缀剥离进 source_refs
        self.assertEqual(winner["horse_name"], "Forever Young")
        self.assertEqual(winner["source_refs"]["horse_name_raw"], "Forever Young (JPN)")
        self.assertEqual(winner["source_refs"]["country_code"], "JPN")
        self.assertEqual(winner["source_refs"]["horse_url"], "/en/horses/H-64589")
        # 马名单元格内联 J/T/O 拆分
        self.assertEqual(winner["jockey_name"], "Ryusei Sakai")
        self.assertEqual(winner["trainer_name"], "Yoshito Yahagi")
        self.assertEqual(winner["source_refs"]["owner_name"], "Susumu Fujita")
        self.assertEqual(winner["carried_weight"], "57")
        # finish_time 取 winner 的 Time 原样
        self.assertEqual(winner["finish_time"], "1:51.027")
        self.assertEqual(winner["margin"], "")
        # JCSA 结果页无赔率
        self.assertEqual(winner["odds_value"], "")
        self.assertTrue(winner["is_confirmed"])
        self.assertEqual(winner["source_refs"]["official_finish_position"], 1)
        self.assertEqual(winner["source_refs"]["prize_money"], "10,000,000")

        second = results[1]
        self.assertEqual(second["horse_name"], "Nysos")
        self.assertEqual(second["jockey_name"], "Flavien Prat")
        self.assertEqual(second["trainer_name"], "Bob Baffert")
        self.assertEqual(second["margin"], "1")
        self.assertEqual(second["finish_time"], "1:51.218")
        self.assertEqual(second["source_refs"]["country_code"], "USA")

        # 无名次马保留在 runners、不进 results
        self.assertEqual(results[-1]["horse_name"], "Haqeet")
        unplaced = [row for row in runners if row["horse_name"] == "Star Of Wonder"]
        self.assertEqual(len(unplaced), 1)
        self.assertEqual(unplaced[0]["running_status"], "unknown")
        self.assertEqual(unplaced[0]["source_refs"]["finish_position_raw"], "-")
        # JCSA 结果页不公布鞍布号/闸位
        self.assertEqual(winner["horse_number"], "")
        self.assertEqual(winner["barrier"], "")
        # runners 保持表序并顺次编 sort_order
        self.assertEqual([row["sort_order"] for row in runners], list(range(1, 15)))
        self.assertEqual(runners[0]["horse_name"], "Forever Young")

    def test_empty_results_raise(self):
        with self.assertRaises(RuntimeError):
            self.module._parse_results_page(
                "<table><thead><tr><th>Place</th><th>Horse Name</th></tr></thead><tbody></tbody></table>",
                source_url=SAUDI_CUP_URL,
            )

    def test_source_url_without_date_raises(self):
        with self.assertRaises(RuntimeError):
            self.module._parse_results_page(
                _fixture("jcsa_api_meeting-info_en_20260214_9_Results_True.html"),
                source_url="https://jcsa.sa/en/races/20260214/9",
            )


class JcsaCandidateFlowTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load("prepare_jcsa_race_detail_candidates.py")

    def _event(self, **overrides) -> dict:
        event = {
            "year": "2026",
            "slug": "saudi-saudi-cup-2026",
            "status": "finished",
            "local_date": "2026-02-14",
            "racecourse": "King Abdulaziz Racetrack",
            "original_name": "Saudi Cup",
            "source_refs": json.dumps(
                {
                    "detail_discovery": {
                        "urls": {
                            "result_url": {
                                "url": SAUDI_CUP_URL,
                                "source_provider": "jcsa",
                            }
                        }
                    }
                }
            ),
        }
        event.update(overrides)
        return event

    def test_main_flow_writes_candidates(self):
        html = _fixture("jcsa_api_meeting-info_en_20260214_9_Results_True.html")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.csv"
            with events.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["year", "slug", "status", "local_date", "racecourse", "original_name", "source_refs"],
                )
                writer.writeheader()
                writer.writerow(self._event())
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
            self.assertEqual(summary["runner_items"], 14)
            self.assertEqual(summary["result_items"], 13)
            self.assertEqual(summary["errors"], [])
            self.assertEqual(download.call_args.args[0], SAUDI_CUP_URL)
            records = [
                json.loads(line)
                for line in (root / "out" / "jcsa_detail_candidates.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["source_name"], "jcsa_meeting_results")
            results = records[0]["modules"]["results"]["items"]
            self.assertEqual(results[0]["horse_name"], "Forever Young")
            self.assertEqual(results[0]["finish_time"], "1:51.027")

    def test_main_flow_rejects_date_mismatch(self):
        html = _fixture("jcsa_api_meeting-info_en_20260214_9_Results_True.html")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.csv"
            with events.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["year", "slug", "status", "local_date", "racecourse", "original_name", "source_refs"],
                )
                writer.writeheader()
                writer.writerow(self._event(local_date="2026-02-15"))
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

    def test_download_rejects_unapproved_host(self):
        with TemporaryDirectory() as tmp:
            cached = Path(tmp) / "cached.html"
            cached.write_text("cached", encoding="utf-8")
            with self.assertRaises(self.module.SafeHttpError):
                self.module._download(
                    "https://attacker.example/api/meeting-info/en/20260214/9/Results/True",
                    cached,
                    allow_network=False,
                    timeout=10,
                    sleep_seconds=0,
                )

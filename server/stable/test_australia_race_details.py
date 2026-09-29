"""澳洲赛果详情候选工具（Racing Australia / Just Horse Racing 双 provider）的测试。

fixture 来自 2026-09-27 真实页面探测样本裁剪（保留解析所需结构）：

- ra_results_2025-10-25_thevalley.html：RA 全天多赛页（Key=2025Oct25,VIC,The Valley），
  保留 Race 1（含 DQ 与空 Finish 退赛）、Race 8（含 SB 闸前退出）、
  Race 9（Drummond Golf Vase，14 出走）与 Race 10（Ladbrokes Cox Plate，9 出走，
  冠军 VIA SISTINA，GLOBE 退赛 Finish 为空）。
- ra_results_2025-11-04_flemington.html：RA 保留期缺口页
  （"Results for this meeting are not currently available."）。
- justhorseracing_melbourne_cup_2025_results.html：24 出走，冠军 HALF YOURS，
  无 Starting Price 列，第 16 名并列（dead-heat），末行缺 Penalty/SP 单元格。
- justhorseracing_cox_plate_2025_results.html：9 行含 Starting Price，GLOBE 标 SCR。
"""
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
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "australia"
RA_THE_VALLEY_URL = "https://racingaustralia.horse/FreeFields/Results.aspx?Key=2025Oct25,VIC,The%20Valley"
RA_FLEMINGTON_URL = "https://racingaustralia.horse/FreeFields/Results.aspx?Key=2025Nov04,VIC,Flemington"
JHR_MELBOURNE_CUP_URL = (
    "https://www.justhorseracing.com.au/fields-results/results/"
    "melbourne-cup-results-replay-and-finishing-positions-half-yours-2025/869400"
)
JHR_COX_PLATE_URL = (
    "https://www.justhorseracing.com.au/fields-results/results/"
    "cox-plate-results-and-replay-via-sistina-2025/868422"
)
WAYBACK_CAULFIELD_URL = (
    "https://web.archive.org/web/20251023160442/"
    "https://www.racingaustralia.horse/FreeFields/Results.aspx?Key=2025Oct18%2CVIC%2CCaulfield"
)


def _load():
    path = TOOLS / "prepare_racing_australia_race_detail_candidates.py"
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


class RacingAustraliaResultsPageTests(SimpleTestCase):
    """RA Results.aspx 全天多赛页 parser。"""

    def setUp(self):
        self.module = _load()
        self.html = _fixture("ra_results_2025-10-25_thevalley.html")

    def test_selects_target_race_from_multi_race_page(self):
        runners, results, metadata = self.module._parse_results_page(
            self.html, source_url=RA_THE_VALLEY_URL, race_number="10"
        )

        self.assertEqual(metadata["racecourse"], "The Valley")
        self.assertEqual(metadata["local_date"], "2025-10-25")
        self.assertEqual(metadata["race_number"], "10")
        self.assertEqual(metadata["race_title"], "Ladbrokes Cox Plate")
        self.assertEqual(metadata["distance_text"], "2040")
        self.assertEqual(metadata["available_race_numbers"], ["1", "8", "9", "10"])
        self.assertEqual(metadata["row_count"], 9)
        self.assertEqual(metadata["result_count"], 8)

        self.assertEqual(len(runners), 9)
        self.assertEqual(len(results), 8)
        winner_runner = next(row for row in runners if row["horse_number"] == "6")
        self.assertEqual(winner_runner["horse_name"], "VIA SISTINA")
        self.assertEqual(winner_runner["trainer_name"], "Chris Waller")
        self.assertEqual(winner_runner["jockey_name"], "James McDonald")
        self.assertEqual(winner_runner["carried_weight"], "57kg")
        self.assertEqual(winner_runner["odds_value"], "$2.25F")
        self.assertEqual(winner_runner["barrier"], "5")
        self.assertEqual(winner_runner["running_status"], "declared")

        winner = results[0]
        self.assertEqual(winner["horse_name"], "VIA SISTINA")
        self.assertEqual(winner["finish_position"], 1)
        self.assertEqual(winner["official_finish_position"], 1)
        self.assertEqual(winner["margin"], "")
        self.assertTrue(winner["is_confirmed"])
        self.assertEqual(results[1]["horse_name"], "BUCKAROO")
        self.assertEqual(results[1]["margin"], "0.1L")

    def test_runner_and_result_source_refs_contract(self):
        runners, results, _metadata = self.module._parse_results_page(
            self.html, source_url=RA_THE_VALLEY_URL, race_number="10"
        )

        winner_runner = next(row for row in runners if row["horse_number"] == "6")
        refs = winner_runner["source_refs"]
        self.assertEqual(refs["primary"], RA_THE_VALLEY_URL)
        self.assertEqual(refs["source_language"], "en")
        self.assertEqual(refs["source_kind"], "racing_australia_results")
        self.assertIn("HorseFullForm.aspx", refs["horse_url"])
        self.assertEqual(refs["horse_name_raw"], "VIA SISTINA (IRE)")
        self.assertEqual(refs["finish_position_raw"], "1")
        self.assertEqual(refs["race_number"], "10")
        result_refs = results[0]["source_refs"]
        self.assertEqual(result_refs["official_finish_position"], 1)
        self.assertEqual(result_refs["primary"], RA_THE_VALLEY_URL)
        for key in (
            "horse_number", "barrier", "horse_name", "jockey_name", "trainer_name",
            "carried_weight", "odds_value", "running_status", "sort_order", "source_refs",
        ):
            self.assertIn(key, winner_runner)
        for key in ("finish_position", "official_finish_position", "finish_time", "margin", "is_confirmed"):
            self.assertIn(key, results[0])

    def test_scratched_runner_stays_in_runners_but_not_results(self):
        runners, results, _metadata = self.module._parse_results_page(
            self.html, source_url=RA_THE_VALLEY_URL, race_number="10"
        )

        globe = next(row for row in runners if row["horse_name"] == "GLOBE")
        self.assertEqual(globe["horse_number"], "5")
        self.assertEqual(globe["running_status"], "scratched")
        self.assertEqual(globe["carried_weight"], "")
        self.assertEqual(globe["odds_value"], "")
        self.assertEqual(globe["trainer_name"], "Mick Price & Michael Kent (Jnr)")
        self.assertNotIn("GLOBE", [row["horse_name"] for row in results])

    def test_runners_sorted_by_horse_number_with_sequential_sort_order(self):
        runners, results, _metadata = self.module._parse_results_page(
            self.html, source_url=RA_THE_VALLEY_URL, race_number="10"
        )

        self.assertEqual(
            [row["horse_number"] for row in runners],
            ["1", "2", "3", "4", "5", "6", "7", "8", "9"],
        )
        self.assertEqual([row["sort_order"] for row in runners], list(range(1, 10)))
        self.assertEqual(
            [row["finish_position"] for row in results],
            [1, 2, 3, 4, 5, 6, 7, 8],
        )

    def test_race_number_falls_back_to_source_url_fragment(self):
        runners, results, metadata = self.module._parse_results_page(
            self.html, source_url=RA_THE_VALLEY_URL + "#race-10"
        )

        self.assertEqual(metadata["race_number"], "10")
        self.assertEqual(results[0]["horse_name"], "VIA SISTINA")
        self.assertEqual(len(runners), 9)

    def test_other_race_on_same_page_can_be_selected(self):
        runners, results, metadata = self.module._parse_results_page(
            self.html, source_url=RA_THE_VALLEY_URL, race_number="9"
        )

        self.assertEqual(metadata["race_title"], "Drummond Golf Vase")
        self.assertEqual(len(runners), 14)
        self.assertGreater(len(results), 0)

    def test_dq_runner_kept_as_unknown_without_invented_placing(self):
        # Race 1 含 DQ（MAJOR SHARE，取消资格、无数字名次）与 4 匹空 Finish 退赛马
        runners, results, metadata = self.module._parse_results_page(
            self.html, source_url=RA_THE_VALLEY_URL, race_number="1"
        )

        self.assertEqual(len(runners), 10)
        self.assertEqual(len(results), 5)
        dq = next(row for row in runners if row["horse_name"] == "MAJOR SHARE")
        self.assertEqual(dq["running_status"], "unknown")
        self.assertEqual(dq["source_refs"]["finish_position_raw"], "DQ")
        self.assertNotIn("MAJOR SHARE", [row["horse_name"] for row in results])
        scratched = {row["horse_name"] for row in runners if row["running_status"] == "scratched"}
        self.assertEqual(scratched, {"COLEMAN", "TREMBLES", "EXTREMELY LUCKY", "RED HOT NICC"})

    def test_barrier_scratch_sb_is_treated_as_scratched(self):
        # Race 8 含 SB（TROPICUS，闸前退出）与 1 匹空 Finish 退赛马
        runners, results, _metadata = self.module._parse_results_page(
            self.html, source_url=RA_THE_VALLEY_URL, race_number="8"
        )

        self.assertEqual(len(runners), 9)
        self.assertEqual(len(results), 7)
        sb = next(row for row in runners if row["horse_name"] == "TROPICUS")
        self.assertEqual(sb["running_status"], "scratched")
        self.assertEqual(sb["source_refs"]["finish_position_raw"], "SB")
        self.assertNotIn("TROPICUS", [row["horse_name"] for row in results])

    def test_missing_race_number_fails_closed(self):
        with self.assertRaisesMessage(RuntimeError, "race_number"):
            self.module._parse_results_page(self.html, source_url=RA_THE_VALLEY_URL)

    def test_unknown_race_number_fails_closed(self):
        with self.assertRaisesMessage(RuntimeError, "7"):
            self.module._parse_results_page(self.html, source_url=RA_THE_VALLEY_URL, race_number="7")

    def test_retention_gap_page_raises_specific_error(self):
        html = _fixture("ra_results_2025-11-04_flemington.html")

        with self.assertRaises(self.module.MeetingResultsUnavailableError) as ctx:
            self.module._parse_results_page(html, source_url=RA_FLEMINGTON_URL, race_number="7")

        self.assertEqual(ctx.exception.reason, "retention_window_expired")

    def test_page_without_race_tables_fails_closed(self):
        with self.assertRaises(RuntimeError):
            self.module._parse_results_page(
                "<html><body><p>nothing</p></body></html>",
                source_url=RA_THE_VALLEY_URL,
                race_number="10",
            )

    def test_wayback_wrapped_page_with_toolbar_parses(self):
        # 夹具从 2025-10-18 Caulfield 真实 Wayback 快照（含 toolbar 注入与改写链接）裁剪
        html = _fixture("wayback_ra_results_2025-10-18_caulfield.html")
        self.assertIn("BEGIN WAYBACK TOOLBAR INSERT", html)

        runners, results, metadata = self.module._parse_results_page(
            html, source_url=WAYBACK_CAULFIELD_URL, race_number="7"
        )

        self.assertEqual(metadata["local_date"], "2025-10-18")
        self.assertEqual(metadata["racecourse"], "Caulfield")
        self.assertEqual(metadata["race_title"], "Schweppes Thousand Guineas")
        self.assertEqual(len(runners), 12)
        self.assertEqual(len(results), 12)
        self.assertEqual(results[0]["horse_name"], "OLE DANCER")


class JustHorseRacingPageTests(SimpleTestCase):
    """justhorseracing.com.au 单场赛果页 parser。"""

    def setUp(self):
        self.module = _load()

    def test_melbourne_cup_full_field_without_starting_price_column(self):
        runners, results, metadata = self.module._parse_just_horse_racing_page(
            _fixture("justhorseracing_melbourne_cup_2025_results.html"),
            source_url=JHR_MELBOURNE_CUP_URL,
        )

        self.assertEqual(metadata["racecourse"], "Flemington")
        self.assertEqual(metadata["local_date"], "2025-11-04")
        self.assertEqual(metadata["race_title"], "Melbourne Cup")
        self.assertEqual(len(runners), 24)
        self.assertEqual(len(results), 24)
        winner = results[0]
        self.assertEqual(winner["horse_name"], "HALF YOURS")
        self.assertEqual(winner["trainer_name"], "Tony & Calvin McEvoy")
        self.assertEqual(winner["jockey_name"], "Ms Jamie Melham")
        self.assertEqual(winner["carried_weight"], "53kg")
        self.assertEqual(winner["barrier"], "8")
        self.assertEqual(winner["horse_number"], "14")
        self.assertEqual(winner["finish_position"], 1)
        self.assertEqual(winner["official_finish_position"], 1)
        # 样本没有 Starting Price 列：odds_value 为空字符串且不报错
        self.assertTrue(all(row["odds_value"] == "" for row in runners))

    def test_melbourne_cup_dead_heat_shares_finish_positions(self):
        _runners, results, _metadata = self.module._parse_just_horse_racing_page(
            _fixture("justhorseracing_melbourne_cup_2025_results.html"),
            source_url=JHR_MELBOURNE_CUP_URL,
        )

        positions = [row["official_finish_position"] for row in results]
        self.assertEqual(positions.count(16), 2)
        self.assertNotIn(17, positions)
        dead_heat = {row["horse_name"] for row in results if row["official_finish_position"] == 16}
        self.assertEqual(dead_heat, {"VALIANT KING", "ONESMOOTHOPERATOR"})
        # 展示名次唯一化（满足 (event, finish_position) 唯一约束），官方名次保留并列
        display = [row["finish_position"] for row in results]
        self.assertEqual(display, list(range(1, len(results) + 1)))
        last = results[-1]
        # 末行缺 Penalty/SP 单元格（只有 9 个 td）：仍要按列名对齐解析
        self.assertEqual(last["horse_name"], "BUCKAROO")
        self.assertEqual(last["finish_position"], 24)
        self.assertEqual(last["margin"], "99L")
        self.assertEqual(last["carried_weight"], "57kg")

    def test_cox_plate_starting_price_and_scratched_runner(self):
        runners, results, metadata = self.module._parse_just_horse_racing_page(
            _fixture("justhorseracing_cox_plate_2025_results.html"),
            source_url=JHR_COX_PLATE_URL,
        )

        self.assertEqual(metadata["racecourse"], "Moonee Valley")
        self.assertEqual(metadata["local_date"], "2025-10-25")
        self.assertEqual(metadata["race_title"], "Cox Plate")
        self.assertEqual(len(runners), 9)
        self.assertEqual(len(results), 8)
        winner = results[0]
        self.assertEqual(winner["horse_name"], "VIA SISTINA")
        self.assertEqual(winner["odds_value"], "$2.25F")
        globe = next(row for row in runners if row["horse_name"] == "GLOBE")
        self.assertEqual(globe["running_status"], "scratched")
        self.assertNotIn("GLOBE", [row["horse_name"] for row in results])
        refs = winner["source_refs"]
        self.assertEqual(refs["source_kind"], "just_horse_racing_results")
        self.assertEqual(refs["primary"], JHR_COX_PLATE_URL)
        self.assertEqual(refs["horse_url"], "")

    def test_page_without_identity_sentence_fails_closed(self):
        html = (
            "<html><body><table class='race-strip-fields'>"
            "<tr><th></th><th>Finish</th><th>No.</th><th>Horse</th><th>Trainer</th>"
            "<th>Jockey</th><th>Margin</th><th>Bar.</th><th>Weight</th><th>Penalty</th><th></th></tr>"
            "<tr><td></td><td>1</td><td>1</td><td class='horse'>TEST HORSE</td><td>T</td>"
            "<td>J</td><td></td><td>1</td><td>57kg</td><td></td><td></td></tr>"
            "</table></body></html>"
        )
        with self.assertRaises(RuntimeError):
            self.module._parse_just_horse_racing_page(html, source_url=JHR_MELBOURNE_CUP_URL)

    def test_page_without_strip_table_fails_closed(self):
        with self.assertRaises(RuntimeError):
            self.module._parse_just_horse_racing_page(
                "<html><body><p>The Melbourne Cup was raced at Flemington racecourse on Tuesday, 4 November 2025.</p></body></html>",
                source_url=JHR_MELBOURNE_CUP_URL,
            )


class AustraliaPageMatchGuardTests(SimpleTestCase):
    def setUp(self):
        self.module = _load()

    def test_ra_page_matches_event(self):
        _runners, _results, metadata = self.module._parse_results_page(
            _fixture("ra_results_2025-10-25_thevalley.html"),
            source_url=RA_THE_VALLEY_URL,
            race_number="10",
        )
        event = {
            "local_date": "2025-10-25",
            "racecourse": "The Valley",
            "original_name": "Cox Plate",
        }
        self.assertTrue(self.module._page_matches_event(event, metadata))

    def test_jhr_moonee_valley_matches_the_valley_event(self):
        _runners, _results, metadata = self.module._parse_just_horse_racing_page(
            _fixture("justhorseracing_cox_plate_2025_results.html"),
            source_url=JHR_COX_PLATE_URL,
        )
        event = {
            "local_date": "2025-10-25",
            "racecourse": "The Valley",
            "original_name": "Cox Plate",
        }
        self.assertTrue(self.module._page_matches_event(event, metadata))

    def test_mismatch_on_date_or_name_is_rejected(self):
        _runners, _results, metadata = self.module._parse_just_horse_racing_page(
            _fixture("justhorseracing_melbourne_cup_2025_results.html"),
            source_url=JHR_MELBOURNE_CUP_URL,
        )
        base = {
            "local_date": "2025-11-04",
            "racecourse": "Flemington",
            "original_name": "Melbourne Cup",
        }
        self.assertTrue(self.module._page_matches_event(base, metadata))
        self.assertFalse(self.module._page_matches_event({**base, "local_date": "2025-11-05"}, metadata))
        self.assertFalse(self.module._page_matches_event({**base, "original_name": "Cox Plate"}, metadata))
        self.assertFalse(self.module._page_matches_event({**base, "racecourse": "Caulfield"}, metadata))

    def test_sponsored_event_name_matches_clean_page_title(self):
        # 官方事件名带赞助商前缀（LEXUS MELBOURNE CUP），JHR 页面用净名（Melbourne Cup）：
        # 页面净名 ≥2 个区别性 token 且全部落入事件名时放行（日期/马场已先行校验）
        _runners, _results, metadata = self.module._parse_just_horse_racing_page(
            _fixture("justhorseracing_melbourne_cup_2025_results.html"),
            source_url=JHR_MELBOURNE_CUP_URL,
        )
        event = {
            "local_date": "2025-11-04",
            "racecourse": "Flemington",
            "original_name": "Lexus Melbourne Cup",
        }
        self.assertTrue(self.module._page_matches_event(event, metadata))

    def test_single_token_reverse_match_rejected(self):
        # 页面净名只剩一个区别性 token 时，反向子集太弱，不得放行
        metadata = {"local_date": "2025-11-04", "racecourse": "Flemington", "race_title": "Oaks"}
        event = {
            "local_date": "2025-11-04",
            "racecourse": "Flemington",
            "original_name": "Lexus Melbourne Cup",
        }
        self.assertFalse(self.module._page_matches_event(event, metadata))

    def test_reverse_match_still_rejects_wrong_race(self):
        _runners, _results, metadata = self.module._parse_just_horse_racing_page(
            _fixture("justhorseracing_melbourne_cup_2025_results.html"),
            source_url=JHR_MELBOURNE_CUP_URL,
        )
        event = {
            "local_date": "2025-11-04",
            "racecourse": "Flemington",
            "original_name": "Caulfield Cup",
        }
        self.assertFalse(self.module._page_matches_event(event, metadata))



class AustraliaPrepareCandidatesTests(SimpleTestCase):
    def setUp(self):
        self.module = _load()

    def _write_events(self, root: Path, rows: list[dict]) -> Path:
        path = root / "events.csv"
        fieldnames = ["year", "slug", "status", "local_date", "racecourse", "original_name", "source_refs"]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return path

    def _event_row(self, *, slug: str, provider: str, url: str, date: str, course: str, name: str, status: str = "finished") -> dict:
        return {
            "year": "2025",
            "slug": slug,
            "status": status,
            "local_date": date,
            "racecourse": course,
            "original_name": name,
            "source_refs": json.dumps(
                {
                    "detail_discovery": {
                        "urls": {
                            "result_url": {"url": url, "source_provider": provider}
                        }
                    }
                }
            ),
        }

    def _args(self, root: Path, events: Path, **overrides) -> SimpleNamespace:
        defaults = {
            "events_csv": [str(events)],
            "source_map_json": "",
            "source_provider": "",
            "output_dir": str(root / "out"),
            "allow_network": False,
            "limit": 0,
            "timeout_seconds": 10,
            "sleep_seconds": 0,
            "fail_fast": False,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_ra_flow_uses_existing_cache_without_network(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_events(
                root,
                [
                    self._event_row(
                        slug="australia-cox-plate-2025",
                        provider="racing_australia",
                        url=RA_THE_VALLEY_URL + "#race-10",
                        date="2025-10-25",
                        course="The Valley",
                        name="Cox Plate",
                    )
                ],
            )
            args = self._args(root, events, source_provider="racing_australia")
            cache_dir = root / "out" / "sources"
            cache_dir.mkdir(parents=True)
            (cache_dir / "source_racing_australia_2025_australia-cox-plate-2025.html").write_text(
                _fixture("ra_results_2025-10-25_thevalley.html"), encoding="utf-8"
            )
            with patch.object(self.module, "fetch_https") as fetch, patch.object(
                self.module, "before_network_request"
            ) as budget:
                summary = self.module.prepare_candidates(args)

            fetch.assert_not_called()
            budget.assert_not_called()
            self.assertEqual(summary["events"], 1)
            self.assertEqual(summary["runner_items"], 9)
            self.assertEqual(summary["result_items"], 8)
            self.assertEqual(summary["errors"], [])
            jsonl = root / "out" / "racing_australia_detail_candidates.jsonl"
            record = json.loads(jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(record["source_name"], "racing_australia_results")
            self.assertEqual(record["source_url"], RA_THE_VALLEY_URL + "#race-10")
            self.assertEqual(record["modules"]["results"]["items"][0]["horse_name"], "VIA SISTINA")
            self.assertEqual(record["metadata"]["race_number"], "10")
            review = (root / "out" / "australia_detail_review.csv").read_text(encoding="utf-8-sig")
            self.assertIn("VIA SISTINA", review)
            self.assertTrue((root / "out" / "summary.json").is_file())

    def test_jhr_flow_via_source_map(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_events(
                root,
                [
                    self._event_row(
                        slug="australia-melbourne-cup-2025",
                        provider="just_horse_racing",
                        url="",
                        date="2025-11-04",
                        course="Flemington",
                        name="Melbourne Cup",
                    )
                ],
            )
            source_map = root / "source_map.json"
            source_map.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "year": 2025,
                                "slug": "australia-melbourne-cup-2025",
                                "source_provider": "just_horse_racing",
                                "source_url": JHR_MELBOURNE_CUP_URL,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            args = self._args(root, events, source_map_json=str(source_map))
            with patch.object(
                self.module,
                "_download",
                return_value=_fixture("justhorseracing_melbourne_cup_2025_results.html"),
            ):
                summary = self.module.prepare_candidates(args)

            self.assertEqual(summary["events"], 1)
            self.assertEqual(summary["runner_items"], 24)
            self.assertEqual(summary["result_items"], 24)
            jsonl = root / "out" / "just_horse_racing_detail_candidates.jsonl"
            record = json.loads(jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(record["source_name"], "just_horse_racing_results")
            self.assertEqual(record["modules"]["results"]["items"][0]["horse_name"], "HALF YOURS")

    def test_source_map_rejects_url_outside_allowlist(self):
        with TemporaryDirectory() as tmp:
            source_map = Path(tmp) / "source_map.json"
            source_map.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "year": 2025,
                                "slug": "australia-cox-plate-2025",
                                "source_provider": "racing_australia",
                                "source_url": "https://attacker.example/results",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                self.module._read_source_map(str(source_map))

    def test_source_map_rejects_unknown_provider(self):
        with TemporaryDirectory() as tmp:
            source_map = Path(tmp) / "source_map.json"
            source_map.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "year": 2025,
                                "slug": "australia-cox-plate-2025",
                                "source_provider": "racenet",
                                "source_url": RA_THE_VALLEY_URL,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesMessage(RuntimeError, "provider"):
                self.module._read_source_map(str(source_map))

    def test_download_rejects_disallowed_host_and_plain_http_before_network(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "page.html"
            for url in (
                "https://attacker.example/results",
                "http://racingaustralia.horse/FreeFields/Results.aspx?Key=2025Oct25,VIC,The%20Valley",
            ):
                with self.subTest(url=url), patch.object(
                    self.module, "before_network_request"
                ) as budget, patch.object(self.module, "fetch_https") as fetch:
                    with self.assertRaises(RuntimeError):
                        self.module._download(
                            url, target, allow_network=True, timeout=10, sleep_seconds=0
                        )
                budget.assert_not_called()
                fetch.assert_not_called()

    def test_retention_gap_is_recorded_with_reason(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_events(
                root,
                [
                    self._event_row(
                        slug="australia-melbourne-cup-2025",
                        provider="racing_australia",
                        url=RA_FLEMINGTON_URL + "#race-7",
                        date="2025-11-04",
                        course="Flemington",
                        name="Melbourne Cup",
                    )
                ],
            )
            args = self._args(root, events, source_provider="racing_australia")
            cache_dir = root / "out" / "sources"
            cache_dir.mkdir(parents=True)
            (cache_dir / "source_racing_australia_2025_australia-melbourne-cup-2025.html").write_text(
                _fixture("ra_results_2025-11-04_flemington.html"), encoding="utf-8"
            )
            summary = self.module.prepare_candidates(args)

            self.assertEqual(summary["events"], 0)
            self.assertEqual(len(summary["errors"]), 1)
            self.assertEqual(summary["errors"][0]["reason"], "retention_window_expired")

    def test_page_mismatch_is_collected_as_error(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_events(
                root,
                [
                    self._event_row(
                        slug="australia-melbourne-cup-2025",
                        provider="just_horse_racing",
                        url=JHR_MELBOURNE_CUP_URL,
                        date="2025-11-05",
                        course="Flemington",
                        name="Melbourne Cup",
                    )
                ],
            )
            args = self._args(root, events, source_provider="just_horse_racing")
            with patch.object(
                self.module,
                "_download",
                return_value=_fixture("justhorseracing_melbourne_cup_2025_results.html"),
            ):
                summary = self.module.prepare_candidates(args)

            self.assertEqual(summary["events"], 0)
            self.assertEqual(len(summary["errors"]), 1)
            self.assertNotIn("reason", summary["errors"][0])

    def test_fail_fast_reraises(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_events(
                root,
                [
                    self._event_row(
                        slug="australia-melbourne-cup-2025",
                        provider="just_horse_racing",
                        url=JHR_MELBOURNE_CUP_URL,
                        date="2025-11-05",
                        course="Flemington",
                        name="Melbourne Cup",
                    )
                ],
            )
            args = self._args(root, events, source_provider="just_horse_racing", fail_fast=True)
            with patch.object(
                self.module,
                "_download",
                return_value=_fixture("justhorseracing_melbourne_cup_2025_results.html"),
            ), self.assertRaises(RuntimeError):
                self.module.prepare_candidates(args)

    def test_unfinished_events_are_ignored(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_events(
                root,
                [
                    self._event_row(
                        slug="australia-melbourne-cup-2026",
                        provider="just_horse_racing",
                        url=JHR_MELBOURNE_CUP_URL,
                        date="2026-11-03",
                        course="Flemington",
                        name="Melbourne Cup",
                        status="scheduled",
                    )
                ],
            )
            summary = self.module.prepare_candidates(self._args(root, events))

            self.assertEqual(summary["events_requested"], 0)
            self.assertEqual(summary["events"], 0)

    def test_error_reason_objects_are_serialized_as_strings(self):
        # 真实批次中 URLError.reason（异常对象）曾让 summary.json 的 json.dumps 崩溃
        from urllib.error import URLError

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_events(
                root,
                [
                    self._event_row(
                        slug="australia-melbourne-cup-2025",
                        provider="just_horse_racing",
                        url=JHR_MELBOURNE_CUP_URL,
                        date="2025-11-04",
                        course="Flemington",
                        name="Melbourne Cup",
                    )
                ],
            )
            args = self._args(root, events, source_provider="just_horse_racing")
            with patch.object(
                self.module, "_download", side_effect=URLError(OSError("boom"))
            ):
                summary = self.module.prepare_candidates(args)
            self.assertEqual(len(summary["errors"]), 1)
            payload = json.loads(
                (Path(args.output_dir) / "summary.json").read_text(encoding="utf-8")
            )
            self.assertIsInstance(payload["errors"][0].get("reason"), str)

    def test_source_map_accepts_wayback_wrapped_url(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_map = root / "source_map.json"
            source_map.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "year": 2025,
                                "slug": "australia-thousand-guineas-2025",
                                "source_provider": "racing_australia",
                                "source_url": WAYBACK_CAULFIELD_URL,
                                "race_number": "7",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            mapped = self.module._read_source_map(str(source_map))

        self.assertEqual(mapped[(2025, "australia-thousand-guineas-2025")]["url"], WAYBACK_CAULFIELD_URL)

    def test_wayback_wrapped_source_url_flow_uses_cache(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_events(
                root,
                [
                    self._event_row(
                        slug="australia-thousand-guineas-2025",
                        provider="racing_australia",
                        url="",
                        date="2025-10-18",
                        course="Caulfield",
                        name="Schweppes Thousand Guineas",
                    )
                ],
            )
            source_map = root / "source_map.json"
            source_map.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "year": 2025,
                                "slug": "australia-thousand-guineas-2025",
                                "source_provider": "racing_australia",
                                "source_url": WAYBACK_CAULFIELD_URL,
                                "race_number": "7",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            args = self._args(root, events, source_map_json=str(source_map))
            cache_dir = root / "out" / "sources"
            cache_dir.mkdir(parents=True)
            (cache_dir / "source_racing_australia_2025_australia-thousand-guineas-2025.html").write_text(
                _fixture("wayback_ra_results_2025-10-18_caulfield.html"), encoding="utf-8"
            )
            with patch.object(self.module, "fetch_https") as fetch, patch.object(
                self.module, "before_network_request"
            ) as budget:
                summary = self.module.prepare_candidates(args)

            fetch.assert_not_called()
            budget.assert_not_called()
            self.assertEqual(summary["events"], 1)
            self.assertEqual(summary["errors"], [])
            jsonl = root / "out" / "racing_australia_detail_candidates.jsonl"
            record = json.loads(jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(record["source_name"], "racing_australia_results")
            self.assertEqual(record["source_url"], WAYBACK_CAULFIELD_URL)
            self.assertEqual(record["modules"]["results"]["items"][0]["horse_name"], "OLE DANCER")
            self.assertEqual(record["metadata"]["race_number"], "7")


class AustraliaFinishCodeTests(SimpleTestCase):
    """Wayback/JHR 批次实测：FF（Fell）与 LR（Lost Rider） Finish 代码。"""

    def setUp(self):
        self.module = _load()

    def _strip(self, finish_values: list[str]):
        from bs4 import BeautifulSoup

        rows = "".join(
            f"<tr><td></td><td>{finish}</td><td>{i}</td><td class='horse'>Horse {i}</td>"
            f"<td>T. T</td><td>J. J</td><td></td><td>1</td><td>55</td><td></td><td>$5.00</td></tr>"
            for i, finish in enumerate(finish_values, start=1)
        )
        html = (
            "<table class='race-strip-fields'><tr><th>Colour</th><th>Finish</th><th>No.</th>"
            "<th>Horse</th><th>Trainer</th><th>Jockey</th><th>Margin</th><th>Bar.</th>"
            "<th>Weight</th><th>Penalty</th><th>Starting Price</th></tr>"
            f"{rows}</table>"
        )
        return BeautifulSoup(html, "html.parser").find("table")

    def test_ff_and_lr_classified_not_in_results(self):
        strip = self._strip(["1", "FF", "LR", "2"])
        runners, results = self.module._parse_strip_rows(
            strip, source_url="https://racingaustralia.horse/x", source_kind="test", race_number="1"
        )
        by_name = {row["horse_name"]: row for row in runners}
        self.assertEqual(by_name["Horse 2"]["running_status"], "fell")
        self.assertEqual(by_name["Horse 3"]["running_status"], "unseated_rider")
        self.assertEqual([row["horse_name"] for row in results], ["Horse 1", "Horse 4"])

    def test_unknown_finish_code_still_raises(self):
        strip = self._strip(["1", "ZZ", "2"])
        with self.assertRaises(RuntimeError):
            self.module._parse_strip_rows(
                strip, source_url="https://racingaustralia.horse/x", source_kind="test", race_number="1"
            )


class AustraliaDeadHeatDisplayTests(SimpleTestCase):
    """Melbourne Cup 2025 第 16 名并列：finish_position 展示唯一化，official 保留。"""

    def setUp(self):
        self.module = _load()
        _runners, self.results, _meta = self.module._parse_just_horse_racing_page(
            _fixture("justhorseracing_melbourne_cup_2025_results.html"),
            source_url=JHR_MELBOURNE_CUP_URL,
        )

    def test_finish_positions_are_unique_display_positions(self):
        display = [row["finish_position"] for row in self.results]
        self.assertEqual(display, list(range(1, len(self.results) + 1)))

    def test_dead_heat_pair_keeps_official_position(self):
        dead_heat = [row for row in self.results if row["official_finish_position"] == 16]
        self.assertEqual(
            sorted(row["horse_name"] for row in dead_heat),
            ["ONESMOOTHOPERATOR", "VALIANT KING"],
        )
        self.assertNotIn(17, {row["official_finish_position"] for row in self.results})

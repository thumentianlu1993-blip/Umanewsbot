from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.test import SimpleTestCase


TOOL_PATH = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "prepare_hkjc_season_gap_candidates.py"
HKJC_TOOL_PATH = TOOL_PATH.parent / "prepare_hkjc_race_detail_candidates.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("prepare_hkjc_season_gap_candidates_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_hkjc_tool():
    spec = importlib.util.spec_from_file_location("prepare_hkjc_race_detail_candidates_fixture", HKJC_TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


RESULTS_ALL_URL = "https://racing.hkjc.com/zh-hk/local/information/resultsall?racedate=2025%2F12%2F14&Racecourse=ST"
LOCAL_URL = "https://racing.hkjc.com/zh-hk/local/information/localresults?racedate=2025%2F12%2F14&Racecourse=ST&RaceNo=7"


def _results_all_html(*, with_cup=True, grade_prefix="一級賽") -> str:
    cup_rows = "".join(
        f"<tr><td>{pos}</td><td>{num}</td><td>{horse}</td><td>骑师</td><td>练马师</td><td>126</td><td>3</td></tr>"
        for pos, num, horse in (("1", "4", "浪漫勇士"), ("2", "6", "遨遊氣泡"), ("WV", "9", "退出马"))
    )
    cup_block = ""
    if with_cup:
        cup_block = (
            '<div class="race_result"><div class="f_fs13 margin_top15">'
            f'一級賽 - 2000米 - 草地 - "A" 賽道 - 第7場 - 浪琴香港盃 全方位賽事重溫'
            f'<table class="result"><tr><th>名次</th></tr>{cup_rows}</table>'
            "</div></div>"
        )
    return f"<html><body>{cup_block}</body></html>"


def _localresults_html() -> str:
    header = (
        "<tr><th>名次</th><th>馬號</th><th>馬名</th><th>騎師</th><th>練馬師</th>"
        "<th>實際負磅</th><th>體重</th><th>檔位</th><th>頭馬距離</th><th>沿途走位</th><th>完成 時間</th><th>獨贏賠率</th></tr>"
    )
    row1 = "<tr>" + "".join(
        f"<td>{cell}</td>"
        for cell in ("1", "4", "浪漫勇士", "麥道朗", "沈集成", "126", "1100", "3", "", "1-1", "2:00.00", "2.1")
    ) + "</tr>"
    row2 = "<tr>" + "".join(
        f"<td>{cell}</td>"
        for cell in ("2", "6", "遨遊氣泡", "潘頓", "姚本輝", "126", "1150", "5", "1/2", "2-2", "2:00.10", "3.0")
    ) + "</tr>"
    row_wv = "<tr>" + "".join(
        f"<td>{cell}</td>"
        for cell in ("WV", "9", "退出马", "—", "—", "", "", "", "", "", "", "")
    ) + "</tr>"
    return f"<html><body><table>{header}{row1}{row2}{row_wv}</table></body></html>"


def _targets_csv(path: Path, rows: list[dict]) -> Path:
    header = "target_id,original_name,normalized_grade,local_date,racecourse,match_title_hant"
    lines = [header]
    for row in rows:
        lines.append(
            ",".join(
                str(row.get(key, ""))
                for key in ("target_id", "original_name", "normalized_grade", "local_date", "racecourse", "match_title_hant")
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _seed_cache(module, output_dir: Path, *, results_all_html=None, local_html=None):
    hkjc = _load_hkjc_tool()
    cache_dir = output_dir / "sources"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if results_all_html is not None:
        (cache_dir / hkjc._source_filename(RESULTS_ALL_URL)).write_text(results_all_html, encoding="utf-8")
    if local_html is not None:
        (cache_dir / hkjc._source_filename(LOCAL_URL)).write_text(local_html, encoding="utf-8")


def _args(targets_csv: Path, output_dir: Path, **overrides):
    base = dict(
        targets_csv=str(targets_csv),
        output_dir=str(output_dir),
        allow_network=False,
        limit=0,
        timeout_seconds=5,
        binding_json="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class HkjcSeasonGapCandidatesTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_tool()

    def test_real_title_prefix_matched_and_candidate_uses_importer_module_shape(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = _targets_csv(
                root / "targets.csv",
                [
                    {
                        "target_id": "49460",
                        "original_name": "Hong Kong Cup [LONGINES]",
                        "normalized_grade": "G1",
                        "local_date": "2025-12-14",
                        "racecourse": "Sha Tin",
                        "match_title_hant": "浪琴香港盃",
                    }
                ],
            )
            out = root / "out"
            _seed_cache(module, out, results_all_html=_results_all_html(), local_html=_localresults_html())

            summary = module.prepare_gap_candidates(_args(targets, out))

            self.assertEqual(summary["events_prepared"], 1)
            candidate = json.loads(
                (out / "hkjc_gap_detail_candidates.jsonl").read_text(encoding="utf-8").strip()
            )
            self.assertEqual(candidate["target_id"], 49460)
            self.assertEqual(candidate["source_name"], "hkjc_results_all_zh_hk")
            self.assertEqual(candidate["source_url"], LOCAL_URL)
            # 导入器契约：模块为 {"items": [...], "is_complete": True} 包装
            runners = candidate["modules"]["runners"]
            results = candidate["modules"]["results"]
            self.assertTrue(runners["is_complete"])
            self.assertTrue(results["is_complete"])
            self.assertEqual(len(runners["items"]), 3)
            self.assertEqual(len(results["items"]), 2)
            self.assertEqual(results["items"][0]["horse_name"], "浪漫勇士")
            self.assertEqual(results["items"][0]["finish_position"], 1)
            withdrawn = [r for r in runners["items"] if r["horse_number"] == "9"]
            self.assertEqual(withdrawn[0]["running_status"], "withdrawn")
            self.assertTrue(all(len(page["sha256"]) == 64 for page in candidate["evidence"]["pages"]))
            # 真实标题前缀提供的赛道/距离/等级证据
            self.assertEqual(candidate["evidence"]["grade_hint"], "G1")
            self.assertEqual(candidate["evidence"]["distance_text"], "2000米")

            updates = (out / "target_updates.csv").read_text(encoding="utf-8")
            self.assertIn("49460", updates)
            self.assertIn("2025-12-14", updates)

    def test_grade_hint_mismatch_is_rejected(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = _targets_csv(
                root / "targets.csv",
                [
                    {
                        "target_id": "49460",
                        "original_name": "Hong Kong Cup [LONGINES]",
                        "normalized_grade": "G2",
                        "local_date": "2025-12-14",
                        "racecourse": "Sha Tin",
                        "match_title_hant": "浪琴香港盃",
                    }
                ],
            )
            out = root / "out"
            _seed_cache(module, out, results_all_html=_results_all_html(grade_prefix="一級賽"), local_html=_localresults_html())

            summary = module.prepare_gap_candidates(_args(targets, out))

            self.assertEqual(summary["events_prepared"], 0)
            self.assertEqual(summary["errors"][0]["reason"], "grade_mismatch")
            self.assertFalse((out / "hkjc_gap_detail_candidates.jsonl").exists())

    def test_name_mismatch_lists_available_titles_and_review_csv_records_failure(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = _targets_csv(
                root / "targets.csv",
                [
                    {
                        "target_id": "49460",
                        "original_name": "Hong Kong Cup [LONGINES]",
                        "normalized_grade": "G1",
                        "local_date": "2025-12-14",
                        "racecourse": "Sha Tin",
                        "match_title_hant": "不存在的赛事",
                    }
                ],
            )
            out = root / "out"
            _seed_cache(module, out, results_all_html=_results_all_html(), local_html=_localresults_html())

            summary = module.prepare_gap_candidates(_args(targets, out))

            self.assertEqual(summary["events_prepared"], 0)
            self.assertEqual(summary["errors"][0]["reason"], "race_title_not_matched")
            self.assertIn("浪琴香港盃", "".join(summary["errors"][0]["available_titles"]))
            review = (out / "hkjc_gap_review.csv").read_text(encoding="utf-8-sig")
            self.assertIn("49460", review)
            self.assertIn("race_title_not_matched", review)

    def test_shared_race_day_page_is_fetched_once(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = _targets_csv(
                root / "targets.csv",
                [
                    {
                        "target_id": "49460",
                        "original_name": "Hong Kong Cup [LONGINES]",
                        "normalized_grade": "G1",
                        "local_date": "2025-12-14",
                        "racecourse": "Sha Tin",
                        "match_title_hant": "浪琴香港盃",
                    },
                    {
                        "target_id": "49462",
                        "original_name": "Hong Kong Mile [LONGINES]",
                        "normalized_grade": "G1",
                        "local_date": "2025-12-14",
                        "racecourse": "Sha Tin",
                        "match_title_hant": "浪琴香港一哩錦標",
                    },
                ],
            )
            out = root / "out"
            _seed_cache(module, out, results_all_html=_results_all_html(), local_html=_localresults_html())

            summary = module.prepare_gap_candidates(_args(targets, out))

            self.assertEqual(summary["events_prepared"], 1)
            self.assertEqual(len(summary["errors"]), 1)
            self.assertEqual(summary["errors"][0]["target_id"], "49462")
            self.assertEqual(summary["errors"][0]["reason"], "race_title_not_matched")
            self.assertEqual(summary["source_pages"], 2)

    def test_missing_cache_without_network_fails_closed(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = _targets_csv(
                root / "targets.csv",
                [
                    {
                        "target_id": "49460",
                        "original_name": "Hong Kong Cup [LONGINES]",
                        "normalized_grade": "G1",
                        "local_date": "2025-12-14",
                        "racecourse": "Sha Tin",
                        "match_title_hant": "浪琴香港盃",
                    }
                ],
            )
            out = root / "out"

            summary = module.prepare_gap_candidates(_args(targets, out))

            self.assertEqual(summary["events_prepared"], 0)
            self.assertEqual(summary["errors"][0]["reason"], "source_fetch_failed")
            self.assertFalse((out / "hkjc_gap_detail_candidates.jsonl").exists())

    def test_empty_day_page_fails_closed(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = _targets_csv(
                root / "targets.csv",
                [
                    {
                        "target_id": "49460",
                        "original_name": "Hong Kong Cup [LONGINES]",
                        "normalized_grade": "G1",
                        "local_date": "2025-12-14",
                        "racecourse": "Sha Tin",
                        "match_title_hant": "浪琴香港盃",
                    }
                ],
            )
            out = root / "out"
            _seed_cache(module, out, results_all_html="<html><body>no races</body></html>")

            summary = module.prepare_gap_candidates(_args(targets, out))

            self.assertEqual(summary["events_prepared"], 0)
            self.assertEqual(summary["errors"][0]["reason"], "source_parse_failed")

    def test_binding_produces_final_import_jsonl_with_required_fields(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = _targets_csv(
                root / "targets.csv",
                [
                    {
                        "target_id": "49460",
                        "original_name": "Hong Kong Cup [LONGINES]",
                        "normalized_grade": "G1",
                        "local_date": "2025-12-14",
                        "racecourse": "Sha Tin",
                        "match_title_hant": "浪琴香港盃",
                    }
                ],
            )
            out = root / "out"
            _seed_cache(module, out, results_all_html=_results_all_html(), local_html=_localresults_html())
            module.prepare_gap_candidates(_args(targets, out))

            binding = root / "binding.json"
            binding.write_text(
                json.dumps({"49460": {"target_sha256": "a" * 64, "inventory_artifact_sha256": "b" * 64}}),
                encoding="utf-8",
            )
            bound_path = module.bind_candidates(out, binding)

            rows = [
                json.loads(line)
                for line in bound_path.read_text(encoding="utf-8").strip().splitlines()
            ]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["target_id"], 49460)
            self.assertEqual(row["target_sha256"], "a" * 64)
            self.assertEqual(row["inventory_artifact_sha256"], "b" * 64)
            self.assertEqual(row["source_name"], "hkjc_results_all_zh_hk")
            self.assertIn("runners", row["modules"])
            self.assertIn("results", row["modules"])

    def test_handicap_suffix_and_rating_band_are_tolerated(self):
        module = self.module
        self.assertEqual(module._clean_day_title('三級賽 - 1400米 - 草地 - "C+3" 賽道 - 慶典盃（讓賽）')["title"], "慶典盃")
        self.assertEqual(
            module._clean_day_title('三級賽 - 1000米 - 草地 - "A+3" 賽道 - 國慶盃（讓賽）')["grade_hint"],
            "G3",
        )
        # 班次+评分段前缀也剥除
        self.assertEqual(
            module._clean_day_title('第四班 - 1200米 - (60-40) - 草地 - "C+3" 賽道 - 伯勞讓賽')["title"],
            "伯勞讓賽",
        )

    def test_binding_refuses_unknown_target(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets = _targets_csv(
                root / "targets.csv",
                [
                    {
                        "target_id": "49460",
                        "original_name": "Hong Kong Cup [LONGINES]",
                        "normalized_grade": "G1",
                        "local_date": "2025-12-14",
                        "racecourse": "Sha Tin",
                        "match_title_hant": "浪琴香港盃",
                    }
                ],
            )
            out = root / "out"
            _seed_cache(module, out, results_all_html=_results_all_html(), local_html=_localresults_html())
            module.prepare_gap_candidates(_args(targets, out))
            binding = root / "binding.json"
            binding.write_text(json.dumps({"99999": {"target_sha256": "a" * 64, "inventory_artifact_sha256": "b" * 64}}), encoding="utf-8")

            with self.assertRaises(ValueError):
                module.bind_candidates(out, binding)

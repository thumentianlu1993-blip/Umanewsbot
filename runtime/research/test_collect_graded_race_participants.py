#!/usr/bin/env python3
"""单年度分级赛全部参赛马 collector 的离线合同测试。

这些测试有意先于新 collector 落地。目标模块不存在时，每个测试都以明确 assertion failure
报告同一个实现阻塞；不会把 ImportError、第三方依赖缺失或错误 fixture 伪装成 RED。
"""

from __future__ import annotations

import importlib.util
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from unittest import mock


SCRIPT_PATH = Path(__file__).with_name("collect_graded_race_participants.py")
WORKFLOW_PATH = (
    Path(__file__).parents[2]
    / ".github"
    / "workflows"
    / "research_graded_race_participants.yml"
)
EIGHT_REGIONS = {
    "日本": ("japan", "japan"),
    "中国香港": ("hong_kong", "hong_kong"),
    "美国": ("united_states", "united_states"),
    "英国": ("united_kingdom", "united_kingdom"),
    "法国": ("france", "france"),
    "澳大利亚": ("australia", "australia"),
    "德国": ("germany", "germany"),
    "中东": ("middle_east", None),
}


def load_collector(testcase: unittest.TestCase):
    """加载目标入口；入口缺失时产生真实、可解释的 assertion RED。"""

    testcase.assertTrue(
        SCRIPT_PATH.is_file(),
        "目标入口 runtime/research/collect_graded_race_participants.py 尚不存在",
    )
    spec = importlib.util.spec_from_file_location("graded_race_participants", SCRIPT_PATH)
    testcase.assertIsNotNone(spec)
    testcase.assertIsNotNone(spec.loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def finished_rows(count: int = 12) -> list[dict[str, str]]:
    return [
        {
            "raw_finish_status": str(index),
            "horse_number": str(index),
            "horse_display_name": f"赛驹{index}",
            "profile_url": f"https://umafans.run/horses/{index}/",
        }
        for index in range(1, count + 1)
    ]


def current_race_template_html(
    *,
    region: str = "英国",
    rows: list[tuple[str, str, str]] | None = None,
    result_phase: str | None = None,
    result_heading: str = "正式赛果",
    conflict_status: str = "",
) -> str:
    result_rows = rows or [("1", "1", "Test Horse")]
    rendered = "".join(
        f"""
        <tr>
          <td>{status}</td><td class="num">{number}</td>
          <td><strong>{name}</strong></td><td>Jockey</td><td>Trainer</td>
          <td class="num">1:35.0</td><td>-</td><td>3.0 / 1</td>
        </tr>
        """
        for status, number, name in result_rows
    )
    phase_status = (
        f"""
        <aside class="race-result-status race-result-status-{result_phase}"
               data-conflict-status="{conflict_status}"
               role="status" aria-label="赛果发布状态">
          <strong>{
              "赛果待复核"
              if conflict_status == "pending"
              else "暂定赛果"
              if result_phase == "provisional"
              else "正式赛果"
          }</strong>
          {
              "<span>不同来源的赛果存在差异，正在复核</span>"
              if conflict_status == "pending"
              else ""
          }
        </aside>
        """
        if result_phase
        else ""
    )
    return f"""
    <main class="race-page">
      <span class="race-hero-meta-text">{region} · Ascot · 草地1600米</span>
      <h1 class="race-hero-name">测试锦标</h1>
      <p class="race-hero-original">Test Stakes · 2025-06-01</p>
      <section id="overview"><div class="race-meta-grid">
        <div><span>日期</span><b>2025-06-01</b></div>
        <div><span>等级</span><b>G1</b></div>
        <div><span>马场</span><b>Ascot</b></div>
        <div><span>状态</span><b>已完赛</b></div>
      </div></section>
      {phase_status}
      <section class="panel" id="results">
        <h2>{result_heading}</h2><div class="race-table-wrap">
          <table class="data-table">
            <thead><tr><th>名次</th><th>马号</th><th>马名</th><th>骑师</th>
              <th>练马师</th><th>时间</th><th>差距</th><th>赔率 / 人气</th></tr></thead>
            <tbody>{rendered}</tbody>
          </table>
        </div>
      </section>
    </main>
    """


def horse_search_page(
    cards: list[tuple[str, str, str, str]],
    *,
    next_href: str = "",
) -> str:
    rendered = "".join(
        f"""
        <article class="horse-card">
          <div class="horse-card-top"><span class="region-label">{region}</span></div>
          <h2 class="horse-card-name"><a href="{path}">{display}</a></h2>
          <p class="horse-card-original">{original}</p>
        </article>
        """
        for display, original, region, path in cards
    )
    pagination = (
        f'<nav class="pagination"><a href="{next_href}">下一页</a></nav>'
        if next_href
        else ""
    )
    return f'<main class="horse-list-page">{rendered}{pagination}</main>'


def current_horse_search_html(
    *,
    display_name: str,
    original_name: str,
    region_label: str,
    profile_path: str = "/horses/42/",
) -> str:
    return f"""
    <main class="horse-list-page">
      <article class="horse-card">
        <div class="horse-card-top"><span class="region-mark"></span>
          <span class="region-label">{region_label}</span></div>
        <h2 class="horse-card-name"><a href="{profile_path}">{display_name}</a></h2>
        <p class="horse-card-original">{original_name}</p>
      </article>
    </main>
    """


def profile_search_url(query: str) -> str:
    return f"https://umafans.run/horses/?{urlencode({'q': query})}"


def current_horse_detail_html(
    *,
    display_name: str,
    original_name: str,
    region_label: str,
    country: str,
    birth_year: int,
) -> str:
    return f"""
    <main class="horse-page">
      <section class="horse-hero">
        <span class="horse-hero-kicker">{region_label} · 基础资料完整</span>
        <h1 class="horse-hero-name">{display_name}</h1>
        <p class="horse-hero-original">{original_name} · {birth_year} 年生 · 枣 · 牡</p>
      </section>
      <section class="panel"><h2>基础资料</h2><div class="race-meta-grid">
        <div><span>国家/地区</span><b>{country}</b></div>
      </div></section>
    </main>
    """


class FakeResponse:
    def __init__(self, content: str | bytes, url: str, status_code: int = 200):
        self.content = content.encode() if isinstance(content, str) else content
        self.url = url
        self.status_code = status_code


class RouteClient:
    routes: dict[str, str | bytes] = {}
    calls: list[str] = []

    def __init__(self, **kwargs):
        self.request_count = kwargs.get("request_count_start", 0)
        self.request_reserver = kwargs.get("request_reserver")

    def get(self, url, *, params=None):
        key = f"{url}?{urlencode(params)}" if params else url
        if self.request_reserver:
            self.request_count = self.request_reserver()
        else:
            self.request_count += 1
        type(self).calls.append(key)
        if key not in type(self).routes:
            raise AssertionError(f"unexpected fake request: {key} params={params}")
        return FakeResponse(type(self).routes[key], key)


class YearAndRegionContractTests(unittest.TestCase):
    def test_year_is_required_and_only_one_natural_year_is_accepted(self):
        collector = load_collector(self)

        with self.assertRaises(SystemExit):
            collector.parse_args(["--stage", "races", "--output-dir", "unused"])
        self.assertEqual(collector.validate_year("1984", current_utc_year=2026), 1984)
        self.assertEqual(collector.validate_year("2026", current_utc_year=2026), 2026)
        for value in ("1983", "2027", "2025,2026", "2025-2026", "not-a-year"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                collector.validate_year(value, current_utc_year=2026)

    def test_direct_labels_cover_all_eight_regions_and_aliases(self):
        collector = load_collector(self)

        for label, expected in EIGHT_REGIONS.items():
            with self.subTest(label=label):
                self.assertEqual(collector.normalize_region_label(label), expected)
        self.assertEqual(
            collector.normalize_region_label("香港"), ("hong_kong", "hong_kong")
        )
        self.assertEqual(
            collector.normalize_region_label("澳洲"), ("australia", "australia")
        )
        for label, country in {
            "阿联酋": "united_arab_emirates",
            "沙特": "saudi_arabia",
            "卡塔尔": "qatar",
            "巴林": "bahrain",
        }.items():
            with self.subTest(label=label):
                self.assertEqual(
                    collector.normalize_region_label(label), ("middle_east", country)
                )

    def test_incomplete_other_manifest_reports_classification_incomplete(self):
        collector = load_collector(self)
        urls = {
            "https://umafans.run/races/2025/a/",
            "https://umafans.run/races/2025/b/",
        }
        manifest = {
            "schema_version": 1,
            "year": 2025,
            "classification_complete": False,
            "races": [
                {
                    "url": "https://umafans.run/races/2025/a/",
                    "region": "australia",
                    "country": "australia",
                    "evidence": "reviewed race identity",
                }
            ],
        }

        result = collector.classify_other_coverage(
            year=2025, discovered_other_urls=urls, manifest=manifest
        )
        self.assertEqual(result["coverage_status"], "classification_incomplete")
        self.assertEqual(result["classified_other_urls"], 1)
        self.assertEqual(result["unclassified_other_urls"], 1)
        self.assertTrue(result["unclassified_other_url_digest"])

    def test_complete_other_manifest_requires_exact_url_coverage(self):
        collector = load_collector(self)
        urls = {
            "https://umafans.run/races/2025/a/",
            "https://umafans.run/races/2025/b/",
        }
        complete = {
            "schema_version": 1,
            "year": 2025,
            "classification_complete": True,
            "races": [
                {
                    "url": url,
                    "region": "out_of_scope",
                    "country": "other",
                    "evidence": "reviewed out-of-scope identity",
                }
                for url in sorted(urls)
            ],
        }

        result = collector.classify_other_coverage(
            year=2025, discovered_other_urls=urls, manifest=complete
        )
        self.assertEqual(result["coverage_status"], "no_public_in_scope_races")
        self.assertEqual(result["unclassified_other_urls"], 0)

        missing = {**complete, "races": complete["races"][:-1]}
        with self.assertRaisesRegex(ValueError, "coverage|manifest|URL"):
            collector.classify_other_coverage(
                year=2025, discovered_other_urls=urls, manifest=missing
            )


class ParticipantContractTests(unittest.TestCase):
    def test_all_twelve_actual_starters_are_preserved_not_top_five(self):
        collector = load_collector(self)

        parsed = collector.parse_result_rows(finished_rows())
        self.assertEqual(len(parsed["occurrences"]), 12)
        self.assertEqual(
            [row["normalized_finish_position"] for row in parsed["occurrences"]],
            list(range(1, 13)),
        )
        self.assertEqual(parsed["non_starters_excluded"], 0)
        self.assertEqual(parsed["participant_status_unresolved"], 0)

    def test_non_starters_and_unknown_status_fail_closed(self):
        collector = load_collector(self)
        rows = finished_rows(2) + [
            {
                "raw_finish_status": "SCR",
                "horse_number": "3",
                "horse_display_name": "退赛马",
                "profile_url": "",
            },
            {
                "raw_finish_status": "MYSTERY",
                "horse_number": "4",
                "horse_display_name": "未知马",
                "profile_url": "",
            },
            {
                "raw_finish_status": "PU",
                "horse_number": "5",
                "horse_display_name": "拉停马",
                "profile_url": "",
            },
        ]

        parsed = collector.parse_result_rows(rows)
        self.assertEqual(
            [row["horse_display_name"] for row in parsed["occurrences"]],
            ["赛驹1", "赛驹2", "拉停马"],
        )
        self.assertEqual(parsed["occurrences"][-1]["participant_status"], "started_non_finish")
        self.assertEqual(parsed["non_starters_excluded"], 1)
        self.assertEqual(parsed["participant_status_unresolved"], 1)
        self.assertEqual(parsed["unresolved_rows"][0]["raw_finish_status"], "MYSTERY")
        self.assertIsNone(
            parsed["unresolved_rows"][0].get("normalized_finish_position")
        )

    def test_all_controlled_non_finish_and_disqualification_codes_are_kept(self):
        collector = load_collector(self)
        rows = [
            {
                "raw_finish_status": status,
                "horse_number": str(index),
                "horse_display_name": f"Horse {index}",
                "profile_url": "",
            }
            for index, status in enumerate(
                ("DNF", "PU", "F", "UR", "RO", "BD", "DSQ"), start=1
            )
        ]
        parsed = collector.parse_result_rows(rows)
        self.assertEqual(len(parsed["occurrences"]), 7)
        self.assertEqual(
            [row["participant_status"] for row in parsed["occurrences"]],
            ["started_non_finish"] * 6 + ["disqualified_after_start"],
        )
        self.assertEqual(parsed["participant_status_unresolved"], 0)
        self.assertEqual(parsed["non_starters_excluded"], 0)

    def test_real_html_parser_preserves_ties_and_controlled_non_finishes(self):
        collector = load_collector(self)
        html = """
        <main class="race-page">
          <div class="race-hero-meta-text">英国 · 平地</div>
          <h1 class="race-hero-name">测试锦标</h1>
          <div class="race-hero-original">Test Stakes · 2025-06-01</div>
          <section id="overview"><div class="race-meta-grid">
            <div><span>日期</span><b>2025-06-01</b></div>
            <div><span>等级</span><b>Group I</b></div>
            <div><span>马场</span><b>Ascot</b></div>
            <div><span>状态</span><b>已完赛</b></div>
          </div></section>
          <section id="results"><h2>正式赛果</h2><table>
            <thead><tr><th>名次</th><th>马号</th><th>马名</th><th>骑师</th>
              <th>练马师</th><th>时间</th><th>差距</th></tr></thead>
            <tbody>
              <tr><td>1</td><td>1</td><td><a href="/horses/1/">Alpha</a></td><td>A</td><td>T</td><td>1:35</td><td></td></tr>
              <tr><td>1</td><td>2</td><td><a href="/horses/2/">Beta</a></td><td>B</td><td>T</td><td>1:35</td><td>同着</td></tr>
              <tr><td>DNF</td><td>3</td><td>Gamma</td><td>C</td><td>T</td><td></td><td></td></tr>
              <tr><td>DSQ</td><td>4</td><td>Delta</td><td>D</td><td>T</td><td></td><td></td></tr>
              <tr><td>SCR</td><td>5</td><td>Epsilon</td><td>E</td><td>T</td><td></td><td></td></tr>
              <tr><td>MYSTERY</td><td>6</td><td>Zeta</td><td>F</td><td>T</td><td></td><td></td></tr>
            </tbody>
          </table></section>
        </main>
        """

        parsed = collector.parse_race_html(
            html,
            url="https://umafans.run/races/2025/test-stakes/",
            year=2025,
            fetched_at="2025-06-02T00:00:00+00:00",
        )

        self.assertEqual(len(parsed["rows"]), 4)
        self.assertEqual(
            [row["normalized_finish_position"] for row in parsed["rows"][:2]],
            [1, 1],
        )
        self.assertEqual(
            [row["participant_status"] for row in parsed["rows"][2:]],
            ["started_non_finish", "disqualified_after_start"],
        )
        self.assertEqual(parsed["non_starters_excluded"], 1)
        self.assertEqual(parsed["participant_status_unresolved"], 1)

    def test_grade_policy_accepts_japan_extensions_and_global_roman_forms(self):
        collector = load_collector(self)
        for raw in ("G1", "GⅡ", "J-G3", "JpnⅡ"):
            with self.subTest(raw=raw):
                self.assertTrue(collector.grade_is_in_scope("japan", raw))
        for raw in ("Group I", "Grade II", "GⅢ"):
            with self.subTest(raw=raw):
                self.assertTrue(collector.grade_is_in_scope("france", raw))
        self.assertFalse(collector.grade_is_in_scope("france", "Listed"))


class HorseNameContractTests(unittest.TestCase):
    def test_name_states_are_orthogonal_and_issue_codes_are_composable(self):
        collector = load_collector(self)
        occurrence = {
            "region": "united_states",
            "country": "united_states",
            "horse_display_name": "Example Horse",
            "profile_url": "https://umafans.run/horses/100/",
        }
        record = collector.build_horse_name_record(
            [occurrence],
            profile={
                "resolution_state": "resolved",
                "name_zh": "",
                "name_ja": "",
                "name_en": "Example Horse",
            },
        )

        self.assertEqual(record["profile_resolution_state"], "resolved")
        self.assertEqual(record["required_english_status"], "complete")
        self.assertEqual(record["name_completeness"], "partial")
        self.assertIn("missing_chinese", record["name_issue_codes"])
        self.assertNotIn("missing_required_english", record["name_issue_codes"])

        missing_both = collector.build_horse_name_record(
            [{**occurrence, "profile_url": ""}],
            profile={
                "resolution_state": "not_found",
                "name_zh": "",
                "name_ja": "",
                "name_en": "",
            },
        )
        self.assertEqual(missing_both["required_english_status"], "missing")
        self.assertEqual(
            set(missing_both["name_issue_codes"]),
            {
                "missing_chinese",
                "missing_japanese",
                "missing_required_english",
                "profile_not_found",
            },
        )

    def test_generic_other_unique_name_is_unresolved_without_identity_fact(self):
        collector = load_collector(self)
        occurrence = {
            "region": "australia",
            "country": "australia",
            "horse_display_name": "Southern Star",
            "original_name": "Southern Star",
            "birth_year": None,
            "profile_url": "",
        }
        candidates = [
            {
                "profile_url": "https://umafans.run/horses/200/",
                "racing_region": "other",
                "display_name": "Southern Star",
                "original_name": "Southern Star",
                "birth_year": None,
                "country": None,
            }
        ]

        result = collector.resolve_other_profile(occurrence, candidates)
        self.assertEqual(result["resolution_state"], "unresolved")
        self.assertIsNone(result.get("profile_url"))


class OutputAndResumeContractTests(unittest.TestCase):
    def test_new_entry_has_no_wikipedia_or_wikidata_surface(self):
        collector = load_collector(self)
        source = SCRIPT_PATH.read_text(encoding="utf-8").lower()

        self.assertEqual(set(collector.ALLOWED_HOSTS), {"umafans.run", "www.umafans.run"})
        self.assertTrue(
            set(collector.STAGES).isdisjoint(
                {
                    "wikidata_search",
                    "wikidata_entities",
                    "score_horses",
                }
            )
        )
        public_symbols = {name.lower() for name in vars(collector)}
        for forbidden_symbol in (
            "wikidataresolver",
            "wikimedia_hosts",
            "wikipedia_hosts",
        ):
            with self.subTest(forbidden_symbol=forbidden_symbol):
                self.assertNotIn(forbidden_symbol, public_symbols)
        for forbidden_source in (
            ".wikipedia.org",
            "wikidata.org",
            "race_top5_",
            "horse_wikipedia_mapping_",
            "wikipedia_review_queue_",
        ):
            with self.subTest(forbidden_source=forbidden_source):
                self.assertNotIn(forbidden_source, source)

    def test_final_directory_contract_is_exactly_seven_files(self):
        collector = load_collector(self)

        self.assertEqual(
            set(collector.final_filenames(2025)),
            {
                "race_participants_2025.csv",
                "horse_names_2025.csv",
                "horse_name_review_queue_2025.csv",
                "source_manifest.jsonl",
                "summary.json",
                "errors.json",
                "README.md",
            },
        )

    def test_resume_rejects_year_drift(self):
        collector = load_collector(self)
        saved = {
            "year": 2025,
            "region_manifest_sha256": "region-a",
            "manifest_sha256": "manifest-a",
            "tool_sha256": "tool-a",
            "checkpoint_sha256": "checkpoint-a",
        }
        with self.assertRaisesRegex(ValueError, "year"):
            collector.validate_resume_identity(saved, {**saved, "year": 2026})

    def test_resume_rejects_region_manifest_and_run_manifest_drift(self):
        collector = load_collector(self)
        saved = {
            "year": 2025,
            "region_manifest_sha256": "region-a",
            "manifest_sha256": "manifest-a",
            "tool_sha256": "tool-a",
            "checkpoint_sha256": "checkpoint-a",
        }
        for field in ("region_manifest_sha256", "manifest_sha256"):
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "manifest"
            ):
                collector.validate_resume_identity(saved, {**saved, field: "drifted"})

    def test_resume_rejects_tool_and_checkpoint_drift(self):
        collector = load_collector(self)
        saved = {
            "year": 2025,
            "region_manifest_sha256": "region-a",
            "manifest_sha256": "manifest-a",
            "tool_sha256": "tool-a",
            "checkpoint_sha256": "checkpoint-a",
        }
        for field, message in (
            ("tool_sha256", "tool"),
            ("checkpoint_sha256", "checkpoint"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                collector.validate_resume_identity(saved, {**saved, field: "drifted"})

    def test_region_manifest_loader_rejects_symlink_and_outside_worktree(self):
        collector = load_collector(self)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            outside = root.parent / f"{root.name}-outside.json"
            outside.write_text("{}", encoding="utf-8")
            link = root / "manifest.json"
            link.symlink_to(outside)
            try:
                with self.assertRaisesRegex(ValueError, "symlink|worktree|regular"):
                    collector.load_region_manifest(
                        link, year=2025, worktree_root=root
                    )
                with self.assertRaisesRegex(ValueError, "worktree"):
                    collector.load_region_manifest(
                        outside, year=2025, worktree_root=root
                    )
            finally:
                outside.unlink(missing_ok=True)

    def test_profile_four_shard_coverage_and_fan_in_are_exact(self):
        collector = load_collector(self)
        records = []
        expected = set()
        shard_owners = set()
        for index in range(12):
            key = f"name|france|france|horse{index}"
            expected.add(key)
            shard_owners.add(collector.stable_shard(key, 4))
            records.append(
                {
                    "key": key,
                    "lookup_keys": [key],
                    "profile_url": "",
                    "resolution_state": "not_found",
                    "name_zh": "",
                    "name_ja": "",
                    "name_en": f"Horse {index}",
                    "status": "not_found",
                }
            )
        self.assertTrue(shard_owners <= {0, 1, 2, 3})
        merged = collector.merge_profile_records(records, expected)
        self.assertEqual({row["key"] for row in merged}, expected)
        with self.assertRaisesRegex(ValueError, "coverage"):
            collector.merge_profile_records(records[:-1], expected)

    def test_finalize_content_invariants_and_exact_files(self):
        collector = load_collector(self)
        occurrence = {
            "region": "united_kingdom",
            "region_label": "英国",
            "country": "united_kingdom",
            "race_date": "2025-06-01",
            "race_name_zh": "测试锦标",
            "grade": "G1",
            "raw_finish_status": "1",
            "normalized_finish_position": 1,
            "participant_status": "finished",
            "horse_number": "1",
            "horse_display_name": "Test Horse",
            "original_name": "Test Horse",
            "profile_url": "https://umafans.run/horses/1/",
            "race_url": "https://umafans.run/races/2025/test/",
            "race_page_sha256": "a" * 64,
        }
        lookup = collector.canonical_horse_key(occurrence)
        profiles = [
            {
                "key": lookup,
                "lookup_keys": [lookup],
                "profile_url": occurrence["profile_url"],
                "resolution_state": "resolved",
                "name_zh": "",
                "name_ja": "",
                "name_en": "Test Horse",
                "status": "success",
            }
        ]
        with tempfile.TemporaryDirectory() as raw:
            final = Path(raw) / "final"
            summary = collector.finalize_artifacts(
                output_dir=final,
                year=2025,
                occurrences=[occurrence],
                profiles=profiles,
                source_manifest=[
                    {
                        "url": occurrence["race_url"],
                        "non_starters_excluded": 0,
                        "participant_status_unresolved": 0,
                    }
                ],
                errors=[],
                other_coverage=collector.classify_other_coverage(
                    year=2025, discovered_other_urls=[], manifest=None
                ),
                request_count=2,
                generated_at="2025-01-01T00:00:00+00:00",
            )
            self.assertEqual(
                {path.name for path in final.iterdir()},
                set(collector.final_filenames(2025)),
            )
            self.assertEqual(summary["counts"]["participant_rows"], 1)
            self.assertEqual(summary["counts"]["unique_horses"], 1)
            self.assertEqual(summary["counts"]["required_english_complete"], 1)
            self.assertEqual(summary["counts"]["profile_resolved"], 1)
            review = (final / "horse_name_review_queue_2025.csv").read_text(
                encoding="utf-8-sig"
            )
            self.assertIn("missing_chinese", review)

    def test_safe_stop_resume_is_byte_equivalent_and_deterministic(self):
        collector = load_collector(self)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            stopped = collector.run_synthetic_smoke(
                root, year=2025, stop_after=1
            )
            self.assertTrue(stopped["safe_stopped"])
            self.assertEqual(stopped["exit_code"], 75)
            resumed = collector.run_synthetic_smoke(root, year=2025)
            self.assertTrue(resumed["byte_equivalent"])
            first = {
                path.name: path.read_bytes()
                for path in (root / "final").iterdir()
            }
            repeated = collector.run_synthetic_smoke(root, year=2025)
            self.assertFalse(repeated["safe_stopped"])
            second = {
                path.name: path.read_bytes()
                for path in (root / "final").iterdir()
            }
            self.assertEqual(first, second)
            summary = json.loads((root / "final" / "summary.json").read_text())
            self.assertEqual(summary["counts"]["request_count"], 4)


class ReviewFindingRegressionTests(unittest.TestCase):
    def test_sitemap_xml_types_and_mixed_year_urls_are_not_confused(self):
        collector = load_collector(self)
        root_url = "https://umafans.run/sitemap.xml"
        shard_url = "https://umafans.run/sitemap-races.xml"
        target_race = "https://umafans.run/races/2025/target/"
        other_year = "https://umafans.run/races/2024/old/"
        horse_html = "https://umafans.run/horses/42/"
        routes = {
            root_url: (
                '<?xml version="1.0"?>'
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<sitemap><loc>{shard_url}</loc></sitemap>"
                "</sitemapindex>"
            ),
            shard_url: (
                '<?xml version="1.0"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{target_race}</loc></url>"
                f"<url><loc>{other_year}</loc></url>"
                f"<url><loc>{horse_html}</loc></url>"
                "</urlset>"
            ),
        }

        class Client:
            def __init__(self):
                self.request_count = 0
                self.calls = []

            def get(self, url):
                self.calls.append(url)
                self.request_count += 1
                if url not in routes:
                    raise AssertionError(f"non-sitemap URL fetched: {url}")
                return FakeResponse(routes[url], url)

        client = Client()
        self.assertEqual(
            collector.discover_race_urls(
                client, base_url="https://umafans.run/", year=2025
            ),
            [target_race],
        )
        self.assertEqual(client.calls, [root_url, shard_url])

        invalid_index_client = Client()
        invalid_index_client_routes = {
            root_url: (
                '<?xml version="1.0"?><sitemapindex>'
                f"<sitemap><loc>{target_race}</loc></sitemap>"
                "</sitemapindex>"
            )
        }
        routes.update(invalid_index_client_routes)
        with self.assertRaisesRegex(ValueError, "sitemap|XML"):
            collector.discover_race_urls(
                invalid_index_client,
                base_url="https://umafans.run/",
                year=2025,
            )
        self.assertEqual(invalid_index_client.calls, [root_url])

    def test_other_profile_uses_detail_alias_intersection_with_identity_facts(self):
        collector = load_collector(self)
        occurrence = {
            "region": "australia",
            "country": "australia",
            "horse_display_name": "南方之星",
            "original_name": "",
            "birth_year": "2020",
        }
        valid = {
            "profile_url": "https://umafans.run/horses/42/",
            "display_name": "南方之星",
            "original_name": "Southern Star",
            "name_zh": "南方之星",
            "name_en": "Southern Star",
            "racing_region": "australia",
            "country": "australia",
            "birth_year": "2020",
        }
        self.assertEqual(
            collector.resolve_other_profile(
                occurrence, [valid]
            )["resolution_state"],
            "resolved",
        )
        conflict = {
            **valid,
            "display_name": "另一匹马",
            "name_zh": "另一匹马",
        }
        self.assertNotEqual(
            collector.resolve_other_profile(
                occurrence, [conflict]
            )["resolution_state"],
            "resolved",
        )
        no_fact_occurrence = {
            "region": "australia",
            "country": "",
            "horse_display_name": "南方之星",
            "original_name": "",
            "birth_year": "",
        }
        self.assertNotEqual(
            collector.resolve_other_profile(
                no_fact_occurrence, [valid]
            )["resolution_state"],
            "resolved",
        )

    def test_other_coverage_requires_graded_evidence_not_manifest_region(self):
        collector = load_collector(self)
        listed_url = "https://umafans.run/races/2025/listed/"
        g1_url = "https://umafans.run/races/2025/g1/"
        def manifest_for(*urls):
            return {
                "schema_version": 1,
                "year": 2025,
                "classification_complete": True,
                "races": [
                    {
                        "url": url,
                        "region": "australia",
                        "country": "australia",
                        "evidence": "reviewed race identity",
                    }
                    for url in urls
                ],
            }

        listed_only = collector.classify_other_coverage(
            year=2025,
            discovered_other_urls=[listed_url],
            manifest=manifest_for(listed_url),
            in_scope_urls=[],
        )
        self.assertEqual(
            listed_only["coverage_by_region"]["australia"],
            "no_public_in_scope_races",
        )
        self.assertEqual(
            listed_only["coverage_status"], "no_public_in_scope_races"
        )
        mixed = collector.classify_other_coverage(
            year=2025,
            discovered_other_urls=[listed_url, g1_url],
            manifest=manifest_for(listed_url, g1_url),
            in_scope_urls=[g1_url],
        )
        self.assertEqual(
            mixed["coverage_by_region"]["australia"], "covered"
        )
        self.assertEqual(mixed["coverage_status"], "covered")

    def test_other_profile_birth_fact_rules_match_direct_and_search_paths(self):
        collector = load_collector(self)
        english_search_url = profile_search_url("Southern Star")
        chinese_search_url = profile_search_url("南方之星")
        detail_url = "https://umafans.run/horses/42/"

        def fetch(
            *,
            path,
            region,
            expected_country,
            detail_country,
            detail_birth_year,
        ):
            routes = {
                detail_url: current_horse_detail_html(
                    display_name="南方之星",
                    original_name="Southern Star",
                    region_label="其他",
                    country=detail_country,
                    birth_year=detail_birth_year,
                )
            }
            profile_url = detail_url
            if path == "search":
                routes[english_search_url] = current_horse_search_html(
                    display_name="南方之星",
                    original_name="Southern Star",
                    region_label="其他",
                )
                routes[chinese_search_url] = horse_search_page([])
                profile_url = ""
            RouteClient.routes = routes
            RouteClient.calls = []
            result = collector.fetch_profile(
                RouteClient(),
                base_url="https://umafans.run/",
                occurrences=[
                    {
                        "region": region,
                        "country": expected_country,
                        "horse_display_name": "南方之星",
                        "original_name": "Southern Star",
                        "birth_year": "2020",
                        "profile_url": profile_url,
                    }
                ],
            )
            return result["resolution_state"]

        for path in ("direct", "search"):
            for region, country in (
                ("australia", "australia"),
                ("germany", "germany"),
            ):
                with self.subTest(path=path, region=region, case="birth_match"):
                    self.assertEqual(
                        fetch(
                            path=path,
                            region=region,
                            expected_country=country,
                            detail_country="",
                            detail_birth_year=2020,
                        ),
                        "resolved",
                    )
            with self.subTest(path=path, case="birth_mismatch"):
                self.assertEqual(
                    fetch(
                        path=path,
                        region="australia",
                        expected_country="australia",
                        detail_country="",
                        detail_birth_year=2021,
                    ),
                    "unresolved",
                )
            with self.subTest(path=path, case="country_conflict"):
                self.assertEqual(
                    fetch(
                        path=path,
                        region="australia",
                        expected_country="australia",
                        detail_country="germany",
                        detail_birth_year=2020,
                    ),
                    "ambiguous",
                )
            with self.subTest(path=path, case="middle_east_requires_country"):
                self.assertEqual(
                    fetch(
                        path=path,
                        region="middle_east",
                        expected_country="united_arab_emirates",
                        detail_country="",
                        detail_birth_year=2020,
                    ),
                    "unresolved",
                )

    def test_search_profile_validates_canonical_group_not_representative_only(self):
        collector = load_collector(self)
        english_search_url = profile_search_url("Southern Star")
        chinese_search_url = profile_search_url("南方之星")
        detail_url = "https://umafans.run/horses/42/"
        RouteClient.routes = {
            english_search_url: current_horse_search_html(
                display_name="南方之星",
                original_name="Southern Star",
                region_label="其他",
            ),
            chinese_search_url: horse_search_page([]),
            detail_url: current_horse_detail_html(
                display_name="南方之星",
                original_name="Southern Star",
                region_label="其他",
                country="",
                birth_year=2020,
            ),
        }
        first = {
            "region": "australia",
            "country": "australia",
            "horse_display_name": "南方之星",
            "original_name": "Southern Star",
            "birth_year": "2020",
            "profile_url": "",
        }
        conflicting = {
            **first,
            "horse_display_name": "Southern Star",
            "birth_year": "2021",
        }
        compatible = {
            **first,
            "horse_display_name": "Southern Star",
        }

        for occurrences in (
            [first, conflicting],
            [conflicting, first],
        ):
            with self.subTest(
                order=[item["birth_year"] for item in occurrences],
                case="conflict",
            ):
                RouteClient.calls = []
                result = collector.fetch_profile(
                    RouteClient(),
                    base_url="https://umafans.run/",
                    occurrences=occurrences,
                )
                self.assertNotEqual(result["resolution_state"], "resolved")
                self.assertEqual(len(result["identity_reviews"]), 2)
                self.assertIn(
                    "2021",
                    {
                        review["birth_year"]
                        for review in result["identity_reviews"]
                        if review["review_state"] != "resolved"
                    },
                )
                self.assertEqual(
                    RouteClient.calls,
                    [english_search_url, chinese_search_url, detail_url],
                )

        for occurrences in (
            [first, compatible],
            [compatible, first],
        ):
            with self.subTest(
                order=[
                    item["horse_display_name"] for item in occurrences
                ],
                case="compatible",
            ):
                RouteClient.calls = []
                result = collector.fetch_profile(
                    RouteClient(),
                    base_url="https://umafans.run/",
                    occurrences=occurrences,
                )
                self.assertEqual(result["resolution_state"], "resolved")
                self.assertEqual(
                    RouteClient.calls,
                    [english_search_url, chinese_search_url, detail_url],
                )

    def test_group_alias_queries_are_order_independent_and_transport_sensitive(self):
        collector = load_collector(self)
        search_base = "https://umafans.run/horses/"
        english_query = f"{search_base}?q=Southern+Star"
        chinese_query = f"{search_base}?q=%E5%8D%97%E6%96%B9%E4%B9%8B%E6%98%9F"
        detail_url = "https://umafans.run/horses/42/"

        class ParamsRouteClient:
            routes = {
                english_query: current_horse_search_html(
                    display_name="南方之星",
                    original_name="Southern Star",
                    region_label="其他",
                ),
                chinese_query: horse_search_page([]),
                detail_url: current_horse_detail_html(
                    display_name="南方之星",
                    original_name="Southern Star",
                    region_label="其他",
                    country="",
                    birth_year=2020,
                ),
            }

            def __init__(self):
                self.calls = []
                self.request_count = 0

            def get(self, url, *, params=None):
                key = (
                    f"{url}?{collector.urlencode(params)}"
                    if params
                    else url
                )
                self.calls.append(key)
                self.request_count += 1
                if key not in self.routes:
                    raise AssertionError(f"unexpected request: {key}")
                return FakeResponse(self.routes[key], key)

        chinese = {
            "region": "australia",
            "country": "australia",
            "horse_display_name": "南方之星",
            "original_name": "Southern Star",
            "birth_year": "2020",
            "profile_url": "",
        }
        english = {
            **chinese,
            "horse_display_name": "Southern Star",
        }
        expected_calls = [english_query, chinese_query, detail_url]
        for occurrences in ([chinese, english], [english, chinese]):
            with self.subTest(
                order=[
                    item["horse_display_name"] for item in occurrences
                ]
            ):
                client = ParamsRouteClient()
                result = collector.fetch_profile(
                    client,
                    base_url="https://umafans.run/",
                    occurrences=occurrences,
                )
                self.assertEqual(result["resolution_state"], "resolved")
                self.assertEqual(client.calls, expected_calls)

        class LimitedClient(ParamsRouteClient):
            def __init__(self, *, limit):
                super().__init__()
                self.limit = limit

            def get(self, url, *, params=None):
                if self.request_count >= self.limit:
                    raise collector.RequestBudgetExceeded("budget")
                return super().get(url, params=params)

        with self.assertRaises(collector.RequestBudgetExceeded):
            collector.fetch_profile(
                LimitedClient(limit=1),
                base_url="https://umafans.run/",
                occurrences=[chinese, english],
            )

        clock = [0.0]
        deadline_client = ParamsRouteClient()
        deadline_client.deadline = collector.StageDeadline(
            deadline_at=1.5,
            clock=lambda: clock[0],
            safety_margin=0,
        )
        original_get = deadline_client.get

        def timed_get(url, *, params=None):
            response = original_get(url, params=params)
            clock[0] += 1.0
            return response

        deadline_client.get = timed_get
        with self.assertRaises(collector.StageDeadlineExceeded):
            collector.fetch_profile(
                deadline_client,
                base_url="https://umafans.run/",
                occurrences=[chinese, english],
            )

    def test_profile_conflict_errors_preserve_expected_and_actual_facts(self):
        collector = load_collector(self)
        profile_url = "https://umafans.run/horses/42/"
        profile = {
            "profile_url": profile_url,
            "display_name": "南方之星",
            "original_name": "Southern Star",
            "name_zh": "南方之星",
            "name_en": "Southern Star",
            "racing_region": "australia",
            "country": "australia",
            "birth_year": "2020",
        }
        base = {
            "region": "australia",
            "country": "australia",
            "horse_display_name": "南方之星",
            "original_name": "Southern Star",
            "birth_year": "2020",
            "profile_url": "",
        }
        occurrences = [
            {
                **base,
                "horse_display_name": "另一匹马",
                "original_name": "Other Horse",
            },
            {**base, "region": "germany", "country": "germany"},
            {**base, "country": "germany"},
            {**base, "birth_year": "2021"},
        ]
        result = collector._validate_profile_group(occurrences, profile)
        errors = collector._structured_errors(
            [
                (
                    "profiles",
                    [{"key": "conflict-group", "status": "success", **result}],
                )
            ]
        )
        self.assertEqual(len(errors), 4)
        by_index = {item["occurrence_index"]: item for item in errors}
        expected_fields = {
            0: "name_aliases",
            1: "region",
            2: "country",
            3: "birth_year",
        }
        for index, field in expected_fields.items():
            with self.subTest(index=index, field=field):
                error = by_index[index]
                self.assertIn(field, error["conflict_fields"])
                self.assertTrue(error["reasons"])
                self.assertEqual(error["profile_url"], profile_url)
                self.assertEqual(error["actual_region"], "australia")
                self.assertEqual(error["actual_country"], "australia")
                self.assertEqual(error["actual_birth_year"], "2020")
                self.assertEqual(
                    error["expected_birth_year"],
                    occurrences[index]["birth_year"],
                )
                self.assertEqual(
                    error["expected_aliases"],
                    sorted(collector._profile_aliases(occurrences[index])),
                )
                self.assertEqual(
                    error["actual_aliases"],
                    sorted(collector._profile_aliases(profile)),
                )

        with tempfile.TemporaryDirectory() as raw:
            collector.finalize_artifacts(
                output_dir=Path(raw),
                year=2025,
                occurrences=[],
                profiles=[],
                source_manifest=[],
                errors=errors,
                other_coverage=collector.classify_other_coverage(
                    year=2025,
                    discovered_other_urls=[],
                    manifest=None,
                ),
                request_count=0,
                generated_at="2025-01-01T00:00:00+00:00",
            )
            written = json.loads(
                (Path(raw) / "errors.json").read_text(encoding="utf-8")
            )
            self.assertEqual(written, errors)

    def test_profile_url_canonicalization_deduplicates_search_direct_and_merge(self):
        collector = load_collector(self)
        search_base = "https://umafans.run/horses/"
        english_query = f"{search_base}?q=Southern+Star"
        chinese_query = f"{search_base}?q=%E5%8D%97%E6%96%B9%E4%B9%8B%E6%98%9F"
        canonical_detail = "https://umafans.run/horses/42/"

        class CanonicalRouteClient:
            def __init__(self):
                self.calls = []
                self.request_count = 0

            def get(self, url, *, params=None):
                key = f"{url}?{urlencode(params)}" if params else url
                self.calls.append(key)
                self.request_count += 1
                routes = {
                    english_query: current_horse_search_html(
                        display_name="南方之星",
                        original_name="Southern Star",
                        region_label="其他",
                        profile_path="/horses/42",
                    ),
                    chinese_query: current_horse_search_html(
                        display_name="南方之星",
                        original_name="Southern Star",
                        region_label="其他",
                        profile_path="/horses/42/",
                    ),
                    canonical_detail: current_horse_detail_html(
                        display_name="南方之星",
                        original_name="Southern Star",
                        region_label="其他",
                        country="",
                        birth_year=2020,
                    ),
                }
                if key not in routes:
                    raise AssertionError(key)
                return FakeResponse(routes[key], key)

        occurrences = [
            {
                "region": "australia",
                "country": "australia",
                "horse_display_name": "南方之星",
                "original_name": "Southern Star",
                "birth_year": "2020",
                "profile_url": "",
            }
        ]
        client = CanonicalRouteClient()
        result = collector.fetch_profile(
            client,
            base_url="https://umafans.run/",
            occurrences=occurrences,
        )
        self.assertEqual(result["resolution_state"], "resolved")
        self.assertEqual(result["profile_url"], canonical_detail)
        self.assertEqual(
            client.calls,
            [english_query, chinese_query, canonical_detail],
        )
        self.assertEqual(client.request_count, 3)

        direct_client = CanonicalRouteClient()
        direct = collector.fetch_profile(
            direct_client,
            base_url="https://umafans.run/",
            occurrences=[
                {**occurrences[0], "profile_url": canonical_detail[:-1]},
                {**occurrences[0], "profile_url": canonical_detail},
            ],
        )
        self.assertEqual(direct["resolution_state"], "resolved")
        self.assertEqual(direct_client.calls, [canonical_detail])

        merged = collector.merge_profile_records(
            [
                {
                    "key": "one",
                    "profile_url": canonical_detail[:-1],
                    "resolution_state": "resolved",
                    "name_zh": "南方之星",
                    "name_en": "Southern Star",
                    "birth_year": "2020",
                    "country": "australia",
                },
                {
                    "key": "two",
                    "profile_url": canonical_detail,
                    "resolution_state": "resolved",
                    "name_zh": "南方之星",
                    "name_en": "Southern Star",
                    "birth_year": "2020",
                    "country": "australia",
                },
            ],
            {"one", "two"},
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["profile_url"], canonical_detail)
        for invalid in (
            "https://umafans.run/horses/",
            "https://umafans.run/horses/0/",
            "https://umafans.run/horses/-1/",
            "https://umafans.run/horses/slug/",
            "https://umafans.run/horses/follows/",
            "https://umafans.run/horses/search/",
            "https://umafans.run/horses/42/extra/",
            "https://umafans.run/horses//42/",
            "https://umafans.run/horses/./42/",
            "https://umafans.run/horses/../42/",
            "https://umafans.run/horses/%34%32/",
            "https://umafans.run/horses/42/?x=1",
            "https://umafans.run/horses/42/#fragment",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                collector.validate_profile_url(invalid)

    def test_profile_url_rejects_raw_unicode_whitespace_and_control_bypasses(self):
        collector = load_collector(self)
        self.assertEqual(collector.optional_profile_url(None), "")
        self.assertEqual(collector.optional_profile_url(""), "")
        for nonempty_invalid in (False, 0, [], " "):
            with self.subTest(nonempty_invalid=repr(nonempty_invalid)):
                with self.assertRaises(ValueError):
                    collector.optional_profile_url(nonempty_invalid)
        self.assertEqual(
            collector.validate_profile_url(
                "https://UMAFANS.RUN/horses/42"
            ),
            "https://umafans.run/horses/42/",
        )
        self.assertEqual(
            collector.validate_profile_url(
                "https://WWW.UMAFANS.RUN/horses/42/"
            ),
            "https://www.umafans.run/horses/42/",
        )
        invalid = (
            "",
            " https://umafans.run/horses/42/",
            "https://umafans.run/horses/42/ ",
            "https://umafans.run/horses/ 42/",
            "https://umafans.run/horses/\t42/",
            "https://umafans.run/horses/\n42/",
            "https://umafans.run/horses/\u00a042/",
            "https://umafans.run/horses/\u200342/",
            "https://umafans.run/horses/\u200b42/",
            "https://umafans.run/horses/\ufeff42/",
            "https://umafans.run/horses/\x0042/",
            "https://umafans.run/horses/\x1f42/",
            "https://umafans.run/horses/４２/",
            "https://umafans.run／horses／42／",
            "https://umafans.run/horses/%34%32/",
        )
        for value in invalid:
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                collector.validate_profile_url(value)

    def test_invalid_profile_routes_are_rejected_at_all_identity_entrypoints(self):
        collector = load_collector(self)
        invalid_values = (
            " https://umafans.run/horses/42/",
            "https://umafans.run/horses/４２/",
            "https://umafans.run/horses/\u200b42/",
        )
        base_occurrence = {
            "region": "france",
            "country": "france",
            "horse_display_name": "Horse",
        }
        for invalid in invalid_values:
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(ValueError):
                    collector.parse_result_rows(
                        [
                            {
                                **finished_rows(1)[0],
                                "profile_url": invalid,
                            }
                        ]
                    )
                with self.assertRaises(ValueError):
                    collector.canonical_horse_key(
                        {**base_occurrence, "profile_url": invalid}
                    )
                with self.assertRaises(ValueError):
                    collector.build_horse_name_record(
                        [{**base_occurrence, "profile_url": ""}],
                        profile={
                            "resolution_state": "resolved",
                            "profile_url": invalid,
                        },
                    )
                with self.assertRaises(ValueError):
                    collector.merge_profile_records(
                        [
                            {
                                "key": "horse",
                                "profile_url": invalid,
                                "resolution_state": "resolved",
                            }
                        ],
                        {"horse"},
                    )
                RouteClient.routes = {}
                RouteClient.calls = []
                with self.assertRaises(ValueError):
                    collector.fetch_profile(
                        RouteClient(),
                        base_url="https://umafans.run/",
                        occurrences=[
                            {
                                **base_occurrence,
                                "profile_url": invalid,
                            }
                        ],
                    )
                self.assertEqual(RouteClient.calls, [])
                with tempfile.TemporaryDirectory() as raw:
                    with self.assertRaises(ValueError):
                        collector.finalize_artifacts(
                            output_dir=Path(raw),
                            year=2025,
                            occurrences=[
                                {
                                    **base_occurrence,
                                    "profile_url": "",
                                }
                            ],
                            profiles=[
                                {
                                    "key": collector.canonical_horse_key(
                                        {
                                            **base_occurrence,
                                            "profile_url": "",
                                        }
                                    ),
                                    "profile_url": invalid,
                                    "resolution_state": "resolved",
                                }
                            ],
                            source_manifest=[],
                            errors=[],
                            other_coverage=collector.classify_other_coverage(
                                year=2025,
                                discovered_other_urls=[],
                                manifest=None,
                            ),
                            request_count=0,
                            generated_at="2025-01-01T00:00:00+00:00",
                        )

    def test_profile_html_hrefs_are_strict_before_resolution(self):
        collector = load_collector(self)
        relative = collector.parse_profile_search_html(
            current_horse_search_html(
                display_name="Horse",
                original_name="Horse",
                region_label="法国",
                profile_path="/horses/42",
            ),
            base_url="https://umafans.run/",
        )
        absolute = collector.parse_profile_search_html(
            current_horse_search_html(
                display_name="Horse",
                original_name="Horse",
                region_label="法国",
                profile_path="https://UMAFANS.RUN/horses/42/",
            ),
            base_url="https://umafans.run/",
        )
        self.assertEqual(
            relative[0]["profile_url"],
            "https://umafans.run/horses/42/",
        )
        self.assertEqual(relative, absolute)

        invalid_hrefs = (
            "/horses/../horses/42/",
            " /horses/42/",
            "/horses/４２/",
            "//umafans.run/horses/42/",
            r"\horses\42",
            "/horses/%34%32/",
            "/horses/42/?x=1",
            "/horses/42/#fragment",
        )
        for href in invalid_hrefs:
            with self.subTest(href=repr(href)), self.assertRaises(ValueError):
                collector.parse_profile_search_html(
                    current_horse_search_html(
                        display_name="Horse",
                        original_name="Horse",
                        region_label="法国",
                        profile_path=href,
                    ),
                    base_url="https://umafans.run/",
                )
            race_html = current_race_template_html().replace(
                "<strong>Test Horse</strong>",
                f'<strong><a href="{href}">Test Horse</a></strong>',
            )
            with self.subTest(race_href=repr(href)), self.assertRaises(ValueError):
                collector.parse_race_html(
                    race_html,
                    url="https://umafans.run/races/2025/href-test/",
                    year=2025,
                )

    def test_absolute_profile_href_must_match_source_hostname_exactly(self):
        collector = load_collector(self)
        cases = (
            (
                "https://umafans.run/races/2025/test/",
                "https://umafans.run/horses/42/",
            ),
            (
                "https://www.umafans.run/races/2025/test/",
                "https://www.umafans.run/horses/42/",
            ),
        )
        for base_url, href in cases:
            with self.subTest(base_url=base_url, href=href):
                self.assertEqual(
                    collector.resolve_profile_href(
                        href, base_url=base_url
                    ),
                    href,
                )
        for base_url, href in (
            (
                "https://umafans.run/races/2025/test/",
                "https://www.umafans.run/horses/42/",
            ),
            (
                "https://www.umafans.run/races/2025/test/",
                "https://umafans.run/horses/42/",
            ),
        ):
            with self.subTest(base_url=base_url, href=href):
                with self.assertRaises(ValueError):
                    collector.resolve_profile_href(
                        href, base_url=base_url
                    )

    def test_multi_query_host_variants_fail_before_detail_request(self):
        collector = load_collector(self)
        search_base = "https://umafans.run/horses/"
        english_query = f"{search_base}?q=Southern+Star"
        chinese_query = f"{search_base}?q=%E5%8D%97%E6%96%B9%E4%B9%8B%E6%98%9F"

        class HostVariantClient:
            def __init__(self):
                self.calls = []
                self.request_count = 0

            def get(self, url, *, params=None):
                key = f"{url}?{urlencode(params)}" if params else url
                self.calls.append(key)
                self.request_count += 1
                routes = {
                    english_query: current_horse_search_html(
                        display_name="南方之星",
                        original_name="Southern Star",
                        region_label="其他",
                        profile_path="https://umafans.run/horses/42/",
                    ),
                    chinese_query: current_horse_search_html(
                        display_name="南方之星",
                        original_name="Southern Star",
                        region_label="其他",
                        profile_path="https://www.umafans.run/horses/42/",
                    ),
                }
                if key not in routes:
                    raise AssertionError(f"detail request was attempted: {key}")
                return FakeResponse(routes[key], key)

        client = HostVariantClient()
        with self.assertRaises(ValueError):
            collector.fetch_profile(
                client,
                base_url="https://umafans.run/",
                occurrences=[
                    {
                        "region": "australia",
                        "country": "australia",
                        "horse_display_name": "南方之星",
                        "original_name": "Southern Star",
                        "birth_year": "2020",
                        "profile_url": "",
                    }
                ],
            )
        self.assertEqual(client.calls, [english_query, chinese_query])
        self.assertEqual(client.request_count, 2)

    def test_profile_redirect_and_final_url_are_strict_before_join(self):
        collector = load_collector(self)
        start = "https://umafans.run/horses/41/"
        target = "https://umafans.run/horses/42/"

        class Response:
            status = 200
            headers = {}

            def __init__(self, url):
                self.url = url

            def read(self):
                return b"ok"

            def geturl(self):
                return self.url

        class RedirectOpener:
            def __init__(self, location, *, final_url=target):
                self.location = location
                self.final_url = final_url
                self.calls = []

            def open(self, request, timeout):
                self.calls.append(request.full_url)
                if len(self.calls) == 1:
                    raise HTTPError(
                        request.full_url,
                        302,
                        "redirect",
                        {"Location": self.location},
                        io.BytesIO(),
                    )
                return Response(self.final_url)

        for location in ("/horses/42/", target):
            with self.subTest(location=location):
                client = collector.HttpClient(
                    delay=0, timeout=1, request_budget=2
                )
                client.opener = RedirectOpener(location)
                response = client.get(start)
                self.assertEqual(response.url, target)
                self.assertEqual(client.opener.calls, [start, target])

        for location in (
            "/horses/../horses/42/",
            "https://evil.example/horses/42/",
            "https://www.umafans.run/horses/42/",
            " /horses/42/",
            "/horses/４２/",
        ):
            with self.subTest(location=repr(location)):
                client = collector.HttpClient(
                    delay=0, timeout=1, request_budget=2
                )
                client.opener = RedirectOpener(location)
                with self.assertRaises(ValueError):
                    client.get(start)
                self.assertEqual(client.opener.calls, [start])

        for final_url in (
            "https://umafans.run/horses/../horses/42/",
            "https://evil.example/horses/42/",
            "https://www.umafans.run/horses/42/",
        ):
            with self.subTest(final_url=final_url):
                client = collector.HttpClient(
                    delay=0, timeout=1, request_budget=1
                )
                client.opener = mock.Mock()
                client.opener.open.return_value = Response(final_url)
                with self.assertRaises(ValueError):
                    client.get(start)

    def test_middle_east_country_failures_always_emit_specific_evidence(self):
        collector = load_collector(self)
        profile_url = "https://umafans.run/horses/42/"
        base_occurrence = {
            "region": "middle_east",
            "horse_display_name": "Desert Star",
            "original_name": "Desert Star",
            "birth_year": "2020",
            "profile_url": "",
        }
        base_profile = {
            "profile_url": profile_url,
            "display_name": "Desert Star",
            "original_name": "Desert Star",
            "racing_region": "other",
            "birth_year": "2020",
        }
        cases = (
            (
                "both_uncontrolled",
                {**base_occurrence, "country": "iran", "country_raw": "Iran"},
                {**base_profile, "country": "iran", "country_raw": "Iran"},
                {
                    "middle_east_expected_country_uncontrolled",
                    "middle_east_actual_country_uncontrolled",
                },
            ),
            (
                "expected_missing",
                {**base_occurrence, "country": "", "country_raw": ""},
                {
                    **base_profile,
                    "country": "united_arab_emirates",
                    "country_raw": "UAE",
                },
                {"middle_east_expected_country_missing"},
            ),
            (
                "actual_missing",
                {
                    **base_occurrence,
                    "country": "united_arab_emirates",
                    "country_raw": "UAE",
                },
                {**base_profile, "country": "", "country_raw": ""},
                {"middle_east_actual_country_missing"},
            ),
        )
        records = []
        for key, occurrence, profile, expected_reasons in cases:
            result = collector._validate_profile_group(
                [occurrence], profile
            )
            self.assertNotEqual(result["resolution_state"], "resolved")
            records.append(
                {"key": key, "status": "success", **result}
            )
            review = result["identity_reviews"][0]
            self.assertIn("country", review["conflict_fields"])
            self.assertTrue(expected_reasons <= set(review["reasons"]))

        errors = collector._structured_errors([("profiles", records)])
        self.assertEqual(len(errors), 3)
        with tempfile.TemporaryDirectory() as raw:
            collector.finalize_artifacts(
                output_dir=Path(raw),
                year=2025,
                occurrences=[],
                profiles=[],
                source_manifest=[],
                errors=errors,
                other_coverage=collector.classify_other_coverage(
                    year=2025,
                    discovered_other_urls=[],
                    manifest=None,
                ),
                request_count=0,
                generated_at="2025-01-01T00:00:00+00:00",
            )
            written = json.loads(
                (Path(raw) / "errors.json").read_text(encoding="utf-8")
            )
        for error in written:
            self.assertIn("country", error["conflict_fields"])
            self.assertTrue(error["reasons"])
            self.assertIn("expected_country_raw", error)
            self.assertIn("expected_country_canonical", error)
            self.assertIn("actual_country_raw", error)
            self.assertIn("actual_country_canonical", error)

    def test_standard_regions_accept_matching_region_without_country(self):
        collector = load_collector(self)
        detail_url = "https://umafans.run/horses/42/"
        labels = {
            "japan": "日本",
            "hong_kong": "中国香港",
            "united_states": "美国",
            "united_kingdom": "英国",
            "france": "法国",
        }

        def fetch(*, region, path, actual_country):
            occurrence = {
                "region": region,
                "country": region,
                "horse_display_name": "Region Horse",
                "original_name": "Region Horse",
                "birth_year": "2020",
                "profile_url": detail_url if path == "direct" else "",
            }
            routes = {
                detail_url: current_horse_detail_html(
                    display_name="Region Horse",
                    original_name="Region Horse",
                    region_label=labels[region],
                    country=actual_country,
                    birth_year=2020,
                )
            }
            if path == "search":
                routes[profile_search_url("Region Horse")] = (
                    current_horse_search_html(
                        display_name="Region Horse",
                        original_name="Region Horse",
                        region_label=labels[region],
                    )
                )
            RouteClient.routes = routes
            RouteClient.calls = []
            parsed_profile = {
                "profile_url": detail_url,
                "display_name": "Region Horse",
                "original_name": "Region Horse",
                "name_en": "Region Horse",
                "racing_region": region,
                "country": actual_country,
                "country_raw": actual_country,
                "birth_year": "",
            }
            with mock.patch.object(
                collector,
                "parse_profile_html",
                return_value=parsed_profile,
            ):
                return collector.fetch_profile(
                    RouteClient(),
                    base_url="https://umafans.run/",
                    occurrences=[occurrence, dict(occurrence)],
                )

        for region in labels:
            for path in ("direct", "search"):
                with self.subTest(
                    region=region, path=path, case="country_missing"
                ):
                    self.assertEqual(
                        fetch(
                            region=region,
                            path=path,
                            actual_country="",
                        )["resolution_state"],
                        "resolved",
                    )
                with self.subTest(
                    region=region, path=path, case="country_conflict"
                ):
                    self.assertEqual(
                        fetch(
                            region=region,
                            path=path,
                            actual_country="germany",
                        )["resolution_state"],
                        "ambiguous",
                    )

        self.assertEqual(
            collector._profile_region_evidence_state(
                {
                    "region": "australia",
                    "country": "australia",
                    "birth_year": "",
                },
                {
                    "racing_region": "other",
                    "country": "",
                    "birth_year": "",
                },
            ),
            "unresolved",
        )
        self.assertEqual(
            collector._profile_region_evidence_state(
                {
                    "region": "middle_east",
                    "country": "united_arab_emirates",
                    "birth_year": "2020",
                },
                {
                    "racing_region": "other",
                    "country": "",
                    "birth_year": "2020",
                },
            ),
            "unresolved",
        )

    def test_uncontrolled_profile_country_fails_closed_without_region_backfill(self):
        collector = load_collector(self)
        detail_url = "https://umafans.run/horses/42/"
        labels = {
            "japan": "日本",
            "hong_kong": "中国香港",
            "united_states": "美国",
            "united_kingdom": "英国",
            "france": "法国",
        }

        for region, region_label in labels.items():
            missing_country_profile = collector.parse_profile_html(
                current_horse_detail_html(
                    display_name="Region Horse",
                    original_name="Region Horse",
                    region_label=region_label,
                    country="",
                    birth_year=2020,
                ),
                url=detail_url,
            )
            self.assertEqual(
                missing_country_profile["racing_region"], region
            )
            self.assertEqual(missing_country_profile["country"], "")
            self.assertEqual(missing_country_profile["country_raw"], "")
            self.assertEqual(
                missing_country_profile["country_fact_state"],
                "missing",
            )
            detail_html = current_horse_detail_html(
                display_name="Region Horse",
                original_name="Region Horse",
                region_label=region_label,
                country="Ireland",
                birth_year=2020,
            )
            parsed = collector.parse_profile_html(
                detail_html,
                url=detail_url,
            )
            self.assertEqual(parsed["racing_region"], region)
            self.assertEqual(parsed["country"], "")
            self.assertEqual(parsed["country_raw"], "Ireland")
            self.assertEqual(
                parsed["country_fact_state"],
                "uncontrolled",
            )
            occurrence = {
                "region": region,
                "country": region,
                "horse_display_name": "Region Horse",
                "original_name": "Region Horse",
                "birth_year": "2020",
            }
            for path in ("direct", "search"):
                with self.subTest(region=region, path=path):
                    current = {
                        **occurrence,
                        "profile_url": (
                            detail_url if path == "direct" else ""
                        ),
                    }
                    routes = {detail_url: detail_html}
                    if path == "search":
                        routes[profile_search_url("Region Horse")] = (
                            current_horse_search_html(
                                display_name="Region Horse",
                                original_name="Region Horse",
                                region_label=region_label,
                            )
                        )
                    RouteClient.routes = routes
                    RouteClient.calls = []
                    result = collector.fetch_profile(
                        RouteClient(),
                        base_url="https://umafans.run/",
                        occurrences=[current, dict(current)],
                    )
                    self.assertEqual(
                        result["resolution_state"],
                        "ambiguous",
                    )
                    for review in result["identity_reviews"]:
                        self.assertIn(
                            "country", review["conflict_fields"]
                        )
                        self.assertIn(
                            "actual_country_uncontrolled",
                            review["reasons"],
                        )
                        self.assertEqual(
                            review["actual_country_raw"], "Ireland"
                        )
                        self.assertEqual(
                            review["actual_country_canonical"], ""
                        )
                        self.assertEqual(
                            review["actual_country_fact_state"],
                            "uncontrolled",
                        )
                    errors = collector._structured_errors(
                        [
                            (
                                "profiles",
                                [{"key": "region-horse", **result}],
                            )
                        ]
                    )
                    self.assertEqual(len(errors), 2)
                    for error in errors:
                        self.assertEqual(
                            error["actual_country_raw"], "Ireland"
                        )
                        self.assertEqual(
                            error["actual_country_canonical"], ""
                        )
                        self.assertEqual(
                            error["actual_country_fact_state"],
                            "uncontrolled",
                        )
                        self.assertIn(
                            "actual_country_uncontrolled",
                            error["reasons"],
                        )

        self.assertEqual(
            collector._profile_region_evidence_state(
                {
                    "region": "france",
                    "country": "france",
                    "birth_year": "2021",
                },
                {
                    "racing_region": "france",
                    "country": "france",
                    "country_raw": "France",
                    "birth_year": "2020",
                },
            ),
            "ambiguous",
        )
        for region in ("australia", "germany"):
            self.assertEqual(
                collector._profile_region_evidence_state(
                    {
                        "region": region,
                        "country": region,
                        "birth_year": "2020",
                    },
                    {
                        "racing_region": "other",
                        "country": "",
                        "country_raw": "Ireland",
                        "birth_year": "2020",
                    },
                ),
                "ambiguous",
            )
        self.assertNotEqual(
            collector._profile_region_evidence_state(
                {
                    "region": "middle_east",
                    "country": "united_arab_emirates",
                    "birth_year": "2020",
                },
                {
                    "racing_region": "other",
                    "country": "",
                    "country_raw": "Ireland",
                    "birth_year": "2020",
                },
            ),
            "resolved",
        )

    def test_discovery_deadline_persists_exact_queue_and_resumes(self):
        collector = load_collector(self)
        root_url = "https://umafans.run/sitemap.xml"
        shard_one = "https://umafans.run/sitemap-races-1.xml"
        shard_two = "https://umafans.run/sitemap-races-2.xml"
        race_one = "https://umafans.run/races/2025/one/"
        race_two = "https://umafans.run/races/2025/two/"
        routes = {
            root_url: (
                '<?xml version="1.0"?><sitemapindex>'
                f"<sitemap><loc>{shard_one}</loc></sitemap>"
                f"<sitemap><loc>{shard_two}</loc></sitemap>"
                "</sitemapindex>"
            ),
            shard_one: (
                '<?xml version="1.0"?><urlset>'
                f"<url><loc>{race_one}</loc></url></urlset>"
            ),
            shard_two: (
                '<?xml version="1.0"?><urlset>'
                f"<url><loc>{race_two}</loc></url></urlset>"
            ),
        }

        class Clock:
            def __init__(self):
                self.value = 0.0

            def __call__(self):
                return self.value

        class Client:
            def __init__(self, clock):
                self.clock = clock
                self.request_count = 0
                self.calls = []

            def get(self, url):
                self.calls.append(url)
                self.request_count += 1
                self.clock.value += 1.0
                return FakeResponse(routes[url], url)

        identity = {
            "schema_version": collector.SCHEMA_VERSION,
            "stage": "races_discovery",
            "year": 2025,
            "base_url": "https://umafans.run/",
            "region_manifest_sha256": "none",
            "tool_identity": collector.current_tool_identity_record(),
            "request_budget": 10,
        }
        with tempfile.TemporaryDirectory() as interrupted_raw, tempfile.TemporaryDirectory() as clean_raw:
            interrupted_path = Path(interrupted_raw) / "discovery.json"
            interrupted_clock = Clock()
            interrupted_client = Client(interrupted_clock)
            with self.assertRaises(collector.StageDeadlineExceeded):
                collector.discover_race_urls(
                    interrupted_client,
                    base_url="https://umafans.run/",
                    year=2025,
                    progress_path=interrupted_path,
                    identity=identity,
                    resume=False,
                    deadline=collector.StageDeadline(
                        deadline_at=1.5,
                        clock=interrupted_clock,
                        safety_margin=0,
                    ),
                )
            stopped = json.loads(interrupted_path.read_text())
            self.assertEqual(stopped["visited"], [root_url, shard_one])
            self.assertEqual(stopped["queue"], [shard_two])
            self.assertEqual(stopped["discovered_urls"], [race_one])
            valid_progress = interrupted_path.read_bytes()
            rolled_back = dict(stopped)
            rolled_back["request_count"] -= 1
            collector.atomic_write_json(interrupted_path, rolled_back)
            rejected_client = Client(interrupted_clock)
            rejected_client.request_count = interrupted_client.request_count
            with self.assertRaisesRegex(ValueError, "request count|drift"):
                collector.discover_race_urls(
                    rejected_client,
                    base_url="https://umafans.run/",
                    year=2025,
                    progress_path=interrupted_path,
                    identity=identity,
                    resume=True,
                )
            collector.atomic_write_text(interrupted_path, "{corrupt")
            with self.assertRaisesRegex(ValueError, "corrupt"):
                collector.discover_race_urls(
                    rejected_client,
                    base_url="https://umafans.run/",
                    year=2025,
                    progress_path=interrupted_path,
                    identity=identity,
                    resume=True,
                )
            collector.atomic_write_bytes(interrupted_path, valid_progress)

            resumed_clock = Clock()
            resumed_client = Client(resumed_clock)
            resumed_client.request_count = interrupted_client.request_count
            resumed = collector.discover_race_urls(
                resumed_client,
                base_url="https://umafans.run/",
                year=2025,
                progress_path=interrupted_path,
                identity=identity,
                resume=True,
                deadline=collector.StageDeadline(
                    deadline_at=10,
                    clock=resumed_clock,
                    safety_margin=0,
                ),
            )
            clean_clock = Clock()
            clean_client = Client(clean_clock)
            clean_path = Path(clean_raw) / "discovery.json"
            clean = collector.discover_race_urls(
                clean_client,
                base_url="https://umafans.run/",
                year=2025,
                progress_path=clean_path,
                identity=identity,
                resume=False,
                deadline=collector.StageDeadline(
                    deadline_at=10,
                    clock=clean_clock,
                    safety_margin=0,
                ),
            )
            self.assertEqual(resumed, clean)
            self.assertEqual(interrupted_path.read_bytes(), clean_path.read_bytes())
            self.assertEqual(
                interrupted_client.request_count
                + len(resumed_client.calls),
                clean_client.request_count,
            )
            self.assertNotIn(root_url, resumed_client.calls)
            self.assertNotIn(shard_one, resumed_client.calls)

    def test_races_discovery_deadline_returns_75_and_run_stage_resumes(self):
        collector = load_collector(self)
        root_url = "https://umafans.run/sitemap.xml"
        shard_one = "https://umafans.run/sitemap-races-1.xml"
        shard_two = "https://umafans.run/sitemap-races-2.xml"
        race_one = "https://umafans.run/races/2025/one/"
        race_two = "https://umafans.run/races/2025/two/"
        routes = {
            root_url: (
                '<?xml version="1.0"?><sitemapindex>'
                f"<sitemap><loc>{shard_one}</loc></sitemap>"
                f"<sitemap><loc>{shard_two}</loc></sitemap>"
                "</sitemapindex>"
            ),
            shard_one: (
                '<?xml version="1.0"?><urlset>'
                f"<url><loc>{race_one}</loc></url></urlset>"
            ),
            shard_two: (
                '<?xml version="1.0"?><urlset>'
                f"<url><loc>{race_two}</loc></url></urlset>"
            ),
            race_one: current_race_template_html(),
            race_two: current_race_template_html(),
        }
        clock_value = [0.0]

        class SlowClient:
            calls = []

            def __init__(self, **kwargs):
                self.request_count = kwargs.get("request_count_start", 0)
                self.request_reserver = kwargs.get("request_reserver")
                self.deadline = kwargs.get("deadline")

            def check_deadline(self, required_seconds=0):
                if self.deadline:
                    self.deadline.check(required_seconds)

            def get(self, url, *, params=None):
                self.check_deadline()
                if self.request_reserver:
                    self.request_count = self.request_reserver()
                else:
                    self.request_count += 1
                type(self).calls.append(url)
                clock_value[0] += 1.0
                return FakeResponse(routes[url], url)

        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            collector, "HttpClient", SlowClient
        ), mock.patch.object(
            collector.time, "monotonic", side_effect=lambda: clock_value[0]
        ), mock.patch.object(
            collector,
            "utc_now_iso",
            return_value="2025-01-01T00:00:00+00:00",
        ):
            root = Path(raw)

            def args(*extra):
                return collector.parse_args(
                    [
                        "--year",
                        "2025",
                        "--stage",
                        "races",
                        "--base-url",
                        "https://umafans.run/",
                        "--output-dir",
                        str(root),
                        "--time-budget-seconds",
                        "1.5",
                        *extra,
                    ]
                )

            self.assertEqual(
                collector.run_stage(args()), collector.SAFE_STOP_EXIT_CODE
            )
            self.assertFalse((root / "run_manifest.json").exists())
            stopped_calls = list(SlowClient.calls)
            self.assertEqual(stopped_calls, [root_url, shard_one])
            clock_value[0] = 0.0
            resumed_args = args("--resume")
            resumed_args.time_budget_seconds = 10
            self.assertEqual(collector.run_stage(resumed_args), 0)
            self.assertEqual(
                json.loads((root / "run_manifest.json").read_text())[
                    "race_urls"
                ],
                [race_one, race_two],
            )
            self.assertEqual(
                SlowClient.calls,
                [root_url, shard_one, shard_two, race_one, race_two],
            )
            self.assertEqual(
                json.loads(
                    (
                        root
                        / "stages/races/shards/0/request_ledger.json"
                    ).read_text()
                )["request_count"],
                5,
            )

    def test_discovery_retry_exhaustion_safe_stops_and_resumes_exactly(self):
        collector = load_collector(self)
        root_url = "https://umafans.run/sitemap.xml"
        race_url = "https://umafans.run/races/2025/retry-race/"
        sitemap = (
            '<?xml version="1.0"?><urlset>'
            f"<url><loc>{race_url}</loc></url></urlset>"
        )

        class Response:
            status = 200
            headers = {}

            def __init__(self, body, url):
                self.body = body.encode()
                self.url = url

            def read(self):
                return self.body

            def geturl(self):
                return self.url

        class ScriptedOpener:
            def __init__(self, failure_factory=None, failures=0):
                self.failure_factory = failure_factory
                self.failures = failures
                self.calls = []

            def open(self, request, timeout):
                url = request.full_url
                self.calls.append(url)
                if url == root_url and self.failures:
                    self.failures -= 1
                    raise self.failure_factory(url)
                if url == root_url:
                    return Response(sitemap, url)
                if url == race_url:
                    return Response(current_race_template_html(), url)
                raise AssertionError(url)

        failures = {
            "429": lambda url: HTTPError(
                url, 429, "rate limited", {}, io.BytesIO()
            ),
            "500": lambda url: HTTPError(
                url, 500, "server error", {}, io.BytesIO()
            ),
            "transport": lambda url: collector.URLError(
                "temporary transport"
            ),
        }
        for label, failure_factory in failures.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as clean_raw:
                root = Path(raw)
                clean_root = Path(clean_raw)
                active_opener = [
                    ScriptedOpener(failure_factory, failures=5)
                ]

                def args(output, *extra):
                    return collector.parse_args(
                        [
                            "--year",
                            "2025",
                            "--stage",
                            "races",
                            "--base-url",
                            "https://umafans.run/",
                            "--output-dir",
                            str(output),
                            "--delay",
                            "0",
                            *extra,
                        ]
                    )

                with mock.patch.object(
                    collector,
                    "build_opener",
                    side_effect=lambda *handlers: active_opener[0],
                ), mock.patch.object(
                    collector.time, "sleep", return_value=None
                ), mock.patch.object(
                    collector,
                    "utc_now_iso",
                    return_value="2025-01-01T00:00:00+00:00",
                ):
                    self.assertEqual(
                        collector.run_stage(args(root)),
                        collector.SAFE_STOP_EXIT_CODE,
                    )
                    self.assertFalse((root / "run_manifest.json").exists())
                    progress_path = (
                        root
                        / "stages/races/discovery_progress.json"
                    )
                    ledger_path = (
                        root
                        / "stages/races/discovery_request_ledger.json"
                    )
                    progress = json.loads(progress_path.read_text())
                    ledger = json.loads(ledger_path.read_text())
                    self.assertEqual(progress["queue"], [root_url])
                    self.assertEqual(progress["inflight_url"], root_url)
                    self.assertEqual(progress["request_count"], 5)
                    self.assertFalse(progress["complete"])
                    self.assertEqual(ledger["request_count"], 5)

                    self.assertEqual(
                        collector.run_stage(args(root, "--resume")), 0
                    )
                    self.assertEqual(
                        active_opener[0].calls,
                        [root_url] * 6 + [race_url],
                    )
                    self.assertEqual(
                        json.loads(
                            (
                                root
                                / "stages/races/shards/0/request_ledger.json"
                            ).read_text()
                        )["request_count"],
                        7,
                    )

                    active_opener[0] = ScriptedOpener()
                    self.assertEqual(
                        collector.run_stage(args(clean_root)), 0
                    )
                    self.assertEqual(
                        (root / "run_manifest.json").read_bytes(),
                        (clean_root / "run_manifest.json").read_bytes(),
                    )
                    self.assertEqual(
                        json.loads(
                            (
                                clean_root
                                / "stages/races/shards/0/request_ledger.json"
                            ).read_text()
                        )["request_count"],
                        2,
                    )

    def test_discovery_deterministic_404_remains_permanent(self):
        collector = load_collector(self)
        root_url = "https://umafans.run/sitemap.xml"

        class NotFoundOpener:
            def open(self, request, timeout):
                raise HTTPError(
                    request.full_url,
                    404,
                    "missing",
                    {},
                    io.BytesIO(),
                )

        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            collector, "build_opener", return_value=NotFoundOpener()
        ):
            root = Path(raw)
            args = collector.parse_args(
                [
                    "--year",
                    "2025",
                    "--stage",
                    "races",
                    "--base-url",
                    "https://umafans.run/",
                    "--output-dir",
                    str(root),
                    "--delay",
                    "0",
                ]
            )
            with self.assertRaises(collector.PermanentHttpError):
                collector.run_stage(args)
            progress = json.loads(
                (
                    root / "stages/races/discovery_progress.json"
                ).read_text()
            )
            ledger = json.loads(
                (
                    root
                    / "stages/races/discovery_request_ledger.json"
                ).read_text()
            )
            self.assertEqual(progress["inflight_url"], root_url)
            self.assertEqual(progress["request_count"], 1)
            self.assertEqual(ledger["request_count"], 1)
            self.assertFalse((root / "run_manifest.json").exists())

    def test_profile_pagination_checks_shared_stage_deadline(self):
        collector = load_collector(self)
        search_url = profile_search_url("English Star")
        clock_value = [0.0]

        class Clock:
            def __call__(self):
                return clock_value[0]

        RouteClient.routes = {
            search_url: horse_search_page(
                [], next_href="?q=English+Star&amp;page=2"
            )
        }
        RouteClient.calls = []
        client = RouteClient()
        client.deadline = collector.StageDeadline(
            deadline_at=1.0,
            clock=Clock(),
            safety_margin=0,
        )
        original_get = client.get

        def slow_get(url, *, params=None):
            response = original_get(url, params=params)
            clock_value[0] += 1.0
            return response

        client.get = slow_get
        with self.assertRaises(collector.StageDeadlineExceeded):
            collector.fetch_profile(
                client,
                base_url="https://umafans.run/",
                occurrences=[
                    {
                        "region": "france",
                        "country": "france",
                        "horse_display_name": "English Star",
                        "original_name": "English Star",
                        "profile_url": "",
                    }
                ],
            )
        self.assertEqual(RouteClient.calls, [search_url])

    def test_profile_search_only_treats_first_page_404_as_empty(self):
        collector = load_collector(self)
        first_url = "https://umafans.run/horses/?q=English+Star"
        second_url = f"{first_url}&page=2"
        detail_url = "https://umafans.run/horses/42/"

        class Response:
            status = 200
            headers = {}

            def __init__(self, body, url):
                self.body = body.encode()
                self.url = url

            def read(self):
                return self.body

            def geturl(self):
                return self.url

        class Opener:
            def __init__(self, first_is_404=False):
                self.first_is_404 = first_is_404
                self.calls = []

            def open(self, request, timeout):
                url = request.full_url
                self.calls.append(url)
                if self.first_is_404 or url == second_url:
                    raise HTTPError(url, 404, "missing", {}, io.BytesIO())
                if url == first_url:
                    return Response(
                        horse_search_page(
                            [
                                (
                                    "中文星",
                                    "English Star",
                                    "法国",
                                    "/horses/42/",
                                )
                            ],
                            next_href="?q=English+Star&amp;page=2",
                        ),
                        url,
                    )
                if url == detail_url:
                    return Response(
                        current_horse_detail_html(
                            display_name="中文星",
                            original_name="English Star",
                            region_label="法国",
                            country="france",
                            birth_year=2020,
                        ),
                        url,
                    )
                raise AssertionError(url)

        occurrence = [
            {
                "region": "france",
                "country": "france",
                "horse_display_name": "English Star",
                "original_name": "English Star",
                "profile_url": "",
            }
        ]
        client = collector.HttpClient(delay=0, timeout=1, request_budget=3)
        client.opener = Opener()
        with self.assertRaises(collector.PermanentHttpError):
            collector.fetch_profile(
                client,
                base_url="https://umafans.run/",
                occurrences=occurrence,
            )
        self.assertEqual(client.opener.calls, [first_url, second_url])

        empty_client = collector.HttpClient(
            delay=0, timeout=1, request_budget=1
        )
        empty_client.opener = Opener(first_is_404=True)
        self.assertEqual(
            collector.fetch_profile(
                empty_client,
                base_url="https://umafans.run/",
                occurrences=occurrence,
            )["resolution_state"],
            "not_found",
        )
        self.assertEqual(empty_client.opener.calls, [first_url])

    def test_periodic_index_crash_resumes_byte_equivalent_with_budget_preserved(self):
        collector = load_collector(self)

        class CheckpointCrash(BaseException):
            pass

        class Response:
            status = 200
            headers = {}

            def read(self):
                return b"ok"

            def geturl(self):
                return "https://umafans.run/healthz/"

        class Opener:
            def open(self, request, timeout):
                return Response()

        def make_store(root):
            return collector.StageStore(
                root,
                stage="races",
                year=2025,
                manifest_sha256="manifest",
                request_budget=2,
                input_keys_sha256=collector.keys_sha256(["a", "b"]),
                tool_identity={"tool": "frozen"},
            )

        def run(store):
            prior = collector.trusted_stage_request_count(store)
            client = collector.HttpClient(
                delay=0,
                timeout=1,
                request_budget=2,
                request_count_start=prior,
                request_reserver=store.request_ledger().reserve,
            )
            client.opener = Opener()

            def process(key):
                client.get("https://umafans.run/healthz/")
                return {"key": key, "status": "success"}

            return collector.run_checkpointed_items(
                ["a", "b"],
                store=store,
                process=process,
                resume=True,
                checkpoint_every=1,
                request_counter=lambda: client.request_count,
                request_counter_start=prior,
                clock=lambda: 0.0,
                now=lambda: "2025-01-01T00:00:00+00:00",
            )

        with tempfile.TemporaryDirectory() as clean_raw, tempfile.TemporaryDirectory() as crash_raw:
            clean_store = make_store(Path(clean_raw))
            clean_progress = run(clean_store)
            self.assertFalse(clean_progress["safe_stopped"])

            crash_store = make_store(Path(crash_raw))
            original_rebuild = crash_store.rebuild_index
            calls = 0

            def crash_after_periodic_index(*, request_count=None):
                nonlocal calls
                index = original_rebuild(request_count=request_count)
                calls += 1
                if calls == 1:
                    raise CheckpointCrash()
                return index

            with mock.patch.object(
                crash_store, "rebuild_index", crash_after_periodic_index
            ), self.assertRaises(CheckpointCrash):
                run(crash_store)
            self.assertTrue(crash_store.index_path.exists())
            self.assertFalse(crash_store.progress_path.exists())
            self.assertEqual(
                crash_store.verify_index()["request_count"], 1
            )
            self.assertEqual(
                crash_store.request_ledger().verify()["request_count"], 1
            )

            resumed = run(crash_store)
            self.assertFalse(resumed["safe_stopped"])
            self.assertEqual(resumed["request_count"], 2)
            self.assertEqual(
                crash_store.request_ledger().verify()["request_count"], 2
            )
            for relative in (
                "stages/races/index.json",
                "stages/races/progress.json",
                "stages/races/request_ledger.json",
            ):
                self.assertEqual(
                    (Path(clean_raw) / relative).read_bytes(),
                    (Path(crash_raw) / relative).read_bytes(),
                )
            clean_items = sorted(
                path.read_bytes()
                for path in clean_store.items_dir.glob("*.json")
            )
            crash_items = sorted(
                path.read_bytes()
                for path in crash_store.items_dir.glob("*.json")
            )
            self.assertEqual(clean_items, crash_items)

    def test_country_fact_accepts_only_controlled_target_iso_codes(self):
        collector = load_collector(self)
        aliases = {
            " JP ": "japan",
            "jpn": "japan",
            "HK": "hong_kong",
            "hkg": "hong_kong",
            "US": "united_states",
            "usa": "united_states",
            "GB": "united_kingdom",
            "gbr": "united_kingdom",
            "UK": "united_kingdom",
            "FR": "france",
            "fra": "france",
            "AU": "australia",
            "aus": "australia",
            "DE": "germany",
            "deu": "germany",
            "AE": "united_arab_emirates",
            "are": "united_arab_emirates",
            "SA": "saudi_arabia",
            "sau": "saudi_arabia",
            "QA": "qatar",
            "qat": "qatar",
            "BH": "bahrain",
            "bhr": "bahrain",
        }
        for raw, expected in aliases.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    collector.normalize_country_fact(raw), expected
                )
        for raw in ("UKR", "AT", "CN", "U S", "ZZ", "JAP"):
            with self.subTest(raw=raw):
                self.assertEqual(collector.normalize_country_fact(raw), "")

    def test_profile_iso_country_fact_proves_region_and_rejects_wrong_region(self):
        collector = load_collector(self)
        cases = (
            ("japan", "japan", "JP"),
            ("hong_kong", "hong_kong", "HKG"),
            ("united_states", "united_states", "US"),
            ("united_kingdom", "united_kingdom", "GBR"),
            ("france", "france", "FR"),
            ("australia", "australia", "AUS"),
            ("germany", "germany", "DE"),
            ("middle_east", "united_arab_emirates", "AE"),
            ("middle_east", "saudi_arabia", "SAU"),
            ("middle_east", "qatar", "QA"),
            ("middle_east", "bahrain", "BHR"),
        )
        for region, country, code in cases:
            with self.subTest(region=region, code=code):
                profile = collector.parse_profile_html(
                    current_horse_detail_html(
                        display_name="Code Horse",
                        original_name="Code Horse",
                        region_label="其他",
                        country=code,
                        birth_year=2020,
                    ),
                    url="https://umafans.run/horses/42/",
                )
                self.assertEqual(profile["country"], country)
                self.assertEqual(
                    collector._profile_region_evidence_state(
                        {"region": region, "country": country},
                        profile,
                    ),
                    "resolved",
                )
        wrong = collector.parse_profile_html(
            current_horse_detail_html(
                display_name="Code Horse",
                original_name="Code Horse",
                region_label="其他",
                country="DE",
                birth_year=2020,
            ),
            url="https://umafans.run/horses/42/",
        )
        self.assertEqual(
            collector._profile_region_evidence_state(
                {"region": "france", "country": "france"}, wrong
            ),
            "ambiguous",
        )

    def test_shared_profile_url_validates_every_occurrence_identity(self):
        collector = load_collector(self)
        detail_url = "https://umafans.run/horses/42/"
        RouteClient.routes = {
            detail_url: current_horse_detail_html(
                display_name="中文星",
                original_name="English Star",
                region_label="法国",
                country="france",
                birth_year=2020,
            )
        }
        base = {
            "region": "france",
            "country": "france",
            "profile_url": detail_url,
        }
        valid = [
            {
                **base,
                "horse_display_name": "中文星",
                "original_name": "English Star",
            },
            {
                **base,
                "horse_display_name": "English Star",
                "original_name": "English Star",
            },
        ]
        RouteClient.calls = []
        resolved = collector.fetch_profile(
            RouteClient(),
            base_url="https://umafans.run/",
            occurrences=valid,
        )
        self.assertEqual(resolved["resolution_state"], "resolved")
        self.assertEqual(RouteClient.calls, [detail_url])

        for conflicting in (
            {
                **base,
                "horse_display_name": "Other Horse",
                "original_name": "Other Horse",
            },
            {
                **base,
                "region": "germany",
                "country": "germany",
                "horse_display_name": "English Star",
                "original_name": "English Star",
            },
        ):
            with self.subTest(conflicting=conflicting):
                RouteClient.calls = []
                result = collector.fetch_profile(
                    RouteClient(),
                    base_url="https://umafans.run/",
                    occurrences=[valid[0], conflicting],
                )
                self.assertEqual(result["resolution_state"], "ambiguous")
                self.assertEqual(
                    [row["occurrence_index"] for row in result["identity_reviews"]],
                    [0, 1],
                )
                self.assertEqual(
                    result["identity_reviews"][1]["review_state"],
                    "ambiguous",
                )
                structured = collector._structured_errors(
                    [
                        (
                            "profiles",
                            [
                                {
                                    "key": "shared-profile",
                                    "status": "success",
                                    **result,
                                }
                            ],
                        )
                    ]
                )
                self.assertEqual(len(structured), 1)
                self.assertEqual(
                    structured[0]["occurrence_index"], 1
                )
                self.assertEqual(
                    structured[0]["horse_display_name"],
                    conflicting["horse_display_name"],
                )
                self.assertEqual(
                    structured[0]["region"], conflicting["region"]
                )
                self.assertEqual(RouteClient.calls, [detail_url])

    def test_pending_live_conflict_is_non_final_but_official_without_conflict_is_final(self):
        collector = load_collector(self)
        pending = collector.parse_race_html(
            current_race_template_html(
                region="法国",
                result_phase="official",
                conflict_status="pending",
            ),
            url="https://umafans.run/races/2025/pending-conflict/",
            year=2025,
        )
        self.assertEqual(pending["status"], "evidence_gap")
        self.assertEqual(pending["error_code"], "result_not_final")
        self.assertEqual(pending["rows"], [])
        self.assertEqual(pending["source"]["region"], "france")
        final = collector.parse_race_html(
            current_race_template_html(
                result_phase="official", conflict_status=""
            ),
            url="https://umafans.run/races/2025/no-conflict/",
            year=2025,
        )
        self.assertEqual(final["status"], "success")
        self.assertEqual(len(final["rows"]), 1)

    def test_missing_profile_hero_name_never_uses_occurrence_fallback(self):
        collector = load_collector(self)
        detail_url = "https://umafans.run/horses/42/"
        for detail in (
            current_horse_detail_html(
                display_name="",
                original_name="Direct Horse",
                region_label="法国",
                country="france",
                birth_year=2020,
            ),
            current_horse_detail_html(
                display_name="Direct Horse",
                original_name="Direct Horse",
                region_label="法国",
                country="france",
                birth_year=2020,
            ).replace(
                '<h1 class="horse-hero-name">Direct Horse</h1>', ""
            ),
        ):
            with self.subTest(missing="<h1" not in detail):
                RouteClient.routes = {detail_url: detail}
                RouteClient.calls = []
                occurrence = {
                    "region": "france",
                    "country": "france",
                    "horse_display_name": "Direct Horse",
                    "original_name": "Direct Horse",
                    "profile_url": detail_url,
                }
                result = collector.fetch_profile(
                    RouteClient(),
                    base_url="https://umafans.run/",
                    occurrences=[occurrence],
                )
                self.assertEqual(result["resolution_state"], "unresolved")
                review_record = collector.build_horse_name_record(
                    [occurrence], profile=result
                )
                self.assertIn(
                    "profile_unresolved", review_record["name_issue_codes"]
                )

    def test_provisional_full_run_stage_dag_emits_partial_seven_files(self):
        collector = load_collector(self)
        sitemap_url = "https://umafans.run/sitemap.xml"
        race_url = "https://umafans.run/races/2025/provisional-only/"
        RouteClient.routes = {
            sitemap_url: (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{race_url}</loc></url></urlset>"
            ),
            race_url: current_race_template_html(
                region="法国", result_phase="provisional"
            ),
        }
        RouteClient.calls = []
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            collector, "HttpClient", RouteClient
        ):
            root = Path(raw)

            def args(stage, *extra):
                return collector.parse_args(
                    [
                        "--year",
                        "2025",
                        "--stage",
                        stage,
                        "--base-url",
                        "https://umafans.run/",
                        "--output-dir",
                        str(root),
                        *extra,
                    ]
                )

            self.assertEqual(collector.run_stage(args("races")), 0)
            race_index = json.loads(
                (root / "stages/races/shards/0/index.json").read_text()
            )
            self.assertEqual(
                [item["status"] for item in race_index["items"]],
                ["evidence_gap"],
            )
            for shard in range(4):
                self.assertEqual(
                    collector.run_stage(
                        args(
                            "profiles",
                            "--shard-index",
                            str(shard),
                            "--shard-count",
                            "4",
                        )
                    ),
                    0,
                )
            self.assertEqual(collector.run_stage(args("merge_profiles")), 0)
            self.assertEqual(collector.run_stage(args("finalize")), 0)
            final = root / "final"
            summary = json.loads((final / "summary.json").read_text())
            errors = json.loads((final / "errors.json").read_text())
            self.assertEqual(summary["outcome"], "partial")
            self.assertEqual(summary["counts"]["participant_rows"], 0)
            self.assertEqual(
                summary["coverage_by_region"]["france"], "partial_error"
            )
            self.assertIn(
                "result_not_final",
                {item["error_code"] for item in errors},
            )
            self.assertEqual(
                sorted(path.name for path in final.iterdir()),
                sorted(collector.final_filenames(2025)),
            )
            for filename, expected_fields in (
                (
                    "race_participants_2025.csv",
                    collector.RACE_PARTICIPANT_FIELDS,
                ),
                ("horse_names_2025.csv", collector.HORSE_NAME_FIELDS),
                (
                    "horse_name_review_queue_2025.csv",
                    collector.HORSE_REVIEW_FIELDS,
                ),
            ):
                with (final / filename).open(
                    encoding="utf-8-sig", newline=""
                ) as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, list(expected_fields))
                    self.assertEqual(list(reader), [])
            self.assertEqual(RouteClient.calls, [sitemap_url, race_url])

    def test_all_unknown_result_rows_complete_dag_as_reviewable_evidence_gap(self):
        collector = load_collector(self)
        sitemap_url = "https://umafans.run/sitemap.xml"
        race_url = "https://umafans.run/races/2025/unknown-statuses/"
        RouteClient.routes = {
            sitemap_url: (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{race_url}</loc></url></urlset>"
            ),
            race_url: current_race_template_html(
                region="法国",
                rows=[
                    ("MYSTERY", "1", "Unknown One"),
                    ("?", "2", "Unknown Two"),
                ],
            ),
        }
        RouteClient.calls = []
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            collector, "HttpClient", RouteClient
        ):
            root = Path(raw)

            def args(stage, *extra):
                return collector.parse_args(
                    [
                        "--year",
                        "2025",
                        "--stage",
                        stage,
                        "--base-url",
                        "https://umafans.run/",
                        "--output-dir",
                        str(root),
                        *extra,
                    ]
                )

            self.assertEqual(collector.run_stage(args("races")), 0)
            race_record = collector.load_store_records(
                collector._bound_store(
                    root,
                    stage="races",
                    year=2025,
                    manifest_sha256=collector.sha256_bytes(
                        (root / "run_manifest.json").read_bytes()
                    ),
                    region_manifest_sha256="none",
                    shard_index=0,
                    shard_count=1,
                    upstream_indexes={},
                    input_keys=[race_url],
                    tool_identity=collector.current_tool_identity_record(),
                    request_budget=collector.REQUEST_BUDGETS["races"],
                )
            )[0]
            self.assertEqual(race_record["status"], "evidence_gap")
            self.assertEqual(race_record["rows"], [])
            self.assertEqual(len(race_record["unresolved_rows"]), 2)
            for shard in range(4):
                self.assertEqual(
                    collector.run_stage(
                        args(
                            "profiles",
                            "--shard-index",
                            str(shard),
                            "--shard-count",
                            "4",
                        )
                    ),
                    0,
                )
            self.assertEqual(collector.run_stage(args("merge_profiles")), 0)
            self.assertEqual(collector.run_stage(args("finalize")), 0)

            final = root / "final"
            summary = json.loads((final / "summary.json").read_text())
            errors = json.loads((final / "errors.json").read_text())
            row_errors = [
                item
                for item in errors
                if item["error_code"] == "participant_status_unresolved"
            ]
            self.assertEqual(summary["outcome"], "partial")
            self.assertEqual(summary["counts"]["participant_rows"], 0)
            self.assertEqual(
                summary["counts"]["participant_status_unresolved"], 2
            )
            self.assertEqual(
                summary["coverage_by_region"]["france"], "partial_error"
            )
            self.assertEqual(
                {
                    (
                        item["horse_display_name"],
                        item["raw_finish_status"],
                        item["region"],
                        item["country"],
                        item["source_url"],
                    )
                    for item in row_errors
                },
                {
                    (
                        "Unknown One",
                        "MYSTERY",
                        "france",
                        "france",
                        race_url,
                    ),
                    (
                        "Unknown Two",
                        "?",
                        "france",
                        "france",
                        race_url,
                    ),
                },
            )
            with (final / "race_participants_2025.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                self.assertEqual(list(csv.DictReader(handle)), [])
            self.assertEqual(RouteClient.calls, [sitemap_url, race_url])

    def test_region_unresolved_completes_dag_with_structured_coverage_error(self):
        collector = load_collector(self)
        sitemap_url = "https://umafans.run/sitemap.xml"
        race_url = "https://umafans.run/races/2025/unresolved-region/"
        RouteClient.routes = {
            sitemap_url: (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{race_url}</loc></url></urlset>"
            ),
            race_url: current_race_template_html(region="其他"),
        }
        RouteClient.calls = []
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            collector, "HttpClient", RouteClient
        ):
            root = Path(raw)

            def args(stage, *extra):
                return collector.parse_args(
                    [
                        "--year",
                        "2025",
                        "--stage",
                        stage,
                        "--base-url",
                        "https://umafans.run/",
                        "--output-dir",
                        str(root),
                        *extra,
                    ]
                )

            self.assertEqual(collector.run_stage(args("races")), 0)
            for shard in range(4):
                self.assertEqual(
                    collector.run_stage(
                        args(
                            "profiles",
                            "--shard-index",
                            str(shard),
                            "--shard-count",
                            "4",
                        )
                    ),
                    0,
                )
            self.assertEqual(collector.run_stage(args("merge_profiles")), 0)
            self.assertEqual(collector.run_stage(args("finalize")), 0)

            final = root / "final"
            summary = json.loads((final / "summary.json").read_text())
            errors = json.loads((final / "errors.json").read_text())
            sources = [
                json.loads(line)
                for line in (final / "source_manifest.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual(summary["outcome"], "partial")
            self.assertEqual(
                summary["other_coverage"]["coverage_status"],
                "classification_incomplete",
            )
            self.assertEqual(set(summary["coverage_by_region"].values()), {"partial_error"})
            self.assertEqual(
                [
                    {
                        key: item.get(key)
                        for key in (
                            "error_code",
                            "skip_reason",
                            "page_region",
                            "region",
                            "country",
                            "source_url",
                        )
                    }
                    for item in errors
                    if item.get("error_code") == "region_unresolved"
                ],
                [
                    {
                        "error_code": "region_unresolved",
                        "skip_reason": "region_unresolved",
                        "page_region": "其他",
                        "region": "",
                        "country": "",
                        "source_url": race_url,
                    }
                ],
            )
            self.assertEqual(sources[0]["url"], race_url)
            self.assertEqual(sources[0]["region_label"], "其他")
            self.assertEqual(sources[0]["region"], "")
            self.assertIsNone(sources[0]["country"])
            self.assertEqual(RouteClient.calls, [sitemap_url, race_url])

    def test_middle_east_manifest_requires_exact_page_country(self):
        collector = load_collector(self)
        race_url = "https://umafans.run/races/2025/middle-east-country/"
        countries = (
            ("阿联酋", "united_arab_emirates"),
            ("沙特阿拉伯", "saudi_arabia"),
            ("卡塔尔", "qatar"),
            ("巴林", "bahrain"),
        )

        def manifest(country):
            return {
                "schema_version": 1,
                "year": 2025,
                "classification_complete": True,
                "races": [
                    {
                        "url": race_url,
                        "region": "middle_east",
                        "country": country,
                        "evidence": "reviewed exact country",
                    }
                ],
            }

        for page_label, page_country in countries:
            for _, manifest_country in countries:
                with self.subTest(
                    page=page_country, manifest=manifest_country
                ):
                    if page_country == manifest_country:
                        parsed = collector.parse_race_html(
                            current_race_template_html(region=page_label),
                            url=race_url,
                            year=2025,
                            region_manifest=manifest(manifest_country),
                        )
                        self.assertEqual(parsed["status"], "success")
                        self.assertEqual(
                            parsed["source"]["country"], page_country
                        )
                    else:
                        with self.assertRaisesRegex(
                            ValueError, "country|manifest"
                        ):
                            collector.parse_race_html(
                                current_race_template_html(
                                    region=page_label
                                ),
                                url=race_url,
                                year=2025,
                                region_manifest=manifest(manifest_country),
                            )
        with self.assertRaisesRegex(ValueError, "country|manifest"):
            collector.parse_race_html(
                current_race_template_html(region="中东"),
                url=race_url,
                year=2025,
                region_manifest=manifest("united_arab_emirates"),
            )

    def test_write_ahead_request_ledger_survives_transport_crash(self):
        collector = load_collector(self)

        class ProcessCrash(BaseException):
            pass

        class Response:
            status = 200
            headers = {}

            def read(self):
                return b"ok"

            def geturl(self):
                return "https://umafans.run/healthz/"

        class CrashOpener:
            calls = 0

            def open(self, *_args, **_kwargs):
                type(self).calls += 1
                raise ProcessCrash()

        class SuccessOpener:
            calls = 0

            def open(self, *_args, **_kwargs):
                type(self).calls += 1
                return Response()

        with tempfile.TemporaryDirectory() as raw:
            store = collector.StageStore(
                Path(raw),
                stage="profiles",
                year=2025,
                shard_index=2,
                shard_count=4,
                manifest_sha256="manifest",
                request_budget=2,
                input_keys_sha256=collector.keys_sha256(["horse"]),
                tool_identity={"tool": "frozen"},
            )
            ledger = store.request_ledger()
            ledger.initialize(0)
            first = collector.HttpClient(
                delay=0,
                timeout=1,
                request_budget=2,
                request_count_start=0,
                request_reserver=ledger.reserve,
            )
            first.opener = CrashOpener()
            with self.assertRaises(ProcessCrash):
                first.get("https://umafans.run/healthz/")
            self.assertEqual(ledger.verify()["request_count"], 1)
            self.assertEqual(collector.trusted_stage_request_count(store), 1)

            resumed = collector.HttpClient(
                delay=0,
                timeout=1,
                request_budget=2,
                request_count_start=1,
                request_reserver=ledger.reserve,
            )
            resumed.opener = SuccessOpener()
            resumed.get("https://umafans.run/healthz/")
            with self.assertRaises(collector.RequestBudgetExceeded):
                resumed.get("https://umafans.run/healthz/")
            self.assertEqual(ledger.verify()["request_count"], 2)
            self.assertEqual(CrashOpener.calls + SuccessOpener.calls, 2)

    def test_request_ledger_identity_and_count_rollback_fail_closed(self):
        collector = load_collector(self)
        with tempfile.TemporaryDirectory() as raw:
            store = collector.StageStore(
                Path(raw),
                stage="races",
                year=2025,
                manifest_sha256="manifest",
                request_budget=3,
                input_keys_sha256=collector.keys_sha256(["race"]),
                tool_identity={"tool": "frozen"},
            )
            ledger = store.request_ledger()
            ledger.initialize(0)
            ledger.reserve()
            store.save_item("race", {"key": "race", "status": "retryable_error"})
            index = store.rebuild_index(request_count=1)
            collector.atomic_write_json(
                store.progress_path,
                {
                    "safe_stopped": True,
                    "processed": 1,
                    "request_count": 1,
                    "index_sha256": collector.sha256_bytes(
                        store.index_path.read_bytes()
                    ),
                },
            )
            payload = ledger.verify()
            payload["request_count"] = 0
            collector.atomic_write_json(ledger.path, payload)
            with self.assertRaisesRegex(ValueError, "rollback|request count"):
                collector.trusted_stage_request_count(store)
            payload["request_count"] = 1
            payload["manifest_sha256"] = "tampered"
            collector.atomic_write_json(ledger.path, payload)
            with self.assertRaisesRegex(ValueError, "identity|manifest"):
                ledger.verify()

    def test_profile_detail_region_and_country_must_match_occurrence(self):
        collector = load_collector(self)
        search_url = profile_search_url("Drift Horse")
        detail_url = "https://umafans.run/horses/42/"
        RouteClient.routes = {
            search_url: current_horse_search_html(
                display_name="Drift Horse",
                original_name="Drift Horse",
                region_label="法国",
            ),
            detail_url: current_horse_detail_html(
                display_name="Drift Horse",
                original_name="Drift Horse",
                region_label="德国",
                country="germany",
                birth_year=2020,
            ),
        }
        RouteClient.calls = []
        drift = collector.fetch_profile(
            RouteClient(),
            base_url="https://umafans.run/",
            occurrences=[
                {
                    "region": "france",
                    "country": "france",
                    "horse_display_name": "Drift Horse",
                    "profile_url": "",
                }
            ],
        )
        self.assertNotEqual(drift["resolution_state"], "resolved")

        for region_label, country in (("德国", "germany"), ("中东", "")):
            with self.subTest(region_label=region_label, country=country):
                RouteClient.routes = {
                    detail_url: current_horse_detail_html(
                        display_name="Direct Horse",
                        original_name="Direct Horse",
                        region_label=region_label,
                        country=country,
                        birth_year=2020,
                    )
                }
                RouteClient.calls = []
                result = collector.fetch_profile(
                    RouteClient(),
                    base_url="https://umafans.run/",
                    occurrences=[
                        {
                            "region": "middle_east",
                            "country": "united_arab_emirates",
                            "horse_display_name": "Direct Horse",
                            "profile_url": detail_url,
                        }
                    ],
                )
                self.assertNotEqual(result["resolution_state"], "resolved")

    def test_non_live_manually_reviewed_result_heading_is_trusted(self):
        collector = load_collector(self)
        parsed = collector.parse_race_html(
            current_race_template_html(result_heading="已人工审核赛果"),
            url="https://umafans.run/races/2025/manually-reviewed/",
            year=2025,
        )
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["source"]["result_phase"], "static_final")
        with self.assertRaisesRegex(ValueError, "final"):
            collector.parse_race_html(
                current_race_template_html(result_heading="最新赛果"),
                url="https://umafans.run/races/2025/untrusted-heading/",
                year=2025,
            )

    def test_provisional_result_is_structured_partial_coverage_error(self):
        collector = load_collector(self)
        parsed = collector.parse_race_html(
            current_race_template_html(
                region="法国", result_phase="provisional"
            ),
            url="https://umafans.run/races/2025/provisional-france/",
            year=2025,
        )
        parsed["key"] = "https://umafans.run/races/2025/provisional-france/"
        self.assertEqual(parsed["status"], "evidence_gap")
        self.assertEqual(parsed["error_code"], "result_not_final")
        errors = collector._structured_errors([("races", [parsed])])
        self.assertEqual(errors[0]["error_code"], "result_not_final")
        self.assertEqual(errors[0]["region"], "france")
        with tempfile.TemporaryDirectory() as raw:
            summary = collector.finalize_artifacts(
                output_dir=Path(raw),
                year=2025,
                occurrences=[],
                profiles=[],
                source_manifest=[parsed["source"]],
                errors=errors,
                other_coverage=collector.classify_other_coverage(
                    year=2025,
                    discovered_other_urls=[],
                    manifest={
                        "schema_version": 1,
                        "year": 2025,
                        "classification_complete": True,
                        "races": [],
                    },
                ),
                request_count=1,
                generated_at="2025-01-01T00:00:00+00:00",
            )
            self.assertEqual(summary["outcome"], "partial")
            self.assertEqual(
                summary["coverage_by_region"]["france"], "partial_error"
            )
            self.assertEqual(
                summary["coverage_by_region"]["united_kingdom"],
                "no_public_in_scope_races",
            )
            written = json.loads((Path(raw) / "errors.json").read_text())
            self.assertEqual(written[0]["error_code"], "result_not_final")

    def test_http_status_classification_and_profile_404(self):
        collector = load_collector(self)

        class ErrorOpener:
            def __init__(self, status):
                self.status = status
                self.calls = 0

            def open(self, request, **_kwargs):
                self.calls += 1
                raise HTTPError(
                    request.full_url,
                    self.status,
                    "error",
                    {},
                    io.BytesIO(b"error"),
                )

        for status, exception, calls in (
            (403, "PermanentHttpError", 1),
            (429, "RetryableHttpError", 5),
            (500, "RetryableHttpError", 5),
        ):
            with self.subTest(status=status), mock.patch.object(
                collector.time, "sleep"
            ):
                client = collector.HttpClient(
                    delay=0, timeout=1, request_budget=5
                )
                opener = ErrorOpener(status)
                client.opener = opener
                with self.assertRaises(getattr(collector, exception)):
                    client.get("https://umafans.run/healthz/")
                self.assertEqual(opener.calls, calls)

        client = collector.HttpClient(delay=0, timeout=1, request_budget=1)
        client.opener = ErrorOpener(404)
        profile = collector.fetch_profile(
            client,
            base_url="https://umafans.run/",
            occurrences=[
                {
                    "region": "france",
                    "country": "france",
                    "horse_display_name": "Missing Horse",
                    "profile_url": "https://umafans.run/horses/404/",
                }
            ],
        )
        self.assertEqual(profile["resolution_state"], "not_found")

    def test_errors_json_contains_deduplicated_composable_name_issues(self):
        collector = load_collector(self)
        occurrence = {
            "region": "france",
            "country": "france",
            "horse_display_name": "Example",
            "profile_url": "https://umafans.run/horses/42/",
            "race_url": "https://umafans.run/races/2025/example/",
            "race_date": "2025-01-01",
            "horse_number": "1",
            "participant_status": "finished",
            "normalized_finish_position": 1,
        }
        key = collector.canonical_horse_key(occurrence)
        duplicate = {
            "stage": "races",
            "key": "race",
            "status": "permanent_error",
            "error_code": "broken",
            "error": "broken",
        }
        with tempfile.TemporaryDirectory() as raw:
            collector.finalize_artifacts(
                output_dir=Path(raw),
                year=2025,
                occurrences=[occurrence],
                profiles=[
                    {
                        "key": key,
                        "lookup_keys": [key],
                        "profile_url": occurrence["profile_url"],
                        "resolution_state": "resolved",
                        "name_zh": "",
                        "name_ja": "",
                        "name_en": "",
                    }
                ],
                source_manifest=[],
                errors=[duplicate, duplicate],
                other_coverage=collector.classify_other_coverage(
                    year=2025, discovered_other_urls=[], manifest=None
                ),
                request_count=0,
                generated_at="2025-01-01T00:00:00+00:00",
            )
            errors = json.loads((Path(raw) / "errors.json").read_text())
            codes = [item["error_code"] for item in errors]
            self.assertEqual(codes.count("broken"), 1)
            self.assertEqual(
                set(codes),
                {
                    "broken",
                    "missing_chinese",
                    "missing_japanese",
                    "missing_required_english",
                },
            )
            self.assertEqual(
                codes,
                sorted(codes),
            )

    def test_request_budget_is_cumulative_across_retries_and_resumes(self):
        collector = load_collector(self)

        class Response:
            status = 200
            headers = {}

            def read(self):
                return b"ok"

            def geturl(self):
                return "https://umafans.run/healthz/"

        class Opener:
            calls = 0

            def open(self, *_args, **_kwargs):
                type(self).calls += 1
                return Response()

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            keys = ["a", "b"]

            def store():
                return collector.StageStore(
                    root,
                    stage="profiles",
                    year=2025,
                    shard_index=0,
                    shard_count=1,
                    manifest_sha256="m",
                    request_budget=3,
                    input_keys_sha256=collector.keys_sha256(keys),
                    tool_identity={"tool": "frozen"},
                )

            attempts = {"a": 0}

            def workflow_run():
                stage_store = store()
                prior = collector.trusted_stage_request_count(stage_store)
                client = collector.HttpClient(
                    delay=0,
                    timeout=1,
                    request_budget=3,
                    request_count_start=prior,
                    request_reserver=stage_store.request_ledger().reserve,
                )
                client.opener = Opener()

                def process(key):
                    client.get("https://umafans.run/healthz/")
                    if key == "a" and attempts["a"] == 0:
                        attempts["a"] += 1
                        raise RuntimeError("temporary")
                    return {"key": key, "status": "success"}

                return collector.run_checkpointed_items(
                    keys,
                    store=stage_store,
                    process=process,
                    resume=True,
                    request_counter=lambda: client.request_count,
                    request_counter_start=prior,
                    now=lambda: "2025-01-01T00:00:00+00:00",
                )

            first = workflow_run()
            self.assertTrue(first["safe_stopped"])
            self.assertEqual(first["request_count"], 2)
            second = workflow_run()
            self.assertFalse(second["safe_stopped"])
            self.assertEqual(second["request_count"], 3)
            third = workflow_run()
            self.assertFalse(third["safe_stopped"])
            self.assertEqual(third["request_count"], 3)
            self.assertEqual(Opener.calls, 3)

    def test_request_budget_checkpoint_count_drift_fails_closed(self):
        collector = load_collector(self)
        with tempfile.TemporaryDirectory() as raw:
            store = collector.StageStore(
                Path(raw),
                stage="races",
                year=2025,
                manifest_sha256="m",
                request_budget=2,
                input_keys_sha256=collector.keys_sha256(["race"]),
                tool_identity={"tool": "frozen"},
            )
            ledger = store.request_ledger()
            ledger.initialize(0)
            ledger.reserve()
            store.save_item("race", {"key": "race", "status": "retryable_error"})
            index = store.rebuild_index(request_count=1)
            collector.atomic_write_json(
                store.progress_path,
                {
                    "safe_stopped": True,
                    "processed": 1,
                    "request_count": 0,
                    "index_sha256": collector.sha256_bytes(
                        store.index_path.read_bytes()
                    ),
                },
            )
            with self.assertRaisesRegex(ValueError, "request count"):
                collector.trusted_stage_request_count(store)
            index["request_count"] = 3
            collector.atomic_write_json(store.index_path, index)
            with self.assertRaisesRegex(ValueError, "request count"):
                store.verify_index()

    def test_current_template_provisional_is_not_formal_participant_evidence(self):
        collector = load_collector(self)
        provisional = collector.parse_race_html(
            current_race_template_html(result_phase="provisional"),
            url="https://umafans.run/races/2025/provisional/",
            year=2025,
        )
        self.assertEqual(provisional["status"], "evidence_gap")
        self.assertEqual(provisional["error_code"], "result_not_final")
        official = collector.parse_race_html(
            current_race_template_html(result_phase="official"),
            url="https://umafans.run/races/2025/official/",
            year=2025,
        )
        self.assertEqual(official["status"], "success")
        self.assertEqual(len(official["rows"]), 1)
        with self.assertRaisesRegex(ValueError, "phase"):
            collector.parse_race_html(
                current_race_template_html(result_phase="unknown"),
                url="https://umafans.run/races/2025/unknown/",
                year=2025,
            )

    def test_profile_search_matches_controlled_original_name_alias(self):
        collector = load_collector(self)
        search_url = profile_search_url("English Star")
        detail_url = "https://umafans.run/horses/42/"
        RouteClient.routes = {
            search_url: current_horse_search_html(
                display_name="中文星",
                original_name="English Star",
                region_label="法国",
            ),
            detail_url: current_horse_detail_html(
                display_name="中文星",
                original_name="English Star",
                region_label="法国",
                country="france",
                birth_year=2020,
            ),
        }
        RouteClient.calls = []
        result = collector.fetch_profile(
            RouteClient(),
            base_url="https://umafans.run/",
            occurrences=[
                {
                    "region": "france",
                    "country": "france",
                    "horse_display_name": "English Star",
                    "original_name": "English Star",
                    "profile_url": "",
                }
            ],
        )
        self.assertEqual(result["resolution_state"], "resolved")
        self.assertEqual(result["display_name"], "中文星")
        self.assertEqual(RouteClient.calls, [search_url, detail_url])

    def test_profile_search_follows_safe_pagination_before_matching(self):
        collector = load_collector(self)
        search_url = profile_search_url("English Star")
        page_two = "https://umafans.run/horses/?q=English+Star&page=2"
        detail_url = "https://umafans.run/horses/42/"
        first_cards = [
            (f"干扰马{index}", f"Decoy {index}", "法国", f"/horses/{index}/")
            for index in range(1, 25)
        ]
        RouteClient.routes = {
            search_url: horse_search_page(
                first_cards, next_href="?q=English+Star&amp;page=2"
            ),
            page_two: horse_search_page(
                [("中文星", "English Star", "法国", "/horses/42/")]
            ),
            detail_url: current_horse_detail_html(
                display_name="中文星",
                original_name="English Star",
                region_label="法国",
                country="france",
                birth_year=2020,
            ),
        }
        RouteClient.calls = []
        result = collector.fetch_profile(
            RouteClient(),
            base_url="https://umafans.run/",
            occurrences=[
                {
                    "region": "france",
                    "country": "france",
                    "horse_display_name": "English Star",
                    "original_name": "English Star",
                    "profile_url": "",
                }
            ],
        )
        self.assertEqual(result["resolution_state"], "resolved")
        self.assertEqual(RouteClient.calls, [search_url, page_two, detail_url])

    def test_profile_search_rejects_malicious_and_cyclic_next_links(self):
        collector = load_collector(self)
        search_url = profile_search_url("English Star")
        occurrence = [
            {
                "region": "france",
                "country": "france",
                "horse_display_name": "English Star",
                "profile_url": "",
            }
        ]
        for next_href, message in (
            ("https://evil.example/horses/?page=2", "allowed"),
            ("?q=English+Star", "cycle|duplicate"),
        ):
            with self.subTest(next_href=next_href):
                RouteClient.routes = {
                    search_url: horse_search_page([], next_href=next_href)
                }
                RouteClient.calls = []
                with self.assertRaisesRegex(ValueError, message):
                    collector.fetch_profile(
                        RouteClient(),
                        base_url="https://umafans.run/",
                        occurrences=occurrence,
                    )
                self.assertEqual(RouteClient.calls, [search_url])

    def test_real_http_client_follows_validated_profile_search_pagination(self):
        collector = load_collector(self)
        first_url = "https://umafans.run/horses/?q=English+Star"
        page_two = f"{first_url}&page=2"
        detail_url = "https://umafans.run/horses/42/"
        first_cards = [
            (f"干扰马{index}", f"Decoy {index}", "法国", f"/horses/{index}/")
            for index in range(1, 25)
        ]
        routes = {
            first_url: horse_search_page(
                first_cards, next_href="?q=English+Star&amp;page=2"
            ),
            page_two: horse_search_page(
                [("中文星", "English Star", "法国", "/horses/42/")]
            ),
            detail_url: current_horse_detail_html(
                display_name="中文星",
                original_name="English Star",
                region_label="法国",
                country="france",
                birth_year=2020,
            ),
        }

        class OpenerResponse:
            status = 200
            headers = {}

            def __init__(self, body, url):
                self._body = body.encode()
                self._url = url

            def read(self):
                return self._body

            def geturl(self):
                return self._url

        class Opener:
            def __init__(self):
                self.calls = []

            def open(self, request, timeout):
                url = request.full_url
                self.calls.append(url)
                if url not in routes:
                    raise AssertionError(f"unexpected request: {url}")
                return OpenerResponse(routes[url], url)

        client = collector.HttpClient(delay=0, timeout=1, request_budget=3)
        opener = Opener()
        client.opener = opener
        result = collector.fetch_profile(
            client,
            base_url="https://umafans.run/",
            occurrences=[
                {
                    "region": "france",
                    "country": "france",
                    "horse_display_name": "English Star",
                    "original_name": "English Star",
                    "profile_url": "",
                }
            ],
        )
        self.assertEqual(result["resolution_state"], "resolved")
        self.assertEqual(opener.calls, [first_url, page_two, detail_url])

    def test_request_url_allows_only_bounded_horse_search_query(self):
        collector = load_collector(self)
        allowed = "https://umafans.run/horses/?q=English+Star&page=100"
        self.assertEqual(
            collector.validate_request_url(
                allowed, allow_horse_search_query=True
            ),
            allowed,
        )
        rejected = (
            "https://umafans.run/races/?q=English+Star",
            "https://umafans.run/horses/?page=2",
            "https://umafans.run/horses/?q=",
            "https://umafans.run/horses/?q=English+Star&extra=1",
            "https://umafans.run/horses/?q=English+Star&q=Other",
            "https://umafans.run/horses/?q=English+Star&page=2&page=3",
            "https://umafans.run/horses/?q=English+Star&page=0",
            "https://umafans.run/horses/?q=English+Star&page=101",
            "https://umafans.run/horses/?q=English+Star&page=-1",
            "https://umafans.run/horses/?q=English+Star#fragment",
            "https://evil.example/horses/?q=English+Star",
            "https://umafans.run/horses/%2e%2e/races/?q=English+Star",
            "https://umafans.run/horses/?%71=English+Star",
        )
        for url in rejected:
            with self.subTest(url=url):
                client = collector.HttpClient(
                    delay=0, timeout=1, request_budget=1
                )
                client.opener = mock.Mock()
                with self.assertRaises(ValueError):
                    client.get(url)
                client.opener.open.assert_not_called()
                self.assertEqual(client.request_count, 0)

    def test_current_public_http_origin_preserves_scheme_across_urls(self):
        collector = load_collector(self)
        self.assertEqual(
            collector.validate_request_url(
                "http://UMAFANS.RUN/sitemap.xml"
            ),
            "http://umafans.run/sitemap.xml",
        )
        self.assertEqual(
            collector.validate_profile_url(
                "http://umafans.run/horses/42"
            ),
            "http://umafans.run/horses/42/",
        )
        self.assertEqual(
            collector.resolve_profile_href(
                "/horses/42/",
                base_url="http://umafans.run/races/2025/example/",
            ),
            "http://umafans.run/horses/42/",
        )
        with self.assertRaisesRegex(ValueError, "scheme drift"):
            collector.resolve_profile_href(
                "https://umafans.run/horses/42/",
                base_url="http://umafans.run/races/2025/example/",
            )
        for invalid in (
            "ftp://umafans.run/sitemap.xml",
            "http://evil.example/sitemap.xml",
            "http://umafans.run:8080/sitemap.xml",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                collector.validate_request_url(invalid)

    def test_current_public_http_sitemap_discovers_http_race_urls(self):
        collector = load_collector(self)
        root_url = "http://umafans.run/sitemap.xml"
        shard_url = "http://umafans.run/sitemaps/races-1.xml"
        target_race = "http://umafans.run/races/2025/target/"
        routes = {
            root_url: (
                '<?xml version="1.0"?>'
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<sitemap><loc>{shard_url}</loc></sitemap>"
                "</sitemapindex>"
            ),
            shard_url: (
                '<?xml version="1.0"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{target_race}</loc></url>"
                "</urlset>"
            ),
        }

        class Client:
            request_count = 0

            def get(self, url):
                self.request_count += 1
                return FakeResponse(routes[url], url)

        self.assertEqual(
            collector.discover_race_urls(
                Client(), base_url="http://umafans.run/", year=2025
            ),
            [target_race],
        )
        cross_scheme_routes = {
            root_url: routes[root_url].replace(
                shard_url, "https://umafans.run/sitemaps/races-1.xml"
            )
        }

        class CrossSchemeClient:
            request_count = 0

            def get(self, url):
                self.request_count += 1
                return FakeResponse(cross_scheme_routes[url], url)

        with self.assertRaisesRegex(ValueError, "scheme drift"):
            collector.discover_race_urls(
                CrossSchemeClient(),
                base_url="http://umafans.run/",
                year=2025,
            )

    def test_run_and_region_manifests_reject_mixed_schemes(self):
        collector = load_collector(self)
        https_race = "https://umafans.run/races/2025/example/"
        with self.assertRaisesRegex(ValueError, "scheme drift"):
            collector.validate_region_manifest(
                {
                    "schema_version": 1,
                    "year": 2025,
                    "classification_complete": False,
                    "races": [
                        {
                            "url": https_race,
                            "region": "germany",
                            "country": "germany",
                            "evidence": "reviewed identity",
                        }
                    ],
                },
                year=2025,
                expected_scheme="http",
            )
        manifest = collector._new_run_manifest(
            year=2025,
            base_url="http://umafans.run/",
            race_urls=[https_race],
            region_manifest_sha256="none",
            created_at="2025-01-01T00:00:00+00:00",
        )
        with self.assertRaisesRegex(ValueError, "scheme drift"):
            collector.validate_run_manifest(
                manifest,
                year=2025,
                region_manifest_sha256="none",
            )

    def test_full_network_workflow_uses_current_public_http_origin(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("--base-url http://umafans.run/", workflow)
        self.assertNotIn("--base-url https://umafans.run/", workflow)

    def test_complete_other_manifest_reports_each_region_independently(self):
        collector = load_collector(self)
        australia_url = "http://umafans.run/races/2025/australia-cup/"
        other = collector.classify_other_coverage(
            year=2025,
            discovered_other_urls=[australia_url],
            in_scope_urls=[australia_url],
            manifest={
                "schema_version": 1,
                "year": 2025,
                "classification_complete": True,
                "races": [
                    {
                        "url": australia_url,
                        "region": "australia",
                        "country": "australia",
                        "evidence": "reviewed race identity",
                    }
                ],
            },
        )
        coverage = collector.coverage_by_region(
            occurrences=[{"region": "australia"}],
            other_coverage=other,
            errors=[],
        )
        self.assertEqual(other["coverage_status"], "covered")
        self.assertEqual(coverage["australia"], "covered")
        self.assertEqual(coverage["germany"], "no_public_in_scope_races")
        self.assertEqual(coverage["middle_east"], "no_public_in_scope_races")
        self.assertNotIn("classification_incomplete", set(coverage.values()))

    def test_public_runner_status_labels_are_complete_and_numeric_is_fullmatch(self):
        collector = load_collector(self)
        kept = {
            "完赛": "finished",
            "并列": "finished",
            "失格": "disqualified_after_start",
            "未完赛": "started_non_finish",
            "中止": "started_non_finish",
            "骑师落马": "started_non_finish",
            "跌倒": "started_non_finish",
            "拒跑": "started_non_finish",
        }
        for raw, expected in kept.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    collector.normalize_participant_status(raw), (expected, None)
                )
        for raw in ("退赛", "取消出走", "未出赛"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    collector.normalize_participant_status(raw),
                    ("non_starter", None),
                )
        for raw in ("已出走登记", "进行中", "恢复出走", "未知", "1abc", "1 DNF"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    collector.normalize_participant_status(raw), ("unresolved", None)
                )
        parsed = collector.parse_race_html(
            current_race_template_html(
                rows=[
                    ("1", "1", "Winner"),
                    ("骑师落马", "2", "Unseated"),
                    ("取消出走", "3", "Withdrawn"),
                    ("未出赛", "4", "Non Runner"),
                ]
            ),
            url="https://umafans.run/races/2025/current-template/",
            year=2025,
            fetched_at="2025-06-02T00:00:00+00:00",
        )
        self.assertEqual(
            [row["participant_status"] for row in parsed["rows"]],
            ["finished", "started_non_finish"],
        )
        self.assertEqual(parsed["non_starters_excluded"], 2)

    def test_retryable_completed_checkpoint_is_retried_on_next_run(self):
        collector = load_collector(self)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            identity = {"tool": "frozen"}
            kwargs = {
                "stage": "profiles",
                "year": 2025,
                "shard_index": 0,
                "shard_count": 1,
                "manifest_sha256": "m",
                "region_manifest_sha256": "none",
                "input_keys_sha256": collector.keys_sha256(["horse"]),
                "tool_identity": identity,
            }
            first = collector.StageStore(root, **kwargs)
            first_progress = collector.run_checkpointed_items(
                ["horse"],
                store=first,
                process=lambda key: {
                    "key": key,
                    "status": "retryable_error",
                    "error_code": "temporary",
                },
                resume=True,
                now=lambda: "2025-01-01T00:00:00+00:00",
            )
            self.assertTrue(first_progress["safe_stopped"])
            calls = []
            resumed = collector.StageStore(root, **kwargs)
            progress = collector.run_checkpointed_items(
                ["horse"],
                store=resumed,
                process=lambda key: calls.append(key)
                or {"key": key, "status": "success", "value": "recovered"},
                resume=True,
                now=lambda: "2025-01-01T00:00:00+00:00",
            )
            self.assertEqual(calls, ["horse"])
            self.assertEqual(progress["success"], 1)
            self.assertEqual(resumed.load_item("horse")["value"], "recovered")

    def test_safe_stop_artifact_resumes_to_byte_equivalent_success(self):
        collector = load_collector(self)
        keys = ["a", "b"]
        identity = {"tool": "frozen"}

        def store_at(root):
            return collector.StageStore(
                root,
                stage="races",
                year=2025,
                shard_index=0,
                shard_count=1,
                manifest_sha256="m",
                region_manifest_sha256="none",
                request_budget=10,
                input_keys_sha256=collector.keys_sha256(keys),
                tool_identity=identity,
            )

        def record(key):
            return {"key": key, "status": "success", "payload": [key]}

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            interrupted = store_at(root / "interrupted")
            calls = []

            def stop_after_one(key):
                calls.append(key)
                if len(calls) == 2:
                    raise collector.RequestBudgetExceeded("budget")
                return record(key)

            first = collector.run_checkpointed_items(
                keys,
                store=interrupted,
                process=stop_after_one,
                resume=True,
                now=lambda: "2025-01-01T00:00:00+00:00",
            )
            self.assertTrue(first["safe_stopped"])
            resumed = collector.run_checkpointed_items(
                keys,
                store=store_at(root / "interrupted"),
                process=record,
                resume=True,
                now=lambda: "2025-01-01T00:00:00+00:00",
            )
            self.assertFalse(resumed["safe_stopped"])
            baseline = store_at(root / "baseline")
            collector.run_checkpointed_items(
                keys,
                store=baseline,
                process=record,
                resume=True,
                now=lambda: "2025-01-01T00:00:00+00:00",
            )
            recovered_bytes = {
                path.name: path.read_bytes()
                for path in interrupted.items_dir.glob("*.json")
            }
            baseline_bytes = {
                path.name: path.read_bytes()
                for path in baseline.items_dir.glob("*.json")
            }
            self.assertEqual(recovered_bytes, baseline_bytes)

    def test_finalize_merges_occurrences_that_resolve_to_one_profile(self):
        collector = load_collector(self)
        occurrences = [
            {
                "region": "united_kingdom",
                "country": "united_kingdom",
                "horse_display_name": (
                    "Test Horse" if index == 1 else "Test Horse (GB)"
                ),
                "original_name": "",
                "profile_url": "",
                "race_url": f"https://umafans.run/races/2025/race-{index}/",
                "race_date": f"2025-06-0{index}",
                "normalized_finish_position": index,
                "participant_status": "finished",
                "horse_number": str(index),
            }
            for index in (1, 2)
        ]
        lookup_keys = [collector.canonical_horse_key(row) for row in occurrences]
        self.assertEqual(len(set(lookup_keys)), 2)
        profiles = [
            {
                "key": "profile|https://umafans.run/horses/42/",
                "lookup_keys": lookup_keys,
                "profile_url": "https://umafans.run/horses/42/",
                "resolution_state": "resolved",
                "name_zh": "测试马",
                "name_ja": "テストホース",
                "name_en": "Test Horse",
                "status": "success",
            }
        ]
        with tempfile.TemporaryDirectory() as raw:
            summary = collector.finalize_artifacts(
                output_dir=Path(raw),
                year=2025,
                occurrences=occurrences,
                profiles=profiles,
                source_manifest=[],
                errors=[],
                other_coverage=collector.classify_other_coverage(
                    year=2025, discovered_other_urls=[], manifest=None
                ),
                request_count=0,
                generated_at="2025-01-01T00:00:00+00:00",
            )
            self.assertEqual(summary["counts"]["participant_rows"], 2)
            self.assertEqual(summary["counts"]["unique_horses"], 1)
            self.assertEqual(summary["counts"]["required_english_complete"], 1)

    def test_no_region_consistent_search_candidate_is_unresolved(self):
        collector = load_collector(self)
        search_url = profile_search_url("Same Name")
        RouteClient.routes = {
            search_url: current_horse_search_html(
                display_name="Same Name",
                original_name="Same Name",
                region_label="美国",
            )
        }
        RouteClient.calls = []
        result = collector.fetch_profile(
            RouteClient(),
            base_url="https://umafans.run/",
            occurrences=[
                {
                    "region": "france",
                    "country": "france",
                    "horse_display_name": "Same Name",
                    "profile_url": "",
                }
            ],
        )
        self.assertEqual(result["resolution_state"], "unresolved")
        self.assertEqual(RouteClient.calls, [search_url])

    def test_generic_other_profile_fetches_and_verifies_detail_facts(self):
        collector = load_collector(self)
        search_url = profile_search_url("Southern Star")
        detail_url = "https://umafans.run/horses/42/"
        RouteClient.routes = {
            search_url: current_horse_search_html(
                display_name="Southern Star",
                original_name="Southern Star",
                region_label="其他",
            ),
            detail_url: current_horse_detail_html(
                display_name="Southern Star",
                original_name="Southern Star",
                region_label="其他",
                country="australia",
                birth_year=2020,
            ),
        }
        RouteClient.calls = []
        result = collector.fetch_profile(
            RouteClient(),
            base_url="https://umafans.run/",
            occurrences=[
                {
                    "region": "australia",
                    "country": "australia",
                    "horse_display_name": "Southern Star",
                    "original_name": "Southern Star",
                    "birth_year": "2020",
                    "profile_url": "",
                }
            ],
        )
        self.assertEqual(result["resolution_state"], "resolved")
        self.assertEqual(result["birth_year"], "2020")
        self.assertEqual(result["country"], "australia")
        self.assertEqual(RouteClient.calls, [search_url, detail_url])

    def test_merge_profile_nonempty_identity_conflicts_fail_closed(self):
        collector = load_collector(self)
        for field, values in {
            "original_name": ("Horse A", "Horse B"),
            "birth_year": ("2020", "2021"),
            "country": ("france", "germany"),
        }.items():
            records = [
                {
                    "key": f"lookup-{index}",
                    "profile_url": "https://umafans.run/horses/42/",
                    "resolution_state": "resolved",
                    "status": "success",
                    field: value,
                }
                for index, value in enumerate(values)
            ]
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "conflict"
            ):
                collector.merge_profile_records(
                    records, {"lookup-0", "lookup-1"}
                )

    def test_coverage_reports_partial_error_instead_of_no_races(self):
        collector = load_collector(self)
        coverage = collector.coverage_by_region(
            occurrences=[],
            other_coverage=collector.classify_other_coverage(
                year=2025, discovered_other_urls=[], manifest=None
            ),
            errors=[
                {
                    "stage": "races",
                    "key": "https://umafans.run/races/2025/broken/",
                    "status": "retryable_error",
                }
            ],
        )
        self.assertEqual(set(coverage.values()), {"partial_error"})

    def test_region_error_takes_precedence_over_present_occurrence(self):
        collector = load_collector(self)
        coverage = collector.coverage_by_region(
            occurrences=[
                {"region": "france"},
                {"region": "united_kingdom"},
            ],
            other_coverage=collector.classify_other_coverage(
                year=2025, discovered_other_urls=[], manifest=None
            ),
            errors=[
                {
                    "stage": "races",
                    "region": "france",
                    "status": "evidence_gap",
                }
            ],
        )
        self.assertEqual(coverage["france"], "partial_error")
        self.assertEqual(coverage["united_kingdom"], "covered")

    def test_unresolved_result_error_preserves_region_and_country(self):
        collector = load_collector(self)
        source_url = "https://umafans.run/races/2025/france/"
        errors = collector._structured_errors(
            [
                (
                    "races",
                    [
                        {
                            "key": source_url,
                            "status": "success",
                            "unresolved_rows": [
                                {
                                    "region": "france",
                                    "country": "france",
                                    "race_url": source_url,
                                    "raw_finish_status": "UNKNOWN",
                                    "horse_display_name": "Mystery Horse",
                                }
                            ],
                        }
                    ],
                )
            ]
        )
        self.assertEqual(errors[0]["region"], "france")
        self.assertEqual(errors[0]["country"], "france")
        self.assertEqual(errors[0]["source_url"], source_url)

    def test_missing_japanese_is_composable_and_reviewable(self):
        collector = load_collector(self)
        record = collector.build_horse_name_record(
            [
                {
                    "region": "france",
                    "country": "france",
                    "horse_display_name": "Example",
                    "profile_url": "https://umafans.run/horses/42/",
                }
            ],
            profile={
                "resolution_state": "resolved",
                "name_zh": "",
                "name_ja": "",
                "name_en": "",
            },
        )
        self.assertEqual(
            set(record["name_issue_codes"]),
            {
                "missing_chinese",
                "missing_japanese",
                "missing_required_english",
            },
        )
        occurrence = {
            "region": "france",
            "country": "france",
            "horse_display_name": "Example",
            "profile_url": "https://umafans.run/horses/42/",
            "race_url": "https://umafans.run/races/2025/example/",
            "race_date": "2025-01-01",
            "horse_number": "1",
            "participant_status": "finished",
            "normalized_finish_position": 1,
        }
        key = collector.canonical_horse_key(occurrence)
        with tempfile.TemporaryDirectory() as raw:
            collector.finalize_artifacts(
                output_dir=Path(raw),
                year=2025,
                occurrences=[occurrence],
                profiles=[
                    {
                        "key": key,
                        "lookup_keys": [key],
                        "profile_url": occurrence["profile_url"],
                        "resolution_state": "resolved",
                        "name_zh": "",
                        "name_ja": "",
                        "name_en": "",
                    }
                ],
                source_manifest=[],
                errors=[],
                other_coverage=collector.classify_other_coverage(
                    year=2025, discovered_other_urls=[], manifest=None
                ),
                request_count=0,
                generated_at="2025-01-01T00:00:00+00:00",
            )
            queue = (
                Path(raw) / "horse_name_review_queue_2025.csv"
            ).read_text(encoding="utf-8-sig")
            self.assertIn("missing_japanese", queue)

    def test_http_request_budget_stops_before_extra_transport_call(self):
        collector = load_collector(self)

        class Response:
            status = 200
            headers = {}

            def read(self):
                return b"ok"

            def geturl(self):
                return "https://umafans.run/healthz/"

        class Opener:
            def __init__(self):
                self.calls = 0

            def open(self, *_args, **_kwargs):
                self.calls += 1
                return Response()

        client = collector.HttpClient(delay=0, timeout=1, request_budget=1)
        client.opener = Opener()
        client.get("https://umafans.run/healthz/")
        with self.assertRaisesRegex(collector.RequestBudgetExceeded, "budget"):
            client.get("https://umafans.run/healthz/")
        self.assertEqual(client.opener.calls, 1)

    def test_run_manifest_and_stage_index_bind_request_budget(self):
        collector = load_collector(self)
        parsed = collector.parse_args(
            [
                "--year",
                "2025",
                "--stage",
                "races",
                "--output-dir",
                "unused",
                "--request-budget",
                str(collector.REQUEST_BUDGETS["races"]),
            ]
        )
        self.assertEqual(
            parsed.request_budget, collector.REQUEST_BUDGETS["races"]
        )
        with self.assertRaises(SystemExit):
            collector.parse_args(
                [
                    "--year",
                    "2025",
                    "--stage",
                    "races",
                    "--output-dir",
                    "unused",
                    "--request-budget",
                    "1",
                ]
            )
        manifest = collector._new_run_manifest(
            year=2025,
            base_url="https://umafans.run/",
            race_urls=["https://umafans.run/races/2025/test/"],
            region_manifest_sha256="none",
            created_at="2025-01-01T00:00:00+00:00",
        )
        self.assertEqual(
            manifest["request_budgets"], collector.REQUEST_BUDGETS
        )
        with tempfile.TemporaryDirectory() as raw:
            store = collector.StageStore(
                Path(raw),
                stage="races",
                year=2025,
                shard_index=0,
                shard_count=1,
                manifest_sha256="m",
                request_budget=collector.REQUEST_BUDGETS["races"],
                input_keys_sha256=collector.keys_sha256(["race"]),
                tool_identity={"tool": "frozen"},
            )
            store.save_item("race", {"key": "race", "status": "success"})
            index = store.rebuild_index(request_count=1)
            self.assertEqual(
                index["request_budget"], collector.REQUEST_BUDGETS["races"]
            )

    def test_current_template_fake_transport_runs_full_stage_dag(self):
        collector = load_collector(self)
        sitemap_url = "https://umafans.run/sitemap.xml"
        race_url = "https://umafans.run/races/2025/current-shape/"
        search_url = profile_search_url("Test Horse")
        detail_url = "https://umafans.run/horses/42/"
        RouteClient.routes = {
            sitemap_url: (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{race_url}</loc></url></urlset>"
            ),
            race_url: current_race_template_html(),
            search_url: current_horse_search_html(
                display_name="Test Horse",
                original_name="Test Horse",
                region_label="英国",
            ),
            detail_url: current_horse_detail_html(
                display_name="Test Horse",
                original_name="Test Horse",
                region_label="英国",
                country="united_kingdom",
                birth_year=2020,
            ),
        }
        RouteClient.calls = []
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            collector, "HttpClient", RouteClient
        ):
            root = Path(raw)

            def args(stage, *extra):
                return collector.parse_args(
                    [
                        "--year",
                        "2025",
                        "--stage",
                        stage,
                        "--base-url",
                        "https://umafans.run/",
                        "--output-dir",
                        str(root),
                        *extra,
                    ]
                )

            self.assertEqual(collector.run_stage(args("races")), 0)
            for shard in range(4):
                self.assertEqual(
                    collector.run_stage(
                        args(
                            "profiles",
                            "--shard-index",
                            str(shard),
                            "--shard-count",
                            "4",
                        )
                    ),
                    0,
                )
            self.assertEqual(collector.run_stage(args("merge_profiles")), 0)
            self.assertEqual(collector.run_stage(args("finalize")), 0)
            summary = json.loads(
                (root / "final" / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["counts"]["participant_rows"], 1)
            self.assertEqual(summary["counts"]["unique_horses"], 1)
            self.assertEqual(summary["counts"]["profile_resolved"], 1)
            self.assertEqual(
                sorted(path.name for path in (root / "final").iterdir()),
                sorted(collector.final_filenames(2025)),
            )
            self.assertEqual(
                RouteClient.calls,
                [sitemap_url, race_url, search_url, detail_url],
            )


if __name__ == "__main__":
    unittest.main()

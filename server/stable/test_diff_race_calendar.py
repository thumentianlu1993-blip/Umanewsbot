"""官方赛历 timeline vs 既有目标快照 diff 工具（runtime/tools/diff_race_calendar.py）测试。

纯函数 + CLI 文件级测试，不触数据库。覆盖三类 diff 桶、uncovered 降级、
计数守恒自校验、空输入 fail closed 与 series_match_hint 模糊候选。
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"

TODAY = date(2026, 9, 28)


def _load():
    path = TOOLS / "diff_race_calendar.py"
    spec = importlib.util.spec_from_file_location(f"{path.stem}_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _incoming(
    series_key="ireland-irish-derby",
    *,
    region="ireland",
    year=2026,
    local_date="2026-10-17",
    racecourse="Curragh",
    grade_text="G1",
    name="Irish Derby",
    distance_text="2400",
    expectation_status="held",
):
    return {
        "record_type": "timeline",
        "country_region": region,
        "year": year,
        "series_key": series_key,
        "canonical_name_original": name,
        "original_name": name,
        "grade_text": grade_text,
        "racecourse": racecourse,
        "local_date": local_date,
        "distance_text": distance_text,
        "surface": "",
        "expectation_status": expectation_status,
        "source_scope": "official_calendar",
    }


def _existing(
    series_key="ireland-irish-derby",
    *,
    region="ireland",
    year=2026,
    local_date="2026-10-17",
    racecourse="Curragh",
    grade_text="G1",
    expectation_status="held",
    resolution_status="pending",
    name="Irish Derby",
):
    return {
        "series_key": series_key,
        "country_region": region,
        "year": year,
        "local_date": local_date,
        "racecourse": racecourse,
        "grade_text": grade_text,
        "expectation_status": expectation_status,
        "resolution_status": resolution_status,
        "original_name": name,
    }


class ComputeDiffTests(SimpleTestCase):
    """compute_diff 纯函数分类语义。"""

    def setUp(self):
        self.module = _load()

    def _diff(self, incoming, existing, *, covers=(), today=TODAY):
        return self.module.compute_diff(
            incoming_rows=incoming,
            existing_rows=existing,
            covers=covers,
            today=today,
        )

    def test_unchanged_when_three_fields_match(self):
        rows = self._diff([_incoming()], [_existing()])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["bucket"], "unchanged")
        self.assertEqual(row["country_region"], "ireland")
        self.assertEqual(row["year"], 2026)
        self.assertEqual(
            row["values"],
            {"local_date": "2026-10-17", "racecourse": "Curragh", "grade_text": "G1"},
        )

    def test_changed_lists_per_field_before_after(self):
        incoming = _incoming(local_date="2026-10-24", grade_text="G2")
        existing = _existing(local_date="2026-10-17", grade_text="G1")
        rows = self._diff([incoming], [existing])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["bucket"], "changed")
        self.assertEqual(
            row["changes"],
            {
                "local_date": {"before": "2026-10-17", "after": "2026-10-24"},
                "grade_text": {"before": "G1", "after": "G2"},
            },
        )
        self.assertEqual(row["before"]["resolution_status"], "pending")
        self.assertEqual(row["after"]["racecourse"], "Curragh")
        self.assertEqual(row["after"]["original_name"], "Irish Derby")

    def test_non_diff_field_change_is_unchanged(self):
        # distance_text 不属于 diff 字段（仅 local_date/racecourse/grade_text）
        rows = self._diff([_incoming(distance_text="2414")], [_existing()])
        self.assertEqual(rows[0]["bucket"], "unchanged")

    def test_new_year_of_known_series_has_no_hint(self):
        # 同一 series_key 在快照其他年份存在：新年度行是常规 new，不给身份映射提示；
        # 既有 2025 行在已声明覆盖的 scope 内缺失 → cancelled
        rows = self._diff(
            [_incoming(year=2026, local_date="2026-10-17")],
            [_existing(year=2025, local_date="2025-10-18")],
            covers={("ireland", 2025)},
        )
        self.assertEqual(len(rows), 2)
        by_year = {row["year"]: row for row in rows}
        self.assertEqual(by_year[2026]["bucket"], "new")
        self.assertEqual(by_year[2026]["series_match_hint"], [])
        self.assertEqual(by_year[2025]["bucket"], "cancelled")

    def test_new_hint_when_series_key_unknown(self):
        rows = self._diff(
            [_incoming(series_key="ireland-irish-derby-new", name="Irish Derby")],
            [_existing(series_key="ireland-irish-derby-old", name="Irish Derby")],
        )
        # new 行之外，既有未命中行降级 uncovered（scope 未声明覆盖）
        self.assertEqual(len(rows), 2)
        new_rows = [row for row in rows if row["bucket"] == "new"]
        self.assertEqual(len(new_rows), 1)
        row = new_rows[0]
        hint = row["series_match_hint"]
        self.assertTrue(hint)
        self.assertEqual(hint[0]["series_key"], "ireland-irish-derby-old")
        self.assertGreaterEqual(hint[0]["score"], 0.72)
        self.assertIn(hint[0]["matched_on"], {"name", "key"})
        others = [row for row in rows if row["bucket"] != "new"]
        self.assertEqual(others[0]["bucket"], "uncovered")
        self.assertEqual(others[0]["reason"], "scope_not_covered")

    def test_new_hint_for_keyless_incoming_row(self):
        rows = self._diff([_incoming(series_key="")], [_existing()])
        new_rows = [row for row in rows if row["bucket"] == "new"]
        self.assertEqual(len(new_rows), 1)
        self.assertEqual(new_rows[0]["series_key"], "")
        self.assertTrue(new_rows[0]["series_match_hint"])

    def test_cancelled_requires_declared_coverage(self):
        existing = _existing()
        incoming = [_incoming(series_key="ireland-galway-plate", name="Galway Plate")]
        # 不声明覆盖：只能降级 uncovered，绝不误判取消
        rows = self._diff(incoming, [existing])
        uncovered = next(row for row in rows if row["bucket"] == "uncovered")
        self.assertEqual(uncovered["series_key"], "ireland-irish-derby")
        self.assertEqual(uncovered["reason"], "scope_not_covered")
        # 声明覆盖后：同一行判 cancelled
        rows = self._diff(incoming, [existing], covers={("ireland", 2026)})
        cancelled = next(row for row in rows if row["bucket"] == "cancelled")
        self.assertEqual(cancelled["series_key"], "ireland-irish-derby")
        self.assertEqual(cancelled["reason"], "absent_from_covered_official_calendar")
        self.assertEqual(cancelled["existing"]["resolution_status"], "pending")

    def test_uncovered_for_non_cancellable_states(self):
        covered = {("ireland", 2026)}
        incoming = [_incoming(series_key="ireland-galway-plate", name="Galway Plate")]
        cases = [
            ({"expectation_status": "not_held"}, "uncovered"),
            ({"expectation_status": "cancelled"}, "uncovered"),
            ({"expectation_status": "not_due"}, "uncovered"),
            ({"resolution_status": "permanently_unavailable"}, "uncovered"),
            # 已物化且已完赛（local_date 已过）：不判取消
            ({"resolution_status": "imported", "local_date": "2026-01-01"}, "uncovered"),
            # 已物化未开赛（local_date 未来或未知）：可判取消
            ({"resolution_status": "ready", "local_date": "2026-12-31"}, "cancelled"),
            ({"resolution_status": "imported", "local_date": "2026-12-31"}, "cancelled"),
            ({"resolution_status": "pending"}, "cancelled"),
        ]
        for overrides, expected_bucket in cases:
            with self.subTest(overrides=overrides):
                rows = self._diff(incoming, [_existing(**overrides)], covers=covered)
                row = next(row for row in rows if row["series_key"] == "ireland-irish-derby")
                self.assertEqual(row["bucket"], expected_bucket)
                if expected_bucket == "uncovered":
                    self.assertEqual(row["reason"], "state_not_cancellable")

    def test_year_string_and_scoped_universe(self):
        # timeline year 可能是字符串；既有快照只把覆盖/涉及 scope 的行计入 diff
        incoming = _incoming(year="2026")
        out_scope = _existing(
            series_key="japan-kikuka-sho", region="japan", year=2025, name="Kikuka Sho"
        )
        rows = self._diff([incoming], [_existing(), out_scope])
        self.assertEqual(len(rows), 1)  # out-of-scope 既有行不产出 diff 行
        self.assertEqual(rows[0]["bucket"], "unchanged")
        self.assertEqual(rows[0]["year"], 2026)

    def test_empty_inputs_fail_closed(self):
        with self.assertRaises(self.module.CalendarDiffError):
            self._diff([], [_existing()])
        with self.assertRaises(self.module.CalendarDiffError):
            self._diff([_incoming()], [])
        with self.assertRaises(self.module.CalendarDiffError):
            self._diff([], [])

    def test_duplicate_incoming_identity_fails_closed(self):
        with self.assertRaises(self.module.CalendarDiffError):
            self._diff([_incoming(), _incoming()], [_existing()])

    def test_duplicate_existing_identity_fails_closed(self):
        with self.assertRaises(self.module.CalendarDiffError):
            self._diff([_incoming()], [_existing(), _existing()])

    def test_incoming_record_type_must_be_timeline(self):
        row = {**_incoming(), "record_type": "catalog"}
        with self.assertRaises(self.module.CalendarDiffError):
            self._diff([row], [_existing()])

    def test_existing_requires_region_and_year(self):
        bad = _existing()
        del bad["country_region"]
        with self.assertRaises(self.module.CalendarDiffError):
            self._diff([_incoming()], [bad])
        bad = _existing()
        bad["year"] = ""
        with self.assertRaises(self.module.CalendarDiffError):
            self._diff([_incoming()], [bad])


class GenerateDiffArtifactTests(SimpleTestCase):
    """generate_diff / CLI 文件级行为与计数守恒。"""

    def setUp(self):
        self.module = _load()

    def _write_jsonl(self, path: Path, rows):
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_csv(self, path: Path, rows):
        fieldnames = [
            "series_key", "country_region", "year", "local_date", "racecourse",
            "grade_text", "expectation_status", "resolution_status", "original_name",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_generate_diff_artifacts_and_conservation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            incoming_path = root / "incoming.jsonl"
            self._write_jsonl(
                incoming_path,
                [
                    _incoming(),  # unchanged
                    _incoming(
                        series_key="ireland-champions-stakes",
                        name="Champions Stakes",
                        local_date="2026-10-25",
                    ),  # changed（日期）
                    _incoming(
                        series_key="ireland-brand-new-race", name="Brand New Race"
                    ),  # new
                ],
            )
            existing_path = root / "existing.csv"
            self._write_csv(
                existing_path,
                [
                    _existing(),
                    _existing(
                        series_key="ireland-champions-stakes",
                        name="Champions Stakes",
                        local_date="2026-10-18",
                    ),
                    _existing(
                        series_key="ireland-retired-race", name="Retired Race"
                    ),  # covered → cancelled
                    _existing(
                        series_key="japan-kikuka-sho",
                        region="japan",
                        year=2025,
                        name="Kikuka Sho",
                    ),  # out-of-scope
                ],
            )
            out_dir = root / "out"
            summary = self.module.generate_diff(
                incoming=[("https://www.hri-ras.ie/pattern", incoming_path)],
                existing_path=existing_path,
                covers={("ireland", 2026)},
                today=TODAY,
                output_dir=out_dir,
            )
            counts = summary["counts"]
            self.assertEqual(counts["incoming_rows"], 3)
            self.assertEqual(counts["existing_rows"], 4)
            self.assertEqual(counts["existing_in_scope_rows"], 3)
            self.assertEqual(counts["existing_out_of_scope_rows"], 1)
            self.assertEqual(
                counts["buckets"],
                {"new": 1, "changed": 1, "unchanged": 1, "cancelled": 1, "uncovered": 0},
            )
            # 计数自校验：changed/unchanged 每行覆盖一对（incoming+existing）输入行，
            # new/cancelled/uncovered 每行覆盖一条；输入行数 = 加权桶行数和
            conservation = summary["conservation"]
            self.assertTrue(conservation["ok"])
            self.assertEqual(conservation["input_rows"], 3 + 3)
            self.assertEqual(conservation["weighted_bucket_rows"], 1 + 2 * (1 + 1) + 1 + 0)
            diff_path = out_dir / "calendar_diff.jsonl"
            summary_path = out_dir / "summary.json"
            self.assertTrue(diff_path.is_file())
            self.assertTrue(summary_path.is_file())
            rows = [
                json.loads(line)
                for line in diff_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 4)  # 3 scoped existing + 1 new
            self.assertEqual(
                {(row["series_key"], row["bucket"]) for row in rows},
                {
                    ("ireland-irish-derby", "unchanged"),
                    ("ireland-champions-stakes", "changed"),
                    ("ireland-brand-new-race", "new"),
                    ("ireland-retired-race", "cancelled"),
                },
            )
            identity = summary["artifacts"]["calendar_diff"]
            self.assertEqual(identity["path"], "calendar_diff.jsonl")
            self.assertEqual(
                identity["sha256"], hashlib.sha256(diff_path.read_bytes()).hexdigest()
            )
            # 已存在输出目录 fail closed
            with self.assertRaises(self.module.CalendarDiffError):
                self.module.generate_diff(
                    incoming=[("https://www.hri-ras.ie/pattern", incoming_path)],
                    existing_path=existing_path,
                    covers={("ireland", 2026)},
                    today=TODAY,
                    output_dir=out_dir,
                )

    def test_generate_diff_accepts_jsonl_existing_snapshot(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            incoming_path = root / "incoming.jsonl"
            self._write_jsonl(incoming_path, [_incoming()])
            existing_path = root / "existing.jsonl"
            self._write_jsonl(existing_path, [_existing()])
            summary = self.module.generate_diff(
                incoming=[("https://www.hri-ras.ie/pattern", incoming_path)],
                existing_path=existing_path,
                covers=set(),
                today=TODAY,
                output_dir=root / "out",
            )
            self.assertEqual(summary["counts"]["buckets"]["unchanged"], 1)

    def test_cli_main_writes_artifacts(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            incoming_path = root / "incoming.jsonl"
            self._write_jsonl(incoming_path, [_incoming()])
            existing_path = root / "existing.csv"
            self._write_csv(existing_path, [_existing()])
            out_dir = root / "out"
            exit_code = self.module.main(
                [
                    "--incoming",
                    f"https://www.hri-ras.ie/pattern={incoming_path}",
                    "--existing",
                    str(existing_path),
                    "--covers",
                    "ireland:2026",
                    "--today",
                    "2026-09-28",
                    "--output-dir",
                    str(out_dir),
                ]
            )
            self.assertEqual(exit_code, 0)
            summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["covers"], ["ireland:2026"])
            self.assertEqual(summary["counts"]["buckets"]["unchanged"], 1)

    def test_cli_rejects_bad_incoming_and_bad_covers(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            incoming_path = root / "incoming.jsonl"
            self._write_jsonl(incoming_path, [_incoming()])
            existing_path = root / "existing.csv"
            self._write_csv(existing_path, [_existing()])
            with self.assertRaises(self.module.CalendarDiffError):
                self.module.main(
                    [
                        "--incoming",
                        str(incoming_path),  # 缺 URL= 前缀
                        "--existing",
                        str(existing_path),
                        "--output-dir",
                        str(root / "out"),
                    ]
                )
            with self.assertRaises(self.module.CalendarDiffError):
                self.module.main(
                    [
                        "--incoming",
                        f"https://www.hri-ras.ie/pattern={incoming_path}",
                        "--existing",
                        str(existing_path),
                        "--covers",
                        "ireland-2026",  # 非法 scope 格式
                        "--output-dir",
                        str(root / "out2"),
                    ]
                )

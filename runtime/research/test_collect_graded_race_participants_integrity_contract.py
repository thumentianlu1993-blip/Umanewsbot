#!/usr/bin/env python3
"""年度参赛马 collector 的身份、断点与计数合同测试。"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("collect_graded_race_participants.py")


def load_collector():
    spec = importlib.util.spec_from_file_location(
        "graded_race_participants_integrity_contract", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError("collector 入口不可加载")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CollectorIntegrityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collector = load_collector()

    def test_fresh_root_rejects_existing_artifact_and_unrequested_resume(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "final").mkdir()
            (root / "final" / "summary.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "immutable output"):
                self.collector.validate_formal_output_root(
                    root, stage="races", resume=False
                )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "run_manifest.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "--resume"):
                self.collector.validate_formal_output_root(
                    root, stage="races", resume=False
                )

    def test_empty_fresh_root_and_explicit_checkpoint_resume_are_allowed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.collector.validate_formal_output_root(
                root, stage="races", resume=False
            )
            (root / "stages" / "races").mkdir(parents=True)
            (root / "stages" / "races" / "discovery_progress.json").write_text(
                "{}\n", encoding="utf-8"
            )
            self.collector.validate_formal_output_root(
                root, stage="races", resume=True
            )

    def test_old_manifest_schema_and_source_fingerprint_are_explicitly_rejected(self):
        identity = self.collector.current_tool_identity_record()
        manifest = self.collector._new_run_manifest(
            year=2025,
            base_url="https://umafans.run/",
            race_urls=["https://umafans.run/races/2025/example/"],
            region_manifest_sha256="none",
            created_at="2025-01-01T00:00:00+00:00",
        )
        for field, value in (
            ("schema_version", identity["schema_version"] - 1),
            ("collector_source_sha256", "0" * 64),
        ):
            with self.subTest(field=field):
                legacy = {**manifest, field: value}
                with self.assertRaisesRegex(
                    ValueError, "incompatible.*fresh output root.*no migration"
                ):
                    self.collector.validate_run_manifest(
                        legacy,
                        year=2025,
                        region_manifest_sha256="none",
                        expected_base_url="https://umafans.run/",
                    )

    def test_checkpoint_tool_fingerprint_mismatch_is_explicitly_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = self.collector.StageStore(
                root,
                stage="races",
                year=2025,
                shard_index=0,
                shard_count=1,
                input_keys_sha256=self.collector.keys_sha256(["race"]),
                tool_identity=self.collector.current_tool_identity_record(),
            )
            store.save_item("race", {"status": "success"})
            store.rebuild_index(request_count=0)
            index = json.loads(store.index_path.read_text(encoding="utf-8"))
            index["tool_identity"]["collector_source_sha256"] = "0" * 64
            store.index_path.write_bytes(self.collector.canonical_json_bytes(index))

            with self.assertRaisesRegex(
                ValueError, "incompatible.*fresh output root.*no migration"
            ):
                store.verify_index()

    def test_identity_and_summary_use_normalized_missing_number_fallbacks(self):
        parsed = self.collector.parse_result_rows(
            [
                {
                    "raw_finish_status": "1",
                    "horse_number": "—",
                    "horse_display_name": "Profile Horse",
                    "profile_url": "https://umafans.run/horses/101/",
                },
                {
                    "raw_finish_status": "2",
                    "horse_number": " - ",
                    "horse_display_name": "Name Horse",
                    "profile_url": "",
                },
            ]
        )
        self.assertEqual(parsed["missing_number_rows"], 2)
        self.assertEqual(parsed["profile_fallback"], 1)
        self.assertEqual(parsed["name_fallback"], 1)
        records = [
            {
                "status": "success",
                "rows": [
                    {
                        **row,
                        "race_url": "https://umafans.run/races/2025/example/",
                        "region": "united_states",
                        "country": "united_states",
                    }
                    for row in parsed["occurrences"]
                ],
            }
        ]
        occurrences = self.collector._race_occurrences(records)
        self.assertEqual([row["horse_number"] for row in occurrences], ["", ""])

        profiles = [
            {
                "key": self.collector.canonical_horse_key(row),
                "lookup_keys": [self.collector.canonical_horse_key(row)],
                "profile_url": row["profile_url"],
                "display_name": row["horse_display_name"],
                "original_name": row["horse_display_name"],
                "name_zh": "测试马",
                "name_ja": "テストホース",
                "name_en": row["horse_display_name"],
                "resolution_state": "resolved",
            }
            for row in occurrences
        ]
        source = {
            "url": "https://umafans.run/races/2025/example/",
            "region": "united_states",
            "missing_number_rows": 2,
            "profile_fallback": 1,
            "name_fallback": 1,
        }
        with tempfile.TemporaryDirectory() as raw:
            summary = self.collector.finalize_artifacts(
                output_dir=Path(raw),
                year=2025,
                occurrences=occurrences,
                profiles=profiles,
                source_manifest=[source],
                errors=[],
                other_coverage={},
                request_count=0,
                generated_at="2025-01-01T00:00:00+00:00",
            )
        for key, expected in {
            "missing_number_rows": 2,
            "profile_fallback": 1,
            "name_fallback": 1,
            "ambiguity_gap": 0,
            "real_number_conflict": 0,
        }.items():
            self.assertEqual(summary["counts"][key], expected)
        self.assertEqual(summary["counts"]["errors"], 0)
        self.assertEqual(summary["outcome"], "complete")

    def test_conflict_counters_are_fail_closed_errors(self):
        errors = [
            {"error_code": "MissingNumberAmbiguityError"},
            {"error_code": "RealHorseNumberConflictError"},
        ]
        counts = self.collector.participant_identity_observability([], errors)
        self.assertEqual(counts["ambiguity_gap"], 1)
        self.assertEqual(counts["real_number_conflict"], 1)

        with self.assertRaisesRegex(ValueError, "counters drift"):
            self.collector.participant_identity_observability(
                [
                    {
                        "missing_number_rows": 2,
                        "profile_fallback": 1,
                        "name_fallback": 0,
                    }
                ],
                [],
            )


if __name__ == "__main__":
    unittest.main()

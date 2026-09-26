from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


TOOL_PATH = Path(__file__).resolve().parents[2] / "runtime" / "tools" / "bind_historical_gap_candidates.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("bind_historical_gap_candidates_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class BindHistoricalGapCandidatesTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = _load_tool()

    def _write_candidates(self, root: Path, rows: list[dict]) -> Path:
        path = root / "candidates.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        return path

    def _binding(self, **entries) -> Path:
        return entries

    def test_target_id_rows_bind_directly(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = self._write_candidates(
                root,
                [
                    {
                        "target_id": 49460,
                        "source_name": "hkjc_results_all_zh_hk",
                        "source_url": "https://example.test/x",
                        "modules": {
                            "runners": {"items": [{"horse_number": "1"}], "is_complete": True},
                            "results": {"items": [{"finish_position": 1}], "is_complete": True},
                        },
                    }
                ],
            )
            binding = {"49460": {"target_sha256": "a" * 64, "inventory_artifact_sha256": "b" * 64}}
            rows = module.bind_candidate_rows(candidates, binding)

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["target_id"], 49460)
            self.assertEqual(row["target_sha256"], "a" * 64)
            self.assertEqual(row["inventory_artifact_sha256"], "b" * 64)
            self.assertEqual(row["source_name"], "hkjc_results_all_zh_hk")

    def test_year_slug_rows_bind_via_slug_map_and_complete_missing_flags(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = self._write_candidates(
                root,
                [
                    {
                        "year": 2025,
                        "slug": "japan-nakayama-daishogai-2025",
                        "source_name": "jra_official_result_page",
                        "source_url": "https://example.test/y",
                        "modules": {
                            "runners": {"items": [{"horse_number": "1"}]},
                            "results": {"items": [{"finish_position": 1}]},
                        },
                    }
                ],
            )
            binding = {
                "53232": {"target_sha256": "c" * 64, "inventory_artifact_sha256": "d" * 64},
            }
            slug_map = {"2025/japan-nakayama-daishogai-2025": 53232}
            rows = module.bind_candidate_rows(candidates, binding, slug_map=slug_map)

            row = rows[0]
            self.assertEqual(row["target_id"], 53232)
            self.assertEqual(row["target_sha256"], "c" * 64)
            self.assertTrue(row["modules"]["runners"]["is_complete"])
            self.assertTrue(row["modules"]["results"]["is_complete"])

    def test_unknown_key_refused(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = self._write_candidates(
                root,
                [
                    {
                        "target_id": 1,
                        "source_name": "x",
                        "source_url": "https://example.test",
                        "modules": {"results": {"items": [{"finish_position": 1}], "is_complete": True}},
                    }
                ],
            )
            with self.assertRaises(ValueError):
                module.bind_candidate_rows(candidates, {})

    def test_bad_sha_refused(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = self._write_candidates(
                root,
                [
                    {
                        "target_id": 1,
                        "source_name": "x",
                        "source_url": "https://example.test",
                        "modules": {"results": {"items": [{"finish_position": 1}], "is_complete": True}},
                    }
                ],
            )
            with self.assertRaises(ValueError):
                module.bind_candidate_rows(candidates, {"1": {"target_sha256": "not-a-sha", "inventory_artifact_sha256": "b" * 64}})

    def test_empty_items_refused(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = self._write_candidates(
                root,
                [
                    {
                        "target_id": 1,
                        "source_name": "x",
                        "source_url": "https://example.test",
                        "modules": {"results": {"items": []}},
                    }
                ],
            )
            with self.assertRaises(ValueError):
                module.bind_candidate_rows(candidates, {"1": {"target_sha256": "a" * 64, "inventory_artifact_sha256": "b" * 64}})

    def test_explicit_incomplete_module_is_not_flipped(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = self._write_candidates(
                root,
                [
                    {
                        "target_id": 1,
                        "source_name": "x",
                        "source_url": "https://example.test",
                        "modules": {"results": {"items": [{"finish_position": 1}], "is_complete": False}},
                    }
                ],
            )
            with self.assertRaisesRegex(ValueError, "is_complete"):
                module.bind_candidate_rows(candidates, {"1": {"target_sha256": "a" * 64, "inventory_artifact_sha256": "b" * 64}})

    def test_duplicate_target_rows_refused(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {
                "target_id": 1,
                "source_name": "x",
                "source_url": "https://example.test",
                "modules": {"results": {"items": [{"finish_position": 1}], "is_complete": True}},
            }
            candidates = self._write_candidates(root, [row, dict(row)])
            with self.assertRaisesRegex(ValueError, "重复"):
                module.bind_candidate_rows(candidates, {"1": {"target_sha256": "a" * 64, "inventory_artifact_sha256": "b" * 64}})

    def test_empty_provenance_refused(self):
        module = self.module
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidates = self._write_candidates(
                root,
                [
                    {
                        "target_id": 1,
                        "source_name": "",
                        "source_url": "",
                        "modules": {"results": {"items": [{"finish_position": 1}], "is_complete": True}},
                    }
                ],
            )
            with self.assertRaisesRegex(ValueError, "source"):
                module.bind_candidate_rows(candidates, {"1": {"target_sha256": "a" * 64, "inventory_artifact_sha256": "b" * 64}})

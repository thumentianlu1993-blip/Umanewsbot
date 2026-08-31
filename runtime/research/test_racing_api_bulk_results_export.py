#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("racing_api_bulk_results_export.py")


def load_tool():
    if not SCRIPT_PATH.is_file():
        raise AssertionError(f"目标入口尚不存在：{SCRIPT_PATH}")
    sys.path.insert(0, str(SCRIPT_PATH.parent))
    spec = importlib.util.spec_from_file_location("racing_api_bulk_results_export", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载目标入口：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def openapi_fingerprint_identity(module, root: Path) -> dict:
    horse_export = sys.modules["racing_api_horse_export"]
    payload = {
        "fingerprint_generated_at": "2026-08-29T15:33:04+08:00",
        "full_openapi_sha256": horse_export.EXPECTED_OPENAPI_FULL_SHA256,
        "openapi_version": horse_export.EXPECTED_OPENAPI_VERSION,
        "selected_contract": {
            "paths": list(horse_export.EXPECTED_OPENAPI_SELECTED_PATHS),
            "sha256": horse_export.EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256,
        },
        "selected_schema": {
            "names": list(horse_export.EXPECTED_OPENAPI_SELECTED_SCHEMA_NAMES),
            "sha256": horse_export.EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256,
        },
        "source_url": horse_export.OPENAPI_SOURCE_URL,
    }
    path = root / "openapi-fingerprint.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    return module.load_openapi_fingerprint(path, sha256)


def arc_result(*, race_id="rac_arc_2025", position="1"):
    return {
        "race_id": race_id,
        "date": "2025-10-05",
        "off_dt": "2025-10-05T16:05:00+02:00",
        "region": "FR",
        "course": "ParisLongchamp (FR)",
        "course_id": "crs_parislongchamp",
        "race_name": "Qatar Prix de l'Arc de Triomphe",
        "type": "Flat",
        "class": "Group 1",
        "pattern": "G1",
        "dist": "1m4f",
        "surface": "Turf",
        "runners": [
            {"horse_id": "hrs_1", "horse": "Winner (FR)", "position": position, "number": "1"},
            {"horse_id": "hrs_2", "horse": "Second (IRE)", "position": "2", "number": "2"},
            {"horse_id": "hrs_3", "horse": "Withdrawn (GB)", "position": "NR", "number": "3"},
        ],
    }


def arc_target(**overrides):
    target = {
        "target_key": "france-prix-de-l-arc-de-triomphe|2025",
        "year": 2025,
        "local_date": "2025-10-05",
        "country_region": "france",
        "canonical_name_original": "Prix de l'Arc de Triomphe",
        "race_name_aliases": ["Qatar Prix de l'Arc de Triomphe"],
        "racecourse": "ParisLongchamp",
        "racecourse_aliases": ["ParisLongchamp (FR)"],
        "grade_text": "G1",
        "discipline": "flat",
    }
    target.update(overrides)
    return target


def complete_target_manifest(target_path: Path) -> tuple[Path, str]:
    target_sha = hashlib.sha256(target_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "graded-horse-target-ledger.v1",
        "status": "complete",
        "completion_marker": "COMPLETE",
        "database_writes": 0,
        "source_count_conflicts": [],
        "blocking_source_count_conflicts": [],
        "target_ledger": {
            "path": target_path.name,
            "sha256": target_sha,
            "rows": len(target_path.read_text(encoding="utf-8").splitlines()),
        },
    }
    path = target_path.parent / "target-ledger-manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    (target_path.parent / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
    return path, manifest_sha


class RacingApiBulkResultsExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = load_tool()

    def test_fetch_partition_pages_by_returned_count(self):
        pages = {
            0: {"results": [arc_result()], "total": 2, "limit": 100, "skip": 0, "query": []},
            1: {"results": [arc_result(race_id="rac_other")], "total": 2, "limit": 100, "skip": 1, "query": []},
        }

        class FakeClient:
            def __init__(self):
                self.urls = []

            def request_json(self, url):
                self.urls.append(url)
                skip = int(url.rsplit("skip=", 1)[1])
                return pages[skip]

        client = FakeClient()
        combined = self.module.fetch_bulk_partition(
            client,
            local_date="2025-10-05",
            country_region="france",
            max_pages=2,
        )

        self.assertEqual(combined["provider_row_count"], 2)
        self.assertIn("start_date=2025-10-05", client.urls[0])
        self.assertIn("end_date=2025-10-05", client.urls[0])
        self.assertTrue(client.urls[1].endswith("skip=1"))

    def test_fetch_range_preserves_distinct_start_and_end_dates(self):
        class FakeClient:
            def __init__(self):
                self.urls = []

            def request_json(self, url):
                self.urls.append(url)
                return {"results": [], "total": 0, "limit": 100, "skip": 0, "query": []}

        client = FakeClient()
        combined = self.module.fetch_bulk_range(
            client,
            start_date="2025-01-01",
            end_date="2025-12-31",
            country_region="france",
            max_pages=1,
        )
        self.assertEqual(combined["provider_row_count"], 0)
        self.assertIn("start_date=2025-01-01", client.urls[0])
        self.assertIn("end_date=2025-12-31", client.urls[0])

    def test_unique_target_match_emits_actual_starters_only(self):
        result = self.module.reconcile_partition(
            targets=[arc_target()],
            races=[arc_result()],
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["mapped_targets"], 1)
        self.assertEqual(len(result["participants"]), 2)
        self.assertEqual(result["participants"][0]["race_id"], "rac_arc_2025")
        self.assertEqual(result["excluded_non_runner_count"], 1)

    def test_zero_or_multiple_race_candidates_stay_in_review(self):
        no_match = self.module.reconcile_partition(
            targets=[arc_target()],
            races=[{**arc_result(), "race_name": "Different Race"}],
        )
        self.assertEqual(no_match["status"], "needs_review")
        self.assertEqual(no_match["gaps"][0]["reason"], "race_candidate_missing")

        multiple = self.module.reconcile_partition(
            targets=[arc_target()],
            races=[arc_result(), arc_result(race_id="rac_arc_duplicate")],
        )
        self.assertEqual(multiple["gaps"][0]["reason"], "race_candidate_ambiguous")

    def test_unknown_runner_status_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unresolved runner status"):
            self.module.reconcile_partition(
                targets=[arc_target()],
                races=[arc_result(position="UNKNOWN")],
            )

    def test_artifact_uses_prepared_when_any_target_gap_remains(self):
        target_rows = [arc_target()]

        class FakeClient:
            request_ceiling = 1
            request_count = 0
            request_ledger = []

            def request_json(self, url):
                self.request_count += 1
                self.request_ledger.append({"url": url, "status": 200})
                return {
                    "results": [{**arc_result(), "race_name": "Different Race"}],
                    "total": 1,
                    "limit": 100,
                    "skip": 0,
                    "query": [],
                }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target_path = root / "targets.jsonl"
            target_path.write_text("".join(json.dumps(row) + "\n" for row in target_rows), encoding="utf-8")
            target_sha = hashlib.sha256(target_path.read_bytes()).hexdigest()
            target_manifest, target_manifest_sha = complete_target_manifest(target_path)
            output = root / "output"
            fingerprint_identity = openapi_fingerprint_identity(self.module, root)

            manifest = self.module.run_bulk_partition_artifact(
                target_path=target_path,
                approved_target_sha256=target_sha,
                target_manifest_path=target_manifest,
                approved_target_manifest_sha256=target_manifest_sha,
                output_dir=output,
                client=FakeClient(),
                local_date="2025-10-05",
                country_region="france",
                max_pages=1,
                openapi_fingerprint_identity=fingerprint_identity,
            )

            self.assertEqual(manifest["status"], "needs_review")
            self.assertTrue((output / "PREPARED").is_file())
            self.assertFalse((output / "COMPLETE").exists())
            self.assertEqual(manifest["database_writes"], 0)

    def test_bulk_network_artifact_rejects_prepared_target_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target_path = root / "targets.jsonl"
            target_path.write_text(json.dumps(arc_target()) + "\n", encoding="utf-8")
            target_sha = hashlib.sha256(target_path.read_bytes()).hexdigest()
            target_manifest, _manifest_sha = complete_target_manifest(target_path)
            manifest = json.loads(target_manifest.read_text(encoding="utf-8"))
            manifest.update(
                status="needs_source_conflict_review",
                completion_marker="PREPARED",
                source_count_conflicts=[{"region": "france", "year": 2025}],
            )
            target_manifest.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
            prepared_sha = hashlib.sha256(target_manifest.read_bytes()).hexdigest()
            (root / "COMPLETE").unlink()
            (root / "PREPARED").write_text(prepared_sha + "\n", encoding="ascii")
            fingerprint_identity = openapi_fingerprint_identity(self.module, root)

            with self.assertRaisesRegex(ValueError, "not COMPLETE"):
                self.module.run_bulk_partition_artifact(
                    target_path=target_path,
                    approved_target_sha256=target_sha,
                    target_manifest_path=target_manifest,
                    approved_target_manifest_sha256=prepared_sha,
                    output_dir=root / "output",
                    client=object(),
                    local_date="2025-10-05",
                    country_region="france",
                    max_pages=1,
                    openapi_fingerprint_identity=fingerprint_identity,
                )

    def test_content_addressed_target_inputs_reject_ambiguous_json(self):
        cases = {
            "duplicate_manifest_key": "manifest",
            "nonfinite_target_value": "target",
        }
        for case_name, corrupt_input in cases.items():
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target_path = root / "targets.jsonl"
                if corrupt_input == "target":
                    target_path.write_text(
                        json.dumps(arc_target(), sort_keys=True)[:-1] + ', "unexpected": NaN}\n',
                        encoding="utf-8",
                    )
                else:
                    target_path.write_text(
                        json.dumps(arc_target(), sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                target_sha = hashlib.sha256(target_path.read_bytes()).hexdigest()
                target_manifest, target_manifest_sha = complete_target_manifest(target_path)
                if corrupt_input == "manifest":
                    manifest_text = target_manifest.read_text(encoding="utf-8")
                    manifest_text = manifest_text.replace(
                        '"status": "complete"',
                        '"status": "complete", "status": "complete"',
                        1,
                    )
                    target_manifest.write_text(manifest_text, encoding="utf-8")
                    target_manifest_sha = hashlib.sha256(target_manifest.read_bytes()).hexdigest()
                    (root / "COMPLETE").write_text(target_manifest_sha + "\n", encoding="ascii")

                with self.assertRaisesRegex(
                    ValueError,
                    "invalid target ledger manifest|invalid target JSONL",
                ):
                    self.module._load_targets(
                        target_path,
                        approved_target_sha256=target_sha,
                        target_manifest_path=target_manifest,
                        approved_target_manifest_sha256=target_manifest_sha,
                        local_date="2025-10-05",
                        country_region="france",
                    )


if __name__ == "__main__":
    unittest.main()

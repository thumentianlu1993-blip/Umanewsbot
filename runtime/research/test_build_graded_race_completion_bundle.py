from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime.research import build_graded_race_completion_bundle as bundler
from runtime.research import build_official_graded_race_manifest as builder
from runtime.research import test_validate_official_graded_race_package as package_fixture


class GradedRaceCompletionBundleTests(unittest.TestCase):
    def test_bundle_binds_legacy_official_and_reviewed_package(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, package_summary_sha = package_fixture.OfficialPackageValidatorTests().package(root)
            package_summary = json.loads((package / "summary.json").read_text(encoding="utf-8"))
            legacy = root / "legacy"
            legacy.mkdir()
            for name in {
                "race_participants_2025.csv", "horse_names_2025.csv",
                "horse_name_review_queue_2025.csv", "source_manifest.jsonl",
                "errors.json", "README.md",
            }:
                (legacy / name).write_text("[]\n" if name == "errors.json" else "fixture\n", encoding="utf-8")
            (legacy / "summary.json").write_bytes(builder.canonical_json_bytes({
                "schema_version": 1,
                "year": 2025,
                "outcome": "partial",
                "counts": {"included_races": 1, "participant_rows": 1},
            }))
            official = root / "official"
            official.mkdir()
            (official / "official_participants.jsonl").write_text("{}\n", encoding="utf-8")
            (official / "official_sources.jsonl").write_text("{}\n", encoding="utf-8")
            official_summary = {
                "schema_version": 1,
                "year": 2025,
                "status": "complete",
                "manifest_sha256": package_summary["official_result_manifest_sha256"],
                "race_count": 1,
                "participant_count": 1,
                "files": {
                    name: builder.sha256_file(official / name)
                    for name in ("official_participants.jsonl", "official_sources.jsonl")
                },
            }
            (official / "summary.json").write_bytes(builder.canonical_json_bytes(official_summary))

            result = bundler.build_bundle(
                year=2025,
                legacy_dir=legacy,
                official_dir=official,
                reviewed_package_dir=package,
                reviewed_summary_sha256=package_summary_sha,
            )
            self.assertEqual(result["counts"]["official_catalog"], 2)
            self.assertEqual(len(result["files"]), 13)

            official_summary["manifest_sha256"] = "f" * 64
            (official / "summary.json").write_bytes(builder.canonical_json_bytes(official_summary))
            with self.assertRaisesRegex(bundler.BundleBuildError, "manifest binding drift"):
                bundler.build_bundle(
                    year=2025,
                    legacy_dir=legacy,
                    official_dir=official,
                    reviewed_package_dir=package,
                    reviewed_summary_sha256=package_summary_sha,
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime.research import build_official_graded_race_manifest as builder
from runtime.research import test_build_official_graded_race_manifest as fixtures
from runtime.research import validate_official_graded_race_package as validator


class OfficialPackageValidatorTests(unittest.TestCase):
    def package(self, root: Path) -> tuple[Path, str]:
        helper = fixtures.OfficialManifestBuilderTests()
        catalogs = helper.catalogs(root)
        reviewed = helper.reviewed(root, catalogs)
        manifest, gaps, summary = builder.compile_review(
            catalogs,
            year=2025,
            reviewed_path=reviewed,
            expected_sha256=builder.sha256_file(reviewed),
        )
        package = root / "package"
        package.mkdir()
        for name, payload in (
            ("official_result_manifest.json", manifest),
            ("official_result_gaps.json", gaps),
            ("summary.json", summary),
        ):
            (package / name).write_bytes(builder.canonical_json_bytes(payload))
        return package, builder.sha256_file(package / "summary.json")

    def test_exact_package_validates_and_conserves(self):
        with TemporaryDirectory() as temporary:
            package, summary_sha = self.package(Path(temporary))
            result = validator.validate_package(
                package,
                year=2025,
                expected_summary_sha256=summary_sha,
            )
        self.assertEqual((result["catalog_count"], result["collect_count"], result["gap_count"]), (2, 1, 1))

    def test_tamper_extra_file_and_symlink_fail_closed(self):
        with TemporaryDirectory() as temporary:
            package, summary_sha = self.package(Path(temporary))
            manifest = package / "official_result_manifest.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["races"][0]["race_name"] = "tampered"
            manifest.write_bytes(builder.canonical_json_bytes(payload))
            with self.assertRaisesRegex(validator.PackageValidationError, "manifest SHA"):
                validator.validate_package(package, year=2025, expected_summary_sha256=summary_sha)

            manifest.unlink()
            manifest.symlink_to(package / "summary.json")
            with self.assertRaisesRegex(validator.PackageValidationError, "non-symlink"):
                validator.validate_package(package, year=2025, expected_summary_sha256=summary_sha)

            manifest.unlink()
            manifest.write_text("{}", encoding="utf-8")
            (package / "extra.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(validator.PackageValidationError, "file set"):
                validator.validate_package(package, year=2025, expected_summary_sha256=summary_sha)


if __name__ == "__main__":
    unittest.main()

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from package_race_name_translation_bundle import (
    MEMBERS,
    build_archive,
    sha256_file,
    sha256_json,
    verify_archive,
    verify_source,
)


def _write_minimal_bundle(source: Path) -> tuple[dict, str]:
    for name in MEMBERS[:-1]:
        (source / name).write_text(f"{name}\n", encoding="utf-8")
    rows = [
        {
            "file": name,
            "sizeBytes": (source / name).stat().st_size,
            "sha256": sha256_file(source / name),
        }
        for name in MEMBERS[:-1]
    ]
    index = {
        "schemaVersion": "race-name-translation-bundle-index.v1",
        "files": rows,
    }
    index["contentSha256"] = sha256_json(index)
    (source / "bundle-index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return index, sha256_file(source / "bundle-index.json")


class PackageRaceNameTranslationBundleTests(unittest.TestCase):
    def test_happy_path_and_deterministic_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bundle"
            source.mkdir()
            index, index_sha = _write_minimal_bundle(source)
            resolved = verify_source(source, index_sha)
            self.assertEqual(resolved["contentSha256"], index["contentSha256"])
            first = Path(directory) / "first.tar.gz"
            second = Path(directory) / "second.tar.gz"
            build_archive(source, first)
            build_archive(source, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            verify_archive(first, index_sha)

    def test_wrong_expected_index_sha_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bundle"
            source.mkdir()
            _write_minimal_bundle(source)
            with self.assertRaisesRegex(RuntimeError, "raw SHA mismatch"):
                verify_source(source, "0" * 64)

    def test_tampered_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bundle"
            source.mkdir()
            _, index_sha = _write_minimal_bundle(source)
            (source / "manifest.json").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "member mismatch"):
                verify_source(source, index_sha)

    def test_forged_content_sha_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bundle"
            source.mkdir()
            index, _ = _write_minimal_bundle(source)
            index["contentSha256"] = "f" * 64
            (source / "bundle-index.json").write_text(
                json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "content sha mismatch"):
                verify_source(source, sha256_file(source / "bundle-index.json"))

    def test_duplicate_files_row_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bundle"
            source.mkdir()
            index, _ = _write_minimal_bundle(source)
            index["files"] = index["files"] + [index["files"][0]]
            index["contentSha256"] = sha256_json(
                {key: value for key, value in index.items() if key != "contentSha256"}
            )
            (source / "bundle-index.json").write_text(
                json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "row count mismatch"):
                verify_source(source, sha256_file(source / "bundle-index.json"))

    def test_wrong_index_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bundle"
            source.mkdir()
            index, _ = _write_minimal_bundle(source)
            index["schemaVersion"] = "race-name-translation-bundle-index.v0"
            index["contentSha256"] = sha256_json(
                {key: value for key, value in index.items() if key != "contentSha256"}
            )
            (source / "bundle-index.json").write_text(
                json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "schema"):
                verify_source(source, sha256_file(source / "bundle-index.json"))


if __name__ == "__main__":
    unittest.main()

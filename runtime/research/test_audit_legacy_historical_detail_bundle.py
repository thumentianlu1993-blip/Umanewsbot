from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("audit_legacy_historical_detail_bundle.py")
SPEC = importlib.util.spec_from_file_location("legacy_bundle_audit", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def identity(root: Path, path: Path) -> dict:
    return {
        "path": str(path.relative_to(root)),
        "sha256": sha(path),
        "size": path.stat().st_size,
    }


class LegacyBundleAuditTests(unittest.TestCase):
    def _target(self, root: Path, *, complete: bool = False) -> Path:
        root.mkdir()
        ledger = root / "target-ledger.jsonl"
        target = {
            "schema_version": "graded-horse-target-ledger.v1",
            "target_key": "united_kingdom:2022:united-kingdom-example:flat",
            "country_region": "united_kingdom",
            "year": 2022,
            "series_key": "united-kingdom-example",
            "discipline": "flat",
            "grade_text": "G2",
        }
        ledger.write_text(json.dumps(target, sort_keys=True) + "\n", encoding="utf-8")
        marker = "COMPLETE" if complete else "PREPARED"
        manifest = {
            "schema_version": "graded-horse-target-ledger.v1",
            "status": "complete" if complete else "needs_source_conflict_review",
            "completion_marker": marker,
            "blocking_source_count_conflicts": [],
            "target_ledger": {**identity(root, ledger), "rows": 1},
        }
        manifest_path = root / "target-ledger-manifest.json"
        write_json(manifest_path, manifest)
        (root / marker).write_text(sha(manifest_path) + "\n", encoding="ascii")
        return root

    def _bundle(
        self,
        root: Path,
        *,
        series_key: str = "united-kingdom-example",
        compact: bool = False,
    ) -> Path:
        root.mkdir()
        chunk = root / "layers/historical/chunks/one"
        source = chunk / "sources/target-7.html"
        source.parent.mkdir(parents=True)
        source.write_text("<html>source</html>", encoding="utf-8")
        source_identity = {
            "path": source.name,
            "sha256": sha(source),
            "size": source.stat().st_size,
            "source_url": "https://example.com/result/7",
        }
        candidate = {
            "pending_target": {
                "target_id": 7,
                "region": "united_kingdom",
                "year": 2022,
                "series_key": series_key,
            },
            "local_date": "2022-06-01",
            "source": {"url": "https://example.com/result/7"},
            "approved_source_cache_identity": source_identity,
            "modules": {
                "runners": {
                    "is_complete": True,
                    "items": [{"horse_name": "Horse One"}, {"horse_name": "Horse Two"}],
                },
                "results": {
                    "is_complete": True,
                    "items": [
                        {
                            "horse_name": "Horse One",
                            "finish_position": 1,
                            "source_refs": {"horse_name_raw": "Horse One (IRE)"},
                        },
                        {"horse_name": "Horse Two", "finish_position": 2},
                    ],
                },
            },
        }
        candidates = chunk / "candidates.jsonl"
        candidates.write_text(json.dumps(candidate, sort_keys=True) + "\n", encoding="utf-8")
        chunk_manifest = chunk / "manifest.json"
        write_json(chunk_manifest, {"target_count": 1})
        gaps = root / "gaps.jsonl"
        gaps.write_text("", encoding="utf-8")
        manifest = {
            "artifact_kind": "historical_race_detail_source_bundle",
            "record_count": 1,
            "layers": {
                "historical": {
                    "gap_count": 0,
                    "chunks": [
                        {
                            "chunk_id": "one",
                            "target_count": 1,
                            "candidates": identity(root, candidates),
                            "manifest": identity(root, chunk_manifest),
                        }
                    ]
                }
            },
        }
        if not compact:
            manifest.update(
                {
                    "scope_count": 1,
                    "gap_count": 0,
                    "outputs": {"gaps.jsonl": identity(root, gaps)},
                }
            )
        write_json(root / "manifest.json", manifest)
        return root

    def test_exact_match_is_audited_but_prepared_target_is_not_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = self._target(base / "target")
            bundle = self._bundle(base / "bundle")
            manifest = MODULE.audit_bundle(
                target_root=target,
                bundle_root=bundle,
                output_dir=base / "out",
            )
            self.assertEqual(manifest["exact_target_match_count"], 1)
            self.assertEqual(manifest["exact_actual_starter_count"], 2)
            self.assertFalse(manifest["target_artifact"]["reviewed_complete"])
            row = json.loads((base / "out/exact-target-matches.jsonl").read_text())
            self.assertEqual(row["discipline"], "flat")
            self.assertFalse(row["target_artifact_reviewed_complete"])
            self.assertEqual(row["anchor_horse"]["name"], "Horse One")
            self.assertEqual(row["anchor_horse"]["country_suffix"], "IRE")
            self.assertEqual(row["target"]["local_date"], "2022-06-01")

    def test_legacy_alias_is_manual_review_not_silent_fuzzy_match(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = self._target(base / "target", complete=True)
            bundle = self._bundle(base / "bundle", series_key="GBR_EXAMPLE")
            manifest = MODULE.audit_bundle(
                target_root=target,
                bundle_root=bundle,
                output_dir=base / "out",
            )
            self.assertEqual(manifest["exact_target_match_count"], 0)
            self.assertEqual(manifest["manual_review_candidate_count"], 1)
            row = json.loads((base / "out/manual-review-candidates.jsonl").read_text())
            self.assertEqual(row["match_status"], "target_match_missing")

    def test_modified_source_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = self._target(base / "target")
            bundle = self._bundle(base / "bundle")
            source = next(bundle.glob("layers/**/sources/*.html"))
            source.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source cache identity mismatch"):
                MODULE.audit_bundle(
                    target_root=target,
                    bundle_root=bundle,
                    output_dir=base / "out",
                )

    def test_compact_zero_gap_bundle_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = self._target(base / "target")
            bundle = self._bundle(base / "bundle", compact=True)
            manifest = MODULE.audit_bundle(
                target_root=target,
                bundle_root=bundle,
                output_dir=base / "out",
            )
            self.assertEqual(manifest["legacy_bundle"]["scope_count"], 1)
            self.assertEqual(manifest["legacy_gap_count"], 0)


if __name__ == "__main__":
    unittest.main()

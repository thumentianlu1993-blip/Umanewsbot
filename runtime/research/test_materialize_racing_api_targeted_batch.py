#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .test_racing_api_targeted_batch_export import FakeClient, seed
except ImportError:  # pragma: no cover - direct script execution
    from test_racing_api_targeted_batch_export import FakeClient, seed


SCRIPT_PATH = Path(__file__).with_name("materialize_racing_api_targeted_batch.py")
BATCH_PATH = Path(__file__).with_name("racing_api_targeted_batch_export.py")


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TargetedBatchMaterializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.batch = _load("materializer_batch_export", BATCH_PATH)
        cls.module = _load("materialize_racing_api_targeted_batch", SCRIPT_PATH)

    def _fingerprint(self, root: Path) -> dict:
        horse = sys.modules["racing_api_horse_export"]
        payload = {
            "fingerprint_generated_at": "2026-08-31T18:11:05+00:00",
            "full_openapi_sha256": horse.EXPECTED_OPENAPI_FULL_SHA256,
            "openapi_version": horse.EXPECTED_OPENAPI_VERSION,
            "selected_contract": {
                "paths": list(horse.EXPECTED_OPENAPI_SELECTED_PATHS),
                "sha256": horse.EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256,
            },
            "selected_schema": {
                "names": list(horse.EXPECTED_OPENAPI_SELECTED_SCHEMA_NAMES),
                "sha256": horse.EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256,
            },
            "source_url": horse.OPENAPI_SOURCE_URL,
        }
        path = root / "openapi.json"
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        return self.batch.load_openapi_fingerprint(
            path,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def _batch(self, root: Path) -> tuple[Path, str, list[str]]:
        seeds = [seed("seed-a"), seed("seed-b")]
        ledger = root / "seeds.jsonl"
        ledger.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in seeds),
            encoding="utf-8",
        )
        batch_root = root / "batch"
        self.batch.run_targeted_batch_artifact(
            seed_ledger_path=ledger,
            approved_seed_ledger_sha256=hashlib.sha256(ledger.read_bytes()).hexdigest(),
            output_dir=batch_root,
            client=FakeClient(request_ceiling=8),
            max_search_candidates=1,
            max_results_pages_per_horse=1,
            max_parent_profiles=0,
            openapi_fingerprint_identity=self._fingerprint(root),
        )
        manifest_path = batch_root / "batch-manifest.json"
        return (
            batch_root,
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            [row["seed_id"] for row in seeds],
        )

    def test_materializes_compact_batch_without_recomputing_normalized_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch_root, batch_sha, seed_ids = self._batch(root)
            output = root / "materialized"

            result = self.module.materialize_targeted_batch(
                batch_dir=batch_root,
                approved_batch_manifest_sha256=batch_sha,
                output_dir=output,
            )

            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["selected_seed_count"], 2)
            self.assertEqual(
                [row["seed_id"] for row in result["materialized"]],
                seed_ids,
            )
            self.assertEqual(
                (output / "COMPLETE").read_text(encoding="ascii").strip(),
                result["materialization_manifest_sha256"],
            )
            first_root = output / result["materialized"][0]["path"]
            normalized = json.loads(
                (first_root / "normalized" / "targeted-horse-export.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(normalized["schema_version"], "targeted-horse-export.v1")
            self.assertEqual(normalized["horse_id"], "hrs_1024")
            self.assertEqual(normalized["career"]["unique_race_count"], 1)
            self.assertEqual(normalized["target_race"]["source_mode"], "targeted_horse_content_pool")
            self.assertEqual(len(normalized["target_race"]["actual_starters"]), 1)
            expanded_manifest = json.loads(
                (first_root / "run-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(expanded_manifest["materialization_mode"], "expanded_compact")
            self.assertEqual(expanded_manifest["source_batch_manifest_sha256"], batch_sha)
            self.assertTrue(expanded_manifest["responses"])
            for response in expanded_manifest["responses"]:
                self.assertEqual(response["sha256"], response["source_object_ref"]["sha256"])

    def test_selected_seed_order_must_match_source_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch_root, batch_sha, seed_ids = self._batch(root)
            with self.assertRaisesRegex(
                self.module.MaterializationError,
                "source batch order",
            ):
                self.module.materialize_targeted_batch(
                    batch_dir=batch_root,
                    approved_batch_manifest_sha256=batch_sha,
                    output_dir=root / "materialized",
                    selected_seed_ids=list(reversed(seed_ids)),
                )

    def test_undeclared_content_pool_member_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch_root, batch_sha, _seed_ids = self._batch(root)
            extra = batch_root / "objects" / "undeclared.json"
            extra.write_text("{}\n", encoding="utf-8")
            extra.chmod(0o600)

            with self.assertRaisesRegex(
                self.module.MaterializationError,
                "member set drift",
            ):
                self.module.materialize_targeted_batch(
                    batch_dir=batch_root,
                    approved_batch_manifest_sha256=batch_sha,
                    output_dir=root / "materialized",
                )


if __name__ == "__main__":
    unittest.main()

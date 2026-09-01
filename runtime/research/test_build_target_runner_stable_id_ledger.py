#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("build_target_runner_stable_id_ledger.py")


def load_tool():
    sys.path.insert(0, str(SCRIPT_PATH.parent))
    spec = importlib.util.spec_from_file_location("build_target_runner_stable_id_ledger", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load stable ID ledger tool")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def canonical(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def race(race_id: str, raced_at: str, starters: list[tuple[str, str]]) -> dict:
    return {
        "race_id": race_id,
        "date": raced_at,
        "region": "FR",
        "course": "Saint-Cloud",
        "course_id": "crs_saint_cloud",
        "race_name": f"Prix {race_id.removeprefix('rac_')}",
        "type": "Flat",
        "pattern": "G3",
        "runners": [
            {"horse_id": horse_id, "horse": name, "position": str(position), "number": str(position)}
            for position, (horse_id, name) in enumerate(starters, 1)
        ],
    }


def materialized_run(root: Path, ordinal: int, seed_id: str, target_race: dict) -> dict:
    run_root = root / f"{ordinal:05d}-fixture"
    normalized = {
        "schema_version": "targeted-horse-export.v1",
        "database_writes": 0,
        "seed_id": seed_id,
        "horse_id": target_race["runners"][0]["horse_id"],
        "identity_mode": "target_occurrence",
        "profile": {},
        "parent_profiles": [],
        "career": {"provider_row_count": 1, "unique_race_count": 1, "page_count": 1, "races": [target_race]},
        "target_race": {
            **target_race,
            "actual_starters": [
                {**runner, "participant_status": "finished"}
                for runner in target_race["runners"]
            ],
            "excluded_non_runner_count": 0,
            "source_mode": "targeted_horse_content_pool",
        },
    }
    normalized_path = run_root / "normalized" / "targeted-horse-export.json"
    normalized_path.parent.mkdir(parents=True)
    normalized_path.write_bytes(canonical(normalized))
    normalized_sha = hashlib.sha256(normalized_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "targeted-horse-run.v1",
        "status": "complete",
        "database_writes": 0,
        "responses": [],
        "normalized": {
            "path": "normalized/targeted-horse-export.json",
            "sha256": normalized_sha,
            "size": normalized_path.stat().st_size,
        },
    }
    manifest_path = run_root / "run-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    (run_root / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
    return {
        "ordinal": ordinal,
        "seed_id": seed_id,
        "horse_id": normalized["horse_id"],
        "path": run_root.relative_to(root).as_posix(),
        "manifest_sha256": manifest_sha,
    }


def profile_only_run(root: Path, ordinal: int, seed_id: str) -> dict:
    run_root = root / f"{ordinal:05d}-profile-only"
    normalized = {
        "schema_version": "targeted-horse-export.v1",
        "database_writes": 0,
        "seed_id": seed_id,
        "horse_id": "hrs_profileonly",
        "identity_mode": "external_anchor_profile_only",
        "profile": {"horse_id": "hrs_profileonly", "name": "Fallback"},
        "parent_profiles": [],
        "career": {"provider_row_count": 1, "unique_race_count": 1, "page_count": 1, "races": []},
        "scope_target_races": [],
        "target_race": None,
        "target_occurrence": {
            "status": "missing_from_provider_results",
            "authority": "external_anchor",
            "expected_finish_position": "1",
            "target": {"year": 2005, "edition_year": 2005},
            "source": {"authority": "human_reviewed_reference", "url": "https://example.com"},
        },
    }
    normalized_path = run_root / "normalized" / "targeted-horse-export.json"
    normalized_path.parent.mkdir(parents=True)
    normalized_path.write_bytes(canonical(normalized))
    normalized_sha = hashlib.sha256(normalized_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "targeted-horse-run.v1",
        "status": "complete",
        "database_writes": 0,
        "responses": [],
        "normalized": {
            "path": "normalized/targeted-horse-export.json",
            "sha256": normalized_sha,
            "size": normalized_path.stat().st_size,
        },
    }
    manifest_path = run_root / "run-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    (run_root / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
    return {
        "ordinal": ordinal,
        "seed_id": seed_id,
        "horse_id": normalized["horse_id"],
        "path": run_root.relative_to(root).as_posix(),
        "manifest_sha256": manifest_sha,
    }


class StableIdLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = load_tool()

    def _materialization(self, root: Path) -> tuple[Path, str, list[dict]]:
        first = race("rac_bango", "2026-03-24", [("hrs_a", "Alpha (FR)"), ("hrs_b", "Beta (FR)")])
        second = race("rac_estruval", "2026-04-17", [("hrs_c", "Gamma (FR)"), ("hrs_a", "Alpha (FR)")])
        materialized = root / "materialized"
        materialized.mkdir()
        rows = [
            materialized_run(materialized, 1, "winner-bango", first),
            materialized_run(materialized, 2, "winner-estruval", second),
        ]
        manifest = {
            "schema_version": "targeted-horse-batch-materialization.v1",
            "status": "complete",
            "database_writes": 0,
            "source_batch_manifest_sha256": "a" * 64,
            "source_content_pool_manifest_sha256": "b" * 64,
            "selected_seed_count": 2,
            "materialized": rows,
        }
        manifest_path = materialized / "materialization-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (materialized / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
        return materialized, manifest_sha, [first, second]

    def test_builds_one_stable_id_seed_per_unique_actual_starter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialized, manifest_sha, _races = self._materialization(root)
            output = root / "ledger"
            report = self.module.build_stable_id_seed_ledger(
                materialized_dir=materialized,
                approved_materialization_manifest_sha256=manifest_sha,
                output_dir=output,
            )

            self.assertEqual(report["source_target_occurrence_count"], 2)
            self.assertEqual(report["unique_target_race_count"], 2)
            self.assertEqual(report["unique_actual_starter_count"], 3)
            seeds = [json.loads(line) for line in (output / "target-runner-stable-id-seeds.v1.jsonl").read_text().splitlines()]
            alpha = next(seed for seed in seeds if seed["horse_id"] == "hrs_a")
            self.assertEqual(len(alpha["target_occurrences"]), 2)
            self.assertEqual(alpha["source_names"], ["Alpha (FR)"])
            self.assertTrue((output / "COMPLETE").is_file())

    def test_rejects_materialization_extra_member_before_stable_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialized, manifest_sha, _races = self._materialization(root)
            (materialized / "unexpected.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                self.module.StableIdLedgerError, "member set drift"
            ):
                self.module.build_stable_id_seed_ledger(
                    materialized_dir=materialized,
                    approved_materialization_manifest_sha256=manifest_sha,
                    output_dir=root / "ledger",
                )
            self.assertFalse((root / "ledger").exists())

    def test_profile_only_member_becomes_gap_without_blocking_other_starters(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialized, _manifest_sha, _races = self._materialization(root)
            manifest_path = materialized / "materialization-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["materialized"].append(
                profile_only_run(materialized, 3, "winner-profile-only")
            )
            manifest["selected_seed_count"] = 3
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            (materialized / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")

            output = root / "ledger"
            report = self.module.build_stable_id_seed_ledger(
                materialized_dir=materialized,
                approved_materialization_manifest_sha256=manifest_sha,
                output_dir=output,
            )

            self.assertEqual(report["coverage_status"], "complete_with_gaps")
            self.assertEqual(report["source_materialized_seed_count"], 3)
            self.assertEqual(report["source_target_occurrence_count"], 2)
            self.assertEqual(report["profile_only_gap_count"], 1)
            self.assertEqual(report["unique_actual_starter_count"], 3)
            gaps = [
                json.loads(line)
                for line in (output / "target-occurrence-gaps.v1.jsonl").read_text().splitlines()
            ]
            self.assertEqual(gaps[0]["gap_code"], "target_occurrence_identity_unresolved")
            self.assertEqual(gaps[0]["horse_id"], "hrs_profileonly")

    def test_stable_id_seed_fetches_directly_and_validates_every_target_race(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialized, manifest_sha, races = self._materialization(root)
            output = root / "ledger"
            self.module.build_stable_id_seed_ledger(
                materialized_dir=materialized,
                approved_materialization_manifest_sha256=manifest_sha,
                output_dir=output,
            )
            seeds = [json.loads(line) for line in (output / "target-runner-stable-id-seeds.v1.jsonl").read_text().splitlines()]
            alpha = next(seed for seed in seeds if seed["horse_id"] == "hrs_a")

            class FakeClient:
                def __init__(self):
                    self.urls = []

                def request_json(self, url, *, allow_not_found=False):
                    self.urls.append(url)
                    if url.endswith("/pro"):
                        return {
                            "id": "hrs_a",
                            "name": "Alpha (FR)",
                            "dob": "2021-01-01",
                            "sex": "mare",
                            "sex_code": "M",
                            "colour": "bay",
                            "colour_code": "B",
                            "breeder": "Example",
                            "sire": "Sire (FR)",
                            "sire_id": "sir_1",
                            "dam": "Dam (FR)",
                            "dam_id": "dam_2",
                            "damsire": "Damsire (FR)",
                            "damsire_id": "dsi_3",
                        }
                    return {"results": races, "total": 2, "limit": 100, "skip": 0, "query": []}

            client = FakeClient()
            exported = sys.modules["racing_api_horse_export"].run_targeted_seed(
                alpha,
                client=client,
                max_search_candidates=1,
                max_results_pages_per_horse=1,
                max_parent_profiles=0,
            )
            self.assertEqual(exported["identity_mode"], "provider_stable_id_from_target_race")
            self.assertEqual(len(exported["scope_target_races"]), 2)
            self.assertEqual(len(client.urls), 2)
            self.assertFalse(any("/search?" in url for url in client.urls))

            v2_seed = {
                **alpha,
                "schema_version": "targeted-runner-stable-id-seed.v2",
                "source_targeted_batch_manifest_sha256s": [
                    alpha.pop("source_targeted_batch_manifest_sha256")
                ],
            }
            v2_client = FakeClient()
            v2_exported = sys.modules["racing_api_horse_export"].run_targeted_seed(
                v2_seed,
                client=v2_client,
                max_search_candidates=1,
                max_results_pages_per_horse=1,
                max_parent_profiles=0,
            )
            self.assertEqual(len(v2_exported["scope_target_races"]), 2)
            self.assertEqual(len(v2_client.urls), 2)
            self.assertFalse(any("/search?" in url for url in v2_client.urls))


if __name__ == "__main__":
    unittest.main()

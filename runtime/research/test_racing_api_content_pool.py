#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("racing_api_content_pool.py")


def load_tool():
    if not SCRIPT_PATH.is_file():
        raise AssertionError(f"目标入口尚不存在：{SCRIPT_PATH}")
    spec = importlib.util.spec_from_file_location("racing_api_content_pool", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载目标入口：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def race(position: str = "1") -> dict:
    return {
        "race_id": "rac_arc_1999",
        "date": "1999-10-03",
        "region": "FR",
        "course": "Longchamp",
        "course_id": "crs_longchamp",
        "race_name": "Prix de l'Arc de Triomphe",
        "type": "Flat",
        "pattern": "G1",
        "runners": [
            {
                "horse_id": "hrs_1024",
                "horse": "Montjeu (IRE)",
                "position": position,
                "number": "7",
            },
            {
                "horse_id": "hrs_2048",
                "horse": "El Condor Pasa (USA)",
                "position": "2",
                "number": "4",
            },
        ],
    }


def export_result() -> dict:
    return {
        "schema_version": "targeted-horse-export.v1",
        "database_writes": 0,
        "seed_id": "montjeu",
        "horse_id": "hrs_1024",
        "identity_mode": "target_occurrence",
        "profile": {
            "horse_id": "hrs_1024",
            "raw_name": "Montjeu (IRE)",
            "payload_sha256": "a" * 64,
        },
        "parent_profiles": [
            {
                "horse_id": "hrs_100",
                "raw_name": "Sadler's Wells (USA)",
                "payload_sha256": "b" * 64,
            }
        ],
        "career": {
            "provider_row_count": 1,
            "unique_race_count": 1,
            "page_count": 1,
            "races": [race()],
        },
        "page_field_matrix": {
            "schema_version": "horse-page-field-matrix.v1",
            "database_writes": 0,
            "horse_id": "hrs_1024",
            "fields": {},
            "career": {},
            "completeness": {},
            "source_refs": {},
        },
        "target_race": {**race(), "actual_starters": race()["runners"]},
    }


class RacingApiContentPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = load_tool()

    def test_identical_race_is_one_object_and_conflicting_revision_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            pool = self.module.ContentAddressedPool(Path(temporary) / "objects")

            first = pool.put_json(
                kind="race",
                identity="rac_arc_1999",
                payload=race(),
                singleton_identity=True,
            )
            second = pool.put_json(
                kind="race",
                identity="rac_arc_1999",
                payload=race(),
                singleton_identity=True,
            )

            self.assertEqual(first, second)
            self.assertEqual(pool.snapshot()["object_count"], 1)
            with self.assertRaisesRegex(self.module.ContentPoolError, "identity conflict"):
                pool.put_json(
                    kind="race",
                    identity="rac_arc_1999",
                    payload=race(position="2"),
                    singleton_identity=True,
                )

    def test_compact_export_keeps_only_target_runner_and_race_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            pool = self.module.ContentAddressedPool(Path(temporary) / "objects")

            compact = self.module.compact_targeted_export(export_result(), pool=pool)

            self.assertEqual(compact["schema_version"], "targeted-horse-pooled-export.v1")
            self.assertNotIn("races", compact["career"])
            self.assertEqual(len(compact["career"]["records"]), 1)
            record = compact["career"]["records"][0]
            self.assertEqual(record["target_runner"]["horse_id"], "hrs_1024")
            self.assertEqual(record["race_ref"]["identity"], "rac_arc_1999")
            self.assertEqual(pool.snapshot()["object_count"], 4)

    def test_compact_profile_only_export_keeps_career_without_claiming_target_race(self):
        with tempfile.TemporaryDirectory() as temporary:
            pool = self.module.ContentAddressedPool(Path(temporary) / "objects")
            result = export_result()
            result["identity_mode"] = "external_anchor_profile_only"
            result["target_race"] = None
            result["scope_target_races"] = []
            result["career_authority"] = {
                "status": "provider_partial",
                "basis": "target_occurrence_missing_from_provider_results",
            }
            result["target_occurrence"] = {
                "status": "missing_from_provider_results",
                "authority": "external_anchor",
            }

            compact = self.module.compact_targeted_export(result, pool=pool)

            self.assertIsNone(compact["target_race_id"])
            self.assertIsNone(compact["target_race_ref"])
            self.assertEqual(compact["scope_target_race_ids"], [])
            self.assertEqual(compact["scope_target_race_refs"], [])
            self.assertEqual(len(compact["career"]["records"]), 1)
            self.assertEqual(compact["career_authority"]["status"], "provider_partial")
            self.assertEqual(
                compact["target_occurrence"]["status"],
                "missing_from_provider_results",
            )

    def test_two_processes_publish_same_object_without_partial_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "objects"
            self.module.ContentAddressedPool(root)
            payload = json.dumps(race(), sort_keys=True)
            script = (
                "import json,sys;"
                f"sys.path.insert(0,{str(SCRIPT_PATH.parent)!r});"
                "from pathlib import Path;"
                "from racing_api_content_pool import ContentAddressedPool;"
                f"p=ContentAddressedPool(Path({str(root)!r}));"
                f"r=p.put_json(kind='race',identity='rac_arc_1999',payload=json.loads({payload!r}),singleton_identity=True);"
                "print(json.dumps(r,sort_keys=True))"
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(2)
            ]
            rows = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                rows.append(json.loads(stdout))

            self.assertEqual(rows[0], rows[1])
            pool = self.module.ContentAddressedPool(root)
            snapshot = pool.snapshot()
            self.assertEqual(snapshot["object_count"], 1)
            self.assertEqual(list(root.rglob(".object-*")), [])


if __name__ == "__main__":
    unittest.main()

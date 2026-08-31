#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_external_result_actual_starter_census.py")


def load_tool():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("external_starter_census", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrepareExternalResultActualStarterCensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def _write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _capture(self, root: Path) -> tuple[str, str, str]:
        source = b"""
        <html><head><title>Irish Champion Stakes (G1) Full Result | 14 SEP 2024 R5</title></head>
        <body><span class='RaceName_main'>Irish Champion Stakes</span>
        <span class='Icon_GradeType Icon_GradeType1'>G1</span>
        <table class='ResultsByRaceDetail'><tbody>
        <tr><td>1</td><td></td><td>5</td><td>Economics</td><td>3C</td><td>58.5</td><td>T.Marquand</td><td>2:03.20</td><td></td><td></td><td></td><td>3.0</td><td>2</td><td>N/A</td><td>W.Haggas</td></tr>
        <tr><td>2</td><td></td><td>1</td><td>Auguste Rodin</td><td>4H</td><td>61</td><td>R.Moore</td><td>2:03.2</td><td>nk</td><td></td><td></td><td>2.7</td><td>1</td><td>N/A</td><td>A.O'brien</td></tr>
        </tbody></table></body></html>
        """
        source_path = root / "sources" / "result.html"
        source_path.parent.mkdir(parents=True)
        source_path.write_bytes(source)
        source_sha = self.module.sha256_path(source_path)
        reference = {
            "race_id": "2024B1091405",
            "result": {
                "grade_text": "G1",
                "local_date": "2024-09-14",
                "parsed_result_rows": 2,
                "race_name": "Irish Champion Stakes",
                "winner_finish_position": "1",
                "winner_name": "Economics",
            },
            "schema_version": "manual-netkeiba-result-reference.v1",
            "source": {
                "cache_path": str(source_path.resolve()),
                "sha256": source_sha,
                "size": source_path.stat().st_size,
                "url": "https://en.netkeiba.com/db/race/2024B1091405/",
            },
            "source_authority": "human_reviewed_reference",
            "status": "proposed_not_approved",
            "systematic_reuse_approved": False,
        }
        reference_path = root / "winner-reference.json"
        self._write_json(reference_path, reference)
        reference_sha = self.module.sha256_path(reference_path)
        manifest = {
            "approval": False,
            "completion_marker": "PREPARED",
            "database_writes": 0,
            "network_requests": 1,
            "reference": {
                "path": "winner-reference.json",
                "sha256": reference_sha,
                "size": reference_path.stat().st_size,
            },
            "schema_version": "manual-netkeiba-result-reference.v1",
            "source": {
                "path": "result.html",
                "sha256": source_sha,
                "size": source_path.stat().st_size,
                "source_url": "https://en.netkeiba.com/db/race/2024B1091405/",
            },
            "status": "PROPOSED_NOT_APPROVED",
        }
        manifest_path = root / "capture-manifest.json"
        self._write_json(manifest_path, manifest)
        manifest_sha = self.module.sha256_path(manifest_path)
        (root / "PREPARED").write_text(manifest_sha + "\n", encoding="ascii")
        return manifest_sha, reference_sha, source_sha

    def _stable(self, root: Path, *, second_name: str = "Auguste Rodin (IRE)") -> str:
        target = {
            "canonical_name_original": "Royal Bahrain Irish Champion Stakes (Group 1)",
            "country_region": "ireland",
            "discipline": "flat",
            "grade_text": "G1",
            "local_date": "2024-09-14",
            "race_name_aliases": [],
            "racecourse": "Leopardstown",
            "racecourse_aliases": [],
            "year": 2024,
        }
        rows = []
        for horse_id, name, position in (
            ("hrs_1", "Economics (GB)", "1"),
            ("hrs_2", second_name, "2"),
        ):
            rows.append(
                {
                    "horse_id": horse_id,
                    "schema_version": "targeted-runner-stable-id-seed.v2",
                    "seed_id": f"target-runner-{horse_id}",
                    "source_names": [name],
                    "source_targeted_batch_manifest_sha256s": ["1" * 64],
                    "target_occurrences": [
                        {
                            "race_id": "rac_11309415",
                            "source_materialized_run_manifest_sha256": "2" * 64,
                            "source_runner_name": name,
                            "source_runner_payload_sha256": ("3" if horse_id == "hrs_1" else "4") * 64,
                            "source_runner_position": position,
                            "source_targeted_seed_id": "sample-winner-b2f8aa520e57d2a63522",
                            "target": target,
                            "target_race_payload_sha256": "5" * 64,
                        }
                    ],
                }
            )
        ledger = root / "target-runner-stable-id-seeds.v2.jsonl"
        ledger.parent.mkdir(parents=True)
        ledger.write_text(
            "".join(self.module.canonical_json(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        manifest = {
            "database_writes": 0,
            "network_requests": 0,
            "schema_version": "target-runner-stable-id-ledger.v2",
            "seed_ledger": {
                "path": ledger.name,
                "rows": len(rows),
                "sha256": self.module.sha256_path(ledger),
                "size": ledger.stat().st_size,
            },
            "source_target_occurrence_count": len(rows),
            "status": "complete",
            "unique_target_race_count": 1,
        }
        manifest_path = root / "manifest.json"
        self._write_json(manifest_path, manifest)
        manifest_sha = self.module.sha256_path(manifest_path)
        (root / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
        return manifest_sha

    def _build(self, temporary: str, *, second_name: str = "Auguste Rodin (IRE)"):
        base = Path(temporary)
        capture_root = base / "capture"
        capture_root.mkdir()
        capture_sha, reference_sha, source_sha = self._capture(capture_root)
        stable_root = base / "stable"
        stable_sha = self._stable(stable_root, second_name=second_name)
        output = base / "proposal"
        manifest = self.module.build_proposal(
            capture_root=capture_root,
            expected_capture_manifest_sha256=capture_sha,
            expected_reference_sha256=reference_sha,
            expected_source_sha256=source_sha,
            stable_runner_ledger_root=stable_root,
            expected_stable_runner_manifest_sha256=stable_sha,
            source_targeted_seed_id="sample-winner-b2f8aa520e57d2a63522",
            target_key="ireland:2024:ireland-irish-champion:flat",
            output_dir=output,
        )
        return output, manifest

    def test_builds_zero_write_unapproved_two_runner_proposal(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, manifest = self._build(temporary)
            self.assertEqual(manifest["status"], "PREPARED_NOT_EXECUTABLE")
            self.assertFalse(manifest["approval"])
            self.assertEqual(manifest["network_requests"], 0)
            self.assertEqual(manifest["database_writes"], 0)
            self.assertEqual(manifest["counts"]["actual_starter_occurrences"], 2)
            census = [
                json.loads(line)
                for line in (output / "actual-starter-census.jsonl").read_text().splitlines()
            ]
            crosswalk = [
                json.loads(line)
                for line in (output / "candidate-crosswalk.jsonl").read_text().splitlines()
            ]
            self.assertEqual([row["horse_name"] for row in census], ["Economics", "Auguste Rodin"])
            self.assertTrue(all(row["provider_horse_id"] is None for row in census))
            self.assertEqual(
                [row["candidate_provider_horse_id"] for row in crosswalk],
                ["hrs_1", "hrs_2"],
            )
            self.assertTrue(all(not row["provider_horse_id_assigned"] for row in crosswalk))
            loaded_starters, loaded_crosswalk, identity = self.module.load_proposal(
                output,
                expected_manifest_sha256=self.module.sha256_path(output / "proposal-manifest.json"),
            )
            self.assertEqual(len(loaded_starters), 2)
            self.assertEqual(len(loaded_crosswalk), 2)
            self.assertFalse(identity["approval"])

    def test_rejects_name_position_mismatch_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "unique name/position"):
                self._build(temporary, second_name="Wrong Horse (IRE)")
            self.assertFalse((Path(temporary) / "proposal").exists())

    def test_rejects_source_sha_drift_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            capture_root = base / "capture"
            capture_root.mkdir()
            capture_sha, reference_sha, source_sha = self._capture(capture_root)
            stable_root = base / "stable"
            stable_sha = self._stable(stable_root)
            with self.assertRaisesRegex(ValueError, "captured result page SHA-256 mismatch"):
                self.module.build_proposal(
                    capture_root=capture_root,
                    expected_capture_manifest_sha256=capture_sha,
                    expected_reference_sha256=reference_sha,
                    expected_source_sha256="0" * 64,
                    stable_runner_ledger_root=stable_root,
                    expected_stable_runner_manifest_sha256=stable_sha,
                    source_targeted_seed_id="sample-winner-b2f8aa520e57d2a63522",
                    target_key="ireland:2024:ireland-irish-champion:flat",
                    output_dir=base / "proposal",
                )
            self.assertEqual(len(source_sha), 64)
            self.assertFalse((base / "proposal").exists())


if __name__ == "__main__":
    unittest.main()

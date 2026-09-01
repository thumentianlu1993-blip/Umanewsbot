#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import importlib.util
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).with_name("racing_api_targeted_batch_export.py")


def load_tool():
    if not SCRIPT_PATH.is_file():
        raise AssertionError(f"目标入口尚不存在：{SCRIPT_PATH}")
    sys.path.insert(0, str(SCRIPT_PATH.parent))
    spec = importlib.util.spec_from_file_location("racing_api_targeted_batch_export", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载目标入口：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def seed(seed_id: str):
    return {
        "schema_version": "targeted-horse-seed.v1",
        "seed_id": seed_id,
        "name": "Montjeu",
        "country_suffix": "IRE",
        "expected_finish_position": "1",
        "source_authority": "official_operator_archived_result",
        "source_url": "https://example.test/official-result",
        "source_payload_sha256": "a" * 64,
        "target": {
            "year": 1999,
            "country_region": "france",
            "local_date": "1999-10-03",
            "canonical_name_original": "Prix de l'Arc de Triomphe",
            "racecourse": "Longchamp",
            "grade_text": "G1",
            "discipline": "flat",
        },
    }


def arc_result():
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
            {"horse_id": "hrs_1024", "horse": "Montjeu (IRE)", "position": "1", "number": "7"}
        ],
    }


def profile():
    return {
        "id": "hrs_1024",
        "name": "Montjeu (IRE)",
        "dob": "1996-04-04",
        "sex": "horse",
        "sex_code": "H",
        "colour": "bay",
        "colour_code": "B",
        "breeder": "Sir James Goldsmith",
        "sire": "Sadler's Wells (USA)",
        "sire_id": "sir_100",
        "dam": "Floripedes (FR)",
        "dam_id": "dam_200",
        "damsire": "Top Ville (IRE)",
        "damsire_id": "dsi_300",
    }


class FakeClient:
    def __init__(self, request_ceiling: int):
        self.request_ceiling = request_ceiling
        self.request_count = 0
        self.request_ledger = []

    def request_json(self, url, *, allow_not_found=False):
        self.request_count += 1
        self.request_ledger.append({"url": url, "status": 200})
        if "/search?" in url:
            return {"search_results": [{"id": "hrs_1024", "name": "Montjeu (IRE)"}]}
        if "/hrs_100/pro" in url:
            return {
                **profile(),
                "id": "hrs_100",
                "name": "Sadler's Wells (USA)",
                "sire_id": "",
                "dam_id": "",
                "damsire_id": "",
            }
        if "/hrs_200/pro" in url:
            return {
                **profile(),
                "id": "hrs_200",
                "name": "Floripedes (FR)",
                "sire_id": "",
                "dam_id": "",
                "damsire_id": "",
            }
        if url.endswith("/pro"):
            return profile()
        return {"results": [arc_result()], "total": 1, "limit": 100, "skip": 0, "query": []}


class RacingApiTargetedBatchExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = load_tool()

    def _ledger(self, root: Path) -> tuple[Path, str]:
        path = root / "seeds.jsonl"
        path.write_text(
            "".join(json.dumps(seed(value), sort_keys=True) + "\n" for value in ("seed-a", "seed-b")),
            encoding="utf-8",
        )
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _openapi_fingerprint(self, root: Path) -> tuple[Path, str, dict]:
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
        return path, sha256, self.module.load_openapi_fingerprint(path, sha256)

    def test_request_ceiling_formula_is_exact_per_seed(self):
        self.assertEqual(
            self.module.targeted_request_ceiling(
                seed_count=2,
                max_search_candidates=3,
                max_results_pages_per_horse=3,
                max_parent_profiles=2,
            ),
            32,
        )

    def test_stable_id_seed_ceiling_has_no_search_candidate_multiplier(self):
        for version in ("v1", "v2"):
            with self.subTest(version=version):
                stable_seed = {
                    "schema_version": f"targeted-runner-stable-id-seed.{version}",
                    "seed_id": f"stable-{version}",
                }
                self.assertEqual(
                    self.module.seed_request_ceiling(
                        stable_seed,
                        max_search_candidates=10,
                        max_results_pages_per_horse=3,
                        max_parent_profiles=2,
                    ),
                    9,
                )

    def test_v2_date_optional_seed_ledger_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row = seed("seed-v2")
            row["schema_version"] = "targeted-horse-seed.v2"
            row["target"].pop("local_date")
            row["target"]["edition_year"] = row["target"]["year"]
            ledger = root / "seeds.jsonl"
            ledger.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
            ledger_sha = hashlib.sha256(ledger.read_bytes()).hexdigest()

            rows, identity = self.module._load_seed_ledger(ledger, ledger_sha)

            self.assertEqual(rows, [row])
            self.assertEqual(identity["rows"], 1)
            self.assertEqual(
                self.module.seed_request_ceiling(
                    row,
                    max_search_candidates=3,
                    max_results_pages_per_horse=3,
                    max_parent_profiles=2,
                ),
                16,
            )

    def test_content_addressed_seed_ledger_rejects_ambiguous_json(self):
        base = json.dumps(seed("seed-ambiguous"), sort_keys=True)
        cases = {
            "duplicate_key": base.replace(
                '"seed_id": "seed-ambiguous"',
                '"seed_id": "seed-ambiguous", "seed_id": "seed-ambiguous"',
                1,
            ),
            "nonfinite_value": base[:-1] + ', "unexpected": Infinity}',
        }
        for case_name, payload in cases.items():
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as temporary:
                ledger = Path(temporary) / "seeds.jsonl"
                ledger.write_text(payload + "\n", encoding="utf-8")
                ledger_sha = hashlib.sha256(ledger.read_bytes()).hexdigest()

                with self.assertRaisesRegex(ValueError, "invalid seed JSONL"):
                    self.module._load_seed_ledger(ledger, ledger_sha)

        batch_cases = {
            "duplicate_key": '{"schema_version":"x","schema_version":"x"}',
            "nonfinite_value": '{"schema_version":Infinity}',
        }
        for case_name, payload in batch_cases.items():
            with self.subTest(batch_json=case_name), tempfile.TemporaryDirectory() as temporary:
                batch_file = Path(temporary) / "batch-definition.json"
                batch_file.write_text(payload + "\n", encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "invalid batch JSON"):
                    self.module._read_json(batch_file)

    def test_batch_writes_checkpoint_and_complete_then_resume_is_zero_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger, ledger_sha = self._ledger(root)
            output = root / "output"
            client = FakeClient(request_ceiling=8)
            _fingerprint_path, _fingerprint_sha, fingerprint_identity = self._openapi_fingerprint(root)

            manifest = self.module.run_targeted_batch_artifact(
                seed_ledger_path=ledger,
                approved_seed_ledger_sha256=ledger_sha,
                output_dir=output,
                client=client,
                max_search_candidates=1,
                max_results_pages_per_horse=1,
                max_parent_profiles=0,
                openapi_fingerprint_identity=fingerprint_identity,
            )

            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["completed_seed_count"], 2)
            self.assertTrue((output / "COMPLETE").is_file())
            self.assertEqual(client.request_count, 3)
            self.assertEqual(manifest["request_ceiling"], 8)
            self.assertEqual(manifest["request_cache"]["hit_count"], 3)
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(len(checkpoint["completed"]), 2)
            pool_manifest = json.loads(
                (output / "content-pool-manifest.json").read_text(encoding="utf-8")
            )
            race_entries = [
                entry
                for entry in pool_manifest["entries"].values()
                if entry["kind"] == "race"
            ]
            self.assertEqual(len(race_entries), 1)
            self.assertEqual(race_entries[0]["identity"], "rac_arc_1999")
            self.assertEqual(len(race_entries[0]["hashes"]), 1)
            pooled_rows = []
            for completed in checkpoint["completed"].values():
                attempt = output / completed["artifact_dir"]
                pooled = json.loads(
                    (attempt / "normalized" / "targeted-horse-export-ref.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertNotIn("races", pooled["career"])
                pooled_rows.append(pooled)
            self.assertEqual(
                pooled_rows[0]["career"]["records"][0]["race_ref"],
                pooled_rows[1]["career"]["records"][0]["race_ref"],
            )

            class NoRequestClient:
                request_ceiling = 0
                request_count = 0
                request_ledger = []

                def request_json(self, *_args, **_kwargs):
                    raise AssertionError("completed batch must not request again")

            replay = self.module.run_targeted_batch_artifact(
                seed_ledger_path=ledger,
                approved_seed_ledger_sha256=ledger_sha,
                output_dir=output,
                client=NoRequestClient(),
                max_search_candidates=1,
                max_results_pages_per_horse=1,
                max_parent_profiles=0,
                openapi_fingerprint_identity=fingerprint_identity,
                resume=True,
            )

            self.assertEqual(replay["status"], "replayed")
            self.assertEqual(replay["database_writes"], 0)

    def test_semantic_identity_gap_is_bound_and_does_not_block_later_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger, ledger_sha = self._ledger(root)
            output = root / "output"
            client = FakeClient(request_ceiling=8)
            _fingerprint_path, _fingerprint_sha, fingerprint_identity = (
                self._openapi_fingerprint(root)
            )
            original = self.module.run_targeted_seed_artifact
            call_count = 0

            def first_seed_is_a_gap(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count != 1:
                    return original(**kwargs)
                artifact_dir = kwargs["output_dir"]
                artifact_dir.mkdir(parents=True)
                failure = artifact_dir / "run-failure.json"
                failure.write_text(
                    json.dumps(
                        {
                            "schema_version": "targeted-horse-run-failure.v1",
                            "status": "failed",
                            "database_writes": 0,
                            "failure": {
                                "category": "semantic_gap",
                                "gap_code": "target_occurrence_identity_unresolved",
                            },
                        },
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                failure_sha = hashlib.sha256(failure.read_bytes()).hexdigest()
                (artifact_dir / "FAILED").write_text(
                    failure_sha + "\n",
                    encoding="ascii",
                )
                raise self.module.RacingApiSemanticGap(
                    "target_occurrence_identity_unresolved",
                    "target occurrence candidate count must be 1, got 0",
                )

            with mock.patch.object(
                self.module,
                "run_targeted_seed_artifact",
                side_effect=first_seed_is_a_gap,
            ):
                manifest = self.module.run_targeted_batch_artifact(
                    seed_ledger_path=ledger,
                    approved_seed_ledger_sha256=ledger_sha,
                    output_dir=output,
                    client=client,
                    max_search_candidates=1,
                    max_results_pages_per_horse=1,
                    max_parent_profiles=0,
                    openapi_fingerprint_identity=fingerprint_identity,
                )

            self.assertEqual(manifest["status"], "complete_with_gaps")
            self.assertEqual(manifest["completed_seed_count"], 1)
            self.assertEqual(manifest["gap_seed_count"], 1)
            self.assertEqual(set(manifest["completed"]), {"seed-b"})
            self.assertEqual(set(manifest["gaps"]), {"seed-a"})
            self.assertTrue((output / "COMPLETE").is_file())
            checkpoint = json.loads(
                (output / "checkpoint.json").read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["status"], "complete_with_gaps")
            self.assertEqual(
                checkpoint["gaps"]["seed-a"]["gap_code"],
                "target_occurrence_identity_unresolved",
            )

    def test_shared_parent_profiles_are_requested_once_per_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger, ledger_sha = self._ledger(root)
            output = root / "output"
            client = FakeClient(request_ceiling=16)
            _fingerprint_path, _fingerprint_sha, fingerprint_identity = self._openapi_fingerprint(root)

            manifest = self.module.run_targeted_batch_artifact(
                seed_ledger_path=ledger,
                approved_seed_ledger_sha256=ledger_sha,
                output_dir=output,
                client=client,
                max_search_candidates=1,
                max_results_pages_per_horse=1,
                max_parent_profiles=2,
                openapi_fingerprint_identity=fingerprint_identity,
            )

            self.assertEqual(manifest["request_ceiling"], 16)
            self.assertEqual(client.request_count, 5)
            self.assertEqual(manifest["request_cache"]["entry_count"], 5)
            self.assertEqual(manifest["request_cache"]["hit_count"], 5)
            parent_urls = [
                row["url"]
                for row in client.request_ledger
                if "/hrs_100/" in row["url"] or "/hrs_200/" in row["url"]
            ]
            self.assertEqual(len(parent_urls), 2)

    def test_stable_id_batch_skips_search_and_preserves_scope_race_refs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            race_payload = arc_result()
            horse_export = sys.modules["racing_api_horse_export"]
            stable = {
                "schema_version": "targeted-runner-stable-id-seed.v1",
                "seed_id": "stable-montjeu",
                "horse_id": "hrs_1024",
                "source_names": ["Montjeu (IRE)"],
                "source_targeted_batch_manifest_sha256": "b" * 64,
                "target_occurrences": [
                    {
                        "race_id": "rac_arc_1999",
                        "target_race_payload_sha256": horse_export.payload_sha256(race_payload),
                        "source_targeted_seed_id": "proof-arc",
                        "source_materialized_run_manifest_sha256": "c" * 64,
                        "source_runner_payload_sha256": "d" * 64,
                        "source_runner_name": "Montjeu (IRE)",
                        "source_runner_position": "1",
                        "target": seed("unused")["target"],
                    }
                ],
            }
            ledger = root / "stable-seeds.jsonl"
            ledger.write_text(json.dumps(stable, sort_keys=True) + "\n", encoding="utf-8")
            ledger_sha = hashlib.sha256(ledger.read_bytes()).hexdigest()
            client = FakeClient(request_ceiling=3)
            output = root / "output"
            _fingerprint_path, _fingerprint_sha, fingerprint_identity = self._openapi_fingerprint(root)

            manifest = self.module.run_targeted_batch_artifact(
                seed_ledger_path=ledger,
                approved_seed_ledger_sha256=ledger_sha,
                output_dir=output,
                client=client,
                max_search_candidates=10,
                max_results_pages_per_horse=1,
                max_parent_profiles=0,
                openapi_fingerprint_identity=fingerprint_identity,
            )

            self.assertEqual(manifest["completed_seed_count"], 1)
            self.assertEqual(client.request_count, 2)
            self.assertFalse(any("/search?" in row["url"] for row in client.request_ledger))
            receipt = manifest["completed"]["stable-montjeu"]
            compact = json.loads(
                (
                    output
                    / receipt["artifact_dir"]
                    / "normalized"
                    / "targeted-horse-export-ref.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(compact["scope_target_race_ids"], ["rac_arc_1999"])

    def test_network_cli_missing_credentials_stops_before_creating_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = root / "execution-ledger.json"
            fingerprint_path, fingerprint_sha, _fingerprint_identity = self._openapi_fingerprint(root)
            argv = [
                "racing_api_targeted_batch_export.py",
                "--seed-ledger", str(root / "seeds.jsonl"),
                "--approved-seed-ledger-sha256", "a" * 64,
                "--output-dir", str(root / "output"),
                "--request-ceiling", "4",
                "--allow-network",
                "--batch-plan-root", str(root / "plan"),
                "--approved-plan-manifest-sha256", "b" * 64,
                "--approved-batch-plan-sha256", "c" * 64,
                "--execution-ledger", str(ledger),
                "--g3-approval-root", str(root / "approval"),
                "--approved-g3-manifest-sha256", "d" * 64,
                "--openapi-fingerprint", str(fingerprint_path),
                "--approved-openapi-fingerprint-sha256", fingerprint_sha,
                "--account-budget-root", str(root / "budget"),
                "--credential-alias", "tra-primary",
                "--account-scope-id", "scope-1",
                "--account-scope-manifest-sha256", "e" * 64,
                "--account-request-ceiling", "4",
                "--exclusive-account-proof", str(root / "proof.json"),
                "--exclusive-account-proof-sha256", "f" * 64,
            ]
            environment = {
                **os.environ,
                "RACING_API_HORSE_EXPORT_NETWORK_ENABLED": "true",
                "RACING_API_USERNAME": "",
                "RACING_API_PASSWORD": "",
            }
            stderr = io.StringIO()
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.dict(os.environ, environment, clear=True),
                contextlib.redirect_stderr(stderr),
            ):
                result = self.module.main()
            self.assertEqual(result, self.module.SAFE_STOP_EXIT_CODE)
            self.assertIn("credentials are required", stderr.getvalue())
            self.assertFalse(ledger.exists())

    def test_network_cli_passes_loaded_openapi_identity_to_batch_runner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fingerprint_identity = {"contract": "frozen"}
            args = Namespace(
                allow_network=True,
                openapi_fingerprint=root / "openapi.json",
                approved_openapi_fingerprint_sha256="a" * 64,
                batch_plan_root=root / "plan",
                approved_plan_manifest_sha256="b" * 64,
                approved_batch_plan_sha256="c" * 64,
                execution_ledger=root / "execution-ledger.json",
                g3_approval_root=root / "approval",
                approved_g3_manifest_sha256="d" * 64,
                exclusive_account_proof=root / "proof.json",
                exclusive_account_proof_sha256="e" * 64,
                seed_ledger=root / "seeds.jsonl",
                approved_seed_ledger_sha256="f" * 64,
                output_dir=root / "output",
                account_budget_root=root / "budget",
                credential_alias="tra-primary",
                account_scope_id="scope-1",
                account_scope_manifest_sha256="1" * 64,
                request_ceiling=4,
                account_request_ceiling=4,
                max_search_candidates=1,
                max_results_pages_per_horse=1,
                max_parent_profiles=0,
                resume=False,
            )
            execution = __import__("racing_api_targeted_batch_execution_ledger")
            observed = {}
            observed_claim = {}

            def run_batch(**kwargs):
                observed.update(kwargs)
                return {
                    "status": "complete",
                    "completed_seed_count": 1,
                    "request_count": 2,
                }

            def claim_batch(**kwargs):
                observed_claim.update(kwargs)
                return {"claim_token": "token"}

            environment = {
                **os.environ,
                "RACING_API_HORSE_EXPORT_NETWORK_ENABLED": "true",
                "RACING_API_USERNAME": "present",
                "RACING_API_PASSWORD": "present",
            }
            with (
                mock.patch.object(self.module, "parse_args", return_value=args),
                mock.patch.object(
                    self.module,
                    "load_openapi_fingerprint",
                    return_value=fingerprint_identity,
                ),
                mock.patch.object(
                    execution,
                    "claim_batch_execution",
                    side_effect=claim_batch,
                ),
                mock.patch.object(
                    execution,
                    "complete_batch_execution",
                    return_value={
                        "batch_id": "sample",
                        "total_request_count": 2,
                    },
                ),
                mock.patch.object(self.module, "build_exclusive_account_budget", return_value=object()),
                mock.patch.object(self.module, "RacingApiClient", return_value=object()),
                mock.patch.object(
                    self.module,
                    "run_targeted_batch_artifact",
                    side_effect=run_batch,
                ),
                mock.patch.dict(os.environ, environment, clear=True),
            ):
                result = self.module.main()
            self.assertEqual(result, 0)
            self.assertEqual(
                observed_claim["openapi_fingerprint_path"], args.openapi_fingerprint
            )
            self.assertEqual(
                observed_claim["approved_openapi_fingerprint_sha256"],
                args.approved_openapi_fingerprint_sha256,
            )
            self.assertNotIn("openapi_fingerprint_identity", observed_claim)
            self.assertIs(observed["openapi_fingerprint_identity"], fingerprint_identity)
            self.assertNotIn("openapi_fingerprint_path", observed)


if __name__ == "__main__":
    unittest.main()

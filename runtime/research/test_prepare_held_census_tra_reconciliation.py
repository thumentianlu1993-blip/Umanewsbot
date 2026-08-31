#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_held_census_tra_reconciliation.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("held_census_tra_reconciliation", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class HeldCensusTraReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def census_row(self, key: str, name: str) -> dict:
        return {
            "target_key": "france:2026:france-test:flat",
            "starter_occurrence_key": key,
            "source_runner_key": f"source:{key}",
            "horse_name": name,
            "source_payload_sha256": "a" * 64,
            "provider_horse_id": None,
        }

    def summary(self) -> dict:
        return {
            "target_key": "france:2026:france-test:flat",
            "country_region": "france",
            "local_date": "2026-01-02",
            "grade": "G3",
            "discipline": "flat",
        }

    def occurrence(self, name: str, position: str, *, seed_id: str = "seed-one") -> dict:
        return {
            "race_id": "rac_test",
            "source_targeted_seed_id": seed_id,
            "source_runner_name": name,
            "source_runner_position": position,
            "source_runner_payload_sha256": "b" * 64,
            "source_materialized_run_manifest_sha256": "c" * 64,
            "target": {
                "country_region": "france",
                "local_date": "2026-01-02",
                "grade_text": "G3",
                "discipline": "flat",
            },
        }

    def approved_seed_artifact(self, root: Path):
        proposal_root = root / "proposal"
        proposal_root.mkdir()
        output_shas = {
            "all-held-targeted-horse-seeds.jsonl": "4" * 64,
            "existing-seed-bindings.jsonl": "5" * 64,
            "new-seed-candidates.jsonl": "6" * 64,
        }
        proposal_identity = {
            "root": str(proposal_root),
            "manifest_sha256": "7" * 64,
            "outputs": {
                name: {"sha256": sha, "rows": 1}
                for name, sha in output_shas.items()
            },
        }
        target_identity = {"manifest_sha256": "8" * 64, "ledger_sha256": "9" * 64}
        approved_root = root / "approved"
        approved_root.mkdir()
        seed = {
            "schema_version": "targeted-horse-seed.v1",
            "seed_id": "seed-one",
            "name": "Alpha",
            "target": {
                "country_region": "france",
                "local_date": "2026-01-02",
                "grade_text": "G3",
                "discipline": "flat",
            },
        }
        ledger = (json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        ledger_path = approved_root / "targeted-horse-seeds.jsonl"
        ledger_path.write_bytes(ledger)
        ledger_sha = hashlib.sha256(ledger).hexdigest()
        manifest = {
            "schema_version": "targeted-horse-seed-ledger.v1",
            "status": "complete",
            "completion_marker": "COMPLETE",
            "target_manifest_sha256": target_identity["manifest_sha256"],
            "target_ledger_sha256": target_identity["ledger_sha256"],
            "seed_ledger": {
                "path": ledger_path.name,
                "rows": 1,
                "size": len(ledger),
                "sha256": ledger_sha,
            },
            "held_winner_seed_extension_approval": {
                "proposal_root": str(proposal_root),
                "proposal_manifest_sha256": proposal_identity["manifest_sha256"],
                "approved_outputs": output_shas,
                "decision_sha256": "a" * 64,
                "independence_acknowledgement": "REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR",
            },
        }
        manifest_path = approved_root / "seed-ledger-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (approved_root / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
        return approved_root, manifest_sha, ledger_sha, target_identity, proposal_identity

    def build(self, root: Path, census: list[dict], stable: list[dict]):
        return self.module.build_proposal(
            census_rows=census,
            census_summaries=[self.summary()],
            census_identity={"manifest_sha256": "d" * 64},
            seed_to_target={"seed-one": "france:2026:france-test:flat"},
            seed_identity={"manifest_sha256": "e" * 64},
            approved_seed_identity={"manifest_sha256": "1" * 64},
            stable_rows=stable,
            stable_identity={"manifest_sha256": "f" * 64},
            output_dir=root / "output",
        )

    def seed_proposal(
        self,
        root: Path,
        *,
        replacement_candidate_target: str | None = None,
        keep_replaced_seed: bool = False,
    ) -> tuple[Path, str, set[str]]:
        proposal = root / "seed-proposal"
        proposal.mkdir()
        target_a = "france:2026:france-a:flat"
        target_b = "france:2026:france-b:flat"
        replacement_id = "held-winner-a"
        bindings = [
            {
                "disposition": "replace_conflicting_existing_seed",
                "seed_id": "legacy-winner-a",
                "seed_sha256": "1" * 64,
                "replacement_seed_id": replacement_id,
                "replacement_seed_sha256": "2" * 64,
                "target_key": target_a,
            },
            {
                "disposition": "reuse_existing_complete_seed",
                "seed_id": "legacy-winner-b",
                "seed_sha256": "3" * 64,
                "target_key": target_b,
            },
        ]
        candidates = [
            {
                "disposition": "replace_conflicting_existing_seed",
                "replaced_seed_id": "legacy-winner-a",
                "replaced_seed_sha256": "1" * 64,
                "target_key": replacement_candidate_target or target_a,
                "seed": {
                    "schema_version": "targeted-horse-seed.v1",
                    "seed_id": replacement_id,
                    "name": "Correct Winner",
                    "target": {"country_region": "france"},
                },
            }
        ]
        combined = [
            {
                "schema_version": "targeted-horse-seed.v1",
                "seed_id": "legacy-winner-a" if keep_replaced_seed else replacement_id,
                "name": "Correct Winner",
                "target": {"country_region": "france"},
            },
            {
                "schema_version": "targeted-horse-seed.v1",
                "seed_id": "legacy-winner-b",
                "name": "Other Winner",
                "target": {"country_region": "france"},
            },
        ]
        outputs = {}
        for filename, rows in (
            ("existing-seed-bindings.jsonl", bindings),
            ("new-seed-candidates.jsonl", candidates),
            ("all-held-targeted-horse-seeds.jsonl", combined),
        ):
            path = proposal / filename
            payload = "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
                for row in rows
            ).encode("utf-8")
            path.write_bytes(payload)
            outputs[filename] = {
                "path": filename,
                "rows": len(rows),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        manifest = {
            "schema_version": self.module.SEED_PROPOSAL_SCHEMA_VERSION,
            "status": "PREPARED_NOT_EXECUTABLE",
            "outputs": outputs,
        }
        manifest_path = proposal / "proposal-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (proposal / "PREPARED").write_text(manifest_sha + "\n", encoding="ascii")
        return proposal, manifest_sha, {target_a, target_b}

    def test_unique_occurrence_names_create_review_candidates_not_approved_bindings(self):
        census = [self.census_row("slot-a", "Alpha GB"), self.census_row("slot-b", "Beta")]
        stable = [
            {
                "horse_id": "hrs_a",
                "target_occurrences": [self.occurrence("Alpha (GB)", "1")],
            },
            {
                "horse_id": "hrs_b",
                "target_occurrences": [self.occurrence("Beta", "PU")],
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.build(root, census, stable)
            rows = [
                json.loads(line)
                for line in (root / "output" / "binding-candidates.jsonl").read_text().splitlines()
            ]
        self.assertEqual(manifest["counts"]["unique_binding_candidates"], 2)
        self.assertEqual(manifest["counts"]["review_items"], 0)
        self.assertFalse(manifest["execution_ready"])
        self.assertTrue(all(row["binding_status"].endswith("requires_review") for row in rows))
        self.assertEqual({row["tra_horse_id"] for row in rows}, {"hrs_a", "hrs_b"})

    def test_duplicate_recall_name_does_not_auto_bind(self):
        census = [self.census_row("slot-a", "Same"), self.census_row("slot-b", "Same")]
        stable = [
            {"horse_id": "hrs_a", "target_occurrences": [self.occurrence("Same", "1")]},
            {"horse_id": "hrs_b", "target_occurrences": [self.occurrence("Same", "2")]},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.build(Path(temporary), census, stable)
        self.assertEqual(manifest["counts"]["unique_binding_candidates"], 0)
        self.assertEqual(manifest["counts"]["review_items"], 1)
        self.assertEqual(manifest["counts"]["source_slots_unmatched_or_ambiguous"], 2)

    def test_count_mismatch_is_visible_and_not_complete(self):
        census = [self.census_row("slot-a", "Alpha"), self.census_row("slot-b", "Beta")]
        stable = [{"horse_id": "hrs_a", "target_occurrences": [self.occurrence("Alpha", "1")]}]
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.build(Path(temporary), census, stable)
        self.assertEqual(manifest["counts"]["targets_with_count_mismatch"], 1)
        self.assertEqual(manifest["counts"]["source_slots_unmatched_or_ambiguous"], 1)
        self.assertEqual(manifest["status"], "PREPARED_NOT_EXECUTABLE")

    def test_stable_scope_only_reconciles_exact_referenced_held_targets(self):
        target_a = "france:2026:france-test:flat"
        target_b = "france:2025:france-other:flat"
        row_a = self.census_row("slot-a", "Alpha")
        row_b = {
            **self.census_row("slot-b", "Other"),
            "target_key": target_b,
        }
        summary_a = self.summary()
        summary_b = {
            **self.summary(),
            "target_key": target_b,
            "local_date": "2025-01-02",
        }
        stable = [
            {
                "horse_id": "hrs_a",
                "target_occurrences": [self.occurrence("Alpha", "1")],
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.module.build_proposal(
                census_rows=[row_a, row_b],
                census_summaries=[summary_a, summary_b],
                census_identity={"manifest_sha256": "d" * 64},
                seed_to_target={"seed-one": target_a, "seed-two": target_b},
                seed_identity={"manifest_sha256": "e" * 64},
                approved_seed_identity={"manifest_sha256": "1" * 64},
                stable_rows=stable,
                stable_identity={"manifest_sha256": "f" * 64},
                output_dir=root / "output",
                stable_scope_only=True,
            )
            bindings = [
                json.loads(line)
                for line in (root / "output" / "binding-candidates.jsonl")
                .read_text()
                .splitlines()
            ]
        self.assertEqual(manifest["counts"]["targets"], 1)
        self.assertEqual(manifest["counts"]["expected_actual_starter_slots"], 1)
        self.assertEqual(manifest["scope"]["target_keys"], [target_a])
        self.assertEqual([row["starter_occurrence_key"] for row in bindings], ["slot-a"])

    def test_stable_scope_rejects_seed_outside_approved_held_map(self):
        stable = [
            {
                "horse_id": "hrs_a",
                "target_occurrences": [
                    self.occurrence("Alpha", "1", seed_id="external-seed")
                ],
            }
        ]
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
            ValueError, "outside approved held target map"
        ):
            self.module.build_proposal(
                census_rows=[self.census_row("slot-a", "Alpha")],
                census_summaries=[self.summary()],
                census_identity={"manifest_sha256": "d" * 64},
                seed_to_target={"seed-one": "france:2026:france-test:flat"},
                seed_identity={"manifest_sha256": "e" * 64},
                approved_seed_identity={"manifest_sha256": "1" * 64},
                stable_rows=stable,
                stable_identity={"manifest_sha256": "f" * 64},
                output_dir=Path(temporary) / "output",
                stable_scope_only=True,
            )

    def test_target_metadata_mismatch_fails(self):
        occurrence = self.occurrence("Alpha", "1")
        occurrence["target"]["local_date"] = "2026-01-03"
        stable = [{"horse_id": "hrs_a", "target_occurrences": [occurrence]}]
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "expected target summary"):
                self.build(Path(temporary), [self.census_row("slot-a", "Alpha")], stable)

    def test_non_runner_or_unresolved_tra_occurrence_fails(self):
        for position in ("NR", "mystery"):
            with self.subTest(position=position), tempfile.TemporaryDirectory() as temporary:
                stable = [
                    {
                        "horse_id": "hrs_a",
                        "target_occurrences": [self.occurrence("Alpha", position)],
                    }
                ]
                with self.assertRaisesRegex(ValueError, "non-runner or unresolved"):
                    self.build(Path(temporary), [self.census_row("slot-a", "Alpha")], stable)

    def test_same_tra_horse_cannot_repeat_within_target(self):
        stable = [
            {
                "horse_id": "hrs_a",
                "target_occurrences": [self.occurrence("Alpha", "1")],
            },
            {
                "horse_id": "hrs_a",
                "target_occurrences": [self.occurrence("Beta", "2")],
            },
        ]
        census = [self.census_row("slot-a", "Alpha"), self.census_row("slot-b", "Beta")]
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "duplicated within one target"):
                self.build(Path(temporary), census, stable)

    def test_approved_seed_artifact_must_bind_exact_proposal_and_seed_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.approved_seed_artifact(Path(temporary))
            seeds, identity = self.module.load_approved_seed_artifact(
                args[0],
                approved_manifest_sha256=args[1],
                approved_ledger_sha256=args[2],
                target_identity=args[3],
                proposal_identity=args[4],
                expected_seed_ids={"seed-one"},
            )
        self.assertEqual(set(seeds), {"seed-one"})
        self.assertEqual(identity["decision_sha256"], "a" * 64)

    def test_seed_target_map_uses_replacement_id_and_excludes_stale_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            proposal, manifest_sha, targets = self.seed_proposal(Path(temporary))
            mapping, _identity = self.module.load_seed_target_map(
                proposal,
                approved_manifest_sha256=manifest_sha,
                expected_target_keys=targets,
            )
        self.assertEqual(mapping["held-winner-a"], "france:2026:france-a:flat")
        self.assertEqual(mapping["legacy-winner-b"], "france:2026:france-b:flat")
        self.assertNotIn("legacy-winner-a", mapping)

    def test_seed_target_map_rejects_replacement_mismatch_or_stale_combined_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            proposal, manifest_sha, targets = self.seed_proposal(
                Path(temporary),
                replacement_candidate_target="france:2026:france-b:flat",
            )
            with self.assertRaisesRegex(ValueError, "replacement seed candidate"):
                self.module.load_seed_target_map(
                    proposal,
                    approved_manifest_sha256=manifest_sha,
                    expected_target_keys=targets,
                )
        with tempfile.TemporaryDirectory() as temporary:
            proposal, manifest_sha, targets = self.seed_proposal(
                Path(temporary), keep_replaced_seed=True
            )
            with self.assertRaisesRegex(ValueError, "seed-to-target conservation"):
                self.module.load_seed_target_map(
                    proposal,
                    approved_manifest_sha256=manifest_sha,
                    expected_target_keys=targets,
                )

    def test_unapproved_or_drifted_seed_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.approved_seed_artifact(Path(temporary))
            drifted_proposal = {**args[4], "manifest_sha256": "b" * 64}
            with self.assertRaisesRegex(ValueError, "exact held seed proposal"):
                self.module.load_approved_seed_artifact(
                    args[0],
                    approved_manifest_sha256=args[1],
                    approved_ledger_sha256=args[2],
                    target_identity=args[3],
                    proposal_identity=drifted_proposal,
                    expected_seed_ids={"seed-one"},
                )
            with self.assertRaisesRegex(ValueError, "exact held seed proposal"):
                self.module.load_approved_seed_artifact(
                    args[0],
                    approved_manifest_sha256=args[1],
                    approved_ledger_sha256=args[2],
                    target_identity=args[3],
                    proposal_identity=args[4],
                    expected_seed_ids={"seed-one", "seed-two"},
                )


if __name__ == "__main__":
    unittest.main()

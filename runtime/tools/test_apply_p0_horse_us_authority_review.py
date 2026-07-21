from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from runtime.tools.apply_p0_horse_us_authority_review import (
    DECISION_SCOPE,
    REVIEW_SCHEMA,
    TRUSTED_APPROVED_REVIEW_SHA256,
    TRUSTED_INPUT_SHA256,
    apply_authority_review,
    build_parser,
    canonical_json_bytes,
    prepare_review_manifest,
    strict_complete_horse_count,
)


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719"
)
INPUT_PATH = ARTIFACT_DIR / "p0_horse_research_50_enriched_v2.json"
REVIEW_PATH = ARTIFACT_DIR / "reviewed_us_career_source_authority_v1.json"
INPUT_RELATIVE_PATH = (
    "runtime/horse_profile_completion/pedigree-research-20260719/"
    "p0_horse_research_50_enriched_v2.json"
)


class P0HorseUsAuthorityReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.input_bytes = INPUT_PATH.read_bytes()
        cls.input_data = json.loads(cls.input_bytes)
        cls.approved_review_bytes = REVIEW_PATH.read_bytes()

    @staticmethod
    def review_bytes(manifest):
        return canonical_json_bytes(manifest)

    def approved_manifest(self):
        return json.loads(self.approved_review_bytes)

    def apply_review(
        self,
        input_bytes=None,
        *,
        review_bytes=None,
        expected_review_sha256=TRUSTED_APPROVED_REVIEW_SHA256,
    ):
        return apply_authority_review(
            input_bytes or self.input_bytes,
            review_bytes=(
                self.approved_review_bytes
                if review_bytes is None
                else review_bytes
            ),
            input_path=INPUT_RELATIVE_PATH,
            expected_review_sha256=expected_review_sha256,
        )

    def mutated_input(self, mutator):
        data = copy.deepcopy(self.input_data)
        mutator(data)
        return canonical_json_bytes(data)

    @staticmethod
    def horse(data, name):
        return next(
            horse
            for horse in data["horses"]
            if horse["candidate"]["horse_name"] == name
        )

    @staticmethod
    def with_current_input_sha(manifest, input_bytes):
        updated = copy.deepcopy(manifest)
        updated["input"]["sha256"] = hashlib.sha256(input_bytes).hexdigest()
        return updated

    def test_frozen_trust_anchors_match_actual_artifacts(self):
        self.assertEqual(
            hashlib.sha256(self.input_bytes).hexdigest(),
            TRUSTED_INPUT_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(self.approved_review_bytes).hexdigest(),
            TRUSTED_APPROVED_REVIEW_SHA256,
        )

    def test_prepare_only_creates_pending_with_separate_metadata(self):
        manifest = prepare_review_manifest(
            self.input_bytes,
            input_path=INPUT_RELATIVE_PATH,
            prepared_by="codex",
            prepared_at="2026-07-19T19:29:23Z",
        )

        self.assertEqual(manifest["review_status"], "pending")
        self.assertEqual(manifest["prepared_by"], "codex")
        self.assertIsNone(manifest["reviewed_by"])
        self.assertIsNone(manifest["approved_at"])
        self.assertIsNone(manifest["decision_source_reference"])
        self.assertEqual(manifest["decision_scope"], DECISION_SCOPE)

    def test_prepare_cli_exposes_no_approval_arguments(self):
        parser = build_parser()
        prepare_parser = next(
            action.choices["prepare"]
            for action in parser._actions
            if getattr(action, "choices", None)
            and "prepare" in action.choices
        )
        option_strings = {
            option
            for action in prepare_parser._actions
            for option in action.option_strings
        }
        self.assertNotIn("--review-status", option_strings)
        self.assertNotIn("--reviewed-by", option_strings)
        self.assertNotIn("--approved-at", option_strings)

    def test_prepare_cannot_create_an_approved_manifest(self):
        with self.assertRaisesRegex(
            ValueError,
            "prepare may only create a pending review artifact",
        ):
            prepare_review_manifest(
                self.input_bytes,
                input_path=INPUT_RELATIVE_PATH,
                prepared_by="codex",
                prepared_at="2026-07-19T19:29:23Z",
                review_status="approved",
                reviewed_by="self_asserted_reviewer",
                review_reference="self-asserted",
                review_recorded_at="2026-07-20T12:00:00Z",
            )

    def test_missing_review_artifact_keeps_us_partial(self):
        result = apply_authority_review(
            self.input_bytes,
            review_bytes=None,
            input_path=INPUT_RELATIVE_PATH,
            expected_review_sha256=TRUSTED_APPROVED_REVIEW_SHA256,
        )

        self.assertEqual(result["decision"], "blocked")
        self.assertIn("review_artifact_missing", result["blockers"])
        self.assertEqual(strict_complete_horse_count(result["data"]), 40)

    def test_missing_or_wrong_explicit_review_sha_blocks(self):
        for expected in (None, "0" * 64):
            with self.subTest(expected=expected):
                result = self.apply_review(
                    expected_review_sha256=expected,
                )
                self.assertEqual(result["decision"], "blocked")
                self.assertIn(
                    "review_artifact_sha256_not_independently_frozen",
                    result["blockers"],
                )

    def test_caller_sha_cannot_trust_a_self_made_manifest(self):
        manifest = self.approved_manifest()
        manifest["reviewed_by"] = "self_asserted_reviewer"
        review_bytes = self.review_bytes(manifest)
        self_made_sha = hashlib.sha256(review_bytes).hexdigest()

        result = self.apply_review(
            review_bytes=review_bytes,
            expected_review_sha256=self_made_sha,
        )

        self.assertEqual(result["decision"], "blocked")
        self.assertIn(
            "review_artifact_sha256_not_independently_frozen",
            result["blockers"],
        )

    def test_matching_independent_review_promotes_only_us_to_50(self):
        result = self.apply_review()

        self.assertEqual(result["decision"], "approved")
        self.assertEqual(result["module_review"]["approved_horse_count"], 10)
        report = result["readiness_report"]
        self.assertEqual(report["strict_complete_before"], 40)
        self.assertEqual(report["strict_complete_after"], 50)
        self.assertEqual(strict_complete_horse_count(result["data"]), 50)
        self.assertEqual(report["database_write_count"], 0)
        self.assertFalse(report["production_write_enabled"])
        self.assertEqual(
            [
                horse
                for horse in result["data"]["horses"]
                if horse["region"] != "united_states"
            ],
            [
                horse
                for horse in self.input_data["horses"]
                if horse["region"] != "united_states"
            ],
        )

    def test_manifest_metadata_and_source_composition_are_exact(self):
        manifest = self.approved_manifest()
        self.assertEqual(manifest["schema_version"], REVIEW_SCHEMA)
        self.assertEqual(manifest["review_status"], "approved")
        self.assertEqual(manifest["reviewed_by"], "project_owner")
        self.assertEqual(manifest["decision_scope"], DECISION_SCOPE)
        self.assertEqual(manifest["row_count"], 10)
        fort_george = next(
            row
            for row in manifest["horses"]
            if row["identity"]["horse_name"] == "Fort George"
        )
        self.assertEqual(
            fort_george["record_source_counts"],
            {
                "horseracingnation": 6,
                "sporting_life": 6,
                "racing_post": 1,
            },
        )
        for row in manifest["horses"]:
            if row["identity"]["horse_name"] != "Fort George":
                self.assertEqual(
                    row["record_source_counts"],
                    {"horseracingnation": row["record_count"]},
                )

    def test_input_or_manifest_input_sha_drift_blocks(self):
        changed = self.mutated_input(
            lambda data: data.update({"generated_at": "drifted"})
        )
        manifest = self.with_current_input_sha(
            self.approved_manifest(),
            changed,
        )
        review_bytes = self.review_bytes(manifest)
        result = self.apply_review(
            changed,
            review_bytes=review_bytes,
            expected_review_sha256=hashlib.sha256(review_bytes).hexdigest(),
        )

        self.assertEqual(result["decision"], "blocked")
        self.assertIn(
            "input_sha256_not_trusted_frozen_v2",
            result["blockers"],
        )
        self.assertIn(
            "review_artifact_sha256_not_independently_frozen",
            result["blockers"],
        )

    def test_record_drift_blocks(self):
        changed = self.mutated_input(
            lambda data: self.horse(data, "Bullard")["career"]["records"][
                0
            ].update({"race_name": "DRIFTED RACE"})
        )
        manifest = self.with_current_input_sha(
            self.approved_manifest(),
            changed,
        )
        result = self.apply_review(
            changed,
            review_bytes=self.review_bytes(manifest),
        )
        self.assertEqual(result["decision"], "blocked")
        self.assertIn(
            "record_set_sha256_mismatch:Bullard",
            result["blockers"],
        )

    def test_source_policy_and_illegal_source_drift_block(self):
        manifest = self.approved_manifest()
        manifest["allowed_source_policy"]["Fort George"] = {
            "horseracingnation": 7,
            "sporting_life": 6,
        }
        result = self.apply_review(
            review_bytes=self.review_bytes(manifest),
        )
        self.assertIn("allowed_source_policy_mismatch", result["blockers"])

        changed = self.mutated_input(
            lambda data: self.horse(data, "Bullard")["career"]["records"][
                0
            ].update({"source_url": "https://example.com/not-reviewed"})
        )
        changed_manifest = self.with_current_input_sha(
            self.approved_manifest(),
            changed,
        )
        result = self.apply_review(
            changed,
            review_bytes=self.review_bytes(changed_manifest),
        )
        self.assertIn("record_source_not_allowed:Bullard", result["blockers"])

    def test_count_identity_and_quality_drift_block(self):
        mutations = {
            "official_start_count_evidence": lambda horse: horse[
                "career"
            ].update({"official_or_source_start_count": 999}),
            "identity": lambda horse: horse["identity"].update(
                {"birth_year": 2021}
            ),
            "missing": lambda horse: horse["field_status"].update(
                {"career_missing_start_count": 1}
            ),
            "excess": lambda horse: horse["field_status"].update(
                {"career_excess_start_count": 1}
            ),
            "unknown": lambda horse: horse["field_status"].update(
                {"unknown_record_count": 1}
            ),
            "conflict": lambda horse: horse.setdefault(
                "pedigree_field_evidence",
                [],
            ).append({"field_name": "sire", "status": "conflict"}),
        }
        for label, mutate_horse in mutations.items():
            with self.subTest(label=label):
                changed = self.mutated_input(
                    lambda data: mutate_horse(
                        self.horse(data, "Bullard")
                    )
                )
                manifest = self.with_current_input_sha(
                    self.approved_manifest(),
                    changed,
                )
                result = self.apply_review(
                    changed,
                    review_bytes=self.review_bytes(manifest),
                )
                self.assertEqual(result["decision"], "blocked")
                self.assertTrue(
                    any(label in blocker for blocker in result["blockers"]),
                    result["blockers"],
                )

    def test_equal_count_record_replacement_is_duplicate(self):
        changed = copy.deepcopy(self.input_data)
        records = self.horse(changed, "Bullard")["career"]["records"]
        records[-1] = copy.deepcopy(records[0])
        records[-1]["external_result_id"] = ""
        records[-1]["external_race_id"] = ""

        with self.assertRaisesRegex(
            ValueError,
            "duplicate stable record key|duplicate canonical race key",
        ):
            prepare_review_manifest(
                canonical_json_bytes(changed),
                input_path=INPUT_RELATIVE_PATH,
                prepared_by="codex",
                prepared_at="2026-07-19T19:29:23Z",
            )

    def test_duplicate_source_bound_record_id_is_rejected(self):
        for field_name in ("external_result_id", "external_race_id"):
            with self.subTest(field_name=field_name):
                changed = copy.deepcopy(self.input_data)
                records = self.horse(
                    changed,
                    "Bullard",
                )["career"]["records"]
                records[0][field_name] = "duplicate-source-id"
                records[1][field_name] = "duplicate-source-id"

                with self.assertRaisesRegex(
                    ValueError,
                    "duplicate source-bound record ID",
                ):
                    prepare_review_manifest(
                        canonical_json_bytes(changed),
                        input_path=INPUT_RELATIVE_PATH,
                        prepared_by="codex",
                        prepared_at="2026-07-19T19:29:23Z",
                    )

    def test_research_derivative_is_not_production_ready(self):
        result = self.apply_review()
        report = result["readiness_report"]

        self.assertEqual(report["mode"], "production_readiness_report")
        self.assertEqual(report["decision"], "blocked")
        self.assertFalse(report["commit_artifact_compatible"])
        self.assertFalse(
            report["ready_for_separate_production_commit_review"]
        )
        self.assertFalse(report["safe_simulation_performed"])
        self.assertEqual(
            report["assessment_type"],
            "static_schema_compatibility_check",
        )
        self.assertEqual(
            report["commit_validation"]["formal_simulation_status"],
            "not_run_missing_commit_artifact",
        )
        self.assertNotIn(
            "simulation_path",
            report["commit_validation"],
        )
        self.assertNotIn(
            "simulation_summary",
            report["commit_validation"],
        )
        self.assertIn("missing_production_profile_ids", report["blockers"])
        self.assertIn("missing_production_reviewer_id", report["blockers"])
        self.assertIn(
            "missing_commit_compatible_module_approvals",
            report["blockers"],
        )


if __name__ == "__main__":
    unittest.main()

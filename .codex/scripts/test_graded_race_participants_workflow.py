#!/usr/bin/env python3
"""年度分级赛参赛马研究 workflow 的离线静态合同测试。"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/research_graded_race_participants.yml"


class GradedRaceParticipantsWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not WORKFLOW.is_file():
            raise AssertionError(
                "目标 workflow .github/workflows/"
                "research_graded_race_participants.yml 尚不存在"
            )
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.lower = cls.source.lower()

    def step(self, name: str) -> str:
        match = re.search(
            rf"(?ms)^\s{{6}}- name: {re.escape(name)}\n"
            rf"(?P<body>.*?)(?=^\s{{6}}- name:|^  [a-z_]+:|\Z)",
            self.source,
        )
        self.assertIsNotNone(match, f"缺少 step: {name}")
        return match.group("body")

    def test_yaml_is_parseable_offline(self) -> None:
        result = subprocess.run(
            [
                "ruby",
                "-e",
                'require "yaml"; YAML.load_file(ARGV.fetch(0))',
                str(WORKFLOW),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dispatch_inputs_and_default_offline_boundary(self) -> None:
        for marker in (
            "workflow_dispatch:",
            "year:",
            "full_network:",
            "region_manifest_path:",
            "region_manifest_sha256:",
            "source_run_id:",
            "source_attempt:",
            "source_stage:",
            "default: false",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)
        self.assertRegex(
            self.source,
            r"(?ms)year:\s*\n\s+description:.*?\n\s+required: true",
        )
        self.assertIn("1984", self.source)
        self.assertIn("date -u +%Y", self.source)
        self.assertIn("synthetic_smoke", self.source)
        self.assertRegex(
            self.source,
            r"github\.event_name == 'workflow_dispatch'\s*&&\s*"
            r"inputs\.full_network == true",
        )

    def test_dag_is_tests_races_four_profiles_merge_finalize(self) -> None:
        for job in ("tests", "races", "profiles", "merge_profiles", "finalize"):
            with self.subTest(job=job):
                self.assertRegex(self.source, rf"(?m)^  {job}:$")
        self.assertRegex(self.source, r"(?ms)^  races:.*?\n    needs: tests\b")
        self.assertRegex(self.source, r"(?ms)^  profiles:.*?\n    needs: races\b")
        self.assertRegex(
            self.source, r"(?ms)^  merge_profiles:.*?\n    needs: profiles\b"
        )
        self.assertRegex(
            self.source, r"(?ms)^  finalize:.*?\n    needs: merge_profiles\b"
        )
        self.assertRegex(self.source, r"shard:\s*\[0,\s*1,\s*2,\s*3\]")
        self.assertIn("--shard-count 4", self.source)
        self.assertNotRegex(
            self.source,
            r"(?m)^  (?:search|entities|score|merge_search|merge_entities|"
            r"merge_scores)[^:]*:",
        )

    def test_checkpoint_artifacts_are_stage_exact_and_resume_is_explicit(self) -> None:
        for marker in (
            "${{ github.run_id }}-${{ github.run_attempt }}-races-0",
            "${{ github.run_id }}-${{ github.run_attempt }}-profiles-${{ matrix.shard }}",
            "${{ github.run_id }}-${{ github.run_attempt }}-merge_profiles-0",
            "${{ inputs.source_run_id }}-${{ inputs.source_attempt }}-races-0",
            "${{ inputs.source_run_id }}-${{ inputs.source_attempt }}-profiles-${{ matrix.shard }}",
            "run-id: ${{ inputs.source_run_id }}",
            "github-token: ${{ github.token }}",
            "if: always()",
            "--resume",
            'SAFE_STOP_CODE: "75"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)
        self.assertIn("retryable_error", self.source)
        self.assertIn("permanent_error", self.source)
        self.assertIn("HTTP Error (408|425|429|500|502|503|504)", self.source)
        self.assertIn('x.get("error_code")=="HTTPError"', self.source)
        self.assertNotIn("continue-on-error", self.source)
        self.assertNotRegex(self.lower, r"max[- _]?attempts|max[- _]?retries|最多\s*6")
        self.assertNotRegex(self.source, r"(?m)^\s+(?:schedule|cron):")
        self.assertNotRegex(self.source, r"(?m)^\s*(?:while|until)\b")

        races_upload = self.step("上传本次 races checkpoint")
        self.assertIn("${{ env.OUTPUT_DIR }}/run_manifest.json", races_upload)
        self.assertIn("${{ env.OUTPUT_DIR }}/stages/races/", races_upload)
        self.assertNotIn("${{ env.OUTPUT_DIR }}\n", races_upload)

        profile_upload = self.step("上传本次 profile shard checkpoint")
        self.assertIn(
            "path: ${{ env.OUTPUT_DIR }}/stages/profiles/shards/${{ matrix.shard }}/",
            profile_upload,
        )
        merged_upload = self.step("上传本次 merged profiles checkpoint")
        self.assertIn(
            "path: ${{ env.OUTPUT_DIR }}/stages/profiles/merged/",
            merged_upload,
        )
        for shard in range(4):
            self.assertIn(
                f"name: ${{{{ github.run_id }}}}-${{{{ github.run_attempt }}}}"
                f"-profiles-{shard}",
                self.source,
            )

    def test_network_stages_pass_the_frozen_request_budgets_exactly(self) -> None:
        races = self.step("运行 races checkpoint")
        profiles = self.step("运行 profile shard checkpoint")
        merge_profiles = self.step("合并四个 profile shards")
        finalize = self.step("纯离线 finalize 并验证精确文件集合")

        self.assertEqual(self.source.count("--stage races"), 1)
        self.assertEqual(self.source.count("--stage profiles"), 1)
        self.assertIn("--resume", races)
        self.assertIn("--request-budget 5000", races)
        self.assertEqual(races.count("--request-budget"), 1)
        self.assertIn("--resume", profiles)
        self.assertIn("--request-budget 2000", profiles)
        self.assertEqual(profiles.count("--request-budget"), 1)

        self.assertNotIn("--request-budget", merge_profiles)
        self.assertNotIn("--request-budget", finalize)
        self.assertEqual(self.source.count("--request-budget"), 2)

    def test_races_stage_uses_the_current_public_http_origin(self) -> None:
        races = self.step("运行 races checkpoint")
        self.assertIn("--base-url http://umafans.run/", races)
        self.assertNotIn("--base-url https://umafans.run/", races)

    def test_crash_safe_request_ledgers_are_preserved_and_timeout_has_margin(self) -> None:
        races_upload = self.step("上传本次 races checkpoint")
        profile_upload = self.step("上传本次 profile shard checkpoint")
        races_restore = self.step("恢复精确来源 races checkpoint")
        profile_restore = self.step("恢复来源 profile shard checkpoint")

        self.assertIn("discovery_progress.json", races_upload)
        self.assertIn("discovery_request_ledger.json", races_upload)
        self.assertIn("request_ledger.json", races_upload)
        self.assertIn("${{ env.OUTPUT_DIR }}/stages/races/", races_upload)
        self.assertIn("if: always()", races_upload)
        self.assertIn("if-no-files-found: error", races_upload)
        self.assertNotRegex(races_upload, r"test\s+-[ef]\s+.*run_manifest")
        self.assertNotRegex(races_upload, r"test\s+-[ef]\s+.*index\.json")
        self.assertIn("path: ${{ env.OUTPUT_DIR }}", races_restore)

        self.assertIn("request_ledger.json", profile_upload)
        self.assertIn(
            "path: ${{ env.OUTPUT_DIR }}/stages/profiles/shards/${{ matrix.shard }}/",
            profile_upload,
        )
        self.assertIn("if: always()", profile_upload)
        self.assertIn(
            "path: ${{ env.OUTPUT_DIR }}/stages/profiles/shards/${{ matrix.shard }}",
            profile_restore,
        )

        self.assertEqual(
            len(re.findall(r"(?m)^    timeout-minutes: 75$", self.source)), 2
        )
        self.assertEqual(self.source.count("--time-budget-seconds 3600"), 2)
        readme = (
            ROOT / "runtime/research/README_graded_race_participants.md"
        ).read_text(encoding="utf-8")
        self.assertIn("hard cancellation", readme)
        self.assertIn("runner timeout", readme)
        self.assertIn("无法保证", readme)
        self.assertIn("15 分钟", readme)

    def test_evidence_gap_continues_to_offline_partial_finalize(self) -> None:
        races = self.step("运行 races checkpoint")
        self.assertIn('"evidence_gap"', races)
        self.assertIn(
            "$OUTPUT_DIR/stages/races/shards/0/index.json", races
        )
        self.assertNotIn("$OUTPUT_DIR/stages/races/index.json", races)
        result = subprocess.run(
            [
                "python3",
                "-m",
                "unittest",
                "runtime.research.test_collect_graded_race_participants."
                "ReviewFindingRegressionTests."
                "test_provisional_full_run_stage_dag_emits_partial_seven_files",
                "-v",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validation_fails_closed_without_shell_interpolation(self) -> None:
        for marker in (
            "REQUESTED_YEAR:",
            "REGION_MANIFEST_PATH:",
            "REGION_MANIFEST_SHA256:",
            "SOURCE_RUN_ID:",
            "SOURCE_ATTEMPT:",
            "SOURCE_STAGE:",
            "sha256sum",
            "realpath",
            "races|profiles",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)
        run_blocks = re.findall(r"(?ms)^\s+- name:.*?\n(?=\s+- (?:name:|uses:)|\Z)", self.source)
        for block in run_blocks:
            if "run:" not in block:
                continue
            with self.subTest(block=block.splitlines()[0].strip()):
                self.assertNotIn("${{ inputs.", block.partition("run:")[2])

    def test_minimum_permissions_and_fixed_action_versions(self) -> None:
        self.assertRegex(
            self.source,
            r"(?ms)^permissions:\s*\n\s+actions: read\s*\n\s+contents: read\s*$",
        )
        allowed_actions = {
            "actions/checkout@v4",
            "actions/setup-python@v5",
            "actions/upload-artifact@v4",
            "actions/download-artifact@v4",
        }
        for action in allowed_actions:
            with self.subTest(action=action):
                self.assertIn(action, self.source)
        self.assertEqual(set(re.findall(r"(?m)^\s+uses: ([^\s]+)$", self.source)), allowed_actions)
        self.assertNotRegex(
            self.source,
            r"permissions:.*(?:write|admin)|(?:contents|actions|packages): write",
        )

    def test_finalize_uploads_only_the_seven_final_files(self) -> None:
        expected = (
            "race_participants_${{ env.REQUESTED_YEAR }}.csv",
            "horse_names_${{ env.REQUESTED_YEAR }}.csv",
            "horse_name_review_queue_${{ env.REQUESTED_YEAR }}.csv",
            "source_manifest.jsonl",
            "summary.json",
            "errors.json",
            "README.md",
        )
        upload = re.search(
            r"(?ms)- name: 上传严格七份最终 artifact.*?"
            r"\n\s+path: \|\n(?P<paths>(?:\s+\$\{\{ env\.OUTPUT_DIR \}\}/final/[^\n]+\n)+)",
            self.source,
        )
        self.assertIsNotNone(upload)
        actual = {
            line.strip().removeprefix("${{ env.OUTPUT_DIR }}/final/")
            for line in upload.group("paths").splitlines()
        }
        self.assertEqual(actual, set(expected))
        self.assertIn("if-no-files-found: error", self.source)

    def test_no_wikimedia_or_production_database_surface(self) -> None:
        for forbidden in (
            "wikipedia",
            "wikidata",
            "wikimedia",
            "manage.py",
            "django",
            "postgres",
            "redis",
            "docker",
            "celery",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.lower)


if __name__ == "__main__":
    unittest.main()

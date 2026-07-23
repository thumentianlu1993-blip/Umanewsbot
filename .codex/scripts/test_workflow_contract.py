#!/usr/bin/env python3
"""Mutation tests for the repository workflow contract checker."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT_DIR = Path(__file__).resolve().parent
CHECKER = SCRIPT_DIR / "check_workflow_contract.py"
SOURCE_ROOT = SCRIPT_DIR.parents[1]
CONTRACT_PATHS = (
    ".codex/agents",
    ".codex/scripts/review_fingerprint.py",
    ".codex/scripts/review_release_transition.py",
    ".codex/scripts/test_review_fingerprint.py",
    ".codex/scripts/test_review_release_transition.py",
    ".codex/scripts/test_workflow_contract.py",
    ".codex/skills",
    "AGENTS.md",
    "archive/disabled-skills/2026-07-15",
    "docs/codex_workflow.md",
    "docs/current_state.md",
    "docs/decisions.md",
    "docs/project_status.md",
    "docs/session_bootstrap.md",
    "docs/changes/codex-native-workflow-migration",
    "openspec/config.yaml",
)


class WorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name) / "repo"
        self.repo.mkdir()
        for relative in CONTRACT_PATHS:
            source = SOURCE_ROOT / relative
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def check(self, *, success: bool) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(CHECKER), "--repo-root", str(self.repo)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if success and result.returncode:
            self.fail(f"checker failed: {result.stderr}")
        if not success:
            self.assertNotEqual(0, result.returncode)
            self.assertNotIn("WORKFLOW_CONTRACT_OK", result.stdout)
        return result

    def replace(self, relative: str, old: str, new: str) -> None:
        path = self.repo / relative
        value = path.read_text(encoding="utf-8")
        self.assertIn(old, value)
        path.write_text(value.replace(old, new, 1), encoding="utf-8")

    def append(self, relative: str, value: str) -> None:
        path = self.repo / relative
        path.write_text(path.read_text(encoding="utf-8") + value, encoding="utf-8")

    def test_current_contract_passes(self) -> None:
        canonical_stages = (
            "探索 -> spec/design -> 方案审核 -> 用户确认实现 -> 测试先行 -> "
            "子代理实现 -> 独立 reviewer 会话 /review -> 用户授权后发布"
        )
        governed_workflow_files = (
            "AGENTS.md",
            "docs/codex_workflow.md",
            "docs/session_bootstrap.md",
        )
        for relative in governed_workflow_files:
            value = (self.repo / relative).read_text(encoding="utf-8")
            self.assertIn(canonical_stages, value)

        result = self.check(success=True)
        self.assertIn("WORKFLOW_CONTRACT_OK", result.stdout)

        stages_without_confirmation = canonical_stages.replace("用户确认实现 -> ", "", 1)
        for relative in governed_workflow_files:
            self.replace(relative, canonical_stages, stages_without_confirmation)
            result = self.check(success=False)
            self.assertIn("workflow", result.stderr.lower())
            self.replace(relative, stages_without_confirmation, canonical_stages)

    def test_release_staging_contract_is_present(self) -> None:
        workflow = (self.repo / "docs/codex_workflow.md").read_text(encoding="utf-8")
        for marker in (
            "approved parent",
            "content_manifest_sha256",
            "staging 前完整 fingerprint",
            "显式 stage 全部受审改动后",
            "无 unstaged、untracked 或 conflict",
            "允许 status/index 表示发生变化",
        ):
            self.assertIn(marker, workflow)

    def test_mutation_missing_subagent_silence_rule_fails(self) -> None:
        self.replace(
            "AGENTS.md",
            "任何 subagent（实现、测试、审核、调研或其他用途）启动后",
            "任何实现 subagent 启动后",
        )
        result = self.check(success=False)
        self.assertIn("subagent", result.stderr)

    def test_mutation_forbidden_active_skill_fails(self) -> None:
        target = self.repo / ".codex/skills/openspec-explore"
        target.mkdir()
        (target / "SKILL.md").write_text(
            "---\nname: openspec-explore\ndescription: forbidden\n---\n", encoding="utf-8"
        )
        result = self.check(success=False)
        self.assertIn("active skill", result.stderr)

    def test_mutation_tampered_archive_fails(self) -> None:
        target = self.repo / "archive/disabled-skills/2026-07-15/grill-me/SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
        result = self.check(success=False)
        self.assertIn("archive", result.stderr)

    def test_mutation_operations_runtime_config_red_exemption_fails(self) -> None:
        self.replace(
            ".codex/agents/operations.toml",
            "只要涉及 feature flag、队列/路由、权限、依赖、Compose/\n容器、部署顺序或数据行为，就必须先写自动化测试并取得真实 RED，不得使用该豁免。",
            "feature flag、队列/路由、权限、依赖、Compose/\n容器、部署顺序或数据行为可以按风险豁免 RED。",
        )
        result = self.check(success=False)
        self.assertIn("operations", result.stderr)

    def test_mutation_review_command_without_read_only_override_fails(self) -> None:
        self.replace(
            "docs/codex_workflow.md",
            "codex review -c 'sandbox_mode=\"read-only\"' --uncommitted",
            "codex review --uncommitted",
        )
        result = self.check(success=False)
        self.assertIn("review command", result.stderr)

    def test_mutation_multiline_review_command_without_read_only_override_fails(self) -> None:
        self.append(
            "docs/codex_workflow.md",
            "\n```sh\ncodex review \\\n  --uncommitted\n```\n",
        )
        result = self.check(success=False)
        self.assertIn("review command", result.stderr)

    def test_mutation_shell_joined_review_command_without_read_only_override_fails(self) -> None:
        self.append(
            "docs/codex_workflow.md",
            "\n```sh\ncodex re\\\nview --uncommitted\n```\n",
        )
        result = self.check(success=False)
        self.assertIn("review command", result.stderr)

    def test_mutation_freeze_must_be_the_complete_fingerprint_scope(self) -> None:
        self.replace(
            "docs/codex_workflow.md",
            "成功 review 记录受审 scope、完整 fingerprint、approved parent",
            "成功 review 记录受审 scope、部分 fingerprint、approved parent",
        )
        result = self.check(success=False)
        self.assertIn("fingerprint freeze", result.stderr)

    def test_mutation_freeze_cannot_exclude_archive_or_state_files(self) -> None:
        self.append(
            "docs/codex_workflow.md",
            "\nreview freeze 排除 `archive/**` 和 `docs/current_state.md`。\n",
        )
        result = self.check(success=False)
        self.assertIn("fingerprint freeze", result.stderr)

    def test_mutation_freeze_cannot_exclude_openspec_or_specs(self) -> None:
        self.append(
            "AGENTS.md",
            "\nreview freeze 排除 `openspec/**` 和其他 spec 文件。\n",
        )
        result = self.check(success=False)
        self.assertIn("fingerprint freeze", result.stderr)

    def test_mutation_rereview_scope_cannot_expand_to_full_review(self) -> None:
        self.replace(
            "docs/codex_workflow.md",
            "复审严格限定为上轮列出的具体漏洞/阻塞项、对应修复，以及这些修复直接触及路径的回归",
            "复审重新执行完整范围审核并继续扩展问题",
        )
        result = self.check(success=False)
        self.assertIn("reviewer continuity", result.stderr)

    def test_mutation_old_fresh_reviewer_rule_is_rejected(self) -> None:
        self.append(
            "docs/changes/codex-native-workflow-migration/rollout.md",
            "\n每轮复审都重新派一个全新 reviewer。\n",
        )
        result = self.check(success=False)
        self.assertIn("reviewer continuity", result.stderr)

    def test_mutation_plan_rereview_scope_is_required(self) -> None:
        self.replace(
            ".codex/skills/plan-eng-review/SKILL.md",
            "复审只核对上轮 findings、对应方案修复与直接触及路径",
            "复审重新执行完整方案审核",
        )
        result = self.check(success=False)
        self.assertIn("reviewer continuity", result.stderr)

    def test_mutation_grill_handoff_requires_rollout_artifact(self) -> None:
        self.replace(
            ".codex/skills/grill-me-codex/SKILL.md",
            "`rollout.md` 五份持久产物",
            "四份持久产物",
        )
        result = self.check(success=False)
        self.assertIn("rollout", result.stderr)

    def test_mutation_plan_review_requires_rollout_input(self) -> None:
        self.replace(
            ".codex/skills/plan-eng-review/SKILL.md",
            "   - `rollout.md`",
            "   - `release_notes.md`",
        )
        result = self.check(success=False)
        self.assertIn("rollout", result.stderr)

    def test_mutation_reviewer_release_freeze_must_keep_fingerprint(self) -> None:
        self.replace(
            ".codex/agents/reviewer.toml",
            "成功 review 后记录 scope、完整 fingerprint、approved parent 和 approved content hash",
            "成功 review 后只记录 scope",
        )
        result = self.check(success=False)
        self.assertIn("reviewer release freeze", result.stderr)

    def test_mutation_release_authorization_before_latest_review_fails(self) -> None:
        self.replace(
            "AGENTS.md",
            "当前任务发布授权必须在最新一轮成功 review 之后取得",
            "当前任务发布授权必须在最新一轮成功 review 之前取得",
        )
        result = self.check(success=False)
        self.assertIn("release authorization", result.stderr)

    def test_mutation_business_code_cannot_enter_evidence_only_allowlist(self) -> None:
        self.replace(
            "docs/codex_workflow.md",
            "- `docs/changes/<slug>/release_report.md`",
            "- `docs/changes/<slug>/release_report.md`\n- `server/stable/models.py`",
        )
        result = self.check(success=False)
        self.assertIn("evidence-only allowlist", result.stderr)

    def test_mutation_freeze_cannot_be_relaxed(self) -> None:
        self.replace(
            "AGENTS.md",
            "成功 review 记录受审 scope、完整 fingerprint、approved parent",
            "成功 review 记录受审 scope、部分 fingerprint、approved parent",
        )
        result = self.check(success=False)
        self.assertIn("fingerprint freeze", result.stderr)

    def test_mutation_outdated_artifact_or_test_count_claim_fails(self) -> None:
        self.replace(
            "docs/project_status.md",
            "五份 durable artifacts",
            "四份 artifacts",
        )
        result = self.check(success=False)
        self.assertIn("outdated count", result.stderr)

    def test_mutation_second_sandbox_override_is_rejected(self) -> None:
        self.append(
            "docs/codex_workflow.md",
            "\n```sh\n"
            "codex review \\\n"
            "  -c 'sandbox_mode=\"read-only\"' \\\n"
            "  -c 'sandbox_mode=\"workspace-write\"' \\\n"
            "  --uncommitted\n"
            "```\n",
        )
        result = self.check(success=False)
        self.assertIn("review command", result.stderr)

    def test_mutation_post_scope_sandbox_override_is_rejected(self) -> None:
        self.append(
            "docs/codex_workflow.md",
            "\n```sh\n"
            "codex review -c 'sandbox_mode=\"read-only\"' --uncommitted \\\n"
            "  -c 'sandbox_mode=\"workspace-write\"'\n"
            "```\n",
        )
        result = self.check(success=False)
        self.assertIn("review command", result.stderr)

    def test_code_rereview_must_reuse_same_reviewer(self) -> None:
        self.replace(
            "docs/codex_workflow.md",
            "同一需求的首次代码审核建立 reviewer 会话；后续复审必须回到同一 reviewer、同一会话与上下文",
            "每轮代码复审都建立全新 reviewer",
        )
        result = self.check(success=False)
        self.assertIn("reviewer continuity", result.stderr)

    def test_plan_rereview_must_reuse_same_reviewer(self) -> None:
        self.replace(
            ".codex/skills/plan-eng-review/SKILL.md",
            "同一方案的后续复审必须回到首次方案 reviewer 的同一会话与上下文",
            "每轮方案复审都建立全新 reviewer",
        )
        result = self.check(success=False)
        self.assertIn("reviewer continuity", result.stderr)


if __name__ == "__main__":
    unittest.main()

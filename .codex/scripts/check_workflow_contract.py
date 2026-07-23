#!/usr/bin/env python3
"""Read-only, stdlib-only validation for the Umanews workflow contract."""

from __future__ import annotations

import argparse
import ast
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import tomllib


ACTIVE_SKILLS = {"grill-me-codex", "plan-eng-review", "tdd"}
ARCHIVE_ROOT = Path("archive/disabled-skills/2026-07-15")
ARCHIVE_FILES = {
    "grill-me-codex-claude-legacy/SKILL.md": ("960e14996c5d2e93356e506a0a09be9a3b9de5a85182e70939c50eed999c3cbd", 0o644),
    "grill-me-codex-claude-legacy/THIRD-PARTY-NOTICES.md": ("783a5221a0af6817833e18e871167d855c17671fc72fdc9ebe8dc1c40333e1b8", 0o644),
    "grill-me/SKILL.md": ("6189dfceb7304a6e5558f75d87e68fa3bc7fcf7ba120e44f21f8a61fe01eba54", 0o644),
    "openspec-apply-change/SKILL.md": ("da3d97f3ea482cca969981a2079ce7f906ccb4a892728f07bf72f354035d951a", 0o644),
    "openspec-archive-change/SKILL.md": ("0526054ec891a8a0c0cd0e19a285f285aa111112f2480a3ab365f9bba18a2b9c", 0o644),
    "openspec-explore/SKILL.md": ("fb359559d93095c81a57760c7739ffbd6d618a03d1810503515f8ae2b5054cd0", 0o644),
    "openspec-propose/SKILL.md": ("ead4a7b7077ff08607b883ce045b31de3d78189432846c58ae80675eeac5033b", 0o644),
    "openspec-sync-specs/SKILL.md": ("9c74dad096467f982806ccf33e213f459890e0b79af1f69f6e9f1e790bb2fccf", 0o644),
    "plan-eng-review-openspec-legacy/SKILL.md": ("93c2a0e4b736bbf5ade610eb20e1e990553ec453911d16b574eaabf36f283ef6", 0o644),
    "plan-eng-review-openspec-legacy/references/gate-templates.md": ("006657260f214e512a7821bd39d5cc3084f9606fa813481e0666c1790cf30795", 0o644),
    "plan-eng-review-openspec-legacy/references/ledger-schema.md": ("ad4849b01be6f03e971028ce6f235a90ab40b007714dc0f59136089f20adcbe0", 0o644),
    "plan-eng-review-openspec-legacy/references/workflow-spine.md": ("62307436f782743e2aaa61eb7d34898689d6e1cb2768546872e819457bc7900a", 0o644),
    "plan-eng-review-openspec-legacy/scripts/write-ledger-entry.py": ("21b55db7a4c97fab1d9df0d8349c703041a0aed48fed07418d391d4e86fb947b", 0o755),
    "workflow-spine/REFERENCE.md": ("6a63bd690733a52b23e0617525b57d22b0141df3547642fef61164b5c9c3a153", 0o644),
}
DURABLE_FILES = {
    "spec.md",
    "design.md",
    "test_cases.md",
    "tasks.md",
    "rollout.md",
}
REVIEW_COMMANDS = {
    "codex review -c 'sandbox_mode=\"read-only\"' --uncommitted",
    "codex review -c 'sandbox_mode=\"read-only\"' --base <base_oid>",
    "codex review -c 'sandbox_mode=\"read-only\"' --commit <commit_oid>",
}
SAFE_REVIEW_OVERRIDE = " -c 'sandbox_mode=\"read-only\"'"
FINGERPRINT_FREEZE_ENTRIES = {
    "成功 review 记录受审 scope、完整 fingerprint、approved parent（审核时 HEAD）和 approved content hash（`content_manifest_sha256`），作为当前任务最新审核基线。",
    "用户授权后、staging 前完整 fingerprint 必须用相同 scope 重算并与审核基线逐字节一致；不一致则停止。",
    "显式 stage 全部受审改动后，允许 status/index 表示发生变化；但 HEAD 必须仍为 approved parent，且无 unstaged、untracked 或 conflict，index 的 `content_manifest_sha256` 必须与 approved content hash 一致。漏 stage、夹带或内容变化均停止。",
    "任何实际内容差异都会使该轮 review 与授权失效；必须回到同一 reviewer 会话，仅复审变化、对应修复和直接触及路径，并在成功后重新取得当前任务授权。",
}
EVIDENCE_ALLOWLIST = {
    "docs/current_state.md",
    "docs/project_status.md",
    "docs/deploy_runbook.md",
    "docs/decisions.md（仅必要发布决策）",
    "docs/changes/<slug>/release_report.md",
}
EVIDENCE_FORBIDDEN = {
    "代码",
    "测试",
    "配置",
    "迁移",
    "spec",
    "tasks",
    "skills",
    "agents",
}
FORBIDDEN_SKILLS = {
    "openspec-explore",
    "openspec-propose",
    "openspec-apply-change",
    "openspec-archive-change",
    "openspec-sync-specs",
    "grill-me",
    "workflow-spine",
}
CANONICAL_REVIEW_FILES = (
    ".codex/agents/reviewer.toml",
    ".codex/skills/grill-me-codex/SKILL.md",
    ".codex/skills/plan-eng-review/SKILL.md",
    "AGENTS.md",
    "docs/codex_workflow.md",
    "docs/current_state.md",
    "docs/decisions.md",
    "docs/project_status.md",
    "docs/session_bootstrap.md",
    "docs/changes/codex-native-workflow-migration/spec.md",
    "docs/changes/codex-native-workflow-migration/design.md",
    "docs/changes/codex-native-workflow-migration/test_cases.md",
    "docs/changes/codex-native-workflow-migration/tasks.md",
    "docs/changes/codex-native-workflow-migration/rollout.md",
)


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def read_text(root: Path, relative: str) -> str:
    path = root / relative
    require(path.is_file(), f"missing durable contract file: {relative}")
    return path.read_text(encoding="utf-8")


def require_markers(text: str, label: str, markers: tuple[str, ...]) -> None:
    missing = [marker for marker in markers if marker not in text]
    require(not missing, f"{label} missing contract marker(s): {missing}")


def contract_block(text: str, name: str, label: str) -> str:
    start = f"<!-- WORKFLOW_CONTRACT:{name}:START -->"
    end = f"<!-- WORKFLOW_CONTRACT:{name}:END -->"
    require(text.count(start) == 1 and text.count(end) == 1, f"{label} {name} block missing/duplicate")
    before, rest = text.split(start, 1)
    block, after = rest.split(end, 1)
    require(before is not None and after is not None, f"{label} {name} block malformed")
    return block.strip()


def contract_bullets(block: str, label: str) -> set[str]:
    lines = [line[2:].strip().strip("`") for line in block.splitlines() if line.startswith("- ")]
    require(len(lines) == len(set(lines)), f"{label} contains duplicate entries")
    return set(lines)


def require_exact_block_entries(text: str, name: str, expected: set[str], label: str) -> None:
    actual = contract_bullets(contract_block(text, name, label), label)
    require(actual == expected, f"{label} mismatch: expected {sorted(expected)}, got {sorted(actual)}")


def normalize_cli_text(text: str) -> str:
    # A backslash followed by a newline is removed by the shell before tokenization.
    # Do not insert whitespace: `re\\\nview` is exactly `review` to the shell.
    without_continuations = re.sub(r"\\[ \t]*\r?\n", "", text)
    return re.sub(r"\s+", " ", without_continuations)


def check_safe_review_occurrences(text: str, label: str) -> None:
    normalized = normalize_cli_text(text)
    for match in re.finditer(r"(?<![\w-])codex review\b", normalized):
        tail = normalized[match.end() :]
        require(
            tail.startswith(SAFE_REVIEW_OVERRIDE),
            f"{label} review command missing immediate read-only override: "
            f"{normalized[match.start():match.end() + 120]!r}",
        )
        after_override = tail[len(SAFE_REVIEW_OVERRIDE) :]
        require(
            after_override.startswith(" --uncommitted")
            or after_override.startswith(" --base ")
            or after_override.startswith(" --commit "),
            f"{label} review command contains an extra config/sandbox override before scope: "
            f"{normalized[match.start():match.end() + 180]!r}",
        )
        # Canonical review commands are Markdown code spans/blocks. Inspect the
        # complete command through the closing backtick so an override placed
        # after the scope cannot evade the immediate-prefix check above.
        command_tail = tail.split("`", 1)[0]
        require(
            command_tail.count(" -c ") == 1 and " --config " not in command_tail,
            f"{label} review command must contain exactly one read-only sandbox config: "
            f"{normalized[match.start():match.end() + 220]!r}",
        )


def check_review_commands(text: str, label: str) -> None:
    require_exact_block_entries(text, "REVIEW_COMMANDS", REVIEW_COMMANDS, f"{label} review command")
    check_safe_review_occurrences(text, label)


def test_method_count(root: Path, relative: str, class_name: str) -> int:
    tree = ast.parse(read_text(root, relative), filename=relative)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return sum(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name.startswith("test_")
                for item in node.body
            )
    raise ContractError(f"test class missing: {relative}:{class_name}")


def parse_frontmatter(path: Path) -> dict[str, str]:
    value = path.read_text(encoding="utf-8")
    require(value.startswith("---\n"), f"active skill frontmatter missing: {path}")
    try:
        raw, _ = value[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ContractError(f"active skill frontmatter unterminated: {path}") from exc
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, content = line.split(":", 1)
            fields[key.strip()] = content.strip()
    return fields


def check_active_skills(root: Path) -> None:
    skills_root = root / ".codex/skills"
    require(skills_root.is_dir(), "active skill root missing")
    discovered = {path.name for path in skills_root.iterdir() if path.is_dir()}
    require(discovered == ACTIVE_SKILLS, f"active skill allowlist mismatch: {sorted(discovered)}")
    require(not (discovered & FORBIDDEN_SKILLS), "forbidden active skill remains discoverable")
    for name in sorted(ACTIVE_SKILLS):
        fields = parse_frontmatter(skills_root / name / "SKILL.md")
        require(fields.get("name") == name, f"active skill name mismatch: {name}")
        require(bool(fields.get("description")), f"active skill description missing: {name}")
    grill = read_text(root, ".codex/skills/grill-me-codex/SKILL.md")
    require_markers(
        grill,
        "grill-me-codex rollout handoff",
        (
            "五份",
            "`spec.md`",
            "`design.md`",
            "`test_cases.md`",
            "`tasks.md`",
            "`rollout.md` 五份持久产物",
            "rollout 交接",
        ),
    )
    plan_review = read_text(root, ".codex/skills/plan-eng-review/SKILL.md")
    require_markers(
        plan_review,
        "plan-eng-review rollout input",
        (
            "   - `rollout.md`",
            "`rollout.md` 缺失",
            "列为 finding",
        ),
    )


def check_archive(root: Path) -> None:
    archive = root / ARCHIVE_ROOT
    actual = {
        path.relative_to(archive).as_posix()
        for path in archive.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    require(actual == set(ARCHIVE_FILES), f"archive file set mismatch: {sorted(actual)}")
    for relative, (expected_sha, expected_mode) in ARCHIVE_FILES.items():
        path = archive / relative
        value = os.lstat(path)
        require(stat.S_ISREG(value.st_mode), f"archive entry is not regular/non-symlink: {relative}")
        require(stat.S_IMODE(value.st_mode) == expected_mode, f"archive mode mismatch: {relative}")
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        require(actual_sha == expected_sha, f"archive SHA mismatch: {relative}")


def check_agents(root: Path) -> None:
    agents = root / ".codex/agents"
    required = {"application", "integration", "operations", "reviewer"}
    for name in sorted(required):
        path = agents / f"{name}.toml"
        require(path.is_file(), f"agent TOML missing: {name}")
        with path.open("rb") as handle:
            parsed = tomllib.load(handle)
        require(parsed.get("name") == name, f"agent TOML name mismatch: {name}")
    operations = read_text(root, ".codex/agents/operations.toml")
    require_markers(
        operations,
        "operations RED contract",
        (
            "只有不改变任何运行时行为的纯文档或纯配置整理",
            "只要涉及 feature flag、队列/路由、权限、依赖、Compose/\n容器、部署顺序或数据行为，就必须先写自动化测试并取得真实 RED，不得使用该豁免。",
        ),
    )
    reviewer = read_text(root, ".codex/agents/reviewer.toml")
    require_markers(
        reviewer,
        "reviewer",
        (
            "Codex 原生 review",
            "sandbox_mode=\"read-only\"",
            "completely clean worktree",
            "--uncommitted",
            "所有 P0-P3",
            "actionable",
        ),
    )
    require_markers(
        reviewer,
        "reviewer release freeze",
        (
            "成功 review 后记录 scope、完整 fingerprint、approved parent 和 approved content hash",
            "staging 前用相同 scope 重算完整 fingerprint",
            "显式 stage 全部受审改动后允许 status/index 表示变化",
            "content_manifest_sha256` 与 approved content",
            "同一 reviewer 会话按上述范围复审",
            "post-release evidence-only closure 也复用本需求既有 reviewer 会话",
        ),
    )
    normalized_reviewer = normalize_cli_text(reviewer)
    require(
        not re.search(
            r"(?:review freeze|fingerprint).{0,120}(?:允许|可以|可)排除",
            normalized_reviewer,
            flags=re.IGNORECASE,
        ),
        "reviewer fingerprint freeze permits a path exclusion",
    )
    check_review_commands(reviewer, ".codex/agents/reviewer.toml")


def check_reviewer_continuity(root: Path) -> None:
    workflow = read_text(root, "docs/codex_workflow.md")
    plan_review = read_text(root, ".codex/skills/plan-eng-review/SKILL.md")
    reviewer = read_text(root, ".codex/agents/reviewer.toml")
    require_markers(
        workflow,
        "reviewer continuity code review",
        (
            "同一需求的首次代码审核建立 reviewer 会话；后续复审必须回到同一 reviewer、同一会话与上下文",
            "只有原 reviewer 明确确认会话不可恢复",
            "记录不可恢复原因、上轮 findings 与已知问题交接",
            "复审严格限定为上轮列出的具体漏洞/阻塞项、对应修复，以及这些修复直接触及路径的回归",
            "只有属于当前具体漏洞直接回归的 P0/P1 新问题才继续阻塞",
        ),
    )
    require_markers(
        plan_review,
        "reviewer continuity plan review",
        (
            "同一方案的后续复审必须回到首次方案 reviewer 的同一会话与上下文",
            "只有原 reviewer 明确确认会话不可恢复",
            "复审只核对上轮 findings、对应方案修复与直接触及路径",
            "直接 P0/P1 回归",
        ),
    )
    require_markers(
        reviewer,
        "reviewer continuity agent",
        (
            "同一需求内必须复用本 reviewer 的同一会话与上下文",
            "复审范围只包含上轮 findings、对应修复和直接触及路径回归",
            "直接 P0/P1 回归",
        ),
    )
    governed = (
        "AGENTS.md",
        "docs/codex_workflow.md",
        "docs/session_bootstrap.md",
        "docs/decisions.md",
        "docs/current_state.md",
        "docs/project_status.md",
        "docs/changes/codex-native-workflow-migration/spec.md",
        "docs/changes/codex-native-workflow-migration/design.md",
        "docs/changes/codex-native-workflow-migration/test_cases.md",
        "docs/changes/codex-native-workflow-migration/tasks.md",
        "docs/changes/codex-native-workflow-migration/rollout.md",
        ".codex/agents/reviewer.toml",
        ".codex/skills/plan-eng-review/SKILL.md",
    )
    forbidden = (
        "每轮复审都重新派一个全新 reviewer",
        "另派一个全新 subagent 复审",
        "不得复用原审核者",
        "每轮修复后必须换一个全新 reviewer",
        "每轮再换一个全新 reviewer",
        "复审仍待下一轮未参与本轮修复的全新 reviewer",
    )
    for relative in governed:
        value = read_text(root, relative)
        require(
            not any(marker in value for marker in forbidden),
            f"reviewer continuity old new-reviewer rule remains in {relative}",
        )


def check_documents(root: Path) -> None:
    stages = (
        "探索 -> spec/design -> 方案审核 -> 用户确认实现 -> 测试先行 -> "
        "子代理实现 -> 独立 reviewer 会话 /review -> 用户授权后发布"
    )
    agents = read_text(root, "AGENTS.md")
    workflow = read_text(root, "docs/codex_workflow.md")
    for label, value in (("AGENTS.md", agents), ("workflow", workflow)):
        require_markers(
            value,
            label,
            (
                stages,
                "evidence-only",
                "actionable",
                "最新一轮成功 review",
                "当前任务授权",
                "冻结",
            ),
        )
        check_review_commands(value, label)
        require_exact_block_entries(
            value,
            "FINGERPRINT_FREEZE",
            FINGERPRINT_FREEZE_ENTRIES,
            f"{label} release transition fingerprint freeze",
        )
        require_exact_block_entries(
            value,
            "EVIDENCE_ALLOWLIST",
            EVIDENCE_ALLOWLIST,
            f"{label} evidence-only allowlist",
        )
        require_exact_block_entries(
            value,
            "EVIDENCE_FORBIDDEN",
            EVIDENCE_FORBIDDEN,
            f"{label} evidence-only forbidden",
        )
        release_auth = contract_block(value, "RELEASE_AUTHORIZATION", label)
        require(
            release_auth == "当前任务发布授权必须在最新一轮成功 review 之后取得。",
            f"{label} release authorization must be after latest successful review",
        )
        normalized = normalize_cli_text(value)
        require(
            not re.search(
                r"(?:review freeze|fingerprint).{0,80}(?:排除|不包含|忽略).{0,120}"
                r"(?:archive|current_state|project_status|openspec|spec)",
                normalized,
                flags=re.IGNORECASE,
            ),
            f"{label} fingerprint freeze contains a path exclusion",
        )
    require_markers(
        agents,
        "AGENTS.md subagent silence",
        (
            "任何 subagent（实现、测试、审核、调研或其他用途）启动后",
            "只能继续派出新的 subagent，或等待/接收结果",
        ),
    )
    for relative in CANONICAL_REVIEW_FILES:
        check_safe_review_occurrences(read_text(root, relative), relative)
    require_markers(
        workflow,
        "native review",
        (
            "实际调用 Codex 原生 review",
            "sandbox_mode=\"read-only\"",
            "完全 clean",
            "所有 P0-P3",
        ),
    )
    for relative in ("docs/current_state.md", "docs/project_status.md", "docs/decisions.md"):
        require_markers(read_text(root, relative), relative, ("codex-native-workflow-migration", "尚未发布"))
    bootstrap = read_text(root, "docs/session_bootstrap.md")
    require_markers(bootstrap, "session bootstrap", (stages, "当前任务", "最新成功 review"))

    change = root / "docs/changes/codex-native-workflow-migration"
    actual = {path.name for path in change.iterdir() if path.is_file()}
    require(DURABLE_FILES <= actual, f"durable artifacts missing: {sorted(DURABLE_FILES - actual)}")
    fingerprint_count = test_method_count(
        root, ".codex/scripts/test_review_fingerprint.py", "ReviewFingerprintTests"
    )
    transition_count = test_method_count(
        root, ".codex/scripts/test_review_release_transition.py", "ReviewReleaseTransitionTests"
    )
    workflow_count = test_method_count(
        root, ".codex/scripts/test_workflow_contract.py", "WorkflowContractTests"
    )
    require(fingerprint_count == 24, f"fingerprint test inventory mismatch: {fingerprint_count}")
    require(transition_count == 10, f"transition test inventory mismatch: {transition_count}")
    require(workflow_count == 26, f"workflow test inventory mismatch: {workflow_count}")
    for relative in ("docs/current_state.md", "docs/project_status.md"):
        value = read_text(root, relative)
        require(
            "fingerprint `24/24`" in value
            and "transition/index `10/10`" in value
            and "workflow contract tests `26/26`" in value,
            f"{relative} outdated count: expected fingerprint 24/24, transition/index 10/10 and workflow 26/26",
        )
    for relative in (
        "docs/project_status.md",
        "docs/changes/codex-native-workflow-migration/design.md",
        "docs/changes/codex-native-workflow-migration/test_cases.md",
    ):
        value = read_text(root, relative)
        require(
            not re.search(r"四份\s+(?:durable\s+)?artifacts", value)
            and "16/16" not in value,
            f"{relative} outdated count claim",
        )
    require(
        "五份 durable artifacts" in read_text(root, "docs/project_status.md"),
        "docs/project_status.md outdated count: five durable artifacts missing",
    )
    require(
        "workflow contract tests `26/26`" in read_text(
            root, "docs/changes/codex-native-workflow-migration/test_cases.md"
        ),
        "test_cases.md outdated count: current workflow test count missing",
    )
    fingerprint_script = read_text(root, ".codex/scripts/review_fingerprint.py")
    require_markers(
        fingerprint_script,
        "external clean filter safety",
        (
            "def reject_external_clean_filters(root: Path)",
            '"check-attr",',
            '"hash-object", "--no-filters", "--stdin"',
            "external Git clean filter is not allowed",
        ),
    )
    transition_script = read_text(root, ".codex/scripts/review_release_transition.py")
    require_markers(
        transition_script,
        "review-approved staging verifier",
        (
            "def verify_index(root: Path, parent_input: str, expected_hash: str)",
            'if head != parent:',
            'summary["unstaged_change_count"]',
            "index content hash",
        ),
    )
    rollout = read_text(root, "docs/changes/codex-native-workflow-migration/rollout.md")
    for marker in (
        "019f482d-df62-75c0-89d5-e359c185f06a",
        "019f1717-0eed-77f1-8137-2bf977bfab38",
        "019f5c49-f7a1-7f02-b7c6-62f10b1eae03",
        "019f481e-4133-7f43-9844-e7a59b33ba9a",
        "019f3cf5-3129-76a3-8f8d-8a26ec557044",
        "019f3a78-d1e4-7a52-a467-4d703254bb48",
        "不主动唤醒",
        "安全检查点",
        "共享 main",
        "尚未发布",
        ".claude/disabled-skills/2026-07-15",
        "本机 ignored 副本",
    ):
        require(marker in rollout, f"rollout migration marker missing: {marker}")
    inventory = contract_block(rollout, "WORKTREE_INVENTORY", "rollout worktree inventory")
    inventory_rows = [line for line in inventory.splitlines() if line.startswith("| `")]
    require(len(inventory_rows) == 34, f"rollout worktree inventory row count mismatch: {len(inventory_rows)}")
    require(
        len(set(inventory_rows)) == 34,
        "rollout worktree inventory contains duplicate rows",
    )
    require_markers(
        rollout,
        "rollout snapshot provenance",
        (
            "2026-07-15T17:38:39+08:00",
            "git worktree list --porcelain",
            "list_threads(limit=100)",
            "调用等待约 90 秒仍无 payload",
            "当前状态一律写 `unknown`",
            "future durable 生效仍依次等待",
        ),
    )

    legacy = read_text(root, "openspec/config.yaml")
    require_markers(
        legacy,
        "OpenSpec legacy config",
        ("Legacy compatibility only", "不得调用 openspec 系列 skills"),
    )


def check(root: Path) -> None:
    require(root.is_dir(), f"repo root is not a directory: {root}")
    check_active_skills(root)
    check_archive(root)
    check_agents(root)
    check_reviewer_continuity(root)
    check_documents(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    try:
        check(arguments.repo_root.resolve())
    except (ContractError, OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        print(f"workflow_contract: {exc}", file=sys.stderr)
        return 1
    print("WORKFLOW_CONTRACT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

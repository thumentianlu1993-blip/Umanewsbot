#!/usr/bin/env python3
"""Read-only validation for the repository-wide Codex workflow contract."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tomllib


ROOT_MARKERS = (
    "是本仓库唯一的人工确认门禁定义",
    "### G1：范围确认",
    "### G2：交付确认",
    "### G3：高影响动作确认",
    "机械步骤不得拆成新的确认点",
    "main` 是受保护的远端引用",
    "同一时间只允许一个 release coordinator",
)

REFERENCE_FILES = (
    "docs/codex_workflow.md",
    "docs/session_bootstrap.md",
)

ACTIVE_SKILLS = {"grill-me-codex", "plan-eng-review", "tdd"}
LEGACY_TOKEN = "open" + "spec"


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def read_text(root: Path, relative: str) -> str:
    path = root / relative
    require(path.is_file(), f"missing contract file: {relative}")
    return path.read_text(encoding="utf-8")


def repository_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    files: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8", errors="surrogateescape"))
        path = root / relative
        if path.is_file():
            files.append(relative)
    return files


def check_no_legacy_workflow(root: Path, files: list[Path]) -> None:
    token = LEGACY_TOKEN.casefold()
    failures: list[str] = []
    for relative in files:
        if token in relative.as_posix().casefold():
            failures.append(f"path:{relative}")
            continue
        path = root / relative
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if token in content.casefold():
            failures.append(f"text:{relative}")
    require(not failures, f"legacy workflow artifacts/references remain: {failures[:20]}")


def check_gate_authority(root: Path) -> None:
    agents = read_text(root, "AGENTS.md")
    missing = [marker for marker in ROOT_MARKERS if marker not in agents]
    require(not missing, f"AGENTS.md missing gate marker(s): {missing}")

    for relative in REFERENCE_FILES:
        text = read_text(root, relative)
        require("根 `AGENTS.md`" in text, f"{relative} must reference root AGENTS.md")
        require("不定义人工确认门禁" in text, f"{relative} must reject local gate definitions")
        require("### G1" not in text and "### G2" not in text and "### G3" not in text,
                f"{relative} duplicates gate definitions")

    for path in root.rglob("AGENTS.md"):
        require(path == root / "AGENTS.md", f"nested AGENTS.md may redefine gates: {path.relative_to(root)}")


def check_skills_and_agents(root: Path) -> None:
    skill_root = root / ".codex/skills"
    actual = {path.name for path in skill_root.iterdir() if path.is_dir()}
    require(actual == ACTIVE_SKILLS, f"unexpected active skill set: {sorted(actual)}")

    for path in sorted((root / ".codex/agents").glob("*.toml")):
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        require(isinstance(data.get("name"), str), f"invalid agent name: {path}")
        instructions = data.get("developer_instructions", "")
        if path.name != "security-scanner.toml":
            require("根 AGENTS.md" in instructions, f"{path} must reference root gate authority")


def check(root: Path) -> None:
    require((root / ".git").exists(), f"not a Git worktree: {root}")
    files = repository_files(root)
    check_gate_authority(root)
    check_skills_and_agents(root)
    check_no_legacy_workflow(root, files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        check(args.root.resolve())
    except (ContractError, subprocess.CalledProcessError, tomllib.TOMLDecodeError) as exc:
        print(f"workflow contract: FAIL: {exc}", file=sys.stderr)
        return 1
    print("workflow contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

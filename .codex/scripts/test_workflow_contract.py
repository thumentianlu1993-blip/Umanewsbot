#!/usr/bin/env python3
"""Regression tests for the repository workflow contract checker."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = ROOT / ".codex/scripts/check_workflow_contract.py"
SPEC = importlib.util.spec_from_file_location("workflow_contract", CHECKER_PATH)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class WorkflowContractTests(unittest.TestCase):
    def test_current_repository_passes(self) -> None:
        CHECKER.check(ROOT)

    def test_missing_gate_marker_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            clone = Path(raw)
            (clone / "docs").mkdir()
            agents = clone / "AGENTS.md"
            text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
            agents.write_text(text.replace("### G3：高影响动作确认", "### 高影响动作"), encoding="utf-8")
            for relative in CHECKER.REFERENCE_FILES:
                target = clone / relative
                target.write_text((ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaises(CHECKER.ContractError):
                CHECKER.check_gate_authority(clone)

    def test_nested_gate_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            clone = Path(raw)
            (clone / "docs").mkdir()
            (clone / "AGENTS.md").write_text((ROOT / "AGENTS.md").read_text(encoding="utf-8"), encoding="utf-8")
            for relative in CHECKER.REFERENCE_FILES:
                target = clone / relative
                target.write_text((ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
            (clone / "server").mkdir()
            nested = clone / "server/AGENTS.md"
            nested.write_text("# local gates\n", encoding="utf-8")
            with self.assertRaises(CHECKER.ContractError):
                CHECKER.check_gate_authority(clone)

    def test_removed_workflow_token_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            clone = Path(raw)
            token = "open" + "spec"
            (clone / "legacy.txt").write_text(token, encoding="utf-8")
            with self.assertRaises(CHECKER.ContractError):
                CHECKER.check_no_legacy_workflow(clone, [Path("legacy.txt")])


if __name__ == "__main__":
    unittest.main()

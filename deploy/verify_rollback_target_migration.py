#!/usr/bin/env python3
"""Fail closed unless a rollback target carries an exactly reviewed 0071."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "deploy" / "reviewed_release_b_rollback_migrations.json"


def _literal_dependencies(source: bytes) -> list[list[str]]:
    try:
        module = ast.parse(source, filename="0071_historical_calendar_release_b.py")
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise ValueError(f"target 0071 is not parseable Python: {exc}") from exc
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "Migration":
            for statement in node.body:
                if (
                    isinstance(statement, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "dependencies"
                        for target in statement.targets
                    )
                ):
                    try:
                        value = ast.literal_eval(statement.value)
                    except (ValueError, TypeError) as exc:
                        raise ValueError("target 0071 dependencies are not literal") from exc
                    if not isinstance(value, list) or any(
                        not isinstance(item, tuple)
                        or len(item) != 2
                        or not all(isinstance(part, str) for part in item)
                        for item in value
                    ):
                        raise ValueError("target 0071 dependencies have an invalid shape")
                    return [list(item) for item in value]
    raise ValueError("target 0071 Migration.dependencies is missing")


def verify(target_oid: str) -> dict:
    if len(target_oid) != 40 or any(char not in "0123456789abcdef" for char in target_oid):
        raise ValueError("target OID must be one lowercase 40-character commit id")
    allowlist = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    if allowlist.get("schema_version") != "release-b-rollback-migration-allowlist/v1":
        raise ValueError("rollback migration allowlist schema is invalid")
    path = allowlist.get("migration_path")
    variants = allowlist.get("reviewed_variants")
    if not isinstance(path, str) or not isinstance(variants, list) or not variants:
        raise ValueError("rollback migration allowlist is incomplete")
    try:
        source = subprocess.run(
            ["git", "show", f"{target_oid}:{path}"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"target does not expose reviewed 0071 content: {detail}") from exc
    digest = hashlib.sha256(source).hexdigest()
    dependencies = _literal_dependencies(source)
    matches = [
        item
        for item in variants
        if isinstance(item, dict)
        and item.get("sha256") == digest
        and item.get("dependencies") == dependencies
        and isinstance(item.get("rationale"), str)
        and item["rationale"].strip()
    ]
    if len(matches) != 1:
        raise ValueError(
            "target 0071 content/dependency contract is not in the reviewed rollback allowlist"
        )
    return {
        "migration_path": path,
        "sha256": digest,
        "dependencies": dependencies,
        "reviewed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-oid", required=True)
    args = parser.parse_args()
    try:
        result = verify(args.target_oid)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"rollback: {exc}; refusing before checkout", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

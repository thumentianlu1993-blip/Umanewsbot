#!/usr/bin/env python3
"""Enforce the Release 0077 forward-only recovery policy before checkout."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "deploy" / "reviewed_release_b_rollback_migrations.json"
EXPECTED_MIGRATION_PATHS = (
    "server/stable/migrations/0071_historical_calendar_release_b.py",
    "server/stable/migrations/0072_add_extended_racing_regions.py",
    "server/stable/migrations/0073_lifecycle_enforce_registry.py",
    "server/stable/migrations/0074_race_data_sync_r0_control_plane.py",
    "server/stable/migrations/0075_race_data_source_priority_and_reported_position.py",
    "server/stable/migrations/0076_alter_externaldataimporterror_racing_region_and_more.py",
    "server/stable/migrations/0077_racing_api_horse_identity_staging.py",
)
REVIEWED_TAIL_PATHS = frozenset(EXPECTED_MIGRATION_PATHS[-2:])


def _dependency_contract(node: ast.AST) -> list[str]:
    if (
        isinstance(node, ast.Tuple)
        and len(node.elts) == 2
        and all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.elts)
    ):
        return [item.value for item in node.elts]
    if (
        isinstance(node, ast.Call)
        and not node.keywords
        and len(node.args) == 1
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "swappable_dependency"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "migrations"
        and isinstance(node.args[0], ast.Attribute)
        and node.args[0].attr == "AUTH_USER_MODEL"
        and isinstance(node.args[0].value, ast.Name)
        and node.args[0].value.id == "settings"
    ):
        # Preserve the exact reviewed symbolic source expression without
        # importing or evaluating settings from the untrusted target commit.
        return ["settings.AUTH_USER_MODEL", "__first__"]
    raise ValueError("target migration dependencies have an invalid shape")


def _literal_dependencies(source: bytes, *, filename: str) -> list[list[str]]:
    try:
        module = ast.parse(source, filename=filename)
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise ValueError(f"target migration is not parseable Python: {exc}") from exc
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
                    if not isinstance(statement.value, ast.List):
                        raise ValueError("target migration dependencies have an invalid shape")
                    return [_dependency_contract(item) for item in statement.value.elts]
    raise ValueError("target migration Migration.dependencies is missing")


def _verify_target_migration_ceiling(target_oid: str) -> list[str]:
    try:
        output = subprocess.run(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                target_oid,
                "--",
                "server/stable/migrations",
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.decode("utf-8")
    except (subprocess.CalledProcessError, UnicodeDecodeError) as exc:
        detail = getattr(exc, "stderr", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise ValueError(f"cannot enumerate target migrations: {str(detail).strip()}") from exc
    paths = sorted(line.strip() for line in output.splitlines() if line.strip())
    unexpected_tail = []
    migration_root = Path("server/stable/migrations")
    for path in paths:
        migration_path = Path(path)
        if migration_path.parent != migration_root:
            unexpected_tail.append(path)
            continue
        name = migration_path.name
        if name == "__init__.py":
            continue
        match = re.match(r"^(\d{4})[^/]*\.py$", name)
        if not match or (
            int(match.group(1)) >= 76 and path not in REVIEWED_TAIL_PATHS
        ):
            unexpected_tail.append(path)
    if unexpected_tail:
        raise ValueError(
            "target migration graph exceeds the exact reviewed 0077 ceiling: "
            + ", ".join(sorted(unexpected_tail))
        )
    return paths


def _reviewed_target_contract(allowlist: dict, target_oid: str) -> dict:
    contracts = allowlist.get("reviewed_targets")
    if not isinstance(contracts, list):
        raise ValueError("reviewed rollback target list is invalid")
    valid_contracts = []
    for item in contracts:
        if not isinstance(item, dict) or set(item) != {
            "commit",
            "application_schema_leaf",
            "migration_paths_sha256",
            "rationale",
        }:
            raise ValueError("reviewed rollback target contract is invalid")
        commit = item["commit"]
        manifest_sha = item["migration_paths_sha256"]
        if (
            not isinstance(commit, str)
            or len(commit) != 40
            or any(char not in "0123456789abcdef" for char in commit)
            or item["application_schema_leaf"]
            != "stable.0077_racing_api_horse_identity_staging"
            or not isinstance(manifest_sha, str)
            or len(manifest_sha) != 64
            or any(char not in "0123456789abcdef" for char in manifest_sha)
            or not isinstance(item["rationale"], str)
            or not item["rationale"].strip()
        ):
            raise ValueError("reviewed rollback target contract is invalid")
        valid_contracts.append(item)
    matches = [item for item in valid_contracts if item["commit"] == target_oid]
    if len(matches) != 1:
        raise ValueError(
            "target commit is not an exact reviewed 0077-compatible rollback release"
        )
    return matches[0]


def _verify_required_migration(
    *, target_oid: str, path: str, variants: object
) -> dict:
    if not isinstance(variants, list) or not variants:
        raise ValueError("rollback migration allowlist contract is incomplete")
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
        raise ValueError(
            f"target does not expose required reviewed migration {path}: {detail}"
        ) from exc
    digest = hashlib.sha256(source).hexdigest()
    dependencies = _literal_dependencies(source, filename=path)
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
            f"target migration {path} content/dependency contract is not in "
            "the reviewed rollback allowlist"
        )
    return {
        "migration_path": path,
        "sha256": digest,
        "dependencies": dependencies,
        "reviewed": True,
    }


def verify(target_oid: str) -> dict:
    if len(target_oid) != 40 or any(char not in "0123456789abcdef" for char in target_oid):
        raise ValueError("target OID must be one lowercase 40-character commit id")
    allowlist = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    expected_policy = {
        "schema_version": "release-b-rollback-migration-allowlist/v6",
        "final_schema_leaf": "stable.0077_racing_api_horse_identity_staging",
        "recoverable_forward_partial_leaf": (
            "stable.0076_alter_externaldataimporterror_racing_region_and_more"
        ),
        "reverse_migration_allowed": False,
    }
    if any(allowlist.get(key) != value for key, value in expected_policy.items()):
        raise ValueError("rollback migration allowlist schema is invalid")
    recovery_mode = allowlist.get("recovery_mode")
    generic_allowed = allowlist.get("generic_code_rollback_allowed")
    backup_required = allowlist.get("verified_backup_restore_required")
    if recovery_mode == "forward-only-verified-backup-restore":
        if (
            generic_allowed is not False
            or backup_required is not True
            or allowlist.get("reviewed_targets") != []
        ):
            raise ValueError("forward-only rollback policy is invalid")
        raise ValueError(
            "0077 is forward-only: generic application rollback is disabled; "
            "restore the release-bound verified backup"
        )
    if (
        recovery_mode != "independently-reviewed-retained-schema"
        or generic_allowed is not True
        or backup_required is not True
    ):
        raise ValueError("rollback recovery mode is invalid")
    contracts = allowlist.get("required_migrations")
    if not isinstance(contracts, list):
        raise ValueError("rollback migration allowlist is incomplete")
    paths = [
        item.get("migration_path") if isinstance(item, dict) else None
        for item in contracts
    ]
    if tuple(paths) != EXPECTED_MIGRATION_PATHS:
        raise ValueError("rollback migration allowlist required paths are invalid")
    target_contract = _reviewed_target_contract(allowlist, target_oid)
    target_migration_paths = _verify_target_migration_ceiling(target_oid)
    migration_paths_sha256 = hashlib.sha256(
        "".join(f"{path}\n" for path in target_migration_paths).encode("utf-8")
    ).hexdigest()
    if migration_paths_sha256 != target_contract["migration_paths_sha256"]:
        raise ValueError("target migration path manifest is not the exact reviewed set")
    migrations = [
        _verify_required_migration(
            target_oid=target_oid,
            path=item["migration_path"],
            variants=item.get("reviewed_variants"),
        )
        for item in contracts
    ]
    return {
        "migrations": migrations,
        "recoverable_forward_partial_leaf": expected_policy[
            "recoverable_forward_partial_leaf"
        ],
        "final_schema_leaf": expected_policy["final_schema_leaf"],
        "reviewed": True,
        "reverse_migration_allowed": False,
        "target_migration_paths": target_migration_paths,
        "target_review": target_contract,
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

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_calendar_release_b_schema import (
    check_release_b_schema_compatibility,
)


class Command(BaseCommand):
    help = "只读检查 migration-history repair / Release B schema 兼容性。"

    def add_arguments(self, parser):
        parser.add_argument("--direction", choices=("forward", "reverse"), required=True)
        parser.add_argument("--json", action="store_true", dest="json_output")
        parser.add_argument(
            "--expected-migration-leaf-set",
            action="append",
            default=[],
            help="完整 leaf set 的一个成员；每个成员重复传入一次。",
        )
        # Kept only for callers from the first Release B rollout. It names one
        # exact leaf, never comma-delimited alternatives.
        parser.add_argument("--expected-migration-leaf", default="")
        parser.add_argument("--expected-database-identity-sha256", default="")
        parser.add_argument("--candidate-commit", default="")
        parser.add_argument("--candidate-image-id", default="")
        parser.add_argument("--enforce-production-audit", action="store_true")

    def handle(self, *args, **options):
        result = check_release_b_schema_compatibility(
            direction=options["direction"],
            enforce_production_audit=options["enforce_production_audit"],
        )
        result["candidate_commit"] = options["candidate_commit"]
        result["candidate_image_id"] = options["candidate_image_id"]
        expected_leaf_set = sorted(options["expected_migration_leaf_set"])
        legacy_leaf = options["expected_migration_leaf"].strip()
        if legacy_leaf:
            if expected_leaf_set:
                raise CommandError(
                    "expected migration leaf arguments are mutually exclusive"
                )
            expected_leaf_set = [legacy_leaf]
        expected_db = options["expected_database_identity_sha256"]
        identity_ok = (
            (not expected_leaf_set or result["migration_leaf_set"] == expected_leaf_set)
            and (
                not expected_db
                or result["database_identity_sha256"] == expected_db
            )
        )
        result["identity_ok"] = identity_ok
        result["ok"] = result["ok"] and identity_ok
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
        self.stdout.write(payload)
        if not result["ok"]:
            raise CommandError("Release B schema preflight failed")

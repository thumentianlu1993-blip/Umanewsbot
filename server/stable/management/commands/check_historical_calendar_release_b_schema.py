from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_calendar_release_b_schema import (
    check_release_b_schema_compatibility,
)


class Command(BaseCommand):
    help = "只读检查历史赛历 Release B 正向或反向 schema 兼容性。"

    def add_arguments(self, parser):
        parser.add_argument("--direction", choices=("forward", "reverse"), required=True)
        parser.add_argument("--json", action="store_true", dest="json_output")
        parser.add_argument("--expected-migration-leaf", default="")
        parser.add_argument("--expected-database-identity-sha256", default="")
        parser.add_argument("--candidate-commit", default="")
        parser.add_argument("--candidate-image-id", default="")

    def handle(self, *args, **options):
        result = check_release_b_schema_compatibility(direction=options["direction"])
        result["candidate_commit"] = options["candidate_commit"]
        result["candidate_image_id"] = options["candidate_image_id"]
        expected_leaf = options["expected_migration_leaf"]
        expected_db = options["expected_database_identity_sha256"]
        allowed_leaves = {item.strip() for item in expected_leaf.split(",") if item.strip()}
        identity_ok = (
            (not allowed_leaves or result["migration_leaf"] in allowed_leaves)
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

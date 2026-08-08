from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_calendar_release_b_handoff import (
    verify_closed_state,
    verify_preflight_artifact,
)
from stable.services.historical_calendar_release_b_schema import (
    database_vendor_contract,
)


class Command(BaseCommand):
    help = "服务关闭后、migrate 前复核精确 Release B handoff。"

    def add_arguments(self, parser):
        parser.add_argument("--artifact-path", required=True)
        parser.add_argument("--artifact-sha256", required=True)
        parser.add_argument("--candidate-commit", required=True)
        parser.add_argument("--candidate-image-id", required=True)
        parser.add_argument("--database-identity-sha256", required=True)
        parser.add_argument("--compose-file", required=True)
        parser.add_argument("--deployment-lock-token-sha256", required=True)
        parser.add_argument("--artifact-only", action="store_true")

    def handle(self, *args, **options):
        vendor = database_vendor_contract()
        if not vendor["ok"]:
            result = {
                "ok": False,
                "database_vendor": vendor,
                "drift_paths": ["database.vendor"],
            }
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
            raise CommandError("Release B handoff requires PostgreSQL")
        bindings = {
            "candidate_commit": options["candidate_commit"],
            "candidate_image_id": options["candidate_image_id"],
            "database_identity_sha256": options["database_identity_sha256"],
            "compose_file": options["compose_file"],
            "deployment_lock_token_sha256": options["deployment_lock_token_sha256"],
            "artifact_path": options["artifact_path"],
        }
        verifier = (
            verify_preflight_artifact
            if options["artifact_only"]
            else verify_closed_state
        )
        result = verifier(
            path=Path(options["artifact_path"]),
            expected_artifact_sha256=options["artifact_sha256"],
            expected_bindings=bindings,
        )
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not result["ok"]:
            mode = "artifact" if options["artifact_only"] else "closed-state"
            raise CommandError(f"{mode} Release B handoff verification failed")

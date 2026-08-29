from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.racing_api_exclusive_account_preflight import (
    RacingApiExclusivePreflightError,
    generate_exclusive_account_proof,
)


class Command(BaseCommand):
    help = "只读核验 TRA 账号无并发 caller，并生成最多 15 分钟有效的 0600 exclusive proof"

    def add_arguments(self, parser):
        parser.add_argument("--credential-alias", required=True)
        parser.add_argument("--scope-id", required=True)
        parser.add_argument("--scope-manifest-sha256", required=True)
        parser.add_argument("--runner-host-evidence", required=True, type=Path)
        parser.add_argument("--runner-host-evidence-sha256", required=True)
        parser.add_argument("--production-host-evidence", required=True, type=Path)
        parser.add_argument("--production-host-evidence-sha256", required=True)
        parser.add_argument("--expected-worker-node", action="append", required=True)
        parser.add_argument("--reserved-by", required=True)
        parser.add_argument("--decision-source-reference", required=True)
        parser.add_argument("--valid-minutes", type=int, default=15)
        parser.add_argument("--output-file", required=True, type=Path)

    def handle(self, **options):
        try:
            proof = generate_exclusive_account_proof(
                credential_alias=options["credential_alias"],
                scope_id=options["scope_id"],
                scope_manifest_sha256=options["scope_manifest_sha256"],
                runner_host_evidence_path=options["runner_host_evidence"],
                runner_host_evidence_sha256=options[
                    "runner_host_evidence_sha256"
                ],
                production_host_evidence_path=options[
                    "production_host_evidence"
                ],
                production_host_evidence_sha256=options[
                    "production_host_evidence_sha256"
                ],
                expected_worker_nodes=options["expected_worker_node"],
                reserved_by=options["reserved_by"],
                decision_source_reference=options["decision_source_reference"],
                output_file=options["output_file"],
                valid_minutes=options["valid_minutes"],
            )
        except (OSError, RacingApiExclusivePreflightError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        proof_sha = hashlib.sha256(options["output_file"].read_bytes()).hexdigest()
        self.stdout.write(
            json.dumps(
                {
                    "status": proof["status"],
                    "scope_id": proof["scope_id"],
                    "valid_until": proof["valid_until"],
                    "proof_sha256": proof_sha,
                    "database_writes": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

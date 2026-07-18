from __future__ import annotations

from datetime import datetime
import hashlib
import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services.race_live_racecard_sync import (
    prepare_race_live_racecards,
)
from stable.services.race_live_source_proof import the_racing_api_transport


class Command(BaseCommand):
    help = "为显式英国赛事准备受控、可审计的 TRA Free racecard 初始化 artifact"

    def add_arguments(self, parser):
        parser.add_argument("--event-id", action="append", type=int, required=True)
        parser.add_argument("--region-code", required=True)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--secret-env-file", required=True)
        parser.add_argument("--registry-file", required=True)
        parser.add_argument("--expected-registry-sha256", required=True)
        parser.add_argument("--approved-commit", required=True)
        parser.add_argument("--coverage-proof-digest", required=True)
        parser.add_argument("--terms-evidence-sha256", required=True)
        parser.add_argument("--policy-valid-until", required=True)
        parser.add_argument("--official-verification-route", required=True)
        parser.add_argument(
            "--official-verification-route-version",
            required=True,
        )
        parser.add_argument(
            "--official-verification-evidence-sha256",
            required=True,
        )
        parser.add_argument(
            "--official-verification-valid-until",
            required=True,
        )
        parser.add_argument("--confirm-real-network", action="store_true")

    def handle(self, *args, **options):
        if options["region_code"].lower() != "gb":
            raise CommandError("--region-code 必须精确为 gb")
        try:
            result = prepare_race_live_racecards(
                event_ids=options["event_id"],
                run_id=options["run_id"],
                artifact_root=settings.RACE_LIVE_RACECARD_ARTIFACT_ROOT,
                secret_env_file=options["secret_env_file"],
                registry_file=options["registry_file"],
                expected_registry_sha256=options[
                    "expected_registry_sha256"
                ],
                approved_commit=options["approved_commit"],
                coverage_proof_digest=options["coverage_proof_digest"],
                terms_evidence_sha256=options["terms_evidence_sha256"],
                policy_valid_until=datetime.fromisoformat(
                    options["policy_valid_until"].replace("Z", "+00:00")
                ),
                official_verification_route=options[
                    "official_verification_route"
                ],
                official_verification_route_version=options[
                    "official_verification_route_version"
                ],
                official_verification_evidence_sha256=options[
                    "official_verification_evidence_sha256"
                ],
                official_verification_valid_until=datetime.fromisoformat(
                    options["official_verification_valid_until"].replace(
                        "Z",
                        "+00:00",
                    )
                ),
                now=timezone.now(),
                transport=the_racing_api_transport,
                sleep=time.sleep,
                clock=timezone.now,
                confirm_real_network=options["confirm_real_network"],
            )
        except (
            OSError,
            ValueError,
            PermissionError,
            json.JSONDecodeError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        output = {
            "completed": result.completed,
            "request_count": result.request_count,
            "artifact": result.output_dir.name,
            "blocker_codes": list(result.blocker_codes),
        }
        manifest_path = result.output_dir / "manifest.json"
        if manifest_path.is_file():
            output["manifest_sha256"] = hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest()
        self.stdout.write(
            json.dumps(
                output,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

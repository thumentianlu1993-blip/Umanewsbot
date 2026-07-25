from __future__ import annotations

import json
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stable.services.p0_horse_identity_bootstrap import (
    P0HorseIdentityBootstrapError,
    approve_identity_bootstrap_artifact,
    commit_identity_bootstrap_artifact,
    prepare_identity_bootstrap_batch,
    select_identity_bootstrap_batch,
    verify_identity_bootstrap_commit,
    _write_json,
)


class Command(BaseCommand):
    help = "有界建立、审核并提交日本 P0 马 Netkeiba+JRA/NAR 双来源身份底稿。"

    def add_arguments(self, parser):
        phases = parser.add_mutually_exclusive_group(required=True)
        phases.add_argument("--select", action="store_true")
        phases.add_argument("--prepare", action="store_true")
        phases.add_argument("--approve", action="store_true")
        phases.add_argument("--commit", action="store_true")
        phases.add_argument("--verify", action="store_true")
        parser.add_argument("--manifest", default="")
        parser.add_argument("--output-dir", default="")
        parser.add_argument("--target-count", type=int, default=100)
        parser.add_argument("--scan-limit", type=int, default=500)
        parser.add_argument("--exclude-profile-id", action="append", type=int, default=[])
        parser.add_argument("--excluded-batch-id", default="")
        parser.add_argument("--exclusion-reason", default="")
        parser.add_argument("--approved-profile-id", action="append", type=int, default=[])
        parser.add_argument("--reviewer", default="")
        parser.add_argument("--approved-by", default="")
        parser.add_argument("--approved-sha256", default="")
        parser.add_argument("--confirm-approved-artifact", action="store_true")
        parser.add_argument("--allow-network", action="store_true")
        parser.add_argument(
            "--request-interval-seconds",
            type=float,
            default=settings.HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS,
        )
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        try:
            result = self._handle(**options)
        except (P0HorseIdentityBootstrapError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        output = json.dumps(result, ensure_ascii=False, default=str, indent=2)
        self.stdout.write(output if options["json"] else self.style.SUCCESS(output))

    def _handle(self, **options):
        manifest_value = options["manifest"]
        if options["select"]:
            if not options["output_dir"]:
                raise P0HorseIdentityBootstrapError("--select requires --output-dir")
            manifest = select_identity_bootstrap_batch(
                target_count=options["target_count"],
                excluded_profile_ids=options["exclude_profile_id"],
                excluded_batch_id=options["excluded_batch_id"],
                exclusion_reason=options["exclusion_reason"],
                scan_limit=options["scan_limit"],
            )
            output_path = Path(options["output_dir"]) / "selected_manifest.json"
            sha = _write_json(output_path, manifest)
            return {
                "phase": "select",
                "manifest_path": str(output_path),
                "file_sha256": sha,
                "input_sha256": manifest["input_sha256"],
                "horse_count": len(manifest["horses"]),
            }
        if not manifest_value:
            raise P0HorseIdentityBootstrapError(
                "--prepare/--approve/--commit/--verify require --manifest"
            )
        if options["prepare"]:
            if not options["output_dir"]:
                raise P0HorseIdentityBootstrapError("--prepare requires --output-dir")
            return {
                "phase": "prepare",
                **prepare_identity_bootstrap_batch(
                    manifest_value,
                    output_dir=options["output_dir"],
                    transport=requests.Session(),
                    allow_network=options["allow_network"],
                    environment_network_enabled=bool(
                        settings.HORSE_PROFILE_COMPLETION_ALLOW_NETWORK
                    ),
                    request_interval_seconds=options["request_interval_seconds"],
                ),
            }
        if options["approve"]:
            artifact = approve_identity_bootstrap_artifact(
                manifest_value,
                reviewer=options["reviewer"],
                approved_profile_ids=options["approved_profile_id"],
            )
            return {
                "phase": "approve",
                "approved_sha256": artifact["approved_sha256"],
                "approved_profile_ids": artifact["approval"]["approved_profile_ids"],
            }
        if not options["approved_sha256"]:
            raise P0HorseIdentityBootstrapError(
                "--commit/--verify require --approved-sha256"
            )
        if not options["confirm_approved_artifact"]:
            raise P0HorseIdentityBootstrapError(
                "--commit/--verify require --confirm-approved-artifact"
            )
        if options["commit"]:
            return {
                "phase": "commit",
                **commit_identity_bootstrap_artifact(
                    manifest_value,
                    approved_sha256=options["approved_sha256"],
                    approved_by=options["approved_by"],
                ),
            }
        return {
            "phase": "verify",
            **verify_identity_bootstrap_commit(
                manifest_value,
                approved_sha256=options["approved_sha256"],
            ),
        }

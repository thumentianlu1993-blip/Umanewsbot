from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.p0_horse_production_apply import (
    P0ReviewedArtifactError,
    commit_reviewed_p0_completion_artifact,
    dry_run_reviewed_p0_completion_artifact,
    prepare_reviewed_p0_completion_artifact,
    write_prepared_artifact_directory,
)


class Command(BaseCommand):
    help = (
        "准备、真实模拟或事务提交精确 SHA 绑定的 P0 50 匹审核资料；"
        "命令不访问网络，也不创建 RaceEvent。"
    )

    def add_arguments(self, parser):
        modes = parser.add_mutually_exclusive_group(required=True)
        modes.add_argument("--prepare", action="store_true")
        modes.add_argument("--dry-run", action="store_true")
        modes.add_argument("--commit", action="store_true")
        parser.add_argument("--research-v3")
        parser.add_argument("--authority-manifest")
        parser.add_argument("--authority-manifest-sha256")
        parser.add_argument("--profile-mapping-decisions")
        parser.add_argument("--reviewer-id", type=int)
        parser.add_argument("--output")
        parser.add_argument("--artifact")
        parser.add_argument("--artifact-sha256")
        parser.add_argument("--confirm-reviewed-artifact", action="store_true")

    def handle(self, *args, **options):
        try:
            if options["prepare"]:
                required = (
                    "research_v3",
                    "authority_manifest",
                    "authority_manifest_sha256",
                    "profile_mapping_decisions",
                    "reviewer_id",
                    "output",
                )
                missing = [name for name in required if options.get(name) in ("", None)]
                if missing:
                    raise CommandError(
                        "--prepare 缺少参数：" + ", ".join(f"--{name.replace('_', '-')}" for name in missing)
                    )
                artifact = prepare_reviewed_p0_completion_artifact(
                    research_v3_path=options["research_v3"],
                    authority_manifest_path=options["authority_manifest"],
                    authority_manifest_sha256=options["authority_manifest_sha256"],
                    profile_mapping_decisions_path=options["profile_mapping_decisions"],
                    reviewer_id=options["reviewer_id"],
                )
                package = write_prepared_artifact_directory(
                    output_directory=options["output"],
                    artifact=artifact,
                )
                self.stdout.write(json.dumps(package, ensure_ascii=False, sort_keys=True))
                return

            if not options.get("artifact") or not options.get("artifact_sha256"):
                raise CommandError(
                    "--dry-run/--commit 必须同时提供 --artifact 与 --artifact-sha256"
                )
            if options["dry_run"]:
                if options.get("confirm_reviewed_artifact"):
                    raise CommandError("--dry-run 不接受 --confirm-reviewed-artifact")
                report = dry_run_reviewed_p0_completion_artifact(
                    artifact_path=options["artifact"],
                    artifact_sha256=options["artifact_sha256"],
                )
            else:
                if not options.get("confirm_reviewed_artifact"):
                    raise CommandError("--commit 必须指定 --confirm-reviewed-artifact")
                report = commit_reviewed_p0_completion_artifact(
                    artifact_path=options["artifact"],
                    artifact_sha256=options["artifact_sha256"],
                    confirm_reviewed_artifact=True,
                )
            self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        except P0ReviewedArtifactError as exc:
            raise CommandError(str(exc)) from exc

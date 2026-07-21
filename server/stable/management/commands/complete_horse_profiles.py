from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stable.models import RacingRegion
from stable.services.horse_profile_completion import (
    CompletionOptions,
    apply_completion_artifact,
    load_completion_artifact,
    plan_profile_completion,
    write_completion_artifacts,
)
from stable.services.p0_horse_completion_adapters import (
    run_reviewed_p0_horse_completion_batch,
)


class Command(BaseCommand):
    help = "为全地区 P0 HorseProfile 生成外部资料补全 dry-run artifact，或应用已审核 artifact。"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--artifact", help="已审核 dry-run artifact JSON。commit 必填。")
        parser.add_argument("--confirm-reviewed-artifact", action="store_true", help="确认 artifact 已经人工审核。")
        parser.add_argument("--region", action="append", choices=[choice[0] for choice in RacingRegion.choices])
        parser.add_argument("--limit", type=int)
        parser.add_argument("--request-interval-seconds", type=float, default=settings.HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS)
        parser.add_argument("--cache-dir", default=settings.HORSE_PROFILE_COMPLETION_CACHE_DIR)
        parser.add_argument("--output-dir", default="")
        parser.add_argument(
            "--p0-reviewed-candidates",
            help="已确认纳入首批的五地区各 10 匹审核 CSV；仅支持 dry-run。",
        )
        parser.add_argument(
            "--p0-review-manifest",
            help="绑定审核 CSV 的人工审核 manifest；网络候选 dry-run 必填。",
        )
        parser.add_argument(
            "--p0-review-manifest-sha256",
            help="冻结审核 manifest 的 lowercase SHA-256；网络候选 dry-run 必填。",
        )
        parser.add_argument(
            "--p0-manual-supplements",
            help=(
                "已由不同人员录入和复核的逐字段人工补录 CSV；"
                "仅支持审核候选网络 dry-run。"
            ),
        )
        parser.add_argument(
            "--allow-network",
            action="store_true",
            help="仅为审核候选 dry-run 开启受控来源访问；还需服务端设置同时开启。",
        )

    def handle(self, *args, **options):
        if options["dry_run"] == options["commit"]:
            raise CommandError("必须且只能指定 --dry-run 或 --commit")
        allow_network = bool(options.get("allow_network"))
        if allow_network and not (
            options["dry_run"] and options.get("p0_reviewed_candidates")
        ):
            raise CommandError(
                "--allow-network 仅允许与 --dry-run 和 "
                "--p0-reviewed-candidates 同时使用"
            )
        if options.get("p0_review_manifest") and not options.get(
            "p0_reviewed_candidates"
        ):
            raise CommandError(
                "--p0-review-manifest 仅允许与 --p0-reviewed-candidates 同时使用"
            )
        if options.get("p0_review_manifest_sha256") and not options.get(
            "p0_reviewed_candidates"
        ):
            raise CommandError(
                "--p0-review-manifest-sha256 仅允许与 "
                "--p0-reviewed-candidates 同时使用"
            )
        if options.get("p0_manual_supplements") and not (
            options.get("p0_reviewed_candidates") and allow_network
        ):
            raise CommandError(
                "--p0-manual-supplements 仅允许与 "
                "--p0-reviewed-candidates、--dry-run 和 --allow-network "
                "同时使用"
            )
        if allow_network and not settings.HORSE_PROFILE_COMPLETION_ALLOW_NETWORK:
            raise CommandError(
                "HORSE_PROFILE_COMPLETION_ALLOW_NETWORK 未开启，拒绝网络批次"
            )
        if allow_network and not options.get("p0_review_manifest"):
            raise CommandError(
                "--allow-network 与 --p0-reviewed-candidates 使用时必须指定 "
                "--p0-review-manifest"
            )
        expected_review_manifest_sha256 = str(
            options.get("p0_review_manifest_sha256") or ""
        )
        if allow_network and not re.fullmatch(
            r"[0-9a-f]{64}",
            expected_review_manifest_sha256,
        ):
            raise CommandError(
                "网络审核批次必须指定合法的 lowercase "
                "--p0-review-manifest-sha256"
            )
        configured_review_manifest_sha256 = str(
            settings.HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256 or ""
        )
        if allow_network and (
            not re.fullmatch(
                r"[0-9a-f]{64}",
                configured_review_manifest_sha256,
            )
            or configured_review_manifest_sha256
            != expected_review_manifest_sha256
        ):
            raise CommandError(
                "HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256 "
                "必须合法且与 CLI 冻结 SHA 完全一致"
            )
        if options["commit"]:
            if options.get("p0_reviewed_candidates"):
                raise CommandError("--p0-reviewed-candidates 仅支持 --dry-run")
            if not options.get("artifact"):
                raise CommandError("--commit 必须指定 --artifact")
            if not options.get("confirm_reviewed_artifact"):
                raise CommandError("--commit 必须显式指定 --confirm-reviewed-artifact")
            payload = load_completion_artifact(options["artifact"])
            result = apply_completion_artifact(payload)
            self.stdout.write(self.style.SUCCESS(f"commit: {result}"))
            return
        output_dir = options["output_dir"] or Path("runtime/horse_profile_completion") / "dry-run"
        if options.get("p0_reviewed_candidates"):
            manifest = run_reviewed_p0_horse_completion_batch(
                reviewed_candidates_csv=Path(options["p0_reviewed_candidates"]),
                review_manifest_path=(
                    Path(options["p0_review_manifest"])
                    if options.get("p0_review_manifest")
                    else None
                ),
                expected_review_manifest_sha256=(
                    expected_review_manifest_sha256 or None
                ),
                manual_supplements_csv=(
                    Path(options["p0_manual_supplements"])
                    if options.get("p0_manual_supplements")
                    else None
                ),
                cache_dir=Path(options["cache_dir"]),
                output_dir=Path(output_dir),
                allow_network=allow_network,
                network_regions=(
                    tuple(options.get("region") or ())
                    if allow_network
                    else ()
                ),
                request_interval_seconds=options["request_interval_seconds"],
            )
            self.stdout.write(
                self.style.SUCCESS(f"p0 reviewed candidates dry-run: {manifest['summary']}")
            )
            self.stdout.write(str(manifest))
            return
        plan = plan_profile_completion(
            CompletionOptions(
                regions=options.get("region"),
                limit=options.get("limit"),
                output_dir=output_dir,
                request_interval_seconds=options["request_interval_seconds"],
                cache_dir=options["cache_dir"],
            )
        )
        artifacts = write_completion_artifacts(plan, output_dir)
        self.stdout.write(self.style.SUCCESS(f"dry-run: {plan['summary']}"))
        self.stdout.write(str(artifacts))

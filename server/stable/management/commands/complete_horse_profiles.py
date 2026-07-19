from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stable.services.horse_profile_completion import (
    CompletionOptions,
    apply_completion_artifact,
    load_completion_artifact,
    plan_profile_completion,
    write_completion_artifacts,
)
from stable.services.regions import HORSE_PROFILE_REGIONS


class Command(BaseCommand):
    help = "为全地区 P0 HorseProfile 生成外部资料补全 dry-run artifact，或应用已审核 artifact。"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--artifact", help="已审核 dry-run artifact JSON。commit 必填。")
        parser.add_argument("--confirm-reviewed-artifact", action="store_true", help="确认 artifact 已经人工审核。")
        parser.add_argument("--region", action="append", choices=list(HORSE_PROFILE_REGIONS))
        parser.add_argument("--limit", type=int)
        parser.add_argument("--request-interval-seconds", type=float, default=settings.HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS)
        parser.add_argument("--cache-dir", default=settings.HORSE_PROFILE_COMPLETION_CACHE_DIR)
        parser.add_argument("--output-dir", default="")

    def handle(self, *args, **options):
        if options["dry_run"] == options["commit"]:
            raise CommandError("必须且只能指定 --dry-run 或 --commit")
        if options["commit"]:
            if not options.get("artifact"):
                raise CommandError("--commit 必须指定 --artifact")
            if not options.get("confirm_reviewed_artifact"):
                raise CommandError("--commit 必须显式指定 --confirm-reviewed-artifact")
            payload = load_completion_artifact(options["artifact"])
            result = apply_completion_artifact(payload)
            self.stdout.write(self.style.SUCCESS(f"commit: {result}"))
            return
        output_dir = options["output_dir"] or Path("runtime/horse_profile_completion") / "dry-run"
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

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.models import RacingRegion
from stable.services import p0_horse_profiles


class Command(BaseCommand):
    help = "同步新版 P0 马范围或预览 P0 资料补全队列。"

    def add_arguments(self, parser):
        parser.add_argument("--sync-sources", action="store_true", help="从术语和重点赛事参赛证据同步 P0 来源。")
        parser.add_argument("--queue", action="store_true", help="预览 P0 补全队列；只读，不写资料字段。")
        parser.add_argument("--commit", action="store_true", help="配合 --sync-sources 写入 P0 来源；未指定时为 dry-run。")
        parser.add_argument("--full-reconcile", action="store_true", help="全地区完整对账并撤销已失效来源；必须配合 --sync-sources --commit。")
        parser.add_argument("--region", action="append", choices=[choice[0] for choice in RacingRegion.choices])
        parser.add_argument("--profile-id", action="append", type=int, help="预览指定马资料；可重复指定。")
        parser.add_argument("--limit-per-region", type=int, default=10)
        parser.add_argument("--json", action="store_true", help="输出机器可读 JSON。")

    def handle(self, *args, **options):
        if options["sync_sources"] == options["queue"]:
            raise CommandError("必须且只能指定 --sync-sources 或 --queue")
        if options["limit_per_region"] <= 0:
            raise CommandError("--limit-per-region 必须大于 0")
        if options["full_reconcile"] and not (options["sync_sources"] and options["commit"]):
            raise CommandError("--full-reconcile 必须配合 --sync-sources --commit")
        if options["full_reconcile"] and options.get("region"):
            raise CommandError("--full-reconcile 只能用于全地区同步，不能与 --region 同时使用")
        if options["sync_sources"] and options.get("profile_id"):
            raise CommandError("--profile-id 只适用于 --queue")

        if options["sync_sources"]:
            result = p0_horse_profiles.sync_p0_horse_sources(
                commit=options["commit"],
                regions=options.get("region"),
                reconcile=options["full_reconcile"],
            )
        else:
            queue = p0_horse_profiles.build_p0_completion_queue(
                regions=options.get("region"),
                limit_per_region=options.get("limit_per_region"),
                profile_ids=options.get("profile_id"),
            )
            result = {
                region: [
                    {
                        "profile_id": item.profile_id,
                        "display_name": item.profile.display_name,
                        "reasons": item.reasons,
                        "source_ids": item.source_ids,
                    }
                    for item in rows
                ]
                for region, rows in queue.items()
            }

        if options["json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str, indent=2))
        else:
            self.stdout.write(self.style.SUCCESS(str(result)))

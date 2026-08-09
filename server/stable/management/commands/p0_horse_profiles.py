from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services import p0_horse_profiles


class Command(BaseCommand):
    help = "同步新版 P0 马范围或预览 P0 资料补全队列。"

    def add_arguments(self, parser):
        parser.add_argument("--sync-sources", action="store_true", help="从术语和重点赛事参赛证据同步 P0 来源。")
        parser.add_argument("--queue", action="store_true", help="预览 P0 补全队列；只读，不写资料字段。")
        parser.add_argument(
            "--extract-candidates",
            action="store_true",
            help="从重点赛事只读提取逐马候选池和每地区人工样本 artifact。",
        )
        parser.add_argument("--commit", action="store_true", help="配合 --sync-sources 写入 P0 来源；未指定时为 dry-run。")
        parser.add_argument("--full-reconcile", action="store_true", help="全地区完整对账并撤销已失效来源；必须配合 --sync-sources --commit。")
        parser.add_argument(
            "--region",
            action="append",
            choices=sorted(p0_horse_profiles.P0_PARTICIPANT_CANDIDATE_REGIONS),
        )
        parser.add_argument("--profile-id", action="append", type=int, help="预览指定马资料；可重复指定。")
        parser.add_argument("--year", type=int, help="候选提取限定单一自然年。")
        parser.add_argument(
            "--actual-starts-only",
            action="store_true",
            help="候选提取仅保留有实际赛果且非退出/未知状态的参赛马。",
        )
        parser.add_argument("--limit-per-region", type=int)
        parser.add_argument(
            "--output-dir",
            default="",
            help="--extract-candidates 输出目录；默认创建带时间戳的新 run 目录。",
        )
        parser.add_argument("--json", action="store_true", help="输出机器可读 JSON。")

    def handle(self, *args, **options):
        selected_modes = sum(
            bool(options[mode])
            for mode in ("sync_sources", "queue", "extract_candidates")
        )
        if selected_modes != 1:
            raise CommandError("必须且只能指定 --sync-sources、--queue 或 --extract-candidates")
        if options["limit_per_region"] is not None and options["limit_per_region"] <= 0:
            raise CommandError("--limit-per-region 必须大于 0")
        if options["commit"] and not options["sync_sources"]:
            raise CommandError("--commit 只能配合 --sync-sources")
        unsupported_operational_regions = set(options.get("region") or ()) - p0_horse_profiles.P0_REGIONS
        if not options["extract_candidates"] and unsupported_operational_regions:
            raise CommandError(
                "新增地区当前只允许 --extract-candidates，只读候选通过 reviewed import 前不得同步或排队"
            )
        if options["output_dir"] and not options["extract_candidates"]:
            raise CommandError("--output-dir 只能配合 --extract-candidates")
        if (options["year"] is not None or options["actual_starts_only"]) and not options["extract_candidates"]:
            raise CommandError("--year/--actual-starts-only 只能配合 --extract-candidates")
        if options["year"] is not None and options["year"] < 1998:
            raise CommandError("--year 必须不早于 1998")
        if options["limit_per_region"] is not None and options["sync_sources"]:
            raise CommandError("--limit-per-region 只适用于 --queue 或 --extract-candidates")
        if options["full_reconcile"] and not (options["sync_sources"] and options["commit"]):
            raise CommandError("--full-reconcile 必须配合 --sync-sources --commit")
        if options["full_reconcile"] and options.get("region"):
            raise CommandError("--full-reconcile 只能用于全地区同步，不能与 --region 同时使用")
        if options["sync_sources"] and options.get("profile_id"):
            raise CommandError("--profile-id 只适用于 --queue")
        if options["extract_candidates"] and options.get("profile_id"):
            raise CommandError("--profile-id 只适用于 --queue")

        if options["sync_sources"]:
            result = p0_horse_profiles.sync_p0_horse_sources(
                commit=options["commit"],
                regions=options.get("region"),
                reconcile=options["full_reconcile"],
            )
        elif options["queue"]:
            queue = p0_horse_profiles.build_p0_completion_queue(
                regions=options.get("region"),
                limit_per_region=options.get("limit_per_region") or 10,
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
        else:
            output_dir = (
                Path(options["output_dir"])
                if options["output_dir"]
                else Path("runtime/p0_horse_candidates")
                / timezone.now().strftime("dry-run-%Y%m%d-%H%M%S")
            )
            artifact = p0_horse_profiles.build_p0_participant_candidate_artifact(
                regions=options.get("region"),
                sample_per_region=options["limit_per_region"] or 10,
                year=options["year"],
                actual_starts_only=options["actual_starts_only"],
            )
            try:
                paths = p0_horse_profiles.write_p0_participant_candidate_artifacts(
                    artifact,
                    output_dir,
                )
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            result = {"summary": artifact["summary"], "artifacts": paths}

        if options["json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str, indent=2))
        else:
            self.stdout.write(self.style.SUCCESS(str(result)))

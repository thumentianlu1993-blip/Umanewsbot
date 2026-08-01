#!/usr/bin/env python3
"""Link HorseRaceRecord rows (from The Racing API) to existing RaceEvents.

Uses heuristic matching by race date, racecourse, race name similarity, and the
presence of the horse name in the event's runner table.  Run with --dry-run
first to review the hit rate.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from stable.models import HorseRaceRecord
from stable.services.horse_race_record_event_matching import RaceEventMatcher, match_horse_race_records


BATCH_SIZE = 1000


class Command(BaseCommand):
    help = "启发式关联 The Racing API 的 HorseRaceRecord 到已有 RaceEvent。"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="预览匹配结果，不写入数据库。")
        parser.add_argument("--threshold", type=float, default=0.6, help="匹配阈值（0-1），默认 0.6。")
        parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="每批处理的记录数。")
        parser.add_argument("--limit", type=int, help="最多处理的记录数（用于测试）。")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        threshold = options["threshold"]
        batch_size = options["batch_size"]
        limit = options.get("limit")

        self.stdout.write("正在预加载 RaceEvent 索引（含出马表）...")
        matcher = RaceEventMatcher()
        self.stdout.write(f"已索引 {len(matcher.events)} 个赛事")

        base_qs = HorseRaceRecord.objects.filter(
            source_refs__has_key="theracingapi_race_id",
            event__isnull=True,
        ).select_related("horse_profile").order_by("id")

        total = base_qs.count()
        self.stdout.write(f"待关联记录：{total}")

        overall: dict[str, int] = {"matched": 0, "unmatched": 0, "skipped_already_linked": 0, "total": 0}
        processed = 0
        remaining_limit = limit

        while True:
            current_batch_size = batch_size
            if remaining_limit is not None:
                current_batch_size = min(batch_size, remaining_limit)
                if current_batch_size <= 0:
                    break

            records = list(base_qs[:current_batch_size])
            if not records:
                break

            result = match_horse_race_records(
                records,
                matcher=matcher,
                threshold=threshold,
                dry_run=dry_run,
            )

            for key in ("matched", "unmatched", "skipped_already_linked", "total"):
                overall[key] += result[key]

            processed += len(records)
            if remaining_limit is not None:
                remaining_limit -= len(records)

            # Move the window forward.
            last_id = records[-1].id
            base_qs = base_qs.filter(id__gt=last_id)

            self.stdout.write(
                f"[batch] processed={processed}/{total} "
                f"matched={overall['matched']} unmatched={overall['unmatched']} "
                f"skipped={overall['skipped_already_linked']}"
            )

        action = "将关联" if dry_run else "已关联"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {overall['matched']} 条记录到赛事，"
                f"未匹配 {overall['unmatched']} 条，"
                f"已跳过 {overall['skipped_already_linked']} 条"
            )
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("这是干跑（dry-run），未写入数据库。"))

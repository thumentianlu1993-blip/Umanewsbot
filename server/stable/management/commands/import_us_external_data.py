from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.external_us_racing_data import USExternalDataImporter, USImportError, USImportOptions


class Command(BaseCommand):
    help = "受控导入美国 Horse Racing Nation 外部赛马数据；默认 dry-run，显式 --commit 才写入。"

    def add_arguments(self, parser):
        parser.add_argument("--race-ids", help="逗号分隔的 HRN race_id；用于按 plan-only 输出执行精确批次")
        parser.add_argument("--race-date", help="按美国赛日导入，例如 2026-06-25")
        parser.add_argument("--recent-days", type=int, help="按最近 N 天 HRN 日期范围导入")
        parser.add_argument("--start-date", help="日期范围开始，例如 2026-04-27")
        parser.add_argument("--end-date", help="日期范围结束，例如 2026-06-26")
        parser.add_argument("--seed-track", default="churchill-downs", help="用于发现同日赛场的 HRN track slug")
        parser.add_argument("--limit-tracks", type=int, dest="limit_tracks", help="最多抓取的同日赛场数")
        parser.add_argument("--limit-races", type=int, dest="limit_races", help="最多解析的比赛数")
        parser.add_argument("--limit-horses", type=int, dest="limit_horses", help="最多补抓的马匹 profile 数")
        parser.add_argument("--skip-races", type=int, default=0, dest="skip_races", help="日期范围内跳过前 N 场，用于拆批续跑")
        parser.add_argument("--plan-only", action="store_true", help="只生成 race 批次计划，不抓 horse profile、不写表")
        parser.add_argument("--batch-size", type=int, default=20, dest="batch_size", help="plan-only 输出每批 race 数")
        parser.add_argument("--allow-network", action="store_true", help="允许真实网络请求；默认关闭")
        parser.add_argument("--commit", action="store_true", help="将抓取结果写入 External* 表；默认只 dry-run")
        parser.add_argument("--max-races", type=int, help="单次最大比赛数")
        parser.add_argument("--max-horses", type=int, help="单次最大马匹数")
        parser.add_argument("--max-requests", type=int, help="单次最大外部请求数")

    def handle(self, *args, **options):
        range_modes = [bool(options["race_ids"]), bool(options["race_date"]), bool(options["recent_days"]), bool(options["start_date"])]
        if sum(range_modes) != 1:
            raise CommandError("必须且只能指定 --race-ids、--race-date、--recent-days 或 --start-date/--end-date 其中一种。")
        if options["start_date"] and not options["end_date"]:
            raise CommandError("--start-date 和 --end-date 必须同时指定。")
        if options["plan_only"] and options["commit"]:
            raise CommandError("--plan-only 不能与 --commit 同时使用。")
        if options["plan_only"] and options["race_ids"]:
            raise CommandError("--race-ids 不能与 --plan-only 同时使用。")
        if options["plan_only"] and not options["allow_network"]:
            raise CommandError("--plan-only 必须与 --allow-network 一起使用。")
        importer = USExternalDataImporter(
            USImportOptions.from_settings(
                dry_run=not options["commit"],
                allow_network=options["allow_network"],
                max_races=options["max_races"],
                max_horses=options["max_horses"],
                max_requests=options["max_requests"],
            )
        )
        try:
            if options["race_ids"]:
                result = importer.import_race_ids(
                    [item.strip() for item in options["race_ids"].split(",") if item.strip()],
                    limit_horses=options.get("limit_horses"),
                )
            elif options["plan_only"] and options["recent_days"]:
                result = importer.plan_recent_days(
                    options["recent_days"],
                    end_date=options.get("end_date"),
                    seed_track=options["seed_track"],
                    limit_tracks=options.get("limit_tracks"),
                    batch_size=options["batch_size"],
                )
            elif options["plan_only"] and options["start_date"]:
                result = importer.plan_date_range(
                    options["start_date"],
                    options["end_date"],
                    seed_track=options["seed_track"],
                    limit_tracks=options.get("limit_tracks"),
                    batch_size=options["batch_size"],
                )
            elif options["plan_only"]:
                result = importer.plan_date_range(
                    options["race_date"],
                    options["race_date"],
                    seed_track=options["seed_track"],
                    limit_tracks=options.get("limit_tracks"),
                    batch_size=options["batch_size"],
                )
            elif options["recent_days"]:
                result = importer.import_recent_days(
                    options["recent_days"],
                    end_date=options.get("end_date"),
                    seed_track=options["seed_track"],
                    limit_tracks=options.get("limit_tracks"),
                    limit_races=options.get("limit_races"),
                    limit_horses=options.get("limit_horses"),
                    skip_races=options.get("skip_races") or 0,
                )
            elif options["start_date"]:
                result = importer.import_date_range(
                    options["start_date"],
                    options["end_date"],
                    seed_track=options["seed_track"],
                    limit_tracks=options.get("limit_tracks"),
                    limit_races=options.get("limit_races"),
                    limit_horses=options.get("limit_horses"),
                    skip_races=options.get("skip_races") or 0,
                )
            else:
                result = importer.import_race_date(
                    options["race_date"],
                    seed_track=options["seed_track"],
                    limit_tracks=options.get("limit_tracks"),
                    limit_races=options.get("limit_races"),
                    limit_horses=options.get("limit_horses"),
                )
        except USImportError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))

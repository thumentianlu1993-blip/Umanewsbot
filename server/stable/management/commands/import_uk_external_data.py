from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.external_uk_racing_data import UKExternalDataImporter, UKImportError, UKImportOptions


class Command(BaseCommand):
    help = "受控导入英国 Sporting Life 外部赛马数据；默认 dry-run。"

    def add_arguments(self, parser):
        parser.add_argument("--recent-days", type=int, help="按最近 N 天 Sporting Life results 范围导入")
        parser.add_argument("--start-date", help="日期范围开始，例如 2026-04-27")
        parser.add_argument("--end-date", help="日期范围结束，例如 2026-06-26")
        parser.add_argument("--race-urls", help="逗号分隔的 Sporting Life racecard URL；用于按 plan-only 输出执行精确批次")
        parser.add_argument("--commit", action="store_true", help="提交写入 External* 缓存表；默认只 dry-run")
        parser.add_argument("--plan-only", action="store_true", help="只枚举日期范围 race links 和批次，不请求 racecard/horse profile")
        parser.add_argument("--batch-size", type=int, default=20, help="plan-only 输出的每批比赛数")
        parser.add_argument("--allow-network", action="store_true", help="允许真实网络请求；默认关闭")
        parser.add_argument("--limit-races", type=int, dest="limit_races", help="本次真实网络抓取最多解析的比赛数")
        parser.add_argument("--limit-horses", type=int, dest="limit_horses", help="本次真实网络抓取最多补抓的马匹详情数")
        parser.add_argument("--skip-races", type=int, default=0, dest="skip_races", help="日期范围内跳过前 N 场，用于拆批续跑")
        parser.add_argument("--max-races", type=int, help="单次最大比赛数")
        parser.add_argument("--max-horses", type=int, help="单次最大马匹数")
        parser.add_argument("--max-requests", type=int, help="单次最大外部请求数")

    def handle(self, *args, **options):
        if not options["race_urls"] and not options["recent_days"] and not options["start_date"]:
            raise CommandError("必须指定 --race-urls、--recent-days 或 --start-date/--end-date。")
        if options["race_urls"] and (options["recent_days"] or options["start_date"] or options["plan_only"]):
            raise CommandError("--race-urls 不能和日期范围或 --plan-only 同时指定。")
        if options["recent_days"] and options["start_date"]:
            raise CommandError("--recent-days 和 --start-date/--end-date 不能同时指定。")
        if options["start_date"] and not options["end_date"]:
            raise CommandError("--start-date 和 --end-date 必须同时指定。")
        if options["plan_only"] and not options["allow_network"]:
            raise CommandError("--plan-only 必须与 --allow-network 一起使用。")
        importer = UKExternalDataImporter(
            UKImportOptions.from_settings(
                dry_run=not options["commit"],
                allow_network=options["allow_network"],
                max_races=options["max_races"],
                max_horses=options["max_horses"],
                max_requests=options["max_requests"],
            )
        )
        try:
            if options["race_urls"]:
                race_urls = [url.strip() for url in options["race_urls"].split(",") if url.strip()]
                result = importer.import_race_urls(
                    race_urls,
                    limit_horses=options.get("limit_horses"),
                )
            elif options["plan_only"] and options["recent_days"]:
                result = importer.plan_recent_days(
                    options["recent_days"],
                    end_date=options.get("end_date"),
                    batch_size=options.get("batch_size") or 20,
                )
            elif options["plan_only"]:
                result = importer.plan_date_range(
                    options["start_date"],
                    options["end_date"],
                    batch_size=options.get("batch_size") or 20,
                )
            elif options["recent_days"]:
                result = importer.import_recent_days(
                    options["recent_days"],
                    end_date=options.get("end_date"),
                    limit_races=options.get("limit_races"),
                    limit_horses=options.get("limit_horses"),
                    skip_races=options.get("skip_races") or 0,
                )
            else:
                result = importer.import_date_range(
                    options["start_date"],
                    options["end_date"],
                    limit_races=options.get("limit_races"),
                    limit_horses=options.get("limit_horses"),
                    skip_races=options.get("skip_races") or 0,
                )
        except UKImportError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))

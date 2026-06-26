from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.models import ExternalDataImportRun, ExternalDataSource
from stable.services.external_hkjc_data import HKJCExternalDataImporter, HKJCImportError, HKJCImportOptions


class Command(BaseCommand):
    help = "受控导入 HKJC 外部赛马数据；默认 dry-run，可用 payload 文件做小样本提交。"

    def add_arguments(self, parser):
        parser.add_argument("--race-date", help="按香港赛日导入，例如 2026-06-21")
        parser.add_argument("--race-id", help="按 HKJC 单场 race_id 导入")
        parser.add_argument("--race-ids", help="按逗号分隔的 HKJC race_id 列表导入精确批次")
        parser.add_argument("--horse-id", help="按 HKJC 单匹 horse_id 导入")
        parser.add_argument("--recent-days", type=int, help="按最近 N 天真实 HKJC 赛日范围导入")
        parser.add_argument("--start-date", help="日期范围开始，例如 2026-04-27")
        parser.add_argument("--end-date", help="日期范围结束，例如 2026-06-26")
        parser.add_argument("--payload-file", default="", help="隔离样本 JSON 文件；可用于 dry-run 或提交")
        parser.add_argument("--commit", action="store_true", help="提交写入 External* 缓存表；默认只 dry-run")
        parser.add_argument("--allow-network", action="store_true", help="预留真实网络请求开关；默认关闭")
        parser.add_argument("--max-races", type=int, help="单次最大比赛数配置记录")
        parser.add_argument("--max-horses", type=int, help="单次最大马匹数配置记录")
        parser.add_argument("--limit-races", type=int, dest="limit_races", help="本次真实网络抓取最多解析的比赛数")
        parser.add_argument("--limit-horses", type=int, dest="limit_horses", help="本次真实网络抓取最多补抓的马匹详情数")
        parser.add_argument("--skip-races", type=int, default=0, help="从日期范围 race link 序列开头跳过 N 场，用于按 plan-only 批次续跑")
        parser.add_argument("--max-requests", type=int, help="单次最大外部请求数")
        parser.add_argument("--plan-only", action="store_true", help="只抓赛日和 race links 生成拆批计划，不抓单场结果或马匹详情")
        parser.add_argument("--lookup-name", help="查询本地 HKJC 马名索引，不发起外部请求")
        parser.add_argument("--stats-run-id", type=int, help="查看指定 HKJC 导入运行统计")

    def handle(self, *args, **options):
        importer = HKJCExternalDataImporter(
            HKJCImportOptions.from_settings(
                dry_run=not options["commit"],
                allow_network=options["allow_network"],
                max_races=options["max_races"],
                max_horses=options["max_horses"],
                max_requests=options["max_requests"],
            )
        )
        if options["lookup_name"]:
            aliases = importer.lookup_alias(options["lookup_name"])
            self.stdout.write(
                json.dumps(
                    [
                        {
                            "external_horse_id": alias.external_horse_id,
                            "source_language": alias.source_language,
                            "name_en": alias.name_en,
                            "name_zh_hant": alias.name_zh_hant,
                            "name": alias.name_ja,
                            "confidence": alias.confidence,
                            "last_seen_at": alias.last_seen_at.isoformat(),
                        }
                        for alias in aliases
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        if options["stats_run_id"]:
            run = ExternalDataImportRun.objects.get(pk=options["stats_run_id"], source=ExternalDataSource.HKJC)
            self.stdout.write(
                json.dumps(
                    {
                        "run_id": run.id,
                        "source": run.source,
                        "target_type": run.target_type,
                        "status": run.status,
                        "success_count": run.success_count,
                        "skipped_count": run.skipped_count,
                        "failure_count": run.failure_count,
                        "coverage_stats": run.coverage_stats,
                        "error_count": run.errors.count(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return

        has_date_range = bool(options.get("start_date"))
        target_count = sum(1 for key in ("race_date", "race_id", "race_ids", "horse_id", "recent_days") if options.get(key))
        target_count += 1 if has_date_range else 0
        if target_count != 1:
            raise CommandError("必须且只能指定 --race-date、--race-id、--race-ids、--horse-id、--recent-days 或 --start-date/--end-date 之一。")
        if has_date_range and not options.get("end_date"):
            raise CommandError("--start-date 和 --end-date 必须同时指定。")
        if options.get("end_date") and not (options.get("start_date") or options.get("recent_days")):
            raise CommandError("--end-date 只能与 --recent-days 或 --start-date 一起使用。")
        if options.get("plan_only") and options["commit"]:
            raise CommandError("--plan-only 只能 dry-run，不能与 --commit 同时使用。")
        if options.get("plan_only") and not options["allow_network"]:
            raise CommandError("--plan-only 必须与 --allow-network 一起使用。")
        if options.get("plan_only") and not (options.get("recent_days") or options.get("start_date")):
            raise CommandError("--plan-only 只能与 --recent-days 或 --start-date/--end-date 一起使用。")
        if options.get("race_ids") and not options["allow_network"]:
            raise CommandError("--race-ids 必须与 --allow-network 一起使用。")
        if options.get("race_ids") and options.get("payload_file"):
            raise CommandError("--race-ids 不支持 --payload-file。")
        if options.get("race_ids") and options.get("limit_races"):
            raise CommandError("--race-ids 已经精确指定比赛，不支持 --limit-races。")
        if options.get("race_ids") and options.get("skip_races"):
            raise CommandError("--race-ids 已经精确指定比赛，不支持 --skip-races。")
        try:
            if options.get("plan_only") and options["recent_days"]:
                result = importer.plan_recent_days(
                    options["recent_days"],
                    end_date=options.get("end_date"),
                    suggested_limit_races=options.get("limit_races"),
                )
            elif options.get("plan_only") and options["start_date"]:
                result = importer.plan_date_range(
                    options["start_date"],
                    options["end_date"],
                    suggested_limit_races=options.get("limit_races"),
                )
            elif options["race_date"]:
                result = importer.import_race_date(options["race_date"], payload_file=options["payload_file"])
            elif options["race_id"]:
                result = importer.import_race(options["race_id"], payload_file=options["payload_file"])
            elif options["race_ids"]:
                race_ids = [race_id.strip() for race_id in options["race_ids"].split(",") if race_id.strip()]
                result = importer.import_race_batch(race_ids, limit_horses=options.get("limit_horses"))
            elif options["recent_days"]:
                result = importer.import_recent_days(
                    options["recent_days"],
                    end_date=options.get("end_date"),
                    limit_races=options.get("limit_races"),
                    limit_horses=options.get("limit_horses"),
                    skip_races=options.get("skip_races") or 0,
                )
            elif options["start_date"]:
                result = importer.import_date_range(
                    options["start_date"],
                    options["end_date"],
                    limit_races=options.get("limit_races"),
                    limit_horses=options.get("limit_horses"),
                    skip_races=options.get("skip_races") or 0,
                )
            else:
                result = importer.import_horse(options["horse_id"], payload_file=options["payload_file"])
        except HKJCImportError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))

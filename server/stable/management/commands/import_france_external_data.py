from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.external_france_racing_data import (
    FranceExternalDataImporter,
    FranceImportError,
    FranceImportOptions,
    GenyFranceExternalDataImporter,
)


class Command(BaseCommand):
    help = "受控导入 France Galop/Geny 外部赛马数据；默认 dry-run，显式 --commit 才写入。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            choices=["france_galop", "geny", "geny_france"],
            default="france_galop",
            help="法国真实抓取来源；France Galop 保留 today 链路，Geny 用于历史日期。",
        )
        parser.add_argument("--race-date", help="按法国赛日导入，例如 2026-06-26")
        parser.add_argument("--partants-urls", help="逗号分隔的 Geny partants URL；用于按 plan-only 输出执行精确批次")
        parser.add_argument("--recent-days", type=int, help="按最近 N 天 Geny 日期范围导入")
        parser.add_argument("--start-date", help="Geny 日期范围开始，例如 2026-04-27")
        parser.add_argument("--end-date", help="Geny 日期范围结束，例如 2026-06-26")
        parser.add_argument("--limit-races", type=int, dest="limit_races", help="本次真实网络抓取最多解析的比赛数")
        parser.add_argument("--limit-horses", type=int, dest="limit_horses", help="Geny 本次最多补抓的马匹 profile 数")
        parser.add_argument("--skip-races", type=int, default=0, dest="skip_races", help="Geny 日期范围内跳过前 N 场，用于拆批续跑")
        parser.add_argument("--plan-only", action="store_true", help="只生成 Geny race 批次计划，不抓 partants/results、不写表")
        parser.add_argument("--batch-size", type=int, default=20, dest="batch_size", help="plan-only 输出每批 race 数")
        parser.add_argument("--allow-network", action="store_true", help="允许真实网络请求；默认关闭")
        parser.add_argument("--commit", action="store_true", help="将抓取结果写入 External* 表；默认只 dry-run")
        parser.add_argument("--max-races", type=int, help="单次最大比赛数")
        parser.add_argument("--max-horses", type=int, help="单次最大马匹数")
        parser.add_argument("--max-requests", type=int, help="单次最大外部请求数")

    def handle(self, *args, **options):
        source = options["source"]
        use_geny = source in {"geny", "geny_france"}
        if use_geny:
            range_modes = [bool(options["partants_urls"]), bool(options["race_date"]), bool(options["recent_days"]), bool(options["start_date"])]
            if sum(range_modes) != 1:
                raise CommandError("Geny 必须且只能指定 --partants-urls、--race-date、--recent-days 或 --start-date/--end-date 其中一种。")
            if options["start_date"] and not options["end_date"]:
                raise CommandError("--start-date 和 --end-date 必须同时指定。")
        elif options["partants_urls"]:
            raise CommandError("--partants-urls 当前仅支持 Geny 来源。")
        elif not options["race_date"]:
            raise CommandError("France Galop 来源必须指定 --race-date。")
        if options["plan_only"] and not use_geny:
            raise CommandError("--plan-only 当前仅支持 Geny 来源。")
        if options["plan_only"] and options["commit"]:
            raise CommandError("--plan-only 不能与 --commit 同时使用。")
        if options["plan_only"] and options["partants_urls"]:
            raise CommandError("--partants-urls 不能与 --plan-only 同时使用。")
        if options["plan_only"] and not options["allow_network"]:
            raise CommandError("--plan-only 必须与 --allow-network 一起使用。")
        import_options = FranceImportOptions.from_settings(
            dry_run=not options["commit"],
            allow_network=options["allow_network"],
            max_races=options["max_races"],
            max_horses=options["max_horses"],
            max_requests=options["max_requests"],
        )
        importer_class = GenyFranceExternalDataImporter if use_geny else FranceExternalDataImporter
        importer = importer_class(import_options)
        try:
            if use_geny and options["partants_urls"]:
                result = importer.import_partants_urls(
                    [item.strip() for item in options["partants_urls"].split(",") if item.strip()],
                    limit_horses=options.get("limit_horses"),
                )
            elif use_geny and options["plan_only"] and options["recent_days"]:
                result = importer.plan_recent_days(
                    options["recent_days"],
                    end_date=options.get("end_date"),
                    batch_size=options["batch_size"],
                )
            elif use_geny and options["plan_only"] and options["start_date"]:
                result = importer.plan_date_range(
                    options["start_date"],
                    options["end_date"],
                    batch_size=options["batch_size"],
                )
            elif use_geny and options["plan_only"]:
                result = importer.plan_date_range(
                    options["race_date"],
                    options["race_date"],
                    batch_size=options["batch_size"],
                )
            elif use_geny and options["recent_days"]:
                result = importer.import_recent_days(
                    options["recent_days"],
                    end_date=options.get("end_date"),
                    limit_races=options.get("limit_races"),
                    skip_races=options.get("skip_races") or 0,
                    limit_horses=options.get("limit_horses"),
                )
            elif use_geny and options["start_date"]:
                result = importer.import_date_range(
                    options["start_date"],
                    options["end_date"],
                    limit_races=options.get("limit_races"),
                    skip_races=options.get("skip_races") or 0,
                    limit_horses=options.get("limit_horses"),
                )
            elif use_geny:
                result = importer.import_race_date(
                    options["race_date"],
                    limit_races=options.get("limit_races"),
                    skip_races=options.get("skip_races") or 0,
                    limit_horses=options.get("limit_horses"),
                )
            else:
                result = importer.import_race_date(options["race_date"], limit_races=options.get("limit_races"))
        except FranceImportError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))

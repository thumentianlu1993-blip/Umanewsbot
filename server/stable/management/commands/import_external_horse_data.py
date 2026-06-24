from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.models import ExternalDataImportRun
from stable.services.external_horse_data import (
    ExternalHorseDataError,
    ExternalHorseDataImporter,
    ImportOptions,
    ensure_keibascraper_available,
)


class Command(BaseCommand):
    help = "受控导入 netkeiba 外部赛马数据，默认仅在显式开启网络开关后执行真实请求。"

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, help="指定导入年份")
        parser.add_argument("--month", type=int, help="指定导入月份")
        parser.add_argument("--race-id", help="指定单场 race_id")
        parser.add_argument("--horse-id", help="指定单匹 horse_id")
        parser.add_argument("--horse-name", default="", help="单马补抓时可选的可信日文马名")
        parser.add_argument("--dry-run", action="store_true", help="只输出计划和估算，不写入外部数据表")
        parser.add_argument("--allow-network", action="store_true", help="允许本次命令发起外部网络请求")
        parser.add_argument("--max-races", type=int, help="单次最大比赛数")
        parser.add_argument("--max-horses", type=int, help="单次最大马匹详情数")
        parser.add_argument("--fetch-odds", action="store_true", help="抓取赔率数据")
        parser.add_argument("--no-fetch-horse-detail", action="store_true", help="只抓比赛/出走/赛果，不补抓马匹详情")
        parser.add_argument("--lookup-name", help="查询本地马名索引，不发起外部请求")
        parser.add_argument("--stats-run-id", type=int, help="查看指定导入运行统计")
        parser.add_argument("--check-dependency", action="store_true", help="检查 keibascraper 是否可 import")

    def handle(self, *args, **options):
        if options["check_dependency"]:
            version = ensure_keibascraper_available()
            self.stdout.write(self.style.SUCCESS(f"keibascraper import ok: {version}"))
            return

        importer = ExternalHorseDataImporter(
            ImportOptions.from_settings(
                dry_run=options["dry_run"],
                allow_network=options["allow_network"],
                max_races=options["max_races"],
                max_horses=options["max_horses"],
                fetch_odds=options["fetch_odds"] or None,
                fetch_horse_detail=False if options["no_fetch_horse_detail"] else None,
            )
        )

        if options["lookup_name"]:
            aliases = importer.lookup_alias(options["lookup_name"])
            payload = [
                {
                    "external_horse_id": alias.external_horse_id,
                    "name_ja": alias.name_ja,
                    "source": alias.source,
                    "confidence": alias.confidence,
                    "last_seen_at": alias.last_seen_at.isoformat(),
                }
                for alias in aliases
            ]
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        if options["stats_run_id"]:
            run = ExternalDataImportRun.objects.get(pk=options["stats_run_id"])
            payload = {
                "run_id": run.id,
                "source": run.source,
                "target_type": run.target_type,
                "status": run.status,
                "success_count": run.success_count,
                "skipped_count": run.skipped_count,
                "failure_count": run.failure_count,
                "coverage_stats": run.coverage_stats,
                "error_count": run.errors.count(),
            }
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        try:
            result = self._run_import(importer, options)
        except ExternalHorseDataError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))

    def _run_import(self, importer: ExternalHorseDataImporter, options: dict) -> dict:
        if options["race_id"]:
            return importer.import_race(options["race_id"])
        if options["horse_id"]:
            return importer.import_horse(options["horse_id"], horse_name=options["horse_name"])
        if options["year"] or options["month"]:
            if not options["year"] or not options["month"]:
                raise CommandError("--year 和 --month 必须同时提供")
            return importer.import_month(options["year"], options["month"])
        return importer.import_default()

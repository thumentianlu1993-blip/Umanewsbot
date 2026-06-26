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
        parser.add_argument("--horse-id", help="按 HKJC 单匹 horse_id 导入")
        parser.add_argument("--payload-file", default="", help="隔离样本 JSON 文件；可用于 dry-run 或提交")
        parser.add_argument("--commit", action="store_true", help="提交写入 External* 缓存表；默认只 dry-run")
        parser.add_argument("--allow-network", action="store_true", help="预留真实网络请求开关；默认关闭")
        parser.add_argument("--max-races", type=int, help="单次最大比赛数配置记录")
        parser.add_argument("--max-horses", type=int, help="单次最大马匹数配置记录")
        parser.add_argument("--lookup-name", help="查询本地 HKJC 马名索引，不发起外部请求")
        parser.add_argument("--stats-run-id", type=int, help="查看指定 HKJC 导入运行统计")

    def handle(self, *args, **options):
        importer = HKJCExternalDataImporter(
            HKJCImportOptions.from_settings(
                dry_run=not options["commit"],
                allow_network=options["allow_network"],
                max_races=options["max_races"],
                max_horses=options["max_horses"],
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

        target_count = sum(1 for key in ("race_date", "race_id", "horse_id") if options.get(key))
        if target_count != 1:
            raise CommandError("必须且只能指定 --race-date、--race-id 或 --horse-id 之一。")
        try:
            if options["race_date"]:
                result = importer.import_race_date(options["race_date"], payload_file=options["payload_file"])
            elif options["race_id"]:
                result = importer.import_race(options["race_id"], payload_file=options["payload_file"])
            else:
                result = importer.import_horse(options["horse_id"], payload_file=options["payload_file"])
        except HKJCImportError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))

import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from stable.services.news_evaluation import inventory_files, validate_gold, evaluation_package
from stable.management.commands.report_news_quality import read_artifact


class Command(BaseCommand):
    help = "验证真实缓存样例/gold 清单并生成小评估预算包，不执行真实模型。"

    def add_arguments(self, parser):
        parser.add_argument("--root", required=True)
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            manifest = read_artifact(options["manifest"], options["manifest_sha256"])
            inventory = inventory_files(options["root"], manifest.get("inputs", []))
            result = {"inventory": inventory, "gold": validate_gold(manifest.get("gold", []), root=options["root"]),
                "evaluation": evaluation_package([row for row in inventory["files"] if row.get("evaluation_sample")], manifest.get("model_candidates", []))}
            with Path(options["output"]).open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write("离线评估包已生成；真实模型调用数为0。")

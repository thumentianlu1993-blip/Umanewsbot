from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.term_admin import commit_term_import, preview_term_import


DEFAULT_TERMS_FILE = Path(__file__).resolve().parents[2] / "data" / "terms_seed.csv"


class Command(BaseCommand):
    help = "导入正式术语 CSV，支持预检和幂等更新。"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", nargs="?", default=str(DEFAULT_TERMS_FILE), help="术语 CSV 文件路径。")
        parser.add_argument("--dry-run", action="store_true", help="只执行预检，不写入数据库。")
        parser.add_argument("--mode", choices=["create", "upsert"], default="upsert", help="导入模式。")

    def handle(self, *args, **options):
        csv_path = Path(options["csv_path"]).expanduser()
        if not csv_path.exists():
            raise CommandError(f"术语 CSV 文件不存在：{csv_path}")

        preview = preview_term_import(csv_text=csv_path.read_text(encoding="utf-8-sig"), import_mode=options["mode"])
        summary = preview["summary"]
        self.stdout.write(
            "预检完成："
            f"总计 {summary['total']} 条，"
            f"新增 {summary['create_count']} 条，"
            f"更新 {summary['update_count']} 条，"
            f"错误 {summary['error_count']} 条。"
        )
        if summary["error_count"]:
            for row in preview["rows"]:
                if row["errors"]:
                    self.stdout.write(f"第 {row['line_no']} 行：{'；'.join(row['errors'])}")
            raise CommandError("术语导入预检失败。")

        if options["dry_run"]:
            self.stdout.write("dry-run 模式，不写入数据库。")
            return

        result = commit_term_import(preview["rows"], preview["import_mode"])
        self.stdout.write(
            "导入完成："
            f"总计 {result['total']} 条，"
            f"新增 {result['success_count']} 条，"
            f"更新 {result['update_count']} 条，"
            f"跳过 {result['skipped_count']} 条。"
        )

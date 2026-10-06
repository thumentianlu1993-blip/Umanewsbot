"""H03 prepare-only 可导入无写 stub；等待真实业务 RED 后实现。"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "从显式可信本地缓存准备未审预览（入口尚未实现，不写数据库）。"
    requires_system_checks = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        for name in ("input-root", "input", "expected-input-sha256",
                     "expected-source-sha256", "output-root", "output-dir"):
            parser.add_argument("--" + name, required=True)

    def handle(self, *args, **options):
        self.stdout.write(json.dumps({
            "status": "not_implemented", "reason": "prepare_not_implemented",
        }))

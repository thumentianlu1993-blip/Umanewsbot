from __future__ import annotations

from django.core.management.base import BaseCommand

from stable.services.horse_profiles import generate_p0_horse_profiles


class Command(BaseCommand):
    help = "从 active horse TermEntry 幂等生成 HorseProfile 草稿；不自动公开。"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, help="最多生成/扫描多少条术语。")

    def handle(self, *args, **options):
        result = generate_p0_horse_profiles(limit=options.get("limit"))
        self.stdout.write(self.style.SUCCESS(f"created={result['created']} existing={result['existing']}"))

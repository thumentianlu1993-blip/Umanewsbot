from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.attribution_gold_review import build_gold_review_package, stratified_gold_candidate_pool


class Command(BaseCommand):
    help = "只读抽取生产文章并生成多地区归属 Gold Set 双人盲标包。"

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--gold-version", required=True)
        parser.add_argument("--per-region", type=int, default=50)
        parser.add_argument("--cross-candidate-target", type=int, default=75)
        parser.add_argument("--candidate-pool-per-source", type=int, default=100)
        parser.add_argument("--seed", default="20260713")

    def handle(self, *args, **options):
        try:
            report = build_gold_review_package(
                output_dir=Path(options["output_dir"]),
                version=options["gold_version"],
                queryset=stratified_gold_candidate_pool(per_source=options["candidate_pool_per_source"]),
                per_region=options["per_region"],
                cross_candidate_target=options["cross_candidate_target"],
                seed=options["seed"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(asdict(report), ensure_ascii=False, indent=2))

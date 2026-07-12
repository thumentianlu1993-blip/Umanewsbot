from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.adapters.international import FranceGalopEnglishNewsAdapter
from stable.models import NewsArticle, SourceSite
from stable.services.published_time_repair import create_time_repair_dry_run, commit_time_repair


def fetch_verified_evidence(article: NewsArticle) -> dict:
    detail = FranceGalopEnglishNewsAdapter().fetch_detail(article.source_url)
    return {
        "published_at": detail.published_at,
        "raw": (detail.metadata.get("published_at_evidence") or {}).get("raw", ""),
        "timezone": "Europe/Paris",
        "verified": bool(detail.published_at),
    }


class Command(BaseCommand):
    help = "以 dry-run/manifest 方式修复 France Galop 近期文章的可信发布时间。"

    def add_arguments(self, parser):
        parser.add_argument("--article-id", action="append", type=int)
        parser.add_argument("--hours", type=int, default=72)
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--run-id", type=int)
        parser.add_argument("--manifest-sha256")

    def handle(self, *args, **options):
        if options["dry_run"] == options["commit"]:
            raise CommandError("必须且只能指定 --dry-run 或 --commit")
        if options["commit"]:
            if not options.get("run_id") or not options.get("manifest_sha256"):
                raise CommandError("commit 必须提供 --run-id 和 --manifest-sha256")
            try:
                result = commit_time_repair(
                    run_id=options["run_id"],
                    manifest_sha256=options["manifest_sha256"],
                )
            except Exception as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(json.dumps(result.__dict__, ensure_ascii=False, default=str))
            return

        queryset = NewsArticle.objects.filter(
            source_site=SourceSite.FRANCE_GALOP_NEWS,
            first_seen_at__gte=timezone.now() - timedelta(hours=max(1, options["hours"])),
        ).order_by("id")
        if options.get("article_id"):
            queryset = queryset.filter(id__in=options["article_id"])
        articles = list(queryset[: max(1, options["limit"])])
        evidence = {}
        for article in articles:
            try:
                evidence[article.id] = fetch_verified_evidence(article)
            except Exception as exc:
                evidence[article.id] = {
                    "published_at": None,
                    "raw": "",
                    "verified": False,
                    "error": f"fetch_failed: {str(exc)[:500]}",
                }
        run = create_time_repair_dry_run(articles, evidence_by_article=evidence)
        self.stdout.write(
            json.dumps(
                {
                    "run_id": run.id,
                    "manifest_sha256": run.manifest_sha256,
                    "candidate_count": len(run.candidate_payload),
                    "outcomes": run.candidate_payload,
                },
                ensure_ascii=False,
                default=str,
            )
        )

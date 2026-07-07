from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from stable.models import HorseProfile, NewsArticle
from stable.services.horse_profiles import scan_article_horse_links


class Command(BaseCommand):
    help = "扫描已发布文章与已发布马匹的关联；默认 dry-run，显式 --commit 才写入。"

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="写入 ArticleHorseLink。")
        parser.add_argument("--dry-run", action="store_true", help="只输出结果，不写入。")
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--article-id", type=int)
        parser.add_argument("--article-from-id", type=int)
        parser.add_argument("--article-to-id", type=int)
        parser.add_argument("--horse-profile-id", type=int)

    def handle(self, *args, **options):
        if options["commit"] and options["dry_run"]:
            raise CommandError("--commit 与 --dry-run 不能同时使用")
        commit = bool(options["commit"])
        article = None
        profile = None
        if options.get("article_id") and (options.get("article_from_id") or options.get("article_to_id")):
            raise CommandError("--article-id 不能与文章范围参数同时使用")
        if options.get("article_id"):
            article = NewsArticle.objects.filter(pk=options["article_id"]).first()
            if article is None:
                raise CommandError(f"article not found: {options['article_id']}")
        if options.get("horse_profile_id"):
            profile = HorseProfile.objects.filter(pk=options["horse_profile_id"]).first()
            if profile is None:
                raise CommandError(f"horse profile not found: {options['horse_profile_id']}")
        if options.get("article_from_id") or options.get("article_to_id"):
            queryset = NewsArticle.objects.all().order_by("id")
            if options.get("article_from_id"):
                queryset = queryset.filter(id__gte=options["article_from_id"])
            if options.get("article_to_id"):
                queryset = queryset.filter(id__lte=options["article_to_id"])
            totals = {"created": 0, "updated": 0, "candidate": 0, "skipped_removed": 0, "skipped_manual": 0}
            article_ids = list(queryset.values_list("id", flat=True)[: options["limit"]])
            for article_id in article_ids:
                result = scan_article_horse_links(
                    article=NewsArticle.objects.get(pk=article_id),
                    profile=profile,
                    limit=1,
                    commit=commit,
                )
                for key in totals:
                    totals[key] += int(result.get(key, 0))
            mode = "commit" if commit else "dry-run"
            self.stdout.write(self.style.SUCCESS(f"{mode}: articles={len(article_ids)} {totals}"))
            return
        result = scan_article_horse_links(
            article=article,
            profile=profile,
            limit=options["limit"],
            commit=commit,
        )
        mode = "commit" if commit else "dry-run"
        self.stdout.write(self.style.SUCCESS(f"{mode}: {result}"))

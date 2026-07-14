from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from stable.models import ArticleTranslationStatus, NewsArticle, WorkflowStatus
from stable.services.queueing import dispatch_task
from stable.tasks import batch_translate_articles_task, translate_article_task


class Command(BaseCommand):
    help = "Queue or run translation jobs for news articles."

    def add_arguments(self, parser):
        parser.add_argument("--article-id", dest="article_ids", action="append", type=int, help="Translate a specific article ID.")
        parser.add_argument("--pending", action="store_true", help="Translate pending articles.")
        parser.add_argument("--failed", action="store_true", help="Translate failed articles again.")
        parser.add_argument("--limit", type=int, default=20, help="Maximum number of articles to process.")
        parser.add_argument("--sync", action="store_true", help="Run translations immediately in the current process.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite manually edited translation fields for explicitly selected articles; requires --sync.",
        )

    def handle(self, *args, **options):
        limit = max(1, options["limit"])
        article_ids = options.get("article_ids") or []
        force = bool(options.get("force"))

        if force and not article_ids:
            raise CommandError("--force 必须配合显式 --article-id")
        if force and not options["sync"]:
            raise CommandError("--force 必须配合 --sync，禁止异步批量强制覆盖")

        if article_ids:
            queryset = NewsArticle.objects.filter(pk__in=article_ids).order_by("id")
        else:
            include_pending = options["pending"] or not options["failed"]
            include_failed = options["failed"] or not options["pending"]
            statuses: list[str] = []
            if include_pending:
                statuses.append(ArticleTranslationStatus.PENDING)
            if include_failed:
                statuses.append(ArticleTranslationStatus.FAILED)
            queryset = (
                NewsArticle.objects.exclude(workflow_status__in=[WorkflowStatus.PUBLISHED, WorkflowStatus.WITHDRAWN])
                .filter(translation_status__in=statuses)
                .order_by("-published_at", "-id")
            )

        selected_ids = list(queryset.values_list("id", flat=True)[:limit])
        if not selected_ids:
            raise CommandError("No articles matched the translation criteria.")
        if force:
            missing_ids = sorted(set(article_ids) - set(selected_ids))
            if missing_ids:
                raise CommandError(f"强制重译未完整匹配显式文章 ID: {missing_ids}")

        if options["sync"]:
            translated = 0
            failed = 0
            for article_id in selected_ids:
                try:
                    result = translate_article_task.run(article_id, force=force)
                    if force and not result.get("translated"):
                        failed += 1
                        self.stderr.write(
                            self.style.WARNING(
                                f"Article {article_id} not translated: {result.get('reason', 'unknown')}"
                            )
                        )
                        continue
                    translated += 1
                except Exception as exc:
                    failed += 1
                    self.stderr.write(self.style.WARNING(f"Article {article_id} failed: {exc}"))
            self.stdout.write(self.style.SUCCESS(f"Processed {len(selected_ids)} article(s): {translated} succeeded, {failed} failed."))
            if force and failed:
                raise CommandError(f"强制重译失败：{failed}/{len(selected_ids)} 篇未完成")
            return

        dispatch_task(batch_translate_articles_task, article_ids=selected_ids, limit=limit)
        self.stdout.write(self.style.SUCCESS(f"Queued translation for {len(selected_ids)} article(s)."))

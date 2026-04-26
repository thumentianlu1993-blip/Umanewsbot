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

    def handle(self, *args, **options):
        limit = max(1, options["limit"])
        article_ids = options.get("article_ids") or []

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

        if options["sync"]:
            translated = 0
            failed = 0
            for article_id in selected_ids:
                try:
                    translate_article_task.run(article_id)
                    translated += 1
                except Exception as exc:
                    failed += 1
                    self.stderr.write(self.style.WARNING(f"Article {article_id} failed: {exc}"))
            self.stdout.write(self.style.SUCCESS(f"Processed {len(selected_ids)} article(s): {translated} succeeded, {failed} failed."))
            return

        dispatch_task(batch_translate_articles_task, article_ids=selected_ids, limit=limit)
        self.stdout.write(self.style.SUCCESS(f"Queued translation for {len(selected_ids)} article(s)."))

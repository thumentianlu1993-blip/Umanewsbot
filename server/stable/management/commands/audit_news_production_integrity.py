from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from stable.models import CrawlJob, NewsSource, TaskStatus
from stable.services.news_production_integrity import (
    production_index_snapshot,
    source_health_snapshot,
    task_execution_index_error_snapshot,
)


class Command(BaseCommand):
    help = "只读审计新闻主表索引、滚动来源失败和超时 CrawlJob。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--index-name",
            default=str(
                getattr(
                    settings,
                    "NEWS_PRODUCTION_INDEX_NAME",
                    "stable_newsarticle_public_slug_46694cb6",
                )
            ),
        )
        parser.add_argument("--hours", type=int, default=24)

    def handle(self, *args, **options):
        now = timezone.now()
        hours = max(1, min(int(options["hours"]), 168))
        stale_minutes = max(1, int(getattr(settings, "CRAWL_JOB_STALE_MINUTES", 60)))
        source_rows = []
        for source in NewsSource.objects.filter(deleted_at__isnull=True).order_by("id"):
            health = source_health_snapshot(
                source,
                now=now,
                stale_minutes=stale_minutes,
                short_window_hours=getattr(settings, "NEWS_SOURCE_HEALTH_SHORT_WINDOW_HOURS", 2),
                long_window_hours=getattr(settings, "NEWS_SOURCE_HEALTH_LONG_WINDOW_HOURS", 24),
            )
            if (
                health["current_running_count"]
                or health["failures_24h"]
                or health["index_error"]["active"]
            ):
                source_rows.append(
                    {
                        "source_id": source.id,
                        "source_name": source.name,
                        **health,
                    }
                )
        payload = {
            "generated_at": now.isoformat(),
            "index": production_index_snapshot(options["index_name"]),
            "task_execution_index_error": task_execution_index_error_snapshot(
                now=now,
                window_hours=getattr(settings, "NEWS_SOURCE_HEALTH_SHORT_WINDOW_HOURS", 2),
            ),
            "crawl_jobs": {
                "window_hours": hours,
                "failed": CrawlJob.objects.filter(
                    status=TaskStatus.FAILED,
                    started_at__gte=now - timedelta(hours=hours),
                ).count(),
                "stale_started": CrawlJob.objects.filter(
                    status=TaskStatus.STARTED,
                    started_at__lte=now - timedelta(minutes=stale_minutes),
                ).count(),
            },
            "sources": source_rows,
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))

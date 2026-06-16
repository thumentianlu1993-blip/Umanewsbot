from __future__ import annotations

import json
from datetime import datetime, time

from django.core.management.base import BaseCommand
from django.utils import timezone

from stable.models import NewsArticle, WorkflowStatus
from stable.services.automation import race_priority, score_article_for_automation
from stable.services.terms import resolve_terms, serialize_terms


class Command(BaseCommand):
    help = "验收执行日 0:00 后进入候选新闻池的文章。"

    def add_arguments(self, parser):
        parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式。")
        parser.add_argument("--since", help="起始时间，格式为 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS。")

    def _since(self, raw: str | None):
        current_tz = timezone.get_current_timezone()
        if raw:
            if "T" in raw:
                parsed = datetime.fromisoformat(raw)
            else:
                parsed = datetime.combine(datetime.fromisoformat(raw).date(), time.min)
            if timezone.is_naive(parsed):
                return timezone.make_aware(parsed, current_tz)
            return parsed
        return timezone.make_aware(datetime.combine(timezone.localdate(), time.min), current_tz)

    def handle(self, *args, **options):
        since = self._since(options.get("since"))
        queryset = (
            NewsArticle.objects.filter(
                workflow_status__in=[WorkflowStatus.PENDING_EDIT, WorkflowStatus.PENDING_REVIEW],
                first_seen_at__gte=since,
            )
            .prefetch_related("term_candidate_evidence")
            .order_by("first_seen_at", "id")
        )
        articles = []
        for article in queryset:
            source_text = "\n".join([article.title_ja or "", article.body_ja_normalized or article.body_ja_raw or ""])
            terms = serialize_terms(resolve_terms(source_text, limit=50))
            race_signal = race_priority(article)
            decision = score_article_for_automation(article)
            articles.append(
                {
                    "article_id": article.id,
                    "title_ja": article.title_ja,
                    "first_seen_at": article.first_seen_at.isoformat(),
                    "workflow_status": article.workflow_status,
                    "term_count": len(terms),
                    "terms": terms,
                    "term_candidate_count": article.term_candidate_evidence.count(),
                    "race_grade": race_signal.get("grade", ""),
                    "race_priority": race_signal.get("priority", ""),
                    "race_grade_source": race_signal.get("source", ""),
                    "score_total": decision.score_total,
                    "review_mode": decision.review_mode,
                    "automation_status": decision.automation_status,
                }
            )

        payload = {
            "since": since.isoformat(),
            "candidate_news_count": len(articles),
            "articles": articles,
        }
        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self.stdout.write(f"候选新闻池验收：自 {payload['since']} 起共 {payload['candidate_news_count']} 篇")
        for item in articles:
            self.stdout.write(
                f"- #{item['article_id']} {item['title_ja']} | "
                f"术语 {item['term_count']} | 候选证据 {item['term_candidate_count']} | "
                f"赛事 {item['race_grade'] or '-'} / {item['race_priority']} | 分数 {item['score_total']}"
            )

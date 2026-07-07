from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.models import AutomationStatus, NewsArticle, RacingRegion, WorkflowStatus
from stable.services.validation import apply_validation_outcome, validate_rewrite


TERMINAL_WORKFLOW_STATUSES = {
    WorkflowStatus.PUBLISHED,
    WorkflowStatus.REJECTED,
    WorkflowStatus.WITHDRAWN,
    WorkflowStatus.DUPLICATE,
    WorkflowStatus.ARCHIVED,
    WorkflowStatus.IGNORED,
}


def _has_core_term_blocker(article: NewsArticle) -> bool:
    return any(
        issue.get("code") == "core_term_missing" and issue.get("severity") == "blocker"
        for issue in (article.gate_issues or [])
    )


def _source_key(article: NewsArticle) -> str:
    return f"{article.source_site}:{article.source_mode}"


class Command(BaseCommand):
    help = "受控重处理近期因 core_term_missing 被挡住的文章。"

    def add_arguments(self, parser):
        parser.add_argument("--region", choices=[choice[0] for choice in RacingRegion.choices], required=True)
        parser.add_argument("--source", action="append", help="限制来源 key（source_site:source_mode）或 NewsSource id，可重复。")
        parser.add_argument("--hours", type=int, help="回看小时数；默认使用 MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS。")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--json", action="store_true", help="以 JSON 输出。")

    def handle(self, *args, **options):
        if options["dry_run"] == options["commit"]:
            raise CommandError("必须且只能指定 --dry-run 或 --commit")

        now = timezone.now()
        lookback_hours = max(
            1,
            int(
                options.get("hours")
                or getattr(settings, "MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS", 3)
            ),
        )
        window_start = now - timedelta(hours=lookback_hours)
        region = options["region"]
        source_filters = {item.strip() for item in (options.get("source") or []) if item.strip()}
        queryset = (
            NewsArticle.objects.filter(
                racing_region=region,
                automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            )
            .order_by("first_seen_at", "id")
        )

        candidates: list[NewsArticle] = []
        skipped = {
            "no_core_term_blocker": [],
            "outside_lookback": [],
            "manual_terminal_state": [],
            "source_not_selected": [],
        }
        for article in queryset:
            if not _has_core_term_blocker(article):
                skipped["no_core_term_blocker"].append(article.id)
                continue
            if article.workflow_status in TERMINAL_WORKFLOW_STATUSES:
                skipped["manual_terminal_state"].append(article.id)
                continue
            if article.first_seen_at < window_start:
                skipped["outside_lookback"].append(article.id)
                continue
            if source_filters and _source_key(article) not in source_filters and str(article.source_config_id or "") not in source_filters:
                skipped["source_not_selected"].append(article.id)
                continue
            candidates.append(article)

        revalidated_to_publish_ready_ids: list[int] = []
        still_blocked_ids: list[int] = []
        outcomes: list[dict] = []
        for article in candidates:
            outcome = validate_rewrite(article)
            outcomes.append(
                {
                    "article_id": article.id,
                    "passed": outcome.passed,
                    "reason": outcome.reason,
                    "blockers": [issue for issue in outcome.issues if issue.get("severity") == "blocker"],
                    "warnings": [issue for issue in outcome.issues if issue.get("severity") == "warning"],
                }
            )
            if not outcome.passed:
                still_blocked_ids.append(article.id)
                if options["commit"]:
                    apply_validation_outcome(article, outcome)
                continue
            revalidated_to_publish_ready_ids.append(article.id)
            if options["commit"]:
                apply_validation_outcome(article, outcome)
                NewsArticle.objects.filter(pk=article.pk).update(ranked_revived_at=now, updated_at=now)

        payload = {
            "dry_run": bool(options["dry_run"]),
            "commit": bool(options["commit"]),
            "region": region,
            "lookback_hours": lookback_hours,
            "window_start": window_start.isoformat(),
            "candidate_ids": [article.id for article in candidates],
            "revalidated_to_publish_ready_ids": revalidated_to_publish_ready_ids,
            "still_blocked_ids": still_blocked_ids,
            "skipped": skipped,
            "outcomes": outcomes,
        }

        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return

        self.stdout.write(
            f"region={region} candidates={len(candidates)} "
            f"publish_ready={len(revalidated_to_publish_ready_ids)} still_blocked={len(still_blocked_ids)}"
        )

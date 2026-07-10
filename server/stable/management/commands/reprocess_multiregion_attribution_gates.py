from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.models import AutomationStatus, NewsArticle, RacingRegion, WorkflowStatus
from stable.services.news_attribution import apply_article_attribution, infer_article_attribution
from stable.services.validation import apply_validation_outcome, validate_rewrite


TERMINAL_WORKFLOW_STATUSES = {
    WorkflowStatus.PUBLISHED,
    WorkflowStatus.REJECTED,
    WorkflowStatus.WITHDRAWN,
    WorkflowStatus.DUPLICATE,
    WorkflowStatus.ARCHIVED,
    WorkflowStatus.IGNORED,
}
REPROCESS_ISSUE_CODES = {"core_term_missing", "term_region_excluded"}


def _has_reprocessable_gate(article: NewsArticle) -> bool:
    return any(
        issue.get("code") in REPROCESS_ISSUE_CODES
        for issue in (article.gate_issues or [])
    )


class Command(BaseCommand):
    help = "重跑多地区归属并重新校验英文术语门禁；commit 只恢复候选，不直接发布。"

    def add_arguments(self, parser):
        parser.add_argument("--region", action="append", choices=[choice[0] for choice in RacingRegion.choices])
        parser.add_argument("--hours", type=int, help="回看小时数；默认使用 MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS。")
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--json", action="store_true", help="以 JSON 输出。")

    def handle(self, *args, **options):
        if options["dry_run"] == options["commit"]:
            raise CommandError("必须且只能指定 --dry-run 或 --commit")

        now = timezone.now()
        lookback_hours = max(
            1,
            int(options.get("hours") or getattr(settings, "MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS", 3)),
        )
        limit = max(1, int(options["limit"]))
        window_start = now - timedelta(hours=lookback_hours)
        regions = {region for region in (options.get("region") or []) if region}
        queryset = (
            NewsArticle.objects.filter(
                first_seen_at__gte=window_start,
                automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            )
            .exclude(workflow_status__in=TERMINAL_WORKFLOW_STATUSES)
            .order_by("first_seen_at", "id")
        )
        if regions:
            queryset = queryset.filter(racing_region__in=regions)

        candidates: list[NewsArticle] = []
        skipped = {"no_reprocessable_gate": []}
        scanned_count = 0
        has_more_candidates = False
        for article in queryset.iterator(chunk_size=200):
            scanned_count += 1
            if not _has_reprocessable_gate(article):
                skipped["no_reprocessable_gate"].append(article.id)
                continue
            candidates.append(article)
            if len(candidates) > limit:
                candidates.pop()
                has_more_candidates = True
                break

        restored_ids: list[int] = []
        still_blocked_ids: list[int] = []
        outcomes: list[dict] = []
        for article in candidates:
            old_regions = {
                "primary": article.racing_region,
                "related": list(article.related_region_links.values_list("region", flat=True)),
            }
            attribution = infer_article_attribution(article)
            attribution_applied = bool(
                getattr(settings, "MULTIREGION_ATTRIBUTION_ENABLED", True)
                and not article.attribution_locked
            )
            effective_regions = {
                "primary": attribution.primary_region if attribution_applied else old_regions["primary"],
                "related": attribution.related_regions if attribution_applied else old_regions["related"],
            }
            if options["commit"]:
                apply_article_attribution(article, force=False, save=True)
                outcome = validate_rewrite(article)
                apply_validation_outcome(article, outcome)
                if outcome.passed:
                    NewsArticle.objects.filter(pk=article.pk).update(ranked_revived_at=now, updated_at=now)
                    restored_ids.append(article.id)
                else:
                    still_blocked_ids.append(article.id)
            else:
                article._attribution_region_override = {
                    effective_regions["primary"],
                    *effective_regions["related"],
                }
                outcome = validate_rewrite(article)
                if outcome.passed:
                    restored_ids.append(article.id)
                else:
                    still_blocked_ids.append(article.id)
            outcomes.append(
                {
                    "article_id": article.id,
                    "old_regions": old_regions,
                    "new_regions": effective_regions,
                    "inferred_regions": {
                        "primary": attribution.primary_region,
                        "related": attribution.related_regions,
                    },
                    "attribution_locked": article.attribution_locked,
                    "attribution_applied": attribution_applied,
                    "content_category": attribution.content_category if attribution_applied else article.content_category,
                    "validation_passed": outcome.passed,
                    "validation_reason": outcome.reason,
                    "blockers": [issue for issue in outcome.issues if issue.get("severity") == "blocker"],
                }
            )

        payload = {
            "dry_run": bool(options["dry_run"]),
            "commit": bool(options["commit"]),
            "regions": sorted(regions),
            "lookback_hours": lookback_hours,
            "window_start": window_start.isoformat(),
            "scanned_count": scanned_count,
            "candidate_count": len(candidates),
            "has_more_candidates": has_more_candidates,
            "candidate_ids": [article.id for article in candidates],
            "restored_candidate_ids": restored_ids,
            "still_blocked_ids": still_blocked_ids,
            "skipped": skipped,
            "outcomes": outcomes,
        }
        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return
        self.stdout.write(
            f"candidates={len(candidates)} restored={len(restored_ids)} still_blocked={len(still_blocked_ids)}"
        )

from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.models import AutomationStatus, NewsArticle, RacingRegion, SourceLanguage, TermEntry, TermType, WorkflowStatus
from stable.services.terms import source_terms_by_entry
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


def _empty_summary() -> dict:
    return {
        "candidate_count": 0,
        "revalidated_to_publish_ready_count": 0,
        "still_blocked_count": 0,
        "common_word_downgraded_count": 0,
        "proper_term_blocker_count": 0,
    }


def _english_term_classifications(outcome) -> list[dict]:
    return list((outcome.details or {}).get("english_term_classifications") or [])


def _proper_term_blocker_count(blockers: list[dict]) -> int:
    return sum(
        1
        for issue in blockers
        if issue.get("code") == "core_term_missing"
        and (issue.get("payload") or {}).get("term_semantic_classification") == "proper_noun"
    )


def _proper_term_blockers(blockers: list[dict]) -> list[dict]:
    return [
        issue.get("payload") or {}
        for issue in blockers
        if issue.get("code") == "core_term_missing"
        and (issue.get("payload") or {}).get("term_semantic_classification") == "proper_noun"
    ]


class Command(BaseCommand):
    help = "受控重处理近期因 core_term_missing 被挡住的文章。"

    def add_arguments(self, parser):
        parser.add_argument("--region", choices=[choice[0] for choice in RacingRegion.choices], required=True)
        parser.add_argument("--source", action="append", help="限制来源 key（source_site:source_mode）或 NewsSource id，可重复。")
        parser.add_argument("--hours", type=int, help="回看小时数；默认使用 MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS。")
        parser.add_argument("--limit", type=int, help="最多重校验多少篇候选；默认不额外限制。")
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
        limit = options.get("limit")
        if limit is not None and limit <= 0:
            raise CommandError("--limit 必须大于 0")
        base_queryset = (
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
            "limit_exceeded": [],
        }

        diagnostic_fields = (
            "id",
            "gate_issues",
            "workflow_status",
            "first_seen_at",
            "source_site",
            "source_mode",
            "source_config_id",
        )
        terminal_queryset = base_queryset.filter(workflow_status__in=TERMINAL_WORKFLOW_STATUSES).only(*diagnostic_fields)
        for article in terminal_queryset:
            if not _has_core_term_blocker(article):
                continue
            skipped["manual_terminal_state"].append(article.id)

        outside_queryset = (
            base_queryset.exclude(workflow_status__in=TERMINAL_WORKFLOW_STATUSES)
            .filter(first_seen_at__lt=window_start)
            .only(*diagnostic_fields)
        )
        for article in outside_queryset:
            if not _has_core_term_blocker(article):
                continue
            skipped["outside_lookback"].append(article.id)

        candidate_queryset = (
            base_queryset.exclude(workflow_status__in=TERMINAL_WORKFLOW_STATUSES)
            .filter(first_seen_at__gte=window_start)
        )
        for article in candidate_queryset:
            if not _has_core_term_blocker(article):
                skipped["no_core_term_blocker"].append(article.id)
                continue
            if source_filters and _source_key(article) not in source_filters and str(article.source_config_id or "") not in source_filters:
                skipped["source_not_selected"].append(article.id)
                continue
            if limit is not None and len(candidates) >= limit:
                skipped["limit_exceeded"].append(article.id)
                continue
            candidates.append(article)

        term_entries = list(
            TermEntry.objects.filter(
                is_active=True,
                term_type__in=[TermType.HORSE, TermType.RACE, TermType.JOCKEY, TermType.TRAINER],
            )
        )
        source_languages = sorted({article.source_language or SourceLanguage.JAPANESE for article in candidates})
        terms_by_language = {
            source_language: source_terms_by_entry(term_entries, source_language)
            for source_language in source_languages
        }

        revalidated_to_publish_ready_ids: list[int] = []
        still_blocked_ids: list[int] = []
        outcomes: list[dict] = []
        summary = _empty_summary()
        summary["candidate_count"] = len(candidates)
        summary_by_region = {region: _empty_summary()}
        summary_by_region[region]["candidate_count"] = len(candidates)
        for article in candidates:
            outcome = validate_rewrite(article, term_entries=term_entries, terms_by_language=terms_by_language)
            blockers = [issue for issue in outcome.issues if issue.get("severity") == "blocker"]
            warnings = [issue for issue in outcome.issues if issue.get("severity") == "warning"]
            classifications = _english_term_classifications(outcome)
            common_word_count = sum(1 for item in classifications if item.get("term_semantic_classification") == "common_word")
            proper_blocker_count = _proper_term_blocker_count(blockers)
            summary["common_word_downgraded_count"] += common_word_count
            summary["proper_term_blocker_count"] += proper_blocker_count
            summary_by_region[region]["common_word_downgraded_count"] += common_word_count
            summary_by_region[region]["proper_term_blocker_count"] += proper_blocker_count
            outcomes.append(
                {
                    "article_id": article.id,
                    "passed": outcome.passed,
                    "reason": outcome.reason,
                    "blockers": blockers,
                    "warnings": warnings,
                    "english_term_classifications": classifications,
                    "proper_term_blockers": _proper_term_blockers(blockers),
                }
            )
            if not outcome.passed:
                still_blocked_ids.append(article.id)
                summary["still_blocked_count"] += 1
                summary_by_region[region]["still_blocked_count"] += 1
                continue
            revalidated_to_publish_ready_ids.append(article.id)
            summary["revalidated_to_publish_ready_count"] += 1
            summary_by_region[region]["revalidated_to_publish_ready_count"] += 1
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
            "summary": summary,
            "summary_by_region": summary_by_region,
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

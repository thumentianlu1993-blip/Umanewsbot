from __future__ import annotations

import json
import hashlib
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.models import AutomationStatus, NewsArticle, RacingRegion, WorkflowStatus
from stable.services.news_attribution import infer_article_attribution
from stable.services.validation import validate_rewrite


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
        parser.add_argument("--run-id", type=int)
        parser.add_argument("--manifest-sha256")
        parser.add_argument("--resume", action="store_true")
        parser.add_argument("--gold-labels", help="版本化 gold labels CSV；用于计算并绑定本次 dry-run 质量指标。")

    def handle(self, *args, **options):
        if options["dry_run"] == options["commit"]:
            raise CommandError("必须且只能指定 --dry-run 或 --commit")

        if options["commit"]:
            if not options.get("run_id") or not options.get("manifest_sha256"):
                raise CommandError("commit 必须提供 --run-id 和 --manifest-sha256")
            from stable.services.attribution_runs import commit_attribution_run

            try:
                commit_result = commit_attribution_run(
                    options["run_id"],
                    manifest_sha256=options["manifest_sha256"],
                    resume=options.get("resume", False),
                    expected_gold_version=getattr(settings, "MULTIREGION_ATTRIBUTION_GOLD_VERSION", "pending-review"),
                    expected_gold_snapshot_sha256=(
                        getattr(settings, "MULTIREGION_ATTRIBUTION_GOLD_SNAPSHOT_SHA256", "") or None
                    ),
                )
            except Exception as exc:
                raise CommandError(str(exc)) from exc
            restored_ids = commit_result.restored_ids
            still_blocked_ids = commit_result.still_blocked_ids
            payload = {
                "dry_run": False,
                "commit": True,
                "run_id": options["run_id"],
                "manifest_sha256": options["manifest_sha256"],
                "status": commit_result.status,
                "applied_ids": commit_result.applied_ids,
                "already_completed_ids": commit_result.already_completed_ids,
                "drifted": commit_result.drifted,
                "restored_candidate_ids": restored_ids,
                "still_blocked_ids": still_blocked_ids,
            }
            if options["json"]:
                self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            else:
                self.stdout.write(
                    f"run={options['run_id']} applied={len(commit_result.applied_ids)} restored={len(restored_ids)}"
                )
            return

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
            .prefetch_related("related_region_links")
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
        from stable.services.news_attribution import AttributionBatchContext

        batch_context = AttributionBatchContext.build()
        for article in candidates:
            old_regions = {
                "primary": article.racing_region,
                "related": list(article.related_region_links.values_list("region", flat=True)),
            }
            attribution = infer_article_attribution(article, batch_context=batch_context)
            attribution_applied = not article.attribution_locked
            effective_regions = {
                "primary": attribution.primary_region if attribution_applied else old_regions["primary"],
                "related": attribution.related_regions if attribution_applied else old_regions["related"],
            }
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

        from stable.services.attribution_runs import create_attribution_dry_run

        gold_metrics = {}
        gold_snapshot_sha256 = getattr(settings, "MULTIREGION_ATTRIBUTION_GOLD_SNAPSHOT_SHA256", "")
        if options.get("gold_labels"):
            from stable.services.attribution_quality import evaluate_gold_labels_against_database, load_gold_labels

            gold_path = Path(options["gold_labels"])
            gold_snapshot_sha256 = hashlib.sha256(gold_path.read_bytes()).hexdigest()
            configured_sha = getattr(settings, "MULTIREGION_ATTRIBUTION_GOLD_SNAPSHOT_SHA256", "")
            if configured_sha and configured_sha != gold_snapshot_sha256:
                raise CommandError("gold labels 文件与配置 SHA-256 不匹配")
            gold_metrics = asdict(evaluate_gold_labels_against_database(load_gold_labels(gold_path)))

        run = create_attribution_dry_run(
            candidates,
            rule_version="multiregion-v2",
            term_version="current",
            gold_version=getattr(settings, "MULTIREGION_ATTRIBUTION_GOLD_VERSION", "pending-review"),
            gold_snapshot_sha256=gold_snapshot_sha256,
            metrics=gold_metrics,
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
            "run_id": run.id,
            "manifest_sha256": run.manifest_sha256,
        }
        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return
        self.stdout.write(
            f"candidates={len(candidates)} restored={len(restored_ids)} still_blocked={len(still_blocked_ids)}"
        )

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
from stable.services.news_attribution import ATTRIBUTION_RULE_VERSION


TERMINAL_WORKFLOW_STATUSES = {
    WorkflowStatus.PUBLISHED,
    WorkflowStatus.REJECTED,
    WorkflowStatus.WITHDRAWN,
    WorkflowStatus.DUPLICATE,
    WorkflowStatus.ARCHIVED,
    WorkflowStatus.IGNORED,
}
AUDIT_EXCLUDED_WORKFLOW_STATUSES = TERMINAL_WORKFLOW_STATUSES - {WorkflowStatus.PUBLISHED}
REPROCESS_ISSUE_CODES = {"core_term_missing", "term_region_excluded"}
AUDIT_SCOPE_GATE_CANDIDATES = "gate_candidates"
AUDIT_SCOPE_ALL_ARTICLES = "all_articles"


def _has_reprocessable_gate(article: NewsArticle) -> bool:
    return any(
        issue.get("code") in REPROCESS_ISSUE_CODES
        for issue in (article.gate_issues or [])
    )


class Command(BaseCommand):
    help = "重跑多地区归属；默认范围重校验英文术语门禁，全量范围只回填归属且不直接发布。"

    def add_arguments(self, parser):
        parser.add_argument("--region", action="append", choices=[choice[0] for choice in RacingRegion.choices])
        parser.add_argument("--hours", type=int, help="回看小时数；默认使用 MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS。")
        parser.add_argument("--limit", type=int)
        parser.add_argument(
            "--scope",
            choices=[AUDIT_SCOPE_GATE_CANDIDATES, AUDIT_SCOPE_ALL_ARTICLES],
            default=AUDIT_SCOPE_GATE_CANDIDATES,
            help="gate_candidates 保持原门禁补跑范围；all_articles 审计近期全部有效文章并包含已发布稿。",
        )
        parser.add_argument(
            "--review-sample-per-region",
            type=int,
            default=5,
            help="全量审计时，在必审项之外按当前主地区确定性抽样的篇数。",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--json", action="store_true", help="以 JSON 输出。")
        parser.add_argument("--run-id", type=int)
        parser.add_argument("--manifest-sha256")
        parser.add_argument("--resume", action="store_true")
        parser.add_argument("--gold-labels", help="版本化 gold labels CSV；用于计算并绑定本次 dry-run 质量指标。")
        parser.add_argument(
            "--single-review-gold",
            action="store_true",
            help="允许单审 Gold Set 进入指标分母；仍须满足全部覆盖与质量门槛。",
        )
        parser.add_argument(
            "--include-gate-validation",
            action="store_true",
            help="全量归属审计也逐篇执行发布门禁；耗时较长，默认关闭。",
        )

    def handle(self, *args, **options):
        if options["dry_run"] == options["commit"]:
            raise CommandError("必须且只能指定 --dry-run 或 --commit")
        if options.get("single_review_gold") and not options.get("gold_labels"):
            raise CommandError("--single-review-gold 必须与 --gold-labels 一起使用")

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
        scope = options.get("scope") or AUDIT_SCOPE_GATE_CANDIDATES
        requested_limit = options.get("limit")
        limit = max(1, int(requested_limit)) if requested_limit else (
            200 if scope == AUDIT_SCOPE_GATE_CANDIDATES else None
        )
        review_sample_per_region = max(0, int(options.get("review_sample_per_region") or 0))
        window_start = now - timedelta(hours=lookback_hours)
        regions = {region for region in (options.get("region") or []) if region}
        queryset = NewsArticle.objects.filter(first_seen_at__gte=window_start)
        if scope == AUDIT_SCOPE_GATE_CANDIDATES:
            queryset = queryset.filter(automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED).exclude(
                workflow_status__in=TERMINAL_WORKFLOW_STATUSES
            )
        else:
            queryset = queryset.exclude(workflow_status__in=AUDIT_EXCLUDED_WORKFLOW_STATUSES)
        queryset = queryset.order_by("first_seen_at", "id").prefetch_related("related_region_links")
        if regions:
            queryset = queryset.filter(racing_region__in=regions)

        candidates: list[NewsArticle] = []
        skipped = {"no_reprocessable_gate": []}
        scanned_count = 0
        has_more_candidates = False
        for article in queryset.iterator(chunk_size=200):
            scanned_count += 1
            if scope == AUDIT_SCOPE_GATE_CANDIDATES and not _has_reprocessable_gate(article):
                skipped["no_reprocessable_gate"].append(article.id)
                continue
            candidates.append(article)
            if limit is not None and len(candidates) > limit:
                candidates.pop()
                has_more_candidates = True
                break

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
            gold_metrics = asdict(
                evaluate_gold_labels_against_database(
                    load_gold_labels(gold_path),
                    allow_provisional=options.get("single_review_gold", False),
                )
            )

        run = create_attribution_dry_run(
            candidates,
            rule_version=ATTRIBUTION_RULE_VERSION,
            term_version="current",
            gold_version=getattr(settings, "MULTIREGION_ATTRIBUTION_GOLD_VERSION", "pending-review"),
            gold_snapshot_sha256=gold_snapshot_sha256,
            metrics=gold_metrics,
            selectors={
                "scope": scope,
                "lookback_hours": lookback_hours,
                "window_start": window_start.isoformat(),
                "regions": sorted(regions),
                "scope_complete": not has_more_candidates,
                "review_sample_per_region": review_sample_per_region,
            },
        )
        from stable.services.attribution_runs import build_attribution_review_report

        report = build_attribution_review_report(
            run,
            include_gate_validation=(
                scope == AUDIT_SCOPE_GATE_CANDIDATES or options.get("include_gate_validation", False)
            ),
            review_sample_per_region=review_sample_per_region,
        )
        run.selectors = {
            **(run.selectors or {}),
            "primary_change_ids": report["primary_change_ids"],
            "needs_review_ids": report["needs_review_ids"],
            "locked_skip_ids": report["locked_skip_ids"],
            "review_sample_ids_by_region": report["review_sample_ids_by_region"],
            "review_checklist_ids": report["review_checklist_ids"],
        }
        run.save(update_fields=["selectors", "updated_at"])
        payload = {
            "dry_run": bool(options["dry_run"]),
            "commit": bool(options["commit"]),
            "scanned_count": scanned_count,
            "has_more_candidates": has_more_candidates,
            "skipped": skipped,
            **report,
        }
        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return
        self.stdout.write(
            f"candidates={len(candidates)} restored={len(report['restored_candidate_ids'])} "
            f"still_blocked={len(report['still_blocked_ids'])}"
        )

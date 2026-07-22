from __future__ import annotations

import copy
import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from stable.models import AutomationStatus, NewsArticle, QQPushDelivery, WorkflowStatus
from stable.services.validation import apply_validation_outcome, validate_rewrite


SCHEMA_VERSION = "publish-ready-backlog-v1"
REVIEW_ACTIONS = {"keep_manual", "revalidate_refresh_ready"}


def _canonical_sha(payload: dict) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_sha(payload) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def article_backlog_snapshot(article: NewsArticle) -> dict:
    content = {
        "title": article.effective_title,
        "summary": article.effective_summary,
        "body": article.effective_body,
        "source_url": article.source_url,
    }
    gate = {
        "gate_issues": article.gate_issues or [],
        "published_at_verified": article.published_at_verified,
        "attribution_status": article.attribution_status,
        "translation_status": article.translation_status,
        "review_mode": article.review_mode,
    }
    return {
        "automation_status": article.automation_status,
        "workflow_status": article.workflow_status,
        "publish_ready_at": article.publish_ready_at.isoformat() if article.publish_ready_at else "",
        "published_to_web_at": article.published_to_web_at.isoformat() if article.published_to_web_at else "",
        "updated_at": article.updated_at.isoformat(),
        "content_sha256": _json_sha(content),
        "gate_sha256": _json_sha(gate),
    }


def _manifest_row(article: NewsArticle, *, now) -> dict:
    if article.publish_ready_at:
        age_minutes = int(max(0, (now - article.publish_ready_at).total_seconds()) // 60)
        ready_at = article.publish_ready_at.isoformat()
        age_reason = "older_than_auto_window"
    else:
        age_minutes = None
        ready_at = ""
        age_reason = "legacy_missing_publish_ready_at"
    blocker_count = sum(1 for issue in (article.gate_issues or []) if issue.get("severity") == "blocker")
    return {
        "article_id": article.id,
        "region": article.racing_region,
        "source": f"{article.source_site}:{article.source_mode}",
        "title": article.effective_title,
        "publish_ready_at": ready_at,
        "publish_ready_age_minutes": age_minutes,
        "gate_summary": {
            "issue_count": len(article.gate_issues or []),
            "blocker_count": blocker_count,
        },
        "snapshot": article_backlog_snapshot(article),
        "recommended_action": "keep_manual",
        "recommendation_reason": age_reason,
        "review_action": "keep_manual",
    }


def build_publish_ready_backlog_manifest(*, now=None, limit: int = 100) -> dict:
    now = now or timezone.now()
    limit = max(1, min(int(limit), 1000))
    auto_hours = max(1, int(getattr(settings, "MULTIREGION_PUBLISH_BACKLOG_AUTO_HOURS", 24)))
    cutoff = now - timedelta(hours=auto_hours)
    queryset = (
        NewsArticle.objects.filter(automation_status=AutomationStatus.PUBLISH_READY)
        .filter(_legacy_or_stale_filter(cutoff=cutoff), published_to_web_at__isnull=True)
        .exclude(workflow_status__in=[WorkflowStatus.PUBLISHED, WorkflowStatus.WITHDRAWN, WorkflowStatus.IGNORED])
        .order_by("id")
    )
    articles = list(queryset[: limit + 1])
    rows = [_manifest_row(article, now=now) for article in articles[:limit]]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "policy": {
            "auto_hours": auto_hours,
            "default_action": "keep_manual",
            "apply_directly_publishes": False,
            "apply_creates_qq_delivery": False,
        },
        "review": {"status": "pending", "reviewer": "", "reviewed_at": ""},
        "truncated": len(articles) > limit,
        "articles": rows,
    }
    manifest["manifest_sha256"] = _canonical_sha(manifest)
    return manifest


def _legacy_or_stale_filter(*, cutoff):
    return Q(publish_ready_at__isnull=True) | Q(publish_ready_at__lt=cutoff)


def verify_publish_ready_manifest(manifest: dict, *, expected_sha256: str | None = None) -> str:
    if not isinstance(manifest, dict):
        raise ValueError("manifest 必须是 JSON object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("manifest schema_version 不受支持")
    rows = manifest.get("articles")
    if not isinstance(rows, list):
        raise ValueError("manifest articles 必须是 JSON array")
    article_ids = [str(row.get("article_id")) for row in rows if isinstance(row, dict)]
    if len(article_ids) != len(rows) or len(set(article_ids)) != len(article_ids):
        raise ValueError("manifest articles 必须包含不重复的 article_id")
    actual = _canonical_sha(manifest)
    embedded = str(manifest.get("manifest_sha256") or "").lower()
    if embedded != actual:
        raise ValueError("manifest 内嵌 SHA 与内容不一致")
    if expected_sha256 and str(expected_sha256).lower() != actual:
        raise ValueError("manifest SHA 与 --expected-sha256 不一致")
    return actual


def seal_publish_ready_backlog_review(
    manifest: dict,
    *,
    decisions: dict,
    reviewer: str,
    now=None,
) -> dict:
    verify_publish_ready_manifest(manifest)
    if not isinstance(decisions, dict):
        raise ValueError("decisions 必须是 article_id 到 review_action 的 JSON object")
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer 不能为空")
    normalized = {str(key): value for key, value in decisions.items()}
    article_ids = {str(row["article_id"]) for row in manifest.get("articles", [])}
    unknown_ids = sorted(set(normalized) - article_ids)
    if unknown_ids:
        raise ValueError(f"审核决定包含 manifest 外文章：{','.join(unknown_ids)}")
    invalid = sorted({str(value) for value in normalized.values()} - REVIEW_ACTIONS)
    if invalid:
        raise ValueError(f"不支持的 review_action：{','.join(invalid)}")

    reviewed = copy.deepcopy(manifest)
    reviewed.pop("manifest_sha256", None)
    for row in reviewed.get("articles", []):
        row["review_action"] = normalized.get(str(row["article_id"]), "keep_manual")
    reviewed["review"] = {
        "status": "approved",
        "reviewer": reviewer,
        "reviewed_at": (now or timezone.now()).isoformat(),
    }
    reviewed["manifest_sha256"] = _canonical_sha(reviewed)
    return reviewed


def _snapshot_drift(article: NewsArticle, expected: dict) -> str:
    actual = article_backlog_snapshot(article)
    for field in (
        "automation_status",
        "workflow_status",
        "publish_ready_at",
        "published_to_web_at",
        "updated_at",
        "content_sha256",
        "gate_sha256",
    ):
        if actual[field] != expected.get(field):
            return field
    return ""


def apply_publish_ready_backlog_manifest(
    manifest: dict,
    *,
    expected_sha256: str,
    now=None,
    limit: int = 100,
) -> dict:
    manifest_sha = verify_publish_ready_manifest(manifest, expected_sha256=expected_sha256)
    review = manifest.get("review") or {}
    if review.get("status") != "approved" or not str(review.get("reviewer") or "").strip():
        raise ValueError("apply 仅接受包含 reviewer 的 approved manifest")
    rows = list(manifest.get("articles") or [])
    if len(rows) > max(1, int(limit)):
        raise ValueError("manifest 文章数超过本次 apply limit")
    if any(row.get("review_action") not in REVIEW_ACTIONS for row in rows):
        raise ValueError("manifest 包含不支持的 review_action")

    apply_now = now or timezone.now()
    outcomes: list[dict] = []
    for row in rows:
        article_id = int(row["article_id"])
        action = row["review_action"]
        with transaction.atomic():
            try:
                article = NewsArticle.objects.select_for_update().get(pk=article_id)
            except NewsArticle.DoesNotExist:
                outcomes.append({"article_id": article_id, "status": "skipped", "reason": "missing"})
                continue
            previous_recovery = (article.decision_reason or {}).get("publish_ready_recovery") or {}
            if action == "revalidate_refresh_ready" and previous_recovery.get("manifest_sha256") == manifest_sha:
                outcomes.append({"article_id": article_id, "status": "already_applied"})
                continue
            drift = _snapshot_drift(article, row.get("snapshot") or {})
            if drift:
                outcomes.append({"article_id": article_id, "status": "skipped", "reason": f"drift:{drift}"})
                continue
            if action == "keep_manual":
                outcomes.append({"article_id": article_id, "status": "kept_manual"})
                continue
            validation = validate_rewrite(article)
            if not validation.passed:
                outcomes.append({"article_id": article_id, "status": "blocked", "reason": validation.reason})
                continue
            public_before = article.published_to_web_at
            qq_before = QQPushDelivery.objects.filter(article=article).count()
            article.decision_reason = {
                **(article.decision_reason or {}),
                "publish_ready_recovery": {
                    "manifest_sha256": manifest_sha,
                    "reviewer": review["reviewer"],
                    "applied_at": apply_now.isoformat(),
                },
            }
            apply_validation_outcome(
                article,
                validation,
                ready_at=apply_now,
                refresh_ready_at=True,
            )
            article.refresh_from_db()
            if (
                article.published_to_web_at != public_before
                or article.workflow_status == WorkflowStatus.PUBLISHED
                or QQPushDelivery.objects.filter(article=article).count() != qq_before
            ):
                raise RuntimeError("恢复命令越权改变了公开状态或 QQ delivery")
            outcomes.append({"article_id": article_id, "status": "refreshed"})

    return {
        "manifest_sha256": manifest_sha,
        "reviewer": review["reviewer"],
        "outcomes": outcomes,
        "refreshed_count": sum(item["status"] == "refreshed" for item in outcomes),
        "kept_manual_count": sum(item["status"] == "kept_manual" for item in outcomes),
        "skipped_count": sum(item["status"] in {"skipped", "blocked"} for item in outcomes),
    }

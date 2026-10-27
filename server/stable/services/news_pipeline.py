"""P01 新闻版本与认领。已接管文章停用后仍隔离旧 writer。"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from django.conf import settings
from django.db import transaction

from stable.models import NewsArticle, NewsProcessingRun

REGIONS = ("japan", "hong_kong", "united_kingdom", "france", "united_states")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def is_pipeline_article(article):
    # 即使调用者持有认领前的旧 ORM 实例，也必须读取已持久化的归属。
    return bool(getattr(article, "active_news_run_id", None)) or bool(
        article.pk and NewsArticle.objects.filter(pk=article.pk, active_news_run__isnull=False).exists()
    )


def policy_sha():
    return digest(getattr(settings, "NEWS_QUALITY_POLICY", {}))


def article_revision(article):
    fields = (
        "title_ja", "body_ja_raw", "body_ja_normalized", "original_content_html", "source_url",
        "published_at", "published_at_verified", "published_at_evidence", "racing_region",
        "attribution_locked", "title_zh", "body_zh", "summary_zh", "translated_title_zh",
        "translated_body_zh", "translated_summary_zh", "rewrite_title_zh", "rewrite_body_zh",
        "rewrite_summary_zh", "manually_edited_fields", "workflow_status", "withdrawn_at",
        "published_to_web_at", "active_news_run_id", "news_generation",
    )
    return digest({name: getattr(article, name) for name in fields})


def source_snapshot(article, draft=None):
    if draft is None:
        return {
            "source_site": article.source_site, "source_mode": article.source_mode,
            "source_id": article.source_article_id, "url": article.source_url,
            "title": article.title_ja, "body": article.body_ja_raw,
            "normalized_body": article.body_ja_normalized, "html": article.original_content_html,
            "language": article.source_language, "region": article.racing_region,
            "attribution_locked": article.attribution_locked,
            "source_time": article.published_at.isoformat(), "time_verified": article.published_at_verified,
            "time_evidence": article.published_at_evidence,
        }
    return {
        "source_site": str(draft.source_site), "source_mode": str(draft.source_mode),
        "source_id": draft.source_article_id, "url": draft.source_url,
        "title": draft.title_ja, "body": draft.body_ja_raw,
        "normalized_body": draft.body_ja_normalized, "html": getattr(draft, "original_content_html", ""),
        "language": draft.source_language or article.source_language,
        "region": article.racing_region if article.attribution_locked else (draft.racing_region or article.racing_region),
        "attribution_locked": article.attribution_locked,
        "source_time": draft.published_at.isoformat() if draft.published_at else None,
        "time_verified": draft.metadata.get("published_at_verified"),
        "time_evidence": draft.metadata.get("published_at_evidence", {}),
    }


@transaction.atomic
def start_revision(article, *, snapshot=None, manual_target=None, editor=None):
    article = NewsArticle.objects.select_for_update().get(pk=article.pk)
    snapshot = deepcopy(snapshot if snapshot is not None else source_snapshot(article))
    target = deepcopy(manual_target or {})
    target_sha = digest(target) if target else "machine"
    run, created = NewsProcessingRun.objects.get_or_create(
        article=article, input_sha=digest(snapshot), policy_sha=policy_sha(), target_revision_sha=target_sha,
        defaults={"source_snapshot": snapshot, "manual_target": target,
                  "editor_provenance": {"user_id": editor.pk} if editor else {},
                  "primary_region": snapshot["region"], "parent_run_id": article.active_news_run_id},
    )
    if not created:
        return run  # 重投不能复活终态、刷新预算、切回旧源文。
    if article.active_news_run_id:
        NewsProcessingRun.objects.filter(pk=article.active_news_run_id).exclude(
            state__in=["published", "duplicate", "rejected", "shadow"]
        ).update(state="stale", reason="new_revision")
    article.news_generation += 1
    article.active_news_run = run
    article.save(update_fields=["active_news_run", "news_generation"])
    run.generation = article.news_generation
    run.expected_article_sha = article_revision(article)
    run.save(update_fields=["generation", "expected_article_sha"])
    return run


def can_enroll(article):
    from django.utils.dateparse import parse_datetime
    policy = getattr(settings, "NEWS_QUALITY_POLICY", {})
    boundary = parse_datetime(policy.get("activated_at", ""))
    source = article.source_config
    return bool(
        getattr(settings, "NEWS_QUALITY_MODE", "off") in {"shadow", "enforce"}
        and boundary and boundary.tzinfo and article.first_seen_at >= boundary
        and source and source.enabled and source.production_approved and not source.deleted_at
        and source.pk in policy.get("source_ids", []) and article.racing_region in REGIONS
        and not article.published_to_web_at and not article.withdrawn_at
    )


@transaction.atomic
def submit_manual_target(article, fields, *, editor):
    article = NewsArticle.objects.select_for_update().get(pk=article.pk)
    active = article.active_news_run
    if active is None:
        raise ValueError("pipeline_owner_required")
    previous = active.manual_target or active.translation_snapshot or {
        "title": article.effective_title, "body": article.effective_body, "summary": article.effective_summary,
    }
    target = {key: fields.get(key + "_zh", previous.get(key, "")) for key in ("title", "body", "summary")}
    if any(not isinstance(value, str) for value in target.values()) or not target["title"].strip() or not target["body"].strip():
        raise ValueError("manual_target_invalid")
    return start_revision(article, snapshot=active.source_snapshot, manual_target=target, editor=editor)


def _current_run(article, run):
    return (
        article.active_news_run_id == run.pk and article.news_generation == run.generation
        and run.policy_sha == policy_sha() and not article.withdrawn_at
        and article_revision(article) == run.expected_article_sha
    )


@transaction.atomic
def claim_stage(run_id, payload):
    from datetime import timedelta
    from django.db.models import Max
    from django.utils import timezone
    from stable.models import NewsStageAttempt
    if getattr(settings, "NEWS_QUALITY_MODE", "off") not in {"shadow", "enforce"}:
        return None
    reference = NewsProcessingRun.objects.get(pk=run_id)
    article = NewsArticle.objects.select_for_update(skip_locked=True).filter(pk=reference.article_id).first()
    if article is None:
        return None
    run = NewsProcessingRun.objects.select_for_update(skip_locked=True).filter(pk=run_id).first()
    if run is None or run.state not in {"pending", "running"}:
        return None
    now = timezone.now()
    if not _current_run(article, run):
        run.state, run.reason = "stale", "revision_changed"
        run.save(update_fields=["state", "reason"])
        return None
    if run.state == "running" or run.next_attempt_at > now:
        return None  # 到期由专门恢复器核对外部请求；不能当成免费重试。
    requests = run.attempts.exclude(provider="")
    if requests.count() >= 10 or requests.filter(stage=run.stage, state="failed").count() >= 3:
        run.state, run.reason = "review", "request_limit"
        run.save(update_fields=["state", "reason"])
        return None
    seq = (run.attempts.filter(stage=run.stage).aggregate(n=Max("seq"))["n"] or 0) + 1
    article.news_generation += 1
    article.save(update_fields=["news_generation"])
    run.generation = article.news_generation
    run.expected_article_sha = article_revision(article)
    run.state, run.lease_until = "running", now + timedelta(seconds=180)
    run.save(update_fields=["generation", "expected_article_sha", "state", "lease_until"])
    return NewsStageAttempt.objects.create(run=run, stage=run.stage, seq=seq,
        generation=run.generation, input_sha=digest(payload))


@transaction.atomic
def commit_stage(attempt_id, generation):
    from django.utils import timezone
    from stable.models import NewsStageAttempt
    reference = NewsStageAttempt.objects.select_related("run").get(pk=attempt_id)
    article = NewsArticle.objects.select_for_update().get(pk=reference.run.article_id)
    run = NewsProcessingRun.objects.select_for_update().get(pk=reference.run_id)
    attempt = NewsStageAttempt.objects.select_for_update().get(pk=attempt_id)
    if not _current_run(article, run):
        if run.state not in {"published", "duplicate", "rejected"}:
            run.state, run.reason = "stale", "revision_changed"
            run.save(update_fields=["state", "reason"])
        return False
    if (run.state != "running" or attempt.generation != generation or run.generation != generation
            or not run.lease_until or timezone.now() >= run.lease_until
            or attempt.state != "completed" or attempt.output_sha != digest(attempt.result)):
        return False
    # 只有接入对应阶段的确定性校验器后才允许推进；原始模型输出不作已审结果。
    return False


def process_news_run(run_id):
    run = NewsProcessingRun.objects.get(pk=run_id)
    return {"run_id": run.pk, "state": run.state}

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from email.utils import parsedate_to_datetime

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    NewsArticle,
    NotificationChannel,
    NotificationLog,
    NotificationStatus,
    NotificationType,
    OperationLog,
    TaskExecutionLog,
    TaskStatus,
    TranslationRun,
    TranslationStatus,
    WorkflowStatus,
)


TRANSIENT_CATEGORIES = {
    "transient_rate_limited",
    "transient_provider_unavailable",
    "transient_timeout",
    "transient_stale_worker",
    "transient_dispatch_failed",
}


@dataclass(frozen=True)
class TranslationErrorClassification:
    category: str
    auto_retryable: bool
    error_summary: str
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class RetryDispatchResult:
    dispatched_ids: list[int] = field(default_factory=list)
    skipped_reason: str = ""


@dataclass(frozen=True)
class TranslationClaimResult:
    claimed: bool
    article_id: int
    reason: str = ""


@dataclass(frozen=True)
class StaleRecoveryResult:
    recovered_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ManualRetryResult:
    accepted: bool
    reason: str


def _retry_after_seconds(value: str, *, now: datetime) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return max(0, int((parsed - now).total_seconds()))


def classify_translation_error(error: Exception, *, now: datetime | None = None) -> TranslationErrorClassification:
    now = now or timezone.now()
    summary = str(error)[:2000]
    if isinstance(error, requests.Timeout) or "timed out" in summary.casefold() or "timeout" in summary.casefold():
        return TranslationErrorClassification("transient_timeout", True, summary)
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    headers = getattr(response, "headers", {}) or {}
    retry_after = _retry_after_seconds(str(headers.get("Retry-After", "")), now=now)
    if status == 429:
        return TranslationErrorClassification("transient_rate_limited", True, summary, retry_after)
    if status in {502, 503, 504}:
        return TranslationErrorClassification("transient_provider_unavailable", True, summary, retry_after)
    if status in {401, 403}:
        return TranslationErrorClassification("permanent_auth", False, summary)
    if status is not None and 400 <= int(status) < 500:
        return TranslationErrorClassification("permanent_payload", False, summary)
    lowered = summary.casefold()
    if "rate limit" in lowered or "too many requests" in lowered:
        return TranslationErrorClassification("transient_rate_limited", True, summary, retry_after)
    if "unavailable" in lowered or "system busy" in lowered:
        return TranslationErrorClassification("transient_provider_unavailable", True, summary, retry_after)
    return TranslationErrorClassification("unknown", False, summary)


def retry_delay_seconds(
    attempt: int,
    *,
    retry_after_seconds: int | None = None,
    jitter_seconds: int | None = None,
) -> int:
    backoffs = list(getattr(settings, "TRANSLATION_AUTO_RETRY_BACKOFF_SECONDS", [60, 300, 900])) or [60, 300, 900]
    base = int(backoffs[min(max(1, attempt) - 1, len(backoffs) - 1)])
    jitter_limit = int(
        getattr(settings, "TRANSLATION_AUTO_RETRY_JITTER_SECONDS", 15)
        if jitter_seconds is None
        else jitter_seconds
    )
    jitter = random.randint(0, max(0, jitter_limit)) if jitter_limit else 0
    return max(base + jitter, int(retry_after_seconds or 0))


def record_translation_failure(
    article: NewsArticle,
    error: Exception,
    *,
    now: datetime | None = None,
    is_retry: bool,
    preserve_publication: bool = False,
) -> TranslationErrorClassification:
    now = now or timezone.now()
    classified = classify_translation_error(error, now=now)
    if is_retry:
        article.translation_retry_count += 1
    article.translation_status = ArticleTranslationStatus.FAILED
    if not preserve_publication:
        article.workflow_status = WorkflowStatus.TRANSLATION_FAILED
        article.automation_status = AutomationStatus.FAILED
    article.translation_error_message = classified.error_summary
    article.translation_error_category = classified.category
    article.translation_started_at = None
    max_attempts = int(getattr(settings, "TRANSLATION_AUTO_RETRY_MAX_ATTEMPTS", 3))
    exhausted = is_retry and article.translation_retry_count >= max_attempts
    if preserve_publication:
        article.translation_next_retry_at = None
        article.translation_retry_exhausted_at = None
    elif classified.auto_retryable and not exhausted:
        next_attempt = article.translation_retry_count + 1
        article.translation_next_retry_at = now + timedelta(
            seconds=retry_delay_seconds(
                next_attempt,
                retry_after_seconds=classified.retry_after_seconds,
            )
        )
        article.translation_retry_exhausted_at = None
    else:
        article.translation_next_retry_at = None
        article.translation_retry_exhausted_at = now if exhausted else None
    article.save(
        update_fields=[
            "translation_status",
            "workflow_status",
            "automation_status",
            "translation_error_message",
            "translation_error_category",
            "translation_started_at",
            "translation_retry_count",
            "translation_next_retry_at",
            "translation_retry_exhausted_at",
            "updated_at",
        ]
    )
    if not classified.auto_retryable or exhausted:
        notify_terminal_translation_failure(article)
    return classified


def dispatch_due_translation_retries(*, now: datetime | None = None) -> RetryDispatchResult:
    now = now or timezone.now()
    if not getattr(settings, "TRANSLATION_AUTO_RETRY_ENABLED", False):
        return RetryDispatchResult(skipped_reason="disabled")
    limit = int(getattr(settings, "TRANSLATION_AUTO_RETRY_BATCH_SIZE", 10))
    due_rows = list(
        NewsArticle.objects.filter(
            translation_status=ArticleTranslationStatus.FAILED,
            translation_error_category__in=TRANSIENT_CATEGORIES,
            translation_next_retry_at__lte=now,
            translation_retry_exhausted_at__isnull=True,
        )
        .order_by("translation_next_retry_at", "id")
        .values_list("id", "translation_next_retry_at")[:limit]
    )
    dispatched_ids: list[int] = []
    for article_id, expected_due_at in due_rows:
        claim = claim_translation_retry(article_id, expected_due_at=expected_due_at, now=now)
        if not claim.claimed:
            continue
        try:
            translate_article_task.delay(article_id, preclaimed_retry=True)
            dispatched_ids.append(article_id)
        except Exception as exc:
            release_failed_translation_dispatch(article_id, claimed_at=now, error=exc)
    return RetryDispatchResult(dispatched_ids=dispatched_ids)


def release_failed_translation_dispatch(
    article_id: int,
    *,
    claimed_at: datetime,
    error: Exception,
) -> bool:
    next_retry_at = claimed_at + timedelta(seconds=retry_delay_seconds(1))
    updated = NewsArticle.objects.filter(
        pk=article_id,
        translation_status=ArticleTranslationStatus.TRANSLATING,
        translation_started_at=claimed_at,
    ).update(
        translation_status=ArticleTranslationStatus.FAILED,
        workflow_status=WorkflowStatus.TRANSLATION_FAILED,
        automation_status=AutomationStatus.FAILED,
        translation_error_category="transient_dispatch_failed",
        translation_error_message=str(error)[:2000],
        translation_started_at=None,
        translation_next_retry_at=next_retry_at,
        updated_at=claimed_at,
    )
    if updated:
        TranslationRun.objects.filter(article_id=article_id, status=TranslationStatus.STARTED).update(
            status=TranslationStatus.FAILED,
            error_message=f"Celery dispatch failed: {str(error)[:1900]}",
            updated_at=claimed_at,
        )
    return bool(updated)


def claim_translation_retry(
    article_id: int,
    *,
    expected_due_at: datetime,
    now: datetime | None = None,
) -> TranslationClaimResult:
    now = now or timezone.now()
    with transaction.atomic():
        updated = NewsArticle.objects.filter(
            pk=article_id,
            translation_status=ArticleTranslationStatus.FAILED,
            translation_next_retry_at=expected_due_at,
            translation_retry_exhausted_at__isnull=True,
        ).update(
            translation_status=ArticleTranslationStatus.TRANSLATING,
            translation_started_at=now,
            translation_next_retry_at=None,
            updated_at=now,
        )
        if not updated:
            return TranslationClaimResult(False, article_id, "already_claimed_or_changed")
        article = NewsArticle.objects.get(pk=article_id)
        TranslationRun.objects.create(
            article=article,
            provider_name=getattr(settings, "TRANSLATION_PROVIDER", ""),
            model_name=getattr(settings, "TRANSLATION_MODEL", ""),
            status=TranslationStatus.STARTED,
        )
    return TranslationClaimResult(True, article_id)


def recover_stale_translations(*, now: datetime | None = None) -> StaleRecoveryResult:
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=int(getattr(settings, "TRANSLATION_STALE_AFTER_SECONDS", 1800)))
    stale_rows = list(
        NewsArticle.objects.filter(
            translation_status=ArticleTranslationStatus.TRANSLATING,
            translation_started_at__lt=cutoff,
        ).values_list("id", "translation_started_at")
    )
    recovered_ids = [
        article_id
        for article_id, started_at in stale_rows
        if recover_one_stale_translation(article_id, expected_started_at=started_at, now=now)
    ]
    return StaleRecoveryResult(recovered_ids=recovered_ids)


def recover_one_stale_translation(
    article_id: int,
    *,
    expected_started_at: datetime,
    now: datetime | None = None,
) -> bool:
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=int(getattr(settings, "TRANSLATION_STALE_AFTER_SECONDS", 1800)))
    with transaction.atomic():
        article = (
            NewsArticle.objects.select_for_update()
            .filter(
                pk=article_id,
                translation_status=ArticleTranslationStatus.TRANSLATING,
                translation_started_at=expected_started_at,
                translation_started_at__lt=cutoff,
            )
            .first()
        )
        if article is None:
            return False
        error = requests.Timeout("stale translating worker interrupted")
        record_translation_failure(article, error, now=now, is_retry=False)
        article.translation_error_category = "transient_stale_worker"
        article.save(update_fields=["translation_error_category", "updated_at"])
        TranslationRun.objects.filter(article=article, status=TranslationStatus.STARTED).update(
            status=TranslationStatus.FAILED,
            error_message="stale translating worker interrupted",
            updated_at=now,
        )
        TaskExecutionLog.objects.create(
            task_name="recover_stale_translations",
            status=TaskStatus.SUCCESS,
            payload={"article_id": article.id, "category": "transient_stale_worker"},
            detail="Recovered stale translating state",
            finished_at=now,
        )
    return True


def run_automation_pipeline(article_id: int) -> None:
    from stable.tasks import process_article_automation_task

    process_article_automation_task.delay(article_id)


def finalize_successful_translation_retry(article: NewsArticle, *, now: datetime | None = None) -> None:
    now = now or timezone.now()
    article.translation_status = ArticleTranslationStatus.TRANSLATED
    article.translation_error_message = ""
    article.translation_error_category = ""
    article.translation_next_retry_at = None
    article.translation_retry_exhausted_at = None
    article.translation_started_at = None
    article.workflow_status = WorkflowStatus.PENDING_EDIT
    article.automation_status = AutomationStatus.PENDING
    reason = dict(article.decision_reason or {})
    reason["translation_recovery"] = {"recovered_at": now.isoformat()}
    article.decision_reason = reason
    article.save()
    run_automation_pipeline(article.id)


def request_manual_translation_retry(
    article: NewsArticle,
    *,
    requested_by=None,
    now: datetime | None = None,
) -> ManualRetryResult:
    now = now or timezone.now()
    recovery = (article.decision_reason or {}).get("manual_translation_retry") or {}
    if article.translation_status == ArticleTranslationStatus.TRANSLATING or recovery.get("requested_at") == now.isoformat():
        return ManualRetryResult(False, "already_due_or_running")
    reason = dict(article.decision_reason or {})
    reason["manual_translation_retry"] = {
        "requested_at": now.isoformat(),
        "requested_by": getattr(requested_by, "id", None),
    }
    article.decision_reason = reason
    article.translation_next_retry_at = now
    article.translation_retry_exhausted_at = None
    article.translation_status = ArticleTranslationStatus.FAILED
    article.workflow_status = WorkflowStatus.TRANSLATION_FAILED
    article.save(
        update_fields=[
            "decision_reason",
            "translation_next_retry_at",
            "translation_retry_exhausted_at",
            "translation_status",
            "workflow_status",
            "updated_at",
        ]
    )
    OperationLog.objects.create(
        admin=requested_by,
        action_type="translation_retry_requested",
        target_type="article",
        target_id=str(article.id),
        detail="运营人员请求立即重试翻译",
    )
    return ManualRetryResult(True, "queued")


def notify_terminal_translation_failure(article: NewsArticle) -> None:
    signature = f"translation_failure:{article.id}:attempt:{article.translation_retry_count}"
    if NotificationLog.objects.filter(
        type=NotificationType.TRANSLATION_FAILED,
        payload_summary__startswith=signature,
        status__in=[NotificationStatus.QUEUED, NotificationStatus.SENT],
    ).exists():
        return
    site_url = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
    article_path = f"/admin/stable/newsarticle/{article.id}/change/"
    article_url = f"{site_url}{article_path}" if site_url else article_path
    recipients = list(getattr(settings, "TRANSLATION_FAILURE_NOTIFY_EMAILS", []) or [])
    summary = (
        f"{signature} article_id={article.id} category={article.translation_error_category} "
        f"retry_count={article.translation_retry_count} {article_url}"
    )
    log = NotificationLog.objects.create(
        type=NotificationType.TRANSLATION_FAILED,
        channel=NotificationChannel.EMAIL,
        status=NotificationStatus.QUEUED,
        target=",".join(recipients),
        payload_summary=summary,
    )
    if not getattr(settings, "TRANSLATION_FAILURE_EMAIL_ENABLED", True) or not recipients:
        log.status = NotificationStatus.SKIPPED
        log.error_message = "翻译失败邮件未启用或未配置收件人"
        log.save(update_fields=["status", "error_message", "updated_at"])
        return
    body = "\n".join(
        [
            "UmaFans 翻译任务已停止自动重试。",
            "",
            f"文章 ID: {article.id}",
            f"标题: {article.effective_title}",
            f"地区: {article.racing_region}",
            f"来源: {article.source_site}:{article.source_mode}",
            f"失败分类: {article.translation_error_category}",
            f"重试次数: {article.translation_retry_count}",
            f"最后错误: {article.translation_error_message}",
            f"快速处理: {article_url}",
        ]
    )
    try:
        send_mail(
            "[UmaFans] 翻译任务失败，需要处理",
            body,
            settings.DEFAULT_FROM_EMAIL,
            recipients,
            fail_silently=False,
        )
        log.status = NotificationStatus.SENT
        log.sent_at = timezone.now()
    except Exception as exc:
        log.status = NotificationStatus.FAILED
        log.error_message = str(exc)[:2000]
    log.save(update_fields=["status", "sent_at", "error_message", "updated_at"])


from stable.tasks import translate_article_task  # noqa: E402

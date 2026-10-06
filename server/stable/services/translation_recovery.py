from __future__ import annotations

import hashlib
import json
import math
import random
from copy import deepcopy
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
    run_id: int | None = None
    claimed_at: str = ""


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
    notify: bool = True,
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
    if notify and (not classified.auto_retryable or exhausted):
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
            translate_article_task.delay(
                article_id, preclaimed_retry=True,
                claim_run_id=claim.run_id, claim_started_at=claim.claimed_at,
            )
            dispatched_ids.append(article_id)
        except Exception as exc:
            release_failed_translation_dispatch(article_id, claimed_at=now, error=exc, run_id=claim.run_id)
    return RetryDispatchResult(dispatched_ids=dispatched_ids)


def release_failed_translation_dispatch(
    article_id: int,
    *,
    claimed_at: datetime,
    error: Exception,
    run_id: int | None = None,
) -> bool:
    if run_id is not None:
        with transaction.atomic():
            article, run, reason = _locked_translation_claim(
                article_id, run_id, claimed_at.isoformat(), phase="claimed",
                now=claimed_at, check_deadline=False, check_input=False,
            )
            if reason:
                return False
            article.translation_status = ArticleTranslationStatus.FAILED
            article.workflow_status = WorkflowStatus.TRANSLATION_FAILED
            article.automation_status = AutomationStatus.FAILED
            article.translation_error_category = "transient_dispatch_failed"
            article.translation_error_message = str(error)[:2000]
            article.translation_started_at = None
            article.translation_next_retry_at = claimed_at + timedelta(seconds=retry_delay_seconds(1))
            article.save(update_fields=[
                "translation_status", "workflow_status", "automation_status",
                "translation_error_category", "translation_error_message",
                "translation_started_at", "translation_next_retry_at", "updated_at",
            ])
            _save_claim_terminal(run, "failed", error=str(error))
        return True
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
        stamp = now.isoformat()
        run = TranslationRun.objects.create(
            article=article,
            provider_name=getattr(settings, "TRANSLATION_PROVIDER", ""),
            model_name=getattr(settings, "TRANSLATION_MODEL", ""),
            status=TranslationStatus.STARTED,
            raw_response={CLAIM_KEY: {
                "phase": "claimed", "claimed_at": stamp,
                "deadline_at": (now + timedelta(seconds=int(getattr(settings, "TRANSLATION_STALE_AFTER_SECONDS", 1800)))).isoformat(),
                "input_sha256": translation_input_sha256(article),
            }},
        )
    return TranslationClaimResult(True, article_id, run_id=run.id, claimed_at=stamp)


CLAIM_KEY = "recovery_claim_v1"
RESULT_KEY = "recovery_result_v1"
RESULT_CONTRACT = "translation-result-apply-v1"
RESULT_MAX_BYTES = 2 * 1024 * 1024
RESULT_MAX_DEPTH = 32


class TranslationCheckpointError(ValueError):
    """结果不能安全持久化/恢复；不是 provider 失败，不增加付费重试次数。"""


def _checkpoint_json(value):
    active = set()

    def validate(item, depth):
        if depth > RESULT_MAX_DEPTH:
            raise TranslationCheckpointError("checkpoint too deep")
        kind = type(item)
        if kind in (dict, list):
            if id(item) in active:
                raise TranslationCheckpointError("checkpoint cycle")
            active.add(id(item))
            try:
                if kind is dict:
                    for key, child in item.items():
                        if type(key) is not str:
                            raise TranslationCheckpointError("checkpoint key type")
                        validate(child, depth + 1)
                else:
                    for child in item:
                        validate(child, depth + 1)
            finally:
                active.remove(id(item))
        elif kind is float:
            if not math.isfinite(item):
                raise TranslationCheckpointError("checkpoint nonfinite number")
        elif kind not in (str, bool, int, type(None)):
            raise TranslationCheckpointError("checkpoint value type")

    validate(value, 0)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, UnicodeError, OverflowError) as exc:
        raise TranslationCheckpointError("checkpoint encoding") from exc
    if len(encoded) > RESULT_MAX_BYTES:
        raise TranslationCheckpointError("checkpoint too large")
    return encoded


def decode_translation_checkpoint(payload, article_id, run_id, claimed_at):
    """锁外严格解码，不重新解析术语或构造 provider；没有跨 claim 缓存。"""
    from .translation import TranslationResult

    encoded = _checkpoint_json(payload)
    if type(payload) is not dict:
        raise TranslationCheckpointError("checkpoint container")
    required = {
        "schema_version", "application_contract_version", "article_id", "run_id", "claimed_at",
        "input_sha256", "deadline_at", "checkpoint_at", "title_zh", "body_zh", "push_summary_zh",
        "metadata", "suppress_automation", "usage_report", "usage_reconciliation", "payload_sha256",
    }
    if set(payload) != required or type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise TranslationCheckpointError("checkpoint schema")
    if payload["application_contract_version"] != RESULT_CONTRACT:
        raise TranslationCheckpointError("checkpoint contract")
    if (type(payload["article_id"]) is not int or type(payload["run_id"]) is not int
            or payload["article_id"] != article_id or payload["run_id"] != run_id
            or payload["claimed_at"] != claimed_at):
        raise TranslationCheckpointError("checkpoint identity")
    for key in ("input_sha256", "payload_sha256"):
        digest = payload[key]
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise TranslationCheckpointError("checkpoint digest type")
    for key in ("title_zh", "body_zh", "push_summary_zh"):
        if type(payload[key]) is not str or (key != "push_summary_zh" and not payload[key].strip()):
            raise TranslationCheckpointError("checkpoint text")
    metadata = payload["metadata"]
    if type(metadata) is not dict or CLAIM_KEY in metadata or RESULT_KEY in metadata:
        raise TranslationCheckpointError("checkpoint metadata")
    for key in ("provider", "model"):
        if type(metadata.get(key)) is not str:
            raise TranslationCheckpointError("checkpoint provider metadata")
    if "terms" in metadata and (type(metadata["terms"]) is not list or any(type(t) is not dict for t in metadata["terms"])):
        raise TranslationCheckpointError("checkpoint terms")
    if "machine_horse_tags" in metadata and (type(metadata["machine_horse_tags"]) is not list
            or any(type(t) is not str for t in metadata["machine_horse_tags"])):
        raise TranslationCheckpointError("checkpoint tags")
    if type(payload["suppress_automation"]) is not bool or payload["usage_reconciliation"] != "unreconciled":
        raise TranslationCheckpointError("checkpoint policy or usage")
    if _checkpoint_json(payload["usage_report"]) != _checkpoint_json(metadata.get("usage")):
        raise TranslationCheckpointError("checkpoint usage changed")
    try:
        stamps = [datetime.fromisoformat(payload[k]) for k in ("claimed_at", "checkpoint_at", "deadline_at")]
        if any(s.utcoffset() is None for s in stamps) or not stamps[0] <= stamps[1] <= stamps[2] or stamps[0] >= stamps[2]:
            raise ValueError("checkpoint timestamps")
    except (TypeError, ValueError) as exc:
        raise TranslationCheckpointError("checkpoint timestamps") from exc
    unsigned = {key: value for key, value in payload.items() if key != "payload_sha256"}
    if hashlib.sha256(_checkpoint_json(unsigned)).hexdigest() != payload["payload_sha256"]:
        raise TranslationCheckpointError("checkpoint digest mismatch")
    # round-trip 只产生内置JSON类型，不触发 deepcopy/自定义对象钩子。
    snapshot = json.loads(encoded)
    return snapshot, TranslationResult(
        title_zh=snapshot["title_zh"], body_zh=snapshot["body_zh"],
        push_summary_zh=snapshot["push_summary_zh"], metadata=snapshot["metadata"],
    )


def build_translation_checkpoint(article, run, result, *, suppress_automation):
    claim = run.raw_response[CLAIM_KEY]
    payload = {
        "schema_version": 1, "application_contract_version": RESULT_CONTRACT,
        "article_id": article.pk, "run_id": run.pk, "claimed_at": claim["claimed_at"],
        "input_sha256": claim["input_sha256"], "deadline_at": claim["deadline_at"],
        "checkpoint_at": timezone.now().isoformat(), "title_zh": result.title_zh,
        "body_zh": result.body_zh, "push_summary_zh": result.push_summary_zh,
        "metadata": result.metadata, "suppress_automation": suppress_automation,
        "usage_report": result.metadata.get("usage") if type(result.metadata) is dict else None,
        "usage_reconciliation": "unreconciled",
    }
    payload["payload_sha256"] = hashlib.sha256(_checkpoint_json(payload)).hexdigest()
    return decode_translation_checkpoint(payload, article.pk, run.pk, claim["claimed_at"])[0]


def translation_input_sha256(article: NewsArticle) -> str:
    # 与翻译实际使用的源字段绑定；不把审计 updated_at 当作内容版本。
    value = {
        "version": "translation-source-v1", "source_site": article.source_site,
        "source_language": article.source_language, "title_ja": article.title_ja,
        "body_field": "body_ja_normalized" if article.body_ja_normalized else "body_ja_raw",
        "body": article.body_ja_normalized or article.body_ja_raw,
    }
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _locked_translation_claim(
    article_id, run_id, claimed_at, *, phase, now, check_deadline=True, check_input=True,
):
    """调用方持 atomic；锁顺序始终 article→指定 run，无外部调用。"""
    if type(run_id) is not int or run_id <= 0 or type(claimed_at) is not str:
        return None, None, "claim_missing"
    article = NewsArticle.objects.select_for_update().filter(pk=article_id).first()
    run = TranslationRun.objects.select_for_update().filter(pk=run_id, article_id=article_id).first()
    if article is None or run is None:
        return article, run, "claim_changed"
    raw = run.raw_response if isinstance(run.raw_response, dict) else {}
    claim = raw.get(CLAIM_KEY)
    if not isinstance(claim, dict) or claim.get("claimed_at") != claimed_at:
        return article, run, "claim_changed"
    phases = phase if type(phase) is tuple else (phase,)
    if claim.get("phase") not in phases or run.status != TranslationStatus.STARTED:
        return article, run, "claim_already_consumed"
    try:
        started = datetime.fromisoformat(claimed_at)
        deadline = datetime.fromisoformat(claim["deadline_at"])
        if started.utcoffset() is None or deadline.utcoffset() is None:
            raise ValueError("naive claim timestamp")
    except (ValueError, TypeError, KeyError):
        return article, run, "claim_changed"
    if article.translation_status != ArticleTranslationStatus.TRANSLATING or article.translation_started_at != started:
        return article, run, "claim_changed"
    # 行锁等待会使锁前 now 失效；两锁到手后读取可注入的执行时钟，截止不续期。
    if check_deadline and timezone.now() >= deadline:
        return article, run, "claim_expired"
    if check_input and translation_input_sha256(article) != claim.get("input_sha256"):
        return article, run, "input_changed"
    return article, run, ""


def consume_translation_claim(article_id, run_id, claimed_at, *, now=None):
    with transaction.atomic():
        article, run, reason = _locked_translation_claim(
            article_id, run_id, claimed_at, phase="claimed", now=now or timezone.now(),
        )
        if reason:
            return article, run, reason
        run.raw_response = {**run.raw_response, CLAIM_KEY: {**run.raw_response[CLAIM_KEY], "phase": "executing"}}
        run.prompt_excerpt = (article.body_ja_normalized or article.body_ja_raw)[:800]
        run.save(update_fields=["raw_response", "prompt_excerpt", "updated_at"])
    return article, run, ""


def prepare_translation_claim(article_id, run_id, claimed_at, *, suppress_automation):
    with transaction.atomic():
        article, run, reason = _locked_translation_claim(
            article_id, run_id, claimed_at, phase=("claimed", "executing"), now=timezone.now(),
        )
        if reason:
            return article, run, None, reason
        raw, claim = run.raw_response, run.raw_response[CLAIM_KEY]
        if claim["phase"] == "claimed":
            if RESULT_KEY in raw or type(suppress_automation) is not bool:
                return article, run, None, "checkpoint_invalid"
            run.raw_response = {**raw, CLAIM_KEY: {**claim, "phase": "executing", "suppress_automation": suppress_automation}}
            run.prompt_excerpt = (article.body_ja_normalized or article.body_ja_raw)[:800]
            run.save(update_fields=["raw_response", "prompt_excerpt", "updated_at"])
            return article, run, None, ""
        if RESULT_KEY not in raw:
            return article, run, None, "claim_already_consumed"
        payload = raw[RESULT_KEY]
    try:
        checkpoint, _ = decode_translation_checkpoint(payload, article_id, run_id, claimed_at)
        if not _checkpoint_matches_claim(checkpoint, claim):
            raise TranslationCheckpointError("checkpoint claim binding")
    except TranslationCheckpointError:
        return article, run, None, "checkpoint_invalid"
    return article, run, checkpoint, ""


def _checkpoint_matches_claim(checkpoint, claim):
    return (checkpoint["input_sha256"] == claim["input_sha256"]
            and checkpoint["deadline_at"] == claim["deadline_at"]
            and ("suppress_automation" not in claim or (type(claim["suppress_automation"]) is bool
                 and checkpoint["suppress_automation"] == claim["suppress_automation"])))


def save_translation_checkpoint(article_id, run_id, claimed_at, checkpoint):
    # 输入校验在锁外；只有既有身份/期限内的 executing 能提交独立结果。
    checkpoint, _ = decode_translation_checkpoint(checkpoint, article_id, run_id, claimed_at)
    with transaction.atomic():
        article, run, reason = _locked_translation_claim(
            article_id, run_id, claimed_at, phase="executing", now=timezone.now(),
        )
        if reason:
            return None, reason
        if not _checkpoint_matches_claim(checkpoint, run.raw_response[CLAIM_KEY]):
            return None, "checkpoint_invalid"
        if RESULT_KEY in run.raw_response:
            existing = run.raw_response[RESULT_KEY]
            if type(existing) is not dict or existing != checkpoint:
                return None, "checkpoint_conflict"
            return checkpoint, ""
        run.raw_response = {**run.raw_response, RESULT_KEY: checkpoint}
        run.save(update_fields=["raw_response", "updated_at"])
    return checkpoint, ""


def _save_claim_terminal(run, phase, *, metadata=None, error=""):
    claim = {**run.raw_response[CLAIM_KEY], "phase": phase}
    metadata = {k: v for k, v in (metadata or {}).items() if k not in {CLAIM_KEY, RESULT_KEY}}
    run.raw_response = {**run.raw_response, **(metadata or {}), CLAIM_KEY: claim}
    run.status = TranslationStatus.SUCCESS if phase == "completed" else TranslationStatus.FAILED
    run.error_message = error[:2000]
    run.model_name = (metadata or {}).get("model") or run.model_name
    run.provider_name = (metadata or {}).get("provider") or run.provider_name
    run.terms_used = (metadata or {}).get("terms", run.terms_used)
    run.save(update_fields=["raw_response", "status", "error_message", "model_name", "provider_name", "terms_used", "updated_at"])


def finalize_translation_claim(article_id, run_id, claimed_at, *, checkpoint=None, error=None, now=None):
    """有效结果与 run 原子落库；失主/到期/输入漂移不回写、不通知。"""
    now = now or timezone.now()
    if error is None:
        try:
            checkpoint, result = decode_translation_checkpoint(checkpoint, article_id, run_id, claimed_at)
        except TranslationCheckpointError:
            return None, "checkpoint_invalid"
    with transaction.atomic():
        article, run, reason = _locked_translation_claim(
            article_id, run_id, claimed_at, phase="executing", now=now,
        )
        if reason:
            return article, reason
        if error is not None:
            if RESULT_KEY in run.raw_response:
                return article, "checkpoint_exists"
            classified = record_translation_failure(article, error, now=now, is_retry=True, notify=False)
            _save_claim_terminal(run, "failed", metadata=getattr(error, "metadata", None), error=str(error))
            if not classified.auto_retryable or article.translation_retry_exhausted_at is not None:
                # 捕获该轮终态快照；回调失败不回流 provider/失败状态路径。
                snapshot = deepcopy(article)
                transaction.on_commit(lambda: notify_terminal_translation_failure(snapshot), robust=True)
        else:
            from stable.models import ArticleStatus

            stored = run.raw_response.get(RESULT_KEY)
            if (type(stored) is not dict or stored != checkpoint
                    or not _checkpoint_matches_claim(checkpoint, run.raw_response[CLAIM_KEY])):
                return article, "checkpoint_changed"

            article.apply_translation_result(result)
            article.status = ArticleStatus.TRANSLATED
            article.translation_status = ArticleTranslationStatus.TRANSLATED
            article.translation_error_message = ""
            article.translation_error_category = ""
            article.translation_next_retry_at = None
            article.translation_retry_exhausted_at = None
            article.translation_started_at = None
            article.translated_at = now
            article.translation_model = result.metadata.get("model", "")
            article.translation_provider = result.metadata.get("provider", "")
            if article.workflow_status in {WorkflowStatus.PENDING_TRANSLATION, WorkflowStatus.TRANSLATION_FAILED}:
                article.workflow_status = WorkflowStatus.PENDING_EDIT
            article.automation_status = AutomationStatus.PENDING
            article.translation_metadata = {**article.translation_metadata, **result.metadata}
            article.decision_reason = {**(article.decision_reason or {}), "translation_recovery": {"recovered_at": now.isoformat()}}
            article.save()
            _save_claim_terminal(run, "completed", metadata=result.metadata)
    return article, ""


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
        managed = list(TranslationRun.objects.select_for_update().filter(
            article=article, status=TranslationStatus.STARTED,
            raw_response__has_key=CLAIM_KEY,
        ))
        if managed:
            matching = [run for run in managed if isinstance(run.raw_response.get(CLAIM_KEY), dict)
                        and run.raw_response[CLAIM_KEY].get("claimed_at") == expected_started_at.isoformat()]
            if len(matching) != 1:
                return False
            run = matching[0]
            phase = run.raw_response[CLAIM_KEY].get("phase")
            if phase not in {"claimed", "executing"}:
                return False
            _, _, reason = _locked_translation_claim(
                article_id, run.id, expected_started_at.isoformat(), phase=phase,
                now=now, check_deadline=False, check_input=False,
            )
            if reason:
                return False
        record_translation_failure(article, error, now=now, is_retry=False, notify=not managed)
        article.translation_error_category = "transient_stale_worker"
        article.save(update_fields=["translation_error_category", "updated_at"])
        if managed:
            _save_claim_terminal(run, "interrupted", error="stale translating worker interrupted")
        else:
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

"""后台人工操作：精确版本、可审计、无发布和外发旁路。"""
from django.db import transaction
from django.utils import timezone
from stable.models import NewsArticle, NewsProcessingRun, NewsPublicationReceipt, NewsEditorialEvent
from stable.services.news_feed import publication_lock
from stable.services.news_pipeline import _current_run, start_revision, enqueue_news_run, source_eligible, article_revision
from stable.services.operations import log_operation


class ReviewConflict(ValueError):
    pass


def _reason(reason):
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise ReviewConflict("请填写不超过1000字的操作原因。")
    return reason.strip()


@transaction.atomic
def withdraw_receipt(receipt_id, *, user, reason):
    reason = _reason(reason)
    publication_lock()
    receipt = NewsPublicationReceipt.objects.select_for_update().get(pk=receipt_id)
    if receipt.visibility == "withdrawn":
        return receipt
    receipt.visibility = "withdrawn"
    receipt.visibility_evidence = {"user_id": user.pk, "reason": reason, "at": timezone.now().isoformat(), "scope": "receipt"}
    receipt.save(update_fields=["visibility", "visibility_evidence"])
    log_operation(action_type="news_receipt_withdrawn", target_type="news_receipt", target_id=receipt.pk,
        detail=reason, admin=user)
    from stable.services.news_feed import request_snapshot_refresh
    transaction.on_commit(request_snapshot_refresh)
    return receipt


@transaction.atomic
def review_action(run_id, *, action, user, reason, event_id=None, receipt_id=None, receipt_ids=()):
    reason = _reason(reason)
    # 与网页发布保持同一锁次序；整来源范围在锁内核对，避免确认后悄悄纳入新稿。
    publication_lock()
    reference = NewsProcessingRun.objects.get(pk=run_id)
    article = NewsArticle.objects.select_for_update().get(pk=reference.article_id)
    run = NewsProcessingRun.objects.select_for_update().get(pk=run_id)
    if article.active_news_run_id != run.pk:
        raise ReviewConflict("已有较新修订，请刷新后操作。")
    if action == "withdraw_source":
        current = list(article.news_receipts.filter(visibility="public").order_by("id"))
        if sorted(str(row.pk) for row in current) != sorted(receipt_ids):
            raise ReviewConflict("公开稿件范围已经变化，请核对完整清单后重试。")
        for receipt in current:
            withdraw_receipt(receipt.pk, user=user, reason=reason)
        article.withdrawn_at = timezone.now()
        article.save(update_fields=["withdrawn_at"])
        if run.state != "published":
            run.state, run.reason = "rejected", "source_withdrawn"
            run.save(update_fields=["state", "reason"])
    elif action == "bind_event":
        event = NewsEditorialEvent.objects.filter(pk=event_id).first()
        if not event or (receipt_id and not event.receipts.filter(pk=receipt_id).exists()):
            raise ReviewConflict("事件或更正原稿不匹配。")
        binding = {"event_id": str(event.pk), "receipt_id": str(receipt_id) if receipt_id else ""}
        run = start_revision(article, snapshot=run.source_snapshot, manual_target=run.manual_target,
            editor=user, event_binding=binding, reason=reason)
    elif action in {"hold", "reject"}:
        if run.state in {"published", "duplicate", "stale"}:
            raise ReviewConflict("已结束稿件不可再次接管；撤回请选具体公开稿。")
        article.news_generation += 1
        article.save(update_fields=["news_generation"])
        run.generation, run.expected_article_sha = article.news_generation, article_revision(article)
        run.state, run.reason, run.lease_until = ("review" if action == "hold" else "rejected"), reason[:255], None
        run.save(update_fields=["state", "reason", "lease_until", "generation", "expected_article_sha"])
    elif action == "retry":
        if run.state != "review" or not _current_run(article, run) or not source_eligible(run):
            raise ReviewConflict("当前版本或来源不可重跑，请先核对配置及待审内容。")
        if run.attempts.filter(state__in=["reserved", "inflight", "unknown"]).exists():
            raise ReviewConflict("存在未核清请求，不能重复调用模型。")
        if run.attempts.exclude(provider="").count() >= 10 or run.attempts.filter(stage=run.stage, state="failed").exclude(provider="").count() >= 3:
            raise ReviewConflict("本版本已达到请求上限。")
        if run.reason in {"quality_failed", "correction_not_substantively_verified"}:
            raise ReviewConflict("请先修正待审内容，再提交新的审校版本。")
        run.state, run.reason, run.lease_until, run.next_attempt_at = "pending", "manual_retry", None, timezone.now()
        if run.stage == "publish":
            run.state = "ready"
        run.save(update_fields=["state", "reason", "lease_until", "next_attempt_at"])
        transaction.on_commit(lambda: enqueue_news_run(run.pk))
    else:
        raise ReviewConflict("未知操作。")
    log_operation(action_type="news_quality_"+action, target_type="news_run", target_id=run.pk, detail=reason, admin=user)
    return run

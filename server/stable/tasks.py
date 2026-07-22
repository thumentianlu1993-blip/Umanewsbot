from __future__ import annotations

from datetime import datetime, timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from stable.adapters.jra import JRAAdapter
from stable.adapters.international import INTERNATIONAL_ADAPTERS
from stable.adapters.netkeiba import NetkeibaAdapter
from stable.models import (
    ArticleStatus,
    ArticleTranslationStatus,
    AutomationPhase,
    AutomationStatus,
    CrawlJob,
    HorseIdentityConflict,
    HorseIdentityConflictStatus,
    HorseProfile,
    NewsArticle,
    NewsSource,
    NotificationLog,
    NotificationType,
    PublishedByMode,
    ProductionWindow,
    ProductionWindowKind,
    ProductionWindowMode,
    ProductionWindowStatus,
    QQPushDelivery,
    QQPushDeliveryStatus,
    PushTarget,
    RaceLiveAlertIncident,
    RacingRegion,
    ReviewMode,
    SourceMode,
    TaskExecutionLog,
    TaskStatus,
    TranslationStatus,
    WorkflowStatus,
)
from stable.services.automation import (
    apply_score_decision,
    automation_content_source,
    important_manual_notification_payload,
    is_ready_for_auto_publish,
    mark_automation_failed,
    prepare_base_translation_for_publish,
    publish_article_automatically,
    revive_article_after_ranked_source_elevation,
    score_article_for_automation,
)
from stable.services.ingestion import upsert_article_from_draft
from stable.services.multiregion import auto_publish_count_today, auto_publish_policy_for_article
from stable.services.multiregion import summarize_multiregion_news_production
from stable.services.news_production_integrity import (
    region_source_health_summary,
    task_execution_index_error_snapshot,
)
from stable.services.news_attribution import apply_article_attribution
from stable.services.notifications import send_automation_notification, send_high_value_warning_notification
from stable.services.operations import log_operation
from stable.services.ops_notifications import send_ops_notification, send_production_summary_notification
from stable.services.onebot import BotPusher
from stable.services.production_windows import (
    active_major_race_window,
    claim_window,
    classify_source_error,
    current_window_bounds,
    due_window_starts,
    record_source_crawl_result,
    select_production_sources,
)
from stable.services.publishing_windows import select_publish_candidates
from stable.services.pushing import push_article_to_targets
from stable.services.qq_auto_push import (
    ensure_qq_push_deliveries,
    get_auto_push_targets,
    is_article_public,
    process_qq_push_delivery,
    qq_push_next_attempt_delay,
    should_push_news_to_qq,
)
from stable.services.qq_windows import select_qq_window_deliveries
from stable.services.queueing import dispatch_task
from stable.services.rewriting import apply_rewrite_result, rewrite_article
from stable.services.sources import find_builtin_source, sync_builtin_sources
from stable.services.source_polling import select_due_enabled_news_sources
from stable.services.term_discovery import discover_and_aggregate_article
from stable.services.translation import translate_article
from stable.services.validation import apply_validation_outcome, validate_rewrite
from stable.services.external_horse_data import ExternalHorseDataImporter, ImportOptions
from stable.services.race_events import (
    claim_due_race_event_live_tracking,
    claim_race_live_alert_delivery,
    complete_race_event_live_checkpoint,
    complete_race_live_alert_delivery,
    resolve_race_live_worker_network_admission,
    stage_race_live_sla_alerts,
)


User = get_user_model()
JRA_SKIPPABLE_DETAIL_ERRORS = (ValueError, AttributeError, IndexError, TypeError)


@shared_task
def select_due_race_live_events_task() -> dict:
    if getattr(settings, "RACE_LIVE_SCHEDULER_ENABLED", False) is not True:
        return {"enabled": False, "claimed": 0, "dispatched": 0}
    enabled_regions = tuple(
        getattr(settings, "RACE_LIVE_ENABLED_REGIONS", ())
    )
    if not enabled_regions:
        return {"enabled": False, "claimed": 0, "dispatched": 0}

    claims = claim_due_race_event_live_tracking(
        now=timezone.now(),
        batch_size=settings.RACE_LIVE_SELECTOR_BATCH_SIZE,
        ttl_seconds=settings.RACE_LIVE_CLAIM_TTL_SECONDS,
        enabled_regions=enabled_regions,
    )
    for claim in claims:
        dispatch_kwargs = {
            "event_id": claim.event_id,
            "expected_owner_generation": claim.owner_generation,
            "expected_claim_generation": claim.claim_generation,
            "attempt_token": claim.attempt_token,
        }
        transaction.on_commit(
            lambda kwargs=dispatch_kwargs: poll_race_live_event_task.apply_async(
                kwargs=kwargs,
                queue="race_live",
            )
        )
    claimed = len(claims)
    return {"enabled": True, "claimed": claimed, "dispatched": claimed}


@shared_task
def poll_race_live_event_task(
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
) -> dict:
    runner_mode = getattr(settings, "RACE_LIVE_RUNNER_MODE", "disabled")
    if runner_mode == "disabled":
        return {
            "processed": False,
            "reason": "runner_not_configured",
            "event_id": event_id,
        }

    if runner_mode == "the_racing_api_free":
        enabled_regions = tuple(
            getattr(settings, "RACE_LIVE_ENABLED_REGIONS", ())
        )
        admission_now = timezone.now()
        admission = resolve_race_live_worker_network_admission(
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            enabled_regions=enabled_regions,
            now=admission_now,
        )
        if admission.allowed is not True:
            complete_race_event_live_checkpoint(
                event_id=event_id,
                expected_owner_generation=expected_owner_generation,
                expected_claim_generation=expected_claim_generation,
                attempt_token=attempt_token,
                now=admission_now,
                success=False,
                next_poll_at=admission_now + timedelta(minutes=5),
                checkpoint_payload={
                    "status": "network_admission_rejected",
                    "reason": admission.reason,
                },
                observation_sha256="",
            )
            return {
                "processed": False,
                "reason": f"network_admission_{admission.reason}",
                "event_id": event_id,
            }
        from stable.services.race_live_runner import (
            run_race_live_the_racing_api_free,
        )
        from stable.services.race_live_source_proof import (
            the_racing_api_transport,
        )

        return run_race_live_the_racing_api_free(
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            secret_env_file=getattr(
                settings,
                "RACE_LIVE_TRA_SECRET_ENV_FILE",
                "",
            ),
            registry_file=getattr(
                settings,
                "RACE_LIVE_TRA_REGISTRY_FILE",
                "",
            ),
            expected_registry_sha256=getattr(
                settings,
                "RACE_LIVE_TRA_REGISTRY_SHA256",
                "",
            ),
            now=timezone.now(),
            transport=the_racing_api_transport,
            clock=timezone.now,
        )

    from stable.services.race_live_runner import run_race_live_offline_fixture

    if runner_mode != "offline_fixture":
        return run_race_live_offline_fixture(
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            fixture_root="",
            configured_mode=runner_mode,
        )
    return run_race_live_offline_fixture(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        fixture_root=getattr(settings, "RACE_LIVE_OFFLINE_FIXTURE_ROOT", ""),
        configured_mode=runner_mode,
    )


@shared_task
def monitor_race_live_sla_task() -> dict:
    if getattr(settings, "RACE_LIVE_MONITOR_ENABLED", False) is not True:
        return {"enabled": False, "staged": 0, "dispatched": 0}
    enabled_regions = tuple(
        getattr(settings, "RACE_LIVE_ENABLED_REGIONS", ())
    )
    if not enabled_regions:
        return {"enabled": False, "staged": 0, "dispatched": 0}
    incident_ids = stage_race_live_sla_alerts(
        now=timezone.now(),
        enabled_regions=enabled_regions,
    )
    for incident_id in incident_ids:
        transaction.on_commit(
            lambda value=incident_id: deliver_race_live_alert_task.apply_async(
                kwargs={"incident_id": value},
                queue="race_live",
            )
        )
    return {
        "enabled": True,
        "staged": len(incident_ids),
        "dispatched": len(incident_ids),
    }


@shared_task
def deliver_race_live_alert_task(incident_id: int) -> dict:
    now = timezone.now()
    claim = claim_race_live_alert_delivery(
        incident_id=incident_id,
        now=now,
        lease_seconds=300,
    )
    if not claim.claimed:
        return {
            "delivered": False,
            "reason": claim.reason,
            "incident_id": incident_id,
        }
    incident = RaceLiveAlertIncident.objects.filter(pk=incident_id).first()
    recipients = list(
        getattr(settings, "RACE_LIVE_ALERT_NOTIFY_EMAILS", ()) or ()
    )
    delivered = False
    error_code = ""
    if incident is None:
        error_code = "incident_missing_after_claim"
    elif not recipients:
        error_code = "recipients_missing"
    else:
        details = (
            incident.details if isinstance(incident.details, dict) else {}
        )
        region = str(details.get("region", "unknown"))
        event_label = str(details.get("event_id", incident.scope_key))
        event_name = str(details.get("event_name", event_label))
        route = str(details.get("official_route", "the_racing_api"))
        try:
            delivered = (
                send_mail(
                    (
                        f"[UmaFans] 准实时赛果告警 "
                        f"{incident.alert_type} event {event_label} "
                        f"{event_name}"
                    ),
                    "\n".join(
                        (
                            f"地区: {region}",
                            f"event: {event_label}",
                            f"赛事: {event_name}",
                            f"告警: {incident.alert_type}",
                            f"route: {route}",
                            f"incident: {incident.pk}",
                        )
                    ),
                    settings.DEFAULT_FROM_EMAIL,
                    recipients,
                    fail_silently=False,
                )
                == 1
            )
            if not delivered:
                error_code = "smtp_zero_deliveries"
        except Exception:
            error_code = "smtp_delivery_failed"
    completion = complete_race_live_alert_delivery(
        incident_id=incident_id,
        delivery_token=claim.delivery_token,
        now=timezone.now(),
        delivered=delivered,
        error_code=error_code,
    )
    return {
        "delivered": delivered and completion.applied,
        "reason": completion.reason,
        "incident_id": incident_id,
    }


@shared_task
def scan_article_horse_links_task(article_id: int | None = None, profile_id: int | None = None, limit: int = 500, commit: bool = True) -> dict:
    from stable.services.horse_profiles import scan_article_horse_links

    article = NewsArticle.objects.filter(pk=article_id).first() if article_id else None
    profile = HorseProfile.objects.filter(pk=profile_id).first() if profile_id else None
    if article_id and article is None:
        return {"skipped": True, "reason": "article_not_found", "article_id": article_id}
    if profile_id and profile is None:
        return {"skipped": True, "reason": "horse_profile_not_found", "profile_id": profile_id}
    return scan_article_horse_links(article=article, profile=profile, limit=limit, commit=commit)


def _log_start(task_name: str, payload: dict | None = None) -> TaskExecutionLog:
    return TaskExecutionLog.objects.create(task_name=task_name, status=TaskStatus.STARTED, payload=payload or {})


def _log_success(log: TaskExecutionLog, detail: str) -> None:
    log.status = TaskStatus.SUCCESS
    log.detail = detail
    log.finished_at = timezone.now()
    log.save()


def _log_failure(log: TaskExecutionLog, detail: str) -> None:
    log.status = TaskStatus.FAILED
    log.detail = detail
    log.finished_at = timezone.now()
    log.save()


def _start_crawl_job(source: NewsSource | None) -> CrawlJob:
    return CrawlJob.objects.create(source=source, status=TaskStatus.STARTED)


def _finish_crawl_job(
    job: CrawlJob,
    *,
    success_count: int = 0,
    fail_count: int = 0,
    error_message: str = "",
    message: str = "",
) -> bool:
    finished_at = timezone.now()
    terminal_status = TaskStatus.FAILED if error_message else TaskStatus.SUCCESS
    terminal_message = error_message or message
    with transaction.atomic():
        claimed = bool(
            CrawlJob.objects.filter(pk=job.pk, status=TaskStatus.STARTED).update(
                status=terminal_status,
                success_count=success_count,
                fail_count=fail_count,
                error_message=terminal_message,
                finished_at=finished_at,
                updated_at=finished_at,
            )
        )
        if not claimed:
            TaskExecutionLog.objects.create(
                task_name="crawl_job_terminal_state",
                status=TaskStatus.SUCCESS,
                payload={"crawl_job_id": job.pk, "source_id": job.source_id},
                detail="terminal_state_already_claimed",
                started_at=finished_at,
                finished_at=finished_at,
            )
            return False
        if job.source_id:
            NewsSource.objects.filter(pk=job.source_id).update(
                last_crawl_at=finished_at,
                last_crawl_status=terminal_status,
                last_crawl_message=terminal_message or f"新增 {success_count}，重复 {fail_count}",
                updated_at=finished_at,
            )
        job.status = terminal_status
        job.success_count = success_count
        job.fail_count = fail_count
        job.error_message = terminal_message
        job.finished_at = finished_at
    return True


def _parse_task_now(now_iso: str | None = None) -> datetime:
    return datetime.fromisoformat(now_iso) if now_iso else timezone.now()


def _json_safe_dispatch_result(result) -> dict | str:
    if isinstance(result, dict | list | str | int | float | bool) or result is None:
        return result
    task_id = getattr(result, "id", None)
    if task_id:
        return {"task_id": str(task_id)}
    return {"repr": repr(result)}


def _window_starts_to_run(*, kind: str, scope_key: str, now: datetime, minutes: int) -> list[datetime]:
    current = current_window_bounds(now, minutes=minutes).start
    lookback_hours = int(getattr(settings, "MULTIREGION_PRODUCTION_WINDOW_LOOKBACK_HOURS", 3))
    earliest = current - timedelta(hours=max(0, lookback_hours))
    starts: set[datetime] = {current}
    last_success = (
        ProductionWindow.objects.filter(
            kind=kind,
            scope_key=scope_key,
            status=ProductionWindowStatus.SUCCEEDED,
            window_start__lt=current,
        )
        .order_by("-window_start")
        .values_list("window_start", flat=True)
        .first()
    )
    if last_success is not None:
        starts.update(due_window_starts(last_window_start=last_success, now=now, minutes=minutes))
    starts.update(
        ProductionWindow.objects.filter(
            kind=kind,
            scope_key=scope_key,
            window_start__gte=earliest,
            window_start__lte=current,
        )
        .exclude(status=ProductionWindowStatus.SUCCEEDED)
        .values_list("window_start", flat=True)
    )
    return sorted(starts)


def _http_status_code_from_exception(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return int(status_code) if status_code is not None else None


def _finish_crawl_window(window_id: int | None, *, status: str, reason: str, payload: dict | None = None, error: str = "") -> None:
    if not window_id:
        return
    window = ProductionWindow.objects.filter(pk=window_id, kind=ProductionWindowKind.CRAWL).first()
    if window is None:
        return
    window.status = status
    window.finished_at = timezone.now()
    window.reason_summary = reason
    window.result_payload = payload or {}
    window.last_error = error
    window.save(update_fields=["status", "finished_at", "reason_summary", "result_payload", "last_error", "updated_at"])


def _can_coalesce_old_window(window: ProductionWindow, *, now: datetime) -> bool:
    if window.status in {
        ProductionWindowStatus.PENDING,
        ProductionWindowStatus.FAILED,
        ProductionWindowStatus.SKIPPED,
    }:
        return True
    return (
        window.status == ProductionWindowStatus.RUNNING
        and (window.lease_expires_at is None or window.lease_expires_at <= now)
    )


def _auto_translate_article_after_ingest(article: NewsArticle) -> dict | None:
    if not getattr(settings, "AUTO_TRANSLATE_ON_INGEST", True):
        return None
    try:
        if getattr(settings, "AUTO_TRANSLATE_SYNC", True):
            return translate_article_task.run(article.id)
        return dispatch_task(translate_article_task, article.id)
    except Exception as exc:
        return {"article_id": article.id, "translated": False, "error": str(exc)}


def _discover_terms_after_ingest(article: NewsArticle) -> dict | None:
    if not getattr(settings, "TERM_DISCOVERY_ENABLED", False):
        return None
    try:
        return dispatch_task(discover_term_candidates_task, article.id)
    except Exception as exc:
        return {"article_id": article.id, "discovered": False, "error": str(exc)}


def _qq_push_after_source_elevation(article: NewsArticle, *, source_elevated: bool) -> dict | None:
    if not source_elevated or not getattr(settings, "QQ_PUSH_ENABLED", False) or not is_article_public(article):
        return None
    try:
        return dispatch_task(qq_auto_push_article_task, article.id)
    except Exception as exc:
        return {"article_id": article.id, "queued": False, "error": str(exc)}


def _ranked_revival_after_source_elevation(article: NewsArticle, *, source_elevated: bool) -> dict | None:
    if not source_elevated or is_article_public(article):
        return None
    try:
        result = revive_article_after_ranked_source_elevation(article)
        payload = {
            "article_id": article.id,
            "revived": bool(getattr(result, "revived", False)),
            "action": getattr(result, "action", ""),
            "reason": getattr(result, "reason", ""),
        }
        if payload["action"] == "translation_retry":
            payload["dispatch_result"] = _json_safe_dispatch_result(dispatch_task(translate_article_task, article.id))
        elif payload["action"] == "rescore":
            payload["dispatch_result"] = _json_safe_dispatch_result(dispatch_task(process_article_automation_task, article.id))
        return payload
    except Exception as exc:
        return {"article_id": article.id, "revived": False, "action": "error", "error": str(exc)}


def _crawl_netkeiba_mode(mode: str, pages: int, source: NewsSource | None = None) -> dict:
    adapter = NetkeibaAdapter()
    job = _start_crawl_job(source)
    new_count = 0
    seen_count = 0
    ranked_revival_results: list[dict] = []
    try:
        for page in range(1, pages + 1):
            stubs = adapter.fetch_listing(mode, page)
            if not stubs:
                break
            for stub in stubs:
                detail = adapter.fetch_detail(stub.source_article_id)
                draft = adapter.normalize_source_payload(stub, detail)
                upsert_result = upsert_article_from_draft(draft, crawl_job=job)
                article, created = upsert_result
                if created:
                    new_count += 1
                    _discover_terms_after_ingest(article)
                    _auto_translate_article_after_ingest(article)
                else:
                    seen_count += 1
                    revival_result = _ranked_revival_after_source_elevation(
                        article,
                        source_elevated=bool(getattr(upsert_result, "source_elevated", False)),
                    )
                    if revival_result:
                        ranked_revival_results.append(revival_result)
                    _qq_push_after_source_elevation(
                        article,
                        source_elevated=bool(getattr(upsert_result, "source_elevated", False)),
                    )
            if mode in {SourceMode.ACCESS, SourceMode.ATTENTION}:
                break
        terminal_state_claimed = _finish_crawl_job(job, success_count=new_count, fail_count=seen_count)
        return {
            "new_count": new_count,
            "seen_count": seen_count,
            "crawl_job_id": job.id,
            "ranked_revival_results": ranked_revival_results,
            "terminal_state_claimed": terminal_state_claimed,
        }
    except Exception as exc:
        terminal_state_claimed = _finish_crawl_job(
            job,
            success_count=new_count,
            fail_count=seen_count,
            error_message=str(exc),
        )
        setattr(exc, "_crawl_terminal_state_claimed", terminal_state_claimed)
        raise


def _crawl_jra_source(source: NewsSource | None = None) -> dict:
    adapter = JRAAdapter()
    job = _start_crawl_job(source)
    months = {
        timezone.localtime().strftime("%Y%m"),
        (timezone.localtime() - timedelta(days=31)).strftime("%Y%m"),
    }
    new_count = 0
    seen_count = 0
    skipped_errors: list[str] = []
    try:
        for month in sorted(months):
            for stub in adapter.fetch_listing(SourceMode.OFFICIAL, month):
                try:
                    detail = adapter.fetch_detail(stub.source_url)
                except JRA_SKIPPABLE_DETAIL_ERRORS as exc:
                    skipped_errors.append(f"{stub.source_url}: {exc}")
                    continue
                draft = adapter.normalize_source_payload(stub, detail)
                article, created = upsert_article_from_draft(draft, crawl_job=job)
                if created:
                    new_count += 1
                    _discover_terms_after_ingest(article)
                    _auto_translate_article_after_ingest(article)
                else:
                    seen_count += 1
        skipped_errors = [*adapter.skipped_items, *skipped_errors]
        message = ""
        if skipped_errors:
            message = f"新增 {new_count}，重复 {seen_count}；跳过 {len(skipped_errors)} 条：{skipped_errors[0][:120]}"
        terminal_state_claimed = _finish_crawl_job(job, success_count=new_count, fail_count=seen_count, message=message)
        return {
            "new_count": new_count,
            "seen_count": seen_count,
            "skipped_count": len(skipped_errors),
            "crawl_job_id": job.id,
            "terminal_state_claimed": terminal_state_claimed,
        }
    except Exception as exc:
        terminal_state_claimed = _finish_crawl_job(
            job,
            success_count=new_count,
            fail_count=seen_count,
            error_message=str(exc),
        )
        setattr(exc, "_crawl_terminal_state_claimed", terminal_state_claimed)
        raise


def _crawl_international_source(source: NewsSource) -> dict:
    adapter_class = INTERNATIONAL_ADAPTERS.get(source.adapter_key)
    if adapter_class is None:
        raise NotImplementedError(f"未支持的国际新闻适配器：{source.adapter_key}")
    adapter = adapter_class()
    job = _start_crawl_job(source)
    new_count = 0
    seen_count = 0
    detail_errors: list[str] = []
    ranked_revival_results: list[dict] = []
    unverified_time_count = 0
    try:
        for stub in adapter.fetch_listing(source.source_mode, 1):
            try:
                detail = adapter.fetch_detail(stub.source_url)
                draft = adapter.normalize_source_payload(stub, detail)
                if (getattr(draft, "metadata", {}) or {}).get("published_at_verified") is False:
                    unverified_time_count += 1
            except Exception as exc:
                detail_errors.append(f"{stub.source_url}: {exc}")
                continue
            upsert_result = upsert_article_from_draft(draft, crawl_job=job)
            article, created = upsert_result
            if created:
                new_count += 1
                _discover_terms_after_ingest(article)
                _auto_translate_article_after_ingest(article)
            else:
                seen_count += 1
                revival_result = _ranked_revival_after_source_elevation(
                    article,
                    source_elevated=bool(getattr(upsert_result, "source_elevated", False)),
                )
                if revival_result:
                    ranked_revival_results.append(revival_result)
                _qq_push_after_source_elevation(
                    article,
                    source_elevated=bool(getattr(upsert_result, "source_elevated", False)),
                )
        listing_skips = list(getattr(adapter, "skipped_items", []) or [])
        query_errors = list(getattr(adapter, "last_listing_query_errors", []) or [])
        skipped_errors = [*listing_skips, *detail_errors]
        message = ""
        if skipped_errors:
            message = f"新增 {new_count}，重复 {seen_count}；跳过 {len(skipped_errors)} 条：{skipped_errors[0][:120]}"
            if detail_errors:
                message = f"新增 {new_count}，重复 {seen_count}；parse failed 跳过 {len(skipped_errors)} 条：{skipped_errors[0][:120]}"
        if detail_errors and new_count == 0 and seen_count == 0:
            error_message = message or "parse failed: no parsable article details"
            terminal_state_claimed = _finish_crawl_job(
                job,
                success_count=new_count,
                fail_count=len(detail_errors),
                error_message=error_message,
            )
            failure = RuntimeError(error_message)
            setattr(failure, "_crawl_terminal_state_claimed", terminal_state_claimed)
            raise failure
        terminal_state_claimed = _finish_crawl_job(job, success_count=new_count, fail_count=seen_count, message=message)
        return {
            "new_count": new_count,
            "seen_count": seen_count,
            "skipped_count": len(skipped_errors),
            "crawl_job_id": job.id,
            "ranked_revival_results": ranked_revival_results,
            "terminal_state_claimed": terminal_state_claimed,
            "source_summary": {
                "new_articles": new_count,
                "duplicates": seen_count,
                "historical_filtered": sum("stale_published_at" in item for item in listing_skips),
                "published_at_missing": sum("missing_published_at" in item for item in listing_skips),
                "published_at_unverified": unverified_time_count,
                "query_failures": len(query_errors),
                "detail_failures": len(detail_errors),
            },
        }
    except Exception as exc:
        job.refresh_from_db(fields=["status"])
        if job.status == TaskStatus.STARTED:
            terminal_state_claimed = _finish_crawl_job(
                job,
                success_count=new_count,
                fail_count=seen_count,
                error_message=str(exc),
            )
            setattr(exc, "_crawl_terminal_state_claimed", terminal_state_claimed)
        raise


@shared_task
def crawl_netkeiba_latest(max_pages: int = 3, rush_window: bool = False) -> dict:
    sync_builtin_sources()
    source = find_builtin_source("netkeiba", "latest")
    log = _log_start("crawl_netkeiba_latest", {"max_pages": max_pages, "rush_window": rush_window})
    try:
        result = _crawl_netkeiba_mode("latest", max_pages, source=source)
        _log_success(log, f"new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_netkeiba_access() -> dict:
    sync_builtin_sources()
    source = find_builtin_source("netkeiba", "access")
    log = _log_start("crawl_netkeiba_access")
    try:
        result = _crawl_netkeiba_mode("access", 1, source=source)
        _log_success(log, f"new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_netkeiba_attention() -> dict:
    sync_builtin_sources()
    source = find_builtin_source("netkeiba", "attention")
    log = _log_start("crawl_netkeiba_attention")
    try:
        result = _crawl_netkeiba_mode("attention", 1, source=source)
        _log_success(log, f"new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_jra_news() -> dict:
    sync_builtin_sources()
    source = find_builtin_source("jra", "official")
    log = _log_start("crawl_jra_news")
    try:
        result = _crawl_jra_source(source=source)
        _log_success(log, f"new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_news_source_task(source_id: int, window_id: int | None = None) -> dict:
    sync_builtin_sources()
    source = NewsSource.objects.get(pk=source_id, deleted_at__isnull=True)
    log = _log_start("crawl_news_source", {"source_id": source_id, "window_id": window_id})
    try:
        if source.adapter_key == "netkeiba":
            pages = 3 if source.source_mode == SourceMode.LATEST else 1
            result = _crawl_netkeiba_mode(source.source_mode, pages, source=source)
        elif source.adapter_key == "jra":
            result = _crawl_jra_source(source=source)
        elif source.adapter_key in INTERNATIONAL_ADAPTERS:
            result = _crawl_international_source(source)
        else:
            raise NotImplementedError("当前版本仅支持内置 netkeiba / JRA / 一期国际新闻来源")
        if result.get("terminal_state_claimed"):
            record_source_crawl_result(source, success=True)
        _finish_crawl_window(
            window_id,
            status=ProductionWindowStatus.SUCCEEDED,
            reason="completed",
            payload={
                "new_count": result.get("new_count", 0),
                "seen_count": result.get("seen_count", 0),
                "crawl_job_id": result.get("crawl_job_id"),
                "ranked_revival_results": result.get("ranked_revival_results", []),
            },
        )
        _log_success(log, f"source={source_id} new={result['new_count']} seen={result['seen_count']}")
        return result
    except Exception as exc:
        error_category = classify_source_error(status_code=_http_status_code_from_exception(exc), message=str(exc))
        if getattr(exc, "_crawl_terminal_state_claimed", False):
            record_source_crawl_result(source, success=False, error_category=error_category)
        _finish_crawl_window(
            window_id,
            status=ProductionWindowStatus.FAILED,
            reason="crawl_failed",
            payload={"error_category": error_category},
            error=str(exc),
        )
        _log_failure(log, str(exc))
        raise


@shared_task
def crawl_production_sources_window_task(now_iso: str | None = None) -> dict:
    log = _log_start("crawl_production_sources_window", {"now_iso": now_iso})
    if (
        not getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_ENABLED", False)
        or not getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED", False)
        or getattr(settings, "MULTIREGION_ROLLBACK_DISABLE_CRAWL_WINDOWS", False)
    ):
        _log_success(log, "disabled")
        return {"skipped": True, "reason": "disabled", "triggered_source_ids": []}

    now = _parse_task_now(now_iso)
    sync_builtin_sources()
    allowed_regions = set(getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS", []))
    selection = select_production_sources(now=now, allowed_regions=allowed_regions)
    triggered: list[dict] = []
    skipped: list[dict] = [
        {"id": item.source.id, "name": item.source.name, "reason": item.reason} for item in selection.skipped
    ]
    failed: list[dict] = []

    for item in selection.selected:
        source = item.source
        major_window = active_major_race_window(source.racing_region, now=now) if source.allow_event_boost else None
        mode = ProductionWindowMode.MAJOR_RACE if major_window else ProductionWindowMode.DAILY
        minutes = (
            int(getattr(settings, "MULTIREGION_CRAWL_MAJOR_RACE_INTERVAL_MINUTES", 5))
            if major_window
            else int(getattr(settings, "MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES", 15))
        )
        scope_key = f"source:{source.id}"
        window_starts = _window_starts_to_run(
            kind=ProductionWindowKind.CRAWL,
            scope_key=scope_key,
            now=now,
            minutes=minutes,
        )
        latest_window_start = window_starts[-1] if window_starts else None
        for window_start in window_starts[:-1]:
            window, created = ProductionWindow.objects.get_or_create(
                kind=ProductionWindowKind.CRAWL,
                scope_key=scope_key,
                window_start=window_start,
                defaults={
                    "mode": mode,
                    "racing_region": source.racing_region,
                    "source": source,
                    "window_end": window_start + timedelta(minutes=minutes),
                    "scheduled_at": now,
                },
            )
            if created or _can_coalesce_old_window(window, now=now):
                window.status = ProductionWindowStatus.SKIPPED
                window.finished_at = timezone.now()
                window.reason_summary = "coalesced_to_latest_crawl_window"
                window.result_payload = {
                    "mode": mode,
                    "coalesced_to_window_start": latest_window_start.isoformat() if latest_window_start else "",
                    "source_reason": item.reason,
                }
                window.save(update_fields=["status", "finished_at", "reason_summary", "result_payload", "updated_at"])
                skipped.append({"id": source.id, "name": source.name, "window_id": window.id, "reason": window.reason_summary})

        for window_start in window_starts[-1:]:
            window, _created = ProductionWindow.objects.get_or_create(
                kind=ProductionWindowKind.CRAWL,
                scope_key=scope_key,
                window_start=window_start,
                defaults={
                    "mode": mode,
                    "racing_region": source.racing_region,
                    "source": source,
                    "window_end": window_start + timedelta(minutes=minutes),
                    "scheduled_at": now,
                },
            )
            claim = claim_window(window, now=now)
            if not claim.claimed:
                skipped.append({"id": source.id, "name": source.name, "window_id": window.id, "reason": claim.reason})
                continue
            try:
                dispatch_result = dispatch_task(crawl_news_source_task, source.id, window.id)
                window = claim.window
                window.refresh_from_db()
                if window.status == ProductionWindowStatus.RUNNING:
                    window.reason_summary = "dispatched"
                    window.result_payload = {
                        "dispatch_result": _json_safe_dispatch_result(dispatch_result),
                        "mode": mode,
                        "source_reason": item.reason,
                    }
                    window.save(update_fields=["reason_summary", "result_payload", "updated_at"])
                triggered.append(
                    {"id": source.id, "name": source.name, "window_id": window.id, "window_start": window_start.isoformat(), "mode": mode}
                )
            except Exception as exc:
                window = ProductionWindow.objects.get(pk=claim.window.pk)
                if window.status != ProductionWindowStatus.FAILED:
                    window.status = ProductionWindowStatus.FAILED
                    window.finished_at = timezone.now()
                    window.reason_summary = "dispatch_failed"
                    window.last_error = str(exc)
                    window.result_payload = {"mode": mode, "source_reason": item.reason}
                    window.save(update_fields=["status", "finished_at", "reason_summary", "last_error", "result_payload", "updated_at"])
                failed.append({"id": source.id, "name": source.name, "window_id": window.id, "error": str(exc)})

    result = {
        "triggered_source_ids": [item["id"] for item in triggered],
        "triggered": triggered,
        "skipped": skipped,
        "failed": failed,
    }
    detail = f"triggered={len(triggered)} skipped={len(skipped)} failed={len(failed)}"
    if failed:
        _log_failure(log, detail)
    else:
        _log_success(log, detail)
    return result


@shared_task
def crawl_enabled_news_sources_task() -> dict:
    log = _log_start("crawl_enabled_news_sources")
    if not getattr(settings, "NEWS_SOURCE_POLL_ENABLED", False):
        _log_success(log, "disabled")
        return {"skipped": True, "reason": "disabled", "triggered_source_ids": []}
    sync_builtin_sources()
    selection = select_due_enabled_news_sources()
    triggered: list[dict] = []
    failed: list[dict] = []
    for item in selection.selected:
        source = item.source
        try:
            dispatch_task(crawl_news_source_task, source.id)
            triggered.append({"id": source.id, "name": source.name, "reason": item.reason})
        except Exception as exc:
            failed.append({"id": source.id, "name": source.name, "error": str(exc)})
    result = {
        "triggered_source_ids": [item["id"] for item in triggered],
        "triggered": triggered,
        "skipped": [{"id": item.source.id, "name": item.source.name, "reason": item.reason} for item in selection.skipped],
        "deferred": [{"id": item.source.id, "name": item.source.name, "reason": item.reason} for item in selection.deferred],
        "deferred_count": selection.deferred_count,
        "failed": failed,
    }
    detail = f"triggered={len(triggered)} skipped={len(selection.skipped)} deferred={selection.deferred_count} failed={len(failed)}"
    if failed:
        _log_failure(log, detail)
    else:
        _log_success(log, detail)
    return result


@shared_task
def discover_term_candidates_task(article_id: int) -> dict:
    log = _log_start("discover_term_candidates", {"article_id": article_id})
    if not getattr(settings, "TERM_DISCOVERY_ENABLED", False):
        _log_success(log, "term discovery disabled")
        return {"article_id": article_id, "skipped": True, "reason": "term discovery disabled"}
    try:
        article = NewsArticle.objects.get(pk=article_id)
        result = discover_and_aggregate_article(article)
        _log_success(log, f"findings={result['finding_count']} candidates={len(result['candidate_ids'])}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def translate_article_task(
    article_id: int,
    preclaimed_retry: bool = False,
    force: bool = False,
    suppress_automation: bool = False,
) -> dict:
    log = _log_start(
        "translate_article",
        {"article_id": article_id, "force": force, "suppress_automation": suppress_automation},
    )
    article = None
    claimed_retry = False
    force_published = False
    previous_automation_status = ""
    try:
        article = NewsArticle.objects.get(pk=article_id)
        force_published = bool(force and article.workflow_status == WorkflowStatus.PUBLISHED)
        previous_automation_status = article.automation_status
        if not preclaimed_retry and article.translation_status == ArticleTranslationStatus.TRANSLATING:
            reason = "translation_already_claimed"
            _log_success(log, f"skipped article={article_id} reason={reason}")
            return {"article_id": article_id, "translated": False, "skipped": True, "reason": reason}
        if preclaimed_retry:
            if (
                article.translation_status != ArticleTranslationStatus.TRANSLATING
                or not article.translation_runs.filter(status=TranslationStatus.STARTED).exists()
            ):
                reason = "preclaimed_retry_state_changed"
                _log_success(log, f"skipped article={article_id} reason={reason}")
                return {"article_id": article_id, "translated": False, "skipped": True, "reason": reason}
            claimed_retry = True
        else:
            expected_due_at = article.translation_next_retry_at
        if (
            not force
            and not preclaimed_retry
            and article.translation_status == ArticleTranslationStatus.FAILED
            and expected_due_at is not None
        ):
            from stable.services.translation_recovery import claim_translation_retry

            claim = claim_translation_retry(article.id, expected_due_at=expected_due_at, now=timezone.now())
            if not claim.claimed:
                _log_success(log, f"skipped article={article_id} reason={claim.reason}")
                return {"article_id": article_id, "translated": False, "skipped": True, "reason": claim.reason}
            claimed_retry = True
            article.refresh_from_db()
        else:
            article.translation_status = ArticleTranslationStatus.TRANSLATING
            article.translation_started_at = timezone.now()
        article.translation_error_message = ""
        article.translation_provider = settings.TRANSLATION_PROVIDER
        article.translation_model = settings.TRANSLATION_MODEL
        article.save(
            update_fields=[
                "translation_status",
                "translation_error_message",
                "translation_started_at",
                "translation_provider",
                "translation_model",
                "updated_at",
            ]
        )
        result = translate_article(article)
        article.apply_translation_result(result, force=force)
        article.status = ArticleStatus.TRANSLATED
        article.translation_status = ArticleTranslationStatus.TRANSLATED
        article.translation_error_message = ""
        article.translation_error_category = ""
        article.translation_next_retry_at = None
        article.translation_retry_exhausted_at = None
        article.translation_started_at = None
        article.translated_at = timezone.now()
        article.translation_model = result.metadata.get("model", "")
        article.translation_provider = result.metadata.get("provider", "")
        if article.workflow_status in {WorkflowStatus.PENDING_TRANSLATION, WorkflowStatus.TRANSLATION_FAILED}:
            article.workflow_status = WorkflowStatus.PENDING_EDIT
        article.automation_status = previous_automation_status if force_published else AutomationStatus.PENDING
        article.translation_metadata = {**article.translation_metadata, **result.metadata}
        if claimed_retry:
            reason = dict(article.decision_reason or {})
            reason["translation_recovery"] = {"recovered_at": timezone.now().isoformat()}
            article.decision_reason = reason
        article.save()
        if getattr(settings, "AUTOMATION_ENABLED", False) and not force_published and not suppress_automation:
            dispatch_task(process_article_automation_task, article.id)
        _log_success(log, f"translated article={article_id}")
        return {
            "article_id": article_id,
            "translated": True,
            "translation_status": article.translation_status,
            "translation_model": article.translation_model,
        }
    except Exception as exc:
        if article is not None:
            article.translation_model = article.translation_model or settings.TRANSLATION_MODEL
            article.translation_provider = article.translation_provider or settings.TRANSLATION_PROVIDER
            article.save(
                update_fields=[
                    "translation_model",
                    "translation_provider",
                    "updated_at",
                ]
            )
            from stable.services.translation_recovery import record_translation_failure

            record_translation_failure(
                article,
                exc,
                now=timezone.now(),
                is_retry=claimed_retry,
                preserve_publication=force_published,
            )
        _log_failure(log, str(exc))
        raise


@shared_task
def translation_retry_selector_task() -> dict:
    from stable.services.translation_recovery import dispatch_due_translation_retries

    result = dispatch_due_translation_retries()
    return {"dispatched_ids": result.dispatched_ids, "skipped_reason": result.skipped_reason}


@shared_task
def recover_stale_translations_task() -> dict:
    from stable.services.translation_recovery import recover_stale_translations

    result = recover_stale_translations()
    return {"recovered_ids": result.recovered_ids}


@shared_task
def process_article_automation_task(article_id: int) -> dict:
    log = _log_start("process_article_automation", {"article_id": article_id})
    if not getattr(settings, "AUTOMATION_ENABLED", False):
        _log_success(log, "automation disabled")
        return {"article_id": article_id, "skipped": True, "reason": "automation disabled"}
    article = NewsArticle.objects.get(pk=article_id)
    try:
        score_article_task.run(article.id)
        article.refresh_from_db()
        if article.automation_status == AutomationStatus.REWRITE_READY and article.review_mode == ReviewMode.AUTO:
            if automation_content_source() == "rewrite":
                rewrite_article_task.run(article.id)
            else:
                prepare_base_translation_for_publish(article)
                validate_rewrite_task.run(article.id)
            article.refresh_from_db()
        if article.automation_status == AutomationStatus.REWRITTEN and article.review_mode == ReviewMode.AUTO:
            validate_rewrite_task.run(article.id)
            article.refresh_from_db()
        send_high_value_warning_notification(article)
        payload = important_manual_notification_payload(article)
        if payload:
            send_notification_task.run(NotificationType.IMPORTANT_MANUAL, payload)
        _log_success(log, f"automation_status={article.automation_status} review_mode={article.review_mode}")
        return {
            "article_id": article.id,
            "automation_status": article.automation_status,
            "review_mode": article.review_mode,
            "score_total": article.score_total,
        }
    except Exception as exc:
        mark_automation_failed(article, phase=AutomationPhase.SCORE, error=exc)
        send_notification_task.run(
            NotificationType.REPEATED_FAILURE,
            {"article_id": article.id, "title": article.effective_title, "error": str(exc)},
        )
        _log_failure(log, str(exc))
        raise


@shared_task
def score_article_task(article_id: int) -> dict:
    log = _log_start("score_article", {"article_id": article_id})
    article = NewsArticle.objects.get(pk=article_id)
    try:
        from stable.services.news_attribution import ATTRIBUTION_RULE_VERSION

        applied_summary = (article.attribution_summary or {}).get("applied") or {}
        apply_article_attribution(
            article,
            is_new_article=applied_summary.get("rule_version") == ATTRIBUTION_RULE_VERSION,
        )
        article.refresh_from_db()
        decision = score_article_for_automation(article)
        apply_score_decision(article, decision)
        _log_success(log, decision.decision_summary)
        return {
            "article_id": article.id,
            "review_mode": decision.review_mode,
            "automation_status": decision.automation_status,
            "score_total": decision.score_total,
        }
    except Exception as exc:
        mark_automation_failed(article, phase=AutomationPhase.SCORE, error=exc)
        _log_failure(log, str(exc))
        raise


@shared_task
def rewrite_article_task(article_id: int) -> dict:
    log = _log_start("rewrite_article", {"article_id": article_id})
    article = NewsArticle.objects.get(pk=article_id)
    if article.review_mode != ReviewMode.AUTO:
        _log_success(log, "skipped non-auto article")
        return {"article_id": article.id, "skipped": True}
    try:
        result = rewrite_article(article)
        apply_rewrite_result(article, result)
        _log_success(log, f"confidence={result.confidence}")
        return {"article_id": article.id, "rewritten": True, "confidence": result.confidence}
    except Exception as exc:
        mark_automation_failed(article, phase=AutomationPhase.REWRITE, error=exc)
        send_notification_task.run(
            NotificationType.REWRITE_FAILED,
            {"article_id": article.id, "title": article.effective_title, "error": str(exc), "source_url": article.source_url},
        )
        _log_failure(log, str(exc))
        raise


@shared_task
def validate_rewrite_task(article_id: int) -> dict:
    log = _log_start("validate_rewrite", {"article_id": article_id})
    article = NewsArticle.objects.get(pk=article_id)
    try:
        outcome = validate_rewrite(article)
        apply_validation_outcome(article, outcome)
        _log_success(log, outcome.reason)
        return {"article_id": article.id, "validated": outcome.passed, "reason": outcome.reason}
    except Exception as exc:
        mark_automation_failed(article, phase=AutomationPhase.VALIDATE, error=exc)
        _log_failure(log, str(exc))
        raise


def _resolve_auto_publish_batch_limit(limit: int | None = None, now=None) -> int:
    if limit is not None:
        return max(0, int(limit))
    base_limit = int(getattr(settings, "AUTO_PUBLISH_BATCH_LIMIT", 4))
    peak_limit = int(getattr(settings, "AUTO_PUBLISH_PEAK_BATCH_LIMIT", 10))
    peak_day = int(getattr(settings, "AUTO_PUBLISH_PEAK_DAY_OF_WEEK", 6))
    peak_start = int(getattr(settings, "AUTO_PUBLISH_PEAK_START_HOUR", 13))
    peak_end = int(getattr(settings, "AUTO_PUBLISH_PEAK_END_HOUR", 16))
    local_now = timezone.localtime(now or timezone.now())
    if local_now.weekday() == peak_day and peak_start <= local_now.hour < peak_end:
        return max(0, peak_limit)
    return max(0, base_limit)


@shared_task
def publish_region_window_task(region: str, now_iso: str | None = None) -> dict:
    log = _log_start("publish_region_window", {"region": region, "now_iso": now_iso})
    if (
        not getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_ENABLED", False)
        or not getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED", False)
        or getattr(settings, "MULTIREGION_ROLLBACK_DISABLE_PUBLISH_WINDOWS", False)
    ):
        _log_success(log, "disabled")
        return {"skipped": True, "reason": "disabled", "published_article_ids": []}

    now = _parse_task_now(now_iso)
    major_window = active_major_race_window(region, now=now)
    mode = ProductionWindowMode.MAJOR_RACE if major_window else ProductionWindowMode.DAILY
    minutes = (
        int(getattr(settings, "MULTIREGION_PRODUCTION_WINDOW_MAJOR_RACE_MINUTES", 5))
        if major_window
        else int(getattr(settings, "MULTIREGION_PRODUCTION_WINDOW_DAILY_MINUTES", 15))
    )
    scope_key = f"region:{region}"
    window_ids: list[int] = []
    published_ids: list[int] = []
    failed_ids: list[int] = []
    skipped_windows: list[dict] = []
    failed_windows: list[dict] = []
    zero_reasons: list[str] = []

    for window_start in _window_starts_to_run(
        kind=ProductionWindowKind.PUBLISH,
        scope_key=scope_key,
        now=now,
        minutes=minutes,
    ):
        window, _created = ProductionWindow.objects.get_or_create(
            kind=ProductionWindowKind.PUBLISH,
            scope_key=scope_key,
            window_start=window_start,
            defaults={
                "mode": mode,
                "racing_region": region,
                "window_end": window_start + timedelta(minutes=minutes),
                "scheduled_at": now,
            },
        )
        claim = claim_window(window, now=now)
        if not claim.claimed:
            skipped_windows.append({"window_id": window.id, "window_start": window_start.isoformat(), "reason": claim.reason})
            continue

        window = claim.window
        window_ids.append(window.id)
        try:
            selection = select_publish_candidates(region, window=window, now=window.window_end)
            window_published_ids: list[int] = []
            window_failed_ids: list[int] = []
            for article in selection.selected:
                try:
                    publish_article_automatically(article)
                    dispatch_task(scan_article_horse_links_task, article_id=article.id, commit=True)
                    window_published_ids.append(article.id)
                except Exception:
                    window_failed_ids.append(article.id)
            published_ids.extend(window_published_ids)
            failed_ids.extend(window_failed_ids)
            zero_reasons.extend(selection.zero_reasons)
            window.status = ProductionWindowStatus.PARTIAL if window_failed_ids else ProductionWindowStatus.SUCCEEDED
            window.finished_at = timezone.now()
            window.reason_summary = "published" if window_published_ids else ",".join(selection.zero_reasons or ["no_published_articles"])
            window.result_payload = {
                "published_article_ids": window_published_ids,
                "failed_article_ids": window_failed_ids,
                "zero_reasons": selection.zero_reasons,
                "mode": mode,
            }
            window.save(update_fields=["status", "finished_at", "reason_summary", "result_payload", "updated_at"])
        except Exception as exc:
            window.status = ProductionWindowStatus.FAILED
            window.finished_at = timezone.now()
            window.reason_summary = "publish_window_failed"
            window.last_error = str(exc)
            window.save(update_fields=["status", "finished_at", "reason_summary", "last_error", "updated_at"])
            failed_windows.append({"window_id": window.id, "window_start": window_start.isoformat(), "error": str(exc)})

    detail = f"region={region} windows={len(window_ids)} published={len(published_ids)} failed={len(failed_ids)}"
    if failed_ids or failed_windows:
        _log_failure(log, detail)
    else:
        _log_success(log, detail)
    return {
        "region": region,
        "window_id": window_ids[-1] if window_ids else None,
        "window_ids": window_ids,
        "published_article_ids": published_ids,
        "failed_article_ids": failed_ids,
        "zero_reasons": list(dict.fromkeys(zero_reasons)),
        "skipped_windows": skipped_windows,
        "failed_windows": failed_windows,
    }


@shared_task
def publish_production_regions_window_task(now_iso: str | None = None) -> dict:
    log = _log_start("publish_production_regions_window", {"now_iso": now_iso})
    if (
        not getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_ENABLED", False)
        or not getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED", False)
        or getattr(settings, "MULTIREGION_ROLLBACK_DISABLE_PUBLISH_WINDOWS", False)
    ):
        _log_success(log, "disabled")
        return {"skipped": True, "reason": "disabled", "triggered_regions": []}
    regions = list(getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS", [])) or [
        RacingRegion.JAPAN,
        RacingRegion.HONG_KONG,
        RacingRegion.UNITED_KINGDOM,
        RacingRegion.FRANCE,
        RacingRegion.UNITED_STATES,
    ]
    triggered: list[str] = []
    failed: list[dict] = []
    for region in regions:
        try:
            dispatch_task(publish_region_window_task, region, now_iso=now_iso)
            triggered.append(region)
        except Exception as exc:
            failed.append({"region": region, "error": str(exc)})
    detail = f"triggered={len(triggered)} failed={len(failed)}"
    if failed:
        _log_failure(log, detail)
    else:
        _log_success(log, detail)
    return {"triggered_regions": triggered, "failed": failed}


@shared_task
def auto_publish_batch_task(limit: int | None = None) -> dict:
    log = _log_start("auto_publish_batch", {"limit": limit})
    if (
        getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_ENABLED", False)
        and getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED", False)
    ):
        _log_success(log, "multiregion windows enabled")
        return {"published_count": 0, "skipped": True, "reason": "multiregion_windows_enabled"}
    if not getattr(settings, "AUTOMATION_ENABLED", False):
        _log_success(log, "automation disabled")
        return {"published_count": 0, "skipped": True}
    batch_limit = _resolve_auto_publish_batch_limit(limit)
    queryset = (
        NewsArticle.objects.filter(review_mode=ReviewMode.AUTO, automation_status=AutomationStatus.PUBLISH_READY)
        .exclude(workflow_status__in=[WorkflowStatus.PUBLISHED, WorkflowStatus.WITHDRAWN, WorkflowStatus.IGNORED, WorkflowStatus.DUPLICATE])
        .order_by("-score_total", "-published_at", "-id")
    )
    published_ids: list[int] = []
    failed_ids: list[int] = []
    skipped_reasons: dict[int, str] = {}
    region_run_counts: dict[str, int] = {}
    candidate_limit = max(batch_limit * 8, batch_limit + 20, 50)
    scan_limit = max(candidate_limit * 4, batch_limit + 100, 200)
    scanned_count = 0
    scanned_ids: set[int] = set()
    limit_skip_seen = False

    def process_candidate(article: NewsArticle) -> None:
        nonlocal limit_skip_seen
        try:
            policy = auto_publish_policy_for_article(article)
            if not policy.allowed:
                skipped_reasons[article.id] = policy.reason
                if policy.reason in {"region_not_allowed", "source_not_allowed", "term_candidate_backlog"}:
                    article.review_mode = ReviewMode.MANUAL
                    article.automation_status = AutomationStatus.MANUAL_REVIEW_REQUIRED
                    article.workflow_status = WorkflowStatus.PENDING_REVIEW
                    article.decision_summary = f"转人工：多地区自动发布策略未放行（{policy.reason}）"
                    article.decision_reason = {**(article.decision_reason or {}), "publish_policy": policy.as_dict()}
                    article.save(
                        update_fields=[
                            "review_mode",
                            "automation_status",
                            "workflow_status",
                            "decision_summary",
                            "decision_reason",
                            "updated_at",
                        ]
                    )
                return
            region = policy.region
            if policy.per_run_limit is not None and region_run_counts.get(region, 0) >= policy.per_run_limit:
                skipped_reasons[article.id] = "batch_limit_reached"
                limit_skip_seen = True
                return
            if policy.daily_limit is not None and auto_publish_count_today(region) >= policy.daily_limit:
                skipped_reasons[article.id] = "daily_limit_reached"
                limit_skip_seen = True
                return
            if not is_ready_for_auto_publish(article):
                return
            publish_article_automatically(article)
            dispatch_task(scan_article_horse_links_task, article_id=article.id, commit=True)
            published_ids.append(article.id)
            region_run_counts[region] = region_run_counts.get(region, 0) + 1
        except Exception as exc:
            failed_ids.append(article.id)
            mark_automation_failed(article, phase=AutomationPhase.PUBLISH, error=exc)
            send_notification_task.run(
                NotificationType.PUBLISH_FAILED,
                {"article_id": article.id, "title": article.effective_title, "error": str(exc)},
            )
    for article in queryset[:scan_limit]:
        if len(published_ids) >= batch_limit:
            break
        scanned_count += 1
        scanned_ids.add(article.id)
        process_candidate(article)
    if len(published_ids) < batch_limit and limit_skip_seen:
        fallback_limit = max((batch_limit - len(published_ids)) * 5, 20)
        fallback_queryset = queryset.filter(racing_region=RacingRegion.JAPAN).exclude(pk__in=scanned_ids)
        for article in fallback_queryset[:fallback_limit]:
            if len(published_ids) >= batch_limit:
                break
            scanned_count += 1
            scanned_ids.add(article.id)
            process_candidate(article)
    detail = f"published={len(published_ids)} failed={len(failed_ids)}"
    if failed_ids:
        _log_failure(log, detail)
    else:
        _log_success(log, detail)
    return {
        "published_count": len(published_ids),
        "batch_limit": batch_limit,
        "scanned_count": scanned_count,
        "published_ids": published_ids,
        "failed_ids": failed_ids,
        "skipped_reasons": skipped_reasons,
    }


def _recent_notification_exists(
    notification_type: str,
    hours: int = 6,
    *,
    summary_contains: str = "",
) -> bool:
    since = timezone.now() - timedelta(hours=hours)
    queryset = NotificationLog.objects.filter(type=notification_type, created_at__gte=since)
    if summary_contains:
        queryset = queryset.filter(payload_summary__icontains=summary_contains)
    return queryset.exists()


@shared_task
def send_notification_task(notification_type: str, payload: dict) -> dict:
    logs = send_automation_notification(notification_type, payload)
    return {"notification_type": notification_type, "log_ids": [log.id for log in logs]}


@shared_task
def detect_automation_anomalies_task() -> dict:
    log = _log_start("detect_automation_anomalies")
    sent: list[str] = []
    now = timezone.now()
    rolling_source_health = region_source_health_summary(
        NewsSource.objects.filter(deleted_at__isnull=True),
        now=now,
        stale_minutes=max(1, int(getattr(settings, "CRAWL_JOB_STALE_MINUTES", 60))),
        short_window_hours=getattr(settings, "NEWS_SOURCE_HEALTH_SHORT_WINDOW_HOURS", 2),
        long_window_hours=getattr(settings, "NEWS_SOURCE_HEALTH_LONG_WINDOW_HOURS", 24),
    )
    index_error = rolling_source_health["index_error"]
    if not index_error["active"]:
        index_error = task_execution_index_error_snapshot(
            now=now,
            window_hours=getattr(settings, "NEWS_SOURCE_HEALTH_SHORT_WINDOW_HOURS", 2),
        )
    if index_error["active"] and not _recent_notification_exists(
        NotificationType.OPS_ANOMALY,
        hours=max(1, int(getattr(settings, "NEWS_INDEX_P0_COOLDOWN_HOURS", 6))),
        summary_contains="news_index_physical_error",
    ):
        send_notification_task.run(
            NotificationType.OPS_ANOMALY,
            {
                "severity": "p0",
                "reason": "news_index_physical_error",
                "index_name": index_error["index_name"]
                or getattr(
                    settings,
                    "NEWS_PRODUCTION_INDEX_NAME",
                    "stable_newsarticle_public_slug_46694cb6",
                ),
                "count": index_error["count"],
                "first_at": index_error["first_at"].isoformat() if index_error["first_at"] else "",
                "last_at": index_error["last_at"].isoformat() if index_error["last_at"] else "",
            },
        )
        sent.append(NotificationType.OPS_ANOMALY)

    if not getattr(settings, "AUTOMATION_ENABLED", False):
        _log_success(log, f"automation disabled; notifications={len(sent)}")
        return {"skipped": True, "notifications": sent}

    stale_sources = []
    for source in NewsSource.objects.filter(enabled=True, deleted_at__isnull=True):
        if not source.last_crawl_at:
            continue
        stale_minutes = max(source.crawl_interval_minutes * 3, 180)
        if source.last_crawl_at < now - timedelta(minutes=stale_minutes):
            stale_sources.append(source.name)
    if stale_sources and not _recent_notification_exists(NotificationType.STALE_SOURCE):
        send_notification_task.run(NotificationType.STALE_SOURCE, {"source": ", ".join(stale_sources)})
        sent.append(NotificationType.STALE_SOURCE)

    backlog_count = NewsArticle.objects.filter(automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED).count()
    if backlog_count >= 50 and not _recent_notification_exists(NotificationType.BACKLOG):
        send_notification_task.run(NotificationType.BACKLOG, {"manual_review_count": backlog_count})
        sent.append(NotificationType.BACKLOG)

    last_day_auto = NewsArticle.objects.filter(auto_publish_at__gte=now - timedelta(hours=24)).exists()
    has_publish_ready = NewsArticle.objects.filter(automation_status=AutomationStatus.PUBLISH_READY).exists()
    if not last_day_auto and has_publish_ready and not _recent_notification_exists(NotificationType.NO_AUTO_PUBLISH_24H):
        send_notification_task.run(NotificationType.NO_AUTO_PUBLISH_24H, {"publish_ready_count": has_publish_ready})
        sent.append(NotificationType.NO_AUTO_PUBLISH_24H)

    recent_failures = TaskExecutionLog.objects.filter(status=TaskStatus.FAILED, started_at__gte=now - timedelta(hours=2)).count()
    if recent_failures >= 3 and not _recent_notification_exists(NotificationType.REPEATED_FAILURE):
        send_notification_task.run(NotificationType.REPEATED_FAILURE, {"failed_task_count": recent_failures})
        sent.append(NotificationType.REPEATED_FAILURE)
    _log_success(log, f"notifications={','.join(sent) or 'none'}")
    return {"notifications": sent}


@shared_task
def import_external_horse_data_task(
    *,
    year: int | None = None,
    month: int | None = None,
    race_id: str = "",
    horse_id: str = "",
    horse_name: str = "",
    allow_network: bool = False,
    max_races: int | None = None,
    max_horses: int | None = None,
    fetch_odds: bool | None = None,
    fetch_horse_detail: bool | None = None,
) -> dict:
    log = _log_start(
        "import_external_horse_data",
        {"year": year, "month": month, "race_id": race_id, "horse_id": horse_id, "allow_network": allow_network},
    )
    importer = ExternalHorseDataImporter(
        ImportOptions.from_settings(
            allow_network=allow_network,
            max_races=max_races,
            max_horses=max_horses,
            fetch_odds=fetch_odds,
            fetch_horse_detail=fetch_horse_detail,
        )
    )
    try:
        if race_id:
            result = importer.import_race(race_id)
        elif horse_id:
            result = importer.import_horse(horse_id, horse_name=horse_name)
        elif year and month:
            result = importer.import_month(year, month)
        else:
            result = importer.import_default()
        _log_success(log, f"status={result.get('status')} run_id={result.get('run_id')}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def batch_translate_articles_task(article_ids: list[int] | None = None, limit: int = 50) -> dict:
    log = _log_start("batch_translate_articles", {"article_ids": article_ids or [], "limit": limit})
    queryset = NewsArticle.objects.all().order_by("-published_at", "-id")
    if article_ids:
        queryset = queryset.filter(pk__in=article_ids)
    else:
        queryset = queryset.filter(
            workflow_status__in=[WorkflowStatus.PENDING_TRANSLATION, WorkflowStatus.TRANSLATION_FAILED]
        )
    article_ids_to_process = list(queryset.values_list("id", flat=True)[:limit])
    translated_count = 0
    failed_count = 0
    for article_id in article_ids_to_process:
        try:
            translate_article_task.run(article_id)
            translated_count += 1
        except Exception:
            failed_count += 1
    detail = f"processed={len(article_ids_to_process)} translated={translated_count} failed={failed_count}"
    if failed_count:
        _log_failure(log, detail)
    else:
        _log_success(log, detail)
    return {
        "processed": len(article_ids_to_process),
        "translated_count": translated_count,
        "failed_count": failed_count,
        "article_ids": article_ids_to_process,
    }


@shared_task
def push_article_task(article_id: int, target_ids: list[int], user_id: int | None = None) -> dict:
    log = _log_start("push_article", {"article_id": article_id, "target_ids": target_ids})
    try:
        article = NewsArticle.objects.get(pk=article_id)
        targets = list(PushTarget.objects.filter(pk__in=target_ids, is_active=True))
        user = User.objects.filter(pk=user_id).first() if user_id else None
        push_article_to_targets(article, targets, user)
        _log_success(log, f"pushed article={article_id} to {len(targets)} target(s)")
        return {"article_id": article_id, "target_count": len(targets)}
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task
def qq_region_window_task(region: str, now_iso: str | None = None) -> dict:
    log = _log_start("qq_region_window", {"region": region, "now_iso": now_iso})
    if (
        not getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_ENABLED", False)
        or not getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED", False)
        or getattr(settings, "MULTIREGION_ROLLBACK_DISABLE_QQ_WINDOWS", False)
        or not getattr(settings, "QQ_PUSH_ENABLED", False)
    ):
        _log_success(log, "disabled")
        return {"skipped": True, "reason": "disabled", "delivery_ids": []}

    now = _parse_task_now(now_iso)
    major_window = active_major_race_window(region, now=now)
    mode = ProductionWindowMode.MAJOR_RACE if major_window else ProductionWindowMode.DAILY
    minutes = (
        int(getattr(settings, "MULTIREGION_PRODUCTION_WINDOW_MAJOR_RACE_MINUTES", 5))
        if major_window
        else int(getattr(settings, "MULTIREGION_PRODUCTION_WINDOW_DAILY_MINUTES", 15))
    )
    scope_key = f"region:{region}:qq"
    window_ids: list[int] = []
    delivery_ids: list[int] = []
    failed_delivery_ids: list[int] = []
    skipped_windows: list[dict] = []
    failed_windows: list[dict] = []
    zero_reasons: list[str] = []

    window_starts = _window_starts_to_run(
        kind=ProductionWindowKind.QQ_PUSH,
        scope_key=scope_key,
        now=now,
        minutes=minutes,
    )
    latest_window_start = window_starts[-1] if window_starts else None
    for window_start in window_starts[:-1]:
        window, created = ProductionWindow.objects.get_or_create(
            kind=ProductionWindowKind.QQ_PUSH,
            scope_key=scope_key,
            window_start=window_start,
            defaults={
                "mode": mode,
                "racing_region": region,
                "window_end": window_start + timedelta(minutes=minutes),
                "scheduled_at": now,
            },
        )
        if created or _can_coalesce_old_window(window, now=now):
            window.status = ProductionWindowStatus.SKIPPED
            window.finished_at = timezone.now()
            window.reason_summary = "coalesced_to_latest_qq_window"
            window.result_payload = {
                "mode": mode,
                "coalesced_to_window_start": latest_window_start.isoformat() if latest_window_start else "",
            }
            window.save(update_fields=["status", "finished_at", "reason_summary", "result_payload", "updated_at"])
            skipped_windows.append(
                {
                    "window_id": window.id,
                    "window_start": window_start.isoformat(),
                    "reason": window.reason_summary,
                }
            )

    for window_start in window_starts[-1:]:
        window, _created = ProductionWindow.objects.get_or_create(
            kind=ProductionWindowKind.QQ_PUSH,
            scope_key=scope_key,
            window_start=window_start,
            defaults={
                "mode": mode,
                "racing_region": region,
                "window_end": window_start + timedelta(minutes=minutes),
                "scheduled_at": now,
            },
        )
        claim = claim_window(window, now=now)
        if not claim.claimed:
            skipped_windows.append({"window_id": window.id, "window_start": window_start.isoformat(), "reason": claim.reason})
            continue

        window = claim.window
        window_ids.append(window.id)
        try:
            online, status_error = BotPusher().is_online()
            if not online:
                reason = status_error or "onebot_offline"
                zero_reasons.append(reason)
                window.status = ProductionWindowStatus.FAILED
                window.finished_at = timezone.now()
                window.reason_summary = reason
                window.last_error = reason
                window.result_payload = {
                    "delivery_ids": [],
                    "failed_delivery_ids": [],
                    "zero_reasons": [reason],
                    "mode": mode,
                    "onebot_online": False,
                }
                window.save(update_fields=["status", "finished_at", "reason_summary", "last_error", "result_payload", "updated_at"])
                failed_windows.append({"window_id": window.id, "window_start": window_start.isoformat(), "error": reason})
                continue
            result = select_qq_window_deliveries(region, window=window, now=window.window_end)
            window_delivery_ids: list[int] = []
            window_failed_delivery_ids: list[int] = []
            for delivery in result.deliveries:
                try:
                    dispatch_task(qq_push_delivery_task, delivery.id)
                    window_delivery_ids.append(delivery.id)
                except Exception:
                    window_failed_delivery_ids.append(delivery.id)
            delivery_ids.extend(window_delivery_ids)
            failed_delivery_ids.extend(window_failed_delivery_ids)
            zero_reasons.extend(result.zero_reasons)
            window.status = ProductionWindowStatus.PARTIAL if window_failed_delivery_ids else ProductionWindowStatus.SUCCEEDED
            window.finished_at = timezone.now()
            window.reason_summary = "queued" if window_delivery_ids else ",".join(result.zero_reasons or ["no_deliveries"])
            window.result_payload = {
                "delivery_ids": window_delivery_ids,
                "failed_delivery_ids": window_failed_delivery_ids,
                "zero_reasons": result.zero_reasons,
                "mode": mode,
            }
            window.save(update_fields=["status", "finished_at", "reason_summary", "result_payload", "updated_at"])
        except Exception as exc:
            window.status = ProductionWindowStatus.FAILED
            window.finished_at = timezone.now()
            window.reason_summary = "qq_window_failed"
            window.last_error = str(exc)
            window.save(update_fields=["status", "finished_at", "reason_summary", "last_error", "updated_at"])
            failed_windows.append({"window_id": window.id, "window_start": window_start.isoformat(), "error": str(exc)})

    detail = f"region={region} windows={len(window_ids)} queued={len(delivery_ids)} failed={len(failed_delivery_ids)}"
    if failed_delivery_ids or failed_windows:
        _log_failure(log, detail)
    else:
        _log_success(log, detail)
    return {
        "region": region,
        "window_id": window_ids[-1] if window_ids else None,
        "window_ids": window_ids,
        "delivery_ids": delivery_ids,
        "failed_delivery_ids": failed_delivery_ids,
        "zero_reasons": list(dict.fromkeys(zero_reasons)),
        "skipped_windows": skipped_windows,
        "failed_windows": failed_windows,
    }


@shared_task
def qq_production_regions_window_task(now_iso: str | None = None) -> dict:
    log = _log_start("qq_production_regions_window", {"now_iso": now_iso})
    if (
        not getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_ENABLED", False)
        or not getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED", False)
        or getattr(settings, "MULTIREGION_ROLLBACK_DISABLE_QQ_WINDOWS", False)
        or not getattr(settings, "QQ_PUSH_ENABLED", False)
    ):
        _log_success(log, "disabled")
        return {"skipped": True, "reason": "disabled", "triggered_regions": []}
    regions = list(getattr(settings, "MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS", [])) or [
        RacingRegion.JAPAN,
        RacingRegion.HONG_KONG,
        RacingRegion.UNITED_KINGDOM,
        RacingRegion.FRANCE,
        RacingRegion.UNITED_STATES,
    ]
    triggered: list[str] = []
    failed: list[dict] = []
    for region in regions:
        try:
            dispatch_task(qq_region_window_task, region, now_iso=now_iso)
            triggered.append(region)
        except Exception as exc:
            failed.append({"region": region, "error": str(exc)})
    detail = f"triggered={len(triggered)} failed={len(failed)}"
    if failed:
        _log_failure(log, detail)
    else:
        _log_success(log, detail)
    return {"triggered_regions": triggered, "failed": failed}


@shared_task
def production_summary_task() -> dict:
    log = _log_start("production_summary")
    payload = summarize_multiregion_news_production()
    send_production_summary_notification(payload)
    _log_success(log, "production summary generated")
    return payload


@shared_task
def notify_p0_horse_identity_conflicts_task() -> dict:
    log = _log_start("notify_p0_horse_identity_conflicts")
    conflicts = HorseIdentityConflict.objects.filter(status=HorseIdentityConflictStatus.PENDING)
    conflict_count = conflicts.count()
    if conflict_count:
        conflict_ids = list(conflicts.values_list("id", flat=True)[:50])
        send_ops_notification(
            notification_type=NotificationType.OPS_ANOMALY,
            title="UmaFans P0 马名歧义待处理",
            payload={
                "conflict_count": conflict_count,
                "conflict_ids": conflict_ids,
                "admin_url": (
                    f"{settings.DJANGO_ADMIN_URL}stable/horseidentityconflict/"
                    "?status__exact=pending"
                ),
            },
        )
    _log_success(log, f"conflicts={conflict_count}")
    return {"conflict_count": conflict_count}


def _qq_push_retry_countdown(attempt_count: int) -> int:
    return min(300, max(30, attempt_count * 60))


@shared_task
def qq_auto_push_article_task(article_id: int) -> dict:
    log = _log_start("qq_auto_push_article", {"article_id": article_id})
    if not getattr(settings, "QQ_PUSH_ENABLED", False):
        _log_success(log, "qq push disabled")
        return {"article_id": article_id, "skipped": True, "reason": "disabled"}
    try:
        article = NewsArticle.objects.get(pk=article_id)
        eligibility = should_push_news_to_qq(article, scope="all_public")
        if not eligibility.allowed:
            _log_success(log, f"skipped: {eligibility.reason}")
            return {"article_id": article_id, "skipped": True, "reason": eligibility.reason}
        targets = get_auto_push_targets()
        if not targets:
            _log_success(log, "skipped: no active targets")
            return {"article_id": article_id, "skipped": True, "reason": "no_targets"}
        eligible_targets = []
        target_skip_reasons: dict[str, str] = {}
        for target in targets:
            target_eligibility = should_push_news_to_qq(article, target=target)
            if target_eligibility.allowed:
                eligible_targets.append(target)
            else:
                target_skip_reasons[str(target.id)] = target_eligibility.reason or "not_eligible"
        deliveries = ensure_qq_push_deliveries(article, eligible_targets)
        queued_ids: list[int] = []
        skipped_ids: list[int] = []
        for delivery in deliveries:
            if delivery.status == QQPushDeliveryStatus.SENT:
                skipped_ids.append(delivery.id)
                continue
            qq_push_delivery_task.delay(delivery.id)
            queued_ids.append(delivery.id)
        _log_success(log, f"queued={len(queued_ids)} already_sent={len(skipped_ids)} target_skipped={len(target_skip_reasons)}")
        return {
            "article_id": article_id,
            "queued_delivery_ids": queued_ids,
            "already_sent_delivery_ids": skipped_ids,
            "target_skip_reasons": target_skip_reasons,
        }
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


@shared_task(bind=True)
def qq_push_delivery_task(self, delivery_id: int) -> dict:
    log = _log_start("qq_push_delivery", {"delivery_id": delivery_id})
    try:
        delivery = QQPushDelivery.objects.select_related("article", "target").get(pk=delivery_id)
        throttle_delay = qq_push_next_attempt_delay(delivery)
        if throttle_delay > 0 and not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            self.apply_async(args=(delivery_id,), countdown=throttle_delay)
            result = {
                "delivery_id": delivery.id,
                "status": delivery.status,
                "attempt_count": delivery.attempt_count,
                "last_error_type": delivery.last_error_type,
                "throttle_delay_seconds": throttle_delay,
            }
            _log_success(log, f"rate limited: retry in {throttle_delay}s")
            return result
        delivery = process_qq_push_delivery(delivery)
        result = {
            "delivery_id": delivery.id,
            "status": delivery.status,
            "attempt_count": delivery.attempt_count,
            "last_error_type": delivery.last_error_type,
        }
        if delivery.status == QQPushDeliveryStatus.RETRYING and delivery.attempt_count < delivery.max_attempts:
            if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
                self.apply_async(args=(delivery_id,), countdown=_qq_push_retry_countdown(delivery.attempt_count))
            _log_success(log, f"retry scheduled: {delivery.last_error_type}")
            return result
        if delivery.status == QQPushDeliveryStatus.FAILED:
            _log_failure(log, delivery.last_error or "qq push delivery failed")
            return result
        _log_success(log, f"status={delivery.status}")
        return result
    except Exception as exc:
        _log_failure(log, str(exc))
        raise


def publish_article(article: NewsArticle, user) -> None:
    article.workflow_status = WorkflowStatus.PUBLISHED
    article.published_to_web_at = timezone.now()
    article.published_by = user
    article.published_by_mode = PublishedByMode.MANUAL
    article.save(update_fields=["workflow_status", "published_to_web_at", "published_by", "published_by_mode", "updated_at"])
    from stable.services.qq_auto_push import enqueue_qq_auto_push_for_article

    enqueue_qq_auto_push_for_article(article.id)
    dispatch_task(scan_article_horse_links_task, article_id=article.id, commit=True)
    log_operation(
        action_type="article_published",
        target_type="article",
        target_id=article.pk,
        detail=f"发布文章《{article.effective_title}》",
        admin=user,
    )

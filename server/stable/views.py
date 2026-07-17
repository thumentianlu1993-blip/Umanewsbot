from __future__ import annotations

import json
import math
import re
import unicodedata
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.core.signing import BadSignature, SignatureExpired
from django.db import transaction
from django.db.models import Count, F, Q
from django.db.models.functions import Lower
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .forms import (
    ArticleEditorForm,
    ArticleQuickTermForm,
    BackendAuthenticationForm,
    HorseArticleLinkForm,
    HorseProfileForm,
    HorseRaceRecordForm,
    NewsSourceForm,
    RaceEventForm,
    TermCandidateAcceptForm,
    TermCandidateMergeForm,
    TermCandidateReviewForm,
    TermEntryForm,
    TermImportForm,
)
from .models import (
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    ArticleRaceLinkType,
    ArticleHorseLink,
    ArticleHorseLinkStatus,
    AutomationLog,
    AutomationStatus,
    ArticleTranslationStatus,
    CrawlJob,
    HistoricalRaceResolutionStatus,
    HorseFollow,
    HorseP0SourceStatus,
    HorseP0SourceType,
    HorseProfile,
    HorseProfileCandidateStatus,
    HorseProfileCompleteness,
    HorseProfileDataCandidate,
    HorseProfileStatus,
    HorseRaceLink,
    HorseRaceRecord,
    HorseRaceResultStatus,
    MediaAsset,
    NewsArticle,
    NewsImage,
    NewsSnapshot,
    NewsSource,
    NotificationLog,
    OperationLog,
    PublishedByMode,
    ProductionWindow,
    ProductionWindowKind,
    ProductionWindowStatus,
    PushTarget,
    QuotaLedger,
    QuotaLedgerKind,
    RaceEvent,
    RaceEventCandidateStatus,
    RaceEventDataCandidate,
    RaceEventDataQuality,
    RaceEventHistoryWinner,
    RaceEventPriority,
    RaceEventResult,
    RaceRunnerStatus,
    RaceEventStatus,
    RaceEventVisibility,
    RacingRegion,
    ReviewMode,
    SourceLanguage,
    SourceMode,
    TaskExecutionLog,
    TaskStatus,
    TermCandidate,
    TermCandidateStatus,
    TermAlias,
    TermEntry,
    TermTranslationStatus,
    TermType,
    WindowCandidateDecision,
    WindowTargetDecision,
    WorkflowStatus,
)
from .services.horse_profiles import (
    FOLLOW_COOKIE_NAME,
    apply_data_candidate as apply_horse_data_candidate,
    follow_horse,
    followed_articles,
    major_win_records,
    scan_article_horse_links,
    set_follow_cookie,
    signed_follow_token,
    token_hash_from_cookie,
    token_hash_from_raw,
    transition_review_status,
    unfollow_horse,
    update_completeness,
)
from .services.horse_race_records import upsert_race_record
from .services.media_assets import localize_news_image, set_cover_asset
from .services.multiregion import PRODUCTION_REGIONS, region_production_rows
from .services.onebot import BotPusher
from .services.operations import log_operation
from .services.race_event_public_cache import (
    public_race_calendar_years,
    public_race_sitemap_count,
)
from .services.news_attribution import filter_articles_visible_in_region
from .services.production_windows import claim_window
from .services.p0_horse_profiles import active_record_freshness_cutoff
from .services.publishing_windows import select_publish_candidates
from .services.pushing import enqueue_push_for_article
from .services.qq_windows import select_qq_window_deliveries
from .services.queueing import dispatch_task
from .services.race_events import (
    apply_data_candidate,
    associate_articles_for_event,
    confirm_article_link,
    remove_article_link,
    resolve_race_live_public_read,
    resolve_race_live_public_reads,
)
from .services.sources import sync_builtin_sources
from .services.storage import current_media_provider
from .services.term_admin import (
    commit_term_import,
    find_term_by_source_alias,
    preview_from_session_value,
    preview_term_import,
    preview_to_session_value,
    serialize_aliases,
    sync_all_term_alias_active,
    sync_term_source_aliases,
    validate_term_payload,
)
from .services.term_candidate_review import accept_candidate, merge_candidate, set_candidate_status
from .services.terms import apply_created_term_to_article
from .tasks import (
    batch_translate_articles_task,
    crawl_news_source_task,
    discover_term_candidates_task,
    process_article_automation_task,
    publish_article_automatically,
    qq_push_delivery_task,
    scan_article_horse_links_task,
    translate_article_task,
)

PUBLIC_FEED_PAGE_SIZE = 12
PUBLIC_HOT_CANDIDATE_LIMIT = 48
PUBLIC_HOT_DISPLAY_LIMIT = 6
QUICK_TERM_FOLLOWUP_SESSION_KEY = "article_quick_term_followup"
RACE_CALENDAR_PAGE_SIZE = 40
RACE_CALENDAR_WINDOW_DAYS = 30
HORSE_PROFILE_PAGE_SIZE = 40
PUBLIC_HORSE_PAGE_SIZE = 24
PUBLIC_REGION_TABS = [
    {"value": "", "label": "综合"},
    {"value": RacingRegion.JAPAN, "label": "日本"},
    {"value": RacingRegion.HONG_KONG, "label": "中国香港"},
    {"value": RacingRegion.UNITED_KINGDOM, "label": "英国"},
    {"value": RacingRegion.FRANCE, "label": "法国"},
    {"value": RacingRegion.UNITED_STATES, "label": "美国"},
]


class BackendLoginView(LoginView):
    template_name = "stable/auth/login.html"
    authentication_form = BackendAuthenticationForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse("console-dashboard")


class BackendLogoutView(LogoutView):
    next_page = settings.LOGOUT_REDIRECT_URL


def _redirect_with_query(request: HttpRequest, target: str):
    query = request.META.get("QUERY_STRING", "")
    if query:
        separator = "&" if "?" in target else "?"
        target = f"{target}{separator}{query}"
    return redirect(target)


def legacy_login_redirect(request: HttpRequest):
    return _redirect_with_query(request, reverse("backend-login"))


def legacy_logout_redirect(request: HttpRequest):
    return _redirect_with_query(request, reverse("backend-logout"))


def legacy_console_redirect(request: HttpRequest, subpath: str = ""):
    base = "/admin/"
    target = f"{base}{subpath.lstrip('/')}" if subpath else base
    return _redirect_with_query(request, target)


def _ensure_staff(request: HttpRequest):
    if not request.user.is_authenticated:
        return redirect(settings.LOGIN_URL)
    if not request.user.is_staff:
        return HttpResponseForbidden("仅管理员可访问。")
    return None


def _console_context(request: HttpRequest, **extra):
    return {
        "active_path": request.path,
        "django_admin_url": settings.DJANGO_ADMIN_URL,
        "pending_edit_count": NewsArticle.objects.filter(workflow_status=WorkflowStatus.PENDING_EDIT).count(),
        "pending_review_count": NewsArticle.objects.filter(workflow_status=WorkflowStatus.PENDING_REVIEW).count(),
        "pending_term_candidate_count": TermCandidate.objects.filter(status=TermCandidateStatus.PENDING).count(),
        **extra,
    }


def _article_filters(queryset, request: HttpRequest):
    query = (request.GET.get("q") or request.POST.get("q") or "").strip()
    source_id = (request.GET.get("source") or request.POST.get("source") or "").strip()
    workflow_status = (request.GET.get("workflow_status") or request.POST.get("workflow_status") or "").strip()
    translated = (request.GET.get("translated") or request.POST.get("translated") or "").strip()
    translation_status = (request.GET.get("translation_status") or request.POST.get("translation_status") or "").strip()
    automation_status = (request.GET.get("automation_status") or request.POST.get("automation_status") or "").strip()
    review_mode = (request.GET.get("review_mode") or request.POST.get("review_mode") or "").strip()

    if query:
        queryset = queryset.filter(
            Q(title_ja__icontains=query)
            | Q(title_zh__icontains=query)
            | Q(translated_title_zh__icontains=query)
            | Q(body_ja_normalized__icontains=query)
        )
    if source_id:
        queryset = queryset.filter(source_config_id=source_id)
    if workflow_status:
        queryset = queryset.filter(workflow_status=workflow_status)
    if translation_status:
        queryset = queryset.filter(translation_status=translation_status)
    if automation_status:
        queryset = queryset.filter(automation_status=automation_status)
    if review_mode:
        queryset = queryset.filter(review_mode=review_mode)
    if translated == "yes":
        queryset = queryset.exclude(translated_body_zh="")
    elif translated == "no":
        queryset = queryset.filter(translated_body_zh="")
    return queryset


def _translation_queue_queryset(request: HttpRequest):
    queryset = NewsArticle.objects.exclude(
        workflow_status__in=[WorkflowStatus.PUBLISHED, WorkflowStatus.WITHDRAWN]
    )
    queryset = _article_filters(queryset, request)
    only_failed = request.POST.get("only_failed", "").strip()
    if only_failed == "1":
        queryset = queryset.filter(translation_status=ArticleTranslationStatus.FAILED)
    else:
        queryset = queryset.filter(
            translation_status__in=[ArticleTranslationStatus.PENDING, ArticleTranslationStatus.FAILED]
        )
    return queryset.order_by("-published_at", "-id")


TERM_IMPORT_SESSION_KEY = "term_import_preview"


def _term_filters(queryset, request: HttpRequest):
    query = request.GET.get("q", "").strip()
    term_type = request.GET.get("term_type", "").strip()
    source_language = request.GET.get("source_language", "").strip()
    racing_region = request.GET.get("racing_region", "").strip()
    is_active = request.GET.get("is_active", "").strip()
    has_alias = request.GET.get("has_alias", "").strip()
    translation_status = request.GET.get("translation_status", "").strip()

    if query:
        normalized_query = query.casefold()
        alias_match_ids = [
            term.id
            for term in queryset.only("id", "aliases_ja", "aliases_zh")
            if any(
                normalized_query in str(alias).casefold()
                for alias in [*(term.aliases_ja or []), *(term.aliases_zh or [])]
            )
        ]
        queryset = queryset.filter(
            Q(source_ja__icontains=query)
            | Q(target_zh__icontains=query)
            | Q(notes__icontains=query)
            | Q(source_aliases__text__icontains=query)
            | Q(pk__in=alias_match_ids)
        ).distinct()
    if term_type:
        queryset = queryset.filter(term_type=term_type)
    if source_language:
        queryset = queryset.filter(Q(source_language=source_language) | Q(source_aliases__source_language=source_language)).distinct()
    if racing_region:
        queryset = queryset.filter(racing_region=racing_region)
    if translation_status:
        queryset = queryset.filter(translation_status=translation_status)
    if is_active == "true":
        queryset = queryset.filter(is_active=True)
    elif is_active == "false":
        queryset = queryset.filter(is_active=False)
    if has_alias == "yes":
        queryset = queryset.filter(~Q(aliases_ja=[]) | ~Q(aliases_zh=[]) | Q(source_aliases__isnull=False)).distinct()
    return queryset


def _term_candidate_filters(queryset, request: HttpRequest):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    term_type = request.GET.get("term_type", "").strip()
    source_id = request.GET.get("source", "").strip()
    min_confidence = request.GET.get("min_confidence", "").strip()
    seen_from = request.GET.get("seen_from", "").strip()
    seen_to = request.GET.get("seen_to", "").strip()
    if query:
        queryset = queryset.filter(Q(source_ja__icontains=query) | Q(suggested_target_zh__icontains=query) | Q(review_notes__icontains=query))
    if status:
        queryset = queryset.filter(status=status)
    if term_type:
        queryset = queryset.filter(term_type=term_type)
    if source_id:
        queryset = queryset.filter(evidence__article__source_config_id=source_id)
    if min_confidence.isdigit():
        queryset = queryset.filter(confidence__gte=int(min_confidence))
    if seen_from:
        queryset = queryset.filter(last_seen_at__date__gte=seen_from)
    if seen_to:
        queryset = queryset.filter(last_seen_at__date__lte=seen_to)
    return queryset.distinct()


def _source_health(source: NewsSource, *, now=None) -> dict:
    now = now or timezone.now()
    latest_job = source.crawl_jobs.order_by("-started_at", "-id").first()
    latest_completed_job = source.crawl_jobs.exclude(status=TaskStatus.STARTED).order_by("-started_at", "-id").first()
    running_timeout_minutes = 60
    stale_minutes = max(source.crawl_interval_minutes * 3, 180)
    completed_at = (latest_completed_job.finished_at if latest_completed_job else None) or source.last_crawl_at
    freshness_reference_at = completed_at or source.created_at
    is_stale = bool(source.enabled and freshness_reference_at and freshness_reference_at < now - timedelta(minutes=stale_minutes))
    status = (latest_completed_job.status if latest_completed_job else "") or source.last_crawl_status
    new_count = latest_completed_job.success_count if latest_completed_job else None
    duplicate_count = latest_completed_job.fail_count if latest_completed_job else None
    error_summary = ((latest_completed_job.error_message if latest_completed_job else "") or source.last_crawl_message).strip()
    if latest_job and latest_job.status == TaskStatus.STARTED:
        running_minutes = int((now - latest_job.started_at).total_seconds() // 60)
        started_at = timezone.localtime(latest_job.started_at).strftime("%m-%d %H:%M")
        if running_minutes > running_timeout_minutes:
            label = "运行超时"
            tone = "warning"
            summary = f"运行中记录已超过 {running_timeout_minutes} 分钟，开始于 {started_at}"
        else:
            label = "运行中"
            tone = "warning"
            summary = f"开始于 {started_at}"
    elif status == TaskStatus.FAILED:
        label = "失败"
        tone = "danger"
        summary = error_summary or "抓取失败"
    elif is_stale:
        label = "长时间未运行"
        tone = "warning"
        summary = f"超过 {stale_minutes} 分钟无抓取记录"
    elif status == TaskStatus.SUCCESS and new_count == 0:
        label = "成功无新增"
        tone = "success"
        summary = f"新增 0，重复 {duplicate_count or 0}"
    elif status == TaskStatus.SUCCESS:
        label = "成功"
        tone = "success"
        summary = f"新增 {new_count or 0}，重复 {duplicate_count or 0}"
    else:
        label = "未运行"
        tone = ""
        summary = "暂无抓取记录"
    return {
        "label": label,
        "tone": tone,
        "summary": summary,
        "new_count": new_count,
        "duplicate_count": duplicate_count,
        "error_summary": error_summary,
        "latest_job": latest_job,
        "latest_completed_job": latest_completed_job,
        "is_stale": is_stale,
    }


def _attach_source_health(sources):
    source_list = list(sources)
    now = timezone.now()
    for source in source_list:
        source.health = _source_health(source, now=now)
    return source_list


def _race_event_filters(queryset, request: HttpRequest):
    query = request.GET.get("q", "").strip()
    year = request.GET.get("year", "").strip()
    region = request.GET.get("region", "").strip()
    priority = request.GET.get("priority", "").strip()
    status = request.GET.get("status", "").strip()
    visibility = request.GET.get("visibility", "").strip()
    quality = request.GET.get("quality", "").strip()
    if query:
        queryset = queryset.filter(
            Q(chinese_name__icontains=query)
            | Q(original_name__icontains=query)
            | Q(slug__icontains=query)
            | Q(racecourse__icontains=query)
            | Q(aliases__text__icontains=query)
        ).distinct()
    if year.isdigit():
        queryset = queryset.filter(year=int(year))
    if region:
        queryset = queryset.filter(country_region=region)
    if priority:
        queryset = queryset.filter(priority=priority)
    if status:
        queryset = queryset.filter(status=status)
    if visibility:
        queryset = queryset.filter(visibility_status=visibility)
    if quality:
        queryset = queryset.filter(data_quality_status=quality)
    return queryset


@login_required
def race_event_list(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    queryset = RaceEvent.objects.annotate(
        candidate_count=Count("data_candidates", distinct=True),
        linked_article_count=Count("article_links", filter=Q(article_links__status__in=[ArticleRaceLinkStatus.AUTO, ArticleRaceLinkStatus.MANUAL]), distinct=True),
    ).order_by("local_date", "local_start_time", "country_region", "chinese_name")
    queryset = _race_event_filters(queryset, request)
    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    pagination_params = request.GET.copy()
    pagination_params.pop("page", None)
    years = RaceEvent.objects.order_by("-year").values_list("year", flat=True).distinct()
    return render(
        request,
        "stable/console/race_event_list.html",
        _console_context(
            request,
            page_obj=page_obj,
            race_events=page_obj.object_list,
            years=years,
            regions=RacingRegion.choices,
            priorities=RaceEventPriority.choices,
            statuses=RaceEventStatus.choices,
            visibilities=RaceEventVisibility.choices,
            qualities=RaceEventDataQuality.choices,
            filters={
                "q": request.GET.get("q", ""),
                "year": request.GET.get("year", ""),
                "region": request.GET.get("region", ""),
                "priority": request.GET.get("priority", ""),
                "status": request.GET.get("status", ""),
                "visibility": request.GET.get("visibility", ""),
                "quality": request.GET.get("quality", ""),
            },
            pagination_querystring=pagination_params.urlencode(),
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def race_event_edit(request: HttpRequest, event_id: int | None = None):
    denied = _ensure_staff(request)
    if denied:
        return denied
    event = get_object_or_404(RaceEvent, pk=event_id) if event_id else RaceEvent()
    if request.method == "POST":
        form = RaceEventForm(request.POST, instance=event)
        if form.is_valid():
            event = form.save()
            log_operation(
                action_type="race_event_saved",
                target_type="race_event",
                target_id=event.pk,
                detail=f"保存赛事 {event}",
                admin=request.user,
            )
            messages.success(request, "赛事资料已保存。")
            return redirect("console-race-event-edit", event_id=event.pk)
    else:
        form = RaceEventForm(instance=event)
    candidates = []
    links = {"linked": [], "candidate": [], "removed": []}
    runners = []
    results = []
    history_winners = []
    logs = []
    if event.pk:
        candidates = event.data_candidates.select_related("applied_by").all()[:30]
        for link in event.article_links.select_related("article").all()[:80]:
            if link.status == ArticleRaceLinkStatus.REMOVED:
                links["removed"].append(link)
            elif link.status == ArticleRaceLinkStatus.CANDIDATE:
                links["candidate"].append(link)
            else:
                links["linked"].append(link)
        runners = event.runners.all()
        results = event.results.all()
        history_winners = event.history_winners.all()
        logs = OperationLog.objects.filter(target_type__in=["race_event", "article_race_link"]).filter(
            Q(target_id=str(event.pk)) | Q(detail__icontains=f"event={event.pk}")
        )[:20]
    return render(
        request,
        "stable/console/race_event_form.html",
        _console_context(
            request,
            form=form,
            event=event,
            page_title="新建赛事" if not event.pk else f"{event.chinese_name} {event.year}",
            candidates=candidates,
            links=links,
            runners=runners,
            results=results,
            history_winners=history_winners,
            logs=logs,
        ),
    )


@login_required
@require_POST
def race_event_apply_candidate(request: HttpRequest, candidate_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    candidate = get_object_or_404(RaceEventDataCandidate.objects.select_related("event"), pk=candidate_id)
    apply_data_candidate(candidate, user=request.user)
    messages.success(request, "候选资料已应用。")
    return redirect("console-race-event-edit", event_id=candidate.event_id)


@login_required
@require_POST
def race_event_associate_articles(request: HttpRequest, event_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    event = get_object_or_404(RaceEvent, pk=event_id)
    result = associate_articles_for_event(event)
    messages.success(request, f"自动关联完成：新增 {result['created']}，更新 {result['updated']}，跳过已移除 {result['skipped_removed']}。")
    return redirect("console-race-event-edit", event_id=event.pk)


@login_required
@require_POST
def race_event_link_article(request: HttpRequest, event_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    event = get_object_or_404(RaceEvent, pk=event_id)
    article_id = (request.POST.get("article_id") or "").strip()
    if not article_id.isdigit():
        messages.error(request, "请输入有效的文章 ID。")
        return redirect("console-race-event-edit", event_id=event.pk)
    article = get_object_or_404(NewsArticle, pk=int(article_id))
    link, _ = ArticleRaceLink.objects.update_or_create(
        event=event,
        article=article,
        defaults={
            "status": ArticleRaceLinkStatus.MANUAL,
            "link_type": request.POST.get("link_type") or ArticleRaceLinkType.RELATED,
            "source": "manual",
            "confidence": 100,
            "match_reason": "后台手动添加",
            "confirmed_by": request.user,
            "confirmed_at": timezone.now(),
        },
    )
    log_operation(
        action_type="race_article_link_added",
        target_type="article_race_link",
        target_id=link.pk,
        detail=f"手动添加赛事新闻关联 event={event.pk} article={article.pk}",
        admin=request.user,
    )
    messages.success(request, "文章已关联到赛事。")
    return redirect("console-race-event-edit", event_id=event.pk)


@login_required
@require_POST
def race_event_confirm_link(request: HttpRequest, link_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    link = get_object_or_404(ArticleRaceLink.objects.select_related("event"), pk=link_id)
    confirm_article_link(link, user=request.user)
    messages.success(request, "关联已确认。")
    return redirect("console-race-event-edit", event_id=link.event_id)


@login_required
@require_POST
def race_event_remove_link(request: HttpRequest, link_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    link = get_object_or_404(ArticleRaceLink.objects.select_related("event"), pk=link_id)
    remove_article_link(link, user=request.user)
    messages.success(request, "关联已移除，自动任务不会重新公开该关联。")
    return redirect("console-race-event-edit", event_id=link.event_id)


def _horse_profile_filters(queryset, request: HttpRequest):
    query = request.GET.get("q", "").strip()
    region = request.GET.get("region", "").strip()
    status = request.GET.get("status", "").strip()
    completeness = request.GET.get("completeness", "").strip()
    major_win = request.GET.get("major_win", "").strip()
    has_news = request.GET.get("has_news", "").strip()
    has_follows = request.GET.get("has_follows", "").strip()
    public = request.GET.get("public", "").strip()
    p0_source = request.GET.get("p0_source", "").strip()
    name_status = request.GET.get("name_status", "").strip()
    sync_status = request.GET.get("sync_status", "").strip()
    candidate_status = request.GET.get("candidate_status", "").strip()
    if query:
        queryset = queryset.filter(
            Q(display_name_zh__icontains=query)
            | Q(original_name__icontains=query)
            | Q(english_name__icontains=query)
            | Q(japanese_name__icontains=query)
            | Q(primary_term__target_zh__icontains=query)
            | Q(primary_term__source_ja__icontains=query)
        )
    if region:
        queryset = queryset.filter(racing_region=region)
    if status:
        queryset = queryset.filter(review_status=status)
    if completeness:
        queryset = queryset.filter(completeness_status=completeness)
    if major_win == "yes":
        queryset = queryset.filter(race_records__result_status="won").distinct()
    elif major_win == "no":
        queryset = queryset.exclude(race_records__result_status="won").distinct()
    if has_news == "yes":
        queryset = queryset.filter(article_links__status__in=[ArticleHorseLinkStatus.AUTO, ArticleHorseLinkStatus.MANUAL]).distinct()
    elif has_news == "no":
        queryset = queryset.exclude(article_links__status__in=[ArticleHorseLinkStatus.AUTO, ArticleHorseLinkStatus.MANUAL]).distinct()
    if has_follows == "yes":
        queryset = queryset.filter(follows__isnull=False).distinct()
    elif has_follows == "no":
        queryset = queryset.filter(follows__isnull=True)
    if public == "yes":
        queryset = queryset.filter(review_status=HorseProfileStatus.PUBLISHED)
    elif public == "no":
        queryset = queryset.exclude(review_status=HorseProfileStatus.PUBLISHED)
    if p0_source:
        queryset = queryset.filter(p0_sources__source_type=p0_source, p0_sources__status=HorseP0SourceStatus.ACTIVE).distinct()
    if name_status == "pending":
        queryset = queryset.filter(primary_term__translation_status=TermTranslationStatus.PENDING)
    elif name_status == "translated":
        queryset = queryset.filter(primary_term__translation_status=TermTranslationStatus.TRANSLATED).exclude(primary_term__target_zh="")
    if sync_status == "stale":
        queryset = queryset.filter(racing_career_status="active").filter(
            Q(records_synced_through__isnull=True)
            | Q(records_synced_through__lt=active_record_freshness_cutoff())
        )
    elif sync_status == "fresh":
        queryset = queryset.exclude(records_synced_through__isnull=True)
    if candidate_status in HorseProfileCandidateStatus.values:
        queryset = queryset.filter(data_candidates__status=candidate_status).distinct()
    return queryset


@login_required
def horse_profile_list(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    queryset = (
        HorseProfile.objects.select_related("primary_term")
        .annotate(
            article_link_count=Count("article_links", filter=Q(article_links__status__in=[ArticleHorseLinkStatus.AUTO, ArticleHorseLinkStatus.MANUAL]), distinct=True),
            candidate_count=Count("data_candidates", filter=Q(data_candidates__status=HorseProfileCandidateStatus.PENDING), distinct=True),
            follow_count=Count("follows", distinct=True),
            race_record_count=Count("race_records", distinct=True),
            p0_source_count=Count("p0_sources", filter=Q(p0_sources__status=HorseP0SourceStatus.ACTIVE), distinct=True),
        )
        .order_by("racing_region", "display_name_zh", "original_name", "id")
    )
    queryset = _horse_profile_filters(queryset, request)
    paginator = Paginator(queryset, HORSE_PROFILE_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    pagination_params = request.GET.copy()
    pagination_params.pop("page", None)
    return render(
        request,
        "stable/console/horse_profile_list.html",
        _console_context(
            request,
            page_obj=page_obj,
            horse_profiles=page_obj.object_list,
            regions=RacingRegion.choices,
            statuses=HorseProfileStatus.choices,
            completenesses=HorseProfileCompleteness.choices,
            p0_source_types=HorseP0SourceType.choices,
            candidate_statuses=HorseProfileCandidateStatus.choices,
            filters={
                "q": request.GET.get("q", ""),
                "region": request.GET.get("region", ""),
                "status": request.GET.get("status", ""),
                "completeness": request.GET.get("completeness", ""),
                "major_win": request.GET.get("major_win", ""),
                "has_news": request.GET.get("has_news", ""),
                "has_follows": request.GET.get("has_follows", ""),
                "public": request.GET.get("public", ""),
                "p0_source": request.GET.get("p0_source", ""),
                "name_status": request.GET.get("name_status", ""),
                "sync_status": request.GET.get("sync_status", ""),
                "candidate_status": request.GET.get("candidate_status", ""),
            },
            pagination_querystring=pagination_params.urlencode(),
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def horse_profile_detail(request: HttpRequest, profile_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    profile = get_object_or_404(
        HorseProfile.objects.select_related("primary_term", "sire_horse_profile", "dam_horse_profile"),
        pk=profile_id,
    )
    if request.method == "POST":
        form = HorseProfileForm(request.POST, instance=profile)
        if form.is_valid():
            profile = form.save()
            update_completeness(profile)
            log_operation(
                action_type="horse_profile_saved",
                target_type="horse_profile",
                target_id=profile.pk,
                detail=f"保存马匹资料 {profile.display_name}",
                admin=request.user,
            )
            messages.success(request, "马匹资料已保存。")
            return redirect("console-horse-profile-detail", profile_id=profile.pk)
    else:
        form = HorseProfileForm(instance=profile)
    race_record_form = HorseRaceRecordForm()
    article_link_form = HorseArticleLinkForm()
    candidates = profile.data_candidates.select_related("applied_by").all()[:40]
    p0_sources = profile.p0_sources.select_related("term", "race_event").all()[:40]
    race_records = profile.race_records.select_related("event").all()[:80]
    article_links = {
        "linked": [],
        "candidate": [],
        "removed": [],
    }
    for link in profile.article_links.select_related("article").all()[:100]:
        if link.status == ArticleHorseLinkStatus.REMOVED:
            article_links["removed"].append(link)
        elif link.status == ArticleHorseLinkStatus.CANDIDATE:
            article_links["candidate"].append(link)
        else:
            article_links["linked"].append(link)
    race_links = profile.race_links.select_related("event").all()[:60]
    logs = OperationLog.objects.filter(target_type__in=["horse_profile", "horse_article_link", "horse_race_record"]).filter(
        Q(target_id=str(profile.pk)) | Q(detail__icontains=f"profile={profile.pk}")
    )[:20]
    return render(
        request,
        "stable/console/horse_profile_detail.html",
        _console_context(
            request,
            profile=profile,
            form=form,
            race_record_form=race_record_form,
            article_link_form=article_link_form,
            candidates=candidates,
            p0_sources=p0_sources,
            race_records=race_records,
            major_wins=major_win_records(profile),
            article_links=article_links,
            race_links=race_links,
            follow_count=profile.follows.count(),
            descendant_follow_count=profile.follows.filter(include_descendants=True).count(),
            logs=logs,
        ),
    )


@login_required
@require_POST
def horse_profile_status(request: HttpRequest, profile_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    profile = get_object_or_404(HorseProfile, pk=profile_id)
    status = request.POST.get("status", "").strip()
    if status not in {HorseProfileStatus.DRAFT, HorseProfileStatus.READY, HorseProfileStatus.PUBLISHED, HorseProfileStatus.HIDDEN}:
        messages.error(request, "无效的审核状态。")
        return redirect("console-horse-profile-detail", profile_id=profile.pk)
    transition_review_status(profile, status, user=request.user, note=request.POST.get("note", "").strip())
    messages.success(request, "审核状态已更新。")
    return redirect("console-horse-profile-detail", profile_id=profile.pk)


@login_required
@require_POST
def horse_profile_apply_candidate(request: HttpRequest, candidate_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    candidate = get_object_or_404(HorseProfileDataCandidate.objects.select_related("profile"), pk=candidate_id)
    action = request.POST.get("action", "apply")
    if action == "apply":
        try:
            apply_horse_data_candidate(candidate, user=request.user)
        except ValueError:
            messages.error(request, "只有待确认候选可以应用。")
        else:
            messages.success(request, "候选资料已应用。")
    elif action in {"ignore", "conflict"}:
        candidate.status = HorseProfileCandidateStatus.IGNORED if action == "ignore" else HorseProfileCandidateStatus.CONFLICT
        candidate.applied_by = request.user
        candidate.applied_at = timezone.now()
        candidate.result_summary = request.POST.get("note", "").strip()
        candidate.save(update_fields=["status", "applied_by", "applied_at", "result_summary", "updated_at"])
        messages.success(request, "候选资料状态已更新。")
    else:
        messages.error(request, "无效的候选处理动作。")
    return redirect("console-horse-profile-detail", profile_id=candidate.profile_id)


@login_required
@require_POST
def horse_profile_add_race_record(request: HttpRequest, profile_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    profile = get_object_or_404(HorseProfile, pk=profile_id)
    form = HorseRaceRecordForm(request.POST)
    if form.is_valid():
        payload = _horse_race_record_payload(form)
        try:
            upsert = upsert_race_record(profile, payload)
        except ValueError as exc:
            messages.error(request, f"参赛履历未保存：{exc}")
            return redirect("console-horse-profile-detail", profile_id=profile.pk)
        record = upsert.record
        log_operation(
            action_type="horse_race_record_saved",
            target_type="horse_race_record",
            target_id=record.pk,
            detail=f"手动添加马匹参赛履历 profile={profile.pk} race={record.race_name} action={upsert.action}",
            admin=request.user,
        )
        messages.success(request, "参赛履历已添加。" if upsert.action == "created" else "已存在相同参赛履历，未重复添加。")
    else:
        messages.error(request, "参赛履历表单有误，请检查必填项。")
    return redirect("console-horse-profile-detail", profile_id=profile.pk)


@login_required
@require_http_methods(["GET", "POST"])
def horse_profile_edit_race_record(request: HttpRequest, record_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    record = get_object_or_404(HorseRaceRecord.objects.select_related("horse_profile"), pk=record_id)
    if request.method == "POST":
        form = HorseRaceRecordForm(request.POST, instance=record)
        if form.is_valid():
            try:
                upsert = upsert_race_record(
                    record.horse_profile,
                    _horse_race_record_payload(form),
                    record=record,
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                record = upsert.record
                log_operation(
                    action_type="horse_race_record_saved",
                    target_type="horse_race_record",
                    target_id=record.pk,
                    detail=(
                        f"编辑马匹参赛履历 profile={record.horse_profile_id} "
                        f"race={record.race_name} action={upsert.action} diff={upsert.diff}"
                    ),
                    admin=request.user,
                )
                messages.success(request, "参赛履历已保存。")
                return redirect("console-horse-profile-detail", profile_id=record.horse_profile_id)
    else:
        form = HorseRaceRecordForm(instance=record)
    return render(
        request,
        "stable/console/horse_race_record_form.html",
        _console_context(request, record=record, profile=record.horse_profile, form=form),
    )


def _horse_race_record_payload(form: HorseRaceRecordForm) -> dict:
    cleaned = form.cleaned_data
    race_date = cleaned.get("race_date")
    event = cleaned.get("event")
    return {
        "event_id": event.pk if event else None,
        "race_name": cleaned.get("race_name") or "",
        "race_year": cleaned.get("race_year"),
        "race_date": race_date.isoformat() if race_date else "",
        "grade_text": cleaned.get("grade_text") or "",
        "normalized_grade": cleaned.get("normalized_grade") or "",
        "racecourse": cleaned.get("racecourse") or "",
        "distance_text": cleaned.get("distance_text") or "",
        "surface": cleaned.get("surface") or "",
        "finish_position": cleaned.get("finish_position") or "",
        "result_status": cleaned.get("result_status") or HorseRaceResultStatus.UNKNOWN,
        "is_major_win": bool(cleaned.get("is_major_win")),
        "major_win_order": cleaned.get("major_win_order") or 0,
        "source_name": cleaned.get("source_name") or "manual",
        "source_url": cleaned.get("source_url") or "",
        "source_refs": {"entry_method": "manual_console"},
    }


@login_required
@require_POST
def horse_profile_delete_race_record(request: HttpRequest, record_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    record = get_object_or_404(HorseRaceRecord.objects.select_related("horse_profile"), pk=record_id)
    profile_id = record.horse_profile_id
    record.delete()
    messages.success(request, "参赛履历已删除。")
    return redirect("console-horse-profile-detail", profile_id=profile_id)


@login_required
@require_POST
def horse_profile_scan_articles(request: HttpRequest, profile_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    profile = get_object_or_404(HorseProfile, pk=profile_id)
    result = scan_article_horse_links(profile=profile, commit=True)
    messages.success(request, f"重新扫描完成：新增 {result['created']}，更新 {result['updated']}，候选命中 {result['candidate']}。")
    return redirect("console-horse-profile-detail", profile_id=profile.pk)


@login_required
@require_POST
def horse_profile_add_article_link(request: HttpRequest, profile_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    profile = get_object_or_404(HorseProfile, pk=profile_id)
    form = HorseArticleLinkForm(request.POST)
    if not form.is_valid():
        messages.error(request, "请输入有效的文章 ID。")
        return redirect("console-horse-profile-detail", profile_id=profile.pk)
    article = get_object_or_404(NewsArticle, pk=form.cleaned_data["article_id"])
    link, _ = ArticleHorseLink.objects.update_or_create(
        horse_profile=profile,
        article=article,
        defaults={
            "status": form.cleaned_data["status"],
            "source": "manual",
            "confidence": 100,
            "match_reason": "后台手动添加",
            "confirmed_by": request.user,
            "confirmed_at": timezone.now(),
        },
    )
    log_operation(
        action_type="horse_article_link_added",
        target_type="horse_article_link",
        target_id=link.pk,
        detail=f"手动添加马匹新闻关联 profile={profile.pk} article={article.pk}",
        admin=request.user,
    )
    messages.success(request, "文章关联已添加。")
    return redirect("console-horse-profile-detail", profile_id=profile.pk)


@login_required
@require_POST
def horse_profile_article_link_status(request: HttpRequest, link_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    link = get_object_or_404(ArticleHorseLink.objects.select_related("horse_profile"), pk=link_id)
    action = request.POST.get("action", "").strip()
    if action == "confirm":
        link.status = ArticleHorseLinkStatus.MANUAL
        link.confirmed_by = request.user
        link.confirmed_at = timezone.now()
        link.removed_by = None
        link.removed_at = None
        link.save(update_fields=["status", "confirmed_by", "confirmed_at", "removed_by", "removed_at", "updated_at"])
        messages.success(request, "新闻关联已确认。")
    elif action == "remove":
        link.status = ArticleHorseLinkStatus.REMOVED
        link.removed_by = request.user
        link.removed_at = timezone.now()
        link.save(update_fields=["status", "removed_by", "removed_at", "updated_at"])
        messages.success(request, "新闻关联已移除，自动扫描不会重新公开。")
    elif action == "reset":
        link.status = ArticleHorseLinkStatus.CANDIDATE
        link.confirmed_by = None
        link.confirmed_at = None
        link.removed_by = None
        link.removed_at = None
        link.save(update_fields=["status", "confirmed_by", "confirmed_at", "removed_by", "removed_at", "updated_at"])
        messages.success(request, "新闻关联已重置为候选。")
    else:
        messages.error(request, "无效的关联操作。")
    return redirect("console-horse-profile-detail", profile_id=link.horse_profile_id)


@login_required
def console_dashboard(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    sync_builtin_sources()
    today = timezone.localdate()
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    published_today = NewsArticle.objects.filter(published_to_web_at__date=today).count()
    crawl_success_today = NewsArticle.objects.filter(first_seen_at__gte=today_start).count()
    crawl_failed_today = CrawlJob.objects.filter(started_at__gte=today_start, status="failed").count()
    recent_sources = _attach_source_health(NewsSource.objects.filter(deleted_at__isnull=True).order_by("-updated_at")[:5])
    recent_published = NewsArticle.objects.filter(workflow_status=WorkflowStatus.PUBLISHED).order_by("-published_to_web_at")[:6]
    stats = {
        "crawl_success_today": crawl_success_today,
        "crawl_failed_today": crawl_failed_today,
        "pending_edit": NewsArticle.objects.filter(workflow_status=WorkflowStatus.PENDING_EDIT).count(),
        "pending_review": NewsArticle.objects.filter(workflow_status=WorkflowStatus.PENDING_REVIEW).count(),
        "published_today": published_today,
    }
    return render(
        request,
        "stable/console/dashboard.html",
        _console_context(request, stats=stats, recent_sources=recent_sources, recent_published=recent_published),
    )


@login_required
def source_list(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    sync_builtin_sources()
    selected_region = (request.GET.get("region") or "").strip()
    queryset = NewsSource.objects.filter(deleted_at__isnull=True)
    if selected_region:
        queryset = queryset.filter(racing_region=selected_region)
    sources = _attach_source_health(queryset.order_by("-enabled", "-priority", "name"))
    return render(
        request,
        "stable/console/source_list.html",
        _console_context(request, sources=sources, selected_region=selected_region, production_regions=PRODUCTION_REGIONS),
    )


@login_required
def region_production(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    selected_region = (request.GET.get("region") or "").strip()
    rows = region_production_rows(selected_region=selected_region)
    sources = NewsSource.objects.filter(deleted_at__isnull=True)
    if selected_region:
        sources = sources.filter(racing_region=selected_region)
    sources = _attach_source_health(sources.order_by("-enabled", "-priority", "name")[:50])
    from stable.models import MultiregionAttributionRun
    from stable.services.news_attribution import (
        ATTRIBUTION_RULE_VERSION,
        attribution_mode,
        related_region_queries_enabled,
    )

    latest_attribution_run = (
        MultiregionAttributionRun.objects.exclude(rule_version="").order_by("-started_at", "-id").first()
    )
    latest_attribution_qualified = bool(
        latest_attribution_run
        and latest_attribution_run.status == "completed"
        and latest_attribution_run.rule_version == ATTRIBUTION_RULE_VERSION
        and latest_attribution_run.gold_version not in {"", "pending-review"}
        and len(latest_attribution_run.gold_snapshot_sha256 or "") == 64
        and (latest_attribution_run.metrics or {}).get("qualified")
    )
    failure_queryset = NewsArticle.objects.filter(
        translation_status=ArticleTranslationStatus.FAILED,
    )
    if selected_region:
        failure_queryset = failure_queryset.filter(racing_region=selected_region)
    translation_failures = list(failure_queryset.order_by("-updated_at", "-id")[:50])
    for article in translation_failures:
        if article.translation_retry_exhausted_at:
            article.ops_failure_reason = "translation_retry_exhausted"
        elif article.translation_next_retry_at:
            article.ops_failure_reason = "translation_retry_waiting"
        else:
            article.ops_failure_reason = article.translation_error_category or "translation_failed"
    attribution_queryset = NewsArticle.objects.filter(attribution_status="needs_review")
    if selected_region:
        attribution_queryset = attribution_queryset.filter(racing_region=selected_region)
    attribution_reviews = list(attribution_queryset.order_by("-updated_at", "-id")[:50])
    return render(
        request,
        "stable/console/region_production.html",
        _console_context(
            request,
            rows=rows,
            sources=sources,
            selected_region=selected_region,
            production_regions=PRODUCTION_REGIONS,
            attribution_mode=attribution_mode(),
            attribution_rollout_stage=getattr(settings, "MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE", "off"),
            related_region_queries_enabled=related_region_queries_enabled(),
            latest_attribution_run=latest_attribution_run,
            latest_attribution_qualified=latest_attribution_qualified,
            translation_failures=translation_failures,
            attribution_reviews=attribution_reviews,
        ),
    )


def _window_quota_ledgers(window: ProductionWindow):
    hour_start = window.window_start.replace(minute=0, second=0, microsecond=0)
    kinds = [QuotaLedgerKind.WEB_PUBLISH] if window.kind == ProductionWindowKind.PUBLISH else [QuotaLedgerKind.QQ_PUSH]
    return QuotaLedger.objects.filter(kind__in=kinds, window_start=hour_start).order_by("kind", "scope", "scope_key")


@login_required
def production_window_detail(request: HttpRequest, window_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    window = get_object_or_404(
        ProductionWindow.objects.select_related("source", "target", "triggered_by"),
        pk=window_id,
    )
    return render(
        request,
        "stable/console/production_window_detail.html",
        _console_context(
            request,
            window=window,
            candidate_decisions=window.candidate_decisions.select_related("article").order_by("rank", "-score", "id"),
            target_decisions=window.target_decisions.select_related("article", "target").order_by("target_id", "article_id", "id"),
            quota_ledgers=_window_quota_ledgers(window),
        ),
    )


@login_required
def production_window_preview(request: HttpRequest, window_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    window = get_object_or_404(ProductionWindow, pk=window_id)
    selected_articles = []
    delivery_articles = []
    candidate_decisions = []
    target_decisions = []
    zero_reasons: list[str] = []
    unsupported = window.kind not in {ProductionWindowKind.PUBLISH, ProductionWindowKind.QQ_PUSH}

    if not unsupported:
        with transaction.atomic():
            if window.kind == ProductionWindowKind.PUBLISH:
                result = select_publish_candidates(window.racing_region, window=window, now=window.window_end)
                selected_articles = list(result.selected)
                zero_reasons = result.zero_reasons
                candidate_decisions = list(
                    WindowCandidateDecision.objects.filter(window=window)
                    .select_related("article")
                    .order_by("rank", "-score", "id")
                )
            else:
                result = select_qq_window_deliveries(window.racing_region, window=window, now=window.window_end)
                zero_reasons = result.zero_reasons
                delivery_articles = [delivery.article for delivery in result.deliveries]
                target_decisions = list(
                    WindowTargetDecision.objects.filter(window=window)
                    .select_related("article", "target")
                    .order_by("target_id", "article_id", "id")
                )
            transaction.set_rollback(True)

    return render(
        request,
        "stable/console/production_window_preview.html",
        _console_context(
            request,
            window=window,
            unsupported=unsupported,
            selected_articles=selected_articles,
            delivery_articles=delivery_articles,
            candidate_decisions=candidate_decisions,
            target_decisions=target_decisions,
            zero_reasons=zero_reasons,
        ),
    )


@login_required
@require_POST
def production_window_rerun(request: HttpRequest, window_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    window = get_object_or_404(ProductionWindow, pk=window_id)
    if window.kind not in {ProductionWindowKind.PUBLISH, ProductionWindowKind.QQ_PUSH}:
        messages.warning(request, "抓取窗口默认不从这里重跑，避免重新请求外部来源。")
        return redirect("console-production-window-detail", window_id=window.id)

    window.status = ProductionWindowStatus.PENDING
    window.rerun_count += 1
    window.triggered_by = request.user
    window.save(update_fields=["status", "rerun_count", "triggered_by", "updated_at"])
    claim = claim_window(window)
    if not claim.claimed:
        messages.warning(request, f"窗口当前不能重跑：{claim.reason}")
        return redirect("console-production-window-detail", window_id=window.id)

    window = claim.window
    try:
        if window.kind == ProductionWindowKind.PUBLISH:
            selection = select_publish_candidates(window.racing_region, window=window, now=window.window_end)
            published_ids = []
            failed_ids = []
            for article in selection.selected:
                try:
                    publish_article_automatically(article)
                    published_ids.append(article.id)
                except Exception:
                    failed_ids.append(article.id)
            window.status = ProductionWindowStatus.PARTIAL if failed_ids else ProductionWindowStatus.SUCCEEDED
            window.reason_summary = "manual_rerun_published" if published_ids else ",".join(selection.zero_reasons or ["manual_rerun_no_published_articles"])
            window.result_payload = {
                "published_article_ids": published_ids,
                "failed_article_ids": failed_ids,
                "zero_reasons": selection.zero_reasons,
                "manual_rerun": True,
            }
            window.last_error = ""
        else:
            online, status_error = BotPusher().is_online()
            if not online:
                reason = status_error or "onebot_offline"
                window.status = ProductionWindowStatus.FAILED
                window.reason_summary = reason
                window.last_error = reason
                window.result_payload = {"delivery_ids": [], "zero_reasons": [reason], "manual_rerun": True}
            else:
                result = select_qq_window_deliveries(window.racing_region, window=window, now=window.window_end)
                delivery_ids = []
                failed_ids = []
                for delivery in result.deliveries:
                    try:
                        dispatch_task(qq_push_delivery_task, delivery.id)
                        delivery_ids.append(delivery.id)
                    except Exception:
                        failed_ids.append(delivery.id)
                window.status = ProductionWindowStatus.PARTIAL if failed_ids else ProductionWindowStatus.SUCCEEDED
                window.reason_summary = "manual_rerun_queued" if delivery_ids else ",".join(result.zero_reasons or ["manual_rerun_no_deliveries"])
                window.result_payload = {
                    "delivery_ids": delivery_ids,
                    "failed_delivery_ids": failed_ids,
                    "zero_reasons": result.zero_reasons,
                    "manual_rerun": True,
                }
                window.last_error = ""
        window.finished_at = timezone.now()
        window.save(update_fields=["status", "finished_at", "reason_summary", "last_error", "result_payload", "updated_at"])
        log_operation(
            action_type="production_window_rerun",
            target_type="production_window",
            target_id=window.pk,
            detail=f"手动重跑 {window.kind} 窗口 {window.scope_key} @ {window.window_start}",
            admin=request.user,
        )
        messages.success(request, "窗口重跑已完成。")
    except Exception as exc:
        window.status = ProductionWindowStatus.FAILED
        window.finished_at = timezone.now()
        window.reason_summary = "manual_rerun_failed"
        window.last_error = str(exc)
        window.save(update_fields=["status", "finished_at", "reason_summary", "last_error", "updated_at"])
        messages.error(request, f"窗口重跑失败：{exc}")
    return redirect("console-production-window-detail", window_id=window.id)


@login_required
def source_create(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    if request.method == "POST":
        form = NewsSourceForm(request.POST)
        if form.is_valid():
            source = form.save()
            log_operation(
                action_type="source_created",
                target_type="source",
                target_id=source.pk,
                detail=f"创建来源 {source.name}",
                admin=request.user,
            )
            messages.success(request, "来源已创建。")
            return redirect("console-source-list")
    else:
        form = NewsSourceForm()
    return render(request, "stable/console/source_form.html", _console_context(request, form=form, page_title="新建来源"))


@login_required
def source_edit(request: HttpRequest, source_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    source = get_object_or_404(NewsSource, pk=source_id, deleted_at__isnull=True)
    if request.method == "POST":
        form = NewsSourceForm(request.POST, instance=source)
        if form.is_valid():
            source = form.save()
            log_operation(
                action_type="source_updated",
                target_type="source",
                target_id=source.pk,
                detail=f"更新来源 {source.name}",
                admin=request.user,
            )
            messages.success(request, "来源已更新。")
            return redirect("console-source-list")
    else:
        form = NewsSourceForm(instance=source)
    return render(request, "stable/console/source_form.html", _console_context(request, form=form, source=source, page_title=f"编辑来源：{source.name}"))


@login_required
@require_POST
def source_toggle(request: HttpRequest, source_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    source = get_object_or_404(NewsSource, pk=source_id, deleted_at__isnull=True)
    source.enabled = not source.enabled
    source.save(update_fields=["enabled", "updated_at"])
    log_operation(
        action_type="source_toggled",
        target_type="source",
        target_id=source.pk,
        detail=f"{'启用' if source.enabled else '停用'}来源 {source.name}",
        admin=request.user,
    )
    messages.success(request, f"已{'启用' if source.enabled else '停用'}来源。")
    return redirect("console-source-list")


@login_required
@require_POST
def source_delete(request: HttpRequest, source_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    source = get_object_or_404(NewsSource, pk=source_id, deleted_at__isnull=True)
    source.deleted_at = timezone.now()
    source.enabled = False
    source.save(update_fields=["deleted_at", "enabled", "updated_at"])
    log_operation(
        action_type="source_deleted",
        target_type="source",
        target_id=source.pk,
        detail=f"软删除来源 {source.name}",
        admin=request.user,
    )
    messages.success(request, "来源已删除。")
    return redirect("console-source-list")


@login_required
@require_POST
def source_test_crawl(request: HttpRequest, source_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    source = get_object_or_404(NewsSource, pk=source_id, deleted_at__isnull=True)
    if source.manual_pause_reason:
        messages.error(request, f"来源已人工暂停：{source.manual_pause_reason}")
        return redirect("console-source-list")
    if source.backoff_until and source.backoff_until > timezone.now():
        messages.error(request, f"来源处于自动降频/backoff，下一次允许抓取：{timezone.localtime(source.backoff_until):%Y-%m-%d %H:%M}")
        return redirect("console-source-list")
    dispatch_task(crawl_news_source_task, source.id)
    log_operation(
        action_type="source_test_crawl",
        target_type="source",
        target_id=source.pk,
        detail=f"手动抓取来源 {source.name}",
        admin=request.user,
    )
    messages.success(request, "抓取任务已触发。")
    return redirect("console-source-list")


@login_required
def term_list(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    queryset = TermEntry.objects.all().order_by("-updated_at", "-priority", "source_ja")
    queryset = _term_filters(queryset, request)
    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    pagination_params = request.GET.copy()
    pagination_params.pop("page", None)
    return render(
        request,
        "stable/console/term_list.html",
        _console_context(
            request,
            page_obj=page_obj,
            term_type_choices=TermType.choices,
            source_language_choices=[
                (SourceLanguage.JAPANESE, "日文"),
                (SourceLanguage.ENGLISH, "英文"),
                (SourceLanguage.CHINESE_TRADITIONAL, "繁体中文"),
            ],
            racing_region_choices=RacingRegion.choices,
            translation_status_choices=TermTranslationStatus.choices,
            pagination_querystring=pagination_params.urlencode(),
        ),
    )


@login_required
def term_create(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    initial = {}
    copy_id = request.GET.get("copy")
    if copy_id:
        source_term = get_object_or_404(TermEntry, pk=copy_id)
        initial = {
            "term_type": source_term.term_type,
            "source_language": source_term.source_language,
            "racing_region": source_term.racing_region,
            "source_ja": source_term.source_ja,
            "target_zh": source_term.target_zh,
            "translation_status": source_term.translation_status,
            "race_grade": source_term.race_grade,
            "priority": source_term.priority,
            "is_active": source_term.is_active,
            "notes": source_term.notes,
            "aliases_ja_text": serialize_aliases(source_term.aliases_ja),
            "aliases_zh_text": serialize_aliases(source_term.aliases_zh),
        }
    if request.method == "POST":
        form = TermEntryForm(request.POST)
        if form.is_valid():
            term = form.save()
            log_operation(
                action_type="term_created",
                target_type="term",
                target_id=term.pk,
                detail=f"创建术语 {term.source_ja} -> {term.target_zh}",
                admin=request.user,
            )
            messages.success(request, "术语已创建。")
            intent = request.POST.get("intent", "save")
            if intent == "save_new":
                return redirect("console-term-create")
            if intent == "save_continue":
                return redirect("console-term-edit", term_id=term.pk)
            return redirect("console-term-list")
    else:
        form = TermEntryForm(initial=initial)
    return render(
        request,
        "stable/console/term_form.html",
        _console_context(request, form=form, page_title="新建术语", submit_label="保存术语"),
    )


@login_required
def term_edit(request: HttpRequest, term_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    term = get_object_or_404(TermEntry, pk=term_id)
    if request.method == "POST":
        form = TermEntryForm(request.POST, instance=term)
        if form.is_valid():
            term = form.save()
            log_operation(
                action_type="term_updated",
                target_type="term",
                target_id=term.pk,
                detail=f"更新术语 {term.source_ja} -> {term.target_zh}",
                admin=request.user,
            )
            messages.success(request, "术语已更新。")
            intent = request.POST.get("intent", "save")
            if intent == "save_new":
                return redirect("console-term-create")
            if intent == "save_continue":
                return redirect("console-term-edit", term_id=term.pk)
            return redirect("console-term-list")
    else:
        form = TermEntryForm(instance=term)
    return render(
        request,
        "stable/console/term_form.html",
        _console_context(request, form=form, term=term, page_title="编辑术语", submit_label="保存修改"),
    )


@login_required
@require_POST
def term_toggle_active(request: HttpRequest, term_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    term = get_object_or_404(TermEntry, pk=term_id)
    term.is_active = not term.is_active
    term.save(update_fields=["is_active", "updated_at"])
    sync_all_term_alias_active(term)
    log_operation(
        action_type="term_toggled",
        target_type="term",
        target_id=term.pk,
        detail=f"{'启用' if term.is_active else '停用'}术语 {term.source_ja}",
        admin=request.user,
    )
    messages.success(request, f"术语已{'启用' if term.is_active else '停用'}。")
    return redirect(request.POST.get("next") or "console-term-list")


@login_required
def term_import(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    preview = None
    commit_result = None
    preview_raw = request.session.get(TERM_IMPORT_SESSION_KEY)
    if preview_raw:
        preview = preview_from_session_value(preview_raw)

    if request.method == "POST":
        action = request.POST.get("action", "preview")
        if action == "commit":
            if not preview:
                messages.error(request, "当前没有可提交的导入预检结果，请先执行预检。")
                return redirect("console-term-import")
            commit_result = commit_term_import(preview["rows"], preview["import_mode"])
            request.session.pop(TERM_IMPORT_SESSION_KEY, None)
            preview = None
            log_operation(
                action_type="term_import_committed",
                target_type="term_import",
                target_id="",
                detail=(
                    f"术语导入完成，总计 {commit_result['total']} 条，"
                    f"新增 {commit_result['success_count']} 条，"
                    f"更新 {commit_result['update_count']} 条，"
                    f"跳过 {commit_result['skipped_count']} 条"
                ),
                admin=request.user,
            )
            messages.success(request, "术语导入已完成。")
            form = TermImportForm()
        else:
            form = TermImportForm(request.POST, request.FILES)
            if form.is_valid():
                preview = preview_term_import(
                    csv_file=form.cleaned_data.get("csv_file"),
                    csv_text=form.cleaned_data.get("csv_text", ""),
                    import_mode=form.cleaned_data["import_mode"],
                )
                request.session[TERM_IMPORT_SESSION_KEY] = preview_to_session_value(preview)
                log_operation(
                    action_type="term_import_previewed",
                    target_type="term_import",
                    target_id="",
                    detail=(
                        f"术语导入预检，总计 {preview['summary']['total']} 条，"
                        f"错误 {preview['summary']['error_count']} 条"
                    ),
                    admin=request.user,
                )
                messages.success(request, "预检完成，请确认结果后再提交导入。")
    else:
        form = TermImportForm()

    return render(
        request,
        "stable/console/term_import.html",
        _console_context(request, form=form, preview=preview, commit_result=commit_result),
    )


@login_required
def term_candidate_list(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    queryset = TermCandidate.objects.select_related("accepted_term", "reviewed_by").order_by("-last_seen_at", "-confidence")
    queryset = _term_candidate_filters(queryset, request)
    paginator = Paginator(queryset, 20)
    return render(
        request,
        "stable/console/term_candidate_list.html",
        _console_context(
            request,
            page_obj=paginator.get_page(request.GET.get("page")),
            status_choices=TermCandidateStatus.choices,
            term_type_choices=[choice for choice in TermType.choices if choice[0] in {"horse", "race", "jockey", "owner"}],
            sources=NewsSource.objects.filter(deleted_at__isnull=True).order_by("name"),
        ),
    )


@login_required
def term_candidate_detail(request: HttpRequest, candidate_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    candidate = get_object_or_404(
        TermCandidate.objects.select_related(
            "accepted_term", "merged_into_candidate", "merged_into_term", "reviewed_by"
        ).prefetch_related("evidence__article"),
        pk=candidate_id,
    )
    return render(
        request,
        "stable/console/term_candidate_detail.html",
        _console_context(
            request,
            candidate=candidate,
            accept_form=TermCandidateAcceptForm(candidate=candidate),
            merge_form=TermCandidateMergeForm(candidate=candidate),
            review_form=TermCandidateReviewForm(),
        ),
    )


@login_required
@require_POST
def term_candidate_accept(request: HttpRequest, candidate_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    candidate = get_object_or_404(TermCandidate, pk=candidate_id)
    form = TermCandidateAcceptForm(request.POST, candidate=candidate)
    if form.is_valid():
        try:
            term = accept_candidate(candidate, form.normalized_payload, request.user)
            messages.success(request, f"候选已接受并创建正式术语：{term.source_ja} -> {term.target_zh}")
            return redirect("console-term-candidate-detail", candidate_id=candidate.pk)
        except ValueError as exc:
            form.add_error(None, str(exc))
    return render(
        request,
        "stable/console/term_candidate_detail.html",
        _console_context(
            request,
            candidate=candidate,
            accept_form=form,
            merge_form=TermCandidateMergeForm(candidate=candidate),
            review_form=TermCandidateReviewForm(),
        ),
        status=400,
    )


@login_required
@require_POST
def term_candidate_merge(request: HttpRequest, candidate_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    candidate = get_object_or_404(TermCandidate, pk=candidate_id)
    form = TermCandidateMergeForm(request.POST, candidate=candidate)
    if form.is_valid():
        try:
            merge_candidate(
                candidate,
                request.user,
                target_candidate=form.cleaned_data.get("target_candidate"),
                target_term=form.cleaned_data.get("target_term"),
                add_as_alias=form.cleaned_data.get("add_as_alias", False),
                notes=form.cleaned_data.get("review_notes", ""),
            )
            messages.success(request, "候选已合并。")
            return redirect("console-term-candidate-detail", candidate_id=candidate.pk)
        except ValueError as exc:
            form.add_error(None, str(exc))
    return render(
        request,
        "stable/console/term_candidate_detail.html",
        _console_context(
            request,
            candidate=candidate,
            accept_form=TermCandidateAcceptForm(candidate=candidate),
            merge_form=form,
            review_form=TermCandidateReviewForm(),
        ),
        status=400,
    )


def _review_term_candidate(request: HttpRequest, candidate_id: int, status: str):
    denied = _ensure_staff(request)
    if denied:
        return denied
    candidate = get_object_or_404(TermCandidate, pk=candidate_id)
    form = TermCandidateReviewForm(request.POST)
    if form.is_valid():
        try:
            set_candidate_status(candidate, request.user, status, form.cleaned_data.get("review_notes", ""))
            messages.success(request, f"候选状态已更新为“{TermCandidateStatus(status).label}”。")
        except ValueError as exc:
            messages.error(request, str(exc))
    return redirect("console-term-candidate-detail", candidate_id=candidate.pk)


@login_required
@require_POST
def term_candidate_reject(request: HttpRequest, candidate_id: int):
    return _review_term_candidate(request, candidate_id, TermCandidateStatus.REJECTED)


@login_required
@require_POST
def term_candidate_ignore(request: HttpRequest, candidate_id: int):
    return _review_term_candidate(request, candidate_id, TermCandidateStatus.IGNORED)


@login_required
@require_POST
def term_candidate_batch_review(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    status = request.POST.get("status", "")
    if status not in {TermCandidateStatus.REJECTED, TermCandidateStatus.IGNORED}:
        messages.error(request, "批量操作仅支持拒绝或忽略。")
        return redirect("console-term-candidate-list")
    candidates = list(
        TermCandidate.objects.filter(
            pk__in=request.POST.getlist("candidate_ids"),
            status=TermCandidateStatus.PENDING,
        )
    )
    for candidate in candidates:
        set_candidate_status(candidate, request.user, status, request.POST.get("review_notes", ""))
    messages.success(request, f"已批量处理 {len(candidates)} 条候选。")
    return redirect("console-term-candidate-list")


@login_required
@require_POST
def article_discover_terms(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    dispatch_task(discover_term_candidates_task, article.id)
    log_operation(
        action_type="article_term_discovery_triggered",
        target_type="article",
        target_id=article.pk,
        detail=f"手动触发术语发现《{article.effective_title}》",
        admin=request.user,
    )
    messages.success(request, "已触发单篇文章术语发现。")
    return redirect(request.POST.get("next") or reverse("console-candidate-detail", args=[article.pk]))


@login_required
def candidate_list(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    queryset = NewsArticle.objects.select_related("source_config", "cover_media_asset").exclude(
        workflow_status__in=[WorkflowStatus.PUBLISHED, WorkflowStatus.WITHDRAWN]
    )
    queryset = _article_filters(queryset, request)
    paginator = Paginator(queryset, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    sources = NewsSource.objects.filter(deleted_at__isnull=True).order_by("name")
    return render(
        request,
        "stable/console/candidate_list.html",
        _console_context(
            request,
            page_obj=page_obj,
            sources=sources,
            workflow_choices=WorkflowStatus.choices,
            translation_status_choices=ArticleTranslationStatus.choices,
            automation_status_choices=AutomationStatus.choices,
            review_mode_choices=ReviewMode.choices,
        ),
    )


@login_required
def candidate_detail(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(
        NewsArticle.objects.select_related("source_config", "cover_media_asset").prefetch_related(
            "images", "media_assets", "translation_runs", "automation_logs"
        ),
        pk=article_id,
    )
    return render(
        request,
        "stable/console/candidate_detail.html",
        _console_context(
            request,
            article=article,
            term_type_choices=TermType.choices,
            quick_term_followup=_pop_quick_term_followup(request, article, "candidate"),
        ),
    )


def _message_quick_term_errors(request: HttpRequest, form: ArticleQuickTermForm, normalized: dict | None = None) -> None:
    existing = None
    if normalized and normalized.get("term_type") and normalized.get("source_ja"):
        existing = find_term_by_source_alias(
            term_type=normalized["term_type"],
            source_language=normalized.get("source_language") or "ja",
            source_text=normalized["source_ja"],
        )
    if existing:
        messages.error(
            request,
            format_html(
                '创建失败：同一术语类型和原文语言下已存在相同原文，<a href="{}">打开已有术语 #{}</a>。',
                reverse("console-term-edit", args=[existing.pk]),
                existing.pk,
            ),
        )

    for field_name, field_errors in form.errors.items():
        label = form.fields[field_name].label if field_name in form.fields else "术语"
        for error in field_errors:
            messages.error(request, f"{label}：{error}")


def _article_context_url(article: NewsArticle, source_context: str) -> str:
    if source_context == "editor":
        return reverse("console-article-editor", args=[article.pk])
    return reverse("console-candidate-detail", args=[article.pk])


def _normalize_article_context(value: str | None) -> str:
    return "editor" if value == "editor" else "candidate"


def _article_context_from_request(article: NewsArticle, request: HttpRequest) -> str:
    explicit = request.POST.get("source_context")
    if explicit in {"candidate", "editor"}:
        return explicit
    if request.POST.get("next") == reverse("console-article-editor", args=[article.pk]):
        return "editor"
    return "candidate"


def _safe_article_return_url(article: NewsArticle, requested_next: str | None, source_context: str | None = None) -> str:
    allowed = {
        reverse("console-candidate-detail", args=[article.pk]),
        reverse("console-article-editor", args=[article.pk]),
    }
    if requested_next in allowed:
        return requested_next
    return _article_context_url(article, _normalize_article_context(source_context))


def _quick_term_followup_key(article: NewsArticle, source_context: str) -> str:
    return f"{_normalize_article_context(source_context)}:{article.pk}"


def _quick_term_followups(request: HttpRequest) -> dict:
    pending = request.session.get(QUICK_TERM_FOLLOWUP_SESSION_KEY)
    return pending if isinstance(pending, dict) else {}


def _store_quick_term_followup(request: HttpRequest, article: NewsArticle, term: TermEntry, source_context: str) -> None:
    pending = _quick_term_followups(request).copy()
    normalized_context = _normalize_article_context(source_context)
    pending[_quick_term_followup_key(article, normalized_context)] = {
        "article_id": article.pk,
        "term_id": term.pk,
        "source_context": normalized_context,
    }
    request.session[QUICK_TERM_FOLLOWUP_SESSION_KEY] = pending
    request.session.modified = True


def _pop_quick_term_followup(request: HttpRequest, article: NewsArticle, source_context: str) -> dict | None:
    pending = _quick_term_followups(request)
    key = _quick_term_followup_key(article, source_context)
    payload = pending.get(key)
    if payload is None:
        return None
    if payload.get("article_id") != article.pk:
        return None
    if payload.get("source_context") != source_context:
        return None
    term = TermEntry.objects.filter(pk=payload.get("term_id"), is_active=True).first()
    if term is None:
        pending = pending.copy()
        pending.pop(key, None)
        request.session[QUICK_TERM_FOLLOWUP_SESSION_KEY] = pending
        request.session.modified = True
        return None
    pending = pending.copy()
    pending.pop(key, None)
    request.session[QUICK_TERM_FOLLOWUP_SESSION_KEY] = pending
    request.session.modified = True
    return {"term": term, "source_context": source_context}


def _field_names_text(field_names: list[str]) -> str:
    labels = {
        "translated_title_zh": "机器标题",
        "translated_body_zh": "机器正文",
        "translated_summary_zh": "机器摘要",
        "base_translation_zh": "基准翻译稿",
        "title_zh": "发布标题",
        "body_zh": "发布正文",
        "summary_zh": "发布摘要",
        "push_summary_zh": "推送摘要",
    }
    return "、".join(labels.get(field_name, field_name) for field_name in field_names)


@login_required
@require_POST
def article_quick_term_create(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    source_context = _article_context_from_request(article, request)
    next_url = _safe_article_return_url(article, request.POST.get("next"), source_context)
    form = ArticleQuickTermForm(request.POST)
    normalized = None
    if form.is_valid():
        payload = form.to_payload(article)
        normalized, errors = validate_term_payload(payload)
        for field_name, field_errors in errors.items():
            mapped_field = field_name if field_name in form.fields else None
            for error in field_errors:
                form.add_error(mapped_field, error)
        if not errors:
            term = TermEntry.objects.create(**normalized)
            sync_term_source_aliases(term, term.source_language)
            log_operation(
                action_type="article_quick_term_created",
                target_type="term",
                target_id=term.pk,
                detail=f"从文章 #{article.pk} 快速创建术语 {term.source_ja} -> {term.target_zh}",
                admin=request.user,
            )
            _store_quick_term_followup(request, article, term, source_context)
            messages.success(request, f"术语已创建：{term.source_ja} -> {term.target_zh}")
            return redirect(next_url)

    _message_quick_term_errors(request, form, normalized)
    return redirect(next_url)


@login_required
@require_POST
def article_apply_created_term(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    source_context = _article_context_from_request(article, request)
    next_url = _safe_article_return_url(article, request.POST.get("next"), source_context)
    term = get_object_or_404(TermEntry, pk=request.POST.get("term_id"), is_active=True)

    result = apply_created_term_to_article(article, term)
    detail = (
        f"应用术语 #{term.pk} {term.source_ja} -> {term.target_zh} 到文章 #{article.pk}；"
        f"更新字段：{','.join(result.updated_fields) or '-'}；"
        f"跳过字段：{','.join(result.skipped_fields) or '-'}"
    )
    log_operation(
        action_type="article_created_term_applied",
        target_type="article",
        target_id=article.pk,
        detail=detail,
        admin=request.user,
    )

    if result.updated_fields:
        messages.success(request, f"已应用该术语，更新字段：{_field_names_text(result.updated_fields)}。")
    else:
        messages.info(request, "没有可更新字段，或当前稿件中没有命中该术语。")
    if result.skipped_fields:
        messages.warning(request, f"已保护人工编辑字段：{_field_names_text(result.skipped_fields)}。")
    return redirect(next_url)


@login_required
@require_POST
def candidate_retranslate(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    source_context = _article_context_from_request(article, request)
    next_url = _safe_article_return_url(article, request.POST.get("next"), source_context)
    dispatch_task(translate_article_task, article.id)
    log_operation(
        action_type="article_retranslated",
        target_type="article",
        target_id=article.pk,
        detail=f"重新触发翻译《{article.effective_title}》，任务已派发",
        admin=request.user,
    )
    messages.success(request, "已重新触发翻译。")
    return redirect(next_url)


@login_required
@require_POST
def candidate_batch_retranslate(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    limit = min(max(int(request.POST.get("limit", "20")), 1), 200)
    queryset = _translation_queue_queryset(request)
    article_ids = list(queryset.values_list("id", flat=True)[:limit])
    if not article_ids:
        messages.warning(request, "当前筛选条件下没有需要补翻的文章。")
        return redirect("console-candidate-list")
    dispatch_task(batch_translate_articles_task, article_ids=article_ids, limit=limit)
    log_operation(
        action_type="article_batch_retranslated",
        target_type="article",
        target_id=",".join(str(article_id) for article_id in article_ids[:10]),
        detail=f"批量触发翻译 {len(article_ids)} 篇文章",
        admin=request.user,
    )
    messages.success(request, f"已触发 {len(article_ids)} 篇文章的翻译任务。")
    return redirect("console-candidate-list")


@login_required
@require_POST
def candidate_ignore(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    article.workflow_status = WorkflowStatus.IGNORED
    article.review_mode = ReviewMode.IGNORED
    article.automation_status = AutomationStatus.IGNORED
    article.ignored_at = timezone.now()
    article.save(update_fields=["workflow_status", "review_mode", "automation_status", "ignored_at", "updated_at"])
    log_operation(
        action_type="article_ignored",
        target_type="article",
        target_id=article.pk,
        detail=f"忽略候选新闻《{article.effective_title}》",
        admin=request.user,
    )
    messages.success(request, "候选新闻已忽略。")
    return redirect("console-candidate-list")


@login_required
@require_POST
def candidate_mark_manual(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    article.review_mode = ReviewMode.MANUAL
    article.automation_status = AutomationStatus.MANUAL_REVIEW_REQUIRED
    article.workflow_status = WorkflowStatus.PENDING_REVIEW
    article.decision_summary = article.decision_summary or "人工接管：管理员手动转入审核"
    article.save(update_fields=["review_mode", "automation_status", "workflow_status", "decision_summary", "updated_at"])
    log_operation(
        action_type="article_marked_manual",
        target_type="article",
        target_id=article.pk,
        detail=f"手动转入人工审核《{article.effective_title}》",
        admin=request.user,
    )
    messages.success(request, "已转入人工审核。")
    return redirect(request.POST.get("next") or reverse("console-candidate-detail", args=[article.pk]))


@login_required
@require_POST
def candidate_run_automation(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    dispatch_task(process_article_automation_task, article.id)
    log_operation(
        action_type="article_automation_triggered",
        target_type="article",
        target_id=article.pk,
        detail=f"手动触发自动化处理《{article.effective_title}》",
        admin=request.user,
    )
    messages.success(request, "已触发自动化处理。")
    return redirect(request.POST.get("next") or reverse("console-candidate-detail", args=[article.pk]))


@login_required
def article_editor(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(
        NewsArticle.objects.select_related("source_config", "cover_media_asset").prefetch_related(
            "images", "media_assets", "translation_runs"
        ),
        pk=article_id,
    )
    article.ensure_editable_fields()
    if request.method == "POST":
        form = ArticleEditorForm(request.POST, instance=article)
        if form.is_valid():
            article = form.save(commit=False)
            article.mark_manual_edits(["title_zh", "summary_zh", "body_zh", "source_note", "editor_notes", "tags_json"])
            intent = request.POST.get("intent", "save")
            if intent == "submit_review":
                article.workflow_status = WorkflowStatus.PENDING_REVIEW
            elif intent == "reject":
                article.workflow_status = WorkflowStatus.REJECTED
            elif intent == "publish":
                if not article.cover_media_asset and not request.POST.get("publish_without_cover"):
                    messages.warning(request, "当前没有封面图，如确认无封面发布，请再次点击“发布”并勾选无封面确认。")
                    return render(
                        request,
                        "stable/console/article_editor.html",
                        _console_context(
                            request,
                            form=form,
                            article=article,
                            allow_publish_without_cover=True,
                            term_type_choices=TermType.choices,
                            quick_term_followup=None,
                        ),
                    )
                article.workflow_status = WorkflowStatus.PUBLISHED
                article.published_to_web_at = timezone.now()
                article.published_by = request.user
                article.published_by_mode = PublishedByMode.MANUAL
            elif intent == "withdraw":
                article.workflow_status = WorkflowStatus.WITHDRAWN
                article.withdrawn_at = timezone.now()
            else:
                if article.workflow_status in {WorkflowStatus.PENDING_TRANSLATION, WorkflowStatus.TRANSLATION_FAILED}:
                    article.workflow_status = WorkflowStatus.PENDING_EDIT
            article.save()
            form.save_related_regions(article)
            if intent == "publish":
                from stable.services.qq_auto_push import enqueue_qq_auto_push_for_article

                enqueue_qq_auto_push_for_article(article.id)
                dispatch_task(scan_article_horse_links_task, article_id=article.id, commit=True)
            action_map = {
                "save": "article_saved",
                "autosave": "article_autosaved",
                "submit_review": "article_submitted_review",
                "reject": "article_rejected",
                "publish": "article_published",
                "withdraw": "article_withdrawn",
            }
            log_operation(
                action_type=action_map.get(intent, "article_saved"),
                target_type="article",
                target_id=article.pk,
                detail=f"{intent}《{article.effective_title}》",
                admin=request.user,
            )
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"saved": True, "workflow_status": article.workflow_status})
            messages.success(request, "文章已保存。" if intent in {"save", "autosave"} else "操作已完成。")
            if intent == "publish":
                return redirect("console-published-list")
            return redirect("console-article-editor", article_id=article.pk)
    else:
        form = ArticleEditorForm(instance=article)
    return render(
        request,
        "stable/console/article_editor.html",
        _console_context(
            request,
            form=form,
            article=article,
            allow_publish_without_cover=False,
            term_type_choices=TermType.choices,
            quick_term_followup=_pop_quick_term_followup(request, article, "editor"),
        ),
    )


@login_required
def article_preview(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    return render(request, "stable/console/article_preview.html", _console_context(request, article=article))


@login_required
@require_POST
def article_localize_image(request: HttpRequest, article_id: int, image_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    image = get_object_or_404(NewsImage, pk=image_id, article=article)
    asset = localize_news_image(article, image)
    log_operation(
        action_type="image_localized",
        target_type="media_asset",
        target_id=asset.pk,
        detail=f"为《{article.effective_title}》本地化图片",
        admin=request.user,
    )
    messages.success(request, "图片已本地化，可用于正文或封面。")
    return redirect("console-article-editor", article_id=article.pk)


@login_required
@require_POST
def article_set_cover(request: HttpRequest, article_id: int, asset_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    asset = get_object_or_404(MediaAsset, pk=asset_id, article=article)
    set_cover_asset(article, asset)
    log_operation(
        action_type="cover_set",
        target_type="media_asset",
        target_id=asset.pk,
        detail=f"为《{article.effective_title}》设置封面",
        admin=request.user,
    )
    messages.success(request, "封面图已更新。")
    return redirect("console-article-editor", article_id=article.pk)


@login_required
@require_POST
def article_upload_cover(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    upload = request.FILES.get("cover_file")
    if not upload:
        messages.error(request, "请选择要上传的图片。")
        return redirect("console-article-editor", article_id=article.pk)
    relative_dir = Path("uploaded_covers") / f"{timezone.localtime():%Y/%m/%d}"
    filename = f"{uuid.uuid4().hex}{Path(upload.name).suffix or '.jpg'}"
    relative_path = (relative_dir / filename).as_posix()
    default_storage.save(relative_path, upload)
    asset = MediaAsset.objects.create(
        article=article,
        original_image_url="",
        internal_image_url=relative_path,
        storage_provider=current_media_provider(),
    )
    set_cover_asset(article, asset)
    log_operation(
        action_type="cover_uploaded",
        target_type="media_asset",
        target_id=asset.pk,
        detail=f"为《{article.effective_title}》上传封面",
        admin=request.user,
    )
    messages.success(request, "封面已上传。")
    return redirect("console-article-editor", article_id=article.pk)


@login_required
def published_list(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    queryset = NewsArticle.objects.select_related("source_config", "cover_media_asset").filter(workflow_status=WorkflowStatus.PUBLISHED)
    queryset = _article_filters(queryset, request)
    paginator = Paginator(queryset, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    sources = NewsSource.objects.filter(deleted_at__isnull=True).order_by("name")
    return render(
        request,
        "stable/console/published_list.html",
        _console_context(request, page_obj=page_obj, sources=sources, workflow_choices=WorkflowStatus.choices),
    )


@login_required
def operation_log_list(request: HttpRequest):
    denied = _ensure_staff(request)
    if denied:
        return denied
    logs = OperationLog.objects.select_related("admin").all()
    automation_logs = AutomationLog.objects.select_related("article").all()[:20]
    notification_logs = NotificationLog.objects.all()[:20]
    paginator = Paginator(logs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "stable/console/logs.html",
        _console_context(request, page_obj=page_obj, automation_logs=automation_logs, notification_logs=notification_logs),
    )


def _public_published_articles(region: str = ""):
    queryset = (
        NewsArticle.objects.select_related("cover_media_asset")
        .prefetch_related("images", "related_region_links")
        .filter(workflow_status=WorkflowStatus.PUBLISHED, published_to_web_at__isnull=False)
        .order_by("-published_to_web_at", "-id")
    )
    if region:
        queryset = filter_articles_visible_in_region(queryset, region)
    return queryset


def _resolve_public_region(value: str) -> str:
    candidate = (value or "").strip()
    valid_regions = {tab["value"] for tab in PUBLIC_REGION_TABS if tab["value"]}
    return candidate if candidate in valid_regions else ""


def _region_tab_context(active_region: str) -> list[dict]:
    tabs: list[dict] = []
    for tab in PUBLIC_REGION_TABS:
        value = tab["value"]
        tabs.append(
            {
                **tab,
                "is_active": value == active_region,
                "url": "/" if not value else f"/?region={value}",
            }
        )
    return tabs


def _public_horse_queryset():
    return (
        HorseProfile.objects.filter(review_status=HorseProfileStatus.PUBLISHED)
        .select_related("primary_term", "sire_horse_profile", "dam_horse_profile")
        .order_by("-is_featured", "racing_region", "display_name_zh", "original_name", "id")
    )


def _follow_token_hash_from_request(request: HttpRequest) -> str:
    cookie_value = request.COOKIES.get(FOLLOW_COOKIE_NAME, "")
    if not cookie_value:
        return ""
    try:
        return token_hash_from_cookie(cookie_value)
    except (BadSignature, SignatureExpired):
        return ""


def _public_followed_entries(request: HttpRequest, *, limit: int = 6) -> list[dict]:
    token_hash = _follow_token_hash_from_request(request)
    if not token_hash:
        return []
    return followed_articles(token_hash, limit=limit)


def _race_priority_score(article: NewsArticle) -> int:
    signals = article.decision_reason.get("signals") if isinstance(article.decision_reason, dict) else {}
    priority = signals.get("race_priority") if isinstance(signals, dict) else ""
    return {"P0": 3, "P1": 2}.get(priority, 0)


def _headline_sort_key(article: NewsArticle) -> tuple:
    published_at = article.published_to_web_at or article.published_at
    return (
        _race_priority_score(article),
        article.score_total or 0,
        1 if article.cover_image_url else 0,
        published_at.timestamp(),
        article.id,
    )


def _select_headline_article(queryset) -> NewsArticle | None:
    now = timezone.now()
    for threshold in (now - timedelta(hours=72), now - timedelta(days=7), None):
        candidates = queryset
        if threshold is not None:
            candidates = candidates.filter(published_to_web_at__gte=threshold)
        candidate_list = list(candidates[:PUBLIC_HOT_CANDIDATE_LIMIT])
        if candidate_list:
            return max(candidate_list, key=_headline_sort_key)
    return None


def _snapshot_sort_key(snapshot: NewsSnapshot) -> tuple:
    mode_score = 2 if snapshot.source_mode == SourceMode.ACCESS else 1
    rank_score = -(snapshot.rank or 9999)
    engagement = (snapshot.comment_count or 0) + (snapshot.attention_count or 0)
    return (mode_score, rank_score, engagement, snapshot.captured_at.timestamp(), snapshot.id)


def _hot_article_sort_key(entry: dict) -> tuple:
    snapshot = entry.get("snapshot")
    if snapshot:
        return (2, *_snapshot_sort_key(snapshot), entry["article"].published_to_web_at.timestamp())
    return (0, entry["article"].score_total or 0, entry["article"].published_to_web_at.timestamp(), entry["article"].id)


def _build_hot_articles(queryset) -> list[dict]:
    candidates = list(queryset[:PUBLIC_HOT_CANDIDATE_LIMIT])
    article_ids = [article.id for article in candidates]
    if not article_ids:
        return []
    snapshots = NewsSnapshot.objects.filter(
        article_id__in=article_ids,
        source_mode__in=[SourceMode.ACCESS, SourceMode.ATTENTION],
    )
    best_snapshots: dict[int, NewsSnapshot] = {}
    for snapshot in snapshots:
        current = best_snapshots.get(snapshot.article_id)
        if current is None or _snapshot_sort_key(snapshot) > _snapshot_sort_key(current):
            best_snapshots[snapshot.article_id] = snapshot

    entries = [{"article": article, "snapshot": best_snapshots.get(article.id)} for article in candidates]
    return sorted(entries, key=_hot_article_sort_key, reverse=True)[:PUBLIC_HOT_DISPLAY_LIMIT]


def _race_calendar_queryset(request: HttpRequest):
    queryset = RaceEvent.objects.filter(visibility_status=RaceEventVisibility.PUBLISHED)
    tab = request.GET.get("tab", "key").strip() or "key"
    region = request.GET.get("region", "").strip()
    direction = request.GET.get("direction", "").strip()
    cursor = request.GET.get("cursor", "").strip()
    year = request.GET.get("year", "").strip()
    query = request.GET.get("q", "").strip()
    today = timezone.localdate()
    if tab == "key":
        queryset = queryset.filter(Q(priority__in=[RaceEventPriority.P0, RaceEventPriority.P1]) | Q(is_featured=True))
    if region:
        queryset = queryset.filter(country_region=region)
    if year.isdigit():
        queryset = queryset.filter(year=int(year))
    if query:
        series_name_match = (
            Q(race_series__names__text__icontains=query)
            & (Q(race_series__names__valid_from_year=0) | Q(race_series__names__valid_from_year__lte=F("year")))
            & (Q(race_series__names__valid_to_year=0) | Q(race_series__names__valid_to_year__gte=F("year")))
        )
        queryset = queryset.filter(
            Q(chinese_name__icontains=query)
            | Q(original_name__icontains=query)
            | Q(aliases__text__icontains=query)
            | Q(race_series__canonical_name_original__icontains=query)
            | Q(race_series__chinese_name__icontains=query)
            | series_name_match
        ).distinct()
    if cursor and not (year or query):
        try:
            cursor_date = datetime.fromisoformat(cursor).date()
        except ValueError:
            cursor_date = today
        if direction == "past":
            queryset = queryset.filter(local_date__lt=cursor_date).order_by("-local_date", "-local_start_time", "id")
        elif direction == "future":
            queryset = queryset.filter(local_date__gt=cursor_date).order_by("local_date", "local_start_time", "id")
        else:
            queryset = queryset.order_by("local_date", "local_start_time", "id")
    elif not (year or query):
        start = today - timedelta(days=RACE_CALENDAR_WINDOW_DAYS)
        end = today + timedelta(days=RACE_CALENDAR_WINDOW_DAYS)
        queryset = queryset.filter(Q(local_date__gte=start, local_date__lte=end) | Q(local_date__isnull=True)).order_by("local_date", "local_start_time", "id")
    else:
        queryset = queryset.order_by("local_date", "local_start_time", "id")
    return queryset.prefetch_related("results")[:RACE_CALENDAR_PAGE_SIZE], {
        "tab": tab,
        "region": region,
        "direction": direction,
        "cursor": cursor,
        "year": year,
        "q": query,
    }


def _group_race_events_by_date(events):
    groups: list[dict] = []
    current_date = object()
    current_group = None
    read_now = timezone.now()
    live_public_reads = resolve_race_live_public_reads(
        event_ids=[event.pk for event in events],
        now=read_now,
    )
    for event in events:
        live_public_read = live_public_reads[event.pk]
        if live_public_read.revision_id is not None and not live_public_read.visible:
            event.top_results = []
        else:
            event.top_results = list(event.results.all()[:5])
        _attach_result_display_positions(event.top_results)
        if event.local_date != current_date:
            current_date = event.local_date
            current_group = {"date": event.local_date, "events": []}
            groups.append(current_group)
        current_group["events"].append(event)
    _attach_race_term_display_names([(event, event.top_results) for event in events])
    return groups


def _attach_result_display_positions(results):
    non_finish_statuses = {
        RaceRunnerStatus.SCRATCHED,
        RaceRunnerStatus.WITHDRAWN,
        RaceRunnerStatus.NON_RUNNER,
        RaceRunnerStatus.DISQUALIFIED,
        RaceRunnerStatus.DID_NOT_FINISH,
        RaceRunnerStatus.PULLED_UP,
        RaceRunnerStatus.UNSEATED_RIDER,
        RaceRunnerStatus.FELL,
        RaceRunnerStatus.REFUSED,
    }
    status_labels = dict(RaceRunnerStatus.choices)
    for result in results:
        source_refs = result.source_refs or {}
        official_position = (
            result.official_finish_position
            or source_refs.get("official_finish_position")
        )
        if official_position is None and result.running_status in non_finish_statuses:
            result.display_finish_position = status_labels[result.running_status]
        else:
            result.display_finish_position = official_position or result.finish_position
    return results


def _race_name_identity(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip().lower()


def _race_number_sort_key(value: str):
    normalized = unicodedata.normalize("NFKC", value or "").strip().upper()
    if not normalized:
        return (2, 0, "")
    match = re.match(r"^(\d+)(.*)$", normalized)
    if match:
        return (0, int(match.group(1)), match.group(2).strip())
    return (1, 0, normalized)


def _runner_display_sort_key(runner, country_region: str):
    # These regions currently publish a stable race/program number. Draw is the
    # fallback for feeds that omit it; keeping this mapping explicit allows a
    # region to switch its primary convention without changing stored source order.
    primary_field_by_region = {
        RacingRegion.JAPAN: "horse_number",
        RacingRegion.HONG_KONG: "horse_number",
        RacingRegion.UNITED_KINGDOM: "horse_number",
        RacingRegion.FRANCE: "horse_number",
        RacingRegion.UNITED_STATES: "horse_number",
    }
    primary_field = primary_field_by_region.get(country_region, "horse_number")
    secondary_field = "barrier" if primary_field == "horse_number" else "horse_number"
    primary_value = getattr(runner, primary_field, "") or getattr(runner, secondary_field, "")
    return (
        _race_number_sort_key(primary_value),
        _race_number_sort_key(getattr(runner, secondary_field, "")),
        runner.sort_order,
        runner.pk,
    )


def _sort_runners_for_display(runners, country_region: str):
    return sorted(runners, key=lambda runner: _runner_display_sort_key(runner, country_region))


def _attach_race_term_display_names(event_records):
    records = [(event, item) for event, items in event_records for item in items]
    source_names = {
        str(value).strip()
        for _event, item in records
        for value in (getattr(item, "horse_name", ""), getattr(item, "jockey_name", ""))
        if value
    }
    names_by_type = {
        TermType.HORSE: {
            _race_name_identity(item.horse_name)
            for _event, item in records
            if getattr(item, "horse_name", "")
        },
        TermType.JOCKEY: {
            _race_name_identity(item.jockey_name)
            for _event, item in records
            if getattr(item, "jockey_name", "")
        },
    }
    all_names = set().union(*names_by_type.values())
    query_names = {value.lower() for value in source_names} | all_names
    candidates: dict[tuple[str, str], list[TermEntry]] = {}
    if all_names:
        primary_terms = (
            TermEntry.objects.filter(is_active=True, term_type__in=names_by_type)
            .annotate(source_name_lower=Lower("source_ja"))
            .filter(source_name_lower__in=query_names)
        )
        for term in primary_terms:
            identity = _race_name_identity(term.source_ja)
            if identity in names_by_type[term.term_type]:
                candidates.setdefault((term.term_type, identity), []).append(term)

        aliases = (
            TermAlias.objects.select_related("term")
            .filter(is_active=True, term__is_active=True, term__term_type__in=names_by_type)
            .annotate(source_name_lower=Lower("text"))
            .filter(source_name_lower__in=query_names)
        )
        for alias in aliases:
            identity = _race_name_identity(alias.text)
            if identity in names_by_type[alias.term.term_type]:
                candidates.setdefault((alias.term.term_type, identity), []).append(alias.term)

    def display_name(value: str, term_type: str, country_region: str) -> str:
        identity = _race_name_identity(value)
        matches = candidates.get((term_type, identity), [])
        if not matches:
            return value
        term = min(
            matches,
            key=lambda item: (
                0 if item.racing_region == country_region else 1 if not item.racing_region else 2,
                -item.priority,
                item.pk,
            ),
        )
        return term.target_zh or value

    for event, item in records:
        item.display_horse_name = display_name(item.horse_name, TermType.HORSE, event.country_region)
        item.display_jockey_name = display_name(item.jockey_name, TermType.JOCKEY, event.country_region)
    return event_records


def public_race_calendar(request: HttpRequest):
    events, filters = _race_calendar_queryset(request)
    events = list(events)
    if filters["direction"] == "past":
        events = list(reversed(events))
    groups = _group_race_events_by_date(events)
    def filter_url(**changes):
        params = request.GET.copy()
        params.pop("cursor", None)
        params.pop("direction", None)
        for key, value in changes.items():
            if value:
                params[key] = value
            else:
                params.pop(key, None)
        return f"?{params.urlencode()}" if params else "?"

    region_tabs = [{"value": "", "label": "全部", "is_active": filters["region"] == "", "url": filter_url(region="")}]
    for value, label in RacingRegion.choices:
        if value == RacingRegion.OTHER:
            continue
        region_tabs.append(
            {
                "value": value,
                "label": label,
                "is_active": filters["region"] == value,
                "url": filter_url(region=value),
            }
        )
    previous_cursor = events[0].local_date.isoformat() if events and events[0].local_date else ""
    next_cursor = events[-1].local_date.isoformat() if events and events[-1].local_date else ""
    return render(
        request,
        "stable/public/race_calendar.html",
        {
            "groups": groups,
            "filters": filters,
            "years": public_race_calendar_years(),
            "region_tabs": region_tabs,
            "all_tab_url": filter_url(tab="all"),
            "key_tab_url": filter_url(tab="key"),
            "clear_search_url": filter_url(year="", q=""),
            "previous_url": filter_url(direction="past", cursor=previous_cursor) if previous_cursor and not (filters["year"] or filters["q"]) else "",
            "next_url": filter_url(direction="future", cursor=next_cursor) if next_cursor and not (filters["year"] or filters["q"]) else "",
        },
    )


def _series_history_winners(
    event: RaceEvent,
    *,
    exclude_result_event_id: int | None = None,
):
    if not event.race_series_id:
        return list(event.history_winners.all())
    result_winner_queryset = (
        RaceEventResult.objects.select_related("event")
        .filter(
            event__race_series_id=event.race_series_id,
            event__visibility_status=RaceEventVisibility.PUBLISHED,
        )
        .filter(
            Q(official_finish_position=1)
            | Q(official_finish_position__isnull=True, finish_position=1)
        )
    )
    if exclude_result_event_id is not None:
        result_winner_queryset = result_winner_queryset.exclude(
            event_id=exclude_result_event_id
        )
    result_winners = list(
        result_winner_queryset.order_by("-event__year", "finish_position", "id")
    )
    covered_years = set()
    for winner in result_winners:
        winner.winner_year = winner.event.year
        covered_years.add(winner.event.year)
    fallback_winner_queryset = RaceEventHistoryWinner.objects.filter(
        event__race_series_id=event.race_series_id,
        event__visibility_status=RaceEventVisibility.PUBLISHED,
    )
    if exclude_result_event_id is not None:
        fallback_winner_queryset = fallback_winner_queryset.exclude(
            event_id=exclude_result_event_id
        )
    fallback_winners = list(
        fallback_winner_queryset.exclude(
            winner_year__in=covered_years
        ).order_by("-winner_year", "horse_name", "id")
    )
    return sorted(
        [*result_winners, *fallback_winners],
        key=lambda winner: (-winner.winner_year, winner.horse_name, winner.pk),
    )


def public_race_detail(request: HttpRequest, year: int, slug: str):
    event = get_object_or_404(
        RaceEvent.objects.filter(visibility_status=RaceEventVisibility.PUBLISHED)
        .select_related(
            "projection_control__current_result_revision",
            "live_tracking",
        )
        .prefetch_related(
            "runners",
            "results",
            "history_winners",
            "article_links__article",
        ),
        year=year,
        slug=slug,
    )
    live_result_status = None
    projection_control = getattr(event, "projection_control", None)
    current_result_revision = (
        projection_control.current_result_revision if projection_control else None
    )
    read_now = timezone.now()
    live_public_read = resolve_race_live_public_read(
        event_id=event.pk,
        now=read_now,
    )
    if current_result_revision and live_public_read.visible:
        tracking = getattr(event, "live_tracking", None)
        if current_result_revision.conflict_status == "pending":
            status_label = "赛果待复核"
            status_detail = "不同来源的赛果存在差异，正在复核"
        else:
            status_label, status_detail = {
                "provisional": ("暂定赛果", "尚待官方来源复核"),
                "official": ("正式赛果", ""),
                "corrected": ("更正赛果", ""),
            }.get(
                current_result_revision.phase,
                ("赛果更新", ""),
            )
        live_result_status = {
            "label": status_label,
            "detail": status_detail,
            "phase": current_result_revision.phase,
            "source_label": (
                "官方来源"
                if current_result_revision.source_authority == "official"
                else "补充来源"
            ),
            "published_at": current_result_revision.published_at,
            "is_stale": bool(
                tracking
                and tracking.stale_at is not None
                and tracking.stale_at <= read_now
            ),
        }
    public_links = [
        link
        for link in event.article_links.all()
        if link.status in {ArticleRaceLinkStatus.AUTO, ArticleRaceLinkStatus.MANUAL}
        and link.article.workflow_status == WorkflowStatus.PUBLISHED
        and link.article.published_to_web_at is not None
    ]
    news_groups = {
        "pre_race": [link.article for link in public_links if link.link_type == ArticleRaceLinkType.PRE_RACE],
        "post_race": [link.article for link in public_links if link.link_type == ArticleRaceLinkType.POST_RACE],
        "related": [link.article for link in public_links if link.link_type == ArticleRaceLinkType.RELATED],
    }
    runners = _sort_runners_for_display(list(event.runners.all()), event.country_region)
    has_current_live_revision = current_result_revision is not None
    hide_live_results = has_current_live_revision and not live_public_read.visible
    results = (
        []
        if hide_live_results
        else _attach_result_display_positions(list(event.results.all()))
    )
    history_winners = _series_history_winners(
        event,
        exclude_result_event_id=event.pk if hide_live_results else None,
    )
    _attach_race_term_display_names(
        [
            (event, runners),
            (event, results),
            (event, history_winners),
        ]
    )
    top_results = results[:5]
    return render(
        request,
        "stable/public/race_detail.html",
        {
            "event": event,
            "runners": runners,
            "results": results,
            "history_winners": history_winners,
            "top_results": top_results,
            "news_groups": news_groups,
            "live_result_status": live_result_status,
        },
    )


def _race_sitemap_queryset():
    return (
        RaceEvent.objects.filter(
            visibility_status=RaceEventVisibility.PUBLISHED,
            data_quality_status=RaceEventDataQuality.COMPLETE,
        )
        .filter(
            Q(historical_target__isnull=True)
            | Q(historical_target__resolution_status=HistoricalRaceResolutionStatus.IMPORTED)
        )
        .order_by("year", "slug", "id")
    )


@require_GET
def public_sitemap_index(request: HttpRequest):
    shard_size = max(1, settings.RACE_EVENT_SITEMAP_SHARD_SIZE)
    shard_count = math.ceil(public_race_sitemap_count(_race_sitemap_queryset()) / shard_size)
    base_url = settings.SITE_URL.rstrip("/")
    return render(
        request,
        "stable/public/sitemap_index.xml",
        {"shards": [f"{base_url}/sitemaps/races-{index}.xml" for index in range(1, shard_count + 1)]},
        content_type="application/xml",
    )


@require_GET
def public_race_sitemap_shard(request: HttpRequest, shard: int):
    shard_size = max(1, settings.RACE_EVENT_SITEMAP_SHARD_SIZE)
    start = (shard - 1) * shard_size
    queryset = _race_sitemap_queryset()
    if shard < 1 or start >= public_race_sitemap_count(queryset):
        return HttpResponse(status=404)
    events = queryset[start : start + shard_size]
    base_url = settings.SITE_URL.rstrip("/")
    return render(
        request,
        "stable/public/race_sitemap.xml",
        {"events": events, "base_url": base_url},
        content_type="application/xml",
    )


def public_news_feed(request: HttpRequest):
    active_region = _resolve_public_region(request.GET.get("region", ""))
    queryset = _public_published_articles(active_region)
    headline_article = _select_headline_article(queryset)
    hot_articles = _build_hot_articles(queryset)
    paginator = Paginator(queryset, PUBLIC_FEED_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    feed_articles = [article for article in page_obj if not headline_article or article.pk != headline_article.pk]
    pagination_params = request.GET.copy()
    pagination_params.pop("page", None)
    return render(
        request,
        "stable/public/feed.html",
        {
            "page_obj": page_obj,
            "latest_articles": page_obj,
            "headline_article": headline_article,
            "feed_articles": feed_articles,
            "hot_articles": hot_articles,
            "region_tabs": _region_tab_context(active_region),
            "active_region": active_region,
            "followed_entries": _public_followed_entries(request),
            "pagination_querystring": pagination_params.urlencode(),
        },
    )


def public_article_detail(request: HttpRequest, article_id: int):
    article = get_object_or_404(
        NewsArticle.objects.prefetch_related(
            "race_links__event",
            "horse_links__horse_profile",
            "related_region_links",
        ),
        workflow_status=WorkflowStatus.PUBLISHED,
        published_to_web_at__isnull=False,
        pk=article_id,
    )
    race_links = [
        link
        for link in article.race_links.all()
        if link.status in {ArticleRaceLinkStatus.AUTO, ArticleRaceLinkStatus.MANUAL}
        and link.event.visibility_status == RaceEventVisibility.PUBLISHED
    ]
    horse_links = [
        link
        for link in article.horse_links.all()
        if link.status in {ArticleHorseLinkStatus.AUTO, ArticleHorseLinkStatus.MANUAL}
        and link.horse_profile.review_status == HorseProfileStatus.PUBLISHED
    ]
    return render(request, "stable/public/detail.html", {"article": article, "race_links": race_links, "horse_links": horse_links})


def public_horse_index(request: HttpRequest):
    queryset = _public_horse_queryset()
    query = request.GET.get("q", "").strip()
    region = _resolve_public_region(request.GET.get("region", ""))
    if query:
        queryset = queryset.filter(
            Q(display_name_zh__icontains=query)
            | Q(original_name__icontains=query)
            | Q(english_name__icontains=query)
            | Q(japanese_name__icontains=query)
            | Q(country__icontains=query)
        )
    if region:
        queryset = queryset.filter(racing_region=region)
    paginator = Paginator(queryset, PUBLIC_HORSE_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    pagination_params = request.GET.copy()
    pagination_params.pop("page", None)
    return render(
        request,
        "stable/public/horse_index.html",
        {
            "page_obj": page_obj,
            "horse_profiles": page_obj.object_list,
            "region_tabs": _region_tab_context(region),
            "filters": {"q": query, "region": region},
            "pagination_querystring": pagination_params.urlencode(),
        },
    )


def public_horse_detail(request: HttpRequest, profile_id: int):
    profile = get_object_or_404(
        _public_horse_queryset()
        .prefetch_related(
            "article_links__article",
            "race_links__event",
            "race_records__event",
            "sire_children",
            "dam_children",
        ),
        pk=profile_id,
    )
    public_article_links = [
        link
        for link in profile.article_links.all()
        if link.status in {ArticleHorseLinkStatus.AUTO, ArticleHorseLinkStatus.MANUAL}
        and link.article.workflow_status == WorkflowStatus.PUBLISHED
        and link.article.published_to_web_at is not None
    ]
    public_race_links = [
        link
        for link in profile.race_links.all()
        if link.status in {ArticleHorseLinkStatus.AUTO, ArticleHorseLinkStatus.MANUAL}
        and link.event.visibility_status == RaceEventVisibility.PUBLISHED
    ]
    race_records = list(profile.race_records.all()[:20])
    token_hash = _follow_token_hash_from_request(request)
    is_following = bool(token_hash and HorseFollow.objects.filter(token_hash=token_hash, horse_profile=profile).exists())
    descendants = (
        HorseProfile.objects.filter(Q(sire_horse_profile=profile) | Q(dam_horse_profile=profile), review_status=HorseProfileStatus.PUBLISHED)
        .order_by("racing_region", "display_name_zh", "id")[:12]
    )
    return render(
        request,
        "stable/public/horse_detail.html",
        {
            "profile": profile,
            "major_wins": major_win_records(profile),
            "article_links": public_article_links[:12],
            "race_links": public_race_links[:12],
            "race_records": race_records,
            "descendants": descendants,
            "is_following": is_following,
        },
    )


@require_POST
def public_horse_follow(request: HttpRequest, profile_id: int):
    profile = get_object_or_404(HorseProfile, pk=profile_id, review_status=HorseProfileStatus.PUBLISHED)
    signed_token = request.COOKIES.get(FOLLOW_COOKIE_NAME, "")
    token_hash = _follow_token_hash_from_request(request)
    if not token_hash:
        signed_token = signed_follow_token()
        token_hash = token_hash_from_cookie(signed_token)
    include_descendants = request.POST.get("include_descendants", "1") == "1"
    if request.POST.get("intent") == "unfollow":
        unfollow_horse(token_hash, profile)
        messages.success(request, "已取消关注。")
    else:
        follow_horse(token_hash, profile, include_descendants=include_descendants)
        messages.success(request, "已关注这匹马。")
    response = redirect(profile.public_path)
    set_follow_cookie(response, signed_token)
    return response


def public_horse_follows(request: HttpRequest):
    token_hash = _follow_token_hash_from_request(request)
    follows = []
    entries = []
    if token_hash:
        follows = (
            HorseFollow.objects.filter(token_hash=token_hash, horse_profile__review_status=HorseProfileStatus.PUBLISHED)
            .select_related("horse_profile")
            .order_by("-followed_at", "-id")
        )
        entries = followed_articles(token_hash, limit=40)
    return render(request, "stable/public/horse_follows.html", {"follows": follows, "followed_entries": entries})


def legacy_public_article_detail(request: HttpRequest, slug: str):
    article = get_object_or_404(
        NewsArticle,
        workflow_status=WorkflowStatus.PUBLISHED,
        published_to_web_at__isnull=False,
        public_slug=slug,
    )
    return redirect(article.public_path)


def _article_payload(article: NewsArticle) -> dict:
    return {
        "id": article.id,
        "source_site": article.source_site,
        "source_mode": article.source_mode,
        "racing_region": article.racing_region,
        "racing_region_label": article.get_racing_region_display(),
        "source_language": article.source_language,
        "source_language_label": article.get_source_language_display(),
        "source_article_id": article.source_article_id,
        "title_ja": article.title_ja,
        "translated_title_zh": article.translated_title_zh,
        "title_zh": article.title_zh,
        "summary_zh": article.summary_zh,
        "published_at": article.published_at.isoformat(),
        "workflow_status": article.workflow_status,
        "review_mode": article.review_mode,
        "risk_level": article.risk_level,
        "automation_status": article.automation_status,
        "decision_summary": article.decision_summary,
        "gate_issues": article.gate_issues,
        "duplicate_of_id": article.duplicate_of_id,
        "duplicate_score": article.duplicate_score,
        "duplicate_reason": article.duplicate_reason,
        "score_total": article.score_total,
        "quality_score": article.quality_score,
        "rewrite_confidence": article.rewrite_confidence,
        "content_category": article.content_category,
        "status": article.status,
        "translation_status": article.translation_status,
        "translation_error_message": article.translation_error_message,
        "translation_model": article.translation_model,
        "translation_provider": article.translation_provider,
        "translation_retry_count": article.translation_retry_count,
        "translated_at": article.translated_at.isoformat() if article.translated_at else None,
        "rewrite_title_zh": article.rewrite_title_zh,
        "rewrite_summary_zh": article.rewrite_summary_zh,
        "rewrite_body_zh": article.rewrite_body_zh,
        "published_by_mode": article.published_by_mode,
        "auto_publish_at": article.auto_publish_at.isoformat() if article.auto_publish_at else None,
        "source_url": article.source_url,
        "is_first_crawled": article.is_first_crawled,
        "images": [
            {
                "id": image.id,
                "original_url": image.original_url,
                "local_path": image.local_path,
                "caption_ja": image.caption_ja,
                "caption_zh": image.caption_zh,
            }
            for image in article.images.all()
        ],
    }


def _translation_status_payload(article: NewsArticle) -> dict:
    latest_run = article.latest_translation_run
    return {
        "article_id": article.id,
        "translation_status": article.translation_status,
        "translation_error_message": article.translation_error_message,
        "translation_model": article.translation_model,
        "translation_provider": article.translation_provider,
        "translation_retry_count": article.translation_retry_count,
        "translation_started_at": article.translation_started_at.isoformat() if article.translation_started_at else None,
        "translated_at": article.translated_at.isoformat() if article.translated_at else None,
        "latest_run": {
            "id": latest_run.id,
            "status": latest_run.status,
            "provider_name": latest_run.provider_name,
            "model_name": latest_run.model_name,
            "error_message": latest_run.error_message,
            "created_at": latest_run.created_at.isoformat(),
            "updated_at": latest_run.updated_at.isoformat(),
        }
        if latest_run
        else None,
    }


@login_required
@require_GET
def article_list_api(request: HttpRequest) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    queryset = NewsArticle.objects.all().prefetch_related("images")
    for key in ("source_site", "source_mode", "racing_region", "source_language", "status", "workflow_status"):
        value = request.GET.get(key)
        if value:
            queryset = queryset.filter(**{key: value})
    payload = [_article_payload(article) for article in queryset[:100]]
    return JsonResponse({"results": payload})


@login_required
@require_GET
def article_detail_api(request: HttpRequest, article_id: int) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    article = get_object_or_404(NewsArticle.objects.prefetch_related("images"), pk=article_id)
    return JsonResponse(_article_payload(article))


@login_required
@require_GET
def article_translation_status_api(request: HttpRequest, article_id: int) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    article = get_object_or_404(NewsArticle.objects.prefetch_related("translation_runs"), pk=article_id)
    return JsonResponse(_translation_status_payload(article))


@login_required
@require_POST
def article_retranslate_api(request: HttpRequest, article_id: int) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    article = get_object_or_404(NewsArticle, pk=article_id)
    dispatch_task(translate_article_task, article.id)
    log_operation(
        action_type="article_retranslated_api",
        target_type="article",
        target_id=article.pk,
        detail=f"通过 API 触发重翻译：{article.effective_title}",
        admin=request.user,
    )
    return JsonResponse({"queued": True, "article_id": article.id})


@login_required
@require_POST
def article_update_api(request: HttpRequest, article_id: int) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    article = get_object_or_404(NewsArticle, pk=article_id)
    payload = json.loads(request.body.decode("utf-8"))
    changed_fields: list[str] = []
    for field in ("title_zh", "summary_zh", "body_zh", "push_summary_zh", "editor_notes", "workflow_status", "status"):
        if field in payload:
            setattr(article, field, payload[field])
            changed_fields.append(field)
    if changed_fields:
        article.mark_manual_edits(changed_fields)
        article.save()
        log_operation(
            action_type="article_updated_api",
            target_type="article",
            target_id=article.pk,
            detail=f"通过 API 更新字段：{', '.join(changed_fields)}",
            admin=request.user,
        )
    return JsonResponse({"updated": True, "fields": changed_fields})


@login_required
@require_POST
def article_push_api(request: HttpRequest, article_id: int) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    article = get_object_or_404(NewsArticle, pk=article_id)
    payload = json.loads(request.body.decode("utf-8"))
    target_ids = payload.get("target_ids") or []
    targets = list(PushTarget.objects.filter(pk__in=target_ids, is_active=True))
    if not targets:
        targets = list(PushTarget.objects.filter(is_default=True, is_active=True))
    enqueue_push_for_article(article, targets, request.user)
    return JsonResponse({"queued": True, "target_count": len(targets)})


@login_required
@require_GET
def task_log_list_api(request: HttpRequest) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    logs = TaskExecutionLog.objects.all()[:100]
    return JsonResponse(
        {
            "results": [
                {
                    "task_name": log.task_name,
                    "status": log.status,
                    "detail": log.detail,
                    "started_at": log.started_at.isoformat(),
                    "finished_at": log.finished_at.isoformat() if log.finished_at else None,
                }
                for log in logs
            ]
        }
    )


def _term_payload(term: TermEntry) -> dict:
    return {
        "id": term.id,
        "term_type": term.term_type,
        "source_language": term.source_language,
        "racing_region": term.racing_region,
        "source_ja": term.source_ja,
        "target_zh": term.target_zh,
        "translation_status": term.translation_status,
        "has_translation": term.has_translation,
        "aliases_ja": term.aliases_ja,
        "aliases_zh": term.aliases_zh,
        "race_grade": term.race_grade,
        "priority": term.priority,
        "is_active": term.is_active,
        "notes": term.notes,
        "updated_at": term.updated_at.isoformat(),
        "created_at": term.created_at.isoformat(),
    }


@login_required
@require_GET
def term_list_api(request: HttpRequest) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    queryset = TermEntry.objects.all().order_by("-updated_at", "-priority", "source_ja")
    queryset = _term_filters(queryset, request)
    paginator = Paginator(queryset, int(request.GET.get("page_size", 20)))
    page_obj = paginator.get_page(request.GET.get("page"))
    return JsonResponse(
        {
            "results": [_term_payload(term) for term in page_obj.object_list],
            "pagination": {
                "page": page_obj.number,
                "num_pages": paginator.num_pages,
                "total": paginator.count,
            },
        }
    )


@login_required
@require_GET
def term_detail_api(request: HttpRequest, term_id: int) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    term = get_object_or_404(TermEntry, pk=term_id)
    return JsonResponse(_term_payload(term))


@login_required
@require_POST
def term_create_api(request: HttpRequest) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    payload = json.loads(request.body.decode("utf-8"))
    normalized, errors = validate_term_payload(payload)
    if errors:
        return JsonResponse({"ok": False, "errors": errors}, status=400)
    term = TermEntry.objects.create(**normalized)
    sync_term_source_aliases(term, term.source_language)
    log_operation(
        action_type="term_created_api",
        target_type="term",
        target_id=term.pk,
        detail=f"通过 API 创建术语 {term.source_ja}",
        admin=request.user,
    )
    return JsonResponse({"ok": True, "term": _term_payload(term)})


@login_required
@require_http_methods(["PUT", "POST"])
def term_update_api(request: HttpRequest, term_id: int) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    term = get_object_or_404(TermEntry, pk=term_id)
    payload = json.loads(request.body.decode("utf-8"))
    normalized, errors = validate_term_payload(payload, instance_id=term.pk)
    if errors:
        return JsonResponse({"ok": False, "errors": errors}, status=400)
    for field, value in normalized.items():
        setattr(term, field, value)
    term.save()
    sync_term_source_aliases(term, term.source_language)
    log_operation(
        action_type="term_updated_api",
        target_type="term",
        target_id=term.pk,
        detail=f"通过 API 更新术语 {term.source_ja}",
        admin=request.user,
    )
    return JsonResponse({"ok": True, "term": _term_payload(term)})


@login_required
@require_POST
def term_toggle_active_api(request: HttpRequest, term_id: int) -> JsonResponse:
    denied = _ensure_staff(request)
    if denied:
        return JsonResponse({"detail": "forbidden"}, status=403)
    term = get_object_or_404(TermEntry, pk=term_id)
    term.is_active = not term.is_active
    term.save(update_fields=["is_active", "updated_at"])
    sync_all_term_alias_active(term)
    log_operation(
        action_type="term_toggled_api",
        target_type="term",
        target_id=term.pk,
        detail=f"通过 API {'启用' if term.is_active else '停用'}术语 {term.source_ja}",
        admin=request.user,
    )
    return JsonResponse({"ok": True, "term": _term_payload(term)})

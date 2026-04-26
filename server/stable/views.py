from __future__ import annotations

import json
import uuid
from datetime import datetime, time
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .forms import ArticleEditorForm, BackendAuthenticationForm, NewsSourceForm, TermEntryForm, TermImportForm
from .models import (
    ArticleTranslationStatus,
    CrawlJob,
    MediaAsset,
    NewsArticle,
    NewsImage,
    NewsSource,
    OperationLog,
    PushTarget,
    TaskExecutionLog,
    TermEntry,
    TermType,
    WorkflowStatus,
)
from .services.media_assets import localize_news_image, set_cover_asset
from .services.operations import log_operation
from .services.pushing import enqueue_push_for_article
from .services.queueing import dispatch_task
from .services.sources import sync_builtin_sources
from .services.storage import current_media_provider
from .services.term_admin import (
    commit_term_import,
    preview_from_session_value,
    preview_term_import,
    preview_to_session_value,
    serialize_aliases,
    validate_term_payload,
)
from .tasks import batch_translate_articles_task, crawl_news_source_task, translate_article_task


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
        **extra,
    }


def _article_filters(queryset, request: HttpRequest):
    query = (request.GET.get("q") or request.POST.get("q") or "").strip()
    source_id = (request.GET.get("source") or request.POST.get("source") or "").strip()
    workflow_status = (request.GET.get("workflow_status") or request.POST.get("workflow_status") or "").strip()
    translated = (request.GET.get("translated") or request.POST.get("translated") or "").strip()
    translation_status = (request.GET.get("translation_status") or request.POST.get("translation_status") or "").strip()

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
    is_active = request.GET.get("is_active", "").strip()
    has_alias = request.GET.get("has_alias", "").strip()

    if query:
        queryset = queryset.filter(
            Q(source_ja__icontains=query)
            | Q(target_zh__icontains=query)
            | Q(aliases_ja__icontains=query)
            | Q(aliases_zh__icontains=query)
            | Q(notes__icontains=query)
        )
    if term_type:
        queryset = queryset.filter(term_type=term_type)
    if is_active == "true":
        queryset = queryset.filter(is_active=True)
    elif is_active == "false":
        queryset = queryset.filter(is_active=False)
    if has_alias == "yes":
        queryset = queryset.filter(~Q(aliases_ja=[]) | ~Q(aliases_zh=[]))
    return queryset


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
    recent_sources = NewsSource.objects.filter(deleted_at__isnull=True).order_by("-updated_at")[:5]
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
    sources = NewsSource.objects.filter(deleted_at__isnull=True).order_by("-enabled", "-priority", "name")
    return render(request, "stable/console/source_list.html", _console_context(request, sources=sources))


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
    return render(
        request,
        "stable/console/term_list.html",
        _console_context(
            request,
            page_obj=page_obj,
            term_type_choices=TermType.choices,
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
            "source_ja": source_term.source_ja,
            "target_zh": source_term.target_zh,
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
        ),
    )


@login_required
def candidate_detail(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(
        NewsArticle.objects.select_related("source_config", "cover_media_asset").prefetch_related("images", "media_assets", "translation_runs"),
        pk=article_id,
    )
    return render(request, "stable/console/candidate_detail.html", _console_context(request, article=article))


@login_required
@require_POST
def candidate_retranslate(request: HttpRequest, article_id: int):
    denied = _ensure_staff(request)
    if denied:
        return denied
    article = get_object_or_404(NewsArticle, pk=article_id)
    dispatch_task(translate_article_task, article.id)
    log_operation(
        action_type="article_retranslated",
        target_type="article",
        target_id=article.pk,
        detail=f"重新触发翻译《{article.effective_title}》",
        admin=request.user,
    )
    messages.success(request, "已重新触发翻译。")
    return redirect(request.POST.get("next") or reverse("console-candidate-detail", args=[article.pk]))


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
    article.ignored_at = timezone.now()
    article.save(update_fields=["workflow_status", "ignored_at", "updated_at"])
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
                        _console_context(request, form=form, article=article, allow_publish_without_cover=True),
                    )
                article.workflow_status = WorkflowStatus.PUBLISHED
                article.published_to_web_at = timezone.now()
                article.published_by = request.user
            elif intent == "withdraw":
                article.workflow_status = WorkflowStatus.WITHDRAWN
                article.withdrawn_at = timezone.now()
            else:
                if article.workflow_status in {WorkflowStatus.PENDING_TRANSLATION, WorkflowStatus.TRANSLATION_FAILED}:
                    article.workflow_status = WorkflowStatus.PENDING_EDIT
            article.save()
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
    return render(request, "stable/console/article_editor.html", _console_context(request, form=form, article=article, allow_publish_without_cover=False))


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
    paginator = Paginator(logs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "stable/console/logs.html", _console_context(request, page_obj=page_obj))


def public_news_feed(request: HttpRequest):
    queryset = (
        NewsArticle.objects.select_related("cover_media_asset")
        .filter(workflow_status=WorkflowStatus.PUBLISHED)
        .order_by("-published_to_web_at", "-id")
    )
    paginator = Paginator(queryset, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "stable/public/feed.html", {"page_obj": page_obj})


def public_article_detail(request: HttpRequest, slug: str):
    article = get_object_or_404(NewsArticle, workflow_status=WorkflowStatus.PUBLISHED, public_slug=slug)
    return render(request, "stable/public/detail.html", {"article": article})


def _article_payload(article: NewsArticle) -> dict:
    return {
        "id": article.id,
        "source_site": article.source_site,
        "source_mode": article.source_mode,
        "source_article_id": article.source_article_id,
        "title_ja": article.title_ja,
        "translated_title_zh": article.translated_title_zh,
        "title_zh": article.title_zh,
        "summary_zh": article.summary_zh,
        "published_at": article.published_at.isoformat(),
        "workflow_status": article.workflow_status,
        "status": article.status,
        "translation_status": article.translation_status,
        "translation_error_message": article.translation_error_message,
        "translation_model": article.translation_model,
        "translation_provider": article.translation_provider,
        "translation_retry_count": article.translation_retry_count,
        "translated_at": article.translated_at.isoformat() if article.translated_at else None,
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
    for key in ("source_site", "source_mode", "status", "workflow_status"):
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
        "source_ja": term.source_ja,
        "target_zh": term.target_zh,
        "aliases_ja": term.aliases_ja,
        "aliases_zh": term.aliases_zh,
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
    log_operation(
        action_type="term_toggled_api",
        target_type="term",
        target_id=term.pk,
        detail=f"通过 API {'启用' if term.is_active else '停用'}术语 {term.source_ja}",
        admin=request.user,
    )
    return JsonResponse({"ok": True, "term": _term_payload(term)})

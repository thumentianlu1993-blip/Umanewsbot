from __future__ import annotations

from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from .forms import NewsArticleAdminForm, NewsImageAdminForm, NewsSourceForm, PushArticleForm
from .models import (
    ArticleStatus,
    AutomationLog,
    CrawlJob,
    MediaAsset,
    NewsArticle,
    NewsImage,
    NewsSnapshot,
    NewsSource,
    NotificationLog,
    OperationLog,
    PushLog,
    PushTarget,
    QQPushDelivery,
    TaskExecutionLog,
    TermCandidate,
    TermCandidateEvidence,
    TermAlias,
    TermEntry,
    TranslationRun,
    WorkflowStatus,
)
from .services.operations import log_operation
from .services.pushing import enqueue_push_for_article
from .services.queueing import dispatch_task
from .tasks import crawl_news_source_task, translate_article_task


admin.site.register(TermCandidate)
admin.site.register(TermCandidateEvidence)
admin.site.register(TermAlias)


class NewsImageInline(admin.TabularInline):
    model = NewsImage
    form = NewsImageAdminForm
    extra = 0


class MediaAssetInline(admin.TabularInline):
    model = MediaAsset
    extra = 0
    readonly_fields = ("original_image_url", "internal_image_url", "storage_provider", "status")


class NewsSnapshotInline(admin.TabularInline):
    model = NewsSnapshot
    extra = 0
    readonly_fields = ("source_mode", "rank", "comment_count", "attention_count", "captured_at")
    can_delete = False


class PushLogInline(admin.TabularInline):
    model = PushLog
    extra = 0
    readonly_fields = ("target", "status", "error_message", "sent_at", "created_at")
    can_delete = False


class QQPushDeliveryInline(admin.TabularInline):
    model = QQPushDelivery
    extra = 0
    readonly_fields = (
        "target",
        "status",
        "attempt_count",
        "max_attempts",
        "last_error_type",
        "last_error",
        "last_attempt_at",
        "sent_at",
        "created_at",
    )
    can_delete = False


class TranslationRunInline(admin.TabularInline):
    model = TranslationRun
    extra = 0
    readonly_fields = ("provider_name", "model_name", "status", "created_at", "error_message")
    can_delete = False


class AutomationLogInline(admin.TabularInline):
    model = AutomationLog
    extra = 0
    readonly_fields = ("phase", "result", "score", "confidence", "reason", "error_message", "created_at")
    can_delete = False


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    form = NewsArticleAdminForm
    list_display = (
        "id",
        "effective_title",
        "racing_region",
        "source_language",
        "source_site",
        "source_mode",
        "published_at",
        "workflow_status",
        "automation_status",
        "review_mode",
        "gate_issue_summary",
        "score_total",
        "status",
        "is_first_crawled",
        "push_action_link",
    )
    list_filter = (
        "racing_region",
        "source_language",
        "source_site",
        "source_mode",
        "workflow_status",
        "automation_status",
        "review_mode",
        "risk_level",
        "status",
        "is_first_crawled",
    )
    search_fields = ("title_ja", "translated_title_zh", "title_zh", "source_article_id", "source_url")
    readonly_fields = (
        "source_config",
        "crawl_job",
        "source_site",
        "source_mode",
        "racing_region",
        "source_language",
        "source_article_id",
        "source_url",
        "title_ja",
        "body_ja_raw",
        "body_ja_normalized",
        "translated_title_zh",
        "translated_body_zh",
        "translated_summary_zh",
        "published_at",
        "is_first_crawled",
        "first_seen_at",
        "last_seen_at",
        "gate_issue_summary",
        "duplicate_article_link",
        "push_action_link",
        "translate_action_link",
    )
    inlines = [
        NewsImageInline,
        MediaAssetInline,
        NewsSnapshotInline,
        TranslationRunInline,
        AutomationLogInline,
        PushLogInline,
        QQPushDeliveryInline,
    ]
    actions = ["mark_pending_review", "mark_published_ready", "queue_translation"]

    fieldsets = (
        (
            "来源信息",
            {
                "fields": (
                    "source_config",
                    "crawl_job",
                    "source_site",
                    "source_mode",
                    "racing_region",
                    "source_language",
                    "source_article_id",
                    "source_url",
                    "published_at",
                )
            },
        ),
        ("来源原文", {"fields": ("title_ja", "body_ja_raw", "body_ja_normalized")}),
        ("翻译参考", {"fields": ("translated_title_zh", "translated_summary_zh", "translated_body_zh")}),
        ("自动化运营", {"fields": ("review_mode", "risk_level", "automation_status", "content_category", "score_total", "quality_score", "rewrite_confidence", "decision_summary", "decision_reason", "gate_issues", "gate_issue_summary", "base_translation_zh", "rewrite_title_zh", "rewrite_summary_zh", "rewrite_body_zh", "published_by_mode", "auto_publish_at", "automation_error_message")}),
        ("重复内容", {"fields": ("duplicate_of", "duplicate_article_link", "duplicate_score", "duplicate_reason", "automation_warning_email_signature", "automation_warning_email_sent_at")}),
        ("发布内容", {"fields": ("title_zh", "summary_zh", "body_zh", "source_note", "editor_notes", "workflow_status", "status")}),
        ("追踪信息", {"fields": ("is_first_crawled", "first_seen_at", "last_seen_at")}),
        ("操作", {"fields": ("translate_action_link", "push_action_link")}),
    )

    def save_model(self, request, obj, form, change):
        changed = set(form.changed_data) & {"title_zh", "summary_zh", "body_zh", "editor_notes"}
        if changed:
            obj.mark_manual_edits(changed)
            if obj.workflow_status == WorkflowStatus.PENDING_EDIT:
                obj.workflow_status = WorkflowStatus.PENDING_REVIEW
            log_operation(
                action_type="article_saved_admin",
                target_type="article",
                target_id=obj.pk or "",
                detail=f"通过 Django Admin 保存《{obj.effective_title}》",
                admin=request.user,
            )
        super().save_model(request, obj, form, change)

    @admin.action(description="标记为待审核")
    def mark_pending_review(self, request, queryset):
        count = queryset.update(workflow_status=WorkflowStatus.PENDING_REVIEW)
        self.message_user(request, f"已将 {count} 篇文章标记为待审核。", messages.SUCCESS)

    @admin.action(description="标记为可推送")
    def mark_published_ready(self, request, queryset):
        count = queryset.update(status=ArticleStatus.PUSH_READY)
        self.message_user(request, f"已将 {count} 篇文章标记为可推送。", messages.SUCCESS)

    @admin.action(description="加入翻译队列")
    def queue_translation(self, request, queryset):
        for article in queryset:
            dispatch_task(translate_article_task, article.id)
        self.message_user(request, f"已将 {queryset.count()} 篇文章加入翻译队列。", messages.SUCCESS)

    def push_action_link(self, obj):
        url = reverse("admin:stable_newsarticle_push", args=[obj.pk])
        return format_html('<a class="button" href="{}">推送到 QQ 群</a>', url)

    push_action_link.short_description = "QQ 推送"

    def translate_action_link(self, obj):
        url = reverse("admin:stable_newsarticle_translate", args=[obj.pk])
        return format_html('<a class="button" href="{}">重新翻译</a>', url)

    translate_action_link.short_description = "重译"

    def gate_issue_summary(self, obj):
        issues = obj.gate_issues or []
        if not issues:
            return "-"
        counts = {"blocker": 0, "warning": 0, "info": 0}
        for issue in issues:
            counts[str(issue.get("severity") or "info")] = counts.get(str(issue.get("severity") or "info"), 0) + 1
        return f"B:{counts.get('blocker', 0)} W:{counts.get('warning', 0)} I:{counts.get('info', 0)}"

    gate_issue_summary.short_description = "门禁"

    def duplicate_article_link(self, obj):
        if not obj.duplicate_of_id:
            return "-"
        url = reverse("admin:stable_newsarticle_change", args=[obj.duplicate_of_id])
        return format_html('<a href="{}">#{}</a>', url, obj.duplicate_of_id)

    duplicate_article_link.short_description = "相似文章"

    def get_urls(self):
        custom_urls = [
            path("<int:article_id>/push/", self.admin_site.admin_view(self.push_view), name="stable_newsarticle_push"),
            path(
                "<int:article_id>/translate/",
                self.admin_site.admin_view(self.translate_view),
                name="stable_newsarticle_translate",
            ),
        ]
        return custom_urls + super().get_urls()

    def push_view(self, request: HttpRequest, article_id: int):
        article = get_object_or_404(NewsArticle, pk=article_id)
        if request.method == "POST":
            form = PushArticleForm(request.POST)
            if form.is_valid():
                targets = list(form.cleaned_data["targets"])
                if not targets:
                    targets = list(PushTarget.objects.filter(is_default=True, is_active=True))
                enqueue_push_for_article(article, targets, request.user)
                self.message_user(request, f"已把《{article}》加入推送队列。", messages.SUCCESS)
                return redirect(reverse("admin:stable_newsarticle_change", args=[article.pk]))
        else:
            form = PushArticleForm()
        context = {
            **self.admin_site.each_context(request),
            "title": f"推送新闻：{article}",
            "opts": self.model._meta,
            "article": article,
            "form": form,
        }
        return render(request, "admin/stable/newsarticle/push_form.html", context)

    def translate_view(self, request: HttpRequest, article_id: int):
        article = get_object_or_404(NewsArticle, pk=article_id)
        dispatch_task(translate_article_task, article.id)
        self.message_user(request, f"已将《{article}》加入翻译队列。", messages.SUCCESS)
        return HttpResponseRedirect(reverse("admin:stable_newsarticle_change", args=[article.pk]))


@admin.register(NewsSource)
class NewsSourceAdmin(admin.ModelAdmin):
    form = NewsSourceForm
    list_display = (
        "name",
        "racing_region",
        "source_language",
        "source_kind",
        "source_type",
        "enabled",
        "crawl_interval_minutes",
        "last_crawl_at",
        "last_crawl_status",
        "test_crawl_link",
    )
    list_filter = ("enabled", "racing_region", "source_language", "source_kind", "source_type", "adapter_key")
    search_fields = ("name", "homepage_url", "feed_url", "notes")

    def test_crawl_link(self, obj):
        url = reverse("admin:stable_newssource_test_crawl", args=[obj.pk])
        return format_html('<a class="button" href="{}">立即测试抓取</a>', url)

    test_crawl_link.short_description = "测试抓取"

    def get_urls(self):
        custom_urls = [
            path("<int:source_id>/test-crawl/", self.admin_site.admin_view(self.test_crawl_view), name="stable_newssource_test_crawl")
        ]
        return custom_urls + super().get_urls()

    def test_crawl_view(self, request: HttpRequest, source_id: int):
        source = get_object_or_404(NewsSource, pk=source_id)
        dispatch_task(crawl_news_source_task, source.id)
        self.message_user(request, f"已为来源“{source.name}”触发抓取。", messages.SUCCESS)
        log_operation(
            action_type="source_crawl_triggered_admin",
            target_type="source",
            target_id=source.pk,
            detail=f"通过 Django Admin 手动抓取来源 {source.name}",
            admin=request.user,
        )
        return redirect(reverse("admin:stable_newssource_change", args=[source.pk]))


@admin.register(TermEntry)
class TermEntryAdmin(admin.ModelAdmin):
    list_display = ("source_ja", "source_language", "racing_region", "target_zh", "term_type", "race_grade", "priority", "is_active", "updated_at")
    list_filter = ("source_language", "racing_region", "term_type", "race_grade", "is_active")
    search_fields = ("source_ja", "target_zh", "notes")


@admin.register(PushTarget)
class PushTargetAdmin(admin.ModelAdmin):
    list_display = ("name", "group_id", "allowed_regions", "push_scope", "importance_strategy", "is_default", "is_active", "updated_at")
    list_filter = ("push_scope", "importance_strategy", "is_default", "is_active")
    search_fields = ("name", "group_id")


@admin.register(CrawlJob)
class CrawlJobAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "status", "started_at", "finished_at", "success_count", "fail_count")
    list_filter = ("status", "source")
    readonly_fields = ("source", "status", "started_at", "finished_at", "success_count", "fail_count", "error_message")


@admin.register(TaskExecutionLog)
class TaskExecutionLogAdmin(admin.ModelAdmin):
    list_display = ("task_name", "status", "started_at", "finished_at")
    list_filter = ("status",)
    search_fields = ("task_name", "detail")
    readonly_fields = ("task_name", "status", "payload", "detail", "started_at", "finished_at")


@admin.register(PushLog)
class PushLogAdmin(admin.ModelAdmin):
    list_display = ("article", "target", "status", "triggered_by", "sent_at", "created_at")
    list_filter = ("status", "target")
    search_fields = ("article__title_ja", "article__title_zh", "target__name", "error_message")
    readonly_fields = ("article", "target", "triggered_by", "status", "request_payload", "response_payload", "error_message", "sent_at")


@admin.register(QQPushDelivery)
class QQPushDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "article",
        "target",
        "status",
        "attempt_count",
        "max_attempts",
        "last_error_type",
        "last_attempt_at",
        "sent_at",
        "created_at",
    )
    list_filter = ("status", "target", "last_error_type", "created_at")
    search_fields = ("article__title_ja", "article__title_zh", "article__rewrite_title_zh", "target__name", "target__group_id", "last_error")
    readonly_fields = (
        "article",
        "target",
        "status",
        "attempt_count",
        "max_attempts",
        "last_error_type",
        "last_error",
        "request_payload",
        "response_payload",
        "message_id",
        "last_attempt_at",
        "sent_at",
        "created_at",
        "updated_at",
    )


@admin.register(OperationLog)
class OperationLogAdmin(admin.ModelAdmin):
    list_display = ("action_type", "target_type", "target_id", "admin", "created_at")
    list_filter = ("action_type", "target_type")
    search_fields = ("detail", "target_id", "admin__username")
    readonly_fields = ("action_type", "target_type", "target_id", "detail", "admin", "created_at")


@admin.register(AutomationLog)
class AutomationLogAdmin(admin.ModelAdmin):
    list_display = ("article", "phase", "result", "score", "confidence", "created_at")
    list_filter = ("phase", "result")
    search_fields = ("article__title_ja", "article__title_zh", "reason", "error_message")
    readonly_fields = ("article", "phase", "result", "score", "confidence", "reason", "payload", "error_message", "created_at")


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("type", "channel", "target", "status", "sent_at", "created_at")
    list_filter = ("type", "channel", "status")
    search_fields = ("target", "payload_summary", "error_message")
    readonly_fields = ("type", "channel", "target", "status", "payload_summary", "error_message", "sent_at", "created_at")

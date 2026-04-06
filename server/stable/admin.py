from __future__ import annotations

from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from .forms import NewsArticleAdminForm, NewsImageAdminForm, PushArticleForm
from .models import (
    ArticleStatus,
    NewsArticle,
    NewsImage,
    NewsSnapshot,
    PushLog,
    PushTarget,
    TaskExecutionLog,
    TermEntry,
    TranslationRun,
)
from .services.pushing import enqueue_push_for_article
from .services.queueing import dispatch_task
from .tasks import translate_article_task


class NewsImageInline(admin.TabularInline):
    model = NewsImage
    form = NewsImageAdminForm
    extra = 0


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


class TranslationRunInline(admin.TabularInline):
    model = TranslationRun
    extra = 0
    readonly_fields = ("provider_name", "model_name", "status", "created_at", "error_message")
    can_delete = False


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    form = NewsArticleAdminForm
    list_display = (
        "id",
        "source_site",
        "source_mode",
        "published_at",
        "title_ja",
        "status",
        "is_first_crawled",
        "push_action_link",
    )
    list_filter = ("source_site", "source_mode", "status", "is_first_crawled")
    search_fields = ("title_ja", "title_zh", "source_article_id", "source_url")
    readonly_fields = (
        "source_site",
        "source_mode",
        "source_article_id",
        "source_url",
        "title_ja",
        "body_ja_raw",
        "body_ja_normalized",
        "published_at",
        "is_first_crawled",
        "first_seen_at",
        "last_seen_at",
        "push_action_link",
        "translate_action_link",
    )
    inlines = [NewsImageInline, NewsSnapshotInline, TranslationRunInline, PushLogInline]
    actions = ["mark_reviewed", "mark_push_ready", "queue_translation"]

    fieldsets = (
        ("来源信息", {"fields": ("source_site", "source_mode", "source_article_id", "source_url", "published_at")}),
        ("日文原文", {"fields": ("title_ja", "body_ja_raw", "body_ja_normalized")}),
        ("中文内容", {"fields": ("title_zh", "body_zh", "push_summary_zh")}),
        ("状态", {"fields": ("status", "is_first_crawled", "first_seen_at", "last_seen_at", "editor_notes")}),
        ("操作", {"fields": ("translate_action_link", "push_action_link")}),
    )

    def save_model(self, request, obj, form, change):
        changed = set(form.changed_data) & {"title_zh", "body_zh", "push_summary_zh", "editor_notes"}
        if changed:
            obj.mark_manual_edits(changed)
            if obj.status == ArticleStatus.TRANSLATED:
                obj.status = ArticleStatus.REVIEWED
        super().save_model(request, obj, form, change)

    @admin.action(description="标记为已审核")
    def mark_reviewed(self, request, queryset):
        count = queryset.update(status=ArticleStatus.REVIEWED)
        self.message_user(request, f"已标记 {count} 条新闻为已审核。", messages.SUCCESS)

    @admin.action(description="标记为可推送")
    def mark_push_ready(self, request, queryset):
        count = queryset.update(status=ArticleStatus.PUSH_READY)
        self.message_user(request, f"已标记 {count} 条新闻为可推送。", messages.SUCCESS)

    @admin.action(description="加入翻译队列")
    def queue_translation(self, request, queryset):
        for article in queryset:
            dispatch_task(translate_article_task, article.id)
        self.message_user(request, f"已将 {queryset.count()} 条新闻加入翻译队列。", messages.SUCCESS)

    def push_action_link(self, obj):
        url = reverse("admin:stable_newsarticle_push", args=[obj.pk])
        return format_html('<a class="button" href="{}">推送到QQ群</a>', url)

    push_action_link.short_description = "推送"

    def translate_action_link(self, obj):
        url = reverse("admin:stable_newsarticle_translate", args=[obj.pk])
        return format_html('<a class="button" href="{}">重新翻译</a>', url)

    translate_action_link.short_description = "重译"

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


@admin.register(TermEntry)
class TermEntryAdmin(admin.ModelAdmin):
    list_display = ("source_ja", "target_zh", "term_type", "priority", "is_active", "updated_at")
    list_filter = ("term_type", "is_active")
    search_fields = ("source_ja", "target_zh", "notes")


@admin.register(PushTarget)
class PushTargetAdmin(admin.ModelAdmin):
    list_display = ("name", "group_id", "is_default", "is_active", "updated_at")
    list_filter = ("is_default", "is_active")
    search_fields = ("name", "group_id")


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

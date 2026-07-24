from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .forms import NewsArticleAdminForm, NewsImageAdminForm, NewsSourceForm, PushArticleForm
from .models import (
    ArticleRaceLink,
    ArticleStatus,
    ArticleTranslationStatus,
    AutomationLog,
    CrawlJob,
    HistoricalRaceEventTarget,
    HorseIdentityConflict,
    HorseIdentityConflictStatus,
    HorseP0Source,
    HorseProfileCompletionRun,
    MajorRaceEvent,
    MediaAsset,
    NewsArticle,
    NewsArticleRelatedRegion,
    NewsImage,
    NewsSnapshot,
    NewsSource,
    NotificationLog,
    OperationLog,
    ProductionWindow,
    PushLog,
    PushTarget,
    QQPushDelivery,
    QuotaLedger,
    RaceEvent,
    RaceEventAlias,
    RaceEventDataCandidate,
    RaceEventHistoryWinner,
    RaceEventLiveTracking,
    RaceEventParticipant,
    RaceEventParticipantSourceIdentity,
    RaceEventProjectionControl,
    RaceEventRevision,
    RaceEventRevisionEvidence,
    RaceEventRevisionItem,
    RaceEventRevisionPublication,
    RaceEventResult,
    RaceEventRunner,
    RaceLiveEventPublicationAllowlist,
    RaceLiveAlertIncident,
    RaceLiveHostBudget,
    RaceLiveOfficialMarkerContract,
    RaceLiveOfficialMarkerEvidence,
    RaceLiveOfficialPublicationAuthorization,
    RaceLiveOfficialVerificationIncident,
    RaceLivePublicationPolicy,
    RaceResultObservation,
    RaceResultSourceIdentity,
    RaceSeries,
    RaceSeriesName,
    RaceSeriesRelation,
    TaskExecutionLog,
    TermCandidate,
    TermCandidateEvidence,
    TermAlias,
    TermEntry,
    TermGateReprocessRun,
    TranslationRun,
    WindowCandidateDecision,
    WindowTargetDecision,
    WorkflowStatus,
)
from .services.operations import log_operation
from .services.race_events import disable_race_event_live_tracking
from .services.production_windows import update_major_race_boost_window
from .services.pushing import enqueue_push_for_article
from .services.queueing import dispatch_task
from .tasks import crawl_news_source_task, translate_article_task


admin.site.register(TermCandidate)
admin.site.register(TermCandidateEvidence)
admin.site.register(TermAlias)


class RaceLiveReadOnlyAdmin(admin.ModelAdmin):
    """Shared observation-only surface for quasi-realtime race state."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RaceEventProjectionControl)
class RaceEventProjectionControlAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "event",
        "write_owner",
        "owner_generation",
        "next_racecard_revision_no",
        "next_result_revision_no",
        "current_result_revision",
        "updated_at",
    )
    list_filter = ("write_owner", "updated_at")
    search_fields = ("event__chinese_name", "event__original_name", "owner_manifest_sha256")
    raw_id_fields = (
        "event",
        "owner_changed_by",
        "current_racecard_revision",
        "last_known_good_racecard_revision",
        "current_result_revision",
        "last_known_good_result_revision",
        "last_provisional_result_revision",
    )


@admin.register(RaceLiveHostBudget)
class RaceLiveHostBudgetAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "host",
        "min_interval_ms",
        "next_allowed_at",
        "consecutive_failures",
        "circuit_open_until",
        "last_error_code",
        "lock_version",
    )
    list_filter = ("last_error_code",)
    search_fields = ("host", "last_error_code")


@admin.register(RaceLiveOfficialPublicationAuthorization)
class RaceLiveOfficialPublicationAuthorizationAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "event",
        "source_key",
        "route",
        "route_version",
        "max_phase",
        "enabled",
        "version",
        "valid_until",
    )
    list_filter = ("source_key", "max_phase", "enabled")
    search_fields = (
        "event__chinese_name",
        "event__original_name",
        "source_key",
        "route",
        "route_version",
    )
    raw_id_fields = ("event",)


@admin.register(RaceLiveAlertIncident)
class RaceLiveAlertIncidentAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "alert_type",
        "scope_type",
        "scope_key",
        "status",
        "deadline_at",
        "next_attempt_at",
        "delivery_attempts",
        "alert_sent_at",
        "last_error_code",
    )
    list_filter = ("alert_type", "status", "last_error_code")
    search_fields = (
        "scope_type",
        "scope_key",
        "reference_version",
        "dedupe_key",
        "last_error_code",
    )


@admin.register(RaceResultSourceIdentity)
class RaceResultSourceIdentityAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "source_key",
        "external_race_id",
        "event",
        "result_authority",
        "review_status",
        "terms_status",
        "automation_allowed",
        "valid_until",
    )
    list_filter = (
        "source_key",
        "result_authority",
        "review_status",
        "terms_status",
        "automation_allowed",
    )
    search_fields = (
        "source_key",
        "external_race_id",
        "event__chinese_name",
        "event__original_name",
        "canonical_url",
    )
    raw_id_fields = ("event", "reviewed_by")


@admin.register(RaceEventParticipant)
class RaceEventParticipantAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "stable_key",
        "canonical_name",
        "event",
        "country_region",
        "birth_year",
        "review_status",
    )
    list_filter = ("country_region", "review_status")
    search_fields = (
        "stable_key",
        "canonical_name",
        "event__chinese_name",
        "event__original_name",
    )
    raw_id_fields = ("event", "horse_profile", "term")


@admin.register(RaceEventParticipantSourceIdentity)
class RaceEventParticipantSourceIdentityAdmin(RaceLiveReadOnlyAdmin):
    list_display = ("participant", "source_identity", "external_runner_id", "updated_at")
    search_fields = (
        "participant__stable_key",
        "participant__canonical_name",
        "source_identity__source_key",
        "external_runner_id",
    )
    raw_id_fields = ("participant", "source_identity")


@admin.register(RaceResultObservation)
class RaceResultObservationAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "id",
        "source_identity",
        "result_phase",
        "observed_at",
        "source_updated_at",
        "http_status",
        "parser_version",
        "error_code",
        "retryable",
    )
    list_filter = ("result_phase", "source_identity__source_key", "error_code", "retryable")
    search_fields = (
        "source_identity__external_race_id",
        "raw_sha256",
        "normalized_sha256",
        "parser_version",
        "error_code",
    )
    raw_id_fields = ("source_identity",)


@admin.register(RaceEventRevision)
class RaceEventRevisionAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "event",
        "kind",
        "revision_no",
        "phase",
        "source_authority",
        "conflict_status",
        "published_at",
        "official_confirmed_at",
    )
    list_filter = ("kind", "phase", "source_authority", "conflict_status")
    search_fields = (
        "event__chinese_name",
        "event__original_name",
        "content_sha256",
        "decision_reason",
    )
    raw_id_fields = ("event", "primary_observation", "supersedes", "applied_by")


@admin.register(RaceEventRevisionItem)
class RaceEventRevisionItemAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "revision",
        "internal_order",
        "official_finish_position",
        "participant",
        "horse_number",
        "status",
        "finish_time",
    )
    list_filter = ("status", "revision__phase")
    search_fields = (
        "participant__canonical_name",
        "participant__stable_key",
        "horse_number",
        "jockey_name",
        "trainer_name",
    )
    raw_id_fields = ("revision", "participant")


@admin.register(RaceEventRevisionEvidence)
class RaceEventRevisionEvidenceAdmin(RaceLiveReadOnlyAdmin):
    list_display = ("revision", "observation", "role", "created_at")
    list_filter = ("role",)
    search_fields = (
        "revision__event__chinese_name",
        "revision__event__original_name",
        "observation__normalized_sha256",
    )
    raw_id_fields = ("revision", "observation")


@admin.register(RaceEventRevisionPublication)
class RaceEventRevisionPublicationAdmin(RaceLiveReadOnlyAdmin):
    list_display = ("revision", "published_at", "reason", "created_at")
    list_filter = ("reason", "published_at")
    search_fields = (
        "revision__event__chinese_name",
        "revision__event__original_name",
        "revision__content_sha256",
    )
    raw_id_fields = ("revision",)


@admin.register(RaceLivePublicationPolicy)
class RaceLivePublicationPolicyAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "scope_type",
        "scope_key",
        "mode",
        "version",
        "valid_until",
        "updated_at",
    )
    list_filter = ("scope_type", "mode", "valid_until")
    search_fields = ("scope_key", "registry_digest", "coverage_proof_digest")


@admin.register(RaceLiveEventPublicationAllowlist)
class RaceLiveEventPublicationAllowlistAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "event",
        "source_key",
        "max_mode",
        "enabled",
        "official_verification_route",
        "official_verification_route_version",
        "official_verification_contract_digest",
        "version",
    )
    list_filter = ("max_mode", "enabled", "event__country_region")
    search_fields = (
        "event__chinese_name",
        "event__original_name",
        "source_key",
        "official_verification_route",
        "official_verification_route_version",
        "official_verification_contract_digest",
        "official_terms_evidence_digest",
    )
    raw_id_fields = ("event",)


@admin.register(RaceLiveOfficialMarkerContract)
class RaceLiveOfficialMarkerContractAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "country_region",
        "source_key",
        "parser_version",
        "review_status",
        "version",
        "valid_until",
    )
    list_filter = ("country_region", "source_key", "review_status")
    search_fields = ("source_key", "parser_version", "contract_digest")


@admin.register(RaceLiveOfficialMarkerEvidence)
class RaceLiveOfficialMarkerEvidenceAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "observation",
        "contract",
        "marker_type",
        "parser_version",
        "source_timestamp",
        "created_at",
    )
    list_filter = ("marker_type", "contract__country_region", "contract__source_key")
    search_fields = (
        "marker_type",
        "contract_digest",
        "parser_version",
        "raw_sha256",
    )
    raw_id_fields = ("observation", "contract")


@admin.register(RaceLiveOfficialVerificationIncident)
class RaceLiveOfficialVerificationIncidentAdmin(RaceLiveReadOnlyAdmin):
    list_display = (
        "event",
        "provisional_revision",
        "official_route",
        "official_route_version",
        "status",
        "deadline_at",
        "manual_verification_due_at",
        "next_probe_at",
        "alert_sent_at",
    )
    list_filter = ("status", "official_route", "event__country_region")
    search_fields = (
        "event__chinese_name",
        "event__original_name",
        "official_route",
        "official_route_version",
        "official_route_contract_digest",
        "official_terms_evidence_digest",
    )
    raw_id_fields = ("event", "provisional_revision")


@admin.register(RaceEventLiveTracking)
class RaceEventLiveTrackingAdmin(admin.ModelAdmin):
    list_display = (
        "event",
        "state",
        "tracking_enabled",
        "next_poll_at",
        "consecutive_failures",
        "circuit_reason",
        "claim_generation",
        "lock_version",
        "updated_at",
    )
    list_filter = ("tracking_enabled", "state", "circuit_reason")
    search_fields = ("event__chinese_name", "event__original_name", "selection_reason")
    raw_id_fields = ("event",)
    readonly_fields = tuple(
        field.name for field in RaceEventLiveTracking._meta.fields
    )
    actions = ("disable_selected_tracking",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        raise PermissionDenied("准实时追踪仅允许通过停用操作变更。")

    @admin.action(description="停用所选赛事的准实时追踪")
    def disable_selected_tracking(self, request, queryset):
        disabled = 0
        already_disabled = 0
        conflicted = 0
        for event_id, lock_version in queryset.order_by("pk").values_list(
            "event_id", "lock_version"
        ):
            decision = disable_race_event_live_tracking(
                event_id=event_id,
                expected_lock_version=lock_version,
                now=timezone.now(),
                disabled_by=request.user,
            )
            if decision.applied:
                disabled += 1
            elif decision.reason == "already_disabled":
                already_disabled += 1
            else:
                conflicted += 1
        level = messages.SUCCESS if conflicted == 0 else messages.WARNING
        self.message_user(
            request,
            (
                f"准实时追踪停用完成：已停用 {disabled}，"
                f"此前已停用 {already_disabled}，冲突或跳过 {conflicted}。"
            ),
            level,
        )


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


class ArticleRaceLinkInline(admin.TabularInline):
    model = ArticleRaceLink
    extra = 0
    readonly_fields = ("source", "confidence", "matched_text", "match_reason", "created_at", "updated_at")
    fields = ("event", "link_type", "status", "source", "confidence", "matched_text", "match_reason", "created_at")
    can_delete = False


class NewsArticleRelatedRegionInline(admin.TabularInline):
    model = NewsArticleRelatedRegion
    extra = 0
    fields = ("region", "source", "reason", "confidence", "is_manual", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")


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
        "published_at_verified",
        "translation_error_category",
        "translation_retry_count",
        "translation_next_retry_at",
        "workflow_status",
        "automation_status",
        "review_mode",
        "gate_issue_summary",
        "automation_reason_summary",
        "score_total",
        "status",
        "is_first_crawled",
        "published_at_verified",
        "translation_error_category",
        "translation_retry_exhausted_at",
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
        "published_at_verified",
        "published_at_evidence",
        "is_first_crawled",
        "first_seen_at",
        "last_seen_at",
        "attribution_source",
        "attribution_summary",
        "attribution_status",
        "attribution_confidence",
        "attribution_rule_version",
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
        ArticleRaceLinkInline,
        NewsArticleRelatedRegionInline,
    ]
    actions = ["mark_pending_review", "mark_published_ready", "queue_translation", "retry_failed_translations"]

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
                    "published_at_verified",
                    "published_at_evidence",
                )
            },
        ),
        ("来源原文", {"fields": ("title_ja", "body_ja_raw", "body_ja_normalized")}),
        ("翻译参考", {"fields": ("translated_title_zh", "translated_summary_zh", "translated_body_zh", "translation_error_category", "translation_retry_count", "translation_next_retry_at", "translation_retry_exhausted_at")}),
        ("自动化运营", {"fields": ("review_mode", "risk_level", "automation_status", "content_category", "attribution_source", "attribution_locked", "attribution_summary", "score_total", "quality_score", "rewrite_confidence", "decision_summary", "decision_reason", "gate_issues", "gate_issue_summary", "base_translation_zh", "rewrite_title_zh", "rewrite_summary_zh", "rewrite_body_zh", "published_by_mode", "auto_publish_at", "automation_error_message")}),
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
        count = 0
        for article in queryset:
            article.workflow_status = WorkflowStatus.PENDING_REVIEW
            article.save(update_fields=["workflow_status", "updated_at"])
            count += 1
        self.message_user(request, f"已将 {count} 篇文章标记为待审核。", messages.SUCCESS, fail_silently=True)

    @admin.action(description="标记为可推送")
    def mark_published_ready(self, request, queryset):
        count = queryset.update(status=ArticleStatus.PUSH_READY)
        self.message_user(request, f"已将 {count} 篇文章标记为可推送。", messages.SUCCESS)

    @admin.action(description="加入翻译队列")
    def queue_translation(self, request, queryset):
        for article in queryset:
            dispatch_task(translate_article_task, article.id)
        self.message_user(request, f"已将 {queryset.count()} 篇文章加入翻译队列。", messages.SUCCESS)

    @admin.action(description="立即重试失败翻译")
    def retry_failed_translations(self, request, queryset):
        from stable.services.translation_recovery import request_manual_translation_retry

        accepted = 0
        for article in queryset:
            result = request_manual_translation_retry(article, requested_by=request.user)
            if result.accepted:
                accepted += 1
                dispatch_task(translate_article_task, article.id)
        self.message_user(request, f"已接受 {accepted} 篇失败文章的翻译重试请求。", messages.SUCCESS)

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

    def automation_reason_summary(self, obj):
        if obj.decision_reason:
            if obj.decision_reason.get("region_minimum_fill"):
                return "保底发布"
            if obj.decision_reason.get("publish_policy"):
                return obj.decision_reason["publish_policy"].get("reason", "-")
        if obj.duplicate_of_id:
            return f"去重 -> #{obj.duplicate_of_id}"
        return obj.decision_summary or "-"

    automation_reason_summary.short_description = "自动化原因"

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
        if article.translation_status == ArticleTranslationStatus.FAILED:
            from stable.services.translation_recovery import request_manual_translation_retry

            request_manual_translation_retry(article, requested_by=request.user)
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
        "production_approved",
        "crawl_interval_minutes",
        "effective_crawl_interval_minutes",
        "backoff_until",
        "failure_streak",
        "last_error_category",
        "last_crawl_at",
        "last_crawl_status",
        "test_crawl_link",
    )
    list_filter = (
        "enabled",
        "production_approved",
        "allow_event_boost",
        "racing_region",
        "source_language",
        "source_kind",
        "source_type",
        "adapter_key",
        "last_error_category",
    )
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


@admin.register(MajorRaceEvent)
class MajorRaceEventAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "year",
        "racing_region",
        "race_grade",
        "local_date",
        "local_start_time",
        "boost_start_at",
        "boost_end_at",
        "is_active",
    )
    list_filter = ("racing_region", "race_grade", "is_active", "local_date")
    search_fields = ("name", "normalized_name", "external_id", "aliases", "notes")
    readonly_fields = ("boost_start_at", "boost_end_at", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        update_major_race_boost_window(obj)


class RaceEventAliasInline(admin.TabularInline):
    model = RaceEventAlias
    extra = 0


class RaceEventRunnerInline(admin.TabularInline):
    model = RaceEventRunner
    extra = 0
    fields = (
        "sort_order",
        "horse_number",
        "barrier",
        "horse_name",
        "jockey_name",
        "trainer_name",
        "carried_weight",
        "odds_value",
        "popularity",
        "running_status",
        "dynamic_updated_at",
    )


class RaceEventResultInline(admin.TabularInline):
    model = RaceEventResult
    extra = 0
    fields = (
        "finish_position",
        "horse_number",
        "horse_name",
        "jockey_name",
        "trainer_name",
        "finish_time",
        "margin",
        "odds_value",
        "popularity",
        "is_confirmed",
    )


class RaceEventHistoryWinnerInline(admin.TabularInline):
    model = RaceEventHistoryWinner
    extra = 0


class RaceEventDataCandidateInline(admin.TabularInline):
    model = RaceEventDataCandidate
    extra = 0
    readonly_fields = ("source_name", "source_url", "status", "confidence", "fetched_at", "applied_by", "applied_at")
    can_delete = False


class RaceEventArticleLinkInline(admin.TabularInline):
    model = ArticleRaceLink
    extra = 0
    readonly_fields = ("source", "confidence", "matched_text", "match_reason", "created_at", "updated_at")
    fields = ("article", "link_type", "status", "source", "confidence", "matched_text", "match_reason", "created_at")


class HistoricalInventoryReadOnlyAdmin(admin.ModelAdmin):
    actions = None

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class HistoricalTargetModuleFilter(admin.SimpleListFilter):
    title = "资料模块"
    parameter_name = "module"

    def lookups(self, request, model_admin):
        return (
            ("basic", "基础资料"),
            ("runners", "出马表"),
            ("results", "赛果"),
            ("history_winners", "冠军覆盖"),
        )

    def queryset(self, request, queryset):
        return queryset.filter(module_statuses__has_key=self.value()) if self.value() else queryset


@admin.register(RaceSeries)
class RaceSeriesAdmin(HistoricalInventoryReadOnlyAdmin):
    list_display = (
        "key",
        "country_region",
        "canonical_name_original",
        "chinese_name",
        "founded_year",
        "ended_year",
        "status",
        "review_status",
    )
    list_filter = ("country_region", "status", "review_status")
    search_fields = ("key", "canonical_name_original", "chinese_name", "names__text")
    list_per_page = 100


@admin.register(RaceSeriesName)
class RaceSeriesNameAdmin(HistoricalInventoryReadOnlyAdmin):
    list_display = ("text", "series", "source_language", "name_type", "valid_from_year", "valid_to_year")
    list_filter = ("source_language", "name_type", "is_active")
    search_fields = ("text", "normalized_text", "series__key", "series__canonical_name_original")
    list_select_related = ("series",)
    list_per_page = 100


@admin.register(RaceSeriesRelation)
class RaceSeriesRelationAdmin(HistoricalInventoryReadOnlyAdmin):
    list_display = ("from_series", "relation_type", "to_series", "effective_year", "review_status", "approved_by")
    list_filter = ("relation_type", "review_status", "effective_year")
    search_fields = (
        "from_series__key",
        "to_series__key",
        "from_series__canonical_name_original",
        "to_series__canonical_name_original",
    )
    list_select_related = ("from_series", "to_series", "approved_by")
    list_per_page = 100


@admin.register(HistoricalRaceEventTarget)
class HistoricalRaceEventTargetAdmin(HistoricalInventoryReadOnlyAdmin):
    change_list_template = "admin/stable/historical_race_event_target/change_list.html"
    list_display = (
        "year",
        "race_series",
        "country_region",
        "expectation_status",
        "resolution_status",
        "original_name",
        "event",
        "last_checked_at",
    )
    list_filter = (
        "country_region",
        "year",
        "expectation_status",
        "resolution_status",
        HistoricalTargetModuleFilter,
        "race_series",
    )
    search_fields = (
        "race_series__key",
        "race_series__canonical_name_original",
        "race_series__chinese_name",
        "original_name",
        "chinese_name",
    )
    list_select_related = ("race_series", "event")
    list_per_page = 100

    def changelist_view(self, request, extra_context=None):
        queryset = self.get_queryset(request)
        summary = {
            "target_count": queryset.count(),
            "by_region": list(
                queryset.values("country_region").annotate(count=Count("id")).order_by("country_region")
            ),
            "by_expectation": list(
                queryset.values("expectation_status").annotate(count=Count("id")).order_by("expectation_status")
            ),
            "by_resolution": list(
                queryset.values("resolution_status").annotate(count=Count("id")).order_by("resolution_status")
            ),
        }
        return super().changelist_view(
            request,
            extra_context={**(extra_context or {}), "inventory_summary": summary},
        )


@admin.register(RaceEvent)
class RaceEventAdmin(admin.ModelAdmin):
    list_display = (
        "chinese_name",
        "original_name",
        "year",
        "country_region",
        "racecourse",
        "grade_text",
        "surface",
        "priority",
        "status",
        "visibility_status",
        "data_quality_status",
        "local_date",
        "is_featured",
    )
    list_filter = (
        "year",
        "country_region",
        "priority",
        "status",
        "visibility_status",
        "data_quality_status",
        "surface",
        "normalized_grade",
    )
    search_fields = ("chinese_name", "original_name", "slug", "series_key", "racecourse", "aliases__text")
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("original_name",)}
    inlines = [
        RaceEventAliasInline,
        RaceEventRunnerInline,
        RaceEventResultInline,
        RaceEventHistoryWinnerInline,
        RaceEventDataCandidateInline,
        RaceEventArticleLinkInline,
    ]


@admin.register(RaceEventDataCandidate)
class RaceEventDataCandidateAdmin(admin.ModelAdmin):
    list_display = ("event", "module", "source_name", "status", "confidence", "fetched_at", "applied_by", "applied_at")
    list_filter = ("module", "status", "source_name", "fetched_at")
    search_fields = ("event__chinese_name", "event__original_name", "source_name", "source_url", "error_message")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RaceEventAlias)
class RaceEventAliasAdmin(admin.ModelAdmin):
    list_display = ("event", "text", "source_language", "alias_type", "source", "is_active")
    list_filter = ("source_language", "alias_type", "is_active")
    search_fields = ("event__chinese_name", "event__original_name", "text", "source")


@admin.register(RaceEventRunner)
class RaceEventRunnerAdmin(admin.ModelAdmin):
    list_display = ("event", "sort_order", "horse_number", "barrier", "horse_name", "jockey_name", "running_status")
    list_filter = ("running_status", "event__country_region", "event__year")
    search_fields = ("event__chinese_name", "event__original_name", "horse_name", "jockey_name", "trainer_name")


@admin.register(RaceEventResult)
class RaceEventResultAdmin(admin.ModelAdmin):
    list_display = ("event", "finish_position", "horse_number", "horse_name", "jockey_name", "margin", "is_confirmed")
    list_filter = ("is_confirmed", "event__country_region", "event__year")
    search_fields = ("event__chinese_name", "event__original_name", "horse_name", "jockey_name", "trainer_name")


@admin.register(RaceEventHistoryWinner)
class RaceEventHistoryWinnerAdmin(admin.ModelAdmin):
    list_display = ("event", "winner_year", "horse_name", "jockey_name", "trainer_name", "margin")
    list_filter = ("winner_year", "event__country_region")
    search_fields = ("event__chinese_name", "event__original_name", "horse_name", "jockey_name", "trainer_name")


@admin.register(ArticleRaceLink)
class ArticleRaceLinkAdmin(admin.ModelAdmin):
    list_display = ("event", "article", "link_type", "status", "source", "confidence", "confirmed_at", "removed_at")
    list_filter = ("link_type", "status", "source", "event__country_region")
    search_fields = ("event__chinese_name", "event__original_name", "article__title_ja", "article__title_zh", "matched_text")
    readonly_fields = ("created_at", "updated_at")


class WindowCandidateDecisionInline(admin.TabularInline):
    model = WindowCandidateDecision
    extra = 0
    readonly_fields = ("article", "status", "reason", "score", "rank", "payload", "created_at")
    can_delete = False


class WindowTargetDecisionInline(admin.TabularInline):
    model = WindowTargetDecision
    extra = 0
    readonly_fields = ("target", "article", "status", "reason", "payload", "created_at")
    can_delete = False


@admin.register(ProductionWindow)
class ProductionWindowAdmin(admin.ModelAdmin):
    list_display = (
        "kind",
        "mode",
        "racing_region",
        "scope_key",
        "window_start",
        "status",
        "reason_summary",
        "attempt_count",
        "rerun_count",
    )
    list_filter = ("kind", "mode", "status", "racing_region", "window_start")
    search_fields = ("scope_key", "reason_summary", "last_error")
    readonly_fields = (
        "kind",
        "mode",
        "racing_region",
        "source",
        "target",
        "scope_key",
        "window_start",
        "window_end",
        "status",
        "claimed_at",
        "lease_expires_at",
        "attempt_count",
        "scheduled_at",
        "started_at",
        "finished_at",
        "reason_summary",
        "result_payload",
        "rerun_count",
        "last_error",
        "triggered_by",
        "created_at",
        "updated_at",
    )
    inlines = [WindowCandidateDecisionInline, WindowTargetDecisionInline]


@admin.register(QuotaLedger)
class QuotaLedgerAdmin(admin.ModelAdmin):
    list_display = ("kind", "scope", "scope_key", "window_start", "limit", "used", "updated_at")
    list_filter = ("kind", "scope", "window_start")
    search_fields = ("scope_key",)
    readonly_fields = ("kind", "scope", "scope_key", "window_start", "limit", "used", "payload", "created_at", "updated_at")


@admin.register(TermEntry)
class TermEntryAdmin(admin.ModelAdmin):
    list_display = (
        "source_ja",
        "source_language",
        "racing_region",
        "target_zh",
        "translation_status",
        "term_type",
        "race_grade",
        "priority",
        "is_active",
        "updated_at",
    )
    list_filter = ("source_language", "racing_region", "term_type", "translation_status", "race_grade", "is_active")
    search_fields = ("source_ja", "target_zh", "notes")


@admin.register(HorseProfileCompletionRun)
class HorseProfileCompletionRunAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "status", "dry_run", "regions", "artifact_path", "started_at", "finished_at", "created_at")
    list_filter = ("status", "dry_run", "created_at")
    search_fields = ("name", "artifact_path", "error_message")
    readonly_fields = ("created_at", "updated_at")


@admin.register(HorseP0Source)
class HorseP0SourceAdmin(admin.ModelAdmin):
    list_display = (
        "profile",
        "source_type",
        "status",
        "racing_region",
        "race_grade",
        "race_event",
        "participant_key",
        "term",
        "observed_at",
    )
    list_filter = ("source_type", "status", "racing_region", "race_grade")
    search_fields = (
        "profile__display_name_zh",
        "profile__original_name",
        "horse_name",
        "participant_key",
        "source_url",
        "evidence_summary",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(HorseIdentityConflict)
class HorseIdentityConflictAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "horse_name",
        "horse_number",
        "status",
        "race_event",
        "resolved_profile",
        "resolved_horse_number",
        "observed_at",
        "resolved_at",
    )
    list_filter = ("status", "race_event__country_region", "observed_at", "resolved_at")
    search_fields = (
        "horse_name",
        "horse_number",
        "resolved_horse_number",
        "fingerprint",
        "sire_name",
        "dam_name",
        "source_url",
        "resolution_notes",
    )
    raw_id_fields = ("candidate_terms", "candidate_profiles", "resolved_profile", "race_event")
    readonly_fields = ("fingerprint", "evidence_payload", "observed_at", "resolved_at", "resolved_by", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if obj.status in {HorseIdentityConflictStatus.RESOLVED, HorseIdentityConflictStatus.IGNORED}:
            obj.resolved_by = request.user
            obj.resolved_at = timezone.now()
        else:
            obj.resolved_by = None
            obj.resolved_at = None
        super().save_model(request, obj, form, change)


@admin.register(PushTarget)
class PushTargetAdmin(admin.ModelAdmin):
    list_display = ("name", "group_id", "allowed_regions", "multiregion_test_enabled", "push_scope", "importance_strategy", "is_default", "is_active", "updated_at")
    list_filter = ("multiregion_test_enabled", "push_scope", "importance_strategy", "is_default", "is_active")
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


@admin.register(TermGateReprocessRun)
class TermGateReprocessRunAdmin(admin.ModelAdmin):
    list_display = ("id", "mode", "status", "started_at", "finished_at", "manifest_sha256")
    list_filter = ("mode", "status", "started_at")
    search_fields = ("id", "manifest_sha256", "error_message")
    readonly_fields = (
        "mode", "selectors", "status", "cursor", "rule_version", "settings_sha256",
        "term_snapshot_sha256", "candidate_payload", "result_payload", "manifest_sha256",
        "statistics", "error_message", "started_at", "finished_at", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

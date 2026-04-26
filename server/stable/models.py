from __future__ import annotations

from typing import Iterable

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class SourceSite(models.TextChoices):
    NETKEIBA = "netkeiba", "netkeiba"
    JRA = "jra", "JRA"


class SourceMode(models.TextChoices):
    LATEST = "latest", "新着顺"
    ACCESS = "access", "访问量榜"
    ATTENTION = "attention", "注目数榜"
    OFFICIAL = "official", "官方新闻"


class SourceType(models.TextChoices):
    BUILTIN = "builtin", "内置适配器"
    RSS = "rss", "RSS"
    HTML_LIST = "html_list", "HTML 列表页"
    ARTICLE_TEMPLATE = "article_template", "文章页模板"


class SourceLanguage(models.TextChoices):
    JAPANESE = "ja", "日文"
    ENGLISH = "en", "英文"
    CHINESE = "zh", "中文"


class ArticleStatus(models.TextChoices):
    CRAWLED = "crawled", "已抓取"
    TRANSLATED = "translated", "已翻译"
    REVIEWED = "reviewed", "已审核"
    PUSH_READY = "push_ready", "可推送"
    PUSHED = "pushed", "已推送"
    PUSH_FAILED = "push_failed", "推送失败"


class WorkflowStatus(models.TextChoices):
    PENDING_TRANSLATION = "pending_translation", "待翻译"
    TRANSLATION_FAILED = "translation_failed", "翻译失败"
    PENDING_EDIT = "pending_edit", "待编辑"
    PENDING_REVIEW = "pending_review", "待审核"
    PUBLISHED = "published", "已发布"
    REJECTED = "rejected", "已驳回"
    WITHDRAWN = "withdrawn", "已撤回"
    ARCHIVED = "archived", "已归档"
    IGNORED = "ignored", "已忽略"


class PushStatus(models.TextChoices):
    QUEUED = "queued", "排队中"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失败"


class TaskStatus(models.TextChoices):
    STARTED = "started", "运行中"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失败"


class TranslationStatus(models.TextChoices):
    STARTED = "started", "进行中"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失败"


class ArticleTranslationStatus(models.TextChoices):
    PENDING = "pending", "待翻译"
    TRANSLATING = "translating", "翻译中"
    TRANSLATED = "translated", "已翻译"
    FAILED = "failed", "翻译失败"


class CrawlStatus(models.TextChoices):
    SUCCESS = "success", "成功"
    FAILED = "failed", "失败"
    IGNORED = "ignored", "忽略"


class MediaAssetStatus(models.TextChoices):
    READY = "ready", "可用"
    FAILED = "failed", "失败"


class TermType(models.TextChoices):
    HORSE = "horse", "马名"
    RACE = "race", "赛事"
    JOCKEY = "jockey", "骑手"
    TRAINER = "trainer", "调教师"
    OWNER = "owner", "马主"
    FARM = "farm", "牧场"
    RACECOURSE = "racecourse", "赛马场"
    ORG = "org", "机构"
    FIXED_PHRASE = "fixed_phrase", "固定译法"
    OTHER = "other", "其他"


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class NewsSource(TimestampedModel):
    name = models.CharField(max_length=255)
    homepage_url = models.URLField(max_length=1000)
    feed_url = models.URLField(max_length=1000)
    source_type = models.CharField(max_length=32, choices=SourceType.choices, default=SourceType.BUILTIN)
    language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    adapter_key = models.CharField(max_length=64, blank=True)
    source_site = models.CharField(max_length=32, choices=SourceSite.choices, blank=True)
    source_mode = models.CharField(max_length=32, choices=SourceMode.choices, blank=True)
    enabled = models.BooleanField(default=True)
    crawl_interval_minutes = models.PositiveIntegerField(default=60)
    notes = models.TextField(blank=True)
    logo_url = models.URLField(max_length=1000, blank=True)
    priority = models.IntegerField(default=0)
    default_tags = models.JSONField(default=list, blank=True)
    last_crawl_at = models.DateTimeField(null=True, blank=True)
    last_crawl_status = models.CharField(max_length=16, choices=TaskStatus.choices, blank=True)
    last_crawl_message = models.TextField(blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-enabled", "-priority", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("source_site", "source_mode"),
                condition=models.Q(deleted_at__isnull=True) & ~models.Q(source_site="") & ~models.Q(source_mode=""),
                name="uq_news_source_site_mode_active",
            )
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class CrawlJob(TimestampedModel):
    source = models.ForeignKey(NewsSource, on_delete=models.SET_NULL, null=True, blank=True, related_name="crawl_jobs")
    status = models.CharField(max_length=16, choices=TaskStatus.choices, default=TaskStatus.STARTED)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    success_count = models.PositiveIntegerField(default=0)
    fail_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ("-started_at", "-id")

    def __str__(self) -> str:
        source_name = self.source.name if self.source else "unknown"
        return f"{source_name} {self.started_at:%Y-%m-%d %H:%M}"


class NewsArticle(TimestampedModel):
    source_config = models.ForeignKey(
        NewsSource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
    )
    crawl_job = models.ForeignKey(
        CrawlJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
    )
    source_site = models.CharField(max_length=32, choices=SourceSite.choices)
    source_mode = models.CharField(max_length=32, choices=SourceMode.choices)
    source_article_id = models.CharField(max_length=255)
    title_ja = models.CharField(max_length=500)
    body_ja_raw = models.TextField(blank=True)
    body_ja_normalized = models.TextField(blank=True)
    original_content_html = models.TextField(blank=True)
    original_author = models.CharField(max_length=255, blank=True)
    translated_title_zh = models.CharField(max_length=500, blank=True)
    translated_body_zh = models.TextField(blank=True)
    translated_summary_zh = models.TextField(blank=True)
    title_zh = models.CharField(max_length=500, blank=True)
    summary_zh = models.TextField(blank=True)
    body_zh = models.TextField(blank=True)
    push_summary_zh = models.TextField(blank=True)
    published_at = models.DateTimeField()
    source_url = models.URLField(max_length=1000)
    is_first_crawled = models.BooleanField(default=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    crawl_status = models.CharField(max_length=16, choices=CrawlStatus.choices, default=CrawlStatus.SUCCESS)
    status = models.CharField(max_length=32, choices=ArticleStatus.choices, default=ArticleStatus.CRAWLED)
    workflow_status = models.CharField(
        max_length=32,
        choices=WorkflowStatus.choices,
        default=WorkflowStatus.PENDING_TRANSLATION,
    )
    editor_notes = models.TextField(blank=True)
    manually_edited_fields = models.JSONField(default=list, blank=True)
    translation_metadata = models.JSONField(default=dict, blank=True)
    translation_status = models.CharField(
        max_length=16,
        choices=ArticleTranslationStatus.choices,
        default=ArticleTranslationStatus.PENDING,
    )
    translation_error_message = models.TextField(blank=True)
    translation_started_at = models.DateTimeField(null=True, blank=True)
    translated_at = models.DateTimeField(null=True, blank=True)
    translation_model = models.CharField(max_length=128, blank=True)
    translation_provider = models.CharField(max_length=64, blank=True)
    translation_retry_count = models.PositiveIntegerField(default=0)
    tags_json = models.JSONField(default=list, blank=True)
    source_note = models.CharField(max_length=255, blank=True)
    public_slug = models.SlugField(max_length=255, blank=True)
    published_to_web_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    ignored_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_articles",
    )
    cover_media_asset = models.ForeignKey(
        "MediaAsset",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cover_for_articles",
    )

    class Meta:
        ordering = ("-published_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("source_site", "source_article_id"),
                name="uq_article_source_article_id",
            )
        ]

    def __str__(self) -> str:
        return self.effective_title

    def save(self, *args, **kwargs):
        if not self.public_slug and (self.title_zh or self.title_ja):
            base = slugify(self.title_zh or self.title_ja, allow_unicode=True)[:80] or f"article-{self.pk or 'draft'}"
            self.public_slug = base
        super().save(*args, **kwargs)
        if self.public_slug.endswith("-draft"):
            stable_slug = slugify(self.title_zh or self.title_ja, allow_unicode=True)[:80] or "article"
            expected = f"{stable_slug}-{self.pk}"
            if self.public_slug != expected:
                self.public_slug = expected
                super().save(update_fields=["public_slug", "updated_at"])

    @property
    def effective_title(self) -> str:
        return self.title_zh or self.translated_title_zh or self.title_ja

    @property
    def effective_body(self) -> str:
        return self.body_zh or self.translated_body_zh or self.body_ja_normalized or self.body_ja_raw

    @property
    def effective_summary(self) -> str:
        manual_fields = set(self.manually_edited_fields or [])
        if "summary_zh" in manual_fields:
            return self.summary_zh or ""
        if self.summary_zh:
            return self.summary_zh
        if "push_summary_zh" in manual_fields:
            return self.push_summary_zh or ""
        if self.push_summary_zh:
            return self.push_summary_zh
        if self.translated_summary_zh:
            return self.translated_summary_zh
        return self.effective_body[:180]

    @property
    def main_image(self) -> "NewsImage | None":
        return self.images.order_by("sort_order", "id").first()

    @property
    def cover_image_url(self) -> str | None:
        if self.cover_media_asset and self.cover_media_asset.public_url:
            return self.cover_media_asset.public_url
        image = self.main_image
        return image.public_url if image else None

    @property
    def public_path(self) -> str:
        return f"/news/{self.public_slug or self.pk}/"

    def mark_manual_edits(self, fields: Iterable[str]) -> None:
        current = set(self.manually_edited_fields or [])
        current.update(fields)
        self.manually_edited_fields = sorted(current)

    def _suggested_tags(self) -> list[str]:
        from stable.services.terms import extract_horse_tags

        source_text = "\n".join(
            [
                self.title_ja or "",
                self.body_ja_normalized or self.body_ja_raw or "",
            ]
        ).strip()
        return extract_horse_tags(source_text, limit=12)

    def ensure_editable_fields(self) -> None:
        manual_fields = set(self.manually_edited_fields or [])
        if not self.title_zh:
            self.title_zh = self.translated_title_zh
        if not self.body_zh:
            self.body_zh = self.translated_body_zh
        if "summary_zh" not in manual_fields and not self.summary_zh:
            self.summary_zh = self.translated_summary_zh or (self.translated_body_zh or "")[:160]
        if "push_summary_zh" not in manual_fields and not self.push_summary_zh:
            self.push_summary_zh = self.translated_summary_zh or (self.translated_body_zh or "")[:160]
        if "tags_json" not in manual_fields:
            merged_tags: list[str] = []
            seen: set[str] = set()
            for tag in [*(self.tags_json or []), *self._suggested_tags()]:
                normalized = (tag or "").strip()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    merged_tags.append(normalized)
            self.tags_json = merged_tags

    @property
    def has_translation(self) -> bool:
        return bool(self.translated_title_zh or self.translated_body_zh or self.translated_summary_zh)

    @property
    def latest_translation_run(self) -> "TranslationRun | None":
        return self.translation_runs.order_by("-created_at", "-id").first()

    def apply_translation_result(self, result: object, *, force: bool = False) -> None:
        manual_fields = set(self.manually_edited_fields or [])
        title_zh = (getattr(result, "title_zh", "") or "").strip()
        body_zh = (getattr(result, "body_zh", "") or "").strip()
        summary_zh = (getattr(result, "push_summary_zh", "") or "").strip()

        self.translated_title_zh = title_zh
        self.translated_body_zh = body_zh
        self.translated_summary_zh = summary_zh

        if force or "title_zh" not in manual_fields or not self.title_zh:
            self.title_zh = title_zh
        if force or "body_zh" not in manual_fields or not self.body_zh:
            self.body_zh = body_zh
        if force or "summary_zh" not in manual_fields:
            self.summary_zh = summary_zh or body_zh[:160]
        if force or "push_summary_zh" not in manual_fields:
            self.push_summary_zh = summary_zh or body_zh[:160]
        if force or "tags_json" not in manual_fields:
            merged_tags: list[str] = []
            seen: set[str] = set()
            for tag in [*(self.tags_json or []), *self._suggested_tags()]:
                normalized = (tag or "").strip()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    merged_tags.append(normalized)
            self.tags_json = merged_tags


class NewsImage(TimestampedModel):
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="images")
    original_url = models.URLField(max_length=1000)
    local_path = models.CharField(max_length=500, blank=True)
    caption_ja = models.TextField(blank=True)
    caption_zh = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")

    def __str__(self) -> str:
        return self.caption_zh or self.caption_ja or self.original_url

    @property
    def public_url(self) -> str:
        if self.local_path:
            from stable.services.storage import resolve_media_url

            return resolve_media_url(self.local_path)
        return self.original_url


class MediaAsset(TimestampedModel):
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="media_assets")
    source_image = models.ForeignKey(
        NewsImage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_assets",
    )
    original_image_url = models.URLField(max_length=1000)
    internal_image_url = models.CharField(max_length=1000, blank=True)
    storage_provider = models.CharField(max_length=32, default="local")
    status = models.CharField(max_length=16, choices=MediaAssetStatus.choices, default=MediaAssetStatus.READY)
    is_cover = models.BooleanField(default=False)
    crop_ratio = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ("-is_cover", "id")

    def __str__(self) -> str:
        return self.public_url or self.original_image_url

    @property
    def public_url(self) -> str:
        if not self.internal_image_url:
            return ""
        if self.internal_image_url.startswith("http://") or self.internal_image_url.startswith("https://"):
            return self.internal_image_url
        url = default_storage.url(self.internal_image_url.lstrip("/"))
        if url.startswith(("http://", "https://")):
            return url
        if url.startswith("/"):
            return f"{settings.SITE_URL.rstrip('/')}{url}"
        return f"{settings.SITE_URL.rstrip('/')}/{url.lstrip('/')}"


class NewsSnapshot(TimestampedModel):
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="snapshots")
    source_site = models.CharField(max_length=32, choices=SourceSite.choices)
    source_mode = models.CharField(max_length=32, choices=SourceMode.choices)
    rank = models.PositiveIntegerField(null=True, blank=True)
    comment_count = models.PositiveIntegerField(null=True, blank=True)
    attention_count = models.PositiveIntegerField(null=True, blank=True)
    snapshot_metadata = models.JSONField(default=dict, blank=True)
    captured_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-captured_at", "-id")


class TermEntry(TimestampedModel):
    term_type = models.CharField(max_length=32, choices=TermType.choices, default=TermType.OTHER)
    source_ja = models.CharField(max_length=255)
    target_zh = models.CharField(max_length=255)
    aliases_ja = models.JSONField(default=list, blank=True)
    aliases_zh = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)

    class Meta:
        ordering = ("-priority", "source_ja")

    def __str__(self) -> str:
        return f"{self.source_ja} -> {self.target_zh}"

    def all_japanese_terms(self) -> list[str]:
        aliases = self.aliases_ja if isinstance(self.aliases_ja, list) else []
        return [self.source_ja, *aliases]


class PushTarget(TimestampedModel):
    name = models.CharField(max_length=255)
    group_id = models.CharField(max_length=64, unique=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-is_default", "name")

    def __str__(self) -> str:
        return f"{self.name} ({self.group_id})"


class PushLog(TimestampedModel):
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="push_logs")
    target = models.ForeignKey(PushTarget, on_delete=models.CASCADE, related_name="push_logs")
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_push_logs",
    )
    status = models.CharField(max_length=16, choices=PushStatus.choices, default=PushStatus.QUEUED)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")


class TranslationRun(TimestampedModel):
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="translation_runs")
    provider_name = models.CharField(max_length=64)
    model_name = models.CharField(max_length=128)
    terms_used = models.JSONField(default=list, blank=True)
    prompt_excerpt = models.TextField(blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=TranslationStatus.choices)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at", "-id")


class TaskExecutionLog(TimestampedModel):
    task_name = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=TaskStatus.choices)
    payload = models.JSONField(default=dict, blank=True)
    detail = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at", "-id")


class OperationLog(models.Model):
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operation_logs",
    )
    action_type = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=64, blank=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return f"{self.action_type} {self.target_type} {self.target_id}".strip()

from __future__ import annotations

from typing import Iterable

from django.conf import settings
from django.db import models
from django.utils import timezone


class SourceSite(models.TextChoices):
    NETKEIBA = "netkeiba", "netkeiba"
    JRA = "jra", "JRA"


class SourceMode(models.TextChoices):
    LATEST = "latest", "新着順"
    ACCESS = "access", "アクセス順"
    ATTENTION = "attention", "注目数順"
    OFFICIAL = "official", "JRA官方"


class ArticleStatus(models.TextChoices):
    CRAWLED = "crawled", "已抓取"
    TRANSLATED = "translated", "已翻译"
    REVIEWED = "reviewed", "已审核"
    PUSH_READY = "push_ready", "可推送"
    PUSHED = "pushed", "已推送"
    PUSH_FAILED = "push_failed", "推送失败"


class PushStatus(models.TextChoices):
    QUEUED = "queued", "排队中"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失败"


class TaskStatus(models.TextChoices):
    STARTED = "started", "运行中"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失败"


class TranslationStatus(models.TextChoices):
    SUCCESS = "success", "成功"
    FAILED = "failed", "失败"


class TermType(models.TextChoices):
    HORSE = "horse", "马名"
    RACE = "race", "赛事"
    JOCKEY = "jockey", "骑手"
    TRAINER = "trainer", "练马师"
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


class NewsArticle(TimestampedModel):
    source_site = models.CharField(max_length=32, choices=SourceSite.choices)
    source_mode = models.CharField(max_length=32, choices=SourceMode.choices)
    source_article_id = models.CharField(max_length=255)
    title_ja = models.CharField(max_length=500)
    body_ja_raw = models.TextField(blank=True)
    body_ja_normalized = models.TextField(blank=True)
    title_zh = models.CharField(max_length=500, blank=True)
    body_zh = models.TextField(blank=True)
    push_summary_zh = models.TextField(blank=True)
    published_at = models.DateTimeField()
    source_url = models.URLField(max_length=1000)
    is_first_crawled = models.BooleanField(default=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=32, choices=ArticleStatus.choices, default=ArticleStatus.CRAWLED)
    editor_notes = models.TextField(blank=True)
    manually_edited_fields = models.JSONField(default=list, blank=True)
    translation_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-published_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("source_site", "source_article_id"),
                name="uq_article_source_article_id",
            )
        ]

    def __str__(self) -> str:
        return self.title_zh or self.title_ja

    @property
    def effective_title(self) -> str:
        return self.title_zh or self.title_ja

    @property
    def effective_body(self) -> str:
        return self.body_zh or self.body_ja_normalized or self.body_ja_raw

    @property
    def effective_summary(self) -> str:
        if self.push_summary_zh:
            return self.push_summary_zh
        return self.effective_body[:180]

    @property
    def main_image(self) -> "NewsImage | None":
        return self.images.order_by("sort_order", "id").first()

    def mark_manual_edits(self, fields: Iterable[str]) -> None:
        current = set(self.manually_edited_fields or [])
        current.update(fields)
        self.manually_edited_fields = sorted(current)


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
            return f"{settings.SITE_URL.rstrip('/')}{settings.MEDIA_URL}{self.local_path}"
        return self.original_url


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

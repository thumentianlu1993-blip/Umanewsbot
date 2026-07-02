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
    SPONICHI = "sponichi", "Sponichi"
    HKJC_NEWS = "hkjc_news", "HKJC Racing News"
    SCMP_RACING = "scmp_racing", "SCMP Racing"
    SPORTING_LIFE = "sporting_life", "Sporting Life Racing"
    SKY_SPORTS_RACING = "sky_sports_racing", "Sky Sports Racing"
    BHA = "bha", "BHA"
    FRANCE_GALOP_NEWS = "france_galop_news", "France Galop English News"
    TDN = "tdn", "Thoroughbred Daily News"
    TDN_FRANCE = "tdn_france", "TDN France Keyword News"
    HORSE_RACING_NATION = "horse_racing_nation", "Horse Racing Nation"
    AT_THE_RACES = "at_the_races", "At The Races"
    BLOODHORSE = "bloodhorse", "BloodHorse"
    PAULICK_REPORT = "paulick_report", "Paulick Report"


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
    CHINESE_TRADITIONAL = "zh-hant", "繁体中文"
    FRENCH = "fr", "法语"


class RacingRegion(models.TextChoices):
    JAPAN = "japan", "日本"
    HONG_KONG = "hong_kong", "中国香港"
    UNITED_KINGDOM = "united_kingdom", "英国"
    FRANCE = "france", "法国"
    UNITED_STATES = "united_states", "美国"
    OTHER = "other", "其他"


class SourceKind(models.TextChoices):
    NEWS = "news", "新闻"
    DATABASE = "database", "数据库"
    OFFICIAL = "official", "官方"
    MEDIA = "media", "媒体"


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
    DUPLICATE = "duplicate", "重复内容"
    REJECTED = "rejected", "已驳回"
    WITHDRAWN = "withdrawn", "已撤回"
    ARCHIVED = "archived", "已归档"
    IGNORED = "ignored", "已忽略"


class ReviewMode(models.TextChoices):
    AUTO = "auto", "自动发布"
    MANUAL = "manual", "人工审核"
    IGNORED = "ignored", "忽略"


class RiskLevel(models.TextChoices):
    LOW = "low", "低风险"
    MEDIUM = "medium", "中风险"
    HIGH = "high", "高风险"


class AutomationStatus(models.TextChoices):
    PENDING = "pending", "待处理"
    SCORED = "scored", "已评分"
    REWRITE_READY = "rewrite_ready", "待改写"
    REWRITTEN = "rewritten", "已改写"
    VALIDATED = "validated", "已校验"
    PUBLISH_READY = "publish_ready", "可自动发布"
    AUTO_PUBLISHED = "auto_published", "已自动发布"
    MANUAL_REVIEW_REQUIRED = "manual_review_required", "需人工审核"
    IGNORED = "ignored", "已忽略"
    FAILED = "failed", "自动化失败"


class ContentCategory(models.TextChoices):
    FLASH = "flash", "快讯"
    PRE_RACE = "pre_race", "赛前前瞻"
    POST_RACE = "post_race", "赛后结果/复盘"
    OFFICIAL = "official", "官方公告"
    INTERVIEW = "interview", "采访/人物"
    OTHER = "other", "其他"


class PublishedByMode(models.TextChoices):
    MANUAL = "manual", "人工"
    AUTO = "auto", "自动"


class AutomationPhase(models.TextChoices):
    SCORE = "score", "评分"
    REWRITE = "rewrite", "改写"
    VALIDATE = "validate", "校验"
    PUBLISH = "publish", "发布"
    NOTIFY = "notify", "通知"


class AutomationResult(models.TextChoices):
    SUCCESS = "success", "成功"
    FAILED = "failed", "失败"
    SKIPPED = "skipped", "跳过"


class NotificationType(models.TextChoices):
    CRAWL_FAILED = "crawl_failed", "来源抓取失败"
    TRANSLATION_FAILED = "translation_failed", "翻译失败"
    REWRITE_FAILED = "rewrite_failed", "改写失败"
    PUBLISH_FAILED = "publish_failed", "自动发布失败"
    STALE_SOURCE = "stale_source", "来源长时间无新稿"
    BACKLOG = "backlog", "候选稿异常堆积"
    NO_AUTO_PUBLISH_24H = "no_auto_publish_24h", "24 小时无自动发布"
    IMPORTANT_MANUAL = "important_manual", "重点新闻转人工"
    HIGH_VALUE_WARNING = "high_value_warning", "高价值新闻 warning"
    REPEATED_FAILURE = "repeated_failure", "关键任务连续失败"
    OPS_SUMMARY = "ops_summary", "运营摘要"
    OPS_ANOMALY = "ops_anomaly", "运营异常"


class NotificationChannel(models.TextChoices):
    EMAIL = "email", "邮件"
    SMS = "sms", "短信"
    QQ = "qq", "QQ"
    WECHAT = "wechat", "微信"


class NotificationStatus(models.TextChoices):
    QUEUED = "queued", "排队中"
    SENT = "sent", "已发送"
    FAILED = "failed", "失败"
    SKIPPED = "skipped", "跳过"


class PushStatus(models.TextChoices):
    QUEUED = "queued", "排队中"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失败"


class QQPushDeliveryStatus(models.TextChoices):
    PENDING = "pending", "待推送"
    RETRYING = "retrying", "等待重试"
    SENDING = "sending", "发送中"
    SENT = "sent", "已发送"
    FAILED = "failed", "失败"
    SKIPPED = "skipped", "已跳过"


class QQPushErrorType(models.TextChoices):
    URL_UNAVAILABLE = "url_unavailable", "公开 URL 不可访问"
    SEND_FAILED = "send_failed", "OneBot 发送失败"
    NOT_ELIGIBLE = "not_eligible", "不符合推送范围"
    NO_TARGETS = "no_targets", "无启用目标群"


class QQPushScope(models.TextChoices):
    INHERIT = "", "继承全局默认"
    ALL_PUBLIC = "all_public", "所有公开新闻"
    HIGH_VALUE_ONLY = "high_value_only", "仅重点新闻"


class QQPushImportanceStrategy(models.TextChoices):
    INHERIT = "", "继承全局默认"
    RANKED = "ranked", "榜单重点新闻"


class TaskStatus(models.TextChoices):
    STARTED = "started", "运行中"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失败"


class ProductionWindowKind(models.TextChoices):
    CRAWL = "crawl", "抓取"
    PUBLISH = "publish", "发布"
    QQ_PUSH = "qq_push", "QQ 推送"


class ProductionWindowMode(models.TextChoices):
    DAILY = "daily", "日常"
    MAJOR_RACE = "major_race", "重要赛事"


class ProductionWindowStatus(models.TextChoices):
    PENDING = "pending", "待执行"
    RUNNING = "running", "运行中"
    SUCCEEDED = "succeeded", "成功"
    PARTIAL = "partial", "部分完成"
    FAILED = "failed", "失败"
    SKIPPED = "skipped", "跳过"


class WindowDecisionStatus(models.TextChoices):
    SELECTED = "selected", "入选"
    SKIPPED = "skipped", "跳过"
    BLOCKED = "blocked", "阻断"
    FAILED = "failed", "失败"


class QuotaLedgerKind(models.TextChoices):
    WEB_PUBLISH = "web_publish", "网页发布"
    QQ_PUSH = "qq_push", "QQ 推送"


class QuotaLedgerScope(models.TextChoices):
    REGION_WINDOW = "region_window", "地区窗口"
    REGION_HOUR = "region_hour", "地区小时"
    GROUP_HOUR = "group_hour", "群小时"
    SITE_HOUR = "site_hour", "全站小时"


class ExternalDataSource(models.TextChoices):
    NETKEIBA = "netkeiba", "netkeiba"
    HKJC = "hkjc", "HKJC"
    SPORTING_LIFE = "sporting_life", "Sporting Life"
    FRANCE_GALOP = "france_galop", "France Galop"
    GENY_FRANCE = "geny_france", "Geny France"
    HORSE_RACING_NATION = "horse_racing_nation", "Horse Racing Nation"


class ExternalImportStatus(models.TextChoices):
    STARTED = "started", "运行中"
    SUCCESS = "success", "成功"
    FAILED = "failed", "失败"
    PARTIAL = "partial", "部分完成"
    PAUSED = "paused", "可继续"


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


class SourceErrorCategory(models.TextChoices):
    HTTP_403 = "http_403", "HTTP 403"
    HTTP_429 = "http_429", "HTTP 429"
    CAPTCHA_OR_BLOCKED = "captcha_or_blocked", "验证码或疑似封禁"
    TIMEOUT = "timeout", "超时"
    PARSE_ERROR = "parse_error", "解析失败"
    EMPTY_SUCCESS = "empty_success", "成功但无内容"
    SERVER_ERROR = "server_error", "服务端错误"
    UNKNOWN = "unknown", "未知"


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


class TermAliasType(models.TextChoices):
    PRIMARY = "primary", "主原文名"
    ALIAS = "alias", "原文别名"


class RaceGrade(models.TextChoices):
    G1 = "G1", "G1 / GI / GⅠ"
    G2 = "G2", "G2 / GII / GⅡ"
    G3 = "G3", "G3 / GIII / GⅢ"
    JPN1 = "JPN1", "Jpn1 / JpnⅠ"
    JPN2 = "JPN2", "Jpn2 / JpnⅡ"
    JPN3 = "JPN3", "Jpn3 / JpnⅢ"
    JG1 = "JG1", "J-G1 / J・GⅠ"
    JG2 = "JG2", "J-G2 / J・GⅡ"
    JG3 = "JG3", "J-G3 / J・GⅢ"
    LISTED = "L", "Listed / リステッド"
    OPEN = "OP", "Open / オープン"
    THREE_WIN = "3WIN", "3胜级"
    TWO_WIN = "2WIN", "2胜级"
    ONE_WIN = "1WIN", "1胜级"
    NEWCOMER = "NEWCOMER", "新马"
    MAIDEN = "MAIDEN", "未胜利"
    LOCAL_GRADE = "LOCAL_GRADE", "地方重赏"
    OTHER = "OTHER", "其他"


class TermCandidateStatus(models.TextChoices):
    PENDING = "pending", "待审核"
    ACCEPTED = "accepted", "已接受"
    REJECTED = "rejected", "已拒绝"
    IGNORED = "ignored", "已忽略"
    MERGED = "merged", "已合并"


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
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    source_kind = models.CharField(max_length=32, choices=SourceKind.choices, default=SourceKind.NEWS)
    adapter_key = models.CharField(max_length=64, blank=True)
    source_site = models.CharField(max_length=32, choices=SourceSite.choices, blank=True)
    source_mode = models.CharField(max_length=32, choices=SourceMode.choices, blank=True)
    enabled = models.BooleanField(default=True)
    crawl_interval_minutes = models.PositiveIntegerField(default=60)
    production_approved = models.BooleanField(default=False)
    effective_crawl_interval_minutes = models.PositiveIntegerField(null=True, blank=True)
    backoff_until = models.DateTimeField(null=True, blank=True)
    manual_pause_reason = models.TextField(blank=True)
    failure_streak = models.PositiveIntegerField(default=0)
    success_streak = models.PositiveIntegerField(default=0)
    last_error_category = models.CharField(max_length=32, choices=SourceErrorCategory.choices, blank=True)
    allow_event_boost = models.BooleanField(default=True)
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
        indexes = [
            models.Index(
                fields=("enabled", "production_approved", "racing_region"),
                name="source_prod_region_idx",
            ),
            models.Index(fields=("backoff_until",), name="source_backoff_idx"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class MajorRaceEvent(TimestampedModel):
    name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255)
    year = models.PositiveSmallIntegerField()
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices)
    race_grade = models.CharField(max_length=32, choices=RaceGrade.choices)
    external_id = models.CharField(max_length=128, blank=True)
    aliases = models.JSONField(default=list, blank=True)
    timezone_name = models.CharField(max_length=64)
    local_date = models.DateField()
    local_start_time = models.TimeField(null=True, blank=True)
    boost_start_at = models.DateTimeField(null=True, blank=True)
    boost_end_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("racing_region", "local_date", "local_start_time", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("normalized_name", "year", "racing_region", "race_grade"),
                name="uq_major_race_identity",
            )
        ]
        indexes = [
            models.Index(fields=("racing_region", "is_active", "local_date"), name="major_region_date_idx"),
            models.Index(fields=("boost_start_at", "boost_end_at"), name="major_boost_window_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.year} {self.racing_region}"


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
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
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
    ranked_revived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    crawl_status = models.CharField(max_length=16, choices=CrawlStatus.choices, default=CrawlStatus.SUCCESS)
    status = models.CharField(max_length=32, choices=ArticleStatus.choices, default=ArticleStatus.CRAWLED)
    workflow_status = models.CharField(
        max_length=32,
        choices=WorkflowStatus.choices,
        default=WorkflowStatus.PENDING_TRANSLATION,
    )
    review_mode = models.CharField(max_length=16, choices=ReviewMode.choices, blank=True)
    risk_level = models.CharField(max_length=16, choices=RiskLevel.choices, blank=True)
    automation_status = models.CharField(
        max_length=32,
        choices=AutomationStatus.choices,
        default=AutomationStatus.PENDING,
    )
    decision_reason = models.JSONField(default=dict, blank=True)
    decision_summary = models.TextField(blank=True)
    gate_issues = models.JSONField(default=list, blank=True)
    score_total = models.PositiveSmallIntegerField(default=0)
    quality_score = models.PositiveSmallIntegerField(default=0)
    rewrite_confidence = models.PositiveSmallIntegerField(default=0)
    base_translation_zh = models.TextField(blank=True)
    rewrite_title_zh = models.CharField(max_length=500, blank=True)
    rewrite_summary_zh = models.TextField(blank=True)
    rewrite_body_zh = models.TextField(blank=True)
    published_by_mode = models.CharField(max_length=16, choices=PublishedByMode.choices, blank=True)
    auto_publish_at = models.DateTimeField(null=True, blank=True)
    automation_error_message = models.TextField(blank=True)
    duplicate_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="duplicate_articles",
    )
    duplicate_score = models.FloatField(null=True, blank=True)
    duplicate_reason = models.TextField(blank=True)
    automation_warning_email_signature = models.CharField(max_length=64, blank=True)
    automation_warning_email_sent_at = models.DateTimeField(null=True, blank=True)
    content_category = models.CharField(max_length=32, choices=ContentCategory.choices, blank=True)
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
        indexes = [
            models.Index(fields=("racing_region", "workflow_status", "-first_seen_at"), name="news_region_workflow_idx"),
            models.Index(fields=("racing_region", "automation_status", "-auto_publish_at"), name="news_region_auto_idx"),
            models.Index(fields=("racing_region", "-published_to_web_at"), name="news_region_public_idx"),
            models.Index(fields=("racing_region", "translation_status"), name="news_region_trans_idx"),
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
        manual_fields = set(self.manually_edited_fields or [])
        if "title_zh" in manual_fields and self.title_zh:
            return self.title_zh
        return self.rewrite_title_zh or self.title_zh or self.translated_title_zh or self.title_ja

    @property
    def effective_body(self) -> str:
        manual_fields = set(self.manually_edited_fields or [])
        if "body_zh" in manual_fields and self.body_zh:
            return self.body_zh
        return self.rewrite_body_zh or self.body_zh or self.translated_body_zh or self.body_ja_normalized or self.body_ja_raw

    @property
    def effective_summary(self) -> str:
        manual_fields = set(self.manually_edited_fields or [])
        if "summary_zh" in manual_fields:
            return self.summary_zh or ""
        if self.rewrite_summary_zh:
            return self.rewrite_summary_zh
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
        if not self.pk:
            return ""
        return f"/news/{self.pk}/"

    def get_absolute_url(self) -> str:
        return self.public_path

    def _gate_issues_by_severity(self, severity: str) -> list[dict]:
        return [issue for issue in (self.gate_issues or []) if issue.get("severity") == severity]

    @property
    def gate_blockers(self) -> list[dict]:
        return self._gate_issues_by_severity("blocker")

    @property
    def gate_warnings(self) -> list[dict]:
        return self._gate_issues_by_severity("warning")

    @property
    def gate_infos(self) -> list[dict]:
        return self._gate_issues_by_severity("info")

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
        return extract_horse_tags(source_text, limit=12, source_language=self.source_language or SourceLanguage.JAPANESE)

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


class ExternalRace(TimestampedModel):
    source = models.CharField(max_length=32, choices=ExternalDataSource.choices, default=ExternalDataSource.NETKEIBA)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    race_id = models.CharField(max_length=32)
    race_name = models.CharField(max_length=255, blank=True)
    race_date = models.DateField(null=True, blank=True)
    course = models.CharField(max_length=128, blank=True)
    venue = models.CharField(max_length=128, blank=True)
    race_number = models.CharField(max_length=32, blank=True)
    race_grade = models.CharField(max_length=64, blank=True)
    race_class = models.CharField(max_length=128, blank=True)
    surface = models.CharField(max_length=64, blank=True)
    track = models.CharField(max_length=128, blank=True)
    distance = models.CharField(max_length=64, blank=True)
    weather = models.CharField(max_length=64, blank=True)
    going = models.CharField(max_length=128, blank=True)
    prize_money = models.CharField(max_length=128, blank=True)
    scheduled_start_at = models.DateTimeField(null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-race_date", "-race_id")
        constraints = [
            models.UniqueConstraint(fields=("source", "race_id"), name="uq_external_race_source_race"),
        ]
        indexes = [
            models.Index(fields=("source", "race_date"), name="ext_race_source_date_idx"),
            models.Index(fields=("source", "race_name"), name="ext_race_source_name_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.race_id} {self.race_name}".strip()


class ExternalRaceEntry(TimestampedModel):
    source = models.CharField(max_length=32, choices=ExternalDataSource.choices, default=ExternalDataSource.NETKEIBA)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    race = models.ForeignKey(ExternalRace, on_delete=models.CASCADE, related_name="entries")
    external_race_id = models.CharField(max_length=32)
    entry_key = models.CharField(max_length=128)
    horse_id = models.CharField(max_length=32, blank=True)
    horse_name = models.CharField(max_length=255, blank=True)
    normalized_horse_name = models.CharField(max_length=255, blank=True)
    horse_number = models.CharField(max_length=32, blank=True)
    frame_number = models.CharField(max_length=32, blank=True)
    barrier = models.CharField(max_length=32, blank=True)
    jockey_name = models.CharField(max_length=255, blank=True)
    trainer_name = models.CharField(max_length=255, blank=True)
    carried_weight = models.CharField(max_length=64, blank=True)
    equipment = models.CharField(max_length=255, blank=True)
    rating = models.CharField(max_length=64, blank=True)
    owner_name = models.CharField(max_length=255, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("external_race_id", "horse_number", "id")
        constraints = [
            models.UniqueConstraint(fields=("source", "external_race_id", "entry_key"), name="uq_ext_entry_source_race_key"),
        ]
        indexes = [
            models.Index(fields=("source", "horse_id"), name="ext_entry_source_horse_idx"),
            models.Index(fields=("source", "normalized_horse_name"), name="ext_entry_source_name_idx"),
        ]


class ExternalRaceResult(TimestampedModel):
    source = models.CharField(max_length=32, choices=ExternalDataSource.choices, default=ExternalDataSource.NETKEIBA)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    race = models.ForeignKey(ExternalRace, on_delete=models.CASCADE, related_name="results")
    external_race_id = models.CharField(max_length=32)
    result_key = models.CharField(max_length=128)
    horse_id = models.CharField(max_length=32, blank=True)
    horse_name = models.CharField(max_length=255, blank=True)
    normalized_horse_name = models.CharField(max_length=255, blank=True)
    horse_number = models.CharField(max_length=32, blank=True)
    finish_position = models.CharField(max_length=32, blank=True)
    finish_time = models.CharField(max_length=64, blank=True)
    margin = models.CharField(max_length=64, blank=True)
    odds_value = models.CharField(max_length=64, blank=True)
    running_position = models.CharField(max_length=255, blank=True)
    sectional_time = models.CharField(max_length=255, blank=True)
    barrier = models.CharField(max_length=32, blank=True)
    jockey_name = models.CharField(max_length=255, blank=True)
    trainer_name = models.CharField(max_length=255, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("external_race_id", "finish_position", "id")
        constraints = [
            models.UniqueConstraint(fields=("source", "external_race_id", "result_key"), name="uq_ext_result_source_race_key"),
        ]
        indexes = [
            models.Index(fields=("source", "horse_id"), name="ext_result_source_horse_idx"),
            models.Index(fields=("source", "normalized_horse_name"), name="ext_result_source_name_idx"),
        ]


class ExternalRaceOdds(TimestampedModel):
    source = models.CharField(max_length=32, choices=ExternalDataSource.choices, default=ExternalDataSource.NETKEIBA)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    race = models.ForeignKey(ExternalRace, on_delete=models.CASCADE, related_name="odds")
    external_race_id = models.CharField(max_length=32)
    odds_type = models.CharField(max_length=64, blank=True)
    odds_key = models.CharField(max_length=128)
    horse_number = models.CharField(max_length=32, blank=True)
    odds_value = models.CharField(max_length=64, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("external_race_id", "odds_type", "odds_key")
        constraints = [
            models.UniqueConstraint(fields=("source", "external_race_id", "odds_type", "odds_key"), name="uq_ext_odds_source_race_key"),
        ]
        indexes = [
            models.Index(fields=("source", "external_race_id"), name="ext_odds_source_race_idx"),
        ]


class ExternalHorse(TimestampedModel):
    source = models.CharField(max_length=32, choices=ExternalDataSource.choices, default=ExternalDataSource.NETKEIBA)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    horse_id = models.CharField(max_length=32)
    horse_name = models.CharField(max_length=255, blank=True)
    horse_name_en = models.CharField(max_length=255, blank=True)
    horse_name_zh_hant = models.CharField(max_length=255, blank=True)
    normalized_horse_name = models.CharField(max_length=255, blank=True)
    sex = models.CharField(max_length=64, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    country = models.CharField(max_length=128, blank=True)
    color = models.CharField(max_length=128, blank=True)
    father_name = models.CharField(max_length=255, blank=True)
    mother_name = models.CharField(max_length=255, blank=True)
    owner_name = models.CharField(max_length=255, blank=True)
    trainer_name = models.CharField(max_length=255, blank=True)
    record_summary = models.CharField(max_length=255, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("source", "horse_id")
        constraints = [
            models.UniqueConstraint(fields=("source", "horse_id"), name="uq_ext_horse_source_horse"),
        ]
        indexes = [
            models.Index(fields=("source", "normalized_horse_name"), name="ext_horse_source_name_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.horse_id} {self.horse_name}".strip()


class ExternalHorseHistory(TimestampedModel):
    source = models.CharField(max_length=32, choices=ExternalDataSource.choices, default=ExternalDataSource.NETKEIBA)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    horse = models.ForeignKey(ExternalHorse, on_delete=models.CASCADE, related_name="history")
    external_horse_id = models.CharField(max_length=32)
    external_race_id = models.CharField(max_length=32, blank=True)
    history_key = models.CharField(max_length=128)
    race_name = models.CharField(max_length=255, blank=True)
    raced_at = models.DateField(null=True, blank=True)
    horse_number = models.CharField(max_length=32, blank=True)
    finish_position = models.CharField(max_length=32, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-raced_at", "-external_race_id", "id")
        constraints = [
            models.UniqueConstraint(fields=("source", "external_horse_id", "history_key"), name="uq_ext_history_source_horse_key"),
        ]
        indexes = [
            models.Index(fields=("source", "external_race_id"), name="ext_history_source_race_idx"),
        ]


class ExternalHorseAlias(TimestampedModel):
    source = models.CharField(max_length=32, choices=ExternalDataSource.choices, default=ExternalDataSource.NETKEIBA)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    horse = models.ForeignKey(ExternalHorse, on_delete=models.CASCADE, related_name="aliases", null=True, blank=True)
    external_horse_id = models.CharField(max_length=32)
    name_ja = models.CharField(max_length=255)
    name_en = models.CharField(max_length=255, blank=True)
    name_zh_hant = models.CharField(max_length=255, blank=True)
    normalized_name = models.CharField(max_length=255)
    confidence = models.PositiveSmallIntegerField(default=100)
    alias_source = models.CharField(max_length=64, blank=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("source", "normalized_name")
        constraints = [
            models.UniqueConstraint(fields=("source", "external_horse_id", "normalized_name"), name="uq_ext_alias_source_horse_name"),
        ]
        indexes = [
            models.Index(fields=("source", "normalized_name"), name="ext_alias_source_name_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name_ja} ({self.external_horse_id})"


class ExternalDataImportRun(TimestampedModel):
    source = models.CharField(max_length=32, choices=ExternalDataSource.choices, default=ExternalDataSource.NETKEIBA)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    target_type = models.CharField(max_length=32)
    target_year = models.PositiveSmallIntegerField(null=True, blank=True)
    target_month = models.PositiveSmallIntegerField(null=True, blank=True)
    race_id = models.CharField(max_length=32, blank=True)
    horse_id = models.CharField(max_length=32, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=ExternalImportStatus.choices, default=ExternalImportStatus.STARTED)
    dry_run = models.BooleanField(default=False)
    current_target_type = models.CharField(max_length=32, blank=True)
    current_target_id = models.CharField(max_length=64, blank=True)
    success_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    coverage_stats = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at", "-id")
        indexes = [
            models.Index(fields=("source", "status", "-started_at"), name="ext_run_source_status_idx"),
            models.Index(fields=("target_type", "target_year", "target_month"), name="ext_run_target_month_idx"),
        ]


class ExternalDataImportError(TimestampedModel):
    run = models.ForeignKey(ExternalDataImportRun, on_delete=models.CASCADE, related_name="errors")
    source = models.CharField(max_length=32, choices=ExternalDataSource.choices, default=ExternalDataSource.NETKEIBA)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    target_type = models.CharField(max_length=32)
    target_id = models.CharField(max_length=128)
    error_type = models.CharField(max_length=128)
    message = models.TextField()
    retry_count = models.PositiveIntegerField(default=0)
    raw_payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-occurred_at", "-id")
        indexes = [
            models.Index(fields=("source", "target_type", "target_id"), name="ext_error_source_target_idx"),
        ]


class ExternalDataImportLock(TimestampedModel):
    source = models.CharField(max_length=32, choices=ExternalDataSource.choices, unique=True)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    locked_by_run = models.ForeignKey(
        ExternalDataImportRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="locks",
    )
    acquired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("source",)


class TermEntry(TimestampedModel):
    term_type = models.CharField(max_length=32, choices=TermType.choices, default=TermType.OTHER)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    racing_region = models.CharField(
        max_length=32,
        choices=[("", "全局通用"), *RacingRegion.choices],
        default="",
        blank=True,
    )
    source_ja = models.CharField(max_length=255)
    target_zh = models.CharField(max_length=255)
    aliases_ja = models.JSONField(default=list, blank=True)
    aliases_zh = models.JSONField(default=list, blank=True)
    race_grade = models.CharField(max_length=32, choices=RaceGrade.choices, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)

    class Meta:
        ordering = ("-priority", "source_ja")
        indexes = [
            models.Index(fields=("racing_region", "source_language", "term_type"), name="term_region_lang_type_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.source_ja} -> {self.target_zh}"

    def all_japanese_terms(self) -> list[str]:
        aliases = self.aliases_ja if isinstance(self.aliases_ja, list) else []
        return [self.source_ja, *aliases]

    def all_source_terms(self) -> list[str]:
        values = [*self.all_japanese_terms()]
        if self.pk:
            values.extend(
                self.source_aliases.filter(is_active=True)
                .order_by("source_language", "alias_type", "text")
                .values_list("text", flat=True)
            )
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = (value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def source_terms_for_language(self, source_language: str | None) -> list[str]:
        language = source_language or SourceLanguage.JAPANESE
        values: list[str] = []
        if language == self.source_language:
            values.extend(self.all_japanese_terms())
        if self.pk:
            values.extend(
                self.source_aliases.filter(source_language=language, is_active=True)
                .order_by("alias_type", "text")
                .values_list("text", flat=True)
            )
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = (value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result


class TermAlias(TimestampedModel):
    term = models.ForeignKey(TermEntry, on_delete=models.CASCADE, related_name="source_aliases")
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    text = models.CharField(max_length=255)
    alias_type = models.CharField(max_length=16, choices=TermAliasType.choices, default=TermAliasType.ALIAS)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("source_language", "alias_type", "text")
        constraints = [
            models.UniqueConstraint(
                fields=("term", "source_language", "text"),
                name="uq_term_alias_term_language_text",
            )
        ]
        indexes = [
            models.Index(fields=("source_language", "text"), name="idx_termalias_lang_text"),
        ]

    def __str__(self) -> str:
        return f"{self.text} ({self.source_language}) -> {self.term.target_zh}"


class TermCandidate(TimestampedModel):
    term_type = models.CharField(max_length=32, choices=TermType.choices)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, default=SourceLanguage.JAPANESE)
    source_ja = models.CharField(max_length=255)
    normalized_key = models.CharField(max_length=255)
    target_zh = models.CharField(max_length=255, blank=True)
    aliases_ja = models.JSONField(default=list, blank=True)
    aliases_zh = models.JSONField(default=list, blank=True)
    suggested_target_zh = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16,
        choices=TermCandidateStatus.choices,
        default=TermCandidateStatus.PENDING,
    )
    confidence = models.PositiveSmallIntegerField(default=0)
    occurrence_count = models.PositiveIntegerField(default=0)
    article_count = models.PositiveIntegerField(default=0)
    detection_reasons = models.JSONField(default=list, blank=True)
    conflicts = models.JSONField(default=list, blank=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_term_candidates",
    )
    accepted_term = models.ForeignKey(
        TermEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_candidates",
    )
    merged_into_candidate = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merged_candidates",
    )
    merged_into_term = models.ForeignKey(
        TermEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merged_candidates",
    )

    class Meta:
        ordering = ("-last_seen_at", "-confidence", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("term_type", "source_language", "normalized_key"),
                name="uq_term_candidate_type_normalized",
            )
        ]
        indexes = [
            models.Index(fields=("status", "term_type", "-last_seen_at"), name="termcand_status_type_idx"),
            models.Index(fields=("-confidence", "-last_seen_at"), name="termcand_conf_seen_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_term_type_display()}：{self.source_ja}"


class TermCandidateEvidence(TimestampedModel):
    candidate = models.ForeignKey(TermCandidate, on_delete=models.CASCADE, related_name="evidence")
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="term_candidate_evidence")
    source_fields = models.JSONField(default=list, blank=True)
    contexts = models.JSONField(default=list, blank=True)
    occurrence_count = models.PositiveIntegerField(default=0)
    confidence = models.PositiveSmallIntegerField(default=0)
    detectors = models.JSONField(default=list, blank=True)
    reasons = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("candidate", "article"),
                name="uq_term_candidate_evidence_article",
            )
        ]

    def __str__(self) -> str:
        return f"{self.candidate.source_ja} @ {self.article_id}"


class PushTarget(TimestampedModel):
    name = models.CharField(max_length=255)
    group_id = models.CharField(max_length=64, unique=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    allowed_regions = models.JSONField(default=list, blank=True)
    push_scope = models.CharField(max_length=32, choices=QQPushScope.choices, blank=True, default=QQPushScope.INHERIT)
    importance_strategy = models.CharField(
        max_length=32,
        choices=QQPushImportanceStrategy.choices,
        blank=True,
        default=QQPushImportanceStrategy.INHERIT,
    )

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


class QQPushDelivery(TimestampedModel):
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="qq_push_deliveries")
    target = models.ForeignKey(PushTarget, on_delete=models.CASCADE, related_name="qq_push_deliveries")
    status = models.CharField(
        max_length=16,
        choices=QQPushDeliveryStatus.choices,
        default=QQPushDeliveryStatus.PENDING,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    last_error_type = models.CharField(max_length=32, choices=QQPushErrorType.choices, blank=True)
    last_error = models.TextField(blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    message_id = models.CharField(max_length=128, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(fields=("article", "target"), name="uq_qq_push_delivery_article_target")
        ]
        indexes = [
            models.Index(fields=("status", "-updated_at"), name="qqpush_status_updated_idx"),
            models.Index(fields=("target", "status"), name="qqpush_target_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.article_id} -> {self.target_id} ({self.status})"


class ProductionWindow(TimestampedModel):
    kind = models.CharField(max_length=16, choices=ProductionWindowKind.choices)
    mode = models.CharField(max_length=16, choices=ProductionWindowMode.choices, default=ProductionWindowMode.DAILY)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, blank=True)
    source = models.ForeignKey(
        NewsSource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_windows",
    )
    target = models.ForeignKey(
        PushTarget,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_windows",
    )
    scope_key = models.CharField(max_length=255)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=ProductionWindowStatus.choices,
        default=ProductionWindowStatus.PENDING,
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    reason_summary = models.TextField(blank=True)
    result_payload = models.JSONField(default=dict, blank=True)
    rerun_count = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_production_windows",
    )

    class Meta:
        ordering = ("-window_start", "kind", "scope_key")
        constraints = [
            models.UniqueConstraint(
                fields=("kind", "scope_key", "window_start"),
                name="uq_prod_window_scope",
            )
        ]
        indexes = [
            models.Index(fields=("kind", "status", "window_start"), name="prodwin_status_idx"),
            models.Index(fields=("racing_region", "window_start"), name="prodwin_region_idx"),
            models.Index(fields=("lease_expires_at",), name="prodwin_lease_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.scope_key}@{self.window_start:%Y-%m-%d %H:%M}"


class WindowCandidateDecision(TimestampedModel):
    window = models.ForeignKey(ProductionWindow, on_delete=models.CASCADE, related_name="candidate_decisions")
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="window_candidate_decisions")
    status = models.CharField(max_length=16, choices=WindowDecisionStatus.choices)
    reason = models.CharField(max_length=128, blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    rank = models.PositiveSmallIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("window", "rank", "-score", "id")
        constraints = [
            models.UniqueConstraint(fields=("window", "article"), name="uq_window_candidate")
        ]
        indexes = [
            models.Index(fields=("window", "status"), name="cand_window_status_idx"),
            models.Index(fields=("article", "status"), name="cand_article_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.window_id}:{self.article_id}:{self.status}"


class WindowTargetDecision(TimestampedModel):
    window = models.ForeignKey(ProductionWindow, on_delete=models.CASCADE, related_name="target_decisions")
    article = models.ForeignKey(
        NewsArticle,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="window_target_decisions",
    )
    target = models.ForeignKey(PushTarget, on_delete=models.CASCADE, related_name="window_target_decisions")
    decision_key = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=WindowDecisionStatus.choices)
    reason = models.CharField(max_length=128, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("window", "target", "article_id")
        constraints = [
            models.UniqueConstraint(fields=("window", "decision_key"), name="uq_window_target_key")
        ]
        indexes = [
            models.Index(fields=("window", "status"), name="target_window_status_idx"),
            models.Index(fields=("target", "status"), name="target_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.window_id}:{self.decision_key}:{self.status}"


class QuotaLedger(TimestampedModel):
    kind = models.CharField(max_length=16, choices=QuotaLedgerKind.choices)
    scope = models.CharField(max_length=32, choices=QuotaLedgerScope.choices)
    scope_key = models.CharField(max_length=255)
    window_start = models.DateTimeField()
    limit = models.PositiveSmallIntegerField()
    used = models.PositiveSmallIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-window_start", "kind", "scope", "scope_key")
        constraints = [
            models.UniqueConstraint(
                fields=("kind", "scope", "scope_key", "window_start"),
                name="uq_quota_ledger_scope",
            )
        ]
        indexes = [
            models.Index(fields=("kind", "scope", "window_start"), name="quota_kind_scope_idx"),
            models.Index(fields=("scope_key", "window_start"), name="quota_scope_start_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.scope}:{self.scope_key}@{self.window_start:%Y-%m-%d %H:%M}"


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


class AutomationLog(TimestampedModel):
    article = models.ForeignKey(NewsArticle, on_delete=models.CASCADE, related_name="automation_logs")
    phase = models.CharField(max_length=16, choices=AutomationPhase.choices)
    result = models.CharField(max_length=16, choices=AutomationResult.choices)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    confidence = models.PositiveSmallIntegerField(null=True, blank=True)
    reason = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at", "-id")


class NotificationLog(TimestampedModel):
    type = models.CharField(max_length=32, choices=NotificationType.choices)
    channel = models.CharField(max_length=16, choices=NotificationChannel.choices)
    target = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=NotificationStatus.choices, default=NotificationStatus.QUEUED)
    payload_summary = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")


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

from __future__ import annotations

from typing import Iterable

from django.conf import settings
from django.core.exceptions import ValidationError
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
    NEWS = "news", "新闻"
    PREVIEW = "preview", "赛前展望"
    RESULT_BRIEF = "result_brief", "赛果简报"
    OFFICIAL_NOTICE = "official_notice", "官方通知"
    RACECARD_UPDATE = "racecard_update", "出赛/排位更新"
    TIPS = "tips", "赛前预测/投注倾向"
    FEATURE = "feature", "特写"
    SALES_BREEDING = "sales_breeding", "育马/拍卖/机构"
    FLASH = "flash", "快讯（旧）"
    PRE_RACE = "pre_race", "赛前前瞻（旧）"
    POST_RACE = "post_race", "赛后结果/复盘（旧）"
    OFFICIAL = "official", "官方公告（旧）"
    INTERVIEW = "interview", "采访/人物（旧）"
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


class TermGateReprocessStatus(models.TextChoices):
    PENDING = "pending", "待执行"
    RUNNING = "running", "执行中"
    SUCCEEDED = "succeeded", "已完成"
    FAILED = "failed", "失败"
    REJECTED = "rejected", "已拒绝"
    COMMITTED = "committed", "已提交"


class AttributionStatus(models.TextChoices):
    APPLIED = "applied", "已应用"
    FALLBACK = "fallback", "来源兜底"
    NEEDS_REVIEW = "needs_review", "待复核"
    LOCKED_SKIP = "locked_skip", "人工锁定跳过"


class MultiregionAttributionRunStatus(models.TextChoices):
    PENDING = "pending", "待执行"
    RUNNING = "running", "执行中"
    COMPLETED = "completed", "已完成"
    PARTIAL = "partial", "部分完成"
    FAILED = "failed", "失败"
    REJECTED = "rejected", "已拒绝"


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


class RaceEventSurface(models.TextChoices):
    TURF = "turf", "草地"
    DIRT = "dirt", "泥地"
    SYNTHETIC = "synthetic", "复合赛道"
    JUMPS = "jumps", "障碍"


class RaceEventPriority(models.TextChoices):
    P0 = "P0", "P0"
    P1 = "P1", "P1"
    P2 = "P2", "P2"


class RaceEventStatus(models.TextChoices):
    SCHEDULED = "scheduled", "赛前"
    RUNNING = "running", "进行中"
    FINISHED = "finished", "已结束"
    POSTPONED = "postponed", "延期"
    CANCELLED = "cancelled", "取消"


class RaceEventVisibility(models.TextChoices):
    DRAFT = "draft", "草稿"
    PUBLISHED = "published", "展示"
    HIDDEN = "hidden", "隐藏"


class RaceEventDataQuality(models.TextChoices):
    INCOMPLETE = "incomplete", "不完整"
    PARTIAL = "partial", "部分完整"
    COMPLETE = "complete", "完整"


class RaceSeriesStatus(models.TextChoices):
    ACTIVE = "active", "现行"
    DISCONTINUED = "discontinued", "已停办"
    UNKNOWN = "unknown", "待确认"


class RaceSeriesReviewStatus(models.TextChoices):
    PENDING = "pending", "待审核"
    APPROVED = "approved", "已批准"
    REJECTED = "rejected", "已驳回"


class RaceSeriesNameType(models.TextChoices):
    CANONICAL = "canonical", "正式名称"
    HISTORICAL = "historical", "历史名称"
    SPONSORED = "sponsored", "冠名名称"
    ALIAS = "alias", "别名"


class RaceSeriesRelationType(models.TextChoices):
    PREDECESSOR = "predecessor", "前身"
    SUCCESSOR = "successor", "后继"
    MERGED_INTO = "merged_into", "并入"
    SPLIT_INTO = "split_into", "拆分为"
    REPLACED_BY = "replaced_by", "被替代"


class HistoricalRaceExpectationStatus(models.TextChoices):
    HELD = "held", "应举办"
    CANCELLED = "cancelled", "已取消"
    NOT_DUE = "not_due", "尚未到期"
    NOT_HELD = "not_held", "该年未举办"


class HistoricalRaceResolutionStatus(models.TextChoices):
    PENDING = "pending", "待处理"
    READY = "ready", "可导入"
    SOURCE_UNAVAILABLE = "source_unavailable", "来源暂不可得"
    IDENTITY_REVIEW_REQUIRED = "identity_review_required", "系列身份待审"
    PERMANENTLY_UNAVAILABLE = "permanently_unavailable", "永久不可得"
    IMPORTED = "imported", "已导入"


class RaceEventModule(models.TextChoices):
    BASIC = "basic", "基础资料"
    HISTORY_WINNERS = "history_winners", "历史冠军"
    RUNNERS = "runners", "出马表/闸位"
    RESULTS = "results", "赛果"
    NEWS_LINKS = "news_links", "相关新闻"
    DYNAMIC_FIELDS = "dynamic_fields", "动态字段"


class RaceEventCandidateStatus(models.TextChoices):
    PENDING = "pending", "待确认"
    APPLIED = "applied", "已应用"
    IGNORED = "ignored", "已忽略"
    FAILED = "failed", "失败"


class RaceRunnerStatus(models.TextChoices):
    DECLARED = "declared", "已出走登记"
    RUNNING = "running", "进行中"
    SCRATCHED = "scratched", "退赛"
    WITHDRAWN = "withdrawn", "取消出走"
    UNKNOWN = "unknown", "未知"


class ArticleRaceLinkStatus(models.TextChoices):
    AUTO = "auto", "自动展示"
    CANDIDATE = "candidate", "候选"
    MANUAL = "manual", "人工确认"
    REMOVED = "removed", "人工移除"


class ArticleRaceLinkType(models.TextChoices):
    PRE_RACE = "pre_race", "赛前新闻"
    POST_RACE = "post_race", "赛后新闻"
    RELATED = "related", "相关新闻"


class HorseProfileStatus(models.TextChoices):
    DRAFT = "draft", "草稿"
    READY = "ready", "待发布"
    PUBLISHED = "published", "展示"
    HIDDEN = "hidden", "隐藏"


class HorseProfileCompleteness(models.TextChoices):
    EMPTY = "empty", "空壳"
    PROFILE_ONLY = "profile_only", "仅基础资料"
    PARTIAL_PEDIGREE = "partial_pedigree", "部分血统"
    COMPLETE_PEDIGREE_2GEN = "complete_pedigree_2gen", "完整二代血统"
    COMPLETE_PROFILE_FULL = "complete_profile_full", "完整马匹资料"


class HorseProfileModule(models.TextChoices):
    PROFILE = "profile", "基础资料"
    PEDIGREE = "pedigree", "血统"
    RACE_RECORD = "race_record", "参赛履历"
    MAJOR_WINS = "major_wins", "主胜鞍"
    ALIASES = "aliases", "别名"


class HorseProfileCandidateStatus(models.TextChoices):
    PENDING = "pending", "待确认"
    APPLIED = "applied", "已应用"
    IGNORED = "ignored", "已忽略"
    CONFLICT = "conflict", "冲突"
    FAILED = "failed", "失败"


class ArticleHorseLinkStatus(models.TextChoices):
    AUTO = "auto", "自动展示"
    CANDIDATE = "candidate", "候选"
    MANUAL = "manual", "人工确认"
    REMOVED = "removed", "人工移除"


class HorseRaceLinkType(models.TextChoices):
    MAJOR_WIN = "major_win", "主胜鞍赛事"
    RELATED = "related", "相关赛事"
    MANUAL = "manual", "人工相关"


class HorseRaceResultStatus(models.TextChoices):
    WON = "won", "胜出"
    PLACED = "placed", "上名"
    UNPLACED = "unplaced", "未上名"
    SCRATCHED = "scratched", "退赛"
    WITHDRAWN = "withdrawn", "取消出走"
    DID_NOT_FINISH = "did_not_finish", "未完赛"
    DISQUALIFIED = "disqualified", "失格"
    UNKNOWN = "unknown", "未知"


class TermTranslationStatus(models.TextChoices):
    PENDING = "pending", "中文名待补"
    TRANSLATED = "translated", "已有中文名"


class HorseRacingCareerStatus(models.TextChoices):
    ACTIVE = "active", "在役"
    RETIRED = "retired", "退役"
    UNKNOWN = "unknown", "未知"


class HorseP0SourceType(models.TextChoices):
    TERM_ACTIVE_WITH_ZH = "term_active_with_zh", "有中文名 active 术语"
    MAJOR_RACE_PARTICIPANT = "major_race_participant", "重点赛事参赛马"
    MANUAL = "manual", "人工标记"


class HorseP0SourceStatus(models.TextChoices):
    ACTIVE = "active", "有效"
    REVOKED = "revoked", "已撤销"


class HorseIdentityConflictStatus(models.TextChoices):
    PENDING = "pending", "待处理"
    RESOLVED = "resolved", "已解决"
    IGNORED = "ignored", "已忽略"


class HorseCompletionRunStatus(models.TextChoices):
    PLANNED = "planned", "已计划"
    RUNNING = "running", "运行中"
    DRY_RUN = "dry_run", "Dry-run 完成"
    COMMITTED = "committed", "已写入"
    FAILED = "failed", "失败"
    CANCELLED = "cancelled", "已取消"


class HorseCompletionFailureReason(models.TextChoices):
    NO_EXTERNAL_MATCH = "no_external_match", "无外部命中"
    AMBIGUOUS_MATCH = "ambiguous_match", "歧义命中"
    SOURCE_UNAVAILABLE = "source_unavailable", "来源不可用"
    RATE_LIMITED = "rate_limited", "来源限流"
    MISSING_PEDIGREE_FIELDS = "missing_pedigree_fields", "血统字段缺失"
    PROFILE_ONLY = "profile_only", "仅基础资料"
    MANUAL_LOCK_SKIPPED = "manual_lock_skipped", "人工锁定跳过"
    NOT_ATTEMPTED = "not_attempted", "未尝试"


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


class RaceSeries(TimestampedModel):
    key = models.SlugField(max_length=160, unique=True)
    country_region = models.CharField(max_length=32, choices=RacingRegion.choices)
    canonical_name_original = models.CharField(max_length=255)
    chinese_name = models.CharField(max_length=255, blank=True)
    founded_year = models.PositiveSmallIntegerField(null=True, blank=True)
    ended_year = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=RaceSeriesStatus.choices, default=RaceSeriesStatus.UNKNOWN)
    review_status = models.CharField(
        max_length=16,
        choices=RaceSeriesReviewStatus.choices,
        default=RaceSeriesReviewStatus.PENDING,
    )
    source_refs = models.JSONField(default=dict, blank=True)
    manual_lock_flags = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("country_region", "canonical_name_original", "key")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(founded_year__isnull=True)
                    | models.Q(ended_year__isnull=True)
                    | models.Q(founded_year__lte=models.F("ended_year"))
                ),
                name="race_series_valid_years",
            )
        ]
        indexes = [
            models.Index(fields=("country_region", "status"), name="race_series_region_status_idx"),
            models.Index(fields=("review_status", "country_region"), name="race_series_review_region_idx"),
        ]

    def clean(self):
        super().clean()
        if self.founded_year and self.ended_year and self.founded_year > self.ended_year:
            raise ValidationError({"ended_year": "终止年份不能早于创办年份。"})

    def __str__(self) -> str:
        return self.chinese_name or self.canonical_name_original


class RaceSeriesName(TimestampedModel):
    series = models.ForeignKey(RaceSeries, on_delete=models.CASCADE, related_name="names")
    text = models.CharField(max_length=255)
    normalized_text = models.CharField(max_length=255, db_index=True, blank=True)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, blank=True)
    name_type = models.CharField(
        max_length=16,
        choices=RaceSeriesNameType.choices,
        default=RaceSeriesNameType.ALIAS,
    )
    valid_from_year = models.PositiveSmallIntegerField(default=0)
    valid_to_year = models.PositiveSmallIntegerField(default=0)
    source_refs = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("series", "valid_from_year", "name_type", "text")
        constraints = [
            models.UniqueConstraint(
                fields=("series", "source_language", "normalized_text", "valid_from_year"),
                name="uq_series_name_lang_text_from",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(valid_from_year=0)
                    | models.Q(valid_to_year=0)
                    | models.Q(valid_from_year__lte=models.F("valid_to_year"))
                ),
                name="series_name_valid_years",
            ),
        ]

    def clean(self):
        super().clean()
        if self.valid_from_year and self.valid_to_year and self.valid_from_year > self.valid_to_year:
            raise ValidationError({"valid_to_year": "名称有效期终止年份不能早于起始年份。"})

    def save(self, *args, **kwargs):
        self.normalized_text = " ".join(self.text.casefold().split())
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"normalized_text"}
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.text} -> {self.series}"


class RaceSeriesRelation(TimestampedModel):
    from_series = models.ForeignKey(RaceSeries, on_delete=models.CASCADE, related_name="outgoing_relations")
    to_series = models.ForeignKey(RaceSeries, on_delete=models.CASCADE, related_name="incoming_relations")
    relation_type = models.CharField(max_length=16, choices=RaceSeriesRelationType.choices)
    effective_year = models.PositiveSmallIntegerField(null=True, blank=True)
    source_refs = models.JSONField(default=dict, blank=True)
    review_status = models.CharField(
        max_length=16,
        choices=RaceSeriesReviewStatus.choices,
        default=RaceSeriesReviewStatus.PENDING,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_race_series_relations",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("from_series", "effective_year", "relation_type", "to_series")
        constraints = [
            models.UniqueConstraint(
                fields=("from_series", "to_series", "relation_type"),
                name="uq_series_relation_direction_type",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_series=models.F("to_series")),
                name="series_relation_no_self",
            ),
        ]

    def clean(self):
        super().clean()
        if self.from_series_id and self.from_series_id == self.to_series_id:
            raise ValidationError({"to_series": "赛事系列不能与自身建立沿革关系。"})
        if self.review_status == RaceSeriesReviewStatus.APPROVED and not (self.approved_by_id and self.approved_at):
            raise ValidationError("批准系列关系时必须记录批准人和批准时间。")

    def __str__(self) -> str:
        return f"{self.from_series} {self.relation_type} {self.to_series}"


class RaceEvent(TimestampedModel):
    year = models.PositiveSmallIntegerField()
    slug = models.SlugField(max_length=160)
    series_key = models.SlugField(max_length=160, blank=True)
    original_name = models.CharField(max_length=255)
    chinese_name = models.CharField(max_length=255)
    country_region = models.CharField(max_length=32, choices=RacingRegion.choices)
    racecourse = models.CharField(max_length=255)
    grade_text = models.CharField(max_length=128)
    normalized_grade = models.CharField(max_length=32, choices=RaceGrade.choices, blank=True)
    surface = models.CharField(max_length=16, choices=RaceEventSurface.choices)
    distance_text = models.CharField(max_length=128, blank=True)
    eligibility_text = models.CharField(max_length=255, blank=True)
    race_datetime = models.DateTimeField(null=True, blank=True)
    timezone_name = models.CharField(max_length=64, default="Asia/Tokyo")
    local_date = models.DateField(null=True, blank=True)
    local_start_time = models.TimeField(null=True, blank=True)
    priority = models.CharField(max_length=2, choices=RaceEventPriority.choices, default=RaceEventPriority.P2)
    status = models.CharField(max_length=16, choices=RaceEventStatus.choices, default=RaceEventStatus.SCHEDULED)
    visibility_status = models.CharField(
        max_length=16,
        choices=RaceEventVisibility.choices,
        default=RaceEventVisibility.DRAFT,
    )
    data_quality_status = models.CharField(
        max_length=16,
        choices=RaceEventDataQuality.choices,
        default=RaceEventDataQuality.INCOMPLETE,
    )
    is_featured = models.BooleanField(default=False)
    result_confirmed_at = models.DateTimeField(null=True, blank=True)
    source_refs = models.JSONField(default=dict, blank=True)
    manual_lock_flags = models.JSONField(default=dict, blank=True)
    race_series = models.ForeignKey(
        RaceSeries,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="annual_events",
    )
    external_race = models.ForeignKey(
        "ExternalRace",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="race_events",
    )
    major_race_event = models.ForeignKey(
        MajorRaceEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="race_events",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("local_date", "local_start_time", "country_region", "chinese_name")
        constraints = [
            models.UniqueConstraint(fields=("year", "slug"), name="uq_race_event_year_slug"),
            models.UniqueConstraint(
                fields=("race_series", "year"),
                condition=models.Q(race_series__isnull=False),
                name="uq_race_event_series_year",
            ),
        ]
        indexes = [
            models.Index(fields=("visibility_status", "local_date"), name="race_event_visible_date_idx"),
            models.Index(fields=("visibility_status", "year"), name="race_event_visible_year_idx"),
            models.Index(
                fields=("visibility_status", "data_quality_status", "year", "slug"),
                name="race_event_sitemap_idx",
            ),
            models.Index(fields=("country_region", "local_date"), name="race_event_region_date_idx"),
            models.Index(fields=("priority", "visibility_status"), name="race_event_priority_idx"),
            models.Index(fields=("status", "visibility_status"), name="race_event_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.chinese_name or self.original_name} {self.year}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.original_name or self.chinese_name, allow_unicode=False) or f"race-{self.year}"
            self.slug = base[:160]
        if self.race_series_id:
            self.series_key = self.race_series.key
        elif not self.series_key:
            self.series_key = self.slug
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"slug", "series_key"}
        super().save(*args, **kwargs)

    @property
    def is_public(self) -> bool:
        return self.visibility_status == RaceEventVisibility.PUBLISHED

    @property
    def public_path(self) -> str:
        return f"/races/{self.year}/{self.slug}/"

    def get_absolute_url(self) -> str:
        return self.public_path

    @property
    def is_key_race(self) -> bool:
        return self.priority in {RaceEventPriority.P0, RaceEventPriority.P1} or self.is_featured


class HistoricalRaceEventTarget(TimestampedModel):
    race_series = models.ForeignKey(RaceSeries, on_delete=models.PROTECT, related_name="historical_targets")
    year = models.PositiveSmallIntegerField()
    country_region = models.CharField(max_length=32, choices=RacingRegion.choices)
    expectation_status = models.CharField(
        max_length=16,
        choices=HistoricalRaceExpectationStatus.choices,
        default=HistoricalRaceExpectationStatus.HELD,
    )
    resolution_status = models.CharField(
        max_length=32,
        choices=HistoricalRaceResolutionStatus.choices,
        default=HistoricalRaceResolutionStatus.PENDING,
    )
    original_name = models.CharField(max_length=255, blank=True)
    chinese_name = models.CharField(max_length=255, blank=True)
    grade_text = models.CharField(max_length=128, blank=True)
    normalized_grade = models.CharField(max_length=32, choices=RaceGrade.choices, blank=True)
    racecourse = models.CharField(max_length=255, blank=True)
    surface = models.CharField(max_length=16, choices=RaceEventSurface.choices, blank=True)
    distance_text = models.CharField(max_length=128, blank=True)
    local_date = models.DateField(null=True, blank=True)
    module_statuses = models.JSONField(default=dict, blank=True)
    field_provenance = models.JSONField(default=dict, blank=True)
    source_refs = models.JSONField(default=dict, blank=True)
    event = models.OneToOneField(
        RaceEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="historical_target",
    )
    last_checked_at = models.DateTimeField(null=True, blank=True)
    permanent_unavailable_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_permanent_race_gaps",
    )
    permanent_unavailable_approved_at = models.DateTimeField(null=True, blank=True)
    permanent_unavailable_evidence = models.JSONField(default=dict, blank=True)
    last_run_id = models.CharField(max_length=64, blank=True)
    artifact_sha256 = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("country_region", "year", "race_series")
        constraints = [
            models.UniqueConstraint(fields=("race_series", "year"), name="uq_historical_target_series_year"),
            models.CheckConstraint(
                condition=~models.Q(
                    expectation_status=HistoricalRaceExpectationStatus.NOT_HELD,
                    event__isnull=False,
                ),
                name="hist_target_not_held_no_event",
            ),
            models.CheckConstraint(
                condition=~models.Q(
                    expectation_status=HistoricalRaceExpectationStatus.NOT_DUE,
                    resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
                ),
                name="hist_target_not_due_unimported",
            ),
        ]
        indexes = [
            models.Index(
                fields=("country_region", "year", "expectation_status", "resolution_status"),
                name="hist_target_region_year_idx",
            ),
            models.Index(fields=("resolution_status", "last_checked_at"), name="hist_target_resolution_idx"),
        ]

    def clean(self):
        super().clean()
        if self.race_series_id and self.country_region != self.race_series.country_region:
            raise ValidationError({"country_region": "年度目标地区必须与赛事系列一致。"})
        if self.expectation_status == HistoricalRaceExpectationStatus.NOT_HELD and self.event_id:
            raise ValidationError({"event": "未举办年份不能关联虚构赛事。"})
        if self.expectation_status == HistoricalRaceExpectationStatus.NOT_DUE:
            if self.resolution_status == HistoricalRaceResolutionStatus.IMPORTED:
                raise ValidationError({"resolution_status": "尚未到期的年度目标不能标记为已导入。"})
        if self.resolution_status == HistoricalRaceResolutionStatus.IMPORTED and not self.event_id:
            raise ValidationError({"event": "标记已导入前必须关联正式赛事。"})
        if self.resolution_status == HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE:
            if not (
                self.permanent_unavailable_approved_by_id
                and self.permanent_unavailable_approved_at
                and self.permanent_unavailable_evidence
            ):
                raise ValidationError("永久不可得必须记录批准人、批准时间和双来源证据。")
        if self.event_id:
            if self.event.year != self.year:
                raise ValidationError({"event": "关联赛事年份必须与年度目标一致。"})
            if self.event.race_series_id != self.race_series_id:
                raise ValidationError({"event": "关联赛事必须属于同一赛事系列。"})

    def save(self, *args, **kwargs):
        if self.race_series_id:
            self.country_region = self.race_series.country_region
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"country_region"}
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.race_series} {self.year}"


class RaceEventAlias(TimestampedModel):
    event = models.ForeignKey(RaceEvent, on_delete=models.CASCADE, related_name="aliases")
    text = models.CharField(max_length=255)
    source_language = models.CharField(max_length=8, choices=SourceLanguage.choices, blank=True)
    alias_type = models.CharField(max_length=32, default="alias")
    source = models.CharField(max_length=128, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("event", "source_language", "alias_type", "text")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "source_language", "text"),
                name="uq_race_alias_event_lang_text",
            )
        ]
        indexes = [
            models.Index(fields=("source_language", "text"), name="race_alias_lang_text_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.text} -> {self.event}"


class RaceEventRunner(TimestampedModel):
    event = models.ForeignKey(RaceEvent, on_delete=models.CASCADE, related_name="runners")
    sort_order = models.PositiveSmallIntegerField(default=0)
    horse_number = models.CharField(max_length=32, blank=True)
    barrier = models.CharField(max_length=32, blank=True)
    horse_name = models.CharField(max_length=255)
    jockey_name = models.CharField(max_length=255, blank=True)
    trainer_name = models.CharField(max_length=255, blank=True)
    carried_weight = models.CharField(max_length=64, blank=True)
    odds_value = models.CharField(max_length=64, blank=True)
    popularity = models.CharField(max_length=64, blank=True)
    running_status = models.CharField(
        max_length=16,
        choices=RaceRunnerStatus.choices,
        default=RaceRunnerStatus.DECLARED,
    )
    dynamic_updated_at = models.DateTimeField(null=True, blank=True)
    manual_lock_flags = models.JSONField(default=dict, blank=True)
    source_refs = models.JSONField(default=dict, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("event", "sort_order", "horse_number", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "horse_number"),
                condition=~models.Q(horse_number=""),
                name="uq_race_runner_event_no",
            )
        ]
        indexes = [
            models.Index(fields=("event", "running_status"), name="race_runner_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event} #{self.horse_number} {self.horse_name}".strip()


class RaceEventResult(TimestampedModel):
    event = models.ForeignKey(RaceEvent, on_delete=models.CASCADE, related_name="results")
    finish_position = models.PositiveSmallIntegerField()
    official_finish_position = models.PositiveSmallIntegerField(null=True, blank=True)
    horse_number = models.CharField(max_length=32, blank=True)
    horse_name = models.CharField(max_length=255)
    jockey_name = models.CharField(max_length=255, blank=True)
    trainer_name = models.CharField(max_length=255, blank=True)
    finish_time = models.CharField(max_length=64, blank=True)
    margin = models.CharField(max_length=64, blank=True)
    odds_value = models.CharField(max_length=64, blank=True)
    popularity = models.CharField(max_length=64, blank=True)
    barrier = models.CharField(max_length=32, blank=True)
    carried_weight = models.CharField(max_length=64, blank=True)
    running_status = models.CharField(max_length=16, choices=RaceRunnerStatus.choices, blank=True)
    is_confirmed = models.BooleanField(default=True)
    source_refs = models.JSONField(default=dict, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("event", "finish_position", "id")
        constraints = [
            models.UniqueConstraint(fields=("event", "finish_position"), name="uq_race_result_event_pos"),
        ]
        indexes = [
            models.Index(
                fields=("official_finish_position", "event"),
                name="race_result_official_event_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event} {self.finish_position} {self.horse_name}"


class RaceEventHistoryWinner(TimestampedModel):
    event = models.ForeignKey(RaceEvent, on_delete=models.CASCADE, related_name="history_winners")
    winner_year = models.PositiveSmallIntegerField()
    horse_name = models.CharField(max_length=255)
    jockey_name = models.CharField(max_length=255, blank=True)
    trainer_name = models.CharField(max_length=255, blank=True)
    finish_time = models.CharField(max_length=64, blank=True)
    margin = models.CharField(max_length=64, blank=True)
    source_refs = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("event", "-winner_year")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "winner_year", "horse_name"),
                name="uq_race_history_event_year_horse",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.winner_year} {self.horse_name}"


class RaceEventDataCandidate(TimestampedModel):
    event = models.ForeignKey(RaceEvent, on_delete=models.CASCADE, related_name="data_candidates")
    module = models.CharField(max_length=32, choices=RaceEventModule.choices)
    source_name = models.CharField(max_length=128)
    source_url = models.URLField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=16,
        choices=RaceEventCandidateStatus.choices,
        default=RaceEventCandidateStatus.PENDING,
    )
    confidence = models.PositiveSmallIntegerField(default=0)
    candidate_payload = models.JSONField(default=dict, blank=True)
    diff_payload = models.JSONField(default=dict, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applied_race_event_candidates",
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ("-fetched_at", "-id")
        indexes = [
            models.Index(fields=("event", "module", "status"), name="race_candidate_module_idx"),
            models.Index(fields=("source_name", "fetched_at"), name="race_candidate_source_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event} {self.module} {self.source_name}"


class ArticleRaceLink(TimestampedModel):
    event = models.ForeignKey(RaceEvent, on_delete=models.CASCADE, related_name="article_links")
    article = models.ForeignKey("NewsArticle", on_delete=models.CASCADE, related_name="race_links")
    link_type = models.CharField(
        max_length=16,
        choices=ArticleRaceLinkType.choices,
        default=ArticleRaceLinkType.RELATED,
    )
    status = models.CharField(
        max_length=16,
        choices=ArticleRaceLinkStatus.choices,
        default=ArticleRaceLinkStatus.CANDIDATE,
    )
    source = models.CharField(max_length=64, blank=True)
    confidence = models.PositiveSmallIntegerField(default=0)
    matched_text = models.CharField(max_length=255, blank=True)
    match_reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_race_article_links",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="removed_race_article_links",
    )
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("event", "-confidence", "-created_at")
        constraints = [
            models.UniqueConstraint(fields=("event", "article"), name="uq_article_race_link"),
        ]
        indexes = [
            models.Index(fields=("event", "status", "link_type"), name="race_link_status_type_idx"),
            models.Index(fields=("article", "status"), name="race_link_article_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event} <-> {self.article_id} ({self.status})"

    @property
    def is_public(self) -> bool:
        return self.status in {ArticleRaceLinkStatus.AUTO, ArticleRaceLinkStatus.MANUAL}


class HorseProfile(TimestampedModel):
    primary_term = models.OneToOneField("TermEntry", on_delete=models.PROTECT, related_name="horse_profile")
    display_name_zh = models.CharField(max_length=255, blank=True)
    original_name = models.CharField(max_length=255, blank=True)
    english_name = models.CharField(max_length=255, blank=True)
    japanese_name = models.CharField(max_length=255, blank=True)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    country = models.CharField(max_length=128, blank=True)
    sex = models.CharField(max_length=64, blank=True)
    color = models.CharField(max_length=128, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    owner_name = models.CharField(max_length=255, blank=True)
    trainer_name = models.CharField(max_length=255, blank=True)
    breeder_name = models.CharField(max_length=255, blank=True)
    intro = models.TextField(blank=True)

    sire_text = models.CharField(max_length=255, blank=True)
    dam_text = models.CharField(max_length=255, blank=True)
    sire_sire_text = models.CharField(max_length=255, blank=True)
    sire_dam_text = models.CharField(max_length=255, blank=True)
    dam_sire_text = models.CharField(max_length=255, blank=True)
    dam_dam_text = models.CharField(max_length=255, blank=True)
    sire_term = models.ForeignKey("TermEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    dam_term = models.ForeignKey("TermEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    sire_sire_term = models.ForeignKey("TermEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    sire_dam_term = models.ForeignKey("TermEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    dam_sire_term = models.ForeignKey("TermEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    dam_dam_term = models.ForeignKey("TermEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    sire_horse_profile = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="sire_children")
    dam_horse_profile = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="dam_children")
    sire_sire_horse_profile = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    sire_dam_horse_profile = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    dam_sire_horse_profile = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    dam_dam_horse_profile = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    review_status = models.CharField(max_length=16, choices=HorseProfileStatus.choices, default=HorseProfileStatus.DRAFT)
    completeness_status = models.CharField(
        max_length=32,
        choices=HorseProfileCompleteness.choices,
        default=HorseProfileCompleteness.EMPTY,
    )
    racing_career_status = models.CharField(
        max_length=16,
        choices=HorseRacingCareerStatus.choices,
        default=HorseRacingCareerStatus.UNKNOWN,
    )
    records_synced_through = models.DateField(null=True, blank=True)
    full_profile_reviewed_at = models.DateTimeField(null=True, blank=True)
    full_profile_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_full_horse_profiles",
    )
    auto_update_enabled = models.BooleanField(default=False)
    auto_first_publish_enabled = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_horse_profiles",
    )
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hidden_horse_profiles",
    )
    review_notes = models.TextField(blank=True)
    manual_lock_flags = models.JSONField(default=dict, blank=True)
    source_refs = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("racing_region", "display_name_zh", "original_name", "id")
        indexes = [
            models.Index(fields=("review_status", "racing_region"), name="horse_status_region_idx"),
            models.Index(fields=("racing_region", "display_name_zh"), name="horse_region_name_idx"),
            models.Index(fields=("completeness_status", "review_status"), name="horse_complete_status_idx"),
            models.Index(fields=("is_featured", "review_status"), name="horse_featured_status_idx"),
            models.Index(fields=("racing_region", "records_synced_through"), name="horse_region_sync_idx"),
        ]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        return self.display_name_zh or self.primary_term.target_zh or self.original_name or self.english_name or self.japanese_name

    @property
    def is_public(self) -> bool:
        return self.review_status == HorseProfileStatus.PUBLISHED

    @property
    def public_path(self) -> str:
        if not self.pk:
            return ""
        return f"/horses/{self.pk}/"

    def get_absolute_url(self) -> str:
        return self.public_path


class HorseProfileCompletionRun(TimestampedModel):
    name = models.CharField(max_length=160, blank=True)
    status = models.CharField(
        max_length=16,
        choices=HorseCompletionRunStatus.choices,
        default=HorseCompletionRunStatus.PLANNED,
    )
    dry_run = models.BooleanField(default=True)
    regions = models.JSONField(default=list, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    artifact_path = models.CharField(max_length=1000, blank=True)
    source_names = models.JSONField(default=list, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    operated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="horse_profile_completion_runs",
    )

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("status", "created_at"), name="horse_run_status_idx"),
        ]

    def __str__(self) -> str:
        return self.name or f"P0 horse completion run #{self.pk}"


class HorseP0Source(TimestampedModel):
    profile = models.ForeignKey(HorseProfile, on_delete=models.CASCADE, related_name="p0_sources")
    term = models.ForeignKey("TermEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="p0_sources")
    race_event = models.ForeignKey(RaceEvent, on_delete=models.SET_NULL, null=True, blank=True, related_name="horse_p0_sources")
    race_result = models.ForeignKey(RaceEventResult, on_delete=models.SET_NULL, null=True, blank=True, related_name="horse_p0_sources")
    race_runner = models.ForeignKey(RaceEventRunner, on_delete=models.SET_NULL, null=True, blank=True, related_name="horse_p0_sources")
    completion_run = models.ForeignKey(
        HorseProfileCompletionRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="p0_sources",
    )
    source_type = models.CharField(max_length=32, choices=HorseP0SourceType.choices)
    status = models.CharField(max_length=16, choices=HorseP0SourceStatus.choices, default=HorseP0SourceStatus.ACTIVE)
    racing_region = models.CharField(max_length=32, choices=RacingRegion.choices, default=RacingRegion.JAPAN)
    race_grade = models.CharField(max_length=32, choices=RaceGrade.choices, blank=True)
    horse_name = models.CharField(max_length=255, blank=True)
    participant_key = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    evidence_summary = models.TextField(blank=True)
    evidence_payload = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    observed_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("profile", "source_type", "-observed_at", "-id")
        indexes = [
            models.Index(fields=("source_type", "status"), name="horse_p0_type_status_idx"),
            models.Index(fields=("racing_region", "status"), name="horse_p0_region_status_idx"),
            models.Index(fields=("race_event", "source_type"), name="horse_p0_event_type_idx"),
            models.Index(fields=("race_event", "participant_key"), name="horse_p0_participant_idx"),
            models.Index(fields=("completion_run", "status"), name="horse_p0_run_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "source_type", "term"),
                condition=models.Q(source_type=HorseP0SourceType.TERM_ACTIVE_WITH_ZH),
                name="uq_horse_p0_term_source",
            ),
            models.UniqueConstraint(
                fields=("profile", "source_type"),
                condition=models.Q(source_type=HorseP0SourceType.MANUAL),
                name="uq_horse_p0_manual_source",
            ),
            models.UniqueConstraint(
                fields=("source_type", "race_event", "participant_key"),
                condition=models.Q(
                    source_type=HorseP0SourceType.MAJOR_RACE_PARTICIPANT,
                    status=HorseP0SourceStatus.ACTIVE,
                ),
                name="uq_horse_p0_major_race_source",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.profile} {self.source_type}"


class HorseIdentityConflict(TimestampedModel):
    fingerprint = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=16,
        choices=HorseIdentityConflictStatus.choices,
        default=HorseIdentityConflictStatus.PENDING,
    )
    race_event = models.ForeignKey(
        RaceEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="horse_identity_conflicts",
    )
    horse_name = models.CharField(max_length=255)
    horse_number = models.CharField(max_length=32, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    identity_keys = models.JSONField(default=list, blank=True)
    sire_name = models.CharField(max_length=255, blank=True)
    dam_name = models.CharField(max_length=255, blank=True)
    birth_year = models.PositiveSmallIntegerField(null=True, blank=True)
    candidate_terms = models.ManyToManyField("TermEntry", blank=True, related_name="horse_identity_conflicts")
    candidate_profiles = models.ManyToManyField(HorseProfile, blank=True, related_name="identity_conflicts")
    resolved_profile = models.ForeignKey(
        HorseProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_identity_conflicts",
    )
    resolved_horse_number = models.CharField(max_length=32, blank=True)
    evidence_payload = models.JSONField(default=dict, blank=True)
    resolution_notes = models.TextField(blank=True)
    observed_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_horse_identity_conflicts",
    )

    class Meta:
        ordering = ("status", "-observed_at", "-id")
        indexes = [
            models.Index(fields=("status", "observed_at"), name="horse_identity_status_idx"),
            models.Index(fields=("race_event", "status"), name="horse_identity_event_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.horse_name} ({self.get_status_display()})"

    def clean(self):
        super().clean()
        if self.status == HorseIdentityConflictStatus.RESOLVED and not self.resolved_profile_id:
            raise ValidationError({"resolved_profile": "标记为已解决时必须选择最终马匹资料。"})
        pairing_conflict = (self.evidence_payload or {}).get("pairing_conflict") or {}
        candidate_numbers = {str(value) for value in pairing_conflict.get("horse_numbers") or []}
        if self.status == HorseIdentityConflictStatus.RESOLVED and pairing_conflict:
            if not self.resolved_horse_number:
                raise ValidationError({"resolved_horse_number": "马号冲突解决时必须选择最终马号。"})
            if self.resolved_horse_number not in candidate_numbers:
                raise ValidationError({"resolved_horse_number": "最终马号必须来自冲突证据中的候选马号。"})
            selected_member = next(
                (
                    member
                    for member in pairing_conflict.get("members") or []
                    if str(member.get("horse_number") or "") == self.resolved_horse_number
                ),
                None,
            )
            event_refs = self.race_event.source_refs if self.race_event_id else {}
            event_source_url = next(
                (
                    event_refs.get(key)
                    for key in ("official", "result", "runner", "source_url", "url")
                    if isinstance(event_refs, dict) and event_refs.get(key)
                ),
                "",
            )
            if not (selected_member and selected_member.get("source_url")) and not event_source_url:
                raise ValidationError(
                    {"resolved_horse_number": "所选马号及对应赛事缺少来源 URL，暂时不能标记为已解决。"}
                )


class HorseProfileDataCandidate(TimestampedModel):
    profile = models.ForeignKey(HorseProfile, on_delete=models.CASCADE, related_name="data_candidates")
    completion_run = models.ForeignKey(
        "HorseProfileCompletionRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="candidates",
    )
    module = models.CharField(max_length=32, choices=HorseProfileModule.choices)
    source_name = models.CharField(max_length=128)
    source_url = models.URLField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=16,
        choices=HorseProfileCandidateStatus.choices,
        default=HorseProfileCandidateStatus.PENDING,
    )
    confidence = models.PositiveSmallIntegerField(default=0)
    candidate_payload = models.JSONField(default=dict, blank=True)
    diff_payload = models.JSONField(default=dict, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applied_horse_profile_candidates",
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    result_summary = models.TextField(blank=True)

    class Meta:
        ordering = ("-fetched_at", "-id")
        indexes = [
            models.Index(fields=("profile", "module", "status"), name="horse_candidate_module_idx"),
            models.Index(fields=("source_name", "fetched_at"), name="horse_candidate_source_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.profile} {self.module} {self.source_name}"


class HorseRaceRecord(TimestampedModel):
    horse_profile = models.ForeignKey(HorseProfile, on_delete=models.CASCADE, related_name="race_records")
    completion_run = models.ForeignKey(
        "HorseProfileCompletionRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="race_records",
    )
    event = models.ForeignKey(RaceEvent, on_delete=models.SET_NULL, null=True, blank=True, related_name="horse_records")
    result = models.ForeignKey(RaceEventResult, on_delete=models.SET_NULL, null=True, blank=True, related_name="horse_records")
    race_name = models.CharField(max_length=255)
    race_year = models.PositiveSmallIntegerField(null=True, blank=True)
    race_date = models.DateField(null=True, blank=True)
    grade_text = models.CharField(max_length=128, blank=True)
    normalized_grade = models.CharField(max_length=32, choices=RaceGrade.choices, blank=True)
    racecourse = models.CharField(max_length=255, blank=True)
    distance_text = models.CharField(max_length=128, blank=True)
    surface = models.CharField(max_length=16, choices=RaceEventSurface.choices, blank=True)
    finish_position = models.CharField(max_length=32, blank=True)
    result_status = models.CharField(max_length=16, choices=HorseRaceResultStatus.choices, default=HorseRaceResultStatus.UNKNOWN)
    is_major_win = models.BooleanField(default=False)
    major_win_order = models.PositiveSmallIntegerField(default=0)
    source_name = models.CharField(max_length=128, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    idempotency_key = models.CharField(max_length=255, blank=True)
    source_refs = models.JSONField(default=dict, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("horse_profile", "-race_date", "-race_year", "major_win_order", "id")
        indexes = [
            models.Index(fields=("horse_profile", "result_status"), name="horse_record_result_idx"),
            models.Index(fields=("horse_profile", "is_major_win"), name="horse_record_major_idx"),
            models.Index(fields=("event", "result_status"), name="horse_record_event_idx"),
            models.Index(fields=("horse_profile", "idempotency_key"), name="horse_record_idem_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("horse_profile", "idempotency_key"),
                condition=~models.Q(idempotency_key=""),
                name="uq_horse_record_idempotency",
            )
        ]

    def __str__(self) -> str:
        return f"{self.horse_profile} {self.race_name}"


class HorseRaceLink(TimestampedModel):
    horse_profile = models.ForeignKey(HorseProfile, on_delete=models.CASCADE, related_name="race_links")
    event = models.ForeignKey(RaceEvent, on_delete=models.CASCADE, related_name="horse_links")
    link_type = models.CharField(max_length=16, choices=HorseRaceLinkType.choices, default=HorseRaceLinkType.RELATED)
    status = models.CharField(
        max_length=16,
        choices=ArticleHorseLinkStatus.choices,
        default=ArticleHorseLinkStatus.CANDIDATE,
    )
    source = models.CharField(max_length=64, blank=True)
    confidence = models.PositiveSmallIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_horse_race_links",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="removed_horse_race_links",
    )
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("horse_profile", "link_type", "-confidence", "-created_at")
        constraints = [
            models.UniqueConstraint(fields=("horse_profile", "event", "link_type"), name="uq_horse_race_link"),
        ]
        indexes = [
            models.Index(fields=("horse_profile", "status", "link_type"), name="horse_race_link_status_idx"),
            models.Index(fields=("event", "status"), name="horse_race_link_event_idx"),
        ]

    @property
    def is_public(self) -> bool:
        return self.status in {ArticleHorseLinkStatus.AUTO, ArticleHorseLinkStatus.MANUAL}


class ArticleHorseLink(TimestampedModel):
    horse_profile = models.ForeignKey(HorseProfile, on_delete=models.CASCADE, related_name="article_links")
    article = models.ForeignKey("NewsArticle", on_delete=models.CASCADE, related_name="horse_links")
    status = models.CharField(
        max_length=16,
        choices=ArticleHorseLinkStatus.choices,
        default=ArticleHorseLinkStatus.CANDIDATE,
    )
    source = models.CharField(max_length=64, blank=True)
    confidence = models.PositiveSmallIntegerField(default=0)
    matched_text = models.CharField(max_length=255, blank=True)
    match_reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_horse_article_links",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="removed_horse_article_links",
    )
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("horse_profile", "-confidence", "-created_at")
        constraints = [
            models.UniqueConstraint(fields=("horse_profile", "article"), name="uq_article_horse_link"),
        ]
        indexes = [
            models.Index(fields=("horse_profile", "status"), name="horse_link_status_idx"),
            models.Index(fields=("article", "status"), name="horse_link_article_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.horse_profile} <-> {self.article_id} ({self.status})"

    @property
    def is_public(self) -> bool:
        return self.status in {ArticleHorseLinkStatus.AUTO, ArticleHorseLinkStatus.MANUAL}


class HorseFollow(TimestampedModel):
    token_hash = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="horse_follows",
    )
    horse_profile = models.ForeignKey(HorseProfile, on_delete=models.CASCADE, related_name="follows")
    include_descendants = models.BooleanField(default=True)
    descendant_depth = models.PositiveSmallIntegerField(default=2)
    followed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-followed_at", "-id")
        constraints = [
            models.UniqueConstraint(fields=("token_hash", "horse_profile"), name="uq_horse_follow_token_profile"),
        ]
        indexes = [
            models.Index(fields=("horse_profile", "include_descendants"), name="horse_follow_desc_idx"),
            models.Index(fields=("user", "horse_profile"), name="horse_follow_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.token_hash[:8]} -> {self.horse_profile_id}"


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
    published_at_verified = models.BooleanField(null=True, blank=True, default=None)
    published_at_evidence = models.JSONField(default=dict, blank=True)
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
    content_category = models.CharField(
        max_length=32,
        choices=ContentCategory.choices,
        default=ContentCategory.NEWS,
        blank=True,
    )
    attribution_source = models.CharField(max_length=64, blank=True)
    attribution_summary = models.JSONField(default=dict, blank=True)
    attribution_locked = models.BooleanField(default=False)
    attribution_status = models.CharField(max_length=32, choices=AttributionStatus.choices, blank=True, db_index=True)
    attribution_confidence = models.PositiveSmallIntegerField(null=True, blank=True)
    attribution_rule_version = models.CharField(max_length=64, blank=True)
    editor_notes = models.TextField(blank=True)
    manually_edited_fields = models.JSONField(default=list, blank=True)
    translation_metadata = models.JSONField(default=dict, blank=True)
    translation_status = models.CharField(
        max_length=16,
        choices=ArticleTranslationStatus.choices,
        default=ArticleTranslationStatus.PENDING,
    )
    translation_error_message = models.TextField(blank=True)
    translation_error_category = models.CharField(max_length=64, blank=True)
    translation_started_at = models.DateTimeField(null=True, blank=True)
    translated_at = models.DateTimeField(null=True, blank=True)
    translation_model = models.CharField(max_length=128, blank=True)
    translation_provider = models.CharField(max_length=64, blank=True)
    translation_retry_count = models.PositiveIntegerField(default=0)
    translation_next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    translation_retry_exhausted_at = models.DateTimeField(null=True, blank=True)
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

    @property
    def region_display_text(self) -> str:
        from stable.services.news_attribution import (
            article_related_region_labels,
            related_region_queries_enabled,
        )

        primary = self.get_racing_region_display()
        related = article_related_region_labels(
            self,
            include_related=related_region_queries_enabled(),
        )
        if related:
            return f"{primary} · 相关：{' / '.join(related)}"
        return primary

    @property
    def related_region_display_text(self) -> str:
        from stable.services.news_attribution import (
            article_related_region_labels,
            related_region_queries_enabled,
        )

        return " / ".join(
            article_related_region_labels(
                self,
                include_related=related_region_queries_enabled(),
            )
        )

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


class NewsArticleRelatedRegion(TimestampedModel):
    article = models.ForeignKey(
        NewsArticle,
        on_delete=models.CASCADE,
        related_name="related_region_links",
    )
    region = models.CharField(max_length=32, choices=RacingRegion.choices)
    source = models.CharField(max_length=64, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    confidence = models.PositiveSmallIntegerField(default=0)
    is_manual = models.BooleanField(default=False)
    evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("region", "id")
        constraints = [
            models.UniqueConstraint(fields=("article", "region"), name="uq_article_related_region"),
        ]
        indexes = [
            models.Index(fields=("region", "article"), name="related_region_article_idx"),
            models.Index(fields=("article", "region"), name="article_related_region_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.article_id}:{self.region}"

    def clean(self):
        super().clean()
        if self.article_id and self.article.racing_region == self.region:
            raise ValidationError({"region": "关联地区不能与文章主地区相同。"})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


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
    target_zh = models.CharField(max_length=255, blank=True)
    translation_status = models.CharField(
        max_length=16,
        choices=TermTranslationStatus.choices,
        default=TermTranslationStatus.TRANSLATED,
    )
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
        return f"{self.source_ja} -> {self.target_zh or '中文名待补'}"

    @property
    def has_translation(self) -> bool:
        return bool((self.target_zh or "").strip()) and self.translation_status == TermTranslationStatus.TRANSLATED

    @property
    def is_pending_horse_translation(self) -> bool:
        return self.term_type == TermType.HORSE and not self.has_translation

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
    multiregion_test_enabled = models.BooleanField(default=False)
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


class TermGateReprocessRun(TimestampedModel):
    mode = models.CharField(max_length=16, choices=(("dry_run", "Dry run"), ("commit", "Commit")))
    selectors = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=TermGateReprocessStatus.choices,
        default=TermGateReprocessStatus.PENDING,
    )
    cursor = models.TextField(blank=True)
    rule_version = models.CharField(max_length=64, blank=True)
    settings_sha256 = models.CharField(max_length=64, blank=True)
    term_snapshot_sha256 = models.CharField(max_length=64, blank=True)
    candidate_payload = models.JSONField(default=list, blank=True)
    result_payload = models.JSONField(default=dict, blank=True)
    manifest_sha256 = models.CharField(max_length=64, blank=True)
    statistics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at", "-id")
        indexes = [
            models.Index(fields=("status", "-started_at"), name="termgate_run_status_idx"),
            models.Index(fields=("mode", "-started_at"), name="termgate_run_mode_idx"),
        ]


class TermGateReprocessLock(TimestampedModel):
    key = models.CharField(max_length=64, unique=True)
    locked_by_run = models.ForeignKey(
        TermGateReprocessRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leases",
    )
    owner_token = models.CharField(max_length=64, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("key",)


class MultiregionAttributionRun(TimestampedModel):
    mode = models.CharField(max_length=16, choices=(("dry_run", "Dry run"), ("commit", "Commit")))
    selectors = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=MultiregionAttributionRunStatus.choices,
        default=MultiregionAttributionRunStatus.PENDING,
    )
    cursor = models.PositiveIntegerField(default=0)
    completed_article_ids = models.JSONField(default=list, blank=True)
    rule_version = models.CharField(max_length=64, blank=True)
    term_version = models.CharField(max_length=64, blank=True)
    gold_version = models.CharField(max_length=64, blank=True)
    settings_sha256 = models.CharField(max_length=64, blank=True)
    term_snapshot_sha256 = models.CharField(max_length=64, blank=True)
    gold_snapshot_sha256 = models.CharField(max_length=64, blank=True)
    candidate_fingerprint = models.CharField(max_length=64, blank=True)
    candidate_payload = models.JSONField(default=list, blank=True)
    outcomes = models.JSONField(default=list, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    manifest_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at", "-id")
        indexes = [
            models.Index(fields=("status", "-started_at"), name="attr_run_status_idx"),
            models.Index(fields=("mode", "-started_at"), name="attr_run_mode_idx"),
        ]


class MultiregionAttributionLock(TimestampedModel):
    key = models.CharField(max_length=64, unique=True)
    locked_by_run = models.ForeignKey(
        MultiregionAttributionRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leases",
    )
    owner_token = models.CharField(max_length=64, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("key",)

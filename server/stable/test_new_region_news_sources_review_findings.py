from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest import mock

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable.adapters.base import (
    CanonicalNewsDraft,
    SourceArticleDetail,
    SourceArticleStub,
)
from stable.adapters.international import TDNAdapter
from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    NewsArticle,
    NewsSource,
    PushTarget,
    RacingRegion,
    SourceKind,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TranslationRun,
    TranslationStatus,
    WorkflowStatus,
)


FIXED_NOW = datetime(2026, 7, 19, 4, 0, tzinfo=dt_timezone.utc)


def _article(source_article_id: str, **overrides) -> NewsArticle:
    values = {
        "source_site": SourceSite.NETKEIBA,
        "source_mode": SourceMode.LATEST,
        "source_article_id": source_article_id,
        "source_url": f"https://fixture.example.test/news/{source_article_id}",
        "title_ja": f"Review finding {source_article_id}",
        "body_ja_raw": "Project-authored review fixture body.",
        "body_ja_normalized": "Project-authored review fixture body.",
        "published_at": timezone.now(),
        "racing_region": RacingRegion.JAPAN,
        "source_language": SourceLanguage.JAPANESE,
    }
    values.update(overrides)
    return NewsArticle.objects.create(**values)


@override_settings(SITE_INTERNAL_ONLY_ENABLED=False)
class SourceScopedPublicDistributionTests(TestCase):
    def test_internal_only_source_stays_out_of_public_surfaces_and_qq_when_site_mode_is_off(
        self,
    ):
        from stable.services.internal_controls import (
            external_news_distribution_blocker,
        )
        from stable.services.qq_auto_push import should_push_news_to_qq

        article = _article(
            "source-scope-public-block",
            source_site=SourceSite.RTE_RACING,
            source_mode=SourceMode.OFFICIAL,
            racing_region=RacingRegion.IRELAND,
            source_language=SourceLanguage.ENGLISH,
            title_zh="不得公开的来源级内部稿",
            summary_zh="不得公开的来源级内部摘要",
            body_zh="不得公开的来源级内部正文",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
            attribution_locked=True,
        )
        target = PushTarget.objects.create(
            name="来源级门禁测试群",
            group_id="source-scope-review-group",
            is_active=True,
            allowed_regions=[RacingRegion.IRELAND],
            push_scope="all_public",
        )

        feed = self.client.get(reverse("public-news-feed"))
        detail = self.client.get(
            reverse("public-article-detail", args=[article.id])
        )
        blocker_signature_supported = True
        try:
            blocker = external_news_distribution_blocker(article=article)
        except TypeError:
            blocker_signature_supported = False
            blocker = ""
        qq_decision = should_push_news_to_qq(
            article,
            scope="all_public",
            target=target,
        )

        observed = {
            "feed_contains_article": (
                "不得公开的来源级内部稿" in feed.content.decode("utf-8")
            ),
            "detail_status": detail.status_code,
            "shared_blocker_accepts_article": blocker_signature_supported,
            "shared_blocker_active": bool(blocker),
            "qq_allowed": qq_decision.allowed,
            "qq_uses_shared_blocker": bool(blocker)
            and qq_decision.reason == blocker,
        }
        self.assertEqual(
            observed,
            {
                "feed_contains_article": False,
                "detail_status": 404,
                "shared_blocker_accepts_article": True,
                "shared_blocker_active": True,
                "qq_allowed": False,
                "qq_uses_shared_blocker": True,
            },
            (
                "SITE_INTERNAL_ONLY_ENABLED=false 只关闭全站登录墙，不能提升 "
                "usage_scope=internal_only/public_publish_allowed=false 的来源级稿件；"
                "公开 queryset 与 QQ 必须复用文章级 blocker。"
            ),
        )


class InternalHTTPSStartupPreflightTests(SimpleTestCase):
    def _ready_outcome(self, settings_overrides: dict) -> str:
        with self.settings(
            SITE_INTERNAL_ONLY_ENABLED=True,
            MEDIA_STORAGE_BACKEND="local",
            DEBUG=False,
            **settings_overrides,
        ):
            try:
                apps.get_app_config("stable").ready()
            except ImproperlyConfigured:
                return "rejected"
        return "accepted"

    def test_production_internal_mode_requires_secure_cookies_and_an_explicit_tls_contract(
        self,
    ):
        cases = {
            "missing_tls_contract": {
                "SESSION_COOKIE_SECURE": True,
                "CSRF_COOKIE_SECURE": True,
                "SECURE_SSL_REDIRECT": False,
                "SECURE_PROXY_SSL_HEADER": None,
                "SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION": False,
            },
            "insecure_session_cookie": {
                "SESSION_COOKIE_SECURE": False,
                "CSRF_COOKIE_SECURE": True,
                "SECURE_SSL_REDIRECT": True,
                "SECURE_PROXY_SSL_HEADER": None,
                "SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION": False,
            },
            "insecure_csrf_cookie": {
                "SESSION_COOKIE_SECURE": True,
                "CSRF_COOKIE_SECURE": False,
                "SECURE_SSL_REDIRECT": True,
                "SECURE_PROXY_SSL_HEADER": None,
                "SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION": False,
            },
            "trusted_tls_without_proxy_header": {
                "SESSION_COOKIE_SECURE": True,
                "CSRF_COOKIE_SECURE": True,
                "SECURE_SSL_REDIRECT": False,
                "SECURE_PROXY_SSL_HEADER": None,
                "SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION": True,
            },
            "direct_https_redirect": {
                "SESSION_COOKIE_SECURE": True,
                "CSRF_COOKIE_SECURE": True,
                "SECURE_SSL_REDIRECT": True,
                "SECURE_PROXY_SSL_HEADER": None,
                "SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION": False,
            },
            "trusted_proxy_tls": {
                "SESSION_COOKIE_SECURE": True,
                "CSRF_COOKIE_SECURE": True,
                "SECURE_SSL_REDIRECT": False,
                "SECURE_PROXY_SSL_HEADER": (
                    "HTTP_X_FORWARDED_PROTO",
                    "https",
                ),
                "SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION": True,
            },
        }
        observed = {
            name: self._ready_outcome(case)
            for name, case in cases.items()
        }
        self.assertEqual(
            observed,
            {
                "missing_tls_contract": "rejected",
                "insecure_session_cookie": "rejected",
                "insecure_csrf_cookie": "rejected",
                "trusted_tls_without_proxy_header": "rejected",
                "direct_https_redirect": "accepted",
                "trusted_proxy_tls": "accepted",
            },
            (
                "DEBUG=false 的内部站点启动预检必须 fail closed：secure cookies "
                "为硬要求，传输层只能选择 direct HTTPS redirect 或显式获准且带 "
                "SECURE_PROXY_SSL_HEADER 的 trusted TLS termination。"
            ),
        )


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    NEWS_EXTERNAL_AI_PROCESSING_ENABLED=False,
    TRANSLATION_PROVIDER="siliconflow",
    TRANSLATION_AUTO_RETRY_ENABLED=True,
    TRANSLATION_AUTO_RETRY_BATCH_SIZE=10,
    AUTOMATION_ENABLED=False,
)
class TranslationRetryAIGateTests(TestCase):
    def test_ai_disabled_retry_skips_before_claim_and_releases_preclaimed_state(
        self,
    ):
        from stable.tasks import (
            translate_article_task,
            translation_retry_selector_task,
        )

        due_at = timezone.now() - timedelta(minutes=1)
        due = _article(
            "retry-selector-ai-disabled",
            workflow_status=WorkflowStatus.TRANSLATION_FAILED,
            automation_status=AutomationStatus.FAILED,
            translation_status=ArticleTranslationStatus.FAILED,
            translation_error_category="transient_provider_unavailable",
            translation_error_message="provider unavailable",
            translation_next_retry_at=due_at,
        )
        with mock.patch(
            "stable.services.translation.OpenAI"
        ) as remote_constructor:
            selector_result = translation_retry_selector_task.run()

        due.refresh_from_db()
        selector_state = {
            "dispatched_ids": selector_result["dispatched_ids"],
            "skipped_reason": selector_result["skipped_reason"],
            "article_status": due.translation_status,
            "due_at_preserved": due.translation_next_retry_at == due_at,
            "started_run_count": due.translation_runs.filter(
                status=TranslationStatus.STARTED
            ).count(),
        }

        claimed_at = timezone.now()
        preclaimed = _article(
            "preclaimed-retry-ai-disabled",
            workflow_status=WorkflowStatus.TRANSLATION_FAILED,
            automation_status=AutomationStatus.FAILED,
            translation_status=ArticleTranslationStatus.TRANSLATING,
            translation_started_at=claimed_at,
            translation_next_retry_at=None,
        )
        run = TranslationRun.objects.create(
            article=preclaimed,
            provider_name="siliconflow",
            model_name="fixture-model",
            status=TranslationStatus.STARTED,
        )
        with mock.patch(
            "stable.services.translation.OpenAI"
        ) as preclaimed_remote_constructor:
            preclaimed_result = translate_article_task.run(
                preclaimed.id,
                preclaimed_retry=True,
            )

        preclaimed.refresh_from_db()
        run.refresh_from_db()
        preclaimed_state = {
            "reason": preclaimed_result.get("reason"),
            "article_status": preclaimed.translation_status,
            "workflow_status": preclaimed.workflow_status,
            "translation_started_at_cleared": (
                preclaimed.translation_started_at is None
            ),
            "run_status": run.status,
            "started_run_count": preclaimed.translation_runs.filter(
                status=TranslationStatus.STARTED
            ).count(),
        }
        self.assertEqual(
            {
                "selector": selector_state,
                "preclaimed": preclaimed_state,
                "remote_constructor_called": remote_constructor.called,
                "preclaimed_remote_constructor_called": (
                    preclaimed_remote_constructor.called
                ),
            },
            {
                "selector": {
                    "dispatched_ids": [],
                    "skipped_reason": "external_translation_disabled",
                    "article_status": ArticleTranslationStatus.FAILED,
                    "due_at_preserved": True,
                    "started_run_count": 0,
                },
                "preclaimed": {
                    "reason": "external_translation_disabled",
                    "article_status": ArticleTranslationStatus.FAILED,
                    "workflow_status": WorkflowStatus.TRANSLATION_FAILED,
                    "translation_started_at_cleared": True,
                    "run_status": TranslationStatus.FAILED,
                    "started_run_count": 0,
                },
                "remote_constructor_called": False,
                "preclaimed_remote_constructor_called": False,
            },
            (
                "外部 AI 关闭时 selector 必须在 claim 前跳过；已 preclaim 的兼容调用"
                "必须释放文章和 TranslationRun，不能留下 TRANSLATING/STARTED。"
            ),
        )


class NotificationSanitizerReviewTests(SimpleTestCase):
    def test_sanitizer_keeps_safe_operational_counts_and_conflict_ids_only(
        self,
    ):
        from stable.services.internal_controls import (
            sanitize_internal_ops_notification,
        )

        forbidden_values = {
            "title": "FORBIDDEN-TITLE",
            "body": "FORBIDDEN-BODY",
            "translated_body_zh": "FORBIDDEN-TRANSLATION",
            "summary": "FORBIDDEN-SUMMARY",
            "source_url": "https://source.example.test/private",
        }
        expected = {
            "task": "regional_review_summary",
            "manual_review_count": 3,
            "publish_ready_count": 5,
            "failed_task_count": 2,
            "conflict_count": 2,
            "conflict_ids": [101, 102],
        }
        sanitized = sanitize_internal_ops_notification(
            {**expected, **forbidden_values}
        )
        serialized = json.dumps(sanitized, ensure_ascii=False, default=str)
        observed = {
            "payload": sanitized,
            "forbidden_values_present": sorted(
                value
                for value in forbidden_values.values()
                if value in serialized
            ),
        }
        self.assertEqual(
            observed,
            {
                "payload": expected,
                "forbidden_values_present": [],
            },
            (
                "内部通知 sanitizer 应保留安全运营计数和整数 conflict_ids，"
                "同时继续丢弃标题、正文、译文、摘要与 source_url。"
            ),
        )


@override_settings(
    NEWS_EXTERNAL_AI_PROCESSING_ENABLED=False,
    TRANSLATION_PROVIDER="siliconflow",
    AUTOMATION_ENABLED=False,
)
class BatchTranslationSkipAccountingTests(TestCase):
    def test_ai_gated_skip_is_not_counted_as_translated(self):
        from stable.tasks import batch_translate_articles_task

        article = _article(
            "batch-ai-gated-skip",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
            translation_status=ArticleTranslationStatus.PENDING,
        )
        with mock.patch(
            "stable.services.translation.OpenAI"
        ) as remote_constructor:
            result = batch_translate_articles_task.run(
                article_ids=[article.id],
                limit=10,
            )

        article.refresh_from_db()
        observed = {
            "processed": result["processed"],
            "translated_count": result["translated_count"],
            "failed_count": result["failed_count"],
            "article_status": article.translation_status,
            "remote_constructor_called": remote_constructor.called,
        }
        self.assertEqual(
            observed,
            {
                "processed": 1,
                "translated_count": 0,
                "failed_count": 0,
                "article_status": ArticleTranslationStatus.PENDING,
                "remote_constructor_called": False,
            },
            (
                "translate_article_task 返回 AI-gated skipped 时不能增加 "
                "translated_count；processed 可以计入，但 translated 必须保持 0。"
            ),
        )


class _TDNListingSkipAdapter(TDNAdapter):
    def fetch_listing(self, mode, page_or_month):
        del mode, page_or_month
        self.skipped_items = [
            (
                "https://www.thoroughbreddailynews.com/stale-review-fixture/: "
                "stale_published_at 2026-07-10T00:00:00+00:00"
            ),
            (
                "https://www.thoroughbreddailynews.com/missing-review-fixture/: "
                "missing_published_at"
            ),
        ]
        return []


class TDNListingSummaryReviewTests(TestCase):
    def test_tdn_listing_skip_reasons_restore_freshness_summary_counters(self):
        from stable.adapters.international import INTERNATIONAL_ADAPTERS
        from stable.tasks import _crawl_international_source_core

        source = NewsSource.objects.create(
            name="TDN listing summary review fixture",
            homepage_url="https://www.thoroughbreddailynews.com/",
            feed_url=(
                "https://www.thoroughbreddailynews.com/"
                "wp-json/wp/v2/posts?per_page=20"
            ),
            language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            source_kind=SourceKind.MEDIA,
            adapter_key="review_tdn_listing_summary",
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            enabled=True,
            production_approved=True,
        )
        with mock.patch.dict(
            INTERNATIONAL_ADAPTERS,
            {source.adapter_key: _TDNListingSkipAdapter},
        ), mock.patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("offline test attempted network access"),
        ):
            result = _crawl_international_source_core(
                source,
                crawled_at=FIXED_NOW,
                permission_preflight_enforced=False,
            )

        summary = result["source_summary"]
        self.assertEqual(
            {
                "skipped_count": result["skipped_count"],
                "historical_filtered": summary["historical_filtered"],
                "published_at_missing": summary["published_at_missing"],
            },
            {
                "skipped_count": 2,
                "historical_filtered": 1,
                "published_at_missing": 1,
            },
            (
                "TDN listing 已在 adapter 中分类的 stale_published_at 与 "
                "missing_published_at 不能只留在 skipped_items；crawl summary "
                "必须分别恢复计入 historical_filtered/published_at_missing。"
            ),
        )


class _ProbeCanonicalAdapter:
    source_site = SourceSite.RTE_RACING
    canonical_source_site = SourceSite.RTE_RACING
    source_mode = SourceMode.OFFICIAL
    racing_region = RacingRegion.IRELAND
    source_language = SourceLanguage.ENGLISH
    source_kind = SourceKind.MEDIA
    adapter_version = "review-probe-adapter-v1"
    parser_version = "review-probe-parser-v1"
    normalize_calls = 0
    last_listing_http_status = 200
    last_listing_final_url = (
        "https://www.rte.ie/feeds/rss/?index=/sport/racing/"
    )
    last_listing_query_errors: list[dict] = []

    def listing_url(self, page_or_month, mode=None):
        del page_or_month, mode
        return "https://www.rte.ie/feeds/rss/?index=/sport/racing/"

    def fetch_listing(self, mode, page_or_month):
        del page_or_month
        return [
            SourceArticleStub(
                source_site=self.source_site,
                source_mode=mode,
                source_article_id="review-probe-canonical",
                source_url=(
                    "https://www.rte.ie/sport/racing/2026/0719/"
                    "review-probe-canonical/"
                ),
                title_ja="Irish Derby canonical review fixture",
                published_at=FIXED_NOW,
                metadata={},
            )
        ]

    def fetch_detail(self, source_url):
        del source_url
        return SourceArticleDetail(
            title_ja="Irish Derby detail looks fresh",
            body_ja_raw=(
                "Irish Derby horse racing detail that looks acceptable before "
                "canonical normalization."
            ),
            body_ja_normalized=(
                "Irish Derby horse racing detail that looks acceptable before "
                "canonical normalization."
            ),
            published_at=FIXED_NOW,
            images=[],
            metadata={
                "published_at_verified": True,
                "published_at_evidence": {
                    "source": "detail",
                    "raw": FIXED_NOW.isoformat(),
                    "timezone": "Europe/Dublin",
                    "precision": "minute",
                    "parser_version": self.parser_version,
                    "verified": True,
                },
            },
        )

    def normalize_source_payload(self, stub, detail):
        type(self).normalize_calls += 1
        historical_at = FIXED_NOW - timedelta(days=7)
        return CanonicalNewsDraft(
            source_site=self.source_site,
            canonical_source_site=self.canonical_source_site,
            source_mode=stub.source_mode,
            source_article_id=stub.source_article_id,
            source_url=stub.source_url,
            title_ja="Irish Derby canonical historical fixture",
            body_ja_raw=detail.body_ja_raw,
            body_ja_normalized=detail.body_ja_normalized,
            published_at=historical_at,
            images=[],
            racing_region=RacingRegion.IRELAND,
            source_language=SourceLanguage.ENGLISH,
            source_kind=SourceKind.MEDIA,
            metadata={
                "published_at_verified": True,
                "published_at_evidence": {
                    "source": "canonical",
                    "raw": historical_at.date().isoformat(),
                    "timezone": "Europe/Dublin",
                    "precision": "date",
                    "parser_version": self.parser_version,
                    "verified": True,
                },
            },
        )


class _ProbeCanonicalTopicRejectAdapter(_ProbeCanonicalAdapter):
    normalize_calls = 0

    def normalize_source_payload(self, stub, detail):
        del stub, detail
        type(self).normalize_calls += 1
        raise ValueError("non_horse_racing_topic")


class ProbeCanonicalNormalizationReviewTests(TestCase):
    def _run_probe(self, adapter_class) -> dict:
        from stable.management.commands import (
            probe_international_news_sources as probe_command,
        )

        permission = SimpleNamespace(
            canonical_source_site=SourceSite.RTE_RACING,
            status="approved",
            reason="internal_only_technical_access",
            allowed=True,
            request_budget=None,
            record=SimpleNamespace(
                technical_access="accepted",
                usage_scope="internal_only",
                public_publish_allowed=False,
                terms_risk="review fixture",
            ),
        )
        stdout = io.StringIO()
        with mock.patch.dict(
            probe_command.INTERNATIONAL_ADAPTERS,
            {"rte_racing": adapter_class},
        ), mock.patch.object(
            probe_command,
            "preflight_source_access",
            return_value=permission,
        ), mock.patch.object(
            probe_command.timezone,
            "now",
            return_value=FIXED_NOW,
        ), mock.patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("offline probe attempted network access"),
        ):
            call_command(
                "probe_international_news_sources",
                source=["rte_racing"],
                limit=1,
                json=True,
                stdout=stdout,
            )
        return json.loads(stdout.getvalue())[0]

    def test_probe_normalizes_before_acceptance_and_uses_canonical_rejections(
        self,
    ):
        _ProbeCanonicalAdapter.normalize_calls = 0
        stale = self._run_probe(_ProbeCanonicalAdapter)
        _ProbeCanonicalTopicRejectAdapter.normalize_calls = 0
        topic = self._run_probe(_ProbeCanonicalTopicRejectAdapter)
        topic_diagnostics = json.dumps(
            {
                "error": topic.get("error"),
                "deferred_reason": topic.get("deferred_reason"),
                "sample_errors": topic.get("sample_errors"),
            },
            ensure_ascii=False,
        )

        observed = {
            "stale_normalize_calls": (
                _ProbeCanonicalAdapter.normalize_calls
            ),
            "stale_rejected": stale["status"] != "accepted",
            "topic_normalize_calls": (
                _ProbeCanonicalTopicRejectAdapter.normalize_calls
            ),
            "topic_rejected": topic["status"] != "accepted",
            "topic_reason_retained": (
                "non_horse_racing_topic" in topic_diagnostics
            ),
        }
        self.assertEqual(
            observed,
            {
                "stale_normalize_calls": 1,
                "stale_rejected": True,
                "topic_normalize_calls": 1,
                "topic_rejected": True,
                "topic_reason_retained": True,
            },
            (
                "probe 必须在 accept/reject 前调用正式 normalize_source_payload()；"
                "时间与主题门禁只能读取 canonical draft，拒绝结论及原因须与 ingestion "
                "保持一致。测试 adapter 与 HTTP 均为离线 mock。"
            ),
        )

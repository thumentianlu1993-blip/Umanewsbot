from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import json
from pathlib import Path
import tempfile
from io import StringIO
import uuid
from unittest.mock import Mock, call, patch
from zoneinfo import ZoneInfo

import requests
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from stable.adapters.jra import JRAAdapter
from stable.adapters.base import CanonicalNewsDraft
from stable.adapters.base import SourceArticleDetail, SourceArticleStub
from stable.adapters.international import (
    AtTheRacesFranceAdapter,
    BloodHorseAdapter,
    BHAAdapter,
    FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS,
    FIRST_VERSION_INTERNATIONAL_PROBES,
    FranceGalopEnglishNewsAdapter,
    HorseRacingNationAdapter,
    HKJCRacingNewsAdapter,
    PaulickReportAdapter,
    SCMPRacingAdapter,
    SkySportsRacingAdapter,
    SponichiAdapter,
    SportingLifeAdapter,
    TDNAdapter,
    TDNFranceBroadKeywordAdapter,
    TDNFranceKeywordAdapter,
)
from stable.adapters.netkeiba import NetkeibaAdapter
from stable.forms import ArticleEditorForm
from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    ContentCategory,
    ExternalDataSource,
    ExternalDataImportLock,
    ExternalDataImportRun,
    ExternalHorse,
    ExternalHorseAlias,
    ExternalImportStatus,
    ExternalRace,
    ExternalRaceEntry,
    ExternalRaceOdds,
    ExternalRaceResult,
    CrawlJob,
    ArticleHorseLink,
    ArticleHorseLinkStatus,
    HorseFollow,
    HorseIdentityConflict,
    HorseIdentityConflictStatus,
    HorseProfile,
    HorseProfileCandidateStatus,
    HorseProfileCompleteness,
    HorseProfileDataCandidate,
    HorseProfileModule,
    HorseProfileStatus,
    HorseRaceRecord,
    HorseRaceResultStatus,
    NewsImage,
    NewsArticle,
    NewsArticleRelatedRegion,
    NewsSnapshot,
    NewsSource,
    NotificationLog,
    OperationLog,
    MajorRaceEvent,
    PublishedByMode,
    ProductionWindow,
    ProductionWindowKind,
    ProductionWindowMode,
    ProductionWindowStatus,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    QQPushErrorType,
    QuotaLedger,
    QuotaLedgerKind,
    QuotaLedgerScope,
    RaceGrade,
    RaceEvent,
    RaceEventAlias,
    RaceEventDataCandidate,
    RaceEventHistoryWinner,
    RaceEventModule,
    RaceEventPriority,
    RaceEventResult,
    RaceEventRunner,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceRunnerStatus,
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    ArticleRaceLinkType,
    RacingRegion,
    ReviewMode,
    SourceErrorCategory,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TermAlias,
    TermAliasType,
    TermCandidate,
    TermCandidateEvidence,
    TermCandidateStatus,
    TermEntry,
    TermType,
    TaskExecutionLog,
    TaskStatus,
    WindowCandidateDecision,
    WindowDecisionStatus,
    WindowTargetDecision,
    WorkflowStatus,
)
from stable.services.onebot import BotPusher, OneBotRequestError
from stable.services.qq_auto_push import (
    build_qq_auto_push_message,
    ensure_qq_push_deliveries,
    qq_push_next_attempt_delay,
    should_push_news_to_qq,
    target_allowed_regions,
)
from stable.services.pushing import build_push_message, push_article_to_targets
from stable.services.automation import score_article_for_automation
from stable.services.notifications import send_high_value_warning_notification
from stable.services.rewriting import OpenAICompatibleRewriteProvider, _loads_rewrite_payload
from stable.services.race_events import (
    apply_data_candidate,
    associate_articles_for_event,
    remove_article_link,
    update_runner_dynamic_fields,
)
from stable.services.sources import BUILTIN_SOURCE_DEFINITIONS, sync_builtin_sources
from stable.services.ingestion import ArticleUpsertResult, upsert_article_from_draft
from stable.services.news_attribution import apply_article_attribution, article_region_set, filter_articles_visible_in_region
from stable.services.term_admin import commit_term_import, preview_term_import
from stable.services.term_candidate_review import accept_candidate, merge_candidate, set_candidate_status
from stable.services.term_discovery import (
    TermDiscoveryFinding,
    aggregate_finding,
    discover_and_aggregate_article,
    discover_term_findings,
    match_formal_terms,
    normalize_japanese_term,
)
from stable.services.terms import (
    apply_created_term_to_article,
    apply_term_mappings,
    extract_horse_tags,
    extract_unknown_horse_names,
    recognize_horse_names,
    resolve_terms,
    resolve_terms_for_language,
)
from stable.services.text import extract_article_text
from stable.services.translation import (
    OpenAICompatibleTranslationProvider,
    TranslationResponseError,
    translate_article as run_translation_service,
)
from stable.services.validation import apply_validation_outcome, validate_rewrite
from stable.services.external_horse_data import (
    ExternalHorseDataAlreadyRunning,
    ExternalHorseDataImporter,
    ExternalHorseDataNetworkDisabled,
    ImportOptions,
)
from stable.services.horse_profile_completion import CompletionOptions, apply_completion_artifact, plan_profile_completion
from stable.services.horse_profiles import (
    FOLLOW_COOKIE_NAME,
    apply_data_candidate as apply_horse_data_candidate,
    follow_horse,
    followed_articles,
    generate_p0_horse_profiles,
    get_descendant_horse_ids,
    major_win_records,
    scan_article_horse_links,
    signed_follow_token,
    token_hash_from_cookie,
    update_completeness,
)
from stable.services.external_hkjc_data import HKJCExternalDataImporter, HKJCImportError, HKJCImportOptions
from stable.tasks import (
    _crawl_jra_source,
    _crawl_international_source,
    _crawl_netkeiba_mode,
    _resolve_auto_publish_batch_limit,
    auto_publish_batch_task,
    batch_translate_articles_task,
    discover_term_candidates_task,
    process_article_automation_task,
    qq_auto_push_article_task,
    qq_push_delivery_task,
    scan_article_horse_links_task,
    score_article_task,
    send_notification_task,
    translate_article_task,
)


User = get_user_model()


class MultiRegionAttributionAndGateTests(TestCase):
    def _article(self, **overrides):
        payload = {
            "source_site": SourceSite.TDN_FRANCE,
            "source_mode": SourceMode.LATEST,
            "source_article_id": overrides.pop("source_article_id", f"multi-{NewsArticle.objects.count()}"),
            "racing_region": RacingRegion.FRANCE,
            "source_language": SourceLanguage.ENGLISH,
            "title_ja": "Ascot Gold Cup preview for Desert Crown",
            "body_ja_raw": "Ascot Gold Cup preview for Desert Crown. " * 8,
            "body_ja_normalized": "Ascot Gold Cup preview for Desert Crown. " * 8,
            "translated_title_zh": "沙漠皇冠出战雅士谷金杯",
            "translated_summary_zh": "沙漠皇冠将出战英国赛事。",
            "translated_body_zh": "沙漠皇冠将出战雅士谷金杯。" * 12,
            "title_zh": "沙漠皇冠出战雅士谷金杯",
            "summary_zh": "沙漠皇冠将出战英国赛事。",
            "body_zh": "沙漠皇冠将出战雅士谷金杯。" * 12,
            "published_at": timezone.now(),
            "source_url": overrides.pop("source_url", f"https://example.com/multi-{NewsArticle.objects.count()}"),
            "translation_status": ArticleTranslationStatus.TRANSLATED,
            "automation_status": AutomationStatus.PUBLISH_READY,
            "workflow_status": WorkflowStatus.PENDING_REVIEW,
            "review_mode": ReviewMode.AUTO,
            "score_total": 90,
            "quality_score": 90,
        }
        payload.update(overrides)
        return NewsArticle.objects.create(**payload)

    @override_settings(MULTIREGION_ATTRIBUTION_ENABLED=False)
    @patch("stable.services.news_attribution.infer_article_attribution")
    def test_disabled_attribution_does_not_scan_terms_or_change_regions(self, infer_mock):
        article = self._article(racing_region=RacingRegion.FRANCE)
        NewsArticleRelatedRegion.objects.create(
            article=article,
            region=RacingRegion.UNITED_KINGDOM,
            source="existing",
        )

        result = apply_article_attribution(article)
        article.refresh_from_db()

        infer_mock.assert_not_called()
        self.assertEqual(result.reason, "attribution_disabled")
        self.assertEqual(result.primary_region, RacingRegion.FRANCE)
        self.assertEqual(result.related_regions, [RacingRegion.UNITED_KINGDOM])
        self.assertEqual(article.racing_region, RacingRegion.FRANCE)

    @patch("stable.services.news_attribution.infer_article_attribution")
    def test_locked_attribution_does_not_scan_terms_without_force(self, infer_mock):
        article = self._article(
            racing_region=RacingRegion.FRANCE,
            attribution_locked=True,
        )

        result = apply_article_attribution(article)

        infer_mock.assert_not_called()
        self.assertEqual(result.reason, "attribution_locked")
        self.assertEqual(result.primary_region, RacingRegion.FRANCE)

    def test_attribution_promotes_event_region_and_keeps_france_related(self):
        article = self._article()

        result = apply_article_attribution(article, force=True)
        article.refresh_from_db()

        self.assertEqual(result.primary_region, RacingRegion.UNITED_KINGDOM)
        self.assertEqual(article.racing_region, RacingRegion.UNITED_KINGDOM)
        self.assertEqual(article.content_category, ContentCategory.PREVIEW)
        self.assertEqual(article_region_set(article), {RacingRegion.UNITED_KINGDOM})

    def test_event_location_outranks_country_context(self):
        article = self._article(
            title_ja="Japanese star runs at Ascot",
            body_ja_raw="A Japanese star runs at Ascot in the feature race. " * 8,
            body_ja_normalized="A Japanese star runs at Ascot in the feature race. " * 8,
        )

        result = apply_article_attribution(article, force=True)
        article.refresh_from_db()

        self.assertEqual(result.primary_region, RacingRegion.UNITED_KINGDOM)
        self.assertEqual(
            article_region_set(article),
            {RacingRegion.UNITED_KINGDOM},
        )
        self.assertEqual(article.attribution_summary["evidence"]["event_keyword_matches"], {
            RacingRegion.UNITED_KINGDOM: ["ascot"],
        })

    def test_source_url_does_not_override_content_or_source_region(self):
        article = self._article(
            racing_region=RacingRegion.UNITED_KINGDOM,
            title_ja="Trainer announces stable update",
            body_ja_raw="The trainer shared a routine stable update. " * 8,
            body_ja_normalized="The trainer shared a routine stable update. " * 8,
            source_url="https://example.com/france/longchamp/archive",
        )

        result = apply_article_attribution(article, force=True)
        article.refresh_from_db()

        self.assertEqual(result.primary_region, RacingRegion.UNITED_KINGDOM)
        self.assertEqual(article_region_set(article), {RacingRegion.UNITED_KINGDOM})

    def test_multiple_context_regions_fall_back_to_source_region(self):
        article = self._article(
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="Japanese and French breeding discussion",
            body_ja_raw="Japanese and French breeding trends were discussed without a named race. " * 8,
            body_ja_normalized="Japanese and French breeding trends were discussed without a named race. " * 8,
        )

        result = apply_article_attribution(article, force=True)
        article.refresh_from_db()

        self.assertEqual(result.primary_region, RacingRegion.UNITED_STATES)
        self.assertEqual(
            article_region_set(article),
            {RacingRegion.UNITED_STATES},
        )
        self.assertEqual(result.reason, "source_region_with_ambiguous_context")

    def test_ireland_content_is_temporarily_grouped_with_uk_and_tagged(self):
        article = self._article(
            title_ja="Irish Derby result at the Curragh",
            body_ja_raw="Irish Derby result at the Curragh. " * 8,
            body_ja_normalized="Irish Derby result at the Curragh. " * 8,
        )

        apply_article_attribution(article, force=True)
        article.refresh_from_db()

        self.assertIn(RacingRegion.UNITED_KINGDOM, article_region_set(article))
        self.assertIn("ireland", article.tags_json)

    def test_english_term_gate_accepts_terms_from_related_regions(self):
        article = self._article(racing_region=RacingRegion.FRANCE)
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.UNITED_KINGDOM, source="test")
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Desert Crown",
            target_zh="沙漠皇冠",
            is_active=True,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(outcome.passed, outcome.details)
        self.assertEqual(outcome.details["term_gate_region_excluded_terms"], [])

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="web_test_groups",
    )
    def test_public_feed_region_filter_includes_related_region_articles(self):
        article = self._article(
            racing_region=RacingRegion.UNITED_KINGDOM,
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="test")

        visible = filter_articles_visible_in_region(
            NewsArticle.objects.filter(workflow_status=WorkflowStatus.PUBLISHED),
            RacingRegion.FRANCE,
        )
        response = self.client.get("/", {"region": RacingRegion.FRANCE})

        self.assertEqual(list(visible), [article])
        self.assertContains(response, article.title_zh)

    @override_settings(
        QQ_PUSH_SCOPE="all_public",
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="web_test_groups",
    )
    def test_qq_eligibility_matches_related_region_and_blocks_tips_category(self):
        article = self._article(
            racing_region=RacingRegion.UNITED_KINGDOM,
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
            content_category=ContentCategory.NEWS,
        )
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="test")
        target = PushTarget.objects.create(
            name="France group",
            group_id="france-1",
            allowed_regions=[RacingRegion.FRANCE],
            is_active=True,
            multiregion_test_enabled=True,
        )

        self.assertTrue(should_push_news_to_qq(article, target=target).allowed)
        article.content_category = ContentCategory.TIPS
        article.save(update_fields=["content_category", "updated_at"])

        result = should_push_news_to_qq(article, target=target)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "content_category_not_qq_eligible")

    @override_settings(
        QQ_PUSH_SCOPE="all_public",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=False,
    )
    def test_qq_single_region_fallback_ignores_related_regions(self):
        article = self._article(
            racing_region=RacingRegion.UNITED_KINGDOM,
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
            content_category=ContentCategory.NEWS,
        )
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="test")
        target = PushTarget.objects.create(
            name="France fallback group",
            group_id="france-fallback",
            allowed_regions=[RacingRegion.FRANCE],
            is_active=True,
        )

        result = should_push_news_to_qq(article, target=target)

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "region_not_allowed")
        self.assertNotIn("关联地区", build_qq_auto_push_message(article))

    @override_settings(QQ_PUSH_SCOPE="all_public")
    def test_qq_default_categories_exclude_other(self):
        article = self._article(
            racing_region=RacingRegion.UNITED_KINGDOM,
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
            content_category=ContentCategory.OTHER,
        )
        target = PushTarget.objects.create(
            name="UK group",
            group_id="uk-other",
            allowed_regions=[RacingRegion.UNITED_KINGDOM],
            is_active=True,
        )

        result = should_push_news_to_qq(article, target=target)

        self.assertNotIn(ContentCategory.OTHER, django_settings.MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "content_category_not_qq_eligible")

    def test_article_editor_can_unlock_manual_attribution(self):
        article = self._article(
            racing_region=RacingRegion.UNITED_KINGDOM,
            attribution_locked=True,
        )
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="manual")
        form = ArticleEditorForm(
            data={
                "racing_region": RacingRegion.UNITED_KINGDOM,
                "related_regions": [RacingRegion.FRANCE],
                "content_category": ContentCategory.NEWS,
                "title_zh": article.title_zh,
                "summary_zh": article.summary_zh,
                "body_zh": article.body_zh,
                "source_note": article.source_note,
                "editor_notes": article.editor_notes,
                "tags_text": "",
            },
            instance=article,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        article.refresh_from_db()

        self.assertFalse(article.attribution_locked)
        self.assertEqual(article_region_set(article), {RacingRegion.UNITED_KINGDOM, RacingRegion.FRANCE})

    def test_article_editor_can_clear_all_related_regions(self):
        article = self._article(racing_region=RacingRegion.UNITED_KINGDOM)
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="manual")
        form = ArticleEditorForm(
            data={
                "racing_region": RacingRegion.UNITED_KINGDOM,
                "related_regions_present": "1",
                "content_category": ContentCategory.NEWS,
                "title_zh": article.title_zh,
                "summary_zh": article.summary_zh,
                "body_zh": article.body_zh,
                "source_note": article.source_note,
                "editor_notes": article.editor_notes,
                "tags_text": "",
            },
            instance=article,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        article.refresh_from_db()

        self.assertEqual(article_region_set(article), {RacingRegion.UNITED_KINGDOM})
        self.assertFalse(article.related_region_links.exists())

    def test_legacy_editor_payload_without_region_fields_preserves_related_regions(self):
        article = self._article(racing_region=RacingRegion.UNITED_KINGDOM)
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="manual")
        form = ArticleEditorForm(
            data={
                "title_zh": article.title_zh,
                "summary_zh": article.summary_zh,
                "body_zh": article.body_zh,
                "source_note": article.source_note,
                "editor_notes": article.editor_notes,
                "tags_text": "",
            },
            instance=article,
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertEqual(article_region_set(article), {RacingRegion.UNITED_KINGDOM, RacingRegion.FRANCE})

    def test_related_region_validation_returns_field_error_for_primary_region(self):
        article = self._article(racing_region=RacingRegion.UNITED_KINGDOM)
        link = NewsArticleRelatedRegion(article=article, region=RacingRegion.UNITED_KINGDOM)

        with self.assertRaises(ValidationError) as raised:
            link.full_clean()

        self.assertIn("region", raised.exception.message_dict)
        self.assertIn("不能与文章主地区相同", raised.exception.message_dict["region"][0])

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="web_test_groups",
    )
    def test_region_display_and_qq_message_show_primary_before_related_regions(self):
        article = self._article(
            racing_region=RacingRegion.UNITED_STATES,
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.JAPAN, source="test")
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="test")

        message = build_qq_auto_push_message(article)
        response = self.client.get(article.public_path)

        self.assertEqual(article.region_display_text, "美国 · 相关：日本 / 法国")
        self.assertIn("地区：美国", message)
        self.assertIn("关联地区：日本 / 法国", message)
        self.assertContains(response, "主地区：")
        self.assertContains(response, "美国")
        self.assertContains(response, "关联地区：")
        self.assertContains(response, "日本 / 法国")

    @override_settings(MULTIREGION_RELATED_REGION_QUERIES_ENABLED=False)
    def test_public_region_display_fallback_hides_related_regions_without_deleting_them(self):
        article = self._article(
            racing_region=RacingRegion.UNITED_STATES,
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.JAPAN, source="test")
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="test")

        detail_response = self.client.get(article.public_path)
        home_response = self.client.get("/")

        self.assertEqual(article.region_display_text, "美国")
        self.assertEqual(article.related_region_display_text, "")
        self.assertContains(detail_response, "主地区：")
        self.assertContains(detail_response, "美国")
        self.assertNotContains(detail_response, "关联地区：")
        self.assertContains(home_response, article.title_zh)
        self.assertNotContains(home_response, "相关：日本")
        self.assertEqual(article.related_region_links.count(), 2)

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="web_test_groups",
    )
    def test_publish_window_records_related_unpublished_article_without_publishing_it(self):
        from stable.services.publishing_windows import select_publish_candidates

        article = self._article(racing_region=RacingRegion.UNITED_KINGDOM)
        NewsArticleRelatedRegion.objects.create(article=article, region=RacingRegion.FRANCE, source="test")
        start = timezone.now().replace(second=0, microsecond=0)
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.PUBLISH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.FRANCE,
            scope_key="region:france",
            window_start=start,
            window_end=start + timedelta(minutes=15),
        )

        result = select_publish_candidates(RacingRegion.FRANCE, window=window, now=timezone.now())

        self.assertEqual(result.selected, [])
        self.assertTrue(
            WindowCandidateDecision.objects.filter(
                window=window,
                article=article,
                reason="related_region_waiting_primary_region",
            ).exists()
        )

    @override_settings(
        MULTIREGION_ATTRIBUTION_GOLD_VERSION="gold-test-v1",
        MULTIREGION_ATTRIBUTION_GOLD_SNAPSHOT_SHA256="a" * 64,
    )
    def test_reprocess_command_dry_run_does_not_write_and_commit_only_restores_candidate(self):
        article = self._article(
            racing_region=RacingRegion.FRANCE,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            gate_issues=[
                {
                    "code": "term_region_excluded",
                    "severity": "info",
                    "payload": {"source_ja": "Desert Crown", "term_region": RacingRegion.UNITED_KINGDOM},
                }
            ],
        )
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Desert Crown",
            target_zh="沙漠皇冠",
            is_active=True,
        )

        dry_run_output = StringIO()
        call_command(
            "reprocess_multiregion_attribution_gates",
            "--region",
            RacingRegion.FRANCE,
            "--dry-run",
            "--json",
            stdout=dry_run_output,
        )
        article.refresh_from_db()
        self.assertEqual(article.racing_region, RacingRegion.FRANCE)
        self.assertFalse(article.related_region_links.exists())
        self.assertIn(str(article.id), dry_run_output.getvalue())

        dry_run_payload = json.loads(dry_run_output.getvalue())
        from stable.models import MultiregionAttributionRun
        from stable.services.attribution_runs import _manifest_sha256

        run = MultiregionAttributionRun.objects.get(pk=dry_run_payload["run_id"])
        run.metrics = {"qualified": True}
        run.manifest_sha256 = _manifest_sha256(
            rows=list(run.candidate_payload or []),
            rule_version=run.rule_version,
            term_version=run.term_version,
            gold_version=run.gold_version,
            settings_sha256=run.settings_sha256,
            term_snapshot_sha256=run.term_snapshot_sha256,
            gold_snapshot_sha256=run.gold_snapshot_sha256,
            metrics=run.metrics,
        )
        run.save(update_fields=["metrics", "manifest_sha256", "updated_at"])
        dry_run_payload["manifest_sha256"] = run.manifest_sha256

        call_command(
            "reprocess_multiregion_attribution_gates",
            "--commit",
            "--run-id",
            dry_run_payload["run_id"],
            "--manifest-sha256",
            dry_run_payload["manifest_sha256"],
            stdout=StringIO(),
        )
        article.refresh_from_db()
        self.assertEqual(article.racing_region, RacingRegion.UNITED_KINGDOM)
        self.assertEqual(article.workflow_status, WorkflowStatus.PENDING_EDIT)
        self.assertIsNone(article.published_to_web_at)
        self.assertEqual(article_region_set(article), {RacingRegion.UNITED_KINGDOM})

    def test_reprocess_dry_run_respects_manual_attribution_lock(self):
        article = self._article(
            racing_region=RacingRegion.FRANCE,
            attribution_locked=True,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            gate_issues=[{"code": "term_region_excluded", "severity": "info"}],
        )
        output = StringIO()

        call_command(
            "reprocess_multiregion_attribution_gates",
            "--region",
            RacingRegion.FRANCE,
            "--dry-run",
            "--json",
            stdout=output,
        )
        payload = json.loads(output.getvalue())
        outcome = next(item for item in payload["outcomes"] if item["article_id"] == article.id)

        self.assertTrue(outcome["attribution_locked"])
        self.assertFalse(outcome["attribution_applied"])
        self.assertEqual(outcome["new_regions"], {"primary": RacingRegion.FRANCE, "related": []})
        self.assertEqual(outcome["inferred_regions"]["primary"], RacingRegion.UNITED_KINGDOM)

    def test_reprocess_limit_counts_valid_candidates_instead_of_scanned_rows(self):
        unrelated = self._article(
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            gate_issues=[{"code": "quality_warning", "severity": "warning"}],
        )
        first_candidate = self._article(
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            gate_issues=[{"code": "core_term_missing", "severity": "blocker"}],
        )
        second_candidate = self._article(
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            gate_issues=[{"code": "term_region_excluded", "severity": "info"}],
        )
        output = StringIO()

        call_command(
            "reprocess_multiregion_attribution_gates",
            "--dry-run",
            "--limit",
            "1",
            "--json",
            stdout=output,
        )
        payload = json.loads(output.getvalue())

        self.assertEqual(payload["candidate_ids"], [first_candidate.id])
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["scanned_count"], 3)
        self.assertTrue(payload["has_more_candidates"])
        self.assertIn(unrelated.id, payload["skipped"]["no_reprocessable_gate"])
        self.assertNotIn(second_candidate.id, payload["candidate_ids"])


class TermResolverTests(TestCase):
    def test_resolve_terms_and_apply_mappings(self):
        TermEntry.objects.create(
            term_type="horse",
            source_ja="ソダシ",
            target_zh="纯白少女",
            aliases_ja=["Sodashi"],
            priority=10,
        )
        matches = resolve_terms("ソダシが勝利した", limit=10)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].target_zh, "纯白少女")
        self.assertEqual(apply_term_mappings("ソダシが勝利した"), "纯白少女が勝利した")

    def test_terms_with_same_text_can_coexist_by_source_language(self):
        TermEntry.objects.create(term_type="race", source_language=SourceLanguage.JAPANESE, source_ja="Title", target_zh="日文标题")
        TermEntry.objects.create(term_type="race", source_language=SourceLanguage.ENGLISH, source_ja="Title", target_zh="英文标题")
        TermEntry.objects.create(
            term_type="race",
            source_language=SourceLanguage.CHINESE_TRADITIONAL,
            source_ja="香港打吡大賽",
            target_zh="香港打吡大赛",
        )

        english_terms = resolve_terms_for_language("Title preview", SourceLanguage.ENGLISH, limit=10)
        zh_hant_terms = resolve_terms_for_language("香港打吡大賽前瞻", SourceLanguage.CHINESE_TRADITIONAL, limit=10)

        self.assertEqual([term.target_zh for term in english_terms], ["英文标题"])
        self.assertEqual([term.target_zh for term in zh_hant_terms], ["香港打吡大赛"])
        self.assertEqual(apply_term_mappings("Title preview", source_language=SourceLanguage.ENGLISH), "英文标题 preview")
        self.assertEqual(apply_term_mappings("Title preview", source_language=SourceLanguage.JAPANESE), "日文标题 preview")
        self.assertEqual(
            apply_term_mappings("香港打吡大賽前瞻", source_language=SourceLanguage.CHINESE_TRADITIONAL),
            "香港打吡大赛前瞻",
        )

    def test_same_term_concept_can_have_multilingual_aliases(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
            priority=100,
        )
        TermAlias.objects.create(term=term, source_language=SourceLanguage.ENGLISH, text="Equinox", alias_type=TermAliasType.PRIMARY)
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.CHINESE_TRADITIONAL,
            text="春秋分",
            alias_type=TermAliasType.PRIMARY,
        )

        english_terms = resolve_terms_for_language("Equinox returns in a feature", SourceLanguage.ENGLISH, limit=10)
        japanese_terms = resolve_terms_for_language("イクイノックスが始動", SourceLanguage.JAPANESE, limit=10)

        self.assertEqual([(item.source_ja, item.target_zh, item.matched_text) for item in english_terms], [("イクイノックス", "春秋分", "Equinox")])
        self.assertEqual([(item.source_ja, item.target_zh, item.matched_text) for item in japanese_terms], [("イクイノックス", "春秋分", "イクイノックス")])
        self.assertEqual(resolve_terms_for_language("イクイノックス", SourceLanguage.ENGLISH, limit=10), [])
        self.assertEqual(extract_horse_tags("Equinox lines up at Ascot.", source_language=SourceLanguage.ENGLISH), ["春秋分"])

    def test_english_term_matching_is_case_insensitive_and_preserves_matched_text(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
            priority=100,
        )
        TermAlias.objects.create(term=term, source_language=SourceLanguage.ENGLISH, text="Equinox", alias_type=TermAliasType.PRIMARY)

        matches = resolve_terms_for_language("EQUINOX returns at Ascot", SourceLanguage.ENGLISH, limit=10)

        self.assertEqual([(item.target_zh, item.matched_text) for item in matches], [("春秋分", "EQUINOX")])
        self.assertEqual(apply_term_mappings("EQUINOX returns at Ascot", source_language=SourceLanguage.ENGLISH), "春秋分 returns at Ascot")
        self.assertEqual(apply_term_mappings("PREQUINOX returns", source_language=SourceLanguage.ENGLISH), "PREQUINOX returns")

    def test_apply_single_created_english_term_is_case_insensitive_for_article_language(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            priority=100,
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="single-term-english-case",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="EQUINOX returns",
            translated_title_zh="EQUINOX returns",
            translated_body_zh="EQUINOX returns at Ascot. PREQUINOX stays unchanged.",
            body_zh="EQUINOX returns at Ascot.",
            published_at=timezone.now(),
            source_url="https://example.com/single-term-english-case",
        )

        result = apply_created_term_to_article(article, term)

        article.refresh_from_db()
        self.assertIn("translated_title_zh", result.updated_fields)
        self.assertEqual(article.translated_title_zh, "春秋分 returns")
        self.assertEqual(article.translated_body_zh, "春秋分 returns at Ascot. PREQUINOX stays unchanged.")
        self.assertEqual(article.body_zh, "春秋分 returns at Ascot.")

    def test_multilingual_alias_matching_bulk_loads_aliases(self):
        for index in range(8):
            term = TermEntry.objects.create(
                term_type="horse",
                source_language=SourceLanguage.JAPANESE,
                source_ja=f"テストホース{index}",
                target_zh=f"测试马{index}",
                priority=index,
            )
            TermAlias.objects.create(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text=f"Test Horse {index}",
                alias_type=TermAliasType.PRIMARY,
            )

        with CaptureQueriesContext(connection) as captured:
            terms = resolve_terms_for_language("Test Horse 7 returns at Sha Tin", SourceLanguage.ENGLISH, limit=10)

        self.assertEqual([term.target_zh for term in terms], ["测试马7"])
        self.assertLessEqual(len(captured.captured_queries), 3)

    def test_latin_term_matching_is_case_insensitive_without_language_filter(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Lucky Star",
            target_zh="幸运星",
            priority=100,
        )

        terms = resolve_terms("lucky star returns at Sha Tin", limit=5)
        mapped = apply_term_mappings("LUCKY STAR returns at Sha Tin")

        self.assertEqual([term.target_zh for term in terms], ["幸运星"])
        self.assertEqual(mapped, "幸运星 returns at Sha Tin")

    def test_english_article_does_not_use_japanese_horse_heuristic(self):
        recognized = recognize_horse_names("ASCOT PREVIEW", "TITLE runs at Ascot.", source_language=SourceLanguage.ENGLISH)

        self.assertEqual(recognized, [])

    def test_english_external_horse_alias_is_recognized_without_japanese_heuristic(self):
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH001",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            confidence=96,
        )

        recognized = recognize_horse_names(
            "Lucky Star wins at Sha Tin",
            "The gelding Lucky Star was too strong in the Class 3 contest.",
            source_language=SourceLanguage.ENGLISH,
        )

        self.assertEqual(len(recognized), 1)
        self.assertEqual(recognized[0].source, "external_alias")
        self.assertEqual(recognized[0].matched_text, "Lucky Star")
        self.assertEqual(recognized[0].external_horse_ids, ["HKH001"])
        self.assertTrue(recognized[0].needs_preserve)

    def test_english_external_horse_alias_preserves_source_spelling(self):
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH002",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            confidence=96,
        )

        recognized = recognize_horse_names(
            "LUCKY STAR wins at Sha Tin",
            "The gelding was too strong.",
            source_language=SourceLanguage.ENGLISH,
        )

        self.assertEqual(len(recognized), 1)
        self.assertEqual(recognized[0].name_ja, "Lucky Star")
        self.assertEqual(recognized[0].matched_text, "LUCKY STAR")

    def test_english_external_horse_alias_lookup_uses_article_candidates(self):
        for index in range(20):
            ExternalHorseAlias.objects.create(
                source="hkjc",
                racing_region=RacingRegion.HONG_KONG,
                source_language=SourceLanguage.ENGLISH,
                external_horse_id=f"UNRELATED{index}",
                name_ja=f"Unrelated Horse {index}",
                name_en=f"Unrelated Horse {index}",
                normalized_name=f"Unrelated Horse {index}",
                confidence=80,
            )
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH003",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            confidence=96,
        )

        with CaptureQueriesContext(connection) as captured:
            recognized = recognize_horse_names(
                "Lucky Star wins again",
                "A sharp performance at Sha Tin.",
                source_language=SourceLanguage.ENGLISH,
            )

        self.assertEqual([item.matched_text for item in recognized], ["Lucky Star"])
        self.assertLessEqual(len(captured.captured_queries), 4)

    def test_extract_horse_tags_returns_translated_horse_names(self):
        TermEntry.objects.create(term_type="horse", source_ja="ソダシ", target_zh="纯净之辉", priority=100)
        TermEntry.objects.create(term_type="horse", source_ja="リバティアイランド", target_zh="自由岛", priority=90)
        TermEntry.objects.create(term_type="race", source_ja="桜花賞", target_zh="樱花赏", priority=80)

        tags = extract_horse_tags("ソダシとリバティアイランドが桜花賞に出走する。")

        self.assertEqual(tags, ["纯净之辉", "自由岛"])

    def test_extract_unknown_horse_names_skips_known_horses_and_keeps_unmapped(self):
        TermEntry.objects.create(term_type="horse", source_ja="クロワデュノール", target_zh="北十字星", priority=100)

        names = extract_unknown_horse_names(
            "【大阪杯レース後コメント】クロワデュノール北村友一騎手ら",
            "1着 クロワデュノール(北村友一騎手)\n2着 メイショウタバル(武豊騎手)\n3着 ダノンデサイル(坂井瑠星騎手)",
        )

        self.assertIn("メイショウタバル", names)
        self.assertIn("ダノンデサイル", names)
        self.assertNotIn("クロワデュノール", names)

    def test_extract_unknown_horse_names_skips_generic_racing_words(self):
        names = extract_unknown_horse_names(
            "【平安S】ロードクロンヌがリベンジへ",
            "昨年の雪辱を期すロードクロンヌが平安Sに向かう。アクションプランも出走予定。",
        )

        self.assertNotIn("リベンジ", names)

    def test_external_horse_alias_is_recognized_and_preserved_without_mapping(self):
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )

        recognized = recognize_horse_names("マヤノライジンが出走", "マヤノライジンは重賞へ向かう。")
        external = [item for item in recognized if item.name_ja == "マヤノライジン"][0]

        self.assertEqual(external.source, "external_alias")
        self.assertTrue(external.needs_preserve)
        self.assertFalse(external.has_translation)
        self.assertEqual(external.external_horse_ids, ["1001"])
        self.assertEqual(apply_term_mappings("マヤノライジンが出走"), "マヤノライジンが出走")
        self.assertIn("マヤノライジン", extract_unknown_horse_names("マヤノライジンが出走", ""))

    def test_formal_horse_term_takes_priority_over_external_alias(self):
        TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神", priority=100)
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )

        recognized = recognize_horse_names("マヤノライジンが出走", "")
        formal = [item for item in recognized if item.name_ja == "マヤノライジン"][0]

        self.assertEqual(formal.source, "formal_term")
        self.assertFalse(formal.needs_preserve)
        self.assertTrue(formal.has_translation)
        self.assertEqual(apply_term_mappings("マヤノライジンが出走"), "摩耶雷神が出走")
        self.assertNotIn("マヤノライジン", extract_unknown_horse_names("マヤノライジンが出走", ""))

    def test_pending_horse_term_is_recognized_and_preserved_without_replacement(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Forever Young",
            target_zh="",
            racing_region=RacingRegion.JAPAN,
            priority=100,
            is_active=True,
        )

        recognized = recognize_horse_names(
            "FOREVER YOUNG aims at the Breeders' Cup",
            "Forever Young remains on the dirt championship trail.",
            source_language=SourceLanguage.ENGLISH,
        )

        self.assertEqual(resolve_terms_for_language("FOREVER YOUNG returns", SourceLanguage.ENGLISH, limit=5)[0].target_zh, "")
        self.assertEqual(apply_term_mappings("FOREVER YOUNG returns", source_language=SourceLanguage.ENGLISH), "FOREVER YOUNG returns")
        self.assertEqual(len(recognized), 1)
        self.assertEqual(recognized[0].source, "formal_pending_term")
        self.assertEqual(recognized[0].matched_text, "FOREVER YOUNG")
        self.assertTrue(recognized[0].needs_preserve)
        self.assertFalse(recognized[0].has_translation)

    def test_validate_rewrite_requires_pending_horse_original_preserved(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Forever Young",
            target_zh="",
            racing_region=RacingRegion.JAPAN,
            priority=100,
            is_active=True,
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="pending-horse-original-required",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="Forever Young targets the Breeders' Cup Classic",
            body_ja_raw="Forever Young will continue his preparation for the Breeders' Cup Classic. " * 8,
            body_ja_normalized="Forever Young will continue his preparation for the Breeders' Cup Classic. " * 8,
            translated_title_zh="日本泥地名马瞄准育马者杯经典赛",
            title_zh="日本泥地名马瞄准育马者杯经典赛",
            translated_body_zh="这匹日本泥地名马将继续备战育马者杯经典赛。" * 12,
            body_zh="这匹日本泥地名马将继续备战育马者杯经典赛。" * 12,
            published_at=timezone.now(),
            source_url="https://example.com/pending-horse-original-required",
        )

        outcome = validate_rewrite(article)

        self.assertFalse(outcome.passed)
        self.assertTrue(any(issue["code"] == "pending_horse_original_missing" for issue in outcome.issues))

    def test_pending_horse_chinese_alias_does_not_replace_original_name_requirement(self):
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Forever Young",
            target_zh="",
            aliases_zh=["青春永驻"],
            racing_region=RacingRegion.JAPAN,
            priority=100,
            is_active=True,
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="pending-horse-chinese-alias-only",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="Forever Young targets the Breeders' Cup Classic",
            body_ja_raw="Forever Young will continue his preparation for the Breeders' Cup Classic. " * 8,
            body_ja_normalized="Forever Young will continue his preparation for the Breeders' Cup Classic. " * 8,
            translated_title_zh="青春永驻瞄准育马者杯经典赛",
            title_zh="青春永驻瞄准育马者杯经典赛",
            translated_body_zh="青春永驻将继续备战育马者杯经典赛。" * 12,
            body_zh="青春永驻将继续备战育马者杯经典赛。" * 12,
            published_at=timezone.now(),
            source_url="https://example.com/pending-horse-chinese-alias-only",
        )

        outcome = validate_rewrite(article)

        self.assertFalse(outcome.passed)
        self.assertTrue(any(issue["code"] == "pending_horse_original_missing" for issue in outcome.issues))

    def test_horse_term_is_recognized_by_english_name_and_chinese_translation(self):
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Forever Young",
            target_zh="青春永驻",
            translation_status="translated",
            is_active=True,
        )

        english = recognize_horse_names("Forever Young returns", "", source_language=SourceLanguage.ENGLISH)
        chinese = recognize_horse_names("青春永驻即将复出", "", source_language=SourceLanguage.CHINESE)

        self.assertEqual(english[0].name_ja, term.source_ja)
        self.assertEqual(chinese[0].name_ja, term.source_ja)
        self.assertEqual(chinese[0].matched_text, "青春永驻")

    def test_ambiguous_translated_horse_name_is_preserved_instead_of_auto_replaced(self):
        for target in ("孪生星", "双星"):
            TermEntry.objects.create(
                term_type=TermType.HORSE,
                source_language=SourceLanguage.ENGLISH,
                source_ja="Twin Star",
                target_zh=target,
                translation_status="translated",
                is_active=True,
            )

        mapped = apply_term_mappings("Twin Star returns", source_language=SourceLanguage.ENGLISH)
        recognized = recognize_horse_names("Twin Star returns", "", source_language=SourceLanguage.ENGLISH)

        self.assertEqual(mapped, "Twin Star returns")
        self.assertTrue(recognized[0].needs_preserve)
        self.assertIn("ambiguous_formal_horse_name", recognized[0].conflict_flags)

    def test_common_word_external_alias_requires_strong_horse_context(self):
        TermEntry.objects.create(
            term_type="fixed_phrase",
            source_ja="タイトル",
            target_zh="标题",
            notes="non_horse_common_word: 测试普通词",
        )
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="2001",
            name_ja="タイトル",
            normalized_name="タイトル",
            alias_source="test",
        )

        ordinary = recognize_horse_names("記事のタイトルを変更", "ページタイトルを確認した。")
        strong = recognize_horse_names("タイトルが出走", "タイトルは武豊騎手とのコンビで重賞へ向かう。")

        self.assertNotIn("タイトル", [item.name_ja for item in ordinary])
        self.assertIn("タイトル", [item.name_ja for item in strong])

    def test_external_horse_alias_keeps_multiple_horse_ids(self):
        for horse_id in ["3001", "3002"]:
            ExternalHorseAlias.objects.create(
                source="netkeiba",
                external_horse_id=horse_id,
                name_ja="ドウメイホース",
                normalized_name="ドウメイホース",
                alias_source="test",
            )

        recognized = recognize_horse_names("ドウメイホースが出走", "")
        item = [entry for entry in recognized if entry.name_ja == "ドウメイホース"][0]

        self.assertCountEqual(item.external_horse_ids, ["3001", "3002"])

    def test_unknown_horse_limit_is_applied_after_known_horse_terms(self):
        for name in ["アカホース", "アオホース", "クロホース"]:
            TermEntry.objects.create(term_type="horse", source_ja=name, target_zh=f"{name}译名")
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="4001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )

        names = extract_unknown_horse_names(
            "アカホース アオホース クロホース マヤノライジンが出走",
            "",
            limit=1,
        )

        self.assertEqual(names, ["マヤノライジン"])


class TermAliasConceptMergeTests(TestCase):
    def _term(self, **overrides):
        payload = {
            "term_type": TermType.HORSE,
            "source_language": SourceLanguage.ENGLISH,
            "source_ja": f"Target {TermEntry.objects.count()}",
            "target_zh": "测试译名",
            "racing_region": RacingRegion.JAPAN,
            "priority": 10,
        }
        payload.update(overrides)
        return TermEntry.objects.create(**payload)

    def test_plan_reports_same_target_japanese_primary_owner_without_writing(self):
        target = self._term(source_ja="Kalamatianos", target_zh="欢快舞步")
        source = self._term(
            source_language=SourceLanguage.JAPANESE,
            source_ja="カラマティアノス",
            target_zh="欢快舞步",
        )

        from stable.services.term_maintenance import plan_hkjc_ja_alias_merge

        result = plan_hkjc_ja_alias_merge(target_term_ids=[target.pk])

        self.assertEqual(result["summary"]["candidate_count"], 1)
        row = result["rows"][0]
        self.assertEqual(row["action"], "candidate")
        self.assertEqual(row["source_text"], "カラマティアノス")
        self.assertEqual(row["owner_term_id"], source.pk)
        self.assertFalse(TermAlias.objects.filter(term=target, text="カラマティアノス").exists())

    def test_plan_treats_primary_alias_for_same_term_as_single_owner(self):
        target = self._term(source_ja="Kalamatianos", target_zh="欢快舞步")
        source = self._term(
            source_language=SourceLanguage.JAPANESE,
            source_ja="カラマティアノス",
            target_zh="欢快舞步",
        )
        TermAlias.objects.create(
            term=source,
            source_language=SourceLanguage.JAPANESE,
            text="カラマティアノス",
            alias_type=TermAliasType.PRIMARY,
            is_active=True,
        )

        from stable.services.term_maintenance import plan_hkjc_ja_alias_merge

        result = plan_hkjc_ja_alias_merge(target_term_ids=[target.pk])

        self.assertEqual(result["summary"]["candidate_count"], 1)
        row = result["rows"][0]
        self.assertEqual(row["action"], "candidate")
        self.assertEqual(row["owner_kind"], "primary")
        self.assertEqual(row["owner_term_id"], source.pk)

    def test_plan_skips_conflicting_target_translation_from_candidate_file(self):
        target = self._term(source_ja="Raijin", target_zh="霹雳雷公")
        self._term(
            source_language=SourceLanguage.JAPANESE,
            source_ja="ライジン",
            target_zh="雷神",
        )

        from stable.services.term_maintenance import plan_hkjc_ja_alias_merge

        result = plan_hkjc_ja_alias_merge(
            target_term_ids=[target.pk],
            candidate_rows=[{"target_term_id": target.pk, "source_text": "ライジン"}],
        )

        self.assertEqual(result["summary"]["skipped_count"], 1)
        self.assertEqual(result["rows"][0]["reason"], "target_zh_conflict")
        self.assertFalse(TermAlias.objects.filter(term=target, text="ライジン").exists())

    def test_plan_skips_active_alias_owner_on_another_concept(self):
        target = self._term(source_ja="Scintillation", target_zh="烁亮丽")
        other = self._term(source_ja="Other", target_zh="灿惑")
        TermAlias.objects.create(
            term=other,
            source_language=SourceLanguage.JAPANESE,
            text="シンチレーション",
            alias_type=TermAliasType.ALIAS,
            is_active=True,
        )

        from stable.services.term_maintenance import plan_hkjc_ja_alias_merge

        result = plan_hkjc_ja_alias_merge(
            target_term_ids=[target.pk],
            candidate_rows=[{"target_term_id": target.pk, "source_text": "シンチレーション"}],
        )

        row = result["rows"][0]
        self.assertEqual(row["action"], "skipped")
        self.assertEqual(row["reason"], "active_alias_owner")
        self.assertEqual(row["owner_term_id"], other.pk)

    def test_apply_merges_alias_deactivates_source_and_is_idempotent(self):
        target = self._term(source_ja="Kalamatianos", target_zh="欢快舞步")
        source = self._term(
            source_language=SourceLanguage.JAPANESE,
            source_ja="カラマティアノス",
            target_zh="欢快舞步",
        )

        from stable.services.term_maintenance import apply_hkjc_ja_alias_merge, plan_hkjc_ja_alias_merge

        plan = plan_hkjc_ja_alias_merge(target_term_ids=[target.pk])
        first = apply_hkjc_ja_alias_merge(plan["rows"])
        second = apply_hkjc_ja_alias_merge(plan["rows"])

        source.refresh_from_db()
        self.assertEqual(first["summary"]["applied_count"], 1)
        self.assertFalse(source.is_active)
        self.assertIn(f"hkjc_ja_alias_merged_into_term_id={target.pk}", source.notes)
        self.assertEqual(TermAlias.objects.filter(term=target, source_language=SourceLanguage.JAPANESE, text="カラマティアノス").count(), 1)
        self.assertEqual(second["summary"]["skipped_count"], 1)

    def test_apply_rechecks_stale_plan_before_writing(self):
        target = self._term(source_ja="Kalamatianos", target_zh="欢快舞步")
        source = self._term(
            source_language=SourceLanguage.JAPANESE,
            source_ja="カラマティアノス",
            target_zh="欢快舞步",
        )

        from stable.services.term_maintenance import apply_hkjc_ja_alias_merge, plan_hkjc_ja_alias_merge

        plan = plan_hkjc_ja_alias_merge(target_term_ids=[target.pk])
        source.target_zh = "不同译名"
        source.save(update_fields=["target_zh", "updated_at"])

        result = apply_hkjc_ja_alias_merge(plan["rows"])

        source.refresh_from_db()
        self.assertEqual(result["summary"]["skipped_count"], 1)
        self.assertTrue(source.is_active)
        self.assertFalse(TermAlias.objects.filter(term=target, text="カラマティアノス").exists())


class ArticleTermBackfillTests(TestCase):
    def _term(self, **overrides):
        payload = {
            "term_type": TermType.HORSE,
            "source_language": SourceLanguage.ENGLISH,
            "source_ja": "Kalamatianos",
            "target_zh": "欢快舞步",
            "racing_region": RacingRegion.JAPAN,
            "priority": 100,
        }
        payload.update(overrides)
        return TermEntry.objects.create(**payload)

    def _article(self, **overrides):
        now = timezone.now()
        payload = {
            "source_site": SourceSite.NETKEIBA,
            "source_mode": SourceMode.LATEST,
            "source_article_id": overrides.pop("source_article_id", f"article-term-backfill-{NewsArticle.objects.count()}"),
            "racing_region": RacingRegion.JAPAN,
            "source_language": SourceLanguage.JAPANESE,
            "title_ja": "カラマティアノス近況",
            "body_ja_raw": "カラマティアノスが出走予定。",
            "body_ja_normalized": "カラマティアノスが出走予定。",
            "translated_title_zh": "カラマティアノス近况",
            "translated_body_zh": "カラマティアノス将出赛。",
            "translated_summary_zh": "カラマティアノス消息。",
            "base_translation_zh": "カラマティアノス将出赛。",
            "title_zh": "カラマティアノス近况",
            "body_zh": "カラマティアノス将出赛。",
            "summary_zh": "カラマティアノス消息。",
            "push_summary_zh": "カラマティアノス消息。",
            "published_at": now,
            "published_to_web_at": now,
            "workflow_status": WorkflowStatus.PUBLISHED,
            "published_by_mode": PublishedByMode.AUTO,
            "source_url": overrides.pop("source_url", f"https://example.com/article-term-backfill-{NewsArticle.objects.count()}"),
        }
        payload.update(overrides)
        return NewsArticle.objects.create(**payload)

    def test_plan_outputs_full_field_diff_without_writing(self):
        term = self._term()
        TermAlias.objects.create(term=term, source_language=SourceLanguage.JAPANESE, text="カラマティアノス")
        article = self._article()

        from stable.services.term_maintenance import plan_article_term_backfill

        result = plan_article_term_backfill(term_ids=[term.pk], article_ids=[article.pk])

        self.assertGreaterEqual(result["summary"]["planned_fields"], 1)
        row = [item for item in result["rows"] if item["field"] == "body_zh"][0]
        self.assertEqual(row["before"], "カラマティアノス将出赛。")
        self.assertEqual(row["after"], "欢快舞步将出赛。")
        article.refresh_from_db()
        self.assertEqual(article.body_zh, "カラマティアノス将出赛。")

    def test_apply_updates_only_planned_fields_and_is_idempotent(self):
        term = self._term()
        TermAlias.objects.create(term=term, source_language=SourceLanguage.JAPANESE, text="カラマティアノス")
        article = self._article()

        from stable.services.term_maintenance import apply_article_term_backfill, plan_article_term_backfill

        plan = plan_article_term_backfill(term_ids=[term.pk], article_ids=[article.pk])
        first = apply_article_term_backfill(plan["rows"])
        second = apply_article_term_backfill(plan["rows"])

        article.refresh_from_db()
        self.assertIn("欢快舞步", article.body_zh)
        self.assertEqual(first["summary"]["updated_fields"], plan["summary"]["planned_fields"])
        self.assertGreaterEqual(second["summary"]["stale_fields"] + second["summary"]["unchanged_fields"], 1)

    def test_manual_publish_field_is_skipped_but_machine_field_updates(self):
        term = self._term()
        TermAlias.objects.create(term=term, source_language=SourceLanguage.JAPANESE, text="カラマティアノス")
        article = self._article(manually_edited_fields=["body_zh"])

        from stable.services.term_maintenance import apply_article_term_backfill, plan_article_term_backfill

        plan = plan_article_term_backfill(term_ids=[term.pk], article_ids=[article.pk])
        body_row = [item for item in plan["rows"] if item["field"] == "body_zh"][0]
        self.assertEqual(body_row["action"], "skipped")
        self.assertEqual(body_row["reason"], "manual_field")

        apply_article_term_backfill(plan["rows"])

        article.refresh_from_db()
        self.assertEqual(article.body_zh, "カラマティアノス将出赛。")
        self.assertEqual(article.translated_body_zh, "欢快舞步将出赛。")

    def test_backfill_apply_preserves_publish_workflow_and_qq_delivery_state(self):
        term = self._term()
        TermAlias.objects.create(term=term, source_language=SourceLanguage.JAPANESE, text="カラマティアノス")
        article = self._article()
        target = PushTarget.objects.create(name="测试群", group_id="1001")
        delivery = QQPushDelivery.objects.create(article=article, target=target, status=QQPushDeliveryStatus.SENT, message_id="msg-1")
        before_status = (article.workflow_status, article.published_to_web_at, article.published_by_mode, delivery.status)

        from stable.services.term_maintenance import apply_article_term_backfill, plan_article_term_backfill

        plan = plan_article_term_backfill(term_ids=[term.pk], article_ids=[article.pk])
        apply_article_term_backfill(plan["rows"])

        article.refresh_from_db()
        delivery.refresh_from_db()
        self.assertEqual((article.workflow_status, article.published_to_web_at, article.published_by_mode, delivery.status), before_status)
        self.assertEqual(QQPushDelivery.objects.filter(article=article).count(), 1)

    def test_unpublished_articles_are_excluded_by_default(self):
        term = self._term()
        TermAlias.objects.create(term=term, source_language=SourceLanguage.JAPANESE, text="カラマティアノス")
        article = self._article(workflow_status=WorkflowStatus.PENDING_REVIEW, published_to_web_at=None)

        from stable.services.term_maintenance import plan_article_term_backfill

        result = plan_article_term_backfill(term_ids=[term.pk], article_ids=[article.pk])

        self.assertEqual(result["summary"]["scanned_articles"], 0)
        self.assertEqual(result["rows"], [])

    def test_stale_field_value_is_not_overwritten(self):
        term = self._term()
        TermAlias.objects.create(term=term, source_language=SourceLanguage.JAPANESE, text="カラマティアノス")
        article = self._article()

        from stable.services.term_maintenance import apply_article_term_backfill, plan_article_term_backfill

        plan = plan_article_term_backfill(term_ids=[term.pk], article_ids=[article.pk])
        article.body_zh = "人工改过的カラマティアノス。"
        article.save(update_fields=["body_zh", "updated_at"])

        result = apply_article_term_backfill([row for row in plan["rows"] if row["field"] == "body_zh"])

        article.refresh_from_db()
        self.assertEqual(result["rows"][0]["action"], "stale")
        self.assertEqual(article.body_zh, "人工改过的カラマティアノス。")

    def test_plan_preloads_aliases_instead_of_querying_per_field(self):
        term = self._term()
        TermAlias.objects.create(term=term, source_language=SourceLanguage.JAPANESE, text="カラマティアノス")
        other = self._term(source_ja="Lucky Sweynesse", target_zh="金钻贵人")
        TermAlias.objects.create(term=other, source_language=SourceLanguage.JAPANESE, text="ラッキースワイネス")
        self._article()
        self._article(
            title_ja="無関係",
            body_ja_raw="無関係",
            body_ja_normalized="無関係",
            translated_title_zh="普通新闻",
            translated_body_zh="没有待替换术语。",
            translated_summary_zh="普通摘要。",
            base_translation_zh="没有待替换术语。",
            title_zh="普通新闻",
            body_zh="没有待替换术语。",
            summary_zh="普通摘要。",
            push_summary_zh="普通摘要。",
        )

        from stable.services.term_maintenance import plan_article_term_backfill

        with CaptureQueriesContext(connection) as queries:
            result = plan_article_term_backfill(term_ids=[term.pk, other.pk], source_language=SourceLanguage.JAPANESE)

        self.assertGreaterEqual(result["summary"]["planned_fields"], 1)
        self.assertLessEqual(len(queries), 4)


class TermMaintenanceCommandTests(TestCase):
    def _term(self, **overrides):
        payload = {
            "term_type": TermType.HORSE,
            "source_language": SourceLanguage.ENGLISH,
            "source_ja": "Kalamatianos",
            "target_zh": "欢快舞步",
            "racing_region": RacingRegion.JAPAN,
        }
        payload.update(overrides)
        return TermEntry.objects.create(**payload)

    def _article(self, **overrides):
        now = timezone.now()
        payload = {
            "source_site": SourceSite.NETKEIBA,
            "source_mode": SourceMode.LATEST,
            "source_article_id": overrides.pop("source_article_id", f"term-command-{NewsArticle.objects.count()}"),
            "racing_region": RacingRegion.JAPAN,
            "source_language": SourceLanguage.JAPANESE,
            "title_ja": "カラマティアノス",
            "body_ja_raw": "カラマティアノス",
            "body_ja_normalized": "カラマティアノス",
            "translated_title_zh": "カラマティアノス",
            "translated_body_zh": "カラマティアノス",
            "translated_summary_zh": "カラマティアノス",
            "base_translation_zh": "カラマティアノス",
            "title_zh": "カラマティアノス",
            "body_zh": "カラマティアノス",
            "summary_zh": "カラマティアノス",
            "push_summary_zh": "カラマティアノス",
            "published_at": now,
            "published_to_web_at": now,
            "workflow_status": WorkflowStatus.PUBLISHED,
            "source_url": overrides.pop("source_url", f"https://example.com/term-command-{NewsArticle.objects.count()}"),
        }
        payload.update(overrides)
        return NewsArticle.objects.create(**payload)

    def test_merge_command_defaults_to_dry_run_and_writes_artifacts(self):
        target = self._term()
        self._term(source_language=SourceLanguage.JAPANESE, source_ja="カラマティアノス")
        out = StringIO()

        with tempfile.TemporaryDirectory() as tmp:
            call_command("merge_hkjc_ja_aliases", "--target-term-id", str(target.pk), "--output-dir", tmp, stdout=out)
            artifact = Path(tmp) / "merge_plan.json"
            payload = json.loads(artifact.read_text(encoding="utf-8"))

        self.assertIn("dry-run", out.getvalue())
        self.assertEqual(payload["summary"]["candidate_count"], 1)
        self.assertFalse(TermAlias.objects.filter(term=target, text="カラマティアノス").exists())

    def test_merge_command_apply_requires_plan_file_and_writes_alias(self):
        target = self._term()
        source = self._term(source_language=SourceLanguage.JAPANESE, source_ja="カラマティアノス")

        with tempfile.TemporaryDirectory() as tmp:
            call_command("merge_hkjc_ja_aliases", "--target-term-id", str(target.pk), "--output-dir", tmp, stdout=StringIO())
            call_command("merge_hkjc_ja_aliases", "--apply", "--plan-file", str(Path(tmp) / "merge_plan.json"), "--output-dir", tmp, stdout=StringIO())

        source.refresh_from_db()
        self.assertFalse(source.is_active)
        self.assertTrue(TermAlias.objects.filter(term=target, text="カラマティアノス").exists())

    def test_backfill_command_writes_full_diff_and_apply_updates_article(self):
        term = self._term()
        TermAlias.objects.create(term=term, source_language=SourceLanguage.JAPANESE, text="カラマティアノス")
        article = self._article()

        with tempfile.TemporaryDirectory() as tmp:
            call_command(
                "backfill_article_terms",
                "--term-id",
                str(term.pk),
                "--article-id",
                str(article.pk),
                "--output-dir",
                tmp,
                stdout=StringIO(),
            )
            diff_path = Path(tmp) / "article_backfill_diff.json"
            payload = json.loads(diff_path.read_text(encoding="utf-8"))
            body_row = [row for row in payload["rows"] if row["field"] == "body_zh"][0]
            call_command("backfill_article_terms", "--apply", "--diff-file", str(diff_path), "--output-dir", tmp, stdout=StringIO())

        article.refresh_from_db()
        self.assertEqual(body_row["before"], "カラマティアノス")
        self.assertEqual(body_row["after"], "欢快舞步")
        self.assertEqual(article.body_zh, "欢快舞步")

    def test_backfill_command_apply_rejects_unbounded_write(self):
        term = self._term()

        with self.assertRaises(CommandError):
            call_command("backfill_article_terms", "--apply", "--term-id", str(term.pk), stdout=StringIO())


class RaceGradeTests(TestCase):
    def test_normalize_race_grade_covers_common_jra_classes(self):
        from stable.services.automation import normalize_race_grade

        cases = {
            "宝塚記念・GI": "G1",
            "安田記念（ＧⅠ）": "G1",
            "札幌記念 GII": "G2",
            "金鯱賞（Ｇ２）": "G2",
            "中山金杯 GIII": "G3",
            "京都金杯（ＧⅢ）": "G3",
            "リステッド競走": "L",
            "Listed": "L",
            "オープン特別": "OP",
            "OP": "OP",
            "メイクデビュー東京": "NEWCOMER",
            "新馬戦": "NEWCOMER",
            "未勝利戦": "MAIDEN",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_race_grade(raw), expected)

    def test_race_grade_drives_automation_priority_and_keeps_low_classes_low(self):
        from stable.services.automation import race_priority

        TermEntry.objects.create(term_type="race", source_ja="宝塚記念", target_zh="宝塚纪念", race_grade="G1")
        g1_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="race-grade-g1",
            title_ja="【宝塚記念】注目馬が出走",
            body_ja_raw="宝塚記念に出走する。GIの大一番に向けて調整は順調。",
            body_ja_normalized="宝塚記念に出走する。GIの大一番に向けて調整は順調。",
            translated_body_zh="宝塚纪念的赛前消息。" * 20,
            translation_status=ArticleTranslationStatus.TRANSLATED,
            published_at=timezone.now(),
            source_url="https://example.com/race-grade-g1",
        )
        self.assertEqual(race_priority(g1_article)["priority"], "P0")

        TermEntry.objects.create(term_type="race", source_ja="新馬戦", target_zh="新马战", race_grade="NEWCOMER")
        newcomer_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="race-grade-newcomer",
            title_ja="東京新馬戦の出走馬が決定",
            body_ja_raw="東京新馬戦に若駒が出走する。",
            body_ja_normalized="東京新馬戦に若駒が出走する。",
            translated_body_zh="新马战消息。" * 20,
            translation_status=ArticleTranslationStatus.TRANSLATED,
            published_at=timezone.now(),
            source_url="https://example.com/race-grade-newcomer",
        )
        decision = score_article_for_automation(newcomer_article)
        self.assertNotEqual(decision.decision_reason["signals"]["race_priority"], "P0")
        self.assertLess(decision.score_total, 75)


class TextExtractionTests(TestCase):
    def test_extract_article_text_keeps_inline_links_in_same_line(self):
        html = """
        <div class="News_Txt">
          <p>JRAは6日、<a href="/?pid=keyword&id=1">WIN5</a>の通年発売を発表した。</p>
          <p>対象レースは<a href="/?pid=keyword&id=2">JRA</a>ホームページに掲載される。</p>
        </div>
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        text = extract_article_text(soup.select_one(".News_Txt"))
        self.assertIn("JRAは6日、WIN5の通年発売を発表した。", text)
        self.assertIn("対象レースはJRAホームページに掲載される。", text)
        self.assertNotIn("\nWIN5\n", text)
        self.assertNotIn("\nJRA\n", text)


class RewritePayloadTests(TestCase):
    def test_loads_rewrite_payload_tolerates_control_characters(self):
        payload = _loads_rewrite_payload(
            '{"rewrite_title_zh":"标题","rewrite_summary_zh":"摘要","rewrite_body_zh":"第一段\x0b第二段","rewrite_confidence":90}'
        )

        self.assertEqual(payload["rewrite_title_zh"], "标题")
        self.assertEqual(payload["rewrite_body_zh"], "第一段第二段")

    def test_rewrite_prompt_uses_matched_source_alias_for_article_language(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
            priority=100,
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.PRIMARY,
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="rewrite-english-term-prompt",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Equinox returns at Ascot",
            body_ja_raw="Equinox returns at Ascot in a feature race.",
            body_ja_normalized="Equinox returns at Ascot in a feature race.",
            translated_title_zh="春秋分回归",
            translated_body_zh="春秋分将在阿斯科特回归。",
            published_at=timezone.now(),
            source_url="https://example.com/rewrite-english-term-prompt",
        )
        provider = OpenAICompatibleRewriteProvider(api_key="test-key", base_url="https://example.com/v1")

        prompt = provider._messages(article)[1]["content"]

        self.assertIn("[horse] Equinox => 春秋分", prompt)
        self.assertNotIn("[horse] イクイノックス => 春秋分", prompt)


class AdapterTests(TestCase):
    def test_netkeiba_listing_parse(self):
        fragment = """
        <div><a href="https://news.netkeiba.com/?pid=news_view&no=1" title="テスト記事" class="ArticleLink fc">
        <div class="NewsTxtBox"><h2 class="NewsTitle">テスト記事</h2>
        <ul class="Nk_DataList"><li class="Time">1時間前</li><li class="Comment">3</li><li class="Chumoku">8</li></ul>
        </div></a></div>
        """
        payload = "(" + __import__("json").dumps(fragment) + ")"
        with patch("stable.adapters.netkeiba.get_bytes", return_value=payload):
            items = NetkeibaAdapter().fetch_listing(SourceMode.LATEST, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_article_id, "1")
        self.assertEqual(items[0].comment_count, 3)

    def test_jra_listing_parse(self):
        html = """
        <div class="news_unit"><h2>2026年3月25日（水曜）</h2>
        <ul class="news_line_list"><li><a href="/news/202603/032503.html"><div class="txt">クイーンSの競走馬登録抹消</div></a></li></ul>
        </div>
        """
        with patch("stable.adapters.jra.get_bytes", return_value=html):
            items = JRAAdapter().fetch_listing(SourceMode.OFFICIAL, "202603")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_site, SourceSite.JRA)
        self.assertEqual(items[0].title_ja, "クイーンSの競走馬登録抹消")

    def test_jra_listing_parse_without_year_uses_month_hint(self):
        html = """
        <div class="news_unit"><h2>5月31日（日曜）</h2>
        <ul class="news_line_list"><li><a href="/news/202605/053101.html"><div class="txt">無年份日期新闻</div></a></li></ul>
        </div>
        """
        with patch("stable.adapters.jra.get_bytes", return_value=html):
            items = JRAAdapter().fetch_listing(SourceMode.OFFICIAL, "202605")
        self.assertEqual(len(items), 1)
        local = items[0].published_at.astimezone(ZoneInfo("Asia/Tokyo"))
        self.assertEqual(local.year, 2026)
        self.assertEqual(local.month, 5)
        self.assertEqual(local.day, 31)

    def test_jra_date_parse_rolls_back_future_no_year_date(self):
        adapter = JRAAdapter()
        now = datetime(2026, 1, 2, 3, 0, tzinfo=dt_timezone.utc)
        with patch("stable.adapters.jra.timezone.now", return_value=now):
            parsed = adapter._parse_heading_date("12月31日（木曜）")
        local = parsed.astimezone(ZoneInfo("Asia/Tokyo"))
        self.assertEqual(local.year, 2025)
        self.assertEqual(local.month, 12)
        self.assertEqual(local.day, 31)

    def test_international_adapters_parse_minimal_article_metadata(self):
        cases = [
            (SponichiAdapter(), RacingRegion.JAPAN, SourceLanguage.JAPANESE, "競馬 テスト記事"),
            (HKJCRacingNewsAdapter(), RacingRegion.HONG_KONG, SourceLanguage.ENGLISH, "HKJC racing preview"),
            (SCMPRacingAdapter(), RacingRegion.HONG_KONG, SourceLanguage.ENGLISH, "Hong Kong racing news"),
            (SportingLifeAdapter(), RacingRegion.UNITED_KINGDOM, SourceLanguage.ENGLISH, "Royal Ascot latest"),
            (SkySportsRacingAdapter(), RacingRegion.UNITED_KINGDOM, SourceLanguage.ENGLISH, "Sky Sports racing latest"),
            (BHAAdapter(), RacingRegion.UNITED_KINGDOM, SourceLanguage.ENGLISH, "BHA racing update"),
            (FranceGalopEnglishNewsAdapter(), RacingRegion.FRANCE, SourceLanguage.ENGLISH, "France Galop English update"),
            (HorseRacingNationAdapter(), RacingRegion.UNITED_STATES, SourceLanguage.ENGLISH, "Kentucky racing report"),
            (AtTheRacesFranceAdapter(), RacingRegion.FRANCE, SourceLanguage.ENGLISH, "France racing at Deauville"),
            (BloodHorseAdapter(), RacingRegion.UNITED_STATES, SourceLanguage.ENGLISH, "Kentucky racing report"),
            (PaulickReportAdapter(), RacingRegion.UNITED_STATES, SourceLanguage.ENGLISH, "US racing report"),
        ]
        listing_html = '<main><article><a href="/news/test-article">France racing at Deauville</a></article></main>'
        detail_html = """
        <html><body>
          <article>
            <h1>France racing at Deauville</h1>
            <time datetime="2026-06-20T10:30:00+00:00">20 June 2026</time>
            <div class="horses-racing-news-content">
              <div class="article-body"><p>Preview body with enough racing detail.</p></div>
            </div>
          </article>
        </body></html>
        """
        for adapter, region, language, title in cases:
            with self.subTest(adapter=adapter.__class__.__name__):
                listing_href = f"{adapter.link_path_keywords[0].rstrip('/')}/test-article"
                listing = listing_html.replace("/news/test-article", listing_href).replace("France racing at Deauville", title)
                detail = detail_html.replace("France racing at Deauville", title)
                stubs = adapter.parse_listing_html(listing, url=adapter.base_url)
                self.assertEqual(len(stubs), 1)
                detail_payload = adapter.parse_detail_html(detail, url=stubs[0].source_url)
                draft = adapter.normalize_source_payload(stubs[0], detail_payload)
                self.assertEqual(draft.title_ja, title)
                self.assertIn("Preview body", draft.body_ja_normalized)
                self.assertEqual(draft.racing_region, region)
                self.assertEqual(draft.source_language, language)
                self.assertTrue(draft.source_url.startswith("https://"))
                self.assertIn("<html>", draft.original_content_html)
                self.assertNotIn("html", draft.metadata)

    def test_international_article_id_includes_url_hash_to_avoid_slug_collision(self):
        adapter = HKJCRacingNewsAdapter()

        first = adapter.parse_listing_html(
            '<article><a href="/english/news/preview">Preview</a></article>',
            url=adapter.base_url,
        )[0]
        second = adapter.parse_listing_html(
            '<article><a href="/english/features/preview">Preview</a></article>',
            url=adapter.base_url,
        )[0]

        self.assertNotEqual(first.source_article_id, second.source_article_id)
        self.assertTrue(first.source_article_id.startswith("preview-"))

    def test_international_listing_ignores_navigation_links(self):
        adapter = AtTheRacesFranceAdapter()
        stubs = adapter.parse_listing_html(
            """
            <nav><a href="/news/site-map">France racing navigation</a></nav>
            <main>
              <article><a href="/news/deauville-preview">France racing at Deauville</a></article>
            </main>
            """,
            url=adapter.base_url,
        )

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].source_url, "https://www.attheraces.com/news/deauville-preview")

    def test_sponichi_access_ranking_keeps_upstream_rank_and_filters_non_racing(self):
        adapter = SponichiAdapter()
        stubs = adapter.parse_listing_html(
            """
            <ul class="tab-contents">
              <a href="/gamble/news/2026/06/25/kiji/20260625s00053000198000c.html">
                1 【鳴門ボート】シリーズ2勝の石野貴之
              </a>
              <a href="/gamble/news/2026/06/25/kiji/20260625s00004048222000c.html">
                4 昨年皐月賞＆有馬記念覇者ミュージアムマイルは放牧中
              </a>
            </ul>
            """,
            url=adapter.listing_url(1, mode=SourceMode.ACCESS),
            mode=SourceMode.ACCESS,
        )

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].source_mode, SourceMode.ACCESS)
        self.assertEqual(stubs[0].rank, 4)
        self.assertEqual(stubs[0].title_ja, "昨年皐月賞＆有馬記念覇者ミュージアムマイルは放牧中")
        self.assertIn("s000040", stubs[0].source_url)

    def test_sky_sports_access_ranking_keeps_top_story_order(self):
        adapter = SkySportsRacingAdapter()
        stubs = adapter.parse_listing_html(
            """
            <main>
              <a href="/football/news/11661/1/not-racing">Football story</a>
              <a href="/racing/news/12426/100/racing-top-story">Racing top story</a>
              <a href="/racing/news/12426/101/royal-ascot-preview">Royal Ascot preview</a>
            </main>
            """,
            url=adapter.listing_url(1, mode=SourceMode.ACCESS),
            mode=SourceMode.ACCESS,
        )

        self.assertEqual(len(stubs), 2)
        self.assertEqual(stubs[0].source_mode, SourceMode.ACCESS)
        self.assertEqual(stubs[0].rank, 1)
        self.assertEqual(stubs[1].rank, 2)
        self.assertEqual(stubs[0].title_ja, "Racing top story")

    def test_france_galop_english_news_uses_official_english_pages(self):
        adapter = FranceGalopEnglishNewsAdapter()
        stubs = adapter.parse_listing_html(
            """
            <div class="views-row">
              <h2><a href="/en/content/grand-prix-preview">Grand Prix preview</a></h2>
            </div>
            <h2><a href="/fr/content/article-francais">Article français</a></h2>
            """,
            url=adapter.listing_url(1, mode=SourceMode.OFFICIAL),
            mode=SourceMode.OFFICIAL,
        )

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].source_site, SourceSite.FRANCE_GALOP_NEWS)
        self.assertEqual(stubs[0].source_mode, SourceMode.OFFICIAL)
        self.assertEqual(stubs[0].source_url, "https://www.france-galop.com/en/content/grand-prix-preview")

    def test_tdn_latest_listing_uses_public_wordpress_api(self):
        adapter = TDNAdapter()

        class FakeResponse:
            status_code = 200
            url = "https://www.thoroughbreddailynews.com/wp-json/wp/v2/search?search=French%20racing&per_page=20"

            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {
                        "link": "https://www.thoroughbreddailynews.com/test-story/",
                        "title": {"rendered": "TDN &amp; racing update"},
                        "date_gmt": "2026-06-25T01:02:03",
                    }
                ]

        with patch("stable.adapters.international.requests.get", return_value=FakeResponse()):
            stubs = adapter.fetch_listing(SourceMode.LATEST, 1)

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].source_site, SourceSite.TDN)
        self.assertEqual(stubs[0].title_ja, "TDN & racing update")
        self.assertEqual(stubs[0].source_url, "https://www.thoroughbreddailynews.com/test-story/")
        self.assertIsNotNone(stubs[0].published_at.tzinfo)

    def test_tdn_normalize_preserves_listing_timestamp_when_detail_has_no_date(self):
        adapter = TDNAdapter()

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {
                        "link": "https://www.thoroughbreddailynews.com/test-story/",
                        "title": {"rendered": "TDN racing update"},
                        "date_gmt": "2026-06-25T01:02:03",
                    }
                ]

        with patch("stable.adapters.international.requests.get", return_value=FakeResponse()):
            stub = adapter.fetch_listing(SourceMode.LATEST, 1)[0]
        detail = adapter.parse_detail_html(
            """
            <html><body>
              <article>
                <h1>TDN racing update</h1>
                <div class="entry-content"><p>Body without a date node.</p></div>
              </article>
            </body></html>
            """,
            url=stub.source_url,
        )

        draft = adapter.normalize_source_payload(stub, detail)

        self.assertIsNone(detail.published_at)
        self.assertEqual(draft.published_at, datetime(2026, 6, 25, 1, 2, 3, tzinfo=dt_timezone.utc))

    def test_tdn_france_keyword_listing_marks_france_region(self):
        adapter = TDNFranceKeywordAdapter()
        adapter.max_api_article_age = None

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return [{"id": 101, "url": "https://www.thoroughbreddailynews.com/france-galop-story/", "title": "France Galop story"}]

        class FakePostResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "link": "https://www.thoroughbreddailynews.com/france-galop-story/",
                    "date_gmt": "2026-07-07T01:02:03",
                }

        with patch("stable.adapters.international.requests.get", side_effect=[FakeResponse(), FakePostResponse()]):
            stubs = adapter.fetch_listing(SourceMode.LATEST, 1)

        self.assertEqual(len(stubs), 1)
        self.assertEqual(adapter.racing_region, RacingRegion.FRANCE)
        self.assertEqual(stubs[0].source_site, SourceSite.TDN_FRANCE)
        self.assertEqual(stubs[0].title_ja, "France Galop story")

    def test_tdn_france_broad_keyword_listing_aggregates_and_dedupes_queries(self):
        adapter = TDNFranceBroadKeywordAdapter()
        adapter.max_api_article_age = None

        responses = [
            [
                {
                    "id": 101,
                    "url": "https://www.thoroughbreddailynews.com/french-racing-story/",
                    "title": "French racing story",
                }
            ],
            [
                {
                    "id": 101,
                    "url": "https://www.thoroughbreddailynews.com/french-racing-story/",
                    "title": "French racing story duplicate",
                },
                {
                    "id": 202,
                    "url": "https://www.thoroughbreddailynews.com/parislongchamp-story/",
                    "title": "ParisLongchamp story",
                },
            ],
            {
                "link": "https://www.thoroughbreddailynews.com/french-racing-story/",
                "date_gmt": "2026-07-07T01:02:03",
            },
            {
                "link": "https://www.thoroughbreddailynews.com/french-racing-story/",
                "date_gmt": "2026-07-07T01:02:03",
            },
            {
                "link": "https://www.thoroughbreddailynews.com/parislongchamp-story/",
                "date_gmt": "2026-07-07T02:03:04",
            },
        ]

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        with patch(
            "stable.adapters.international.requests.get",
            side_effect=[
                FakeResponse(responses[0]),
                FakeResponse(responses[2]),
                FakeResponse(responses[1]),
                FakeResponse(responses[3]),
                FakeResponse(responses[4]),
            ],
        ):
            adapter.search_queries = ("French racing", "ParisLongchamp")
            stubs = adapter.fetch_listing(SourceMode.ACCESS, 1)

        self.assertEqual([stub.title_ja for stub in stubs], ["ParisLongchamp story", "French racing story"])
        self.assertEqual([stub.source_mode for stub in stubs], [SourceMode.ACCESS, SourceMode.ACCESS])
        self.assertEqual(stubs[0].source_site, SourceSite.TDN_FRANCE)
        self.assertEqual(adapter.canonical_source_site, SourceSite.TDN)
        self.assertEqual(adapter.racing_region, RacingRegion.FRANCE)
        self.assertEqual(stubs[0].published_at, datetime(2026, 7, 7, 2, 3, 4, tzinfo=dt_timezone.utc))

    def test_tdn_france_broad_keyword_listing_keeps_successful_queries_when_one_query_fails(self):
        adapter = TDNFranceBroadKeywordAdapter()
        adapter.max_api_article_age = None

        class FakeResponse:
            status_code = 200
            url = "https://www.thoroughbreddailynews.com/wp-json/wp/v2/search?search=French%20racing&per_page=20"

            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {
                        "id": 101,
                        "url": "https://www.thoroughbreddailynews.com/french-racing-story/",
                        "title": "French racing story",
                    }
                ]

        class FakePostResponse:
            status_code = 200
            url = "https://www.thoroughbreddailynews.com/wp-json/wp/v2/posts/101"

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "link": "https://www.thoroughbreddailynews.com/french-racing-story/",
                    "date_gmt": "2026-07-07T01:02:03",
                }

        response = Mock(status_code=503)
        error = requests.HTTPError("503 Server Error")
        error.response = response

        with patch("stable.adapters.international.requests.get", side_effect=[FakeResponse(), FakePostResponse(), error]):
            adapter.search_queries = ("French racing", "ParisLongchamp")
            stubs = adapter.fetch_listing(SourceMode.ACCESS, 1)

        self.assertEqual([stub.title_ja for stub in stubs], ["French racing story"])
        self.assertEqual(stubs[0].metadata["listing_query"], "French racing")
        self.assertEqual(adapter.last_listing_http_status, 200)
        self.assertEqual(
            adapter.last_listing_final_url,
            "https://www.thoroughbreddailynews.com/wp-json/wp/v2/search?search=French%20racing&per_page=20",
        )
        self.assertEqual(adapter.last_listing_query_errors, [{"query": "ParisLongchamp", "error": "503 Server Error"}])

    def test_tdn_france_broad_keyword_listing_filters_historical_search_results(self):
        adapter = TDNFranceBroadKeywordAdapter()
        adapter.search_queries = ("French racing",)

        class FakeResponse:
            status_code = 200

            def __init__(self, payload, url):
                self.payload = payload
                self.url = url

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        responses = [
            FakeResponse(
                [
                    {
                        "id": 101,
                        "url": "https://www.thoroughbreddailynews.com/old-french-racing-story/",
                        "title": "Old French racing story",
                    },
                    {
                        "id": 202,
                        "url": "https://www.thoroughbreddailynews.com/new-french-racing-story/",
                        "title": "New French racing story",
                    },
                ],
                "https://www.thoroughbreddailynews.com/wp-json/wp/v2/search?search=French%20racing&per_page=20",
            ),
            FakeResponse(
                {
                    "link": "https://www.thoroughbreddailynews.com/old-french-racing-story/",
                    "date_gmt": "2022-03-21T13:11:40",
                },
                "https://www.thoroughbreddailynews.com/wp-json/wp/v2/posts/101",
            ),
            FakeResponse(
                {
                    "link": "https://www.thoroughbreddailynews.com/new-french-racing-story/",
                    "date_gmt": "2026-07-07T01:02:03",
                },
                "https://www.thoroughbreddailynews.com/wp-json/wp/v2/posts/202",
            ),
        ]

        with (
            patch("stable.adapters.international.requests.get", side_effect=responses),
            patch("stable.adapters.international.timezone.now", return_value=datetime(2026, 7, 7, 3, 0, tzinfo=dt_timezone.utc)),
        ):
            stubs = adapter.fetch_listing(SourceMode.ACCESS, 1)

        self.assertEqual([stub.title_ja for stub in stubs], ["New French racing story"])
        self.assertEqual(stubs[0].published_at, datetime(2026, 7, 7, 1, 2, 3, tzinfo=dt_timezone.utc))
        self.assertEqual(len(adapter.skipped_items), 1)
        self.assertIn("stale_published_at", adapter.skipped_items[0])

    def test_tdn_france_broad_keyword_listing_skips_search_items_without_post_date(self):
        adapter = TDNFranceBroadKeywordAdapter()
        adapter.search_queries = ("French racing",)

        class FakeResponse:
            status_code = 200

            def __init__(self, payload, url):
                self.payload = payload
                self.url = url

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        responses = [
            FakeResponse(
                [
                    {
                        "id": 101,
                        "url": "https://www.thoroughbreddailynews.com/no-date-french-racing-story/",
                        "title": "No date French racing story",
                    }
                ],
                "https://www.thoroughbreddailynews.com/wp-json/wp/v2/search?search=French%20racing&per_page=20",
            ),
            FakeResponse(
                {
                    "link": "https://www.thoroughbreddailynews.com/no-date-french-racing-story/",
                },
                "https://www.thoroughbreddailynews.com/wp-json/wp/v2/posts/101",
            ),
        ]

        with (
            patch("stable.adapters.international.requests.get", side_effect=responses),
            patch("stable.adapters.international.timezone.now", return_value=datetime(2026, 7, 7, 3, 0, tzinfo=dt_timezone.utc)),
        ):
            stubs = adapter.fetch_listing(SourceMode.ACCESS, 1)

        self.assertEqual(stubs, [])
        self.assertEqual(len(adapter.skipped_items), 1)
        self.assertIn("missing_published_at", adapter.skipped_items[0])

    def test_tdn_france_broad_keyword_listing_raises_when_all_queries_fail(self):
        adapter = TDNFranceBroadKeywordAdapter()
        response = Mock(status_code=503)
        error = requests.HTTPError("503 Server Error")
        error.response = response

        with patch("stable.adapters.international.requests.get", side_effect=[error, error]):
            adapter.search_queries = ("French racing", "ParisLongchamp")
            with self.assertRaises(requests.HTTPError):
                adapter.fetch_listing(SourceMode.ACCESS, 1)

        self.assertEqual(len(adapter.last_listing_query_errors), 2)

    def test_tdn_france_keyword_draft_uses_tdn_canonical_source_site(self):
        adapter = TDNFranceKeywordAdapter()
        stub = SourceArticleStub(
            source_site=SourceSite.TDN_FRANCE,
            source_mode=SourceMode.LATEST,
            source_article_id="france-galop-story-123",
            source_url="https://www.thoroughbreddailynews.com/france-galop-story/",
            title_ja="France Galop story",
            published_at=timezone.now(),
        )
        detail = SourceArticleDetail(
            title_ja="France Galop story",
            body_ja_raw="France Galop story body",
            body_ja_normalized="France Galop story body",
            published_at=None,
            images=[],
        )

        draft = adapter.normalize_source_payload(stub, detail)

        self.assertEqual(draft.source_site, SourceSite.TDN_FRANCE)
        self.assertEqual(draft.canonical_source_site, SourceSite.TDN)
        self.assertEqual(draft.racing_region, RacingRegion.FRANCE)

    def test_horse_racing_nation_access_prefers_trending_links(self):
        adapter = HorseRacingNationAdapter()
        stubs = adapter.parse_listing_html(
            """
            <div class="ticker">
              <a href="/news/Trending_story_123">Trending story</a>
            </div>
            <main>
              <a href="/news/Latest_story_456">Latest story</a>
            </main>
            """,
            url=adapter.listing_url(1, mode=SourceMode.ACCESS),
            mode=SourceMode.ACCESS,
        )

        self.assertEqual(len(stubs), 2)
        self.assertEqual(stubs[0].title_ja, "Trending story")
        self.assertEqual(stubs[0].rank, 1)
        self.assertEqual(stubs[1].rank, 2)

    def test_horse_racing_nation_listing_skips_news_index_links(self):
        adapter = HorseRacingNationAdapter()
        stubs = adapter.parse_listing_html(
            """
            <main>
              <a href="/news/news.aspx">Horse Racing News - Today's News Stories</a>
              <a href="/news/Real_story_123">Real racing story</a>
            </main>
            """,
            url=adapter.listing_url(1, mode=SourceMode.LATEST),
            mode=SourceMode.LATEST,
        )

        self.assertEqual(len(stubs), 1)
        self.assertEqual(stubs[0].title_ja, "Real racing story")

    def test_jra_listing_skips_bad_date_and_keeps_following_items(self):
        html = """
        <div class="news_unit"><h2>bad-date</h2>
        <ul class="news_line_list"><li><a href="/news/202605/053099.html"><div class="txt">坏日期</div></a></li></ul>
        </div>
        <div class="news_unit"><h2>5月31日（日曜）</h2>
        <ul class="news_line_list"><li><a href="/news/202605/053101.html"><div class="txt">可解析新闻</div></a></li></ul>
        </div>
        """
        adapter = JRAAdapter()
        with patch("stable.adapters.jra.get_bytes", return_value=html):
            items = adapter.fetch_listing(SourceMode.OFFICIAL, "202605")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title_ja, "可解析新闻")
        self.assertEqual(len(adapter.skipped_items), 1)

    def test_netkeiba_rank_schedule_and_builtin_interval_stay_aligned(self):
        latest_schedule = django_settings.CELERY_BEAT_SCHEDULE["crawl-netkeiba-latest-hourly"]["schedule"]
        rush_schedule = django_settings.CELERY_BEAT_SCHEDULE["crawl-netkeiba-latest-sunday-rush"]["schedule"]
        rush_end_schedule = django_settings.CELERY_BEAT_SCHEDULE["crawl-netkeiba-latest-sunday-rush-end"]["schedule"]
        access_schedule = django_settings.CELERY_BEAT_SCHEDULE["crawl-netkeiba-access"]["schedule"]
        attention_schedule = django_settings.CELERY_BEAT_SCHEDULE["crawl-netkeiba-attention"]["schedule"]

        def minute_values(schedule):
            return {int(item) for item in str(schedule._orig_minute).split(",")}

        latest_minutes = minute_values(latest_schedule)
        access_minutes = minute_values(access_schedule)
        attention_minutes = minute_values(attention_schedule)
        rush_minutes = minute_values(rush_schedule) | minute_values(rush_end_schedule)

        self.assertEqual(access_schedule._orig_minute, 16)
        self.assertEqual(attention_schedule._orig_minute, 26)
        self.assertEqual(access_schedule._orig_hour, "*")
        self.assertEqual(attention_schedule._orig_hour, "*")
        self.assertTrue(latest_minutes.isdisjoint(access_minutes))
        self.assertTrue(latest_minutes.isdisjoint(attention_minutes))
        self.assertTrue(access_minutes.isdisjoint(attention_minutes))
        self.assertTrue(rush_minutes.isdisjoint(access_minutes))
        self.assertTrue(rush_minutes.isdisjoint(attention_minutes))
        definitions = {(item["source_site"], item["source_mode"]): item for item in BUILTIN_SOURCE_DEFINITIONS}
        self.assertEqual(definitions[(SourceSite.NETKEIBA, SourceMode.ACCESS)]["crawl_interval_minutes"], 60)
        self.assertEqual(definitions[(SourceSite.NETKEIBA, SourceMode.ATTENTION)]["crawl_interval_minutes"], 60)
        self.assertEqual(definitions[(SourceSite.SPONICHI, SourceMode.ACCESS)]["feed_url"], "https://www.sponichi.co.jp/gamble/ranking/")


class IngestionSourceElevationTests(TestCase):
    def setUp(self):
        sync_builtin_sources()

    def make_draft(self, source_article_id: str, source_mode: str, *, rank: int | None = None) -> CanonicalNewsDraft:
        return CanonicalNewsDraft(
            source_site=SourceSite.NETKEIBA,
            source_mode=source_mode,
            source_article_id=source_article_id,
            source_url=f"https://news.netkeiba.com/?pid=news_view&no={source_article_id}",
            title_ja=f"榜单来源测试 {source_article_id}",
            body_ja_raw=f"榜单来源测试正文 {source_article_id}",
            body_ja_normalized=f"榜单来源测试正文 {source_article_id}",
            published_at=timezone.now(),
            images=[],
            rank=rank,
            metadata={"source_mode": source_mode},
        )

    def make_source_draft(
        self,
        source_article_id: str,
        source_mode: str,
        *,
        source_site: str,
        canonical_source_site: str | None = None,
        rank: int | None = None,
        racing_region: str = RacingRegion.JAPAN,
        source_language: str = SourceLanguage.JAPANESE,
    ) -> CanonicalNewsDraft:
        return CanonicalNewsDraft(
            source_site=source_site,
            source_mode=source_mode,
            source_article_id=source_article_id,
            source_url=f"https://example.com/{source_site}/{source_article_id}",
            title_ja=f"排序来源测试 {source_article_id}",
            body_ja_raw=f"排序来源测试正文 {source_article_id}",
            body_ja_normalized=f"排序来源测试正文 {source_article_id}",
            published_at=timezone.now(),
            images=[],
            racing_region=racing_region,
            source_language=source_language,
            rank=rank,
            canonical_source_site=canonical_source_site,
            metadata={"source_mode": source_mode},
        )

    def upsert(self, source_article_id: str, source_mode: str, *, rank: int | None = None, crawl_job: CrawlJob | None = None):
        return upsert_article_from_draft(self.make_draft(source_article_id, source_mode, rank=rank), crawl_job=crawl_job)

    def unpack_article(self, result):
        return result[0] if isinstance(result, tuple) else result.article

    def source_elevated(self, result) -> bool:
        if hasattr(result, "source_elevated"):
            return bool(result.source_elevated)
        if isinstance(result, tuple) and len(result) >= 3:
            return bool(result[2])
        return False

    def test_latest_article_elevates_to_access_and_exposes_signal(self):
        self.upsert("rank-elevate-access", SourceMode.LATEST)
        access_source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ACCESS)
        access_job = CrawlJob.objects.create(source=access_source)

        result = self.upsert("rank-elevate-access", SourceMode.ACCESS, rank=1, crawl_job=access_job)

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ACCESS)
        self.assertEqual(article.source_config, access_source)
        self.assertEqual(article.source_note, access_source.name)
        self.assertEqual(article.crawl_job, access_job)
        self.assertTrue(self.source_elevated(result))
        self.assertTrue(
            NewsSnapshot.objects.filter(article=article, source_mode=SourceMode.ACCESS, rank=1).exists()
        )

    def test_latest_article_elevates_to_attention_and_exposes_signal(self):
        self.upsert("rank-elevate-attention", SourceMode.LATEST)
        attention_source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ATTENTION)

        result = self.upsert("rank-elevate-attention", SourceMode.ATTENTION, rank=2)

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ATTENTION)
        self.assertEqual(article.source_config, attention_source)
        self.assertTrue(self.source_elevated(result))
        self.assertTrue(
            NewsSnapshot.objects.filter(article=article, source_mode=SourceMode.ATTENTION, rank=2).exists()
        )

    def test_access_and_attention_do_not_override_each_other(self):
        result = self.upsert("rank-no-mutual-override", SourceMode.ACCESS, rank=3)
        article = self.unpack_article(result)
        access_source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ACCESS)
        self.assertEqual(article.source_mode, SourceMode.ACCESS)

        result = self.upsert("rank-no-mutual-override", SourceMode.ATTENTION, rank=4)

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ACCESS)
        self.assertEqual(article.source_config, access_source)
        self.assertFalse(self.source_elevated(result))
        self.assertTrue(
            NewsSnapshot.objects.filter(article=article, source_mode=SourceMode.ATTENTION, rank=4).exists()
        )

    def test_latest_does_not_override_ranked_source(self):
        result = self.upsert("rank-not-overwritten-by-latest", SourceMode.ATTENTION, rank=5)
        article = self.unpack_article(result)
        attention_source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ATTENTION)
        self.assertEqual(article.source_mode, SourceMode.ATTENTION)

        result = self.upsert("rank-not-overwritten-by-latest", SourceMode.LATEST)

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ATTENTION)
        self.assertEqual(article.source_config, attention_source)
        self.assertFalse(self.source_elevated(result))
        self.assertTrue(NewsSnapshot.objects.filter(article=article, source_mode=SourceMode.LATEST).exists())

    def test_international_latest_article_elevates_to_ranked_source(self):
        latest_draft = self.make_source_draft(
            "sky-ranked-elevate",
            SourceMode.LATEST,
            source_site=SourceSite.SKY_SPORTS_RACING,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_language=SourceLanguage.ENGLISH,
        )
        upsert_article_from_draft(latest_draft)
        ranked_source = NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.ACCESS)

        result = upsert_article_from_draft(
            self.make_source_draft(
                "sky-ranked-elevate",
                SourceMode.ACCESS,
                source_site=SourceSite.SKY_SPORTS_RACING,
                rank=1,
                racing_region=RacingRegion.UNITED_KINGDOM,
                source_language=SourceLanguage.ENGLISH,
            )
        )

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ACCESS)
        self.assertEqual(article.source_config, ranked_source)
        self.assertTrue(self.source_elevated(result))

    def test_source_elevation_preserves_manually_locked_primary_region(self):
        initial = upsert_article_from_draft(
            self.make_source_draft(
                "sky-ranked-locked-region",
                SourceMode.LATEST,
                source_site=SourceSite.SKY_SPORTS_RACING,
                racing_region=RacingRegion.UNITED_KINGDOM,
                source_language=SourceLanguage.ENGLISH,
            )
        )
        article = self.unpack_article(initial)
        article.racing_region = RacingRegion.FRANCE
        article.attribution_locked = True
        article.save(update_fields=["racing_region", "attribution_locked", "updated_at"])

        result = upsert_article_from_draft(
            self.make_source_draft(
                "sky-ranked-locked-region",
                SourceMode.ACCESS,
                source_site=SourceSite.SKY_SPORTS_RACING,
                rank=1,
                racing_region=RacingRegion.UNITED_KINGDOM,
                source_language=SourceLanguage.ENGLISH,
            )
        )

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertTrue(self.source_elevated(result))
        self.assertEqual(article.source_mode, SourceMode.ACCESS)
        self.assertEqual(article.racing_region, RacingRegion.FRANCE)
        self.assertTrue(article.attribution_locked)

    def test_latest_source_does_not_override_international_ranked_source(self):
        ranked_draft = self.make_source_draft(
            "hrn-ranked-keeps-priority",
            SourceMode.ACCESS,
            source_site=SourceSite.HORSE_RACING_NATION,
            rank=3,
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
        )
        result = upsert_article_from_draft(ranked_draft)
        article = self.unpack_article(result)
        ranked_source = NewsSource.objects.get(source_site=SourceSite.HORSE_RACING_NATION, source_mode=SourceMode.ACCESS)
        self.assertEqual(article.source_mode, SourceMode.ACCESS)

        result = upsert_article_from_draft(
            self.make_source_draft(
                "hrn-ranked-keeps-priority",
                SourceMode.LATEST,
                source_site=SourceSite.HORSE_RACING_NATION,
                racing_region=RacingRegion.UNITED_STATES,
                source_language=SourceLanguage.ENGLISH,
            )
        )

        article = self.unpack_article(result)
        article.refresh_from_db()
        self.assertEqual(article.source_mode, SourceMode.ACCESS)
        self.assertEqual(article.source_config, ranked_source)
        self.assertFalse(self.source_elevated(result))
        self.assertTrue(NewsSnapshot.objects.filter(article=article, source_mode=SourceMode.LATEST).exists())

    def test_tdn_france_keyword_dedupes_against_tdn_and_keeps_france_region(self):
        normal_draft = self.make_source_draft(
            "tdn-shared-url",
            SourceMode.LATEST,
            source_site=SourceSite.TDN,
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
        )
        france_draft = self.make_source_draft(
            "tdn-shared-url",
            SourceMode.LATEST,
            source_site=SourceSite.TDN_FRANCE,
            canonical_source_site=SourceSite.TDN,
            racing_region=RacingRegion.FRANCE,
            source_language=SourceLanguage.ENGLISH,
        )
        france_source = NewsSource.objects.get(source_site=SourceSite.TDN_FRANCE, source_mode=SourceMode.LATEST)

        first_result = upsert_article_from_draft(normal_draft)
        second_result = upsert_article_from_draft(france_draft)

        article = self.unpack_article(first_result)
        article.refresh_from_db()
        self.assertFalse(second_result.created)
        self.assertEqual(NewsArticle.objects.filter(source_site=SourceSite.TDN, source_article_id="tdn-shared-url").count(), 1)
        self.assertEqual(article.racing_region, RacingRegion.FRANCE)
        self.assertEqual(article.source_config, france_source)
        self.assertTrue(
            NewsSnapshot.objects.filter(
                article=article,
                source_site=SourceSite.TDN_FRANCE,
                source_mode=SourceMode.LATEST,
            ).exists()
        )

        upsert_article_from_draft(normal_draft)
        article.refresh_from_db()
        self.assertEqual(article.racing_region, RacingRegion.FRANCE)
        self.assertEqual(article.source_config, france_source)


class InternationalSourceMetadataTests(TestCase):
    def test_sync_builtin_sources_includes_region_language_and_kind(self):
        sync_builtin_sources()

        jra = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        hkjc = NewsSource.objects.get(source_site=SourceSite.HKJC_NEWS, source_mode=SourceMode.LATEST)
        france = NewsSource.objects.get(source_site=SourceSite.FRANCE_GALOP_NEWS, source_mode=SourceMode.OFFICIAL)
        sky_ranked = NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.ACCESS)
        hpn_ranked = NewsSource.objects.get(source_site=SourceSite.HORSE_RACING_NATION, source_mode=SourceMode.ACCESS)
        at_the_races = NewsSource.objects.get(source_site=SourceSite.AT_THE_RACES, source_mode=SourceMode.LATEST)

        self.assertEqual(jra.racing_region, RacingRegion.JAPAN)
        self.assertEqual(jra.source_language, SourceLanguage.JAPANESE)
        self.assertEqual(hkjc.racing_region, RacingRegion.HONG_KONG)
        self.assertEqual(hkjc.source_language, SourceLanguage.ENGLISH)
        self.assertEqual(france.racing_region, RacingRegion.FRANCE)
        self.assertEqual(france.source_language, SourceLanguage.ENGLISH)
        self.assertFalse(france.enabled)
        self.assertEqual(sky_ranked.adapter_key, "sky_sports_racing")
        self.assertEqual(hpn_ranked.adapter_key, "horse_racing_nation")
        self.assertGreater(sky_ranked.priority, NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.LATEST).priority)
        self.assertIn("403", at_the_races.notes)

    def test_sync_builtin_sources_preserves_manual_enabled_flags(self):
        sync_builtin_sources()
        sky_latest = NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.LATEST)
        jra = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        sky_latest.enabled = True
        sky_latest.save(update_fields=["enabled", "updated_at"])
        jra.enabled = False
        jra.save(update_fields=["enabled", "updated_at"])

        sync_builtin_sources()

        sky_latest.refresh_from_db()
        jra.refresh_from_db()
        self.assertTrue(sky_latest.enabled)
        self.assertFalse(jra.enabled)

    def test_default_probe_sources_are_first_version_usable_sources(self):
        self.assertIn("sky_sports_racing", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertIn("france_galop_news", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertIn("tdn_france", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertIn("tdn", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertIn("horse_racing_nation", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertNotIn("at_the_races_france", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertNotIn("bloodhorse", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertNotIn("paulick_report", FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS)
        self.assertIn(("sky_sports_racing", SourceMode.ACCESS), FIRST_VERSION_INTERNATIONAL_PROBES)
        self.assertIn(("horse_racing_nation", SourceMode.ACCESS), FIRST_VERSION_INTERNATIONAL_PROBES)
        self.assertIn(("france_galop_news", SourceMode.OFFICIAL), FIRST_VERSION_INTERNATIONAL_PROBES)
        self.assertNotIn(("at_the_races_france", SourceMode.LATEST), FIRST_VERSION_INTERNATIONAL_PROBES)

    def test_article_upsert_inherits_region_and_language_from_source(self):
        sync_builtin_sources()
        draft = CanonicalNewsDraft(
            source_site=SourceSite.HKJC_NEWS,
            source_mode=SourceMode.LATEST,
            source_article_id="hkjc-meta-1",
            source_url="https://racingnews.hkjc.com/english/example",
            title_ja="HKJC news",
            body_ja_raw="HKJC body",
            body_ja_normalized="HKJC body",
            published_at=timezone.now(),
            images=[],
        )

        result = upsert_article_from_draft(draft)

        self.assertEqual(result.article.racing_region, RacingRegion.HONG_KONG)
        self.assertEqual(result.article.source_language, SourceLanguage.ENGLISH)
        self.assertEqual(result.article.source_config.adapter_key, "hkjc_news")

    def test_article_upsert_keeps_html_out_of_translation_metadata(self):
        sync_builtin_sources()
        draft = CanonicalNewsDraft(
            source_site=SourceSite.HKJC_NEWS,
            source_mode=SourceMode.LATEST,
            source_article_id="hkjc-html-meta",
            source_url="https://racingnews.hkjc.com/english/html-meta",
            title_ja="HKJC HTML metadata",
            body_ja_raw="HKJC body",
            body_ja_normalized="HKJC body",
            published_at=timezone.now(),
            images=[],
            original_content_html="<html><body>full page</body></html>",
            metadata={"html": "<html>legacy html</html>", "author": "HKJC"},
        )

        result = upsert_article_from_draft(draft)

        self.assertEqual(result.article.original_content_html, "<html><body>full page</body></html>")
        self.assertEqual(result.article.translation_metadata.get("author"), "HKJC")
        self.assertNotIn("html", result.article.translation_metadata)
        snapshot = NewsSnapshot.objects.get(article=result.article)
        self.assertEqual(snapshot.snapshot_metadata.get("author"), "HKJC")
        self.assertNotIn("html", snapshot.snapshot_metadata)


class FranceNewsSourceExpansionTests(TestCase):
    class FakeAcceptedFranceAdapter:
        source_site = SourceSite.AT_THE_RACES
        source_mode = SourceMode.LATEST
        racing_region = RacingRegion.FRANCE
        source_language = SourceLanguage.ENGLISH

        def listing_url(self, page_or_month, mode=None):
            return "https://example.com/france/news"

        def fetch_listing(self, mode, page_or_month):
            self.last_listing_http_status = 200
            self.last_listing_final_url = "https://example.com/france/news?page=1"
            return [
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=mode,
                    source_article_id="fr-accepted-1",
                    source_url="https://example.com/france/news/fr-accepted-1",
                    title_ja="Prix de l'Arc de Triomphe latest",
                    published_at=timezone.now(),
                )
            ]

        def fetch_detail(self, source_url):
            return SourceArticleDetail(
                title_ja="Prix de l'Arc de Triomphe latest",
                body_ja_raw="France racing body with enough detail for a stable probe. " * 4,
                body_ja_normalized="France racing body with enough detail for a stable probe. " * 4,
                published_at=timezone.now(),
                images=[],
                original_content_html="<html><article>France racing body</article></html>",
            )

    class FakeBlockedFranceAdapter(FakeAcceptedFranceAdapter):
        source_language = SourceLanguage.ENGLISH

        def fetch_listing(self, mode, page_or_month):
            self.last_listing_http_status = 403
            self.last_listing_final_url = "https://example.com/france/news/challenge"
            response = Mock(status_code=403)
            error = requests.HTTPError("403 Client Error: Forbidden")
            error.response = response
            raise error

    class FakePartialDetailFailureFranceAdapter(FakeAcceptedFranceAdapter):
        def fetch_listing(self, mode, page_or_month):
            self.last_listing_http_status = 200
            self.last_listing_final_url = "https://example.com/france/news?page=1"
            return [
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=mode,
                    source_article_id="fr-bad-detail",
                    source_url="https://example.com/france/news/fr-bad-detail",
                    title_ja="Bad detail article",
                    published_at=timezone.now(),
                ),
                SourceArticleStub(
                    source_site=self.source_site,
                    source_mode=mode,
                    source_article_id="fr-good-detail",
                    source_url="https://example.com/france/news/fr-good-detail",
                    title_ja="Good detail article",
                    published_at=timezone.now(),
                ),
            ]

        def fetch_detail(self, source_url):
            if source_url.endswith("/fr-bad-detail"):
                raise ValueError("empty detail body")
            return super().fetch_detail(source_url)

    class FakePartialQueryFailureFranceAdapter(FakeAcceptedFranceAdapter):
        def fetch_listing(self, mode, page_or_month):
            stubs = super().fetch_listing(mode, page_or_month)
            self.last_listing_query_errors = [{"query": "ParisLongchamp", "error": "503 Server Error"}]
            return stubs

    def test_france_source_probe_reports_accepted_result_and_remains_read_only(self):
        from stable.management.commands import probe_international_news_sources as probe_command

        before = {
            "articles": NewsArticle.objects.count(),
            "crawl_jobs": CrawlJob.objects.count(),
            "sources": NewsSource.objects.count(),
        }
        out = StringIO()
        adapters = {**probe_command.INTERNATIONAL_ADAPTERS, "fake_france_accepted": self.FakeAcceptedFranceAdapter}

        with patch.object(probe_command, "INTERNATIONAL_ADAPTERS", adapters):
            call_command(
                "probe_international_news_sources",
                "--source",
                "fake_france_accepted",
                "--json",
                stdout=out,
            )

        payload = json.loads(out.getvalue())
        after = {
            "articles": NewsArticle.objects.count(),
            "crawl_jobs": CrawlJob.objects.count(),
            "sources": NewsSource.objects.count(),
        }
        self.assertEqual(before, after)
        self.assertEqual(payload[0]["source"], "fake_france_accepted")
        self.assertEqual(payload[0]["region"], RacingRegion.FRANCE)
        self.assertEqual(payload[0]["source_language"], SourceLanguage.ENGLISH)
        self.assertEqual(payload[0]["status"], "accepted")
        self.assertEqual(payload[0]["http_status"], 200)
        self.assertEqual(payload[0]["final_url"], "https://example.com/france/news?page=1")
        self.assertGreaterEqual(payload[0]["parse_quality"]["list_count"], 1)
        self.assertGreaterEqual(payload[0]["parse_quality"]["detail_body_length"], 80)
        self.assertTrue(payload[0]["articles"][0]["published_at_verified"])
        self.assertIn("published_at_evidence", payload[0]["articles"][0])

    def test_france_source_probe_marks_access_limited_candidate_deferred(self):
        from stable.management.commands import probe_international_news_sources as probe_command

        out = StringIO()
        adapters = {**probe_command.INTERNATIONAL_ADAPTERS, "fake_france_blocked": self.FakeBlockedFranceAdapter}

        with patch.object(probe_command, "INTERNATIONAL_ADAPTERS", adapters):
            call_command(
                "probe_international_news_sources",
                "--source",
                "fake_france_blocked",
                "--json",
                stdout=out,
            )

        payload = json.loads(out.getvalue())
        self.assertEqual(payload[0]["status"], "deferred")
        self.assertEqual(payload[0]["deferred_reason"], "access_limited")
        self.assertEqual(payload[0]["http_status"], 403)
        self.assertEqual(payload[0]["final_url"], "https://example.com/france/news/challenge")
        self.assertIn("403", payload[0]["error"])

    def test_france_source_probe_skips_single_detail_error_and_keeps_sampling(self):
        from stable.management.commands import probe_international_news_sources as probe_command

        out = StringIO()
        adapters = {
            **probe_command.INTERNATIONAL_ADAPTERS,
            "fake_france_partial_detail_failure": self.FakePartialDetailFailureFranceAdapter,
        }

        with patch.object(probe_command, "INTERNATIONAL_ADAPTERS", adapters):
            call_command(
                "probe_international_news_sources",
                "--source",
                "fake_france_partial_detail_failure",
                "--json",
                stdout=out,
            )

        payload = json.loads(out.getvalue())
        self.assertEqual(payload[0]["status"], "accepted")
        self.assertEqual(payload[0]["deferred_reason"], "")
        self.assertEqual(payload[0]["parse_quality"]["list_count"], 2)
        self.assertEqual(payload[0]["parse_quality"]["detail_sample_count"], 1)
        self.assertEqual(payload[0]["parse_quality"]["detail_error_count"], 1)
        self.assertEqual(len(payload[0]["articles"]), 1)
        self.assertEqual(payload[0]["sample_errors"][0]["url"], "https://example.com/france/news/fr-bad-detail")
        self.assertIn("empty detail body", payload[0]["sample_errors"][0]["error"])

    def test_france_source_probe_reports_partial_query_errors(self):
        from stable.management.commands import probe_international_news_sources as probe_command

        out = StringIO()
        adapters = {
            **probe_command.INTERNATIONAL_ADAPTERS,
            "fake_france_partial_query_failure": self.FakePartialQueryFailureFranceAdapter,
        }

        with patch.object(probe_command, "INTERNATIONAL_ADAPTERS", adapters):
            call_command(
                "probe_international_news_sources",
                "--source",
                "fake_france_partial_query_failure",
                "--json",
                stdout=out,
            )

        payload = json.loads(out.getvalue())
        self.assertEqual(payload[0]["status"], "accepted")
        self.assertEqual(payload[0]["query_errors"], [{"query": "ParisLongchamp", "error": "503 Server Error"}])

    @override_settings(MULTIREGION_SUPPORTED_PRODUCTION_SOURCE_LANGUAGES=["ja", "en", "zh-hant"])
    def test_sync_builtin_sources_does_not_production_approve_unsupported_french_source(self):
        from stable.services import sources as source_service

        french_definition = {
            "name": "France French candidate",
            "homepage_url": "https://example.com/fr/",
            "feed_url": "https://example.com/fr/news",
            "source_type": "builtin",
            "language": SourceLanguage.FRENCH,
            "racing_region": RacingRegion.FRANCE,
            "source_language": SourceLanguage.FRENCH,
            "source_kind": "news",
            "adapter_key": "fake_france_french",
            "source_site": SourceSite.AT_THE_RACES,
            "source_mode": SourceMode.OFFICIAL,
            "enabled": True,
            "production_approved": True,
            "crawl_interval_minutes": 15,
            "notes": "French-only candidate.",
            "priority": 80,
        }

        with patch.object(source_service, "BUILTIN_SOURCE_DEFINITIONS", [french_definition]):
            synced = source_service.sync_builtin_sources()

        source = synced[0]
        self.assertEqual(source.source_language, SourceLanguage.FRENCH)
        self.assertTrue(source.enabled)
        self.assertFalse(source.production_approved)
        self.assertIn("source_language_not_supported", source.notes)

    def test_france_audit_distinguishes_no_new_parse_failure_and_gate_blocked(self):
        from stable.services.multiregion import summarize_multiregion_news_production

        no_new = NewsSource.objects.create(
            name="France no new",
            homepage_url="https://example.com/no-new",
            feed_url="https://example.com/no-new/feed",
            racing_region=RacingRegion.FRANCE,
            source_language=SourceLanguage.ENGLISH,
            adapter_key="fake_no_new",
            source_site=SourceSite.FRANCE_GALOP_NEWS,
            source_mode=SourceMode.OFFICIAL,
            enabled=True,
            production_approved=True,
            last_crawl_status=TaskStatus.SUCCESS,
            last_crawl_message="成功，新增 0，重复 12",
        )
        parse_failed = NewsSource.objects.create(
            name="France parse failed",
            homepage_url="https://example.com/parse",
            feed_url="https://example.com/parse/feed",
            racing_region=RacingRegion.FRANCE,
            source_language=SourceLanguage.ENGLISH,
            adapter_key="fake_parse_failed",
            source_site=SourceSite.TDN_FRANCE,
            source_mode=SourceMode.LATEST,
            enabled=True,
            production_approved=True,
            last_crawl_status=TaskStatus.FAILED,
            last_crawl_message="parse failed: empty detail body",
        )
        blocked_article = NewsArticle.objects.create(
            source_site=SourceSite.TDN_FRANCE,
            source_mode=SourceMode.LATEST,
            source_config=no_new,
            source_article_id="fr-gate-blocked",
            source_url="https://example.com/fr-gate-blocked",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.FRANCE,
            title_ja="French racing blocked",
            body_ja_raw="French racing body. " * 20,
            body_ja_normalized="French racing body. " * 20,
            translated_title_zh="法国新闻",
            translated_body_zh="法国新闻正文。" * 20,
            published_at=timezone.now(),
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            gate_issues=[
                {
                    "code": "core_term_missing",
                    "severity": "blocker",
                    "payload": {"source_ja": "Prix de Diane", "term_region": RacingRegion.FRANCE},
                }
            ],
        )

        summary = summarize_multiregion_news_production()
        france = summary["regions"][RacingRegion.FRANCE]

        self.assertEqual(france["sources"]["success_no_new"], 1)
        self.assertEqual(france["sources"]["failed"], 1)
        self.assertIn(parse_failed.id, france["sources"]["parse_failed_source_ids"])
        self.assertEqual(france["articles"]["automation"][AutomationStatus.MANUAL_REVIEW_REQUIRED], 1)
        self.assertEqual(france["articles"]["gate_blockers"]["core_term_missing"], 1)
        self.assertEqual(france["articles"]["gate_blocker_examples"][0]["article_id"], blocked_article.id)


class ProductionWindowModelTests(TestCase):
    def _article(self, **overrides):
        payload = {
            "source_site": SourceSite.HKJC_NEWS,
            "source_mode": SourceMode.LATEST,
            "source_article_id": overrides.pop("source_article_id", "window-article"),
            "racing_region": RacingRegion.HONG_KONG,
            "source_language": SourceLanguage.ENGLISH,
            "title_ja": "Window article",
            "body_ja_raw": "Window body. " * 20,
            "body_ja_normalized": "Window body. " * 20,
            "published_at": timezone.now(),
            "source_url": "https://example.com/window-article",
        }
        payload.update(overrides)
        return NewsArticle.objects.create(**payload)

    def test_production_window_unique_scope_per_kind_and_start(self):
        window_start = timezone.now().replace(second=0, microsecond=0)
        ProductionWindow.objects.create(
            kind=ProductionWindowKind.PUBLISH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            scope_key="region:hong_kong",
            window_start=window_start,
            window_end=window_start + timedelta(minutes=15),
            status=ProductionWindowStatus.PENDING,
        )

        with self.assertRaises(IntegrityError):
            ProductionWindow.objects.create(
                kind=ProductionWindowKind.PUBLISH,
                mode=ProductionWindowMode.DAILY,
                racing_region=RacingRegion.HONG_KONG,
                scope_key="region:hong_kong",
                window_start=window_start,
                window_end=window_start + timedelta(minutes=15),
                status=ProductionWindowStatus.PENDING,
            )

    def test_window_decisions_record_article_and_target_reasons(self):
        article = self._article()
        target = PushTarget.objects.create(name="HK group", group_id="12345", allowed_regions=[RacingRegion.HONG_KONG])
        window_start = timezone.now().replace(second=0, microsecond=0)
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.QQ_PUSH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            target=target,
            scope_key="region:hong_kong:target:12345",
            window_start=window_start,
            window_end=window_start + timedelta(minutes=15),
        )

        candidate = WindowCandidateDecision.objects.create(
            window=window,
            article=article,
            status=WindowDecisionStatus.SELECTED,
            reason="high_value",
            score=92,
            rank=1,
            payload={"signals": ["ranked"]},
        )
        target_decision = WindowTargetDecision.objects.create(
            window=window,
            article=article,
            target=target,
            decision_key=f"target:{target.pk}:article:{article.pk}",
            status=WindowDecisionStatus.SKIPPED,
            reason="group_hour_quota_exhausted",
            payload={"limit": 12, "used": 12},
        )

        self.assertEqual(candidate.payload["signals"], ["ranked"])
        self.assertEqual(target_decision.reason, "group_hour_quota_exhausted")

    def test_quota_ledger_unique_scope_and_window(self):
        window_start = timezone.now().replace(minute=0, second=0, microsecond=0)
        QuotaLedger.objects.create(
            kind=QuotaLedgerKind.QQ_PUSH,
            scope=QuotaLedgerScope.GROUP_HOUR,
            scope_key="group:12345",
            window_start=window_start,
            limit=12,
            used=3,
        )

        with self.assertRaises(IntegrityError):
            QuotaLedger.objects.create(
                kind=QuotaLedgerKind.QQ_PUSH,
                scope=QuotaLedgerScope.GROUP_HOUR,
                scope_key="group:12345",
                window_start=window_start,
                limit=12,
                used=1,
            )

    def test_major_race_event_unique_by_name_year_region_and_grade(self):
        race_date = timezone.localdate()
        MajorRaceEvent.objects.create(
            name="皋月赏",
            normalized_name="皋月赏",
            year=2026,
            racing_region=RacingRegion.JAPAN,
            race_grade=RaceGrade.G1,
            timezone_name="Asia/Tokyo",
            local_date=race_date,
        )

        with self.assertRaises(IntegrityError):
            MajorRaceEvent.objects.create(
                name="皐月賞",
                normalized_name="皋月赏",
                year=2026,
                racing_region=RacingRegion.JAPAN,
                race_grade=RaceGrade.G1,
                timezone_name="Asia/Tokyo",
                local_date=race_date,
            )

    def test_major_race_event_admin_recalculates_boost_window_on_save(self):
        from django.contrib import admin as django_admin

        from stable.admin import MajorRaceEventAdmin

        race_date = datetime(2026, 4, 19, tzinfo=dt_timezone.utc).date()
        event = MajorRaceEvent(
            name="皋月赏",
            normalized_name="皋月赏",
            year=2026,
            racing_region=RacingRegion.JAPAN,
            race_grade=RaceGrade.G1,
            timezone_name="Asia/Tokyo",
            local_date=race_date,
            local_start_time=datetime(2026, 4, 19, 15, 40).time(),
        )
        admin_instance = MajorRaceEventAdmin(MajorRaceEvent, django_admin.site)

        admin_instance.save_model(None, event, None, False)
        event.refresh_from_db()
        first_boost_start = event.boost_start_at
        self.assertEqual(first_boost_start, datetime(2026, 4, 19, 3, 40, tzinfo=dt_timezone.utc))

        event.local_start_time = datetime(2026, 4, 19, 15, 45).time()
        admin_instance.save_model(None, event, None, True)

        event.refresh_from_db()
        self.assertEqual(event.boost_start_at, datetime(2026, 4, 19, 3, 45, tzinfo=dt_timezone.utc))
        self.assertNotEqual(event.boost_start_at, first_boost_start)

    def test_news_source_production_runtime_fields(self):
        backoff_until = timezone.now() + timedelta(minutes=30)
        source = NewsSource.objects.create(
            name="HK production source",
            homepage_url="https://example.com",
            feed_url="https://example.com/feed",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            adapter_key="hkjc_news",
            source_site=SourceSite.HKJC_NEWS,
            source_mode=SourceMode.LATEST,
            enabled=True,
            production_approved=True,
            effective_crawl_interval_minutes=15,
            backoff_until=backoff_until,
            manual_pause_reason="manual pause",
            failure_streak=3,
            success_streak=0,
            last_error_category=SourceErrorCategory.HTTP_429,
            allow_event_boost=False,
        )

        source.refresh_from_db()
        self.assertTrue(source.production_approved)
        self.assertEqual(source.effective_crawl_interval_minutes, 15)
        self.assertEqual(source.failure_streak, 3)
        self.assertEqual(source.last_error_category, SourceErrorCategory.HTTP_429)
        self.assertFalse(source.allow_event_boost)


class ProductionWindowServiceTests(TestCase):
    def _source(self, **overrides):
        payload = {
            "name": overrides.pop("name", "HK production source"),
            "homepage_url": "https://example.com",
            "feed_url": "https://example.com/feed",
            "racing_region": RacingRegion.HONG_KONG,
            "source_language": SourceLanguage.ENGLISH,
            "adapter_key": "hkjc_news",
            "source_site": SourceSite.HKJC_NEWS,
            "source_mode": SourceMode.LATEST,
            "enabled": True,
            "production_approved": True,
            "effective_crawl_interval_minutes": 15,
        }
        payload.update(overrides)
        return NewsSource.objects.create(**payload)

    def test_window_bounds_floor_to_daily_and_major_race_intervals(self):
        from stable.services.production_windows import current_window_bounds

        now = datetime(2026, 7, 1, 10, 17, 33, tzinfo=dt_timezone.utc)

        daily = current_window_bounds(now, minutes=15)
        major = current_window_bounds(now, minutes=5)

        self.assertEqual(daily.start, datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc))
        self.assertEqual(daily.end, datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc))
        self.assertEqual(major.start, datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc))
        self.assertEqual(major.end, datetime(2026, 7, 1, 10, 20, tzinfo=dt_timezone.utc))

    def test_lookback_windows_are_capped_to_three_hours(self):
        from stable.services.production_windows import due_window_starts

        now = datetime(2026, 7, 1, 12, 0, tzinfo=dt_timezone.utc)
        starts = due_window_starts(
            last_window_start=datetime(2026, 7, 1, 1, 0, tzinfo=dt_timezone.utc),
            now=now,
            minutes=15,
            lookback_hours=3,
        )

        self.assertEqual(starts[0], datetime(2026, 7, 1, 9, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(starts[-1], datetime(2026, 7, 1, 11, 45, tzinfo=dt_timezone.utc))
        self.assertEqual(len(starts), 12)

    def test_claim_window_respects_active_lease_and_reclaims_expired_lease(self):
        from stable.services.production_windows import claim_window

        window_start = datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc)
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.PUBLISH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            scope_key="region:hong_kong",
            window_start=window_start,
            window_end=window_start + timedelta(minutes=15),
        )

        first = claim_window(window, now=window_start, lease_minutes=30)
        second = claim_window(window, now=window_start + timedelta(minutes=5), lease_minutes=30)
        third = claim_window(window, now=window_start + timedelta(minutes=31), lease_minutes=30)

        window.refresh_from_db()
        self.assertTrue(first.claimed)
        self.assertFalse(second.claimed)
        self.assertEqual(second.reason, "lease_active")
        self.assertTrue(third.claimed)
        self.assertEqual(window.attempt_count, 2)

    def test_major_race_window_uses_local_time_and_overlaps_by_region(self):
        from stable.services.production_windows import active_major_race_window, update_major_race_boost_window

        timed = MajorRaceEvent.objects.create(
            name="日本德比",
            normalized_name="日本德比",
            year=2026,
            racing_region=RacingRegion.JAPAN,
            race_grade=RaceGrade.G1,
            timezone_name="Asia/Tokyo",
            local_date=datetime(2026, 5, 31).date(),
            local_start_time=datetime(2026, 5, 31, 15, 40).time(),
        )
        date_level = MajorRaceEvent.objects.create(
            name="女皇杯",
            normalized_name="女皇杯",
            year=2026,
            racing_region=RacingRegion.HONG_KONG,
            race_grade=RaceGrade.G1,
            timezone_name="Asia/Hong_Kong",
            local_date=datetime(2026, 4, 26).date(),
        )
        update_major_race_boost_window(timed)
        update_major_race_boost_window(date_level)

        japan_window = active_major_race_window(
            RacingRegion.JAPAN,
            now=datetime(2026, 5, 31, 5, 0, tzinfo=dt_timezone.utc),
        )
        hk_window = active_major_race_window(
            RacingRegion.HONG_KONG,
            now=datetime(2026, 4, 26, 10, 0, tzinfo=dt_timezone.utc),
        )
        uk_window = active_major_race_window(
            RacingRegion.UNITED_KINGDOM,
            now=datetime(2026, 5, 31, 5, 0, tzinfo=dt_timezone.utc),
        )

        self.assertIsNotNone(japan_window)
        self.assertIsNotNone(hk_window)
        self.assertIsNone(uk_window)
        self.assertEqual(japan_window.events[0].name, "日本德比")
        self.assertEqual(hk_window.events[0].name, "女皇杯")

    def test_import_major_race_events_csv_upserts_by_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "major-races.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "name,normalized_name,year,racing_region,race_grade,timezone_name,local_date,local_start_time,is_active,aliases,notes",
                        "皋月赏,皋月赏,2026,japan,G1,Asia/Tokyo,2026-04-19,15:40,true,皐月賞|Satsuki Sho,first",
                    ]
                ),
                encoding="utf-8",
            )
            call_command("import_major_race_events", "--csv", str(csv_path))
            csv_path.write_text(
                "\n".join(
                    [
                        "name,normalized_name,year,racing_region,race_grade,timezone_name,local_date,local_start_time,is_active,aliases,notes",
                        "皋月赏,皋月赏,2026,japan,G1,Asia/Tokyo,2026-04-19,15:45,true,皐月賞|Satsuki Sho,updated",
                    ]
                ),
                encoding="utf-8",
            )
            call_command("import_major_race_events", "--csv", str(csv_path))

        event = MajorRaceEvent.objects.get(normalized_name="皋月赏", year=2026, racing_region=RacingRegion.JAPAN)
        self.assertEqual(MajorRaceEvent.objects.count(), 1)
        self.assertEqual(event.local_start_time.strftime("%H:%M"), "15:45")
        self.assertEqual(event.notes, "updated")
        self.assertIsNotNone(event.boost_start_at)

    def test_select_production_sources_filters_approval_backoff_and_pause(self):
        from stable.services.production_windows import select_production_sources

        due = self._source(name="due", source_mode=SourceMode.LATEST)
        self._source(name="not approved", source_mode=SourceMode.OFFICIAL, production_approved=False)
        self._source(name="paused", source_mode=SourceMode.ACCESS, manual_pause_reason="manual")
        self._source(
            name="backoff",
            source_site=SourceSite.SCMP_RACING,
            source_mode=SourceMode.LATEST,
            backoff_until=timezone.now() + timedelta(hours=1),
        )

        selection = select_production_sources(
            now=timezone.now(),
            allowed_regions={RacingRegion.HONG_KONG},
        )

        self.assertEqual([item.source for item in selection.selected], [due])
        self.assertIn("production_not_approved", {item.reason for item in selection.skipped})
        self.assertIn("manual_pause", {item.reason for item in selection.skipped})
        self.assertIn("backoff_active", {item.reason for item in selection.skipped})

    def test_select_production_sources_skips_active_crawl_window(self):
        from stable.services.production_windows import select_production_sources

        source = self._source(name="running", source_mode=SourceMode.LATEST)
        now = datetime(2026, 7, 1, 10, 17, tzinfo=dt_timezone.utc)
        ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            source=source,
            scope_key=f"source:{source.id}",
            window_start=datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
            window_end=datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc),
            status=ProductionWindowStatus.RUNNING,
            lease_expires_at=now + timedelta(minutes=20),
        )

        selection = select_production_sources(now=now, allowed_regions={RacingRegion.HONG_KONG})

        self.assertEqual(selection.selected, [])
        self.assertIn("crawl_window_running", {item.reason for item in selection.skipped})

    @override_settings(MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES=15)
    def test_production_approved_sources_default_to_15_minute_due_interval(self):
        from stable.services.production_windows import select_production_sources

        now = datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc)
        due = self._source(
            name="due after default interval",
            source_mode=SourceMode.LATEST,
            crawl_interval_minutes=240,
            effective_crawl_interval_minutes=None,
            last_crawl_at=now - timedelta(minutes=20),
        )
        self._source(
            name="not due before default interval",
            source_site=SourceSite.SCMP_RACING,
            source_mode=SourceMode.LATEST,
            crawl_interval_minutes=240,
            effective_crawl_interval_minutes=None,
            last_crawl_at=now - timedelta(minutes=10),
        )

        selection = select_production_sources(now=now, allowed_regions={RacingRegion.HONG_KONG})

        self.assertEqual([item.source for item in selection.selected], [due])
        self.assertIn("not_due", {item.reason for item in selection.skipped})

    def test_source_error_backoff_and_recovery_update_runtime_fields(self):
        from stable.services.production_windows import record_source_crawl_result

        source = self._source()
        now = timezone.now()

        record_source_crawl_result(source, success=False, error_category=SourceErrorCategory.TIMEOUT, now=now)
        record_source_crawl_result(source, success=False, error_category=SourceErrorCategory.TIMEOUT, now=now + timedelta(minutes=1))
        record_source_crawl_result(source, success=False, error_category=SourceErrorCategory.HTTP_429, now=now + timedelta(minutes=2))
        source.refresh_from_db()
        self.assertEqual(source.failure_streak, 3)
        self.assertEqual(source.last_error_category, SourceErrorCategory.HTTP_429)
        self.assertIsNotNone(source.backoff_until)
        self.assertGreaterEqual(source.effective_crawl_interval_minutes, 60)

        for offset in range(3, 6):
            record_source_crawl_result(source, success=True, now=now + timedelta(minutes=offset))
        source.refresh_from_db()
        self.assertEqual(source.failure_streak, 0)
        self.assertEqual(source.success_streak, 3)
        self.assertIsNone(source.backoff_until)
        self.assertEqual(source.effective_crawl_interval_minutes, 15)

    def test_classify_source_error_maps_common_failure_shapes(self):
        from stable.services.production_windows import classify_source_error

        self.assertEqual(classify_source_error(status_code=403), SourceErrorCategory.HTTP_403)
        self.assertEqual(classify_source_error(status_code=429), SourceErrorCategory.HTTP_429)
        self.assertEqual(classify_source_error(status_code=503), SourceErrorCategory.SERVER_ERROR)
        self.assertEqual(classify_source_error(message="request timeout"), SourceErrorCategory.TIMEOUT)
        self.assertEqual(classify_source_error(message="captcha required"), SourceErrorCategory.CAPTCHA_OR_BLOCKED)
        self.assertEqual(classify_source_error(message="parse failed"), SourceErrorCategory.PARSE_ERROR)
        self.assertEqual(classify_source_error(empty_success=True), SourceErrorCategory.EMPTY_SUCCESS)

    def test_builtin_source_sync_preserves_manual_production_runtime_fields(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.HKJC_NEWS, source_mode=SourceMode.LATEST)
        source.enabled = True
        source.production_approved = True
        source.effective_crawl_interval_minutes = 45
        source.backoff_until = timezone.now() + timedelta(hours=2)
        source.manual_pause_reason = "operator pause"
        source.allow_event_boost = False
        source.save(
            update_fields=[
                "enabled",
                "production_approved",
                "effective_crawl_interval_minutes",
                "backoff_until",
                "manual_pause_reason",
                "allow_event_boost",
                "updated_at",
            ]
        )

        sync_builtin_sources()

        source.refresh_from_db()
        self.assertTrue(source.enabled)
        self.assertTrue(source.production_approved)
        self.assertEqual(source.effective_crawl_interval_minutes, 45)
        self.assertIsNotNone(source.backoff_until)
        self.assertEqual(source.manual_pause_reason, "operator pause")
        self.assertFalse(source.allow_event_boost)

    def test_crawl_news_source_task_updates_window_after_real_success(self):
        from stable.tasks import crawl_news_source_task

        source = self._source()
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            source=source,
            scope_key=f"source:{source.id}",
            window_start=datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
            window_end=datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc),
            status=ProductionWindowStatus.RUNNING,
        )

        with patch("stable.tasks._crawl_international_source", return_value={"new_count": 2, "seen_count": 1, "crawl_job_id": 123}):
            result = crawl_news_source_task.run(source.id, window.id)

        window.refresh_from_db()
        self.assertEqual(result["new_count"], 2)
        self.assertEqual(window.status, ProductionWindowStatus.SUCCEEDED)
        self.assertEqual(window.reason_summary, "completed")
        self.assertEqual(window.result_payload["new_count"], 2)

    def test_crawl_news_source_task_classifies_http_status_failures(self):
        from stable.tasks import crawl_news_source_task

        source = self._source()
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            source=source,
            scope_key=f"source:{source.id}",
            window_start=datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
            window_end=datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc),
            status=ProductionWindowStatus.RUNNING,
        )
        response = Mock(status_code=429)
        error = requests.HTTPError("rate limited")
        error.response = response

        with patch("stable.tasks._crawl_international_source", side_effect=error):
            with self.assertRaises(requests.HTTPError):
                crawl_news_source_task.run(source.id, window.id)

        source.refresh_from_db()
        window.refresh_from_db()
        self.assertEqual(source.last_error_category, SourceErrorCategory.HTTP_429)
        self.assertEqual(window.status, ProductionWindowStatus.FAILED)
        self.assertEqual(window.reason_summary, "crawl_failed")
        self.assertEqual(window.result_payload["error_category"], SourceErrorCategory.HTTP_429)

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=False,
        MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED=True,
    )
    def test_crawl_production_sources_window_task_stays_disabled_by_default(self):
        from stable.tasks import crawl_production_sources_window_task

        source = self._source()
        result = crawl_production_sources_window_task.run()

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "disabled")
        self.assertEqual(ProductionWindow.objects.count(), 0)
        self.assertEqual(CrawlJob.objects.filter(source=source).count(), 0)

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES=15,
    )
    def test_crawl_production_sources_window_task_claims_source_windows(self):
        from stable.tasks import crawl_news_source_task, crawl_production_sources_window_task

        source = self._source()

        with patch("stable.tasks.dispatch_task", return_value={"queued": True}) as dispatch:
            result = crawl_production_sources_window_task.run(now_iso="2026-07-01T10:17:00+00:00")

        window = ProductionWindow.objects.get(kind=ProductionWindowKind.CRAWL, source=source)
        self.assertEqual(result["triggered_source_ids"], [source.id])
        self.assertEqual(window.status, ProductionWindowStatus.RUNNING)
        self.assertEqual(window.reason_summary, "dispatched")
        self.assertEqual(window.scope_key, f"source:{source.id}")
        self.assertEqual(window.window_start, datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc))
        dispatch.assert_called_once_with(crawl_news_source_task, source.id, window.id)

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES=15,
    )
    def test_crawl_window_serializes_async_dispatch_result(self):
        from stable.tasks import crawl_production_sources_window_task

        source = self._source()
        async_result = Mock()
        async_result.id = "queued-task-1"

        with patch("stable.tasks.dispatch_task", return_value=async_result):
            crawl_production_sources_window_task.run(now_iso="2026-07-01T10:17:00+00:00")

        window = ProductionWindow.objects.get(kind=ProductionWindowKind.CRAWL, source=source)
        self.assertEqual(window.status, ProductionWindowStatus.RUNNING)
        self.assertEqual(window.result_payload["dispatch_result"], {"task_id": "queued-task-1"})

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES=15,
    )
    def test_crawl_window_task_only_fetches_latest_missing_window(self):
        from stable.tasks import crawl_news_source_task, crawl_production_sources_window_task

        source = self._source(last_crawl_at=datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc))
        ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            source=source,
            scope_key=f"source:{source.id}",
            window_start=datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc),
            window_end=datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
            status=ProductionWindowStatus.SUCCEEDED,
        )

        with patch("stable.tasks.dispatch_task", return_value={"queued": True}) as dispatch:
            result = crawl_production_sources_window_task.run(now_iso="2026-07-01T10:47:00+00:00")

        starts = list(
            ProductionWindow.objects.filter(kind=ProductionWindowKind.CRAWL, source=source)
            .order_by("window_start")
            .values_list("window_start", flat=True)
        )
        self.assertEqual(
            starts,
            [
                datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc),
                datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
                datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc),
                datetime(2026, 7, 1, 10, 45, tzinfo=dt_timezone.utc),
            ],
        )
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(result["triggered_source_ids"], [source.id])
        latest = ProductionWindow.objects.get(kind=ProductionWindowKind.CRAWL, source=source, window_start=datetime(2026, 7, 1, 10, 45, tzinfo=dt_timezone.utc))
        coalesced = ProductionWindow.objects.filter(kind=ProductionWindowKind.CRAWL, source=source, reason_summary="coalesced_to_latest_crawl_window")
        self.assertEqual(latest.status, ProductionWindowStatus.RUNNING)
        self.assertEqual(coalesced.count(), 2)
        dispatch.assert_called_once_with(crawl_news_source_task, source.id, latest.id)

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES=15,
    )
    def test_crawl_window_task_coalesces_stale_running_windows(self):
        from stable.tasks import crawl_news_source_task, crawl_production_sources_window_task

        now = datetime(2026, 7, 1, 10, 47, tzinfo=dt_timezone.utc)
        source = self._source(last_crawl_at=datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc))
        ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            source=source,
            scope_key=f"source:{source.id}",
            window_start=datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc),
            window_end=datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
            status=ProductionWindowStatus.SUCCEEDED,
        )
        stale = ProductionWindow.objects.create(
            kind=ProductionWindowKind.CRAWL,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            source=source,
            scope_key=f"source:{source.id}",
            window_start=datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
            window_end=datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc),
            status=ProductionWindowStatus.RUNNING,
            lease_expires_at=now - timedelta(minutes=1),
        )

        with patch("stable.tasks.dispatch_task", return_value={"queued": True}) as dispatch:
            crawl_production_sources_window_task.run(now_iso=now.isoformat())

        stale.refresh_from_db()
        latest = ProductionWindow.objects.get(
            kind=ProductionWindowKind.CRAWL,
            source=source,
            window_start=datetime(2026, 7, 1, 10, 45, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(stale.status, ProductionWindowStatus.SKIPPED)
        self.assertEqual(stale.reason_summary, "coalesced_to_latest_crawl_window")
        dispatch.assert_called_once_with(crawl_news_source_task, source.id, latest.id)


class PublishWindowServiceTests(TestCase):
    def _article(self, **overrides):
        payload = {
            "source_site": SourceSite.HKJC_NEWS,
            "source_mode": SourceMode.LATEST,
            "source_article_id": overrides.pop("source_article_id", f"publish-{NewsArticle.objects.count()}"),
            "racing_region": RacingRegion.HONG_KONG,
            "source_language": SourceLanguage.ENGLISH,
            "title_ja": overrides.pop("title_ja", "Publish article"),
            "body_ja_raw": "Publish body. " * 20,
            "body_ja_normalized": "Publish body. " * 20,
            "translated_title_zh": overrides.pop("translated_title_zh", "发布文章"),
            "title_zh": overrides.pop("title_zh", "发布文章"),
            "translated_summary_zh": "摘要",
            "summary_zh": "摘要",
            "translated_body_zh": "正文。" * 30,
            "body_zh": "正文。" * 30,
            "published_at": timezone.now(),
            "source_url": overrides.pop("source_url", f"https://example.com/{NewsArticle.objects.count()}"),
            "review_mode": ReviewMode.AUTO,
            "automation_status": AutomationStatus.PUBLISH_READY,
            "score_total": overrides.pop("score_total", 80),
            "quality_score": 80,
            "rewrite_confidence": 80,
        }
        payload.update(overrides)
        return NewsArticle.objects.create(**payload)

    def _window(self):
        start = datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc)
        return ProductionWindow.objects.create(
            kind=ProductionWindowKind.PUBLISH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            scope_key="region:hong_kong",
            window_start=start,
            window_end=start + timedelta(minutes=15),
        )

    @override_settings(
        MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_PUBLISH_REGION_WINDOW_MAX=5,
        MULTIREGION_PUBLISH_REGION_WINDOW_MIN=1,
        MULTIREGION_PUBLISH_SOFT_FILL_MIN_SCORE=45,
        MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY=60,
    )
    def test_select_publish_candidates_dedupes_scores_and_records_reasons(self):
        from stable.services.publishing_windows import select_publish_candidates

        for score in [95, 90, 85, 80, 75, 70]:
            self._article(score_total=score, title_zh=f"新闻 {score}", source_article_id=f"a-{score}")
        duplicate = self._article(score_total=94, title_zh="新闻 95", source_article_id="duplicate")
        blocked = self._article(score_total=100, title_zh="", translated_title_zh="", title_ja="", source_article_id="blocked")
        window = self._window()

        result = select_publish_candidates(RacingRegion.HONG_KONG, window=window, now=timezone.now())

        self.assertEqual(len(result.selected), 5)
        self.assertNotIn(duplicate, result.selected)
        reasons = set(WindowCandidateDecision.objects.filter(window=window).values_list("reason", flat=True))
        self.assertIn("dedupe_loser", reasons)
        self.assertIn("hard_gate_blocked", reasons)
        self.assertIn("region_window_limit", reasons)
        self.assertEqual(blocked.workflow_status, WorkflowStatus.PENDING_TRANSLATION)

    @override_settings(
        MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_PUBLISH_REGION_WINDOW_MAX=5,
        MULTIREGION_PUBLISH_REGION_WINDOW_MIN=1,
        MULTIREGION_PUBLISH_SOFT_FILL_MIN_SCORE=45,
        MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY=60,
    )
    def test_soft_fill_selects_one_web_only_article_above_min_score(self):
        from stable.services.publishing_windows import select_publish_candidates

        article = self._article(score_total=45, source_article_id="soft-fill")
        window = self._window()

        result = select_publish_candidates(RacingRegion.HONG_KONG, window=window, now=timezone.now())

        self.assertEqual(result.selected, [article])
        article.refresh_from_db()
        self.assertTrue(article.decision_reason["region_minimum_fill"])
        self.assertTrue(article.decision_reason["disable_auto_qq"])

    @override_settings(
        MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_PUBLISH_REGION_WINDOW_MAX=5,
        MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY=0,
    )
    def test_publish_quota_blocks_selection_with_structured_reason(self):
        from stable.services.publishing_windows import select_publish_candidates

        self._article(score_total=95)
        window = self._window()

        result = select_publish_candidates(RacingRegion.HONG_KONG, window=window, now=timezone.now())

        self.assertEqual(result.selected, [])
        self.assertIn("site_hour_quota_exhausted", result.zero_reasons)
        self.assertTrue(
            WindowCandidateDecision.objects.filter(window=window, reason="site_hour_quota_exhausted").exists()
        )

    @override_settings(
        MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_PUBLISH_REGION_WINDOW_MAX=5,
        MULTIREGION_PUBLISH_REGION_WINDOW_MIN=1,
        MULTIREGION_PUBLISH_SOFT_FILL_MIN_SCORE=45,
        MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY=60,
        MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS=3,
    )
    def test_ranked_revived_article_enters_publish_window_after_first_seen_lookback(self):
        from stable.services.publishing_windows import select_publish_candidates

        now = datetime(2026, 7, 1, 10, 20, tzinfo=dt_timezone.utc)
        article = self._article(
            source_article_id="ranked-revived-candidate",
            first_seen_at=now - timedelta(hours=6),
            score_total=90,
            decision_reason={
                "ranked_revival": {
                    "revived_at": (now - timedelta(minutes=20)).isoformat(),
                    "source_site": SourceSite.HKJC_NEWS,
                    "source_mode": SourceMode.ACCESS,
                }
            },
        )
        article.ranked_revived_at = now - timedelta(minutes=20)
        article.save(update_fields=["ranked_revived_at", "updated_at"])
        window = self._window()

        result = select_publish_candidates(RacingRegion.HONG_KONG, window=window, now=now)

        self.assertEqual(result.selected, [article])
        decision = WindowCandidateDecision.objects.get(window=window, article=article)
        self.assertEqual(decision.status, WindowDecisionStatus.SELECTED)
        self.assertTrue(decision.payload["ranked_revival"])
        self.assertEqual(decision.payload["ranked_revived_at"], article.ranked_revived_at.isoformat())
        self.assertEqual(decision.payload["ranked_revival_source_mode"], SourceMode.ACCESS)

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_PUBLISH_REGION_WINDOW_MAX=5,
        MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY=60,
        QQ_PUSH_ENABLED=False,
    )
    def test_publish_region_window_task_publishes_selected_articles(self):
        from stable.tasks import publish_region_window_task

        article = self._article(score_total=95, source_article_id="publish-task")

        result = publish_region_window_task.run(RacingRegion.HONG_KONG, now_iso="2026-07-01T10:17:00+00:00")

        article.refresh_from_db()
        window = ProductionWindow.objects.get(kind=ProductionWindowKind.PUBLISH, racing_region=RacingRegion.HONG_KONG)
        self.assertEqual(result["published_article_ids"], [article.id])
        self.assertEqual(window.status, ProductionWindowStatus.SUCCEEDED)
        self.assertEqual(article.workflow_status, WorkflowStatus.PUBLISHED)

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_PUBLISH_REGION_WINDOW_MAX=5,
        MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY=60,
        QQ_PUSH_ENABLED=False,
    )
    def test_publish_region_window_task_backfills_missing_recent_windows(self):
        from stable.services.publishing_windows import PublishSelectionResult
        from stable.tasks import publish_region_window_task

        ProductionWindow.objects.create(
            kind=ProductionWindowKind.PUBLISH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            scope_key="region:hong_kong",
            window_start=datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc),
            window_end=datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
            status=ProductionWindowStatus.SUCCEEDED,
        )

        with patch("stable.tasks.select_publish_candidates", return_value=PublishSelectionResult(selected=[])) as select:
            result = publish_region_window_task.run(RacingRegion.HONG_KONG, now_iso="2026-07-01T10:47:00+00:00")

        starts = list(
            ProductionWindow.objects.filter(kind=ProductionWindowKind.PUBLISH, racing_region=RacingRegion.HONG_KONG)
            .order_by("window_start")
            .values_list("window_start", flat=True)
        )
        self.assertEqual(
            starts,
            [
                datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc),
                datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
                datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc),
                datetime(2026, 7, 1, 10, 45, tzinfo=dt_timezone.utc),
            ],
        )
        self.assertEqual(select.call_count, 3)
        expected_window_ids = list(
            ProductionWindow.objects.exclude(window_start=datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc))
            .order_by("window_start")
            .values_list("id", flat=True)
        )
        self.assertEqual(result["window_ids"], expected_window_ids)

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED=True,
    )
    def test_auto_publish_batch_delegates_when_new_windows_are_enabled(self):
        from stable.tasks import auto_publish_batch_task

        result = auto_publish_batch_task.run()

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "multiregion_windows_enabled")


class QQWindowServiceTests(TestCase):
    def _target(self, **overrides):
        payload = {
            "name": "HK QQ",
            "group_id": overrides.pop("group_id", f"group-{PushTarget.objects.count()}"),
            "allowed_regions": [RacingRegion.HONG_KONG],
            "is_active": True,
            "push_scope": "high_value_only",
            "importance_strategy": "ranked",
        }
        payload.update(overrides)
        return PushTarget.objects.create(**payload)

    def _article(self, **overrides):
        payload = {
            "source_site": SourceSite.SKY_SPORTS_RACING,
            "source_mode": SourceMode.ACCESS,
            "source_article_id": overrides.pop("source_article_id", f"qq-{NewsArticle.objects.count()}"),
            "racing_region": RacingRegion.HONG_KONG,
            "source_language": SourceLanguage.ENGLISH,
            "title_ja": "QQ article",
            "body_ja_raw": "QQ body. " * 20,
            "body_ja_normalized": "QQ body. " * 20,
            "title_zh": "QQ 新闻",
            "summary_zh": "摘要",
            "body_zh": "正文。" * 30,
            "published_at": timezone.now(),
            "source_url": overrides.pop("source_url", f"https://example.com/qq-{NewsArticle.objects.count()}"),
            "workflow_status": WorkflowStatus.PUBLISHED,
            "published_to_web_at": timezone.now(),
            "published_by_mode": PublishedByMode.AUTO,
            "auto_publish_at": timezone.now(),
            "score_total": 90,
        }
        payload.update(overrides)
        return NewsArticle.objects.create(**payload)

    def _window(self):
        start = datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc)
        target = self._target()
        return ProductionWindow.objects.create(
            kind=ProductionWindowKind.QQ_PUSH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            target=target,
            scope_key=f"region:hong_kong:target:{target.id}",
            window_start=start,
            window_end=start + timedelta(minutes=15),
        ), target

    @override_settings(
        MULTIREGION_QQ_REGION_WINDOW_MAX=3,
        MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY=12,
        MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY=40,
        SITE_URL="https://umafans.run",
    )
    def test_qq_window_limits_region_to_three_high_value_articles(self):
        from stable.services.qq_windows import select_qq_window_deliveries

        window, target = self._window()
        articles = [self._article(source_article_id=f"ranked-{index}", title_zh=f"重点 {index}") for index in range(4)]

        result = select_qq_window_deliveries(RacingRegion.HONG_KONG, window=window, targets=[target], now=timezone.now())

        self.assertEqual(len(result.deliveries), 3)
        self.assertTrue({delivery.article_id for delivery in result.deliveries}.issubset({article.id for article in articles}))
        self.assertTrue(
            WindowTargetDecision.objects.filter(window=window, reason="region_window_limit").exists()
        )

    @override_settings(
        MULTIREGION_QQ_REGION_WINDOW_MAX=3,
        MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY=12,
        MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY=40,
    )
    def test_qq_window_skips_soft_fill_articles(self):
        from stable.services.qq_windows import select_qq_window_deliveries

        window, target = self._window()
        self._article(source_article_id="soft", decision_reason={"disable_auto_qq": True, "region_minimum_fill": True})

        result = select_qq_window_deliveries(RacingRegion.HONG_KONG, window=window, targets=[target], now=timezone.now())

        self.assertEqual(result.deliveries, [])
        self.assertIn("soft_fill_no_auto_qq", result.zero_reasons)
        self.assertTrue(
            WindowTargetDecision.objects.filter(window=window, reason="soft_fill_no_auto_qq").exists()
        )

    @override_settings(
        MULTIREGION_QQ_REGION_WINDOW_MAX=3,
        MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY=0,
        MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY=40,
    )
    def test_qq_window_records_group_quota_zero_reason(self):
        from stable.services.qq_windows import select_qq_window_deliveries

        window, target = self._window()
        self._article(source_article_id="quota")

        result = select_qq_window_deliveries(RacingRegion.HONG_KONG, window=window, targets=[target], now=timezone.now())

        self.assertEqual(result.deliveries, [])
        self.assertIn("group_hour_quota_exhausted", result.zero_reasons)
        self.assertTrue(
            WindowTargetDecision.objects.filter(window=window, reason="group_hour_quota_exhausted").exists()
        )

    @override_settings(
        MULTIREGION_QQ_REGION_WINDOW_MAX=3,
        MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY=12,
        MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY=0,
    )
    def test_qq_site_quota_failure_does_not_consume_group_quota(self):
        from stable.services.qq_windows import select_qq_window_deliveries

        window, target = self._window()
        self._article(source_article_id="site-quota")

        result = select_qq_window_deliveries(RacingRegion.HONG_KONG, window=window, targets=[target], now=timezone.now())

        self.assertEqual(result.deliveries, [])
        self.assertIn("site_hour_quota_exhausted", result.zero_reasons)
        group_ledger = QuotaLedger.objects.get(
            kind=QuotaLedgerKind.QQ_PUSH,
            scope=QuotaLedgerScope.GROUP_HOUR,
            scope_key=f"group:{target.group_id}",
        )
        self.assertEqual(group_ledger.used, 0)

    @override_settings(
        MULTIREGION_QQ_REGION_WINDOW_MAX=3,
        MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY=12,
        MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY=40,
    )
    def test_qq_existing_delivery_is_skipped_before_quota_reservation(self):
        from stable.services.qq_windows import select_qq_window_deliveries

        window, target = self._window()
        article = self._article(source_article_id="already-queued")
        QQPushDelivery.objects.create(article=article, target=target, status=QQPushDeliveryStatus.PENDING)

        result = select_qq_window_deliveries(RacingRegion.HONG_KONG, window=window, targets=[target], now=timezone.now())

        self.assertEqual(result.deliveries, [])
        self.assertIn("already_queued", result.zero_reasons)
        self.assertFalse(QuotaLedger.objects.filter(kind=QuotaLedgerKind.QQ_PUSH).exists())
        self.assertTrue(WindowTargetDecision.objects.filter(window=window, reason="already_queued").exists())

    @override_settings(
        MULTIREGION_QQ_REGION_WINDOW_MAX=3,
        MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY=12,
        MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY=40,
    )
    def test_qq_retryable_existing_delivery_reserves_quota(self):
        from stable.services.qq_windows import select_qq_window_deliveries

        window, target = self._window()
        article = self._article(source_article_id="retry-skipped")
        delivery = QQPushDelivery.objects.create(
            article=article,
            target=target,
            status=QQPushDeliveryStatus.SKIPPED,
            attempt_count=1,
            max_attempts=3,
        )

        result = select_qq_window_deliveries(RacingRegion.HONG_KONG, window=window, targets=[target], now=timezone.now())

        self.assertEqual(result.deliveries, [delivery])
        self.assertTrue(WindowTargetDecision.objects.filter(window=window, reason="retry_existing").exists())
        group_ledger = QuotaLedger.objects.get(
            kind=QuotaLedgerKind.QQ_PUSH,
            scope=QuotaLedgerScope.GROUP_HOUR,
            scope_key=f"group:{target.group_id}",
        )
        site_ledger = QuotaLedger.objects.get(
            kind=QuotaLedgerKind.QQ_PUSH,
            scope=QuotaLedgerScope.SITE_HOUR,
            scope_key="site",
        )
        self.assertEqual(group_ledger.used, 1)
        self.assertEqual(site_ledger.used, 1)

    @override_settings(
        MULTIREGION_QQ_REGION_WINDOW_MAX=3,
        MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY=12,
        MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY=0,
    )
    def test_qq_retryable_existing_delivery_respects_quota(self):
        from stable.services.qq_windows import select_qq_window_deliveries

        window, target = self._window()
        article = self._article(source_article_id="retry-site-quota")
        QQPushDelivery.objects.create(
            article=article,
            target=target,
            status=QQPushDeliveryStatus.SKIPPED,
            attempt_count=1,
            max_attempts=3,
        )

        result = select_qq_window_deliveries(RacingRegion.HONG_KONG, window=window, targets=[target], now=timezone.now())

        self.assertEqual(result.deliveries, [])
        self.assertIn("site_hour_quota_exhausted", result.zero_reasons)
        self.assertTrue(WindowTargetDecision.objects.filter(window=window, reason="site_hour_quota_exhausted").exists())
        group_ledger = QuotaLedger.objects.get(
            kind=QuotaLedgerKind.QQ_PUSH,
            scope=QuotaLedgerScope.GROUP_HOUR,
            scope_key=f"group:{target.group_id}",
        )
        self.assertEqual(group_ledger.used, 0)

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_QQ_REGION_WINDOW_MAX=3,
        MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY=12,
        MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY=40,
        QQ_PUSH_ENABLED=True,
        SITE_URL="https://umafans.run",
    )
    def test_qq_region_window_task_creates_and_dispatches_deliveries(self):
        from stable.tasks import qq_push_delivery_task, qq_region_window_task

        self._target()
        article = self._article(source_article_id="qq-task")

        with (
            patch("stable.tasks.BotPusher.is_online", return_value=(True, "")),
            patch("stable.tasks.dispatch_task", return_value={"queued": True}) as dispatch,
        ):
            result = qq_region_window_task.run(RacingRegion.HONG_KONG, now_iso="2026-07-01T10:17:00+00:00")

        delivery = QQPushDelivery.objects.get(article=article)
        window = ProductionWindow.objects.get(kind=ProductionWindowKind.QQ_PUSH, racing_region=RacingRegion.HONG_KONG)
        self.assertEqual(result["delivery_ids"], [delivery.id])
        self.assertEqual(window.status, ProductionWindowStatus.SUCCEEDED)
        dispatch.assert_called_once_with(qq_push_delivery_task, delivery.id)

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_QQ_REGION_WINDOW_MAX=3,
        MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY=12,
        MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY=40,
        QQ_PUSH_ENABLED=True,
        SITE_URL="https://umafans.run",
    )
    def test_qq_region_window_task_records_onebot_offline_before_delivery_selection(self):
        from stable.tasks import qq_region_window_task

        self._target()
        self._article(source_article_id="qq-offline")

        with (
            patch("stable.tasks.BotPusher.is_online", return_value=(False, "onebot_offline")),
            patch("stable.tasks.dispatch_task", return_value={"queued": True}) as dispatch,
        ):
            result = qq_region_window_task.run(RacingRegion.HONG_KONG, now_iso="2026-07-01T10:17:00+00:00")

        window = ProductionWindow.objects.get(kind=ProductionWindowKind.QQ_PUSH, racing_region=RacingRegion.HONG_KONG)
        self.assertEqual(result["delivery_ids"], [])
        self.assertIn("onebot_offline", result["zero_reasons"])
        self.assertEqual(window.status, ProductionWindowStatus.FAILED)
        self.assertEqual(window.reason_summary, "onebot_offline")
        self.assertFalse(QQPushDelivery.objects.exists())
        self.assertFalse(QuotaLedger.objects.filter(kind=QuotaLedgerKind.QQ_PUSH).exists())
        dispatch.assert_not_called()

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_QQ_REGION_WINDOW_MAX=3,
        MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY=12,
        MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY=40,
        QQ_PUSH_ENABLED=True,
        SITE_URL="https://umafans.run",
    )
    def test_qq_region_window_task_only_sends_latest_missing_window(self):
        from stable.services.qq_windows import QQWindowResult
        from stable.tasks import qq_region_window_task

        ProductionWindow.objects.create(
            kind=ProductionWindowKind.QQ_PUSH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            scope_key="region:hong_kong:qq",
            window_start=datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc),
            window_end=datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
            status=ProductionWindowStatus.SUCCEEDED,
        )

        with (
            patch("stable.tasks.BotPusher.is_online", return_value=(True, "")),
            patch("stable.tasks.select_qq_window_deliveries", return_value=QQWindowResult(deliveries=[])) as select,
        ):
            result = qq_region_window_task.run(RacingRegion.HONG_KONG, now_iso="2026-07-01T10:47:00+00:00")

        starts = list(
            ProductionWindow.objects.filter(kind=ProductionWindowKind.QQ_PUSH, racing_region=RacingRegion.HONG_KONG)
            .order_by("window_start")
            .values_list("window_start", flat=True)
        )
        self.assertEqual(
            starts,
            [
                datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc),
                datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
                datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc),
                datetime(2026, 7, 1, 10, 45, tzinfo=dt_timezone.utc),
            ],
        )
        self.assertEqual(select.call_count, 1)
        latest = ProductionWindow.objects.get(
            kind=ProductionWindowKind.QQ_PUSH,
            racing_region=RacingRegion.HONG_KONG,
            window_start=datetime(2026, 7, 1, 10, 45, tzinfo=dt_timezone.utc),
        )
        coalesced = ProductionWindow.objects.filter(
            kind=ProductionWindowKind.QQ_PUSH,
            racing_region=RacingRegion.HONG_KONG,
            reason_summary="coalesced_to_latest_qq_window",
        )
        self.assertEqual(latest.status, ProductionWindowStatus.SUCCEEDED)
        self.assertEqual(coalesced.count(), 2)
        self.assertEqual(result["window_ids"], [latest.id])

    @override_settings(
        MULTIREGION_PRODUCTION_WINDOWS_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED=True,
        MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_QQ_REGION_WINDOW_MAX=3,
        MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY=12,
        MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY=40,
        QQ_PUSH_ENABLED=True,
        SITE_URL="https://umafans.run",
    )
    def test_qq_region_window_task_coalesces_stale_running_windows(self):
        from stable.services.qq_windows import QQWindowResult
        from stable.tasks import qq_region_window_task

        now = datetime(2026, 7, 1, 10, 47, tzinfo=dt_timezone.utc)
        ProductionWindow.objects.create(
            kind=ProductionWindowKind.QQ_PUSH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            scope_key="region:hong_kong:qq",
            window_start=datetime(2026, 7, 1, 10, 0, tzinfo=dt_timezone.utc),
            window_end=datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
            status=ProductionWindowStatus.SUCCEEDED,
        )
        stale = ProductionWindow.objects.create(
            kind=ProductionWindowKind.QQ_PUSH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            scope_key="region:hong_kong:qq",
            window_start=datetime(2026, 7, 1, 10, 15, tzinfo=dt_timezone.utc),
            window_end=datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc),
            status=ProductionWindowStatus.RUNNING,
            lease_expires_at=now - timedelta(minutes=1),
        )

        with (
            patch("stable.tasks.BotPusher.is_online", return_value=(True, "")),
            patch("stable.tasks.select_qq_window_deliveries", return_value=QQWindowResult(deliveries=[])) as select,
        ):
            result = qq_region_window_task.run(RacingRegion.HONG_KONG, now_iso=now.isoformat())

        stale.refresh_from_db()
        latest = ProductionWindow.objects.get(
            kind=ProductionWindowKind.QQ_PUSH,
            racing_region=RacingRegion.HONG_KONG,
            window_start=datetime(2026, 7, 1, 10, 45, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(stale.status, ProductionWindowStatus.SKIPPED)
        self.assertEqual(stale.reason_summary, "coalesced_to_latest_qq_window")
        self.assertEqual(result["window_ids"], [latest.id])
        select.assert_called_once()


class MultiRegionNewsProductionTests(TestCase):
    def _article(self, **overrides):
        payload = {
            "source_site": SourceSite.HKJC_NEWS,
            "source_mode": SourceMode.LATEST,
            "source_article_id": overrides.pop("source_article_id", "mr-article"),
            "racing_region": RacingRegion.HONG_KONG,
            "source_language": SourceLanguage.ENGLISH,
            "title_ja": "Lucky Star wins at Sha Tin",
            "body_ja_raw": "Lucky Star wins at Sha Tin. " * 16,
            "body_ja_normalized": "Lucky Star wins at Sha Tin. " * 16,
            "translated_title_zh": "Lucky Star 在沙田取胜",
            "title_zh": "Lucky Star 在沙田取胜",
            "translated_summary_zh": "香港赛马新闻摘要",
            "summary_zh": "香港赛马新闻摘要",
            "translated_body_zh": "Lucky Star 在沙田取胜。" * 20,
            "body_zh": "Lucky Star 在沙田取胜。" * 20,
            "published_at": timezone.now(),
            "source_url": "https://example.com/mr-article",
        }
        payload.update(overrides)
        return NewsArticle.objects.create(**payload)

    @override_settings(NEWS_SOURCE_POLL_ENABLED=False)
    def test_disabled_generic_source_poll_does_not_create_crawl_jobs(self):
        from stable.tasks import crawl_enabled_news_sources_task

        source = NewsSource.objects.create(
            name="HK enabled source",
            homepage_url="https://example.com",
            feed_url="https://example.com/feed",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            adapter_key="hkjc_news",
            source_site=SourceSite.HKJC_NEWS,
            source_mode=SourceMode.LATEST,
            enabled=True,
            crawl_interval_minutes=1,
        )

        result = crawl_enabled_news_sources_task.run()

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "disabled")
        self.assertEqual(CrawlJob.objects.filter(source=source).count(), 0)

    @override_settings(
        NEWS_SOURCE_POLL_ENABLED=True,
        NEWS_SOURCE_POLL_ALLOWED_REGIONS=["hong_kong", "japan"],
        NEWS_SOURCE_POLL_MAX_SOURCES=3,
    )
    def test_generic_source_selector_excludes_fixed_schedule_sources_and_respects_limit(self):
        from stable.services.source_polling import select_due_enabled_news_sources

        sync_builtin_sources()
        fixed = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.LATEST)
        fixed.enabled = True
        fixed.last_crawl_at = timezone.now() - timedelta(hours=3)
        fixed.save(update_fields=["enabled", "last_crawl_at", "updated_at"])
        first = NewsSource.objects.get(source_site=SourceSite.HKJC_NEWS, source_mode=SourceMode.LATEST)
        second = NewsSource.objects.get(source_site=SourceSite.SCMP_RACING, source_mode=SourceMode.LATEST)
        third = NewsSource.objects.create(
            name="HK extra",
            homepage_url="https://example.com",
            feed_url="https://example.com/extra",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            adapter_key="hkjc_news",
            source_site=SourceSite.HKJC_NEWS,
            source_mode=SourceMode.OFFICIAL,
            enabled=True,
            priority=1,
            crawl_interval_minutes=1,
        )
        for index, source in enumerate([first, second]):
            source.enabled = True
            source.last_crawl_at = timezone.now() - timedelta(hours=6 + index)
            source.save(update_fields=["enabled", "last_crawl_at", "updated_at"])

        selection = select_due_enabled_news_sources(max_sources=2)

        self.assertEqual([item.source.id for item in selection.selected], [first.id, second.id])
        self.assertEqual(selection.deferred_count, 1)
        self.assertIn(fixed.id, [item.source.id for item in selection.skipped])
        self.assertTrue(third.enabled)

    @override_settings(
        NEWS_SOURCE_POLL_ENABLED=True,
        NEWS_SOURCE_POLL_ALLOWED_REGIONS=["hong_kong"],
        NEWS_SOURCE_POLL_RUNNING_TIMEOUT_MINUTES=60,
        NEWS_SOURCE_POLL_RETRY_STALE_RUNNING=False,
    )
    def test_generic_source_selector_reports_stale_running_without_retriggering_by_default(self):
        from stable.services.source_polling import select_due_enabled_news_sources

        source = NewsSource.objects.create(
            name="HK stale running",
            homepage_url="https://example.com",
            feed_url="https://example.com/feed",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            adapter_key="hkjc_news",
            source_site=SourceSite.HKJC_NEWS,
            source_mode=SourceMode.LATEST,
            enabled=True,
            crawl_interval_minutes=1,
        )
        CrawlJob.objects.create(source=source, status=TaskStatus.STARTED, started_at=timezone.now() - timedelta(minutes=90))

        selection = select_due_enabled_news_sources(max_sources=1)

        self.assertEqual(selection.selected, [])
        self.assertIn((source.id, "stale_running"), [(item.source.id, item.reason) for item in selection.skipped])

    @override_settings(MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=[], MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=[])
    def test_non_japan_article_defaults_to_manual_review_without_auto_publish_policy(self):
        from stable.services.automation import score_article_for_automation

        article = self._article(
            source_article_id="mr-manual-default",
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_mode=SourceMode.ACCESS,
            racing_region=RacingRegion.UNITED_KINGDOM,
        )

        decision = score_article_for_automation(article)

        self.assertEqual(decision.review_mode, ReviewMode.MANUAL)
        self.assertEqual(decision.automation_status, AutomationStatus.MANUAL_REVIEW_REQUIRED)
        self.assertEqual(decision.decision_reason["publish_policy"]["reason"], "region_not_allowed")

    @override_settings(
        MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=["hkjc_news:latest"],
        MULTIREGION_TERM_CANDIDATE_BACKLOG_THRESHOLD=1,
    )
    def test_term_candidate_backlog_routes_allowed_international_article_to_manual(self):
        from stable.services.automation import score_article_for_automation

        article = self._article(source_article_id="mr-term-backlog")
        candidate = TermCandidate.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Lucky Star",
            normalized_key="lucky star",
            status=TermCandidateStatus.PENDING,
            confidence=90,
        )
        TermCandidateEvidence.objects.create(candidate=candidate, article=article, occurrence_count=1, confidence=90)

        decision = score_article_for_automation(article)

        self.assertEqual(decision.review_mode, ReviewMode.MANUAL)
        self.assertEqual(decision.decision_reason["publish_policy"]["reason"], "term_candidate_backlog")

    @override_settings(
        AUTOMATION_ENABLED=True,
        MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=["hkjc_news:latest"],
        MULTIREGION_AUTO_PUBLISH_REGION_BATCH_LIMITS={"hong_kong": 1},
        MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS={"hong_kong": 1},
    )
    def test_auto_publish_batch_applies_region_per_run_and_daily_limits(self):
        first = self._article(source_article_id="mr-ready-1", automation_status=AutomationStatus.PUBLISH_READY, review_mode=ReviewMode.AUTO, score_total=90)
        second = self._article(source_article_id="mr-ready-2", automation_status=AutomationStatus.PUBLISH_READY, review_mode=ReviewMode.AUTO, score_total=89)
        third = self._article(source_article_id="mr-ready-3", automation_status=AutomationStatus.PUBLISH_READY, review_mode=ReviewMode.AUTO, score_total=88)

        first_result = auto_publish_batch_task.run(limit=5)
        second_result = auto_publish_batch_task.run(limit=5)

        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        self.assertEqual(first_result["published_count"], 1)
        self.assertEqual(second_result["published_count"], 0)
        self.assertEqual(first.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertNotEqual(second.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertNotEqual(third.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertIn("daily_limit_reached", second_result["skipped_reasons"].values())

    @override_settings(
        AUTOMATION_ENABLED=True,
        MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=["hkjc_news:latest"],
        MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS={"hong_kong": 1},
    )
    def test_auto_publish_batch_continues_past_limited_region_for_japan(self):
        self._article(
            source_article_id="mr-hk-published-today",
            automation_status=AutomationStatus.AUTO_PUBLISHED,
            workflow_status=WorkflowStatus.PUBLISHED,
            published_by_mode=PublishedByMode.AUTO,
            auto_publish_at=timezone.now(),
            published_to_web_at=timezone.now(),
            score_total=100,
        )
        for index in range(220):
            self._article(
                source_article_id=f"mr-hk-limited-{index}",
                automation_status=AutomationStatus.PUBLISH_READY,
                review_mode=ReviewMode.AUTO,
                score_total=100,
            )
        japan_article = self._article(
            source_article_id="mr-japan-ready-after-limited-hk",
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            racing_region=RacingRegion.JAPAN,
            source_language=SourceLanguage.JAPANESE,
            automation_status=AutomationStatus.PUBLISH_READY,
            review_mode=ReviewMode.AUTO,
            score_total=10,
        )

        result = auto_publish_batch_task.run(limit=1)

        japan_article.refresh_from_db()
        self.assertEqual(result["published_ids"], [japan_article.id])
        self.assertEqual(japan_article.workflow_status, WorkflowStatus.PUBLISHED)

    def test_multiregion_audit_command_is_read_only_and_outputs_region_metrics(self):
        source = NewsSource.objects.create(
            name="HK audit source",
            homepage_url="https://example.com",
            feed_url="https://example.com/feed",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            adapter_key="hkjc_news",
            source_site=SourceSite.HKJC_NEWS,
            source_mode=SourceMode.LATEST,
            enabled=True,
        )
        CrawlJob.objects.create(source=source, status=TaskStatus.SUCCESS, success_count=1, finished_at=timezone.now())
        self._article(source_article_id="mr-audit")
        before = {
            "crawl_jobs": CrawlJob.objects.count(),
            "articles": NewsArticle.objects.count(),
            "deliveries": QQPushDelivery.objects.count(),
            "external_runs": ExternalDataImportRun.objects.count(),
        }
        out = StringIO()

        call_command("audit_multiregion_news_production", stdout=out)

        payload = json.loads(out.getvalue())
        after = {
            "crawl_jobs": CrawlJob.objects.count(),
            "articles": NewsArticle.objects.count(),
            "deliveries": QQPushDelivery.objects.count(),
            "external_runs": ExternalDataImportRun.objects.count(),
        }
        self.assertEqual(before, after)
        self.assertGreaterEqual(payload["regions"]["hong_kong"]["sources"]["enabled"], 1)
        self.assertEqual(payload["regions"]["hong_kong"]["articles"]["total"], 1)
        self.assertIn("term_operations", payload["regions"]["hong_kong"])

    def test_region_overview_uses_today_window_for_publish_counts(self):
        now = timezone.now()
        yesterday = now - timedelta(days=1)
        self._article(
            source_article_id="mr-old-auto",
            workflow_status=WorkflowStatus.PUBLISHED,
            automation_status=AutomationStatus.AUTO_PUBLISHED,
            published_by_mode=PublishedByMode.AUTO,
            first_seen_at=yesterday,
            auto_publish_at=yesterday,
            published_to_web_at=yesterday,
        )
        self._article(
            source_article_id="mr-today-manual",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_by_mode=PublishedByMode.MANUAL,
            first_seen_at=now,
            published_to_web_at=now,
        )

        from stable.services.multiregion import region_production_rows

        rows = region_production_rows(selected_region=RacingRegion.HONG_KONG, now=now)

        self.assertEqual(rows[0]["today_new"], 1)
        self.assertEqual(rows[0]["auto_published"], 0)
        self.assertEqual(rows[0]["manual_published"], 1)
        self.assertEqual(rows[0]["public"], 1)

    def test_multiregion_audit_filters_formal_terms_by_region(self):
        from stable.services.multiregion import summarize_multiregion_news_production

        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Global Horse",
            target_zh="全局马",
        )
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            source_ja="HK Horse",
            target_zh="香港马",
        )
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="UK Horse",
            target_zh="英国马",
        )

        summary = summarize_multiregion_news_production()

        self.assertEqual(summary["regions"][RacingRegion.HONG_KONG]["term_operations"]["formal_terms_by_language"][SourceLanguage.ENGLISH], 2)
        self.assertEqual(summary["regions"][RacingRegion.UNITED_KINGDOM]["term_operations"]["formal_terms_by_language"][SourceLanguage.ENGLISH], 2)
        self.assertEqual(summary["regions"][RacingRegion.FRANCE]["term_operations"]["formal_terms_by_language"][SourceLanguage.ENGLISH], 1)

    def test_multiregion_audit_crawl_statuses_use_current_source_state(self):
        from stable.services.multiregion import summarize_multiregion_news_production

        success_source = NewsSource.objects.create(
            name="HK current success",
            homepage_url="https://example.com/success",
            feed_url="https://example.com/success/feed",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            adapter_key="hkjc_news",
            source_site=SourceSite.HKJC_NEWS,
            source_mode=SourceMode.LATEST,
            enabled=True,
            last_crawl_status=TaskStatus.SUCCESS,
        )
        failed_source = NewsSource.objects.create(
            name="HK current failed",
            homepage_url="https://example.com/failed",
            feed_url="https://example.com/failed/feed",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            adapter_key="scmp_racing",
            source_site=SourceSite.SCMP_RACING,
            source_mode=SourceMode.LATEST,
            enabled=True,
            last_crawl_status=TaskStatus.FAILED,
        )
        for index in range(3):
            CrawlJob.objects.create(source=success_source, status=TaskStatus.SUCCESS, finished_at=timezone.now() - timedelta(days=index + 1))
            CrawlJob.objects.create(source=failed_source, status=TaskStatus.SUCCESS, finished_at=timezone.now() - timedelta(days=index + 1))

        summary = summarize_multiregion_news_production()

        self.assertEqual(summary["regions"][RacingRegion.HONG_KONG]["sources"]["crawl_statuses"][TaskStatus.SUCCESS], 1)
        self.assertEqual(summary["regions"][RacingRegion.HONG_KONG]["sources"]["crawl_statuses"][TaskStatus.FAILED], 1)

    def test_qq_message_for_international_article_contains_region_label(self):
        article = self._article(
            source_article_id="mr-qq-region",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        message = build_qq_auto_push_message(article, public_url="http://testserver/news/1/")

        self.assertIn("地区：中国香港", message)
        self.assertIn("【UmaFans】", message)

    def test_region_overview_view_filters_sources_by_region_and_shows_qq_counts(self):
        user = User.objects.create_superuser("region-admin", "region-admin@example.com", "pass")
        self.client.login(username="region-admin", password="pass")
        source = NewsSource.objects.create(
            name="HK overview source",
            homepage_url="https://example.com",
            feed_url="https://example.com/feed",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            adapter_key="hkjc_news",
            source_site=SourceSite.HKJC_NEWS,
            source_mode=SourceMode.LATEST,
            enabled=True,
        )
        article = self._article(source_article_id="mr-overview", source_config=source, workflow_status=WorkflowStatus.PUBLISHED, published_to_web_at=timezone.now())
        target = PushTarget.objects.create(name="测试群", group_id="10001", allowed_regions=[RacingRegion.HONG_KONG], is_active=True)
        QQPushDelivery.objects.create(article=article, target=target, status=QQPushDeliveryStatus.SENT, sent_at=timezone.now())

        response = self.client.get(reverse("console-region-production"), {"region": RacingRegion.HONG_KONG})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "中国香港")
        self.assertContains(response, "HK overview source")
        self.assertContains(response, "QQ")

    def test_region_overview_links_to_window_detail(self):
        User.objects.create_superuser("window-admin", "window-admin@example.com", "pass")
        self.client.login(username="window-admin", password="pass")
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.PUBLISH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            scope_key="region:hong_kong",
            window_start=timezone.now().replace(second=0, microsecond=0),
            window_end=timezone.now().replace(second=0, microsecond=0) + timedelta(minutes=15),
            status=ProductionWindowStatus.SUCCEEDED,
            reason_summary="published",
        )

        response = self.client.get(reverse("console-region-production"), {"region": RacingRegion.HONG_KONG})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("console-production-window-detail", args=[window.id]))

    @override_settings(
        MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY=60,
    )
    def test_publish_window_preview_does_not_write_business_state(self):
        User.objects.create_superuser("preview-admin", "preview-admin@example.com", "pass")
        self.client.login(username="preview-admin", password="pass")
        window_start = timezone.now().replace(second=0, microsecond=0)
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.PUBLISH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            scope_key="region:hong_kong",
            window_start=window_start,
            window_end=window_start + timedelta(minutes=15),
            status=ProductionWindowStatus.SUCCEEDED,
        )
        article = self._article(
            source_article_id="mr-preview-window",
            automation_status=AutomationStatus.PUBLISH_READY,
            review_mode=ReviewMode.AUTO,
            score_total=90,
        )

        response = self.client.get(reverse("console-production-window-preview", args=[window.id]))

        article.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lucky Star 在沙田取胜")
        self.assertFalse(WindowCandidateDecision.objects.filter(window=window).exists())
        self.assertFalse(QuotaLedger.objects.filter(kind=QuotaLedgerKind.WEB_PUBLISH).exists())
        self.assertNotEqual(article.workflow_status, WorkflowStatus.PUBLISHED)

    @override_settings(
        MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=["hong_kong"],
        MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY=60,
    )
    def test_publish_window_manual_rerun_records_operator_and_rerun_count(self):
        user = User.objects.create_superuser("rerun-admin", "rerun-admin@example.com", "pass")
        self.client.login(username="rerun-admin", password="pass")
        window_start = timezone.now().replace(second=0, microsecond=0)
        window = ProductionWindow.objects.create(
            kind=ProductionWindowKind.PUBLISH,
            mode=ProductionWindowMode.DAILY,
            racing_region=RacingRegion.HONG_KONG,
            scope_key="region:hong_kong",
            window_start=window_start,
            window_end=window_start + timedelta(minutes=15),
            status=ProductionWindowStatus.SUCCEEDED,
        )
        article = self._article(
            source_article_id="mr-rerun-window",
            automation_status=AutomationStatus.PUBLISH_READY,
            review_mode=ReviewMode.AUTO,
            score_total=90,
        )

        response = self.client.post(reverse("console-production-window-rerun", args=[window.id]))

        window.refresh_from_db()
        article.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(window.rerun_count, 1)
        self.assertEqual(window.triggered_by, user)
        self.assertEqual(window.status, ProductionWindowStatus.SUCCEEDED)
        self.assertEqual(article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertTrue(OperationLog.objects.filter(action_type="production_window_rerun", target_id=window.id).exists())


class TermRegionFilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("term-region-admin", "term-region-admin@example.com", "pass")
        self.client.login(username="term-region-admin", password="pass")

    def test_term_list_filters_by_racing_region(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            source_ja="HK Term",
            target_zh="香港术语",
        )
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="UK Term",
            target_zh="英国术语",
        )

        response = self.client.get(reverse("console-term-list"), {"racing_region": RacingRegion.HONG_KONG})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HK Term")
        self.assertNotContains(response, "UK Term")


class FakeExternalHorseDataAdapter:
    def __init__(self):
        self.fetched_race_ids: list[str] = []

    def race_list(self, year: int, month: int) -> list[str]:
        return [f"{year}{month:02d}0101", f"{year}{month:02d}0102"]

    def fetch_race(self, race_id: str, *, fetch_odds: bool = False) -> dict:
        self.fetched_race_ids.append(race_id)
        return {
            "race": {
                "race_id": race_id,
                "race_name": "東京優駿",
                "race_date": "2026-05-31",
                "extra_field": "保留字段",
            },
            "entry": [
                {
                    "horse_id": "1001",
                    "horse_name": "マヤノライジン",
                    "horse_number": "1",
                    "jockey_name": "武豊",
                    "extra_entry": "保存",
                },
                {
                    "horse_id": "1002",
                    "horse_name": "クロワデュノール",
                    "horse_number": "2",
                },
            ],
            "result": [
                {
                    "horse_id": "1001",
                    "horse_name": "マヤノライジン",
                    "horse_number": "1",
                    "finish_position": "1",
                }
            ],
            "odds": [{"odds_type": "win", "horse_number": "1", "odds": "2.1"}] if fetch_odds else [],
        }

    def fetch_horse(self, horse_id: str) -> dict:
        return {
            "horse": {
                "horse_id": horse_id,
                "father_name": "マヤノトップガン",
                "unknown_future_field": "後で使う",
            },
            "history": [
                {
                    "race_id": "202605310101",
                    "race_name": "東京優駿",
                    "race_date": "2026-05-31",
                    "finish_position": "1",
                }
            ],
        }


@override_settings(EXTERNAL_HORSE_DATA_IMPORT_ENABLED=True)
class ExternalHorseDataImportTests(TestCase):
    def importer(self, **overrides):
        adapter = overrides.pop("adapter", None) or FakeExternalHorseDataAdapter()
        values = {
            "allow_network": True,
            "request_interval_seconds": 0,
            "jitter_seconds": 0,
            "max_races": 1,
            "max_horses": 10,
            "fetch_odds": True,
            "fetch_horse_detail": True,
        }
        values.update(overrides)
        options = ImportOptions(**values)
        return ExternalHorseDataImporter(options, adapter=adapter)

    def test_import_race_preserves_payload_and_is_idempotent(self):
        importer = self.importer()

        first = importer.import_race("202605310101")
        second = importer.import_race("202605310101")

        self.assertEqual(first["status"], ExternalImportStatus.SUCCESS)
        self.assertEqual(second["status"], ExternalImportStatus.SUCCESS)
        self.assertEqual(ExternalRace.objects.count(), 1)
        self.assertEqual(ExternalRaceEntry.objects.count(), 2)
        self.assertEqual(ExternalRaceResult.objects.count(), 1)
        self.assertEqual(ExternalRaceOdds.objects.count(), 1)
        self.assertEqual(ExternalHorseAlias.objects.filter(name_ja="マヤノライジン").count(), 1)
        race = ExternalRace.objects.get()
        self.assertEqual(race.raw_payload["extra_field"], "保留字段")
        entry = ExternalRaceEntry.objects.get(horse_id="1001")
        self.assertEqual(entry.raw_payload["extra_entry"], "保存")

    def test_dry_run_does_not_write_external_tables(self):
        importer = self.importer(dry_run=True, allow_network=False)

        result = importer.import_race("202605310101")

        self.assertTrue(result["dry_run"])
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)
        self.assertEqual(ExternalRace.objects.count(), 0)

    @override_settings(EXTERNAL_HORSE_DATA_IMPORT_ENABLED=False)
    def test_real_import_requires_enabled_setting(self):
        with self.assertRaises(ExternalHorseDataNetworkDisabled):
            self.importer().import_race("202605310101")

    def test_single_horse_import_only_creates_alias_with_trusted_name(self):
        importer = self.importer(fetch_horse_detail=True)

        importer.import_horse("1001")
        importer.import_horse("1002", horse_name="マヤノライジン")

        self.assertFalse(ExternalHorseAlias.objects.filter(external_horse_id="1001").exists())
        alias = ExternalHorseAlias.objects.get(external_horse_id="1002")
        self.assertEqual(alias.name_ja, "マヤノライジン")

    def test_source_lock_blocks_parallel_real_imports(self):
        run = ExternalDataImportRun.objects.create(source="netkeiba", target_type="month", status=ExternalImportStatus.STARTED)
        ExternalDataImportLock.objects.create(source="netkeiba", locked_by_run=run, acquired_at=timezone.now())

        with self.assertRaises(ExternalHorseDataAlreadyRunning):
            self.importer().import_race("202605310101")

    def test_month_import_respects_max_races_and_records_coverage_stats(self):
        result = self.importer(max_races=1).import_month(2026, 5)

        self.assertEqual(result["status"], ExternalImportStatus.PAUSED)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["coverage_stats"]["race_count"], 1)
        self.assertEqual(result["coverage_stats"]["unique_horse_name_count"], 2)

    def test_month_import_skips_existing_races_and_processes_next_batch(self):
        first_adapter = FakeExternalHorseDataAdapter()
        second_adapter = FakeExternalHorseDataAdapter()

        first = self.importer(adapter=first_adapter, max_races=1).import_month(2026, 5)
        second = self.importer(adapter=second_adapter, max_races=1).import_month(2026, 5)

        self.assertEqual(first["status"], ExternalImportStatus.PAUSED)
        self.assertEqual(second["status"], ExternalImportStatus.SUCCESS)
        self.assertEqual(first_adapter.fetched_race_ids, ["2026050101"])
        self.assertEqual(second_adapter.fetched_race_ids, ["2026050102"])
        self.assertEqual(ExternalRace.objects.count(), 2)
        second_run = ExternalDataImportRun.objects.get(pk=second["run_id"])
        self.assertEqual(second_run.parameters["already_imported_race_count"], 1)

    def test_management_command_dry_run_does_not_write(self):
        out = StringIO()

        call_command("import_external_horse_data", "--race-id", "202605310101", "--dry-run", stdout=out)

        self.assertIn('"dry_run": true', out.getvalue())
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)
        self.assertEqual(ExternalRace.objects.count(), 0)

    def test_management_command_lookup_name_reads_local_alias(self):
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        out = StringIO()

        call_command("import_external_horse_data", "--lookup-name", "マヤノライジン", stdout=out)

        self.assertIn('"external_horse_id": "1001"', out.getvalue())


class HKJCExternalDataImportTests(TestCase):
    def test_hkjc_meeting_parser_filters_recent_result_dates(self):
        # Mutation: if the parser reads option labels instead of JSON values, or forgets the date window,
        # stale meetings such as 2026-04-22 leak into a 60-day import.
        from pathlib import Path

        from stable.services.external_hkjc_data import HKJCHTMLParser

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "localresults-meetings-sample.html"
        )
        parser = HKJCHTMLParser()

        meetings = parser.parse_result_meetings(
            fixture_path.read_text(encoding="utf-8"),
            start_date="2026-04-27",
            end_date="2026-06-26",
            source_url="https://racing.hkjc.com/en-us/local/information/localresults",
        )

        self.assertEqual(
            [meeting["race_date"] for meeting in meetings],
            ["2026-06-24", "2026-06-21", "2026-05-27"],
        )
        self.assertEqual(meetings[0]["source_url"], "https://racing.hkjc.com/en-us/local/information/localresults")
        self.assertEqual(meetings[0]["raw_date"], "24/06/2026")

    def test_hkjc_meeting_parser_skips_overseas_simulcast_dates(self):
        # Mutation: if S1/S5 overseas simulcast options are treated as Hong Kong meetings, imports create invalid HK race ids.
        from stable.services.external_hkjc_data import HKJCHTMLParser

        html = """
        <html><body>
          <select id="selectId">
            <option value='{"date":"24/06/2026","venue":""}'>24/06/2026</option>
            <option value='{"date":"20/06/2026","venue":"S5"}'>20/06/2026 Overseas</option>
            <option value='{"date":"21/06/2026","venue":"ST"}'>21/06/2026 Sha Tin</option>
          </select>
        </body></html>
        """

        meetings = HKJCHTMLParser().parse_result_meetings(
            html,
            start_date="2026-04-27",
            end_date="2026-06-26",
            source_url="https://racing.hkjc.com/en-us/local/information/localresults",
        )

        self.assertEqual([meeting["race_date"] for meeting in meetings], ["2026-06-24", "2026-06-21"])
        self.assertEqual([meeting["venue"] for meeting in meetings], ["", "ST"])

    def test_hkjc_result_parser_maps_race_and_result_rows(self):
        # Mutation: if horse IDs are parsed from brand numbers instead of horse links, aliases collide across seasons.
        from pathlib import Path

        from stable.services.external_hkjc_data import HKJCHTMLParser

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "localresults-race-sample.html"
        )
        parser = HKJCHTMLParser()

        race = parser.parse_race_result(
            fixture_path.read_text(encoding="utf-8"),
            race_date="2026-06-24",
            racecourse="HV",
            race_no="1",
            source_url="https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
        )

        self.assertEqual(race["race_id"], "HK20260624HV01")
        self.assertEqual(race["race_date"], "2026-06-24")
        self.assertEqual(race["venue"], "Happy Valley")
        self.assertEqual(race["race_number"], "1")
        self.assertEqual(race["race_name"], "ICE HOUSE STREET HANDICAP")
        self.assertEqual(race["race_class"], "Class 5")
        self.assertEqual(race["distance"], "2200M")
        self.assertEqual(race["going"], "GOOD")
        self.assertEqual(race["prize_money"], "HK$ 875,000")
        self.assertEqual(len(race["entries"]), 2)
        self.assertEqual(len(race["results"]), 2)
        self.assertEqual(race["entries"][0]["horse_id"], "HK_2023_J524")
        self.assertEqual(race["entries"][0]["horse_name_en"], "ROSEWOOD FLEETFOOT")
        self.assertEqual(race["entries"][0]["horse_number"], "3")
        self.assertEqual(race["entries"][0]["barrier"], "10")
        self.assertEqual(race["results"][0]["finish_position"], "1")
        self.assertEqual(race["results"][0]["finish_time"], "2:16.62")
        self.assertEqual(race["results"][0]["odds"], "3.2")
        self.assertEqual(race["results"][1]["margin"], "1-1/4")
        self.assertEqual(race["raw_payload"]["source_url"], "https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1")

    def test_hkjc_result_race_link_parser_skips_overseas_racecourses(self):
        # Mutation: accepting S1/S5 racecourses makes local HKJC batches include overseas simulcast races.
        from stable.services.external_hkjc_data import HKJCHTMLParser

        html = """
        <html><body>
          <a href="/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1">HV Race</a>
          <a href="/en-us/overseas/results?RaceDate=20260620&Racecourse=S5&RaceNo=1">Overseas Race</a>
          <a href="/en-us/local/information/localresults?racedate=2026/06/13&Racecourse=S1&RaceNo=1">Simulcast Race</a>
          <a href="/en-us/local/information/localresults?racedate=2026/06/21&Racecourse=ST&RaceNo=2">ST Race</a>
        </body></html>
        """

        links = HKJCHTMLParser().parse_result_race_links(
            html,
            source_url="https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24",
        )

        self.assertEqual([link["race_id"] for link in links], ["HK20260624HV01", "HK20260621ST02"])

    def test_hkjc_result_parser_handles_realistic_td_header_table(self):
        # Mutation: HKJC result tables often use td header cells; requiring th silently drops every runner.
        from pathlib import Path

        from stable.services.external_hkjc_data import HKJCHTMLParser

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "localresults-race-realistic-sample.html"
        )
        parser = HKJCHTMLParser()

        race = parser.parse_race_result(
            fixture_path.read_text(encoding="utf-8"),
            race_date="2026-06-24",
            racecourse="HV",
            race_no="1",
            source_url="https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
        )

        self.assertEqual(race["race_name"], "ICE HOUSE STREET HANDICAP")
        self.assertEqual(race["course"], 'TURF - "A" Course')
        self.assertEqual(len(race["results"]), 1)
        self.assertEqual(race["results"][0]["horse_id"], "HK_2023_J524")

    def test_hkjc_horse_parser_maps_profile_fields(self):
        # Mutation: if profile label/value rows are parsed positionally, wrapped labels like Country of Origin / Age shift fields.
        from pathlib import Path

        from stable.services.external_hkjc_data import HKJCHTMLParser

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "horse-profile-sample.html"
        )
        parser = HKJCHTMLParser()

        horse = parser.parse_horse_profile(
            fixture_path.read_text(encoding="utf-8"),
            horse_id="HK_2023_J524",
            source_url="https://racing.hkjc.com/en-us/local/information/horse?horseid=HK_2023_J524",
        )

        self.assertEqual(horse["horse_id"], "HK_2023_J524")
        self.assertEqual(horse["horse_name_en"], "ROSEWOOD FLEETFOOT")
        self.assertEqual(horse["brand_number"], "J524")
        self.assertEqual(horse["country"], "NZ")
        self.assertEqual(horse["age"], "5")
        self.assertEqual(horse["color"], "Bay")
        self.assertEqual(horse["sex"], "Gelding")
        self.assertEqual(horse["trainer"], "P F Yiu")
        self.assertEqual(horse["owner"], "Lam Ka Lai & Yeung Wing Shut")
        self.assertEqual(horse["rating"], "45")
        self.assertEqual(horse["sire"], "Proisir")
        self.assertEqual(horse["dam"], "Ends Meet")
        self.assertEqual(horse["record_summary"], "2-1-1-16")
        self.assertEqual(horse["raw_payload"]["source_url"], "https://racing.hkjc.com/en-us/local/information/horse?horseid=HK_2023_J524")

    def sample_payload(self) -> dict:
        return {
            "races": [
                {
                    "race_id": "HK2026062101",
                    "race_date": "2026-06-21",
                    "venue": "Sha Tin",
                    "race_number": "1",
                    "race_name": "Class 4 Handicap",
                    "class": "Class 4",
                    "distance": "1200m",
                    "surface": "Turf",
                    "going": "Good",
                    "weather": "Fine",
                    "entries": [
                        {
                            "horse_id": "HKH001",
                            "horse_name_en": "Lucky Star",
                            "horse_name_zh_hant": "幸運星",
                            "horse_number": "1",
                            "barrier": "5",
                            "jockey": "Z Purton",
                            "trainer": "C Fownes",
                            "owner": "Happy Syndicate",
                            "weight": "126",
                            "rating": "60",
                        }
                    ],
                    "results": [
                        {
                            "horse_id": "HKH001",
                            "horse_name_en": "Lucky Star",
                            "finish_position": "1",
                            "finish_time": "1:09.88",
                            "margin": "",
                            "odds": "3.5",
                            "running_position": "2-1",
                            "sectional_time": "22.1",
                            "jockey": "Z Purton",
                            "trainer": "C Fownes",
                            "barrier": "5",
                        }
                    ],
                }
            ],
            "horses": [
                {
                    "horse_id": "HKH001",
                    "horse_name_en": "Lucky Star",
                    "horse_name_zh_hant": "幸運星",
                    "sire": "Deep Field",
                    "dam": "Lucky Mare",
                    "birth_date": "2021-03-01",
                    "owner": "Happy Syndicate",
                    "trainer": "C Fownes",
                    "country": "AUS",
                    "colour": "Bay",
                    "career_record": "10-2-1-1",
                }
            ],
            "completion": {
                "is_complete": True,
                "stop_reason": "complete",
                "races_imported": 1,
                "unique_horses_found": 1,
                "horse_profiles_fetched": 1,
            },
        }

    def write_payload(self, payload: dict | None = None) -> str:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        with handle:
            json.dump(payload or self.sample_payload(), handle, ensure_ascii=False)
        return handle.name

    def hkjc_response(self, *, url: str, text: str, status_code: int = 200):
        response = Mock()
        response.status_code = status_code
        response.url = url
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.text = text
        response.json.side_effect = ValueError("not json")
        return response

    def hkjc_date_page_with_race_links(self) -> str:
        return """
        <html><body>
          <a href="/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1">Race 1</a>
          <a href="/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=2">Race 2</a>
        </body></html>
        """

    def hkjc_date_page_with_single_race_link(self, race_date: str, racecourse: str = "ST", race_no: int = 1) -> str:
        return f"""
        <html><body>
          <a href="/en-us/local/information/localresults?racedate={race_date}&Racecourse={racecourse}&RaceNo={race_no}">Race {race_no}</a>
        </body></html>
        """

    def test_dry_run_reports_coverage_without_writing(self):
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=True))
        result = importer.import_race_date("2026-06-21", payload_file=self.write_payload())

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 1, "results": 1, "horses": 1})
        self.assertEqual(ExternalRace.objects.count(), 0)

    def test_payload_import_is_idempotent_and_creates_aliases(self):
        payload_file = self.write_payload()
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False))

        first = importer.import_race_date("2026-06-21", payload_file=payload_file)
        second = importer.import_race_date("2026-06-21", payload_file=payload_file)

        self.assertFalse(first["dry_run"])
        self.assertFalse(second["dry_run"])
        self.assertEqual(ExternalRace.objects.count(), 1)
        self.assertEqual(ExternalRaceEntry.objects.count(), 1)
        self.assertEqual(ExternalRaceResult.objects.count(), 1)
        self.assertEqual(ExternalHorseAlias.objects.filter(source="hkjc", external_horse_id="HKH001").count(), 2)
        race = ExternalRace.objects.get()
        self.assertEqual(race.racing_region, RacingRegion.HONG_KONG)
        self.assertEqual(race.going, "Good")
        horse_alias = ExternalHorseAlias.objects.get(source="hkjc", normalized_name="Lucky Star")
        self.assertEqual(horse_alias.source_language, SourceLanguage.ENGLISH)

    def test_commit_requires_payload_file_until_network_import_is_implemented(self):
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False))

        with self.assertRaisesRegex(HKJCImportError, "requires --payload-file"):
            importer.import_race("HK2026062101")

        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)

    def test_commit_rejects_running_hkjc_import_lock(self):
        active_run = ExternalDataImportRun.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            target_type="race_date",
            status=ExternalImportStatus.STARTED,
        )
        ExternalDataImportLock.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            locked_by_run=active_run,
            acquired_at=timezone.now(),
        )
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False))

        with self.assertRaisesRegex(HKJCImportError, "already running"):
            importer.import_race_date("2026-06-21", payload_file=self.write_payload())

        self.assertEqual(ExternalDataImportRun.objects.count(), 1)
        self.assertEqual(ExternalRace.objects.count(), 0)

    def test_commit_rejects_payload_over_configured_limits(self):
        payload = self.sample_payload()
        payload["races"] = [*payload["races"], {**payload["races"][0], "race_id": "HK2026062102"}]
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False, max_races=1))

        with self.assertRaisesRegex(HKJCImportError, "max_races"):
            importer.import_race_date("2026-06-21", payload_file=self.write_payload(payload))

        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)

    def test_commit_rejects_entry_and_result_horses_over_configured_limits(self):
        payload = self.sample_payload()
        payload["horses"] = []
        payload["races"][0]["entries"] = [
            {"horse_id": "HKH001", "horse_name_en": "Lucky Star", "horse_number": "1"},
            {"horse_id": "HKH002", "horse_name_en": "Fast Runner", "horse_number": "2"},
        ]
        payload["races"][0]["results"] = [
            {"horse_id": "HKH003", "horse_name_en": "Late Charge", "finish_position": "1"},
        ]
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False, max_horses=2))

        with self.assertRaisesRegex(HKJCImportError, "max_horses"):
            importer.import_race_date("2026-06-21", payload_file=self.write_payload(payload))

        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalHorseAlias.objects.count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)

    def test_commit_rejects_incomplete_hkjc_payload(self):
        # Mutation: HKJC commit must not write a dry-run payload that explicitly reports incomplete coverage.
        payload = self.sample_payload()
        payload["completion"] = {
            "is_complete": False,
            "stop_reason": "limit_horses_reached",
            "horse_profiles_fetched": 1,
            "unique_horses_found": 2,
        }
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False))

        with self.assertRaisesRegex(HKJCImportError, "incomplete"):
            importer.import_race_date("2026-06-21", payload_file=self.write_payload(payload))

        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalHorseAlias.objects.count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)

    def test_hkjc_management_command_lookup_name(self):
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH001",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            alias_source="test",
        )
        out = StringIO()

        call_command("import_hkjc_external_data", "--lookup-name", "Lucky Star", stdout=out)

        self.assertIn('"external_horse_id": "HKH001"', out.getvalue())

    def test_hkjc_management_command_stats_run_id_reports_coverage(self):
        payload_file = self.write_payload()
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=False))
        result = importer.import_race_date("2026-06-21", payload_file=payload_file)
        out = StringIO()

        call_command("import_hkjc_external_data", "--stats-run-id", str(result["run_id"]), stdout=out)

        stats = json.loads(out.getvalue())
        self.assertEqual(stats["run_id"], result["run_id"])
        self.assertEqual(stats["source"], "hkjc")
        self.assertEqual(stats["status"], ExternalImportStatus.SUCCESS)
        self.assertEqual(stats["success_count"], 4)
        self.assertEqual(stats["coverage_stats"], {"races": 1, "entries": 1, "results": 1, "horses": 1})
        self.assertEqual(stats["error_count"], 0)

    def test_hkjc_import_options_are_backed_by_runtime_settings(self):
        # Mutation: removing HKJC_IMPORT_* from settings.py would leave production limits stuck at code defaults.
        self.assertTrue(hasattr(django_settings, "HKJC_IMPORT_REQUEST_INTERVAL_SECONDS"))
        self.assertTrue(hasattr(django_settings, "HKJC_IMPORT_MAX_RACES_PER_RUN"))
        self.assertTrue(hasattr(django_settings, "HKJC_IMPORT_MAX_HORSES_PER_RUN"))
        self.assertTrue(hasattr(django_settings, "HKJC_IMPORT_MAX_REQUESTS_PER_RUN"))

        options = HKJCImportOptions.from_settings()

        self.assertEqual(options.request_interval_seconds, django_settings.HKJC_IMPORT_REQUEST_INTERVAL_SECONDS)
        self.assertEqual(options.max_races, django_settings.HKJC_IMPORT_MAX_RACES_PER_RUN)
        self.assertEqual(options.max_horses, django_settings.HKJC_IMPORT_MAX_HORSES_PER_RUN)
        self.assertEqual(options.max_requests, django_settings.HKJC_IMPORT_MAX_REQUESTS_PER_RUN)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=2,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=10,
    )
    def test_hkjc_network_dry_run_records_request_boundary_without_writing(self):
        # Mutation: treating --allow-network dry-run as a placeholder payload would hide request URLs and status.
        fake_payload = self.sample_payload()
        from stable.services import external_hkjc_data as hkjc_module

        mock_get = Mock()
        mock_get.return_value.status_code = 200
        mock_get.return_value.url = "https://hkjc.example.test/racing/2026-06-21"
        mock_get.return_value.json.return_value = fake_payload
        mock_get.return_value.text = json.dumps(fake_payload)
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command("import_hkjc_external_data", "--race-date", "2026-06-21", "--allow-network", stdout=out)

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["network_probe"])
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 1, "results": 1, "horses": 1})
        self.assertEqual(
            result["requests"],
            [
                {
                    "url": "https://hkjc.example.test/racing/2026-06-21",
                    "status_code": 200,
                    "target_type": "race_date",
                    "target_id": "2026-06-21",
                }
            ],
        )
        self.assertFalse(result["would_write_formal_tables"])
        self.assertTrue(mock_get.called)
        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalHorseAlias.objects.count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=2,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=10,
    )
    def test_hkjc_network_race_dry_run_parses_html_without_writing(self):
        # Mutation: if --allow-network still expects JSON, real HKJC HTML pages can never enter dry-run.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "localresults-race-sample.html"
        )
        horse_fixture = fixture_path.parent / "horse-profile-sample.html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                    text=fixture_path.read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                    text=horse_fixture.read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2024_K500",
                    text=horse_fixture.read_text(encoding="utf-8"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command("import_hkjc_external_data", "--race-id", "HK20260624HV01", "--allow-network", stdout=out)

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["network_probe"])
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(
            result["requests"],
            [
                {
                    "url": "https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                    "status_code": 200,
                    "target_type": "race",
                    "target_id": "HK20260624HV01",
                },
                {
                    "url": "https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                    "status_code": 200,
                    "target_type": "horse",
                    "target_id": "HK_2023_J524",
                },
                {
                    "url": "https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2024_K500",
                    "status_code": 200,
                    "target_type": "horse",
                    "target_id": "HK_2024_K500",
                },
            ],
        )
        self.assertFalse(result["would_write_formal_tables"])
        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalRaceResult.objects.count(), 0)
        self.assertEqual(ExternalHorseAlias.objects.count(), 0)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=2,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=10,
    )
    def test_hkjc_network_race_commit_writes_html_payload(self):
        # Mutation: keeping the old "commit requires payload file" gate blocks verified real HKJC race HTML imports.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "hkjc"
            / "html"
            / "localresults-race-sample.html"
        )
        horse_fixture = fixture_path.parent / "horse-profile-sample.html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                    text=fixture_path.read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                    text=horse_fixture.read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2024_K500",
                    text=horse_fixture.read_text(encoding="utf-8"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=False, allow_network=True))

        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            result = importer.import_race("HK20260624HV01")

        self.assertFalse(result["dry_run"])
        self.assertEqual(result["success_count"], 7)
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(result["completion"]["horse_profiles_fetched"], 2)
        self.assertEqual(ExternalRace.objects.count(), 1)
        self.assertEqual(ExternalRaceEntry.objects.count(), 2)
        self.assertEqual(ExternalRaceResult.objects.count(), 2)
        self.assertEqual(ExternalHorse.objects.count(), 2)
        self.assertEqual(ExternalHorseAlias.objects.filter(source="hkjc").count(), 3)
        race = ExternalRace.objects.get()
        self.assertEqual(race.race_id, "HK20260624HV01")
        self.assertEqual(race.race_name, "ICE HOUSE STREET HANDICAP")
        self.assertFalse(ExternalDataImportLock.objects.get(source="hkjc").locked_by_run_id)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_hkjc_network_recent_days_dry_run_fetches_races_and_horse_profiles(self):
        # Mutation: if recent-days only fetches race result pages, ExternalHorse details never become available.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults",
                    text=(fixture_dir / "localresults-meetings-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24",
                    text=self.hkjc_date_page_with_race_links(),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                    text=(fixture_dir / "localresults-race-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                    text=(fixture_dir / "horse-profile-sample.html").read_text(encoding="utf-8"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_hkjc_external_data",
                "--recent-days",
                "60",
                "--end-date",
                "2026-06-26",
                "--limit-races",
                "1",
                "--limit-horses",
                "1",
                "--max-requests",
                "10",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(len(result["requests"]), 4)
        self.assertEqual(result["requests"][0]["target_type"], "meeting_list")
        self.assertEqual(result["requests"][2]["target_type"], "race")
        self.assertEqual(result["requests"][3]["target_type"], "horse")
        self.assertEqual(result["requests"][3]["target_id"], "HK_2023_J524")
        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalHorse.objects.count(), 0)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_hkjc_network_date_range_skip_races_starts_later_batch(self):
        # Mutation: without skip_races, every planned batch re-imports the first races instead of advancing.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults",
                    text=(fixture_dir / "localresults-meetings-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24",
                    text=self.hkjc_date_page_with_race_links(),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/21",
                    text=self.hkjc_date_page_with_single_race_link("2026/06/21", racecourse="ST", race_no=3),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/21&Racecourse=ST&RaceNo=3",
                    text=(fixture_dir / "localresults-race-sample.html").read_text(encoding="utf-8"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        importer = HKJCExternalDataImporter(
            HKJCImportOptions(dry_run=True, allow_network=True, request_interval_seconds=0, max_requests=10)
        )

        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            result = importer.import_date_range("2026-04-27", "2026-06-26", limit_races=1, limit_horses=0, skip_races=2)

        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(result["requests"][-1]["target_id"], "HK20260621ST03")
        self.assertEqual(result["completion"]["skip_races"], 2)
        self.assertEqual(result["completion"]["races_imported"], 1)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_hkjc_network_race_ids_batch_fetches_exact_races_without_date_scan(self):
        # Mutation: if race-id batches still scan meeting/date pages, production batches waste requests before fetching the requested races.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                    text=(fixture_dir / "localresults-race-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/21&Racecourse=ST&RaceNo=3",
                    text=(fixture_dir / "localresults-race-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                    text=(fixture_dir / "horse-profile-sample.html").read_text(encoding="utf-8"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_hkjc_external_data",
                "--race-ids",
                "HK20260624HV01,HK20260621ST03",
                "--limit-horses",
                "1",
                "--max-requests",
                "10",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["target_type"], "race_batch")
        self.assertEqual(result["target_id"], "HK20260624HV01,HK20260621ST03")
        self.assertEqual(result["coverage_stats"], {"races": 2, "entries": 4, "results": 4, "horses": 2})
        self.assertEqual([request["target_type"] for request in result["requests"]], ["race", "race", "horse"])
        self.assertEqual([request["target_id"] for request in result["requests"]], ["HK20260624HV01", "HK20260621ST03", "HK_2023_J524"])
        self.assertEqual(
            result["completion"],
            {
                "is_complete": False,
                "stop_reason": "limit_horses_reached",
                "race_ids": ["HK20260624HV01", "HK20260621ST03"],
                "races_imported": 2,
                "unique_horses_found": 2,
                "horse_profiles_fetched": 1,
                "limit_horses": 1,
                "max_requests": 10,
            },
        )
        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalHorse.objects.count(), 0)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_hkjc_network_dry_run_reports_incomplete_when_horse_limit_truncates_profiles(self):
        # Mutation: without completion metadata, a limited sample can be mistaken for a complete 60-day import.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults",
                    text=(fixture_dir / "localresults-meetings-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24",
                    text=self.hkjc_date_page_with_race_links(),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                    text=(fixture_dir / "localresults-race-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                    text=(fixture_dir / "horse-profile-sample.html").read_text(encoding="utf-8"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        importer = HKJCExternalDataImporter(
            HKJCImportOptions(dry_run=True, allow_network=True, request_interval_seconds=0, max_requests=10)
        )

        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            result = importer.import_date_range("2026-04-27", "2026-06-26", limit_races=1, limit_horses=1)

        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(
            result["completion"],
            {
                "is_complete": False,
                "stop_reason": "limit_horses_reached",
                "meetings_found": 3,
                "races_imported": 1,
                "unique_horses_found": 2,
                "horse_profiles_fetched": 1,
                "limit_races": 1,
                "limit_horses": 1,
                "skip_races": 0,
                "max_requests": 10,
            },
        )

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_hkjc_network_plan_only_builds_batches_without_fetching_races_or_horses(self):
        # Mutation: if plan-only fetches race or horse detail pages, the safe preflight can still trigger heavy crawling.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults",
                    text=(fixture_dir / "localresults-meetings-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24",
                    text=self.hkjc_date_page_with_race_links(),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/21",
                    text=self.hkjc_date_page_with_single_race_link("2026/06/21"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/05/27",
                    text=self.hkjc_date_page_with_single_race_link("2026/05/27", race_no=2),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_hkjc_external_data",
                "--recent-days",
                "60",
                "--end-date",
                "2026-06-26",
                "--limit-races",
                "2",
                "--max-requests",
                "10",
                "--allow-network",
                "--plan-only",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["plan_only"])
        self.assertEqual(result["coverage_stats"], {"meetings": 3, "races": 4, "estimated_requests_without_horses": 8})
        self.assertEqual([request["target_type"] for request in result["requests"]], ["meeting_list", "race_date", "race_date", "race_date"])
        self.assertEqual(
            result["batches"],
            [
                {
                    "batch_no": 1,
                    "skip_races": 0,
                    "start_date": "2026-06-24",
                    "end_date": "2026-06-24",
                    "race_ids": ["HK20260624HV01", "HK20260624HV02"],
                    "race_count": 2,
                    "suggested_limit_races": 2,
                },
                {
                    "batch_no": 2,
                    "skip_races": 2,
                    "start_date": "2026-06-21",
                    "end_date": "2026-05-27",
                    "race_ids": ["HK20260621ST01", "HK20260527ST02"],
                    "race_count": 2,
                    "suggested_limit_races": 2,
                },
            ],
        )
        self.assertEqual(ExternalRace.objects.count(), 0)
        self.assertEqual(ExternalHorse.objects.count(), 0)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_hkjc_network_race_batch_commit_writes_horse_profiles_idempotently(self):
        # Mutation: if horse profile payloads are not part of the verified network payload, commit only creates aliases.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        response_cycle = [
            self.hkjc_response(
                url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                text=(fixture_dir / "localresults-race-sample.html").read_text(encoding="utf-8"),
            ),
            self.hkjc_response(
                url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                text=(fixture_dir / "horse-profile-sample.html").read_text(encoding="utf-8"),
            ),
            self.hkjc_response(
                url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2024_K500",
                text=(fixture_dir / "horse-profile-sample.html")
                .read_text(encoding="utf-8")
                .replace("ROSEWOOD FLEETFOOT", "GOLDEN FORTUNE")
                .replace("(J524)", "(K500)"),
            ),
        ]
        mock_get = Mock(side_effect=[*response_cycle, *response_cycle])
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        importer = HKJCExternalDataImporter(
            HKJCImportOptions(
                dry_run=False,
                allow_network=True,
                request_interval_seconds=0,
                max_races=5,
                max_horses=5,
                max_requests=10,
            )
        )

        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            first = importer.import_race_batch(["HK20260624HV01"], limit_horses=2)
            second = importer.import_race_batch(["HK20260624HV01"], limit_horses=2)

        self.assertFalse(first["dry_run"])
        self.assertFalse(second["dry_run"])
        self.assertEqual(ExternalRace.objects.count(), 1)
        self.assertEqual(ExternalRaceEntry.objects.count(), 2)
        self.assertEqual(ExternalRaceResult.objects.count(), 2)
        self.assertEqual(ExternalHorse.objects.count(), 2)
        horse = ExternalHorse.objects.get(source="hkjc", horse_id="HK_2023_J524")
        self.assertEqual(horse.horse_name_en, "ROSEWOOD FLEETFOOT")
        self.assertEqual(horse.country, "NZ")
        alias = ExternalHorseAlias.objects.get(source="hkjc", external_horse_id="HK_2023_J524", normalized_name="ROSEWOOD FLEETFOOT")
        self.assertEqual(alias.horse_id, horse.id)

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=2.5,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_hkjc_network_client_applies_request_interval_between_fetches(self):
        # Mutation: removing rate-limit sleep would make this import issue four consecutive requests with no pause.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults",
                    text=(fixture_dir / "localresults-meetings-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24",
                    text=self.hkjc_date_page_with_race_links(),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1",
                    text=(fixture_dir / "localresults-race-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/horse?horseid=HK_2023_J524",
                    text=(fixture_dir / "horse-profile-sample.html").read_text(encoding="utf-8"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=True, allow_network=True, request_interval_seconds=2.5))

        with patch.object(hkjc_module, "requests", fake_requests, create=True), patch.object(hkjc_module.time, "sleep") as sleep:
            importer.import_date_range("2026-04-27", "2026-06-26", limit_races=1, limit_horses=1)

        sleep.assert_has_calls([call(2.5), call(2.5), call(2.5)])

    def test_hkjc_network_client_retries_transient_timeout_and_records_attempts(self):
        # Mutation: without retry, one transient HKJC TLS/read timeout aborts a long production batch dry-run.
        from stable.services import external_hkjc_data as hkjc_module

        response = self.hkjc_response(url="https://hkjc.example.test/horse", text="<html></html>")
        mock_get = Mock(side_effect=[requests.exceptions.ReadTimeout("handshake timed out"), response])
        fake_exceptions = type("FakeRequestExceptions", (), {"RequestException": requests.RequestException})
        fake_requests = type("FakeRequests", (), {"get": mock_get, "exceptions": fake_exceptions})
        client = hkjc_module.HKJCNetworkClient(
            HKJCImportOptions(dry_run=True, allow_network=True, request_interval_seconds=0, max_requests=10)
        )

        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            result = client.get("https://hkjc.example.test/horse", target_type="horse", target_id="HK_2022_H293")

        self.assertEqual(result.status_code, 200)
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(
            client.requests,
            [
                {
                    "url": "https://hkjc.example.test/horse",
                    "status_code": None,
                    "target_type": "horse",
                    "target_id": "HK_2022_H293",
                    "attempt": 1,
                    "error": "handshake timed out",
                },
                {
                    "url": "https://hkjc.example.test/horse",
                    "status_code": 200,
                    "target_type": "horse",
                    "target_id": "HK_2022_H293",
                    "attempt": 2,
                },
            ],
        )

    @override_settings(
        HKJC_IMPORT_NETWORK_BASE_URL="https://hkjc.example.test",
        HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        HKJC_IMPORT_MAX_RACES_PER_RUN=5,
        HKJC_IMPORT_MAX_HORSES_PER_RUN=5,
        HKJC_IMPORT_MAX_REQUESTS_PER_RUN=2,
    )
    def test_hkjc_network_import_stops_when_request_limit_is_exceeded(self):
        # Mutation: if request counting happens after fetch, a low max_requests guard cannot stop a large range early.
        from pathlib import Path

        from stable.services import external_hkjc_data as hkjc_module

        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "hkjc" / "html"
        mock_get = Mock(
            side_effect=[
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults",
                    text=(fixture_dir / "localresults-meetings-sample.html").read_text(encoding="utf-8"),
                ),
                self.hkjc_response(
                    url="https://hkjc.example.test/en-us/local/information/localresults?racedate=2026/06/24",
                    text=self.hkjc_date_page_with_race_links(),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        importer = HKJCExternalDataImporter(HKJCImportOptions(dry_run=True, allow_network=True, max_requests=2))

        with patch.object(hkjc_module, "requests", fake_requests, create=True):
            with self.assertRaisesRegex(HKJCImportError, "max_requests"):
                importer.import_date_range("2026-04-27", "2026-06-26", limit_races=1, limit_horses=1)

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(ExternalRace.objects.count(), 0)


class ExternalDataSourceChoicesTests(TestCase):
    def test_all_external_importer_sources_are_declared_choices(self):
        from stable.services.external_france_racing_data import (
            FRANCE_EXTERNAL_SOURCE,
            GENY_FRANCE_EXTERNAL_SOURCE,
        )
        from stable.services.external_uk_racing_data import UK_EXTERNAL_SOURCE
        from stable.services.external_us_racing_data import US_EXTERNAL_SOURCE

        declared_sources = set(ExternalDataSource.values)

        self.assertIn(UK_EXTERNAL_SOURCE, declared_sources)
        self.assertIn(FRANCE_EXTERNAL_SOURCE, declared_sources)
        self.assertIn(GENY_FRANCE_EXTERNAL_SOURCE, declared_sources)
        self.assertIn(US_EXTERNAL_SOURCE, declared_sources)


class UKExternalDataImportTests(TestCase):
    def sporting_life_fixture(self, name: str) -> str:
        from pathlib import Path

        path = Path(__file__).resolve().parent / "fixtures" / "uk" / "sporting_life" / name
        return path.read_text(encoding="utf-8")

    def uk_response(self, *, url: str, text: str, status_code: int = 200):
        response = Mock()
        response.status_code = status_code
        response.url = url
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.text = text
        response.json.side_effect = ValueError("not json")
        return response

    def test_sporting_life_results_page_parses_race_links(self):
        # Mutation: if the parser only detects generic /racing links, UK live planning cannot build exact race batches.
        from stable.services.external_uk_racing_data import SportingLifeHTMLParser

        parser = SportingLifeHTMLParser()

        race_links = parser.parse_result_race_links(
            self.sporting_life_fixture("results-date-sample.html"),
            source_url="https://www.sportinglife.com/racing/results/2026-06-26",
        )

        self.assertEqual(
            race_links,
            [
                {
                    "race_id": "SL924406",
                    "race_date": "2026-06-26",
                    "venue": "yarmouth",
                    "race_no": "924406",
                    "url": "https://www.sportinglife.com/racing/racecards/2026-06-26/yarmouth/racecard/924406/download-the-free-attheraces-app-handicap",
                },
                {
                    "race_id": "SL924407",
                    "race_date": "2026-06-26",
                    "venue": "newmarket",
                    "race_no": "924407",
                    "url": "https://www.sportinglife.com/racing/racecards/2026-06-26/newmarket/racecard/924407/british-stallion-studs-ebf-fillies-novice-stakes",
                },
            ],
        )

    def test_sporting_life_racecard_parses_runners_results_and_profile_links(self):
        # Mutation: if horse profile ids are not extracted, the 60-day import cannot fetch involved horse details.
        from stable.services.external_uk_racing_data import SportingLifeHTMLParser

        parser = SportingLifeHTMLParser()

        race = parser.parse_racecard(
            self.sporting_life_fixture("racecard-sample.html"),
            race_id="SL924406",
            race_date="2026-06-26",
            venue="yarmouth",
            source_url="https://www.sportinglife.com/racing/racecards/2026-06-26/yarmouth/racecard/924406/download-the-free-attheraces-app-handicap",
        )

        self.assertEqual(race["race_id"], "SL924406")
        self.assertEqual(race["race_name"], "Download The Free At The Races App Handicap")
        self.assertEqual(race["venue"], "yarmouth")
        self.assertEqual(race["race_date"], "2026-06-26")
        self.assertEqual(race["race_class"], "Class 5")
        self.assertEqual(race["distance"], "1m 2f")
        self.assertEqual(race["going"], "Good to Firm")
        self.assertEqual(race["surface"], "Turf")
        self.assertEqual(race["prize_money"], "Winner £4,711")
        self.assertEqual(len(race["entries"]), 2)
        self.assertEqual(race["entries"][0]["horse_id"], "1212905")
        self.assertEqual(race["entries"][0]["horse_name_en"], "Sea Legend")
        self.assertEqual(race["entries"][0]["jockey"], "Oisin Murphy")
        self.assertEqual(race["results"][0]["finish_position"], "1")
        self.assertEqual(race["results"][1]["odds"], "4/1")

    def test_sporting_life_horse_profile_parses_identity_and_breeding(self):
        # Mutation: if profile dt/dd fields are not mapped, UK horse pages would create aliases without useful detail.
        from stable.services.external_uk_racing_data import SportingLifeHTMLParser

        parser = SportingLifeHTMLParser()

        horse = parser.parse_horse_profile(
            self.sporting_life_fixture("horse-profile-sample.html"),
            horse_id="1212905",
            source_url="https://www.sportinglife.com/racing/profiles/horse/1212905/sea-legend",
        )

        self.assertEqual(horse["horse_id"], "1212905")
        self.assertEqual(horse["horse_name_en"], "Sea Legend")
        self.assertEqual(horse["age"], "4")
        self.assertEqual(horse["sex"], "Gelding")
        self.assertEqual(horse["trainer"], "Andrew Balding")
        self.assertEqual(horse["owner"], "Kingsclere Racing Club")
        self.assertEqual(horse["sire"], "Sea The Stars")
        self.assertEqual(horse["dam"], "Urban Castle")
        self.assertEqual(horse["country"], "GB")
        self.assertEqual(horse["record_summary"], "21-3521")

    @override_settings(
        UK_IMPORT_NETWORK_BASE_URL="https://www.sportinglife.com",
        UK_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        UK_IMPORT_MAX_RACES_PER_RUN=5,
        UK_IMPORT_MAX_HORSES_PER_RUN=5,
        UK_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_uk_recent_days_dry_run_fetches_races_and_horse_profiles_without_writing(self):
        # Mutation: if UK dry-run writes External* rows, the production safety gate is bypassed before confirmation.
        from stable.services import external_uk_racing_data as uk_module

        mock_get = Mock(
            side_effect=[
                self.uk_response(
                    url="https://www.sportinglife.com/racing/results/2026-06-26",
                    text=self.sporting_life_fixture("results-date-sample.html"),
                ),
                self.uk_response(
                    url="https://www.sportinglife.com/racing/racecards/2026-06-26/yarmouth/racecard/924406/download-the-free-attheraces-app-handicap",
                    text=self.sporting_life_fixture("racecard-sample.html"),
                ),
                self.uk_response(
                    url="https://www.sportinglife.com/racing/profiles/horse/1212905",
                    text=self.sporting_life_fixture("horse-profile-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(uk_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_uk_external_data",
                "--recent-days",
                "1",
                "--end-date",
                "2026-06-26",
                "--limit-races",
                "1",
                "--limit-horses",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["network_probe"])
        self.assertEqual(result["source"], "sporting_life")
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual([request["target_type"] for request in result["requests"]], ["result_date", "race", "horse"])
        self.assertEqual(result["completion"]["stop_reason"], "limit_horses_reached")
        self.assertEqual(ExternalRace.objects.filter(source="sporting_life").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="sporting_life").count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.filter(source="sporting_life").count(), 0)

    @override_settings(
        UK_IMPORT_NETWORK_BASE_URL="https://www.sportinglife.com",
        UK_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        UK_IMPORT_MAX_RACES_PER_RUN=5,
        UK_IMPORT_MAX_HORSES_PER_RUN=5,
        UK_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_uk_recent_days_dry_run_supports_skip_races_for_batch_resume(self):
        # Mutation: without skip-races, each UK batch restarts from the same earliest race in the 60-day window.
        from stable.services import external_uk_racing_data as uk_module

        mock_get = Mock(
            side_effect=[
                self.uk_response(
                    url="https://www.sportinglife.com/racing/results/2026-06-26",
                    text=self.sporting_life_fixture("results-date-sample.html"),
                ),
                self.uk_response(
                    url="https://www.sportinglife.com/racing/racecards/2026-06-26/newmarket/racecard/924407/british-stallion-studs-ebf-fillies-novice-stakes",
                    text=self.sporting_life_fixture("racecard-sample.html"),
                ),
                self.uk_response(
                    url="https://www.sportinglife.com/racing/profiles/horse/1212905",
                    text=self.sporting_life_fixture("horse-profile-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(uk_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_uk_external_data",
                "--recent-days",
                "1",
                "--end-date",
                "2026-06-26",
                "--skip-races",
                "1",
                "--limit-races",
                "1",
                "--limit-horses",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertEqual([request["target_type"] for request in result["requests"]], ["result_date", "race", "horse"])
        self.assertEqual(result["requests"][1]["target_id"], "SL924407")
        self.assertEqual(result["completion"]["skip_races"], 1)
        self.assertEqual(result["completion"]["race_links_selected"], 1)
        self.assertEqual(ExternalRace.objects.filter(source="sporting_life").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="sporting_life").count(), 0)

    @override_settings(
        UK_IMPORT_NETWORK_BASE_URL="https://www.sportinglife.com",
        UK_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        UK_IMPORT_MAX_RACES_PER_RUN=5,
        UK_IMPORT_MAX_HORSES_PER_RUN=5,
        UK_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_uk_recent_days_plan_only_lists_race_batches_without_fetching_races(self):
        # Mutation: without plan-only, operators cannot size the full 60-day UK window before starting race/profile requests.
        from stable.services import external_uk_racing_data as uk_module

        mock_get = Mock(
            return_value=self.uk_response(
                url="https://www.sportinglife.com/racing/results/2026-06-26",
                text=self.sporting_life_fixture("results-date-sample.html"),
            )
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(uk_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_uk_external_data",
                "--recent-days",
                "1",
                "--end-date",
                "2026-06-26",
                "--plan-only",
                "--batch-size",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["plan_only"])
        self.assertEqual(result["source"], "sporting_life")
        self.assertEqual(result["coverage_stats"], {"races": 2, "entries": 0, "results": 0, "horses": 0})
        self.assertEqual([request["target_type"] for request in result["requests"]], ["result_date"])
        self.assertEqual(result["completion"]["race_links_found"], 2)
        self.assertEqual(result["completion"]["batch_size"], 1)
        self.assertEqual(result["completion"]["batches"], 2)
        self.assertEqual(result["batches"][1]["skip_races"], 1)
        self.assertEqual(result["batches"][1]["race_ids"], ["SL924407"])
        self.assertEqual(
            result["batches"][1]["race_urls"],
            [
                "https://www.sportinglife.com/racing/racecards/2026-06-26/newmarket/racecard/924407/british-stallion-studs-ebf-fillies-novice-stakes",
            ],
        )
        self.assertEqual(ExternalRace.objects.filter(source="sporting_life").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="sporting_life").count(), 0)

    @override_settings(
        UK_IMPORT_NETWORK_BASE_URL="https://www.sportinglife.com",
        UK_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        UK_IMPORT_MAX_RACES_PER_RUN=5,
        UK_IMPORT_MAX_HORSES_PER_RUN=5,
        UK_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_uk_plan_only_excludes_non_uk_race_links(self):
        # Mutation: Sporting Life results include Irish/overseas cards; UK batches must not count them as UK races.
        from stable.services import external_uk_racing_data as uk_module

        html = """
        <a href="/racing/racecards/2026-06-26/newmarket/racecard/924388/debenhamscom-handicap">Newmarket</a>
        <a href="/racing/racecards/2026-06-26/curragh/racecard/924649/schweppes-trophy-handicap">Curragh</a>
        <a href="/racing/racecards/2026-06-26/laurel-park/racecard/925165/race-3-maiden-claiming">Laurel</a>
        """
        mock_get = Mock(
            return_value=self.uk_response(
                url="https://www.sportinglife.com/racing/results/2026-06-26",
                text=html,
            )
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(uk_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_uk_external_data",
                "--recent-days",
                "1",
                "--end-date",
                "2026-06-26",
                "--plan-only",
                "--batch-size",
                "5",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertEqual(result["completion"]["race_links_found"], 1)
        self.assertEqual(result["batches"][0]["race_ids"], ["SL924388"])
        self.assertEqual(
            result["batches"][0]["race_urls"],
            ["https://www.sportinglife.com/racing/racecards/2026-06-26/newmarket/racecard/924388/debenhamscom-handicap"],
        )

    @override_settings(
        UK_IMPORT_NETWORK_BASE_URL="https://www.sportinglife.com",
        UK_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        UK_IMPORT_MAX_RACES_PER_RUN=5,
        UK_IMPORT_MAX_HORSES_PER_RUN=5,
        UK_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_uk_race_urls_dry_run_fetches_exact_races_without_date_scan(self):
        # Mutation: if exact race batches still scan date pages, later UK batches waste requests and increase rate-limit risk.
        from stable.services import external_uk_racing_data as uk_module

        race_url = "https://www.sportinglife.com/racing/racecards/2026-06-26/newmarket/racecard/924407/british-stallion-studs-ebf-fillies-novice-stakes"
        mock_get = Mock(
            side_effect=[
                self.uk_response(
                    url=race_url,
                    text=self.sporting_life_fixture("racecard-sample.html"),
                ),
                self.uk_response(
                    url="https://www.sportinglife.com/racing/profiles/horse/1212905",
                    text=self.sporting_life_fixture("horse-profile-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(uk_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_uk_external_data",
                "--race-urls",
                race_url,
                "--limit-horses",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["target_type"], "race_urls")
        self.assertEqual([request["target_type"] for request in result["requests"]], ["race", "horse"])
        self.assertEqual(result["completion"]["race_links_found"], 1)
        self.assertEqual(result["completion"]["race_links_selected"], 1)
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(ExternalRace.objects.filter(source="sporting_life").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="sporting_life").count(), 0)

    @override_settings(
        UK_IMPORT_NETWORK_BASE_URL="https://www.sportinglife.com",
        UK_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        UK_IMPORT_MAX_RACES_PER_RUN=5,
        UK_IMPORT_MAX_HORSES_PER_RUN=5,
        UK_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_uk_commit_rejects_incomplete_profile_batch(self):
        # Mutation: production commit must not write a batch whose horse-profile fetch was truncated by limits.
        from stable.services import external_uk_racing_data as uk_module

        race_url = "https://www.sportinglife.com/racing/racecards/2026-06-26/newmarket/racecard/924407/british-stallion-studs-ebf-fillies-novice-stakes"
        mock_get = Mock(
            side_effect=[
                self.uk_response(
                    url=race_url,
                    text=self.sporting_life_fixture("racecard-sample.html"),
                ),
                self.uk_response(
                    url="https://www.sportinglife.com/racing/profiles/horse/1212905",
                    text=self.sporting_life_fixture("horse-profile-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(uk_module, "requests", fake_requests, create=True):
            with self.assertRaisesRegex(CommandError, "incomplete"):
                call_command(
                    "import_uk_external_data",
                    "--race-urls",
                    race_url,
                    "--limit-horses",
                    "1",
                    "--allow-network",
                    "--commit",
                    stdout=StringIO(),
                )

        self.assertEqual(ExternalDataImportRun.objects.filter(source="sporting_life").count(), 0)
        self.assertEqual(ExternalRace.objects.filter(source="sporting_life").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="sporting_life").count(), 0)

    @override_settings(
        UK_IMPORT_NETWORK_BASE_URL="https://www.sportinglife.com",
        UK_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        UK_IMPORT_MAX_RACES_PER_RUN=5,
        UK_IMPORT_MAX_HORSES_PER_RUN=5,
        UK_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_uk_race_urls_commit_writes_external_tables_idempotently(self):
        # Mutation: full UK ingestion needs the exact race batch path to be writable and idempotent, not only dry-run proof.
        from stable.services import external_uk_racing_data as uk_module

        race_url = "https://www.sportinglife.com/racing/racecards/2026-06-26/newmarket/racecard/924407/british-stallion-studs-ebf-fillies-novice-stakes"
        responses = [
            self.uk_response(
                url=race_url,
                text=self.sporting_life_fixture("racecard-sample.html"),
            ),
            self.uk_response(
                url="https://www.sportinglife.com/racing/profiles/horse/1212905",
                text=self.sporting_life_fixture("horse-profile-sample.html"),
            ),
            self.uk_response(
                url="https://www.sportinglife.com/racing/profiles/horse/328651",
                text=self.sporting_life_fixture("horse-profile-sample.html").replace("Sea Legend", "City Streak"),
            ),
        ]
        mock_get = Mock(side_effect=[*responses, *responses])
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(uk_module, "requests", fake_requests, create=True):
            first = StringIO()
            second = StringIO()

            for out in (first, second):
                call_command(
                    "import_uk_external_data",
                    "--race-urls",
                    race_url,
                    "--allow-network",
                    "--commit",
                    stdout=out,
                )

        result = json.loads(second.getvalue())
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["source"], "sporting_life")
        self.assertEqual(result["target_type"], "race_urls")
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(ExternalDataImportRun.objects.filter(source="sporting_life", status=ExternalImportStatus.SUCCESS).count(), 2)
        self.assertEqual(ExternalRace.objects.filter(source="sporting_life").count(), 1)
        self.assertEqual(ExternalRaceEntry.objects.filter(source="sporting_life").count(), 2)
        self.assertEqual(ExternalRaceResult.objects.filter(source="sporting_life").count(), 2)
        self.assertEqual(ExternalHorse.objects.filter(source="sporting_life").count(), 2)
        self.assertEqual(ExternalHorseAlias.objects.filter(source="sporting_life").count(), 2)
        self.assertFalse(ExternalDataImportLock.objects.get(source="sporting_life").locked_by_run_id)


class FranceExternalDataImportTests(TestCase):
    def france_galop_fixture(self, name: str) -> str:
        from pathlib import Path

        path = Path(__file__).resolve().parent / "fixtures" / "france_galop" / name
        return path.read_text(encoding="utf-8")

    def france_response(self, *, url: str, text: str, status_code: int = 200):
        response = Mock()
        response.status_code = status_code
        response.url = url
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.text = text
        response.json.side_effect = ValueError("not json")
        return response

    def test_france_galop_today_page_parses_meeting_links(self):
        # Mutation: if meeting ids are not preserved, France date-range crawling cannot fetch race detail pages.
        from stable.services.external_france_racing_data import FranceGalopHTMLParser

        parser = FranceGalopHTMLParser()

        meetings = parser.parse_meeting_links(
            self.france_galop_fixture("racing-today-sample.html"),
            race_date="2026-06-26",
            source_url="https://www.france-galop.com/en/racing/today",
        )

        self.assertEqual(
            meetings,
            [
                {
                    "meeting_id": "UUI1MEN3bUdDZ09lcDluYm41NGxndz09",
                    "race_date": "2026-06-26",
                    "venue": "DEAUVILLE",
                    "url": "https://www.france-galop.com/en/racing/meeting/20260626/UUI1MEN3bUdDZ09lcDluYm41NGxndz09",
                },
                {
                    "meeting_id": "bFM4ZXA3eFQ0TGVkSEhKR0FRamMyUT09",
                    "race_date": "2026-06-26",
                    "venue": "LA TESTE",
                    "url": "https://www.france-galop.com/en/racing/meeting/20260626/bFM4ZXA3eFQ0TGVkSEhKR0FRamMyUT09",
                },
            ],
        )

    def test_france_galop_race_detail_parses_results_and_horse_detail_rows(self):
        # Mutation: if detail rows are treated as plain runner links, sire/dam/owner/trainer fields are lost.
        from stable.services.external_france_racing_data import FranceGalopHTMLParser

        parser = FranceGalopHTMLParser()

        race = parser.parse_race_detail(
            self.france_galop_fixture("race-detail-sample.html"),
            race_id="FG2026P-Mk5FdWZLYVplaEljbmRZckU4bEo3UT09",
            source_url="https://www.france-galop.com/en/racing/detail/2026/P/Mk5FdWZLYVplaEljbmRZckU4bEo3UT09",
        )

        self.assertEqual(race["race_name"], "PRIX ADELAIDE")
        self.assertEqual(race["race_date"], "2026-06-26")
        self.assertEqual(race["venue"], "DEAUVILLE")
        self.assertEqual(race["distance"], "1.900 meters")
        self.assertEqual(race["surface"], "PSF")
        self.assertEqual(race["going"], "LENTE")
        self.assertEqual(len(race["entries"]), 2)
        self.assertEqual(race["entries"][0]["horse_id"], "UVIvUnZsZ3lqYUM4b21vTFdZK1d5UT09")
        self.assertEqual(race["entries"][0]["horse_name_en"], "SHEERAN")
        self.assertEqual(race["entries"][0]["sex"], "F")
        self.assertEqual(race["entries"][0]["age"], "3")
        self.assertEqual(race["entries"][0]["sire"], "DUBAWI")
        self.assertEqual(race["entries"][0]["dam"], "SOLSTICIA")
        self.assertEqual(race["entries"][0]["owner"], "WERTHEIMER & FRERE")
        self.assertEqual(race["results"][1]["finish_position"], "2")
        self.assertEqual(race["results"][1]["margin"], "3.5")

    @override_settings(
        FRANCE_IMPORT_NETWORK_BASE_URL="https://www.france-galop.com",
        FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        FRANCE_IMPORT_MAX_RACES_PER_RUN=5,
        FRANCE_IMPORT_MAX_HORSES_PER_RUN=20,
        FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_france_galop_dry_run_fetches_meeting_and_race_detail_without_writing(self):
        # Mutation: France Galop dry-run must not create External* rows while horse profile pages still require login.
        from stable.services import external_france_racing_data as france_module

        mock_get = Mock(
            side_effect=[
                self.france_response(
                    url="https://www.france-galop.com/en/racing/today",
                    text=self.france_galop_fixture("racing-today-sample.html"),
                ),
                self.france_response(
                    url="https://www.france-galop.com/en/racing/meeting/20260626/UUI1MEN3bUdDZ09lcDluYm41NGxndz09",
                    text=self.france_galop_fixture("meeting-sample.html"),
                ),
                self.france_response(
                    url="https://www.france-galop.com/en/racing/detail/2026/P/Mk5FdWZLYVplaEljbmRZckU4bEo3UT09",
                    text=self.france_galop_fixture("race-detail-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(france_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_france_external_data",
                "--race-date",
                "2026-06-26",
                "--limit-races",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["source"], "france_galop")
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual([request["target_type"] for request in result["requests"]], ["race_date", "meeting", "race"])
        self.assertEqual(result["completion"]["horse_profile_source"], "race_detail_rows")
        self.assertEqual(ExternalRace.objects.filter(source="france_galop").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="france_galop").count(), 0)

    def test_geny_date_page_parses_french_race_links(self):
        # Mutation: Geny date pages also list foreign meetings; those must not enter France import batches.
        from stable.services.external_france_racing_data import GenyFranceHTMLParser

        parser = GenyFranceHTMLParser()

        links = parser.parse_race_links(
            self.france_galop_fixture("geny-date-sample.html"),
            race_date="2026-06-24",
            source_url="https://www.geny.com/reunions-courses-pmu/_d2026-06-24",
        )

        self.assertEqual(len(links), 3)
        self.assertEqual(links[1]["race_id"], "GENY1662144")
        self.assertEqual(links[1]["venue"], "Chantilly")
        self.assertEqual(links[1]["meeting_number"], "R2")
        self.assertEqual(links[1]["race_number"], "1")
        self.assertEqual(links[1]["race_name"], "Prix du Clos de la Barre")
        self.assertEqual(
            links[1]["partants_url"],
            "https://www.geny.com/partants-pmu/2026-06-24-chantilly-pmu-prix-du-clos-de-la-barre_c1662144",
        )
        self.assertEqual(
            links[1]["results_url"],
            "https://www.geny.com/arrivee-et-rapports-pmu/2026-06-24-pmu-prix-du-clos-de-la-barre_c1662144",
        )
        self.assertNotIn("Happy Valley", {link["venue"] for link in links})

    def test_geny_partants_and_results_parse_horse_rows(self):
        # Mutation: if the Geny runner onclick payload is ignored, horse ids and profile references disappear.
        from stable.services.external_france_racing_data import GenyFranceHTMLParser

        parser = GenyFranceHTMLParser()

        race = parser.parse_partants(
            self.france_galop_fixture("geny-partants-sample.html"),
            race_link={
                "race_id": "GENY1662144",
                "race_date": "2026-06-24",
                "venue": "Chantilly",
                "meeting_number": "R2",
                "race_number": "1",
                "race_name": "Prix du Clos de la Barre",
                "partants_url": "https://www.geny.com/partants-pmu/2026-06-24-chantilly-pmu-prix-du-clos-de-la-barre_c1662144",
            },
        )
        results = parser.parse_results(self.france_galop_fixture("geny-results-sample.html"))

        self.assertEqual(len(race["entries"]), 2)
        self.assertEqual(race["entries"][1]["horse_id"], "2814630")
        self.assertEqual(race["entries"][1]["horse_name_en"], "Zakharova")
        self.assertEqual(race["entries"][1]["horse_number"], "6")
        self.assertEqual(race["entries"][1]["barrier"], "5")
        self.assertEqual(race["entries"][1]["sex"], "F")
        self.assertEqual(race["entries"][1]["age"], "4")
        self.assertEqual(race["entries"][1]["weight"], "54,5")
        self.assertEqual(race["entries"][1]["jockey"], "C. Belmont")
        self.assertEqual(race["entries"][1]["trainer"], "F. Belmont")
        self.assertEqual(race["entries"][1]["record_summary"], "0p8p(25)1p")
        self.assertEqual(race["entries"][1]["rating"], "43")
        self.assertEqual(race["entries"][1]["odds"], "27,8")
        self.assertEqual(race["entries"][1]["raw_payload"]["horse_profile_url"], "https://www.geny.com/fr/cheval/2814630/course/1662144")
        self.assertEqual(results[0]["horse_id"], "2814630")
        self.assertEqual(results[0]["finish_position"], "1")
        self.assertEqual(results[0]["horse_number"], "6")
        self.assertEqual(results[0]["margin"], "Courte tête")
        self.assertEqual(results[1]["horse_name_en"], "Waldnebel")

    def test_geny_horse_profile_parses_identity_breeding_and_connections(self):
        # Mutation: if Geny profile prose is not parsed, France horses keep only row-level race fields.
        from stable.services.external_france_racing_data import GenyFranceHTMLParser

        parser = GenyFranceHTMLParser()

        horse = parser.parse_horse_profile(
            self.france_galop_fixture("geny-horse-profile-sample.html"),
            horse_id="2814630",
            source_url="https://www.geny.com/fr/cheval/2814630/course/1662144",
        )

        self.assertEqual(horse["horse_id"], "2814630")
        self.assertEqual(horse["horse_name_en"], "Zakharova")
        self.assertEqual(horse["sex"], "Femelle")
        self.assertEqual(horse["age"], "4")
        self.assertEqual(horse["color"], "bai")
        self.assertEqual(horse["sire"], "Zelzal")
        self.assertEqual(horse["dam"], "Diva Cattiva")
        self.assertEqual(horse["trainer"], "François Belmont")
        self.assertEqual(horse["owner"], "François Belmont")
        self.assertEqual(horse["record_summary"], "0p8p(25)1p3p7p3p6p(24)7p")
        self.assertEqual(horse["earnings"], "57 100 €")

    @override_settings(
        GENY_FRANCE_IMPORT_NETWORK_BASE_URL="https://www.geny.com",
        FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        FRANCE_IMPORT_MAX_RACES_PER_RUN=5,
        FRANCE_IMPORT_MAX_HORSES_PER_RUN=20,
        FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_geny_france_recent_days_dry_run_fetches_date_partants_results_without_writing(self):
        # Mutation: Geny is the historical France source; dry-run batches must support date windows and race offsets.
        from stable.services import external_france_racing_data as france_module

        mock_get = Mock(
            side_effect=[
                self.france_response(
                    url="https://www.geny.com/reunions-courses-pmu/_d2026-06-24",
                    text=self.france_galop_fixture("geny-date-sample.html"),
                ),
                self.france_response(
                    url="https://www.geny.com/partants-pmu/2026-06-24-chantilly-pmu-prix-du-clos-de-la-barre_c1662144",
                    text=self.france_galop_fixture("geny-partants-sample.html"),
                ),
                self.france_response(
                    url="https://www.geny.com/arrivee-et-rapports-pmu/2026-06-24-pmu-prix-du-clos-de-la-barre_c1662144",
                    text=self.france_galop_fixture("geny-results-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(france_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_france_external_data",
                "--source",
                "geny",
                "--recent-days",
                "1",
                "--end-date",
                "2026-06-24",
                "--skip-races",
                "1",
                "--limit-races",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["source"], "geny_france")
        self.assertEqual(result["target_type"], "date_range")
        self.assertEqual(result["target_id"], "2026-06-24..2026-06-24")
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual([request["target_type"] for request in result["requests"]], ["race_date", "partants", "results"])
        self.assertEqual(result["requests"][1]["target_id"], "GENY1662144")
        self.assertEqual(result["completion"]["horse_profile_source"], "geny_partants_rows")
        self.assertEqual(result["completion"]["skip_races"], 1)
        self.assertEqual(ExternalRace.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.filter(source="geny_france").count(), 0)

    @override_settings(
        GENY_FRANCE_IMPORT_NETWORK_BASE_URL="https://www.geny.com",
        FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        FRANCE_IMPORT_MAX_RACES_PER_RUN=5,
        FRANCE_IMPORT_MAX_HORSES_PER_RUN=20,
        FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_geny_france_dry_run_fetches_limited_horse_profiles_without_writing(self):
        # Mutation: without a profile fetch limit, France full ingestion cannot safely prove horse-detail coverage.
        from stable.services import external_france_racing_data as france_module

        mock_get = Mock(
            side_effect=[
                self.france_response(
                    url="https://www.geny.com/reunions-courses-pmu/_d2026-06-24",
                    text=self.france_galop_fixture("geny-date-sample.html"),
                ),
                self.france_response(
                    url="https://www.geny.com/partants-pmu/2026-06-24-chantilly-pmu-prix-du-clos-de-la-barre_c1662144",
                    text=self.france_galop_fixture("geny-partants-sample.html"),
                ),
                self.france_response(
                    url="https://www.geny.com/arrivee-et-rapports-pmu/2026-06-24-pmu-prix-du-clos-de-la-barre_c1662144",
                    text=self.france_galop_fixture("geny-results-sample.html"),
                ),
                self.france_response(
                    url="https://www.geny.com/fr/cheval/2818930/course/1662144",
                    text=self.france_galop_fixture("geny-horse-profile-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(france_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_france_external_data",
                "--source",
                "geny",
                "--recent-days",
                "1",
                "--end-date",
                "2026-06-24",
                "--skip-races",
                "1",
                "--limit-races",
                "1",
                "--limit-horses",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual([request["target_type"] for request in result["requests"]], ["race_date", "partants", "results", "horse"])
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(result["completion"]["unique_horses_found"], 2)
        self.assertEqual(result["completion"]["horse_profiles_fetched"], 1)
        self.assertEqual(result["completion"]["stop_reason"], "limit_horses_reached")
        self.assertEqual(ExternalRace.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.filter(source="geny_france").count(), 0)

    @override_settings(
        GENY_FRANCE_IMPORT_NETWORK_BASE_URL="https://www.geny.com",
        FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        FRANCE_IMPORT_MAX_RACES_PER_RUN=5,
        FRANCE_IMPORT_MAX_HORSES_PER_RUN=20,
        FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_geny_france_plan_only_lists_race_batches_without_fetching_races(self):
        # Mutation: without a Geny plan-only map, French 60-day batches cannot be sized before partants/results requests.
        from stable.services import external_france_racing_data as france_module

        mock_get = Mock(
            return_value=self.france_response(
                url="https://www.geny.com/reunions-courses-pmu/_d2026-06-24",
                text=self.france_galop_fixture("geny-date-sample.html"),
            )
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(france_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_france_external_data",
                "--source",
                "geny",
                "--recent-days",
                "1",
                "--end-date",
                "2026-06-24",
                "--plan-only",
                "--batch-size",
                "2",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["plan_only"])
        self.assertEqual(result["source"], "geny_france")
        self.assertEqual(result["coverage_stats"], {"races": 3, "entries": 0, "results": 0, "horses": 0})
        self.assertEqual([request["target_type"] for request in result["requests"]], ["race_date"])
        self.assertEqual(result["completion"]["race_links_found"], 3)
        self.assertEqual(result["completion"]["batches"], 2)
        self.assertEqual(result["batches"][0]["skip_races"], 0)
        self.assertEqual(result["batches"][0]["race_ids"], ["GENY1662153", "GENY1662144"])
        self.assertEqual(result["batches"][1]["skip_races"], 2)
        self.assertEqual(result["batches"][1]["race_ids"], ["GENY1662145"])
        self.assertEqual(ExternalRace.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.filter(source="geny_france").count(), 0)

    @override_settings(
        GENY_FRANCE_IMPORT_NETWORK_BASE_URL="https://www.geny.com",
        FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        FRANCE_IMPORT_MAX_RACES_PER_RUN=5,
        FRANCE_IMPORT_MAX_HORSES_PER_RUN=20,
        FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_geny_france_partants_urls_dry_run_fetches_exact_races_without_date_scan(self):
        # Mutation: if France exact batches rescan date pages, later 60-day runs waste requests and increase 429 risk.
        from stable.services import external_france_racing_data as france_module

        partants_url = "https://www.geny.com/partants-pmu/2026-06-24-chantilly-pmu-prix-du-clos-de-la-barre_c1662144"
        mock_get = Mock(
            side_effect=[
                self.france_response(
                    url=partants_url,
                    text=self.france_galop_fixture("geny-partants-sample.html"),
                ),
                self.france_response(
                    url="https://www.geny.com/arrivee-et-rapports-pmu/2026-06-24-pmu-prix-du-clos-de-la-barre_c1662144",
                    text=self.france_galop_fixture("geny-results-sample.html"),
                ),
                self.france_response(
                    url="https://www.geny.com/fr/cheval/2818930/course/1662144",
                    text=self.france_galop_fixture("geny-horse-profile-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(france_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_france_external_data",
                "--source",
                "geny",
                "--partants-urls",
                partants_url,
                "--limit-horses",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["target_type"], "partants_urls")
        self.assertEqual(result["target_id"], "GENY1662144")
        self.assertEqual([request["target_type"] for request in result["requests"]], ["partants", "results", "horse"])
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(result["completion"]["race_links_found"], 1)
        self.assertEqual(result["completion"]["race_links_selected"], 1)
        self.assertEqual(result["completion"]["race_ids_selected"], ["GENY1662144"])
        self.assertEqual(result["completion"]["horse_profiles_fetched"], 1)
        self.assertEqual(ExternalRace.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="geny_france").count(), 0)

    @override_settings(
        GENY_FRANCE_IMPORT_NETWORK_BASE_URL="https://www.geny.com",
        FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        FRANCE_IMPORT_MAX_RACES_PER_RUN=5,
        FRANCE_IMPORT_MAX_HORSES_PER_RUN=20,
        FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_geny_france_commit_rejects_incomplete_profile_batch(self):
        # Mutation: production commit must not write a Geny batch whose profile fetch stopped at limit_horses.
        from stable.services import external_france_racing_data as france_module

        partants_url = "https://www.geny.com/partants-pmu/2026-06-24-chantilly-pmu-prix-du-clos-de-la-barre_c1662144"
        mock_get = Mock(
            side_effect=[
                self.france_response(
                    url=partants_url,
                    text=self.france_galop_fixture("geny-partants-sample.html"),
                ),
                self.france_response(
                    url="https://www.geny.com/arrivee-et-rapports-pmu/2026-06-24-pmu-prix-du-clos-de-la-barre_c1662144",
                    text=self.france_galop_fixture("geny-results-sample.html"),
                ),
                self.france_response(
                    url="https://www.geny.com/fr/cheval/2818930/course/1662144",
                    text=self.france_galop_fixture("geny-horse-profile-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(france_module, "requests", fake_requests, create=True):
            with self.assertRaisesRegex(CommandError, "incomplete"):
                call_command(
                    "import_france_external_data",
                    "--source",
                    "geny",
                    "--partants-urls",
                    partants_url,
                    "--limit-horses",
                    "1",
                    "--allow-network",
                    "--commit",
                    stdout=StringIO(),
                )

        self.assertEqual(ExternalDataImportRun.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalRace.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="geny_france").count(), 0)

    @override_settings(
        GENY_FRANCE_IMPORT_NETWORK_BASE_URL="https://www.geny.com",
        FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        FRANCE_IMPORT_MAX_RACES_PER_RUN=5,
        FRANCE_IMPORT_MAX_HORSES_PER_RUN=20,
        FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_geny_france_partants_urls_commit_writes_external_tables_idempotently(self):
        # Mutation: full France ingestion should commit exact partants-url batches, not only date-range batches.
        from stable.services import external_france_racing_data as france_module

        partants_url = "https://www.geny.com/partants-pmu/2026-06-24-chantilly-pmu-prix-du-clos-de-la-barre_c1662144"
        responses = [
            self.france_response(
                url=partants_url,
                text=self.france_galop_fixture("geny-partants-sample.html"),
            ),
            self.france_response(
                url="https://www.geny.com/arrivee-et-rapports-pmu/2026-06-24-pmu-prix-du-clos-de-la-barre_c1662144",
                text=self.france_galop_fixture("geny-results-sample.html"),
            ),
            self.france_response(
                url="https://www.geny.com/fr/cheval/2818930/course/1662144",
                text=self.france_galop_fixture("geny-horse-profile-sample.html"),
            ),
            self.france_response(
                url="https://www.geny.com/fr/cheval/2814630/course/1662144",
                text=self.france_galop_fixture("geny-horse-profile-sample.html"),
            ),
        ]
        mock_get = Mock(side_effect=[*responses, *responses])
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(france_module, "requests", fake_requests, create=True):
            first = StringIO()
            second = StringIO()

            for out in (first, second):
                call_command(
                    "import_france_external_data",
                    "--source",
                    "geny",
                    "--partants-urls",
                    partants_url,
                    "--limit-horses",
                    "2",
                    "--allow-network",
                    "--commit",
                    stdout=out,
                )

        result = json.loads(second.getvalue())
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["source"], "geny_france")
        self.assertEqual(result["target_type"], "partants_urls")
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(ExternalDataImportRun.objects.filter(source="geny_france", status=ExternalImportStatus.SUCCESS).count(), 2)
        self.assertEqual(ExternalRace.objects.filter(source="geny_france").count(), 1)
        self.assertEqual(ExternalRaceEntry.objects.filter(source="geny_france").count(), 2)
        self.assertEqual(ExternalRaceResult.objects.filter(source="geny_france").count(), 2)
        self.assertEqual(ExternalHorse.objects.filter(source="geny_france").count(), 2)
        self.assertEqual(ExternalHorseAlias.objects.filter(source="geny_france").count(), 2)
        self.assertFalse(ExternalDataImportLock.objects.get(source="geny_france").locked_by_run_id)

    @override_settings(
        GENY_FRANCE_IMPORT_NETWORK_BASE_URL="https://www.geny.com",
        FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        FRANCE_IMPORT_MAX_RACES_PER_RUN=5,
        FRANCE_IMPORT_MAX_HORSES_PER_RUN=20,
        FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_geny_france_dry_run_stops_safely_on_rate_limit_without_writing(self):
        # Mutation: a Geny 429 must produce resumable dry-run evidence instead of hiding partial progress behind CommandError.
        from stable.services import external_france_racing_data as france_module

        mock_get = Mock(
            side_effect=[
                self.france_response(
                    url="https://www.geny.com/reunions-courses-pmu/_d2026-06-24",
                    text=self.france_galop_fixture("geny-date-sample.html"),
                ),
                self.france_response(
                    url="https://www.geny.com/partants-pmu/2026-06-24-chantilly-pmu-prix-du-clos-de-la-barre_c1662144",
                    text=self.france_galop_fixture("geny-partants-sample.html"),
                ),
                self.france_response(
                    url="https://www.geny.com/arrivee-et-rapports-pmu/2026-06-24-pmu-prix-du-clos-de-la-barre_c1662144",
                    text="rate limited",
                    status_code=429,
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(france_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_france_external_data",
                "--source",
                "geny",
                "--recent-days",
                "1",
                "--end-date",
                "2026-06-24",
                "--skip-races",
                "1",
                "--limit-races",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertFalse(result["completion"]["is_complete"])
        self.assertEqual(result["completion"]["stop_reason"], "rate_limited")
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 0, "horses": 2})
        self.assertEqual(result["requests"][-1]["status_code"], 429)
        self.assertEqual(ExternalRace.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.filter(source="geny_france").count(), 0)

    @override_settings(
        GENY_FRANCE_IMPORT_NETWORK_BASE_URL="https://www.geny.com",
        FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        FRANCE_IMPORT_MAX_RACES_PER_RUN=5,
        FRANCE_IMPORT_MAX_HORSES_PER_RUN=20,
        FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_geny_france_commit_rejects_limited_date_range_batch(self):
        # Mutation: date-range commits should not write a range explicitly truncated by limit_races.
        from stable.services import external_france_racing_data as france_module

        responses = [
            self.france_response(
                url="https://www.geny.com/reunions-courses-pmu/_d2026-06-24",
                text=self.france_galop_fixture("geny-date-sample.html"),
            ),
            self.france_response(
                url="https://www.geny.com/partants-pmu/2026-06-24-chantilly-pmu-prix-du-clos-de-la-barre_c1662144",
                text=self.france_galop_fixture("geny-partants-sample.html"),
            ),
            self.france_response(
                url="https://www.geny.com/arrivee-et-rapports-pmu/2026-06-24-pmu-prix-du-clos-de-la-barre_c1662144",
                text=self.france_galop_fixture("geny-results-sample.html"),
            ),
        ]
        mock_get = Mock(side_effect=responses)
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(france_module, "requests", fake_requests, create=True):
            with self.assertRaisesRegex(CommandError, "incomplete"):
                call_command(
                    "import_france_external_data",
                    "--source",
                    "geny",
                    "--recent-days",
                    "1",
                    "--end-date",
                    "2026-06-24",
                    "--skip-races",
                    "1",
                    "--limit-races",
                    "1",
                    "--allow-network",
                    "--commit",
                    stdout=StringIO(),
                )

        self.assertEqual(ExternalDataImportRun.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalRace.objects.filter(source="geny_france").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="geny_france").count(), 0)


class USExternalDataImportTests(TestCase):
    def hrn_fixture(self, name: str) -> str:
        from pathlib import Path

        path = Path(__file__).resolve().parent / "fixtures" / "us_hrn" / name
        return path.read_text(encoding="utf-8")

    def hrn_response(self, *, url: str, text: str, status_code: int = 200):
        response = Mock()
        response.status_code = status_code
        response.url = url
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.text = text
        response.json.side_effect = ValueError("not json")
        return response

    def test_hrn_track_day_parses_same_date_track_links(self):
        # Mutation: without same-date track links, the US import cannot expand from one seed track to the day slate.
        from stable.services.external_us_racing_data import HorseRacingNationHTMLParser

        parser = HorseRacingNationHTMLParser()

        track_links = parser.parse_track_day_links(
            self.hrn_fixture("track-day-sample.html"),
            race_date="2026-06-25",
            source_url="https://entries.horseracingnation.com/entries-results/churchill-downs/2026-06-25",
        )

        self.assertEqual(
            track_links,
            [
                {
                    "track_slug": "churchill-downs",
                    "race_date": "2026-06-25",
                    "track_name": "Churchill Downs",
                    "url": "https://entries.horseracingnation.com/entries-results/churchill-downs/2026-06-25",
                },
                {
                    "track_slug": "belmont-at-aqueduct",
                    "race_date": "2026-06-25",
                    "track_name": "Belmont at Aqueduct",
                    "url": "https://entries.horseracingnation.com/entries-results/belmont-at-aqueduct/2026-06-25",
                },
                {
                    "track_slug": "woodbine",
                    "race_date": "2026-06-25",
                    "track_name": "Woodbine",
                    "url": "https://entries.horseracingnation.com/entries-results/woodbine/2026-06-25",
                },
            ],
        )

    def test_hrn_track_day_parses_races_entries_results_and_horse_links(self):
        # Mutation: parsing only the summary tables would miss the actual runner/result payload.
        from stable.services.external_us_racing_data import HorseRacingNationHTMLParser

        parser = HorseRacingNationHTMLParser()

        races = parser.parse_track_day_races(
            self.hrn_fixture("track-day-sample.html"),
            race_date="2026-06-25",
            track_slug="churchill-downs",
            track_name="Churchill Downs",
            source_url="https://entries.horseracingnation.com/entries-results/churchill-downs/2026-06-25",
        )

        self.assertEqual(len(races), 1)
        race = races[0]
        self.assertEqual(race["race_id"], "HRN_churchill-downs_2026-06-25_1")
        self.assertEqual(race["race_name"], "Churchill Downs Race # 1")
        self.assertEqual(race["scheduled_start_time"], "5:00 PM")
        self.assertEqual(len(race["entries"]), 2)
        self.assertEqual(race["entries"][0]["horse_id"], "Crystal_Frost")
        self.assertEqual(race["entries"][0]["horse_name_en"], "Crystal Frost")
        self.assertEqual(race["entries"][0]["sire"], "Frosted")
        self.assertEqual(race["entries"][1]["jockey"], "Tyler Gaffalione")
        self.assertEqual(race["results"][0]["horse_name_en"], "Beauxbatons")
        self.assertEqual(race["results"][0]["finish_position"], "1")
        self.assertEqual(race["results"][1]["horse_name_en"], "Crystal Frost")

    def test_hrn_horse_profile_parses_pedigree_owner_and_trainer(self):
        # Mutation: if profile prose is not parsed, US horse aliases would lack the useful detail fields.
        from stable.services.external_us_racing_data import HorseRacingNationHTMLParser

        parser = HorseRacingNationHTMLParser()

        horse = parser.parse_horse_profile(
            self.hrn_fixture("horse-profile-sample.html"),
            horse_id="Avalon_Rose_1",
            source_url="https://www.horseracingnation.com/horse/Avalon_Rose_1",
        )

        self.assertEqual(horse["horse_id"], "Avalon_Rose_1")
        self.assertEqual(horse["horse_name_en"], "Avalon Rose")
        self.assertEqual(horse["age"], "2")
        self.assertEqual(horse["sex"], "Filly")
        self.assertEqual(horse["sire"], "Rock Your World")
        self.assertEqual(horse["dam"], "Freedom Rose")
        self.assertEqual(horse["dams_sire"], "Constitution")
        self.assertEqual(horse["owner"], "James Avansino, Bobby Stephen")
        self.assertEqual(horse["trainer"], "Robert B. Hess Jr.")
        self.assertEqual(horse["country"], "Kentucky, US")

    @override_settings(
        US_IMPORT_ENTRIES_BASE_URL="https://entries.horseracingnation.com",
        US_IMPORT_HRN_BASE_URL="https://www.horseracingnation.com",
        US_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        US_IMPORT_MAX_RACES_PER_RUN=5,
        US_IMPORT_MAX_HORSES_PER_RUN=5,
        US_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_us_hrn_dry_run_fetches_track_day_and_horse_profile_without_writing(self):
        # Mutation: US dry-run must not write External* rows before the source coverage and safety gate are accepted.
        from stable.services import external_us_racing_data as us_module

        mock_get = Mock(
            side_effect=[
                self.hrn_response(
                    url="https://entries.horseracingnation.com/entries-results/2026-06-25",
                    text=self.hrn_fixture("track-day-sample.html"),
                ),
                self.hrn_response(
                    url="https://www.horseracingnation.com/horse/Crystal_Frost",
                    text=self.hrn_fixture("horse-profile-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(us_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_us_external_data",
                "--race-date",
                "2026-06-25",
                "--seed-track",
                "churchill-downs",
                "--limit-tracks",
                "1",
                "--limit-races",
                "1",
                "--limit-horses",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["source"], "horse_racing_nation")
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual([request["target_type"] for request in result["requests"]], ["track_day", "horse"])
        self.assertEqual(result["completion"]["track_days_fetched"], 1)
        self.assertEqual(result["completion"]["horse_profiles_fetched"], 1)
        self.assertEqual(ExternalRace.objects.filter(source="horse_racing_nation").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="horse_racing_nation").count(), 0)

    @override_settings(
        US_IMPORT_ENTRIES_BASE_URL="https://entries.horseracingnation.com",
        US_IMPORT_HRN_BASE_URL="https://www.horseracingnation.com",
        US_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        US_IMPORT_MAX_RACES_PER_RUN=5,
        US_IMPORT_MAX_HORSES_PER_RUN=5,
        US_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_us_hrn_dry_run_reports_only_actual_track_days_fetched(self):
        # Mutation: if limit_races stops on the seed page, reporting all planned track links as fetched overstates coverage.
        from stable.services import external_us_racing_data as us_module

        mock_get = Mock(
            return_value=self.hrn_response(
                url="https://entries.horseracingnation.com/entries-results/churchill-downs/2026-06-25",
                text=self.hrn_fixture("track-day-sample.html"),
            )
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(us_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_us_external_data",
                "--race-date",
                "2026-06-25",
                "--seed-track",
                "churchill-downs",
                "--limit-tracks",
                "3",
                "--limit-races",
                "1",
                "--limit-horses",
                "0",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertEqual([request["target_type"] for request in result["requests"]], ["track_day"])
        self.assertEqual(result["completion"]["track_days_found"], 3)
        self.assertEqual(result["completion"]["track_days_fetched"], 1)

    @override_settings(
        US_IMPORT_ENTRIES_BASE_URL="https://entries.horseracingnation.com",
        US_IMPORT_HRN_BASE_URL="https://www.horseracingnation.com",
        US_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        US_IMPORT_MAX_RACES_PER_RUN=5,
        US_IMPORT_MAX_HORSES_PER_RUN=5,
        US_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_us_hrn_recent_days_dry_run_fetches_date_range_without_writing(self):
        # Mutation: without recent-days/date-range support, US cannot progress from a one-day smoke to a two-month batch.
        from stable.services import external_us_racing_data as us_module

        mock_get = Mock(
            side_effect=[
                self.hrn_response(
                    url="https://entries.horseracingnation.com/entries-results/2026-06-25",
                    text=self.hrn_fixture("track-day-sample.html"),
                ),
                self.hrn_response(
                    url="https://www.horseracingnation.com/horse/Crystal_Frost",
                    text=self.hrn_fixture("horse-profile-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(us_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_us_external_data",
                "--recent-days",
                "1",
                "--end-date",
                "2026-06-25",
                "--seed-track",
                "churchill-downs",
                "--limit-tracks",
                "1",
                "--limit-races",
                "1",
                "--limit-horses",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["source"], "horse_racing_nation")
        self.assertEqual(result["target_type"], "date_range")
        self.assertEqual(result["target_id"], "2026-06-25..2026-06-25")
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual([request["target_type"] for request in result["requests"]], ["track_day", "horse"])
        self.assertEqual(result["requests"][0]["url"], "https://entries.horseracingnation.com/entries-results/2026-06-25")
        self.assertEqual(result["completion"]["race_dates_fetched"], 1)
        self.assertEqual(result["completion"]["track_days_fetched"], 1)
        self.assertEqual(result["completion"]["horse_profiles_fetched"], 1)
        self.assertEqual(ExternalRace.objects.filter(source="horse_racing_nation").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="horse_racing_nation").count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.filter(source="horse_racing_nation").count(), 0)

    @override_settings(
        US_IMPORT_ENTRIES_BASE_URL="https://entries.horseracingnation.com",
        US_IMPORT_HRN_BASE_URL="https://www.horseracingnation.com",
        US_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        US_IMPORT_MAX_RACES_PER_RUN=5,
        US_IMPORT_MAX_HORSES_PER_RUN=5,
        US_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_us_hrn_plan_only_lists_race_batches_without_fetching_horses(self):
        # Mutation: without a plan-only map, the 60-day US crawl cannot be split safely before profile requests.
        from stable.services import external_us_racing_data as us_module

        mock_get = Mock(
            return_value=self.hrn_response(
                url="https://entries.horseracingnation.com/entries-results/2026-06-25",
                text=self.hrn_fixture("track-day-sample.html"),
            )
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(us_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_us_external_data",
                "--recent-days",
                "1",
                "--end-date",
                "2026-06-25",
                "--seed-track",
                "churchill-downs",
                "--limit-tracks",
                "1",
                "--plan-only",
                "--batch-size",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["plan_only"])
        self.assertEqual(result["source"], "horse_racing_nation")
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 0, "results": 0, "horses": 0})
        self.assertEqual([request["target_type"] for request in result["requests"]], ["track_day"])
        self.assertEqual(result["completion"]["race_links_found"], 1)
        self.assertEqual(result["completion"]["batches"], 1)
        self.assertTrue(result["completion"]["coverage_scope_limited"])
        self.assertEqual(result["completion"]["limit_tracks"], 1)
        self.assertEqual(result["batches"][0]["skip_races"], 0)
        self.assertEqual(result["batches"][0]["race_ids"], ["HRN_churchill-downs_2026-06-25_1"])
        self.assertEqual(ExternalRace.objects.filter(source="horse_racing_nation").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="horse_racing_nation").count(), 0)
        self.assertEqual(ExternalDataImportRun.objects.filter(source="horse_racing_nation").count(), 0)

    @override_settings(
        US_IMPORT_ENTRIES_BASE_URL="https://entries.horseracingnation.com",
        US_IMPORT_HRN_BASE_URL="https://www.horseracingnation.com",
        US_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        US_IMPORT_MAX_RACES_PER_RUN=5,
        US_IMPORT_MAX_HORSES_PER_RUN=5,
        US_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_us_hrn_race_ids_dry_run_fetches_exact_races_without_date_scan(self):
        # Mutation: if US exact batches rescan date indexes, later 60-day batches waste requests and raise rate-limit risk.
        from stable.services import external_us_racing_data as us_module

        mock_get = Mock(
            side_effect=[
                self.hrn_response(
                    url="https://entries.horseracingnation.com/entries-results/churchill-downs/2026-06-25",
                    text=self.hrn_fixture("track-day-sample.html"),
                ),
                self.hrn_response(
                    url="https://www.horseracingnation.com/horse/Crystal_Frost",
                    text=self.hrn_fixture("horse-profile-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(us_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_us_external_data",
                "--race-ids",
                "HRN_churchill-downs_2026-06-25_1",
                "--limit-horses",
                "1",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["target_type"], "race_ids")
        self.assertEqual(result["target_id"], "HRN_churchill-downs_2026-06-25_1")
        self.assertEqual([request["target_type"] for request in result["requests"]], ["track_day", "horse"])
        self.assertEqual(result["requests"][0]["url"], "https://entries.horseracingnation.com/entries-results/churchill-downs/2026-06-25")
        self.assertEqual(result["completion"]["race_links_found"], 1)
        self.assertEqual(result["completion"]["race_links_selected"], 1)
        self.assertEqual(result["completion"]["race_ids_selected"], ["HRN_churchill-downs_2026-06-25_1"])
        self.assertEqual(result["completion"]["horse_profiles_fetched"], 1)
        self.assertEqual(ExternalRace.objects.filter(source="horse_racing_nation").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="horse_racing_nation").count(), 0)

    @override_settings(
        US_IMPORT_ENTRIES_BASE_URL="https://entries.horseracingnation.com",
        US_IMPORT_HRN_BASE_URL="https://www.horseracingnation.com",
        US_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        US_IMPORT_MAX_RACES_PER_RUN=5,
        US_IMPORT_MAX_HORSES_PER_RUN=5,
        US_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_us_hrn_commit_rejects_incomplete_profile_batch(self):
        # Mutation: production commit must not write HRN race-id batches whose profile fetch was truncated.
        from stable.services import external_us_racing_data as us_module

        mock_get = Mock(
            side_effect=[
                self.hrn_response(
                    url="https://entries.horseracingnation.com/entries-results/churchill-downs/2026-06-25",
                    text=self.hrn_fixture("track-day-sample.html"),
                ),
                self.hrn_response(
                    url="https://www.horseracingnation.com/horse/Crystal_Frost",
                    text=self.hrn_fixture("horse-profile-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(us_module, "requests", fake_requests, create=True):
            with self.assertRaisesRegex(CommandError, "incomplete"):
                call_command(
                    "import_us_external_data",
                    "--race-ids",
                    "HRN_churchill-downs_2026-06-25_1",
                    "--limit-horses",
                    "1",
                    "--allow-network",
                    "--commit",
                    stdout=StringIO(),
                )

        self.assertEqual(ExternalDataImportRun.objects.filter(source="horse_racing_nation").count(), 0)
        self.assertEqual(ExternalRace.objects.filter(source="horse_racing_nation").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="horse_racing_nation").count(), 0)

    @override_settings(
        US_IMPORT_ENTRIES_BASE_URL="https://entries.horseracingnation.com",
        US_IMPORT_HRN_BASE_URL="https://www.horseracingnation.com",
        US_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        US_IMPORT_MAX_RACES_PER_RUN=5,
        US_IMPORT_MAX_HORSES_PER_RUN=5,
        US_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_us_hrn_race_ids_commit_writes_external_tables_idempotently(self):
        # Mutation: full US ingestion should commit exact race-id batches, not only date-range batches.
        from stable.services import external_us_racing_data as us_module

        responses = [
            self.hrn_response(
                url="https://entries.horseracingnation.com/entries-results/churchill-downs/2026-06-25",
                text=self.hrn_fixture("track-day-sample.html"),
            ),
            self.hrn_response(
                url="https://www.horseracingnation.com/horse/Crystal_Frost",
                text=self.hrn_fixture("horse-profile-sample.html"),
            ),
            self.hrn_response(
                url="https://www.horseracingnation.com/horse/Avalon_Rose_1",
                text=self.hrn_fixture("horse-profile-sample.html"),
            ),
        ]
        mock_get = Mock(side_effect=[*responses, *responses])
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(us_module, "requests", fake_requests, create=True):
            first = StringIO()
            second = StringIO()

            for out in (first, second):
                call_command(
                    "import_us_external_data",
                    "--race-ids",
                    "HRN_churchill-downs_2026-06-25_1",
                    "--allow-network",
                    "--commit",
                    stdout=out,
                )

        result = json.loads(second.getvalue())
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["source"], "horse_racing_nation")
        self.assertEqual(result["target_type"], "race_ids")
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(ExternalDataImportRun.objects.filter(source="horse_racing_nation", status=ExternalImportStatus.SUCCESS).count(), 2)
        self.assertEqual(ExternalRace.objects.filter(source="horse_racing_nation").count(), 1)
        self.assertEqual(ExternalRaceEntry.objects.filter(source="horse_racing_nation").count(), 2)
        self.assertEqual(ExternalRaceResult.objects.filter(source="horse_racing_nation").count(), 2)
        self.assertEqual(ExternalHorse.objects.filter(source="horse_racing_nation").count(), 2)
        self.assertEqual(ExternalHorseAlias.objects.filter(source="horse_racing_nation").count(), 2)
        self.assertFalse(ExternalDataImportLock.objects.get(source="horse_racing_nation").locked_by_run_id)

    @override_settings(
        US_IMPORT_ENTRIES_BASE_URL="https://entries.horseracingnation.com",
        US_IMPORT_HRN_BASE_URL="https://www.horseracingnation.com",
        US_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        US_IMPORT_MAX_RACES_PER_RUN=5,
        US_IMPORT_MAX_HORSES_PER_RUN=5,
        US_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_us_hrn_recent_days_dry_run_supports_skip_races_for_batch_resume(self):
        # Mutation: without skip-races, each US batch restarts from the first race in the date window.
        from stable.services import external_us_racing_data as us_module

        mock_get = Mock(
            side_effect=[
                self.hrn_response(
                    url="https://entries.horseracingnation.com/entries-results/2026-06-25",
                    text=self.hrn_fixture("track-day-sample.html"),
                ),
                self.hrn_response(
                    url="https://entries.horseracingnation.com/entries-results/belmont-at-aqueduct/2026-06-25",
                    text=self.hrn_fixture("track-day-sample.html"),
                ),
            ]
        )
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(us_module, "requests", fake_requests, create=True):
            out = StringIO()

            call_command(
                "import_us_external_data",
                "--recent-days",
                "1",
                "--end-date",
                "2026-06-25",
                "--seed-track",
                "churchill-downs",
                "--limit-tracks",
                "2",
                "--skip-races",
                "1",
                "--limit-races",
                "1",
                "--limit-horses",
                "0",
                "--allow-network",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual([request["target_type"] for request in result["requests"]], ["track_day", "track_day"])
        self.assertEqual(result["requests"][1]["target_id"], "belmont-at-aqueduct:2026-06-25")
        self.assertEqual(result["coverage_stats"], {"races": 1, "entries": 2, "results": 2, "horses": 2})
        self.assertEqual(result["completion"]["skip_races"], 1)
        self.assertEqual(result["completion"]["race_links_found"], 2)
        self.assertEqual(result["completion"]["race_links_selected"], 1)
        self.assertEqual(result["completion"]["race_ids_selected"], ["HRN_belmont-at-aqueduct_2026-06-25_1"])
        self.assertEqual(result["completion"]["horse_profiles_fetched"], 0)
        self.assertEqual(ExternalRace.objects.filter(source="horse_racing_nation").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="horse_racing_nation").count(), 0)

    @override_settings(
        US_IMPORT_ENTRIES_BASE_URL="https://entries.horseracingnation.com",
        US_IMPORT_HRN_BASE_URL="https://www.horseracingnation.com",
        US_IMPORT_REQUEST_INTERVAL_SECONDS=0,
        US_IMPORT_MAX_RACES_PER_RUN=5,
        US_IMPORT_MAX_HORSES_PER_RUN=5,
        US_IMPORT_MAX_REQUESTS_PER_RUN=10,
    )
    def test_us_hrn_commit_rejects_limited_date_range_batch(self):
        # Mutation: date-range commits should not write batches truncated by track/race/profile limits.
        from stable.services import external_us_racing_data as us_module

        responses = [
            self.hrn_response(
                url="https://entries.horseracingnation.com/entries-results/2026-06-25",
                text=self.hrn_fixture("track-day-sample.html"),
            ),
            self.hrn_response(
                url="https://www.horseracingnation.com/horse/Crystal_Frost",
                text=self.hrn_fixture("horse-profile-sample.html"),
            ),
        ]
        mock_get = Mock(side_effect=responses)
        fake_requests = type("FakeRequests", (), {"get": mock_get})
        with patch.object(us_module, "requests", fake_requests, create=True):
            with self.assertRaisesRegex(CommandError, "incomplete"):
                call_command(
                    "import_us_external_data",
                    "--recent-days",
                    "1",
                    "--end-date",
                    "2026-06-25",
                    "--seed-track",
                    "churchill-downs",
                    "--limit-tracks",
                    "1",
                    "--limit-races",
                    "1",
                    "--limit-horses",
                    "1",
                    "--allow-network",
                    "--commit",
                    stdout=StringIO(),
                )

        self.assertEqual(ExternalDataImportRun.objects.filter(source="horse_racing_nation").count(), 0)
        self.assertEqual(ExternalRace.objects.filter(source="horse_racing_nation").count(), 0)
        self.assertEqual(ExternalHorse.objects.filter(source="horse_racing_nation").count(), 0)


class GlobalRacingSpikeIsolationTests(TestCase):
    def external_counts(self) -> dict[str, int]:
        return {
            "ExternalRace": ExternalRace.objects.count(),
            "ExternalRaceEntry": ExternalRaceEntry.objects.count(),
            "ExternalRaceResult": ExternalRaceResult.objects.count(),
            "ExternalHorse": ExternalHorse.objects.count(),
            "ExternalHorseAlias": ExternalHorseAlias.objects.count(),
        }

    def test_equibase_spike_records_counts_and_does_not_write_formal_tables(self):
        # Mutation: if a spike accidentally upserts ExternalRace or aliases, before/after counts diverge.
        before_counts = self.external_counts()

        from stable.services.global_racing_spikes import run_source_spike

        report = run_source_spike(
            source="equibase",
            fixture_payload={
                "sample_url": "https://www.equibase.com/static/entry/RaceCard.html",
                "request_count": 1,
                "fields": {"entries": True, "results": True, "horse_profile": False},
            },
            dry_run=True,
        )

        self.assertEqual(self.external_counts(), before_counts)
        self.assertEqual(report["before_counts"], before_counts)
        self.assertEqual(report["after_counts"], before_counts)
        self.assertEqual(report["source"], "equibase")
        self.assertEqual(report["readiness_status"], "needs_more_spike")
        self.assertFalse(report["wrote_formal_tables"])

    def test_uk_fr_us_spikes_reject_commit_mode(self):
        # Mutation: accepting commit=True for spike sources would bypass the OpenSpec read-only boundary.
        from stable.services.global_racing_spikes import run_source_spike

        for source in ("equibase", "sporting_life_bha", "france_galop"):
            with self.subTest(source=source):
                with self.assertRaisesMessage(ValueError, "read-only spike"):
                    run_source_spike(source=source, fixture_payload={}, dry_run=False, commit=True)


class GlobalRacingImporterCommitGateTests(TestCase):
    def test_plan_batch_command_renders_exact_batch_commands(self):
        # Mutation: full-crawl batches should be driven from plan JSON instead of hand-copying URLs or IDs.
        from stable.services.global_racing_plan import build_plan_batch_command

        cases = [
            (
                {
                    "source": "hkjc",
                    "plan_only": True,
                    "batches": [{"batch_no": 2, "race_ids": ["HK20260624HV01", "HK20260624HV02"]}],
                },
                2,
                "import_hkjc_external_data",
                "--race-ids",
                "HK20260624HV01,HK20260624HV02",
            ),
            (
                {
                    "source": "sporting_life",
                    "plan_only": True,
                    "batches": [{"batch_index": 1, "race_urls": ["https://www.sportinglife.com/racing/racecards/race-a"]}],
                },
                1,
                "import_uk_external_data",
                "--race-urls",
                "https://www.sportinglife.com/racing/racecards/race-a",
            ),
            (
                {
                    "source": "geny_france",
                    "plan_only": True,
                    "batches": [{"batch_index": 3, "partants_urls": ["https://www.geny.com/partants/foo"]}],
                },
                3,
                "import_france_external_data",
                "--partants-urls",
                "https://www.geny.com/partants/foo",
            ),
            (
                {
                    "source": "horse_racing_nation",
                    "plan_only": True,
                    "batches": [{"batch_index": 4, "race_ids": ["HRN_track_2026-06-25_1"]}],
                },
                4,
                "import_us_external_data",
                "--race-ids",
                "HRN_track_2026-06-25_1",
            ),
        ]

        for plan, batch_number, command_name, target_flag, target_value in cases:
            with self.subTest(source=plan["source"]):
                rendered = build_plan_batch_command(plan, batch_number=batch_number, limit_horses=99)

                self.assertEqual(rendered["management_command"], command_name)
                self.assertIn("--allow-network", rendered["args"])
                self.assertIn("--limit-horses", rendered["args"])
                self.assertEqual(rendered["args"][rendered["args"].index(target_flag) + 1], target_value)
                self.assertIn(command_name, rendered["command_line"])

    def test_plan_batch_command_rejects_missing_or_unsafe_plan(self):
        from stable.services.global_racing_plan import GlobalRacingPlanError, build_plan_batch_command

        with self.assertRaisesRegex(GlobalRacingPlanError, "plan_only"):
            build_plan_batch_command({"source": "sporting_life", "batches": []}, batch_number=1)
        with self.assertRaisesRegex(GlobalRacingPlanError, "batch 2"):
            build_plan_batch_command(
                {"source": "sporting_life", "plan_only": True, "batches": [{"batch_index": 1, "race_urls": ["u1"]}]},
                batch_number=2,
            )
        with self.assertRaisesRegex(GlobalRacingPlanError, "target list"):
            build_plan_batch_command(
                {"source": "sporting_life", "plan_only": True, "batches": [{"batch_index": 1, "race_ids": ["SL1"]}]},
                batch_number=1,
            )

    def test_plan_batch_commands_render_all_batches(self):
        # Mutation: full-crawl execution should be able to enumerate every planned batch without manual batch selection.
        from stable.services.global_racing_plan import build_plan_batch_commands

        plan = {
            "source": "sporting_life",
            "plan_only": True,
            "batches": [
                {"batch_index": 1, "race_urls": ["https://www.sportinglife.com/racing/racecards/race-a"]},
                {"batch_index": 2, "race_urls": ["https://www.sportinglife.com/racing/racecards/race-b"]},
            ],
        }

        rendered = build_plan_batch_commands(plan, limit_horses=88)

        self.assertEqual([item["batch_number"] for item in rendered], [1, 2])
        self.assertEqual([item["target_count"] for item in rendered], [1, 1])
        self.assertTrue(all("--limit-horses 88" in item["command_line"] for item in rendered))
        self.assertIn("race-a", rendered[0]["command_line"])
        self.assertIn("race-b", rendered[1]["command_line"])

    def test_plan_batch_command_suggests_stable_output_filename_and_path(self):
        # Mutation: batch command manifests need stable output names so dry-run JSON files are not overwritten or misplaced.
        from stable.services.global_racing_plan import build_plan_batch_command

        plan = {
            "source": "geny_france",
            "plan_only": True,
            "batches": [{"batch_index": 12, "partants_urls": ["https://www.geny.com/partants/foo"]}],
        }

        dry_run = build_plan_batch_command(plan, batch_number=12, output_dir="runtime/global_racing_import/france-geny")
        commit = build_plan_batch_command(
            plan,
            batch_number=12,
            commit=True,
            output_dir="runtime/global_racing_import/france-geny",
        )

        self.assertEqual(dry_run["suggested_output_file"], "france-geny-batch-012-dryrun.json")
        self.assertEqual(dry_run["suggested_output_path"], "runtime/global_racing_import/france-geny/france-geny-batch-012-dryrun.json")
        self.assertTrue(dry_run["tee_command_line"].endswith("| tee runtime/global_racing_import/france-geny/france-geny-batch-012-dryrun.json"))
        self.assertEqual(commit["suggested_output_file"], "france-geny-batch-012-commit.json")
        self.assertEqual(commit["suggested_output_path"], "runtime/global_racing_import/france-geny/france-geny-batch-012-commit.json")
        self.assertTrue(commit["tee_command_line"].endswith("| tee runtime/global_racing_import/france-geny/france-geny-batch-012-commit.json"))

    def test_render_plan_batch_command_reads_plan_file(self):
        plan = {
            "source": "geny_france",
            "plan_only": True,
            "batches": [{"batch_index": 1, "partants_urls": ["https://www.geny.com/partants/foo"]}],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = Path(tmpdir) / "france-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            out = StringIO()

            call_command(
                "render_global_racing_batch_command",
                "--plan-file",
                str(plan_path),
                "--batch",
                "1",
                "--limit-horses",
                "12",
                "--output-dir",
                "runtime/global_racing_import/france-geny",
                stdout=out,
            )

        rendered = json.loads(out.getvalue())
        self.assertEqual(rendered["artifact_type"], "global_racing_batch_command")
        self.assertEqual(rendered["management_command"], "import_france_external_data")
        self.assertEqual(
            rendered["suggested_output_path"],
            "runtime/global_racing_import/france-geny/france-geny-batch-001-dryrun.json",
        )
        self.assertIn("| tee runtime/global_racing_import/france-geny/france-geny-batch-001-dryrun.json", rendered["tee_command_line"])
        self.assertEqual(rendered["args"][:3], ["import_france_external_data", "--source", "geny"])
        self.assertIn("--limit-horses", rendered["args"])

    def test_render_plan_batch_command_can_render_all_batches(self):
        plan = {
            "source": "horse_racing_nation",
            "plan_only": True,
            "batches": [
                {"batch_index": 1, "race_ids": ["HRN_track_2026-06-25_1"]},
                {"batch_index": 2, "race_ids": ["HRN_track_2026-06-25_2"]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = Path(tmpdir) / "us-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            out = StringIO()

            call_command(
                "render_global_racing_batch_command",
                "--plan-file",
                str(plan_path),
                "--all-batches",
                "--output-dir",
                "runtime/global_racing_import/us-hrn",
                stdout=out,
            )

        rendered = json.loads(out.getvalue())
        self.assertEqual(rendered["artifact_type"], "global_racing_batch_commands")
        self.assertEqual(rendered["batch_count"], 2)
        self.assertEqual([item["batch_number"] for item in rendered["commands"]], [1, 2])
        self.assertEqual(
            [item["suggested_output_path"] for item in rendered["commands"]],
            [
                "runtime/global_racing_import/us-hrn/us-hrn-batch-001-dryrun.json",
                "runtime/global_racing_import/us-hrn/us-hrn-batch-002-dryrun.json",
            ],
        )
        self.assertIn("HRN_track_2026-06-25_2", rendered["commands"][1]["command_line"])

    def test_plan_only_commands_require_explicit_network_permission(self):
        # Mutation: plan-only still fetches external date/race listing pages, so it must not run without an explicit network gate.
        cases = [
            (
                "import_uk_external_data",
                ["--recent-days", "60", "--plan-only"],
                "--plan-only 必须与 --allow-network 一起使用。",
            ),
            (
                "import_france_external_data",
                ["--source", "geny", "--recent-days", "60", "--plan-only"],
                "--plan-only 必须与 --allow-network 一起使用。",
            ),
            (
                "import_us_external_data",
                ["--recent-days", "60", "--plan-only"],
                "--plan-only 必须与 --allow-network 一起使用。",
            ),
        ]
        for command_name, args, message in cases:
            with self.subTest(command_name=command_name):
                with self.assertRaisesRegex(CommandError, message):
                    call_command(command_name, *args, stdout=StringIO())

    def test_commit_completion_gate_rejects_missing_or_unproven_completion(self):
        # Mutation: commit mode must not treat missing completion metadata as safe to write.
        from stable.services.external_france_racing_data import FranceExternalDataImporter, FranceImportError
        from stable.services.external_hkjc_data import HKJCExternalDataImporter, HKJCImportError
        from stable.services.external_uk_racing_data import UKExternalDataImporter, UKImportError
        from stable.services.external_us_racing_data import USExternalDataImporter, USImportError

        cases = [
            (HKJCExternalDataImporter(), HKJCImportError, "HKJC"),
            (UKExternalDataImporter(), UKImportError, "UK"),
            (FranceExternalDataImporter(), FranceImportError, "France"),
            (USExternalDataImporter(), USImportError, "US"),
        ]
        for importer, error_class, region in cases:
            for completion in ({}, {"stop_reason": "complete"}, {"is_complete": None}, {"is_complete": "true"}):
                with self.subTest(region=region, completion=completion):
                    with self.assertRaisesRegex(error_class, "Cannot commit unverified"):
                        importer._validate_completion_for_commit(completion)

    def test_commit_completion_gate_accepts_explicit_complete_completion(self):
        from stable.services.external_france_racing_data import FranceExternalDataImporter
        from stable.services.external_hkjc_data import HKJCExternalDataImporter
        from stable.services.external_uk_racing_data import UKExternalDataImporter
        from stable.services.external_us_racing_data import USExternalDataImporter

        for importer in (
            HKJCExternalDataImporter(),
            UKExternalDataImporter(),
            FranceExternalDataImporter(),
            USExternalDataImporter(),
        ):
            with self.subTest(importer=importer.__class__.__name__):
                importer._validate_completion_for_commit(
                    {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "unique_horses_found": 8,
                        "horse_profiles_fetched": 8,
                    }
                )

    def test_commit_completion_gate_rejects_missing_horse_detail_coverage_metadata(self):
        # Mutation: is_complete=true is not enough; commit needs counters proving horse detail coverage.
        from stable.services.external_france_racing_data import FranceExternalDataImporter, FranceImportError
        from stable.services.external_hkjc_data import HKJCExternalDataImporter, HKJCImportError
        from stable.services.external_uk_racing_data import UKExternalDataImporter, UKImportError
        from stable.services.external_us_racing_data import USExternalDataImporter, USImportError

        cases = [
            (HKJCExternalDataImporter(), HKJCImportError, "HKJC"),
            (UKExternalDataImporter(), UKImportError, "UK"),
            (FranceExternalDataImporter(), FranceImportError, "France"),
            (USExternalDataImporter(), USImportError, "US"),
        ]
        completions = [
            {"is_complete": True, "stop_reason": "complete"},
            {"is_complete": True, "stop_reason": "complete", "unique_horses_found": 8},
            {"is_complete": True, "stop_reason": "complete", "horse_profiles_fetched": 8},
        ]
        for importer, error_class, region in cases:
            for completion in completions:
                with self.subTest(region=region, completion=completion):
                    with self.assertRaisesRegex(error_class, "horse detail coverage metadata"):
                        importer._validate_completion_for_commit(completion)

    def test_commit_completion_gate_rejects_inconsistent_complete_metadata(self):
        # Mutation: commit mode must not trust is_complete=true if the completion details still show a partial crawl.
        from stable.services.external_france_racing_data import FranceExternalDataImporter, FranceImportError
        from stable.services.external_hkjc_data import HKJCExternalDataImporter, HKJCImportError
        from stable.services.external_uk_racing_data import UKExternalDataImporter, UKImportError
        from stable.services.external_us_racing_data import USExternalDataImporter, USImportError

        cases = [
            (HKJCExternalDataImporter(), HKJCImportError, "HKJC"),
            (UKExternalDataImporter(), UKImportError, "UK"),
            (FranceExternalDataImporter(), FranceImportError, "France"),
            (USExternalDataImporter(), USImportError, "US"),
        ]
        inconsistent_completions = [
            {"is_complete": True, "stop_reason": "limit_horses_reached"},
            {
                "is_complete": True,
                "stop_reason": "complete",
                "unique_horses_found": 8,
                "horse_profiles_fetched": 3,
            },
        ]
        for importer, error_class, region in cases:
            for completion in inconsistent_completions:
                with self.subTest(region=region, completion=completion):
                    with self.assertRaisesRegex(error_class, "Cannot commit inconsistent"):
                        importer._validate_completion_for_commit(completion)

    def test_commit_completion_gate_allows_declared_row_detail_horse_source(self):
        from stable.services.external_france_racing_data import FranceExternalDataImporter
        from stable.services.external_hkjc_data import HKJCExternalDataImporter
        from stable.services.external_uk_racing_data import UKExternalDataImporter
        from stable.services.external_us_racing_data import USExternalDataImporter

        completion = {
            "is_complete": True,
            "stop_reason": "complete",
            "unique_horses_found": 8,
            "horse_profiles_fetched": 0,
            "horse_profile_source": "geny_partants_rows",
        }
        for importer in (
            HKJCExternalDataImporter(),
            UKExternalDataImporter(),
            FranceExternalDataImporter(),
            USExternalDataImporter(),
        ):
            with self.subTest(importer=importer.__class__.__name__):
                importer._validate_completion_for_commit(completion)

    def test_commit_payload_gate_rejects_missing_required_coverage(self):
        # Mutation: a complete-looking payload must still contain race, entry, result, and horse coverage before commit.
        from stable.services.external_france_racing_data import FranceExternalDataImporter, FranceImportError
        from stable.services.external_hkjc_data import HKJCExternalDataImporter, HKJCImportError
        from stable.services.external_uk_racing_data import UKExternalDataImporter, UKImportError
        from stable.services.external_us_racing_data import USExternalDataImporter, USImportError

        cases = [
            (HKJCExternalDataImporter(), HKJCImportError, "HKJC"),
            (UKExternalDataImporter(), UKImportError, "UK"),
            (FranceExternalDataImporter(), FranceImportError, "France"),
            (USExternalDataImporter(), USImportError, "US"),
        ]
        for importer, error_class, region in cases:
            for missing_key in ("races", "entries", "results", "horses"):
                stats = {"races": 1, "entries": 1, "results": 1, "horses": 1}
                stats[missing_key] = 0
                with self.subTest(region=region, missing_key=missing_key):
                    with self.assertRaisesRegex(error_class, "missing required coverage"):
                        importer._validate_payload_limits(stats)

    def test_commit_payload_gate_accepts_required_coverage(self):
        from stable.services.external_france_racing_data import FranceExternalDataImporter
        from stable.services.external_hkjc_data import HKJCExternalDataImporter
        from stable.services.external_uk_racing_data import UKExternalDataImporter
        from stable.services.external_us_racing_data import USExternalDataImporter

        stats = {"races": 1, "entries": 1, "results": 1, "horses": 1}
        for importer in (
            HKJCExternalDataImporter(),
            UKExternalDataImporter(),
            FranceExternalDataImporter(),
            USExternalDataImporter(),
        ):
            with self.subTest(importer=importer.__class__.__name__):
                importer._validate_payload_limits(stats)


class GlobalRacingImportOutputAuditTests(TestCase):
    def write_json(self, directory, name: str, payload: dict) -> None:
        path = directory / name
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_audit_ignores_rendered_batch_command_artifacts(self):
        # Mutation: saving the read-only command manifest beside dry-run outputs must not poison commit-candidate auditing.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"], "race_urls": ["https://example.test/race/SL1"]}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "unique_horses_found": 8,
                        "horse_profiles_fetched": 8,
                        "race_ids_selected": ["SL1"],
                    },
                    "requests": [{"url": "https://example.test/race/SL1", "status_code": 200}],
                },
            )
            self.write_json(
                directory,
                "uk-rendered-commands.json",
                {
                    "artifact_type": "global_racing_batch_commands",
                    "source": "sporting_life",
                    "batch_count": 1,
                    "commands": [{"batch_number": 1, "command_line": "python server/manage.py import_uk_external_data"}],
                },
            )
            out = StringIO()

            call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete", stdout=out)

        result = json.loads(out.getvalue())
        self.assertTrue(result["commit_candidate_ready"])
        self.assertEqual(result["ignored_artifact_file_count"], 1)
        self.assertEqual(result["ignored_artifact_files"], [{"path": "uk-rendered-commands.json", "artifact_type": "global_racing_batch_commands"}])
        self.assertEqual(result["batch_file_count"], 1)

    def test_audit_summarizes_complete_dry_run_batches(self):
        # Mutation: operators need a machine summary before deciding whether a group of dry-run files can approach commit.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 10, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [
                        {"batch_index": 1, "race_ids": ["SL1"], "race_urls": ["https://example.test/race/SL1"]},
                        {"batch_index": 2, "race_ids": ["SL2"], "race_urls": ["https://example.test/race/SL2"]},
                    ],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 5, "entries": 47, "results": 47, "horses": 46},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "unique_horses_found": 46,
                        "horse_profiles_fetched": 46,
                        "race_ids_selected": ["SL1"],
                    },
                    "requests": [{"url": "https://example.test/race", "status_code": 200}, {"url": "https://example.test/horse", "status_code": 200}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-2.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL2",
                    "dry_run": True,
                    "coverage_stats": {"races": 5, "entries": 61, "results": 61, "horses": 59},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "unique_horses_found": 59,
                        "horse_profiles_fetched": 59,
                        "race_ids_selected": ["SL2"],
                    },
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )
            out = StringIO()

            call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), stdout=out)

        result = json.loads(out.getvalue())
        self.assertTrue(result["commit_candidate_ready"])
        self.assertEqual(result["file_count"], 3)
        self.assertEqual(result["plan_file_count"], 1)
        self.assertEqual(result["batch_file_count"], 2)
        self.assertEqual(result["incomplete_file_count"], 0)
        self.assertEqual(result["planned_item_count"], 2)
        self.assertEqual(result["covered_planned_item_count"], 2)
        self.assertEqual(result["missing_planned_item_count"], 0)
        self.assertEqual(result["total_requests"], 3)
        self.assertEqual(result["coverage_totals"], {"races": 10, "entries": 108, "results": 108, "horses": 105})

    def test_audit_can_fail_when_horse_profiles_do_not_cover_unique_horses(self):
        # Mutation: a complete-looking batch must not pass if involved horses lack profile/detail coverage.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["SL1"],
                        "unique_horses_found": 8,
                        "horse_profiles_fetched": 3,
                    },
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "incomplete horse details"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_batch_without_request_evidence(self):
        # Mutation: a batch cannot become a commit candidate unless it carries request evidence.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["SL1"],
                        "unique_horses_found": 8,
                        "horse_profiles_fetched": 8,
                    },
                    "requests": [],
                },
            )

            with self.assertRaisesRegex(CommandError, "empty batch requests"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_batch_without_required_coverage(self):
        # Mutation: claiming a planned race without entries/results/horses must not satisfy full-crawl coverage.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["SL1"],
                        "unique_horses_found": 0,
                        "horse_profiles_fetched": 0,
                    },
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "empty batch coverage"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_batch_non_success_response(self):
        # Mutation: a batch with failed network evidence cannot anchor a production commit decision.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["SL1"],
                        "unique_horses_found": 8,
                        "horse_profiles_fetched": 8,
                    },
                    "requests": [{"url": "https://example.test/race", "status_code": 503}],
                },
            )

            with self.assertRaisesRegex(CommandError, "non-success batch response"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_plan_without_request_evidence(self):
        # Mutation: a plan cannot anchor a full-crawl commit audit unless it records its source requests.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["SL1"],
                        "unique_horses_found": 8,
                        "horse_profiles_fetched": 8,
                    },
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "empty plan requests"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_plan_non_success_response(self):
        # Mutation: a failed plan discovery request cannot prove the 60-day batch ledger.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 503}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["SL1"],
                        "unique_horses_found": 8,
                        "horse_profiles_fetched": 8,
                    },
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "non-success plan response"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_allows_declared_row_detail_horse_source(self):
        # Mutation: France row-level horse detail sources can be the documented equivalent to independent profile pages.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "france-plan.json",
                {
                    "source": "geny_france",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["GENY1"], "partants_urls": ["https://example.test/partants"]}],
                },
            )
            self.write_json(
                directory,
                "france-batch-1.json",
                {
                    "source": "geny_france",
                    "target_type": "partants_urls",
                    "target_id": "GENY1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["GENY1"],
                        "unique_horses_found": 8,
                        "horse_profiles_fetched": 0,
                        "horse_profile_source": "geny_partants_rows",
                    },
                    "requests": [{"url": "https://example.test/partants", "status_code": 200}],
                },
            )
            out = StringIO()

            call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete", stdout=out)

        result = json.loads(out.getvalue())
        self.assertTrue(result["commit_candidate_ready"])
        self.assertEqual(result["incomplete_horse_detail_file_count"], 0)

    def test_audit_reports_blocking_reasons_without_fail_flag(self):
        # Mutation: a handoff audit without --fail-on-incomplete still needs machine-readable reasons for why commit is blocked.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "france-batch-1.json",
                {
                    "source": "geny_france",
                    "target_type": "partants_urls",
                    "dry_run": True,
                    "coverage_stats": {"races": 5, "entries": 57, "results": 52, "horses": 54},
                    "completion": {"is_complete": False, "stop_reason": "limit_horses_reached"},
                    "requests": [{"url": "https://example.test/partants", "status_code": 200}],
                },
            )
            out = StringIO()

            call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), stdout=out)

        result = json.loads(out.getvalue())
        self.assertFalse(result["commit_candidate_ready"])
        self.assertEqual(
            result["blocking_reasons"],
            ["missing plan file", "france-batch-1.json"],
        )

    def test_audit_reports_missing_batch_reason(self):
        # Mutation: a plan-only file by itself must not produce an empty failure reason when no batch output exists.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            out = StringIO()

            call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), stdout=out)

        result = json.loads(out.getvalue())
        self.assertFalse(result["commit_candidate_ready"])
        self.assertEqual(result["blocking_reasons"], ["missing batch file"])

    def test_audit_can_fail_on_incomplete_batch_outputs(self):
        # Mutation: incomplete dry-run files must stop the handoff before anyone adds --commit.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "france-batch-1.json",
                {
                    "source": "geny_france",
                    "target_type": "partants_urls",
                    "dry_run": True,
                    "coverage_stats": {"races": 5, "entries": 57, "results": 52, "horses": 54},
                    "completion": {"is_complete": False, "stop_reason": "limit_horses_reached"},
                    "requests": [{"url": "https://example.test/partants", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "incomplete"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_missing_planned_race_ids(self):
        # Mutation: a complete-looking batch set must not pass if it skipped items listed by plan-only output.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "us-plan.json",
                {
                    "source": "horse_racing_nation",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 2, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [
                        {"batch_index": 1, "race_ids": ["HRN_track_2026-06-25_1"]},
                        {"batch_index": 2, "race_ids": ["HRN_track_2026-06-25_2"]},
                    ],
                },
            )
            self.write_json(
                directory,
                "us-batch-1.json",
                {
                    "source": "horse_racing_nation",
                    "target_type": "race_ids",
                    "target_id": "HRN_track_2026-06-25_1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["HRN_track_2026-06-25_1"],
                    },
                    "requests": [{"url": "https://example.test/track-day", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "missing planned"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_extra_covered_items(self):
        # Mutation: a complete-looking batch set must not pass if it includes races outside the plan.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"], "race_urls": ["https://example.test/race/SL1"]}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1,SL999",
                    "dry_run": True,
                    "coverage_stats": {"races": 2, "entries": 12, "results": 12, "horses": 12},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["SL1", "SL999"],
                    },
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "extra covered"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_when_plan_file_is_missing(self):
        # Mutation: complete dry-run batches without a plan-only file must not become commit candidates.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["SL1"],
                    },
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "missing plan"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_non_dry_run_plan_file(self):
        # Mutation: a plan file produced by commit mode must not anchor a dry-run commit audit.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": False,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {"is_complete": True, "stop_reason": "complete", "race_ids_selected": ["SL1"]},
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "non-dry-run plan"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_incomplete_plan_file(self):
        # Mutation: a partial plan cannot prove that subsequent batches cover the intended window.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "us-plan.json",
                {
                    "source": "horse_racing_nation",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": False, "stop_reason": "rate_limited"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["HRN_track_2026-06-25_1"]}],
                },
            )
            self.write_json(
                directory,
                "us-batch-1.json",
                {
                    "source": "horse_racing_nation",
                    "target_type": "race_ids",
                    "target_id": "HRN_track_2026-06-25_1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["HRN_track_2026-06-25_1"],
                    },
                    "requests": [{"url": "https://example.test/track-day", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "incomplete plan"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_limited_plan_file(self):
        # Mutation: a proof plan that intentionally limited source coverage must not anchor a full-crawl commit audit.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "us-plan.json",
                {
                    "source": "horse_racing_nation",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "plan_only",
                        "coverage_scope_limited": True,
                        "limit_tracks": 3,
                    },
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["HRN_track_2026-06-25_1"]}],
                },
            )
            self.write_json(
                directory,
                "us-batch-1.json",
                {
                    "source": "horse_racing_nation",
                    "target_type": "race_ids",
                    "target_id": "HRN_track_2026-06-25_1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["HRN_track_2026-06-25_1"],
                    },
                    "requests": [{"url": "https://example.test/track-day", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "limited plan"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_duplicate_planned_items(self):
        # Mutation: duplicate plan entries must not make the batch ledger look one-to-one.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 2, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [
                        {"batch_index": 1, "race_ids": ["SL1"]},
                        {"batch_index": 2, "race_ids": ["SL1"]},
                    ],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {
                        "is_complete": True,
                        "stop_reason": "complete",
                        "race_ids_selected": ["SL1"],
                        "unique_horses_found": 8,
                        "horse_profiles_fetched": 8,
                    },
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "duplicate planned"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_duplicate_covered_items(self):
        # Mutation: running the same planned race twice must not be accepted as a clean full-crawl batch set.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            for name in ("uk-batch-1.json", "uk-batch-2.json"):
                self.write_json(
                    directory,
                    name,
                    {
                        "source": "sporting_life",
                        "target_type": "race_urls",
                        "target_id": "SL1",
                        "dry_run": True,
                        "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                        "completion": {
                            "is_complete": True,
                            "stop_reason": "complete",
                            "race_ids_selected": ["SL1"],
                            "unique_horses_found": 8,
                            "horse_profiles_fetched": 8,
                        },
                        "requests": [{"url": "https://example.test/race", "status_code": 200}],
                    },
                )

            with self.assertRaisesRegex(CommandError, "duplicate covered"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_mixed_sources(self):
        # Mutation: a commit audit must not combine plan and batch files from different regions or sources.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            self.write_json(
                directory,
                "france-batch-1.json",
                {
                    "source": "geny_france",
                    "target_type": "partants_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {"is_complete": True, "stop_reason": "complete", "race_ids_selected": ["SL1"]},
                    "requests": [{"url": "https://example.test/partants", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "mixed sources"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_missing_source(self):
        # Mutation: source-less JSON must not fail with an empty audit reason.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "plan.json",
                {
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["R1"]}],
                },
            )
            self.write_json(
                directory,
                "batch.json",
                {
                    "target_type": "race_ids",
                    "target_id": "R1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {"is_complete": True, "stop_reason": "complete", "race_ids_selected": ["R1"]},
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "missing source"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_dry_run_that_would_write_formal_tables(self):
        # Mutation: a contradictory dry-run file must not be allowed into commit review.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "would_write_formal_tables": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {"is_complete": True, "stop_reason": "complete", "race_ids_selected": ["SL1"]},
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "would write formal tables"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_can_fail_on_plan_that_would_write_formal_tables(self):
        # Mutation: a contradictory plan file must not anchor commit review.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-plan.json",
                {
                    "source": "sporting_life",
                    "target_type": "date_range",
                    "dry_run": True,
                    "plan_only": True,
                    "would_write_formal_tables": True,
                    "coverage_stats": {"races": 1, "entries": 0, "results": 0, "horses": 0},
                    "completion": {"is_complete": True, "stop_reason": "plan_only"},
                    "requests": [{"url": "https://example.test/plan", "status_code": 200}],
                    "batches": [{"batch_index": 1, "race_ids": ["SL1"]}],
                },
            )
            self.write_json(
                directory,
                "uk-batch-1.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "target_id": "SL1",
                    "dry_run": True,
                    "coverage_stats": {"races": 1, "entries": 8, "results": 8, "horses": 8},
                    "completion": {"is_complete": True, "stop_reason": "complete", "race_ids_selected": ["SL1"]},
                    "requests": [{"url": "https://example.test/race", "status_code": 200}],
                },
            )

            with self.assertRaisesRegex(CommandError, "would write formal tables"):
                call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--fail-on-incomplete")

    def test_audit_proof_only_accepts_limited_real_dry_run_proofs(self):
        # Mutation: proof runs intentionally stop at low limits, but still need a machine gate proving real dry-run requests.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-proof.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "dry_run": True,
                    "would_write_formal_tables": False,
                    "coverage_stats": {"races": 1, "entries": 7, "results": 7, "horses": 7},
                    "completion": {"is_complete": False, "stop_reason": "limit_horses_reached"},
                    "requests": [
                        {"target_type": "race", "status_code": 200, "url": "https://example.test/race"},
                        {"target_type": "horse", "status_code": 200, "url": "https://example.test/horse"},
                    ],
                },
            )
            self.write_json(
                directory,
                "france-proof.json",
                {
                    "source": "geny_france",
                    "target_type": "partants_urls",
                    "dry_run": True,
                    "would_write_formal_tables": False,
                    "coverage_stats": {"races": 1, "entries": 6, "results": 6, "horses": 6},
                    "completion": {"is_complete": False, "stop_reason": "limit_horses_reached"},
                    "requests": [
                        {"target_type": "partants", "status_code": 200, "url": "https://example.test/partants"},
                        {"target_type": "results", "status_code": 200, "url": "https://example.test/results"},
                        {"target_type": "horse", "status_code": 200, "url": "https://example.test/horse"},
                    ],
                },
            )
            self.write_json(
                directory,
                "us-proof.json",
                {
                    "source": "horse_racing_nation",
                    "target_type": "race_ids",
                    "dry_run": True,
                    "would_write_formal_tables": False,
                    "coverage_stats": {"races": 1, "entries": 12, "results": 4, "horses": 12},
                    "completion": {"is_complete": False, "stop_reason": "limit_horses_reached"},
                    "requests": [
                        {"target_type": "track_day", "status_code": 200, "url": "https://example.test/track-day"},
                        {"target_type": "horse", "status_code": 200, "url": "https://example.test/horse"},
                    ],
                },
            )
            out = StringIO()

            call_command("audit_global_racing_import_outputs", "--input-dir", str(directory), "--proof-only", "--fail-on-incomplete", stdout=out)

        result = json.loads(out.getvalue())
        self.assertTrue(result["proof_ready"])
        self.assertFalse(result["commit_candidate_ready"])
        self.assertEqual(result["handoff_decision"], "proof_only_ready_not_commit_candidate")
        self.assertEqual(
            result["handoff_decision_reasons"],
            [
                "proof-only audit passed",
                "commit audit still blocked",
                "complete 60-day crawl and commit gate remain required",
            ],
        )
        self.assertEqual(result["proof_file_count"], 3)
        self.assertEqual(result["proof_successful_response_count"], 7)
        self.assertEqual(result["proof_blocking_reasons"], [])
        self.assertEqual(
            result["proof_sources"]["sporting_life"],
            {
                "files": ["uk-proof.json"],
                "file_count": 1,
                "complete_file_count": 0,
                "incomplete_file_count": 1,
                "request_count": 2,
                "successful_response_count": 2,
                "coverage_totals": {"races": 1, "entries": 7, "results": 7, "horses": 7},
                "request_types": ["horse", "race"],
                "stop_reasons": ["limit_horses_reached"],
            },
        )
        self.assertEqual(result["proof_sources"]["geny_france"]["request_types"], ["horse", "partants", "results"])
        self.assertEqual(result["proof_sources"]["horse_racing_nation"]["coverage_totals"]["horses"], 12)

    def test_audit_records_runtime_parameters_for_handoff(self):
        # Mutation: without audit parameters, a saved audit JSON cannot prove which directory or gate produced it.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-proof.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "dry_run": True,
                    "would_write_formal_tables": False,
                    "coverage_stats": {"races": 1, "entries": 7, "results": 7, "horses": 7},
                    "completion": {"is_complete": False, "stop_reason": "limit_horses_reached"},
                    "requests": [
                        {"target_type": "race", "status_code": 200, "url": "https://example.test/race"},
                        {"target_type": "horse", "status_code": 200, "url": "https://example.test/horse"},
                    ],
                },
            )
            out = StringIO()

            call_command(
                "audit_global_racing_import_outputs",
                "--input-dir",
                str(directory),
                "--pattern",
                "*.json",
                "--proof-only",
                "--expected-sources",
                "sporting_life",
                "--expected-request-types",
                "sporting_life:race|horse",
                "--fail-on-incomplete",
                stdout=out,
            )

        result = json.loads(out.getvalue())
        self.assertEqual(
            result["audit_parameters"],
            {
                "input_dir": str(directory),
                "pattern": "*.json",
                "proof_only": True,
                "fail_on_incomplete": True,
                "expected_sources": ["sporting_life"],
                "expected_request_types": {"sporting_life": ["horse", "race"]},
            },
        )

    def test_audit_proof_only_requires_expected_sources_when_declared(self):
        # Mutation: a handoff claiming UK/France/US proof must fail if one expected source JSON is missing.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "uk-proof.json",
                {
                    "source": "sporting_life",
                    "target_type": "race_urls",
                    "dry_run": True,
                    "would_write_formal_tables": False,
                    "coverage_stats": {"races": 1, "entries": 7, "results": 7, "horses": 7},
                    "completion": {"is_complete": False, "stop_reason": "limit_horses_reached"},
                    "requests": [{"target_type": "race", "status_code": 200, "url": "https://example.test/race"}],
                },
            )
            self.write_json(
                directory,
                "france-proof.json",
                {
                    "source": "geny_france",
                    "target_type": "partants_urls",
                    "dry_run": True,
                    "would_write_formal_tables": False,
                    "coverage_stats": {"races": 1, "entries": 6, "results": 6, "horses": 6},
                    "completion": {"is_complete": False, "stop_reason": "limit_horses_reached"},
                    "requests": [{"target_type": "partants", "status_code": 200, "url": "https://example.test/partants"}],
                },
            )

            with self.assertRaisesRegex(CommandError, "missing expected proof source horse_racing_nation"):
                call_command(
                    "audit_global_racing_import_outputs",
                    "--input-dir",
                    str(directory),
                    "--proof-only",
                    "--expected-sources",
                    "sporting_life,geny_france,horse_racing_nation",
                    "--fail-on-incomplete",
                )

    def test_audit_proof_only_requires_expected_request_types_when_declared(self):
        # Mutation: a source proof without horse/profile requests must not prove the full race-to-horse path is usable.
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_json(
                directory,
                "us-proof.json",
                {
                    "source": "horse_racing_nation",
                    "target_type": "race_ids",
                    "dry_run": True,
                    "would_write_formal_tables": False,
                    "coverage_stats": {"races": 1, "entries": 12, "results": 4, "horses": 12},
                    "completion": {"is_complete": False, "stop_reason": "limit_horses_reached"},
                    "requests": [{"target_type": "track_day", "status_code": 200, "url": "https://example.test/track-day"}],
                },
            )

            with self.assertRaisesRegex(CommandError, "missing proof request type horse_racing_nation:horse"):
                call_command(
                    "audit_global_racing_import_outputs",
                    "--input-dir",
                    str(directory),
                    "--proof-only",
                    "--expected-request-types",
                    "horse_racing_nation:track_day|horse",
                    "--fail-on-incomplete",
                )


class PushTests(TestCase):
    def setUp(self):
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="1",
            title_ja="原文标题",
            title_zh="中文标题",
            summary_zh="中文摘要",
            body_ja_raw="原文正文",
            body_ja_normalized="原文正文",
            body_zh="中文正文",
            push_summary_zh="中文摘要",
            published_at=timezone.now(),
            source_url="https://example.com/article/1",
            workflow_status=WorkflowStatus.PENDING_REVIEW,
        )
        self.target = PushTarget.objects.create(name="测试群", group_id="10001", is_default=True)

    def test_build_push_message_contains_source_url(self):
        text, image_url = build_push_message(self.article)
        self.assertIn("中文标题", text)
        self.assertIn("https://example.com/article/1", text)
        self.assertIsNone(image_url)

    def test_build_push_message_skips_blank_summary_when_cleared_manually(self):
        self.article.summary_zh = ""
        self.article.push_summary_zh = "机器摘要"
        self.article.mark_manual_edits(["summary_zh"])
        self.article.save()

        text, _ = build_push_message(self.article)

        self.assertNotIn("机器摘要", text)
        self.assertIn("原文链接：https://example.com/article/1", text)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_push_article_success(self):
        with patch("stable.services.pushing.BotPusher.send_group_message", return_value={"status": "ok"}):
            logs = push_article_to_targets(self.article, [self.target])
        self.assertEqual(len(logs), 1)
        logs[0].refresh_from_db()
        self.article.refresh_from_db()
        self.assertEqual(logs[0].status, "success")
        self.assertEqual(self.article.status, "pushed")


@override_settings(
    SITE_URL="http://testserver",
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=False,
    QQ_PUSH_SCOPE="all_public",
)
class QQAutoPushTests(TestCase):
    def setUp(self):
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="qq-auto-1",
            title_ja="原文标题",
            title_zh="中文标题",
            summary_zh="中文摘要",
            body_ja_raw="原文正文",
            body_ja_normalized="原文正文",
            body_zh="中文正文" * 80,
            push_summary_zh="中文摘要",
            published_at=timezone.now(),
            source_url="https://example.com/article/qq-auto-1",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
            score_total=90,
        )
        self.target = PushTarget.objects.create(name="测试群", group_id="10001", is_default=False, is_active=True)
        self.inactive_target = PushTarget.objects.create(name="停用群", group_id="10002", is_active=False)

    def test_delivery_records_are_unique_per_article_and_target(self):
        first = ensure_qq_push_deliveries(self.article, [self.target])
        second = ensure_qq_push_deliveries(self.article, [self.target])

        self.assertEqual(first[0].id, second[0].id)
        self.assertEqual(QQPushDelivery.objects.count(), 1)

    @override_settings(QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked", AUTO_REVIEW_THRESHOLD=75)
    def test_high_value_scope_uses_ranked_strategy_instead_of_score(self):
        self.assertFalse(should_push_news_to_qq(self.article).allowed)
        self.article.score_total = 20
        self.article.source_mode = SourceMode.ACCESS
        self.article.save(update_fields=["score_total", "source_mode", "updated_at"])

        result = should_push_news_to_qq(self.article)

        self.assertTrue(result.allowed)

    @override_settings(QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked", AUTO_REVIEW_THRESHOLD=75)
    def test_ranked_strategy_allows_attention_source(self):
        self.article.score_total = 20
        self.article.source_mode = SourceMode.ATTENTION
        self.article.save(update_fields=["score_total", "source_mode", "updated_at"])

        self.assertTrue(should_push_news_to_qq(self.article).allowed)

    @override_settings(QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked", AUTO_REVIEW_THRESHOLD=75)
    def test_ranked_strategy_allows_international_ranked_sources(self):
        self.article.source_site = SourceSite.SKY_SPORTS_RACING
        self.article.source_mode = SourceMode.ACCESS
        self.article.racing_region = RacingRegion.UNITED_KINGDOM
        self.article.source_language = SourceLanguage.ENGLISH
        self.article.score_total = 20
        self.article.save(
            update_fields=["source_site", "source_mode", "racing_region", "source_language", "score_total", "updated_at"]
        )

        self.assertTrue(should_push_news_to_qq(self.article).allowed)

    @override_settings(QQ_PUSH_SCOPE="all_public")
    def test_blank_target_regions_keep_legacy_japan_only_behavior(self):
        self.assertEqual(target_allowed_regions(self.target), {RacingRegion.JAPAN})
        self.target.allowed_regions = [""]
        self.target.save(update_fields=["allowed_regions", "updated_at"])
        self.assertEqual(target_allowed_regions(self.target), {RacingRegion.JAPAN})
        self.article.racing_region = RacingRegion.HONG_KONG
        self.article.source_language = SourceLanguage.ENGLISH
        self.article.save(update_fields=["racing_region", "source_language", "updated_at"])

        result = should_push_news_to_qq(self.article, target=self.target)

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "region_not_allowed")

    @override_settings(QQ_PUSH_SCOPE="all_public")
    def test_invalid_target_regions_keep_legacy_japan_only_behavior(self):
        self.target.allowed_regions = ["hongkong"]
        self.target.save(update_fields=["allowed_regions", "updated_at"])
        self.assertEqual(target_allowed_regions(self.target), {RacingRegion.JAPAN})
        self.article.racing_region = RacingRegion.HONG_KONG
        self.article.source_language = SourceLanguage.ENGLISH
        self.article.save(update_fields=["racing_region", "source_language", "updated_at"])

        result = should_push_news_to_qq(self.article, target=self.target)

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "region_not_allowed")

    @override_settings(QQ_PUSH_SCOPE="all_public", AUTO_REVIEW_THRESHOLD=75)
    def test_all_public_scope_ignores_score(self):
        self.article.score_total = 20
        self.article.save(update_fields=["score_total", "updated_at"])

        self.assertTrue(should_push_news_to_qq(self.article).allowed)

    @override_settings(QQ_PUSH_SCOPE="unsupported", AUTO_REVIEW_THRESHOLD=75)
    def test_invalid_scope_falls_back_to_high_value_only(self):
        self.article.score_total = 20
        self.article.save(update_fields=["score_total", "updated_at"])

        self.assertFalse(should_push_news_to_qq(self.article).allowed)

    @override_settings(QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="unsupported", AUTO_REVIEW_THRESHOLD=75)
    def test_invalid_importance_strategy_falls_back_to_ranked(self):
        self.article.source_mode = SourceMode.ACCESS
        self.article.score_total = 20
        self.article.save(update_fields=["source_mode", "score_total", "updated_at"])

        self.assertTrue(should_push_news_to_qq(self.article).allowed)

    @override_settings(QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked")
    def test_blocker_article_is_not_eligible_for_auto_push(self):
        self.article.source_mode = SourceMode.ACCESS
        self.article.gate_issues = [
            {"code": "missing_body", "severity": "blocker", "message": "正文为空", "route": "manual_review", "payload": {}}
        ]
        self.article.save(update_fields=["source_mode", "gate_issues", "updated_at"])

        self.assertFalse(should_push_news_to_qq(self.article).allowed)

    def test_auto_push_message_uses_summary_and_public_url(self):
        message = build_qq_auto_push_message(self.article)

        self.assertIn("【UmaFans】中文标题", message)
        self.assertIn("中文摘要", message)
        self.assertIn(f"阅读全文：http://testserver/news/{self.article.id}/", message)

    def test_auto_push_message_truncates_body_when_summary_blank(self):
        self.article.summary_zh = ""
        self.article.push_summary_zh = ""
        self.article.translated_summary_zh = ""
        self.article.rewrite_summary_zh = ""
        self.article.save()

        message = build_qq_auto_push_message(self.article)

        self.assertIn("……", message)
        self.assertIn(f"阅读全文：http://testserver/news/{self.article.id}/", message)

    @override_settings(QQ_PUSH_MAX_ATTEMPTS=3)
    def test_delivery_url_unavailable_records_retryable_error_type(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]

        with (
            patch("stable.services.qq_auto_push.BotPusher.is_online", return_value=(True, "")),
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(False, "HTTP 404")),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.RETRYING)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.last_error_type, QQPushErrorType.URL_UNAVAILABLE)

    @override_settings(QQ_PUSH_SCOPE="all_public")
    def test_delivery_rechecks_blocker_before_sending(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]
        self.article.gate_issues = [
            {"code": "late_blocker", "severity": "blocker", "message": "发布后发现 blocker", "payload": {}}
        ]
        self.article.save(update_fields=["gate_issues", "updated_at"])

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible") as url_check,
            patch("stable.services.qq_auto_push.BotPusher.send_group_message") as send_message,
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.SKIPPED)
        self.assertEqual(delivery.attempt_count, 0)
        self.assertEqual(delivery.last_error_type, QQPushErrorType.NOT_ELIGIBLE)
        self.assertEqual(delivery.last_error, "has_blocker")
        url_check.assert_not_called()
        send_message.assert_not_called()

    @override_settings(QQ_PUSH_SCOPE="all_public")
    def test_skipped_delivery_can_send_after_article_becomes_eligible_again(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]
        delivery.status = QQPushDeliveryStatus.SKIPPED
        delivery.last_error_type = QQPushErrorType.NOT_ELIGIBLE
        delivery.last_error = "has_blocker"
        delivery.save(update_fields=["status", "last_error_type", "last_error", "updated_at"])

        with (
            patch("stable.services.qq_auto_push.BotPusher.is_online", return_value=(True, "")),
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")),
            patch("stable.services.qq_auto_push.BotPusher.send_group_message", return_value={"status": "ok"}),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.SENT)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.last_error_type, "")
        self.assertEqual(delivery.last_error, "")

    @override_settings(QQ_PUSH_MAX_ATTEMPTS=1)
    def test_delivery_onebot_failure_records_send_failed(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]

        with (
            patch("stable.services.qq_auto_push.BotPusher.is_online", return_value=(True, "")),
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")),
            patch("stable.services.qq_auto_push.BotPusher.send_group_message", side_effect=RuntimeError("bot down")),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.FAILED)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.last_error_type, QQPushErrorType.SEND_FAILED)

    def test_delivery_success_saves_message_id(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]

        with (
            patch("stable.services.qq_auto_push.BotPusher.is_online", return_value=(True, "")),
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")),
            patch("stable.services.qq_auto_push.BotPusher.send_group_message", return_value={"status": "ok", "data": {"message_id": 123}}),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.SENT)
        self.assertEqual(delivery.message_id, "123")
        self.assertIsNotNone(delivery.sent_at)

    @override_settings(QQ_PUSH_MAX_ATTEMPTS=1, ONEBOT_ACCESS_TOKEN="SECRET")
    def test_delivery_onebot_failed_json_records_send_failed(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]

        class FailedResponse:
            text = '{"status":"failed","retcode":100,"wording":"bad SECRET"}'

            def raise_for_status(self):
                return None

            def json(self):
                return {"status": "failed", "retcode": 100, "wording": "bad SECRET"}

        with (
            patch("stable.services.qq_auto_push.BotPusher.is_online", return_value=(True, "")),
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")),
            patch("stable.services.onebot.requests.post", return_value=FailedResponse()),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.FAILED)
        self.assertEqual(delivery.last_error_type, QQPushErrorType.SEND_FAILED)
        self.assertNotIn("SECRET", delivery.last_error)

    def test_delivery_does_not_consume_attempt_when_onebot_offline(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")) as url_check,
            patch("stable.services.qq_auto_push.BotPusher.is_online", return_value=(False, "onebot_offline")),
            patch("stable.services.qq_auto_push.BotPusher.send_group_message") as send_message,
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.RETRYING)
        self.assertEqual(delivery.status, QQPushDeliveryStatus.RETRYING)
        self.assertEqual(delivery.attempt_count, 0)
        self.assertEqual(delivery.last_error_type, QQPushErrorType.SEND_FAILED)
        self.assertIn("onebot_offline", delivery.last_error)
        url_check.assert_not_called()
        send_message.assert_not_called()

    def test_delivery_does_not_consume_attempt_when_onebot_status_check_fails(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")) as url_check,
            patch("stable.services.qq_auto_push.BotPusher.is_online", return_value=(False, "status_check_failed: timeout")),
            patch("stable.services.qq_auto_push.BotPusher.send_group_message") as send_message,
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.RETRYING)
        self.assertEqual(delivery.attempt_count, 0)
        self.assertEqual(delivery.last_error_type, QQPushErrorType.SEND_FAILED)
        self.assertIn("status_check_failed", delivery.last_error)
        url_check.assert_not_called()
        send_message.assert_not_called()

    def test_delivery_sends_after_onebot_recovers_online(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]
        delivery.status = QQPushDeliveryStatus.RETRYING
        delivery.last_error_type = QQPushErrorType.SEND_FAILED
        delivery.last_error = "onebot_offline"
        delivery.save(update_fields=["status", "last_error_type", "last_error", "updated_at"])

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")),
            patch("stable.services.qq_auto_push.BotPusher.is_online", return_value=(True, "")),
            patch("stable.services.qq_auto_push.BotPusher.send_group_message", return_value={"status": "ok", "data": {"message_id": 789}}),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.SENT)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.message_id, "789")
        self.assertEqual(delivery.last_error_type, "")
        self.assertEqual(delivery.last_error, "")

    @override_settings(QQ_PUSH_SENDING_STALE_SECONDS=60)
    def test_active_sending_delivery_is_not_reclaimed(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]
        delivery.status = QQPushDeliveryStatus.SENDING
        delivery.attempt_count = 1
        delivery.last_attempt_at = timezone.now()
        delivery.save(update_fields=["status", "attempt_count", "last_attempt_at", "updated_at"])

        with (
            patch("stable.services.qq_auto_push.is_public_url_accessible") as url_check,
            patch("stable.services.qq_auto_push.BotPusher.send_group_message") as send_message,
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.SENDING)
        self.assertEqual(delivery.attempt_count, 1)
        url_check.assert_not_called()
        send_message.assert_not_called()

    @override_settings(QQ_PUSH_SENDING_STALE_SECONDS=60)
    def test_stale_sending_delivery_is_reclaimed(self):
        delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]
        delivery.status = QQPushDeliveryStatus.SENDING
        delivery.attempt_count = 1
        delivery.max_attempts = 3
        delivery.last_attempt_at = timezone.now() - timedelta(seconds=120)
        delivery.save(update_fields=["status", "attempt_count", "max_attempts", "last_attempt_at", "updated_at"])

        with (
            patch("stable.services.qq_auto_push.BotPusher.is_online", return_value=(True, "")),
            patch("stable.services.qq_auto_push.is_public_url_accessible", return_value=(True, "")),
            patch("stable.services.qq_auto_push.BotPusher.send_group_message", return_value={"status": "ok", "data": {"message_id": 456}}),
        ):
            result = qq_push_delivery_task.run(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(result["status"], QQPushDeliveryStatus.SENT)
        self.assertEqual(delivery.attempt_count, 2)
        self.assertEqual(delivery.message_id, "456")

    @override_settings(QQ_PUSH_MIN_INTERVAL_SECONDS=60)
    def test_delivery_attempt_delay_uses_target_last_attempt(self):
        first_delivery = ensure_qq_push_deliveries(self.article, [self.target])[0]
        first_delivery.last_attempt_at = timezone.now() - timedelta(seconds=15)
        first_delivery.save(update_fields=["last_attempt_at", "updated_at"])
        second_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="qq-auto-2",
            title_ja="原文标题2",
            title_zh="中文标题2",
            body_ja_raw="原文正文2",
            body_ja_normalized="原文正文2",
            body_zh="中文正文2",
            published_at=timezone.now(),
            source_url="https://example.com/article/qq-auto-2",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
            score_total=90,
        )
        second_delivery = ensure_qq_push_deliveries(second_article, [self.target])[0]

        delay = qq_push_next_attempt_delay(second_delivery)

        self.assertGreaterEqual(delay, 44)
        self.assertLessEqual(delay, 60)

    @override_settings(QQ_PUSH_ENABLED=True, QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked")
    def test_article_task_queues_only_active_targets_for_ranked_news(self):
        self.article.source_mode = SourceMode.ACCESS
        self.article.score_total = 20
        self.article.save(update_fields=["source_mode", "score_total", "updated_at"])
        with patch("stable.tasks.qq_push_delivery_task.delay") as delay:
            result = qq_auto_push_article_task.run(self.article.id)

        self.assertIn("queued_delivery_ids", result)
        self.assertEqual(len(result["queued_delivery_ids"]), 1)
        self.assertEqual(QQPushDelivery.objects.count(), 1)
        self.assertEqual(QQPushDelivery.objects.get().target, self.target)
        delay.assert_called_once()

    @override_settings(QQ_PUSH_ENABLED=True, QQ_PUSH_SCOPE="high_value_only", QQ_PUSH_IMPORTANCE_STRATEGY="ranked")
    def test_article_task_uses_target_region_and_scope_config(self):
        self.article.racing_region = RacingRegion.HONG_KONG
        self.article.source_language = SourceLanguage.ENGLISH
        self.article.save(update_fields=["racing_region", "source_language", "updated_at"])
        self.target.allowed_regions = [RacingRegion.HONG_KONG]
        self.target.push_scope = "all_public"
        self.target.save(update_fields=["allowed_regions", "push_scope", "updated_at"])
        uk_us_target = PushTarget.objects.create(
            name="英美群",
            group_id="10003",
            allowed_regions=[RacingRegion.UNITED_KINGDOM, RacingRegion.UNITED_STATES],
            push_scope="all_public",
            is_active=True,
        )

        with patch("stable.tasks.qq_push_delivery_task.delay") as delay:
            result = qq_auto_push_article_task.run(self.article.id)

        self.assertEqual(QQPushDelivery.objects.count(), 1)
        self.assertEqual(QQPushDelivery.objects.get().target, self.target)
        self.assertIn(str(uk_us_target.id), result["target_skip_reasons"])
        self.assertEqual(result["target_skip_reasons"][str(uk_us_target.id)], "region_not_allowed")
        delay.assert_called_once()

    def test_article_without_region_is_not_auto_push_eligible(self):
        NewsArticle.objects.filter(pk=self.article.pk).update(racing_region="")
        self.article.refresh_from_db()

        result = should_push_news_to_qq(self.article, target=self.target)

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "region_missing")

    @override_settings(QQ_PUSH_ENABLED=False)
    def test_manual_push_still_works_when_auto_push_disabled(self):
        with patch("stable.services.pushing.BotPusher.send_group_message", return_value={"status": "ok"}):
            logs = push_article_to_targets(self.article, [self.target])

        self.assertEqual(logs[0].status, "success")

    @override_settings(ONEBOT_ACCESS_TOKEN="SECRET", ONEBOT_TIMEOUT_SECONDS=1)
    def test_onebot_errors_redact_token(self):
        with patch("stable.services.onebot.requests.post", side_effect=requests.RequestException("bad SECRET")):
            with self.assertRaises(OneBotRequestError) as error:
                BotPusher().send_group_message("10001", "测试")

        self.assertNotIn("SECRET", str(error.exception))

    def test_onebot_status_check_detects_offline(self):
        class OfflineResponse:
            text = '{"status":"ok","retcode":0,"data":{"online":false}}'

            def raise_for_status(self):
                return None

            def json(self):
                return {"status": "ok", "retcode": 0, "data": {"online": False, "good": False}}

        with patch("stable.services.onebot.requests.get", return_value=OfflineResponse()):
            online, error = BotPusher().is_online()

        self.assertFalse(online)
        self.assertIn("onebot_offline", error)

    @override_settings(ONEBOT_ACCESS_TOKEN="SECRET", ONEBOT_TIMEOUT_SECONDS=1)
    def test_onebot_status_check_errors_redact_token(self):
        with patch("stable.services.onebot.requests.get", side_effect=requests.RequestException("bad SECRET")):
            online, error = BotPusher().is_online()

        self.assertFalse(online)
        self.assertIn("onebot_status_check_failed", error)
        self.assertNotIn("SECRET", error)

    def test_admin_delivery_changelist_is_visible(self):
        user = User.objects.create_superuser("admin2", "admin2@example.com", "admin123456")
        client = Client()
        client.login(username="admin2", password="admin123456")
        ensure_qq_push_deliveries(self.article, [self.target])

        response = client.get(reverse("admin:stable_qqpushdelivery_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "测试群")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ConsoleFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser("admin", "admin@example.com", "admin123456")
        self.client.login(username="admin", password="admin123456")
        sync_builtin_sources()
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="detail-1",
            title_ja="大阪杯回顾",
            translated_title_zh="大阪杯回顾",
            translated_body_zh="这是自动翻译后的正文。",
            translated_summary_zh="自动摘要",
            title_zh="大阪杯回顾",
            summary_zh="自动摘要",
            body_ja_raw="日文正文",
            body_ja_normalized="日文正文",
            body_zh="这是自动翻译后的正文。",
            published_at=timezone.now(),
            source_url="https://example.com/detail-1",
            workflow_status=WorkflowStatus.PENDING_EDIT,
        )

    def _create_article(self, source_article_id: str, title_ja: str) -> NewsArticle:
        return NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id=source_article_id,
            title_ja=title_ja,
            translated_title_zh=title_ja,
            translated_body_zh=f"{title_ja} 的译文",
            title_zh=title_ja,
            body_ja_raw=f"{title_ja} 原文",
            body_ja_normalized=f"{title_ja} 原文",
            body_zh=f"{title_ja} 的译文",
            published_at=timezone.now(),
            source_url=f"https://example.com/{source_article_id}",
            workflow_status=WorkflowStatus.PENDING_EDIT,
        )

    def _post_quick_term(
        self,
        article: NewsArticle,
        source_ja: str,
        target_zh: str,
        *,
        source_context: str = "candidate",
        term_type: str = "horse",
        follow: bool = False,
    ):
        next_url = (
            reverse("console-article-editor", args=[article.id])
            if source_context == "editor"
            else reverse("console-candidate-detail", args=[article.id])
        )
        return self.client.post(
            reverse("console-article-quick-term-create", args=[article.id]),
            {
                "source_ja": source_ja,
                "term_type": term_type,
                "target_zh": target_zh,
                "source_context": source_context,
                "next": next_url,
            },
            follow=follow,
        )

    def _assert_quick_term_toast(self, response, source_ja: str, target_zh: str, context: str):
        self.assertContains(response, f"术语【{source_ja}（{target_zh}）】已添加，点击此处立即应用到文章中")
        self.assertContains(response, "data-quick-term-followup-toast")
        self.assertContains(response, 'data-auto-dismiss-ms="15000"')
        self.assertContains(response, "data-quick-term-followup-close")
        self.assertContains(response, f"apply-created-term-{context}")
        self.assertNotContains(response, f"刚创建术语：{source_ja}")
        self.assertNotContains(response, f"retranslate-created-term-{context}")

    def test_dashboard_and_sources_page_available(self):
        dashboard = self.client.get(reverse("console-dashboard"))
        source_page = self.client.get(reverse("console-source-list"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "工作台")
        self.assertEqual(source_page.status_code, 200)
        self.assertContains(source_page, "来源管理")

    def test_source_pages_show_success_no_new_failure_and_stale_health(self):
        sources = {source.source_mode: source for source in NewsSource.objects.all()}
        latest = sources[SourceMode.LATEST]
        latest.last_crawl_at = timezone.now()
        latest.last_crawl_status = TaskStatus.SUCCESS
        latest.last_crawl_message = "新增 0，重复 120"
        latest.save(update_fields=["last_crawl_at", "last_crawl_status", "last_crawl_message", "updated_at"])
        CrawlJob.objects.create(source=latest, status=TaskStatus.SUCCESS, success_count=0, fail_count=120)

        access = sources[SourceMode.ACCESS]
        access.last_crawl_at = timezone.now()
        access.last_crawl_status = TaskStatus.FAILED
        access.last_crawl_message = "解析失败"
        access.save(update_fields=["last_crawl_at", "last_crawl_status", "last_crawl_message", "updated_at"])
        CrawlJob.objects.create(source=access, status=TaskStatus.FAILED, error_message="解析失败")

        attention = sources[SourceMode.ATTENTION]
        stale_time = timezone.now() - timedelta(hours=4)
        attention.last_crawl_at = stale_time
        attention.last_crawl_status = TaskStatus.SUCCESS
        attention.last_crawl_message = "新增 3，重复 37"
        attention.save(update_fields=["last_crawl_at", "last_crawl_status", "last_crawl_message", "updated_at"])
        CrawlJob.objects.create(source=attention, status=TaskStatus.SUCCESS, success_count=3, fail_count=37, started_at=stale_time, finished_at=stale_time)

        source_page = self.client.get(reverse("console-source-list"))
        dashboard = self.client.get(reverse("console-dashboard"))
        self.assertContains(source_page, "成功无新增")
        self.assertContains(source_page, "新增 0，重复 120")
        self.assertContains(source_page, "解析失败")
        self.assertContains(source_page, "长时间未运行")
        self.assertContains(dashboard, "成功无新增")

    def test_source_health_shows_current_running_job_before_stale_success_cache(self):
        source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.LATEST)
        source.last_crawl_at = timezone.now() - timedelta(minutes=5)
        source.last_crawl_status = TaskStatus.SUCCESS
        source.last_crawl_message = "新增 0，重复 120"
        source.save(update_fields=["last_crawl_at", "last_crawl_status", "last_crawl_message", "updated_at"])
        CrawlJob.objects.create(source=source, status=TaskStatus.SUCCESS, success_count=0, fail_count=120, finished_at=timezone.now() - timedelta(minutes=5))
        CrawlJob.objects.create(source=source, status=TaskStatus.STARTED, started_at=timezone.now())

        source_page = self.client.get(reverse("console-source-list"))

        self.assertContains(source_page, "运行中")
        self.assertNotContains(source_page, "成功无新增")

    def test_source_health_shows_first_running_job_instead_of_not_run_or_stale(self):
        source = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        CrawlJob.objects.create(source=source, status=TaskStatus.STARTED, started_at=timezone.now())

        source_page = self.client.get(reverse("console-source-list"))

        self.assertContains(source_page, "运行中")
        self.assertNotContains(source_page, "长时间未运行")

    def test_source_health_shows_timed_out_running_job(self):
        source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ACCESS)
        CrawlJob.objects.create(source=source, status=TaskStatus.STARTED, started_at=timezone.now() - timedelta(minutes=61))

        source_page = self.client.get(reverse("console-source-list"))

        self.assertContains(source_page, "运行超时")
        self.assertContains(source_page, "超过 60 分钟")

    def test_source_health_shows_old_never_run_source_as_stale(self):
        source = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        old_time = timezone.now() - timedelta(hours=37)
        NewsSource.objects.filter(pk=source.pk).update(created_at=old_time)
        source.refresh_from_db()

        from stable.views import _source_health

        health = _source_health(source, now=timezone.now())

        self.assertEqual(health["label"], "长时间未运行")
        self.assertIn("超过", health["summary"])

    def test_source_health_does_not_mark_disabled_source_as_stale(self):
        source = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        old_time = timezone.now() - timedelta(hours=37)
        NewsSource.objects.filter(pk=source.pk).update(created_at=old_time, enabled=False)
        source.refresh_from_db()

        from stable.views import _source_health

        health = _source_health(source, now=timezone.now())

        self.assertEqual(health["label"], "未运行")
        self.assertFalse(health["is_stale"])

    def test_public_backend_route_and_legacy_console_redirect_work(self):
        dashboard = self.client.get("/admin/")
        legacy = self.client.get("/console/", follow=False)
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(legacy.status_code, 302)
        self.assertEqual(legacy["Location"], "/admin/")

    def test_editor_can_publish_article_and_show_on_public_page(self):
        response = self.client.post(
            reverse("console-article-editor", args=[self.article.id]),
            {
                "title_zh": "大阪杯回顾",
                "summary_zh": "中文摘要",
                "body_zh": "这是发布正文。",
                "tags_text": "赛事, 赛后复盘",
                "source_note": "netkeiba",
                "editor_notes": "已校对",
                "publish_without_cover": "1",
                "intent": "publish",
            },
            follow=True,
        )
        self.article.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PUBLISHED)
        public_detail = self.client.get(self.article.public_path)
        self.assertEqual(public_detail.status_code, 200)
        self.assertContains(public_detail, "这是发布正文。")

    def test_candidate_retranslate_endpoint_redirects(self):
        with patch("stable.views.dispatch_task") as mocked_dispatch:
            response = self.client.post(
                reverse("console-candidate-retranslate", args=[self.article.id]),
                {"next": reverse("console-candidate-detail", args=[self.article.id])},
            )
        self.assertEqual(response.status_code, 302)
        mocked_dispatch.assert_called_once_with(translate_article_task, self.article.id)

    def test_apply_created_term_service_updates_only_specified_term(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_ja="マヤノライジン",
            target_zh="摩耶雷神",
            aliases_ja=["マヤノR"],
        )
        TermEntry.objects.create(term_type="race", source_ja="大阪杯", target_zh="大阪杯")
        other_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="detail-other",
            title_ja="其他文章",
            translated_body_zh="マヤノライジン",
            published_at=timezone.now(),
            source_url="https://example.com/detail-other",
        )
        self.article.translated_title_zh = "マヤノライジン挑战"
        self.article.translated_body_zh = "マヤノライジン与マヤノR连续出现。大阪杯保持原样。"
        self.article.base_translation_zh = "基准稿提到マヤノR，也提到大阪杯。"
        self.article.body_zh = "发布稿：マヤノライジン、マヤノライジン。大阪杯。"
        self.article.save()

        result = apply_created_term_to_article(self.article, term)

        self.article.refresh_from_db()
        other_article.refresh_from_db()
        self.assertIn("translated_title_zh", result.updated_fields)
        self.assertIn("translated_body_zh", result.updated_fields)
        self.assertIn("base_translation_zh", result.updated_fields)
        self.assertEqual(self.article.translated_title_zh, "摩耶雷神挑战")
        self.assertEqual(self.article.translated_body_zh, "摩耶雷神与摩耶雷神连续出现。大阪杯保持原样。")
        self.assertEqual(self.article.base_translation_zh, "基准稿提到摩耶雷神，也提到大阪杯。")
        self.assertEqual(self.article.body_zh, "发布稿：摩耶雷神、摩耶雷神。大阪杯。")
        self.assertEqual(other_article.translated_body_zh, "マヤノライジン")

    def test_apply_created_term_service_protects_manual_publish_fields(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        self.article.translated_body_zh = "机器稿 マヤノライジン"
        self.article.title_zh = "人工标题 マヤノライジン"
        self.article.body_zh = "人工正文 マヤノライジン"
        self.article.summary_zh = "人工摘要 マヤノライジン"
        self.article.push_summary_zh = "人工推送 マヤノライジン"
        self.article.manually_edited_fields = ["title_zh", "body_zh", "summary_zh", "push_summary_zh"]
        self.article.save()

        result = apply_created_term_to_article(self.article, term)

        self.article.refresh_from_db()
        self.assertEqual(self.article.translated_body_zh, "机器稿 摩耶雷神")
        self.assertEqual(self.article.title_zh, "人工标题 マヤノライジン")
        self.assertEqual(self.article.body_zh, "人工正文 マヤノライジン")
        self.assertEqual(self.article.summary_zh, "人工摘要 マヤノライジン")
        self.assertEqual(self.article.push_summary_zh, "人工推送 マヤノライジン")
        self.assertEqual(
            set(result.skipped_fields),
            {"title_zh", "body_zh", "summary_zh", "push_summary_zh"},
        )

    def test_candidate_detail_quick_term_create_defaults_to_horse_and_logs_article(self):
        response = self._post_quick_term(self.article, "マヤノライジン", "摩耶雷神", follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "术语已创建：マヤノライジン")
        self.assertContains(response, "摩耶雷神")
        self._assert_quick_term_toast(response, "マヤノライジン", "摩耶雷神", "candidate")
        term = TermEntry.objects.get(source_ja="マヤノライジン")
        self.assertEqual(term.term_type, "horse")
        self.assertEqual(term.target_zh, "摩耶雷神")
        self.assertEqual(term.aliases_ja, [])
        self.assertEqual(term.aliases_zh, [])
        self.assertEqual(term.priority, 0)
        self.assertEqual(term.race_grade, "")
        self.assertTrue(term.is_active)
        self.assertIn(f"文章 #{self.article.id}", term.notes)
        self.assertTrue(
            OperationLog.objects.filter(
                action_type="article_quick_term_created",
                target_type="term",
                target_id=str(term.id),
                detail__contains=f"文章 #{self.article.id}",
            ).exists()
        )

        refreshed = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        self.assertNotContains(refreshed, "术语【マヤノライジン（摩耶雷神）】已添加")
        self.assertNotContains(refreshed, "apply-created-term-candidate")

    def test_article_editor_quick_term_create_returns_to_editor(self):
        editor_url = reverse("console-article-editor", args=[self.article.id])
        response = self._post_quick_term(
            self.article,
            "大阪杯",
            "大阪杯",
            source_context="editor",
            term_type="race",
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], editor_url)
        self._assert_quick_term_toast(response, "大阪杯", "大阪杯", "editor")
        self.assertTrue(TermEntry.objects.filter(term_type="race", source_ja="大阪杯").exists())

    def test_quick_term_followup_keeps_other_article_pending_until_matching_page_renders(self):
        other_article = self._create_article("detail-other-pending", "別記事")

        self._post_quick_term(self.article, "マヤノライジン", "摩耶雷神")

        other_response = self.client.get(reverse("console-candidate-detail", args=[other_article.id]))
        self.assertNotContains(other_response, "术语【マヤノライジン（摩耶雷神）】已添加")

        matching_response = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        self._assert_quick_term_toast(matching_response, "マヤノライジン", "摩耶雷神", "candidate")

    def test_quick_term_followup_keeps_parallel_candidate_and_editor_contexts(self):
        other_article = self._create_article("detail-editor-pending", "編集台記事")

        self._post_quick_term(self.article, "マヤノライジン", "摩耶雷神", source_context="candidate")
        self._post_quick_term(other_article, "ナリタブライアン", "成田白仁", source_context="editor")

        candidate_response = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        editor_response = self.client.get(reverse("console-article-editor", args=[other_article.id]))

        self._assert_quick_term_toast(candidate_response, "マヤノライジン", "摩耶雷神", "candidate")
        self._assert_quick_term_toast(editor_response, "ナリタブライアン", "成田白仁", "editor")

    def test_quick_term_followup_replaces_old_pending_for_same_page(self):
        self._post_quick_term(self.article, "古い馬", "旧译名")
        self._post_quick_term(self.article, "新しい馬", "新译名")

        response = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))

        self.assertNotContains(response, "术语【古い馬（旧译名）】已添加")
        self._assert_quick_term_toast(response, "新しい馬", "新译名", "candidate")

    def test_apply_created_term_from_followup_does_not_dispatch_translation_task(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        self.article.translated_body_zh = "マヤノライジン"
        self.article.save(update_fields=["translated_body_zh", "updated_at"])

        with patch("stable.views.dispatch_task") as mocked_dispatch:
            response = self.client.post(
                reverse("console-article-apply-created-term", args=[self.article.id]),
                {
                    "term_id": term.id,
                    "source_context": "candidate",
                    "next": reverse("console-candidate-detail", args=[self.article.id]),
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        mocked_dispatch.assert_not_called()

    def test_apply_created_term_endpoint_updates_article_and_sanitizes_next(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        self.article.translated_body_zh = "マヤノライジン"
        self.article.base_translation_zh = "基准 マヤノライジン"
        self.article.body_zh = "发布 マヤノライジン"
        self.article.save()

        response = self.client.post(
            reverse("console-article-apply-created-term", args=[self.article.id]),
            {
                "term_id": term.id,
                "source_context": "editor",
                "next": "https://evil.example/",
            },
            follow=True,
        )

        self.article.refresh_from_db()
        self.assertEqual(response.redirect_chain[-1][0], reverse("console-article-editor", args=[self.article.id]))
        self.assertEqual(self.article.translated_body_zh, "摩耶雷神")
        self.assertEqual(self.article.base_translation_zh, "基准 摩耶雷神")
        self.assertEqual(self.article.body_zh, "发布 摩耶雷神")
        self.assertContains(response, "已应用该术语")
        self.assertTrue(
            OperationLog.objects.filter(
                action_type="article_created_term_applied",
                target_type="article",
                target_id=str(self.article.id),
                detail__contains=f"术语 #{term.id}",
            )
            .filter(detail__contains="更新字段")
            .exists()
        )

    def test_apply_created_term_endpoint_reports_no_change_and_protected_fields(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        self.article.title_zh = "人工标题 マヤノライジン"
        self.article.body_zh = "人工正文 マヤノライジン"
        self.article.summary_zh = "人工摘要 マヤノライジン"
        self.article.push_summary_zh = "人工推送 マヤノライジン"
        self.article.manually_edited_fields = ["title_zh", "body_zh", "summary_zh", "push_summary_zh"]
        self.article.save()

        response = self.client.post(
            reverse("console-article-apply-created-term", args=[self.article.id]),
            {
                "term_id": term.id,
                "source_context": "candidate",
                "next": reverse("console-candidate-detail", args=[self.article.id]),
            },
            follow=True,
        )

        self.article.refresh_from_db()
        self.assertEqual(self.article.title_zh, "人工标题 マヤノライジン")
        self.assertEqual(self.article.body_zh, "人工正文 マヤノライジン")
        self.assertEqual(self.article.summary_zh, "人工摘要 マヤノライジン")
        self.assertEqual(self.article.push_summary_zh, "人工推送 マヤノライジン")
        self.assertContains(response, "没有可更新字段")
        self.assertContains(response, "已保护人工编辑字段")

    def test_page_level_retranslate_logs_task_result_and_does_not_publish(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        self.article.workflow_status = WorkflowStatus.PENDING_EDIT
        self.article.save(update_fields=["workflow_status", "updated_at"])

        with patch("stable.views.dispatch_task") as mocked_dispatch:
            response = self.client.post(
                reverse("console-candidate-retranslate", args=[self.article.id]),
                {
                    "source_context": "candidate",
                    "next": reverse("console-candidate-detail", args=[self.article.id]),
                },
                follow=True,
            )

        self.article.refresh_from_db()
        mocked_dispatch.assert_called_once_with(translate_article_task, self.article.id)
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PENDING_EDIT)
        self.assertContains(response, "已重新触发翻译")
        self.assertTrue(
            OperationLog.objects.filter(
                action_type="article_retranslated",
                target_id=str(self.article.id),
                detail__contains="任务已派发",
            )
            .exists()
        )
        self.assertFalse(
            OperationLog.objects.filter(
                action_type="article_retranslated",
                target_id=str(self.article.id),
                detail__contains=f"来源术语 #{term.id}",
            ).exists()
        )

    def test_quick_term_create_rejects_blank_long_and_duplicate_source(self):
        url = reverse("console-article-quick-term-create", args=[self.article.id])
        TermEntry.objects.create(term_type="horse", source_ja="重複馬", target_zh="重复马")
        cases = [
            (
                {"source_ja": "タイトル", "term_type": "horse", "target_zh": ""},
                "中文译词不能为空。",
            ),
            (
                {"source_ja": "", "term_type": "horse", "target_zh": "空词"},
                "原文不能为空",
            ),
            (
                {"source_ja": "ア" * 81, "term_type": "horse", "target_zh": "过长"},
                "原文过长",
            ),
            (
                {"source_ja": "マヤノライジン\nゲート確認", "term_type": "horse", "target_zh": "整段误选"},
                "不能包含换行",
            ),
            (
                {"source_ja": "重複馬", "term_type": "horse", "target_zh": "重复马二号"},
                "打开已有术语",
            ),
            (
                {"source_ja": "タイプ不正", "term_type": "not-a-term-type", "target_zh": "非法类型"},
                "术语类型不合法",
            ),
        ]

        for payload, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                before_count = TermEntry.objects.count()
                response = self.client.post(
                    url,
                    {**payload, "next": reverse("console-candidate-detail", args=[self.article.id])},
                    follow=True,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(TermEntry.objects.count(), before_count)
                self.assertContains(response, expected_message)

    def test_quick_term_create_requires_staff(self):
        url = reverse("console-article-quick-term-create", args=[self.article.id])
        self.client.logout()

        anonymous = self.client.post(url, {"source_ja": "未登录", "term_type": "horse", "target_zh": "未登录"})
        self.assertEqual(anonymous.status_code, 302)
        self.assertFalse(TermEntry.objects.filter(source_ja="未登录").exists())

        normal_user = User.objects.create_user("editor", "editor@example.com", "editor123456")
        self.client.login(username="editor", password="editor123456")
        forbidden = self.client.post(url, {"source_ja": "普通用户", "term_type": "horse", "target_zh": "普通用户"})
        self.assertEqual(forbidden.status_code, 403)
        self.assertFalse(TermEntry.objects.filter(source_ja="普通用户").exists())

    def test_quick_term_create_does_not_retranslate_or_mutate_article_copy(self):
        self.article.title_zh = "旧中文标题"
        self.article.body_zh = "旧中文正文"
        self.article.base_translation_zh = "旧基准翻译"
        self.article.rewrite_body_zh = "旧改写正文"
        self.article.workflow_status = WorkflowStatus.PENDING_EDIT
        self.article.automation_status = AutomationStatus.PENDING
        self.article.save()

        with patch("stable.views.dispatch_task") as mocked_dispatch:
            response = self.client.post(
                reverse("console-article-quick-term-create", args=[self.article.id]),
                {
                    "source_ja": "非联动馬",
                    "term_type": "horse",
                    "target_zh": "非联动马",
                    "next": reverse("console-candidate-detail", args=[self.article.id]),
                },
            )

        self.assertEqual(response.status_code, 302)
        mocked_dispatch.assert_not_called()
        self.article.refresh_from_db()
        self.assertEqual(self.article.title_zh, "旧中文标题")
        self.assertEqual(self.article.body_zh, "旧中文正文")
        self.assertEqual(self.article.base_translation_zh, "旧基准翻译")
        self.assertEqual(self.article.rewrite_body_zh, "旧改写正文")
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PENDING_EDIT)
        self.assertEqual(self.article.automation_status, AutomationStatus.PENDING)

    def test_quick_term_create_rejects_missing_article_without_creating_term(self):
        response = self.client.post(
            reverse("console-article-quick-term-create", args=[999999]),
            {
                "source_ja": "存在しない記事",
                "term_type": "horse",
                "target_zh": "不存在文章",
                "next": reverse("console-candidate-detail", args=[self.article.id]),
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(TermEntry.objects.filter(source_ja="存在しない記事").exists())

    def test_candidate_and_editor_templates_include_quick_term_entry(self):
        candidate = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        editor = self.client.get(reverse("console-article-editor", args=[self.article.id]))

        for response in (candidate, editor):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "快速加入术语库")
            self.assertContains(response, "加入术语库后会出现一次性操作")
            self.assertContains(response, 'name="csrfmiddlewaretoken"')
            self.assertContains(response, 'name="next"')
            self.assertContains(response, 'name="source_context"')
            self.assertContains(response, 'data-term-selection-source')
            self.assertContains(response, 'data-fill-selected-term')
            self.assertContains(response, '<option value="horse" selected>马名</option>', html=True)
            self.assertNotContains(response, "应用该术语到当前稿")
        self.assertContains(candidate, 'id="quick-term-candidate-form"')
        self.assertContains(candidate, 'form="quick-term-candidate-form"')
        self.assertContains(editor, 'id="quick-term-editor-form"')
        self.assertContains(editor, 'form="quick-term-editor-form"')

    def test_quick_term_script_prefills_only_original_selection(self):
        candidate = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        html = candidate.content.decode()

        self.assertIn('closest("[data-term-selection-source]")', html)
        self.assertIn("anchorSource !== focusSource", html)
        self.assertIn('status.textContent = "请先在原文标题或正文中选择一个短词。";', html)
        self.assertIn("sourceInput.value = text;", html)

    def test_public_feed_only_shows_published_articles(self):
        NewsArticle.objects.create(
            source_site=SourceSite.JRA,
            source_mode=SourceMode.OFFICIAL,
            source_article_id="draft-2",
            title_ja="草稿新闻",
            title_zh="草稿新闻",
            body_ja_raw="原文",
            body_ja_normalized="原文",
            body_zh="未发布内容",
            published_at=timezone.now(),
            source_url="https://example.com/draft-2",
            workflow_status=WorkflowStatus.PENDING_EDIT,
        )
        self.article.workflow_status = WorkflowStatus.PUBLISHED
        self.article.published_to_web_at = timezone.now()
        self.article.save()
        response = self.client.get("/")
        self.assertContains(response, "大阪杯回顾")
        self.assertNotContains(response, "草稿新闻")

    def test_editor_requires_body_but_allows_blank_summary(self):
        response = self.client.post(
            reverse("console-article-editor", args=[self.article.id]),
            {
                "title_zh": "大阪杯回顾",
                "summary_zh": "",
                "body_zh": "",
                "tags_text": "",
                "source_note": "",
                "editor_notes": "",
                "intent": "save",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "正文不能为空。")

    def test_editor_can_clear_summary_without_being_refilled(self):
        self.article.summary_zh = "旧摘要"
        self.article.push_summary_zh = "机器摘要"
        self.article.translated_summary_zh = "机器摘要"
        self.article.save()

        response = self.client.post(
            reverse("console-article-editor", args=[self.article.id]),
            {
                "title_zh": "大阪杯回顾",
                "summary_zh": "",
                "body_zh": "这是自动翻译后的正文。",
                "tags_text": "",
                "source_note": "",
                "editor_notes": "",
                "intent": "save",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.article.refresh_from_db()
        self.assertEqual(self.article.summary_zh, "")
        self.assertEqual(self.article.effective_summary, "")

    def test_duplicate_reference_links_to_candidate_detail(self):
        original = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.ACCESS,
            source_article_id="original-for-duplicate-link",
            title_ja="相似原稿",
            translated_title_zh="相似原稿",
            title_zh="相似原稿",
            body_ja_raw="相似原稿の本文",
            body_ja_normalized="相似原稿の本文",
            translated_body_zh="相似原稿的正文。",
            body_zh="相似原稿的正文。",
            published_at=timezone.now(),
            source_url="https://example.com/original-for-duplicate-link",
            workflow_status=WorkflowStatus.PUBLISHED,
        )
        self.article.duplicate_of = original
        self.article.duplicate_score = 0.91
        self.article.workflow_status = WorkflowStatus.DUPLICATE
        self.article.save(update_fields=["duplicate_of", "duplicate_score", "workflow_status", "updated_at"])

        detail = self.client.get(reverse("console-candidate-detail", args=[self.article.id]))
        candidate_list = self.client.get(reverse("console-candidate-list"))
        duplicate_href = reverse("console-candidate-detail", args=[original.id])

        self.assertContains(detail, f'href="{duplicate_href}"')
        self.assertContains(candidate_list, f'href="{duplicate_href}"')


class PublicHomeInfoFeedTests(TestCase):
    def make_article(
        self,
        source_article_id: str,
        title: str,
        *,
        workflow_status: str = WorkflowStatus.PUBLISHED,
        published_to_web_at=None,
        published_at=None,
        score_total: int = 0,
        race_priority: str = "",
        has_cover: bool = False,
        source_mode: str = SourceMode.LATEST,
        racing_region: str = RacingRegion.JAPAN,
        source_language: str = SourceLanguage.JAPANESE,
        tags: list[str] | None = None,
    ) -> NewsArticle:
        published_at = published_at or timezone.now()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=source_mode,
            racing_region=racing_region,
            source_language=source_language,
            source_article_id=source_article_id,
            title_ja=title,
            translated_title_zh=title,
            title_zh=title,
            body_ja_raw=f"{title} 原文",
            body_ja_normalized=f"{title} 原文",
            translated_body_zh=f"{title} 正文",
            body_zh=f"{title} 正文",
            translated_summary_zh=f"{title} 摘要",
            summary_zh=f"{title} 摘要",
            published_at=published_at,
            source_url=f"https://example.com/{source_article_id}",
            workflow_status=workflow_status,
            published_to_web_at=published_to_web_at if published_to_web_at is not None else published_at,
            source_note="netkeiba",
            tags_json=tags or ["赛马"],
            score_total=score_total,
            decision_reason={"signals": {"race_priority": race_priority}} if race_priority else {},
        )
        if has_cover:
            NewsImage.objects.create(
                article=article,
                original_url=f"https://example.com/images/{source_article_id}.jpg",
                caption_zh=title,
            )
        return article

    def test_article_public_path_uses_article_id(self):
        article = self.make_article("id-public-path", "ID 链接文章")

        self.assertEqual(article.public_path, f"/news/{article.id}/")

    def test_unsaved_article_public_path_is_blank(self):
        article = NewsArticle(title_zh="未保存文章")

        self.assertEqual(article.public_path, "")

    def test_public_article_detail_can_be_visited_by_article_id(self):
        article = self.make_article("id-detail", "ID 详情文章")

        response = self.client.get(f"/news/{article.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ID 详情文章")

    def test_unpublished_article_id_is_not_public(self):
        article = self.make_article(
            "id-unpublished",
            "未发布 ID 文章",
            workflow_status=WorkflowStatus.PENDING_EDIT,
            published_to_web_at=None,
        )

        response = self.client.get(f"/news/{article.id}/")

        self.assertEqual(response.status_code, 404)

    def test_legacy_non_numeric_slug_redirects_to_article_id_url(self):
        article = self.make_article("legacy-slug", "旧 slug 文章")
        article.public_slug = "legacy-slug-path"
        article.save(update_fields=["public_slug", "updated_at"])

        response = self.client.get("/news/legacy-slug-path/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/news/{article.id}/")

    def test_public_home_links_use_article_id_url(self):
        article = self.make_article("home-id-link", "首页 ID 链接文章")
        article.public_slug = "home-legacy-slug"
        article.save(update_fields=["public_slug", "updated_at"])

        response = self.client.get("/")

        self.assertContains(response, f'href="/news/{article.id}/"')
        self.assertNotContains(response, 'href="/news/home-legacy-slug/"')

    def test_public_home_latest_articles_filter_and_order_published_items(self):
        now = timezone.now()
        self.make_article("older", "较早发布", published_to_web_at=now - timedelta(hours=2))
        self.make_article("newer", "最新发布", published_to_web_at=now)
        self.make_article(
            "draft",
            "待编辑草稿",
            workflow_status=WorkflowStatus.PENDING_EDIT,
            published_to_web_at=now + timedelta(hours=1),
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        latest_titles = [article.effective_title for article in response.context["latest_articles"]]
        self.assertEqual(latest_titles, ["最新发布", "较早发布"])

    def test_public_home_region_tabs_filter_published_articles(self):
        now = timezone.now()
        self.make_article("jp-region", "日本新闻", published_to_web_at=now - timedelta(minutes=2))
        hk_article = self.make_article(
            "hk-region",
            "香港新闻",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            published_to_web_at=now,
        )
        self.make_article(
            "uk-draft",
            "英国草稿",
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_language=SourceLanguage.ENGLISH,
            workflow_status=WorkflowStatus.PENDING_EDIT,
            published_to_web_at=now + timedelta(minutes=1),
        )

        aggregate = self.client.get("/")
        hk = self.client.get("/", {"region": RacingRegion.HONG_KONG})

        self.assertContains(aggregate, "综合")
        self.assertContains(aggregate, "日本")
        self.assertContains(aggregate, "中国香港")
        self.assertContains(aggregate, "英国")
        self.assertContains(aggregate, "法国")
        self.assertContains(aggregate, "美国")
        self.assertEqual([article.effective_title for article in aggregate.context["latest_articles"]], ["香港新闻", "日本新闻"])
        self.assertEqual([article.effective_title for article in hk.context["latest_articles"]], ["香港新闻"])
        self.assertEqual(hk.context["headline_article"], hk_article)
        self.assertNotContains(hk, "日本新闻")
        self.assertNotContains(hk, "英国草稿")

    def test_public_home_pagination_preserves_region_filter(self):
        now = timezone.now()
        for index in range(14):
            self.make_article(
                f"hk-page-{index}",
                f"香港分页新闻 {index}",
                racing_region=RacingRegion.HONG_KONG,
                source_language=SourceLanguage.ENGLISH,
                published_to_web_at=now - timedelta(minutes=index),
            )

        response = self.client.get("/", {"region": RacingRegion.HONG_KONG})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "?region=hong_kong&amp;page=2")

    def test_public_detail_shows_region_source_and_source_language(self):
        article = self.make_article(
            "us-detail",
            "美国详情",
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
            source_mode=SourceMode.LATEST,
        )

        response = self.client.get(article.public_path)

        self.assertContains(response, "美国")
        self.assertContains(response, "英文")
        self.assertContains(response, "netkeiba")

    def test_public_home_selects_recent_high_value_cover_article_as_headline(self):
        now = timezone.now()
        self.make_article(
            "new-low",
            "最新普通稿",
            published_to_web_at=now,
            score_total=20,
        )
        featured = self.make_article(
            "featured",
            "宝塚纪念重点稿",
            published_to_web_at=now - timedelta(hours=1),
            score_total=95,
            race_priority="P0",
            has_cover=True,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["headline_article"], featured)

    def test_public_home_headline_falls_back_to_latest_published_article(self):
        now = timezone.now()
        old_article = self.make_article(
            "old",
            "七天外旧稿",
            published_to_web_at=now - timedelta(days=10),
            score_total=20,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["headline_article"], old_article)

    def test_public_home_feed_articles_do_not_repeat_headline(self):
        now = timezone.now()
        headline = self.make_article(
            "featured-no-repeat",
            "重点头条",
            published_to_web_at=now,
            score_total=95,
            race_priority="P0",
            has_cover=True,
        )
        regular = self.make_article(
            "regular-no-repeat",
            "普通新闻",
            published_to_web_at=now - timedelta(minutes=5),
            score_total=20,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["headline_article"], headline)
        self.assertNotIn(headline, response.context["feed_articles"])
        self.assertIn(regular, response.context["feed_articles"])

    def test_public_home_hot_articles_prioritize_upstream_access_snapshot(self):
        now = timezone.now()
        snapshot_article = self.make_article(
            "snapshot-hot",
            "原站访问榜文章",
            published_to_web_at=now - timedelta(hours=1),
            score_total=30,
        )
        high_score_article = self.make_article(
            "score-hot",
            "高分无快照文章",
            published_to_web_at=now,
            score_total=95,
        )
        NewsSnapshot.objects.create(
            article=snapshot_article,
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.ACCESS,
            rank=1,
            comment_count=18,
            attention_count=4,
            captured_at=now,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        hot_articles = [entry["article"] for entry in response.context["hot_articles"]]
        self.assertEqual(hot_articles[0], snapshot_article)

    def test_public_home_hot_articles_fall_back_to_score_and_recency_without_snapshots(self):
        now = timezone.now()
        low_score_newer = self.make_article(
            "low-score-hot",
            "低分新稿",
            published_to_web_at=now,
            score_total=10,
        )
        high_score_older = self.make_article(
            "high-score-hot",
            "高分旧稿",
            published_to_web_at=now - timedelta(hours=3),
            score_total=85,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        hot_articles = [entry["article"] for entry in response.context["hot_articles"]]
        self.assertEqual(hot_articles[:2], [high_score_older, low_score_newer])
        self.assertTrue(all(entry["snapshot"] is None for entry in response.context["hot_articles"]))

    def test_public_home_labels_upstream_hot_signal_without_site_metric_claims(self):
        now = timezone.now()
        hot = self.make_article("label-hot", "访问榜重点稿", published_to_web_at=now)
        NewsSnapshot.objects.create(
            article=hot,
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.ACCESS,
            rank=2,
            comment_count=88,
            attention_count=66,
            captured_at=now,
        )

        response = self.client.get("/")

        self.assertContains(response, "原站热度")
        self.assertNotContains(response, "本站评论")
        self.assertNotContains(response, "本站浏览")

    def test_public_pages_use_public_stylesheet_instead_of_console_stylesheet(self):
        article = self.make_article("public-css", "公开样式测试", published_to_web_at=timezone.now())

        home = self.client.get("/")
        detail = self.client.get(article.public_path)

        for response in (home, detail):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'stable/public.css')
            self.assertNotContains(response, 'stable/console.css')

    def test_public_detail_uses_public_structure_and_effective_article_fields(self):
        article = self.make_article("detail-public", "原始标题", published_to_web_at=timezone.now())
        article.rewrite_title_zh = "改写标题"
        article.rewrite_summary_zh = "改写摘要"
        article.rewrite_body_zh = "改写正文第一段。\n改写正文第二段。"
        article.source_note = "netkeiba"
        article.save()

        response = self.client.get(article.public_path)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-public-detail')
        self.assertContains(response, "改写标题")
        self.assertContains(response, "改写摘要")
        self.assertContains(response, "改写正文第一段")
        self.assertContains(response, "netkeiba")
        self.assertContains(response, article.source_url)

    def test_public_detail_requires_web_publish_time(self):
        article = self.make_article("detail-without-web-time", "无发布时间", published_to_web_at=None)
        article.published_to_web_at = None
        article.save(update_fields=["published_to_web_at", "updated_at"])

        response = self.client.get(article.public_path)

        self.assertEqual(response.status_code, 404)


class RankedNewsRevivalTests(TestCase):
    def _article(self, **overrides):
        payload = {
            "source_site": SourceSite.NETKEIBA,
            "source_mode": SourceMode.ACCESS,
            "source_article_id": overrides.pop("source_article_id", f"ranked-revival-{NewsArticle.objects.count()}"),
            "racing_region": RacingRegion.JAPAN,
            "source_language": SourceLanguage.JAPANESE,
            "title_ja": overrides.pop("title_ja", "ランキング再浮上ニュース"),
            "body_ja_raw": overrides.pop("body_ja_raw", "レース前の展望記事です。" * 20),
            "body_ja_normalized": overrides.pop("body_ja_normalized", "レース前の展望記事です。" * 20),
            "translated_title_zh": overrides.pop("translated_title_zh", "榜单唤醒新闻"),
            "title_zh": overrides.pop("title_zh", "榜单唤醒新闻"),
            "translated_summary_zh": overrides.pop("translated_summary_zh", "榜单唤醒摘要"),
            "summary_zh": overrides.pop("summary_zh", "榜单唤醒摘要"),
            "translated_body_zh": overrides.pop("translated_body_zh", "榜单唤醒正文。" * 30),
            "body_zh": overrides.pop("body_zh", "榜单唤醒正文。" * 30),
            "published_at": timezone.now(),
            "source_url": overrides.pop("source_url", f"https://example.com/ranked/{NewsArticle.objects.count()}"),
            "translation_status": ArticleTranslationStatus.TRANSLATED,
            "workflow_status": WorkflowStatus.PENDING_REVIEW,
            "review_mode": ReviewMode.MANUAL,
            "automation_status": AutomationStatus.MANUAL_REVIEW_REQUIRED,
            "score_total": 40,
            "quality_score": 60,
            "decision_reason": {},
            "gate_issues": [],
        }
        payload.update(overrides)
        return NewsArticle.objects.create(**payload)

    def test_ranked_revived_at_is_nullable_indexed_model_field(self):
        field = NewsArticle._meta.get_field("ranked_revived_at")

        self.assertTrue(field.null)
        self.assertTrue(field.blank)
        self.assertTrue(field.db_index)

    def test_low_score_ignored_article_is_revived_for_rescore(self):
        from stable.services.automation import revive_article_after_ranked_source_elevation

        now = datetime(2026, 7, 1, 10, 20, tzinfo=dt_timezone.utc)
        article = self._article(
            workflow_status=WorkflowStatus.IGNORED,
            review_mode=ReviewMode.IGNORED,
            automation_status=AutomationStatus.IGNORED,
            score_total=30,
            ignored_at=now - timedelta(hours=1),
            decision_reason={"scores": {"total": 30}, "summary": "忽略：总分 30，发布价值不足"},
        )

        result = revive_article_after_ranked_source_elevation(article, now=now)

        article.refresh_from_db()
        self.assertTrue(result.revived)
        self.assertEqual(result.action, "rescore")
        self.assertEqual(article.ranked_revived_at, now)
        self.assertEqual(article.workflow_status, WorkflowStatus.PENDING_EDIT)
        self.assertEqual(article.automation_status, AutomationStatus.PENDING)
        self.assertEqual(article.decision_reason["ranked_revival"]["previous_workflow_status"], WorkflowStatus.IGNORED)
        self.assertEqual(article.decision_reason["ranked_revival"]["previous_automation_status"], AutomationStatus.IGNORED)
        self.assertEqual(article.decision_reason["ranked_revival"]["source_mode"], SourceMode.ACCESS)

    def test_hard_rule_ignored_article_is_not_revived(self):
        from stable.services.automation import revive_article_after_ranked_source_elevation

        now = datetime(2026, 7, 1, 10, 22, tzinfo=dt_timezone.utc)
        article = self._article(
            workflow_status=WorkflowStatus.IGNORED,
            review_mode=ReviewMode.IGNORED,
            automation_status=AutomationStatus.IGNORED,
            score_total=60,
            ignored_at=now - timedelta(hours=1),
            decision_reason={
                "hard_rules": ["正文过短或为空"],
                "scores": {"total": 60},
                "summary": "忽略：正文过短或为空",
            },
        )

        result = revive_article_after_ranked_source_elevation(article, now=now)

        article.refresh_from_db()
        self.assertFalse(result.revived)
        self.assertEqual(result.action, "blocked")
        self.assertEqual(result.reason, "hard_rule_ignored")
        self.assertEqual(article.workflow_status, WorkflowStatus.IGNORED)
        self.assertIsNone(article.ranked_revived_at)
        self.assertNotIn("ranked_revival", article.decision_reason)

    def test_manual_value_insufficient_article_is_revived_for_rescore_without_blocker(self):
        from stable.services.automation import revive_article_after_ranked_source_elevation

        now = datetime(2026, 7, 1, 10, 25, tzinfo=dt_timezone.utc)
        article = self._article(
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            review_mode=ReviewMode.MANUAL,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            score_total=50,
            decision_reason={"summary": "转人工：总分 50，价值或确定性不足"},
        )

        result = revive_article_after_ranked_source_elevation(article, now=now)

        article.refresh_from_db()
        self.assertTrue(result.revived)
        self.assertEqual(result.action, "rescore")
        self.assertEqual(article.ranked_revived_at, now)
        self.assertEqual(article.workflow_status, WorkflowStatus.PENDING_EDIT)
        self.assertEqual(article.review_mode, ReviewMode.AUTO)
        self.assertEqual(article.automation_status, AutomationStatus.PENDING)

    def test_translation_failed_article_is_revived_for_one_translation_retry(self):
        from stable.services.automation import revive_article_after_ranked_source_elevation

        now = datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc)
        article = self._article(
            workflow_status=WorkflowStatus.TRANSLATION_FAILED,
            translation_status=ArticleTranslationStatus.FAILED,
            translated_title_zh="",
            title_zh="",
            translated_summary_zh="",
            summary_zh="",
            translated_body_zh="",
            body_zh="",
            review_mode=ReviewMode.MANUAL,
            automation_status=AutomationStatus.FAILED,
            translation_error_message="provider timeout",
        )

        result = revive_article_after_ranked_source_elevation(article, now=now)

        article.refresh_from_db()
        self.assertTrue(result.revived)
        self.assertEqual(result.action, "translation_retry")
        self.assertEqual(article.ranked_revived_at, now)
        self.assertEqual(article.workflow_status, WorkflowStatus.PENDING_TRANSLATION)
        self.assertEqual(article.translation_status, ArticleTranslationStatus.PENDING)
        self.assertEqual(article.decision_reason["ranked_revival"]["translation_retry_requested_at"], now.isoformat())

    def test_pending_translation_article_is_revived_but_not_marked_publish_ready(self):
        from stable.services.automation import revive_article_after_ranked_source_elevation

        now = datetime(2026, 7, 1, 10, 35, tzinfo=dt_timezone.utc)
        article = self._article(
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
            translation_status=ArticleTranslationStatus.PENDING,
            translated_title_zh="",
            title_zh="",
            translated_summary_zh="",
            summary_zh="",
            translated_body_zh="",
            body_zh="",
            automation_status=AutomationStatus.PENDING,
        )

        result = revive_article_after_ranked_source_elevation(article, now=now)

        article.refresh_from_db()
        self.assertTrue(result.revived)
        self.assertEqual(result.action, "translation_retry")
        self.assertEqual(article.workflow_status, WorkflowStatus.PENDING_TRANSLATION)
        self.assertNotEqual(article.automation_status, AutomationStatus.PUBLISH_READY)

    def test_ranked_revival_does_not_revive_terminal_or_blocked_articles(self):
        from stable.services.automation import revive_article_after_ranked_source_elevation

        now = datetime(2026, 7, 1, 10, 40, tzinfo=dt_timezone.utc)
        blocked_cases = [
            self._article(source_article_id="revival-rejected", workflow_status=WorkflowStatus.REJECTED),
            self._article(source_article_id="revival-withdrawn", workflow_status=WorkflowStatus.WITHDRAWN),
            self._article(source_article_id="revival-duplicate", workflow_status=WorkflowStatus.DUPLICATE),
            self._article(
                source_article_id="revival-blocker",
                workflow_status=WorkflowStatus.PENDING_REVIEW,
                gate_issues=[{"code": "core_term_missing", "severity": "blocker"}],
            ),
        ]

        for article in blocked_cases:
            result = revive_article_after_ranked_source_elevation(article, now=now)
            article.refresh_from_db()

            self.assertFalse(result.revived)
            self.assertEqual(result.action, "blocked")
            self.assertIsNone(article.ranked_revived_at)
            self.assertNotIn("ranked_revival", article.decision_reason)

    def test_repeated_ranked_revival_does_not_repeat_translation_retry(self):
        from stable.services.automation import revive_article_after_ranked_source_elevation

        first_revived_at = datetime(2026, 7, 1, 10, 30, tzinfo=dt_timezone.utc)
        second_seen_at = datetime(2026, 7, 1, 10, 35, tzinfo=dt_timezone.utc)
        article = self._article(
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
            translation_status=ArticleTranslationStatus.PENDING,
            translated_title_zh="",
            title_zh="",
            translated_summary_zh="",
            summary_zh="",
            translated_body_zh="",
            body_zh="",
            decision_reason={
                "ranked_revival": {
                    "revived_at": first_revived_at.isoformat(),
                    "action": "translation_retry",
                    "translation_retry_requested_at": first_revived_at.isoformat(),
                }
            },
        )
        article.ranked_revived_at = first_revived_at
        article.save(update_fields=["ranked_revived_at", "decision_reason", "updated_at"])

        result = revive_article_after_ranked_source_elevation(article, now=second_seen_at)

        article.refresh_from_db()
        self.assertFalse(result.revived)
        self.assertEqual(result.action, "already_retrying_translation")
        self.assertEqual(article.ranked_revived_at, first_revived_at)
        self.assertEqual(
            article.decision_reason["ranked_revival"]["translation_retry_requested_at"],
            first_revived_at.isoformat(),
        )


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, AUTOMATION_ENABLED=True, REWRITE_PROVIDER="fallback")
class AutomationFlowTests(TestCase):
    def _translated_article(self, **overrides):
        body_ja = (
            "大阪杯G1（芝2000メートル）はクロワデュノールが1着。北村友一騎手が騎乗し、直線で抜け出した。"
            "道中は中団で脚をため、最後の直線では力強く伸びて後続を振り切った。"
            "管理する斉藤崇史調教師は状態の良さを評価し、今後の大舞台にも期待を寄せている。"
            "勝ち時計は1分57秒台で、良馬場のなか内容の濃い結果となった。"
        )
        body_zh = (
            "大阪杯G1（草地2000米）由北十字星取得第1名。北村友一骑手策骑，直线冲出。"
            "比赛中段保持在中团蓄力，进入最后直线后强势加速，最终甩开后续马群。"
            "练马师斉藤崇史评价其状态良好，也对接下来的大舞台寄予期待。"
            "胜利时间为1分57秒区间，在良好场地下是一场内容扎实的胜利。"
        )
        defaults = {
            "source_site": SourceSite.NETKEIBA,
            "source_mode": SourceMode.LATEST,
            "source_article_id": "auto-1",
            "title_ja": "大阪杯G1 クロワデュノールが優勝",
            "translated_title_zh": "大阪杯G1 北十字星夺冠",
            "title_zh": "大阪杯G1 北十字星夺冠",
            "body_ja_raw": body_ja,
            "body_ja_normalized": body_ja,
            "translated_body_zh": body_zh,
            "translated_summary_zh": "北十字星赢下大阪杯G1。",
            "summary_zh": "北十字星赢下大阪杯G1。",
            "body_zh": body_zh,
            "published_at": timezone.now(),
            "source_url": "https://example.com/auto-1",
            "workflow_status": WorkflowStatus.PENDING_EDIT,
            "translation_status": ArticleTranslationStatus.TRANSLATED,
        }
        defaults.update(overrides)
        return NewsArticle.objects.create(**defaults)

    def test_process_article_automation_marks_high_value_article_publish_ready(self):
        TermEntry.objects.create(term_type="horse", source_ja="クロワデュノール", target_zh="北十字星", priority=100)
        article = self._translated_article()

        result = process_article_automation_task.run(article.id)

        article.refresh_from_db()
        self.assertEqual(result["review_mode"], ReviewMode.AUTO)
        self.assertEqual(article.automation_status, AutomationStatus.PUBLISH_READY)
        self.assertEqual(article.review_mode, ReviewMode.AUTO)
        self.assertGreaterEqual(article.score_total, 75)
        self.assertFalse(article.rewrite_body_zh)
        self.assertEqual(article.base_translation_zh, article.translated_body_zh)
        self.assertEqual(article.decision_reason["gate_issue_counts"]["blocker"], 0)

    def test_takarazuka_article_uses_title_horse_and_race_grade(self):
        TermEntry.objects.create(term_type="horse", source_ja="キタサンブラック", target_zh="北部玄驹", priority=100)
        TermEntry.objects.create(term_type="race", source_ja="宝塚記念", target_zh="宝塚纪念", race_grade="G1", priority=90)
        body = (
            "シュガークンが宝塚記念・GIで一発を狙う。兄キタサンブラックの悔しさを晴らす舞台だ。"
            "ドゥラメンテ、シュガーハート、サクラバクシンオーなど血統面の話題も多い。"
            "最終追い切りでは軽快な動きを見せ、陣営は状態の良さを強調した。"
            "今年の上半期を締めくくる大一番としてファンの注目も集まっている。"
        )
        article = self._translated_article(
            source_article_id="takarazuka-3961-shape",
            title_ja="【宝塚記念】兄キタサンブラックの悔しさを晴らすか シュガークンが一発狙う",
            translated_title_zh="【宝塚纪念】弟弟シュガークン能否为兄长北部玄驹雪耻",
            title_zh="【宝塚纪念】弟弟シュガークン能否为兄长北部玄驹雪耻",
            body_ja_raw=body,
            body_ja_normalized=body,
            translated_body_zh="シュガークン将挑战宝塚纪念，北部玄驹相关背景受到关注。" * 20,
            body_zh="シュガークン将挑战宝塚纪念，北部玄驹相关背景受到关注。" * 20,
        )

        decision = score_article_for_automation(article)

        self.assertGreaterEqual(decision.score_total, 75)
        self.assertEqual(decision.review_mode, ReviewMode.AUTO)
        self.assertEqual(decision.decision_reason["signals"]["race_grade"], "G1")
        self.assertEqual(decision.decision_reason["signals"]["race_priority"], "P0")
        self.assertTrue(decision.decision_reason["signals"]["p0_horse_hits"])

    def test_automation_scoring_uses_terms_for_article_source_language_only(self):
        from stable.services.automation import race_priority

        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="International Star",
            target_zh="国际之星",
            priority=100,
        )
        TermEntry.objects.create(
            term_type="race",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Derby",
            target_zh="德比",
            race_grade="G1",
            priority=100,
        )
        japanese_article = self._translated_article(
            source_article_id="ja-language-term-isolation",
            title_ja="Derby preview for International Star",
            translated_title_zh="Derby preview for International Star",
            body_ja_raw="Derby preview for International Star.",
            body_ja_normalized="Derby preview for International Star.",
            translated_body_zh="Derby preview for International Star.",
        )
        english_article = self._translated_article(
            source_article_id="en-language-term-isolation",
            source_language=SourceLanguage.ENGLISH,
            title_ja="Derby preview for International Star",
            translated_title_zh="Derby preview for International Star",
            body_ja_raw="Derby preview for International Star.",
            body_ja_normalized="Derby preview for International Star.",
            translated_body_zh="Derby preview for International Star.",
        )

        japanese_decision = score_article_for_automation(japanese_article)
        english_decision = score_article_for_automation(english_article)

        self.assertEqual(race_priority(japanese_article)["priority"], "P2")
        self.assertEqual(race_priority(english_article)["priority"], "P0")
        self.assertEqual(japanese_decision.decision_reason["signals"]["p0_horse_hits"], [])
        self.assertTrue(english_decision.decision_reason["signals"]["p0_horse_hits"])

    def test_automation_p0_horse_hits_match_english_terms_case_insensitively(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            priority=100,
        )
        article = self._translated_article(
            source_article_id="english-uppercase-p0-horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="EQUINOX returns in top form",
            body_ja_raw="EQUINOX returns in a G1 preview. The champion will feature at Ascot.",
            body_ja_normalized="EQUINOX returns in a G1 preview. The champion will feature at Ascot.",
            translated_title_zh="春秋分回归",
            title_zh="春秋分回归",
            translated_body_zh="春秋分将在一级赛前瞻中回归。" * 12,
            body_zh="春秋分将在一级赛前瞻中回归。" * 12,
        )

        decision = score_article_for_automation(article)

        self.assertEqual(decision.decision_reason["signals"]["p0_horse_hits"][0]["target_zh"], "春秋分")

    def test_english_automation_scoring_uses_english_racing_keywords(self):
        article = self._translated_article(
            source_article_id="english-keyword-score",
            source_language=SourceLanguage.ENGLISH,
            title_ja="Breeders' Cup Classic preview: entries and draw confirmed",
            translated_title_zh="育马者杯经典赛前瞻",
            body_ja_raw=(
                "Breeders' Cup Classic preview with entries, draw and barrier updates. "
                "Connections confirmed one runner was withdrawn after an injury. "
            )
            * 8,
            body_ja_normalized=(
                "Breeders' Cup Classic preview with entries, draw and barrier updates. "
                "Connections confirmed one runner was withdrawn after an injury. "
            )
            * 8,
            translated_body_zh="育马者杯经典赛前瞻，报名、排位和伤退消息受到关注。" * 20,
            body_zh="育马者杯经典赛前瞻，报名、排位和伤退消息受到关注。" * 20,
        )

        decision = score_article_for_automation(article)

        self.assertEqual(decision.content_category, ContentCategory.PREVIEW)
        self.assertEqual(decision.decision_reason["signals"]["race_priority"], "P0")
        self.assertIn("withdrawn", decision.decision_reason["signals"]["high_focus_hits"])
        self.assertIn("entries", decision.decision_reason["signals"]["high_focus_hits"])

    def test_high_value_source_overrides_score_stage_only(self):
        article = self._translated_article(
            source_article_id="access-source-1",
            source_mode=SourceMode.ACCESS,
            title_ja="アクセスランキングの一般ニュース",
            body_ja_raw="レース前の短い展望記事です。" * 20,
            body_ja_normalized="レース前の短い展望記事です。" * 20,
            translated_body_zh="访问量榜新闻的中文正文。" * 20,
            body_zh="访问量榜新闻的中文正文。" * 20,
        )

        decision = score_article_for_automation(article)

        self.assertEqual(decision.review_mode, ReviewMode.AUTO)
        self.assertGreaterEqual(decision.score_total, 75)
        self.assertTrue(decision.decision_reason["signals"]["high_value_source"])
        self.assertTrue(decision.decision_reason["scores"]["high_value_source_override"])

    def test_non_horse_fixed_phrases_are_not_unknown_horse_names(self):
        TermEntry.objects.create(
            term_type="fixed_phrase",
            source_ja="タイトル",
            target_zh="头衔",
            notes="non_horse_common_word: 测试普通词",
        )
        TermEntry.objects.create(
            term_type="fixed_phrase",
            source_ja="オッズ",
            target_zh="赔率",
            notes="non_horse_common_word: 测试普通词",
        )

        names = extract_unknown_horse_names(
            "【函館記念】マジックサンズがタイトル狙う",
            "3番人気マジックサンズのオッズが注目され、アラタは2つ目のタイトルを狙う。",
        )

        self.assertIn("マジックサンズ", names)
        self.assertNotIn("タイトル", names)
        self.assertNotIn("オッズ", names)

    def test_warning_issues_do_not_block_publish_ready(self):
        article = self._translated_article(
            source_article_id="warning-not-blocking",
            title_ja="【函館記念】マジックサンズがタイトルを狙う",
            translated_title_zh="函馆纪念热门马冲击头衔",
            title_zh="函馆纪念热门马冲击头衔",
            body_ja_raw="マジックサンズは函館記念で24日の追い切り後に2000メートルへ向かう。" * 8,
            body_ja_normalized="マジックサンズは函館記念で24日の追い切り後に2000メートルへ向かう。" * 8,
            translated_body_zh="这匹热门马将向函馆纪念发起挑战，阵营称状态良好。" * 8,
            body_zh="这匹热门马将向函馆纪念发起挑战，阵营称状态良好。" * 8,
        )

        outcome = validate_rewrite(article)
        apply_validation_outcome(article, outcome)

        article.refresh_from_db()
        self.assertTrue(outcome.passed)
        self.assertEqual(article.automation_status, AutomationStatus.PUBLISH_READY)
        self.assertTrue(any(issue["code"] == "unknown_horse_not_preserved" for issue in article.gate_issues))
        self.assertTrue(any(issue["severity"] == "warning" for issue in article.gate_issues))

    def test_external_horse_missing_warns_without_known_term_blocker_and_keeps_all_ids(self):
        for horse_id in ["1001", "1002"]:
            ExternalHorseAlias.objects.create(
                source="netkeiba",
                external_horse_id=horse_id,
                name_ja="マヤノライジン",
                normalized_name="マヤノライジン",
                alias_source="test",
            )
        article = self._translated_article(
            source_article_id="external-horse-warning",
            title_ja="マヤノライジンが出走",
            body_ja_raw="マヤノライジンは重賞へ向かう。" * 10,
            body_ja_normalized="マヤノライジンは重賞へ向かう。" * 10,
            translated_title_zh="摩耶雷神出战",
            title_zh="摩耶雷神出战",
            translated_body_zh="这匹马将向重赏进发。" * 10,
            body_zh="这匹马将向重赏进发。" * 10,
        )

        outcome = validate_rewrite(article)

        external_issue = next(issue for issue in outcome.issues if issue["code"] == "external_horse_not_preserved")
        self.assertTrue(outcome.passed)
        self.assertEqual(external_issue["severity"], "warning")
        self.assertCountEqual(external_issue["payload"]["names"][0]["external_horse_ids"], ["1001", "1002"])
        self.assertFalse(any(issue["code"] in {"core_term_missing", "background_term_missing"} for issue in outcome.issues))

    def test_validation_uses_matched_external_horse_spelling_for_english_article(self):
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH001",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            alias_source="test",
        )
        article = self._translated_article(
            source_article_id="english-external-horse-preserved",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            title_ja="LUCKY STAR wins at Sha Tin",
            body_ja_raw="LUCKY STAR was too strong in the closing stages. " * 8,
            body_ja_normalized="LUCKY STAR was too strong in the closing stages. " * 8,
            translated_title_zh="LUCKY STAR 在沙田取胜",
            title_zh="LUCKY STAR 在沙田取胜",
            translated_body_zh="LUCKY STAR 在末段表现强劲。" * 12,
            body_zh="LUCKY STAR 在末段表现强劲。" * 12,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(outcome.passed)
        self.assertEqual(outcome.details["external_horse_names"], ["LUCKY STAR"])
        self.assertFalse(any(issue["code"] == "external_horse_not_preserved" for issue in outcome.issues))

    def test_validation_preserve_limit_is_not_consumed_by_known_horse_terms(self):
        known_names = [
            "アカホース",
            "アオホース",
            "クロホース",
            "シロホース",
            "キンホース",
            "ギンホース",
            "ミドリホース",
            "サクラホース",
            "モモホース",
            "ユキホース",
            "ソラホース",
            "ナミホース",
        ]
        for index, name in enumerate(known_names):
            TermEntry.objects.create(term_type="horse", source_ja=name, target_zh=f"译名{index}", priority=100)
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="4001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        source_body = " ".join(known_names) + " マヤノライジンは重賞へ向かう。" + "調整は順調。" * 12
        translated_known = " ".join(f"译名{index}" for index in range(len(known_names)))
        article = self._translated_article(
            source_article_id="external-horse-after-known-terms",
            title_ja="重賞展望",
            body_ja_raw=source_body,
            body_ja_normalized=source_body,
            translated_title_zh="重赏展望",
            title_zh="重赏展望",
            translated_body_zh=translated_known + " 这匹马将向重赏进发。" * 10,
            body_zh=translated_known + " 这匹马将向重赏进发。" * 10,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(any(issue["code"] == "external_horse_not_preserved" for issue in outcome.issues))

    def test_core_term_missing_blocks_and_background_term_missing_warns(self):
        TermEntry.objects.create(term_type="race", source_ja="有馬記念", target_zh="有马纪念", priority=90)
        core_article = self._translated_article(
            source_article_id="core-term-missing",
            title_ja="有馬記念の登録馬が発表",
            translated_title_zh="重要赛事报名马公布",
            title_zh="重要赛事报名马公布",
            translated_body_zh="重要赛事报名马公布，阵容受到关注。" * 10,
            body_zh="重要赛事报名马公布，阵容受到关注。" * 10,
        )

        core_outcome = validate_rewrite(core_article)
        apply_validation_outcome(core_article, core_outcome)

        core_article.refresh_from_db()
        self.assertFalse(core_outcome.passed)
        self.assertEqual(core_article.workflow_status, WorkflowStatus.PENDING_REVIEW)
        self.assertTrue(any(issue["code"] == "core_term_missing" for issue in core_article.gate_issues))

        TermEntry.objects.create(term_type="race", source_ja="金鯱賞", target_zh="金鯱赏", priority=10)
        background_body = "前半は陣営の調整過程を詳しく紹介する。" * 40 + "金鯱賞での好走歴にも触れた。"
        background_article = self._translated_article(
            source_article_id="background-term-warning",
            title_ja="夏競馬へ向けた調整進む",
            body_ja_raw=background_body,
            body_ja_normalized=background_body,
            translated_body_zh="前半介绍阵营调整过程，最后概括过往表现。" * 12,
            body_zh="前半介绍阵营调整过程，最后概括过往表现。" * 12,
        )

        background_outcome = validate_rewrite(background_article)
        apply_validation_outcome(background_article, background_outcome)

        background_article.refresh_from_db()
        self.assertTrue(background_outcome.passed)
        self.assertEqual(background_article.automation_status, AutomationStatus.PUBLISH_READY)
        self.assertTrue(any(issue["code"] == "background_term_missing" for issue in background_article.gate_issues))

    def test_english_core_term_missing_detects_source_case_insensitively(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            priority=90,
        )
        article = self._translated_article(
            source_article_id="english-core-term-uppercase-missing",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="EQUINOX returns in feature",
            body_ja_raw="EQUINOX returns in feature company at Ascot.",
            body_ja_normalized="EQUINOX returns in feature company at Ascot.",
            translated_title_zh="名马回归",
            title_zh="名马回归",
            translated_body_zh="这匹名马将在阿斯科特回归。" * 12,
            body_zh="这匹名马将在阿斯科特回归。" * 12,
        )

        outcome = validate_rewrite(article)

        self.assertFalse(outcome.passed)
        self.assertTrue(any(issue["code"] == "core_term_missing" for issue in outcome.issues))

    @override_settings(MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS=["class", "content", "agent"])
    def test_english_short_core_entity_not_in_ambiguity_config_still_blocks(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="Cody",
            target_zh="科迪",
            priority=100,
        )
        article = self._translated_article(
            source_article_id="english-short-core-entity-still-blocks",
            source_site=SourceSite.TDN,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="Cody returns in stakes company",
            body_ja_raw="Cody returns in stakes company after a sharp workout at Saratoga. " * 6,
            body_ja_normalized="Cody returns in stakes company after a sharp workout at Saratoga. " * 6,
            translated_title_zh="美国让赛马匹复出",
            title_zh="美国让赛马匹复出",
            translated_body_zh="这是一篇美国赛事新闻，介绍一匹马训练后复出。" * 12,
            body_zh="这是一篇美国赛事新闻，介绍一匹马训练后复出。" * 12,
        )

        outcome = validate_rewrite(article)

        self.assertFalse(outcome.passed)
        blockers = [issue for issue in outcome.issues if issue["code"] == "core_term_missing"]
        self.assertEqual([issue["payload"]["source_ja"] for issue in blockers], ["Cody"])
        self.assertFalse(any(issue["code"] == "ambiguous_term_downgraded" for issue in outcome.issues))

    @override_settings(MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS=["class", "content", "agent"])
    def test_english_high_ambiguity_common_word_is_downgraded_from_blocker(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            source_ja="Class",
            target_zh="高班",
            priority=100,
        )
        article = self._translated_article(
            source_article_id="english-ambiguous-class-downgraded",
            source_site=SourceSite.HKJC_NEWS,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            title_ja="Class 3 handicap preview at Sha Tin",
            body_ja_raw="Class 3 handicap runners are ready at Sha Tin. The preview focuses on barrier draws and pace. " * 5,
            body_ja_normalized="Class 3 handicap runners are ready at Sha Tin. The preview focuses on barrier draws and pace. " * 5,
            translated_title_zh="沙田三班让赛前瞻",
            title_zh="沙田三班让赛前瞻",
            translated_body_zh="这是一篇沙田赛事前瞻，重点分析档位和步速。" * 12,
            body_zh="这是一篇沙田赛事前瞻，重点分析档位和步速。" * 12,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(outcome.passed)
        self.assertFalse(any(issue["code"] == "core_term_missing" for issue in outcome.issues))
        downgraded = [issue for issue in outcome.issues if issue["code"] == "ambiguous_term_downgraded"]
        self.assertTrue(downgraded)
        self.assertIn(downgraded[0]["severity"], {"warning", "info"})
        self.assertEqual(downgraded[0]["payload"]["source_ja"], "Class")
        self.assertIn("high_ambiguity", downgraded[0]["payload"]["reason"])

    @override_settings(MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS=[])
    def test_english_common_word_context_downgrades_review_seed_terms(self):
        for source_ja, target_zh in [
            ("Contact", "接触"),
            ("Number", "号码"),
            ("Live", "直播"),
            ("Were", "曾经"),
            ("AGENDA", "议程"),
            ("Tuesday", "战神日"),
        ]:
            TermEntry.objects.create(
                term_type="horse",
                source_language=SourceLanguage.ENGLISH,
                racing_region=RacingRegion.UNITED_KINGDOM,
                source_ja=source_ja,
                target_zh=target_zh,
                priority=100,
            )
        article = self._translated_article(
            source_article_id="english-common-word-context-downgrade",
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            title_ja="Agenda for Tuesday racing coverage",
            body_ja_raw=(
                "Contact the racecourse office for the live stream number. "
                "The races were moved after the going changed. "
                "The agenda also includes odds updates and stable news. "
            )
            * 5,
            body_ja_normalized=(
                "Contact the racecourse office for the live stream number. "
                "The races were moved after the going changed. "
                "The agenda also includes odds updates and stable news. "
            )
            * 5,
            translated_title_zh="周二赛马报道日程",
            title_zh="周二赛马报道日程",
            translated_body_zh="报道日程包括视频信号、赔率更新和马房消息。" * 12,
            body_zh="报道日程包括视频信号、赔率更新和马房消息。" * 12,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(outcome.passed)
        self.assertFalse(any(issue["code"] == "core_term_missing" for issue in outcome.issues))
        downgraded = [issue for issue in outcome.issues if issue["code"] == "english_term_common_word_downgraded"]
        self.assertEqual({issue["payload"]["source_ja"] for issue in downgraded}, {"Contact", "Number", "Live", "Were", "AGENDA", "Tuesday"})
        for issue in downgraded:
            self.assertIn(issue["severity"], {"warning", "info"})
            self.assertEqual(issue["payload"]["term_semantic_classification"], "common_word")
            self.assertGreaterEqual(issue["payload"]["confidence"], 0.8)
            self.assertTrue(issue["payload"]["classification_reason"])
            self.assertTrue(issue["payload"]["matched_context"])

    @override_settings(MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS=[])
    def test_english_common_seed_with_race_marker_defaults_to_common_word_without_entity_context(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="Classic",
            target_zh="经典名驹",
            priority=100,
        )
        article = self._translated_article(
            source_article_id="english-classic-common-seed-default",
            source_site=SourceSite.HORSE_RACING_NATION,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="Classic racing coverage continues this weekend",
            body_ja_raw="Classic racing coverage continues this weekend with broadcast updates and analysis. " * 8,
            body_ja_normalized="Classic racing coverage continues this weekend with broadcast updates and analysis. " * 8,
            translated_title_zh="周末赛马报道继续",
            title_zh="周末赛马报道继续",
            translated_body_zh="本周末继续提供赛马报道、转播更新和分析。" * 12,
            body_zh="本周末继续提供赛马报道、转播更新和分析。" * 12,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(outcome.passed)
        self.assertFalse(any(issue["code"] == "core_term_missing" for issue in outcome.issues))
        downgraded = [issue for issue in outcome.issues if issue["code"] == "english_term_common_word_downgraded"]
        self.assertEqual(len(downgraded), 1)
        self.assertEqual(downgraded[0]["payload"]["source_ja"], "Classic")
        self.assertEqual(downgraded[0]["payload"]["term_semantic_classification"], "common_word")
        self.assertEqual(downgraded[0]["payload"]["classification_reason"], "ordinary_english_seed_default")

    @override_settings(MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS=[])
    def test_english_common_word_weak_racing_title_context_still_downgrades(self):
        for source_ja, target_zh in [
            ("Contact", "常联系"),
            ("Live", "直播"),
        ]:
            TermEntry.objects.create(
                term_type="horse",
                source_language=SourceLanguage.ENGLISH,
                racing_region=RacingRegion.UNITED_KINGDOM,
                source_ja=source_ja,
                target_zh=target_zh,
                priority=100,
            )
        article = self._translated_article(
            source_article_id="english-common-weak-racing-title-context",
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            title_ja="Contact and live updates from York",
            body_ja_raw=(
                "Live stable updates and contact details are available before the meeting. "
                "The racecourse office number was also updated for visitors. "
            )
            * 8,
            body_ja_normalized=(
                "Live stable updates and contact details are available before the meeting. "
                "The racecourse office number was also updated for visitors. "
            )
            * 8,
            translated_title_zh="约克赛前实时资讯",
            title_zh="约克赛前实时资讯",
            translated_body_zh="赛前提供实时马房动态、联系方式和访客信息。" * 12,
            body_zh="赛前提供实时马房动态、联系方式和访客信息。" * 12,
        )

        outcome = validate_rewrite(article)

        self.assertTrue(outcome.passed)
        self.assertFalse(any(issue["code"] == "core_term_missing" for issue in outcome.issues))
        downgraded = [issue for issue in outcome.issues if issue["code"] == "english_term_common_word_downgraded"]
        self.assertEqual({issue["payload"]["source_ja"] for issue in downgraded}, {"Contact", "Live"})
        self.assertEqual({issue["payload"]["term_semantic_classification"] for issue in downgraded}, {"common_word"})

    @override_settings(MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS=[])
    def test_english_common_word_seeds_stay_blocked_in_entity_context(self):
        for source_ja, target_zh in [
            ("Contact", "常联系"),
            ("Live", "直播"),
            ("Action", "大有作为"),
        ]:
            TermEntry.objects.create(
                term_type="horse",
                source_language=SourceLanguage.ENGLISH,
                racing_region=RacingRegion.UNITED_KINGDOM,
                source_ja=source_ja,
                target_zh=target_zh,
                priority=100,
            )
        article = self._translated_article(
            source_article_id="english-common-seed-entity-context-blocks",
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            title_ja="Contact wins at York as Live returns after trial",
            body_ja_raw=(
                "Contact wins at York after a strong finish. "
                "Live returns after trial work, while Action will target the Derby next month. "
            )
            * 6,
            body_ja_normalized=(
                "Contact wins at York after a strong finish. "
                "Live returns after trial work, while Action will target the Derby next month. "
            )
            * 6,
            translated_title_zh="英国赛驹在约克取胜",
            title_zh="英国赛驹在约克取胜",
            translated_body_zh="英国赛驹在约克取胜，另一匹赛驹试闸后复出。" * 12,
            body_zh="英国赛驹在约克取胜，另一匹赛驹试闸后复出。" * 12,
        )

        outcome = validate_rewrite(article)

        blockers = [issue for issue in outcome.issues if issue["code"] == "core_term_missing"]
        self.assertFalse(outcome.passed)
        self.assertEqual({issue["payload"]["source_ja"] for issue in blockers}, {"Contact", "Live", "Action"})
        self.assertFalse(any(issue["code"] == "english_term_common_word_downgraded" for issue in outcome.issues))
        for issue in blockers:
            self.assertEqual(issue["payload"]["term_semantic_classification"], "uncertain")
            self.assertIn(
                issue["payload"]["classification_reason"],
                {"common_seed_entity_context", "common_seed_context_uncertain"},
            )

    @override_settings(MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS=[])
    def test_english_proper_race_terms_still_block_with_semantic_payload(self):
        for source_ja, target_zh, region in [
            ("Belmont Stakes", "贝蒙锦标", RacingRegion.UNITED_STATES),
            ("Kentucky Derby", "肯塔基打吡", RacingRegion.UNITED_STATES),
        ]:
            TermEntry.objects.create(
                term_type="race",
                source_language=SourceLanguage.ENGLISH,
                racing_region=region,
                source_ja=source_ja,
                target_zh=target_zh,
                race_grade="G1",
                priority=100,
            )
        article = self._translated_article(
            source_article_id="english-proper-race-term-still-blocks",
            source_site=SourceSite.HORSE_RACING_NATION,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="Belmont Stakes winner points to Kentucky Derby",
            body_ja_raw="Belmont Stakes winner is being prepared for a Kentucky Derby campaign. " * 8,
            body_ja_normalized="Belmont Stakes winner is being prepared for a Kentucky Derby campaign. " * 8,
            translated_title_zh="美国冠军马备战大赛",
            title_zh="美国冠军马备战大赛",
            translated_body_zh="这匹美国冠军马正准备下一场重要赛事。" * 12,
            body_zh="这匹美国冠军马正准备下一场重要赛事。" * 12,
        )

        outcome = validate_rewrite(article)

        blockers = [issue for issue in outcome.issues if issue["code"] == "core_term_missing"]
        self.assertFalse(outcome.passed)
        self.assertEqual({issue["payload"]["source_ja"] for issue in blockers}, {"Belmont Stakes", "Kentucky Derby"})
        self.assertFalse(any(issue["code"] == "english_term_common_word_downgraded" for issue in outcome.issues))
        for issue in blockers:
            self.assertEqual(issue["payload"]["term_semantic_classification"], "proper_noun")
            self.assertTrue(issue["payload"]["classification_reason"])

    @override_settings(MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS=[])
    def test_english_dual_use_terms_remain_blocked_in_strong_entity_context(self):
        for source_ja, target_zh in [
            ("Tuesday", "战神日"),
            ("GOOD JOB", "极速雕神"),
            ("Fast Track", "捷径快途"),
        ]:
            TermEntry.objects.create(
                term_type="horse",
                source_language=SourceLanguage.ENGLISH,
                racing_region=RacingRegion.UNITED_KINGDOM,
                source_ja=source_ja,
                target_zh=target_zh,
                priority=100,
            )
        article = self._translated_article(
            source_article_id="english-dual-use-strong-entity-context-blocks",
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            title_ja="Tuesday wins as GOOD JOB returns and Fast Track entered",
            body_ja_raw="Tuesday wins after a strong finish. GOOD JOB returns from a break and Fast Track entered the next race. " * 8,
            body_ja_normalized="Tuesday wins after a strong finish. GOOD JOB returns from a break and Fast Track entered the next race. " * 8,
            translated_title_zh="两匹马前往约克",
            title_zh="两匹马前往约克",
            translated_body_zh="两匹马在最新试闸后前往约克。" * 12,
            body_zh="两匹马在最新试闸后前往约克。" * 12,
        )

        outcome = validate_rewrite(article)

        blockers = [issue for issue in outcome.issues if issue["code"] == "core_term_missing"]
        self.assertFalse(outcome.passed)
        self.assertEqual({issue["payload"]["source_ja"] for issue in blockers}, {"Tuesday", "GOOD JOB", "Fast Track"})
        for issue in blockers:
            self.assertEqual(issue["payload"]["term_semantic_classification"], "uncertain")
            self.assertTrue(issue["payload"]["classification_reason"])

    @override_settings(MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS=["google play", "トレセン"])
    def test_confirmed_non_terms_are_ignored_by_publish_gate(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="Google Play",
            target_zh="谷歌商店",
            priority=100,
        )
        english_article = self._translated_article(
            source_article_id="english-non-term-ignored",
            source_site=SourceSite.TDN,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="Google Play links appear in the racing app article",
            body_ja_raw="Google Play links appear in this article footer while the racing news continues. " * 8,
            body_ja_normalized="Google Play links appear in this article footer while the racing news continues. " * 8,
            translated_title_zh="应用页链接出现在赛马新闻中",
            title_zh="应用页链接出现在赛马新闻中",
            translated_body_zh="这是一篇赛马新闻，页脚含有应用下载链接。" * 12,
            body_zh="这是一篇赛马新闻，页脚含有应用下载链接。" * 12,
        )

        english_outcome = validate_rewrite(english_article)

        self.assertTrue(english_outcome.passed)
        self.assertFalse(any(issue["code"] == "core_term_missing" for issue in english_outcome.issues))
        self.assertTrue(any(issue["code"] == "non_term_gate_ignored" for issue in english_outcome.issues))

        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="トレセン",
            target_zh="训练中心",
            priority=100,
        )
        japanese_article = self._translated_article(
            source_article_id="japanese-non-term-ignored",
            title_ja="トレセンニュース 調整順調",
            body_ja_raw="トレセンニュースとして各馬の調整過程を紹介する。" * 8,
            body_ja_normalized="トレセンニュースとして各馬の調整過程を紹介する。" * 8,
            translated_title_zh="训练新闻 调整顺利",
            title_zh="训练新闻 调整顺利",
            translated_body_zh="这是一篇介绍各马调整过程的新闻。" * 12,
            body_zh="这是一篇介绍各马调整过程的新闻。" * 12,
        )

        japanese_outcome = validate_rewrite(japanese_article)

        self.assertTrue(japanese_outcome.passed)
        self.assertFalse(any(issue["code"] == "core_term_missing" for issue in japanese_outcome.issues))
        self.assertTrue(any(issue["code"] == "non_term_gate_ignored" for issue in japanese_outcome.issues))

    @override_settings(MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS=["lane"])
    def test_ignored_alias_does_not_bypass_gate_for_another_matched_source_term(self):
        entry = TermEntry.objects.create(
            term_type=TermType.RACE,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Royal Ascot",
            target_zh="皇家雅士谷赛马周",
            priority=100,
        )
        TermAlias.objects.create(
            term=entry,
            source_language=SourceLanguage.ENGLISH,
            text="Lane",
            alias_type=TermAliasType.ALIAS,
            is_active=True,
        )
        article = self._translated_article(
            source_article_id="english-ignore-alias-isolation",
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            title_ja="Royal Ascot entries announced",
            body_ja_raw="Royal Ascot entries were announced for the feature race. " * 8,
            body_ja_normalized="Royal Ascot entries were announced for the feature race. " * 8,
            translated_title_zh="重要赛事报名名单公布",
            title_zh="重要赛事报名名单公布",
            translated_body_zh="重要赛事报名名单已经公布，参赛阵容受到关注。" * 12,
            body_zh="重要赛事报名名单已经公布，参赛阵容受到关注。" * 12,
        )

        outcome = validate_rewrite(article)

        self.assertFalse(outcome.passed)
        self.assertTrue(any(issue["code"] == "core_term_missing" for issue in outcome.issues))
        self.assertFalse(any(issue["code"] == "non_term_gate_ignored" for issue in outcome.issues))

    def test_english_term_gate_ignores_other_region_terms_but_keeps_global_terms(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            source_ja="LINK",
            target_zh="连捷",
            priority=100,
        )
        TermEntry.objects.create(
            term_type="race",
            source_language=SourceLanguage.ENGLISH,
            racing_region="",
            source_ja="Breeders' Cup",
            target_zh="育马者杯",
            race_grade="G1",
            priority=100,
        )
        article = self._translated_article(
            source_article_id="english-region-filter-global-term",
            source_site=SourceSite.TDN,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="Breeders' Cup preview includes a LINK to entries",
            body_ja_raw="Breeders' Cup preview includes a LINK to the entries page and a full field analysis. " * 6,
            body_ja_normalized="Breeders' Cup preview includes a LINK to the entries page and a full field analysis. " * 6,
            translated_title_zh="美国大赛前瞻",
            title_zh="美国大赛前瞻",
            translated_body_zh="这是一篇美国大赛前瞻，提到报名和阵容分析。" * 12,
            body_zh="这是一篇美国大赛前瞻，提到报名和阵容分析。" * 12,
        )

        outcome = validate_rewrite(article)

        blockers = [issue for issue in outcome.issues if issue["code"] == "core_term_missing"]
        self.assertFalse(outcome.passed)
        self.assertEqual([issue["payload"]["source_ja"] for issue in blockers], ["Breeders' Cup"])
        excluded = outcome.details.get("term_gate_region_excluded_terms", [])
        self.assertEqual(excluded[0]["source_ja"], "LINK")
        self.assertEqual(excluded[0]["term_region"], RacingRegion.HONG_KONG)
        self.assertEqual(excluded[0]["article_region"], RacingRegion.UNITED_STATES)
        self.assertNotIn("term_semantic_classification", excluded[0])
        self.assertFalse(any(issue["code"] == "english_term_common_word_downgraded" for issue in outcome.issues))

    def test_english_same_region_core_term_still_blocks_auto_publish(self):
        TermEntry.objects.create(
            term_type="race",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            source_ja="Breeders' Cup Classic",
            target_zh="育马者杯经典赛",
            race_grade="G1",
            priority=100,
        )
        article = self._translated_article(
            source_article_id="english-same-region-core-term-blocks",
            source_site=SourceSite.TDN,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_STATES,
            title_ja="Breeders' Cup Classic entries confirmed",
            body_ja_raw="Breeders' Cup Classic entries confirmed after the latest round of workouts. " * 8,
            body_ja_normalized="Breeders' Cup Classic entries confirmed after the latest round of workouts. " * 8,
            translated_title_zh="美国大赛报名确认",
            title_zh="美国大赛报名确认",
            translated_body_zh="这是一篇美国大赛报名新闻，介绍最新训练后的阵容。" * 12,
            body_zh="这是一篇美国大赛报名新闻，介绍最新训练后的阵容。" * 12,
        )

        outcome = validate_rewrite(article)
        apply_validation_outcome(article, outcome)

        article.refresh_from_db()
        self.assertFalse(outcome.passed)
        self.assertEqual(article.automation_status, AutomationStatus.MANUAL_REVIEW_REQUIRED)
        self.assertEqual(article.workflow_status, WorkflowStatus.PENDING_REVIEW)
        self.assertTrue(any(issue["payload"].get("source_ja") == "Breeders' Cup Classic" for issue in article.gate_issues))

    @override_settings(MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS=3)
    def test_reprocess_term_gate_blocked_articles_only_rechecks_latest_lookback_window(self):
        recent = self._translated_article(
            source_article_id="term-gate-reprocess-recent",
            source_site=SourceSite.HKJC_NEWS,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            gate_issues=[{"code": "core_term_missing", "severity": "blocker", "payload": {"source_ja": "Class"}}],
            first_seen_at=timezone.now() - timedelta(hours=2),
        )
        stale = self._translated_article(
            source_article_id="term-gate-reprocess-stale",
            source_site=SourceSite.HKJC_NEWS,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            gate_issues=[{"code": "core_term_missing", "severity": "blocker", "payload": {"source_ja": "Class"}}],
            first_seen_at=timezone.now() - timedelta(hours=6),
        )
        rejected = self._translated_article(
            source_article_id="term-gate-reprocess-rejected",
            source_site=SourceSite.HKJC_NEWS,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            workflow_status=WorkflowStatus.REJECTED,
            gate_issues=[{"code": "core_term_missing", "severity": "blocker", "payload": {"source_ja": "Class"}}],
            first_seen_at=timezone.now() - timedelta(hours=1),
        )
        out = StringIO()

        call_command(
            "reprocess_term_gate_blocked_articles",
            "--region",
            RacingRegion.HONG_KONG,
            "--dry-run",
            "--json",
            stdout=out,
        )

        payload = json.loads(out.getvalue())
        recent.refresh_from_db()
        stale.refresh_from_db()
        rejected.refresh_from_db()
        self.assertEqual(payload["candidate_ids"], [recent.id])
        self.assertEqual(payload["summary"]["candidate_count"], 1)
        self.assertIn(RacingRegion.HONG_KONG, payload["summary_by_region"])
        self.assertEqual(payload["summary_by_region"][RacingRegion.HONG_KONG]["candidate_count"], 1)
        self.assertEqual(payload["outside_lookback_count"], 1)
        self.assertNotIn("outside_lookback", payload["skipped"])
        self.assertIn(rejected.id, payload["skipped"]["manual_terminal_state"])
        self.assertEqual(recent.automation_status, AutomationStatus.MANUAL_REVIEW_REQUIRED)

    @override_settings(MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS=[])
    def test_reprocess_term_gate_blocked_articles_reports_common_word_downgrades_and_region_summary(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_ja="Contact",
            target_zh="接触",
            priority=100,
        )
        article = self._translated_article(
            source_article_id="term-gate-reprocess-common-word-summary",
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.UNITED_KINGDOM,
            title_ja="Contact details updated for racegoers",
            body_ja_raw="Contact details and the office number were updated before the meeting. " * 8,
            body_ja_normalized="Contact details and the office number were updated before the meeting. " * 8,
            translated_title_zh="观众联系方式更新",
            title_zh="观众联系方式更新",
            translated_body_zh="赛前更新了观众联系方式和办公室电话。" * 12,
            body_zh="赛前更新了观众联系方式和办公室电话。" * 12,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            gate_issues=[{"code": "core_term_missing", "severity": "blocker", "payload": {"source_ja": "Contact"}}],
            first_seen_at=timezone.now() - timedelta(hours=1),
        )
        out = StringIO()

        call_command(
            "reprocess_term_gate_blocked_articles",
            "--region",
            RacingRegion.UNITED_KINGDOM,
            "--dry-run",
            "--json",
            stdout=out,
        )

        payload = json.loads(out.getvalue())
        article.refresh_from_db()
        self.assertEqual(payload["candidate_ids"], [article.id])
        self.assertEqual(payload["revalidated_to_publish_ready_ids"], [article.id])
        self.assertEqual(payload["summary"]["common_word_downgraded_count"], 1)
        self.assertEqual(payload["summary"]["proper_term_blocker_count"], 0)
        self.assertEqual(payload["summary_by_region"][RacingRegion.UNITED_KINGDOM]["revalidated_to_publish_ready_count"], 1)
        outcome = payload["outcomes"][0]
        self.assertEqual(outcome["english_term_classifications"][0]["source_ja"], "Contact")
        self.assertEqual(outcome["english_term_classifications"][0]["term_semantic_classification"], "common_word")
        self.assertEqual(article.automation_status, AutomationStatus.MANUAL_REVIEW_REQUIRED)

    @override_settings(MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS=["class"])
    def test_reprocess_term_gate_blocked_articles_commit_revalidates_without_direct_publish(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            source_ja="Class",
            target_zh="高班",
            priority=100,
        )
        article = self._translated_article(
            source_article_id="term-gate-reprocess-commit",
            source_site=SourceSite.HKJC_NEWS,
            source_language=SourceLanguage.ENGLISH,
            racing_region=RacingRegion.HONG_KONG,
            title_ja="Class 3 handicap preview at Sha Tin",
            body_ja_raw="Class 3 handicap runners are ready at Sha Tin. The preview focuses on barrier draws and pace. " * 5,
            body_ja_normalized="Class 3 handicap runners are ready at Sha Tin. The preview focuses on barrier draws and pace. " * 5,
            translated_title_zh="沙田三班让赛前瞻",
            title_zh="沙田三班让赛前瞻",
            translated_body_zh="这是一篇沙田赛事前瞻，重点分析档位和步速。" * 12,
            body_zh="这是一篇沙田赛事前瞻，重点分析档位和步速。" * 12,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            gate_issues=[{"code": "core_term_missing", "severity": "blocker", "payload": {"source_ja": "Class"}}],
            first_seen_at=timezone.now() - timedelta(hours=1),
        )
        out = StringIO()

        call_command(
            "reprocess_term_gate_blocked_articles",
            "--region",
            RacingRegion.HONG_KONG,
            "--dry-run",
            "--json",
            stdout=out,
        )
        dry_run = json.loads(out.getvalue())
        out = StringIO()
        call_command(
            "reprocess_term_gate_blocked_articles",
            "--commit",
            "--run-id",
            str(dry_run["run_id"]),
            "--manifest-sha256",
            dry_run["manifest_sha256"],
            "--json",
            stdout=out,
        )

        payload = json.loads(out.getvalue())
        article.refresh_from_db()
        self.assertEqual(payload["restored_candidate_ids"], [article.id])
        self.assertEqual(article.automation_status, AutomationStatus.PUBLISH_READY)
        self.assertNotEqual(article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertIsNotNone(article.ranked_revived_at)

    def test_duplicate_detection_blocks_highly_similar_article(self):
        published = self._translated_article(
            source_article_id="published-duplicate-source",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )
        article = self._translated_article(source_article_id="duplicate-candidate")

        outcome = validate_rewrite(article)
        apply_validation_outcome(article, outcome)

        article.refresh_from_db()
        self.assertFalse(outcome.passed)
        self.assertEqual(article.workflow_status, WorkflowStatus.DUPLICATE)
        self.assertEqual(article.duplicate_of, published)
        self.assertTrue(any(issue["code"] == "duplicate_content" for issue in article.gate_issues))

    def test_passing_validation_clears_stale_duplicate_state_and_can_publish(self):
        stale_duplicate = self._translated_article(source_article_id="stale-duplicate-reference")
        article = self._translated_article(source_article_id="stale-duplicate-now-clean")
        article.workflow_status = WorkflowStatus.DUPLICATE
        article.duplicate_of = stale_duplicate
        article.duplicate_score = 0.91
        article.duplicate_reason = "旧重复检测结果"
        article.save(
            update_fields=[
                "workflow_status",
                "duplicate_of",
                "duplicate_score",
                "duplicate_reason",
                "updated_at",
            ]
        )

        outcome = validate_rewrite(article)
        apply_validation_outcome(article, outcome)
        publish_result = auto_publish_batch_task.run(limit=1)

        article.refresh_from_db()
        self.assertTrue(outcome.passed)
        self.assertEqual(article.duplicate_of, None)
        self.assertEqual(article.duplicate_score, None)
        self.assertEqual(article.duplicate_reason, "")
        self.assertEqual(publish_result["published_count"], 1)
        self.assertEqual(article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(article.automation_status, AutomationStatus.AUTO_PUBLISHED)

    def test_score_short_body_is_ignored(self):
        article = self._translated_article(
            source_article_id="short-1",
            title_ja="短い記事",
            body_ja_raw="短文",
            body_ja_normalized="短文",
            translated_body_zh="短文",
            body_zh="短文",
        )

        score_article_task.run(article.id)

        article.refresh_from_db()
        self.assertEqual(article.review_mode, ReviewMode.IGNORED)
        self.assertEqual(article.workflow_status, WorkflowStatus.IGNORED)
        self.assertEqual(article.automation_status, AutomationStatus.IGNORED)

    def test_auto_publish_batch_only_publishes_ready_articles(self):
        TermEntry.objects.create(term_type="horse", source_ja="クロワデュノール", target_zh="北十字星", priority=100)
        article = self._translated_article()
        process_article_automation_task.run(article.id)

        result = auto_publish_batch_task.run(limit=3)

        article.refresh_from_db()
        self.assertEqual(result["published_count"], 1)
        self.assertEqual(article.workflow_status, WorkflowStatus.PUBLISHED)
        self.assertEqual(article.automation_status, AutomationStatus.AUTO_PUBLISHED)
        self.assertEqual(article.published_by_mode, "auto")
        self.assertIsNotNone(article.auto_publish_at)

    @override_settings(
        AUTO_PUBLISH_BATCH_LIMIT=4,
        AUTO_PUBLISH_PEAK_BATCH_LIMIT=10,
        AUTO_PUBLISH_PEAK_DAY_OF_WEEK=6,
        AUTO_PUBLISH_PEAK_START_HOUR=13,
        AUTO_PUBLISH_PEAK_END_HOUR=16,
    )
    def test_auto_publish_limit_uses_sunday_peak_window(self):
        sunday_peak = datetime(2026, 5, 17, 5, 30, tzinfo=dt_timezone.utc)
        sunday_window_end = datetime(2026, 5, 17, 8, 0, tzinfo=dt_timezone.utc)
        monday_same_hour = datetime(2026, 5, 18, 5, 30, tzinfo=dt_timezone.utc)

        self.assertEqual(_resolve_auto_publish_batch_limit(now=sunday_peak), 10)
        self.assertEqual(_resolve_auto_publish_batch_limit(now=sunday_window_end), 4)
        self.assertEqual(_resolve_auto_publish_batch_limit(now=monday_same_hour), 4)
        self.assertEqual(_resolve_auto_publish_batch_limit(limit=2, now=sunday_peak), 2)
        self.assertEqual(_resolve_auto_publish_batch_limit(limit=0, now=sunday_peak), 0)

    def test_public_page_prefers_rewrite_when_not_manually_edited(self):
        article = self._translated_article(
            source_article_id="rewrite-public",
            rewrite_title_zh="改写后的中文标题",
            rewrite_summary_zh="改写后的摘要",
            rewrite_body_zh="改写后的正文内容。",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        response = self.client.get(article.public_path)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "改写后的中文标题")
        self.assertContains(response, "改写后的正文内容。")

    def test_notification_without_email_config_is_logged_as_skipped(self):
        send_notification_task.run("rewrite_failed", {"article_id": 123, "title": "测试稿"})

        log = NotificationLog.objects.get(channel="email")
        self.assertEqual(log.status, "skipped")
        self.assertEqual(log.channel, "email")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        AUTOMATION_WARNING_EMAIL_ENABLED=True,
        AUTOMATION_WARNING_NOTIFY_EMAILS=["754652181@qq.com"],
        HIGH_VALUE_SOURCE_RULES=["netkeiba:access"],
    )
    def test_high_value_warning_sends_deduplicated_email(self):
        article = self._translated_article(
            source_article_id="warning-email",
            source_mode=SourceMode.ACCESS,
            title_ja="【函館記念】マジックサンズが挑む",
            translated_title_zh="函馆纪念热门马挑战",
            title_zh="函馆纪念热门马挑战",
            body_ja_raw="マジックサンズは函館記念で上位を狙う。" * 10,
            body_ja_normalized="マジックサンズは函館記念で上位を狙う。" * 10,
            translated_body_zh="热门马将挑战函馆纪念，阵营状态良好。" * 10,
            body_zh="热门马将挑战函馆纪念，阵营状态良好。" * 10,
        )

        process_article_automation_task.run(article.id)
        article.refresh_from_db()
        send_high_value_warning_notification(article)

        sent = NotificationLog.objects.filter(type="high_value_warning", status="sent").count()
        skipped = NotificationLog.objects.filter(type="high_value_warning", status="skipped").count()
        self.assertEqual(sent, 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(article.automation_status, AutomationStatus.PUBLISH_READY)

    @override_settings(AUTOMATION_WARNING_EMAIL_ENABLED=True, AUTOMATION_WARNING_NOTIFY_EMAILS=[])
    def test_high_value_warning_missing_recipient_is_skipped(self):
        article = self._translated_article(source_article_id="warning-email-skipped", score_total=100)
        article.gate_issues = [
            {
                "code": "numbers_omitted",
                "severity": "warning",
                "message": "发布稿省略较多原文数字",
                "route": "auto",
                "payload": {},
            }
        ]
        article.save(update_fields=["gate_issues", "score_total", "updated_at"])

        logs = send_high_value_warning_notification(article)

        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].status, "skipped")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class TermConsoleTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser("admin", "admin@example.com", "admin123456")
        self.client.login(username="admin", password="admin123456")
        self.term = TermEntry.objects.create(
            term_type="horse",
            source_ja="イクイノックス",
            target_zh="春秋分",
            translation_status="translated",
            aliases_ja=["イクイノ"],
            aliases_zh=["春秋分马"],
            priority=100,
            is_active=True,
        )

    def test_term_list_page_available(self):
        response = self.client.get(reverse("console-term-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "术语映射")
        self.assertContains(response, "イクイノックス")

    def test_term_list_filters_and_labels_pending_horse_translation(self):
        pending = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Forever Young",
            target_zh="",
            translation_status="pending",
            racing_region=RacingRegion.UNITED_STATES,
        )

        response = self.client.get(reverse("console-term-list"), {"translation_status": "pending"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, pending.source_ja)
        self.assertContains(response, "中文名待补")
        self.assertNotContains(response, self.term.source_ja)

    def test_term_api_exposes_translation_status(self):
        self.term.translation_status = "translated"
        self.term.save(update_fields=["translation_status", "updated_at"])

        response = self.client.get(reverse("api-term-detail", args=[self.term.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["translation_status"], "translated")
        self.assertTrue(payload["has_translation"])

    def test_term_list_can_search_japanese_and_chinese_aliases(self):
        response = self.client.get(reverse("console-term-list"), {"q": "イクイノ"})
        self.assertContains(response, "イクイノックス")
        response = self.client.get(reverse("console-term-list"), {"q": "春秋分马"})
        self.assertContains(response, "イクイノックス")

    def test_term_list_pagination_preserves_source_language_filter(self):
        for index in range(21):
            TermEntry.objects.create(
                term_type="horse",
                source_language=SourceLanguage.ENGLISH,
                source_ja=f"English Horse {index:02d}",
                target_zh=f"英文马{index:02d}",
            )

        response = self.client.get(reverse("console-term-list"), {"source_language": SourceLanguage.ENGLISH})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "source_language=en&amp;page=2")

    def test_term_create_page_can_create_entry(self):
        response = self.client.post(
            reverse("console-term-create"),
            {
                "term_type": "race",
                "source_ja": "大阪杯",
                "target_zh": "大阪杯",
                "aliases_ja_text": "大阪杯GI\n大阪杯ＧＩ",
                "aliases_zh_text": "大阪杯一级赛",
                "priority": "50",
                "is_active": "on",
                "notes": "重要赛事",
                "intent": "save",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(TermEntry.objects.filter(term_type="race", source_ja="大阪杯").exists())

    def test_term_create_duplicate_rejected(self):
        response = self.client.post(
            reverse("console-term-create"),
            {
                "term_type": "horse",
                "source_ja": "イクイノックス",
                "target_zh": "春秋分",
                "aliases_ja_text": "",
                "aliases_zh_text": "",
                "priority": "10",
                "is_active": "on",
                "notes": "",
                "intent": "save",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已有术语 ID")

    def test_english_term_create_duplicate_rejected_case_insensitively(self):
        TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
        )

        response = self.client.post(
            reverse("console-term-create"),
            {
                "term_type": "horse",
                "source_language": SourceLanguage.ENGLISH,
                "source_ja": "EQUINOX",
                "target_zh": "另一个春秋分",
                "aliases_ja_text": "",
                "aliases_zh_text": "",
                "priority": "10",
                "is_active": "on",
                "notes": "",
                "intent": "save",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已有术语 ID")
        self.assertEqual(
            TermEntry.objects.filter(term_type="horse", source_language=SourceLanguage.ENGLISH, source_ja__iexact="equinox").count(),
            1,
        )

    def test_term_toggle_active(self):
        TermAlias.objects.create(
            term=self.term,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.ALIAS,
            is_active=True,
        )
        response = self.client.post(reverse("console-term-toggle", args=[self.term.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.term.refresh_from_db()
        self.assertFalse(self.term.is_active)
        self.assertFalse(TermAlias.objects.get(term=self.term, text="Equinox").is_active)

    def test_preview_term_import_service(self):
        csv_text = (
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade\n"
            "horse,グランアレグリア,放声欢呼,Gran Alegria|グラン,放声欢呼,100,true,,\n"
            "race,大阪杯,大阪杯,,大阪杯一级赛,20,true,重要赛事,G1\n"
        )
        preview = preview_term_import(csv_text=csv_text, import_mode="create")
        self.assertEqual(preview["summary"]["total"], 2)
        self.assertEqual(preview["summary"]["error_count"], 0)
        self.assertTrue(preview["can_commit"])
        self.assertEqual(preview["rows"][1]["payload"]["race_grade"], "G1")

    def test_preview_term_import_rejects_invalid_race_grade(self):
        csv_text = (
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade\n"
            "race,謎の特別,谜之特别,,,,true,,P9\n"
        )
        preview = preview_term_import(csv_text=csv_text, import_mode="create")
        self.assertEqual(preview["summary"]["error_count"], 1)
        self.assertIn("比赛等级", " ".join(preview["rows"][0]["errors"]))

    def test_preview_term_import_service_decodes_gb18030_file(self):
        TermEntry.objects.all().delete()
        csv_text = (
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes\n"
            "horse,\u30a4\u30af\u30a4\u30ce\u30c3\u30af\u30b9,\u6625\u79cb\u5206,Equinox|\u30a4\u30af\u30a4,\u6625\u79cb\u5206,100,true,\n"
        )
        upload = SimpleUploadedFile("terms_gb18030.csv", csv_text.encode("gb18030"), content_type="text/csv")
        preview = preview_term_import(csv_file=upload, import_mode="create")
        self.assertEqual(preview["summary"]["error_count"], 0)
        self.assertEqual(preview["detected_encoding"], "gb18030")
        self.assertEqual(preview["rows"][0]["payload"]["source_ja"], "\u30a4\u30af\u30a4\u30ce\u30c3\u30af\u30b9")
        self.assertEqual(preview["rows"][0]["payload"]["target_zh"], "\u6625\u79cb\u5206")

    def test_preview_term_import_service_decodes_cp932_file(self):
        TermEntry.objects.all().delete()
        csv_text = (
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes\n"
            "horse,\u30a4\u30af\u30a4\u30ce\u30c3\u30af\u30b9,\u6625\u79cb\u5206,Equinox|\u30a4\u30af\u30a4,\u6625\u79cb\u5206,100,true,\n"
        )
        upload = SimpleUploadedFile("terms_cp932.csv", csv_text.encode("cp932"), content_type="text/csv")
        preview = preview_term_import(csv_file=upload, import_mode="create")
        self.assertEqual(preview["summary"]["error_count"], 0)
        self.assertIn(preview["detected_encoding"], {"cp932", "shift_jis", "gb18030"})
        self.assertEqual(preview["rows"][0]["payload"]["source_ja"], "\u30a4\u30af\u30a4\u30ce\u30c3\u30af\u30b9")
        self.assertEqual(preview["rows"][0]["payload"]["target_zh"], "\u6625\u79cb\u5206")

    def test_term_import_preview_and_commit(self):
        csv_text = (
            "term_type,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade\n"
            "horse,グランアレグリア,放声欢呼,Gran Alegria|グラン,放声欢呼,100,true,,\n"
            "race,大阪杯,大阪杯,,大阪杯一级赛,20,true,重要赛事,G1\n"
        )
        preview_response = self.client.post(
            reverse("console-term-import"),
            {"import_mode": "create", "csv_text": csv_text, "action": "preview"},
            follow=True,
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertContains(preview_response, "预检结果")
        commit_response = self.client.post(
            reverse("console-term-import"),
            {"action": "commit"},
            follow=True,
        )
        self.assertEqual(commit_response.status_code, 200)
        self.assertTrue(TermEntry.objects.filter(source_ja="グランアレグリア").exists())
        self.assertEqual(TermEntry.objects.get(source_ja="大阪杯").race_grade, "G1")

    def test_term_import_upsert_alias_match_preserves_concept_primary_source(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
            aliases_ja=["イクイ"],
            priority=100,
            is_active=True,
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.PRIMARY,
            is_active=True,
        )
        preview_rows = [
            {
                "line_no": 1,
                "status": "update",
                "payload": {
                    "term_type": "horse",
                    "source_language": SourceLanguage.ENGLISH,
                    "source_ja": "Equinox",
                    "target_zh": "春秋分",
                    "aliases_ja": ["EQUINOX"],
                    "aliases_zh": ["春秋分马"],
                    "race_grade": "",
                    "priority": 80,
                    "is_active": True,
                    "notes": "英文别名",
                },
            }
        ]

        result = commit_term_import(preview_rows, import_mode="upsert")

        self.assertEqual(result["update_count"], 1)
        term.refresh_from_db()
        self.assertEqual(term.source_language, SourceLanguage.JAPANESE)
        self.assertEqual(term.source_ja, "イクイノックス")
        self.assertEqual(term.aliases_ja, ["イクイ"])
        self.assertEqual(term.target_zh, "春秋分")
        self.assertEqual(term.aliases_zh, ["春秋分马"])
        self.assertEqual(term.priority, 80)
        self.assertTrue(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="Equinox",
                alias_type=TermAliasType.PRIMARY,
            ).exists()
        )
        self.assertFalse(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="EQUINOX",
                alias_type=TermAliasType.ALIAS,
            ).exists()
        )

    def test_term_import_upsert_same_language_case_variant_updates_primary_source(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="旧译名",
            aliases_ja=["Old Alias"],
            priority=10,
            is_active=True,
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.PRIMARY,
            is_active=True,
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Old Alias",
            alias_type=TermAliasType.ALIAS,
            is_active=True,
        )
        preview_rows = [
            {
                "line_no": 1,
                "status": "update",
                "payload": {
                    "term_type": "horse",
                    "source_language": SourceLanguage.ENGLISH,
                    "source_ja": "EQUINOX",
                    "target_zh": "春秋分",
                    "aliases_ja": ["Fresh Alias", "equinox"],
                    "aliases_zh": ["春秋分马"],
                    "race_grade": "",
                    "priority": 90,
                    "is_active": True,
                    "notes": "英文主原文大小写更新",
                },
            }
        ]

        result = commit_term_import(preview_rows, import_mode="upsert")

        self.assertEqual(result["update_count"], 1)
        term.refresh_from_db()
        self.assertEqual(term.source_language, SourceLanguage.ENGLISH)
        self.assertEqual(term.source_ja, "EQUINOX")
        self.assertEqual(term.target_zh, "春秋分")
        self.assertEqual(term.aliases_ja, ["Fresh Alias", "equinox"])
        self.assertEqual(term.aliases_zh, ["春秋分马"])
        self.assertEqual(term.priority, 90)
        self.assertEqual(term.notes, "英文主原文大小写更新")
        self.assertTrue(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="EQUINOX",
                alias_type=TermAliasType.PRIMARY,
            ).exists()
        )
        self.assertTrue(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="Fresh Alias",
                alias_type=TermAliasType.ALIAS,
            ).exists()
        )
        self.assertFalse(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="Equinox",
            ).exists()
        )
        self.assertFalse(
            TermAlias.objects.filter(
                term=term,
                source_language=SourceLanguage.ENGLISH,
                text="equinox",
            ).exists()
        )
        self.assertEqual(TermAlias.objects.filter(term=term, source_language=SourceLanguage.ENGLISH).count(), 2)

    def test_term_import_upsert_rejects_alias_conflict_with_other_term(self):
        existing = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            is_active=True,
        )
        TermAlias.objects.create(
            term=existing,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.PRIMARY,
            is_active=True,
        )
        csv_text = (
            "term_type,source_language,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade\n"
            "horse,en,Different Horse,另一匹马,EQUINOX,,10,true,,\n"
        )

        preview = preview_term_import(csv_text=csv_text, import_mode="upsert")

        self.assertEqual(preview["summary"]["error_count"], 1)
        self.assertFalse(preview["can_commit"])
        self.assertIn(f"术语 ID：{existing.pk}", " ".join(preview["rows"][0]["errors"]))
        self.assertFalse(TermEntry.objects.filter(source_ja="Different Horse").exists())

    def test_term_import_commit_rechecks_alias_conflict_with_other_term(self):
        existing = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            is_active=True,
        )
        TermAlias.objects.create(
            term=existing,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.PRIMARY,
            is_active=True,
        )
        preview_rows = [
            {
                "line_no": 2,
                "status": "create",
                "payload": {
                    "term_type": "horse",
                    "source_language": SourceLanguage.ENGLISH,
                    "source_ja": "Different Horse",
                    "target_zh": "另一匹马",
                    "aliases_ja": ["EQUINOX"],
                    "aliases_zh": [],
                    "race_grade": "",
                    "priority": 10,
                    "is_active": True,
                    "notes": "",
                },
            }
        ]

        result = commit_term_import(preview_rows, import_mode="upsert")

        self.assertEqual(result["skipped_count"], 1)
        self.assertIn(f"术语 ID：{existing.pk}", " ".join(result["failed_rows"][0]["errors"]))
        self.assertFalse(TermEntry.objects.filter(source_ja="Different Horse").exists())

    def test_import_terms_management_command_supports_dry_run(self):
        out = StringIO()
        call_command("import_terms", "--dry-run", stdout=out)
        self.assertIn("预检", out.getvalue())
        self.assertFalse(TermEntry.objects.filter(source_ja="キタサンブラック").exists())

    def test_term_api_create_and_toggle(self):
        create_response = self.client.post(
            reverse("api-term-create"),
            data='{"term_type":"org","source_language":"en","source_ja":"JRA","target_zh":"日本中央竞马会","aliases_ja":["jra","Japan Racing Association"],"aliases_zh":["JRA"],"priority":5,"is_active":true,"notes":""}',
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 200)
        payload = create_response.json()
        term_id = payload["term"]["id"]
        self.assertEqual(payload["term"]["source_language"], SourceLanguage.ENGLISH)
        self.assertTrue(
            TermAlias.objects.filter(
                term_id=term_id,
                source_language=SourceLanguage.ENGLISH,
                text="JRA",
                alias_type=TermAliasType.PRIMARY,
                is_active=True,
            ).exists()
        )
        self.assertTrue(
            TermAlias.objects.filter(
                term_id=term_id,
                source_language=SourceLanguage.ENGLISH,
                text="Japan Racing Association",
                alias_type=TermAliasType.ALIAS,
                is_active=True,
            ).exists()
        )
        self.assertFalse(TermAlias.objects.filter(term_id=term_id, text="jra").exists())
        toggle_response = self.client.post(reverse("api-term-toggle-active", args=[term_id]))
        self.assertEqual(toggle_response.status_code, 200)
        self.assertFalse(TermEntry.objects.get(pk=term_id).is_active)
        self.assertFalse(TermAlias.objects.filter(term_id=term_id, is_active=True).exists())

    def test_term_api_update_syncs_source_aliases_case_insensitively(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.ENGLISH,
            source_ja="Equinox",
            target_zh="春秋分",
            aliases_ja=["Old Alias"],
            is_active=True,
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Old Alias",
            alias_type=TermAliasType.ALIAS,
            is_active=True,
        )

        response = self.client.post(
            reverse("api-term-update", args=[term.id]),
            data='{"term_type":"horse","source_language":"en","source_ja":"EQUINOX","target_zh":"春秋分","aliases_ja":["equinox","Fresh Alias"],"aliases_zh":[],"priority":5,"is_active":true,"notes":""}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        term.refresh_from_db()
        self.assertEqual(term.aliases_ja, ["Fresh Alias"])
        self.assertTrue(TermAlias.objects.filter(term=term, text="EQUINOX", alias_type=TermAliasType.PRIMARY).exists())
        self.assertTrue(TermAlias.objects.filter(term=term, text="Fresh Alias", alias_type=TermAliasType.ALIAS).exists())
        self.assertFalse(TermAlias.objects.filter(term=term, text="Old Alias").exists())


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class TranslationWorkflowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser("admin", "admin@example.com", "admin123456")
        self.client.login(username="admin", password="admin123456")
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="translation-1",
            title_ja="原文标题",
            body_ja_raw="原文正文",
            body_ja_normalized="原文正文",
            published_at=timezone.now(),
            source_url="https://example.com/translation-1",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

    def test_translate_task_updates_status_and_preserves_manual_fields(self):
        self.article.title_zh = "人工标题"
        self.article.mark_manual_edits(["title_zh"])
        self.article.save()

        fake_result = type(
            "Result",
            (),
            {
                "title_zh": "机器标题",
                "body_zh": "机器正文",
                "push_summary_zh": "机器摘要",
                "metadata": {"provider": "openai-compatible", "model": "gpt-4.1-mini"},
            },
        )()

        with patch("stable.tasks.translate_article", return_value=fake_result):
            translate_article_task.run(self.article.id)

        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_status, ArticleTranslationStatus.TRANSLATED)
        self.assertEqual(self.article.translation_model, "gpt-4.1-mini")
        self.assertEqual(self.article.translation_provider, "openai-compatible")
        self.assertEqual(self.article.translated_title_zh, "机器标题")
        self.assertEqual(self.article.body_zh, "机器正文")
        self.assertEqual(self.article.summary_zh, "机器摘要")
        self.assertEqual(self.article.push_summary_zh, "机器摘要")
        self.assertEqual(self.article.title_zh, "人工标题")
        self.assertEqual(self.article.workflow_status, WorkflowStatus.PENDING_EDIT)

    def test_translate_task_marks_failure(self):
        with patch("stable.tasks.translate_article", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                translate_article_task.run(self.article.id)

        self.article.refresh_from_db()
        self.assertEqual(self.article.translation_status, ArticleTranslationStatus.FAILED)
        self.assertIn("boom", self.article.translation_error_message)
        self.assertEqual(self.article.workflow_status, WorkflowStatus.TRANSLATION_FAILED)

    def test_translation_status_api_exposes_latest_state(self):
        self.article.translation_status = ArticleTranslationStatus.FAILED
        self.article.translation_error_message = "bad gateway"
        self.article.translation_model = "gpt-4.1-mini"
        self.article.save()

        response = self.client.get(reverse("api-article-translation-status", args=[self.article.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["translation_status"], ArticleTranslationStatus.FAILED)
        self.assertEqual(payload["translation_model"], "gpt-4.1-mini")
        self.assertEqual(payload["translation_error_message"], "bad gateway")

    def test_batch_translate_task_processes_pending_articles(self):
        second_article = NewsArticle.objects.create(
            source_site=SourceSite.JRA,
            source_mode=SourceMode.OFFICIAL,
            source_article_id="translation-2",
            title_ja="第二条原文",
            body_ja_raw="第二条正文",
            body_ja_normalized="第二条正文",
            published_at=timezone.now(),
            source_url="https://example.com/translation-2",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        fake_result = type(
            "Result",
            (),
            {
                "title_zh": "批量标题",
                "body_zh": "批量正文",
                "push_summary_zh": "批量摘要",
                "metadata": {"provider": "openai-compatible", "model": "gpt-4.1-mini"},
            },
        )()

        with patch("stable.tasks.translate_article", return_value=fake_result):
            result = batch_translate_articles_task.run(limit=10)

        self.article.refresh_from_db()
        second_article.refresh_from_db()
        self.assertEqual(result["translated_count"], 2)
        self.assertEqual(self.article.translation_status, ArticleTranslationStatus.TRANSLATED)
        self.assertEqual(second_article.translation_status, ArticleTranslationStatus.TRANSLATED)

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=2)
    def test_provider_retries_when_translation_looks_incomplete(self):
        self.article.body_ja_raw = (
            "樱花赏将在阪神赛马场举行。"
            + "前情介绍。" * 40
            + "\n■第五名 2022年 星映天下。"
            + "\n■第四名 2019年 放声欢呼。"
            + "\n■第三名 2024年 橡木城。"
            + "\n■第二名 2023年 自由岛。"
            + "\n■第一名 2021年 纯净之辉。"
        )
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")

        def fake_response(payload):
            usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 123, "prompt_tokens": 456}})()
            choice = type(
                "Choice",
                (),
                {
                    "message": type("Message", (), {"content": __import__("json").dumps(payload, ensure_ascii=False)})(),
                    "finish_reason": "stop",
                },
            )()
            return type("Response", (), {"choices": [choice], "usage": usage})()

        incomplete = fake_response(
            {
                "title_zh": "樱花赏历届冠军用时排行",
                "body_zh": (
                    "樱花赏将在阪神赛马场举行，本文回顾历届最快夺冠时间。"
                    "\n■第五名 2022年 星映天下。"
                    "\n■第四名 2019年 放声欢呼。"
                    "\n■第三名 2024年 橡木城。"
                    "\n■第二名 2023年 自由岛。"
                    "\n■第一名 2021年 纯净之辉"
                ),
                "push_summary_zh": "樱花赏速度榜回顾。",
            }
        )
        complete = fake_response(
            {
                "title_zh": "樱花赏历届冠军用时排行",
                "body_zh": (
                    "樱花赏将在阪神赛马场举行，本文回顾历届最快夺冠时间。"
                    "\n■第五名 2022年 星映天下。"
                    "\n■第四名 2019年 放声欢呼。"
                    "\n■第三名 2024年 橡木城。"
                    "\n■第二名 2023年 自由岛。"
                    "\n■第一名 2021年 纯净之辉。"
                ),
                "push_summary_zh": "樱花赏速度榜回顾。",
            }
        )

        with patch.object(provider, "_request_completion", side_effect=[incomplete, complete]) as mocked:
            result = provider.translate(self.article)

        self.assertEqual(mocked.call_count, 2)
        self.assertTrue(result.body_zh.endswith("。"))
        self.assertEqual(result.metadata["attempt"], 2)
        self.assertEqual(result.metadata["finish_reason"], "stop")

    def test_translation_service_persists_failed_metadata(self):
        self.article.body_ja_raw = "原文第一段。\n原文第二段。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        class BrokenProvider:
            name = "siliconflow"

            def translate(self, article):
                raise TranslationResponseError(
                    "Translation response appears incomplete",
                    metadata={
                        "provider": "siliconflow",
                        "model": "deepseek-ai/DeepSeek-V3",
                        "finish_reason": "stop",
                        "attempt": 2,
                    },
                )

        with patch("stable.services.translation.get_translation_provider", return_value=BrokenProvider()):
            with self.assertRaises(TranslationResponseError):
                run_translation_service(self.article)

        run = self.article.translation_runs.first()
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.raw_response["finish_reason"], "stop")
        self.assertEqual(run.raw_response["attempt"], 2)

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=1)
    def test_provider_uses_title_terms_and_excludes_known_horse_from_unknowns(self):
        TermEntry.objects.create(term_type="horse", source_ja="キタサンブラック", target_zh="北部玄驹", priority=100)
        self.article.title_ja = "【宝塚記念】兄キタサンブラックの悔しさを晴らすか シュガークンが一発狙う"
        self.article.body_ja_raw = "シュガークンがGI宝塚記念に挑む。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 42}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "キタサンブラック的弟弟__UMA_KEEP_1__挑战宝塚纪念",
                                "body_zh": "__UMA_KEEP_1__将向GI宝塚纪念发起挑战。",
                                "push_summary_zh": "__UMA_KEEP_1__挑战宝塚纪念。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()
        response = type("Response", (), {"choices": [choice], "usage": usage})()

        with patch.object(provider, "_request_completion", return_value=response):
            result = provider.translate(self.article)

        self.assertIn("北部玄驹", result.title_zh)
        self.assertIn("キタサンブラック", [term["source_ja"] for term in result.metadata["terms"]])
        self.assertNotIn("キタサンブラック", result.metadata["unknown_horse_names"])
        self.assertIn("シュガークン", result.metadata["unknown_horse_names"])

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=1)
    def test_provider_protects_external_horse_alias_without_chinese_mapping(self):
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        self.article.title_ja = "マヤノライジンが出走"
        self.article.body_ja_raw = "マヤノライジンは重賞へ向かう。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "__UMA_KEEP_1__出战",
                                "body_zh": "__UMA_KEEP_1__将向重赏进发。",
                                "push_summary_zh": "__UMA_KEEP_1__出战。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()

        with patch.object(provider, "_request_completion", return_value=type("Response", (), {"choices": [choice], "usage": usage})()):
            result = provider.translate(self.article)

        self.assertIn("マヤノライジン", result.title_zh)
        self.assertIn("マヤノライジン", result.body_zh)
        self.assertIn("マヤノライジン", result.metadata["external_horse_names"])
        external = [item for item in result.metadata["recognized_horse_names"] if item["source"] == "external_alias"][0]
        self.assertEqual(external["external_horse_ids"], ["1001"])

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=1)
    def test_provider_protects_english_external_horse_alias_with_source_spelling(self):
        ExternalHorseAlias.objects.create(
            source="hkjc",
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            external_horse_id="HKH001",
            name_ja="Lucky Star",
            name_en="Lucky Star",
            normalized_name="Lucky Star",
            alias_source="test",
        )
        self.article.source_site = SourceSite.HKJC_NEWS
        self.article.source_language = SourceLanguage.ENGLISH
        self.article.racing_region = RacingRegion.HONG_KONG
        self.article.title_ja = "LUCKY STAR wins at Sha Tin"
        self.article.body_ja_raw = "LUCKY STAR was too strong in the closing stages."
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "__UMA_KEEP_1__ 在沙田取胜",
                                "body_zh": "__UMA_KEEP_1__ 在末段表现强劲。",
                                "push_summary_zh": "__UMA_KEEP_1__ 取胜。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()

        with patch.object(provider, "_request_completion", return_value=type("Response", (), {"choices": [choice], "usage": usage})()):
            result = provider.translate(self.article)

        self.assertIn("LUCKY STAR", result.title_zh)
        self.assertEqual(result.metadata["unknown_horse_names"], ["LUCKY STAR"])
        self.assertEqual(result.metadata["external_horse_names"], ["LUCKY STAR"])
        self.assertEqual(result.metadata["external_horse_aliases"][0]["name_ja"], "Lucky Star")

    @override_settings(
        TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3",
        TRANSLATION_MAX_ATTEMPTS=1,
        TRANSLATION_UNKNOWN_HORSE_LIMIT=1,
    )
    def test_provider_unknown_limit_is_not_consumed_by_known_horse_terms(self):
        for name in ["アカホース", "アオホース", "クロホース"]:
            TermEntry.objects.create(term_type="horse", source_ja=name, target_zh=f"{name}译名")
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="4001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        self.article.title_ja = "アカホース アオホース クロホース マヤノライジンが出走"
        self.article.body_ja_raw = "マヤノライジンは重賞へ向かう。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "__UMA_KEEP_1__出战",
                                "body_zh": "__UMA_KEEP_1__将向重赏进发。",
                                "push_summary_zh": "__UMA_KEEP_1__出战。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()

        with patch.object(provider, "_request_completion", return_value=type("Response", (), {"choices": [choice], "usage": usage})()):
            result = provider.translate(self.article)

        self.assertEqual(result.metadata["unknown_horse_names"], ["マヤノライジン"])
        self.assertIn("マヤノライジン", result.title_zh)

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=2)
    def test_provider_retries_when_unknown_horse_names_are_translated_away(self):
        self.article.title_ja = "【大阪杯レース後コメント】クロワデュノール北村友一騎手ら"
        self.article.body_ja_raw = (
            "1着 クロワデュノール(北村友一騎手)\n"
            "2着 メイショウタバル(武豊騎手)\n"
            "3着 ダノンデサイル(坂井瑠星騎手)"
        )
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")

        def fake_response(payload):
            usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 88, "prompt_tokens": 144}})()
            choice = type(
                "Choice",
                (),
                {
                    "message": type("Message", (), {"content": __import__("json").dumps(payload, ensure_ascii=False)})(),
                    "finish_reason": "stop",
                },
            )()
            return type("Response", (), {"choices": [choice], "usage": usage})()

        first = fake_response(
            {
                "title_zh": "大阪杯赛后评论 北十字星与骑手",
                "body_zh": "冠军北十字星，亚军名将原野，季军野田分位。",
                "push_summary_zh": "赛后评论。",
            }
        )
        second = fake_response(
            {
                "title_zh": "【大阪杯赛后评论】__UMA_KEEP_1__与北村友一骑手等",
                "body_zh": (
                    "1着 __UMA_KEEP_1__(北村友一骑手)\n"
                    "2着 __UMA_KEEP_2__(武丰骑手)\n"
                    "3着 __UMA_KEEP_3__(坂井瑠星骑手)。"
                ),
                "push_summary_zh": "__UMA_KEEP_1__夺冠，__UMA_KEEP_2__与__UMA_KEEP_3__分列二三位。",
            }
        )

        with patch.object(provider, "_request_completion", side_effect=[first, second]) as mocked:
            result = provider.translate(self.article)

        self.assertEqual(mocked.call_count, 2)
        self.assertIn("クロワデュノール", result.body_zh)
        self.assertIn("メイショウタバル", result.body_zh)
        self.assertIn("ダノンデサイル", result.body_zh)
        self.assertEqual(result.metadata["attempt"], 2)
        self.assertIn("メイショウタバル", result.metadata["unknown_horse_names"])

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=1)
    def test_provider_restores_unknown_horse_placeholders(self):
        self.article.title_ja = "メイショウタバルが出走"
        self.article.body_ja_raw = "1着 メイショウタバル(武豊騎手)。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "__UMA_KEEP_1__出战",
                                "body_zh": "第1名 __UMA_KEEP_1__(武丰骑手)。",
                                "push_summary_zh": "__UMA_KEEP_1__获胜。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()

        with patch.object(provider, "_request_completion", return_value=type("Response", (), {"choices": [choice], "usage": usage})()):
            result = provider.translate(self.article)

        self.assertIn("メイショウタバル", result.title_zh)
        self.assertIn("メイショウタバル", result.body_zh)
        self.assertNotIn("__UMA_KEEP_", result.body_zh)

    @override_settings(TRANSLATION_MODEL="deepseek-ai/DeepSeek-V3", TRANSLATION_MAX_ATTEMPTS=1)
    def test_provider_rejects_when_unknown_horse_still_missing(self):
        self.article.title_ja = "メイショウタバルが出走"
        self.article.body_ja_raw = "1着 メイショウタバル(武豊騎手)。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.save()

        provider = OpenAICompatibleTranslationProvider(api_key="test-key", base_url="https://example.com/v1")
        usage = type("Usage", (), {"model_dump": lambda self: {"completion_tokens": 20}})()
        choice = type(
            "Choice",
            (),
            {
                "message": type(
                    "Message",
                    (),
                    {
                        "content": __import__("json").dumps(
                            {
                                "title_zh": "名将原野出战",
                                "body_zh": "第1名 名将原野(武丰骑手)。",
                                "push_summary_zh": "名将原野获胜。",
                            },
                            ensure_ascii=False,
                        )
                    },
                )(),
                "finish_reason": "stop",
            },
        )()

        with patch.object(provider, "_request_completion", return_value=type("Response", (), {"choices": [choice], "usage": usage})()):
            with self.assertRaisesRegex(TranslationResponseError, "protected entity placeholder"):
                provider.translate(self.article)

    def test_translate_task_preserves_manually_cleared_summary_and_populates_horse_tags(self):
        TermEntry.objects.create(term_type="horse", source_ja="ソダシ", target_zh="纯净之辉", priority=100)
        TermEntry.objects.create(term_type="horse", source_ja="リバティアイランド", target_zh="自由岛", priority=90)
        self.article.title_ja = "ソダシとリバティアイランド"
        self.article.body_ja_raw = "ソダシが勝利し、リバティアイランドも健闘した。"
        self.article.body_ja_normalized = self.article.body_ja_raw
        self.article.summary_zh = ""
        self.article.mark_manual_edits(["summary_zh"])
        self.article.save()

        fake_result = type(
            "Result",
            (),
            {
                "title_zh": "纯净之辉与自由岛",
                "body_zh": "纯净之辉获胜，自由岛也有出色表现。",
                "push_summary_zh": "机器摘要",
                "metadata": {"provider": "siliconflow", "model": "deepseek-ai/DeepSeek-V3"},
            },
        )()

        with patch("stable.tasks.translate_article", return_value=fake_result):
            translate_article_task.run(self.article.id)

        self.article.refresh_from_db()
        self.assertEqual(self.article.summary_zh, "")
        self.assertEqual(self.article.effective_summary, "")
        self.assertCountEqual(self.article.tags_json, ["纯净之辉", "自由岛"])


class CrawlAutoTranslateTests(TestCase):
    @override_settings(AUTO_TRANSLATE_ON_INGEST=True, AUTO_TRANSLATE_SYNC=True)
    def test_new_article_is_translated_immediately_after_ingest(self):
        stub = type("Stub", (), {"source_article_id": "123"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="existing-123",
            title_ja="原文标题",
            body_ja_raw="原文正文",
            body_ja_normalized="原文正文",
            published_at=timezone.now(),
            source_url="https://example.com/news/123",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft", return_value=(article, True)
        ), patch("stable.tasks.translate_article_task.run", return_value={"translated": True}) as mocked_translate:
            result = _crawl_netkeiba_mode("latest", 1)

        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["seen_count"], 0)
        mocked_translate.assert_called_once_with(article.id)

    @override_settings(TERM_DISCOVERY_ENABLED=True, AUTO_TRANSLATE_ON_INGEST=False)
    def test_term_discovery_dispatch_failure_does_not_abort_crawl(self):
        stub = type("Stub", (), {"source_article_id": "789"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="existing-789",
            title_ja="术语发现隔离测试",
            body_ja_raw="正文",
            body_ja_normalized="正文",
            published_at=timezone.now(),
            source_url="https://example.com/news/789",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft", return_value=(article, True)
        ), patch("stable.tasks.dispatch_task", side_effect=RuntimeError("boom")):
            result = _crawl_netkeiba_mode("latest", 1)

        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["seen_count"], 0)

    @override_settings(AUTO_TRANSLATE_ON_INGEST=True, AUTO_TRANSLATE_SYNC=True)
    def test_translation_failure_does_not_abort_crawl(self):
        stub = type("Stub", (), {"source_article_id": "456"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="existing-456",
            title_ja="原文标题2",
            body_ja_raw="原文正文2",
            body_ja_normalized="原文正文2",
            published_at=timezone.now(),
            source_url="https://example.com/news/456",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft", return_value=(article, True)
        ), patch("stable.tasks.translate_article_task.run", side_effect=RuntimeError("boom")) as mocked_translate:
            result = _crawl_netkeiba_mode("latest", 1)

        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["seen_count"], 0)
        mocked_translate.assert_called_once_with(article.id)

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False)
    def test_crawl_success_with_no_new_articles_records_success_summary(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.LATEST)
        stub = type("Stub", (), {"source_article_id": "seen-article"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="seen-article",
            title_ja="既存記事",
            body_ja_raw="本文",
            body_ja_normalized="本文",
            published_at=timezone.now(),
            source_url="https://example.com/news/seen-article",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft", return_value=(article, False)
        ):
            result = _crawl_netkeiba_mode("latest", 1, source=source)

        source.refresh_from_db()
        job = CrawlJob.objects.get(pk=result["crawl_job_id"])
        self.assertEqual(job.status, TaskStatus.SUCCESS)
        self.assertEqual(job.success_count, 0)
        self.assertEqual(job.fail_count, 1)
        self.assertEqual(source.last_crawl_status, TaskStatus.SUCCESS)
        self.assertEqual(source.last_crawl_message, "新增 0，重复 1")

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False, QQ_PUSH_ENABLED=True)
    def test_source_elevated_public_article_dispatches_qq_auto_push(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ACCESS)
        stub = type("Stub", (), {"source_article_id": "seen-ranked-article"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.ACCESS,
            source_article_id="seen-ranked-article",
            title_ja="榜单提升已公开",
            title_zh="榜单提升已公开",
            body_ja_raw="本文",
            body_ja_normalized="本文",
            body_zh="正文",
            published_at=timezone.now(),
            source_url="https://example.com/news/seen-ranked-article",
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft",
            return_value=ArticleUpsertResult(article=article, created=False, source_elevated=True),
        ), patch("stable.tasks.dispatch_task") as mocked_dispatch:
            result = _crawl_netkeiba_mode("access", 1, source=source)

        self.assertEqual(result["new_count"], 0)
        self.assertEqual(result["seen_count"], 1)
        mocked_dispatch.assert_called_once_with(qq_auto_push_article_task, article.id)

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False, QQ_PUSH_ENABLED=True)
    def test_source_elevated_unpublished_article_runs_ranked_revival_without_qq_push(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ACCESS)
        stub = type("Stub", (), {"source_article_id": "seen-ranked-unpublished"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.ACCESS,
            source_article_id="seen-ranked-unpublished",
            title_ja="榜单提升未公开",
            body_ja_raw="本文",
            body_ja_normalized="本文",
            published_at=timezone.now(),
            source_url="https://example.com/news/seen-ranked-unpublished",
            workflow_status=WorkflowStatus.IGNORED,
            automation_status=AutomationStatus.IGNORED,
            review_mode=ReviewMode.IGNORED,
        )

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft",
            return_value=ArticleUpsertResult(article=article, created=False, source_elevated=True),
        ), patch("stable.tasks.revive_article_after_ranked_source_elevation", return_value=Mock(action="rescore")) as mocked_revival, patch(
            "stable.tasks.dispatch_task"
        ) as mocked_dispatch:
            result = _crawl_netkeiba_mode("access", 1, source=source)

        self.assertEqual(result["new_count"], 0)
        self.assertEqual(result["seen_count"], 1)
        mocked_revival.assert_called_once()
        self.assertEqual(mocked_revival.call_args.args[0], article)
        self.assertFalse(any(call_args.args and call_args.args[0] is qq_auto_push_article_task for call_args in mocked_dispatch.call_args_list))

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False, QQ_PUSH_ENABLED=True)
    def test_source_elevated_revival_dispatch_result_is_json_safe(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.NETKEIBA, source_mode=SourceMode.ACCESS)
        stub = type("Stub", (), {"source_article_id": "seen-ranked-json-safe"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.ACCESS,
            source_article_id="seen-ranked-json-safe",
            title_ja="榜单提升 JSON 化",
            body_ja_raw="本文",
            body_ja_normalized="本文",
            published_at=timezone.now(),
            source_url="https://example.com/news/seen-ranked-json-safe",
            workflow_status=WorkflowStatus.IGNORED,
            automation_status=AutomationStatus.IGNORED,
            review_mode=ReviewMode.IGNORED,
        )
        async_result = type("AsyncResult", (), {"id": "ranked-revival-task-1"})()

        with patch("stable.tasks.NetkeibaAdapter.fetch_listing", return_value=[stub]), patch(
            "stable.tasks.NetkeibaAdapter.fetch_detail", return_value=object()
        ), patch("stable.tasks.NetkeibaAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft",
            return_value=ArticleUpsertResult(article=article, created=False, source_elevated=True),
        ), patch("stable.tasks.revive_article_after_ranked_source_elevation", return_value=Mock(action="rescore")), patch(
            "stable.tasks.dispatch_task", return_value=async_result
        ):
            result = _crawl_netkeiba_mode("access", 1, source=source)

        self.assertEqual(
            result["ranked_revival_results"][0]["dispatch_result"],
            {"task_id": "ranked-revival-task-1"},
        )

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False, QQ_PUSH_ENABLED=True)
    def test_international_source_elevated_public_article_dispatches_qq_auto_push(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.ACCESS)
        stub = type("Stub", (), {"source_url": "https://www.skysports.com/racing/news/sky-ranked-article"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_mode=SourceMode.ACCESS,
            source_article_id="sky-ranked-article",
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Sky ranked article",
            title_zh="Sky 榜单文章",
            body_ja_raw="Body",
            body_ja_normalized="Body",
            body_zh="正文",
            published_at=timezone.now(),
            source_url=stub.source_url,
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        class FakeInternationalAdapter:
            def fetch_listing(self, mode, page):
                return [stub]

            def fetch_detail(self, source_url):
                return object()

            def normalize_source_payload(self, stub, detail):
                return object()

        with patch("stable.tasks.INTERNATIONAL_ADAPTERS", {source.adapter_key: FakeInternationalAdapter}), patch(
            "stable.tasks.upsert_article_from_draft",
            return_value=ArticleUpsertResult(article=article, created=False, source_elevated=True),
        ), patch("stable.tasks.dispatch_task") as mocked_dispatch:
            result = _crawl_international_source(source)

        self.assertEqual(result["new_count"], 0)
        self.assertEqual(result["seen_count"], 1)
        mocked_dispatch.assert_called_once_with(qq_auto_push_article_task, article.id)

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False, QQ_PUSH_ENABLED=True)
    def test_international_source_elevated_unpublished_article_runs_ranked_revival_without_qq_push(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.ACCESS)
        stub = type("Stub", (), {"source_url": "https://www.skysports.com/racing/news/sky-ranked-unpublished"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_mode=SourceMode.ACCESS,
            source_article_id="sky-ranked-unpublished",
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Sky ranked unpublished",
            body_ja_raw="Body",
            body_ja_normalized="Body",
            published_at=timezone.now(),
            source_url=stub.source_url,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            review_mode=ReviewMode.MANUAL,
        )

        class FakeInternationalAdapter:
            def fetch_listing(self, mode, page):
                return [stub]

            def fetch_detail(self, source_url):
                return object()

            def normalize_source_payload(self, stub, detail):
                return object()

        with patch("stable.tasks.INTERNATIONAL_ADAPTERS", {source.adapter_key: FakeInternationalAdapter}), patch(
            "stable.tasks.upsert_article_from_draft",
            return_value=ArticleUpsertResult(article=article, created=False, source_elevated=True),
        ), patch("stable.tasks.revive_article_after_ranked_source_elevation", return_value=Mock(action="rescore")) as mocked_revival, patch(
            "stable.tasks.dispatch_task"
        ) as mocked_dispatch:
            result = _crawl_international_source(source)

        self.assertEqual(result["new_count"], 0)
        self.assertEqual(result["seen_count"], 1)
        mocked_revival.assert_called_once()
        self.assertEqual(mocked_revival.call_args.args[0], article)
        self.assertFalse(any(call_args.args and call_args.args[0] is qq_auto_push_article_task for call_args in mocked_dispatch.call_args_list))

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False)
    def test_international_detail_parse_error_skips_article_and_continues(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.ACCESS)
        bad_stub = type("Stub", (), {"source_url": "https://www.skysports.com/racing/news/bad-detail"})()
        good_stub = type("Stub", (), {"source_url": "https://www.skysports.com/racing/news/good-detail"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.SKY_SPORTS_RACING,
            source_mode=SourceMode.ACCESS,
            source_article_id="good-detail",
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_language=SourceLanguage.ENGLISH,
            title_ja="Sky good detail",
            body_ja_raw="Body",
            body_ja_normalized="Body",
            published_at=timezone.now(),
            source_url=good_stub.source_url,
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        class FakeInternationalAdapter:
            def fetch_listing(self, mode, page):
                return [bad_stub, good_stub]

            def fetch_detail(self, source_url):
                if source_url == bad_stub.source_url:
                    raise ValueError("empty detail body")
                return object()

            def normalize_source_payload(self, stub, detail):
                return object()

        with patch("stable.tasks.INTERNATIONAL_ADAPTERS", {source.adapter_key: FakeInternationalAdapter}), patch(
            "stable.tasks.upsert_article_from_draft", return_value=ArticleUpsertResult(article=article, created=True)
        ):
            result = _crawl_international_source(source)

        source.refresh_from_db()
        job = CrawlJob.objects.get(pk=result["crawl_job_id"])
        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(job.status, TaskStatus.SUCCESS)
        self.assertIn("parse failed 跳过 1 条", job.error_message)
        self.assertIn("empty detail body", job.error_message)
        self.assertIn("parse failed 跳过 1 条", source.last_crawl_message)

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False)
    def test_international_listing_skips_are_recorded_without_marking_source_failed(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.TDN_FRANCE, source_mode=SourceMode.ACCESS)

        class FakeInternationalAdapter:
            def __init__(self):
                self.skipped_items = [
                    "https://www.thoroughbreddailynews.com/old-story/: stale_published_at 2022-03-21T13:11:40+00:00"
                ]

            def fetch_listing(self, mode, page):
                return []

            def fetch_detail(self, source_url):
                raise AssertionError("no detail fetch expected")

            def normalize_source_payload(self, stub, detail):
                raise AssertionError("no draft expected")

        with patch("stable.tasks.INTERNATIONAL_ADAPTERS", {source.adapter_key: FakeInternationalAdapter}):
            result = _crawl_international_source(source)

        source.refresh_from_db()
        job = CrawlJob.objects.get(pk=result["crawl_job_id"])
        self.assertEqual(result["new_count"], 0)
        self.assertEqual(result["seen_count"], 0)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(job.status, TaskStatus.SUCCESS)
        self.assertIn("跳过 1 条", job.error_message)
        self.assertIn("stale_published_at", job.error_message)
        self.assertEqual(source.last_crawl_status, TaskStatus.SUCCESS)
        self.assertIn("stale_published_at", source.last_crawl_message)

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False)
    def test_international_all_detail_parse_errors_mark_source_failed(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.SKY_SPORTS_RACING, source_mode=SourceMode.ACCESS)
        bad_stub = type("Stub", (), {"source_url": "https://www.skysports.com/racing/news/bad-detail"})()

        class FakeInternationalAdapter:
            def fetch_listing(self, mode, page):
                return [bad_stub]

            def fetch_detail(self, source_url):
                raise ValueError("empty detail body")

            def normalize_source_payload(self, stub, detail):
                return object()

        with patch("stable.tasks.INTERNATIONAL_ADAPTERS", {source.adapter_key: FakeInternationalAdapter}):
            with self.assertRaises(RuntimeError):
                _crawl_international_source(source)

        source.refresh_from_db()
        job = CrawlJob.objects.latest("id")
        self.assertEqual(job.status, TaskStatus.FAILED)
        self.assertEqual(job.fail_count, 1)
        self.assertIn("parse failed 跳过 1 条", job.error_message)
        self.assertIn("empty detail body", job.error_message)
        self.assertEqual(source.last_crawl_status, TaskStatus.FAILED)
        self.assertIn("parse failed 跳过 1 条", source.last_crawl_message)

    @override_settings(AUTO_TRANSLATE_ON_INGEST=False)
    def test_jra_detail_structure_error_skips_article_and_continues(self):
        sync_builtin_sources()
        source = NewsSource.objects.get(source_site=SourceSite.JRA, source_mode=SourceMode.OFFICIAL)
        bad_stub = type("Stub", (), {"source_url": "https://www.jra.go.jp/news/202605/bad.html"})()
        good_stub = type("Stub", (), {"source_url": "https://www.jra.go.jp/news/202605/good.html"})()
        article = NewsArticle.objects.create(
            source_site=SourceSite.JRA,
            source_mode=SourceMode.OFFICIAL,
            source_article_id="/news/202605/good.html",
            title_ja="JRA 正常详情",
            body_ja_raw="本文",
            body_ja_normalized="本文",
            published_at=timezone.now(),
            source_url="https://www.jra.go.jp/news/202605/good.html",
            workflow_status=WorkflowStatus.PENDING_TRANSLATION,
        )

        with patch("stable.tasks.JRAAdapter.fetch_listing", side_effect=[[bad_stub, good_stub], []]), patch(
            "stable.tasks.JRAAdapter.fetch_detail", side_effect=[AttributeError("missing date node"), object()]
        ), patch("stable.tasks.JRAAdapter.normalize_source_payload", return_value=object()), patch(
            "stable.tasks.upsert_article_from_draft", return_value=(article, True)
        ):
            result = _crawl_jra_source(source=source)

        source.refresh_from_db()
        job = CrawlJob.objects.get(pk=result["crawl_job_id"])
        self.assertEqual(result["new_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(job.status, TaskStatus.SUCCESS)
        self.assertIn("跳过 1 条", job.error_message)
        self.assertIn("missing date node", job.error_message)
        self.assertIn("跳过 1 条", source.last_crawl_message)
        self.assertIn("missing date node", source.last_crawl_message)


class TermCandidateDiscoveryTests(TestCase):
    def setUp(self):
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="term-candidate-1",
            title_ja="【大阪杯】メイショウタバルが出走、武豊騎手が騎乗",
            body_ja_raw="馬主は松本好雄。メイショウタバルが大阪杯に挑む。",
            body_ja_normalized="馬主は松本好雄。メイショウタバルが大阪杯に挑む。",
            published_at=timezone.now(),
            source_url="https://example.com/term-candidate-1",
        )

    def test_normalize_and_formal_alias_matching_includes_inactive_terms(self):
        term = TermEntry.objects.create(
            term_type="horse",
            source_ja="別名の馬",
            target_zh="测试马",
            aliases_ja=["メイショウタバル"],
            is_active=False,
        )
        self.assertEqual(normalize_japanese_term(" メイショウタバル "), "メイショウタバル")
        self.assertEqual(normalize_japanese_term(" EQUINOX "), "equinox")
        same_type, other_type = match_formal_terms("horse", "メイショウタバル")
        self.assertEqual(same_type, [term])
        self.assertEqual(other_type, [])

    def test_rule_discovery_finds_four_supported_types(self):
        findings = discover_term_findings(self.article)
        values = {(item.term_type, item.source_ja) for item in findings}
        self.assertIn(("horse", "メイショウタバル"), values)
        self.assertIn(("race", "大阪杯"), values)
        self.assertIn(("jockey", "武豊"), values)
        self.assertIn(("owner", "松本好雄"), values)

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_aggregate_is_idempotent_and_preserves_rejected_status(self):
        first = discover_and_aggregate_article(self.article)
        second = discover_and_aggregate_article(self.article)
        self.assertEqual(set(first["candidate_ids"]), set(second["candidate_ids"]))
        horse = TermCandidate.objects.get(term_type="horse", source_ja="メイショウタバル")
        evidence = horse.evidence.get(article=self.article)
        self.assertEqual(evidence.occurrence_count, 2)
        self.assertEqual(horse.article_count, 1)
        horse.status = TermCandidateStatus.REJECTED
        horse.save(update_fields=["status", "updated_at"])
        discover_and_aggregate_article(self.article)
        horse.refresh_from_db()
        self.assertEqual(horse.status, TermCandidateStatus.REJECTED)

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_formal_term_and_absent_source_are_not_persisted(self):
        TermEntry.objects.create(term_type="race", source_ja="大阪杯", target_zh="大阪杯")
        discover_and_aggregate_article(self.article)
        self.assertFalse(TermCandidate.objects.filter(term_type="race", source_ja="大阪杯").exists())
        absent = TermDiscoveryFinding("horse", "不存在的马", 99, "test", "测试", "title_ja", "")
        self.assertIsNone(aggregate_finding(self.article, absent))

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_unknown_horse_and_race_enter_candidate_pool_with_content_fields(self):
        discover_and_aggregate_article(self.article)
        horse = TermCandidate.objects.get(term_type="horse", source_ja="メイショウタバル")
        race = TermCandidate.objects.get(term_type="race", source_ja="大阪杯")

        self.assertEqual(horse.target_zh, "")
        self.assertEqual(horse.aliases_ja, [])
        self.assertEqual(horse.aliases_zh, [])
        self.assertEqual(race.target_zh, "")
        self.assertEqual(race.aliases_ja, [])
        self.assertEqual(race.aliases_zh, [])
        self.assertTrue(horse.evidence.filter(article=self.article).exists())
        self.assertTrue(race.evidence.filter(article=self.article).exists())

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_external_alias_horse_enters_candidate_pool_from_background_body(self):
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="external-alias-candidate",
            title_ja="重賞展望",
            body_ja_raw="前半は調教過程を紹介する。" * 6 + "背景としてマヤノライジンにも触れた。",
            body_ja_normalized="前半は調教過程を紹介する。" * 6 + "背景としてマヤノライジンにも触れた。",
            published_at=timezone.now(),
            source_url="https://example.com/external-alias-candidate",
        )

        discover_and_aggregate_article(article)

        candidate = TermCandidate.objects.get(term_type="horse", source_ja="マヤノライジン")
        evidence = candidate.evidence.get(article=article)
        self.assertIn("本地外部马名索引命中且缺少中文译名", candidate.detection_reasons)
        self.assertIn("external_horse_alias", evidence.detectors)

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_external_alias_horse_with_formal_term_does_not_create_candidate(self):
        TermEntry.objects.create(term_type="horse", source_ja="マヤノライジン", target_zh="摩耶雷神")
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="1001",
            name_ja="マヤノライジン",
            normalized_name="マヤノライジン",
            alias_source="test",
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="external-alias-formal",
            title_ja="マヤノライジンが出走",
            body_ja_raw="マヤノライジンが重賞へ向かう。",
            body_ja_normalized="マヤノライジンが重賞へ向かう。",
            published_at=timezone.now(),
            source_url="https://example.com/external-alias-formal",
        )

        discover_and_aggregate_article(article)

        self.assertFalse(TermCandidate.objects.filter(term_type="horse", source_ja="マヤノライジン").exists())

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_common_word_external_alias_without_strong_context_does_not_enter_candidate_pool(self):
        TermEntry.objects.create(
            term_type="fixed_phrase",
            source_ja="タイトル",
            target_zh="标题",
            notes="non_horse_common_word: 测试普通词",
        )
        ExternalHorseAlias.objects.create(
            source="netkeiba",
            external_horse_id="2001",
            name_ja="タイトル",
            normalized_name="タイトル",
            alias_source="test",
        )
        article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="external-alias-common-word",
            title_ja="記事のタイトルを変更",
            body_ja_raw="ページタイトルを確認した。",
            body_ja_normalized="ページタイトルを確認した。",
            published_at=timezone.now(),
            source_url="https://example.com/external-alias-common-word",
        )

        discover_and_aggregate_article(article)

        self.assertFalse(TermCandidate.objects.filter(term_type="horse", source_ja="タイトル").exists())

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_formal_alias_prevents_horse_and_race_candidates(self):
        TermEntry.objects.create(term_type="horse", source_ja="正式马名", target_zh="正式马名", aliases_ja=["メイショウタバル"])
        TermEntry.objects.create(term_type="race", source_ja="正式赛事", target_zh="正式赛事", aliases_ja=["大阪杯"])
        discover_and_aggregate_article(self.article)
        self.assertFalse(TermCandidate.objects.filter(term_type="horse", source_ja="メイショウタバル").exists())
        self.assertFalse(TermCandidate.objects.filter(term_type="race", source_ja="大阪杯").exists())

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_cross_type_formal_conflict_is_retained(self):
        TermEntry.objects.create(term_type="owner", source_ja="武豊", target_zh="冲突词")
        discover_and_aggregate_article(self.article)
        candidate = TermCandidate.objects.get(term_type="jockey", source_ja="武豊")
        self.assertEqual(candidate.conflicts[0]["term_type"], "owner")

    @override_settings(TERM_DISCOVERY_MIN_CONFIDENCE=60)
    def test_evidence_contexts_are_bounded(self):
        for index in range(7):
            aggregate_finding(
                self.article,
                TermDiscoveryFinding(
                    "horse",
                    "メイショウタバル",
                    78,
                    "test",
                    "测试",
                    "title_ja",
                    f"上下文 {index}",
                ),
            )
        evidence = TermCandidate.objects.get(term_type="horse", source_ja="メイショウタバル").evidence.get(article=self.article)
        self.assertEqual(len(evidence.contexts), 5)

    @override_settings(TERM_DISCOVERY_ENABLED=False)
    def test_task_skips_when_disabled(self):
        result = discover_term_candidates_task.run(self.article.id)
        self.assertTrue(result["skipped"])
        self.assertEqual(TermCandidate.objects.count(), 0)

    @override_settings(TERM_DISCOVERY_ENABLED=True)
    def test_task_records_failure_when_article_is_missing(self):
        with self.assertRaises(NewsArticle.DoesNotExist):
            discover_term_candidates_task.run(999999)
        log = TaskExecutionLog.objects.get(task_name="discover_term_candidates")
        self.assertEqual(log.status, TaskStatus.FAILED)
        self.assertTrue(log.finished_at)


@override_settings(TERM_DISCOVERY_ENABLED=True, TERM_DISCOVERY_MIN_CONFIDENCE=60, CELERY_TASK_ALWAYS_EAGER=True)
class TermCandidateReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="term-admin", password="pass", is_staff=True)
        self.client = Client()
        self.client.force_login(self.user)
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="term-review-1",
            title_ja="メイショウタバルが出走",
            body_ja_raw="メイショウタバルが勝利した。",
            body_ja_normalized="メイショウタバルが勝利した。",
            published_at=timezone.now(),
            source_url="https://example.com/term-review-1",
        )
        discover_and_aggregate_article(self.article)
        self.candidate = TermCandidate.objects.get(term_type="horse")

    def test_accept_candidate_creates_formal_term_and_logs(self):
        self.candidate.target_zh = "名将田原"
        self.candidate.aliases_ja = ["メイショウ"]
        self.candidate.aliases_zh = ["名将田原号"]
        self.candidate.save(update_fields=["target_zh", "aliases_ja", "aliases_zh", "updated_at"])
        term = accept_candidate(
            self.candidate,
            {
                "term_type": "horse",
                "source_ja": self.candidate.source_ja,
                "target_zh": self.candidate.target_zh,
                "aliases_ja": self.candidate.aliases_ja,
                "aliases_zh": self.candidate.aliases_zh,
                "priority": 10,
                "is_active": True,
                "notes": "",
                "review_notes": "确认",
            },
            self.user,
        )
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.ACCEPTED)
        self.assertEqual(self.candidate.accepted_term, term)
        self.assertEqual(term.aliases_ja, ["メイショウ"])
        self.assertEqual(term.aliases_zh, ["名将田原号"])
        self.assertTrue(self.user.operation_logs.filter(action_type="term_candidate_accepted").exists())
        with self.assertRaisesMessage(ValueError, "只有待审核候选"):
            set_candidate_status(self.candidate, self.user, TermCandidateStatus.REJECTED)

    def test_merge_requires_explicit_alias_confirmation(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="正式马名", target_zh="正式译名")
        merge_candidate(self.candidate, self.user, target_term=term, add_as_alias=False)
        term.refresh_from_db()
        self.assertNotIn(self.candidate.source_ja, term.aliases_ja)

    def test_reject_keeps_candidate_and_evidence(self):
        set_candidate_status(self.candidate, self.user, TermCandidateStatus.REJECTED, "误报")
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.REJECTED)
        self.assertTrue(self.candidate.evidence.exists())

    def test_staff_pages_and_single_article_retrigger(self):
        list_response = self.client.get(reverse("console-term-candidate-list"))
        detail_response = self.client.get(reverse("console-term-candidate-detail", args=[self.candidate.id]))
        retrigger_response = self.client.post(
            reverse("console-article-discover-terms", args=[self.article.id]),
            {"next": reverse("console-candidate-detail", args=[self.article.id])},
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "メイショウタバル")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(retrigger_response.status_code, 302)
        self.assertTrue(TaskExecutionLog.objects.filter(task_name="discover_term_candidates", status=TaskStatus.SUCCESS).exists())

    def test_list_filters_by_status_and_type(self):
        response = self.client.get(
            reverse("console-term-candidate-list"),
            {"status": TermCandidateStatus.PENDING, "term_type": "horse", "min_confidence": 70},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "メイショウタバル")
        response = self.client.get(reverse("console-term-candidate-list"), {"term_type": "race"})
        self.assertNotContains(response, "メイショウタバル")

    def test_list_filters_by_keyword_source_and_seen_date(self):
        source = NewsSource.objects.create(
            name="功能测试来源",
            homepage_url="https://example.com",
            feed_url="https://example.com/feed",
        )
        self.article.source_config = source
        self.article.save(update_fields=["source_config", "updated_at"])
        today = timezone.localdate().isoformat()

        response = self.client.get(
            reverse("console-term-candidate-list"),
            {"q": "メイショウ", "source": source.id, "seen_from": today, "seen_to": today},
        )
        self.assertContains(response, "メイショウタバル")
        response = self.client.get(reverse("console-term-candidate-list"), {"q": "不存在"})
        self.assertNotContains(response, "メイショウタバル")

    def test_unauthenticated_user_is_redirected_to_login(self):
        client = Client()
        response = client.get(reverse("console-term-candidate-list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("backend-login"), response.url)

    def test_non_staff_is_forbidden(self):
        non_staff = User.objects.create_user(username="reader", password="pass")
        client = Client()
        client.force_login(non_staff)
        response = client.get(reverse("console-term-candidate-list"))
        self.assertEqual(response.status_code, 403)

    def test_batch_review_only_changes_pending_candidates(self):
        accepted = TermCandidate.objects.create(
            term_type="race",
            source_ja="大阪杯",
            normalized_key="大阪杯",
            status=TermCandidateStatus.ACCEPTED,
        )
        response = self.client.post(
            reverse("console-term-candidate-batch-review"),
            {"candidate_ids": [self.candidate.id, accepted.id], "status": TermCandidateStatus.IGNORED},
        )
        self.assertEqual(response.status_code, 302)
        self.candidate.refresh_from_db()
        accepted.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.IGNORED)
        self.assertEqual(accepted.status, TermCandidateStatus.ACCEPTED)

    def test_accept_endpoint_creates_formal_term_with_modified_fields(self):
        self.candidate.target_zh = "名将田原"
        self.candidate.aliases_ja = ["メイショウ"]
        self.candidate.aliases_zh = ["名将"]
        self.candidate.save(update_fields=["target_zh", "aliases_ja", "aliases_zh", "updated_at"])
        response = self.client.post(
            reverse("console-term-candidate-accept", args=[self.candidate.id]),
            {
                "term_type": "horse",
                "source_ja": "メイショウタバル改",
                "target_zh": "名将田原改",
                "aliases_ja_text": "メイショウタバル",
                "aliases_zh_text": "名将田原",
                "priority": "25",
                "notes": "功能测试正式术语",
                "review_notes": "页面修改后接受",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.candidate.refresh_from_db()
        term = TermEntry.objects.get(source_ja="メイショウタバル改")
        self.assertEqual(self.candidate.status, TermCandidateStatus.ACCEPTED)
        self.assertEqual(self.candidate.accepted_term, term)
        self.assertEqual(term.aliases_ja, ["メイショウタバル"])
        self.assertEqual(term.aliases_zh, ["名将田原"])
        self.assertEqual(term.priority, 25)
        self.assertEqual(self.candidate.review_notes, "页面修改后接受")

    def test_accept_endpoint_rejects_existing_formal_term(self):
        TermEntry.objects.create(term_type="horse", source_ja=self.candidate.source_ja, target_zh="已有译名")
        response = self.client.post(
            reverse("console-term-candidate-accept", args=[self.candidate.id]),
            {
                "term_type": "horse",
                "source_ja": self.candidate.source_ja,
                "target_zh": "重复译名",
                "priority": "0",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "已存在相同原文", status_code=400)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.PENDING)

    def test_merge_endpoint_adds_alias_only_with_explicit_confirmation(self):
        term = TermEntry.objects.create(term_type="horse", source_ja="正式马名", target_zh="正式译名")
        response = self.client.post(
            reverse("console-term-candidate-merge", args=[self.candidate.id]),
            {
                "target_term": term.id,
                "add_as_alias": "on",
                "review_notes": "确认添加别名",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.candidate.refresh_from_db()
        term.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.MERGED)
        self.assertEqual(self.candidate.merged_into_term, term)
        self.assertIn(self.candidate.source_ja, term.aliases_ja)
        self.assertTrue(self.candidate.evidence.exists())
        search_response = self.client.get(reverse("console-term-list"), {"q": self.candidate.source_ja})
        self.assertContains(search_response, term.source_ja)

    def test_merge_endpoint_adds_cross_language_alias_to_term_concept(self):
        self.candidate.source_language = SourceLanguage.ENGLISH
        self.candidate.source_ja = "Equinox"
        self.candidate.normalized_key = "Equinox"
        self.candidate.save(update_fields=["source_language", "source_ja", "normalized_key", "updated_at"])
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
        )

        response = self.client.post(
            reverse("console-term-candidate-merge", args=[self.candidate.id]),
            {
                "target_term": term.id,
                "add_as_alias": "on",
                "review_notes": "英文名并入同一马匹",
            },
        )

        self.assertEqual(response.status_code, 302)
        term.refresh_from_db()
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.MERGED)
        self.assertNotIn("Equinox", term.aliases_ja)
        self.assertTrue(
            TermAlias.objects.filter(term=term, source_language=SourceLanguage.ENGLISH, text="Equinox").exists()
        )
        matches = resolve_terms_for_language("Equinox is back", SourceLanguage.ENGLISH, limit=10)
        self.assertEqual([item.target_zh for item in matches], ["春秋分"])

    def test_merge_endpoint_does_not_duplicate_cross_language_alias_by_case(self):
        self.candidate.source_language = SourceLanguage.ENGLISH
        self.candidate.source_ja = "EQUINOX"
        self.candidate.normalized_key = "equinox"
        self.candidate.save(update_fields=["source_language", "source_ja", "normalized_key", "updated_at"])
        term = TermEntry.objects.create(
            term_type="horse",
            source_language=SourceLanguage.JAPANESE,
            source_ja="イクイノックス",
            target_zh="春秋分",
        )
        TermAlias.objects.create(
            term=term,
            source_language=SourceLanguage.ENGLISH,
            text="Equinox",
            alias_type=TermAliasType.ALIAS,
            is_active=True,
        )

        response = self.client.post(
            reverse("console-term-candidate-merge", args=[self.candidate.id]),
            {
                "target_term": term.id,
                "add_as_alias": "on",
                "review_notes": "英文名大小写合并",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            TermAlias.objects.filter(term=term, source_language=SourceLanguage.ENGLISH, text__iexact="equinox").count(),
            1,
        )

    def test_merge_endpoint_into_candidate_keeps_evidence(self):
        target = TermCandidate.objects.create(
            term_type="horse",
            source_ja="メイショウタバル別候補",
            normalized_key="メイショウタバル別候補",
        )
        response = self.client.post(
            reverse("console-term-candidate-merge", args=[self.candidate.id]),
            {"target_candidate": target.id, "review_notes": "合并重复候选"},
        )
        self.assertEqual(response.status_code, 302)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.MERGED)
        self.assertEqual(self.candidate.merged_into_candidate, target)
        self.assertTrue(self.candidate.evidence.exists())

    def test_reject_and_ignore_endpoints_keep_evidence_and_log_operations(self):
        reject_response = self.client.post(
            reverse("console-term-candidate-reject", args=[self.candidate.id]),
            {"review_notes": "页面拒绝"},
            follow=True,
        )
        self.assertEqual(reject_response.status_code, 200)
        self.assertContains(reject_response, "候选状态已更新为“已拒绝”。")
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, TermCandidateStatus.REJECTED)
        self.assertTrue(self.candidate.evidence.exists())

        ignored = TermCandidate.objects.create(
            term_type="race",
            source_ja="测试忽略杯",
            normalized_key="测试忽略杯",
        )
        ignore_response = self.client.post(
            reverse("console-term-candidate-ignore", args=[ignored.id]),
            {"review_notes": "页面忽略"},
            follow=True,
        )
        self.assertEqual(ignore_response.status_code, 200)
        self.assertContains(ignore_response, "候选状态已更新为“已忽略”。")
        ignored.refresh_from_db()
        self.assertEqual(ignored.status, TermCandidateStatus.IGNORED)
        self.assertTrue(self.user.operation_logs.filter(action_type="term_candidate_rejected").exists())
        self.assertTrue(self.user.operation_logs.filter(action_type="term_candidate_ignored").exists())

    def test_validate_candidate_news_since_midnight_command_reports_today_articles(self):
        TermEntry.objects.create(term_type="race", source_ja="宝塚記念", target_zh="宝塚纪念", race_grade="G1")
        today_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="today-candidate-news",
            title_ja="【宝塚記念】シュガークンが出走",
            body_ja_raw="シュガークンが宝塚記念・GIに挑む。",
            body_ja_normalized="シュガークンが宝塚記念・GIに挑む。",
            translated_body_zh="宝塚纪念候选新闻。",
            translation_status=ArticleTranslationStatus.TRANSLATED,
            published_at=timezone.now(),
            first_seen_at=timezone.now(),
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            source_url="https://example.com/today-candidate-news",
        )
        yesterday = timezone.now() - timedelta(days=1)
        old_article = NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            source_article_id="old-candidate-news",
            title_ja="【大阪杯】古い候補ニュース",
            body_ja_raw="古い候補ニュース。",
            body_ja_normalized="古い候補ニュース。",
            translated_body_zh="旧新闻。",
            translation_status=ArticleTranslationStatus.TRANSLATED,
            published_at=yesterday,
            first_seen_at=yesterday,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            source_url="https://example.com/old-candidate-news",
        )
        discover_and_aggregate_article(today_article)

        out = StringIO()
        call_command("validate_candidate_news_since_midnight", "--format", "json", stdout=out)
        payload = __import__("json").loads(out.getvalue())
        article_ids = [item["article_id"] for item in payload["articles"]]

        self.assertIn(today_article.id, article_ids)
        self.assertNotIn(old_article.id, article_ids)
        self.assertGreaterEqual(payload["candidate_news_count"], 1)
        self.assertIn("race_priority", payload["articles"][0])
        self.assertIn("term_candidate_count", payload["articles"][0])


class TermbaseSeedDataPreparationTests(TestCase):
    def _write_fixture(self, root: Path, name: str, text: str) -> None:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _read_csv(self, path: Path) -> list[dict]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_prepare_seed_command_generates_review_files_without_db_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "fixtures"
            output_dir = root / "out"
            terms_seed_before = Path("server/stable/data/terms_seed.csv").read_text(encoding="utf-8")
            counts_before = {
                "term_entries": TermEntry.objects.count(),
                "term_aliases": TermAlias.objects.count(),
                "term_candidates": TermCandidate.objects.count(),
                "external_horses": ExternalHorse.objects.count(),
                "external_aliases": ExternalHorseAlias.objects.count(),
            }
            self._write_fixture(
                input_dir,
                "hkjc_local_horses.html",
                """
                <table data-source-url="https://racing.hkjc.com/en-us/local/information/selecthorse">
                  <tr><th>English Name</th><th>Chinese Name</th><th>Former Name</th><th>Region</th></tr>
                  <tr><td>BEAUTY GENERATION</td><td>美麗傳承</td><td>Montaigna</td><td>hk</td></tr>
                </table>
                """,
            )
            self._write_fixture(
                input_dir,
                "wpstud_horses.html",
                """
                <table data-source-url="https://www.wpstud.com/Translation/Horse/Horse.htm">
                  <tr><th>日文馬名</th><th>英文馬名</th><th>中文馬名</th><th>代表地區</th></tr>
                  <tr><td>ディープインパクト</td><td>Deep Impact</td><td>大震撼</td><td>jp</td></tr>
                  <tr><td></td><td>BEAUTY GENERATION</td><td>美麗傳承號</td><td>hk</td></tr>
                </table>
                """,
            )

            out = StringIO()
            call_command(
                "prepare_termbase_seed_data",
                "--source",
                "hkjc",
                "--source",
                "wpstud",
                "--input-dir",
                str(input_dir),
                "--output-dir",
                str(output_dir),
                stdout=out,
            )

            candidates_path = output_dir / "seed_candidates.csv"
            conflicts_path = output_dir / "seed_conflicts.csv"
            summary_path = output_dir / "summary.json"
            self.assertTrue(candidates_path.exists())
            self.assertTrue(conflicts_path.exists())
            self.assertTrue(summary_path.exists())
            self.assertEqual(Path("server/stable/data/terms_seed.csv").read_text(encoding="utf-8"), terms_seed_before)
            self.assertEqual(TermEntry.objects.count(), counts_before["term_entries"])
            self.assertEqual(TermAlias.objects.count(), counts_before["term_aliases"])
            self.assertEqual(TermCandidate.objects.count(), counts_before["term_candidates"])
            self.assertEqual(ExternalHorse.objects.count(), counts_before["external_horses"])
            self.assertEqual(ExternalHorseAlias.objects.count(), counts_before["external_aliases"])

            with candidates_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                self.assertEqual(
                    next(reader),
                    [
                        "term_type",
                        "source_language",
                        "racing_region",
                        "source_ja",
                        "target_zh",
                        "aliases_ja",
                        "aliases_zh",
                        "priority",
                        "is_active",
                        "notes",
                        "race_grade",
                    ],
                )
            preview = preview_term_import(csv_text=candidates_path.read_text(encoding="utf-8-sig"), import_mode="create")
            self.assertEqual(preview["summary"]["error_count"], 0)

            rows = self._read_csv(candidates_path)
            beauty_rows = [row for row in rows if row["source_ja"] == "BEAUTY GENERATION"]
            self.assertEqual(beauty_rows[0]["target_zh"], "美丽传承")
            self.assertIn("美丽传承号", beauty_rows[0]["aliases_zh"])
            self.assertIn("original_zh_hant=美麗傳承", beauty_rows[0]["notes"])
            self.assertIn("source_tier=official", beauty_rows[0]["notes"])

            deep_impact = next(row for row in rows if row["source_ja"] == "ディープインパクト")
            self.assertEqual(deep_impact["target_zh"], "大震撼")
            self.assertIn("source_tier=community", deep_impact["notes"])
            self.assertIn("requires_review=true", deep_impact["notes"])
            self.assertEqual(rows[-1]["source_ja"], "ディープインパクト")

            conflicts = self._read_csv(conflicts_path)
            self.assertEqual(conflicts[0]["recommended_target_zh"], "美丽传承")
            self.assertIn("美丽传承号", conflicts[0]["alternate_target_zh"])
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertFalse(summary["incomplete"])
            self.assertEqual(summary["candidate_count"], len(rows))

    def test_prepare_seed_command_marks_network_failures_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with patch("stable.services.termbase_seed.requests.get", side_effect=requests.Timeout("slow")):
                out = StringIO()
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc",
                    "--allow-network",
                    "--max-requests",
                    "1",
                    "--timeout-seconds",
                    "1",
                    "--output-dir",
                    str(output_dir),
                    stdout=out,
                )

            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["incomplete"])
            self.assertEqual(summary["request_count"], 1)
            self.assertEqual(summary["failures"][0]["error"], "max_requests=1 reached")
            self.assertEqual(len(summary["requests"]), 1)
            self.assertIn("slow", summary["requests"][0]["error"])

    def test_prepare_seed_command_extracts_hkjc_horses_from_letter_and_detail_pages(self):
        class Response:
            status_code = 200
            encoding = "utf-8"

            def __init__(self, url: str, text: str):
                self.url = url
                self.text = text

        responses = {
            "https://racing.hkjc.com/en-us/local/information/selecthorse": """
                <a href="/en-us/local/information/selecthorsebychar?ordertype=A">A</a>
            """,
            "https://racing.hkjc.com/en-us/local/information/selecthorsebychar?ordertype=A": """
                <a href="/en-us/local/information/horse?horseid=HK_2023_J260">BEAUTY ALLIANCE</a>
                <a href="/en-us/local/information/horse?horseid=HK_2024_K491">BEAUTY BOLT</a>
            """,
            "https://racing.hkjc.com/zh-hk/local/information/horse?horseid=HK_2023_J260": """
                <table class="horseProfile"><tr><td><span class="title_text">一起美麗 (J260)</span></td></tr></table>
            """,
            "https://racing.hkjc.com/zh-hk/local/information/horse?horseid=HK_2024_K491": """
                <table class="horseProfile"><tr><td><span class="title_text">美麗閃電 (K491)</span></td></tr></table>
            """,
        }

        def fake_get(url, **_kwargs):
            return Response(url, responses[url])

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with patch("stable.services.termbase_seed.requests.get", side_effect=fake_get) as get:
                out = StringIO()
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc",
                    "--allow-network",
                    "--limit-pages",
                    "1",
                    "--limit-horses",
                    "2",
                    "--max-requests",
                    "10",
                    "--request-interval-seconds",
                    "0",
                    "--output-dir",
                    str(output_dir),
                    stdout=out,
                )

            self.assertEqual(get.call_count, 4)
            rows = self._read_csv(output_dir / "seed_candidates.csv")
            self.assertEqual([row["source_ja"] for row in rows], ["BEAUTY ALLIANCE", "BEAUTY BOLT"])
            self.assertEqual([row["target_zh"] for row in rows], ["一起美丽", "美丽闪电"])
            self.assertTrue(all(row["source_language"] == SourceLanguage.ENGLISH for row in rows))
            self.assertTrue(all(row["racing_region"] == RacingRegion.HONG_KONG for row in rows))
            self.assertTrue(all("source_tier=official" in row["notes"] for row in rows))
            self.assertTrue(all("requires_review=false" in row["notes"] for row in rows))
            self.assertIn("original_zh_hant=一起美麗", rows[0]["notes"])
            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertFalse(summary["incomplete"])
            self.assertEqual(summary["candidate_count"], 2)

    def test_prepare_seed_command_filters_hkjc_horses_by_letter(self):
        class Response:
            status_code = 200
            encoding = "utf-8"

            def __init__(self, url: str, text: str):
                self.url = url
                self.text = text

        responses = {
            "https://racing.hkjc.com/en-us/local/information/selecthorse": """
                <a href="/en-us/local/information/selecthorsebychar?ordertype=A">A</a>
                <a href="/en-us/local/information/selecthorsebychar?ordertype=B">B</a>
            """,
            "https://racing.hkjc.com/en-us/local/information/selecthorsebychar?ordertype=B": """
                <a href="/en-us/local/information/horse?horseid=HK_2024_K491">BEAUTY BOLT</a>
            """,
            "https://racing.hkjc.com/zh-hk/local/information/horse?horseid=HK_2024_K491": """
                <table class="horseProfile"><tr><td><span class="title_text">美麗閃電 (K491)</span></td></tr></table>
            """,
        }

        def fake_get(url, **_kwargs):
            return Response(url, responses[url])

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with patch("stable.services.termbase_seed.requests.get", side_effect=fake_get) as get:
                out = StringIO()
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc",
                    "--allow-network",
                    "--limit-pages",
                    "1",
                    "--hkjc-letter",
                    "B",
                    "--max-requests",
                    "10",
                    "--request-interval-seconds",
                    "0",
                    "--output-dir",
                    str(output_dir),
                    stdout=out,
                )

            requested_urls = [call_args.args[0] for call_args in get.call_args_list]
            self.assertIn("https://racing.hkjc.com/en-us/local/information/selecthorsebychar?ordertype=B", requested_urls)
            self.assertNotIn("https://racing.hkjc.com/en-us/local/information/selecthorsebychar?ordertype=A", requested_urls)
            rows = self._read_csv(output_dir / "seed_candidates.csv")
            self.assertEqual([row["source_ja"] for row in rows], ["BEAUTY BOLT"])

    def test_prepare_seed_command_extracts_hkjc_local_result_terms(self):
        class Response:
            status_code = 200
            encoding = "utf-8"

            def __init__(self, url: str, text: str):
                self.url = url
                self.text = text

        landing = """
            <select id="selectId">
              <option value='{"date":"24/06/2026","venue":""}'>24/06/2026</option>
            </select>
        """
        date_page = """
            <a href="/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=2">Race 2</a>
        """
        en_race = """
            <table>
              <tr><td>RACE 1 (796)</td><td></td><td></td></tr>
              <tr><td>Class 5 - 2200M</td><td>Going :</td><td>GOOD</td></tr>
              <tr><td>ICE HOUSE STREET HANDICAP</td><td>Course :</td><td>TURF</td></tr>
            </table>
            <table>
              <tr><th>Pla.</th><th>Horse No.</th><th>Horse</th><th>Jockey</th><th>Trainer</th></tr>
              <tr><td>1</td><td>3</td><td><a href="/en-us/local/information/horse?horseid=HK_2023_J524">ROSEWOOD FLEETFOOT (J524)</a></td><td>K Teetan</td><td>P F Yiu</td></tr>
              <tr><td>2</td><td>4</td><td><a href="/en-us/local/information/horse?horseid=HK_2024_K500">GOLDEN FORTUNE (K500)</a></td><td>H Bowman</td><td>K L Man</td></tr>
            </table>
        """
        zh_race = """
            <table>
              <tr><td>第 1 場 (796)</td><td></td><td></td></tr>
              <tr><td>第五班 - 2200米</td><td>場地狀況 :</td><td>好地</td></tr>
              <tr><td>雪廠街讓賽</td><td>賽道 :</td><td>草地</td></tr>
            </table>
            <table>
              <tr><th>名次</th><th>馬號</th><th>馬名</th><th>騎師</th><th>練馬師</th></tr>
              <tr><td>1</td><td>3</td><td><a href="/zh-hk/local/information/horse?horseid=HK_2023_J524">捷足奔馳 (J524)</a></td><td>田泰安</td><td>姚本輝</td></tr>
              <tr><td>2</td><td>4</td><td><a href="/zh-hk/local/information/horse?horseid=HK_2024_K500">連連好運 (K500)</a></td><td>布文</td><td>文家良</td></tr>
            </table>
        """
        responses = {
            "https://racing.hkjc.com/en-us/local/information/localresults": landing,
            "https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24": date_page,
            "https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1": en_race,
            "https://racing.hkjc.com/zh-hk/local/information/localresults?racedate=2026/06/24&Racecourse=HV&RaceNo=1": zh_race,
        }

        def fake_get(url, **_kwargs):
            return Response(url, responses[url])

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with patch("stable.services.termbase_seed.requests.get", side_effect=fake_get) as get:
                out = StringIO()
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc",
                    "--allow-network",
                    "--limit-pages",
                    "0",
                    "--hkjc-skip-horse-details",
                    "--hkjc-local-results-start-date",
                    "2026-06-24",
                    "--hkjc-local-results-end-date",
                    "2026-06-24",
                    "--limit-races",
                    "1",
                    "--max-requests",
                    "10",
                    "--request-interval-seconds",
                    "0",
                    "--output-dir",
                    str(output_dir),
                    stdout=out,
                )

            self.assertEqual(get.call_count, 4)
            rows = self._read_csv(output_dir / "seed_candidates.csv")
            by_source = {row["source_ja"]: row for row in rows}
            self.assertEqual(by_source["ICE HOUSE STREET HANDICAP"]["target_zh"], "雪厂街让赛")
            self.assertEqual(by_source["ROSEWOOD FLEETFOOT"]["target_zh"], "捷足奔驰")
            self.assertEqual(by_source["GOLDEN FORTUNE"]["target_zh"], "连连好运")
            self.assertEqual(by_source["K Teetan"]["target_zh"], "田泰安")
            self.assertEqual(by_source["H Bowman"]["target_zh"], "布文")
            self.assertTrue(all(row["source_language"] == SourceLanguage.ENGLISH for row in rows))
            self.assertTrue(all(row["racing_region"] == RacingRegion.HONG_KONG for row in rows))
            self.assertTrue(all("source=hkjc" in row["notes"] for row in rows))
            self.assertTrue(all("requires_review=false" in row["notes"] for row in rows))

            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            evidence = json.loads((output_dir / "source_evidence.json").read_text(encoding="utf-8"))
            self.assertFalse(summary["incomplete"])
            self.assertEqual(summary["candidate_count"], len(rows))
            horse_evidence = next(item for item in evidence["candidates"] if item["source_text"] == "ROSEWOOD FLEETFOOT")
            self.assertEqual(horse_evidence["race_key"]["RaceDate"], "20260624")
            self.assertEqual(horse_evidence["horse_id"], "HK_2023_J524")

    def test_hkjc_local_result_empty_bilingual_card_is_skipped(self):
        from stable.services.termbase_seed import (
            HKJCLocalResultRaceKey,
            build_seed_result,
            parse_hkjc_local_result_pair,
        )

        race_key = HKJCLocalResultRaceKey(race_date="20241113", racecourse="HV", race_no="7")
        records, failures = parse_hkjc_local_result_pair(
            "<html><body>Results</body></html>",
            "<html><body>賽果</body></html>",
            race_key=race_key,
            en_url="https://example.test/en",
            zh_url="https://example.test/zh",
            fetch_mode="network",
        )
        result = build_seed_result(records, failures=failures)

        self.assertEqual(records, [])
        self.assertFalse(result.summary["incomplete"])
        self.assertEqual(result.summary["failures"], failures)
        self.assertEqual(result.summary["skipped_races"][0]["error"], "local_result_not_available")

    def test_prepare_seed_command_stops_all_sources_at_max_requests(self):
        class Response:
            status_code = 200
            url = "https://example.com/ok"
            encoding = "utf-8"
            text = """
            <table data-source-url="https://example.com/ok">
              <tr><th>English Name</th><th>Chinese Name</th><th>Region</th></tr>
              <tr><td>ROMANTIC WARRIOR</td><td>浪漫勇士</td><td>hk</td></tr>
            </table>
            """

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with patch("stable.services.termbase_seed.requests.get", return_value=Response()) as get:
                out = StringIO()
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc",
                    "--source",
                    "wpstud",
                    "--allow-network",
                    "--max-requests",
                    "1",
                    "--request-interval-seconds",
                    "0",
                    "--output-dir",
                    str(output_dir),
                    stdout=out,
                )

            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(get.call_count, 1)
            self.assertEqual(summary["request_count"], 1)
            self.assertTrue(summary["incomplete"])
            self.assertEqual(summary["failures"][0]["error"], "max_requests=1 reached")
            self.assertEqual(summary["failures"][0]["source"], "hkjc")

    def test_seed_network_retry_attempts_count_against_max_requests(self):
        from stable.services.termbase_seed import MaxRequestsReached, SeedFetchOptions, SeedNetworkClient

        options = SeedFetchOptions(allow_network=True, max_requests=1, request_interval_seconds=0)
        get_client = SeedNetworkClient(options)
        with patch("stable.services.termbase_seed.requests.get", side_effect=requests.Timeout("GET timeout")) as get:
            with self.assertRaises(MaxRequestsReached):
                get_client.get_text("https://example.test/get", source="hkjc")

        self.assertEqual(get.call_count, 1)
        self.assertEqual(len(get_client.requests), 1)
        self.assertIn("GET timeout", get_client.requests[0].error)

        post_client = SeedNetworkClient(options)
        with patch("stable.services.termbase_seed.requests.post", side_effect=requests.Timeout("POST timeout")) as post:
            with self.assertRaises(MaxRequestsReached):
                post_client.post_json("https://example.test/post", source="hkjc_overseas", payload={})

        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(post_client.requests), 1)
        self.assertIn("POST timeout", post_client.requests[0].error)

    def test_prepare_seed_command_internal_preview_uses_upsert_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "fixtures"
            output_dir = Path(tmp) / "out"
            self._write_fixture(
                input_dir,
                "hkjc_local_horses.html",
                """
                <table data-source-url="https://racing.hkjc.com/en-us/local/information/selecthorse">
                  <tr><th>English Name</th><th>Chinese Name</th><th>Region</th></tr>
                  <tr><td>ROMANTIC WARRIOR</td><td>浪漫勇士</td><td>hk</td></tr>
                </table>
                """,
            )
            TermEntry.objects.create(
                term_type=TermType.HORSE,
                source_language=SourceLanguage.ENGLISH,
                source_ja="ROMANTIC WARRIOR",
                target_zh="浪漫勇士",
            )

            out = StringIO()
            call_command(
                "prepare_termbase_seed_data",
                "--source",
                "hkjc",
                "--input-dir",
                str(input_dir),
                "--output-dir",
                str(output_dir),
                stdout=out,
            )

            payload = json.loads(out.getvalue())
            self.assertEqual(payload["dry_run_error_count"], 0)
            create_preview = preview_term_import(
                csv_text=(output_dir / "seed_candidates.csv").read_text(encoding="utf-8-sig"),
                import_mode="create",
            )
            self.assertGreater(create_preview["summary"]["error_count"], 0)

    def test_prepare_seed_command_rejects_deferred_racecard_pdf_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CommandError):
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc_racecards_pdf",
                    "--output-dir",
                    str(Path(tmp) / "out"),
                )

    def test_prepare_seed_command_defaults_to_independent_runtime_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "fixtures"
            default_dir = root / "runtime" / "termbase_seed" / "fixed"
            self._write_fixture(
                input_dir,
                "hkjc_local_horses.html",
                """
                <table data-source-url="https://racing.hkjc.com/en-us/local/information/selecthorse">
                  <tr><th>English Name</th><th>Chinese Name</th><th>Region</th></tr>
                  <tr><td>ROMANTIC WARRIOR</td><td>浪漫勇士</td><td>hk</td></tr>
                </table>
                """,
            )

            with patch("stable.management.commands.prepare_termbase_seed_data.default_output_dir", return_value=default_dir):
                out = StringIO()
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc",
                    "--input-dir",
                    str(input_dir),
                    stdout=out,
                )

            payload = json.loads(out.getvalue())
            self.assertEqual(payload["output_dir"], str(default_dir))
            self.assertTrue((default_dir / "seed_candidates.csv").exists())
            self.assertTrue((default_dir / "seed_conflicts.csv").exists())
            self.assertNotEqual(default_dir, Path("server/stable/data"))

    def test_prepare_seed_command_extracts_hkjc_overseas_bilingual_racecard_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "fixtures"
            output_dir = root / "out"
            self._write_fixture(
                input_dir,
                "hkjc_overseas_racecard_en.html",
                """
                <html lang="en" data-language="en-us"><body>
                  <main data-hkjc-overseas-racecard="true" data-race-date="2026-06-20" data-racecourse="S5" data-race-no="1" data-country="united_kingdom" data-source-url="https://racing.hkjc.com/en-us/overseas/racecard?RaceDate=20260620&Racecourse=S5&RaceNo=1">
                    <h1 data-race-name="true">King Charles III Stakes</h1>
                    <table data-race-card="true">
                      <tr><th>No.</th><th>Horse</th><th>Jockey</th></tr>
                      <tr><td>1</td><td><a href="/en-us/overseas/horseprofile?h=20260620/S5/1/GB001/1">ROYAL ASCOT</a></td><td>Ryan Moore</td></tr>
                      <tr><td>2</td><td><a href="/en-us/overseas/horseprofile?h=20260620/S5/1/GB002/2">BLUE POINT</a></td><td>William Buick</td></tr>
                    </table>
                  </main>
                </body></html>
                """,
            )
            self._write_fixture(
                input_dir,
                "hkjc_overseas_racecard_zh.html",
                """
                <html lang="zh-hk" data-language="zh-hk"><body>
                  <main data-hkjc-overseas-racecard="true" data-race-date="2026-06-20" data-racecourse="S5" data-race-no="1" data-country="英國" data-source-url="https://racing.hkjc.com/zh-hk/overseas/racecard?RaceDate=20260620&Racecourse=S5&RaceNo=1">
                    <h1 data-race-name="true">英皇查理斯三世錦標</h1>
                    <table data-race-card="true">
                      <tr><th>馬號</th><th>馬名</th><th>騎師</th></tr>
                      <tr><td>1</td><td><a href="/zh-hk/overseas/horseprofile?h=20260620/S5/1/GB001/1">皇家雅士谷</a></td><td>莫雅</td></tr>
                      <tr><td>2</td><td><a href="/zh-hk/overseas/horseprofile?h=20260620/S5/1/GB002/2">藍點</a></td><td>布宜學</td></tr>
                    </table>
                  </main>
                </body></html>
                """,
            )

            out = StringIO()
            call_command(
                "prepare_termbase_seed_data",
                "--source",
                "hkjc_overseas",
                "--input-dir",
                str(input_dir),
                "--output-dir",
                str(output_dir),
                stdout=out,
            )

            rows = self._read_csv(output_dir / "seed_candidates.csv")
            by_source = {row["source_ja"]: row for row in rows}
            self.assertEqual(by_source["ROYAL ASCOT"]["target_zh"], "皇家雅士谷")
            self.assertEqual(by_source["BLUE POINT"]["target_zh"], "蓝点")
            self.assertEqual(by_source["Ryan Moore"]["target_zh"], "莫雅")
            self.assertEqual(by_source["King Charles III Stakes"]["target_zh"], "英皇查理斯三世锦标")
            self.assertTrue(all(row["source_language"] == SourceLanguage.ENGLISH for row in rows))
            self.assertTrue(all(row["racing_region"] == RacingRegion.UNITED_KINGDOM for row in rows))
            self.assertTrue(all("source=hkjc_overseas" in row["notes"] for row in rows))
            self.assertTrue(all("source_tier=official" in row["notes"] for row in rows))
            self.assertTrue(all("requires_review=false" in row["notes"] for row in rows))

            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            evidence = json.loads((output_dir / "source_evidence.json").read_text(encoding="utf-8"))
            self.assertFalse(summary["incomplete"])
            self.assertEqual(summary["candidate_count"], len(rows))
            horse_evidence = next(item for item in evidence["candidates"] if item["source_text"] == "ROYAL ASCOT")
            self.assertEqual(horse_evidence["race_key"]["RaceDate"], "20260620")
            self.assertEqual(horse_evidence["horse_profile"]["simulcastHorseId"], "GB001")

            preview = preview_term_import(csv_text=(output_dir / "seed_candidates.csv").read_text(encoding="utf-8-sig"), import_mode="upsert")
            self.assertEqual(preview["summary"]["error_count"], 0)

    def test_prepare_seed_command_rejects_bad_hkjc_overseas_race_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CommandError, "Race Card 参数格式错误"):
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc_overseas",
                    "--hkjc-overseas-race",
                    "RaceDate=bad,Racecourse=S5,RaceNo=1",
                    "--output-dir",
                    str(Path(tmp) / "out"),
                )

    def test_prepare_seed_command_records_hkjc_overseas_translation_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "fixtures"
            output_dir = root / "out"
            for suffix, race_no, target in (
                ("a", "1", "皇家雅士谷"),
                ("b", "2", "皇家雅士谷號"),
                ("c", "3", "皇家雅士谷之星"),
            ):
                self._write_fixture(
                    input_dir,
                    f"hkjc_overseas_conflict_{suffix}_en.html",
                    f"""
                    <html lang="en"><body>
                      <main data-hkjc-overseas-racecard="true" data-race-date="2026-06-20" data-racecourse="S5" data-race-no="{race_no}" data-country="united_kingdom" data-source-url="https://racing.hkjc.com/en-us/overseas/racecard?RaceDate=20260620&Racecourse=S5&RaceNo={race_no}">
                        <h1 data-race-name="true">Conflict Race {race_no}</h1>
                        <table data-race-card="true"><tr><th>No.</th><th>Horse</th><th>Jockey</th></tr><tr><td>1</td><td>ROYAL ASCOT</td><td>Ryan Moore</td></tr></table>
                      </main>
                    </body></html>
                    """,
                )
                self._write_fixture(
                    input_dir,
                    f"hkjc_overseas_conflict_{suffix}_zh.html",
                    f"""
                    <html lang="zh-hk"><body>
                      <main data-hkjc-overseas-racecard="true" data-race-date="2026-06-20" data-racecourse="S5" data-race-no="{race_no}" data-country="英國" data-source-url="https://racing.hkjc.com/zh-hk/overseas/racecard?RaceDate=20260620&Racecourse=S5&RaceNo={race_no}">
                        <h1 data-race-name="true">衝突賽事{race_no}</h1>
                        <table data-race-card="true"><tr><th>馬號</th><th>馬名</th><th>騎師</th></tr><tr><td>1</td><td>{target}</td><td>莫雅</td></tr></table>
                      </main>
                    </body></html>
                    """,
                )

            out = StringIO()
            call_command(
                "prepare_termbase_seed_data",
                "--source",
                "hkjc_overseas",
                "--input-dir",
                str(input_dir),
                "--output-dir",
                str(output_dir),
                stdout=out,
            )

            conflicts = self._read_csv(output_dir / "seed_conflicts.csv")
            horse_conflicts = [row for row in conflicts if row["term_type"] == TermType.HORSE]
            candidates = self._read_csv(output_dir / "seed_candidates.csv")
            royal_ascot_rows = [row for row in candidates if row["source_ja"] == "ROYAL ASCOT"]
            self.assertEqual(len(royal_ascot_rows), 1)
            self.assertEqual(royal_ascot_rows[0]["target_zh"], "皇家雅士谷")
            self.assertIn("皇家雅士谷号", royal_ascot_rows[0]["aliases_zh"])
            self.assertIn("皇家雅士谷之星", royal_ascot_rows[0]["aliases_zh"])
            self.assertEqual({row["recommended_target_zh"] for row in horse_conflicts}, {"皇家雅士谷"})
            self.assertEqual({row["alternate_target_zh"] for row in horse_conflicts}, {"皇家雅士谷号", "皇家雅士谷之星"})

    def test_prepare_seed_command_marks_hkjc_overseas_direct_next_shell_incomplete(self):
        class Response:
            status_code = 200
            encoding = "utf-8"

            def __init__(self, url: str, text: str):
                self.url = url
                self.text = text

        landing = """
        <html><body>
          <a href="/en-us/overseas/racecard?RaceDate=20260620&Racecourse=S5&RaceNo=1">Race 1</a>
        </body></html>
        """
        next_shell = '<html><body><div class="Loadingcontainer"></div><script src="/_next/static/chunks/app.js"></script></body></html>'

        def fake_get(url, **_kwargs):
            if url == "https://racing.hkjc.com/en-us/overseas/":
                return Response(url, landing)
            return Response(url, next_shell)

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with patch("stable.services.termbase_seed.requests.get", side_effect=fake_get):
                out = StringIO()
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc_overseas",
                    "--allow-network",
                    "--request-interval-seconds",
                    "0",
                    "--max-requests",
                    "5",
                    "--output-dir",
                    str(output_dir),
                    stdout=out,
                )

            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            evidence = json.loads((output_dir / "source_evidence.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["incomplete"])
            self.assertIn("render_fallback_unavailable", evidence["failures"][0]["error"])

    def test_prepare_seed_command_extracts_hkjc_overseas_qids_date_range(self):
        class TextResponse:
            status_code = 200
            encoding = "utf-8"

            def __init__(self, url: str, text: str):
                self.url = url
                self.text = text

        class JsonResponse:
            status_code = 200
            url = "https://info.cld.hkjc.com/graphql/base/"

            def json(self):
                return {
                    "data": {
                        "raceMeetingProfile": [
                            {
                                "date": "2026-06-20",
                                "venueCode": "S5",
                                "races": [
                                    {
                                        "no": 1,
                                        "raceName_en": "King Charles III Stakes",
                                        "raceName_ch": "英皇查理斯三世錦標",
                                        "countryCodeNm": {"code": "GB", "english": "United Kingdom", "chinese": "英國"},
                                        "runners": [
                                            {
                                                "no": "1",
                                                "horse": {"id": "GB001", "name_en": "ROYAL ASCOT (GB)", "name_ch": "皇家雅士谷"},
                                                "jockey": {"code": "RM", "name_en": "Ryan Moore", "name_ch": "莫雅"},
                                            },
                                            {
                                                "no": "2",
                                                "horse": {"id": "GB002", "name_en": "BLUE POINT", "name_ch": "藍點"},
                                                "jockey": {"code": "WB", "name_en": "William Buick", "name_ch": "布宜學"},
                                            },
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }

        def fake_get(url, **_kwargs):
            return TextResponse(
                url,
                """
                <html><body>
                  <a href="/en-us/overseas/results?RaceDate=20260620&Racecourse=S5">Overseas Results</a>
                </body></html>
                """,
            )

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with patch("stable.services.termbase_seed.requests.get", side_effect=fake_get), patch(
                "stable.services.termbase_seed.requests.post", return_value=JsonResponse()
            ):
                out = StringIO()
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc_overseas",
                    "--allow-network",
                    "--hkjc-overseas-start-date",
                    "2026-06-20",
                    "--hkjc-overseas-end-date",
                    "2026-06-20",
                    "--request-interval-seconds",
                    "0",
                    "--max-requests",
                    "4",
                    "--output-dir",
                    str(output_dir),
                    stdout=out,
                )

            rows = self._read_csv(output_dir / "seed_candidates.csv")
            by_source = {row["source_ja"]: row for row in rows}
            self.assertEqual(by_source["ROYAL ASCOT"]["target_zh"], "皇家雅士谷")
            self.assertNotIn("ROYAL ASCOT (GB)", by_source)
            self.assertEqual(by_source["BLUE POINT"]["target_zh"], "蓝点")
            self.assertEqual(by_source["William Buick"]["target_zh"], "布宜学")
            self.assertEqual(by_source["King Charles III Stakes"]["target_zh"], "英皇查理斯三世锦标")
            self.assertTrue(all(row["racing_region"] == RacingRegion.UNITED_KINGDOM for row in rows))

            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            evidence = json.loads((output_dir / "source_evidence.json").read_text(encoding="utf-8"))
            self.assertFalse(summary["incomplete"])
            self.assertEqual(summary["request_count"], 2)
            royal_ascot = next(item for item in evidence["candidates"] if item["source_text"] == "ROYAL ASCOT")
            self.assertEqual(royal_ascot["fetch_mode"], "qids_graphql")
            self.assertEqual(royal_ascot["horse_profile"]["simulcastHorseId"], "GB001")
            self.assertEqual(royal_ascot["entity_key"], "hkjc_overseas:horse:gb001")
            self.assertIn("entity_key=hkjc_overseas:horse:gb001", by_source["ROYAL ASCOT"]["notes"])

    def test_hkjc_overseas_qids_uses_global_entity_key_for_duplicate_english_horse_names(self):
        class TextResponse:
            status_code = 200
            encoding = "utf-8"

            def __init__(self, url: str, text: str):
                self.url = url
                self.text = text

        class JsonResponse:
            status_code = 200
            url = "https://info.cld.hkjc.com/graphql/base/"

            def json(self):
                return {
                    "data": {
                        "raceMeetingProfile": [
                            {
                                "date": "2026-06-20",
                                "venueCode": "S5",
                                "races": [
                                    {
                                        "no": 1,
                                        "raceName_en": "Duplicate Test Stakes",
                                        "raceName_ch": "重名測試錦標",
                                        "countryCodeNm": {"code": "GB", "english": "United Kingdom", "chinese": "英國"},
                                        "runners": [
                                            {
                                                "no": "1",
                                                "horse": {"id": "GB001", "name_en": "DUPLICATE NAME", "name_ch": "第一重名"},
                                                "jockey": {"code": "RM", "name_en": "Ryan Moore", "name_ch": "莫雅"},
                                            },
                                            {
                                                "no": "2",
                                                "horse": {"id": "GB002", "name_en": "DUPLICATE NAME", "name_ch": "第二重名"},
                                                "jockey": {"code": "WB", "name_en": "William Buick", "name_ch": "布宜學"},
                                            },
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }

        def fake_get(url, **_kwargs):
            return TextResponse(
                url,
                '<a href="/en-us/overseas/results?RaceDate=20260620&Racecourse=S5">Overseas Results</a>',
            )

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with patch("stable.services.termbase_seed.requests.get", side_effect=fake_get), patch(
                "stable.services.termbase_seed.requests.post", return_value=JsonResponse()
            ):
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc_overseas",
                    "--allow-network",
                    "--hkjc-overseas-start-date",
                    "2026-06-20",
                    "--hkjc-overseas-end-date",
                    "2026-06-20",
                    "--request-interval-seconds",
                    "0",
                    "--max-requests",
                    "4",
                    "--output-dir",
                    str(output_dir),
                    stdout=StringIO(),
                )

            rows = [row for row in self._read_csv(output_dir / "seed_candidates.csv") if row["source_ja"] == "DUPLICATE NAME"]
            self.assertEqual([row["target_zh"] for row in rows], ["第一重名", "第二重名"])
            self.assertIn("entity_key=hkjc_overseas:horse:gb001", rows[0]["notes"])
            self.assertIn("entity_key=hkjc_overseas:horse:gb002", rows[1]["notes"])
            evidence = json.loads((output_dir / "source_evidence.json").read_text(encoding="utf-8"))
            duplicate_evidence = [item for item in evidence["candidates"] if item["source_text"] == "DUPLICATE NAME"]
            self.assertEqual({item["entity_key"] for item in duplicate_evidence}, {"hkjc_overseas:horse:gb001", "hkjc_overseas:horse:gb002"})

    def test_hkjc_overseas_qids_maps_ire_and_can_to_other(self):
        from stable.services.termbase_seed import build_seed_result, parse_hkjc_overseas_race_key
        from stable.services.termbase_seed import _records_from_hkjc_overseas_qids_meeting

        race_key = parse_hkjc_overseas_race_key("RaceDate=2026-06-20,Racecourse=S5,RaceNo=0")
        records = _records_from_hkjc_overseas_qids_meeting(
            {},
            races=[
                {
                    "no": 1,
                    "raceName_en": "Irish Stakes",
                    "raceName_ch": "愛爾蘭錦標",
                    "countryCodeNm": {"code": "IRE", "english": "Ireland", "chinese": "愛爾蘭"},
                    "runners": [{"no": "1", "horse": {"id": "IRE001", "name_en": "IRISH HORSE", "name_ch": "愛爾蘭馬"}}],
                },
                {
                    "no": 2,
                    "raceName_en": "Canadian Stakes",
                    "raceName_ch": "加拿大錦標",
                    "countryCodeNm": {"code": "CAN", "english": "Canada", "chinese": "加拿大"},
                    "runners": [{"no": "1", "horse": {"id": "CAN001", "name_en": "CANADIAN HORSE", "name_ch": "加拿大馬"}}],
                },
            ],
            race_key=race_key,
        )
        result = build_seed_result(records)

        by_source = {row["source_ja"]: row for row in result.candidates}
        self.assertEqual(by_source["IRISH HORSE"]["racing_region"], RacingRegion.OTHER)
        self.assertEqual(by_source["CANADIAN HORSE"]["racing_region"], RacingRegion.OTHER)

    def test_hkjc_overseas_qids_limits_merged_evidence_samples(self):
        class TextResponse:
            status_code = 200
            encoding = "utf-8"

            def __init__(self, url: str, text: str):
                self.url = url
                self.text = text

        class JsonResponse:
            status_code = 200
            url = "https://info.cld.hkjc.com/graphql/base/"

            def json(self):
                return {
                    "data": {
                        "raceMeetingProfile": [
                            {
                                "date": "2026-06-20",
                                "venueCode": "S5",
                                "races": [
                                    {
                                        "no": race_no,
                                        "raceName_en": f"Evidence Race {race_no}",
                                        "raceName_ch": f"證據賽{race_no}",
                                        "countryCodeNm": {"code": "GB", "english": "United Kingdom", "chinese": "英國"},
                                        "runners": [
                                            {
                                                "no": "1",
                                                "horse": {"id": f"GB{race_no:03d}", "name_en": f"HORSE {race_no}", "name_ch": f"馬{race_no}"},
                                                "jockey": {"code": "RM", "name_en": "Ryan Moore", "name_ch": "莫雅"},
                                            }
                                        ],
                                    }
                                    for race_no in range(1, 13)
                                ],
                            }
                        ]
                    }
                }

        def fake_get(url, **_kwargs):
            return TextResponse(
                url,
                '<a href="/en-us/overseas/results?RaceDate=20260620&Racecourse=S5">Overseas Results</a>',
            )

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            with patch("stable.services.termbase_seed.requests.get", side_effect=fake_get), patch(
                "stable.services.termbase_seed.requests.post", return_value=JsonResponse()
            ):
                call_command(
                    "prepare_termbase_seed_data",
                    "--source",
                    "hkjc_overseas",
                    "--allow-network",
                    "--hkjc-overseas-start-date",
                    "2026-06-20",
                    "--hkjc-overseas-end-date",
                    "2026-06-20",
                    "--request-interval-seconds",
                    "0",
                    "--max-requests",
                    "4",
                    "--output-dir",
                    str(output_dir),
                    stdout=StringIO(),
                )

            evidence = json.loads((output_dir / "source_evidence.json").read_text(encoding="utf-8"))
            ryan_moore = next(item for item in evidence["candidates"] if item["source_text"] == "Ryan Moore")
            self.assertEqual(len(ryan_moore["evidence_samples"]), 10)
            self.assertEqual([sample["race_key"]["RaceNo"] for sample in ryan_moore["evidence_samples"]], [str(item) for item in range(1, 11)])

    def test_prepare_seed_command_records_hkjc_overseas_unavailable_race_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "fixtures"
            output_dir = root / "out"
            self._write_fixture(
                input_dir,
                "hkjc_overseas_unavailable_en.html",
                """
                <html lang="en"><body>
                  <main data-hkjc-overseas-racecard="true" data-race-date="2026-06-20" data-racecourse="S5" data-race-no="2" data-source-url="https://racing.hkjc.com/en-us/overseas/racecard?RaceDate=20260620&Racecourse=S5&RaceNo=2">
                    No race information
                  </main>
                </body></html>
                """,
            )
            self._write_fixture(
                input_dir,
                "hkjc_overseas_unavailable_zh.html",
                """
                <html lang="zh-hk"><body>
                  <main data-hkjc-overseas-racecard="true" data-race-date="2026-06-20" data-racecourse="S5" data-race-no="2" data-source-url="https://racing.hkjc.com/zh-hk/overseas/racecard?RaceDate=20260620&Racecourse=S5&RaceNo=2">
                    未有資料
                  </main>
                </body></html>
                """,
            )

            out = StringIO()
            call_command(
                "prepare_termbase_seed_data",
                "--source",
                "hkjc_overseas",
                "--input-dir",
                str(input_dir),
                "--output-dir",
                str(output_dir),
                stdout=out,
            )

            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertFalse(summary["incomplete"])
            self.assertEqual(summary["skipped_races"][0]["error"], "race_card_not_available")

    def test_prepare_seed_command_extracts_wpstud_race_jockey_and_racecourse_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "fixtures"
            output_dir = root / "out"
            self._write_fixture(
                input_dir,
                "wpstud_raceuk.htm",
                """
                <html><body><h1>英國</h1>
                  <table>
                    <tr><th>賽事日文名稱</th><th>賽事英文名稱</th><th>賽事中文名稱</th><th>級數</th></tr>
                    <tr><td>ダービーS</td><td>Derby Stakes</td><td>英國打吡大賽</td><td>I</td></tr>
                  </table>
                </body></html>
                """,
            )
            self._write_fixture(
                input_dir,
                "wpstud_jockey.htm",
                """
                <html><body><h1>騎師日－英－中對照翻譯</h1>
                  <table>
                    <tr><th>日文</th><th>英文</th><th>中文</th><th>出生地</th><th>據點</th></tr>
                    <tr><td>ライアン・ムーア</td><td>Ryan Moore</td><td>莫雅</td><td>英國</td><td>英國</td></tr>
                  </table>
                </body></html>
                """,
            )
            self._write_fixture(
                input_dir,
                "wpstud_racecourse.htm",
                """
                <html><body><h1>馬場中－英－日對照</h1>
                  <table>
                    <tr><th>馬場中文名稱</th><th>所在國家／地區</th><th>馬場英文名稱</th><th>馬場日文名稱</th></tr>
                    <tr><td>沙田</td><td>香港</td><td>Sha Tin</td><td>シャティン</td></tr>
                  </table>
                </body></html>
                """,
            )
            self._write_fixture(
                input_dir,
                "wpstud_horselist.html",
                """
                <html><body><h1>馬名日－英－中對照翻譯</h1>
                  <table>
                    <tr><th>日文馬名</th><th>英文馬名</th><th>中文馬名</th><th>原產地</th><th>代表地區</th></tr>
                    <tr><td>イクイノックス</td><td>Equinox</td><td>春秋分</td><td>日本</td><td>日本</td></tr>
                  </table>
                </body></html>
                """,
            )

            out = StringIO()
            call_command(
                "prepare_termbase_seed_data",
                "--source",
                "wpstud",
                "--input-dir",
                str(input_dir),
                "--output-dir",
                str(output_dir),
                stdout=out,
            )

            rows = self._read_csv(output_dir / "seed_candidates.csv")
            by_source = {row["source_ja"]: row for row in rows}
            self.assertEqual(by_source["Derby Stakes"]["term_type"], TermType.RACE)
            self.assertEqual(by_source["Derby Stakes"]["target_zh"], "英国打吡大赛")
            self.assertEqual(by_source["Derby Stakes"]["racing_region"], RacingRegion.UNITED_KINGDOM)
            self.assertEqual(by_source["Derby Stakes"]["race_grade"], "G1")
            self.assertEqual(by_source["Ryan Moore"]["term_type"], TermType.JOCKEY)
            self.assertEqual(by_source["Ryan Moore"]["racing_region"], RacingRegion.UNITED_KINGDOM)
            self.assertEqual(by_source["Sha Tin"]["term_type"], TermType.RACECOURSE)
            self.assertEqual(by_source["Sha Tin"]["racing_region"], RacingRegion.HONG_KONG)
            self.assertEqual(by_source["イクイノックス"]["term_type"], TermType.HORSE)
            self.assertEqual(by_source["イクイノックス"]["source_language"], SourceLanguage.JAPANESE)
            self.assertEqual(by_source["イクイノックス"]["aliases_ja"], "Equinox")
            self.assertEqual(by_source["イクイノックス"]["target_zh"], "春秋分")
            self.assertEqual(by_source["イクイノックス"]["racing_region"], RacingRegion.JAPAN)
            self.assertTrue(all("source_tier=community" in row["notes"] for row in rows))


class RaceEventPageMVPTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="race-admin", password="pass", is_staff=True)
        self.event = RaceEvent.objects.create(
            year=2026,
            slug="takarazuka-kinen",
            original_name="Takarazuka Kinen",
            chinese_name="宝塚纪念",
            country_region=RacingRegion.JAPAN,
            racecourse="阪神竞马场",
            grade_text="G1",
            normalized_grade=RaceGrade.G1,
            surface="turf",
            distance_text="2200m",
            eligibility_text="3岁以上",
            local_date=timezone.localdate(),
            local_start_time=datetime.strptime("15:40", "%H:%M").time(),
            priority=RaceEventPriority.P0,
            status=RaceEventStatus.SCHEDULED,
            visibility_status=RaceEventVisibility.PUBLISHED,
        )
        RaceEventAlias.objects.create(event=self.event, text="宝冢纪念", source_language=SourceLanguage.CHINESE)

    def _article(self, **overrides):
        payload = {
            "source_site": SourceSite.NETKEIBA,
            "source_mode": SourceMode.LATEST,
            "source_article_id": f"race-article-{uuid.uuid4()}",
            "title_ja": "宝塚纪念出马表公布",
            "body_ja_raw": "宝塚纪念的出马表已经公布。",
            "body_ja_normalized": "宝塚纪念的出马表已经公布。",
            "title_zh": "宝塚纪念出马表公布",
            "summary_zh": "宝塚纪念相关消息。",
            "body_zh": "宝塚纪念相关消息。",
            "published_at": timezone.now(),
            "published_to_web_at": timezone.now(),
            "source_url": f"https://example.com/{uuid.uuid4()}",
            "workflow_status": WorkflowStatus.PUBLISHED,
            "content_category": ContentCategory.PRE_RACE,
        }
        payload.update(overrides)
        return NewsArticle.objects.create(**payload)

    def test_public_calendar_hides_non_public_events_and_never_shows_odds(self):
        RaceEventRunner.objects.create(event=self.event, horse_number="1", horse_name="贝拉吉奥歌剧", odds_value="3.5")
        RaceEvent.objects.create(
            year=2026,
            slug="hidden-race",
            original_name="Hidden Race",
            chinese_name="隐藏赛事",
            country_region=RacingRegion.JAPAN,
            racecourse="东京竞马场",
            grade_text="G1",
            surface="turf",
            local_date=timezone.localdate(),
            visibility_status=RaceEventVisibility.HIDDEN,
        )

        response = self.client.get(reverse("public-race-calendar"), {"tab": "all", "direction": "future", "cursor": "2026-06-28"})

        self.assertContains(response, "宝塚纪念")
        self.assertNotContains(response, "隐藏赛事")
        self.assertNotContains(response, "3.5")

    def test_public_calendar_uses_term_name_for_top_results(self):
        self.event.status = RaceEventStatus.FINISHED
        self.event.save(update_fields=["status", "updated_at"])
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            source_ja="ロブチェン",
            target_zh="凌驾",
        )
        RaceEventResult.objects.create(event=self.event, finish_position=1, horse_name="ロブチェン")

        response = self.client.get(
            reverse("public-race-calendar"),
            {"tab": "all", "direction": "future", "cursor": "2026-06-28"},
        )

        self.assertContains(response, "凌驾")

    def test_public_detail_shows_runner_odds_results_and_article_backlink(self):
        RaceEventRunner.objects.create(event=self.event, horse_number="1", horse_name="贝拉吉オ歌剧", odds_value="3.5", popularity="1")
        RaceEventResult.objects.create(event=self.event, finish_position=1, horse_name="贝拉吉オ歌剧", margin="颈位")
        article = self._article()
        ArticleRaceLink.objects.create(
            event=self.event,
            article=article,
            status=ArticleRaceLinkStatus.MANUAL,
            link_type=ArticleRaceLinkType.PRE_RACE,
            confidence=100,
        )

        detail = self.client.get(self.event.public_path)
        article_detail = self.client.get(article.public_path)

        self.assertContains(detail, "3.5")
        self.assertContains(detail, "颈位")
        self.assertContains(detail, "赛前新闻")
        self.assertContains(article_detail, "关联赛事")
        self.assertContains(article_detail, "宝塚纪念 2026")

    def test_public_detail_uses_region_term_names_for_runners_results_and_history(self):
        global_horse = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            source_ja="ロブチェン",
            target_zh="全局译名",
            priority=100,
        )
        TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            source_ja="ロブチェン",
            target_zh="凌驾",
            priority=10,
        )
        jockey = TermEntry.objects.create(
            term_type=TermType.JOCKEY,
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            source_ja="松山弘平",
            target_zh="松山弘平",
        )
        TermAlias.objects.create(
            term=jockey,
            source_language=SourceLanguage.JAPANESE,
            text="松山 弘平",
        )
        RaceEventRunner.objects.create(
            event=self.event,
            horse_number="17",
            horse_name="ロブチェン",
            jockey_name="松山 弘平",
        )
        RaceEventResult.objects.create(
            event=self.event,
            finish_position=1,
            horse_number="17",
            horse_name="ロブチェン",
            jockey_name="松山 弘平",
        )
        RaceEventHistoryWinner.objects.create(
            event=self.event,
            winner_year=2025,
            horse_name="ロブチェン",
            jockey_name="松山 弘平",
        )

        detail = self.client.get(self.event.public_path)

        self.assertContains(detail, "凌驾", count=3)
        self.assertContains(detail, "松山弘平", count=3)
        self.assertNotContains(detail, "全局译名")
        self.assertEqual(global_horse.racing_region, "")
        self.assertEqual(detail.context["results"][0].display_horse_name, "凌驾")

    def test_public_detail_sorts_runners_by_natural_horse_number_then_barrier(self):
        RaceEventRunner.objects.create(event=self.event, sort_order=1, horse_number="17", barrier="8", horse_name="第十七号")
        RaceEventRunner.objects.create(event=self.event, sort_order=2, horse_number="2", barrier="1", horse_name="第二号")
        RaceEventRunner.objects.create(event=self.event, sort_order=3, horse_number="10", barrier="5", horse_name="第十号")
        RaceEventRunner.objects.create(event=self.event, sort_order=4, horse_number="1A", barrier="1", horse_name="第一号A")
        RaceEventRunner.objects.create(event=self.event, sort_order=5, horse_number="", barrier="3", horse_name="闸位回退")

        detail = self.client.get(self.event.public_path)

        self.assertEqual(
            [runner.horse_name for runner in detail.context["runners"]],
            ["第一号A", "第二号", "闸位回退", "第十号", "第十七号"],
        )

    def test_public_detail_keeps_original_name_when_no_active_term_matches(self):
        RaceEventResult.objects.create(
            event=self.event,
            finish_position=1,
            horse_name="未收录马名",
            jockey_name="未收录骑师",
        )

        detail = self.client.get(self.event.public_path)

        self.assertEqual(detail.context["results"][0].display_horse_name, "未收录马名")
        self.assertEqual(detail.context["results"][0].display_jockey_name, "未收录骑师")

    def test_public_detail_prefers_official_finish_position_for_dead_heats(self):
        self.event.status = RaceEventStatus.FINISHED
        self.event.save(update_fields=["status", "updated_at"])
        RaceEventResult.objects.create(event=self.event, finish_position=2, horse_name="ワールズエンド", source_refs={"official_finish_position": 2})
        RaceEventResult.objects.create(event=self.event, finish_position=3, horse_name="ガイアフォース", margin="同着", source_refs={"official_finish_position": 2})

        detail = self.client.get(self.event.public_path)

        self.assertContains(detail, "<td>2</td>", count=2, html=True)
        self.assertContains(detail, "ガイアフォース")
        self.assertContains(detail, "同着")

    def test_public_detail_hides_race_links_for_articles_not_published_to_web(self):
        article = self._article(
            source_article_id="race-linked-but-not-web",
            title_zh="不应出现在赛事页",
            published_to_web_at=None,
        )
        ArticleRaceLink.objects.create(
            event=self.event,
            article=article,
            status=ArticleRaceLinkStatus.MANUAL,
            link_type=ArticleRaceLinkType.RELATED,
            confidence=100,
        )

        detail = self.client.get(self.event.public_path)

        self.assertNotContains(detail, "不应出现在赛事页")

    def test_candidate_apply_supports_history_winners_and_news_links(self):
        article = self._article(title_zh="宝塚纪念赛前焦点")
        removed_article = self._article(title_zh="已人工移除的关联")
        removed_link = ArticleRaceLink.objects.create(
            event=self.event,
            article=removed_article,
            status=ArticleRaceLinkStatus.REMOVED,
            link_type=ArticleRaceLinkType.RELATED,
            confidence=80,
        )
        history_candidate = RaceEventDataCandidate.objects.create(
            event=self.event,
            module=RaceEventModule.HISTORY_WINNERS,
            source_name="fixture",
            candidate_payload={
                "items": [
                    {
                        "winner_year": 2025,
                        "horse_name": "贝拉吉奥歌剧",
                        "jockey_name": "横山和生",
                        "finish_time": "2:10.0",
                    }
                ]
            },
        )
        news_candidate = RaceEventDataCandidate.objects.create(
            event=self.event,
            module=RaceEventModule.NEWS_LINKS,
            source_name="fixture",
            candidate_payload={
                "items": [
                    {"article_id": article.id, "link_type": ArticleRaceLinkType.PRE_RACE, "confidence": 88},
                    {"article_id": removed_article.id, "link_type": ArticleRaceLinkType.RELATED, "confidence": 88},
                ]
            },
        )

        history_summary = apply_data_candidate(history_candidate, user=self.user)
        news_summary = apply_data_candidate(news_candidate, user=self.user)
        removed_link.refresh_from_db()

        self.assertEqual(history_summary["created_count"], 1)
        self.assertTrue(RaceEventHistoryWinner.objects.filter(event=self.event, winner_year=2025, horse_name="贝拉吉奥歌剧").exists())
        self.assertEqual(news_summary["created_count"], 1)
        self.assertEqual(news_summary["skipped_removed"], 1)
        self.assertTrue(
            ArticleRaceLink.objects.filter(
                event=self.event,
                article=article,
                status=ArticleRaceLinkStatus.MANUAL,
                link_type=ArticleRaceLinkType.PRE_RACE,
            ).exists()
        )
        self.assertEqual(removed_link.status, ArticleRaceLinkStatus.REMOVED)

    def test_candidate_apply_strips_trailing_horse_country_suffixes(self):
        runner_candidate = RaceEventDataCandidate.objects.create(
            event=self.event,
            module=RaceEventModule.RUNNERS,
            source_name="fixture",
            candidate_payload={
                "items": [
                    {"horse_number": "1", "horse_name": "Calandagan (IRE)", "jockey_name": "Mickael Barzalona"}
                ]
            },
        )
        result_candidate = RaceEventDataCandidate.objects.create(
            event=self.event,
            module=RaceEventModule.RESULTS,
            source_name="fixture",
            candidate_payload={
                "items": [
                    {"finish_position": 1, "horse_number": "1", "horse_name": "Calandagan (IRE)", "jockey_name": "Mickael Barzalona"}
                ]
            },
        )
        history_candidate = RaceEventDataCandidate.objects.create(
            event=self.event,
            module=RaceEventModule.HISTORY_WINNERS,
            source_name="fixture",
            candidate_payload={
                "items": [
                    {"winner_year": 2025, "horse_name": "Masquerade Ball（JPN）", "jockey_name": "Christophe Lemaire"}
                ]
            },
        )

        apply_data_candidate(runner_candidate, user=self.user)
        apply_data_candidate(result_candidate, user=self.user)
        apply_data_candidate(history_candidate, user=self.user)
        update_result = update_runner_dynamic_fields(
            self.event,
            [{"horse_name": "Calandagan (IRE)", "odds_value": "2.1"}],
            source_name="fixture",
        )

        self.assertTrue(RaceEventRunner.objects.filter(event=self.event, horse_name="Calandagan").exists())
        self.assertFalse(RaceEventRunner.objects.filter(event=self.event, horse_name__contains="(IRE)").exists())
        self.assertTrue(RaceEventResult.objects.filter(event=self.event, horse_name="Calandagan").exists())
        self.assertTrue(RaceEventHistoryWinner.objects.filter(event=self.event, horse_name="Masquerade Ball").exists())
        self.assertEqual(update_result["updated"], 1)
        self.assertEqual(self.event.runners.get(horse_number="1").odds_value, "2.1")

    def test_import_race_event_detail_candidates_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "details.jsonl"
            payload_path.write_text(
                json.dumps(
                    {
                        "year": self.event.year,
                        "slug": self.event.slug,
                        "source_name": "fixture",
                        "modules": {
                            RaceEventModule.RUNNERS: {
                                "items": [{"horse_number": "1", "horse_name": "Calandagan (IRE)"}]
                            },
                            RaceEventModule.RESULTS: {
                                "items": [{"finish_position": 1, "horse_name": "Calandagan (IRE)"}]
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            out = StringIO()

            call_command("import_race_event_detail_candidates", "--jsonl", str(payload_path), "--dry-run", stdout=out)

        self.assertIn("dry-run 通过", out.getvalue())
        self.assertFalse(RaceEventDataCandidate.objects.filter(event=self.event).exists())
        self.assertFalse(RaceEventRunner.objects.filter(event=self.event).exists())
        self.assertFalse(RaceEventResult.objects.filter(event=self.event).exists())

    def test_import_race_event_detail_candidates_can_apply_runners_and_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "details.jsonl"
            payload_path.write_text(
                json.dumps(
                    {
                        "year": self.event.year,
                        "slug": self.event.slug,
                        "source_name": "fixture",
                        "source_url": "https://example.com/result.html",
                        "modules": {
                            RaceEventModule.RUNNERS: {
                                "items": [
                                    {
                                        "sort_order": 1,
                                        "horse_number": "1",
                                        "barrier": "7",
                                        "horse_name": "Calandagan (IRE)",
                                        "jockey_name": "Mickael Barzalona",
                                        "carried_weight": "58.0",
                                    }
                                ]
                            },
                            RaceEventModule.RESULTS: {
                                "items": [
                                    {
                                        "finish_position": 1,
                                        "horse_number": "1",
                                        "barrier": "7",
                                        "horse_name": "Calandagan (IRE)",
                                        "jockey_name": "Mickael Barzalona",
                                        "finish_time": "2:22.1",
                                        "is_confirmed": True,
                                    }
                                ]
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            call_command("import_race_event_detail_candidates", "--jsonl", str(payload_path), "--apply", stdout=StringIO())

        self.assertEqual(RaceEventDataCandidate.objects.filter(event=self.event, status="applied").count(), 2)
        self.assertTrue(RaceEventRunner.objects.filter(event=self.event, horse_name="Calandagan", barrier="7").exists())
        self.assertTrue(RaceEventResult.objects.filter(event=self.event, horse_name="Calandagan", finish_time="2:22.1").exists())

    def test_import_race_event_detail_candidates_rolls_back_the_whole_batch_on_apply_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "details.jsonl"
            payload_path.write_text(
                json.dumps(
                    {
                        "year": self.event.year,
                        "slug": self.event.slug,
                        "source_name": "fixture",
                        "source_url": "https://example.com/result.html",
                        "modules": {
                            RaceEventModule.RUNNERS: {
                                "items": [{"horse_number": "1", "horse_name": "Calandagan"}]
                            },
                            RaceEventModule.RESULTS: {
                                "items": [{"finish_position": "invalid", "horse_name": "Calandagan"}]
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                call_command(
                    "import_race_event_detail_candidates",
                    "--jsonl",
                    str(payload_path),
                    "--apply",
                    stdout=StringIO(),
                )

        self.assertFalse(RaceEventDataCandidate.objects.filter(event=self.event).exists())
        self.assertFalse(RaceEventRunner.objects.filter(event=self.event).exists())
        self.assertFalse(RaceEventResult.objects.filter(event=self.event).exists())

    def test_dynamic_field_update_and_removed_article_link_protection(self):
        RaceEventRunner.objects.create(event=self.event, horse_number="1", horse_name="贝拉吉奥歌剧", odds_value="4.0")
        update_result = update_runner_dynamic_fields(
            self.event,
            [{"horse_number": "1", "odds_value": "3.1", "popularity": "1", "running_status": RaceRunnerStatus.DECLARED}],
            source_name="fixture",
        )
        runner = self.event.runners.get(horse_number="1")
        article = self._article()
        first_result = associate_articles_for_event(self.event, articles=[article])
        link = ArticleRaceLink.objects.get(event=self.event, article=article)
        remove_article_link(link, user=self.user)
        second_result = associate_articles_for_event(self.event, articles=[article])
        link.refresh_from_db()

        self.assertEqual(update_result["updated"], 1)
        self.assertEqual(runner.odds_value, "3.1")
        self.assertEqual(first_result["created"], 1)
        self.assertEqual(second_result["skipped_removed"], 1)
        self.assertEqual(link.status, ArticleRaceLinkStatus.REMOVED)

    def test_auto_association_maps_current_content_categories_to_race_link_types(self):
        preview = self._article(content_category=ContentCategory.PREVIEW)
        result_brief = self._article(content_category=ContentCategory.RESULT_BRIEF)

        summary = associate_articles_for_event(self.event, articles=[preview, result_brief])

        self.assertEqual(summary["created"], 2)
        self.assertEqual(
            ArticleRaceLink.objects.get(event=self.event, article=preview).link_type,
            ArticleRaceLinkType.PRE_RACE,
        )
        self.assertEqual(
            ArticleRaceLink.objects.get(event=self.event, article=result_brief).link_type,
            ArticleRaceLinkType.POST_RACE,
        )

    def test_auto_association_does_not_overwrite_manual_article_link(self):
        article = self._article(content_category=ContentCategory.PRE_RACE)
        manual_link = ArticleRaceLink.objects.create(
            event=self.event,
            article=article,
            status=ArticleRaceLinkStatus.MANUAL,
            link_type=ArticleRaceLinkType.POST_RACE,
            confidence=100,
            match_reason="运营手动确认",
        )

        result = associate_articles_for_event(self.event, articles=[article])
        manual_link.refresh_from_db()

        self.assertEqual(result["skipped_manual"], 1)
        self.assertEqual(manual_link.status, ArticleRaceLinkStatus.MANUAL)
        self.assertEqual(manual_link.link_type, ArticleRaceLinkType.POST_RACE)
        self.assertEqual(manual_link.match_reason, "运营手动确认")

    def test_csv_import_candidate_fetch_and_candidate_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "races.csv"
            csv_path.write_text(
                "year,slug,original_name,chinese_name,aliases,country_region,racecourse,grade_text,normalized_grade,surface,local_date,priority,visibility_status\n"
                "2026,hong-kong-cup,Hong Kong Cup,香港杯,Hong Kong Cup|HK Cup,hong_kong,沙田马场,G1,G1,turf,2026-12-13,P0,published\n",
                encoding="utf-8",
            )
            call_command("import_race_events", "--csv", str(csv_path), stdout=StringIO())
            event = RaceEvent.objects.get(slug="hong-kong-cup")
            payload_path = Path(tmp) / "candidate.json"
            payload_path.write_text(
                json.dumps({"modules": {"basic": {"distance_text": "2000m", "eligibility_text": "3岁以上"}}}),
                encoding="utf-8",
            )
            call_command(
                "fetch_race_event_candidates",
                "--event-id",
                str(event.id),
                "--source",
                "json",
                "--payload-file",
                str(payload_path),
                stdout=StringIO(),
            )
            candidate = RaceEventDataCandidate.objects.get(event=event, module=RaceEventModule.BASIC)
            apply_data_candidate(candidate, user=self.user)
            event.refresh_from_db()

        self.assertEqual(event.distance_text, "2000m")
        self.assertTrue(event.aliases.filter(text="HK Cup", is_active=True).exists())
        self.assertEqual(candidate.status, "applied")

    def test_csv_import_dry_run_rejects_invalid_choice_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "invalid-races.csv"
            csv_path.write_text(
                "year,slug,original_name,chinese_name,country_region,racecourse,grade_text,surface,priority\n"
                "2026,bad-race,Bad Race,错误赛事,japan,东京竞马场,G1,grass,P9\n",
                encoding="utf-8",
            )

            with self.assertRaises(CommandError) as context:
                call_command("import_race_events", "--csv", str(csv_path), "--dry-run", stdout=StringIO())

        self.assertIn("第 2 行字段校验失败", str(context.exception))
        self.assertFalse(RaceEvent.objects.filter(slug="bad-race").exists())

    def test_csv_import_supports_synthetic_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "synthetic-races.csv"
            csv_path.write_text(
                "year,slug,original_name,chinese_name,country_region,racecourse,grade_text,surface,local_date,visibility_status\n"
                "2026,synthetic-stakes,Synthetic Stakes,Synthetic Stakes,united_states,Turfway Park,G3,synthetic,2026-03-21,published\n",
                encoding="utf-8",
            )
            call_command("import_race_events", "--csv", str(csv_path), stdout=StringIO())

        event = RaceEvent.objects.get(slug="synthetic-stakes")
        response = self.client.get(reverse("public-race-detail", args=[event.year, event.slug]))

        self.assertEqual(event.surface, RaceEventSurface.SYNTHETIC)
        self.assertContains(response, "复合赛道")

    def test_seed_sample_import_covers_five_regions_and_calendar_visibility(self):
        sample_path = Path(django_settings.BASE_DIR) / "stable" / "data" / "race_events_seed_sample.csv"
        call_command("import_race_events", "--csv", str(sample_path), stdout=StringIO())

        regions = set(RaceEvent.objects.exclude(slug="takarazuka-kinen").values_list("country_region", flat=True))
        response = self.client.get(reverse("public-race-calendar"), {"tab": "all", "direction": "future", "cursor": "2026-06-28"})

        self.assertTrue(
            {
                RacingRegion.HONG_KONG,
                RacingRegion.UNITED_KINGDOM,
                RacingRegion.FRANCE,
                RacingRegion.UNITED_STATES,
            }.issubset(regions)
        )
        self.assertContains(response, "凯旋门大赛")
        self.assertContains(response, "香港杯")

    def test_console_race_event_workbench_supports_filters_and_manual_link(self):
        self.client.force_login(self.user)
        article = self._article()

        list_response = self.client.get(reverse("console-race-event-list"), {"priority": RaceEventPriority.P0})
        detail_response = self.client.get(reverse("console-race-event-edit", args=[self.event.id]))
        post_response = self.client.post(
            reverse("console-race-event-link-article", args=[self.event.id]),
            {"article_id": str(article.id), "link_type": ArticleRaceLinkType.RELATED},
            follow=True,
        )

        self.assertContains(list_response, "宝塚纪念")
        self.assertContains(detail_response, "候选资料确认")
        self.assertContains(post_response, "文章已关联到赛事")
        self.assertTrue(ArticleRaceLink.objects.filter(event=self.event, article=article, status=ArticleRaceLinkStatus.MANUAL).exists())

    def test_console_race_event_list_pagination_preserves_filters(self):
        self.client.force_login(self.user)
        for index in range(50):
            RaceEvent.objects.create(
                year=2026,
                slug=f"filtered-race-{index}",
                original_name=f"Filtered Race {index}",
                chinese_name=f"筛选赛事 {index}",
                country_region=RacingRegion.JAPAN,
                racecourse="东京竞马场",
                grade_text="G1",
                surface="turf",
                local_date=timezone.localdate() + timedelta(days=index + 1),
                priority=RaceEventPriority.P0,
                visibility_status=RaceEventVisibility.PUBLISHED,
            )

        response = self.client.get(
            reverse("console-race-event-list"),
            {"priority": RaceEventPriority.P0, "region": RacingRegion.JAPAN},
        )

        self.assertContains(response, "priority=P0&amp;region=japan&amp;page=2")

    def test_calendar_query_count_stays_bounded_for_initial_window(self):
        for index in range(8):
            RaceEvent.objects.create(
                year=2026,
                slug=f"race-{index}",
                original_name=f"Race {index}",
                chinese_name=f"测试赛事 {index}",
                country_region=RacingRegion.JAPAN,
                racecourse="东京竞马场",
                grade_text="G1",
                surface="turf",
                local_date=timezone.localdate() + timedelta(days=index),
                visibility_status=RaceEventVisibility.PUBLISHED,
            )
        with CaptureQueriesContext(connection) as context:
            response = self.client.get(reverse("public-race-calendar"), {"tab": "all"})

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(context), 8)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class HorseProfilePageMvpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="editor", password="pass", is_staff=True)

    def _term(self, source_ja="イクイノックス", target_zh="春秋分", priority=100, region=RacingRegion.JAPAN):
        return TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            source_ja=source_ja,
            target_zh=target_zh,
            racing_region=region,
            priority=priority,
            is_active=True,
        )

    def _profile(self, **overrides):
        term = overrides.pop("primary_term", None) or self._term()
        defaults = {
            "primary_term": term,
            "display_name_zh": term.target_zh,
            "original_name": term.source_ja,
            "racing_region": term.racing_region,
            "review_status": HorseProfileStatus.PUBLISHED,
        }
        defaults.update(overrides)
        return HorseProfile.objects.create(**defaults)

    def _article(self, title="春秋分胜出宝塚纪念", body="春秋分在比赛中表现出色。"):
        now = timezone.now()
        return NewsArticle.objects.create(
            source_site=SourceSite.NETKEIBA,
            source_mode=SourceMode.LATEST,
            racing_region=RacingRegion.JAPAN,
            source_language=SourceLanguage.JAPANESE,
            source_article_id=str(uuid.uuid4()),
            title_ja=title,
            body_ja_raw=body,
            body_ja_normalized=body,
            title_zh=title,
            summary_zh="摘要",
            body_zh=body,
            published_at=now,
            published_to_web_at=now,
            source_url="https://example.com/news",
            workflow_status=WorkflowStatus.PUBLISHED,
        )

    def test_p0_generation_is_draft_and_public_requires_manual_publish(self):
        term = self._term()
        result = generate_p0_horse_profiles()
        profile = HorseProfile.objects.get(primary_term=term)
        draft_response = self.client.get(reverse("public-horse-detail", args=[profile.id]))
        self.client.force_login(self.user)
        transition_response = self.client.post(
            reverse("console-horse-profile-status", args=[profile.id]),
            {"status": HorseProfileStatus.PUBLISHED, "note": "允许空壳强制发布"},
            follow=True,
        )
        published_response = self.client.get(reverse("public-horse-detail", args=[profile.id]))

        self.assertEqual(result["created"], 1)
        self.assertEqual(profile.review_status, HorseProfileStatus.DRAFT)
        self.assertEqual(draft_response.status_code, 404)
        self.assertEqual(transition_response.status_code, 200)
        self.assertContains(published_response, "春秋分")

    def test_horse_index_uses_horse_empty_copy(self):
        response = self.client.get(reverse("public-horse-index"))

        self.assertContains(response, "目前还没有已发布马匹资料。")
        self.assertNotContains(response, "目前还没有已发布文章。")

    def test_completeness_requires_all_six_pedigree_fields_and_descendants_use_profile_links(self):
        parent = self._profile(sire_text="父", dam_text="母", sire_sire_text="父父", sire_dam_text="父母", dam_sire_text="母父")
        self.assertEqual(update_completeness(parent), HorseProfileCompleteness.PARTIAL_PEDIGREE)
        parent.dam_dam_text = "母母"
        parent.save(update_fields=["dam_dam_text"])
        self.assertEqual(update_completeness(parent), HorseProfileCompleteness.COMPLETE_PEDIGREE_2GEN)

        child = self._profile(primary_term=self._term("キタサンブラック", "北部玄驹"), sire_horse_profile=parent)
        grandchild = self._profile(primary_term=self._term("イクイノックス2", "子代马"), dam_horse_profile=child)

        self.assertEqual(get_descendant_horse_ids(parent, depth=2, public_only=True), {child.id, grandchild.id})

    def test_major_win_records_choose_highest_grade_and_allow_manual_marks(self):
        profile = self._profile()
        g2 = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="札幌记念",
            normalized_grade=RaceGrade.G2,
            result_status=HorseRaceResultStatus.WON,
        )
        g1 = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="宝塚纪念",
            normalized_grade=RaceGrade.G1,
            result_status=HorseRaceResultStatus.WON,
        )
        manual = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="人工主胜鞍",
            normalized_grade=RaceGrade.G3,
            result_status=HorseRaceResultStatus.PLACED,
            is_major_win=True,
        )

        self.assertEqual(set(major_win_records(profile).values_list("id", flat=True)), {g1.id, manual.id})
        self.assertNotIn(g2.id, set(major_win_records(profile).values_list("id", flat=True)))

    def test_article_horse_scan_and_detail_tags_respect_removed_and_public_rules(self):
        profile = self._profile()
        article = self._article(
            title="イクイノックス宝塚記念勝利",
            body="イクイノックスはレースで好走した。",
        )
        result = scan_article_horse_links(article=article, commit=True)
        detail_response = self.client.get(reverse("public-article-detail", args=[article.id]))
        link = ArticleHorseLink.objects.get(article=article, horse_profile=profile)
        link.status = ArticleHorseLinkStatus.REMOVED
        link.save(update_fields=["status"])
        second = scan_article_horse_links(article=article, commit=True)
        removed_response = self.client.get(reverse("public-article-detail", args=[article.id]))

        self.assertEqual(result["created"], 1)
        self.assertContains(detail_response, profile.display_name)
        self.assertEqual(second["skipped_removed"], 1)
        self.assertNotContains(removed_response, profile.public_path)

    def test_anonymous_follow_stores_only_token_hash_and_feed_includes_descendant_news(self):
        parent = self._profile()
        child = self._profile(primary_term=self._term("キタサンブラック", "北部玄驹"), sire_horse_profile=parent)
        article = self._article(title="北部玄驹子嗣新闻", body="北部玄驹相关。")
        ArticleHorseLink.objects.create(horse_profile=child, article=article, status=ArticleHorseLinkStatus.MANUAL)
        signed_token = signed_follow_token()
        token_hash = token_hash_from_cookie(signed_token)
        follow_horse(token_hash, parent, include_descendants=True)
        self.client.cookies[FOLLOW_COOKIE_NAME] = signed_token
        response = self.client.get(reverse("public-news-feed"))

        self.assertEqual(HorseFollow.objects.get().token_hash, token_hash)
        self.assertNotIn(signed_token, HorseFollow.objects.get().token_hash)
        self.assertEqual(followed_articles(token_hash)[0]["article"].id, article.id)
        self.assertContains(response, "我的关注")
        self.assertContains(response, "北部玄驹子嗣新闻")

    def test_follow_feed_and_manage_page_hide_unpublished_profiles(self):
        profile = self._profile()
        article = self._article(title="春秋分相关新闻", body="春秋分相关。")
        ArticleHorseLink.objects.create(horse_profile=profile, article=article, status=ArticleHorseLinkStatus.MANUAL)
        signed_token = signed_follow_token()
        token_hash = token_hash_from_cookie(signed_token)
        follow_horse(token_hash, profile, include_descendants=True)
        profile.review_status = HorseProfileStatus.HIDDEN
        profile.save(update_fields=["review_status"])
        self.client.cookies[FOLLOW_COOKIE_NAME] = signed_token

        feed_response = self.client.get(reverse("public-news-feed"))
        follows_response = self.client.get(reverse("public-horse-follows"))

        self.assertEqual(followed_articles(token_hash), [])
        self.assertNotContains(feed_response, "follow-news-panel")
        self.assertNotContains(follows_response, profile.display_name)

    def test_public_follow_view_sets_cookie_attributes(self):
        profile = self._profile()
        response = self.client.post(reverse("public-horse-follow", args=[profile.id]), {"include_descendants": "1"})
        cookie = response.cookies[FOLLOW_COOKIE_NAME]

        self.assertEqual(response.status_code, 302)
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(HorseFollow.objects.count(), 1)

    def test_profile_save_form_cannot_publish_without_status_transition(self):
        profile = self._profile(review_status=HorseProfileStatus.DRAFT)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("console-horse-profile-detail", args=[profile.id]),
            {
                "display_name_zh": "春秋分",
                "original_name": "イクイノックス",
                "racing_region": RacingRegion.JAPAN,
                "review_status": HorseProfileStatus.PUBLISHED,
            },
            follow=True,
        )
        profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(profile.review_status, HorseProfileStatus.DRAFT)
        self.assertIsNone(profile.published_at)
        self.assertIsNone(profile.published_by)

    def test_console_workbench_supports_review_candidate_record_and_article_link(self):
        profile = self._profile(review_status=HorseProfileStatus.DRAFT)
        article = self._article()
        candidate = HorseProfileDataCandidate.objects.create(
            profile=profile,
            module=HorseProfileModule.PEDIGREE,
            source_name="fixture",
            candidate_payload={
                "sire_text": "父",
                "dam_text": "母",
                "sire_sire_text": "父父",
                "sire_dam_text": "父母",
                "dam_sire_text": "母父",
                "dam_dam_text": "母母",
            },
        )
        self.client.force_login(self.user)
        list_response = self.client.get(reverse("console-horse-profile-list"), {"status": HorseProfileStatus.DRAFT})
        detail_response = self.client.get(reverse("console-horse-profile-detail", args=[profile.id]))
        candidate_response = self.client.post(reverse("console-horse-profile-apply-candidate", args=[candidate.id]), {"action": "apply"}, follow=True)
        record_response = self.client.post(
            reverse("console-horse-profile-add-race-record", args=[profile.id]),
            {
                "race_name": "宝塚纪念",
                "normalized_grade": RaceGrade.G1,
                "result_status": HorseRaceResultStatus.WON,
                "source_name": "manual",
                "source_url": "https://example.com/takarazuka-kinen",
            },
            follow=True,
        )
        link_response = self.client.post(
            reverse("console-horse-profile-add-article-link", args=[profile.id]),
            {"article_id": article.id, "status": ArticleHorseLinkStatus.MANUAL},
            follow=True,
        )

        profile.refresh_from_db()
        record = HorseRaceRecord.objects.get(horse_profile=profile, race_name="宝塚纪念")
        edit_response = self.client.post(
            reverse("console-horse-profile-edit-race-record", args=[record.id]),
            {
                "race_name": "宝塚纪念",
                "race_year": 2026,
                "normalized_grade": RaceGrade.G1,
                "result_status": HorseRaceResultStatus.WON,
                "source_name": "manual",
                "source_url": "https://example.com/takarazuka-kinen",
            },
            follow=True,
        )
        self.assertContains(list_response, "春秋分")
        self.assertContains(detail_response, "候选资料 diff")
        self.assertContains(candidate_response, "候选资料已应用")
        self.assertEqual(profile.completeness_status, HorseProfileCompleteness.COMPLETE_PEDIGREE_2GEN)
        self.assertContains(record_response, "参赛履历已添加")
        self.assertContains(edit_response, "参赛履历已保存")
        record.refresh_from_db()
        self.assertEqual(record.race_year, 2026)
        self.assertContains(link_response, "文章关联已添加")
        self.assertTrue(ArticleHorseLink.objects.filter(horse_profile=profile, article=article, status=ArticleHorseLinkStatus.MANUAL).exists())

    def test_race_record_candidates_share_idempotent_upsert(self):
        profile = self._profile()
        payload = {
            "items": [
                {
                    "race_name": "宝塚纪念",
                    "race_year": 2026,
                    "race_date": "2026-06-28",
                    "racecourse": "阪神",
                    "normalized_grade": RaceGrade.G1,
                    "finish_position": "1",
                    "result_status": HorseRaceResultStatus.WON,
                }
            ]
        }
        candidates = [
            HorseProfileDataCandidate.objects.create(
                profile=profile,
                module=HorseProfileModule.RACE_RECORD,
                source_name="jra",
                source_url="https://example.com/takarazuka-kinen",
                candidate_payload=payload,
            )
            for _ in range(2)
        ]

        first = apply_horse_data_candidate(candidates[0], user=self.user)
        second = apply_horse_data_candidate(candidates[1], user=self.user)
        record = HorseRaceRecord.objects.get(horse_profile=profile, race_name="宝塚纪念")

        self.assertIn("'created': 1", first["updated_fields"][0])
        self.assertIn("'unchanged': 1", second["updated_fields"][0])
        self.assertTrue(record.idempotency_key)
        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=profile, race_name="宝塚纪念").count(), 1)

    def test_race_record_candidate_without_source_url_stays_pending(self):
        profile = self._profile()
        candidate = HorseProfileDataCandidate.objects.create(
            profile=profile,
            module=HorseProfileModule.RACE_RECORD,
            source_name="manual",
            source_url="",
            candidate_payload={"items": [{"race_name": "来源缺失赛事", "race_year": 2026}]},
        )

        with self.assertRaisesMessage(ValueError, "source_url is required"):
            apply_horse_data_candidate(candidate, user=self.user)
        candidate.refresh_from_db()

        self.assertEqual(candidate.status, HorseProfileCandidateStatus.PENDING)
        self.assertFalse(HorseRaceRecord.objects.filter(horse_profile=profile).exists())

    def test_manual_race_record_add_and_edit_use_idempotency_service(self):
        profile = self._profile()
        self.client.force_login(self.user)
        payload = {
            "race_name": "安田纪念",
            "race_year": 2026,
            "race_date": "2026-06-07",
            "racecourse": "东京",
            "normalized_grade": RaceGrade.G1,
            "result_status": HorseRaceResultStatus.WON,
            "source_name": "manual",
            "source_url": "https://example.com/yasuda-kinen",
        }

        self.client.post(reverse("console-horse-profile-add-race-record", args=[profile.id]), payload)
        self.client.post(reverse("console-horse-profile-add-race-record", args=[profile.id]), payload)
        record = HorseRaceRecord.objects.get(horse_profile=profile, race_name="安田纪念")
        original_key = record.idempotency_key
        edit_payload = {**payload, "race_name": "安田记念（修正）"}
        response = self.client.post(
            reverse("console-horse-profile-edit-race-record", args=[record.id]),
            edit_payload,
        )
        record.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=profile).count(), 1)
        self.assertTrue(record.idempotency_key)
        self.assertNotEqual(record.idempotency_key, original_key)
        self.assertEqual(record.race_name, "安田记念（修正）")

    def test_manual_race_record_requires_source_url(self):
        profile = self._profile()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("console-horse-profile-add-race-record", args=[profile.id]),
            {
                "race_name": "来源缺失赛事",
                "result_status": HorseRaceResultStatus.UNKNOWN,
                "source_name": "manual",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "参赛履历表单有误")
        self.assertFalse(HorseRaceRecord.objects.filter(horse_profile=profile).exists())

    def test_manual_race_record_edit_preserves_import_source_evidence(self):
        from stable.services.horse_race_records import upsert_race_record

        profile = self._profile()
        record = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="Imported Race",
            race_date=datetime(2026, 6, 7).date(),
            result_status=HorseRaceResultStatus.WON,
            source_name="jra",
            source_url="https://example.com/imported-race",
            source_refs={"external_result_id": "JRA-RESULT-7", "official": "https://example.com/official"},
            raw_payload={
                "external_result_id": "JRA-RESULT-7",
                "horse_number": "7",
                "raw_status": "confirmed",
            },
        )
        original_source_refs = dict(record.source_refs)
        original_raw_payload = dict(record.raw_payload)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("console-horse-profile-edit-race-record", args=[record.id]),
            {
                "race_name": "Imported Race Corrected",
                "race_date": "2026-06-07",
                "result_status": HorseRaceResultStatus.WON,
                "source_name": "jra",
                "source_url": "https://example.com/imported-race",
            },
        )
        record.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(record.race_name, "Imported Race Corrected")
        self.assertEqual(record.source_refs, original_source_refs)
        self.assertEqual(record.raw_payload, original_raw_payload)
        self.assertTrue(record.idempotency_key)

        upsert_race_record(
            profile,
            {
                "external_result_id": "JRA-RESULT-7",
                "race_name": "Imported Race",
                "race_date": "2026-06-07",
                "result_status": HorseRaceResultStatus.WON,
                "source_name": "jra",
                "source_url": "https://example.com/imported-race",
            },
        )
        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=profile).count(), 1)

    @override_settings(HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS=1)
    def test_stale_profile_filter_uses_completion_freshness_cutoff(self):
        profile = self._profile(
            primary_term=self._term("FRESHNESS-HORSE", "新鲜度测试马"),
            records_synced_through=timezone.localdate() - timedelta(days=1),
            racing_career_status="active",
        )
        self.client.force_login(self.user)

        fresh_response = self.client.get(reverse("console-horse-profile-list"), {"sync_status": "stale"})
        profile.records_synced_through = timezone.localdate() - timedelta(days=2)
        profile.save(update_fields=["records_synced_through", "updated_at"])
        stale_response = self.client.get(reverse("console-horse-profile-list"), {"sync_status": "stale"})

        self.assertNotContains(fresh_response, "新鲜度测试马")
        self.assertContains(stale_response, "新鲜度测试马")

    def test_completion_plan_is_dry_run_and_reports_missing_reasons(self):
        profile = self._profile(review_status=HorseProfileStatus.DRAFT)
        horse = ExternalHorse.objects.create(
            source=ExternalDataSource.NETKEIBA,
            racing_region=RacingRegion.JAPAN,
            horse_id="h1",
            horse_name="イクイノックス",
            normalized_horse_name="イクイノックス",
            father_name="父",
            mother_name="母",
            raw_payload={
                "sire_sire": "父父",
                "sire_dam": "父母",
                "dam_sire": "母父",
                "dam_dam": "母母",
            },
        )
        ExternalHorseAlias.objects.create(
            source=ExternalDataSource.NETKEIBA,
            racing_region=RacingRegion.JAPAN,
            horse=horse,
            external_horse_id=horse.horse_id,
            name_ja="イクイノックス",
            normalized_name="イクイノックス",
        )
        before_candidates = HorseProfileDataCandidate.objects.count()
        plan = plan_profile_completion(CompletionOptions(limit=10))
        profile.refresh_from_db()

        self.assertEqual(HorseProfileDataCandidate.objects.count(), before_candidates)
        self.assertEqual(profile.sire_text, "")
        self.assertEqual(plan["summary"]["total"], 1)
        self.assertEqual(plan["summary"]["complete_pedigree_2gen"], 1)
        self.assertEqual(plan["summary"]["regions"][RacingRegion.JAPAN]["complete_ratio"], 1.0)
        self.assertEqual(plan["summary"]["regions"][RacingRegion.JAPAN]["not_complete_ratio"], 0.0)
        self.assertEqual(plan["rows"][0]["completion_status"], HorseProfileCompleteness.COMPLETE_PEDIGREE_2GEN)

    def test_scan_article_horse_links_task_skips_stale_explicit_ids(self):
        self._profile()
        article = self._article()

        article_result = scan_article_horse_links_task.run(article_id=article.id + 1000, commit=True)
        profile_result = scan_article_horse_links_task.run(profile_id=999999, commit=True)

        self.assertEqual(article_result["reason"], "article_not_found")
        self.assertEqual(profile_result["reason"], "horse_profile_not_found")
        self.assertFalse(ArticleHorseLink.objects.exists())

    @override_settings(HORSE_PROFILE_COMPLETION_BATCH_LIMIT=1)
    def test_completion_command_without_limit_covers_all_p0_profiles(self):
        self._profile(review_status=HorseProfileStatus.DRAFT)
        self._profile(primary_term=self._term("キタサンブラック", "北部玄驹"), review_status=HorseProfileStatus.DRAFT)
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = StringIO()
            call_command("complete_horse_profiles", "--dry-run", "--output-dir", tmpdir, stdout=stdout)
            summary = json.loads((Path(tmpdir) / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["total"], 2)

    def test_completion_plan_matches_external_names_case_insensitively(self):
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Lucky Star",
            target_zh="幸运星",
            racing_region=RacingRegion.HONG_KONG,
            priority=100,
            is_active=True,
        )
        profile = self._profile(primary_term=term, review_status=HorseProfileStatus.DRAFT, english_name="lucky star")
        horse = ExternalHorse.objects.create(
            source=ExternalDataSource.HKJC,
            racing_region=RacingRegion.HONG_KONG,
            horse_id="HKH001",
            horse_name="Lucky Star",
            normalized_horse_name="Lucky Star",
            father_name="父",
            mother_name="母",
            raw_payload={
                "sire_sire": "父父",
                "sire_dam": "父母",
                "dam_sire": "母父",
                "dam_dam": "母母",
            },
        )
        ExternalHorseAlias.objects.create(
            source=ExternalDataSource.HKJC,
            racing_region=RacingRegion.HONG_KONG,
            horse=horse,
            external_horse_id=horse.horse_id,
            source_language=SourceLanguage.ENGLISH,
            name_en="Lucky Star",
            normalized_name="Lucky Star",
        )

        plan = plan_profile_completion(CompletionOptions(limit=10))

        self.assertEqual(plan["summary"]["total"], 1)
        self.assertEqual(plan["summary"]["complete_pedigree_2gen"], 1)
        self.assertEqual(plan["rows"][0]["profile_id"], profile.id)

    def test_completion_apply_records_pre_apply_diff(self):
        profile = self._profile(review_status=HorseProfileStatus.DRAFT)
        payload = {
            "rows": [
                {
                    "profile_id": profile.id,
                    "source": ExternalDataSource.NETKEIBA,
                    "source_url": "https://example.com/horse",
                    "confidence": 95,
                    "failure_reason": "",
                    "profile_payload": {"country": "日本"},
                    "pedigree_payload": {
                        "sire_text": "父",
                        "dam_text": "母",
                        "sire_sire_text": "父父",
                        "sire_dam_text": "父母",
                        "dam_sire_text": "母父",
                        "dam_dam_text": "母母",
                    },
                    "source_evidence": {"external_horse_id": "h1"},
                }
            ]
        }

        result = apply_completion_artifact(payload)
        profile.refresh_from_db()
        candidate = HorseProfileDataCandidate.objects.get(profile=profile)

        self.assertEqual(result["applied"], 1)
        self.assertEqual(profile.sire_text, "父")
        self.assertEqual(candidate.diff_payload["profile"]["country"]["current"], "")
        self.assertEqual(candidate.diff_payload["profile"]["country"]["candidate"], "日本")
        self.assertEqual(candidate.diff_payload["pedigree"]["sire_text"]["current"], "")
        self.assertEqual(candidate.diff_payload["pedigree"]["sire_text"]["candidate"], "父")


class P0HorseProfileDataCompletionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="p0-reviewer", password="pass")

    def _term(self, source="Forever Young", target="", region=RacingRegion.UNITED_STATES):
        from stable.models import TermTranslationStatus

        return TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja=source,
            target_zh=target,
            translation_status=TermTranslationStatus.TRANSLATED if target else TermTranslationStatus.PENDING,
            racing_region=region,
            priority=100,
            is_active=True,
        )

    def _profile(self, **overrides):
        from stable.models import HorseRacingCareerStatus

        term = overrides.pop("primary_term", None) or self._term()
        defaults = {
            "primary_term": term,
            "display_name_zh": term.target_zh,
            "original_name": term.source_ja,
            "english_name": term.source_ja,
            "racing_region": term.racing_region,
            "country": "美国",
            "sex": "牡",
            "color": "鹿毛",
            "birth_date": datetime(2021, 2, 24).date(),
            "owner_name": "Susumu Fujita",
            "trainer_name": "Yoshito Yahagi",
            "breeder_name": "Northern Racing",
            "sire_text": "Real Steel",
            "dam_text": "Forever Darling",
            "sire_sire_text": "Deep Impact",
            "sire_dam_text": "Loves Only Me",
            "dam_sire_text": "Congrats",
            "dam_dam_text": "Darling My Darling",
            "review_status": HorseProfileStatus.READY,
            "racing_career_status": HorseRacingCareerStatus.RETIRED,
            "records_synced_through": datetime(2026, 11, 8).date(),
        }
        defaults.update(overrides)
        return HorseProfile.objects.create(**defaults)

    def _approve_required_modules(self, profile):
        from stable.models import HorseRacingCareerStatus

        profile.racing_career_status = profile.racing_career_status or HorseRacingCareerStatus.RETIRED
        profile.full_profile_reviewed_at = timezone.now()
        profile.full_profile_reviewed_by = self.user
        profile.save(
            update_fields=[
                "racing_career_status",
                "full_profile_reviewed_at",
                "full_profile_reviewed_by",
                "updated_at",
            ]
        )
        for module in (
            HorseProfileModule.PROFILE,
            HorseProfileModule.PEDIGREE,
            HorseProfileModule.RACE_RECORD,
            HorseProfileModule.MAJOR_WINS,
        ):
            HorseProfileDataCandidate.objects.create(
                profile=profile,
                module=module,
                source_name="test_manual_review",
                source_url="https://example.com/review",
                status="applied",
                confidence=100,
                candidate_payload={"reviewed": True, "module": module},
                applied_by=self.user,
                applied_at=timezone.now(),
            )

    def _reviewed_artifact_row(self, profile, *, race_payload=None, profile_payload=None, pedigree_payload=None):
        return {
            "profile_id": profile.id,
            "reviewed": True,
            "source_name": "official",
            "source_url": "https://example.com/profile",
            "confidence": 100,
            "module_reviews": {
                "profile": {"status": "approved", "confidence": 100},
                "pedigree": {"status": "approved", "confidence": 100},
                "race_record": {"status": "approved", "confidence": 100},
                "major_wins": {"status": "approved", "confidence": 100},
            },
            "profile_payload": profile_payload or {},
            "pedigree_payload": pedigree_payload or {},
            "race_history_payload": race_payload or [],
        }

    def _race_event(
        self,
        *,
        region=RacingRegion.UNITED_STATES,
        grade=RaceGrade.G1,
        year=2026,
        horse_name="Forever Young",
        source_namespace="official",
        external_horse_id="",
    ):
        event = RaceEvent.objects.create(
            year=year,
            slug=f"{region.lower()}-{grade.lower()}-{year}-{RaceEvent.objects.count()}",
            original_name="Breeders' Cup Classic",
            chinese_name="育马者杯经典赛",
            country_region=region,
            racecourse="Del Mar",
            grade_text=grade,
            normalized_grade=grade,
            surface=RaceEventSurface.DIRT,
            local_date=datetime(year, 11, 7).date(),
            priority=RaceEventPriority.P0,
            status=RaceEventStatus.FINISHED,
            visibility_status=RaceEventVisibility.PUBLISHED,
            source_refs={"official": "https://example.com/race"},
        )
        result_source_refs = {"result": "https://example.com/result", "source": source_namespace}
        result_raw_payload = {}
        if external_horse_id:
            result_source_refs["external_horse_id"] = external_horse_id
            result_raw_payload["horse_id"] = external_horse_id
        RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            horse_number="1",
            horse_name=horse_name,
            jockey_name="Ryusei Sakai",
            trainer_name="Yoshito Yahagi",
            source_refs=result_source_refs,
            raw_payload=result_raw_payload,
        )
        return event

    def _complete_records(self, profile):
        HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="Breeders' Cup Classic",
            race_year=2026,
            race_date=datetime(2026, 11, 7).date(),
            grade_text="G1",
            normalized_grade=RaceGrade.G1,
            racecourse="Del Mar",
            distance_text="2000m",
            surface=RaceEventSurface.DIRT,
            finish_position="1",
            result_status=HorseRaceResultStatus.WON,
            is_major_win=True,
            source_name="official",
            source_url="https://example.com/result",
        )
        HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="Saudi Cup",
            race_year=2026,
            race_date=datetime(2026, 2, 21).date(),
            grade_text="G1",
            normalized_grade=RaceGrade.G1,
            racecourse="King Abdulaziz",
            distance_text="1800m",
            surface=RaceEventSurface.DIRT,
            finish_position="2",
            result_status=HorseRaceResultStatus.PLACED,
            source_name="official",
            source_url="https://example.com/saudi-cup",
        )

    def test_major_race_participant_without_translation_enters_p0_queue(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import build_p0_completion_queue, sync_p0_horse_sources

        self._race_event(region=RacingRegion.UNITED_STATES, grade=RaceGrade.G1, horse_name="Forever Young")

        summary = sync_p0_horse_sources(commit=True)
        queue = build_p0_completion_queue(regions=[RacingRegion.UNITED_STATES], limit_per_region=10)
        profile = HorseProfile.objects.get(original_name="Forever Young")

        self.assertEqual(summary["created_profiles"], 1)
        self.assertEqual(profile.display_name_zh, "")
        self.assertEqual(profile.review_status, HorseProfileStatus.DRAFT)
        self.assertTrue(
            HorseP0Source.objects.filter(
                profile=profile,
                source_type="major_race_participant",
                race_event__normalized_grade=RaceGrade.G1,
            ).exists()
        )
        self.assertEqual([item.profile_id for item in queue[RacingRegion.UNITED_STATES]], [profile.id])

    def test_p0_source_sync_covers_all_five_regions_and_rejects_non_major_grade(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        major_cases = [
            (RacingRegion.JAPAN, RaceGrade.JPN1, "Japan Hero"),
            (RacingRegion.HONG_KONG, RaceGrade.G1, "Hong Kong Hero"),
            (RacingRegion.UNITED_KINGDOM, RaceGrade.G2, "United Kingdom Hero"),
            (RacingRegion.FRANCE, RaceGrade.G3, "France Hero"),
            (RacingRegion.UNITED_STATES, RaceGrade.G1, "United States Hero"),
        ]
        for region, grade, horse_name in major_cases:
            self._race_event(region=region, grade=grade, horse_name=horse_name)
        self._race_event(region=RacingRegion.UNITED_STATES, grade=RaceGrade.LISTED, horse_name="Listed Only")

        summary = sync_p0_horse_sources(commit=True)

        self.assertEqual(summary["created_sources"], 5)
        self.assertEqual(HorseP0Source.objects.count(), 5)
        self.assertFalse(HorseProfile.objects.filter(original_name="Listed Only").exists())

    def test_full_source_sync_includes_global_translated_horse_terms(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        term = self._term(source="Global Horse", target="全局马", region="")

        summary = sync_p0_horse_sources(commit=True)

        profile = HorseProfile.objects.get(primary_term=term)
        self.assertEqual(summary["term_sources"], 1)
        self.assertTrue(HorseP0Source.objects.filter(profile=profile, source_type="term_active_with_zh").exists())

    def test_full_profile_completeness_requires_required_modules_but_not_intro_or_news(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import evaluate_full_profile_completeness

        profile = self._profile(intro="")
        self._complete_records(profile)
        HorseP0Source.objects.create(
            profile=profile,
            source_type="major_race_participant",
            source_url="https://example.com/race",
            observed_at=timezone.now(),
            metadata={"race_grade": RaceGrade.G1},
        )
        self._approve_required_modules(profile)

        complete = evaluate_full_profile_completeness(profile)
        profile.breeder_name = ""
        profile.save(update_fields=["breeder_name", "updated_at"])
        missing_basic = evaluate_full_profile_completeness(profile)

        self.assertTrue(complete.is_complete)
        self.assertNotIn("intro", complete.blocking_reasons)
        self.assertNotIn("article_links", complete.blocking_reasons)
        self.assertFalse(missing_basic.is_complete)
        self.assertIn("basic_facts.breeder_name", missing_basic.blocking_reasons)

    def test_active_horse_history_must_record_sync_window_and_stale_state(self):
        from stable.models import HorseP0Source, HorseRacingCareerStatus
        from stable.services.p0_horse_profiles import evaluate_full_profile_completeness

        profile = self._profile()
        self._complete_records(profile)
        profile.racing_career_status = HorseRacingCareerStatus.ACTIVE
        profile.records_synced_through = datetime(2026, 6, 30).date()
        profile.save(update_fields=["racing_career_status", "records_synced_through", "updated_at"])
        HorseP0Source.objects.create(profile=profile, source_type="term_active_with_zh", source_url="https://example.com/term")
        self._approve_required_modules(profile)

        stale = evaluate_full_profile_completeness(profile, as_of=datetime(2026, 11, 8).date())
        profile.records_synced_through = datetime(2026, 11, 8).date()
        profile.save(update_fields=["records_synced_through", "updated_at"])
        fresh = evaluate_full_profile_completeness(profile, as_of=datetime(2026, 11, 8).date())

        self.assertFalse(stale.is_complete)
        self.assertIn("race_history.sync_window_stale", stale.blocking_reasons)
        self.assertTrue(fresh.is_complete)

    @override_settings(HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS=1)
    def test_active_horse_history_uses_default_freshness_cutoff(self):
        from stable.models import HorseP0Source, HorseRacingCareerStatus
        from stable.services.p0_horse_profiles import evaluate_full_profile_completeness

        profile = self._profile(racing_career_status=HorseRacingCareerStatus.ACTIVE)
        self._complete_records(profile)
        HorseP0Source.objects.create(profile=profile, source_type="term_active_with_zh", source_url="https://example.com/term")
        self._approve_required_modules(profile)
        profile.records_synced_through = timezone.localdate() - timedelta(days=2)
        profile.save(update_fields=["records_synced_through", "updated_at"])

        stale = evaluate_full_profile_completeness(profile)
        profile.records_synced_through = timezone.localdate() - timedelta(days=1)
        profile.save(update_fields=["records_synced_through", "updated_at"])
        fresh = evaluate_full_profile_completeness(profile)

        self.assertIn("race_history.sync_window_stale", stale.blocking_reasons)
        self.assertTrue(fresh.is_complete)

    def test_reviewed_completion_batch_is_idempotent_and_respects_manual_locks(self):
        from stable.services.p0_horse_profiles import apply_reviewed_completion_artifact

        profile = self._profile(country="美国", manual_lock_flags={"country": True})
        payload = {
            "reviewed": True,
            "reviewer_id": self.user.id,
            "rows": [
                self._reviewed_artifact_row(
                    profile,
                    profile_payload={
                        "country": "日本",
                        "owner_name": "Susumu Fujita",
                        "trainer_name": "Yoshito Yahagi",
                    },
                    pedigree_payload={
                        "sire_text": "Real Steel",
                        "dam_text": "Forever Darling",
                        "sire_sire_text": "Deep Impact",
                        "sire_dam_text": "Loves Only Me",
                        "dam_sire_text": "Congrats",
                        "dam_dam_text": "Darling My Darling",
                    },
                    race_payload=[
                        {
                            "race_name": "Breeders' Cup Classic",
                            "race_year": 2026,
                            "race_date": "2026-11-07",
                            "normalized_grade": RaceGrade.G1,
                            "finish_position": "1",
                            "result_status": HorseRaceResultStatus.WON,
                            "is_major_win": True,
                            "source_name": "official",
                            "source_url": "https://example.com/result",
                        }
                    ],
                )
            ],
        }

        first = apply_reviewed_completion_artifact(payload, commit=True)
        second = apply_reviewed_completion_artifact(payload, commit=True)
        profile.refresh_from_db()

        self.assertEqual(first["applied_profiles"], 1)
        self.assertEqual(second["applied_profiles"], 0)
        self.assertEqual(profile.country, "美国")
        self.assertEqual(profile.review_status, HorseProfileStatus.READY)
        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=profile, race_name="Breeders' Cup Classic").count(), 1)

    def test_reviewed_artifact_keeps_manual_p0_source_active_for_each_profile(self):
        from stable.models import HorseP0Source, HorseP0SourceStatus, HorseP0SourceType
        from stable.services.p0_horse_profiles import apply_reviewed_completion_artifact

        first_profile = self._profile(primary_term=self._term(source="First Manual Source"))
        second_profile = self._profile(primary_term=self._term(source="Second Manual Source"))
        payload = {
            "reviewed": True,
            "reviewer_id": self.user.id,
            "rows": [
                {**self._reviewed_artifact_row(first_profile), "source_url": "https://example.com/horse/first"},
                {**self._reviewed_artifact_row(second_profile), "source_url": "https://example.com/horse/second"},
            ],
        }

        apply_reviewed_completion_artifact(payload, commit=True)

        active_sources = HorseP0Source.objects.filter(
            source_type=HorseP0SourceType.MANUAL,
            status=HorseP0SourceStatus.ACTIVE,
        )
        self.assertEqual(active_sources.filter(profile=first_profile).count(), 1)
        self.assertEqual(active_sources.filter(profile=second_profile).count(), 1)
        self.assertEqual(active_sources.count(), 2)

    def test_unapproved_modules_never_write_even_when_artifact_is_reviewed(self):
        from stable.services.p0_horse_profiles import apply_reviewed_completion_artifact

        profile = self._profile(owner_name="Old Owner", sire_text="Old Sire")
        row = self._reviewed_artifact_row(
            profile,
            profile_payload={"owner_name": "Approved Owner"},
            pedigree_payload={"sire_text": "Unapproved Sire"},
            race_payload=[
                {
                    "race_name": "Unapproved Race",
                    "race_date": "2026-01-01",
                    "source_name": "official",
                    "source_url": "https://example.com/unapproved-race",
                }
            ],
        )
        row["module_reviews"]["pedigree"]["status"] = "pending"
        row["module_reviews"]["race_record"]["status"] = "conflict"
        row["module_reviews"]["major_wins"]["status"] = "pending"

        summary = apply_reviewed_completion_artifact(
            {"reviewed": True, "reviewer_id": self.user.id, "rows": [row]},
            commit=True,
        )
        profile.refresh_from_db()

        self.assertEqual(profile.owner_name, "Approved Owner")
        self.assertEqual(profile.sire_text, "Old Sire")
        self.assertFalse(HorseRaceRecord.objects.filter(horse_profile=profile, race_name="Unapproved Race").exists())
        self.assertEqual(summary["skipped_unreviewed_modules"], 3)
        self.assertNotEqual(profile.completeness_status, HorseProfileCompleteness.COMPLETE_PROFILE_FULL)

    def test_approved_race_module_without_record_source_never_writes(self):
        from stable.services.p0_horse_profiles import apply_reviewed_completion_artifact

        profile = self._profile()
        row = self._reviewed_artifact_row(
            profile,
            race_payload=[
                {
                    "race_name": "Missing Source Race",
                    "race_date": "2026-01-01",
                    "source_name": "official",
                    "source_url": "",
                }
            ],
        )

        summary = apply_reviewed_completion_artifact(
            {"reviewed": True, "reviewer_id": self.user.id, "rows": [row]},
            commit=True,
        )

        self.assertEqual(summary["skipped_missing_source_url"], 1)
        self.assertFalse(HorseRaceRecord.objects.filter(horse_profile=profile, race_name="Missing Source Race").exists())

    def test_reviewed_artifact_without_reviewer_never_writes(self):
        from stable.services.p0_horse_profiles import apply_reviewed_completion_artifact

        profile = self._profile(owner_name="Old Owner")
        row = self._reviewed_artifact_row(profile, profile_payload={"owner_name": "No Reviewer"})

        summary = apply_reviewed_completion_artifact(
            {"reviewed": True, "rows": [row]},
            commit=True,
        )
        profile.refresh_from_db()

        self.assertEqual(summary["skipped_missing_reviewer"], 1)
        self.assertEqual(profile.owner_name, "Old Owner")
        self.assertFalse(HorseProfileDataCandidate.objects.filter(profile=profile).exists())

    def test_legacy_race_record_is_adopted_instead_of_duplicated(self):
        from stable.services.p0_horse_profiles import apply_reviewed_completion_artifact

        profile = self._profile()
        legacy = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="Breeders' Cup Classic",
            race_year=2026,
            race_date=datetime(2026, 11, 7).date(),
            racecourse="Del Mar",
            finish_position="1",
            result_status=HorseRaceResultStatus.WON,
            source_name="official",
            source_url="https://example.com/result",
        )
        row = self._reviewed_artifact_row(
            profile,
            race_payload=[
                {
                    "race_name": "Breeders' Cup Classic",
                    "race_year": 2026,
                    "race_date": "2026-11-07",
                    "racecourse": "Del Mar",
                    "finish_position": "1",
                    "result_status": HorseRaceResultStatus.WON,
                    "source_name": "official",
                    "source_url": "https://example.com/result",
                }
            ],
        )

        summary = apply_reviewed_completion_artifact(
            {"reviewed": True, "reviewer_id": self.user.id, "rows": [row]},
            commit=True,
        )
        legacy.refresh_from_db()

        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=profile).count(), 1)
        self.assertTrue(legacy.idempotency_key)
        self.assertEqual(summary["race_records_adopted"], 1)

    def test_duplicate_legacy_race_records_become_conflict_without_third_copy(self):
        from stable.services.p0_horse_profiles import apply_reviewed_completion_artifact

        profile = self._profile()
        record_data = {
            "race_name": "Duplicate Race",
            "race_year": 2026,
            "race_date": datetime(2026, 5, 1).date(),
            "racecourse": "Test Course",
            "source_name": "official",
            "source_url": "https://example.com/duplicate-race",
        }
        HorseRaceRecord.objects.create(horse_profile=profile, **record_data)
        HorseRaceRecord.objects.create(horse_profile=profile, **record_data)
        row = self._reviewed_artifact_row(
            profile,
            race_payload=[
                {
                    **record_data,
                    "race_date": "2026-05-01",
                    "result_status": HorseRaceResultStatus.UNKNOWN,
                }
            ],
        )

        summary = apply_reviewed_completion_artifact(
            {"reviewed": True, "reviewer_id": self.user.id, "rows": [row]},
            commit=True,
        )

        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=profile, race_name="Duplicate Race").count(), 2)
        self.assertEqual(summary["skipped_conflict_modules"], 1)
        self.assertTrue(
            HorseProfileDataCandidate.objects.filter(
                profile=profile,
                module=HorseProfileModule.RACE_RECORD,
                status="conflict",
            ).exists()
        )

    def test_duplicate_external_identity_records_block_third_copy_despite_field_changes(self):
        from stable.services.horse_race_records import AmbiguousLegacyRaceRecordError, upsert_race_record

        profile = self._profile()
        for index, race_name in enumerate(("Old Race Name", "Corrected Race Name"), start=1):
            HorseRaceRecord.objects.create(
                horse_profile=profile,
                race_name=race_name,
                race_year=2026,
                source_name="official",
                source_url=f"https://example.com/legacy-result/{index}",
                source_refs={"external_result_id": "DUPLICATE-EXTERNAL-1"},
                idempotency_key="",
            )

        with self.assertRaises(AmbiguousLegacyRaceRecordError):
            upsert_race_record(
                profile,
                {
                    "external_result_id": "DUPLICATE-EXTERNAL-1",
                    "race_name": "Latest Official Race Name",
                    "race_year": 2026,
                    "source_name": "official",
                    "source_url": "https://example.com/latest-result",
                },
            )

        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=profile).count(), 2)

    def test_external_identity_adopts_legacy_record_with_source_only_in_evidence(self):
        from stable.services.horse_race_records import upsert_race_record

        profile = self._profile()
        legacy = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="Old Race Name",
            race_year=2026,
            source_name="",
            source_url="https://example.com/old-result",
            source_refs={
                "source": "official",
                "external_result_id": "EVIDENCE-SOURCE-1",
            },
            idempotency_key="",
        )

        result = upsert_race_record(
            profile,
            {
                "external_result_id": "EVIDENCE-SOURCE-1",
                "race_name": "Corrected Race Name",
                "race_year": 2026,
                "source_name": "official",
                "source_url": "https://example.com/corrected-result",
            },
        )

        legacy.refresh_from_db()
        self.assertEqual(result.record.id, legacy.id)
        self.assertEqual(result.action, "adopted")
        self.assertEqual(legacy.source_name, "official")
        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=profile).count(), 1)

    def test_race_record_source_namespace_is_case_insensitive_for_idempotency(self):
        from stable.services.horse_race_records import upsert_race_record

        profile = self._profile()
        first = upsert_race_record(
            profile,
            {
                "external_result_id": "SOURCE-CASE-1",
                "race_name": "Source Case Race",
                "race_year": 2026,
                "source_name": "Official",
                "source_url": "https://example.com/source-case",
            },
        )
        second = upsert_race_record(
            profile,
            {
                "external_result_id": "SOURCE-CASE-1",
                "race_name": "Source Case Race",
                "race_year": 2026,
                "source_name": "official",
                "source_url": "https://example.com/source-case",
            },
        )

        self.assertEqual(second.record.id, first.record.id)
        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=profile).count(), 1)

    def test_editing_legacy_record_rejects_other_record_with_same_external_identity(self):
        from stable.services.horse_race_records import DuplicateRaceRecordError, upsert_race_record

        profile = self._profile()
        records = []
        for index, race_name in enumerate(("First Legacy Name", "Second Legacy Name"), start=1):
            records.append(
                HorseRaceRecord.objects.create(
                    horse_profile=profile,
                    race_name=race_name,
                    race_year=2026,
                    source_name="official",
                    source_url=f"https://example.com/edit-legacy/{index}",
                    source_refs={"external_result_id": "EDIT-DUPLICATE-1"},
                    idempotency_key="",
                )
            )

        with self.assertRaises(DuplicateRaceRecordError):
            upsert_race_record(
                profile,
                {
                    "race_name": "Edited Legacy Name",
                    "race_year": 2026,
                    "source_name": "official",
                    "source_url": "https://example.com/edit-legacy/1",
                },
                record=records[0],
            )

        for record in records:
            record.refresh_from_db()
            self.assertEqual(record.idempotency_key, "")

    def test_race_record_correction_is_reported_and_audited(self):
        from stable.services.p0_horse_profiles import apply_reviewed_completion_artifact

        profile = self._profile()
        base_record = {
            "external_result_id": "official-result-1",
            "race_name": "Breeders' Cup Classic",
            "race_year": 2026,
            "race_date": "2026-11-07",
            "racecourse": "Del Mar",
            "finish_position": "2",
            "result_status": HorseRaceResultStatus.PLACED,
            "source_name": "official",
            "source_url": "https://example.com/result",
        }
        first_row = self._reviewed_artifact_row(profile, race_payload=[base_record])
        apply_reviewed_completion_artifact(
            {"reviewed": True, "reviewer_id": self.user.id, "rows": [first_row]},
            commit=True,
        )
        corrected = {**base_record, "finish_position": "", "result_status": HorseRaceResultStatus.DISQUALIFIED}
        second_row = self._reviewed_artifact_row(profile, race_payload=[corrected])

        summary = apply_reviewed_completion_artifact(
            {"reviewed": True, "reviewer_id": self.user.id, "rows": [second_row]},
            commit=True,
        )
        record = HorseRaceRecord.objects.get(horse_profile=profile, race_name="Breeders' Cup Classic")
        audit = HorseProfileDataCandidate.objects.filter(profile=profile, module=HorseProfileModule.RACE_RECORD).latest("id")

        self.assertEqual(summary["race_records_updated"], 1)
        self.assertEqual(record.result_status, HorseRaceResultStatus.DISQUALIFIED)
        self.assertEqual(audit.diff_payload["records"][0]["before"]["result_status"], HorseRaceResultStatus.PLACED)
        self.assertEqual(audit.diff_payload["records"][0]["after"]["result_status"], HorseRaceResultStatus.DISQUALIFIED)

    def test_complete_profile_rejects_unknown_career_and_any_unsourced_record(self):
        from stable.models import HorseP0Source, HorseRacingCareerStatus
        from stable.services.p0_horse_profiles import evaluate_full_profile_completeness

        profile = self._profile(racing_career_status=HorseRacingCareerStatus.UNKNOWN)
        self._complete_records(profile)
        HorseP0Source.objects.create(profile=profile, source_type="manual", source_url="https://example.com/profile")
        self._approve_required_modules(profile)
        unknown = evaluate_full_profile_completeness(profile)

        profile.racing_career_status = HorseRacingCareerStatus.RETIRED
        profile.save(update_fields=["racing_career_status", "updated_at"])
        HorseRaceRecord.objects.filter(horse_profile=profile, race_name="Saudi Cup").update(source_url="")
        unsourced = evaluate_full_profile_completeness(profile)

        self.assertIn("racing_career_status.unknown", unknown.blocking_reasons)
        self.assertIn("race_history.source_url", unsourced.blocking_reasons)

    def test_latest_module_conflict_invalidates_historical_approval(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import apply_reviewed_completion_artifact, evaluate_full_profile_completeness

        profile = self._profile(completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL)
        self._complete_records(profile)
        HorseP0Source.objects.create(profile=profile, source_type="manual", source_url="https://example.com/profile")
        self._approve_required_modules(profile)
        self.assertTrue(evaluate_full_profile_completeness(profile).is_complete)
        row = self._reviewed_artifact_row(profile)
        row["module_reviews"]["race_record"]["status"] = "conflict"
        apply_reviewed_completion_artifact(
            {"reviewed": True, "reviewer_id": self.user.id, "rows": [row]},
            commit=True,
        )
        profile.refresh_from_db()

        evaluation = evaluate_full_profile_completeness(profile)

        self.assertFalse(evaluation.is_complete)
        self.assertIn("review.module.race_record", evaluation.blocking_reasons)
        self.assertNotEqual(profile.completeness_status, HorseProfileCompleteness.COMPLETE_PROFILE_FULL)

    def test_cross_region_participant_reuses_identity_without_changing_home_region(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        term = self._term(region=RacingRegion.JAPAN)
        profile = self._profile(
            primary_term=term,
            racing_region=RacingRegion.JAPAN,
            country="日本",
            source_refs={"horse_identity_keys": ["official:FY-001"]},
        )
        self._race_event(
            region=RacingRegion.UNITED_STATES,
            horse_name="Forever Young",
            source_namespace="official",
            external_horse_id="FY-001",
        )

        summary = sync_p0_horse_sources(commit=True)
        profile.refresh_from_db()
        source = HorseP0Source.objects.get(profile=profile, source_type="major_race_participant")

        self.assertEqual(summary["created_profiles"], 0)
        self.assertEqual(TermEntry.objects.filter(term_type=TermType.HORSE, source_ja__iexact="Forever Young").count(), 1)
        self.assertEqual(profile.racing_region, RacingRegion.JAPAN)
        self.assertEqual(source.racing_region, RacingRegion.UNITED_STATES)

    def test_same_region_same_name_without_strong_identity_is_ambiguous(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        first_term = self._term(source="Twin Star", region=RacingRegion.UNITED_STATES)
        first_profile = self._profile(primary_term=first_term, original_name="Twin Star", english_name="Twin Star")
        self._race_event(region=RacingRegion.UNITED_STATES, horse_name="Twin Star")

        summary = sync_p0_horse_sources(commit=True)

        self.assertEqual(summary["ambiguous_participants"], 1)
        self.assertFalse(
            HorseP0Source.objects.filter(
                profile=first_profile,
                source_type="major_race_participant",
            ).exists()
        )

    def test_same_region_same_name_with_distinct_external_ids_creates_distinct_profiles(self):
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        first_term = self._term(source="Twin Star", region=RacingRegion.UNITED_STATES)
        first_profile = self._profile(
            primary_term=first_term,
            original_name="Twin Star",
            english_name="Twin Star",
            source_refs={"horse_identity_keys": ["official:TWIN-A"]},
        )
        self._race_event(
            region=RacingRegion.UNITED_STATES,
            horse_name="Twin Star",
            source_namespace="official",
            external_horse_id="TWIN-B",
        )

        summary = sync_p0_horse_sources(commit=True)

        profiles = HorseProfile.objects.filter(original_name="Twin Star").order_by("id")
        self.assertEqual(summary["ambiguous_participants"], 0)
        self.assertEqual(profiles.count(), 2)
        self.assertEqual(profiles.first(), first_profile)
        self.assertIn("official:twin-b", profiles.last().source_refs["horse_identity_keys"])

    def test_same_event_same_name_runners_are_kept_separate_by_horse_number(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(
            horse_name="Twin Star",
            source_namespace="official",
            external_horse_id="TWIN-A",
        )
        first_result = event.results.get()
        first_result.horse_number = "3"
        first_result.save(update_fields=["horse_number", "updated_at"])
        RaceEventResult.objects.create(
            event=event,
            finish_position=2,
            horse_number="8",
            horse_name="Twin Star",
            source_refs={
                "result": "https://example.com/result/2",
                "source": "official",
                "external_horse_id": "TWIN-B",
            },
            raw_payload={"horse_id": "TWIN-B"},
        )

        summary = sync_p0_horse_sources(commit=True)

        self.assertEqual(summary["major_race_sources"], 2)
        self.assertEqual(HorseProfile.objects.filter(original_name="Twin Star").count(), 2)
        self.assertEqual(HorseP0Source.objects.filter(race_event=event, status="active").count(), 2)

    def test_same_event_same_name_without_external_ids_uses_horse_number_identity(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Twin Star", external_horse_id="")
        first_result = event.results.get()
        first_result.horse_number = "3"
        first_result.save(update_fields=["horse_number", "updated_at"])
        RaceEventResult.objects.create(
            event=event,
            finish_position=2,
            horse_number="8",
            horse_name="Twin Star",
            source_refs={"result": "https://example.com/result/2", "source": "official"},
        )

        summary = sync_p0_horse_sources(commit=True)
        second_summary = sync_p0_horse_sources(commit=True)

        sources = HorseP0Source.objects.filter(race_event=event, status="active").order_by("participant_key")
        self.assertEqual(summary["major_race_sources"], 2)
        self.assertEqual(second_summary["major_race_sources"], 2)
        self.assertEqual(HorseProfile.objects.filter(original_name="Twin Star").count(), 2)
        self.assertEqual(set(sources.values_list("participant_key", flat=True)), {"number:3", "number:8"})
        self.assertEqual(sources.values_list("profile_id", flat=True).distinct().count(), 2)

    def test_runner_and_result_pair_by_external_id_when_result_has_no_number(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Asymmetric Star", external_horse_id="ASYM-1")
        result = event.results.get()
        result.horse_number = ""
        result.save(update_fields=["horse_number", "updated_at"])
        runner = RaceEventRunner.objects.create(
            event=event,
            horse_number="7",
            horse_name="Asymmetric Star",
            source_refs={
                "runner": "https://example.com/runner/7",
                "source": "official",
                "external_horse_id": "ASYM-1",
            },
            raw_payload={"horse_id": "ASYM-1"},
        )

        summary = sync_p0_horse_sources(commit=True)

        source = HorseP0Source.objects.get(race_event=event, status="active")
        self.assertEqual(summary["major_race_sources"], 1)
        self.assertEqual(source.participant_key, "number:7")
        self.assertEqual(source.race_runner, runner)
        self.assertEqual(source.race_result, result)

    def test_participant_key_upgrades_from_external_identity_to_horse_number(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Key Upgrade", external_horse_id="UPGRADE-1")
        result = event.results.get()
        result.horse_number = ""
        result.save(update_fields=["horse_number", "updated_at"])
        sync_p0_horse_sources(commit=True)
        source = HorseP0Source.objects.get(race_event=event, status="active")
        self.assertTrue(source.participant_key.startswith("identity:"))

        result.horse_number = "7"
        result.save(update_fields=["horse_number", "updated_at"])
        summary = sync_p0_horse_sources(commit=True)
        source.refresh_from_db()

        self.assertEqual(summary["major_race_sources"], 1)
        self.assertEqual(source.participant_key, "number:7")
        self.assertEqual(HorseP0Source.objects.filter(race_event=event, status="active").count(), 1)

    def test_conflicting_runner_and_result_numbers_create_identity_conflict(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Number Conflict", external_horse_id="CONFLICT-1")
        result = event.results.get()
        result.horse_number = "8"
        result.save(update_fields=["horse_number", "updated_at"])
        RaceEventRunner.objects.create(
            event=event,
            horse_number="3",
            horse_name="Number Conflict",
            source_refs={
                "runner": "https://example.com/runner/3",
                "source": "official",
                "external_horse_id": "CONFLICT-1",
            },
            raw_payload={"horse_id": "CONFLICT-1"},
        )

        summary = sync_p0_horse_sources(commit=True)

        conflict = HorseIdentityConflict.objects.get(race_event=event)
        pairing = conflict.evidence_payload["pairing_conflict"]
        self.assertEqual(summary["ambiguous_participants"], 1)
        self.assertEqual(pairing["runner_number"], "3")
        self.assertEqual(pairing["result_number"], "8")
        self.assertFalse(HorseP0Source.objects.filter(race_event=event, status="active").exists())

    def test_same_identity_with_different_result_numbers_creates_one_conflict(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Result Number Conflict", external_horse_id="RESULT-CONFLICT")
        first_result = event.results.get()
        first_result.horse_number = "3"
        first_result.save(update_fields=["horse_number", "updated_at"])
        RaceEventResult.objects.create(
            event=event,
            horse_number="8",
            horse_name="Result Number Conflict",
            finish_position=2,
            source_refs={
                "result": "https://example.com/result/8",
                "source": "official",
                "external_horse_id": "RESULT-CONFLICT",
            },
            raw_payload={"horse_id": "RESULT-CONFLICT"},
        )

        summary = sync_p0_horse_sources(commit=True)

        conflict = HorseIdentityConflict.objects.get(race_event=event)
        pairing = conflict.evidence_payload["pairing_conflict"]
        self.assertEqual(summary["ambiguous_participants"], 1)
        self.assertEqual(pairing["horse_numbers"], ["3", "8"])
        self.assertEqual(len(pairing["result_ids"]), 2)
        self.assertFalse(HorseP0Source.objects.filter(race_event=event, status="active").exists())

    def test_same_identity_with_different_runner_numbers_creates_one_conflict(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Runner Number Conflict", external_horse_id="RUNNER-CONFLICT")
        event.results.all().delete()
        for horse_number in ("3", "8"):
            RaceEventRunner.objects.create(
                event=event,
                horse_number=horse_number,
                horse_name="Runner Number Conflict",
                source_refs={
                    "runner": f"https://example.com/runner/{horse_number}",
                    "source": "official",
                    "external_horse_id": "RUNNER-CONFLICT",
                },
                raw_payload={"horse_id": "RUNNER-CONFLICT"},
            )

        summary = sync_p0_horse_sources(commit=True)

        conflict = HorseIdentityConflict.objects.get(race_event=event)
        pairing = conflict.evidence_payload["pairing_conflict"]
        self.assertEqual(summary["ambiguous_participants"], 1)
        self.assertEqual(pairing["horse_numbers"], ["3", "8"])
        self.assertEqual(len(pairing["runner_ids"]), 2)
        self.assertFalse(HorseP0Source.objects.filter(race_event=event, status="active").exists())

    def test_overlapping_identity_keys_create_one_complete_conflict_group(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Linked Identity", external_horse_id="IDENTITY-A")
        first_result = event.results.get()
        first_result.horse_number = "3"
        first_result.raw_payload = {"horse_id": "IDENTITY-B"}
        first_result.save(update_fields=["horse_number", "raw_payload", "updated_at"])
        second_result = RaceEventResult.objects.create(
            event=event,
            horse_number="8",
            horse_name="Linked Identity",
            finish_position=2,
            source_refs={
                "result": "https://example.com/result/8",
                "source": "official",
                "external_horse_id": "IDENTITY-A",
            },
        )
        third_result = RaceEventResult.objects.create(
            event=event,
            horse_number="9",
            horse_name="Linked Identity",
            finish_position=3,
            source_refs={
                "result": "https://example.com/result/9",
                "source": "official",
                "external_horse_id": "IDENTITY-B",
            },
        )

        summary = sync_p0_horse_sources(commit=True)

        conflict = HorseIdentityConflict.objects.get(race_event=event)
        pairing = conflict.evidence_payload["pairing_conflict"]
        self.assertEqual(summary["ambiguous_participants"], 1)
        self.assertEqual(pairing["horse_numbers"], ["3", "8", "9"])
        self.assertEqual(
            set(pairing["result_ids"]),
            {first_result.id, second_result.id, third_result.id},
        )
        self.assertEqual(
            set(pairing["identity_keys"]),
            {"official:identity-a", "official:identity-b"},
        )
        self.assertFalse(HorseP0Source.objects.filter(race_event=event, status="active").exists())

    def test_resolved_number_conflict_requires_and_uses_selected_horse_number(self):
        from django.core.exceptions import ValidationError

        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Resolved Number Conflict", external_horse_id="RESOLVED-CONFLICT")
        result = event.results.get()
        result.horse_number = "8"
        result.save(update_fields=["horse_number", "updated_at"])
        runner = RaceEventRunner.objects.create(
            event=event,
            horse_number="3",
            horse_name="Resolved Number Conflict",
            source_refs={
                "runner": "https://example.com/runner/3",
                "source": "official",
                "external_horse_id": "RESOLVED-CONFLICT",
            },
            raw_payload={"horse_id": "RESOLVED-CONFLICT"},
        )
        sync_p0_horse_sources(commit=True)
        conflict = HorseIdentityConflict.objects.get(race_event=event)
        resolved_profile = self._profile(
            primary_term=self._term(source="Resolved Number Conflict Profile"),
            original_name="Resolved Number Conflict",
        )
        conflict.status = HorseIdentityConflictStatus.RESOLVED
        conflict.resolved_profile = resolved_profile
        with self.assertRaises(ValidationError):
            conflict.full_clean()
        conflict.resolved_horse_number = "3"
        conflict.full_clean()
        conflict.save(
            update_fields=["status", "resolved_profile", "resolved_horse_number", "updated_at"]
        )

        summary = sync_p0_horse_sources(commit=True)

        source = HorseP0Source.objects.get(race_event=event, status="active")
        self.assertEqual(summary["major_race_sources"], 1)
        self.assertEqual(source.profile, resolved_profile)
        self.assertEqual(source.participant_key, "number:3")
        self.assertEqual(source.race_runner, runner)
        self.assertIsNone(source.race_result)

    def test_conflict_uses_url_from_any_member_and_persists_without_urls(self):
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Conflict URL", external_horse_id="CONFLICT-URL")
        event.source_refs = {}
        event.save(update_fields=["source_refs", "updated_at"])
        first_result = event.results.get()
        first_result.horse_number = "3"
        first_result.source_refs = {"source": "official", "external_horse_id": "CONFLICT-URL"}
        first_result.save(update_fields=["horse_number", "source_refs", "updated_at"])
        second_result = RaceEventResult.objects.create(
            event=event,
            horse_number="8",
            horse_name="Conflict URL",
            finish_position=2,
            source_refs={
                "result": "https://example.com/result/8",
                "source": "official",
                "external_horse_id": "CONFLICT-URL",
            },
        )

        sync_p0_horse_sources(commit=True)

        conflict = HorseIdentityConflict.objects.get(race_event=event)
        self.assertEqual(conflict.source_url, second_result.source_refs["result"])
        self.assertEqual(conflict.evidence_payload["pairing_conflict"]["source_urls"], [second_result.source_refs["result"]])

        no_url_event = self._race_event(
            horse_name="Conflict No URL",
            external_horse_id="CONFLICT-NO-URL",
        )
        no_url_event.source_refs = {}
        no_url_event.save(update_fields=["source_refs", "updated_at"])
        no_url_first = no_url_event.results.get()
        no_url_first.horse_number = "3"
        no_url_first.source_refs = {"source": "official", "external_horse_id": "CONFLICT-NO-URL"}
        no_url_first.save(update_fields=["horse_number", "source_refs", "updated_at"])
        RaceEventResult.objects.create(
            event=no_url_event,
            horse_number="8",
            horse_name="Conflict No URL",
            finish_position=2,
            source_refs={"source": "official", "external_horse_id": "CONFLICT-NO-URL"},
        )

        summary = sync_p0_horse_sources(commit=True)

        no_url_conflict = HorseIdentityConflict.objects.get(race_event=no_url_event)
        self.assertEqual(no_url_conflict.source_url, "")
        self.assertEqual(no_url_conflict.evidence_payload["pairing_conflict"]["source_urls"], [])
        self.assertGreaterEqual(summary["missing_source_url_participants"], 1)

    def test_resolved_number_conflict_without_selected_member_url_returns_to_pending(self):
        from django.core.exceptions import ValidationError

        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Missing Selected URL", external_horse_id="MISSING-URL")
        event.source_refs = {}
        event.save(update_fields=["source_refs", "updated_at"])
        first_result = event.results.get()
        first_result.horse_number = "3"
        first_result.source_refs = {"source": "official", "external_horse_id": "MISSING-URL"}
        first_result.save(update_fields=["horse_number", "source_refs", "updated_at"])
        RaceEventResult.objects.create(
            event=event,
            horse_number="8",
            horse_name="Missing Selected URL",
            finish_position=2,
            source_refs={
                "result": "https://example.com/result/8",
                "source": "official",
                "external_horse_id": "MISSING-URL",
            },
        )
        sync_p0_horse_sources(commit=True)
        conflict = HorseIdentityConflict.objects.get(race_event=event)
        resolved_profile = self._profile(
            primary_term=self._term(source="Missing Selected URL Profile"),
            original_name="Missing Selected URL",
        )
        conflict.status = HorseIdentityConflictStatus.RESOLVED
        conflict.resolved_profile = resolved_profile
        conflict.resolved_horse_number = "3"
        with self.assertRaises(ValidationError):
            conflict.full_clean()

        HorseIdentityConflict.objects.filter(pk=conflict.pk).update(
            status=HorseIdentityConflictStatus.RESOLVED,
            resolved_profile=resolved_profile,
            resolved_horse_number="3",
        )
        sync_p0_horse_sources(commit=True)

        conflict.refresh_from_db()
        self.assertEqual(conflict.status, HorseIdentityConflictStatus.PENDING)
        self.assertIsNone(conflict.resolved_profile)
        self.assertEqual(conflict.resolved_horse_number, "")
        self.assertEqual(
            conflict.evidence_payload["resolution_failure"]["reason"],
            "resolved_member_missing_source_url",
        )
        self.assertFalse(HorseP0Source.objects.filter(race_event=event, status="active").exists())

    def test_resolved_number_conflict_without_selected_member_returns_to_pending(self):
        from unittest.mock import patch

        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Missing Selected Member", external_horse_id="MISSING-MEMBER")
        first_result = event.results.get()
        first_result.horse_number = "3"
        first_result.save(update_fields=["horse_number", "updated_at"])
        RaceEventResult.objects.create(
            event=event,
            horse_number="8",
            horse_name="Missing Selected Member",
            finish_position=2,
            source_refs={
                "result": "https://example.com/result/8",
                "source": "official",
                "external_horse_id": "MISSING-MEMBER",
            },
        )
        sync_p0_horse_sources(commit=True)
        conflict = HorseIdentityConflict.objects.get(race_event=event)
        resolved_profile = self._profile(
            primary_term=self._term(source="Missing Selected Member Profile"),
            original_name="Missing Selected Member",
        )
        conflict.status = HorseIdentityConflictStatus.RESOLVED
        conflict.resolved_profile = resolved_profile
        conflict.resolved_horse_number = "3"
        conflict.full_clean()
        conflict.save(
            update_fields=["status", "resolved_profile", "resolved_horse_number", "updated_at"]
        )

        with patch("stable.services.p0_horse_profiles._resolved_conflict_member", return_value=None):
            sync_p0_horse_sources(commit=True)

        conflict.refresh_from_db()
        self.assertEqual(conflict.status, HorseIdentityConflictStatus.PENDING)
        self.assertIsNone(conflict.resolved_profile)
        self.assertEqual(conflict.resolved_horse_number, "")
        self.assertEqual(
            conflict.evidence_payload["resolution_failure"]["reason"],
            "resolved_member_missing",
        )

    def test_idempotency_backfill_reads_external_id_from_source_refs(self):
        import importlib

        from django.apps import apps
        from stable.services.horse_race_records import upsert_race_record

        profile = self._profile()
        record = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="Source Refs Race",
            race_year=2026,
            source_name="",
            source_url="https://example.com/source-refs-race",
            source_refs={
                "source": "official",
                "external_result_id": "  RESULT-FROM-SOURCE-REFS  ",
            },
            raw_payload={},
            idempotency_key="",
        )
        migration = importlib.import_module("stable.migrations.0027_p0_horse_profile_completion")

        migration.backfill_horse_record_idempotency_keys(apps, None)

        record.refresh_from_db()
        expected_raw = f"{profile.id}|external|official|RESULT-FROM-SOURCE-REFS"
        self.assertEqual(record.idempotency_key, hashlib.sha256(expected_raw.encode("utf-8")).hexdigest())
        self.assertEqual(record.source_name, "official")

        result = upsert_race_record(
            profile,
            {
                "race_name": "Source Refs Race",
                "race_year": 2026,
                "source_name": "official",
                "source_url": "https://example.com/source-refs-race",
                "external_result_id": "RESULT-FROM-SOURCE-REFS",
            },
        )

        self.assertEqual(result.record.id, record.id)
        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=profile).count(), 1)

    def test_cross_source_id_difference_stays_ambiguous_without_pedigree_identity(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        term = self._term(source="Twin Star", region=RacingRegion.UNITED_STATES)
        profile = self._profile(
            primary_term=term,
            original_name="Twin Star",
            english_name="Twin Star",
            source_refs={"horse_identity_keys": ["netkeiba:TWIN-A"]},
        )
        event = self._race_event(
            region=RacingRegion.UNITED_STATES,
            horse_name="Twin Star",
            source_namespace="hkjc",
            external_horse_id="TWIN-B",
        )

        summary = sync_p0_horse_sources(commit=True)

        self.assertEqual(summary["ambiguous_participants"], 1)
        self.assertEqual(HorseProfile.objects.filter(original_name="Twin Star").count(), 1)
        self.assertFalse(HorseP0Source.objects.filter(profile=profile, race_event=event).exists())
        self.assertTrue(
            HorseIdentityConflict.objects.filter(
                candidate_profiles=profile,
                race_event=event,
                status=HorseIdentityConflictStatus.PENDING,
            ).exists()
        )

    def test_duplicate_source_identity_records_conflict_for_every_matched_profile(self):
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        profiles = [
            self._profile(
                primary_term=self._term(source=name),
                original_name=name,
                source_refs={"horse_identity_keys": ["official:COLLISION"]},
            )
            for name in ("First Runner", "Second Runner")
        ]
        self._race_event(
            horse_name="Unknown Runner",
            source_namespace="official",
            external_horse_id="COLLISION",
        )

        summary = sync_p0_horse_sources(commit=True)

        self.assertEqual(summary["ambiguous_participants"], 1)
        conflict = HorseIdentityConflict.objects.get(status=HorseIdentityConflictStatus.PENDING)
        self.assertEqual(set(conflict.candidate_profiles.all()), set(profiles))

    def test_identity_conflict_is_persisted_without_existing_profile(self):
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        terms = [self._term(source="Twin Star") for _ in range(2)]
        event = self._race_event(horse_name="Twin Star", external_horse_id="")

        summary = sync_p0_horse_sources(commit=True)

        self.assertEqual(summary["ambiguous_participants"], 1)
        conflict = HorseIdentityConflict.objects.get(race_event=event)
        self.assertEqual(conflict.status, HorseIdentityConflictStatus.PENDING)
        self.assertEqual(set(conflict.candidate_terms.all()), set(terms))
        self.assertEqual(conflict.candidate_profiles.count(), 0)

    def test_resolved_identity_conflict_is_applied_on_next_sync(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        terms = [self._term(source="Twin Star") for _ in range(2)]
        event = self._race_event(horse_name="Twin Star", external_horse_id="")
        sync_p0_horse_sources(commit=True)
        conflict = HorseIdentityConflict.objects.get(race_event=event)
        resolved_profile = self._profile(
            primary_term=terms[0],
            original_name="Twin Star",
            english_name="Twin Star",
        )
        conflict.status = HorseIdentityConflictStatus.RESOLVED
        conflict.resolved_profile = resolved_profile
        conflict.full_clean()
        conflict.save(update_fields=["status", "resolved_profile", "updated_at"])

        summary = sync_p0_horse_sources(commit=True)

        self.assertEqual(summary["major_race_sources"], 1)
        self.assertTrue(HorseP0Source.objects.filter(profile=resolved_profile, race_event=event).exists())

    def test_pedigree_identity_matches_multilingual_name_to_existing_profile(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        term = self._term(source="Forever Young", target="青春永驻", region=RacingRegion.JAPAN)
        profile = self._profile(primary_term=term, racing_region=RacingRegion.JAPAN)
        event = self._race_event(
            region=RacingRegion.UNITED_STATES,
            horse_name="青春永驻",
            source_namespace="hkjc",
            external_horse_id="HK-FY",
        )
        result = event.results.get()
        result.raw_payload.update(
            {
                "sire_name": "Real Steel",
                "dam_name": "Forever Darling",
                "birth_year": 2021,
            }
        )
        result.save(update_fields=["raw_payload", "updated_at"])

        summary = sync_p0_horse_sources(commit=True)

        self.assertEqual(summary["ambiguous_participants"], 0)
        self.assertEqual(HorseProfile.objects.filter(primary_term=term).count(), 1)
        self.assertTrue(HorseP0Source.objects.filter(profile=profile, race_event=event).exists())
        profile.refresh_from_db()
        self.assertIn("hkjc:hk-fy", profile.source_refs["horse_identity_keys"])

    def test_multilingual_identity_index_prefetches_term_aliases(self):
        from stable.services.p0_horse_profiles import _horse_name_identity_index

        terms = [self._term(source=f"Runner {index}") for index in range(4)]
        for index, term in enumerate(terms):
            TermAlias.objects.create(
                term=term,
                source_language=SourceLanguage.CHINESE,
                text=f"赛驹{index}",
            )

        with self.assertNumQueries(2):
            identity_index = _horse_name_identity_index()

        self.assertIn(terms[0].id, identity_index["赛驹0"])

    def test_existing_event_binding_does_not_override_corrected_external_identity(self):
        from stable.models import HorseP0Source, HorseP0SourceStatus
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(
            region=RacingRegion.UNITED_STATES,
            horse_name="Twin Star",
            source_namespace="official",
            external_horse_id="TWIN-A",
        )
        sync_p0_horse_sources(commit=True)
        old_source = HorseP0Source.objects.get(race_event=event, source_type="major_race_participant")
        result = event.results.get()
        result.source_refs["external_horse_id"] = "TWIN-B"
        result.raw_payload["horse_id"] = "TWIN-B"
        result.save(update_fields=["source_refs", "raw_payload", "updated_at"])

        summary = sync_p0_horse_sources(commit=True, reconcile=True)
        old_source.refresh_from_db()

        self.assertEqual(summary["ambiguous_participants"], 0)
        self.assertEqual(old_source.status, HorseP0SourceStatus.REVOKED)
        self.assertEqual(HorseProfile.objects.filter(original_name="Twin Star").count(), 2)
        active_source = HorseP0Source.objects.get(
            race_event=event,
            source_type="major_race_participant",
            status=HorseP0SourceStatus.ACTIVE,
        )
        self.assertIn("official:twin-b", active_source.profile.source_refs["horse_identity_keys"])

    def test_full_reconcile_keeps_existing_source_when_identity_is_ambiguous(self):
        from stable.models import HorseP0Source, HorseP0SourceStatus
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(horse_name="Twin Star")
        sync_p0_horse_sources(commit=True)
        source = HorseP0Source.objects.get(race_event=event)
        duplicate_term = self._term(source="Twin Star", region=RacingRegion.UNITED_STATES)
        self._profile(primary_term=duplicate_term, original_name="Twin Star", english_name="Twin Star")
        result = event.results.get()
        result.source_refs.pop("external_horse_id", None)
        result.raw_payload = {}
        result.save(update_fields=["source_refs", "raw_payload", "updated_at"])

        summary = sync_p0_horse_sources(commit=True, reconcile=True)
        source.refresh_from_db()

        self.assertEqual(summary["ambiguous_participants"], 1)
        self.assertEqual(source.status, HorseP0SourceStatus.ACTIVE)

    def test_conflict_flag_creates_latest_conflict_audit(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import apply_reviewed_completion_artifact, evaluate_full_profile_completeness

        profile = self._profile(completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL)
        self._complete_records(profile)
        HorseP0Source.objects.create(profile=profile, source_type="manual", source_url="https://example.com/profile")
        self._approve_required_modules(profile)
        row = self._reviewed_artifact_row(profile)
        row["module_reviews"]["race_record"]["conflict"] = "new_source_disagrees"

        apply_reviewed_completion_artifact(
            {"reviewed": True, "reviewer_id": self.user.id, "rows": [row]},
            commit=True,
        )

        latest = profile.data_candidates.filter(module=HorseProfileModule.RACE_RECORD).order_by("-fetched_at", "-id").first()
        self.assertEqual(latest.status, "conflict")
        self.assertFalse(evaluate_full_profile_completeness(profile).is_complete)

    def test_generic_completeness_refresh_preserves_valid_full_profile(self):
        from stable.models import HorseP0Source
        from stable.services.horse_profiles import update_completeness

        profile = self._profile(completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL)
        self._complete_records(profile)
        HorseP0Source.objects.create(profile=profile, source_type="manual", source_url="https://example.com/profile")
        self._approve_required_modules(profile)

        result = update_completeness(profile)

        self.assertEqual(result, HorseProfileCompleteness.COMPLETE_PROFILE_FULL)
        profile.refresh_from_db()
        self.assertEqual(profile.completeness_status, HorseProfileCompleteness.COMPLETE_PROFILE_FULL)

    def test_queue_uses_home_region_once_and_prioritizes_manual_source(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import build_p0_completion_queue

        term_profile = self._profile(original_name="Term First", english_name="Term First", racing_region=RacingRegion.JAPAN)
        manual_profile = self._profile(
            primary_term=self._term(source="Manual First", region=RacingRegion.JAPAN),
            original_name="Manual First",
            english_name="Manual First",
            racing_region=RacingRegion.JAPAN,
        )
        HorseP0Source.objects.create(
            profile=term_profile,
            source_type="term_active_with_zh",
            racing_region=RacingRegion.JAPAN,
        )
        HorseP0Source.objects.create(
            profile=term_profile,
            source_type="major_race_participant",
            racing_region=RacingRegion.UNITED_STATES,
            horse_name="Term First",
        )
        HorseP0Source.objects.create(
            profile=manual_profile,
            source_type="manual",
            racing_region=RacingRegion.JAPAN,
        )

        queue = build_p0_completion_queue(
            regions=[RacingRegion.JAPAN, RacingRegion.UNITED_STATES],
            limit_per_region=1,
        )

        self.assertEqual([item.profile_id for item in queue[RacingRegion.JAPAN]], [manual_profile.id])
        self.assertEqual(queue[RacingRegion.UNITED_STATES], [])

    def test_queue_prioritizes_incomplete_profile_before_complete_manual_profile(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import build_p0_completion_queue

        incomplete_profile = self._profile(
            primary_term=self._term(source="Incomplete Queue Horse", region=RacingRegion.JAPAN),
            racing_region=RacingRegion.JAPAN,
            completeness_status=HorseProfileCompleteness.EMPTY,
        )
        complete_profile = self._profile(
            primary_term=self._term(source="Complete Queue Horse", region=RacingRegion.JAPAN),
            racing_region=RacingRegion.JAPAN,
            completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL,
        )
        HorseP0Source.objects.create(
            profile=incomplete_profile,
            source_type="term_active_with_zh",
            racing_region=RacingRegion.JAPAN,
        )
        HorseP0Source.objects.create(
            profile=complete_profile,
            source_type="manual",
            racing_region=RacingRegion.JAPAN,
        )

        queue = build_p0_completion_queue(
            regions=[RacingRegion.JAPAN],
            limit_per_region=1,
        )

        self.assertEqual([item.profile_id for item in queue[RacingRegion.JAPAN]], [incomplete_profile.id])

    def test_queue_prioritizes_stale_retired_profile_and_ignores_empty_external_keys(self):
        from stable.models import HorseP0Source, HorseRacingCareerStatus
        from stable.services.p0_horse_profiles import build_p0_completion_queue

        stale_profile = self._profile(
            primary_term=self._term(source="Stale Retired Queue Horse", region=RacingRegion.JAPAN),
            racing_region=RacingRegion.JAPAN,
            completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL,
            racing_career_status=HorseRacingCareerStatus.RETIRED,
            records_synced_through=datetime(2026, 1, 1).date(),
            source_refs={"horse_identity_keys": []},
        )
        fresh_profile = self._profile(
            primary_term=self._term(source="Fresh Retired Queue Horse", region=RacingRegion.JAPAN),
            racing_region=RacingRegion.JAPAN,
            completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL,
            racing_career_status=HorseRacingCareerStatus.RETIRED,
            records_synced_through=datetime(2026, 11, 8).date(),
        )
        self._complete_records(stale_profile)
        self._complete_records(fresh_profile)
        for profile in (stale_profile, fresh_profile):
            HorseP0Source.objects.create(
                profile=profile,
                source_type="manual",
                racing_region=RacingRegion.JAPAN,
            )

        queue = build_p0_completion_queue(
            regions=[RacingRegion.JAPAN],
            limit_per_region=1,
        )

        self.assertEqual([item.profile_id for item in queue[RacingRegion.JAPAN]], [stale_profile.id])
        self.assertNotIn("external_identity", queue[RacingRegion.JAPAN][0].reasons)

    def test_identity_conflict_notification_task_notifies_admin(self):
        from stable.tasks import notify_p0_horse_identity_conflicts_task

        HorseIdentityConflict.objects.create(
            fingerprint="identity-notification",
            horse_name="Twin Star",
            source_url="https://example.com/race",
            status=HorseIdentityConflictStatus.PENDING,
        )

        with patch("stable.tasks.send_ops_notification") as notify:
            result = notify_p0_horse_identity_conflicts_task.run()

        self.assertEqual(result["conflict_count"], 1)
        notify.assert_called_once()
        self.assertEqual(
            notify.call_args.kwargs["payload"]["admin_url"],
            f"{django_settings.DJANGO_ADMIN_URL}stable/horseidentityconflict/?status__exact=pending",
        )

    def test_admin_can_filter_and_resolve_identity_conflict(self):
        from django.contrib import admin

        from stable.admin import HorseIdentityConflictAdmin
        from stable.tasks import notify_p0_horse_identity_conflicts_task

        conflict = HorseIdentityConflict.objects.create(
            fingerprint="identity-admin-resolution",
            horse_name="Twin Star",
            status=HorseIdentityConflictStatus.PENDING,
        )
        profile = self._profile()
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("admin:stable_horseidentityconflict_changelist"),
            {"status__exact": HorseIdentityConflictStatus.PENDING},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Twin Star")
        conflict.status = HorseIdentityConflictStatus.RESOLVED
        conflict.resolved_profile = profile
        conflict.resolution_notes = "已人工确认并完成术语拆分"
        request = Mock(user=self.user)
        HorseIdentityConflictAdmin(HorseIdentityConflict, admin.site).save_model(
            request,
            conflict,
            form=Mock(),
            change=True,
        )
        conflict.refresh_from_db()
        self.assertEqual(conflict.resolved_by, self.user)
        self.assertIsNotNone(conflict.resolved_at)
        with patch("stable.tasks.send_ops_notification") as notify:
            result = notify_p0_horse_identity_conflicts_task.run()
        self.assertEqual(result["conflict_count"], 0)
        notify.assert_not_called()

    def test_sync_revokes_missing_managed_sources_without_deleting_history(self):
        from stable.models import HorseP0Source, HorseP0SourceStatus
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        term = self._term(target="青春永驻", region=RacingRegion.JAPAN)
        profile = self._profile(primary_term=term, racing_region=RacingRegion.JAPAN)
        sync_p0_horse_sources(commit=True)
        source = HorseP0Source.objects.get(profile=profile, source_type="term_active_with_zh")
        term.is_active = False
        term.save(update_fields=["is_active", "updated_at"])

        summary = sync_p0_horse_sources(commit=True, reconcile=True)
        source.refresh_from_db()

        self.assertEqual(summary["revoked_sources"], 1)
        self.assertEqual(source.status, HorseP0SourceStatus.REVOKED)
        self.assertIsNotNone(source.revoked_at)
        self.assertTrue(source.revoked_reason)

    def test_scoped_source_sync_does_not_revoke_other_regions(self):
        from stable.models import HorseP0Source, HorseP0SourceStatus
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        term = self._term(target="青春永驻", region=RacingRegion.JAPAN)
        profile = self._profile(primary_term=term, racing_region=RacingRegion.JAPAN)
        sync_p0_horse_sources(commit=True)
        source = HorseP0Source.objects.get(profile=profile, source_type="term_active_with_zh")
        term.is_active = False
        term.save(update_fields=["is_active", "updated_at"])

        summary = sync_p0_horse_sources(commit=True, regions=[RacingRegion.UNITED_STATES], reconcile=True)
        source.refresh_from_db()

        self.assertEqual(summary["revoked_sources"], 0)
        self.assertEqual(source.status, HorseP0SourceStatus.ACTIVE)

    def test_full_reconcile_preserves_existing_source_when_url_is_temporarily_missing(self):
        from stable.models import HorseP0Source, HorseP0SourceStatus
        from stable.services.p0_horse_profiles import sync_p0_horse_sources

        event = self._race_event(external_horse_id="FY-001")
        sync_p0_horse_sources(commit=True)
        source = HorseP0Source.objects.get(race_event=event)
        result = event.results.get()
        result.source_refs = {"source": "official", "external_horse_id": "FY-001"}
        result.raw_payload = {"horse_id": "FY-001"}
        result.save(update_fields=["source_refs", "raw_payload", "updated_at"])
        event.source_refs = {}
        event.save(update_fields=["source_refs", "updated_at"])

        summary = sync_p0_horse_sources(commit=True, reconcile=True)
        source.refresh_from_db()

        self.assertEqual(summary["missing_source_url_participants"], 1)
        self.assertEqual(summary["revoked_sources"], 0)
        self.assertEqual(source.status, HorseP0SourceStatus.ACTIVE)

    def test_conflict_candidate_cannot_be_applied_through_generic_endpoint(self):
        profile = self._profile(country="美国")
        candidate = HorseProfileDataCandidate.objects.create(
            profile=profile,
            module=HorseProfileModule.PROFILE,
            source_name="p0_completion_artifact",
            status=HorseProfileCandidateStatus.CONFLICT,
            candidate_payload={"country": "法国"},
        )
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("console-horse-profile-apply-candidate", args=[candidate.id]),
            {"action": "apply"},
        )

        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        candidate.refresh_from_db()
        self.assertEqual(profile.country, "美国")
        self.assertEqual(candidate.status, HorseProfileCandidateStatus.CONFLICT)

    def test_management_command_supports_profile_ids_and_explicit_full_reconcile(self):
        from stable.services import p0_horse_profiles

        output = StringIO()
        with patch.object(p0_horse_profiles, "build_p0_completion_queue", return_value={}) as build_queue:
            call_command("p0_horse_profiles", "--queue", "--profile-id", "42", "--json", stdout=output)
        build_queue.assert_called_once_with(regions=None, limit_per_region=10, profile_ids=[42])

        with patch.object(p0_horse_profiles, "sync_p0_horse_sources", return_value={}) as sync_sources:
            call_command("p0_horse_profiles", "--sync-sources", "--commit", "--full-reconcile", stdout=StringIO())
        sync_sources.assert_called_once_with(commit=True, regions=None, reconcile=True)

        with self.assertRaises(CommandError):
            call_command(
                "p0_horse_profiles",
                "--sync-sources",
                "--commit",
                "--full-reconcile",
                "--region",
                RacingRegion.JAPAN,
                stdout=StringIO(),
            )

    def test_first_publish_remains_manual_after_profile_becomes_complete(self):
        from stable.models import HorseP0Source
        from stable.services.p0_horse_profiles import mark_profile_completion_ready

        profile = self._profile(review_status=HorseProfileStatus.DRAFT)
        self._complete_records(profile)
        HorseP0Source.objects.create(profile=profile, source_type="term_active_with_zh", source_url="https://example.com/term")

        result = mark_profile_completion_ready(profile, reviewer=self.user)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("review.source_url", result["blocking_reasons"])

        profile.source_refs = {"p0_completion": "https://example.com/horse-profile"}
        profile.save(update_fields=["source_refs", "updated_at"])
        result = mark_profile_completion_ready(profile, reviewer=self.user)
        profile.refresh_from_db()

        self.assertEqual(result["status"], "ready_for_manual_publish")
        self.assertEqual(profile.review_status, HorseProfileStatus.READY)
        self.assertIsNone(profile.published_at)
        self.assertNotEqual(profile.review_status, HorseProfileStatus.PUBLISHED)

    def test_public_horse_pages_never_trigger_p0_sync_or_completion_adapters(self):
        from stable.services import p0_horse_profiles

        profile = self._profile(review_status=HorseProfileStatus.PUBLISHED)
        with patch.object(p0_horse_profiles, "sync_p0_horse_sources") as sync_sources, patch.object(
            p0_horse_profiles,
            "complete_p0_horse_profiles",
        ) as complete_profiles:
            index_response = self.client.get(reverse("public-horse-index"))
            detail_response = self.client.get(reverse("public-horse-detail", args=[profile.id]))

        self.assertEqual(index_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        sync_sources.assert_not_called()
        complete_profiles.assert_not_called()

    def test_public_horse_detail_uses_original_name_when_translation_is_pending(self):
        profile = self._profile(
            display_name_zh="",
            original_name="Forever Young",
            english_name="Forever Young",
            review_status=HorseProfileStatus.PUBLISHED,
        )

        response = self.client.get(reverse("public-horse-detail", args=[profile.id]))

        self.assertContains(response, "Forever Young")
        self.assertContains(response, "中文译名待补")

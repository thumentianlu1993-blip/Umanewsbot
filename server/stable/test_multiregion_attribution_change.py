from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings, tag
from django.test.utils import CaptureQueriesContext

from stable.models import (
    NewsArticle,
    NewsArticleRelatedRegion,
    NewsSource,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TermEntry,
    TermType,
)
from stable.services.news_attribution import (
    ATTRIBUTION_RULE_VERSION,
    apply_article_attribution,
    filter_articles_visible_in_region,
    infer_article_attribution,
    related_region_queries_enabled,
)
from stable.services.terms import source_term_matches_text


UTC = dt_timezone.utc
NOW = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)


def article_with_text(
    title: str,
    body: str = "",
    *,
    region: str = RacingRegion.UNITED_STATES,
    source_site: str = SourceSite.TDN,
    locked: bool = False,
    source_config: NewsSource | None = None,
) -> NewsArticle:
    return NewsArticle.objects.create(
        source_config=source_config,
        source_site=source_site,
        source_mode=SourceMode.LATEST,
        source_article_id=f"attribution-{NewsArticle.objects.count()}",
        source_url=f"https://example.com/attribution/{NewsArticle.objects.count()}",
        racing_region=region,
        source_language=SourceLanguage.ENGLISH,
        title_ja=title,
        body_ja_raw=body or title,
        body_ja_normalized=body or title,
        published_at=NOW,
        attribution_locked=locked,
    )


def add_term(text: str, term_type: str, region: str) -> TermEntry:
    return TermEntry.objects.create(
        source_ja=text,
        target_zh=f"{text}-zh",
        source_language=SourceLanguage.ENGLISH,
        term_type=term_type,
        racing_region=region,
        is_active=True,
    )


class AttributionModelContractTests(TestCase):
    def test_article_structured_attribution_fields_are_indexable(self):
        status = NewsArticle._meta.get_field("attribution_status")
        confidence = NewsArticle._meta.get_field("attribution_confidence")
        version = NewsArticle._meta.get_field("attribution_rule_version")

        self.assertTrue(status.db_index)
        self.assertTrue(status.blank)
        self.assertTrue(confidence.null)
        self.assertTrue(version.blank)

    def test_run_ledger_and_lock_have_correct_foreign_key(self):
        from stable.models import MultiregionAttributionLock, MultiregionAttributionRun

        field = MultiregionAttributionLock._meta.get_field("locked_by_run")
        self.assertIs(field.remote_field.model, MultiregionAttributionRun)
        self.assertTrue(MultiregionAttributionRun._meta.get_field("manifest_sha256").db_index)
        self.assertIsNotNone(MultiregionAttributionRun._meta.get_field("cursor"))
        self.assertIsNotNone(MultiregionAttributionRun._meta.get_field("completed_article_ids"))

    def test_related_region_cannot_equal_primary_region(self):
        article = article_with_text("France Galop update", region=RacingRegion.FRANCE)
        link = NewsArticleRelatedRegion(article=article, region=RacingRegion.FRANCE)

        with self.assertRaises(ValidationError):
            link.full_clean()

    def test_leaf_migration_contains_all_new_article_fields_and_run_models(self):
        executor = MigrationExecutor(connection)
        state = executor.loader.project_state(executor.loader.graph.leaf_nodes("stable"))
        article_model = state.apps.get_model("stable", "NewsArticle")
        article_fields = {field.name for field in article_model._meta.get_fields()}

        self.assertTrue(
            {
                "published_at_verified",
                "published_at_evidence",
                "translation_error_category",
                "translation_next_retry_at",
                "translation_retry_exhausted_at",
                "attribution_status",
                "attribution_confidence",
                "attribution_rule_version",
            }.issubset(article_fields)
        )
        run_model = state.apps.get_model("stable", "MultiregionAttributionRun")
        lock_model = state.apps.get_model("stable", "MultiregionAttributionLock")
        self.assertEqual(lock_model._meta.get_field("locked_by_run").remote_field.model, run_model)


class ChangeSettingsContractTests(TestCase):
    def test_new_behavior_defaults_are_safe(self):
        self.assertEqual(settings.MULTIREGION_ATTRIBUTION_MODE, "off")
        self.assertFalse(settings.MULTIREGION_RELATED_REGION_QUERIES_ENABLED)
        self.assertFalse(settings.TRANSLATION_AUTO_RETRY_ENABLED)
        self.assertEqual(settings.TRANSLATION_AUTO_RETRY_MAX_ATTEMPTS, 3)
        self.assertEqual(settings.TRANSLATION_AUTO_RETRY_BACKOFF_SECONDS, [60, 300, 900])
        self.assertEqual(settings.TDN_FRANCE_FRESHNESS_DAYS, 3)
        self.assertEqual(settings.MULTIREGION_ATTRIBUTION_GOLD_MIN_TOTAL, 150)
        self.assertEqual(settings.MULTIREGION_ATTRIBUTION_GOLD_MIN_PER_REGION, 10)
        self.assertEqual(settings.MULTIREGION_ATTRIBUTION_GOLD_MIN_CROSS_REGION, 20)
        self.assertEqual(settings.MULTIREGION_ATTRIBUTION_RELATED_RECALL_MIN, 0.50)

    def test_example_env_and_both_production_compose_files_expose_safe_defaults(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        env_text = (repo_root / ".env.example").read_text()
        self.assertIn("MULTIREGION_ATTRIBUTION_MODE=off", env_text)
        self.assertIn("MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false", env_text)
        self.assertIn("MULTIREGION_ATTRIBUTION_GOLD_MIN_TOTAL=150", env_text)
        self.assertIn("MULTIREGION_ATTRIBUTION_GOLD_MIN_PER_REGION=10", env_text)
        self.assertIn("MULTIREGION_ATTRIBUTION_GOLD_MIN_CROSS_REGION=20", env_text)
        self.assertIn("MULTIREGION_ATTRIBUTION_RELATED_RECALL_MIN=0.50", env_text)
        self.assertIn("TRANSLATION_AUTO_RETRY_ENABLED=false", env_text)
        for filename in ("docker-compose.prod.yml", "docker-compose.prod.lowcost.yml"):
            with self.subTest(filename=filename):
                compose_text = (repo_root / filename).read_text()
                self.assertIn("MULTIREGION_ATTRIBUTION_MODE", compose_text)
                self.assertIn("MULTIREGION_ATTRIBUTION_GOLD_MIN_TOTAL", compose_text)
                self.assertIn("MULTIREGION_ATTRIBUTION_GOLD_MIN_PER_REGION", compose_text)
                self.assertIn("MULTIREGION_ATTRIBUTION_GOLD_MIN_CROSS_REGION", compose_text)
                self.assertIn("MULTIREGION_ATTRIBUTION_RELATED_RECALL_MIN", compose_text)
                self.assertIn("TRANSLATION_AUTO_RETRY_ENABLED", compose_text)


class AttributionModeTests(TestCase):
    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="off",
        MULTIREGION_ATTRIBUTION_ENABLED=True,
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
    )
    def test_new_mode_takes_precedence_over_legacy_boolean(self):
        from stable.services.news_attribution import attribution_mode

        self.assertEqual(attribution_mode(), "off")
        self.assertFalse(related_region_queries_enabled())

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="",
        MULTIREGION_ATTRIBUTION_ENABLED=True,
    )
    def test_legacy_true_maps_to_enforce_when_new_mode_absent(self):
        from stable.services.news_attribution import attribution_mode

        self.assertEqual(attribution_mode(), "enforce")

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="shadow",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
    )
    def test_shadow_writes_only_shadow_audit_and_preserves_applied_summary(self):
        article = article_with_text("Prix de Diane at Chantilly", region=RacingRegion.UNITED_STATES)
        article.attribution_summary = {"applied": {"primary_region": RacingRegion.UNITED_STATES, "rule_version": "old"}}
        article.save(update_fields=["attribution_summary", "updated_at"])

        apply_article_attribution(article, save=True)

        article.refresh_from_db()
        self.assertEqual(article.racing_region, RacingRegion.UNITED_STATES)
        self.assertEqual(article.attribution_summary["applied"]["rule_version"], "old")
        self.assertEqual(article.attribution_summary["shadow"]["primary_region"], RacingRegion.FRANCE)
        self.assertFalse(article.related_region_links.exists())

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="web_test_groups",
    )
    def test_enforce_applies_regions_and_enables_related_queries(self):
        add_term("Japanese Star", TermType.HORSE, RacingRegion.JAPAN)
        article = article_with_text(
            "Japanese Star targets Prix de Diane at Chantilly",
            region=RacingRegion.UNITED_STATES,
        )

        apply_article_attribution(article, save=True, is_new_article=True)

        article.refresh_from_db()
        self.assertEqual(article.racing_region, RacingRegion.FRANCE)
        self.assertEqual(
            set(article.related_region_links.values_list("region", flat=True)),
            {RacingRegion.JAPAN},
        )
        self.assertTrue(filter_articles_visible_in_region(NewsArticle.objects.all(), RacingRegion.JAPAN).filter(pk=article.pk).exists())

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_RELATED_REGION_QUERIES_ENABLED=True,
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="new_articles",
    )
    def test_related_queries_stay_disabled_until_web_test_group_stage(self):
        self.assertFalse(related_region_queries_enabled())

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="new_articles",
    )
    def test_new_articles_stage_enforces_only_new_ingestion_and_shadows_existing_articles(self):
        existing = article_with_text("Prix de Diane at Chantilly", region=RacingRegion.UNITED_STATES)
        fresh = article_with_text("Prix de Diane at Chantilly", region=RacingRegion.UNITED_STATES)

        apply_article_attribution(existing, save=True, is_new_article=False)
        apply_article_attribution(fresh, save=True, is_new_article=True)

        existing.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(existing.racing_region, RacingRegion.UNITED_STATES)
        self.assertEqual(existing.attribution_summary["shadow"]["primary_region"], RacingRegion.FRANCE)
        self.assertEqual(fresh.racing_region, RacingRegion.FRANCE)

    @override_settings(MULTIREGION_ATTRIBUTION_MODE="off")
    def test_legacy_flat_summary_is_read_as_applied_without_rewrite(self):
        from stable.services.news_attribution import attribution_summary_namespace

        summary = {"primary_region": RacingRegion.FRANCE, "rule_version": "legacy-v1"}

        self.assertEqual(attribution_summary_namespace(summary, "applied"), summary)
        self.assertEqual(attribution_summary_namespace(summary, "shadow"), {})


class AttributionEvidenceHierarchyTests(TestCase):
    def assertResult(
        self,
        result,
        primary: str,
        related: set[str] | None = None,
        status: str = "applied",
    ):
        self.assertEqual(result.primary_region, primary)
        self.assertEqual(set(result.related_regions), related or set())
        self.assertEqual(result.status, status)
        self.assertIn(result.confidence_band, {"high", "medium", "low"})
        self.assertGreaterEqual(result.confidence, 0)
        self.assertTrue(result.rule_version)
        self.assertIn("positive", result.evidence)
        self.assertIn("negative", result.evidence)

    def test_five_regions_have_event_centre_precedence(self):
        cases = [
            ("Japan Cup at Tokyo Racecourse", RacingRegion.JAPAN),
            ("Hong Kong Derby at Sha Tin", RacingRegion.HONG_KONG),
            ("The Derby at Epsom", RacingRegion.UNITED_KINGDOM),
            ("Prix de Diane at Chantilly", RacingRegion.FRANCE),
            ("Kentucky Derby at Churchill Downs", RacingRegion.UNITED_STATES),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                result = infer_article_attribution(article_with_text(title))
                self.assertResult(result, expected)

    def test_overseas_event_is_primary_and_subject_origin_is_related(self):
        add_term("Liberty Island", TermType.HORSE, RacingRegion.JAPAN)
        add_term("Christophe Soumillon", TermType.JOCKEY, RacingRegion.FRANCE)
        article = article_with_text(
            "Liberty Island and Christophe Soumillon target Breeders' Cup at Del Mar"
        )

        result = infer_article_attribution(article)

        self.assertResult(
            result,
            RacingRegion.UNITED_STATES,
            {RacingRegion.JAPAN, RacingRegion.FRANCE},
        )

    def test_japanese_title_country_shorthand_can_identify_foreign_event(self):
        article = article_with_text(
            "25日英キングジョージの馬券発売決定!日本調教馬が出走予定",
            region=RacingRegion.JAPAN,
            source_site=SourceSite.JRA,
        )

        result = infer_article_attribution(article)

        self.assertResult(result, RacingRegion.UNITED_KINGDOM, {RacingRegion.JAPAN})

    def test_explicit_country_result_bulletin_uses_foreign_event_region(self):
        article = article_with_text(
            "英ダービー（G1）の結果",
            region=RacingRegion.JAPAN,
            source_site=SourceSite.JRA,
        )

        result = infer_article_attribution(article)

        self.assertResult(result, RacingRegion.UNITED_KINGDOM)

    def test_result_bulletin_without_country_prefix_keeps_japanese_source(self):
        article = article_with_text(
            "ジュライカップ（G1）の結果",
            region=RacingRegion.JAPAN,
            source_site=SourceSite.JRA,
        )

        result = infer_article_attribution(article)

        self.assertResult(result, RacingRegion.JAPAN, {RacingRegion.UNITED_KINGDOM})

    def test_local_event_is_not_overridden_by_one_word_horse_match(self):
        add_term("Relish", TermType.HORSE, RacingRegion.JAPAN)
        article = article_with_text(
            "Hayes and Eustace relish tournament theme at Happy Valley",
            region=RacingRegion.HONG_KONG,
            source_site=SourceSite.HKJC_NEWS,
        )

        result = infer_article_attribution(article)

        self.assertResult(result, RacingRegion.HONG_KONG)

    def test_ambiguous_one_word_event_does_not_override_global_source(self):
        add_term("Oaks", TermType.RACE, RacingRegion.UNITED_KINGDOM)
        article = article_with_text(
            "Maximum Offer Gate To Wire In Indiana Oaks",
            region=RacingRegion.UNITED_STATES,
        )

        result = infer_article_attribution(article)

        self.assertResult(result, RacingRegion.UNITED_STATES, status="fallback")

    def test_explicit_title_subject_can_outrank_local_event(self):
        article = article_with_text(
            "Team Hong Kong set for Shergar Cup at Ascot",
            region=RacingRegion.UNITED_KINGDOM,
            source_site=SourceSite.SPORTING_LIFE,
        )

        result = infer_article_attribution(article)

        self.assertResult(result, RacingRegion.HONG_KONG, {RacingRegion.UNITED_KINGDOM})

    def test_global_source_uses_unique_lead_context_when_title_is_ambiguous(self):
        article = article_with_text(
            "Future Prospects Best Of The July Delights",
            "Newmarket's July Festival and the July Cup are the focus of the week.",
            region=RacingRegion.UNITED_STATES,
        )

        result = infer_article_attribution(article)

        self.assertResult(result, RacingRegion.UNITED_KINGDOM)

    def test_supported_and_out_of_scope_partnership_keeps_source_and_related_other(self):
        article = article_with_text(
            "York And Dubai Racing Club Announce International Partnership",
            region=RacingRegion.UNITED_STATES,
        )

        result = infer_article_attribution(article)

        self.assertResult(result, RacingRegion.UNITED_STATES, {RacingRegion.OTHER})

    def test_france_breeding_auction_and_institution_topics_are_primary_france(self):
        cases = [
            "France Galop announces new integrity programme",
            "Arqana August Yearling Sale catalogue released",
            "Haras de Bouquetot welcomes a new stallion",
            "Chantilly training centre publishes stable update",
        ]
        for title in cases:
            with self.subTest(title=title):
                self.assertResult(infer_article_attribution(article_with_text(title)), RacingRegion.FRANCE)

    def test_source_url_and_source_note_do_not_decide_primary_region(self):
        article = article_with_text("Trainer confirms routine stable update", region=RacingRegion.UNITED_STATES)
        article.source_url = "https://example.com/france/chantilly/prix-story"
        article.source_note = "French racing France Galop Longchamp"
        article.save(update_fields=["source_url", "source_note", "updated_at"])

        result = infer_article_attribution(article)

        self.assertEqual(result.primary_region, RacingRegion.UNITED_STATES)
        self.assertEqual(result.source, "source_fallback")

    def test_ordinary_word_term_does_not_create_region_evidence(self):
        add_term("Contact", TermType.HORSE, RacingRegion.UNITED_KINGDOM)
        article = article_with_text("Contact and live updates from the racing desk", region=RacingRegion.FRANCE)

        result = infer_article_attribution(article)

        self.assertEqual(result.primary_region, RacingRegion.FRANCE)
        self.assertNotIn(RacingRegion.UNITED_KINGDOM, result.related_regions)

    def test_batch_term_index_preserves_alias_case_and_word_boundaries(self):
        from stable.models import TermAlias
        from stable.services.news_attribution import AttributionBatchContext

        horse = add_term("Liberty Island", TermType.HORSE, RacingRegion.JAPAN)
        TermAlias.objects.create(
            term=horse,
            source_language=SourceLanguage.ENGLISH,
            text="LIBERTY ISLAND",
        )
        add_term("Contact", TermType.HORSE, RacingRegion.UNITED_KINGDOM)
        article = article_with_text(
            "Liberty Island targets Breeders' Cup at Del Mar",
            "The contractual update contains no separate horse named Contact.",
        )

        result = infer_article_attribution(article, batch_context=AttributionBatchContext.build())

        self.assertResult(
            result,
            RacingRegion.UNITED_STATES,
            {RacingRegion.JAPAN},
        )
        self.assertNotIn(RacingRegion.UNITED_KINGDOM, result.related_regions)

    def test_batch_term_index_shortlists_unrelated_terms(self):
        from stable.services.news_attribution import AttributionBatchContext

        for index in range(200):
            add_term(f"Unrelated Candidate {index}", TermType.HORSE, RacingRegion.UNITED_KINGDOM)
        liberty_island = add_term("Liberty Island", TermType.HORSE, RacingRegion.JAPAN)
        article = article_with_text("Liberty Island targets Breeders' Cup at Del Mar")
        context = AttributionBatchContext.build()

        with patch(
            "stable.services.news_attribution.source_term_matches_text",
            wraps=source_term_matches_text,
        ) as matcher:
            indexed_matches = context.term_indexes[SourceLanguage.ENGLISH].match(
                article.title_ja,
                SourceLanguage.ENGLISH,
            )

        result = infer_article_attribution(article, batch_context=context)

        self.assertResult(
            result,
            RacingRegion.UNITED_STATES,
            {RacingRegion.JAPAN},
        )
        self.assertEqual(set(indexed_matches), {liberty_island.pk})
        self.assertLess(matcher.call_count, 10)
        self.assertGreater(context.preload_counts["indexed_candidates"], 0)

    def test_historical_record_and_pedigree_background_do_not_override_centre(self):
        add_term("American Sire", TermType.HORSE, RacingRegion.UNITED_STATES)
        article = article_with_text(
            "Prix de Diane at Chantilly preview",
            "The French race is the focus. The dam once raced in America and is by American Sire.",
        )

        result = infer_article_attribution(article)

        self.assertEqual(result.primary_region, RacingRegion.FRANCE)
        self.assertNotIn(RacingRegion.UNITED_STATES, result.related_regions)

    def test_conflicting_event_centres_fail_closed(self):
        article = article_with_text("Late changes for both Prix de Diane at Chantilly and The Derby at Epsom")

        result = infer_article_attribution(article)

        self.assertResult(result, RacingRegion.UNITED_STATES, status="needs_review")
        self.assertEqual(result.related_regions, [])
        self.assertIn("conflicting_event_centres", result.conflict_reasons)

    def test_more_than_three_related_regions_fails_closed_without_truncating(self):
        add_term("Japan Horse", TermType.HORSE, RacingRegion.JAPAN)
        add_term("Hong Kong Rider", TermType.JOCKEY, RacingRegion.HONG_KONG)
        add_term("British Trainer", TermType.TRAINER, RacingRegion.UNITED_KINGDOM)
        add_term("French Owner", TermType.OWNER, RacingRegion.FRANCE)
        article = article_with_text(
            "Japan Horse, Hong Kong Rider, British Trainer and French Owner target Kentucky Derby at Churchill Downs"
        )

        result = infer_article_attribution(article)

        self.assertResult(result, RacingRegion.UNITED_STATES, status="needs_review")
        self.assertEqual(result.related_regions, [])
        self.assertIn("related_region_spread", result.conflict_reasons)

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="new_articles",
    )
    def test_enforce_needs_review_only_saves_candidate_audit(self):
        article = article_with_text(
            "Late changes for both Prix de Diane at Chantilly and The Derby at Epsom",
            region=RacingRegion.UNITED_STATES,
        )

        result = apply_article_attribution(article, save=True, is_new_article=True)

        article.refresh_from_db()
        self.assertEqual(result.status, "needs_review")
        self.assertEqual(article.racing_region, RacingRegion.UNITED_STATES)
        self.assertEqual(
            article.attribution_summary["review_candidate"]["primary_region"],
            RacingRegion.UNITED_STATES,
        )
        self.assertFalse(article.related_region_links.exists())

    @override_settings(
        MULTIREGION_ATTRIBUTION_MODE="enforce",
        MULTIREGION_ATTRIBUTION_ROLLOUT_STAGE="new_articles",
    )
    def test_other_region_can_be_persisted_as_related_evidence(self):
        article = article_with_text(
            "York And Dubai Racing Club Announce International Partnership",
            region=RacingRegion.UNITED_STATES,
        )

        result = apply_article_attribution(article, save=True, is_new_article=True)

        article.refresh_from_db()
        self.assertEqual(result.primary_region, RacingRegion.UNITED_STATES)
        self.assertEqual(
            set(article.related_region_links.values_list("region", flat=True)),
            {RacingRegion.OTHER},
        )

    def test_real_three_region_story_is_preserved(self):
        add_term("Japanese Star", TermType.HORSE, RacingRegion.JAPAN)
        add_term("British Rider", TermType.JOCKEY, RacingRegion.UNITED_KINGDOM)
        article = article_with_text("Japanese Star and British Rider target Prix de Diane at Chantilly")

        result = infer_article_attribution(article)

        self.assertResult(
            result,
            RacingRegion.FRANCE,
            {RacingRegion.JAPAN, RacingRegion.UNITED_KINGDOM},
        )

    def test_locked_article_is_never_modified(self):
        article = article_with_text(
            "Prix de Diane at Chantilly",
            region=RacingRegion.UNITED_STATES,
            locked=True,
        )

        result = apply_article_attribution(article, save=True)

        article.refresh_from_db()
        self.assertEqual(article.racing_region, RacingRegion.UNITED_STATES)
        self.assertEqual(result.status, "locked_skip")
        self.assertFalse(article.related_region_links.exists())


class GoldSetQualityTests(TestCase):
    def labels(self, *, per_region: int = 50, cross_region: int = 50):
        from stable.services.attribution_quality import GoldLabel

        labels = []
        regions = [
            RacingRegion.JAPAN,
            RacingRegion.HONG_KONG,
            RacingRegion.UNITED_KINGDOM,
            RacingRegion.FRANCE,
            RacingRegion.UNITED_STATES,
        ]
        for region in regions:
            for index in range(per_region):
                labels.append(
                    GoldLabel(
                        key=f"{region}-{index}",
                        article_id=index + 1,
                        source_url=f"https://example.com/{region}/{index}",
                        input_sha256=f"{index:064x}"[-64:],
                        expected_primary_region=region,
                        expected_related_regions=[regions[(regions.index(region) + 1) % len(regions)]] if len(labels) < cross_region else [],
                        reviewer_roles=["reviewer_a", "reviewer_b"],
                        rationale="Fixture label",
                        adjudicated=True,
                    )
                )
        return labels

    def test_unresolved_and_sha_drifted_labels_are_excluded_from_denominator(self):
        from stable.services.attribution_quality import evaluate_gold_set

        labels = self.labels()
        labels[0] = replace(labels[0], adjudicated=False)
        actual = {label.key: {"input_sha256": label.input_sha256, "primary_region": label.expected_primary_region, "related_regions": label.expected_related_regions} for label in labels}
        actual[labels[1].key]["input_sha256"] = "f" * 64

        report = evaluate_gold_set(labels, actual)

        self.assertEqual(report.total_labels, 250)
        self.assertEqual(report.valid_denominator, 248)
        self.assertEqual(report.unresolved_count, 1)
        self.assertEqual(report.drifted_count, 1)

    def test_any_region_below_ten_valid_samples_is_no_go(self):
        from stable.services.attribution_quality import evaluate_gold_set

        labels = self.labels()
        for index in range(len(labels) - 41, len(labels)):
            labels[index] = replace(labels[index], adjudicated=False)
        actual = {label.key: {"input_sha256": label.input_sha256, "primary_region": label.expected_primary_region, "related_regions": label.expected_related_regions} for label in labels}

        report = evaluate_gold_set(labels, actual)

        self.assertFalse(report.qualified)
        self.assertEqual(report.region_valid_counts[RacingRegion.UNITED_STATES], 9)
        self.assertIn("region_sample_count", report.no_go_reasons)

    def test_unresolved_rows_do_not_satisfy_150_valid_sample_minimum(self):
        from stable.services.attribution_quality import evaluate_gold_set

        labels = self.labels(per_region=32)
        for index in range(50, 55):
            labels[index] = replace(labels[index], adjudicated=False)
        actual = {
            label.key: {
                "input_sha256": label.input_sha256,
                "primary_region": label.expected_primary_region,
                "related_regions": label.expected_related_regions,
            }
            for label in labels
        }

        report = evaluate_gold_set(labels, actual)

        self.assertEqual(report.total_labels, 160)
        self.assertEqual(report.valid_denominator, 155)
        self.assertTrue(report.qualified)

        for index in range(55, 61):
            labels[index] = replace(labels[index], adjudicated=False)
        report = evaluate_gold_set(labels, actual)
        self.assertEqual(report.valid_denominator, 149)
        self.assertFalse(report.qualified)
        self.assertIn("total_sample_count", report.no_go_reasons)

    def test_single_region_accuracy_failure_is_not_hidden_by_overall_score(self):
        from stable.services.attribution_quality import evaluate_gold_set

        labels = self.labels(per_region=50)
        actual = {label.key: {"input_sha256": label.input_sha256, "primary_region": label.expected_primary_region, "related_regions": label.expected_related_regions} for label in labels}
        france = [label for label in labels if label.expected_primary_region == RacingRegion.FRANCE]
        for label in france[:6]:
            actual[label.key]["primary_region"] = RacingRegion.UNITED_KINGDOM

        report = evaluate_gold_set(labels, actual)

        self.assertGreaterEqual(report.primary_accuracy, 0.95)
        self.assertLess(report.region_primary_accuracy[RacingRegion.FRANCE], 0.90)
        self.assertFalse(report.qualified)

    def test_other_labels_are_reported_without_becoming_a_sixth_region_gate(self):
        from stable.services.attribution_quality import GoldLabel, evaluate_gold_set

        labels = self.labels(per_region=50)
        other = GoldLabel(
            key="other-0",
            article_id=999,
            source_url="https://example.com/other/0",
            input_sha256="f" * 64,
            expected_primary_region=RacingRegion.OTHER,
            expected_related_regions=[],
            reviewer_roles=["reviewer_a", "reviewer_b"],
            rationale="非五个运营地区样本",
            adjudicated=True,
        )
        labels.append(other)
        actual = {
            label.key: {
                "input_sha256": label.input_sha256,
                "primary_region": label.expected_primary_region,
                "related_regions": label.expected_related_regions,
            }
            for label in labels
        }

        report = evaluate_gold_set(labels, actual)

        self.assertEqual(report.region_valid_counts[RacingRegion.OTHER], 1)
        self.assertNotIn("region_sample_count", report.no_go_reasons)
        self.assertNotIn("region_accuracy", report.no_go_reasons)
        self.assertTrue(report.qualified)

    def test_report_includes_precision_recall_spread_lock_and_wilson_intervals(self):
        from stable.services.attribution_quality import evaluate_gold_set

        labels = self.labels(per_region=50)
        actual = {label.key: {"input_sha256": label.input_sha256, "primary_region": label.expected_primary_region, "related_regions": label.expected_related_regions} for label in labels}

        report = evaluate_gold_set(labels, actual)

        self.assertGreaterEqual(report.related_precision, 0.95)
        self.assertGreaterEqual(report.related_recall, 0.50)
        self.assertLessEqual(report.unsupported_primary_change_rate, 0.02)
        self.assertLessEqual(report.over_expansion_rate, 0.01)
        self.assertEqual(report.locked_override_count, 0)
        self.assertIn("primary_accuracy", report.wilson_intervals)
        self.assertTrue(report.qualified)

    def test_related_recall_at_fifty_percent_can_qualify_when_precision_is_high(self):
        from stable.services.attribution_quality import evaluate_gold_set

        labels = self.labels(per_region=50)
        actual = {
            label.key: {
                "input_sha256": label.input_sha256,
                "primary_region": label.expected_primary_region,
                "related_regions": label.expected_related_regions,
            }
            for label in labels
        }
        related_labels = [label for label in labels if label.expected_related_regions]
        for label in related_labels[:25]:
            actual[label.key]["related_regions"] = []

        report = evaluate_gold_set(labels, actual)

        self.assertEqual(report.related_precision, 1.0)
        self.assertEqual(report.related_recall, 0.5)
        self.assertNotIn("related_recall", report.no_go_reasons)
        self.assertTrue(report.qualified)

    def test_related_recall_below_fifty_percent_remains_no_go(self):
        from stable.services.attribution_quality import evaluate_gold_set

        labels = self.labels(per_region=50)
        actual = {
            label.key: {
                "input_sha256": label.input_sha256,
                "primary_region": label.expected_primary_region,
                "related_regions": label.expected_related_regions,
            }
            for label in labels
        }
        related_labels = [label for label in labels if label.expected_related_regions]
        for label in related_labels[:26]:
            actual[label.key]["related_regions"] = []

        report = evaluate_gold_set(labels, actual)

        self.assertEqual(report.related_precision, 1.0)
        self.assertEqual(report.related_recall, 0.48)
        self.assertIn("related_recall", report.no_go_reasons)
        self.assertFalse(report.qualified)

    def test_related_precision_below_ninety_five_percent_is_no_go_even_with_full_recall(self):
        from stable.services.attribution_quality import evaluate_gold_set

        labels = self.labels(per_region=50)
        actual = {
            label.key: {
                "input_sha256": label.input_sha256,
                "primary_region": label.expected_primary_region,
                "related_regions": list(label.expected_related_regions),
            }
            for label in labels
        }
        for label in labels[50:53]:
            actual[label.key]["related_regions"] = [RacingRegion.FRANCE]

        report = evaluate_gold_set(labels, actual)

        self.assertLess(report.related_precision, 0.95)
        self.assertEqual(report.related_recall, 1.0)
        self.assertIn("related_precision", report.no_go_reasons)
        self.assertFalse(report.qualified)


class AttributionRunLedgerTests(TransactionTestCase):
    reset_sequences = True

    def test_lock_prevents_overlapping_runs_and_can_be_renewed(self):
        from stable.services.attribution_runs import acquire_attribution_lease, create_attribution_run, renew_attribution_lease

        first = create_attribution_run(mode="dry_run", selectors={"hours": 72})
        second = create_attribution_run(mode="dry_run", selectors={"hours": 72})

        self.assertTrue(acquire_attribution_lease(first, now=NOW).acquired)
        self.assertFalse(acquire_attribution_lease(second, now=NOW).acquired)
        renewed = renew_attribution_lease(first, now=NOW + timedelta(minutes=20))
        self.assertEqual(renewed.expires_at, NOW + timedelta(minutes=50))

    def test_commit_requires_successful_dry_run_and_matching_manifest(self):
        from stable.services.attribution_runs import commit_attribution_run, create_attribution_run

        run = create_attribution_run(mode="dry_run", selectors={"hours": 72}, status="failed")

        with self.assertRaises(ValidationError):
            commit_attribution_run(run.id, manifest_sha256="0" * 64)

    def test_partial_failure_saves_cursor_and_resume_skips_completed_articles(self):
        from stable.services.attribution_runs import commit_attribution_run, create_attribution_dry_run

        articles = [article_with_text(f"Prix de Diane at Chantilly {index}") for index in range(3)]
        run = create_attribution_dry_run(articles, rule_version=ATTRIBUTION_RULE_VERSION, gold_version="gold-v1", metrics={"qualified": True})

        with patch("stable.services.attribution_runs.apply_run_outcome", side_effect=[None, RuntimeError("database interruption")]):
            first = commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)

        run.refresh_from_db()
        self.assertEqual(first.status, "partial")
        self.assertEqual(run.cursor, 1)
        self.assertEqual(run.completed_article_ids, [articles[0].id])

        second = commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256, resume=True)
        run.refresh_from_db()
        self.assertEqual(second.status, "completed")
        self.assertEqual(run.completed_article_ids, [article.id for article in articles])

    def test_repeated_commit_of_same_manifest_is_idempotent(self):
        from stable.services.attribution_runs import commit_attribution_run, create_attribution_dry_run

        article = article_with_text("Prix de Diane at Chantilly")
        run = create_attribution_dry_run([article], rule_version=ATTRIBUTION_RULE_VERSION, gold_version="gold-v1", metrics={"qualified": True})

        first = commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)
        second = commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)

        self.assertEqual(first.applied_ids, [article.id])
        self.assertEqual(second.applied_ids, [])
        self.assertEqual(second.already_completed_ids, [article.id])
        self.assertEqual(NewsArticleRelatedRegion.objects.filter(article=article).count(), 0)

    def test_rule_term_gold_article_or_lock_drift_is_reported_and_skipped(self):
        from stable.services.attribution_runs import commit_attribution_run, create_attribution_dry_run

        article = article_with_text("Prix de Diane at Chantilly")
        run = create_attribution_dry_run([article], rule_version=ATTRIBUTION_RULE_VERSION, term_version="terms-v1", gold_version="gold-v1", metrics={"qualified": True})
        article.attribution_locked = True
        article.save(update_fields=["attribution_locked", "updated_at"])

        result = commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)

        self.assertEqual(result.applied_ids, [])
        self.assertEqual(result.drifted[article.id], "attribution_locked")

    def test_commit_applies_reviewed_manifest_outcome_without_recomputing(self):
        from stable.services.attribution_runs import commit_attribution_run, create_attribution_dry_run

        article = article_with_text("Prix de Diane at Chantilly", region=RacingRegion.UNITED_STATES)
        run = create_attribution_dry_run([article], rule_version=ATTRIBUTION_RULE_VERSION, gold_version="gold-v1", metrics={"qualified": True})

        with patch(
            "stable.services.news_attribution.infer_article_attribution",
            side_effect=AssertionError("commit must not infer again"),
        ):
            result = commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)

        article.refresh_from_db()
        self.assertEqual(result.applied_ids, [article.id])
        self.assertEqual(article.racing_region, RacingRegion.FRANCE)

    def test_term_snapshot_drift_rejects_commit(self):
        from stable.services.attribution_runs import commit_attribution_run, create_attribution_dry_run

        article = article_with_text("Prix de Diane at Chantilly")
        run = create_attribution_dry_run([article], rule_version=ATTRIBUTION_RULE_VERSION, gold_version="gold-v1", metrics={"qualified": True})
        add_term("Newly Added Horse", TermType.HORSE, RacingRegion.JAPAN)

        with self.assertRaises(ValidationError):
            commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)

    def test_stale_rule_version_rejects_commit(self):
        from stable.services.attribution_runs import commit_attribution_run, create_attribution_dry_run

        article = article_with_text("Prix de Diane at Chantilly")
        run = create_attribution_dry_run(
            [article],
            rule_version="multiregion-v2",
            gold_version="gold-v1",
            metrics={"qualified": True},
        )

        with self.assertRaisesMessage(ValidationError, "归属规则版本已漂移"):
            commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)

    def test_commit_respects_lease_held_by_another_run(self):
        from stable.services.attribution_runs import (
            acquire_attribution_lease,
            commit_attribution_run,
            create_attribution_dry_run,
            create_attribution_run,
        )

        blocker = create_attribution_run(mode="dry_run", selectors={"kind": "blocker"})
        self.assertTrue(acquire_attribution_lease(blocker).acquired)
        article = article_with_text("Prix de Diane at Chantilly")
        run = create_attribution_dry_run([article], rule_version=ATTRIBUTION_RULE_VERSION, gold_version="gold-v1", metrics={"qualified": True})

        with self.assertRaises(ValidationError):
            commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)

    def test_gate_failure_is_part_of_cursor_and_resume(self):
        from stable.services.attribution_runs import commit_attribution_run, create_attribution_dry_run

        articles = [article_with_text(f"Prix de Diane at Chantilly {index}") for index in range(2)]
        run = create_attribution_dry_run(articles, rule_version=ATTRIBUTION_RULE_VERSION, gold_version="gold-v1", metrics={"qualified": True})

        with patch(
            "stable.services.attribution_runs.apply_validation_outcome",
            side_effect=[None, RuntimeError("gate interrupted")],
            create=True,
        ):
            first = commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)

        run.refresh_from_db()
        self.assertEqual(first.status, "partial")
        self.assertEqual(run.completed_article_ids, [articles[0].id])

        second = commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256, resume=True)
        self.assertEqual(second.status, "completed")

    def test_pending_or_unqualified_gold_run_cannot_commit(self):
        from stable.services.attribution_runs import commit_attribution_run, create_attribution_dry_run

        article = article_with_text("Prix de Diane at Chantilly")
        run = create_attribution_dry_run(
            [article],
            rule_version=ATTRIBUTION_RULE_VERSION,
            gold_version="pending-review",
        )

        with self.assertRaises(ValidationError):
            commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)

    def test_manifest_binds_versions_snapshots_and_metrics(self):
        from stable.services.attribution_runs import commit_attribution_run, create_attribution_dry_run

        article = article_with_text("Prix de Diane at Chantilly")
        run = create_attribution_dry_run(
            [article],
            rule_version=ATTRIBUTION_RULE_VERSION,
            term_version="terms-v1",
            gold_version="gold-v1",
            metrics={"qualified": True},
        )
        run.term_version = "tampered-after-review"
        run.save(update_fields=["term_version", "updated_at"])

        with self.assertRaises(ValidationError):
            commit_attribution_run(run.id, manifest_sha256=run.manifest_sha256)


class AttributionCommandContractTests(TestCase):
    def test_single_review_flag_requires_gold_labels(self):
        with self.assertRaisesMessage(CommandError, "--single-review-gold 必须与 --gold-labels 一起使用"):
            call_command(
                "reprocess_multiregion_attribution_gates",
                dry_run=True,
                single_review_gold=True,
            )


@tag("postgresql", "performance")
class AttributionPostgresPerformanceTests(TestCase):
    databases = {"default"}

    def test_250_article_batch_stays_within_sql_time_and_rss_budget(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL-only production performance contract")
        from stable.services.attribution_quality import benchmark_attribution_batch

        source = NewsSource.objects.create(
            name="TDN performance source",
            homepage_url="https://example.com/",
            feed_url="https://example.com/feed",
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH,
        )
        created_articles = [
            article_with_text(
                f"Prix de Diane at Chantilly fixture {index}",
                source_config=source,
            )
            for index in range(250)
        ]
        articles = list(
            NewsArticle.objects.filter(id__in=[article.id for article in created_articles]).order_by("id")
        )

        with CaptureQueriesContext(connection) as queries:
            report = benchmark_attribution_batch(articles)

        self.assertLessEqual(len(queries), 30)
        self.assertLessEqual(report.elapsed_seconds, 30)
        self.assertLessEqual(report.rss_delta_bytes, 256 * 1024 * 1024)
        self.assertEqual(report.preload_counts["term_index_builds"], 1)
        self.assertEqual(report.preload_counts["sources"], 1)

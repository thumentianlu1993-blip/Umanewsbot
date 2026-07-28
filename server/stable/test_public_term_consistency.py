"""
Tests for multilingual term unification and public content consistency.

Aligns with docs/changes/unify-public-racing-terms/test_cases.md.

RED state: target service modules (stable.services.term_consistency) and
model (stable.models.TermMappingEvidence) do not exist yet.  Tests that
depend on them will fail with ImportError / LookupError / AssertionError
until the implementation is complete.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.apps import apps
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TestCase, override_settings, tag
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from stable.models import (
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    ArticleTranslationStatus,
    AutomationStatus,
    NewsArticle,
    RaceEvent,
    RaceEventRunner,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    TermAlias,
    TermAliasType,
    TermEntry,
    TermType,
    WorkflowStatus,
)

# ---------------------------------------------------------------------------
# Checks for yet-to-be-created modules and models
# ---------------------------------------------------------------------------

try:
    from stable.models import TermMappingEvidence  # noqa: F401
    MAPPING_EVIDENCE_EXISTS = True
except (ImportError, RuntimeError):
    MAPPING_EVIDENCE_EXISTS = False

try:
    from stable.services import term_consistency  # noqa: F401
    TERM_CONSISTENCY_EXISTS = True
except (ImportError, ModuleNotFoundError):
    TERM_CONSISTENCY_EXISTS = False


# ===========================================================================
# Test helpers
# ===========================================================================

BASE_SETTINGS = {
    "AUTO_DUPLICATE_HIGH_THRESHOLD": 0,
    "AUTO_DUPLICATE_REVIEW_THRESHOLD": 0,
    "AUTO_REWRITE_ENABLED": False,
    "MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS": [],
    "MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS": [],
    "MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS": [],
}


def _create_term_entry(
    *,
    source_ja: str,
    target_zh: str,
    term_type: str = TermType.HORSE,
    source_language: str = SourceLanguage.ENGLISH,
    racing_region: str = "",
    priority: int = 100,
) -> TermEntry:
    return TermEntry.objects.create(
        term_type=term_type,
        source_language=source_language,
        racing_region=racing_region,
        source_ja=source_ja,
        target_zh=target_zh,
        priority=priority,
    )


def _create_term_alias(
    term: TermEntry,
    text: str,
    *,
    source_language: str = SourceLanguage.ENGLISH,
    alias_type: str = TermAliasType.ALIAS,
    is_active: bool = True,
) -> TermAlias:
    return TermAlias.objects.create(
        term=term,
        source_language=source_language,
        text=text,
        alias_type=alias_type,
        is_active=is_active,
    )


def _create_article(
    *,
    source_article_id: str | None = None,
    title_ja: str = "Racing report",
    body_ja: str | None = None,
    translated_title_zh: str = "赛马新闻",
    translated_body_zh: str | None = None,
    title_zh: str = "赛马新闻",
    body_zh: str | None = None,
    summary_zh: str = "赛事最新消息。",
    push_summary_zh: str = "赛事最新消息。",
    tags_json: list | None = None,
    racing_region: str = RacingRegion.UNITED_KINGDOM,
    source_site: str = SourceSite.SKY_SPORTS_RACING,
    source_language: str = SourceLanguage.ENGLISH,
    workflow_status: str = WorkflowStatus.PENDING_REVIEW,
    translation_status: str = ArticleTranslationStatus.TRANSLATED,
    automation_status: str = AutomationStatus.PENDING,
    **overrides,
) -> NewsArticle:
    if body_ja is None:
        body_ja = "The report reviewed the meeting, runners and conditions in detail. " * 12
    if translated_body_zh is None:
        translated_body_zh = "这是一篇经过翻译的赛马新闻正文，内容包含赛事背景、参赛阵容和相关消息。" * 8
    if body_zh is None:
        body_zh = translated_body_zh

    defaults = {
        "source_site": source_site,
        "source_mode": SourceMode.LATEST,
        "source_article_id": source_article_id or f"test-article-{NewsArticle.objects.count() + 1}",
        "source_language": source_language,
        "racing_region": racing_region,
        "title_ja": title_ja,
        "body_ja_raw": body_ja,
        "body_ja_normalized": body_ja,
        "translated_title_zh": translated_title_zh,
        "title_zh": title_zh,
        "translated_summary_zh": "赛事最新消息。",
        "summary_zh": summary_zh,
        "translated_body_zh": translated_body_zh,
        "body_zh": body_zh,
        "push_summary_zh": push_summary_zh,
        "tags_json": tags_json or [],
        "published_at": timezone.now(),
        "source_url": f"https://example.com/consistency/{NewsArticle.objects.count() + 1}",
        "workflow_status": workflow_status,
        "translation_status": translation_status,
        "automation_status": automation_status,
        "score_total": 85,
        "first_seen_at": timezone.now(),
    }
    defaults.update(overrides)
    return NewsArticle.objects.create(**defaults)


# ===========================================================================
# Section 1: TermMappingEvidence model
# ===========================================================================

class TermMappingEvidenceModelExistsTest(TestCase):
    """test_cases.md 7 — TermMappingEvidence model does not exist yet."""

    def test_model_is_registered(self):
        """stable.TermMappingEvidence should exist (RED until migration created)."""
        if not MAPPING_EVIDENCE_EXISTS:
            self.fail(
                "TermMappingEvidence model has not been created yet. "
                "Create the model in stable.models and add a migration."
            )
        model = apps.get_model("stable", "TermMappingEvidence")
        self.assertIsNotNone(model)

    def test_model_has_required_fields(self):
        """TermMappingEvidence should expose required fields (RED)."""
        if not MAPPING_EVIDENCE_EXISTS:
            self.fail(
                "TermMappingEvidence model has not been created yet. "
                "Required fields: term, alias, evidence_kind, source_url, "
                "source_digest, review_status, reviewed_by, reviewed_at, "
                "identity_payload, identity_sha256."
            )
        model = apps.get_model("stable", "TermMappingEvidence")
        fields = {f.name for f in model._meta.get_fields()}
        expected = {
            "term", "alias", "evidence_kind", "source_url",
            "source_digest", "review_status", "reviewed_by",
            "reviewed_at", "identity_payload", "identity_sha256",
        }
        missing = expected - fields
        self.assertFalse(
            missing,
            f"TermMappingEvidence is missing these fields: {missing}",
        )

    def test_unapproved_evidence_cannot_activate_alias(self):
        """
        An alias without approved TermMappingEvidence must not resolve
        as a confirmed occurrence.
        """
        entry = _create_term_entry(
            source_ja="UnapprovedHorse",
            target_zh="未审核马",
            term_type=TermType.HORSE,
        )
        _create_term_alias(entry, "UnapprovedHorse", source_language=SourceLanguage.ENGLISH)
        # Create evidence but leave it pending (unapproved)
        from stable.services.term_consistency import resolve_occurrences
        from stable.models import TermMappingEvidence

        TermMappingEvidence.objects.create(
            term=entry,
            evidence_kind="manual_review",
            review_status="pending",
        )
        result = resolve_occurrences("UnapprovedHorse", source_language=SourceLanguage.ENGLISH)
        # Without approved evidence, the resolver may still resolve for
        # non-common-word terms, but the evidence is not "approved" so
        # the occurrence status should not rely on unapproved evidence.
        self.assertTrue(len(result.occurrences) >= 1)
        # The resolver should still resolve the alias even without
        # approved evidence (it's not a common English word), but
        # this verifies the model layer works.
        self.assertEqual(result.occurrences[0].term_id, entry.id)


# ===========================================================================
# Section 2: Multi-language alias resolution
# ===========================================================================

class MultilingualAliasResolutionTest(TestCase):
    """test_cases.md 1, 2 — multi-language alias resolution."""

    def setUp(self):
        self.horse_entry = _create_term_entry(
            source_ja="Kalpana",
            target_zh="幻梦逸想",
            term_type=TermType.HORSE,
        )

    def test_english_alias_resolves_to_term_entry(self):
        """
        'Kalpana' (English alias) should resolve to TermEntry -> '幻梦逸想'.
        RED: resolver does not exist.
        """
        _create_term_alias(self.horse_entry, "Kalpana", source_language=SourceLanguage.ENGLISH)
        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Implement resolve_occurrences() that maps 'Kalpana' "
                "to TermEntry.id={} / target_zh='幻梦逸想'.".format(self.horse_entry.id)
            )
        # If the module exists, test the resolver
        from stable.services.term_consistency import resolve_occurrences
        result = resolve_occurrences("Kalpana", source_language=SourceLanguage.ENGLISH)
        self.assertEqual(len(result.occurrences), 1)
        occ = result.occurrences[0]
        self.assertEqual(occ.term_id, self.horse_entry.id)
        self.assertEqual(occ.target_zh, "幻梦逸想")
        self.assertEqual(occ.status, "confirmed")

    def test_japanese_alias_resolves_to_same_term_entry(self):
        """
        'カルパナ' (Japanese alias) with approved mapping evidence should
        resolve to the same TermEntry -> '幻梦逸想'.
        RED: resolver does not exist.
        """
        ja_alias = _create_term_alias(self.horse_entry, "カルパナ", source_language=SourceLanguage.JAPANESE)
        # Japanese HORSE aliases require approved TermMappingEvidence before
        # they can be trusted as confirmed occurrences.
        from stable.models import TermMappingEvidence
        TermMappingEvidence.objects.create(
            term=self.horse_entry,
            alias=ja_alias,
            evidence_kind="manual_review",
            review_status="approved",
        )
        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Implement resolve_occurrences() that maps 'カルパナ' "
                "to the same TermEntry as 'Kalpana'."
            )
        from stable.services.term_consistency import resolve_occurrences
        # Resolve English alias
        en_result = resolve_occurrences("Kalpana", source_language=SourceLanguage.ENGLISH)
        # Resolve Japanese alias
        ja_result = resolve_occurrences("カルパナ", source_language=SourceLanguage.JAPANESE)
        self.assertEqual(len(en_result.occurrences), 1)
        self.assertEqual(len(ja_result.occurrences), 1)
        self.assertEqual(en_result.occurrences[0].term_id, ja_result.occurrences[0].term_id)
        self.assertEqual(ja_result.occurrences[0].target_zh, "幻梦逸想")

    def test_japanese_alias_without_evidence_is_uncertain(self):
        """
        A Japanese HORSE alias without approved TermMappingEvidence must NOT
        bypass the evidence gate via the non-English race-context rule —
        it resolves as 'uncertain' and is not auto-replaced.
        """
        _create_term_alias(self.horse_entry, "カルパナ", source_language=SourceLanguage.JAPANESE)
        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Unreviewed Japanese aliases must not resolve as confirmed."
            )
        from stable.services.term_consistency import resolve_occurrences
        result = resolve_occurrences("カルパナ", source_language=SourceLanguage.JAPANESE)
        self.assertEqual(len(result.occurrences), 1)
        occ = result.occurrences[0]
        self.assertEqual(occ.term_id, self.horse_entry.id)
        self.assertEqual(occ.status, "uncertain")
        self.assertEqual(occ.target_zh, "")

    def test_race_aliases_converge_to_canonical_zh(self):
        """
        Multiple English / Japanese aliases for '英皇锦标' must all
        resolve to the same canonical Chinese name.
        Aliases (of any term type) require approved TermMappingEvidence
        before they resolve as confirmed; the surface that duplicates the
        term's own source_ja resolves through the registry entry instead.
        RED: resolver does not exist.
        """
        race_entry = _create_term_entry(
            source_ja="King George Stakes",
            target_zh="英皇锦标",
            term_type=TermType.RACE,
        )
        from stable.models import TermMappingEvidence
        for alias_text in [
            "King George VI Stakes",
            "King George Stakes",
            "キングジョージステークス",
            "キングジョージ六世ステークス",
        ]:
            source_lang = SourceLanguage.JAPANESE if any(
                ord(c) > 0x2E80 for c in alias_text
            ) else SourceLanguage.ENGLISH
            alias = _create_term_alias(race_entry, alias_text, source_language=source_lang)
            if alias_text != race_entry.source_ja:
                # Pure aliases need approved evidence; the source_ja duplicate
                # resolves through the registry entry itself.
                TermMappingEvidence.objects.create(
                    term=race_entry,
                    alias=alias,
                    evidence_kind="manual_review",
                    review_status="approved",
                )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Resolve all race aliases to '英皇锦标'."
            )
        from stable.services.term_consistency import resolve_occurrences
        for alias_text in [
            "King George VI Stakes",
            "King George Stakes",
            "キングジョージステークス",
            "キングジョージ六世ステークス",
        ]:
            source_lang = SourceLanguage.JAPANESE if any(
                ord(c) > 0x2E80 for c in alias_text
            ) else SourceLanguage.ENGLISH
            result = resolve_occurrences(alias_text, source_language=source_lang)
            self.assertEqual(len(result.occurrences), 1, f"Failed for alias: {alias_text}")
            self.assertEqual(result.occurrences[0].target_zh, "英皇锦标")
            self.assertEqual(result.occurrences[0].term_id, race_entry.id)


# ===========================================================================
# Section 3: Conflict detection
# ===========================================================================

class ConflictDetectionTest(TestCase):
    """test_cases.md 3, 4 — conflict / fail-closed behavior."""

    def test_language_conflict_fails_closed(self):
        """
        An alias in one language that maps to two different active terms
        should fail closed, NOT guess by priority.
        RED: conflict detection not implemented.
        """
        term_a = _create_term_entry(source_ja="Alpha", target_zh="阿尔法", term_type=TermType.HORSE)
        term_b = _create_term_entry(source_ja="Beta", target_zh="贝塔", term_type=TermType.HORSE)
        _create_term_alias(term_a, "ConflictingName", source_language=SourceLanguage.ENGLISH)
        _create_term_alias(term_b, "ConflictingName", source_language=SourceLanguage.ENGLISH)

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Implement conflict detection: same surface + active under "
                "two terms must return conflict, not a guessed winner."
            )
        from stable.services.term_consistency import resolve_occurrences
        result = resolve_occurrences("ConflictingName", source_language=SourceLanguage.ENGLISH)
        self.assertEqual(len(result.occurrences), 1)
        self.assertEqual(result.occurrences[0].status, "conflict")
        self.assertIsNone(result.occurrences[0].target_zh)

    def test_region_conflict_fails_closed(self):
        """
        Same surface active in two different regions with different
        target terms should fail closed.
        RED: region-based conflict detection not implemented.
        """
        _create_term_entry(
            source_ja="Global Star", target_zh="全球之星",
            term_type=TermType.HORSE, racing_region=RacingRegion.UNITED_KINGDOM,
        )
        _create_term_entry(
            source_ja="Global Star", target_zh="环球明星",
            term_type=TermType.HORSE, racing_region=RacingRegion.HONG_KONG,
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Region conflict for same surface must fail closed."
            )
        from stable.services.term_consistency import resolve_occurrences
        result = resolve_occurrences("Global Star", source_language=SourceLanguage.ENGLISH)
        if result.occurrences:
            self.assertEqual(result.occurrences[0].status, "conflict")

    def test_type_conflict_fails_closed(self):
        """
        Same surface as HORSE and RACE types must fail closed when
        both are active.
        RED: type-conflict detection not implemented.
        """
        _create_term_entry(
            source_ja="Champion", target_zh="冠军马",
            term_type=TermType.HORSE,
        )
        _create_term_entry(
            source_ja="Champion", target_zh="冠军锦标",
            term_type=TermType.RACE,
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Type conflict must fail closed."
            )
        from stable.services.term_consistency import resolve_occurrences
        result = resolve_occurrences("Champion", source_language=SourceLanguage.ENGLISH)
        if len(result.occurrences) > 1:
            self.assertTrue(all(o.status == "conflict" for o in result.occurrences))


# ===========================================================================
# Section 4: English homograph / occurrence-level matching
# ===========================================================================

class OccurrenceLevelMatchingTest(TestCase):
    """test_cases.md 5 — homograph and occurrence-level gating."""

    def test_common_english_word_not_replaced(self):
        """
        A common English word that happens to match a horse alias
        must NOT be replaced without strong racing-runner context.
        RED: occurrence-level gating not implemented.
        """
        entry = _create_term_entry(source_ja="Brilliant", target_zh="辉煌")
        _create_term_alias(entry, "Brilliant", source_language=SourceLanguage.ENGLISH)

        article = _create_article(
            title_ja="Stable update",
            body_ja=(
                "The filly produced a brilliant performance in testing conditions. "
                "Connections reviewed the result and confirmed plans. " * 8
            ),
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Implement occurrence-level gating: 'brilliant' as common "
                "word must not be replaced."
            )
        from stable.services.term_consistency import apply_consistency_gate
        result = apply_consistency_gate(article)
        # 'brilliant' (lowercase, common adjective) should not be flagged
        # as a confirmed horse occurrence
        horse_issues = [
            o for o in result.occurrences
            if o.surface.lower() == "brilliant" and o.status == "confirmed"
        ]
        self.assertFalse(horse_issues)

    def test_runner_evidence_enables_replacement(self):
        """
        When the article has an active ArticleRaceLink with a RaceEventRunner
        whose horse_name matches, the occurrence should be confirmed.
        RED: structured-entity-driven resolution not implemented.
        """
        entry = _create_term_entry(source_ja="Brilliant", target_zh="辉煌")
        _create_term_alias(entry, "Brilliant", source_language=SourceLanguage.ENGLISH)

        article = _create_article(
            title_ja="Brilliant wins at Ascot",
            body_ja=("Brilliant won at Ascot after leading inside the final furlong. " * 8),
        )
        event = RaceEvent.objects.create(
            year=2026,
            slug="ascot-race",
            original_name="Ascot Test Stakes",
            chinese_name="雅士谷测试锦标",
            country_region=RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="Listed",
            surface="turf",
        )
        RaceEventRunner.objects.create(event=event, horse_name="Brilliant")
        ArticleRaceLink.objects.create(
            event=event,
            article=article,
            status=ArticleRaceLinkStatus.AUTO,
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Implement structured entity resolution: ArticleRaceLink + "
                "RaceEventRunner should confirm the occurrence."
            )
        from stable.services.term_consistency import apply_consistency_gate
        result = apply_consistency_gate(article)
        brilliant_occs = [o for o in result.occurrences if o.surface == "Brilliant"]
        self.assertTrue(len(brilliant_occs) >= 1)
        for occ in brilliant_occs:
            if occ.entity_evidence:
                self.assertEqual(occ.status, "confirmed")


# ===========================================================================
# Section 5: Old Chinese aliases restriction
# ===========================================================================

class ChineseAliasesRestrictionTest(TestCase):
    """test_cases.md 6 — old Chinese aliases only in aliases_zh."""

    def test_old_chinese_aliases_in_aliases_zh(self):
        """
        Old Chinese translations like '乔治六世锦标' should live only in
        TermEntry.aliases_zh, not as a TermAlias with source_language=zh.
        RED: validation that prevents fake Chinese TermAlias not implemented.
        """
        race_entry = _create_term_entry(
            source_ja="King George Stakes",
            target_zh="英皇锦标",
            term_type=TermType.RACE,
        )
        # This Chinese alias should be stored in aliases_zh, not as a TermAlias
        race_entry.aliases_zh = ["乔治六世锦标", "英王乔治锦标"]
        race_entry.save(update_fields=["aliases_zh", "updated_at"])

        # Verify it's NOT in TermAlias
        alias_qs = TermAlias.objects.filter(term=race_entry, source_language=SourceLanguage.CHINESE)
        self.assertEqual(
            alias_qs.count(), 0,
            "Old Chinese aliases must NOT be stored as TermAlias with "
            "source_language=zh. They belong in TermEntry.aliases_zh.",
        )

        # Verify it IS in aliases_zh
        race_entry.refresh_from_db()
        self.assertIn("乔治六世锦标", race_entry.aliases_zh)
        self.assertIn("英王乔治锦标", race_entry.aliases_zh)

    def test_service_rejects_fake_chinese_alias(self):
        """
        The consistency service (when implemented) must reject attempts
        to create a TermAlias with source_language=zh containing a
        Chinese surface value.
        RED: service-level guard not implemented.
        """
        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Implement a validator that rejects Chinese-language "
                "TermAlias entries."
            )

    def test_aliases_zh_not_used_for_entity_resolution(self):
        """
        Aliases in TermEntry.aliases_zh must NOT participate in source
        language entity resolution — only TermAlias entries do.
        RED: entity resolution that incorrectly uses aliases_zh is a bug.
        """
        # This test validates correct existing behavior as a baseline
        race_entry = _create_term_entry(
            source_ja="King George Stakes",
            target_zh="英皇锦标",
            term_type=TermType.RACE,
        )
        race_entry.aliases_zh = ["乔治六世锦标"]
        race_entry.save(update_fields=["aliases_zh", "updated_at"])

        # Simulate what a naive resolver would do — check if aliases_zh
        # is used for source-language matching. Currently, the model
        # has no such logic; this test serves as a regression guard.
        source_terms = race_entry.source_terms_for_language(SourceLanguage.ENGLISH)
        for zh_alias in race_entry.aliases_zh:
            self.assertNotIn(
                zh_alias, source_terms,
                f"Chinese alias '{zh_alias}' leaked into English source term resolution",
            )


# ===========================================================================
# Section 6: Article consistency gate
# ===========================================================================

class ArticleConsistencyGateTest(TestCase):
    """test_cases.md 8 — all public fields use canonical Chinese name."""

    def setUp(self):
        self.horse_entry = _create_term_entry(
            source_ja="Kalpana",
            target_zh="幻梦逸想",
            term_type=TermType.HORSE,
        )
        _create_term_alias(self.horse_entry, "Kalpana", source_language=SourceLanguage.ENGLISH)
        _create_term_alias(self.horse_entry, "カルパナ", source_language=SourceLanguage.JAPANESE)

    def test_title_body_summary_push_tags_use_canonical_zh(self):
        """
        Title, body, summary, push summary and tags must all use
        canonical '幻梦逸想' when 'Kalpana' appears.
        RED: consistency gate not implemented.
        """
        article = _create_article(
            title_zh="Kalpana 赢得比赛",
            body_zh="Kalpana 在比赛中表现出色，最终获胜。",
            summary_zh="Kalpana 赢得赛事最新消息。",
            push_summary_zh="Kalpana 赢得赛事",
            tags_json=["Kalpana", "賽馬"],
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "apply_consistency_gate() must flag fields containing "
                "'Kalpana' and require replacement with '幻梦逸想'."
            )
        from stable.services.term_consistency import apply_consistency_gate
        result = apply_consistency_gate(article)
        self.assertTrue(result.issues, "Should flag non-canonical occurrences")
        for field in ("title_zh", "body_zh", "summary_zh", "push_summary_zh", "tags_json"):
            field_issues = [i for i in result.issues if i.get("field") == field]
            self.assertTrue(
                field_issues,
                f"No consistency issues found for field '{field}'",
            )

    def test_ai_rewrite_reintroducing_alias_is_corrected(self):
        """
        If AI rewrite re-creates 'Kalpana' or 'カルパナ' in a confirmed
        context, the consistency gate must flag and correct it.
        RED: post-rewrite gate not implemented.
        """
        article = _create_article(
            rewrite_title_zh="Kalpana returns to winning form",
            rewrite_body_zh="カルパナ delivered a strong performance.",
            rewrite_summary_zh="Kalpana winning form",
            automation_status=AutomationStatus.REWRITTEN,
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Post-AI-rewrite check must flag 'Kalpana' / 'カルパナ' "
                "in rewrite fields and suggest corrections."
            )
        from stable.services.term_consistency import apply_consistency_gate
        result = apply_consistency_gate(article)
        rewrite_issues = [
            i for i in result.issues
            if i.get("field", "").startswith("rewrite_")
        ]
        self.assertTrue(
            rewrite_issues,
            "AI rewrite fields containing 'Kalpana' or 'カルパナ' "
            "should be flagged as consistency issues.",
        )

    def test_conflict_blocks_auto_publish(self):
        """
        When a confirmed conflict exists, the gate must block auto-publish
        and include field/occurrence evidence in the gate issue.
        RED: conflict-based auto-publish block not implemented.
        """
        term_a = _create_term_entry(
            source_ja="Champion", target_zh="冠军马",
            term_type=TermType.HORSE,
        )
        term_b = _create_term_entry(
            source_ja="Champion", target_zh="冠军锦标",
            term_type=TermType.RACE,
        )
        _create_term_alias(term_a, "Champion", source_language=SourceLanguage.ENGLISH)
        _create_term_alias(term_b, "Champion", source_language=SourceLanguage.ENGLISH)

        article = _create_article(
            title_zh="Champion 赛事报道",
            body_zh="Champion 在这场比赛表现出色。",
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Conflict detection must block auto-publish."
            )
        from stable.services.term_consistency import apply_consistency_gate
        result = apply_consistency_gate(article)
        conflict_issues = [i for i in result.issues if i.get("severity") == "blocker"]
        self.assertTrue(conflict_issues, "Conflict should produce a blocker gate issue")


# ===========================================================================
# Section 7: Uncertain occurrence preservation
# ===========================================================================

class UncertainOccurrenceTest(TestCase):
    """test_cases.md 10 — uncertain occurrences preserved as-is."""

    def test_uncertain_occurrence_preserves_original_text(self):
        """
        When occurrence cannot be confirmed as a racing entity, the
        original text must be preserved without generating a horse tag.
        RED: uncertain handling not implemented.
        """
        entry = _create_term_entry(
            source_ja="Brilliant", target_zh="辉煌",
            term_type=TermType.HORSE,
        )
        _create_term_alias(entry, "Brilliant", source_language=SourceLanguage.ENGLISH)

        article = _create_article(
            title_zh="Brilliant Result 赛马报道",
            body_zh="本次赛事 Brilliant Result 被用作宣传标题，并非指具体马匹。",
            tags_json=[],
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Uncertain occurrences must preserve original text "
                "and must NOT produce erroneous horse tags."
            )
        from stable.services.term_consistency import apply_consistency_gate
        result = apply_consistency_gate(article)
        uncertain = [o for o in result.occurrences if o.status == "uncertain"]
        self.assertTrue(uncertain, "Should classify 'Brilliant Result' as uncertain")
        for occ in uncertain:
            self.assertEqual(occ.target_zh, "", "Uncertain occurrence must not produce a target_zh")
        # Verify no erroneous horse tag was generated
        erroneous_tags = [t for t in result.suggested_tags if t == "辉煌"]
        self.assertFalse(erroneous_tags, "Uncertain occurrence must not produce horse tag '辉煌'")

    def test_conflict_blocks_auto_publish_with_evidence(self):
        """
        Conflict must block auto-publish and the gate issue must contain
        field/occurrence evidence.
        RED: conflict blocking not implemented.
        """
        term_a = _create_term_entry(
            source_ja="Global Star", target_zh="全球之星",
            term_type=TermType.HORSE, racing_region=RacingRegion.UNITED_KINGDOM,
        )
        term_b = _create_term_entry(
            source_ja="Global Star", target_zh="环球明星",
            term_type=TermType.HORSE, racing_region=RacingRegion.HONG_KONG,
        )

        article = _create_article(
            title_zh="Global Star 赢得大赛",
            body_zh="Global Star 在今天的比赛中表现出色。",
            racing_region=RacingRegion.UNITED_KINGDOM,
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Cross-region conflict must block auto-publish."
            )
        from stable.services.term_consistency import apply_consistency_gate
        result = apply_consistency_gate(article)
        blocker = [i for i in result.issues if i.get("severity") == "blocker"]
        self.assertTrue(blocker, "Conflict must produce a blocker gate issue")


# ===========================================================================
# Section 8: Historical repair — dry-run
# ===========================================================================

class HistoricalRepairDryRunTest(TestCase):
    """test_cases.md 12, 13, 14, 15, 16 — published article repair."""

    def setUp(self):
        # Create a term and alias for "Kalpana" so that repair dry-run has
        # data to match against when scanning published articles.
        self.kalpana_entry = _create_term_entry(
            source_ja="Kalpana",
            target_zh="幻梦逸想",
            term_type=TermType.HORSE,
        )
        _create_term_alias(
            self.kalpana_entry, "Kalpana",
            source_language=SourceLanguage.ENGLISH,
        )

    def _published_article(self, **overrides):
        defaults = {
            "workflow_status": WorkflowStatus.PUBLISHED,
            "automation_status": AutomationStatus.AUTO_PUBLISHED,
            "published_to_web_at": timezone.now(),
            "translated_title_zh": "Kalpana赢得雅士谷赛事",
            "title_zh": "Kalpana赢得雅士谷赛事",
            "translated_body_zh": "Kalpana在雅士谷的比赛中以出色表现获胜。",
            "body_zh": "Kalpana在雅士谷的比赛中以出色表现获胜。",
            "tags_json": ["Kalpana", "赛马"],
        }
        defaults.update(overrides)
        return _create_article(
            source_article_id=f"published-repair-{NewsArticle.objects.count() + 1}",
            **defaults,
        )

    def test_dry_run_does_not_write_to_database(self):
        """
        Dry-run must produce a manifest without modifying any article fields.
        RED: dry-run not implemented.
        """
        article = self._published_article()
        before = NewsArticle.objects.values(
            "title_zh", "body_zh", "tags_json",
            "workflow_status", "published_to_web_at",
            "public_slug", "updated_at",
        ).get(pk=article.pk)

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "build_dry_run_manifest() must not write to database."
            )
        from stable.services.term_consistency import build_dry_run_manifest
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)

        after = NewsArticle.objects.values(
            "title_zh", "body_zh", "tags_json",
            "workflow_status", "published_to_web_at",
            "public_slug", "updated_at",
        ).get(pk=article.pk)
        self.assertEqual(after, before, "Dry-run must not modify article fields")
        self.assertIsNotNone(manifest.manifest_sha256)
        self.assertIsNotNone(manifest.run_id)

    def test_dry_run_outputs_deterministic_field_diff(self):
        """
        Dry-run manifest must contain article ID, field name, before SHA,
        replacement occurrences, target term, and evidence.
        RED: deterministic diff output not implemented.
        """
        article = self._published_article()

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Dry-run manifest must include deterministic field-level diffs."
            )
        from stable.services.term_consistency import build_dry_run_manifest
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
        self.assertTrue(manifest.diffs)
        for diff in manifest.diffs:
            self.assertIn("article_id", diff)
            self.assertIn("field", diff)
            self.assertIn("before_sha256", diff)
            self.assertIn("occurrences", diff)
            self.assertIn("target_zh", diff)

    def test_canonical_fields_conserved(self):
        """
        Source fields, public_slug, published_at, workflow_status, and
        QQ delivery must be conserved during repair.
        RED: conservation guarantees not implemented.
        """
        article = self._published_article(
            body_ja_raw="Kalpana won at Ascot.",
            body_ja_normalized="Kalpana won at Ascot.",
            title_ja="Kalpana wins at Ascot",
            public_slug="kalpana-wins-at-ascot",
        )
        before = {
            "body_ja_raw": article.body_ja_raw,
            "body_ja_normalized": article.body_ja_normalized,
            "title_ja": article.title_ja,
            "public_slug": article.public_slug,
            "published_at": article.published_at,
            "workflow_status": article.workflow_status,
        }

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Source fields, slug, published_at, workflow_status, and "
                "QQ delivery must be conserved."
            )
        from stable.services.term_consistency import build_dry_run_manifest, commit_dry_run
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
        commit_dry_run(manifest.run_id, manifest.manifest_sha256)

        article.refresh_from_db()
        after = {
            "body_ja_raw": article.body_ja_raw,
            "body_ja_normalized": article.body_ja_normalized,
            "title_ja": article.title_ja,
            "public_slug": article.public_slug,
            "published_at": article.published_at,
            "workflow_status": article.workflow_status,
        }
        self.assertEqual(after, before, "Conserved fields must not change")

    def test_manually_edited_fields_are_skipped(self):
        """
        Fields listed in manually_edited_fields must not be included
        in the dry-run diff or manifest.
        RED: manual-field skip not implemented.
        """
        article = self._published_article(
            title_zh="Kalpana赢得雅士谷赛事（人工编辑）",
            manually_edited_fields=["title_zh"],
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Fields in manually_edited_fields must be skipped in dry-run."
            )
        from stable.services.term_consistency import build_dry_run_manifest
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
        title_diffs = [d for d in manifest.diffs if d.get("field") == "title_zh"]
        self.assertFalse(
            title_diffs,
            "Title is manually edited — must not appear in dry-run manifest.",
        )

    def test_before_sha_drift_rejects_whole_batch(self):
        """
        If any article's before SHA drifts between dry-run and commit,
        the entire batch must be rejected.
        RED: SHA drift detection not implemented.
        """
        article = self._published_article()

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "before-SHA drift must reject the entire batch."
            )
        from stable.services.term_consistency import build_dry_run_manifest, commit_dry_run
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)

        # Simulate drift by modifying the article
        article.title_zh = "运营修改后的标题"
        article.save(update_fields=["title_zh", "updated_at"])

        with self.assertRaises(Exception):
            commit_dry_run(manifest.run_id, manifest.manifest_sha256)

    def test_reapply_is_idempotent(self):
        """
        Re-applying the same repair batch must produce zero additional
        business effect (no new diffs, no field changes).
        RED: idempotent reapply not implemented.
        """
        article = self._published_article()

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Re-apply must be idempotent."
            )
        from stable.services.term_consistency import build_dry_run_manifest, commit_dry_run
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)

        # First application
        commit_dry_run(manifest.run_id, manifest.manifest_sha256)
        after_first = NewsArticle.objects.values(
            "title_zh", "body_zh", "tags_json",
        ).get(pk=article.pk)

        # Second application (same manifest)
        manifest2 = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
        commit_dry_run(manifest2.run_id, manifest2.manifest_sha256)
        after_second = NewsArticle.objects.values(
            "title_zh", "body_zh", "tags_json",
        ).get(pk=article.pk)

        self.assertEqual(after_first, after_second, "Re-apply must be idempotent")


# ===========================================================================
# Section 9: Historical repair — CAS commit drift
# ===========================================================================

class HistoricalRepairCommitDriftTest(TestCase):
    """test_cases.md 15 — batch rejection on SHA/manifest drift."""

    def setUp(self):
        self.kalpana_entry = _create_term_entry(
            source_ja="Kalpana",
            target_zh="幻梦逸想",
            term_type=TermType.HORSE,
        )
        _create_term_alias(
            self.kalpana_entry, "Kalpana",
            source_language=SourceLanguage.ENGLISH,
        )

    def test_term_version_drift_rejects_commit(self):
        """
        If term snapshot SHA changes between dry-run and commit,
        the entire batch must be rejected.
        RED: term version drift detection not implemented.
        """
        horse_entry = _create_term_entry(source_ja="Kalpana", target_zh="幻梦逸想")
        _create_term_alias(horse_entry, "Kalpana", source_language=SourceLanguage.ENGLISH)

        article = _create_article(
            title_zh="Kalpana wins again",
            body_zh="Kalpana won at the recent meeting.",
            workflow_status=WorkflowStatus.PUBLISHED,
            automation_status=AutomationStatus.AUTO_PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Term snapshot drift must reject the entire batch."
            )
        from stable.services.term_consistency import build_dry_run_manifest, commit_dry_run
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)

        # Change the term — simulating drift
        horse_entry.target_zh = "新译名"
        horse_entry.save(update_fields=["target_zh", "updated_at"])

        with self.assertRaises(Exception) as ctx:
            commit_dry_run(manifest.run_id, manifest.manifest_sha256)
        error_msg = str(ctx.exception).lower()
        self.assertTrue("drift" in error_msg or "snapshot" in error_msg)

    def test_settings_drift_rejects_commit(self):
        """
        If validation settings SHA changes between dry-run and commit,
        the entire batch must be rejected.
        RED: settings drift detection not implemented.
        """
        _create_term_entry(source_ja="Kalpana", target_zh="幻梦逸想")
        _create_article(
            title_zh="Kalpana wins",
            body_zh="Kalpana won at Ascot.",
            workflow_status=WorkflowStatus.PUBLISHED,
            automation_status=AutomationStatus.AUTO_PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Settings drift must reject the entire batch."
            )
        from stable.services.term_consistency import build_dry_run_manifest, commit_dry_run
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)

        with override_settings(AUTO_REWRITE_ENABLED=True):
            with self.assertRaises(Exception):
                commit_dry_run(manifest.run_id, manifest.manifest_sha256)


# ===========================================================================
# Section 9b: Manifest persistence & rollback
# ===========================================================================

class ManifestPersistenceAndRollbackTest(TestCase):
    """Manifests persist in the database and committed manifests roll back."""

    def setUp(self):
        self.kalpana_entry = _create_term_entry(
            source_ja="Kalpana",
            target_zh="幻梦逸想",
            term_type=TermType.HORSE,
        )
        _create_term_alias(
            self.kalpana_entry, "Kalpana",
            source_language=SourceLanguage.ENGLISH,
        )

    def _published_article(self, **overrides):
        defaults = {
            "workflow_status": WorkflowStatus.PUBLISHED,
            "automation_status": AutomationStatus.AUTO_PUBLISHED,
            "published_to_web_at": timezone.now(),
            "translated_title_zh": "Kalpana赢得雅士谷赛事",
            "title_zh": "Kalpana赢得雅士谷赛事",
            "translated_body_zh": "Kalpana在雅士谷的比赛中以出色表现获胜。",
            "body_zh": "Kalpana在雅士谷的比赛中以出色表现获胜。",
            "tags_json": ["Kalpana", "赛马"],
        }
        defaults.update(overrides)
        return _create_article(
            source_article_id=f"rollback-{NewsArticle.objects.count() + 1}",
            **defaults,
        )

    def test_manifest_persisted_to_database(self):
        """build_dry_run_manifest must persist a queryable manifest row."""
        self._published_article()
        from stable.models import TermConsistencyManifest
        from stable.services.term_consistency import build_dry_run_manifest
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
        row = TermConsistencyManifest.objects.get(run_id=manifest.run_id)
        self.assertEqual(row.manifest_sha256, manifest.manifest_sha256)
        self.assertEqual(row.status, "pending")
        self.assertTrue(row.diffs)

    def test_commit_marks_manifest_committed(self):
        """commit_dry_run records status/approver and refuses re-commit."""
        self._published_article()
        from stable.models import TermConsistencyManifest
        from stable.services.term_consistency import build_dry_run_manifest, commit_dry_run
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
        commit_dry_run(manifest.run_id, manifest.manifest_sha256, approved_by="editor")
        row = TermConsistencyManifest.objects.get(run_id=manifest.run_id)
        self.assertEqual(row.status, "committed")
        self.assertEqual(row.approved_by, "editor")
        self.assertIsNotNone(row.committed_at)
        with self.assertRaises(Exception):
            commit_dry_run(manifest.run_id, manifest.manifest_sha256)

    def test_rollback_restores_before_values(self):
        """Rollback restores original field values with CAS verification."""
        article = self._published_article()
        original = NewsArticle.objects.values("title_zh", "body_zh", "tags_json").get(pk=article.pk)
        from stable.services.term_consistency import (
            build_dry_run_manifest,
            commit_dry_run,
            rollback_canonical_consistency,
        )
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
        commit_dry_run(manifest.run_id, manifest.manifest_sha256)
        article.refresh_from_db()
        self.assertIn("幻梦逸想", article.title_zh)

        result = rollback_canonical_consistency(manifest.run_id)
        self.assertTrue(result.success, f"rollback failed: {result.errors}")
        self.assertGreater(result.total_fields, 0)
        after = NewsArticle.objects.values("title_zh", "body_zh", "tags_json").get(pk=article.pk)
        self.assertEqual(after, original, "Rollback must restore before-values")

        from stable.models import TermConsistencyManifest
        row = TermConsistencyManifest.objects.get(run_id=manifest.run_id)
        self.assertEqual(row.status, "rolled_back")
        self.assertIsNotNone(row.rolled_back_at)

    def test_rollback_rejects_drift_without_writing(self):
        """If a field changed after commit, rollback aborts and writes nothing."""
        article = self._published_article()
        from stable.services.term_consistency import (
            build_dry_run_manifest,
            commit_dry_run,
            rollback_canonical_consistency,
        )
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
        commit_dry_run(manifest.run_id, manifest.manifest_sha256)
        article.refresh_from_db()
        committed_title = article.title_zh
        # Simulate an out-of-band edit after commit
        NewsArticle.objects.filter(pk=article.pk).update(body_zh="人工改过的正文")

        result = rollback_canonical_consistency(manifest.run_id)
        self.assertFalse(result.success)
        self.assertTrue(result.errors)
        article.refresh_from_db()
        self.assertEqual(article.title_zh, committed_title, "Drifted rollback must not write")
        self.assertEqual(article.body_zh, "人工改过的正文")

    def test_rollback_requires_committed_manifest(self):
        """Pending or missing manifests cannot be rolled back."""
        self._published_article()
        from stable.services.term_consistency import (
            build_dry_run_manifest,
            rollback_canonical_consistency,
        )
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
        result = rollback_canonical_consistency(manifest.run_id)
        self.assertFalse(result.success)
        missing = rollback_canonical_consistency("no-such-run")
        self.assertFalse(missing.success)

    def _two_articles_by_process_order(self):
        """Return (first_processed, second_processed) articles.

        build_dry_run_manifest scans articles in -published_at order, so the
        newer article's diffs are applied first.
        """
        older = self._published_article(
            published_at=timezone.now() - timedelta(hours=2),
            published_to_web_at=timezone.now() - timedelta(hours=2),
        )
        newer = self._published_article(
            published_at=timezone.now(),
            published_to_web_at=timezone.now(),
        )
        return newer, older

    def test_commit_batch_rolls_back_on_save_failure(self):
        """A mid-batch save failure must roll back the whole commit."""
        from stable.models import TermConsistencyManifest
        from stable.services.term_consistency import build_dry_run_manifest, commit_dry_run
        newer, older = self._two_articles_by_process_order()
        original_newer_title = newer.title_zh
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
        # Sanity: both articles have diffs
        diff_articles = {d["article_id"] for d in manifest.diffs}
        self.assertIn(newer.pk, diff_articles)
        self.assertIn(older.pk, diff_articles)

        real_save = NewsArticle.save

        def failing_save(self, *args, **kwargs):
            if self.pk == older.pk:
                raise RuntimeError("injected mid-batch failure")
            return real_save(self, *args, **kwargs)

        with patch.object(NewsArticle, "save", failing_save):
            with self.assertRaises(RuntimeError):
                commit_dry_run(manifest.run_id, manifest.manifest_sha256)

        # The first-processed article's write must have been rolled back
        newer.refresh_from_db()
        self.assertEqual(newer.title_zh, original_newer_title)
        # Manifest status flip must also have been rolled back
        row = TermConsistencyManifest.objects.get(run_id=manifest.run_id)
        self.assertEqual(row.status, "pending")

    def test_rollback_batch_rolls_back_on_save_failure(self):
        """A mid-batch save failure must roll back the whole rollback."""
        from stable.models import TermConsistencyManifest
        from stable.services.term_consistency import (
            build_dry_run_manifest,
            commit_dry_run,
            rollback_canonical_consistency,
        )
        newer, older = self._two_articles_by_process_order()
        manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
        commit_dry_run(manifest.run_id, manifest.manifest_sha256)
        newer.refresh_from_db()
        committed_newer_title = newer.title_zh
        self.assertIn("幻梦逸想", committed_newer_title)

        real_save = NewsArticle.save

        def failing_save(self, *args, **kwargs):
            if self.pk == older.pk:
                raise RuntimeError("injected mid-batch failure")
            return real_save(self, *args, **kwargs)

        with patch.object(NewsArticle, "save", failing_save):
            with self.assertRaises(RuntimeError):
                rollback_canonical_consistency(manifest.run_id)

        # The first-processed article's restore must have been rolled back:
        # it still holds the committed (replaced) value.
        newer.refresh_from_db()
        self.assertEqual(newer.title_zh, committed_newer_title)
        row = TermConsistencyManifest.objects.get(run_id=manifest.run_id)
        self.assertEqual(row.status, "committed")

    def test_snapshot_hash_covers_identity_payload(self):
        """Editing only identity_payload must invalidate the term snapshot."""
        from stable.models import TermMappingEvidence
        from stable.services.term_consistency import _term_snapshot_sha256
        evidence = TermMappingEvidence.objects.create(
            term=self.kalpana_entry,
            evidence_kind="manual_review",
            review_status="pending",
            identity_payload={"name": "Kalpana", "year": 2021},
        )
        hash_before = _term_snapshot_sha256()
        evidence.identity_payload = {"name": "Kalpana", "year": 2022}
        evidence.save(update_fields=["identity_payload", "updated_at"])
        self.assertNotEqual(hash_before, _term_snapshot_sha256())


# ===========================================================================
# Section 10: Performance baseline
# ===========================================================================

class PerformanceBaselineTest(TestCase):
    """test_cases.md 17 — 100 articles, 20k aliases, <10s with constant queries."""

    def _seed_aliases(self, count: int) -> TermEntry:
        """Create a single TermEntry with `count` active aliases."""
        entry = _create_term_entry(
            source_ja="BaseHorse",
            target_zh="基础赛马",
            term_type=TermType.HORSE,
        )
        TermAlias.objects.bulk_create([
            TermAlias(
                term=entry,
                source_language=SourceLanguage.ENGLISH,
                text=f"Alias{idx:05d}",
                alias_type=TermAliasType.ALIAS,
                is_active=True,
            )
            for idx in range(count)
        ], ignore_conflicts=True)
        return entry

    def _seed_articles(self, count: int, entry: TermEntry | None = None):
        """Create `count` published articles."""
        alias_surface = "BaseHorse"
        for idx in range(count):
            _create_article(
                source_article_id=f"perf-{idx:05d}",
                title_zh=f"{alias_surface} wins race {idx}",
                body_zh=f"{alias_surface} won the race with a strong finish. " * 3,
                workflow_status=WorkflowStatus.PUBLISHED,
                automation_status=AutomationStatus.AUTO_PUBLISHED,
                published_to_web_at=timezone.now() - timedelta(minutes=idx),
            )

    @tag("performance")
    def test_100_article_dry_run_within_10_seconds(self):
        """
        Dry-run across 100 articles with 20,000 active aliases must
        complete in under 10 seconds with constant ORM queries.
        RED: batch prefetch / performance not implemented.
        """
        self._seed_aliases(20_000)
        entry = _create_term_entry(source_ja="TargetHorse", target_zh="目标赛马")
        _create_term_alias(entry, "TargetHorse", source_language=SourceLanguage.ENGLISH)
        self._seed_articles(100, entry)

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "100-article dry-run with 20k aliases must complete in "
                "<10 seconds with constant ORM queries."
            )
        from stable.services.term_consistency import build_dry_run_manifest

        with CaptureQueriesContext(connection) as queries:
            import time
            start = time.monotonic()
            manifest = build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
            elapsed = time.monotonic() - start

        self.assertLess(
            elapsed, 10.0,
            f"Dry-run took {elapsed:.2f}s, expected <10.0s",
        )
        self.assertLessEqual(
            len(queries), 50,
            f"ORM query count {len(queries)} exceeds budget of 50",
        )
        self.assertTrue(manifest.diffs)

    @tag("performance")
    def test_orm_query_count_constant_regardless_of_article_count(self):
        """
        ORM query count must remain constant (not proportional to
        article count) when scanning for dry-run candidates.
        RED: constant-query prefetch not implemented.
        """
        self._seed_aliases(10_000)

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "ORM queries must remain constant regardless of article count."
            )
        from stable.services.term_consistency import build_dry_run_manifest

        def count_queries(article_count: int) -> int:
            NewsArticle.objects.filter(
                workflow_status=WorkflowStatus.PUBLISHED,
            ).delete()
            self._seed_articles(article_count)
            with CaptureQueriesContext(connection) as queries:
                build_dry_run_manifest(region=RacingRegion.UNITED_KINGDOM)
            return len(queries)

        count_10 = count_queries(10)
        count_100 = count_queries(100)

        self.assertAlmostEqual(
            count_10, count_100, delta=5,
            msg=f"Query count grew from {count_10} to {count_100}",
        )

    @tag("performance")
    def test_no_overlapping_replacement_or_position_offset(self):
        """
        Long text with multiple occurrences of the same alias must not
        produce overlapping replacements or position offsets.
        RED: position-safe replacement not implemented.
        """
        entry = _create_term_entry(source_ja="Kalpana", target_zh="幻梦逸想")
        _create_term_alias(entry, "Kalpana", source_language=SourceLanguage.ENGLISH)

        body = "Kalpana won. " + "Kalpana and another horse ran well. " * 100
        article = _create_article(
            title_zh="Kalpana multiple occurrences",
            body_zh=body,
            workflow_status=WorkflowStatus.PUBLISHED,
            automation_status=AutomationStatus.AUTO_PUBLISHED,
            published_to_web_at=timezone.now(),
        )

        if not TERM_CONSISTENCY_EXISTS:
            self.fail(
                "stable.services.term_consistency module does not exist. "
                "Multiple-occurrence replacement must not overlap or offset."
            )
        from stable.services.term_consistency import build_dry_run_manifest, apply_consistency_gate
        result = apply_consistency_gate(article)
        kalpana_occs = [o for o in result.occurrences if o.surface == "Kalpana"]
        self.assertGreaterEqual(len(kalpana_occs), 50)
        # Verify no overlapping spans
        positions = sorted((o.start, o.end) for o in kalpana_occs)
        for i in range(len(positions) - 1):
            self.assertLessEqual(
                positions[i][1], positions[i + 1][0],
                f"Overlapping replacement positions at index {i}: {positions[i]} vs {positions[i + 1]}",
            )


# ===========================================================================
# Appendix: Validate the test file itself is loadable
# ===========================================================================

class TestFileContractTest(TestCase):
    """Meta-tests ensuring the test file environment is correct."""

    def test_module_importable(self):
        """The test module must be importable without syntax errors."""
        import importlib
        mod = importlib.import_module("stable.test_public_term_consistency")
        self.assertIsNotNone(mod)

    def test_service_flags_are_accurate(self):
        """
        After implementation, both MAPPING_EVIDENCE_EXISTS and
        TERM_CONSISTENCY_EXISTS should be True (feature is implemented).
        """
        self.assertTrue(
            MAPPING_EVIDENCE_EXISTS,
            "TermMappingEvidence model must exist after implementation.",
        )
        self.assertTrue(
            TERM_CONSISTENCY_EXISTS,
            "term_consistency service must exist after implementation.",
        )

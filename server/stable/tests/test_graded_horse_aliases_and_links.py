"""Tests for graded-horse alias backfill and race-record-to-event heuristic linking."""

from __future__ import annotations

from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from stable.models import (
    HorseProfile,
    HorseRaceRecord,
    RaceEvent,
    RaceEventRunner,
    RacingRegion,
    SourceLanguage,
    TermAlias,
    TermEntry,
    TermType,
)
from stable.services.horse_race_record_event_matching import RaceEventMatcher


def _horse_term(source_ja: str) -> TermEntry:
    return TermEntry.objects.create(
        term_type=TermType.HORSE,
        source_language=SourceLanguage.ENGLISH,
        source_ja=source_ja,
        target_zh="",
        is_active=True,
    )


def _profile(term: TermEntry, **kwargs) -> HorseProfile:
    defaults = {
        "primary_term": term,
        "english_name": term.source_ja,
        "original_name": term.source_ja,
        "racing_region": RacingRegion.UNITED_KINGDOM,
        "review_status": "published",
    }
    defaults.update(kwargs)
    return HorseProfile.objects.create(**defaults)


class AddGradedHorseTermAliasesTests(TestCase):
    """Tests for add_graded_horse_term_aliases command."""

    def test_adds_base_name_alias_for_disambiguated_term(self):
        term = _horse_term("A Bit Of Spirit (IRE)")
        _profile(term, source_refs={"theracingapi_horse_id": "horse_123"})

        out = StringIO()
        call_command("add_graded_horse_term_aliases", stdout=out)

        term.refresh_from_db()
        self.assertIn("A Bit Of Spirit", term.aliases_ja)
        alias = TermAlias.objects.get(term=term, text="A Bit Of Spirit")
        self.assertEqual(alias.source_language, SourceLanguage.ENGLISH)
        self.assertTrue(alias.is_active)

    def test_skips_terms_without_country_suffix(self):
        term = _horse_term("Normal Name")
        _profile(term, source_refs={"theracingapi_horse_id": "horse_456"})

        out = StringIO()
        call_command("add_graded_horse_term_aliases", stdout=out)

        self.assertFalse(TermAlias.objects.filter(term=term).exists())

    def test_idempotent(self):
        term = _horse_term("Duplicate Base (GB)")
        term.aliases_ja = ["Duplicate Base"]
        term.save(update_fields=["aliases_ja"])
        _profile(term, source_refs={"theracingapi_horse_id": "horse_789"})

        out = StringIO()
        call_command("add_graded_horse_term_aliases", stdout=out)

        term.refresh_from_db()
        self.assertEqual(term.aliases_ja.count("Duplicate Base"), 1)
        self.assertIn("跳过", out.getvalue())


class RaceEventMatcherTests(TestCase):
    """Tests for heuristic RaceEvent matching service."""

    def _make_event(self, **kwargs):
        defaults = {
            "year": 2024,
            "slug": "test-event",
            "original_name": "Test Race",
            "chinese_name": "测试赛",
            "country_region": RacingRegion.UNITED_KINGDOM,
            "racecourse": "Ascot",
            "local_date": date(2024, 6, 1),
            "surface": "turf",
        }
        defaults.update(kwargs)
        return RaceEvent.objects.create(**defaults)

    def test_exact_course_and_name_match(self):
        event = self._make_event(
            slug="ascot-2024",
            original_name="King George Stakes (Group 1)",
        )
        RaceEventRunner.objects.create(event=event, horse_name="Horse One", sort_order=1)

        term = _horse_term("Horse One")
        profile = _profile(term)
        record = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="King George Stakes",
            race_date=date(2024, 6, 1),
            racecourse="Ascot",
            source_refs={"theracingapi_race_id": "rac_1"},
        )

        matcher = RaceEventMatcher()
        match = matcher.find_best_match(record, profile=profile)

        self.assertIsNotNone(match)
        self.assertEqual(match.event.id, event.id)
        self.assertTrue(match.horse_name_match)

    def test_no_match_when_course_differs(self):
        event = self._make_event(
            slug="ascot-2024",
            original_name="King George Stakes",
            racecourse="Ascot",
        )
        term = _horse_term("Horse One")
        profile = _profile(term)
        record = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="King George Stakes",
            race_date=date(2024, 6, 1),
            racecourse="Curragh",
            source_refs={"theracingapi_race_id": "rac_2"},
        )

        matcher = RaceEventMatcher()
        match = matcher.find_best_match(record, profile=profile)

        self.assertIsNone(match)

    def test_requires_high_name_score_without_horse_match(self):
        event = self._make_event(
            slug="ascot-2024",
            original_name="Totally Different Race",
        )
        term = _horse_term("Missing Horse")
        profile = _profile(term)
        record = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="King George Stakes",
            race_date=date(2024, 6, 1),
            racecourse="Ascot",
            source_refs={"theracingapi_race_id": "rac_3"},
        )

        matcher = RaceEventMatcher()
        match = matcher.find_best_match(record, profile=profile)

        self.assertIsNone(match)


class LinkGradedHorseRaceRecordsTests(TestCase):
    """Tests for link_graded_horse_race_records command."""

    def _make_event(self, **kwargs):
        defaults = {
            "year": 2024,
            "slug": "link-test",
            "original_name": "Linkable Race",
            "chinese_name": "可关联赛",
            "country_region": RacingRegion.UNITED_KINGDOM,
            "racecourse": "Newmarket",
            "local_date": date(2024, 5, 15),
            "surface": "turf",
        }
        defaults.update(kwargs)
        return RaceEvent.objects.create(**defaults)

    def test_links_records_dry_run_does_not_write(self):
        event = self._make_event()
        RaceEventRunner.objects.create(event=event, horse_name="Link Horse", sort_order=1)

        term = _horse_term("Link Horse")
        profile = _profile(term)
        record = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="Linkable Race",
            race_date=date(2024, 5, 15),
            racecourse="Newmarket",
            source_refs={"theracingapi_race_id": "rac_link"},
        )

        out = StringIO()
        call_command("link_graded_horse_race_records", "--dry-run", stdout=out)

        record.refresh_from_db()
        self.assertIsNone(record.event)
        self.assertIn("matched=1", out.getvalue())

    def test_links_records_in_apply_mode(self):
        event = self._make_event(
            slug="apply-test",
            original_name="Apply Race",
            chinese_name="应用赛",
            racecourse="York",
            local_date=date(2024, 7, 20),
        )
        RaceEventRunner.objects.create(event=event, horse_name="Apply Horse", sort_order=1)

        term = _horse_term("Apply Horse")
        profile = _profile(term)
        record = HorseRaceRecord.objects.create(
            horse_profile=profile,
            race_name="Apply Race",
            race_date=date(2024, 7, 20),
            racecourse="York",
            source_refs={"theracingapi_race_id": "rac_apply"},
        )

        out = StringIO()
        call_command("link_graded_horse_race_records", stdout=out)

        record.refresh_from_db()
        self.assertEqual(record.event_id, event.id)

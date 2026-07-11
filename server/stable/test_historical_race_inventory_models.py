from importlib import import_module

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    RaceEvent,
    RaceEventHistoryWinner,
    RaceEventResult,
    RaceEventStatus,
    RaceEventSurface,
    RaceSeries,
    RaceSeriesName,
    RaceSeriesRelation,
    RaceSeriesRelationType,
    RaceSeriesReviewStatus,
    RacingRegion,
)


class HistoricalRaceInventoryModelTests(TestCase):
    def _series(self, *, key="uk-derby", region=RacingRegion.UNITED_KINGDOM, **overrides):
        values = {
            "key": key,
            "country_region": region,
            "canonical_name_original": "The Derby",
            "chinese_name": "叶森德比",
        }
        values.update(overrides)
        return RaceSeries.objects.create(**values)

    def _event(self, *, series=None, year=1984, slug="uk-derby-1984", **overrides):
        values = {
            "year": year,
            "slug": slug,
            "series_key": "legacy-series-key",
            "race_series": series,
            "original_name": "The Derby",
            "chinese_name": "叶森德比",
            "country_region": RacingRegion.UNITED_KINGDOM,
            "racecourse": "Epsom",
            "grade_text": "Group 1",
            "surface": RaceEventSurface.TURF,
            "status": RaceEventStatus.FINISHED,
        }
        values.update(overrides)
        return RaceEvent.objects.create(**values)

    def test_series_rejects_ended_year_before_founded_year(self):
        series = RaceSeries(
            key="invalid-years",
            country_region=RacingRegion.UNITED_KINGDOM,
            canonical_name_original="Invalid Years",
            founded_year=2000,
            ended_year=1999,
        )

        with self.assertRaises(ValidationError):
            series.full_clean()

        series = self._series(founded_year=1999, ended_year=2000)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RaceSeries.objects.filter(pk=series.pk).update(founded_year=2000, ended_year=1999)

    def test_series_name_normalizes_text_and_enforces_effective_period_identity(self):
        series = self._series()
        name = RaceSeriesName.objects.create(
            series=series,
            text="  THE   DERBY ",
            source_language="en",
            valid_from_year=1984,
        )

        self.assertEqual(name.normalized_text, "the derby")
        with self.assertRaises(IntegrityError), transaction.atomic():
            RaceSeriesName.objects.create(
                series=series,
                text="the derby",
                source_language="en",
                valid_from_year=1984,
            )

    def test_series_name_rejects_reversed_effective_period(self):
        name = RaceSeriesName(
            series=self._series(),
            text="Sponsored Derby",
            source_language="en",
            valid_from_year=2000,
            valid_to_year=1999,
        )

        with self.assertRaises(ValidationError):
            name.full_clean()

    def test_series_relation_rejects_self_relation_and_incomplete_approval(self):
        series = self._series()
        relation = RaceSeriesRelation(
            from_series=series,
            to_series=series,
            relation_type=RaceSeriesRelationType.PREDECESSOR,
        )
        with self.assertRaises(ValidationError):
            relation.full_clean()

        successor = self._series(key="uk-derby-successor")
        relation.to_series = successor
        relation.review_status = RaceSeriesReviewStatus.APPROVED
        with self.assertRaises(ValidationError):
            relation.full_clean()

    def test_series_relation_accepts_audited_approval(self):
        approver = get_user_model().objects.create_user(username="inventory-reviewer")
        relation = RaceSeriesRelation(
            from_series=self._series(),
            to_series=self._series(key="uk-derby-successor"),
            relation_type=RaceSeriesRelationType.SUCCESSOR,
            review_status=RaceSeriesReviewStatus.APPROVED,
            approved_by=approver,
            approved_at=timezone.now(),
        )

        relation.full_clean()
        relation.save()

    def test_event_series_binding_syncs_legacy_series_key_without_changing_slug(self):
        series = self._series()
        event = self._event(series=series)

        self.assertEqual(event.series_key, series.key)
        self.assertEqual(event.slug, "uk-derby-1984")

    def test_event_series_year_is_unique_only_for_bound_series(self):
        series = self._series()
        self._event(series=series)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._event(series=series, slug="another-1984-derby")

        self._event(series=None, slug="legacy-unbound-a")
        self._event(series=None, slug="legacy-unbound-b")

    def test_target_syncs_region_and_enforces_series_year_identity(self):
        series = self._series()
        event = self._event(series=series)
        target = HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=1984,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
            event=event,
        )

        self.assertEqual(target.country_region, RacingRegion.UNITED_KINGDOM)
        target.full_clean()

        target.year = 1985
        with self.assertRaises(ValidationError):
            target.full_clean()

    def test_target_rejects_not_held_event_and_imported_target_without_event(self):
        series = self._series()
        event = self._event(series=series)
        not_held = HistoricalRaceEventTarget(
            race_series=series,
            year=1984,
            country_region=series.country_region,
            expectation_status=HistoricalRaceExpectationStatus.NOT_HELD,
            event=event,
        )
        with self.assertRaises(ValidationError):
            not_held.full_clean()

        imported = HistoricalRaceEventTarget(
            race_series=series,
            year=1985,
            country_region=series.country_region,
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
        )
        with self.assertRaises(ValidationError):
            imported.full_clean()

    def test_permanently_unavailable_requires_complete_approval_evidence(self):
        target = HistoricalRaceEventTarget(
            race_series=self._series(),
            year=1984,
            country_region=RacingRegion.UNITED_KINGDOM,
            resolution_status=HistoricalRaceResolutionStatus.PERMANENTLY_UNAVAILABLE,
        )

        with self.assertRaises(ValidationError):
            target.full_clean()

        target.permanent_unavailable_approved_by = get_user_model().objects.create_user(username="gap-reviewer")
        target.permanent_unavailable_approved_at = timezone.now()
        target.permanent_unavailable_evidence = {
            "official_archive": {"url": "https://example.test/official"},
            "independent_source": {"url": "https://example.test/reference"},
        }
        target.full_clean()

    def test_result_supports_separate_internal_and_official_finish_positions(self):
        event = self._event()
        RaceEventResult.objects.create(
            event=event,
            finish_position=2,
            official_finish_position=1,
            horse_name="Dead Heat A",
        )
        RaceEventResult.objects.create(
            event=event,
            finish_position=3,
            official_finish_position=1,
            horse_name="Dead Heat B",
        )

        self.assertEqual(list(event.results.values_list("official_finish_position", flat=True)), [1, 1])

    def test_history_winner_supports_dead_heat_but_rejects_exact_duplicate(self):
        event = self._event()
        RaceEventHistoryWinner.objects.create(event=event, winner_year=1984, horse_name="Dead Heat A")
        RaceEventHistoryWinner.objects.create(event=event, winner_year=1984, horse_name="Dead Heat B")

        with self.assertRaises(IntegrityError), transaction.atomic():
            RaceEventHistoryWinner.objects.create(event=event, winner_year=1984, horse_name="Dead Heat A")

    def test_official_position_migration_uses_source_value_then_falls_back(self):
        event = self._event()
        source_position = RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            horse_name="Source Position",
            source_refs={"official_finish_position": "2"},
        )
        fallback = RaceEventResult.objects.create(
            event=event,
            finish_position=2,
            horse_name="Fallback Position",
            source_refs={"official_finish_position": "invalid"},
        )
        migration = import_module("stable.migrations.0024_historical_race_inventory")

        migration.backfill_official_finish_positions(apps, None)

        source_position.refresh_from_db()
        fallback.refresh_from_db()
        self.assertEqual(source_position.official_finish_position, 2)
        self.assertEqual(fallback.official_finish_position, 2)

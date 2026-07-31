from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    RaceEventStatus,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.historical_race_batches import materialize_historical_event
from stable.services.historical_race_importer import historical_basic_fields_complete
from stable.services.historical_race_inventory import InventoryValidationError
from stable.services.race_event_years import (
    derive_public_year,
    historical_event_identity,
    validate_event_years,
)


class RaceEventYearHelperTests(SimpleTestCase):
    def test_known_local_date_overrides_planned_year(self):
        self.assertEqual(derive_public_year(date(2024, 12, 8), 2025), 2024)

    def test_legitimate_cross_year_requires_approved_authoritative_evidence(self):
        evidence = {
            "actual_year": 2026,
            "reason": "official_reschedule",
            "authority_url": "https://authority.example.test/reschedule",
            "approved": True,
        }
        validate_event_years(2026, 2025, date(2026, 1, 10), evidence)
        with self.assertRaises(ValidationError):
            validate_event_years(
                2026,
                2025,
                date(2026, 1, 10),
                {**evidence, "approved": False},
            )

    def test_cross_year_authority_url_must_be_structured_credential_free_https(self):
        evidence = {
            "actual_year": 2026,
            "reason": "official_reschedule",
            "authority_url": "https://authority.example.test/reschedule?notice=official",
            "approved": True,
        }
        validate_event_years(2026, 2025, date(2026, 1, 10), evidence)

        invalid_urls = (
            "not-a-url",
            "http://authority.example.test/reschedule",
            "https://reviewer:secret@authority.example.test/reschedule",
            "https://authority.example.test/reschedule#unreviewed-fragment",
            "https://authority.example.test/reschedule notice",
            "https:///missing-host",
            "ftp://authority.example.test/reschedule",
            "file:///private/evidence.json",
            "data:text/plain,approved",
            "javascript:approved",
        )
        for authority_url in invalid_urls:
            with self.subTest(authority_url=authority_url), self.assertRaises(
                ValidationError
            ):
                validate_event_years(
                    2026,
                    2025,
                    date(2026, 1, 10),
                    {**evidence, "authority_url": authority_url},
                )

    def test_deprecated_hong_kong_season_reason_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_event_years(
                2025,
                2024,
                date(2025, 1, 1),
                {
                    "actual_year": 2025,
                    "reason": "hong_kong_racing_season_spans_calendar_years",
                    "authority_url": "https://racing.hkjc.com/",
                    "approved": True,
                },
            )

    def test_historical_identity_uses_target_year_only_as_edition(self):
        target = SimpleNamespace(
            year=2025,
            source_refs={
                "cross_year_evidence": {
                    "actual_year": 2026,
                    "reason": "official_reschedule",
                    "authority_url": "https://authority.example.test/reschedule",
                    "approved": True,
                }
            },
        )
        self.assertEqual(
            historical_event_identity(target, date(2026, 1, 10)),
            {
                "public_year": 2026,
                "edition_year": 2025,
                "cross_year_evidence": target.source_refs["cross_year_evidence"],
            },
        )


class HistoricalRaceMaterializeYearTests(TestCase):
    def _target(
        self,
        *,
        series_key: str,
        edition_year: int,
        local_date: date,
        source_refs: dict,
        region: str = RacingRegion.UNITED_KINGDOM,
    ) -> HistoricalRaceEventTarget:
        series = RaceSeries.objects.create(
            key=series_key,
            country_region=region,
            canonical_name_original=series_key,
            chinese_name=series_key,
            review_status=RaceSeriesReviewStatus.APPROVED,
        )
        return HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=edition_year,
            country_region=region,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.READY,
            original_name=series_key,
            chinese_name=series_key,
            grade_text="G1",
            normalized_grade="G1",
            racecourse="Test Course",
            surface="turf",
            distance_text="1600m",
            local_date=local_date,
            source_refs=source_refs,
            artifact_sha256="a" * 64,
        )

    def test_materializer_dual_writes_public_and_edition_year(self):
        target = self._target(
            series_key="delayed-edition",
            edition_year=2025,
            local_date=date(2026, 1, 10),
            source_refs={
                "detail_discovery": {
                    "actual_year": 2026,
                    "cross_year_reason": "official_reschedule",
                    "approved": True,
                    "approved_by": "reviewer",
                    "approved_at": "2026-07-31T00:00:00Z",
                    "urls": {
                        "result_url": {
                            "url": "https://authority.example.test/reschedule",
                            "source_authority": "official",
                        }
                    },
                }
            },
        )

        event = materialize_historical_event(target)
        target.refresh_from_db()

        self.assertEqual(event.year, 2026)
        self.assertEqual(event.edition_year, 2025)
        self.assertEqual(event.local_date, date(2026, 1, 10))
        self.assertEqual(event.status, RaceEventStatus.FINISHED)
        self.assertEqual(event.source_refs["cross_year_evidence"]["approved"], True)
        self.assertTrue(historical_basic_fields_complete(target, event)["complete"])

    def test_materializer_rejects_deprecated_hong_kong_season_artifact(self):
        target = self._target(
            series_key="hong-kong-stale-season",
            edition_year=2025,
            local_date=date(2024, 12, 8),
            region=RacingRegion.HONG_KONG,
            source_refs={
                "cross_year_evidence": {
                    "actual_year": 2024,
                    "reason": "hong_kong_racing_season_spans_calendar_years",
                    "authority_url": "https://racing.hkjc.com/",
                    "approved": True,
                }
            },
        )

        with self.assertRaises(InventoryValidationError):
            materialize_historical_event(target)

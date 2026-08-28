from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase

from stable import models
from stable.services.race_data_sync_policy import (
    arbitrate_source_value,
    calculate_next_poll_at,
    normalize_source_class,
    source_priority,
)


NOW = datetime(2026, 8, 28, 4, 0, tzinfo=dt_timezone.utc)


class RaceDataSourcePriorityTests(SimpleTestCase):
    def test_priority_matches_product_rule(self):
        self.assertGreater(source_priority("racingapi"), source_priority("official_website"))
        self.assertGreater(source_priority("official_operator"), source_priority("third_party"))
        self.assertEqual(normalize_source_class("the_racing_api"), "licensed_api")

    def test_higher_class_replaces_newer_lower_class(self):
        decision = arbitrate_source_value(
            current_source_key="jra",
            current_source_class="official_operator",
            current_observed_at=NOW,
            candidate_source_key="the_racing_api",
            candidate_source_class="licensed_api",
            candidate_observed_at=NOW - timedelta(hours=1),
            has_current_value=True,
            values_equal=False,
        )
        self.assertTrue(decision.apply)
        self.assertEqual(decision.reason_code, "higher_priority_source")

    def test_lower_class_never_replaces_higher_class(self):
        decision = arbitrate_source_value(
            current_source_key="the_racing_api",
            current_source_class="licensed_api",
            current_observed_at=NOW - timedelta(days=1),
            candidate_source_key="sporting_life",
            candidate_source_class="trusted_publisher",
            candidate_observed_at=NOW,
            has_current_value=True,
            values_equal=False,
        )
        self.assertFalse(decision.apply)
        self.assertEqual(decision.reason_code, "lower_priority_source")

    def test_equal_class_uses_time_then_stable_provider_key(self):
        newer = arbitrate_source_value(
            current_source_key="jra",
            current_source_class="official_operator",
            current_observed_at=NOW - timedelta(minutes=1),
            candidate_source_key="nar",
            candidate_source_class="official_operator",
            candidate_observed_at=NOW,
            has_current_value=True,
            values_equal=False,
        )
        self.assertTrue(newer.apply)

        tie = arbitrate_source_value(
            current_source_key="nar",
            current_source_class="official_operator",
            current_observed_at=NOW,
            candidate_source_key="jra",
            candidate_source_class="official_operator",
            candidate_observed_at=NOW,
            has_current_value=True,
            values_equal=False,
        )
        self.assertTrue(tie.apply)
        self.assertEqual(tie.reason_code, "stable_provider_tiebreak")

    def test_manual_lock_wins_over_every_source(self):
        decision = arbitrate_source_value(
            current_source_key="manual",
            current_source_class="",
            current_observed_at=None,
            candidate_source_key="the_racing_api",
            candidate_source_class="licensed_api",
            candidate_observed_at=NOW,
            has_current_value=True,
            values_equal=False,
            manual_locked=True,
        )
        self.assertFalse(decision.apply)
        self.assertEqual(decision.reason_code, "manual_lock")


class RaceDataDynamicCadenceTests(SimpleTestCase):
    def test_unknown_race_time_and_distant_racecard_are_checked_twice_daily(self):
        self.assertEqual(
            calculate_next_poll_at(
                data_kind=models.RaceDataSyncDataKind.RACE_TIME,
                now=NOW,
                race_datetime=None,
            ),
            NOW + timedelta(hours=12),
        )
        self.assertEqual(
            calculate_next_poll_at(
                data_kind=models.RaceDataSyncDataKind.RACECARD,
                now=NOW,
                race_datetime=NOW + timedelta(days=30),
            ),
            NOW + timedelta(hours=12),
        )

    def test_racecard_accelerates_near_post_time(self):
        self.assertEqual(
            calculate_next_poll_at(
                data_kind=models.RaceDataSyncDataKind.RACECARD,
                now=NOW,
                race_datetime=NOW + timedelta(hours=5),
            ),
            NOW + timedelta(minutes=10),
        )

    def test_result_uses_explicit_checkpoints_and_correction_watch(self):
        race_datetime = NOW - timedelta(minutes=4)
        self.assertEqual(
            calculate_next_poll_at(
                data_kind=models.RaceDataSyncDataKind.RESULT,
                now=NOW,
                race_datetime=race_datetime,
            ),
            race_datetime + timedelta(minutes=5),
        )
        self.assertEqual(
            calculate_next_poll_at(
                data_kind=models.RaceDataSyncDataKind.RESULT,
                now=NOW,
                race_datetime=NOW - timedelta(hours=12),
                result_confirmed=True,
            ),
            NOW + timedelta(hours=6),
        )

    def test_naive_datetime_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            calculate_next_poll_at(
                data_kind=models.RaceDataSyncDataKind.RACECARD,
                now=NOW.replace(tzinfo=None),
                race_datetime=None,
            )

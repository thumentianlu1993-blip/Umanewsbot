"""
Page regression, term-display integration, and query-count tests.

RED tests verify that current display behavior is incorrect — leading zero
finish positions, missing formal-term Chinese names, non-finish status not
translated, and query counts beyond the gate.

Test case identifiers below refer to ``test_cases.md`` sections 7 (formal term
display), 9 (page regression), and 10 (performance & validation matrix).
"""

from __future__ import annotations

import re
from datetime import date
from unittest.mock import Mock

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from stable.models import (
    HorseProfile,
    HorseProfileStatus,
    HorseRaceRecord,
    HorseRaceResultStatus,
    HorseRaceStartStatus,
    RacingRegion,
    SourceLanguage,
    TermAlias,
    TermEntry,
    TermTranslationStatus,
    TermType,
)
from stable.views import _horse_record_position

# ============================================================================
# Section 9 — finish-position leading-zero regression
# ============================================================================


class HorseRecordPositionLeadingZeroTests(TestCase):
    """test_cases.md id: 76-79 — leading zeros and non-win display."""

    def _mock_record(self, finish_position: str = "", result_status: str = "") -> Mock:
        record = Mock(spec=HorseRaceRecord)
        record.finish_position = finish_position
        record.result_status = result_status
        return record

    # ---- leading-zero RED tests -------------------------------------------

    def test_leading_zero_01_not_won_returns_leading_zero(self):
        """DINOZZO '01' with non-WON result_status displays as '01' not '1'.

        Current behavior: regex ``r'^\\s*([123])(?:\\D|$)'`` does NOT match
        ``'01'`` because the string starts with ``'0'``, and the
        ``result_status`` fallback only covers ``WON``.  The function falls
        through to returning the raw ``finish_position`` verbatim.

        RED because we expect ``'1'`` but get ``'01'``.
        """
        record = self._mock_record(finish_position="01", result_status="")
        result = _horse_record_position(record)
        self.assertEqual(
            result,
            "1",
            f"Expected '1' but got '{result}' — leading-zero handling missing",
        )

    def test_leading_zero_02_not_placed_returns_leading_zero(self):
        """'02' with non-PLACED result_status displays as '02' not '2'.

        Mirror of the ``'01'`` issue for second place.
        """
        record = self._mock_record(finish_position="02", result_status="")
        result = _horse_record_position(record)
        self.assertEqual(
            result,
            "2",
            f"Expected '2' but got '{result}' — leading-zero handling missing",
        )

    def test_leading_zero_03_not_placed_returns_leading_zero(self):
        """'03' with non-PLACED result_status displays as '03' not '3'.

        Mirror of the ``'01'`` issue for third place.
        """
        record = self._mock_record(finish_position="03", result_status="")
        result = _horse_record_position(record)
        self.assertEqual(
            result,
            "3",
            f"Expected '3' but got '{result}' — leading-zero handling missing",
        )

    # ---- non-finish status RED tests --------------------------------------

    def test_dnf_status_shows_raw_dnf_not_chinese(self):
        """DNF status shows as 'DNF' instead of a Chinese label.

        test_cases.md id: 83 — 非完赛状态应显示中文状态，当前不处理。
        """
        record = self._mock_record(finish_position="", result_status=HorseRaceResultStatus.DID_NOT_FINISH)
        result = _horse_record_position(record)
        # Current behavior: empty finish_position → '-'
        self.assertEqual(
            result,
            "未完赛",
            f"Expected Chinese '未完赛' but got '{result}' — non-finish status not translated",
        )

    def test_pu_status_shows_raw_pu(self):
        """PU (pulled up) status shows as raw finish_position value."""
        record = self._mock_record(finish_position="PU", result_status=HorseRaceResultStatus.DID_NOT_FINISH)
        result = _horse_record_position(record)
        self.assertEqual(
            result,
            "拉停",
            f"Expected Chinese '拉停' but got '{result}' — PU status not translated",
        )

    def test_scratched_not_counted_as_start(self):
        """SCRATCHED records should not count as starts.

        test_cases.md id: 53 — SCR/NR/Withdrawn 不计实际出赛。
        """
        record = self._mock_record(finish_position="SCR", result_status=HorseRaceResultStatus.SCRATCHED)
        result = _horse_record_position(record)
        # Current: SCR is not '1' or WON, so returns raw "SCR"
        self.assertEqual(
            result,
            "退赛",
            f"Expected Chinese '退赛' but got '{result}' — scratched not translated",
        )

    # ---- position-display correctness (current-passing baselines) ----------

    def test_won_01_shows_1(self):
        """WON record with '01' shows '1' due to result_status fallback."""
        record = self._mock_record(finish_position="01", result_status=HorseRaceResultStatus.WON)
        result = _horse_record_position(record)
        self.assertEqual(result, "1")

    def test_tenth_not_counted_as_win(self):
        """'10' should display as '10', not match '1' as win.

        test_cases.md id: 79 — Art Power '10' 不计冠军。
        """
        record = self._mock_record(finish_position="10", result_status="")
        result = _horse_record_position(record)
        self.assertEqual(result, "10")


# ============================================================================
# Section 7 — formal term display integration
# ============================================================================


@override_settings(RACE_FIELD_NORMALIZED_DISPLAY_ENABLED=True)
class HorsePageTermDisplayTests(TestCase):
    """test_cases.md id: 58-64 — term display when display flag is enabled."""

    def setUp(self):
        # ---- HorseProfile base term ----
        self.horse_term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            source_ja="DINOZZO",
            target_zh="",
            is_active=True,
        )
        # ---- Racecourse term with Chinese name ----
        self.course_term = TermEntry.objects.create(
            term_type=TermType.RACECOURSE,
            source_language=SourceLanguage.JAPANESE,
            source_ja="東京",
            target_zh="东京竞马场",
            is_active=True,
            translation_status=TermTranslationStatus.TRANSLATED,
        )
        TermAlias.objects.create(
            term=self.course_term,
            source_language=SourceLanguage.JAPANESE,
            text="東京",
            is_active=True,
        )
        # ---- Race term with Chinese name ----
        self.race_term = TermEntry.objects.create(
            term_type=TermType.RACE,
            source_language=SourceLanguage.JAPANESE,
            source_ja="東京優駿",
            target_zh="日本德比",
            is_active=True,
            translation_status=TermTranslationStatus.TRANSLATED,
        )
        TermAlias.objects.create(
            term=self.race_term,
            source_language=SourceLanguage.JAPANESE,
            text="東京優駿",
            is_active=True,
        )
        # ---- HorseProfile ----
        self.profile = HorseProfile.objects.create(
            primary_term=self.horse_term,
            display_name_zh="",
            original_name="DINOZZO",
            review_status=HorseProfileStatus.PUBLISHED,
            racing_region=RacingRegion.JAPAN,
        )
        # ---- RaceRecord with race_name/racecourse that have Chinese terms ----
        self.record = HorseRaceRecord.objects.create(
            horse_profile=self.profile,
            race_name="東京優駿",
            racecourse="東京",
            finish_position="1",
            result_status=HorseRaceResultStatus.WON,
            race_date=date(2024, 5, 26),
            distance_text="2400m",
            grade_text="G1",
            start_status=HorseRaceStartStatus.STARTED,
            source_name="netkeiba",
        )

    def test_race_name_does_not_show_chinese(self):
        """Race name '東京優駿' is NOT displayed as '日本德比' on horse detail.

        The template renders ``{{ record.race_name }}`` directly without a
        display-name service — RED because a TermEntry with the alias exists
        but is not consulted.
        """
        response = self.client.get(f"/horses/{self.profile.pk}/")
        self.assertEqual(response.status_code, 200)
        # The Chinese translation SHOULD be on the page but ISN'T (RED).
        self.assertContains(
            response,
            "日本德比",
            msg_prefix="Expected '日本德比' (term display) on horse detail page — "
            "current rendering only shows raw race_name",
        )

    def test_racecourse_does_not_show_chinese(self):
        """Racecourse '東京' is NOT displayed as '东京竞马场' on horse detail.

        RED because the TermEntry/TermAlias exist but the template renders the
        raw ``racecourse`` field.
        """
        response = self.client.get(f"/horses/{self.profile.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "东京竞马场",
            msg_prefix="Expected '东京竞马场' (term display) on horse detail page — "
            "current rendering only shows raw racecourse",
        )

    def test_raw_race_name_still_rendered(self):
        """Raw race_name '東京優駿' IS rendered (baseline sanity check)."""
        response = self.client.get(f"/horses/{self.profile.pk}/")
        self.assertContains(response, "東京優駿")

    def test_raw_racecourse_still_rendered(self):
        """Raw racecourse '東京' IS rendered (baseline sanity check)."""
        response = self.client.get(f"/horses/{self.profile.pk}/")
        self.assertContains(response, "東京")


class CalendarPageTermDisplayTests(TestCase):
    """test_cases.md id: 58-64 — calendar race / racecourse term display."""

    def setUp(self):
        from stable.models import (
            RaceEvent,
            RaceEventSurface,
            RaceEventVisibility,
            RaceEventDataQuality,
            RaceEventPriority,
        )
        from django.utils import timezone

        today = timezone.localdate()
        self.race_term = TermEntry.objects.create(
            term_type=TermType.RACE,
            source_language=SourceLanguage.JAPANESE,
            source_ja="東京優駿",
            target_zh="日本德比",
            is_active=True,
        )
        TermAlias.objects.create(
            term=self.race_term,
            source_language=SourceLanguage.JAPANESE,
            text="東京優駿",
            is_active=True,
        )
        # Create one race event for today
        self.event = RaceEvent.objects.create(
            original_name="東京優駿",
            chinese_name="日本德比",
            country_region=RacingRegion.JAPAN,
            racecourse="東京",
            grade_text="G1",
            normalized_grade="G1",
            surface=RaceEventSurface.TURF,
            distance_text="2400",
            year=2024,
            local_date=today,
            visibility_status=RaceEventVisibility.PUBLISHED,
            data_quality_status=RaceEventDataQuality.COMPLETE,
            priority=RaceEventPriority.P0,
        )

    def test_calendar_race_name_shows_chinese(self):
        """Race event original_name has Chinese name but may not be displayed.

        RED — if the calendar page accepts a ``chinese_name`` that exists
        but isn't always applied, this test fails.
        """
        response = self.client.get("/races/")
        self.assertEqual(response.status_code, 200)
        # The calendar SHOULD show the Chinese name
        self.assertContains(
            response,
            "日本德比",
            msg_prefix="Expected Chinese race name on calendar page",
        )


# ============================================================================
# Section 10 — query count baseline
# ============================================================================


class HorseDetailQueryCountTests(TestCase):
    """test_cases.md id: 89, 89a — query count with 20 race records."""

    def setUp(self):
        self.horse_term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            source_ja="DINOZZO",
            target_zh="",
            is_active=True,
        )
        self.profile = HorseProfile.objects.create(
            primary_term=self.horse_term,
            display_name_zh="",
            original_name="DINOZZO",
            review_status=HorseProfileStatus.PUBLISHED,
            racing_region=RacingRegion.HONG_KONG,
        )

    def _create_records(self, count: int) -> list[HorseRaceRecord]:
        records: list[HorseRaceRecord] = []
        for i in range(count):
            pos = f"{i + 1:02d}" if i < 3 else str(i + 1)
            rec = HorseRaceRecord.objects.create(
                horse_profile=self.profile,
                race_name=f"Race {i + 1}",
                racecourse="ST",
                finish_position=pos,
                result_status=(
                    HorseRaceResultStatus.WON
                    if i == 0
                    else HorseRaceResultStatus.UNKNOWN
                ),
                race_date=date(2024, 1, 1),
                distance_text="1200",
                grade_text="",
                start_status=HorseRaceStartStatus.STARTED,
            )
            records.append(rec)
        return records

    def test_20_records_query_count_gate(self):
        """Horse detail page with 20 records stays within query gate (RED if exceeded).

        Current baseline is 11 queries.  RED gate is 14.
        """
        self._create_records(20)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(f"/horses/{self.profile.pk}/")
        qcount = len(ctx)
        self.assertLessEqual(
            qcount,
            14,
            f"Query count {qcount} exceeds RED gate of 14",
        )

    def test_1_record_query_count_equals_20(self):
        """1-record page and 20-record page should issue the same number of
        term/alias queries (batch resolution).  Currently they already match
        because no batch term service has been added yet — RED if they diverge
        after implementation.
        """
        self._create_records(1)
        with CaptureQueriesContext(connection) as ctx1:
            self.client.get(f"/horses/{self.profile.pk}/")
        count_1 = len(ctx1)

        # Create 19 more records for the 20-record variant
        self._create_records(19)
        with CaptureQueriesContext(connection) as ctx2:
            self.client.get(f"/horses/{self.profile.pk}/")
        count_20 = len(ctx2)

        # The term/alias query count should be the same (batch resolution).
        # Currently they match because no term service is consulted at all.
        self.assertEqual(
            count_1,
            count_20,
            f"Query count differs: 1-record={count_1}, 20-record={count_20}. "
            "Batch term resolution not implemented (per-record querying).",
        )


class CalendarQueryCountTests(TestCase):
    """test_cases.md id: 88 — 40-event calendar query count."""

    def setUp(self):
        from stable.models import (
            RaceEvent,
            RaceEventSurface,
            RaceEventVisibility,
            RaceEventDataQuality,
            RaceEventPriority,
        )
        from django.utils import timezone

        today = timezone.localdate()
        for i in range(40):
            RaceEvent.objects.create(
                original_name=f"Race {i + 1}",
                chinese_name="",
                country_region=RacingRegion.JAPAN,
                racecourse="TC",
                grade_text="G1",
                normalized_grade="G1",
                surface=RaceEventSurface.TURF,
                distance_text="2000",
                year=2024,
                local_date=today,
                visibility_status=RaceEventVisibility.PUBLISHED,
                data_quality_status=RaceEventDataQuality.COMPLETE,
                priority=RaceEventPriority.P0,
            )

    def test_calendar_40_events_query_count_gate(self):
        """40-event calendar stays within query gate (RED if exceeded)."""
        with CaptureQueriesContext(connection) as ctx:
            self.client.get("/races/")
        qcount = len(ctx)
        self.assertLessEqual(
            qcount,
            14,
            f"40-event calendar query count {qcount} exceeds RED gate of 14",
        )

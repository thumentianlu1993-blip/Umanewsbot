"""
Tests for race_field_normalization.py pure functions.

This file is intentionally written against a module and enums that do not yet
exist.  Importing from ``stable.services.race_field_normalization`` will raise
``ModuleNotFoundError`` -- this is the expected RED state before implementation.

Test case identifiers below refer to ``test_cases.md`` section 2 (pure function
contract) and section 3 (five-region fixtures).
"""

from __future__ import annotations

import hashlib

from django.test import TestCase

# ---------------------------------------------------------------------------
# Imports that will fail on first run (target module does not exist yet).
# Each import group is isolated so the RED is clearly attributable.
# ---------------------------------------------------------------------------

# test_cases.md 2.x  --  finish position & status
from stable.services.race_field_normalization import (  # noqa: F401  # ModuleNotFoundError expected  # noqa: E501
    FinishNormalization,
    normalize_finish_position,
    NormalizedRaceResultStatus,
)

# test_cases.md 2.x  --  grade
from stable.services.race_field_normalization import (  # noqa: F401  # ModuleNotFoundError expected  # noqa: E501
    GradeNormalization,
    normalize_grade,
)

# test_cases.md 2.x  --  distance
from stable.services.race_field_normalization import (  # noqa: F401  # ModuleNotFoundError expected  # noqa: E501
    RACE_FIELD_NORMALIZATION_VERSION,
    DISTANCE_CONVERSION_CONSTANTS,
    DistanceNormalization,
    DistancePrecision,
    normalize_distance,
)

# test_cases.md 2.x  --  surface / race-type / layout / going
from stable.services.race_field_normalization import (  # noqa: F401  # ModuleNotFoundError expected  # noqa: E501
    SurfaceNormalization,
    NormalizedSurface,
    NormalizedRaceType,
    normalize_surface_race_type_layout_going,
)

# test_cases.md 2.x  --  eligibility (age, sex, constraints)
from stable.services.race_field_normalization import (  # noqa: F401  # ModuleNotFoundError expected  # noqa: E501
    EligibilityNormalization,
    RaceSexRestriction,
    normalize_eligibility,
)

# test_cases.md 2.x  --  historical context recovery
from stable.services.race_field_normalization import (  # noqa: F401  # ModuleNotFoundError expected  # noqa: E501
    ContextRecoveryResult,
    normalize_context,
)

# also expected to fail:
from stable.services.race_field_normalization import (  # noqa: F401  # ModuleNotFoundError expected  # noqa: E501
    REASON_CODE_CONTEXT_FROM_LINKED_EVENT,
    REASON_CODE_CONTEXT_FROM_VALIDATED_SOURCE_REF,
    REASON_CODE_CONTEXT_FROM_OFFICIAL_VENUE_ID,
    REASON_CODE_CONTEXT_FROM_UNIQUE_FORMAL_TERM,
    REASON_CODE_REGION_UNKNOWN,
    REASON_CODE_SOURCE_LANGUAGE_UNKNOWN,
    REASON_CODE_CONTEXT_CONFLICT,
)


# ====== 1. 完赛名次与状态 ===========================================
# test_cases.md id: 1-9

class FinishPositionAndStatusNormalizationTests(TestCase):
    """Section 2 -- 完赛名次与状态 (test cases 1--9)."""

    def test_position_01_1_1st_returns_1(self):
        """Case 1: '01', '1', '1st', '第1' -> position=1"""
        result = normalize_finish_position("01", source_kind="hkjc")
        self.assertEqual(result.position, 1)

        result = normalize_finish_position("1", source_kind="sporting_life")
        self.assertEqual(result.position, 1)

        result = normalize_finish_position("1st", source_kind="sporting_life")
        self.assertEqual(result.position, 1)

        result = normalize_finish_position("第1", source_kind="netkeiba")
        self.assertEqual(result.position, 1)

    def test_position_02_2_2nd_returns_2(self):
        """Case 2: '02', '2', '2nd', '第2' -> position=2"""
        result = normalize_finish_position("02", source_kind="hkjc")
        self.assertEqual(result.position, 2)

        result = normalize_finish_position("2", source_kind="sporting_life")
        self.assertEqual(result.position, 2)

        result = normalize_finish_position("2nd", source_kind="sporting_life")
        self.assertEqual(result.position, 2)

        result = normalize_finish_position("第2", source_kind="netkeiba")
        self.assertEqual(result.position, 2)

    def test_position_03_3_3rd_returns_3(self):
        """Case 3: '03', '3', '3rd', '第3' -> position=3"""
        result = normalize_finish_position("03", source_kind="hkjc")
        self.assertEqual(result.position, 3)

        result = normalize_finish_position("3", source_kind="sporting_life")
        self.assertEqual(result.position, 3)

        result = normalize_finish_position("3rd", source_kind="sporting_life")
        self.assertEqual(result.position, 3)

        result = normalize_finish_position("第3", source_kind="netkeiba")
        self.assertEqual(result.position, 3)

    def test_position_10_never_counts_as_winner(self):
        """Case 4: '10', '10th' -> position=10, never winner"""
        result = normalize_finish_position("10", source_kind="sporting_life")
        self.assertEqual(result.position, 10)
        self.assertNotEqual(result.position, 1)

        result = normalize_finish_position("10th", source_kind="sporting_life")
        self.assertEqual(result.position, 10)
        self.assertNotEqual(result.position, 1)

    def test_dead_heat_retains_position_with_status(self):
        """Case 5: dead heat retains numeric position and status dead_heat"""
        result = normalize_finish_position("1", source_kind="sporting_life", is_dead_heat=True)
        self.assertEqual(result.position, 1)
        self.assertEqual(result.status, NormalizedRaceResultStatus.DEAD_HEAT)

        result = normalize_finish_position("DH", source_kind="sporting_life")
        self.assertIsNone(result.position)
        self.assertEqual(result.status, NormalizedRaceResultStatus.DEAD_HEAT)

    def test_dnf_pu_ur_f_dsq_mapped_to_fine_grained_statuses(self):
        """Case 6: DNF, PU, UR, F, DSQ -> fine-grained statuses"""
        cases = {
            "DNF": NormalizedRaceResultStatus.DID_NOT_FINISH,
            "PU": NormalizedRaceResultStatus.PULLED_UP,
            "UR": NormalizedRaceResultStatus.UNSEATED_RIDER,
            "F": NormalizedRaceResultStatus.FELL,
            "DSQ": NormalizedRaceResultStatus.DISQUALIFIED,
            "DQ": NormalizedRaceResultStatus.DISQUALIFIED,
            "BD": NormalizedRaceResultStatus.BROUGHT_DOWN,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                result = normalize_finish_position(raw, source_kind="sporting_life")
                self.assertEqual(result.status, expected)
                self.assertIsNone(result.position)

    def test_scr_nr_withdrawn_map_to_non_runner_status(self):
        """Case 7: SCR, NR, Withdrawn -> non-started, position=None"""
        cases = {"SCR": NormalizedRaceResultStatus.SCRATCHED,
                 "NR": NormalizedRaceResultStatus.NON_RUNNER,
                 "Withdrawn": NormalizedRaceResultStatus.WITHDRAWN,
                 "WV": NormalizedRaceResultStatus.WITHDRAWN}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                result = normalize_finish_position(raw, source_kind="sporting_life")
                self.assertEqual(result.status, expected)
                self.assertIsNone(result.position)

    def test_empty_unknown_returns_unknown_status_and_reason(self):
        """Case 8: empty/unknown -> status=unknown, position=None, reason preserved"""
        cases = ["", "??", "N/A", None]
        for raw in cases:
            with self.subTest(raw=repr(raw)):
                result = normalize_finish_position(raw, source_kind="sporting_life")
                self.assertIsNone(result.position)
                self.assertEqual(result.status, NormalizedRaceResultStatus.UNKNOWN)
                self.assertEqual(result.reason.status, "unknown")

    def test_01_is_not_scratched(self):
        """Case 1 special: '01' is numeric position 1, NOT a non-started status code."""
        result = normalize_finish_position("01", source_kind="hkjc")
        self.assertEqual(result.position, 1)
        self.assertIsNotNone(result.position)
        self.assertEqual(result.status, NormalizedRaceResultStatus.FINISHED)

    def test_identical_input_same_version_returns_same_result_and_sha(self):
        """Case 9: same input + same version -> deterministic result + same input SHA."""
        result1 = normalize_finish_position("01", source_kind="hkjc")
        result2 = normalize_finish_position("01", source_kind="hkjc")
        # same position and status
        self.assertEqual(result1.position, result2.position)
        self.assertEqual(result1.status, result2.status)
        # input SHA is deterministic
        expected_sha = hashlib.sha256("01".encode("utf-8")).hexdigest()
        self.assertEqual(result1.input_sha256, expected_sha)
        self.assertEqual(result1.input_sha256, result2.input_sha256)
        # version matches
        self.assertEqual(result1.version, RACE_FIELD_NORMALIZATION_VERSION)


# ====== 2. 等级 =====================================================
# test_cases.md id: 10-18

class GradeNormalizationTests(TestCase):
    """Section 2 -- 等级 (test cases 10--18)."""

    def test_g1_variants_map_to_g1(self):
        """Case 10: G1, GI, GⅠ, Group 1, Grade 1, Groupe I -> G1"""
        sources = {
            "G1": "en",
            "GI": "en",
            "G1": "en",
            "Group 1": "en",
            "Grade 1": "en",
            "Groupe I": "fr",
        }
        # We also test with NFKC normalization
        for raw, lang in sources.items():
            with self.subTest(raw=raw):
                result = normalize_grade(raw, source_language=lang)
                self.assertEqual(result.grade, "G1")

    def test_g2_g3_variants(self):
        """Case 11: G2/G3 equivalent formats -> G2/G3."""
        for marker in ("G2", "GII", "Group 2", "Grade 2", "Groupe II"):
            with self.subTest(marker=marker):
                result = normalize_grade(marker, source_language="en")
                self.assertEqual(result.grade, "G2")

        for marker in ("G3", "GIII", "Group 3", "Grade 3", "Groupe III"):
            with self.subTest(marker=marker):
                result = normalize_grade(marker, source_language="en")
                self.assertEqual(result.grade, "G3")

    def test_jpn1_distinct_from_g1(self):
        """Case 12: Jpn1 is distinct from G1."""
        result_g1 = normalize_grade("G1", source_language="en")
        result_jpn1 = normalize_grade("Jpn1", source_language="en")
        self.assertEqual(result_g1.grade, "G1")
        self.assertEqual(result_jpn1.grade, "JPN1")
        self.assertNotEqual(result_jpn1.grade, result_g1.grade)

        # Jpn2, Jpn3 also distinct
        self.assertEqual(normalize_grade("Jpn2", source_language="en").grade, "JPN2")
        self.assertEqual(normalize_grade("Jpn3", source_language="en").grade, "JPN3")

    def test_jg1_jg1_distinct_from_g1(self):
        """Case 13: J-G1/JG1 is distinct from ordinary G1."""
        result_g1 = normalize_grade("G1", source_language="en")
        result_jg1 = normalize_grade("J-G1", source_language="en")
        self.assertEqual(result_g1.grade, "G1")
        self.assertEqual(result_jg1.grade, "JG1")
        self.assertNotEqual(result_jg1.grade, result_g1.grade)

        # JG2, JG3 also distinct
        self.assertEqual(normalize_grade("JG1", source_language="en").grade, "JG1")
        self.assertEqual(normalize_grade("J-G2", source_language="en").grade, "JG2")
        self.assertEqual(normalize_grade("JG3", source_language="en").grade, "JG3")

    def test_hong_kong_chinese_grades_map_to_standard(self):
        """Case 14: HK Chinese grades map to G1/G2/G3 with correct context."""
        for raw in ("一级赛", "一級賽", "香港一级赛"):
            with self.subTest(raw=raw):
                result = normalize_grade(raw, source_language="zh", source_region="hk")
                self.assertEqual(result.grade, "G1")

        for raw in ("二级赛", "二級賽", "香港二级赛"):
            with self.subTest(raw=raw):
                result = normalize_grade(raw, source_language="zh", source_region="hk")
                self.assertEqual(result.grade, "G2")

        for raw in ("三级赛", "三級賽", "香港三级赛"):
            with self.subTest(raw=raw):
                result = normalize_grade(raw, source_language="zh", source_region="hk")
                self.assertEqual(result.grade, "G3")

    def test_listed_l_maps_to_l(self):
        """Case 15: Listed / L -> L."""
        result = normalize_grade("Listed", source_language="en")
        self.assertEqual(result.grade, "L")

        result = normalize_grade("L", source_language="en")
        self.assertEqual(result.grade, "L")

        result = normalize_grade("リステッド", source_language="ja")
        self.assertEqual(result.grade, "L")

    def test_class_1_not_g1(self):
        """Case 16: Class 1 is NOT G1."""
        result = normalize_grade("Class 1", source_language="en", source_region="gb")
        self.assertNotEqual(result.grade, "G1")
        self.assertEqual(result.status, "preserved")

    def test_french_class_category_not_groupe(self):
        """Case 17: French Class / Category / Classe -> not Groupe."""
        for raw in ("Classe 1", "Category 2", "Classe 2"):
            with self.subTest(raw=raw):
                result = normalize_grade(raw, source_language="fr")
                self.assertNotIn(result.grade, ("G1", "G2", "G3"))
                self.assertEqual(result.status, "preserved")

    def test_unknown_grade_preserves_original(self):
        """Case 18: Unknown grade preserves original text."""
        result = normalize_grade("SomeWeirdGrade", source_language="en")
        self.assertEqual(result.status, "preserved")
        self.assertEqual(result.original, "SomeWeirdGrade")


# ====== 3. 距离 =====================================================
# test_cases.md id: 19-25

class DistanceNormalizationTests(TestCase):
    """Section 2 -- 距离 (test cases 19--25)."""

    def test_metric_values_parse_as_official(self):
        """Case 19: '1200m', '1200米' -> official metric."""
        result = normalize_distance("1200m")
        self.assertEqual(result.meters, 1200)
        self.assertEqual(result.precision, DistancePrecision.OFFICIAL_METRIC)

        result = normalize_distance("1200米")
        self.assertEqual(result.meters, 1200)
        self.assertEqual(result.precision, DistancePrecision.OFFICIAL_METRIC)

    def test_furlongs_convert_exactly(self):
        """Case 20: '6f', '9f' -> exact conversion."""
        result = normalize_distance("6f")
        expected_m = 6 * DISTANCE_CONVERSION_CONSTANTS["furlong"]
        self.assertEqual(result.meters, expected_m)
        self.assertEqual(result.precision, DistancePrecision.EXACT_CONVERSION)
        self.assertEqual(result.source_unit, "f")

        result = normalize_distance("9f")
        expected_m = 9 * DISTANCE_CONVERSION_CONSTANTS["furlong"]
        self.assertEqual(result.meters, expected_m)
        self.assertEqual(result.precision, DistancePrecision.EXACT_CONVERSION)

    def test_mile_and_mile_furlong_combinations(self):
        """Case 21: '1m', '1m2f', '1m 2f' -> correct parsed value."""
        mile_m = DISTANCE_CONVERSION_CONSTANTS["mile"]
        furlong_m = DISTANCE_CONVERSION_CONSTANTS["furlong"]

        result = normalize_distance("1m")
        self.assertEqual(result.meters, mile_m)
        self.assertEqual(result.precision, DistancePrecision.EXACT_CONVERSION)

        result = normalize_distance("1m2f")
        self.assertEqual(result.meters, mile_m + 2 * furlong_m)
        self.assertEqual(result.precision, DistancePrecision.EXACT_CONVERSION)

        result = normalize_distance("1m 2f")
        self.assertEqual(result.meters, mile_m + 2 * furlong_m)
        self.assertEqual(result.precision, DistancePrecision.EXACT_CONVERSION)

        result = normalize_distance("2m 5f 191y")
        expected_m = 2 * mile_m + 5 * furlong_m + 191 * DISTANCE_CONVERSION_CONSTANTS["yard"]
        self.assertEqual(result.meters, expected_m)
        self.assertEqual(result.precision, DistancePrecision.EXACT_CONVERSION)

    def test_yard_and_foot_combinations(self):
        """Case 22: '4f 213y', feet/yards combinations."""
        furlong_m = DISTANCE_CONVERSION_CONSTANTS["furlong"]
        yard_m = DISTANCE_CONVERSION_CONSTANTS["yard"]
        foot_m = DISTANCE_CONVERSION_CONSTANTS["foot"]

        result = normalize_distance("4f 213y")
        self.assertEqual(result.meters, 4 * furlong_m + 213 * yard_m)
        self.assertEqual(result.precision, DistancePrecision.EXACT_CONVERSION)

        result = normalize_distance("4f 213y 0ft")
        expected = 4 * furlong_m + 213 * yard_m
        self.assertEqual(result.meters, expected)

    def test_about_prefix_not_official(self):
        """Case 23: 'about 6f' -> NOT official metric or exact conversion."""
        result = normalize_distance("about 6f")
        self.assertNotEqual(result.precision, DistancePrecision.OFFICIAL_METRIC)
        self.assertNotEqual(result.precision, DistancePrecision.EXACT_CONVERSION)

        result = normalize_distance("approx 6f")
        self.assertNotEqual(result.precision, DistancePrecision.OFFICIAL_METRIC)
        self.assertNotEqual(result.precision, DistancePrecision.EXACT_CONVERSION)

    def test_conflicting_metric_and_imperial_fails_closed(self):
        """Case 24: Official metric + text imperial conflict -> fail closed."""
        result = normalize_distance(
            "1200m",
            official_metric_meters=1200,
            raw_text="6f",
        )
        self.assertEqual(result.status, "conflict")
        self.assertIn("conflict", result.reason.reason_code)

    def test_raw_unit_and_text_always_preserved(self):
        """Case 25: Original units and text always kept in result."""
        result = normalize_distance("6f")
        self.assertEqual(result.source_unit, "f")
        self.assertEqual(result.original, "6f")

        result = normalize_distance("1200m")
        self.assertEqual(result.source_unit, "m")
        self.assertEqual(result.original, "1200m")


# ====== 4. 场地、赛种、路线和 going =================================
# test_cases.md id: 26-30

class SurfaceRaceTypeLayoutGoingTests(TestCase):
    """Section 2 -- 场地、赛种、路线和 going (test cases 26--30)."""

    def test_turf_dirt_aw_synthetic_mapped(self):
        """Case 26: turf/dirt/AW/synthetic -> surface mapping correct."""
        cases = {
            "turf": (NormalizedSurface.TURF, None),
            "Turf": (NormalizedSurface.TURF, None),
            "dirt": (NormalizedSurface.DIRT, None),
            "Dirt": (NormalizedSurface.DIRT, None),
            "AW": (NormalizedSurface.SYNTHETIC, None),
            "all-weather": (NormalizedSurface.SYNTHETIC, None),
            "synthetic": (NormalizedSurface.SYNTHETIC, None),
            "ポリトラック": (NormalizedSurface.SYNTHETIC, "ja"),
            "ダート": (NormalizedSurface.DIRT, "ja"),
            "芝": (NormalizedSurface.TURF, "ja"),
        }
        for raw, (expected_surface, lang) in cases.items():
            with self.subTest(raw=raw):
                result = normalize_surface_race_type_layout_going(raw, source_language=lang or "en")
                self.assertEqual(result.surface, expected_surface)

    def test_hurdle_steeplechase_goes_to_race_type_not_flat(self):
        """Case 27: hurdle/steeplechase -> race_type, NOT flat."""
        for raw in ("hurdle", "Hurdle", "障害", "steeplechase", "Steeplechase", "チェイス"):
            with self.subTest(raw=raw):
                result = normalize_surface_race_type_layout_going(raw)
                self.assertNotEqual(result.race_type, NormalizedRaceType.FLAT)
                self.assertIn(
                    result.race_type,
                    (NormalizedRaceType.HURDLE, NormalizedRaceType.STEEPLECHASE, NormalizedRaceType.OTHER),
                )

    def test_going_not_written_to_surface(self):
        """Case 28: going text -> going field, NOT surface."""
        for raw in ("Good", "Soft", "Heavy", "Firm", "Yielding", "Standard"):
            with self.subTest(raw=raw):
                result = normalize_surface_race_type_layout_going(raw)
                # going_text should be preserved, surface should NOT be set from going
                self.assertEqual(result.going_text, raw)
                # surface is not the going value
                if result.surface:
                    self.assertNotEqual(result.surface.value.lower(), raw.lower())

    def test_hkjc_racecourse_surface_layout_split(self):
        """Case 29: 'ST / Turf / \"A\"' -> course=ST, surface=turf, layout=A."""
        result = normalize_surface_race_type_layout_going("ST / Turf / \"A\"", source_language="zh", source_region="hk")
        self.assertIn("ST", result.course_text)
        self.assertEqual(result.surface, NormalizedSurface.TURF)
        self.assertEqual(result.course_layout, "A")

        result = normalize_surface_race_type_layout_going("HV / Turf / \"B+2\"", source_language="zh", source_region="hk")
        self.assertIn("HV", result.course_text)
        self.assertEqual(result.surface, NormalizedSurface.TURF)
        self.assertEqual(result.course_layout, "B+2")

    def test_unknown_or_conflict_preserves_original(self):
        """Case 30: unknown/conflict -> preserve original text."""
        result = normalize_surface_race_type_layout_going("SomeBogusSurface")
        self.assertEqual(result.status, "preserved")
        self.assertEqual(result.original, "SomeBogusSurface")


# ====== 5. 年龄与资格 ===============================================
# test_cases.md id: 31-34

class EligibilityNormalizationTests(TestCase):
    """Section 2 -- 年龄与资格 (test cases 31--34)."""

    def test_age_ranges_correct(self):
        """Case 31: '2yo'/'3yo' -> exact age; '3U'/'4yo+' -> open-ended."""
        result = normalize_eligibility("2yo")
        self.assertEqual(result.min_age, 2)
        self.assertEqual(result.max_age, 2)
        self.assertFalse(result.age_open_ended)

        result = normalize_eligibility("3yo")
        self.assertEqual(result.min_age, 3)
        self.assertEqual(result.max_age, 3)

        result = normalize_eligibility("3U")
        self.assertEqual(result.min_age, 3)
        self.assertIsNone(result.max_age)
        self.assertTrue(result.age_open_ended)

        result = normalize_eligibility("3UP")
        self.assertEqual(result.min_age, 3)
        self.assertTrue(result.age_open_ended)

        result = normalize_eligibility("3yo+")
        self.assertEqual(result.min_age, 3)
        self.assertTrue(result.age_open_ended)

        result = normalize_eligibility("4yo+")
        self.assertEqual(result.min_age, 4)
        self.assertTrue(result.age_open_ended)

        result = normalize_eligibility("2歳")
        self.assertEqual(result.min_age, 2)
        self.assertEqual(result.max_age, 2)

        result = normalize_eligibility("3歳")
        self.assertEqual(result.min_age, 3)
        self.assertEqual(result.max_age, 3)

        result = normalize_eligibility("3歳以上")
        self.assertEqual(result.min_age, 3)
        self.assertTrue(result.age_open_ended)

    def test_mares_fillies_separated_from_age(self):
        """Case 32: 'mares', 'fillies' -> sex=female."""
        result = normalize_eligibility("mares")
        self.assertEqual(result.sex, RaceSexRestriction.FEMALE)
        self.assertIsNone(result.min_age)

        result = normalize_eligibility("fillies")
        self.assertEqual(result.sex, RaceSexRestriction.FEMALE)

        result = normalize_eligibility("牝")
        self.assertEqual(result.sex, RaceSexRestriction.FEMALE)

    def test_complex_eligibility_normalizes_reliable_tokens_only(self):
        """Case 33: '3U f 3UP F/M ...' -> only reliable tokens normalized."""
        result = normalize_eligibility("3U f 3UP F/M")
        self.assertEqual(result.min_age, 3)
        self.assertTrue(result.age_open_ended)
        self.assertEqual(result.sex, RaceSexRestriction.FEMALE)
        # remaining tokens preserved
        self.assertIsNotNone(result.extra_constraints)

    def test_complex_unknown_not_compressed_to_bad_age(self):
        """Case 34: complex unknown eligibility -> not compressed to wrong age."""
        result = normalize_eligibility("claimer 5000nzw")
        # should NOT claim age=5 or anything fabricated
        self.assertIsNone(result.min_age)
        self.assertIsNone(result.max_age)
        self.assertEqual(result.status, "preserved")


# ====== 6. 历史上下文恢复 ===========================================
# test_cases.md id: 34a-34d

class HistoricalContextRecoveryTests(TestCase):
    """Section 2 -- 历史上下文 (test cases 34a--34d)."""

    def test_overseas_record_not_inherit_horse_region(self):
        """Case 34a: Overseas record does NOT inherit HorseProfile.racing_region."""
        result = normalize_context(
            raw_region="",
            horse_profile_racing_region="jp",
            provider="sporting_life",
        )
        # Should NOT return 'jp' just because horse is Japanese
        self.assertNotEqual(result.region, "jp")
        self.assertIn(result.reason.reason_code, ("region_unknown", "source_language_unknown"))

    def test_provider_only_sets_language_not_region(self):
        """Case 34b: provider -> language/format dialect, NOT racing region."""
        for provider in ("netkeiba", "sporting_life", "hrn"):
            with self.subTest(provider=provider):
                result = normalize_context(raw_region="", provider=provider)
                self.assertIsNotNone(result.source_language)
                # region should NOT be inferred from provider
                self.assertNotIn(result.reason.reason_code, ("context_from_validated_source_ref",))

    def test_event_source_venue_priority_order(self):
        """Case 34c: linked event > validated source ref > venue ID."""
        # linked event should take highest priority
        result = normalize_context(
            raw_region="",
            linked_event_region="gb",
            validated_source_ref_region="hk",
        )
        self.assertEqual(result.reason.reason_code, "context_from_linked_event")
        self.assertEqual(result.region, "gb")

        # validated source ref when no linked event
        result = normalize_context(
            raw_region="",
            validated_source_ref_region="hk",
            official_venue_id_region="gb",
        )
        self.assertEqual(result.reason.reason_code, "context_from_validated_source_ref")
        self.assertEqual(result.region, "hk")

        # official venue ID when no better context
        result = normalize_context(
            raw_region="",
            official_venue_id_region="fr",
        )
        self.assertEqual(result.reason.reason_code, "context_from_official_venue_id")
        self.assertEqual(result.region, "fr")

    def test_context_conflict_missing_returns_reason_code(self):
        """Case 34d: missing/conflicting context -> reason code and preserve original."""
        result = normalize_context(raw_region="")
        self.assertIn(result.reason.reason_code, ("region_unknown", "source_language_unknown"))

        # conflicting contexts
        result = normalize_context(
            raw_region="hk",
            linked_event_region="gb",
            validated_source_ref_region="fr",
        )
        self.assertEqual(result.reason.reason_code, "context_conflict")


# ====== 7. 日本 =====================================================
# test_cases.md section 3, Japan fixture

class JapanFixtureTests(TestCase):
    """Section 3 -- Japan (netkeiba/JBIS)."""

    def test_japanese_distance_notation(self):
        """芝1200 (turf), ダ1800 (dirt), 障3110 (jumps)."""
        result = normalize_distance("芝1200")
        self.assertEqual(result.meters, 1200)
        self.assertEqual(result.precision, DistancePrecision.OFFICIAL_METRIC)
        # surface side-effect check
        surface_result = normalize_surface_race_type_layout_going("芝", source_language="ja")
        self.assertEqual(surface_result.surface, NormalizedSurface.TURF)

        result = normalize_distance("ダ1800")
        self.assertEqual(result.meters, 1800)

        result = normalize_distance("障3110")
        self.assertEqual(result.meters, 3110)

    def test_japanese_cancellation_and_statuses(self):
        """取消 (scratched), 除外 (excluded), 中止 (cancelled), 失格 (disqualified)."""
        cases = {
            "取消": NormalizedRaceResultStatus.SCRATCHED,
            "除外": NormalizedRaceResultStatus.SCRATCHED,
            "中止": NormalizedRaceResultStatus.DID_NOT_FINISH,
            "失格": NormalizedRaceResultStatus.DISQUALIFIED,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                result = normalize_finish_position(raw, source_kind="netkeiba")
                self.assertEqual(result.status, expected)

    def test_japanese_age_notation(self):
        """２歳 (2yo), ３歳 (3yo), ３歳以上 (3UP), 牮 (female)."""
        result = normalize_eligibility("2歳")
        self.assertEqual(result.min_age, 2)

        result = normalize_eligibility("3歳")
        self.assertEqual(result.min_age, 3)

        result = normalize_eligibility("3歳以上")
        self.assertEqual(result.min_age, 3)
        self.assertTrue(result.age_open_ended)

        result = normalize_eligibility("牝")
        self.assertEqual(result.sex, RaceSexRestriction.FEMALE)

    def test_japanese_grade_distinction(self):
        """G, Jpn, J-G grades distinct for Japan."""
        self.assertEqual(normalize_grade("G1", source_language="ja").grade, "G1")
        self.assertEqual(normalize_grade("Jpn1", source_language="ja").grade, "JPN1")
        self.assertEqual(normalize_grade("J-G1", source_language="ja").grade, "JG1")
        self.assertEqual(normalize_grade("J・G1", source_language="ja").grade, "JG1")


# ====== 8. 中国香港 =================================================
# test_cases.md section 3, Hong Kong fixture

class HongKongFixtureTests(TestCase):
    """Section 3 -- Hong Kong (HKJC)."""

    def test_hkjc_two_digit_positions(self):
        """"01"/"02"/"03" -> positions 1/2/3."""
        self.assertEqual(normalize_finish_position("01", source_kind="hkjc").position, 1)
        self.assertEqual(normalize_finish_position("02", source_kind="hkjc").position, 2)
        self.assertEqual(normalize_finish_position("03", source_kind="hkjc").position, 3)
        # higher two-digit numbers
        self.assertEqual(normalize_finish_position("10", source_kind="hkjc").position, 10)

    def test_hkjc_course_names(self):
        """ST -> Sha Tin candidate, HV -> Happy Valley candidate."""
        result_st = normalize_surface_race_type_layout_going("ST", source_language="zh", source_region="hk")
        self.assertIn("ST", result_st.course_text)

        result_hv = normalize_surface_race_type_layout_going("HV", source_language="zh", source_region="hk")
        self.assertIn("HV", result_hv.course_text)

    def test_hkjc_turf_and_layout(self):
        """Turf + 'A'/'B+2'/'C+3' layout parsing."""
        for layout in ('"A"', '"B+2"', '"C+3"'):
            with self.subTest(layout=layout):
                combined = f"ST / Turf / {layout}"
                result = normalize_surface_race_type_layout_going(combined, source_language="zh", source_region="hk")
                self.assertEqual(result.surface, NormalizedSurface.TURF)

    def test_hkjc_distance_without_unit(self):
        """HKJC uses bare metric numbers without 'm'."""
        result = normalize_distance("1200")
        self.assertEqual(result.meters, 1200)
        self.assertEqual(result.precision, DistancePrecision.OFFICIAL_METRIC)

        result = normalize_distance("1600")
        self.assertEqual(result.meters, 1600)

    def test_hong_kong_chinese_grade(self):
        """HK Chinese grade -> standard like G1."""
        self.assertEqual(normalize_grade("一级赛", source_language="zh", source_region="hk").grade, "G1")
        self.assertEqual(normalize_grade("二级赛", source_language="zh", source_region="hk").grade, "G2")
        self.assertEqual(normalize_grade("三级赛", source_language="zh", source_region="hk").grade, "G3")


# ====== 9. 英国 =====================================================
# test_cases.md section 3, UK fixture

class UKFixtureTests(TestCase):
    """Section 3 -- UK (Sporting Life / Racing Post)."""

    def test_uk_distance_notation(self):
        """UK '1m 2f', '2m 5f 191y'."""
        mile_m = DISTANCE_CONVERSION_CONSTANTS["mile"]
        furlong_m = DISTANCE_CONVERSION_CONSTANTS["furlong"]
        yard_m = DISTANCE_CONVERSION_CONSTANTS["yard"]

        result = normalize_distance("1m 2f")
        self.assertEqual(result.meters, mile_m + 2 * furlong_m)

        result = normalize_distance("2m 5f 191y")
        self.assertEqual(result.meters, 2 * mile_m + 5 * furlong_m + 191 * yard_m)

    def test_uk_surface_types(self):
        """UK turf, AW -> correct surface."""
        self.assertEqual(normalize_surface_race_type_layout_going("turf").surface, NormalizedSurface.TURF)
        self.assertEqual(normalize_surface_race_type_layout_going("AW").surface, NormalizedSurface.SYNTHETIC)

    def test_uk_jumps_race_types(self):
        """UK hurdle, steeplechase -> race_type, NOT flat."""
        hurdle = normalize_surface_race_type_layout_going("hurdle")
        self.assertEqual(hurdle.race_type, NormalizedRaceType.HURDLE)

        chase = normalize_surface_race_type_layout_going("steeplechase")
        self.assertEqual(chase.race_type, NormalizedRaceType.STEEPLECHASE)

    def test_uk_failure_statuses(self):
        """UK F/PU/UR/BD -> fine-grained statuses."""
        self.assertEqual(normalize_finish_position("F", source_kind="sporting_life").status,
                         NormalizedRaceResultStatus.FELL)
        self.assertEqual(normalize_finish_position("PU", source_kind="sporting_life").status,
                         NormalizedRaceResultStatus.PULLED_UP)
        self.assertEqual(normalize_finish_position("UR", source_kind="sporting_life").status,
                         NormalizedRaceResultStatus.UNSEATED_RIDER)
        self.assertEqual(normalize_finish_position("BD", source_kind="sporting_life").status,
                         NormalizedRaceResultStatus.BROUGHT_DOWN)

    def test_uk_grade_group_listed_and_class_1(self):
        """Group 1/2/3, Listed -> standard; Class 1 -> NOT G1."""
        self.assertEqual(normalize_grade("Group 1", source_language="en").grade, "G1")
        self.assertEqual(normalize_grade("Group 2", source_language="en").grade, "G2")
        self.assertEqual(normalize_grade("Group 3", source_language="en").grade, "G3")
        self.assertEqual(normalize_grade("Listed", source_language="en").grade, "L")
        class_1 = normalize_grade("Class 1", source_language="en", source_region="gb")
        self.assertNotEqual(class_1.grade, "G1")


# ====== 10. 法国 ====================================================
# test_cases.md section 3, France fixture

class FranceFixtureTests(TestCase):
    """Section 3 -- France (France Galop)."""

    def test_french_metric_distance(self):
        """French distances are metric."""
        result = normalize_distance("1600m")
        self.assertEqual(result.meters, 1600)
        self.assertEqual(result.precision, DistancePrecision.OFFICIAL_METRIC)

        result = normalize_distance("2100")
        self.assertEqual(result.meters, 2100)

    def test_french_groupe_notation(self):
        """Groupe I/II/III -> G1/G2/G3."""
        self.assertEqual(normalize_grade("Groupe I", source_language="fr").grade, "G1")
        self.assertEqual(normalize_grade("Groupe II", source_language="fr").grade, "G2")
        self.assertEqual(normalize_grade("Groupe III", source_language="fr").grade, "G3")

    def test_french_unresolved_statuses(self):
        """tbé, t.j, arr -> unresolved, not guessed."""
        for raw in ("tbé", "t.j", "arr"):
            with self.subTest(raw=raw):
                result = normalize_finish_position(raw, source_kind="france_galop")
                self.assertEqual(result.status, NormalizedRaceResultStatus.UNKNOWN)

    def test_french_category_class_not_groupe(self):
        """Category/Class -> NOT Groupe."""
        for raw in ("Category 1", "Classe 2"):
            with self.subTest(raw=raw):
                result = normalize_grade(raw, source_language="fr")
                self.assertNotEqual(result.grade, "G1")

    def test_going_separate_from_surface(self):
        """Going text retains, surface set separately."""
        result = normalize_surface_race_type_layout_going("turf", going_text="bon")
        self.assertEqual(result.surface, NormalizedSurface.TURF)
        self.assertEqual(result.going_text, "bon")


# ====== 11. 美国 ====================================================
# test_cases.md section 3, US fixture

class USFixtureTests(TestCase):
    """Section 3 -- US (HRN / BloodHorse / TDN)."""

    def test_us_fractional_distance(self):
        """'1 1/16M' -> ~1710m, '8.5f' -> exact."""
        mile_m = DISTANCE_CONVERSION_CONSTANTS["mile"]
        furlong_m = DISTANCE_CONVERSION_CONSTANTS["furlong"]

        result = normalize_distance("1 1/16M")
        # 1 1/16 mile = 1.0625 miles
        self.assertEqual(result.meters, 1.0625 * mile_m)
        self.assertEqual(result.precision, DistancePrecision.EXACT_CONVERSION)

        result = normalize_distance("8.5f")
        self.assertAlmostEqual(result.meters, 8.5 * furlong_m)

    def test_us_combined_distance_surface(self):
        """'8.5f dirt' -> surface extracted correctly."""
        result = normalize_distance("8.5f")
        self.assertEqual(result.source_unit, "f")

    def test_us_grade_notation(self):
        """Grade 1/2/3 -> standard with US context."""
        self.assertEqual(normalize_grade("Grade 1", source_language="en").grade, "G1")
        self.assertEqual(normalize_grade("Grade 2", source_language="en").grade, "G2")
        self.assertEqual(normalize_grade("Grade 3", source_language="en").grade, "G3")

    def test_us_statuses_scratched_dsq_dnf(self):
        """SCR -> scratched; DQ -> DQ; DNF -> did_not_finish."""
        self.assertEqual(normalize_finish_position("SCR", source_kind="hrn").status,
                         NormalizedRaceResultStatus.SCRATCHED)
        self.assertEqual(normalize_finish_position("DSQ", source_kind="hrn").status,
                         NormalizedRaceResultStatus.DISQUALIFIED)
        self.assertEqual(normalize_finish_position("DNF", source_kind="hrn").status,
                         NormalizedRaceResultStatus.DID_NOT_FINISH)

    def test_us_track_needs_official_id(self):
        """Track identity -> relies on official source ID / exact alias, not ambiguous name."""
        result = normalize_context(
            raw_region="",
            official_venue_id="saratoga",
        )
        # Needs official venue mapping to recover region
        self.assertEqual(result.reason.reason_code, "context_from_official_venue_id")

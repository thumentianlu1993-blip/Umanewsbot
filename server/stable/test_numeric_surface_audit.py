"""N04 数字表面证据合同；表面相同不代表事实正确。"""

import unittest

from stable.services.numeric_surface_audit import audit_numeric_surfaces


class NumericSurfaceAuditTests(unittest.TestCase):
    def _audit(self, source, translated, status, source_count, translated_count):
        result = audit_numeric_surfaces(source, translated)
        self.assertEqual(result["comparison_scope"], "raw_numeric_lexemes")
        self.assertEqual(result["fact_verdict"], "not_assessed")
        self.assertNotIn("passed", result)
        self.assertEqual(result["status"], status)
        self.assertEqual(result["source_token_count"], source_count)
        self.assertEqual(result["translated_token_count"], translated_count)
        return result

    def test_single_digit_change_reports_both_sides_without_pairing(self):
        result = self._audit("Ran 2 times.", "跑了3次。", "surface_difference", 1, 1)
        self.assertEqual(result["differences"], [
            {"token": "2", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[4, 5]], "translated_spans": []},
            {"token": "3", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[2, 3]]},
        ])

    def test_missing_single_digit_is_reported(self):
        result = self._audit("1 2", "1", "surface_difference", 2, 1)
        self.assertEqual(result["differences"], [
            {"token": "2", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[2, 3]], "translated_spans": []},
        ])

    def test_translation_only_number_is_reported(self):
        result = self._audit("12", "12 99", "surface_difference", 1, 2)
        self.assertEqual(result["differences"], [
            {"token": "99", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[3, 5]]},
        ])

    def test_source_repetition_keeps_every_span_without_assigning_the_loss(self):
        result = self._audit("2000m and 2000m", "2000米", "surface_difference", 2, 1)
        self.assertEqual(result["differences"], [
            {"token": "2000", "code": "source_excess", "source_count": 2,
             "translated_count": 1, "source_spans": [[0, 4], [10, 14]],
             "translated_spans": [[0, 4]]},
        ])

    def test_translation_repetition_keeps_every_span(self):
        result = self._audit("2", "2 2", "surface_difference", 1, 2)
        self.assertEqual(result["differences"], [
            {"token": "2", "code": "translation_excess", "source_count": 1,
             "translated_count": 2, "source_spans": [[0, 1]],
             "translated_spans": [[0, 1], [2, 3]]},
        ])

    def test_changes_after_twenty_four_tokens_are_not_truncated(self):
        result = self._audit("7 " * 25 + "9", "7 " * 25 + "8",
                             "surface_difference", 26, 26)
        self.assertEqual(result["differences"], [
            {"token": "9", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[50, 51]], "translated_spans": []},
            {"token": "8", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[50, 51]]},
        ])

    def test_difference_after_twenty_four_distinct_two_digit_tokens_is_retained(self):
        source = "10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34"
        translated = "10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 99"
        result = self._audit(source, translated, "surface_difference", 25, 25)
        self.assertEqual(result["differences"], [
            {"token": "34", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[72, 74]], "translated_spans": []},
            {"token": "99", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[72, 74]]},
        ])

    def test_spans_use_original_unicode_character_offsets(self):
        result = self._audit("马🐎 12", "马🐎 13", "surface_difference", 1, 1)
        self.assertEqual(result["differences"], [
            {"token": "12", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[3, 5]], "translated_spans": []},
            {"token": "13", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[3, 5]]},
        ])

    def test_decimal_lexemes_are_whole_and_not_value_normalized(self):
        result = self._audit("12.50", "12.5", "surface_difference", 1, 1)
        self.assertEqual(result["differences"], [
            {"token": "12.50", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[0, 5]], "translated_spans": []},
            {"token": "12.5", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[0, 4]]},
        ])

    def test_one_token_is_not_preserved_by_a_larger_number(self):
        result = self._audit("12", "112", "surface_difference", 1, 1)
        self.assertEqual(result["differences"], [
            {"token": "12", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[0, 2]], "translated_spans": []},
            {"token": "112", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[0, 3]]},
        ])

    def test_difference_order_follows_source_then_translation_only_tokens(self):
        result = self._audit("8 3 8", "7 3 9", "surface_difference", 3, 3)
        self.assertEqual(result["differences"], [
            {"token": "8", "code": "source_excess", "source_count": 2,
             "translated_count": 0, "source_spans": [[0, 1], [4, 5]], "translated_spans": []},
            {"token": "7", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[0, 1]]},
            {"token": "9", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[4, 5]]},
        ])

    def test_identical_numbers_are_surface_match_only(self):
        result = self._audit("12 2 12.5", "12 2 12.5", "surface_match", 3, 3)
        self.assertEqual(result["differences"], [])

    def test_number_reordering_does_not_infer_fact_alignment(self):
        result = self._audit("2 12 2", "12 2 2", "surface_match", 3, 3)
        self.assertEqual(result["differences"], [])

    def test_empty_fields_are_not_a_fact_check_pass(self):
        result = self._audit("", "", "no_numeric_lexemes", 0, 0)
        self.assertEqual(result["differences"], [])

    def test_text_without_numeric_lexemes_is_not_a_fact_check_pass(self):
        result = self._audit("Aurora won.", "Aurora落败。", "no_numeric_lexemes", 0, 0)
        self.assertEqual(result["differences"], [])

    def test_empty_translation_retains_source_evidence(self):
        result = self._audit("2", "", "surface_difference", 1, 0)
        self.assertEqual(result["differences"], [
            {"token": "2", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[0, 1]], "translated_spans": []},
        ])

    def test_empty_source_retains_translation_evidence(self):
        result = self._audit("", "2", "surface_difference", 0, 1)
        self.assertEqual(result["differences"], [
            {"token": "2", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[0, 1]]},
        ])

    def test_date_and_rank_formatting_match_does_not_verify_their_facts(self):
        result = self._audit("2026-10-17, 2nd", "2026年10月17日，第2名",
                             "surface_match", 4, 4)
        self.assertEqual(result["differences"], [])

    def test_unit_conversion_difference_is_surface_evidence_only(self):
        result = self._audit("2000m", "2公里", "surface_difference", 1, 1)
        self.assertEqual(result["differences"], [
            {"token": "2000", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[0, 4]], "translated_spans": []},
            {"token": "2", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[0, 1]]},
        ])

    def test_grouped_number_is_not_silently_canonicalized(self):
        result = self._audit("1,000", "1000", "surface_difference", 2, 1)
        self.assertEqual(result["differences"], [
            {"token": "1", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[0, 1]], "translated_spans": []},
            {"token": "000", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[2, 5]], "translated_spans": []},
            {"token": "1000", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[0, 4]]},
        ])

    def test_fullwidth_digits_keep_their_original_surface(self):
        result = self._audit("１２", "12", "surface_difference", 1, 1)
        self.assertEqual(result["differences"], [
            {"token": "１２", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[0, 2]], "translated_spans": []},
            {"token": "12", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[0, 2]]},
        ])

    def test_name_number_swap_remains_semantically_unassessed(self):
        result = self._audit("Aurora 2, Vega 3", "Aurora 3，Vega 2",
                             "surface_match", 2, 2)
        self.assertEqual(result["differences"], [])

    def test_negation_plan_unit_and_attribution_changes_are_not_inferred(self):
        pairs = [
            ("Aurora did not win 2 races.", "Aurora赢了2场。"),
            ("Aurora plans to run 2 races.", "Aurora已跑了2场。"),
            ("Distance 2000m", "距离2000英里"),
            ('A said "2 races".', 'B说“2场”。'),
        ]
        for source, translated in pairs:
            with self.subTest(source=source):
                result = self._audit(source, translated, "surface_match", 1, 1)
                self.assertEqual(result["differences"], [])

    def test_separate_article_calls_do_not_retain_previous_evidence(self):
        first = self._audit("2", "3", "surface_difference", 1, 1)
        self.assertEqual([d["token"] for d in first["differences"]], ["2", "3"])
        second = self._audit("9", "9", "surface_match", 1, 1)
        self.assertEqual(second["differences"], [])
        self.assertEqual(first["source_token_count"], 1)
        self.assertEqual([d["token"] for d in first["differences"]], ["2", "3"])

    def test_invalid_inputs_raise_without_polluting_the_next_call(self):
        for source, translated in [(None, "2"), ("2", None), (2, "2"), ("2", []),
                                   (b"2", "2"), ("2", False)]:
            with self.subTest(source=source, translated=translated):
                with self.assertRaises(TypeError):
                    audit_numeric_surfaces(source, translated)
        result = self._audit("2", "2", "surface_match", 1, 1)
        self.assertEqual(result["differences"], [])

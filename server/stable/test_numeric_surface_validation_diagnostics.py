"""N04 当前校验快照诊断合同；本模块不要求新 private helper 已可导入。"""

import hashlib
import json
import platform
import time
import tracemalloc
from datetime import datetime, timedelta, timezone

from django.db import connection
from django.test import TestCase, override_settings

from stable.models import (
    ArticleTranslationStatus,
    AutomationLog,
    AutomationStatus,
    NewsArticle,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    WorkflowStatus,
)
from stable.services import validation
from stable.services.numeric_surface_audit import audit_numeric_surfaces


BODY = "this report describes routine preparation and the current programme in a calm factual account."
STAMP = datetime(2026, 10, 17, 12, 0, 0, 123456, tzinfo=timezone.utc)
STAMP_JSON = "2026-10-17T12:00:00.123456Z"
ZERO_CHANGE = [
    {"token": "2", "code": "source_excess", "source_count": 1,
     "translated_count": 0, "source_spans": [[0, 1]], "translated_spans": []},
    {"token": "3", "code": "translation_excess", "source_count": 0,
     "translated_count": 1, "source_spans": [], "translated_spans": [[0, 1]]},
]
TITLE_CHANGE = [
    {"token": "2", "code": "source_excess", "source_count": 1,
     "translated_count": 0, "source_spans": [[7, 8]], "translated_spans": []},
    {"token": "3", "code": "translation_excess", "source_count": 0,
     "translated_count": 1, "source_spans": [], "translated_spans": [[7, 8]]},
]


def utf8_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@override_settings(
    AUTO_DUPLICATE_HIGH_THRESHOLD=0,
    AUTO_DUPLICATE_REVIEW_THRESHOLD=0,
    AUTO_REWRITE_ENABLED=False,
    TERM_CONSISTENCY_ENABLED=False,
    ENGLISH_TERM_CONTEXT_MODE="off",
)
class NumericSurfaceValidationDiagnosticsTests(TestCase):
    def setUp(self):
        self.article = NewsArticle.objects.create(
            source_site=SourceSite.TDN,
            source_mode=SourceMode.LATEST,
            source_article_id="numeric-validation-diagnostic",
            source_language=SourceLanguage.JAPANESE,
            racing_region=RacingRegion.JAPAN,
            title_ja="report 2",
            body_ja_raw="2 " + BODY,
            body_ja_normalized="2 " + BODY,
            translated_title_zh="report 3",
            title_zh="report 3",
            translated_body_zh="3 " + BODY,
            body_zh="3 " + BODY,
            translated_summary_zh="routine report",
            summary_zh="routine report",
            published_at=STAMP,
            published_at_verified=True,
            source_url="https://example.invalid/numeric-validation",
            workflow_status=WorkflowStatus.PENDING_EDIT,
            translation_status=ArticleTranslationStatus.TRANSLATED,
            automation_status=AutomationStatus.PENDING,
            score_total=100,
        )
        NewsArticle.objects.filter(id=self.article.id).update(updated_at=STAMP)
        self.article.refresh_from_db()

    def _validate(self, article=None):
        return validation.validate_rewrite(
            self.article if article is None else article, term_entries=[]
        )

    def _public_diagnostic(self, article=None):
        outcome = self._validate(article)
        self.assertIn("numeric_surface_audit", outcome.details)
        return outcome, outcome.details["numeric_surface_audit"]

    def _build(self, *, article=None, source_title="report 2", source_body=None,
               translated_title="report 3", translated_body=None,
               content_source="base_translation", existing_details=None,
               source_fields=None, target_selectors=None):
        # 缺 helper 在该方法内如实报接口 ERROR；不阻止 public caller 测试收集。
        builder = getattr(validation, "_numeric_surface_diagnostics")
        return builder(
            article=self.article if article is None else article,
            content_source=content_source,
            legacy_title=source_title,
            legacy_body="2 " + BODY if source_body is None else source_body,
            publish_title=translated_title,
            publish_body="3 " + BODY if translated_body is None else translated_body,
            existing_details={} if existing_details is None else existing_details,
            source_fields={"title": "title_ja", "body": "body_ja_normalized"}
                          if source_fields is None else source_fields,
            target_selectors={"title": "_publish_title", "body": "_publish_body"}
                             if target_selectors is None else target_selectors,
        )

    def _bodies(self, source, translated, *, article=None, existing_details=None):
        return self._build(
            article=article, source_title="", source_body=source,
            translated_title="", translated_body=translated,
            existing_details=existing_details,
        )

    def _assert_available(self, diagnostic):
        self.assertEqual(diagnostic["status"], "available")
        self.assertEqual(diagnostic["comparison_scope"], "raw_numeric_lexemes")
        self.assertEqual(diagnostic["fact_verdict"], "not_assessed")
        self.assertEqual(diagnostic["binding_scope"], "current_validation_snapshot")
        self.assertEqual(diagnostic["coordinate_space"], "diagnostic_input_string")
        self.assertNotIn("passed", diagnostic)
        self.assertEqual(set(diagnostic["fields"]), {"title", "body"})
        self.assertEqual(diagnostic["fields"]["title"]["source_field"], "title_ja")
        self.assertIn(diagnostic["fields"]["body"]["source_field"],
                      {"body_ja_normalized", "body_ja_raw"})
        self.assertEqual(diagnostic["fields"]["title"]["target_selector"], "_publish_title")
        self.assertEqual(diagnostic["fields"]["body"]["target_selector"], "_publish_body")

    def _assert_unavailable(self, diagnostic, reason, resource_limit=None):
        self.assertEqual(diagnostic["status"], "diagnostic_unavailable")
        self.assertEqual(diagnostic["reason"], reason)
        self.assertEqual(diagnostic["comparison_scope"], "raw_numeric_lexemes")
        self.assertEqual(diagnostic["fact_verdict"], "not_assessed")
        self.assertNotIn("passed", diagnostic)
        self.assertNotIn("fields", diagnostic)
        self.assertNotIn("snapshot_sha256", diagnostic)
        if resource_limit is not None:
            self.assertEqual(diagnostic["resource_limit"], resource_limit)
        self.assertLessEqual(len(json.dumps(diagnostic).encode("utf-8")), 512)

    def _assert_inputs(self, field, source, translated, raw_source=None, raw_translated=None):
        self.assertEqual(field["source_text"], source)
        self.assertEqual(field["translated_text"], translated)
        self.assertEqual(field["source_sha256"], utf8_sha(source))
        self.assertEqual(field["translated_sha256"], utf8_sha(translated))
        self.assertEqual(field["raw_source_sha256"], utf8_sha(source if raw_source is None else raw_source))
        self.assertEqual(field["raw_translated_sha256"], utf8_sha(translated if raw_translated is None else raw_translated))

    def _assert_snapshot_hash(self, diagnostic):
        # 独立使用公开标准 JSON/SHA 规则验证记录完整性，不调用未来 builder 的工具。
        snapshot = {k: v for k, v in diagnostic.items() if k != "snapshot_sha256"}
        encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.assertEqual(diagnostic["snapshot_sha256"], hashlib.sha256(encoded).hexdigest())
        self.assertEqual(json.loads(json.dumps(diagnostic, allow_nan=False)), diagnostic)

    def _assert_original_normal_gate(self, outcome):
        self.assertTrue(outcome.passed)
        self.assertEqual(outcome.issues, [])
        self.assertEqual(outcome.reason, "门禁校验通过")
        self.assertEqual(validation.warning_signature(outcome.issues), "")

    def test_public_caller_adds_diagnostic_after_real_core_and_gate_preconditions(self):
        core = audit_numeric_surfaces("2", "3")
        self.assertEqual(core["differences"], ZERO_CHANGE)
        self.assertEqual(core["fact_verdict"], "not_assessed")
        outcome = self._validate()
        self._assert_original_normal_gate(outcome)
        # 基线应在真实既有 caller 返回后在这里 AssertionError，不是 import/helper ERROR。
        self.assertIn("numeric_surface_audit", outcome.details)
        diagnostic = outcome.details["numeric_surface_audit"]
        self._assert_available(diagnostic)
        self._assert_inputs(diagnostic["fields"]["title"], "report 2", "report 3")
        self._assert_inputs(diagnostic["fields"]["body"], "2 " + BODY, "3 " + BODY)
        self.assertEqual(diagnostic["fields"]["title"]["audit"]["differences"], TITLE_CHANGE)
        self.assertEqual(diagnostic["fields"]["body"]["audit"]["differences"], ZERO_CHANGE)
        self._assert_snapshot_hash(diagnostic)

    def test_public_current_article_and_loaded_timestamp_are_bound(self):
        outcome, diagnostic = self._public_diagnostic()
        self._assert_original_normal_gate(outcome)
        self.assertEqual(diagnostic["article_id"], self.article.id)
        self.assertEqual(diagnostic["article_updated_at"], STAMP_JSON)
        self.assertEqual(diagnostic["updated_at_observation"], "loaded")
        self.assertEqual(diagnostic["content_source"], "base_translation")
        self.assertEqual(diagnostic["transform"], "terms.clean_visible_source_text")
        self._assert_snapshot_hash(diagnostic)

    def test_public_title_differences_cannot_be_hidden_by_body_numbers(self):
        self.article.title_ja = "report 2"
        self.article.title_zh = "report 3"
        self.article.body_ja_normalized = "2 3 " + BODY
        self.article.body_zh = "2 3 " + BODY
        _, diagnostic = self._public_diagnostic()
        self.assertEqual(diagnostic["fields"]["title"]["audit"]["differences"], TITLE_CHANGE)
        self.assertEqual(diagnostic["fields"]["body"]["audit"]["differences"], [])

    def test_public_summary_numbers_are_not_compared_to_complete_body(self):
        self.article.title_zh = "report 2"
        self.article.body_zh = "2 " + BODY
        self.article.summary_zh = "summary 99"
        outcome, diagnostic = self._public_diagnostic()
        self._assert_original_normal_gate(outcome)
        self.assertEqual(diagnostic["fields"]["title"]["audit"]["differences"], [])
        self.assertEqual(diagnostic["fields"]["body"]["audit"]["differences"], [])
        self.assertNotIn("summary", diagnostic["fields"])
        self.assertEqual(diagnostic["fields"]["body"]["translated_text"], "2 " + BODY)

    def test_public_normalized_source_wins_over_raw_source(self):
        self.article.body_ja_normalized = "4 " + BODY
        self.article.body_ja_raw = "5 " + BODY
        _, diagnostic = self._public_diagnostic()
        field = diagnostic["fields"]["body"]
        self._assert_inputs(field, "4 " + BODY, "3 " + BODY)
        self.assertEqual(field["source_field"], "body_ja_normalized")
        self.assertEqual(field["target_selector"], "_publish_body")
        self.assertEqual([d["token"] for d in field["audit"]["differences"]], ["4", "3"])

    def test_public_empty_normalized_source_uses_complete_raw_source(self):
        self.article.body_ja_normalized = ""
        _, diagnostic = self._public_diagnostic()
        self._assert_inputs(diagnostic["fields"]["body"], "2 " + BODY, "3 " + BODY)
        self.assertEqual(diagnostic["fields"]["body"]["source_field"], "body_ja_raw")
        self.assertEqual(diagnostic["fields"]["title"]["source_field"], "title_ja")
        self.assertEqual(diagnostic["fields"]["title"]["target_selector"], "_publish_title")
        self.assertEqual(diagnostic["fields"]["body"]["target_selector"], "_publish_body")

    def test_same_text_source_selection_changes_hash_and_survives_real_log_roundtrip(self):
        normalized_outcome, normalized = self._public_diagnostic()
        self._assert_original_normal_gate(normalized_outcome)
        # QuerySet.update不写auto_now；两次观察的id/time/完整文本/hash保持相同。
        NewsArticle.objects.filter(id=self.article.id).update(body_ja_normalized="")
        self.article.refresh_from_db()
        raw_outcome, raw = self._public_diagnostic()
        self._assert_original_normal_gate(raw_outcome)
        self.assertEqual(normalized["fields"]["body"]["source_field"], "body_ja_normalized")
        self.assertEqual(raw["fields"]["body"]["source_field"], "body_ja_raw")
        for key in ("source_text", "translated_text", "source_sha256", "translated_sha256",
                    "raw_source_sha256", "raw_translated_sha256", "audit"):
            self.assertEqual(normalized["fields"]["body"][key], raw["fields"]["body"][key])
        self.assertEqual(normalized["article_updated_at"], STAMP_JSON)
        self.assertEqual(raw["article_updated_at"], STAMP_JSON)
        self._assert_snapshot_hash(normalized)
        self._assert_snapshot_hash(raw)
        self.assertNotEqual(normalized["snapshot_sha256"], raw["snapshot_sha256"])
        normalized_body = json.loads(json.dumps(normalized))
        raw_body = json.loads(json.dumps(raw))
        normalized_body.pop("snapshot_sha256")
        raw_body.pop("snapshot_sha256")
        normalized_body["fields"]["body"]["source_field"] = "body_ja_raw"
        self.assertEqual(normalized_body, raw_body)
        validation.apply_validation_outcome(self.article, normalized_outcome)
        first_log = AutomationLog.objects.filter(article=self.article).latest("id")
        self.assertEqual(first_log.payload["numeric_surface_audit"], normalized)
        self.assertEqual(first_log.payload["numeric_surface_audit"]["fields"]["body"]["source_field"],
                         "body_ja_normalized")
        validation.apply_validation_outcome(self.article, raw_outcome)
        second_log = AutomationLog.objects.filter(article=self.article).latest("id")
        self.assertNotEqual(first_log.id, second_log.id)
        self.assertEqual(second_log.payload["numeric_surface_audit"], raw)
        self.assertEqual(second_log.payload["numeric_surface_audit"]["fields"]["body"]["source_field"],
                         "body_ja_raw")

    def test_public_current_edit_fields_win_over_base_translation_fields(self):
        self.article.title_zh = "report 4"
        self.article.body_zh = "4 " + BODY
        self.article.translated_title_zh = "report 5"
        self.article.translated_body_zh = "5 " + BODY
        _, diagnostic = self._public_diagnostic()
        self.assertEqual(diagnostic["fields"]["title"]["translated_text"], "report 4")
        self.assertEqual(diagnostic["fields"]["body"]["translated_text"], "4 " + BODY)
        self.assertEqual(diagnostic["fields"]["title"]["target_selector"], "_publish_title")
        self.assertEqual(diagnostic["fields"]["body"]["target_selector"], "_publish_body")

    def test_public_empty_edit_fields_use_translation_fallback(self):
        self.article.title_zh = ""
        self.article.body_zh = ""
        _, diagnostic = self._public_diagnostic()
        self.assertEqual(diagnostic["fields"]["title"]["translated_text"], "report 3")
        self.assertEqual(diagnostic["fields"]["body"]["translated_text"], "3 " + BODY)
        self.assertEqual(diagnostic["fields"]["title"]["target_selector"], "_publish_title")
        self.assertEqual(diagnostic["fields"]["body"]["target_selector"], "_publish_body")

    @override_settings(AUTO_REWRITE_ENABLED=True, AUTO_PUBLISH_CONTENT_SOURCE="rewrite")
    def test_public_rewrite_selection_is_diagnosed_without_changing_gate(self):
        self.article.rewrite_title_zh = "report 6"
        self.article.rewrite_body_zh = "6 " + BODY
        self.article.rewrite_summary_zh = "summary 99"
        self.article.rewrite_confidence = 100
        outcome, diagnostic = self._public_diagnostic()
        self._assert_original_normal_gate(outcome)
        self.assertEqual(diagnostic["content_source"], "rewrite")
        self.assertEqual(diagnostic["fields"]["title"]["translated_text"], "report 6")
        self.assertEqual(diagnostic["fields"]["body"]["translated_text"], "6 " + BODY)
        self.assertEqual(diagnostic["fields"]["title"]["target_selector"], "_publish_title")
        self.assertEqual(diagnostic["fields"]["body"]["target_selector"], "_publish_body")

    def test_public_all_languages_clean_both_inputs_with_separate_original_hashes(self):
        source = "<p>2 " + BODY + "</p><aside>99</aside>"
        translated = "<p>3 " + BODY + "</p><script>88</script>"
        for language in [SourceLanguage.JAPANESE, SourceLanguage.ENGLISH]:
            with self.subTest(language=language):
                self.article.source_language = language
                self.article.body_ja_normalized = source
                self.article.body_zh = translated
                _, diagnostic = self._public_diagnostic()
                field = diagnostic["fields"]["body"]
                self._assert_inputs(field, "2 " + BODY, "3 " + BODY, source, translated)
                self.assertEqual(field["audit"]["differences"], ZERO_CHANGE)
                self.assertEqual(self.article.body_ja_normalized, source)
                self.assertEqual(self.article.body_zh, translated)

    def test_public_old_blocker_reason_route_and_signature_are_unchanged(self):
        self.article.source_url = ""
        outcome, diagnostic = self._public_diagnostic()
        self.assertFalse(outcome.passed)
        self.assertEqual(outcome.reason, "缺少原文链接")
        self.assertEqual(outcome.issues, [{
            "code": "missing_source_url", "severity": "blocker", "message": "缺少原文链接",
            "route": "manual_review", "payload": {},
        }])
        self.assertEqual(validation.warning_signature(outcome.issues), "")
        self._assert_available(diagnostic)

    def test_public_resource_refusal_does_not_add_an_issue_or_change_passed(self):
        self.article.body_ja_normalized = "x" * 16385
        outcome, diagnostic = self._public_diagnostic()
        self._assert_original_normal_gate(outcome)
        self._assert_unavailable(diagnostic, "resource_refusal", "raw_field_codepoints")

    def test_public_unmatched_facts_are_still_not_assessed(self):
        self.article.title_zh = "report 2"
        self.article.body_ja_normalized = "2 planned events. " + BODY
        self.article.body_zh = "2 completed events. " + BODY
        outcome, diagnostic = self._public_diagnostic()
        self._assert_original_normal_gate(outcome)
        audit = diagnostic["fields"]["body"]["audit"]
        self.assertEqual(audit["status"], "surface_match")
        self.assertEqual(audit["fact_verdict"], "not_assessed")

    def test_loaded_builder_has_no_queries_and_canonical_timestamp(self):
        with self.assertNumQueries(0):
            diagnostic = self._build()
        self._assert_available(diagnostic)
        self.assertEqual(diagnostic["article_updated_at"], STAMP_JSON)
        self.assertEqual(diagnostic["updated_at_observation"], "loaded")
        self._assert_snapshot_hash(diagnostic)

    def test_deferred_timestamp_builder_has_no_descriptor_fetch(self):
        deferred = NewsArticle.objects.defer("updated_at").get(id=self.article.id)
        self.assertNotIn("updated_at", deferred.__dict__)
        with self.assertNumQueries(0):
            diagnostic = self._build(article=deferred)
        self.assertNotIn("updated_at", deferred.__dict__)
        self._assert_available(diagnostic)
        self.assertIsNone(diagnostic["article_updated_at"])
        self.assertEqual(diagnostic["updated_at_observation"], "field_not_loaded")
        self._assert_snapshot_hash(diagnostic)

    def test_public_deferred_observation_does_not_change_gate_result(self):
        deferred = NewsArticle.objects.defer("updated_at").get(id=self.article.id)
        outcome, diagnostic = self._public_diagnostic(deferred)
        self._assert_original_normal_gate(outcome)
        self.assertNotIn("updated_at", deferred.__dict__)
        self.assertIsNone(diagnostic["article_updated_at"])
        self.assertEqual(diagnostic["updated_at_observation"], "field_not_loaded")

    def test_builder_uses_passed_strings_when_all_other_model_fields_are_deferred(self):
        minimal = NewsArticle.objects.only("id").get(id=self.article.id)
        loaded_keys = set(minimal.__dict__)
        with self.assertNumQueries(0):
            diagnostic = self._build(
                article=minimal, source_fields={"title": "title_ja", "body": "body_ja_raw"},
                target_selectors={"title": "_publish_title", "body": "_publish_body"},
            )
        self.assertEqual(set(minimal.__dict__), loaded_keys)
        self._assert_available(diagnostic)
        self.assertIsNone(diagnostic["article_updated_at"])
        self.assertEqual(diagnostic["updated_at_observation"], "field_not_loaded")
        self.assertEqual(diagnostic["fields"]["body"]["source_field"], "body_ja_raw")
        self._assert_inputs(diagnostic["fields"]["body"], "2 " + BODY, "3 " + BODY)

    def test_loaded_optional_timestamp_states_do_not_fabricate_a_time(self):
        values = [
            (None, "loaded_null"),
            (datetime(2026, 10, 17, 12, 0), "naive_timestamp"),
            ("not a datetime", "unsupported_timestamp_value"),
        ]
        for value, reason in values:
            with self.subTest(reason=reason):
                self.article.__dict__["updated_at"] = value
                with self.assertNumQueries(0):
                    diagnostic = self._build()
                self.assertIsNone(diagnostic["article_updated_at"])
                self.assertEqual(diagnostic["updated_at_observation"], reason)
                self._assert_snapshot_hash(diagnostic)

    def test_aware_timestamp_is_normalized_to_a_deterministic_utc_string(self):
        self.article.__dict__["updated_at"] = datetime(
            2026, 10, 17, 17, 30, 0, 123456,
            tzinfo=timezone(timedelta(hours=5, minutes=30)),
        )
        with self.assertNumQueries(0):
            first = self._build()
            second = self._build()
        self.assertEqual(first["article_updated_at"], STAMP_JSON)
        self.assertEqual(first["snapshot_sha256"], second["snapshot_sha256"])
        self._assert_snapshot_hash(first)

    def test_missing_loaded_identity_returns_unavailable_without_queries(self):
        unbound = NewsArticle()
        with self.assertNumQueries(0):
            diagnostic = self._build(article=unbound)
        self._assert_unavailable(diagnostic, "missing_article_identity")

    def test_distinct_twenty_fifth_tokens_and_full_spans_are_retained(self):
        source = "10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34"
        translated = "10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 99"
        diagnostic = self._bodies(source, translated)
        self._assert_available(diagnostic)
        field = diagnostic["fields"]["body"]
        self._assert_inputs(field, source, translated)
        self.assertEqual(field["audit"]["source_token_count"], 25)
        self.assertEqual(field["audit"]["translated_token_count"], 25)
        self.assertEqual(field["audit"]["differences"], [
            {"token": "34", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[72, 74]], "translated_spans": []},
            {"token": "99", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[72, 74]]},
        ])

    def test_complete_empty_inputs_remain_not_assessed(self):
        diagnostic = self._bodies("", "")
        self._assert_available(diagnostic)
        for field in diagnostic["fields"].values():
            self._assert_inputs(field, "", "")
            self.assertEqual(field["audit"]["status"], "no_numeric_lexemes")
            self.assertEqual(field["audit"]["fact_verdict"], "not_assessed")

    def test_repeated_source_keeps_all_positions_without_pairing_a_replacement(self):
        diagnostic = self._bodies("2 2", "3")
        self._assert_available(diagnostic)
        self.assertEqual(diagnostic["fields"]["body"]["audit"]["differences"], [
            {"token": "2", "code": "source_excess", "source_count": 2,
             "translated_count": 0, "source_spans": [[0, 1], [2, 3]], "translated_spans": []},
            {"token": "3", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[0, 1]]},
        ])

    def test_cleaned_snapshot_does_not_normalize_fullwidth_numeric_surfaces(self):
        diagnostic = self._bodies("１２", "12")
        self._assert_available(diagnostic)
        self._assert_inputs(diagnostic["fields"]["body"], "１２", "12")
        self.assertEqual(diagnostic["fields"]["body"]["audit"]["differences"], [
            {"token": "１２", "code": "source_excess", "source_count": 1,
             "translated_count": 0, "source_spans": [[0, 2]], "translated_spans": []},
            {"token": "12", "code": "translation_excess", "source_count": 0,
             "translated_count": 1, "source_spans": [], "translated_spans": [[0, 2]]},
        ])

    def test_two_sixteen_kib_fields_are_completely_admitted(self):
        source, translated = "a" * 16384, "b" * 16384
        diagnostic = self._bodies(source, translated)
        self._assert_available(diagnostic)
        self._assert_inputs(diagnostic["fields"]["body"], source, translated)
        self._assert_snapshot_hash(diagnostic)

    def test_aggregate_raw_budget_refuses_even_when_individual_fields_fit(self):
        diagnostic = self._build(
            source_title="x", source_body="a" * 16384,
            translated_title="", translated_body="b" * 16384,
        )
        self._assert_unavailable(diagnostic, "resource_refusal", "raw_total_codepoints")

    def test_utf8_field_budget_is_not_a_character_count_budget(self):
        diagnostic = self._bodies("中" * 6000, "")
        self._assert_unavailable(diagnostic, "resource_refusal", "raw_field_utf8_bytes")

    def test_utf8_aggregate_budget_is_checked_within_individual_limits(self):
        diagnostic = self._build(
            source_title="abc", source_body="中" * 5461,
            translated_title="", translated_body="中" * 5461,
        )
        self._assert_unavailable(diagnostic, "resource_refusal", "raw_total_utf8_bytes")

    def test_clean_unicode_snapshots_near_byte_limits_are_not_truncated(self):
        source, translated = "中" * 5461, "文" * 5461
        diagnostic = self._bodies(source, translated)
        self._assert_available(diagnostic)
        self._assert_inputs(diagnostic["fields"]["body"], source, translated)
        self._assert_snapshot_hash(diagnostic)

    def test_exactly_five_hundred_twelve_occurrences_are_completely_admitted(self):
        diagnostic = self._bodies("1 " * 256, "1 " * 256)
        self._assert_available(diagnostic)
        field = diagnostic["fields"]["body"]
        self._assert_inputs(field, "1 " * 255 + "1", "1 " * 255 + "1",
                            "1 " * 256, "1 " * 256)
        self.assertEqual(field["audit"]["source_token_count"], 256)
        self.assertEqual(field["audit"]["translated_token_count"], 256)
        self.assertEqual(field["audit"]["differences"], [])

    def test_five_hundred_thirteenth_raw_occurrence_refuses_the_whole_snapshot(self):
        diagnostic = self._bodies("1 " * 513, "")
        self._assert_unavailable(diagnostic, "resource_refusal", "raw_occurrences")

    def test_hidden_raw_occurrences_can_conservatively_refuse_before_cleaning(self):
        diagnostic = self._bodies("<script>" + "1 " * 513 + "</script>", "")
        self._assert_unavailable(diagnostic, "resource_refusal", "raw_occurrences")

    def test_old_payload_near_upper_limit_is_preserved_and_completely_admitted(self):
        existing = {"padding": "x" * 10800}
        diagnostic = self._bodies("2", "3", existing_details=existing)
        self._assert_available(diagnostic)
        self.assertEqual(existing, {"padding": "x" * 10800})
        self.assertLessEqual(len(json.dumps({**existing, "numeric_surface_audit": diagnostic}).encode()), 786432)

    def test_old_payload_over_upper_limit_is_not_truncated_or_replaced(self):
        existing = {"padding": "x" * 11000}
        diagnostic = self._bodies("2", "3", existing_details=existing)
        self._assert_unavailable(diagnostic, "resource_refusal", "existing_payload_json_upper_bytes")
        self.assertEqual(existing, {"padding": "x" * 11000})

    def test_old_payload_node_budget_has_accept_and_refusal_controls(self):
        accepted = self._bodies("2", "3", existing_details={"items": [True] * 4000})
        self._assert_available(accepted)
        refused = self._bodies("2", "3", existing_details={"items": [True] * 4097})
        self._assert_unavailable(refused, "resource_refusal", "existing_payload_scan_max_nodes")

    def test_old_payload_depth_budget_has_accept_and_refusal_controls(self):
        accepted_value = True
        for _ in range(14):
            accepted_value = [accepted_value]
        self._assert_available(self._bodies("2", "3", existing_details={"value": accepted_value}))
        refused_value = True
        for _ in range(17):
            refused_value = [refused_value]
        refused = self._bodies("2", "3", existing_details={"value": refused_value})
        self._assert_unavailable(refused, "resource_refusal", "existing_payload_scan_max_depth")

    def test_old_payload_cycle_and_non_json_values_do_not_enter_snapshot(self):
        cyclic = {}
        cyclic["self"] = cyclic
        cases = [
            (cyclic, "existing_payload_cycle"),
            ({"value": object()}, "existing_payload_type"),
            ({"value": float("nan")}, "existing_payload_type"),
            ({"value": 1 << 65}, "existing_payload_type"),
        ]
        for existing, limit in cases:
            with self.subTest(limit=limit):
                diagnostic = self._bodies("2", "3", existing_details=existing)
                self._assert_unavailable(diagnostic, "resource_refusal", limit)

    def test_invalid_utf8_is_unavailable_without_claiming_a_surface_result(self):
        diagnostic = self._bodies("\ud800", "")
        self._assert_unavailable(diagnostic, "invalid_input")

    def test_invalid_builder_input_does_not_pollute_a_later_valid_call(self):
        diagnostic = self._bodies([], "")
        self._assert_unavailable(diagnostic, "invalid_input")
        valid = self._bodies("2", "3")
        self._assert_available(valid)
        self.assertEqual(valid["fields"]["body"]["audit"]["differences"], ZERO_CHANGE)

    def test_real_apply_log_roundtrip_preserves_every_snapshot_value(self):
        outcome, diagnostic = self._public_diagnostic()
        self._assert_available(diagnostic)
        self._assert_snapshot_hash(diagnostic)
        validation.apply_validation_outcome(self.article, outcome)
        log = AutomationLog.objects.get(article=self.article)
        self.assertEqual(log.payload["numeric_surface_audit"], diagnostic)
        self.assertEqual(log.payload["numeric_surface_audit"]["fields"]["title"]["source_field"], "title_ja")
        self.assertEqual(log.payload["numeric_surface_audit"]["fields"]["body"]["source_field"], "body_ja_normalized")
        self.assertEqual(log.payload["numeric_surface_audit"]["fields"]["title"]["target_selector"], "_publish_title")
        self.assertEqual(log.payload["numeric_surface_audit"]["fields"]["body"]["target_selector"], "_publish_body")
        self.assertEqual(log.payload["numeric_surface_audit"]["fields"]["body"]["audit"]["differences"], ZERO_CHANGE)
        self._assert_snapshot_hash(log.payload["numeric_surface_audit"])
        self.assertEqual(log.payload["issue_counts"], {"blocker": 0, "warning": 0, "info": 0})
        self.article.refresh_from_db()
        self.assertEqual(self.article.gate_issues, [])
        self.assertEqual(self.article.automation_warning_email_signature, "")

    def test_real_deferred_timestamp_log_roundtrip_keeps_explicit_null_reason(self):
        deferred = NewsArticle.objects.defer("updated_at").get(id=self.article.id)
        outcome, diagnostic = self._public_diagnostic(deferred)
        self.assertEqual(diagnostic["updated_at_observation"], "field_not_loaded")
        self.assertIsNone(diagnostic["article_updated_at"])
        validation.apply_validation_outcome(deferred, outcome)
        stored = AutomationLog.objects.get(article=deferred).payload["numeric_surface_audit"]
        self.assertEqual(stored, diagnostic)
        self._assert_snapshot_hash(stored)

    def test_log_keeps_validation_snapshot_after_article_fields_change(self):
        outcome, diagnostic = self._public_diagnostic()
        original_hash = diagnostic["snapshot_sha256"]
        NewsArticle.objects.filter(id=self.article.id).update(body_zh="9 " + BODY)
        self.article.refresh_from_db()
        validation.apply_validation_outcome(self.article, outcome)
        stored = AutomationLog.objects.get(article=self.article).payload["numeric_surface_audit"]
        self.assertEqual(stored, diagnostic)
        self.assertEqual(stored["snapshot_sha256"], original_hash)
        self.assertEqual(stored["fields"]["body"]["translated_text"], "3 " + BODY)

    def test_existing_log_serialization_error_is_not_swallowed_by_builder_fallback(self):
        outcome, _ = self._public_diagnostic()
        legacy_value = object()
        outcome.details["legacy_value"] = legacy_value
        diagnostic = self._bodies("2", "3", existing_details=outcome.details)
        self._assert_unavailable(diagnostic, "resource_refusal", "existing_payload_type")
        outcome.details["numeric_surface_audit"] = diagnostic
        with self.assertRaises(TypeError):
            validation.apply_validation_outcome(self.article, outcome)
        self.assertIs(outcome.details["legacy_value"], legacy_value)
        self.assertEqual(AutomationLog.objects.filter(article=self.article).count(), 0)

    def _measure_peak(self, operation):
        owned = not tracemalloc.is_tracing()
        if owned:
            tracemalloc.start()
        try:
            baseline = tracemalloc.get_traced_memory()[0]
            tracemalloc.reset_peak()
            started = time.perf_counter()
            value = operation()
            elapsed = time.perf_counter() - started
            peak = tracemalloc.get_traced_memory()[1]
            return value, max(0, peak - baseline), elapsed
        finally:
            if owned:
                tracemalloc.stop()

    def _measure_real_path(self, fixture_name, expected_refusal=None):
        raw = (self.article.title_ja, self.article.body_ja_normalized or self.article.body_ja_raw,
               validation._publish_title(self.article, "base_translation"),
               validation._publish_body(self.article, "base_translation"))
        outcome, public_diagnostic = self._public_diagnostic()
        if expected_refusal is None:
            self._assert_available(public_diagnostic)
        else:
            self._assert_unavailable(public_diagnostic, "resource_refusal", expected_refusal)
        old_details = {k: v for k, v in outcome.details.items() if k != "numeric_surface_audit"}
        diagnostic, builder_peak, builder_seconds = self._measure_peak(lambda: self._build(
            source_title=raw[0], source_body=raw[1], translated_title=raw[2],
            translated_body=raw[3], existing_details=old_details,
        ))
        self.assertEqual(diagnostic, public_diagnostic)
        _, apply_peak, apply_seconds = self._measure_peak(
            lambda: validation.apply_validation_outcome(self.article, outcome)
        )
        log = AutomationLog.objects.get(article=self.article)
        self.assertEqual(log.payload["numeric_surface_audit"], diagnostic)
        canonical_bytes = len(json.dumps(diagnostic, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False, allow_nan=False).encode("utf-8"))
        diagnostic_bytes = len(json.dumps(diagnostic, allow_nan=False).encode("utf-8"))
        log_bytes = len(json.dumps(log.payload, allow_nan=False).encode("utf-8"))
        # 正常 profile 既有合同为 PostgreSQL16；没有 SQLite/宿主替代路径。
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT octet_length(payload::text), pg_column_size(payload) "
                "FROM stable_automationlog WHERE id = %s", [log.id]
            )
            db_json_text_bytes, db_physical_bytes = cursor.fetchone()
        fields = diagnostic.get("fields")
        record = {
            "fixture": fixture_name, "canonical_method": self.id(), "python": platform.python_version(),
            "platform": platform.platform(), "raw_utf8_bytes": [len(s.encode("utf-8")) for s in raw],
            "raw_input_order": ["source_title", "source_body", "translated_title", "translated_body"],
            "clean_input_order": ["title.source", "title.translated", "body.source", "body.translated"],
            "raw_codepoints": [len(s) for s in raw],
            # 物理fixture观测，不作为业务expected或native分母。
            "raw_occurrences_observed": [sum(1 for _ in validation._NUMBER_RE.finditer(s)) for s in raw],
            "clean_utf8_bytes": [len(fields[k][side].encode("utf-8"))
                                 for k in ("title", "body") for side in ("source_text", "translated_text")]
                                if fields is not None else None,
            "clean_source_occurrences": sum(fields[k]["audit"]["source_token_count"] for k in fields)
                                        if fields is not None else None,
            "clean_translated_occurrences": sum(fields[k]["audit"]["translated_token_count"] for k in fields)
                                            if fields is not None else None,
            "admission_status": diagnostic["status"], "refused_limit": expected_refusal,
            "canonical_diagnostic_bytes": canonical_bytes, "default_json_diagnostic_bytes": diagnostic_bytes,
            "default_json_augmented_log_bytes": log_bytes, "db_json_text_bytes": db_json_text_bytes,
            "db_physical_bytes_separate": db_physical_bytes, "builder_incremental_peak_bytes": builder_peak,
            "apply_incremental_peak_bytes": apply_peak, "builder_seconds_observation_only": builder_seconds,
            "apply_seconds_observation_only": apply_seconds,
            "measurement": "inputs built before baseline; tracemalloc reset_peak around builder and separately real apply/log",
        }
        print("NUMERIC_DIAGNOSTIC_COST " + json.dumps(record, sort_keys=True))
        # 先留下真实尺寸/峰值原始观测，即使随后预算断言失败也可复核。
        self.assertLessEqual(builder_peak, 16777216)
        if expected_refusal is None:
            self.assertLessEqual(diagnostic_bytes, 589824)
            self.assertLessEqual(log_bytes, 786432)
            self.assertLessEqual(db_json_text_bytes, 786432)
        else:
            # 拒绝只限制新增贡献；不发明旧日志全路径的全局上限。
            self.assertLessEqual(diagnostic_bytes, 512)

    def test_measure_ordinary_real_builder_and_apply_log_path(self):
        self._measure_real_path("ordinary")

    def test_measure_large_complete_snapshots_with_repeated_numbers_beyond_twenty_four(self):
        self.article.title_ja = "a"
        self.article.title_zh = "b"
        self.article.body_ja_normalized = ("1 " * 256) + ("a" * 15871)
        self.article.body_zh = "b" * 16383
        self._measure_real_path("large-repeated-over24")

    def test_measure_large_distinct_token_evidence_and_real_log_roundtrip(self):
        self.article.title_ja = "a"
        self.article.title_zh = "b"
        self.article.body_ja_normalized = " ".join(f"{i:03d}" + "1" * 60 for i in range(256))
        self.article.body_zh = " ".join(f"{i:03d}" + "2" * 60 for i in range(256))
        self._measure_real_path("large-distinct-512-occurrences")

    def test_measure_raw_character_refusal_through_real_caller_and_log(self):
        self.article.body_ja_normalized = "x" * 16385
        self._measure_real_path("refused-raw-codepoints", "raw_field_codepoints")

    def test_measure_raw_utf8_refusal_through_real_caller_and_log(self):
        self.article.body_ja_normalized = "中" * 6000
        self._measure_real_path("refused-raw-utf8", "raw_field_utf8_bytes")

    def test_measure_occurrence_refusal_through_real_caller_and_log(self):
        self.article.body_ja_normalized = "1 " * 513
        self._measure_real_path("refused-raw-occurrences", "raw_occurrences")

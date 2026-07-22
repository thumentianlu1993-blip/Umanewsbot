import csv
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase

from stable.models import OperationLog, RaceEvent, RaceSeries, TermEntry
from stable.services import race_display_name_translation_2026 as translation


class NormalizeKeyTests(TestCase):
    def test_lowercases_and_strips_non_alnum(self):
        self.assertEqual(
            translation.normalize_key("Betfair Cleeve Hurdle!"),
            "betfaircleevehurdle",
        )
        self.assertEqual(translation.normalize_key("CLEEVE  HURDLE"), "cleevehurdle")
        self.assertEqual(
            translation.normalize_key("Premier Cup (H)"), "premiercuph"
        )

    def test_kana_only_name_normalizes_to_empty(self):
        self.assertEqual(translation.normalize_key("ブルーバードカップ"), "")


class StripSponsorTests(TestCase):
    def test_trailing_bracket_segment_is_stripped(self):
        base, stripped = translation.strip_sponsor("Cleeve Hurdle[McCoy Contractors]")
        self.assertTrue(stripped)
        self.assertEqual(base, "Cleeve Hurdle")

    def test_presented_by_suffix_is_stripped_case_insensitive(self):
        base, stripped = translation.strip_sponsor(
            "Pegasus World Cup Filly Turf Presented by SirDavis"
        )
        self.assertTrue(stripped)
        self.assertEqual(base, "Pegasus World Cup Filly Turf")
        base, stripped = translation.strip_sponsor(
            "Pegasus Turf presented by SirDavis [TAA]"
        )
        self.assertTrue(stripped)
        self.assertEqual(base, "Pegasus Turf")

    def test_allowlisted_prefixes_are_stripped(self):
        for prefix in (
            "Betfair",
            "William Hill",
            "Unibet",
            "Virgin Bet",
            "BetMGM",
            "Betmgm",
            "Coral",
            "Sky Bet",
            "JCB",
            "Trustatrader",
            "Dornan Engineering",
            "AIS",
            "SBK",
        ):
            base, stripped = translation.strip_sponsor(f"{prefix} Cleeve Hurdle")
            self.assertTrue(stripped, prefix)
            self.assertEqual(base, "Cleeve Hurdle", prefix)

    def test_prefix_outside_allowlist_is_not_stripped(self):
        base, stripped = translation.strip_sponsor("Jane Seymour Nov. Hurdle")
        self.assertFalse(stripped)
        self.assertEqual(base, "Jane Seymour Nov. Hurdle")

    def test_empty_or_unchanged_result_counts_as_unstripped(self):
        base, stripped = translation.strip_sponsor("[McCoy Contractors]")
        self.assertFalse(stripped)
        self.assertEqual(base, "[McCoy Contractors]")
        base, stripped = translation.strip_sponsor("Betfair")
        self.assertFalse(stripped)
        self.assertEqual(base, "Betfair")
        base, stripped = translation.strip_sponsor("Cleeve Hurdle")
        self.assertFalse(stripped)
        self.assertEqual(base, "Cleeve Hurdle")


class HandicapGuardTests(TestCase):
    def test_contains_marker(self):
        self.assertTrue(translation.contains_handicap_marker("精英杯 (让赛)"))
        self.assertTrue(translation.contains_handicap_marker("洋紫荆短途锦标 (讓賽)"))
        self.assertTrue(translation.contains_handicap_marker("两岁马让步赛"))
        self.assertTrue(translation.contains_handicap_marker("兩歲馬讓步賽"))
        self.assertFalse(translation.contains_handicap_marker("精英杯"))

    def test_unbracketed_guard(self):
        self.assertTrue(
            translation.has_unbracketed_handicap_marker("Sprint 2yo Handicap")
        )
        self.assertTrue(
            translation.has_unbracketed_handicap_marker(
                "THE KWANGTUNG HANDICAP CUP (HANDICAP)"
            )
        )
        self.assertFalse(
            translation.has_unbracketed_handicap_marker("Premier Cup (H)")
        )
        self.assertFalse(
            translation.has_unbracketed_handicap_marker("Cleeve Hurdle")
        )


class TranslationDbMixin:
    def setUp(self):
        self.series_cjk = RaceSeries.objects.create(
            key="us-first-lady",
            canonical_name_original="First Lady Stakes",
            chinese_name="第一夫人锦标",
            country_region="united_states",
        )
        self.series_guard = RaceSeries.objects.create(
            key="hk-guard-cup",
            canonical_name_original="Guard Cup",
            chinese_name="守卫杯 (让赛)",
            country_region="hong_kong",
        )
        self.series_plain = RaceSeries.objects.create(
            key="uk-plain-series",
            canonical_name_original="Plain Series",
            chinese_name="",
            country_region="united_kingdom",
        )

        self.term_cleeve = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="united_kingdom",
            source_ja="Cleeve Hurdle",
            target_zh="克利夫跨栏锦标",
        )
        self.term_alias = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="united_kingdom",
            source_ja="York Stakes",
            aliases_ja=["Yorkshire Stakes"],
            target_zh="约克锦标",
        )
        self.term_pending = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="united_kingdom",
            source_ja="Falmouth Stakes",
            target_zh="法尔曼斯锦标",
            translation_status="pending",
        )
        self.term_empty = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="united_kingdom",
            source_ja="Coronation Cup",
            target_zh="",
        )
        self.term_ambiguous_a = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="united_kingdom",
            source_ja="Sun Chariot Stakes",
            target_zh="太阳战车锦标",
        )
        self.term_ambiguous_b = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="united_kingdom",
            source_ja="Sun Chariot Stakes!",
            target_zh="太阳马车锦标",
        )
        self.term_guard = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="united_kingdom",
            source_ja="Guardian Stakes",
            target_zh="卫士锦标 (让赛)",
        )
        self.term_inactive = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="united_kingdom",
            source_ja="Inactive Stakes",
            target_zh="停用锦标",
            is_active=False,
        )
        self.term_other_type = TermEntry.objects.create(
            term_type="horse",
            source_language="en",
            racing_region="united_kingdom",
            source_ja="Horse Type Stakes",
            target_zh="马类锦标",
        )

        # 历史已发布赛事（非 2026）译名参照集
        self._event("Prix Foy", year=2024, chinese="福伊锦标", region="france")
        self._event("Dante Stakes", year=2023, chinese="但丁锦标")
        self._event("Pegasus Turf", year=2025, chinese="飞马草地锦标", region="united_states")
        self._event("Nassau Stakes", year=2021, chinese="拿骚锦标")
        self._event("Nassau Stakes", year=2022, chinese="纳索锦标")
        self._event("Premier Cup (H)", year=2025, chinese="精英杯", region="hong_kong")
        self._event("Old Stakes", year=2025, chinese="Old Stakes")
        self._event("Draft History", year=2025, chinese="草稿历史", visibility="draft")

        # 2026 目标赛事（chinese_name 为原文回退）
        self.e_series = self._event(
            "First Lady Stakes", region="united_states", series=self.series_cjk
        )
        self.e_series_guard = self._event(
            "Guard Cup", region="hong_kong", series=self.series_guard
        )
        self.e_term = self._event("CLEEVE  HURDLE")
        self.e_term_alias = self._event("Yorkshire Stakes")
        self.e_term_pending = self._event("Falmouth Stakes")
        self.e_term_empty = self._event("Coronation Cup")
        self.e_term_ambiguous = self._event("Sun Chariot Stakes")
        self.e_term_guard = self._event("Guardian Stakes")
        self.e_term_inactive = self._event("Inactive Stakes")
        self.e_term_other_type = self._event("Horse Type Stakes")
        self.e_history_full = self._event("Prix Foy", region="france")
        self.e_history_base = self._event("Betfair Dante Stakes")
        self.e_history_presented = self._event(
            "Pegasus Turf Presented by SirDavis [TAA]", region="united_states"
        )
        self.e_history_ambiguous = self._event("Nassau Stakes")
        self.e_bracketed_handicap = self._event(
            "Premier Cup (H)", region="hong_kong"
        )
        self.e_unbracketed_handicap = self._event("Sprint 2yo Handicap")
        self.e_locked = self._event(
            "Coral Eclipse", flags={"chinese_name": True}
        )
        self.e_l3_kana = self._event("ブルーバードカップ", region="japan")
        self.e_l3_plain = self._event("Zetland Stakes")
        self.e_l3_old = self._event("Old Stakes")

        # 非目标对象
        self.e_draft = self._event("Draft Stakes", visibility="draft")
        self.e_cjk = self._event("Already Stakes", chinese="已有锦标")

    def _event(
        self,
        original,
        *,
        year=2026,
        chinese=None,
        region="united_kingdom",
        visibility="published",
        series=None,
        flags=None,
    ):
        return RaceEvent.objects.create(
            year=year,
            original_name=original,
            chinese_name=chinese if chinese is not None else original,
            country_region=region,
            visibility_status=visibility,
            race_series=series,
            manual_lock_flags=flags or {},
        )


class DryRunTests(TranslationDbMixin, TestCase):
    def _rows_by_id(self, report):
        rows = {}
        for bucket in ("candidates", "manual"):
            for row in report[bucket]:
                rows[row["id"]] = (bucket, row)
        return rows

    def test_target_scope_excludes_non_targets(self):
        report = translation.build_dry_run()
        rows = self._rows_by_id(report)
        self.assertEqual(report["counts"]["total"], 20)
        self.assertNotIn(self.e_draft.id, rows)
        self.assertNotIn(self.e_cjk.id, rows)

    def test_series_inheritance_candidate(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_series.id]
        self.assertEqual(bucket, "candidates")
        self.assertEqual(row["level"], "series")
        self.assertEqual(row["suggestedName"], "第一夫人锦标")
        self.assertEqual(row["matchedOn"], "First Lady Stakes")

    def test_series_guard_hit_goes_to_manual(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_series_guard.id]
        self.assertEqual(bucket, "manual")
        self.assertIn("handicap", row["reason"])

    def test_term_hit_with_case_and_whitespace_normalization(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_term.id]
        self.assertEqual(bucket, "candidates")
        self.assertEqual(row["level"], "term")
        self.assertEqual(row["suggestedName"], "克利夫跨栏锦标")
        self.assertIn("Cleeve Hurdle", row["matchedOn"])

    def test_term_alias_hit(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_term_alias.id]
        self.assertEqual(bucket, "candidates")
        self.assertEqual(row["level"], "term")
        self.assertEqual(row["suggestedName"], "约克锦标")
        self.assertIn("Yorkshire Stakes", row["matchedOn"])

    def test_pending_and_empty_terms_do_not_participate(self):
        report = translation.build_dry_run()
        rows = self._rows_by_id(report)
        for event in (self.e_term_pending, self.e_term_empty):
            bucket, row = rows[event.id]
            self.assertEqual(bucket, "candidates")
            self.assertEqual(row["level"], "needs_translation")
            self.assertEqual(row["suggestedName"], "")

    def test_inactive_and_non_race_terms_do_not_participate(self):
        report = translation.build_dry_run()
        rows = self._rows_by_id(report)
        for event in (self.e_term_inactive, self.e_term_other_type):
            bucket, row = rows[event.id]
            self.assertEqual(bucket, "candidates")
            self.assertEqual(row["level"], "needs_translation")

    def test_ambiguous_term_translations_go_to_manual(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_term_ambiguous.id]
        self.assertEqual(bucket, "manual")
        self.assertIn("ambiguous", row["reason"])

    def test_term_candidate_with_marker_goes_to_manual(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_term_guard.id]
        self.assertEqual(bucket, "manual")
        self.assertIn("handicap", row["reason"])

    def test_history_full_name_hit(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_history_full.id]
        self.assertEqual(bucket, "candidates")
        self.assertEqual(row["level"], "history")
        self.assertEqual(row["suggestedName"], "福伊锦标")
        self.assertIn("Prix Foy", row["matchedOn"])

    def test_history_base_name_hit_after_prefix_strip(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_history_base.id]
        self.assertEqual(bucket, "candidates")
        self.assertEqual(row["level"], "history")
        self.assertEqual(row["suggestedName"], "但丁锦标")

    def test_history_hit_after_presented_by_and_bracket_strip(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_history_presented.id]
        self.assertEqual(bucket, "candidates")
        self.assertEqual(row["level"], "history")
        self.assertEqual(row["suggestedName"], "飞马草地锦标")

    def test_ambiguous_history_translations_go_to_manual(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_history_ambiguous.id]
        self.assertEqual(bucket, "manual")
        self.assertIn("ambiguous", row["reason"])

    def test_bracketed_handicap_original_can_still_match(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_bracketed_handicap.id]
        self.assertEqual(bucket, "candidates")
        self.assertEqual(row["level"], "history")
        self.assertEqual(row["suggestedName"], "精英杯")

    def test_unbracketed_handicap_original_goes_to_manual(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_unbracketed_handicap.id]
        self.assertEqual(bucket, "manual")
        self.assertIn("unbracketed", row["reason"])

    def test_manual_lock_goes_to_manual(self):
        report = translation.build_dry_run()
        bucket, row = self._rows_by_id(report)[self.e_locked.id]
        self.assertEqual(bucket, "manual")
        self.assertIn("manual lock", row["reason"])

    def test_needs_translation_bucket(self):
        report = translation.build_dry_run()
        rows = self._rows_by_id(report)
        for event in (self.e_l3_kana, self.e_l3_plain, self.e_l3_old):
            bucket, row = rows[event.id]
            self.assertEqual(bucket, "candidates")
            self.assertEqual(row["level"], "needs_translation")
            self.assertEqual(row["suggestedName"], "")

    def test_counts_levels_and_content_sha(self):
        report = translation.build_dry_run()
        self.assertEqual(
            report["schemaVersion"], "race-display-name-translation-2026-dry-run.v1"
        )
        counts = report["counts"]
        self.assertEqual(counts["candidates"], 14)
        self.assertEqual(counts["manual"], 6)
        self.assertEqual(counts["total"], 20)
        self.assertEqual(
            counts["levels"],
            {"series": 1, "term": 2, "history": 4, "needs_translation": 7},
        )
        content = {"candidates": report["candidates"], "manual": report["manual"]}
        self.assertEqual(
            report["contentSha256"], translation._sha256_json(content)
        )
        for row in report["candidates"] + report["manual"]:
            self.assertIn("chinese_name", row["beforeRow"])
            self.assertIn("manual_lock_flags", row["beforeRow"])


class BuildManifestTests(TranslationDbMixin, TestCase):
    def _reviewed_rows(self):
        report = translation.build_dry_run()
        rows = []
        for row in report["candidates"]:
            rows.append(
                {
                    "id": str(row["id"]),
                    "before": row["before"],
                    "final_name": row["suggestedName"],
                }
            )
        for row in report["manual"]:
            rows.append(
                {"id": str(row["id"]), "before": row["before"], "final_name": ""}
            )
        return rows

    def test_build_manifest_writes_and_veto(self):
        manifest = translation.build_manifest(self._reviewed_rows())
        self.assertEqual(
            manifest["schemaVersion"],
            "race-display-name-translation-2026-manifest.v1",
        )
        self.assertEqual(manifest["counts"]["written"], 7)
        self.assertEqual(manifest["counts"]["veto"], 13)
        self.assertEqual(manifest["counts"]["total"], 20)
        content = {"actions": manifest["actions"], "veto": manifest["veto"]}
        self.assertEqual(
            manifest["contentSha256"], translation._sha256_json(content)
        )
        by_id = {row["id"]: row for row in manifest["actions"]}
        action = by_id[self.e_term.id]
        self.assertEqual(action["before"]["chineseName"], "CLEEVE  HURDLE")
        self.assertEqual(action["after"]["chineseName"], "克利夫跨栏锦标")
        self.assertEqual(action["beforeRow"]["chinese_name"], "CLEEVE  HURDLE")
        self.assertEqual(action["beforeRow"]["manual_lock_flags"], {})
        veto_ids = {row["id"] for row in manifest["veto"]}
        self.assertIn(self.e_l3_plain.id, veto_ids)
        self.assertIn(self.e_locked.id, veto_ids)

    def test_row_count_mismatch_rejected(self):
        rows = self._reviewed_rows()[:-1]
        with self.assertRaisesRegex(translation.TranslationError, "row count"):
            translation.build_manifest(rows)

    def test_id_set_mismatch_rejected(self):
        rows = self._reviewed_rows()
        rows[0]["id"] = str(self.e_draft.id)
        with self.assertRaisesRegex(translation.TranslationError, "id set"):
            translation.build_manifest(rows)

    def test_before_drift_rejected(self):
        rows = self._reviewed_rows()
        RaceEvent.objects.filter(id=self.e_term.id).update(chinese_name="Drifted Value")
        with self.assertRaisesRegex(translation.TranslationError, "before drift"):
            translation.build_manifest(rows)

    def test_final_name_with_marker_rejected(self):
        rows = self._reviewed_rows()
        for row in rows:
            if row["id"] == str(self.e_term.id):
                row["final_name"] = "克利夫跨栏锦标让赛"
        with self.assertRaisesRegex(translation.TranslationError, "handicap marker"):
            translation.build_manifest(rows)

    def test_handicap_final_allowed_when_original_has_hcap_abbreviation(self):
        # 用户裁决先例：id 666 型原文含 H’Cap（未括号让赛缩写 = 赛事名组成部分），
        # 中文名可保留「让赛」（去让赛锁定规则：两岁马让赛 kept）。
        event = self._event("Betvictor EBF Nov. H’Cap Hurdle")
        rows = self._reviewed_rows()
        for row in rows:
            if row["id"] == str(event.id):
                row["final_name"] = "新手让赛跨栏锦标"
        manifest = translation.build_manifest(rows)
        by_id = {row["id"]: row for row in manifest["actions"]}
        self.assertEqual(
            by_id[event.id]["after"]["chineseName"], "新手让赛跨栏锦标"
        )

    def test_handicap_final_rejected_when_original_has_no_indicator(self):
        rows = self._reviewed_rows()
        for row in rows:
            if row["id"] == str(self.e_l3_plain.id):
                row["final_name"] = "泽特兰让赛锦标"
        with self.assertRaisesRegex(translation.TranslationError, "handicap marker"):
            translation.build_manifest(rows)

    def test_handicap_final_allowed_when_original_has_unbracketed_handicap(self):
        # 原文含未括号 handicap 完整词（dry-run 守卫转 manual 的行，用户审核通过
        # 保留「让赛」）→ 放行。
        rows = self._reviewed_rows()
        for row in rows:
            if row["id"] == str(self.e_unbracketed_handicap.id):
                row["final_name"] = "短途两岁马让赛锦标"
        manifest = translation.build_manifest(rows)
        by_id = {row["id"]: row for row in manifest["actions"]}
        self.assertEqual(
            by_id[self.e_unbracketed_handicap.id]["after"]["chineseName"],
            "短途两岁马让赛锦标",
        )

    def test_final_name_without_cjk_rejected(self):
        rows = self._reviewed_rows()
        for row in rows:
            if row["id"] == str(self.e_term.id):
                row["final_name"] = "Cleeve Hurdle Zh"
        with self.assertRaisesRegex(translation.TranslationError, "CJK"):
            translation.build_manifest(rows)

    def test_final_name_for_locked_event_rejected(self):
        rows = self._reviewed_rows()
        for row in rows:
            if row["id"] == str(self.e_locked.id):
                row["final_name"] = "日蚀锦标"
        with self.assertRaisesRegex(translation.TranslationError, "manual lock"):
            translation.build_manifest(rows)

    def test_veto_decision_with_final_name_rejected(self):
        rows = self._reviewed_rows()
        for row in rows:
            if row["id"] == str(self.e_term.id):
                row["decision"] = "veto"
        with self.assertRaisesRegex(translation.TranslationError, "decision"):
            translation.build_manifest(rows)

    def test_veto_decision_with_blank_final_name_records_veto(self):
        rows = self._reviewed_rows()
        for row in rows:
            if row["id"] == str(self.e_term.id):
                row["decision"] = " Veto "
                row["final_name"] = ""
        manifest = translation.build_manifest(rows)
        veto_ids = {row["id"] for row in manifest["veto"]}
        self.assertIn(self.e_term.id, veto_ids)
        action_ids = {row["id"] for row in manifest["actions"]}
        self.assertNotIn(self.e_term.id, action_ids)

    def test_approve_decision_with_final_name_writes_action(self):
        rows = self._reviewed_rows()
        for row in rows:
            row["decision"] = "通过" if row["final_name"] else "否决"
        manifest = translation.build_manifest(rows)
        by_id = {row["id"]: row for row in manifest["actions"]}
        self.assertEqual(
            by_id[self.e_term.id]["after"]["chineseName"], "克利夫跨栏锦标"
        )
        self.assertEqual(manifest["counts"]["written"], 7)

    def test_rows_without_decision_key_keep_existing_behavior(self):
        rows = self._reviewed_rows()
        for row in rows:
            self.assertNotIn("decision", row)
        manifest = translation.build_manifest(rows)
        self.assertEqual(manifest["counts"]["written"], 7)
        self.assertEqual(manifest["counts"]["veto"], 13)


class CommitTests(TranslationDbMixin, TransactionTestCase):
    def _context(self):
        return {
            "artifactSha256": "a" * 64,
            "backupSha256": "b" * 64,
            "backupSizeBytes": 12345,
            "operator": "mentianlu_via_codex",
            "authorizationRef": "user-test",
            "authorizationTime": "2026-07-22T00:00:00Z",
        }

    def _manifest(self):
        report = translation.build_dry_run()
        rows = []
        for row in report["candidates"]:
            rows.append(
                {
                    "id": str(row["id"]),
                    "before": row["before"],
                    "final_name": row["suggestedName"],
                }
            )
        for row in report["manual"]:
            rows.append(
                {"id": str(row["id"]), "before": row["before"], "final_name": ""}
            )
        return translation.build_manifest(rows)

    def test_commit_writes_only_approved_rows_and_logs_once(self):
        manifest = self._manifest()
        result = translation.execute_commit(manifest, audit_context=self._context())
        self.assertEqual(result["written"], 7)
        self.e_term.refresh_from_db()
        self.e_history_base.refresh_from_db()
        self.e_series.refresh_from_db()
        self.e_l3_plain.refresh_from_db()
        self.e_locked.refresh_from_db()
        self.e_history_ambiguous.refresh_from_db()
        self.assertEqual(self.e_term.chinese_name, "克利夫跨栏锦标")
        self.assertEqual(self.e_history_base.chinese_name, "但丁锦标")
        self.assertEqual(self.e_series.chinese_name, "第一夫人锦标")
        self.assertEqual(self.e_l3_plain.chinese_name, "Zetland Stakes")
        self.assertEqual(self.e_locked.chinese_name, "Coral Eclipse")
        self.assertEqual(self.e_history_ambiguous.chinese_name, "Nassau Stakes")
        logs = OperationLog.objects.filter(
            action_type="race_display_name_translation_2026_applied"
        )
        self.assertEqual(logs.count(), 1)
        log = logs.get()
        self.assertEqual(
            log.target_type, "race_display_name_translation_2026_batch"
        )
        detail = json.loads(log.detail)
        self.assertEqual(
            detail["schemaVersion"],
            "race-display-name-translation-2026-operation-log.v1",
        )
        self.assertEqual(detail["backupSha256"], "b" * 64)
        self.assertEqual(detail["authorizationRef"], "user-test")
        self.assertEqual(detail["counts"]["written"], 7)
        self.assertEqual(detail["counts"]["veto"], 13)

    def test_commit_does_not_touch_slug_or_series_key(self):
        manifest = self._manifest()
        before_slug = self.e_term.slug
        before_series_key = self.e_series.series_key
        translation.execute_commit(manifest, audit_context=self._context())
        self.e_term.refresh_from_db()
        self.e_series.refresh_from_db()
        self.assertEqual(self.e_term.slug, before_slug)
        self.assertEqual(self.e_series.series_key, before_series_key)

    def test_commit_uses_bulk_update_without_model_save(self):
        manifest = self._manifest()
        with mock.patch.object(RaceEvent, "save") as save_mock:
            translation.execute_commit(manifest, audit_context=self._context())
            save_mock.assert_not_called()
        self.e_term.refresh_from_db()
        self.assertEqual(self.e_term.chinese_name, "克利夫跨栏锦标")

    def test_repeated_commit_is_rejected(self):
        manifest = self._manifest()
        translation.execute_commit(manifest, audit_context=self._context())
        with self.assertRaisesRegex(translation.TranslationError, "already applied"):
            translation.execute_commit(manifest, audit_context=self._context())
        self.assertEqual(
            OperationLog.objects.filter(
                action_type="race_display_name_translation_2026_applied"
            ).count(),
            1,
        )

    def test_before_drift_rolls_back_everything(self):
        manifest = self._manifest()
        RaceEvent.objects.filter(id=self.e_term.id).update(chinese_name="漂移值")
        with self.assertRaisesRegex(translation.TranslationError, "CAS"):
            translation.execute_commit(manifest, audit_context=self._context())
        self.e_history_base.refresh_from_db()
        self.assertEqual(self.e_history_base.chinese_name, "Betfair Dante Stakes")
        self.assertEqual(
            OperationLog.objects.filter(
                action_type="race_display_name_translation_2026_applied"
            ).count(),
            0,
        )

    def test_flags_drift_rolls_back_everything(self):
        manifest = self._manifest()
        RaceEvent.objects.filter(id=self.e_term.id).update(
            manual_lock_flags={"chinese_name": True}
        )
        with self.assertRaisesRegex(translation.TranslationError, "CAS"):
            translation.execute_commit(manifest, audit_context=self._context())
        self.e_history_base.refresh_from_db()
        self.assertEqual(self.e_history_base.chinese_name, "Betfair Dante Stakes")
        self.assertEqual(
            OperationLog.objects.filter(
                action_type="race_display_name_translation_2026_applied"
            ).count(),
            0,
        )

    def test_manual_lock_hard_rejects_commit(self):
        manifest = self._manifest()
        RaceEvent.objects.filter(id=self.e_term.id).update(
            manual_lock_flags={"chinese_name": True}
        )
        for row in manifest["actions"]:
            if row["id"] == self.e_term.id:
                row["beforeRow"]["manual_lock_flags"] = {"chinese_name": True}
        with self.assertRaisesRegex(translation.TranslationError, "manual lock"):
            translation.execute_commit(manifest, audit_context=self._context())
        self.e_history_base.refresh_from_db()
        self.assertEqual(self.e_history_base.chinese_name, "Betfair Dante Stakes")
        self.assertEqual(
            OperationLog.objects.filter(
                action_type="race_display_name_translation_2026_applied"
            ).count(),
            0,
        )


class VerifyTests(TranslationDbMixin, TransactionTestCase):
    def _build_manifest(self, overrides=None):
        report = translation.build_dry_run()
        rows = []
        for row in report["candidates"]:
            rows.append(
                {
                    "id": str(row["id"]),
                    "before": row["before"],
                    "final_name": row["suggestedName"],
                }
            )
        for row in report["manual"]:
            rows.append(
                {"id": str(row["id"]), "before": row["before"], "final_name": ""}
            )
        for row in rows:
            if overrides and int(row["id"]) in overrides:
                row["final_name"] = overrides[int(row["id"])]
        return translation.build_manifest(rows)

    def _commit(self, overrides=None):
        manifest = self._build_manifest(overrides=overrides)
        self._execute(manifest)
        return manifest

    def _execute(self, manifest):
        translation.execute_commit(
            manifest,
            audit_context={
                "artifactSha256": "a" * 64,
                "backupSha256": "b" * 64,
                "backupSizeBytes": 12345,
                "operator": "mentianlu_via_codex",
                "authorizationRef": "user-test",
                "authorizationTime": "2026-07-22T00:00:00Z",
            },
        )

    def test_verify_after_commit_ok(self):
        manifest = self._commit()
        outcome = translation.verify_applied(manifest)
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["written"], 7)
        self.assertEqual(outcome["veto"], 13)

    def test_commit_verify_end_to_end_with_hcap_handicap_value(self):
        # id 666 型：原文含 H’Cap（让赛为赛事名组成部分），定稿中文名保留「让赛」，
        # build_manifest 例外放行 -> commit 写入 -> verify 同样放行（两层规则一致）。
        event = self._event("Betvictor EBF Nov. H’Cap Hurdle")
        manifest = self._commit(overrides={event.id: "新手让赛跨栏锦标"})
        outcome = translation.verify_applied(manifest)
        self.assertTrue(outcome["ok"])
        event.refresh_from_db()
        self.assertEqual(event.chinese_name, "新手让赛跨栏锦标")

    def test_verify_detects_marker_tamper_without_indicator(self):
        manifest = self._commit()
        RaceEvent.objects.filter(id=self.e_term.id).update(
            chinese_name="克利夫跨栏锦标让赛"
        )
        with self.assertRaisesRegex(translation.TranslationError, "verify"):
            translation.verify_applied(manifest)

    def test_verify_rejects_marker_value_when_original_has_no_indicator(self):
        # 构造 manifest 写入值含让赛标记但原文无未括号指标（绕过 build_manifest
        # 校验的篡改场景）：commit 后 verify 仍须拒绝。
        manifest = self._build_manifest()
        for row in manifest["actions"]:
            if row["id"] == self.e_term.id:
                row["after"]["chineseName"] = "克利夫跨栏锦标让赛"
        self._execute(manifest)
        with self.assertRaisesRegex(translation.TranslationError, "marker remains"):
            translation.verify_applied(manifest)

    def test_verify_detects_written_value_tamper(self):
        manifest = self._commit()
        RaceEvent.objects.filter(id=self.e_term.id).update(chinese_name="被篡改")
        with self.assertRaisesRegex(translation.TranslationError, "verify"):
            translation.verify_applied(manifest)

    def test_verify_detects_veto_row_tamper(self):
        manifest = self._commit()
        RaceEvent.objects.filter(id=self.e_l3_plain.id).update(
            chinese_name="被篡改"
        )
        with self.assertRaisesRegex(translation.TranslationError, "verify"):
            translation.verify_applied(manifest)

    def test_verify_rejects_wrong_schema(self):
        with self.assertRaisesRegex(translation.TranslationError, "schema"):
            translation.verify_applied({"schemaVersion": "other"})


class ManagementCommandTests(TranslationDbMixin, TransactionTestCase):
    def _dry_run(self, directory):
        out = io.StringIO()
        call_command(
            "translate_2026_race_display_names",
            "--output-dir",
            directory,
            stdout=out,
        )
        return json.loads(out.getvalue())

    def test_command_dry_run_outputs_artifact_and_review_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = self._dry_run(directory)
            artifact = Path(summary["artifact"])
            review_csv = Path(summary["reviewCsv"])
            self.assertTrue(artifact.is_file())
            self.assertTrue(review_csv.is_file())
            self.assertEqual(summary["counts"]["total"], 20)
            with review_csv.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 20)
            self.assertEqual(
                summary["counts"]["candidates"] + summary["counts"]["manual"], 20
            )

    def test_command_build_manifest_commit_and_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = self._dry_run(directory)
            review_csv = Path(summary["reviewCsv"])
            with review_csv.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                if row["bucket"] == "candidates" and row["suggested_name"]:
                    row["final_name"] = row["suggested_name"]
            reviewed = Path(directory) / "reviewed.csv"
            with reviewed.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

            out = io.StringIO()
            call_command(
                "translate_2026_race_display_names",
                "--build-manifest",
                "--reviewed-csv",
                str(reviewed),
                "--output-dir",
                directory,
                stdout=out,
            )
            manifest_summary = json.loads(out.getvalue())
            self.assertEqual(manifest_summary["counts"]["written"], 7)
            self.assertEqual(manifest_summary["counts"]["veto"], 13)
            artifact = manifest_summary["artifact"]
            sha = manifest_summary["artifactSha256"]

            out = io.StringIO()
            call_command(
                "translate_2026_race_display_names",
                "--commit",
                "--artifact",
                artifact,
                "--artifact-sha256",
                sha,
                "--backup-sha256",
                "c" * 64,
                "--backup-size-bytes",
                "999",
                "--authorization-ref",
                "user-test",
                "--authorization-time",
                "2026-07-22T00:00:00Z",
                stdout=out,
            )
            result = json.loads(out.getvalue())
            self.assertEqual(result["written"], 7)
            self.e_term.refresh_from_db()
            self.assertEqual(self.e_term.chinese_name, "克利夫跨栏锦标")
            self.e_l3_plain.refresh_from_db()
            self.assertEqual(self.e_l3_plain.chinese_name, "Zetland Stakes")

            out = io.StringIO()
            call_command(
                "translate_2026_race_display_names",
                "--verify",
                "--artifact",
                artifact,
                "--artifact-sha256",
                sha,
                stdout=out,
            )
            outcome = json.loads(out.getvalue())
            self.assertTrue(outcome["ok"])
            self.assertEqual(outcome["written"], 7)

    def test_command_build_manifest_accepts_bom_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = self._dry_run(directory)
            review_csv = Path(summary["reviewCsv"])
            with review_csv.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                if row["bucket"] == "candidates" and row["suggested_name"]:
                    row["final_name"] = row["suggested_name"]
            # 真实定稿工作簿列布局（首列为 id；Excel 导出带 UTF-8 BOM）
            fieldnames = [
                "id",
                "region",
                "original_name",
                "before",
                "level",
                "matched_on",
                "suggested_name",
                "confidence",
                "rationale",
                "final_name",
                "decision",
            ]
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "id": row["id"],
                        "region": row["region"],
                        "original_name": row["original_name"],
                        "before": row["before"],
                        "level": row["level"],
                        "matched_on": row["matched_on"],
                        "suggested_name": row["suggested_name"],
                        "confidence": "",
                        "rationale": "",
                        "final_name": row["final_name"],
                        "decision": "",
                    }
                )
            reviewed = Path(directory) / "reviewed.csv"
            reviewed.write_bytes(b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8"))
            out = io.StringIO()
            call_command(
                "translate_2026_race_display_names",
                "--build-manifest",
                "--reviewed-csv",
                str(reviewed),
                "--output-dir",
                directory,
                stdout=out,
            )
            manifest_summary = json.loads(out.getvalue())
            self.assertEqual(manifest_summary["counts"]["written"], 7)
            self.assertEqual(manifest_summary["counts"]["veto"], 13)

    def test_command_rejects_tampered_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "manifest.json"
            artifact.write_text("{}", encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command(
                    "translate_2026_race_display_names",
                    "--verify",
                    "--artifact",
                    str(artifact),
                    "--artifact-sha256",
                    "0" * 64,
                )

    def test_command_commit_and_verify_are_mutually_exclusive(self):
        with self.assertRaises(CommandError):
            call_command(
                "translate_2026_race_display_names",
                "--commit",
                "--verify",
            )

    def test_command_commit_requires_backup_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = self._dry_run(directory)
            review_csv = Path(summary["reviewCsv"])
            with review_csv.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                if row["bucket"] == "candidates" and row["suggested_name"]:
                    row["final_name"] = row["suggested_name"]
            reviewed = Path(directory) / "reviewed.csv"
            with reviewed.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            out = io.StringIO()
            call_command(
                "translate_2026_race_display_names",
                "--build-manifest",
                "--reviewed-csv",
                str(reviewed),
                "--output-dir",
                directory,
                stdout=out,
            )
            manifest_summary = json.loads(out.getvalue())
            with self.assertRaises(CommandError):
                call_command(
                    "translate_2026_race_display_names",
                    "--commit",
                    "--artifact",
                    manifest_summary["artifact"],
                    "--artifact-sha256",
                    manifest_summary["artifactSha256"],
                )

import json

from django.test import TestCase, TransactionTestCase

from stable.models import OperationLog, RaceEvent, RaceSeries, TermEntry
from stable.services import race_name_handicap_cleanup as cleanup


class CleanDisplayNameTests(TestCase):
    def test_removes_parenthesized_markers_and_separator_space(self):
        self.assertEqual(cleanup.clean_display_name("精英杯 (让赛)"), "精英杯")
        self.assertEqual(cleanup.clean_display_name("精英杯(让赛)"), "精英杯")
        self.assertEqual(cleanup.clean_display_name("雅士谷锦标 (让赛)"), "雅士谷锦标")
        self.assertEqual(cleanup.clean_display_name("洋紫荆短途锦标 (讓賽)"), "洋紫荆短途锦标")

    def test_removes_bare_marker_suffix_without_inventing_words(self):
        self.assertEqual(cleanup.clean_display_name("洋紫荆短途锦标(让赛)"), "洋紫荆短途锦标")

    def test_locked_value_for_keisei_autumn(self):
        self.assertEqual(cleanup.clean_display_name("京成杯秋季让赛"), "京成杯秋季赛")
        self.assertNotEqual(cleanup.clean_display_name("京成杯秋季让赛"), "京成杯秋季")

    def test_preserves_unrelated_text(self):
        self.assertEqual(cleanup.clean_display_name("H. Allen 纪念赛"), "H. Allen 纪念赛")
        self.assertEqual(cleanup.clean_display_name("隆尚教堂大赛"), "隆尚教堂大赛")

    def test_does_not_collapse_other_whitespace(self):
        self.assertEqual(cleanup.clean_display_name("前缀  名称"), "前缀  名称")


class BracketRuleTests(TestCase):
    def test_bracketed_marker_in_original(self):
        self.assertTrue(cleanup.has_bracketed_marker_in_original("THE PREMIER CUP (HANDICAP)"))
        self.assertTrue(cleanup.has_bracketed_marker_in_original("Premier Cup (H)"))
        self.assertTrue(cleanup.has_bracketed_marker_in_original("Ascot Stakes (Handicap)"))
        self.assertTrue(cleanup.has_bracketed_marker_in_original("某赛事（讓賽）"))

    def test_unbracketed_marker_in_original_is_not_bracketed(self):
        self.assertFalse(cleanup.has_bracketed_marker_in_original("2yo Handicap"))
        self.assertFalse(cleanup.has_bracketed_marker_in_original("ALBATROSS HANDICAP"))
        self.assertFalse(cleanup.has_bracketed_marker_in_original("京成杯オータムH"))
        self.assertFalse(cleanup.has_bracketed_marker_in_original("Keisei Hai Autumn Handicap"))
        self.assertFalse(cleanup.has_bracketed_marker_in_original("CANMAKE TOKYO"))
        self.assertFalse(cleanup.has_bracketed_marker_in_original("H. Allen Memorial"))

    def test_should_clean_only_bracketed_or_keisei_exception(self):
        self.assertTrue(cleanup.should_clean("Premier Cup (H)", "精英杯 (让赛)"))
        self.assertTrue(cleanup.should_clean("京成杯オータムH", "京成杯秋季让赛"))
        self.assertFalse(cleanup.should_clean("2yo Handicap", "两岁马让赛"))
        self.assertFalse(cleanup.should_clean("ALBATROSS HANDICAP", "信天翁让赛"))
        self.assertFalse(cleanup.should_clean("京成杯オータムH", "京成杯秋季赛"))


class ClassifyObjectTests(TestCase):
    def test_unbracketed_original_is_kept(self):
        self.assertEqual(
            cleanup.classify_object("2yo Handicap", "两岁马让赛", set(), "united_kingdom"),
            "kept",
        )
        self.assertEqual(
            cleanup.classify_object("CANMAKE TOKYO", "CANMAKE TOKYO让赛", set(), "hong_kong"),
            "kept",
        )
        self.assertEqual(
            cleanup.classify_object("ALBATROSS HANDICAP", "信天翁让赛", set(), "hong_kong"),
            "kept",
        )

    def test_bracketed_original_is_auto_clean(self):
        self.assertEqual(
            cleanup.classify_object("Ascot Stakes (Handicap)", "雅士谷锦标 (让赛)", set(), "united_kingdom"),
            "auto_clean",
        )

    def test_keisei_exception_is_auto_clean(self):
        self.assertEqual(
            cleanup.classify_object("京成杯オータムH", "京成杯秋季让赛", set(), "japan"),
            "auto_clean",
        )

    def test_validation_failure_goes_to_review(self):
        self.assertEqual(
            cleanup.classify_object("X (HANDICAP)", "ABC让赛", set(), "hong_kong"),
            "review",
        )

    def test_same_region_duplicate_goes_to_review(self):
        seen = {("hong_kong", "精英杯")}
        self.assertEqual(
            cleanup.classify_object("Premier Cup (H)", "精英杯 (让赛)", seen, "hong_kong"),
            "review",
        )


class HandicapCleanupDbMixin:
    def setUp(self):
        self.series_locked = RaceSeries.objects.create(
            key="japan-keisei-hai-autumn-h",
            canonical_name_original="京成杯オータムH",
            chinese_name="京成杯秋季让赛",
            country_region="japan",
        )
        self.series_hk = RaceSeries.objects.create(
            key="hong-kong-premier-cup",
            canonical_name_original="Premier Cup (H)",
            chinese_name="精英杯 (让赛)",
            country_region="hong_kong",
        )
        self.series_clean = RaceSeries.objects.create(
            key="france-abbaye-de-longchamp",
            canonical_name_original="Abbaye de Longchamp",
            chinese_name="隆尚教堂大赛",
            country_region="france",
        )
        self.event_hk = RaceEvent.objects.create(
            race_series=self.series_hk,
            series_key=self.series_hk.key,
            original_name="Premier Cup (H)",
            chinese_name="精英杯 (让赛)",
            country_region="hong_kong",
            year=2026,
        )
        self.event_locked = RaceEvent.objects.create(
            race_series=self.series_hk,
            series_key=self.series_hk.key,
            original_name="Locked Cup (H)",
            chinese_name="锁定杯 (让赛)",
            country_region="hong_kong",
            year=2025,
            manual_lock_flags={"chinese_name": True},
        )
        self.term_specific = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="united_kingdom",
            source_ja="Ascot Stakes (Handicap)",
            target_zh="雅士谷锦标 (让赛)",
        )
        self.term_condition = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="united_kingdom",
            source_ja="2yo Handicap",
            target_zh="两岁马让赛",
        )
        self.term_keisei = TermEntry.objects.create(
            term_type="race",
            source_language="ja",
            racing_region="japan",
            source_ja="京成杯オータムH",
            target_zh="京成杯秋季让赛",
        )
        self.term_latin = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="hong_kong",
            source_ja="CANMAKE TOKYO",
            target_zh="CANMAKE TOKYO让赛",
        )
        self.term_clean = TermEntry.objects.create(
            term_type="race",
            source_language="en",
            racing_region="france",
            source_ja="Prix de l'Abbaye de Longchamp",
            target_zh="隆尚教堂大赛",
        )


class DryRunTests(HandicapCleanupDbMixin, TestCase):
    def test_dry_run_buckets_and_actions(self):
        report = cleanup.build_dry_run()
        self.assertEqual(report["schemaVersion"], "race-name-handicap-cleanup-dry-run.v2")
        actions = report["actions"]
        by_key = {(a["kind"], a["id"]): a for a in actions}
        self.assertEqual(
            by_key[("series", self.series_locked.id)]["after"]["chineseName"],
            "京成杯秋季赛",
        )
        self.assertEqual(
            by_key[("event", self.event_hk.id)]["after"]["chineseName"], "精英杯"
        )
        self.assertEqual(
            by_key[("term", self.term_specific.id)]["after"]["targetZh"], "雅士谷锦标"
        )
        self.assertEqual(
            by_key[("term", self.term_keisei.id)]["after"]["targetZh"], "京成杯秋季赛"
        )
        self.assertEqual(len(actions), 5)
        kept_ids = {(k["kind"], k["id"]) for k in report["kept"]}
        self.assertIn(("term", self.term_condition.id), kept_ids)
        self.assertIn(("term", self.term_latin.id), kept_ids)
        locked_ids = {(l["kind"], l["id"]) for l in report["locked"]}
        self.assertIn(("event", self.event_locked.id), locked_ids)
        self.assertNotIn(("series", self.series_clean.id), by_key)
        self.assertNotIn(("term", self.term_clean.id), by_key)
        self.assertEqual(report["counts"]["autoClean"], len(actions))
        self.assertTrue(report["contentSha256"])


class CommitTests(HandicapCleanupDbMixin, TransactionTestCase):
    def _context(self):
        return {
            "artifactSha256": "a" * 64,
            "backupSha256": "b" * 64,
            "backupSizeBytes": 12345,
            "operator": "mentianlu_via_codex",
            "authorizationRef": "user-test",
            "authorizationTime": "2026-07-21T00:00:00Z",
        }

    def _unlock_event(self):
        RaceEvent.objects.filter(id=self.event_locked.id).update(manual_lock_flags={})

    def test_commit_writes_only_auto_clean_and_logs_once(self):
        self._unlock_event()
        report = cleanup.build_dry_run()
        result = cleanup.execute_commit(report, audit_context=self._context())
        self.assertEqual(result["written"], 6)
        self.series_locked.refresh_from_db()
        self.event_hk.refresh_from_db()
        self.event_locked.refresh_from_db()
        self.term_specific.refresh_from_db()
        self.term_keisei.refresh_from_db()
        self.assertEqual(self.series_locked.chinese_name, "京成杯秋季赛")
        self.assertEqual(self.event_hk.chinese_name, "精英杯")
        self.assertEqual(self.event_locked.chinese_name, "锁定杯")
        self.assertEqual(self.term_specific.target_zh, "雅士谷锦标")
        self.assertEqual(self.term_keisei.target_zh, "京成杯秋季赛")
        self.term_condition.refresh_from_db()
        self.term_latin.refresh_from_db()
        self.assertEqual(self.term_condition.target_zh, "两岁马让赛")
        self.assertEqual(self.term_latin.target_zh, "CANMAKE TOKYO让赛")
        logs = OperationLog.objects.filter(
            action_type="race_name_handicap_markers_removed"
        )
        self.assertEqual(logs.count(), 1)
        detail = json.loads(logs.get().detail)
        self.assertEqual(detail["backupSha256"], "b" * 64)
        self.assertEqual(detail["counts"]["autoClean"], 6)

    def test_manual_lock_blocks_entire_commit(self):
        report = cleanup.build_dry_run()
        with self.assertRaisesRegex(cleanup.CleanupError, "manual lock"):
            cleanup.execute_commit(
                report,
                audit_context=self._context(),
            )
        self.series_locked.refresh_from_db()
        self.assertEqual(self.series_locked.chinese_name, "京成杯秋季让赛")
        self.assertEqual(
            OperationLog.objects.filter(
                action_type="race_name_handicap_markers_removed"
            ).count(),
            0,
        )

    def test_before_drift_rolls_back_everything(self):
        self._unlock_event()
        report = cleanup.build_dry_run()
        TermEntry.objects.filter(id=self.term_specific.id).update(target_zh="漂移值")
        with self.assertRaisesRegex(cleanup.CleanupError, "CAS"):
            cleanup.execute_commit(
                report,
                audit_context=self._context(),
            )
        self.series_locked.refresh_from_db()
        self.term_keisei.refresh_from_db()
        self.assertEqual(self.series_locked.chinese_name, "京成杯秋季让赛")
        self.assertEqual(self.term_keisei.target_zh, "京成杯秋季让赛")
        self.assertEqual(
            OperationLog.objects.filter(
                action_type="race_name_handicap_markers_removed"
            ).count(),
            0,
        )

    def test_repeated_commit_is_rejected(self):
        self._unlock_event()
        report = cleanup.build_dry_run()
        cleanup.execute_commit(
            report, audit_context=self._context()
        )
        with self.assertRaisesRegex(cleanup.CleanupError, "already applied"):
            cleanup.execute_commit(
                report, audit_context=self._context()
            )
        self.assertEqual(
            OperationLog.objects.filter(
                action_type="race_name_handicap_markers_removed"
            ).count(),
            1,
        )


class VerifyTests(HandicapCleanupDbMixin, TransactionTestCase):
    def test_verify_after_commit_and_drift_detection(self):
        RaceEvent.objects.filter(id=self.event_locked.id).update(manual_lock_flags={})
        report = cleanup.build_dry_run()
        cleanup.execute_commit(
            report,
            audit_context={
                "artifactSha256": "a" * 64,
                "backupSha256": "b" * 64,
                "backupSizeBytes": 12345,
                "operator": "mentianlu_via_codex",
                "authorizationRef": "user-test",
                "authorizationTime": "2026-07-21T00:00:00Z",
            },
        )
        outcome = cleanup.verify_applied(report)
        self.assertTrue(outcome["ok"])
        TermEntry.objects.filter(id=self.term_keisei.id).update(target_zh="被篡改")
        with self.assertRaisesRegex(cleanup.CleanupError, "verify"):
            cleanup.verify_applied(report)


class ManagementCommandTests(HandicapCleanupDbMixin, TransactionTestCase):
    def test_command_dry_run_commit_and_verify(self):
        from django.core.management import call_command

        RaceEvent.objects.filter(id=self.event_locked.id).update(manual_lock_flags={})
        import io
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            out = io.StringIO()
            call_command(
                "clean_race_name_handicap_markers",
                "--output-dir",
                directory,
                stdout=out,
            )
            summary = json.loads(out.getvalue())
            artifact = Path(summary["artifact"])
            self.assertTrue(artifact.is_file())
            self.assertTrue(Path(summary["reviewCsv"]).is_file())
            self.assertEqual(summary["counts"]["autoClean"], 6)

            out = io.StringIO()
            call_command(
                "clean_race_name_handicap_markers",
                "--commit",
                "--artifact",
                str(artifact),
                "--artifact-sha256",
                summary["artifactSha256"],
                "--backup-sha256",
                "c" * 64,
                "--backup-size-bytes",
                "999",
                "--authorization-ref",
                "user-test",
                "--authorization-time",
                "2026-07-21T00:00:00Z",
                stdout=out,
            )
            result = json.loads(out.getvalue())
            self.assertEqual(result["written"], 6)
            self.term_keisei.refresh_from_db()
            self.assertEqual(self.term_keisei.target_zh, "京成杯秋季赛")

            out = io.StringIO()
            call_command(
                "clean_race_name_handicap_markers",
                "--verify",
                "--artifact",
                str(artifact),
                "--artifact-sha256",
                summary["artifactSha256"],
                stdout=out,
            )
            self.assertTrue(json.loads(out.getvalue())["ok"])

    def test_command_rejects_tampered_artifact(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "dry-run.json"
            artifact.write_text("{}", encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command(
                    "clean_race_name_handicap_markers",
                    "--verify",
                    "--artifact",
                    str(artifact),
                    "--artifact-sha256",
                    "0" * 64,
                )

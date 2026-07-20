"""Tests for rolling P0 horse completion batch selection and manifest gates."""

from __future__ import annotations

import json
from pathlib import Path

from django.test import TestCase, override_settings

from stable.models import (
    HorseP0Source,
    HorseP0SourceStatus,
    HorseP0SourceType,
    HorseProfile,
    HorseProfileCompleteness,
    HorseProfileCompletionRun,
    RacingRegion,
    SourceLanguage,
    TermEntry,
    TermType,
)
from stable.services.p0_horse_completion_batch import (
    P0HorseBatchError,
    approve_batch_manifest,
    load_batch_manifest,
    select_p0_horse_batch,
    validate_approved_batch_manifest,
    write_batch_manifest,
)


class P0HorseBatchTestBase(TestCase):
    def _term(self, name: str, region: str = RacingRegion.JAPAN, **overrides):
        defaults = {
            "term_type": TermType.HORSE,
            "source_language": SourceLanguage.JAPANESE,
            "source_ja": name,
            "target_zh": "",
            "racing_region": region,
            "is_active": True,
        }
        defaults.update(overrides)
        return TermEntry.objects.create(**defaults)

    def _profile(self, name: str, region: str = RacingRegion.JAPAN, **overrides):
        term = overrides.pop("primary_term", None) or self._term(name, region)
        defaults = {
            "primary_term": term,
            "original_name": name,
            "racing_region": region,
        }
        defaults.update(overrides)
        return HorseProfile.objects.create(**defaults)

    def _p0_source(self, profile, region: str = RacingRegion.JAPAN, **overrides):
        defaults = {
            "profile": profile,
            "source_type": HorseP0SourceType.MAJOR_RACE_PARTICIPANT,
            "status": HorseP0SourceStatus.ACTIVE,
            "racing_region": region,
            "horse_name": profile.original_name,
            "participant_key": f"test:{profile.pk}",
            "source_url": "https://example.test/race/1",
        }
        defaults.update(overrides)
        return HorseP0Source.objects.create(**defaults)


class P0HorseBatchSelectionTests(P0HorseBatchTestBase):
    def test_select_fail_closed_without_scope_and_limit(self):
        with self.assertRaises(P0HorseBatchError):
            select_p0_horse_batch()

    def test_select_fail_closed_total_limit_exceeded(self):
        with self.assertRaises(P0HorseBatchError):
            select_p0_horse_batch(
                regions=[RacingRegion.JAPAN],
                limit_per_region=99999,
            )

    def test_select_defaults_to_region_batch_limit(self):
        for index in range(120):
            profile = self._profile(f"テスト馬{index:03d}")
            self._p0_source(profile)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        self.assertEqual(len(manifest["horses"]), 100)
        self.assertEqual(manifest["region_counts"][RacingRegion.JAPAN], 100)

    def test_select_excludes_complete_profile_full(self):
        complete = self._profile(
            "完成馬",
            completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL,
        )
        self._p0_source(complete)
        pending = self._profile("未完成馬")
        self._p0_source(pending)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        names = {horse["horse_name"] for horse in manifest["horses"]}
        self.assertIn("未完成馬", names)
        self.assertNotIn("完成馬", names)

    def test_select_include_complete_with_reason(self):
        complete = self._profile(
            "完成馬",
            completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL,
        )
        self._p0_source(complete)
        manifest = select_p0_horse_batch(
            regions=[RacingRegion.JAPAN],
            include_complete=True,
        )
        horse = next(h for h in manifest["horses"] if h["horse_name"] == "完成馬")
        self.assertIn("include_complete_override", horse["queue_reasons"])

    def test_select_excludes_in_flight_profiles(self):
        busy = self._profile("在批馬")
        self._p0_source(busy)
        HorseProfileCompletionRun.objects.create(
            status="running",
            parameters={"p0_batch": {"profile_ids": [busy.pk]}},
        )
        free = self._profile("空闲馬")
        self._p0_source(free)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        names = {horse["horse_name"] for horse in manifest["horses"]}
        self.assertIn("空闲馬", names)
        self.assertNotIn("在批馬", names)

    def test_select_allow_in_flight_records_reason(self):
        busy = self._profile("在批馬")
        self._p0_source(busy)
        HorseProfileCompletionRun.objects.create(
            status="running",
            parameters={"p0_batch": {"profile_ids": [busy.pk]}},
        )
        manifest = select_p0_horse_batch(
            regions=[RacingRegion.JAPAN],
            allow_in_flight=True,
        )
        horse = next(h for h in manifest["horses"] if h["horse_name"] == "在批馬")
        self.assertIn("allow_in_flight_override", horse["queue_reasons"])

    def test_candidate_conversion_identity_and_enrichment(self):
        identified = self._profile(
            "有身份马",
            source_refs={"horse_identity_keys": ["jbis:0001234567"]},
        )
        self._p0_source(
            identified,
            evidence_payload={"horse_identity_keys": ["jbis:0001234567", "netkeiba:2010100001"]},
        )
        unidentified = self._profile("无身份马")
        self._p0_source(unidentified)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        by_name = {horse["horse_name"]: horse for horse in manifest["horses"]}
        identified_row = by_name["有身份马"]
        self.assertEqual(identified_row["candidate_key"], f"profile:{identified.pk}")
        self.assertIn("jbis:0001234567", identified_row["identity_keys"])
        self.assertIn("netkeiba:2010100001", identified_row["identity_keys"])
        self.assertEqual(identified_row["source_namespace"], "jbis")
        self.assertNotIn("identity_status", identified_row)
        for url in identified_row["source_urls"]:
            self.assertNotIn("example.test/race", url)
        enrichment_row = by_name["无身份马"]
        self.assertEqual(enrichment_row["identity_status"], "needs_identity_enrichment")

    def test_candidate_conversion_birth_year_and_pedigree(self):
        import datetime

        profile = self._profile(
            "谱系马",
            birth_date=datetime.date(2020, 3, 15),
            sire_text="父马",
            dam_text="母马",
        )
        self._p0_source(profile)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        horse = manifest["horses"][0]
        self.assertEqual(horse["expected_birth_year"], 2020)
        self.assertEqual(horse["expected_sire_name"], "父马")
        self.assertEqual(horse["expected_dam_name"], "母马")

    def test_manifest_pending_shape(self):
        profile = self._profile("形状马")
        self._p0_source(profile)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN], operator="tester")
        self.assertEqual(manifest["schema_version"], "p0-horse-completion-batch.v1")
        self.assertEqual(manifest["status"], "pending")
        self.assertIsNone(manifest["approval"])
        self.assertEqual(manifest["created_by"], "tester")
        self.assertTrue(manifest["batch_id"].startswith("p0batch-"))
        horse = manifest["horses"][0]
        self.assertEqual(horse["queue_reasons"][0], "p0_source")
        self.assertEqual(horse["profile_id"], profile.pk)


@override_settings(HORSE_PROFILE_COMPLETION_BATCH_STATE_DIR=None)
class P0HorseBatchManifestTests(P0HorseBatchTestBase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        profile = self._profile("清单马")
        self._p0_source(profile)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        self.manifest_path = write_batch_manifest(manifest, state_dir=self.state_dir)

    def test_write_and_load_roundtrip(self):
        loaded = load_batch_manifest(self.manifest_path)
        self.assertEqual(loaded["status"], "pending")
        self.assertEqual(
            loaded["batch_sha256"],
            json.loads(self.manifest_path.read_text(encoding="utf-8"))["batch_sha256"],
        )
        self.assertEqual(self.manifest_path.parent.name, loaded["batch_id"])

    def test_load_rejects_tampered_manifest(self):
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        data["horses"][0]["horse_name"] = "被篡改马"
        self.manifest_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(P0HorseBatchError):
            load_batch_manifest(self.manifest_path)

    def test_validate_requires_approved(self):
        with self.assertRaises(P0HorseBatchError):
            validate_approved_batch_manifest(self.manifest_path)

    def test_approve_writes_approval_and_ledger(self):
        approved = approve_batch_manifest(
            self.manifest_path,
            reviewer="reviewer-a",
            note="抽样通过",
        )
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["approval"]["reviewer"], "reviewer-a")
        self.assertEqual(approved["approval"]["note"], "抽样通过")
        self.assertTrue(approved["approval"]["approved_at"])
        ledger_path = self.manifest_path.parent / "approvals_ledger.jsonl"
        ledger_entries = [
            json.loads(line)
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(ledger_entries), 1)
        self.assertEqual(ledger_entries[0]["event"], "batch_approved")
        self.assertEqual(ledger_entries[0]["reviewer"], "reviewer-a")
        self.assertEqual(ledger_entries[0]["batch_sha256"], approved["batch_sha256"])
        validated = validate_approved_batch_manifest(self.manifest_path)
        self.assertEqual(validated["batch_sha256"], approved["batch_sha256"])

    def test_validate_expected_sha_mismatch(self):
        approved = approve_batch_manifest(self.manifest_path, reviewer="reviewer-a")
        self.assertTrue(approved["batch_sha256"])
        with self.assertRaises(P0HorseBatchError):
            validate_approved_batch_manifest(
                self.manifest_path,
                expected_sha256="0" * 64,
            )

    def test_approve_requires_reviewer(self):
        with self.assertRaises(P0HorseBatchError):
            approve_batch_manifest(self.manifest_path, reviewer="")

    def test_approve_excluded_profiles_removed_from_horses(self):
        excluded_id = self.manifest_horse_profile_id()
        approved = approve_batch_manifest(
            self.manifest_path,
            reviewer="reviewer-a",
            excluded_profile_ids=[excluded_id],
            note="整匹排除",
        )
        self.assertEqual(approved["horses"], [])
        self.assertEqual(
            approved["approval"]["excluded_profile_ids"],
            [excluded_id],
        )

    def manifest_horse_profile_id(self) -> int:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))["horses"][0][
            "profile_id"
        ]


class P0HorseBatchCommandTests(P0HorseBatchTestBase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        profile = self._profile("命令马")
        self._p0_source(profile)

    def _call(self, *command_args) -> dict:
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        with self._state_dir_override():
            call_command("p0_horse_completion_batch", *command_args, "--json", stdout=out)
        text = out.getvalue()
        marker = text.rfind("\n{")
        payload = text[marker + 1 :] if marker != -1 else text
        return json.loads(payload)

    def _state_dir_override(self):
        return override_settings(
            HORSE_PROFILE_COMPLETION_BATCH_STATE_DIR=str(self.state_dir)
        )

    def test_select_approve_validate_roundtrip(self):
        selected = self._call("--select", "--regions", "japan")
        self.assertEqual(selected["status"], "pending")
        self.assertEqual(selected["horse_count"], 1)
        manifest_path = selected["manifest_path"]
        approved = self._call("--approve", manifest_path, "--reviewer", "reviewer-a")
        self.assertEqual(approved["status"], "approved")
        validated = self._call(
            "--validate",
            manifest_path,
            "--expected-sha256",
            approved["batch_sha256"],
        )
        self.assertEqual(validated["batch_sha256"], approved["batch_sha256"])

    def test_select_unbounded_rejected(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self._call("--select")

    def test_approve_requires_reviewer(self):
        from django.core.management.base import CommandError

        selected = self._call("--select", "--regions", "japan")
        with self.assertRaises(CommandError):
            self._call("--approve", selected["manifest_path"])

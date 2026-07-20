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
        validated = validate_approved_batch_manifest(
            self.manifest_path,
            expected_sha256=approved["batch_sha256"],
        )
        self.assertEqual(validated["batch_sha256"], approved["batch_sha256"])

    def test_validate_requires_explicit_expected_sha(self):
        approve_batch_manifest(self.manifest_path, reviewer="reviewer-a")
        with self.assertRaises(P0HorseBatchError):
            validate_approved_batch_manifest(self.manifest_path)

    def test_select_rejects_oversized_region_limit(self):
        with self.assertRaises(P0HorseBatchError):
            select_p0_horse_batch(
                regions=[RacingRegion.JAPAN],
                limit_per_region=101,
            )

    def test_approve_exclusion_writes_blocker_pool(self):
        excluded_id = self.manifest_horse_profile_id()
        approve_batch_manifest(
            self.manifest_path,
            reviewer="reviewer-a",
            excluded_profile_ids=[excluded_id],
            note="字段存疑",
        )
        pool_path = self.manifest_path.parent / "blocker_pool.jsonl"
        entries = [
            json.loads(line)
            for line in pool_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["profile_id"], excluded_id)
        self.assertEqual(entries[0]["reason"], "excluded_at_batch_approval")

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


class BatchRunStateTests(TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = Path(self._tmp.name) / "p0batch-abc123"

    def _candidate(self, **overrides):
        candidate = {
            "candidate_key": "profile:1",
            "region": "japan",
            "horse_name": "テスト馬",
            "identity_keys": ["jbis:0001"],
            "source_namespace": "jbis",
            "source_urls": ["https://www.jbis.or.jp/horse/0001/"],
            "expected_sire_name": "父",
            "expected_dam_name": "母",
            "expected_birth_year": 2020,
        }
        candidate.update(overrides)
        return candidate

    def test_write_read_roundtrip(self):
        from stable.services.p0_horse_completion_batch import BatchRunState

        state = BatchRunState.create(batch_id="p0batch-abc123", run_dir=self.run_dir)
        state.stage = "preparing"
        state.write()
        loaded = BatchRunState.read(self.run_dir)
        self.assertEqual(loaded.batch_id, "p0batch-abc123")
        self.assertEqual(loaded.stage, "preparing")
        self.assertEqual(loaded.candidate_states, {})
        self.assertEqual(loaded.resume_history, [])

    def test_input_fingerprint_stability(self):
        from stable.services.p0_horse_completion_batch import (
            candidate_input_fingerprint,
        )

        base = candidate_input_fingerprint(self._candidate())
        self.assertEqual(base, candidate_input_fingerprint(self._candidate()))
        changed = candidate_input_fingerprint(self._candidate(expected_sire_name="别的父"))
        self.assertNotEqual(base, changed)
        reordered = candidate_input_fingerprint(
            self._candidate(identity_keys=["jbis:0001", "netkeiba:2010"])
        )
        self.assertNotEqual(base, reordered)

    def test_resume_decision_matrix(self):
        from stable.services.p0_horse_completion_batch import (
            BatchRunState,
            candidate_input_fingerprint,
            plan_candidate_resume,
            record_candidate_success,
        )

        state = BatchRunState.create(batch_id="p0batch-abc123", run_dir=self.run_dir)
        candidate = self._candidate()
        output_file = self.run_dir / "staging" / "profile_1.json"
        output_file.parent.mkdir(parents=True)
        output_file.write_text('{"ok": true}', encoding="utf-8")
        record_candidate_success(state, candidate, outputs={"payload": output_file})
        decisions = plan_candidate_resume(state, [candidate])
        self.assertEqual(decisions[candidate["candidate_key"]]["action"], "skipped_unchanged")

        state.candidate_states[candidate["candidate_key"]]["status"] = "failed"
        decisions = plan_candidate_resume(state, [candidate])
        self.assertEqual(decisions[candidate["candidate_key"]]["action"], "retry_failed")

        state.candidate_states[candidate["candidate_key"]]["status"] = "succeeded"
        changed = self._candidate(expected_birth_year=2021)
        decisions = plan_candidate_resume(state, [changed])
        self.assertEqual(
            decisions[changed["candidate_key"]]["action"], "rerun_input_changed"
        )

        decisions = plan_candidate_resume(state, [self._candidate(candidate_key="profile:2")])
        self.assertEqual(decisions["profile:2"]["action"], "executed")

    def test_resume_output_drift_codes(self):
        from stable.services.p0_horse_completion_batch import (
            BatchRunState,
            candidate_input_fingerprint,
            plan_candidate_resume,
        )

        state = BatchRunState.create(batch_id="p0batch-abc123", run_dir=self.run_dir)
        candidate = self._candidate()
        missing = self.run_dir / "staging" / "gone.json"
        state.candidate_states[candidate["candidate_key"]] = {
            "status": "succeeded",
            "input_fingerprint": candidate_input_fingerprint(candidate),
            "outputs": {"payload": str(missing)},
        }
        decisions = plan_candidate_resume(state, [candidate])
        self.assertEqual(
            decisions[candidate["candidate_key"]]["action"], "rerun_output_missing"
        )

        missing.parent.mkdir(parents=True, exist_ok=True)
        missing.write_text('{"ok": true}', encoding="utf-8")
        decisions = plan_candidate_resume(state, [candidate])
        self.assertEqual(
            decisions[candidate["candidate_key"]]["action"], "rerun_output_unverified"
        )

        from stable.services.p0_horse_completion_batch import record_candidate_success

        record_candidate_success(state, candidate, outputs={"payload": missing})
        missing.write_text('{"ok": false, "changed": true}', encoding="utf-8")
        decisions = plan_candidate_resume(state, [candidate])
        self.assertEqual(
            decisions[candidate["candidate_key"]]["action"], "rerun_output_changed"
        )

    def test_record_success_and_failure(self):
        from stable.services.p0_horse_completion_batch import (
            BatchRunState,
            candidate_input_fingerprint,
            record_candidate_failure,
            record_candidate_success,
        )

        state = BatchRunState.create(batch_id="p0batch-abc123", run_dir=self.run_dir)
        candidate = self._candidate()
        output_file = self.run_dir / "staging" / "profile_1.json"
        output_file.parent.mkdir(parents=True)
        output_file.write_text('{"ok": true}', encoding="utf-8")
        record_candidate_success(state, candidate, outputs={"payload": output_file})
        entry = state.candidate_states[candidate["candidate_key"]]
        self.assertEqual(entry["status"], "succeeded")
        self.assertEqual(
            entry["input_fingerprint"], candidate_input_fingerprint(candidate)
        )
        self.assertEqual(len(entry["outputs"]["payload"]["sha256"]), 64)

        record_candidate_failure(state, candidate, error="http_error: HTTP 500")
        entry = state.candidate_states[candidate["candidate_key"]]
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["error"], "http_error: HTTP 500")

    def test_downstream_stages_invalidated_on_rerun(self):
        from stable.services.p0_horse_completion_batch import (
            BatchRunState,
            invalidate_downstream_stages,
        )

        state = BatchRunState.create(batch_id="p0batch-abc123", run_dir=self.run_dir)
        state.completed_stages = [
            "prepare",
            "artifact",
            "review:japan",
            "commit:japan",
        ]
        state.artifacts = {
            "artifact_dir": "/tmp/x",
            "bundle:japan": {"research_path": "/tmp/r.json"},
            "commit:japan": {"artifact_sha256": "abc"},
        }
        invalidate_downstream_stages(state, reran=True)
        self.assertEqual(state.completed_stages, ["prepare"])
        self.assertEqual(state.artifacts, {"artifact_dir": "/tmp/x"})
        invalidate_downstream_stages(state, reran=False)
        self.assertEqual(state.completed_stages, ["prepare"])

    def test_resume_history_appended(self):
        from stable.services.p0_horse_completion_batch import (
            BatchRunState,
            append_resume_history,
        )

        state = BatchRunState.create(batch_id="p0batch-abc123", run_dir=self.run_dir)
        append_resume_history(
            state,
            from_stage="preparing",
            decisions={"skipped_unchanged": 3, "retry_failed": 1},
        )
        self.assertEqual(len(state.resume_history), 1)
        entry = state.resume_history[0]
        self.assertEqual(entry["from_stage"], "preparing")
        self.assertEqual(entry["decisions"]["retry_failed"], 1)
        self.assertTrue(entry["started_at"])
        loaded = BatchRunState.read(self.run_dir)
        self.assertEqual(len(loaded.resume_history), 1)

    def test_abandon_requires_reason_and_preserves_evidence(self):
        from stable.services.p0_horse_completion_batch import (
            BatchRunState,
            P0HorseBatchError,
            abandon_batch_run,
        )

        state = BatchRunState.create(batch_id="p0batch-abc123", run_dir=self.run_dir)
        staging = self.run_dir / "staging" / "profile_1.json"
        staging.parent.mkdir(parents=True)
        staging.write_text('{"ok": true}', encoding="utf-8")
        with self.assertRaises(P0HorseBatchError):
            abandon_batch_run(state, reason="")
        abandon_batch_run(state, reason="批次构成有误，另起新批")
        self.assertEqual(state.stage, "abandoned")
        self.assertTrue(staging.exists())
        loaded = BatchRunState.read(self.run_dir)
        self.assertEqual(loaded.stage, "abandoned")
        self.assertEqual(loaded.errors[-1]["error"], "批次构成有误，另起新批")


class RequestBudgetToolTests(TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.budget_dir = Path(self._tmp.name)

    def test_check_request_budget_persists_count(self):
        import json as jsonlib

        from stable.services.p0_horse_completion_budget import load_race_event_request_budget_module

        check_request_budget = load_race_event_request_budget_module().check_request_budget

        artifact = self.budget_dir / "japan.json"
        check_request_budget(
            "https://www.jbis.or.jp/horse/0001/",
            artifact_path=artifact,
            max_requests=5,
            interval=0,
        )
        check_request_budget(
            "https://www.jbis.or.jp/horse/0002/",
            artifact_path=artifact,
            max_requests=5,
            interval=0,
        )
        state = jsonlib.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(state["request_count"], 2)

    def test_check_request_budget_limit_exceeded_fail_closed(self):
        import json as jsonlib

        from stable.services.p0_horse_completion_budget import (
            load_race_event_request_budget_module,
        )

        _budget_module = load_race_event_request_budget_module()
        RequestBudgetExceeded = _budget_module.RequestBudgetExceeded
        check_request_budget = _budget_module.check_request_budget

        artifact = self.budget_dir / "japan.json"
        check_request_budget(
            "https://www.jbis.or.jp/horse/0001/",
            artifact_path=artifact,
            max_requests=1,
            interval=0,
        )
        with self.assertRaises(RequestBudgetExceeded):
            check_request_budget(
                "https://www.jbis.or.jp/horse/0002/",
                artifact_path=artifact,
                max_requests=1,
                interval=0,
            )
        state = jsonlib.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "limit_exceeded")

    def test_check_request_budget_corrupted_artifact_fail_closed(self):
        from stable.services.p0_horse_completion_budget import (
            load_race_event_request_budget_module,
        )

        _budget_module = load_race_event_request_budget_module()
        RequestBudgetExceeded = _budget_module.RequestBudgetExceeded
        check_request_budget = _budget_module.check_request_budget

        artifact = self.budget_dir / "japan.json"
        artifact.write_text("not-json", encoding="utf-8")
        with self.assertRaises(RequestBudgetExceeded):
            check_request_budget(
                "https://www.jbis.or.jp/horse/0001/",
                artifact_path=artifact,
                max_requests=5,
                interval=0,
            )

    def test_host_interval_dir_derives_per_host_artifact(self):
        from stable.services.p0_horse_completion_budget import load_race_event_request_budget_module

        check_request_budget = load_race_event_request_budget_module().check_request_budget

        artifact = self.budget_dir / "japan.json"
        host_dir = self.budget_dir / "host-interval"
        check_request_budget(
            "https://www.jbis.or.jp/horse/0001/",
            artifact_path=artifact,
            max_requests=5,
            interval=0,
            host_interval_dir=host_dir,
        )
        check_request_budget(
            "https://db.netkeiba.com/horse/2010100001/",
            artifact_path=artifact,
            max_requests=5,
            interval=0,
            host_interval_dir=host_dir,
        )
        self.assertTrue((host_dir / "www.jbis.or.jp.json").exists())
        self.assertTrue((host_dir / "db.netkeiba.com.json").exists())

    def test_before_network_request_env_still_works(self):
        import json as jsonlib
        import os
        from unittest import mock

        from stable.services.p0_horse_completion_budget import (
            load_race_event_request_budget_module,
        )

        before_network_request = load_race_event_request_budget_module().before_network_request

        artifact = self.budget_dir / "race.json"
        with mock.patch.dict(
            os.environ,
            {
                "RACE_EVENT_CRAWL_MAX_REQUESTS": "3",
                "RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT": str(artifact),
            },
        ):
            before_network_request("https://example.com/race/1")
        state = jsonlib.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(state["request_count"], 1)


class P0HorseSourceRetryTests(TestCase):
    def _request(self, **overrides):
        from stable.services.p0_horse_completion_adapters import (
            P0HorseCompletionRequest,
        )

        defaults = {
            "candidate_key": "profile:1",
            "region": "japan",
            "horse_name": "テスト馬",
            "source_url": "https://www.jbis.or.jp/horse/0001234567/",
            "request_budget": 3,
            "batch_limit": 100,
        }
        defaults.update(overrides)
        return P0HorseCompletionRequest(**defaults)

    def _client(self, transport, **kwargs):
        from stable.services.p0_horse_completion_source_clients import (
            build_p0_horse_completion_source_client,
        )

        return build_p0_horse_completion_source_client(
            "japan",
            transport,
            **kwargs,
        )

    @override_settings(
        HORSE_PROFILE_COMPLETION_RETRY_MAX_ATTEMPTS=3,
        HORSE_PROFILE_COMPLETION_RETRY_BACKOFF_BASE_SECONDS=0,
    )
    def test_429_retried_then_succeeds(self):
        from unittest.mock import Mock

        transport = Mock()
        transport.get.side_effect = [
            Mock(status_code=429, text="", url="", headers={"Retry-After": "0"}),
            Mock(status_code=200, text="<html>ok</html>", url="", headers={}),
        ]
        ledger_calls = []
        client = self._client(
            transport,
            budget_hook=lambda url: ledger_calls.append(url),
        )
        response = client._get(
            "https://www.jbis.or.jp/horse/0001234567/",
            self._request(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(transport.get.call_count, 2)
        self.assertEqual(len(ledger_calls), 2)

    @override_settings(
        HORSE_PROFILE_COMPLETION_RETRY_MAX_ATTEMPTS=3,
        HORSE_PROFILE_COMPLETION_RETRY_BACKOFF_BASE_SECONDS=0,
    )
    def test_403_not_retried(self):
        from unittest.mock import Mock

        from stable.services.p0_horse_completion_source_clients import (
            P0HorseSourceBlocked,
        )

        transport = Mock()
        transport.get.return_value = Mock(
            status_code=403, text="", url="", headers={}
        )
        client = self._client(transport)
        with self.assertRaises(P0HorseSourceBlocked) as ctx:
            client._get("https://www.jbis.or.jp/horse/0001234567/", self._request())
        self.assertEqual(transport.get.call_count, 1)
        self.assertFalse(ctx.exception.transient)
        self.assertEqual(ctx.exception.status_code, 403)

    @override_settings(
        HORSE_PROFILE_COMPLETION_RETRY_MAX_ATTEMPTS=2,
        HORSE_PROFILE_COMPLETION_RETRY_BACKOFF_BASE_SECONDS=0,
    )
    def test_retry_exhaustion_raises_transient_error(self):
        from unittest.mock import Mock

        from stable.services.p0_horse_completion_source_clients import (
            P0HorseSourceBlocked,
        )

        transport = Mock()
        transport.get.side_effect = RuntimeError("connection reset")
        client = self._client(transport)
        with self.assertRaises(P0HorseSourceBlocked) as ctx:
            client._get("https://www.jbis.or.jp/horse/0001234567/", self._request())
        self.assertEqual(transport.get.call_count, 2)
        self.assertTrue(ctx.exception.transient)

    @override_settings(
        HORSE_PROFILE_COMPLETION_RETRY_MAX_ATTEMPTS=3,
        HORSE_PROFILE_COMPLETION_RETRY_BACKOFF_BASE_SECONDS=0,
    )
    def test_retry_does_not_consume_per_candidate_budget(self):
        from unittest.mock import Mock

        transport = Mock()
        transport.get.side_effect = [
            Mock(status_code=500, text="", url="", headers={}),
            Mock(status_code=500, text="", url="", headers={}),
            Mock(status_code=200, text="<html>ok</html>", url="", headers={}),
        ]
        client = self._client(transport)
        request = self._request(request_budget=1)
        response = client._get(
            "https://www.jbis.or.jp/horse/0001234567/",
            request,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client._request_count, 1)


class P0HorseBudgetLedgerTests(TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.budget_dir = Path(self._tmp.name)

    @override_settings(HORSE_PROFILE_COMPLETION_MAX_REQUESTS=10)
    def test_region_ledger_and_host_interval(self):
        import json as jsonlib

        from stable.services.p0_horse_completion_budget import (
            before_p0_horse_source_request,
        )

        before_p0_horse_source_request(
            "https://www.jbis.or.jp/horse/0001/",
            region="japan",
            budget_dir=self.budget_dir,
            interval=0,
        )
        before_p0_horse_source_request(
            "https://www.jbis.or.jp/horse/0002/",
            region="japan",
            budget_dir=self.budget_dir,
            interval=0,
        )
        ledger = jsonlib.loads(
            (self.budget_dir / "japan.json").read_text(encoding="utf-8")
        )
        self.assertEqual(ledger["request_count"], 2)
        self.assertTrue(
            (self.budget_dir / "host-interval" / "www.jbis.or.jp.json").exists()
        )

    @override_settings(HORSE_PROFILE_COMPLETION_MAX_REQUESTS=1)
    def test_region_ledger_limit_fail_closed(self):
        from stable.services.p0_horse_completion_budget import (
            before_p0_horse_source_request,
            load_race_event_request_budget_module,
        )

        RequestBudgetExceeded = load_race_event_request_budget_module().RequestBudgetExceeded

        before_p0_horse_source_request(
            "https://www.jbis.or.jp/horse/0001/",
            region="japan",
            budget_dir=self.budget_dir,
            interval=0,
        )
        with self.assertRaises(RequestBudgetExceeded):
            before_p0_horse_source_request(
                "https://www.jbis.or.jp/horse/0002/",
                region="japan",
                budget_dir=self.budget_dir,
                interval=0,
            )


class P0HorseBatchPrepareTests(P0HorseBatchTestBase):
    def setUp(self):
        import shutil
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.state_dir = root / "batches"
        self.cache_dir = root / "cache"
        import datetime

        self.profile = self._profile(
            "FOREVER TEST",
            sire_text="Japan Sire",
            dam_text="Japan Dam",
            birth_date=datetime.date(2021, 2, 24),
            source_refs={
                "horse_identity_keys": ["jbis:jp-001"],
                "horse_source_urls": ["https://example.test/jbis/horse/jp-001"],
            },
        )
        self._p0_source(self.profile)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        self.manifest_path = write_batch_manifest(manifest, state_dir=self.state_dir)
        self.approved = approve_batch_manifest(self.manifest_path, reviewer="reviewer-a")
        from stable.services.p0_horse_completion_adapters import (
            p0_horse_completion_cache_path,
        )

        fixture = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "p0_horse_completion"
            / "japan.json"
        )
        fixture_payload = json.loads(fixture.read_text(encoding="utf-8"))
        for record in fixture_payload["career"]["records"]:
            record.setdefault("source_name", "jbis")
        fixture_payload["career"]["records"][0]["race_date"] = "2023-11-05"
        cache_path = p0_horse_completion_cache_path(
            self.cache_dir, f"profile:{self.profile.pk}"
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(fixture_payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def _prepare(self, **overrides):
        from stable.services.p0_horse_completion_prepare import prepare_p0_horse_batch

        defaults = {
            "expected_sha256": self.approved["batch_sha256"],
            "allow_network": False,
            "cache_dir": self.cache_dir,
        }
        defaults.update(overrides)
        return prepare_p0_horse_batch(self.manifest_path, **defaults)

    def test_prepare_cache_only_success(self):
        summary = self._prepare()
        self.assertEqual(summary["totals"]["horses"], 1)
        self.assertEqual(summary["totals"]["succeeded"], 1)
        self.assertEqual(summary["totals"]["blocked"], 0)
        artifact_dir = self.manifest_path.parent / "artifact"
        combined = artifact_dir / "combined_candidates.jsonl"
        self.assertTrue(combined.exists())
        lines = combined.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["candidate_key"], f"profile:{self.profile.pk}")
        self.assertTrue((artifact_dir / "batch_review.csv").exists())
        self.assertTrue((artifact_dir / "summary.json").exists())
        self.assertTrue((artifact_dir / "source_evidence_manifest.jsonl").exists())
        from stable.services.p0_horse_completion_batch import BatchRunState

        state = BatchRunState.read(self.manifest_path.parent)
        self.assertIn("prepare", state.completed_stages)
        self.assertIn("artifact", state.completed_stages)
        candidate_state = state.candidate_states[f"profile:{self.profile.pk}"]
        self.assertEqual(candidate_state["status"], "succeeded")
        self.assertEqual(len(candidate_state["outputs"]["payload"]["sha256"]), 64)

    def test_prepare_requires_approved_manifest(self):
        pending_manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        pending_path = write_batch_manifest(pending_manifest, state_dir=self.state_dir / "other")
        from stable.services.p0_horse_completion_batch import P0HorseBatchError
        from stable.services.p0_horse_completion_prepare import prepare_p0_horse_batch

        with self.assertRaises(P0HorseBatchError):
            prepare_p0_horse_batch(
                pending_path,
                allow_network=False,
                cache_dir=self.cache_dir,
            )

    def test_prepare_expected_sha_mismatch(self):
        from stable.services.p0_horse_completion_batch import P0HorseBatchError

        with self.assertRaises(P0HorseBatchError):
            self._prepare(expected_sha256="0" * 64)

    def test_prepare_resume_skips_unchanged(self):
        from stable.services.p0_horse_completion_batch import BatchRunState

        self._prepare()
        staging_file = next((self.manifest_path.parent / "staging").glob("*.json"))
        first_bytes = staging_file.read_bytes()
        summary = self._prepare()
        self.assertEqual(summary["resume"]["skipped_unchanged"], 1)
        self.assertEqual(staging_file.read_bytes(), first_bytes)
        state = BatchRunState.read(self.manifest_path.parent)
        self.assertGreaterEqual(len(state.resume_history), 1)

    def test_prepare_blocked_when_cache_missing(self):
        other = self._profile("无缓存马")
        self._p0_source(other)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        manifest_path = write_batch_manifest(manifest, state_dir=self.state_dir / "batch2")
        approved = approve_batch_manifest(manifest_path, reviewer="reviewer-a")
        from stable.services.p0_horse_completion_prepare import prepare_p0_horse_batch

        summary = prepare_p0_horse_batch(
            manifest_path,
            expected_sha256=approved["batch_sha256"],
            allow_network=False,
            cache_dir=self.cache_dir,
        )
        self.assertEqual(summary["totals"]["horses"], 2)
        self.assertEqual(summary["totals"]["succeeded"], 1)
        self.assertEqual(summary["totals"]["blocked"], 1)
        combined = (manifest_path.parent / "artifact" / "combined_candidates.jsonl")
        payloads = [
            json.loads(line)
            for line in combined.read_text(encoding="utf-8").splitlines()
        ]
        blocked = next(p for p in payloads if p["candidate_key"] == f"profile:{other.pk}")
        self.assertIn("network_disabled_cache_missing", blocked["failure_reason"])

    def test_prepare_aborts_on_budget_exhaustion(self):
        from stable.services.p0_horse_completion_batch import (
            BatchRunState,
            P0HorseBatchError,
        )
        from stable.services.p0_horse_completion_budget import (
            load_race_event_request_budget_module,
        )

        no_cache = self._profile("触网马")
        self._p0_source(no_cache)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        manifest_path = write_batch_manifest(manifest, state_dir=self.state_dir / "batch3")
        approved = approve_batch_manifest(manifest_path, reviewer="reviewer-a")

        budget_error = load_race_event_request_budget_module().RequestBudgetExceeded

        class _ExhaustedClient:
            def fetch_source_payload(self, request):
                raise budget_error("budget exhausted: 1/1")

            def has_manual_supplements(self, request):
                return False

        from stable.services.p0_horse_completion_prepare import prepare_p0_horse_batch

        with self.assertRaises(P0HorseBatchError):
            prepare_p0_horse_batch(
                manifest_path,
                expected_sha256=approved["batch_sha256"],
                allow_network=True,
                cache_dir=self.cache_dir,
                source_client_factory=lambda region: _ExhaustedClient(),
            )
        state = BatchRunState.read(manifest_path.parent)
        self.assertEqual(state.stage, "prepare_failed")
        failed = state.candidate_states[f"profile:{no_cache.pk}"]
        self.assertEqual(failed["status"], "failed")


class P0HorseBatchResearchTests(P0HorseBatchPrepareTests):
    def _research(self, region=RacingRegion.JAPAN):
        from stable.services.p0_horse_completion_research import (
            build_region_research_v3,
        )

        self._prepare()
        return build_region_research_v3(
            self.manifest_path.parent / "artifact",
            region=region,
        )

    def test_converter_deterministic(self):
        first = self._research()
        second = self._research()
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True),
            json.dumps(second, ensure_ascii=False, sort_keys=True),
        )

    def test_research_v3_shape(self):
        research = self._research()
        self.assertEqual(research["schema_version"], "p0-horse-research.v3")
        self.assertEqual(len(research["horses"]), 1)
        horse = research["horses"][0]
        self.assertEqual(horse["region"], "japan")
        self.assertEqual(horse["identity"]["horse_name"], "FOREVER TEST")
        self.assertEqual(horse["identity"]["sire_name"], "Japan Sire")
        self.assertEqual(horse["identity"]["birth_year"], 2021)
        self.assertTrue(horse["source"]["url"].startswith("https://"))
        self.assertEqual(horse["source"]["external_horse_id"], "jp-001")
        self.assertEqual(horse["candidate"]["sample_region"], "japan")
        self.assertTrue(horse["source_evidence"])
        self.assertEqual(horse["basic_profile"]["owner_name"], "Japan Owner")
        self.assertEqual(horse["pedigree"]["sire"], "Japan Sire")
        self.assertEqual(len(horse["career"]["records"]), 4)
        self.assertEqual(horse["career"]["official_or_source_start_count"], 3)
        self.assertEqual(
            horse["career"]["record_authority_status"], "source_records_verified"
        )
        self.assertTrue(horse["aliases"])

    def test_converter_excludes_blocked_payloads(self):
        other = self._profile("无缓存马")
        self._p0_source(other)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        manifest_path = write_batch_manifest(manifest, state_dir=self.state_dir / "batch-blocked")
        approved = approve_batch_manifest(manifest_path, reviewer="reviewer-a")
        from stable.services.p0_horse_completion_prepare import prepare_p0_horse_batch
        from stable.services.p0_horse_completion_research import (
            build_region_research_v3,
        )

        prepare_p0_horse_batch(
            manifest_path,
            expected_sha256=approved["batch_sha256"],
            allow_network=False,
            cache_dir=self.cache_dir,
        )
        research = build_region_research_v3(
            manifest_path.parent / "artifact",
            region=RacingRegion.JAPAN,
        )
        names = {horse["identity"]["horse_name"] for horse in research["horses"]}
        self.assertIn("FOREVER TEST", names)
        self.assertNotIn("无缓存马", names)


class P0HorseBatchApprovalBundleTests(P0HorseBatchPrepareTests):
    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model

        self.reviewer = get_user_model().objects.create_user(
            username="p0-batch-reviewer",
            password="unused",
            is_superuser=True,
            is_staff=True,
        )
        self._prepare()

    def _bundle(self, **overrides):
        from stable.services.p0_horse_completion_research import (
            build_region_approval_bundle,
            build_region_research_v3,
            write_region_research,
        )

        research = build_region_research_v3(
            self.manifest_path.parent / "artifact",
            region=RacingRegion.JAPAN,
        )
        research_path, research_sha = write_region_research(
            research,
            output_dir=self.manifest_path.parent / "approval",
            region=RacingRegion.JAPAN,
        )
        defaults = {
            "research_path": research_path,
            "region": RacingRegion.JAPAN,
            "reviewer": self.reviewer,
            "output_dir": self.manifest_path.parent / "approval",
            "batch_dir": self.manifest_path.parent,
        }
        defaults.update(overrides)
        return build_region_approval_bundle(**defaults)

    def test_bundle_binds_existing_profile(self):
        bundle = self._bundle()
        self.assertEqual(bundle["mapping"]["schema_version"], "p0-horse-profile-mapping-decisions.v1")
        self.assertEqual(bundle["mapping"]["review_status"], "approved")
        self.assertEqual(bundle["mapping"]["research_v3_sha256"], bundle["research_sha256"])
        rows = bundle["mapping"]["rows"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["decision"], "bind_existing")
        self.assertEqual(row["profile_id"], self.profile.pk)
        self.assertEqual(row["rejected_profile_ids"], [])
        for module in ("profile", "pedigree", "race_record", "major_wins"):
            review = row["module_reviews"][module]
            self.assertEqual(review["status"], "approved")
            self.assertGreaterEqual(review["confidence"], 90)
        self.assertTrue(row["database_mapping_snapshot"]["sha256"])
        authority = bundle["authority"]
        self.assertEqual(authority["review_status"], "approved")
        self.assertEqual(authority["horses"], [])

    def test_bundle_us_horses_fail_closed_without_authorization(self):
        us_profile = self._profile(
            "US TEST",
            region=RacingRegion.UNITED_STATES,
            sire_text="US Sire",
            dam_text="US Dam",
        )
        us_profile.birth_date = __import__("datetime").date(2020, 1, 1)
        us_profile.save()
        self._p0_source(us_profile, region=RacingRegion.UNITED_STATES)
        from stable.services.p0_horse_completion_research import (
            P0HorseBatchError,
            build_region_approval_bundle,
            build_region_research_v3,
            write_region_research,
        )

        research = build_region_research_v3(
            self.manifest_path.parent / "artifact",
            region=RacingRegion.JAPAN,
        )
        research["horses"].append(
            {
                "identity": {
                    "horse_name": "US TEST",
                    "sire_name": "US Sire",
                    "dam_name": "US Dam",
                    "birth_year": 2020,
                },
                "region": "united_states",
                "source": {"name": "hrn", "url": "https://example.test/hrn/us-test", "external_horse_id": "us-1"},
                "candidate": {"sample_region": "united_states"},
                "source_evidence": [{"source_url": "https://example.test/hrn/us-test"}],
                "basic_profile": {},
                "pedigree": {},
                "aliases": [],
                "career": {"records": [], "record_authority_status": "source_records_verified"},
                "confidence": 100,
            }
        )
        research_path, _ = write_region_research(
            research,
            output_dir=self.manifest_path.parent / "approval",
            region=RacingRegion.JAPAN,
        )
        with self.assertRaises(P0HorseBatchError):
            build_region_approval_bundle(
                research_path=research_path,
                region=RacingRegion.JAPAN,
                reviewer=self.reviewer,
                output_dir=self.manifest_path.parent / "approval",
                batch_dir=self.manifest_path.parent,
            )

    def test_bundle_writes_ledger_entry(self):
        bundle = self._bundle()
        ledger_path = self.manifest_path.parent / "approvals_ledger.jsonl"
        events = [
            json.loads(line)
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        module_events = [e for e in events if e["event"] == "region_modules_approved"]
        self.assertEqual(len(module_events), 1)
        entry = module_events[0]
        self.assertEqual(entry["region"], "japan")
        self.assertEqual(entry["mapping_sha256"], bundle["mapping_sha256"])
        self.assertEqual(entry["reviewer"], self.reviewer.get_username())

    def test_bundle_feeds_existing_commit_chain_end_to_end(self):
        from stable.services.p0_horse_completion_research import (
            _write_canonical,
            build_region_release_manifest,
        )
        from stable.services.p0_horse_production_apply import (
            commit_reviewed_p0_completion_artifact,
            dry_run_reviewed_p0_completion_artifact,
            prepare_reviewed_p0_completion_artifact,
        )

        bundle = self._bundle()
        artifact = prepare_reviewed_p0_completion_artifact(
            research_v3_path=bundle["research_path"],
            authority_manifest_path=bundle["authority_path"],
            authority_manifest_sha256=bundle["authority_sha256"],
            profile_mapping_decisions_path=bundle["mapping_path"],
            reviewer_id=self.reviewer.id,
        )
        artifact_path = self.manifest_path.parent / "approval" / "commit_artifact_japan.json"
        artifact_sha = _write_canonical(artifact_path, artifact)
        release = build_region_release_manifest(
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha,
            bundle=bundle,
            reviewer=self.reviewer,
            approved_by="human-approver",
            batch_dir=self.manifest_path.parent,
            region=RacingRegion.JAPAN,
        )
        report = dry_run_reviewed_p0_completion_artifact(
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha,
            release_manifest_path=release["release_path"],
            release_manifest_sha256=release["release_sha256"],
        )
        self.assertGreater(
            report["planned_profile_updates"] + report["planned_race_record_creates"],
            0,
        )
        commit_reviewed_p0_completion_artifact(
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha,
            release_manifest_path=release["release_path"],
            release_manifest_sha256=release["release_sha256"],
            confirm_reviewed_artifact=True,
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.owner_name, "Japan Owner")
        self.assertEqual(self.profile.trainer_name, "Japan Trainer")
        verification = dry_run_reviewed_p0_completion_artifact(
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha,
            release_manifest_path=release["release_path"],
            release_manifest_sha256=release["release_sha256"],
        )
        self.assertEqual(verification["planned_profile_creates"], 0)
        self.assertEqual(verification["planned_profile_updates"], 0)
        self.assertEqual(verification["planned_race_record_creates"], 0)

    def test_release_manifest_without_ledger_entry_rejected(self):
        from stable.services.p0_horse_completion_research import (
            _write_canonical,
            build_region_release_manifest,
        )
        from stable.services.p0_horse_production_apply import (
            dry_run_reviewed_p0_completion_artifact,
            prepare_reviewed_p0_completion_artifact,
        )

        bundle = self._bundle()
        artifact = prepare_reviewed_p0_completion_artifact(
            research_v3_path=bundle["research_path"],
            authority_manifest_path=bundle["authority_path"],
            authority_manifest_sha256=bundle["authority_sha256"],
            profile_mapping_decisions_path=bundle["mapping_path"],
            reviewer_id=self.reviewer.id,
        )
        artifact_path = self.manifest_path.parent / "approval" / "commit_artifact_japan.json"
        artifact_sha = _write_canonical(artifact_path, artifact)
        release = build_region_release_manifest(
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha,
            bundle=bundle,
            reviewer=self.reviewer,
            approved_by="human-approver",
            batch_dir=self.manifest_path.parent,
            region=RacingRegion.JAPAN,
        )
        # remove the release_approved ledger line to simulate an unapproved channel
        ledger_path = self.manifest_path.parent / "approvals_ledger.jsonl"
        kept = [
            line
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
            if '"release_approved"' not in line
        ]
        ledger_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        with self.assertRaises(Exception) as ctx:
            dry_run_reviewed_p0_completion_artifact(
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha,
                release_manifest_path=release["release_path"],
                release_manifest_sha256=release["release_sha256"],
            )
        self.assertIn("ledger", str(ctx.exception))


class P0HorseBatchReviewWorkbookTests(P0HorseBatchPrepareTests):
    def test_workbook_sheets_and_exception_sampling(self):
        from openpyxl import load_workbook

        from stable.services.p0_horse_completion_batch import load_batch_manifest
        from stable.services.p0_horse_completion_review import (
            EXCEPTION_SHEET,
            SUMMARY_SHEET,
            build_batch_review_workbook,
        )

        self._prepare()
        manifest = load_batch_manifest(self.manifest_path)
        output = Path(self._tmp.name) / "review" / f"{manifest['batch_id']}.xlsx"
        build_batch_review_workbook(
            manifest=manifest,
            artifact_dir=self.manifest_path.parent / "artifact",
            output_path=output,
        )
        self.assertTrue(output.exists())
        workbook = load_workbook(output)
        self.assertIn(SUMMARY_SHEET, workbook.sheetnames)
        self.assertIn("日本", workbook.sheetnames)
        self.assertIn(EXCEPTION_SHEET, workbook.sheetnames)
        japan_sheet = workbook["日本"]
        self.assertEqual(japan_sheet.max_row, 2)
        header = [cell.value for cell in japan_sheet[1]]
        self.assertIn("马名", header)
        self.assertIn("生涯缺口", header)
        name_col = header.index("马名") + 1
        self.assertEqual(japan_sheet.cell(row=2, column=name_col).value, "FOREVER TEST")

    def test_workbook_lists_blocked_horse_in_exceptions(self):
        from openpyxl import load_workbook

        from stable.services.p0_horse_completion_batch import load_batch_manifest
        from stable.services.p0_horse_completion_prepare import prepare_p0_horse_batch
        from stable.services.p0_horse_completion_review import (
            EXCEPTION_SHEET,
            build_batch_review_workbook,
        )

        other = self._profile("无缓存马")
        self._p0_source(other)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        manifest_path = write_batch_manifest(manifest, state_dir=self.state_dir / "batch-review")
        approved = approve_batch_manifest(manifest_path, reviewer="reviewer-a")
        prepare_p0_horse_batch(
            manifest_path,
            expected_sha256=approved["batch_sha256"],
            allow_network=False,
            cache_dir=self.cache_dir,
        )
        output = Path(self._tmp.name) / "review" / "blocked.xlsx"
        build_batch_review_workbook(
            manifest=load_batch_manifest(manifest_path),
            artifact_dir=manifest_path.parent / "artifact",
            output_path=output,
        )
        workbook = load_workbook(output)
        sheet = workbook[EXCEPTION_SHEET]
        names = [sheet.cell(row=row, column=5).value for row in range(2, sheet.max_row + 1)]
        self.assertIn("无缓存马", names)
        self.assertNotIn("FOREVER TEST", names)


class P0HorseBatchCommandPipelineTests(P0HorseBatchPrepareTests):
    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model

        self.reviewer = get_user_model().objects.create_user(
            username="p0-pipeline-reviewer",
            password="unused",
            is_superuser=True,
            is_staff=True,
        )

    def _call(self, *command_args) -> dict:
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        with override_settings(
            HORSE_PROFILE_COMPLETION_BATCH_STATE_DIR=str(self.state_dir),
            HORSE_PROFILE_COMPLETION_CACHE_DIR=str(self.cache_dir),
            HORSE_PROFILE_COMPLETION_REVIEW_OUTPUT_DIR=str(
                Path(self._tmp.name) / "review"
            ),
        ):
            call_command("p0_horse_completion_batch", *command_args, "--json", stdout=out)
        text = out.getvalue()
        marker = text.rfind("\n{")
        payload = text[marker + 1 :] if marker != -1 else text
        return json.loads(payload)

    def test_full_pipeline_via_command(self):
        prepared = self._call(
            "--prepare",
            str(self.manifest_path),
            "--expected-sha256",
            self.approved["batch_sha256"],
        )
        self.assertEqual(prepared["totals"]["succeeded"], 1)
        self.assertTrue(Path(prepared["review_workbook"]).exists())

        bundled = self._call(
            "--bundle",
            str(self.manifest_path),
            "--region",
            "japan",
            "--reviewer-id",
            str(self.reviewer.id),
        )
        self.assertEqual(bundled["horse_count"], 1)

        committed = self._call(
            "--commit",
            str(self.manifest_path),
            "--region",
            "japan",
            "--reviewer-id",
            str(self.reviewer.id),
            "--approved-by",
            "human-approver",
            "--confirm-reviewed-artifact",
        )
        self.assertTrue(committed["idempotent_verification"]["passed"])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.owner_name, "Japan Owner")
        self.assertEqual(self.profile.completeness_status, "complete_profile_full")

        run = HorseProfileCompletionRun.objects.get(id=committed["completion_run_id"])
        self.assertEqual(
            run.parameters["p0_batch"]["profile_ids"], [self.profile.pk]
        )
        self.assertEqual(run.parameters["p0_batch"]["region"], "japan")
        self.assertTrue(run.summary["idempotent_verification"]["passed"])

    def test_commit_requires_confirm_flag(self):
        from django.core.management.base import CommandError

        self._call(
            "--prepare",
            str(self.manifest_path),
            "--expected-sha256",
            self.approved["batch_sha256"],
        )
        self._call(
            "--bundle",
            str(self.manifest_path),
            "--region",
            "japan",
            "--reviewer-id",
            str(self.reviewer.id),
        )
        with self.assertRaises(CommandError):
            self._call(
                "--commit",
                str(self.manifest_path),
                "--region",
                "japan",
                "--reviewer-id",
                str(self.reviewer.id),
                "--approved-by",
                "human-approver",
            )

    def test_prepare_network_flag_requires_setting(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self._call(
                "--prepare",
                str(self.manifest_path),
                "--expected-sha256",
                self.approved["batch_sha256"],
                "--allow-network",
            )

    def test_commit_rejects_stale_bundle_after_rerun(self):
        from stable.services.p0_horse_completion_batch import (
            BatchRunState,
            P0HorseBatchError,
        )
        from stable.services.p0_horse_completion_commit import (
            commit_p0_horse_batch_region,
        )

        self._call(
            "--prepare",
            str(self.manifest_path),
            "--expected-sha256",
            self.approved["batch_sha256"],
        )
        self._call(
            "--bundle",
            str(self.manifest_path),
            "--region",
            "japan",
            "--reviewer-id",
            str(self.reviewer.id),
        )
        # simulate a rerun that republished the combined artifact (new bytes)
        combined = self.manifest_path.parent / "artifact" / "combined_candidates.jsonl"
        combined.write_text(combined.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(P0HorseBatchError) as ctx:
            commit_p0_horse_batch_region(
                self.manifest_path,
                region="japan",
                reviewer=self.reviewer,
                approved_by="human-approver",
                state_dir=self.state_dir,
                confirm_reviewed_artifact=True,
            )
        self.assertIn("stale", str(ctx.exception))

    def test_commit_marks_manifest_committed_and_leaves_inflight(self):
        self.test_full_pipeline_via_command()
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "committed")
        selected = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        names = {horse["horse_name"] for horse in selected["horses"]}
        self.assertNotIn("FOREVER TEST", names)

    def test_abandon_command_marks_manifest_abandoned(self):
        self._call(
            "--prepare",
            str(self.manifest_path),
            "--expected-sha256",
            self.approved["batch_sha256"],
        )
        result = self._call(
            "--abandon",
            str(self.manifest_path),
            "--note",
            "批次构成有误",
        )
        self.assertEqual(result["status"], "abandoned")
        from stable.services.p0_horse_completion_batch import P0HorseBatchError
        from stable.services.p0_horse_completion_prepare import prepare_p0_horse_batch

        with self.assertRaises(P0HorseBatchError):
            prepare_p0_horse_batch(
                self.manifest_path,
                expected_sha256=self.approved["batch_sha256"],
                allow_network=False,
                cache_dir=self.cache_dir,
            )

    def test_prepare_blocked_payload_writes_blocker_pool(self):
        other = self._profile("无缓存马")
        self._p0_source(other)
        manifest = select_p0_horse_batch(regions=[RacingRegion.JAPAN])
        manifest_path = write_batch_manifest(manifest, state_dir=self.state_dir / "batch-pool")
        approved = approve_batch_manifest(manifest_path, reviewer="reviewer-a")
        from stable.services.p0_horse_completion_prepare import prepare_p0_horse_batch

        prepare_p0_horse_batch(
            manifest_path,
            expected_sha256=approved["batch_sha256"],
            allow_network=False,
            cache_dir=self.cache_dir,
        )
        pool_path = manifest_path.parent / "blocker_pool.jsonl"
        entries = [
            json.loads(line)
            for line in pool_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["horse_name"], "无缓存马")
        self.assertEqual(entries[0]["reason"], "blocked_at_prepare")

    def test_abandon_without_prepare_works(self):
        result = self._call(
            "--abandon",
            str(self.manifest_path),
            "--note",
            "选错批次",
        )
        self.assertEqual(result["status"], "abandoned")

    def test_recommit_with_changed_artifact_rejected_and_preserves_evidence(self):
        self.test_full_pipeline_via_command()
        from stable.services.p0_horse_completion_batch import (
            BatchRunState,
            P0HorseBatchError,
        )
        from stable.services.p0_horse_completion_commit import (
            commit_p0_horse_batch_region,
        )

        state = BatchRunState.read(self.manifest_path.parent)
        recorded_sha = state.artifacts["commit:japan"]["artifact_sha256"]
        artifact_path = (
            self.manifest_path.parent / "approval" / "commit_artifact_japan.json"
        )
        original_bytes = artifact_path.read_bytes()
        # simulate a tampered checkpoint recording a different committed SHA
        state.artifacts["commit:japan"]["artifact_sha256"] = "0" * 64
        state.write()
        with self.assertRaises(P0HorseBatchError):
            commit_p0_horse_batch_region(
                self.manifest_path,
                region="japan",
                reviewer=self.reviewer,
                approved_by="human-approver",
                state_dir=self.state_dir,
                confirm_reviewed_artifact=True,
            )
        self.assertEqual(artifact_path.read_bytes(), original_bytes)
        state = BatchRunState.read(self.manifest_path.parent)
        self.assertEqual(
            state.artifacts["commit:japan"]["artifact_sha256"], "0" * 64
        )
        self.assertNotEqual(recorded_sha, "0" * 64)

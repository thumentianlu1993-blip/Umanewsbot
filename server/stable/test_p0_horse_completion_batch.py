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
        state.completed_stages = ["prepare", "artifact", "review", "apply"]
        invalidate_downstream_stages(state, reran=True)
        self.assertEqual(state.completed_stages, ["prepare"])
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

"""Operations RED contracts for full-cohort enrollment and activation."""

from pathlib import Path
import subprocess
import sys

from django.core.management import get_commands
from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[3]
PROMOTE = ROOT / "deploy/promote_lifecycle_enforce_registry.sh"
SWITCH = ROOT / "deploy/switch_lifecycle_mode.sh"
COHERENCE = ROOT / "deploy/verify_lifecycle_runtime_coherence.sh"
ENV_EXAMPLE = ROOT / ".env.example"
PROMOTION_PARSER = ROOT / "deploy/parse_lifecycle_registry_promotion_result.py"
REGISTRY_METADATA_PARSER = ROOT / "deploy/parse_lifecycle_registry_artifact_metadata.py"


def _source(testcase: SimpleTestCase, path: Path) -> str:
    testcase.assertTrue(
        path.is_file(),
        f"目标能力缺失：尚未新增受审运维脚本 {path.relative_to(ROOT)}",
    )
    return path.read_text(encoding="utf-8")


class FullCohortOperationsContracts(SimpleTestCase):
    def _parse_registry_metadata(self, payload: str):
        self.assertTrue(
            REGISTRY_METADATA_PARSER.is_file(),
            "目标能力缺失：registry artifact metadata parser",
        )
        return subprocess.run(
            [sys.executable, str(REGISTRY_METADATA_PARSER)],
            input=payload,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_registry_metadata_parser_distinguishes_first_and_successor(self):
        first = self._parse_registry_metadata(
            '{"member_count":2,"predecessor_root_sha256":""}\n'
        )
        successor = self._parse_registry_metadata(
            '{"member_count":3,"predecessor_root_sha256":"' + "a" * 64 + '"}\n'
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), "2 first")
        self.assertEqual(successor.returncode, 0, successor.stderr)
        self.assertEqual(successor.stdout.strip(), f"3 successor {'a' * 64}")

    def test_registry_metadata_parser_rejects_invalid_predecessor(self):
        for payload in (
            '{"member_count":2}',
            '{"member_count":0,"predecessor_root_sha256":""}',
            '{"member_count":2,"predecessor_root_sha256":"abc"}',
            '{"member_count":2,"predecessor_root_sha256":"' + "A" * 64 + '"}',
            '{"member_count":2,"predecessor_root_sha256":null}',
            '{ "member_count":2,"predecessor_root_sha256":""}',
            '{"member_count":2,"member_count":3,"predecessor_root_sha256":""}',
        ):
            with self.subTest(payload=payload):
                self.assertNotEqual(self._parse_registry_metadata(payload).returncode, 0)

    def test_first_registry_requires_legacy_disarm_but_successor_forbids_it(self):
        source = _source(self, PROMOTE)
        self.assertIn('case "$registry_kind" in', source)
        self.assertIn("  first)", source)
        self.assertIn("  successor)", source)
        branch = source[source.index('case "$registry_kind" in') : source.index("read_key()")]
        self.assertIn("LEGACY_CANARY_APPROVED_COMMIT", branch)
        self.assertIn("verify_race_event_lifecycle_enforce_canary", source)
        canary_call = source.index("verify_race_event_lifecycle_enforce_canary")
        first_runtime_branch = source.rfind('if [ "$registry_kind" = "first" ]', 0, canary_call)
        self.assertGreaterEqual(first_runtime_branch, 0)
        self.assertNotIn(
            "LEGACY_MANIFEST_FILE LEGACY_MANIFEST_SHA256 LEGACY_CANARY_APPROVED_COMMIT",
            source[: source.index('case "$registry_kind" in')],
        )
        self.assertIn("successor registry forbids legacy", source)

    def _parse_promotion(self, line: str, *, total: int, previous: int):
        self.assertTrue(PROMOTION_PARSER.is_file(), "目标能力缺失：promotion canonical output parser")
        return subprocess.run(
            [sys.executable, str(PROMOTION_PARSER), "--expected-total", str(total), "--previous-remaining", str(previous)],
            input=line,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_promotion_parser_accepts_canonical_monotonic_batches_and_replay(self):
        first = self._parse_promotion(
            "outcome=partial batch_members=100 total=250 remaining=150\n",
            total=250,
            previous=250,
        )
        second = self._parse_promotion(
            "outcome=partial batch_members=100 total=250 remaining=50\n",
            total=250,
            previous=150,
        )
        terminal = self._parse_promotion(
            "outcome=applied batch_members=50 total=250 remaining=0\n",
            total=250,
            previous=50,
        )
        replay = self._parse_promotion(
            "outcome=replay batch_members=250 total=250 remaining=0\n",
            total=250,
            previous=250,
        )
        resumed = self._parse_promotion(
            "outcome=partial batch_members=100 total=250 remaining=50\n",
            total=250,
            previous=0,
        )
        for result in (first, second, terminal, replay, resumed):
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(terminal.stdout.strip(), "applied 0")
        self.assertEqual(replay.stdout.strip(), "replay 0")

    def test_promotion_parser_rejects_old_unknown_and_contradictory_output(self):
        invalid = (
            "outcome=partial members=100",
            "outcome=root batch_members=100 total=250 remaining=150",
            "outcome=partial batch_members=100 total=251 remaining=150",
            "outcome=partial batch_members=100 total=250 remaining=250",
            "outcome=partial batch_members=100 total=250 remaining=0",
            "outcome=applied batch_members=50 total=250 remaining=1",
            "outcome=replay batch_members=249 total=250 remaining=0",
            "outcome=applied batch_members=50 total=250 remaining=0\nextra",
        )
        for line in invalid:
            with self.subTest(line=line):
                result = self._parse_promotion(line + "\n", total=250, previous=250)
                self.assertNotEqual(result.returncode, 0)

    def test_prepare_promote_verify_commands_are_registered(self):
        commands = get_commands()
        expected = {
            "prepare_race_event_lifecycle_enforce_registry",
            "promote_race_event_lifecycle_enforce_registry",
            "verify_race_event_lifecycle_enforce_registry",
        }
        self.assertEqual(
            expected - set(commands),
            set(),
            "目标能力缺失：full-cohort prepare/promote/verify 命令未完整注册",
        )

    def test_runtime_root_is_declared_once_and_legacy_root_is_mutually_exclusive(self):
        env = _source(self, ENV_EXAMPLE)
        switch = _source(self, SWITCH)
        coherence = _source(self, COHERENCE)
        key_names = (
            "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256",
            "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256",
            "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT",
            "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID",
        )
        for key in key_names:
            self.assertEqual(
                sum(line.startswith(f"{key}=") for line in env.splitlines()),
                1,
                f"{key} must be declared exactly once",
            )
            self.assertIn(key, switch)
            self.assertIn(key, coherence)
        self.assertIn("RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256", switch)
        self.assertRegex(
            switch,
            r"(?s)CANARY_SHA256.*REGISTRY_SHA256|REGISTRY_SHA256.*CANARY_SHA256",
        )
        self.assertIn("false/off", coherence)

    def test_promotion_backs_up_before_env_clear_disarm_and_registry_write(self):
        source = _source(self, PROMOTE)
        tokens = (
            "backup_db.sh",
            "RACE_EVENT_LIFECYCLE_ENABLED=false",
            "--disarm",
            "promote_race_event_lifecycle_enforce_registry",
        )
        positions = []
        for token in tokens:
            self.assertIn(token, source)
            positions.append(source.index(token))
        self.assertEqual(
            positions,
            sorted(positions),
            "DB backup must precede env clear, legacy disarm and registry promotion",
        )
        self.assertNotIn(
            "migrate --noinput",
            source,
            "registry wrapper must not become a second Django migration owner",
        )
        self.assertIn("deployment_lock.sh", source)
        self.assertIn("lifecycle-enforce-registry-promotion", source)
        self.assertNotIn("race_live_worker", source)

    def test_legacy_canary_disarm_is_bound_to_its_frozen_approved_commit(self):
        source = _source(self, PROMOTE)
        self.assertIn("LEGACY_CANARY_APPROVED_COMMIT", source)
        self.assertRegex(
            source,
            r'--expected-commit "\$LEGACY_CANARY_APPROVED_COMMIT"[^\n]*--expected-event-ids',
        )
        canary_command = source[
            source.index("verify_race_event_lifecycle_enforce_canary") :
            source.index("promote_race_event_lifecycle_enforce_registry")
        ]
        self.assertNotIn('--expected-commit "$EXPECTED_RELEASE_COMMIT"', canary_command)

    def test_promotion_quiesces_lifecycle_writer_before_backup(self):
        source = _source(self, PROMOTE)
        main = source[source.index("# Quiesce the only lifecycle scheduler/consumer") :]
        stop_beat = main.find("stop beat")
        drain = main.find("wait_for_celery_drain.sh", stop_beat)
        stop_worker = main.find("stop worker", drain)
        backup = main.find('backup_output="$(BACKUP_TARGET', stop_worker)
        self.assertGreaterEqual(stop_beat, 0)
        self.assertGreater(drain, stop_beat)
        self.assertGreater(stop_worker, drain)
        self.assertGreater(backup, stop_worker)
        self.assertNotIn("|| true", main[stop_beat:backup])

    def test_any_backup_failure_stops_before_disarm_or_database_write(self):
        source = _source(self, PROMOTE)
        self.assertIn("set -eu", source)
        backup_index = source.index('backup_output="$(BACKUP_TARGET')
        disarm_index = source.index("--disarm")
        self.assertLess(backup_index, disarm_index)
        between = source[backup_index:disarm_index]
        self.assertNotIn("|| true", between)
        self.assertRegex(source, r"(?s)backup_db\.sh.*sha256")
        self.assertRegex(source, r"(?s)backup_db\.sh.*pg_restore")

    def test_promotion_recovery_requires_verified_off_before_lock_release(self):
        source = _source(self, PROMOTE)
        self.assertIn("recover_off()", source)
        recovery = source[source.index("recover_off()") : source.index("on_exit()")]
        self.assertIn("recovery_rc=0", recovery)
        self.assertIn('rewrite_off "$CANONICAL_ENV_FILE" || recovery_rc=1', recovery)
        self.assertIn('rewrite_off "$ACTIVE_RELEASE_ENV_FILE" || recovery_rc=1', recovery)
        self.assertIn("verify_off || recovery_rc=1", recovery)
        self.assertIn("keep_lock=1", recovery)
        on_exit = source[source.index("on_exit()") : source.index("export DEPLOYMENT_LOCK_ACTION")]
        self.assertIn('[ "$keep_lock" -eq 0 ]', on_exit)
        self.assertIn("manual recovery required", source)

    def test_activation_happens_before_beat_and_failure_converges_off(self):
        source = _source(self, SWITCH)
        activate = source.find("activate_race_event_lifecycle_enforce_registry")
        if activate < 0:
            activate = source.find("--activate-registry")
        self.assertGreaterEqual(
            activate, 0, "switch must activate the verified registry"
        )
        beat = source.find("up -d --no-deps --force-recreate beat", activate)
        self.assertGreater(beat, activate, "Beat must start only after activation")
        self.assertRegex(source, r"(?s)on_exit|trap")
        self.assertRegex(source, r"(?s)RACE_EVENT_LIFECYCLE_ENABLED=false.*RACE_EVENT_LIFECYCLE_MODE=off")

    def test_registry_activation_id_is_generated_and_activated_before_env_rewrite(self):
        source = _source(self, SWITCH)
        self.assertNotIn(
            "EXPECTED_REGISTRY_ACTIVATION_ID; do require",
            source,
            "caller must not have to predict the activation ID",
        )
        generate = source.find("generate_registry_activation_id")
        activate = source.find(
            'activate_race_event_lifecycle_enforce_registry "$registry_activation_id"'
        )
        rewrite = source.find('rewrite_env "$CANONICAL_ENV_FILE"')
        self.assertGreaterEqual(generate, 0, "switch must generate a fresh activation ID")
        self.assertGreater(activate, generate, "false/off resident must activate with that ID")
        self.assertGreater(rewrite, activate, "the same ID is written only after DB activation")
        self.assertIn('--activation-id "$registry_activation_id"', source)
        tail = source[rewrite:]
        self.assertNotIn(
            'activate_race_event_lifecycle_enforce_registry\n',
            tail,
            "recreated enforce web must verify, not generate a second activation",
        )

    def test_registry_enable_admits_reviewed_stopped_beat_and_keeps_beat_last(self):
        source = _source(self, SWITCH)
        self.assertIn("enable_admission_beat_state", source)
        admission = source.find("verify_runtime \"$enable_admission_beat_state\" false off")
        activate = source.find('registry_activation_id="$(resolve_registry_activation_id)"')
        beat = source.rfind("up -d --no-deps --force-recreate beat")
        self.assertGreaterEqual(admission, 0)
        self.assertGreater(activate, admission)
        self.assertGreater(beat, activate)

    def test_registry_retry_reuses_database_activation_id_for_same_artifact(self):
        source = _source(self, SWITCH)
        self.assertIn("resolve_registry_activation_id", source)
        self.assertIn("outcome=verified_active", source)
        self.assertIn("parse_registry_result_activation_id replay", source)
        self.assertRegex(
            source,
            r'(?s)resolve_registry_activation_id.*registry_activation_id=.*rewrite_env "\$CANONICAL_ENV_FILE"',
        )

    def test_caller_membership_root_is_checked_before_activation_and_final_verify(self):
        switch = _source(self, SWITCH)
        coherence = _source(self, COHERENCE)
        self.assertIn("validate_registry_artifact_roots", switch)
        validation = switch.find("validate_registry_artifact_roots")
        activation = switch.find('activate_race_event_lifecycle_enforce_registry "$registry_activation_id"')
        self.assertGreater(activation, validation)
        for key in (
            "EXPECTED_REGISTRY_MEMBERSHIP_SHA256",
            "EXPECTED_REGISTRY_MEMBER_COUNT",
            "EXPECTED_LIFECYCLE_ENFORCE_REGISTRY_MEMBERSHIP_SHA256",
            "EXPECTED_LIFECYCLE_ENFORCE_REGISTRY_MEMBER_COUNT",
            "EXPECTED_LIFECYCLE_ENFORCE_REGISTRY_ACTIVATION_ID",
        ):
            self.assertIn(key, switch)
            if key.startswith("EXPECTED_LIFECYCLE"):
                self.assertIn(key, coherence)

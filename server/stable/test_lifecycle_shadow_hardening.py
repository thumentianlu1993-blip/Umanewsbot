"""Load-bearing RED tests for lifecycle shadow observation hardening.

The shell tests execute the real repository entrypoints against fake host tools.
They never invoke Docker, touch production paths, or use the network.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from stable import models as stable_models
from stable.services import race_event_lifecycle
from stable.test_race_event_lifecycle import _apply, _make_control, _make_event


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "deploy/docker/compose-wrapper.sh"
COHERENCE = ROOT / "deploy/verify_lifecycle_runtime_coherence.sh"
MODE_SWITCH = ROOT / "deploy/switch_lifecycle_mode.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


class LifecycleShadowAttemptTests(TestCase):
    def test_shadow_proposal_is_recorded_as_success(self):
        race_dt = datetime(2026, 8, 8, 6, 0, tzinfo=dt_timezone.utc)
        event = _make_event(slug="shadow-success", race_datetime=race_dt)
        control = _make_control(event, mode="shadow")
        stable_models.RaceEventLifecycleControl.objects.filter(pk=control.pk).update(
            consecutive_failures=4,
            last_error="old-error",
        )
        now = race_dt

        result = _apply(event, now=now, mode="shadow")

        self.assertEqual(result.action, "proposed")
        control.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(control.last_attempt_at, now)
        self.assertEqual(control.last_success_at, now)
        self.assertEqual(control.last_result_code, "shadow_proposed")
        self.assertEqual(control.last_error, "")
        self.assertEqual(control.consecutive_failures, 0)
        self.assertEqual(event.status, "scheduled")
        self.assertEqual(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event, record_kind="proposal"
            ).count(),
            1,
        )

    def test_shadow_duplicate_is_idempotent_success(self):
        race_dt = datetime(2026, 8, 8, 6, 0, tzinfo=dt_timezone.utc)
        event = _make_event(slug="shadow-duplicate-success", race_datetime=race_dt)
        control = _make_control(event, mode="shadow")
        first = _apply(event, now=race_dt, mode="shadow")
        self.assertEqual(first.action, "proposed")
        stable_models.RaceEventLifecycleControl.objects.filter(pk=control.pk).update(
            consecutive_failures=7,
            last_error="stale-error",
            last_success_at=None,
        )
        second_now = race_dt + timedelta(seconds=1)

        second = _apply(event, now=second_now, mode="shadow")

        self.assertEqual(second.reason_code, "proposal_duplicate")
        control.refresh_from_db()
        self.assertEqual(control.last_success_at, second_now)
        self.assertEqual(control.last_result_code, "proposal_duplicate")
        self.assertEqual(control.last_error, "")
        self.assertEqual(control.consecutive_failures, 0)
        self.assertEqual(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event, record_kind="proposal"
            ).count(),
            1,
        )

    def test_real_decision_error_still_fails_and_backs_off(self):
        now = timezone.now()
        event = _make_event(
            slug="shadow-real-error",
            race_datetime=now - timedelta(minutes=1),
            timezone_name="Not/A-Timezone",
        )
        control = _make_control(event, mode="shadow", next_refresh_at=now)
        stable_models.RaceEventLifecycleControl.objects.filter(pk=control.pk).update(
            consecutive_failures=2,
        )

        result = _apply(event, now=now, mode="shadow")

        self.assertEqual(result.action, "error")
        control.refresh_from_db()
        self.assertEqual(control.last_result_code, "decision_error")
        self.assertEqual(control.consecutive_failures, 3)
        self.assertIsNone(control.last_success_at)
        self.assertGreater(control.next_refresh_at, now)
        self.assertFalse(
            stable_models.RaceEventLifecycleTransition.objects.filter(event=event).exists()
        )

    def test_proposal_duplicate_identity_conflicts_fail_closed(self):
        """A dedupe-key collision is success only for an identical proposal."""
        identity_mutations = (
            "event",
            "record_kind",
            "schedule_generation",
            "reason_code",
            "to_status",
            "from_status",
        )
        for index, mutation in enumerate(identity_mutations):
            with self.subTest(mutation=mutation):
                race_dt = datetime(2026, 8, 8, 6, 0, tzinfo=dt_timezone.utc)
                event = _make_event(
                    slug=f"shadow-collision-{index}", race_datetime=race_dt
                )
                other_event = _make_event(
                    slug=f"shadow-collision-other-{index}", race_datetime=race_dt
                )
                control = _make_control(event, mode="shadow", schedule_generation=3)
                stable_models.RaceEventLifecycleControl.objects.filter(
                    pk=control.pk
                ).update(consecutive_failures=5, last_error="prior-real-error")
                expected = {
                    "event": event,
                    "from_status": "scheduled",
                    "to_status": "running",
                    "reason_code": "time_reached_race_datetime",
                    "effective_at": race_dt,
                    "record_kind": "proposal",
                    "schedule_generation": 3,
                    "trigger_task": "advance_race_event_lifecycle_task",
                    "source_authority": "time_rule",
                    "dedupe_key": (
                        f"proposal:{event.id}:3:time_reached_race_datetime:running"
                    ),
                }
                replacements = {
                    "event": other_event,
                    "record_kind": "applied",
                    "schedule_generation": 99,
                    "reason_code": "wrong_reason",
                    "to_status": "finished",
                    "from_status": "running",
                }
                expected[mutation] = replacements[mutation]
                collision = stable_models.RaceEventLifecycleTransition.objects.create(
                    **expected
                )
                before_identity = stable_models.RaceEventLifecycleTransition.objects.filter(
                    pk=collision.pk
                ).values(
                    "event_id",
                    "record_kind",
                    "schedule_generation",
                    "reason_code",
                    "to_status",
                    "from_status",
                    "dedupe_key",
                ).get()

                result = _apply(event, expected_generation=3, now=race_dt, mode="shadow")

                self.assertEqual(result.action, "error")
                self.assertEqual(result.reason_code, "proposal_identity_conflict")
                control.refresh_from_db()
                self.assertEqual(control.last_result_code, "proposal_identity_conflict")
                self.assertTrue(control.last_error)
                self.assertEqual(control.consecutive_failures, 6)
                self.assertIsNone(control.last_success_at)
                self.assertEqual(
                    stable_models.RaceEventLifecycleTransition.objects.filter(
                        pk=collision.pk
                    ).values(
                        "event_id",
                        "record_kind",
                        "schedule_generation",
                        "reason_code",
                        "to_status",
                        "from_status",
                        "dedupe_key",
                    ).get(),
                    before_identity,
                )


class LifecycleRuntimeHandshakeTests(TestCase):
    control_fields = tuple(
        field.attname
        for field in stable_models.RaceEventLifecycleControl._meta.concrete_fields
    )

    def _snapshot(self, event, control):
        return {
            "event": stable_models.RaceEvent.objects.filter(pk=event.pk)
            .values("status", "updated_at")
            .get(),
            "control": stable_models.RaceEventLifecycleControl.objects.filter(pk=control.pk)
            .values(*self.control_fields)
            .get(),
            "transitions": stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event
            ).count(),
        }

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=True,
        RACE_EVENT_LIFECYCLE_MODE="shadow",
        RACE_EVENT_LIFECYCLE_CLAIM_TTL_SECONDS=240,
    )
    def test_scanner_dispatches_expected_runtime_configuration(self):
        event = _make_event(
            slug="scanner-runtime-expectation",
            race_datetime=timezone.now() - timedelta(minutes=1),
        )
        _make_control(event, mode="shadow", next_refresh_at=timezone.now())

        with patch("stable.tasks.advance_race_event_lifecycle_task.apply_async") as dispatch:
            from stable.tasks import scan_due_race_event_lifecycle_task

            with self.captureOnCommitCallbacks(execute=True):
                result = scan_due_race_event_lifecycle_task()

        self.assertEqual(result["claimed"], 1)
        kwargs = dispatch.call_args.kwargs["kwargs"]
        self.assertIs(kwargs["expected_runtime_enabled"], True)
        self.assertEqual(kwargs["expected_runtime_mode"], "shadow")
        self.assertEqual(
            dispatch.call_args.kwargs.get("queue", "celery"),
            "celery",
        )

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_runtime_mismatch_logs_and_performs_zero_business_writes(self):
        now = timezone.now()
        event = _make_event(
            slug="worker-runtime-mismatch",
            race_datetime=now - timedelta(minutes=1),
        )
        control = _make_control(event, mode="shadow", next_refresh_at=now)
        stable_models.RaceEventLifecycleControl.objects.filter(pk=control.pk).update(
            claim_token="scanner-token",
            claim_generation=4,
            claim_expires_at=now + timedelta(seconds=240),
        )
        control.refresh_from_db()
        before = self._snapshot(event, control)

        from stable.tasks import advance_race_event_lifecycle_task

        with self.assertLogs("stable.tasks", level="ERROR") as captured, patch(
            "stable.services.race_event_lifecycle.apply_race_lifecycle_decision"
        ) as apply_decision:
            result = advance_race_event_lifecycle_task(
                event_id=event.id,
                expected_generation=control.schedule_generation,
                attempt_token=control.claim_token,
                expected_claim_generation=control.claim_generation,
                expected_runtime_enabled=True,
                expected_runtime_mode="shadow",
            )

        self.assertEqual(
            result,
            {
                "processed": False,
                "reason": "lifecycle_runtime_config_mismatch",
                "event_id": event.id,
            },
        )
        apply_decision.assert_not_called()
        self.assertEqual(self._snapshot(event, control), before)
        joined = "\n".join(captured.output)
        for value in (
            "lifecycle_runtime_config_mismatch",
            str(event.id),
            "shadow",
            "off",
        ):
            self.assertIn(value, joined)

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=True,
        RACE_EVENT_LIFECYCLE_MODE="shadow",
    )
    def test_matching_runtime_processes_normally(self):
        now = timezone.now()
        event = _make_event(
            slug="worker-runtime-match",
            race_datetime=now - timedelta(minutes=1),
        )
        control = _make_control(event, mode="shadow", next_refresh_at=now)

        from stable.tasks import advance_race_event_lifecycle_task

        result = advance_race_event_lifecycle_task(
            event_id=event.id,
            expected_generation=control.schedule_generation,
            attempt_token="",
            expected_claim_generation=0,
            expected_runtime_enabled=True,
            expected_runtime_mode="shadow",
        )

        self.assertTrue(result["processed"])
        self.assertEqual(result["action"], "proposed")

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=True,
        RACE_EVENT_LIFECYCLE_MODE="shadow",
    )
    def test_legacy_message_without_runtime_expectations_remains_compatible(self):
        now = timezone.now()
        event = _make_event(
            slug="legacy-lifecycle-message",
            race_datetime=now - timedelta(minutes=1),
        )
        control = _make_control(event, mode="shadow", next_refresh_at=now)

        from stable.tasks import advance_race_event_lifecycle_task

        result = advance_race_event_lifecycle_task(
            event_id=event.id,
            expected_generation=control.schedule_generation,
            attempt_token="",
            expected_claim_generation=0,
        )

        self.assertTrue(result["processed"])

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
        RACE_EVENT_LIFECYCLE_CLAIM_TTL_SECONDS=240,
    )
    def test_mismatch_claim_ttl_reclaim_and_stale_message_isolation(self):
        now = timezone.now()
        event = _make_event(
            slug="runtime-mismatch-reclaim",
            race_datetime=now - timedelta(minutes=1),
        )
        control = _make_control(event, mode="shadow", next_refresh_at=now)
        old_claim = race_event_lifecycle.claim_due_lifecycle_controls(
            now=now, batch_size=10, ttl_seconds=240
        )[0]

        from stable.tasks import advance_race_event_lifecycle_task

        with self.assertLogs("stable.tasks", level="ERROR") as captured:
            mismatch = advance_race_event_lifecycle_task(
                event_id=event.id,
                expected_generation=old_claim.schedule_generation,
                attempt_token=old_claim.attempt_token,
                expected_claim_generation=old_claim.claim_generation,
                expected_runtime_enabled=True,
                expected_runtime_mode="shadow",
            )
        self.assertEqual(mismatch["reason"], "lifecycle_runtime_config_mismatch")
        self.assertEqual(
            sum("lifecycle_runtime_config_mismatch" in line for line in captured.output),
            1,
        )
        self.assertEqual(
            race_event_lifecycle.claim_due_lifecycle_controls(
                now=now + timedelta(seconds=239), batch_size=10, ttl_seconds=240
            ),
            [],
        )
        new_claim = race_event_lifecycle.claim_due_lifecycle_controls(
            now=now + timedelta(seconds=241), batch_size=10, ttl_seconds=240
        )[0]
        self.assertNotEqual(new_claim.attempt_token, old_claim.attempt_token)
        self.assertGreater(new_claim.claim_generation, old_claim.claim_generation)

        with override_settings(
            RACE_EVENT_LIFECYCLE_ENABLED=True,
            RACE_EVENT_LIFECYCLE_MODE="shadow",
        ):
            stale = advance_race_event_lifecycle_task(
                event_id=event.id,
                expected_generation=old_claim.schedule_generation,
                attempt_token=old_claim.attempt_token,
                expected_claim_generation=old_claim.claim_generation,
                expected_runtime_enabled=True,
                expected_runtime_mode="shadow",
            )
            fresh = advance_race_event_lifecycle_task(
                event_id=event.id,
                expected_generation=new_claim.schedule_generation,
                attempt_token=new_claim.attempt_token,
                expected_claim_generation=new_claim.claim_generation,
                expected_runtime_enabled=True,
                expected_runtime_mode="shadow",
            )

        self.assertIn(stale["action"], ("claim_not_expired", "claim_generation_mismatch"))
        self.assertEqual(fresh["action"], "proposed")
        control.refresh_from_db()
        self.assertEqual(control.claim_token, "")
        self.assertIsNone(control.claim_expires_at)
        self.assertEqual(control.consecutive_failures, 0)
        self.assertEqual(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event, record_kind="proposal"
            ).count(),
            1,
        )


FAKE_WRAPPER_DOCKER = r"""#!/bin/sh
set -eu
printf '%s\n' "$*" >> "${FAKE_DOCKER_LOG:?}"
if [ "${1:-}" = "compose" ] && [ "${2:-}" = "version" ]; then exit 0; fi
exit 0
"""


class ComposeWrapperCanonicalGrammarTests(SimpleTestCase):
    def _run(self, *args: str):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / "docker"
            log = root / "docker.log"
            _write_executable(fake, FAKE_WRAPPER_DOCKER)
            result = subprocess.run(
                ["sh", str(WRAPPER), *args],
                text=True,
                capture_output=True,
                check=False,
                env={
                    **os.environ,
                    "PATH": f"{root}{os.pathsep}/usr/bin:/bin",
                    "FAKE_DOCKER_LOG": str(log),
                },
            )
            calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
            return result, calls

    def assert_rejected_before_compose(self, *args: str):
        result, calls = self._run(*args)
        self.assertNotEqual(result.returncode, 0, (result.stdout, result.stderr, calls))
        self.assertEqual(calls, ["compose version"])

    def test_run_requires_rm_then_no_deps(self):
        self.assert_rejected_before_compose("run", "--rm", "web", "echo", "--no-deps")

    def test_command_argv_no_deps_does_not_satisfy_run_contract(self):
        self.assert_rejected_before_compose(
            "run", "--rm", "web", "python", "manage.py", "check", "--no-deps"
        )

    def test_release_b_repeated_env_options_are_preserved(self):
        args = (
            "-f", "docker-compose.prod.yml", "run", "--rm", "--no-deps",
            "-e", "A=B", "-e", "C=D", "web", "python", "manage.py", "check",
        )
        result, calls = self._run(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1], "compose " + " ".join(args))

    def test_file_equals_global_option_is_preserved(self):
        args = (
            "--file=docker-compose.prod.yml", "run", "--rm", "--no-deps",
            "--env=A=B", "web", "echo", "ok",
        )
        result, calls = self._run(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1], "compose " + " ".join(args))

    def test_unknown_or_ambiguous_global_options_fail_closed(self):
        cases = (
            ("--ansi", "never", "run", "--rm", "--no-deps", "web"),
            ("--foo=run", "run", "--rm", "--no-deps", "web"),
            ("-f",),
            ("--", "run", "--rm", "--no-deps", "web"),
        )
        for args in cases:
            with self.subTest(args=args):
                self.assert_rejected_before_compose(*args)

    def test_unknown_or_missing_run_options_fail_closed(self):
        cases = (
            ("run", "--rm", "--no-deps", "--mystery", "web"),
            ("run", "--rm", "--no-deps", "-e"),
            ("run", "--rm", "--no-deps", "--"),
        )
        for args in cases:
            with self.subTest(args=args):
                self.assert_rejected_before_compose(*args)

    def test_allowlisted_globals_and_non_run_commands_pass_through(self):
        for args in (
            ("-f", "prod.yml", "ps"),
            ("--project-name", "umanews", "config"),
            ("--project-directory=/srv/release", "exec", "-T", "web", "true"),
            ("--env-file", ".env", "up", "-d", "web"),
            ("--profile", "ops", "ps"),
        ):
            with self.subTest(args=args):
                result, calls = self._run(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls[-1], "compose " + " ".join(args))


FAKE_CENSUS_DOCKER = r"""#!/bin/sh
set -eu
printf '%s\n' "$*" >> "${FAKE_CENSUS_LOG:?}"
state="${FAKE_CENSUS_STATE:?}"
if [ "${1:-}" = "ps" ]; then
  cat "$state/ps"
  exit 0
fi
if [ "${1:-}" = "inspect" ]; then
  cid=""
  format=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --format) format="$2"; shift 2 ;;
      --format=*) format="${1#*=}"; shift ;;
      -*) shift ;;
      *) cid="$1"; shift ;;
    esac
  done
  meta="$state/meta-$cid"
  envf="$state/env-$cid"
  [ -f "$meta" ] || exit 1
  IFS='|' read -r running restarting image service project oneoff workdir commit < "$meta"
  case "$format" in
    *State.Running*State.Restarting*) printf '%s %s\n' "$running" "$restarting" ;;
    *State.Running*) printf '%s\n' "$running" ;;
    *State.Restarting*) printf '%s\n' "$restarting" ;;
    *Config.Env*) cat "$envf" ;;
    *com.docker.compose.service*) printf '%s\n' "$service" ;;
    *com.docker.compose.project.working_dir*) printf '%s\n' "$workdir" ;;
    *com.docker.compose.project*) printf '%s\n' "$project" ;;
    *com.docker.compose.oneoff*) printf '%s\n' "$oneoff" ;;
    *Image*) printf '%s\n' "$image" ;;
    *) cat "$meta" ;;
  esac
  exit 0
fi
if [ "${1:-}" = "image" ] && [ "${2:-}" = "inspect" ]; then
  image=""
  for arg in "$@"; do image="$arg"; done
  for meta in "$state"/meta-*; do
    IFS='|' read -r running restarting candidate service project oneoff workdir commit < "$meta"
    if [ "$candidate" = "$image" ]; then printf '%s\n' "$commit"; exit 0; fi
  done
  exit 1
fi
exit 91
"""


class CoherenceHarness:
    def __init__(self, base: Path):
        self.base = base
        self.state = base / "state"
        self.state.mkdir()
        self.bin = base / "bin"
        self.bin.mkdir()
        self.log = base / "docker.log"
        _write_executable(self.bin / "docker", FAKE_CENSUS_DOCKER)
        self.services = {
            "web": "cid-web",
            "worker": "cid-worker",
            "beat": "cid-beat",
        }
        self.seed()

    def seed(self):
        rows = []
        for service, cid in self.services.items():
            self.set_container(cid, service=service)
            rows.append(f"{cid}|{service}|umanews|False|/srv/release")
        (self.state / "ps").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def set_container(
        self,
        cid: str,
        *,
        service: str,
        project: str = "umanews",
        oneoff: str = "False",
        workdir: str = "/srv/release",
        image: str = "sha256:good",
        commit: str = "a" * 40,
        running: str = "true",
        restarting: str = "false",
        env_lines: str = (
            "RACE_EVENT_LIFECYCLE_ENABLED=true\n"
            "RACE_EVENT_LIFECYCLE_MODE=shadow\n"
            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=\n"
            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=\n"
            "SECRET_MUST_NOT_LEAK=hunter2\n"
        ),
    ):
        (self.state / f"meta-{cid}").write_text(
            "|".join(
                (running, restarting, image, service, project, oneoff, workdir, commit)
            )
            + "\n",
            encoding="utf-8",
        )
        (self.state / f"env-{cid}").write_text(env_lines, encoding="utf-8")

    def run(self, **overrides):
        if not COHERENCE.exists():
            return None
        env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}/usr/bin:/bin",
            "FAKE_CENSUS_LOG": str(self.log),
            "FAKE_CENSUS_STATE": str(self.state),
            "COMPOSE_FILE": "docker-compose.prod.yml",
            "EXPECTED_LIFECYCLE_ENABLED": "true",
            "EXPECTED_LIFECYCLE_MODE": "shadow",
            "EXPECTED_COMPOSE_PROJECT": "umanews",
            "EXPECTED_RELEASE_DIR": "/srv/release",
            "EXPECTED_IMAGE_ID": "sha256:good",
            "EXPECTED_RELEASE_COMMIT": "a" * 40,
            "EXPECTED_BEAT_STATE": "running",
        }
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(
            ["sh", str(COHERENCE)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )


class LifecycleRuntimeCoherenceContractTests(SimpleTestCase):
    def _harness(self, base: Path) -> CoherenceHarness:
        self.assertTrue(COHERENCE.is_file(), "missing lifecycle runtime coherence script")
        return CoherenceHarness(base)

    def _assert_read_only_docker_calls(self, harness: CoherenceHarness):
        calls = harness.log.read_text(encoding="utf-8").splitlines()
        self.assertTrue(calls, "coherence script did not perform a host census")
        for call in calls:
            self.assertTrue(
                call.startswith(("ps ", "inspect ", "image inspect ")),
                f"coherence script issued a mutating or unsupported Docker call: {call}",
            )

    def test_matching_host_wide_runtime_passes_without_secret_output(self):
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            result = harness.run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("hunter2", result.stdout + result.stderr)

    def test_false_off_treats_absent_canary_keys_as_empty_during_bootstrap(self):
        env_lines = (
            "RACE_EVENT_LIFECYCLE_ENABLED=false\n"
            "RACE_EVENT_LIFECYCLE_MODE=off\n"
        )
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            for service, cid in harness.services.items():
                harness.set_container(cid, service=service, env_lines=env_lines)
            result = harness.run(
                EXPECTED_LIFECYCLE_ENABLED="false",
                EXPECTED_LIFECYCLE_MODE="off",
                EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256="",
                EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS="",
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_duplicate_cross_project_worker_and_oneoff_fail_closed(self):
        for oneoff in ("False", "True"):
            with self.subTest(oneoff=oneoff), TemporaryDirectory() as temporary:
                harness = self._harness(Path(temporary))
                harness.set_container(
                    "cid-rogue",
                    service="worker",
                    project="old-project",
                    oneoff=oneoff,
                    workdir="/opt/umanewsbot",
                )
                with (harness.state / "ps").open("a", encoding="utf-8") as stream:
                    stream.write(
                        f"cid-rogue|worker|old-project|{oneoff}|/opt/umanewsbot\n"
                    )
                result = harness.run()
                self.assertNotEqual(result.returncode, 0)
                self._assert_read_only_docker_calls(harness)

    def test_wrong_image_commit_directory_or_flags_fail_closed(self):
        mutations = (
            {"image": "sha256:old"},
            {"commit": "b" * 40},
            {"workdir": "/opt/umanewsbot"},
            {"env_lines": "RACE_EVENT_LIFECYCLE_ENABLED=false\nRACE_EVENT_LIFECYCLE_MODE=off\n"},
            {"env_lines": "RACE_EVENT_LIFECYCLE_ENABLED=true\nRACE_EVENT_LIFECYCLE_MODE=shadow\nRACE_EVENT_LIFECYCLE_MODE=shadow\n"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), TemporaryDirectory() as temporary:
                harness = self._harness(Path(temporary))
                harness.set_container("cid-worker", service="worker", **mutation)
                result = harness.run()
                self.assertNotEqual(result.returncode, 0)
                self._assert_read_only_docker_calls(harness)

    def test_missing_or_stopped_beat_and_inspect_failure_fail_closed(self):
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            rows = (harness.state / "ps").read_text(encoding="utf-8").splitlines()
            (harness.state / "ps").write_text(
                "\n".join(row for row in rows if "|beat|" not in row) + "\n",
                encoding="utf-8",
            )
            result = harness.run()
            self.assertNotEqual(result.returncode, 0)
            self._assert_read_only_docker_calls(harness)
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            (harness.state / "meta-cid-worker").unlink()
            result = harness.run()
            self.assertNotEqual(result.returncode, 0)
            self._assert_read_only_docker_calls(harness)

    def test_expected_beat_stopped_allows_only_web_and_worker(self):
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            rows = (harness.state / "ps").read_text(encoding="utf-8").splitlines()
            (harness.state / "ps").write_text(
                "\n".join(row for row in rows if "|beat|" not in row) + "\n",
                encoding="utf-8",
            )
            result = harness.run(EXPECTED_BEAT_STATE="stopped")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_expected_production_inputs_are_required(self):
        required = (
            "COMPOSE_FILE",
            "EXPECTED_LIFECYCLE_ENABLED",
            "EXPECTED_LIFECYCLE_MODE",
            "EXPECTED_COMPOSE_PROJECT",
            "EXPECTED_RELEASE_DIR",
            "EXPECTED_IMAGE_ID",
            "EXPECTED_RELEASE_COMMIT",
            "EXPECTED_BEAT_STATE",
        )
        for key in required:
            with self.subTest(key=key), TemporaryDirectory() as temporary:
                harness = self._harness(Path(temporary))
                result = harness.run(**{key: None})
                self.assertNotEqual(result.returncode, 0)
                calls = (
                    harness.log.read_text(encoding="utf-8") if harness.log.exists() else ""
                )
                self.assertEqual(calls, "", f"{key} was checked after Docker access")


FAKE_SWITCH_LOCK = r"""#!/bin/sh
set -eu
printf 'lock %s %s\n' "${DEPLOYMENT_LOCK_ACTION:-}" "$*" >> "${FAKE_SWITCH_LOG:?}"
if [ "${1:-}" = "acquire" ] && [ "${FAKE_LOCK_FAIL:-0}" = "1" ]; then exit 1; fi
exit 0
"""

FAKE_SWITCH_COMPOSE = r"""#!/bin/sh
set -eu
printf 'compose %s\n' "$*" >> "${FAKE_SWITCH_LOG:?}"
if [ -n "${FAKE_COMPOSE_FAIL_MATCH:-}" ] && printf '%s' "$*" | grep -F "${FAKE_COMPOSE_FAIL_MATCH}" >/dev/null; then
  marker="${FAKE_SWITCH_STATE:?}/compose-failed"
  if [ ! -f "$marker" ]; then : > "$marker"; exit 1; fi
fi
exit 0
"""

FAKE_SWITCH_VERIFY = r"""#!/bin/sh
set -eu
printf 'verify %s %s\n' "${EXPECTED_BEAT_STATE:-}" "${EXPECTED_LIFECYCLE_MODE:-}" >> "${FAKE_SWITCH_LOG:?}"
count_file="${FAKE_SWITCH_STATE:?}/verify-count"
count=0
if [ -f "$count_file" ]; then count="$(cat "$count_file")"; fi
count=$((count + 1)); printf '%s\n' "$count" > "$count_file"
case ",${FAKE_VERIFY_FAIL_AT:-}," in *",$count,"*) exit 1 ;; esac
if [ -f "${FAKE_SWITCH_STATE:?}/host-offenders" ]; then
  while IFS= read -r offender; do
    [ -n "$offender" ] || continue
    if [ ! -f "${FAKE_SWITCH_STATE:?}/host-stopped-$offender" ] \
      && { { [ "${EXPECTED_LIFECYCLE_MODE:-}" = "shadow" ] \
          && [ "${EXPECTED_BEAT_STATE:-}" = "running" ]; } \
        || { [ "${EXPECTED_LIFECYCLE_MODE:-}" = "off" ] \
          && [ "$count" -gt 3 ]; }; }; then
      exit 1
    fi
  done < "${FAKE_SWITCH_STATE:?}/host-offenders"
fi
exit 0
"""

FAKE_SWITCH_DOCKER = r"""#!/bin/sh
set -eu
printf 'docker %s\n' "$*" >> "${FAKE_SWITCH_LOG:?}"
state="${FAKE_SWITCH_STATE:?}"
command="${1:-}"
if [ "$#" -gt 0 ]; then shift; fi
case "$command" in
  ps)
    [ "${FAKE_HOST_PS_FAIL:-0}" = "0" ] || exit 1
    if [ -f "$state/host-cids" ]; then
      while IFS= read -r cid; do
        [ -n "$cid" ] || continue
        [ -f "$state/host-stopped-$cid" ] || printf '%s\n' "$cid"
      done < "$state/host-cids"
    fi
    ;;
  inspect)
    format=""
    cid=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --format) format="$2"; shift 2 ;;
        --format=*) format="${1#*=}"; shift ;;
        -*) shift ;;
        *) cid="$1"; shift ;;
      esac
    done
    [ -n "$cid" ] || exit 1
    [ "${FAKE_HOST_INSPECT_FAIL_CID:-}" != "$cid" ] || exit 1
    meta="$state/host-meta-$cid"
    [ -f "$meta" ] || exit 1
    IFS='|' read -r service project oneoff running workdir image revision < "$meta"
    case "$format" in
      *com.docker.compose.service*com.docker.compose.project*com.docker.compose.oneoff*com.docker.compose.project.working_dir*)
        printf '%s|%s|%s|%s\n' "$service" "$project" "$oneoff" "$workdir" ;;
      *com.docker.compose.service*com.docker.compose.project*com.docker.compose.oneoff*)
        printf '%s|%s|%s\n' "$service" "$project" "$oneoff" ;;
      *com.docker.compose.service*) printf '%s\n' "$service" ;;
      *com.docker.compose.project.working_dir*) printf '%s\n' "$workdir" ;;
      *com.docker.compose.project*) printf '%s\n' "$project" ;;
      *com.docker.compose.oneoff*) printf '%s\n' "$oneoff" ;;
      *State.Running*) printf '%s\n' "$running" ;;
      *Image*) printf '%s\n' "$image" ;;
      *) printf '%s|%s|%s|%s|%s|%s|%s\n' "$service" "$project" "$oneoff" "$running" "$workdir" "$image" "$revision" ;;
    esac
    ;;
  image)
    [ "${1:-}" = "inspect" ] || exit 1
    shift
    format=""
    image=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --format) format="$2"; shift 2 ;;
        --format=*) format="${1#*=}"; shift ;;
        -*) shift ;;
        *) image="$1"; shift ;;
      esac
    done
    [ -n "$image" ] || exit 1
    for meta in "$state"/host-meta-*; do
      [ -f "$meta" ] || continue
      IFS='|' read -r service project oneoff running workdir candidate revision < "$meta"
      if [ "$candidate" = "$image" ]; then printf '%s\n' "$revision"; exit 0; fi
    done
    exit 1
    ;;
  stop)
    [ "$#" -eq 1 ] || exit 93
    cid="$1"
    [ "${FAKE_HOST_STOP_FAIL_CID:-}" != "$cid" ] || exit 1
    [ -f "$state/host-meta-$cid" ] || exit 1
    : > "$state/host-stopped-$cid"
    ;;
  *) exit 92 ;;
esac
"""


class ModeSwitchHarness:
    def __init__(
        self,
        base: Path,
        *,
        enabled: str = "false",
        mode: str = "off",
        detached_release: bool = False,
    ):
        self.base = base
        self.repo = base / "repo"
        self.deploy = self.repo / "deploy"
        (self.deploy / "docker").mkdir(parents=True)
        self.state = base / "state"
        self.state.mkdir()
        self.log = base / "calls.log"
        self.bin = base / "bin"
        self.bin.mkdir()
        self.release = base / "release" if detached_release else self.repo
        if detached_release:
            self.release.mkdir()
        self.canonical = base / "canonical.env"
        self.release_env = self.release / ".env"
        self._write_env(self.canonical, enabled, mode)
        self._write_env(self.release_env, enabled, mode)
        if MODE_SWITCH.exists():
            switch_copy = self.deploy / "switch_lifecycle_mode.sh"
            switch_text = MODE_SWITCH.read_text(encoding="utf-8")
            # Production must hard-code the canonical path.  The copied test
            # entrypoint substitutes only that reviewed literal, never a
            # production environment-variable bypass.
            switch_text = switch_text.replace(
                "/opt/umanewsbot/.env", str(self.canonical)
            )
            _write_executable(switch_copy, switch_text)
        _write_executable(self.deploy / "deployment_lock.sh", FAKE_SWITCH_LOCK)
        _write_executable(self.deploy / "docker/compose-wrapper.sh", FAKE_SWITCH_COMPOSE)
        _write_executable(
            self.deploy / "verify_lifecycle_runtime_coherence.sh", FAKE_SWITCH_VERIFY
        )
        _write_executable(self.bin / "docker", FAKE_SWITCH_DOCKER)
        (self.state / "host-cids").write_text("", encoding="utf-8")

    @staticmethod
    def _write_env(path: Path, enabled: str, mode: str):
        path.write_text(
            "KEEP_ME=unchanged\n"
            f"RACE_EVENT_LIFECYCLE_ENABLED={enabled}\n"
            f"RACE_EVENT_LIFECYCLE_MODE={mode}\n"
            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=\n"
            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=\n",
            encoding="utf-8",
        )
        path.chmod(0o600)

    def env(self, *, target_enabled: str, target_mode: str, **overrides):
        env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}/usr/bin:/bin",
            "ACTIVE_RELEASE_ENV_FILE": str(self.release_env),
            "COMPOSE_FILE": "docker-compose.prod.yml",
            "EXPECTED_COMPOSE_PROJECT": "umanews",
            "EXPECTED_RELEASE_DIR": str(self.release),
            "EXPECTED_IMAGE_ID": "sha256:good",
            "EXPECTED_RELEASE_COMMIT": "a" * 40,
            "TARGET_LIFECYCLE_ENABLED": target_enabled,
            "TARGET_LIFECYCLE_MODE": target_mode,
            "DEPLOYMENT_LOCK_DIR": str(self.base / "lock"),
            "DEPLOYMENT_LOCK_TOKEN": "test-high-entropy-token-0123456789abcdef",
            "FAKE_SWITCH_LOG": str(self.log),
            "FAKE_SWITCH_STATE": str(self.state),
        }
        # Compatibility only while demonstrating RED against the vulnerable
        # implementation, which has no hard-coded production trust root yet.
        # Once the production literal exists, this key is intentionally absent.
        if "/opt/umanewsbot/.env" not in MODE_SWITCH.read_text(encoding="utf-8"):
            env["CANONICAL_ENV_FILE"] = str(self.canonical)
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def seed_host_cleanup_scenario(
        self,
        *,
        offender_service: str,
        offender_project: str,
        offender_oneoff: str,
        offender_running: str = "true",
        offender_workdir: str | None = None,
        offender_image: str = "sha256:good",
        offender_revision: str = "a" * 40,
    ) -> tuple[str, str]:
        offender = "cid-offender"
        unrelated = "cid-unrelated"
        trusted_old_release = self.base / "umanews-release-old"
        trusted_old_release.mkdir(exist_ok=True)
        if offender_workdir is None:
            offender_workdir = str(trusted_old_release)
        (self.state / "host-cids").write_text(
            f"{offender}\n{unrelated}\n", encoding="utf-8"
        )
        (self.state / "host-offenders").write_text(
            f"{offender}\n", encoding="utf-8"
        )
        (self.state / f"host-meta-{offender}").write_text(
            f"{offender_service}|{offender_project}|{offender_oneoff}|"
            f"{offender_running}|{offender_workdir}|{offender_image}|"
            f"{offender_revision}\n",
            encoding="utf-8",
        )
        (self.state / f"host-meta-{unrelated}").write_text(
            f"nginx|umanews|False|true|{self.repo}|sha256:good|{'a' * 40}\n",
            encoding="utf-8",
        )
        return offender, unrelated

    def run(self, *, target_enabled: str, target_mode: str, **overrides):
        script = self.deploy / "switch_lifecycle_mode.sh"
        return subprocess.run(
            ["sh", str(script)],
            cwd=self.repo,
            env=self.env(
                target_enabled=target_enabled, target_mode=target_mode, **overrides
            ),
            text=True,
            capture_output=True,
            check=False,
        )

    def lines(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    @staticmethod
    def lifecycle_values(path: Path):
        values = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("RACE_EVENT_LIFECYCLE_"):
                key, value = line.split("=", 1)
                values[key] = value
        return values


class LifecycleModeSwitchContractTests(SimpleTestCase):
    def _harness(self, base: Path, **kwargs) -> ModeSwitchHarness:
        self.assertTrue(MODE_SWITCH.is_file(), "missing lifecycle mode switch script")
        return ModeSwitchHarness(base, **kwargs)

    def _parse_bound_compose_mutation(
        self,
        line: str,
        *,
        expected_dir: str,
        expected_project: str = "umanews",
        expected_file: str = "docker-compose.prod.yml",
    ) -> tuple[str, list[str]]:
        """Parse a fake Compose call and prove identity globals precede command."""
        tokens = shlex.split(line)
        self.assertEqual(tokens[:1], ["compose"], line)
        index = 1
        globals_seen: dict[str, str] = {}
        allowed = {"--project-directory", "--project-name", "-f"}
        while index < len(tokens) and tokens[index] in allowed:
            option = tokens[index]
            self.assertNotIn(option, globals_seen, f"duplicate global option: {line}")
            self.assertLess(index + 1, len(tokens), f"missing global option value: {line}")
            globals_seen[option] = tokens[index + 1]
            index += 2
        self.assertLess(index, len(tokens), f"missing Compose subcommand: {line}")
        self.assertEqual(
            globals_seen,
            {
                "--project-directory": expected_dir,
                "--project-name": expected_project,
                "-f": expected_file,
            },
            f"all identity globals must occur before subcommand: {line}",
        )
        return tokens[index], tokens[index + 1 :]

    def test_lock_contention_causes_zero_compose_and_zero_file_writes(self):
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            before = (harness.canonical.read_bytes(), harness.release_env.read_bytes())
            result = harness.run(
                target_enabled="true", target_mode="shadow", FAKE_LOCK_FAIL="1"
            )
            after = (harness.canonical.read_bytes(), harness.release_env.read_bytes())
            calls = harness.lines()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, after)
        self.assertTrue(calls and calls[0].startswith("lock lifecycle-mode-switch acquire"))
        self.assertFalse(any(line.startswith(("compose ", "verify ")) for line in calls))
        self.assertFalse(any(" release" in line for line in calls))

    def test_old_checkout_cannot_mutate_a_different_physical_release(self):
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary), detached_release=True)
            before = (harness.canonical.read_bytes(), harness.release_env.read_bytes())
            result = harness.run(target_enabled="true", target_mode="shadow")
            after = (harness.canonical.read_bytes(), harness.release_env.read_bytes())
            calls = harness.lines()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, after)
        self.assertEqual(
            calls,
            [],
            "release-directory identity must be rejected before lock or service access",
        )

    def test_enable_preflight_verifies_running_false_off_before_any_mutation(self):
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            before = (harness.canonical.read_bytes(), harness.release_env.read_bytes())
            result = harness.run(
                target_enabled="true",
                target_mode="shadow",
                FAKE_VERIFY_FAIL_AT="1",
            )
            after = (harness.canonical.read_bytes(), harness.release_env.read_bytes())
            calls = harness.lines()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, after)
        self.assertTrue(calls[0].startswith("lock lifecycle-mode-switch acquire"), calls)
        self.assertIn("verify running off", calls)
        self.assertFalse(any(line.startswith("compose ") for line in calls), calls)
        self.assertTrue(calls[-1].startswith("lock lifecycle-mode-switch release"), calls)

    def test_every_compose_mutation_is_bound_to_expected_project_identity(self):
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            result = harness.run(target_enabled="true", target_mode="shadow")
            calls = harness.lines()
            expected_dir = str(harness.release)
        self.assertEqual(result.returncode, 0, result.stderr)
        mutations = [line for line in calls if line.startswith("compose ")]
        self.assertTrue(mutations)
        for line in mutations:
            subcommand, _args = self._parse_bound_compose_mutation(
                line, expected_dir=expected_dir
            )
            self.assertIn(subcommand, ("stop", "up"), line)

    def test_production_canonical_env_is_a_non_overridable_trust_root(self):
        source = MODE_SWITCH.read_text(encoding="utf-8")
        self.assertIn(
            'CANONICAL_ENV_FILE="/opt/umanewsbot/.env"',
            source,
            "production script must own the canonical env path instead of accepting it",
        )
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            malicious = harness.base / "attacker-selected.env"
            harness._write_env(malicious, "false", "off")
            malicious_before = malicious.read_bytes()
            result = harness.run(
                target_enabled="true",
                target_mode="shadow",
                CANONICAL_ENV_FILE=str(malicious),
            )
            canonical_values = harness.lifecycle_values(harness.canonical)
            malicious_after = malicious.read_bytes()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            canonical_values,
            {
                "RACE_EVENT_LIFECYCLE_ENABLED": "true",
                "RACE_EVENT_LIFECYCLE_MODE": "shadow",
                "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256": "",
                "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS": "",
            },
        )
        self.assertEqual(malicious_before, malicious_after)

    def test_invalid_env_properties_reject_before_stopping_beat(self):
        mutations = ("mode", "duplicate", "symlink")
        for mutation in mutations:
            with self.subTest(mutation=mutation), TemporaryDirectory() as temporary:
                harness = self._harness(Path(temporary))
                if mutation == "mode":
                    harness.release_env.chmod(0o644)
                elif mutation == "duplicate":
                    with harness.release_env.open("a", encoding="utf-8") as stream:
                        stream.write("RACE_EVENT_LIFECYCLE_MODE=off\n")
                else:
                    target = harness.base / "symlink-target"
                    target.write_bytes(harness.release_env.read_bytes())
                    target.chmod(0o600)
                    harness.release_env.unlink()
                    harness.release_env.symlink_to(target)
                result = harness.run(target_enabled="true", target_mode="shadow")
                calls = harness.lines()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(line.startswith("compose ") for line in calls))

    def test_enable_success_uses_beat_last_and_releases_lock(self):
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            result = harness.run(target_enabled="true", target_mode="shadow")
            calls = harness.lines()
            values = (
                harness.lifecycle_values(harness.canonical),
                harness.lifecycle_values(harness.release_env),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values[0], values[1])
        self.assertEqual(
            values[0],
            {
                "RACE_EVENT_LIFECYCLE_ENABLED": "true",
                "RACE_EVENT_LIFECYCLE_MODE": "shadow",
                "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256": "",
                "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS": "",
            },
        )
        expected_dir = str(harness.release)
        compose_events: list[tuple[int, str, list[str]]] = []
        for index, line in enumerate(calls):
            if line.startswith("compose "):
                subcommand, args = self._parse_bound_compose_mutation(
                    line, expected_dir=expected_dir
                )
                compose_events.append((index, subcommand, args))
        self.assertEqual(
            [(subcommand, args) for _index, subcommand, args in compose_events],
            [
                ("stop", ["beat"]),
                (
                    "up",
                    ["-d", "--no-deps", "--force-recreate", "web", "worker"],
                ),
                ("up", ["-d", "--no-deps", "--force-recreate", "beat"]),
            ],
        )
        position = lambda fragment: next(
            i for i, line in enumerate(calls) if fragment in line
        )
        positions = [
            position("lock lifecycle-mode-switch acquire"),
            position("verify running off"),
            compose_events[0][0],
            compose_events[1][0],
            position("verify stopped shadow"),
            compose_events[2][0],
            position("verify running shadow"),
            position("lock lifecycle-mode-switch release"),
        ]
        self.assertEqual(positions, sorted(positions), calls)
        self.assertFalse(any("scanner" in line or "race_live" in line for line in calls))

    def test_enable_final_verify_failure_converges_to_off_and_stopped_beat(self):
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            result = harness.run(
                target_enabled="true",
                target_mode="shadow",
                FAKE_VERIFY_FAIL_AT="3",
            )
            calls = harness.lines()
            values = (
                harness.lifecycle_values(harness.canonical),
                harness.lifecycle_values(harness.release_env),
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(values[0]["RACE_EVENT_LIFECYCLE_ENABLED"], "false")
        self.assertEqual(values[1]["RACE_EVENT_LIFECYCLE_MODE"], "off")
        beat_up = next(i for i, line in enumerate(calls) if "up -d --no-deps --force-recreate beat" in line)
        recovery_stop = next(
            i for i, line in enumerate(calls[beat_up + 1 :], start=beat_up + 1)
            if "stop beat" in line
        )
        recovery_verify = next(
            i for i, line in enumerate(calls[recovery_stop + 1 :], start=recovery_stop + 1)
            if line == "verify stopped off"
        )
        self.assertGreater(recovery_verify, recovery_stop)
        self.assertTrue(any("lock lifecycle-mode-switch release" in line for line in calls))

    def test_disable_failure_never_restores_shadow(self):
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary), enabled="true", mode="shadow")
            result = harness.run(
                target_enabled="false",
                target_mode="off",
                FAKE_COMPOSE_FAIL_MATCH="up -d --no-deps --force-recreate web worker",
            )
            values = (
                harness.lifecycle_values(harness.canonical),
                harness.lifecycle_values(harness.release_env),
            )
        self.assertNotEqual(result.returncode, 0)
        for value in values:
            self.assertEqual(value["RACE_EVENT_LIFECYCLE_ENABLED"], "false")
            self.assertEqual(value["RACE_EVENT_LIFECYCLE_MODE"], "off")

    def test_recovery_failure_stops_worker_and_beat_and_keeps_lock(self):
        with TemporaryDirectory() as temporary:
            harness = self._harness(Path(temporary))
            result = harness.run(
                target_enabled="true",
                target_mode="shadow",
                FAKE_VERIFY_FAIL_AT="3,4",
            )
            calls = harness.lines()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            any(
                "stop beat worker" in line or "stop worker beat" in line
                for line in calls
            ),
            calls,
        )
        self.assertFalse(any("lock lifecycle-mode-switch release" in line for line in calls))

    def test_final_coherence_failure_stops_only_verified_rogue_cids(self):
        scenarios = (
            ("worker", "umanews", "False"),
            ("beat", "umanews", "False"),
            ("worker", "umanews", "True"),
        )
        for service, project, oneoff in scenarios:
            with self.subTest(
                service=service, project=project, oneoff=oneoff
            ), TemporaryDirectory() as temporary:
                harness = self._harness(Path(temporary))
                offender, unrelated = harness.seed_host_cleanup_scenario(
                    offender_service=service,
                    offender_project=project,
                    offender_oneoff=oneoff,
                )

                result = harness.run(target_enabled="true", target_mode="shadow")
                calls = harness.lines()

                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(
                    (harness.state / f"host-stopped-{offender}").is_file(), calls
                )
                self.assertFalse(
                    (harness.state / f"host-stopped-{unrelated}").exists(), calls
                )
                self.assertEqual(
                    [line for line in calls if line.startswith("docker stop ")],
                    [f"docker stop {offender}"],
                    "host cleanup must stop the exact inspected CID, not a name or selector",
                )
                offender_inspects = [
                    line
                    for line in calls
                    if line.startswith("docker inspect ") and offender in line
                ]
                self.assertTrue(offender_inspects, calls)
                inspect_evidence = "\n".join(offender_inspects)
                for label in (
                    "com.docker.compose.service",
                    "com.docker.compose.project",
                    "com.docker.compose.oneoff",
                    "com.docker.compose.project.working_dir",
                    "State.Running",
                    "Image",
                ):
                    self.assertIn(label, inspect_evidence)
                self.assertTrue(
                    any(
                        line.startswith("docker image inspect ")
                        and "sha256:good" in line
                        for line in calls
                    ),
                    calls,
                )
                self.assertTrue(
                    any("lock lifecycle-mode-switch release" in line for line in calls),
                    calls,
                )
                for env_file in (harness.canonical, harness.release_env):
                    self.assertEqual(
                        harness.lifecycle_values(env_file),
                        {
                            "RACE_EVENT_LIFECYCLE_ENABLED": "false",
                            "RACE_EVENT_LIFECYCLE_MODE": "off",
                            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256": "",
                            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS": "",
                        },
                    )

    def test_host_cleanup_probe_or_stop_failure_keeps_lock(self):
        failure_modes = ("enumerate", "inspect", "stop")
        for failure_mode in failure_modes:
            with self.subTest(failure_mode=failure_mode), TemporaryDirectory() as temporary:
                harness = self._harness(Path(temporary))
                offender, unrelated = harness.seed_host_cleanup_scenario(
                    offender_service="worker",
                    offender_project="umanews",
                    offender_oneoff="False",
                )
                overrides = {}
                if failure_mode == "enumerate":
                    overrides["FAKE_HOST_PS_FAIL"] = "1"
                elif failure_mode == "inspect":
                    overrides["FAKE_HOST_INSPECT_FAIL_CID"] = offender
                else:
                    overrides["FAKE_HOST_STOP_FAIL_CID"] = offender

                result = harness.run(
                    target_enabled="true", target_mode="shadow", **overrides
                )
                calls = harness.lines()

                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(
                    any("lock lifecycle-mode-switch release" in line for line in calls),
                    calls,
                )
                self.assertFalse(
                    (harness.state / f"host-stopped-{unrelated}").exists(), calls
                )
                if failure_mode != "stop":
                    self.assertFalse(
                        (harness.state / f"host-stopped-{offender}").exists(), calls
                    )
                if failure_mode == "enumerate":
                    self.assertTrue(
                        any(line.startswith("docker ps ") for line in calls), calls
                    )
                elif failure_mode == "inspect":
                    self.assertTrue(
                        any(
                            line.startswith("docker inspect ") and offender in line
                            for line in calls
                        ),
                        calls,
                    )
                else:
                    self.assertIn(f"docker stop {offender}", calls)

    def test_untrusted_generic_service_names_are_never_stopped(self):
        """worker/beat names alone never authorize stopping another app."""
        with TemporaryDirectory() as outer:
            outer_path = Path(outer)
            trusted = outer_path / "umanews-release-old"
            trusted.mkdir()
            other = outer_path / "other-app"
            other.mkdir()
            evil_prefix = outer_path / "umanews-evil"
            evil_prefix.mkdir()
            scenarios = (
                {
                    "label": "other-app-worker",
                    "offender_service": "worker",
                    "offender_project": "other-app",
                    "offender_oneoff": "False",
                    "offender_workdir": str(other),
                    "offender_image": "sha256:other",
                    "offender_revision": "b" * 40,
                },
                {
                    "label": "other-app-beat",
                    "offender_service": "beat",
                    "offender_project": "other-app",
                    "offender_oneoff": "False",
                    "offender_workdir": str(other),
                    "offender_image": "sha256:other",
                    "offender_revision": "b" * 40,
                },
                {
                    "label": "missing-service-label",
                    "offender_service": "",
                    "offender_project": "umanews",
                    "offender_oneoff": "False",
                    "offender_workdir": str(trusted),
                },
                {
                    "label": "missing-project-label",
                    "offender_service": "worker",
                    "offender_project": "",
                    "offender_oneoff": "False",
                    "offender_workdir": str(trusted),
                },
                {
                    "label": "anomalous-oneoff-label",
                    "offender_service": "worker",
                    "offender_project": "umanews",
                    "offender_oneoff": "sometimes",
                    "offender_workdir": str(trusted),
                },
                {
                    "label": "confusing-project-prefix",
                    "offender_service": "worker",
                    "offender_project": "umanews-evil",
                    "offender_oneoff": "False",
                    "offender_workdir": str(trusted),
                },
                {
                    "label": "confusing-working-dir-prefix",
                    "offender_service": "worker",
                    "offender_project": "umanews",
                    "offender_oneoff": "False",
                    "offender_workdir": str(evil_prefix),
                },
                {
                    "label": "wrong-image-id",
                    "offender_service": "worker",
                    "offender_project": "umanews",
                    "offender_oneoff": "False",
                    "offender_workdir": str(trusted),
                    "offender_image": "sha256:other",
                },
                {
                    "label": "wrong-image-revision",
                    "offender_service": "worker",
                    "offender_project": "umanews",
                    "offender_oneoff": "False",
                    "offender_workdir": str(trusted),
                    "offender_revision": "b" * 40,
                },
            )

            for scenario in scenarios:
                label = scenario["label"]
                kwargs = {key: value for key, value in scenario.items() if key != "label"}
                with self.subTest(label=label), TemporaryDirectory(dir=outer) as temporary:
                    harness = self._harness(Path(temporary))
                    offender, unrelated = harness.seed_host_cleanup_scenario(**kwargs)

                    result = harness.run(
                        target_enabled="true", target_mode="shadow"
                    )
                    calls = harness.lines()

                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(f"docker stop {offender}", calls)
                    self.assertNotIn(f"docker stop {unrelated}", calls)
                    self.assertFalse(
                        any("lock lifecycle-mode-switch release" in line for line in calls),
                        calls,
                    )
                    self.assertTrue(
                        any(
                            line.startswith("docker inspect ") and offender in line
                            for line in calls
                        ),
                        calls,
                    )


class DeploymentLockLifecycleActionTests(SimpleTestCase):
    def test_lifecycle_mode_switch_is_an_allowlisted_lock_action(self):
        script = ROOT / "deploy/deployment_lock.sh"
        with TemporaryDirectory() as temporary:
            lock = Path(temporary) / "lock"
            env = {
                **os.environ,
                "DEPLOYMENT_LOCK_DIR": str(lock),
                "DEPLOYMENT_LOCK_ACTION": "lifecycle-mode-switch",
                "DEPLOYMENT_LOCK_TOKEN": "0123456789abcdef0123456789abcdef",
            }
            acquired = subprocess.run(
                ["sh", str(script), "acquire"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            if acquired.returncode == 0:
                subprocess.run(
                    ["sh", str(script), "release"],
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
        self.assertEqual(acquired.returncode, 0, acquired.stderr)


class SupportedDeployOneOffInventoryTests(SimpleTestCase):
    """Characterize every supported wrapper one-off, not a hand-picked list."""

    def test_all_deploy_wrapper_run_calls_are_canonical_and_lock_contracts_remain(self):
        deploy = ROOT / "deploy"
        calls = []
        for script in sorted(deploy.rglob("*.sh")):
            if script == WRAPPER:
                continue
            normalized = script.read_text(encoding="utf-8").replace("\\\n", " ")
            wrapper_variables = set(
                re.findall(
                    r"^([A-Za-z_][A-Za-z0-9_]*)=.*compose-wrapper\.sh",
                    normalized,
                    flags=re.MULTILINE,
                )
            )
            for line_number, line in enumerate(normalized.splitlines(), start=1):
                invokes_wrapper = "compose-wrapper.sh" in line or any(
                    re.search(rf'\$\{{?{re.escape(variable)}\}}?', line)
                    for variable in wrapper_variables
                )
                if invokes_wrapper and " run " in f" {line} ":
                    calls.append((script.relative_to(ROOT).as_posix(), line_number, line))

        paths = {path for path, _line, _text in calls}
        self.assertEqual(
            paths,
            {
                "deploy/run_release_tasks.sh",
                "deploy/run_historical_calendar_release_b_preflight.sh",
                "deploy/deploy_race_live_p0_closed.sh",
                "deploy/resume_migration_history_repair.sh",
                "deploy/resume_rollback_control_state.sh",
            },
            calls,
        )
        for path, line_number, line in calls:
            with self.subTest(path=path, line=line_number):
                self.assertRegex(line, r"\brun\s+--rm\s+--no-deps\b")

        release = (deploy / "run_release_tasks.sh").read_text(encoding="utf-8")
        p0 = (deploy / "deploy_race_live_p0_closed.sh").read_text(encoding="utf-8")
        release_b = (
            deploy / "run_historical_calendar_release_b_preflight.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("deployment_lock.sh verify", release)
        self.assertRegex(p0, r'deployment_lock\.sh["\']?\s+acquire\b')
        self.assertRegex(p0, r'deployment_lock\.sh["\']?\s+release\b')
        self.assertIn("run --rm --no-deps", release_b.replace("\\\n", " "))

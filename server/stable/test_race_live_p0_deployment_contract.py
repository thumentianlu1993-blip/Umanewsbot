from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

from django.test import SimpleTestCase


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "deploy/deploy_race_live_p0_closed.sh"


@dataclass(frozen=True)
class ScriptResult:
    process: subprocess.CompletedProcess[str]
    calls: tuple[str, ...]
    beat_state: str

    @property
    def output(self) -> str:
        return f"{self.process.stdout}\n{self.process.stderr}"


class ClosedDeployHarness:
    """在临时仓库内用伪命令运行关闭态发布入口。"""

    def __init__(
        self,
        test_case: SimpleTestCase,
        *,
        initial_beat_state: str = "running",
    ):
        self.test_case = test_case
        self.initial_beat_state = initial_beat_state
        self._temporary: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> "ClosedDeployHarness":
        self.test_case.assertTrue(
            DEPLOY_SCRIPT.is_file(),
            "缺少关闭态专用发布入口 deploy/deploy_race_live_p0_closed.sh",
        )
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.deploy_dir = self.root / "deploy"
        self.docker_dir = self.deploy_dir / "docker"
        self.fake_bin = self.root / "fake-bin"
        self.state_dir = self.root / "state"
        self.docker_data_dir = self.root / "docker-data"
        for path in (
            self.docker_dir,
            self.fake_bin,
            self.state_dir,
            self.docker_data_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

        self.script = self.deploy_dir / DEPLOY_SCRIPT.name
        shutil.copy2(DEPLOY_SCRIPT, self.script)
        self.script.chmod(0o755)

        self.call_log = self.state_dir / "calls.log"
        self.call_log.write_text("", encoding="utf-8")
        self.beat_state_file = self.state_dir / "beat-state"
        self.beat_state_file.write_text(self.initial_beat_state, encoding="utf-8")
        self.web_state_file = self.state_dir / "web-state"
        self.web_state_file.write_text("running", encoding="utf-8")
        self.worker_state_file = self.state_dir / "worker-state"
        self.worker_state_file.write_text("running", encoding="utf-8")
        self.live_worker_state_file = self.state_dir / "race-live-worker-state"
        self.live_worker_state_file.write_text("stopped", encoding="utf-8")
        self.logical_minute_file = self.state_dir / "logical-minute"
        self.logical_minute_file.write_text("0", encoding="utf-8")
        self.worker_cmdline_file = self.state_dir / "worker-pid1-cmdline"
        self.set_worker_pid1_argv(
            "celery",
            "-A",
            "app",
            "worker",
            "--queues=celery",
            "--without-gossip",
        )
        self.meminfo_file = self.state_dir / "meminfo"
        self.test_sentinel = self.root / ".race-live-p0-test-sentinel"
        self.test_sentinel.write_text(
            "race-live-p0-deployment-contract-test\n",
            encoding="utf-8",
        )
        self.set_memory(mem_available_mib=4096, swap_free_mib=4096)
        self.set_flags()

        self._install_compose_fake()
        self._install_helper_fakes()
        self._install_system_fakes()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()

    def _write_executable(self, path: Path, body: str) -> None:
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
        path.chmod(0o755)

    def set_flags(
        self,
        *,
        scheduler: str = "false",
        monitor: str = "false",
        runner_mode: str = "disabled",
    ) -> None:
        (self.root / ".env").write_text(
            "\n".join(
                (
                    f"RACE_LIVE_SCHEDULER_ENABLED={scheduler}",
                    f"RACE_LIVE_MONITOR_ENABLED={monitor}",
                    f"RACE_LIVE_RUNNER_MODE={runner_mode}",
                    "",
                )
            ),
            encoding="utf-8",
        )

    def set_memory(self, *, mem_available_mib: int, swap_free_mib: int) -> None:
        self.meminfo_file.write_text(
            "\n".join(
                (
                    "MemTotal:        8388608 kB",
                    f"MemAvailable:    {mem_available_mib * 1024} kB",
                    "SwapTotal:       4194304 kB",
                    f"SwapFree:        {swap_free_mib * 1024} kB",
                    "",
                )
            ),
            encoding="utf-8",
        )

    def set_service_state(self, service: str, state: str) -> None:
        state_files = {
            "beat": self.beat_state_file,
            "web": self.web_state_file,
            "worker": self.worker_state_file,
            "race_live_worker": self.live_worker_state_file,
        }
        state_files[service].write_text(state, encoding="utf-8")

    def set_worker_pid1_argv(self, *arguments: str) -> None:
        self.worker_cmdline_file.write_bytes(
            b"\0".join(argument.encode("utf-8") for argument in arguments)
            + b"\0"
        )

    def install_production_compose_marker(self) -> Path:
        production_compose = self.root / "docker-compose.prod.lowcost.yml"
        shutil.copy2(
            REPO_ROOT / "docker-compose.prod.lowcost.yml",
            production_compose,
        )
        return production_compose

    def _base_env(self) -> dict[str, str]:
        return {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": f"{self.fake_bin}:/usr/bin:/bin",
            "TMPDIR": str(self.root / "tmp"),
            "RACE_LIVE_P0_TEST_MODE": "1",
            "RACE_LIVE_P0_TEST_SENTINEL": str(self.test_sentinel),
            "P0_FAKE_CALL_LOG": str(self.call_log),
            "P0_FAKE_BEAT_STATE_FILE": str(self.beat_state_file),
            "P0_FAKE_WEB_STATE_FILE": str(self.web_state_file),
            "P0_FAKE_WORKER_STATE_FILE": str(self.worker_state_file),
            "P0_FAKE_LIVE_WORKER_STATE_FILE": str(
                self.live_worker_state_file
            ),
            "P0_FAKE_LOGICAL_MINUTE_FILE": str(self.logical_minute_file),
            "P0_FAKE_WORKER_CMDLINE_FILE": str(self.worker_cmdline_file),
            "P0_FAKE_COMPOSE": str(
                self.docker_dir / "compose-wrapper.sh"
            ),
            "P0_FAKE_DOCKER_ROOT": str(self.docker_data_dir),
            "P0_FAKE_REPO_AVAILABLE_KIB": str(20 * 1024 * 1024),
            "P0_FAKE_DOCKER_AVAILABLE_KIB": str(20 * 1024 * 1024),
            "P0_FAKE_OOM": "false",
            "P0_FAKE_DRAIN_EXIT": "0",
            "P0_FAKE_PREFLIGHT_EXIT": "0",
            "P0_FAKE_BUILD_EXIT": "0",
            "P0_FAKE_STOP_BEAT_EXIT": "0",
            "P0_FAKE_STOP_BEAT_NOOP": "false",
            "P0_FAKE_STOP_WORKER_EXIT_AFTER_STOP": "0",
            "P0_FAKE_STOP_WORKER_FINAL_STATE": "stopped",
            "P0_FAKE_MIGRATION_COUNT": "0",
            "P0_FAKE_MIGRATION_EXIT": "0",
            "P0_FAKE_SETTINGS_EXIT": "0",
            "P0_FAKE_SCHEDULE_EXIT": "0",
            "P0_FAKE_WEB_HEALTH": "healthy",
            "P0_FAKE_WORKER_HEALTH": "healthy",
            "P0_FAKE_WEB_FAIL_AT_MINUTE": "0",
            "P0_FAKE_LIVE_WORKER_RESTART_AT_MINUTE": "0",
            "P0_FAKE_TARGET_COUNT_GROW_AT_MINUTE": "0",
            "P0_FAKE_BEAT_LOG_TARGET_AT_MINUTE": "0",
            "P0_FAKE_CELERY_QUEUE_LENGTH": "11",
            "P0_FAKE_RACE_LIVE_QUEUE_LENGTH": "22",
            "P0_FAKE_QUEUE_SNAPSHOT_OUTPUT": "",
            "RACE_LIVE_P0_TEST_OBSERVATION_INTERVAL_SECONDS": "0",
            # 生产默认仍指向 /proc/meminfo；合同测试只替换读取来源。
            "RACE_LIVE_P0_MEMINFO_FILE": str(self.meminfo_file),
            "RACE_LIVE_P0_REPOSITORY_PATH": str(self.root),
            "RACE_LIVE_P0_DOCKER_DATA_PATH": str(self.docker_data_dir),
        }

    def run(
        self,
        phase: str,
        *,
        env: dict[str, str] | None = None,
    ) -> ScriptResult:
        run_env = self._base_env()
        if env:
            run_env.update(env)
        (self.root / "tmp").mkdir(exist_ok=True)
        process = subprocess.run(
            ["/bin/sh", str(self.script), phase],
            cwd=self.root,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        calls = tuple(
            line
            for line in self.call_log.read_text(encoding="utf-8").splitlines()
            if line
        )
        return ScriptResult(
            process=process,
            calls=calls,
            beat_state=self.beat_state_file.read_text(encoding="utf-8").strip(),
        )

    def _install_compose_fake(self) -> None:
        self._write_executable(
            self.docker_dir / "compose-wrapper.sh",
            r"""
            #!/bin/sh
            set -eu

            log() {
              printf '%s\n' "$1" >> "$P0_FAKE_CALL_LOG"
            }

            args=" $* "
            log "compose|$*"

            service_state() {
              service_name="$1"
              state_file="$2"
              current_state=$(cat "$state_file")
              current_minute=$(cat "$P0_FAKE_LOGICAL_MINUTE_FILE")
              log "${service_name}-state|$current_state"
              if [ "$current_minute" -gt 0 ]; then
                log "observation|minute=${current_minute}|${service_name}=${current_state}"
              fi
              case "$args" in
                *" --format json "*)
                  log "${service_name}-state-query|${current_state}|json"
                  if [ "$current_state" = "absent" ]; then
                    printf '[]\n'
                  else
                    printf '{"Service":"%s","State":"%s","Health":""}\n' \
                      "$service_name" "$current_state"
                  fi
                  ;;
                *" --status running "*)
                  log "${service_name}-state-query|${current_state}|running-filter"
                  case "$current_state" in
                    running|healthy) printf '%s-container\n' "$service_name" ;;
                  esac
                  ;;
                *" -q "*)
                  log "${service_name}-state-query|${current_state}|id"
                  [ "$current_state" = "absent" ] \
                    || printf '%s-container\n' "$service_name"
                  ;;
                *)
                  log "${service_name}-state-query|${current_state}|plain"
                  printf '%s\n' "$current_state"
                  ;;
              esac
            }

            case "$args" in
              *" stop "*" beat "*)
                if [ "${P0_FAKE_STOP_BEAT_EXIT:-0}" -ne 0 ]; then
                  log "stop-beat|failed:${P0_FAKE_STOP_BEAT_EXIT}"
                  exit "$P0_FAKE_STOP_BEAT_EXIT"
                fi
                if [ "${P0_FAKE_STOP_BEAT_NOOP:-false}" = "true" ]; then
                  log "stop-beat|noop"
                  exit 0
                fi
                printf 'stopped' > "$P0_FAKE_BEAT_STATE_FILE"
                log "stop-beat|stopped"
                exit 0
                ;;
              *" stop "*" worker "*)
                printf '%s' "${P0_FAKE_STOP_WORKER_FINAL_STATE:-stopped}" \
                  > "$P0_FAKE_WORKER_STATE_FILE"
                log "stop-worker|state=${P0_FAKE_STOP_WORKER_FINAL_STATE:-stopped}"
                if [ "${P0_FAKE_STOP_WORKER_EXIT_AFTER_STOP:-0}" -ne 0 ]; then
                  log "stop-worker|failed:${P0_FAKE_STOP_WORKER_EXIT_AFTER_STOP}"
                  exit "$P0_FAKE_STOP_WORKER_EXIT_AFTER_STOP"
                fi
                exit 0
                ;;
            esac

            case "$args" in
              *" build "*)
                exit "${P0_FAKE_BUILD_EXIT:-0}"
                ;;
            esac

            case "$args" in
              *" up "*)
                case "$args" in
                  *" web "*) printf 'running' > "$P0_FAKE_WEB_STATE_FILE" ;;
                esac
                case "$args" in
                  *" worker "*) printf 'running' > "$P0_FAKE_WORKER_STATE_FILE" ;;
                esac
                case "$args" in
                  *" race_live_worker "*)
                    printf 'running' > "$P0_FAKE_LIVE_WORKER_STATE_FILE"
                    ;;
                esac
                case "$args" in
                  *" beat "*) printf 'running' > "$P0_FAKE_BEAT_STATE_FILE" ;;
                esac
                exit 0
                ;;
            esac

            case "$args" in
              *" logs "*" beat "*)
                current_minute=$(cat "$P0_FAKE_LOGICAL_MINUTE_FILE")
                log_since=missing
                case "$args" in
                  *" --since "*|*" --since="*) log_since=start ;;
                esac
                log "beat-log-check|minute=${current_minute}|since=${log_since}"
                if [ "${P0_FAKE_BEAT_LOG_TARGET_AT_MINUTE:-0}" -gt 0 ] \
                  && [ "$current_minute" -ge "$P0_FAKE_BEAT_LOG_TARGET_AT_MINUTE" ]; then
                  printf '%s\n' \
                    'Scheduler: Sending due task select-due-race-live-events'
                fi
                exit 0
                ;;
            esac

            case "$*" in
              *select_due_race_live_events_task*|*monitor_race_live_sla_task*)
                current_minute=$(cat "$P0_FAKE_LOGICAL_MINUTE_FILE")
                selector_count=0
                monitor_count=0
                if [ "${P0_FAKE_TARGET_COUNT_GROW_AT_MINUTE:-0}" -gt 0 ] \
                  && [ "$current_minute" -ge "$P0_FAKE_TARGET_COUNT_GROW_AT_MINUTE" ]; then
                  selector_count=1
                fi
                log "queue-observation|minute=${current_minute}|celery=${P0_FAKE_CELERY_QUEUE_LENGTH:-11}|race_live=${P0_FAKE_RACE_LIVE_QUEUE_LENGTH:-22}|selector=${selector_count}|monitor=${monitor_count}"
                case "$args" in
                  *" --no-imports "*)
                    log "queue-snapshot-command|no-imports"
                    ;;
                  *)
                    log "queue-snapshot-output|django-auto-import-banner"
                    printf '%s\n\n' \
                      '105 objects imported automatically (use -v 2 for details).'
                    ;;
                esac
                if [ -n "${P0_FAKE_QUEUE_SNAPSHOT_OUTPUT:-}" ]; then
                  log "queue-snapshot-output|override"
                  printf '%s\n' "$P0_FAKE_QUEUE_SNAPSHOT_OUTPUT"
                else
                  printf 'celery_length=%s race_live_length=%s selector_count=%s monitor_count=%s\n' \
                    "${P0_FAKE_CELERY_QUEUE_LENGTH:-11}" \
                    "${P0_FAKE_RACE_LIVE_QUEUE_LENGTH:-22}" \
                    "$selector_count" "$monitor_count"
                fi
                [ "$selector_count" -eq 0 ] && [ "$monitor_count" -eq 0 ]
                exit
                ;;
            esac

            case "$*" in
              *MigrationExecutor*|*migration_plan*|*"showmigrations"*)
                log "migration-plan|${P0_FAKE_MIGRATION_COUNT:-0}"
                if [ "${P0_FAKE_MIGRATION_EXIT:-0}" -ne 0 ]; then
                  exit "$P0_FAKE_MIGRATION_EXIT"
                fi
                printf 'pending_migrations=%s\n' \
                  "${P0_FAKE_MIGRATION_COUNT:-0}"
                [ "${P0_FAKE_MIGRATION_COUNT:-0}" -eq 0 ]
                exit
                ;;
            esac

            case "$*" in
              *CELERY_BEAT_SCHEDULE*|*select-due-race-live-events*|*monitor-race-live-sla*)
                if [ "${P0_FAKE_SETTINGS_EXIT:-0}" -ne 0 ]; then
                  log "settings-check|failed"
                  exit "$P0_FAKE_SETTINGS_EXIT"
                fi
                if [ "${P0_FAKE_SCHEDULE_EXIT:-0}" -ne 0 ]; then
                  log "schedule-check|failed"
                  exit "$P0_FAKE_SCHEDULE_EXIT"
                fi
                log "schedule-check|closed"
                printf '%s\n' 'race_live_flags=closed schedule=closed'
                exit 0
                ;;
            esac

            case "$args" in
              *" ps "*" beat "*)
                service_state beat "$P0_FAKE_BEAT_STATE_FILE"
                exit 0
                ;;
              *" ps "*" race_live_worker "*)
                service_state race-live-worker \
                  "$P0_FAKE_LIVE_WORKER_STATE_FILE"
                exit 0
                ;;
              *" ps "*" web "*)
                service_state web "$P0_FAKE_WEB_STATE_FILE"
                exit 0
                ;;
              *" ps "*" worker "*)
                service_state worker "$P0_FAKE_WORKER_STATE_FILE"
                exit 0
                ;;
            esac

            case "$args" in
              *" exec "*" web "*" curl "*)
                current_web_state=$(cat "$P0_FAKE_WEB_STATE_FILE")
                [ "$current_web_state" = "running" ] \
                  && [ "${P0_FAKE_WEB_HEALTH:-healthy}" = "healthy" ]
                exit
                ;;
              *"/proc/1/cmdline"*)
                validation_code=
                for validation_argument in "$@"; do
                  validation_code=$validation_argument
                done
                safe_validation_code="$(
                  printf '%s' "$validation_code" \
                    | sed "s|/proc/1/cmdline|$P0_FAKE_WORKER_CMDLINE_FILE|g"
                )"
                worker_argv="$(
                  tr '\000' ' ' < "$P0_FAKE_WORKER_CMDLINE_FILE"
                )"
                log "worker-pid1|$worker_argv"
                set +e
                /bin/sh -c "$safe_validation_code"
                validation_status="$?"
                set -e
                log "worker-pid1-validation-exit|$validation_status"
                exit "$validation_status"
                ;;
              *" exec "*" worker "*)
                log "worker-health|${P0_FAKE_WORKER_HEALTH:-healthy}"
                [ "${P0_FAKE_WORKER_HEALTH:-healthy}" = "healthy" ]
                exit
                ;;
              *" images "*|*" image "*)
                printf 'sha256:candidate-image\n'
                exit 0
                ;;
            esac

            exit 0
            """,
        )

    def _install_helper_fakes(self) -> None:
        self._write_executable(
            self.deploy_dir / "wait_for_celery_drain.sh",
            r"""
            #!/bin/sh
            set -eu
            printf '%s\n' 'drain|worker' >> "$P0_FAKE_CALL_LOG"
            exit "${P0_FAKE_DRAIN_EXIT:-0}"
            """,
        )
        self._write_executable(
            self.deploy_dir / "historical_runner_preflight.sh",
            r"""
            #!/bin/sh
            set -eu
            printf 'historical-preflight|%s\n' "$*" >> "$P0_FAKE_CALL_LOG"
            exit "${P0_FAKE_PREFLIGHT_EXIT:-0}"
            """,
        )

    def _install_system_fakes(self) -> None:
        self._write_executable(
            self.fake_bin / "docker",
            r"""
            #!/bin/sh
            set -eu
            printf 'docker|%s\n' "$*" >> "$P0_FAKE_CALL_LOG"
            if [ "${1:-}" = "compose" ]; then
              shift
              exec "$P0_FAKE_COMPOSE" "$@"
            fi
            case " $* " in
              *" info "*)
                printf '%s\n' "$P0_FAKE_DOCKER_ROOT"
                ;;
              *" inspect "*" beat "*)
                beat_state=$(cat "$P0_FAKE_BEAT_STATE_FILE")
                printf 'beat-state|%s\n' "$beat_state" >> "$P0_FAKE_CALL_LOG"
                printf '%s\n' "$beat_state"
                ;;
              *" inspect "*|*" image inspect "*)
                printf 'sha256:candidate-image\n'
                ;;
              *)
                :
                ;;
            esac
            """,
        )
        self._write_executable(
            self.fake_bin / "docker-compose",
            r"""
            #!/bin/sh
            set -eu
            exec "$P0_FAKE_COMPOSE" "$@"
            """,
        )
        self._write_executable(
            self.fake_bin / "df",
            r"""
            #!/bin/sh
            set -eu
            target=
            for argument in "$@"; do
              target=$argument
            done
            available=${P0_FAKE_REPO_AVAILABLE_KIB:-20971520}
            case "$target" in
              "$P0_FAKE_DOCKER_ROOT"|"$P0_FAKE_DOCKER_ROOT"/*)
                available=${P0_FAKE_DOCKER_AVAILABLE_KIB:-20971520}
                ;;
            esac
            printf 'system|df %s\n' "$*" >> "$P0_FAKE_CALL_LOG"
            printf '%s\n' \
              'Filesystem 1024-blocks Used Available Capacity Mounted on'
            printf 'fakefs 41943040 1 %s 1%% %s\n' "$available" "$target"
            """,
        )
        self._write_executable(
            self.fake_bin / "journalctl",
            r"""
            #!/bin/sh
            set -eu
            printf 'system|journalctl %s\n' "$*" >> "$P0_FAKE_CALL_LOG"
            if [ "${P0_FAKE_OOM:-false}" = "true" ]; then
              printf '%s\n' 'kernel: oom-kill:constraint=CONSTRAINT_NONE'
            fi
            """,
        )
        self._write_executable(
            self.fake_bin / "dmesg",
            r"""
            #!/bin/sh
            set -eu
            printf 'system|dmesg %s\n' "$*" >> "$P0_FAKE_CALL_LOG"
            if [ "${P0_FAKE_OOM:-false}" = "true" ]; then
              printf '%s\n' 'Out of memory: Killed process 999 (fake)'
            fi
            """,
        )
        self._write_executable(
            self.fake_bin / "curl",
            r"""
            #!/bin/sh
            set -eu
            printf 'system|curl %s\n' "$*" >> "$P0_FAKE_CALL_LOG"
            current_web_state=$(cat "$P0_FAKE_WEB_STATE_FILE")
            [ "$current_web_state" = "running" ] \
              && [ "${P0_FAKE_WEB_HEALTH:-healthy}" = "healthy" ]
            """,
        )
        self._write_executable(
            self.fake_bin / "sleep",
            r"""
            #!/bin/sh
            set -eu
            current_minute=$(cat "$P0_FAKE_LOGICAL_MINUTE_FILE")
            next_minute=$((current_minute + 1))
            printf '%s' "$next_minute" > "$P0_FAKE_LOGICAL_MINUTE_FILE"
            printf 'logical-minute|%s|sleep=%s\n' "$next_minute" "$*" \
              >> "$P0_FAKE_CALL_LOG"
            if [ "${P0_FAKE_WEB_FAIL_AT_MINUTE:-0}" -gt 0 ] \
              && [ "$next_minute" -ge "$P0_FAKE_WEB_FAIL_AT_MINUTE" ]; then
              printf 'failed' > "$P0_FAKE_WEB_STATE_FILE"
            fi
            if [ "${P0_FAKE_LIVE_WORKER_RESTART_AT_MINUTE:-0}" -gt 0 ] \
              && [ "$next_minute" -ge "$P0_FAKE_LIVE_WORKER_RESTART_AT_MINUTE" ]; then
              printf 'restarting' > "$P0_FAKE_LIVE_WORKER_STATE_FILE"
            fi
            """,
        )
        for command in ("python", "python3", "psql", "redis-cli", "nc"):
            self._write_executable(
                self.fake_bin / command,
                f"""
                #!/bin/sh
                set -eu
                printf 'blocked-host-command|{command} %s\\n' "$*" \
                  >> "$P0_FAKE_CALL_LOG"
                exit 97
                """,
            )


class DeploymentContractAssertions:
    def compose_calls(self, result: ScriptResult) -> list[list[str]]:
        return [
            shlex.split(line.split("|", 1)[1])
            for line in result.calls
            if line.startswith("compose|")
        ]

    def compose_operation_calls(
        self,
        result: ScriptResult,
        operation: str,
    ) -> list[list[str]]:
        return [
            arguments
            for arguments in self.compose_calls(result)
            if operation in arguments
        ]

    def services_after_operation(
        self,
        arguments: list[str],
        operation: str,
    ) -> list[str]:
        operation_index = arguments.index(operation)
        return [
            argument
            for argument in arguments[operation_index + 1 :]
            if not argument.startswith("-")
        ]

    def assert_no_mutating_compose_calls(self, result: ScriptResult) -> None:
        for operation in ("stop", "build", "up"):
            self.assertEqual(
                self.compose_operation_calls(result, operation),
                [],
                f"no-go 后仍调用了 compose {operation}: {result.calls}",
            )

    def assert_no_fake_resource_probes(self, result: ScriptResult) -> None:
        forbidden_prefixes = (
            "system|df ",
            "system|journalctl ",
            "system|dmesg ",
            "docker|info ",
        )
        self.assertFalse(
            any(
                call.startswith(forbidden_prefixes)
                for call in result.calls
            ),
            result.calls,
        )

    def assert_beat_unchanged_receipt(
        self,
        result: ScriptResult,
        expected_state: str,
    ) -> None:
        self.assertEqual(result.beat_state, expected_state)
        self.assertRegex(
            result.output,
            rf"(?is)beat.*{expected_state}.*(?:未被本命令改变|未改变|unchanged)",
        )

    def assert_no_beat_or_live_worker_up(self, result: ScriptResult) -> None:
        for arguments in self.compose_operation_calls(result, "up"):
            services = self.services_after_operation(arguments, "up")
            self.assertNotIn("beat", services, result.calls)
            self.assertNotIn("race_live_worker", services, result.calls)


class RaceLiveP0DeploymentEntrypointTests(
    DeploymentContractAssertions,
    SimpleTestCase,
):
    def test_closed_state_deployment_entrypoint_exists_and_is_executable(self):
        self.assertTrue(
            DEPLOY_SCRIPT.is_file(),
            "缺少关闭态专用发布入口 deploy/deploy_race_live_p0_closed.sh",
        )
        self.assertTrue(
            os.access(DEPLOY_SCRIPT, os.X_OK),
            "关闭态专用发布入口必须可直接执行",
        )

    def test_prepare_and_start_beat_are_real_isolated_phases(self):
        with ClosedDeployHarness(self) as harness:
            prepared = harness.run("prepare")
        self.assertEqual(prepared.process.returncode, 0, prepared.output)
        self.assertEqual(prepared.beat_state, "stopped")
        self.assert_no_beat_or_live_worker_up(prepared)

        with ClosedDeployHarness(
            self,
            initial_beat_state="stopped",
        ) as harness:
            started = harness.run("start-beat")
        self.assertEqual(started.process.returncode, 0, started.output)
        beat_up_calls = [
            arguments
            for arguments in self.compose_operation_calls(started, "up")
            if "beat" in self.services_after_operation(arguments, "up")
        ]
        self.assertEqual(len(beat_up_calls), 1, started.calls)
        self.assertEqual(
            self.services_after_operation(beat_up_calls[0], "up"),
            ["beat"],
        )


class RaceLiveP0DeploymentPreStopTests(
    DeploymentContractAssertions,
    SimpleTestCase,
):
    def test_flag_no_go_keeps_original_beat_state_and_does_not_mutate(self):
        with ClosedDeployHarness(self) as harness:
            harness.set_flags(scheduler="true")
            result = harness.run("prepare")

        self.assertNotEqual(result.process.returncode, 0, result.output)
        self.assert_no_mutating_compose_calls(result)
        self.assert_beat_unchanged_receipt(result, "running")

    def test_fake_overrides_require_test_mode_and_root_local_sentinel(self):
        scenarios = (
            ("test-mode-disabled", {"RACE_LIVE_P0_TEST_MODE": "0"}),
            (
                "sentinel-missing",
                {"RACE_LIVE_P0_TEST_SENTINEL": "/missing/p0-test-sentinel"},
            ),
            (
                "sentinel-outside-temporary-root",
                {"RACE_LIVE_P0_TEST_SENTINEL": "/dev/null"},
            ),
        )
        for label, env in scenarios:
            with self.subTest(label=label), ClosedDeployHarness(self) as harness:
                result = harness.run("prepare", env=env)
                self.assertNotEqual(result.process.returncode, 0, result.output)
                self.assert_no_mutating_compose_calls(result)
                self.assert_no_fake_resource_probes(result)
                self.assertRegex(
                    result.output,
                    r"(?is)(?:test mode|测试模式).*(?:sentinel|哨兵)",
                )

    def test_test_mode_refuses_a_production_compose_root_before_overrides(self):
        with ClosedDeployHarness(self) as harness:
            production_compose = harness.install_production_compose_marker()
            result = harness.run(
                "prepare",
                env={
                    "RACE_LIVE_P0_MEMINFO_FILE": str(
                        harness.root / "must-not-read-meminfo"
                    ),
                    "RACE_LIVE_P0_REPOSITORY_PATH": str(
                        harness.root / "must-not-use-repository-override"
                    ),
                    "RACE_LIVE_P0_DOCKER_DATA_PATH": str(
                        harness.root / "must-not-use-docker-override"
                    ),
                },
            )

        self.assertTrue(production_compose.name == "docker-compose.prod.lowcost.yml")
        self.assertNotEqual(result.process.returncode, 0, result.output)
        self.assert_no_mutating_compose_calls(result)
        self.assert_no_fake_resource_probes(result)
        self.assertRegex(
            result.output,
            r"(?is)(?:test mode|测试模式).*(?:production|生产|docker-compose\.prod\.lowcost\.yml)",
        )

    def test_each_resource_no_go_is_pre_stop_and_non_mutating(self):
        scenarios = (
            (
                "memory-below-absolute-floor",
                {"memory": (1400, 4096)},
                {},
            ),
            (
                "memory-below-low-swap-floor",
                {"memory": (1800, 512)},
                {},
            ),
            (
                "repository-disk",
                {},
                {"P0_FAKE_REPO_AVAILABLE_KIB": str(5 * 1024 * 1024)},
            ),
            (
                "docker-disk",
                {},
                {"P0_FAKE_DOCKER_AVAILABLE_KIB": str(5 * 1024 * 1024)},
            ),
            ("recent-oom", {}, {"P0_FAKE_OOM": "true"}),
        )
        for label, state, env in scenarios:
            with self.subTest(label=label), ClosedDeployHarness(self) as harness:
                if "memory" in state:
                    mem_available, swap_free = state["memory"]
                    harness.set_memory(
                        mem_available_mib=mem_available,
                        swap_free_mib=swap_free,
                    )
                result = harness.run("prepare", env=env)
                self.assertNotEqual(result.process.returncode, 0, result.output)
                self.assert_no_mutating_compose_calls(result)
                self.assert_beat_unchanged_receipt(result, "running")


class RaceLiveP0DeploymentPrepareFlowTests(
    DeploymentContractAssertions,
    SimpleTestCase,
):
    def assert_unconfirmed_stop_keeps_pre_stop_boundary(
        self,
        result: ScriptResult,
    ) -> None:
        self.assertNotEqual(result.process.returncode, 0, result.output)
        self.assertEqual(result.beat_state, "running")
        self.assertNotIn("drain|worker", result.calls)
        self.assertEqual(
            self.compose_operation_calls(result, "build"),
            [],
            result.calls,
        )
        self.assertEqual(
            self.compose_operation_calls(result, "up"),
            [],
            result.calls,
        )
        for arguments in self.compose_operation_calls(result, "stop"):
            self.assertNotIn(
                "worker",
                self.services_after_operation(arguments, "stop"),
                result.calls,
            )
        self.assertRegex(
            result.output,
            r"(?is)beat.*(?:停止|stop).*(?:不可确认|未确认|not confirmed|failed|失败)",
        )
        self.assertNotIn(
            "失败复核：Beat",
            result.output,
            "stop 未确认时不得进入 BEAT_STOPPED 的失败复核路径",
        )
        self.assertRegex(
            result.output,
            r"(?is)beat.*原状态.*running.*(?:未被本命令改变|未改变|unchanged)",
        )

    def test_stop_beat_command_failure_keeps_pre_stop_boundary(self):
        with ClosedDeployHarness(self) as harness:
            result = harness.run(
                "prepare",
                env={"P0_FAKE_STOP_BEAT_EXIT": "75"},
            )

        self.assertIn("stop-beat|failed:75", result.calls)
        self.assert_unconfirmed_stop_keeps_pre_stop_boundary(result)

    def test_stop_beat_noop_keeps_pre_stop_boundary(self):
        with ClosedDeployHarness(self) as harness:
            result = harness.run(
                "prepare",
                env={"P0_FAKE_STOP_BEAT_NOOP": "true"},
            )

        self.assertIn("stop-beat|noop", result.calls)
        self.assertGreaterEqual(
            result.calls.count("beat-state|running"),
            2,
            result.calls,
        )
        self.assert_unconfirmed_stop_keeps_pre_stop_boundary(result)

    def test_prepare_orders_verified_beat_stop_before_drain_worker_stop_and_build(
        self,
    ):
        with ClosedDeployHarness(self) as harness:
            result = harness.run("prepare")

        self.assertEqual(result.process.returncode, 0, result.output)
        stop_beat_index = next(
            index
            for index, call in enumerate(result.calls)
            if call.startswith("compose|")
            and "stop" in shlex.split(call.split("|", 1)[1])
            and "beat" in shlex.split(call.split("|", 1)[1])
        )
        beat_verified_index = next(
            index
            for index, call in enumerate(result.calls)
            if index > stop_beat_index and call == "beat-state|stopped"
        )
        drain_index = result.calls.index("drain|worker")
        stop_worker_index = next(
            index
            for index, call in enumerate(result.calls)
            if call.startswith("compose|")
            and "stop" in shlex.split(call.split("|", 1)[1])
            and "worker" in shlex.split(call.split("|", 1)[1])
        )
        build_index = next(
            index
            for index, call in enumerate(result.calls)
            if call.startswith("compose|")
            and "build" in shlex.split(call.split("|", 1)[1])
        )
        self.assertLess(
            stop_beat_index,
            beat_verified_index,
            result.calls,
        )
        self.assertLess(beat_verified_index, drain_index, result.calls)
        self.assertLess(drain_index, stop_worker_index, result.calls)
        self.assertLess(stop_worker_index, build_index, result.calls)

    def test_prepare_recreates_and_health_checks_nginx_without_pulling_it(self):
        with ClosedDeployHarness(self) as harness:
            result = harness.run("prepare")

        self.assertEqual(result.process.returncode, 0, result.output)
        nginx_up_calls = [
            arguments
            for arguments in self.compose_operation_calls(result, "up")
            if "nginx" in self.services_after_operation(arguments, "up")
        ]
        self.assertEqual(len(nginx_up_calls), 1, result.calls)
        self.assertIn("--force-recreate", nginx_up_calls[0], result.calls)
        self.assertIn(
            "system|curl -fsS http://127.0.0.1/healthz/",
            result.calls,
        )
        nginx_pull_calls = [
            arguments
            for arguments in self.compose_operation_calls(result, "pull")
            if "nginx" in self.services_after_operation(arguments, "pull")
        ]
        self.assertEqual(
            nginx_pull_calls,
            [],
            f"P0 专用脚本不得拉取 nginx 镜像：{result.calls}",
        )

    def test_post_stop_failure_rechecks_that_beat_is_still_stopped(self):
        with ClosedDeployHarness(self) as harness:
            result = harness.run("prepare", env={"P0_FAKE_DRAIN_EXIT": "41"})

        self.assertNotEqual(result.process.returncode, 0, result.output)
        self.assertEqual(result.beat_state, "stopped")
        self.assertGreaterEqual(
            result.calls.count("beat-state|stopped"),
            2,
            result.calls,
        )
        self.assertEqual(
            self.compose_operation_calls(result, "build"),
            [],
            result.calls,
        )
        self.assertEqual(
            self.compose_operation_calls(result, "up"),
            [],
            result.calls,
        )

    def test_prepare_never_starts_beat_or_race_live_worker(self):
        with ClosedDeployHarness(self) as harness:
            result = harness.run("prepare")
            live_worker_state = harness.live_worker_state_file.read_text(
                encoding="utf-8"
            ).strip()

        self.assertEqual(result.process.returncode, 0, result.output)
        self.assert_no_beat_or_live_worker_up(result)
        self.assertEqual(result.beat_state, "stopped")
        self.assertEqual(live_worker_state, "stopped")

    def test_prepare_failure_trap_does_not_implicitly_start_beat(self):
        with ClosedDeployHarness(self) as harness:
            result = harness.run("prepare", env={"P0_FAKE_BUILD_EXIT": "73"})

        self.assertNotEqual(result.process.returncode, 0, result.output)
        self.assertEqual(result.beat_state, "stopped")
        self.assert_no_beat_or_live_worker_up(result)
        self.assertGreaterEqual(
            result.calls.count("beat-state|stopped"),
            2,
            result.calls,
        )

    def test_candidate_schedule_failure_keeps_beat_stopped(self):
        with ClosedDeployHarness(self) as harness:
            result = harness.run(
                "prepare",
                env={"P0_FAKE_SCHEDULE_EXIT": "74"},
            )

        self.assertNotEqual(result.process.returncode, 0, result.output)
        self.assertIn("schedule-check|failed", result.calls)
        self.assertEqual(result.beat_state, "stopped")
        self.assert_no_beat_or_live_worker_up(result)
        self.assertGreaterEqual(
            result.calls.count("beat-state|stopped"),
            2,
            result.calls,
        )

    def test_worker_stop_failure_after_stopped_restores_worker(self):
        with ClosedDeployHarness(self) as harness:
            result = harness.run(
                "prepare",
                env={"P0_FAKE_STOP_WORKER_EXIT_AFTER_STOP": "76"},
            )
            worker_state = harness.worker_state_file.read_text(
                encoding="utf-8"
            ).strip()

        self.assertNotEqual(result.process.returncode, 0, result.output)
        self.assertEqual(result.beat_state, "stopped")
        self.assertEqual(worker_state, "running")
        self.assertIn("stop-worker|state=stopped", result.calls)
        self.assertIn("stop-worker|failed:76", result.calls)
        self.assertEqual(
            self.compose_operation_calls(result, "build"),
            [],
            result.calls,
        )
        worker_up_calls = [
            arguments
            for arguments in self.compose_operation_calls(result, "up")
            if "worker" in self.services_after_operation(arguments, "up")
        ]
        self.assertEqual(len(worker_up_calls), 1, result.calls)
        self.assert_no_beat_or_live_worker_up(result)


class RaceLiveP0DeploymentServiceStateTests(
    DeploymentContractAssertions,
    SimpleTestCase,
):
    def test_created_race_live_worker_allows_prepare_and_start_beat(self):
        scenarios = (
            ("prepare", "running", "stopped"),
            ("start-beat", "stopped", "running"),
        )
        for phase, initial_beat_state, expected_beat_state in scenarios:
            with (
                self.subTest(phase=phase),
                ClosedDeployHarness(
                    self,
                    initial_beat_state=initial_beat_state,
                ) as harness,
            ):
                harness.set_service_state("race_live_worker", "created")
                result = harness.run(phase)
                self.assertEqual(result.process.returncode, 0, result.output)
                self.assertEqual(result.beat_state, expected_beat_state)
                self.assertIn(
                    "race-live-worker-state-query|created|json",
                    result.calls,
                )

    def test_ambiguous_race_live_worker_blocks_prepare_and_start_beat(self):
        scenarios = (
            ("prepare", "running"),
            ("start-beat", "stopped"),
        )
        for live_worker_state in ("restarting", "paused", "unknown"):
            for phase, initial_beat_state in scenarios:
                with (
                    self.subTest(
                        live_worker_state=live_worker_state,
                        phase=phase,
                    ),
                    ClosedDeployHarness(
                        self,
                        initial_beat_state=initial_beat_state,
                    ) as harness,
                ):
                    harness.set_service_state(
                        "race_live_worker",
                        live_worker_state,
                    )
                    result = harness.run(phase)
                    self.assertNotEqual(
                        result.process.returncode,
                        0,
                        result.output,
                    )
                    self.assertEqual(result.beat_state, initial_beat_state)
                    self.assertIn(
                        f"race-live-worker-state-query|{live_worker_state}|json",
                        result.calls,
                    )
                    if phase == "prepare":
                        self.assert_no_mutating_compose_calls(result)
                    else:
                        self.assertEqual(
                            self.compose_operation_calls(result, "up"),
                            [],
                            result.calls,
                        )

    def test_ambiguous_worker_state_after_stop_is_not_stopped(self):
        for worker_state in ("restarting", "paused", "unknown"):
            with (
                self.subTest(worker_state=worker_state),
                ClosedDeployHarness(self) as harness,
            ):
                result = harness.run(
                    "prepare",
                    env={"P0_FAKE_STOP_WORKER_FINAL_STATE": worker_state},
                )
                self.assertNotEqual(result.process.returncode, 0, result.output)
                self.assertEqual(result.beat_state, "stopped")
                self.assertIn(
                    f"worker-state-query|{worker_state}|json",
                    result.calls,
                )
                self.assertEqual(
                    self.compose_operation_calls(result, "build"),
                    [],
                    result.calls,
                )

    def test_absent_worker_after_stop_is_explicitly_accepted(self):
        with ClosedDeployHarness(self) as harness:
            result = harness.run(
                "prepare",
                env={"P0_FAKE_STOP_WORKER_FINAL_STATE": "absent"},
            )

        self.assertEqual(result.process.returncode, 0, result.output)
        self.assertIn(
            "worker-state-query|absent|json",
            result.calls,
        )


class RaceLiveP0DeploymentMigrationTests(
    DeploymentContractAssertions,
    SimpleTestCase,
):
    def test_nonzero_migration_plan_blocks_candidate_web_start(self):
        with ClosedDeployHarness(self) as harness:
            result = harness.run(
                "prepare",
                env={"P0_FAKE_MIGRATION_COUNT": "2"},
            )

        self.assertNotEqual(result.process.returncode, 0, result.output)
        self.assertIn("migration-plan|2", result.calls)
        self.assertFalse(
            self._candidate_web_was_started(result),
            result.calls,
        )
        self.assertEqual(result.beat_state, "stopped")

    def test_unreadable_migration_plan_blocks_candidate_web_start(self):
        with ClosedDeployHarness(self) as harness:
            result = harness.run(
                "prepare",
                env={"P0_FAKE_MIGRATION_EXIT": "42"},
            )

        self.assertNotEqual(result.process.returncode, 0, result.output)
        self.assertTrue(
            any(call.startswith("migration-plan|") for call in result.calls),
            result.calls,
        )
        self.assertFalse(
            self._candidate_web_was_started(result),
            result.calls,
        )
        self.assertEqual(result.beat_state, "stopped")

    def test_zero_migration_plan_is_verified_twice_before_web_without_migrate(
        self,
    ):
        with ClosedDeployHarness(self) as harness:
            result = harness.run("prepare")

        self.assertEqual(result.process.returncode, 0, result.output)
        migration_indices = [
            index
            for index, call in enumerate(result.calls)
            if call == "migration-plan|0"
        ]
        self.assertEqual(len(migration_indices), 2, result.calls)
        web_up_index = next(
            index
            for index, call in enumerate(result.calls)
            if call.startswith("compose|")
            and "up" in shlex.split(call.split("|", 1)[1])
            and "web" in shlex.split(call.split("|", 1)[1])
        )
        self.assertLess(migration_indices[0], web_up_index, result.calls)
        self.assertLess(migration_indices[1], web_up_index, result.calls)
        self.assertFalse(
            any(
                "manage.py migrate" in call
                for call in result.calls
            ),
            result.calls,
        )
        self.assertFalse(
            any(call.startswith("blocked-host-command|") for call in result.calls),
            result.calls,
        )

    def _candidate_web_was_started(self, result: ScriptResult) -> bool:
        return any(
            "web" in self.services_after_operation(arguments, "up")
            for arguments in self.compose_operation_calls(result, "up")
        )


class RaceLiveP0DeploymentStartBeatTests(
    DeploymentContractAssertions,
    SimpleTestCase,
):
    def test_start_beat_requires_every_closed_candidate_precondition(self):
        scenarios = (
            ("closed-flags", {"scheduler": "true"}, {}),
            ("schedule", {}, {"P0_FAKE_SCHEDULE_EXIT": "51"}),
            (
                "web-health",
                {"web": "failed"},
                {"P0_FAKE_WEB_HEALTH": "failed"},
            ),
            (
                "worker-health",
                {"worker": "failed"},
                {"P0_FAKE_WORKER_HEALTH": "failed"},
            ),
            ("live-worker-stopped", {"race_live_worker": "running"}, {}),
        )
        for label, state, env in scenarios:
            with (
                self.subTest(label=label),
                ClosedDeployHarness(
                    self,
                    initial_beat_state="stopped",
                ) as harness,
            ):
                if "scheduler" in state:
                    harness.set_flags(scheduler=state["scheduler"])
                if "race_live_worker" in state:
                    harness.set_service_state(
                        "race_live_worker",
                        state["race_live_worker"],
                    )
                if "web" in state:
                    harness.set_service_state("web", state["web"])
                if "worker" in state:
                    harness.set_service_state("worker", state["worker"])
                result = harness.run("start-beat", env=env)
                self.assertNotEqual(result.process.returncode, 0, result.output)
                self.assertEqual(result.beat_state, "stopped")
                beat_up_calls = [
                    arguments
                    for arguments in self.compose_operation_calls(result, "up")
                    if "beat" in self.services_after_operation(arguments, "up")
                ]
                self.assertEqual(beat_up_calls, [], result.calls)

    def test_start_beat_checks_flags_schedule_health_and_live_worker_then_only_beat(
        self,
    ):
        with ClosedDeployHarness(
            self,
            initial_beat_state="stopped",
        ) as harness:
            result = harness.run("start-beat")

        self.assertEqual(result.process.returncode, 0, result.output)
        schedule_index = result.calls.index("schedule-check|closed")
        web_index = next(
            index
            for index, call in enumerate(result.calls)
            if call.startswith("web-state|")
            or call.startswith("system|curl ")
        )
        worker_index = next(
            index
            for index, call in enumerate(result.calls)
            if call.startswith("worker-state|")
            or call.startswith("worker-health|")
        )
        live_worker_index = result.calls.index(
            "race-live-worker-state|stopped"
        )
        beat_up_calls = [
            arguments
            for arguments in self.compose_operation_calls(result, "up")
            if "beat" in self.services_after_operation(arguments, "up")
        ]
        self.assertEqual(len(beat_up_calls), 1, result.calls)
        self.assertEqual(
            self.services_after_operation(beat_up_calls[0], "up"),
            ["beat"],
        )
        beat_up_log_index = next(
            index
            for index, call in enumerate(result.calls)
            if call.startswith("compose|")
            and shlex.split(call.split("|", 1)[1]) == beat_up_calls[0]
        )
        for prerequisite_index in (
            schedule_index,
            web_index,
            worker_index,
            live_worker_index,
        ):
            self.assertLess(prerequisite_index, beat_up_log_index, result.calls)
        self.assertEqual(result.beat_state, "running")

    def test_start_beat_failure_trap_never_starts_beat(self):
        with ClosedDeployHarness(
            self,
            initial_beat_state="stopped",
        ) as harness:
            result = harness.run(
                "start-beat",
                env={"P0_FAKE_SETTINGS_EXIT": "61"},
            )

        self.assertNotEqual(result.process.returncode, 0, result.output)
        self.assertEqual(result.beat_state, "stopped")
        self.assertEqual(
            [
                arguments
                for arguments in self.compose_operation_calls(result, "up")
                if "beat" in self.services_after_operation(arguments, "up")
            ],
            [],
            result.calls,
        )


class RaceLiveP0DeploymentWorkerQueueTests(
    DeploymentContractAssertions,
    SimpleTestCase,
):
    def test_only_one_exact_celery_queue_is_accepted(self):
        with ClosedDeployHarness(
            self,
            initial_beat_state="stopped",
        ) as harness:
            harness.set_worker_pid1_argv(
                "celery",
                "-A",
                "app",
                "worker",
                "--queues=celery",
                "--without-gossip",
            )
            result = harness.run("start-beat")

        self.assertEqual(result.process.returncode, 0, result.output)
        self.assertTrue(
            any(
                call.startswith("worker-pid1|")
                and "--queues=celery " in call
                for call in result.calls
            ),
            result.calls,
        )

    def test_non_exact_or_multiple_worker_queues_block_start_beat(self):
        invalid_argv = (
            (
                "comma-separated-live-queue",
                (
                    "celery",
                    "-A",
                    "app",
                    "worker",
                    "--queues=celery,race_live",
                ),
            ),
            (
                "celery-prefix",
                (
                    "celery",
                    "-A",
                    "app",
                    "worker",
                    "--queues=celery2",
                ),
            ),
            (
                "multiple-queue-options",
                (
                    "celery",
                    "-A",
                    "app",
                    "worker",
                    "--queues=celery",
                    "--queues=race_live",
                ),
            ),
            (
                "separate-multi-queue-value",
                (
                    "celery",
                    "-A",
                    "app",
                    "worker",
                    "--queues",
                    "celery,race_live",
                ),
            ),
        )
        for label, arguments in invalid_argv:
            with (
                self.subTest(label=label),
                ClosedDeployHarness(
                    self,
                    initial_beat_state="stopped",
                ) as harness,
            ):
                harness.set_worker_pid1_argv(*arguments)
                result = harness.run("start-beat")
                self.assertNotEqual(result.process.returncode, 0, result.output)
                self.assertEqual(result.beat_state, "stopped")
                self.assertEqual(
                    self.compose_operation_calls(result, "up"),
                    [],
                    result.calls,
                )


class RaceLiveP0DeploymentPostStartObservationTests(
    DeploymentContractAssertions,
    SimpleTestCase,
):
    def beat_up_calls(self, result: ScriptResult) -> list[list[str]]:
        return [
            arguments
            for arguments in self.compose_operation_calls(result, "up")
            if "beat" in self.services_after_operation(arguments, "up")
        ]

    def logical_minutes(self, result: ScriptResult) -> list[int]:
        return [
            int(call.split("|", 2)[1])
            for call in result.calls
            if call.startswith("logical-minute|")
        ]

    def assert_observation_failure_stops_beat(
        self,
        result: ScriptResult,
        *,
        failed_minute: int,
    ) -> None:
        self.assertNotEqual(result.process.returncode, 0, result.output)
        self.assertEqual(self.logical_minutes(result), list(range(1, failed_minute + 1)))
        self.assertEqual(len(self.beat_up_calls(result)), 1, result.calls)
        self.assertEqual(result.beat_state, "stopped")
        self.assertIn("stop-beat|stopped", result.calls)

    def test_third_minute_web_health_failure_stops_beat_immediately(self):
        with ClosedDeployHarness(
            self,
            initial_beat_state="stopped",
        ) as harness:
            result = harness.run(
                "start-beat",
                env={"P0_FAKE_WEB_FAIL_AT_MINUTE": "3"},
            )

        self.assert_observation_failure_stops_beat(result, failed_minute=3)

    def test_target_task_count_growth_stops_beat(self):
        with ClosedDeployHarness(
            self,
            initial_beat_state="stopped",
        ) as harness:
            result = harness.run(
                "start-beat",
                env={"P0_FAKE_TARGET_COUNT_GROW_AT_MINUTE": "3"},
            )

        self.assertIn(
            "queue-observation|minute=3|celery=11|race_live=22|selector=1|monitor=0",
            result.calls,
        )
        self.assert_observation_failure_stops_beat(result, failed_minute=3)

    def test_target_schedule_in_beat_log_stops_beat(self):
        with ClosedDeployHarness(
            self,
            initial_beat_state="stopped",
        ) as harness:
            result = harness.run(
                "start-beat",
                env={"P0_FAKE_BEAT_LOG_TARGET_AT_MINUTE": "3"},
            )

        self.assertIn("beat-log-check|minute=3|since=start", result.calls)
        self.assert_observation_failure_stops_beat(result, failed_minute=3)

    def test_race_live_worker_restarting_mid_observation_stops_beat(self):
        with ClosedDeployHarness(
            self,
            initial_beat_state="stopped",
        ) as harness:
            result = harness.run(
                "start-beat",
                env={"P0_FAKE_LIVE_WORKER_RESTART_AT_MINUTE": "3"},
            )

        self.assertIn(
            "observation|minute=3|race-live-worker=restarting",
            result.calls,
        )
        self.assert_observation_failure_stops_beat(result, failed_minute=3)

    def test_machine_queue_snapshot_runs_five_minutes_and_malformed_fails_closed(
        self,
    ):
        with ClosedDeployHarness(
            self,
            initial_beat_state="stopped",
        ) as harness:
            result = harness.run("start-beat")

        self.assertEqual(result.process.returncode, 0, result.output)
        self.assertEqual(self.logical_minutes(result), [1, 2, 3, 4, 5])
        self.assertEqual(len(self.beat_up_calls(result)), 1, result.calls)
        self.assertEqual(result.beat_state, "running")
        for minute in range(1, 6):
            self.assertIn(
                f"observation|minute={minute}|beat=running",
                result.calls,
            )
            self.assertIn(
                f"observation|minute={minute}|web=running",
                result.calls,
            )
            self.assertIn(
                f"observation|minute={minute}|worker=running",
                result.calls,
            )
            self.assertIn(
                f"observation|minute={minute}|race-live-worker=stopped",
                result.calls,
            )
            self.assertIn(
                f"queue-observation|minute={minute}|celery=11|race_live=22|selector=0|monitor=0",
                result.calls,
            )
            self.assertIn(
                f"beat-log-check|minute={minute}|since=start",
                result.calls,
            )

        with ClosedDeployHarness(
            self,
            initial_beat_state="stopped",
        ) as harness:
            malformed = harness.run(
                "start-beat",
                env={"P0_FAKE_QUEUE_SNAPSHOT_OUTPUT": "malformed"},
            )

        self.assertIn("queue-snapshot-output|override", malformed.calls)
        self.assertNotEqual(
            malformed.process.returncode,
            0,
            malformed.output,
        )
        self.assertIn("队列/task 计数格式不可确认", malformed.output)
        self.assertEqual(self.logical_minutes(malformed), [])
        self.assertEqual(self.beat_up_calls(malformed), [], malformed.calls)
        self.assertEqual(malformed.beat_state, "stopped")

    def test_queue_snapshot_disables_django_auto_import_banner(self):
        with ClosedDeployHarness(
            self,
            initial_beat_state="stopped",
        ) as harness:
            result = harness.run("start-beat")

        snapshot_calls = [
            arguments
            for arguments in self.compose_calls(result)
            if "run" in arguments
            and "manage.py" in arguments
            and "shell" in arguments
            and "json" in arguments
        ]
        self.assertTrue(snapshot_calls, result.calls)
        for arguments in snapshot_calls:
            self.assertIn("--no-imports", arguments, result.calls)
        self.assertNotIn(
            "queue-snapshot-output|django-auto-import-banner",
            result.calls,
        )
        self.assertEqual(result.process.returncode, 0, result.output)
        self.assertEqual(self.logical_minutes(result), [1, 2, 3, 4, 5])
        self.assertEqual(len(snapshot_calls), 6, result.calls)
        self.assertEqual(
            result.calls.count("queue-snapshot-command|no-imports"),
            6,
            result.calls,
        )
        self.assertEqual(len(self.beat_up_calls(result)), 1, result.calls)
        self.assertEqual(result.beat_state, "running")

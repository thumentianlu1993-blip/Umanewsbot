"""Focused contract tests for the single migration owner change.

Covers docs/changes/fix-single-migration-owner/test_cases.md T01-T16, T18, T19
(T17 adjacent Django regressions are run by the main thread).

All tests are SimpleTestCase based: no database, no network, no real Docker.
Shell behaviour is exercised with fake `docker`/`git`/`python` executables and
a copied deploy tree inside temporary directories.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = ROOT / "deploy"
THIS_FILE = Path(__file__).resolve()

RELEASE_TASK_SCRIPT_REL = "deploy/docker/run-release-tasks.sh"
RELEASE_TASK_CONTAINER_PATH = "/app/deploy/docker/run-release-tasks.sh"
HOST_WRAPPER_REL = "deploy/run_release_tasks.sh"
LOCK_SCRIPT_REL = "deploy/deployment_lock.sh"
HEALTH_WAIT_REL = "deploy/wait_for_compose_service_healthy.sh"
ORCHESTRATION_REL = "deploy/run_application_release.sh"
MANUAL_RELEASE_REL = "deploy/manual_release.sh"
RESUME_SCRIPT_REL = "deploy/resume_stopped_release.sh"
PRE_CONTRACT_BRIDGE_REL = "deploy/rollback_pre_single_owner.sh"
DRAIN_SCRIPT_REL = "deploy/wait_for_celery_drain.sh"

COMPOSE_STANDARD = "docker-compose.prod.yml"
COMPOSE_LOWCOST = "docker-compose.prod.lowcost.yml"
ALLOWED_COMPOSE_FILES = (COMPOSE_STANDARD, COMPOSE_LOWCOST)

DEPLOY_DOC_PATHS = (
    ROOT / "docs" / "deploy_production.md",
    ROOT / "docs" / "rollback_guide.md",
    ROOT / "docs" / "deploy_runbook.md",
)

EXPECTED_RELEASE_RUN_ARGV = [
    "run",
    "--rm",
    "--no-deps",
    "web",
    RELEASE_TASK_CONTAINER_PATH,
]

# 16+ character fake container ids so health-wait output must truncate to 12.
SERVICE_IDS = {
    "web": "cidweb111aaa2222",
    "worker": "cidworker222bbbb",
    "beat": "cidbeat3333cccc",
    "race_live_worker": "cidrlive4444dddd",
    "race_sync_v2_worker": "cidrsync7777gggg",
    "db": "ciddb5555555eeee",
    "redis": "cidredis6666ffff",
}

LOCK_TOKEN_A = "tok-alpha-0123456789abcdef0123456789abcdef"
LOCK_TOKEN_B = "tok-bravo-fedcba9876543210fedcba9876543210"


FAKE_DOCKER = r"""#!/bin/sh
# Fake docker for the single-migration-owner harness.
# Logs every invocation to $FAKE_CALL_LOG, serves state from $FAKE_STATE_DIR.
set -u
log="${FAKE_CALL_LOG:?FAKE_CALL_LOG required}"
state="${FAKE_STATE_DIR:?FAKE_STATE_DIR required}"
printf 'docker %s\n' "$*" >> "$log"

rc_file() {
  f="$state/rc-$1"
  if [ -f "$f" ]; then cat "$f"; else printf '%s\n' "${2:-0}"; fi
}

pop_line() {
  f="$1"
  line="$(head -n 1 "$f")"
  count="$(wc -l < "$f" | tr -d ' ')"
  if [ "${count:-0}" -gt 1 ]; then
    tail -n +2 "$f" > "$f.pop" && mv "$f.pop" "$f"
  fi
  printf '%s\n' "$line"
}

cmd="${1:-}"
if [ $# -gt 0 ]; then shift; fi
case "$cmd" in
  image)
    case " $* " in
      *org.opencontainers.image.revision*)
        if [ -f "$state/git-rev-parse-head" ]; then cat "$state/git-rev-parse-head"; fi
        ;;
      *" inspect "*)
        ref=""
        for a in "$@"; do
          case "$a" in --format|--format=*) ;; '{{.Id}}') ;; *) ref="$a" ;; esac
        done
        case "$ref" in
          umanewsbot:prod)
            if [ -f "$state/prod-image-id" ]; then cat "$state/prod-image-id"; else printf '%s\n' 'sha256:candidate-image-id'; fi
            ;;
          umanewsbot:rollback-control-*)
            if [ -f "$state/control-image-id" ]; then cat "$state/control-image-id"; else printf '%s\n' 'sha256:candidate-image-id'; fi
            ;;
          umanewsbot:rollback-target-*)
            if [ -f "$state/target-image-id-seq" ]; then
              pop_line "$state/target-image-id-seq"
            elif [ -f "$state/target-image-id" ]; then
              cat "$state/target-image-id"
            else
              printf '%s\n' 'sha256:candidate-image-id'
            fi
            ;;
          sha256:*) printf '%s\n' "$ref" ;;
          *) printf '%s\n' 'sha256:candidate-image-id' ;;
        esac
        ;;
    esac
    exit "$(rc_file image)"
    ;;
  compose)
    while [ $# -gt 0 ]; do
      case "$1" in
        -f)
          case "${2:-}" in
            *target-collectstatic.*.yml)
              if [ -f "$2" ]; then cp "$2" "$state/last-target-collectstatic-override.yml"; fi
              ;;
          esac
          shift 2
          ;;
        *) break ;;
      esac
    done
    sub="${1:-}"
    if [ $# -gt 0 ]; then shift; fi
    case "$sub" in
      version)
        echo "fake-docker-compose v2.0.0"
        exit 0
        ;;
      ps)
        if [ "${1:-}" = "-q" ]; then
          svc="${2:-}"
          if [ -f "$state/rc-ps-q-$svc" ]; then exit "$(cat "$state/rc-ps-q-$svc")"; fi
          if [ -f "$state/rc-compose-ps" ]; then exit "$(cat "$state/rc-compose-ps")"; fi
          seq="$state/ps-seq-$svc"
          if [ -f "$seq" ]; then pop_line "$seq"; exit 0; fi
          f="$state/ps-$svc"
          if [ -f "$f" ]; then cat "$f"; fi
          exit 0
        fi
        exit "$(rc_file compose-ps)"
        ;;
      exec)
        case " $* " in
          *manage_historical_batch_runner*)
            case " $* " in
              *" status "*)
                printf '%s\n' '{"state": "idle"}'
                ;;
            esac
            exit "$(rc_file exec-preflight)"
            ;;
          *" shell "*)
            case " $* " in
              *"print(connection.vendor)"*)
                if [ -f "$state/database-vendor" ]; then
                  cat "$state/database-vendor"
                else
                  printf '%s\n' postgresql
                fi
                exit "$(rc_file database-vendor)"
                ;;
              *historical-initial-install-0070-or-later*)
                if [ -f "$state/initial-install-schema" ]; then
                  cat "$state/initial-install-schema"
                else
                  printf '%s\n' historical-initial-install-0070-or-later
                fi
                exit "$(rc_file initial-install-schema)"
                ;;
            esac
            if [ -f "$state/drain-strict" ] && [ -n "${EXPECTED_CELERY_WORKERS:-}" ]; then
              missing=""
              for node in $EXPECTED_CELERY_WORKERS; do
                case " $* " in
                  *"$node"*) ;;
                  *) missing="$missing $node" ;;
                esac
                if [ -f "$state/drain-nodes" ]; then
                  case " $(cat "$state/drain-nodes") " in
                    *" $node "*) ;;
                    *) missing="$missing $node" ;;
                  esac
                else
                  missing="$missing $node"
                fi
              done
              if [ -n "$missing" ]; then
                echo "celery snapshot missing expected nodes:$missing" >&2
                exit 1
              fi
            fi
            exit "$(rc_file exec-drain)"
            ;;
          *)
            exit "$(rc_file exec)"
            ;;
        esac
        ;;
      run)
        run_rc_name="compose-run"
        case " $* " in
          *" nginx nginx -t "*)
            run_rc_name="compose-nginx-config"
            ;;
          *" manage.py collectstatic --noinput "*)
            run_rc_name="compose-target-collectstatic"
            ;;
          *" /app/deploy/docker/run-release-tasks.sh "*)
            case " $* " in
              *" RELEASE_TASK_PHASE=complete-intent "*) run_rc_name="compose-complete-intent" ;;
              *)
                if [ -f "$state/rc-compose-release-task" ]; then
                  run_rc_name="compose-release-task"
                fi
                ;;
            esac
            ;;
        esac
        output_path=""
        handoff_action="deploy"
        for arg in "$@"; do
          case "$arg" in
            --output-path=*) output_path="${arg#--output-path=}" ;;
            --action=*) handoff_action="${arg#--action=}" ;;
          esac
        done
        if [ -n "$output_path" ] && [ "$(rc_file "$run_rc_name")" -eq 0 ]; then
          attempt_mode="not-required"
          if [ -f "$state/preflight-attempt-mode" ]; then attempt_mode="$(cat "$state/preflight-attempt-mode")"; fi
          printf '%s' "{\"artifact_sha256\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"database_identity_sha256\":\"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd\",\"handoff_action\":\"$handoff_action\",\"recovery_intent_mode\":\"$attempt_mode\"}" > "$output_path"
          chmod 600 "$output_path"
        fi
        case " $* " in
          *" RELEASE_TASK_PHASE=migrate-verify "*)
            case " $* " in
              *" RESTRICTED_RECOVERY_ATTEMPT_MODE=required "*)
                marker_path=""
                for arg in "$@"; do
                  case "$arg" in RESTRICTED_RECOVERY_MARKER_PATH=*) marker_path="${arg#*=}" ;; esac
                done
                if [ -n "$marker_path" ]; then
                  mkdir -p "$(dirname "$marker_path")"
                  printf '%s\n' '{"marker_sha256":"fake"}' > "$marker_path"
                  chmod 600 "$marker_path"
                fi
                printf '%s\n' 'release-marker-identity=1:2'
                ;;
              *) printf '%s\n' 'release-marker-identity=none' ;;
            esac
            ;;
        esac
        exit "$(rc_file "$run_rc_name")"
        ;;
      stop)
        last=""
        for a in "$@"; do last="$a"; done
        if [ -n "$last" ] && [ -f "$state/rc-stop-$last" ]; then
          exit "$(cat "$state/rc-stop-$last")"
        fi
        exit "$(rc_file stop)"
        ;;
      up)
        first=""
        for a in "$@"; do
          case "$a" in
            -*) ;;
            *) first="$a"; break ;;
          esac
        done
        if [ -n "$first" ] && [ -f "$state/rc-up-$first" ]; then
          exit "$(cat "$state/rc-up-$first")"
        fi
        exit "$(rc_file up)"
        ;;
      build)
        if [ "$(rc_file build)" -eq 0 ] && [ -f "$state/prod-image-id" ]; then
          printf '%s\n' 'sha256:candidate-image-id' > "$state/prod-image-id"
        fi
        exit "$(rc_file build)"
        ;;
      pull)
        exit "$(rc_file pull)"
        ;;
      config)
        exit "$(rc_file config)"
        ;;
      *)
        exit "$(rc_file compose-other)"
        ;;
    esac
    ;;
  inspect)
    if [ -f "$state/rc-inspect" ]; then exit "$(cat "$state/rc-inspect")"; fi
    id=""
    skip=0
    for a in "$@"; do
      if [ "$skip" -eq 1 ]; then skip=0; continue; fi
      case "$a" in
        --format) skip=1 ;;
        --format=*|-*) ;;
        *) id="$a" ;;
      esac
    done
    if [ -n "$id" ] && [ -f "$state/rc-inspect-$id" ]; then
      exit "$(cat "$state/rc-inspect-$id")"
    fi
    if [ -n "$id" ] && [ -f "$state/inspect-seq-$id" ]; then
      pop_line "$state/inspect-seq-$id"
      exit 0
    fi
    if [ -n "$id" ] && [ -f "$state/inspect-$id" ]; then
      cat "$state/inspect-$id"
    else
      echo "false none"
    fi
    exit 0
    ;;
  tag)
    source_ref="${1:-}"
    target_ref="${2:-}"
    if [ -f "$state/prod-image-id" ]; then
      case "$source_ref" in
        umanewsbot:prod) source_id="$(cat "$state/prod-image-id")" ;;
        sha256:*) source_id="$source_ref" ;;
        umanewsbot:rollback-control-*) source_id="$(cat "$state/control-image-id")" ;;
        umanewsbot:rollback-target-*) source_id="$(cat "$state/target-image-id")" ;;
        *) source_id="sha256:candidate-image-id" ;;
      esac
      case "$target_ref" in
        umanewsbot:prod) printf '%s\n' "$source_id" > "$state/prod-image-id" ;;
        umanewsbot:rollback-control-*) printf '%s\n' "$source_id" > "$state/control-image-id" ;;
        umanewsbot:rollback-target-*) printf '%s\n' "$source_id" > "$state/target-image-id" ;;
      esac
    fi
    exit "$(rc_file tag)"
    ;;
  container|network)
    exit "$(rc_file "$cmd" 1)"
    ;;
  *)
    exit "$(rc_file docker-other)"
    ;;
esac
"""

FAKE_GIT = r"""#!/bin/sh
set -u
log="${FAKE_CALL_LOG:?FAKE_CALL_LOG required}"
state="${FAKE_STATE_DIR:?FAKE_STATE_DIR required}"
printf 'git %s\n' "$*" >> "$log"
cmd="${1:-}"
if [ $# -gt 0 ]; then shift; fi
f="$state/rc-git-$cmd"
if [ -f "$f" ]; then exit "$(cat "$f")"; fi
case "$cmd" in
  symbolic-ref)
    if [ -f "$state/git-head-ref" ]; then cat "$state/git-head-ref"; exit 0; fi
    exit 1
    ;;
  rev-parse)
    # `git rev-parse HEAD` (binding the current checkout) reads
    # git-rev-parse-head; `git rev-parse --verify <ref>` reads
    # git-rev-parse-output.
    case " $* " in
      *" HEAD "*)
        if [ -f "$state/git-rev-parse-head" ]; then cat "$state/git-rev-parse-head"; fi
        ;;
      *)
        if [ -f "$state/git-rev-parse-output" ]; then cat "$state/git-rev-parse-output"; fi
        ;;
    esac
    exit 0
    ;;
  cat-file)
    # Optional per-path failure list: one missing path per line in
    # $FAKE_STATE_DIR/git-cat-file-missing; "git cat-file -e <ref>:<path>"
    # exits 1 when <path> is listed.
    if [ -f "$state/git-cat-file-missing" ]; then
      target=""
      for a in "$@"; do
        case "$a" in
          *:*) target="${a#*:}" ;;
        esac
      done
      if [ -n "$target" ]; then
        while IFS= read -r missing; do
          if [ -n "$missing" ] && [ "$target" = "$missing" ]; then
            exit 1
          fi
        done < "$state/git-cat-file-missing"
      fi
    fi
    exit 0
    ;;
  show)
    case "${1:-}" in
      *0071_historical_calendar_release_b.py)
        [ -f "$state/git-show-0071" ] || exit 1
        cat "$state/git-show-0071"
        exit 0
        ;;
      *0072_add_extended_racing_regions.py)
        [ -f "$state/git-show-0072" ] || exit 1
        cat "$state/git-show-0072"
        exit 0
        ;;
      *0073_lifecycle_enforce_registry.py)
        [ -f "$state/git-show-0073" ] || exit 1
        cat "$state/git-show-0073"
        exit 0
        ;;
      *0074_race_data_sync_r0_control_plane.py)
        [ -f "$state/git-show-0074" ] || exit 1
        cat "$state/git-show-0074"
        exit 0
        ;;
      *0075_race_data_source_priority_and_reported_position.py)
        [ -f "$state/git-show-0075" ] || exit 1
        cat "$state/git-show-0075"
        exit 0
        ;;
    esac
    exit 1
    ;;
  checkout)
    checkout_target=""
    for checkout_arg in "$@"; do
      case "$checkout_arg" in --detach) ;; *) checkout_target="$checkout_arg" ;; esac
    done
    if [ -f "$state/git-stateful-head" ]; then
      target=""
      detached=false
      for a in "$@"; do
        if [ "$a" = "--detach" ]; then detached=true; else target="$a"; fi
      done
      if [ "$detached" = true ]; then
        rm -f "$state/git-head-ref"
        printf '%s\n' "$target" > "$state/git-rev-parse-head"
      else
        case "$target" in
          refs/heads/*)
            printf '%s\n' "$target" > "$state/git-head-ref"
            cat "$state/git-original-head-oid" > "$state/git-rev-parse-head"
            ;;
          *)
            current_branch=""
            if [ -f "$state/git-original-head-ref" ]; then current_branch="$(cat "$state/git-original-head-ref")"; current_branch="${current_branch#refs/heads/}"; fi
            if [ -n "$current_branch" ] && [ "$target" = "$current_branch" ]; then
              cat "$state/git-original-head-ref" > "$state/git-head-ref"
              cat "$state/git-original-head-oid" > "$state/git-rev-parse-head"
            else
              rm -f "$state/git-head-ref"
              printf '%s\n' "$target" > "$state/git-rev-parse-head"
            fi
            ;;
        esac
      fi
    fi
    if [ -f "$state/git-checkout-pre-v2-control" ]; then
      original_branch=""
      if [ -f "$state/git-original-head-ref" ]; then original_branch="$(cat "$state/git-original-head-ref")"; original_branch="${original_branch#refs/heads/}"; fi
      case "$checkout_target" in
        refs/heads/*|"$original_branch")
          cp "$state/original-preflight.sh" deploy/run_historical_calendar_release_b_preflight.sh
          cp "$state/original-application.sh" deploy/run_application_release.sh
          cp "$state/original-release-tasks.sh" deploy/run_release_tasks.sh
          ;;
        *)
          if [ -f "$state/git-original-head-oid" ] && [ "$checkout_target" = "$(cat "$state/git-original-head-oid")" ]; then
            cp "$state/original-preflight.sh" deploy/run_historical_calendar_release_b_preflight.sh
            cp "$state/original-application.sh" deploy/run_application_release.sh
            cp "$state/original-release-tasks.sh" deploy/run_release_tasks.sh
          else
            if [ ! -f "$state/original-preflight.sh" ]; then
              cp deploy/run_historical_calendar_release_b_preflight.sh "$state/original-preflight.sh"
              cp deploy/run_application_release.sh "$state/original-application.sh"
              cp deploy/run_release_tasks.sh "$state/original-release-tasks.sh"
            fi
            printf '%s\n' '#!/bin/sh' 'exit 0' > deploy/run_historical_calendar_release_b_preflight.sh
            printf '%s\n' '#!/bin/sh' 'echo target-v1-application-helper-used >&2' 'exit 97' > deploy/run_application_release.sh
            printf '%s\n' '#!/bin/sh' 'echo target-v1-release-helper-used >&2' 'exit 98' > deploy/run_release_tasks.sh
          fi
          ;;
      esac
      chmod +x deploy/run_historical_calendar_release_b_preflight.sh deploy/run_application_release.sh deploy/run_release_tasks.sh
    fi
    exit 0
    ;;
esac
exit 0
"""

FAKE_PYTHON = r"""#!/bin/sh
set -u
log="${FAKE_CALL_LOG:?FAKE_CALL_LOG required}"
printf 'python %s\n' "$*" >> "$log"
rc=0
case " $* " in
  *" check_production_database_vendor "*)
    rc="${FAKE_PY_DATABASE_VENDOR_RC:-0}" ;;
  *" ensure_historical_calendar_recovery_intent "*)
    case " $* " in
      *" --attempt-mode=required "*)
        printf '%s\n' '{"marker_device": 1, "marker_inode": 2, "ok": true, "status": "verified"}' ;;
      *) printf '%s\n' '{"ok": true, "status": "not-required"}' ;;
    esac ;;
  *" migrate "*)
    rc="${FAKE_PY_MIGRATE_RC:-0}" ;;
  *" collectstatic "*)
    rc="${FAKE_PY_COLLECTSTATIC_RC:-0}" ;;
esac
exit "$rc"
"""


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


class Harness:
    """A copied deploy tree plus fake docker/git inside a temp directory."""

    def __init__(self, base: Path):
        self.base = base
        self.work = base / "repo"
        self.work.mkdir()
        shutil.copytree(DEPLOY_DIR, self.work / "deploy")
        for script in (self.work / "deploy").rglob("*.sh"):
            script.chmod(0o755)
        persistent_runtime = base / "persistent-runtime"
        for relative in (
            "horse_profile_completion",
            "upcoming_racecard_urls",
            "secrets",
            "race_live_racecards",
            "race_live_publications",
            "race_data_sync",
        ):
            (persistent_runtime / relative).mkdir(parents=True, exist_ok=True)
        for state_dir in ("cache", "batches", "review", "budget"):
            (persistent_runtime / "horse_profile_completion" / state_dir).mkdir()
        persistent_certs = base / "persistent-certs"
        live_certs = persistent_certs / "letsencrypt/live/umafans.run"
        live_certs.mkdir(parents=True)
        (live_certs / "fullchain.pem").write_text("test certificate\n", encoding="utf-8")
        (live_certs / "privkey.pem").write_text("test private key\n", encoding="utf-8")
        release_runtime = self.work / "runtime"
        release_runtime.mkdir()
        tracked_horse_runtime = release_runtime / "horse_profile_completion"
        tracked_horse_runtime.mkdir()
        for state_dir in ("cache", "batches", "review", "budget"):
            (tracked_horse_runtime / state_dir).symlink_to(
                persistent_runtime / "horse_profile_completion" / state_dir
            )
        for relative in (
            "upcoming_racecard_urls",
            "secrets",
            "race_live_racecards",
            "race_live_publications",
            "race_data_sync",
        ):
            (release_runtime / relative).symlink_to(persistent_runtime / relative)
        (self.work / "deploy/certs/letsencrypt").symlink_to(
            persistent_certs / "letsencrypt"
        )
        (self.work / ".env").write_text(
            f"UMANEWS_PERSISTENT_RUNTIME_ROOT={persistent_runtime}\n"
            f"UMANEWS_TLS_CERT_ROOT={persistent_certs}\n",
            encoding="utf-8",
        )
        for name in ALLOWED_COMPOSE_FILES:
            (self.work / name).write_text("services: {}\n", encoding="utf-8")
        self.fakes = base / "fakes"
        self.fakes.mkdir()
        _write_executable(self.fakes / "docker", FAKE_DOCKER)
        _write_executable(self.fakes / "git", FAKE_GIT)
        self.state = base / "state"
        self.state.mkdir()
        shutil.copyfile(
            ROOT / "server/stable/migrations/0071_historical_calendar_release_b.py",
            self.state / "git-show-0071",
        )
        shutil.copyfile(
            ROOT / "server/stable/migrations/0072_add_extended_racing_regions.py",
            self.state / "git-show-0072",
        )
        shutil.copyfile(
            ROOT / "server/stable/migrations/0073_lifecycle_enforce_registry.py",
            self.state / "git-show-0073",
        )
        shutil.copyfile(
            ROOT / "server/stable/migrations/0074_race_data_sync_r0_control_plane.py",
            self.state / "git-show-0074",
        )
        shutil.copyfile(
            ROOT
            / "server/stable/migrations/0075_race_data_source_priority_and_reported_position.py",
            self.state / "git-show-0075",
        )
        self.log = base / "calls.log"
        self.log.touch()
        self.lock_dir = base / "deployment.lock"

    def env(self, **overrides) -> dict:
        env = {
            "PATH": f"{self.fakes}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.base),
            "FAKE_CALL_LOG": str(self.log),
            "FAKE_STATE_DIR": str(self.state),
            "DEPLOYMENT_LOCK_DIR": str(self.lock_dir),
            "CELERY_DRAIN_TIMEOUT_SECONDS": "2",
            "SERVICE_HEALTH_TIMEOUT_SECONDS": "2",
            "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256": "a" * 64,
        }
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def run_script(self, script_rel: str, *args: str, timeout: int = 90, **env_overrides):
        return subprocess.run(
            ["sh", f"./{script_rel}", *args],
            cwd=self.work,
            env=self.env(**env_overrides),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def set_state(self, name: str, content: str) -> None:
        (self.state / name).write_text(content, encoding="utf-8")

    def set_rc(self, name: str, rc: int) -> None:
        self.set_state(f"rc-{name}", f"{rc}\n")

    def clear_log(self) -> None:
        self.log.write_text("", encoding="utf-8")

    def log_lines(self) -> list:
        return self.log.read_text(encoding="utf-8").splitlines()

    def events(self) -> list:
        """Parse the fake call log into (kind, compose_file, argv) tuples."""
        evts = []
        for line in self.log_lines():
            parts = line.split()
            if not parts:
                continue
            if parts[:2] == ["docker", "compose"]:
                rest = parts[2:]
                compose_file = None
                while len(rest) >= 2 and rest[:1] == ["-f"]:
                    if compose_file is None:
                        compose_file = rest[1]
                    rest = rest[2:]
                evts.append(("compose", compose_file, rest))
            elif parts[0] in ("docker", "git", "python"):
                evts.append((parts[0], None, parts[1:]))
        return evts


def seed_services(
    harness: Harness,
    *,
    web: str = "running",
    race_live: str = "running",
    race_sync: str = "absent",
) -> None:
    """Seed fake service state. Modes: running / stopped / absent."""
    harness.set_state(
        "git-rev-parse-head",
        "0123456789abcdef0123456789abcdef01234567\n",
    )
    for service, cid in SERVICE_IDS.items():
        if service == "web":
            mode = web
        elif service == "race_live_worker":
            mode = race_live
        elif service == "race_sync_v2_worker":
            mode = race_sync
        else:
            mode = "running"
        if mode == "absent":
            continue
        harness.set_state(f"ps-{service}", f"{cid}\n")
        inspect_state = "true healthy" if mode == "running" else "false exited"
        harness.set_state(f"inspect-{cid}", f"{inspect_state}\n")


def acquire_lock(harness: Harness, token: str, action: str = "deploy"):
    return harness.run_script(
        LOCK_SCRIPT_REL,
        "acquire",
        DEPLOYMENT_LOCK_ACTION=action,
        DEPLOYMENT_LOCK_TOKEN=token,
    )


def compose_calls(evts: list) -> list:
    """Compose calls excluding the wrapper's `docker compose version` probe."""
    return [
        (compose_file, argv)
        for kind, compose_file, argv in evts
        if kind == "compose" and argv[:1] != ["version"]
    ]


def first_index(evts: list, predicate) -> int | None:
    for index, event in enumerate(evts):
        if predicate(event):
            return index
    return None


def is_exec_migrate(event) -> bool:
    kind, _cf, argv = event
    return kind == "compose" and argv[:1] == ["exec"] and "migrate" in argv


def is_drain_exec(event) -> bool:
    kind, _cf, argv = event
    return kind == "compose" and argv[:1] == ["exec"] and "shell" in argv


def is_release_run(event) -> bool:
    kind, _cf, argv = event
    return (
        kind == "compose"
        and argv[:3] == ["run", "--rm", "--no-deps"]
        and argv[-2:] == ["web", RELEASE_TASK_CONTAINER_PATH]
        and "RELEASE_B_PREFLIGHT_ARTIFACT_PATH=" in " ".join(argv)
    )


# Files whose migrate/collectstatic mentions are assertion strings inside
# test code, not executable entry points (same rationale as excluding this
# test file itself; deliberately NOT a blanket test_*.py exclusion).
ASSERTION_ONLY_SCAN_EXCLUSIONS = {
    # assertFalse any("manage.py migrate" in call) — a negative assertion
    # string, not a migration entry point.
    "server/stable/test_race_live_p0_deployment_contract.py",
    "server/stable/test_migration_history_repair.py",
}


def _scan_repo_text_files():
    excluded_dirs = {
        "docs",
        "__pycache__",
        "node_modules",
        "staticfiles",
        "media",
    }
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(ROOT)
        parts = rel.parts
        if any(part.startswith(".") for part in parts):
            continue
        if parts[0] in excluded_dirs:
            continue
        if parts[:3] == ("server", "stable", "migrations"):
            continue
        if path.resolve() == THIS_FILE:
            continue
        if str(rel) in ASSERTION_ONLY_SCAN_EXCLUSIONS:
            continue
        if path.suffix.lower() in {".md", ".markdown", ".rst"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        yield str(rel), text


class MigrationCommandOwnershipTests(SimpleTestCase):
    """T01/T02: exactly one owner for migrate and collectstatic."""

    def test_t01_migrate_noinput_has_exactly_one_owner(self):
        hits = {}
        for rel, text in _scan_repo_text_files():
            count = len(re.findall(r"manage\.py\s+migrate\s+--noinput", text))
            if count:
                hits[rel] = count
        self.assertEqual(hits, {RELEASE_TASK_SCRIPT_REL: 1})

    def test_t01_no_migrate_variant_or_hidden_entry_outside_release_task(self):
        hits = {}
        for rel, text in _scan_repo_text_files():
            count = len(re.findall(r"manage\.py\s+migrate\b", text))
            if count:
                hits[rel] = count
        self.assertEqual(hits, {RELEASE_TASK_SCRIPT_REL: 1})
        call_command_hits = []
        for rel, text in _scan_repo_text_files():
            if rel.startswith("deploy/") and re.search(
                r"call_command\(\s*['\"]migrate", text
            ):
                call_command_hits.append(rel)
        self.assertEqual(call_command_hits, [])

    def test_t02_collectstatic_noinput_has_exactly_one_owner(self):
        # Approved exception (user-sanctioned): the race-live P0 closed-admission
        # one-shot script deploy/deploy_race_live_p0_closed.sh may run a single
        # collectstatic via `run --rm --no-deps web` before `up web`, because it
        # is itself a single-process release path gated by an empty migration
        # plan. Every other file must still have zero occurrences.
        p0_exception = "deploy/deploy_race_live_p0_closed.sh"
        allowed = {
            RELEASE_TASK_SCRIPT_REL: 1,
            HOST_WRAPPER_REL: 1,
            p0_exception: 1,
        }
        hits = {}
        for rel, text in _scan_repo_text_files():
            count = len(re.findall(r"manage\.py\s+collectstatic\s+--noinput", text))
            if count:
                hits[rel] = count
        self.assertEqual(hits, allowed)
        variant_hits = {}
        for rel, text in _scan_repo_text_files():
            count = len(re.findall(r"manage\.py\s+collectstatic\b", text))
            if count:
                variant_hits[rel] = count
        self.assertEqual(variant_hits, allowed)
        # The exception only holds while the p0 script owns no migration entry
        # and proves an empty migration plan (verify_migration_plan_zero) both
        # before and after the candidate Django check.
        p0_text = (ROOT / p0_exception).read_text(encoding="utf-8")
        self.assertNotIn(
            "manage.py migrate",
            p0_text,
            "the collectstatic exception script must not own a migration entry",
        )
        verify_calls = re.findall(r"(?m)^\s*verify_migration_plan_zero\s*$", p0_text)
        self.assertEqual(
            len(verify_calls),
            2,
            "the collectstatic exception requires exactly two "
            "verify_migration_plan_zero call sites in the p0 script",
        )

    def test_t02_p0_exception_script_uses_shared_deployment_lock(self):
        # The approved collectstatic exception only holds while the p0 script is
        # fenced by the shared deployment lock: acquire with its own action
        # before the first stateful compose call, plus a release trap.
        script = ROOT / "deploy" / "deploy_race_live_p0_closed.sh"
        text = script.read_text(encoding="utf-8")
        self.assertIn("DEPLOYMENT_LOCK_ACTION=p0-closed-admission", text)
        self.assertIn("deployment_lock.sh release", text)
        self.assertIn("trap", text)
        lines = text.splitlines()
        acquire = next(
            (
                index
                for index, line in enumerate(lines)
                if "deployment_lock.sh" in line and "acquire" in line
            ),
            None,
        )
        self.assertIsNotNone(
            acquire, "p0 script must acquire the shared deployment lock"
        )
        first_stateful = next(
            (
                index
                for index, line in enumerate(lines)
                if '"$COMPOSE"' in line and (" stop " in line or " build " in line)
            ),
            None,
        )
        self.assertIsNotNone(first_stateful)
        self.assertLess(
            acquire,
            first_stateful,
            "p0 script must acquire the deployment lock before its first "
            "stateful compose stop/build call",
        )


class StartWebEntrypointTests(SimpleTestCase):
    """T03: start-web.sh waits for dependencies then only runs gunicorn."""

    def test_t03_start_web_is_pure_application_start(self):
        script = DEPLOY_DIR / "docker" / "start-web.sh"
        self.assertTrue(script.is_file(), f"missing {script}")
        text = script.read_text(encoding="utf-8")
        self.assertIn("wait_for_services.py", text)
        self.assertIn("seed_admin", text)
        self.assertIn("exec gunicorn", text)
        self.assertNotIn("migrate", text)
        self.assertNotIn("collectstatic", text)
        self.assertNotIn("run-release-tasks", text)


class ReleaseTasksContainerScriptTests(SimpleTestCase):
    """T04: normal release stays whole; rollback control phases never collect static."""

    def _script_path(self) -> Path:
        script = DEPLOY_DIR / "docker" / "run-release-tasks.sh"
        self.assertTrue(
            script.is_file(),
            "missing deploy/docker/run-release-tasks.sh (single release task entry)",
        )
        return script

    def _run_copy(self, tmp: Path, **env_overrides):
        original = self._script_path().read_text(encoding="utf-8")
        # The production script targets container paths (/app/...). Run a
        # path-normalized copy against the fake python to observe ordering.
        rewritten = original.replace("/app", str(tmp / "containerfs"))
        (tmp / "containerfs" / "server").mkdir(parents=True)
        copy_path = tmp / "run-release-tasks.sh"
        _write_executable(copy_path, rewritten)
        fakes = tmp / "fakes"
        fakes.mkdir(exist_ok=True)
        _write_executable(fakes / "python", FAKE_PYTHON)
        log = tmp / "python-calls.log"
        log.touch()
        (tmp / "preflight.json").write_text(
            '{"handoff_action":"deploy","recovery_intent_mode":"not-required"}\n',
            encoding="utf-8",
        )
        env = {
            "PATH": f"{fakes}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(tmp),
            "FAKE_CALL_LOG": str(log),
            "RELEASE_B_PREFLIGHT_ARTIFACT_PATH": str(tmp / "preflight.json"),
            "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256": "a" * 64,
            "EXPECTED_CANDIDATE_COMMIT": "b" * 40,
            "EXPECTED_CANDIDATE_IMAGE_ID": "sha256:" + "c" * 64,
            "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256": "d" * 64,
            "RESTRICTED_RECOVERY_ATTEMPT_MODE": "not-required",
            "EXPECTED_COMPOSE_FILE": COMPOSE_STANDARD,
            "EXPECTED_DEPLOYMENT_LOCK_TOKEN_SHA256": "e" * 64,
            "RESTRICTED_RECOVERY_MARKER_PATH": str(tmp / "restricted.json"),
        }
        env.update(env_overrides)
        result = subprocess.run(
            ["sh", str(copy_path)],
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        return result, log.read_text(encoding="utf-8").splitlines()

    def _stages(self, lines) -> list:
        stages = []
        for line in lines:
            if "wait_for_services" in line:
                stages.append("wait")
            elif "verify_historical_calendar_release_b_handoff" in line:
                stages.append("verify")
            elif "ensure_historical_calendar_recovery_intent" in line:
                stages.append("intent")
            elif " migrate " in f" {line} ":
                stages.append("migrate")
            elif "complete_historical_calendar_restricted_recovery" in line:
                stages.append("complete")
            elif " collectstatic " in f" {line} ":
                stages.append("collectstatic")
        return stages

    def test_t04_static_contract_of_release_task_script(self):
        text = self._script_path().read_text(encoding="utf-8")
        self.assertIn("set -e", text)
        self.assertIn("cd /app/server", text)
        self.assertIn("python /app/deploy/docker/wait_for_services.py", text)
        self.assertIn("python manage.py migrate --noinput", text)
        self.assertIn("python manage.py collectstatic --noinput", text)
        self.assertNotIn("gunicorn", text)
        self.assertNotIn("celery", text)
        self.assertNotIn("seed_admin", text)

    def test_t04_wait_then_migrate_then_collectstatic_in_order(self):
        with TemporaryDirectory() as tmp:
            result, lines = self._run_copy(Path(tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self._stages(lines),
            ["wait", "verify", "intent", "migrate", "complete", "collectstatic"],
        )

    def test_t04_migrate_failure_skips_collectstatic(self):
        with TemporaryDirectory() as tmp:
            result, lines = self._run_copy(Path(tmp), FAKE_PY_MIGRATE_RC="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._stages(lines), ["wait", "verify", "intent", "migrate"])

    def test_initial_install_intent_is_durable_before_a_migrate_crash(self):
        bridge = (ROOT / "deploy/run_historical_initial_install_release.sh").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            bridge.index("RELEASE_B_PREFLIGHT_ACTION=initial-install"),
            bridge.index("run_application_release.sh"),
        )
        self.assertIn('RESTRICTED_RECOVERY_ATTEMPT_MODE" != required', bridge)
        with TemporaryDirectory() as tmp:
            result, lines = self._run_copy(Path(tmp), FAKE_PY_MIGRATE_RC="47")
        self.assertEqual(result.returncode, 47)
        self.assertEqual(self._stages(lines), ["wait", "verify", "intent", "migrate"])

    def test_t04_collectstatic_failure_fails_whole_script(self):
        with TemporaryDirectory() as tmp:
            result, lines = self._run_copy(Path(tmp), FAKE_PY_COLLECTSTATIC_RC="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            self._stages(lines),
            ["wait", "verify", "intent", "migrate", "complete", "collectstatic"],
        )

    def test_t04_no_gunicorn_or_celery_is_invoked(self):
        with TemporaryDirectory() as tmp:
            result, lines = self._run_copy(Path(tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        joined = "\n".join(lines).lower()
        self.assertNotIn("gunicorn", joined)
        self.assertNotIn("celery", joined)
        self.assertEqual(len(lines), 7)

    def test_t04_initial_install_uses_required_intent_flow(self):
        with TemporaryDirectory() as tmp:
            result, lines = self._run_copy(Path(tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self._stages(lines),
            ["wait", "verify", "intent", "migrate", "complete", "collectstatic"],
        )

    def test_initial_install_non_postgresql_stops_before_migrate_and_collectstatic(self):
        with TemporaryDirectory() as tmp:
            result, lines = self._run_copy(
                Path(tmp),
                DB_ENGINE="",
                FAKE_PY_DATABASE_VENDOR_RC="1",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._stages(lines), ["wait"])

    def test_initial_install_postgresql_vendor_gate_passes_to_migrate(self):
        with TemporaryDirectory() as tmp:
            result, lines = self._run_copy(
                Path(tmp),
                DB_ENGINE="django.db.backends.postgresql",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self._stages(lines),
            ["wait", "verify", "intent", "migrate", "complete", "collectstatic"],
        )

    def test_rollback_control_migrate_phase_skips_completion_and_collectstatic(self):
        with TemporaryDirectory() as tmp:
            result, lines = self._run_copy(
                Path(tmp),
                RELEASE_TASK_PHASE="migrate-verify",
                RESTRICTED_RECOVERY_ATTEMPT_MODE="required",
                FAKE_PY_COLLECTSTATIC_RC="97",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self._stages(lines), ["wait", "verify", "intent", "migrate"]
        )
        self.assertIn("release-marker-identity=1:2", result.stdout)

    def test_rollback_control_completion_phase_only_completes_intent(self):
        with TemporaryDirectory() as tmp:
            result, lines = self._run_copy(
                Path(tmp),
                RELEASE_TASK_PHASE="complete-intent",
                FAKE_PY_MIGRATE_RC="96",
                FAKE_PY_COLLECTSTATIC_RC="97",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._stages(lines), ["wait", "complete"])

    def test_required_split_completion_reuses_pre_static_marker_identity(self):
        with TemporaryDirectory() as tmp:
            result, lines = self._run_copy(
                Path(tmp),
                RELEASE_TASK_PHASE="complete-intent",
                RESTRICTED_RECOVERY_ATTEMPT_MODE="required",
                RELEASE_EXPECTED_MARKER_DEVICE="11",
                RELEASE_EXPECTED_MARKER_INODE="22",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._stages(lines), ["wait", "complete"])
        self.assertIn("--expected-marker-device=11", lines[-1])
        self.assertIn("--expected-marker-inode=22", lines[-1])


class HostReleaseWrapperTests(SimpleTestCase):
    """T05: deploy/run_release_tasks.sh protected one-shot wrapper."""

    def _assert_scripts_exist(self, harness: Harness) -> None:
        self.assertTrue(
            (harness.work / HOST_WRAPPER_REL).is_file(),
            "missing deploy/run_release_tasks.sh (protected host wrapper)",
        )
        self.assertTrue(
            (harness.work / LOCK_SCRIPT_REL).is_file(),
            "missing deploy/deployment_lock.sh",
        )

    def _prepared(self, harness: Harness) -> None:
        self._assert_scripts_exist(harness)
        seed_services(harness)
        result = acquire_lock(harness, LOCK_TOKEN_A)
        self.assertEqual(result.returncode, 0, result.stderr)
        harness.clear_log()

    def _run_wrapper(self, harness: Harness, **env):
        repair = harness.work.resolve() / "runtime" / "migration_history_repair"
        artifact_dir = repair / "preflight" / "before.test"
        artifact_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        handoff_action = env.pop("TEST_HANDOFF_ACTION", "deploy")
        recovery_intent_mode = env.get(
            "RESTRICTED_RECOVERY_ATTEMPT_MODE", "not-required"
        )
        (artifact_dir / "preflight.json").write_text(
            json.dumps(
                {
                    "handoff_action": handoff_action,
                    "recovery_intent_mode": recovery_intent_mode,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        defaults = {
            "RELEASE_B_PREFLIGHT_ARTIFACT_PATH": str(artifact_dir / "preflight.json"),
            "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256": "a" * 64,
            "EXPECTED_CANDIDATE_COMMIT": "b" * 40,
            "EXPECTED_CANDIDATE_IMAGE_ID": "sha256:" + "c" * 64,
            "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256": "d" * 64,
            "RESTRICTED_RECOVERY_ATTEMPT_MODE": "not-required",
        }
        defaults.update(env)
        return harness.run_script(HOST_WRAPPER_REL, **defaults)

    def test_t05_missing_compose_file_fails_before_any_compose_call(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            result = self._run_wrapper(harness, DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(compose_calls(harness.events()), [])

    def test_t05_non_allowlisted_compose_file_fails_before_any_compose_call(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            result = self._run_wrapper(
                harness,
                COMPOSE_FILE="docker-compose.dev.yml",
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(compose_calls(harness.events()), [])

    def test_t05_missing_lock_token_fails_before_any_compose_call(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            result = self._run_wrapper(harness, COMPOSE_FILE=COMPOSE_STANDARD)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(compose_calls(harness.events()), [])

    def test_t05_wrong_lock_token_fails_before_any_compose_call(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            result = self._run_wrapper(
                harness,
                COMPOSE_FILE=COMPOSE_STANDARD,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_B,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(compose_calls(harness.events()), [])

    def _assert_one_shot(self, harness: Harness, compose_file: str) -> None:
        calls = compose_calls(harness.events())
        self.assertEqual(len(calls), 1, f"expected exactly one compose call: {calls}")
        actual_file, argv = calls[0]
        self.assertEqual(actual_file, compose_file)
        self.assertTrue(is_release_run(("compose", actual_file, argv)), argv)

    def test_t05_standard_compose_file_runs_exactly_one_one_shot(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            result = self._run_wrapper(
                harness,
                COMPOSE_FILE=COMPOSE_STANDARD,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_one_shot(harness, COMPOSE_STANDARD)

    def test_t05_lowcost_compose_file_runs_exactly_one_one_shot(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            result = self._run_wrapper(
                harness,
                COMPOSE_FILE=COMPOSE_LOWCOST,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_one_shot(harness, COMPOSE_LOWCOST)

    def test_t05_stale_provenance_is_cleared_for_normal_release(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            result = self._run_wrapper(
                harness,
                COMPOSE_FILE=COMPOSE_STANDARD,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
                RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256="b" * 64,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            _compose_file, argv = compose_calls(harness.events())[0]
            self.assertIn(
                "RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256=", argv
            )
            self.assertNotIn(
                f"RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256={'b' * 64}",
                argv,
            )

    def test_t05_forward_resume_preserves_exact_provenance(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            provenance = "b" * 64
            result = self._run_wrapper(
                harness,
                COMPOSE_FILE=COMPOSE_STANDARD,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
                TEST_HANDOFF_ACTION="forward-resume",
                RESTRICTED_RECOVERY_ATTEMPT_MODE="required",
                RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256=provenance,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            _compose_file, argv = compose_calls(harness.events())[0]
            self.assertIn(
                f"RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256={provenance}",
                argv,
            )

    def test_t05_compose_failure_is_propagated(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            harness.set_rc("compose-run", 1)
            result = self._run_wrapper(
                harness,
                COMPOSE_FILE=COMPOSE_STANDARD,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
            )
            self.assertNotEqual(result.returncode, 0)
            self._assert_one_shot(harness, COMPOSE_STANDARD)

    def test_rollback_split_uses_control_target_control_image_phases(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            control_override = harness.work / "runtime/control.yml"
            control_override.parent.mkdir(parents=True, exist_ok=True)
            control_override.write_text(
                'services:\n  web:\n    image: "sha256:control-image-id"\n',
                encoding="utf-8",
            )
            control_override.chmod(0o400)
            target_tag = "umanewsbot:rollback-target-" + "a" * 64
            result = self._run_wrapper(
                harness,
                COMPOSE_FILE=COMPOSE_STANDARD,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
                EXPECTED_CANDIDATE_IMAGE_ID="sha256:candidate-image-id",
                RELEASE_CONTROL_COMPOSE_OVERRIDE=str(control_override),
                RELEASE_TARGET_IMAGE_TAG=target_tag,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            runs = [
                argv
                for _compose_file, argv in compose_calls(harness.events())
                if argv[:1] == ["run"]
            ]
            self.assertEqual(len(runs), 3)
            self.assertIn("RELEASE_TASK_PHASE=migrate-verify", runs[0])
            self.assertEqual(
                runs[1][-5:],
                ["web", "python", "manage.py", "collectstatic", "--noinput"],
            )
            self.assertIn("RELEASE_TASK_PHASE=complete-intent", runs[2])
            target_override = (
                harness.state / "last-target-collectstatic-override.yml"
            ).read_text(encoding="utf-8")
            self.assertEqual(
                target_override,
                f'services:\n  web:\n    image: "{target_tag}"\n',
            )

    def test_rollback_split_rejects_wrong_target_image_before_any_phase(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            control_override = harness.work / "runtime/control.yml"
            control_override.parent.mkdir(parents=True, exist_ok=True)
            control_override.write_text("services: {}\n", encoding="utf-8")
            control_override.chmod(0o400)
            harness.set_state("target-image-id", "sha256:wrong-image-id\n")
            result = self._run_wrapper(
                harness,
                COMPOSE_FILE=COMPOSE_STANDARD,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
                EXPECTED_CANDIDATE_IMAGE_ID="sha256:candidate-image-id",
                RELEASE_CONTROL_COMPOSE_OVERRIDE=str(control_override),
                RELEASE_TARGET_IMAGE_TAG="umanewsbot:rollback-target-" + "a" * 64,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(compose_calls(harness.events()), [])

    def test_rollback_split_rejects_target_tag_drift_after_collectstatic(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            control_override = harness.work / "runtime/control.yml"
            control_override.parent.mkdir(parents=True, exist_ok=True)
            control_override.write_text("services: {}\n", encoding="utf-8")
            control_override.chmod(0o400)
            harness.set_state(
                "target-image-id-seq",
                "sha256:candidate-image-id\n"
                "sha256:candidate-image-id\n"
                "sha256:drifted-image-id\n",
            )
            result = self._run_wrapper(
                harness,
                COMPOSE_FILE=COMPOSE_STANDARD,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
                EXPECTED_CANDIDATE_IMAGE_ID="sha256:candidate-image-id",
                RELEASE_CONTROL_COMPOSE_OVERRIDE=str(control_override),
                RELEASE_TARGET_IMAGE_TAG="umanewsbot:rollback-target-" + "a" * 64,
            )
            self.assertNotEqual(result.returncode, 0)
            runs = [
                argv
                for _compose_file, argv in compose_calls(harness.events())
                if argv[:1] == ["run"]
            ]
            self.assertEqual(len(runs), 2)
            self.assertIn("RELEASE_TASK_PHASE=migrate-verify", runs[0])
            self.assertEqual(
                runs[1][-5:],
                ["web", "python", "manage.py", "collectstatic", "--noinput"],
            )
            self.assertFalse(
                any("RELEASE_TASK_PHASE=complete-intent" in argv for argv in runs)
            )


class DeploymentLockTests(SimpleTestCase):
    """T06 (lock part): deploy/deployment_lock.sh mutual exclusion."""

    def _assert_script_exists(self, harness: Harness) -> None:
        self.assertTrue(
            (harness.work / LOCK_SCRIPT_REL).is_file(),
            "missing deploy/deployment_lock.sh",
        )

    def _lock_metadata(self, harness: Harness) -> str:
        chunks = []
        for path in sorted(harness.lock_dir.rglob("*")):
            if path.is_file():
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(chunks)

    def test_t06_acquire_verify_release_cycle(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            first = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(harness.lock_dir.is_dir())

            ok = harness.run_script(
                LOCK_SCRIPT_REL, "verify", DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            wrong = harness.run_script(
                LOCK_SCRIPT_REL, "verify", DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_B
            )
            self.assertNotEqual(wrong.returncode, 0)
            self.assertTrue(harness.lock_dir.is_dir())

            released = harness.run_script(
                LOCK_SCRIPT_REL, "release", DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A
            )
            self.assertEqual(released.returncode, 0, released.stderr)
            self.assertFalse(harness.lock_dir.exists())

    def test_t06_second_acquire_fails_closed_immediately(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            first = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = acquire_lock(harness, LOCK_TOKEN_B, action="rollback")
            self.assertNotEqual(second.returncode, 0)
            # Winner lock still intact and verifiable only by the winner token.
            ok = harness.run_script(
                LOCK_SCRIPT_REL, "verify", DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            # Losing contender must not have removed the winner lock on exit.
            self.assertTrue(harness.lock_dir.is_dir())

    def test_t06_release_by_non_owner_is_rejected_and_lock_kept(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            first = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(first.returncode, 0, first.stderr)
            released = harness.run_script(
                LOCK_SCRIPT_REL, "release", DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_B
            )
            self.assertNotEqual(released.returncode, 0)
            self.assertTrue(harness.lock_dir.is_dir())

    def test_t06_stale_lock_fails_closed_without_auto_cleanup(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            harness.lock_dir.mkdir()
            (harness.lock_dir / "stale-garbage").write_text("unknown\n", encoding="utf-8")
            result = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((harness.lock_dir / "stale-garbage").exists())

    def test_t06_lock_metadata_never_contains_raw_token_or_secrets(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            secret = "postgres://user:Sup3rSecret@db.internal/umanews"
            result = harness.run_script(
                LOCK_SCRIPT_REL,
                "acquire",
                DEPLOYMENT_LOCK_ACTION="deploy",
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
                DATABASE_URL=secret,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            metadata = self._lock_metadata(harness)
            self.assertNotIn(LOCK_TOKEN_A, metadata)
            self.assertNotIn("Sup3rSecret", metadata)
            self.assertNotIn(secret, metadata)
            token_hash = hashlib.sha256(LOCK_TOKEN_A.encode()).hexdigest()
            self.assertIn(token_hash, metadata)

    def test_p1_lock_accepts_p0_closed_admission_and_resume_release_actions(self):
        for action in ("p0-closed-admission", "resume-release"):
            with self.subTest(action=action):
                with TemporaryDirectory() as tmp:
                    harness = Harness(Path(tmp))
                    self._assert_script_exists(harness)
                    acquired = acquire_lock(harness, LOCK_TOKEN_A, action=action)
                    self.assertEqual(acquired.returncode, 0, acquired.stderr)
                    verified = harness.run_script(
                        LOCK_SCRIPT_REL, "verify", DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A
                    )
                    self.assertEqual(verified.returncode, 0, verified.stderr)
                    released = harness.run_script(
                        LOCK_SCRIPT_REL, "release", DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A
                    )
                    self.assertEqual(released.returncode, 0, released.stderr)


class PersistentReleaseMountTests(SimpleTestCase):
    """Isolated releases must use stable runtime and TLS host roots."""

    def _seed_roots(self, root: Path) -> tuple[Path, Path]:
        runtime = root / "persistent-runtime"
        for relative in (
            "horse_profile_completion",
            "upcoming_racecard_urls",
            "secrets",
            "race_live_racecards",
            "race_live_publications",
            "race_data_sync",
        ):
            (runtime / relative).mkdir(parents=True, exist_ok=True)
        for state_dir in ("cache", "batches", "review", "budget"):
            (runtime / "horse_profile_completion" / state_dir).mkdir()
        certs = root / "persistent-certs"
        live = certs / "letsencrypt/live/umafans.run"
        live.mkdir(parents=True)
        (live / "fullchain.pem").write_text("certificate\n", encoding="utf-8")
        (live / "privkey.pem").write_text("private key\n", encoding="utf-8")
        release_runtime = root / "runtime"
        release_runtime.mkdir()
        tracked_horse_runtime = release_runtime / "horse_profile_completion"
        tracked_horse_runtime.mkdir()
        for state_dir in ("cache", "batches", "review", "budget"):
            (tracked_horse_runtime / state_dir).symlink_to(
                runtime / "horse_profile_completion" / state_dir
            )
        for relative in (
            "upcoming_racecard_urls",
            "secrets",
            "race_live_racecards",
            "race_live_publications",
            "race_data_sync",
        ):
            (release_runtime / relative).symlink_to(runtime / relative)
        release_certs = root / "deploy/certs"
        release_certs.mkdir(parents=True)
        (release_certs / "letsencrypt").symlink_to(certs / "letsencrypt")
        return runtime, certs

    def _run(self, root: Path):
        return subprocess.run(
            ["sh", str(ROOT / "deploy/verify_persistent_release_mounts.sh")],
            env={**os.environ, "UMANEWS_ROOT_DIR": str(root)},
            text=True,
            capture_output=True,
            check=False,
        )

    def test_valid_absolute_persistent_roots_pass(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, certs = self._seed_roots(root)
            (root / ".env").write_text(
                f"UMANEWS_PERSISTENT_RUNTIME_ROOT={runtime}\n"
                f"UMANEWS_TLS_CERT_ROOT={certs}\n",
                encoding="utf-8",
            )
            result = self._run(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("preflight passed", result.stdout)

    def test_relative_or_duplicate_root_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _runtime, certs = self._seed_roots(root)
            (root / ".env").write_text(
                "UMANEWS_PERSISTENT_RUNTIME_ROOT=./runtime\n"
                "UMANEWS_PERSISTENT_RUNTIME_ROOT=./other\n"
                f"UMANEWS_TLS_CERT_ROOT={certs}\n",
                encoding="utf-8",
            )
            result = self._run(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exactly once", result.stderr)

    def test_tls_symlink_cannot_escape_certificate_root(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, certs = self._seed_roots(root)
            outside = root / "outside-key.pem"
            outside.write_text("outside\n", encoding="utf-8")
            private_key = certs / "letsencrypt/live/umafans.run/privkey.pem"
            private_key.unlink()
            private_key.symlink_to(outside)
            (root / ".env").write_text(
                f"UMANEWS_PERSISTENT_RUNTIME_ROOT={runtime}\n"
                f"UMANEWS_TLS_CERT_ROOT={certs}\n",
                encoding="utf-8",
            )
            result = self._run(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("escapes", result.stderr)

    def test_release_local_rollback_path_must_resolve_to_persistent_root(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, certs = self._seed_roots(root)
            fallback = root / "runtime/race_data_sync"
            fallback.unlink()
            fallback.mkdir()
            (root / ".env").write_text(
                f"UMANEWS_PERSISTENT_RUNTIME_ROOT={runtime}\n"
                f"UMANEWS_TLS_CERT_ROOT={certs}\n",
                encoding="utf-8",
            )
            result = self._run(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("rollback compatibility", result.stderr)

    def test_tracked_horse_profile_parent_cannot_be_replaced_by_symlink(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, certs = self._seed_roots(root)
            tracked_parent = root / "runtime/horse_profile_completion"
            for child in tracked_parent.iterdir():
                child.unlink()
            tracked_parent.rmdir()
            tracked_parent.symlink_to(runtime / "horse_profile_completion")
            (root / ".env").write_text(
                f"UMANEWS_PERSISTENT_RUNTIME_ROOT={runtime}\n"
                f"UMANEWS_TLS_CERT_ROOT={certs}\n",
                encoding="utf-8",
            )
            result = self._run(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("tracked horse-profile", result.stderr)

    def test_prod_compose_files_bind_stable_roots(self):
        for relative in ALLOWED_COMPOSE_FILES:
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("${UMANEWS_PERSISTENT_RUNTIME_ROOT:-./runtime}", text)
            self.assertIn("${UMANEWS_TLS_CERT_ROOT:-./deploy/certs}", text)
            self.assertNotIn("- ./runtime/secrets:/run/secrets", text)
            self.assertNotIn("- ./deploy/certs:/etc/nginx/certs", text)

    def test_deploy_preflights_mounts_and_nginx_before_build(self):
        for relative in ("deploy/deploy.sh", "deploy/deploy_lowcost.sh"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            marker = text.index("check_restricted_recovery_marker.sh")
            mounts = text.index("verify_persistent_release_mounts.sh")
            nginx = text.index('run --rm --no-deps nginx nginx -t')
            build = text.index('build web')
            self.assertLess(marker, mounts, relative)
            self.assertLess(mounts, nginx, relative)
            self.assertLess(nginx, build, relative)


class ManualReleaseTests(SimpleTestCase):
    """T06 (manual part): deploy/manual_release.sh fail-closed manual entry."""

    def _assert_script_exists(self, harness: Harness) -> None:
        self.assertTrue(
            (harness.work / MANUAL_RELEASE_REL).is_file(),
            "missing deploy/manual_release.sh (protected manual release entry)",
        )

    def _run_manual(self, harness: Harness, **env):
        harness.set_state(
            "git-rev-parse-head",
            "0123456789abcdef0123456789abcdef01234567\n",
        )
        return harness.run_script(
            MANUAL_RELEASE_REL, COMPOSE_FILE=COMPOSE_STANDARD, **env
        )

    def _assert_no_compose_run(self, harness: Harness) -> None:
        runs = [argv for _cf, argv in compose_calls(harness.events()) if argv[:1] == ["run"]]
        self.assertEqual(runs, [])

    def test_t06_manual_release_refuses_when_web_running(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, race_live="absent")
            result = self._run_manual(harness)
            self.assertNotEqual(result.returncode, 0)
            self._assert_no_compose_run(harness)

    def test_t06_manual_release_refuses_when_worker_state_unknown(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, web="absent", race_live="absent")
            harness.set_rc(f"inspect-{SERVICE_IDS['worker']}", 1)
            result = self._run_manual(harness)
            self.assertNotEqual(result.returncode, 0)
            self._assert_no_compose_run(harness)

    def test_t06_manual_release_refuses_when_beat_restarting(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, web="absent", race_live="absent")
            harness.set_state(
                f"inspect-{SERVICE_IDS['beat']}", "false restarting\n"
            )
            result = self._run_manual(harness)
            self.assertNotEqual(result.returncode, 0)
            self._assert_no_compose_run(harness)

    def test_t06_manual_release_refuses_when_race_live_running(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, web="absent", race_live="running")
            result = self._run_manual(harness)
            self.assertNotEqual(result.returncode, 0)
            self._assert_no_compose_run(harness)

    def test_t06_manual_release_runs_one_shot_only_when_all_app_services_stopped(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            # Infra (db/redis) may stay up; all four app services absent.
            harness.set_state("ps-db", f"{SERVICE_IDS['db']}\n")
            harness.set_state(f"inspect-{SERVICE_IDS['db']}", "true healthy\n")
            harness.set_state("ps-redis", f"{SERVICE_IDS['redis']}\n")
            harness.set_state(f"inspect-{SERVICE_IDS['redis']}", "true healthy\n")
            result = self._run_manual(harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = compose_calls(harness.events())
            runs = [argv for _cf, argv in calls if argv[:1] == ["run"]]
            self.assertEqual(len(runs), 2)
            self.assertIn("create_historical_calendar_release_b_handoff", runs[0])
            self.assertTrue(is_release_run(("compose", COMPOSE_STANDARD, runs[1])))
            ups = [argv for _cf, argv in calls if argv[:1] == ["up"]]
            self.assertEqual(ups, [], "manual release must not start any service")

    def test_t06_manual_release_releases_lock_on_failure(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, race_live="absent")
            result = self._run_manual(harness)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(
                harness.lock_dir.exists(),
                "failed manual release must release the deployment lock it acquired",
            )

    def test_t06_contending_entry_cannot_grab_or_delete_winner_lock(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            self.assertTrue((harness.work / LOCK_SCRIPT_REL).is_file())
            winner = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(winner.returncode, 0, winner.stderr)
            seed_services(harness, web="absent", race_live="absent")
            result = self._run_manual(harness)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(
                harness.lock_dir.is_dir(),
                "contending entry must not delete the winner lock",
            )
            self._assert_no_compose_run(harness)
            released = harness.run_script(
                LOCK_SCRIPT_REL, "release", DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A
            )
            self.assertEqual(released.returncode, 0, released.stderr)

    def test_p3_manual_release_refuses_when_container_status_is_restarting(self):
        # State.Status=restarting is a distinct third column, not Health.Status:
        # an implementation that only compares the health field must still fail
        # closed here. The restarting worker is the ONLY present app service so
        # the refusal cannot be attributed to any other service.
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            harness.set_state("ps-worker", f"{SERVICE_IDS['worker']}\n")
            harness.set_state(
                f"inspect-{SERVICE_IDS['worker']}", "false none restarting\n"
            )
            harness.set_state("ps-db", f"{SERVICE_IDS['db']}\n")
            harness.set_state(f"inspect-{SERVICE_IDS['db']}", "true healthy\n")
            harness.set_state("ps-redis", f"{SERVICE_IDS['redis']}\n")
            harness.set_state(f"inspect-{SERVICE_IDS['redis']}", "true healthy\n")
            result = self._run_manual(harness)
            self.assertNotEqual(result.returncode, 0)
            self._assert_no_compose_run(harness)


class ComposeServiceHealthyWaitTests(SimpleTestCase):
    """T07/T08: deploy/wait_for_compose_service_healthy.sh."""

    def _assert_script_exists(self, harness: Harness) -> None:
        self.assertTrue(
            (harness.work / HEALTH_WAIT_REL).is_file(),
            "missing deploy/wait_for_compose_service_healthy.sh",
        )

    def _run_wait(self, harness: Harness, **env):
        overrides = {"COMPOSE_FILE": COMPOSE_STANDARD, "SERVICE_NAME": "web"}
        overrides.update(env)
        return harness.run_script(HEALTH_WAIT_REL, **overrides)

    def test_t07_absent_then_starting_then_healthy_succeeds(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            cid = SERVICE_IDS["web"]
            harness.set_state("ps-seq-web", f"\n{cid}\n")
            harness.set_state(f"inspect-seq-{cid}", "true starting\ntrue healthy\n")
            result = self._run_wait(harness, SERVICE_HEALTH_TIMEOUT_SECONDS="10")
            self.assertEqual(result.returncode, 0, result.stderr)
            # Only the web service is ever queried.
            ps_queries = [
                argv
                for _cf, argv in compose_calls(harness.events())
                if argv[:2] == ["ps", "-q"]
            ]
            self.assertTrue(ps_queries)
            for argv in ps_queries:
                self.assertEqual(argv, ["ps", "-q", "web"])
            # Output must not leak the full container id or env secrets.
            output = result.stdout + result.stderr
            self.assertNotIn(cid, output)
            self.assertNotIn("FAKE_STATE_DIR", output)

    def test_t08_not_running_container_fails(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            cid = SERVICE_IDS["web"]
            harness.set_state("ps-web", f"{cid}\n")
            harness.set_state(f"inspect-{cid}", "false none\n")
            result = self._run_wait(harness)
            self.assertNotEqual(result.returncode, 0)

    def test_t08_unhealthy_container_fails(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            cid = SERVICE_IDS["web"]
            harness.set_state("ps-web", f"{cid}\n")
            harness.set_state(f"inspect-{cid}", "true unhealthy\n")
            result = self._run_wait(harness)
            self.assertNotEqual(result.returncode, 0)

    def test_t08_inspect_error_fails(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            cid = SERVICE_IDS["web"]
            harness.set_state("ps-web", f"{cid}\n")
            harness.set_rc("inspect", 1)
            result = self._run_wait(harness, SERVICE_HEALTH_TIMEOUT_SECONDS="3")
            self.assertNotEqual(result.returncode, 0)

    def test_t08_starting_until_timeout_fails(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            cid = SERVICE_IDS["web"]
            harness.set_state("ps-web", f"{cid}\n")
            harness.set_state(f"inspect-{cid}", "true starting\n")
            result = self._run_wait(harness, SERVICE_HEALTH_TIMEOUT_SECONDS="3")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("web", result.stdout + result.stderr)

    def test_t08_container_id_change_never_succeeds(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            first, second = SERVICE_IDS["web"], "cidweb9999zzzzyyyy"
            harness.set_state("ps-seq-web", f"{first}\n{second}\n{first}\n")
            for cid in (first, second):
                harness.set_state(f"inspect-{cid}", "true starting\n")
            result = self._run_wait(harness, SERVICE_HEALTH_TIMEOUT_SECONDS="3")
            self.assertNotEqual(result.returncode, 0)

    def test_t08_only_web_service_is_supported(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            result = self._run_wait(harness, SERVICE_NAME="worker")
            self.assertNotEqual(result.returncode, 0)

    def test_t08_missing_or_unknown_compose_file_fails(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            missing = harness.run_script(HEALTH_WAIT_REL, SERVICE_NAME="web")
            self.assertNotEqual(missing.returncode, 0)
            bad = harness.run_script(
                HEALTH_WAIT_REL,
                COMPOSE_FILE="docker-compose.dev.yml",
                SERVICE_NAME="web",
            )
            self.assertNotEqual(bad.returncode, 0)


class DeployOrchestrationTests(SimpleTestCase):
    """T09/T10/T15: real deploy.sh / deploy_lowcost.sh orchestration order."""

    def _run_deploy(self, harness: Harness, script_rel: str, **env):
        return harness.run_script(script_rel, **env)

    def test_candidate_schema_preflight_failure_stops_before_release_or_service_stop(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness)
            harness.set_rc("compose-run", 1)

            result = self._run_deploy(harness, "deploy/deploy.sh")

            self.assertNotEqual(result.returncode, 0)
            events = harness.events()
            self.assertEqual([event for event in events if is_release_run(event)], [])
            self.assertEqual(
                [event for event in events if event[0] == "compose" and event[2][:1] == ["stop"]],
                [],
            )

    def test_full_history_consistency_failure_is_zero_stop_zero_migrate(self):
        for script in ("deploy/deploy.sh", "deploy/deploy_lowcost.sh"):
            with self.subTest(script=script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness)
                seed_git_head(harness)
                harness.set_rc("compose-run", 74)
                result = self._run_deploy(harness, script)
                self.assertEqual(result.returncode, 74)
                events = harness.events()
                self.assertEqual(
                    [e for e in events if e[0] == "compose" and e[2][:1] == ["stop"]],
                    [],
                )
                self.assertEqual([e for e in events if is_exec_migrate(e)], [])
                self.assertEqual([e for e in events if is_release_run(e)], [])

    def test_nginx_mount_or_config_failure_stops_before_build_or_service_stop(self):
        for script in ("deploy/deploy.sh", "deploy/deploy_lowcost.sh"):
            with self.subTest(script=script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness)
                harness.set_rc("compose-nginx-config", 1)
                result = self._run_deploy(harness, script)
                self.assertNotEqual(result.returncode, 0)
                events = harness.events()
                self.assertEqual(
                    [e for e in events if e[0] == "compose" and e[2][:1] == ["build"]],
                    [],
                )
                self.assertEqual(
                    [e for e in events if e[0] == "compose" and e[2][:1] == ["stop"]],
                    [],
                )
                self.assertEqual([e for e in events if is_release_run(e)], [])

    def _assert_full_orchestration(
        self, harness: Harness, result, compose_file: str
    ) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        repair_root = harness.work / "runtime" / "migration_history_repair"
        self.assertTrue(repair_root.is_dir())
        self.assertFalse(repair_root.is_symlink())
        self.assertEqual(stat.S_IMODE(repair_root.stat().st_mode), 0o700)
        evts = harness.events()
        calls = compose_calls(evts)
        for actual_file, _argv in calls:
            if actual_file is not None:
                self.assertEqual(actual_file, compose_file)

        # T09.7: never an `exec web ... migrate` second owner.
        self.assertEqual(
            [e for e in evts if is_exec_migrate(e)],
            [],
            "deploy must never exec migrate inside the web container",
        )

        # T09.4: nginx config/cert preflight precedes the handoff and the
        # release wrapper is still invoked exactly once with the exact argv.
        runs = [argv for _cf, argv in calls if argv[:1] == ["run"]]
        self.assertEqual(len(runs), 3)
        self.assertEqual(runs[0], ["run", "--rm", "--no-deps", "nginx", "nginx", "-t"])
        self.assertIn("create_historical_calendar_release_b_handoff", runs[1])
        self.assertTrue(is_release_run(("compose", compose_file, runs[2])), runs[2])

        def index(predicate, label):
            found = first_index(evts, predicate)
            self.assertIsNotNone(found, f"missing orchestration step: {label}")
            return found

        preflight = index(
            lambda e: e[0] == "compose"
            and e[2][:1] == ["exec"]
            and "manage_historical_batch_runner" in e[2],
            "historical runner preflight",
        )
        build = index(
            lambda e: e[0] == "compose" and e[2][:1] == ["build"] and "web" in e[2],
            "build web",
        )
        stop_beat = index(
            lambda e: e[0] == "compose" and e[2] == ["stop", "beat"], "stop beat"
        )
        drain = index(is_drain_exec, "celery drain")
        stop_worker = index(
            lambda e: e[0] == "compose" and e[2] == ["stop", "worker"], "stop worker"
        )
        stop_race_live = index(
            lambda e: e[0] == "compose" and e[2] == ["stop", "race_live_worker"],
            "stop race_live_worker (originally running)",
        )
        stop_web = index(
            lambda e: e[0] == "compose" and e[2] == ["stop", "web"], "stop web"
        )
        release = index(is_release_run, "one-shot release task")
        up_web = index(
            lambda e: e[0] == "compose" and e[2] == ["up", "-d", "--no-deps", "web"],
            "up web",
        )
        healthy_probe = first_index(
            evts[up_web + 1 :],
            lambda e: e[0] == "docker" and e[2][:1] == ["inspect"],
        )
        self.assertIsNotNone(healthy_probe, "missing web health probe after web start")
        healthy_probe += up_web + 1
        up_downstream = index(
            lambda e: e[0] == "compose"
            and e[2] == ["up", "-d", "--no-deps", "worker", "beat", "nginx"],
            "up worker beat nginx",
        )
        up_race_live = index(
            lambda e: e[0] == "compose"
            and e[2] == ["up", "-d", "--no-deps", "race_live_worker"],
            "restore race_live_worker",
        )
        final_ps = index(
            lambda e: e[0] == "compose" and e[2] == ["ps"], "final status ps"
        )

        self.assertLess(preflight, build, "preflight must run before stateful actions")
        self.assertLess(build, stop_beat)
        self.assertLess(stop_beat, drain)
        self.assertLess(drain, stop_worker)
        self.assertLess(stop_worker, stop_race_live)
        self.assertLess(stop_race_live, stop_web)
        self.assertLess(stop_web, release)
        self.assertLess(release, up_web)
        self.assertLess(up_web, healthy_probe)
        self.assertLess(healthy_probe, up_downstream)
        self.assertLess(up_downstream, up_race_live)
        self.assertLess(up_race_live, final_ps)

        # T15: every up keeps --no-deps; release run keeps --no-deps; no down;
        # no db/redis/volume/network lifecycle mutation.
        for _cf, argv in calls:
            if argv[:1] == ["up"]:
                self.assertIn("--no-deps", argv, f"up without --no-deps: {argv}")
            if argv[:1] == ["run"]:
                self.assertIn("--no-deps", argv, f"run without --no-deps: {argv}")
            self.assertNotEqual(argv[:1], ["down"], "deploy must not run compose down")
            if argv[:1] in (["stop"], ["up"], ["run"], ["exec"], ["build"], ["kill"], ["rm"], ["restart"], ["create"]):
                self.assertNotIn("db", argv[1:], f"infra service touched: {argv}")
                self.assertNotIn("redis", argv[1:], f"infra service touched: {argv}")
        docker_direct = [argv for kind, _cf, argv in evts if kind == "docker"]
        for argv in docker_direct:
            self.assertNotIn(argv[:1], (["volume"], ["network"]), f"infra mutation: {argv}")

        # T15: historical runner preflight and celery drain are not bypassed.
        self.assertTrue(
            any(
                e[0] == "compose" and "manage_historical_batch_runner" in e[2]
                for e in evts
            ),
            "historical runner preflight was bypassed",
        )
        self.assertTrue(any(is_drain_exec(e) for e in evts), "celery drain was bypassed")

    def test_t09_standard_deploy_full_orchestration(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            result = self._run_deploy(harness, "deploy/deploy.sh")
            self._assert_full_orchestration(harness, result, COMPOSE_STANDARD)

    def test_t10_lowcost_deploy_full_orchestration(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            result = self._run_deploy(harness, "deploy/deploy_lowcost.sh")
            self._assert_full_orchestration(harness, result, COMPOSE_LOWCOST)


class RollbackOrchestrationTests(SimpleTestCase):
    """T11: rollback.sh / rollback_lowcost.sh contract gating and orchestration."""

    def _seed(self, harness: Harness) -> None:
        seed_services(harness, race_live="running")
        # A successful real `git rev-parse --verify` always prints an OID; the
        # fake would otherwise return an unrealistic empty stdout.
        harness.set_state(
            "git-rev-parse-output",
            "0123456789abcdef0123456789abcdef01234567\n",
        )

    def test_t11_empty_ref_is_rejected_without_any_stateful_action(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._seed(harness)
            for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
                with self.subTest(script=script):
                    harness.clear_log()
                    result = harness.run_script(script)
                    self.assertNotEqual(result.returncode, 0)
                    calls = compose_calls(harness.events())
                    self.assertEqual(
                        [a for _cf, a in calls if a[:1] in (["stop"], ["up"], ["run"])],
                        [],
                    )

    def test_t11_unresolvable_ref_is_rejected_without_stop_or_release(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._seed(harness)
            harness.set_rc("git-rev-parse", 1)
            for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
                with self.subTest(script=script):
                    harness.clear_log()
                    result = harness.run_script(script, "deadbeef")
                    self.assertNotEqual(result.returncode, 0)
                    calls = compose_calls(harness.events())
                    self.assertEqual(
                        [a for _cf, a in calls if a[:1] in (["stop"], ["up"], ["run"])],
                        [],
                    )

    def test_t11_ref_without_release_contract_rejected_before_checkout_or_stop(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._seed(harness)
            harness.set_rc("git-cat-file", 1)  # target ref lacks release_contract_v1
            for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
                with self.subTest(script=script):
                    harness.clear_log()
                    result = harness.run_script(script, "oldref123")
                    self.assertNotEqual(result.returncode, 0)
                    evts = harness.events()
                    self.assertEqual(
                        [e for e in evts if e[0] == "git" and e[2][:1] == ["checkout"]],
                        [],
                        "rollback must not checkout a ref without release_contract_v1",
                    )
                    calls = compose_calls(evts)
                    self.assertEqual(
                        [a for _cf, a in calls if a[:1] in (["stop"], ["up"], ["run"])],
                        [],
                        "pre-contract target must be rejected with zero stop and zero release",
                    )

    def test_active_restricted_marker_blocks_before_fetch_checkout_or_build(self):
        for relative in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            lock = text.index("deployment_lock.sh acquire")
            marker_gate = text.index("check_restricted_recovery_marker.sh")
            fetch = text.index("git fetch --all --tags")
            checkout = text.index('git checkout "$TARGET_OID"')
            build = text.index('build web')
            self.assertLess(lock, marker_gate, relative)
            self.assertLess(marker_gate, fetch, relative)
            self.assertLess(marker_gate, checkout, relative)
            self.assertLess(marker_gate, build, relative)
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._seed(harness)
            marker_dir = harness.work / "runtime" / "migration_history_repair"
            marker_dir.mkdir(parents=True, mode=0o700)
            marker_dir.chmod(0o700)
            marker = marker_dir / "restricted-recovery.json"
            marker.write_text('{"marker_sha256":"preserve-me"}', encoding="utf-8")
            marker.chmod(0o600)
            before = (marker.stat().st_ino, marker.stat().st_mode, marker.read_bytes())
            for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
                with self.subTest(script=script):
                    harness.clear_log()
                    result = harness.run_script(script, "releasecontractref")
                    self.assertNotEqual(result.returncode, 0)
                    events = harness.events()
                    self.assertFalse(
                        any(e[0] == "git" and e[2][:1] in (["fetch"], ["checkout"]) for e in events),
                        events,
                    )
                    self.assertFalse(
                        any(e[0] == "compose" and e[2][:1] == ["build"] for e in events),
                        events,
                    )
                    after = (marker.stat().st_ino, marker.stat().st_mode, marker.read_bytes())
                    self.assertEqual(after, before)

    def _assert_rollback_orchestration(
        self, harness: Harness, result, compose_file: str
    ) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        evts = harness.events()
        calls = compose_calls(evts)
        for actual_file, _argv in calls:
            if actual_file is not None:
                self.assertEqual(actual_file, compose_file)
        self.assertEqual([e for e in evts if is_exec_migrate(e)], [])
        runs = [argv for _cf, argv in calls if argv[:1] == ["run"]]
        self.assertEqual(len(runs), 4)
        self.assertIn("create_historical_calendar_release_b_handoff", runs[0])
        self.assertNotIn("--direction=reverse", runs[0])
        self.assertTrue(is_release_run(("compose", compose_file, runs[1])), runs[1])
        self.assertIn("RELEASE_TASK_PHASE=migrate-verify", runs[1])
        self.assertEqual(
            runs[2][-5:],
            ["web", "python", "manage.py", "collectstatic", "--noinput"],
        )
        self.assertTrue(is_release_run(("compose", compose_file, runs[3])), runs[3])
        self.assertIn("RELEASE_TASK_PHASE=complete-intent", runs[3])
        target_override = (
            harness.state / "last-target-collectstatic-override.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("umanewsbot:rollback-target-", target_override)
        checkout = first_index(
            evts, lambda e: e[0] == "git" and e[2][:1] == ["checkout"]
        )
        self.assertIsNotNone(checkout, "rollback must checkout the target ref")
        preflight = first_index(
            evts,
            lambda e: e[0] == "compose"
            and "create_historical_calendar_release_b_handoff" in e[2],
        )
        self.assertIsNotNone(preflight)
        self.assertLess(checkout, preflight)
        release = first_index(evts, is_release_run)
        self.assertIsNotNone(release)
        self.assertLess(checkout, release)
        target_collectstatic = first_index(
            evts,
            lambda e: e[0] == "compose"
            and e[2][-5:]
            == ["web", "python", "manage.py", "collectstatic", "--noinput"],
        )
        self.assertIsNotNone(target_collectstatic)
        complete = first_index(
            evts,
            lambda e: is_release_run(e)
            and "RELEASE_TASK_PHASE=complete-intent" in e[2],
        )
        self.assertIsNotNone(complete)
        self.assertLess(release, target_collectstatic)
        self.assertLess(target_collectstatic, complete)
        stop_web = first_index(
            evts, lambda e: e[0] == "compose" and e[2] == ["stop", "web"]
        )
        self.assertIsNotNone(stop_web, "rollback must stop web before release")
        self.assertLess(stop_web, release)

    def test_t11_standard_rollback_with_contract_uses_shared_release(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._seed(harness)
            result = harness.run_script("deploy/rollback.sh", "releasecontractref")
            self._assert_rollback_orchestration(harness, result, COMPOSE_STANDARD)

    def test_t11_lowcost_rollback_with_contract_uses_shared_release(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._seed(harness)
            result = harness.run_script(
                "deploy/rollback_lowcost.sh", "releasecontractref"
            )
            self._assert_rollback_orchestration(harness, result, COMPOSE_LOWCOST)

    def test_candidate_schema_preflight_failure_stops_rollback_before_release_or_stop(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._seed(harness)
            harness.set_rc("compose-run", 1)

            result = harness.run_script("deploy/rollback.sh", "releasecontractref")

            self.assertNotEqual(result.returncode, 0)
            events = harness.events()
            self.assertEqual([event for event in events if is_release_run(event)], [])
            self.assertEqual(
                [event for event in events if event[0] == "compose" and event[2][:1] == ["stop"]],
                [],
            )

    def test_t11_docs_warn_forward_migrate_is_not_database_rollback(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in DEPLOY_DOC_PATHS if path.is_file()
        )
        self.assertRegex(
            combined,
            r"forward migrate[^\n]{0,40}(不能|不等于|不代表|≠)[^\n]{0,40}(回退|回滚)"
            r"|(不能|不等于|不代表|≠)[^\n]{0,40}forward migrate[^\n]{0,40}(回退|回滚)",
            "rollback docs must warn that forward migrate is not a database rollback",
        )


class PreContractRollbackBridgeTests(SimpleTestCase):
    """T12: deploy/rollback_pre_single_owner.sh first-release bridge."""

    FROZEN_TAG = "umanewsbot:prod-frozen-20260701"

    def _assert_script_exists(self, harness: Harness) -> None:
        self.assertTrue(
            (harness.work / PRE_CONTRACT_BRIDGE_REL).is_file(),
            "missing deploy/rollback_pre_single_owner.sh (pre-contract rollback bridge)",
        )

    def _run_bridge(self, harness: Harness, *args, **env):
        overrides = {"COMPOSE_FILE": COMPOSE_STANDARD}
        overrides.update(env)
        return harness.run_script(PRE_CONTRACT_BRIDGE_REL, *args, **overrides)

    def _prepare_resume_after_bridge_abort(self, harness: Harness) -> None:
        for service in (
            "worker",
            "beat",
            "race_live_worker",
            "race_sync_v2_worker",
        ):
            cid = SERVICE_IDS[service]
            harness.set_state(f"ps-{service}", f"{cid}\n")
            harness.set_state(f"inspect-{cid}", "false exited\n")
        harness.set_state("ps-seq-web", f"\n{SERVICE_IDS['web']}\n")
        harness.set_state(f"inspect-{SERVICE_IDS['web']}", "true healthy\n")
        repair_root = harness.work / "runtime" / "migration_history_repair"
        repair_root.mkdir(parents=True, mode=0o700)
        repair_root.chmod(0o700)
        harness.clear_log()

    def test_t12_missing_frozen_image_tag_is_rejected(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness)
            result = self._run_bridge(harness)
            self.assertNotEqual(result.returncode, 0)

    def test_t12_bridge_restores_frozen_image_without_checkout_or_one_shot(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, race_live="running")
            result = self._run_bridge(
                harness, self.FROZEN_TAG, SCHEMA_COMPATIBLE_WITH_TARGET="true"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evts = harness.events()

            self.assertEqual(
                [e for e in evts if e[0] == "git" and e[2][:1] == ["checkout"]],
                [],
                "bridge must keep the current checkout (no git checkout)",
            )
            self.assertEqual(
                [e for e in evts if is_release_run(e)],
                [],
                "bridge must never run the new one-shot release task",
            )
            tags = [
                e[2] for e in evts if e[0] == "docker" and e[2][:1] == ["tag"]
            ]
            self.assertEqual(tags, [["tag", self.FROZEN_TAG, "umanewsbot:prod"]])

            def index(predicate, label):
                found = first_index(evts, predicate)
                self.assertIsNotNone(found, f"missing bridge step: {label}")
                return found

            stop_beat = index(
                lambda e: e[0] == "compose" and e[2] == ["stop", "beat"], "stop beat"
            )
            drain = index(is_drain_exec, "celery drain")
            stop_worker = index(
                lambda e: e[0] == "compose" and e[2] == ["stop", "worker"],
                "stop worker",
            )
            stop_race_live = index(
                lambda e: e[0] == "compose" and e[2] == ["stop", "race_live_worker"],
                "stop race_live_worker",
            )
            stop_web = index(
                lambda e: e[0] == "compose" and e[2] == ["stop", "web"], "stop web"
            )
            tag = index(
                lambda e: e[0] == "docker" and e[2][:1] == ["tag"], "docker tag"
            )
            up_web = index(
                lambda e: e[0] == "compose"
                and e[2] == ["up", "-d", "--no-deps", "web"],
                "up single old web",
            )
            up_downstream = index(
                lambda e: e[0] == "compose"
                and e[2] == ["up", "-d", "--no-deps", "worker", "beat", "nginx"],
                "up worker beat nginx",
            )
            up_race_live = index(
                lambda e: e[0] == "compose"
                and e[2] == ["up", "-d", "--no-deps", "race_live_worker"],
                "restore race_live_worker",
            )
            self.assertLess(stop_beat, drain)
            self.assertLess(drain, stop_worker)
            self.assertLess(stop_worker, stop_race_live)
            self.assertLess(stop_race_live, stop_web)
            self.assertLess(stop_web, tag)
            self.assertLess(tag, up_web)
            self.assertLess(up_web, up_downstream)
            self.assertLess(up_downstream, up_race_live)

            web_ups = [
                a for _cf, a in compose_calls(evts) if a[:1] == ["up"] and "web" in a
            ]
            self.assertEqual(len(web_ups), 1, "bridge must start exactly one old web")

    def test_t12_schema_incompatible_stops_before_image_switch(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness)
            result = self._run_bridge(
                harness, self.FROZEN_TAG, SCHEMA_COMPATIBLE_WITH_TARGET="false"
            )
            self.assertNotEqual(result.returncode, 0)
            evts = harness.events()
            self.assertEqual(
                [e for e in evts if e[0] == "docker" and e[2][:1] == ["tag"]],
                [],
                "schema-incompatible rollback must stop before docker tag",
            )
            self.assertEqual(
                [a for _cf, a in compose_calls(evts) if a[:1] == ["up"]],
                [],
                "schema-incompatible rollback must not start any service",
            )

    def test_t12_pre_switch_abort_resume_restores_sync_worker_intent(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, race_sync="running")
            result = self._run_bridge(
                harness,
                self.FROZEN_TAG,
                SCHEMA_COMPATIBLE_WITH_TARGET="false",
            )
            self.assertNotEqual(result.returncode, 0)
            state_file = Path(f"{harness.lock_dir}.race-data-sync-state")
            self.assertTrue(state_file.exists())
            self.assertIn("phase=pre-switch", state_file.read_text(encoding="utf-8"))
            for service in (
                "worker",
                "beat",
                "race_live_worker",
                "race_sync_v2_worker",
            ):
                cid = SERVICE_IDS[service]
                harness.set_state(f"ps-{service}", f"{cid}\n")
                harness.set_state(f"inspect-{cid}", "false exited\n")
            harness.set_state(
                "ps-seq-web",
                f"\n{SERVICE_IDS['web']}\n",
            )
            harness.set_state(
                f"inspect-{SERVICE_IDS['web']}",
                "true healthy\n",
            )
            repair_root = harness.work / "runtime" / "migration_history_repair"
            repair_root.mkdir(parents=True, mode=0o700)
            repair_root.chmod(0o700)
            harness.clear_log()

            resumed = harness.run_script(
                RESUME_SCRIPT_REL,
                COMPOSE_FILE=COMPOSE_STANDARD,
            )

            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertIn(
                ["up", "-d", "--no-deps", "race_sync_v2_worker"],
                [argv for _compose, argv in compose_calls(harness.events())],
            )
            self.assertFalse(state_file.exists())

    def test_t12_switching_abort_resume_starts_nothing_and_preserves_intent(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, race_sync="running")
            harness.set_rc("tag", 1)
            result = self._run_bridge(
                harness,
                self.FROZEN_TAG,
                SCHEMA_COMPATIBLE_WITH_TARGET="true",
            )
            self.assertNotEqual(result.returncode, 0)
            state_file = Path(f"{harness.lock_dir}.race-data-sync-state")
            self.assertIn("phase=switching", state_file.read_text(encoding="utf-8"))
            self._prepare_resume_after_bridge_abort(harness)

            resumed = harness.run_script(
                RESUME_SCRIPT_REL,
                COMPOSE_FILE=COMPOSE_STANDARD,
            )

            self.assertNotEqual(resumed.returncode, 0)
            self.assertIn("outcome is unknown", resumed.stderr)
            self.assertEqual(
                [argv for _compose, argv in compose_calls(harness.events()) if argv[:1] == ["up"]],
                [],
            )
            self.assertTrue(state_file.exists())

    def test_t12_switching_race_live_marker_blocks_when_sync_sibling_is_missing(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, race_sync="running")
            harness.set_rc("tag", 1)
            result = self._run_bridge(
                harness,
                self.FROZEN_TAG,
                SCHEMA_COMPATIBLE_WITH_TARGET="true",
            )
            self.assertNotEqual(result.returncode, 0)
            live_state_file = Path(f"{harness.lock_dir}.race-live-state")
            sync_state_file = Path(f"{harness.lock_dir}.race-data-sync-state")
            self.assertIn("phase=switching", live_state_file.read_text(encoding="utf-8"))
            sync_state_file.unlink()
            self._prepare_resume_after_bridge_abort(harness)

            resumed = harness.run_script(
                RESUME_SCRIPT_REL,
                COMPOSE_FILE=COMPOSE_STANDARD,
            )

            self.assertNotEqual(resumed.returncode, 0)
            self.assertIn("outcome is unknown", resumed.stderr)
            self.assertEqual(
                [argv for _compose, argv in compose_calls(harness.events()) if argv[:1] == ["up"]],
                [],
            )
            self.assertTrue(live_state_file.exists())

    def test_t12_switching_race_live_marker_blocks_when_sync_sibling_is_corrupt(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, race_sync="running")
            harness.set_rc("tag", 1)
            result = self._run_bridge(
                harness,
                self.FROZEN_TAG,
                SCHEMA_COMPATIBLE_WITH_TARGET="true",
            )
            self.assertNotEqual(result.returncode, 0)
            live_state_file = Path(f"{harness.lock_dir}.race-live-state")
            sync_state_file = Path(f"{harness.lock_dir}.race-data-sync-state")
            self.assertIn("phase=switching", live_state_file.read_text(encoding="utf-8"))
            sync_state_file.write_text("corrupt\n", encoding="utf-8")
            sync_state_file.chmod(0o600)
            self._prepare_resume_after_bridge_abort(harness)

            resumed = harness.run_script(
                RESUME_SCRIPT_REL,
                COMPOSE_FILE=COMPOSE_STANDARD,
            )

            self.assertNotEqual(resumed.returncode, 0)
            self.assertIn("outcome is unknown", resumed.stderr)
            self.assertEqual(
                [argv for _compose, argv in compose_calls(harness.events()) if argv[:1] == ["up"]],
                [],
            )
            self.assertTrue(live_state_file.exists())
            self.assertTrue(sync_state_file.exists())

    def test_t12_trusted_sibling_intent_mismatch_refuses_recovery(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, race_sync="running")
            result = self._run_bridge(
                harness,
                self.FROZEN_TAG,
                SCHEMA_COMPATIBLE_WITH_TARGET="false",
            )
            self.assertNotEqual(result.returncode, 0)
            live_state_file = Path(f"{harness.lock_dir}.race-live-state")
            sync_state_file = Path(f"{harness.lock_dir}.race-data-sync-state")
            sync_state_file.write_text(
                sync_state_file.read_text(encoding="utf-8").replace(
                    "action=pre-contract-rollback", "action=rollback"
                ),
                encoding="utf-8",
            )
            sync_state_file.chmod(0o600)
            self._prepare_resume_after_bridge_abort(harness)

            resumed = harness.run_script(
                RESUME_SCRIPT_REL,
                COMPOSE_FILE=COMPOSE_STANDARD,
            )

            self.assertNotEqual(resumed.returncode, 0)
            self.assertIn("intents disagree", resumed.stderr)
            self.assertEqual(
                [argv for _compose, argv in compose_calls(harness.events()) if argv[:1] == ["up"]],
                [],
            )
            self.assertTrue(live_state_file.exists())
            self.assertTrue(sync_state_file.exists())

    def test_t12_image_switched_abort_resume_skips_old_catalog_sync_service(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, race_sync="running")
            harness.set_rc("up-web", 1)
            result = self._run_bridge(
                harness,
                self.FROZEN_TAG,
                SCHEMA_COMPATIBLE_WITH_TARGET="true",
            )
            self.assertNotEqual(result.returncode, 0)
            state_file = Path(f"{harness.lock_dir}.race-data-sync-state")
            self.assertIn(
                "phase=image-switched", state_file.read_text(encoding="utf-8")
            )
            harness.set_rc("up-web", 0)
            self._prepare_resume_after_bridge_abort(harness)

            resumed = harness.run_script(
                RESUME_SCRIPT_REL,
                COMPOSE_FILE=COMPOSE_STANDARD,
            )

            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            up_calls = [
                argv
                for _compose, argv in compose_calls(harness.events())
                if argv[:1] == ["up"]
            ]
            self.assertIn(["up", "-d", "--no-deps", "web"], up_calls)
            self.assertIn(
                ["up", "-d", "--no-deps", "worker", "beat", "nginx"],
                up_calls,
            )
            self.assertFalse(
                any("race_sync_v2_worker" in argv for argv in up_calls),
                up_calls,
            )
            self.assertFalse(state_file.exists())

    def test_t12_race_live_not_restored_when_not_running_before(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, race_live="stopped")
            result = self._run_bridge(
                harness, self.FROZEN_TAG, SCHEMA_COMPATIBLE_WITH_TARGET="true"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evts = harness.events()
            self.assertEqual(
                [
                    a
                    for _cf, a in compose_calls(evts)
                    if a[:1] in (["stop"], ["up"]) and "race_live_worker" in a
                ],
                [],
                "race_live_worker must not be stopped or started when not running",
            )


class ApplicationReleaseOrchestrationTests(SimpleTestCase):
    """T13: deploy/run_application_release.sh shared orchestration."""

    def _prepared(self, harness: Harness, *, race_live: str = "running") -> None:
        self.assertTrue(
            (harness.work / ORCHESTRATION_REL).is_file(),
            "missing deploy/run_application_release.sh (shared release orchestration)",
        )
        self.assertTrue(
            (harness.work / LOCK_SCRIPT_REL).is_file(),
            "missing deploy/deployment_lock.sh",
        )
        seed_services(harness, race_live=race_live)
        locked = acquire_lock(harness, LOCK_TOKEN_A)
        self.assertEqual(locked.returncode, 0, locked.stderr)
        harness.clear_log()

    def _run_orchestration(self, harness: Harness, **env):
        repair = harness.work.resolve() / "runtime" / "migration_history_repair"
        artifact_dir = repair / "preflight" / "before.orchestration"
        artifact_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        artifact_path = artifact_dir / "preflight.json"
        if not artifact_path.exists():
            artifact_path.write_text(
                '{"handoff_action":"deploy"}\n',
                encoding="utf-8",
            )
        overrides = {
            "COMPOSE_FILE": COMPOSE_STANDARD,
            "DEPLOYMENT_LOCK_TOKEN": LOCK_TOKEN_A,
            "RELEASE_B_PREFLIGHT_ARTIFACT_PATH": str(artifact_path),
            "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256": "a" * 64,
            "EXPECTED_CANDIDATE_COMMIT": "b" * 40,
            "EXPECTED_CANDIDATE_IMAGE_ID": "sha256:" + "c" * 64,
            "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256": "d" * 64,
            "RESTRICTED_RECOVERY_ATTEMPT_MODE": "not-required",
        }
        overrides.update(env)
        return harness.run_script(ORCHESTRATION_REL, **overrides)

    def _race_live_calls(self, evts: list, verb: str) -> list:
        return [
            a
            for _cf, a in compose_calls(evts)
            if a[:1] == [verb] and "race_live_worker" in a
        ]

    def test_attempt_mode_only_activates_from_exact_artifact_and_stale_env_is_cleared(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="running")
            result = self._run_orchestration(
                harness, RESTRICTED_RECOVERY_ATTEMPT_MODE="required"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            release_calls = [
                argv
                for _compose_file, argv in compose_calls(harness.events())
                if argv[:3] == ["run", "--rm", "--no-deps"]
            ]
            self.assertEqual(len(release_calls), 1)
            self.assertIn(
                "RESTRICTED_RECOVERY_ATTEMPT_MODE=not-required",
                " ".join(release_calls[0]),
            )

        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="running")
            artifact = (
                harness.work.resolve()
                / "runtime"
                / "migration_history_repair"
                / "preflight"
                / "before.orchestration"
                / "preflight.json"
            )
            artifact.parent.mkdir(parents=True, mode=0o700)
            artifact.write_text(
                '{"handoff_action":"deploy","recovery_intent_mode":"required"}',
                encoding="utf-8",
            )
            artifact.chmod(0o600)
            result = self._run_orchestration(
                harness, RESTRICTED_RECOVERY_ATTEMPT_MODE=None
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            release_calls = [
                argv
                for _compose_file, argv in compose_calls(harness.events())
                if argv[:3] == ["run", "--rm", "--no-deps"]
            ]
            self.assertEqual(len(release_calls), 1)
            self.assertIn(
                "RESTRICTED_RECOVERY_ATTEMPT_MODE=required",
                " ".join(release_calls[0]),
            )

        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="running")
            artifact = (
                harness.work.resolve()
                / "runtime"
                / "migration_history_repair"
                / "preflight"
                / "before.orchestration"
                / "preflight.json"
            )
            artifact.parent.mkdir(parents=True, mode=0o700)
            artifact.write_text(
                '{"handoff_action":"deploy","recovery_intent_mode":"required"}',
                encoding="utf-8",
            )
            artifact.chmod(0o600)
            result = self._run_orchestration(
                harness, RESTRICTED_RECOVERY_ATTEMPT_MODE="not-required"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(
                [
                    argv
                    for _compose_file, argv in compose_calls(harness.events())
                    if argv[:1] == ["stop"]
                ],
                [],
            )

    def test_t13_race_live_running_is_stopped_before_release_and_restored_once(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="running")
            result = self._run_orchestration(harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            evts = harness.events()
            self.assertEqual(
                len(self._race_live_calls(evts, "stop")),
                1,
                "running race_live_worker must be stopped exactly once",
            )
            self.assertEqual(
                len(self._race_live_calls(evts, "up")),
                1,
                "running race_live_worker must be restored exactly once",
            )
            stop_race = first_index(
                evts, lambda e: e[0] == "compose" and e[2] == ["stop", "race_live_worker"]
            )
            stop_web = first_index(
                evts, lambda e: e[0] == "compose" and e[2] == ["stop", "web"]
            )
            release = first_index(evts, is_release_run)
            up_race = first_index(
                evts,
                lambda e: e[0] == "compose"
                and e[2] == ["up", "-d", "--no-deps", "race_live_worker"],
            )
            up_downstream = first_index(
                evts,
                lambda e: e[0] == "compose"
                and e[2] == ["up", "-d", "--no-deps", "worker", "beat", "nginx"],
            )
            self.assertLess(stop_race, stop_web)
            self.assertLess(stop_web, release)
            self.assertLess(up_downstream, up_race)

    def test_t13_race_live_created_or_stopped_is_never_touched(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="stopped")
            result = self._run_orchestration(harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            evts = harness.events()
            self.assertEqual(self._race_live_calls(evts, "stop"), [])
            self.assertEqual(self._race_live_calls(evts, "up"), [])

    def test_t13_race_live_absent_is_never_started(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="absent")
            result = self._run_orchestration(harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            evts = harness.events()
            self.assertEqual(self._race_live_calls(evts, "stop"), [])
            self.assertEqual(self._race_live_calls(evts, "up"), [])

    def test_t13_migration_runs_only_after_worker_race_live_and_web_stopped(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="running")
            result = self._run_orchestration(harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            evts = harness.events()
            release = first_index(evts, is_release_run)
            self.assertIsNotNone(release)
            for service in ("worker", "race_live_worker", "web"):
                stop_index = first_index(
                    evts, lambda e, s=service: e[0] == "compose" and e[2] == ["stop", s]
                )
                self.assertIsNotNone(stop_index, f"missing stop {service}")
                self.assertLess(
                    stop_index,
                    release,
                    f"migration ran before {service} was stopped",
                )

    def test_t13_release_failure_prevents_any_service_restart(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="running")
            harness.set_rc("compose-run", 1)
            result = self._run_orchestration(harness)
            self.assertNotEqual(result.returncode, 0)
            ups = [a for _cf, a in compose_calls(harness.events()) if a[:1] == ["up"]]
            self.assertEqual(ups, [])

    def test_t13_unhealthy_web_prevents_downstream_start(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="running")
            harness.set_state(f"inspect-{SERVICE_IDS['web']}", "true starting\n")
            result = self._run_orchestration(
                harness, SERVICE_HEALTH_TIMEOUT_SECONDS="3"
            )
            self.assertNotEqual(result.returncode, 0)
            ups = [a for _cf, a in compose_calls(harness.events()) if a[:1] == ["up"]]
            self.assertEqual(
                [a for a in ups if "worker" in a or "race_live_worker" in a],
                [],
                "worker/beat/nginx/race_live must not start when web is not healthy",
            )

    def test_t13_race_live_state_probe_failure_fails_closed_before_any_stop(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="running")
            harness.set_rc(f"inspect-{SERVICE_IDS['race_live_worker']}", 1)
            result = self._run_orchestration(harness)
            self.assertNotEqual(result.returncode, 0)
            stops = [
                a for _cf, a in compose_calls(harness.events()) if a[:1] == ["stop"]
            ]
            self.assertEqual(
                stops,
                [],
                "orchestration must fail closed before any stop when state probing fails",
            )

    def test_t13_orchestration_requires_valid_lock_token(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="running")
            result = self._run_orchestration(
                harness, DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_B
            )
            self.assertNotEqual(result.returncode, 0)
            calls = compose_calls(harness.events())
            self.assertEqual(calls, [])

    def test_t13_drain_requires_complete_expected_worker_snapshot(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self.assertTrue(
                (harness.work / DRAIN_SCRIPT_REL).is_file(),
                "missing deploy/wait_for_celery_drain.sh",
            )
            seed_services(harness)
            harness.set_state("drain-strict", "1\n")
            harness.set_state("drain-nodes", "worker-node-a race-live-node-b\n")
            complete = harness.run_script(
                DRAIN_SCRIPT_REL,
                COMPOSE_FILE=COMPOSE_STANDARD,
                EXPECTED_CELERY_WORKERS="worker-node-a race-live-node-b",
            )
            self.assertEqual(
                complete.returncode,
                0,
                f"drain must succeed when every expected node is in the snapshot: {complete.stderr}",
            )
            harness.set_state("drain-nodes", "worker-node-a\n")
            missing = harness.run_script(
                DRAIN_SCRIPT_REL,
                COMPOSE_FILE=COMPOSE_STANDARD,
                EXPECTED_CELERY_WORKERS="worker-node-a race-live-node-b",
            )
            self.assertNotEqual(
                missing.returncode,
                0,
                "drain must fail when any expected node (regular or race-live) is missing",
            )

    def test_t13_drain_failure_keeps_web_running(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness, race_live="running")
            harness.set_rc("exec-drain", 1)
            result = self._run_orchestration(harness)
            self.assertNotEqual(result.returncode, 0)
            evts = harness.events()
            self.assertIsNone(
                first_index(
                    evts, lambda e: e[0] == "compose" and e[2] == ["stop", "web"]
                ),
                "web must not be stopped when celery drain fails",
            )
            self.assertEqual([e for e in evts if is_release_run(e)], [])


class DeployFailClosedTests(SimpleTestCase):
    """T14: deploy.sh stops immediately at each injected failure point."""

    def _run(self, harness: Harness):
        return harness.run_script("deploy/deploy.sh")

    def _stateful_calls(self, harness: Harness) -> list:
        return [
            a
            for _cf, a in compose_calls(harness.events())
            if a[:1] in (["stop"], ["up"], ["run"], ["build"], ["pull"])
        ]

    def test_t14_preflight_failure_runs_zero_stateful_actions(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness)
            harness.set_rc("exec-preflight", 1)
            result = self._run(harness)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self._stateful_calls(harness), [])

    def test_t14_drain_failure_never_stops_web_or_releases(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness)
            harness.set_rc("exec-drain", 1)
            result = self._run(harness)
            self.assertNotEqual(result.returncode, 0)
            evts = harness.events()
            calls = compose_calls(evts)
            self.assertIn(["stop", "beat"], [a for _cf, a in calls])
            self.assertNotIn(["stop", "web"], [a for _cf, a in calls])
            self.assertEqual([e for e in evts if is_release_run(e)], [])
            self.assertEqual([a for _cf, a in calls if a[:1] == ["up"]], [])

    def test_t14_stop_web_failure_prevents_release_and_restart(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness)
            harness.set_rc("stop-web", 1)
            result = self._run(harness)
            self.assertNotEqual(result.returncode, 0)
            evts = harness.events()
            calls = compose_calls(evts)
            self.assertEqual([e for e in evts if is_release_run(e)], [])
            self.assertEqual([a for _cf, a in calls if a[:1] == ["up"]], [])

    def test_t14_release_failure_prevents_any_restart(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness)
            harness.set_rc("compose-run", 1)
            result = self._run(harness)
            self.assertNotEqual(result.returncode, 0)
            calls = compose_calls(harness.events())
            ups = [a for _cf, a in calls if a[:1] == ["up"]]
            self.assertEqual(ups, [])
            self.assertEqual(
                [a for a in ups if "race_live_worker" in a],
                [],
                "race_live_worker restore count must be 0 after release failure",
            )

    def test_t14_web_start_failure_prevents_downstream_start(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness)
            harness.set_rc("up-web", 1)
            result = self._run(harness)
            self.assertNotEqual(result.returncode, 0)
            calls = compose_calls(harness.events())
            ups = [a for _cf, a in calls if a[:1] == ["up"]]
            self.assertEqual(
                [a for a in ups if "worker" in a or "race_live_worker" in a],
                [],
                "downstream services must not start when web fails to start",
            )

    def test_t14_unhealthy_web_prevents_downstream_start(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness)
            harness.set_state(
                f"inspect-seq-{SERVICE_IDS['web']}", "true healthy\ntrue starting\n"
            )
            # static inspect file would win over seq removal; remove it
            static_probe = harness.state / f"inspect-{SERVICE_IDS['web']}"
            if static_probe.exists():
                static_probe.unlink()
            result = harness.run_script(
                "deploy/deploy.sh", SERVICE_HEALTH_TIMEOUT_SECONDS="3"
            )
            self.assertNotEqual(result.returncode, 0)
            calls = compose_calls(harness.events())
            ups = [a for _cf, a in calls if a[:1] == ["up"]]
            self.assertEqual(
                [a for a in ups if "worker" in a or "race_live_worker" in a],
                [],
                "worker/beat/nginx and race_live restore must be 0 after unhealthy web",
            )


class ComposePsProbeFailClosedTests(SimpleTestCase):
    """P2-1: a failing `compose ps -q` probe must fail closed everywhere.

    A ps failure must never be read as "service not running": every top-level
    entry must stop before any stateful action when the probe itself errors.
    """

    def test_p2_orchestration_ps_probe_failure_fails_closed_before_any_stop(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            locked = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(locked.returncode, 0, locked.stderr)
            harness.set_rc("ps-q-race_live_worker", 1)
            harness.clear_log()
            result = harness.run_script(
                ORCHESTRATION_REL,
                COMPOSE_FILE=COMPOSE_STANDARD,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
            )
            self.assertNotEqual(result.returncode, 0)
            stops = [
                a for _cf, a in compose_calls(harness.events()) if a[:1] == ["stop"]
            ]
            self.assertEqual(
                stops,
                [],
                "compose ps probe failure must fail closed before any stop",
            )

    def test_p2_manual_release_ps_probe_failure_yields_zero_compose_run(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, web="absent", race_live="absent")
            for service in ("web", "worker", "beat", "race_live_worker"):
                harness.set_rc(f"ps-q-{service}", 1)
            result = harness.run_script(
                MANUAL_RELEASE_REL, COMPOSE_FILE=COMPOSE_STANDARD
            )
            self.assertNotEqual(result.returncode, 0)
            runs = [
                a for _cf, a in compose_calls(harness.events()) if a[:1] == ["run"]
            ]
            self.assertEqual(
                runs,
                [],
                "manual release must not run the release task when ps probes fail",
            )

    def test_p2_bridge_ps_probe_failure_stops_before_image_tag(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            harness.set_rc("ps-q-race_live_worker", 1)
            result = harness.run_script(
                PRE_CONTRACT_BRIDGE_REL,
                "umanewsbot:prod-frozen-20260701",
                COMPOSE_FILE=COMPOSE_STANDARD,
                SCHEMA_COMPATIBLE_WITH_TARGET="true",
            )
            self.assertNotEqual(result.returncode, 0)
            evts = harness.events()
            self.assertEqual(
                [e for e in evts if e[0] == "docker" and e[2][:1] == ["tag"]],
                [],
                "compose ps probe failure must stop the bridge before docker tag",
            )
            stops = [
                a for _cf, a in compose_calls(evts) if a[:1] == ["stop"]
            ]
            self.assertEqual(
                stops,
                [],
                "compose ps probe failure must fail closed before any stop",
            )


class DeploymentLockCoverageTests(SimpleTestCase):
    """P3-2/P3-4: the deployment lock must cover historical preflight (spec 5.4)."""

    DEPLOY_SCRIPTS = ("deploy/deploy.sh", "deploy/deploy_lowcost.sh")

    def _acquire_and_preflight_lines(self, relative: str) -> tuple:
        lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
        acquire = next(
            (
                index
                for index, line in enumerate(lines)
                if "deployment_lock.sh" in line and "acquire" in line
            ),
            None,
        )
        preflight = next(
            (
                index
                for index, line in enumerate(lines)
                if "historical_runner_preflight" in line
            ),
            None,
        )
        return lines, acquire, preflight

    def test_p3_lock_acquire_runs_before_historical_preflight(self):
        for relative in self.DEPLOY_SCRIPTS:
            with self.subTest(script=relative):
                _lines, acquire, preflight = self._acquire_and_preflight_lines(relative)
                self.assertIsNotNone(
                    acquire, f"{relative} must acquire the deployment lock"
                )
                self.assertIsNotNone(
                    preflight, f"{relative} must keep historical runner preflight"
                )
                self.assertLess(
                    acquire,
                    preflight,
                    "deployment lock must be acquired before historical preflight "
                    "(spec 5.4: the lock covers preflight)",
                )

    def test_p3_lock_acquire_passes_compose_file(self):
        for relative in self.DEPLOY_SCRIPTS:
            with self.subTest(script=relative):
                lines, acquire, _preflight = self._acquire_and_preflight_lines(relative)
                self.assertIsNotNone(acquire)
                self.assertIn(
                    "COMPOSE_FILE",
                    lines[acquire],
                    "lock acquire must pass COMPOSE_FILE so the lock metadata "
                    "records the compose file in use",
                )

    def test_p3_lock_metadata_records_compose_file(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            result = harness.run_script(
                LOCK_SCRIPT_REL,
                "acquire",
                DEPLOYMENT_LOCK_ACTION="deploy",
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
                COMPOSE_FILE=COMPOSE_STANDARD,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            metadata_files = {
                path.name: path.read_text(encoding="utf-8").strip()
                for path in harness.lock_dir.iterdir()
                if path.is_file()
            }
            self.assertIn("compose_file", metadata_files)
            self.assertEqual(metadata_files["compose_file"], COMPOSE_STANDARD)


class ShellAndComposeStaticValidationTests(SimpleTestCase):
    """T16: sh -n over deploy scripts and real compose config validation."""

    def test_t16_r0_host_entry_and_direct_helper_graph_is_executable(self):
        graph_sources = (
            "deploy.sh",
            "deploy_lowcost.sh",
            "deploy/deploy.sh",
            "deploy/deploy_lowcost.sh",
            "deploy/run_application_release.sh",
        )
        direct_paths = {"deploy.sh", "deploy_lowcost.sh"}
        direct_path_pattern = re.compile(r"\./(deploy/[A-Za-z0-9_./-]+\.sh)")
        for relative in graph_sources:
            source = (ROOT / relative).read_text(encoding="utf-8")
            direct_paths.update(direct_path_pattern.findall(source))

        required_paths = {
            "deploy.sh",
            "deploy_lowcost.sh",
            "deploy/deploy.sh",
            "deploy/deploy_lowcost.sh",
            "deploy/docker/compose-wrapper.sh",
            "deploy/wait_for_celery_drain.sh",
        }
        self.assertTrue(
            required_paths <= direct_paths,
            "R0 source parsing must retain the standard/lowcost entry and "
            "direct-helper execution graph",
        )

        missing_execute_bits = {
            relative: oct((ROOT / relative).stat().st_mode & 0o777)
            for relative in sorted(direct_paths)
            if (ROOT / relative).stat().st_mode & 0o111 != 0o111
        }
        self.assertEqual(
            missing_execute_bits,
            {},
            "raw Git checkout files invoked directly by the R0 standard/lowcost "
            f"host graph must retain all execute bits: {missing_execute_bits}",
        )

    def test_t16_compose_wrapper_direct_execution_uses_fake_docker(self):
        wrapper = DEPLOY_DIR / "docker" / "compose-wrapper.sh"
        with TemporaryDirectory() as tmp:
            fake_docker = Path(tmp) / "docker"
            _write_executable(
                fake_docker,
                """#!/bin/sh
if [ "$*" = "compose version" ] || [ "$*" = "compose --help" ]; then
  exit 0
fi
exit 99
""",
            )
            result = subprocess.run(
                [str(wrapper), "--help"],
                text=True,
                capture_output=True,
                check=False,
                env={
                    **os.environ,
                    "PATH": f"{tmp}{os.pathsep}/usr/bin:/bin",
                },
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_t16_all_deploy_shell_scripts_pass_syntax_check(self):
        scripts = sorted(DEPLOY_DIR.glob("*.sh")) + sorted(
            (DEPLOY_DIR / "docker").glob("*.sh")
        )
        self.assertTrue(scripts, "no deploy shell scripts found")
        for script in scripts:
            with self.subTest(script=script.name):
                result = subprocess.run(
                    ["sh", "-n", str(script)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def _assert_compose_config(self, compose_file: str) -> None:
        docker = shutil.which("docker")
        if docker is None:
            self.skipTest(
                "docker CLI not available; compose config validation was NOT verified"
            )
        wrapper = DEPLOY_DIR / "docker" / "compose-wrapper.sh"
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            shutil.copy(ROOT / compose_file, work / compose_file)
            # Non-sensitive empty .env: absence must not be reported as a product failure.
            (work / ".env").write_text("", encoding="utf-8")
            result = subprocess.run(
                ["sh", str(wrapper), "-f", compose_file, "config"],
                cwd=work,
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_t16_standard_compose_config_is_valid(self):
        self._assert_compose_config(COMPOSE_STANDARD)

    def test_t16_lowcost_compose_config_is_valid(self):
        self._assert_compose_config(COMPOSE_LOWCOST)


class HistoricalInitialInstallSemanticsTests(SimpleTestCase):
    """T18: initial-install is not a greenfield bootstrap capability."""

    def test_t18_deploy_without_existing_web_fails_before_any_release(self):
        for extra_env in ({}, {"HISTORICAL_RUNNER_INITIAL_INSTALL": "true"}):
            with self.subTest(env=extra_env):
                with TemporaryDirectory() as tmp:
                    harness = Harness(Path(tmp))
                    seed_services(harness, web="absent", race_live="absent")
                    result = harness.run_script("deploy/deploy.sh", **extra_env)
                    self.assertNotEqual(result.returncode, 0)
                    evts = harness.events()
                    calls = compose_calls(evts)
                    self.assertEqual(
                        [a for _cf, a in calls if a[:1] in (["up"], ["run"])],
                        [],
                        "deploy must not start web or run release tasks without an existing healthy web",
                    )
                    self.assertEqual([e for e in evts if is_exec_migrate(e)], [])

    def test_t18_docs_do_not_present_initial_install_as_greenfield_bootstrap(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in DEPLOY_DOC_PATHS if path.is_file()
        )
        self.assertIn("HISTORICAL_RUNNER_INITIAL_INSTALL", combined)
        self.assertRegex(
            combined,
            r"(不是|并非|不在|不能)[^\n]{0,60}(全新站点|greenfield)"
            r"|(全新站点|greenfield)[^\n]{0,60}(不在|不是|并非)",
            "deploy docs must explicitly state initial-install is not a greenfield install",
        )

    def test_t18_no_release_task_bypass_mode_survives(self):
        for relative in (
            "deploy/run_application_release.sh",
            "deploy/run_release_tasks.sh",
            "deploy/docker/run-release-tasks.sh",
        ):
            self.assertNotIn(
                "historical-initial-install",
                (ROOT / relative).read_text(encoding="utf-8"),
                relative,
            )

    def test_t18_pre_0070_initial_install_reaches_release_for_standard_and_lowcost(self):
        for script, compose_file in (
            ("deploy/deploy.sh", COMPOSE_STANDARD),
            ("deploy/deploy_lowcost.sh", COMPOSE_LOWCOST),
        ):
            with self.subTest(script=script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness, race_live="running")
                seed_git_head(harness)
                harness.set_state(
                    "initial-install-schema", "historical-initial-install-pre-0070\n"
                )
                harness.set_state("preflight-attempt-mode", "required\n")
                result = harness.run_script(
                    script, HISTORICAL_RUNNER_INITIAL_INSTALL="true"
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                runs = [a for _cf, a in compose_calls(harness.events()) if a[:1] == ["run"]]
                self.assertEqual(len(runs), 3)
                self.assertEqual(
                    runs[0],
                    ["run", "--rm", "--no-deps", "nginx", "nginx", "-t"],
                )
                self.assertTrue(any("--action=initial-install" in arg for arg in runs[1]))
                self.assertTrue(any("--output-path=" in arg for arg in runs[1]))
                self.assertIn("RELEASE_HANDOFF_MODE=release-b", runs[2])
                self.assertEqual(
                    {cf for cf, _a in compose_calls(harness.events()) if cf},
                    {compose_file},
                )

    def test_t18_missing_or_sqlite_database_engine_stops_before_stateful_release(self):
        for script in ("deploy/deploy.sh", "deploy/deploy_lowcost.sh"):
            for engine_case in ("missing", "sqlite"):
                with self.subTest(script=script, engine=engine_case), TemporaryDirectory() as tmp:
                    harness = Harness(Path(tmp))
                    seed_services(harness, race_live="running")
                    seed_git_head(harness)
                    harness.set_state("database-vendor", "sqlite\n")
                    harness.set_state(
                        "initial-install-schema",
                        "historical-initial-install-pre-0070\n",
                    )
                    result = harness.run_script(
                        script,
                        HISTORICAL_RUNNER_INITIAL_INSTALL="true",
                        DB_ENGINE=(None if engine_case == "missing" else "django.db.backends.sqlite3"),
                    )
                    self.assertNotEqual(result.returncode, 0)
                    calls = compose_calls(harness.events())
                    self.assertEqual(
                        [a for _cf, a in calls if a[:1] in (["build"], ["stop"], ["up"], ["run"])],
                        [],
                    )
                    self.assertEqual([e for e in harness.events() if is_exec_migrate(e)], [])

    def test_t18_pre_0070_without_flag_still_requires_release_b_preflight(self):
        for script in ("deploy/deploy.sh", "deploy/deploy_lowcost.sh"):
            with self.subTest(script=script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness, race_live="running")
                seed_git_head(harness)
                harness.set_state(
                    "initial-install-schema", "historical-initial-install-pre-0070\n"
                )
                harness.set_rc("compose-run", 81)
                result = harness.run_script(script)
                self.assertEqual(result.returncode, 81, result.stderr)
                self.assertEqual(
                    [a for _cf, a in compose_calls(harness.events()) if a[:1] == ["stop"]],
                    [],
                )
                self.assertFalse(
                    any(
                        RELEASE_TASK_CONTAINER_PATH in a
                        for _cf, a in compose_calls(harness.events())
                    )
                )

    def test_t18_0070_or_later_cannot_use_initial_install_bypass(self):
        for script in ("deploy/deploy.sh", "deploy/deploy_lowcost.sh"):
            with self.subTest(script=script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness, race_live="running")
                seed_git_head(harness)
                harness.set_state(
                    "initial-install-schema",
                    "historical-initial-install-0070-or-later\n",
                )
                result = harness.run_script(
                    script, HISTORICAL_RUNNER_INITIAL_INSTALL="true"
                )
                self.assertNotEqual(result.returncode, 0)
                stateful = [
                    a
                    for _cf, a in compose_calls(harness.events())
                    if a[:1] in (["build"], ["stop"], ["up"], ["run"])
                ]
                self.assertEqual(stateful, [])


class MigrationDriftGuardTests(SimpleTestCase):
    """T19: only explicitly reviewed migrations may be new."""

    def test_t19_no_new_migration_files(self):
        result = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain", "--", "server/stable/migrations"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        unexpected = [
            line
            for line in result.stdout.splitlines()
            if not line.endswith((
                "server/stable/migrations/0070_horse_identity_evidence_commit_receipt.py",
                "server/stable/migrations/0071_historical_calendar_release_b.py",
                "server/stable/migrations/0074_race_data_sync_r0_control_plane.py",
                "server/stable/migrations/0075_race_data_source_priority_and_reported_position.py",
            ))
        ]
        self.assertEqual(unexpected, [], f"unexpected migration drift:\n{result.stdout}")


def race_live_state_file(harness: Harness) -> Path:
    """Frozen race_live_worker state shared across release retries."""
    return Path(f"{harness.lock_dir}.race-live-state")


def release_b_handoff_env(harness: Harness) -> dict[str, str]:
    repair = harness.work.resolve() / "runtime" / "migration_history_repair"
    artifact_dir = repair / "preflight" / "before.shared"
    artifact_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifact_path = artifact_dir / "preflight.json"
    artifact_path.write_text(
        '{"handoff_action":"deploy"}\n',
        encoding="utf-8",
    )
    return {
        "RELEASE_B_PREFLIGHT_ARTIFACT_PATH": str(artifact_path),
        "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256": "a" * 64,
        "EXPECTED_CANDIDATE_COMMIT": "b" * 40,
        "EXPECTED_CANDIDATE_IMAGE_ID": "sha256:" + "c" * 64,
        "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256": "d" * 64,
    }


HEAD_OID = "f1f2f3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0"
OTHER_HEAD_OID = "0a1b2c3d4e5f6a7b8c9d0f1f2f3f4a5b6c7d8e9f"


def seed_git_head(harness: Harness, oid: str = HEAD_OID) -> None:
    """Make fake `git rev-parse HEAD` resolve to the given OID."""
    harness.set_state("git-rev-parse-head", f"{oid}\n")


def write_frozen_race_live_state(
    harness: Harness,
    state: str,
    node: str = "frozennode00",
    *,
    action: str = "deploy",
    compose_file: str = COMPOSE_STANDARD,
    head: str = HEAD_OID,
    mode: int = 0o600,
) -> Path:
    """Pre-write a bound frozen race_live state file (writer format, mode 600)."""
    state_file = race_live_state_file(harness)
    state_file.write_text(
        f"state={state}\n"
        f"node={node}\n"
        f"compose_file={compose_file}\n"
        f"action={action}\n"
        f"head={head}\n"
        "frozen_at_utc=2026-07-28T00:00:00Z\n",
        encoding="utf-8",
    )
    state_file.chmod(mode)
    return state_file


def seed_services_with_hostnames(harness: Harness) -> None:
    """Seed all services running with deterministic celery node hostnames."""
    seed_services(harness, race_live="running")
    harness.set_state(
        f"inspect-{SERVICE_IDS['worker']}", "true healthy workerhost01\n"
    )
    harness.set_state(
        f"inspect-{SERVICE_IDS['race_live_worker']}", "true healthy racehost01\n"
    )


class RaceDataSyncWorkerReleaseStateTests(SimpleTestCase):
    def _run_orchestration(self, harness: Harness):
        return harness.run_script(
            ORCHESTRATION_REL,
            COMPOSE_FILE=COMPOSE_STANDARD,
            DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
            RELEASE_ACTION="deploy",
            **release_b_handoff_env(harness),
        )

    def test_running_sync_worker_is_drained_stopped_and_restored(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(
                harness,
                race_live="stopped",
                race_sync="running",
            )
            seed_git_head(harness)
            harness.set_state(
                f"inspect-{SERVICE_IDS['worker']}",
                "true healthy workerhost01\n",
            )
            harness.set_state(
                f"inspect-{SERVICE_IDS['race_sync_v2_worker']}",
                "true healthy synchost01\n",
            )
            harness.set_state("drain-strict", "1\n")
            harness.set_state("drain-nodes", "workerhost01 synchost01\n")
            locked = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(locked.returncode, 0, locked.stderr)
            harness.clear_log()

            result = self._run_orchestration(harness)

            self.assertEqual(result.returncode, 0, result.stderr)
            events = harness.events()
            drain = first_index(events, is_drain_exec)
            stop = first_index(
                events,
                lambda event: event[0] == "compose"
                and event[2] == ["stop", "race_sync_v2_worker"],
            )
            stop_web = first_index(
                events,
                lambda event: event[0] == "compose"
                and event[2] == ["stop", "web"],
            )
            restore = first_index(
                events,
                lambda event: event[0] == "compose"
                and event[2] == ["up", "-d", "--no-deps", "race_sync_v2_worker"],
            )
            self.assertIsNotNone(drain)
            self.assertIsNotNone(stop)
            self.assertIsNotNone(stop_web)
            self.assertIsNotNone(restore)
            self.assertLess(drain, stop)
            self.assertLess(stop, stop_web)
            self.assertLess(stop_web, restore)
            drain_calls = [event[2] for event in events if is_drain_exec(event)]
            self.assertTrue(any("synchost01" in " ".join(call) for call in drain_calls))
            self.assertFalse(Path(f"{harness.lock_dir}.race-data-sync-state").exists())

    def test_sync_worker_probe_failure_is_before_any_stop(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_sync="running")
            seed_git_head(harness)
            harness.set_rc("ps-q-race_sync_v2_worker", 1)
            locked = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(locked.returncode, 0, locked.stderr)
            harness.clear_log()

            result = self._run_orchestration(harness)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("race_sync_v2_worker", result.stderr)
            self.assertFalse(
                any(
                    event[0] == "compose" and event[2][:1] == ["stop"]
                    for event in harness.events()
                )
            )


class RaceLiveStatePersistenceTests(SimpleTestCase):
    """P1-1: frozen race_live_worker state must survive a failed release retry."""

    def _run_orchestration(self, harness: Harness):
        return harness.run_script(
            ORCHESTRATION_REL,
            COMPOSE_FILE=COMPOSE_STANDARD,
            DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
            RELEASE_ACTION="deploy",
            **release_b_handoff_env(harness),
        )

    def _race_live_ups(self, harness: Harness) -> list:
        return [
            a
            for _cf, a in compose_calls(harness.events())
            if a[:1] == ["up"] and "race_live_worker" in a
        ]

    def test_p1_failed_release_retry_restores_originally_running_race_live(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            seed_git_head(harness)
            locked = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(locked.returncode, 0, locked.stderr)
            harness.set_rc("compose-run", 1)
            first = self._run_orchestration(harness)
            self.assertNotEqual(first.returncode, 0)

            state_file = race_live_state_file(harness)
            self.assertTrue(
                state_file.is_file(),
                "a failed release must keep the frozen race_live state file for retry",
            )
            content = state_file.read_text(encoding="utf-8")
            self.assertIn("running", content)
            self.assertNotIn("not-running", content)
            self.assertIn(COMPOSE_STANDARD, content)

            # Retry: the live probe now sees race_live_worker as stopped, but
            # the frozen original state must win and restore it exactly once.
            harness.set_state(
                f"inspect-{SERVICE_IDS['race_live_worker']}", "false exited\n"
            )
            (harness.state / "rc-compose-run").unlink()
            harness.clear_log()
            second = self._run_orchestration(harness)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                len(self._race_live_ups(harness)),
                1,
                "retry must restore race_live_worker from the frozen original state",
            )
            self.assertFalse(
                state_file.exists(),
                "a fully successful release must remove the frozen state file",
            )

    def test_p1_failed_release_retry_keeps_originally_not_running_race_live(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="stopped")
            seed_git_head(harness)
            locked = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(locked.returncode, 0, locked.stderr)
            harness.set_rc("compose-run", 1)
            first = self._run_orchestration(harness)
            self.assertNotEqual(first.returncode, 0)

            state_file = race_live_state_file(harness)
            self.assertTrue(
                state_file.is_file(),
                "a failed release must keep the frozen race_live state file for retry",
            )
            self.assertIn("not-running", state_file.read_text(encoding="utf-8"))

            # Retry: even if race_live_worker started running in the meantime,
            # the frozen not-running state must prevent any restore.
            harness.set_state(
                f"inspect-{SERVICE_IDS['race_live_worker']}", "true healthy\n"
            )
            (harness.state / "rc-compose-run").unlink()
            harness.clear_log()
            second = self._run_orchestration(harness)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(self._race_live_ups(harness), [])
            self.assertFalse(state_file.exists())


class RaceLiveRetrySemanticsTests(SimpleTestCase):
    """P1: the frozen state file decides restore intent only.

    Every attempt must still probe the CURRENT race_live_worker state to decide
    stopping and drain membership; a probe failure fails closed even when a
    frozen state file exists.
    """

    def _run_orchestration(self, harness: Harness):
        return harness.run_script(
            ORCHESTRATION_REL,
            COMPOSE_FILE=COMPOSE_STANDARD,
            DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
            RELEASE_ACTION="deploy",
            **release_b_handoff_env(harness),
        )

    def _race_live_calls(self, harness: Harness, verb: str) -> list:
        return [
            a
            for _cf, a in compose_calls(harness.events())
            if a[:1] == [verb] and "race_live_worker" in a
        ]

    def test_p1_frozen_not_running_current_running_still_stops_and_drains(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services_with_hostnames(harness)
            seed_git_head(harness)
            locked = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(locked.returncode, 0, locked.stderr)
            state_file = write_frozen_race_live_state(harness, "not-running")
            harness.set_state("drain-strict", "1\n")
            harness.set_state("drain-nodes", "workerhost01 racehost01\n")
            harness.clear_log()
            result = self._run_orchestration(harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            evts = harness.events()
            stop_race_live = first_index(
                evts,
                lambda e: e[0] == "compose" and e[2] == ["stop", "race_live_worker"],
            )
            self.assertIsNotNone(
                stop_race_live,
                "current running race_live_worker must be stopped even when the "
                "frozen restore intent is not-running",
            )
            release = first_index(evts, is_release_run)
            self.assertIsNotNone(release)
            self.assertLess(stop_race_live, release)
            drain_execs = [e[2] for e in evts if is_drain_exec(e)]
            self.assertTrue(drain_execs)
            self.assertTrue(
                any("racehost01" in " ".join(argv) for argv in drain_execs),
                "drain EXPECTED_CELERY_WORKERS must include the currently running "
                "race_live node",
            )
            self.assertEqual(
                self._race_live_calls(harness, "up"),
                [],
                "frozen not-running intent must not restore race_live_worker",
            )
            self.assertFalse(state_file.exists())

    def test_p1_frozen_running_current_not_running_restores_once(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="stopped")
            seed_git_head(harness)
            locked = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(locked.returncode, 0, locked.stderr)
            state_file = write_frozen_race_live_state(harness, "running")
            harness.clear_log()
            result = self._run_orchestration(harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                self._race_live_calls(harness, "stop"),
                [],
                "currently stopped race_live_worker must not be stopped again",
            )
            self.assertEqual(
                len(self._race_live_calls(harness, "up")),
                1,
                "frozen running intent must restore race_live_worker exactly once",
            )
            self.assertFalse(state_file.exists())

    def test_p1_frozen_state_file_does_not_skip_probe_fail_closed(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            seed_git_head(harness)
            locked = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(locked.returncode, 0, locked.stderr)
            write_frozen_race_live_state(harness, "running")
            harness.set_rc("ps-q-race_live_worker", 1)
            harness.clear_log()
            result = self._run_orchestration(harness)
            self.assertNotEqual(result.returncode, 0)
            stops = [
                a
                for _cf, a in compose_calls(harness.events())
                if a[:1] == ["stop"]
            ]
            self.assertEqual(
                stops,
                [],
                "a state file must never bypass the current-state probe; "
                "probe failure fails closed before any stop",
            )

    def test_p1_bridge_frozen_not_running_current_running_still_stops_race_live(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services_with_hostnames(harness)
            seed_git_head(harness)
            state_file = write_frozen_race_live_state(
                harness, "not-running", action="pre-contract-rollback"
            )
            harness.set_state("drain-strict", "1\n")
            harness.set_state("drain-nodes", "workerhost01 racehost01\n")
            harness.clear_log()
            result = harness.run_script(
                PRE_CONTRACT_BRIDGE_REL,
                "umanewsbot:prod-frozen-20260701",
                COMPOSE_FILE=COMPOSE_STANDARD,
                SCHEMA_COMPATIBLE_WITH_TARGET="true",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evts = harness.events()
            stop_race_live = first_index(
                evts,
                lambda e: e[0] == "compose" and e[2] == ["stop", "race_live_worker"],
            )
            self.assertIsNotNone(
                stop_race_live,
                "bridge must stop a currently running race_live_worker even when "
                "the frozen restore intent is not-running",
            )
            tag = first_index(
                evts, lambda e: e[0] == "docker" and e[2][:1] == ["tag"]
            )
            self.assertIsNotNone(tag)
            self.assertLess(stop_race_live, tag)
            drain_execs = [e[2] for e in evts if is_drain_exec(e)]
            self.assertTrue(
                any("racehost01" in " ".join(argv) for argv in drain_execs),
                "bridge drain EXPECTED must include the currently running "
                "race_live node",
            )
            self.assertEqual(
                self._race_live_calls(harness, "up"),
                [],
                "frozen not-running intent must not restore race_live_worker",
            )
            self.assertFalse(state_file.exists())


class RaceLiveStateBindingTests(SimpleTestCase):
    """P1-3: frozen race_live state files must be bound and trustworthy.

    Orchestration/bridge must fail closed before any stop when the state file
    is not a regular non-symlink user-owned mode-600 file, or when its
    compose_file/action/head binding does not match the current attempt.
    """

    def _prepared(self, harness: Harness) -> None:
        seed_services(harness, race_live="running")
        seed_git_head(harness)
        locked = acquire_lock(harness, LOCK_TOKEN_A)
        self.assertEqual(locked.returncode, 0, locked.stderr)
        harness.clear_log()

    def _run_orchestration(self, harness: Harness):
        return harness.run_script(
            ORCHESTRATION_REL,
            COMPOSE_FILE=COMPOSE_STANDARD,
            DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
            RELEASE_ACTION="deploy",
            **release_b_handoff_env(harness),
        )

    def _assert_fail_closed_before_any_stop(self, harness: Harness, result) -> None:
        self.assertNotEqual(result.returncode, 0)
        stops = [
            a
            for _cf, a in compose_calls(harness.events())
            if a[:1] == ["stop"]
        ]
        self.assertEqual(
            stops, [], "untrusted state file must fail closed before any stop"
        )

    def test_p1_compose_file_mismatch_fails_closed(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            write_frozen_race_live_state(
                harness, "running", compose_file=COMPOSE_LOWCOST
            )
            self._assert_fail_closed_before_any_stop(
                harness, self._run_orchestration(harness)
            )

    def test_p1_action_mismatch_fails_closed(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            write_frozen_race_live_state(harness, "running", action="rollback")
            self._assert_fail_closed_before_any_stop(
                harness, self._run_orchestration(harness)
            )

    def test_p1_head_mismatch_fails_closed(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            write_frozen_race_live_state(harness, "running", head=OTHER_HEAD_OID)
            self._assert_fail_closed_before_any_stop(
                harness, self._run_orchestration(harness)
            )

    def test_p1_symlinked_state_file_fails_closed(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            target = harness.base / "elsewhere-state"
            target.write_text(
                "state=running\n"
                "node=frozennode00\n"
                f"compose_file={COMPOSE_STANDARD}\n"
                "action=deploy\n"
                f"head={HEAD_OID}\n"
                "frozen_at_utc=2026-07-28T00:00:00Z\n",
                encoding="utf-8",
            )
            target.chmod(0o600)
            race_live_state_file(harness).symlink_to(target)
            self._assert_fail_closed_before_any_stop(
                harness, self._run_orchestration(harness)
            )

    def test_p1_group_writable_state_file_fails_closed(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._prepared(harness)
            write_frozen_race_live_state(harness, "running", mode=0o620)
            self._assert_fail_closed_before_any_stop(
                harness, self._run_orchestration(harness)
            )

    def test_p1_bridge_action_mismatch_fails_closed(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            # The bridge acquires the lock itself; do NOT pre-hold it here.
            seed_services(harness, race_live="running")
            seed_git_head(harness)
            # The bridge only accepts state frozen by a pre-contract-rollback.
            write_frozen_race_live_state(harness, "running", action="deploy")
            harness.clear_log()
            result = harness.run_script(
                PRE_CONTRACT_BRIDGE_REL,
                "umanewsbot:prod-frozen-20260701",
                COMPOSE_FILE=COMPOSE_STANDARD,
                SCHEMA_COMPATIBLE_WITH_TARGET="true",
            )
            self.assertNotEqual(result.returncode, 0)
            evts = harness.events()
            self.assertEqual(
                [e for e in evts if e[0] == "docker" and e[2][:1] == ["tag"]],
                [],
                "bridge must fail closed before docker tag on binding mismatch",
            )
            stops = [
                a for _cf, a in compose_calls(evts) if a[:1] == ["stop"]
            ]
            self.assertEqual(stops, [])


class ResumeStoppedReleaseTests(SimpleTestCase):
    """P1-2: deploy/resume_stopped_release.sh audited recovery entry."""

    def _assert_script_exists(self, harness: Harness) -> None:
        self.assertTrue(
            (harness.work / RESUME_SCRIPT_REL).is_file(),
            "missing deploy/resume_stopped_release.sh (audited resume entry)",
        )

    def _run_resume(self, harness: Harness, **env):
        overrides = {"COMPOSE_FILE": COMPOSE_STANDARD}
        overrides.update(env)
        return harness.run_script(RESUME_SCRIPT_REL, **overrides)

    def _seed_all_stopped(self, harness: Harness, web_health: str = "true healthy") -> None:
        # web is absent at probe time and gets a container only after `up web`
        # (health wait), mirroring a fully stopped release failure scene.
        harness.set_state("ps-db", f"{SERVICE_IDS['db']}\n")
        harness.set_state(f"inspect-{SERVICE_IDS['db']}", "true healthy\n")
        harness.set_state("ps-redis", f"{SERVICE_IDS['redis']}\n")
        harness.set_state(f"inspect-{SERVICE_IDS['redis']}", "true healthy\n")
        harness.set_state("ps-seq-web", f"\n{SERVICE_IDS['web']}\n")
        harness.set_state(f"inspect-{SERVICE_IDS['web']}", f"{web_health}\n")
        seed_git_head(harness)
        repair_root = harness.work / "runtime" / "migration_history_repair"
        repair_root.mkdir(parents=True, mode=0o700)
        repair_root.chmod(0o700)

    def _stateful_calls(self, harness: Harness) -> list:
        return [
            a
            for _cf, a in compose_calls(harness.events())
            if a[:1] in (["up"], ["run"], ["stop"])
        ]

    def _up_calls(self, harness: Harness, *services: str) -> list:
        return [
            a
            for _cf, a in compose_calls(harness.events())
            if a[:1] == ["up"] and any(s in a for s in services)
        ]

    def test_p1_resume_happy_path_order_without_one_shot(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            self._seed_all_stopped(harness)
            result = self._run_resume(harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            evts = harness.events()
            self.assertEqual(
                [a for _cf, a in compose_calls(evts) if a[:1] == ["run"]],
                [],
                "resume must never invoke the one-shot release task",
            )
            up_web = first_index(
                evts,
                lambda e: e[0] == "compose" and e[2] == ["up", "-d", "--no-deps", "web"],
            )
            self.assertIsNotNone(up_web, "resume must start web")
            healthy = first_index(
                evts[up_web + 1 :],
                lambda e: e[0] == "docker" and e[2][:1] == ["inspect"],
            )
            self.assertIsNotNone(healthy, "resume must wait for web healthy")
            healthy += up_web + 1
            up_downstream = first_index(
                evts,
                lambda e: e[0] == "compose"
                and e[2] == ["up", "-d", "--no-deps", "worker", "beat", "nginx"],
            )
            self.assertIsNotNone(up_downstream)
            final_ps = first_index(
                evts, lambda e: e[0] == "compose" and e[2] == ["ps"]
            )
            self.assertIsNotNone(final_ps)
            self.assertLess(up_web, healthy)
            self.assertLess(healthy, up_downstream)
            self.assertLess(up_downstream, final_ps)
            self.assertEqual(
                self._up_calls(harness, "race_live_worker"),
                [],
                "without an intent file resume must not start race_live_worker",
            )

    def test_p1_resume_rejects_missing_or_untrusted_empty_repair_parent_before_start(self):
        cases = ("missing", "symlink", "wrong-mode", "wrong-owner")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                self._seed_all_stopped(harness)
                repair_root = harness.work / "runtime" / "migration_history_repair"
                if case == "missing":
                    repair_root.rmdir()
                elif case == "symlink":
                    repair_root.rmdir()
                    target = harness.work / "runtime" / "marker-target"
                    target.mkdir(mode=0o700)
                    repair_root.symlink_to(target)
                elif case == "wrong-mode":
                    repair_root.chmod(0o755)
                else:
                    _write_executable(
                        harness.fakes / "stat",
                        """#!/bin/sh
case "$*" in
  *migration_history_repair*) printf '%s\\n' 999999 ;;
  *) exec /usr/bin/stat "$@" ;;
esac
""",
                    )
                harness.clear_log()
                result = self._run_resume(harness)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self._up_calls(harness, "web", "worker", "beat"), [])

    def test_p1_resume_restores_race_live_from_running_intent_and_removes_file(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            self._seed_all_stopped(harness)
            state_file = write_frozen_race_live_state(harness, "running")
            result = self._run_resume(harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            evts = harness.events()
            up_downstream = first_index(
                evts,
                lambda e: e[0] == "compose"
                and e[2] == ["up", "-d", "--no-deps", "worker", "beat", "nginx"],
            )
            self.assertIsNotNone(up_downstream)
            up_race_live = first_index(
                evts,
                lambda e: e[0] == "compose"
                and e[2] == ["up", "-d", "--no-deps", "race_live_worker"],
            )
            self.assertIsNotNone(
                up_race_live, "running intent must restore race_live_worker once"
            )
            self.assertLess(up_downstream, up_race_live)
            self.assertEqual(len(self._up_calls(harness, "race_live_worker")), 1)
            self.assertFalse(
                state_file.exists(),
                "a consumed running intent file must be removed",
            )

    def test_p1_resume_with_invalid_intent_file_skips_race_live_but_recovers_core(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            self._seed_all_stopped(harness)
            write_frozen_race_live_state(harness, "running", head=OTHER_HEAD_OID)
            result = self._run_resume(harness)
            self.assertEqual(
                result.returncode,
                0,
                "an untrusted intent file must NOT fail the whole resume; "
                f"core services must still recover: {result.stderr}",
            )
            self.assertTrue(
                self._up_calls(harness, "web"),
                "core web recovery must proceed despite the invalid intent file",
            )
            self.assertTrue(
                self._up_calls(harness, "worker"),
                "core worker/beat/nginx recovery must proceed",
            )
            self.assertEqual(
                self._up_calls(harness, "race_live_worker"),
                [],
                "an untrusted intent file must skip race_live recovery (safe direction)",
            )

    def test_p1_resume_refuses_when_any_service_running(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, race_live="absent")
            seed_git_head(harness)
            result = self._run_resume(harness)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self._stateful_calls(harness), [])

    def test_p1_resume_refuses_when_service_state_unknown(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            seed_services(harness, web="absent", race_live="absent")
            seed_git_head(harness)
            harness.set_rc(f"inspect-{SERVICE_IDS['worker']}", 1)
            result = self._run_resume(harness)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self._stateful_calls(harness), [])

    def test_p1_resume_refuses_when_service_restarting(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            harness.set_state("ps-beat", f"{SERVICE_IDS['beat']}\n")
            harness.set_state(
                f"inspect-{SERVICE_IDS['beat']}", "false none restarting\n"
            )
            seed_git_head(harness)
            result = self._run_resume(harness)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self._stateful_calls(harness), [])

    def test_p1_resume_refuses_when_lock_is_held_by_another_entry(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            self._seed_all_stopped(harness)
            winner = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(winner.returncode, 0, winner.stderr)
            harness.clear_log()
            result = self._run_resume(harness)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self._stateful_calls(harness), [])
            self.assertTrue(
                harness.lock_dir.is_dir(),
                "resume must not delete the winner lock",
            )

    def test_p1_resume_unhealthy_web_blocks_downstream(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            self._seed_all_stopped(harness, web_health="true starting")
            result = self._run_resume(harness)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(
                self._up_calls(harness, "worker", "race_live_worker"),
                [],
                "unhealthy web must block worker/beat/nginx and race_live recovery",
            )

    def test_p1_resume_deletes_consumed_not_running_intent_file(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            self._seed_all_stopped(harness)
            state_file = write_frozen_race_live_state(harness, "not-running")
            result = self._run_resume(harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                self._up_calls(harness, "race_live_worker"),
                [],
                "a not-running intent must not start race_live_worker",
            )
            self.assertFalse(
                state_file.exists(),
                "a trusted intent file consumed by a fully successful resume "
                "must be deleted regardless of state (running or not-running)",
            )

    def test_p1_consumed_intent_does_not_leak_into_next_orchestration(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            self._seed_all_stopped(harness)
            write_frozen_race_live_state(harness, "not-running")
            resumed = self._run_resume(harness)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)

            # Same HEAD, later deploy: race_live_worker is running now. The
            # orchestration must follow the CURRENT probe (stop + restore),
            # unaffected by the already-consumed not-running intent.
            harness.set_state(
                "ps-race_live_worker", f"{SERVICE_IDS['race_live_worker']}\n"
            )
            harness.set_state(
                f"inspect-{SERVICE_IDS['race_live_worker']}", "true healthy\n"
            )
            harness.set_state("ps-worker", f"{SERVICE_IDS['worker']}\n")
            harness.set_state(f"inspect-{SERVICE_IDS['worker']}", "true healthy\n")
            locked = acquire_lock(harness, LOCK_TOKEN_A)
            self.assertEqual(locked.returncode, 0, locked.stderr)
            harness.clear_log()
            result = harness.run_script(
                ORCHESTRATION_REL,
                COMPOSE_FILE=COMPOSE_STANDARD,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
                RELEASE_ACTION="deploy",
                **release_b_handoff_env(harness),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evts = harness.events()
            stop_race_live = first_index(
                evts,
                lambda e: e[0] == "compose" and e[2] == ["stop", "race_live_worker"],
            )
            self.assertIsNotNone(
                stop_race_live,
                "orchestration must stop the currently running race_live_worker",
            )
            release = first_index(evts, is_release_run)
            self.assertIsNotNone(release)
            self.assertLess(stop_race_live, release)
            self.assertEqual(
                len(self._up_calls(harness, "race_live_worker")),
                1,
                "orchestration must restore race_live_worker from the current "
                "probe; a consumed intent file must not leak a stale "
                "not-running intent into this attempt",
            )

    def test_active_or_transition_repair_marker_blocks_all_service_restart(self):
        for name in (
            "restricted-recovery.json",
            "restricted-recovery.transition.json",
        ):
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                self._assert_script_exists(harness)
                self._seed_all_stopped(harness)
                marker_dir = (
                    harness.work / "runtime" / "migration_history_repair"
                )
                marker_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                marker_dir.chmod(0o700)
                marker = marker_dir / name
                marker.write_text("{}", encoding="utf-8")
                marker.chmod(0o600)
                result = self._run_resume(harness)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("forward-resume", result.stderr)
                self.assertEqual(
                    [
                        argv
                        for _compose_file, argv in compose_calls(harness.events())
                        if argv[:1] == ["up"]
                    ],
                    [],
                )

    def test_p1_resume_keeps_untrusted_intent_file(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            self._assert_script_exists(harness)
            self._seed_all_stopped(harness)
            state_file = write_frozen_race_live_state(
                harness, "running", head=OTHER_HEAD_OID
            )
            result = self._run_resume(harness)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self._up_calls(harness, "race_live_worker"), [])
            self.assertTrue(
                state_file.exists(),
                "an untrusted intent file must be kept for manual review",
            )


class BridgeSchemaGateTests(SimpleTestCase):
    """P1-2: SCHEMA_COMPATIBLE_WITH_TARGET must be explicitly true or false."""

    def test_p1_bridge_rejects_unset_or_invalid_schema_gate_before_any_action(self):
        cases = (
            ("unset", None),
            ("capitalized", "False"),
            ("typo", "flase"),
        )
        for label, value in cases:
            with self.subTest(case=label):
                with TemporaryDirectory() as tmp:
                    harness = Harness(Path(tmp))
                    seed_services(harness, race_live="running")
                    env = {}
                    if value is not None:
                        env["SCHEMA_COMPATIBLE_WITH_TARGET"] = value
                    result = harness.run_script(
                        PRE_CONTRACT_BRIDGE_REL,
                        "umanewsbot:prod-frozen-20260701",
                        COMPOSE_FILE=COMPOSE_STANDARD,
                        **env,
                    )
                    self.assertNotEqual(
                        result.returncode,
                        0,
                        "schema gate must fail closed unless explicitly true/false",
                    )
                    evts = harness.events()
                    self.assertEqual(
                        [
                            a
                            for _cf, a in compose_calls(evts)
                            if a[:1] in (["stop"], ["up"], ["run"])
                        ],
                        [],
                        "schema gate rejection must happen before any service action",
                    )
                    self.assertEqual(
                        [e for e in evts if e[0] == "docker" and e[2][:1] == ["tag"]],
                        [],
                        "schema gate rejection must happen before docker tag",
                    )


class RollbackContractValidationTests(SimpleTestCase):
    """P2-3/P2-4: rollback must validate all v1 helpers at an immutable OID."""

    V1_HELPERS = (
        "deploy/release_contract_v1",
        "deploy/run_application_release.sh",
        "deploy/deployment_lock.sh",
        "deploy/run_release_tasks.sh",
        "deploy/wait_for_compose_service_healthy.sh",
        "deploy/wait_for_celery_drain.sh",
        "deploy/docker/run-release-tasks.sh",
        "deploy/docker/start-web.sh",
        "deploy/docker/compose-wrapper.sh",
    )
    FIXED_OID = "0123456789abcdef0123456789abcdef01234567"

    def _seed_stateful_original(self, harness: Harness, *, branch: bool) -> tuple[str, str]:
        original_oid = "fedcba9876543210fedcba9876543210fedcba98"
        original_image = "sha256:original-production-image"
        harness.set_state("git-stateful-head", "1\n")
        harness.set_state("git-original-head-oid", f"{original_oid}\n")
        harness.set_state("git-rev-parse-head", f"{original_oid}\n")
        if branch:
            harness.set_state("git-head-ref", "refs/heads/production\n")
            harness.set_state("git-original-head-ref", "refs/heads/production\n")
        harness.set_state("prod-image-id", f"{original_image}\n")
        return original_oid, original_image

    def _assert_original_restored(
        self, harness: Harness, original_oid: str, original_image: str, *, branch: bool
    ) -> None:
        self.assertEqual(
            (harness.state / "git-rev-parse-head").read_text().strip(), original_oid
        )
        self.assertEqual(
            (harness.state / "prod-image-id").read_text().strip(), original_image
        )
        head_ref = harness.state / "git-head-ref"
        if branch:
            self.assertEqual(head_ref.read_text().strip(), "refs/heads/production")
        else:
            self.assertFalse(head_ref.exists())
        self.assertEqual(
            [
                argv
                for _compose_file, argv in compose_calls(harness.events())
                if argv[:1] in (["stop"], ["up"])
            ],
            [],
        )

    def test_pre_control_build_failure_restores_branch_head_and_prod_image(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
            original_oid, original_image = self._seed_stateful_original(
                harness, branch=True
            )
            helper = harness.work / "deploy/run_application_release.sh"
            original_helper = helper.read_bytes()
            harness.set_state("git-checkout-pre-v2-control", "1\n")
            harness.set_rc("build", 71)
            result = harness.run_script("deploy/rollback.sh", "build-fails")
            self.assertEqual(result.returncode, 71, result.stderr)
            self._assert_original_restored(
                harness, original_oid, original_image, branch=True
            )
            self.assertFalse(
                (harness.work / "runtime/migration_history_repair/restricted-recovery-control.json").exists()
            )
            self.assertEqual(helper.read_bytes(), original_helper)

    def test_pre_control_target_preflight_failure_restores_detached_head_and_prod_image(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
            original_oid, original_image = self._seed_stateful_original(
                harness, branch=False
            )
            harness.set_rc("compose-run", 72)
            result = harness.run_script("deploy/rollback_lowcost.sh", "preflight-fails")
            self.assertEqual(result.returncode, 72, result.stderr)
            self._assert_original_restored(
                harness, original_oid, original_image, branch=False
            )

    def test_malformed_target_sha_keeps_original_head_and_prod_image(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            original_oid, original_image = self._seed_stateful_original(
                harness, branch=True
            )
            harness.set_state("git-rev-parse-output", "not-an-oid\n")
            result = harness.run_script("deploy/rollback.sh", "bad-sha")
            self.assertNotEqual(result.returncode, 0)
            self._assert_original_restored(
                harness, original_oid, original_image, branch=True
            )

    def test_rollback_allowlist_requires_reviewed_migrations_through_0075(self):
        allowlist = json.loads(
            (
                ROOT / "deploy/reviewed_release_b_rollback_migrations.json"
            ).read_text(encoding="utf-8")
        )
        contracts = {
            item["migration_path"]: item["reviewed_variants"]
            for item in allowlist["required_migrations"]
        }
        self.assertEqual(
            set(contracts),
            {
                "server/stable/migrations/0071_historical_calendar_release_b.py",
                "server/stable/migrations/0072_add_extended_racing_regions.py",
                "server/stable/migrations/0073_lifecycle_enforce_registry.py",
                "server/stable/migrations/0074_race_data_sync_r0_control_plane.py",
                "server/stable/migrations/0075_race_data_source_priority_and_reported_position.py",
            },
        )
        self.assertEqual(
            {item["sha256"] for item in contracts[
                "server/stable/migrations/0071_historical_calendar_release_b.py"
            ]},
            {
                "74ee3ca9f03e60fca3735d2d90d3fdebcde40579387cb76e146720ef2ee23197",
                "e82f720970ae7f38a321b43fbfa5f8ff68a4637c4bd0e285754d9a12aa0b3260",
            },
        )
        self.assertEqual(
            {item["sha256"] for item in contracts[
                "server/stable/migrations/0072_add_extended_racing_regions.py"
            ]},
            {
                "f53cd64d7625fecc6f0cad9458e36d670c8e95cf6c2b23cd6ef7fab5123be67a",
            },
        )
        self.assertEqual(
            {item["sha256"] for item in contracts[
                "server/stable/migrations/0073_lifecycle_enforce_registry.py"
            ]},
            {
                "fa2b26f907ded36553f17cb75a0738ae09281adbe0e620d67aba8187d5ad9404",
            },
        )
        self.assertEqual(
            {item["sha256"] for item in contracts[
                "server/stable/migrations/0074_race_data_sync_r0_control_plane.py"
            ]},
            {
                "21670e7731456a33e473fd97cb43ca72545477aa600ea594c6c071c4dd2d54eb",
            },
        )
        self.assertEqual(
            {item["sha256"] for item in contracts[
                "server/stable/migrations/0075_race_data_source_priority_and_reported_position.py"
            ]},
            {
                "d8b220b241e560911bc5a02acada986926d93eb13a8aae0ace590a7f1e8bb0bd",
            },
        )
        self.assertTrue(
            all(
                item["rationale"].strip()
                for variants in contracts.values()
                for item in variants
            )
        )

    def test_legacy_reviewed_0071_with_exact_0072_remains_b_to_b_eligible(self):
        repaired = (
            ROOT / "server/stable/migrations/0071_historical_calendar_release_b.py"
        ).read_bytes()
        repaired_dependency = (
            b'        ("stable", "0069_race_data_sync_pipeline_a_ledger_guards"),\n'
        )
        self.assertEqual(repaired.count(repaired_dependency), 1)
        legacy = repaired.replace(repaired_dependency, b"", 1)
        for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            with self.subTest(script=script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness, race_live="running")
                harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
                (harness.state / "git-show-0071").write_bytes(legacy)
                result = harness.run_script(script, "legacy-0071-with-0072")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_0072_with_unreviewed_0071_fails_before_checkout_and_build(self):
        reviewed_0071 = (
            ROOT / "server/stable/migrations/0071_historical_calendar_release_b.py"
        ).read_text(encoding="utf-8")
        drifted_0071 = reviewed_0071.replace(
            'name="uq_race_event_series_edition"',
            'name="uq_race_event_series_edition_drift"',
            1,
        )
        self.assertNotEqual(reviewed_0071, drifted_0071)
        for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            with self.subTest(script=script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness, race_live="running")
                harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
                harness.set_state("git-show-0071", drifted_0071)
                result = harness.run_script(script, "drifted-0071-exact-0072")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("reviewed rollback allowlist", result.stderr)
                events = harness.events()
                self.assertFalse(any(
                    event[0] == "git" and event[2][:1] == ["checkout"]
                    for event in events
                ))
                self.assertFalse(any(
                    event[0] == "compose" and "build" in event[2]
                    for event in events
                ))

    def test_pre_0072_target_is_not_b_to_b_eligible(self):
        pre_0072 = (
            ROOT / "server/stable/migrations/0071_historical_calendar_release_b.py"
        ).read_bytes()
        for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            with self.subTest(script=script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness, race_live="running")
                harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
                (harness.state / "git-show-0072").write_bytes(pre_0072)
                result = harness.run_script(script, "pre-0072-release")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("reviewed rollback allowlist", result.stderr)

    def test_unreviewed_0072_content_or_dependencies_fail_before_checkout_and_build(self):
        reviewed = (
            ROOT / "server/stable/migrations/0072_add_extended_racing_regions.py"
        ).read_text(encoding="utf-8")
        cases = {
            "placeholder": "from django.db import migrations\nclass Migration(migrations.Migration):\n    dependencies = []\n    operations = []\n",
            "dependency": reviewed.replace(
                "'0071_historical_calendar_release_b'",
                "'0070_horse_identity_evidence_commit_receipt'",
                1,
            ),
            "operation": reviewed.replace(
                "model_name='externaldataimporterror'",
                "model_name='externaldataimporterror_drift'",
                1,
            ),
        }
        for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            for label, source in cases.items():
                with self.subTest(script=script, drift=label), TemporaryDirectory() as tmp:
                    harness = Harness(Path(tmp))
                    seed_services(harness, race_live="running")
                    harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
                    harness.set_state("git-show-0072", source)
                    result = harness.run_script(script, "unreviewed-release-b")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("reviewed rollback allowlist", result.stderr)
                    events = harness.events()
                    self.assertFalse(
                        any(
                            event[0] == "git" and event[2][:1] == ["checkout"]
                            for event in events
                        )
                    )
                    self.assertFalse(
                        any(
                            event[0] == "compose" and "build" in event[2]
                            for event in events
                        )
                    )

    def test_0075_rollback_target_does_not_need_later_v2_marker_file(self):
        verifier_call = (
            "python3 ./deploy/verify_rollback_target_migration.py "
            '--target-oid "$TARGET_OID"'
        )
        for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            text = (ROOT / script).read_text(encoding="utf-8")
            self.assertNotIn("deploy/release_contract_v2", text)
            self.assertIn(verifier_call, text)
            self.assertLess(
                text.index(verifier_call),
                text.index('git checkout "$TARGET_OID"'),
                "target migration verifier must run before checkout",
            )
            self.assertNotIn(
                "server/stable/migrations/0072_add_extended_racing_regions.py",
                text,
                "the shell must delegate target migration details to the verifier",
            )
            self.assertIn(
                "RELEASE_B_EXPECTED_MIGRATION_LEAF_SET="
                "stable.0075_race_data_source_priority_and_reported_position",
                text,
            )

        resume = (
            ROOT / "deploy/resume_rollback_control_state.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "EXPECTED_LEAF=stable.0075_race_data_source_priority_and_reported_position",
            resume,
        )

        verifier = (
            ROOT / "deploy/verify_rollback_target_migration.py"
        ).read_text(encoding="utf-8")
        allowlist = json.loads(
            (
                ROOT / "deploy/reviewed_release_b_rollback_migrations.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn('["git", "show", f"{target_oid}:{path}"]', verifier)
        self.assertIn('item.get("sha256") == digest', verifier)
        self.assertIn('item.get("dependencies") == dependencies', verifier)
        self.assertEqual(
            {
                item["migration_path"]
                for item in allowlist["required_migrations"]
            },
            {
                "server/stable/migrations/0071_historical_calendar_release_b.py",
                "server/stable/migrations/0072_add_extended_racing_regions.py",
                "server/stable/migrations/0073_lifecycle_enforce_registry.py",
                "server/stable/migrations/0074_race_data_sync_r0_control_plane.py",
                "server/stable/migrations/0075_race_data_source_priority_and_reported_position.py",
            },
        )

        for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            with self.subTest(script=script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness, race_live="running")
                harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
                harness.set_state(
                    "git-cat-file-missing", "deploy/release_contract_v2\n"
                )
                result = harness.run_script(script, "release-b-parent")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_pre_v2_target_uses_preserved_v2_control_plane_for_artifact_and_release(self):
        for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            with self.subTest(script=script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness, race_live="running")
                harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
                harness.set_state("git-checkout-pre-v2-control", "1\n")
                result = harness.run_script(script, "release-b-pre-v2")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("target-v1-", result.stderr)
                artifacts = list(
                    (harness.work / "runtime" / "migration_history_repair").glob(
                        "preflight/before.*/preflight.json"
                    )
                )
                self.assertEqual(len(artifacts), 1)
                self.assertGreater(artifacts[0].stat().st_size, 0)
                docker_tags = [
                    e[2]
                    for e in harness.events()
                    if e[0] == "docker" and e[2][:1] == ["tag"]
                ]
                self.assertTrue(
                    any("rollback-control-" in " ".join(argv) for argv in docker_tags)
                )
                self.assertTrue(
                    any("rollback-target-" in " ".join(argv) for argv in docker_tags)
                )
                self.assertFalse(
                    any(
                        argv[-1:] == ["umanewsbot:prod"]
                        and "rollback-control-" in " ".join(argv)
                        for argv in docker_tags
                    ),
                    "the immutable control image must never replace the production tag",
                )

    def test_markerless_pre_v2_failure_has_only_pinned_control_retry(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
            harness.set_state("git-checkout-pre-v2-control", "1\n")
            harness.set_rc("compose-release-task", 73)

            failed = harness.run_script("deploy/rollback.sh", "release-b-pre-v2")
            self.assertEqual(failed.returncode, 73, failed.stderr)
            self.assertNotIn("target-v1-", failed.stderr)
            runtime = harness.work / "runtime" / "migration_history_repair"
            active_state = runtime / "restricted-recovery-control.json"
            self.assertTrue(active_state.is_file())
            state = json.loads(active_state.read_text(encoding="utf-8"))
            self.assertEqual(state["target_commit"], self.FIXED_OID)
            self.assertEqual(state["target_image_id"], "sha256:candidate-image-id")
            self.assertEqual(state["recovery_intent_mode"], "not-required")
            self.assertEqual(state["initiating_artifact_sha256"], "a" * 64)
            self.assertEqual(len(state["initiating_lock_token_sha256"]), 64)
            self.assertEqual(
                state["initiating_database_identity_sha256"], "d" * 64
            )
            self.assertTrue(Path(state["control_override"]).is_file())
            retry_script = Path(state["control_dir"]) / "resume-rollback-release.sh"
            self.assertTrue(retry_script.is_file())
            self.assertIn(
                f"EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256={state['initiating_artifact_sha256']}",
                failed.stderr,
            )
            self.assertIn(
                f"EXPECTED_ROLLBACK_CONTROL_STATE_SHA256={state['state_sha256']}",
                failed.stderr,
            )

            docker_tags = [
                e[2]
                for e in harness.events()
                if e[0] == "docker" and e[2][:1] == ["tag"]
            ]
            self.assertFalse(
                any(
                    argv[-1:] == ["umanewsbot:prod"]
                    and "rollback-control-" in " ".join(argv)
                    for argv in docker_tags
                ),
                "a failed one-shot must leave prod on the target/original image, never control",
            )

            harness.clear_log()
            ordinary_resume = harness.run_script(
                RESUME_SCRIPT_REL, COMPOSE_FILE=COMPOSE_STANDARD
            )
            self.assertNotEqual(ordinary_resume.returncode, 0)
            self.assertEqual(
                [
                    argv
                    for _compose_file, argv in compose_calls(harness.events())
                    if argv[:1] == ["up"]
                ],
                [],
                "ordinary stopped-service recovery must not bypass active control state",
            )

            retry_rel = str(
                Path(os.path.realpath(retry_script)).relative_to(
                    Path(os.path.realpath(harness.work))
                )
            )
            harness.clear_log()
            wrong_target = harness.run_script(
                retry_rel,
                COMPOSE_FILE=COMPOSE_STANDARD,
                EXPECTED_ROLLBACK_TARGET_COMMIT="f" * 40,
                EXPECTED_ROLLBACK_TARGET_IMAGE_ID="sha256:candidate-image-id",
                EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256=state["initiating_artifact_sha256"],
                EXPECTED_ROLLBACK_CONTROL_STATE_SHA256=state["state_sha256"],
            )
            self.assertNotEqual(wrong_target.returncode, 0)
            self.assertTrue(active_state.is_file())
            self.assertEqual(
                [
                    argv
                    for _compose_file, argv in compose_calls(harness.events())
                    if argv[:1] in (["stop"], ["up"], ["run"])
                ],
                [],
            )

            harness.clear_log()
            retry_failed = harness.run_script(
                retry_rel,
                COMPOSE_FILE=COMPOSE_STANDARD,
                EXPECTED_ROLLBACK_TARGET_COMMIT=self.FIXED_OID,
                EXPECTED_ROLLBACK_TARGET_IMAGE_ID="sha256:candidate-image-id",
                EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256=state["initiating_artifact_sha256"],
                EXPECTED_ROLLBACK_CONTROL_STATE_SHA256=state["state_sha256"],
            )
            self.assertEqual(retry_failed.returncode, 73, retry_failed.stderr)
            self.assertTrue(
                active_state.is_file(),
                "a failed dedicated retry must retain the exact control state",
            )
            self.assertEqual(
                [
                    argv
                    for _compose_file, argv in compose_calls(harness.events())
                    if argv[:1] == ["up"]
                ],
                [],
            )

            (harness.state / "rc-compose-release-task").unlink()
            harness.clear_log()
            resumed = harness.run_script(
                retry_rel,
                COMPOSE_FILE=COMPOSE_STANDARD,
                EXPECTED_ROLLBACK_TARGET_COMMIT=self.FIXED_OID,
                EXPECTED_ROLLBACK_TARGET_IMAGE_ID="sha256:candidate-image-id",
                EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256=state["initiating_artifact_sha256"],
                EXPECTED_ROLLBACK_CONTROL_STATE_SHA256=state["state_sha256"],
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertNotIn("target-v1-", resumed.stderr)
            self.assertFalse(active_state.exists())
            self.assertTrue(
                (
                    runtime
                    / f"restricted-recovery-control.completed.{self.FIXED_OID}.{state['initiating_artifact_sha256']}.{state['state_sha256']}.json"
                ).is_file()
            )
            resumed_log = "\n".join(harness.log_lines())
            self.assertIn(state["control_override"], resumed_log)
            self.assertIn(state["target_image_tag"], resumed_log)

    def test_target_collectstatic_failure_is_retryable_for_both_markerless_rollbacks(self):
        for rollback_script, compose_file in (
            ("deploy/rollback.sh", COMPOSE_STANDARD),
            ("deploy/rollback_lowcost.sh", COMPOSE_LOWCOST),
        ):
            with self.subTest(rollback=rollback_script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness, race_live="running")
                harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
                harness.set_rc("compose-target-collectstatic", 74)
                failed = harness.run_script(rollback_script, "release-b-target-static")
                self.assertEqual(failed.returncode, 74, failed.stderr)
                runtime = harness.work / "runtime/migration_history_repair"
                active_state = runtime / "restricted-recovery-control.json"
                self.assertTrue(active_state.is_file())
                payload = json.loads(active_state.read_text(encoding="utf-8"))
                failed_runs = [
                    argv
                    for _compose_file, argv in compose_calls(harness.events())
                    if argv[:1] == ["run"]
                ]
                self.assertTrue(
                    any(
                        argv[-5:]
                        == [
                            "web",
                            "python",
                            "manage.py",
                            "collectstatic",
                            "--noinput",
                        ]
                        for argv in failed_runs
                    )
                )
                self.assertFalse(
                    any("RELEASE_TASK_PHASE=complete-intent" in argv for argv in failed_runs)
                )
                self.assertEqual(
                    [
                        argv
                        for _compose_file, argv in compose_calls(harness.events())
                        if argv[:1] == ["up"]
                    ],
                    [],
                )

                retry_script = Path(payload["control_dir"]) / "resume-rollback-release.sh"
                retry_rel = str(
                    Path(os.path.realpath(retry_script)).relative_to(
                        Path(os.path.realpath(harness.work))
                    )
                )
                (harness.state / "rc-compose-target-collectstatic").unlink()
                harness.clear_log()
                resumed = harness.run_script(
                    retry_rel,
                    COMPOSE_FILE=compose_file,
                    EXPECTED_ROLLBACK_TARGET_COMMIT=self.FIXED_OID,
                    EXPECTED_ROLLBACK_TARGET_IMAGE_ID="sha256:candidate-image-id",
                    EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256=payload[
                        "initiating_artifact_sha256"
                    ],
                    EXPECTED_ROLLBACK_CONTROL_STATE_SHA256=payload["state_sha256"],
                )
                self.assertEqual(resumed.returncode, 0, resumed.stderr)
                resumed_runs = [
                    argv
                    for _compose_file, argv in compose_calls(harness.events())
                    if argv[:1] == ["run"]
                ]
                self.assertEqual(
                    sum(
                        argv[-5:]
                        == [
                            "web",
                            "python",
                            "manage.py",
                            "collectstatic",
                            "--noinput",
                        ]
                        for argv in resumed_runs
                    ),
                    1,
                )
                self.assertTrue(
                    any("RELEASE_TASK_PHASE=complete-intent" in argv for argv in resumed_runs)
                )
                self.assertFalse(active_state.exists())

    def test_required_rollback_forward_resume_retries_target_collectstatic(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
            harness.set_state("preflight-attempt-mode", "required\n")
            harness.set_rc("compose-target-collectstatic", 75)
            failed = harness.run_script("deploy/rollback.sh", "release-b-required")
            self.assertEqual(failed.returncode, 75, failed.stderr)
            active_state = (
                harness.work
                / "runtime/migration_history_repair/restricted-recovery-control.json"
            )
            self.assertTrue(active_state.is_file())

            resume_env = {
                "COMPOSE_FILE": COMPOSE_STANDARD,
                "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256": "a" * 64,
                "EXPECTED_CANDIDATE_COMMIT": self.FIXED_OID,
                "EXPECTED_CANDIDATE_IMAGE_ID": "sha256:candidate-image-id",
            }
            harness.clear_log()
            failed_again = harness.run_script(
                "deploy/resume_migration_history_repair.sh", **resume_env
            )
            self.assertEqual(failed_again.returncode, 75, failed_again.stderr)
            self.assertTrue(active_state.is_file())
            self.assertEqual(
                [
                    argv
                    for _compose_file, argv in compose_calls(harness.events())
                    if argv[:1] == ["up"]
                ],
                [],
            )

            (harness.state / "rc-compose-target-collectstatic").unlink()
            harness.clear_log()
            resumed = harness.run_script(
                "deploy/resume_migration_history_repair.sh", **resume_env
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            runs = [
                argv
                for _compose_file, argv in compose_calls(harness.events())
                if argv[:1] == ["run"]
            ]
            self.assertEqual(
                sum(
                    argv[-5:]
                    == ["web", "python", "manage.py", "collectstatic", "--noinput"]
                    for argv in runs
                ),
                1,
            )
            self.assertTrue(
                any("RELEASE_TASK_PHASE=complete-intent" in argv for argv in runs)
            )
            self.assertFalse(active_state.exists())

    def test_generic_resume_verifies_control_state_and_files_before_any_execution(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
            harness.set_rc("compose-release-task", 73)
            failed = harness.run_script("deploy/rollback.sh", "resume-verifier")
            self.assertEqual(failed.returncode, 73, failed.stderr)
            active_state = (
                harness.work
                / "runtime/migration_history_repair/restricted-recovery-control.json"
            )
            state_bytes = active_state.read_bytes()
            state = json.loads(state_bytes)
            resume_env = {
                "COMPOSE_FILE": COMPOSE_STANDARD,
                "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256": state[
                    "initiating_artifact_sha256"
                ],
                "EXPECTED_CANDIDATE_COMMIT": self.FIXED_OID,
                "EXPECTED_CANDIDATE_IMAGE_ID": "sha256:candidate-image-id",
            }

            drifted = dict(state)
            drifted["target_image_tag"] += "-tampered"
            active_state.chmod(0o700)
            active_state.write_text(
                json.dumps(drifted, sort_keys=True, separators=(",", ":")) + "\n"
            )
            active_state.chmod(0o600)
            harness.clear_log()
            rejected_state = harness.run_script(RESUME_SCRIPT_REL, **resume_env)
            self.assertNotEqual(rejected_state.returncode, 0)
            self.assertEqual(harness.events(), [])
            active_state.chmod(0o700)
            active_state.write_bytes(state_bytes)
            active_state.chmod(0o600)

            verifier = Path(state["control_files"]["control_state_verifier"]["path"])
            verifier_bytes = verifier.read_bytes()
            verifier.chmod(0o700)
            verifier.write_bytes(verifier_bytes + b"\n# tampered\n")
            verifier.chmod(0o500)
            harness.clear_log()
            rejected_file = harness.run_script(RESUME_SCRIPT_REL, **resume_env)
            self.assertNotEqual(rejected_file.returncode, 0)
            self.assertEqual(harness.events(), [])
            verifier.chmod(0o700)
            verifier.write_bytes(verifier_bytes)
            verifier.chmod(0o500)

            preflight = Path(state["control_files"]["preflight"]["path"])
            saved = preflight.with_name("preflight.saved")
            preflight.rename(saved)
            preflight.symlink_to(saved.name)
            harness.clear_log()
            rejected_symlink = harness.run_script(RESUME_SCRIPT_REL, **resume_env)
            self.assertNotEqual(rejected_symlink.returncode, 0)
            self.assertEqual(harness.events(), [])
            preflight.unlink()
            saved.rename(preflight)

    def test_reverse_handoff_direction_is_rejected_before_compose(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            locked = acquire_lock(harness, LOCK_TOKEN_A, action="rollback")
            self.assertEqual(locked.returncode, 0, locked.stderr)
            artifact_dir = (
                harness.work
                / "runtime"
                / "migration_history_repair"
                / "preflight"
                / "reverse.test"
            )
            artifact_dir.mkdir(parents=True, mode=0o700)
            artifact_dir.chmod(0o700)
            harness.clear_log()
            result = harness.run_script(
                "deploy/run_historical_calendar_release_b_preflight.sh",
                COMPOSE_FILE=COMPOSE_STANDARD,
                DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
                EXPECTED_CANDIDATE_COMMIT=self.FIXED_OID,
                RELEASE_B_PREFLIGHT_ARTIFACT_PATH=str(
                    artifact_dir / "preflight.json"
                ),
                RELEASE_B_PREFLIGHT_ACTION="rollback",
                SCHEMA_PREFLIGHT_DIRECTION="reverse",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reverse schema preflight is unsupported", result.stderr)
            self.assertEqual(
                [
                    argv
                    for _compose_file, argv in compose_calls(harness.events())
                    if argv[:1] == ["run"]
                ],
                [],
            )

    def test_every_pinned_control_file_rejects_same_mode_tamper_for_both_rollbacks(self):
        cases = (
            ("deploy/rollback.sh", COMPOSE_STANDARD),
            ("deploy/rollback_lowcost.sh", COMPOSE_LOWCOST),
        )
        for rollback_script, compose_file in cases:
            with self.subTest(rollback=rollback_script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness, race_live="running")
                harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
                harness.set_state("git-checkout-pre-v2-control", "1\n")
                harness.set_rc("compose-release-task", 73)
                failed = harness.run_script(rollback_script, "release-b-pre-v2")
                self.assertEqual(failed.returncode, 73, failed.stderr)

                runtime = harness.work / "runtime" / "migration_history_repair"
                active_state = runtime / "restricted-recovery-control.json"
                state = json.loads(active_state.read_text(encoding="utf-8"))
                self.assertEqual(
                    set(state["control_files"]),
                    {
                        "application_release",
                        "control_state_creator",
                        "control_state_verifier",
                        "preflight",
                        "release_tasks",
                        "resume_rollback",
                        "compose_override",
                    },
                )
                self.assertEqual(len(state["state_sha256"]), 64)
                retry_script = Path(state["control_dir"]) / "resume-rollback-release.sh"
                retry_rel = str(
                    Path(os.path.realpath(retry_script)).relative_to(
                        Path(os.path.realpath(harness.work))
                    )
                )
                original_state = active_state.read_bytes()
                drifted_state = json.loads(original_state)
                drifted_state["target_image_tag"] += "-same-mode-tamper"
                active_state.chmod(0o700)
                active_state.write_text(
                    json.dumps(
                        drifted_state,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n",
                    encoding="utf-8",
                )
                active_state.chmod(0o600)
                harness.clear_log()
                state_rejected = harness.run_script(
                    retry_rel,
                    COMPOSE_FILE=compose_file,
                    EXPECTED_ROLLBACK_TARGET_COMMIT=self.FIXED_OID,
                    EXPECTED_ROLLBACK_TARGET_IMAGE_ID="sha256:candidate-image-id",
                    EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256=state["initiating_artifact_sha256"],
                    EXPECTED_ROLLBACK_CONTROL_STATE_SHA256=state["state_sha256"],
                )
                self.assertNotEqual(state_rejected.returncode, 0)
                self.assertEqual(harness.events(), [])
                active_state.chmod(0o700)
                active_state.write_bytes(original_state)
                active_state.chmod(0o600)

                for name, binding in state["control_files"].items():
                    with self.subTest(rollback=rollback_script, control_file=name):
                        path = Path(binding["path"])
                        original = path.read_bytes()
                        original_mode = stat.S_IMODE(path.stat().st_mode)
                        path.chmod(original_mode | stat.S_IWUSR)
                        path.write_bytes(original + b"\n# same-mode tamper\n")
                        path.chmod(original_mode)
                        harness.clear_log()
                        rejected = harness.run_script(
                            retry_rel,
                            COMPOSE_FILE=compose_file,
                            EXPECTED_ROLLBACK_TARGET_COMMIT=self.FIXED_OID,
                            EXPECTED_ROLLBACK_TARGET_IMAGE_ID="sha256:candidate-image-id",
                            EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256=state["initiating_artifact_sha256"],
                            EXPECTED_ROLLBACK_CONTROL_STATE_SHA256=state["state_sha256"],
                        )
                        self.assertNotEqual(rejected.returncode, 0)
                        self.assertTrue(active_state.is_file())
                        self.assertEqual(
                            [
                                event
                                for event in harness.events()
                                if event[0] in ("docker", "compose", "git")
                            ],
                            [],
                            "content drift must fail before Docker, Compose, or Git",
                        )
                        path.chmod(original_mode | stat.S_IWUSR)
                        path.write_bytes(original)
                        path.chmod(original_mode)

                preflight = Path(state["control_files"]["preflight"]["path"])
                saved_preflight = preflight.with_name("preflight.saved")
                preflight.rename(saved_preflight)
                preflight.symlink_to(saved_preflight.name)
                harness.clear_log()
                replaced = harness.run_script(
                    retry_rel,
                    COMPOSE_FILE=compose_file,
                    EXPECTED_ROLLBACK_TARGET_COMMIT=self.FIXED_OID,
                    EXPECTED_ROLLBACK_TARGET_IMAGE_ID="sha256:candidate-image-id",
                    EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256=state["initiating_artifact_sha256"],
                    EXPECTED_ROLLBACK_CONTROL_STATE_SHA256=state["state_sha256"],
                )
                self.assertNotEqual(replaced.returncode, 0)
                self.assertEqual(harness.events(), [])
                preflight.unlink()
                saved_preflight.rename(preflight)

                (harness.state / "rc-compose-release-task").unlink()
                harness.clear_log()
                resumed = harness.run_script(
                    retry_rel,
                    COMPOSE_FILE=compose_file,
                    EXPECTED_ROLLBACK_TARGET_COMMIT=self.FIXED_OID,
                    EXPECTED_ROLLBACK_TARGET_IMAGE_ID="sha256:candidate-image-id",
                    EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256=state["initiating_artifact_sha256"],
                    EXPECTED_ROLLBACK_CONTROL_STATE_SHA256=state["state_sha256"],
                )
                self.assertEqual(resumed.returncode, 0, resumed.stderr)
                self.assertFalse(active_state.exists())

    def test_two_successful_rollbacks_to_same_target_get_distinct_idempotent_receipts(self):
        for rollback_script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            with self.subTest(rollback=rollback_script), TemporaryDirectory() as tmp:
                harness = Harness(Path(tmp))
                seed_services(harness, race_live="running")
                harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
                runtime = harness.work / "runtime" / "migration_history_repair"

                first = harness.run_script(rollback_script, "same-target")
                self.assertEqual(first.returncode, 0, first.stderr)
                receipts = sorted(
                    runtime.glob(
                        f"restricted-recovery-control.completed.{self.FIXED_OID}.*.json"
                    )
                )
                self.assertEqual(len(receipts), 1)

                second = harness.run_script(rollback_script, "same-target")
                self.assertEqual(second.returncode, 0, second.stderr)
                receipts = sorted(
                    runtime.glob(
                        f"restricted-recovery-control.completed.{self.FIXED_OID}.*.json"
                    )
                )
                self.assertEqual(len(receipts), 2)
                self.assertNotEqual(receipts[0].name, receipts[1].name)

                for receipt in receipts:
                    payload = json.loads(receipt.read_text(encoding="utf-8"))
                    unsigned = {
                        key: value
                        for key, value in payload.items()
                        if key != "state_sha256"
                    }
                    actual_sha = hashlib.sha256(
                        json.dumps(
                            unsigned,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                    self.assertEqual(payload["state_sha256"], actual_sha)
                    self.assertTrue(receipt.name.endswith(f".{actual_sha}.json"))
                    self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)

                    before = (
                        receipt.stat().st_ino,
                        receipt.read_bytes(),
                    )
                    creator = Path(payload["control_dir"]) / "create-control-state.py"
                    replay = subprocess.run(
                        [
                            os.environ.get("PYTHON", "python3"),
                            str(creator),
                            "complete",
                            "--state-path",
                            str(runtime / "restricted-recovery-control.json"),
                            "--completed-path",
                            str(receipt),
                            "--expected-state-sha256",
                            actual_sha,
                        ],
                        cwd=harness.work,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(replay.returncode, 0, replay.stderr)
                    self.assertIn("already-completed", replay.stdout)
                    self.assertEqual(
                        (receipt.stat().st_ino, receipt.read_bytes()), before
                    )

    def test_retry_closes_same_inode_active_completed_crash_without_release_replay(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
            harness.set_rc("compose-release-task", 73)
            failed = harness.run_script("deploy/rollback.sh", "same-attempt-crash")
            self.assertEqual(failed.returncode, 73, failed.stderr)
            runtime = harness.work / "runtime" / "migration_history_repair"
            active = runtime / "restricted-recovery-control.json"
            payload = json.loads(active.read_text(encoding="utf-8"))
            completed = runtime / (
                "restricted-recovery-control.completed."
                f"{self.FIXED_OID}.{payload['initiating_artifact_sha256']}."
                f"{payload['state_sha256']}.json"
            )
            os.link(active, completed)
            before = (completed.stat().st_ino, completed.read_bytes())
            retry_script = Path(payload["control_dir"]) / "resume-rollback-release.sh"
            retry_rel = str(
                Path(os.path.realpath(retry_script)).relative_to(
                    Path(os.path.realpath(harness.work))
                )
            )
            harness.clear_log()
            resumed = harness.run_script(
                retry_rel,
                COMPOSE_FILE=COMPOSE_STANDARD,
                EXPECTED_ROLLBACK_TARGET_COMMIT=self.FIXED_OID,
                EXPECTED_ROLLBACK_TARGET_IMAGE_ID="sha256:candidate-image-id",
                EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256=payload["initiating_artifact_sha256"],
                EXPECTED_ROLLBACK_CONTROL_STATE_SHA256=payload["state_sha256"],
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertFalse(active.exists())
            self.assertEqual(
                (completed.stat().st_ino, completed.read_bytes()), before
            )
            self.assertEqual(
                [
                    event
                    for event in harness.events()
                    if event[0] in ("git", "docker", "compose")
                ],
                [],
                "completion crash replay must not rerun release or inspect images",
            )

    def test_retry_completed_only_crash_is_exact_and_skips_release_replay(self):
        with TemporaryDirectory() as tmp:
            harness = Harness(Path(tmp))
            seed_services(harness, race_live="running")
            harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
            runtime = harness.work / "runtime" / "migration_history_repair"

            first = harness.run_script("deploy/rollback.sh", "same-target")
            self.assertEqual(first.returncode, 0, first.stderr)
            first_receipt = next(
                runtime.glob(
                    f"restricted-recovery-control.completed.{self.FIXED_OID}.*.json"
                )
            )
            payload = json.loads(first_receipt.read_text(encoding="utf-8"))
            second = harness.run_script("deploy/rollback.sh", "same-target")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                len(
                    list(
                        runtime.glob(
                            f"restricted-recovery-control.completed.{self.FIXED_OID}.*.json"
                        )
                    )
                ),
                2,
                "an unrelated older/newer receipt must coexist without fuzzy matching",
            )

            retry_script = Path(payload["control_dir"]) / "resume-rollback-release.sh"
            retry_rel = str(
                Path(os.path.realpath(retry_script)).relative_to(
                    Path(os.path.realpath(harness.work))
                )
            )
            harness.clear_log()
            replay = harness.run_script(
                retry_rel,
                COMPOSE_FILE=COMPOSE_STANDARD,
                EXPECTED_ROLLBACK_TARGET_COMMIT=self.FIXED_OID,
                EXPECTED_ROLLBACK_TARGET_IMAGE_ID="sha256:candidate-image-id",
                EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256=payload[
                    "initiating_artifact_sha256"
                ],
                EXPECTED_ROLLBACK_CONTROL_STATE_SHA256=payload["state_sha256"],
            )
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertIn("already completed", replay.stdout)
            self.assertEqual(
                [
                    event
                    for event in harness.events()
                    if event[0] in ("git", "docker", "compose")
                ],
                [],
                "completed-only crash replay must return before Git, Docker, or Compose",
            )

    def test_p2_rollback_rejects_target_missing_any_v1_helper(self):
        for missing in (
            "deploy/deployment_lock.sh",
            "deploy/run_application_release.sh",
            "deploy/docker/compose-wrapper.sh",
        ):
            with self.subTest(missing=missing):
                with TemporaryDirectory() as tmp:
                    harness = Harness(Path(tmp))
                    seed_services(harness, race_live="running")
                    # Valid OID so the refusal is caused by the missing helper,
                    # not by OID format validation.
                    harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
                    harness.set_state("git-cat-file-missing", f"{missing}\n")
                    result = harness.run_script("deploy/rollback.sh", "oldref123")
                    self.assertNotEqual(result.returncode, 0)
                    evts = harness.events()
                    self.assertEqual(
                        [e for e in evts if e[0] == "git" and e[2][:1] == ["checkout"]],
                        [],
                        f"rollback must refuse before checkout when {missing} is missing",
                    )
                    self.assertEqual(
                        [
                            a
                            for _cf, a in compose_calls(evts)
                            if a[:1] in (["stop"], ["up"], ["run"])
                        ],
                        [],
                        "missing v1 helper must be rejected with zero stop and zero release",
                    )

    def test_p2_rollback_binds_immutable_oid_for_cat_file_and_checkout(self):
        for script in ("deploy/rollback.sh", "deploy/rollback_lowcost.sh"):
            with self.subTest(script=script):
                with TemporaryDirectory() as tmp:
                    harness = Harness(Path(tmp))
                    seed_services(harness, race_live="running")
                    harness.set_state("git-rev-parse-output", f"{self.FIXED_OID}\n")
                    result = harness.run_script(script, "release-notes-branch")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    evts = harness.events()
                    cat_files = [
                        e[2] for e in evts if e[0] == "git" and e[2][:1] == ["cat-file"]
                    ]
                    self.assertTrue(
                        cat_files, "rollback must validate v1 helpers via git cat-file"
                    )
                    for argv in cat_files:
                        joined = " ".join(argv)
                        self.assertIn(
                            f"{self.FIXED_OID}:",
                            joined,
                            f"cat-file must use the resolved immutable OID: {argv}",
                        )
                        self.assertNotIn("release-notes-branch", joined)
                    checked_paths = {
                        argv[-1].split(":", 1)[1] for argv in cat_files if ":" in argv[-1]
                    }
                    for helper in self.V1_HELPERS:
                        self.assertIn(
                            helper,
                            checked_paths,
                            f"rollback must cat-file -e the v1 helper {helper}",
                        )
                    shows = [
                        e[2] for e in evts if e[0] == "git" and e[2][:1] == ["show"]
                    ]
                    self.assertEqual(
                        shows,
                        [
                            [
                                "show",
                                f"{self.FIXED_OID}:server/stable/migrations/"
                                "0071_historical_calendar_release_b.py",
                            ],
                            [
                                "show",
                                f"{self.FIXED_OID}:server/stable/migrations/"
                                "0072_add_extended_racing_regions.py",
                            ],
                            [
                                "show",
                                f"{self.FIXED_OID}:server/stable/migrations/"
                                "0073_lifecycle_enforce_registry.py",
                            ],
                            [
                                "show",
                                f"{self.FIXED_OID}:server/stable/migrations/"
                                "0074_race_data_sync_r0_control_plane.py",
                            ],
                            [
                                "show",
                                f"{self.FIXED_OID}:server/stable/migrations/"
                                "0075_race_data_source_priority_and_reported_position.py",
                            ],
                        ],
                    )
                    checkouts = [
                        e[2] for e in evts if e[0] == "git" and e[2][:1] == ["checkout"]
                    ]
                    self.assertEqual(checkouts, [["checkout", self.FIXED_OID]])

    def test_p2_rollback_rejects_malformed_resolved_oid(self):
        bad_outputs = (
            ("empty", ""),
            ("two-lines", f"{self.FIXED_OID}\nabcdef0123456789abcdef0123456789abcdef01\n"),
            ("non-hex", "zzzz\n"),
            ("hex-with-trailing-junk-line", f"{self.FIXED_OID}\njunk\n"),
        )
        for label, output in bad_outputs:
            with self.subTest(case=label):
                with TemporaryDirectory() as tmp:
                    harness = Harness(Path(tmp))
                    seed_services(harness, race_live="running")
                    harness.set_state("git-rev-parse-output", output)
                    result = harness.run_script("deploy/rollback.sh", "release-notes-branch")
                    self.assertNotEqual(
                        result.returncode,
                        0,
                        "rollback must reject a malformed resolved OID explicitly",
                    )
                    cat_files = [
                        e[2]
                        for e in harness.events()
                        if e[0] == "git" and e[2][:1] == ["cat-file"]
                    ]
                    self.assertEqual(
                        cat_files,
                        [],
                        "OID format validation must happen before any git cat-file",
                    )


class InspectProbeValidityTests(SimpleTestCase):
    """P2-5: empty or unknown inspect output must fail closed everywhere."""

    INVALID_OUTPUTS = ("", "unknown garbage")

    def test_p2_orchestration_rejects_invalid_race_live_probe_output(self):
        for bad in self.INVALID_OUTPUTS:
            with self.subTest(inspect_output=bad or "<empty>"):
                with TemporaryDirectory() as tmp:
                    harness = Harness(Path(tmp))
                    seed_services(harness, race_live="running")
                    locked = acquire_lock(harness, LOCK_TOKEN_A)
                    self.assertEqual(locked.returncode, 0, locked.stderr)
                    harness.set_state(
                        f"inspect-{SERVICE_IDS['race_live_worker']}", f"{bad}\n"
                    )
                    harness.clear_log()
                    result = harness.run_script(
                        ORCHESTRATION_REL,
                        COMPOSE_FILE=COMPOSE_STANDARD,
                        DEPLOYMENT_LOCK_TOKEN=LOCK_TOKEN_A,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    stops = [
                        a
                        for _cf, a in compose_calls(harness.events())
                        if a[:1] == ["stop"]
                    ]
                    self.assertEqual(
                        stops,
                        [],
                        "invalid inspect output must fail closed before any stop",
                    )

    def test_p2_manual_release_rejects_invalid_inspect_output(self):
        for bad in self.INVALID_OUTPUTS:
            with self.subTest(inspect_output=bad or "<empty>"):
                with TemporaryDirectory() as tmp:
                    harness = Harness(Path(tmp))
                    harness.set_state("ps-worker", f"{SERVICE_IDS['worker']}\n")
                    harness.set_state(f"inspect-{SERVICE_IDS['worker']}", f"{bad}\n")
                    harness.set_state("ps-db", f"{SERVICE_IDS['db']}\n")
                    harness.set_state(f"inspect-{SERVICE_IDS['db']}", "true healthy\n")
                    harness.set_state("ps-redis", f"{SERVICE_IDS['redis']}\n")
                    harness.set_state(
                        f"inspect-{SERVICE_IDS['redis']}", "true healthy\n"
                    )
                    result = harness.run_script(
                        MANUAL_RELEASE_REL, COMPOSE_FILE=COMPOSE_STANDARD
                    )
                    self.assertNotEqual(result.returncode, 0)
                    runs = [
                        a
                        for _cf, a in compose_calls(harness.events())
                        if a[:1] == ["run"]
                    ]
                    self.assertEqual(
                        runs,
                        [],
                        "invalid inspect output must fail closed with zero compose run",
                    )

    def test_p3_bridge_rejects_invalid_race_live_probe_output(self):
        for bad in self.INVALID_OUTPUTS:
            with self.subTest(inspect_output=bad or "<empty>"):
                with TemporaryDirectory() as tmp:
                    harness = Harness(Path(tmp))
                    seed_services(harness, race_live="running")
                    harness.set_state(
                        f"inspect-{SERVICE_IDS['race_live_worker']}", f"{bad}\n"
                    )
                    harness.clear_log()
                    result = harness.run_script(
                        PRE_CONTRACT_BRIDGE_REL,
                        "umanewsbot:prod-frozen-20260701",
                        COMPOSE_FILE=COMPOSE_STANDARD,
                        SCHEMA_COMPATIBLE_WITH_TARGET="true",
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(
                        [
                            e
                            for e in harness.events()
                            if e[0] == "docker" and e[2][:1] == ["tag"]
                        ],
                        [],
                        "invalid inspect output must stop the bridge before docker tag",
                    )


class DocumentationSyncTests(SimpleTestCase):
    """P3-6/P3-7: docs must match the implemented lock order and status."""

    def test_p3_deploy_production_doc_acquires_lock_before_preflight(self):
        text = (ROOT / "docs" / "deploy_production.md").read_text(encoding="utf-8")
        sequence_lines = [
            line
            for line in text.splitlines()
            if "preflight" in line and "部署锁" in line
        ]
        self.assertTrue(
            sequence_lines,
            "deploy doc must describe the lock/preflight ordering",
        )
        for line in sequence_lines:
            self.assertLess(
                line.index("部署锁"),
                line.index("preflight"),
                "deploy doc must acquire the deployment lock before historical "
                f"preflight: {line}",
            )

    def test_p3_spec_and_tasks_no_longer_claim_implementation_unstarted(self):
        change_dir = ROOT / "docs" / "changes" / "fix-single-migration-owner"
        spec = (change_dir / "spec.md").read_text(encoding="utf-8")
        tasks = (change_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "仅允许文档变更",
            spec,
            "spec.md must not claim only doc changes are authorized after implementation",
        )
        self.assertNotIn(
            "当前不授权应用代码",
            spec,
            "spec.md must not claim application code is still unauthorized",
        )
        self.assertNotIn(
            "只有在用户明确授权实现后才开始",
            tasks,
            "tasks.md must not claim no implementation task has started",
        )

    def test_p3_runbook_records_current_focused_test_count(self):
        runbook = (ROOT / "docs" / "deploy_runbook.md").read_text(encoding="utf-8")
        lines = [
            line for line in runbook.splitlines() if "test_single_migration_owner" in line
        ]
        self.assertTrue(lines, "runbook must record the focused test suite")
        for line in lines:
            self.assertNotIn(
                "87 项",
                line,
                f"runbook test count is stale (97 tests now): {line}",
            )
        self.assertTrue(
            any("97" in line for line in lines),
            "runbook must record the current 97-test count for the focused suite",
        )

    def test_p3_design_doc_no_longer_claims_in_memory_only_race_live_state(self):
        design = (
            ROOT / "docs" / "changes" / "fix-single-migration-owner" / "design.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn(
            "不写持久配置",
            design,
            "design.md must not claim race_live state is never persisted "
            "(it now persists to the retry state file)",
        )
        self.assertNotIn(
            "本次内存状态",
            design,
            "design.md must not claim race_live state is memory-only for one run",
        )

    def test_p3_review_handoff_records_current_focused_test_count(self):
        handoff = (
            ROOT / "docs" / "changes" / "fix-single-migration-owner" / "REVIEW_HANDOFF.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn(
            "77 用例",
            handoff,
            "REVIEW_HANDOFF.md focused-suite count is stale (97 tests now)",
        )
        self.assertIn(
            "97 用例",
            handoff,
            "REVIEW_HANDOFF.md must record the current 97-test count",
        )

    def test_p3_rollback_docs_describe_immutable_oid_checkout(self):
        runbook = (ROOT / "docs" / "deploy_runbook.md").read_text(encoding="utf-8")
        self.assertNotIn(
            '"$TARGET_REF:',
            runbook,
            "deploy_runbook.md must not describe cat-file against the movable "
            "TARGET_REF (checks bind to the resolved immutable OID)",
        )
        guide = (ROOT / "docs" / "rollback_guide.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "git checkout <git-ref>",
            guide,
            "rollback_guide.md must not describe checkout of the movable ref; "
            "checkout uses the resolved immutable OID",
        )
        self.assertIn(
            "OID",
            guide,
            "rollback_guide.md must describe the immutable-OID binding",
        )

    def test_p3_review_handoff_no_longer_presents_round5_as_pending(self):
        handoff = (
            ROOT / "docs" / "changes" / "fix-single-migration-owner" / "REVIEW_HANDOFF.md"
        ).read_text(encoding="utf-8")
        pending_markers = ("尚未", "待办", "等待", "需同一", "必须在")
        offenders = [
            line.strip()
            for line in handoff.splitlines()
            if "第 5 轮" in line and any(marker in line for marker in pending_markers)
        ]
        self.assertEqual(
            offenders,
            [],
            "REVIEW_HANDOFF.md must not describe the round-5 review as the "
            f"current pending gate (history narrative may stay): {offenders}",
        )
        self.assertIn(
            "第 6 轮",
            handoff,
            "REVIEW_HANDOFF.md must record the round-6 review state",
        )

    def test_p3_spec_records_p0_collectstatic_exception(self):
        spec = (
            ROOT / "docs" / "changes" / "fix-single-migration-owner" / "spec.md"
        ).read_text(encoding="utf-8")
        section = spec.split("### 5.1", 1)[-1].split("### 5.2", 1)[0]
        self.assertIn(
            "deploy_race_live_p0_closed.sh",
            section,
            "spec.md §5.1 must record the approved collectstatic exception for "
            "the race-live P0 closed-admission one-shot script",
        )
        self.assertRegex(
            section,
            r"deploy_race_live_p0_closed\.sh[^\n]{0,120}(例外|豁免)"
            r"|(例外|豁免)[^\n]{0,120}deploy_race_live_p0_closed\.sh",
            "spec.md §5.1 must mark deploy_race_live_p0_closed.sh as an explicit "
            "exception, not a silent second collectstatic owner",
        )

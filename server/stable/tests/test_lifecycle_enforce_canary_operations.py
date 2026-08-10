import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[3]
PROMOTE = ROOT / "deploy/promote_lifecycle_enforce_canary.sh"
SWITCH = ROOT / "deploy/switch_lifecycle_mode.sh"
COHERENCE = ROOT / "deploy/verify_lifecycle_runtime_coherence.sh"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


FAKE_LOCK = """#!/bin/sh
set -eu
printf 'lock %s %s\n' "${DEPLOYMENT_LOCK_ACTION:-}" "$*" >> "${CANARY_OPS_LOG:?}"
exit 0
"""

FAKE_VERIFY = """#!/bin/sh
set -eu
printf 'coherence %s %s %s %s\n' \
  "${EXPECTED_LIFECYCLE_ENABLED:-}" "${EXPECTED_LIFECYCLE_MODE:-}" \
  "${EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256:-}" \
  "${EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS:-}" >> "${CANARY_OPS_LOG:?}"
exit 0
"""

FAKE_COMPOSE = """#!/bin/sh
set -eu
printf 'compose %s\n' "$*" >> "${CANARY_OPS_LOG:?}"
case " $* " in *' exec -T web '*) cat >/dev/null ;; esac
exit 0
"""

FAKE_SWITCH_COMPOSE = """#!/bin/sh
set -eu
printf 'compose %s\n' "$*" >> "${CANARY_OPS_LOG:?}"
case " $* " in *' exec -T web '*) cat >/dev/null ;; esac
if [ -n "${CANARY_FAIL_COMPOSE_MATCH:-}" ] \
  && printf '%s' "$*" | grep -F -- "$CANARY_FAIL_COMPOSE_MATCH" >/dev/null; then
  exit 1
fi
exit 0
"""

FAKE_HEALTH = """#!/bin/sh
set -eu
printf 'health web\n' >> "${CANARY_OPS_LOG:?}"
exit 0
"""


class PromotionHarness:
    def __init__(self, base: Path):
        self.repo = base / "repo"
        self.deploy = self.repo / "deploy"
        (self.deploy / "docker").mkdir(parents=True)
        self.log = base / "calls.log"
        self.manifest = base / "canary.json"
        self.manifest.write_bytes(b'{"schema_version":1}\n')
        self.sha256 = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        if PROMOTE.exists():
            shutil.copy2(PROMOTE, self.deploy / PROMOTE.name)
            (self.deploy / PROMOTE.name).chmod(0o755)
        _write_executable(self.deploy / "deployment_lock.sh", FAKE_LOCK)
        _write_executable(
            self.deploy / "verify_lifecycle_runtime_coherence.sh", FAKE_VERIFY
        )
        _write_executable(self.deploy / "docker/compose-wrapper.sh", FAKE_COMPOSE)

    def run(self, **overrides):
        self.assert_script()
        env = {
            **os.environ,
            "CANARY_OPS_LOG": str(self.log),
            "COMPOSE_FILE": "docker-compose.prod.yml",
            "EXPECTED_COMPOSE_PROJECT": "umanews",
            "EXPECTED_RELEASE_DIR": str(self.repo),
            "EXPECTED_IMAGE_ID": "sha256:good",
            "EXPECTED_RELEASE_COMMIT": "a" * 40,
            "EXPECTED_CANARY_EVENT_IDS": "186,187",
            "MANIFEST_FILE": str(self.manifest),
            "MANIFEST_SHA256": self.sha256,
            "DEPLOYMENT_LOCK_DIR": str(self.repo / "lock"),
            "DEPLOYMENT_LOCK_TOKEN": "0123456789abcdef0123456789abcdef",
        }
        env.update(overrides)
        return subprocess.run(
            ["sh", str(self.deploy / PROMOTE.name)],
            cwd=self.repo,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def assert_script(self):
        if not (self.deploy / PROMOTE.name).exists():
            raise AssertionError("missing enforce-canary promotion wrapper")

    def lines(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []


class SwitchHarness:
    def __init__(self, base: Path):
        self.repo = base / "repo"
        self.deploy = self.repo / "deploy"
        (self.deploy / "docker").mkdir(parents=True)
        self.log = base / "calls.log"
        self.canonical = base / "canonical.env"
        self.active = self.repo / ".env"
        env_bytes = (
            "KEEP_ME=yes\n"
            "RACE_EVENT_LIFECYCLE_ENABLED=false\n"
            "RACE_EVENT_LIFECYCLE_MODE=off\n"
            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=\n"
            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=\n"
        )
        for path in (self.canonical, self.active):
            path.write_text(env_bytes, encoding="utf-8")
            path.chmod(0o600)
        self.manifest = base / "canary.json"
        self.manifest.write_bytes(b'{"schema_version":1}\n')
        self.sha256 = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        switch_source = SWITCH.read_text(encoding="utf-8").replace(
            "/opt/umanewsbot/.env", str(self.canonical)
        )
        _write_executable(self.deploy / SWITCH.name, switch_source)
        _write_executable(self.deploy / "deployment_lock.sh", FAKE_LOCK)
        _write_executable(
            self.deploy / "verify_lifecycle_runtime_coherence.sh", FAKE_VERIFY
        )
        _write_executable(
            self.deploy / "docker/compose-wrapper.sh", FAKE_SWITCH_COMPOSE
        )
        _write_executable(
            self.deploy / "wait_for_compose_service_healthy.sh", FAKE_HEALTH
        )

    def run(self, **overrides):
        env = {
            **os.environ,
            "CANARY_OPS_LOG": str(self.log),
            "ACTIVE_RELEASE_ENV_FILE": str(self.active),
            "COMPOSE_FILE": "docker-compose.prod.yml",
            "EXPECTED_COMPOSE_PROJECT": "umanews",
            "EXPECTED_RELEASE_DIR": str(self.repo),
            "EXPECTED_IMAGE_ID": "sha256:good",
            "EXPECTED_RELEASE_COMMIT": "a" * 40,
            "TARGET_LIFECYCLE_ENABLED": "true",
            "TARGET_LIFECYCLE_MODE": "enforce",
            "EXPECTED_CANARY_EVENT_IDS": "186,187",
            "MANIFEST_FILE": str(self.manifest),
            "MANIFEST_SHA256": self.sha256,
            "DEPLOYMENT_LOCK_DIR": str(self.repo / "lock"),
            "DEPLOYMENT_LOCK_TOKEN": "0123456789abcdef0123456789abcdef",
        }
        env.update(overrides)
        return subprocess.run(
            ["sh", str(self.deploy / SWITCH.name)],
            cwd=self.repo,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def lines(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    @staticmethod
    def values(path: Path):
        return dict(
            line.split("=", 1)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("RACE_EVENT_LIFECYCLE_")
        )


class LifecycleEnforceCanaryOperationsTests(SimpleTestCase):
    def test_promotion_uses_shared_lock_false_off_coherence_and_bounded_stdin(self):
        with TemporaryDirectory() as temporary:
            harness = PromotionHarness(Path(temporary))
            result = harness.run()
            lines = harness.lines()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(lines[0].startswith("lock lifecycle-enforce-canary-promotion acquire"))
        self.assertEqual(lines[1], "coherence false off  ")
        command = next(line for line in lines if line.startswith("compose "))
        self.assertIn("exec -T web", command)
        self.assertIn("promote_race_event_lifecycle_enforce_canary", command)
        self.assertIn("--manifest-stdin", command)
        self.assertIn("--expected-event-ids 186,187", command)
        self.assertIn("--apply", command)
        self.assertIn("--confirm-enforce-canary", command)
        self.assertNotIn("prepare", command)
        self.assertEqual(lines[-2], "coherence false off  ")
        self.assertTrue(lines[-1].endswith(" release"))

    def test_promotion_rejects_symlink_or_bad_raw_sha_before_lock(self):
        with TemporaryDirectory() as temporary:
            harness = PromotionHarness(Path(temporary))
            target = harness.manifest
            link = target.with_name("manifest-link.json")
            link.symlink_to(target)
            result = harness.run(MANIFEST_FILE=str(link))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(harness.lines(), [])

        with TemporaryDirectory() as temporary:
            harness = PromotionHarness(Path(temporary))
            result = harness.run(MANIFEST_SHA256="b" * 64)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(harness.lines(), [])

    def test_switch_and_coherence_bind_both_canary_runtime_keys(self):
        switch_source = SWITCH.read_text(encoding="utf-8")
        coherence_source = COHERENCE.read_text(encoding="utf-8")
        for key in (
            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256",
            "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS",
        ):
            self.assertIn(key, switch_source)
            self.assertIn(key, coherence_source)
        self.assertIn("true/enforce", switch_source)
        self.assertIn("--manifest-stdin", switch_source)
        self.assertIn("--disarm", switch_source)
        self.assertIn("--activate", switch_source)

    def test_env_example_declares_empty_fail_closed_canary_keys(self):
        env_source = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256=", env_source)
        self.assertIn("RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS=", env_source)

    def test_deployment_lock_allows_promotion_action(self):
        source = (ROOT / "deploy/deployment_lock.sh").read_text(encoding="utf-8")
        self.assertIn("lifecycle-enforce-canary-promotion", source)

    def test_enforce_switch_uses_staged_inactive_activate_active_order(self):
        with TemporaryDirectory() as temporary:
            harness = SwitchHarness(Path(temporary))
            result = harness.run()
            lines = harness.lines()
            canonical = harness.values(harness.canonical)
            active = harness.values(harness.active)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr, lines))
        fragments = (
            "lock lifecycle-mode-switch acquire",
            "coherence false off",
            "--phase inactive --disarm",
            "stop beat worker",
            "up -d --no-deps --force-recreate web",
            "health web",
            "--phase inactive",
            "up -d --no-deps --force-recreate worker",
            f"coherence true enforce {harness.sha256} 186,187",
            "--phase active --activate",
            "--phase active",
            "up -d --no-deps --force-recreate beat",
            "lock lifecycle-mode-switch release",
        )
        positions = []
        start = 0
        for fragment in fragments:
            position = next(
                i for i, line in enumerate(lines[start:], start=start) if fragment in line
            )
            positions.append(position)
            start = position + 1
        self.assertEqual(positions, sorted(positions), lines)
        self.assertEqual(canonical, active)
        self.assertEqual(
            canonical["RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256"],
            harness.sha256,
        )
        self.assertEqual(
            canonical["RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS"], "186,187"
        )
        self.assertFalse(any("scanner" in line or "race_live" in line for line in lines))

    def test_activation_failure_converges_off_and_never_starts_beat(self):
        with TemporaryDirectory() as temporary:
            harness = SwitchHarness(Path(temporary))
            result = harness.run(CANARY_FAIL_COMPOSE_MATCH="--activate")
            lines = harness.lines()
            values = (harness.values(harness.canonical), harness.values(harness.active))
        self.assertNotEqual(result.returncode, 0)
        for value in values:
            self.assertEqual(value["RACE_EVENT_LIFECYCLE_ENABLED"], "false")
            self.assertEqual(value["RACE_EVENT_LIFECYCLE_MODE"], "off")
            self.assertEqual(value["RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256"], "")
            self.assertEqual(value["RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS"], "")
        activation_index = next(i for i, line in enumerate(lines) if "--activate" in line)
        self.assertFalse(
            any(
                "up -d --no-deps --force-recreate beat" in line
                for line in lines[activation_index + 1 :]
            ),
            lines,
        )

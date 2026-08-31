#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("racing_api_account_budget.py")


def load_tool():
    if not SCRIPT_PATH.is_file():
        raise AssertionError(f"目标入口尚不存在：{SCRIPT_PATH}")
    spec = importlib.util.spec_from_file_location("racing_api_account_budget", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载目标入口：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MutableClock:
    def __init__(self, value: float):
        self.value = value
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class RacingApiAccountBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module = load_tool()

    def _budget(self, root: Path, clock: MutableClock, **overrides):
        values = {
            "root": root,
            "credential_alias": "tra-primary",
            "scope_id": "montjeu-proof",
            "scope_manifest_sha256": "a" * 64,
            "request_ceiling": 3,
            "min_interval_seconds": 0.25,
            "valid_until_epoch": 4102444800.0,
            "wall_clock": clock.now,
            "sleep": clock.sleep,
        }
        values.update(overrides)
        return self.module.FileAccountBudget(**values)

    def test_two_instances_share_one_account_interval_and_request_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "budget"
            clock = MutableClock(1000.0)
            first = self._budget(root, clock)
            second = self._budget(root, clock)

            reservation_one = first.reserve()
            reservation_two = second.reserve()

            self.assertEqual(reservation_one.request_number, 1)
            self.assertEqual(reservation_two.request_number, 2)
            self.assertAlmostEqual(
                reservation_two.started_at_epoch - reservation_one.started_at_epoch,
                0.25,
            )
            self.assertEqual(clock.sleeps, [0.25])
            self.assertEqual(second.snapshot()["request_count"], 2)

    def test_two_processes_are_serialized_by_the_same_lock_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "budget"
            FileBudget = self.module.FileAccountBudget
            FileBudget(
                root=root,
                credential_alias="tra-primary",
                scope_id="multiprocess-proof",
                scope_manifest_sha256="b" * 64,
                request_ceiling=2,
                min_interval_seconds=0.25,
                valid_until_epoch=4102444800.0,
            )
            script = (
                "import json,sys;"
                f"sys.path.insert(0,{str(SCRIPT_PATH.parent)!r});"
                "from racing_api_account_budget import FileAccountBudget;"
                f"b=FileAccountBudget(root=__import__('pathlib').Path({str(root)!r}),"
                "credential_alias='tra-primary',scope_id='multiprocess-proof',"
                f"scope_manifest_sha256={'b' * 64!r},request_ceiling=2,"
                "min_interval_seconds=0.25,valid_until_epoch=4102444800.0);"
                "r=b.reserve();"
                "print(json.dumps({'n':r.request_number,'started':r.started_at_epoch}))"
            )
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(2)
            ]
            outputs = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                outputs.append(json.loads(stdout))

            outputs.sort(key=lambda item: item["started"])
            self.assertEqual(sorted(item["n"] for item in outputs), [1, 2])
            self.assertGreaterEqual(outputs[1]["started"] - outputs[0]["started"], 0.24)

    def test_reserved_attempt_survives_crash_and_is_not_returned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "budget"
            clock = MutableClock(2000.0)
            self._budget(root, clock, request_ceiling=1).reserve()

            resumed = self._budget(root, clock, request_ceiling=1)
            with self.assertRaisesRegex(self.module.AccountBudgetError, "ceiling exhausted"):
                resumed.reserve()

            state = resumed.snapshot()
            self.assertEqual(state["request_count"], 1)
            self.assertEqual(state["generation"], 1)

    def test_scope_or_credential_drift_is_rejected_before_reservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "budget"
            clock = MutableClock(3000.0)
            self._budget(root, clock)

            with self.assertRaisesRegex(self.module.AccountBudgetError, "identity drift"):
                self._budget(root, clock, scope_id="other-scope")
            with self.assertRaisesRegex(self.module.AccountBudgetError, "identity drift"):
                self._budget(root, clock, credential_alias="other-account")

    def test_clock_rollback_and_symlink_state_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "budget"
            clock = MutableClock(4000.0)
            budget = self._budget(root, clock)
            budget.reserve()
            clock.value = 3990.0
            with self.assertRaisesRegex(self.module.AccountBudgetError, "clock moved backwards"):
                budget.reserve()

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "budget"
            clock = MutableClock(5000.0)
            budget = self._budget(root, clock)
            state = root / "account-budget.json"
            real = base / "real-state.json"
            state.replace(real)
            state.symlink_to(real)
            with self.assertRaisesRegex(self.module.AccountBudgetError, "symlink"):
                budget.snapshot()

    def test_retry_after_defers_all_instances(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "budget"
            clock = MutableClock(6000.0)
            first = self._budget(root, clock)
            second = self._budget(root, clock)
            first.reserve()
            first.defer(2.0, reason="http_429")

            reservation = second.reserve()

            self.assertGreaterEqual(reservation.started_at_epoch, 6002.0)
            self.assertEqual(clock.sleeps, [2.0])
            self.assertEqual(second.snapshot()["last_defer_reason"], "http_429")

    def test_each_reservation_and_defer_stays_inside_exclusive_proof_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "budget"
            clock = MutableClock(7000.0)
            budget = self._budget(root, clock, valid_until_epoch=7000.2)
            budget.reserve()

            with self.assertRaisesRegex(
                self.module.AccountBudgetError,
                "expires before next request",
            ):
                budget.reserve()
            self.assertEqual(clock.sleeps, [])
            with self.assertRaisesRegex(
                self.module.AccountBudgetError,
                "expires during requested defer",
            ):
                budget.defer(1.0, reason="http_429")

    def test_exclusive_proof_is_sha_bound_time_limited_and_zero_caller(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proof_path = root / "exclusive-proof.json"
            payload = {
                "schema_version": "racing-api-exclusive-account-proof.v1",
                "status": "approved",
                "host": "api.theracingapi.com",
                "credential_alias": "tra-primary",
                "scope_id": "montjeu-proof",
                "scope_manifest_sha256": "a" * 64,
                "observed_at": "2026-08-29T10:00:00+00:00",
                "valid_until": "2026-08-29T10:15:00+00:00",
                "checks": {
                    "race_live_scheduler_enabled": False,
                    "race_live_runner_active": 0,
                    "race_data_sync_network_enabled": False,
                    "race_data_sync_active_claims": 0,
                    "other_backfill_processes": 0,
                    "manual_caller_window_reserved": True,
                },
            }
            proof_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            proof_path.chmod(0o600)
            proof_sha = hashlib.sha256(proof_path.read_bytes()).hexdigest()

            loaded = self.module.load_exclusive_account_proof(
                proof_path,
                expected_sha256=proof_sha,
                credential_alias="tra-primary",
                scope_id="montjeu-proof",
                scope_manifest_sha256="a" * 64,
                now=datetime(2026, 8, 29, 10, 5, tzinfo=timezone.utc),
            )

            self.assertEqual(loaded["status"], "approved")
            with self.assertRaisesRegex(self.module.AccountBudgetError, "expired"):
                self.module.load_exclusive_account_proof(
                    proof_path,
                    expected_sha256=proof_sha,
                    credential_alias="tra-primary",
                    scope_id="montjeu-proof",
                    scope_manifest_sha256="a" * 64,
                    now=datetime(2026, 8, 29, 10, 16, tzinfo=timezone.utc),
                )


if __name__ == "__main__":
    unittest.main()

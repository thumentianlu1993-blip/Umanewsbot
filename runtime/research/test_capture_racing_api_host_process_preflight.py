from __future__ import annotations

import json
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.research.capture_racing_api_host_process_preflight import (
    capture_host_process_preflight,
)


class CaptureRacingApiHostProcessPreflightTests(unittest.TestCase):
    def test_captures_host_and_container_processes_without_raw_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            responses = {
                ("ps", "-axo", "pid=,command="): "999 /usr/bin/python benign.py\n",
                ("docker", "ps", "--format", "{{.ID}}\t{{.Names}}"): (
                    "abcdef123456\tumanews-web\n"
                ),
                ("docker", "top", "abcdef123456", "-eo", "pid,args"): (
                    "PID COMMAND\n1000 celery -A app worker\n"
                ),
            }

            def runner(command):
                return responses[tuple(command)]

            output = root / "host-evidence.json"
            payload = capture_host_process_preflight(
                host_role="runner",
                scope_id="batch-1",
                scope_manifest_sha256="a" * 64,
                output_file=output,
                now=datetime(2026, 8, 30, tzinfo=timezone.utc),
                runner=runner,
            )
            self.assertEqual(payload["matching_processes"], [])
            self.assertEqual(payload["host_role"], "runner")
            self.assertEqual(payload["containers"][0]["name"], "umanews-web")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertNotIn("celery -A app", output.read_text(encoding="utf-8"))

    def test_records_only_hash_and_marker_for_matching_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def runner(command):
                if command[:2] == ["ps", "-axo"]:
                    return "2000 python racing_api_targeted_batch_export.py --allow-network\n"
                if command[:2] == ["docker", "ps"]:
                    return ""
                raise AssertionError(command)

            output = root / "host-evidence.json"
            payload = capture_host_process_preflight(
                host_role="production",
                scope_id="batch-1",
                scope_manifest_sha256="a" * 64,
                output_file=output,
                now=datetime(2026, 8, 30, tzinfo=timezone.utc),
                runner=runner,
            )
            self.assertEqual(len(payload["matching_processes"]), 1)
            self.assertEqual(payload["host_role"], "production")
            row = payload["matching_processes"][0]
            self.assertEqual(row["marker"], "racing_api_targeted_batch_export.py")
            self.assertEqual(len(row["command_sha256"]), 64)
            frozen = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotIn("command", frozen["matching_processes"][0])


if __name__ == "__main__":
    unittest.main()

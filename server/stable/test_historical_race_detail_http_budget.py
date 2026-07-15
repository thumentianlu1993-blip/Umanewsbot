from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_tool(name: str):
    path = REPO_ROOT / "runtime" / "tools" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _policy(*, max_requests: int = 2, max_requests_per_host: int = 1) -> dict:
    return {
        "max_requests": max_requests,
        "max_requests_per_host": max_requests_per_host,
        "minimum_interval_seconds": 1.0,
        "allowed_hosts": ["www.jra.go.jp"],
        "redirect_hosts": ["www.jra.go.jp"],
        "url_patterns": {
            "www.jra.go.jp": [r"^/datafile/seiseki/replay/200[56]/[0-9]+\.html$"],
        },
    }


class HistoricalRaceDetailHTTPBudgetTests(SimpleTestCase):
    def test_host_budget_is_per_descriptor_while_shared_state_still_limits_and_audits(self):
        module = _load_tool("historical_race_detail_http.py")
        first_url = "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"
        second_url = "https://www.jra.go.jp/datafile/seiseki/replay/2006/27.html"

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared_root = root / "host-locks"
            first_state = root / "first-request-budget.json"
            second_state = root / "second-request-budget.json"
            first = module.ControlledRequestSession(
                policy=_policy(),
                shard_id="japan-2005-jra-01",
                shard_state_path=first_state,
                host_state_root=shared_root,
            )
            second = module.ControlledRequestSession(
                policy=_policy(),
                shard_id="japan-2006-jra-01",
                shard_state_path=second_state,
                host_state_root=shared_root,
            )

            with patch.object(module.time, "time", side_effect=[100.0, 100.0, 100.0, 101.0]), patch.object(
                module.time, "sleep"
            ) as sleep:
                first.reserve_initial(first_url)
                second.reserve_initial(second_url)

            sleep.assert_called_once_with(1.0)
            with self.assertRaisesMessage(module.ControlledHTTPError, "per-host request budget"):
                module.ControlledRequestSession(
                    policy=_policy(),
                    shard_id="japan-2006-jra-01",
                    shard_state_path=second_state,
                    host_state_root=shared_root,
                ).reserve_initial(second_url)

            first_payload = json.loads(first_state.read_text(encoding="utf-8"))
            second_payload = json.loads(second_state.read_text(encoding="utf-8"))
            shared_payload = json.loads(
                (shared_root / "www.jra.go.jp.last-start.json").read_text(encoding="utf-8")
            )
            audit_rows = [
                json.loads(line)
                for line in (shared_root / "www.jra.go.jp.requests.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

        self.assertEqual(first_payload["request_count"], 1)
        self.assertEqual(second_payload["request_count"], 1)
        self.assertEqual(shared_payload["request_count"], 2)
        self.assertEqual([row["shard_id"] for row in audit_rows], [
            "japan-2005-jra-01",
            "japan-2006-jra-01",
        ])

    def test_runner_host_budget_uses_only_the_descriptor_ledger(self):
        module = _load_tool("historical_race_detail_runner_v2.py")
        url = "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"
        descriptor = {"request_policy": _policy()}

        module.validate_request(descriptor, [], url=url, redirect_chain=[])
        with self.assertRaisesMessage(module.RunnerV2Error, "per-host request budget"):
            module.validate_request(
                descriptor,
                [{"host": "www.jra.go.jp", "url": url}],
                url=url,
                redirect_chain=[],
            )

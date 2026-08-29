from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import importlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class TheRacingApiFreeSourceProofTests(SimpleTestCase):
    NOW = datetime(2026, 7, 17, 1, 30, tzinfo=dt_timezone.utc)
    FINISHED = datetime(2026, 7, 17, 1, 30, 3, tzinfo=dt_timezone.utc)
    USERNAME = "proof-user"
    PASSWORD = "proof-password#42"

    def _service(self):
        try:
            return importlib.import_module("stable.services.race_live_source_proof")
        except ModuleNotFoundError:
            self.fail("The Racing API Free 受控 proof runner 尚未实现")

    def _secret(self, root: Path, *, mode: int = 0o600) -> Path:
        path = root / "the-racing-api-free.env"
        path.write_text(
            "\n".join(
                (
                    f"THE_RACING_API_USERNAME={self.USERNAME}",
                    f'THE_RACING_API_PASSWORD="{self.PASSWORD}"',
                    "",
                )
            ),
            encoding="utf-8",
        )
        path.chmod(mode)
        return path

    def _registry(self, root: Path, **overrides) -> tuple[Path, str]:
        payload = {
            "schema_version": 1,
            "source_key": "the_racing_api",
            "host": "api.theracingapi.com",
            "terms_status": "approved",
            "proof_network_allowed": True,
            "automation_allowed": True,
            "valid_until": "2026-08-17T00:00:00+00:00",
            "max_requests": 3,
            "evidence": {
                "documentation_url": "https://api.theracingapi.com/documentation",
                "terms_url": "https://www.theracingapi.com/terms-of-service",
                "verified_at": "2026-07-17T00:00:00+00:00",
                "authorization_basis": "user_confirmed_automation_permission",
            },
            "endpoints": [
                {
                    "name": "regions",
                    "path": "/v1/courses/regions",
                },
                {
                    "name": "racecards_today",
                    "path": "/v1/racecards/free?day=today&limit=500&skip=0",
                },
                {
                    "name": "results_today",
                    "path": "/v1/results/today/free?limit=50&skip=0",
                },
                {
                    "name": "racecards_sync_today",
                    "path": "/v1/racecards/free?day=today&region_codes=gb&limit=500&skip=0",
                },
                {
                    "name": "racecards_sync_tomorrow",
                    "path": "/v1/racecards/free?day=tomorrow&region_codes=gb&limit=500&skip=0",
                },
            ],
        }
        payload.update(overrides)
        path = root / "source-registry.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _response(self, body, *, status_code=200, content_type="application/json"):
        service = self._service()
        response_type = getattr(service, "RaceLiveProofHttpResponse", None)
        self.assertIsNotNone(response_type, "proof HTTP response contract 尚未实现")
        return response_type(
            status_code=status_code,
            content_type=content_type,
            body=json.dumps(body).encode("utf-8"),
            elapsed_ms=125,
            redirect_url=None,
        )

    def _registry_v2(self, root: Path, **overrides) -> tuple[Path, str]:
        payload = {
            "schema_version": 2,
            "source_key": "the_racing_api",
            "host": "api.theracingapi.com",
            "terms_status": "approved",
            "proof_network_allowed": True,
            "automation_allowed": True,
            "valid_until": "2026-08-17T00:00:00+00:00",
            "max_requests": 3,
            "evidence": {
                "documentation_url": "https://api.theracingapi.com/documentation",
                "terms_url": "https://www.theracingapi.com/terms-of-service",
                "verified_at": "2026-07-17T00:00:00+00:00",
                "authorization_basis": "user_confirmed_automation_permission",
            },
            "allowed_region_codes": {
                "united_kingdom": "gb",
                "france": "fr",
                "hong_kong": "hk",
                "ireland": "ire",
                "japan": "jpn",
                "united_states": "usa",
            },
            "route_contracts": {
                "racecards_free": {
                    "path": "/v1/racecards/free",
                    "day": ["today", "tomorrow"],
                    "limit": [500],
                    "skip": [0],
                },
                "results_today_free": {
                    "path": "/v1/results/today/free",
                    "limit": [50],
                    "skip": list(range(0, 500, 50)),
                },
                "result_by_id": {
                    "path": "/v1/results/{race_id}",
                },
            },
        }
        payload.update(overrides)
        path = root / "source-registry-v2.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_schema_v2_builds_region_routes_in_fixed_order_and_records_actual_paths(
        self,
    ):
        service = self._service()
        runner = service.run_the_racing_api_free_proof
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = self._secret(root)
            registry, digest = self._registry_v2(root)
            output = root / "v2-proof"
            calls = []
            bodies = {
                "racecards_sync_today": {"racecards": []},
                "racecards_sync_tomorrow": {"racecards": []},
                "results_today": {"results": []},
            }

            def transport(**kwargs):
                calls.append(kwargs)
                return self._response(bodies[kwargs["endpoint_name"]])

            with patch.object(
                service,
                "build_the_racing_api_route_url",
                wraps=service.build_the_racing_api_route_url,
            ) as route_builder:
                result = runner(
                    secret_env_file=secret,
                    registry_file=registry,
                    expected_registry_sha256=digest,
                    output_dir=output,
                    now=self.NOW,
                    transport=transport,
                    sleep=lambda _: None,
                    max_requests=3,
                    region="france",
                    clock=lambda: self.FINISHED,
                )

            self.assertTrue(result.completed)
            self.assertEqual(
                [call["endpoint_name"] for call in calls],
                [
                    "racecards_sync_today",
                    "racecards_sync_tomorrow",
                    "results_today",
                ],
            )
            expected_urls = [
                (
                    "https://api.theracingapi.com/v1/racecards/free"
                    "?day=today&region_codes=fr&limit=500&skip=0"
                ),
                (
                    "https://api.theracingapi.com/v1/racecards/free"
                    "?day=tomorrow&region_codes=fr&limit=500&skip=0"
                ),
                (
                    "https://api.theracingapi.com/v1/results/today/free"
                    "?limit=50&skip=0"
                ),
            ]
            self.assertEqual([call["url"] for call in calls], expected_urls)
            route_calls = [
                call.kwargs for call in route_builder.call_args_list
            ]
            self.assertEqual(
                [call["route_name"] for call in route_calls],
                [
                    "racecards_free",
                    "racecards_free",
                    "results_today_free",
                ],
            )
            self.assertEqual(
                [call["region"] for call in route_calls],
                ["france", "france", "france"],
            )
            self.assertEqual(
                [call.get("day") for call in route_calls],
                ["today", "tomorrow", None],
            )
            self.assertTrue(
                all(call["limit"] in {50, 500} and call["skip"] == 0 for call in route_calls)
            )
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["endpoints"],
                [
                    url.removeprefix("https://api.theracingapi.com")
                    for url in expected_urls
                ],
            )

    def test_schema_v2_region_and_registry_budget_fail_closed_before_transport(self):
        service = self._service()
        runner = service.run_the_racing_api_free_proof
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = self._secret(root)
            registry, digest = self._registry_v2(root)
            limited_root = root / "limited"
            limited_root.mkdir()
            limited_registry, limited_digest = self._registry_v2(
                limited_root,
                max_requests=2,
            )
            transport_calls = []

            def transport(**kwargs):
                transport_calls.append(kwargs)
                raise AssertionError("transport must not be called")

            cases = (
                ("missing", registry, digest, None, 3),
                ("invalid", registry, digest, "australia", 3),
                (
                    "registry-budget",
                    limited_registry,
                    limited_digest,
                    "france",
                    3,
                ),
            )
            for name, registry_file, registry_digest, region, max_requests in cases:
                with self.subTest(case=name):
                    with self.assertRaises((ValueError, PermissionError)):
                        runner(
                            secret_env_file=secret,
                            registry_file=registry_file,
                            expected_registry_sha256=registry_digest,
                            output_dir=root / f"blocked-{name}",
                            now=self.NOW,
                            transport=transport,
                            sleep=lambda _: None,
                            max_requests=max_requests,
                            region=region,
                        )
            self.assertEqual(transport_calls, [])

    def test_success_is_budgeted_rate_limited_atomic_and_sanitized(self):
        service = self._service()
        runner = getattr(service, "run_the_racing_api_free_proof", None)
        self.assertTrue(callable(runner), "The Racing API proof service 尚未实现")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = self._secret(root)
            registry, digest = self._registry(root)
            output = root / "proof-output"
            calls = []
            sleeps = []
            order = []
            bodies = {
                "regions": [{"region": "Great Britain", "region_code": "gb"}],
                "racecards_today": {
                    "racecards": [
                        {
                            "race_id": "race-secret-1",
                            "race_name": "Do Not Persist Stakes",
                            "runners": [
                                {
                                    "horse_id": "horse-secret-1",
                                    "horse": "Do Not Persist Horse",
                                    "number": "1",
                                }
                            ],
                        }
                    ],
                    "total": 1,
                    "limit": 10,
                    "skip": 0,
                },
                "results_today": {
                    "results": [],
                    "total": 0,
                    "limit": 10,
                    "skip": 0,
                },
            }

            def transport(**kwargs):
                calls.append(kwargs)
                endpoint_name = kwargs["endpoint_name"]
                order.append(f"transport:{endpoint_name}")
                return self._response(bodies[endpoint_name])

            def sleep(seconds):
                sleeps.append(seconds)
                order.append(f"sleep:{seconds}")

            def clock():
                order.append("clock")
                return self.FINISHED

            result = runner(
                secret_env_file=secret,
                registry_file=registry,
                expected_registry_sha256=digest,
                output_dir=output,
                now=self.NOW,
                transport=transport,
                sleep=sleep,
                max_requests=3,
                clock=clock,
            )

            self.assertTrue(result.completed)
            self.assertEqual(result.request_count, 3)
            self.assertEqual(sleeps, [1.05, 1.05])
            self.assertEqual(
                order,
                [
                    "transport:regions",
                    "sleep:1.05",
                    "transport:racecards_today",
                    "sleep:1.05",
                    "transport:results_today",
                    "clock",
                ],
            )
            self.assertEqual([call["endpoint_name"] for call in calls], list(bodies))
            self.assertTrue(
                all(call["timeout_seconds"] == 15 for call in calls)
            )
            self.assertTrue(
                all(call["max_response_bytes"] == 2 * 1024 * 1024 for call in calls)
            )
            self.assertTrue(all(call["allow_redirects"] is False for call in calls))
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"manifest.json", "requests.jsonl", "summary.json"},
            )
            artifact_text = "\n".join(
                path.read_text(encoding="utf-8") for path in output.iterdir()
            )
            for forbidden in (
                self.USERNAME,
                self.PASSWORD,
                "Do Not Persist Stakes",
                "Do Not Persist Horse",
                "race-secret-1",
                "horse-secret-1",
            ):
                self.assertNotIn(forbidden, artifact_text)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["registry_sha256"], digest)
            self.assertEqual(summary["request_count"], 3)
            self.assertTrue(summary["completed"])
            self.assertEqual(summary["started_at"], self.NOW.isoformat())
            self.assertEqual(summary["finished_at"], self.FINISHED.isoformat())
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["runner_version"], "race-live-proof-v1")
            self.assertEqual(manifest["request_budget"], 3)
            self.assertEqual(
                manifest["endpoints"],
                [
                    "/v1/courses/regions",
                    "/v1/racecards/free?day=today&limit=500&skip=0",
                    "/v1/results/today/free?limit=50&skip=0",
                    "/v1/racecards/free?day=today&region_codes=gb&limit=500&skip=0",
                    "/v1/racecards/free?day=tomorrow&region_codes=gb&limit=500&skip=0",
                ],
            )
            request_rows = [
                json.loads(line)
                for line in (output / "requests.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(request_rows[1]["collection_count"], 1)
            self.assertIn("race_id", request_rows[1]["row_fields"])
            self.assertIn("horse_id", request_rows[1]["runner_fields"])
            self.assertNotIn("raw_body", request_rows[1])

    def test_invalid_completion_clocks_fail_without_partial_artifacts(self):
        service = self._service()
        runner = getattr(service, "run_the_racing_api_free_proof", None)
        self.assertTrue(callable(runner), "The Racing API proof service 尚未实现")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = self._secret(root)
            registry, digest = self._registry(root)

            def clock_error():
                raise RuntimeError("clock failed")

            cases = (
                ("naive", lambda: self.FINISHED.replace(tzinfo=None), ValueError),
                (
                    "backwards",
                    lambda: self.NOW - timedelta(seconds=1),
                    ValueError,
                ),
                ("not-datetime", lambda: "2026-07-17T01:30:03Z", ValueError),
                ("exception", clock_error, RuntimeError),
            )
            for name, clock, expected_error in cases:
                with self.subTest(case=name):
                    output = root / f"invalid-clock-{name}"
                    with self.assertRaises(expected_error):
                        runner(
                            secret_env_file=secret,
                            registry_file=registry,
                            expected_registry_sha256=digest,
                            output_dir=output,
                            now=self.NOW,
                            transport=lambda **_: self._response(
                                [{"region": "Great Britain", "region_code": "gb"}]
                            ),
                            sleep=lambda _: None,
                            max_requests=1,
                            clock=clock,
                        )
                    self.assertFalse(output.exists())
                    self.assertEqual(
                        [
                            path.name
                            for path in root.iterdir()
                            if path.name.startswith(f".{output.name}.")
                        ],
                        [],
                    )

    def test_secret_registry_permission_and_budget_gates_fail_before_transport(self):
        service = self._service()
        runner = getattr(service, "run_the_racing_api_free_proof", None)
        self.assertTrue(callable(runner), "The Racing API proof service 尚未实现")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            valid_secret = self._secret(root)
            valid_registry, digest = self._registry(root)
            transport_calls = []
            wide_root = root / "wide"
            wide_root.mkdir()
            wide_secret = self._secret(wide_root, mode=0o644)

            def transport(**kwargs):
                transport_calls.append(kwargs)
                raise AssertionError("transport must not be called")

            cases = [
                {
                    "name": "secret_permissions",
                    "secret": wide_secret,
                    "registry": valid_registry,
                    "digest": digest,
                    "max_requests": 3,
                },
                {
                    "name": "registry_digest",
                    "secret": valid_secret,
                    "registry": valid_registry,
                    "digest": "0" * 64,
                    "max_requests": 3,
                },
            ]
            blocked_registry_inputs = (
                ("permission_false", {"proof_network_allowed": False}),
                ("expired", {"valid_until": "2026-07-16T00:00:00+00:00"}),
                ("wrong_host", {"host": "example.com"}),
                (
                    "unsafe_path",
                    {
                        "endpoints": [
                            {
                                "name": "regions",
                                "path": "https://example.com/private",
                            }
                        ]
                    },
                ),
            )
            for name, overrides in blocked_registry_inputs:
                registry_root = root / name
                registry_root.mkdir()
                registry, registry_digest = self._registry(
                    registry_root, **overrides
                )
                cases.append(
                    {
                        "name": name,
                        "secret": valid_secret,
                        "registry": registry,
                        "digest": registry_digest,
                        "max_requests": 3,
                    }
                )
            cases.append(
                {
                    "name": "budget",
                    "secret": valid_secret,
                    "registry": valid_registry,
                    "digest": digest,
                    "max_requests": 4,
                }
            )

            for case in cases:
                with self.subTest(case=case["name"]):
                    with self.assertRaises((ValueError, PermissionError)):
                        runner(
                            secret_env_file=case["secret"],
                            registry_file=case["registry"],
                            expected_registry_sha256=case["digest"],
                            output_dir=root / f"output-{case['name']}",
                            now=self.NOW,
                            transport=transport,
                            sleep=lambda _: None,
                            max_requests=case["max_requests"],
                        )
            self.assertEqual(transport_calls, [])

    def test_one_time_proof_permission_does_not_require_long_term_automation(self):
        service = self._service()
        runner = getattr(service, "run_the_racing_api_free_proof", None)
        self.assertTrue(callable(runner), "The Racing API proof service 尚未实现")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = self._secret(root)
            registry, digest = self._registry(root, automation_allowed=False)
            output = root / "proof-only"
            transport_calls = []

            def transport(**kwargs):
                transport_calls.append(kwargs)
                return self._response(
                    [{"region": "Great Britain", "region_code": "gb"}]
                )

            result = runner(
                secret_env_file=secret,
                registry_file=registry,
                expected_registry_sha256=digest,
                output_dir=output,
                now=self.NOW,
                transport=transport,
                sleep=lambda _: None,
                max_requests=1,
            )

            self.assertTrue(result.completed)
            self.assertEqual(result.request_count, 1)
            self.assertEqual(len(transport_calls), 1)

    def test_long_term_automation_permission_is_independent_from_one_time_proof(self):
        service = self._service()
        reader = getattr(
            service,
            "read_the_racing_api_automation_registry",
            None,
        )
        self.assertTrue(callable(reader), "TRA automation registry gate 尚未实现")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            automation_registry, automation_digest = self._registry(
                root,
                proof_network_allowed=False,
                automation_allowed=True,
            )

            registry, digest = reader(
                registry_file=automation_registry,
                expected_registry_sha256=automation_digest,
                now=self.NOW,
            )

            self.assertEqual(digest, automation_digest)
            self.assertIs(registry["automation_allowed"], True)
            self.assertIs(registry["proof_network_allowed"], False)

            proof_only_root = root / "proof-only-registry"
            proof_only_root.mkdir()
            proof_only_registry, proof_only_digest = self._registry(
                proof_only_root,
                proof_network_allowed=True,
                automation_allowed=False,
            )
            with self.assertRaises(PermissionError):
                reader(
                    registry_file=proof_only_registry,
                    expected_registry_sha256=proof_only_digest,
                    now=self.NOW,
                )

    def test_http_or_transport_failure_stops_without_retry_and_redacts_secrets(self):
        service = self._service()
        runner = getattr(service, "run_the_racing_api_free_proof", None)
        self.assertTrue(callable(runner), "The Racing API proof service 尚未实现")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = self._secret(root)
            registry, digest = self._registry(root)
            output = root / "failed-proof"
            call_count = 0

            def transport(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return self._response([{"region": "GB", "region_code": "gb"}])
                raise RuntimeError(
                    f"upstream rejected {self.USERNAME}:{self.PASSWORD}"
                )

            result = runner(
                secret_env_file=secret,
                registry_file=registry,
                expected_registry_sha256=digest,
                output_dir=output,
                now=self.NOW,
                transport=transport,
                sleep=lambda _: None,
                max_requests=3,
            )

            self.assertFalse(result.completed)
            self.assertEqual(result.request_count, 2)
            self.assertEqual(call_count, 2)
            artifact_text = "\n".join(
                path.read_text(encoding="utf-8") for path in output.iterdir()
            )
            self.assertNotIn(self.USERNAME, artifact_text)
            self.assertNotIn(self.PASSWORD, artifact_text)
            self.assertIn("[REDACTED]", artifact_text)
            self.assertIn("transport_error", artifact_text)

    def test_http_200_with_wrong_schema_is_an_incomplete_proof(self):
        service = self._service()
        runner = getattr(service, "run_the_racing_api_free_proof", None)
        self.assertTrue(callable(runner), "The Racing API proof service 尚未实现")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = self._secret(root)
            registry, digest = self._registry(root)
            output = root / "wrong-schema"

            result = runner(
                secret_env_file=secret,
                registry_file=registry,
                expected_registry_sha256=digest,
                output_dir=output,
                now=self.NOW,
                transport=lambda **_: self._response({"unexpected": []}),
                sleep=lambda _: None,
                max_requests=1,
            )

            self.assertFalse(result.completed)
            self.assertEqual(result.request_count, 1)
            request_row = json.loads(
                (output / "requests.jsonl").read_text(encoding="utf-8").strip()
            )
            self.assertEqual(request_row["error"], "schema_contract_error")

    def test_existing_output_directory_is_never_overwritten(self):
        service = self._service()
        runner = getattr(service, "run_the_racing_api_free_proof", None)
        self.assertTrue(callable(runner), "The Racing API proof service 尚未实现")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = self._secret(root)
            registry, digest = self._registry(root)
            output = root / "existing"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                runner(
                    secret_env_file=secret,
                    registry_file=registry,
                    expected_registry_sha256=digest,
                    output_dir=output,
                    now=self.NOW,
                    transport=lambda **_: self._response([]),
                    sleep=lambda _: None,
                    max_requests=3,
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_artifact_write_failure_leaves_no_partial_output_directory(self):
        service = self._service()
        runner = getattr(service, "run_the_racing_api_free_proof", None)
        self.assertTrue(callable(runner), "The Racing API proof service 尚未实现")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = self._secret(root)
            registry, digest = self._registry(root)
            output = root / "atomic-output"
            with patch.object(
                service,
                "_write_artifacts",
                side_effect=OSError("simulated artifact failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated artifact failure"):
                    runner(
                        secret_env_file=secret,
                        registry_file=registry,
                        expected_registry_sha256=digest,
                        output_dir=output,
                        now=self.NOW,
                        transport=lambda **_: self._response([]),
                        sleep=lambda _: None,
                        max_requests=1,
                    )
            self.assertFalse(output.exists())
            self.assertEqual(
                [path.name for path in root.iterdir() if "atomic-output" in path.name],
                [],
            )

    def test_management_command_is_registered_for_controlled_manual_proof(self):
        self.assertIn(
            "run_race_live_source_proof",
            get_commands(),
            "受控来源 proof 管理命令尚未注册",
        )

    def test_management_command_accepts_region_and_passes_it_to_the_runner(self):
        service = self._service()
        command_module = importlib.import_module(
            "stable.management.commands.run_race_live_source_proof"
        )
        result = service.RaceLiveSourceProofResult(
            completed=True,
            request_count=3,
            output_dir=Path("/tmp/v2-proof-output"),
        )
        with patch.object(
            command_module,
            "run_the_racing_api_free_proof",
            return_value=result,
        ) as runner:
            call_command(
                "run_race_live_source_proof",
                secret_env_file="/tmp/proof-secret.env",
                registry_file="/tmp/proof-registry.json",
                registry_sha256="a" * 64,
                output_dir="/tmp/v2-proof-output",
                max_requests=3,
                region="france",
                confirm_network_proof=True,
                stdout=StringIO(),
            )

        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.kwargs["region"], "france")

    def test_management_command_rejects_schema_v2_without_region_before_transport(
        self,
    ):
        command_module = importlib.import_module(
            "stable.management.commands.run_race_live_source_proof"
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = self._secret(root)
            registry, digest = self._registry_v2(root)
            transport_calls = []

            def transport(**kwargs):
                transport_calls.append(kwargs)
                raise AssertionError("transport must not be called")

            with patch.object(
                command_module,
                "the_racing_api_transport",
                side_effect=transport,
            ):
                with self.assertRaisesRegex(CommandError, "region"):
                    call_command(
                        "run_race_live_source_proof",
                        secret_env_file=str(secret),
                        registry_file=str(registry),
                        registry_sha256=digest,
                        output_dir=str(root / "missing-region"),
                        max_requests=3,
                        confirm_network_proof=True,
                        stdout=StringIO(),
                    )
            self.assertEqual(transport_calls, [])

    def test_sync_routes_are_exactly_allowlisted_without_expanding_proof_budget(self):
        service = self._service()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            registry, digest = self._registry(root)
            payload, actual_digest = service.read_the_racing_api_automation_registry(
                registry_file=registry,
                expected_registry_sha256=digest,
                now=self.NOW,
            )
            self.assertEqual(actual_digest, digest)
            self.assertEqual(
                payload["endpoints"][-2:],
                [
                    {
                        "name": "racecards_sync_today",
                        "path": "/v1/racecards/free?day=today&region_codes=gb&limit=500&skip=0",
                    },
                    {
                        "name": "racecards_sync_tomorrow",
                        "path": "/v1/racecards/free?day=tomorrow&region_codes=gb&limit=500&skip=0",
                    },
                ],
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "valid allowlist reached transport",
            ):
                with patch.object(
                    service,
                    "_resolve_public_addresses",
                    side_effect=RuntimeError("valid allowlist reached transport"),
                ):
                    service.the_racing_api_transport(
                        endpoint_name="racecards_sync_today",
                        url=(
                            "https://api.theracingapi.com/v1/racecards/free"
                            "?day=today&region_codes=gb&limit=500&skip=0"
                        ),
                        username="user",
                        password="password",
                        timeout_seconds=15,
                        max_response_bytes=2 * 1024 * 1024,
                        allow_redirects=False,
                    )

            with patch.object(
                service,
                "_resolve_public_addresses",
                side_effect=AssertionError(
                    "unsafe URL must be rejected before DNS resolution"
                ),
            ) as resolver:
                for unsafe_url in (
                    "https://api.theracingapi.com/v1/racecards/free?region_codes=gb&day=today&limit=500&skip=0",
                    "https://api.theracingapi.com/v1/racecards/free?day=today&region_codes=ie&limit=500&skip=0",
                    "https://api.theracingapi.com/v1/racecards/free?day=yesterday&region_codes=gb&limit=500&skip=0",
                ):
                    with self.subTest(url=unsafe_url):
                        with self.assertRaises(PermissionError):
                            service.the_racing_api_transport(
                                endpoint_name="racecards_sync_today",
                                url=unsafe_url,
                                username="user",
                                password="password",
                                timeout_seconds=15,
                                max_response_bytes=2 * 1024 * 1024,
                                allow_redirects=False,
                            )
                resolver.assert_not_called()

    def test_identity_discovery_routes_are_exactly_bound_to_region_and_day(self):
        service = self._service()
        region_codes = {
            "united_kingdom": "gb",
            "france": "fr",
            "hong_kong": "hk",
            "ireland": "ire",
            "japan": "jpn",
            "united_states": "usa",
        }
        for region_name, region_code in region_codes.items():
            for day in ("today", "tomorrow"):
                with self.subTest(region=region_name, day=day):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "valid identity route reached transport",
                    ):
                        with patch.object(
                            service,
                            "_resolve_public_addresses",
                            side_effect=RuntimeError(
                                "valid identity route reached transport"
                            ),
                        ):
                            service.the_racing_api_transport(
                                endpoint_name=(
                                    f"racecards_identity_{region_name}_{day}"
                                ),
                                url=(
                                    "https://api.theracingapi.com"
                                    "/v1/racecards/free"
                                    f"?day={day}&region_codes={region_code}"
                                    "&limit=500&skip=0"
                                ),
                                username="user",
                                password="password",
                                timeout_seconds=15,
                                max_response_bytes=2 * 1024 * 1024,
                                allow_redirects=False,
                            )

        with patch.object(
            service,
            "_resolve_public_addresses",
            side_effect=AssertionError(
                "mismatched identity route must fail before DNS"
            ),
        ) as resolver:
            for endpoint_name, url in (
                (
                    "racecards_identity_france_today",
                    "https://api.theracingapi.com/v1/racecards/free"
                    "?day=today&region_codes=gb&limit=500&skip=0",
                ),
                (
                    "racecards_identity_united_kingdom_tomorrow",
                    "https://api.theracingapi.com/v1/racecards/free"
                    "?day=today&region_codes=gb&limit=500&skip=0",
                ),
                (
                    "racecards_identity_gb_today",
                    "https://api.theracingapi.com/v1/racecards/free"
                    "?day=today&region_codes=gb&limit=500&skip=0",
                ),
            ):
                with self.subTest(endpoint_name=endpoint_name, url=url):
                    with self.assertRaises(PermissionError):
                        service.the_racing_api_transport(
                            endpoint_name=endpoint_name,
                            url=url,
                            username="user",
                            password="password",
                            timeout_seconds=15,
                            max_response_bytes=2 * 1024 * 1024,
                            allow_redirects=False,
                        )
            resolver.assert_not_called()

    def test_results_pagination_uses_one_exact_allowlisted_endpoint_name(self):
        service = self._service()
        for skip in (0, 50, 450):
            with self.subTest(skip=skip):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "valid results page reached transport",
                ):
                    with patch.object(
                        service,
                        "_resolve_public_addresses",
                        side_effect=RuntimeError(
                            "valid results page reached transport"
                        ),
                    ):
                        service.the_racing_api_transport(
                            endpoint_name="results_today",
                            url=(
                                "https://api.theracingapi.com"
                                "/v1/results/today/free"
                                f"?limit=50&skip={skip}"
                            ),
                            username="user",
                            password="password",
                            timeout_seconds=15,
                            max_response_bytes=2 * 1024 * 1024,
                            allow_redirects=False,
                        )

        for endpoint_name, skip in (
            ("results_today_skip_50", 50),
            ("results_today", 500),
        ):
            with self.subTest(endpoint_name=endpoint_name, skip=skip):
                with self.assertRaises(PermissionError):
                    service.the_racing_api_transport(
                        endpoint_name=endpoint_name,
                        url=(
                            "https://api.theracingapi.com"
                            "/v1/results/today/free"
                            f"?limit=50&skip={skip}"
                        ),
                        username="user",
                        password="password",
                        timeout_seconds=15,
                        max_response_bytes=2 * 1024 * 1024,
                        allow_redirects=False,
                    )

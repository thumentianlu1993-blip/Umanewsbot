from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from stable.test_historical_race_detail_import_packager import ArtifactBuilder


TOOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "runtime"
    / "tools"
    / "discover_uk_sportinglife_result_urls.py"
)


def _load_discovery_module():
    spec = importlib.util.spec_from_file_location(
        "discover_uk_sportinglife_result_urls_under_test",
        TOOL_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOL_PATH.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _load_tool(filename: str):
    path = TOOL_PATH.parent / filename
    spec = importlib.util.spec_from_file_location(f"{path.stem}_consumer_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOL_PATH.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class SportingLifeHistoricalUrlDiscoveryTests(SimpleTestCase):
    databases = set()

    def setUp(self):
        self.module = _load_discovery_module()

    def _write_jsonl(self, path: Path, rows: list[dict]) -> Path:
        path.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        return path

    def _write_events(self, path: Path, rows: list[dict]) -> Path:
        fieldnames = [
            "target_id",
            "target_sha256",
            "year",
            "slug",
            "original_name",
            "country_region",
            "racecourse",
            "status",
            "local_date",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def _target(
        self,
        target_id: int,
        *,
        coverage_tier: str = "historical_hard",
        country_region: str = "united_kingdom",
        reason: str = "url_discovery_pending",
    ) -> dict:
        return {
            "target_id": target_id,
            "target_sha256": f"{target_id % 10:x}" * 64,
            "country_region": country_region,
            "coverage_tier": coverage_tier,
            "reason": reason,
            "state": "unstarted",
        }

    def _event(
        self,
        target: dict,
        *,
        local_date: str,
        racecourse: str,
        original_name: str,
    ) -> dict:
        return {
            "target_id": target["target_id"],
            "target_sha256": target["target_sha256"],
            "year": int(local_date[:4]),
            "slug": f"uk-test-{target['target_id']}-{local_date[:4]}",
            "original_name": original_name,
            "country_region": target["country_region"],
            "racecourse": racecourse,
            "status": "finished",
            "local_date": local_date,
        }

    def _race(
        self,
        race_id: int,
        *,
        name: str,
        course: str,
        date: str,
        stage: str = "WEIGHEDIN",
        slug: str | None = None,
    ) -> dict:
        return {
            "race_summary_reference": {"id": race_id, "external_reference": []},
            "name": name,
            "race_slug": slug,
            "course_name": course,
            "date": date,
            "race_stage": stage,
        }

    def _meeting(
        self,
        date: str,
        course: str,
        races: list[dict],
        *,
        country: str = "GBR",
    ) -> dict:
        return {
            "meeting_summary": {
                "date": date,
                "status": "DORMANT",
                "course": {
                    "name": course,
                    "country": {"short_name": country, "long_name": country},
                },
            },
            "races": races,
        }

    def _args(
        self,
        root: Path,
        pending_path: Path,
        events_path: Path,
        *,
        allow_network: bool = True,
        coverage_tiers: tuple[str, ...] = ("historical_hard", "new_formal"),
        coverage_ledger: Path | None = None,
        plan_id: str = "detail-crawl-1998-2026-v6",
        shard_id: str = "united_kingdom-2020-sportinglife-url-discovery-01",
    ) -> Namespace:
        return Namespace(
            pending_master_targets=str(pending_path),
            events_csv=str(events_path),
            output_dir=str(root / "output"),
            coverage_tiers=list(coverage_tiers),
            coverage_ledger=(str(coverage_ledger) if coverage_ledger else None),
            allow_network=allow_network,
            timeout_seconds=10,
            sleep_seconds=0.0,
            plan_id=plan_id,
            shard_id=shard_id,
        )

    def _environment(self, root: Path, *, max_requests: int):
        cache_root = root / "output" / "sources"
        return patch.dict(
            os.environ,
            {
                "RACE_EVENT_CRAWL_MAX_REQUESTS": str(max_requests),
                "RACE_EVENT_CRAWL_REQUEST_INTERVAL_SECONDS": "0",
                "RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT": str(
                    root / "output" / "request_budget.json"
                ),
                "RACE_EVENT_CRAWL_SOURCE_CACHE_ROOT": str(cache_root),
                "RACE_EVENT_CRAWL_SOURCE_CACHE_MANIFEST": str(
                    cache_root / "source_cache_manifest.json"
                ),
                "RACE_EVENT_CRAWL_MAX_SOURCE_CACHE_BYTES": "1048576",
                "RACE_EVENT_CRAWL_MIN_FREE_DISK_BYTES": "1",
            },
            clear=False,
        )

    def _read_jsonl(self, path: Path) -> list[dict]:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _assert_file_identity(self, path: Path, identity: dict) -> None:
        self.assertEqual(identity["path"], str(path.resolve()))
        self.assertEqual(identity["size"], path.stat().st_size)
        self.assertEqual(
            identity["sha256"],
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def _file_identity(self, path: Path) -> dict:
        body = path.read_bytes()
        return {
            "path": str(path.resolve()),
            "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }

    def _urlopen(self, responses: dict[str, object], calls: list[str]):
        def open_url(request, timeout=0):
            url = getattr(request, "full_url", str(request))
            calls.append(url)
            payload = responses[url]
            return _Response(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            )

        return open_url

    def _assert_uk_adapter_consumes_discovery_outputs(
        self,
        root: Path,
        summary: dict,
        staged_path: Path,
        fragment_path: Path,
    ) -> None:
        self.assertTrue(staged_path.is_file(), "identity-validated staged events missing")
        self.assertTrue(fragment_path.is_file(), "identity-validated date fragment missing")
        output_identities = summary["output_identities"]
        self._assert_file_identity(
            staged_path,
            output_identities["staged_events"],
        )
        self._assert_file_identity(
            fragment_path,
            output_identities["date_fragment"],
        )
        with staged_path.open("r", encoding="utf-8-sig", newline="") as handle:
            staged_rows = list(csv.DictReader(handle))
        self.assertEqual(
            {int(row["target_id"]) for row in staged_rows},
            {101, 102},
        )
        for row in staged_rows:
            result_evidence = json.loads(row["source_refs"])["detail_discovery"][
                "urls"
            ]["result_url"]
            self.assertEqual(result_evidence["source_provider"], "uk_sportinglife")
            self.assertEqual(
                result_evidence["source_authority"],
                "third_party_high_access",
            )
            self.assertEqual(
                result_evidence["target_sha256"],
                row["target_sha256"],
            )

        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
        self.assertEqual(
            fragment["artifact_kind"],
            "historical_race_detail_source_fragment",
        )
        self.assertEqual(fragment["region"], "united_kingdom")
        self.assertEqual(fragment["input_identity"], summary["input_identity"])
        self.assertEqual(
            {int(row["target_id"]) for row in fragment["requests"]},
            {101, 102},
        )
        self.assertTrue(
            all(
                row["source_authority"] == "third_party_high_access"
                and row["target_sha256"] in {"1" * 64, "2" * 64}
                for row in fragment["requests"]
            )
        )

        adapter = _load_tool("prepare_uk_sportinglife_race_detail_candidates.py")
        adapter_root = root / "adapter"
        adapter_sources = adapter_root / "sources"
        adapter_sources.mkdir(parents=True)
        for race_id in (700101, 700102):
            (adapter_sources / f"source_sl_detail_{race_id}.html").write_text(
                "cached detail fixture",
                encoding="utf-8",
            )
        adapter_args = Namespace(
            events_csv=[str(staged_path)],
            output_dir=str(adapter_root),
            allow_network=False,
            limit=0,
            timeout_seconds=10,
            sleep_seconds=0,
            fail_fast=True,
        )
        with patch.object(
            adapter,
            "fetch_https",
            side_effect=AssertionError("network must remain disabled"),
        ) as fetch, patch.object(
            adapter,
            "_parse_detail_page",
            return_value=(
                [{"horse_name": "Runner"}],
                [{"horse_name": "Winner"}],
                {"race_title": "Fixture"},
            ),
        ):
            adapter_summary = adapter.prepare_candidates(adapter_args)
        self.assertEqual(adapter_summary["events"], 2)
        self.assertEqual(adapter_summary["date_pages"], 0)
        self.assertEqual(adapter_summary["detail_pages"], 2)
        fetch.assert_not_called()

    def test_filters_pending_uk_targets_and_fetches_each_unique_date_once(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hard = self._target(101)
            formal = self._target(102, coverage_tier="new_formal")
            best_effort = self._target(103, coverage_tier="historical_best_effort")
            france = self._target(104, country_region="france")
            resolved = self._target(105, reason="already_discovered")
            targets = [hard, formal, best_effort, france, resolved]
            events = [
                self._event(
                    hard,
                    local_date="2020-06-18",
                    racecourse="Ascot",
                    original_name="Gold Cup Stakes",
                ),
                self._event(
                    formal,
                    local_date="2020-06-18",
                    racecourse="Newmarket",
                    original_name="July Cup",
                ),
                self._event(
                    best_effort,
                    local_date="2020-06-18",
                    racecourse="Ascot",
                    original_name="Hardwicke Stakes",
                ),
                self._event(
                    france,
                    local_date="2020-06-18",
                    racecourse="Chantilly",
                    original_name="Prix de Diane",
                ),
                self._event(
                    resolved,
                    local_date="2020-06-18",
                    racecourse="Ascot",
                    original_name="Queen Anne Stakes",
                ),
            ]
            pending_path = self._write_jsonl(root / "pending.jsonl", targets)
            events_path = self._write_events(root / "events.csv", events)
            api_url = (
                "https://www.sportinglife.com/api/horse-racing/racing/racecards/"
                "2020-06-18"
            )
            payload = [
                self._meeting(
                    "2020-06-18",
                    "Ascot",
                    [
                        self._race(
                            700101,
                            name="Gold Cup (Group 1)",
                            course="Ascot",
                            date="2020-06-18",
                            slug="gold-cup-group-1",
                        )
                    ],
                ),
                self._meeting(
                    "2020-06-18",
                    "Newmarket",
                    [
                        self._race(
                            700102,
                            name="July Cup Stakes (Group 1)",
                            course="Newmarket",
                            date="2020-06-18",
                            slug="sponsor-name-that-can-change",
                        )
                    ],
                ),
            ]
            calls: list[str] = []

            with self._environment(root, max_requests=1), patch.object(
                self.module,
                "urlopen",
                side_effect=self._urlopen({api_url: payload}, calls),
            ):
                summary = self.module.discover_urls(
                    self._args(root, pending_path, events_path)
                )

            discovered = self._read_jsonl(
                root / "output" / "sportinglife_result_urls.jsonl"
            )
            self.assertEqual(summary["selected_targets"], 2)
            self.assertEqual(summary["discovered_count"], 2)
            self.assertEqual(calls, [api_url])
            self.assertEqual({row["target_id"] for row in discovered}, {101, 102})
            by_target = {row["target_id"]: row for row in discovered}
            self.assertEqual(by_target[101]["race_id"], 700101)
            self.assertIn("/700101/", by_target[101]["result_url"])
            self.assertTrue(by_target[101]["result_url"].startswith("https://"))
            self.assertEqual(by_target[102]["race_id"], 700102)
            self.assertIn("/700102/", by_target[102]["result_url"])
            self.assertNotIn("slug_identity", by_target[102])
            staged_path = root / "output" / "staged-events.csv"
            fragment_path = root / "output" / "sportinglife_date_fragment.json"
            with self.subTest(contract="discovery_status"):
                self.assertTrue(
                    all(
                        row.get("discovery_status") == "url_discovered"
                        and "accounting_status" not in row
                        for row in discovered
                    )
                )
            with self.subTest(contract="staged_events"):
                self.assertTrue(staged_path.is_file())
            with self.subTest(contract="date_fragment"):
                self.assertTrue(fragment_path.is_file())
            with self.subTest(contract="uk_adapter_no_network"):
                self._assert_uk_adapter_consumes_discovery_outputs(
                    root,
                    summary,
                    staged_path,
                    fragment_path,
                )

    def test_date_fragment_binds_controlled_plan_and_shard_for_bundle_packager(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_id = "detail-crawl-1998-2026-v6"
            shard_id = "united_kingdom-2024-sportinglife-01"
            target_id = 701
            target_sha = f"{target_id:064x}"
            master = {
                "actionability": "pending",
                "local_date": "2024-01-02",
                "original_shard_id": shard_id,
                "plan_id": plan_id,
                "reason": "url_discovery_pending",
                "region": "united_kingdom",
                "schema_version": "2.0",
                "slug": "united_kingdom-gold-cup-2024",
                "state": "unstarted",
                "target_id": str(target_id),
                "target_sha256": target_sha,
                "year": 2024,
            }
            coverage = {
                "country_region": "united_kingdom",
                "coverage_tier": "historical_hard",
                "target_id": target_id,
                "target_sha256": target_sha,
                "year": 2024,
            }
            event = {
                "target_id": target_id,
                "target_sha256": target_sha,
                "year": 2024,
                "slug": master["slug"],
                "original_name": "Gold Cup",
                "country_region": "united_kingdom",
                "racecourse": "Ascot",
                "status": "finished",
                "local_date": "2024-01-02",
            }
            pending_path = self._write_jsonl(root / "master_targets.jsonl", [master])
            coverage_path = self._write_jsonl(
                root / "coverage_ledger.jsonl",
                [coverage],
            )
            events_path = self._write_events(root / "events.csv", [event])
            api_url = (
                "https://www.sportinglife.com/api/horse-racing/racing/racecards/"
                "2024-01-02"
            )
            payload = [
                self._meeting(
                    "2024-01-02",
                    "Ascot",
                    [
                        self._race(
                            900701,
                            name="Gold Cup (Group 1)",
                            course="Ascot",
                            date="2024-01-02",
                        )
                    ],
                )
            ]
            calls: list[str] = []
            with self._environment(root, max_requests=1), patch.object(
                self.module,
                "urlopen",
                side_effect=self._urlopen({api_url: payload}, calls),
            ):
                summary = self.module.discover_urls(
                    self._args(
                        root,
                        pending_path,
                        events_path,
                        coverage_ledger=coverage_path,
                        plan_id=plan_id,
                        shard_id=shard_id,
                    )
                )

            fragment_path = root / "output" / "sportinglife_date_fragment.json"
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            self.assertEqual(fragment["plan_id"], plan_id)
            self.assertEqual(fragment["shard_id"], shard_id)
            self.assertEqual(summary["input_identity"]["plan_id"], plan_id)
            self.assertEqual(summary["input_identity"]["shard_id"], shard_id)
            self.assertEqual(fragment["input_identity"], summary["input_identity"])
            self.assertEqual(calls, [api_url])

            builder = ArtifactBuilder(root / "bundle-contract")
            builder.add_gap(target_id, 2024)
            builder.targets[0]["country_region"] = "united_kingdom"
            builder.build()

            old_shard_id = "japan-2024-official-01"
            old_run_dir = builder.v6 / "run" / old_shard_id
            run_dir = builder.v6 / "run" / shard_id
            old_run_dir.rename(run_dir)
            old_fragment_path = (
                builder.v6 / "source_fragments" / f"{old_shard_id}.json"
            )
            old_fragment_path.unlink()
            contract_fragment_path = (
                builder.v6 / "source_fragments" / f"{shard_id}.json"
            )
            contract_fragment_path.write_bytes(fragment_path.read_bytes())

            package_path = run_dir / "package-manifest.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["staged_event_identity"] = self._file_identity(
                run_dir / "staged-events.csv"
            )
            package["candidate_identity"] = self._file_identity(
                run_dir / "validated-candidates.jsonl"
            )
            package["source_cache_manifest_identity"] = self._file_identity(
                run_dir / "source-cache" / "source_cache_manifest.json"
            )
            package_path.write_text(
                json.dumps(package, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            request_log_path = (
                builder.v6
                / "carry_forward/source_host_audit/results.example.test.requests.jsonl"
            )
            request_rows = self._read_jsonl(request_log_path)
            for row in request_rows:
                if row.get("shard_id") == old_shard_id:
                    row["shard_id"] = shard_id
                    row["host"] = "www.sportinglife.com"
                    row["url"] = fragment["requests"][0]["source_url"]
            self._write_jsonl(request_log_path, request_rows)
            builder._write_v6_manifest(smoke_count=1)

            packager = _load_tool(
                "package_historical_race_detail_import_candidates.py"
            )
            bundle = packager.package_source_bundle(
                builder.v6,
                builder.v9,
                builder.due,
                root / "bundle-output",
                expected_package_count=39,
                expected_scope_count=1,
                expected_input_record_count=0,
                expected_input_gap_count=1,
                expected_historical_record_count=0,
                expected_historical_gap_count=1,
                expected_historical_chunk_count=0,
                expected_new_record_count=0,
                expected_new_gap_count=0,
                expected_new_chunk_count=0,
                expected_runner_count=0,
                expected_result_count=0,
            )
            self.assertEqual(bundle["scope_count"], 1)
            self.assertEqual(bundle["gap_count"], 1)

    def test_joins_real_master_shape_to_independent_coverage_ledger_fail_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            definitions = [
                (601, "united_kingdom", "historical_hard", "Ascot", "Gold Cup"),
                (602, "united_kingdom", "new_formal", "Newmarket", "July Cup"),
                (
                    603,
                    "united_kingdom",
                    "historical_best_effort",
                    "Ascot",
                    "Hardwicke Stakes",
                ),
                (604, "france", "historical_hard", "Chantilly", "Prix de Diane"),
            ]
            master_rows = []
            coverage_rows = []
            events = []
            for target_id, region, tier, course, name in definitions:
                target_sha = f"{target_id % 10:x}" * 64
                master_rows.append(
                    {
                        "actionability": "pending",
                        "local_date": "2020-06-18",
                        "original_shard_id": f"{region}-2020-01",
                        "plan_id": "detail-crawl-1998-2026-v6",
                        "reason": "url_discovery_pending",
                        "region": region,
                        "schema_version": "2.0",
                        "slug": f"real-shape-{target_id}",
                        "state": "unstarted",
                        "target_id": str(target_id),
                        "target_sha256": target_sha,
                        "year": 2020,
                    }
                )
                coverage_rows.append(
                    {
                        "accounting_status": "blocked",
                        "country_region": region,
                        "coverage_tier": tier,
                        "policy_version": "historical-race-coverage-v1",
                        "target_id": target_id,
                        "target_sha256": target_sha,
                        "year": 2020,
                    }
                )
                events.append(
                    {
                        "target_id": target_id,
                        "target_sha256": target_sha,
                        "year": 2020,
                        "slug": f"real-shape-{target_id}",
                        "original_name": name,
                        "country_region": region,
                        "racecourse": course,
                        "status": "finished",
                        "local_date": "2020-06-18",
                    }
                )

            pending_path = self._write_jsonl(root / "master_targets.jsonl", master_rows)
            coverage_path = self._write_jsonl(
                root / "coverage_ledger.jsonl",
                coverage_rows,
            )
            events_path = self._write_events(root / "events.csv", events)
            api_url = (
                "https://www.sportinglife.com/api/horse-racing/racing/racecards/"
                "2020-06-18"
            )
            payload = [
                self._meeting(
                    "2020-06-18",
                    "Ascot",
                    [
                        self._race(
                            800601,
                            name="Gold Cup (Group 1)",
                            course="Ascot",
                            date="2020-06-18",
                        )
                    ],
                ),
                self._meeting(
                    "2020-06-18",
                    "Newmarket",
                    [
                        self._race(
                            800602,
                            name="July Cup Stakes (Group 1)",
                            course="Newmarket",
                            date="2020-06-18",
                        )
                    ],
                ),
            ]
            calls: list[str] = []

            with self._environment(root, max_requests=1), patch.object(
                self.module,
                "urlopen",
                side_effect=self._urlopen({api_url: payload}, calls),
            ):
                summary = self.module.discover_urls(
                    self._args(
                        root,
                        pending_path,
                        events_path,
                        coverage_ledger=coverage_path,
                    )
                )

            self.assertEqual(summary["selected_targets"], 2)
            self.assertEqual(
                {
                    row["target_id"]
                    for row in self._read_jsonl(
                        root / "output" / "sportinglife_result_urls.jsonl"
                    )
                },
                {601, 602},
            )
            self.assertEqual(calls, [api_url])

            invalid_cases = {
                "missing": coverage_rows[1:],
                "target SHA mismatch": [
                    {**coverage_rows[0], "target_sha256": "f" * 64},
                    *coverage_rows[1:],
                ],
                "region mismatch": [
                    {**coverage_rows[0], "country_region": "france"},
                    *coverage_rows[1:],
                ],
            }
            for label, invalid_coverage in invalid_cases.items():
                case_root = root / label.replace(" ", "-")
                case_root.mkdir()
                case_pending = self._write_jsonl(
                    case_root / "master_targets.jsonl",
                    master_rows,
                )
                case_events = self._write_events(case_root / "events.csv", events)
                case_coverage = self._write_jsonl(
                    case_root / "coverage_ledger.jsonl",
                    invalid_coverage,
                )
                case_calls: list[str] = []
                with self._environment(case_root, max_requests=1), patch.object(
                    self.module,
                    "urlopen",
                    side_effect=lambda *args, **kwargs: case_calls.append("called"),
                ):
                    with self.subTest(label=label), self.assertRaisesRegex(
                        RuntimeError,
                        label,
                    ):
                        self.module.discover_urls(
                            self._args(
                                case_root,
                                case_pending,
                                case_events,
                                coverage_ledger=case_coverage,
                            )
                        )
                self.assertEqual(case_calls, [])

    def test_master_event_slug_year_and_local_date_drift_fail_before_network(self):
        base_master = {
            "actionability": "pending",
            "local_date": "2020-06-18",
            "original_shard_id": "united_kingdom-2020-01",
            "plan_id": "detail-crawl-1998-2026-v6",
            "reason": "url_discovery_pending",
            "region": "united_kingdom",
            "schema_version": "2.0",
            "slug": "united_kingdom-gold-cup-2020",
            "state": "unstarted",
            "target_id": "701",
            "target_sha256": "7" * 64,
            "year": 2020,
        }
        coverage = {
            "country_region": "united_kingdom",
            "coverage_tier": "historical_hard",
            "target_id": 701,
            "target_sha256": "7" * 64,
            "year": 2020,
        }
        base_event = {
            "target_id": 701,
            "target_sha256": "7" * 64,
            "year": 2020,
            "slug": "united_kingdom-gold-cup-2020",
            "original_name": "Gold Cup",
            "country_region": "united_kingdom",
            "racecourse": "Ascot",
            "status": "finished",
            "local_date": "2020-06-18",
        }
        drift_cases = {
            "slug mismatch": {**base_event, "slug": "wrong-slug-2020"},
            "year mismatch": {**base_event, "year": 2021},
            "local_date mismatch": {**base_event, "local_date": "2020-06-19"},
        }
        for label, event in drift_cases.items():
            with self.subTest(label=label), TemporaryDirectory() as tmp:
                root = Path(tmp)
                pending_path = self._write_jsonl(
                    root / "master_targets.jsonl",
                    [base_master],
                )
                coverage_path = self._write_jsonl(
                    root / "coverage_ledger.jsonl",
                    [coverage],
                )
                events_path = self._write_events(root / "events.csv", [event])
                calls: list[str] = []
                with self._environment(root, max_requests=1), patch.object(
                    self.module,
                    "urlopen",
                    side_effect=lambda *args, **kwargs: calls.append("called"),
                ):
                    with self.assertRaisesRegex(RuntimeError, label):
                        self.module.discover_urls(
                            self._args(
                                root,
                                pending_path,
                                events_path,
                                coverage_ledger=coverage_path,
                            )
                        )
                self.assertEqual(calls, [])

    def test_records_ambiguous_missing_nonterminal_and_drift_as_gaps(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [
                (201, "2020-01-01", "Ascot", "Gold Cup"),
                (202, "2020-01-02", "Ascot", "No Such Stakes"),
                (203, "2020-01-03", "Kempton", "Adonis Juvenile Hurdle"),
                (204, "2020-01-04", "Sandown", "Bet365 Gold Cup"),
                (205, "2020-01-05", "Newmarket", "July Cup"),
            ]
            targets = [self._target(target_id) for target_id, *_ in cases]
            events = [
                self._event(
                    target,
                    local_date=date,
                    racecourse=course,
                    original_name=name,
                )
                for target, (_, date, course, name) in zip(targets, cases)
            ]
            pending_path = self._write_jsonl(root / "pending.jsonl", targets)
            events_path = self._write_events(root / "events.csv", events)
            base = "https://www.sportinglife.com/api/horse-racing/racing/racecards/"
            responses = {
                base + "2020-01-01": [
                    self._meeting(
                        "2020-01-01",
                        "Ascot",
                        [
                            self._race(1, name="Gold Cup", course="Ascot", date="2020-01-01"),
                            self._race(2, name="Gold Cup", course="Ascot", date="2020-01-01"),
                        ],
                    )
                ],
                base + "2020-01-02": [
                    self._meeting(
                        "2020-01-02",
                        "Ascot",
                        [self._race(3, name="Other Race", course="Ascot", date="2020-01-02")],
                    )
                ],
                base + "2020-01-03": [
                    self._meeting(
                        "2020-01-03",
                        "Kempton",
                        [
                            self._race(
                                4,
                                name="Adonis Juvenile Hurdle",
                                course="Kempton",
                                date="2020-01-03",
                                stage="DECLARED",
                            )
                        ],
                    )
                ],
                base + "2020-01-04": [
                    self._meeting(
                        "2020-01-04",
                        "Sandown",
                        [
                            self._race(
                                5,
                                name="Bet365 Gold Cup",
                                course="Sandown",
                                date="2020-01-05",
                            )
                        ],
                    )
                ],
                base + "2020-01-05": [
                    self._meeting(
                        "2020-01-05",
                        "Newmarket",
                        [self._race(6, name="July Cup", course="Newmarket", date="2020-01-05")],
                        country="FRA",
                    )
                ],
            }
            calls: list[str] = []

            with self._environment(root, max_requests=5), patch.object(
                self.module,
                "urlopen",
                side_effect=self._urlopen(responses, calls),
            ):
                summary = self.module.discover_urls(
                    self._args(root, pending_path, events_path)
                )

            gaps = self._read_jsonl(
                root / "output" / "sportinglife_url_discovery_gaps.jsonl"
            )
            discovered = self._read_jsonl(
                root / "output" / "sportinglife_result_urls.jsonl"
            )
            self.assertEqual(discovered, [])
            self.assertEqual(summary["gap_count"], 5)
            self.assertEqual(
                {row["target_id"]: row["gap_reason"] for row in gaps},
                {
                    201: "ambiguous_match",
                    202: "no_match",
                    203: "non_terminal_race",
                    204: "date_drift",
                    205: "region_drift",
                },
            )
            self.assertTrue(all(row["accounting_status"] == "gap" for row in gaps))

    def test_target_sha_mismatch_fails_before_network_or_outputs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = self._target(301)
            event = self._event(
                target,
                local_date="2020-06-18",
                racecourse="Ascot",
                original_name="Gold Cup",
            )
            event["target_sha256"] = "f" * 64
            pending_path = self._write_jsonl(root / "pending.jsonl", [target])
            events_path = self._write_events(root / "events.csv", [event])
            calls: list[str] = []

            with self._environment(root, max_requests=1), patch.object(
                self.module,
                "urlopen",
                side_effect=lambda *args, **kwargs: calls.append("called"),
            ):
                with self.assertRaisesRegex(RuntimeError, r"target SHA.*mismatch"):
                    self.module.discover_urls(
                        self._args(root, pending_path, events_path)
                    )

            self.assertEqual(calls, [])
            self.assertFalse(
                (root / "output" / "sportinglife_result_urls.jsonl").exists()
            )

    def test_cached_response_sha_is_recorded_and_tampering_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = self._target(401)
            event = self._event(
                target,
                local_date="2020-06-18",
                racecourse="Ascot",
                original_name="Gold Cup",
            )
            pending_path = self._write_jsonl(root / "pending.jsonl", [target])
            events_path = self._write_events(root / "events.csv", [event])
            api_url = (
                "https://www.sportinglife.com/api/horse-racing/racing/racecards/"
                "2020-06-18"
            )
            payload = [
                self._meeting(
                    "2020-06-18",
                    "Ascot",
                    [self._race(9, name="Gold Cup", course="Ascot", date="2020-06-18")],
                )
            ]
            response_body = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            calls: list[str] = []

            with self._environment(root, max_requests=1), patch.object(
                self.module,
                "urlopen",
                side_effect=self._urlopen({api_url: payload}, calls),
            ):
                self.module.discover_urls(self._args(root, pending_path, events_path))

            row = self._read_jsonl(
                root / "output" / "sportinglife_result_urls.jsonl"
            )[0]
            self.assertEqual(row["response_sha256"], hashlib.sha256(response_body).hexdigest())
            manifest_path = root / "output" / "sources" / "source_cache_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["files"]), 1)
            relative_path = next(iter(manifest["files"]))
            cache_path = manifest_path.parent / relative_path
            cache_path.write_bytes(cache_path.read_bytes() + b"\n")

            with self._environment(root, max_requests=1):
                with self.assertRaisesRegex(RuntimeError, r"cache.*identity"):
                    self.module.discover_urls(
                        self._args(
                            root,
                            pending_path,
                            events_path,
                            allow_network=False,
                        )
                    )

            self.assertEqual(calls, [api_url])

    def test_request_budget_configuration_drift_fails_closed_on_resume(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = self._target(501)
            event = self._event(
                target,
                local_date="2020-06-18",
                racecourse="Ascot",
                original_name="Gold Cup",
            )
            pending_path = self._write_jsonl(root / "pending.jsonl", [target])
            events_path = self._write_events(root / "events.csv", [event])
            api_url = (
                "https://www.sportinglife.com/api/horse-racing/racing/racecards/"
                "2020-06-18"
            )
            payload = [
                self._meeting(
                    "2020-06-18",
                    "Ascot",
                    [self._race(10, name="Gold Cup", course="Ascot", date="2020-06-18")],
                )
            ]
            calls: list[str] = []

            with self._environment(root, max_requests=1), patch.object(
                self.module,
                "urlopen",
                side_effect=self._urlopen({api_url: payload}, calls),
            ):
                self.module.discover_urls(self._args(root, pending_path, events_path))

            with self._environment(root, max_requests=2):
                with self.assertRaisesRegex(RuntimeError, r"request budget.*drift"):
                    self.module.discover_urls(
                        self._args(
                            root,
                            pending_path,
                            events_path,
                            allow_network=False,
                        )
                    )

            self.assertEqual(calls, [api_url])

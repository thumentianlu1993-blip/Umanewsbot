from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    path = ROOT / "tmp" / name
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def identity(path):
    body = path.read_bytes()
    return {"path": path.name, "sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}


class KnownCalendarShardRunnerTests(SimpleTestCase):
    def setUp(self):
        self.module = load_script("run_known_calendar_shards.py")

    def test_parse_artifact_reuse_requires_exact_selection_catalog_and_tool_identity(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            current_selection = root / "selection.json"
            current_catalog = root / "catalog.json"
            current_tool = root / "parser.py"
            current_selection.write_text('{"targets":[1]}')
            current_catalog.write_text('{"sources":[1]}')
            current_tool.write_text("VERSION = 1\n")
            parse_root = root / "parse"
            parse_root.mkdir()
            summary = parse_root / "summary.json"
            summary.write_text('{"scope_count":1}')
            (parse_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "selection": identity(current_selection),
                        "source_catalog": identity(current_catalog),
                    }
                )
            )
            (parse_root / "execution-identity.json").write_text(
                json.dumps({"tools": {"parser.py": identity(current_tool)}})
            )
            cache_summary = root / "cache-summary.json"
            cache_summary.write_text('{"failure_count":0}')

            self.assertTrue(
                self.module.parse_artifact_is_reusable(
                    summary_path=summary,
                    cache_summary_path=cache_summary,
                    selection_path=current_selection,
                    catalog_path=current_catalog,
                    tool_paths={"parser.py": current_tool},
                )
            )

            current_selection.write_text('{"targets":[2]}')
            self.assertFalse(
                self.module.parse_artifact_is_reusable(
                    summary_path=summary,
                    cache_summary_path=cache_summary,
                    selection_path=current_selection,
                    catalog_path=current_catalog,
                    tool_paths={"parser.py": current_tool},
                )
            )
            current_selection.write_text('{"targets":[1]}')
            current_catalog.write_text('{"sources":[2]}')
            self.assertFalse(
                self.module.parse_artifact_is_reusable(
                    summary_path=summary,
                    cache_summary_path=cache_summary,
                    selection_path=current_selection,
                    catalog_path=current_catalog,
                    tool_paths={"parser.py": current_tool},
                )
            )
            current_catalog.write_text('{"sources":[1]}')
            current_tool.write_text("VERSION = 2\n")
            self.assertFalse(
                self.module.parse_artifact_is_reusable(
                    summary_path=summary,
                    cache_summary_path=cache_summary,
                    selection_path=current_selection,
                    catalog_path=current_catalog,
                    tool_paths={"parser.py": current_tool},
                )
            )

    def test_toba_fetch_uses_guarded_docker_network_stage(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            shard = root / "united_states-2024-01"
            write_jsonl(
                shard / "requests" / "provider_rows.jsonl",
                [
                    {
                        "adapter_key": "toba",
                        "target_id": 1,
                        "urls": {
                            "calendar_source": {
                                "url": "https://toba.org/graded-stakes/2024-races/"
                            }
                        },
                    }
                ],
            )
            commands = []

            with patch.object(self.module, "RUNTIME_HOST", root), patch.object(
                self.module, "RUNTIME_CONTAINER", Path("/runs")
            ), patch.object(
                self.module, "run", side_effect=lambda command, cwd: commands.append(command)
            ), patch.object(
                self.module, "reuse_existing_complete_cache", return_value=False
            ), patch.object(
                self.module, "finish_cache_retry"
            ):
                self.module.cache_toba(worktree=ROOT, shard_root=shard, year=2024)

        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertNotIn("curl", command)
        self.assertIn("HISTORICAL_RACE_BACKFILL_ENABLED=true", command)
        self.assertIn("HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=true", command)
        self.assertTrue(any(value.startswith("RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT=") for value in command))
        self.assertTrue(any(value.startswith("RACE_EVENT_CRAWL_HOST_INTERVAL_ARTIFACT=") for value in command))
        self.assertIn("RACE_EVENT_CRAWL_MIN_FREE_DISK_BYTES=5368709120", command)
        self.assertIn("runtime/tools/cache_historical_race_date_sources.py", command)
        self.assertIn("--allow-network", command)

    def _assert_partial_cache_retry(self, cache_method, *, urls, year):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "runs"
            shard = run_root / f"fixture-{year}-01"
            provider_path = shard / "requests" / "provider_rows.jsonl"
            write_jsonl(
                provider_path,
                [
                    {
                        "adapter_key": "toba" if "toba.org" in url else "jra",
                        "target_id": index,
                        "urls": {"calendar_source": {"url": url}},
                    }
                    for index, url in enumerate(urls, start=1)
                ],
            )
            cache = shard / "cache"
            cache.mkdir()
            initial_rows = [
                {"source_url": urls[0], "status": "succeeded"},
                *[
                    {"source_url": url, "status": "failed", "error": "timeout"}
                    for url in urls[1:]
                ],
            ] if len(urls) > 1 else [
                {"source_url": urls[0], "status": "failed", "error": "timeout"}
            ]
            write_jsonl(cache / "request-ledger.jsonl", initial_rows)
            (cache / "summary.json").write_text(
                json.dumps(
                    {
                        "request_count": len(initial_rows),
                        "success_count": sum(row["status"] == "succeeded" for row in initial_rows),
                        "failure_count": sum(row["status"] == "failed" for row in initial_rows),
                    }
                )
            )
            commands = []

            def fake_run(command, *, cwd):
                commands.append(command)
                provider_container = command[command.index("--provider-jsonl") + 1]
                retry_path = run_root / Path(provider_container).relative_to("/runs")
                retry_rows = read_jsonl(retry_path)
                self.assertEqual(
                    [row["urls"]["calendar_source"]["url"] for row in retry_rows],
                    urls[1:] if len(urls) > 1 else urls,
                )
                write_jsonl(
                    cache / "request-ledger.jsonl",
                    [
                        {
                            "source_url": row["urls"]["calendar_source"]["url"],
                            "status": "succeeded",
                        }
                        for row in retry_rows
                    ],
                )
                (cache / "summary.json").write_text(
                    json.dumps(
                        {
                            "request_count": len(retry_rows),
                            "success_count": len(retry_rows),
                            "failure_count": 0,
                        }
                    )
                )

            with patch.object(self.module, "RUNTIME_HOST", run_root), patch.object(
                self.module, "RUNTIME_CONTAINER", Path("/runs")
            ), patch.object(self.module, "run", side_effect=fake_run):
                kwargs = {"worktree": ROOT, "shard_root": shard}
                if cache_method.__name__ == "cache_toba":
                    kwargs["year"] = year
                cache_method(**kwargs)

            final_rows = read_jsonl(cache / "request-ledger.jsonl")
            attempts = read_jsonl(cache / "request-attempt-ledger.jsonl")
            attempt_summaries = read_jsonl(cache / "request-attempt-summaries.jsonl")

        self.assertEqual(len(commands), 1)
        self.assertEqual({row["source_url"] for row in final_rows}, set(urls))
        self.assertTrue(all(row["status"] == "succeeded" for row in final_rows))
        self.assertEqual(len(attempts), len(initial_rows) + len(urls[1:] or urls))
        self.assertEqual([row["phase"] for row in attempt_summaries], ["before_retry", "retry"])

    def test_standard_cache_retries_only_failed_urls_and_preserves_attempt_audit(self):
        self._assert_partial_cache_retry(
            self.module.cache_standard,
            urls=[
                "https://www.jra.go.jp/a.html",
                "https://www.jra.go.jp/b.html",
            ],
            year=2020,
        )

    def test_toba_cache_retries_failed_url_and_preserves_attempt_audit(self):
        self._assert_partial_cache_retry(
            self.module.cache_toba,
            urls=["https://toba.org/graded-stakes/2024-races/"],
            year=2024,
        )

    def test_parse_rebuilds_successful_artifact_without_current_execution_identity(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            shard = root / "japan-2020-01"
            bootstrap = shard / "bootstrap"
            cache = shard / "cache"
            output = shard / "parse"
            bootstrap.mkdir(parents=True)
            cache.mkdir()
            output.mkdir()
            (bootstrap / "selection_snapshot.json").write_text('{"selection":1}')
            (bootstrap / "source_catalog.json").write_text('{"catalog":1}')
            (cache / "summary.json").write_text('{"failure_count":0}')
            (output / "summary.json").write_text('{"scope_count":1}')
            commands = []

            def fake_run(command, *, cwd):
                commands.append(command)
                rebuilt = shard / "parse"
                rebuilt.mkdir()
                (rebuilt / "summary.json").write_text('{"scope_count":1}')

            with patch.object(self.module, "RUNTIME_HOST", root), patch.object(
                self.module, "RUNTIME_CONTAINER", Path("/runs")
            ), patch.object(self.module, "run", side_effect=fake_run):
                result = self.module.parse(
                    worktree=ROOT,
                    shard_root=shard,
                    region="japan",
                    year=2020,
                )

            archived = sorted(shard.glob("parse-before-identity-rebuild-*"))

        self.assertEqual(result["scope_count"], 1)
        self.assertEqual(len(commands), 1)
        self.assertEqual(len(archived), 1)


class CurrentYearSourceOverrideRunnerTests(SimpleTestCase):
    def setUp(self):
        self.module = load_script("run_current_year_source_override.py")

    def test_classified_reuse_rejects_old_cutoff_identity(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = root / "selection_snapshot.json"
            date_matches = root / "date_matches.jsonl"
            gaps = root / "gaps.jsonl"
            selection.write_text("{}")
            date_matches.write_text("")
            gaps.write_text("")
            classified = root / "classified-v2"
            classified.mkdir()
            (classified / "summary.json").write_text(
                '{"cutoff_date":"2026-07-14"}'
            )
            (classified / "manifest.json").write_text(
                json.dumps(
                    {
                        "cutoff_date": "2026-07-14",
                        "inputs": {
                            "selection": identity(selection),
                            "date_matches": identity(date_matches),
                            "gaps": identity(gaps),
                        },
                        "apply_artifacts": {},
                    }
                )
            )
            (classified / "apply_descriptor.json").write_text(
                json.dumps(
                    {
                        "cutoff_date": "2026-07-14",
                        "apply_artifacts": {},
                    }
                )
            )

            reusable = self.module._classified_is_reusable(
                classified,
                selection=selection,
                date_matches=date_matches,
                gaps=gaps,
            )

        self.assertFalse(reusable)

    def test_partial_cache_retries_failed_url_and_preserves_attempt_audit(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "runs"
            shard_id = "france-2026-01"
            shard = run_root / shard_id
            (shard / "bootstrap-v2").mkdir(parents=True)
            (shard / "requests-v2").mkdir()
            cache = shard / "cache-v2"
            cache.mkdir()
            (shard / "bootstrap-v2" / "selection_snapshot.json").write_text("{}")
            (shard / "bootstrap-v2" / "source_catalog.json").write_text("{}")
            urls = ["https://www.france-galop.com/a.pdf", "https://www.france-galop.com/b.pdf"]
            write_jsonl(
                shard / "requests-v2" / "provider_rows.jsonl",
                [
                    {
                        "adapter_key": "france_galop",
                        "target_id": index,
                        "urls": {"calendar_source": {"url": url}},
                    }
                    for index, url in enumerate(urls, start=1)
                ],
            )
            write_jsonl(
                cache / "request-ledger.jsonl",
                [
                    {"source_url": urls[0], "status": "succeeded"},
                    {"source_url": urls[1], "status": "failed", "error": "timeout"},
                ],
            )
            (cache / "summary.json").write_text(
                json.dumps({"request_count": 2, "success_count": 1, "failure_count": 1})
            )
            commands = []

            def fake_run(command, *, cwd):
                commands.append(command)
                if any(
                    value.endswith("cache_historical_race_date_sources.py")
                    for value in command
                ):
                    provider_path = Path(
                        str(command[command.index("--provider-jsonl") + 1]).replace(
                            "/runs", str(run_root)
                        )
                    )
                    retry_rows = [
                        json.loads(line)
                        for line in provider_path.read_text().splitlines()
                        if line.strip()
                    ]
                    self.assertEqual(
                        [row["urls"]["calendar_source"]["url"] for row in retry_rows],
                        [urls[1]],
                    )
                    write_jsonl(
                        cache / "request-ledger.jsonl",
                        [{"source_url": urls[1], "status": "succeeded"}],
                    )
                    (cache / "summary.json").write_text(
                        json.dumps({"request_count": 1, "success_count": 1, "failure_count": 0})
                    )
                elif any(
                    value.endswith("prepare_historical_race_calendar_inputs.py")
                    for value in command
                ):
                    output = shard / "parse-v2"
                    output.mkdir()
                    (output / "summary.json").write_text('{"scope_count":2}')
                    (output / "manifest.json").write_text("{}")
                    write_jsonl(
                        output / "date_matches.jsonl",
                        [
                            {
                                "target_id": 1,
                                "local_date": "2026-01-01",
                                "country_region": "france",
                            },
                            {
                                "target_id": 2,
                                "local_date": "2026-08-01",
                                "country_region": "france",
                            },
                        ],
                    )
                    write_jsonl(output / "gaps.jsonl", [])
                elif any(
                    value.endswith("classify_current_year_race_due_checks.py")
                    for value in command
                ):
                    classified = shard / "classified-v2"
                    classified.mkdir()
                    (classified / "summary.json").write_text('{"scope_count":2}')
                    (classified / "manifest.json").write_text("{}")
                    (classified / "apply_descriptor.json").write_text(
                        '{"apply_artifacts":{"events_france":{}}}'
                    )

            argv = [
                "run_current_year_source_override.py",
                "--worktree",
                str(ROOT),
                "--plan-root",
                str(root / "plan"),
                "--run-root",
                str(run_root),
                "--shard-id",
                shard_id,
                "--region",
                "france",
            ]
            with patch.object(self.module, "RUNTIME_HOST", run_root), patch.object(
                self.module, "RUNTIME_CONTAINER", Path("/runs")
            ), patch.object(self.module, "run", side_effect=fake_run), patch.object(
                sys, "argv", argv
            ):
                self.module.main()

            final_rows = [
                json.loads(line)
                for line in (cache / "request-ledger.jsonl").read_text().splitlines()
                if line.strip()
            ]
            attempts = [
                json.loads(line)
                for line in (cache / "request-attempt-ledger.jsonl").read_text().splitlines()
                if line.strip()
            ]

        self.assertEqual({row["source_url"] for row in final_rows}, set(urls))
        self.assertTrue(all(row["status"] == "succeeded" for row in final_rows))
        self.assertEqual(len(attempts), 3)
        self.assertEqual(attempts[1]["status"], "failed")
        self.assertTrue(
            any(
                any(value.endswith("cache_historical_race_date_sources.py") for value in row)
                for row in commands
            )
        )

    def test_hong_kong_runner_binds_same_cutoff_and_request_manifest_to_both_stages(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "runs"
            shard_id = "hong-kong-2026-01"
            shard = run_root / shard_id
            bootstrap = shard / "bootstrap-v2"
            bootstrap.mkdir(parents=True)
            (bootstrap / "selection_snapshot.json").write_text("{}")
            (bootstrap / "source_catalog.json").write_text("{}")
            commands = []

            def fake_run(command, *, cwd):
                commands.append(command)
                if any(
                    value.endswith("build_historical_race_calendar_requests.py")
                    for value in command
                ):
                    requests = shard / "requests-v2"
                    requests.mkdir()
                    (requests / "provider_rows.jsonl").write_text("")
                    (requests / "manifest.json").write_text("{}")
                elif any(
                    value.endswith("prepare_historical_race_calendar_inputs.py")
                    for value in command
                ):
                    output = shard / "parse-v2"
                    output.mkdir()
                    (output / "summary.json").write_text('{"scope_count":1}')
                    write_jsonl(
                        output / "date_matches.jsonl",
                        [
                            {
                                "target_id": 1,
                                "local_date": "2026-01-07",
                                "country_region": "hong_kong",
                            }
                        ],
                    )
                    write_jsonl(output / "gaps.jsonl", [])
                    (output / "manifest.json").write_text("{}")
                elif any(
                    value.endswith("classify_current_year_race_due_checks.py")
                    for value in command
                ):
                    classified = shard / "classified-v2"
                    classified.mkdir()
                    (classified / "summary.json").write_text(
                        '{"scope_count":1,"due_event_count":1}'
                    )
                    (classified / "manifest.json").write_text("{}")
                    (classified / "apply_descriptor.json").write_text(
                        '{"apply_artifacts":{"events_hong_kong":{}}}'
                    )

            argv = [
                "run_current_year_source_override.py",
                "--worktree",
                str(ROOT),
                "--plan-root",
                str(root / "plan"),
                "--run-root",
                str(run_root),
                "--shard-id",
                shard_id,
                "--region",
                "hong_kong",
            ]
            with patch.object(self.module, "RUNTIME_HOST", run_root), patch.object(
                self.module, "RUNTIME_CONTAINER", Path("/runs")
            ), patch.object(self.module, "run", side_effect=fake_run), patch.object(
                self.module, "cache_is_complete", return_value=True
            ), patch.object(sys, "argv", argv):
                self.module.main()

        request_command = next(
            command
            for command in commands
            if any(
                value.endswith("build_historical_race_calendar_requests.py")
                for value in command
            )
        )
        prepare_command = next(
            command
            for command in commands
            if any(
                value.endswith("prepare_historical_race_calendar_inputs.py")
                for value in command
            )
        )
        classify_command = next(
            command
            for command in commands
            if any(
                value.endswith("classify_current_year_race_due_checks.py")
                for value in command
            )
        )
        self.assertIn("--hkjc-cutoff-date", request_command)
        self.assertEqual(
            request_command[request_command.index("--hkjc-cutoff-date") + 1],
            "2026-07-15",
        )
        self.assertIn("--request-manifest", prepare_command)
        self.assertIn("--hkjc-cutoff-date", prepare_command)
        self.assertEqual(
            prepare_command[prepare_command.index("--hkjc-cutoff-date") + 1],
            "2026-07-15",
        )
        self.assertIn("--date-matches", classify_command)
        self.assertIn("--gaps", classify_command)
        self.assertIn("classified-v2", " ".join(classify_command))

    def test_hong_kong_runner_archives_and_rebuilds_pre_cutoff_bootstrap(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "runs"
            shard_id = "hong-kong-2026-01"
            shard = run_root / shard_id
            bootstrap = shard / "bootstrap-v2"
            bootstrap.mkdir(parents=True)
            (bootstrap / "selection_snapshot.json").write_text('{"schema_version":"1.0"}')
            (bootstrap / "source_catalog.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "sources": [
                            {
                                "parser": "hkjc_pattern",
                                "options": {"season_end_year": 2026},
                            }
                        ],
                    }
                )
            )
            for name in ("requests-v2", "cache-v2", "parse-v2", "classified-v2"):
                dependency = shard / name
                dependency.mkdir()
                (dependency / "old-evidence.txt").write_text(name)
            commands = []

            def fake_run(command, *, cwd):
                commands.append(command)
                if "tmp/build_current_year_source_override.py" in command:
                    bootstrap.mkdir()
                    (bootstrap / "selection_snapshot.json").write_text(
                        '{"schema_version":"1.0"}'
                    )
                    (bootstrap / "source_catalog.json").write_text("{}")
                elif any(
                    value.endswith("build_historical_race_calendar_requests.py")
                    for value in command
                ):
                    requests = shard / "requests-v2"
                    requests.mkdir()
                    (requests / "provider_rows.jsonl").write_text("")
                    (requests / "manifest.json").write_text("{}")
                elif any(
                    value.endswith("prepare_historical_race_calendar_inputs.py")
                    for value in command
                ):
                    output = shard / "parse-v2"
                    output.mkdir()
                    (output / "summary.json").write_text('{"scope_count":1}')
                    write_jsonl(output / "date_matches.jsonl", [])
                    write_jsonl(
                        output / "gaps.jsonl",
                        [{"target_id": 1, "reason_code": "missing"}],
                    )
                    (output / "manifest.json").write_text("{}")
                elif any(
                    value.endswith("classify_current_year_race_due_checks.py")
                    for value in command
                ):
                    classified = shard / "classified-v2"
                    classified.mkdir()
                    (classified / "summary.json").write_text(
                        '{"scope_count":1,"due_check_pending_count":1}'
                    )
                    (classified / "manifest.json").write_text("{}")
                    (classified / "apply_descriptor.json").write_text(
                        '{"apply_artifacts":{}}'
                    )

            argv = [
                "run_current_year_source_override.py",
                "--worktree",
                str(ROOT),
                "--plan-root",
                str(root / "plan"),
                "--run-root",
                str(run_root),
                "--shard-id",
                shard_id,
                "--region",
                "hong_kong",
            ]
            with patch.object(self.module, "RUNTIME_HOST", run_root), patch.object(
                self.module, "RUNTIME_CONTAINER", Path("/runs")
            ), patch.object(self.module, "run", side_effect=fake_run), patch.object(
                self.module, "cache_is_complete", return_value=True
            ), patch.object(sys, "argv", argv):
                self.module.main()

            archived = sorted(shard.glob("cutoff-policy-chain-before-*"))
            archived_names = (
                {
                    path.name
                    for path in archived[0].iterdir()
                    if path.is_dir()
                }
                if archived
                else set()
            )
            evidence_preserved = bool(archived) and all(
                (archived[0] / name / "old-evidence.txt").read_text() == name
                for name in ("requests-v2", "cache-v2", "parse-v2", "classified-v2")
            )

        self.assertEqual(len(archived), 1)
        self.assertEqual(
            archived_names,
            {
                "bootstrap-v2",
                "requests-v2",
                "cache-v2",
                "parse-v2",
                "classified-v2",
            },
        )
        self.assertTrue(evidence_preserved)
        self.assertTrue(
            any("tmp/build_current_year_source_override.py" in command for command in commands)
        )
        self.assertTrue(
            any(
                any(
                    value.endswith("classify_current_year_race_due_checks.py")
                    for value in command
                )
                for command in commands
            )
        )

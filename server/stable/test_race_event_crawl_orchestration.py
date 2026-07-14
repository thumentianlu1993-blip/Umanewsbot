from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import os
import stat
import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from stable.models import (
    ExternalDataImportLock,
    ExternalDataImportRun,
    ExternalDataSource,
    ExternalImportStatus,
    ExternalRace,
    RaceEvent,
    RaceEventHistoryWinner,
    RaceEventModule,
    RaceEventPriority,
    RaceEventResult,
    RaceEventRunner,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceGrade,
    RacingRegion,
    SourceLanguage,
)


TARGET_MODULES = [
    RaceEventModule.RUNNERS,
    RaceEventModule.RESULTS,
    RaceEventModule.HISTORY_WINNERS,
]


def _field(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _artifact_path(result, key):
    artifacts = _field(result, "artifacts", {})
    artifact = artifacts[key]
    return Path(_field(artifact, "path", artifact))


class RaceEventCrawlOrchestrationTestCase(TestCase):
    def _module(self):
        from stable.services import race_event_crawl_orchestration

        return race_event_crawl_orchestration

    def _runtime_tool(self, filename: str):
        tools_dir = Path(__file__).resolve().parents[2] / "runtime" / "tools"
        sys.path.insert(0, str(tools_dir))
        try:
            spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), tools_dir / filename)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
        finally:
            sys.path.remove(str(tools_dir))

    def test_jra_detail_subset_matches_result_link_by_race_name(self):
        tool = self._runtime_tool("prepare_jra_race_detail_candidates.py")
        html = """
        <table>
          <tr><td>GIII 中山金杯</td><td><a href="/datafile/seiseki/replay/2026/001.html">レース結果</a></td></tr>
          <tr><td>GI 日本ダービー</td><td><a href="/datafile/seiseki/g1/derby/result/derby2026.html">レース結果</a></td></tr>
        </table>
        """
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "jra.html"
            source.write_bytes(html.encode("cp932"))
            links = tool._match_result_links(
                source,
                [{"slug": "jra-2026-0531-01", "original_name": "日本ダービー", "aliases": "日本德比"}],
            )

        self.assertEqual(
            links,
            ["https://www.jra.go.jp/datafile/seiseki/g1/derby/result/derby2026.html"],
        )

    def test_jra_history_current_winner_is_enriched_from_detail_result(self):
        tool = self._runtime_tool("prepare_jra_history_winner_candidates.py")
        items = [
            {
                "winner_year": 2026,
                "horse_name": "ロブチェン",
                "jockey_name": "松山 弘平",
                "trainer_name": "",
                "finish_time": "",
                "margin": "",
                "source_refs": {"primary": "https://www.jra.go.jp/history"},
            }
        ]

        result = tool._enrich_current_winner(
            items,
            event={"year": "2026"},
            detail_winner={
                "horse_name": "ロブチェン",
                "trainer_name": "杉山 晴紀",
                "finish_time": "2:22.7",
                "source_refs": {"primary": "https://www.jra.go.jp/derby2026"},
            },
        )

        self.assertEqual(result[0]["trainer_name"], "杉山 晴紀")
        self.assertEqual(result[0]["finish_time"], "2:22.7")
        self.assertEqual(result[0]["source_refs"]["current_result"], "https://www.jra.go.jp/derby2026")

    def _race_event(self, *, year=2026, slug="uk-derby-2026", series_key="uk-derby", region=RacingRegion.UNITED_KINGDOM, locks=None):
        return RaceEvent.objects.create(
            year=year,
            slug=slug,
            series_key=series_key,
            original_name="Derby Stakes",
            chinese_name="英国打吡大赛",
            country_region=region,
            racecourse="Epsom Downs",
            grade_text="G1",
            normalized_grade=RaceGrade.G1,
            surface=RaceEventSurface.TURF,
            distance_text="1m4f",
            local_date=timezone.localdate(),
            priority=RaceEventPriority.P1,
            status=RaceEventStatus.FINISHED,
            visibility_status=RaceEventVisibility.PUBLISHED,
            manual_lock_flags=locks or {},
        )

    def _base_plan(self, output_dir: Path, **overrides):
        plan = {
            "run_id": "acceptance-20260710",
            "target_layer": "race_event",
            "first_acceptance": False,
            "allow_network": False,
            "batch_size": 3,
            "rate_limit": {"request_interval_seconds": 1, "max_requests": 20},
            "regions": [
                {
                    "region": RacingRegion.UNITED_KINGDOM,
                    "source": "sporting_life",
                    "source_authority": "third_party_high_access",
                    "series": [
                        {
                            "series_key": "uk-derby",
                            "slugs": {"2026": "uk-derby-2026"},
                            "years": {"start": 2026, "end": 2026},
                        }
                    ],
                    "modules": {
                        RaceEventModule.RUNNERS: {"years": {"start": 2026, "end": 2026}},
                        RaceEventModule.RESULTS: {"years": {"start": 2026, "end": 2026}},
                        RaceEventModule.HISTORY_WINNERS: {"years": {"start": 2026, "end": 2026}},
                    },
                }
            ],
            "adapters": ["uk_sporting_life_results", "uk_sporting_life_history"],
            "output_dir": str(output_dir),
        }
        plan.update(overrides)
        return plan

    def _write_json(self, path: Path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _candidate_record(self, *, year=2026, slug="uk-derby-2026", source_url="https://source.test/derby-2026"):
        return {
            "year": year,
            "slug": slug,
            "series_key": "uk-derby",
            "source_name": "sporting_life",
            "source_authority": "third_party_high_access",
            "source_url": source_url,
            "modules": {
                RaceEventModule.RUNNERS: {"items": [{"horse_number": "1", "horse_name": "Calandagan"}]},
                RaceEventModule.RESULTS: {"items": [{"finish_position": 1, "horse_name": "Calandagan"}]},
                RaceEventModule.HISTORY_WINNERS: {
                    "items": [{"winner_year": 2026, "horse_name": "Calandagan"}]
                },
            },
        }

    def _write_jsonl(self, path: Path, records):
        path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")
        return path

    def _write_gzip(self, path: Path, payload: bytes = b"database backup fixture") -> Path:
        with gzip.open(path, "wb") as handle:
            handle.write(payload)
        return path

    def _approved_confirmation(self, scope: dict, **overrides):
        confirmation = {
            **scope,
            "status": "approved",
            "confirmed_by": "operator",
            "confirmed_at": "2026-07-10T04:30:00+08:00",
        }
        confirmation.update(overrides)
        return confirmation


class RaceEventCrawlCommandValidationTests(RaceEventCrawlOrchestrationTestCase):
    def test_command_rejects_stage_without_plan_or_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesMessage(CommandError, "plan"):
                call_command("orchestrate_race_event_crawl", "--stage", "prepare", "--run-dir", tmp, stdout=StringIO())

    def test_plan_validation_rejects_non_race_event_target_without_external_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = self._write_json(Path(tmp) / "plan.json", self._base_plan(Path(tmp), target_layer="external_race"))

            with self.assertRaisesMessage(CommandError, "target_layer"):
                call_command("orchestrate_race_event_crawl", "--plan", str(plan_path), "--stage", "plan", stdout=StringIO())

        self.assertEqual(ExternalRace.objects.count(), 0)

    def test_plan_validation_rejects_missing_required_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._base_plan(Path(tmp))
            del plan["regions"][0]["modules"][RaceEventModule.HISTORY_WINNERS]
            plan_path = self._write_json(Path(tmp) / "plan.json", plan)

            with self.assertRaisesMessage(CommandError, "history_winners"):
                call_command("orchestrate_race_event_crawl", "--plan", str(plan_path), "--stage", "plan", stdout=StringIO())

    def test_plan_validation_rejects_mismatched_module_history_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._base_plan(Path(tmp))
            plan["regions"][0]["modules"][RaceEventModule.HISTORY_WINNERS]["years"]["start"] = 2000
            plan_path = self._write_json(Path(tmp) / "plan.json", plan)

            with self.assertRaisesMessage(CommandError, "history depth"):
                call_command("orchestrate_race_event_crawl", "--plan", str(plan_path), "--stage", "plan", stdout=StringIO())

    def test_prepare_rejects_network_adapter_without_explicit_network_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._base_plan(Path(tmp), allow_network=False)
            plan["adapters"] = [
                {
                    "key": "uk_live_results",
                    "region": RacingRegion.UNITED_KINGDOM,
                    "source": "sporting_life",
                    "modules": [RaceEventModule.RUNNERS],
                    "requires_network": True,
                    "source_authority": "third_party_high_access",
                    "command": [sys.executable, "-c", "raise SystemExit(0)"],
                    "outputs": [
                        {"key": "candidate_jsonl", "path": "candidate.jsonl", "required": True}
                    ],
                }
            ]
            plan_path = self._write_json(Path(tmp) / "plan.json", plan)

            with self.assertRaisesMessage(CommandError, "network"):
                call_command("orchestrate_race_event_crawl", "--plan", str(plan_path), "--stage", "prepare", stdout=StringIO())

    def test_plan_stage_accepts_plan_already_in_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_path = self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path))
            out = StringIO()

            call_command("orchestrate_race_event_crawl", "--plan", str(plan_path), "--stage", "plan", "--run-dir", str(tmp_path), stdout=out)

            self.assertTrue((tmp_path / "state.json").exists())
            self.assertIn("plan 通过", out.getvalue())

    def test_audit_uses_combined_candidate_artifact_when_path_is_omitted(self):
        self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_path = self._write_json(tmp_path / "plan-source.json", self._base_plan(tmp_path))
            state = self._module().create_run(plan_path, tmp_path)
            (tmp_path / "candidates").mkdir(exist_ok=True)
            combined = self._write_jsonl(
                tmp_path / "candidates" / "combined_candidates.jsonl",
                [self._candidate_record()],
            )
            state.artifacts["combined_candidates"] = str(combined)
            state.artifacts["combined_candidates_identity"] = self._module().file_identity(combined)
            state.write()
            mapping = self._write_json(
                tmp_path / "series-mapping.json",
                {"uk-derby": {"status": "approved", "slugs": {"2026": "uk-derby-2026"}}},
            )

            call_command(
                "orchestrate_race_event_crawl",
                "--plan",
                str(plan_path),
                "--stage",
                "audit",
                "--series-mapping",
                str(mapping),
                "--run-dir",
                str(tmp_path),
                stdout=StringIO(),
            )

            coverage = json.loads((tmp_path / "coverage_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(coverage["status"], "passed")

    def test_prepare_rejects_registry_network_adapter_without_explicit_network_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = self._base_plan(tmp_path, allow_network=False, adapters=["jra_detail"])
            plan_path = self._write_json(tmp_path / "plan.json", plan)

            with self.assertRaisesMessage(CommandError, "network"):
                call_command("orchestrate_race_event_crawl", "--plan", str(plan_path), "--stage", "prepare", stdout=StringIO())

    def test_plan_validation_rejects_invalid_rate_limit_and_region_batch_overflow(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            invalid_rate = self._base_plan(tmp_path)
            invalid_rate["rate_limit"]["max_requests"] = 0
            with self.assertRaisesMessage(module.PlanValidationError, "max_requests"):
                module.validate_plan(invalid_rate)

            over_batch = self._base_plan(tmp_path, batch_size=1)
            over_batch["regions"][0]["series"][0]["slugs"]["2025"] = "uk-derby-2025"
            over_batch["regions"][0]["series"][0]["years"] = {"start": 2025, "end": 2026}
            for module_name in TARGET_MODULES:
                over_batch["regions"][0]["modules"][module_name]["years"] = {"start": 2025, "end": 2026}
            with self.assertRaisesMessage(module.PlanValidationError, "batch_size"):
                module.validate_plan(over_batch)


class RaceEventCrawlAdapterManifestTests(RaceEventCrawlOrchestrationTestCase):
    def _script(self, directory: Path, body: str):
        script = directory / "fake_adapter.py"
        script.write_text(body, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script

    def test_manifest_accepts_special_inputs_dependencies_and_output_normalization(self):
        module = self._module()
        manifest = module.AdapterManifest.from_dict(
            {
                "key": "uk_sporting_life_history",
                "region": RacingRegion.UNITED_KINGDOM,
                "source": "sporting_life",
                "modules": [RaceEventModule.HISTORY_WINNERS],
                "source_authority": "third_party_high_access",
                "command": [sys.executable, "prepare_uk_sportinglife_history_winner_candidates.py", "--review-csv", "{review_csv}", "--output-dir", "{adapter_output_dir}"],
                "inputs": {"review_csv": {"required": True, "artifact": "review/uk_results_review.csv"}},
                "dependencies": [{"artifact": "review/uk_results_review.csv", "stage": "audit"}],
                "outputs": [
                    {
                        "key": "candidate_jsonl",
                        "path": "uk_history_winners_2026.jsonl",
                        "standard_name": "candidates/uk_sporting_life_history_winners.jsonl",
                        "required": True,
                    }
                ],
            }
        )

        self.assertEqual(_field(manifest, "key"), "uk_sporting_life_history")
        self.assertEqual(_field(manifest, "source_authority"), "third_party_high_access")
        self.assertIn("review_csv", _field(manifest, "inputs"))
        self.assertEqual(_field(manifest, "modules"), [RaceEventModule.HISTORY_WINNERS])
        self.assertEqual(_field(manifest, "outputs")[0]["standard_name"], "candidates/uk_sporting_life_history_winners.jsonl")

    def test_plan_rejects_incomplete_or_unknown_adapter_payloads(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for adapter in [
                {"key": "missing-everything"},
                {
                    "key": "missing-command",
                    "region": RacingRegion.UNITED_KINGDOM,
                    "source": "sporting_life",
                    "modules": [RaceEventModule.RUNNERS],
                    "source_authority": "third_party_high_access",
                    "outputs": [{"key": "candidate_jsonl", "path": "candidate.jsonl"}],
                },
                {
                    "key": "empty-command",
                    "region": RacingRegion.UNITED_KINGDOM,
                    "source": "sporting_life",
                    "modules": [RaceEventModule.RUNNERS],
                    "source_authority": "third_party_high_access",
                    "command": [],
                    "outputs": [{"key": "candidate_jsonl", "path": "candidate.jsonl"}],
                },
            ]:
                plan = self._base_plan(tmp_path, adapters=[adapter])
                with self.subTest(adapter=adapter["key"]):
                    with self.assertRaises(module.PlanValidationError):
                        module.validate_plan(plan)

            plan = self._base_plan(tmp_path, adapters=[object()])
            with self.assertRaisesMessage(module.PlanValidationError, "adapter must"):
                module.validate_plan(plan)

    def test_adapter_blocks_missing_declared_dependency_before_subprocess(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script = self._script(
                tmp_path,
                "from pathlib import Path\nPath('should_not_exist.txt').write_text('ran')\n",
            )
            manifest = module.AdapterManifest.from_dict(
                {
                    "key": "jra_source_html_detail",
                    "region": RacingRegion.JAPAN,
                    "source": "jra",
                    "modules": [RaceEventModule.RUNNERS],
                    "source_authority": "official",
                    "command": [sys.executable, str(script), "--source-html", "{source_html}"],
                    "inputs": {"source_html": {"required": True, "artifact": "source/jra.html"}},
                    "dependencies": [{"artifact": "source/jra.html", "stage": "prepare"}],
                    "outputs": [{"key": "candidate_jsonl", "path": "jra_detail_candidates_2026.jsonl", "required": True}],
                }
            )

            with self.assertRaises(module.AdapterDependencyError):
                module.AdapterRunner(manifest).run(inputs={}, run_dir=tmp_path, allow_network=False)

            self.assertFalse((tmp_path / "should_not_exist.txt").exists())

    def test_adapter_records_command_output_and_normalizes_fixed_year_artifacts(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script = self._script(
                tmp_path,
                "import argparse, json\n"
                "from pathlib import Path\n"
                "parser = argparse.ArgumentParser()\n"
                "parser.add_argument('--output-dir')\n"
                "args = parser.parse_args()\n"
                "out = Path(args.output_dir)\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                "(out / 'jra_detail_candidates_2026.jsonl').write_text(json.dumps({'slug': 'tokyo-yushun-2026'}) + '\\n')\n"
                "(out / 'review.csv').write_text('slug,status\\ntokyo-yushun-2026,complete\\n')\n"
                "(out / 'summary.json').write_text(json.dumps({'candidate_count': 1}))\n"
                "print('adapter ok')\n",
            )
            manifest = module.AdapterManifest.from_dict(
                {
                    "key": "jra_detail",
                    "region": RacingRegion.JAPAN,
                    "source": "jra",
                    "modules": [RaceEventModule.RUNNERS, RaceEventModule.RESULTS],
                    "source_authority": "official",
                    "command": [sys.executable, str(script), "--output-dir", "{adapter_output_dir}"],
                    "outputs": [
                        {
                            "key": "candidate_jsonl",
                            "path": "jra_detail_candidates_2026.jsonl",
                            "standard_name": "candidates/jra_detail.jsonl",
                            "required": True,
                        },
                        {"key": "review_csv", "path": "review.csv", "standard_name": "review/jra_detail.csv", "required": True},
                        {"key": "summary", "path": "summary.json", "standard_name": "summary/jra_detail.json", "required": True},
                    ],
                }
            )

            result = module.AdapterRunner(manifest).run(inputs={}, run_dir=tmp_path, allow_network=False)

            self.assertEqual(_field(result, "status"), "succeeded")
            self.assertIn("adapter ok", _field(result, "stdout_excerpt"))
            self.assertTrue(_artifact_path(result, "candidate_jsonl").exists())
            self.assertTrue((tmp_path / "candidates" / "jra_detail.jsonl").exists())
            self.assertTrue((tmp_path / "adapter_runs" / "jra_detail" / "jra_detail_candidates_2026.jsonl").exists())
            candidate = json.loads((tmp_path / "candidates" / "jra_detail.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(candidate["adapter_key"], "jra_detail")
            self.assertEqual(candidate["source_provider"], "jra")
            self.assertEqual(candidate["source_authority"], "official")
            self.assertEqual(candidate["racing_region"], RacingRegion.JAPAN)
            candidate_artifact = _field(_field(result, "artifacts"), "candidate_jsonl")
            self.assertEqual(
                _field(candidate_artifact, "sha256"),
                module.file_identity(_artifact_path(result, "candidate_jsonl"))["sha256"],
            )
            summary = json.loads((tmp_path / "summary" / "jra_detail.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["orchestration_provenance"]["source_authority"], "official")

    def test_adapter_default_workdir_resolves_repo_relative_commands(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest = module.AdapterManifest.from_dict(
                {
                    "key": "repo_relative_check",
                    "region": RacingRegion.JAPAN,
                    "source": "jra",
                    "modules": [RaceEventModule.RUNNERS],
                    "source_authority": "official",
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path\n"
                        "assert Path('server/manage.py').exists()\n"
                        "out = Path('{adapter_output_dir}')\n"
                        "out.mkdir(parents=True, exist_ok=True)\n"
                        "(out / 'candidate.jsonl').write_text('{{\"slug\": \"repo-relative\"}}\\n')\n",
                    ],
                    "outputs": [{"key": "candidate_jsonl", "path": "candidate.jsonl", "required": True}],
                }
            )

            result = module.AdapterRunner(manifest).run(inputs={}, run_dir=tmp_path, allow_network=False)

            self.assertEqual(_field(result, "status"), "succeeded")
            command = json.loads((tmp_path / "adapter_runs" / "repo_relative_check" / "command.json").read_text(encoding="utf-8"))
            self.assertEqual(command["returncode"], 0)

    def test_adapter_fails_when_required_artifact_is_missing_even_if_script_exits_zero(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script = self._script(tmp_path, "print('zero exit but no outputs')\n")
            manifest = module.AdapterManifest.from_dict(
                {
                    "key": "france_zeturf",
                    "region": RacingRegion.FRANCE,
                    "source": "zeturf",
                    "modules": [RaceEventModule.RUNNERS, RaceEventModule.RESULTS],
                    "source_authority": "third_party_high_access",
                    "command": [sys.executable, str(script)],
                    "outputs": [{"key": "candidate_jsonl", "path": "france_detail_candidates_2026.jsonl", "required": True}],
                }
            )

            with self.assertRaises(module.AdapterOutputError):
                module.AdapterRunner(manifest).run(inputs={}, run_dir=tmp_path, allow_network=False)

    def test_adapter_runner_enforces_shared_request_budget_without_real_network(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest = module.AdapterManifest.from_dict(
                {
                    "key": "budget_probe",
                    "region": RacingRegion.UNITED_KINGDOM,
                    "source": "sporting_life",
                    "modules": [RaceEventModule.RESULTS],
                    "source_authority": "third_party_high_access",
                    "requires_network": True,
                    "command": [
                        sys.executable,
                        "-c",
                        "import sys; sys.path.insert(0, 'runtime/tools'); "
                        "from race_event_request_budget import before_network_request; "
                        "before_network_request('https://source.test/one'); "
                        "before_network_request('https://source.test/two')",
                    ],
                    "outputs": [
                        {"key": "candidate_jsonl", "path": "candidate.jsonl", "required": True}
                    ],
                }
            )

            with self.assertRaises(module.AdapterExecutionError):
                module.AdapterRunner(manifest).run(
                    inputs={},
                    run_dir=tmp_path,
                    allow_network=True,
                    execution_policy={
                        "batch_size": 1,
                        "max_requests": 1,
                        "request_interval_seconds": 0,
                    },
                )

            budget = json.loads((tmp_path / "request_budget.json").read_text(encoding="utf-8"))
            self.assertEqual(budget["request_count"], 1)
            self.assertEqual(budget["status"], "limit_exceeded")

    def test_adapter_runner_preserves_parent_runner_paths_and_stricter_resource_limits(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            parent_root = tmp_path / "parent-runner"
            parent_root.mkdir()
            script = self._script(
                tmp_path,
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "keys = sys.argv[2:]\n"
                "Path(sys.argv[1]).write_text(json.dumps({key: os.environ.get(key) for key in keys}))\n",
            )
            output = "environment.json"
            keys = [
                "RACE_EVENT_CRAWL_MAX_REQUESTS",
                "RACE_EVENT_CRAWL_REQUEST_INTERVAL_SECONDS",
                "RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT",
                "RACE_EVENT_CRAWL_MAX_SOURCE_CACHE_BYTES",
                "RACE_EVENT_CRAWL_MIN_FREE_DISK_BYTES",
                "RACE_EVENT_CRAWL_SOURCE_CACHE_ROOT",
                "RACE_EVENT_CRAWL_SOURCE_CACHE_MANIFEST",
            ]
            manifest = module.AdapterManifest.from_dict(
                {
                    "key": "parent_budget_probe",
                    "region": RacingRegion.UNITED_KINGDOM,
                    "source": "sporting_life",
                    "modules": [RaceEventModule.RESULTS],
                    "source_authority": "third_party_high_access",
                    "requires_network": True,
                    "command": [
                        sys.executable,
                        str(script),
                        "{adapter_output_dir}/environment.json",
                        *keys,
                    ],
                    "outputs": [{"key": "environment", "path": output, "required": True}],
                }
            )
            parent_environment = {
                "RACE_EVENT_CRAWL_MAX_REQUESTS": "17",
                "RACE_EVENT_CRAWL_REQUEST_INTERVAL_SECONDS": "1",
                "RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT": str(
                    parent_root / "runner-request-budget.json"
                ),
                "RACE_EVENT_CRAWL_MAX_SOURCE_CACHE_BYTES": "4096",
                "RACE_EVENT_CRAWL_MIN_FREE_DISK_BYTES": str(5 * 1024**3),
                "RACE_EVENT_CRAWL_SOURCE_CACHE_ROOT": str(parent_root),
                "RACE_EVENT_CRAWL_SOURCE_CACHE_MANIFEST": str(
                    parent_root / "runner-source-cache-manifest.json"
                ),
            }
            with patch.dict(os.environ, parent_environment):
                result = module.AdapterRunner(manifest).run(
                    inputs={},
                    run_dir=tmp_path,
                    allow_network=True,
                    execution_policy={
                        "max_requests": 250,
                        "request_interval_seconds": 0,
                        "max_source_cache_bytes": 2 * 1024**3,
                        "min_free_disk_bytes": 1,
                    },
                )
            self.assertEqual(_field(result, "status"), "succeeded")
            payload = json.loads(
                (
                    tmp_path
                    / "adapter_runs"
                    / "parent_budget_probe"
                    / "environment.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(payload, parent_environment)

    def test_candidate_artifacts_are_combined_for_downstream_stages(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            detail = self._candidate_record()
            detail["modules"] = {
                RaceEventModule.RUNNERS: detail["modules"][RaceEventModule.RUNNERS],
                RaceEventModule.RESULTS: detail["modules"][RaceEventModule.RESULTS],
            }
            history = self._candidate_record(source_url="https://source.test/history")
            history["modules"] = {
                RaceEventModule.HISTORY_WINNERS: history["modules"][RaceEventModule.HISTORY_WINNERS]
            }
            detail_path = self._write_jsonl(tmp_path / "detail.jsonl", [detail])
            history_path = self._write_jsonl(tmp_path / "history.jsonl", [history])
            result = module.aggregate_candidate_artifacts(
                results=[
                    {"artifacts": {"candidate_jsonl": {"path": str(detail_path)}}},
                    {"artifacts": {"candidate_jsonl": {"path": str(history_path)}}},
                ],
                run_dir=tmp_path,
            )

            combined_path = Path(result["path"])
            combined_records = [
                json.loads(line) for line in combined_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(combined_records), 2)
            self.assertEqual(result["identity"]["sha256"], module.file_identity(combined_path)["sha256"])

    def test_combined_candidates_drop_empty_modules_and_empty_records(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            detail = self._candidate_record()
            detail["modules"][RaceEventModule.RESULTS] = {"items": []}
            empty = self._candidate_record(source_url="https://source.test/empty")
            empty["modules"] = {RaceEventModule.RESULTS: {"items": []}}
            source_path = self._write_jsonl(tmp_path / "source.jsonl", [detail, empty])

            result = module.aggregate_candidate_artifacts(
                results=[{"artifacts": {"candidate_jsonl": {"path": str(source_path)}}}],
                run_dir=tmp_path,
            )

            combined_records = [
                json.loads(line)
                for line in Path(result["path"]).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(combined_records), 1)
            self.assertEqual(
                set(combined_records[0]["modules"]),
                {RaceEventModule.RUNNERS, RaceEventModule.HISTORY_WINNERS},
            )

    def test_resume_skips_unchanged_successful_adapter_and_retries_failed_adapter(self):
        self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_input = tmp_path / "input" / "source.txt"
            source_input.parent.mkdir(parents=True)
            source_input.write_text('{"slug": "first-v1"}\n', encoding="utf-8")
            first_count = tmp_path / "first-count.txt"
            trigger = tmp_path / "allow-second.txt"
            first_script = self._script(
                tmp_path,
                "import argparse\n"
                "from pathlib import Path\n"
                "parser = argparse.ArgumentParser()\n"
                "parser.add_argument('--input')\n"
                "parser.add_argument('--output-dir')\n"
                "args = parser.parse_args()\n"
                f"count = Path({str(first_count)!r})\n"
                "value = int(count.read_text() or '0') + 1 if count.exists() else 1\n"
                "count.write_text(str(value))\n"
                "out = Path(args.output_dir)\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                "(out / 'first.jsonl').write_text(Path(args.input).read_text())\n",
            )
            second_script = tmp_path / "second_adapter.py"
            second_script.write_text(
                "import argparse\n"
                "from pathlib import Path\n"
                "parser = argparse.ArgumentParser()\n"
                "parser.add_argument('--output-dir')\n"
                "args = parser.parse_args()\n"
                f"trigger = Path({str(trigger)!r})\n"
                "if not trigger.exists():\n"
                "    raise SystemExit(2)\n"
                "out = Path(args.output_dir)\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                "(out / 'second.jsonl').write_text('{\"slug\": \"second\"}\\n')\n",
                encoding="utf-8",
            )
            plan = self._base_plan(tmp_path)
            plan["adapters"] = [
                {
                    "key": "first_adapter",
                    "region": RacingRegion.UNITED_KINGDOM,
                    "source": "sporting_life",
                    "modules": [RaceEventModule.RUNNERS],
                    "source_authority": "third_party_high_access",
                    "command": [sys.executable, str(first_script), "--input", "{source_input}", "--output-dir", "{adapter_output_dir}"],
                    "inputs": {"source_input": {"required": True, "artifact": "input/source.txt"}},
                    "outputs": [{"key": "candidate_jsonl", "path": "first.jsonl", "required": True}],
                },
                {
                    "key": "second_adapter",
                    "region": RacingRegion.UNITED_KINGDOM,
                    "source": "sporting_life",
                    "modules": [RaceEventModule.RESULTS],
                    "source_authority": "third_party_high_access",
                    "command": [sys.executable, str(second_script), "--output-dir", "{adapter_output_dir}"],
                    "outputs": [{"key": "candidate_jsonl", "path": "second.jsonl", "required": True}],
                },
            ]
            plan_path = self._write_json(tmp_path / "plan-source.json", plan)

            with self.assertRaises(CommandError):
                call_command(
                    "orchestrate_race_event_crawl",
                    "--plan",
                    str(plan_path),
                    "--stage",
                    "prepare",
                    "--run-dir",
                    str(tmp_path),
                    stdout=StringIO(),
                )

            state_path = tmp_path / "state.json"
            failed_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(failed_state["adapter_states"]["first_adapter"]["status"], "succeeded")
            self.assertEqual(failed_state["adapter_states"]["second_adapter"]["status"], "failed")
            self.assertEqual(first_count.read_text(encoding="utf-8"), "1")

            trigger.write_text("ready", encoding="utf-8")
            call_command(
                "orchestrate_race_event_crawl",
                "--stage",
                "resume",
                "--state",
                str(state_path),
                stdout=StringIO(),
            )

            resumed_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(first_count.read_text(encoding="utf-8"), "1")
            self.assertEqual(resumed_state["adapter_states"]["first_adapter"]["resume_action"], "skipped_unchanged")
            self.assertEqual(resumed_state["adapter_states"]["second_adapter"]["status"], "succeeded")
            self.assertIn("prepare", resumed_state["completed_stages"])
            self.assertTrue(resumed_state["resume_history"])

            first_output = Path(
                resumed_state["adapter_states"]["first_adapter"]["result"]["artifacts"]["candidate_jsonl"]["path"]
            )
            first_output.unlink()
            call_command(
                "orchestrate_race_event_crawl",
                "--stage",
                "resume",
                "--state",
                str(state_path),
                stdout=StringIO(),
            )

            missing_output_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(first_count.read_text(encoding="utf-8"), "2")
            self.assertEqual(
                missing_output_state["adapter_states"]["first_adapter"]["resume_action"],
                "rerun_output_missing",
            )

            source_input.write_text('{"slug": "first-v2"}\n', encoding="utf-8")
            call_command(
                "orchestrate_race_event_crawl",
                "--stage",
                "resume",
                "--state",
                str(state_path),
                stdout=StringIO(),
            )

            changed_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(first_count.read_text(encoding="utf-8"), "3")
            self.assertEqual(changed_state["adapter_states"]["first_adapter"]["resume_action"], "rerun_input_changed")


class RaceEventCrawlCoverageAuditTests(RaceEventCrawlOrchestrationTestCase):
    def test_expected_target_snapshot_is_created_before_crawl(self):
        module = self._module()
        event = self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_path = self._write_json(tmp_path / "plan-source.json", self._base_plan(tmp_path))

            state = module.create_run(plan_path, tmp_path)

            expected_path = Path(state.artifacts["expected_targets"])
            review_path = Path(state.artifacts["expected_targets_review"])
            payload = json.loads(expected_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["expected_target_count"], 1)
            self.assertEqual(payload["expected_module_count"], 3)
            self.assertEqual(payload["targets"][0]["race_event_id"], event.id)
            self.assertEqual(
                state.artifacts["expected_targets_identity"]["sha256"],
                module.file_identity(expected_path)["sha256"],
            )
            review_text = review_path.read_text(encoding="utf-8")
            self.assertIn("uk-derby-2026", review_text)
            self.assertIn("Derby Stakes", review_text)
            self.assertIn("英国打吡大赛", review_text)

    def test_expected_targets_require_matching_approval_and_generate_region_scoped_input(self):
        module = self._module()
        event = self._race_event()
        event.source_refs = {"chart_url": "https://source.test/approved-chart"}
        event.save(update_fields=["source_refs", "updated_at"])
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_path = self._write_json(tmp_path / "plan-source.json", self._base_plan(tmp_path))
            state = module.create_run(plan_path, tmp_path)
            approval_path = Path(state.artifacts["expected_targets_approval"])

            with self.assertRaisesMessage(module.PlanValidationError, "not approved"):
                module.validate_expected_targets_approval(
                    run_dir=tmp_path,
                    expected_targets=state.artifacts["expected_targets"],
                )

            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approval.update(
                {
                    "status": "approved",
                    "approved_by": "operator",
                    "approved_at": "2026-07-11T09:00:00+08:00",
                }
            )
            self._write_json(approval_path, approval)
            module.validate_expected_targets_approval(
                run_dir=tmp_path,
                expected_targets=state.artifacts["expected_targets"],
            )

            inputs = module.materialize_adapter_event_inputs(
                expected_snapshot=json.loads(
                    Path(state.artifacts["expected_targets"]).read_text(encoding="utf-8")
                ),
                run_dir=tmp_path,
            )
            rows = list(csv.DictReader(Path(inputs[RacingRegion.UNITED_KINGDOM]).open(encoding="utf-8-sig")))
            self.assertEqual([(row["year"], row["slug"]) for row in rows], [("2026", "uk-derby-2026")])
            self.assertIn("approved-chart", rows[0]["source_refs"])

            event.source_refs = {"chart_url": "https://source.test/changed-after-approval"}
            event.save(update_fields=["source_refs", "updated_at"])
            with self.assertRaisesMessage(module.PlanValidationError, "changed after approval"):
                module.materialize_adapter_event_inputs(
                    expected_snapshot=json.loads(
                        Path(state.artifacts["expected_targets"]).read_text(encoding="utf-8")
                    ),
                    run_dir=tmp_path,
                )

    def test_coverage_audit_blocks_empty_candidate_file_against_expected_targets(self):
        module = self._module()
        self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(tmp_path / "empty.jsonl", []),
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json",
                    {"uk-derby": {"status": "approved", "slugs": {"2026": "uk-derby-2026"}}},
                ),
                run_dir=tmp_path,
            )

            self.assertEqual(_field(result, "status"), "blocked")
            self.assertIn("missing_event_candidate", _field(result, "blocker_codes"))
            self.assertEqual(_field(result, "expected_target_count"), 1)
            self.assertEqual(_field(result, "actual_target_count"), 0)

    def test_coverage_audit_blocks_present_modules_with_empty_items(self):
        module = self._module()
        self._race_event()
        record = self._candidate_record()
        for payload in record["modules"].values():
            payload["items"] = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(tmp_path / "candidates.jsonl", [record]),
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}
                ),
                run_dir=tmp_path,
            )

            self.assertEqual(_field(result, "complete_count"), 0)
            self.assertEqual(
                set(_field(result, "blocker_codes")),
                {"empty_history_winners", "empty_results", "empty_runners"},
            )

    def test_coverage_audit_only_accepts_explicitly_approved_mapping(self):
        module = self._module()
        self._race_event()
        for mapping_status in ["new_series_candidate", "rejected", "approvd", ""]:
            with self.subTest(mapping_status=mapping_status), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                result = module.audit_coverage(
                    plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                    candidate_jsonl=self._write_jsonl(
                        tmp_path / "candidates.jsonl", [self._candidate_record()]
                    ),
                    series_mapping_path=self._write_json(
                        tmp_path / "series_mapping.json",
                        {"uk-derby": {"status": mapping_status}},
                    ),
                    run_dir=tmp_path,
                )

                self.assertIn("series_needs_review", _field(result, "blocker_codes"))
                self.assertEqual(_field(result, "complete_count"), 0)

    def test_coverage_audit_blocks_candidate_without_source_url(self):
        module = self._module()
        self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(
                    tmp_path / "candidate.jsonl",
                    [self._candidate_record(source_url="")],
                ),
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json",
                    {"uk-derby": {"status": "approved"}},
                ),
                run_dir=tmp_path,
            )

            self.assertIn("source_url_missing", _field(result, "blocker_codes"))
            self.assertEqual(_field(result, "complete_count"), 0)

    def test_coverage_audit_blocks_candidates_outside_the_expected_plan(self):
        module = self._module()
        self._race_event()
        self._race_event(year=2026, slug="uk-oaks-2026", series_key="uk-oaks")
        extra = self._candidate_record(slug="uk-oaks-2026")
        extra["series_key"] = "uk-oaks"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(
                    tmp_path / "candidates.jsonl", [self._candidate_record(), extra]
                ),
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json",
                    {
                        "uk-derby": {"status": "approved", "slugs": {"2026": "uk-derby-2026"}},
                        "uk-oaks": {"status": "approved", "slugs": {"2026": "uk-oaks-2026"}},
                    },
                ),
                run_dir=tmp_path,
            )

            self.assertIn("unexpected_candidate", _field(result, "blocker_codes"))

    def test_coverage_audit_marks_three_module_complete_candidate_as_complete(self):
        module = self._module()
        self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_path = self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path))
            candidates = self._write_jsonl(tmp_path / "candidates.jsonl", [self._candidate_record()])
            mapping = self._write_json(
                tmp_path / "series_mapping.json",
                {"uk-derby": {"status": "approved", "series_key": "uk-derby", "slugs": {"2026": "uk-derby-2026"}}},
            )

            result = module.audit_coverage(plan_path=plan_path, candidate_jsonl=candidates, series_mapping_path=mapping, run_dir=tmp_path)

            self.assertEqual(_field(result, "status"), "passed")
            self.assertEqual(_field(result, "complete_count"), 1)
            self.assertEqual(_field(result, "blockers"), [])

    def test_coverage_audit_aggregates_modules_from_separate_adapter_records(self):
        module = self._module()
        self._race_event()
        detail = self._candidate_record()
        history = self._candidate_record()
        detail["modules"] = {
            RaceEventModule.RUNNERS: detail["modules"][RaceEventModule.RUNNERS],
            RaceEventModule.RESULTS: detail["modules"][RaceEventModule.RESULTS],
        }
        history["modules"] = {
            RaceEventModule.HISTORY_WINNERS: history["modules"][RaceEventModule.HISTORY_WINNERS],
        }
        detail.pop("series_key")
        history.pop("series_key")
        history["source_name"] = "sporting_life_previous_winners_chain"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(tmp_path / "candidates.jsonl", [detail, history]),
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json",
                    {"uk-derby": {"status": "approved", "slugs": {"2026": "uk-derby-2026"}}},
                ),
                run_dir=tmp_path,
            )

            self.assertEqual(_field(result, "status"), "passed")
            self.assertEqual(_field(result, "complete_count"), 1)
            self.assertNotIn("missing_runners", _field(result, "blocker_codes"))
            self.assertNotIn("missing_results", _field(result, "blocker_codes"))
            self.assertNotIn("missing_history_winners", _field(result, "blocker_codes"))

    def test_coverage_audit_ignores_empty_module_when_another_record_has_items(self):
        module = self._module()
        self._race_event()
        detail = self._candidate_record()
        results = self._candidate_record()
        detail["modules"][RaceEventModule.RESULTS] = {"items": []}
        results["modules"] = {
            RaceEventModule.RESULTS: results["modules"][RaceEventModule.RESULTS],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(tmp_path / "candidates.jsonl", [detail, results]),
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}
                ),
                run_dir=tmp_path,
            )

            self.assertEqual(_field(result, "status"), "passed")
            self.assertEqual(_field(result, "complete_count"), 1)
            self.assertNotIn("duplicate_candidate", _field(result, "blocker_codes"))
            self.assertNotIn("empty_results", _field(result, "blocker_codes"))

    def test_coverage_audit_reports_missing_module_and_excludes_it_from_complete_count(self):
        module = self._module()
        self._race_event()
        record = self._candidate_record()
        del record["modules"][RaceEventModule.RESULTS]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(tmp_path / "candidates.jsonl", [record]),
                series_mapping_path=self._write_json(tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}),
                run_dir=tmp_path,
            )

            self.assertEqual(_field(result, "complete_count"), 0)
            self.assertIn("missing_results", _field(result, "blocker_codes"))

    def test_coverage_audit_blocks_missing_or_conflicting_source_authority(self):
        module = self._module()
        self._race_event()
        missing = self._candidate_record()
        missing.pop("source_authority")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            common = {
                "plan_path": self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                "series_mapping_path": self._write_json(
                    tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}
                ),
                "run_dir": tmp_path,
            }
            result = module.audit_coverage(
                candidate_jsonl=self._write_jsonl(tmp_path / "missing.jsonl", [missing]),
                **common,
            )
            self.assertIn("source_authority_missing", _field(result, "blocker_codes"))

            conflict = self._candidate_record()
            conflict["source_authority"] = "official"
            result = module.audit_coverage(
                candidate_jsonl=self._write_jsonl(tmp_path / "conflict.jsonl", [conflict]),
                **common,
            )
            self.assertIn("source_provenance_conflict", _field(result, "blocker_codes"))

    def test_coverage_audit_blocks_missing_target_race_event_and_writes_seed_review(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = self._base_plan(tmp_path)
            plan["regions"][0]["series"][0]["slugs"] = {"2025": "uk-derby-2025"}
            plan["regions"][0]["series"][0]["years"] = {"start": 2025, "end": 2025}
            for module_name in TARGET_MODULES:
                plan["regions"][0]["modules"][module_name]["years"] = {"start": 2025, "end": 2025}
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", plan),
                candidate_jsonl=self._write_jsonl(tmp_path / "candidates.jsonl", [self._candidate_record(year=2025, slug="uk-derby-2025")]),
                series_mapping_path=self._write_json(tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}),
                run_dir=tmp_path,
            )

            self.assertIn("missing_race_event", _field(result, "blocker_codes"))
            seed_path = _artifact_path(result, "race_event_seed_review")
            self.assertTrue(seed_path.exists())
            self.assertIn("uk-derby-2025", seed_path.read_text(encoding="utf-8"))

    def test_coverage_audit_blocks_duplicate_source_conflict_mapping_review_and_manual_lock(self):
        module = self._module()
        self._race_event(locks={RaceEventModule.RESULTS: True})
        record = self._candidate_record(source_url="https://source.test/shared")
        duplicate = self._candidate_record(source_url="https://source.test/shared")
        duplicate["slug"] = "uk-oaks-2026"
        duplicate["series_key"] = "uk-oaks"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(tmp_path / "candidates.jsonl", [record, record, duplicate]),
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json",
                    {
                        "uk-derby": {"status": "needs_review"},
                        "uk-oaks": {"status": "ambiguous", "candidates": ["uk-oaks", "epsom-oaks"]},
                    },
                ),
                run_dir=tmp_path,
            )

            blocker_codes = set(_field(result, "blocker_codes"))
            self.assertIn("duplicate_candidate", blocker_codes)
            self.assertIn("source_conflict", blocker_codes)
            self.assertIn("series_needs_review", blocker_codes)
            self.assertIn("ambiguous_series", blocker_codes)
            self.assertIn("manual_lock_conflict", blocker_codes)

    def test_coverage_audit_blocks_candidate_that_is_less_complete_than_existing_data(self):
        module = self._module()
        event = self._race_event()
        RaceEventRunner.objects.create(event=event, horse_number="1", horse_name="Existing One")
        RaceEventRunner.objects.create(event=event, horse_number="2", horse_name="Existing Two")
        RaceEventResult.objects.create(event=event, finish_position=1, horse_name="Existing One")
        RaceEventHistoryWinner.objects.create(event=event, winner_year=2026, horse_name="Existing One")
        record = self._candidate_record()
        record["modules"][RaceEventModule.RUNNERS]["items"] = [{"horse_number": "1", "horse_name": "Existing One"}]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(tmp_path / "candidates.jsonl", [record]),
                series_mapping_path=self._write_json(tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}),
                run_dir=tmp_path,
            )

            self.assertIn("existing_data_diff", _field(result, "warning_codes"))
            self.assertIn("candidate_less_complete", _field(result, "blocker_codes"))
            review_rows = list(csv.DictReader(_artifact_path(result, "review_csv").open(encoding="utf-8")))
            self.assertEqual(review_rows[0]["status"], "blocked")

    def test_coverage_audit_blocks_equal_count_candidate_with_less_complete_fields(self):
        module = self._module()
        event = self._race_event()
        RaceEventHistoryWinner.objects.create(
            event=event,
            winner_year=2026,
            horse_name="Existing One",
            jockey_name="Existing Jockey",
            trainer_name="Existing Trainer",
            finish_time="2:30.00",
        )
        record = self._candidate_record()
        record["modules"][RaceEventModule.HISTORY_WINNERS]["items"] = [
            {
                "winner_year": 2026,
                "horse_name": "Existing One",
                "jockey_name": "Existing Jockey",
                "trainer_name": "",
                "finish_time": "",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(tmp_path / "candidates.jsonl", [record]),
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}
                ),
                run_dir=tmp_path,
            )

            self.assertIn("candidate_less_complete", _field(result, "blocker_codes"))
            blocker = next(
                item
                for item in _field(result, "blockers")
                if item["code"] == "candidate_less_complete"
                and item.get("field_completeness_regressions")
            )
            self.assertEqual(
                set(blocker["field_completeness_regressions"]),
                {"trainer_name", "finish_time"},
            )

    def test_coverage_warning_only_candidate_remains_complete(self):
        module = self._module()
        event = self._race_event()
        RaceEventRunner.objects.create(event=event, horse_number="1", horse_name="Existing One")
        RaceEventResult.objects.create(event=event, finish_position=1, horse_name="Existing One")
        RaceEventHistoryWinner.objects.create(event=event, winner_year=2026, horse_name="Existing One")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(tmp_path / "candidates.jsonl", [self._candidate_record()]),
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}
                ),
                run_dir=tmp_path,
            )

            review_rows = list(csv.DictReader(_artifact_path(result, "review_csv").open(encoding="utf-8")))
            self.assertEqual(_field(result, "status"), "passed")
            self.assertEqual(_field(result, "complete_count"), 1)
            self.assertEqual(review_rows[0]["status"], "complete_with_warnings")
            self.assertEqual(review_rows[0]["blocker_codes"], "")
            self.assertIn("existing_data_diff", review_rows[0]["warning_codes"])

    def test_coverage_more_complete_candidate_remains_complete_with_warnings(self):
        module = self._module()
        event = self._race_event()
        RaceEventRunner.objects.create(event=event, horse_number="1", horse_name="Existing One")
        candidate = self._candidate_record()
        candidate["modules"][RaceEventModule.RUNNERS]["items"].append(
            {"horse_number": "2", "horse_name": "Additional Runner"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=self._write_jsonl(tmp_path / "candidates.jsonl", [candidate]),
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}
                ),
                run_dir=tmp_path,
            )

            review_rows = list(csv.DictReader(_artifact_path(result, "review_csv").open(encoding="utf-8")))
            self.assertEqual(_field(result, "complete_count"), 1)
            self.assertEqual(review_rows[0]["status"], "complete_with_warnings")

    def test_resume_reruns_audit_after_candidate_artifact_is_corrected(self):
        self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = self._base_plan(tmp_path, adapters=[])
            plan_path = self._write_json(tmp_path / "plan-source.json", plan)
            candidate_path = self._write_jsonl(tmp_path / "candidates.jsonl", [
                {
                    **self._candidate_record(),
                    "modules": {
                        RaceEventModule.RUNNERS: self._candidate_record()["modules"][RaceEventModule.RUNNERS],
                    },
                }
            ])
            mapping_path = self._write_json(
                tmp_path / "series_mapping.json",
                {"uk-derby": {"status": "approved", "slugs": {"2026": "uk-derby-2026"}}},
            )

            call_command(
                "orchestrate_race_event_crawl",
                "--plan",
                str(plan_path),
                "--stage",
                "audit",
                "--candidate-jsonl",
                str(candidate_path),
                "--series-mapping",
                str(mapping_path),
                "--run-dir",
                str(tmp_path),
                stdout=StringIO(),
            )
            first_audit = json.loads((tmp_path / "coverage_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(first_audit["status"], "blocked")

            self._write_jsonl(candidate_path, [self._candidate_record()])
            call_command(
                "orchestrate_race_event_crawl",
                "--stage",
                "resume",
                "--state",
                str(tmp_path / "state.json"),
                stdout=StringIO(),
            )

            resumed_audit = json.loads((tmp_path / "coverage_audit.json").read_text(encoding="utf-8"))
            resumed_state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(resumed_audit["status"], "passed")
            self.assertEqual(resumed_state["stage"], "audit")
            self.assertEqual(resumed_state["resume_history"][-1]["status"], "succeeded")


class RaceEventCrawlFirstAcceptanceFixtureTests(RaceEventCrawlOrchestrationTestCase):
    def test_first_acceptance_fixture_requires_all_five_regions_and_three_modules(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = self._base_plan(tmp_path, first_acceptance=True)
            plan["regions"] = [
                {
                    "region": region,
                    "source": source,
                    "source_authority": authority,
                    "series": [{"series_key": f"{region}-core", "slugs": {"2026": f"{region}-core-2026"}, "years": {"start": 2026, "end": 2026}}],
                    "modules": {module_name: {"years": {"start": 2026, "end": 2026}} for module_name in TARGET_MODULES},
                }
                for region, source, authority in [
                    (RacingRegion.JAPAN, "jra", "official"),
                    (RacingRegion.HONG_KONG, "hkjc", "official"),
                    (RacingRegion.UNITED_KINGDOM, "sporting_life", "third_party_high_access"),
                    (RacingRegion.FRANCE, "zeturf", "third_party_high_access"),
                    (RacingRegion.UNITED_STATES, "toba", "reference"),
                ]
            ]
            plan["adapters"] = [
                "jra_detail",
                "jra_history_winners",
                "hkjc_detail",
                "hkjc_history_winners",
                "uk_sporting_life_detail",
                "uk_sporting_life_history_winners",
                "france_zeturf_detail",
                "france_wikipedia_history_winners",
                "us_hrn_detail",
                "us_toba_history_winners",
            ]

            result = module.validate_first_acceptance_fixture(self._write_json(tmp_path / "first_acceptance.json", plan))

            self.assertEqual(
                set(_field(result, "regions")),
                {
                    RacingRegion.JAPAN,
                    RacingRegion.HONG_KONG,
                    RacingRegion.UNITED_KINGDOM,
                    RacingRegion.FRANCE,
                    RacingRegion.UNITED_STATES,
                },
            )
            self.assertEqual(set(_field(result, "modules")), set(TARGET_MODULES))
            self.assertEqual(_field(result, "missing_regions"), [])
            self.assertEqual(_field(result, "adapter_selection_errors"), [])

    def test_first_acceptance_rejects_missing_region_adapter_coverage(self):
        module = self._module()
        fixture = Path("server/stable/fixtures/race_event_crawl/first_acceptance_plan.json")
        plan = json.loads(fixture.read_text(encoding="utf-8"))
        plan["adapters"] = [
            key for key in plan["adapters"] if key != "france_wikipedia_history_winners"
        ]

        with self.assertRaisesMessage(module.PlanValidationError, "france"):
            module.validate_first_acceptance_plan(plan)


class RaceEventCrawlApplyCheckTests(RaceEventCrawlOrchestrationTestCase):
    def test_confirmation_requires_explicit_approval_operator_and_timestamp(self):
        module = self._module()
        scope = {
            "region": RacingRegion.UNITED_KINGDOM,
            "source": "sporting_life",
            "modules": TARGET_MODULES,
        }

        self.assertFalse(module._has_matching_confirmation([scope], scope))
        self.assertFalse(
            module._has_matching_confirmation(
                [self._approved_confirmation(scope, status="pending")],
                scope,
            )
        )
        self.assertFalse(
            module._has_matching_confirmation(
                [self._approved_confirmation(scope, confirmed_by="")],
                scope,
            )
        )
        self.assertFalse(
            module._has_matching_confirmation(
                [self._approved_confirmation(scope, confirmed_at="")],
                scope,
            )
        )
        self.assertTrue(
            module._has_matching_confirmation(
                [self._approved_confirmation(scope)],
                scope,
            )
        )

    def test_apply_check_blocks_missing_confirmation_dry_run_backup_health_and_lock_evidence(self):
        module = self._module()
        ExternalDataImportRun.objects.create(
            source=ExternalDataSource.HKJC,
            racing_region=RacingRegion.HONG_KONG,
            source_language=SourceLanguage.ENGLISH,
            target_type="race",
            status=ExternalImportStatus.STARTED,
            dry_run=True,
        )
        ExternalDataImportLock.objects.create(source=ExternalDataSource.HKJC, racing_region=RacingRegion.HONG_KONG)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = module.evaluate_apply_check(
                run_dir=tmp_path,
                coverage_audit={"status": "passed", "blockers": []},
                dry_run_artifact=None,
                confirmations=[],
                production_evidence={},
                apply_scope={"region": RacingRegion.HONG_KONG, "source": "hkjc", "modules": TARGET_MODULES},
            )

            codes = set(_field(result, "blocker_codes"))
            self.assertIn("first_batch_confirmation_missing", codes)
            self.assertIn("dry_run_missing", codes)
            self.assertIn("backup_evidence_missing", codes)
            self.assertIn("health_check_missing", codes)
            self.assertIn("external_import_lock_active", codes)
            self.assertFalse(_field(result, "is_apply_allowed"))

    def test_apply_check_generates_explicit_apply_command_without_executing_apply(self):
        module = self._module()
        event = self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            candidate_jsonl = self._write_jsonl(tmp_path / "candidate.jsonl", [self._candidate_record()])
            coverage = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=candidate_jsonl,
                series_mapping_path=self._write_json(tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}),
                run_dir=tmp_path,
            )
            dry_run = self._write_json(
                tmp_path / "dry_run.json",
                {"status": "passed", "candidate_identity": module.file_identity(candidate_jsonl)},
            )
            backup = self._write_gzip(tmp_path / "pre-apply.sql.gz")
            result = module.evaluate_apply_check(
                run_dir=tmp_path,
                coverage_audit=coverage,
                dry_run_artifact=dry_run,
                confirmations=[
                    {
                        "region": RacingRegion.UNITED_KINGDOM,
                        "source": "sporting_life",
                        "modules": TARGET_MODULES,
                        "status": "approved",
                        "confirmed_by": "operator",
                        "confirmed_at": "2026-07-10T04:30:00+08:00",
                    }
                ],
                production_evidence={
                    "healthz": {"status": "ok"},
                    "external_import_locks_empty": True,
                    "backup_path": str(backup),
                    "backup_gzip_test": "passed",
                    "diff_review": {"status": "approved"},
                },
                apply_scope={"region": RacingRegion.UNITED_KINGDOM, "source": "sporting_life", "modules": TARGET_MODULES},
            )

            self.assertTrue(_field(result, "is_apply_allowed"))
            self.assertIn("import_race_event_detail_candidates", _field(result, "apply_command"))
            self.assertIn("--apply", _field(result, "apply_command"))
            self.assertIn("--expected-sha256", _field(result, "apply_command"))
            approved_path = Path(_field(result, "approved_candidate_identity")["path"])
            self.assertTrue(approved_path.exists())
            self.assertIn(str(approved_path), _field(result, "apply_command"))
            self.assertEqual(event.data_candidates.count(), 0)

            approved_path.chmod(0o644)
            approved_path.write_text('{"tampered": true}\n', encoding="utf-8")
            with self.assertRaisesMessage(CommandError, "candidate_sha256_mismatch"):
                call_command(
                    "import_race_event_detail_candidates",
                    "--jsonl",
                    str(approved_path),
                    "--expected-sha256",
                    _field(result, "candidate_identity")["sha256"],
                    "--apply",
                    stdout=StringIO(),
                )
            self.assertEqual(event.data_candidates.count(), 0)

    def test_apply_check_ignores_persistent_idle_lock_rows(self):
        module = self._module()
        self._race_event()
        ExternalDataImportLock.objects.create(
            source=ExternalDataSource.HKJC,
            racing_region=RacingRegion.HONG_KONG,
            locked_by_run=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            candidate_jsonl = self._write_jsonl(tmp_path / "candidate.jsonl", [self._candidate_record()])
            candidate_identity = module.file_identity(candidate_jsonl)
            dry_run = self._write_json(
                tmp_path / "dry_run.json",
                {"status": "passed", "candidate_identity": candidate_identity},
            )
            plan_path = self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path))
            module.ensure_expected_targets_snapshot(
                plan=self._base_plan(tmp_path),
                plan_path=plan_path,
                run_dir=tmp_path,
            )
            expected_identity = module.file_identity(tmp_path / "expected_targets.json")
            backup = self._write_gzip(tmp_path / "backup.sql.gz")

            result = module.evaluate_apply_check(
                run_dir=tmp_path,
                coverage_audit={
                    "status": "passed",
                    "blockers": [],
                    "candidate_jsonl": str(candidate_jsonl),
                    "candidate_identity": candidate_identity,
                    "expected_targets_identity": expected_identity,
                    "actual_apply_scopes": [
                        {
                            "region": RacingRegion.UNITED_KINGDOM,
                            "source": "sporting_life",
                            "modules": TARGET_MODULES,
                        }
                    ],
                },
                dry_run_artifact=dry_run,
                confirmations=[
                    self._approved_confirmation(
                        {
                            "region": RacingRegion.UNITED_KINGDOM,
                            "source": "sporting_life",
                            "modules": TARGET_MODULES,
                        }
                    )
                ],
                production_evidence={
                    "healthz": {"status": "ok"},
                    "external_import_locks_empty": True,
                    "backup_path": str(backup),
                    "backup_gzip_test": "passed",
                    "diff_review": {"status": "approved"},
                },
                apply_scope={
                    "region": RacingRegion.UNITED_KINGDOM,
                    "source": "sporting_life",
                    "modules": TARGET_MODULES,
                },
            )

            self.assertTrue(_field(result, "is_apply_allowed"))
            self.assertNotIn("external_import_lock_active", _field(result, "blocker_codes"))

    def test_apply_check_rejects_candidate_swap_and_invalid_dry_run_artifact(self):
        module = self._module()
        self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            candidate_a = self._write_jsonl(tmp_path / "candidate-a.jsonl", [self._candidate_record()])
            candidate_b = self._write_jsonl(
                tmp_path / "candidate-b.jsonl",
                [self._candidate_record(source_url="https://source.test/swapped")],
            )
            coverage = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=candidate_a,
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}
                ),
                run_dir=tmp_path,
            )
            invalid_dry_run = self._write_json(tmp_path / "dry-run.json", {"status": "failed"})
            result = module.evaluate_apply_check(
                run_dir=tmp_path,
                coverage_audit=coverage,
                dry_run_artifact=invalid_dry_run,
                confirmations=[],
                production_evidence={},
                apply_scope={},
                candidate_jsonl=candidate_b,
            )

            codes = set(_field(result, "blocker_codes"))
            self.assertIn("candidate_evidence_mismatch", codes)
            self.assertIn("dry_run_not_passed", codes)
            self.assertIn("dry_run_candidate_identity_missing", codes)
            self.assertFalse(_field(result, "is_apply_allowed"))

    def test_apply_check_rejects_coverage_from_a_different_expected_snapshot(self):
        module = self._module()
        self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            candidate = self._write_jsonl(tmp_path / "candidate.jsonl", [self._candidate_record()])
            coverage = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=candidate,
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}
                ),
                run_dir=tmp_path,
            )
            expected_path = tmp_path / "expected_targets.json"
            changed_expected = json.loads(expected_path.read_text(encoding="utf-8"))
            changed_expected["generated_at"] = "2026-07-11T09:30:00+08:00"
            self._write_json(expected_path, changed_expected)

            result = module.evaluate_apply_check(
                run_dir=tmp_path,
                coverage_audit=coverage,
                dry_run_artifact=None,
                confirmations=[],
                production_evidence={},
                apply_scope={},
                candidate_jsonl=candidate,
            )

            self.assertIn("expected_targets_evidence_mismatch", _field(result, "blocker_codes"))
            self.assertFalse(_field(result, "is_apply_allowed"))

    def test_apply_check_rejects_fake_gzip_even_when_evidence_claims_passed(self):
        module = self._module()
        self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            candidate = self._write_jsonl(tmp_path / "candidate.jsonl", [self._candidate_record()])
            coverage = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=candidate,
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}
                ),
                run_dir=tmp_path,
            )
            dry_run = self._write_json(
                tmp_path / "dry-run.json",
                {"status": "passed", "candidate_identity": module.file_identity(candidate)},
            )
            fake_backup = tmp_path / "fake.sql.gz"
            fake_backup.write_bytes(b"not gzip")
            scope = {
                "region": RacingRegion.UNITED_KINGDOM,
                "source": "sporting_life",
                "modules": TARGET_MODULES,
            }

            result = module.evaluate_apply_check(
                run_dir=tmp_path,
                coverage_audit=coverage,
                dry_run_artifact=dry_run,
                confirmations=[scope],
                production_evidence={
                    "healthz": {"status": "ok"},
                    "external_import_locks_empty": True,
                    "backup_path": str(fake_backup),
                    "backup_gzip_test": "passed",
                    "diff_review": {"status": "approved"},
                },
                apply_scope=scope,
            )

            self.assertIn("backup_evidence_missing", _field(result, "blocker_codes"))
            self.assertEqual(_field(result, "backup_validation")["reason"], "gzip_invalid")
            self.assertFalse(_field(result, "is_apply_allowed"))

    def test_apply_check_rejects_missing_backup_and_unapproved_diff_review(self):
        module = self._module()
        self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            candidate = self._write_jsonl(tmp_path / "candidate.jsonl", [self._candidate_record()])
            identity = module.file_identity(candidate)
            dry_run = self._write_json(
                tmp_path / "dry-run.json", {"status": "passed", "candidate_identity": identity}
            )
            result = module.evaluate_apply_check(
                run_dir=tmp_path,
                coverage_audit={
                    "status": "passed",
                    "blockers": [],
                    "candidate_jsonl": str(candidate),
                    "candidate_identity": identity,
                },
                dry_run_artifact=dry_run,
                confirmations=[
                    {
                        "region": RacingRegion.UNITED_KINGDOM,
                        "source": "sporting_life",
                        "modules": TARGET_MODULES,
                    }
                ],
                production_evidence={
                    "healthz": {"status": "ok"},
                    "external_import_locks_empty": True,
                    "backup_path": str(tmp_path / "missing.sql.gz"),
                    "backup_gzip_test": "passed",
                    "diff_review": {"status": "rejected"},
                },
                apply_scope={
                    "region": RacingRegion.UNITED_KINGDOM,
                    "source": "sporting_life",
                    "modules": TARGET_MODULES,
                },
            )

            self.assertIn("backup_evidence_missing", _field(result, "blocker_codes"))
            self.assertIn("diff_review_not_approved", _field(result, "blocker_codes"))
            self.assertFalse(_field(result, "is_apply_allowed"))

    def test_apply_check_requires_confirmation_for_actual_mixed_source_strategy(self):
        module = self._module()
        self._race_event()
        detail = self._candidate_record(source_url="https://source.test/detail")
        detail["modules"] = {
            RaceEventModule.RUNNERS: detail["modules"][RaceEventModule.RUNNERS],
            RaceEventModule.RESULTS: detail["modules"][RaceEventModule.RESULTS],
        }
        history = self._candidate_record(source_url="https://source.test/history")
        history["source_name"] = "toba"
        history["source_provider"] = "toba"
        history["source_authority"] = "reference"
        history["modules"] = {
            RaceEventModule.HISTORY_WINNERS: history["modules"][RaceEventModule.HISTORY_WINNERS]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            candidate_jsonl = self._write_jsonl(tmp_path / "candidate.jsonl", [detail, history])
            coverage = module.audit_coverage(
                plan_path=self._write_json(tmp_path / "plan.json", self._base_plan(tmp_path)),
                candidate_jsonl=candidate_jsonl,
                series_mapping_path=self._write_json(
                    tmp_path / "series_mapping.json", {"uk-derby": {"status": "approved"}}
                ),
                run_dir=tmp_path,
            )
            strategy_sha256 = coverage["mixed_source_strategies"][0]["strategy_sha256"]
            dry_run = self._write_json(
                tmp_path / "dry-run.json",
                {"status": "passed", "candidate_identity": module.file_identity(candidate_jsonl)},
            )
            evidence = {
                "healthz": {"status": "ok"},
                "external_import_locks_empty": True,
                "backup_path": str(tmp_path / "backup.sql.gz"),
                "backup_gzip_test": "passed",
                "diff_review": {"status": "approved"},
            }
            self._write_gzip(Path(evidence["backup_path"]))
            sporting_life_scope = {
                "region": RacingRegion.UNITED_KINGDOM,
                "source": "sporting_life",
                "modules": [RaceEventModule.RUNNERS, RaceEventModule.RESULTS],
            }
            toba_scope = {
                "region": RacingRegion.UNITED_KINGDOM,
                "source": "toba",
                "modules": [RaceEventModule.HISTORY_WINNERS],
            }
            incomplete_scope = {
                "region": RacingRegion.UNITED_KINGDOM,
                "source": "sporting_life",
                "modules": TARGET_MODULES,
            }
            confirmation = self._approved_confirmation(sporting_life_scope)
            blocked = module.evaluate_apply_check(
                run_dir=tmp_path,
                coverage_audit=coverage,
                dry_run_artifact=dry_run,
                confirmations=[confirmation],
                production_evidence=evidence,
                apply_scope=incomplete_scope,
            )
            self.assertIn("apply_scope_mismatch", _field(blocked, "blocker_codes"))
            self.assertIn("confirmation_missing", _field(blocked, "blocker_codes"))
            self.assertIn("first_batch_confirmation_missing", _field(blocked, "blocker_codes"))

            pending_strategy = module.evaluate_apply_check(
                run_dir=tmp_path,
                coverage_audit=coverage,
                dry_run_artifact=dry_run,
                confirmations=[
                    confirmation,
                    self._approved_confirmation(toba_scope),
                    {
                        "status": "pending",
                        "confirmed_by": "operator",
                        "confirmed_at": "2026-07-10T04:30:00+08:00",
                        "mixed_source_strategy_sha256s": [strategy_sha256],
                    },
                ],
                production_evidence=evidence,
                apply_scope={"scopes": [sporting_life_scope, toba_scope]},
            )
            self.assertIn(
                "mixed_source_confirmation_missing",
                _field(pending_strategy, "blocker_codes"),
            )

            confirmation["mixed_source_strategy_sha256s"] = [strategy_sha256]
            source_cache = tmp_path / "source" / "official.html"
            source_cache.parent.mkdir(parents=True, exist_ok=True)
            source_cache.write_bytes(b"official evidence")
            source_cache_identity = module.file_identity(source_cache)
            self._write_json(
                tmp_path / "source_cache_manifest.json",
                {
                    "schema_version": "1.0",
                    "root": str(tmp_path),
                    "files": {
                        "source/official.html": {
                            **source_cache_identity,
                            "path": "source/official.html",
                            "source_url": "https://official.test/result",
                            "protected_by": [],
                        }
                    },
                },
            )
            allowed = module.evaluate_apply_check(
                run_dir=tmp_path,
                coverage_audit=coverage,
                dry_run_artifact=dry_run,
                confirmations=[confirmation, self._approved_confirmation(toba_scope)],
                production_evidence=evidence,
                apply_scope={"scopes": [sporting_life_scope, toba_scope]},
            )
            self.assertTrue(_field(allowed, "is_apply_allowed"))
            protected_manifest = json.loads(
                (tmp_path / "source_cache_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                protected_manifest["files"]["source/official.html"]["protected_by"],
                [_field(allowed, "approved_candidate_identity")["sha256"]],
            )


class RaceEventCrawlRunStateTests(RaceEventCrawlOrchestrationTestCase):
    def test_dry_run_apply_check_and_resume_persist_full_run_state(self):
        self._race_event()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_path = self._write_json(
                tmp_path / "plan-source.json",
                self._base_plan(tmp_path, adapters=[]),
            )
            candidate_jsonl = self._write_jsonl(
                tmp_path / "candidate.jsonl", [self._candidate_record()]
            )
            mapping = self._write_json(
                tmp_path / "series-mapping.json", {"uk-derby": {"status": "approved"}}
            )
            call_command(
                "orchestrate_race_event_crawl",
                "--plan",
                str(plan_path),
                "--stage",
                "audit",
                "--candidate-jsonl",
                str(candidate_jsonl),
                "--series-mapping",
                str(mapping),
                "--run-dir",
                str(tmp_path),
                stdout=StringIO(),
            )
            call_command(
                "orchestrate_race_event_crawl",
                "--plan",
                str(plan_path),
                "--stage",
                "dry-run",
                "--candidate-jsonl",
                str(candidate_jsonl),
                "--run-dir",
                str(tmp_path),
                stdout=StringIO(),
            )
            state_path = tmp_path / "state.json"
            dry_run_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(dry_run_state["stage"], "dry-run")
            self.assertIn("dry-run", dry_run_state["completed_stages"])
            self.assertEqual(dry_run_state["artifacts"]["dry_run"], str(tmp_path / "dry_run.json"))

            confirmations = self._write_json(
                tmp_path / "confirmations.json",
                {
                    "confirmations": [
                        {
                            "region": RacingRegion.UNITED_KINGDOM,
                            "source": "sporting_life",
                            "modules": TARGET_MODULES,
                            "status": "approved",
                            "confirmed_by": "operator",
                            "confirmed_at": "2026-07-10T04:30:00+08:00",
                        }
                    ]
                },
            )
            backup = tmp_path / "backup.sql.gz"
            self._write_gzip(backup)
            evidence = self._write_json(
                tmp_path / "production-evidence.json",
                {
                    "healthz": {"status": "ok"},
                    "external_import_locks_empty": True,
                    "backup_path": str(backup),
                    "backup_gzip_test": "passed",
                    "diff_review": {"status": "approved"},
                },
            )
            scope = self._write_json(
                tmp_path / "apply-scope.json",
                {
                    "region": RacingRegion.UNITED_KINGDOM,
                    "source": "sporting_life",
                    "modules": TARGET_MODULES,
                },
            )
            call_command(
                "orchestrate_race_event_crawl",
                "--plan",
                str(plan_path),
                "--stage",
                "apply-check",
                "--coverage-audit",
                str(tmp_path / "coverage_audit.json"),
                "--dry-run-artifact",
                str(tmp_path / "dry_run.json"),
                "--confirmations",
                str(confirmations),
                "--production-evidence",
                str(evidence),
                "--apply-scope",
                str(scope),
                "--candidate-jsonl",
                str(candidate_jsonl),
                "--run-dir",
                str(tmp_path),
                stdout=StringIO(),
            )
            apply_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(apply_state["stage"], "apply-check")
            self.assertIn("apply-check", apply_state["completed_stages"])
            self.assertEqual(apply_state["artifacts"]["apply_check"], str(tmp_path / "apply_check.json"))

            call_command(
                "orchestrate_race_event_crawl",
                "--stage",
                "resume",
                "--state",
                str(state_path),
                stdout=StringIO(),
            )
            resumed_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(resumed_state["stage"], "apply-check")
            self.assertEqual(resumed_state["resume_history"][-1]["status"], "succeeded")

    def test_failed_dry_run_is_recorded_in_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_path = self._write_json(
                tmp_path / "plan-source.json",
                self._base_plan(tmp_path, adapters=[]),
            )
            missing_event_candidate = self._write_jsonl(
                tmp_path / "missing-event.jsonl",
                [self._candidate_record(year=1999, slug="missing-event-1999")],
            )
            with self.assertRaises(CommandError):
                call_command(
                    "orchestrate_race_event_crawl",
                    "--plan",
                    str(plan_path),
                    "--stage",
                    "dry-run",
                    "--candidate-jsonl",
                    str(missing_event_candidate),
                    "--run-dir",
                    str(tmp_path),
                    stdout=StringIO(),
                )

            state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["stage"], "dry-run_failed")
            self.assertEqual(state["errors"][-1]["stage"], "dry-run")

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "runtime" / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "historical_detail_runner_v2"
V2_MODULE = TOOLS / "historical_race_detail_runner_v2.py"
V2_LAUNCHER = ROOT / "deploy" / "historical_race_detail_runner_v2.sh"
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
STAGES = ["discover", "cache", "parse", "validate", "package"]
TARGET_STATES = {
    "complete",
    "source_exhausted",
    "terminal_review_gap",
    "cancelled",
    "not_held",
    "retryable_gap",
    "unstarted",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _load_tool(name: str):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location(f"{path.stem}_v2_contract_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load production tool: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _load_v2():
    if not V2_MODULE.is_file():
        raise AssertionError(
            "missing v2 production module runtime/tools/historical_race_detail_runner_v2.py"
        )
    return _load_tool(V2_MODULE.name)


def _replace_tokens(value, replacements: dict[str, object]):
    if isinstance(value, dict):
        return {key: _replace_tokens(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_tokens(item, replacements) for item in value]
    if isinstance(value, str):
        if value in replacements:
            return replacements[value]
        for token, replacement in replacements.items():
            if isinstance(replacement, str):
                value = value.replace(token, replacement)
        return value
    return value


def _materialize_descriptor(root: Path) -> tuple[dict, dict[str, Path]]:
    repo_root = root / "repo"
    plan_root = root / "plan"
    run_root = root / "run"
    host_lock_root = root / "host-lock"
    for path in (repo_root, plan_root, run_root, host_lock_root):
        path.mkdir()

    tool_file = repo_root / "runtime" / "tools" / "jra_parser.py"
    tool_file.parent.mkdir(parents=True)
    tool_file.write_text("PARSER_VERSION = 'v2-test'\n", encoding="utf-8")
    plan_file = plan_root / "plan.json"
    plan_file.write_text('{"plan_id":"detail-crawl-1998-2026-v2"}\n', encoding="utf-8")
    events_file = plan_root / "events.csv"
    events_file.write_text(
        "target_id,slug,status,date,course,distance\n"
        "50556,japan-daily-hai-nisai-2005,finished,2005-10-15,Kyoto,1600m\n"
        "50557,japan-fuchu-himba-2005,finished,2005-10-16,Tokyo,1800m\n",
        encoding="utf-8",
    )
    source_file = plan_root / "source-fragment.json"
    source_file.write_text('{"target_count":2}\n', encoding="utf-8")
    recipe_file = plan_root / "recipes.json"
    recipe_file.write_bytes((FIXTURES / "recipes.json").read_bytes())
    descriptor_file = plan_root / "descriptor.json"

    paths = {
        "repo_root": repo_root,
        "plan_root": plan_root,
        "run_root": run_root,
        "host_lock_root": host_lock_root,
        "tool_file": tool_file,
        "plan_file": plan_file,
        "events_file": events_file,
        "source_file": source_file,
        "recipe_file": recipe_file,
        "descriptor_file": descriptor_file,
    }
    replacements: dict[str, object] = {
        "${REPO_ROOT}": str(repo_root),
        "${PLAN_ROOT}": str(plan_root),
        "${RUN_ROOT}": str(run_root),
        "${HOST_LOCK_ROOT}": str(host_lock_root),
        "${TOOL_FILE}": str(tool_file),
        "${TOOL_SIZE}": tool_file.stat().st_size,
        "${TOOL_SHA256}": _sha256(tool_file),
        "${PLAN_FILE}": str(plan_file),
        "${PLAN_SIZE}": plan_file.stat().st_size,
        "${PLAN_SHA256}": _sha256(plan_file),
        "${EVENTS_FILE}": str(events_file),
        "${EVENTS_SIZE}": events_file.stat().st_size,
        "${EVENTS_SHA256}": _sha256(events_file),
        "${SOURCE_FILE}": str(source_file),
        "${SOURCE_SIZE}": source_file.stat().st_size,
        "${SOURCE_SHA256}": _sha256(source_file),
        "${RECIPE_FILE}": str(recipe_file),
        "${RECIPE_SIZE}": recipe_file.stat().st_size,
        "${RECIPE_SHA256}": _sha256(recipe_file),
        "${DESCRIPTOR_FILE}": str(descriptor_file),
    }
    descriptor = _replace_tokens(_load_json("descriptor.valid.json"), replacements)
    descriptor_file.write_text(
        json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return descriptor, paths


def _validate_descriptor(module, descriptor: dict, paths: dict[str, Path]):
    return module.validate_descriptor(
        descriptor,
        descriptor_path=paths["descriptor_file"],
        repo_root=paths["repo_root"],
        plan_root=paths["plan_root"],
        run_root=paths["run_root"],
        host_lock_root=paths["host_lock_root"],
    )


def _complete_candidate() -> dict:
    source_url = "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"
    return {
        "target_id": "50556",
        "status": "complete",
        "event": {
            "date": "2005-10-15",
            "course": "Kyoto",
            "distance": "1600m",
            "source_url": source_url,
        },
        "source_mappings": [
            {"provider": "jra", "source_url": source_url, "target_id": "50556"}
        ],
        "runners": [
            {"horse_number": "1", "horse_name": "Maruka Schenk"},
            {"horse_number": "8", "horse_name": "Diamond Head"},
        ],
        "results": [
            {"finish_position": 1, "horse_number": "1", "horse_name": "Maruka Schenk"},
            {"finish_position": 2, "horse_number": "8", "horse_name": "Diamond Head"},
        ],
        "winner": {"horse_number": "1", "horse_name": "Maruka Schenk"},
    }


def _bind_v1_migration_evidence(
    module,
    source: dict,
    descriptor: dict,
    *,
    evidence_root: Path,
) -> tuple[dict, dict]:
    bound_source = copy.deepcopy(source)
    all_ids = [
        *bound_source["complete_target_ids"],
        *bound_source["gap_target_ids"],
    ]
    complete_ids = set(bound_source["complete_target_ids"])
    targets = []
    for target_id in all_ids:
        target_sha = hashlib.sha256(f"target:{target_id}".encode()).hexdigest()
        target = {"target_id": target_id, "target_sha256": target_sha}
        if target_id in complete_ids:
            candidate = _complete_candidate()
            candidate["target_id"] = target_id
            candidate["source_mappings"][0]["target_id"] = target_id
            evidence_payload = {
                "schema_version": "1.0",
                "plan_id": bound_source["plan_id"],
                "shard_id": bound_source["shard_id"],
                "target_id": target_id,
                "target_sha256": target_sha,
                "candidate": candidate,
            }
            evidence_path = evidence_root / f"{target_id}.json"
            evidence_path.write_text(json.dumps(evidence_payload), encoding="utf-8")
            target["completion_evidence_identity"] = {
                "path": evidence_path.name,
                "size": evidence_path.stat().st_size,
                "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            }
        targets.append(target)
    bound_source["targets"] = targets
    target_set_sha = module.hash_v1_target_set(targets)
    manifest_path = evidence_root / "plan-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "plan_id": bound_source["plan_id"],
                "shard_id": bound_source["shard_id"],
                "target_set_sha256": target_set_sha,
            }
        ),
        encoding="utf-8",
    )
    bound_source["plan_manifest_identity"] = {
        "path": manifest_path.name,
        "size": manifest_path.stat().st_size,
        "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    bound_descriptor = copy.deepcopy(descriptor)
    bound_descriptor["targets"] = copy.deepcopy(targets)
    bound_descriptor["v1_source_identity"] = {
        "plan_id": bound_source["plan_id"],
        "shard_id": bound_source["shard_id"],
        "plan_manifest_identity": copy.deepcopy(bound_source["plan_manifest_identity"]),
        "target_set_sha256": target_set_sha,
    }
    return bound_source, bound_descriptor


class HistoricalDetailRunnerV2FixtureTests(SimpleTestCase):
    def test_descriptor_fixture_is_structurally_self_consistent(self):
        descriptor = _load_json("descriptor.valid.json")
        self.assertEqual(descriptor["schema_version"], "2.0")
        self.assertEqual(descriptor["stages"], STAGES)
        self.assertFalse(descriptor["permissions"]["database"])
        self.assertFalse(descriptor["permissions"]["apply"])
        self.assertEqual(
            {(row["role"], row["mode"]) for row in descriptor["mounts"]},
            {("repo", "ro"), ("plan", "ro"), ("run", "rw"), ("host_lock", "rw")},
        )

    def test_v1_migration_fixture_has_exactly_39_unique_uk_gaps(self):
        fixture = _load_json("v1-migration-uk39.json")
        gaps = fixture["gap_target_ids"]
        self.assertEqual(fixture["region"], "united_kingdom")
        self.assertEqual(len(gaps), 39)
        self.assertEqual(len(set(gaps)), 39)
        self.assertEqual(len({row["url"] for row in fixture["cache_entries"]}), 2)

    def test_recipe_fixture_covers_exactly_five_regions_and_fixed_stages(self):
        fixture = _load_json("recipes.json")
        self.assertEqual(fixture["stages"], STAGES)
        self.assertEqual(
            {row["region"] for row in fixture["recipes"]},
            {"japan", "hong_kong", "united_kingdom", "france", "united_states"},
        )

    def test_jra_2005_fixture_retains_one_header_and_11_legacy_result_rows(self):
        html = (FIXTURES / "jra-2005-replay-legacy.html").read_text(encoding="ascii")
        result_table = html.split('ID="W01D_D2"', 1)[1]
        self.assertEqual(len(re.findall(r"<TR>", result_table, flags=re.IGNORECASE)), 12)
        self.assertIn("2dbe222766b6ed2e9a5c3c60c348ec98896e55acbbefbfdb8d5b3c0e2177bf4a", html)


class HistoricalDetailRunnerV2LauncherTests(SimpleTestCase):
    def test_docker_image_copies_historical_coverage_policies(self):
        dockerfile_exists = DOCKERFILE.is_file()
        dockerignore_exists = DOCKERIGNORE.is_file()
        if not dockerfile_exists and not dockerignore_exists:
            self.skipTest(
                "source-only Docker packaging contract: production image intentionally "
                "omits Dockerfile and .dockerignore"
            )
        self.assertTrue(
            dockerfile_exists and dockerignore_exists,
            "incomplete source tree: Dockerfile and .dockerignore must either both exist "
            "or both be absent from a production image",
        )
        copy_instructions = {
            tuple(line.split())
            for line in DOCKERFILE.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("COPY ")
        }
        self.assertIn(
            ("COPY", "runtime/policies", "/app/runtime/policies"),
            copy_instructions,
        )
        dockerignore_rules = {
            line.strip()
            for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("!runtime/policies/", dockerignore_rules)
        self.assertIn("!runtime/policies/**", dockerignore_rules)

    def test_tracked_launcher_is_shell_valid_and_mounts_only_approved_roots(self):
        self.assertTrue(V2_LAUNCHER.is_file(), f"missing tracked v2 launcher: {V2_LAUNCHER}")
        syntax = subprocess.run(
            ["sh", "-n", str(V2_LAUNCHER)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        text = V2_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("historical_race_detail_runner_v2.py", text)
        self.assertIn("--read-only", text)
        self.assertIn(":ro", text)
        self.assertIn(":rw", text)
        self.assertNotIn("docker compose", text)
        self.assertNotIn("DATABASE_URL", text)
        self.assertNotIn("POSTGRES_", text)
        self.assertNotIn("eval ", text)

    def test_launcher_rejects_apply_database_arbitrary_argv_and_symlinked_roots(self):
        self.assertTrue(V2_LAUNCHER.is_file(), f"missing tracked v2 launcher: {V2_LAUNCHER}")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_repo = root / "repo"
            real_repo.mkdir()
            linked_repo = root / "linked-repo"
            linked_repo.symlink_to(real_repo, target_is_directory=True)
            cases = (
                ["--apply"],
                ["--database-url", "postgres://forbidden"],
                ["--argv", "sh", "-c", "true"],
                ["--repo-root", str(linked_repo)],
            )
            for argv in cases:
                with self.subTest(argv=argv):
                    result = subprocess.run(
                        ["sh", str(V2_LAUNCHER), *argv],
                        cwd=ROOT,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertRegex((result.stdout + result.stderr).lower(), r"reject|forbid|symlink|unsupported")


class HistoricalDetailRunnerV2DescriptorTests(SimpleTestCase):
    def test_valid_v2_descriptor_is_accepted_without_mutating_v1(self):
        module = _load_v2()
        with TemporaryDirectory() as tmp:
            descriptor, paths = _materialize_descriptor(Path(tmp))
            normalized = _validate_descriptor(module, descriptor, paths)
        self.assertEqual(normalized["schema_version"], "2.0")
        self.assertEqual(normalized["stages"], STAGES)

    def test_descriptor_rejects_apply_database_and_arbitrary_argv(self):
        module = _load_v2()
        with TemporaryDirectory() as tmp:
            descriptor, paths = _materialize_descriptor(Path(tmp))
            mutations = (
                ("apply", lambda value: value["permissions"].update({"apply": True})),
                ("database", lambda value: value.update({"database_url": "postgres://forbidden"})),
                ("argv", lambda value: value["recipe"].update({"argv": ["sh", "-c", "true"]})),
            )
            for label, mutate in mutations:
                with self.subTest(label=label):
                    changed = copy.deepcopy(descriptor)
                    mutate(changed)
                    with self.assertRaises(module.RunnerV2Error):
                        _validate_descriptor(module, changed, paths)

    def test_descriptor_rejects_path_escape_and_any_symlink(self):
        module = _load_v2()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor, paths = _materialize_descriptor(root)
            escaped = copy.deepcopy(descriptor)
            escaped["identities"][1]["path"] = str(root / "outside.csv")
            with self.assertRaises(module.RunnerV2Error):
                _validate_descriptor(module, escaped, paths)

            real_events = paths["events_file"]
            linked_events = paths["plan_root"] / "events-linked.csv"
            linked_events.symlink_to(real_events)
            symlinked = copy.deepcopy(descriptor)
            symlinked["identities"][1]["path"] = str(linked_events)
            with self.assertRaises(module.RunnerV2Error):
                _validate_descriptor(module, symlinked, paths)

            linked_descriptor = root / "descriptor-link.json"
            linked_descriptor.symlink_to(paths["descriptor_file"])
            with self.assertRaises(module.RunnerV2Error):
                module.validate_descriptor(
                    descriptor,
                    descriptor_path=linked_descriptor,
                    repo_root=paths["repo_root"],
                    plan_root=paths["plan_root"],
                    run_root=paths["run_root"],
                    host_lock_root=paths["host_lock_root"],
                )


class HistoricalDetailRunnerV2MigrationAndStateTests(SimpleTestCase):
    def test_v1_migration_is_read_only_and_maps_all_uk39_gaps_to_fallback_pending(self):
        module = _load_v2()
        source = _load_json("v1-migration-uk39.json")
        descriptor = {
            "schema_version": "2.0",
            "plan_id": "detail-crawl-1998-2026-v2",
            "shard_id": "united_kingdom-2013-v2",
            "region": "united_kingdom",
        }
        with TemporaryDirectory() as tmp:
            evidence_root = Path(tmp)
            source, descriptor = _bind_v1_migration_evidence(
                module,
                source,
                descriptor,
                evidence_root=evidence_root,
            )
            before = copy.deepcopy(source)
            migrated = module.migrate_v1_progress(
                source,
                descriptor,
                evidence_root=evidence_root,
            )
        self.assertEqual(source, before)
        gap_rows = [row for row in migrated["target_states"] if row["target_id"] in source["gap_target_ids"]]
        self.assertEqual(len(gap_rows), 39)
        self.assertEqual({row["state"] for row in gap_rows}, {"retryable_gap"})
        self.assertEqual({row["reason_code"] for row in gap_rows}, {"fallback_pending"})
        self.assertEqual(migrated["migration"]["source_plan_id"], source["plan_id"])

    def test_v1_cache_migration_preserves_each_url_size_and_sha_identity(self):
        module = _load_v2()
        source = _load_json("v1-migration-uk39.json")
        descriptor = {
            "schema_version": "2.0",
            "plan_id": "v2",
            "shard_id": "uk-v2",
            "region": "united_kingdom",
        }
        with TemporaryDirectory() as tmp:
            evidence_root = Path(tmp)
            source, descriptor = _bind_v1_migration_evidence(
                module,
                source,
                descriptor,
                evidence_root=evidence_root,
            )
            migrated = module.migrate_v1_progress(
                source,
                descriptor,
                evidence_root=evidence_root,
            )
        expected = {
            row["url"]: (row["path"], row["size"], row["sha256"])
            for row in source["cache_entries"]
        }
        actual = {
            row["url"]: (row["path"], row["size"], row["sha256"])
            for row in migrated["cache_entries"]
        }
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(source["cache_entries"]))

    def test_target_states_are_mutually_exclusive(self):
        module = _load_v2()
        scope = [str(index) for index in range(1, 8)]
        rows = [
            {"target_id": target_id, "state": state}
            for target_id, state in zip(scope, sorted(TARGET_STATES), strict=True)
        ]
        summary = module.validate_progress(scope, rows)
        self.assertEqual(set(summary["counts"]), TARGET_STATES)
        duplicate = rows + [{"target_id": "1", "state": "complete"}]
        with self.assertRaises(module.RunnerV2Error):
            module.validate_progress(scope, duplicate)

    def test_global_denominator_is_conserved_and_missing_targets_are_unstarted(self):
        module = _load_v2()
        scope = ["jp-1", "jp-2", "uk-1", "uk-2", "fr-1"]
        rows = [
            {"target_id": "jp-1", "state": "complete"},
            {"target_id": "jp-2", "state": "retryable_gap"},
            {"target_id": "uk-1", "state": "source_exhausted"},
            {"target_id": "uk-2", "state": "not_held"},
        ]
        summary = module.validate_progress(scope, rows)
        self.assertEqual(summary["scope_count"], 5)
        self.assertEqual(sum(summary["counts"].values()), 5)
        self.assertEqual(summary["counts"]["unstarted"], 1)


class HistoricalDetailRunnerV2CompletenessTests(SimpleTestCase):
    def test_zero_row_package_and_empty_complete_are_rejected(self):
        module = _load_v2()
        empty = _complete_candidate()
        empty["runners"] = []
        empty["results"] = []
        empty["winner"] = None
        with self.assertRaises(module.RunnerV2Error):
            module.validate_complete_target(empty, seen_source_urls=set())
        with self.assertRaises(module.RunnerV2Error):
            module.validate_package(["50556"], [])

    def test_complete_requires_mapping_fields_and_unique_numbers_positions_and_url(self):
        module = _load_v2()
        candidate = _complete_candidate()
        normalized = module.validate_complete_target(candidate, seen_source_urls=set())
        self.assertEqual(normalized["winner"]["horse_name"], "Maruka Schenk")

        duplicate_number = copy.deepcopy(candidate)
        duplicate_number["runners"][1]["horse_number"] = "1"
        with self.assertRaises(module.RunnerV2Error):
            module.validate_complete_target(duplicate_number, seen_source_urls=set())

        duplicate_position = copy.deepcopy(candidate)
        duplicate_position["results"][1]["finish_position"] = 1
        with self.assertRaises(module.RunnerV2Error):
            module.validate_complete_target(duplicate_position, seen_source_urls=set())

        seen = {candidate["event"]["source_url"]}
        with self.assertRaises(module.RunnerV2Error):
            module.validate_complete_target(candidate, seen_source_urls=seen)

    def test_jra_2005_legacy_fixture_parses_exactly_11_results_with_winner(self):
        module = _load_tool("prepare_jra_race_detail_candidates.py")
        fixture = FIXTURES / "jra-2005-replay-legacy.html"
        runners, results, metadata = module._parse_detail_page(
            fixture.read_bytes(),
            source_url="https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html",
        )
        self.assertEqual(len(runners), 11)
        self.assertEqual(len(results), 11)
        self.assertEqual(results[0]["finish_position"], 1)
        self.assertEqual(results[0]["horse_name"], "マルカシェンク")
        self.assertEqual(metadata["result_count"], 11)


class HistoricalDetailRunnerV2RecoveryTests(SimpleTestCase):
    def _checkpoint(self) -> dict:
        return {
            "parser_sha256": "a" * 64,
            "stages": {
                "discover": "complete",
                "cache": "started",
                "parse": "unstarted",
                "validate": "unstarted",
                "package": "unstarted",
            },
            "requests": [
                {
                    "url": "https://www.jra.go.jp/datafile/seiseki/replay/2005/98.html",
                    "status": "succeeded",
                    "cache_identity": {"size": 10, "sha256": "1" * 64},
                },
                {
                    "url": "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html",
                    "status": "started",
                },
            ],
        }

    def test_interrupted_started_request_resumes_only_unfinished_cache_url(self):
        module = _load_v2()
        checkpoint = self._checkpoint()
        recovery = module.plan_recovery(
            checkpoint,
            current_parser_sha256="a" * 64,
            cache_identities={
                checkpoint["requests"][0]["url"]: {"size": 10, "sha256": "1" * 64}
            },
        )
        self.assertEqual(recovery["resume_from"], "cache")
        self.assertEqual(recovery["network_urls"], [checkpoint["requests"][1]["url"]])
        self.assertEqual(recovery["reused_cache_urls"], [checkpoint["requests"][0]["url"]])

    def test_corrupt_cache_requeues_only_corrupt_url_and_invalidates_downstream(self):
        module = _load_v2()
        checkpoint = self._checkpoint()
        checkpoint["requests"][1] = {
            "url": checkpoint["requests"][1]["url"],
            "status": "succeeded",
            "cache_identity": {"size": 20, "sha256": "2" * 64},
        }
        recovery = module.plan_recovery(
            checkpoint,
            current_parser_sha256="a" * 64,
            cache_identities={
                checkpoint["requests"][0]["url"]: {"size": 10, "sha256": "f" * 64},
                checkpoint["requests"][1]["url"]: {"size": 20, "sha256": "2" * 64},
            },
        )
        self.assertEqual(recovery["network_urls"], [checkpoint["requests"][0]["url"]])
        self.assertEqual(recovery["invalidated_stages"], ["parse", "validate", "package"])

    def test_parser_change_reuses_verified_cache_and_restarts_offline_parse(self):
        module = _load_v2()
        checkpoint = self._checkpoint()
        checkpoint["stages"] = {stage: "complete" for stage in STAGES}
        checkpoint["requests"] = checkpoint["requests"][:1]
        recovery = module.plan_recovery(
            checkpoint,
            current_parser_sha256="b" * 64,
            cache_identities={
                checkpoint["requests"][0]["url"]: {"size": 10, "sha256": "1" * 64}
            },
        )
        self.assertEqual(recovery["resume_from"], "parse")
        self.assertEqual(recovery["network_urls"], [])
        self.assertEqual(recovery["invalidated_stages"], ["parse", "validate", "package"])


class HistoricalDetailRunnerV2HostLockAndCheckpointTests(SimpleTestCase):
    def test_shared_host_lock_limits_two_processes_and_appends_both_shards(self):
        _load_v2()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "www.jra.go.jp.last-start.json"
            log = root / "www.jra.go.jp.requests.jsonl"
            code = (
                "import importlib.util, pathlib, sys; "
                "p=pathlib.Path(sys.argv[1]); "
                "s=importlib.util.spec_from_file_location('runner_v2_child', p); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                "print(m.reserve_host_start(pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]), "
                "host='www.jra.go.jp', shard_id=sys.argv[4], minimum_interval_seconds=0.2))"
            )
            first = subprocess.run(
                [sys.executable, "-c", code, str(V2_MODULE), str(state), str(log), "shard-a"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            started = time.monotonic()
            second = subprocess.run(
                [sys.executable, "-c", code, str(V2_MODULE), str(state), str(log), "shard-b"],
                text=True,
                capture_output=True,
                check=False,
            )
            elapsed = time.monotonic() - started
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertGreaterEqual(elapsed, 0.17)
            rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["shard_id"] for row in rows], ["shard-a", "shard-b"])

    def test_checkpoint_binds_all_immutable_inputs_but_not_live_shared_last_start_sha(self):
        module = _load_v2()
        with TemporaryDirectory() as tmp:
            descriptor, paths = _materialize_descriptor(Path(tmp))
            cache = paths["run_root"] / "cache-manifest.json"
            output = paths["run_root"] / "package.jsonl"
            shared = paths["host_lock_root"] / "www.jra.go.jp.last-start.json"
            cache.write_text('{"entries":[]}\n', encoding="utf-8")
            output.write_text('{"target_id":"50556"}\n', encoding="utf-8")
            shared.write_text('{"last_start":1}\n', encoding="utf-8")
            artifacts = {"cache": cache, "output": output}
            checkpoint = module.build_checkpoint_identity(
                descriptor,
                artifacts=artifacts,
                shared_host_state_path=shared,
            )
            roles = {row["role"] for row in checkpoint["identities"]}
            self.assertTrue(
                {"plan", "descriptor", "events_csv", "source_fragment", "tool", "image", "recipe", "cache", "output"}
                <= roles
            )
            shared.write_text('{"last_start":2,"other_shard":"appended"}\n', encoding="utf-8")
            self.assertTrue(
                module.checkpoint_matches(
                    checkpoint,
                    descriptor,
                    artifacts=artifacts,
                    shared_host_state_path=shared,
                )
            )
            paths["events_file"].write_text("changed\n", encoding="utf-8")
            self.assertFalse(
                module.checkpoint_matches(
                    checkpoint,
                    descriptor,
                    artifacts=artifacts,
                    shared_host_state_path=shared,
                )
            )


class HistoricalDetailRunnerV2RequestAndAuthorityTests(SimpleTestCase):
    def test_request_budget_is_hard_and_zero_is_not_unlimited(self):
        module = _load_v2()
        with TemporaryDirectory() as tmp:
            descriptor, _paths = _materialize_descriptor(Path(tmp))
        valid_url = "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"
        module.validate_request(descriptor, [], url=valid_url, redirect_chain=[])
        full_ledger = [{"url": valid_url}, {"url": valid_url}]
        with self.assertRaises(module.RunnerV2Error):
            module.validate_request(descriptor, full_ledger, url=valid_url, redirect_chain=[])
        descriptor["request_policy"]["max_requests"] = 0
        with self.assertRaises(module.RunnerV2Error):
            module.validate_request(descriptor, [], url=valid_url, redirect_chain=[])

    def test_initial_host_redirect_host_and_url_pattern_all_fail_closed(self):
        module = _load_v2()
        with TemporaryDirectory() as tmp:
            descriptor, _paths = _materialize_descriptor(Path(tmp))
        valid_url = "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"
        invalid_cases = (
            ("https://attacker.example/replay/2005/99.html", []),
            (valid_url, ["https://attacker.example/final"]),
            ("https://www.jra.go.jp/news/2005/99.html", []),
            ("http://www.jra.go.jp/datafile/seiseki/replay/2005/99.html", []),
        )
        for url, redirects in invalid_cases:
            with self.subTest(url=url, redirects=redirects):
                with self.assertRaises(module.RunnerV2Error):
                    module.validate_request(descriptor, [], url=url, redirect_chain=redirects)

    def test_request_ledger_hash_chain_detects_boundary_tampering(self):
        module = _load_v2()
        rows: list[dict] = []
        rows = module.append_request_record(
            rows,
            {"shard_id": "jp-a", "url": "https://www.jra.go.jp/datafile/seiseki/replay/2005/98.html"},
        )
        rows = module.append_request_record(
            rows,
            {"shard_id": "jp-a", "url": "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"},
        )
        self.assertEqual(rows[0]["previous_hash"], "0" * 64)
        self.assertEqual(rows[1]["previous_hash"], rows[0]["record_hash"])
        module.verify_request_hash_chain(rows)
        tampered = copy.deepcopy(rows)
        tampered[0]["url"] = "https://attacker.example/tampered"
        with self.assertRaises(module.RunnerV2Error):
            module.verify_request_hash_chain(tampered)

    def test_lower_authority_conflict_is_logged_and_never_overwrites_official_field(self):
        module = _load_v2()
        merged = module.merge_authoritative_fields(
            "50556",
            [
                {
                    "provider": "jra",
                    "authority": "official",
                    "fields": {"date": "2005-10-15", "winner": "Maruka Schenk"},
                },
                {
                    "provider": "netkeiba",
                    "authority": "fallback",
                    "fields": {"date": "2005-10-16", "winner": "Wrong Horse"},
                },
            ],
        )
        self.assertEqual(merged["fields"]["date"], "2005-10-15")
        self.assertEqual(merged["fields"]["winner"], "Maruka Schenk")
        self.assertEqual({row["field"] for row in merged["review_ledger"]}, {"date", "winner"})

    def test_fallback_may_fill_missing_field_without_replacing_official_value(self):
        module = _load_v2()
        merged = module.merge_authoritative_fields(
            "50556",
            [
                {
                    "provider": "jra",
                    "authority": "official",
                    "fields": {"date": "2005-10-15", "winner": "Maruka Schenk"},
                },
                {
                    "provider": "netkeiba",
                    "authority": "fallback",
                    "fields": {"date": "2005-10-15", "winner_jockey": "Yuichi Fukunaga"},
                },
            ],
        )
        self.assertEqual(merged["fields"]["winner"], "Maruka Schenk")
        self.assertEqual(merged["fields"]["winner_jockey"], "Yuichi Fukunaga")
        self.assertEqual(merged["review_ledger"], [])


class HistoricalDetailRunnerV2RecipeTests(SimpleTestCase):
    def test_five_region_recipes_use_fixed_pipeline_and_no_shell_or_database_recipe(self):
        module = _load_v2()
        fixture = _load_json("recipes.json")
        normalized = module.validate_recipes(fixture)
        self.assertEqual(normalized["stages"], STAGES)
        self.assertEqual(set(normalized["by_region"]), {"japan", "hong_kong", "united_kingdom", "france", "united_states"})
        serialized = json.dumps(normalized, ensure_ascii=False).lower()
        self.assertNotIn('"argv"', serialized)
        self.assertNotIn('"shell"', serialized)
        self.assertNotIn('"database"', serialized)
        self.assertNotIn('"apply"', serialized)

    def test_jp_us_uk_fr_have_explicit_fallback_and_hk_requires_discovery(self):
        module = _load_v2()
        normalized = module.validate_recipes(_load_json("recipes.json"))
        recipes = normalized["by_region"]
        for region in ("japan", "united_states", "united_kingdom", "france"):
            with self.subTest(region=region):
                self.assertTrue(recipes[region]["fallback_sources"])
        hong_kong = recipes["hong_kong"]
        self.assertTrue(hong_kong["discovery"]["required"])
        self.assertEqual(hong_kong["discovery"]["provider"], "hkjc")
        self.assertEqual(hong_kong["discovery"]["url_strategy"], "discovery_only")
        self.assertEqual(hong_kong["fallback_sources"], [])

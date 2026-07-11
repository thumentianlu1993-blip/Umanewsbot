from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import os
import shlex
import sys
import shutil
import subprocess
from functools import lru_cache
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from stable.models import (
    ExternalDataImportLock,
    ExternalDataImportRun,
    ExternalImportStatus,
    HistoricalRaceEventTarget,
    HistoricalRaceResolutionStatus,
    RaceEvent,
    RaceEventModule,
    RacingRegion,
)
from stable.services.historical_race_batches import target_identity


TARGET_LAYER = "race_event"
TARGET_REGIONS = {
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.UNITED_KINGDOM,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
}
TARGET_MODULES = [
    RaceEventModule.RUNNERS,
    RaceEventModule.RESULTS,
    RaceEventModule.HISTORY_WINNERS,
]
SOURCE_AUTHORITY_LEVELS = {"official", "third_party_high_access", "third_party", "reference"}
REPO_ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _source_cache_tool():
    path = REPO_ROOT / "runtime" / "tools" / "race_event_source_cache.py"
    spec = importlib.util.spec_from_file_location("race_event_source_cache_for_orchestration", path)
    if spec is None or spec.loader is None:
        raise PlanValidationError(f"source cache protection tool is unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def protect_approved_run_source_cache(run_dir: str | Path, *, artifact_sha256: str) -> dict[str, Any]:
    run_path = Path(run_dir)
    manifest_path = run_path / "source_cache_manifest.json"
    if not manifest_path.is_file():
        return {"status": "not_present", "protected_count": 0}
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError, PlanValidationError) as exc:
        raise PlanValidationError(f"source cache manifest cannot be protected: {exc}") from exc
    files = manifest.get("files") if isinstance(manifest.get("files"), dict) else None
    if files is None:
        raise PlanValidationError("source cache manifest cannot be protected: files are invalid")
    paths = sorted(files)
    try:
        _source_cache_tool().protect_source_cache_files(
            manifest_path,
            paths,
            artifact_sha256=artifact_sha256,
        )
    except Exception as exc:
        raise PlanValidationError(f"source cache protection failed: {exc}") from exc
    return {"status": "protected", "protected_count": len(paths)}


DEFAULT_SOURCE_AUTHORITY_MATRIX = {
    "jra": {"authority": "official", "region": RacingRegion.JAPAN, "notes": "JRA official race detail and graded race pages."},
    "nar": {"authority": "official", "region": RacingRegion.JAPAN, "notes": "NAR / keiba.go.jp official race detail pages."},
    "hkjc": {"authority": "official", "region": RacingRegion.HONG_KONG, "notes": "HKJC official result and key race pages."},
    "sporting_life": {
        "authority": "third_party_high_access",
        "region": RacingRegion.UNITED_KINGDOM,
        "notes": "High-access third-party result and previous-winners pages.",
    },
    "zeturf": {
        "authority": "third_party_high_access",
        "region": RacingRegion.FRANCE,
        "notes": "High-access third-party runner/result pages for France.",
    },
    "france_wikipedia": {"authority": "reference", "region": RacingRegion.FRANCE, "notes": "Reference source for historical winners only."},
    "horse_racing_nation": {
        "authority": "third_party_high_access",
        "region": RacingRegion.UNITED_STATES,
        "notes": "High-access third-party runner/result pages for US stakes.",
    },
    "equibase": {"authority": "third_party", "region": RacingRegion.UNITED_STATES, "notes": "PDF chart result extraction path."},
    "toba": {"authority": "reference", "region": RacingRegion.UNITED_STATES, "notes": "TOBA annual graded stakes pages for historical winners."},
}


DEFAULT_ADAPTER_MANIFESTS: dict[str, dict[str, Any]] = {
    "jra_detail": {
        "key": "jra_detail",
        "region": RacingRegion.JAPAN,
        "source": "jra",
        "modules": [RaceEventModule.RUNNERS, RaceEventModule.RESULTS],
        "source_authority": "official",
        "requires_network": True,
        "command": [
            "{python}",
            "runtime/tools/prepare_jra_race_detail_candidates.py",
            "--events-csv",
            "{events_csv}",
            "--source-html",
            "{source_html}",
            "--output-dir",
            "{adapter_output_dir}",
            "{network_flag}",
        ],
        "inputs": {
            "events_csv": {"required": True, "artifact": "input/events.csv"},
            "source_html": {"required": True, "artifact": "source/jra.html"},
        },
        "outputs": [
            {"key": "candidate_jsonl", "path": "jra_detail_candidates_2026.jsonl", "standard_name": "candidates/jra_detail.jsonl", "required": True},
            {"key": "review_csv", "path": "jra_detail_review_2026.csv", "standard_name": "review/jra_detail.csv", "required": True},
            {"key": "summary", "path": "summary.json", "standard_name": "summary/jra_detail.json", "required": True},
        ],
    },
    "nar_detail": {
        "key": "nar_detail",
        "region": RacingRegion.JAPAN,
        "source": "nar",
        "modules": [RaceEventModule.RUNNERS, RaceEventModule.RESULTS],
        "source_authority": "official",
        "requires_network": True,
        "command": ["{python}", "runtime/tools/prepare_nar_race_detail_candidates.py", "--events-csv", "{events_csv}", "--output-dir", "{adapter_output_dir}", "{network_flag}"],
        "inputs": {"events_csv": {"required": True, "artifact": "input/events.csv"}},
        "outputs": [
            {"key": "candidate_jsonl", "path": "nar_detail_candidates_2026.jsonl", "standard_name": "candidates/nar_detail.jsonl", "required": True},
            {"key": "review_csv", "path": "nar_detail_review_2026.csv", "standard_name": "review/nar_detail.csv", "required": True},
            {"key": "summary", "path": "summary.json", "standard_name": "summary/nar_detail.json", "required": True},
        ],
    },
    "hkjc_detail": {
        "key": "hkjc_detail",
        "region": RacingRegion.HONG_KONG,
        "source": "hkjc",
        "modules": [RaceEventModule.RUNNERS, RaceEventModule.RESULTS],
        "source_authority": "official",
        "requires_network": True,
        "command": ["{python}", "runtime/tools/prepare_hkjc_race_detail_candidates.py", "--events-csv", "{events_csv}", "--output-dir", "{adapter_output_dir}", "{network_flag}"],
        "inputs": {"events_csv": {"required": True, "artifact": "input/events.csv"}},
        "outputs": [
            {"key": "candidate_jsonl", "path": "hkjc_detail_candidates_2026.jsonl", "standard_name": "candidates/hkjc_detail.jsonl", "required": True},
            {"key": "review_csv", "path": "hkjc_detail_review_2026.csv", "standard_name": "review/hkjc_detail.csv", "required": True},
            {"key": "summary", "path": "summary.json", "standard_name": "summary/hkjc_detail.json", "required": True},
        ],
    },
    "uk_sporting_life_detail": {
        "key": "uk_sporting_life_detail",
        "region": RacingRegion.UNITED_KINGDOM,
        "source": "sporting_life",
        "modules": [RaceEventModule.RUNNERS, RaceEventModule.RESULTS],
        "source_authority": "third_party_high_access",
        "requires_network": True,
        "command": ["{python}", "runtime/tools/prepare_uk_sportinglife_race_detail_candidates.py", "--events-csv", "{events_csv}", "--output-dir", "{adapter_output_dir}", "{network_flag}"],
        "inputs": {"events_csv": {"required": True, "artifact": "input/events.csv"}},
        "outputs": [
            {"key": "candidate_jsonl", "path": "uk_sportinglife_detail_candidates_2026.jsonl", "standard_name": "candidates/uk_sporting_life_detail.jsonl", "required": True},
            {"key": "review_csv", "path": "uk_sportinglife_detail_review_2026.csv", "standard_name": "review/uk_sporting_life_detail.csv", "required": True},
            {"key": "summary", "path": "summary.json", "standard_name": "summary/uk_sporting_life_detail.json", "required": True},
        ],
    },
    "france_zeturf_detail": {
        "key": "france_zeturf_detail",
        "region": RacingRegion.FRANCE,
        "source": "zeturf",
        "modules": [RaceEventModule.RUNNERS, RaceEventModule.RESULTS],
        "source_authority": "third_party_high_access",
        "requires_network": True,
        "command": ["{python}", "runtime/tools/prepare_france_zeturf_race_detail_candidates.py", "--events-csv", "{events_csv}", "--output-dir", "{adapter_output_dir}", "{network_flag}"],
        "inputs": {"events_csv": {"required": True, "artifact": "input/events.csv"}},
        "outputs": [
            {"key": "candidate_jsonl", "path": "france_zeturf_detail_candidates_2026.jsonl", "standard_name": "candidates/france_zeturf_detail.jsonl", "required": True},
            {"key": "review_csv", "path": "france_zeturf_detail_review_2026.csv", "standard_name": "review/france_zeturf_detail.csv", "required": True},
            {"key": "summary", "path": "summary.json", "standard_name": "summary/france_zeturf_detail.json", "required": True},
        ],
    },
    "us_hrn_detail": {
        "key": "us_hrn_detail",
        "region": RacingRegion.UNITED_STATES,
        "source": "horse_racing_nation",
        "modules": [RaceEventModule.RUNNERS, RaceEventModule.RESULTS],
        "source_authority": "third_party_high_access",
        "requires_network": True,
        "command": ["{python}", "runtime/tools/prepare_us_hrn_race_detail_candidates.py", "--events-csv", "{events_csv}", "--output-dir", "{adapter_output_dir}", "{network_flag}"],
        "inputs": {"events_csv": {"required": True, "artifact": "input/events.csv"}},
        "outputs": [
            {"key": "candidate_jsonl", "path": "us_hrn_detail_candidates_2026.jsonl", "standard_name": "candidates/us_hrn_detail.jsonl", "required": True},
            {"key": "review_csv", "path": "us_hrn_detail_review_2026.csv", "standard_name": "review/us_hrn_detail.csv", "required": True},
            {"key": "summary", "path": "summary.json", "standard_name": "summary/us_hrn_detail.json", "required": True},
        ],
    },
    "us_equibase_results": {
        "key": "us_equibase_results",
        "region": RacingRegion.UNITED_STATES,
        "source": "equibase",
        "modules": [RaceEventModule.RESULTS],
        "source_authority": "third_party",
        "command": [
            "{python}",
            "runtime/tools/prepare_us_equibase_result_candidates.py",
            "--events-csv",
            "{events_csv}",
            "--runner-jsonl",
            "{runner_jsonl}",
            "--pdf-dir",
            "{pdf_dir}",
            "--output-dir",
            "{adapter_output_dir}",
        ],
        "inputs": {
            "events_csv": {"required": True, "artifact": "input/events.csv"},
            "runner_jsonl": {"required": True, "artifact": "candidates/us_hrn_detail.jsonl"},
            "pdf_dir": {"required": True, "artifact": "source/equibase_pdfs"},
        },
        "dependencies": [{"artifact": "candidates/us_hrn_detail.jsonl", "stage": "prepare"}],
        "outputs": [
            {"key": "candidate_jsonl", "path": "us_equibase_gap_result_candidates_2026.jsonl", "standard_name": "candidates/us_equibase_results.jsonl", "required": True},
            {"key": "review_csv", "path": "us_equibase_gap_result_review_2026.csv", "standard_name": "review/us_equibase_results.csv", "required": True},
            {"key": "summary", "path": "summary.json", "standard_name": "summary/us_equibase_results.json", "required": True},
        ],
    },
}

DEFAULT_ADAPTER_MANIFESTS.update(
    {
        "jra_history_winners": {
            "key": "jra_history_winners",
            "region": RacingRegion.JAPAN,
            "source": "jra",
            "modules": [RaceEventModule.HISTORY_WINNERS],
            "source_authority": "official",
            "requires_network": True,
            "supports_year_range": True,
            "command": ["{python}", "runtime/tools/prepare_jra_history_winner_candidates.py", "--events-csv", "{events_csv}", "--detail-jsonl", "{detail_jsonl}", "--output-dir", "{adapter_output_dir}", "{network_flag}"],
            "inputs": {
                "events_csv": {"required": True, "artifact": "input/events.csv"},
                "detail_jsonl": {"required": True, "artifact": "candidates/jra_detail.jsonl"},
            },
            "dependencies": [{"artifact": "candidates/jra_detail.jsonl", "stage": "prepare"}],
            "outputs": [
                {"key": "candidate_jsonl", "path": "jra_history_winner_candidates_2026.jsonl", "standard_name": "candidates/jra_history_winners.jsonl", "required": True},
                {"key": "review_csv", "path": "jra_history_winner_review_2026.csv", "standard_name": "review/jra_history_winners.csv", "required": True},
                {"key": "summary", "path": "summary.json", "standard_name": "summary/jra_history_winners.json", "required": True},
            ],
        },
        "nar_history_winners": {
            "key": "nar_history_winners",
            "region": RacingRegion.JAPAN,
            "source": "nar",
            "modules": [RaceEventModule.HISTORY_WINNERS],
            "source_authority": "official",
            "requires_network": True,
            "command": ["{python}", "runtime/tools/prepare_nar_history_winner_candidates.py", "--events-csv", "{events_csv}", "--output-dir", "{adapter_output_dir}", "{network_flag}"],
            "inputs": {"events_csv": {"required": True, "artifact": "input/events.csv"}},
            "outputs": [
                {"key": "candidate_jsonl", "path": "nar_history_winner_candidates_2026.jsonl", "standard_name": "candidates/nar_history_winners.jsonl", "required": True},
                {"key": "review_csv", "path": "nar_history_winner_review_2026.csv", "standard_name": "review/nar_history_winners.csv", "required": True},
                {"key": "summary", "path": "summary.json", "standard_name": "summary/nar_history_winners.json", "required": True},
            ],
        },
        "hkjc_history_winners": {
            "key": "hkjc_history_winners",
            "region": RacingRegion.HONG_KONG,
            "source": "hkjc",
            "modules": [RaceEventModule.HISTORY_WINNERS],
            "source_authority": "official",
            "requires_network": True,
            "command": ["{python}", "runtime/tools/prepare_hkjc_history_winner_candidates.py", "--events-csv", "{events_csv}", "--output-dir", "{adapter_output_dir}", "{network_flag}"],
            "inputs": {"events_csv": {"required": True, "artifact": "input/events.csv"}},
            "outputs": [
                {"key": "candidate_jsonl", "path": "hkjc_history_winner_candidates_2026.jsonl", "standard_name": "candidates/hkjc_history_winners.jsonl", "required": True},
                {"key": "review_csv", "path": "hkjc_history_winner_review_2026.csv", "standard_name": "review/hkjc_history_winners.csv", "required": True},
                {"key": "summary", "path": "summary.json", "standard_name": "summary/hkjc_history_winners.json", "required": True},
            ],
        },
        "uk_sporting_life_history_winners": {
            "key": "uk_sporting_life_history_winners",
            "region": RacingRegion.UNITED_KINGDOM,
            "source": "sporting_life",
            "modules": [RaceEventModule.HISTORY_WINNERS],
            "source_authority": "third_party_high_access",
            "requires_network": True,
            "command": [
                "{python}",
                "runtime/tools/prepare_uk_sportinglife_history_winner_candidates.py",
                "--review-csv",
                "{review_csv}",
                "--output-dir",
                "{adapter_output_dir}",
                "{network_flag}",
            ],
            "inputs": {"review_csv": {"required": True, "artifact": "review/uk_sporting_life_detail.csv"}},
            "dependencies": [{"artifact": "review/uk_sporting_life_detail.csv", "stage": "audit"}],
            "outputs": [
                {"key": "candidate_jsonl", "path": "uk_sportinglife_history_winner_candidates_2026.jsonl", "standard_name": "candidates/uk_sporting_life_history_winners.jsonl", "required": True},
                {"key": "review_csv", "path": "uk_sportinglife_history_winner_review_2026.csv", "standard_name": "review/uk_sporting_life_history_winners.csv", "required": True},
                {"key": "summary", "path": "summary.json", "standard_name": "summary/uk_sporting_life_history_winners.json", "required": True},
            ],
        },
        "france_wikipedia_history_winners": {
            "key": "france_wikipedia_history_winners",
            "region": RacingRegion.FRANCE,
            "source": "france_wikipedia",
            "modules": [RaceEventModule.HISTORY_WINNERS],
            "source_authority": "reference",
            "requires_network": True,
            "command": ["{python}", "runtime/tools/prepare_france_wikipedia_history_winner_candidates.py", "--events-csv", "{events_csv}", "--output-dir", "{adapter_output_dir}", "{network_flag}"],
            "inputs": {"events_csv": {"required": True, "artifact": "input/events.csv"}},
            "outputs": [
                {"key": "candidate_jsonl", "path": "france_wikipedia_history_winner_candidates_2026.jsonl", "standard_name": "candidates/france_wikipedia_history_winners.jsonl", "required": True},
                {"key": "review_csv", "path": "france_wikipedia_history_winner_review_2026.csv", "standard_name": "review/france_wikipedia_history_winners.csv", "required": True},
                {"key": "summary", "path": "summary.json", "standard_name": "summary/france_wikipedia_history_winners.json", "required": True},
            ],
        },
        "us_toba_history_winners": {
            "key": "us_toba_history_winners",
            "region": RacingRegion.UNITED_STATES,
            "source": "toba",
            "modules": [RaceEventModule.HISTORY_WINNERS],
            "source_authority": "reference",
            "requires_network": True,
            "command": ["{python}", "runtime/tools/prepare_us_toba_history_winner_candidates.py", "--events-csv", "{events_csv}", "--output-dir", "{adapter_output_dir}", "{network_flag}"],
            "inputs": {"events_csv": {"required": True, "artifact": "input/events.csv"}},
            "outputs": [
                {"key": "candidate_jsonl", "path": "us_toba_history_winner_candidates_2026.jsonl", "standard_name": "candidates/us_toba_history_winners.jsonl", "required": True},
                {"key": "review_csv", "path": "us_toba_history_winner_review_2026.csv", "standard_name": "review/us_toba_history_winners.csv", "required": True},
                {"key": "summary", "path": "summary.json", "standard_name": "summary/us_toba_history_winners.json", "required": True},
            ],
        },
    }
)
DEFAULT_ADAPTER_MANIFESTS["uk_sporting_life_results"] = DEFAULT_ADAPTER_MANIFESTS["uk_sporting_life_detail"]
DEFAULT_ADAPTER_MANIFESTS["uk_sporting_life_history"] = DEFAULT_ADAPTER_MANIFESTS["uk_sporting_life_history_winners"]


class PlanValidationError(ValueError):
    pass


class AdapterDependencyError(RuntimeError):
    pass


class AdapterOutputError(RuntimeError):
    pass


class AdapterExecutionError(RuntimeError):
    pass


@dataclass
class ArtifactRef:
    path: str
    original_path: str = ""
    required: bool = True
    size: int = 0
    sha256: str = ""
    original_size: int = 0
    original_sha256: str = ""


@dataclass
class RunState:
    run_id: str
    run_dir: str
    stage: str = "created"
    completed_stages: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    adapter_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    resume_history: list[dict[str, Any]] = field(default_factory=list)

    def write(self) -> Path:
        path = Path(self.run_dir) / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def read(cls, path: str | Path) -> "RunState":
        payload = _read_json(Path(path))
        return cls(**payload)


@dataclass
class AdapterManifest:
    key: str
    region: str
    source: str
    modules: list[str]
    source_authority: str
    command: list[str] = field(default_factory=list)
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    requires_network: bool = False
    working_dir: str = ""
    supports_year_range: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AdapterManifest":
        required = ["key", "region", "source", "modules", "source_authority", "command", "outputs"]
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise PlanValidationError(f"adapter manifest missing required fields: {', '.join(missing)}")
        modules = [str(module) for module in payload.get("modules") or []]
        unknown_modules = [module for module in modules if module not in TARGET_MODULES]
        if unknown_modules:
            raise PlanValidationError(f"adapter manifest has unsupported modules: {', '.join(unknown_modules)}")
        authority = str(payload.get("source_authority"))
        if authority not in SOURCE_AUTHORITY_LEVELS:
            raise PlanValidationError(f"unsupported source_authority: {authority}")
        command = payload.get("command")
        if not isinstance(command, list) or not all(str(part).strip() for part in command):
            raise PlanValidationError("adapter manifest command must be a non-empty list")
        outputs = payload.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            raise PlanValidationError("adapter manifest outputs must be a non-empty list")
        for output in outputs:
            if not isinstance(output, dict) or not output.get("key") or not output.get("path"):
                raise PlanValidationError("adapter manifest outputs must include key and path")
        return cls(
            key=str(payload["key"]),
            region=str(payload["region"]),
            source=str(payload["source"]),
            modules=modules,
            source_authority=authority,
            command=[str(part) for part in command],
            inputs=dict(payload.get("inputs") or {}),
            dependencies=list(payload.get("dependencies") or []),
            outputs=list(outputs),
            requires_network=bool(payload.get("requires_network", False)),
            working_dir=str(payload.get("working_dir") or ""),
            supports_year_range=bool(payload.get("supports_year_range", False)),
        )


@dataclass
class AdapterResult:
    key: str
    status: str
    command: list[str]
    returncode: int
    stdout_excerpt: str
    stderr_excerpt: str
    artifacts: dict[str, ArtifactRef]
    region: str = ""
    source: str = ""
    source_authority: str = ""
    modules: list[str] = field(default_factory=list)
    request_budget: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifacts"] = {key: asdict(value) for key, value in self.artifacts.items()}
        return payload


class AdapterRunner:
    def __init__(self, manifest: AdapterManifest):
        self.manifest = manifest

    def run(
        self,
        *,
        inputs: dict[str, str | Path],
        run_dir: str | Path,
        allow_network: bool = False,
        execution_policy: dict[str, Any] | None = None,
    ) -> AdapterResult:
        if self.manifest.requires_network and not allow_network:
            raise AdapterDependencyError(f"adapter {self.manifest.key} requires network authorization")

        run_path = Path(run_dir)
        adapter_dir = run_path / "adapter_runs" / self.manifest.key
        adapter_dir.mkdir(parents=True, exist_ok=True)
        normalized_inputs = {key: str(value) for key, value in (inputs or {}).items()}
        self._check_dependencies(run_path, normalized_inputs)

        command = self._render_command(run_path, adapter_dir, normalized_inputs, allow_network=allow_network)
        if not command:
            raise AdapterExecutionError(f"adapter {self.manifest.key} has no command")

        workdir = Path(self.manifest.working_dir) if self.manifest.working_dir else REPO_ROOT
        if not workdir.is_absolute():
            workdir = REPO_ROOT / workdir
        execution_policy = dict(execution_policy or {})
        budget_artifact = run_path / "request_budget.json"
        environment = {
            **os.environ,
            "RACE_EVENT_CRAWL_MAX_REQUESTS": str(execution_policy.get("max_requests") or 0),
            "RACE_EVENT_CRAWL_REQUEST_INTERVAL_SECONDS": str(
                execution_policy.get("request_interval_seconds") or 0
            ),
            "RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT": str(budget_artifact),
            "RACE_EVENT_CRAWL_BATCH_SIZE": str(execution_policy.get("batch_size") or 0),
            "RACE_EVENT_CRAWL_MAX_SOURCE_CACHE_BYTES": str(
                execution_policy.get("max_source_cache_bytes") or 0
            ),
            "RACE_EVENT_CRAWL_MIN_FREE_DISK_BYTES": str(
                execution_policy.get("min_free_disk_bytes") or 0
            ),
            "RACE_EVENT_CRAWL_SOURCE_CACHE_ROOT": str(run_path.resolve()),
            "RACE_EVENT_CRAWL_SOURCE_CACHE_MANIFEST": str(
                (run_path / "source_cache_manifest.json").resolve()
            ),
        }
        completed = subprocess.run(
            command,
            cwd=str(workdir),
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        command_record = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": _excerpt(completed.stdout),
            "stderr": _excerpt(completed.stderr),
            "execution_policy": execution_policy,
        }
        if budget_artifact.exists():
            try:
                request_budget = _read_json(budget_artifact)
            except (OSError, json.JSONDecodeError, PlanValidationError, UnicodeError) as exc:
                request_budget = {"status": "invalid", "error": str(exc)}
        else:
            request_budget = {}
        command_record["request_budget"] = request_budget
        (adapter_dir / "command.json").write_text(
            json.dumps(command_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if completed.returncode != 0:
            raise AdapterExecutionError(f"adapter {self.manifest.key} failed with exit code {completed.returncode}")

        artifacts = self._collect_outputs(run_path, adapter_dir)
        self._annotate_outputs(artifacts)
        self._refresh_artifact_identities(artifacts)
        return AdapterResult(
            key=self.manifest.key,
            status="succeeded",
            command=command,
            returncode=completed.returncode,
            stdout_excerpt=_excerpt(completed.stdout),
            stderr_excerpt=_excerpt(completed.stderr),
            artifacts=artifacts,
            region=self.manifest.region,
            source=self.manifest.source,
            source_authority=self.manifest.source_authority,
            modules=self.manifest.modules.copy(),
            request_budget=request_budget,
        )

    def input_fingerprint(
        self,
        *,
        inputs: dict[str, str | Path],
        run_dir: str | Path,
        allow_network: bool = False,
        execution_policy: dict[str, Any] | None = None,
    ) -> str:
        run_path = Path(run_dir)
        adapter_dir = run_path / "adapter_runs" / self.manifest.key
        normalized_inputs = {key: str(value) for key, value in (inputs or {}).items()}
        self._check_dependencies(run_path, normalized_inputs)
        command = self._render_command(run_path, adapter_dir, normalized_inputs, allow_network=allow_network)
        fingerprint_payload = {
            "manifest": asdict(self.manifest),
            "command": command,
            "allow_network": allow_network,
            "execution_policy": execution_policy or {},
            "inputs": {
                key: _path_fingerprint(Path(value))
                for key, value in sorted(normalized_inputs.items())
            },
            "dependencies": {
                str(dependency.get("artifact")): _path_fingerprint(run_path / str(dependency.get("artifact")))
                for dependency in self.manifest.dependencies
                if dependency.get("artifact")
            },
        }
        encoded = json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _render_command(self, run_dir: Path, adapter_dir: Path, inputs: dict[str, str], *, allow_network: bool) -> list[str]:
        values = {
            **inputs,
            "run_dir": str(run_dir),
            "adapter_output_dir": str(adapter_dir),
            "network_flag": "--allow-network" if allow_network else "",
            "python": sys.executable,
        }
        return [part.format(**values) for part in self.manifest.command if part.format(**values)]

    def _check_dependencies(self, run_dir: Path, inputs: dict[str, str]) -> None:
        for name, spec in self.manifest.inputs.items():
            if not spec.get("required", False):
                continue
            artifact = spec.get("artifact")
            candidate = Path(inputs[name]) if name in inputs else (run_dir / str(artifact) if artifact else None)
            if candidate is None or not candidate.exists():
                raise AdapterDependencyError(f"adapter {self.manifest.key} missing required input: {name}")
            inputs.setdefault(name, str(candidate))
        for dependency in self.manifest.dependencies:
            artifact = dependency.get("artifact")
            if artifact and not (run_dir / str(artifact)).exists():
                raise AdapterDependencyError(f"adapter {self.manifest.key} missing dependency artifact: {artifact}")

    def _collect_outputs(self, run_dir: Path, adapter_dir: Path) -> dict[str, ArtifactRef]:
        artifacts: dict[str, ArtifactRef] = {}
        for output in self.manifest.outputs:
            key = str(output.get("key") or "artifact")
            relative = str(output.get("path") or "")
            source_path = Path(relative)
            if not source_path.is_absolute():
                source_path = adapter_dir / relative
            required = bool(output.get("required", True))
            if required and not source_path.exists():
                raise AdapterOutputError(f"adapter {self.manifest.key} missing required output: {relative}")
            standard_name = output.get("standard_name")
            destination = source_path
            if source_path.exists() and standard_name:
                destination = run_dir / str(standard_name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination)
            artifacts[key] = ArtifactRef(path=str(destination), original_path=str(source_path), required=required)
        return artifacts

    def _annotate_outputs(self, artifacts: dict[str, ArtifactRef]) -> None:
        provenance = {
            "adapter_key": self.manifest.key,
            "source_provider": self.manifest.source,
            "source_authority": self.manifest.source_authority,
            "racing_region": self.manifest.region,
            "modules": self.manifest.modules,
        }
        for key, artifact in artifacts.items():
            path = Path(artifact.path)
            if not path.exists():
                continue
            try:
                if "candidate" in key.lower() and path.suffix.lower() == ".jsonl":
                    self._annotate_candidate_jsonl(path)
                elif "summary" in key.lower() and path.suffix.lower() == ".json":
                    payload = _read_json(path)
                    payload["orchestration_provenance"] = provenance
                    _write_json(path, payload)
            except (OSError, json.JSONDecodeError, PlanValidationError, UnicodeError) as exc:
                raise AdapterOutputError(
                    f"adapter {self.manifest.key} produced invalid {key}: {exc}"
                ) from exc

    def _annotate_candidate_jsonl(self, path: Path) -> None:
        records = _read_jsonl(path)
        annotated: list[dict[str, Any]] = []
        expected = {
            "adapter_key": self.manifest.key,
            "source_provider": self.manifest.source,
            "source_authority": self.manifest.source_authority,
            "racing_region": self.manifest.region,
        }
        for record in records:
            record.pop("_line_number", None)
            for field_name, expected_value in expected.items():
                current = str(record.get(field_name) or "").strip()
                if current and current != expected_value:
                    raise AdapterOutputError(
                        f"adapter {self.manifest.key} candidate provenance mismatch: "
                        f"{field_name}={current!r}, expected {expected_value!r}"
                    )
                record[field_name] = expected_value
            if not str(record.get("source_name") or "").strip():
                record["source_name"] = self.manifest.source
            modules = record.get("modules") if isinstance(record.get("modules"), dict) else {}
            unexpected_modules = sorted(set(modules) - set(self.manifest.modules))
            if unexpected_modules:
                raise AdapterOutputError(
                    f"adapter {self.manifest.key} candidate contains undeclared modules: "
                    f"{', '.join(unexpected_modules)}"
                )
            annotated.append(record)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in annotated),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _refresh_artifact_identities(self, artifacts: dict[str, ArtifactRef]) -> None:
        for artifact in artifacts.values():
            path = Path(artifact.path)
            if path.exists() and path.is_file():
                identity = file_identity(path)
                artifact.size = identity["size"]
                artifact.sha256 = identity["sha256"]
            original_path = Path(artifact.original_path) if artifact.original_path else None
            if original_path and original_path.exists() and original_path.is_file():
                original_identity = file_identity(original_path)
                artifact.original_size = original_identity["size"]
                artifact.original_sha256 = original_identity["sha256"]


def _excerpt(value: str, limit: int = 4000) -> str:
    value = value or ""
    return value if len(value) <= limit else value[:limit] + "\n...<truncated>"


def _path_fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "path": str(path),
            "kind": "file",
            "size": path.stat().st_size,
            "sha256": digest.hexdigest(),
        }
    children = []
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        stat = child.stat()
        children.append(
            {
                "path": str(child.relative_to(path)),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return {"path": str(path), "kind": "directory", "children": children}


def file_identity(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        raise PlanValidationError(f"artifact file does not exist: {candidate}")
    fingerprint = _path_fingerprint(candidate)
    return {
        "path": str(candidate.resolve()),
        "size": int(fingerprint["size"]),
        "sha256": str(fingerprint["sha256"]),
    }


def read_file_with_identity(path: str | Path) -> tuple[bytes, dict[str, Any]]:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        raise PlanValidationError(f"artifact file does not exist: {candidate}")
    raw = candidate.read_bytes()
    return raw, {
        "path": str(candidate.resolve()),
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise PlanValidationError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise PlanValidationError(f"candidate line {line_number} must be a JSON object")
            record["_line_number"] = line_number
            records.append(record)
    return records


def load_plan(path: str | Path) -> dict[str, Any]:
    return _read_json(Path(path))


def default_adapter_manifests() -> dict[str, AdapterManifest]:
    return {key: AdapterManifest.from_dict(value) for key, value in DEFAULT_ADAPTER_MANIFESTS.items()}


def adapter_manifest_for_key(key: str) -> AdapterManifest:
    try:
        payload = DEFAULT_ADAPTER_MANIFESTS[key]
    except KeyError as exc:
        raise PlanValidationError(f"unknown adapter key: {key}") from exc
    return AdapterManifest.from_dict(payload)


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("target_layer") != TARGET_LAYER:
        raise PlanValidationError("target_layer must be race_event")
    try:
        batch_size = int(plan.get("batch_size"))
    except (TypeError, ValueError) as exc:
        raise PlanValidationError("batch_size must be a positive integer") from exc
    if batch_size <= 0:
        raise PlanValidationError("batch_size must be a positive integer")
    rate_limit = plan.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise PlanValidationError("rate_limit must be an object")
    try:
        max_requests = int(rate_limit.get("max_requests"))
        request_interval = float(rate_limit.get("request_interval_seconds"))
    except (TypeError, ValueError) as exc:
        raise PlanValidationError("rate_limit max_requests and request_interval_seconds must be numeric") from exc
    if max_requests <= 0:
        raise PlanValidationError("rate_limit.max_requests must be a positive integer")
    if request_interval < 0:
        raise PlanValidationError("rate_limit.request_interval_seconds must be non-negative")
    regions = plan.get("regions")
    if not isinstance(regions, list) or not regions:
        raise PlanValidationError("plan must include regions")
    historical = bool(plan.get("historical_inventory_sha256"))
    for region_plan in regions:
        _validate_region_plan(region_plan, batch_size=batch_size, historical=historical)
    adapters = plan.get("adapters") or []
    if not isinstance(adapters, list):
        raise PlanValidationError("adapters must be a list")
    for adapter in adapters:
        if isinstance(adapter, str):
            adapter_manifest_for_key(adapter)
        elif isinstance(adapter, dict):
            AdapterManifest.from_dict(adapter)
        else:
            raise PlanValidationError("adapter must be a registered key or complete manifest object")
    if plan.get("first_acceptance"):
        validate_first_acceptance_plan(plan)
    if plan.get("historical_inventory_sha256"):
        validate_historical_plan_budgets(plan)
    return plan


def validate_historical_plan_budgets(
    plan: dict[str, Any],
    *,
    cache_path: str | Path | None = None,
) -> dict[str, int]:
    try:
        max_source_cache_bytes = int(plan["max_source_cache_bytes"])
        min_free_disk_bytes = int(plan["min_free_disk_bytes"])
        max_requests = int((plan.get("rate_limit") or {})["max_requests"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PlanValidationError(
            "historical plan requires numeric max_source_cache_bytes, min_free_disk_bytes and rate_limit.max_requests"
        ) from exc
    if max_source_cache_bytes <= 0 or min_free_disk_bytes <= 0:
        raise PlanValidationError("historical cache and disk budgets must be positive")
    if max_source_cache_bytes > settings.HISTORICAL_RACE_BACKFILL_MAX_SOURCE_CACHE_BYTES:
        raise PlanValidationError("historical max_source_cache_bytes exceeds configured safety ceiling")
    if max_requests > settings.HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET:
        raise PlanValidationError("historical request budget exceeds configured safety ceiling")
    probe = Path(cache_path or plan.get("source_cache_dir") or REPO_ROOT / "runtime")
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free_disk_bytes = shutil.disk_usage(probe).free
    if free_disk_bytes < min_free_disk_bytes:
        raise PlanValidationError(
            f"historical free disk budget is not met: free={free_disk_bytes} required={min_free_disk_bytes}"
        )
    return {
        "max_source_cache_bytes": max_source_cache_bytes,
        "min_free_disk_bytes": min_free_disk_bytes,
        "free_disk_bytes": free_disk_bytes,
        "max_requests": max_requests,
    }


def _validate_region_plan(region_plan: dict[str, Any], *, batch_size: int, historical: bool = False) -> None:
    region = region_plan.get("region")
    if region not in TARGET_REGIONS:
        raise PlanValidationError(f"unsupported region: {region}")
    authority = region_plan.get("source_authority")
    if authority not in SOURCE_AUTHORITY_LEVELS:
        raise PlanValidationError(f"unsupported source_authority: {authority}")
    modules = region_plan.get("modules")
    if not isinstance(modules, dict):
        raise PlanValidationError(f"{region} modules must be an object")
    missing = [module for module in TARGET_MODULES if module not in modules]
    if missing:
        raise PlanValidationError(f"missing required modules: {', '.join(missing)}")
    if historical:
        targets = region_plan.get("targets")
        if not isinstance(targets, list) or not targets:
            raise PlanValidationError(f"{region} historical plan must include target snapshot rows")
        if len(targets) > batch_size:
            raise PlanValidationError(
                f"{region} target count {len(targets)} exceeds batch_size {batch_size}"
            )
        for target in targets:
            if not isinstance(target, dict) or not target.get("target_id") or not str(
                target.get("target_sha256") or ""
            ).strip():
                raise PlanValidationError(f"{region} historical target is missing id or SHA")
        return
    series = region_plan.get("series")
    if not isinstance(series, list) or not series:
        raise PlanValidationError(f"{region} must include explicit series list")
    ranges = [_years_tuple(modules[module].get("years")) for module in TARGET_MODULES]
    if any(value is None for value in ranges) or len(set(ranges)) != 1:
        raise PlanValidationError("module history depth must match for runners/results/history_winners")
    module_range = ranges[0]
    if module_range[0] > module_range[1]:
        raise PlanValidationError(f"{region} module year range is invalid")
    target_count = 0
    for series_plan in series:
        if not isinstance(series_plan, dict) or not str(series_plan.get("series_key") or "").strip():
            raise PlanValidationError(f"{region} series must include series_key")
        series_range = _years_tuple(series_plan.get("years")) or module_range
        if series_range != module_range:
            raise PlanValidationError(f"{region} series and module history depth must match")
        slugs = series_plan.get("slugs")
        if not isinstance(slugs, dict):
            raise PlanValidationError(f"{region} series slugs must be an object")
        for year in range(series_range[0], series_range[1] + 1):
            if not str(slugs.get(str(year)) or "").strip():
                raise PlanValidationError(
                    f"{region} target_mapping_missing: {series_plan.get('series_key')} year={year}"
                )
            target_count += 1
    if target_count > batch_size:
        raise PlanValidationError(
            f"{region} target count {target_count} exceeds batch_size {batch_size}"
        )


def _years_tuple(years: Any) -> tuple[int, int] | None:
    if not isinstance(years, dict):
        return None
    try:
        return int(years["start"]), int(years["end"])
    except (KeyError, TypeError, ValueError):
        return None


def validate_first_acceptance_plan(plan: dict[str, Any]) -> dict[str, Any]:
    regions = {region_plan.get("region") for region_plan in plan.get("regions", [])}
    missing_regions = sorted(TARGET_REGIONS - regions)
    modules: set[str] = set()
    adapter_selection_errors: list[str] = []
    manifests = [
        manifest
        for adapter in plan.get("adapters") or []
        if (manifest := _manifest_from_plan_adapter(adapter)) is not None
    ]
    for region_plan in plan.get("regions", []):
        region = str(region_plan.get("region") or "")
        target_modules = set((region_plan.get("modules") or {}).keys())
        modules.update(target_modules)
        if not region_plan.get("series"):
            adapter_selection_errors.append(f"{region}: missing series list")
        adapter_modules = {
            module
            for manifest in manifests
            if manifest.region == region
            for module in manifest.modules
        }
        missing_adapter_modules = sorted(target_modules - adapter_modules)
        if missing_adapter_modules:
            adapter_selection_errors.append(
                f"{region}: missing adapter modules {', '.join(missing_adapter_modules)}"
            )
    missing_modules = [module for module in TARGET_MODULES if module not in modules]
    if missing_regions:
        raise PlanValidationError(f"first acceptance missing regions: {', '.join(missing_regions)}")
    if missing_modules:
        raise PlanValidationError(f"first acceptance missing modules: {', '.join(missing_modules)}")
    if adapter_selection_errors:
        raise PlanValidationError("; ".join(adapter_selection_errors))
    return {
        "regions": sorted(regions),
        "modules": TARGET_MODULES.copy(),
        "missing_regions": [],
        "adapter_selection_errors": [],
    }


def validate_first_acceptance_fixture(plan_path: str | Path) -> dict[str, Any]:
    plan = load_plan(plan_path)
    validate_plan(plan)
    return validate_first_acceptance_plan(plan)


def _race_event_adapter_input(event: RaceEvent) -> dict[str, Any]:
    return {
        "year": event.year,
        "slug": event.slug,
        "series_key": event.series_key,
        "original_name": event.original_name,
        "chinese_name": event.chinese_name,
        "aliases": "|".join(
            event.aliases.filter(is_active=True)
            .order_by("source_language", "text")
            .values_list("text", flat=True)
        ),
        "country_region": event.country_region,
        "racing_region": event.country_region,
        "racecourse": event.racecourse,
        "grade_text": event.grade_text,
        "normalized_grade": event.normalized_grade,
        "surface": event.surface,
        "distance_text": event.distance_text,
        "status": event.status,
        "local_date": event.local_date.isoformat() if event.local_date else "",
        "source_refs": json.dumps(event.source_refs or {}, ensure_ascii=False, sort_keys=True),
    }


def expected_targets_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if plan.get("historical_inventory_sha256"):
        return _historical_expected_targets_from_plan(plan)
    targets: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for region_plan in plan.get("regions") or []:
        region = str(region_plan.get("region") or "")
        source = str(region_plan.get("source") or "")
        source_authority = str(region_plan.get("source_authority") or "")
        modules = sorted((region_plan.get("modules") or {}).keys())
        for series_plan in region_plan.get("series") or []:
            series_key = str(series_plan.get("series_key") or "").strip()
            start_year, end_year = _years_tuple(series_plan.get("years")) or _years_tuple(
                (region_plan.get("modules") or {}).get(TARGET_MODULES[0], {}).get("years")
            )
            slugs = series_plan.get("slugs") or {}
            for year in range(start_year, end_year + 1):
                slug = str(slugs.get(str(year)) or "").strip()
                identity = (year, slug)
                if identity in seen:
                    raise PlanValidationError(f"duplicate expected target: year={year} slug={slug}")
                seen.add(identity)
                event = RaceEvent.objects.filter(year=year, slug=slug).first()
                targets.append(
                    {
                        "year": year,
                        "slug": slug,
                        "series_key": series_key,
                        "racing_region": region,
                        "source": source,
                        "source_authority": source_authority,
                        "modules": modules,
                        "race_event_id": event.id if event else None,
                        "race_event_original_name": str(event.original_name or "") if event else "",
                        "race_event_chinese_name": str(event.chinese_name or "") if event else "",
                        "race_event_series_key": str(event.series_key or "") if event else "",
                        "adapter_input": _race_event_adapter_input(event) if event else {},
                        "preflight_status": "ready" if event else "missing_race_event",
                    }
                )
    if not targets:
        raise PlanValidationError("expected_target_empty")
    return targets


def _historical_expected_targets_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    inventory_sha = str(plan.get("historical_inventory_sha256") or "")
    target_rows = [
        (region_plan, row)
        for region_plan in plan.get("regions") or []
        for row in region_plan.get("targets") or []
    ]
    target_ids = [int(row["target_id"]) for _region_plan, row in target_rows]
    if len(target_ids) != len(set(target_ids)):
        raise PlanValidationError("duplicate historical target id")
    targets_by_id = HistoricalRaceEventTarget.objects.select_related("race_series", "event").in_bulk(target_ids)
    results: list[dict[str, Any]] = []
    for region_plan, approved in target_rows:
        target = targets_by_id.get(int(approved["target_id"]))
        if target is None:
            raise PlanValidationError(f"historical target disappeared: {approved['target_id']}")
        actual_identity = target_identity(target)
        if actual_identity["target_sha256"] != approved["target_sha256"]:
            raise PlanValidationError(f"historical target changed after approval: {target.pk}")
        if target.country_region != region_plan["region"]:
            raise PlanValidationError(f"historical target region mismatch: {target.pk}")
        if target.artifact_sha256 != inventory_sha:
            raise PlanValidationError(f"historical target inventory artifact mismatch: {target.pk}")
        if target.resolution_status != HistoricalRaceResolutionStatus.READY or target.event is None:
            raise PlanValidationError(f"historical target is outside ready ledger scope: {target.pk}")
        event = target.event
        results.append(
            {
                "historical_target_id": target.pk,
                "historical_target_sha256": actual_identity["target_sha256"],
                "year": target.year,
                "slug": event.slug,
                "series_key": target.race_series.key,
                "racing_region": target.country_region,
                "source": str(region_plan.get("source") or ""),
                "source_authority": str(region_plan.get("source_authority") or ""),
                "modules": sorted((region_plan.get("modules") or {}).keys()),
                "race_event_id": event.pk,
                "race_event_original_name": event.original_name,
                "race_event_chinese_name": event.chinese_name,
                "race_event_series_key": event.series_key,
                "adapter_input": _race_event_adapter_input(event),
                "preflight_status": "ready",
            }
        )
    if not results:
        raise PlanValidationError("expected_target_empty")
    return results


def ensure_expected_targets_snapshot(
    *,
    plan: dict[str, Any],
    plan_path: str | Path,
    run_dir: str | Path,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    snapshot_path = run_path / "expected_targets.json"
    review_path = run_path / "review" / "expected_targets_review.csv"
    plan_identity = file_identity(plan_path)
    if snapshot_path.exists():
        payload = _read_json(snapshot_path)
        recorded_plan = payload.get("plan_identity") if isinstance(payload.get("plan_identity"), dict) else {}
        if recorded_plan.get("sha256") != plan_identity["sha256"]:
            raise PlanValidationError("expected target snapshot does not match current plan")
        if not review_path.exists():
            _write_expected_targets_review(review_path, payload.get("targets") or [])
        _ensure_expected_targets_approval(run_path, file_identity(snapshot_path))
        return payload

    targets = expected_targets_from_plan(plan)
    payload = {
        "schema_version": "1.0",
        "generated_at": timezone.now().isoformat(),
        "plan_identity": plan_identity,
        "expected_target_count": len(targets),
        "expected_module_count": sum(len(target["modules"]) for target in targets),
        "preflight_blocker_count": sum(
            1 for target in targets if target["preflight_status"] != "ready"
        ),
        "targets": targets,
    }
    _write_json(snapshot_path, payload)
    _write_expected_targets_review(review_path, targets)
    _ensure_expected_targets_approval(run_path, file_identity(snapshot_path))
    return payload


def _write_expected_targets_review(path: Path, targets: list[dict[str, Any]]) -> Path:
    rows = [
        {
            "year": target.get("year"),
            "slug": target.get("slug"),
            "series_key": target.get("series_key"),
            "race_event_original_name": target.get("race_event_original_name"),
            "race_event_chinese_name": target.get("race_event_chinese_name"),
            "racing_region": target.get("racing_region"),
            "source": target.get("source"),
            "source_authority": target.get("source_authority"),
            "modules": "|".join(target.get("modules") or []),
            "race_event_id": target.get("race_event_id") or "",
            "preflight_status": target.get("preflight_status"),
            "operator_confirmation": "",
        }
        for target in targets
    ]
    return _write_review_csv(path, rows)


def _ensure_expected_targets_approval(
    run_path: Path,
    expected_identity: dict[str, Any],
) -> Path:
    approval_path = run_path / "review" / "expected_targets_approval.json"
    if approval_path.exists():
        payload = _read_json(approval_path)
        recorded = payload.get("expected_targets_identity")
        if isinstance(recorded, dict) and recorded.get("sha256") == expected_identity["sha256"]:
            return approval_path
    return _write_json(
        approval_path,
        {
            "schema_version": "1.0",
            "status": "pending",
            "expected_targets_identity": expected_identity,
            "approved_by": "",
            "approved_at": "",
        },
    )


def validate_expected_targets_approval(
    *,
    run_dir: str | Path,
    expected_targets: str | Path,
) -> dict[str, Any]:
    expected_identity = file_identity(expected_targets)
    approval_path = Path(run_dir) / "review" / "expected_targets_approval.json"
    if not approval_path.is_file():
        raise PlanValidationError("expected targets approval is missing")
    approval = _read_json(approval_path)
    recorded = approval.get("expected_targets_identity")
    if not isinstance(recorded, dict) or recorded.get("sha256") != expected_identity["sha256"]:
        raise PlanValidationError("expected targets approval does not match current snapshot")
    if approval.get("status") != "approved":
        raise PlanValidationError("expected targets are not approved for network crawl")
    if not str(approval.get("approved_by") or "").strip() or not str(
        approval.get("approved_at") or ""
    ).strip():
        raise PlanValidationError("expected targets approval is missing operator evidence")
    return approval


def materialize_adapter_event_inputs(
    *,
    expected_snapshot: dict[str, Any],
    run_dir: str | Path,
) -> dict[str, str]:
    targets_by_region: dict[str, list[dict[str, Any]]] = {}
    for target in expected_snapshot.get("targets") or []:
        region = str(target.get("racing_region") or "").strip()
        targets_by_region.setdefault(region, []).append(target)

    fieldnames = [
        "year",
        "slug",
        "series_key",
        "original_name",
        "chinese_name",
        "aliases",
        "country_region",
        "racing_region",
        "racecourse",
        "grade_text",
        "normalized_grade",
        "surface",
        "distance_text",
        "status",
        "local_date",
        "source_refs",
    ]
    input_dir = Path(run_dir) / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}
    for region, targets in sorted(targets_by_region.items()):
        path = input_dir / f"events_{region}.csv"
        rows: list[dict[str, Any]] = []
        for target in sorted(targets, key=lambda item: (int(item["year"]), str(item["slug"]))):
            event = RaceEvent.objects.filter(
                pk=target.get("race_event_id"),
                year=int(target["year"]),
                slug=str(target["slug"]),
            ).first()
            if event is None:
                raise PlanValidationError(
                    f"expected target RaceEvent disappeared: year={target['year']} slug={target['slug']}"
                )
            approved_input = target.get("adapter_input")
            if not isinstance(approved_input, dict) or not approved_input:
                raise PlanValidationError(
                    f"expected target is missing approved adapter input: year={target['year']} slug={target['slug']}"
                )
            if _race_event_adapter_input(event) != approved_input:
                raise PlanValidationError(
                    f"expected target RaceEvent changed after approval: year={target['year']} slug={target['slug']}"
                )
            rows.append({field: approved_input.get(field, "") for field in fieldnames})
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        result[region] = str(path)
    return result


def create_run(plan_path: str | Path, run_dir: str | Path | None = None) -> RunState:
    plan_source = Path(plan_path)
    plan = load_plan(plan_path)
    validate_plan(plan)
    destination = Path(run_dir or plan.get("output_dir") or Path("runtime") / "race_event_crawl_runs" / str(plan.get("run_id") or "manual"))
    destination.mkdir(parents=True, exist_ok=True)
    plan_destination = destination / "plan.json"
    if plan_source.resolve() != plan_destination.resolve():
        shutil.copy2(plan_source, plan_destination)
    state_path = destination / "state.json"
    if state_path.exists():
        state = RunState.read(state_path)
        state.artifacts["plan"] = str(plan_destination)
        expected = ensure_expected_targets_snapshot(
            plan=plan,
            plan_path=plan_destination,
            run_dir=destination,
        )
        expected_path = destination / "expected_targets.json"
        state.artifacts["expected_targets"] = str(expected_path)
        state.artifacts["expected_targets_review"] = str(
            destination / "review" / "expected_targets_review.csv"
        )
        state.artifacts["expected_targets_approval"] = str(
            destination / "review" / "expected_targets_approval.json"
        )
        state.artifacts["expected_targets_identity"] = file_identity(expected_path)
        state.artifacts["expected_target_count"] = expected["expected_target_count"]
        state.write()
        return state
    expected = ensure_expected_targets_snapshot(
        plan=plan,
        plan_path=plan_destination,
        run_dir=destination,
    )
    expected_path = destination / "expected_targets.json"
    state = RunState(
        run_id=str(plan.get("run_id") or destination.name),
        run_dir=str(destination),
        artifacts={
            "plan": str(plan_destination),
            "expected_targets": str(expected_path),
            "expected_targets_review": str(destination / "review" / "expected_targets_review.csv"),
            "expected_targets_approval": str(destination / "review" / "expected_targets_approval.json"),
            "expected_targets_identity": file_identity(expected_path),
            "expected_target_count": expected["expected_target_count"],
        },
    )
    state.write()
    return state


def prepare_adapters(plan: dict[str, Any], state: RunState, *, resume: bool = False) -> list[dict[str, Any]]:
    validate_plan(plan)
    validate_prepare_authorization(plan)
    expected = _read_json(Path(state.artifacts["expected_targets"]))
    if plan.get("allow_network") and expected.get("preflight_blocker_count"):
        raise PlanValidationError(
            "expected target preflight is blocked; review expected_targets_review.csv before network crawl"
        )
    if plan.get("allow_network") and any(
        _adapter_requires_network(adapter) for adapter in plan.get("adapters") or []
    ):
        validate_expected_targets_approval(
            run_dir=state.run_dir,
            expected_targets=state.artifacts["expected_targets"],
        )
    event_inputs = materialize_adapter_event_inputs(
        expected_snapshot=expected,
        run_dir=state.run_dir,
    )
    state.artifacts["adapter_event_inputs"] = {
        region: {"path": path, "identity": file_identity(path)}
        for region, path in event_inputs.items()
    }
    state.write()
    results: list[dict[str, Any]] = []
    reran_adapter = False
    for adapter_payload in plan.get("adapters") or []:
        manifest = _manifest_from_plan_adapter(adapter_payload)
        runner = AdapterRunner(manifest)
        execution_policy = _execution_policy_for_manifest(plan, manifest)
        if "events_csv" in manifest.inputs and manifest.region not in event_inputs:
            raise PlanValidationError(
                f"adapter {manifest.key} has no approved expected targets for region {manifest.region}"
            )
        adapter_inputs = (
            {"events_csv": event_inputs[manifest.region]}
            if "events_csv" in manifest.inputs and manifest.region in event_inputs
            else {}
        )
        previous = state.adapter_states.get(manifest.key) or {}
        try:
            fingerprint = runner.input_fingerprint(
                inputs=adapter_inputs,
                run_dir=state.run_dir,
                allow_network=bool(plan.get("allow_network", False)),
                execution_policy=execution_policy,
            )
        except (AdapterDependencyError, AdapterExecutionError, AdapterOutputError) as exc:
            error = {
                "stage": "prepare",
                "adapter": manifest.key,
                "error": str(exc),
                "recorded_at": timezone.now().isoformat(),
            }
            state.adapter_states[manifest.key] = {
                "status": "failed",
                "input_fingerprint": "",
                "resume_action": "retry_failed" if resume else "executed",
                "error": str(exc),
            }
            state.errors.append(error)
            state.stage = "prepare_failed"
            state.write()
            raise
        outputs_valid, output_resume_action = _previous_adapter_outputs_valid(manifest, previous)
        if (
            resume
            and previous.get("status") == "succeeded"
            and previous.get("input_fingerprint") == fingerprint
            and outputs_valid
        ):
            previous["resume_action"] = "skipped_unchanged"
            state.adapter_states[manifest.key] = previous
            if isinstance(previous.get("result"), dict):
                results.append(previous["result"])
            state.write()
            continue

        if resume and previous.get("status") == "succeeded" and previous.get("input_fingerprint") == fingerprint:
            resume_action = output_resume_action
        elif resume and previous.get("status") == "succeeded":
            resume_action = "rerun_input_changed"
        elif resume and previous.get("status") == "failed":
            resume_action = "retry_failed"
        else:
            resume_action = "executed"
        reran_adapter = reran_adapter or resume_action != "skipped_unchanged"
        try:
            result = runner.run(
                inputs=adapter_inputs,
                run_dir=state.run_dir,
                allow_network=bool(plan.get("allow_network", False)),
                execution_policy=execution_policy,
            )
        except (AdapterDependencyError, AdapterExecutionError, AdapterOutputError) as exc:
            error = {
                "stage": "prepare",
                "adapter": manifest.key,
                "error": str(exc),
                "recorded_at": timezone.now().isoformat(),
            }
            state.adapter_states[manifest.key] = {
                "status": "failed",
                "input_fingerprint": fingerprint,
                "resume_action": resume_action,
                "error": str(exc),
            }
            state.errors.append(error)
            state.stage = "prepare_failed"
            state.write()
            raise

        result_payload = result.to_dict()
        state.adapter_states[manifest.key] = {
            "status": "succeeded",
            "input_fingerprint": fingerprint,
            "resume_action": resume_action,
            "result": result_payload,
        }
        results.append(result_payload)
        state.stage = "prepare"
        state.write()

    if reran_adapter:
        state.completed_stages = [stage for stage in state.completed_stages if stage not in {"audit", "dry-run", "apply-check"}]
    if "prepare" not in state.completed_stages:
        state.completed_stages.append("prepare")
    state.stage = "prepare"
    state.artifacts["adapter_results"] = results
    combined = aggregate_candidate_artifacts(results=results, run_dir=state.run_dir)
    state.artifacts["combined_candidates"] = combined["path"]
    state.artifacts["combined_candidates_identity"] = combined["identity"]
    state.write()
    return results


def aggregate_candidate_artifacts(*, results: list[dict[str, Any]], run_dir: str | Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    source_paths: list[str] = []
    seen_paths: set[str] = set()
    for result in results:
        artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
        artifact = artifacts.get("candidate_jsonl") if isinstance(artifacts.get("candidate_jsonl"), dict) else {}
        path_text = str(artifact.get("path") or "").strip()
        if not path_text or path_text in seen_paths:
            continue
        path = Path(path_text)
        if not path.is_file():
            raise AdapterOutputError(f"combined candidate input is missing: {path}")
        seen_paths.add(path_text)
        source_paths.append(str(path.resolve()))
        for record in _read_jsonl(path):
            record.pop("_line_number", None)
            modules = record.get("modules") if isinstance(record.get("modules"), dict) else None
            if modules is not None:
                record["modules"] = {
                    module: payload
                    for module, payload in modules.items()
                    if not _is_explicitly_empty_module_payload(payload)
                }
                if not record["modules"]:
                    continue
            records.append(record)
    output_path = Path(run_dir) / "candidates" / "combined_candidates.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return {
        "path": str(output_path),
        "identity": file_identity(output_path),
        "record_count": len(records),
        "source_paths": source_paths,
    }


def _is_explicitly_empty_module_payload(payload: Any) -> bool:
    if isinstance(payload, list):
        return not payload
    return isinstance(payload, dict) and isinstance(payload.get("items"), list) and not payload["items"]


def _previous_adapter_outputs_valid(
    manifest: AdapterManifest,
    previous: dict[str, Any],
) -> tuple[bool, str]:
    if previous.get("status") != "succeeded":
        return False, "retry_failed"
    result = previous.get("result") if isinstance(previous.get("result"), dict) else {}
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
    for output in manifest.outputs:
        if not bool(output.get("required", True)):
            continue
        key = str(output.get("key") or "artifact")
        artifact = artifacts.get(key) if isinstance(artifacts.get(key), dict) else {}
        path_text = str(artifact.get("path") or "").strip()
        if not path_text or not Path(path_text).is_file():
            return False, "rerun_output_missing"
        expected_sha256 = str(artifact.get("sha256") or "").strip()
        if not expected_sha256:
            return False, "rerun_output_unverified"
        if file_identity(path_text)["sha256"] != expected_sha256:
            return False, "rerun_output_changed"
        original_text = str(artifact.get("original_path") or "").strip()
        expected_original_sha256 = str(artifact.get("original_sha256") or "").strip()
        if original_text and Path(original_text) != Path(path_text):
            if not Path(original_text).is_file():
                return False, "rerun_output_missing"
            if not expected_original_sha256:
                return False, "rerun_output_unverified"
            if file_identity(original_text)["sha256"] != expected_original_sha256:
                return False, "rerun_output_changed"
    return True, "skipped_unchanged"


def _execution_policy_for_manifest(plan: dict[str, Any], manifest: AdapterManifest) -> dict[str, Any]:
    rate_limit = plan.get("rate_limit") or {}
    region_plan = next(
        (
            item
            for item in plan.get("regions") or []
            if str(item.get("region") or "") == manifest.region
        ),
        {},
    )
    module_ranges = [
        _years_tuple((region_plan.get("modules") or {}).get(module, {}).get("years"))
        for module in manifest.modules
    ]
    valid_ranges = [value for value in module_ranges if value is not None]
    return {
        "batch_size": int(plan.get("batch_size") or 0),
        "max_requests": int(rate_limit.get("max_requests") or 0),
        "request_interval_seconds": float(rate_limit.get("request_interval_seconds") or 0),
        "start_year": min((value[0] for value in valid_ranges), default=None),
        "end_year": max((value[1] for value in valid_ranges), default=None),
        "racing_region": manifest.region,
        "max_source_cache_bytes": int(plan.get("max_source_cache_bytes") or 0),
        "min_free_disk_bytes": int(plan.get("min_free_disk_bytes") or 0),
    }


def _manifest_from_plan_adapter(adapter_payload: Any) -> AdapterManifest:
    if isinstance(adapter_payload, str):
        return adapter_manifest_for_key(adapter_payload)
    if isinstance(adapter_payload, dict):
        return AdapterManifest.from_dict(adapter_payload)
    raise PlanValidationError("adapter must be a registered key or complete manifest object")


def validate_prepare_authorization(plan: dict[str, Any]) -> None:
    allow_network = bool(plan.get("allow_network", False))
    if plan.get("historical_inventory_sha256"):
        validate_historical_plan_budgets(plan)
        if not settings.HISTORICAL_RACE_BACKFILL_ENABLED:
            raise PlanValidationError("historical race backfill is disabled")
        if allow_network and not settings.HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK:
            raise PlanValidationError("historical race backfill network access is disabled")
    for adapter in plan.get("adapters") or []:
        if _adapter_requires_network(adapter) and not allow_network:
            raise PlanValidationError("network access requires explicit allow_network=true")


def _adapter_requires_network(adapter: Any) -> bool:
    if isinstance(adapter, str):
        return adapter_manifest_for_key(adapter).requires_network
    if isinstance(adapter, dict):
        return AdapterManifest.from_dict(adapter).requires_network
    raise PlanValidationError("adapter must be a registered key or complete manifest object")


def audit_coverage(
    *,
    plan_path: str | Path,
    candidate_jsonl: str | Path,
    series_mapping_path: str | Path,
    run_dir: str | Path,
) -> dict[str, Any]:
    plan = load_plan(plan_path)
    validate_plan(plan)
    records = _read_jsonl(Path(candidate_jsonl))
    mapping = _read_json(Path(series_mapping_path))
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    candidate_identity = file_identity(candidate_jsonl)
    expected_snapshot = ensure_expected_targets_snapshot(
        plan=plan,
        plan_path=plan_path,
        run_dir=run_path,
    )
    expected_targets = {
        (int(target["year"]), str(target["slug"])): target
        for target in expected_snapshot.get("targets") or []
    }
    adapter_manifests = {
        manifest.key: manifest
        for adapter in plan.get("adapters") or []
        if (manifest := _manifest_from_plan_adapter(adapter)) is not None
    }
    plan_sources = {
        str(region_plan.get("source") or ""): {
            "source_authority": str(region_plan.get("source_authority") or ""),
            "racing_region": str(region_plan.get("region") or ""),
        }
        for region_plan in plan.get("regions") or []
        if region_plan.get("source")
    }

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    complete_count = 0
    seen_candidates: set[tuple[int, str, str]] = set()
    source_targets: dict[str, set[tuple[int, str, str]]] = {}
    seed_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    source_strategies: list[dict[str, Any]] = []
    mixed_source_strategies: list[dict[str, Any]] = []

    grouped_records: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for record in records:
        identity = (int(record.get("year") or 0), str(record.get("slug") or "").strip())
        grouped_records.setdefault(identity, []).append(record)
    actual_target_count = len(grouped_records)
    for identity in expected_targets:
        grouped_records.setdefault(identity, [])

    for (year, slug), event_records in sorted(grouped_records.items()):
        row_blocker_codes: list[str] = []
        row_warning_codes: list[str] = []
        expected_target = expected_targets.get((year, slug))
        if expected_target is None:
            row_blocker_codes.append("unexpected_candidate")
            _append_issue(blockers, "unexpected_candidate", year=year, slug=slug)
        elif not event_records:
            row_blocker_codes.append("missing_event_candidate")
            _append_issue(
                blockers,
                "missing_event_candidate",
                year=year,
                slug=slug,
                series_key=expected_target.get("series_key"),
            )
        event = RaceEvent.objects.filter(year=year, slug=slug).first()
        explicit_series_keys = {
            str(record.get("series_key") or "").strip()
            for record in event_records
            if str(record.get("series_key") or "").strip()
        }
        if len(explicit_series_keys) > 1:
            series_key = ""
            row_blocker_codes.append("ambiguous_series")
            _append_issue(
                blockers,
                "ambiguous_series",
                year=year,
                slug=slug,
                candidates=sorted(explicit_series_keys),
            )
        elif explicit_series_keys:
            series_key = next(iter(explicit_series_keys))
        elif expected_target is not None:
            series_key = str(expected_target.get("series_key") or "")
        else:
            series_key = _series_key_for_target(mapping, year=year, slug=slug)
            if not series_key and event is not None:
                series_key = str(event.series_key or "").strip()

        expected_series_key = str((expected_target or {}).get("series_key") or "")
        if expected_series_key and series_key and series_key != expected_series_key:
            row_blocker_codes.append("series_mismatch")
            _append_issue(
                blockers,
                "series_mismatch",
                year=year,
                slug=slug,
                expected_series_key=expected_series_key,
                candidate_series_key=series_key,
            )
        if event is not None and expected_series_key and str(event.series_key or "") != expected_series_key:
            row_blocker_codes.append("race_event_series_mismatch")
            _append_issue(
                blockers,
                "race_event_series_mismatch",
                year=year,
                slug=slug,
                expected_series_key=expected_series_key,
                race_event_series_key=str(event.series_key or ""),
            )

        mapping_status = _mapping_status(mapping, series_key)
        if mapping_status != "approved":
            code = "ambiguous_series" if mapping_status == "ambiguous" else "series_needs_review"
            row_blocker_codes.append(code)
            _append_issue(
                blockers,
                code,
                year=year,
                slug=slug,
                series_key=series_key,
                mapping_status=mapping_status,
            )

        if event is None:
            row_blocker_codes.append("missing_race_event")
            representative = event_records[0] if event_records else (expected_target or {})
            seed_rows.append(
                {
                    "year": year,
                    "slug": slug,
                    "series_key": series_key,
                    "original_name": representative.get("original_name", ""),
                    "source_url": representative.get("source_url", ""),
                    "reason": "missing_race_event",
                }
            )
            _append_issue(blockers, "missing_race_event", year=year, slug=slug, series_key=series_key)

        module_candidates: dict[str, list[tuple[Any, dict[str, Any]]]] = {}
        module_sources: dict[str, list[dict[str, str]]] = {}
        empty_module_declarations: set[str] = set()
        for record in event_records:
            provenance_codes = _candidate_provenance_codes(
                record,
                adapter_manifests=adapter_manifests,
                plan_sources=plan_sources,
            )
            for code, detail in provenance_codes:
                row_blocker_codes.append(code)
                _append_issue(
                    blockers,
                    code,
                    year=year,
                    slug=slug,
                    line=record.get("_line_number"),
                    detail=detail,
                )
            modules = record.get("modules") if isinstance(record.get("modules"), dict) else {}
            source_url = str(record.get("source_url") or "").strip()
            if source_url:
                source_targets.setdefault(source_url, set()).add((year, slug, series_key))
            for module, payload in modules.items():
                module_name = str(module)
                if not _payload_items(payload):
                    empty_module_declarations.add(module_name)
                    continue
                module_candidates.setdefault(module_name, []).append((payload, record))
                module_sources.setdefault(module_name, []).append(
                    {
                        "source_name": str(record.get("source_name") or ""),
                        "source_provider": str(record.get("source_provider") or record.get("source_name") or ""),
                        "source_authority": str(record.get("source_authority") or ""),
                        "source_url": source_url,
                    }
                )

        source_strategy = {
            module: _unique_source_entries(entries)
            for module, entries in sorted(module_sources.items())
        }
        strategy_payload = {
            "year": year,
            "slug": slug,
            "series_key": series_key,
            "region": str(
                (event.country_region if event is not None else "")
                or next((record.get("racing_region") for record in event_records if record.get("racing_region")), "")
            ),
            "modules": source_strategy,
        }
        strategy_payload["strategy_sha256"] = hashlib.sha256(
            json.dumps(strategy_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        source_strategies.append(strategy_payload)
        module_signatures = {_source_strategy_signature(entries) for entries in source_strategy.values()}
        if len(module_signatures) > 1:
            mixed_source_strategies.append(strategy_payload)

        missing_modules = [module for module in TARGET_MODULES if module not in module_candidates]
        for module in missing_modules:
            code = f"empty_{module}" if module in empty_module_declarations else f"missing_{module}"
            row_blocker_codes.append(code)
            _append_issue(blockers, code, year=year, slug=slug, module=module)

        for module, candidates in module_candidates.items():
            identity = (year, slug, module)
            if len(candidates) > 1 or identity in seen_candidates:
                row_blocker_codes.append("duplicate_candidate")
                _append_issue(blockers, "duplicate_candidate", year=year, slug=slug, module=module)
            seen_candidates.add(identity)
            if event is not None and _module_locked(event, module):
                row_blocker_codes.append("manual_lock_conflict")
                _append_issue(blockers, "manual_lock_conflict", year=year, slug=slug, module=module)
            if event is not None:
                _check_existing_data_diff(
                    event,
                    module,
                    candidates[0][0],
                    blockers,
                    warnings,
                    row_blocker_codes,
                    row_warning_codes,
                )

        is_complete = (
            event is not None
            and not row_blocker_codes
            and all(module in module_candidates for module in TARGET_MODULES)
        )
        if is_complete:
            complete_count += 1

        if row_blocker_codes:
            row_status = "blocked"
        elif row_warning_codes:
            row_status = "complete_with_warnings"
        else:
            row_status = "complete"

        review_rows.append(
            {
                "year": year,
                "slug": slug,
                "series_key": series_key,
                "expected": "yes" if expected_target is not None else "no",
                "status": row_status,
                "codes": "|".join(sorted(set(row_blocker_codes + row_warning_codes))),
                "blocker_codes": "|".join(sorted(set(row_blocker_codes))),
                "warning_codes": "|".join(sorted(set(row_warning_codes))),
                "module_sources": json.dumps(module_sources, ensure_ascii=False, sort_keys=True),
            }
        )

    for source_url, targets in source_targets.items():
        if len(targets) > 1:
            _append_issue(blockers, "source_conflict", source_url=source_url, targets=sorted(targets))

    artifacts: dict[str, dict[str, str]] = {}
    review_path = _write_review_csv(run_path / "review" / "coverage_audit.csv", review_rows)
    artifacts["review_csv"] = {"path": str(review_path)}
    if seed_rows:
        seed_path = _write_review_csv(run_path / "review" / "race_event_seed_review.csv", seed_rows)
        artifacts["race_event_seed_review"] = {"path": str(seed_path)}

    blocker_codes = _unique_codes(blockers)
    warning_codes = _unique_codes(warnings)
    status = "passed" if not blockers else "blocked"
    result = {
        "status": status,
        "complete_count": complete_count,
        "expected_target_count": len(expected_targets),
        "actual_target_count": actual_target_count,
        "expected_targets_identity": file_identity(run_path / "expected_targets.json"),
        "candidate_jsonl": str(candidate_jsonl),
        "candidate_identity": candidate_identity,
        "source_strategies": source_strategies,
        "mixed_source_strategies": mixed_source_strategies,
        "actual_apply_scopes": _actual_apply_scopes(source_strategies),
        "blockers": blockers,
        "warnings": warnings,
        "blocker_codes": blocker_codes,
        "warning_codes": warning_codes,
        "artifacts": artifacts,
    }
    artifacts["coverage_json"] = {"path": str(_write_json(run_path / "coverage_audit.json", result))}
    return result


def _candidate_provenance_codes(
    record: dict[str, Any],
    *,
    adapter_manifests: dict[str, AdapterManifest],
    plan_sources: dict[str, dict[str, str]],
) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    if not str(record.get("source_url") or "").strip():
        issues.append(("source_url_missing", "candidate is missing source_url"))

    authority = str(record.get("source_authority") or "").strip()
    if not authority:
        issues.append(("source_authority_missing", "candidate is missing source_authority"))
    elif authority not in SOURCE_AUTHORITY_LEVELS:
        issues.append(("source_authority_invalid", f"unsupported source_authority: {authority}"))

    adapter_key = str(record.get("adapter_key") or "").strip()
    provider = str(record.get("source_provider") or record.get("source_name") or "").strip()
    manifest = adapter_manifests.get(adapter_key) if adapter_key else None
    if adapter_key and manifest is None:
        issues.append(("source_provenance_conflict", f"unknown adapter_key: {adapter_key}"))
    if manifest is not None:
        expected = {
            "source_provider": manifest.source,
            "source_authority": manifest.source_authority,
            "racing_region": manifest.region,
        }
        actual = {
            "source_provider": provider,
            "source_authority": authority,
            "racing_region": str(record.get("racing_region") or "").strip(),
        }
        for field_name, expected_value in expected.items():
            if actual[field_name] != expected_value:
                issues.append(
                    (
                        "source_provenance_conflict",
                        f"{field_name}={actual[field_name]!r}, expected {expected_value!r} from {adapter_key}",
                    )
                )
        modules = record.get("modules") if isinstance(record.get("modules"), dict) else {}
        unexpected_modules = sorted(set(modules) - set(manifest.modules))
        if unexpected_modules:
            issues.append(
                (
                    "source_provenance_conflict",
                    f"adapter {adapter_key} does not declare modules: {', '.join(unexpected_modules)}",
                )
            )
    elif provider in plan_sources:
        expected = plan_sources[provider]
        if authority and authority != expected["source_authority"]:
            issues.append(
                (
                    "source_provenance_conflict",
                    f"source {provider} authority={authority!r}, expected {expected['source_authority']!r}",
                )
            )
        region = str(record.get("racing_region") or "").strip()
        if region and region != expected["racing_region"]:
            issues.append(
                (
                    "source_provenance_conflict",
                    f"source {provider} region={region!r}, expected {expected['racing_region']!r}",
                )
            )
    return issues


def _unique_source_entries(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    unique = {
        json.dumps(entry, ensure_ascii=False, sort_keys=True): entry
        for entry in entries
    }
    return [unique[key] for key in sorted(unique)]


def _source_strategy_signature(entries: list[dict[str, str]]) -> str:
    providers = sorted(
        {
            (
                str(entry.get("source_provider") or entry.get("source_name") or ""),
                str(entry.get("source_authority") or ""),
            )
            for entry in entries
        }
    )
    return json.dumps(providers, ensure_ascii=False)


def _actual_apply_scopes(source_strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, set[str]]] = {}
    for strategy in source_strategies:
        region = str(strategy.get("region") or "").strip()
        modules = strategy.get("modules") if isinstance(strategy.get("modules"), dict) else {}
        for module, entries in modules.items():
            for entry in entries if isinstance(entries, list) else []:
                source = str(entry.get("source_provider") or entry.get("source_name") or "").strip()
                authority = str(entry.get("source_authority") or "").strip()
                scope = grouped.setdefault((region, source), {"modules": set(), "authorities": set()})
                scope["modules"].add(str(module))
                if authority:
                    scope["authorities"].add(authority)
    return [
        {
            "region": region,
            "source": source,
            "modules": sorted(values["modules"]),
            "source_authorities": sorted(values["authorities"]),
        }
        for (region, source), values in sorted(grouped.items())
    ]


def _mapping_status(mapping: dict[str, Any], series_key: str) -> str:
    entry = mapping.get(series_key)
    if not isinstance(entry, dict):
        return "needs_review"
    return str(entry.get("status") or "needs_review")


def _series_key_for_target(mapping: dict[str, Any], *, year: int, slug: str) -> str:
    matches: list[str] = []
    for key, entry in mapping.items():
        if not isinstance(entry, dict):
            continue
        slugs = entry.get("slugs") if isinstance(entry.get("slugs"), dict) else {}
        if str(slugs.get(str(year)) or "").strip() == slug:
            matches.append(str(key))
    return matches[0] if len(matches) == 1 else ""


def _module_locked(event: RaceEvent, module: str) -> bool:
    flags = event.manual_lock_flags or {}
    return bool(flags.get(module))


def _payload_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    return []


def _existing_count(event: RaceEvent, module: str) -> int:
    if module == RaceEventModule.RUNNERS:
        return event.runners.count()
    if module == RaceEventModule.RESULTS:
        return event.results.count()
    if module == RaceEventModule.HISTORY_WINNERS:
        return event.history_winners.count()
    return 0


def _check_existing_data_diff(
    event: RaceEvent,
    module: str,
    payload: Any,
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    row_blocker_codes: list[str],
    row_warning_codes: list[str],
) -> None:
    existing = _existing_count(event, module)
    candidate = len(_payload_items(payload))
    if existing:
        row_warning_codes.append("existing_data_diff")
        _append_issue(warnings, "existing_data_diff", year=event.year, slug=event.slug, module=module, existing=existing, candidate=candidate)
    if existing and candidate < existing:
        row_blocker_codes.append("candidate_less_complete")
        _append_issue(blockers, "candidate_less_complete", year=event.year, slug=event.slug, module=module, existing=existing, candidate=candidate)
    existing_fields = _existing_critical_field_counts(event, module)
    candidate_fields = _critical_field_counts(_payload_items(payload), module)
    regressions = {
        field: {"existing": count, "candidate": candidate_fields.get(field, 0)}
        for field, count in existing_fields.items()
        if candidate_fields.get(field, 0) < count
    }
    if regressions:
        row_blocker_codes.append("candidate_less_complete")
        _append_issue(
            blockers,
            "candidate_less_complete",
            year=event.year,
            slug=event.slug,
            module=module,
            field_completeness_regressions=regressions,
        )


CRITICAL_MODULE_FIELDS = {
    RaceEventModule.RUNNERS: ["horse_number", "horse_name", "jockey_name", "trainer_name", "carried_weight", "running_status"],
    RaceEventModule.RESULTS: ["finish_position", "horse_number", "horse_name", "jockey_name", "trainer_name", "finish_time", "running_status"],
    RaceEventModule.HISTORY_WINNERS: ["winner_year", "horse_name", "jockey_name", "trainer_name", "finish_time"],
}


def _critical_field_counts(items: list[Any], module: str) -> dict[str, int]:
    fields = CRITICAL_MODULE_FIELDS.get(module, [])
    return {
        field: sum(
            1
            for item in items
            if isinstance(item, dict)
            and _critical_field_value(item, module, field) not in (None, "")
        )
        for field in fields
    }


def _critical_field_value(item: dict[str, Any], module: str, field: str) -> Any:
    if module == RaceEventModule.RUNNERS and field == "running_status":
        return item.get(field) or "declared"
    return item.get(field)


def _existing_critical_field_counts(event: RaceEvent, module: str) -> dict[str, int]:
    fields = CRITICAL_MODULE_FIELDS.get(module, [])
    if not fields:
        return {}
    related = {
        RaceEventModule.RUNNERS: event.runners,
        RaceEventModule.RESULTS: event.results,
        RaceEventModule.HISTORY_WINNERS: event.history_winners,
    }[module]
    return _critical_field_counts(list(related.values(*fields)), module)


def _append_issue(target: list[dict[str, Any]], code: str, **payload: Any) -> None:
    item = {"code": code}
    item.update(payload)
    target.append(item)


def _unique_codes(issues: list[dict[str, Any]]) -> list[str]:
    return sorted({str(issue.get("code")) for issue in issues if issue.get("code")})


def _write_review_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()}) or ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def evaluate_apply_check(
    *,
    run_dir: str | Path,
    coverage_audit: dict[str, Any],
    dry_run_artifact: str | Path | None,
    confirmations: list[dict[str, Any]],
    production_evidence: dict[str, Any],
    apply_scope: dict[str, Any],
    candidate_jsonl: str | Path | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    run_path = Path(run_dir)
    for blocker in coverage_audit.get("blockers") or []:
        _append_issue(blockers, str(blocker.get("code") or "coverage_blocker"), detail=blocker)
    if coverage_audit.get("status") != "passed":
        _append_issue(blockers, "coverage_not_passed")

    coverage_expected_identity = coverage_audit.get("expected_targets_identity")
    if not isinstance(coverage_expected_identity, dict) or not coverage_expected_identity.get("sha256"):
        _append_issue(blockers, "coverage_expected_targets_identity_missing")
        coverage_expected_identity = {}
    current_expected_identity: dict[str, Any] = {}
    expected_targets_path = run_path / "expected_targets.json"
    try:
        current_expected_identity = file_identity(expected_targets_path)
    except PlanValidationError:
        _append_issue(blockers, "expected_targets_evidence_missing")
    else:
        if (
            coverage_expected_identity
            and current_expected_identity["sha256"] != coverage_expected_identity.get("sha256")
        ):
            _append_issue(
                blockers,
                "expected_targets_evidence_mismatch",
                expected_sha256=current_expected_identity["sha256"],
                coverage_sha256=coverage_expected_identity.get("sha256"),
            )

    coverage_identity = coverage_audit.get("candidate_identity")
    if not isinstance(coverage_identity, dict) or not coverage_identity.get("sha256"):
        _append_issue(blockers, "coverage_candidate_identity_missing")
        coverage_identity = {}

    resolved_candidate_jsonl = str(candidate_jsonl or coverage_audit.get("candidate_jsonl") or "").strip()
    candidate_identity: dict[str, Any] = {}
    candidate_bytes = b""
    if not resolved_candidate_jsonl:
        _append_issue(blockers, "candidate_jsonl_missing")
    else:
        try:
            candidate_bytes, candidate_identity = read_file_with_identity(resolved_candidate_jsonl)
        except PlanValidationError:
            _append_issue(blockers, "candidate_jsonl_missing", path=resolved_candidate_jsonl)
        else:
            if coverage_identity and candidate_identity["sha256"] != coverage_identity.get("sha256"):
                _append_issue(
                    blockers,
                    "candidate_evidence_mismatch",
                    expected_sha256=coverage_identity.get("sha256"),
                    actual_sha256=candidate_identity["sha256"],
                )

    dry_run_payload: dict[str, Any] = {}
    if not dry_run_artifact or not Path(dry_run_artifact).is_file():
        _append_issue(blockers, "dry_run_missing")
    else:
        try:
            dry_run_payload = _read_json(Path(dry_run_artifact))
        except (OSError, json.JSONDecodeError, PlanValidationError, UnicodeError) as exc:
            _append_issue(blockers, "dry_run_invalid", error=str(exc))
        else:
            if dry_run_payload.get("status") != "passed":
                _append_issue(blockers, "dry_run_not_passed")
            dry_run_identity = dry_run_payload.get("candidate_identity")
            if not isinstance(dry_run_identity, dict) or not dry_run_identity.get("sha256"):
                _append_issue(blockers, "dry_run_candidate_identity_missing")
            elif coverage_identity and dry_run_identity.get("sha256") != coverage_identity.get("sha256"):
                _append_issue(
                    blockers,
                    "candidate_evidence_mismatch",
                    expected_sha256=coverage_identity.get("sha256"),
                    dry_run_sha256=dry_run_identity.get("sha256"),
                )
            elif candidate_identity and dry_run_identity.get("sha256") != candidate_identity.get("sha256"):
                _append_issue(
                    blockers,
                    "candidate_evidence_mismatch",
                    actual_sha256=candidate_identity.get("sha256"),
                    dry_run_sha256=dry_run_identity.get("sha256"),
                )

    required_strategy_sha256s = {
        str(strategy.get("strategy_sha256"))
        for strategy in coverage_audit.get("mixed_source_strategies") or []
        if strategy.get("strategy_sha256")
    }
    actual_apply_scopes = _normalized_scopes(coverage_audit.get("actual_apply_scopes"))
    declared_apply_scopes = _declared_apply_scopes(apply_scope)
    if not actual_apply_scopes:
        _append_issue(blockers, "coverage_apply_scopes_missing")
    elif {_scope_identity(scope) for scope in actual_apply_scopes} != {
        _scope_identity(scope) for scope in declared_apply_scopes
    }:
        _append_issue(
            blockers,
            "apply_scope_mismatch",
            actual_scopes=actual_apply_scopes,
            declared_scopes=declared_apply_scopes,
        )

    missing_confirmations = [
        scope
        for scope in actual_apply_scopes
        if not _has_matching_confirmation(confirmations, scope)
    ]
    for scope in missing_confirmations:
        _append_issue(blockers, "confirmation_missing", scope=scope)
    if missing_confirmations or not actual_apply_scopes:
        _append_issue(blockers, "first_batch_confirmation_missing")
    confirmed_strategy_sha256s = {
        str(value)
        for confirmation in confirmations or []
        if _is_approved_confirmation(confirmation)
        for value in confirmation.get("mixed_source_strategy_sha256s") or []
    }
    missing_strategy_sha256s = required_strategy_sha256s - confirmed_strategy_sha256s
    if missing_strategy_sha256s:
        _append_issue(
            blockers,
            "mixed_source_confirmation_missing",
            strategy_sha256s=sorted(missing_strategy_sha256s),
        )
    if (production_evidence.get("healthz") or {}).get("status") != "ok":
        _append_issue(blockers, "health_check_missing")
    backup_path = str(production_evidence.get("backup_path") or "").strip()
    backup_validation = _validate_gzip_backup(backup_path)
    if backup_validation.get("status") != "passed":
        _append_issue(blockers, "backup_evidence_missing")
    diff_review = production_evidence.get("diff_review")
    if not isinstance(diff_review, dict):
        _append_issue(blockers, "diff_review_missing")
    elif diff_review.get("status") != "approved":
        _append_issue(blockers, "diff_review_not_approved")
    if not production_evidence.get("external_import_locks_empty") or _has_active_external_imports():
        _append_issue(blockers, "external_import_lock_active")

    apply_command = ""
    approved_candidate_identity: dict[str, Any] = {}
    source_cache_protection: dict[str, Any] = {}
    if not blockers:
        approved_path = (
            Path(run_dir)
            / "approved"
            / f"candidates-{candidate_identity['sha256']}.jsonl"
        )
        approved_path.parent.mkdir(parents=True, exist_ok=True)
        if approved_path.exists():
            approved_bytes, approved_candidate_identity = read_file_with_identity(approved_path)
            if approved_bytes != candidate_bytes:
                _append_issue(blockers, "approved_candidate_conflict", path=str(approved_path))
        else:
            temporary = approved_path.with_suffix(approved_path.suffix + ".tmp")
            temporary.write_bytes(candidate_bytes)
            temporary.replace(approved_path)
            approved_candidate_identity = file_identity(approved_path)
        if not blockers:
            approved_path.chmod(0o444)
            apply_command = (
                "python server/manage.py import_race_event_detail_candidates "
                f"--jsonl {shlex.quote(str(approved_path.resolve()))} "
                f"--expected-sha256 {candidate_identity['sha256']} --apply"
            )
            try:
                source_cache_protection = protect_approved_run_source_cache(
                    run_path,
                    artifact_sha256=approved_candidate_identity["sha256"],
                )
            except PlanValidationError as exc:
                _append_issue(blockers, "source_cache_protection_failed", error=str(exc))
                apply_command = ""

    result = {
        "is_apply_allowed": not blockers,
        "blockers": blockers,
        "blocker_codes": _unique_codes(blockers),
        "apply_command": apply_command,
        "apply_scope": apply_scope,
        "actual_apply_scopes": actual_apply_scopes,
        "declared_apply_scopes": declared_apply_scopes,
        "candidate_identity": candidate_identity,
        "approved_candidate_identity": approved_candidate_identity,
        "source_cache_protection": source_cache_protection,
        "coverage_candidate_identity": coverage_identity,
        "dry_run_candidate_identity": dry_run_payload.get("candidate_identity", {}),
        "coverage_expected_targets_identity": coverage_expected_identity,
        "current_expected_targets_identity": current_expected_identity,
        "backup_validation": backup_validation,
        "required_mixed_source_strategy_sha256s": sorted(required_strategy_sha256s),
    }
    run_path.mkdir(parents=True, exist_ok=True)
    _write_json(run_path / "apply_check.json", result)
    return result


def _validate_gzip_backup(path_value: str) -> dict[str, Any]:
    path = Path(path_value) if path_value else None
    if path is None or not path.is_file() or path.stat().st_size <= 0:
        return {"status": "failed", "reason": "missing_or_empty", "path": path_value}
    try:
        with gzip.open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                if not chunk:
                    break
    except (EOFError, OSError) as exc:
        return {"status": "failed", "reason": "gzip_invalid", "path": str(path), "error": str(exc)}
    return {"status": "passed", **file_identity(path)}


def _has_matching_confirmation(
    confirmations: list[dict[str, Any]],
    apply_scope: dict[str, Any],
) -> bool:
    scope_modules = set(apply_scope.get("modules") or [])
    for confirmation in confirmations or []:
        if not _is_approved_confirmation(confirmation):
            continue
        if confirmation.get("region") != apply_scope.get("region") or confirmation.get("source") != apply_scope.get("source"):
            continue
        if scope_modules and not scope_modules.issubset(set(confirmation.get("modules") or [])):
            continue
        return True
    return False


def _is_approved_confirmation(confirmation: dict[str, Any]) -> bool:
    return bool(
        confirmation.get("status") == "approved"
        and str(confirmation.get("confirmed_by") or "").strip()
        and str(confirmation.get("confirmed_at") or "").strip()
    )


def _normalized_scopes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    scopes: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        region = str(item.get("region") or "").strip()
        source = str(item.get("source") or "").strip()
        modules = sorted({str(module) for module in item.get("modules") or [] if str(module)})
        if region and source and modules:
            scopes.append({"region": region, "source": source, "modules": modules})
    return scopes


def _declared_apply_scopes(apply_scope: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(apply_scope.get("scopes"), list):
        return _normalized_scopes(apply_scope["scopes"])
    return _normalized_scopes([apply_scope])


def _scope_identity(scope: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    return (
        str(scope.get("region") or ""),
        str(scope.get("source") or ""),
        tuple(sorted(str(module) for module in scope.get("modules") or [])),
    )


def _has_active_external_imports() -> bool:
    if ExternalDataImportRun.objects.filter(status=ExternalImportStatus.STARTED).exists():
        return True
    return ExternalDataImportLock.objects.filter(
        locked_by_run__status=ExternalImportStatus.STARTED,
    ).exists()


def run_detail_dry_run(*, candidate_jsonl: str | Path, run_dir: str | Path) -> dict[str, Any]:
    candidate_identity = file_identity(candidate_jsonl)
    out = _StringIO()
    call_command("import_race_event_detail_candidates", "--jsonl", str(candidate_jsonl), "--dry-run", stdout=out)
    text = out.getvalue()
    run_path = Path(run_dir)
    text_path = run_path / "dry_run.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text, encoding="utf-8")
    result = {
        "status": "passed",
        "candidate_identity": candidate_identity,
        "completed_at": timezone.now().isoformat(),
        "stdout_path": str(text_path),
        "stdout": text,
    }
    artifact_path = _write_json(run_path / "dry_run.json", result)
    result["path"] = str(artifact_path)
    return result


class _StringIO:
    def __init__(self) -> None:
        self._parts: list[str] = []

    def write(self, value: str) -> int:
        self._parts.append(value)
        return len(value)

    def flush(self) -> None:
        return None

    def getvalue(self) -> str:
        return "".join(self._parts)

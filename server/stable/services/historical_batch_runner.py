from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from stable.models import (
    HistoricalBatchLock,
    HistoricalBatchPhase,
    HistoricalBatchRun,
    HistoricalBatchRunEvent,
    HistoricalBatchRunStatus,
    RaceEvent,
    RaceEventVisibility,
)


RUNNER_PLAN_SCHEMA_VERSION = "1.0"
RUNNER_LOCK_KEY = "global"
RUNNER_HEARTBEAT_SECONDS = 30
RUNNER_LEASE_SECONDS = 180
RUNNER_SUMMARY_BYTES = 8 * 1024
RUNNER_STREAM_SUMMARY_BYTES = 3 * 1024
RUNNER_MAX_CRAWL_REQUESTS = 250
RUNNER_MAX_SOURCE_CACHE_BYTES = 2 * 1024 * 1024 * 1024
RUNNER_MIN_FREE_DISK_BYTES = 5 * 1024 * 1024 * 1024
RUNNER_REQUEST_INTERVAL_SECONDS = 1
RUNNER_IMMUTABLE_TOOL_ROOT = Path("/app/runtime/tools").resolve()
RUNNER_PRODUCTION_ARTIFACT_ROOT = Path("/app/historical-runtime").resolve()
RUNNER_OWNER_TOKEN_ENV = "HISTORICAL_RUNNER_OWNER_TOKEN"
RUNNER_PLAN_PATH_ENV = "HISTORICAL_RUNNER_PLAN_PATH"
RUNNER_STEP_ID_ENV = "HISTORICAL_RUNNER_STEP_ID"
_APPROVED_HISTORICAL_PYTHON_TOOLS = {
    "cache_historical_race_date_sources.py",
    "discover_historical_race_band_sources.py",
    "export_race_events_full.py",
    "historical_runner_smoke_probe.py",
    "merge_historical_race_batch_fragments.py",
    "package_historical_race_detail_candidates.py",
    "prepare_cached_historical_race_details.py",
    "prepare_historical_race_calendar_inputs.py",
    "prepare_france_wikipedia_history_winner_candidates.py",
    "prepare_france_zeturf_gap_candidates.py",
    "prepare_france_zeturf_race_detail_candidates.py",
    "prepare_hkjc_history_winner_candidates.py",
    "prepare_hkjc_race_detail_candidates.py",
    "prepare_irishracing_race_detail_candidates.py",
    "prepare_jra_history_winner_candidates.py",
    "prepare_jra_race_detail_candidates.py",
    "prepare_nar_history_winner_candidates.py",
    "prepare_nar_race_detail_candidates.py",
    "prepare_netkeiba_race_detail_candidates.py",
    "prepare_tjcis_ics_catalog.py",
    "prepare_uk_sportinglife_gap_candidates.py",
    "prepare_uk_sportinglife_history_winner_candidates.py",
    "prepare_uk_sportinglife_race_detail_candidates.py",
    "prepare_us_equibase_archived_race_detail_candidates.py",
    "prepare_us_equibase_result_candidates.py",
    "prepare_us_hrn_race_detail_candidates.py",
    "prepare_us_toba_history_winner_candidates.py",
}
_SHELL_PROGRAMS = {"bash", "dash", "fish", "sh", "zsh"}
_SHELL_FLAGS = {"-c", "-lc"}
_PYTHON_PROGRAMS = {"python", "python3"}
_WRITE_ARGUMENTS = {"--apply", "--commit", "apply", "commit"}
_WRITE_MANAGEMENT_COMMANDS = {
    "build_historical_race_date_discovery",
    "import_historical_race_event_candidates",
    "import_historical_race_event_field_candidates",
    "import_race_events",
    "manage_historical_race_detail_sources",
    "import_historical_race_detail_chunk",
    "reconcile_historical_race_detail_receipt",
}
_JSONL_APPLY_COMMANDS = {
    "import_historical_race_event_candidates",
    "import_historical_race_event_field_candidates",
}
_ARTIFACT_APPLY_COMMANDS = {
    "build_historical_race_date_discovery",
    "manage_historical_race_detail_sources",
}
_DETAIL_CHUNK_APPLY_COMMANDS = {"import_historical_race_detail_chunk"}
_DETAIL_RECEIPT_RECONCILE_COMMANDS = {"reconcile_historical_race_detail_receipt"}
_CURRENT_YEAR_DESCRIPTOR_APPLY_COMMANDS = {"import_race_events"}
_READ_MANAGEMENT_COMMANDS = {
    "build_historical_race_band_batch",
    "build_historical_race_date_discovery",
    "orchestrate_race_event_crawl",
    "manage_historical_race_detail_sources",
    "verify_historical_race_detail_chunk",
}


class RunnerPlanError(ValueError):
    pass


class RunnerLeaseError(RuntimeError):
    pass


class RunnerStateError(RuntimeError):
    pass


@dataclass
class RunnerLease:
    run_id: int
    lock_path: Path
    handle: Any

    def close(self) -> None:
        if self.handle is None:
            return
        with suppress(OSError):
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _owner_hash(owner_token: str) -> str:
    if not owner_token:
        raise RunnerLeaseError("owner token is required")
    return _sha256_bytes(owner_token.encode("utf-8"))


def _owner_prefix(owner_token: str) -> str:
    return _owner_hash(owner_token)[:12]


def _bounded_detail(detail: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(detail, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(encoded) <= RUNNER_SUMMARY_BYTES:
        return detail
    return {
        "truncated": True,
        "original_bytes": len(encoded),
        "summary": encoded[:7000].decode("utf-8", errors="replace"),
    }


def _tail_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[-max_bytes:].decode("utf-8", errors="ignore")


def _append_event(
    run: HistoricalBatchRun,
    event_type: str,
    *,
    owner_token: str = "",
    step_id: str = "",
    detail: dict[str, Any] | None = None,
) -> HistoricalBatchRunEvent:
    return HistoricalBatchRunEvent.objects.create(
        run=run,
        event_type=event_type,
        phase=run.phase,
        step_id=step_id,
        owner_prefix=_owner_prefix(owner_token) if owner_token else "",
        detail=_bounded_detail(detail or {}),
    )


def _phase_permissions(phase: str) -> tuple[bool, bool]:
    if phase == HistoricalBatchPhase.CRAWL:
        return True, False
    if phase == HistoricalBatchPhase.APPLY:
        return False, True
    if phase == HistoricalBatchPhase.VERIFY:
        return False, False
    raise RunnerPlanError(f"unknown historical runner phase: {phase}")


def create_runner_run(
    *,
    batch_id: str,
    phase: str,
    artifact_root: str,
    plan_sha256: str,
    image_id: str,
    image_revision: str,
    run_id: str | None = None,
) -> HistoricalBatchRun:
    network_enabled, write_enabled = _phase_permissions(phase)
    root = Path(artifact_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run = HistoricalBatchRun(
        run_id=run_id or uuid.uuid4().hex,
        batch_id=batch_id,
        phase=phase,
        network_enabled=network_enabled,
        write_enabled=write_enabled,
        artifact_root=str(root),
        plan_sha256=plan_sha256,
        image_id=image_id,
        image_revision=image_revision,
    )
    run.full_clean()
    run.save()
    _append_event(run, "created", detail={"plan_sha256": plan_sha256})
    return run


def _ensure_within(path_value: str, root: Path, label: str) -> Path:
    path = Path(path_value).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RunnerPlanError(f"{label} escapes approved root: {path_value}") from exc
    return path


def _declared_path(value: Any, *, label: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        return value["path"]
    raise RunnerPlanError(f"{label} must be a path string or identity object")


def _management_command(argv: list[str]) -> str:
    if len(argv) < 3 or argv[0].casefold() not in _PYTHON_PROGRAMS or argv[1] != "manage.py":
        raise RunnerPlanError("management argv must start with python manage.py COMMAND")
    return argv[2]


def _option_value(argv: list[str], option: str) -> str:
    matches: list[str] = []
    for index, value in enumerate(argv):
        if value == option:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise RunnerPlanError(f"runner command option has no value: {option}")
            matches.append(argv[index + 1])
        elif value.startswith(option + "="):
            matches.append(value.split("=", 1)[1])
    if len(matches) != 1 or not matches[0]:
        raise RunnerPlanError(f"runner command must provide {option} exactly once")
    return matches[0]


def _validate_apply_bindings(
    *,
    step: dict[str, Any],
    command: str,
    artifact_root: Path,
) -> None:
    identities = {
        str(_ensure_within(_declared_path(value, label="input"), artifact_root, "input path")): value["sha256"]
        for value in step.get("inputs", [])
    }
    approval = step["approval"]
    approval_path = str(
        _ensure_within(_declared_path(approval, label="approval"), artifact_root, "approval path")
    )
    if identities.get(approval_path) != approval["sha256"]:
        raise RunnerPlanError(f"apply step {step['id']} approval is not a declared input")
    try:
        approval_bytes = Path(approval_path).read_bytes()
        if _sha256_bytes(approval_bytes) != approval["sha256"]:
            raise RunnerPlanError(f"apply step {step['id']} approval changed during validation")
        approval_payload = json.loads(approval_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerPlanError(f"apply step {step['id']} approval file is invalid") from exc
    if not isinstance(approval_payload, dict) or approval_payload.get("status") != "approved":
        raise RunnerPlanError(f"apply step {step['id']} approval file is not approved")
    if not str(approval_payload.get("approved_by") or "").strip() or not str(
        approval_payload.get("approved_at") or ""
    ).strip():
        raise RunnerPlanError(f"apply step {step['id']} approval file has no operator or timestamp")

    argv = step["argv"]
    expected_sha256 = step["expected_sha256"]
    if command in _CURRENT_YEAR_DESCRIPTOR_APPLY_COMMANDS:
        descriptor_path = str(
            _ensure_within(
                _option_value(argv, "--current-year-descriptor"),
                artifact_root,
                "current-year descriptor path",
            )
        )
        command_approval = str(
            _ensure_within(
                _option_value(argv, "--current-year-approval"),
                artifact_root,
                "current-year approval path",
            )
        )
        csv_path = str(
            _ensure_within(_option_value(argv, "--csv"), artifact_root, "due CSV path")
        )
        cutoff = _option_value(argv, "--approved-cutoff-date")
        if command_approval != approval_path:
            raise RunnerPlanError(
                f"apply step {step['id']} command approval does not match approved input"
            )
        if descriptor_path not in identities or csv_path not in identities:
            raise RunnerPlanError(
                f"apply step {step['id']} descriptor and due CSV must be declared inputs"
            )
        if approval_payload.get("cutoff_date") != cutoff:
            raise RunnerPlanError(
                f"apply step {step['id']} approval cutoff does not match command"
            )
        try:
            descriptor_bytes = Path(descriptor_path).read_bytes()
            descriptor = json.loads(descriptor_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RunnerPlanError(
                f"apply step {step['id']} descriptor file is invalid"
            ) from exc
        if (
            not isinstance(descriptor, dict)
            or descriptor.get("artifact_kind") != "due_only"
            or descriptor.get("cutoff_date") != cutoff
            or approval_payload.get("descriptor_sha256")
            != _sha256_bytes(descriptor_bytes)
            or approval_payload.get("classified_manifest_sha256") != expected_sha256
        ):
            raise RunnerPlanError(
                f"apply step {step['id']} descriptor or approval identity does not match"
            )
        manifest_identity = descriptor.get("classified_manifest")
        apply_artifacts = descriptor.get("apply_artifacts")
        if (
            not isinstance(manifest_identity, dict)
            or manifest_identity.get("sha256") != expected_sha256
            or expected_sha256 not in identities.values()
            or not isinstance(apply_artifacts, dict)
            or identities.get(csv_path)
            not in {
                value.get("sha256")
                for value in apply_artifacts.values()
                if isinstance(value, dict)
            }
            or "--dry-run" in argv[3:]
        ):
            raise RunnerPlanError(
                f"apply step {step['id']} due-only artifacts are not bound to expected SHA"
            )
        return
    if command in _DETAIL_CHUNK_APPLY_COMMANDS:
        bundle_dir = _ensure_within(
            _option_value(argv, "--bundle-dir"), artifact_root, "detail chunk bundle dir"
        )
        bundle_manifest = str(bundle_dir / "manifest.json")
        chunk_manifest = str(
            _ensure_within(
                _option_value(argv, "--chunk-manifest"),
                artifact_root,
                "detail chunk manifest",
            )
        )
        command_approval = str(
            _ensure_within(
                _option_value(argv, "--approval"), artifact_root, "detail chunk approval"
            )
        )
        if command_approval != approval_path:
            raise RunnerPlanError(
                f"apply step {step['id']} command approval does not match approved input"
            )
        if (
            identities.get(bundle_manifest) != _option_value(argv, "--expected-bundle-sha256")
            or identities.get(chunk_manifest) != _option_value(argv, "--expected-chunk-sha256")
            or identities.get(command_approval) != _option_value(argv, "--expected-approval-sha256")
            or expected_sha256 != identities.get(chunk_manifest)
            or "--dry-run" in argv[3:]
        ):
            raise RunnerPlanError(
                f"apply step {step['id']} detail chunk identities are not fully bound"
            )
        _option_value(argv, "--runner-run-id")
        return
    if command in _DETAIL_RECEIPT_RECONCILE_COMMANDS:
        if expected_sha256 != approval["sha256"]:
            raise RunnerPlanError(
                f"apply step {step['id']} reconcile expected SHA must be the approval SHA"
            )
        if approval_payload.get("receipt_id") != _option_value(argv, "--receipt-id"):
            raise RunnerPlanError(f"apply step {step['id']} reconcile receipt is not approved")
        if approval_payload.get("approved_by") != _option_value(argv, "--approved-by"):
            raise RunnerPlanError(f"apply step {step['id']} reconcile operator is not approved")
        if approval_payload.get("reason") != _option_value(argv, "--reason"):
            raise RunnerPlanError(f"apply step {step['id']} reconcile reason is not approved")
        _option_value(argv, "--runner-run-id")
        return
    if command in _JSONL_APPLY_COMMANDS:
        if approval_payload.get("expected_sha256") != expected_sha256:
            raise RunnerPlanError(f"apply step {step['id']} approval file does not approve expected SHA")
        jsonl_path = str(_ensure_within(_option_value(argv, "--jsonl"), artifact_root, "jsonl path"))
        if identities.get(jsonl_path) != expected_sha256:
            raise RunnerPlanError(f"apply step {step['id']} jsonl is not the expected declared input")
        if _option_value(argv, "--expected-sha256") != expected_sha256:
            raise RunnerPlanError(f"apply step {step['id']} command SHA does not match expected input")
        if "--apply" not in argv[3:]:
            raise RunnerPlanError(f"apply step {step['id']} must use --apply")
        return

    if command in _ARTIFACT_APPLY_COMMANDS:
        manifest_identity = approval_payload.get("manifest_identity")
        if not isinstance(manifest_identity, dict) or manifest_identity.get("sha256") != expected_sha256:
            raise RunnerPlanError(f"apply step {step['id']} approval file does not approve manifest SHA")
        artifact_dir = _ensure_within(_option_value(argv, "--artifact-dir"), artifact_root, "artifact dir")
        command_approval = str(
            _ensure_within(_option_value(argv, "--approval"), artifact_root, "approval path")
        )
        if command_approval != approval_path:
            raise RunnerPlanError(f"apply step {step['id']} command approval does not match approved input")
        expected_paths = [Path(path) for path, sha256 in identities.items() if sha256 == expected_sha256]
        if not expected_paths or not any(path == artifact_dir or artifact_dir in path.parents for path in expected_paths):
            raise RunnerPlanError(f"apply step {step['id']} expected input is outside artifact directory")
        if "--commit" not in argv[3:]:
            raise RunnerPlanError(f"apply step {step['id']} must use --commit")
        return
    raise RunnerPlanError(f"apply command has no input-binding policy: {command}")


def validate_runner_plan(plan: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "batch_id",
        "phase",
        "network_enabled",
        "write_enabled",
        "image_id",
        "image_revision",
        "artifact_root",
        "tool_root",
        "tool_manifest",
        "steps",
    }
    missing = sorted(required - plan.keys())
    if missing:
        raise RunnerPlanError(f"runner plan missing fields: {', '.join(missing)}")
    if plan["schema_version"] != RUNNER_PLAN_SCHEMA_VERSION:
        raise RunnerPlanError("unsupported runner plan schema version")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(plan["image_id"])):
        raise RunnerPlanError("runner image_id must be a full immutable SHA-256 ID")
    if not re.fullmatch(r"[0-9a-f]{40}", str(plan["image_revision"])):
        raise RunnerPlanError("runner image_revision must be a 40-character commit")
    phase = str(plan["phase"])
    network_enabled, write_enabled = _phase_permissions(phase)
    if bool(plan["network_enabled"]) != network_enabled or bool(plan["write_enabled"]) != write_enabled:
        raise RunnerPlanError("runner phase permission combination is invalid")
    if not isinstance(plan["steps"], list) or not plan["steps"]:
        raise RunnerPlanError("runner plan steps must be a non-empty list")
    if not isinstance(plan["tool_manifest"], dict):
        raise RunnerPlanError("runner tool manifest must be an object")
    resource_limits = plan.get("resource_limits")
    if resource_limits is not None:
        if phase != HistoricalBatchPhase.CRAWL or not isinstance(resource_limits, dict):
            raise RunnerPlanError("runner resource_limits are only valid for crawl plans")
        required_resource_limits = {
            "request_budget",
            "max_source_cache_bytes",
            "min_free_disk_bytes",
            "request_interval_seconds",
        }
        if set(resource_limits) != required_resource_limits:
            raise RunnerPlanError("runner resource_limits fields are invalid")
        if (
            not isinstance(resource_limits["request_budget"], int)
            or isinstance(resource_limits["request_budget"], bool)
            or not 1 <= resource_limits["request_budget"] <= RUNNER_MAX_CRAWL_REQUESTS
            or not isinstance(resource_limits["max_source_cache_bytes"], int)
            or isinstance(resource_limits["max_source_cache_bytes"], bool)
            or not 1 <= resource_limits["max_source_cache_bytes"] <= RUNNER_MAX_SOURCE_CACHE_BYTES
            or not isinstance(resource_limits["min_free_disk_bytes"], int)
            or isinstance(resource_limits["min_free_disk_bytes"], bool)
            or resource_limits["min_free_disk_bytes"] < RUNNER_MIN_FREE_DISK_BYTES
            or isinstance(resource_limits["request_interval_seconds"], bool)
            or resource_limits["request_interval_seconds"] != RUNNER_REQUEST_INTERVAL_SECONDS
        ):
            raise RunnerPlanError("runner resource_limits are outside approved boundaries")
    if (
        "selection_identity" in plan
        and phase == HistoricalBatchPhase.CRAWL
        and resource_limits is None
    ):
        raise RunnerPlanError("formal historical crawl plan requires resource_limits")

    artifact_root = Path(str(plan["artifact_root"])).resolve()
    tool_root = Path(str(plan["tool_root"])).resolve()
    if "selection_identity" in plan:
        selection_identity = plan["selection_identity"]
        approved_target_ids = (
            selection_identity.get("approved_target_ids")
            if isinstance(selection_identity, dict)
            else None
        )
        if (
            not isinstance(selection_identity, dict)
            or set(selection_identity) != {"sha256", "approved_target_ids"}
            or not re.fullmatch(r"[0-9a-f]{64}", str(selection_identity.get("sha256") or ""))
            or not isinstance(approved_target_ids, list)
            or not approved_target_ids
            or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in approved_target_ids)
            or len(approved_target_ids) != len(set(approved_target_ids))
            or len(approved_target_ids) > RUNNER_MAX_CRAWL_REQUESTS
        ):
            raise RunnerPlanError("formal historical crawl plan has invalid selection_identity")
        batch_identity = plan.get("batch_identity")
        required_batch_identities = {
            "selection",
            "approval",
            "batch_manifest",
            "descriptor",
        }
        if not isinstance(batch_identity, dict) or set(batch_identity) != required_batch_identities:
            raise RunnerPlanError("formal historical crawl plan has invalid batch_identity")
        identity_paths: dict[str, Path] = {}
        for label, identity in batch_identity.items():
            if (
                not isinstance(identity, dict)
                or not re.fullmatch(r"[0-9a-f]{64}", str(identity.get("sha256") or ""))
                or not isinstance(identity.get("size"), int)
                or isinstance(identity.get("size"), bool)
                or identity["size"] < 0
            ):
                raise RunnerPlanError(f"formal batch identity is invalid: {label}")
            path = _ensure_within(
                _declared_path(identity, label=f"batch identity {label}"),
                artifact_root,
                f"batch identity {label}",
            )
            identity_paths[label] = path
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != identity["size"]
                or _sha256_file(path) != identity["sha256"]
            ):
                raise RunnerPlanError(f"formal batch identity changed: {label}")
        if selection_identity["sha256"] != batch_identity["selection"]["sha256"]:
            raise RunnerPlanError("formal selection identity does not match batch selection")
        try:
            selection_payload = json.loads(identity_paths["selection"].read_bytes())
            approval_payload = json.loads(identity_paths["approval"].read_bytes())
            manifest_payload = json.loads(identity_paths["batch_manifest"].read_bytes())
            raw_selection_targets = selection_payload["targets"]
            if not isinstance(raw_selection_targets, list) or any(
                not isinstance(row, dict)
                or not isinstance(row.get("target_id"), int)
                or isinstance(row.get("target_id"), bool)
                for row in raw_selection_targets
            ):
                raise ValueError
            selection_ids = {row["target_id"] for row in raw_selection_targets}
            raw_approval_ids = approval_payload["approved_target_ids"]
            if any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in raw_approval_ids
            ):
                raise ValueError
            approval_ids = set(raw_approval_ids)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RunnerPlanError("formal selection or approval content is invalid") from exc
        approved_scope = set(approved_target_ids)
        approval_manifest_identity = (
            approval_payload.get("manifest_identity")
            if isinstance(approval_payload, dict)
            else None
        )
        manifest_selection_identity = (
            (manifest_payload.get("artifacts") or {}).get("selection_snapshot")
            if isinstance(manifest_payload, dict)
            and isinstance(manifest_payload.get("artifacts"), dict)
            else None
        )
        if (
            not isinstance(selection_payload, dict)
            or not isinstance(selection_payload.get("targets"), list)
            or not isinstance(approval_payload, dict)
            or approval_payload.get("status") != "approved"
            or not str(approval_payload.get("approved_by") or "").strip()
            or not str(approval_payload.get("approved_at") or "").strip()
            or not isinstance(approval_payload.get("approved_target_ids"), list)
            or not isinstance(approval_manifest_identity, dict)
            or approval_manifest_identity.get("sha256")
            != batch_identity["batch_manifest"]["sha256"]
            or approval_manifest_identity.get("size")
            != batch_identity["batch_manifest"]["size"]
            or not isinstance(manifest_selection_identity, dict)
            or manifest_selection_identity.get("sha256")
            != batch_identity["selection"]["sha256"]
            or manifest_selection_identity.get("size")
            != batch_identity["selection"]["size"]
            or manifest_payload.get("target_count") != len(selection_ids)
            or manifest_payload.get("inventory_manifest_sha256")
            != selection_payload.get("inventory_manifest_sha256")
            or len(selection_ids) != len(selection_payload["targets"])
            or len(approval_ids) != len(approval_payload["approved_target_ids"])
            or not approved_scope <= selection_ids
            or not approved_scope <= approval_ids
        ):
            raise RunnerPlanError("formal shard scope is not covered by selection and approval")
    if (
        (
            artifact_root == RUNNER_PRODUCTION_ARTIFACT_ROOT
            or RUNNER_PRODUCTION_ARTIFACT_ROOT in artifact_root.parents
        )
        and tool_root != RUNNER_IMMUTABLE_TOOL_ROOT
    ):
        raise RunnerPlanError(
            "production runner must use the immutable image tool root"
        )
    seen: set[str] = set()
    claimed_output_paths: list[Path] = []
    normalized_steps: list[dict[str, Any]] = []
    formal_plan = "selection_identity" in plan
    for raw_step in plan["steps"]:
        if not isinstance(raw_step, dict):
            raise RunnerPlanError("runner step must be an object")
        step = dict(raw_step)
        step_id = str(step.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", step_id) or step_id in seen:
            raise RunnerPlanError(f"runner step id is empty or duplicated: {step_id}")
        seen.add(step_id)
        kind = str(step.get("kind") or "")
        argv = step.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(value, str) and value for value in argv):
            raise RunnerPlanError(f"runner step {step_id} argv must be a string array")
        if (
            not isinstance(step.get("inputs", []), list)
            or not isinstance(step.get("outputs", []), list)
            or not isinstance(step.get("output_directories", []), list)
        ):
            raise RunnerPlanError(
                f"runner step {step_id} inputs, outputs and output_directories must be lists"
            )
        declared_input_paths: list[Path] = []
        for value in step.get("inputs", []):
            if not isinstance(value, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("sha256") or "")):
                raise RunnerPlanError(f"runner step {step_id} input requires a SHA-256 identity")
            input_path = _ensure_within(_declared_path(value, label="input"), artifact_root, "input path")
            if not input_path.is_file() or _sha256_file(input_path) != value["sha256"]:
                raise RunnerPlanError(f"runner step {step_id} input SHA does not match")
            declared_input_paths.append(input_path)
        declared_output_paths: list[Path] = []
        for value in step.get("outputs", []):
            output_path = _ensure_within(
                _declared_path(value, label="output"),
                artifact_root,
                "output path",
            )
            if formal_plan and output_path.relative_to(artifact_root).parts[:1] != ("outputs",):
                raise RunnerPlanError(
                    f"formal runner step {step_id} output must stay under outputs/"
                )
            declared_output_paths.append(output_path)
        declared_output_directories: list[Path] = []
        for value in step.get("output_directories", []):
            output_directory = _ensure_within(
                _declared_path(value, label="output directory"),
                artifact_root,
                "output directory",
            )
            if formal_plan and output_directory.relative_to(artifact_root).parts[:1] != (
                "outputs",
            ):
                raise RunnerPlanError(
                    f"formal runner step {step_id} output directory must stay under outputs/"
                )
            if output_directory.is_symlink() or (
                output_directory.exists() and not output_directory.is_dir()
            ):
                raise RunnerPlanError(
                    f"runner step {step_id} output directory is invalid"
                )
            declared_output_directories.append(output_directory)
        output_claims = [*declared_output_paths, *declared_output_directories]
        if len(set(output_claims)) != len(output_claims) or any(
            left in right.parents or right in left.parents
            for index, left in enumerate(output_claims)
            for right in output_claims[index + 1 :]
        ) or any(
            current == claimed
            or current in claimed.parents
            or claimed in current.parents
            for current in output_claims
            for claimed in claimed_output_paths
        ):
            raise RunnerPlanError(f"runner step {step_id} output paths overlap")
        claimed_output_paths.extend(output_claims)
        step["output_directories"] = [
            {"path": str(path)} for path in declared_output_directories
        ]
        if formal_plan:
            input_root = artifact_root / "inputs"
            raw_input_directories = step.get("input_directories", [])
            if not isinstance(raw_input_directories, list):
                raise RunnerPlanError(
                    f"formal runner step {step_id} input_directories must be a list"
                )
            declared_input_directories: list[Path] = []
            for value in raw_input_directories:
                directory = _ensure_within(
                    _declared_path(value, label="input directory"),
                    input_root,
                    "input directory",
                )
                if directory == input_root or directory.is_symlink() or not directory.is_dir():
                    raise RunnerPlanError(
                        f"formal runner step {step_id} input directory is invalid"
                    )
                directory_members = list(directory.rglob("*"))
                if any(path.is_symlink() for path in directory_members):
                    raise RunnerPlanError(
                        f"formal runner step {step_id} input directory contains a symlink"
                    )
                directory_files = {
                    path.resolve() for path in directory_members if path.is_file()
                }
                if not directory_files <= set(declared_input_paths):
                    raise RunnerPlanError(
                        f"formal runner step {step_id} input directory files are not declared"
                    )
                declared_input_directories.append(directory)
            for argument in argv[2:]:
                argument_path = Path(argument)
                if not argument_path.is_absolute():
                    continue
                try:
                    artifact_argument = argument_path.resolve()
                    artifact_argument.relative_to(artifact_root)
                except ValueError:
                    continue
                if artifact_argument == input_root or input_root in artifact_argument.parents:
                    if not any(
                        artifact_argument == input_path
                        for input_path in declared_input_paths
                    ) and artifact_argument not in declared_input_directories:
                        raise RunnerPlanError(
                            f"formal runner step {step_id} argv uses an undeclared input path"
                        )
                    continue
                if (
                    artifact_argument not in declared_output_paths
                    and artifact_argument not in declared_output_directories
                ):
                    raise RunnerPlanError(
                        f"formal runner step {step_id} argv uses an undeclared artifact path"
                    )
        executable = argv[0].casefold()
        if executable in _SHELL_PROGRAMS and any(flag in argv[1:3] for flag in _SHELL_FLAGS):
            raise RunnerPlanError(f"runner step {step_id} cannot invoke a shell")
        if kind == "python_tool":
            if phase == HistoricalBatchPhase.APPLY:
                raise RunnerPlanError("apply phase only permits approval-aware management commands")
            if executable not in _PYTHON_PROGRAMS or len(argv) < 2:
                raise RunnerPlanError(f"runner step {step_id} has no tool path")
            tool = _ensure_within(argv[1], tool_root, "tool path")
            relative = tool.relative_to(tool_root).as_posix()
            if (
                tool_root == RUNNER_IMMUTABLE_TOOL_ROOT
                and relative not in _APPROVED_HISTORICAL_PYTHON_TOOLS
            ):
                raise RunnerPlanError(
                    f"runner step {step_id} Python tool is not approved for historical batches"
                )
            expected = plan["tool_manifest"].get(relative)
            if not expected or not tool.is_file() or _sha256_file(tool) != expected:
                raise RunnerPlanError(f"runner step {step_id} tool SHA does not match manifest")
        elif kind in {"management", "verify"}:
            command = _management_command(argv)
            allowed = _WRITE_MANAGEMENT_COMMANDS if phase == HistoricalBatchPhase.APPLY else _READ_MANAGEMENT_COMMANDS
            if command not in allowed:
                raise RunnerPlanError(f"management command is not allowed in {phase}: {command}")
            if phase != HistoricalBatchPhase.APPLY and any(
                value.casefold() in _WRITE_ARGUMENTS
                or value.casefold().startswith("--action=apply")
                or value.casefold().startswith("--mode=commit")
                for value in argv[3:]
            ):
                raise RunnerPlanError(f"write argument is not allowed in {phase}: {command}")
            if phase == HistoricalBatchPhase.APPLY:
                approval = step.get("approval")
                expected_sha256 = step.get("expected_sha256")
                input_sha256s = {
                    value.get("sha256") for value in step.get("inputs", []) if isinstance(value, dict)
                }
                if (
                    not isinstance(approval, dict)
                    or approval.get("status") != "approved"
                    or not re.fullmatch(r"[0-9a-f]{64}", str(approval.get("sha256") or ""))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256 or ""))
                    or approval.get("sha256") not in input_sha256s
                    or expected_sha256 not in input_sha256s
                ):
                    raise RunnerPlanError(f"apply step {step_id} requires approval and expected SHA")
                _validate_apply_bindings(
                    step=step,
                    command=command,
                    artifact_root=artifact_root,
                )
        else:
            raise RunnerPlanError(f"runner step {step_id} has unsupported kind: {kind}")
        normalized_steps.append(step)
    normalized = dict(plan)
    normalized["phase"] = phase
    normalized["artifact_root"] = str(artifact_root)
    normalized["tool_root"] = str(tool_root)
    normalized["steps"] = normalized_steps
    return normalized


def validate_runner_resource_limits(plan: dict[str, Any]) -> dict[str, int]:
    """Bind a formal crawl plan to the effective runner phase settings."""

    limits = plan.get("resource_limits")
    if limits is None:
        return {}
    if plan.get("phase") != HistoricalBatchPhase.CRAWL:
        raise RunnerPlanError("resource identity is only supported for crawl plans")
    try:
        effective = {
            "request_budget": int(settings.HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET),
            "max_source_cache_bytes": int(
                settings.HISTORICAL_RACE_BACKFILL_MAX_SOURCE_CACHE_BYTES
            ),
            "min_free_disk_bytes": int(
                settings.HISTORICAL_RACE_BACKFILL_MIN_FREE_DISK_BYTES
            ),
            "request_interval_seconds": RUNNER_REQUEST_INTERVAL_SECONDS,
        }
    except (TypeError, ValueError) as exc:
        raise RunnerStateError("historical crawl resource settings must be integers") from exc
    if limits != effective:
        differences = {
            key: {"plan": limits.get(key), "effective": effective[key]}
            for key in effective
            if limits.get(key) != effective[key]
        }
        raise RunnerStateError(
            f"historical crawl resource identity does not match runner settings: {differences}"
        )
    return effective


def redact_runner_text(value: str, secret_values: Iterable[str]) -> str:
    redacted = value
    for secret in sorted({str(item) for item in secret_values if item}, key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def runner_secret_values_from_environment(extra_values: Iterable[str] = ()) -> list[str]:
    secret_markers = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "ACCESS_KEY")
    values = list(extra_values)
    values.extend(
        value
        for key, value in os.environ.items()
        if value and any(marker in key.upper() for marker in secret_markers)
    )
    return sorted(set(values), key=len, reverse=True)


def _write_atomic_bytes(path: str | Path, data: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        with suppress(OSError):
            temporary.unlink()
        raise RunnerStateError(f"cannot persist runner state: {exc}") from exc


def write_runtime_state(path: str | Path, payload: dict[str, Any]) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_atomic_bytes(path, data)


def load_runtime_state(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerStateError(f"cannot read runner state: {exc}") from exc
    if not isinstance(payload, dict):
        raise RunnerStateError("runner state must be an object")
    return payload


def _fail_new_runner_lease(*, run: HistoricalBatchRun, owner_token: str, reason: str) -> None:
    owner_sha = _owner_hash(owner_token)
    now = timezone.now()
    with transaction.atomic():
        locked_run = HistoricalBatchRun.objects.select_for_update().get(pk=run.pk)
        lock = HistoricalBatchLock.objects.select_for_update().get(key=RUNNER_LOCK_KEY)
        if lock.locked_by_run_id == run.pk and lock.owner_token_sha256 == owner_sha:
            lock.locked_by_run = None
            lock.owner_token_sha256 = ""
            lock.acquired_at = None
            lock.heartbeat_at = None
            lock.lease_expires_at = None
            lock.save()
        if (
            locked_run.status == HistoricalBatchRunStatus.RUNNING
            and locked_run.owner_token_sha256 == owner_sha
        ):
            locked_run.status = HistoricalBatchRunStatus.FAILED
            locked_run.lease_expires_at = None
            locked_run.error_message = reason
            locked_run.finished_at = now
            locked_run.save(
                update_fields={
                    "status",
                    "lease_expires_at",
                    "error_message",
                    "finished_at",
                    "updated_at",
                }
            )
    run.refresh_from_db()
    with suppress(Exception):
        _append_event(run, "lease_failed", owner_token=owner_token, detail={"reason": reason})


def acquire_runner_lease(
    *,
    run: HistoricalBatchRun,
    owner_token: str,
    lock_path: str | Path,
    lease_seconds: int = RUNNER_LEASE_SECONDS,
) -> RunnerLease:
    owner_sha = _owner_hash(owner_token)
    now = timezone.now()
    with transaction.atomic():
        locked_run = HistoricalBatchRun.objects.select_for_update().get(pk=run.pk)
        if locked_run.status not in {
            HistoricalBatchRunStatus.PLANNED,
            HistoricalBatchRunStatus.RUNNING,
            HistoricalBatchRunStatus.FAILED,
        }:
            raise RunnerLeaseError(f"runner state cannot acquire a lease: {locked_run.status}")
        if locked_run.owner_token_sha256 and locked_run.owner_token_sha256 != owner_sha:
            raise RunnerLeaseError("runner owner token does not match registered owner")
        lock, _ = HistoricalBatchLock.objects.select_for_update().get_or_create(key=RUNNER_LOCK_KEY)
        same_owner = lock.locked_by_run_id == run.pk and lock.owner_token_sha256 == owner_sha
        if lock.locked_by_run_id and not same_owner:
            state = "active" if lock.lease_expires_at and lock.lease_expires_at > now else "expired"
            lease_until = lock.lease_expires_at.isoformat() if lock.lease_expires_at else "unknown"
            raise RunnerLeaseError(
                f"historical runner lease is {state} and held by run={lock.locked_by_run_id} "
                f"owner={lock.owner_token_sha256[:12]} until={lease_until}"
            )
        lock.locked_by_run = run
        lock.owner_token_sha256 = owner_sha
        lock.acquired_at = lock.acquired_at if same_owner and lock.acquired_at else now
        lock.heartbeat_at = now
        lock.lease_expires_at = now + timedelta(seconds=lease_seconds)
        lock.save()
        locked_run.status = HistoricalBatchRunStatus.RUNNING
        locked_run.owner_token_sha256 = owner_sha
        locked_run.started_at = locked_run.started_at or now
        locked_run.heartbeat_at = now
        locked_run.lease_expires_at = lock.lease_expires_at
        locked_run.save(
            update_fields={
                "status",
                "owner_token_sha256",
                "started_at",
                "heartbeat_at",
                "lease_expires_at",
                "updated_at",
            }
        )
        run.status = locked_run.status
        run.owner_token_sha256 = owner_sha
        run.started_at = locked_run.started_at
        run.heartbeat_at = now
        run.lease_expires_at = lock.lease_expires_at

    path = Path(lock_path).absolute()
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.fdopen(os.open(path, flags, 0o600), "a+")
    except OSError as exc:
        reason = f"historical runner lock file cannot be opened safely: {path}"
        if not same_owner:
            _fail_new_runner_lease(run=run, owner_token=owner_token, reason=reason)
        raise RunnerLeaseError(reason) from exc
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        reason = f"historical runner file lock is held: {path}"
        if not same_owner:
            _fail_new_runner_lease(run=run, owner_token=owner_token, reason=reason)
        raise RunnerLeaseError(reason) from exc
    lease = RunnerLease(run_id=run.pk, lock_path=path, handle=handle)
    try:
        _append_event(run, "lease_acquired", owner_token=owner_token, detail={"lock_path": str(path)})
    except Exception:
        lease.close()
        if not same_owner:
            _fail_new_runner_lease(
                run=run,
                owner_token=owner_token,
                reason="historical runner lease audit event could not be persisted",
            )
        raise
    return lease


def heartbeat_runner_lease(
    *, run: HistoricalBatchRun, owner_token: str, lease_seconds: int = RUNNER_LEASE_SECONDS
) -> None:
    owner_sha = _owner_hash(owner_token)
    now = timezone.now()
    with transaction.atomic():
        lock = HistoricalBatchLock.objects.select_for_update().get(key=RUNNER_LOCK_KEY)
        if lock.locked_by_run_id != run.pk or lock.owner_token_sha256 != owner_sha:
            raise RunnerLeaseError("historical runner heartbeat owner does not match lease")
        lock.heartbeat_at = now
        lock.lease_expires_at = now + timedelta(seconds=lease_seconds)
        lock.save(update_fields={"heartbeat_at", "lease_expires_at", "updated_at"})
        HistoricalBatchRun.objects.filter(pk=run.pk).update(
            heartbeat_at=now,
            lease_expires_at=lock.lease_expires_at,
        )


def release_runner_lease(*, run: HistoricalBatchRun, owner_token: str) -> None:
    owner_sha = _owner_hash(owner_token)
    with transaction.atomic():
        lock = HistoricalBatchLock.objects.select_for_update().get(key=RUNNER_LOCK_KEY)
        if lock.locked_by_run_id != run.pk or lock.owner_token_sha256 != owner_sha:
            raise RunnerLeaseError("historical runner release owner does not match lease")
        lock.locked_by_run = None
        lock.owner_token_sha256 = ""
        lock.acquired_at = None
        lock.heartbeat_at = None
        lock.lease_expires_at = None
        lock.save()
        HistoricalBatchRun.objects.filter(pk=run.pk).update(lease_expires_at=None)
        _append_event(run, "lease_released", owner_token=owner_token)


def request_runner_pause(*, run: HistoricalBatchRun, requested_by: str, reason: str) -> None:
    if not requested_by.strip() or not reason.strip():
        raise RunnerStateError("pause request requires operator and reason")
    run.refresh_from_db()
    if run.status in {
        HistoricalBatchRunStatus.COMPLETED,
        HistoricalBatchRunStatus.FAILED,
        HistoricalBatchRunStatus.BLOCKED,
    }:
        raise RunnerStateError(f"cannot pause terminal runner state: {run.status}")
    now = timezone.now()
    HistoricalBatchRun.objects.filter(pk=run.pk).update(
        pause_requested_at=now,
        pause_requested_by=requested_by.strip(),
        pause_reason=reason.strip(),
    )
    run.refresh_from_db()
    _append_event(run, "pause_requested", detail={"requested_by": requested_by, "reason": reason})


def resume_runner_run(*, run: HistoricalBatchRun, owner_token: str) -> HistoricalBatchRun:
    owner_sha = _owner_hash(owner_token)
    run.refresh_from_db()
    if run.status == HistoricalBatchRunStatus.COMPLETED:
        return run
    if run.status != HistoricalBatchRunStatus.PAUSED:
        raise RunnerStateError(f"runner is not paused: {run.status}")
    if run.owner_token_sha256 and run.owner_token_sha256 != owner_sha:
        raise RunnerStateError("runner owner token does not match registered owner")
    run.status = HistoricalBatchRunStatus.PLANNED
    run.pause_requested_at = None
    run.pause_requested_by = ""
    run.pause_reason = ""
    run.paused_at = None
    run.save(
        update_fields={
            "status",
            "pause_requested_at",
            "pause_requested_by",
            "pause_reason",
            "paused_at",
            "updated_at",
        }
    )
    _append_event(run, "resumed", owner_token=owner_token)
    return run


def takeover_runner_lease(
    *,
    run: HistoricalBatchRun,
    new_owner_token: str,
    actor: str,
    reason: str,
    container_absent: bool,
    no_active_db_session: bool,
    checkpoint_matches: bool,
    lease_seconds: int = RUNNER_LEASE_SECONDS,
) -> None:
    if not actor.strip() or not reason.strip():
        raise RunnerLeaseError("stale takeover requires actor and reason")
    if not (container_absent and no_active_db_session and checkpoint_matches):
        raise RunnerLeaseError("stale takeover safety conditions are not satisfied")
    now = timezone.now()
    new_owner_sha = _owner_hash(new_owner_token)
    with transaction.atomic():
        lock = HistoricalBatchLock.objects.select_for_update().get(key=RUNNER_LOCK_KEY)
        if not lock.locked_by_run_id or not lock.lease_expires_at or lock.lease_expires_at >= now:
            raise RunnerLeaseError("historical runner lease is not expired")
        if lock.locked_by_run_id != run.pk:
            raise RunnerLeaseError("takeover run does not match the expired lease owner")
        old_owner_prefix = lock.owner_token_sha256[:12]
        lock.locked_by_run = run
        lock.owner_token_sha256 = new_owner_sha
        lock.acquired_at = now
        lock.heartbeat_at = now
        lock.lease_expires_at = now + timedelta(seconds=lease_seconds)
        lock.save()
        HistoricalBatchRun.objects.filter(pk=run.pk).update(
            status=HistoricalBatchRunStatus.PAUSED,
            owner_token_sha256=new_owner_sha,
            heartbeat_at=now,
            lease_expires_at=lock.lease_expires_at,
        )
    run.refresh_from_db()
    _append_event(
        run,
        "takeover",
        owner_token=new_owner_token,
        detail={"actor": actor, "reason": reason, "old_owner_prefix": old_owner_prefix},
    )


def _file_identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RunnerStateError(f"runner expected output is missing: {path}")
    return {"path": str(path), "size": path.stat().st_size, "sha256": _sha256_file(path)}


def _directory_identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_dir():
        raise RunnerStateError(f"runner expected output directory is missing: {path}")
    files: list[dict[str, Any]] = []
    for member in sorted(path.rglob("*")):
        if member.is_symlink():
            raise RunnerStateError(
                f"runner output directory contains a symlink: {member}"
            )
        if member.is_dir():
            continue
        if not member.is_file():
            raise RunnerStateError(
                f"runner output directory contains a special entry: {member}"
            )
        files.append(
            {
                "path": member.relative_to(path).as_posix(),
                "size": member.stat().st_size,
                "sha256": _sha256_file(member),
            }
        )
    return {"path": str(path), "files": files}


def _directory_identity_matches(identity: Any) -> bool:
    if not isinstance(identity, dict) or not isinstance(identity.get("path"), str):
        return False
    try:
        return _directory_identity(Path(identity["path"])) == identity
    except (OSError, RunnerStateError):
        return False


def _crawl_resource_paths(artifact_root: Path) -> tuple[Path, Path]:
    root = artifact_root.resolve()
    return (
        root / "runner-request-budget.json",
        root / "runner-source-cache-manifest.json",
    )


def _crawl_resource_artifacts(artifact_root: Path) -> list[dict[str, Any]]:
    artifacts = []
    for path in _crawl_resource_paths(artifact_root):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise RunnerStateError(f"runner resource artifact is not a regular file: {path}")
        if path.is_file():
            artifacts.append({"exists": True, **_file_identity(path)})
        else:
            artifacts.append({"exists": False, "path": str(path)})
    return artifacts


def _crawl_resource_artifacts_match(
    artifact_root: Path,
    artifacts: Any,
) -> bool:
    if not isinstance(artifacts, list) or len(artifacts) != 2:
        return False
    expected_paths = [str(path) for path in _crawl_resource_paths(artifact_root)]
    if [item.get("path") for item in artifacts if isinstance(item, dict)] != expected_paths:
        return False
    for item in artifacts:
        path = Path(item["path"])
        if path.is_symlink():
            return False
        if item.get("exists") is False:
            if path.exists():
                return False
            continue
        if (
            item.get("exists") is not True
            or not path.is_file()
            or path.stat().st_size != item.get("size")
            or _sha256_file(path) != item.get("sha256")
        ):
            return False
    return True


def _verify_declared_inputs(step: dict[str, Any]) -> list[dict[str, Any]]:
    identities = []
    for value in step.get("inputs", []):
        identity = _file_identity(Path(_declared_path(value, label="input")))
        if identity["sha256"] != value["sha256"]:
            raise RunnerStateError(f"runner step input changed after plan validation: {step['id']}")
        identities.append(identity)
    return identities


def _state_payload(
    run: HistoricalBatchRun,
    completed_steps: list[dict[str, Any]],
    *,
    resource_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "1.0",
        "run_id": run.run_id,
        "batch_id": run.batch_id,
        "phase": run.phase,
        "image_id": run.image_id,
        "image_revision": run.image_revision,
        "plan_sha256": run.plan_sha256,
        "completed_steps": completed_steps,
    }
    if resource_artifacts is not None:
        payload["resource_artifacts"] = resource_artifacts
    return payload


def _persist_runtime_checkpoint(
    *,
    run: HistoricalBatchRun,
    state_path: Path,
    completed_steps: list[dict[str, Any]],
    resource_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    state = _state_payload(
        run,
        completed_steps,
        resource_artifacts=resource_artifacts,
    )
    write_runtime_state(state_path, state)
    with transaction.atomic():
        run.checkpoint = state
        run.save(update_fields={"checkpoint", "updated_at"})
    return state


def _checkpoint_matches(run: HistoricalBatchRun, state: dict[str, Any]) -> bool:
    expected = {
        "run_id": run.run_id,
        "batch_id": run.batch_id,
        "phase": run.phase,
        "image_id": run.image_id,
        "image_revision": run.image_revision,
        "plan_sha256": run.plan_sha256,
    }
    if any(state.get(key) != value for key, value in expected.items()):
        return False
    for step in state.get("completed_steps", []):
        for output in step.get("outputs", []):
            path = Path(output["path"])
            if (
                path.is_symlink()
                or not path.is_file()
                or _sha256_file(path) != output["sha256"]
            ):
                return False
        if not all(
            _directory_identity_matches(identity)
            for identity in step.get("output_directories", [])
        ):
            return False
    if "resource_artifacts" in state and not _crawl_resource_artifacts_match(
        Path(run.artifact_root), state["resource_artifacts"]
    ):
        return False
    return run.checkpoint == state


def runner_checkpoint_matches(run: HistoricalBatchRun, state_path: str | Path | None = None) -> bool:
    expected_path = (Path(run.artifact_root) / "runner-state.json").resolve()
    path = Path(state_path).resolve() if state_path else expected_path
    if path != expected_path:
        return False
    if not path.exists():
        return not bool(run.checkpoint)
    try:
        return _checkpoint_matches(run, load_runtime_state(path))
    except (KeyError, OSError, RunnerStateError, TypeError, ValueError):
        return False


def runner_has_active_db_sessions(run: HistoricalBatchRun | None = None) -> bool:
    if connection.vendor != "postgresql":
        return False
    prefix = f"umanews-historical-runner:{run.run_id}:" if run else "umanews-historical-runner:"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_stat_activity
                WHERE application_name LIKE %s
                  AND pid <> pg_backend_pid()
            )
            """,
            [prefix + "%"],
        )
        return bool(cursor.fetchone()[0])


def _terminate_process_group(process: subprocess.Popen[str], grace_seconds: int = 15) -> None:
    if process.poll() is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def _crawl_step_environment(artifact_root: Path) -> dict[str, str]:
    try:
        request_budget = int(settings.HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET)
        max_cache_bytes = int(settings.HISTORICAL_RACE_BACKFILL_MAX_SOURCE_CACHE_BYTES)
        min_free_disk_bytes = int(settings.HISTORICAL_RACE_BACKFILL_MIN_FREE_DISK_BYTES)
    except (TypeError, ValueError) as exc:
        raise RunnerStateError("historical crawl resource settings must be integers") from exc
    if not 1 <= request_budget <= RUNNER_MAX_CRAWL_REQUESTS:
        raise RunnerStateError(
            f"historical crawl request budget must be between 1 and {RUNNER_MAX_CRAWL_REQUESTS}"
        )
    if not 1 <= max_cache_bytes <= RUNNER_MAX_SOURCE_CACHE_BYTES:
        raise RunnerStateError(
            "historical crawl source cache budget must be between 1 and "
            f"{RUNNER_MAX_SOURCE_CACHE_BYTES} bytes"
        )
    if min_free_disk_bytes < RUNNER_MIN_FREE_DISK_BYTES:
        raise RunnerStateError(
            f"historical crawl free disk floor must be at least {RUNNER_MIN_FREE_DISK_BYTES} bytes"
        )
    for path in _crawl_resource_paths(artifact_root):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise RunnerStateError(f"runner resource artifact is not a regular file: {path}")
    free_disk_bytes = shutil.disk_usage(artifact_root).free
    if free_disk_bytes < min_free_disk_bytes:
        raise RunnerStateError(
            "historical crawl artifact free disk is below the configured floor: "
            f"free={free_disk_bytes} minimum={min_free_disk_bytes}"
        )

    root = artifact_root.resolve()
    child_env = os.environ.copy()
    child_env.pop("RACE_EVENT_CRAWL_HOST_INTERVAL_ARTIFACT", None)
    child_env.update(
        {
            "RACE_EVENT_CRAWL_MAX_REQUESTS": str(request_budget),
            "RACE_EVENT_CRAWL_REQUEST_INTERVAL_SECONDS": str(
                RUNNER_REQUEST_INTERVAL_SECONDS
            ),
            "RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT": str(
                root / "runner-request-budget.json"
            ),
            "RACE_EVENT_CRAWL_MAX_SOURCE_CACHE_BYTES": str(max_cache_bytes),
            "RACE_EVENT_CRAWL_MIN_FREE_DISK_BYTES": str(min_free_disk_bytes),
            "RACE_EVENT_CRAWL_SOURCE_CACHE_ROOT": str(root),
            "RACE_EVENT_CRAWL_SOURCE_CACHE_MANIFEST": str(
                root / "runner-source-cache-manifest.json"
            ),
        }
    )
    return child_env


def execute_runner_plan(
    *,
    run: HistoricalBatchRun,
    plan_path: str | Path,
    owner_token: str,
    lock_path: str | Path,
    secret_values: Iterable[str] = (),
) -> HistoricalBatchRun:
    plan_file = Path(plan_path)
    _ensure_within(str(plan_file), Path(run.artifact_root).resolve(), "plan path")
    try:
        plan_bytes = plan_file.read_bytes()
    except OSError as exc:
        raise RunnerPlanError(f"runner plan cannot be read: {exc}") from exc
    if _sha256_bytes(plan_bytes) != run.plan_sha256:
        raise RunnerPlanError("runner plan SHA does not match registered run")
    plan = validate_runner_plan(json.loads(plan_bytes))
    for field in ("batch_id", "phase", "image_id", "image_revision", "artifact_root"):
        if str(plan[field]) != str(getattr(run, field)):
            raise RunnerPlanError(f"runner plan {field} does not match registered run")
    if Path(plan["tool_root"]).resolve() != Path(settings.HISTORICAL_RUNNER_TOOL_ROOT).resolve():
        raise RunnerPlanError("runner tool_root does not match immutable image tool root")
    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        raise RunnerStateError("historical runner application gate is disabled")
    if run.phase == HistoricalBatchPhase.CRAWL and not getattr(
        settings, "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK", False
    ):
        raise RunnerStateError("historical crawl network gate is disabled")
    if run.phase != HistoricalBatchPhase.CRAWL and getattr(
        settings, "HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK", False
    ):
        raise RunnerStateError("non-crawl runner cannot enable historical network gate")

    root = Path(run.artifact_root)
    child_env: dict[str, str] | None = None
    expected_lock_path = root / ".runner.lock"
    if expected_lock_path.is_symlink() or Path(lock_path).absolute() != expected_lock_path.absolute():
        raise RunnerPlanError("runner lock file must be the fixed artifact-root .runner.lock")
    state_path = root / "runner-state.json"
    logs_root = root / "runner-logs"
    if logs_root.is_symlink():
        raise RunnerStateError("runner log directory cannot be a symlink")
    logs_root.mkdir(parents=True, exist_ok=True)
    completed: list[dict[str, Any]] = []
    run.refresh_from_db()
    if run.status == HistoricalBatchRunStatus.COMPLETED:
        if not state_path.exists() or not _checkpoint_matches(run, load_runtime_state(state_path)):
            run.status = HistoricalBatchRunStatus.BLOCKED
            run.error_message = "completed runner checkpoint is missing or inconsistent"
            run.save(update_fields={"status", "error_message", "updated_at"})
            _append_event(run, "blocked", owner_token=owner_token, detail={"reason": run.error_message})
            raise RunnerStateError("completed runner checkpoint is missing or inconsistent")
        return run
    if run.checkpoint and not state_path.exists():
        run.status = HistoricalBatchRunStatus.BLOCKED
        run.error_message = "database checkpoint exists but runtime state is missing"
        run.save(update_fields={"status", "error_message", "updated_at"})
        _append_event(run, "blocked", owner_token=owner_token, detail={"reason": run.error_message})
        raise RunnerStateError(run.error_message)
    if state_path.exists():
        state = load_runtime_state(state_path)
        run.refresh_from_db()
        if not _checkpoint_matches(run, state):
            run.status = HistoricalBatchRunStatus.BLOCKED
            run.error_message = "runtime/database checkpoint mismatch"
            run.save(update_fields={"status", "error_message", "updated_at"})
            _append_event(run, "blocked", owner_token=owner_token, detail={"reason": run.error_message})
            raise RunnerStateError(run.error_message)
        completed = list(state.get("completed_steps", []))
    completed_ids = {item["id"] for item in completed}
    if (
        run.phase == HistoricalBatchPhase.APPLY
        and run.status == HistoricalBatchRunStatus.FAILED
        and run.current_step
        and run.current_step not in completed_ids
    ):
        run.status = HistoricalBatchRunStatus.BLOCKED
        run.error_message = "unfinished apply step requires importer and database verification"
        run.save(update_fields={"status", "error_message", "updated_at"})
        _append_event(run, "blocked", owner_token=owner_token, detail={"reason": run.error_message})
        raise RunnerStateError(run.error_message)
    if (
        run.phase == HistoricalBatchPhase.CRAWL
        and completed
        and "resource_artifacts" not in run.checkpoint
    ):
        run.status = HistoricalBatchRunStatus.BLOCKED
        run.error_message = "legacy crawl checkpoint has no resource artifact identity"
        run.save(update_fields={"status", "error_message", "updated_at"})
        _append_event(run, "blocked", owner_token=owner_token, detail={"reason": run.error_message})
        raise RunnerStateError(run.error_message)
    if run.phase == HistoricalBatchPhase.CRAWL:
        child_env = _crawl_step_environment(root)
        for private_name in (
            RUNNER_OWNER_TOKEN_ENV,
            RUNNER_PLAN_PATH_ENV,
            RUNNER_STEP_ID_ENV,
        ):
            child_env.pop(private_name, None)
    published_before = (
        set(
            RaceEvent.objects.filter(visibility_status=RaceEventVisibility.PUBLISHED).values_list(
                "pk", flat=True
            )
        )
        if run.write_enabled
        else None
    )
    lease = acquire_runner_lease(run=run, owner_token=owner_token, lock_path=lock_path)
    active_process: subprocess.Popen[str] | None = None
    step_process_started = False
    previous_handlers: dict[int, Any] = {}

    def interrupt_handler(signum, _frame):
        raise RunnerStateError(f"historical runner interrupted by signal {signum}")

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, interrupt_handler)
    try:
        if run.phase == HistoricalBatchPhase.CRAWL and "resource_artifacts" not in run.checkpoint:
            _persist_runtime_checkpoint(
                run=run,
                state_path=state_path,
                completed_steps=completed,
                resource_artifacts=_crawl_resource_artifacts(root),
            )
        for step in plan["steps"]:
            step_process_started = False
            run.refresh_from_db()
            if (
                run.phase == HistoricalBatchPhase.CRAWL
                and completed
                and "resource_artifacts" in run.checkpoint
                and not _crawl_resource_artifacts_match(
                    root, run.checkpoint["resource_artifacts"]
                )
            ):
                run.status = HistoricalBatchRunStatus.BLOCKED
                run.error_message = "crawl resource artifact checkpoint changed between steps"
                run.save(update_fields={"status", "error_message", "updated_at"})
                _append_event(
                    run,
                    "blocked",
                    owner_token=owner_token,
                    detail={"reason": run.error_message},
                )
                raise RunnerStateError(run.error_message)
            if run.pause_requested_at:
                run.status = HistoricalBatchRunStatus.PAUSED
                run.paused_at = timezone.now()
                run.current_step = ""
                run.save(update_fields={"status", "paused_at", "current_step", "updated_at"})
                _append_event(run, "paused", owner_token=owner_token)
                return run
            if step["id"] in completed_ids:
                continue
            heartbeat_runner_lease(run=run, owner_token=owner_token)
            run.current_step = step["id"]
            run.save(update_fields={"current_step", "updated_at"})
            started_at = timezone.now()
            input_identities = _verify_declared_inputs(step)
            _append_event(run, "step_started", owner_token=owner_token, step_id=step["id"])
            with (
                tempfile.TemporaryFile(mode="w+b", dir=tempfile.gettempdir()) as stdout_stream,
                tempfile.TemporaryFile(mode="w+b", dir=tempfile.gettempdir()) as stderr_stream,
            ):
                step_env = child_env
                try:
                    step_command = _management_command(step["argv"])
                except RunnerPlanError:
                    step_command = ""
                if step_command in {
                    "import_historical_race_detail_chunk",
                    "verify_historical_race_detail_chunk",
                    "reconcile_historical_race_detail_receipt",
                }:
                    step_env = dict(child_env or os.environ.copy())
                    for private_name in (
                        RUNNER_OWNER_TOKEN_ENV,
                        RUNNER_PLAN_PATH_ENV,
                        RUNNER_STEP_ID_ENV,
                    ):
                        step_env.pop(private_name, None)
                    step_env.update(
                        {
                            RUNNER_OWNER_TOKEN_ENV: owner_token,
                            RUNNER_PLAN_PATH_ENV: str(plan_file.resolve()),
                            RUNNER_STEP_ID_ENV: step["id"],
                        }
                    )
                active_process = subprocess.Popen(
                    step["argv"],
                    cwd=str(Path(__file__).resolve().parents[2]),
                    env=step_env,
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    shell=False,
                    start_new_session=True,
                )
                step_process_started = True
                try:
                    while True:
                        try:
                            return_code = active_process.wait(timeout=RUNNER_HEARTBEAT_SECONDS)
                            break
                        except subprocess.TimeoutExpired:
                            heartbeat_runner_lease(run=run, owner_token=owner_token)
                except BaseException:
                    _terminate_process_group(active_process)
                    raise
                stdout_stream.seek(0)
                stderr_stream.seek(0)
                stdout = stdout_stream.read().decode("utf-8", errors="replace")
                stderr = stderr_stream.read().decode("utf-8", errors="replace")
            active_process = None
            redaction_values = (*secret_values, owner_token)
            stdout = redact_runner_text(stdout, redaction_values)
            stderr = redact_runner_text(stderr, redaction_values)
            _write_atomic_bytes(
                logs_root / f"{step['id']}.stdout.log",
                stdout.encode("utf-8"),
            )
            _write_atomic_bytes(
                logs_root / f"{step['id']}.stderr.log",
                stderr.encode("utf-8"),
            )
            if return_code:
                diagnostic = _tail_utf8(stderr or stdout, RUNNER_STREAM_SUMMARY_BYTES).strip()
                suffix = f" diagnostic={diagnostic}" if diagnostic else ""
                raise RunnerStateError(f"runner step failed: {step['id']} exit={return_code}{suffix}")
            outputs = [
                _file_identity(Path(_declared_path(value, label="output")))
                for value in step.get("outputs", [])
            ]
            output_directories = [
                _directory_identity(
                    Path(_declared_path(value, label="output directory"))
                )
                for value in step.get("output_directories", [])
            ]
            record = {
                "id": step["id"],
                "argv_sha256": _sha256_bytes(json.dumps(step["argv"]).encode("utf-8")),
                "started_at": started_at.isoformat(),
                "finished_at": timezone.now().isoformat(),
                "exit_code": return_code,
                "stdout_summary": _tail_utf8(stdout, RUNNER_STREAM_SUMMARY_BYTES),
                "stderr_summary": _tail_utf8(stderr, RUNNER_STREAM_SUMMARY_BYTES),
                "inputs": input_identities,
                "outputs": outputs,
                "output_directories": output_directories,
            }
            completed.append(record)
            with transaction.atomic():
                _persist_runtime_checkpoint(
                    run=run,
                    state_path=state_path,
                    completed_steps=completed,
                    resource_artifacts=(
                        _crawl_resource_artifacts(root)
                        if run.phase == HistoricalBatchPhase.CRAWL
                        else None
                    ),
                )
                _append_event(
                    run,
                    "step_completed",
                    owner_token=owner_token,
                    step_id=step["id"],
                    detail=record,
                )
            step_process_started = False
        if published_before is not None:
            published_after = set(
                RaceEvent.objects.filter(visibility_status=RaceEventVisibility.PUBLISHED).values_list(
                    "pk", flat=True
                )
            )
            if published_after != published_before:
                raise RunnerStateError("historical runner changed published RaceEvent identities")
        run.status = HistoricalBatchRunStatus.COMPLETED
        run.current_step = ""
        run.finished_at = timezone.now()
        run.error_message = ""
        run.save(update_fields={"status", "current_step", "finished_at", "error_message", "updated_at"})
        _append_event(run, "completed", owner_token=owner_token)
        return run
    except BaseException as exc:
        if active_process is not None:
            _terminate_process_group(active_process)
        checkpoint_error = ""
        if (
            run.phase == HistoricalBatchPhase.CRAWL
            and step_process_started
            and run.status != HistoricalBatchRunStatus.BLOCKED
        ):
            try:
                _persist_runtime_checkpoint(
                    run=run,
                    state_path=state_path,
                    completed_steps=completed,
                    resource_artifacts=_crawl_resource_artifacts(root),
                )
            except Exception as resource_exc:
                checkpoint_error = f"; resource checkpoint failed: {resource_exc}"
        run.refresh_from_db()
        published_changed = bool(
            published_before is not None
            and set(
                RaceEvent.objects.filter(visibility_status=RaceEventVisibility.PUBLISHED).values_list(
                    "pk", flat=True
                )
            )
            != published_before
        )
        if published_changed:
            run.status = HistoricalBatchRunStatus.BLOCKED
            run.error_message = "failed historical runner changed published RaceEvent count"
        elif checkpoint_error:
            run.status = HistoricalBatchRunStatus.BLOCKED
            run.error_message = _tail_utf8(
                redact_runner_text(f"{exc}{checkpoint_error}", secret_values),
                RUNNER_SUMMARY_BYTES,
            )
        elif run.status != HistoricalBatchRunStatus.BLOCKED:
            run.status = HistoricalBatchRunStatus.FAILED
            run.error_message = _tail_utf8(
                redact_runner_text(str(exc), secret_values),
                RUNNER_SUMMARY_BYTES,
            )
        run.finished_at = timezone.now()
        run.save(update_fields={"status", "error_message", "finished_at", "updated_at"})
        _append_event(run, "failed", owner_token=owner_token, detail={"error": run.error_message})
        raise
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        with suppress(RunnerLeaseError, HistoricalBatchLock.DoesNotExist):
            release_runner_lease(run=run, owner_token=owner_token)
        lease.close()
        run.lease_expires_at = None


def runner_status_payload(run: HistoricalBatchRun | None) -> dict[str, Any]:
    if run is None:
        return {"state": "idle", "run": None}
    now = timezone.now()
    heartbeat_age = (now - run.heartbeat_at).total_seconds() if run.heartbeat_at else None
    lock = HistoricalBatchLock.objects.filter(key=RUNNER_LOCK_KEY).first()
    lock_matches = bool(
        lock
        and lock.locked_by_run_id == run.pk
        and lock.owner_token_sha256 == run.owner_token_sha256
        and lock.lease_expires_at
        and lock.lease_expires_at > now
    )
    artifact_root = Path(run.artifact_root)
    checkpoint_matches = runner_checkpoint_matches(run) if artifact_root.is_dir() else None
    degraded_reasons = []
    if run.status == HistoricalBatchRunStatus.RUNNING and not lock_matches:
        degraded_reasons.append("lease_not_owned_or_expired")
    if checkpoint_matches is False:
        degraded_reasons.append("checkpoint_mismatch")
    return {
        "run_id": run.run_id,
        "batch_id": run.batch_id,
        "phase": run.phase,
        "state": run.status,
        "image_id": run.image_id,
        "image_revision": run.image_revision,
        "plan_sha256": run.plan_sha256,
        "owner_token_prefix": run.owner_token_sha256[:12],
        "current_step": run.current_step,
        "checkpoint": run.checkpoint,
        "heartbeat_age_seconds": heartbeat_age,
        "lock_matches": lock_matches,
        "checkpoint_matches": checkpoint_matches,
        "degraded_reasons": degraded_reasons,
        "lease_expires_at": run.lease_expires_at.isoformat() if run.lease_expires_at else None,
        "pause_requested_at": run.pause_requested_at.isoformat() if run.pause_requested_at else None,
        "paused_at": run.paused_at.isoformat() if run.paused_at else None,
        "error": run.error_message,
        "healthy": bool(
            run.status == HistoricalBatchRunStatus.RUNNING
            and heartbeat_age is not None
            and heartbeat_age <= RUNNER_LEASE_SECONDS
            and lock_matches
            and checkpoint_matches is not False
        ),
    }

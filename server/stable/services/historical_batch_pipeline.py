from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from stable.models import RacingRegion
from stable.services.historical_batch_runner import (
    RUNNER_MAX_CRAWL_REQUESTS,
    RUNNER_REQUEST_INTERVAL_SECONDS,
    validate_runner_plan,
)
from stable.services.regions import RACE_DATA_REGIONS


PIPELINE_SCHEMA_VERSION = "1.0"
MERGE_SCHEMA_VERSION = "1.0"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_IMAGE_RE = re.compile(r"sha256:[0-9a-f]{64}")
_REVISION_RE = re.compile(r"[0-9a-f]{40}")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_VALID_REGIONS = set(RACE_DATA_REGIONS)


class HistoricalBatchPipelineError(ValueError):
    pass


class HistoricalBatchEvidenceConflict(HistoricalBatchPipelineError):
    pass


def _valid_iso_timestamp(value: Any) -> bool:
    text = str(value or "")
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        text,
    ):
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HistoricalBatchPipelineError(f"artifact input must be a regular non-symlink file: {path}")
    return {"path": str(path), "size": path.stat().st_size, "sha256": _sha256_file(path)}


def _read_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        if path.is_symlink() or not path.is_file():
            raise HistoricalBatchPipelineError(f"{label} must be a regular non-symlink file")
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalBatchPipelineError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise HistoricalBatchPipelineError(f"{label} must be a JSON object")
    return payload, raw


def _read_jsonl(paths: Iterable[Path], *, label: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for path in paths:
        identity = _identity(path)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise HistoricalBatchPipelineError(f"{label} is unreadable: {path}") from exc
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HistoricalBatchPipelineError(
                    f"{label} has invalid JSON at {path}:{line_number}"
                ) from exc
            if not isinstance(payload, dict):
                raise HistoricalBatchPipelineError(
                    f"{label} row must be an object at {path}:{line_number}"
                )
            evidence = {
                "path": path.name,
                "sha256": identity["sha256"],
                "size": identity["size"],
                "file_sha256": identity["sha256"],
                "file_size": identity["size"],
                "line_number": line_number,
            }
            rows.append((payload, evidence))
    return rows


def _read_gap_fragments(
    paths: Iterable[Path],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for path in paths:
        identity = _identity(path)
        try:
            text = path.read_text(encoding="utf-8-sig")
            payload = json.loads(text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            rows.extend(_read_jsonl([path], label="gap"))
            continue
        if isinstance(payload, dict):
            rows.extend(_read_jsonl([path], label="gap"))
            continue
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise HistoricalBatchPipelineError(f"gap JSON must be an array of objects: {path}")
        for item_index, row in enumerate(payload):
            rows.append(
                (
                    row,
                    {
                        "path": path.name,
                        "sha256": identity["sha256"],
                        "size": identity["size"],
                        "item_index": item_index,
                    },
                )
            )
    return rows


def _validated_identity(value: Any, *, label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(value, dict):
        raise HistoricalBatchPipelineError(f"{label} identity must be an object")
    path = Path(str(value.get("path") or ""))
    expected = str(value.get("sha256") or "")
    if not _SHA256_RE.fullmatch(expected):
        raise HistoricalBatchPipelineError(f"{label} identity has invalid SHA-256")
    actual = _identity(path)
    if actual["sha256"] != expected:
        raise HistoricalBatchPipelineError(f"{label} SHA-256 mismatch")
    return path, actual


def _strict_json_integer(value: Any, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise HistoricalBatchPipelineError(f"{label} must be a JSON integer")
    return value


def _load_selection(path: Path) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    payload, _raw = _read_json(path, label="selection snapshot")
    if payload.get("schema_version") != "1.0" or not isinstance(payload.get("targets"), list):
        raise HistoricalBatchPipelineError("selection snapshot schema is invalid")
    inventory_sha = str(payload.get("inventory_manifest_sha256") or "")
    if not _SHA256_RE.fullmatch(inventory_sha):
        raise HistoricalBatchPipelineError("selection inventory identity is invalid")
    targets: dict[int, dict[str, Any]] = {}
    identities: set[tuple[str, int]] = set()
    for row in payload["targets"]:
        if not isinstance(row, dict):
            raise HistoricalBatchPipelineError("selection target must be an object")
        try:
            target_id = _strict_json_integer(
                row["target_id"], label="selection target_id"
            )
            year = _strict_json_integer(row["year"], label="selection year")
        except (KeyError, HistoricalBatchPipelineError) as exc:
            raise HistoricalBatchPipelineError("selection target identity is invalid") from exc
        series_key = str(row.get("series_key") or "")
        region = str(row.get("country_region") or "")
        target_sha = str(row.get("target_sha256") or "")
        target_inventory_sha = str(row.get("inventory_artifact_sha256") or inventory_sha)
        if (
            target_id <= 0
            or target_id in targets
            or not series_key
            or region not in _VALID_REGIONS
            or not _SHA256_RE.fullmatch(target_sha)
            or target_inventory_sha != inventory_sha
            or (series_key, year) in identities
        ):
            raise HistoricalBatchPipelineError(f"selection target is invalid or duplicated: {target_id}")
        normalized = dict(row)
        normalized.update(
            {
                "target_id": target_id,
                "year": year,
                "series_key": series_key,
                "country_region": region,
                "inventory_artifact_sha256": inventory_sha,
            }
        )
        targets[target_id] = normalized
        identities.add((series_key, year))
    if not targets:
        raise HistoricalBatchPipelineError("selection snapshot has no targets")
    return payload, targets


def _target_ids_from_events(paths: list[Path]) -> set[int]:
    target_ids: set[int] = set()
    for path in paths:
        _identity(path)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if "target_id" not in (reader.fieldnames or []):
                raise HistoricalBatchPipelineError(f"events CSV has no target_id: {path}")
            for row in reader:
                try:
                    target_id = int(row["target_id"])
                except (TypeError, ValueError) as exc:
                    raise HistoricalBatchPipelineError(f"events CSV target_id is invalid: {path}") from exc
                if target_id in target_ids:
                    raise HistoricalBatchPipelineError(f"events CSV target_id is duplicated: {target_id}")
                target_ids.add(target_id)
    return target_ids


def _event_local_dates(paths: list[Path]) -> dict[int, date]:
    event_dates: dict[int, date] = {}
    for path in paths:
        _identity(path)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"target_id", "local_date"}
            if not required <= set(reader.fieldnames or []):
                raise HistoricalBatchPipelineError(
                    f"events CSV lacks date scope fields: {path}"
                )
            for row in reader:
                try:
                    target_id = int(row["target_id"])
                    local_date = date.fromisoformat(str(row["local_date"] or ""))
                except (TypeError, ValueError) as exc:
                    raise HistoricalBatchPipelineError(
                        f"events CSV local_date is invalid: {path}"
                    ) from exc
                if target_id in event_dates:
                    raise HistoricalBatchPipelineError(
                        f"events CSV target_id is duplicated: {target_id}"
                    )
                event_dates[target_id] = local_date
    return event_dates


def _event_candidate_identity_map(paths: list[Path]) -> tuple[set[int], dict[tuple[int, str], int]]:
    target_ids: set[int] = set()
    identities: dict[tuple[int, str], int] = {}
    for path in paths:
        _identity(path)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"target_id", "year", "slug"}
            if not required <= set(reader.fieldnames or []):
                raise HistoricalBatchPipelineError(
                    f"events CSV lacks candidate identity fields: {path}"
                )
            for row in reader:
                try:
                    target_id = int(row["target_id"])
                    identity = (int(row["year"]), str(row["slug"] or ""))
                except (TypeError, ValueError) as exc:
                    raise HistoricalBatchPipelineError(
                        f"events CSV candidate identity is invalid: {path}"
                    ) from exc
                if (
                    target_id in target_ids
                    or not identity[1]
                    or identity in identities
                ):
                    raise HistoricalBatchPipelineError(
                        f"events CSV candidate identity is duplicated: {path}"
                    )
                target_ids.add(target_id)
                identities[identity] = target_id
    return target_ids, identities


def _package_candidate_target_ids(
    *, candidate_paths: list[Path], event_paths: list[Path]
) -> set[int]:
    event_target_ids, event_identities = _event_candidate_identity_map(event_paths)
    candidate_target_ids: set[int] = set()
    for row, _evidence in _read_jsonl(candidate_paths, label="package candidate JSONL"):
        try:
            candidate_year = _strict_json_integer(
                row["year"], label="package candidate year"
            )
            target_id = event_identities[(candidate_year, str(row["slug"]))]
            if row.get("target_id") not in (None, "") and _strict_json_integer(
                row["target_id"], label="package candidate target_id"
            ) != target_id:
                raise KeyError
            if target_id not in event_target_ids:
                raise KeyError
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalBatchPipelineError(
                "package candidate is outside the shard events scope"
            ) from exc
        if target_id in candidate_target_ids:
            raise HistoricalBatchPipelineError(
                f"package candidate target is duplicated: {target_id}"
            )
        candidate_target_ids.add(target_id)
    return candidate_target_ids


def _gap_fragment_target_ids(
    paths: list[Path], *, targets_by_identity: dict[tuple[str, int], int]
) -> set[int]:
    target_ids: set[int] = set()
    for row, _evidence in _read_gap_fragments(paths):
        try:
            if row.get("target_id") not in (None, ""):
                target_id = _strict_json_integer(
                    row["target_id"], label="gap fragment target_id"
                )
            else:
                edition_year = _strict_json_integer(
                    row["edition_year"], label="gap fragment edition_year"
                )
                target_id = targets_by_identity[
                    (str(row["series_key"]), edition_year)
                ]
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalBatchPipelineError(
                "gap fragment target is outside selection"
            ) from exc
        if row.get("series_key") not in (None, "") or row.get("edition_year") not in (
            None,
            "",
        ):
            try:
                edition_year = _strict_json_integer(
                    row["edition_year"], label="gap fragment edition_year"
                )
                identity_target_id = targets_by_identity[(str(row["series_key"]), edition_year)]
            except (KeyError, TypeError, ValueError) as exc:
                raise HistoricalBatchPipelineError(
                    "gap fragment target identity is outside selection"
                ) from exc
            if identity_target_id != target_id:
                raise HistoricalBatchPipelineError(
                    "gap fragment target identities conflict"
                )
        if target_id in target_ids:
            raise HistoricalBatchPipelineError(
                f"gap fragment target is duplicated: {target_id}"
            )
        target_ids.add(target_id)
    return target_ids


def _target_ids_from_selection(paths: list[Path]) -> set[int]:
    target_ids: set[int] = set()
    for path in paths:
        _payload, targets = _load_selection(path)
        overlap = target_ids & targets.keys()
        if overlap:
            raise HistoricalBatchPipelineError(f"selection input target is duplicated: {sorted(overlap)[:5]}")
        target_ids.update(targets)
    return target_ids


def _target_ids_from_jsonl(
    paths: list[Path],
    *,
    targets_by_identity: dict[tuple[str, int], int],
    allow_duplicate_targets: bool = False,
) -> set[int]:
    target_ids: set[int] = set()
    for row, _evidence in _read_jsonl(paths, label="recipe JSONL"):
        if row.get("target_id") not in (None, ""):
            try:
                target_id = _strict_json_integer(
                    row["target_id"], label="recipe JSONL target_id"
                )
            except HistoricalBatchPipelineError as exc:
                raise HistoricalBatchPipelineError("recipe JSONL target_id is invalid") from exc
        else:
            try:
                edition_year = _strict_json_integer(
                    row["edition_year"], label="recipe JSONL edition_year"
                )
                identity = (str(row["series_key"]), edition_year)
                target_id = targets_by_identity[identity]
            except (KeyError, HistoricalBatchPipelineError) as exc:
                raise HistoricalBatchPipelineError("recipe JSONL target identity is outside selection") from exc
        if row.get("series_key") not in (None, "") or row.get("edition_year") not in (None, ""):
            try:
                edition_year = _strict_json_integer(
                    row["edition_year"], label="recipe JSONL edition_year"
                )
                identity_target_id = targets_by_identity[(str(row["series_key"]), edition_year)]
            except (KeyError, HistoricalBatchPipelineError) as exc:
                raise HistoricalBatchPipelineError(
                    "recipe JSONL target identity is outside selection"
                ) from exc
            if identity_target_id != target_id:
                raise HistoricalBatchPipelineError(
                    "recipe JSONL target identities conflict"
                )
        if target_id in target_ids and not allow_duplicate_targets:
            raise HistoricalBatchPipelineError(f"recipe JSONL target is duplicated: {target_id}")
        target_ids.add(target_id)
    return target_ids


_RECIPE_POLICIES: dict[str, dict[str, Any]] = {
    "discover_historical_race_band_sources.py": {
        "scope_key": "selection_snapshot",
        "scope_kind": "selection",
        "required_options": {"year"},
        "inputs": {
            "selection_snapshot": ("--selection-snapshot", "one"),
            "jra_english_schedule": ("--jra-english-schedule", "optional"),
            "jra_history": ("--jra-history", "optional"),
            "toba": ("--toba", "optional"),
        },
        "outputs": {"output_jsonl": "--output-jsonl", "issues_json": "--issues-json"},
        "options": {"year": "--year"},
    },
    "cache_historical_race_date_sources.py": {
        "scope_key": "provider_jsonl",
        "scope_kind": "jsonl",
        "allow_duplicate_scope_rows": True,
        "inputs": {"provider_jsonl": ("--provider-jsonl", "many")},
        "outputs": {
            "output_root": "--output-root",
            "request_ledger": "--request-ledger",
            "summary": "--summary",
        },
        "output_directories": {"output_root"},
        "options": {
            "timeout": "--timeout",
            "allow_network": "--allow-network",
            "allow_partial": "--allow-partial",
        },
    },
    "prepare_historical_race_calendar_inputs.py": {
        "phases": {"verify"},
        "scope_key": "selection_snapshot",
        "scope_kind": "selection",
        "required_options": {"country_region", "year", "recorded_at"},
        "inputs": {
            "selection_snapshot": ("--selection-snapshot", "one"),
            "source_catalog": ("--source-catalog", "one"),
            "source_cache_manifest": ("--source-cache-manifest", "one"),
            "request_ledger": ("--request-ledger", "one"),
            "source_cache_root": ("--source-cache-root", "directory"),
        },
        "outputs": {"output_dir": "--output-dir"},
        "output_directories": {"output_dir"},
        "options": {
            "country_region": "--country-region",
            "year": "--year",
            "recorded_at": "--recorded-at",
        },
    },
    "prepare_jra_race_detail_candidates.py": {
        "regions": {RacingRegion.JAPAN},
        "scope_key": "events_csv",
        "scope_kind": "events",
        "inputs": {
            "events_csv": ("--events-csv", "one"),
            "source_html": ("--source-html", "one"),
        },
        "outputs": {"output_dir": "--output-dir"},
        "output_directories": {"output_dir"},
        "options": {
            "allow_network": "--allow-network",
            "limit": "--limit",
            "timeout_seconds": "--timeout-seconds",
            "fail_fast": "--fail-fast",
        },
    },
    "prepare_hkjc_race_detail_candidates.py": {
        "regions": {RacingRegion.HONG_KONG},
        "scope_key": "events_csv",
        "scope_kind": "events",
        "inputs": {"events_csv": ("--events-csv", "one")},
        "outputs": {"output_dir": "--output-dir"},
        "output_directories": {"output_dir"},
        "options": {
            "allow_network": "--allow-network",
            "limit": "--limit",
            "timeout_seconds": "--timeout-seconds",
            "fail_fast": "--fail-fast",
        },
    },
    "prepare_uk_sportinglife_race_detail_candidates.py": {
        "regions": {RacingRegion.UNITED_KINGDOM},
        "scope_key": "events_csv",
        "scope_kind": "events",
        "inputs": {"events_csv": ("--events-csv", "one")},
        "outputs": {"output_dir": "--output-dir"},
        "output_directories": {"output_dir"},
        "options": {
            "allow_network": "--allow-network",
            "limit": "--limit",
            "timeout_seconds": "--timeout-seconds",
            "sleep_seconds": "--sleep-seconds",
            "fail_fast": "--fail-fast",
        },
    },
    "prepare_france_zeturf_race_detail_candidates.py": {
        "regions": {RacingRegion.FRANCE},
        "scope_key": "events_csv",
        "scope_kind": "events",
        "inputs": {"events_csv": ("--events-csv", "one")},
        "outputs": {"output_dir": "--output-dir"},
        "output_directories": {"output_dir"},
        "options": {
            "allow_network": "--allow-network",
            "limit": "--limit",
            "start_date": "--start-date",
            "end_date": "--end-date",
            "max_r": "--max-r",
            "max_c": "--max-c",
            "timeout_seconds": "--timeout-seconds",
            "sleep_seconds": "--sleep-seconds",
            "fail_fast": "--fail-fast",
        },
    },
    "prepare_us_equibase_result_candidates.py": {
        "regions": {RacingRegion.UNITED_STATES},
        "scope_key": "events_csv",
        "scope_kind": "events",
        "inputs": {
            "events_csv": ("--events-csv", "one"),
            "runner_jsonl": ("--runner-jsonl", "one"),
            "pdf_dir": ("--pdf-dir", "directory"),
        },
        "outputs": {"output_dir": "--output-dir"},
        "output_directories": {"output_dir"},
        "options": {"fail_fast": "--fail-fast"},
    },
    "prepare_cached_historical_race_details.py": {
        "scope_key": "events_csv",
        "scope_kind": "events",
        "inputs": {
            "events_csv": ("--events-csv", "many"),
            "source_cache_manifest": ("--source-cache-manifest", "one"),
        },
        "outputs": {
            "output_jsonl": "--output-jsonl",
            "gap_json": "--gap-json",
            "summary": "--summary",
        },
        "options": {},
    },
    "package_historical_race_detail_candidates.py": {
        "scope_key": "events_csv",
        "scope_kind": "events",
        "inputs": {
            "events_csv": ("--events-csv", "many"),
            "candidate_jsonl": ("--candidate-jsonl", "many"),
            "source_cache_manifest": ("--source-cache-manifest", "many"),
        },
        "outputs": {
            "output_jsonl": "--output-jsonl",
            "gap_json": "--gap-json",
            "summary": "--summary",
        },
        "options": {},
    },
    "merge_historical_race_batch_fragments.py": {
        "scope_key": "selection",
        "scope_kind": "selection",
        "inputs": {
            "selection": ("--selection", "one"),
            "fragment": ("--fragment", "many"),
            "gap": ("--gap", "many_optional"),
            "evidence": ("--evidence", "many_optional"),
            "source_cache_manifest": ("--source-cache-manifest", "many_optional"),
        },
        "outputs": {"output_dir": "--output-dir"},
        "output_directories": {"output_dir"},
        "options": {"mode": "--mode", "recorded_at": "--recorded-at"},
    },
}


def _relative_output(value: Any, *, label: str) -> Path:
    path = Path(str(value or ""))
    if (
        path == Path(".")
        or path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.parts[0] != "outputs"
    ):
        raise HistoricalBatchPipelineError(
            f"{label} must be a safe relative path under outputs/"
        )
    return path


def _copy_input(source: Path, *, destination_root: Path, used_names: set[str]) -> Path:
    identity = _identity(source)
    name = source.name
    if name in used_names:
        name = f"{identity['sha256'][:12]}-{name}"
    used_names.add(name)
    destination = destination_root / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if _sha256_file(destination) != identity["sha256"]:
        raise HistoricalBatchPipelineError(f"copied input SHA mismatch: {source}")
    return destination


def _copy_input_directory(
    source: Path, *, destination_root: Path, used_names: set[str]
) -> tuple[Path, list[dict[str, Any]]]:
    if source.is_symlink() or not source.is_dir():
        raise HistoricalBatchPipelineError(f"artifact directory input is invalid: {source}")
    name = source.name
    if name in used_names:
        name = f"directory-{len(used_names):04d}-{name}"
    used_names.add(name)
    destination = destination_root / name
    identities: list[dict[str, Any]] = []
    destination.mkdir(parents=True)
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise HistoricalBatchPipelineError(f"artifact directory contains a symlink: {path}")
        relative = path.relative_to(source)
        copied = destination / relative
        if path.is_dir():
            copied.mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            raise HistoricalBatchPipelineError(f"artifact directory has non-file entry: {path}")
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, copied)
        source_identity = _identity(path)
        copied_identity = _identity(copied)
        if copied_identity["sha256"] != source_identity["sha256"]:
            raise HistoricalBatchPipelineError(f"copied directory input SHA mismatch: {path}")
        identities.append(copied_identity)
    return destination, identities


def _input_values(inputs: dict[str, Any], key: str, cardinality: str) -> list[Path]:
    raw = inputs.get(key)
    optional = cardinality in {"optional", "many_optional"}
    many = cardinality in {"many", "many_optional"}
    if raw in (None, "", []):
        if optional:
            return []
        raise HistoricalBatchPipelineError(f"recipe input is required: {key}")
    values = raw if isinstance(raw, list) else [raw]
    if not many and len(values) != 1:
        raise HistoricalBatchPipelineError(f"recipe input must appear once: {key}")
    paths = [Path(str(value)) for value in values]
    if cardinality == "directory":
        if len(paths) != 1 or paths[0].is_symlink() or not paths[0].is_dir():
            raise HistoricalBatchPipelineError(f"recipe directory input is invalid: {key}")
    else:
        for path in paths:
            _identity(path)
    return paths


def _recipe_scope(
    *,
    policy: dict[str, Any],
    original_inputs: dict[str, list[Path]],
    targets_by_identity: dict[tuple[str, int], int],
) -> set[int]:
    paths = original_inputs[policy["scope_key"]]
    if policy["scope_kind"] == "events":
        return _target_ids_from_events(paths)
    if policy["scope_kind"] == "selection":
        return _target_ids_from_selection(paths)
    if policy["scope_kind"] == "jsonl":
        return _target_ids_from_jsonl(
            paths,
            targets_by_identity=targets_by_identity,
            allow_duplicate_targets=bool(policy.get("allow_duplicate_scope_rows")),
        )
    raise HistoricalBatchPipelineError("recipe has unsupported target-binding policy")


def _append_option(argv: list[str], flag: str, value: Any) -> None:
    if isinstance(value, bool):
        if value:
            argv.append(flag)
        return
    if value in (None, ""):
        return
    if isinstance(value, (dict, list)):
        raise HistoricalBatchPipelineError(f"recipe option has invalid structured value: {flag}")
    argv.extend([flag, str(value)])


def _fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
    directories = [root, *[path for path in root.rglob("*") if path.is_dir()]]
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _atomic_publish_directory(output_dir: Path, writer) -> None:
    if output_dir.exists() or output_dir.is_symlink():
        raise HistoricalBatchPipelineError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent))
    published = False
    try:
        writer(temporary)
        _fsync_tree(temporary)
        temporary.rename(output_dir)
        published = True
        parent_fd = os.open(output_dir.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        cleanup = output_dir if published else temporary
        shutil.rmtree(cleanup, ignore_errors=True)
        raise


def build_historical_batch_shard_plan(
    *,
    descriptor_path: str | Path,
    shard_id: str,
    output_dir: str | Path,
) -> dict[str, Any]:
    descriptor_path = Path(descriptor_path)
    descriptor, _descriptor_raw = _read_json(descriptor_path, label="stage descriptor")
    if descriptor.get("schema_version") != PIPELINE_SCHEMA_VERSION:
        raise HistoricalBatchPipelineError("unsupported stage descriptor schema")
    if not _SAFE_ID_RE.fullmatch(str(descriptor.get("batch_id") or "")) or not _SAFE_ID_RE.fullmatch(
        str(descriptor.get("stage_id") or "")
    ):
        raise HistoricalBatchPipelineError("batch_id or stage_id is invalid")
    selection_path, selection_identity = _validated_identity(descriptor.get("selection"), label="selection")
    approval_path, approval_identity = _validated_identity(descriptor.get("approval"), label="approval")
    manifest_path, manifest_identity = _validated_identity(
        descriptor.get("batch_manifest"), label="batch manifest"
    )
    selection, targets = _load_selection(selection_path)
    batch_manifest, _manifest_raw = _read_json(manifest_path, label="batch manifest")
    approval, _approval_raw = _read_json(approval_path, label="approval")
    approved_ids = approval.get("approved_target_ids")
    selection_manifest_identity = (
        (batch_manifest.get("artifacts") or {}).get("selection_snapshot")
        if isinstance(batch_manifest.get("artifacts"), dict)
        else None
    )
    approval_manifest_identity = approval.get("manifest_identity")
    if (
        approval.get("status") != "approved"
        or not str(approval.get("approved_by") or "").strip()
        or not str(approval.get("approved_at") or "").strip()
        or not isinstance(approval_manifest_identity, dict)
        or approval_manifest_identity.get("sha256") != manifest_identity["sha256"]
        or approval_manifest_identity.get("size") != manifest_identity["size"]
        or not isinstance(selection_manifest_identity, dict)
        or selection_manifest_identity.get("sha256") != selection_identity["sha256"]
        or selection_manifest_identity.get("size") != selection_identity["size"]
        or batch_manifest.get("inventory_manifest_sha256")
        != selection.get("inventory_manifest_sha256")
        or batch_manifest.get("target_count") != len(targets)
        or not isinstance(approved_ids, list)
        or any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in approved_ids
        )
        or sorted(approved_ids) != sorted(targets)
    ):
        raise HistoricalBatchPipelineError("approval does not exactly authorize the selection")
    if not _IMAGE_RE.fullmatch(str(descriptor.get("image_id") or "")):
        raise HistoricalBatchPipelineError("image_id must be a full immutable SHA-256 ID")
    if not _REVISION_RE.fullmatch(str(descriptor.get("image_revision") or "")):
        raise HistoricalBatchPipelineError("image_revision must be a 40-character commit")
    tool_root = Path(str(descriptor.get("tool_root") or ""))
    if tool_root.is_symlink() or not tool_root.is_dir():
        raise HistoricalBatchPipelineError("tool_root must be a regular directory")
    tool_manifest = descriptor.get("tool_manifest")
    if not isinstance(tool_manifest, dict):
        raise HistoricalBatchPipelineError("tool_manifest must be an object")
    phase = str(descriptor.get("phase") or "crawl")
    if phase not in {"crawl", "verify"}:
        raise HistoricalBatchPipelineError("stage descriptor phase must be crawl or verify")
    limits = descriptor.get("resource_limits")
    if phase == "verify":
        if "resource_limits" in descriptor:
            raise HistoricalBatchPipelineError("verify stage cannot define resource_limits")
    else:
        if not isinstance(limits, dict):
            raise HistoricalBatchPipelineError("crawl stage resource_limits must be an object")
        for key in ("max_source_cache_bytes", "min_free_disk_bytes"):
            if (
                not isinstance(limits.get(key), int)
                or isinstance(limits.get(key), bool)
                or limits[key] <= 0
            ):
                raise HistoricalBatchPipelineError(f"resource limit is invalid: {key}")
        if "request_budget" in limits and (
            not isinstance(limits["request_budget"], int)
            or isinstance(limits["request_budget"], bool)
            or not 1 <= limits["request_budget"] <= RUNNER_MAX_CRAWL_REQUESTS
        ):
            raise HistoricalBatchPipelineError("resource limit is invalid: request_budget")
        if limits.get("request_interval_seconds") != RUNNER_REQUEST_INTERVAL_SECONDS:
            raise HistoricalBatchPipelineError(
                "request interval does not match the fixed runner contract"
            )

    shards = descriptor.get("shards")
    if not isinstance(shards, list) or not shards:
        raise HistoricalBatchPipelineError("descriptor shards must be a non-empty list")
    seen_shards: set[str] = set()
    seen_targets: set[int] = set()
    selected_shard: dict[str, Any] | None = None
    targets_by_identity = {
        (target["series_key"], target["year"]): target_id for target_id, target in targets.items()
    }
    validated_recipes: dict[str, list[tuple[dict[str, Any], dict[str, list[Path]], dict[str, Path]]]] = {}
    for shard in shards:
        if not isinstance(shard, dict):
            raise HistoricalBatchPipelineError("shard must be an object")
        current_id = str(shard.get("id") or "")
        if not _SAFE_ID_RE.fullmatch(current_id) or current_id in seen_shards:
            raise HistoricalBatchPipelineError(f"shard id is invalid or duplicated: {current_id}")
        seen_shards.add(current_id)
        region = str(shard.get("country_region") or "")
        target_ids = shard.get("target_ids")
        budget = shard.get("request_budget")
        if (
            region not in _VALID_REGIONS
            or not isinstance(target_ids, list)
            or not target_ids
            or not all(isinstance(value, int) for value in target_ids)
            or any(isinstance(value, bool) for value in target_ids)
            or len(target_ids) != len(set(target_ids))
            or len(target_ids) > RUNNER_MAX_CRAWL_REQUESTS
            or not isinstance(budget, int)
            or isinstance(budget, bool)
            or (
                phase == "crawl"
                and not 1 <= budget <= RUNNER_MAX_CRAWL_REQUESTS
            )
            or (phase == "verify" and budget != 0)
        ):
            raise HistoricalBatchPipelineError(f"shard limits are invalid: {current_id}")
        shard_scope = set(target_ids)
        if seen_targets & shard_scope:
            raise HistoricalBatchPipelineError(f"target appears in more than one shard: {current_id}")
        unknown = shard_scope - targets.keys()
        wrong_region = [target_id for target_id in shard_scope if targets[target_id]["country_region"] != region]
        if unknown or wrong_region:
            raise HistoricalBatchPipelineError(
                f"shard target is outside selection or region: {current_id}"
            )
        seen_targets.update(shard_scope)
        recipes = shard.get("recipes")
        if not isinstance(recipes, list) or not recipes:
            raise HistoricalBatchPipelineError(f"shard has no recipes: {current_id}")
        validated_recipes[current_id] = []
        output_claims: set[str] = set()
        for recipe in recipes:
            if not isinstance(recipe, dict) or "argv" in recipe:
                raise HistoricalBatchPipelineError("recipe cannot provide arbitrary argv")
            tool_name = str(recipe.get("tool") or "")
            policy = _RECIPE_POLICIES.get(tool_name)
            if policy is None:
                raise HistoricalBatchPipelineError(f"tool has no typed recipe policy: {tool_name}")
            if policy.get("phases") and phase not in policy["phases"]:
                raise HistoricalBatchPipelineError(
                    f"tool is not approved for stage phase: {tool_name}/{phase}"
                )
            if policy.get("regions") and region not in policy["regions"]:
                raise HistoricalBatchPipelineError(
                    f"tool does not support shard region: {tool_name}/{region}"
                )
            expected_tool_sha = str(tool_manifest.get(tool_name) or "")
            tool_path = tool_root / tool_name
            if (
                tool_path.is_symlink()
                or not tool_path.is_file()
                or not _SHA256_RE.fullmatch(expected_tool_sha)
                or _sha256_file(tool_path) != expected_tool_sha
            ):
                raise HistoricalBatchPipelineError(f"tool SHA does not match manifest: {tool_name}")
            raw_inputs = recipe.get("inputs")
            raw_outputs = recipe.get("outputs")
            raw_options = recipe.get("options", {})
            if not isinstance(raw_inputs, dict) or not isinstance(raw_outputs, dict) or not isinstance(raw_options, dict):
                raise HistoricalBatchPipelineError("recipe inputs, outputs and options must be objects")
            if set(raw_inputs) - set(policy["inputs"]):
                raise HistoricalBatchPipelineError(f"recipe has unknown inputs: {tool_name}")
            if set(raw_outputs) != set(policy["outputs"]):
                raise HistoricalBatchPipelineError(f"recipe outputs do not match policy: {tool_name}")
            if set(raw_options) - set(policy["options"]):
                raise HistoricalBatchPipelineError(f"recipe has unknown options: {tool_name}")
            if set(policy.get("required_options", set())) - set(raw_options):
                raise HistoricalBatchPipelineError(
                    f"recipe is missing required options: {tool_name}"
                )
            original_inputs = {
                key: _input_values(raw_inputs, key, cardinality)
                for key, (_flag, cardinality) in policy["inputs"].items()
            }
            if tool_name == "merge_historical_race_batch_fragments.py":
                if raw_options.get("mode") not in {"date", "detail"}:
                    raise HistoricalBatchPipelineError("merger recipe mode is invalid")
                if not raw_options.get("recorded_at"):
                    raise HistoricalBatchPipelineError("merger recipe requires recorded_at")
                if raw_options.get("mode") == "detail" and not original_inputs.get(
                    "source_cache_manifest"
                ):
                    raise HistoricalBatchPipelineError(
                        "detail merger recipe requires source cache manifests"
                    )
            actual_scope = _recipe_scope(
                policy=policy,
                original_inputs=original_inputs,
                targets_by_identity=targets_by_identity,
            )
            if tool_name == "discover_historical_race_band_sources.py":
                year = raw_options.get("year")
                if not isinstance(year, int) or isinstance(year, bool):
                    raise HistoricalBatchPipelineError(
                        "discovery recipe year must be an integer"
                    )
                discovery_scope: set[int] = set()
                for path in original_inputs["selection_snapshot"]:
                    _payload, discovery_targets = _load_selection(path)
                    discovery_scope.update(
                        target_id
                        for target_id, target in discovery_targets.items()
                        if target["year"] == year
                    )
                actual_scope = discovery_scope
            if tool_name == "prepare_historical_race_calendar_inputs.py":
                option_region = str(raw_options.get("country_region") or "")
                option_year = raw_options.get("year")
                if (
                    option_region != region
                    or not isinstance(option_year, int)
                    or isinstance(option_year, bool)
                ):
                    raise HistoricalBatchPipelineError(
                        "calendar parser recipe region/year does not match the shard"
                    )
                calendar_scope: set[int] = set()
                for path in original_inputs["selection_snapshot"]:
                    _payload, calendar_targets = _load_selection(path)
                    calendar_scope.update(
                        target_id
                        for target_id, target in calendar_targets.items()
                        if target["country_region"] == option_region
                        and target["year"] == option_year
                    )
                actual_scope = calendar_scope
            if "limit" in policy["options"] and "limit" in raw_options:
                limit = raw_options["limit"]
                if (
                    not isinstance(limit, int)
                    or isinstance(limit, bool)
                    or limit < 0
                    or (limit and limit < len(actual_scope))
                ):
                    raise HistoricalBatchPipelineError(
                        f"recipe limit would truncate the shard: {tool_name}"
                    )
            if tool_name == "prepare_france_zeturf_race_detail_candidates.py":
                try:
                    start_date = (
                        date.fromisoformat(str(raw_options["start_date"]))
                        if raw_options.get("start_date")
                        else None
                    )
                    end_date = (
                        date.fromisoformat(str(raw_options["end_date"]))
                        if raw_options.get("end_date")
                        else None
                    )
                except ValueError as exc:
                    raise HistoricalBatchPipelineError(
                        "France recipe date filter is invalid"
                    ) from exc
                if start_date and end_date and start_date > end_date:
                    raise HistoricalBatchPipelineError(
                        "France recipe date filter is reversed"
                    )
                if start_date or end_date:
                    event_dates = _event_local_dates(original_inputs["events_csv"])
                    filtered_scope = {
                        target_id
                        for target_id, local_date in event_dates.items()
                        if (start_date is None or local_date >= start_date)
                        and (end_date is None or local_date <= end_date)
                    }
                    actual_scope &= filtered_scope
            if actual_scope != shard_scope:
                raise HistoricalBatchPipelineError(
                    f"recipe actual target scope does not match shard {current_id}: "
                    f"missing={sorted(shard_scope - actual_scope)[:10]} "
                    f"unexpected={sorted(actual_scope - shard_scope)[:10]}"
                )
            if tool_name == "package_historical_race_detail_candidates.py":
                candidate_scope = _package_candidate_target_ids(
                    candidate_paths=original_inputs["candidate_jsonl"],
                    event_paths=original_inputs["events_csv"],
                )
                if not candidate_scope <= shard_scope:
                    raise HistoricalBatchPipelineError(
                        "package candidate scope exceeds the shard"
                    )
            if tool_name == "merge_historical_race_batch_fragments.py":
                fragment_scope = _target_ids_from_jsonl(
                    original_inputs["fragment"],
                    targets_by_identity=targets_by_identity,
                    allow_duplicate_targets=True,
                )
                gap_scope = _gap_fragment_target_ids(
                    original_inputs["gap"],
                    targets_by_identity=targets_by_identity,
                )
                if (
                    fragment_scope & gap_scope
                    or fragment_scope | gap_scope != shard_scope
                ):
                    raise HistoricalBatchPipelineError(
                        "merger fragment/gap scope does not exactly cover the shard"
                    )
            outputs = {
                key: _relative_output(raw_outputs[key], label=f"recipe output {key}")
                for key in policy["outputs"]
            }
            for path in outputs.values():
                claim = path.as_posix().rstrip("/")
                if any(
                    claim == existing
                    or claim.startswith(existing + "/")
                    or existing.startswith(claim + "/")
                    for existing in output_claims
                ):
                    raise HistoricalBatchPipelineError(f"recipe output paths overlap: {claim}")
                output_claims.add(claim)
            validated_recipes[current_id].append((recipe, original_inputs, outputs))
        if current_id == shard_id:
            selected_shard = shard
    if seen_targets != set(targets):
        raise HistoricalBatchPipelineError(
            f"descriptor shard coverage is incomplete: missing={sorted(set(targets) - seen_targets)[:10]}"
        )
    if selected_shard is None:
        raise HistoricalBatchPipelineError(f"requested shard does not exist: {shard_id}")
    if phase == "crawl" and "request_budget" in limits and limits["request_budget"] != selected_shard["request_budget"]:
        raise HistoricalBatchPipelineError("stage resource budget does not match selected shard")
    plan_limits = (
        {**limits, "request_budget": selected_shard["request_budget"]}
        if phase == "crawl"
        else None
    )

    output_dir = Path(output_dir)
    result: dict[str, Any] = {}

    def write_stage(temporary: Path) -> None:
        nonlocal result
        input_root = temporary / "inputs"
        input_root.mkdir(parents=True)
        used_names: set[str] = set()
        canonical_descriptor = deepcopy(descriptor)
        canonical_descriptor["shards"] = sorted(
            canonical_descriptor["shards"], key=lambda item: item["id"]
        )
        for shard in canonical_descriptor["shards"]:
            shard["target_ids"] = sorted(shard["target_ids"])
        canonical_descriptor_path = input_root / "stage-descriptor.json"
        canonical_descriptor_path.write_bytes(_canonical_bytes(canonical_descriptor))
        used_names.add(canonical_descriptor_path.name)
        copied_core = {
            "selection": _copy_input(selection_path, destination_root=input_root, used_names=used_names),
            "approval": _copy_input(approval_path, destination_root=input_root, used_names=used_names),
            "batch_manifest": _copy_input(manifest_path, destination_root=input_root, used_names=used_names),
            "descriptor": canonical_descriptor_path,
        }
        steps = []
        for index, (recipe, original_inputs, outputs) in enumerate(validated_recipes[shard_id], start=1):
            tool_name = recipe["tool"]
            policy = _RECIPE_POLICIES[tool_name]
            copied_inputs: dict[str, list[Path]] = {}
            declared_inputs = []
            declared_input_directories = []
            argv = ["python", str(tool_root / tool_name)]
            for key, (flag, cardinality) in policy["inputs"].items():
                copied_inputs[key] = []
                for source in original_inputs[key]:
                    if cardinality == "directory":
                        destination, directory_identities = _copy_input_directory(
                            source, destination_root=input_root, used_names=used_names
                        )
                        copied_inputs[key].append(destination)
                        argv.extend([flag, str(destination)])
                        declared_inputs.extend(directory_identities)
                        declared_input_directories.append({"path": str(destination)})
                        continue
                    destination = _copy_input(source, destination_root=input_root, used_names=used_names)
                    copied_inputs[key].append(destination)
                    argv.extend([flag, str(destination)])
                    declared_inputs.append(_identity(destination))
            output_paths = []
            output_directories = []
            for key, flag in policy["outputs"].items():
                output_path = temporary / outputs[key]
                argv.extend([flag, str(output_path)])
                declaration = {"path": str(output_path)}
                if key in policy.get("output_directories", set()):
                    output_directories.append(declaration)
                else:
                    output_paths.append(declaration)
            for key, value in sorted((recipe.get("options") or {}).items()):
                _append_option(argv, policy["options"][key], value)
            steps.append(
                {
                    "id": f"{index:02d}-{Path(tool_name).stem}",
                    "kind": "python_tool",
                    "argv": argv,
                    "inputs": declared_inputs,
                    "input_directories": declared_input_directories,
                    "outputs": output_paths,
                    "output_directories": output_directories,
                }
            )
        scope = {
            "schema_version": PIPELINE_SCHEMA_VERSION,
            "batch_id": descriptor["batch_id"],
            "stage_id": descriptor["stage_id"],
            "shard_id": shard_id,
            "country_region": selected_shard["country_region"],
            "target_ids": sorted(selected_shard["target_ids"]),
            "targets": [targets[target_id] for target_id in sorted(selected_shard["target_ids"])],
            "request_budget": selected_shard["request_budget"],
        }
        (temporary / "scope.json").write_bytes(_canonical_bytes(scope))
        plan = {
            "schema_version": "1.0",
            "batch_id": descriptor["batch_id"],
            "phase": phase,
            "network_enabled": phase == "crawl",
            "write_enabled": False,
            "image_id": descriptor["image_id"],
            "image_revision": descriptor["image_revision"],
            "artifact_root": str(temporary.resolve()),
            "tool_root": str(tool_root.resolve()),
            "tool_manifest": {name: tool_manifest[name] for name in sorted(tool_manifest)},
            "batch_identity": {
                key: _identity(path) for key, path in copied_core.items()
            },
            "selection_identity": {
                "sha256": selection_identity["sha256"],
                "approved_target_ids": sorted(selected_shard["target_ids"]),
            },
            "steps": steps,
        }
        if plan_limits is not None:
            plan["resource_limits"] = deepcopy(plan_limits)
        normalized_plan = validate_runner_plan(plan)
        contract = deepcopy(normalized_plan)
        root_text = str(temporary.resolve())

        def replace_root(value):
            if isinstance(value, str):
                return value.replace(root_text, "${ARTIFACT_ROOT}")
            if isinstance(value, list):
                return [replace_root(item) for item in value]
            if isinstance(value, dict):
                return {key: replace_root(item) for key, item in value.items()}
            return value

        plan_contract_sha = _sha256_bytes(_canonical_bytes(replace_root(contract)))
        final_root = str(output_dir.resolve())
        final_plan = replace_root(normalized_plan)

        def materialize_root(value):
            if isinstance(value, str):
                return value.replace("${ARTIFACT_ROOT}", final_root)
            if isinstance(value, list):
                return [materialize_root(item) for item in value]
            if isinstance(value, dict):
                return {key: materialize_root(item) for key, item in value.items()}
            return value

        final_plan = materialize_root(final_plan)
        (temporary / "runner-plan.json").write_bytes(_canonical_bytes(final_plan))
        summary = {
            "schema_version": PIPELINE_SCHEMA_VERSION,
            "batch_id": descriptor["batch_id"],
            "stage_id": descriptor["stage_id"],
            "shard_id": shard_id,
            "phase": phase,
            "target_count": len(selected_shard["target_ids"]),
            "request_budget": selected_shard["request_budget"],
            "selection_sha256": selection_identity["sha256"],
            "approval_sha256": approval_identity["sha256"],
            "batch_manifest_sha256": manifest_identity["sha256"],
            "plan_contract_sha256": plan_contract_sha,
        }
        (temporary / "summary.json").write_bytes(_canonical_bytes(summary))
        manifest = {
            "schema_version": PIPELINE_SCHEMA_VERSION,
            "scope": {"path": "scope.json", "sha256": _sha256_file(temporary / "scope.json")},
            "plan": {"path": "runner-plan.json", "sha256": _sha256_file(temporary / "runner-plan.json")},
            "summary": {"path": "summary.json", "sha256": _sha256_file(temporary / "summary.json")},
            "core_inputs": {
                key: {"path": path.relative_to(temporary).as_posix(), "sha256": _sha256_file(path)}
                for key, path in copied_core.items()
            },
        }
        (temporary / "manifest.json").write_bytes(_canonical_bytes(manifest))
        result = {
            **summary,
            "scope_sha256": manifest["scope"]["sha256"],
            "plan_sha256": manifest["plan"]["sha256"],
            "manifest_sha256": _sha256_file(temporary / "manifest.json"),
            "output_dir": str(output_dir),
        }

    _atomic_publish_directory(output_dir, write_stage)
    try:
        final_plan_path = output_dir / "runner-plan.json"
        validate_runner_plan(json.loads(final_plan_path.read_text(encoding="utf-8")))
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise
    return result


def _https_url(value: Any) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme == "https" and bool(parsed.netloc)


def _target_for_row(
    row: dict[str, Any],
    *,
    targets: dict[int, dict[str, Any]],
    identities: dict[tuple[str, int], int],
    allow_missing_hashes: bool = False,
) -> tuple[int, dict[str, Any]]:
    try:
        if row.get("target_id") not in (None, ""):
            target_id = _strict_json_integer(
                row["target_id"], label="fragment target_id"
            )
        else:
            edition_year = _strict_json_integer(
                row["edition_year"], label="fragment edition_year"
            )
            target_id = identities[(str(row["series_key"]), edition_year)]
        target = targets[target_id]
    except (KeyError, HistoricalBatchPipelineError) as exc:
        raise HistoricalBatchPipelineError("fragment target is outside selection") from exc
    if row.get("series_key") not in (None, "") or row.get("edition_year") not in (None, ""):
        try:
            edition_year = _strict_json_integer(
                row["edition_year"], label="fragment edition_year"
            )
            identity_target_id = identities[(str(row["series_key"]), edition_year)]
        except (KeyError, HistoricalBatchPipelineError) as exc:
            raise HistoricalBatchPipelineError(
                "fragment series/year identity is outside selection"
            ) from exc
        if identity_target_id != target_id:
            raise HistoricalBatchPipelineError("fragment target identities conflict")
    row_target_sha = str(row.get("target_sha256") or "")
    row_inventory_sha = str(row.get("inventory_artifact_sha256") or "")
    if (row_target_sha or not allow_missing_hashes) and row_target_sha != target["target_sha256"]:
        raise HistoricalBatchPipelineError(f"fragment target SHA mismatch: {target_id}")
    if (
        row_inventory_sha or not allow_missing_hashes
    ) and row_inventory_sha != target["inventory_artifact_sha256"]:
        raise HistoricalBatchPipelineError(f"fragment inventory SHA mismatch: {target_id}")
    return target_id, target


def _normalized_date_row(row: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(row)
    try:
        local_date = str(value["local_date"])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", local_date):
            raise ValueError
        date.fromisoformat(local_date)
    except (KeyError, ValueError):
        raise HistoricalBatchPipelineError("date fragment local_date is invalid")
    urls = value.get("urls")
    result_url = ((urls or {}).get("result_url") or {}).get("url") if isinstance(urls, dict) else None
    if not _https_url(result_url):
        raise HistoricalBatchPipelineError("date fragment result URL must use HTTPS")
    value["target_id"] = target["target_id"]
    value["target_sha256"] = target["target_sha256"]
    value["inventory_artifact_sha256"] = target["inventory_artifact_sha256"]
    value["series_key"] = target["series_key"]
    value["edition_year"] = target["year"]
    return value


def _module_items(module: Any, *, identity_key: str) -> list[dict[str, Any]]:
    if not isinstance(module, dict) or module.get("is_complete") is not True:
        raise HistoricalBatchPipelineError(f"detail module is incomplete: {identity_key}")
    items = module.get("items")
    if not isinstance(items, list) or not items or any(not isinstance(item, dict) for item in items):
        raise HistoricalBatchPipelineError(f"detail module has no valid items: {identity_key}")
    identities = []
    for item in items:
        if not str(item.get("horse_name") or "").strip():
            raise HistoricalBatchPipelineError("detail item has no horse_name")
        value = item.get(identity_key)
        if identity_key == "horse_number" and value in (None, ""):
            continue
        if identity_key == "finish_position" and value in (None, ""):
            status = str(item.get("running_status") or "")
            if status in {"scratched", "withdrawn", "did_not_finish", "disqualified"}:
                continue
        if value in (None, ""):
            raise HistoricalBatchPipelineError(f"detail item has no {identity_key}")
        identities.append(str(value))
    if len(identities) != len(set(identities)):
        raise HistoricalBatchPipelineError(f"detail module duplicates {identity_key}")
    return items


def _normalized_detail_row(row: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(row)
    if not _https_url(value.get("source_url")):
        raise HistoricalBatchPipelineError("detail source URL must use HTTPS")
    modules = value.get("modules")
    if not isinstance(modules, dict) or set(modules) != {"runners", "results"}:
        raise HistoricalBatchPipelineError("detail candidate modules are incomplete")
    _module_items(modules["runners"], identity_key="horse_number")
    _module_items(modules["results"], identity_key="finish_position")
    for module_name in ("runners", "results"):
        cache_identity = modules[module_name].get("source_cache_identity")
        if (
            not isinstance(cache_identity, dict)
            or cache_identity.get("source_url") != value["source_url"]
            or not _SHA256_RE.fullmatch(str(cache_identity.get("sha256") or ""))
            or not isinstance(cache_identity.get("size"), int)
            or isinstance(cache_identity.get("size"), bool)
            or cache_identity["size"] < 0
        ):
            raise HistoricalBatchPipelineError("detail source cache identity is invalid")
    value["target_id"] = target["target_id"]
    value["target_sha256"] = target["target_sha256"]
    value["inventory_artifact_sha256"] = target["inventory_artifact_sha256"]
    return value


def _verified_source_cache(
    manifest_paths: list[Path],
) -> dict[str, dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for manifest_path in manifest_paths:
        manifest, _raw = _read_json(manifest_path, label="source cache manifest")
        files = manifest.get("files")
        if manifest.get("schema_version") != "1.0" or not isinstance(files, dict):
            raise HistoricalBatchPipelineError("source cache manifest schema is invalid")
        root = manifest_path.parent.resolve()
        for identity in files.values():
            if not isinstance(identity, dict):
                raise HistoricalBatchPipelineError("source cache file identity is invalid")
            relative = Path(str(identity.get("path") or ""))
            source_url = str(identity.get("source_url") or "")
            expected_sha = str(identity.get("sha256") or "")
            expected_size = identity.get("size")
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not _https_url(source_url)
                or not _SHA256_RE.fullmatch(expected_sha)
                or not isinstance(expected_size, int)
                or isinstance(expected_size, bool)
                or expected_size < 0
            ):
                raise HistoricalBatchPipelineError("source cache file identity is invalid")
            source_candidate = root / relative
            current = root
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    raise HistoricalBatchPipelineError(
                        f"source cache file uses a symlink: {source_url}"
                    )
            source = source_candidate.resolve()
            try:
                source.relative_to(root)
            except ValueError as exc:
                raise HistoricalBatchPipelineError("source cache file escapes manifest root") from exc
            actual = _identity(source)
            if actual["sha256"] != expected_sha or actual["size"] != expected_size:
                raise HistoricalBatchPipelineError(f"source cache file identity drifted: {source_url}")
            normalized = {
                "source_url": source_url,
                "path": relative.as_posix(),
                "size": expected_size,
                "sha256": expected_sha,
            }
            previous = by_url.get(source_url)
            if previous is not None and previous != normalized:
                raise HistoricalBatchPipelineError(f"source cache URL has conflicting identities: {source_url}")
            by_url[source_url] = normalized
    return by_url


def _validated_gap(row: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(row)
    evidence = value.get("evidence_identity")
    evidence_path = Path(str((evidence or {}).get("path") or ""))
    if (
        str(value.get("target_sha256") or "") != target["target_sha256"]
        or not str(value.get("reason_code") or "").strip()
        or not _valid_iso_timestamp(value.get("recorded_at"))
        or not isinstance(evidence, dict)
        or not _SHA256_RE.fullmatch(str(evidence.get("sha256") or ""))
        or evidence_path == Path(".")
        or evidence_path.is_absolute()
        or ".." in evidence_path.parts
        or (value.get("source_url") and not _https_url(value["source_url"]))
    ):
        raise HistoricalBatchPipelineError("gap fragment has incomplete evidence identity")
    value["target_id"] = target["target_id"]
    return value


def _apply_evidence(row: dict[str, Any], evidence_rows: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any]:
    original = deepcopy(row)
    result = deepcopy(row)
    applied: list[dict[str, Any]] = []
    seen_fields: dict[str, Any] = {}
    for evidence in sorted(evidence_rows, key=lambda item: _canonical_bytes(item)):
        required = (
            "target_sha256",
            "field",
            "expected_old_value",
            "new_value",
            "source_url",
            "source_authority",
            "reason",
            "reviewed_by",
            "reviewed_at",
        )
        if any(key not in evidence or evidence[key] in (None, "") for key in required):
            raise HistoricalBatchPipelineError("manual evidence is incomplete")
        if evidence["target_sha256"] != target["target_sha256"]:
            raise HistoricalBatchEvidenceConflict(
                "manual evidence target identity drifted"
            )
        if not _https_url(evidence["source_url"]) or not _valid_iso_timestamp(
            evidence["reviewed_at"]
        ):
            raise HistoricalBatchPipelineError(
                "manual evidence source identity is invalid"
            )
        field = str(evidence["field"])
        if field in {
            "target_id",
            "target_sha256",
            "inventory_artifact_sha256",
            "series_key",
            "edition_year",
        }:
            raise HistoricalBatchPipelineError(
                f"manual evidence cannot change protected identity: {field}"
            )
        if field not in original or original[field] != evidence["expected_old_value"]:
            raise HistoricalBatchEvidenceConflict(
                f"manual evidence expected old value drifted: {field}"
            )
        if field in seen_fields and seen_fields[field] != evidence["new_value"]:
            raise HistoricalBatchEvidenceConflict(
                f"manual evidence conflicts for field: {field}"
            )
        seen_fields[field] = evidence["new_value"]
        result[field] = evidence["new_value"]
        applied.append(evidence)
    if applied:
        result["manual_evidence"] = applied
    return result


def merge_historical_race_fragments(
    *,
    mode: str,
    selection_path: str | Path,
    fragment_paths: Iterable[str | Path],
    gap_paths: Iterable[str | Path],
    evidence_paths: Iterable[str | Path],
    output_dir: str | Path,
    source_cache_manifest_paths: Iterable[str | Path] = (),
    recorded_at: str = "",
) -> dict[str, Any]:
    if mode not in {"date", "detail"}:
        raise HistoricalBatchPipelineError("merge mode must be date or detail")
    if recorded_at and not _valid_iso_timestamp(recorded_at):
        raise HistoricalBatchPipelineError("merge recorded_at must be an ISO-8601 timestamp")
    selection_path = Path(selection_path)
    selection_identity = _identity(selection_path)
    _selection, targets = _load_selection(selection_path)
    identities = {(target["series_key"], target["year"]): target_id for target_id, target in targets.items()}
    fragment_paths = [Path(path) for path in fragment_paths]
    gap_paths = [Path(path) for path in gap_paths]
    evidence_paths = [Path(path) for path in evidence_paths]
    source_cache_manifest_paths = [Path(path) for path in source_cache_manifest_paths]
    fragments = _read_jsonl(fragment_paths, label="fragment")
    gaps = _read_gap_fragments(gap_paths)
    evidence = _read_jsonl(evidence_paths, label="manual evidence")
    verified_cache = _verified_source_cache(source_cache_manifest_paths)
    if mode == "detail" and not verified_cache:
        raise HistoricalBatchPipelineError("detail merge requires verified source cache manifests")
    evidence_by_target: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row, _identity_row in evidence:
        try:
            target_id = _strict_json_integer(
                row["target_id"], label="manual evidence target_id"
            )
            targets[target_id]
        except (KeyError, HistoricalBatchPipelineError) as exc:
            raise HistoricalBatchPipelineError("manual evidence target is outside selection") from exc
        evidence_by_target[target_id].append(row)

    valid_rows: dict[int, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    invalid_gaps: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row, source_identity in fragments:
        target_id, target = _target_for_row(
            row,
            targets=targets,
            identities=identities,
            allow_missing_hashes=mode == "date",
        )
        try:
            normalized = (
                _normalized_date_row(row, target)
                if mode == "date"
                else _normalized_detail_row(row, target)
            )
            if mode == "detail":
                expected_cache = verified_cache.get(str(normalized.get("source_url") or ""))
                if expected_cache is None:
                    raise HistoricalBatchPipelineError(
                        "detail source URL is absent from source cache manifests"
                    )
                for module_name in ("runners", "results"):
                    module_identity = normalized["modules"][module_name]["source_cache_identity"]
                    if any(
                        module_identity.get(field) != expected_cache[field]
                        for field in ("source_url", "size", "sha256")
                    ):
                        raise HistoricalBatchPipelineError(
                            "detail module cache identity differs from verified manifest"
                        )
        except HistoricalBatchPipelineError as exc:
            if not recorded_at:
                raise HistoricalBatchPipelineError(
                    "invalid fragment requires a bound merge recorded_at"
                ) from exc
            invalid_gaps[target_id].append(
                {
                    "target_id": target_id,
                    "target_sha256": target["target_sha256"],
                    "reason_code": "invalid_fragment",
                    "error": str(exc),
                    "evidence_identity": source_identity,
                    "recorded_at": recorded_at,
                }
            )
            continue
        valid_rows[target_id].append((normalized, source_identity))

    explicit_gaps: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row, source_identity in gaps:
        try:
            if row.get("target_id") not in (None, ""):
                target_id = _strict_json_integer(
                    row["target_id"], label="gap target_id"
                )
            else:
                edition_year = _strict_json_integer(
                    row["edition_year"], label="gap edition_year"
                )
                target_id = identities[(str(row["series_key"]), edition_year)]
            target = targets[target_id]
        except (KeyError, HistoricalBatchPipelineError) as exc:
            raise HistoricalBatchPipelineError("gap target is outside selection") from exc
        if row.get("series_key") not in (None, "") or row.get("edition_year") not in (None, ""):
            try:
                edition_year = _strict_json_integer(
                    row["edition_year"], label="gap edition_year"
                )
                identity_target_id = identities[(str(row["series_key"]), edition_year)]
            except (KeyError, HistoricalBatchPipelineError) as exc:
                raise HistoricalBatchPipelineError(
                    "gap series/year identity is outside selection"
                ) from exc
            if identity_target_id != target_id:
                raise HistoricalBatchPipelineError("gap target identities conflict")
        normalized_gap = deepcopy(row)
        normalized_gap["target_id"] = target_id
        normalized_gap.setdefault("target_sha256", target["target_sha256"])
        if not normalized_gap.get("reason_code"):
            normalized_gap["reason_code"] = normalized_gap.get("reason") or normalized_gap.get("code")
        if not normalized_gap.get("recorded_at"):
            if not recorded_at:
                raise HistoricalBatchPipelineError(
                    "legacy gap fragment requires a bound merge recorded_at"
                )
            normalized_gap["recorded_at"] = recorded_at
        normalized_gap["evidence_identity"] = source_identity
        explicit_gaps[target_id].append(_validated_gap(normalized_gap, target))

    complete_rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []
    conflict_count = 0
    duplicate_count = 0
    for target_id in sorted(targets):
        target = targets[target_id]
        candidates = valid_rows.get(target_id, [])
        canonical_groups: dict[bytes, list[dict[str, Any]]] = defaultdict(list)
        canonical_rows: dict[bytes, dict[str, Any]] = {}
        for candidate, source_identity in candidates:
            key = _canonical_bytes(candidate)
            canonical_rows[key] = candidate
            canonical_groups[key].append(source_identity)
        if len(canonical_groups) == 1:
            candidate_key = next(iter(canonical_groups))
            candidate = canonical_rows[candidate_key]
            duplicate_count += max(0, len(canonical_groups[candidate_key]) - 1)
            if explicit_gaps.get(target_id) or invalid_gaps.get(target_id):
                raise HistoricalBatchPipelineError(f"target appears in both complete and gap: {target_id}")
            try:
                candidate = _apply_evidence(
                    candidate,
                    evidence_by_target.get(target_id, []),
                    target,
                )
            except HistoricalBatchEvidenceConflict as exc:
                if not recorded_at:
                    raise HistoricalBatchPipelineError(
                        "conflicting manual evidence requires a bound merge recorded_at"
                    ) from exc
                conflict_count += 1
                gap_rows.append(
                    {
                        "target_id": target_id,
                        "target_sha256": target["target_sha256"],
                        "reason_code": "conflicting_manual_evidence",
                        "error": str(exc),
                        "evidence": evidence_by_target[target_id],
                        "recorded_at": recorded_at,
                    }
                )
                continue
            candidate = (
                _normalized_date_row(candidate, target)
                if mode == "date"
                else _normalized_detail_row(candidate, target)
            )
            if mode == "detail":
                expected_cache = verified_cache.get(str(candidate.get("source_url") or ""))
                if expected_cache is None:
                    raise HistoricalBatchPipelineError(
                        "manual evidence detail source URL is absent from source cache manifests"
                    )
                for module_name in ("runners", "results"):
                    module_identity = candidate["modules"][module_name]["source_cache_identity"]
                    if any(
                        module_identity.get(field) != expected_cache[field]
                        for field in ("source_url", "size", "sha256")
                    ):
                        raise HistoricalBatchPipelineError(
                            "manual evidence detail cache identity differs from verified manifest"
                        )
            complete_rows.append(candidate)
            continue
        if len(canonical_groups) > 1:
            if not recorded_at:
                raise HistoricalBatchPipelineError(
                    "conflicting fragments require a bound merge recorded_at"
                )
            conflict_count += 1
            conflict_evidence = [
                {
                    "candidate_sha256": _sha256_bytes(candidate_key),
                    "inputs": source_identities,
                }
                for candidate_key, source_identities in sorted(canonical_groups.items())
            ]
            gap_rows.append(
                {
                    "target_id": target_id,
                    "target_sha256": target["target_sha256"],
                    "reason_code": "conflicting_fragments",
                    "conflicting_evidence": conflict_evidence,
                    "recorded_at": recorded_at,
                }
            )
            continue
        all_gaps = explicit_gaps.get(target_id, []) + invalid_gaps.get(target_id, [])
        if not all_gaps:
            raise HistoricalBatchPipelineError(f"target has no complete row or evidenced gap: {target_id}")
        if evidence_by_target.get(target_id):
            raise HistoricalBatchPipelineError(f"manual evidence has no complete row to amend: {target_id}")
        reasons = {_canonical_bytes(row): row for row in all_gaps}
        if len(reasons) == 1:
            gap_rows.append(next(iter(reasons.values())))
        else:
            gap_rows.append(
                {
                    "target_id": target_id,
                    "target_sha256": target["target_sha256"],
                    "reason_code": "multiple_gap_evidence",
                    "gap_evidence": list(reasons.values()),
                    "recorded_at": recorded_at or all_gaps[0]["recorded_at"],
                }
            )

    complete_ids = {row["target_id"] for row in complete_rows}
    gap_ids = {row["target_id"] for row in gap_rows}
    if complete_ids & gap_ids or complete_ids | gap_ids != set(targets):
        raise HistoricalBatchPipelineError("complete and gap coverage does not equal selection scope")
    output_dir = Path(output_dir)
    result: dict[str, Any] = {}

    def write_merge(temporary: Path) -> None:
        nonlocal result
        selection_copy = temporary / "selection.json"
        shutil.copyfile(selection_path, selection_copy)
        if _sha256_file(selection_copy) != selection_identity["sha256"]:
            raise HistoricalBatchPipelineError("selection copy SHA mismatch")
        complete_path = temporary / "complete.jsonl"
        gaps_path = temporary / "gaps.jsonl"
        complete_path.write_bytes(b"".join(_canonical_bytes(row) for row in complete_rows))
        gaps_path.write_bytes(b"".join(_canonical_bytes(row) for row in gap_rows))
        scope_count = len(targets)
        summary = {
            "schema_version": MERGE_SCHEMA_VERSION,
            "mode": mode,
            "scope_count": scope_count,
            "complete_count": len(complete_rows),
            "gap_count": len(gap_rows),
            "conflict_count": conflict_count,
            "duplicate_evidence_count": duplicate_count,
            "accounted_count": len(complete_rows) + len(gap_rows),
            "accounted_rate": 1.0,
            "data_complete_rate": len(complete_rows) / scope_count,
            "recorded_at": recorded_at,
        }
        summary_path = temporary / "summary.json"
        summary_path.write_bytes(_canonical_bytes(summary))
        manifest = {
            "schema_version": MERGE_SCHEMA_VERSION,
            "selection": {"path": selection_copy.name, "sha256": selection_identity["sha256"]},
            "complete": {"path": complete_path.name, "sha256": _sha256_file(complete_path)},
            "gaps": {"path": gaps_path.name, "sha256": _sha256_file(gaps_path)},
            "summary": {"path": summary_path.name, "sha256": _sha256_file(summary_path)},
            "inputs": sorted(
                [
                    {"kind": kind, "sha256": _identity(Path(path))["sha256"], "size": _identity(Path(path))["size"]}
                    for kind, paths in (
                        ("fragment", fragment_paths),
                        ("gap", gap_paths),
                        ("evidence", evidence_paths),
                        ("source_cache_manifest", source_cache_manifest_paths),
                    )
                    for path in paths
                ],
                key=lambda row: (row["kind"], row["sha256"]),
            ),
        }
        manifest_path = temporary / "manifest.json"
        manifest_path.write_bytes(_canonical_bytes(manifest))
        result = {
            **summary,
            "complete_sha256": manifest["complete"]["sha256"],
            "gap_sha256": manifest["gaps"]["sha256"],
            "manifest_sha256": _sha256_file(manifest_path),
            "output_dir": str(output_dir),
        }

    _atomic_publish_directory(output_dir, write_merge)
    return result

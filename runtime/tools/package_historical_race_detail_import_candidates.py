#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable
from urllib.parse import urlparse


ARTIFACT_KIND = "historical_race_detail_source_bundle"
SCHEMA_VERSION = "2.0"
PACKAGE_KIND = "historical_race_detail_package"
FRAGMENT_KIND = "historical_race_detail_source_fragment"
V6_KIND = "canonical_immutable_detail_crawl_plan_manifest"
DUE_KIND = "current_year_due_classification_aggregate"
HISTORICAL_LAYER = "historical_through_2024"
CURRENT_YEAR_LAYER = "current_year_due"
REGIONS = (
    "japan",
    "hong_kong",
    "united_kingdom",
    "france",
    "united_states",
)


class SourceBundlePackagingError(ValueError):
    pass


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _canonical_jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(_canonical_json_bytes(row) for row in rows)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_identity(path: Path, rendered_path: str) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": rendered_path, "sha256": _sha256(raw), "size": len(raw)}


def _output_identity(path: str, raw: bytes) -> dict[str, Any]:
    return {"path": path, "sha256": _sha256(raw), "size": len(raw)}


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceBundlePackagingError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceBundlePackagingError(f"{label} must be a JSON object: {path}")
    return payload, raw


def _load_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise SourceBundlePackagingError(
                        f"{label} line {line_number} must be an object: {path}"
                    )
                rows.append(row)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceBundlePackagingError(f"cannot read {label} {path}: {exc}") from exc
    return rows


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_evidence_path(
    raw_path: object,
    *,
    base: Path,
    allowed_roots: tuple[Path, ...],
    label: str,
) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise SourceBundlePackagingError(f"{label} path must be a non-empty string")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    lexical = Path(os.path.abspath(candidate))
    normalized_candidate = lexical.parent.resolve(strict=False) / lexical.name
    if not any(_is_within(normalized_candidate, root) for root in allowed_roots):
        raise SourceBundlePackagingError(f"{label} path escapes allowed roots: {raw_path}")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise SourceBundlePackagingError(f"{label} path does not exist: {lexical}") from exc
    containing_roots = [root for root in allowed_roots if _is_within(resolved, root)]
    if not containing_roots:
        raise SourceBundlePackagingError(f"{label} path escapes allowed roots: {raw_path}")
    containing_root = max(containing_roots, key=lambda root: len(root.parts))
    for component in (lexical, *lexical.parents):
        if not component.is_symlink():
            continue
        try:
            symlink_target = component.resolve(strict=True)
        except OSError as exc:
            raise SourceBundlePackagingError(
                f"{label} contains an invalid symlink: {component}"
            ) from exc
        if _is_within(symlink_target, containing_root):
            raise SourceBundlePackagingError(
                f"{label} must not use a symlink: {component}"
            )
    if not resolved.is_file():
        raise SourceBundlePackagingError(f"{label} is not a file: {resolved}")
    return resolved


def _compact_path(path: Path, roots: dict[str, Path]) -> dict[str, str]:
    matches = [
        (name, root)
        for name, root in roots.items()
        if _is_within(path, root)
    ]
    if not matches:
        raise SourceBundlePackagingError(f"cannot render path outside known roots: {path}")
    name, root = max(matches, key=lambda item: len(item[1].parts))
    return {"root": name, "path": path.relative_to(root).as_posix()}


def _verify_identity(
    identity: object,
    *,
    base: Path,
    allowed_roots: tuple[Path, ...],
    named_roots: dict[str, Path],
    label: str,
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(identity, dict):
        raise SourceBundlePackagingError(f"{label} identity must be an object")
    path = _resolve_evidence_path(
        identity.get("path"), base=base, allowed_roots=allowed_roots, label=label
    )
    raw = path.read_bytes()
    actual_sha = _sha256(raw)
    actual_size = len(raw)
    if identity.get("sha256") != actual_sha or identity.get("size") != actual_size:
        raise SourceBundlePackagingError(f"{label} identity mismatch: {path}")
    compact = {
        **_compact_path(path, named_roots),
        "sha256": actual_sha,
        "size": actual_size,
    }
    if isinstance(identity.get("source_url"), str) and identity["source_url"]:
        compact["source_url"] = identity["source_url"]
    return path, compact


def _iter_manifest_identities(payload: object) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        if {"path", "sha256", "size"}.issubset(payload):
            yield payload
            return
        for value in payload.values():
            yield from _iter_manifest_identities(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _iter_manifest_identities(value)


def _artifact_rows(payload: dict[str, Any], label: str) -> list[dict[str, Any]]:
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, list):
        rows = artifacts
    elif isinstance(artifacts, dict):
        rows = list(artifacts.values())
    else:
        raise SourceBundlePackagingError(f"{label} artifacts must be an array or object")
    if not all(isinstance(row, dict) for row in rows):
        raise SourceBundlePackagingError(f"{label} artifact rows must be objects")
    return rows


def _verify_top_manifest_artifacts(
    manifest: dict[str, Any],
    *,
    root: Path,
    allowed_roots: tuple[Path, ...],
    named_roots: dict[str, Path],
    label: str,
) -> dict[str, dict[str, Any]]:
    rows = _artifact_rows(manifest, label)
    artifact_count = manifest.get("artifact_count")
    if artifact_count != len(rows):
        raise SourceBundlePackagingError(
            f"{label} artifact_count {artifact_count!r} does not match {len(rows)} artifacts"
        )
    verified: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        path, compact = _verify_identity(
            row,
            base=root,
            allowed_roots=allowed_roots,
            named_roots=named_roots,
            label=f"{label} artifact[{index}]",
        )
        relative = path.relative_to(root).as_posix()
        if relative in verified:
            raise SourceBundlePackagingError(f"duplicate {label} artifact path: {relative}")
        verified[relative] = compact
    return verified


def _target_id(row: object, label: str) -> int:
    if not isinstance(row, dict):
        raise SourceBundlePackagingError(f"{label} row must be an object")
    value = row.get("target_id")
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SourceBundlePackagingError(f"{label} target_id must be a positive integer")
    return value


def _year(value: object, label: str) -> int:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1900:
        raise SourceBundlePackagingError(f"{label} year is invalid: {value!r}")
    return value


def _strict_count(payload: dict[str, Any], key: str, label: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SourceBundlePackagingError(f"{label} {key} must be a non-negative integer")
    return value


def _region_for_shard(shard_id: str) -> str:
    for region in sorted(REGIONS, key=len, reverse=True):
        if shard_id == region or shard_id.startswith(f"{region}-"):
            return region
    raise SourceBundlePackagingError(f"shard does not identify a supported region: {shard_id}")


def _parse_source_refs(value: object, label: str) -> dict[str, Any]:
    if isinstance(value, dict):
        payload = value
    elif isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SourceBundlePackagingError(f"{label} source_refs is invalid JSON") from exc
    else:
        raise SourceBundlePackagingError(f"{label} source_refs must be an object or JSON string")
    if not isinstance(payload, dict):
        raise SourceBundlePackagingError(f"{label} source_refs must decode to an object")
    return payload


def _calendar_source(source_refs: dict[str, Any]) -> tuple[str, str]:
    calendar = source_refs.get("calendar_discovery")
    if not isinstance(calendar, dict):
        return "", ""
    url = calendar.get("calendar_source_url") or calendar.get("source_url")
    provider = calendar.get("calendar_source_provider") or calendar.get("source_provider")
    return (url if isinstance(url, str) else "", provider if isinstance(provider, str) else "")


def _collect_cache_identities(value: object) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "source_cache_identity" and isinstance(child, dict):
                collected.append(child)
            else:
                collected.extend(_collect_cache_identities(child))
    elif isinstance(value, list):
        for child in value:
            collected.extend(_collect_cache_identities(child))
    return collected


def _module_count(record: dict[str, Any], module_name: str, label: str) -> int:
    modules = record.get("modules")
    module = modules.get(module_name) if isinstance(modules, dict) else None
    items = module.get("items") if isinstance(module, dict) else None
    if not isinstance(items, list):
        raise SourceBundlePackagingError(f"{label} modules.{module_name}.items must be an array")
    return len(items)


def _results_complete(record: dict[str, Any]) -> bool:
    modules = record.get("modules")
    results = modules.get("results") if isinstance(modules, dict) else None
    return bool(
        isinstance(results, dict)
        and results.get("is_complete") is True
        and isinstance(results.get("items"), list)
        and results["items"]
    )


def _load_staged_rows(path: Path) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                target_id = _target_id(row, f"staged-events {path}")
                if target_id in rows:
                    raise SourceBundlePackagingError(
                        f"duplicate staged-events target_id {target_id}: {path}"
                    )
                rows[target_id] = row
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise SourceBundlePackagingError(f"cannot read staged-events {path}: {exc}") from exc
    return rows


def _layer_for_year(year: int) -> str:
    return HISTORICAL_LAYER if year <= 2024 else CURRENT_YEAR_LAYER


def _load_request_logs(
    v6_root: Path,
    top_artifacts: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_url: dict[str, list[dict[str, Any]]] = {}
    identities: dict[str, dict[str, Any]] = {}
    for relative, compact in top_artifacts.items():
        if not relative.endswith(".requests.jsonl"):
            continue
        path = v6_root / relative
        identities[relative] = compact
        for row in _load_jsonl(path, f"request log {relative}"):
            url = row.get("url")
            if isinstance(url, str) and url:
                by_url.setdefault(url, []).append(
                    {
                        "identity": compact,
                        "shard_id": row.get("shard_id"),
                        "host": row.get("host"),
                    }
                )
    return by_url, identities


def _verify_cache_manifest(
    path: Path,
    *,
    allowed_roots: tuple[Path, ...],
    named_roots: dict[str, Path],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    payload, _ = _load_json(path, "source cache manifest")
    files = payload.get("files")
    if not isinstance(files, dict):
        raise SourceBundlePackagingError(f"source cache manifest files must be an object: {path}")
    verified: dict[str, dict[str, Any]] = {}
    compact_by_name: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for filename, identity in sorted(files.items()):
        if not isinstance(filename, str) or not isinstance(identity, dict):
            raise SourceBundlePackagingError(f"invalid source cache entry in {path}")
        if identity.get("path") != filename:
            raise SourceBundlePackagingError(f"source cache key/path mismatch in {path}: {filename}")
        if not isinstance(identity.get("cached_at"), str) or not isinstance(
            identity.get("protected_by"), list
        ):
            raise SourceBundlePackagingError(
                f"source cache entry lacks cached_at/protected_by in {path}: {filename}"
            )
        cache_path, compact = _verify_identity(
            identity,
            base=path.parent,
            allowed_roots=allowed_roots,
            named_roots=named_roots,
            label=f"source cache {filename}",
        )
        if cache_path.parent != path.parent:
            raise SourceBundlePackagingError(f"source cache path escapes cache directory: {cache_path}")
        total_bytes += compact["size"]
        verified[filename] = identity
        compact_by_name[filename] = compact
        for key in ("cached_at", "protected_by"):
            if key in identity:
                compact[key] = identity[key]
    if payload.get("total_bytes") != total_bytes:
        raise SourceBundlePackagingError(f"source cache total_bytes mismatch: {path}")
    return verified, compact_by_name


def _bind_record_caches(
    record: dict[str, Any],
    *,
    cache_entries: dict[str, dict[str, Any]],
    compact_entries: dict[str, dict[str, Any]],
    label: str,
) -> list[dict[str, Any]]:
    references = _collect_cache_identities(record.get("modules"))
    if not references:
        raise SourceBundlePackagingError(f"{label} has no source_cache_identity")
    bound: dict[tuple[str, str], dict[str, Any]] = {}
    for identity in references:
        filename = identity.get("path")
        if not isinstance(filename, str) or filename not in cache_entries:
            raise SourceBundlePackagingError(f"{label} references unknown source cache: {filename}")
        manifest_identity = cache_entries[filename]
        for key in ("sha256", "size", "source_url"):
            if identity.get(key) != manifest_identity.get(key):
                raise SourceBundlePackagingError(
                    f"{label} source cache identity mismatch for {filename}: {key}"
                )
        compact = compact_entries[filename]
        bound[(compact["sha256"], compact.get("source_url", ""))] = compact
    return [bound[key] for key in sorted(bound)]


DATE_FIELD_NAMES = {"date", "event_date", "local_date", "race_date"}
DATE_IN_PATH_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")


def _collect_named_dates(value: object) -> set[str]:
    dates: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in DATE_FIELD_NAMES and isinstance(child, str):
                try:
                    date.fromisoformat(child)
                except ValueError:
                    pass
                else:
                    dates.add(child)
            dates.update(_collect_named_dates(child))
    elif isinstance(value, list):
        for child in value:
            dates.update(_collect_named_dates(child))
    return dates


def _row_target_id(row: object) -> int | None:
    if not isinstance(row, dict):
        return None
    value = row.get("target_id")
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _build_recovery_date_index(path: Path) -> dict[int, set[str]]:
    rows: list[dict[str, Any]] = []
    try:
        if path.suffix.lower() in {".csv", ".tsv"}:
            delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows.extend(csv.DictReader(handle, delimiter=delimiter))
        elif path.suffix.lower() == ".jsonl":
            rows.extend(_load_jsonl(path, "recovery candidate evidence"))
        elif path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                rows.extend(row for row in payload if isinstance(row, dict))
            elif isinstance(payload, dict):
                candidate_rows = payload.get("records") or payload.get("candidates")
                if isinstance(candidate_rows, list):
                    rows.extend(row for row in candidate_rows if isinstance(row, dict))
                else:
                    rows.append(payload)
    except (OSError, UnicodeDecodeError, csv.Error, json.JSONDecodeError) as exc:
        raise SourceBundlePackagingError(
            f"cannot inspect recovery date evidence {path}: {exc}"
        ) from exc
    indexed: dict[int, set[str]] = {}
    for row in rows:
        target_id = _row_target_id(row)
        if target_id is None:
            continue
        indexed.setdefault(target_id, set()).update(_collect_named_dates(row))
    return indexed


def _verify_external_recovery_evidence(
    rows: object,
    *,
    target_id: int,
    date_index_cache: dict[Path, dict[int, set[str]]],
    base: Path,
    allowed_roots: tuple[Path, ...],
    named_roots: dict[str, Path],
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    verified: list[dict[str, Any]] = []
    for index, identity in enumerate(rows):
        path, compact = _verify_identity(
            identity,
            base=base,
            allowed_roots=allowed_roots,
            named_roots=named_roots,
            label=f"{label} recovery_evidence[{index}]",
        )
        if isinstance(identity, dict) and isinstance(identity.get("kind"), str):
            compact["kind"] = identity["kind"]
        kind = str(compact.get("kind", "")).lower()
        if any(token in kind for token in ("candidate", "review", "calendar")):
            if path not in date_index_cache:
                date_index_cache[path] = _build_recovery_date_index(path)
            supported_dates = sorted(date_index_cache[path].get(target_id, set()))
            if supported_dates:
                compact["supported_local_dates"] = supported_dates
        verified.append(compact)
    return verified


def _url_path_supports_date(url: str, local_date: str) -> bool:
    if not url or not local_date:
        return False
    path_dates = {
        candidate
        for candidate in DATE_IN_PATH_RE.findall(urlparse(url).path)
        if _is_iso_date(candidate)
    }
    return local_date in path_dates


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _calendar_evidence(
    *,
    target_id: int,
    calendar_url: str,
    staged_local_date: str,
    cache_identities: list[dict[str, Any]],
    fragment_request: dict[str, Any],
    request_logs: dict[str, list[dict[str, Any]]],
    recovery_evidence: list[dict[str, Any]],
    due_row: dict[str, Any] | None,
    due_manifest_identity: dict[str, Any],
    due_shard_evidence: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    if not calendar_url:
        return None
    matching_cache = [row for row in cache_identities if row.get("source_url") == calendar_url]
    if matching_cache:
        return {"kind": "verified_source_cache", "source_url": calendar_url, "identities": matching_cache}
    fixture = fragment_request.get("fixture_identity")
    fragment_urls = {
        fragment_request.get("source_url"),
        fragment_request.get("evidence_source_url"),
    }
    if calendar_url in fragment_urls and isinstance(fixture, dict):
        return {
            "kind": "source_fragment_fixture",
            "source_url": calendar_url,
            "identity": fixture,
        }
    if calendar_url in request_logs:
        return {
            "kind": "request_log",
            "source_url": calendar_url,
            "identities": [row["identity"] for row in request_logs[calendar_url]],
        }
    detail_url = fragment_request.get("source_url")
    fragment_local_date = fragment_request.get("local_date")
    recovery_support = any(
        staged_local_date in row.get("supported_local_dates", [])
        for row in recovery_evidence
    )
    url_support = isinstance(detail_url, str) and _url_path_supports_date(
        detail_url, staged_local_date
    )
    if (
        calendar_url != detail_url
        and isinstance(detail_url, str)
        and detail_url
        and isinstance(fragment_local_date, str)
        and fragment_local_date == staged_local_date
        and (url_support or recovery_support)
        and isinstance(fixture, dict)
        and cache_identities
    ):
        return {
            "kind": "verified_detail_source_date",
            "calendar_url": calendar_url,
            "detail_url": detail_url,
            "local_date": staged_local_date,
            "date_support": {
                "detail_url_path": url_support,
                "verified_recovery_evidence": recovery_support,
            },
            "fixture_identity": fixture,
            "cache_identities": cache_identities,
            "recovery_identities": recovery_evidence,
        }
    if due_row is not None:
        due_refs = _parse_source_refs(due_row.get("source_refs"), f"due target {target_id}")
        due_url, _ = _calendar_source(due_refs)
        shard_id = due_row.get("shard_id")
        if (
            due_url == calendar_url
            and isinstance(shard_id, str)
            and due_shard_evidence.get(shard_id)
        ):
            evidence = {
                "kind": "current_year_due_aggregate",
                "source_url": calendar_url,
                "aggregate_manifest": due_manifest_identity,
                "due_row_sha256": _sha256(_canonical_json_bytes(due_row)),
            }
            evidence["shard_evidence"] = due_shard_evidence[shard_id]
            return evidence
    direct_recovery = [
        row
        for row in recovery_evidence
        if any(token in str(row.get("kind", "")).lower() for token in ("calendar", "request", "cache", "capture", "pdf"))
    ]
    if direct_recovery and calendar_url in fragment_urls:
        return {
            "kind": "verified_recovery_evidence",
            "source_url": calendar_url,
            "identities": direct_recovery,
        }
    return None


def _due_gate_reason(
    row: dict[str, Any],
    *,
    v9_target: dict[str, Any],
    record: dict[str, Any],
    staged: dict[str, Any],
    cutoff: date,
) -> str | None:
    if row.get("target_sha256") != v9_target.get("target_sha256"):
        return "target_sha256_mismatch"
    if _year(row.get("year"), "current-year due row") != 2026:
        return "year_not_2026"
    if row.get("status") != "finished":
        return "status_not_finished"
    if staged.get("status") != "finished":
        return "staged_status_not_finished"
    try:
        local_date = date.fromisoformat(str(row.get("local_date", "")))
    except ValueError:
        return "local_date_invalid"
    if local_date > cutoff:
        return "local_date_after_cutoff"
    if staged.get("local_date") != row.get("local_date"):
        return "staged_local_date_mismatch"
    if not _results_complete(record):
        return "results_incomplete"
    return None


def _approval_template(
    *,
    bundle_manifest_sha256: str,
    layer: str,
    cutoff_date: str | None,
    chunk: dict[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_kind": "historical_race_detail_chunk_approval",
        "schema_version": SCHEMA_VERSION,
        "status": "pending",
        "approved_by": None,
        "approved_at": None,
        "bundle_manifest_sha256": bundle_manifest_sha256,
        "layer": layer,
        "cutoff_date": cutoff_date,
        "chunk_id": chunk["chunk_id"],
        "chunk_manifest_sha256": chunk["manifest"]["sha256"],
        "candidates_sha256": chunk["candidates"]["sha256"],
        "target_count": chunk["target_count"],
        "target_ids": chunk["target_ids"],
    }


def verify_source_bundle(bundle_root: Path | str) -> dict[str, int]:
    supplied_root = Path(bundle_root).expanduser()
    if supplied_root.is_symlink():
        raise SourceBundlePackagingError(f"bundle root must not be a symlink: {supplied_root}")
    bundle_root = supplied_root.resolve()
    if not bundle_root.is_dir():
        raise SourceBundlePackagingError(f"bundle root is not a directory: {bundle_root}")
    allowed_roots = (bundle_root,)
    named_roots = {"bundle": bundle_root}
    identity_payload, _ = _load_json(bundle_root / "bundle-identity.json", "bundle identity")
    manifest_path, manifest_identity = _verify_identity(
        identity_payload.get("manifest"),
        base=bundle_root,
        allowed_roots=allowed_roots,
        named_roots=named_roots,
        label="bundle manifest",
    )
    manifest, _ = _load_json(manifest_path, "bundle manifest")
    if manifest.get("artifact_kind") != ARTIFACT_KIND:
        raise SourceBundlePackagingError("bundle manifest artifact_kind is invalid")
    manifest_sha = manifest_identity["sha256"]
    for index, approval_identity in enumerate(identity_payload.get("approval_templates", [])):
        approval_path, _ = _verify_identity(
            approval_identity,
            base=bundle_root,
            allowed_roots=allowed_roots,
            named_roots=named_roots,
            label=f"approval template[{index}]",
        )
        approval, _ = _load_json(approval_path, f"approval template[{index}]")
        if approval.get("bundle_manifest_sha256") != manifest_sha:
            raise SourceBundlePackagingError(
                f"approval template does not bind bundle manifest: {approval_path}"
            )

    total_candidates = 0
    total_sources = 0
    total_source_bytes = 0
    layers = manifest.get("layers")
    if not isinstance(layers, dict):
        raise SourceBundlePackagingError("bundle manifest layers must be an object")
    for layer, layer_summary in layers.items():
        if not isinstance(layer_summary, dict):
            raise SourceBundlePackagingError(f"layer summary must be an object: {layer}")
        for chunk in layer_summary.get("chunks", []):
            if not isinstance(chunk, dict):
                raise SourceBundlePackagingError(f"chunk summary must be an object: {layer}")
            chunk_manifest_path, chunk_manifest_identity = _verify_identity(
                chunk.get("manifest"),
                base=bundle_root,
                allowed_roots=allowed_roots,
                named_roots=named_roots,
                label=f"chunk {chunk.get('chunk_id')} manifest",
            )
            chunk_manifest, _ = _load_json(
                chunk_manifest_path, f"chunk {chunk.get('chunk_id')} manifest"
            )
            if chunk_manifest_identity["sha256"] != chunk["manifest"].get("sha256"):
                raise SourceBundlePackagingError(
                    f"chunk manifest identity mismatch: {chunk.get('chunk_id')}"
                )
            chunk_root = chunk_manifest_path.parent
            artifacts = chunk_manifest.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                raise SourceBundlePackagingError(
                    f"chunk artifacts are missing: {chunk.get('chunk_id')}"
                )
            artifact_by_path: dict[str, dict[str, Any]] = {}
            for artifact_index, artifact in enumerate(artifacts):
                _, _ = _verify_identity(
                    artifact,
                    base=chunk_root,
                    allowed_roots=allowed_roots,
                    named_roots=named_roots,
                    label=f"chunk {chunk.get('chunk_id')} artifact[{artifact_index}]",
                )
                artifact_path = artifact.get("path")
                if not isinstance(artifact_path, str) or artifact_path in artifact_by_path:
                    raise SourceBundlePackagingError(
                        f"chunk artifact path is invalid or duplicated: {artifact_path}"
                    )
                artifact_by_path[artifact_path] = artifact
            if artifacts[0].get("path") != "candidates.jsonl":
                raise SourceBundlePackagingError(
                    f"chunk candidates must be the first artifact: {chunk.get('chunk_id')}"
                )
            candidate_path = chunk_root / "candidates.jsonl"
            candidates = _load_jsonl(
                candidate_path, f"chunk {chunk.get('chunk_id')} candidates"
            )
            candidate_summary = chunk.get("candidates")
            if not isinstance(candidate_summary, dict):
                raise SourceBundlePackagingError(
                    f"chunk candidates summary is missing: {chunk.get('chunk_id')}"
                )
            candidate_raw = candidate_path.read_bytes()
            if (
                candidate_summary.get("sha256") != _sha256(candidate_raw)
                or candidate_summary.get("size") != len(candidate_raw)
                or chunk_manifest.get("candidates") != artifacts[0]
            ):
                raise SourceBundlePackagingError(
                    f"chunk candidates identity mismatch: {chunk.get('chunk_id')}"
                )
            target_ids = [
                row.get("pending_target", {}).get("target_id")
                for row in candidates
            ]
            if target_ids != chunk_manifest.get("target_ids"):
                raise SourceBundlePackagingError(
                    f"chunk candidate target IDs mismatch: {chunk.get('chunk_id')}"
                )
            source_paths: set[str] = set()
            chunk_source_bytes = 0
            for row in candidates:
                approved = row.get("approved_source_cache_identity")
                if not isinstance(approved, dict):
                    raise SourceBundlePackagingError(
                        f"candidate lacks approved source identity: {chunk.get('chunk_id')}"
                    )
                source_path = approved.get("path")
                artifact = artifact_by_path.get(source_path)
                if artifact is None or source_path == "candidates.jsonl":
                    raise SourceBundlePackagingError(
                        f"approved source is not bound by chunk manifest: {source_path}"
                    )
                for key in (
                    "path",
                    "sha256",
                    "size",
                    "source_url",
                    "cached_at",
                    "protected_by",
                ):
                    if approved.get(key) != artifact.get(key):
                        raise SourceBundlePackagingError(
                            f"approved source identity mismatch for {source_path}: {key}"
                        )
                source_paths.add(source_path)
                chunk_source_bytes += approved["size"]
            manifest_source_paths = set(artifact_by_path) - {"candidates.jsonl"}
            if source_paths != manifest_source_paths or len(source_paths) != len(candidates):
                raise SourceBundlePackagingError(
                    f"chunk source/candidate conservation failed: {chunk.get('chunk_id')}"
                )
            if (
                chunk_manifest.get("source_object_count") != len(source_paths)
                or chunk_manifest.get("source_object_bytes") != chunk_source_bytes
            ):
                raise SourceBundlePackagingError(
                    f"chunk source object counts mismatch: {chunk.get('chunk_id')}"
                )
            total_candidates += len(candidates)
            total_sources += len(source_paths)
            total_source_bytes += chunk_source_bytes
    source_summary = manifest.get("source_objects")
    if not isinstance(source_summary, dict) or (
        source_summary.get("count") != total_sources
        or source_summary.get("bytes") != total_source_bytes
        or manifest.get("record_count") != total_candidates
    ):
        raise SourceBundlePackagingError("bundle source object accounting mismatch")
    return {
        "record_count": total_candidates,
        "source_object_count": total_sources,
        "source_object_bytes": total_source_bytes,
    }


def package_source_bundle(
    v6_root: Path | str,
    v9_root: Path | str,
    current_year_root: Path | str,
    output_dir: Path | str,
    *,
    expected_package_count: int = 39,
    expected_scope_count: int = 4930,
    expected_input_record_count: int = 4652,
    expected_input_gap_count: int = 278,
    expected_historical_record_count: int = 4351,
    expected_historical_gap_count: int = 214,
    expected_historical_chunk_count: int = 18,
    expected_new_record_count: int = 301,
    expected_new_gap_count: int = 64,
    expected_new_chunk_count: int = 2,
    expected_runner_count: int = 51191,
    expected_result_count: int = 48413,
    cutoff_date: str = "2026-07-15",
    chunk_size: int = 250,
) -> dict[str, Any]:
    roots = {
        "v6": Path(v6_root).expanduser().resolve(),
        "v9": Path(v9_root).expanduser().resolve(),
        "current_year": Path(current_year_root).expanduser().resolve(),
    }
    output_dir = Path(output_dir).expanduser().resolve()
    if any(not root.is_dir() for root in roots.values()):
        raise SourceBundlePackagingError("all three input roots must be directories")
    if output_dir.exists():
        raise SourceBundlePackagingError(f"output directory already exists: {output_dir}")
    if chunk_size <= 0 or chunk_size > 250:
        raise SourceBundlePackagingError("chunk_size must be between 1 and 250")
    if any(_is_within(output_dir, root) for root in roots.values()):
        raise SourceBundlePackagingError("output directory must not be inside an input root")
    runtime_root = Path(os.path.commonpath([str(root) for root in roots.values()])).resolve()
    named_roots = {**roots, "runtime": runtime_root}
    allowed_roots = (runtime_root,)

    v6_manifest_path = roots["v6"] / "manifest.json"
    v9_manifest_path = roots["v9"] / "manifest.json"
    due_manifest_path = roots["current_year"] / "manifest.json"
    v6_manifest, v6_manifest_raw = _load_json(v6_manifest_path, "v6 manifest")
    v9_manifest, v9_manifest_raw = _load_json(v9_manifest_path, "v9 manifest")
    due_manifest, due_manifest_raw = _load_json(due_manifest_path, "current-year manifest")
    if v6_manifest.get("artifact_kind") != V6_KIND:
        raise SourceBundlePackagingError(f"v6 manifest artifact_kind must be {V6_KIND}")
    if v6_manifest.get("descriptor_count") != expected_package_count:
        raise SourceBundlePackagingError(
            f"v6 manifest must declare exactly {expected_package_count} descriptors"
        )
    if v6_manifest.get("actionable_count") != expected_scope_count:
        raise SourceBundlePackagingError(
            "v6 actionable_count does not match the expected formal package scope: "
            f"expected {expected_scope_count}, got {v6_manifest.get('actionable_count')!r}"
        )
    if due_manifest.get("artifact_kind") != DUE_KIND:
        raise SourceBundlePackagingError(f"current-year manifest artifact_kind must be {DUE_KIND}")
    if due_manifest.get("cutoff_date") != cutoff_date:
        raise SourceBundlePackagingError(
            f"current-year cutoff must be {cutoff_date}, got {due_manifest.get('cutoff_date')!r}"
        )
    due_validations = due_manifest.get("validations")
    if not isinstance(due_validations, dict) or due_validations.get(
        "required_identity_chain_verified"
    ) is not True:
        raise SourceBundlePackagingError(
            "current-year manifest has not verified its required identity chain"
        )
    try:
        cutoff = date.fromisoformat(cutoff_date)
    except ValueError as exc:
        raise SourceBundlePackagingError(f"invalid cutoff_date: {cutoff_date}") from exc

    v6_artifacts = _verify_top_manifest_artifacts(
        v6_manifest,
        root=roots["v6"],
        allowed_roots=allowed_roots,
        named_roots=named_roots,
        label="v6 manifest",
    )
    v9_artifacts = _verify_top_manifest_artifacts(
        v9_manifest,
        root=roots["v9"],
        allowed_roots=allowed_roots,
        named_roots=named_roots,
        label="v9 manifest",
    )
    for index, identity in enumerate(_iter_manifest_identities(due_manifest.get("artifacts", {}))):
        _verify_identity(
            identity,
            base=roots["current_year"],
            allowed_roots=allowed_roots,
            named_roots=named_roots,
            label=f"current-year artifact[{index}]",
        )
    for index, identity in enumerate(_iter_manifest_identities(due_manifest.get("shards", []))):
        _verify_identity(
            identity,
            base=roots["current_year"],
            allowed_roots=allowed_roots,
            named_roots=named_roots,
            label=f"current-year shard identity[{index}]",
        )

    remaining_identity = v9_artifacts.get("remaining_targets.jsonl")
    if remaining_identity is None:
        raise SourceBundlePackagingError("v9 manifest does not bind remaining_targets.jsonl")
    remaining_path = roots["v9"] / "remaining_targets.jsonl"
    v9_rows = _load_jsonl(remaining_path, "v9 remaining targets")
    if v9_manifest.get("target_count") != len(v9_rows):
        raise SourceBundlePackagingError("v9 target_count does not match remaining_targets.jsonl")
    v9_targets: dict[int, dict[str, Any]] = {}
    approved_inventory_values: set[str] = set()
    for row in v9_rows:
        target_id = _target_id(row, "v9 remaining target")
        if target_id in v9_targets:
            raise SourceBundlePackagingError(f"duplicate v9 target_id {target_id}")
        inventory_sha = row.get("inventory_artifact_sha256")
        if not isinstance(inventory_sha, str) or len(inventory_sha) != 64:
            raise SourceBundlePackagingError(f"v9 target {target_id} has invalid formal inventory SHA")
        approved_inventory_values.add(inventory_sha)
        v9_targets[target_id] = row
    if len(approved_inventory_values) != 1:
        raise SourceBundlePackagingError("v9 must bind exactly one approved inventory artifact SHA")
    approved_inventory_sha = next(iter(approved_inventory_values))

    due_files = due_manifest.get("artifacts")
    if not isinstance(due_files, dict):
        raise SourceBundlePackagingError("current-year artifacts must be an object")
    due_rows = _load_jsonl(
        _resolve_evidence_path(
            due_files.get("unified_due_events.jsonl", {}).get("path"),
            base=roots["current_year"],
            allowed_roots=allowed_roots,
            label="unified_due_events",
        ),
        "unified due events",
    )
    due_by_id: dict[int, dict[str, Any]] = {}
    for row in due_rows:
        target_id = _target_id(row, "unified due event")
        if target_id in due_by_id:
            raise SourceBundlePackagingError(f"duplicate unified due target_id {target_id}")
        due_by_id[target_id] = row
    due_non_event_ids: set[int] = set()
    for filename in ("unified_due_gaps.jsonl", "unified_not_due.jsonl"):
        identity = due_files.get(filename)
        if not isinstance(identity, dict):
            raise SourceBundlePackagingError(f"current-year manifest missing {filename}")
        path = _resolve_evidence_path(
            identity.get("path"),
            base=roots["current_year"],
            allowed_roots=allowed_roots,
            label=filename,
        )
        for row in _load_jsonl(path, filename):
            target_id = _target_id(row, filename)
            if target_id in due_by_id or target_id in due_non_event_ids:
                raise SourceBundlePackagingError(
                    f"current-year classifications overlap for target_id {target_id}"
                )
            due_non_event_ids.add(target_id)
    due_shard_evidence: dict[str, list[dict[str, Any]]] = {}
    for shard in due_manifest.get("shards", []):
        if not isinstance(shard, dict) or not isinstance(shard.get("shard_id"), str):
            continue
        compact_rows: list[dict[str, Any]] = []
        for identity in _iter_manifest_identities(shard.get("identities", {})):
            _, compact = _verify_identity(
                identity,
                base=roots["current_year"],
                allowed_roots=allowed_roots,
                named_roots=named_roots,
                label=f"due shard {shard['shard_id']}",
            )
            compact_rows.append(compact)
        due_shard_evidence[shard["shard_id"]] = compact_rows

    request_logs, request_log_identities = _load_request_logs(roots["v6"], v6_artifacts)
    package_paths = sorted(
        (roots["v6"] / "run").glob("*/package-manifest.json"),
        key=lambda path: path.parent.name,
    )
    smoke_package_paths = sorted((roots["v6"] / "smoke/run").glob("*/package-manifest.json"))
    if len(package_paths) != expected_package_count:
        raise SourceBundlePackagingError(
            f"v6 run must contain exactly {expected_package_count} package manifests, found {len(package_paths)}"
        )
    if any("smoke" in path.relative_to(roots["v6"]).parts for path in package_paths):
        raise SourceBundlePackagingError("smoke package must not be included in formal run packages")
    if v6_manifest.get("smoke_descriptor_count") != len(smoke_package_paths):
        raise SourceBundlePackagingError("v6 smoke package count does not match smoke_descriptor_count")

    records_by_layer: dict[str, list[dict[str, Any]]] = {
        HISTORICAL_LAYER: [],
        CURRENT_YEAR_LAYER: [],
    }
    gaps: list[dict[str, Any]] = []
    package_index_rows: list[dict[str, Any]] = []
    evidence_index_rows: list[dict[str, Any]] = []
    formal_package_scope_target_ids: set[int] = set()
    seen_target_ids: set[int] = set()
    source_plan_values: set[str] = set()
    regions = {
        region: {"records": 0, "gaps": 0, "runners": 0, "results": 0}
        for region in REGIONS
    }
    input_historical_records = 0
    input_historical_gaps = 0
    input_new_records = 0
    input_new_gaps = 0
    current_year_due_passed = 0
    current_year_due_failed = 0
    recovery_date_index_cache: dict[Path, dict[int, set[str]]] = {}

    for package_path in package_paths:
        shard_id = package_path.parent.name
        region = _region_for_shard(shard_id)
        package_relative = package_path.relative_to(roots["v6"]).as_posix()
        package_identity = v6_artifacts.get(package_relative)
        if package_identity is None:
            raise SourceBundlePackagingError(f"v6 manifest does not bind package {package_relative}")
        package, _ = _load_json(package_path, f"package {shard_id}")
        if package.get("artifact_kind") != PACKAGE_KIND:
            raise SourceBundlePackagingError(f"{shard_id} artifact_kind must be {PACKAGE_KIND}")
        package_records = package.get("records")
        package_gaps = package.get("gaps")
        if not isinstance(package_records, list) or not isinstance(package_gaps, list):
            raise SourceBundlePackagingError(f"{shard_id} records/gaps must be arrays")
        record_count = _strict_count(package, "record_count", shard_id)
        gap_count = _strict_count(package, "gap_count", shard_id)
        accounted_count = _strict_count(package, "accounted_count", shard_id)
        scope_count = _strict_count(package, "scope_count", shard_id)
        if record_count != len(package_records) or gap_count != len(package_gaps):
            raise SourceBundlePackagingError(f"{shard_id} package counts do not match arrays")
        if record_count + gap_count != accounted_count or accounted_count != scope_count:
            raise SourceBundlePackagingError(f"{shard_id} package accounting conservation failed")
        package_target_ids = [
            _target_id(row, f"{shard_id} package")
            for row in [*package_records, *package_gaps]
        ]
        if len(set(package_target_ids)) != len(package_target_ids):
            raise SourceBundlePackagingError(f"{shard_id} package contains duplicate target IDs")
        duplicate_scope_ids = formal_package_scope_target_ids.intersection(package_target_ids)
        if duplicate_scope_ids:
            raise SourceBundlePackagingError(
                "formal package scope contains duplicate target IDs across packages: "
                f"{sorted(duplicate_scope_ids)}"
            )
        formal_package_scope_target_ids.update(package_target_ids)

        staged_path, staged_identity = _verify_identity(
            package.get("staged_event_identity"),
            base=package_path.parent,
            allowed_roots=allowed_roots,
            named_roots=named_roots,
            label=f"{shard_id} staged-events",
        )
        candidate_path, candidate_identity = _verify_identity(
            package.get("candidate_identity"),
            base=package_path.parent,
            allowed_roots=allowed_roots,
            named_roots=named_roots,
            label=f"{shard_id} validated candidates",
        )
        cache_manifest_path, cache_manifest_identity = _verify_identity(
            package.get("source_cache_manifest_identity"),
            base=package_path.parent,
            allowed_roots=allowed_roots,
            named_roots=named_roots,
            label=f"{shard_id} source cache manifest",
        )
        for path in (staged_path, candidate_path, cache_manifest_path):
            relative = path.relative_to(roots["v6"]).as_posix()
            if relative not in v6_artifacts:
                raise SourceBundlePackagingError(
                    f"v6 manifest does not bind {shard_id} evidence {relative}"
                )
        staged_rows = _load_staged_rows(staged_path)
        cache_entries, compact_cache_entries = _verify_cache_manifest(
            cache_manifest_path,
            allowed_roots=allowed_roots,
            named_roots=named_roots,
        )
        fragment_relative = f"source_fragments/{shard_id}.json"
        fragment_identity = v6_artifacts.get(fragment_relative)
        if fragment_identity is None:
            raise SourceBundlePackagingError(f"v6 manifest missing {fragment_relative}")
        fragment_path = roots["v6"] / fragment_relative
        fragment, _ = _load_json(fragment_path, f"source fragment {shard_id}")
        if fragment.get("artifact_kind") != FRAGMENT_KIND or fragment.get("shard_id") != shard_id:
            raise SourceBundlePackagingError(f"invalid source fragment for {shard_id}")
        fragment_requests: dict[int, dict[str, Any]] = {}
        for request in fragment.get("requests", []):
            target_id = _target_id(request, f"source fragment {shard_id}")
            if target_id in fragment_requests:
                raise SourceBundlePackagingError(
                    f"duplicate source fragment target_id {target_id}: {shard_id}"
                )
            fragment_requests[target_id] = request
        if fragment.get("target_count") != len(fragment_requests):
            raise SourceBundlePackagingError(
                f"{shard_id} source fragment target_count does not match requests"
            )
        expected_target_ids = set(package_target_ids)
        if set(staged_rows) != expected_target_ids or set(fragment_requests) != expected_target_ids:
            raise SourceBundlePackagingError(
                f"{shard_id} package/staged/source-fragment target sets differ"
            )

        package_request_identities: dict[str, dict[str, Any]] = {}
        for rows in request_logs.values():
            for row in rows:
                if row.get("shard_id") == shard_id:
                    compact = row["identity"]
                    package_request_identities[compact["sha256"]] = compact
        for request in fragment_requests.values():
            source_url = request.get("source_url")
            if isinstance(source_url, str):
                for row in request_logs.get(source_url, []):
                    compact = row["identity"]
                    package_request_identities[compact["sha256"]] = compact
        package_runner_count = 0
        package_result_count = 0

        for collection_name, collection in (("records", package_records), ("gaps", package_gaps)):
            for raw_row in collection:
                target_id = _target_id(raw_row, f"{shard_id} {collection_name}")
                if target_id in seen_target_ids:
                    raise SourceBundlePackagingError(f"duplicate target_id {target_id} across packages")
                seen_target_ids.add(target_id)
                v9_target = v9_targets.get(target_id)
                if v9_target is None:
                    raise SourceBundlePackagingError(f"target {target_id} is not in v9 remaining targets")
                if v9_target.get("resolution_status") != "pending":
                    raise SourceBundlePackagingError(
                        f"target {target_id} is not pending in v9 remaining targets"
                    )
                if raw_row.get("target_sha256") != v9_target.get("target_sha256"):
                    raise SourceBundlePackagingError(
                        f"target {target_id} pending target SHA differs between v6 and v9"
                    )
                year = _year(v9_target.get("year"), f"v9 target {target_id}")
                layer = _layer_for_year(year)
                if year == 2025:
                    raise SourceBundlePackagingError(
                        f"target {target_id} unexpectedly belongs to unsupported 2025 input"
                    )
                staged = staged_rows.get(target_id)
                fragment_request = fragment_requests.get(target_id)
                if staged is None or fragment_request is None:
                    raise SourceBundlePackagingError(
                        f"target {target_id} lacks staged-events or source fragment binding"
                    )
                if staged.get("target_sha256") != v9_target.get("target_sha256"):
                    raise SourceBundlePackagingError(
                        f"target {target_id} staged pending target SHA mismatch"
                    )
                if fragment_request.get("target_sha256") != v9_target.get("target_sha256"):
                    raise SourceBundlePackagingError(
                        f"target {target_id} source fragment pending target SHA mismatch"
                    )
                source_plan_sha = raw_row.get("inventory_artifact_sha256") or staged.get(
                    "inventory_artifact_sha256"
                )
                if not isinstance(source_plan_sha, str) or len(source_plan_sha) != 64:
                    raise SourceBundlePackagingError(
                        f"target {target_id} source plan artifact SHA is invalid"
                    )
                if staged.get("inventory_artifact_sha256") != source_plan_sha:
                    raise SourceBundlePackagingError(
                        f"target {target_id} staged source plan artifact SHA mismatch"
                    )
                source_plan_values.add(source_plan_sha)

                if collection_name == "gaps":
                    if layer == HISTORICAL_LAYER:
                        input_historical_gaps += 1
                    else:
                        input_new_gaps += 1
                    gap_row = {
                        "target_id": target_id,
                        "target_sha256": v9_target["target_sha256"],
                        "year": year,
                        "series_key": v9_target.get("series_key"),
                        "region": v9_target.get("country_region"),
                        "layer": layer,
                        "reason_code": raw_row.get("reason_code", "source_package_gap"),
                        "source_gap": raw_row,
                        "package_identity": package_identity,
                    }
                    gaps.append(gap_row)
                    regions[region]["gaps"] += 1
                    continue

                if year <= 2024:
                    input_historical_records += 1
                else:
                    input_new_records += 1
                record = raw_row
                cache_identities = _bind_record_caches(
                    record,
                    cache_entries=cache_entries,
                    compact_entries=compact_cache_entries,
                    label=f"target {target_id}",
                )
                _, fixture_identity = _verify_identity(
                    fragment_request.get("fixture_identity"),
                    base=fragment_path.parent,
                    allowed_roots=allowed_roots,
                    named_roots=named_roots,
                    label=f"target {target_id} source fragment fixture",
                )
                if fragment_request.get("source_url") != record.get("source_url"):
                    raise SourceBundlePackagingError(
                        f"target {target_id} source fragment URL differs from record source URL"
                    )
                if fixture_identity["sha256"] not in {
                    identity["sha256"] for identity in cache_identities
                }:
                    raise SourceBundlePackagingError(
                        f"target {target_id} source fragment fixture differs from record cache"
                    )
                verified_fragment_request = dict(fragment_request)
                verified_fragment_request["fixture_identity"] = fixture_identity
                primary_cache_candidates = [
                    identity
                    for identity in cache_identities
                    if identity.get("source_url") == record.get("source_url")
                ]
                if len(primary_cache_candidates) != 1:
                    gaps.append(
                        {
                            "target_id": target_id,
                            "target_sha256": v9_target["target_sha256"],
                            "year": year,
                            "series_key": v9_target.get("series_key"),
                            "region": region,
                            "layer": layer,
                            "reason_code": "primary_source_cache_unresolved",
                            "evidence": {
                                "record_source_url": record.get("source_url"),
                                "matching_cache_count": len(primary_cache_candidates),
                            },
                            "package_identity": package_identity,
                        }
                    )
                    regions[region]["gaps"] += 1
                    continue
                primary_cache_identity = primary_cache_candidates[0]
                primary_source_path = (
                    named_roots[primary_cache_identity["root"]]
                    / primary_cache_identity["path"]
                )
                recovery_evidence = _verify_external_recovery_evidence(
                    fragment_request.get("recovery_evidence"),
                    target_id=target_id,
                    date_index_cache=recovery_date_index_cache,
                    base=fragment_path.parent,
                    allowed_roots=allowed_roots,
                    named_roots=named_roots,
                    label=f"target {target_id}",
                )
                for identity in recovery_evidence:
                    package_request_identities[identity["sha256"]] = identity
                source_refs = _parse_source_refs(
                    staged.get("source_refs"), f"staged target {target_id}"
                )
                calendar_url, calendar_provider = _calendar_source(source_refs)
                due_row = due_by_id.get(target_id)
                if year == 2026:
                    if due_row is None or target_id in due_non_event_ids:
                        due_reason = "not_in_due_events"
                    else:
                        due_reason = _due_gate_reason(
                            due_row,
                            v9_target=v9_target,
                            record=record,
                            staged=staged,
                            cutoff=cutoff,
                        )
                    if due_reason:
                        current_year_due_failed += 1
                        gaps.append(
                            {
                                "target_id": target_id,
                                "target_sha256": v9_target["target_sha256"],
                                "year": year,
                                "series_key": v9_target.get("series_key"),
                                "region": region,
                                "layer": layer,
                                "reason_code": "current_year_due_gate_failed",
                                "evidence": {"failure": due_reason, "cutoff_date": cutoff_date},
                                "package_identity": package_identity,
                            }
                        )
                        regions[region]["gaps"] += 1
                        continue
                    current_year_due_passed += 1
                calendar_evidence = _calendar_evidence(
                    target_id=target_id,
                    calendar_url=calendar_url,
                    staged_local_date=str(staged.get("local_date") or ""),
                    cache_identities=cache_identities,
                    fragment_request=verified_fragment_request,
                    request_logs=request_logs,
                    recovery_evidence=recovery_evidence,
                    due_row=due_row,
                    due_manifest_identity=_file_identity(
                        due_manifest_path,
                        "current_year/manifest.json",
                    ),
                    due_shard_evidence=due_shard_evidence,
                )
                if calendar_evidence is None:
                    gaps.append(
                        {
                            "target_id": target_id,
                            "target_sha256": v9_target["target_sha256"],
                            "year": year,
                            "series_key": v9_target.get("series_key"),
                            "region": region,
                            "layer": layer,
                            "reason_code": "calendar_evidence_untraceable",
                            "evidence": {
                                "calendar_source_url": calendar_url,
                                "calendar_source_provider": calendar_provider,
                            },
                            "package_identity": package_identity,
                        }
                    )
                    regions[region]["gaps"] += 1
                    continue

                runners = _module_count(record, "runners", f"target {target_id}")
                results = _module_count(record, "results", f"target {target_id}")
                package_runner_count += runners
                package_result_count += results
                source_provider = fragment_request.get("source_provider")
                if not isinstance(source_provider, str) or not source_provider:
                    raise SourceBundlePackagingError(f"target {target_id} has no source provider")
                bundle_record = {
                    "pending_target": {
                        "target_id": target_id,
                        "target_sha256": v9_target["target_sha256"],
                        "year": year,
                        "series_key": v9_target.get("series_key"),
                        "region": v9_target.get("country_region"),
                        "resolution_status": v9_target.get("resolution_status"),
                    },
                    "source_plan_artifact_sha256": source_plan_sha,
                    "approved_inventory_artifact_sha256": approved_inventory_sha,
                    "local_date": staged.get("local_date"),
                    "status": staged.get("status"),
                    "source_refs": source_refs,
                    "distance_text": record.get("distance_text") or staged.get("distance_text"),
                    "distance_provenance": record.get("distance_provenance"),
                    "modules": record.get("modules"),
                    "source": {
                        "name": record.get("source_name"),
                        "provider": source_provider,
                        "url": record.get("source_url"),
                    },
                    "calendar_evidence": calendar_evidence,
                    "cache_identities": cache_identities,
                    "package_identity": package_identity,
                    "source_fragment_identity": fragment_identity,
                    "staged_event_identity": staged_identity,
                    "source_cache_manifest_identity": cache_manifest_identity,
                    "candidate_identity": candidate_identity,
                    "_primary_source_path": str(primary_source_path),
                    "_primary_cache_identity": primary_cache_identity,
                }
                records_by_layer[layer].append(bundle_record)
                regions[region]["records"] += 1
                regions[region]["runners"] += runners
                regions[region]["results"] += results

        if not package_request_identities:
            raise SourceBundlePackagingError(
                f"{shard_id} has no verified request-log or recovery evidence identity"
            )

        package_index_rows.append(
            {
                "shard_id": shard_id,
                "region": region,
                "package_identity": package_identity,
                "scope_count": scope_count,
                "record_count": record_count,
                "gap_count": gap_count,
                "runner_count": package_runner_count,
                "result_count": package_result_count,
            }
        )
        evidence_index_rows.append(
            {
                "shard_id": shard_id,
                "package_identity": package_identity,
                "staged_event_identity": staged_identity,
                "candidate_identity": candidate_identity,
                "source_fragment_identity": fragment_identity,
                "source_cache_manifest_identity": cache_manifest_identity,
                "request_evidence_identities": [
                    package_request_identities[key]
                    for key in sorted(package_request_identities)
                ],
            }
        )

    input_record_count = input_historical_records + input_new_records
    input_gap_count = input_historical_gaps + input_new_gaps
    if len(formal_package_scope_target_ids) != expected_scope_count:
        raise SourceBundlePackagingError(
            "formal package scope target union count mismatch: "
            f"expected {expected_scope_count}, found {len(formal_package_scope_target_ids)}"
        )
    unknown_scope_target_ids = formal_package_scope_target_ids.difference(v9_targets)
    if unknown_scope_target_ids:
        raise SourceBundlePackagingError(
            "formal package scope contains targets outside v9: "
            f"{sorted(unknown_scope_target_ids)}"
        )
    if seen_target_ids != formal_package_scope_target_ids:
        missing_seen = sorted(formal_package_scope_target_ids - seen_target_ids)
        unexpected_seen = sorted(seen_target_ids - formal_package_scope_target_ids)
        raise SourceBundlePackagingError(
            "seen target IDs differ from the formal package scope union: "
            f"missing={missing_seen}, unexpected={unexpected_seen}"
        )
    if input_record_count != expected_input_record_count:
        raise SourceBundlePackagingError(
            f"expected {expected_input_record_count} input package records, found {input_record_count}"
        )
    if input_gap_count != expected_input_gap_count:
        raise SourceBundlePackagingError(
            f"expected {expected_input_gap_count} input package gaps, found {input_gap_count}"
        )
    if input_historical_records != expected_historical_record_count:
        raise SourceBundlePackagingError(
            f"expected {expected_historical_record_count} <=2024 records, found {input_historical_records}"
        )
    if input_historical_gaps != expected_historical_gap_count:
        raise SourceBundlePackagingError(
            f"expected {expected_historical_gap_count} <=2024 gaps, found {input_historical_gaps}"
        )
    if input_new_records != expected_new_record_count:
        raise SourceBundlePackagingError(
            f"expected {expected_new_record_count} 2026 records, found {input_new_records}"
        )
    if input_new_gaps != expected_new_gap_count:
        raise SourceBundlePackagingError(
            f"expected {expected_new_gap_count} 2026 gaps, found {input_new_gaps}"
        )
    if len(source_plan_values) != 1:
        raise SourceBundlePackagingError("v6 records/gaps must bind exactly one source plan artifact SHA")
    source_plan_sha = next(iter(source_plan_values))
    if len(seen_target_ids) != sum(row["scope_count"] for row in package_index_rows):
        raise SourceBundlePackagingError("global package scope conservation failed")
    output_record_count = sum(len(rows) for rows in records_by_layer.values())
    if output_record_count + len(gaps) != len(seen_target_ids):
        raise SourceBundlePackagingError("record/gap accounting conservation failed")
    output_historical_records = len(records_by_layer[HISTORICAL_LAYER])
    output_new_records = len(records_by_layer[CURRENT_YEAR_LAYER])
    output_historical_gaps = sum(
        1 for gap in gaps if gap["layer"] == HISTORICAL_LAYER
    )
    output_new_gaps = sum(
        1 for gap in gaps if gap["layer"] == CURRENT_YEAR_LAYER
    )
    if (
        output_historical_records != expected_historical_record_count
        or output_historical_gaps != expected_historical_gap_count
    ):
        raise SourceBundlePackagingError(
            "final historical layer record/gap counts differ from the approved package input: "
            f"expected {expected_historical_record_count}/{expected_historical_gap_count}, "
            f"found {output_historical_records}/{output_historical_gaps}"
        )
    if output_new_records != expected_new_record_count or output_new_gaps != expected_new_gap_count:
        raise SourceBundlePackagingError(
            "final current-year layer record/gap counts differ from the approved package input: "
            f"expected {expected_new_record_count}/{expected_new_gap_count}, "
            f"found {output_new_records}/{output_new_gaps}"
        )
    if output_record_count != expected_input_record_count or len(gaps) != expected_input_gap_count:
        raise SourceBundlePackagingError(
            "final bundle record/gap counts differ from the approved package input: "
            f"expected {expected_input_record_count}/{expected_input_gap_count}, "
            f"found {output_record_count}/{len(gaps)}"
        )
    output_runner_count = sum(row["runners"] for row in regions.values())
    output_result_count = sum(row["results"] for row in regions.values())
    if output_runner_count != expected_runner_count or output_result_count != expected_result_count:
        raise SourceBundlePackagingError(
            "final runner/result counts differ from the approved package input: "
            f"expected {expected_runner_count}/{expected_result_count}, "
            f"found {output_runner_count}/{output_result_count}"
        )

    for rows in records_by_layer.values():
        rows.sort(key=lambda row: row["pending_target"]["target_id"])
    gaps.sort(key=lambda row: row["target_id"])
    package_index_rows.sort(key=lambda row: row["shard_id"])
    evidence_index_rows.sort(key=lambda row: row["shard_id"])
    package_index_payload = {
        "artifact_kind": "historical_race_detail_source_bundle_package_index",
        "schema_version": SCHEMA_VERSION,
        "package_count": len(package_index_rows),
        "excluded_smoke_package_count": len(smoke_package_paths),
        "packages": package_index_rows,
    }
    evidence_index_payload = {
        "artifact_kind": "historical_race_detail_source_bundle_evidence_index",
        "schema_version": SCHEMA_VERSION,
        "packages": evidence_index_rows,
        "request_logs": [request_log_identities[key] for key in sorted(request_log_identities)],
    }
    package_index_raw = _canonical_json_bytes(package_index_payload)
    evidence_index_raw = _canonical_json_bytes(evidence_index_payload)
    gaps_raw = _canonical_jsonl_bytes(gaps)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        (temporary_dir / "package-index.json").write_bytes(package_index_raw)
        (temporary_dir / "evidence-index.json").write_bytes(evidence_index_raw)
        (temporary_dir / "gaps.jsonl").write_bytes(gaps_raw)
        layer_summaries: dict[str, dict[str, Any]] = {}
        total_source_objects = 0
        total_source_bytes = 0
        source_content_sizes: dict[str, int] = {}
        for layer, rows in records_by_layer.items():
            chunks: list[dict[str, Any]] = []
            for chunk_index, offset in enumerate(range(0, len(rows), chunk_size), start=1):
                chunk_rows = rows[offset : offset + chunk_size]
                chunk_id = f"{layer}-{chunk_index:04d}"
                chunk_root_path = f"layers/{layer}/chunks/{chunk_id}"
                candidate_path = f"{chunk_root_path}/candidates.jsonl"
                chunk_output_rows: list[dict[str, Any]] = []
                source_artifacts: list[dict[str, Any]] = []
                chunk_source_bytes = 0
                for row in chunk_rows:
                    target_id = row["pending_target"]["target_id"]
                    source_path = Path(row["_primary_source_path"])
                    if source_path.is_symlink():
                        raise SourceBundlePackagingError(
                            f"target {target_id} primary source must not be a symlink"
                        )
                    source_raw = source_path.read_bytes()
                    primary_identity = row["_primary_cache_identity"]
                    if (
                        _sha256(source_raw) != primary_identity["sha256"]
                        or len(source_raw) != primary_identity["size"]
                    ):
                        raise SourceBundlePackagingError(
                            f"target {target_id} primary source identity changed before copy"
                        )
                    suffix = source_path.suffix
                    if not suffix:
                        raise SourceBundlePackagingError(
                            f"target {target_id} primary source has no original suffix"
                        )
                    source_relative = f"sources/target-{target_id}{suffix}"
                    approved_identity = {
                        "path": source_relative,
                        "sha256": primary_identity["sha256"],
                        "size": primary_identity["size"],
                        "source_url": primary_identity["source_url"],
                        "cached_at": primary_identity["cached_at"],
                        "protected_by": primary_identity["protected_by"],
                    }
                    source_file = temporary_dir / chunk_root_path / source_relative
                    source_file.parent.mkdir(parents=True, exist_ok=True)
                    source_file.write_bytes(source_raw)
                    output_row = {
                        key: value
                        for key, value in row.items()
                        if not key.startswith("_")
                    }
                    output_row["approved_source_cache_identity"] = approved_identity
                    chunk_output_rows.append(output_row)
                    source_artifacts.append(approved_identity)
                    chunk_source_bytes += len(source_raw)
                    total_source_objects += 1
                    total_source_bytes += len(source_raw)
                    source_content_sizes[primary_identity["sha256"]] = len(source_raw)

                candidate_raw = _canonical_jsonl_bytes(chunk_output_rows)
                target_ids = [row["pending_target"]["target_id"] for row in chunk_rows]
                chunk_manifest_path = f"{chunk_root_path}/manifest.json"
                candidate_artifact = _output_identity("candidates.jsonl", candidate_raw)
                chunk_manifest_payload = {
                    "artifact_kind": "historical_race_detail_source_bundle_chunk",
                    "schema_version": SCHEMA_VERSION,
                    "chunk_id": chunk_id,
                    "layer": layer,
                    "cutoff_date": cutoff_date if layer == CURRENT_YEAR_LAYER else None,
                    "target_count": len(chunk_rows),
                    "target_ids": target_ids,
                    "source_object_count": len(source_artifacts),
                    "source_object_bytes": chunk_source_bytes,
                    "candidates": candidate_artifact,
                    "artifacts": [candidate_artifact, *source_artifacts],
                }
                chunk_manifest_raw = _canonical_json_bytes(chunk_manifest_payload)
                candidate_file = temporary_dir / candidate_path
                candidate_file.parent.mkdir(parents=True, exist_ok=True)
                candidate_file.write_bytes(candidate_raw)
                (temporary_dir / chunk_manifest_path).write_bytes(chunk_manifest_raw)
                chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "path": candidate_path,
                        "target_count": len(chunk_rows),
                        "target_ids": target_ids,
                        "source_object_count": len(source_artifacts),
                        "source_object_bytes": chunk_source_bytes,
                        "candidates": _output_identity(candidate_path, candidate_raw),
                        "manifest": _output_identity(chunk_manifest_path, chunk_manifest_raw),
                    }
                )
            layer_summaries[layer] = {
                "record_count": len(rows),
                "gap_count": sum(1 for gap in gaps if gap["layer"] == layer),
                "chunk_count": len(chunks),
                "chunks": chunks,
            }

        actual_historical_chunks = layer_summaries[HISTORICAL_LAYER]["chunk_count"]
        actual_new_chunks = layer_summaries[CURRENT_YEAR_LAYER]["chunk_count"]
        if actual_historical_chunks != expected_historical_chunk_count:
            raise SourceBundlePackagingError(
                "final historical layer chunk count mismatch: "
                f"expected {expected_historical_chunk_count}, found {actual_historical_chunks}"
            )
        if actual_new_chunks != expected_new_chunk_count:
            raise SourceBundlePackagingError(
                "final current-year layer chunk count mismatch: "
                f"expected {expected_new_chunk_count}, found {actual_new_chunks}"
            )

        manifest = {
            "artifact_kind": ARTIFACT_KIND,
            "schema_version": SCHEMA_VERSION,
            "inputs": {
                "v6_manifest": _file_identity(v6_manifest_path, "v6/manifest.json"),
                "v9_manifest": _file_identity(v9_manifest_path, "v9/manifest.json"),
                "v9_remaining_targets": remaining_identity,
                "current_year_manifest": _file_identity(
                    due_manifest_path, "current_year/manifest.json"
                ),
            },
            "source_plan_artifact_sha256": source_plan_sha,
            "approved_inventory_artifact_sha256": approved_inventory_sha,
            "current_year_due": {
                "cutoff_date": cutoff_date,
                "aggregate_manifest_sha256": _sha256(due_manifest_raw),
                "input_record_count": input_new_records,
                "due_record_count": current_year_due_passed,
                "not_due_or_pending_record_count": current_year_due_failed,
            },
            "package_count": len(package_index_rows),
            "scope_count": len(seen_target_ids),
            "record_count": output_record_count,
            "gap_count": len(gaps),
            "accounted_count": output_record_count + len(gaps),
            "source_objects": {
                "count": total_source_objects,
                "bytes": total_source_bytes,
                "unique_content_count": len(source_content_sizes),
                "deduplicated_bytes": sum(source_content_sizes.values()),
            },
            "regions": regions,
            "layers": layer_summaries,
            "validated_counts": {
                "package_count": expected_package_count,
                "scope_count": expected_scope_count,
                "input_record_count": expected_input_record_count,
                "input_gap_count": expected_input_gap_count,
                "historical_record_count": expected_historical_record_count,
                "historical_gap_count": expected_historical_gap_count,
                "historical_chunk_count": expected_historical_chunk_count,
                "current_year_due_record_count": expected_new_record_count,
                "current_year_due_gap_count": expected_new_gap_count,
                "current_year_due_chunk_count": expected_new_chunk_count,
                "runner_count": expected_runner_count,
                "result_count": expected_result_count,
            },
            "outputs": {
                "package-index.json": _output_identity("package-index.json", package_index_raw),
                "evidence-index.json": _output_identity("evidence-index.json", evidence_index_raw),
                "gaps.jsonl": _output_identity("gaps.jsonl", gaps_raw),
            },
            "validations": {
                "v6_full_artifact_list_verified": True,
                "v9_remaining_targets_identity_verified": True,
                "formal_run_package_count_verified": True,
                "smoke_packages_excluded": True,
                "record_cache_objects_verified": True,
                "pending_target_sha_chain_verified": True,
                "inventory_roles_separated": True,
                "current_year_due_gate_applied": True,
                "counts_conserved": True,
                "formal_package_scope_verified": True,
                "input_record_gap_counts_verified": True,
                "final_record_gap_counts_verified": True,
                "layer_counts_and_chunks_verified": True,
                "runner_result_counts_verified": True,
            },
        }
        manifest_raw = _canonical_json_bytes(manifest)
        (temporary_dir / "manifest.json").write_bytes(manifest_raw)
        manifest_sha = _sha256(manifest_raw)
        approval_identities: list[dict[str, Any]] = []
        for layer, summary in layer_summaries.items():
            for chunk in summary["chunks"]:
                approval_path = f"approval-templates/{chunk['chunk_id']}.approval.json"
                approval_raw = _canonical_json_bytes(
                    _approval_template(
                        bundle_manifest_sha256=manifest_sha,
                        layer=layer,
                        cutoff_date=cutoff_date if layer == CURRENT_YEAR_LAYER else None,
                        chunk=chunk,
                    )
                )
                approval_file = temporary_dir / approval_path
                approval_file.parent.mkdir(parents=True, exist_ok=True)
                approval_file.write_bytes(approval_raw)
                approval_identities.append(_output_identity(approval_path, approval_raw))
        bundle_identity = {
            "artifact_kind": "historical_race_detail_source_bundle_identity",
            "schema_version": SCHEMA_VERSION,
            "manifest": _output_identity("manifest.json", manifest_raw),
            "approval_templates": sorted(approval_identities, key=lambda row: row["path"]),
        }
        (temporary_dir / "bundle-identity.json").write_bytes(
            _canonical_json_bytes(bundle_identity)
        )
        verify_source_bundle(temporary_dir)
        os.replace(temporary_dir, output_dir)
    except Exception:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build an immutable, approval-ready historical race detail source bundle."
    )
    parser.add_argument("--v6-root", required=True, type=Path)
    parser.add_argument("--v9-root", required=True, type=Path)
    parser.add_argument("--current-year-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest = package_source_bundle(
            args.v6_root,
            args.v9_root,
            args.current_year_root,
            args.output_dir,
        )
    except SourceBundlePackagingError as exc:
        parser.error(str(exc))
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

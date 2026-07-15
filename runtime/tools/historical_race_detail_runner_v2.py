#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import csv
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import parse_qsl, urlsplit


SCHEMA_VERSION = "2.0"
STAGES = ("discover", "cache", "parse", "validate", "package")
NETWORK_STAGES = frozenset({"discover", "cache"})
TARGET_STATES = frozenset(
    {
        "complete",
        "source_exhausted",
        "terminal_review_gap",
        "cancelled",
        "not_held",
        "retryable_gap",
        "unstarted",
    }
)
REGIONS = frozenset(
    {"japan", "hong_kong", "united_kingdom", "france", "united_states"}
)
ZERO_HASH = "0" * 64
SHA256_RE = re.compile(r"[0-9a-f]{64}", re.IGNORECASE)
SAFE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
APPROVED_UNMATCHED_RUNNER_STATUSES = frozenset(
    {
        "scratched",
        "withdrawn",
        "did_not_start",
        "did_not_finish",
        "disqualified",
        "non_runner",
        "fell",
        "pulled_up",
        "refused",
        "unseated_rider",
        "brought_down",
    }
)
_DETAIL_ADAPTER_MODULE = None


class RunnerV2Error(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_identity(path: Path, *, role: str) -> dict:
    _reject_symlink_components(path, require_exists=True)
    if not path.is_file():
        raise RunnerV2Error(f"identity is not a regular file: {path}")
    body = path.read_bytes()
    return {
        "role": role,
        "path": str(path),
        "size": len(body),
        "sha256": _sha256_bytes(body),
    }


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _reject_symlink_components(path: Path, *, require_exists: bool) -> None:
    if not path.is_absolute():
        raise RunnerV2Error(f"path must be absolute: {path}")
    if ".." in path.parts:
        raise RunnerV2Error(f"parent path traversal is forbidden: {path}")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise RunnerV2Error(f"symlink path is forbidden: {current}")
        if not current.exists():
            if require_exists:
                raise RunnerV2Error(f"path does not exist: {current}")
            break


def _require_within(path: Path, root: Path, *, require_exists: bool) -> None:
    _reject_symlink_components(root, require_exists=True)
    _reject_symlink_components(path, require_exists=require_exists)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RunnerV2Error(f"path escapes approved root {root}: {path}") from exc


def _assert_no_runtime_escape(value: object, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key).casefold().replace("-", "_")
            location = ".".join((*path, str(raw_key)))
            if key in {"argv", "command", "commands", "database_url", "db_url"}:
                raise RunnerV2Error(f"forbidden runtime field: {location}")
            if any(token in key for token in ("postgres", "docker_sock", "compose_file", "env_file")):
                raise RunnerV2Error(f"forbidden runtime field: {location}")
            if key in {"apply", "database", "shell"} and item is not False:
                raise RunnerV2Error(f"forbidden runtime capability: {location}")
            _assert_no_runtime_escape(item, (*path, str(raw_key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_runtime_escape(item, (*path, str(index)))


def _validate_root(path: str | Path, *, label: str) -> Path:
    root = Path(path)
    _reject_symlink_components(root, require_exists=True)
    if not root.is_dir():
        raise RunnerV2Error(f"{label} root is not a directory: {root}")
    return root


def validate_descriptor(
    descriptor: dict,
    *,
    descriptor_path: str | Path,
    repo_root: str | Path,
    plan_root: str | Path,
    run_root: str | Path,
    host_lock_root: str | Path,
) -> dict:
    if not isinstance(descriptor, dict):
        raise RunnerV2Error("descriptor must be an object")
    normalized = copy.deepcopy(descriptor)
    _assert_no_runtime_escape(normalized)
    if normalized.get("schema_version") != SCHEMA_VERSION:
        raise RunnerV2Error("descriptor schema_version must be 2.0")
    if normalized.get("artifact_kind") != "historical_race_detail_shard_descriptor":
        raise RunnerV2Error("descriptor artifact_kind is invalid")
    if normalized.get("stages") != list(STAGES):
        raise RunnerV2Error("descriptor stages are not the fixed v2 pipeline")
    if normalized.get("region") not in REGIONS:
        raise RunnerV2Error("descriptor region is invalid")
    for key in ("plan_id", "shard_id"):
        if not isinstance(normalized.get(key), str) or not SAFE_NAME_RE.fullmatch(normalized[key]):
            raise RunnerV2Error(f"descriptor {key} is invalid")

    permissions = normalized.get("permissions")
    if not isinstance(permissions, dict) or any(
        permissions.get(key) is not False for key in ("database", "apply", "shell")
    ):
        raise RunnerV2Error("database, apply, and shell permissions must be false")
    if permissions.get("network_stages") != list(STAGES[:2]):
        raise RunnerV2Error("network is allowed only for discover and cache")

    roots = {
        "repo": _validate_root(repo_root, label="repo"),
        "plan": _validate_root(plan_root, label="plan"),
        "run": _validate_root(run_root, label="run"),
        "host_lock": _validate_root(host_lock_root, label="host_lock"),
    }
    descriptor_file = Path(descriptor_path)
    _require_within(descriptor_file, roots["plan"], require_exists=True)
    if not descriptor_file.is_file():
        raise RunnerV2Error("descriptor path is not a regular file")
    try:
        descriptor_on_disk = json.loads(descriptor_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerV2Error("descriptor file is unreadable") from exc
    if descriptor_on_disk != descriptor:
        raise RunnerV2Error("descriptor value does not match the approved descriptor file")

    mounts = normalized.get("mounts")
    if not isinstance(mounts, list) or len(mounts) != 4:
        raise RunnerV2Error("descriptor must contain exactly four mounts")
    mount_by_role: dict[str, dict] = {}
    for mount in mounts:
        if not isinstance(mount, dict) or set(mount) != {"role", "path", "mode"}:
            raise RunnerV2Error("mount entry is invalid")
        role = mount.get("role")
        if role in mount_by_role or role not in roots:
            raise RunnerV2Error("mount role is duplicate or unsupported")
        expected_mode = "ro" if role in {"repo", "plan"} else "rw"
        if mount.get("mode") != expected_mode or Path(str(mount.get("path"))) != roots[role]:
            raise RunnerV2Error(f"mount contract mismatch for {role}")
        mount_by_role[role] = mount
    if set(mount_by_role) != set(roots):
        raise RunnerV2Error("mount roles are incomplete")

    identity_roots = {
        "plan": roots["plan"],
        "events_csv": roots["plan"],
        "source_fragment": roots["plan"],
        "recipe": roots["plan"],
        "tool": roots["repo"],
    }
    identities = normalized.get("identities")
    if not isinstance(identities, list):
        raise RunnerV2Error("descriptor identities must be a list")
    seen_roles: set[str] = set()
    for identity in identities:
        if not isinstance(identity, dict):
            raise RunnerV2Error("descriptor identity is invalid")
        role = identity.get("role")
        if role not in identity_roots or role in seen_roles:
            raise RunnerV2Error("identity role is duplicate or unsupported")
        path = Path(str(identity.get("path") or ""))
        _require_within(path, identity_roots[role], require_exists=True)
        actual = _file_identity(path, role=role)
        if (
            isinstance(identity.get("size"), bool)
            or not isinstance(identity.get("size"), int)
            or identity.get("size") != actual["size"]
            or identity.get("sha256") != actual["sha256"]
        ):
            raise RunnerV2Error(f"identity changed for {role}: {path}")
        seen_roles.add(role)
    if seen_roles != set(identity_roots):
        raise RunnerV2Error("descriptor immutable identities are incomplete")

    outputs = normalized.get("outputs")
    output_roots = {
        "cache_root": roots["run"],
        "parse_root": roots["run"],
        "package_root": roots["run"],
        "checkpoint": roots["run"],
        "request_log": roots["run"],
        "host_last_start": roots["host_lock"],
        "host_append_log": roots["host_lock"],
    }
    if not isinstance(outputs, dict) or set(outputs) != set(output_roots):
        raise RunnerV2Error("descriptor outputs are incomplete")
    for key, root in output_roots.items():
        _require_within(Path(str(outputs[key])), root, require_exists=False)

    image = normalized.get("image")
    if (
        not isinstance(image, dict)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(image.get("digest") or ""))
        or not re.fullmatch(r"[0-9a-f]{40}", str(image.get("revision") or ""))
    ):
        raise RunnerV2Error("image identity is invalid")

    validate_request_policy(normalized.get("request_policy"))
    recipe = normalized.get("recipe")
    if not isinstance(recipe, dict) or recipe.get("region") != normalized["region"]:
        raise RunnerV2Error("descriptor recipe does not match its region")
    chain = recipe.get("source_chain")
    fallback = recipe.get("fallback_sources")
    if not isinstance(chain, list) or not chain or len(chain) != len(set(chain)):
        raise RunnerV2Error("descriptor source chain is invalid")
    if not isinstance(fallback, list) or not set(fallback) <= set(chain):
        raise RunnerV2Error("descriptor fallback sources are invalid")

    targets = normalized.get("targets")
    if not isinstance(targets, list) or not targets:
        raise RunnerV2Error("descriptor targets must be non-empty")
    target_ids: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise RunnerV2Error("descriptor target is invalid")
        target_id = str(target.get("target_id") or "")
        if not target_id or target_id in target_ids or not _is_sha256(target.get("target_sha256")):
            raise RunnerV2Error("descriptor target identity is invalid")
        target_ids.add(target_id)
    adapter_inputs = normalized.get("adapter_inputs")
    if adapter_inputs is not None:
        if not isinstance(adapter_inputs, dict) or set(adapter_inputs) != {
            "events_csv",
            "source_fragment",
        }:
            raise RunnerV2Error("structured adapter inputs are invalid")
        identity_paths = {
            row["role"]: Path(row["path"])
            for row in identities
            if row.get("role") in {"events_csv", "source_fragment"}
        }
        for role, raw_path in adapter_inputs.items():
            path = Path(str(raw_path))
            _require_within(path, roots["plan"], require_exists=True)
            if identity_paths.get(role) != path:
                raise RunnerV2Error(f"adapter input is not bound to descriptor identity: {role}")
    return normalized


def _artifact_identity(value: object, *, label: str) -> dict:
    if not isinstance(value, dict):
        raise RunnerV2Error(f"{label} identity must be an object")
    path = str(value.get("path") or "")
    size = value.get("size")
    if (
        (path and (Path(path).is_absolute() or ".." in Path(path).parts))
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 0
        or not _is_sha256(value.get("sha256"))
    ):
        raise RunnerV2Error(f"{label} identity is invalid")
    normalized = {"size": size, "sha256": value["sha256"]}
    if path:
        normalized["path"] = path
    return normalized


def hash_v1_target_set(targets: Iterable[dict]) -> str:
    normalized = []
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise RunnerV2Error("v1 target identity is invalid")
        target_id = str(target.get("target_id") or "")
        target_sha = target.get("target_sha256")
        if not target_id or target_id in seen or not _is_sha256(target_sha):
            raise RunnerV2Error("v1 target identity is invalid")
        seen.add(target_id)
        normalized.append({"target_id": target_id, "target_sha256": target_sha})
    if not normalized:
        raise RunnerV2Error("v1 target set cannot be empty")
    return _sha256_bytes(_canonical_bytes(sorted(normalized, key=lambda row: row["target_id"])))


def _verified_evidence_file(
    identity: object,
    *,
    evidence_root: Path,
    label: str,
) -> tuple[dict, bytes]:
    normalized = _artifact_identity(identity, label=label)
    relative = str(normalized.get("path") or "")
    if not relative:
        raise RunnerV2Error(f"{label} identity requires a relative path")
    path = evidence_root / relative
    _require_within(path, evidence_root, require_exists=True)
    if not path.is_file():
        raise RunnerV2Error(f"{label} is not a regular file")
    body = path.read_bytes()
    if len(body) != normalized["size"] or _sha256_bytes(body) != normalized["sha256"]:
        raise RunnerV2Error(f"{label} file identity changed")
    return normalized, body


def _evidence_json(body: bytes, *, label: str) -> dict:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerV2Error(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise RunnerV2Error(f"{label} must contain an object")
    return value


def migrate_v1_progress(
    source: dict,
    descriptor: dict,
    *,
    evidence_root: str | Path,
) -> dict:
    if not isinstance(source, dict) or source.get("schema_version") != "1.0":
        raise RunnerV2Error("only v1 progress can be migrated")
    if not isinstance(descriptor, dict) or descriptor.get("schema_version") != SCHEMA_VERSION:
        raise RunnerV2Error("v2 descriptor is required for migration")
    if source.get("region") != descriptor.get("region"):
        raise RunnerV2Error("migration region mismatch")
    root = Path(evidence_root)
    _reject_symlink_components(root, require_exists=True)
    if not root.is_dir():
        raise RunnerV2Error("v1 evidence root is not a directory")
    source_identity = descriptor.get("v1_source_identity")
    if not isinstance(source_identity, dict):
        raise RunnerV2Error("descriptor v1 source identity is required")
    source_manifest, source_manifest_body = _verified_evidence_file(
        source.get("plan_manifest_identity"),
        evidence_root=root,
        label="v1 plan manifest",
    )
    expected_manifest = _artifact_identity(
        source_identity.get("plan_manifest_identity"),
        label="descriptor v1 plan manifest",
    )
    if (
        source_identity.get("plan_id") != source.get("plan_id")
        or source_identity.get("shard_id") != source.get("shard_id")
        or expected_manifest != source_manifest
    ):
        raise RunnerV2Error("v1 plan or shard identity does not match the descriptor")
    source_targets = source.get("targets")
    if not isinstance(source_targets, list):
        raise RunnerV2Error("v1 target identities are required")
    target_set_sha = hash_v1_target_set(source_targets)
    if source_identity.get("target_set_sha256") != target_set_sha:
        raise RunnerV2Error("v1 target set identity does not match the descriptor")
    source_manifest_payload = _evidence_json(source_manifest_body, label="v1 plan manifest")
    if (
        source_manifest_payload.get("plan_id") != source.get("plan_id")
        or source_manifest_payload.get("shard_id") != source.get("shard_id")
        or source_manifest_payload.get("target_set_sha256") != target_set_sha
    ):
        raise RunnerV2Error("v1 plan manifest content is not bound to the source target set")
    source_target_by_id = {str(row["target_id"]): row for row in source_targets}
    descriptor_targets = descriptor.get("targets")
    if not isinstance(descriptor_targets, list):
        raise RunnerV2Error("v2 descriptor target identities are required")
    descriptor_target_by_id = {
        str(row.get("target_id") or ""): row
        for row in descriptor_targets
        if isinstance(row, dict)
    }
    if len(descriptor_target_by_id) != len(descriptor_targets) or set(descriptor_target_by_id) != set(
        source_target_by_id
    ):
        raise RunnerV2Error("v1 and v2 target scopes differ")
    for target_id, source_target in source_target_by_id.items():
        if descriptor_target_by_id[target_id].get("target_sha256") != source_target.get("target_sha256"):
            raise RunnerV2Error(f"target identity changed across migration: {target_id}")
    complete = [str(item) for item in source.get("complete_target_ids") or []]
    gaps = [str(item) for item in source.get("gap_target_ids") or []]
    if (
        len(set((*complete, *gaps))) != len(complete) + len(gaps)
        or set((*complete, *gaps)) != set(source_target_by_id)
    ):
        raise RunnerV2Error("v1 progress target IDs are not mutually exclusive")
    cache_entries = copy.deepcopy(source.get("cache_entries") or [])
    seen_urls: set[str] = set()
    for entry in cache_entries:
        if (
            not isinstance(entry, dict)
            or not str(entry.get("url") or "")
            or entry["url"] in seen_urls
            or not isinstance(entry.get("size"), int)
            or entry["size"] < 0
            or not _is_sha256(entry.get("sha256"))
        ):
            raise RunnerV2Error("v1 cache identity is invalid")
        seen_urls.add(entry["url"])
    target_states = []
    seen_complete_urls: set[str] = set()
    for target_id in complete:
        source_target = source_target_by_id[target_id]
        evidence, evidence_body = _verified_evidence_file(
            source_target.get("completion_evidence_identity"),
            evidence_root=root,
            label=f"v1 completion evidence for {target_id}",
        )
        evidence_payload = _evidence_json(
            evidence_body,
            label=f"v1 completion evidence for {target_id}",
        )
        if (
            evidence_payload.get("schema_version") != "1.0"
            or evidence_payload.get("plan_id") != source.get("plan_id")
            or evidence_payload.get("shard_id") != source.get("shard_id")
            or str(evidence_payload.get("target_id") or "") != target_id
            or evidence_payload.get("target_sha256") != source_target.get("target_sha256")
        ):
            raise RunnerV2Error(f"v1 completion evidence content is not bound to target {target_id}")
        candidate = evidence_payload.get("candidate")
        if not isinstance(candidate, dict) or str(candidate.get("target_id") or "") != target_id:
            raise RunnerV2Error(f"v1 completion candidate is not bound to target {target_id}")
        candidate_target_sha = candidate.get("target_sha256", evidence_payload["target_sha256"])
        if candidate_target_sha != evidence_payload["target_sha256"]:
            raise RunnerV2Error(f"v1 completion candidate target SHA differs for {target_id}")
        candidate = copy.deepcopy(candidate)
        candidate["target_id"] = target_id
        candidate["target_sha256"] = candidate_target_sha
        validate_complete_target(candidate, seen_source_urls=seen_complete_urls)
        seen_complete_urls.add(candidate["event"]["source_url"])
        target_states.append(
            {
                "target_id": target_id,
                "target_sha256": source_target["target_sha256"],
                "state": "complete",
                "source_identity": {
                    "plan_id": source["plan_id"],
                    "shard_id": source["shard_id"],
                    "plan_manifest_identity": source_manifest,
                    "target_set_sha256": target_set_sha,
                    "completion_evidence_identity": evidence,
                },
            }
        )
    target_states.extend(
        {
            "target_id": target_id,
            "target_sha256": source_target_by_id[target_id]["target_sha256"],
            "state": "retryable_gap",
            "reason_code": "fallback_pending",
            "source_identity": {
                "plan_id": source["plan_id"],
                "shard_id": source["shard_id"],
                "plan_manifest_identity": source_manifest,
                "target_set_sha256": target_set_sha,
            },
        }
        for target_id in gaps
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_id": descriptor.get("plan_id"),
        "shard_id": descriptor.get("shard_id"),
        "region": descriptor.get("region"),
        "migration": {
            "source_schema_version": "1.0",
            "source_plan_id": source.get("plan_id"),
            "source_shard_id": source.get("shard_id"),
            "source_plan_manifest_identity": source_manifest,
            "source_target_set_sha256": target_set_sha,
        },
        "target_states": target_states,
        "cache_entries": cache_entries,
    }


def validate_progress(scope: Iterable[str], rows: Iterable[dict]) -> dict:
    target_scope = [str(item) for item in scope]
    if not target_scope or len(set(target_scope)) != len(target_scope):
        raise RunnerV2Error("target scope must be non-empty and unique")
    scope_set = set(target_scope)
    state_by_target: dict[str, str] = {}
    normalized_rows: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            raise RunnerV2Error("target state row must be an object")
        target_id = str(row.get("target_id") or "")
        state = row.get("state")
        if target_id not in scope_set or target_id in state_by_target or state not in TARGET_STATES:
            raise RunnerV2Error("target states are invalid or not mutually exclusive")
        state_by_target[target_id] = state
        normalized_rows.append(copy.deepcopy(row))
    for target_id in target_scope:
        if target_id not in state_by_target:
            state_by_target[target_id] = "unstarted"
            normalized_rows.append({"target_id": target_id, "state": "unstarted"})
    counts = Counter(state_by_target.values())
    complete_counts = {state: counts.get(state, 0) for state in sorted(TARGET_STATES)}
    if sum(complete_counts.values()) != len(target_scope):
        raise RunnerV2Error("global target denominator was not conserved")
    return {
        "scope_count": len(target_scope),
        "counts": complete_counts,
        "target_states": normalized_rows,
    }


def _required_text(mapping: Mapping, key: str, *, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RunnerV2Error(f"{label} requires {key}")
    return value


def _normalize_horse_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _row_source_identity(row: Mapping) -> str:
    refs = row.get("source_refs")
    if not isinstance(refs, dict):
        return ""
    cache = refs.get("source_cache_identity")
    if isinstance(cache, dict) and _is_sha256(cache.get("sha256")):
        return f"cache:{cache['sha256']}"
    for key in ("primary", "source_url"):
        value = refs.get(key)
        if isinstance(value, str) and value:
            return f"url:{value}"
    return ""


def _horse_match_key(row: Mapping, *, label: str) -> tuple[str, ...]:
    number = unicodedata.normalize("NFKC", str(row.get("horse_number") or "")).strip().casefold()
    name = _required_text(row, "horse_name", label=label)
    if number:
        return ("number", number)
    normalized_name = _normalize_horse_text(name)
    source_identity = _row_source_identity(row)
    if not normalized_name or not source_identity:
        raise RunnerV2Error(f"{label} without horse_number requires normalized name and source identity")
    return ("name_source", normalized_name, source_identity)


def validate_complete_target(candidate: dict, *, seen_source_urls: set[str]) -> dict:
    if not isinstance(candidate, dict) or candidate.get("status") != "complete":
        raise RunnerV2Error("complete target candidate is invalid")
    normalized = copy.deepcopy(candidate)
    target_id = _required_text(normalized, "target_id", label="candidate")
    event = normalized.get("event")
    if not isinstance(event, dict):
        raise RunnerV2Error("complete target event is missing")
    for field in ("date", "course", "distance", "source_url"):
        _required_text(event, field, label="event")
    source_url = event["source_url"]
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RunnerV2Error("complete target source URL is invalid")
    if source_url in seen_source_urls:
        raise RunnerV2Error("source URL is reused by more than one target")

    mappings = normalized.get("source_mappings")
    if not isinstance(mappings, list) or not mappings:
        raise RunnerV2Error("complete target has no source mapping")
    mapped_urls: set[str] = set()
    for row in mappings:
        if not isinstance(row, dict):
            raise RunnerV2Error("complete target source mapping is invalid")
        mapped_target = str(row.get("target_id") or "")
        mapped_provider = str(row.get("provider") or "")
        mapped_url = str(row.get("source_url") or "")
        mapped_parsed = urlsplit(mapped_url)
        if (
            mapped_target != target_id
            or not mapped_provider
            or mapped_parsed.scheme != "https"
            or not mapped_parsed.hostname
            or mapped_url in mapped_urls
        ):
            raise RunnerV2Error("complete target source mapping is invalid")
        mapped_urls.add(mapped_url)
    if source_url not in mapped_urls:
        raise RunnerV2Error("complete target source mapping is incomplete")

    runners = normalized.get("runners")
    results = normalized.get("results")
    winner = normalized.get("winner")
    if not isinstance(runners, list) or not runners or not isinstance(results, list) or not results:
        raise RunnerV2Error("complete target must contain runners and results")
    runner_numbers: set[str] = set()
    runner_by_number: dict[str, tuple[int, dict]] = {}
    runner_by_name_source: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    for runner_index, row in enumerate(runners):
        if not isinstance(row, dict):
            raise RunnerV2Error("runner row is invalid")
        key = _horse_match_key(row, label="runner")
        number = unicodedata.normalize("NFKC", str(row.get("horse_number") or "")).strip().casefold()
        if number and number in runner_numbers:
            raise RunnerV2Error("runner horse numbers must be unique")
        fallback_key = (key[1], key[2]) if key[0] == "name_source" else None
        if not number and fallback_key in runner_by_name_source:
            raise RunnerV2Error("runner identities must be unique")
        if number:
            runner_numbers.add(number)
            runner_by_number[number] = (runner_index, row)
        source_identity = _row_source_identity(row)
        normalized_name = _normalize_horse_text(row.get("horse_name"))
        if source_identity and normalized_name:
            runner_by_name_source.setdefault((normalized_name, source_identity), []).append(
                (runner_index, row)
            )
    positions: set[int] = set()
    result_numbers: set[str] = set()
    matched_runner_indexes: set[int] = set()
    winner_row: dict | None = None
    for row in results:
        if not isinstance(row, dict):
            raise RunnerV2Error("result row is invalid")
        position = row.get("finish_position")
        _horse_match_key(row, label="result")
        number = unicodedata.normalize("NFKC", str(row.get("horse_number") or "")).strip().casefold()
        name = _required_text(row, "horse_name", label="result")
        if not isinstance(position, int) or position <= 0 or position in positions:
            raise RunnerV2Error("finish positions must be unique positive integers")
        match = runner_by_number.get(number) if number else None
        if match is None:
            source_identity = _row_source_identity(row)
            fallback_matches = runner_by_name_source.get(
                (_normalize_horse_text(name), source_identity),
                [],
            )
            if len(fallback_matches) == 1:
                match = fallback_matches[0]
        runner_index, runner = match if match is not None else (-1, None)
        if (
            (number and number in result_numbers)
            or runner_index in matched_runner_indexes
            or runner is None
            or _normalize_horse_text(runner.get("horse_name")) != _normalize_horse_text(name)
        ):
            raise RunnerV2Error("result horse mapping is invalid")
        positions.add(position)
        matched_runner_indexes.add(runner_index)
        if number:
            result_numbers.add(number)
        if position == 1:
            winner_row = row
    for runner_index, runner in enumerate(runners):
        if runner_index in matched_runner_indexes:
            continue
        status = str(runner.get("running_status") or runner.get("status") or "").strip().casefold()
        if status not in APPROVED_UNMATCHED_RUNNER_STATUSES:
            raise RunnerV2Error("runner without a result lacks an approved exception status")
    if not isinstance(winner, dict) or winner_row is None:
        raise RunnerV2Error("complete target winner is missing")
    if positions != set(range(1, len(results) + 1)):
        raise RunnerV2Error("result positions are incomplete")
    if (
        _normalize_horse_text(winner.get("horse_number"))
        != _normalize_horse_text(winner_row.get("horse_number"))
        or _normalize_horse_text(winner.get("horse_name"))
        != _normalize_horse_text(winner_row.get("horse_name"))
    ):
        raise RunnerV2Error("winner does not match first-place result")
    return normalized


def validate_package(scope: Iterable[str], candidates: Iterable[dict]) -> dict:
    target_scope = [str(item) for item in scope]
    if not target_scope or len(target_scope) != len(set(target_scope)):
        raise RunnerV2Error("package scope must be non-empty and unique")
    candidate_rows = list(candidates)
    if not candidate_rows:
        raise RunnerV2Error("zero-row detail package is forbidden")
    scope_set = set(target_scope)
    seen_targets: set[str] = set()
    seen_urls: set[str] = set()
    normalized = []
    for candidate in candidate_rows:
        row = validate_complete_target(candidate, seen_source_urls=seen_urls)
        target_id = row["target_id"]
        if target_id not in scope_set or target_id in seen_targets:
            raise RunnerV2Error("package target is outside scope or duplicated")
        seen_targets.add(target_id)
        seen_urls.add(row["event"]["source_url"])
        normalized.append(row)
    return {
        "scope_count": len(target_scope),
        "complete_count": len(normalized),
        "candidates": normalized,
    }


def plan_recovery(
    checkpoint: dict,
    *,
    current_parser_sha256: str,
    cache_identities: Mapping[str, dict],
) -> dict:
    if not isinstance(checkpoint, dict) or not _is_sha256(current_parser_sha256):
        raise RunnerV2Error("recovery checkpoint or parser identity is invalid")
    requests = checkpoint.get("requests")
    if not isinstance(requests, list):
        raise RunnerV2Error("recovery checkpoint request ledger is invalid")
    network_urls: list[str] = []
    reused_urls: list[str] = []
    seen_urls: set[str] = set()
    for request in requests:
        if not isinstance(request, dict):
            raise RunnerV2Error("checkpoint request row is invalid")
        url = str(request.get("url") or "")
        if not url or url in seen_urls:
            raise RunnerV2Error("checkpoint request URLs must be non-empty and unique")
        seen_urls.add(url)
        expected = request.get("cache_identity")
        current = cache_identities.get(url)
        verified = (
            request.get("status") == "succeeded"
            and isinstance(expected, dict)
            and isinstance(current, dict)
            and expected.get("size") == current.get("size")
            and expected.get("sha256") == current.get("sha256")
            and _is_sha256(expected.get("sha256"))
        )
        (reused_urls if verified else network_urls).append(url)
    parser_changed = checkpoint.get("parser_sha256") != current_parser_sha256
    invalidated = list(STAGES[2:]) if parser_changed or network_urls else []
    if network_urls:
        resume_from = "cache"
    elif parser_changed:
        resume_from = "parse"
    else:
        stages = checkpoint.get("stages") if isinstance(checkpoint.get("stages"), dict) else {}
        resume_from = next((stage for stage in STAGES if stages.get(stage) != "complete"), "complete")
    return {
        "resume_from": resume_from,
        "network_urls": network_urls,
        "reused_cache_urls": reused_urls,
        "invalidated_stages": invalidated,
    }


def _atomic_write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def reserve_host_start(
    state_path: Path,
    append_log_path: Path,
    *,
    host: str,
    shard_id: str,
    minimum_interval_seconds: float,
) -> float:
    state = Path(state_path)
    log = Path(append_log_path)
    if not re.fullmatch(r"[a-z0-9.-]+", host) or not SAFE_NAME_RE.fullmatch(shard_id):
        raise RunnerV2Error("host limiter identity is invalid")
    if minimum_interval_seconds < 0:
        raise RunnerV2Error("host limiter interval cannot be negative")
    if state.parent != log.parent:
        raise RunnerV2Error("shared host state and log must have the same root")
    state.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(state.parent, require_exists=True)
    for path in (state, log):
        if path.is_symlink():
            raise RunnerV2Error(f"symlink host limiter artifact is forbidden: {path}")
    lock_path = state.with_suffix(state.suffix + ".lock")
    if lock_path.is_symlink():
        raise RunnerV2Error("symlink host limiter lock is forbidden")
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        previous = 0.0
        request_count = 0
        if state.exists():
            try:
                payload = json.loads(state.read_text(encoding="utf-8"))
                previous = float(payload.get("last_start_epoch") or 0.0)
                request_count = int(payload.get("request_count") or 0)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise RunnerV2Error(f"shared host state is corrupt: {state}") from exc
        remaining = float(minimum_interval_seconds) - (time.time() - previous)
        if remaining > 0:
            time.sleep(remaining)
        started_epoch = time.time()
        row = {
            "host": host,
            "shard_id": shard_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "started_at_epoch": started_epoch,
            "minimum_interval_seconds": float(minimum_interval_seconds),
        }
        _atomic_write_json(
            state,
            {
                "schema_version": SCHEMA_VERSION,
                "host": host,
                "request_count": request_count + 1,
                "last_start_epoch": started_epoch,
                "last_shard_id": shard_id,
            },
        )
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return started_epoch


def _descriptor_identity(descriptor: dict) -> dict:
    body = _canonical_bytes(descriptor)
    return {
        "role": "descriptor",
        "size": len(body),
        "sha256": _sha256_bytes(body),
    }


def build_checkpoint_identity(
    descriptor: dict,
    *,
    artifacts: Mapping[str, str | Path],
    shared_host_state_path: str | Path,
    actual_image_digest: str | None = None,
    actual_image_revision: str | None = None,
) -> dict:
    if not isinstance(descriptor, dict):
        raise RunnerV2Error("checkpoint descriptor is invalid")
    identities: list[dict] = []
    for identity in descriptor.get("identities") or []:
        if not isinstance(identity, dict) or not isinstance(identity.get("role"), str):
            raise RunnerV2Error("checkpoint input identity is invalid")
        identities.append(_file_identity(Path(str(identity.get("path") or "")), role=identity["role"]))
    identities.append(_descriptor_identity(descriptor))
    image = descriptor.get("image")
    if not isinstance(image, dict):
        raise RunnerV2Error("checkpoint image identity is invalid")
    identities.append(
        {
            "role": "image",
            "digest": actual_image_digest or image.get("digest"),
            "revision": actual_image_revision or image.get("revision"),
        }
    )
    for role, raw_path in sorted(artifacts.items()):
        if not SAFE_NAME_RE.fullmatch(str(role)):
            raise RunnerV2Error(f"unsupported checkpoint artifact role: {role}")
        identities.append(_file_identity(Path(raw_path), role=role))
    roles = [row["role"] for row in identities]
    if len(roles) != len(set(roles)):
        raise RunnerV2Error("checkpoint identity roles must be unique")
    shared = Path(shared_host_state_path)
    if shared.is_symlink():
        raise RunnerV2Error("shared host state cannot be a symlink")
    return {
        "schema_version": SCHEMA_VERSION,
        "identities": sorted(identities, key=lambda row: row["role"]),
        "excluded_mutable_artifacts": [str(shared)],
    }


def checkpoint_matches(
    checkpoint: dict,
    descriptor: dict,
    *,
    artifacts: Mapping[str, str | Path],
    shared_host_state_path: str | Path,
) -> bool:
    try:
        current = build_checkpoint_identity(
            descriptor,
            artifacts=artifacts,
            shared_host_state_path=shared_host_state_path,
        )
    except (OSError, RunnerV2Error):
        return False
    return (
        isinstance(checkpoint, dict)
        and checkpoint.get("schema_version") == SCHEMA_VERSION
        and checkpoint.get("identities") == current["identities"]
    )


def validate_runtime_image(
    descriptor: dict,
    *,
    actual_image_digest: str,
    actual_image_revision: str,
) -> dict:
    image = descriptor.get("image") if isinstance(descriptor, dict) else None
    if not isinstance(image, dict):
        raise RunnerV2Error("descriptor image identity is missing")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(actual_image_digest or "")):
        raise RunnerV2Error("actual image digest is invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", str(actual_image_revision or "")):
        raise RunnerV2Error("actual image revision is invalid")
    if image.get("digest") != actual_image_digest:
        raise RunnerV2Error("actual image digest mismatch")
    if image.get("revision") != actual_image_revision:
        raise RunnerV2Error("actual image revision mismatch")
    return {"digest": actual_image_digest, "revision": actual_image_revision}


def _read_stage_artifact(path: Path, *, expected_stage: str) -> dict:
    _reject_symlink_components(path, require_exists=True)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerV2Error(f"prior {expected_stage} stage artifact is unreadable") from exc
    if not isinstance(value, dict) or value.get("stage") != expected_stage:
        raise RunnerV2Error(f"prior {expected_stage} stage artifact is invalid")
    return value


def _detail_adapter_module():
    global _DETAIL_ADAPTER_MODULE
    if _DETAIL_ADAPTER_MODULE is not None:
        return _DETAIL_ADAPTER_MODULE
    path = Path(__file__).with_name("historical_race_detail_adapters.py")
    spec = importlib.util.spec_from_file_location("historical_race_detail_adapters_v2_runtime", path)
    if spec is None or spec.loader is None:
        raise RunnerV2Error("historical detail adapter module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        raise RunnerV2Error("historical detail adapter dependencies are unavailable") from exc
    finally:
        sys.path.pop(0)
    _DETAIL_ADAPTER_MODULE = module
    return module


def get_adapter_spec(region: str, stage: str) -> dict:
    try:
        return _detail_adapter_module().get_adapter_spec(region, stage)
    except RuntimeError as exc:
        raise RunnerV2Error(str(exc)) from exc


def _event_rows(path: Path) -> dict[tuple[int, str], dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {(int(row["year"]), str(row["slug"])): row for row in rows}


def _distance_for_validation(event_row: dict, parsed: dict) -> tuple[str, dict]:
    event_distance = str(event_row.get("distance") or event_row.get("distance_text") or "").strip()
    metadata = parsed.get("metadata")
    parsed_distance = (
        str(metadata.get("distance_text") or "").strip() if isinstance(metadata, dict) else ""
    )
    if event_distance and parsed_distance:
        event_comparison = " ".join(unicodedata.normalize("NFKC", event_distance).casefold().split())
        parsed_comparison = " ".join(unicodedata.normalize("NFKC", parsed_distance).casefold().split())
        if event_comparison != parsed_comparison:
            raise RunnerV2Error("event and parsed metadata distance conflict")
    distance = event_distance or parsed_distance
    source = "event_csv.distance_text" if event_distance else "parsed.metadata.distance_text"
    return distance, {
        "source": source,
        "original_text": distance,
        "source_url": str(parsed.get("source_url") or ""),
    }


def _validation_gap_reason(exc: RunnerV2Error, *, runners: list, results: list) -> str:
    if (
        len(results) < len(runners)
        and str(exc) == "runner without a result lacks an approved exception status"
    ):
        return "source_result_truncated"
    return "validation_failed"


def _validate_parsed_stage(descriptor: dict, *, parse_artifact: dict, run_root: Path) -> dict:
    adapters = _detail_adapter_module()
    candidate_path = Path(parse_artifact["candidate_jsonl"])
    parse_gap_path = Path(parse_artifact["parse_gap_json"])
    event_path = Path(descriptor["adapter_inputs"]["events_csv"])
    events = _event_rows(event_path)
    validated = []
    validated_package_rows = []
    validation_gaps = []
    seen_urls: set[str] = set()
    seen_targets: set[str] = set()
    candidate_artifact_identity = _file_identity(candidate_path, role="parsed_candidates")
    event_identity = _file_identity(event_path, role="events_csv")
    _file_identity(parse_gap_path, role="parse_gaps")
    for parsed in adapters.read_candidates(candidate_path):
        event_row = events.get((int(parsed.get("year") or 0), str(parsed.get("slug") or "")))
        if event_row is None:
            raise RunnerV2Error("parsed candidate is outside structured event input")
        target_id = str(event_row["target_id"])
        if target_id in seen_targets:
            raise RunnerV2Error("parsed candidate target is duplicated")
        seen_targets.add(target_id)
        modules = parsed.get("modules") or {}
        runners = ((modules.get("runners") or {}).get("items")) or []
        results = ((modules.get("results") or {}).get("items")) or []
        source_url = str(parsed.get("source_url") or "")
        try:
            first = next((row for row in results if row.get("finish_position") == 1), None)
            distance, distance_provenance = _distance_for_validation(event_row, parsed)
            candidate = {
                "target_id": target_id,
                "status": "complete",
                "event": {
                    "date": event_row.get("date") or event_row.get("local_date") or "",
                    "course": event_row.get("course") or event_row.get("racecourse") or "",
                    "distance": distance,
                    "distance_provenance": distance_provenance,
                    "source_url": parsed.get("source_url"),
                },
                "source_mappings": [
                    {
                        "provider": parsed.get("source_name"),
                        "source_url": parsed.get("source_url"),
                        "target_id": target_id,
                    }
                ],
                "runners": runners,
                "results": results,
                "winner": (
                    {
                        "horse_number": first.get("horse_number") or "",
                        "horse_name": first.get("horse_name") or "",
                    }
                    if first
                    else None
                ),
            }
            if source_url in seen_urls:
                raise RunnerV2Error("source URL is reused by more than one target")
            normalized = validate_complete_target(candidate, seen_source_urls=seen_urls)
        except RunnerV2Error as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
            candidate_body = _canonical_bytes(parsed)
            validation_gaps.append(
                {
                    "target_id": target_id,
                    "target_sha256": str(event_row.get("target_sha256") or ""),
                    "reason_code": _validation_gap_reason(
                        exc,
                        runners=runners,
                        results=results,
                    ),
                    "source_url": source_url,
                    "error": error,
                    "error_identity": {
                        "sha256": _sha256_bytes(_canonical_bytes(error)),
                    },
                    "evidence_identities": {
                        "candidate": {
                            "size": len(candidate_body),
                            "sha256": _sha256_bytes(candidate_body),
                        },
                        "candidate_artifact": candidate_artifact_identity,
                        "events_csv": event_identity,
                    },
                    "evidence": {
                        "runner_count": len(runners),
                        "result_count": len(results),
                    },
                }
            )
            continue
        validated.append(normalized)
        validated_package_rows.append(
            {
                **copy.deepcopy(parsed),
                "target_id": target_id,
                "target_sha256": str(event_row.get("target_sha256") or ""),
                "validation": normalized,
            }
        )
        seen_urls.add(source_url)
    validated_path = run_root / "validated-candidates.jsonl"
    validated_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in validated_package_rows
        ),
        encoding="utf-8",
    )
    validation_gap_path = run_root / "validation-gaps.json"
    validation_gap_path.write_text(
        json.dumps(validation_gaps, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "candidate_jsonl": str(candidate_path),
        "parse_gap_json": str(parse_gap_path),
        "validated_candidate_jsonl": str(validated_path),
        "validation_gap_json": str(validation_gap_path),
        "validated_count": len(validated),
        "validation_gap_count": len(validation_gaps),
    }


def _execute_internal_stage(
    descriptor: dict,
    *,
    stage: str,
    stage_root: Path,
    run_root: Path,
) -> dict:
    adapters = _detail_adapter_module()
    plan_root = next(Path(row["path"]) for row in descriptor["mounts"] if row["role"] == "plan")
    try:
        if stage == "discover":
            return adapters.discover_sources(descriptor, plan_root=plan_root)
        previous_stage = STAGES[STAGES.index(stage) - 1]
        previous = _read_stage_artifact(stage_root / f"{previous_stage}.json", expected_stage=previous_stage)
        if stage == "cache":
            return adapters.cache_sources(
                descriptor,
                discover_artifact=previous,
                plan_root=plan_root,
                run_root=run_root,
            )
        if stage == "parse":
            return adapters.parse_cached_sources(
                descriptor,
                cache_artifact=previous,
                run_root=run_root,
            )
        if stage == "validate":
            return _validate_parsed_stage(descriptor, parse_artifact=previous, run_root=run_root)
        cache_artifact = _read_stage_artifact(stage_root / "cache.json", expected_stage="cache")
        return adapters.package_validated_sources(
            descriptor,
            candidate_jsonl=Path(previous["validated_candidate_jsonl"]),
            cache_manifest=Path(cache_artifact["source_cache_manifest"]),
            parse_gap_json=Path(previous["parse_gap_json"]),
            validation_gap_json=Path(previous["validation_gap_json"]),
            run_root=run_root,
        )
    except (OSError, KeyError, ValueError, RuntimeError) as exc:
        if isinstance(exc, RunnerV2Error):
            raise
        raise RunnerV2Error(f"internal {descriptor.get('region')}/{stage} adapter failed: {exc}") from exc


def dispatch_stage(
    descriptor: dict,
    *,
    stage: str,
    run_root: str | Path,
    actual_image_digest: str,
    actual_image_revision: str,
) -> dict:
    if stage not in STAGES or descriptor.get("region") not in REGIONS:
        raise RunnerV2Error("fixed region/stage adapter is unavailable")
    image = validate_runtime_image(
        descriptor,
        actual_image_digest=actual_image_digest,
        actual_image_revision=actual_image_revision,
    )
    adapter_spec = get_adapter_spec(descriptor["region"], stage)
    root = Path(run_root)
    _reject_symlink_components(root, require_exists=True)
    if not root.is_dir():
        raise RunnerV2Error("run root is invalid")
    stage_root = root / "stages"
    stage_root.mkdir(exist_ok=True)
    _reject_symlink_components(stage_root, require_exists=True)
    artifact_path = stage_root / f"{stage}.json"
    if artifact_path.is_symlink():
        raise RunnerV2Error("stage artifact symlink is forbidden")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "historical_race_detail_stage_result",
        "plan_id": descriptor["plan_id"],
        "shard_id": descriptor["shard_id"],
        "region": descriptor["region"],
        "stage": stage,
        "adapter": adapter_spec,
        "target_count": len(descriptor["targets"]),
        **_execute_internal_stage(
            descriptor,
            stage=stage,
            stage_root=stage_root,
            run_root=root,
        ),
    }
    _atomic_write_json(artifact_path, payload)

    checkpoint_path = Path(descriptor["outputs"]["checkpoint"])
    _require_within(checkpoint_path, root, require_exists=False)
    stages = {name: "unstarted" for name in STAGES}
    stage_artifacts: dict[str, str | Path] = {}
    if checkpoint_path.exists():
        try:
            prior = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunnerV2Error("existing stage checkpoint is corrupt") from exc
        if (
            prior.get("actual_image_digest") != image["digest"]
            or prior.get("actual_image_revision") != image["revision"]
        ):
            raise RunnerV2Error("existing checkpoint runtime image changed")
        stages.update(prior.get("stages") or {})
        stage_artifacts.update(prior.get("stage_artifacts") or {})
    stages[stage] = "complete"
    stage_artifacts[f"stage_{stage}"] = str(artifact_path)
    identity = build_checkpoint_identity(
        descriptor,
        artifacts=stage_artifacts,
        shared_host_state_path=descriptor["outputs"]["host_last_start"],
        actual_image_digest=image["digest"],
        actual_image_revision=image["revision"],
    )
    checkpoint = {
        **identity,
        "plan_id": descriptor["plan_id"],
        "shard_id": descriptor["shard_id"],
        "region": descriptor["region"],
        "actual_image_digest": image["digest"],
        "actual_image_revision": image["revision"],
        "stages": stages,
        "stage_artifacts": stage_artifacts,
    }
    _atomic_write_json(checkpoint_path, checkpoint)
    return {
        "adapter": adapter_spec,
        "stage": stage,
        "artifact_path": str(artifact_path),
        "checkpoint_path": str(checkpoint_path),
    }


def validate_request_policy(policy: object) -> dict:
    if not isinstance(policy, dict):
        raise RunnerV2Error("request policy must be an object")
    max_requests = policy.get("max_requests")
    max_requests_per_host = policy.get("max_requests_per_host", max_requests)
    interval = policy.get("minimum_interval_seconds")
    if isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests <= 0:
        raise RunnerV2Error("request budget must be a positive integer")
    if (
        isinstance(max_requests_per_host, bool)
        or not isinstance(max_requests_per_host, int)
        or max_requests_per_host <= 0
    ):
        raise RunnerV2Error("per-host request budget must be a positive integer")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval < 0:
        raise RunnerV2Error("request interval is invalid")
    allowed = policy.get("allowed_hosts")
    redirects = policy.get("redirect_hosts")
    patterns = policy.get("url_patterns")
    if (
        not isinstance(allowed, list)
        or not allowed
        or len(allowed) != len(set(allowed))
        or not isinstance(redirects, list)
        or not set(redirects) <= set(allowed)
        or not isinstance(patterns, dict)
        or set(patterns) != set(allowed)
    ):
        raise RunnerV2Error("request host policy is invalid")
    for host in allowed:
        if not isinstance(host, str) or host != host.casefold() or not re.fullmatch(r"[a-z0-9.-]+", host):
            raise RunnerV2Error("allowed host is invalid")
        host_patterns = patterns.get(host)
        if not isinstance(host_patterns, list) or not host_patterns:
            raise RunnerV2Error("URL pattern list is empty")
        for pattern in host_patterns:
            if not isinstance(pattern, str):
                raise RunnerV2Error("URL regex is invalid")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise RunnerV2Error("URL regex is invalid") from exc
    normalized = copy.deepcopy(policy)
    normalized["max_requests_per_host"] = max_requests_per_host
    query_patterns = normalized.get("query_patterns")
    if query_patterns is None:
        return normalized
    if not isinstance(query_patterns, dict) or not set(query_patterns) <= set(allowed):
        raise RunnerV2Error("request query host policy is invalid")
    for host, query_policy in query_patterns.items():
        if not isinstance(query_policy, dict) or set(query_policy) != {
            "parameters",
            "required_keys",
        }:
            raise RunnerV2Error("request query policy is invalid")
        parameters = query_policy["parameters"]
        required = query_policy["required_keys"]
        if (
            not isinstance(parameters, dict)
            or not parameters
            or not isinstance(required, list)
            or len(required) != len(set(required))
            or not set(required) <= set(parameters)
        ):
            raise RunnerV2Error("request query parameter policy is invalid")
        for key, pattern in parameters.items():
            if (
                not isinstance(key, str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key)
                or not isinstance(pattern, str)
                or not pattern
                or ".*" in pattern
                or ".+" in pattern
            ):
                raise RunnerV2Error("request query parameter regex is invalid")
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise RunnerV2Error("request query parameter regex is invalid") from exc
            if compiled.fullmatch("") is not None:
                raise RunnerV2Error("request query parameter regex cannot match empty values")
    return normalized


def _validate_policy_query(
    query: str,
    *,
    host: str,
    query_patterns: Mapping[str, dict],
    url: str,
) -> None:
    query_policy = query_patterns.get(host)
    if not query:
        if query_policy and query_policy["required_keys"]:
            raise RunnerV2Error(f"request URL is missing required query parameters: {url}")
        return
    if query_policy is None:
        raise RunnerV2Error(f"request URL query is not approved: {url}")
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise RunnerV2Error(f"request URL query is malformed: {url}") from exc
    parameters = query_policy["parameters"]
    seen: set[str] = set()
    for key, value in pairs:
        if (
            not key
            or key in seen
            or key not in parameters
            or not value
            or re.fullmatch(parameters[key], value) is None
        ):
            raise RunnerV2Error(f"request URL query is not approved: {url}")
        seen.add(key)
    if not set(query_policy["required_keys"]) <= seen:
        raise RunnerV2Error(f"request URL is missing required query parameters: {url}")


def _validate_policy_url(
    url: str,
    *,
    hosts: set[str],
    patterns: Mapping[str, list[str]],
    query_patterns: Mapping[str, dict],
) -> None:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold()
        port = parsed.port
    except ValueError as exc:
        raise RunnerV2Error(f"request URL is malformed: {url}") from exc
    if (
        parsed.scheme != "https"
        or not host
        or host not in hosts
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        raise RunnerV2Error(f"request URL is outside the approved boundary: {url}")
    if not any(re.fullmatch(pattern, parsed.path) for pattern in patterns.get(host, [])):
        raise RunnerV2Error(f"request URL path is not approved: {url}")
    _validate_policy_query(
        parsed.query,
        host=host,
        query_patterns=query_patterns,
        url=url,
    )


def validate_request(
    descriptor: dict,
    ledger: Iterable[dict],
    *,
    url: str,
    redirect_chain: Iterable[str],
) -> dict:
    policy = validate_request_policy(descriptor.get("request_policy") if isinstance(descriptor, dict) else None)
    ledger_rows = list(ledger)
    if len(ledger_rows) >= policy["max_requests"]:
        raise RunnerV2Error("request budget is exhausted")
    query_patterns = policy.get("query_patterns") or {}
    _validate_policy_url(
        url,
        hosts=set(policy["allowed_hosts"]),
        patterns=policy["url_patterns"],
        query_patterns=query_patterns,
    )
    request_host = (urlsplit(url).hostname or "").casefold()
    host_request_count = 0
    for row in ledger_rows:
        if not isinstance(row, dict):
            raise RunnerV2Error("request ledger row is invalid")
        row_host = row.get("host")
        if row_host is None:
            row_url = row.get("url")
            if not isinstance(row_url, str):
                raise RunnerV2Error("request ledger row is missing host identity")
            try:
                row_host = (urlsplit(row_url).hostname or "").casefold()
            except ValueError as exc:
                raise RunnerV2Error("request ledger host identity is invalid") from exc
        if not isinstance(row_host, str) or not row_host:
            raise RunnerV2Error("request ledger host identity is invalid")
        if row_host.casefold() == request_host:
            host_request_count += 1
    if host_request_count >= policy["max_requests_per_host"]:
        raise RunnerV2Error("per-host request budget is exhausted")
    redirects = list(redirect_chain)
    for redirected_url in redirects:
        _validate_policy_url(
            redirected_url,
            hosts=set(policy["redirect_hosts"]),
            patterns=policy["url_patterns"],
            query_patterns=query_patterns,
        )
    return {"url": url, "redirect_chain": redirects, "request_number": len(ledger_rows) + 1}


def _record_hash(row: dict) -> str:
    payload = {key: value for key, value in row.items() if key != "record_hash"}
    return _sha256_bytes(_canonical_bytes(payload))


def verify_request_hash_chain(rows: Iterable[dict]) -> None:
    previous = ZERO_HASH
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RunnerV2Error("request ledger row is invalid")
        if row.get("previous_hash") != previous or row.get("record_hash") != _record_hash(row):
            raise RunnerV2Error(f"request ledger hash chain is invalid at row {index}")
        previous = row["record_hash"]


def append_request_record(rows: Iterable[dict], record: dict) -> list[dict]:
    existing = copy.deepcopy(list(rows))
    verify_request_hash_chain(existing)
    if not isinstance(record, dict) or {"previous_hash", "record_hash"} & set(record):
        raise RunnerV2Error("request record contains reserved hash fields")
    row = copy.deepcopy(record)
    row["previous_hash"] = existing[-1]["record_hash"] if existing else ZERO_HASH
    row["record_hash"] = _record_hash(row)
    existing.append(row)
    return existing


def _authority_rank(value: object) -> int:
    authority = str(value or "").casefold()
    return {
        "official": 100,
        "official_archive": 90,
        "fallback": 20,
        "third_party": 10,
    }.get(authority, 0)


def merge_authoritative_fields(target_id: str, sources: Iterable[dict]) -> dict:
    if not str(target_id):
        raise RunnerV2Error("target ID is required for authority merge")
    candidates: dict[str, list[dict]] = {}
    for order, source in enumerate(sources):
        if not isinstance(source, dict) or not isinstance(source.get("fields"), dict):
            raise RunnerV2Error("authority source is invalid")
        provider = _required_text(source, "provider", label="authority source")
        authority = _required_text(source, "authority", label="authority source")
        rank = _authority_rank(authority)
        if rank == 0:
            raise RunnerV2Error(f"unsupported field authority: {authority}")
        for field, value in source["fields"].items():
            if not isinstance(field, str) or not field or value in (None, ""):
                continue
            candidates.setdefault(field, []).append(
                {
                    "provider": provider,
                    "authority": authority,
                    "rank": rank,
                    "value": copy.deepcopy(value),
                    "order": order,
                }
            )
    fields: dict = {}
    provenance: dict = {}
    review_ledger: list[dict] = []
    for field, options in candidates.items():
        selected = sorted(options, key=lambda item: (-item["rank"], item["order"]))[0]
        fields[field] = selected["value"]
        provenance[field] = {
            "provider": selected["provider"],
            "authority": selected["authority"],
        }
        for option in options:
            if option is selected or option["value"] == selected["value"]:
                continue
            review_ledger.append(
                {
                    "target_id": str(target_id),
                    "field": field,
                    "selected_value": selected["value"],
                    "selected_provider": selected["provider"],
                    "selected_authority": selected["authority"],
                    "conflicting_value": option["value"],
                    "conflicting_provider": option["provider"],
                    "conflicting_authority": option["authority"],
                    "reason_code": "field_authority_conflict",
                }
            )
    return {
        "target_id": str(target_id),
        "fields": fields,
        "field_provenance": provenance,
        "review_ledger": review_ledger,
        "requires_review": bool(review_ledger),
    }


def validate_recipes(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise RunnerV2Error("recipe artifact must be an object")
    normalized = copy.deepcopy(payload)
    _assert_no_runtime_escape(normalized)
    if normalized.get("schema_version") != SCHEMA_VERSION or normalized.get("stages") != list(STAGES):
        raise RunnerV2Error("recipe artifact does not use the fixed v2 pipeline")
    recipes = normalized.get("recipes")
    if not isinstance(recipes, list) or len(recipes) != len(REGIONS):
        raise RunnerV2Error("recipe artifact must contain exactly five regions")
    by_region: dict[str, dict] = {}
    recipe_ids: set[str] = set()
    for recipe in recipes:
        if not isinstance(recipe, dict):
            raise RunnerV2Error("recipe entry is invalid")
        recipe_id = recipe.get("id")
        region = recipe.get("region")
        if (
            not isinstance(recipe_id, str)
            or not SAFE_NAME_RE.fullmatch(recipe_id)
            or recipe_id in recipe_ids
            or region not in REGIONS
            or region in by_region
        ):
            raise RunnerV2Error("recipe identity is duplicate or invalid")
        chain = recipe.get("source_chain")
        official = recipe.get("official_sources")
        fallback = recipe.get("fallback_sources")
        discovery = recipe.get("discovery")
        if (
            not isinstance(chain, list)
            or not chain
            or any(
                not isinstance(item, str) or not SAFE_NAME_RE.fullmatch(item)
                for item in chain
            )
            or len(chain) != len(set(chain))
            or not isinstance(official, list)
            or not official
            or not set(official) <= set(chain)
            or not isinstance(fallback, list)
            or not set(fallback) <= set(chain)
            or set(official) & set(fallback)
            or not isinstance(discovery, dict)
            or not isinstance(discovery.get("required"), bool)
            or not isinstance(discovery.get("url_strategy"), str)
            or not discovery["url_strategy"]
        ):
            raise RunnerV2Error(f"source recipe is invalid for {region}")
        recipe_ids.add(recipe_id)
        by_region[region] = recipe
    if set(by_region) != REGIONS:
        raise RunnerV2Error("recipe region coverage is incomplete")
    for region in REGIONS - {"hong_kong"}:
        if not by_region[region]["fallback_sources"]:
            raise RunnerV2Error(f"fallback chain is required for {region}")
    hong_kong = by_region["hong_kong"]
    if (
        hong_kong["fallback_sources"]
        or hong_kong["source_chain"] != ["hkjc"]
        or hong_kong["discovery"].get("required") is not True
        or hong_kong["discovery"].get("provider") != "hkjc"
        or hong_kong["discovery"].get("url_strategy") != "discovery_only"
    ):
        raise RunnerV2Error("Hong Kong recipe must use HKJC discovery only")
    normalized["by_region"] = by_region
    return normalized


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a fixed local historical detail runner v2 stage")
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--plan-root", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--host-lock-root", required=True)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--actual-image-digest", required=True)
    parser.add_argument("--actual-image-revision", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    descriptor_path = Path(args.descriptor)
    try:
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        normalized = validate_descriptor(
            descriptor,
            descriptor_path=descriptor_path,
            repo_root=args.repo_root,
            plan_root=args.plan_root,
            run_root=args.run_root,
            host_lock_root=args.host_lock_root,
        )
        if args.stage not in normalized["stages"]:
            raise RunnerV2Error("requested stage is not approved")
        validate_runtime_image(
            normalized,
            actual_image_digest=args.actual_image_digest,
            actual_image_revision=args.actual_image_revision,
        )
        result = None
        if not args.preflight_only:
            result = dispatch_stage(
                normalized,
                stage=args.stage,
                run_root=args.run_root,
                actual_image_digest=args.actual_image_digest,
                actual_image_revision=args.actual_image_revision,
            )
    except (OSError, json.JSONDecodeError, RunnerV2Error) as exc:
        raise SystemExit(f"runner v2 rejected input: {exc}") from exc
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "plan_id": normalized["plan_id"],
                "shard_id": normalized["shard_id"],
                "stage": args.stage,
                "network_allowed": args.stage in NETWORK_STAGES,
                "validated": True,
                "dispatched": not args.preflight_only,
                "result": result,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

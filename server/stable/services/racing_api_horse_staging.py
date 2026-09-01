from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit

from django.db import transaction
from django.utils import timezone

from stable.models import (
    ExternalDataImportLock,
    ExternalDataImportRun,
    ExternalDataSource,
    ExternalHorse,
    ExternalHorseHistory,
    ExternalImportStatus,
    ExternalRace,
    ExternalRaceResult,
    HorseExternalIdentity,
    HorseNameKind,
    HorseNameVariant,
    RacingRegion,
    SourceLanguage,
)


SHA256_RE = re.compile(r"[0-9a-f]{64}$")
HORSE_ID_RE = re.compile(r"hrs_[A-Za-z0-9]+$")
RACE_ID_RE = re.compile(r"rac_[A-Za-z0-9_]+$")
COUNTRY_SUFFIX_RE = re.compile(r"^(.*?)\s*\(([A-Z]{2,3})\)\s*$")
MAX_CONTROL_FILE_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_JSON_BYTES = 16 * 1024 * 1024
MAX_RUN_JSON_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_FILES_PER_RUN = 256
MAX_MATERIALIZED_RUNS = 5
MAX_COLLECTION_MATERIALIZATIONS = 25
MAX_MARKER_BYTES = 256
REGION_BY_CODE = {
    "GB": RacingRegion.UNITED_KINGDOM,
    "IRE": RacingRegion.IRELAND,
    "FR": RacingRegion.FRANCE,
    "USA": RacingRegion.UNITED_STATES,
    "US": RacingRegion.UNITED_STATES,
    "JPN": RacingRegion.JAPAN,
    "JP": RacingRegion.JAPAN,
    "HK": RacingRegion.HONG_KONG,
    "AUS": RacingRegion.AUSTRALIA,
    "AU": RacingRegion.AUSTRALIA,
    "GER": RacingRegion.GERMANY,
    "DE": RacingRegion.GERMANY,
    "UAE": RacingRegion.MIDDLE_EAST,
    "KSA": RacingRegion.MIDDLE_EAST,
    "QAT": RacingRegion.MIDDLE_EAST,
    "BHR": RacingRegion.MIDDLE_EAST,
}
NON_RUNNER_CODES = {
    "NR",
    "NON-RUNNER",
    "NON RUNNER",
    "SCR",
    "SCRATCHED",
    "WD",
    "WDR",
    "WITHDRAWN",
}


class RacingApiStagingError(RuntimeError):
    pass


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            # Artifact keys are untrusted terminal/log input.  Keep the error
            # fixed instead of echoing a potentially control-character-bearing
            # key back through the management command.
            raise RacingApiStagingError("duplicate JSON key")
        payload[key] = value
    return payload


def _reject_non_finite_json(value: str) -> None:
    raise RacingApiStagingError(f"non-finite JSON constant: {value}")


def _load_strict_json_bytes(content: bytes, *, label: str) -> Any:
    try:
        text = content.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_non_finite_json,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RacingApiStagingError(f"invalid {label} JSON") from exc


def _read_file_bytes_once(
    path: Path,
    *,
    label: str,
    max_bytes: int = MAX_ARTIFACT_JSON_BYTES,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RacingApiStagingError(f"{label} must be a regular file")
        if before.st_size > max_bytes:
            raise RacingApiStagingError(f"{label} exceeds size limit")
        chunks = []
        bytes_read = 0
        while True:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, max_bytes + 1 - bytes_read),
            )
            if not chunk:
                break
            chunks.append(chunk)
            bytes_read += len(chunk)
            if bytes_read > max_bytes:
                raise RacingApiStagingError(f"{label} exceeds size limit")
        after = os.fstat(descriptor)
    except OSError as exc:
        raise RacingApiStagingError(f"cannot read {label}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    try:
        current = os.lstat(path)
    except OSError as exc:
        raise RacingApiStagingError(f"{label} path changed while reading") from exc
    if (
        identity_before != identity_after
        or not stat.S_ISREG(current.st_mode)
        or (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
            current.st_ctime_ns,
        )
        != identity_after
    ):
        raise RacingApiStagingError(f"{label} changed while reading")
    return b"".join(chunks)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_ascii_marker_once(path: Path, *, label: str) -> str:
    content = _read_file_bytes_once(
        path,
        label=label,
        max_bytes=MAX_MARKER_BYTES,
    )
    try:
        return content.decode("ascii").strip()
    except UnicodeError as exc:
        raise RacingApiStagingError(f"invalid {label}") from exc


def _safe_relative_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise RacingApiStagingError("artifact path must be relative")
    candidate = root / value
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RacingApiStagingError("artifact path escapes run root") from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise RacingApiStagingError("artifact member must be a regular non-symlink file")
    return resolved


def _load_verified_json(
    root: Path,
    identity: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, Any]:
    path = _safe_relative_path(root, identity.get("path"))
    expected_sha = identity.get("sha256")
    expected_size = identity.get("size")
    if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
        raise RacingApiStagingError("artifact member SHA-256 is invalid")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int):
        raise RacingApiStagingError("artifact member size is invalid")
    if expected_size < 0 or expected_size > MAX_ARTIFACT_JSON_BYTES:
        raise RacingApiStagingError("artifact member size exceeds limit")
    content = _read_file_bytes_once(path, label=label)
    if len(content) != expected_size or _sha256_bytes(content) != expected_sha:
        raise RacingApiStagingError("artifact member identity mismatch")
    return path, _load_strict_json_bytes(content, label=label)


def load_targeted_artifact(run_dir: Path, *, approved_manifest_sha256: str) -> dict[str, Any]:
    if not SHA256_RE.fullmatch(str(approved_manifest_sha256 or "")):
        raise RacingApiStagingError("approved manifest SHA-256 is invalid")
    try:
        root = run_dir.resolve(strict=True)
    except OSError as exc:
        raise RacingApiStagingError("artifact run directory is missing") from exc
    if run_dir.is_symlink() or not root.is_dir():
        raise RacingApiStagingError("artifact run directory must be a non-symlink directory")
    manifest_path = root / "run-manifest.json"
    complete_path = root / "COMPLETE"
    if manifest_path.is_symlink() or complete_path.is_symlink():
        raise RacingApiStagingError("artifact control files cannot be symlinks")
    if not manifest_path.is_file() or not complete_path.is_file():
        raise RacingApiStagingError("artifact is not complete")
    manifest_bytes = _read_file_bytes_once(
        manifest_path,
        label="run manifest",
        max_bytes=MAX_CONTROL_FILE_BYTES,
    )
    actual_manifest_sha = _sha256_bytes(manifest_bytes)
    if actual_manifest_sha != approved_manifest_sha256:
        raise RacingApiStagingError("approved manifest SHA-256 mismatch")
    if (
        _read_ascii_marker_once(complete_path, label="COMPLETE marker")
        != actual_manifest_sha
    ):
        raise RacingApiStagingError("COMPLETE marker does not bind manifest")
    manifest = _load_strict_json_bytes(manifest_bytes, label="run manifest")
    if not isinstance(manifest, dict):
        raise RacingApiStagingError("run manifest root must be an object")
    if (
        manifest.get("schema_version") != "targeted-horse-run.v1"
        or manifest.get("status") != "complete"
        or manifest.get("database_writes") != 0
        or manifest.get("materialization_mode") != "expanded_compact"
        or not SHA256_RE.fullmatch(
            str(manifest.get("source_batch_manifest_sha256") or "")
        )
        or not SHA256_RE.fullmatch(
            str(manifest.get("source_content_pool_manifest_sha256") or "")
        )
    ):
        raise RacingApiStagingError("targeted run manifest contract drift")
    normalized_identity = manifest.get("normalized")
    if not isinstance(normalized_identity, Mapping):
        raise RacingApiStagingError("normalized artifact identity is missing")
    response_identities = manifest.get("responses")
    if not isinstance(response_identities, list):
        raise RacingApiStagingError("response identity list is missing")
    if len(response_identities) > MAX_RESPONSE_FILES_PER_RUN:
        raise RacingApiStagingError("response identity count exceeds limit")
    declared_identities = [normalized_identity, *response_identities]
    declared_total_size = len(manifest_bytes)
    for identity in declared_identities:
        if not isinstance(identity, Mapping):
            raise RacingApiStagingError("artifact identity must be an object")
        expected_size = identity.get("size")
        if (
            isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or expected_size < 0
            or expected_size > MAX_ARTIFACT_JSON_BYTES
        ):
            raise RacingApiStagingError("artifact member size exceeds limit")
        declared_total_size += expected_size
    if declared_total_size > MAX_RUN_JSON_BYTES:
        raise RacingApiStagingError("targeted run JSON size exceeds limit")
    normalized_path, normalized = _load_verified_json(
        root,
        normalized_identity,
        label="normalized artifact",
    )
    expected_paths = {"run-manifest.json", "COMPLETE", str(normalized_identity["path"])}
    responses = []
    for identity in response_identities:
        identity_path = str(identity.get("path") or "")
        if identity_path in expected_paths:
            raise RacingApiStagingError("duplicate artifact member path")
        response_path, wrapper = _load_verified_json(
            root,
            identity,
            label="response wrapper",
        )
        if (
            not isinstance(wrapper, dict)
            or wrapper.get("url") != identity.get("url")
            or not isinstance(wrapper.get("allow_not_found"), bool)
            or not isinstance(wrapper.get("not_found"), bool)
        ):
            raise RacingApiStagingError("response wrapper contract drift")
        try:
            captured_at = datetime.fromisoformat(
                str(wrapper.get("captured_at") or "").replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise RacingApiStagingError("response capture timestamp is invalid") from exc
        if captured_at.tzinfo is None:
            raise RacingApiStagingError("response capture timestamp requires timezone")
        payload = wrapper.get("payload")
        if wrapper["not_found"] != (payload is None) or (
            payload is not None and not isinstance(payload, dict)
        ):
            raise RacingApiStagingError("response wrapper payload contract drift")
        expected_paths.add(identity_path)
        responses.append(
            {
                "identity": dict(identity),
                "wrapper": wrapper,
                "path": response_path,
            }
        )
    actual_paths = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RacingApiStagingError("artifact cannot contain symlinks")
        if path.is_file():
            actual_paths.add(str(path.relative_to(root)))
    extra = sorted(actual_paths - expected_paths)
    missing = sorted(expected_paths - actual_paths)
    if extra:
        raise RacingApiStagingError("artifact contains an undeclared file")
    if missing:
        raise RacingApiStagingError("artifact is missing a declared file")
    if not isinstance(normalized, dict):
        raise RacingApiStagingError("normalized artifact root must be an object")
    if (
        normalized.get("schema_version") != "targeted-horse-export.v1"
        or normalized.get("database_writes") != 0
        or normalized.get("identity_mode")
        != "provider_stable_id_from_target_race"
        or not isinstance(normalized.get("seed_id"), str)
        or not normalized["seed_id"].strip()
    ):
        raise RacingApiStagingError("normalized artifact contract drift")
    _validate_provider_evidence(normalized, responses)
    return {
        "root": root,
        "manifest": manifest,
        "manifest_sha256": actual_manifest_sha,
        "normalized": normalized,
        "responses": responses,
    }


def load_targeted_materialization(
    materialization_dir: Path,
    *,
    approved_manifest_sha256: str,
) -> dict[str, Any]:
    """加载并重验 materializer 生成的整批 v1 单马工件。"""

    if not SHA256_RE.fullmatch(str(approved_manifest_sha256 or "")):
        raise RacingApiStagingError("approved materialization SHA-256 is invalid")
    try:
        root = materialization_dir.resolve(strict=True)
    except OSError as exc:
        raise RacingApiStagingError("materialization directory is missing") from exc
    if materialization_dir.is_symlink() or not root.is_dir():
        raise RacingApiStagingError(
            "materialization directory must be a non-symlink directory"
        )
    manifest_path = root / "materialization-manifest.json"
    complete_path = root / "COMPLETE"
    if (
        manifest_path.is_symlink()
        or complete_path.is_symlink()
        or not manifest_path.is_file()
        or not complete_path.is_file()
    ):
        raise RacingApiStagingError("materialization is not complete")
    manifest_bytes = _read_file_bytes_once(
        manifest_path,
        label="materialization manifest",
        max_bytes=MAX_CONTROL_FILE_BYTES,
    )
    actual_manifest_sha = _sha256_bytes(manifest_bytes)
    if actual_manifest_sha != approved_manifest_sha256:
        raise RacingApiStagingError("approved materialization SHA-256 mismatch")
    if (
        _read_ascii_marker_once(
            complete_path,
            label="materialization COMPLETE marker",
        )
        != actual_manifest_sha
    ):
        raise RacingApiStagingError(
            "materialization COMPLETE marker does not bind manifest"
        )
    manifest = _load_strict_json_bytes(
        manifest_bytes,
        label="materialization manifest",
    )
    rows = manifest.get("materialized") if isinstance(manifest, dict) else None
    selected_count = (
        manifest.get("selected_seed_count") if isinstance(manifest, dict) else None
    )
    source_batch_sha = (
        manifest.get("source_batch_manifest_sha256")
        if isinstance(manifest, dict)
        else None
    )
    source_content_pool_sha = (
        manifest.get("source_content_pool_manifest_sha256")
        if isinstance(manifest, dict)
        else None
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version")
        != "targeted-horse-batch-materialization.v1"
        or manifest.get("status") != "complete"
        or manifest.get("database_writes") != 0
        or manifest.get("recompute_normalized") is not False
        or not SHA256_RE.fullmatch(str(source_batch_sha or ""))
        or not SHA256_RE.fullmatch(str(source_content_pool_sha or ""))
        or isinstance(selected_count, bool)
        or not isinstance(selected_count, int)
        or selected_count < 1
        or not isinstance(rows, list)
        or len(rows) != selected_count
    ):
        raise RacingApiStagingError("materialization manifest contract drift")
    if selected_count > MAX_MATERIALIZED_RUNS:
        raise RacingApiStagingError("materialized run count exceeds limit")

    expected_top_level = {"materialization-manifest.json", "COMPLETE"}
    seen_seed_ids = set()
    seen_horse_ids = set()
    seen_run_paths = set()
    runs = []
    for ordinal, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise RacingApiStagingError("materialization row must be an object")
        seed_id = str(row.get("seed_id") or "").strip()
        horse_id = str(row.get("horse_id") or "").strip()
        relative = Path(str(row.get("path") or ""))
        run_manifest_sha = str(row.get("manifest_sha256") or "")
        if (
            row.get("ordinal") != ordinal
            or row.get("materialization_mode") != "expanded_compact"
            or not seed_id
            or seed_id in seen_seed_ids
            or not HORSE_ID_RE.fullmatch(horse_id)
            or horse_id in seen_horse_ids
            or not SHA256_RE.fullmatch(run_manifest_sha)
            or relative.is_absolute()
            or len(relative.parts) != 1
            or relative.name in {"", ".", ".."}
        ):
            raise RacingApiStagingError("materialization row identity drift")
        candidate = root / relative
        try:
            run_root = candidate.resolve(strict=True)
            run_root.relative_to(root)
        except (OSError, ValueError) as exc:
            raise RacingApiStagingError(
                "materialized run path escapes root"
            ) from exc
        if candidate.is_symlink() or not run_root.is_dir() or run_root in seen_run_paths:
            raise RacingApiStagingError("materialized run directory identity drift")
        loaded = load_targeted_artifact(
            run_root,
            approved_manifest_sha256=run_manifest_sha,
        )
        normalized = loaded["normalized"]
        if (
            loaded["manifest"].get("source_batch_manifest_sha256")
            != source_batch_sha
            or loaded["manifest"].get("source_content_pool_manifest_sha256")
            != source_content_pool_sha
            or loaded["manifest"].get("materialization_mode")
            != row.get("materialization_mode")
            or normalized.get("seed_id") != seed_id
            or normalized.get("horse_id") != horse_id
        ):
            raise RacingApiStagingError("materialized run source identity drift")
        seen_seed_ids.add(seed_id)
        seen_horse_ids.add(horse_id)
        seen_run_paths.add(run_root)
        expected_top_level.add(relative.name)
        runs.append(
            {
                "ordinal": ordinal,
                "seed_id": seed_id,
                "horse_id": horse_id,
                "run_dir": run_root,
                "manifest_sha256": run_manifest_sha,
            }
        )
    actual_top_level = set()
    for path in root.iterdir():
        if path.is_symlink():
            raise RacingApiStagingError("materialization cannot contain symlinks")
        actual_top_level.add(path.name)
    if actual_top_level != expected_top_level:
        raise RacingApiStagingError("materialization top-level member drift")
    return {
        "root": root,
        "manifest": manifest,
        "manifest_sha256": actual_manifest_sha,
        "source_batch_manifest_sha256": source_batch_sha,
        "source_content_pool_manifest_sha256": source_content_pool_sha,
        "runs": runs,
    }


def _normalized_name(value: object) -> str:
    raw = " ".join(unicodedata.normalize("NFKC", str(value or "")).split())
    match = COUNTRY_SUFFIX_RE.fullmatch(raw)
    if match:
        raw = match.group(1).strip()
    ascii_value = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.casefold())) or raw.casefold()


def _split_name(value: object) -> tuple[str, str]:
    raw = " ".join(str(value or "").split())
    match = COUNTRY_SUFFIX_RE.fullmatch(raw)
    if not match:
        return raw, ""
    return match.group(1).strip(), match.group(2)


def _canonical_json_sha256(value: object) -> str:
    """Match the exporter payload digest: sorted compact UTF-8, no newline."""

    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(content)


def _provider_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise RacingApiStagingError("provider profile field type drift")
    return value


def _profile_projection_from_response(
    payload: Mapping[str, object],
) -> dict[str, object]:
    horse_id = _provider_text(payload, "id").strip()
    raw_name = _provider_text(payload, "name").strip()
    if not HORSE_ID_RE.fullmatch(horse_id) or not raw_name:
        raise RacingApiStagingError("provider profile identity drift")
    name, country_suffix = _split_name(raw_name)
    parent_ids = []
    for key in ("sire_id", "dam_id", "damsire_id"):
        raw_parent_id = _provider_text(payload, key).strip()
        if raw_parent_id:
            parent_ids.append(_parent_horse_id(raw_parent_id))
    return {
        "provider": "the_racing_api",
        "profile_kind": "pro",
        "horse_id": horse_id,
        "raw_name": raw_name,
        "name": name,
        "country_suffix": country_suffix,
        "dob": _provider_text(payload, "dob"),
        "sex": _provider_text(payload, "sex"),
        "sex_code": _provider_text(payload, "sex_code"),
        "colour": _provider_text(payload, "colour"),
        "colour_code": _provider_text(payload, "colour_code"),
        "breeder": _provider_text(payload, "breeder"),
        "sire": _provider_text(payload, "sire"),
        "sire_id": _provider_text(payload, "sire_id"),
        "dam": _provider_text(payload, "dam"),
        "dam_id": _provider_text(payload, "dam_id"),
        "damsire": _provider_text(payload, "damsire"),
        "damsire_id": _provider_text(payload, "damsire_id"),
        "parent_profile_ids": parent_ids,
        "payload_sha256": _canonical_json_sha256(payload),
    }


def _race_rows_by_id(rows: object, *, label: str) -> dict[str, dict[str, object]]:
    if not isinstance(rows, list):
        raise RacingApiStagingError(f"{label} rows are invalid")
    by_id: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RacingApiStagingError(f"{label} row is invalid")
        race_id = str(row.get("race_id") or "").strip()
        if not RACE_ID_RE.fullmatch(race_id) or race_id in by_id:
            raise RacingApiStagingError(f"{label} race identity drift")
        by_id[race_id] = row
    return by_id


def _validated_response_route(
    response: Mapping[str, object],
) -> tuple[str, str, int | None]:
    identity = response.get("identity")
    wrapper = response.get("wrapper")
    if not isinstance(identity, Mapping) or not isinstance(wrapper, Mapping):
        raise RacingApiStagingError("provider response evidence is invalid")
    url = identity.get("url")
    if not isinstance(url, str) or wrapper.get("url") != url:
        raise RacingApiStagingError("provider response URL drift")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise RacingApiStagingError("provider response route is invalid") from exc
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.theracingapi.com"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise RacingApiStagingError("provider response route is not allowed")
    profile_match = re.fullmatch(
        r"/v1/horses/(hrs_[A-Za-z0-9]+)/pro",
        parsed.path,
    )
    if profile_match:
        if parsed.query:
            raise RacingApiStagingError("provider profile query is not allowed")
        return "profile", profile_match.group(1), None
    results_match = re.fullmatch(
        r"/v1/horses/(hrs_[A-Za-z0-9]+)/results",
        parsed.path,
    )
    if not results_match:
        raise RacingApiStagingError("provider response route is not allowed")
    try:
        query = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as exc:
        raise RacingApiStagingError("provider results query is invalid") from exc
    if len(query) != 2 or [key for key, _value in query] != ["limit", "skip"]:
        raise RacingApiStagingError("provider results query is not allowed")
    query_values = dict(query)
    if query_values.get("limit") != "100" or not re.fullmatch(
        r"(?:0|[1-9][0-9]*)",
        query_values.get("skip", ""),
    ):
        raise RacingApiStagingError("provider results pagination is invalid")
    skip = int(query_values["skip"])
    if skip % 100:
        raise RacingApiStagingError("provider results pagination is invalid")
    return "results", results_match.group(1), skip


def _validate_provider_evidence(
    normalized: Mapping[str, object],
    responses: list[dict[str, object]],
) -> None:
    """Bind every staged field to exact manifest-listed TRA response bytes.

    The run manifest already binds wrapper file path, size and SHA.  This gate
    additionally binds the normalized profile and complete career projection to
    the wrapper payloads and to a narrow HTTPS route allowlist.
    """

    if not responses:
        raise RacingApiStagingError("provider response evidence is required")
    target_horse_id = str(normalized.get("horse_id") or "").strip()
    if not HORSE_ID_RE.fullmatch(target_horse_id):
        raise RacingApiStagingError("target horse identity drift")

    profile_payloads: dict[str, Mapping[str, object]] = {}
    result_pages: dict[int, Mapping[str, object]] = {}
    result_total: int | None = None
    for response in responses:
        route_kind, route_horse_id, skip = _validated_response_route(response)
        wrapper = response["wrapper"]
        if wrapper.get("not_found") is not False:
            raise RacingApiStagingError("provider response evidence is incomplete")
        payload = wrapper.get("payload")
        if not isinstance(payload, Mapping):
            raise RacingApiStagingError("provider response payload is invalid")
        if route_kind == "profile":
            if wrapper.get("allow_not_found") is not True:
                raise RacingApiStagingError("provider profile response policy drift")
            if route_horse_id in profile_payloads or payload.get("id") != route_horse_id:
                raise RacingApiStagingError("provider profile response identity drift")
            profile_payloads[route_horse_id] = payload
            continue
        if route_horse_id != target_horse_id or skip is None or skip in result_pages:
            raise RacingApiStagingError("provider results response identity drift")
        if wrapper.get("allow_not_found") is not False:
            raise RacingApiStagingError("provider results response policy drift")
        if (
            payload.get("limit") != 100
            or payload.get("skip") != skip
            or isinstance(payload.get("total"), bool)
            or not isinstance(payload.get("total"), int)
            or payload["total"] < 0
            or payload.get("query")
            != [
                ["limit", "100"],
                ["skip", str(skip)],
                ["horse_id", target_horse_id],
            ]
            or not isinstance(payload.get("results"), list)
        ):
            raise RacingApiStagingError("provider results response contract drift")
        if result_total is None:
            result_total = payload["total"]
        elif result_total != payload["total"]:
            raise RacingApiStagingError("provider results total drift")
        result_pages[skip] = payload

    profile = normalized.get("profile")
    parent_profiles = normalized.get("parent_profiles", [])
    if not isinstance(profile, Mapping) or not isinstance(parent_profiles, list):
        raise RacingApiStagingError("normalized profile evidence is invalid")
    normalized_profiles = [profile, *parent_profiles]
    expected_profile_ids: set[str] = set()
    for normalized_profile in normalized_profiles:
        if not isinstance(normalized_profile, Mapping):
            raise RacingApiStagingError("normalized profile evidence is invalid")
        profile_horse_id = str(normalized_profile.get("horse_id") or "").strip()
        if profile_horse_id in expected_profile_ids:
            raise RacingApiStagingError("duplicate normalized profile identity")
        payload = profile_payloads.get(profile_horse_id)
        if payload is None or dict(normalized_profile) != _profile_projection_from_response(
            payload
        ):
            raise RacingApiStagingError("normalized profile provenance mismatch")
        expected_profile_ids.add(profile_horse_id)
    if set(profile_payloads) != expected_profile_ids:
        raise RacingApiStagingError("provider profile response scope drift")

    if result_total is None or not result_pages:
        raise RacingApiStagingError("provider career response evidence is required")
    expected_skips = set(range(0, max(result_total, 1), 100))
    if set(result_pages) != expected_skips:
        raise RacingApiStagingError("provider results pagination is incomplete")
    provider_rows: list[dict[str, object]] = []
    for skip in sorted(result_pages):
        page_rows = result_pages[skip]["results"]
        expected_page_size = min(100, max(result_total - skip, 0))
        if len(page_rows) != expected_page_size:
            raise RacingApiStagingError("provider results page size drift")
        provider_rows.extend(page_rows)
    if len(provider_rows) != result_total:
        raise RacingApiStagingError("provider results row count drift")
    provider_by_id = _race_rows_by_id(provider_rows, label="provider career")

    career = normalized.get("career")
    if (
        not isinstance(career, Mapping)
        or career.get("provider_row_count") != result_total
        or career.get("unique_race_count") != len(provider_by_id)
        or career.get("page_count") != len(result_pages)
        or _race_rows_by_id(career.get("races"), label="normalized career")
        != provider_by_id
    ):
        raise RacingApiStagingError("normalized career provenance mismatch")

    target_race = normalized.get("target_race")
    if not isinstance(target_race, Mapping):
        raise RacingApiStagingError("normalized target-race provenance is invalid")
    target_race_id = str(target_race.get("race_id") or "").strip()
    provider_target = provider_by_id.get(target_race_id)
    stripped_target = dict(target_race)
    actual_starters = stripped_target.pop("actual_starters", None)
    excluded_non_runner_count = stripped_target.pop("excluded_non_runner_count", None)
    source_mode = stripped_target.pop("source_mode", None)
    if provider_target is None or stripped_target != provider_target:
        raise RacingApiStagingError("normalized target-race provenance mismatch")
    provider_runners = provider_target.get("runners")
    if not isinstance(provider_runners, list):
        raise RacingApiStagingError("provider target-race runners are invalid")
    expected_starters = [
        runner
        for runner in provider_runners
        if isinstance(runner, Mapping)
        and str(runner.get("position") or "").strip().upper()
        not in NON_RUNNER_CODES
    ]
    if (
        any(not isinstance(runner, Mapping) for runner in provider_runners)
        or actual_starters != expected_starters
        or excluded_non_runner_count != len(provider_runners) - len(expected_starters)
        or source_mode
        not in {"targeted_horse", "targeted_horse_content_pool"}
    ):
        raise RacingApiStagingError("normalized target-race starter provenance mismatch")


def _region_from_race(race: Mapping[str, object]) -> str:
    code = str(race.get("region") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2,3}", code):
        raise RacingApiStagingError("invalid TRA race region")
    # Full careers can contain starts outside the target jurisdictions.  Keep
    # their raw provider region in ``raw`` and use OTHER for an otherwise valid
    # code instead of making an overseas start impossible to stage.
    return REGION_BY_CODE.get(code, RacingRegion.OTHER)


def _horse_region(raw_name: object, fallback: str) -> str:
    _name, suffix = _split_name(raw_name)
    return REGION_BY_CODE.get(suffix, fallback)


def _parent_horse_id(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not re.fullmatch(r"(?:hrs|sir|dam|dsi)_[A-Za-z0-9]+", raw):
        raise RacingApiStagingError("invalid TRA parent ID")
    return f"hrs_{raw.split('_', 1)[1]}"


def _validated_payload_sha256(value: object) -> str:
    raw = str(value or "").strip()
    if raw and not SHA256_RE.fullmatch(raw):
        raise RacingApiStagingError("profile payload SHA-256 is invalid")
    return raw


def _numeric_finish_position(value: object) -> int | None:
    match = re.match(r"^([1-9][0-9]*)(?:DH)?$", str(value or "").strip().upper())
    return int(match.group(1)) if match else None


def _normalized_grade(race: Mapping[str, object]) -> str:
    for field in ("pattern", "class"):
        value = str(race.get(field) or "").strip().upper()
        match = re.search(r"(?:GROUP|GRADE|G)\s*([123])\b", value)
        if match:
            return f"G{match.group(1)}"
    return ""


def _latest_observation(
    rows: list[dict[str, object]],
    *,
    field: str,
) -> dict[str, object]:
    observations = [
        {
            "value": str(row["runner"].get(field) or "").strip(),
            "as_of": row["raced_at"].isoformat(),
            "race_id": row["race_id"],
        }
        for row in rows
        if str(row["runner"].get(field) or "").strip()
    ]
    if not observations:
        return {"value": "", "as_of": "", "race_ids": [], "conflict": False}
    latest_date = max(row["as_of"] for row in observations)
    latest = [row for row in observations if row["as_of"] == latest_date]
    values = sorted({row["value"] for row in latest})
    return {
        "value": values[0] if len(values) == 1 else "",
        "as_of": latest_date,
        "race_ids": sorted(row["race_id"] for row in latest),
        "conflict": len(values) > 1,
        "candidates": values if len(values) > 1 else [],
    }


def _page_profile_snapshot(
    normalized: Mapping[str, object],
    *,
    profile: Mapping[str, object],
    parent_profiles: list[Mapping[str, object]],
    started_rows: list[dict[str, object]],
    response_urls: list[str],
) -> dict[str, object]:
    parent_by_id = {
        str(row.get("horse_id") or "").strip(): row
        for row in parent_profiles
    }
    sire_id = _parent_horse_id(profile.get("sire_id"))
    dam_id = _parent_horse_id(profile.get("dam_id"))
    sire = parent_by_id.get(sire_id, {})
    dam = parent_by_id.get(dam_id, {})
    finishes = [
        _numeric_finish_position(row["position"])
        for row in started_rows
    ]
    major_wins = []
    for row, finish in zip(started_rows, finishes, strict=True):
        grade = _normalized_grade(row["race"])
        if finish == 1 and grade:
            major_wins.append(
                {
                    "race_id": row["race_id"],
                    "race_date": row["raced_at"].isoformat(),
                    "race_name": str(row["race"].get("race_name") or ""),
                    "grade": grade,
                    "course": str(row["race"].get("course") or ""),
                    "region": str(row["race"].get("region") or ""),
                }
            )
    career = normalized.get("career") or {}
    authority = normalized.get("career_authority") or {}
    return {
        "schema_version": "racing-api-external-horse-page-snapshot.v1",
        "provider": "the_racing_api",
        "horse_id": str(profile.get("horse_id") or ""),
        "profile_payload_sha256": str(profile.get("payload_sha256") or ""),
        "pedigree_two_generation": {
            "sire": str(profile.get("sire") or ""),
            "sire_id": sire_id,
            "dam": str(profile.get("dam") or ""),
            "dam_id": dam_id,
            "sire_sire": str(sire.get("sire") or ""),
            "sire_sire_id": _parent_horse_id(sire.get("sire_id")),
            "sire_dam": str(sire.get("dam") or ""),
            "sire_dam_id": _parent_horse_id(sire.get("dam_id")),
            "dam_sire": str(dam.get("sire") or profile.get("damsire") or ""),
            "dam_sire_id": _parent_horse_id(
                dam.get("sire_id") or profile.get("damsire_id")
            ),
            "dam_dam": str(dam.get("dam") or ""),
            "dam_dam_id": _parent_horse_id(dam.get("dam_id")),
            "parent_profile_payload_sha256": {
                horse_id: str(parent.get("payload_sha256") or "")
                for horse_id, parent in sorted(parent_by_id.items())
            },
        },
        "owner_observation": _latest_observation(started_rows, field="owner"),
        "trainer_observation": _latest_observation(started_rows, field="trainer"),
        "career": {
            "provider_row_count": career.get("provider_row_count"),
            "unique_race_count": career.get("unique_race_count"),
            "page_count": career.get("page_count"),
            "started_count": len(started_rows),
            "win_count": sum(position == 1 for position in finishes),
            "second_count": sum(position == 2 for position in finishes),
            "third_count": sum(position == 3 for position in finishes),
            "provider_pagination_complete": True,
            "authority_status": str(authority.get("status") or "provider_available"),
            "authority_basis": str(authority.get("basis") or ""),
        },
        "major_wins": sorted(
            major_wins,
            key=lambda row: (row["race_date"], row["race_id"]),
        ),
        "evidence_urls": sorted(set(response_urls)),
    }


def _profile_summary_fields(snapshot: Mapping[str, object]) -> dict[str, object]:
    career = snapshot.get("career") or {}
    if not isinstance(career, Mapping):
        raise RacingApiStagingError("page profile career snapshot is invalid")
    required_counts = ("started_count", "win_count", "second_count", "third_count")
    if any(
        isinstance(career.get(field), bool)
        or not isinstance(career.get(field), int)
        or career[field] < 0
        for field in required_counts
    ):
        raise RacingApiStagingError("page profile career counts are invalid")
    owner = snapshot.get("owner_observation") or {}
    trainer = snapshot.get("trainer_observation") or {}
    if not isinstance(owner, Mapping) or not isinstance(trainer, Mapping):
        raise RacingApiStagingError("page profile observations are invalid")
    return {
        "owner_name": str(owner.get("value") or ""),
        "trainer_name": str(trainer.get("value") or ""),
        "record_summary": (
            "starts={started_count};wins={win_count};seconds={second_count};"
            "thirds={third_count}"
        ).format(**career),
        "profile_snapshot": dict(snapshot),
    }


def _validate_and_plan(
    normalized: Mapping[str, object],
    *,
    responses: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    profile = normalized.get("profile")
    career = normalized.get("career")
    if not isinstance(profile, Mapping) or not isinstance(career, Mapping):
        raise RacingApiStagingError("profile and career objects are required")
    _validated_payload_sha256(profile.get("payload_sha256"))
    horse_id = str(normalized.get("horse_id") or "").strip()
    if not HORSE_ID_RE.fullmatch(horse_id) or profile.get("horse_id") != horse_id:
        raise RacingApiStagingError("target horse identity drift")
    target_race = normalized.get("target_race")
    if not isinstance(target_race, Mapping):
        raise RacingApiStagingError("target race object is required")
    target_event_region = _region_from_race(target_race)
    races = career.get("races")
    if not isinstance(races, list) or career.get("unique_race_count") != len(races):
        raise RacingApiStagingError("career race count drift")
    # The staging authorization is scoped to the selected target stable IDs.
    # Parent profiles and the other runners remain immutable provenance inside
    # the artifact, but must not create additional ExternalHorse rows.
    parent_profiles = normalized.get("parent_profiles", [])
    if not isinstance(parent_profiles, list):
        raise RacingApiStagingError("parent_profiles must be a list")
    typed_parent_profiles: list[Mapping[str, object]] = []
    for parent_profile in parent_profiles:
        if not isinstance(parent_profile, Mapping):
            raise RacingApiStagingError("parent profile must be an object")
        parent_horse_id = str(parent_profile.get("horse_id") or "").strip()
        parent_raw_name = str(parent_profile.get("raw_name") or "").strip()
        _validated_payload_sha256(parent_profile.get("payload_sha256"))
        if not HORSE_ID_RE.fullmatch(parent_horse_id) or not parent_raw_name:
            raise RacingApiStagingError("parent profile identity is invalid")
        if parent_horse_id == horse_id:
            raise RacingApiStagingError("parent profile conflicts with target identity")
        typed_parent_profiles.append(parent_profile)
    planned_races = []
    results = []
    histories = []
    started_rows = []
    for race in races:
        if not isinstance(race, Mapping):
            raise RacingApiStagingError("career race must be an object")
        race_id = str(race.get("race_id") or "").strip()
        if not RACE_ID_RE.fullmatch(race_id):
            raise RacingApiStagingError("invalid TRA race ID")
        race_region = _region_from_race(race)
        try:
            raced_at = date.fromisoformat(str(race.get("date") or ""))
        except ValueError as exc:
            raise RacingApiStagingError("invalid TRA race date") from exc
        runners = race.get("runners")
        if not isinstance(runners, list):
            raise RacingApiStagingError("TRA race runners must be a list")
        planned_races.append({"race_id": race_id, "region": race_region, "raced_at": raced_at, "raw": dict(race)})
        target_rows = []
        for runner in runners:
            if not isinstance(runner, Mapping):
                raise RacingApiStagingError("TRA runner must be an object")
            runner_horse_id = str(runner.get("horse_id") or "").strip()
            runner_name = str(runner.get("horse") or "").strip()
            if not HORSE_ID_RE.fullmatch(runner_horse_id) or not runner_name:
                raise RacingApiStagingError("TRA runner identity is invalid")
            position = str(runner.get("position") or "").strip()
            if runner_horse_id == horse_id:
                target_rows.append(runner)
        if len(target_rows) != 1:
            raise RacingApiStagingError(f"target horse occurrence count must be 1 for {race_id}")
        if str(target_rows[0].get("position") or "").strip().upper() in NON_RUNNER_CODES:
            # Full horse history can legitimately contain a declaration that
            # did not become an actual start. Keep the immutable race/runner
            # evidence, but do not create a result or career-start row.
            continue
        target_runner = target_rows[0]
        started_rows.append(
            {
                "race_id": race_id,
                "raced_at": raced_at,
                "position": str(target_runner.get("position") or "").strip(),
                "runner": dict(target_runner),
                "race": dict(race),
            }
        )
        results.append(
            {
                "race_id": race_id,
                "race_region": race_region,
                "horse_id": horse_id,
                "horse_name": str(target_runner.get("horse") or "").strip(),
                "position": str(target_runner.get("position") or "").strip(),
                "runner": dict(target_runner),
            }
        )
        histories.append(
            {
                "race_id": race_id,
                "race_name": str(race.get("race_name") or "").strip(),
                "raced_at": raced_at,
                "position": str(target_rows[0].get("position") or "").strip(),
                "horse_number": str(target_rows[0].get("number") or "").strip(),
                "raw": dict(target_rows[0]),
            }
        )
    target_raw_name = str(profile.get("raw_name") or "").strip()
    if not target_raw_name:
        raise RacingApiStagingError("target profile name is missing")
    # For an origin suffix that has no dedicated RacingRegion (for example NZ
    # or SAF), use the reviewed target-event cohort.  Known JPN/HK/AUS/etc.
    # suffixes still win and preserve the local identity namespace.
    target_region = _horse_region(target_raw_name, target_event_region)
    target = {
        "horse_id": horse_id,
        "raw_name": target_raw_name,
        "region": target_region,
        "profile": dict(profile),
        "page_profile_snapshot": _page_profile_snapshot(
            normalized,
            profile=profile,
            parent_profiles=typed_parent_profiles,
            started_rows=started_rows,
            response_urls=[
                str(row.get("identity", {}).get("url") or "")
                for row in (responses or [])
                if isinstance(row.get("identity"), Mapping)
            ],
        ),
    }
    return {
        "horse_id": horse_id,
        "horses": [target],
        "races": sorted(planned_races, key=lambda row: row["race_id"]),
        "results": sorted(results, key=lambda row: (row["race_id"], row["horse_id"])),
        "histories": sorted(histories, key=lambda row: (row["raced_at"], row["race_id"])),
    }


def dry_run_targeted_artifact(run_dir: Path, *, approved_manifest_sha256: str) -> dict[str, Any]:
    loaded = load_targeted_artifact(run_dir, approved_manifest_sha256=approved_manifest_sha256)
    plan = _validate_and_plan(
        loaded["normalized"],
        responses=loaded["responses"],
    )
    return {
        "status": "dry_run",
        "database_writes": 0,
        "manifest_sha256": loaded["manifest_sha256"],
        "horse_id": plan["horse_id"],
        "scope_stable_ids": [plan["horse_id"]],
        "planned": {
            "external_horses": len(plan["horses"]),
            "external_races": len(plan["races"]),
            "external_results": len(plan["results"]),
            "external_histories": len(plan["histories"]),
            "name_variants": len(plan["horses"]),
            "canonical_identity_writes": 0,
            "out_of_scope_horse_writes": 0,
        },
        "existing": {
            "external_horses": ExternalHorse.objects.filter(
                source=ExternalDataSource.THE_RACING_API,
                horse_id__in=[row["horse_id"] for row in plan["horses"]],
            ).count(),
            "external_races": ExternalRace.objects.filter(
                source=ExternalDataSource.THE_RACING_API,
                race_id__in=[row["race_id"] for row in plan["races"]],
            ).count(),
        },
    }


def _write_enabled(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _upsert_name_variant(horse: ExternalHorse, raw_name: str, *, payload_sha256: str = "") -> None:
    payload_sha256 = _validated_payload_sha256(payload_sha256)
    _name, suffix = _split_name(raw_name)
    strict = _normalized_name(raw_name)
    defaults = {
        "name_text": raw_name,
        "language": SourceLanguage.ENGLISH,
        "script": "latin",
        "country_suffix": suffix,
        "normalized_loose": strict,
        "is_official": False,
    }
    if payload_sha256:
        defaults["payload_sha256"] = payload_sha256
    HorseNameVariant.objects.update_or_create(
        external_horse=horse,
        source=ExternalDataSource.THE_RACING_API,
        name_kind=HorseNameKind.SOURCE_DISPLAY,
        normalized_strict=strict,
        defaults=defaults,
    )


def apply_targeted_artifact(
    run_dir: Path,
    *,
    approved_manifest_sha256: str,
    allow_write: bool = False,
    skip_race_ids: set[str] | None = None,
) -> dict[str, Any]:
    if not allow_write or not _write_enabled(os.environ.get("RACING_API_STAGING_WRITE_ENABLED")):
        raise RacingApiStagingError(
            "staging write gate requires allow_write and RACING_API_STAGING_WRITE_ENABLED=true"
        )
    loaded = load_targeted_artifact(run_dir, approved_manifest_sha256=approved_manifest_sha256)
    plan = _validate_and_plan(
        loaded["normalized"],
        responses=loaded["responses"],
    )
    with transaction.atomic():
        lock, _created = ExternalDataImportLock.objects.select_for_update().get_or_create(
            source=ExternalDataSource.THE_RACING_API,
            defaults={"racing_region": RacingRegion.OTHER},
        )
        if lock.locked_by_run_id and lock.locked_by_run.status == ExternalImportStatus.STARTED:
            raise RacingApiStagingError("another The Racing API staging run is active")
        existing_receipt = ExternalDataImportRun.objects.filter(
            source=ExternalDataSource.THE_RACING_API,
            target_type="targeted_horse_artifact",
            parameters__manifest_sha256=loaded["manifest_sha256"],
            status=ExternalImportStatus.SUCCESS,
        ).first()
        if existing_receipt is not None:
            target_plan = plan["horses"][0]
            snapshot_fields = _profile_summary_fields(
                target_plan.get("page_profile_snapshot") or {}
            )
            existing_horse = ExternalHorse.objects.filter(
                source=ExternalDataSource.THE_RACING_API,
                horse_id=target_plan["horse_id"],
            ).first()
            if existing_horse is not None and all(
                getattr(existing_horse, field) == value
                for field, value in snapshot_fields.items()
            ):
                return {
                    "status": "replayed",
                    "database_writes": 0,
                    "manifest_sha256": loaded["manifest_sha256"],
                    "run_id": existing_receipt.pk,
                }
        now = timezone.now()
        run = ExternalDataImportRun.objects.create(
            source=ExternalDataSource.THE_RACING_API,
            racing_region=RacingRegion.OTHER,
            source_language=SourceLanguage.ENGLISH,
            target_type=(
                "targeted_horse_profile_snapshot_v1"
                if existing_receipt is not None
                else "targeted_horse_artifact"
            ),
            horse_id=plan["horse_id"],
            parameters={
                "manifest_sha256": loaded["manifest_sha256"],
                "artifact_root": str(loaded["root"]),
                "canonical_identity_writes": 0,
            },
            status=ExternalImportStatus.STARTED,
            dry_run=False,
            started_at=now,
        )
        lock.locked_by_run = run
        lock.acquired_at = now
        lock.save(update_fields=["locked_by_run", "acquired_at", "updated_at"])
        horse_objects: dict[str, ExternalHorse] = {}
        for row in plan["horses"]:
            profile = row.get("profile") or {}
            raw_name = row["raw_name"]
            plain_name, suffix = _split_name(raw_name)
            birth_date = None
            if profile.get("dob"):
                try:
                    birth_date = date.fromisoformat(str(profile["dob"]))
                except ValueError as exc:
                    raise RacingApiStagingError("invalid target horse DOB") from exc
            observation_defaults = {
                "racing_region": row["region"],
                "source_language": SourceLanguage.ENGLISH,
                "horse_name": raw_name,
                "horse_name_en": plain_name,
                "normalized_horse_name": _normalized_name(raw_name),
                "country": suffix,
                "last_seen_at": now,
            }
            profile_defaults = {
                "sex": str(profile.get("sex_code") or profile.get("sex") or ""),
                "birth_date": birth_date,
                "color": str(profile.get("colour") or ""),
                "breeder_name": str(profile.get("breeder") or ""),
                "father_name": str(profile.get("sire") or ""),
                "mother_name": str(profile.get("dam") or ""),
                "damsire_name": str(profile.get("damsire") or ""),
                "sire_external_id": _parent_horse_id(profile.get("sire_id")),
                "dam_external_id": _parent_horse_id(profile.get("dam_id")),
                "damsire_external_id": _parent_horse_id(profile.get("damsire_id")),
                **_profile_summary_fields(row.get("page_profile_snapshot") or {}),
                "raw_payload": dict(profile),
                "fetched_at": now,
            }
            create_defaults = {
                **observation_defaults,
                **profile_defaults,
            }
            horse, horse_created = ExternalHorse.objects.get_or_create(
                source=ExternalDataSource.THE_RACING_API,
                horse_id=row["horse_id"],
                defaults=create_defaults,
            )
            if not horse_created:
                update_values = dict(observation_defaults)
                if profile:
                    update_values.update(profile_defaults)
                for field, value in update_values.items():
                    setattr(horse, field, value)
                horse.save(update_fields=[*update_values, "updated_at"])
            horse_objects[row["horse_id"]] = horse
            _upsert_name_variant(
                horse,
                raw_name,
                payload_sha256=str(profile.get("payload_sha256") or ""),
            )
        race_objects: dict[str, ExternalRace] = {}
        skipped_race_ids = set(skip_race_ids or ())
        race_write_count = 0
        for row in plan["races"]:
            if row["race_id"] in skipped_race_ids:
                race_objects[row["race_id"]] = ExternalRace.objects.get(
                    source=ExternalDataSource.THE_RACING_API,
                    race_id=row["race_id"],
                )
                continue
            raw = row["raw"]
            race, _race_created = ExternalRace.objects.update_or_create(
                source=ExternalDataSource.THE_RACING_API,
                race_id=row["race_id"],
                defaults={
                    "racing_region": row["region"],
                    "source_language": SourceLanguage.ENGLISH,
                    "race_name": str(raw.get("race_name") or ""),
                    "race_date": row["raced_at"],
                    "course": str(raw.get("course") or ""),
                    "venue": str(raw.get("course_id") or ""),
                    "race_grade": str(raw.get("pattern") or ""),
                    "race_class": str(raw.get("class") or ""),
                    "surface": str(raw.get("surface") or ""),
                    "distance": str(raw.get("dist") or raw.get("dist_m") or ""),
                    "going": str(raw.get("going") or ""),
                    "raw_payload": raw,
                    "fetched_at": now,
                    "last_seen_at": now,
                },
            )
            race_objects[row["race_id"]] = race
            race_write_count += 1
        for row in plan["results"]:
            runner = row["runner"]
            ExternalRaceResult.objects.update_or_create(
                source=ExternalDataSource.THE_RACING_API,
                external_race_id=row["race_id"],
                result_key=row["horse_id"],
                defaults={
                    "racing_region": row["race_region"],
                    "source_language": SourceLanguage.ENGLISH,
                    "race": race_objects[row["race_id"]],
                    "horse_id": row["horse_id"],
                    "horse_name": row["horse_name"],
                    "normalized_horse_name": _normalized_name(row["horse_name"]),
                    "horse_number": str(runner.get("number") or ""),
                    "finish_position": row["position"],
                    "finish_time": str(runner.get("time") or ""),
                    "margin": str(runner.get("btn") or runner.get("ovr_btn") or ""),
                    "odds_value": str(runner.get("sp") or runner.get("bsp") or ""),
                    "barrier": str(runner.get("draw") or ""),
                    "jockey_name": str(runner.get("jockey") or ""),
                    "trainer_name": str(runner.get("trainer") or ""),
                    "raw_payload": runner,
                    "fetched_at": now,
                    "last_seen_at": now,
                },
            )
        target_horse = horse_objects[plan["horse_id"]]
        for row in plan["histories"]:
            ExternalHorseHistory.objects.update_or_create(
                source=ExternalDataSource.THE_RACING_API,
                external_horse_id=plan["horse_id"],
                history_key=row["race_id"],
                defaults={
                    "racing_region": race_objects[row["race_id"]].racing_region,
                    "source_language": SourceLanguage.ENGLISH,
                    "horse": target_horse,
                    "external_race_id": row["race_id"],
                    "race_name": row["race_name"],
                    "raced_at": row["raced_at"],
                    "horse_number": row["horse_number"],
                    "finish_position": row["position"],
                    "raw_payload": row["raw"],
                    "fetched_at": now,
                    "last_seen_at": now,
                },
            )
        run.status = ExternalImportStatus.SUCCESS
        run.success_count = len(plan["races"]) + len(plan["horses"])
        run.coverage_stats = {
            "external_horses": len(plan["horses"]),
            "external_races": len(plan["races"]),
            "external_results": len(plan["results"]),
            "external_histories": len(plan["histories"]),
            "canonical_identity_writes": 0,
            "out_of_scope_horse_writes": 0,
            "deduplicated_external_races": len(skipped_race_ids),
        }
        run.finished_at = timezone.now()
        run.save(
            update_fields=[
                "status",
                "success_count",
                "coverage_stats",
                "finished_at",
                "updated_at",
            ]
        )
        lock.locked_by_run = None
        lock.acquired_at = None
        lock.save(update_fields=["locked_by_run", "acquired_at", "updated_at"])
    return {
        "status": "applied",
        "database_writes": (
            len(plan["horses"])
            + race_write_count
            + len(plan["results"])
            + len(plan["histories"])
            + len(plan["horses"])
            + 2
        ),
        "manifest_sha256": loaded["manifest_sha256"],
        "run_id": run.pk,
        "coverage": run.coverage_stats,
    }


def _materialization_plans(loaded: Mapping[str, object]) -> list[dict[str, Any]]:
    plans = []
    race_payload_sha_by_id: dict[str, str] = {}
    for row in loaded["runs"]:
        artifact = load_targeted_artifact(
            row["run_dir"],
            approved_manifest_sha256=row["manifest_sha256"],
        )
        plan = _validate_and_plan(
            artifact["normalized"],
            responses=artifact["responses"],
        )
        if plan["horse_id"] != row["horse_id"]:
            raise RacingApiStagingError("materialization plan horse identity drift")
        for race in plan["races"]:
            race_id = race["race_id"]
            payload_sha = _canonical_json_sha256(race["raw"])
            previous_sha = race_payload_sha_by_id.setdefault(race_id, payload_sha)
            if previous_sha != payload_sha:
                raise RacingApiStagingError(
                    "duplicate materialized race has conflicting provider payload"
                )
        plans.append(plan)
    return plans


def _action_counts_for_plans(
    loaded: Mapping[str, object],
    plans: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Return row-level create/update/skip/conflict counts for the live DB."""

    horse_ids = {plan["horse_id"] for plan in plans}
    race_ids = {race["race_id"] for plan in plans for race in plan["races"]}
    result_keys = {
        (result["race_id"], result["horse_id"])
        for plan in plans
        for result in plan["results"]
    }
    history_keys = {
        (plan["horse_id"], history["race_id"])
        for plan in plans
        for history in plan["histories"]
    }

    existing_horse_ids = set(
        ExternalHorse.objects.filter(
            source=ExternalDataSource.THE_RACING_API,
            horse_id__in=horse_ids,
        ).values_list("horse_id", flat=True)
    )
    existing_race_ids = set(
        ExternalRace.objects.filter(
            source=ExternalDataSource.THE_RACING_API,
            race_id__in=race_ids,
        ).values_list("race_id", flat=True)
    )
    existing_result_keys = set(
        ExternalRaceResult.objects.filter(
            source=ExternalDataSource.THE_RACING_API,
            external_race_id__in=race_ids,
            result_key__in=horse_ids,
        ).values_list("external_race_id", "result_key")
    ) & result_keys
    existing_history_keys = set(
        ExternalHorseHistory.objects.filter(
            source=ExternalDataSource.THE_RACING_API,
            external_horse_id__in=horse_ids,
            history_key__in=race_ids,
        ).values_list("external_horse_id", "history_key")
    ) & history_keys
    existing_variant_horse_ids = set(
        HorseNameVariant.objects.filter(
            source=ExternalDataSource.THE_RACING_API,
            name_kind=HorseNameKind.SOURCE_DISPLAY,
            external_horse__source=ExternalDataSource.THE_RACING_API,
            external_horse__horse_id__in=horse_ids,
        ).values_list("external_horse__horse_id", flat=True)
    )
    successful_manifest_shas = set(
        ExternalDataImportRun.objects.filter(
            source=ExternalDataSource.THE_RACING_API,
            target_type="targeted_horse_artifact",
            parameters__manifest_sha256__in=[
                row["manifest_sha256"] for row in loaded["runs"]
            ],
            status=ExternalImportStatus.SUCCESS,
        ).values_list("parameters__manifest_sha256", flat=True)
    )
    lock_exists = ExternalDataImportLock.objects.filter(
        source=ExternalDataSource.THE_RACING_API
    ).exists()
    summed_race_operations = sum(len(plan["races"]) for plan in plans)

    def upsert_counts(total: int, existing: int, *, skip: int = 0) -> dict[str, int]:
        return {
            "create": total - existing,
            "update": existing,
            "skip": skip,
            "conflict": 0,
        }

    return {
        ExternalDataImportLock._meta.db_table: {
            "create": int(not lock_exists),
            "update": int(lock_exists),
            "skip": 0,
            "conflict": 0,
        },
        ExternalDataImportRun._meta.db_table: {
            "create": len(plans) - len(successful_manifest_shas),
            "update": 0,
            "skip": len(successful_manifest_shas),
            "conflict": 0,
        },
        ExternalHorse._meta.db_table: upsert_counts(
            len(horse_ids), len(existing_horse_ids)
        ),
        ExternalRace._meta.db_table: upsert_counts(
            len(race_ids),
            len(existing_race_ids),
            skip=summed_race_operations - len(race_ids),
        ),
        ExternalRaceResult._meta.db_table: upsert_counts(
            len(result_keys), len(existing_result_keys)
        ),
        ExternalHorseHistory._meta.db_table: upsert_counts(
            len(history_keys), len(existing_history_keys)
        ),
        HorseNameVariant._meta.db_table: upsert_counts(
            len(horse_ids), len(existing_variant_horse_ids)
        ),
    }


def dry_run_targeted_materialization(
    materialization_dir: Path,
    *,
    approved_manifest_sha256: str,
) -> dict[str, Any]:
    loaded = load_targeted_materialization(
        materialization_dir,
        approved_manifest_sha256=approved_manifest_sha256,
    )
    plans = _materialization_plans(loaded)
    reports = []
    for row in loaded["runs"]:
        report = dry_run_targeted_artifact(
            row["run_dir"],
            approved_manifest_sha256=row["manifest_sha256"],
        )
        if report.get("horse_id") != row["horse_id"]:
            raise RacingApiStagingError("materialization dry-run horse identity drift")
        reports.append(
            {
                "ordinal": row["ordinal"],
                "seed_id": row["seed_id"],
                **report,
            }
        )
    planned_keys = (
        "external_horses",
        "external_races",
        "external_results",
        "external_histories",
        "name_variants",
        "canonical_identity_writes",
        "out_of_scope_horse_writes",
    )
    unique_race_ids = {
        race["race_id"] for plan in plans for race in plan["races"]
    }
    unique_result_keys = {
        (result["race_id"], result["horse_id"])
        for plan in plans
        for result in plan["results"]
    }
    unique_history_keys = {
        (plan["horse_id"], history["race_id"])
        for plan in plans
        for history in plan["histories"]
    }
    target_ids = [plan["horse_id"] for plan in plans]
    summed_race_count = sum(len(plan["races"]) for plan in plans)
    action_counts = _action_counts_for_plans(loaded, plans)
    return {
        "status": "batch_dry_run",
        "database_writes": 0,
        "materialization_manifest_sha256": loaded["manifest_sha256"],
        "source_batch_manifest_sha256": loaded["source_batch_manifest_sha256"],
        "source_content_pool_manifest_sha256": loaded[
            "source_content_pool_manifest_sha256"
        ],
        "run_count": len(reports),
        "unique_target_horse_count": len(
            {row["horse_id"] for row in loaded["runs"]}
        ),
        "scope_stable_ids": target_ids,
        "scope_guard": {
            "out_of_scope_horse_writes": 0,
            "canonical_identity_writes": 0,
            "provider": ExternalDataSource.THE_RACING_API,
        },
        "planned_tables": [
            ExternalDataImportLock._meta.db_table,
            ExternalDataImportRun._meta.db_table,
            ExternalHorse._meta.db_table,
            ExternalRace._meta.db_table,
            ExternalRaceResult._meta.db_table,
            ExternalHorseHistory._meta.db_table,
            HorseNameVariant._meta.db_table,
        ],
        "unique_planned_rows": {
            "external_horses": len(target_ids),
            "external_races": len(unique_race_ids),
            "external_results": len(unique_result_keys),
            "external_histories": len(unique_history_keys),
            "name_variants": len(target_ids),
            "import_runs": len(target_ids),
        },
        "deduplicated_operations": {
            "external_races": summed_race_count - len(unique_race_ids),
        },
        "action_counts": action_counts,
        "action_totals": {
            action: sum(row[action] for row in action_counts.values())
            for action in ("create", "update", "skip", "conflict")
        },
        "per_run_planned_sum": {
            key: sum(report["planned"][key] for report in reports)
            for key in planned_keys
        },
        "runs": reports,
    }


def apply_targeted_materialization(
    materialization_dir: Path,
    *,
    approved_manifest_sha256: str,
    allow_write: bool = False,
) -> dict[str, Any]:
    if not allow_write or not _write_enabled(
        os.environ.get("RACING_API_STAGING_WRITE_ENABLED")
    ):
        raise RacingApiStagingError(
            "batch staging write gate requires allow_write and "
            "RACING_API_STAGING_WRITE_ENABLED=true"
        )
    loaded = load_targeted_materialization(
        materialization_dir,
        approved_manifest_sha256=approved_manifest_sha256,
    )
    plans = _materialization_plans(loaded)
    # 全批先 dry-run，保证格式/字段错误在第一笔写入前暴露。
    dry_run_report = dry_run_targeted_materialization(
        materialization_dir,
        approved_manifest_sha256=approved_manifest_sha256,
    )
    results = []
    seen_race_ids: set[str] = set()
    with transaction.atomic():
        for row, plan in zip(loaded["runs"], plans, strict=True):
            current_race_ids = {race["race_id"] for race in plan["races"]}
            result = apply_targeted_artifact(
                row["run_dir"],
                approved_manifest_sha256=row["manifest_sha256"],
                allow_write=True,
                skip_race_ids=current_race_ids & seen_race_ids,
            )
            if result.get("status") not in {"applied", "replayed"}:
                raise RacingApiStagingError(
                    "materialized run returned an invalid apply status"
                )
            results.append(
                {
                    "ordinal": row["ordinal"],
                    "seed_id": row["seed_id"],
                    "horse_id": row["horse_id"],
                    **result,
                }
            )
            seen_race_ids.update(current_race_ids)
    return {
        "status": (
            "applied"
            if any(row["status"] == "applied" for row in results)
            else "replayed"
        ),
        "database_writes": sum(row["database_writes"] for row in results),
        "materialization_manifest_sha256": loaded["manifest_sha256"],
        "source_batch_manifest_sha256": loaded["source_batch_manifest_sha256"],
        "source_content_pool_manifest_sha256": loaded[
            "source_content_pool_manifest_sha256"
        ],
        "run_count": len(results),
        "dry_run_run_count": dry_run_report["run_count"],
        "scope_stable_ids": dry_run_report["scope_stable_ids"],
        "scope_guard": dry_run_report["scope_guard"],
        "planned_tables": dry_run_report["planned_tables"],
        "unique_planned_rows": dry_run_report["unique_planned_rows"],
        "deduplicated_operations": dry_run_report[
            "deduplicated_operations"
        ],
        "dry_run_action_counts": dry_run_report["action_counts"],
        "dry_run_action_totals": dry_run_report["action_totals"],
        "results": results,
    }


def _verified_exact_row(queryset, expected: Mapping[str, object], *, label: str):
    rows = list(queryset[:2])
    if len(rows) != 1:
        raise RacingApiStagingError(f"{label} row count drift")
    row = rows[0]
    actual = {field: getattr(row, field) for field in expected}
    if actual != dict(expected):
        raise RacingApiStagingError(f"{label} field drift")
    return row


def verify_targeted_materialization(
    materialization_dir: Path,
    *,
    approved_manifest_sha256: str,
) -> dict[str, Any]:
    """Read-only exact verifier for one already-applied materialization.

    The verifier reloads all content-addressed provider evidence, reconstructs
    the write plan, and compares every field controlled by the staging writer.
    It does not treat row existence or a successful import receipt alone as
    proof of a valid apply.
    """

    loaded = load_targeted_materialization(
        materialization_dir,
        approved_manifest_sha256=approved_manifest_sha256,
    )
    plans = _materialization_plans(loaded)
    seen_race_ids: set[str] = set()
    verified_counts = {
        "external_horses": 0,
        "external_races": 0,
        "external_results": 0,
        "external_histories": 0,
        "name_variants": 0,
        "import_runs": 0,
    }

    for materialized, plan in zip(loaded["runs"], plans, strict=True):
        manifest_sha = materialized["manifest_sha256"]
        duplicate_races = {
            race["race_id"] for race in plan["races"]
        } & seen_race_ids
        expected_coverage = {
            "external_horses": len(plan["horses"]),
            "external_races": len(plan["races"]),
            "external_results": len(plan["results"]),
            "external_histories": len(plan["histories"]),
            "canonical_identity_writes": 0,
            "out_of_scope_horse_writes": 0,
            "deduplicated_external_races": len(duplicate_races),
        }
        import_run = _verified_exact_row(
            ExternalDataImportRun.objects.filter(
                source=ExternalDataSource.THE_RACING_API,
                target_type="targeted_horse_artifact",
                parameters__manifest_sha256=manifest_sha,
                status=ExternalImportStatus.SUCCESS,
            ),
            {
                "horse_id": plan["horse_id"],
                "status": ExternalImportStatus.SUCCESS,
                "dry_run": False,
                "success_count": len(plan["races"]) + len(plan["horses"]),
                "failure_count": 0,
                "coverage_stats": expected_coverage,
            },
            label="ExternalDataImportRun",
        )
        if (
            import_run.finished_at is None
            or import_run.parameters.get("canonical_identity_writes") != 0
            or not str(import_run.parameters.get("artifact_root") or "").strip()
        ):
            raise RacingApiStagingError("ExternalDataImportRun evidence drift")
        verified_counts["import_runs"] += 1

        horse_objects: dict[str, ExternalHorse] = {}
        for horse_plan in plan["horses"]:
            profile = horse_plan.get("profile") or {}
            raw_name = horse_plan["raw_name"]
            plain_name, suffix = _split_name(raw_name)
            birth_date = None
            if profile.get("dob"):
                try:
                    birth_date = date.fromisoformat(str(profile["dob"]))
                except ValueError as exc:
                    raise RacingApiStagingError("invalid target horse DOB") from exc
            horse = _verified_exact_row(
                ExternalHorse.objects.filter(
                    source=ExternalDataSource.THE_RACING_API,
                    horse_id=horse_plan["horse_id"],
                ),
                {
                    "racing_region": horse_plan["region"],
                    "source_language": SourceLanguage.ENGLISH,
                    "horse_name": raw_name,
                    "horse_name_en": plain_name,
                    "normalized_horse_name": _normalized_name(raw_name),
                    "country": suffix,
                    "sex": str(profile.get("sex_code") or profile.get("sex") or ""),
                    "birth_date": birth_date,
                    "color": str(profile.get("colour") or ""),
                    "breeder_name": str(profile.get("breeder") or ""),
                    "father_name": str(profile.get("sire") or ""),
                    "mother_name": str(profile.get("dam") or ""),
                    "damsire_name": str(profile.get("damsire") or ""),
                    "sire_external_id": _parent_horse_id(profile.get("sire_id")),
                    "dam_external_id": _parent_horse_id(profile.get("dam_id")),
                    "damsire_external_id": _parent_horse_id(profile.get("damsire_id")),
                    **_profile_summary_fields(
                        horse_plan.get("page_profile_snapshot") or {}
                    ),
                    "raw_payload": dict(profile),
                },
                label="ExternalHorse",
            )
            horse_objects[horse_plan["horse_id"]] = horse
            verified_counts["external_horses"] += 1

            strict_name = _normalized_name(raw_name)
            _verified_exact_row(
                HorseNameVariant.objects.filter(
                    external_horse=horse,
                    source=ExternalDataSource.THE_RACING_API,
                    name_kind=HorseNameKind.SOURCE_DISPLAY,
                    normalized_strict=strict_name,
                ),
                {
                    "horse_profile_id": None,
                    "name_text": raw_name,
                    "language": SourceLanguage.ENGLISH,
                    "script": "latin",
                    "country_suffix": suffix,
                    "normalized_loose": strict_name,
                    "is_official": False,
                    "payload_sha256": str(profile.get("payload_sha256") or ""),
                },
                label="HorseNameVariant",
            )
            verified_counts["name_variants"] += 1

        race_objects: dict[str, ExternalRace] = {}
        for race_plan in plan["races"]:
            raw = race_plan["raw"]
            race = _verified_exact_row(
                ExternalRace.objects.filter(
                    source=ExternalDataSource.THE_RACING_API,
                    race_id=race_plan["race_id"],
                ),
                {
                    "racing_region": race_plan["region"],
                    "source_language": SourceLanguage.ENGLISH,
                    "race_name": str(raw.get("race_name") or ""),
                    "race_date": race_plan["raced_at"],
                    "course": str(raw.get("course") or ""),
                    "venue": str(raw.get("course_id") or ""),
                    "race_grade": str(raw.get("pattern") or ""),
                    "race_class": str(raw.get("class") or ""),
                    "surface": str(raw.get("surface") or ""),
                    "distance": str(raw.get("dist") or raw.get("dist_m") or ""),
                    "going": str(raw.get("going") or ""),
                    "raw_payload": raw,
                },
                label="ExternalRace",
            )
            race_objects[race_plan["race_id"]] = race
            if race_plan["race_id"] not in seen_race_ids:
                verified_counts["external_races"] += 1

        for result_plan in plan["results"]:
            runner = result_plan["runner"]
            _verified_exact_row(
                ExternalRaceResult.objects.filter(
                    source=ExternalDataSource.THE_RACING_API,
                    external_race_id=result_plan["race_id"],
                    result_key=result_plan["horse_id"],
                ),
                {
                    "racing_region": result_plan["race_region"],
                    "source_language": SourceLanguage.ENGLISH,
                    "race_id": race_objects[result_plan["race_id"]].pk,
                    "horse_id": result_plan["horse_id"],
                    "horse_name": result_plan["horse_name"],
                    "normalized_horse_name": _normalized_name(result_plan["horse_name"]),
                    "horse_number": str(runner.get("number") or ""),
                    "finish_position": result_plan["position"],
                    "finish_time": str(runner.get("time") or ""),
                    "margin": str(runner.get("btn") or runner.get("ovr_btn") or ""),
                    "odds_value": str(runner.get("sp") or runner.get("bsp") or ""),
                    "barrier": str(runner.get("draw") or ""),
                    "jockey_name": str(runner.get("jockey") or ""),
                    "trainer_name": str(runner.get("trainer") or ""),
                    "raw_payload": runner,
                },
                label="ExternalRaceResult",
            )
            verified_counts["external_results"] += 1

        target_horse = horse_objects[plan["horse_id"]]
        for history_plan in plan["histories"]:
            _verified_exact_row(
                ExternalHorseHistory.objects.filter(
                    source=ExternalDataSource.THE_RACING_API,
                    external_horse_id=plan["horse_id"],
                    history_key=history_plan["race_id"],
                ),
                {
                    "racing_region": race_objects[
                        history_plan["race_id"]
                    ].racing_region,
                    "source_language": SourceLanguage.ENGLISH,
                    "horse_id": target_horse.pk,
                    "external_race_id": history_plan["race_id"],
                    "race_name": history_plan["race_name"],
                    "raced_at": history_plan["raced_at"],
                    "horse_number": history_plan["horse_number"],
                    "finish_position": history_plan["position"],
                    "raw_payload": history_plan["raw"],
                },
                label="ExternalHorseHistory",
            )
            verified_counts["external_histories"] += 1
        seen_race_ids.update(race_objects)

    target_ids = [plan["horse_id"] for plan in plans]
    canonical_identity_count = HorseExternalIdentity.objects.filter(
        source=ExternalDataSource.THE_RACING_API,
        external_id__in=target_ids,
    ).count()
    if canonical_identity_count:
        raise RacingApiStagingError("canonical identity scope is not empty")
    active_lock_count = ExternalDataImportLock.objects.filter(
        source=ExternalDataSource.THE_RACING_API,
        locked_by_run__status=ExternalImportStatus.STARTED,
    ).count()
    active_run_count = ExternalDataImportRun.objects.filter(
        source=ExternalDataSource.THE_RACING_API,
        status=ExternalImportStatus.STARTED,
    ).count()
    if active_lock_count or active_run_count:
        raise RacingApiStagingError("The Racing API staging import is still active")

    return {
        "status": "verified",
        "database_writes": 0,
        "materialization_manifest_sha256": loaded["manifest_sha256"],
        "source_batch_manifest_sha256": loaded["source_batch_manifest_sha256"],
        "source_content_pool_manifest_sha256": loaded[
            "source_content_pool_manifest_sha256"
        ],
        "run_count": len(plans),
        "scope_stable_ids": target_ids,
        "verified_rows": verified_counts,
        "canonical_identity_count": canonical_identity_count,
        "active_import_lock_count": active_lock_count,
        "active_import_run_count": active_run_count,
    }


def _collection_preflight(
    bindings: list[tuple[Path, str]],
) -> dict[str, Any]:
    if not bindings or len(bindings) > MAX_COLLECTION_MATERIALIZATIONS:
        raise RacingApiStagingError(
            "materialization collection must contain between 1 and "
            f"{MAX_COLLECTION_MATERIALIZATIONS} parts"
        )
    seen_paths: set[Path] = set()
    seen_horse_ids: set[str] = set()
    race_payload_sha_by_id: dict[str, str] = {}
    rows = []
    for ordinal, (path, manifest_sha) in enumerate(bindings, 1):
        if not SHA256_RE.fullmatch(str(manifest_sha or "")):
            raise RacingApiStagingError("collection manifest SHA-256 is invalid")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise RacingApiStagingError("collection materialization is missing") from exc
        if path.is_symlink() or not resolved.is_dir() or resolved in seen_paths:
            raise RacingApiStagingError("collection materialization path is invalid")
        loaded = load_targeted_materialization(
            resolved,
            approved_manifest_sha256=manifest_sha,
        )
        plans = _materialization_plans(loaded)
        horse_ids = [plan["horse_id"] for plan in plans]
        duplicates = seen_horse_ids & set(horse_ids)
        if duplicates:
            raise RacingApiStagingError(
                "materialization collection contains a duplicate target horse"
            )
        for plan in plans:
            for race in plan["races"]:
                race_id = race["race_id"]
                payload_sha = _canonical_json_sha256(race["raw"])
                previous_sha = race_payload_sha_by_id.setdefault(race_id, payload_sha)
                if previous_sha != payload_sha:
                    raise RacingApiStagingError(
                        "materialization collection contains conflicting race payloads"
                    )
        dry_run = dry_run_targeted_materialization(
            resolved,
            approved_manifest_sha256=manifest_sha,
        )
        if dry_run.get("scope_stable_ids") != horse_ids:
            raise RacingApiStagingError("collection dry-run scope drift")
        rows.append(
            {
                "ordinal": ordinal,
                "path": resolved,
                "manifest_sha256": manifest_sha,
                "horse_ids": horse_ids,
                "dry_run": dry_run,
            }
        )
        seen_paths.add(resolved)
        seen_horse_ids.update(horse_ids)
    binding_payload = [
        {
            "ordinal": row["ordinal"],
            "manifest_sha256": row["manifest_sha256"],
            "horse_ids": row["horse_ids"],
        }
        for row in rows
    ]
    return {
        "rows": rows,
        "binding_sha256": _canonical_json_sha256(binding_payload),
        "scope_stable_ids": sorted(seen_horse_ids),
        "unique_race_count": len(race_payload_sha_by_id),
    }


def dry_run_targeted_materialization_collection(
    bindings: list[tuple[Path, str]],
) -> dict[str, Any]:
    preflight = _collection_preflight(bindings)
    reports = [row["dry_run"] for row in preflight["rows"]]
    return {
        "status": "collection_dry_run",
        "database_writes": 0,
        "commit_unit": "materialization_part",
        "collection_binding_sha256": preflight["binding_sha256"],
        "materialization_count": len(reports),
        "horse_count": len(preflight["scope_stable_ids"]),
        "unique_race_count": preflight["unique_race_count"],
        "scope_stable_ids": preflight["scope_stable_ids"],
        "parts": [
            {
                "ordinal": row["ordinal"],
                "manifest_sha256": row["manifest_sha256"],
                "run_count": row["dry_run"]["run_count"],
                "scope_stable_ids": row["horse_ids"],
                "action_totals": row["dry_run"]["action_totals"],
            }
            for row in preflight["rows"]
        ],
    }


def apply_targeted_materialization_collection(
    bindings: list[tuple[Path, str]],
    *,
    allow_write: bool = False,
) -> dict[str, Any]:
    if not allow_write or not _write_enabled(
        os.environ.get("RACING_API_STAGING_WRITE_ENABLED")
    ):
        raise RacingApiStagingError(
            "collection staging write gate requires allow_write and "
            "RACING_API_STAGING_WRITE_ENABLED=true"
        )
    preflight = _collection_preflight(bindings)
    results = []
    for row in preflight["rows"]:
        result = apply_targeted_materialization(
            row["path"],
            approved_manifest_sha256=row["manifest_sha256"],
            allow_write=True,
        )
        results.append(
            {
                "ordinal": row["ordinal"],
                "manifest_sha256": row["manifest_sha256"],
                **result,
            }
        )
    return {
        "status": (
            "applied"
            if any(row["status"] == "applied" for row in results)
            else "replayed"
        ),
        "database_writes": sum(row["database_writes"] for row in results),
        "commit_unit": "materialization_part",
        "collection_binding_sha256": preflight["binding_sha256"],
        "materialization_count": len(results),
        "horse_count": len(preflight["scope_stable_ids"]),
        "scope_stable_ids": preflight["scope_stable_ids"],
        "results": results,
    }


def verify_targeted_materialization_collection(
    bindings: list[tuple[Path, str]],
) -> dict[str, Any]:
    preflight = _collection_preflight(bindings)
    results = []
    for row in preflight["rows"]:
        result = verify_targeted_materialization(
            row["path"],
            approved_manifest_sha256=row["manifest_sha256"],
        )
        results.append(
            {
                "ordinal": row["ordinal"],
                "manifest_sha256": row["manifest_sha256"],
                **result,
            }
        )
    return {
        "status": "verified",
        "database_writes": 0,
        "commit_unit": "materialization_part",
        "collection_binding_sha256": preflight["binding_sha256"],
        "materialization_count": len(results),
        "horse_count": len(preflight["scope_stable_ids"]),
        "scope_stable_ids": preflight["scope_stable_ids"],
        "results": results,
    }

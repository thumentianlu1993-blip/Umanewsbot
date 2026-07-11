#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


class SourceCacheBudgetExceeded(RuntimeError):
    pass


def _positive_env(name: str) -> int:
    return max(0, int(os.environ.get(name, "0") or 0))


def _manifest_path(destination: Path) -> Path:
    configured = os.environ.get("RACE_EVENT_CRAWL_SOURCE_CACHE_MANIFEST", "").strip()
    return Path(configured) if configured else destination.parent / "source_cache_manifest.json"


def _cache_root(destination: Path) -> Path:
    configured = os.environ.get("RACE_EVENT_CRAWL_SOURCE_CACHE_ROOT", "").strip()
    return Path(configured).resolve() if configured else destination.parent.resolve()


def _read_manifest(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": "1.0", "files": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceCacheBudgetExceeded(f"source cache manifest is unreadable: {path}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "1.0"
        or not isinstance(payload.get("files"), dict)
    ):
        raise SourceCacheBudgetExceeded(f"source cache manifest is invalid: {path}")
    return payload


def _manifest_root(manifest_file: Path, manifest: dict) -> Path:
    root = Path(manifest.get("root") or manifest_file.parent).resolve()
    if root != manifest_file.parent.resolve():
        raise SourceCacheBudgetExceeded(
            f"source cache manifest root does not match manifest directory: {root}"
        )
    return root


def _safe_cache_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SourceCacheBudgetExceeded(f"source cache path escapes cache root: {relative}") from exc
    return candidate


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_source_cache(destination: str | Path, body: bytes, *, source_url: str) -> dict:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = _cache_root(path)
    try:
        relative = str(path.resolve().relative_to(root))
    except ValueError as exc:
        raise SourceCacheBudgetExceeded(f"source cache destination escapes configured root: {path}") from exc
    manifest_path = _manifest_path(path)
    if manifest_path.parent.resolve() != root:
        raise SourceCacheBudgetExceeded(
            "source cache manifest must be stored at the configured cache root"
        )
    lock_path = manifest_path.with_suffix(manifest_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        manifest = _read_manifest(manifest_path)
        files = manifest["files"]
        existing = files.get(relative) or {}
        protected_by = list(existing.get("protected_by") or [])
        body_sha256 = hashlib.sha256(body).hexdigest()
        if protected_by:
            if (
                not path.is_file()
                or path.stat().st_size != int(existing.get("size") or -1)
                or _file_sha256(path) != existing.get("sha256")
            ):
                raise SourceCacheBudgetExceeded(
                    f"protected source cache identity changed on disk: {relative}"
                )
            if body_sha256 != existing.get("sha256"):
                raise SourceCacheBudgetExceeded(
                    f"protected source cache cannot be overwritten: {relative}"
                )
        existing_size = int(existing.get("size") or 0)
        current_size = sum(int(item.get("size") or 0) for item in files.values())
        projected_size = current_size - existing_size + len(body)
        max_bytes = _positive_env("RACE_EVENT_CRAWL_MAX_SOURCE_CACHE_BYTES")
        if max_bytes and projected_size > max_bytes:
            raise SourceCacheBudgetExceeded(
                f"source cache byte budget exceeded: projected={projected_size} max={max_bytes}"
            )
        min_free = _positive_env("RACE_EVENT_CRAWL_MIN_FREE_DISK_BYTES")
        free_bytes = shutil.disk_usage(path.parent).free
        if min_free and free_bytes - len(body) < min_free:
            raise SourceCacheBudgetExceeded(
                f"source cache disk floor would be crossed: free={free_bytes} body={len(body)} min={min_free}"
            )
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_bytes(body)
            temporary.replace(path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        identity = {
            "path": relative,
            "size": len(body),
            "sha256": body_sha256,
            "source_url": source_url,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "protected_by": protected_by,
        }
        files[relative] = identity
        manifest.update(
            {
                "schema_version": "1.0",
                "root": str(root),
                "total_bytes": projected_size,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        _write_manifest(manifest_path, manifest)
        return identity


def write_source_cache_text(
    destination: str | Path,
    text: str,
    *,
    source_url: str,
    encoding: str = "utf-8",
) -> dict:
    return write_source_cache(destination, text.encode(encoding), source_url=source_url)


def protect_source_cache_files(manifest_path: str | Path, paths: list[str], *, artifact_sha256: str) -> None:
    if len(artifact_sha256) != 64 or any(character not in "0123456789abcdef" for character in artifact_sha256.lower()):
        raise SourceCacheBudgetExceeded("approved artifact SHA-256 is invalid")
    manifest_file = Path(manifest_path)
    lock_path = manifest_file.with_suffix(manifest_file.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        manifest = _read_manifest(manifest_file)
        root = _manifest_root(manifest_file, manifest)
        for path in paths:
            if path not in manifest["files"]:
                raise SourceCacheBudgetExceeded(f"cannot protect unknown source cache file: {path}")
            cache_file = _safe_cache_file(root, path)
            expected = manifest["files"][path]
            if (
                not cache_file.is_file()
                or cache_file.stat().st_size != int(expected.get("size") or -1)
                or _file_sha256(cache_file) != expected.get("sha256")
            ):
                raise SourceCacheBudgetExceeded(f"source cache identity changed before approval: {path}")
            protected = set(manifest["files"][path].get("protected_by") or [])
            protected.add(artifact_sha256)
            manifest["files"][path]["protected_by"] = sorted(protected)
        _write_manifest(manifest_file, manifest)


def cleanup_unprotected_source_cache(manifest_path: str | Path) -> list[str]:
    manifest_file = Path(manifest_path)
    lock_path = manifest_file.with_suffix(manifest_file.suffix + ".lock")
    removed = []
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        manifest = _read_manifest(manifest_file)
        root = _manifest_root(manifest_file, manifest)
        for relative, item in list(manifest["files"].items()):
            if item.get("protected_by"):
                continue
            _safe_cache_file(root, relative).unlink(missing_ok=True)
            removed.append(relative)
            del manifest["files"][relative]
        manifest["total_bytes"] = sum(int(item.get("size") or 0) for item in manifest["files"].values())
        _write_manifest(manifest_file, manifest)
    return removed

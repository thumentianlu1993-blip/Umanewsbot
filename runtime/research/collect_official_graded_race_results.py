#!/usr/bin/env python3
"""按受审 manifest 有界采集新增地区官方分级赛赛果。

本工具只写 artifact/checkpoint，不连接 Django 或生产数据库。临时网络错误返回
75；manifest、URL、解析和身份错误属于确定性错误并返回 1。
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib import error, request

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.research.official_graded_race_sources import (  # noqa: E402
    POLICIES,
    OfficialSourceError,
    canonical_provider_url_identity,
    derive_data_url,
    parse_official_results,
    validate_provider_url,
)
from runtime.research import official_graded_race_sources as official_sources  # noqa: E402


SCHEMA_VERSION = 1
TOOL_VERSION = "official-graded-results.v1"
SAFE_STOP_CODE = 75
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}
GRADE_RE = re.compile(r"^G[123]$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class RunnerError(RuntimeError):
    pass


class RetryableNetworkError(RunnerError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _regular_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise RunnerError(f"manifest must be a regular non-symlink file: {path}")
    return path.resolve(strict=True)


def load_manifest(path: Path, *, expected_sha256: str) -> tuple[dict, str]:
    path = _regular_file(path)
    actual_sha = sha256_file(path)
    if not SHA_RE.fullmatch(expected_sha256) or actual_sha != expected_sha256:
        raise RunnerError("manifest SHA-256 mismatch")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError("manifest JSON is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise RunnerError("manifest schema drift")
    year = manifest.get("year")
    if not isinstance(year, int) or not 1998 <= year <= 2100:
        raise RunnerError("manifest year is invalid")
    catalog_sha = manifest.get("catalog_sha256")
    if not isinstance(catalog_sha, str) or not SHA_RE.fullmatch(catalog_sha):
        raise RunnerError("manifest catalog SHA-256 is invalid")
    reviewed_mapping_sha = manifest.get("reviewed_mapping_sha256")
    if not isinstance(reviewed_mapping_sha, str) or not SHA_RE.fullmatch(reviewed_mapping_sha):
        raise RunnerError("manifest reviewed mapping SHA-256 is invalid")
    races = manifest.get("races")
    if not isinstance(races, list) or not races:
        raise RunnerError("manifest races must be a non-empty list")
    seen_keys: set[str] = set()
    seen_urls: set[tuple[str, str]] = set()
    normalized = []
    for item in races:
        if not isinstance(item, dict):
            raise RunnerError("manifest race entry must be an object")
        race_key = str(item.get("race_key") or "").strip()
        provider = str(item.get("provider") or "").strip()
        result_url = str(item.get("result_url") or "").strip()
        grade = str(item.get("grade") or "").strip().upper()
        if not race_key or race_key in seen_keys:
            raise RunnerError("manifest race_key is blank or duplicated")
        if provider not in POLICIES:
            raise RunnerError(f"manifest provider is unsupported: {provider}")
        validate_provider_url(provider, result_url, year=year)
        if not GRADE_RE.fullmatch(grade):
            raise RunnerError(f"manifest grade is invalid: {race_key}")
        policy = POLICIES[provider]
        expected_region = str(item.get("region") or "").strip()
        expected_country = str(item.get("country") or "").strip()
        if expected_region != policy.region or expected_country != policy.country:
            raise RunnerError(f"manifest provider geography mismatch: {race_key}")
        local_date = str(item.get("local_date") or "").strip()
        try:
            parsed_date = date.fromisoformat(local_date)
        except ValueError as exc:
            raise RunnerError(f"manifest local_date is invalid: {race_key}") from exc
        if parsed_date.year != year:
            raise RunnerError(f"manifest local_date year drift: {race_key}")
        url_key = (provider, canonical_provider_url_identity(result_url))
        if url_key in seen_urls:
            raise RunnerError("manifest provider/result_url is duplicated")
        seen_keys.add(race_key)
        seen_urls.add(url_key)
        normalized.append(
            {
                "race_key": race_key,
                "provider": provider,
                "result_url": result_url,
                "region": policy.region,
                "country": policy.country,
                "grade": grade,
                "race_name": str(item.get("race_name") or "").strip(),
                "local_date": local_date,
            }
        )
    provider_counts: dict[str, int] = {}
    for item in normalized:
        provider_counts[item["provider"]] = provider_counts.get(item["provider"], 0) + 1
    for provider, count in provider_counts.items():
        if count > POLICIES[provider].request_budget:
            raise RunnerError(f"manifest exceeds provider request budget: {provider}")
    return {**manifest, "races": normalized}, actual_sha


class StrictRedirectHandler(request.HTTPRedirectHandler):
    def __init__(self, provider: str, year: int):
        super().__init__()
        self.provider = provider
        self.year = year

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_provider_url(self.provider, newurl, year=self.year)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(provider: str, page_url: str, *, year: int, timeout: int) -> tuple[bytes, str]:
    data_url = derive_data_url(provider, page_url, year=year)
    validate_provider_url(provider, data_url, year=year)
    opener = request.build_opener(StrictRedirectHandler(provider, year))
    req = request.Request(
        data_url,
        headers={"User-Agent": "UmaFansBot/1.0 (+https://umafans.run; official graded result audit)"},
    )
    try:
        with opener.open(req, timeout=timeout) as response:
            final_url = validate_provider_url(provider, response.geturl(), year=year)
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise RunnerError(f"official response exceeds byte budget: {data_url}")
            return body, final_url
    except error.HTTPError as exc:
        if exc.code in RETRYABLE_HTTP:
            raise RetryableNetworkError(f"HTTP {exc.code}: {data_url}") from exc
        raise RunnerError(f"deterministic HTTP {exc.code}: {data_url}") from exc
    except (
        error.URLError,
        TimeoutError,
        ConnectionResetError,
        http.client.IncompleteRead,
        http.client.RemoteDisconnected,
        socket.timeout,
        ssl.SSLError,
    ) as exc:
        raise RetryableNetworkError(f"temporary network error: {data_url}: {type(exc).__name__}") from exc


def _checkpoint_identity(manifest_sha: str, year: int) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "tool_sha256": sha256_file(Path(__file__)),
        "parser_policy_sha256": sha256_file(Path(official_sources.__file__)),
        "manifest_sha256": manifest_sha,
        "year": year,
    }


def _load_checkpoint(path: Path, identity: dict, *, resume: bool) -> dict:
    if not path.exists():
        return {**identity, "items": {}, "provider_request_counts": {}}
    if path.is_symlink() or not path.is_file():
        raise RunnerError("checkpoint must be a regular non-symlink file")
    if not resume:
        raise RunnerError("checkpoint exists but --resume was not supplied")
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError("checkpoint JSON is invalid") from exc
    for key, value in identity.items():
        if checkpoint.get(key) != value:
            raise RunnerError(f"checkpoint identity drift: {key}")
    if not isinstance(checkpoint.get("items"), dict):
        raise RunnerError("checkpoint items are invalid")
    if not isinstance(checkpoint.get("provider_request_counts"), dict):
        raise RunnerError("checkpoint request counts are invalid")
    return checkpoint


def _write_checkpoint(path: Path, checkpoint: dict) -> None:
    atomic_write(path, canonical_json_bytes(checkpoint))


def _validate_checkpoint_state(checkpoint: dict, manifest: dict) -> None:
    races = {race["race_key"]: race for race in manifest["races"]}
    items = checkpoint["items"]
    if not set(items).issubset(races):
        raise RunnerError("checkpoint contains race outside manifest")
    for race_key, item in items.items():
        if not isinstance(item, dict) or item.get("status") not in {
            "success",
            "retryable_error",
            "deterministic_error",
        }:
            raise RunnerError(f"checkpoint item status is invalid: {race_key}")
    manifest_providers = {race["provider"] for race in manifest["races"]}
    counts = checkpoint["provider_request_counts"]
    if not set(counts).issubset(manifest_providers):
        raise RunnerError("checkpoint contains provider outside manifest")
    for provider, value in counts.items():
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= POLICIES[provider].request_budget:
            raise RunnerError(f"checkpoint provider request count is invalid: {provider}")


def _cache_path(root: Path, race_key: str) -> Path:
    digest = hashlib.sha256(race_key.encode()).hexdigest()
    return root / "source" / f"{digest}.response"


def _checkpoint_cache_path(root: Path, race_key: str, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise RunnerError(f"checkpoint cache path is invalid: {race_key}")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise RunnerError(f"checkpoint cache path escapes output root: {race_key}")
    candidate = root / relative
    expected = _cache_path(root, race_key)
    if candidate != expected:
        raise RunnerError(f"checkpoint cache path is not race-bound: {race_key}")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RunnerError(f"checkpoint cache path contains symlink: {race_key}")
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise RunnerError(f"checkpoint cache path escapes output root: {race_key}")
    return candidate


def run(args) -> dict:
    if not args.allow_network:
        raise RunnerError("official result collection requires explicit --allow-network")
    if args.timeout <= 0 or args.request_interval_seconds < 0 or args.time_budget_seconds < 0:
        raise RunnerError("timeout must be positive and timing budgets must be non-negative")
    manifest, manifest_sha = load_manifest(Path(args.manifest), expected_sha256=args.manifest_sha256)
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    checkpoint_path = root / "checkpoint.json"
    identity = _checkpoint_identity(manifest_sha, manifest["year"])
    checkpoint = _load_checkpoint(checkpoint_path, identity, resume=args.resume)
    _validate_checkpoint_state(checkpoint, manifest)
    started = time.monotonic()
    last_request_at: float | None = None
    for race in manifest["races"]:
        race_key = race["race_key"]
        previous = checkpoint["items"].get(race_key)
        if previous and previous.get("status") == "success":
            cache = _checkpoint_cache_path(root, race_key, previous.get("cache_path"))
            if cache.is_symlink() or not cache.is_file() or sha256_file(cache) != previous.get("cache_sha256"):
                raise RunnerError(f"checkpoint cache identity mismatch: {race_key}")
            continue
        if previous and previous.get("status") == "deterministic_error":
            raise RunnerError(
                f"checkpoint contains deterministic error for {race_key}: "
                f"{previous.get('error') or 'unknown error'}"
            )
        if previous and previous.get("status") not in {"retryable_error"}:
            raise RunnerError(f"checkpoint item status is invalid: {race_key}")
        if args.time_budget_seconds and time.monotonic() - started >= args.time_budget_seconds:
            _write_checkpoint(checkpoint_path, checkpoint)
            raise RetryableNetworkError("time budget reached at checkpoint boundary")
        try:
            provider = race["provider"]
            request_count = int(checkpoint["provider_request_counts"].get(provider, 0))
            if request_count >= POLICIES[provider].request_budget:
                raise RunnerError(f"cumulative provider request budget exhausted: {provider}")
            if last_request_at is not None and args.request_interval_seconds:
                remaining = args.request_interval_seconds - (time.monotonic() - last_request_at)
                if remaining > 0:
                    time.sleep(remaining)
            # Write ahead so a crash or timeout cannot erase a network attempt.
            checkpoint["provider_request_counts"][provider] = request_count + 1
            _write_checkpoint(checkpoint_path, checkpoint)
            last_request_at = time.monotonic()
            body, final_url = fetch(
                provider, race["result_url"], year=manifest["year"], timeout=args.timeout
            )
            participants = parse_official_results(race["provider"], body.decode("utf-8", errors="replace"))
        except RetryableNetworkError:
            checkpoint["items"][race_key] = {"status": "retryable_error"}
            _write_checkpoint(checkpoint_path, checkpoint)
            raise
        except RunnerError as exc:
            checkpoint["items"][race_key] = {"status": "deterministic_error", "error": str(exc)}
            _write_checkpoint(checkpoint_path, checkpoint)
            raise
        except (OfficialSourceError, UnicodeError) as exc:
            checkpoint["items"][race_key] = {"status": "deterministic_error", "error": str(exc)}
            _write_checkpoint(checkpoint_path, checkpoint)
            raise RunnerError(f"deterministic parse error for {race_key}: {exc}") from exc
        cache_path = _cache_path(root, race_key)
        if cache_path.exists():
            if cache_path.is_symlink() or not cache_path.is_file():
                raise RunnerError(f"source cache must be a regular non-symlink file: {race_key}")
            if sha256_file(cache_path) != sha256_bytes(body):
                raise RunnerError(f"source cache content drift: {race_key}")
        else:
            atomic_write(cache_path, body)
        checkpoint["items"][race_key] = {
            "status": "success",
            "cache_path": str(cache_path.relative_to(root)),
            "cache_sha256": sha256_bytes(body),
            "final_url": final_url,
            "participant_count": len(participants),
        }
        _write_checkpoint(checkpoint_path, checkpoint)

    rows = []
    sources = []
    for race in manifest["races"]:
        item = checkpoint["items"].get(race["race_key"])
        if not item or item.get("status") != "success":
            raise RunnerError(f"incomplete checkpoint at finalize: {race['race_key']}")
        cache_path = _checkpoint_cache_path(root, race["race_key"], item.get("cache_path"))
        if cache_path.is_symlink() or not cache_path.is_file() or sha256_file(cache_path) != item["cache_sha256"]:
            raise RunnerError(f"source cache identity mismatch at finalize: {race['race_key']}")
        participants = parse_official_results(
            race["provider"], cache_path.read_text(encoding="utf-8", errors="replace")
        )
        source = {**race, **item}
        sources.append(source)
        for participant in participants:
            rows.append(
                {
                    **race,
                    **participant,
                    "source_url": item["final_url"],
                    "source_cache_sha256": item["cache_sha256"],
                    "parser_version": TOOL_VERSION,
                }
            )
    rows.sort(key=lambda row: (row["race_key"], row["finish_position"] is None, row["finish_position"] or 0, row.get("participant_status", ""), row["horse_name"]))
    output = root / "final"
    atomic_write(output / "official_participants.jsonl", b"".join(canonical_json_bytes(row) for row in rows))
    atomic_write(output / "official_sources.jsonl", b"".join(canonical_json_bytes(row) for row in sources))
    summary = {
        **identity,
        "status": "complete",
        "race_count": len(sources),
        "participant_count": len(rows),
        "provider_counts": {
            provider: sum(source["provider"] == provider for source in sources)
            for provider in sorted({source["provider"] for source in sources})
        },
        "files": {
            name: sha256_file(output / name)
            for name in ("official_participants.jsonl", "official_sources.jsonl")
        },
    }
    atomic_write(output / "summary.json", canonical_json_bytes(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="受审 manifest 驱动的新增地区官方分级赛赛果采集器")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--request-interval-seconds", type=float, default=2.0)
    parser.add_argument("--time-budget-seconds", type=int, default=0)
    args = parser.parse_args()
    try:
        result = run(args)
    except RetryableNetworkError as exc:
        print(str(exc), file=os.sys.stderr)
        return SAFE_STOP_CODE
    except (RunnerError, OfficialSourceError, OSError, ValueError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

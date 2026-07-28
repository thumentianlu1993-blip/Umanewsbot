#!/usr/bin/env python3
"""Collect 2026 graded-race top-five finishers from UmaFans public pages.

This is a read-only research utility. It does not import Django models and does
not write to the UmaFans database. The collector:

1. discovers published race pages through the public sitemap;
2. keeps completed 2026 graded races in Japan, Hong Kong, the United States,
   the United Kingdom and France;
3. extracts official positions 1-5 from the public result tables;
4. enriches horse names from public horse-profile search pages;
5. resolves likely Wikipedia/Wikidata identities with explicit confidence
   states instead of forcing an uncertain match;
6. writes auditable CSV/JSON artifacts.

The output represents the current public, data-quality-complete UmaFans race
pages at collection time. It must not be described as proof that every race in
an external global catalog is present.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger("graded-top5-wikipedia")

REGION_LABELS = {
    "日本": "japan",
    "中国香港": "hong_kong",
    "香港": "hong_kong",
    "美国": "united_states",
    "英国": "united_kingdom",
    "法国": "france",
}
REGION_OUTPUT = {
    "japan": "日本",
    "hong_kong": "中国香港",
    "united_states": "美国",
    "united_kingdom": "英国",
    "france": "法国",
}
TARGET_REGIONS = set(REGION_OUTPUT)
TARGET_STANDARD_GRADES = {"G1", "G2", "G3"}
TARGET_JAPAN_GRADES = {
    "G1",
    "G2",
    "G3",
    "J-G1",
    "J-G2",
    "J-G3",
    "JPN1",
    "JPN2",
    "JPN3",
}
WIKI_LANG_PRIORITY = ("zh", "ja", "en", "fr")
WIKI_SITE_KEYS = {"zh": "zhwiki", "ja": "jawiki", "en": "enwiki", "fr": "frwiki"}
HORSE_DESCRIPTION_KEYWORDS = (
    "racehorse",
    "race horse",
    "thoroughbred",
    "競走馬",
    "赛马",
    "賽馬",
    "cheval de course",
    "pur-sang",
)
COUNTRY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,3})\)\s*$")
DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
POSITION_RE = re.compile(r"^\s*(\d+)")
HAN_RE = re.compile(r"[\u3400-\u9fff]")
KANA_RE = re.compile(r"[\u3040-\u30ff]")
LATIN_RE = re.compile(r"[A-Za-z]")
SCHEMA_VERSION = 2
PARSER_VERSION = "race-page-v2"
SCORER_VERSION = "wikidata-score-v1"
SAFE_STOP_EXIT_CODE = 75
TERMINAL_ITEM_STATUSES = {"success", "skipped", "permanent_error", "not_found"}
RETRYABLE_ITEM_STATUSES = {"retryable_error"}
UMAFANS_HOSTS = {"umafans.run", "www.umafans.run"}
WIKIMEDIA_HOSTS = {
    "www.wikidata.org",
    "wikidata.org",
    "zh.wikipedia.org",
    "ja.wikipedia.org",
    "en.wikipedia.org",
    "fr.wikipedia.org",
}


class ProfileDetailError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_space(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    return " ".join(value.replace("\u3000", " ").split())


def normalize_identity(value: str) -> str:
    value = normalize_space(value).casefold()
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", value)


def strip_country_suffix(value: str) -> str:
    return COUNTRY_SUFFIX_RE.sub("", normalize_space(value)).strip()


def contains_han(value: str) -> bool:
    return bool(HAN_RE.search(value or ""))


def contains_kana(value: str) -> bool:
    return bool(KANA_RE.search(value or ""))


def contains_latin(value: str) -> bool:
    return bool(LATIN_RE.search(value or ""))


def normalize_grade(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").upper().strip()
    replacements = {
        "Ⅰ": "1",
        "Ⅱ": "2",
        "Ⅲ": "3",
        "I": "1",
        "II": "2",
        "III": "3",
        "・": "-",
        "—": "-",
        "–": "-",
        "−": "-",
    }
    # Replace the longer Roman forms first before replacing standalone I.
    for source, target in (("III", "3"), ("II", "2"), ("Ⅰ", "1"), ("Ⅱ", "2"), ("Ⅲ", "3")):
        value = value.replace(source, target)
    value = value.replace("・", "-").replace("—", "-").replace("–", "-").replace("−", "-")
    value = re.sub(r"\bGRADE\s*", "G", value)
    value = re.sub(r"\bGROUP\s*", "G", value)
    value = re.sub(r"\s+", "", value)
    value = value.replace("JPNⅠ", "JPN1").replace("JPNⅡ", "JPN2").replace("JPNⅢ", "JPN3")
    value = value.replace("JPNI", "JPN1").replace("JPNII", "JPN2").replace("JPNIII", "JPN3")
    value = value.replace("JG1", "J-G1").replace("JG2", "J-G2").replace("JG3", "J-G3")
    value = value.replace("J-GRADE", "J-G")
    match = re.search(r"JPN[- ]?([123])", value)
    if match:
        return f"JPN{match.group(1)}"
    match = re.search(r"J-?G([123])", value)
    if match:
        return f"J-G{match.group(1)}"
    match = re.search(r"(?:^|[^A-Z])G([123])(?:$|[^0-9])", value)
    if match:
        return f"G{match.group(1)}"
    return value


def grade_is_in_scope(region: str, grade: str) -> bool:
    normalized = normalize_grade(grade)
    if region == "japan":
        return normalized in TARGET_JAPAN_GRADES
    return normalized in TARGET_STANDARD_GRADES


def safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return value or "item"


def wiki_url(language: str, title: str) -> str:
    return f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='():,_-')}"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def keys_sha256(keys: Iterable[str]) -> str:
    return sha256_bytes(canonical_json_bytes(sorted(set(str(key) for key in keys))))


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Durably replace path; incomplete sibling temp files are never inputs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def atomic_write_text(path: Path, value: str, *, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, value.encode(encoding))


def stable_shard(key: str, shard_count: int) -> int:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % shard_count


def merge_keyed_records(groups: Iterable[Iterable[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: dict[str, tuple[bytes, dict[str, Any]]] = {}
    for group in groups:
        for record in group:
            key = str(record.get("key", ""))
            if not key:
                raise ValueError("record key is required")
            encoded = canonical_json_bytes(record)
            previous = merged.get(key)
            if previous and previous[0] != encoded:
                raise ValueError(f"conflict for key {key}")
            merged[key] = (encoded, record)
    return [merged[key][1] for key in sorted(merged)]


def require_exact_coverage(records: Iterable[dict[str, Any]], expected_keys: Iterable[str], label: str) -> None:
    actual = [str(record.get("key", "")) for record in records]
    expected = sorted(set(expected_keys))
    if len(actual) != len(set(actual)):
        raise ValueError(f"{label} duplicate key coverage")
    if sorted(actual) != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise ValueError(f"{label} incomplete coverage missing={missing[:5]} extra={extra[:5]}")


def canonical_lookup_key(region: str, display_name: str, profile_href: str, _context: str = "") -> str:
    if profile_href:
        parsed = urlparse(urljoin("https://umafans.run/", profile_href))
        host = (parsed.hostname or "").casefold()
        identity = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
        return f"{region}|{host}|{normalize_identity(identity)}"
    return f"{region}|{normalize_identity(display_name)}"


def validate_request_url(url: str, *, allowed_hosts: set[str]) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL scheme is not allowed")
    if parsed.username or parsed.password:
        raise ValueError("URL userinfo is not allowed")
    host = (parsed.hostname or "").casefold()
    if host not in {value.casefold() for value in allowed_hosts}:
        raise ValueError("URL host is not allowed")
    if parsed.port is not None:
        allowed_port = (parsed.scheme == "http" and parsed.port == 80) or (
            parsed.scheme == "https" and parsed.port == 443
        )
        if not allowed_port:
            raise ValueError("URL port is not allowed")
    return url


def ensure_run_manifest(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    if path.exists():
        actual = json.loads(path.read_text(encoding="utf-8"))
        if canonical_json_bytes(actual) != canonical_json_bytes(expected):
            raise ValueError("run manifest drift")
        return actual
    atomic_write_json(path, expected)
    return expected


def resolution_outcome(
    *, search_requests: list[dict[str, Any]], entity_requests: list[dict[str, Any]]
) -> dict[str, Any]:
    errors = sorted(
        {
            str(item.get("error_code") or item.get("status"))
            for item in [*search_requests, *entity_requests]
            if item.get("status") != "success"
        }
    )
    if errors:
        return {
            "resolution_state": "error",
            "error_code": "|".join(errors),
            "wikipedia_match_status": "",
        }
    candidates = sorted(
        {
            str(qid)
            for request in search_requests
            for qid in request.get("candidates", [])
            if qid
        }
    )
    if not candidates:
        return {
            "resolution_state": "resolved",
            "error_code": "",
            "wikipedia_match_status": "no_page",
        }
    present = {str(item.get("qid")) for item in entity_requests}
    if set(candidates) - present:
        return {
            "resolution_state": "error",
            "error_code": "missing_entity_checkpoint",
            "wikipedia_match_status": "",
        }
    return {"resolution_state": "ready_to_score", "error_code": "", "wikipedia_match_status": ""}


class StageStore:
    def __init__(
        self,
        root: Path,
        *,
        stage: str,
        shard_index: int | None = None,
        shard_count: int = 1,
        manifest_sha256: str = "unit-test",
        upstream_indexes: dict[str, str] | None = None,
        input_keys_sha256: str = "",
    ):
        self.root = root
        self.stage = stage
        self.shard_index = shard_index
        self.shard_count = shard_count
        self.manifest_sha256 = manifest_sha256
        self.upstream_indexes = dict(sorted((upstream_indexes or {}).items()))
        self.input_keys_sha256 = input_keys_sha256
        merged_paths = {
            "profiles_merged": ("profiles", "merged"),
            "wikidata_search_merged": ("wikidata_search", "merged"),
            "wikidata_entities_merged": ("wikidata_entities", "merged"),
            "scored_horses_merged": ("scored_horses", "merged"),
        }
        base = root / "stages"
        for part in merged_paths.get(stage, (stage,)):
            base /= part
        if shard_index is not None:
            base = base / "shards" / str(shard_index)
        self.path = base
        self.items_dir = base / (
            "entities"
            if stage in {"wikidata_entities", "wikidata_entities_merged"}
            else "items"
        )
        self.index_path = base / "index.json"
        self.progress_path = base / "progress.json"

    @staticmethod
    def filename(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"

    def item_path(self, key: str) -> Path:
        return self.items_dir / self.filename(key)

    def load_item(self, key: str) -> dict[str, Any] | None:
        path = self.item_path(key)
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("key") != key and value.get("qid") != key:
            raise ValueError(f"checkpoint key mismatch for {key}")
        return value

    def save_item(self, key: str, value: dict[str, Any]) -> None:
        if value.get("key") not in {None, key} or value.get("qid") not in {None, key}:
            raise ValueError(f"checkpoint key mismatch for {key}")
        payload = dict(value)
        payload.setdefault("key", key)
        path = self.item_path(key)
        atomic_write_json(path, payload)
        print(f"CHECKPOINT_SAVED path={path}", flush=True)

    def rebuild_index(
        self, *, upstream_sha256: str = "", request_count: int | None = None
    ) -> dict[str, Any]:
        if upstream_sha256:
            if self.upstream_indexes and upstream_sha256 not in self.upstream_indexes.values():
                raise ValueError("stage upstream index binding conflict")
            if not self.upstream_indexes:
                self.upstream_indexes = {"upstream": upstream_sha256}
        prior_request_count = 0
        if self.index_path.exists():
            prior = json.loads(self.index_path.read_text(encoding="utf-8"))
            prior_request_count = int(prior.get("request_count", 0))
        entries = []
        if self.items_dir.exists():
            for path in sorted(self.items_dir.glob("*.json")):
                payload = path.read_bytes()
                item = json.loads(payload)
                key = str(item.get("key") or item.get("qid") or "")
                if not key or path.name != self.filename(key):
                    raise ValueError(f"invalid checkpoint item {path}")
                entries.append(
                    {
                        "key": key,
                        "path": path.relative_to(self.root).as_posix(),
                        "status": item.get("status", ""),
                        "sha256": sha256_bytes(payload),
                    }
                )
        entries.sort(key=lambda item: item["key"])
        index = {
            "schema_version": SCHEMA_VERSION,
            "stage": self.stage,
            "shard_index": self.shard_index,
            "shard_count": self.shard_count,
            "manifest_sha256": self.manifest_sha256,
            "upstream_indexes": self.upstream_indexes,
            "input_keys_sha256": self.input_keys_sha256 or keys_sha256(
                item["key"] for item in entries
            ),
            "tool_identity": current_tool_identity_record(),
            "request_count": prior_request_count if request_count is None else request_count,
            "items": entries,
            "items_sha256": sha256_bytes(canonical_json_bytes(entries)),
        }
        atomic_write_json(self.index_path, index)
        return index

    def verify_index(self) -> dict[str, Any]:
        index = json.loads(self.index_path.read_text(encoding="utf-8"))
        if index.get("stage") != self.stage or index.get("shard_count") != self.shard_count:
            raise ValueError("stage index drift")
        if self.shard_index != index.get("shard_index"):
            raise ValueError("stage shard drift")
        if index.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("stage schema drift")
        if index.get("manifest_sha256") != self.manifest_sha256:
            raise ValueError("stage manifest drift")
        if index.get("upstream_indexes") != self.upstream_indexes:
            raise ValueError("stage upstream index drift")
        if self.input_keys_sha256 and index.get("input_keys_sha256") != self.input_keys_sha256:
            raise ValueError("stage input key drift")
        if index.get("tool_identity") != current_tool_identity_record():
            raise ValueError("stage tool identity drift")
        if not isinstance(index.get("request_count"), int) or index["request_count"] < 0:
            raise ValueError("stage request count drift")
        entries = index.get("items", [])
        if entries != sorted(entries, key=lambda item: item["key"]):
            raise ValueError("stage index is not sorted")
        if sha256_bytes(canonical_json_bytes(entries)) != index.get("items_sha256"):
            raise ValueError("stage index summary drift")
        seen: set[str] = set()
        for entry in entries:
            if entry["key"] in seen:
                raise ValueError("duplicate key in stage index")
            seen.add(entry["key"])
            path = self.root / entry["path"]
            if path != self.item_path(entry["key"]):
                raise ValueError(f"checkpoint path drift for {entry['key']}")
            if sha256_bytes(path.read_bytes()) != entry["sha256"]:
                raise ValueError(f"checkpoint content drift for {entry['key']}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if str(payload.get("key") or payload.get("qid") or "") != entry["key"]:
                raise ValueError(f"checkpoint key drift for {entry['key']}")
            if payload.get("status", "") != entry.get("status", ""):
                raise ValueError(f"checkpoint status drift for {entry['key']}")
        return index

    def save_progress(self, value: dict[str, Any]) -> None:
        atomic_write_json(self.progress_path, value)


def run_checkpointed_items(
    keys: Iterable[str],
    *,
    store: StageStore,
    process: Callable[[str], dict[str, Any]],
    resume: bool,
    start_index: int = 0,
    limit: int = 0,
    time_budget_seconds: float = 0,
    checkpoint_every: int = 25,
    request_counter: Callable[[], int] | None = None,
    request_counter_start: int | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], str] = utc_now_iso,
) -> dict[str, Any]:
    planned = [
        key
        for key in sorted(set(keys))
        if stable_shard(key, store.shard_count) == (store.shard_index or 0)
    ]
    selected = planned[start_index:]
    if limit:
        selected = selected[:limit]
    selected_digest = keys_sha256(planned)
    if store.input_keys_sha256 and store.input_keys_sha256 != selected_digest:
        raise ValueError("stage input key drift")
    store.input_keys_sha256 = selected_digest
    prior_requests = 0
    prior_index: dict[str, Any] | None = None
    if store.index_path.exists():
        prior_index = store.verify_index()
        prior_requests = int(prior_index.get("request_count", 0))
        if resume:
            indexed_keys = {str(item["key"]) for item in prior_index.get("items", [])}
            planned_keys = set(planned)
            if not indexed_keys <= planned_keys:
                raise ValueError("stage checkpoint coverage drift")
            if store.progress_path.exists():
                progress_bytes = store.progress_path.read_bytes()
                try:
                    prior_progress = json.loads(progress_bytes)
                except (TypeError, ValueError) as exc:
                    raise ValueError("stage progress invalid for resume") from exc
                if not isinstance(prior_progress, dict):
                    raise ValueError("stage progress invalid for resume")
                if prior_progress.get("stage") != store.stage:
                    raise ValueError("stage progress stage drift")
                progress_total = prior_progress.get("total")
                progress_processed = prior_progress.get("processed")
                progress_requests = prior_progress.get("request_count")
                if (
                    isinstance(progress_total, bool)
                    or not isinstance(progress_total, int)
                    or progress_total != len(planned)
                ):
                    raise ValueError("stage progress total drift")
                if (
                    isinstance(progress_processed, bool)
                    or not isinstance(progress_processed, int)
                    or not 0 <= progress_processed <= progress_total
                ):
                    raise ValueError("stage progress processed drift")
                if (
                    isinstance(progress_requests, bool)
                    or not isinstance(progress_requests, int)
                    or progress_requests < 0
                ):
                    raise ValueError("stage progress request count drift")
                safe_stopped_value = prior_progress.get("safe_stopped")
                if not isinstance(safe_stopped_value, bool):
                    raise ValueError("stage progress safe-stop drift")
                progress_index_sha = prior_progress.get("index_sha256")
                if not isinstance(progress_index_sha, str) or not re.fullmatch(
                    r"[0-9a-f]{64}", progress_index_sha
                ):
                    raise ValueError("stage progress index drift")
                progress_matches_index = progress_index_sha == sha256_bytes(
                    store.index_path.read_bytes()
                )
                if progress_matches_index:
                    if progress_requests != prior_requests:
                        raise ValueError("stage progress request count drift")
                    if progress_processed != len(indexed_keys):
                        raise ValueError("stage progress coverage drift")
                    if not safe_stopped_value:
                        if (
                            progress_processed != progress_total
                            or indexed_keys != planned_keys
                        ):
                            raise ValueError("completed stage coverage drift")
                        return prior_progress
                else:
                    if (
                        not safe_stopped_value
                        or progress_processed >= len(indexed_keys)
                    ):
                        raise ValueError("stage progress index drift")
                    if progress_requests > prior_requests:
                        raise ValueError("stage progress request count drift")
                    # The verified index atomically advanced beyond the last
                    # safe-stopped progress. Continue from its terminal items;
                    # never infer that this unknown window was completed.
            elif len(indexed_keys) >= len(planned):
                raise ValueError("stage progress missing for complete index")
    elif resume and store.progress_path.exists():
        raise ValueError("stage index missing for resume")
    request_start = (
        request_counter_start
        if request_counter_start is not None
        else (request_counter() if request_counter else 0)
    )
    started = clock()
    processed = cached = succeeded = failed = 0
    safe_stopped = False
    last_key = ""
    for key in selected:
        if time_budget_seconds and clock() - started >= time_budget_seconds:
            safe_stopped = True
            break
        existing = store.load_item(key)
        if resume and existing and existing.get("status") in TERMINAL_ITEM_STATUSES:
            cached += 1
            continue
        try:
            value = process(key)
            value.setdefault("status", "success")
        except Exception as exc:
            value = {
                "key": key,
                "status": "retryable_error",
                "error_code": type(exc).__name__,
                "error": str(exc),
            }
        store.save_item(key, value)
        processed += 1
        last_key = key
        if value["status"] == "success":
            succeeded += 1
        elif value["status"] in RETRYABLE_ITEM_STATUSES | {"permanent_error"}:
            failed += 1
        if processed % max(1, checkpoint_every) == 0:
            current_requests = prior_requests + (
                request_counter() - request_start if request_counter else 0
            )
            store.rebuild_index(request_count=current_requests)
    request_count = prior_requests + (
        request_counter() - request_start if request_counter else 0
    )
    index = store.rebuild_index(request_count=request_count)
    indexed_keys = {str(item["key"]) for item in index["items"]}
    safe_stopped = safe_stopped or indexed_keys != set(planned)
    status_counts = Counter(str(item.get("status", "")) for item in index["items"])
    progress = {
        "stage": store.stage,
        "processed": len(indexed_keys),
        "total": len(planned),
        "success": status_counts.get("success", 0),
        "failed": sum(
            status_counts.get(status, 0)
            for status in RETRYABLE_ITEM_STATUSES | {"permanent_error"}
        ),
        "cached": cached,
        "last_object": last_key,
        "updated_at": now(),
        "elapsed_seconds": round(clock() - started, 3),
        "safe_stopped": safe_stopped,
        "index_sha256": sha256_bytes(store.index_path.read_bytes()),
        "request_count": request_count,
    }
    store.save_progress(progress)
    print(
        f"[stage={store.stage}] {processed + cached}/{len(planned)} success={succeeded} "
        f"errors={failed} cached={cached} elapsed={progress['elapsed_seconds']}",
        flush=True,
    )
    return progress


def unique_preserve(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = normalize_space(value)
        identity = normalize_identity(cleaned)
        if not cleaned or not identity or identity in seen:
            continue
        seen.add(identity)
        result.append(cleaned)
    return result


class HttpClient:
    def __init__(self, *, delay: float, timeout: float, user_agent: str):
        self.delay = max(0.0, delay)
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            status=5,
            backoff_factor=0.8,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.5",
                "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.7,en;q=0.6",
            }
        )
        self.request_count = 0

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
        parsed = urlparse(url)
        allowed_hosts = WIKIMEDIA_HOSTS if parsed.hostname in WIKIMEDIA_HOSTS else UMAFANS_HOSTS
        current = validate_request_url(url, allowed_hosts=allowed_hosts)
        response: requests.Response | None = None
        for redirect_index in range(6):
            response = self.session.get(
                current,
                params=params if redirect_index == 0 else None,
                timeout=self.timeout,
                allow_redirects=False,
            )
            self.request_count += 1
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            location = response.headers.get("Location")
            if not location:
                raise RuntimeError("redirect response has no Location")
            current = validate_request_url(urljoin(current, location), allowed_hosts=allowed_hosts)
        else:
            raise RuntimeError("too many redirects")
        assert response is not None
        response.raise_for_status()
        if self.delay:
            time.sleep(self.delay)
        return response


@dataclass
class RaceResultRow:
    region: str
    region_label: str
    race_date: str
    race_name_zh: str
    race_name_original: str
    grade: str
    racecourse: str
    finish_position: int
    horse_display_name: str
    jockey_name: str
    trainer_name: str
    finish_time: str
    margin: str
    race_url: str
    race_page_sha256: str
    horse_lookup_key: str = ""
    horse_profile_url: str = ""
    horse_original_name: str = ""
    horse_birth_year: str = ""
    horse_name_zh: str = ""
    horse_name_ja: str = ""
    horse_name_en: str = ""
    wikidata_id: str = ""
    wikipedia_url: str = ""
    wikipedia_language: str = ""
    wikipedia_title: str = ""
    zh_wikipedia_url: str = ""
    ja_wikipedia_url: str = ""
    en_wikipedia_url: str = ""
    fr_wikipedia_url: str = ""
    wikipedia_match_status: str = ""
    wikipedia_match_score: str = ""
    wikipedia_match_evidence: str = ""


@dataclass
class HorseSeed:
    key: str
    regions: set[str] = field(default_factory=set)
    display_names: set[str] = field(default_factory=set)
    original_names: set[str] = field(default_factory=set)
    profile_urls: set[str] = field(default_factory=set)
    birth_years: set[str] = field(default_factory=set)
    name_zh: str = ""
    name_ja: str = ""
    name_en: str = ""
    race_contexts: list[str] = field(default_factory=list)
    candidate_meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    wikidata_id: str = ""
    wikipedia_url: str = ""
    wikipedia_language: str = ""
    wikipedia_title: str = ""
    wiki_urls: dict[str, str] = field(default_factory=dict)
    match_status: str = "no_page"
    match_score: int = 0
    match_evidence: str = ""
    alternative_candidates: list[str] = field(default_factory=list)
    identity_confidence: str = "sufficient"
    resolution_state: str = "resolved"
    error_code: str = ""


class UmaFansCollector:
    def __init__(self, *, base_url: str, client: HttpClient, output_dir: Path, year: int, cutoff: date):
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.output_dir = output_dir
        self.year = year
        self.cutoff = cutoff
        self.errors: list[dict[str, str]] = []
        self.source_manifest: list[dict[str, Any]] = []

    def _record_error(self, stage: str, url: str, exc: Exception) -> None:
        LOGGER.warning("%s failed for %s: %s", stage, url, exc)
        self.errors.append({"stage": stage, "url": url, "error": f"{type(exc).__name__}: {exc}"})

    def _get_xml_locs(self, url: str) -> list[str]:
        response = self.client.get(url)
        root = ET.fromstring(response.content)
        return [normalize_space(node.text or "") for node in root.findall(".//{*}loc") if node.text]

    def discover_race_urls(self) -> list[str]:
        candidates = [f"{self.base_url}/sitemap.xml"]
        last_error: Exception | None = None
        shard_urls: list[str] = []
        for sitemap_url in candidates:
            try:
                shard_urls = self._get_xml_locs(sitemap_url)
                if shard_urls:
                    break
            except Exception as exc:  # pragma: no cover - live-network branch
                last_error = exc
                self._record_error("sitemap_index", sitemap_url, exc)
        if not shard_urls:
            raise RuntimeError(f"Unable to read UmaFans sitemap: {last_error}")

        race_urls: list[str] = []
        for shard_url in shard_urls:
            try:
                for loc in self._get_xml_locs(shard_url):
                    if f"/races/{self.year}/" in loc:
                        race_urls.append(loc)
            except Exception as exc:
                self._record_error("sitemap_shard", shard_url, exc)
        race_urls = unique_preserve(race_urls)
        LOGGER.info("Discovered %s race URLs for %s", len(race_urls), self.year)
        return race_urls

    @staticmethod
    def _meta_grid(soup: BeautifulSoup) -> dict[str, str]:
        metadata: dict[str, str] = {}
        for item in soup.select("#overview .race-meta-grid > div"):
            label_node = item.find("span")
            value_node = item.find("b")
            if label_node and value_node:
                metadata[normalize_space(label_node.get_text(" ", strip=True))] = normalize_space(
                    value_node.get_text(" ", strip=True)
                )
        return metadata

    @staticmethod
    def _region_from_page(soup: BeautifulSoup) -> tuple[str, str]:
        node = soup.select_one(".race-hero-meta-text")
        text = normalize_space(node.get_text(" ", strip=True)) if node else ""
        label = text.split("·", 1)[0].strip()
        return REGION_LABELS.get(label, ""), label

    @staticmethod
    def _race_original_name(soup: BeautifulSoup) -> str:
        node = soup.select_one(".race-hero-original")
        text = normalize_space(node.get_text(" ", strip=True)) if node else ""
        match = DATE_RE.search(text)
        if match:
            return text[: match.start()].strip(" ·")
        return text.strip(" ·")

    def parse_race_page(self, url: str) -> list[RaceResultRow]:
        response = self.client.get(url)
        body = response.content
        soup = BeautifulSoup(body, "html.parser")
        if soup.select_one("main.race-page") is None:
            raise RuntimeError("public race page marker missing")
        metadata = self._meta_grid(soup)
        region, region_label = self._region_from_page(soup)
        race_name_node = soup.select_one(".race-hero-name")
        race_name_zh = normalize_space(race_name_node.get_text(" ", strip=True)) if race_name_node else ""
        race_name_original = self._race_original_name(soup)
        grade_node = soup.select_one(".grade-badge")
        grade_raw = metadata.get("等级") or (
            normalize_space(grade_node.get_text(" ", strip=True)) if grade_node else ""
        )
        grade = normalize_grade(grade_raw)
        race_date = metadata.get("日期", "")
        racecourse = metadata.get("马场", "")
        status = metadata.get("状态", "")

        manifest_entry = {
            "url": response.url,
            "requested_url": url,
            "http_status": response.status_code,
            "sha256": sha256_bytes(body),
            "region": region,
            "race_date": race_date,
            "race_name_zh": race_name_zh,
            "grade": grade,
            "status": status,
            "fetched_at": utc_now_iso(),
        }
        self.source_manifest.append(manifest_entry)

        if region not in TARGET_REGIONS:
            return []
        if status not in {"已结束", "已完赛"}:
            return []
        try:
            race_date_value = date.fromisoformat(race_date)
        except ValueError:
            raise RuntimeError(f"completed race has invalid date: {race_date!r}")
        if race_date_value.year != self.year or race_date_value > self.cutoff:
            return []
        if not grade_is_in_scope(region, grade):
            return []

        section = soup.select_one("section#results")
        if section is None:
            raise RuntimeError("completed in-scope race has no result section")
        rows: list[RaceResultRow] = []
        for tr in section.select("tbody tr"):
            cells = tr.find_all("td")
            if len(cells) < 8:
                continue
            position_text = normalize_space(cells[0].get_text(" ", strip=True))
            match = POSITION_RE.match(position_text)
            if not match:
                continue
            position = int(match.group(1))
            if not 1 <= position <= 5:
                continue
            horse_name = normalize_space(cells[2].get_text(" ", strip=True))
            if not horse_name:
                continue
            horse_link = cells[2].find("a")
            profile_url = (
                validate_request_url(
                    urljoin(response.url, horse_link.get("href", "")), allowed_hosts=UMAFANS_HOSTS
                )
                if horse_link and horse_link.get("href")
                else ""
            )
            rows.append(
                RaceResultRow(
                    region=region,
                    region_label=REGION_OUTPUT[region],
                    race_date=race_date,
                    race_name_zh=race_name_zh,
                    race_name_original=race_name_original,
                    grade=grade,
                    racecourse=racecourse,
                    finish_position=position,
                    horse_display_name=horse_name,
                    jockey_name=normalize_space(cells[3].get_text(" ", strip=True)),
                    trainer_name=normalize_space(cells[4].get_text(" ", strip=True)),
                    finish_time=normalize_space(cells[5].get_text(" ", strip=True)),
                    margin=normalize_space(cells[6].get_text(" ", strip=True)),
                    race_url=response.url,
                    race_page_sha256=manifest_entry["sha256"],
                    horse_lookup_key=canonical_lookup_key(region, horse_name, profile_url, response.url),
                    horse_profile_url=profile_url,
                )
            )
        if not rows:
            raise RuntimeError("completed in-scope race has no numeric top-five rows")
        if len(rows) != 5:
            raise RuntimeError("top five must contain exactly five result rows")
        horse_keys = [normalize_identity(row.horse_display_name) for row in rows]
        if len(set(horse_keys)) != 5:
            raise RuntimeError("top five must contain five unique horses")
        if {row.finish_position for row in rows} != {1, 2, 3, 4, 5}:
            # Legal dead heats may omit a rank, but must still terminate at fifth place.
            positions = [row.finish_position for row in rows]
            if positions[-1] != 5 or positions != sorted(positions):
                raise RuntimeError("top five official positions are incomplete")
        return rows

    def collect_races(self, *, max_races: int = 0) -> tuple[list[RaceResultRow], int]:
        race_urls = self.discover_race_urls()
        if max_races:
            race_urls = race_urls[:max_races]
        result_rows: list[RaceResultRow] = []
        included_race_urls: set[str] = set()
        for index, url in enumerate(race_urls, start=1):
            if index == 1 or index % 50 == 0:
                LOGGER.info("Race pages %s/%s; included races=%s", index, len(race_urls), len(included_race_urls))
            try:
                page_rows = self.parse_race_page(url)
                if page_rows:
                    included_race_urls.add(page_rows[0].race_url)
                    result_rows.extend(page_rows)
            except Exception as exc:
                self._record_error("race_page", url, exc)
        return result_rows, len(included_race_urls)

    def find_horse_profile(self, display_name: str, region: str) -> dict[str, str]:
        search_url = f"{self.base_url}/horses/"
        response = self.client.get(search_url, params={"q": display_name})
        soup = BeautifulSoup(response.content, "html.parser")
        exact_cards = []
        for card in soup.select("article.horse-card"):
            name_node = card.select_one(".horse-card-name a")
            if not name_node:
                continue
            card_display = normalize_space(name_node.get_text(" ", strip=True))
            if normalize_identity(card_display) != normalize_identity(display_name):
                continue
            region_node = card.select_one(".region-label")
            card_region_label = normalize_space(region_node.get_text(" ", strip=True)) if region_node else ""
            card_region = REGION_LABELS.get(card_region_label, "")
            original_node = card.select_one(".horse-card-original")
            original = normalize_space(original_node.get_text(" ", strip=True)) if original_node else ""
            if original == "资料整理中":
                original = ""
            exact_cards.append(
                {
                    "display_name": card_display,
                    "original_name": original,
                    "profile_url": urljoin(response.url, name_node.get("href", "")),
                    "region": card_region,
                }
            )
        if not exact_cards:
            return {}
        region_matches = [card for card in exact_cards if card["region"] == region]
        candidates = region_matches or exact_cards
        if len(candidates) != 1:
            return {"ambiguous": "1", "candidate_count": str(len(candidates))}
        candidate = candidates[0]
        try:
            detail = self.client.get(candidate["profile_url"])
            detail_soup = BeautifulSoup(detail.content, "html.parser")
            original_node = detail_soup.select_one(".horse-hero-original")
            detail_text = normalize_space(original_node.get_text(" ", strip=True)) if original_node else ""
            year_match = YEAR_RE.search(detail_text)
            if year_match:
                candidate["birth_year"] = year_match.group(1)
            date_match = re.search(r"\s+·\s+", detail_text)
            first_part = detail_text.split(" · ", 1)[0].strip() if detail_text else ""
            if first_part and first_part != candidate["display_name"]:
                candidate["original_name"] = first_part
            candidate["profile_page_sha256"] = sha256_bytes(detail.content)
        except Exception as exc:
            self._record_error("horse_profile_detail", candidate["profile_url"], exc)
            raise ProfileDetailError(
                f"profile detail transport/parse failed for {candidate['profile_url']}: {exc}"
            ) from exc
        return candidate

    def enrich_horse_profiles(self, rows: list[RaceResultRow]) -> dict[str, HorseSeed]:
        lookup_cache: dict[tuple[str, str], dict[str, str]] = {}
        horses: dict[str, HorseSeed] = {}
        for index, row in enumerate(rows, start=1):
            cache_key = (row.region, normalize_identity(row.horse_display_name))
            if cache_key not in lookup_cache:
                try:
                    lookup_cache[cache_key] = self.find_horse_profile(row.horse_display_name, row.region)
                except Exception as exc:
                    self._record_error("horse_profile_search", row.horse_display_name, exc)
                    lookup_cache[cache_key] = {}
                if len(lookup_cache) == 1 or len(lookup_cache) % 100 == 0:
                    LOGGER.info("Horse profile lookups=%s/%s rows", len(lookup_cache), len(rows))
            profile = lookup_cache[cache_key]
            profile_url = profile.get("profile_url", "")
            original_name = profile.get("original_name", "")
            birth_year = profile.get("birth_year", "")
            key = canonical_lookup_key(
                row.region,
                original_name or row.horse_display_name,
                profile_url or row.horse_profile_url,
                row.race_url,
            )
            row.horse_lookup_key = key
            row.horse_profile_url = profile_url
            row.horse_original_name = original_name
            row.horse_birth_year = birth_year

            seed = horses.setdefault(key, HorseSeed(key=key))
            seed.regions.add(row.region)
            seed.display_names.add(row.horse_display_name)
            if original_name:
                seed.original_names.add(original_name)
            if profile_url:
                seed.profile_urls.add(profile_url)
            if birth_year:
                seed.birth_years.add(birth_year)
            context = f"{row.race_date} {row.region_label} {row.grade} {row.race_name_zh} 第{row.finish_position}名"
            if context not in seed.race_contexts:
                seed.race_contexts.append(context)

        for seed in horses.values():
            display = sorted(seed.display_names, key=lambda value: (len(value), value))[0]
            original = sorted(seed.original_names, key=lambda value: (len(value), value))[0] if seed.original_names else ""
            if contains_han(display) and not contains_kana(display):
                seed.name_zh = display
            if contains_kana(original):
                seed.name_ja = original
            elif contains_kana(display):
                seed.name_ja = display
            if original and contains_latin(original) and not contains_kana(original):
                seed.name_en = original
            elif contains_latin(display) and not contains_han(display) and not contains_kana(display):
                seed.name_en = display
        return horses


class WikidataResolver:
    def __init__(self, *, client: HttpClient, output_dir: Path):
        self.client = client
        self.output_dir = output_dir
        self.api_url = "https://www.wikidata.org/w/api.php"
        self.search_cache_path = output_dir / "wikidata_search_cache.json"
        self.search_cache: dict[str, list[dict[str, Any]]] = {}
        if self.search_cache_path.exists():
            try:
                self.search_cache = json.loads(self.search_cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.search_cache = {}

    @staticmethod
    def _query_languages(query: str) -> list[str]:
        if contains_kana(query):
            return ["ja", "en"]
        if contains_han(query) and not contains_latin(query):
            return ["zh", "ja"]
        return ["en", "ja"]

    def _search(self, query: str, language: str) -> list[dict[str, Any]]:
        cache_key = f"{language}|{normalize_space(query)}"
        if cache_key in self.search_cache:
            return self.search_cache[cache_key]
        response = self.client.get(
            self.api_url,
            params={
                "action": "wbsearchentities",
                "search": query,
                "language": language,
                "uselang": language,
                "type": "item",
                "limit": 8,
                "format": "json",
                "maxlag": 5,
            },
        )
        payload = response.json()
        results = payload.get("search", []) if isinstance(payload, dict) else []
        self.search_cache[cache_key] = results
        return results

    @staticmethod
    def _search_queries(seed: HorseSeed) -> list[str]:
        values = [*seed.original_names, seed.name_en, seed.name_ja, seed.name_zh, *seed.display_names]
        stripped = [strip_country_suffix(value) for value in values]
        return unique_preserve([*values, *stripped])[:4]

    def search_candidates(self, horses: dict[str, HorseSeed]) -> set[str]:
        entity_ids: set[str] = set()
        for index, seed in enumerate(horses.values(), start=1):
            for query in self._search_queries(seed):
                for language in self._query_languages(query):
                    try:
                        results = self._search(query, language)
                    except Exception as exc:
                        LOGGER.warning("Wikidata search failed for %s/%s: %s", language, query, exc)
                        continue
                    for rank, result in enumerate(results[:5], start=1):
                        entity_id = result.get("id", "")
                        if not entity_id:
                            continue
                        meta = seed.candidate_meta.setdefault(
                            entity_id,
                            {
                                "rank": rank,
                                "descriptions": set(),
                                "matched_queries": set(),
                                "search_labels": set(),
                            },
                        )
                        meta["rank"] = min(meta["rank"], rank)
                        if result.get("description"):
                            meta["descriptions"].add(normalize_space(result["description"]))
                        if result.get("label"):
                            meta["search_labels"].add(normalize_space(result["label"]))
                        meta["matched_queries"].add(query)
                        entity_ids.add(entity_id)
            if index == 1 or index % 100 == 0:
                LOGGER.info("Wikidata search %s/%s horses; candidate IDs=%s", index, len(horses), len(entity_ids))
        self.search_cache_path.write_text(
            json.dumps(self.search_cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return entity_ids

    def fetch_entities(self, entity_ids: set[str]) -> dict[str, dict[str, Any]]:
        ids = sorted(entity_ids)
        entities: dict[str, dict[str, Any]] = {}
        for start in range(0, len(ids), 50):
            batch = ids[start : start + 50]
            response = self.client.get(
                self.api_url,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "labels|aliases|descriptions|sitelinks|claims",
                    "languages": "zh|ja|en|fr",
                    "format": "json",
                    "maxlag": 5,
                },
            )
            payload = response.json()
            entities.update(payload.get("entities", {}))
            LOGGER.info("Fetched Wikidata entities %s/%s", min(start + 50, len(ids)), len(ids))
        return entities

    @staticmethod
    def _entity_texts(entity: dict[str, Any], field: str) -> dict[str, list[str]]:
        output: dict[str, list[str]] = defaultdict(list)
        for language, payload in (entity.get(field) or {}).items():
            if field == "aliases":
                output[language].extend(normalize_space(item.get("value", "")) for item in payload)
            elif isinstance(payload, dict):
                output[language].append(normalize_space(payload.get("value", "")))
        return output

    @staticmethod
    def _entity_birth_year(entity: dict[str, Any]) -> str:
        for claim in (entity.get("claims") or {}).get("P569", []):
            value = (((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {})
            time_value = value.get("time", "") if isinstance(value, dict) else ""
            match = re.match(r"^[+-](\d{4})-", time_value)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _sitelink_urls(entity: dict[str, Any]) -> dict[str, str]:
        urls: dict[str, str] = {}
        sitelinks = entity.get("sitelinks") or {}
        for language, site_key in WIKI_SITE_KEYS.items():
            payload = sitelinks.get(site_key)
            if not payload:
                continue
            title = normalize_space(payload.get("title", ""))
            if title:
                urls[language] = wiki_url(language, title)
        return urls

    @staticmethod
    def _candidate_score(seed: HorseSeed, entity_id: str, entity: dict[str, Any]) -> tuple[int, list[str], bool, bool]:
        meta = seed.candidate_meta[entity_id]
        labels = WikidataResolver._entity_texts(entity, "labels")
        aliases = WikidataResolver._entity_texts(entity, "aliases")
        descriptions = [
            *meta.get("descriptions", set()),
            *[value for values in WikidataResolver._entity_texts(entity, "descriptions").values() for value in values],
        ]
        description_text = " | ".join(descriptions).casefold()
        is_horse = any(keyword.casefold() in description_text for keyword in HORSE_DESCRIPTION_KEYWORDS)
        source_names = unique_preserve(
            [*seed.display_names, *seed.original_names, seed.name_zh, seed.name_ja, seed.name_en]
        )
        source_norms = {normalize_identity(value) for value in source_names if normalize_identity(value)}
        entity_names = [
            *[value for values in labels.values() for value in values],
            *[value for values in aliases.values() for value in values],
            *meta.get("search_labels", set()),
        ]
        entity_norms = {normalize_identity(value) for value in entity_names if normalize_identity(value)}
        exact_name = bool(source_norms & entity_norms)
        fuzzy_name = any(
            source in target or target in source
            for source in source_norms
            for target in entity_norms
            if min(len(source), len(target)) >= 5
        )
        score = max(0, 10 - int(meta.get("rank", 10)))
        evidence = [f"rank={meta.get('rank', '')}"]
        if is_horse:
            score += 55
            evidence.append("horse_description")
        else:
            score -= 25
            evidence.append("no_horse_description")
        if exact_name:
            score += 45
            evidence.append("exact_multilingual_name")
        elif fuzzy_name:
            score += 16
            evidence.append("fuzzy_name")
        birth_year = WikidataResolver._entity_birth_year(entity)
        expected_years = {year for year in seed.birth_years if year}
        birth_mismatch = False
        if birth_year and expected_years:
            if birth_year in expected_years:
                score += 25
                evidence.append(f"birth_year_match={birth_year}")
            else:
                score -= 45
                birth_mismatch = True
                evidence.append(f"birth_year_mismatch={birth_year}/{','.join(sorted(expected_years))}")
        if WikidataResolver._sitelink_urls(entity):
            score += 8
            evidence.append("wikipedia_sitelink")
        return score, evidence, is_horse, exact_name and not birth_mismatch

    def resolve(self, horses: dict[str, HorseSeed]) -> None:
        candidate_ids = self.search_candidates(horses)
        entities = self.fetch_entities(candidate_ids)
        for seed in horses.values():
            scored: list[tuple[int, str, list[str], bool, bool]] = []
            for entity_id in seed.candidate_meta:
                entity = entities.get(entity_id)
                if not entity or entity.get("missing") is not None:
                    continue
                score, evidence, is_horse, strong_identity = self._candidate_score(seed, entity_id, entity)
                if self._sitelink_urls(entity):
                    scored.append((score, entity_id, evidence, is_horse, strong_identity))
            scored.sort(key=lambda item: (-item[0], item[1]))
            if not scored:
                seed.match_status = "no_page"
                seed.match_evidence = "no Wikipedia-linked Wikidata candidate"
                continue
            top = scored[0]
            second = scored[1] if len(scored) > 1 else None
            ambiguous = bool(second and second[0] >= top[0] - 7 and second[3] and top[3])
            if top[0] < 35 or not top[3]:
                seed.match_status = "no_page"
                seed.match_score = top[0]
                seed.match_evidence = "; ".join(top[2])
                seed.alternative_candidates = [f"{item[1]}:{item[0]}" for item in scored[:3]]
                continue
            entity = entities[top[1]]
            urls = self._sitelink_urls(entity)
            if ambiguous:
                seed.match_status = "ambiguous"
                seed.match_score = top[0]
                seed.match_evidence = "; ".join(top[2])
                seed.alternative_candidates = [f"{item[1]}:{item[0]}" for item in scored[:5]]
                continue
            seed.wikidata_id = top[1]
            seed.wiki_urls = urls
            seed.match_score = top[0]
            seed.match_evidence = "; ".join(top[2])
            seed.match_status = "exact" if top[4] and top[0] >= 90 else "probable"
            sitelinks = entity.get("sitelinks") or {}
            for language in WIKI_LANG_PRIORITY:
                if language in urls:
                    site_payload = sitelinks.get(WIKI_SITE_KEYS[language], {})
                    seed.wikipedia_language = language
                    seed.wikipedia_title = normalize_space(site_payload.get("title", ""))
                    seed.wikipedia_url = urls[language]
                    break
            # A language-specific Wikipedia title is a safer name source than a
            # fallback Wikidata label that may simply repeat another language.
            if not seed.name_zh and "zh" in urls:
                seed.name_zh = normalize_space(sitelinks["zhwiki"].get("title", ""))
            if not seed.name_ja and "ja" in urls:
                seed.name_ja = normalize_space(sitelinks["jawiki"].get("title", ""))
            if not seed.name_en and "en" in urls:
                seed.name_en = normalize_space(sitelinks["enwiki"].get("title", ""))


def assign_horse_results(rows: list[RaceResultRow], horses: dict[str, HorseSeed]) -> None:
    for row in rows:
        seed = horses[row.horse_lookup_key]
        row.horse_name_zh = seed.name_zh
        row.horse_name_ja = seed.name_ja
        row.horse_name_en = seed.name_en
        row.wikidata_id = seed.wikidata_id
        row.wikipedia_url = seed.wikipedia_url
        row.wikipedia_language = seed.wikipedia_language
        row.wikipedia_title = seed.wikipedia_title
        row.zh_wikipedia_url = seed.wiki_urls.get("zh", "")
        row.ja_wikipedia_url = seed.wiki_urls.get("ja", "")
        row.en_wikipedia_url = seed.wiki_urls.get("en", "")
        row.fr_wikipedia_url = seed.wiki_urls.get("fr", "")
        row.wikipedia_match_status = seed.match_status
        row.wikipedia_match_score = str(seed.match_score) if seed.match_score else ""
        row.wikipedia_match_evidence = seed.match_evidence


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
    if fieldnames:
        writer.writeheader()
        writer.writerows(rows)
    atomic_write_bytes(path, b"\xef\xbb\xbf" + handle.getvalue().encode("utf-8"))


def write_outputs(
    *,
    output_dir: Path,
    rows: list[RaceResultRow],
    horses: dict[str, HorseSeed],
    collector: UmaFansCollector,
    included_races: int,
    base_url: str,
    cutoff: date,
    started_at: str,
    request_count: int,
    completed_at: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    race_rows = [asdict(row) for row in sorted(rows, key=lambda row: (row.race_date, row.region, row.race_url, row.finish_position))]
    write_csv(output_dir / "race_top5_2026.csv", race_rows)

    occurrences: Counter[str] = Counter(row.horse_lookup_key for row in rows)
    race_counts: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        race_counts[row.horse_lookup_key].add(row.race_url)
    horse_rows: list[dict[str, Any]] = []
    for seed in horses.values():
        horse_rows.append(
            {
                "horse_key": seed.key,
                "regions": "|".join(REGION_OUTPUT.get(region, region) for region in sorted(seed.regions)),
                "horse_name_zh": seed.name_zh,
                "horse_name_ja": seed.name_ja,
                "horse_name_en": seed.name_en,
                "display_names": "|".join(sorted(seed.display_names)),
                "original_names": "|".join(sorted(seed.original_names)),
                "birth_year": "|".join(sorted(seed.birth_years)),
                "profile_urls": "|".join(sorted(seed.profile_urls)),
                "wikidata_id": seed.wikidata_id,
                "wikipedia_url": seed.wikipedia_url,
                "wikipedia_language": seed.wikipedia_language,
                "wikipedia_title": seed.wikipedia_title,
                "zh_wikipedia_url": seed.wiki_urls.get("zh", ""),
                "ja_wikipedia_url": seed.wiki_urls.get("ja", ""),
                "en_wikipedia_url": seed.wiki_urls.get("en", ""),
                "fr_wikipedia_url": seed.wiki_urls.get("fr", ""),
                "match_status": seed.match_status,
                "resolution_state": seed.resolution_state,
                "error_code": seed.error_code,
                "match_score": seed.match_score,
                "match_evidence": seed.match_evidence,
                "alternative_candidates": "|".join(seed.alternative_candidates),
                "graded_race_count": len(race_counts[seed.key]),
                "top5_occurrences": occurrences[seed.key],
                "race_context": " || ".join(sorted(seed.race_contexts)),
            }
        )
    horse_rows.sort(
        key=lambda item: (
            {"exact": 0, "probable": 1, "ambiguous": 2, "no_page": 3}.get(item["match_status"], 9),
            item["horse_name_zh"] or item["horse_name_ja"] or item["horse_name_en"] or item["display_names"],
        )
    )
    write_csv(output_dir / "horse_wikipedia_mapping_2026.csv", horse_rows)
    review_rows = [
        row
        for row in horse_rows
        if row["match_status"] in {"ambiguous", "no_page", "probable"}
        or row["resolution_state"] == "error"
    ]
    write_csv(output_dir / "wikipedia_review_queue_2026.csv", review_rows, list(horse_rows[0].keys()) if horse_rows else [])

    atomic_write_text(
        output_dir / "source_manifest.jsonl",
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for item in sorted(collector.source_manifest, key=lambda item: item.get("url", ""))
        ),
    )
    atomic_write_json(
        output_dir / "errors.json",
        sorted(
            collector.errors,
            key=lambda item: (
                item.get("stage", ""),
                item.get("key", item.get("url", "")),
                item.get("error_code", ""),
            ),
        ),
    )

    region_races: dict[str, set[str]] = defaultdict(set)
    grade_races: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        region_races[row.region].add(row.race_url)
        grade_races[f"{row.region}:{row.grade}"].add(row.race_url)
    summary = {
        "artifact_type": "umafans_2026_graded_top5_wikipedia_mapping",
        "scope": {
            "year": 2026,
            "cutoff_inclusive": cutoff.isoformat(),
            "regions": [REGION_OUTPUT[key] for key in ("japan", "hong_kong", "united_states", "united_kingdom", "france")],
            "japan_grades": sorted(TARGET_JAPAN_GRADES),
            "other_region_grades": sorted(TARGET_STANDARD_GRADES),
            "finish_positions": [1, 2, 3, 4, 5],
            "coverage_basis": "UmaFans current public data-quality-complete race sitemap and public result pages",
            "completeness_warning": "This artifact does not independently prove that every externally catalogued 2026 graded race is present in UmaFans.",
        },
        "source": {
            "base_url": base_url,
            "started_at": started_at,
            "completed_at": completed_at or utc_now_iso(),
            "http_request_count": request_count,
            "race_pages_fetched": len(collector.source_manifest),
            "race_page_errors": len(
                [
                    item
                    for item in collector.errors
                    if item["stage"] in {"race_page", "races"}
                ]
            ),
            "all_errors": len(collector.errors),
        },
        "counts": {
            "included_races": included_races,
            "top5_rows": len(rows),
            "unique_horse_seeds": len(horses),
            "races_by_region": {REGION_OUTPUT[key]: len(value) for key, value in sorted(region_races.items())},
            "races_by_region_grade": {key: len(value) for key, value in sorted(grade_races.items())},
            "wikipedia_status": dict(
                sorted(Counter(seed.match_status for seed in horses.values() if seed.match_status).items())
            ),
            "resolution_error": sum(seed.resolution_state == "error" for seed in horses.values()),
        },
        "files": [
            "race_top5_2026.csv",
            "horse_wikipedia_mapping_2026.csv",
            "wikipedia_review_queue_2026.csv",
            "source_manifest.jsonl",
            "errors.json",
        ],
    }
    four_states = sum(summary["counts"]["wikipedia_status"].get(name, 0) for name in (
        "exact", "probable", "ambiguous", "no_page"
    ))
    if four_states + summary["counts"]["resolution_error"] != len(horses):
        raise ValueError("Wikipedia status accounting invariant failed")
    atomic_write_json(output_dir / "summary.json", summary)
    readme = f"""# 2026 重赏入版马与 Wikipedia 对应关系\n\n- 生成时间：{summary['source']['completed_at']}\n- 截止日期（含）：{cutoff.isoformat()}\n- 数据范围：日本（JRA G1/G2/G3、J-G1/J-G2/J-G3；NAR Jpn1/Jpn2/Jpn3）、中国香港、美国、英国、法国 G1/G2/G3。\n- 名次：正式赛果第 1—5 名。\n- 数据基线：UmaFans 当前公开且 data-quality-complete 的赛事页。\n- Wikipedia：优先中文，其次日文、英文、法文；不确定匹配不会强行写入。\n\n## 文件\n\n- `race_top5_2026.csv`：赛事—名次级明细。\n- `horse_wikipedia_mapping_2026.csv`：马匹去重映射。\n- `wikipedia_review_queue_2026.csv`：`probable`、`ambiguous`、`no_page` 与 resolution error 人工复核队列。\n- `source_manifest.jsonl`：赛事页 URL、抓取时间与 SHA-256。\n- `summary.json`：范围、计数和覆盖声明。\n- `errors.json`：所有阶段的结构化抓取、解析或解析链错误。\n\n## 匹配状态\n\n- `exact`：Wikidata 描述为赛马，跨语言名称精确匹配，且无出生年份冲突。\n- `probable`：高概率为同一匹马，但证据未达到 exact 门槛。\n- `ambiguous`：存在分数接近的多个赛马候选，未自动选择。\n- `no_page`：未找到足够可信且带 Wikipedia sitelink 的候选。\n- resolution error：profile/search/entity 未补齐，匹配状态留空，禁止评分。\n\n注意：该结果覆盖的是 UmaFans 当前公开完整赛事页，不是对外部全球赛事目录的独立全量证明。\n"""
    atomic_write_text(output_dir / "README.md", readme)
    return summary


def resolve_base_url(client: HttpClient, requested: str) -> str:
    requested = requested.rstrip("/")
    parsed = urlparse(requested)
    candidates = [requested]
    if parsed.scheme == "https":
        candidates.append(urlunparse(("http", parsed.netloc, parsed.path, "", "", "")).rstrip("/"))
    elif parsed.scheme == "http":
        candidates.insert(0, urlunparse(("https", parsed.netloc, parsed.path, "", "", "")).rstrip("/"))
    for candidate in unique_preserve(candidates):
        try:
            response = client.get(f"{candidate}/sitemap.xml")
            if response.status_code == 200 and b"sitemap" in response.content.lower():
                return candidate
        except Exception as exc:
            LOGGER.warning("Base URL probe failed for %s: %s", candidate, exc)
    raise RuntimeError(f"No reachable UmaFans base URL among {candidates}")


def seed_to_record(seed: HorseSeed) -> dict[str, Any]:
    return {
        "key": seed.key,
        "regions": sorted(seed.regions),
        "display_names": sorted(seed.display_names),
        "original_names": sorted(seed.original_names),
        "profile_urls": sorted(seed.profile_urls),
        "birth_years": sorted(seed.birth_years),
        "name_zh": seed.name_zh,
        "name_ja": seed.name_ja,
        "name_en": seed.name_en,
        "race_contexts": sorted(set(seed.race_contexts)),
        "candidate_meta": {
            qid: {
                field: sorted(value) if isinstance(value, set) else value
                for field, value in sorted(meta.items())
            }
            for qid, meta in sorted(seed.candidate_meta.items())
        },
        "wikidata_id": seed.wikidata_id,
        "wikipedia_url": seed.wikipedia_url,
        "wikipedia_language": seed.wikipedia_language,
        "wikipedia_title": seed.wikipedia_title,
        "wiki_urls": dict(sorted(seed.wiki_urls.items())),
        "match_status": seed.match_status,
        "match_score": seed.match_score,
        "match_evidence": seed.match_evidence,
        "alternative_candidates": sorted(seed.alternative_candidates),
        "identity_confidence": seed.identity_confidence,
        "resolution_state": seed.resolution_state,
        "error_code": seed.error_code,
    }


def current_tool_identity() -> tuple[str, str]:
    source_sha = sha256_bytes(Path(__file__).read_bytes())
    tool_version = sha256_bytes(
        f"{source_sha}|{PARSER_VERSION}|{SCORER_VERSION}|{SCHEMA_VERSION}".encode()
    )
    return source_sha, tool_version


def current_base_commit() -> str:
    configured = os.environ.get("GITHUB_SHA", "").strip()
    if configured:
        return configured
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def current_tool_identity_record() -> dict[str, Any]:
    source_sha, tool_version = current_tool_identity()
    return {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "scorer_version": SCORER_VERSION,
        "collector_source_sha256": source_sha,
        "tool_version": tool_version,
        "base_commit": current_base_commit(),
    }


def validate_run_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    required = {
        "year",
        "cutoff",
        "base_url",
        "requested_base_url",
        "race_urls",
        "race_urls_sha256",
        "created_at",
        *current_tool_identity_record().keys(),
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"run manifest missing fields: {missing}")
    race_urls = manifest.get("race_urls")
    if not isinstance(race_urls, list) or any(not isinstance(url, str) for url in race_urls):
        raise ValueError("run manifest race_urls schema drift")
    if race_urls != sorted(set(race_urls)):
        raise ValueError("run manifest race_urls ordering drift")
    if sha256_bytes(canonical_json_bytes(race_urls)) != manifest.get("race_urls_sha256"):
        raise ValueError("run manifest race_urls digest drift")
    identity = current_tool_identity_record()
    for key, expected in identity.items():
        if manifest.get(key) != expected:
            raise ValueError(f"run manifest {key} drift")
    if manifest.get("year") != 2026:
        raise ValueError("run manifest year drift")
    for url in race_urls:
        validate_request_url(url, allowed_hosts=UMAFANS_HOSTS)
    return manifest


def seed_from_record(record: dict[str, Any]) -> HorseSeed:
    seed = HorseSeed(key=str(record["key"]))
    for field_name in ("regions", "display_names", "original_names", "profile_urls", "birth_years"):
        setattr(seed, field_name, set(record.get(field_name, [])))
    for field_name in (
        "name_zh", "name_ja", "name_en", "wikidata_id", "wikipedia_url",
        "wikipedia_language", "wikipedia_title", "match_status", "match_evidence",
        "identity_confidence", "resolution_state", "error_code",
    ):
        if field_name in record:
            setattr(seed, field_name, record[field_name])
    seed.race_contexts = list(record.get("race_contexts", []))
    seed.wiki_urls = dict(record.get("wiki_urls", {}))
    seed.match_score = int(record.get("match_score", 0) or 0)
    seed.alternative_candidates = list(record.get("alternative_candidates", []))
    seed.candidate_meta = {
        qid: {
            field: set(value) if field in {"descriptions", "matched_queries", "search_labels"} else value
            for field, value in meta.items()
        }
        for qid, meta in record.get("candidate_meta", {}).items()
    }
    return seed


def load_store_records(store: StageStore) -> list[dict[str, Any]]:
    index = store.verify_index()
    return [json.loads((store.root / item["path"]).read_text(encoding="utf-8")) for item in index["items"]]


def upstream_index_sha(store: StageStore) -> str:
    store.verify_index()
    return sha256_bytes(store.index_path.read_bytes())


def index_request_count(store: StageStore) -> int:
    return int(store.verify_index().get("request_count", 0))


def collect_structured_errors(
    stage_records: Iterable[tuple[str, Iterable[dict[str, Any]]]]
) -> list[dict[str, Any]]:
    errors: dict[bytes, dict[str, Any]] = {}
    for stage, records in stage_records:
        for record in records:
            key = str(record.get("key") or record.get("qid") or "")
            status = str(record.get("status") or "")
            if status in RETRYABLE_ITEM_STATUSES | {"permanent_error", "not_found"}:
                item = {
                    "stage": stage,
                    "key": key,
                    "status": status,
                    "error_code": str(record.get("error_code") or status),
                    "error": str(record.get("error") or ""),
                }
                errors[canonical_json_bytes(item)] = item
            if record.get("resolution_state") == "error" and record.get("error_code"):
                item = {
                    "stage": stage,
                    "key": key,
                    "status": "resolution_error",
                    "error_code": str(record["error_code"]),
                    "error": "",
                }
                errors[canonical_json_bytes(item)] = item
            for request in record.get("search_requests", []):
                request_status = str(request.get("status") or "")
                if request_status == "success":
                    continue
                item = {
                    "stage": stage,
                    "key": key,
                    "status": request_status,
                    "error_code": str(request.get("error_code") or request_status),
                    "error": str(request.get("error") or ""),
                    "request": {
                        "query": str(request.get("query") or ""),
                        "language": str(request.get("language") or ""),
                    },
                }
                errors[canonical_json_bytes(item)] = item
    return sorted(
        errors.values(),
        key=lambda item: (
            item["stage"],
            item["key"],
            item["error_code"],
            canonical_json_bytes(item),
        ),
    )


def race_rows_from_store(store: StageStore) -> list[RaceResultRow]:
    rows: list[RaceResultRow] = []
    seen: set[tuple[str, int, str]] = set()
    for item in load_store_records(store):
        if item.get("status") != "success":
            continue
        for raw in item.get("rows", []):
            row = RaceResultRow(**raw)
            unique = (row.race_url, row.finish_position, normalize_identity(row.horse_display_name))
            if unique in seen:
                raise ValueError(f"duplicate race result row {unique}")
            seen.add(unique)
            rows.append(row)
    return sorted(rows, key=lambda row: (row.race_url, row.finish_position, row.horse_display_name))


def build_seed_from_occurrences(
    lookup_key: str, rows: list[RaceResultRow], profile: dict[str, Any]
) -> HorseSeed:
    seed = HorseSeed(key=lookup_key)
    for row in rows:
        seed.regions.add(row.region)
        seed.display_names.add(row.horse_display_name)
        context = f"{row.race_date} {row.region_label} {row.grade} {row.race_name_zh} 第{row.finish_position}名"
        seed.race_contexts.append(context)
    profile_url = str(profile.get("profile_url", ""))
    original_name = str(profile.get("original_name", ""))
    birth_year = str(profile.get("birth_year", ""))
    if profile_url:
        seed.profile_urls.add(profile_url)
    if original_name:
        seed.original_names.add(original_name)
    if birth_year:
        seed.birth_years.add(birth_year)
    display = sorted(seed.display_names, key=lambda value: (len(value), value))[0]
    if contains_han(display) and not contains_kana(display):
        seed.name_zh = display
    if contains_kana(original_name):
        seed.name_ja = original_name
    elif contains_kana(display):
        seed.name_ja = display
    if original_name and contains_latin(original_name) and not contains_kana(original_name):
        seed.name_en = original_name
    elif contains_latin(display) and not contains_han(display) and not contains_kana(display):
        seed.name_en = display
    if not profile_url:
        seed.identity_confidence = "insufficient"
    return seed


def merge_profile_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = merge_keyed_records([records])
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        profile_urls = record.get("profile_urls", [])
        if len(profile_urls) > 1:
            raise ValueError(f"profile URL conflict for {record['key']}")
        canonical = profile_urls[0] if profile_urls else record["key"]
        groups[canonical].append(record)
    output = []
    for canonical in sorted(groups):
        members = groups[canonical]
        seed = HorseSeed(key=canonical)
        lookup_keys = []
        for record in members:
            member = seed_from_record(record)
            lookup_keys.append(member.key)
            for name in ("regions", "display_names", "original_names", "profile_urls", "birth_years"):
                getattr(seed, name).update(getattr(member, name))
            seed.race_contexts.extend(member.race_contexts)
            seed.identity_confidence = (
                "sufficient"
                if seed.identity_confidence == "sufficient" and member.identity_confidence == "sufficient"
                else "insufficient"
            )
            if member.resolution_state == "error":
                seed.resolution_state = "error"
                seed.match_status = ""
                seed.error_code = "|".join(
                    sorted({value for value in (seed.error_code, member.error_code) if value})
                )
        display = sorted(seed.display_names, key=lambda value: (len(value), value))[0]
        original = sorted(seed.original_names, key=lambda value: (len(value), value))[0] if seed.original_names else ""
        seed.name_zh = display if contains_han(display) and not contains_kana(display) else ""
        seed.name_ja = original if contains_kana(original) else (display if contains_kana(display) else "")
        seed.name_en = original if contains_latin(original) and not contains_kana(original) else (
            display if contains_latin(display) and not contains_han(display) and not contains_kana(display) else ""
        )
        item = seed_to_record(seed)
        item["lookup_keys"] = sorted(lookup_keys)
        item["status"] = "success"
        output.append(item)
    return output


def score_seed_from_entities(
    seed: HorseSeed, search_requests: list[dict[str, Any]], entities: dict[str, dict[str, Any]]
) -> HorseSeed:
    entity_requests = [
        {"qid": qid, "status": payload.get("status", ""), "error_code": payload.get("error_code", "")}
        for qid, payload in sorted(entities.items())
        if qid in seed.candidate_meta
    ]
    outcome = resolution_outcome(
        search_requests=search_requests, entity_requests=entity_requests
    )
    seed.resolution_state = outcome["resolution_state"]
    seed.error_code = outcome["error_code"]
    seed.match_status = outcome["wikipedia_match_status"]
    if outcome["resolution_state"] == "error":
        seed.match_evidence = f"resolution_error:{seed.error_code}"
        return seed
    if seed.match_status == "no_page":
        seed.match_evidence = "all planned searches succeeded with zero candidates"
        return seed
    scored: list[tuple[int, str, list[str], bool, bool]] = []
    for qid in sorted(seed.candidate_meta):
        entity = entities[qid].get("entity", {})
        score, evidence, is_horse, strong_identity = WikidataResolver._candidate_score(seed, qid, entity)
        if WikidataResolver._sitelink_urls(entity):
            scored.append((score, qid, evidence, is_horse, strong_identity))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored:
        seed.match_status = "no_page"
        seed.match_evidence = "no Wikipedia-linked Wikidata candidate"
        return seed
    top = scored[0]
    second = scored[1] if len(scored) > 1 else None
    if top[0] < 35 or not top[3]:
        seed.match_status = "no_page"
    elif second and second[0] >= top[0] - 7 and second[3] and top[3]:
        seed.match_status = "ambiguous"
    else:
        seed.match_status = (
            "exact"
            if top[4] and top[0] >= 90 and seed.identity_confidence == "sufficient"
            else "probable"
        )
        entity = entities[top[1]]["entity"]
        seed.wikidata_id = top[1]
        seed.wiki_urls = WikidataResolver._sitelink_urls(entity)
        sitelinks = entity.get("sitelinks") or {}
        for language in WIKI_LANG_PRIORITY:
            if language in seed.wiki_urls:
                seed.wikipedia_language = language
                seed.wikipedia_title = normalize_space(sitelinks[WIKI_SITE_KEYS[language]].get("title", ""))
                seed.wikipedia_url = seed.wiki_urls[language]
                break
    seed.match_score = top[0]
    seed.match_evidence = "; ".join(top[2])
    seed.alternative_candidates = [f"{item[1]}:{item[0]}" for item in scored[:5]]
    return seed


def make_client(args: argparse.Namespace) -> HttpClient:
    return HttpClient(
        delay=args.delay,
        timeout=args.timeout,
        user_agent="UmaFansResearch/2.0 (resumable 2026 graded top-five mapping)",
    )


def stage_store(args: argparse.Namespace, stage: str, *, sharded: bool = True) -> StageStore:
    return StageStore(
        Path(args.output_dir),
        stage=stage,
        shard_index=args.shard_index if sharded else None,
        shard_count=args.shard_count if sharded else 1,
    )


def open_bound_store(
    root: Path,
    *,
    stage: str,
    shard_index: int | None,
    shard_count: int,
    manifest_sha256: str,
    upstream_indexes: dict[str, str],
    input_keys: Iterable[str],
) -> StageStore:
    probe = StageStore(
        root, stage=stage, shard_index=shard_index, shard_count=shard_count
    )
    if not probe.index_path.exists():
        raise ValueError(f"required stage index missing: {stage} shard={shard_index}")
    raw = json.loads(probe.index_path.read_text(encoding="utf-8"))
    store = StageStore(
        root,
        stage=stage,
        shard_index=shard_index,
        shard_count=shard_count,
        manifest_sha256=manifest_sha256,
        upstream_indexes=upstream_indexes,
        input_keys_sha256=keys_sha256(input_keys),
    )
    store.verify_index()
    if raw.get("manifest_sha256") != manifest_sha256:
        raise ValueError(f"{stage} manifest binding drift")
    return store


def new_bound_store(
    root: Path,
    *,
    stage: str,
    shard_index: int | None,
    shard_count: int,
    manifest_sha256: str,
    upstream_indexes: dict[str, str],
    input_keys: Iterable[str],
) -> StageStore:
    return StageStore(
        root,
        stage=stage,
        shard_index=shard_index,
        shard_count=shard_count,
        manifest_sha256=manifest_sha256,
        upstream_indexes=upstream_indexes,
        input_keys_sha256=keys_sha256(input_keys),
    )


def verify_declared_shard_bindings(
    root: Path,
    *,
    merged_index: dict[str, Any],
    prefix: str,
    stage: str,
    manifest_sha256: str,
    upstream_indexes: dict[str, str],
    input_keys: Iterable[str],
) -> None:
    declared = {
        key: value
        for key, value in merged_index.get("upstream_indexes", {}).items()
        if key.startswith(f"{prefix}:")
    }
    if not declared:
        return
    all_keys = sorted(set(input_keys))
    shard_numbers = sorted(int(key.split(":", 1)[1]) for key in declared)
    shard_count = max(shard_numbers) + 1
    if shard_numbers != list(range(shard_count)):
        raise ValueError(f"{stage} declared shard coverage drift")
    for shard in shard_numbers:
        owned = [key for key in all_keys if stable_shard(key, shard_count) == shard]
        store = open_bound_store(
            root,
            stage=stage,
            shard_index=shard,
            shard_count=shard_count,
            manifest_sha256=manifest_sha256,
            upstream_indexes=upstream_indexes,
            input_keys=owned,
        )
        if upstream_index_sha(store) != declared[f"{prefix}:{shard}"]:
            raise ValueError(f"{stage} shard {shard} upstream digest drift")


def run_stage(args: argparse.Namespace) -> int:
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "run_manifest.json"
    cutoff = date.fromisoformat(args.cutoff)

    if args.stage == "races":
        client = make_client(args)
        collector = UmaFansCollector(
            base_url=args.base_url.rstrip("/"), client=client, output_dir=root, year=args.year, cutoff=cutoff
        )
        if manifest_path.exists():
            manifest = validate_run_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
            race_urls = manifest["race_urls"]
        else:
            base_url = resolve_base_url(client, args.base_url)
            collector.base_url = base_url
            race_urls = sorted(collector.discover_race_urls())
            if args.max_races:
                race_urls = race_urls[:args.max_races]
            manifest = {
                **current_tool_identity_record(),
                "year": args.year,
                "cutoff": args.cutoff,
                "base_url": base_url,
                "requested_base_url": args.base_url.rstrip("/"),
                "race_urls": race_urls,
                "race_urls_sha256": sha256_bytes(canonical_json_bytes(race_urls)),
                "created_at": utc_now_iso(),
            }
            ensure_run_manifest(manifest_path, manifest)
            validate_run_manifest(manifest)
        for key, value in (("year", args.year), ("cutoff", args.cutoff)):
            if manifest.get(key) != value:
                raise ValueError(f"run manifest drift: {key}")
        if manifest.get("requested_base_url") != args.base_url.rstrip("/"):
            raise ValueError("run manifest drift: base_url")
        collector.base_url = manifest["base_url"]
        manifest_sha = sha256_bytes(manifest_path.read_bytes())
        race_input_keys = [
            key
            for key in race_urls
            if stable_shard(key, args.shard_count) == args.shard_index
        ]
        store = new_bound_store(
            root,
            stage="races",
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            manifest_sha256=manifest_sha,
            upstream_indexes={},
            input_keys=race_input_keys,
        )
        progress = run_checkpointed_items(
            race_urls,
            store=store,
            process=lambda url: {
                "key": url,
                "status": "success" if (rows := collector.parse_race_page(url)) else "skipped",
                "rows": [asdict(row) for row in rows],
                "source": collector.source_manifest[-1],
            },
            resume=args.resume,
            start_index=args.start_index,
            limit=args.limit,
            time_budget_seconds=args.time_budget_seconds,
            checkpoint_every=args.checkpoint_every,
            request_counter=lambda: client.request_count,
            request_counter_start=0,
        )
        return SAFE_STOP_EXIT_CODE if progress["safe_stopped"] else 0

    if not manifest_path.exists():
        raise ValueError("run_manifest.json is required; run races first")
    manifest = validate_run_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.get("year") != args.year or manifest.get("cutoff") != args.cutoff:
        raise ValueError("run manifest drift")
    manifest_sha = sha256_bytes(manifest_path.read_bytes())
    races = open_bound_store(
        root,
        stage="races",
        shard_index=args.races_shard_index,
        shard_count=args.races_shard_count,
        manifest_sha256=manifest_sha,
        upstream_indexes={},
        input_keys=manifest["race_urls"],
    )
    races_sha = upstream_index_sha(races)
    rows = race_rows_from_store(races)
    grouped: dict[str, list[RaceResultRow]] = defaultdict(list)
    for row in rows:
        key = row.horse_lookup_key or canonical_lookup_key(
            row.region, row.horse_display_name, row.horse_profile_url, row.race_url
        )
        grouped[key].append(row)

    if args.stage == "profiles":
        client = make_client(args)
        collector = UmaFansCollector(
            base_url=manifest["base_url"], client=client, output_dir=root, year=args.year, cutoff=cutoff
        )
        store = new_bound_store(
            root,
            stage="profiles",
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            manifest_sha256=manifest_sha,
            upstream_indexes={"races": races_sha},
            input_keys=(
                key
                for key in grouped
                if stable_shard(key, args.shard_count) == args.shard_index
            ),
        )

        def profile_one(key: str) -> dict[str, Any]:
            representative = grouped[key][0]
            try:
                profile = collector.find_horse_profile(
                    representative.horse_display_name, representative.region
                )
                status = "success"
                error_code = ""
            except Exception as exc:
                profile = {}
                status = "retryable_error"
                error_code = (
                    "detail_transport_or_parse_error"
                    if isinstance(exc, ProfileDetailError)
                    else type(exc).__name__
                )
            seed = build_seed_from_occurrences(key, grouped[key], profile)
            if error_code:
                seed.resolution_state = "error"
                seed.match_status = ""
                seed.error_code = f"profile_{error_code}"
            record = seed_to_record(seed)
            record["status"] = status
            return record
        progress = run_checkpointed_items(
            grouped,
            store=store,
            process=profile_one,
            resume=args.resume,
            start_index=args.start_index,
            limit=args.limit,
            time_budget_seconds=args.time_budget_seconds,
            checkpoint_every=args.checkpoint_every,
            request_counter=lambda: client.request_count,
        )
        return SAFE_STOP_EXIT_CODE if progress["safe_stopped"] else 0

    if args.stage == "merge_profiles":
        records: list[dict[str, Any]] = []
        upstreams = {"races": races_sha}
        request_count = 0
        for shard in range(args.shard_count):
            shard_keys = [key for key in grouped if stable_shard(key, args.shard_count) == shard]
            shard_store = open_bound_store(
                root,
                stage="profiles",
                shard_index=shard,
                shard_count=args.shard_count,
                manifest_sha256=manifest_sha,
                upstream_indexes={"races": races_sha},
                input_keys=shard_keys,
            )
            upstreams[f"profiles:{shard}"] = upstream_index_sha(shard_store)
            request_count += index_request_count(shard_store)
            records.extend(load_store_records(shard_store))
        require_exact_coverage(records, grouped, "profiles")
        merged = merge_profile_records(records)
        store = new_bound_store(
            root,
            stage="profiles_merged",
            shard_index=None,
            shard_count=1,
            manifest_sha256=manifest_sha,
            upstream_indexes=upstreams,
            input_keys=grouped,
        )
        for record in merged:
            store.save_item(record["key"], record)
        store.rebuild_index(request_count=request_count)
        return 0

    profile_probe = StageStore(root, stage="profiles_merged", shard_index=None, shard_count=1)
    if not profile_probe.index_path.exists():
        raise ValueError("required merged profiles index missing")
    profile_raw = json.loads(profile_probe.index_path.read_text(encoding="utf-8"))
    profiles = open_bound_store(
        root,
        stage="profiles_merged",
        shard_index=None,
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes=profile_raw.get("upstream_indexes", {}),
        input_keys=grouped,
    )
    if profile_raw.get("upstream_indexes", {}).get("races") != races_sha:
        raise ValueError("profiles merged upstream race drift")
    verify_declared_shard_bindings(
        root,
        merged_index=profile_raw,
        prefix="profiles",
        stage="profiles",
        manifest_sha256=manifest_sha,
        upstream_indexes={"races": races_sha},
        input_keys=grouped,
    )
    profile_records = load_store_records(profiles)
    profiles_sha = upstream_index_sha(profiles)

    if args.stage == "finalize":
        score_probe = StageStore(root, stage="scored_horses_merged", shard_index=None, shard_count=1)
        if not score_probe.index_path.exists():
            raise ValueError("required merged scores index missing")
        score_raw = json.loads(score_probe.index_path.read_text(encoding="utf-8"))
        scores = open_bound_store(
            root,
            stage="scored_horses_merged",
            shard_index=None,
            shard_count=1,
            manifest_sha256=manifest_sha,
            upstream_indexes=score_raw.get("upstream_indexes", {}),
            input_keys=(record["key"] for record in profile_records),
        )
        if score_raw.get("upstream_indexes", {}).get("wikidata_search_merged") is None:
            raise ValueError("finalize scores missing search binding")
        if score_raw.get("upstream_indexes", {}).get("wikidata_entities_merged") is None:
            raise ValueError("finalize scores missing entity binding")
        score_records = load_store_records(scores)
        if {item["key"] for item in score_records} != {item["key"] for item in profile_records}:
            raise ValueError("finalize horse coverage mismatch")
        lookup_to_canonical = {
            lookup: record["key"]
            for record in profile_records
            for lookup in record.get("lookup_keys", [record["key"]])
        }
        for row in rows:
            row.horse_lookup_key = lookup_to_canonical[row.horse_lookup_key]
        horses = {record["key"]: seed_from_record(record) for record in score_records}
        assign_horse_results(rows, horses)
        collector = UmaFansCollector(
            base_url=manifest["base_url"], client=None, output_dir=root, year=args.year, cutoff=cutoff  # type: ignore[arg-type]
        )
        race_items = load_store_records(races)
        collector.source_manifest = [item["source"] for item in race_items if item.get("source")]
        all_stage_records: list[tuple[str, Iterable[dict[str, Any]]]] = [
            ("races", race_items),
            ("profiles", profile_records),
            ("scored_horses", score_records),
        ]
        request_count = index_request_count(races) + index_request_count(profiles)
        search_probe = StageStore(root, stage="wikidata_search_merged", shard_index=None, shard_count=1)
        search_raw = json.loads(search_probe.index_path.read_text(encoding="utf-8"))
        search_bound = open_bound_store(
            root,
            stage="wikidata_search_merged",
            shard_index=None,
            shard_count=1,
            manifest_sha256=manifest_sha,
            upstream_indexes=search_raw.get("upstream_indexes", {}),
            input_keys=(record["key"] for record in profile_records),
        )
        if search_raw.get("upstream_indexes", {}).get("profiles_merged") != profiles_sha:
            raise ValueError("finalize search upstream profile drift")
        verify_declared_shard_bindings(
            root,
            merged_index=search_raw,
            prefix="wikidata_search",
            stage="wikidata_search",
            manifest_sha256=manifest_sha,
            upstream_indexes={"profiles_merged": profiles_sha},
            input_keys=(record["key"] for record in profile_records),
        )
        search_final_records = load_store_records(search_bound)
        search_final_sha = upstream_index_sha(search_bound)
        entity_qids = sorted(
            {
                qid
                for record in search_final_records
                for qid in record.get("candidate_meta", {})
            }
        )
        entity_probe = StageStore(
            root, stage="wikidata_entities_merged", shard_index=None, shard_count=1
        )
        entity_raw = json.loads(entity_probe.index_path.read_text(encoding="utf-8"))
        entity_bound = open_bound_store(
            root,
            stage="wikidata_entities_merged",
            shard_index=None,
            shard_count=1,
            manifest_sha256=manifest_sha,
            upstream_indexes=entity_raw.get("upstream_indexes", {}),
            input_keys=entity_qids,
        )
        if (
            entity_raw.get("upstream_indexes", {}).get("wikidata_search_merged")
            != search_final_sha
        ):
            raise ValueError("finalize entity upstream search drift")
        verify_declared_shard_bindings(
            root,
            merged_index=entity_raw,
            prefix="wikidata_entities",
            stage="wikidata_entities",
            manifest_sha256=manifest_sha,
            upstream_indexes={"wikidata_search_merged": search_final_sha},
            input_keys=entity_qids,
        )
        entity_final_records = load_store_records(entity_bound)
        entity_final_sha = upstream_index_sha(entity_bound)
        if score_raw["upstream_indexes"]["wikidata_search_merged"] != search_final_sha:
            raise ValueError("finalize score upstream search drift")
        if score_raw["upstream_indexes"]["wikidata_entities_merged"] != entity_final_sha:
            raise ValueError("finalize score upstream entity drift")
        verify_declared_shard_bindings(
            root,
            merged_index=score_raw,
            prefix="scored_horses",
            stage="scored_horses",
            manifest_sha256=manifest_sha,
            upstream_indexes={
                "wikidata_search_merged": search_final_sha,
                "wikidata_entities_merged": entity_final_sha,
            },
            input_keys=(record["key"] for record in profile_records),
        )
        all_stage_records.extend(
            [
                ("wikidata_search", search_final_records),
                ("wikidata_entities", entity_final_records),
            ]
        )
        request_count += index_request_count(search_bound) + index_request_count(entity_bound)
        collector.errors = collect_structured_errors(all_stage_records)
        write_outputs(
            output_dir=root / "final",
            rows=rows,
            horses=horses,
            collector=collector,
            included_races=len({row.race_url for row in rows}),
            base_url=manifest["base_url"],
            cutoff=cutoff,
            started_at=manifest["created_at"],
            completed_at=manifest["created_at"],
            request_count=request_count,
        )
        return 0

    if args.stage == "wikidata_search":
        client = make_client(args)
        resolver = WikidataResolver(client=client, output_dir=root)
        seeds = {record["key"]: seed_from_record(record) for record in profile_records}
        store = new_bound_store(
            root,
            stage="wikidata_search",
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            manifest_sha256=manifest_sha,
            upstream_indexes={"profiles_merged": profiles_sha},
            input_keys=(
                key
                for key in seeds
                if stable_shard(key, args.shard_count) == args.shard_index
            ),
        )

        def search_one(key: str) -> dict[str, Any]:
            existing = store.load_item(key)
            seed = seed_from_record(existing) if existing else seeds[key]
            requests_state = list(existing.get("search_requests", [])) if existing else []
            if seed.resolution_state == "error":
                record = seed_to_record(seed)
                record.update(
                    {
                        "status": "success",
                        "search_requests": [
                            {
                                "query": "",
                                "language": "",
                                "status": "retryable_error",
                                "error_code": seed.error_code or "profile_resolution_error",
                            }
                        ],
                    }
                )
                return record
            completed = {
                (item["query"], item["language"]): item
                for item in requests_state
                if item.get("status") == "success"
            }
            plans = [
                (query, language)
                for query in resolver._search_queries(seed)
                for language in resolver._query_languages(query)
            ]
            requests_state = []
            for query, language in plans:
                if (query, language) in completed:
                    requests_state.append(completed[(query, language)])
                    continue
                try:
                    results = resolver._search(query, language)
                    qids = sorted({str(item.get("id")) for item in results[:5] if item.get("id")})
                    requests_state.append(
                        {"query": query, "language": language, "status": "success", "candidates": qids}
                    )
                    for rank, result in enumerate(results[:5], 1):
                        qid = str(result.get("id", ""))
                        if not qid:
                            continue
                        meta = seed.candidate_meta.setdefault(
                            qid, {"rank": rank, "descriptions": set(), "matched_queries": set(), "search_labels": set()}
                        )
                        meta["rank"] = min(meta["rank"], rank)
                        if result.get("description"):
                            meta["descriptions"].add(normalize_space(result["description"]))
                        if result.get("label"):
                            meta["search_labels"].add(normalize_space(result["label"]))
                        meta["matched_queries"].add(query)
                except Exception as exc:
                    requests_state.append(
                        {"query": query, "language": language, "status": "retryable_error",
                         "error_code": type(exc).__name__}
                    )
                partial = seed_to_record(seed)
                partial.update(
                    {
                        "status": "in_progress",
                        "planned_request_count": len(plans),
                        "search_requests": sorted(
                            requests_state, key=lambda item: (item["query"], item["language"])
                        ),
                    }
                )
                store.save_item(key, partial)
            record = seed_to_record(seed)
            record.update(
                {
                    "status": "success" if all(item["status"] == "success" for item in requests_state) else "retryable_error",
                    "search_requests": sorted(requests_state, key=lambda item: (item["query"], item["language"])),
                }
            )
            return record
        progress = run_checkpointed_items(
            seeds,
            store=store,
            process=search_one,
            resume=args.resume,
            start_index=args.start_index,
            limit=args.limit,
            time_budget_seconds=args.time_budget_seconds,
            checkpoint_every=args.checkpoint_every,
            request_counter=lambda: client.request_count,
        )
        return SAFE_STOP_EXIT_CODE if progress["safe_stopped"] else 0

    if args.stage == "merge_search":
        groups: list[list[dict[str, Any]]] = []
        upstreams = {"profiles_merged": profiles_sha}
        request_count = 0
        profile_keys = [record["key"] for record in profile_records]
        for shard in range(args.shard_count):
            shard_keys = [key for key in profile_keys if stable_shard(key, args.shard_count) == shard]
            shard_store = open_bound_store(
                root,
                stage="wikidata_search",
                shard_index=shard,
                shard_count=args.shard_count,
                manifest_sha256=manifest_sha,
                upstream_indexes={"profiles_merged": profiles_sha},
                input_keys=shard_keys,
            )
            groups.append(load_store_records(shard_store))
            upstreams[f"wikidata_search:{shard}"] = upstream_index_sha(shard_store)
            request_count += index_request_count(shard_store)
        merged = merge_keyed_records(groups)
        require_exact_coverage(merged, profile_keys, "wikidata_search")
        store = new_bound_store(
            root,
            stage="wikidata_search_merged",
            shard_index=None,
            shard_count=1,
            manifest_sha256=manifest_sha,
            upstream_indexes=upstreams,
            input_keys=profile_keys,
        )
        for record in merged:
            store.save_item(record["key"], record)
        store.rebuild_index(request_count=request_count)
        return 0

    search_probe = StageStore(root, stage="wikidata_search_merged", shard_index=None, shard_count=1)
    if not search_probe.index_path.exists():
        raise ValueError("required merged search index missing")
    search_raw = json.loads(search_probe.index_path.read_text(encoding="utf-8"))
    search = open_bound_store(
        root,
        stage="wikidata_search_merged",
        shard_index=None,
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes=search_raw.get("upstream_indexes", {}),
        input_keys=(record["key"] for record in profile_records),
    )
    if search_raw.get("upstream_indexes", {}).get("profiles_merged") != profiles_sha:
        raise ValueError("search merged upstream profiles drift")
    verify_declared_shard_bindings(
        root,
        merged_index=search_raw,
        prefix="wikidata_search",
        stage="wikidata_search",
        manifest_sha256=manifest_sha,
        upstream_indexes={"profiles_merged": profiles_sha},
        input_keys=(record["key"] for record in profile_records),
    )
    search_records = load_store_records(search)
    search_sha = upstream_index_sha(search)
    qids = sorted({qid for record in search_records for qid in record.get("candidate_meta", {})})

    if args.stage == "wikidata_entities":
        client = make_client(args)
        store = new_bound_store(
            root,
            stage="wikidata_entities",
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            manifest_sha256=manifest_sha,
            upstream_indexes={"wikidata_search_merged": search_sha},
            input_keys=(
                qid
                for qid in qids
                if stable_shard(qid, args.shard_count) == args.shard_index
            ),
        )

        def entity_one(qid: str) -> dict[str, Any]:
            response = client.get(
                "https://www.wikidata.org/w/api.php",
                params={"action": "wbgetentities", "ids": qid,
                        "props": "labels|aliases|descriptions|sitelinks|claims",
                        "languages": "zh|ja|en|fr", "format": "json", "maxlag": 5},
            )
            entity = (response.json().get("entities") or {}).get(qid)
            if not entity or entity.get("missing") is not None:
                return {"key": qid, "qid": qid, "status": "not_found", "error_code": "entity_not_found"}
            return {"key": qid, "qid": qid, "status": "success", "entity": entity}
        progress = run_checkpointed_items(
            qids,
            store=store,
            process=entity_one,
            resume=args.resume,
            start_index=args.start_index,
            limit=args.limit,
            time_budget_seconds=args.time_budget_seconds,
            checkpoint_every=args.checkpoint_every,
            request_counter=lambda: client.request_count,
        )
        return SAFE_STOP_EXIT_CODE if progress["safe_stopped"] else 0

    if args.stage == "merge_entities":
        groups: list[list[dict[str, Any]]] = []
        upstreams = {"wikidata_search_merged": search_sha}
        request_count = 0
        for shard in range(args.shard_count):
            shard_keys = [qid for qid in qids if stable_shard(qid, args.shard_count) == shard]
            shard_store = open_bound_store(
                root,
                stage="wikidata_entities",
                shard_index=shard,
                shard_count=args.shard_count,
                manifest_sha256=manifest_sha,
                upstream_indexes={"wikidata_search_merged": search_sha},
                input_keys=shard_keys,
            )
            groups.append(load_store_records(shard_store))
            upstreams[f"wikidata_entities:{shard}"] = upstream_index_sha(shard_store)
            request_count += index_request_count(shard_store)
        merged = merge_keyed_records(groups)
        require_exact_coverage(merged, qids, "wikidata_entities")
        store = new_bound_store(
            root,
            stage="wikidata_entities_merged",
            shard_index=None,
            shard_count=1,
            manifest_sha256=manifest_sha,
            upstream_indexes=upstreams,
            input_keys=qids,
        )
        for record in merged:
            store.save_item(record["key"], record)
        store.rebuild_index(request_count=request_count)
        return 0

    entity_probe = StageStore(root, stage="wikidata_entities_merged", shard_index=None, shard_count=1)
    if not entity_probe.index_path.exists():
        raise ValueError("required merged entity index missing")
    entity_raw = json.loads(entity_probe.index_path.read_text(encoding="utf-8"))
    entities_store = open_bound_store(
        root,
        stage="wikidata_entities_merged",
        shard_index=None,
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes=entity_raw.get("upstream_indexes", {}),
        input_keys=qids,
    )
    if entity_raw.get("upstream_indexes", {}).get("wikidata_search_merged") != search_sha:
        raise ValueError("entity merged upstream search drift")
    verify_declared_shard_bindings(
        root,
        merged_index=entity_raw,
        prefix="wikidata_entities",
        stage="wikidata_entities",
        manifest_sha256=manifest_sha,
        upstream_indexes={"wikidata_search_merged": search_sha},
        input_keys=qids,
    )
    entities_sha = upstream_index_sha(entities_store)
    entity_records = {record["key"]: record for record in load_store_records(entities_store)}

    if args.stage == "score_horses":
        searches = {record["key"]: record for record in search_records}
        store = new_bound_store(
            root,
            stage="scored_horses",
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            manifest_sha256=manifest_sha,
            upstream_indexes={
                "wikidata_search_merged": search_sha,
                "wikidata_entities_merged": entities_sha,
            },
            input_keys=(
                key
                for key in searches
                if stable_shard(key, args.shard_count) == args.shard_index
            ),
        )

        def score_one(key: str) -> dict[str, Any]:
            source = searches[key]
            seed = score_seed_from_entities(
                seed_from_record(source), source.get("search_requests", []), entity_records
            )
            record = seed_to_record(seed)
            record["status"] = "success"
            return record
        progress = run_checkpointed_items(
            searches,
            store=store,
            process=score_one,
            resume=args.resume,
            start_index=args.start_index,
            limit=args.limit,
            time_budget_seconds=args.time_budget_seconds,
            checkpoint_every=args.checkpoint_every,
        )
        return SAFE_STOP_EXIT_CODE if progress["safe_stopped"] else 0

    if args.stage == "merge_scores":
        groups: list[list[dict[str, Any]]] = []
        searches = {record["key"]: record for record in search_records}
        base_upstreams = {
            "wikidata_search_merged": search_sha,
            "wikidata_entities_merged": entities_sha,
        }
        upstreams = dict(base_upstreams)
        for shard in range(args.shard_count):
            shard_keys = [
                key for key in searches if stable_shard(key, args.shard_count) == shard
            ]
            shard_store = open_bound_store(
                root,
                stage="scored_horses",
                shard_index=shard,
                shard_count=args.shard_count,
                manifest_sha256=manifest_sha,
                upstream_indexes=base_upstreams,
                input_keys=shard_keys,
            )
            groups.append(load_store_records(shard_store))
            upstreams[f"scored_horses:{shard}"] = upstream_index_sha(shard_store)
        merged = merge_keyed_records(groups)
        require_exact_coverage(merged, searches, "scored_horses")
        store = new_bound_store(
            root,
            stage="scored_horses_merged",
            shard_index=None,
            shard_count=1,
            manifest_sha256=manifest_sha,
            upstream_indexes=upstreams,
            input_keys=searches,
        )
        for record in merged:
            store.save_item(record["key"], record)
        store.rebuild_index(request_count=0)
        return 0

    raise ValueError(f"unsupported stage {args.stage}")


def run_synthetic_smoke(root: Path, *, stop_after: int = 0) -> dict[str, Any]:
    """Exercise safe-stop, resume, fan-in and offline finalize without network."""
    root.mkdir(parents=True, exist_ok=True)
    race_urls = [
        "https://umafans.run/races/2026/synthetic-a/",
        "https://umafans.run/races/2026/synthetic-b/",
    ]
    manifest_path = root / "run_manifest.json"
    if manifest_path.exists():
        manifest = validate_run_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    else:
        manifest = {
            **current_tool_identity_record(),
            "year": 2026,
            "cutoff": "2026-07-26",
            "base_url": "https://umafans.run",
            "requested_base_url": "https://umafans.run",
            "race_urls": race_urls,
            "race_urls_sha256": sha256_bytes(canonical_json_bytes(race_urls)),
            "created_at": "2026-07-26T00:00:00+00:00",
        }
        atomic_write_json(manifest_path, manifest)
        validate_run_manifest(manifest)
    manifest_sha = sha256_bytes(manifest_path.read_bytes())

    def race_record(url: str) -> dict[str, Any]:
        suffix = "a" if url.endswith("a/") else "b"
        key = f"japan|synthetic-{suffix}"
        row = RaceResultRow(
            region="japan",
            region_label="日本",
            race_date="2026-07-01",
            race_name_zh=f"合成赛事{suffix.upper()}",
            race_name_original=f"Synthetic {suffix.upper()}",
            grade="G1",
            racecourse="东京",
            finish_position=1,
            horse_display_name=f"Synthetic {suffix.upper()}",
            jockey_name="",
            trainer_name="",
            finish_time="",
            margin="",
            race_url=url,
            race_page_sha256=sha256_bytes(url.encode()),
            horse_lookup_key=key,
        )
        return {
            "key": url,
            "status": "success",
            "rows": [asdict(row)],
            "source": {"url": url, "sha256": row.race_page_sha256},
        }

    race_store = new_bound_store(
        root,
        stage="races",
        shard_index=0,
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes={},
        input_keys=race_urls,
    )
    request_counter = {"value": 0}

    def process(url: str) -> dict[str, Any]:
        request_counter["value"] += 1
        return race_record(url)

    run_kwargs: dict[str, Any] = {}
    if stop_after:
        ticks = iter([0.0, 0.0, 1.0, 1.0, 1.0])
        run_kwargs = {
            "time_budget_seconds": 0.5,
            "clock": lambda: next(ticks),
        }
    progress = run_checkpointed_items(
        race_urls,
        store=race_store,
        process=process,
        resume=True,
        request_counter=lambda: request_counter["value"],
        now=lambda: "2026-07-26T00:00:00+00:00",
        **run_kwargs,
    )
    if progress["safe_stopped"]:
        atomic_write_json(
            root / "safe_stop.json",
            {
                "exit_code": SAFE_STOP_EXIT_CODE,
                "stage": "races",
                "index_sha256": progress["index_sha256"],
            },
        )
        return {"safe_stopped": True, "exit_code": SAFE_STOP_EXIT_CODE}

    baseline_root = root / "synthetic_uninterrupted_baseline"
    baseline = new_bound_store(
        baseline_root,
        stage="races",
        shard_index=0,
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes={},
        input_keys=race_urls,
    )
    baseline_requests = {"value": 0}

    def baseline_process(url: str) -> dict[str, Any]:
        baseline_requests["value"] += 1
        return race_record(url)

    run_checkpointed_items(
        race_urls,
        store=baseline,
        process=baseline_process,
        resume=True,
        request_counter=lambda: baseline_requests["value"],
        now=lambda: "2026-07-26T00:00:00+00:00",
    )
    recovered_bytes = {
        path.name: path.read_bytes() for path in sorted(race_store.items_dir.glob("*.json"))
    }
    baseline_bytes = {
        path.name: path.read_bytes() for path in sorted(baseline.items_dir.glob("*.json"))
    }
    if recovered_bytes != baseline_bytes:
        raise ValueError("synthetic resume bytes differ from uninterrupted baseline")

    races_sha = upstream_index_sha(race_store)
    profile_records: list[dict[str, Any]] = []
    for suffix in ("a", "b"):
        key = f"japan|synthetic-{suffix}"
        seed = HorseSeed(
            key=key,
            regions={"japan"},
            display_names={f"Synthetic {suffix.upper()}"},
        )
        if suffix == "a":
            seed.resolution_state = "error"
            seed.match_status = ""
            seed.error_code = "profile_detail_transport_error"
        record = seed_to_record(seed)
        record.update(
            {
                "status": "retryable_error" if suffix == "a" else "success",
                "lookup_keys": [key],
                "error_code": seed.error_code,
            }
        )
        profile_records.append(record)
    profile_shard = new_bound_store(
        root,
        stage="profiles",
        shard_index=0,
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes={"races": races_sha},
        input_keys=(record["key"] for record in profile_records),
    )
    for record in profile_records:
        profile_shard.save_item(record["key"], record)
    profile_shard.rebuild_index(request_count=2)
    run_stage(
        parse_args(
            ["--stage", "merge_profiles", "--shard-count", "1", "--output-dir", str(root)]
        )
    )
    profile_store = StageStore(
        root,
        stage="profiles_merged",
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes={
            "races": races_sha,
            "profiles:0": upstream_index_sha(profile_shard),
        },
        input_keys_sha256=keys_sha256(record["key"] for record in profile_records),
    )
    profiles_sha = upstream_index_sha(profile_store)

    search_records: list[dict[str, Any]] = []
    for record in profile_records:
        item = dict(record)
        if record["key"].endswith("-a"):
            item["search_requests"] = [
                {
                    "query": "",
                    "language": "",
                    "status": "retryable_error",
                    "error_code": "profile_detail_transport_error",
                }
            ]
        else:
            item["search_requests"] = [
                {
                    "query": "Synthetic B",
                    "language": "en",
                    "status": "success",
                    "candidates": [],
                }
            ]
        search_records.append(item)
    search_shard = new_bound_store(
        root,
        stage="wikidata_search",
        shard_index=0,
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes={"profiles_merged": profiles_sha},
        input_keys=(record["key"] for record in search_records),
    )
    for record in search_records:
        search_shard.save_item(record["key"], record)
    search_shard.rebuild_index(request_count=1)
    run_stage(
        parse_args(
            ["--stage", "merge_search", "--shard-count", "1", "--output-dir", str(root)]
        )
    )
    search_store = StageStore(
        root,
        stage="wikidata_search_merged",
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes={
            "profiles_merged": profiles_sha,
            "wikidata_search:0": upstream_index_sha(search_shard),
        },
        input_keys_sha256=keys_sha256(record["key"] for record in search_records),
    )
    search_sha = upstream_index_sha(search_store)

    entity_shard = new_bound_store(
        root,
        stage="wikidata_entities",
        shard_index=0,
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes={"wikidata_search_merged": search_sha},
        input_keys=[],
    )
    entity_shard.rebuild_index(request_count=0)
    run_stage(
        parse_args(
            ["--stage", "merge_entities", "--shard-count", "1", "--output-dir", str(root)]
        )
    )
    entity_store = StageStore(
        root,
        stage="wikidata_entities_merged",
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes={
            "wikidata_search_merged": search_sha,
            "wikidata_entities:0": upstream_index_sha(entity_shard),
        },
        input_keys_sha256=keys_sha256([]),
    )
    entity_sha = upstream_index_sha(entity_store)

    score_shard = new_bound_store(
        root,
        stage="scored_horses",
        shard_index=0,
        shard_count=1,
        manifest_sha256=manifest_sha,
        upstream_indexes={
            "wikidata_search_merged": search_sha,
            "wikidata_entities_merged": entity_sha,
        },
        input_keys=(record["key"] for record in profile_records),
    )
    for record in profile_records:
        seed = seed_from_record(record)
        if seed.resolution_state != "error":
            seed.resolution_state = "resolved"
            seed.match_status = "no_page"
        scored = seed_to_record(seed)
        scored["status"] = "success"
        score_shard.save_item(seed.key, scored)
    score_shard.rebuild_index(request_count=0)
    run_stage(
        parse_args(
            ["--stage", "merge_scores", "--shard-count", "1", "--output-dir", str(root)]
        )
    )

    finalize_args = parse_args(
        ["--stage", "finalize", "--output-dir", str(root)]
    )
    run_stage(finalize_args)
    report = {
        "safe_stopped": False,
        "safe_stop_evidence_present": (root / "safe_stop.json").exists(),
        "byte_equivalent": True,
        "recovered_items_sha256": race_store.verify_index()["items_sha256"],
        "baseline_items_sha256": baseline.verify_index()["items_sha256"],
        "final_files": sorted(path.name for path in (root / "final").iterdir() if path.is_file()),
    }
    atomic_write_json(root / "synthetic_smoke_report.json", report)
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://umafans.run")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--cutoff", default="2026-07-26", help="Inclusive YYYY-MM-DD cutoff")
    parser.add_argument("--output-dir", default="runtime/research/output/2026-graded-top5-wikipedia")
    parser.add_argument("--delay", type=float, default=0.12, help="Delay after every HTTP response")
    parser.add_argument("--timeout", type=float, default=40.0)
    parser.add_argument("--max-races", type=int, default=0, help="Debug limit after sitemap discovery")
    parser.add_argument("--skip-wikipedia", action="store_true")
    parser.add_argument(
        "--stage",
        choices=(
            "races", "profiles", "merge_profiles", "wikidata_search", "merge_search",
            "wikidata_entities", "merge_entities", "score_horses", "merge_scores", "finalize",
            "synthetic_smoke",
        ),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--races-shard-index", type=int, default=0)
    parser.add_argument("--races-shard-count", type=int, default=1)
    parser.add_argument("--time-budget-seconds", type=float, default=0)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.year != 2026:
        raise SystemExit("This research artifact is intentionally scoped to 2026")
    cutoff = date.fromisoformat(args.cutoff)
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("invalid shard parameters")
    if args.stage:
        if args.stage == "synthetic_smoke":
            result = run_synthetic_smoke(
                Path(args.output_dir), stop_after=1 if args.limit else 0
            )
            return int(result.get("exit_code", 0))
        return run_stage(args)
    raise SystemExit("--stage is required; the unsafe monolithic network run is disabled")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now_iso()
    client = HttpClient(
        delay=args.delay,
        timeout=args.timeout,
        user_agent="UmaFansResearch/1.0 (2026 graded top-five Wikipedia mapping; non-commercial research)",
    )
    base_url = resolve_base_url(client, args.base_url)
    LOGGER.info("Using UmaFans base URL %s", base_url)
    collector = UmaFansCollector(
        base_url=base_url,
        client=client,
        output_dir=output_dir,
        year=args.year,
        cutoff=cutoff,
    )
    rows, included_races = collector.collect_races(max_races=args.max_races)
    if not rows:
        (output_dir / "errors.json").write_text(
            json.dumps(collector.errors, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise RuntimeError("No in-scope top-five rows were collected")
    LOGGER.info("Collected %s top-five rows from %s races", len(rows), included_races)
    horses = collector.enrich_horse_profiles(rows)
    LOGGER.info("Built %s horse identity seeds", len(horses))
    if not args.skip_wikipedia:
        resolver = WikidataResolver(client=client, output_dir=output_dir)
        resolver.resolve(horses)
    else:
        for seed in horses.values():
            seed.match_status = "not_run"
            seed.match_evidence = "Wikipedia resolution skipped"
    assign_horse_results(rows, horses)
    summary = write_outputs(
        output_dir=output_dir,
        rows=rows,
        horses=horses,
        collector=collector,
        included_races=included_races,
        base_url=base_url,
        cutoff=cutoff,
        started_at=started_at,
        request_count=client.request_count,
    )
    LOGGER.info("Summary: %s", json.dumps(summary["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

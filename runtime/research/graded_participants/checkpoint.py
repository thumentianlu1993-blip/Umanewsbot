from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from .core import (
    PARSER_VERSION, SCHEMA_VERSION, TERMINAL_STATUSES, atomic_write_json,
    canonical_json_bytes, keys_sha256, sha256_bytes, stable_shard, utc_now_iso,
)


class CheckpointStore:
    def __init__(self, root: Path, *, stage: str, manifest_sha256: str,
                 shard_index: int | None = None, shard_count: int = 1,
                 input_keys_sha256: str = ""):
        self.root = root; self.stage = stage; self.shard_index = shard_index
        self.shard_count = shard_count; self.manifest_sha256 = manifest_sha256
        self.input_keys_sha256 = input_keys_sha256
        base = root / "stages" / stage
        if shard_index is not None: base = base / "shards" / str(shard_index)
        self.path = base; self.items_dir = base / "items"
        self.index_path = base / "index.json"; self.progress_path = base / "progress.json"

    @staticmethod
    def filename(key: str) -> str:
        return sha256_bytes(key.encode("utf-8")) + ".json"

    def item_path(self, key: str) -> Path:
        return self.items_dir / self.filename(key)

    def load_item(self, key: str) -> dict[str, Any] | None:
        path = self.item_path(key)
        if not path.exists(): return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("key") != key: raise ValueError(f"checkpoint key mismatch: {key}")
        return value

    def save_item(self, key: str, value: dict[str, Any]) -> None:
        payload = dict(value); payload["key"] = key
        atomic_write_json(self.item_path(key), payload)
        print(f"CHECKPOINT_SAVED path={self.item_path(key)}", flush=True)

    def rebuild_index(self, *, request_count: int = 0) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if self.items_dir.exists():
            for path in sorted(self.items_dir.glob("*.json")):
                payload = path.read_bytes(); item = json.loads(payload); key = str(item.get("key", ""))
                if not key or path.name != self.filename(key): raise ValueError(f"invalid checkpoint item: {path}")
                items.append({
                    "key": key, "status": item.get("status", ""),
                    "path": path.relative_to(self.root).as_posix(), "sha256": sha256_bytes(payload),
                })
        items.sort(key=lambda item: item["key"])
        index = {
            "schema_version": SCHEMA_VERSION, "parser_version": PARSER_VERSION,
            "stage": self.stage, "shard_index": self.shard_index, "shard_count": self.shard_count,
            "manifest_sha256": self.manifest_sha256, "input_keys_sha256": self.input_keys_sha256,
            "request_count": request_count, "items": items,
            "items_sha256": sha256_bytes(canonical_json_bytes(items)),
        }
        atomic_write_json(self.index_path, index); return index

    def verify_index(self) -> dict[str, Any]:
        index = json.loads(self.index_path.read_text(encoding="utf-8"))
        expected = {
            "schema_version": SCHEMA_VERSION, "parser_version": PARSER_VERSION,
            "stage": self.stage, "shard_index": self.shard_index,
            "shard_count": self.shard_count, "manifest_sha256": self.manifest_sha256,
            "input_keys_sha256": self.input_keys_sha256,
        }
        for key, value in expected.items():
            if index.get(key) != value: raise ValueError(f"stage index drift: {key}")
        if sha256_bytes(canonical_json_bytes(index.get("items", []))) != index.get("items_sha256"):
            raise ValueError("stage index summary drift")
        return index

    def records(self) -> list[dict[str, Any]]:
        index = self.verify_index()
        return [json.loads((self.root / item["path"]).read_text(encoding="utf-8")) for item in index["items"]]


def store_for(root: Path, *, stage: str, manifest_sha: str, keys: Iterable[str],
              shard_index: int | None, shard_count: int) -> CheckpointStore:
    selected = [key for key in sorted(set(keys)) if shard_index is None or stable_shard(key, shard_count) == shard_index]
    return CheckpointStore(
        root, stage=stage, manifest_sha256=manifest_sha, shard_index=shard_index,
        shard_count=shard_count, input_keys_sha256=keys_sha256(selected),
    )


def run_checkpointed(keys: Iterable[str], *, store: CheckpointStore,
                     process: Callable[[str], dict[str, Any]], resume: bool,
                     start_index: int, limit: int, time_budget_seconds: float,
                     checkpoint_every: int, request_counter: Callable[[], int] | None = None) -> dict[str, Any]:
    planned = [key for key in sorted(set(keys)) if stable_shard(key, store.shard_count) == (store.shard_index or 0)]
    digest = keys_sha256(planned)
    if store.input_keys_sha256 and store.input_keys_sha256 != digest: raise ValueError("stage input key drift")
    store.input_keys_sha256 = digest
    selected = planned[start_index:]
    if limit: selected = selected[:limit]
    prior_requests = int(store.verify_index().get("request_count", 0)) if store.index_path.exists() else 0
    request_start = request_counter() if request_counter else 0
    started = time.monotonic(); cached = failed = processed = 0; last_key = ""; safe_stopped = False
    for key in selected:
        if time_budget_seconds and time.monotonic() - started >= time_budget_seconds:
            safe_stopped = True; break
        existing = store.load_item(key)
        if resume and existing and existing.get("status") in TERMINAL_STATUSES:
            cached += 1; continue
        try:
            value = process(key); value.setdefault("status", "success")
        except Exception as exc:
            value = {"status": "retryable_error", "error_code": type(exc).__name__, "error": str(exc)}
            failed += 1
        store.save_item(key, value); processed += 1; last_key = key
        if processed % max(1, checkpoint_every) == 0:
            requests = prior_requests + ((request_counter() - request_start) if request_counter else 0)
            store.rebuild_index(request_count=requests)
    requests = prior_requests + ((request_counter() - request_start) if request_counter else 0)
    index = store.rebuild_index(request_count=requests)
    completed = {item["key"] for item in index["items"] if item.get("status") in TERMINAL_STATUSES}
    safe_stopped = safe_stopped or completed != set(planned)
    progress = {
        "stage": store.stage, "processed": len(index["items"]), "total": len(planned),
        "cached": cached, "failed_this_run": failed, "last_object": last_key,
        "safe_stopped": safe_stopped, "elapsed_seconds": round(time.monotonic() - started, 3),
        "request_count": requests, "updated_at": utc_now_iso(),
    }
    atomic_write_json(store.progress_path, progress)
    print(f"[stage={store.stage}] {progress['processed']}/{progress['total']} cached={cached} errors={failed} elapsed={progress['elapsed_seconds']}", flush=True)
    return progress


def merge_stage(root: Path, *, source_stage: str, target_stage: str,
                manifest_sha: str, keys: list[str], shard_count: int) -> None:
    records: dict[str, dict[str, Any]] = {}; request_count = 0
    for shard in range(shard_count):
        shard_keys = [key for key in keys if stable_shard(key, shard_count) == shard]
        store = store_for(root, stage=source_stage, manifest_sha=manifest_sha,
                          keys=shard_keys, shard_index=shard, shard_count=shard_count)
        index = store.verify_index(); request_count += int(index.get("request_count", 0))
        for record in store.records():
            key = record["key"]
            if key in records and canonical_json_bytes(records[key]) != canonical_json_bytes(record):
                raise ValueError(f"conflicting shard record: {key}")
            records[key] = record
    if set(records) != set(keys):
        missing = sorted(set(keys) - set(records)); raise ValueError(f"incomplete {source_stage} coverage: {missing[:5]}")
    target = store_for(root, stage=target_stage, manifest_sha=manifest_sha,
                       keys=keys, shard_index=None, shard_count=1)
    for key in sorted(records): target.save_item(key, records[key])
    target.rebuild_index(request_count=request_count)

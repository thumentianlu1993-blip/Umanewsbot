#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import fcntl
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class RequestBudgetExceeded(RuntimeError):
    pass


def _max_requests() -> int:
    return max(0, int(os.environ.get("RACE_EVENT_CRAWL_MAX_REQUESTS", "0") or 0))


def _request_interval() -> float:
    return max(
        0.0,
        float(os.environ.get("RACE_EVENT_CRAWL_REQUEST_INTERVAL_SECONDS", "0") or 0),
    )


def _artifact_path() -> Path | None:
    value = os.environ.get("RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT", "").strip()
    return Path(value) if value else None


def _host_interval_artifact_path() -> Path | None:
    value = os.environ.get("RACE_EVENT_CRAWL_HOST_INTERVAL_ARTIFACT", "").strip()
    return Path(value) if value else None


def _read_state(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {"request_count": 0, "requests": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RequestBudgetExceeded(f"request budget artifact is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise RequestBudgetExceeded(f"request budget artifact is invalid: {path}")
    return payload


def _write_state(path: Path | None, state: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def _budget_lock(path: Path | None):
    if path is None:
        yield
        return
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _reserve_interval(path: Path, *, interval: float, url: str, method: str) -> float:
    with _budget_lock(path):
        state = _read_state(path)
        last_started = float(state.get("last_request_started_at_epoch") or 0.0)
        remaining = interval - (time.time() - last_started)
        if remaining > 0:
            time.sleep(remaining)
        started_epoch = time.time()
        request_count = int(state.get("request_count") or 0) + 1
        requests = state.get("requests") if isinstance(state.get("requests"), list) else []
        requests.append(
            {
                "sequence": request_count,
                "method": method,
                "url": url,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        state.update(
            {
                "status": "active",
                "request_interval_seconds": interval,
                "request_count": request_count,
                "last_request_started_at_epoch": started_epoch,
                "requests": requests[-200:],
            }
        )
        _write_state(path, state)
        return started_epoch


def _host_artifact_for_url(host_interval_dir: Path, url: str) -> Path:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "unknown").casefold()
    safe_host = "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in host)
    return host_interval_dir / f"{safe_host}.json"


def check_request_budget(
    url: str,
    *,
    method: str = "GET",
    artifact_path: Path | str | None = None,
    max_requests: int = 0,
    interval: float = 0.0,
    host_interval_path: Path | str | None = None,
    host_interval_dir: Path | str | None = None,
    budget_label: str = "request",
) -> None:
    """Explicit-config request budget check shared by race crawls and P0 batches.

    Counts the request in the persistent artifact (flock-protected), enforces
    ``max_requests`` (0 = unlimited), and applies the per-host interval via
    either a single shared artifact or per-host artifacts derived from
    ``host_interval_dir``. Corrupted artifacts and lock failures fail closed.
    """
    path = Path(artifact_path) if artifact_path else None
    if host_interval_dir is not None:
        resolved_host_path = _host_artifact_for_url(Path(host_interval_dir), url)
    elif host_interval_path is not None:
        resolved_host_path = Path(host_interval_path)
    else:
        resolved_host_path = None
    with _budget_lock(path):
        state = _read_state(path)
        request_count = int(state.get("request_count") or 0)
        if max_requests and request_count >= max_requests:
            state.update(
                {
                    "status": "limit_exceeded",
                    "max_requests": max_requests,
                    "request_interval_seconds": interval,
                    "stopped_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            _write_state(path, state)
            raise RequestBudgetExceeded(
                f"{budget_label} budget exhausted: {request_count}/{max_requests}"
            )

        if resolved_host_path is not None and resolved_host_path != path:
            started_epoch = _reserve_interval(
                resolved_host_path,
                interval=interval,
                url=url,
                method=method,
            )
        else:
            last_started = float(state.get("last_request_started_at_epoch") or 0.0)
            remaining = interval - (time.time() - last_started)
            if remaining > 0:
                time.sleep(remaining)
            started_epoch = time.time()
        requests = state.get("requests") if isinstance(state.get("requests"), list) else []
        requests.append(
            {
                "sequence": request_count + 1,
                "method": method,
                "url": url,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        state.update(
            {
                "status": "active",
                "max_requests": max_requests,
                "request_interval_seconds": interval,
                "request_count": request_count + 1,
                "last_request_started_at_epoch": started_epoch,
                "requests": requests[-200:],
            }
        )
        _write_state(path, state)


def before_network_request(url: str, *, method: str = "GET") -> None:
    check_request_budget(
        url,
        method=method,
        artifact_path=_artifact_path(),
        max_requests=_max_requests(),
        interval=_request_interval(),
        host_interval_path=_host_interval_artifact_path(),
        budget_label="race event crawl request",
    )

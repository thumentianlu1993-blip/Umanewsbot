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


def before_network_request(url: str, *, method: str = "GET") -> None:
    max_requests = _max_requests()
    interval = _request_interval()
    path = _artifact_path()
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
                f"race event crawl request budget exhausted: {request_count}/{max_requests}"
            )

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

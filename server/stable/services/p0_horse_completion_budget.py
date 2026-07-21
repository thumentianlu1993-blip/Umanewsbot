"""Persistent request budget wiring for P0 horse completion source clients.

Loads the shared race-event request budget tool (single implementation for
both specials) via importlib, following the race orchestration precedent,
and exposes a per-region ledger + per-host throttle entry point for the
rolling P0 batch pipeline.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from django.conf import settings


_BUDGET_MODULE_CACHE: Any = None


def load_race_event_request_budget_module() -> Any:
    global _BUDGET_MODULE_CACHE
    if _BUDGET_MODULE_CACHE is not None:
        return _BUDGET_MODULE_CACHE
    repo_root = Path(settings.BASE_DIR).resolve().parent
    path = repo_root / "runtime" / "tools" / "race_event_request_budget.py"
    spec = importlib.util.spec_from_file_location(
        "race_event_request_budget_shared", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load request budget tool: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _BUDGET_MODULE_CACHE = module
    return module


def default_budget_dir() -> Path:
    configured = getattr(settings, "HORSE_PROFILE_COMPLETION_BUDGET_DIR", "") or (
        "runtime/horse_profile_completion/budget"
    )
    return Path(configured)


def before_p0_horse_source_request(
    url: str,
    *,
    region: str,
    budget_dir: str | Path | None = None,
    interval: float | None = None,
    max_requests: int | None = None,
    host_interval_dir: str | Path | None = None,
) -> None:
    """Fail-closed budget + throttle gate before every P0 source request.

    Every attempt (including retries) is counted in the persistent per-region
    ledger and throttled by the per-host artifact shared across runs. The
    ledger directory is run-scoped by the caller (per batch), so
    ``max_requests`` always means per-run, never cumulative history.
    """
    budget = load_race_event_request_budget_module()
    root = Path(budget_dir) if budget_dir is not None else default_budget_dir()
    effective_interval = (
        float(interval)
        if interval is not None
        else float(
            getattr(settings, "HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS", 8.0)
        )
    )
    effective_max = (
        int(max_requests)
        if max_requests is not None
        else int(getattr(settings, "HORSE_PROFILE_COMPLETION_MAX_REQUESTS", 0))
    )
    budget.check_request_budget(
        url,
        artifact_path=root / f"{region}.json",
        max_requests=effective_max,
        interval=effective_interval,
        host_interval_dir=Path(host_interval_dir)
        if host_interval_dir is not None
        else root / "host-interval",
        budget_label=f"P0 horse completion ({region})",
    )

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlsplit

from django.conf import settings
from django.db.models import Q
from django.utils import timezone as django_timezone

from stable import models
from stable.services.race_data_sync_pipeline import RaceDataSyncFlags


PROOF_SCHEMA = "racing-api-exclusive-account-proof.v1"
HOST_EVIDENCE_SCHEMA = "racing-api-host-process-preflight.v2"
HOST = "api.theracingapi.com"
THE_RACING_API_SOURCE = "the_racing_api"
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MAX_EVIDENCE_BYTES = 1024 * 1024
QUEUE_NAMES = ("celery", "race_live", "race_sync_v2")
NETWORK_WORKER_NAME_RE = re.compile(
    r"(?:^|[-_.])(?:race[-_]live|race[-_]sync[-_]v2)[-_]worker(?:$|[-_.])"
)


class RacingApiExclusivePreflightError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_object(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise RacingApiExclusivePreflightError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _read_private_json(path: Path, *, label: str) -> tuple[bytes, dict]:
    if path.is_symlink():
        raise RacingApiExclusivePreflightError(f"{label} must not be a symlink")
    try:
        metadata = path.stat(follow_symlinks=False)
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RacingApiExclusivePreflightError(f"{label} is missing") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or not resolved.is_file()
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_size > MAX_EVIDENCE_BYTES
    ):
        raise RacingApiExclusivePreflightError(f"{label} is not a private regular file")
    raw = resolved.read_bytes()
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                RacingApiExclusivePreflightError(f"invalid JSON constant: {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RacingApiExclusivePreflightError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise RacingApiExclusivePreflightError(f"{label} must be an object")
    return raw, value


def _parse_time(value: object, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise RacingApiExclusivePreflightError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise RacingApiExclusivePreflightError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _now(value: datetime | None) -> datetime:
    result = value or django_timezone.now()
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise RacingApiExclusivePreflightError("clock must be timezone-aware")
    return result.astimezone(timezone.utc)


def _task_names(payload: Mapping[str, object]) -> list[str]:
    names = []
    for rows in payload.values():
        if not isinstance(rows, list):
            raise RacingApiExclusivePreflightError("Celery task snapshot is invalid")
        for row in rows:
            if not isinstance(row, Mapping):
                raise RacingApiExclusivePreflightError("Celery task row is invalid")
            names.append(str(row.get("name") or ""))
    return sorted(names)


def _worker_matches(expected: str, actual: str) -> bool:
    return expected == actual or actual.endswith("@" + expected)


def _queue_names(payload: Mapping[str, object]) -> list[str]:
    names = []
    for rows in payload.values():
        if not isinstance(rows, list):
            raise RacingApiExclusivePreflightError("Celery queue snapshot is invalid")
        for row in rows:
            if not isinstance(row, Mapping) or not str(row.get("name") or "").strip():
                raise RacingApiExclusivePreflightError("Celery queue row is invalid")
            names.append(str(row["name"]))
    return sorted(set(names))


def collect_celery_idle_snapshot(
    *, expected_worker_nodes: Iterable[str], timeout: float = 5.0
) -> dict[str, Any]:
    expected = tuple(str(value).strip() for value in expected_worker_nodes if str(value).strip())
    if not expected or any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)
        for value in expected
    ):
        raise RacingApiExclusivePreflightError("expected Celery worker nodes are invalid")
    try:
        from app.celery import app

        inspector = app.control.inspect(timeout=timeout)
        ping = inspector.ping()
        active = inspector.active()
        reserved = inspector.reserved()
        scheduled = inspector.scheduled()
        active_confirm = inspector.active()
        active_queues = inspector.active_queues()
    except Exception as exc:
        raise RacingApiExclusivePreflightError(
            f"Celery inspection failed: {exc.__class__.__name__}"
        ) from exc
    snapshots = (ping, active, reserved, scheduled, active_confirm, active_queues)
    if any(not isinstance(value, dict) or not value for value in snapshots):
        raise RacingApiExclusivePreflightError("Celery inspection returned no worker snapshot")
    workers = set(ping)
    if any(set(value) != workers for value in snapshots[1:]):
        raise RacingApiExclusivePreflightError("Celery inspection returned a partial snapshot")
    missing = [
        expected_node
        for expected_node in expected
        if not any(_worker_matches(expected_node, actual) for actual in workers)
    ]
    unexpected = [
        actual
        for actual in workers
        if not any(_worker_matches(expected_node, actual) for expected_node in expected)
    ]
    if missing or unexpected:
        raise RacingApiExclusivePreflightError(
            "Celery snapshot has missing or unexpected workers"
        )
    active_names = _task_names(active)
    reserved_names = _task_names(reserved)
    scheduled_names = _task_names(scheduled)
    active_confirm_names = _task_names(active_confirm)
    subscribed_queues = _queue_names(active_queues)
    if active_names or reserved_names or scheduled_names or active_confirm_names:
        raise RacingApiExclusivePreflightError("Celery workers are not fully idle")
    if subscribed_queues != ["celery"]:
        raise RacingApiExclusivePreflightError(
            "Celery workers subscribe to a non-default queue"
        )
    return {
        "workers": sorted(workers),
        "expected_workers": list(expected),
        "active_count": 0,
        "reserved_count": 0,
        "scheduled_count": 0,
        "active_confirm_count": 0,
        "subscribed_queues": subscribed_queues,
    }


def collect_broker_queue_lengths() -> dict[str, int]:
    broker_url = str(getattr(settings, "CELERY_BROKER_URL", ""))
    parsed = urlsplit(broker_url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise RacingApiExclusivePreflightError("Celery broker is not a supported Redis URL")
    try:
        from redis import Redis

        client = Redis.from_url(broker_url, socket_timeout=5, socket_connect_timeout=5)
        lengths = {queue: int(client.llen(queue)) for queue in QUEUE_NAMES}
    except Exception as exc:
        raise RacingApiExclusivePreflightError(
            f"Redis queue inspection failed: {exc.__class__.__name__}"
        ) from exc
    if any(value < 0 for value in lengths.values()):
        raise RacingApiExclusivePreflightError("Redis queue length is invalid")
    return lengths


def _validate_host_evidence(
    *,
    path: Path,
    expected_sha256: str,
    expected_role: str,
    scope_id: str,
    scope_manifest_sha256: str,
    now: datetime,
) -> tuple[dict, str]:
    if not SHA256_RE.fullmatch(str(expected_sha256 or "")):
        raise RacingApiExclusivePreflightError("host evidence SHA-256 is invalid")
    raw, evidence = _read_private_json(path, label="host process evidence")
    actual_sha = hashlib.sha256(raw).hexdigest()
    captured_at = _parse_time(evidence.get("captured_at"), label="host evidence captured_at")
    if (
        actual_sha != expected_sha256
        or evidence.get("schema_version") != HOST_EVIDENCE_SCHEMA
        or evidence.get("host_role") != expected_role
        or not IDENTIFIER_RE.fullmatch(str(evidence.get("host") or ""))
        or evidence.get("scope_id") != scope_id
        or evidence.get("scope_manifest_sha256") != scope_manifest_sha256
        or evidence.get("host_ps_available") is not True
        or evidence.get("docker_ps_available") is not True
        or evidence.get("network_requests") != 0
        or evidence.get("database_writes") != 0
        or not isinstance(evidence.get("containers"), list)
        or evidence.get("matching_processes") != []
        or captured_at > now
        or now - captured_at > timedelta(minutes=2)
    ):
        raise RacingApiExclusivePreflightError("host process evidence is not clean and fresh")
    return evidence, actual_sha


def _network_worker_containers(evidence: Mapping[str, object]) -> list[str]:
    containers = evidence.get("containers")
    if not isinstance(containers, list):
        raise RacingApiExclusivePreflightError("host container evidence is invalid")
    matches = []
    for row in containers:
        if not isinstance(row, Mapping):
            raise RacingApiExclusivePreflightError("host container row is invalid")
        name = str(row.get("name") or "")
        if not name:
            raise RacingApiExclusivePreflightError("host container name is invalid")
        if NETWORK_WORKER_NAME_RE.search(name):
            matches.append(name)
    return sorted(matches)


def _atomic_private_write(path: Path, payload: bytes) -> None:
    if path.is_symlink() or path.exists():
        raise RacingApiExclusivePreflightError("proof output must be absent")
    parent = path.parent.resolve(strict=True)
    if path.parent.is_symlink() or not parent.is_dir():
        raise RacingApiExclusivePreflightError("proof output parent is invalid")
    if stat.S_IMODE(parent.stat(follow_symlinks=False).st_mode) & 0o077:
        raise RacingApiExclusivePreflightError("proof output parent must be private")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def generate_exclusive_account_proof(
    *,
    credential_alias: str,
    scope_id: str,
    scope_manifest_sha256: str,
    runner_host_evidence_path: Path,
    runner_host_evidence_sha256: str,
    production_host_evidence_path: Path,
    production_host_evidence_sha256: str,
    expected_worker_nodes: Iterable[str],
    reserved_by: str,
    decision_source_reference: str,
    output_file: Path,
    valid_minutes: int = 15,
    now: datetime | None = None,
    celery_collector: Callable[..., dict[str, Any]] = collect_celery_idle_snapshot,
    queue_collector: Callable[[], dict[str, int]] = collect_broker_queue_lengths,
) -> dict:
    clock = _now(now)
    if (
        not IDENTIFIER_RE.fullmatch(str(credential_alias or ""))
        or not IDENTIFIER_RE.fullmatch(str(scope_id or ""))
        or not SHA256_RE.fullmatch(str(scope_manifest_sha256 or ""))
        or isinstance(valid_minutes, bool)
        or not isinstance(valid_minutes, int)
        or not 1 <= valid_minutes <= 15
        or not str(reserved_by or "").strip()
        or not str(decision_source_reference or "").strip()
    ):
        raise RacingApiExclusivePreflightError("exclusive proof inputs are invalid")
    runner_host_evidence, runner_host_sha = _validate_host_evidence(
        path=runner_host_evidence_path,
        expected_sha256=runner_host_evidence_sha256,
        expected_role="runner",
        scope_id=scope_id,
        scope_manifest_sha256=scope_manifest_sha256,
        now=clock,
    )
    production_host_evidence, production_host_sha = _validate_host_evidence(
        path=production_host_evidence_path,
        expected_sha256=production_host_evidence_sha256,
        expected_role="production",
        scope_id=scope_id,
        scope_manifest_sha256=scope_manifest_sha256,
        now=clock,
    )
    if runner_host_evidence["host"] == production_host_evidence["host"]:
        raise RacingApiExclusivePreflightError(
            "runner and production host evidence must cover distinct hosts"
        )
    if _network_worker_containers(runner_host_evidence) or _network_worker_containers(
        production_host_evidence
    ):
        raise RacingApiExclusivePreflightError(
            "a Racing API-capable Celery worker container is present"
        )
    flags = RaceDataSyncFlags.from_settings()
    race_live_scheduler_enabled = bool(
        getattr(settings, "RACE_LIVE_SCHEDULER_ENABLED", False)
        or getattr(settings, "RACE_LIVE_MONITOR_ENABLED", False)
        or tuple(getattr(settings, "RACE_LIVE_ENABLED_REGIONS", ()))
    )
    race_data_sync_network_enabled = bool(
        flags.enabled or flags.scheduler_enabled or flags.allow_network
    )
    active_tracking = models.RaceEventLiveTracking.objects.filter(
        Q(active_attempt_token__gt="") | Q(claim_expires_at__isnull=False)
    ).count()
    active_lifecycle = models.RaceEventLifecycleControl.objects.filter(
        Q(claim_token__gt="") | Q(claim_expires_at__isnull=False)
    ).count()
    active_import_locks = models.ExternalDataImportLock.objects.filter(
        # The proof-only release intentionally precedes the broader staging
        # migration that adds this value to ExternalDataSource choices. A
        # stable string lookup remains valid before and after that migration.
        source=THE_RACING_API_SOURCE,
        locked_by_run__isnull=False,
    ).count()
    celery = celery_collector(expected_worker_nodes=expected_worker_nodes)
    queue_lengths = queue_collector()
    if set(queue_lengths) != set(QUEUE_NAMES) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in queue_lengths.values()
    ):
        raise RacingApiExclusivePreflightError("Celery broker queue snapshot is invalid")
    if queue_lengths["celery"] != 0 or queue_lengths["race_sync_v2"] != 0:
        raise RacingApiExclusivePreflightError("Celery broker queues are not empty")
    checks = {
        "race_live_scheduler_enabled": race_live_scheduler_enabled,
        "race_live_runner_active": active_tracking + active_lifecycle,
        "race_data_sync_network_enabled": race_data_sync_network_enabled,
        "race_data_sync_active_claims": active_tracking,
        "other_backfill_processes": active_import_locks
        + len(runner_host_evidence["matching_processes"])
        + len(production_host_evidence["matching_processes"]),
        "manual_caller_window_reserved": True,
    }
    expected_checks = {
        "race_live_scheduler_enabled": False,
        "race_live_runner_active": 0,
        "race_data_sync_network_enabled": False,
        "race_data_sync_active_claims": 0,
        "other_backfill_processes": 0,
        "manual_caller_window_reserved": True,
    }
    if checks != expected_checks:
        raise RacingApiExclusivePreflightError("exclusive account preflight is not closed")
    payload = {
        "schema_version": PROOF_SCHEMA,
        "status": "approved",
        "host": HOST,
        "credential_alias": credential_alias,
        "scope_id": scope_id,
        "scope_manifest_sha256": scope_manifest_sha256,
        "observed_at": clock.isoformat().replace("+00:00", "Z"),
        "valid_until": (clock + timedelta(minutes=valid_minutes)).isoformat().replace(
            "+00:00", "Z"
        ),
        "checks": checks,
        "evidence": {
            "host_processes": [
                {
                    "role": "runner",
                    "sha256": runner_host_sha,
                    "host": runner_host_evidence["host"],
                    "container_count": len(runner_host_evidence["containers"]),
                },
                {
                    "role": "production",
                    "sha256": production_host_sha,
                    "host": production_host_evidence["host"],
                    "container_count": len(production_host_evidence["containers"]),
                },
            ],
            "celery": celery,
            "queue_lengths": dict(sorted(queue_lengths.items())),
            "active_tracking_claims": active_tracking,
            "active_lifecycle_claims": active_lifecycle,
            "active_the_racing_api_import_locks": active_import_locks,
            "reserved_by": str(reserved_by).strip(),
            "decision_source_reference": str(decision_source_reference).strip(),
        },
        "network_requests": 0,
        "database_writes": 0,
    }
    _atomic_private_write(output_file, _canonical_bytes(payload))
    return payload

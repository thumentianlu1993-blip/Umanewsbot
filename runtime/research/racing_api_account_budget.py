#!/usr/bin/env python3
"""The Racing API 账号级 one-shot 文件预算与独占调用证明。

该模块不访问网络、不读取凭据，也不写数据库。它只为已经通过 G3 的 one-shot 导出提供
跨进程 request slot；常驻 Django/Celery caller 继续使用数据库中的 RaceLiveHostBudget。
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator


SCHEMA_VERSION = "racing-api-account-budget.v1"
PROOF_SCHEMA_VERSION = "racing-api-exclusive-account-proof.v1"
HOST = "api.theracingapi.com"
STATE_NAME = "account-budget.json"
LOCK_NAME = "account-budget.lock"
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
REASON_RE = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,63}$")
MAX_STATE_BYTES = 64 * 1024


class AccountBudgetError(ValueError):
    pass


@dataclass(frozen=True)
class AccountReservation:
    request_number: int
    generation: int
    started_at_epoch: float
    next_allowed_at_epoch: float
    waited_seconds: float


def _strict_object(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise AccountBudgetError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _load_json_bytes(raw: bytes, *, label: str) -> dict:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                AccountBudgetError(f"invalid JSON constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AccountBudgetError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise AccountBudgetError(f"{label} must be a JSON object")
    return payload


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _safe_epoch(value: object, *, label: str, minimum: float = 0.0) -> float:
    if not _is_finite_number(value) or float(value) < minimum:
        raise AccountBudgetError(f"{label} is invalid")
    return float(value)


def _regular_private_file(path: Path, *, label: str, allow_missing: bool = False) -> os.stat_result | None:
    if path.is_symlink():
        raise AccountBudgetError(f"{label} must not be a symlink")
    try:
        value = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise AccountBudgetError(f"{label} is missing") from None
    if not stat.S_ISREG(value.st_mode):
        raise AccountBudgetError(f"{label} must be a regular file")
    if stat.S_IMODE(value.st_mode) & 0o077:
        raise AccountBudgetError(f"{label} permissions must not grant group/other access")
    return value


class FileAccountBudget:
    """在一个已独占的 TRA 账号窗口内跨进程串行化请求 attempt。"""

    def __init__(
        self,
        *,
        root: Path,
        credential_alias: str,
        scope_id: str,
        scope_manifest_sha256: str,
        request_ceiling: int,
        min_interval_seconds: float,
        valid_until_epoch: float,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        max_wait_seconds: float = 3600.0,
    ):
        if not IDENTIFIER_RE.fullmatch(str(credential_alias or "")):
            raise AccountBudgetError("credential alias is invalid")
        if not IDENTIFIER_RE.fullmatch(str(scope_id or "")):
            raise AccountBudgetError("scope id is invalid")
        if not SHA256_RE.fullmatch(str(scope_manifest_sha256 or "")):
            raise AccountBudgetError("scope manifest SHA-256 is invalid")
        if (
            isinstance(request_ceiling, bool)
            or not isinstance(request_ceiling, int)
            or request_ceiling < 1
        ):
            raise AccountBudgetError("request ceiling is invalid")
        if not _is_finite_number(min_interval_seconds) or not 0.001 <= float(
            min_interval_seconds
        ) <= 60.0:
            raise AccountBudgetError("minimum interval is invalid")
        interval_ms_float = float(min_interval_seconds) * 1000
        interval_ms = round(interval_ms_float)
        if abs(interval_ms_float - interval_ms) > 1e-9:
            raise AccountBudgetError("minimum interval must use whole milliseconds")
        if not _is_finite_number(max_wait_seconds) or float(max_wait_seconds) <= 0:
            raise AccountBudgetError("maximum wait is invalid")
        self.valid_until_epoch = _safe_epoch(
            valid_until_epoch,
            label="exclusive account proof valid-until",
            minimum=0.001,
        )

        supplied_root = Path(root)
        if supplied_root.is_symlink():
            raise AccountBudgetError("account budget root must not be a symlink")
        supplied_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if supplied_root.is_symlink() or not supplied_root.is_dir():
            raise AccountBudgetError("account budget root must be a directory")
        mode = stat.S_IMODE(supplied_root.stat(follow_symlinks=False).st_mode)
        if mode & 0o077:
            raise AccountBudgetError(
                "account budget root permissions must not grant group/other access"
            )

        self.root = supplied_root.resolve(strict=True)
        self.state_path = self.root / STATE_NAME
        self.lock_path = self.root / LOCK_NAME
        self.credential_alias = credential_alias
        self.scope_id = scope_id
        self.scope_manifest_sha256 = scope_manifest_sha256
        self.request_ceiling = request_ceiling
        self.min_interval_ms = interval_ms
        self._wall_clock = wall_clock
        self._sleep = sleep
        self.max_wait_seconds = float(max_wait_seconds)
        with self._locked():
            if self.state_path.exists() or self.state_path.is_symlink():
                self._validate_state(self._read_state_unlocked())
            else:
                self._write_state_unlocked(self._initial_state())

    def _initial_state(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "host": HOST,
            "credential_alias": self.credential_alias,
            "scope_id": self.scope_id,
            "scope_manifest_sha256": self.scope_manifest_sha256,
            "request_ceiling": self.request_ceiling,
            "min_interval_ms": self.min_interval_ms,
            "valid_until_epoch": self.valid_until_epoch,
            "request_count": 0,
            "generation": 0,
            "last_clock_at_epoch": 0.0,
            "last_reservation_at_epoch": 0.0,
            "next_allowed_at_epoch": 0.0,
            "last_defer_reason": "",
            "updated_at_epoch": 0.0,
        }

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if self.lock_path.is_symlink():
            raise AccountBudgetError("account budget lock must not be a symlink")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise AccountBudgetError("account budget lock cannot be opened") from exc
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or stat.S_IMODE(opened.st_mode) & 0o077:
                raise AccountBudgetError("account budget lock is not a private regular file")
            if self.lock_path.is_symlink():
                raise AccountBudgetError("account budget lock must not be a symlink")
            current = self.lock_path.stat(follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise AccountBudgetError("account budget lock identity changed")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _read_state_unlocked(self) -> dict:
        metadata = _regular_private_file(self.state_path, label="account budget state")
        if metadata is None or metadata.st_size > MAX_STATE_BYTES:
            raise AccountBudgetError("account budget state is too large")
        try:
            raw = self.state_path.read_bytes()
        except OSError as exc:
            raise AccountBudgetError("account budget state is unreadable") from exc
        if len(raw) != metadata.st_size:
            raise AccountBudgetError("account budget state changed while reading")
        return _load_json_bytes(raw, label="account budget state")

    def _write_state_unlocked(self, state: dict) -> None:
        self._validate_state(state)
        payload = _canonical_bytes(state)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".account-budget.", dir=self.root
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if self.state_path.is_symlink():
                raise AccountBudgetError("account budget state must not be a symlink")
            os.replace(temporary, self.state_path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _validate_state(self, state: dict) -> None:
        expected_identity = {
            "schema_version": SCHEMA_VERSION,
            "host": HOST,
            "credential_alias": self.credential_alias,
            "scope_id": self.scope_id,
            "scope_manifest_sha256": self.scope_manifest_sha256,
            "request_ceiling": self.request_ceiling,
            "min_interval_ms": self.min_interval_ms,
            "valid_until_epoch": self.valid_until_epoch,
        }
        if any(state.get(key) != expected for key, expected in expected_identity.items()):
            raise AccountBudgetError("account budget identity drift")
        for key in ("request_count", "generation"):
            value = state.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AccountBudgetError(f"account budget {key} is invalid")
        if state["request_count"] > self.request_ceiling:
            raise AccountBudgetError("account budget request count exceeds ceiling")
        for key in (
            "last_clock_at_epoch",
            "last_reservation_at_epoch",
            "next_allowed_at_epoch",
            "updated_at_epoch",
        ):
            _safe_epoch(state.get(key), label=f"account budget {key}")
        reason = state.get("last_defer_reason")
        if not isinstance(reason, str) or (reason and not REASON_RE.fullmatch(reason)):
            raise AccountBudgetError("account budget defer reason is invalid")

    def _validated_now(self, state: dict) -> float:
        now = _safe_epoch(self._wall_clock(), label="account budget clock")
        previous = _safe_epoch(
            state["last_clock_at_epoch"], label="account budget previous clock"
        )
        if now + 1e-6 < previous:
            raise AccountBudgetError("account budget clock moved backwards")
        if now >= self.valid_until_epoch:
            raise AccountBudgetError("exclusive account proof expired during run")
        return now

    def reserve(self) -> AccountReservation:
        total_waited = 0.0
        while True:
            with self._locked():
                state = self._read_state_unlocked()
                self._validate_state(state)
                now = self._validated_now(state)
                if state["request_count"] >= self.request_ceiling:
                    raise AccountBudgetError("account budget request ceiling exhausted")
                next_allowed = _safe_epoch(
                    state["next_allowed_at_epoch"],
                    label="account budget next allowed time",
                )
                wait_seconds = max(0.0, next_allowed - now)
                if now + wait_seconds >= self.valid_until_epoch:
                    raise AccountBudgetError(
                        "exclusive account proof expires before next request"
                    )
                if wait_seconds <= 1e-9:
                    state["request_count"] += 1
                    state["generation"] += 1
                    state["last_clock_at_epoch"] = now
                    state["last_reservation_at_epoch"] = now
                    state["next_allowed_at_epoch"] = now + (
                        self.min_interval_ms / 1000
                    )
                    state["updated_at_epoch"] = now
                    self._write_state_unlocked(state)
                    return AccountReservation(
                        request_number=state["request_count"],
                        generation=state["generation"],
                        started_at_epoch=now,
                        next_allowed_at_epoch=state["next_allowed_at_epoch"],
                        waited_seconds=total_waited,
                    )
            if wait_seconds > self.max_wait_seconds:
                raise AccountBudgetError("account budget wait exceeds maximum")
            self._sleep(wait_seconds)
            total_waited += wait_seconds

    def defer(self, seconds: float, *, reason: str) -> dict:
        if not _is_finite_number(seconds) or not 0 <= float(seconds) <= self.max_wait_seconds:
            raise AccountBudgetError("account budget defer interval is invalid")
        if not REASON_RE.fullmatch(str(reason or "")):
            raise AccountBudgetError("account budget defer reason is invalid")
        with self._locked():
            state = self._read_state_unlocked()
            self._validate_state(state)
            now = self._validated_now(state)
            if now + float(seconds) >= self.valid_until_epoch:
                raise AccountBudgetError(
                    "exclusive account proof expires during requested defer"
                )
            state["generation"] += 1
            state["last_clock_at_epoch"] = now
            state["next_allowed_at_epoch"] = max(
                float(state["next_allowed_at_epoch"]), now + float(seconds)
            )
            state["last_defer_reason"] = reason
            state["updated_at_epoch"] = now
            self._write_state_unlocked(state)
            return dict(state)

    def snapshot(self) -> dict:
        with self._locked():
            state = self._read_state_unlocked()
            self._validate_state(state)
            return dict(state)


def load_exclusive_account_proof(
    path: Path,
    *,
    expected_sha256: str,
    credential_alias: str,
    scope_id: str,
    scope_manifest_sha256: str,
    now: datetime,
) -> dict:
    supplied = Path(path)
    if supplied.is_symlink():
        raise AccountBudgetError("exclusive account proof must not be a symlink")
    try:
        resolved = supplied.resolve(strict=True)
    except OSError as exc:
        raise AccountBudgetError("exclusive account proof is missing") from exc
    metadata = _regular_private_file(resolved, label="exclusive account proof")
    if metadata is None or metadata.st_size > MAX_STATE_BYTES:
        raise AccountBudgetError("exclusive account proof is too large")
    raw = resolved.read_bytes()
    if not SHA256_RE.fullmatch(str(expected_sha256 or "")) or hashlib.sha256(
        raw
    ).hexdigest() != expected_sha256:
        raise AccountBudgetError("exclusive account proof SHA-256 mismatch")
    payload = _load_json_bytes(raw, label="exclusive account proof")
    identity = {
        "schema_version": PROOF_SCHEMA_VERSION,
        "status": "approved",
        "host": HOST,
        "credential_alias": credential_alias,
        "scope_id": scope_id,
        "scope_manifest_sha256": scope_manifest_sha256,
    }
    if any(payload.get(key) != value for key, value in identity.items()):
        raise AccountBudgetError("exclusive account proof identity drift")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise AccountBudgetError("exclusive account proof clock must be timezone-aware")
    try:
        observed_at = datetime.fromisoformat(
            str(payload.get("observed_at") or "").replace("Z", "+00:00")
        )
        valid_until = datetime.fromisoformat(
            str(payload.get("valid_until") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise AccountBudgetError("exclusive account proof time is invalid") from exc
    if observed_at.tzinfo is None or valid_until.tzinfo is None or observed_at >= valid_until:
        raise AccountBudgetError("exclusive account proof time window is invalid")
    if now < observed_at:
        raise AccountBudgetError("exclusive account proof is not yet valid")
    if now >= valid_until:
        raise AccountBudgetError("exclusive account proof expired")
    expected_checks = {
        "race_live_scheduler_enabled": False,
        "race_live_runner_active": 0,
        "race_data_sync_network_enabled": False,
        "race_data_sync_active_claims": 0,
        "other_backfill_processes": 0,
        "manual_caller_window_reserved": True,
    }
    checks = payload.get("checks")
    if not isinstance(checks, dict) or any(
        checks.get(key) != value for key, value in expected_checks.items()
    ):
        raise AccountBudgetError("exclusive account proof has active callers")
    return payload

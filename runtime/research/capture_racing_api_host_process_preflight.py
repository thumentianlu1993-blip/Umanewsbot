#!/usr/bin/env python3
"""在 Docker host 上只读捕获可能并发调用 The Racing API 的进程证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


SCHEMA_VERSION = "racing-api-host-process-preflight.v2"
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
PROCESS_MARKERS = (
    "racing_api_horse_export.py",
    "racing_api_targeted_batch_export.py",
    "racing_api_bulk_results_export.py",
)


class HostProcessPreflightError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    if path.is_symlink() or path.exists():
        raise HostProcessPreflightError("output file must be absent")
    parent = path.parent.resolve(strict=True)
    if path.parent.is_symlink() or not parent.is_dir():
        raise HostProcessPreflightError("output parent is invalid")
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


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostProcessPreflightError(
            f"read-only process command failed: {command[0]}"
        ) from exc
    return result.stdout


def _process_rows(output: str, *, source: str, excluded_pids: set[int]) -> list[dict]:
    matches = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise HostProcessPreflightError(f"{source} process output is invalid")
        if parts[0].upper() == "PID":
            continue
        try:
            pid = int(parts[0])
        except ValueError as exc:
            raise HostProcessPreflightError(f"{source} process PID is invalid") from exc
        command = parts[1]
        if pid in excluded_pids:
            continue
        markers = [marker for marker in PROCESS_MARKERS if marker in command]
        for marker in markers:
            matches.append(
                {
                    "source": source,
                    "pid": pid,
                    "marker": marker,
                    "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
                }
            )
    return matches


def capture_host_process_preflight(
    *,
    host_role: str,
    scope_id: str,
    scope_manifest_sha256: str,
    output_file: Path,
    now: datetime | None = None,
    runner: Callable[[list[str]], str] = _run,
) -> dict:
    if (
        host_role not in {"runner", "production"}
        or not IDENTIFIER_RE.fullmatch(str(scope_id or ""))
        or not SHA256_RE.fullmatch(str(scope_manifest_sha256 or ""))
    ):
        raise HostProcessPreflightError("scope identity is invalid")
    clock = now or datetime.now(timezone.utc)
    if not isinstance(clock, datetime) or clock.tzinfo is None:
        raise HostProcessPreflightError("clock must be timezone-aware")
    excluded = {os.getpid(), os.getppid()}
    host_rows = _process_rows(
        runner(["ps", "-axo", "pid=,command="]),
        source="host",
        excluded_pids=excluded,
    )
    container_listing = runner(["docker", "ps", "--format", "{{.ID}}\t{{.Names}}"])
    containers = []
    container_rows = []
    for line in container_listing.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{12,64}", parts[0]):
            raise HostProcessPreflightError("docker process listing is invalid")
        container_id, name = parts
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
            raise HostProcessPreflightError("docker container name is invalid")
        containers.append({"id": container_id, "name": name})
        container_rows.extend(
            _process_rows(
                runner(["docker", "top", container_id, "-eo", "pid,args"]),
                source=f"container:{name}",
                excluded_pids=excluded,
            )
        )
    matches = sorted(
        [*host_rows, *container_rows],
        key=lambda row: (row["source"], row["pid"], row["marker"]),
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": clock.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "host": socket.gethostname(),
        "host_role": host_role,
        "scope_id": scope_id,
        "scope_manifest_sha256": scope_manifest_sha256,
        "host_ps_available": True,
        "docker_ps_available": True,
        "containers": containers,
        "matching_processes": matches,
        "network_requests": 0,
        "database_writes": 0,
    }
    _atomic_write(output_file, _canonical_bytes(payload))
    if stat.S_IMODE(output_file.stat(follow_symlinks=False).st_mode) != 0o600:
        raise HostProcessPreflightError("output permissions drift")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-role", choices=("runner", "production"), required=True)
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--scope-manifest-sha256", required=True)
    parser.add_argument("--output-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = capture_host_process_preflight(**vars(args))
    except (HostProcessPreflightError, OSError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

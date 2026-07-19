#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


DB_KEYS = (
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_CONNECT_TIMEOUT",
    "POSTGRES_SSLMODE",
)
FIXED_VALUES = {
    "DB_ENGINE": "postgres",
    "DEBUG": "false",
    "SECRET_KEY": "fixed-race-live-rollback-validation-key",
    "POSTGRES_CONN_MAX_AGE": "0",
    "POSTGRES_APPLICATION_NAME": "race-live-rollback-one-shot",
    "CELERY_BROKER_URL": "memory://",
    "CELERY_RESULT_BACKEND": "cache+memory://",
    "EMAIL_BACKEND": "django.core.mail.backends.dummy.EmailBackend",
    "RACE_LIVE_RUNNER_MODE": "disabled",
    "RACE_LIVE_SCHEDULER_ENABLED": "false",
    "RACE_LIVE_MONITOR_ENABLED": "false",
}
KEY_RE = re.compile(r"[A-Z][A-Z0-9_]*\Z")


def _read_source(path: Path) -> dict[str, str]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise PermissionError("input must be a regular non-symlink file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PermissionError("input must be mode 0600 or stricter")
    if metadata.st_size <= 0 or metadata.st_size > 1024 * 1024:
        raise ValueError("input size is invalid")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("input contains an invalid assignment")
        key, value = line.split("=", 1)
        if KEY_RE.fullmatch(key) is None or key in values:
            raise ValueError("input contains an invalid or duplicate key")
        values[key] = value
    for key in DB_KEYS:
        value = values.get(key)
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or any(marker in value for marker in ("$", "`", "\x00", "\r", "\n"))
        ):
            raise ValueError("required database value is missing or unsafe")
    return values


def _atomic_write(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError("output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sha256-output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output)
    digest_output = Path(args.sha256_output)
    try:
        values = _read_source(Path(args.input))
        lines = [f"{key}={values[key]}" for key in DB_KEYS]
        lines.extend(f"{key}={value}" for key, value in FIXED_VALUES.items())
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        if output == digest_output:
            raise ValueError("output paths must differ")
        _atomic_write(output, payload)
        try:
            _atomic_write(
                digest_output,
                f"{digest}  {output.name}\n".encode("ascii"),
            )
        except Exception:
            output.unlink(missing_ok=True)
            raise
    except Exception as exc:
        output.unlink(missing_ok=True)
        digest_output.unlink(missing_ok=True)
        print(f"rollback env generation failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"filtered_env_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

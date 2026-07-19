#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
DB_KEYS = {
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_CONNECT_TIMEOUT",
    "POSTGRES_SSLMODE",
}
REQUIRED_FIXED = {
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
ALLOWED_ENV_KEYS = DB_KEYS | set(REQUIRED_FIXED)
FORBIDDEN_KEYS = {
    "RACE_LIVE_TRA_SECRET_ENV_FILE",
    "RACE_LIVE_ALERT_NOTIFY_EMAILS",
    "AUTOMATION_WARNING_NOTIFY_EMAILS",
    "TRANSLATION_FAILURE_NOTIFY_EMAILS",
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
}


def validate_immutable_image_id(value: str) -> str:
    if not isinstance(value, str) or IMAGE_ID_RE.fullmatch(value) is None:
        raise ValueError("reviewed release image must be a full local image ID")
    return value


def validate_pre_django_environment(values: dict[str, str]) -> None:
    if not isinstance(values, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in values.items()
    ):
        raise TypeError("environment must be a string mapping")
    for key in values:
        if (
            key.startswith("THE_RACING_API_")
            or key in FORBIDDEN_KEYS
            or key.startswith("SMTP_")
        ):
            raise PermissionError("source, SMTP, and notification settings are forbidden")
    if not DB_KEYS.issubset(values):
        raise ValueError("required database settings are missing")
    for key in DB_KEYS:
        value = values[key]
        if (
            not value
            or value != value.strip()
            or any(marker in value for marker in ("$", "`", "\x00", "\r", "\n"))
        ):
            raise ValueError("database setting is unsafe")
    if set(values) != ALLOWED_ENV_KEYS:
        raise PermissionError("filtered environment keys are not exact")
    for key, expected in REQUIRED_FIXED.items():
        if values.get(key) != expected:
            raise PermissionError(f"{key} is not fail-closed")


def validate_rollback_manifest_identity(
    *,
    manifest: dict,
    actual_image_id: str,
    expected_filtered_env_sha256: str,
    expected_manifest_sha256: str,
) -> None:
    if not isinstance(manifest, dict):
        raise TypeError("manifest must be an object")
    image_id = validate_immutable_image_id(actual_image_id)
    for digest in (
        expected_filtered_env_sha256,
        expected_manifest_sha256,
    ):
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            raise ValueError("expected digest is invalid")
    if (
        manifest.get("reviewed_release_image_id") != image_id
        or manifest.get("filtered_env_sha256")
        != expected_filtered_env_sha256
    ):
        raise PermissionError("rollback manifest identity drifted")


def _read_secure_file(
    path: Path,
    *,
    label: str,
    maximum_bytes: int,
) -> bytes:
    if not path.is_absolute():
        raise ValueError(f"{label} path must be absolute")
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
        metadata.st_mode
    ):
        raise PermissionError(f"{label} must be a regular non-symlink file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise PermissionError(f"{label} must be mode 0600")
    if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
        raise ValueError(f"{label} size is invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (metadata.st_dev, metadata.st_ino)
        ):
            raise PermissionError(f"{label} identity changed")
        chunks = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > maximum_bytes:
            raise ValueError(f"{label} size is invalid")
        return payload
    finally:
        os.close(descriptor)


def _parse_env(payload: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in payload.decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("invalid environment assignment")
        key, value = line.split("=", 1)
        if (
            re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is None
            or key in values
        ):
            raise ValueError("duplicate environment key")
        values[key] = value
    return values


def _strict_json(payload: bytes) -> dict:
    def strict_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate manifest key")
            value[key] = item
        return value

    parsed = json.loads(
        payload,
        object_pairs_hook=strict_object,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"invalid JSON constant: {value}")
        ),
    )
    if not isinstance(parsed, dict):
        raise TypeError("manifest must be an object")
    return parsed


def main(
    argv: list[str] | None = None,
    *,
    environ: dict[str, str] | None = None,
    django_setup=None,
    command_runner=None,
) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--actual-image-id", required=True)
    parser.add_argument("--expected-filtered-env-sha256", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument(
        "--command",
        choices=(
            "validate",
            "restore-result",
            "restore-policies-coarse",
            "restore-policy-event",
        ),
        required=True,
    )
    args = parser.parse_args(argv)
    env_path = Path(args.env_file)
    env_bytes = _read_secure_file(
        env_path,
        label="filtered environment",
        maximum_bytes=64 * 1024,
    )
    env_values = _parse_env(env_bytes)
    validate_pre_django_environment(env_values)
    actual_env_digest = hashlib.sha256(env_bytes).hexdigest()
    if actual_env_digest != args.expected_filtered_env_sha256:
        raise PermissionError("filtered environment digest drifted")
    manifest_path = Path(args.manifest)
    manifest_bytes = _read_secure_file(
        manifest_path,
        label="rollback manifest",
        maximum_bytes=1024 * 1024,
    )
    actual_manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_manifest_digest != args.expected_manifest_sha256:
        raise PermissionError("rollback manifest digest drifted")
    manifest = _strict_json(manifest_bytes)
    validate_rollback_manifest_identity(
        manifest=manifest,
        actual_image_id=args.actual_image_id,
        expected_filtered_env_sha256=args.expected_filtered_env_sha256,
        expected_manifest_sha256=args.expected_manifest_sha256,
    )

    runtime_environ = os.environ if environ is None else environ
    runtime_environ.clear()
    runtime_environ.update(env_values)
    runtime_environ["DJANGO_SETTINGS_MODULE"] = "app.settings"
    server_dir = Path(__file__).resolve().parents[1] / "server"
    if not server_dir.is_dir():
        raise RuntimeError("/app/server workdir is unavailable")
    original_cwd = Path.cwd()
    inserted_path = str(server_dir)
    sys.path.insert(0, inserted_path)
    try:
        os.chdir(server_dir)
        if django_setup is None or command_runner is None:
            import django
            from django.core.management import call_command

            django_setup = django.setup
            command_runner = call_command
        django_setup()
        commands = {
            "validate": "validate_race_live_rollback_target",
            "restore-result": "restore_race_live_provisional_result",
            "restore-policies-coarse": (
                "restore_race_live_provisional_policies"
            ),
            "restore-policy-event": (
                "restore_race_live_provisional_policies"
            ),
        }
        kwargs = {
            "manifest": str(manifest_path),
            "expected_manifest_sha256": (
                args.expected_manifest_sha256
            ),
        }
        if args.command == "restore-policies-coarse":
            kwargs["phase"] = "coarse"
        elif args.command == "restore-policy-event":
            kwargs["phase"] = "event"
        command_runner(commands[args.command], **kwargs)
    finally:
        os.chdir(original_cwd)
        try:
            sys.path.remove(inserted_path)
        except ValueError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

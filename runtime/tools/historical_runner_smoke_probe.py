#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from pathlib import Path


def _bounded_seconds(value: str) -> float:
    seconds = float(value)
    if seconds < 0 or seconds > 300:
        raise argparse.ArgumentTypeError("sleep seconds must be between 0 and 300")
    return seconds


def _label(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        raise argparse.ArgumentTypeError("label is invalid")
    return value


def _output_path(artifact_root: Path, raw_output: str) -> Path:
    output = Path(raw_output)
    if output.is_symlink():
        raise ValueError("output cannot be a symlink")
    resolved = output.parent.resolve() / output.name
    try:
        resolved.relative_to(artifact_root)
    except ValueError as exc:
        raise ValueError("output must be inside artifact root") from exc
    return resolved


def _write_atomic(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded, read-only historical runner smoke step.")
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sleep-seconds", type=_bounded_seconds, default=0.0)
    parser.add_argument("--label", type=_label, default="historical-runner-smoke")
    args = parser.parse_args()

    artifact_root = Path(args.artifact_root).resolve(strict=True)
    if not artifact_root.is_dir():
        parser.error("artifact root must be a directory")
    try:
        output = _output_path(artifact_root, args.output)
    except ValueError as exc:
        parser.error(str(exc))

    time.sleep(args.sleep_seconds)
    payload = {"label": args.label, "status": "ok"}
    _write_atomic(output, payload)
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

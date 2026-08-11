from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_event_lifecycle_enforce import (
    MAX_ARTIFACT_BYTES,
    RegistryError,
    load_registry_manifest_bytes,
    promote_registry,
)


def _read(options) -> bytes:
    path, use_stdin = options.get("manifest_file"), options.get("manifest_stdin")
    if bool(path) == bool(use_stdin):
        raise RegistryError("--manifest-file 与 --manifest-stdin 必须且只能提供一个")
    raw = sys.stdin.buffer.read(MAX_ARTIFACT_BYTES + 1) if use_stdin else Path(path).read_bytes()
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise RegistryError("registry artifact 超限")
    return raw


class Command(BaseCommand):
    help = "校验并 promotion lifecycle enforce registry（默认 dry-run）"

    def add_arguments(self, parser):
        parser.add_argument("--manifest-file")
        parser.add_argument("--manifest-stdin", action="store_true")
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--expected-commit", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            manifest = load_registry_manifest_bytes(
                _read(options),
                expected_raw_sha256=options["manifest_sha256"],
                expected_commit=options["expected_commit"],
                require_apply_fresh=options["apply"],
            )
            result = promote_registry(manifest, apply=options["apply"])
            self.stdout.write(
                f"outcome={result.outcome} batch_members={len(result.event_ids)} "
                f"total={result.total} remaining={result.remaining}"
            )
        except (RegistryError, OSError) as exc:
            raise CommandError(str(exc)) from exc

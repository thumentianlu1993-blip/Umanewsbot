from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_event_lifecycle_enforce import (
    RegistryError,
    build_registry_renewal_artifact,
)


class Command(BaseCommand):
    help = "只读生成当前 lifecycle registry 的原范围续期 artifact"

    def add_arguments(self, parser):
        parser.add_argument("--expected-root-sha256", required=True)
        parser.add_argument("--approved-commit", required=True)
        parser.add_argument("--runtime-valid-until", required=True)
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            raw = build_registry_renewal_artifact(
                expected_root_sha256=options["expected_root_sha256"],
                approved_commit=options["approved_commit"],
                runtime_valid_until=datetime.fromisoformat(options["runtime_valid_until"]),
            )
            with Path(options["output"]).open("xb") as output:
                output.write(raw)
            self.stdout.write(f"status=renewal_prepared raw_sha256={hashlib.sha256(raw).hexdigest()}")
        except (RegistryError, ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc

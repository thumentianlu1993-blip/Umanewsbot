from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from stable.models import RaceEventLifecycleEnforceRegistry
from stable.services.race_event_lifecycle_enforce import (
    RegistryError,
    activate_registry,
    load_registry_manifest_bytes,
    verify_registry_state,
)
from stable.management.commands.promote_race_event_lifecycle_enforce_registry import _read


class Command(BaseCommand):
    help = "验证或原子激活 lifecycle enforce registry"

    def add_arguments(self, parser):
        parser.add_argument("--manifest-file")
        parser.add_argument("--manifest-stdin", action="store_true")
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--expected-commit", required=True)
        parser.add_argument("--expected-state", choices=("inactive", "active"), required=True)
        parser.add_argument("--activate", action="store_true")
        parser.add_argument("--activation-id", default="")

    def handle(self, *args, **options):
        try:
            manifest = load_registry_manifest_bytes(
                _read(options),
                expected_raw_sha256=options["manifest_sha256"],
                expected_commit=options["expected_commit"],
                require_apply_fresh=options["activate"],
            )
            if options["activate"]:
                if options["expected_state"] != "inactive":
                    raise RegistryError("--activate 必须绑定 --expected-state inactive")
                result = activate_registry(
                    manifest,
                    apply=True,
                    expected_activation_id=options["activation_id"],
                )
                self.stdout.write(
                    f"outcome={result.outcome} activation_id={result.activation_id}"
                )
                return
            result = verify_registry_state(
                manifest,
                expected_state=options["expected_state"],
                expected_activation_id=options["activation_id"],
            )
            self.stdout.write(
                f"outcome={result.outcome} members={len(result.event_ids)} "
                f"activation_id={result.activation_id}"
            )
        except (RegistryError, OSError, RaceEventLifecycleEnforceRegistry.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc

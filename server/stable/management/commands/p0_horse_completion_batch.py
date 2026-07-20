"""Rolling P0 horse completion batch selection and approval command.

Stages implemented here are offline and read-only with respect to profile
data: ``--select`` writes a pending batch manifest, ``--approve`` records
human approval, and ``--validate`` performs the fail-closed binding check
required before any network prepare.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from stable.services.p0_horse_completion_batch import (
    P0HorseBatchError,
    approve_batch_manifest,
    default_batch_state_dir,
    select_p0_horse_batch,
    validate_approved_batch_manifest,
    write_batch_manifest,
)


class Command(BaseCommand):
    help = "Select, approve, and validate rolling P0 horse completion batches"

    def add_arguments(self, parser):
        stages = parser.add_mutually_exclusive_group(required=True)
        stages.add_argument("--select", action="store_true")
        stages.add_argument("--approve", metavar="MANIFEST_PATH")
        stages.add_argument("--validate", metavar="MANIFEST_PATH")
        parser.add_argument("--regions", default="")
        parser.add_argument("--profile-id", action="append", type=int, default=[])
        parser.add_argument("--limit-per-region", type=int, default=None)
        parser.add_argument("--include-complete", action="store_true")
        parser.add_argument("--allow-in-flight", action="store_true")
        parser.add_argument("--operator", default="")
        parser.add_argument("--reviewer", default="")
        parser.add_argument("--note", default="")
        parser.add_argument("--exclude-profile-id", action="append", type=int, default=[])
        parser.add_argument("--expected-sha256", default=None)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        try:
            if options["select"]:
                result = self._select(options)
            elif options["approve"]:
                result = self._approve(options)
            else:
                result = self._validate(options)
        except P0HorseBatchError as exc:
            raise CommandError(str(exc)) from exc
        if options["json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    def _select(self, options) -> dict:
        regions = [
            value.strip()
            for value in str(options["regions"] or "").split(",")
            if value.strip()
        ]
        manifest = select_p0_horse_batch(
            regions=regions or None,
            profile_ids=options["profile_id"] or None,
            limit_per_region=options["limit_per_region"],
            include_complete=options["include_complete"],
            allow_in_flight=options["allow_in_flight"],
            operator=options["operator"],
            state_dir=default_batch_state_dir(),
        )
        manifest_path = write_batch_manifest(
            manifest,
            state_dir=default_batch_state_dir(),
        )
        result = {
            "stage": "select",
            "manifest_path": str(manifest_path),
            "batch_id": manifest["batch_id"],
            "batch_sha256": manifest["batch_sha256"],
            "status": manifest["status"],
            "region_counts": manifest["region_counts"],
            "horse_count": len(manifest["horses"]),
        }
        self.stdout.write(
            f"batch {manifest['batch_id']} selected: "
            f"{result['horse_count']} horses, manifest at {manifest_path}"
        )
        return result

    def _approve(self, options) -> dict:
        manifest = approve_batch_manifest(
            options["approve"],
            reviewer=options["reviewer"],
            note=options["note"],
            excluded_profile_ids=options["exclude_profile_id"],
        )
        result = {
            "stage": "approve",
            "batch_id": manifest["batch_id"],
            "batch_sha256": manifest["batch_sha256"],
            "status": manifest["status"],
            "region_counts": manifest["region_counts"],
            "horse_count": len(manifest["horses"]),
            "excluded_profile_ids": manifest["approval"]["excluded_profile_ids"],
        }
        self.stdout.write(
            f"batch {manifest['batch_id']} approved by "
            f"{manifest['approval']['reviewer']}: {result['horse_count']} horses"
        )
        return result

    def _validate(self, options) -> dict:
        manifest = validate_approved_batch_manifest(
            options["validate"],
            expected_sha256=options["expected_sha256"],
        )
        result = {
            "stage": "validate",
            "batch_id": manifest["batch_id"],
            "batch_sha256": manifest["batch_sha256"],
            "status": manifest["status"],
            "horse_count": len(manifest["horses"]),
        }
        self.stdout.write(
            f"batch {manifest['batch_id']} approval binding valid: "
            f"{result['horse_count']} horses"
        )
        return result

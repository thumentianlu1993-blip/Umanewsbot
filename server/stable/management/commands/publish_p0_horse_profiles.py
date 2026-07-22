"""Stock first-publish command for P0 horse profiles.

Stages: --dry-run (artifact only), --approve (record human approval),
--commit (chunked per region, requires approved SHA + active superuser
reviewer). Publishes profiles passing the BASIC gate via the audited
transition channel. No stage performs network requests.
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from stable.services.horse_profile_publish import (
    P0HorsePublishError,
    approve_publish_manifest,
    build_publish_dry_run_artifact,
    commit_approved_publish_manifest,
    write_publish_manifest,
)


class Command(BaseCommand):
    help = "Publish stock P0 horse profiles that pass the BASIC gate"

    def add_arguments(self, parser):
        stages = parser.add_mutually_exclusive_group(required=True)
        stages.add_argument("--dry-run", action="store_true")
        stages.add_argument("--approve", metavar="MANIFEST_PATH")
        stages.add_argument("--commit", metavar="MANIFEST_PATH")
        parser.add_argument("--regions", default="")
        parser.add_argument("--profile-id", action="append", type=int, default=[])
        parser.add_argument("--output-dir", default="")
        parser.add_argument("--reviewer", default="")
        parser.add_argument("--reviewer-id", type=int, default=None)
        parser.add_argument("--approved-sha256", default=None)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        try:
            if options["dry_run"]:
                result = self._dry_run(options)
            elif options["approve"]:
                result = self._approve(options)
            else:
                result = self._commit(options)
        except P0HorsePublishError as exc:
            raise CommandError(str(exc)) from exc
        if options["json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    def _regions(self, options) -> list[str]:
        regions = [
            value.strip()
            for value in str(options["regions"] or "").split(",")
            if value.strip()
        ]
        if not regions:
            raise CommandError("--regions is required")
        return regions

    def _dry_run(self, options) -> dict:
        if not options["output_dir"]:
            raise CommandError("--dry-run requires --output-dir")
        artifact = build_publish_dry_run_artifact(
            regions=self._regions(options),
            profile_ids=options["profile_id"] or None,
        )
        manifest_path = write_publish_manifest(
            artifact,
            output_dir=options["output_dir"],
        )
        result = {
            "stage": "dry-run",
            "manifest_path": str(manifest_path),
            "stats": artifact["stats"],
        }
        self.stdout.write(
            f"publish dry-run: {artifact['stats']['candidates']} candidates, "
            f"{artifact['stats']['blocked']} blocked, manifest at {manifest_path}"
        )
        return result

    def _approve(self, options) -> dict:
        manifest = approve_publish_manifest(
            options["approve"],
            reviewer=options["reviewer"],
        )
        result = {
            "stage": "approve",
            "status": manifest["status"],
            "approved_sha256": manifest["approved_sha256"],
        }
        self.stdout.write(
            f"publish manifest approved: {manifest['approved_sha256']}"
        )
        return result

    def _commit(self, options) -> dict:
        if not options["approved_sha256"]:
            raise CommandError("--commit requires --approved-sha256")
        if not options["reviewer_id"]:
            raise CommandError("--commit requires --reviewer-id")
        reviewer = get_user_model().objects.filter(pk=options["reviewer_id"]).first()
        if reviewer is None or not (reviewer.is_active and reviewer.is_superuser):
            raise CommandError(
                "--reviewer-id must reference an active superuser"
            )
        report = commit_approved_publish_manifest(
            options["commit"],
            approved_sha256=options["approved_sha256"],
            reviewer=reviewer,
        )
        report["stage"] = "commit"
        self.stdout.write(f"publish commit: {report['regions']}")
        error_count = sum(
            len(region_report["errors"])
            for region_report in report["regions"].values()
        )
        if error_count:
            if options["json"]:
                self.stdout.write(
                    json.dumps(report, ensure_ascii=False, indent=2, default=str)
                )
                options["json"] = False
            raise CommandError(
                f"stock publish completed with {error_count} per-profile errors"
            )
        return report

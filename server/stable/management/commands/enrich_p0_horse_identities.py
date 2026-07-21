"""Offline P0 horse identity enrichment command.

Stages: --dry-run (artifact only), --approve (record human approval),
--commit (chunked, requires approved SHA), --aggregate (read-only conflict
grouping), --suggest-resolutions (resolution artifact only),
--commit-resolutions (requires approved SHA + reviewer user). No stage
performs network requests.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from stable.services.p0_horse_identity_enrichment import (
    P0HorseIdentityEnrichmentError,
    aggregate_identity_conflicts,
    approve_enrichment_manifest,
    build_dry_run_artifact,
    build_resolution_suggestions,
    commit_approved_artifact,
    commit_resolution_suggestions,
    write_aggregation_artifact,
    write_dry_run_artifact,
    write_resolution_artifact,
)


class Command(BaseCommand):
    help = "Enrich P0 horse profiles with offline external identity evidence"

    def add_arguments(self, parser):
        stages = parser.add_mutually_exclusive_group(required=True)
        stages.add_argument("--dry-run", action="store_true")
        stages.add_argument("--approve", metavar="MANIFEST_PATH")
        stages.add_argument("--commit", metavar="MANIFEST_PATH")
        stages.add_argument("--aggregate", action="store_true")
        stages.add_argument("--suggest-resolutions", action="store_true")
        stages.add_argument("--commit-resolutions", metavar="MANIFEST_PATH")
        parser.add_argument("--regions", default="")
        parser.add_argument("--profile-id", action="append", type=int, default=[])
        parser.add_argument("--output-dir", default="")
        parser.add_argument("--cache-evidence", default="", help="JSONL from reparse tool")
        parser.add_argument("--nar-probe", default="", help="NAR coverage probe summary JSON")
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
            elif options["commit"]:
                result = self._commit(options)
            elif options["aggregate"]:
                result = self._aggregate(options)
            elif options["suggest_resolutions"]:
                result = self._suggest_resolutions(options)
            else:
                result = self._commit_resolutions(options)
        except P0HorseIdentityEnrichmentError as exc:
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

    def _load_jsonl(self, path_text: str) -> list[dict]:
        if not path_text:
            return []
        path = Path(path_text)
        if not path.is_file():
            raise CommandError(f"cache evidence file not found: {path}")
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _load_json(self, path_text: str) -> dict | None:
        if not path_text:
            return None
        path = Path(path_text)
        if not path.is_file():
            raise CommandError(f"probe file not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _dry_run(self, options) -> dict:
        if not options["output_dir"]:
            raise CommandError("--dry-run requires --output-dir")
        artifact = build_dry_run_artifact(
            regions=self._regions(options),
            profile_ids=options["profile_id"] or None,
            cache_evidence=self._load_jsonl(options["cache_evidence"]),
            nar_probe=self._load_json(options["nar_probe"]),
        )
        manifest_path = write_dry_run_artifact(
            artifact,
            output_dir=options["output_dir"],
        )
        result = {
            "stage": "dry-run",
            "manifest_path": str(manifest_path),
            "stats": artifact["stats"],
        }
        self.stdout.write(
            f"identity enrichment dry-run: {artifact['stats']['candidates']} candidates, "
            f"{artifact['stats']['conflicts']} conflicts, manifest at {manifest_path}"
        )
        return result

    def _approve(self, options) -> dict:
        manifest = approve_enrichment_manifest(
            options["approve"],
            reviewer=options["reviewer"],
        )
        result = {
            "stage": "approve",
            "status": manifest["status"],
            "approved_sha256": manifest["approved_sha256"],
        }
        self.stdout.write(
            f"identity enrichment manifest approved: {manifest['approved_sha256']}"
        )
        return result

    def _commit(self, options) -> dict:
        if not options["approved_sha256"]:
            raise CommandError("--commit requires --approved-sha256")
        report = commit_approved_artifact(
            options["commit"],
            approved_sha256=options["approved_sha256"],
        )
        report["stage"] = "commit"
        self.stdout.write(f"identity enrichment commit: {report['regions']}")
        return report

    def _aggregate(self, options) -> dict:
        report = aggregate_identity_conflicts()
        result = {
            "stage": "aggregate",
            "total_pending": report["total_pending"],
            "group_count": report["group_count"],
            "groups": report["groups"][:50],
        }
        if options["output_dir"]:
            manifest_path = write_aggregation_artifact(
                report,
                output_dir=options["output_dir"],
            )
            result["manifest_path"] = str(manifest_path)
            self.stdout.write(f"conflict aggregation manifest at {manifest_path}")
        self.stdout.write(
            f"identity conflicts: {report['total_pending']} pending, "
            f"{report['group_count']} groups"
        )
        return result

    def _suggest_resolutions(self, options) -> dict:
        if not options["output_dir"]:
            raise CommandError("--suggest-resolutions requires --output-dir")
        artifact = build_resolution_suggestions()
        manifest_path = write_resolution_artifact(
            artifact,
            output_dir=options["output_dir"],
        )
        result = {
            "stage": "suggest-resolutions",
            "manifest_path": str(manifest_path),
            "stats": artifact["stats"],
        }
        self.stdout.write(
            f"resolution suggestions: {artifact['stats']['suggestions']} suggestions, "
            f"{artifact['stats']['skipped']} skipped, manifest at {manifest_path}"
        )
        return result

    def _commit_resolutions(self, options) -> dict:
        if not options["approved_sha256"]:
            raise CommandError("--commit-resolutions requires --approved-sha256")
        if not options["reviewer_id"]:
            raise CommandError("--commit-resolutions requires --reviewer-id")
        reviewer = get_user_model().objects.filter(pk=options["reviewer_id"]).first()
        if reviewer is None:
            raise CommandError(f"reviewer user not found: {options['reviewer_id']}")
        report = commit_resolution_suggestions(
            options["commit_resolutions"],
            approved_sha256=options["approved_sha256"],
            resolved_by=reviewer,
        )
        report["stage"] = "commit-resolutions"
        self.stdout.write(
            f"resolution commit: {report['resolved']} resolved, "
            f"{report['skipped_not_pending']} not pending, "
            f"{len(report['failed_validation'])} failed validation"
        )
        return report

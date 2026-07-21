"""Rolling P0 horse completion batch selection and approval command.

Stages implemented here are offline and read-only with respect to profile
data: ``--select`` writes a pending batch manifest, ``--approve`` records
human approval, and ``--validate`` performs the fail-closed binding check
required before any network prepare.
"""

from __future__ import annotations

import json
from pathlib import Path

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
        stages.add_argument("--prepare", metavar="MANIFEST_PATH")
        stages.add_argument("--bundle", metavar="MANIFEST_PATH")
        stages.add_argument("--commit", metavar="MANIFEST_PATH")
        stages.add_argument("--abandon", metavar="MANIFEST_PATH")
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
        parser.add_argument("--region", default="")
        parser.add_argument("--reviewer-id", type=int, default=None)
        parser.add_argument("--approved-by", default="")
        parser.add_argument("--racing-career-status", default="active")
        parser.add_argument("--allow-network", action="store_true")
        parser.add_argument("--confirm-reviewed-artifact", action="store_true")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        try:
            if options["select"]:
                result = self._select(options)
            elif options["approve"]:
                result = self._approve(options)
            elif options["validate"]:
                result = self._validate(options)
            elif options["prepare"]:
                result = self._prepare(options)
            elif options["bundle"]:
                result = self._bundle(options)
            elif options["commit"]:
                result = self._commit(options)
            else:
                result = self._abandon(options)
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

    def _prepare(self, options) -> dict:
        from django.conf import settings

        from stable.services.p0_horse_completion_batch import load_batch_manifest
        from stable.services.p0_horse_completion_prepare import prepare_p0_horse_batch
        from stable.services.p0_horse_completion_review import (
            build_batch_review_workbook,
        )

        allow_network = bool(options["allow_network"]) and bool(
            getattr(settings, "HORSE_PROFILE_COMPLETION_ALLOW_NETWORK", False)
        )
        if options["allow_network"] and not allow_network:
            raise CommandError(
                "network prepare requires HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true"
            )
        summary = prepare_p0_horse_batch(
            options["prepare"],
            expected_sha256=options["expected_sha256"],
            allow_network=allow_network,
        )
        manifest = load_batch_manifest(options["prepare"])
        review_output_dir = getattr(
            settings,
            "HORSE_PROFILE_COMPLETION_REVIEW_OUTPUT_DIR",
            "runtime/horse_profile_completion/review",
        )
        workbook_path = build_batch_review_workbook(
            manifest=manifest,
            artifact_dir=Path(options["prepare"]).parent / "artifact",
            output_path=Path(review_output_dir) / f"{manifest['batch_id']}.xlsx",
        )
        summary["stage"] = "prepare"
        summary["review_workbook"] = str(workbook_path)
        summary["allow_network"] = allow_network
        self.stdout.write(
            f"batch {manifest['batch_id']} prepared: "
            f"{summary['totals']['succeeded']}/{summary['totals']['horses']} horses, "
            f"review workbook at {workbook_path}"
        )
        return summary

    def _bundle(self, options) -> dict:
        from django.contrib.auth import get_user_model

        from stable.services.p0_horse_completion_batch import BatchRunState
        from stable.services.p0_horse_completion_research import (
            build_region_approval_bundle,
            build_region_research_v3,
            write_region_research,
        )

        region = str(options["region"] or "").strip()
        if not region:
            raise CommandError("--bundle requires --region")
        reviewer_id = options["reviewer_id"]
        if reviewer_id is None:
            raise CommandError("--bundle requires --reviewer-id")
        reviewer = get_user_model().objects.filter(pk=reviewer_id).first()
        if reviewer is None or not reviewer.is_active or not reviewer.is_superuser:
            raise CommandError("reviewer must be an active superuser")
        batch_dir = Path(options["bundle"]).parent
        research = build_region_research_v3(
            batch_dir / "artifact",
            region=region,
        )
        research_path, _ = write_region_research(
            research,
            output_dir=batch_dir / "approval",
            region=region,
        )
        bundle = build_region_approval_bundle(
            research_path=research_path,
            region=region,
            reviewer=reviewer,
            output_dir=batch_dir / "approval",
            batch_dir=batch_dir,
            racing_career_status=options["racing_career_status"],
        )
        state = BatchRunState.read(batch_dir)
        state.artifacts[f"bundle:{region}"] = {
            "research_path": str(bundle["research_path"]),
            "research_sha256": bundle["research_sha256"],
            "mapping_path": str(bundle["mapping_path"]),
            "mapping_sha256": bundle["mapping_sha256"],
            "authority_path": str(bundle["authority_path"]),
            "authority_sha256": bundle["authority_sha256"],
        }
        stage_name = f"review:{region}"
        if stage_name not in state.completed_stages:
            state.completed_stages.append(stage_name)
        state.write()
        result = {
            "stage": "bundle",
            "region": region,
            "research_sha256": bundle["research_sha256"],
            "mapping_sha256": bundle["mapping_sha256"],
            "authority_sha256": bundle["authority_sha256"],
            "horse_count": bundle["horse_count"],
        }
        self.stdout.write(
            f"batch region {region} modules approved: {bundle['horse_count']} horses"
        )
        return result

    def _commit(self, options) -> dict:
        from django.contrib.auth import get_user_model

        from stable.services.p0_horse_completion_commit import (
            commit_p0_horse_batch_region,
        )

        region = str(options["region"] or "").strip()
        if not region:
            raise CommandError("--commit requires --region")
        reviewer_id = options["reviewer_id"]
        if reviewer_id is None:
            raise CommandError("--commit requires --reviewer-id")
        reviewer = get_user_model().objects.filter(pk=reviewer_id).first()
        if reviewer is None or not reviewer.is_active or not reviewer.is_superuser:
            raise CommandError("reviewer must be an active superuser")
        approved_by = str(options["approved_by"] or "").strip()
        if not approved_by:
            raise CommandError("--commit requires --approved-by")
        result = commit_p0_horse_batch_region(
            options["commit"],
            region=region,
            reviewer=reviewer,
            approved_by=approved_by,
            state_dir=default_batch_state_dir(),
            confirm_reviewed_artifact=options["confirm_reviewed_artifact"],
        )
        result["stage"] = "commit"
        self.stdout.write(
            f"batch region {region} committed; idempotent verification "
            f"passed={result['idempotent_verification']['passed']}"
        )
        return result

    def _abandon(self, options) -> dict:
        from stable.services.p0_horse_completion_batch import (
            BatchRunState,
            abandon_batch_run,
            load_batch_manifest,
            mark_batch_manifest_status,
        )

        manifest_path = Path(options["abandon"])
        state_file = manifest_path.parent / "state.json"
        if state_file.exists():
            state = BatchRunState.read(manifest_path.parent)
        else:
            manifest = load_batch_manifest(manifest_path)
            state = BatchRunState.create(
                batch_id=manifest["batch_id"],
                run_dir=manifest_path.parent,
            )
        abandon_batch_run(state, reason=options["note"])
        manifest = mark_batch_manifest_status(manifest_path, status="abandoned")
        result = {
            "stage": "abandon",
            "batch_id": manifest["batch_id"],
            "status": manifest["status"],
        }
        self.stdout.write(f"batch {manifest['batch_id']} abandoned")
        return result

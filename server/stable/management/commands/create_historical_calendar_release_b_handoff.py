from __future__ import annotations

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_calendar_release_b_handoff import (
    authorize_handoff_action,
    build_preflight_artifact,
    collect_handoff_preflight,
    collect_initial_install_preflight,
    find_completed_restricted_recovery_marker,
    publish_preflight_artifact,
    restricted_marker_origin_action,
    verify_restricted_marker_for_live_state,
)


class Command(BaseCommand):
    help = "生成受保护的 Release B 迁移前 handoff artifact。"

    def add_arguments(self, parser):
        parser.add_argument("--output-path", required=True)
        parser.add_argument("--candidate-commit", required=True)
        parser.add_argument("--candidate-image-id", required=True)
        parser.add_argument("--compose-file", required=True)
        parser.add_argument("--deployment-lock-token-sha256", required=True)
        parser.add_argument("--expected-database-identity-sha256", default="")
        parser.add_argument(
            "--expected-migration-leaf-set", action="append", default=[]
        )
        parser.add_argument(
            "--action",
            choices=("deploy", "manual-release", "rollback", "forward-resume", "initial-install"),
            required=True,
        )
        parser.add_argument("--restricted-marker-path", required=True)
        parser.add_argument("--provenance-artifact-sha256", default="")
        parser.add_argument("--release-0077-recovery-manifest-path", default="")
        parser.add_argument("--release-0077-recovery-manifest-sha256", default="")
        parser.add_argument(
            "--release-0077-recovery-origin-handoff-sha256", default=""
        )

    def handle(self, *args, **options):
        marker_path = (
            Path(options["restricted_marker_path"])
            if options["restricted_marker_path"]
            else None
        )
        active_marker_present = bool(
            marker_path and os.path.lexists(marker_path)
        )
        transition_path = (
            marker_path.parent / "restricted-recovery.transition.json"
            if marker_path
            else None
        )
        transition_present = bool(
            transition_path and os.path.lexists(transition_path)
        )
        active_marker_present = active_marker_present or transition_present
        marker_source = None
        if marker_path and active_marker_present:
            marker_source = marker_path if os.path.lexists(marker_path) else transition_path
        initial_origin = options["action"] == "initial-install" or (
            options["action"] == "forward-resume"
            and marker_source is not None
            and restricted_marker_origin_action(path=marker_source) == "initial-install"
        )
        result = (
            collect_initial_install_preflight()
            if initial_origin
            else collect_handoff_preflight(
                repair_intent=options["action"] == "forward-resume"
            )
        )
        if initial_origin:
            result["recovery_origin_action"] = "initial-install"
        if not result["ok"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
            raise CommandError("Release B preflight failed")
        marker_ok = False
        verified_marker = None
        if options["action"] == "forward-resume":
            if not options["restricted_marker_path"] or not options["provenance_artifact_sha256"]:
                raise CommandError("forward-resume requires marker and provenance")
            expected_binding = {
                    "candidate_commit": options["candidate_commit"],
                    "candidate_image_id": options["candidate_image_id"],
                    "artifact_sha256": options["provenance_artifact_sha256"],
                    "database_identity_sha256": result[
                        "database_identity_sha256"
                    ],
                    "action": "forward-resume",
            }
            if marker_path and transition_path and os.path.lexists(marker_path) and os.path.lexists(transition_path):
                marker_ok = False
            elif active_marker_present:
                marker_result = verify_restricted_marker_for_live_state(
                    path=marker_path if os.path.lexists(marker_path) else transition_path,
                    expected_binding=expected_binding,
                    live_leaf_set=result["migration_leaf_set"],
                )
                marker_ok = marker_result["ok"]
                verified_marker = marker_result.get("marker")
            elif marker_path:
                completed = find_completed_restricted_recovery_marker(
                    path=marker_path, expected_binding=expected_binding
                )
                if completed is not None:
                    marker_result = verify_restricted_marker_for_live_state(
                        path=completed,
                        expected_binding=expected_binding,
                        live_leaf_set=result["migration_leaf_set"],
                    )
                    marker_ok = marker_result["ok"]
                    verified_marker = marker_result.get("marker")
        if initial_origin and verified_marker:
            result.update({
                "recovery_origin_catalog_sha256": verified_marker.get("initial_catalog_sha256"),
                "recovery_origin_rows_sha256": verified_marker.get("initial_rows_sha256"),
                "recovery_origin_data_state": verified_marker.get("initial_install_data_state"),
                "recovery_origin_legacy_counts": verified_marker.get("initial_legacy_counts"),
            })
        action_gate = authorize_handoff_action(
            leaf_set=result["migration_leaf_set"],
            action=options["action"],
            restricted_marker_ok=marker_ok,
            active_marker_present=active_marker_present,
        )
        if (
            not action_gate["ok"]
            or (
                options["expected_database_identity_sha256"]
                and result["database_identity_sha256"]
                != options["expected_database_identity_sha256"]
            )
            or (
                options["expected_migration_leaf_set"]
                and result["migration_leaf_set"]
                != sorted(options["expected_migration_leaf_set"])
            )
        ):
            raise CommandError("Release B preflight failed")
        path = Path(options["output_path"])
        try:
            artifact = build_preflight_artifact(
                preflight=result,
                candidate_commit=options["candidate_commit"],
                candidate_image_id=options["candidate_image_id"],
                compose_file=options["compose_file"],
                deployment_lock_token_sha256=options["deployment_lock_token_sha256"],
                artifact_path=str(path),
                handoff_action=options["action"],
                release_0077_recovery_manifest_path=options[
                    "release_0077_recovery_manifest_path"
                ],
                release_0077_recovery_manifest_sha256=options[
                    "release_0077_recovery_manifest_sha256"
                ],
                release_0077_recovery_origin_handoff_sha256=options[
                    "release_0077_recovery_origin_handoff_sha256"
                ],
            )
            publish_preflight_artifact(path=path, payload=artifact)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps({"artifact_path": str(path), "artifact_sha256": artifact["artifact_sha256"]}, sort_keys=True))

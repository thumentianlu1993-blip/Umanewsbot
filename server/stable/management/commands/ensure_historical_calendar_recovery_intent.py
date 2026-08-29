from __future__ import annotations

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_calendar_release_b_handoff import (
    FINAL_LEAF_SET,
    INITIAL_INSTALL_LEAF_SET,
    ORDINARY_RELEASE_LEAF_SETS,
    build_restricted_recovery_marker,
    collect_handoff_preflight,
    collect_initial_install_preflight,
    find_completed_restricted_recovery_marker,
    publish_restricted_recovery_marker,
    trusted_restricted_marker_identity,
    verify_preflight_artifact,
    verify_restricted_marker_for_live_state,
)
from stable.services.historical_calendar_release_b_schema import database_vendor_contract


INITIAL_LEAF_SET = ["stable.0070_horse_identity_evidence_commit_receipt"]


class Command(BaseCommand):
    help = "在任何 migration 前持久化或复验受信任的 migration-history recovery intent。"

    def add_arguments(self, parser):
        parser.add_argument("--marker-path", required=True)
        parser.add_argument("--artifact-path", required=True)
        parser.add_argument("--artifact-sha256", required=True)
        parser.add_argument("--candidate-commit", required=True)
        parser.add_argument("--candidate-image-id", required=True)
        parser.add_argument("--database-identity-sha256", required=True)
        parser.add_argument("--provenance-artifact-sha256", default="")
        parser.add_argument(
            "--attempt-mode", choices=("required", "not-required"), required=True
        )

    def handle(self, *args, **options):
        vendor = database_vendor_contract()
        if not vendor["ok"]:
            self.stdout.write(json.dumps({
                "ok": False,
                "database_vendor": vendor,
                "drift_paths": ["database.vendor"],
            }, ensure_ascii=False, sort_keys=True))
            raise CommandError("recovery intent requires PostgreSQL")
        artifact_path = Path(options["artifact_path"])
        artifact_trust = verify_preflight_artifact(
            path=artifact_path,
            expected_artifact_sha256=options["artifact_sha256"],
            expected_bindings={
                "candidate_commit": options["candidate_commit"],
                "candidate_image_id": options["candidate_image_id"],
                "database_identity_sha256": options[
                    "database_identity_sha256"
                ],
            },
        )
        if not artifact_trust["ok"]:
            raise CommandError("recovery intent artifact verification failed")
        artifact = artifact_trust["payload"]
        if artifact.get("recovery_intent_mode") != options["attempt_mode"]:
            raise CommandError("recovery intent attempt mode is not artifact-bound")
        action = artifact.get("handoff_action")
        if action not in {"deploy", "manual-release", "rollback", "forward-resume", "initial-install"}:
            raise CommandError("recovery intent handoff action is invalid")
        initial_origin = artifact.get("recovery_origin_action") == "initial-install"
        live = (
            collect_initial_install_preflight()
            if initial_origin
            else collect_handoff_preflight(
                repair_intent=options["attempt_mode"] == "required"
            )
        )
        if not live.get("ok"):
            self.stdout.write(json.dumps(live, ensure_ascii=False, sort_keys=True))
            raise CommandError("recovery intent live preflight failed")
        if (
            live.get("database_identity_sha256")
            != options["database_identity_sha256"]
        ):
            raise CommandError("recovery intent live preflight failed")

        marker_path = Path(options["marker_path"])
        marker_present = os.path.lexists(marker_path)
        transition_present = os.path.lexists(
            marker_path.parent / "restricted-recovery.transition.json"
        )
        binding = {
            "candidate_commit": options["candidate_commit"],
            "candidate_image_id": options["candidate_image_id"],
            "artifact_sha256": (
                options["provenance_artifact_sha256"]
                if action == "forward-resume"
                else options["artifact_sha256"]
            ),
            "database_identity_sha256": options[
                "database_identity_sha256"
            ],
            "action": "forward-resume",
        }
        if initial_origin:
            binding.update({
                "origin_action": "initial-install",
                "allowed_recovery_action": "forward-resume",
            })
            if action == "initial-install":
                binding.update({
                    "initial_catalog_sha256": artifact["recovery_origin_catalog_sha256"],
                    "initial_rows_sha256": artifact["recovery_origin_rows_sha256"],
                    "initial_install_data_state": artifact["recovery_origin_data_state"],
                    "initial_legacy_counts": artifact["recovery_origin_legacy_counts"],
                })

        if options["attempt_mode"] == "not-required":
            if action == "forward-resume" or marker_present or transition_present:
                raise CommandError("no-intent attempt has recovery marker state")
            artifact_preflight = artifact.get("preflight")
            artifact_leaf_set = (
                artifact_preflight.get("migration_leaf_set")
                if isinstance(artifact_preflight, dict)
                else None
            )
            if not isinstance(artifact_leaf_set, list) or not all(
                isinstance(item, str) and item for item in artifact_leaf_set
            ):
                raise CommandError(
                    "no-intent artifact is missing an exact starting leaf"
                )
            live_leaf_set = tuple(live["migration_leaf_set"])
            if live_leaf_set != tuple(artifact_leaf_set):
                raise CommandError("no-intent starting leaf drifted after handoff")
            if live_leaf_set not in ORDINARY_RELEASE_LEAF_SETS:
                raise CommandError(
                    "no-intent attempt requires an exact reviewed ordinary starting leaf"
                )
            self.stdout.write(
                json.dumps(
                    {
                        "ok": True,
                        "status": "not-required",
                        "starting_leaf_set": list(live_leaf_set),
                    },
                    sort_keys=True,
                )
            )
            return

        if action == "forward-resume":
            if not options["provenance_artifact_sha256"]:
                raise CommandError("forward resume requires active marker provenance")
            if not marker_present and not transition_present:
                completed = find_completed_restricted_recovery_marker(
                    path=marker_path, expected_binding=binding
                )
                if completed is not None and tuple(live["migration_leaf_set"]) == FINAL_LEAF_SET:
                    device, inode = trusted_restricted_marker_identity(
                        path=completed, expected_binding=binding
                    )
                    self.stdout.write(
                        json.dumps(
                            {
                                "ok": True,
                                "status": "completed",
                                "marker_device": device,
                                "marker_inode": inode,
                            },
                            sort_keys=True,
                        )
                    )
                    return
                raise CommandError("forward resume requires recovery marker state")
            if marker_present and transition_present:
                raise CommandError("active and transition marker conflict")
            verify_path = (
                marker_path
                if marker_present
                else marker_path.parent / "restricted-recovery.transition.json"
            )
            result = verify_restricted_marker_for_live_state(
                path=verify_path,
                expected_binding=binding,
                live_leaf_set=live["migration_leaf_set"],
            )
            if not result["ok"]:
                raise CommandError("active recovery intent verification failed")
            device, inode = trusted_restricted_marker_identity(
                path=verify_path, expected_binding=binding
            )
            self.stdout.write(
                json.dumps(
                    {
                        "ok": True,
                        "status": "verified",
                        "marker_device": device,
                        "marker_inode": inode,
                    },
                    sort_keys=True,
                )
            )
            return

        if marker_present or transition_present:
            raise CommandError("active recovery marker blocks ordinary release")
        leaf_set = live["migration_leaf_set"]
        required_initial_leaf = (
            list(INITIAL_INSTALL_LEAF_SET) if action == "initial-install" else INITIAL_LEAF_SET
        )
        if leaf_set != required_initial_leaf:
            raise CommandError("new recovery intent requires an exact reviewed initial state")
        marker = build_restricted_recovery_marker(
            binding={**binding, "initiating_action": action},
            leaf_set=required_initial_leaf,
        )
        try:
            publish_restricted_recovery_marker(path=marker_path, marker=marker)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        device, inode = trusted_restricted_marker_identity(
            path=marker_path, expected_binding=binding
        )
        self.stdout.write(
            json.dumps(
                {
                    "ok": True,
                    "status": "created",
                    "marker_device": device,
                    "marker_inode": inode,
                },
                sort_keys=True,
            )
        )

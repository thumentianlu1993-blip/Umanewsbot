from __future__ import annotations

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_calendar_release_b_handoff import (
    FINAL_LEAF_SET,
    complete_restricted_recovery_marker,
    collect_handoff_preflight,
    collect_initial_install_preflight,
    find_completed_restricted_recovery_marker,
    verify_preflight_artifact,
    verify_restricted_marker_for_live_state,
)
from stable.services.historical_calendar_release_b_schema import (
    collect_initial_install_completion_audit,
    database_vendor_contract,
)


class Command(BaseCommand):
    help = "migration 成功到当前受审最终叶节点后原子转换 restricted-recovery marker。"

    def add_arguments(self, parser):
        parser.add_argument("--marker-path", required=True)
        parser.add_argument("--provenance-artifact-sha256", required=True)
        parser.add_argument("--candidate-commit", required=True)
        parser.add_argument("--candidate-image-id", required=True)
        parser.add_argument("--database-identity-sha256", required=True)
        parser.add_argument("--artifact-path", required=True)
        parser.add_argument("--artifact-sha256", required=True)
        parser.add_argument(
            "--attempt-mode", choices=("required", "not-required"), required=True
        )
        parser.add_argument("--expected-marker-device", type=int)
        parser.add_argument("--expected-marker-inode", type=int)

    def handle(self, *args, **options):
        vendor = database_vendor_contract()
        if not vendor["ok"]:
            self.stdout.write(json.dumps({
                "ok": False,
                "database_vendor": vendor,
                "drift_paths": ["database.vendor"],
            }, ensure_ascii=False, sort_keys=True))
            raise CommandError("restricted recovery completion requires PostgreSQL")
        marker_path = Path(options["marker_path"])
        artifact = verify_preflight_artifact(
            path=Path(options["artifact_path"]),
            expected_artifact_sha256=options["artifact_sha256"],
            expected_bindings={
                "candidate_commit": options["candidate_commit"],
                "candidate_image_id": options["candidate_image_id"],
                "database_identity_sha256": options["database_identity_sha256"],
                "recovery_intent_mode": options["attempt_mode"],
            },
        )
        if not artifact["ok"]:
            raise CommandError("completion attempt mode is not artifact-bound")
        artifact_payload = artifact["payload"]
        origin_action = artifact_payload.get("recovery_origin_action")
        if origin_action not in {"initial-install", "migration-history-repair"}:
            raise CommandError("completion recovery origin is not artifact-bound")
        transition_path = marker_path.parent / "restricted-recovery.transition.json"
        marker_binding = {
            "artifact_sha256": options["provenance_artifact_sha256"],
            "candidate_commit": options["candidate_commit"],
            "candidate_image_id": options["candidate_image_id"],
            "database_identity_sha256": options["database_identity_sha256"],
            "action": "forward-resume",
        }
        if origin_action == "initial-install":
            marker_binding.update({
                "origin_action": "initial-install",
                "allowed_recovery_action": "forward-resume",
                "initial_catalog_sha256": artifact_payload.get(
                    "recovery_origin_catalog_sha256"
                ),
                "initial_rows_sha256": artifact_payload.get(
                    "recovery_origin_rows_sha256"
                ),
                "initial_install_data_state": artifact_payload.get(
                    "recovery_origin_data_state"
                ),
                "initial_legacy_counts": artifact_payload.get(
                    "recovery_origin_legacy_counts"
                ),
            })
        marker_payload = None
        if options["attempt_mode"] == "required":
            active = os.path.lexists(marker_path)
            transition = os.path.lexists(transition_path)
            if active and transition:
                raise CommandError("active and transition marker conflict")
            marker_source = marker_path if active else transition_path if transition else None
            if marker_source is None:
                marker_source = find_completed_restricted_recovery_marker(
                    path=marker_path, expected_binding=marker_binding
                )
            if marker_source is None:
                raise CommandError("required completion marker is missing")
            marker_result = verify_restricted_marker_for_live_state(
                path=marker_source,
                expected_binding=marker_binding,
                live_leaf_set=list(FINAL_LEAF_SET),
            )
            if not marker_result["ok"]:
                raise CommandError("completion artifact/marker binding mismatch")
            marker_payload = marker_result["marker"]
            marker_origin = marker_payload.get(
                "origin_action", "migration-history-repair"
            )
            if marker_origin != origin_action:
                raise CommandError("completion recovery origin mismatch")
        elif origin_action != "migration-history-repair":
            raise CommandError("initial-install completion requires durable intent")

        live = (
            collect_initial_install_preflight()
            if origin_action == "initial-install"
            else collect_handoff_preflight(
                repair_intent=options["attempt_mode"] == "required"
            )
        )
        if not live.get("ok"):
            self.stdout.write(json.dumps(live, ensure_ascii=False, sort_keys=True))
            raise CommandError("restricted recovery requires a valid live preflight")
        if live.get("migration_leaf_set") != list(FINAL_LEAF_SET) or live.get(
            "database_identity_sha256"
        ) != options[
            "database_identity_sha256"
        ]:
            raise CommandError(
                "restricted recovery has not reached the exact reviewed final state"
            )
        if origin_action == "initial-install":
            assert marker_payload is not None
            initial_audit = collect_initial_install_completion_audit(
                expected={
                    "data_state": marker_payload["initial_install_data_state"],
                    "legacy_counts": marker_payload["initial_legacy_counts"],
                }
            )
            if not initial_audit["ok"]:
                self.stdout.write(json.dumps(initial_audit, ensure_ascii=False, sort_keys=True))
                raise CommandError("initial-install completion audit failed")
        if options["attempt_mode"] == "not-required":
            if os.path.lexists(marker_path) or os.path.lexists(transition_path):
                raise CommandError("no-intent completion found recovery marker state")
            self.stdout.write(
                json.dumps({"ok": True, "status": "not-required"}, sort_keys=True)
            )
            return
        if options["expected_marker_device"] is None or options["expected_marker_inode"] is None:
            raise CommandError("required completion needs ensure marker identity")
        try:
            completed = complete_restricted_recovery_marker(
                path=marker_path,
                expected_binding={
                    **marker_binding,
                },
                expected_file_identity=(
                    options["expected_marker_device"],
                    options["expected_marker_inode"],
                ),
            )
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps({"ok": True, "completed_marker": str(completed)}, sort_keys=True))

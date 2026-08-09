from __future__ import annotations

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.historical_calendar_release_b_handoff import (
    FINAL_LEAF_SET,
    collect_handoff_preflight,
    collect_initial_install_preflight,
    find_completed_restricted_recovery_marker,
    restricted_marker_origin_action,
    verify_restricted_marker_for_live_state,
)


class Command(BaseCommand):
    help = "可信校验 restricted-recovery marker、candidate binding 与 live partial state。"

    def add_arguments(self, parser):
        parser.add_argument("--marker-path", required=True)
        parser.add_argument("--artifact-sha256", required=True)
        parser.add_argument("--candidate-commit", required=True)
        parser.add_argument("--candidate-image-id", required=True)

    def handle(self, *args, **options):
        marker_path = Path(options["marker_path"])
        transition_path = marker_path.parent / "restricted-recovery.transition.json"
        marker_source = marker_path if os.path.lexists(marker_path) else transition_path
        initial_origin = (
            os.path.lexists(marker_source)
            and restricted_marker_origin_action(path=marker_source) == "initial-install"
        )
        live = (
            collect_initial_install_preflight()
            if initial_origin
            else collect_handoff_preflight(repair_intent=True)
        )
        if not live.get("ok"):
            self.stdout.write(json.dumps(live, ensure_ascii=False, sort_keys=True))
            raise CommandError("restricted recovery requires a valid live preflight")
        expected_binding = {
                "artifact_sha256": options["artifact_sha256"],
                "candidate_commit": options["candidate_commit"],
                "candidate_image_id": options["candidate_image_id"],
                "database_identity_sha256": live[
                    "database_identity_sha256"
                ],
                "action": "forward-resume",
        }
        active_present = os.path.lexists(marker_path)
        transition_present = os.path.lexists(transition_path)
        if active_present and transition_present:
            result = {"ok": False, "errors": ["active_transition_conflict"]}
        elif active_present or transition_present:
            result = verify_restricted_marker_for_live_state(
                path=marker_path if active_present else transition_path,
                expected_binding=expected_binding,
                live_leaf_set=live["migration_leaf_set"],
            )
        else:
            completed = find_completed_restricted_recovery_marker(
                path=marker_path, expected_binding=expected_binding
            )
            result = {
                "ok": completed is not None
                and live["migration_leaf_set"] == list(FINAL_LEAF_SET),
                "errors": [] if completed is not None else ["marker_missing"],
                "completed_marker": str(completed) if completed else None,
            }
        result["completion_required"] = (
            live["migration_leaf_set"] == list(FINAL_LEAF_SET)
        )
        result["live_ok"] = live["ok"]
        result["ok"] = result["ok"] and live["ok"]
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not result["ok"]:
            raise CommandError("restricted recovery marker verification failed")

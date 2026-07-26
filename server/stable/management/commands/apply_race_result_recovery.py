from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services.race_result_recovery_projection import (
    CanonicalIdentityApprovalError,
    RecoveryApplyBlocked,
    approve_canonical_link,
    apply_recovery_event,
)


def _read_bound_json(path_value: str, expected_sha256: str, label: str):
    path = Path(path_value)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise CommandError(f"{label} unreadable: {exc}") from exc
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_sha256:
        raise CommandError(f"{label} sha256 mismatch")
    try:
        return json.loads(content)
    except ValueError as exc:
        raise CommandError(f"{label} is not valid JSON") from exc


class Command(BaseCommand):
    help = "Apply SHA-bound official race-result recovery events (database only)."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--approval", required=True)
        parser.add_argument("--approval-sha256", required=True)
        parser.add_argument("--route-registry", required=True)
        parser.add_argument("--route-registry-sha256", required=True)
        parser.add_argument("--ledger-root", required=True)
        parser.add_argument("--applied-by-id", required=True, type=int)
        parser.add_argument("--confirm-apply", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm_apply"]:
            raise CommandError("--confirm-apply is required")
        manifest = _read_bound_json(
            options["manifest"],
            options["manifest_sha256"],
            "manifest",
        )
        approval = _read_bound_json(
            options["approval"],
            options["approval_sha256"],
            "approval",
        )
        route_registry = _read_bound_json(
            options["route_registry"],
            options["route_registry_sha256"],
            "route registry",
        )
        if approval.get("manifest_sha256") != options["manifest_sha256"]:
            raise CommandError("approval does not bind the manifest sha256")
        events = manifest.get("events", [])
        canonical_links = manifest.get("canonical_links", [])
        if not isinstance(events, list) or not isinstance(canonical_links, list):
            raise CommandError("manifest event/link scopes must be lists")
        if not events and not canonical_links:
            raise CommandError("manifest has no approved work")
        event_ids = [item.get("event_id") for item in events]
        if (
            any(not isinstance(event_id, int) for event_id in event_ids)
            or len(event_ids) != len(set(event_ids))
        ):
            raise CommandError("manifest event IDs must be unique integers")
        approved_ids = approval.get("event_ids")
        if approved_ids != event_ids:
            raise CommandError("approval event scope does not exactly match manifest")
        if approval.get("canonical_links", []) != canonical_links:
            raise CommandError(
                "approval canonical scope does not exactly match manifest"
            )
        if events and (
            manifest.get("route_registry_sha256")
            != options["route_registry_sha256"]
        ):
            raise CommandError(
                "manifest does not bind the current route registry sha256"
            )

        canonical_results = []
        for item in canonical_links:
            try:
                link = approve_canonical_link(
                    duplicate_event_id=item["duplicate_event_id"],
                    canonical_event_id=item["canonical_event_id"],
                    identity_sha256=item["identity_sha256"],
                    manifest_sha256=options["manifest_sha256"],
                    approved_by_id=options["applied_by_id"],
                    approved_at=timezone.now(),
                )
            except (CanonicalIdentityApprovalError, KeyError) as exc:
                reason = getattr(exc, "reason_code", "canonical_manifest_invalid")
                raise CommandError(f"canonical link blocked: {reason}") from exc
            canonical_results.append(
                {
                    "link_id": link.pk,
                    "duplicate_event_id": link.duplicate_event_id,
                    "canonical_event_id": link.canonical_event_id,
                }
            )
        results = []
        for item in events:
            try:
                results.append(
                    apply_recovery_event(
                        event_id=item["event_id"],
                        validated_receipt=item["validated_receipt"],
                        manifest_sha256=options["manifest_sha256"],
                        approval_sha256=options["approval_sha256"],
                        expected_owner=item["expected_owner"],
                        expected_generation=item["expected_generation"],
                        expected_before_identity=item["before_identity"],
                        route_registry=route_registry,
                        ledger_root=Path(options["ledger_root"]),
                        applied_by_id=options["applied_by_id"],
                        now=timezone.now(),
                    )
                )
            except RecoveryApplyBlocked as exc:
                raise CommandError(
                    f"event {item['event_id']} blocked: {exc.reason_code}"
                ) from exc
        self.stdout.write(
            json.dumps(
                {
                    "status": "applied",
                    "manifest_sha256": options["manifest_sha256"],
                    "approval_sha256": options["approval_sha256"],
                    "events": results,
                    "canonical_links": canonical_results,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

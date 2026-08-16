from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.models import (
    RaceEvent,
    RaceEventLifecycleControl,
    RaceEventLifecycleEnforceRegistry,
)
from stable.services.race_event_lifecycle_enforce import (
    RegistryError,
    build_registry_artifact,
    build_registry_selector_scope,
    canonical_artifact_bytes,
    select_registry_candidates,
    scope_sha256,
)


class Command(BaseCommand):
    help = "只读生成 lifecycle full-cohort registry artifact"

    def add_arguments(self, parser):
        parser.add_argument("--scope-kind", required=True)
        parser.add_argument("--cutoff", required=True)
        parser.add_argument("--window-end")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--explicit-event-id", action="append", type=int, default=[])
        parser.add_argument("--approved-commit", required=True)
        parser.add_argument("--generation", required=True, type=int)
        parser.add_argument("--predecessor-root-sha256", default="")
        parser.add_argument("--output", required=True)
        parser.add_argument("--census-output")
        parser.add_argument("--enrollment-plan-output")
        parser.add_argument(
            "--allowed-us-zone",
            action="append",
            default=[],
            metavar="EVENT_ID=America/Zone",
        )

    def handle(self, *args, **options):
        try:
            output = Path(options["output"])
            census_output = Path(
                options.get("census_output") or f"{output}.census.json"
            )
            enrollment_plan_output = Path(
                options.get("enrollment_plan_output")
                or f"{output}.enrollment-plan.json"
            )
            existing_outputs = [
                path
                for path in (output, census_output, enrollment_plan_output)
                if path.exists()
            ]
            if existing_outputs:
                raise RegistryError(
                    "输出 artifact 已存在，拒绝覆盖: "
                    + ", ".join(str(path) for path in existing_outputs)
                )
            cutoff = datetime.fromisoformat(options["cutoff"])
            if timezone.is_naive(cutoff):
                raise RegistryError("cutoff 必须为 aware")
            generated_at = timezone.now()
            if cutoff > generated_at:
                raise RegistryError("cutoff 不得晚于实际生成时刻（future cutoff）")
            window_end = (
                datetime.fromisoformat(options["window_end"])
                if options.get("window_end") else None
            )
            kind = options["scope_kind"]
            if window_end is None and kind == "datetime_7d_canary":
                window_end = cutoff + timedelta(days=7)
            if window_end is None and kind == "datetime_30d":
                window_end = cutoff + timedelta(days=30)
            predecessor_ids: list[int] = []
            predecessor_root = options["predecessor_root_sha256"]
            if predecessor_root:
                predecessor = RaceEventLifecycleEnforceRegistry.objects.filter(
                    root_sha256=predecessor_root
                ).first()
                if predecessor is None:
                    raise RegistryError("predecessor registry 不存在")
                predecessor_ids = list(
                    predecessor.memberships.order_by("event_id").values_list("event_id", flat=True)
                )
            scope = build_registry_selector_scope(
                kind=kind,
                cutoff=cutoff,
                window_end=window_end,
                explicit_event_ids=options["explicit_event_id"],
                limit=options["limit"],
                predecessor_carry_forward=True,
            )
            census = select_registry_candidates(
                scope=scope, predecessor_event_ids=predecessor_ids
            )
            required_ids = list(census.enrollment_required_event_ids)
            required_events = {
                event.id: event
                for event in RaceEvent.objects.filter(id__in=required_ids)
            }
            us_required_ids = {
                event_id
                for event_id, event in required_events.items()
                if event.country_region == "united_states"
            }
            zones_by_event: dict[int, set[str]] = {}
            for value in options["allowed_us_zone"]:
                if not isinstance(value, str) or "=" not in value:
                    raise RegistryError(
                        "--allowed-us-zone 格式必须为 EVENT_ID=America/Zone"
                    )
                event_text, zone = value.split("=", 1)
                try:
                    event_id = int(event_text)
                except ValueError as exc:
                    raise RegistryError("US allowlist event ID 非法") from exc
                if event_id not in us_required_ids:
                    raise RegistryError(
                        f"US allowlist event {event_id} 不属于 census 中待 enrollment 的美国赛事"
                    )
                if not zone.startswith("America/"):
                    raise RegistryError("US allowlist zone 必须为 America/*")
                zones_by_event.setdefault(event_id, set()).add(zone)
            blocked_us_ids = sorted(
                event_id
                for event_id in us_required_ids
                if required_events[event_id].timezone_name
                not in zones_by_event.get(event_id, set())
            )
            blocked_us_set = set(blocked_us_ids)
            ready_ids = [
                event_id for event_id in required_ids
                if event_id not in blocked_us_set
            ]
            census_payload = {
                "schema_version": 1,
                "approved_commit": options["approved_commit"],
                "generation": options["generation"],
                "predecessor_root_sha256": predecessor_root,
                "selector_scope": scope,
                "scope_sha256": scope_sha256(scope),
                "inspected": census.inspected,
                "included": census.included,
                "blocked_by_reason": census.blocked_by_reason,
                "blocked_by_scope": census.blocked_by_scope,
                "reason_counts": census.reason_counts,
                "included_event_ids": list(census.included_event_ids),
                "enrollment_required_event_ids": list(
                    census.enrollment_required_event_ids
                ),
                "ready_enrollment_event_ids": ready_ids,
                "blocked_pending_us_allowlist_event_ids": blocked_us_ids,
                "successor_pending_event_ids": list(
                    census.successor_pending_event_ids
                ),
            }
            census_output.write_bytes(canonical_artifact_bytes(census_payload))
            batches = []
            enrollment_output_root = f"{output}.enrollment-batches"
            for offset in range(0, len(ready_ids), 20):
                event_ids = ready_ids[offset : offset + 20]
                batch_number = len(batches) + 1
                allowed_us_zone = sorted(
                    f"{event_id}={zone}"
                    for event_id in event_ids
                    for zone in zones_by_event.get(event_id, set())
                )
                batches.append(
                    {
                        "batch_number": batch_number,
                        "event_ids": event_ids,
                        "prepare_command": {
                            "command": "prepare_race_event_lifecycle_enrollment",
                            "event_ids": [str(event_id) for event_id in event_ids],
                            "approved_commit": options["approved_commit"],
                            "output_dir": (
                                f"{enrollment_output_root}/batch-{batch_number:04d}"
                            ),
                            "allowed_us_zone": allowed_us_zone,
                        },
                    }
                )
            plan_payload = {
                "schema_version": 1,
                "scope_sha256": scope_sha256(scope),
                "approved_commit": options["approved_commit"],
                "batch_size": 20,
                "required_count": len(required_ids),
                "ready_count": len(ready_ids),
                "blocked_pending_us_allowlist_event_ids": blocked_us_ids,
                "batches": batches,
            }
            enrollment_plan_output.write_bytes(
                canonical_artifact_bytes(plan_payload)
            )
            controls = {
                row.event_id: row.enrollment_manifest_sha256
                for row in RaceEventLifecycleControl.objects.filter(
                    event_id__in=census.included_event_ids
                )
            }
            if set(controls) != set(census.included_event_ids):
                status = (
                    "blocked_pending_us_allowlist"
                    if blocked_us_ids else "enrollment_required"
                )
                self.stdout.write(
                    f"status={status} inspected={census.inspected} "
                    f"included={census.included} required={len(required_ids)} "
                    f"ready={len(ready_ids)} blocked_us={len(blocked_us_ids)} "
                    f"batches={len(batches)} census={census_output} "
                    f"plan={enrollment_plan_output}"
                )
                return
            raw = build_registry_artifact(
                event_ids=census.included_event_ids,
                enrollment_sha_by_event=controls,
                approved_commit=options["approved_commit"],
                generation=options["generation"],
                predecessor_root_sha256=predecessor_root,
                selector_scope=scope,
                now=generated_at,
            )
            output.write_bytes(raw)
            self.stdout.write(
                f"status=registry_prepared members={census.included} "
                f"inspected={census.inspected} remaining=0 "
                f"raw_sha256={hashlib.sha256(raw).hexdigest()} "
                f"census={census_output} plan={enrollment_plan_output}"
            )
        except (RegistryError, ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc

from __future__ import annotations

from datetime import datetime, timedelta
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable import models
from stable.services.race_data_sync_enrollment import (
    build_race_data_enrollment_census,
    load_standing_policy_file,
    parse_standing_policy,
)
from stable.services.race_data_sync_pipeline import (
    RaceDataSyncCapacityLimits,
    RaceDataSyncFlags,
    build_race_data_provider_roster,
    inspect_race_data_artifact_capacity,
    resolve_race_data_provider_route,
)


def _aware(value: str | None) -> datetime:
    if not value:
        return timezone.now()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CommandError("--cutoff 必须是 ISO-8601 时间") from exc
    if timezone.is_naive(parsed):
        raise CommandError("--cutoff 必须包含时区")
    return parsed


class Command(BaseCommand):
    help = "只读审计赛事时间、出马表、赛果和生命周期自动同步"

    def add_arguments(self, parser):
        parser.add_argument("--cutoff")
        parser.add_argument("--horizon-days", type=int)
        parser.add_argument("--standing-policy-file")
        parser.add_argument("--standing-policy-sha256")

    def handle(self, **options):
        cutoff = _aware(options.get("cutoff"))
        horizon_days = options.get("horizon_days") or int(
            settings.RACE_DATA_SYNC_FUTURE_HORIZON_DAYS
        )
        if not 1 <= horizon_days <= 366:
            raise CommandError("--horizon-days 必须在 1-366 之间")
        end_date = (cutoff + timedelta(days=horizon_days)).date()
        flags = RaceDataSyncFlags.from_settings()
        try:
            capacity_limits = RaceDataSyncCapacityLimits.from_settings()
            artifact_bytes, free_disk_bytes = inspect_race_data_artifact_capacity(
                artifact_roots=tuple(
                    str(value)
                    for value in getattr(
                        settings, "RACE_DATA_RAW_ARTIFACT_ROOTS", ()
                    )
                    if str(value)
                )
            )
            capacity_status = {
                "status": (
                    "valid"
                    if artifact_bytes < capacity_limits.artifact_high_water_bytes
                    and free_disk_bytes >= capacity_limits.min_free_disk_bytes
                    else "invalid"
                ),
                "artifact_root_bytes": artifact_bytes,
                "free_disk_bytes": free_disk_bytes,
            }
            if capacity_status["status"] == "invalid":
                capacity_status["reason"] = "artifact_capacity_threshold"
        except (OSError, TypeError, ValueError) as exc:
            capacity_status = {
                "status": "invalid",
                "reason": str(exc),
            }
        capacity_status["usage_date"] = cutoff.date().isoformat()
        capacity_status["daily_ledgers"] = list(
            models.RaceDataTransportCapacityLedger.objects.filter(
                usage_date=cutoff.date()
            )
            .order_by("provider", "region_code")
            .values(
                "provider",
                "region_code",
                "request_count",
                "budgeted_response_bytes",
            )
        )
        roster = build_race_data_provider_roster(configuration_only=True)
        configured_entries = [
            {
                "provider": entry.provider,
                "regions": list(entry.regions),
                "source_class": entry.source_class,
                "adapter_status": entry.adapter_status,
                "transport_enabled": entry.transport_enabled,
                "apply_enabled": entry.apply_enabled,
                "enabled_data_kinds": list(entry.enabled_data_kinds),
                "route_admitted": bool(
                    entry.adapter_status == "implemented"
                    and entry.automation_allowed
                    and entry.proof_digest
                    and entry.allowed_hosts
                    and entry.allowed_path_prefixes
                    and entry.request_budget > 0
                ),
            }
            for entry in roster.entries
        ]
        policy_path = options.get("standing_policy_file") or str(
            settings.RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE
        )
        policy_sha = options.get("standing_policy_sha256") or str(
            settings.RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256
        )
        policy_report: dict = {"status": "not_configured"}
        if policy_path or policy_sha:
            try:
                policy = load_standing_policy_file(
                    path=policy_path,
                    expected_sha256=policy_sha,
                )
                parsed_policy = parse_standing_policy(policy)
                route_drift = []
                for policy_route in parsed_policy.routes:
                    binding = resolve_race_data_provider_route(
                        provider=policy_route.provider,
                        region=policy_route.region_code,
                        identity_namespace=policy_route.identity_namespace,
                        data_kinds=policy_route.data_kinds,
                        configuration_only=True,
                    )
                    if (
                        binding is None
                        or binding.route_digest != policy_route.route_digest
                    ):
                        route_drift.append(
                            {
                                "provider": policy_route.provider,
                                "region": policy_route.region_code,
                                "identity_namespace": (
                                    policy_route.identity_namespace
                                ),
                            }
                        )
                census = build_race_data_enrollment_census(
                    standing_policy=policy,
                    cutoff=cutoff,
                    horizon_days=horizon_days,
                )
                blockers: dict[str, int] = {}
                for entry in census.entries:
                    if entry.reason_code:
                        blockers[entry.reason_code] = (
                            blockers.get(entry.reason_code, 0) + 1
                        )
                policy_report = {
                    "status": "loaded",
                    "census_sha256": census.census_sha256,
                    "classification_counts": census.classification_counts,
                    "blocker_counts": blockers,
                    "route_drift": route_drift,
                }
            except (OSError, TypeError, ValueError) as exc:
                policy_report = {
                    "status": "invalid",
                    "reason": exc.__class__.__name__,
                }

        upcoming = models.RaceEvent.objects.filter(
            visibility_status=models.RaceEventVisibility.PUBLISHED,
            local_date__gte=cutoff.date(),
            local_date__lte=end_date,
        )
        due_checkpoints = models.RaceEventLiveProviderCheckpoint.objects.filter(
            next_poll_at__lte=cutoff,
            tracking__tracking_enabled=True,
            tracking__event__race_data_sync_enrollment__state=(
                models.RaceDataSyncEnrollmentState.ENROLLED
            ),
        )
        report = {
            "schema_version": 1,
            "cutoff": cutoff.isoformat(),
            "horizon_days": horizon_days,
            "would_write": False,
            "runtime": {
                "enabled": flags.enabled,
                "scheduler_enabled": flags.scheduler_enabled,
                "allow_network": flags.allow_network,
                "schedule_apply_enabled": flags.schedule_apply_enabled,
                "racecard_apply_enabled": flags.racecard_apply_enabled,
                "result_apply_enabled": flags.result_apply_enabled,
                "result_public_enabled": flags.result_public_enabled,
                "correction_apply_enabled": flags.correction_apply_enabled,
                "lifecycle_apply_enabled": bool(
                    settings.RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED
                ),
                "future_discovery_enabled": bool(
                    settings.RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED
                ),
                "providers": sorted(flags.providers),
                "regions": sorted(flags.regions),
                "data_kinds": sorted(flags.data_kinds),
            },
            "roster": {
                "registry_digest": roster.registry_digest,
                "entries": configured_entries,
            },
            "capacity": capacity_status,
            "inventory": {
                "upcoming_published_events": upcoming.count(),
                "upcoming_missing_race_datetime": upcoming.filter(
                    race_datetime__isnull=True
                ).count(),
                "upcoming_without_any_source_identity": upcoming.filter(
                    source_identities__isnull=True
                ).count(),
                "enrolled_events": models.RaceDataSyncEnrollment.objects.filter(
                    state=models.RaceDataSyncEnrollmentState.ENROLLED
                ).count(),
                "due_checkpoints": due_checkpoints.count(),
            },
            "standing_policy": policy_report,
        }
        report["configuration_status"] = (
            "ready"
            if all(
                (
                    bool(flags.providers),
                    bool(flags.regions),
                    bool(flags.fields),
                    bool(flags.data_kinds),
                    any(entry["route_admitted"] for entry in configured_entries),
                    capacity_status["status"] == "valid",
                    policy_report.get("status") == "loaded",
                    not policy_report.get("route_drift"),
                )
            )
            else "blocked"
        )
        self.stdout.write(
            json.dumps(
                report,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

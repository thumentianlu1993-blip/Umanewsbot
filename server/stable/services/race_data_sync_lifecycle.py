from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from stable import models
from stable.services.race_event_lifecycle_enforce import (
    apply_registry_lifecycle_decision,
    validate_registry_membership_snapshot,
    validate_runtime_registry_settings,
)


@dataclass(frozen=True)
class DataSyncLifecycleDecision:
    to_status: str = ""
    reason_code: str = ""
    next_refresh_at: datetime | None = None


def decide_data_sync_lifecycle(
    *, event: models.RaceEvent, now: datetime
) -> DataSyncLifecycleDecision:
    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    if event.status in {
        models.RaceEventStatus.CANCELLED,
        models.RaceEventStatus.FINISHED,
    }:
        return DataSyncLifecycleDecision(reason_code="terminal")
    if event.status == models.RaceEventStatus.POSTPONED:
        return DataSyncLifecycleDecision(
            reason_code="postponed_awaiting_schedule",
            next_refresh_at=now + timedelta(hours=12),
        )
    if event.race_datetime is None:
        return DataSyncLifecycleDecision(
            reason_code="race_datetime_missing",
            next_refresh_at=now + timedelta(hours=12),
        )
    if timezone.is_naive(event.race_datetime):
        raise ValueError("race_datetime must be timezone-aware")
    finish_at = event.race_datetime + timedelta(minutes=30)
    if now >= finish_at:
        return DataSyncLifecycleDecision(
            to_status=models.RaceEventStatus.FINISHED,
            reason_code="data_sync_time_t_plus_30",
        )
    if now >= event.race_datetime and event.status == models.RaceEventStatus.SCHEDULED:
        return DataSyncLifecycleDecision(
            to_status=models.RaceEventStatus.RUNNING,
            reason_code="data_sync_time_reached_post",
            next_refresh_at=finish_at,
        )
    next_refresh = (
        event.race_datetime
        if event.status == models.RaceEventStatus.SCHEDULED
        else finish_at
    )
    return DataSyncLifecycleDecision(
        reason_code="not_due",
        next_refresh_at=next_refresh,
    )


def advance_due_data_sync_lifecycle(
    *, now: datetime, batch_size: int = 100, dry_run: bool = False
) -> dict[str, int]:
    """Advance only events authorized by the active lifecycle registry.

    Data-sync supplies cohort selection; the lifecycle registry coordinator is
    the sole writer of lifecycle state and transition evidence.
    """

    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    if isinstance(batch_size, bool) or not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    stats = {
        "selected": 0,
        "transitioned": 0,
        "replayed": 0,
        "not_due": 0,
        "error": 0,
    }
    if not getattr(settings, "RACE_EVENT_LIFECYCLE_ENABLED", False) or getattr(
        settings, "RACE_EVENT_LIFECYCLE_MODE", "off"
    ) != "enforce":
        stats["error"] = 1
        return stats
    registry_valid, registry_or_reason = validate_runtime_registry_settings()
    if not registry_valid:
        stats["error"] = 1
        return stats
    registry = registry_or_reason
    assert isinstance(registry, models.RaceEventLifecycleEnforceRegistry)
    if now >= registry.runtime_valid_until:
        stats["error"] = 1
        return stats

    control_ids = tuple(
        models.RaceEventLifecycleControl.objects.filter(
            Q(next_refresh_at__isnull=True) | Q(next_refresh_at__lte=now),
            mode=models.RaceEventLifecycleMode.ENFORCE,
            event__projection_control__write_owner=(
                models.RaceEventProjectionWriteOwner.DATA_SYNC
            ),
            event__race_data_sync_enrollment__state=(
                models.RaceDataSyncEnrollmentState.ENROLLED
            ),
            event__lifecycle_enforce_memberships__registry=registry,
            event__lifecycle_enforce_memberships__state="active",
        )
        .exclude(
            event__status__in=(
                models.RaceEventStatus.FINISHED,
                models.RaceEventStatus.CANCELLED,
            )
        )
        .order_by("next_refresh_at", "event_id")
        .values_list("id", flat=True)[:batch_size]
    )
    stats["selected"] = len(control_ids)

    for control_id in control_ids:
        control = (
            models.RaceEventLifecycleControl.objects.select_related("event")
            .filter(pk=control_id)
            .first()
        )
        if control is None:
            stats["replayed"] += 1
            continue
        membership = (
            models.RaceEventLifecycleEnforceMembership.objects.select_related(
                "registry"
            )
            .filter(registry=registry, event_id=control.event_id, state="active")
            .first()
        )
        validation = validate_registry_membership_snapshot(
            membership=membership,
            event=control.event,
            control=control,
            now=now,
        )
        if not validation.valid:
            stats["error"] += 1
            continue
        try:
            decision = decide_data_sync_lifecycle(event=control.event, now=now)
        except ValueError:
            stats["error"] += 1
            continue
        if dry_run:
            stats["transitioned" if decision.to_status else "not_due"] += 1
            continue
        # The generic lifecycle engine has a date-only next-midnight rule. The
        # data-sync contract deliberately does not: a missing exact race time is
        # refreshed later and must never be inferred as a completed race.
        if not decision.to_status:
            with transaction.atomic():
                locked_control = (
                    models.RaceEventLifecycleControl.objects.select_for_update()
                    .select_related("event")
                    .filter(pk=control_id)
                    .first()
                )
                if locked_control is None:
                    stats["replayed"] += 1
                    continue
                locked_membership = (
                    models.RaceEventLifecycleEnforceMembership.objects.select_related(
                        "registry"
                    )
                    .filter(
                        registry=registry,
                        event_id=locked_control.event_id,
                        state="active",
                    )
                    .first()
                )
                locked_validation = validate_registry_membership_snapshot(
                    membership=locked_membership,
                    event=locked_control.event,
                    control=locked_control,
                    now=now,
                )
                if not locked_validation.valid:
                    stats["error"] += 1
                    continue
                try:
                    locked_decision = decide_data_sync_lifecycle(
                        event=locked_control.event,
                        now=now,
                    )
                except ValueError:
                    stats["error"] += 1
                    continue
                if locked_decision.to_status:
                    # The schedule changed between the read and row lock. Leave
                    # the due time intact so the next selector pass re-enters
                    # the registry-authorized transition path.
                    stats["replayed"] += 1
                    continue
                locked_control.last_attempt_at = now
                locked_control.last_success_at = now
                locked_control.last_result_code = locked_decision.reason_code
                locked_control.last_error = ""
                locked_control.consecutive_failures = 0
                locked_control.next_refresh_at = locked_decision.next_refresh_at
                locked_control.claim_token = ""
                locked_control.claim_expires_at = None
                locked_control.save(
                    update_fields=(
                        "last_attempt_at",
                        "last_success_at",
                        "last_result_code",
                        "last_error",
                        "consecutive_failures",
                        "next_refresh_at",
                        "claim_token",
                        "claim_expires_at",
                        "updated_at",
                    )
                )
                stats["not_due"] += 1
            continue

        with transaction.atomic():
            result = apply_registry_lifecycle_decision(
                event_id=control.event_id,
                expected_generation=control.schedule_generation,
                now=now,
                expected_registry_root_sha256=registry.root_sha256,
                expected_registry_activation_id=registry.activation_id,
                expected_registry_membership_sha256=registry.membership_sha256,
                expected_registry_member_count=registry.member_count,
                expected_runtime_enabled=True,
                expected_runtime_mode="enforce",
            )
            if result.action == "applied":
                event_status = (
                    models.RaceEvent.objects.filter(pk=control.event_id)
                    .values_list("status", flat=True)
                    .first()
                )
                if event_status == models.RaceEventStatus.FINISHED:
                    models.RaceEventLiveTracking.objects.filter(
                        event_id=control.event_id
                    ).update(
                        state=models.RaceEventLiveState.AWAITING_RESULT,
                        updated_at=now,
                    )
                stats["transitioned"] += 1
            elif result.action == "error":
                stats["error"] += 1
            elif result.reason_code in {
                "already_finished",
                "applied_duplicate",
                "generation_stale",
            }:
                stats["replayed"] += 1
            elif result.reason_code in {
                "before_race_datetime",
                "before_local_midnight",
                "postponed_awaiting_new_time",
                "terminal_cancelled",
            }:
                stats["not_due"] += 1
            else:
                stats["error"] += 1
    return stats

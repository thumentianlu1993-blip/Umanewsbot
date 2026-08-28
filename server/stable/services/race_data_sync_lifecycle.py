from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from stable import models
from stable.services.race_event_public_cache import invalidate_public_race_cache


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
    query = models.RaceEventLifecycleControl.objects.filter(
        mode=models.RaceEventLifecycleMode.ENFORCE,
        event__projection_control__write_owner=(
            models.RaceEventProjectionWriteOwner.DATA_SYNC
        ),
        event__race_data_sync_enrollment__state=(
            models.RaceDataSyncEnrollmentState.ENROLLED
        ),
    ).filter(next_refresh_at__isnull=True) | models.RaceEventLifecycleControl.objects.filter(
        mode=models.RaceEventLifecycleMode.ENFORCE,
        next_refresh_at__lte=now,
        event__projection_control__write_owner=(
            models.RaceEventProjectionWriteOwner.DATA_SYNC
        ),
        event__race_data_sync_enrollment__state=(
            models.RaceDataSyncEnrollmentState.ENROLLED
        ),
    )
    control_ids = tuple(
        query.order_by("next_refresh_at", "event_id").values_list("id", flat=True)[
            :batch_size
        ]
    )
    stats["selected"] = len(control_ids)
    for control_id in control_ids:
        if dry_run:
            control = models.RaceEventLifecycleControl.objects.select_related(
                "event"
            ).get(pk=control_id)
            try:
                decision = decide_data_sync_lifecycle(event=control.event, now=now)
            except ValueError:
                stats["error"] += 1
                continue
            stats["transitioned" if decision.to_status else "not_due"] += 1
            continue

        with transaction.atomic():
            control = (
                models.RaceEventLifecycleControl.objects.select_for_update()
                .select_related("event")
                .filter(
                    pk=control_id,
                    mode=models.RaceEventLifecycleMode.ENFORCE,
                    event__projection_control__write_owner=(
                        models.RaceEventProjectionWriteOwner.DATA_SYNC
                    ),
                    event__race_data_sync_enrollment__state=(
                        models.RaceDataSyncEnrollmentState.ENROLLED
                    ),
                )
                .first()
            )
            if control is None:
                stats["replayed"] += 1
                continue
            event = models.RaceEvent.objects.select_for_update().get(
                pk=control.event_id
            )
            try:
                decision = decide_data_sync_lifecycle(event=event, now=now)
            except ValueError as exc:
                control.last_attempt_at = now
                control.last_result_code = "invalid_schedule"
                control.last_error = str(exc)
                control.consecutive_failures += 1
                control.next_refresh_at = now + timedelta(hours=12)
                control.save()
                stats["error"] += 1
                continue
            if decision.to_status:
                dedupe_key = (
                    f"data-sync-time:{event.pk}:{control.schedule_generation}:"
                    f"{decision.reason_code}:{decision.to_status}"
                )
                transition, created = models.RaceEventLifecycleTransition.objects.get_or_create(
                    dedupe_key=dedupe_key,
                    defaults={
                        "event": event,
                        "from_status": event.status,
                        "to_status": decision.to_status,
                        "reason_code": decision.reason_code,
                        "effective_at": now,
                        "source_authority": "data_sync_time_rule",
                        "source_key": "race_sync_v2",
                        "trigger_task": "advance_race_data_sync_lifecycle_task",
                        "schedule_generation": control.schedule_generation,
                        "record_kind": models.RaceEventLifecycleTransitionKind.APPLIED,
                    },
                )
                if created:
                    event.status = decision.to_status
                    event.save(update_fields=("status", "updated_at"))
                    if decision.to_status == models.RaceEventStatus.FINISHED:
                        models.RaceEventLiveTracking.objects.filter(event=event).update(
                            state=models.RaceEventLiveState.AWAITING_RESULT,
                            updated_at=now,
                        )
                    stats["transitioned"] += 1
                    transaction.on_commit(invalidate_public_race_cache)
                else:
                    stats["replayed"] += 1
            else:
                stats["not_due"] += 1
            control.last_attempt_at = now
            control.last_success_at = now
            control.last_result_code = decision.reason_code
            control.last_error = ""
            control.consecutive_failures = 0
            control.next_refresh_at = decision.next_refresh_at
            control.claim_token = ""
            control.claim_expires_at = None
            control.save(
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
    return stats

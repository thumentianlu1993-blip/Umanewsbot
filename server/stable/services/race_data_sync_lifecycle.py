from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from stable import models
from stable.services.race_data_sync_admission import (
    validate_data_sync_lifecycle_admission,
)
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
            reason_code=(
                "data_sync_late_admission_finish"
                if event.status == models.RaceEventStatus.SCHEDULED
                else "data_sync_time_t_plus_30"
            ),
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


def apply_data_sync_lifecycle_decision(
    *,
    event_id: int,
    expected_generation: int,
    now: datetime,
    standing_policy: dict | None = None,
):
    """Apply the lifecycle decision for one data-sync-admitted event.

    The shared admission validator is the only authorization source; the
    existing lifecycle engine remains the sole transition writer.
    """

    from stable.services.race_event_lifecycle import (
        ApplyResult,
        apply_race_lifecycle_decision,
    )

    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    if not getattr(settings, "RACE_EVENT_LIFECYCLE_ENABLED", False) or getattr(
        settings, "RACE_EVENT_LIFECYCLE_MODE", "off"
    ) != "enforce":
        return ApplyResult(action="noop", reason_code="lifecycle_disabled_mid_flight")
    with transaction.atomic():
        admission = validate_data_sync_lifecycle_admission(
            event_id=event_id,
            now=now,
            lock=True,
            standing_policy=standing_policy,
        )
        if not admission.admitted:
            return ApplyResult(action="noop", reason_code=admission.reason_code)
        control = admission.control
        assert control is not None
        evidence = (
            control.manifest_data.get("race_data_sync")
            if isinstance(control.manifest_data, dict)
            else None
        )
        if not isinstance(evidence, dict):
            return ApplyResult(action="noop", reason_code="lifecycle_evidence_drift")
        pre_status = admission.event.status if admission.event is not None else ""
        result = apply_race_lifecycle_decision(
            event_id=event_id,
            expected_generation=expected_generation,
            now=now,
            mode="enforce",
            registry_authorized=True,
            registry_transition_metadata={"race_data_sync": dict(evidence)},
        )
        if (
            result.action == "applied"
            and pre_status == models.RaceEventStatus.SCHEDULED
            and models.RaceEvent.objects.filter(
                pk=event_id, status=models.RaceEventStatus.FINISHED
            ).exists()
        ):
            transition = (
                models.RaceEventLifecycleTransition.objects.filter(event_id=event_id)
                .order_by("-id")
                .first()
            )
            if transition is not None and transition.reason_code == "time_t_plus_30":
                transition.reason_code = "data_sync_late_admission_finish"
                transition.save(update_fields=("reason_code", "updated_at"))
        return result


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
    registry = registry_or_reason if registry_valid else None
    if registry is not None and (
        not isinstance(registry, models.RaceEventLifecycleEnforceRegistry)
        or now >= registry.runtime_valid_until
    ):
        registry = None

    from stable.services.race_data_sync_enrollment import (
        load_standing_policy_file,
    )

    try:
        standing_policy = load_standing_policy_file(
            path=settings.RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE,
            expected_sha256=settings.RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256,
        )
    except (OSError, TypeError, ValueError):
        standing_policy = None

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
        membership = None
        if registry is not None:
            membership = (
                models.RaceEventLifecycleEnforceMembership.objects.select_related(
                    "registry"
                )
                .filter(registry=registry, event_id=control.event_id, state="active")
                .first()
            )
        elif models.RaceEventLifecycleEnforceMembership.objects.filter(
            event_id=control.event_id,
            state="active",
            registry__state="active",
            registry__is_active=True,
        ).exists():
            stats["error"] += 1
            continue
        if membership is not None:
            if isinstance(control.manifest_data, dict) and (
                "race_data_sync" in control.manifest_data
            ):
                stats["error"] += 1
                continue
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
            continue

        admission = validate_data_sync_lifecycle_admission(
            event_id=control.event_id,
            now=now,
            standing_policy=standing_policy,
        )
        if not admission.admitted:
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
                locked_admission = validate_data_sync_lifecycle_admission(
                    event_id=locked_control.event_id,
                    now=now,
                    lock=True,
                    standing_policy=standing_policy,
                )
                if not locked_admission.admitted:
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
            result = apply_data_sync_lifecycle_decision(
                event_id=control.event_id,
                expected_generation=control.schedule_generation,
                now=now,
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


def reconcile_data_sync_lifecycle_admission(
    *,
    now: datetime,
    batch_size: int = 20,
    standing_policy: dict | None = None,
) -> dict[str, int]:
    """Promote long-enrolled events to data-sync lifecycle admission.

    Bounded per batch; only rows whose standing policy is still valid and
    whose evidence chain is complete are promoted.  Manual pauses, active
    legacy memberships and drifted rows are skipped, never forced.
    """

    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    if isinstance(batch_size, bool) or not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100")
    stats: dict[str, int] = {"selected": 0, "enforced": 0, "skipped": 0, "error": 0}
    from stable.services.race_data_sync_enrollment import (
        load_standing_policy_file,
        parse_standing_policy,
    )

    if standing_policy is None:
        try:
            standing_policy = load_standing_policy_file(
                path=settings.RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE,
                expected_sha256=settings.RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256,
            )
        except (OSError, TypeError, ValueError):
            stats["error"] = 1
            return stats
    try:
        policy = parse_standing_policy(standing_policy)
    except (TypeError, ValueError):
        stats["error"] = 1
        return stats
    if not (policy.valid_from <= now < policy.valid_until):
        stats["error"] = 1
        return stats

    enrollments = tuple(
        models.RaceDataSyncEnrollment.objects.filter(
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            standing_policy_digest=policy.digest,
            event__projection_control__write_owner=(
                models.RaceEventProjectionWriteOwner.DATA_SYNC
            ),
        )
        .exclude(
            event__lifecycle_control__mode=models.RaceEventLifecycleMode.ENFORCE
        )
        .select_related("event", "source_identity")
        .order_by("event_id")[:batch_size]
    )
    stats["selected"] = len(enrollments)

    from stable.services.race_data_sync_control import (
        _establish_data_sync_lifecycle_evidence,
        source_admission_reason,
    )

    for enrollment in enrollments:
        event = enrollment.event
        projection = (
            models.RaceEventProjectionControl.objects.filter(event=event).first()
        )
        control = models.RaceEventLifecycleControl.objects.filter(
            event=event
        ).first()
        route = next(
            (
                item
                for item in policy.routes
                if item.country_region == event.country_region
                and item.provider == enrollment.source_identity.source_key
                and item.region_code == enrollment.source_identity.region_code
                and item.identity_namespace
                == enrollment.source_identity.identity_namespace
                and item.route_digest == enrollment.route_digest
            ),
            None,
        )
        legacy_active = models.RaceEventLifecycleEnforceMembership.objects.filter(
            event_id=event.pk,
            state="active",
            registry__state="active",
            registry__is_active=True,
            registry__runtime_valid_until__gt=now,
        ).exists()
        reason = ""
        if control is not None and control.manual_pause_reason:
            reason = "manual_pause_present"
        elif isinstance(event.manual_lock_flags, dict) and any(
            event.manual_lock_flags.values()
        ):
            reason = "manual_lock_present"
        elif (
            event.visibility_status != models.RaceEventVisibility.PUBLISHED
            or event.status
            in {
                models.RaceEventStatus.FINISHED,
                models.RaceEventStatus.CANCELLED,
            }
        ):
            reason = "event_state_not_allowed"
        elif legacy_active:
            reason = "legacy_membership_active"
        elif route is None or not route.enrollment_eligible:
            reason = "enrollment_route_missing"
        elif projection is None:
            reason = "writer_owner_conflict"
        elif (
            enrollment.projection_owner_generation != projection.owner_generation
            or enrollment.manifest_sha256 != projection.owner_manifest_sha256
        ):
            reason = "enrollment_owner_generation_drift"
        else:
            reason = source_admission_reason(
                source=enrollment.source_identity,
                route_digest=route.route_digest,
                data_kinds=route.data_kinds,
                now=now,
            )
        if reason:
            stats["skipped"] += 1
            stats[f"skipped_{reason}"] = stats.get(f"skipped_{reason}", 0) + 1
            continue
        with transaction.atomic():
            control, _ = models.RaceEventLifecycleControl.objects.get_or_create(
                event=event,
                defaults={
                    "mode": models.RaceEventLifecycleMode.OFF,
                    "schedule_generation": 1,
                    "next_refresh_at": None,
                    "enrollment_manifest_sha256": "",
                    "manifest_data": {},
                },
            )
            control = models.RaceEventLifecycleControl.objects.select_for_update().get(
                pk=control.pk
            )
            _establish_data_sync_lifecycle_evidence(
                lifecycle=control,
                event=event,
                standing_policy_digest=policy.digest,
                manifest_sha256=enrollment.manifest_sha256,
                entry_sha256=enrollment.entry_sha256,
                owner_generation=enrollment.projection_owner_generation,
                now=now,
            )
        stats["enforced"] += 1
    return stats

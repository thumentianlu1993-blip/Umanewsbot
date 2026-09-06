from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.conf import settings
from django.utils import timezone

from stable import models
from stable.services import race_data_sync_control
from stable.services.race_data_sync_enrollment import (
    StandingPolicyRoute,
    load_standing_policy_file,
    parse_standing_policy,
)


@dataclass(frozen=True)
class LifecycleAdmissionDecision:
    admitted: bool
    reason_code: str
    authority: str = ""
    event: models.RaceEvent | None = None
    control: models.RaceEventLifecycleControl | None = None
    enrollment: models.RaceDataSyncEnrollment | None = None
    source: models.RaceResultSourceIdentity | None = None
    route: StandingPolicyRoute | None = None


def _deny(reason_code: str, **kwargs: Any) -> LifecycleAdmissionDecision:
    return LifecycleAdmissionDecision(False, reason_code, **kwargs)


def validate_data_sync_lifecycle_admission(
    *,
    event_id: int,
    now: datetime,
    lock: bool = False,
    standing_policy: dict[str, Any] | None = None,
) -> LifecycleAdmissionDecision:
    """Single admission entry for data-sync lifecycle, result and public reads.

    Every caller must share this one decision so a database write can never be
    authorized by rules that the public page would reject, or the other way
    around.  Legacy registry membership for an unfinished event is a hard
    conflict, not a fallback.
    """

    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    for flag in (
        "RACE_DATA_SYNC_ENABLED",
        "RACE_DATA_SYNC_SCHEDULER_ENABLED",
        "RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED",
    ):
        if getattr(settings, flag, False) is not True:
            return _deny("lifecycle_apply_disabled")
    if standing_policy is None:
        try:
            standing_policy = load_standing_policy_file(
                path=settings.RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE,
                expected_sha256=settings.RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256,
            )
        except (OSError, TypeError, ValueError):
            return _deny("standing_policy_unavailable")
    try:
        policy = parse_standing_policy(standing_policy)
    except (TypeError, ValueError):
        return _deny("standing_policy_unavailable")
    if not (policy.valid_from <= now < policy.valid_until):
        return _deny("standing_policy_expired")

    event_qs = models.RaceEvent.objects.all()
    control_qs = models.RaceEventLifecycleControl.objects.all()
    enrollment_qs = models.RaceDataSyncEnrollment.objects.select_related(
        "source_identity"
    )
    if lock:
        # Global lock graph: lifecycle control -> event -> projection ->
        # tracking/checkpoint -> source identity -> observation/revision.
        control_qs = control_qs.select_for_update()
        event_qs = event_qs.select_for_update()
        enrollment_qs = enrollment_qs.select_for_update()
    control = control_qs.filter(event_id=event_id).first()
    event = event_qs.filter(pk=event_id).first()
    if event is None:
        return _deny("event_missing")
    if event.visibility_status != models.RaceEventVisibility.PUBLISHED:
        return _deny("event_not_published")
    if isinstance(event.manual_lock_flags, dict) and any(event.manual_lock_flags.values()):
        return _deny("manual_lock_present")
    if event.status not in policy.continuation_statuses:
        return _deny("continuation_status_not_allowed")

    legacy_active = models.RaceEventLifecycleEnforceMembership.objects.filter(
        event_id=event_id,
        state="active",
        registry__state="active",
        registry__is_active=True,
        registry__runtime_valid_until__gt=now,
    ).exists()
    if legacy_active and event.status not in {
        models.RaceEventStatus.FINISHED,
        models.RaceEventStatus.CANCELLED,
    }:
        return _deny("lifecycle_authority_conflict")

    projection = models.RaceEventProjectionControl.objects.filter(
        event_id=event_id
    ).first()
    if (
        projection is None
        or projection.write_owner != models.RaceEventProjectionWriteOwner.DATA_SYNC
    ):
        return _deny("writer_owner_conflict")

    enrollment = enrollment_qs.filter(event_id=event_id).first()
    if (
        enrollment is None
        or enrollment.state != models.RaceDataSyncEnrollmentState.ENROLLED
    ):
        return _deny("enrollment_missing")
    if enrollment.standing_policy_digest != policy.digest:
        return _deny("enrollment_policy_drift")
    if enrollment.projection_owner_generation != projection.owner_generation:
        return _deny("enrollment_owner_generation_drift")
    if enrollment.manifest_sha256 != projection.owner_manifest_sha256:
        return _deny("enrollment_manifest_drift")

    source = enrollment.source_identity
    route = next(
        (
            item
            for item in policy.routes
            if item.country_region == event.country_region
            and item.provider == source.source_key
            and item.region_code == source.region_code
            and item.identity_namespace == source.identity_namespace
            and item.route_digest == enrollment.route_digest
        ),
        None,
    )
    if route is None:
        return _deny("enrollment_route_missing")
    if not route.enrollment_eligible:
        return _deny("enrollment_route_not_eligible")

    source_reason = race_data_sync_control.source_admission_reason(
        source=source,
        route_digest=route.route_digest,
        data_kinds=route.data_kinds,
        now=now,
    )
    if source_reason:
        return _deny(source_reason)

    if control is None:
        return _deny("lifecycle_control_missing")
    if control.manual_pause_reason:
        return _deny("manual_pause_present")
    if control.mode != models.RaceEventLifecycleMode.ENFORCE:
        return _deny("lifecycle_control_off")
    evidence = (
        control.manifest_data.get("race_data_sync")
        if isinstance(control.manifest_data, dict)
        else None
    )
    if (
        not isinstance(evidence, dict)
        or evidence.get("standing_policy_digest") != policy.digest
        or evidence.get("manifest_sha256") != enrollment.manifest_sha256
        or evidence.get("entry_sha256") != enrollment.entry_sha256
        or evidence.get("owner_generation") != projection.owner_generation
    ):
        return _deny("lifecycle_evidence_drift")

    return LifecycleAdmissionDecision(
        True,
        "",
        authority="data_sync",
        event=event,
        control=control,
        enrollment=enrollment,
        source=source,
        route=route,
    )

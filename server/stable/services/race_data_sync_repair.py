from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from stable import models
from stable.services import race_data_sync_control
from stable.services.race_data_sync_admission import (
    validate_data_sync_lifecycle_admission,
)
from stable.services.race_data_sync_enrollment import (
    _event_snapshot,
    parse_standing_policy,
)
from stable.services.race_data_sync_lifecycle import (
    reconcile_data_sync_lifecycle_admission,
)


@dataclass(frozen=True)
class StalledEventAssessment:
    event_id: int
    revision_id: int | None
    observation_id: int | None
    repairable: bool
    reason_code: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "revision_id": self.revision_id,
            "observation_id": self.observation_id,
            "repairable": self.repairable,
            "reason_code": self.reason_code,
        }


def find_unclosed_data_sync_events(
    *,
    now: datetime,
    horizon_days: int = 7,
    batch_size: int = 20,
) -> tuple[models.RaceEvent, ...]:
    """Bounded list of recently stalled data-sync events.

    Only events that are enrolled, still tracked and either hold a terminal
    result revision that was never published or carry an open data-sync
    incident qualify; cancelled events and anything outside the recent
    window are never scanned.
    """

    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    if isinstance(horizon_days, bool) or not 1 <= horizon_days <= 30:
        raise ValueError("horizon_days must be between 1 and 30")
    if isinstance(batch_size, bool) or not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100")
    revision_ids = set(
        models.RaceEvent.objects.filter(
            race_data_sync_enrollment__state=models.RaceDataSyncEnrollmentState.ENROLLED,
            live_tracking__tracking_enabled=True,
            revisions__kind=models.RaceEventRevisionKind.RESULT,
            revisions__phase__in=(
                models.RaceResultPhase.OFFICIAL,
                models.RaceResultPhase.CORRECTED,
            ),
            revisions__published_at__isnull=True,
        ).values_list("id", flat=True)
    )
    incident_keys = models.RaceLiveAlertIncident.objects.filter(
        scope_type="data_sync_event",
        status=models.RaceLiveAlertIncidentStatus.OPEN,
    ).values_list("scope_key", flat=True)
    incident_ids = {int(key) for key in incident_keys if str(key).isdigit()}
    return tuple(
        models.RaceEvent.objects.filter(
            pk__in=revision_ids | incident_ids,
            local_date__gte=(now - timedelta(days=horizon_days)).date(),
            local_date__lte=now.date() + timedelta(days=1),
        )
        .exclude(status=models.RaceEventStatus.CANCELLED)
        .distinct()
        .order_by("id")[:batch_size]
    )


def adopt_stalled_event_policy(
    *,
    event: models.RaceEvent,
    now: datetime,
    standing_policy: dict[str, Any],
    adoption_token: str,
) -> str:
    """Rotate a stale-digest enrollment onto the current policy.

    Only allowed when the enrollment's granted route is still present and
    eligible in the current policy and the source still passes admission;
    the route identity itself never changes.  Returns "" or a reason code.
    """

    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    policy = parse_standing_policy(standing_policy)
    if not (policy.valid_from <= now < policy.valid_until):
        return "standing_policy_expired"
    with transaction.atomic():
        enrollment = (
            models.RaceDataSyncEnrollment.objects.select_for_update()
            .select_related("source_identity")
            .filter(event=event)
            .first()
        )
        if (
            enrollment is None
            or enrollment.state != models.RaceDataSyncEnrollmentState.ENROLLED
        ):
            return "enrollment_missing"
        if enrollment.standing_policy_digest == policy.digest:
            return ""
        source = enrollment.source_identity
        route = next(
            (
                item
                for item in policy.routes
                if item.country_region == event.country_region
                and item.provider == source.source_key
                and item.region_code == source.region_code
                and item.identity_namespace == source.identity_namespace
                and item.enrollment_eligible
            ),
            None,
        )
        if route is None:
            return "enrollment_route_missing"
        source_reason = race_data_sync_control.source_admission_reason(
            source=source,
            route_digest=route.route_digest,
            data_kinds=route.data_kinds,
            now=now,
        )
        if source_reason:
            return source_reason
        projection = models.RaceEventProjectionControl.objects.filter(
            event=event
        ).first()
        if (
            projection is None
            or projection.write_owner
            != models.RaceEventProjectionWriteOwner.DATA_SYNC
        ):
            return "writer_owner_conflict"
        if (
            enrollment.projection_owner_generation != projection.owner_generation
            or enrollment.manifest_sha256 != projection.owner_manifest_sha256
        ):
            return "enrollment_owner_generation_drift"
        import hashlib

        previous_digest = enrollment.standing_policy_digest
        successor_manifest = hashlib.sha256(
            f"repair-adopt:{adoption_token}:{event.pk}:manifest".encode()
        ).hexdigest()
        successor_entry = hashlib.sha256(
            f"repair-adopt:{adoption_token}:{event.pk}:entry".encode()
        ).hexdigest()
        snapshot = _event_snapshot(
            event=event,
            control=projection,
            enrollment=enrollment,
            source=source,
            route=route,
        )
        decision = race_data_sync_control.rotate_enrollment(
            event_id=event.pk,
            source_identity_id=source.pk,
            standing_policy_digest=policy.digest,
            route_digest=route.route_digest,
            event_snapshot_sha256=snapshot,
            successor_manifest_sha256=successor_manifest,
            successor_entry_sha256=successor_entry,
            expected_manifest_sha256=projection.owner_manifest_sha256,
            expected_owner_generation=projection.owner_generation,
            data_kinds=route.data_kinds,
            now=now,
        )
        if decision.action != "rotated":
            transaction.set_rollback(True)
            return decision.reason_code or "rotation_rejected"
        import json

        models.OperationLog.objects.create(
            admin=None,
            action_type="race_data_sync_policy_adoption",
            target_type="race_event",
            target_id=str(event.pk),
            detail=json.dumps(
                {
                    "policy_digest": policy.digest,
                    "previous_policy_digest": previous_digest,
                    "rotation_manifest": successor_manifest,
                    "adoption_token": adoption_token,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    return ""


def assess_stalled_event(
    *,
    event: models.RaceEvent,
    now: datetime,
    standing_policy: dict[str, Any] | None = None,
    lock: bool = False,
) -> StalledEventAssessment:
    revision = (
        models.RaceEventRevision.objects.filter(
            event=event,
            kind=models.RaceEventRevisionKind.RESULT,
            phase__in=(
                models.RaceResultPhase.OFFICIAL,
                models.RaceResultPhase.CORRECTED,
            ),
            published_at__isnull=True,
        )
        .order_by("-revision_no")
        .first()
    )
    if revision is None:
        return StalledEventAssessment(
            event.pk, None, None, False, "no_unpublished_terminal_revision"
        )
    observation = revision.primary_observation
    if observation is None:
        return StalledEventAssessment(
            event.pk, revision.pk, None, False, "primary_observation_missing"
        )
    if (
        observation.result_phase != revision.phase
        or observation.normalized_sha256 != revision.content_sha256
    ):
        return StalledEventAssessment(
            event.pk, revision.pk, observation.pk, False, "observation_revision_mismatch"
        )
    if isinstance(event.manual_lock_flags, dict) and any(event.manual_lock_flags.values()):
        return StalledEventAssessment(
            event.pk, revision.pk, observation.pk, False, "manual_lock_present"
        )
    admission = validate_data_sync_lifecycle_admission(
        event_id=event.pk,
        now=now,
        lock=lock,
        standing_policy=standing_policy,
    )
    if not admission.admitted:
        return StalledEventAssessment(
            event.pk, revision.pk, observation.pk, False, admission.reason_code
        )
    return StalledEventAssessment(event.pk, revision.pk, observation.pk, True, "")


def verify_stalled_event_repair(
    *,
    event_id: int,
    revision_id: int,
    now: datetime,
) -> str:
    """Independent post-write checks; returns "" only when fully closed."""

    event = models.RaceEvent.objects.filter(pk=event_id).first()
    if event is None:
        return "event_missing"
    revision = models.RaceEventRevision.objects.filter(
        pk=revision_id, event_id=event_id
    ).first()
    if revision is None:
        return "revision_missing"
    if event.status != models.RaceEventStatus.FINISHED or event.result_confirmed_at is None:
        return "event_not_finished"
    if revision.published_at is None:
        return "revision_not_published"
    if not models.RaceEventRevisionPublication.objects.filter(
        revision_id=revision.pk
    ).exists():
        return "publication_missing"
    control = models.RaceEventProjectionControl.objects.filter(event_id=event_id).first()
    if control is None or control.current_result_revision_id != revision.pk:
        return "current_revision_mismatch"
    if revision.items.count() != event.results.count():
        return "result_count_mismatch"
    from stable.services import race_events

    public = race_events.resolve_race_live_public_read(event_id=event_id, now=now)
    if not public.visible:
        return f"public_read_{public.reason}"
    return ""


def apply_stalled_event_repair(
    *,
    assessment: StalledEventAssessment,
    now: datetime,
    standing_policy: dict[str, Any] | None = None,
    operation_detail: dict[str, Any] | None = None,
) -> str:
    """Re-validate and project one stalled event through the standard writer."""

    if not assessment.repairable or assessment.observation_id is None:
        return assessment.reason_code or "not_repairable"
    from stable.services.race_data_sync_results import (
        apply_data_sync_result_observation,
    )

    with transaction.atomic():
        admission = validate_data_sync_lifecycle_admission(
            event_id=assessment.event_id,
            now=now,
            lock=True,
            standing_policy=standing_policy,
        )
        if not admission.admitted:
            return admission.reason_code
        decision = apply_data_sync_result_observation(
            observation_id=assessment.observation_id,
            expected_event_id=assessment.event_id,
            now=now,
            project_current=True,
            correction_apply_enabled=getattr(
                settings, "RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED", False
            )
            is True,
        )
        if not decision.projected:
            transaction.set_rollback(True)
            return decision.reason_code or "result_not_projected"
        verify_reason = verify_stalled_event_repair(
            event_id=assessment.event_id,
            revision_id=decision.revision_id,
            now=now,
        )
        if verify_reason:
            transaction.set_rollback(True)
            return verify_reason
        models.RaceLiveAlertIncident.objects.filter(
            scope_type="data_sync_event",
            scope_key=str(assessment.event_id),
            status__in=(
                models.RaceLiveAlertIncidentStatus.OPEN,
                models.RaceLiveAlertIncidentStatus.SENDING,
                models.RaceLiveAlertIncidentStatus.FAILED,
            ),
        ).update(
            status=models.RaceLiveAlertIncidentStatus.RESOLVED,
            resolved_at=now,
            updated_at=now,
        )
        import json

        models.OperationLog.objects.create(
            admin=None,
            action_type="race_data_sync_stalled_repair",
            target_type="race_event",
            target_id=str(assessment.event_id),
            detail=json.dumps(
                {
                    **(operation_detail or {}),
                    "revision_id": decision.revision_id,
                    "observation_id": assessment.observation_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    return ""

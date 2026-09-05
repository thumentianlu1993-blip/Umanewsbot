from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from stable import models
from stable.services.race_data_sync_admission import (
    validate_data_sync_lifecycle_admission,
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

    Only events that are enrolled, still tracked and hold a terminal result
    revision that was never published qualify; cancelled events and anything
    outside the recent window are never scanned.
    """

    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    if isinstance(horizon_days, bool) or not 1 <= horizon_days <= 30:
        raise ValueError("horizon_days must be between 1 and 30")
    if isinstance(batch_size, bool) or not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100")
    return tuple(
        models.RaceEvent.objects.filter(
            race_data_sync_enrollment__state=models.RaceDataSyncEnrollmentState.ENROLLED,
            live_tracking__tracking_enabled=True,
            revisions__kind=models.RaceEventRevisionKind.RESULT,
            revisions__phase__in=(
                models.RaceResultPhase.OFFICIAL,
                models.RaceResultPhase.CORRECTED,
            ),
            revisions__published_at__isnull=True,
            local_date__gte=(now - timedelta(days=horizon_days)).date(),
            local_date__lte=now.date() + timedelta(days=1),
        )
        .distinct()
        .order_by("id")[:batch_size]
    )


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
    return ""

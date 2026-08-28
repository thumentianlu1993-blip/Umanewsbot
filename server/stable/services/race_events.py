from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from stable.models import (
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    ArticleRaceLinkType,
    ContentCategory,
    NewsArticle,
    RaceEvent,
    RaceEventCandidateStatus,
    RaceEventDataCandidate,
    RaceEventDataQuality,
    RaceEventHistoryWinner,
    RaceEventLiveState,
    RaceEventLifecycleControl,
    RaceEventLifecycleEnforceMembership,
    RaceDataSyncEnrollment,
    RaceLiveHostBudget,
    RaceEventLiveTracking,
    RaceEventModule,
    RaceEventParticipant,
    RaceEventProjectionControl,
    RaceEventProjectionWriteOwner,
    RaceEventRevision,
    RaceEventRevisionConflictStatus,
    RaceEventRevisionEvidence,
    RaceEventRevisionItem,
    RaceEventRevisionItemStatus,
    RaceEventRevisionKind,
    RaceEventRevisionPublication,
    RaceEventResult,
    RaceEventRunner,
    RaceEventStatus,
    RaceEventParticipantSourceIdentity,
    RaceLiveEventPublicationAllowlist,
    RaceLiveAlertIncident,
    RaceLiveAlertIncidentStatus,
    RaceLiveAlertType,
    RaceLiveOfficialMarkerEvidence,
    RaceLiveOfficialPublicationAuthorization,
    RaceLiveOfficialVerificationIncident,
    RaceLiveOfficialVerificationIncidentStatus,
    RaceLivePublicationMode,
    RaceLivePublicationPolicy,
    RaceLivePublicationScopeType,
    RaceResultObservation,
    RaceResultPhase,
    RaceResultSourceAuthority,
    RaceResultSourceIdentity,
    RaceLiveReviewStatus,
    RaceRunnerStatus,
    RacingRegion,
    RaceSourceTermsStatus,
    TaskExecutionLog,
    TaskStatus,
    WorkflowStatus,
)
from stable.services.operations import log_operation
from stable.services.historical_race_inventory import sanitize_structured_row_evidence
from stable.services.terms import source_term_matches_text
from stable.services.race_field_normalization import (
    RACE_FIELD_NORMALIZATION_VERSION,
    compute_input_sha256,
    normalize_distance,
    normalize_eligibility,
    normalize_surface_race_type_layout_going,
)

# 赛事总账关联保持为独立领域服务；这里重导出兼容既有调用方和测试 API。
from stable.services.race_event_reconciliation import (
    adopt_existing_race_event_for_target,
    apply_race_event_coverage_reconciliation,
    build_layered_race_event_coverage_report,
    classify_historical_race_event_targets,
    export_race_event_coverage_reconciliation,
    reconcile_historical_race_event_targets,
    rollback_race_event_coverage_reconciliation,
    verify_race_event_coverage_reconciliation,
)
from stable.services.race_live_rollback import (
    build_race_live_rollback_bundle,
    load_race_live_rollback_manifest,
    prepare_race_live_rollback_bundle,
    transition_race_live_rollback_maintenance,
)


User = get_user_model()

DYNAMIC_RUNNER_FIELDS = {"odds_value", "popularity", "running_status"}
BASIC_EVENT_FIELDS = {
    "original_name",
    "chinese_name",
    "country_region",
    "racecourse",
    "grade_text",
    "normalized_grade",
    "surface",
    "distance_text",
    "eligibility_text",
    "race_datetime",
    "timezone_name",
    "local_date",
    "local_start_time",
    "priority",
    "status",
    "visibility_status",
    "data_quality_status",
    "is_featured",
    "source_refs",
}

HORSE_COUNTRY_SUFFIX_RE = re.compile(r"\s*[\(\（][A-Z]{2,3}[\)\）]\s*$")

RACE_LIVE_MODE_ORDER = (
    "off",
    "shadow",
    "provisional_public",
    "official_public",
)
RACE_LIVE_MODE_RANK = {mode: rank for rank, mode in enumerate(RACE_LIVE_MODE_ORDER)}
RACE_LIVE_ALLOWED_STATE_TRANSITIONS = frozenset(
    {
        ("scheduled", "racecard_ready"),
        ("racecard_ready", "awaiting_result"),
        ("awaiting_result", "provisional_result"),
        ("awaiting_result", "official_result"),
        ("provisional_result", "official_result"),
        ("official_result", "corrected_result"),
        ("corrected_result", "corrected_result"),
    }
)
RACE_LIVE_STATES = frozenset(
    {
        "scheduled",
        "racecard_ready",
        "awaiting_result",
        "provisional_result",
        "official_result",
        "corrected_result",
    }
)
RACE_PROJECTION_MANIFEST_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class RaceEventProjectionOwnershipConflict(RuntimeError):
    """Raised when a projection ownership compare-and-swap cannot be applied."""


@dataclass
class RaceArticleMatch:
    article: NewsArticle
    status: str
    link_type: str
    confidence: int
    matched_text: str
    reason: str


@dataclass(frozen=True)
class RaceSourceNetworkPermissionDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class RaceLivePublicationPolicyDecision:
    allowed: bool
    effective_mode: str
    reason: str
    policy_versions: tuple[tuple[str, str, int], ...] = ()
    allowlist_version: int = 0
    registry_digest: str = ""
    coverage_proof_digest: str = ""


@dataclass(frozen=True)
class RaceLiveWorkerNetworkAdmissionDecision:
    allowed: bool
    reason: str
    source_identity_id: int | None = None
    effective_mode: str = RaceLivePublicationMode.OFF


@dataclass(frozen=True)
class RaceLiveOfficialAuthorizationDecision:
    allowed: bool
    reason: str
    authorization_version: int = 0
    route_registry_digest: str = ""
    coverage_proof_digest: str = ""


@dataclass(frozen=True)
class RaceLiveProvisionalRollbackDecision:
    allowed: bool
    reason: str
    revision_id: int | None = None


@dataclass(frozen=True)
class RaceLiveAlertDeliveryClaimDecision:
    claimed: bool
    reason: str
    delivery_token: str = ""
    incident_id: int | None = None


@dataclass(frozen=True)
class RaceLiveAlertDeliveryCompletionDecision:
    applied: bool
    reason: str


@dataclass(frozen=True)
class RaceLiveRacecardRefreshDecision:
    applied: bool
    reason: str
    revision_id: int | None = None
    replayed: bool = False


@dataclass(frozen=True)
class RaceLivePublicReadDecision:
    visible: bool
    reason: str
    revision_id: int | None = None
    phase: str = ""
    effective_mode: str = RaceLivePublicationMode.OFF


@dataclass(frozen=True)
class RaceLiveHostReservationDecision:
    reserved: bool
    reason: str
    next_allowed_at: datetime | None = None
    reservation_version: int = 0


@dataclass(frozen=True)
class RaceLiveHostOutcomeDecision:
    recorded: bool
    reason: str
    consecutive_failures: int = 0
    circuit_open_until: datetime | None = None


@dataclass(frozen=True)
class RaceEventLiveClaimDecision:
    claimed: bool
    reason: str
    attempt_token: str = ""
    claim_generation: int = 0


@dataclass(frozen=True)
class RaceEventLiveBatchClaim:
    event_id: int
    owner_generation: int
    claim_generation: int
    attempt_token: str


@dataclass(frozen=True)
class RaceEventLiveCheckpointDecision:
    applied: bool
    reason: str


@dataclass(frozen=True)
class RaceEventLivePreOffDecision:
    applied: bool
    reason: str
    promoted: bool = False


@dataclass(frozen=True)
class RaceEventLiveDisableDecision:
    applied: bool
    reason: str


@dataclass(frozen=True)
class RaceResultObservationRecordDecision:
    recorded: bool
    reason: str
    created: bool = False
    observation: RaceResultObservation | None = None


@dataclass(frozen=True)
class RaceResultRevisionApplyDecision:
    applied: bool
    action: str
    reason: str
    revision: RaceEventRevision | None = None


@dataclass(frozen=True)
class RaceResultRevisionActionDecision:
    action: str
    reason: str
    next_state: str | None = None
    next_phase: str | None = None
    conflict: bool = False


def disable_race_event_live_tracking(
    *,
    event_id: int,
    expected_lock_version: int,
    now: datetime,
    disabled_by: User | None,
) -> RaceEventLiveDisableDecision:
    """Disable one event's live polling and invalidate every outstanding claim."""
    if not isinstance(event_id, int) or isinstance(event_id, bool) or event_id <= 0:
        return RaceEventLiveDisableDecision(False, "invalid_event_id")
    if (
        not isinstance(expected_lock_version, int)
        or isinstance(expected_lock_version, bool)
        or expected_lock_version < 0
    ):
        return RaceEventLiveDisableDecision(False, "invalid_lock_version")
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return RaceEventLiveDisableDecision(False, "invalid_now")
    if disabled_by is not None and not isinstance(disabled_by, User):
        return RaceEventLiveDisableDecision(False, "invalid_disabled_by")

    with transaction.atomic():
        try:
            tracking = RaceEventLiveTracking.objects.select_for_update().get(
                event_id=event_id
            )
        except RaceEventLiveTracking.DoesNotExist:
            return RaceEventLiveDisableDecision(False, "tracking_missing")

        if tracking.lock_version != expected_lock_version:
            return RaceEventLiveDisableDecision(False, "lock_version_mismatch")
        if not tracking.tracking_enabled:
            return RaceEventLiveDisableDecision(False, "already_disabled")

        tracking.tracking_enabled = False
        tracking.next_poll_at = None
        tracking.active_attempt_token = ""
        tracking.claim_expires_at = None
        tracking.claim_generation += 1
        tracking.lock_version += 1
        tracking.circuit_reason = "manual_kill_switch"
        tracking.save(
            update_fields=(
                "tracking_enabled",
                "next_poll_at",
                "active_attempt_token",
                "claim_expires_at",
                "claim_generation",
                "lock_version",
                "circuit_reason",
                "updated_at",
            )
        )
        log_operation(
            action_type="race_live_tracking_disabled",
            target_type="race_event_live_tracking",
            target_id=tracking.pk,
            detail=(
                f"手动停用准实时赛事追踪 event={event_id} "
                f"lock_version={expected_lock_version}->{tracking.lock_version} "
                f"disabled_at={now.isoformat()}"
            ),
            admin=disabled_by,
        )
        return RaceEventLiveDisableDecision(True, "tracking_disabled")


def reserve_race_live_host_request(
    *,
    host: str,
    now: datetime,
) -> RaceLiveHostReservationDecision:
    """Reserve one request slot from an explicitly configured host budget."""
    if (
        not isinstance(host, str)
        or not host
        or len(host) > 255
        or host.strip() != host
    ):
        return RaceLiveHostReservationDecision(False, "invalid_host")
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return RaceLiveHostReservationDecision(False, "invalid_now")

    with transaction.atomic():
        try:
            budget = RaceLiveHostBudget.objects.select_for_update().get(host=host)
        except RaceLiveHostBudget.DoesNotExist:
            return RaceLiveHostReservationDecision(False, "budget_missing")

        if budget.circuit_open_until is not None and budget.circuit_open_until > now:
            return RaceLiveHostReservationDecision(
                False,
                "circuit_open",
                next_allowed_at=budget.circuit_open_until,
            )
        if budget.next_allowed_at is not None and budget.next_allowed_at > now:
            return RaceLiveHostReservationDecision(
                False,
                "rate_limited",
                next_allowed_at=budget.next_allowed_at,
            )

        budget.next_allowed_at = now + timedelta(milliseconds=budget.min_interval_ms)
        budget.lock_version += 1
        budget.save(update_fields=("next_allowed_at", "lock_version"))
        return RaceLiveHostReservationDecision(
            True,
            "reserved",
            next_allowed_at=budget.next_allowed_at,
            reservation_version=budget.lock_version,
        )


def record_race_live_host_outcome(
    *,
    host: str,
    now: datetime,
    success: bool,
    error_code: str,
    circuit_threshold: int,
    circuit_seconds: int,
    expected_reservation_version: int,
) -> RaceLiveHostOutcomeDecision:
    """Record one request outcome against an explicitly configured host budget."""
    if (
        not isinstance(host, str)
        or not host
        or len(host) > 255
        or host.strip() != host
    ):
        return RaceLiveHostOutcomeDecision(False, "invalid_host")
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return RaceLiveHostOutcomeDecision(False, "invalid_now")
    if not isinstance(success, bool):
        return RaceLiveHostOutcomeDecision(False, "invalid_success")
    if (
        not isinstance(error_code, str)
        or len(error_code) > 64
        or error_code.strip() != error_code
        or (success and error_code != "")
        or (not success and error_code == "")
    ):
        return RaceLiveHostOutcomeDecision(False, "invalid_error_code")
    if (
        isinstance(circuit_threshold, bool)
        or not isinstance(circuit_threshold, int)
        or not 1 <= circuit_threshold <= 100
    ):
        return RaceLiveHostOutcomeDecision(False, "invalid_threshold")
    if (
        isinstance(circuit_seconds, bool)
        or not isinstance(circuit_seconds, int)
        or circuit_seconds <= 0
    ):
        return RaceLiveHostOutcomeDecision(False, "invalid_circuit_seconds")
    if (
        isinstance(expected_reservation_version, bool)
        or not isinstance(expected_reservation_version, int)
        or expected_reservation_version < 0
    ):
        return RaceLiveHostOutcomeDecision(False, "invalid_reservation_version")

    with transaction.atomic():
        try:
            budget = RaceLiveHostBudget.objects.select_for_update().get(host=host)
        except RaceLiveHostBudget.DoesNotExist:
            return RaceLiveHostOutcomeDecision(False, "budget_missing")
        if budget.lock_version != expected_reservation_version:
            return RaceLiveHostOutcomeDecision(False, "stale_reservation")

        if success:
            budget.consecutive_failures = 0
            budget.last_error_code = ""
            budget.circuit_open_until = None
            reason = "success_recorded"
        else:
            budget.consecutive_failures += 1
            budget.last_error_code = error_code
            if budget.consecutive_failures >= circuit_threshold:
                budget.circuit_open_until = now + timedelta(seconds=circuit_seconds)
                reason = "circuit_opened"
            else:
                budget.circuit_open_until = None
                reason = "failure_recorded"

        budget.lock_version += 1
        budget.save(
            update_fields=(
                "consecutive_failures",
                "last_error_code",
                "circuit_open_until",
                "lock_version",
                "updated_at",
            )
        )
        return RaceLiveHostOutcomeDecision(
            True,
            reason,
            consecutive_failures=budget.consecutive_failures,
            circuit_open_until=budget.circuit_open_until,
        )


def claim_race_event_live_tracking(
    *,
    event_id: int,
    expected_owner_generation: int,
    now: datetime,
    ttl_seconds: int,
) -> RaceEventLiveClaimDecision:
    """Claim one due live-tracking row under projection-owner arbitration."""
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
        return RaceEventLiveClaimDecision(False, "invalid_event")
    if (
        isinstance(expected_owner_generation, bool)
        or not isinstance(expected_owner_generation, int)
        or expected_owner_generation < 0
    ):
        return RaceEventLiveClaimDecision(False, "invalid_owner_generation")
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return RaceEventLiveClaimDecision(False, "invalid_now")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        return RaceEventLiveClaimDecision(False, "invalid_ttl")

    with transaction.atomic():
        try:
            control = RaceEventProjectionControl.objects.select_for_update().get(
                event_id=event_id
            )
        except RaceEventProjectionControl.DoesNotExist:
            if not RaceEventLiveTracking.objects.filter(event_id=event_id).exists():
                return RaceEventLiveClaimDecision(False, "tracking_missing")
            return RaceEventLiveClaimDecision(False, "control_missing")

        try:
            tracking = RaceEventLiveTracking.objects.select_for_update().get(
                event_id=event_id
            )
        except RaceEventLiveTracking.DoesNotExist:
            return RaceEventLiveClaimDecision(False, "tracking_missing")

        if (
            control.write_owner != RaceEventProjectionWriteOwner.LIVE
            or control.owner_generation != expected_owner_generation
        ):
            return RaceEventLiveClaimDecision(False, "owner_mismatch")
        if tracking.tracking_enabled is not True:
            return RaceEventLiveClaimDecision(False, "tracking_disabled")
        if tracking.next_poll_at is None or tracking.next_poll_at > now:
            return RaceEventLiveClaimDecision(False, "not_due")
        if tracking.active_attempt_token and tracking.claim_expires_at is None:
            return RaceEventLiveClaimDecision(False, "claim_missing_expiry")
        if (
            tracking.active_attempt_token
            and tracking.claim_expires_at is not None
            and tracking.claim_expires_at > now
        ):
            return RaceEventLiveClaimDecision(False, "claim_active")

        attempt_token = uuid.uuid4().hex
        tracking.active_attempt_token = attempt_token
        tracking.claim_generation += 1
        tracking.claim_expires_at = now + timedelta(seconds=ttl_seconds)
        tracking.last_attempt_at = now
        tracking.lock_version += 1
        tracking.save(
            update_fields=(
                "active_attempt_token",
                "claim_generation",
                "claim_expires_at",
                "last_attempt_at",
                "lock_version",
                "updated_at",
            )
        )
        return RaceEventLiveClaimDecision(
            True,
            "claimed",
            attempt_token=attempt_token,
            claim_generation=tracking.claim_generation,
        )


def claim_due_race_event_live_tracking(
    *,
    now: datetime,
    batch_size: int,
    ttl_seconds: int,
    enabled_regions: Iterable[str] | None = None,
) -> tuple[RaceEventLiveBatchClaim, ...]:
    """Atomically claim a bounded batch of due live-tracking rows."""
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return ()
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or batch_size < 1
        or batch_size > 200
    ):
        return ()
    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or ttl_seconds <= 0
    ):
        return ()
    known_regions = {
        choice for choice, _label in RaceEvent._meta.get_field(
            "country_region"
        ).choices
    }
    if enabled_regions is None:
        region_ceiling = tuple(sorted(known_regions))
    else:
        if isinstance(enabled_regions, (str, bytes)):
            return ()
        try:
            region_ceiling = tuple(enabled_regions)
        except TypeError:
            return ()
        if (
            not region_ceiling
            or len(set(region_ceiling)) != len(region_ceiling)
            or any(region not in known_regions for region in region_ceiling)
        ):
            return ()

    with transaction.atomic():
        due_rows = list(
            RaceEventLiveTracking.objects.select_for_update(
                skip_locked=True,
                of=("self",),
            )
            .filter(
                tracking_enabled=True,
                next_poll_at__lte=now,
                event__country_region__in=region_ceiling,
                event__projection_control__write_owner=(
                    RaceEventProjectionWriteOwner.LIVE
                ),
            )
            .filter(
                Q(active_attempt_token="")
                | (
                    Q(active_attempt_token__gt="")
                    & Q(claim_expires_at__isnull=False)
                    & Q(claim_expires_at__lte=now)
                )
            )
            .annotate(
                selected_owner_generation=F(
                    "event__projection_control__owner_generation"
                )
            )
            .order_by("next_poll_at", "event_id")[:batch_size]
        )

        claims = []
        claim_expires_at = now + timedelta(seconds=ttl_seconds)
        for tracking in due_rows:
            attempt_token = uuid.uuid4().hex
            tracking.active_attempt_token = attempt_token
            tracking.claim_generation += 1
            tracking.claim_expires_at = claim_expires_at
            tracking.last_attempt_at = now
            tracking.lock_version += 1
            tracking.save(
                update_fields=(
                    "active_attempt_token",
                    "claim_generation",
                    "claim_expires_at",
                    "last_attempt_at",
                    "lock_version",
                    "updated_at",
                )
            )
            claims.append(
                RaceEventLiveBatchClaim(
                    event_id=tracking.event_id,
                    owner_generation=tracking.selected_owner_generation,
                    claim_generation=tracking.claim_generation,
                    attempt_token=attempt_token,
                )
            )
        return tuple(claims)


def resolve_race_live_worker_network_admission(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    enabled_regions: Iterable[str],
    now: datetime,
) -> RaceLiveWorkerNetworkAdmissionDecision:
    """Recheck source and publication gates immediately before any network I/O."""

    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
        or not isinstance(now, datetime)
        or timezone.is_naive(now)
    ):
        return RaceLiveWorkerNetworkAdmissionDecision(False, "invalid_input")
    try:
        region_ceiling = tuple(enabled_regions)
    except (TypeError, ValueError):
        return RaceLiveWorkerNetworkAdmissionDecision(
            False, "invalid_enabled_regions"
        )
    known_regions = {
        RacingRegion.UNITED_KINGDOM,
        RacingRegion.FRANCE,
        RacingRegion.HONG_KONG,
        RacingRegion.JAPAN,
        RacingRegion.UNITED_STATES,
    }
    if (
        len(set(region_ceiling)) != len(region_ceiling)
        or any(region not in known_regions for region in region_ceiling)
    ):
        return RaceLiveWorkerNetworkAdmissionDecision(
            False, "invalid_enabled_regions"
        )
    if not region_ceiling:
        return RaceLiveWorkerNetworkAdmissionDecision(
            False, "region_not_enabled"
        )
    try:
        event = RaceEvent.objects.get(pk=event_id)
        control = RaceEventProjectionControl.objects.get(event_id=event_id)
        tracking = RaceEventLiveTracking.objects.get(event_id=event_id)
    except (
        RaceEvent.DoesNotExist,
        RaceEventProjectionControl.DoesNotExist,
        RaceEventLiveTracking.DoesNotExist,
    ):
        return RaceLiveWorkerNetworkAdmissionDecision(False, "baseline_missing")
    if event.country_region not in region_ceiling:
        return RaceLiveWorkerNetworkAdmissionDecision(
            False, "region_not_enabled"
        )
    if (
        control.write_owner != RaceEventProjectionWriteOwner.LIVE
        or control.owner_generation != expected_owner_generation
    ):
        return RaceLiveWorkerNetworkAdmissionDecision(False, "owner_mismatch")
    if (
        tracking.tracking_enabled is not True
        or tracking.claim_generation != expected_claim_generation
        or tracking.active_attempt_token != attempt_token
        or tracking.claim_expires_at is None
        or tracking.claim_expires_at <= now
    ):
        return RaceLiveWorkerNetworkAdmissionDecision(False, "claim_mismatch")
    source = RaceResultSourceIdentity.objects.filter(
        event_id=event_id,
        source_key="the_racing_api",
    ).first()
    if source is None:
        return RaceLiveWorkerNetworkAdmissionDecision(False, "source_missing")
    policy = resolve_race_live_publication_policy(
        event_id=event_id,
        source_identity_id=source.pk,
        now=now,
    )
    if policy.effective_mode == RaceLivePublicationMode.OFF:
        return RaceLiveWorkerNetworkAdmissionDecision(
            False,
            policy.reason,
            source_identity_id=source.pk,
        )
    return RaceLiveWorkerNetworkAdmissionDecision(
        True,
        "admitted",
        source_identity_id=source.pk,
        effective_mode=policy.effective_mode,
    )


def calculate_race_live_alert_retry_delay(
    *,
    attempt_number: int,
) -> timedelta | None:
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
        raise TypeError("attempt_number must be an integer")
    if attempt_number < 1:
        raise ValueError("attempt_number must be positive")
    seconds = {1: 60, 2: 300, 3: 900}.get(attempt_number)
    return timedelta(seconds=seconds) if seconds is not None else None


def stage_race_live_sla_alerts(
    *,
    now: datetime,
    enabled_regions: Iterable[str],
) -> tuple[int, ...]:
    """Stage deduplicated SLA incidents; delivery is intentionally separate."""

    if not isinstance(now, datetime) or timezone.is_naive(now):
        return ()
    try:
        regions = tuple(enabled_regions)
    except TypeError:
        return ()
    known_regions = {
        choice
        for choice, _label in RaceEvent._meta.get_field(
            "country_region"
        ).choices
    }
    if not regions or any(region not in known_regions for region in regions):
        return ()

    candidates: list[dict[str, Any]] = []
    trackings = (
        RaceEventLiveTracking.objects.select_related("event")
        .filter(
            tracking_enabled=True,
            event__country_region__in=regions,
        )
        .order_by("event_id")
    )[:100]
    for tracking in trackings:
        event = tracking.event
        if (
            event.race_datetime is not None
            and tracking.state
            in {
                RaceEventLiveState.RACECARD_READY,
                RaceEventLiveState.AWAITING_RESULT,
            }
            and event.race_datetime + timedelta(minutes=15) <= now
        ):
            candidates.append(
                {
                    "alert_type": RaceLiveAlertType.PROVISIONAL_OVERDUE,
                    "scope_type": "event",
                    "scope_key": str(event.pk),
                    "reference_version": (
                        f"off:{event.race_datetime.isoformat()}"
                    ),
                    "deadline_at": event.race_datetime
                    + timedelta(minutes=15),
                    "details": {
                        "event_id": event.pk,
                        "event_name": (
                            event.chinese_name or event.original_name
                        ),
                        "region": event.country_region,
                        "state": tracking.state,
                    },
                }
            )
        if tracking.consecutive_failures >= 3:
            failure_episode_anchor = (
                tracking.last_success_at
                or event.race_datetime
                or tracking.window_started_at
            )
            candidates.append(
                {
                    "alert_type": RaceLiveAlertType.SOURCE_FAILURES,
                    "scope_type": "event",
                    "scope_key": str(event.pk),
                    "reference_version": (
                        "failure:"
                        + (
                            failure_episode_anchor.isoformat()
                            if failure_episode_anchor is not None
                            else "initial"
                        )
                    ),
                    "deadline_at": now,
                    "details": {
                        "event_id": event.pk,
                        "event_name": (
                            event.chinese_name or event.original_name
                        ),
                        "region": event.country_region,
                        "consecutive_failures": tracking.consecutive_failures,
                    },
                }
            )
        claim_is_active = bool(
            tracking.active_attempt_token
            and tracking.claim_expires_at is not None
            and tracking.claim_expires_at > now
        )
        if (
            tracking.next_poll_at is not None
            and tracking.next_poll_at + timedelta(minutes=3) <= now
            and not claim_is_active
        ):
            candidates.append(
                {
                    "alert_type": RaceLiveAlertType.QUEUE_AGE,
                    "scope_type": "event",
                    "scope_key": str(event.pk),
                    "reference_version": (
                        f"poll:{tracking.next_poll_at.isoformat()}"
                    ),
                    "deadline_at": tracking.next_poll_at
                    + timedelta(minutes=3),
                    "details": {
                        "event_id": event.pk,
                        "event_name": (
                            event.chinese_name or event.original_name
                        ),
                        "region": event.country_region,
                    },
                }
            )
        checkpoint = (
            tracking.checkpoint_payload
            if isinstance(tracking.checkpoint_payload, dict)
            else {}
        )
        pagination = checkpoint.get("pagination")
        pagination_category = (
            pagination.get("category")
            if isinstance(pagination, dict)
            else None
        )
        if pagination_category in {
            "deadline_exceeded",
            "incomplete",
            "metadata_drift",
            "overflow",
        }:
            checkpoint_digest = hashlib.sha256(
                json.dumps(
                    checkpoint,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            candidates.append(
                {
                    "alert_type": RaceLiveAlertType.PAGINATION_OVERFLOW,
                    "scope_type": "event",
                    "scope_key": str(event.pk),
                    "reference_version": (
                        f"checkpoint:{checkpoint_digest}"
                    ),
                    "deadline_at": now,
                    "details": {
                        "event_id": event.pk,
                        "event_name": (
                            event.chinese_name or event.original_name
                        ),
                        "region": event.country_region,
                        "reason": str(checkpoint.get("reason", ""))[:128],
                        "pagination_category": pagination_category,
                    },
                }
            )

    official_incidents = (
        RaceLiveOfficialVerificationIncident.objects.select_related("event")
        .filter(
            status=RaceLiveOfficialVerificationIncidentStatus.OPEN,
            deadline_at__lte=now,
            event__country_region__in=regions,
        )
        .order_by("event_id", "pk")
    )[:100]
    for incident in official_incidents:
        candidates.append(
            {
                "alert_type": RaceLiveAlertType.OFFICIAL_OVERDUE,
                "scope_type": "event",
                "scope_key": str(incident.event_id),
                "reference_version": (
                    f"official:{incident.pk}:"
                    f"{incident.official_route_version}"
                ),
                "deadline_at": incident.deadline_at,
                "details": {
                    "event_id": incident.event_id,
                    "event_name": (
                        incident.event.chinese_name
                        or incident.event.original_name
                    ),
                    "region": incident.event.country_region,
                    "official_incident_id": incident.pk,
                    "official_route": incident.official_route,
                },
            }
        )

    for budget in RaceLiveHostBudget.objects.filter(
        circuit_open_until__gt=now
    ).order_by("host")[:100]:
        candidates.append(
            {
                "alert_type": RaceLiveAlertType.HOST_CIRCUIT,
                "scope_type": "host",
                "scope_key": budget.host,
                "reference_version": (
                    f"circuit:{budget.circuit_open_until.isoformat()}"
                ),
                "deadline_at": now,
                "details": {
                    "host": budget.host,
                    "circuit_open_until": budget.circuit_open_until.isoformat(),
                },
            }
        )

    staged: list[int] = []
    with transaction.atomic():
        for candidate in candidates:
            dedupe_key = hashlib.sha256(
                json.dumps(
                    {
                        "alert_type": candidate["alert_type"],
                        "scope_type": candidate["scope_type"],
                        "scope_key": candidate["scope_key"],
                        "reference_version": candidate["reference_version"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            incident, created = RaceLiveAlertIncident.objects.get_or_create(
                dedupe_key=dedupe_key,
                defaults={
                    **candidate,
                    "status": RaceLiveAlertIncidentStatus.OPEN,
                    "opened_at": now,
                    "last_seen_at": now,
                    "next_attempt_at": now,
                },
            )
            if not created and incident.status not in {
                RaceLiveAlertIncidentStatus.SENT,
                RaceLiveAlertIncidentStatus.RESOLVED,
            }:
                incident.last_seen_at = now
                incident.details = candidate["details"]
                incident.save(
                    update_fields=(
                        "last_seen_at",
                        "details",
                        "updated_at",
                    )
                )
            if incident.status not in {
                RaceLiveAlertIncidentStatus.SENT,
                RaceLiveAlertIncidentStatus.RESOLVED,
            }:
                staged.append(incident.pk)
    return tuple(staged)


def claim_race_live_alert_delivery(
    *,
    incident_id: int,
    now: datetime,
    lease_seconds: int = 300,
) -> RaceLiveAlertDeliveryClaimDecision:
    if (
        isinstance(incident_id, bool)
        or not isinstance(incident_id, int)
        or incident_id <= 0
        or not isinstance(now, datetime)
        or timezone.is_naive(now)
        or isinstance(lease_seconds, bool)
        or not isinstance(lease_seconds, int)
        or lease_seconds < 1
        or lease_seconds > 900
    ):
        return RaceLiveAlertDeliveryClaimDecision(False, "invalid_input")
    with transaction.atomic():
        incident = (
            RaceLiveAlertIncident.objects.select_for_update()
            .filter(pk=incident_id)
            .first()
        )
        if incident is None:
            return RaceLiveAlertDeliveryClaimDecision(
                False, "incident_missing"
            )
        if incident.status in {
            RaceLiveAlertIncidentStatus.SENT,
            RaceLiveAlertIncidentStatus.RESOLVED,
        }:
            return RaceLiveAlertDeliveryClaimDecision(
                False, "incident_terminal"
            )
        if (
            incident.status == RaceLiveAlertIncidentStatus.SENDING
            and incident.delivery_lease_expires_at is not None
            and incident.delivery_lease_expires_at > now
        ):
            return RaceLiveAlertDeliveryClaimDecision(
                False, "delivery_lease_active"
            )
        if (
            incident.next_attempt_at is not None
            and incident.next_attempt_at > now
        ):
            return RaceLiveAlertDeliveryClaimDecision(
                False, "delivery_not_due"
            )
        if incident.delivery_attempts >= 4:
            return RaceLiveAlertDeliveryClaimDecision(
                False, "delivery_attempts_exhausted"
            )
        token = uuid.uuid4().hex
        incident.status = RaceLiveAlertIncidentStatus.SENDING
        incident.delivery_attempts += 1
        incident.delivery_token = token
        incident.delivery_lease_expires_at = now + timedelta(
            seconds=lease_seconds
        )
        incident.last_error_code = ""
        incident.save(
            update_fields=(
                "status",
                "delivery_attempts",
                "delivery_token",
                "delivery_lease_expires_at",
                "last_error_code",
                "updated_at",
            )
        )
        return RaceLiveAlertDeliveryClaimDecision(
            True,
            "delivery_claimed",
            delivery_token=token,
            incident_id=incident.pk,
        )


def complete_race_live_alert_delivery(
    *,
    incident_id: int,
    delivery_token: str,
    now: datetime,
    delivered: bool,
    error_code: str = "",
) -> RaceLiveAlertDeliveryCompletionDecision:
    if (
        isinstance(incident_id, bool)
        or not isinstance(incident_id, int)
        or incident_id <= 0
        or not isinstance(delivery_token, str)
        or not delivery_token
        or delivery_token != delivery_token.strip()
        or len(delivery_token) > 64
        or not isinstance(now, datetime)
        or timezone.is_naive(now)
        or not isinstance(delivered, bool)
        or not isinstance(error_code, str)
        or len(error_code) > 64
    ):
        return RaceLiveAlertDeliveryCompletionDecision(False, "invalid_input")
    with transaction.atomic():
        incident = (
            RaceLiveAlertIncident.objects.select_for_update()
            .filter(pk=incident_id)
            .first()
        )
        if incident is None:
            return RaceLiveAlertDeliveryCompletionDecision(
                False, "incident_missing"
            )
        if (
            incident.status != RaceLiveAlertIncidentStatus.SENDING
            or incident.delivery_token != delivery_token
        ):
            return RaceLiveAlertDeliveryCompletionDecision(
                False, "delivery_token_mismatch"
            )
        incident.delivery_token = ""
        incident.delivery_lease_expires_at = None
        if delivered:
            incident.status = RaceLiveAlertIncidentStatus.SENT
            incident.alert_sent_at = now
            incident.next_attempt_at = None
            incident.last_error_code = ""
            reason = "delivery_completed"
        else:
            incident.status = RaceLiveAlertIncidentStatus.FAILED
            retry_delay = calculate_race_live_alert_retry_delay(
                attempt_number=incident.delivery_attempts
            )
            incident.next_attempt_at = (
                now + retry_delay if retry_delay is not None else None
            )
            incident.last_error_code = error_code or "delivery_failed"
            reason = (
                "delivery_retry_scheduled"
                if retry_delay is not None
                else "delivery_failed_terminal"
            )
        incident.save(
            update_fields=(
                "status",
                "delivery_token",
                "delivery_lease_expires_at",
                "alert_sent_at",
                "next_attempt_at",
                "last_error_code",
                "updated_at",
            )
        )
        return RaceLiveAlertDeliveryCompletionDecision(True, reason)


def complete_race_event_live_checkpoint(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    now: datetime,
    success: bool,
    next_poll_at: datetime | None,
    checkpoint_payload: dict,
    observation_sha256: str,
) -> RaceEventLiveCheckpointDecision:
    """Persist one claimed live attempt using owner and claim CAS guards."""
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
        return RaceEventLiveCheckpointDecision(False, "invalid_event")
    if (
        isinstance(expected_owner_generation, bool)
        or not isinstance(expected_owner_generation, int)
        or expected_owner_generation < 0
    ):
        return RaceEventLiveCheckpointDecision(False, "invalid_owner_generation")
    if (
        isinstance(expected_claim_generation, bool)
        or not isinstance(expected_claim_generation, int)
        or expected_claim_generation < 0
    ):
        return RaceEventLiveCheckpointDecision(False, "invalid_claim_generation")
    if (
        not isinstance(attempt_token, str)
        or not attempt_token
        or len(attempt_token) > 64
    ):
        return RaceEventLiveCheckpointDecision(False, "invalid_attempt_token")
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return RaceEventLiveCheckpointDecision(False, "invalid_now")
    if not isinstance(success, bool):
        return RaceEventLiveCheckpointDecision(False, "invalid_success")
    if next_poll_at is not None and (
        not isinstance(next_poll_at, datetime) or timezone.is_naive(next_poll_at)
    ):
        return RaceEventLiveCheckpointDecision(False, "invalid_next_poll_at")
    if not isinstance(checkpoint_payload, dict):
        return RaceEventLiveCheckpointDecision(False, "invalid_checkpoint")
    try:
        json.dumps(checkpoint_payload, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return RaceEventLiveCheckpointDecision(False, "invalid_checkpoint")
    if not isinstance(observation_sha256, str) or (
        observation_sha256 and not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
            observation_sha256
        )
    ):
        return RaceEventLiveCheckpointDecision(False, "invalid_observation_digest")
    if success and not observation_sha256:
        return RaceEventLiveCheckpointDecision(False, "invalid_observation_digest")

    with transaction.atomic():
        try:
            control = RaceEventProjectionControl.objects.select_for_update().get(
                event_id=event_id
            )
        except RaceEventProjectionControl.DoesNotExist:
            return RaceEventLiveCheckpointDecision(False, "control_missing")

        try:
            tracking = RaceEventLiveTracking.objects.select_for_update().get(
                event_id=event_id
            )
        except RaceEventLiveTracking.DoesNotExist:
            return RaceEventLiveCheckpointDecision(False, "tracking_missing")

        if (
            control.write_owner != RaceEventProjectionWriteOwner.LIVE
            or control.owner_generation != expected_owner_generation
        ):
            return RaceEventLiveCheckpointDecision(False, "owner_mismatch")
        if (
            tracking.active_attempt_token != attempt_token
            or tracking.claim_generation != expected_claim_generation
        ):
            return RaceEventLiveCheckpointDecision(False, "claim_mismatch")
        if tracking.claim_expires_at is None:
            return RaceEventLiveCheckpointDecision(False, "claim_missing_expiry")
        if tracking.claim_expires_at <= now:
            return RaceEventLiveCheckpointDecision(False, "claim_expired")

        tracking.next_poll_at = next_poll_at
        tracking.checkpoint_payload = checkpoint_payload
        tracking.active_attempt_token = ""
        tracking.claim_expires_at = None
        tracking.lock_version += 1
        update_fields = [
            "next_poll_at",
            "checkpoint_payload",
            "active_attempt_token",
            "claim_expires_at",
            "lock_version",
            "updated_at",
        ]
        if success:
            tracking.last_success_at = now
            tracking.last_observation_hash = observation_sha256
            tracking.consecutive_failures = 0
            update_fields.extend(
                (
                    "last_success_at",
                    "last_observation_hash",
                    "consecutive_failures",
                )
            )
        else:
            tracking.consecutive_failures += 1
            update_fields.append("consecutive_failures")
        tracking.save(update_fields=update_fields)
        return RaceEventLiveCheckpointDecision(True, "checkpoint_applied")


def checkpoint_or_promote_race_event_live_pre_off(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    now: datetime,
) -> RaceEventLivePreOffDecision:
    """Release a pre-off claim or promote it at off time under owner/claim CAS."""
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
        return RaceEventLivePreOffDecision(False, "invalid_event")
    if (
        isinstance(expected_owner_generation, bool)
        or not isinstance(expected_owner_generation, int)
        or expected_owner_generation < 0
    ):
        return RaceEventLivePreOffDecision(False, "invalid_owner_generation")
    if (
        isinstance(expected_claim_generation, bool)
        or not isinstance(expected_claim_generation, int)
        or expected_claim_generation < 0
    ):
        return RaceEventLivePreOffDecision(False, "invalid_claim_generation")
    if (
        not isinstance(attempt_token, str)
        or not attempt_token
        or len(attempt_token) > 64
    ):
        return RaceEventLivePreOffDecision(False, "invalid_attempt_token")
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return RaceEventLivePreOffDecision(False, "invalid_now")

    with transaction.atomic():
        try:
            control = RaceEventProjectionControl.objects.select_for_update().get(
                event_id=event_id
            )
            tracking = RaceEventLiveTracking.objects.select_for_update().get(
                event_id=event_id
            )
            event = RaceEvent.objects.select_for_update().get(pk=event_id)
        except RaceEventProjectionControl.DoesNotExist:
            return RaceEventLivePreOffDecision(False, "control_missing")
        except RaceEventLiveTracking.DoesNotExist:
            return RaceEventLivePreOffDecision(False, "tracking_missing")
        except RaceEvent.DoesNotExist:
            return RaceEventLivePreOffDecision(False, "event_missing")

        if (
            control.write_owner != RaceEventProjectionWriteOwner.LIVE
            or control.owner_generation != expected_owner_generation
        ):
            return RaceEventLivePreOffDecision(False, "owner_mismatch")
        if (
            tracking.active_attempt_token != attempt_token
            or tracking.claim_generation != expected_claim_generation
        ):
            return RaceEventLivePreOffDecision(False, "claim_mismatch")
        if tracking.claim_expires_at is None:
            return RaceEventLivePreOffDecision(False, "claim_missing_expiry")
        if tracking.claim_expires_at <= now:
            return RaceEventLivePreOffDecision(False, "claim_expired")
        if tracking.state == RaceEventLiveState.AWAITING_RESULT:
            return RaceEventLivePreOffDecision(True, "already_awaiting", True)
        if tracking.state != RaceEventLiveState.RACECARD_READY:
            return RaceEventLivePreOffDecision(False, "state_mismatch")
        if event.race_datetime is None or timezone.is_naive(event.race_datetime):
            return RaceEventLivePreOffDecision(False, "race_datetime_missing")

        if now >= event.race_datetime:
            tracking.state = RaceEventLiveState.AWAITING_RESULT
            tracking.next_poll_at = now
            tracking.lock_version += 1
            tracking.save(
                update_fields=(
                    "state",
                    "next_poll_at",
                    "lock_version",
                    "updated_at",
                )
            )
            return RaceEventLivePreOffDecision(True, "promoted", True)

        next_poll_at = calculate_race_live_next_poll_at(
            off_time=event.race_datetime,
            now=now,
            state=RaceEventLiveState.RACECARD_READY,
        )
        tracking.next_poll_at = min(
            next_poll_at or event.race_datetime,
            event.race_datetime,
        )
        tracking.checkpoint_payload = {"status": "pre_off_wait"}
        tracking.active_attempt_token = ""
        tracking.claim_expires_at = None
        tracking.lock_version += 1
        tracking.save(
            update_fields=(
                "next_poll_at",
                "checkpoint_payload",
                "active_attempt_token",
                "claim_expires_at",
                "lock_version",
                "updated_at",
            )
        )
        return RaceEventLivePreOffDecision(True, "pre_off_wait")


def calculate_race_live_next_poll_at(
    *,
    off_time: datetime,
    now: datetime,
    state: str,
) -> datetime | None:
    """Return the next bounded poll time for a tracked race, or stop polling."""
    if (
        not isinstance(off_time, datetime)
        or timezone.is_naive(off_time)
        or not isinstance(now, datetime)
        or timezone.is_naive(now)
        or not isinstance(state, str)
        or state not in RACE_LIVE_STATES
    ):
        return None

    if state == "corrected_result":
        return None

    pre_race_states = {"scheduled", "racecard_ready", "awaiting_result"}
    if now < off_time:
        if state not in pre_race_states:
            return None

        twenty_four_hours_before = off_time - timedelta(hours=24)
        two_hours_before = off_time - timedelta(hours=2)
        thirty_minutes_before = off_time - timedelta(minutes=30)
        if now < twenty_four_hours_before:
            return twenty_four_hours_before
        if now < two_hours_before:
            return min(now + timedelta(hours=1), two_hours_before)
        if now < thirty_minutes_before:
            return min(now + timedelta(minutes=15), thirty_minutes_before)
        return min(now + timedelta(minutes=5), off_time)

    if state in {"scheduled", "racecard_ready"}:
        return None
    if state == "awaiting_result":
        return now + timedelta(minutes=3)

    two_hours_after = off_time + timedelta(hours=2)
    if state == "provisional_result" and now < two_hours_after:
        return min(now + timedelta(minutes=10), two_hours_after)

    for offset in (timedelta(hours=24), timedelta(hours=72), timedelta(days=7)):
        probe_at = off_time + offset
        if probe_at > now:
            return probe_at
    return None


def resolve_race_source_network_permission(
    *,
    mode: str,
    terms_status: str,
    automation_allowed: bool,
    proof_network_allowed: bool,
    valid_until: datetime | None,
    evidence_sha256: str,
    registry_digest: str,
    expected_registry_digest: str,
    manifest_approved: bool,
    request_budget: int,
    historical_handoff_complete: bool,
    now: datetime | None,
) -> RaceSourceNetworkPermissionDecision:
    """Resolve source-network permission from explicit fail-closed gates."""
    if mode == "offline":
        return RaceSourceNetworkPermissionDecision(True, "offline_fixture")
    if not isinstance(mode, str) or mode not in {"proof", "shadow", "production"}:
        return RaceSourceNetworkPermissionDecision(False, "invalid_mode")
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return RaceSourceNetworkPermissionDecision(False, "invalid_now")
    if historical_handoff_complete is not True:
        return RaceSourceNetworkPermissionDecision(False, "historical_handoff_incomplete")
    if terms_status != "approved":
        return RaceSourceNetworkPermissionDecision(False, "terms_not_approved")
    if not isinstance(valid_until, datetime) or timezone.is_naive(valid_until):
        return RaceSourceNetworkPermissionDecision(False, "invalid_terms_expiry")
    if valid_until <= now:
        return RaceSourceNetworkPermissionDecision(False, "terms_expired")
    if not isinstance(evidence_sha256, str) or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
        evidence_sha256
    ):
        return RaceSourceNetworkPermissionDecision(False, "invalid_evidence_digest")
    if (
        not isinstance(registry_digest, str)
        or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(registry_digest)
        or not isinstance(expected_registry_digest, str)
        or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(expected_registry_digest)
    ):
        return RaceSourceNetworkPermissionDecision(False, "invalid_registry_digest")
    if registry_digest != expected_registry_digest:
        return RaceSourceNetworkPermissionDecision(False, "registry_digest_mismatch")

    if mode == "proof":
        if proof_network_allowed is not True:
            return RaceSourceNetworkPermissionDecision(False, "proof_network_not_allowed")
        if manifest_approved is not True:
            return RaceSourceNetworkPermissionDecision(False, "manifest_not_approved")
        if (
            isinstance(request_budget, bool)
            or not isinstance(request_budget, int)
            or request_budget <= 0
        ):
            return RaceSourceNetworkPermissionDecision(False, "invalid_request_budget")
        return RaceSourceNetworkPermissionDecision(True, "proof_allowed")

    if automation_allowed is not True:
        return RaceSourceNetworkPermissionDecision(False, "automation_not_allowed")
    return RaceSourceNetworkPermissionDecision(True, "automation_allowed")


def transfer_race_event_projection_owner(
    *,
    event_id: int,
    expected_owner: str,
    expected_generation: int,
    new_owner: str,
    manifest_sha256: str,
    changed_by=None,
) -> RaceEventProjectionControl:
    """Transfer projection ownership using a locked compare-and-swap."""
    valid_owners = RaceEventProjectionWriteOwner.values
    if expected_owner not in valid_owners or new_owner not in valid_owners:
        raise ValueError("projection owner is invalid")
    if isinstance(expected_generation, bool) or not isinstance(expected_generation, int):
        raise ValueError("projection owner generation must be a non-negative integer")
    if expected_generation < 0:
        raise ValueError("projection owner generation must be a non-negative integer")
    if not isinstance(manifest_sha256, str) or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
        manifest_sha256
    ):
        raise ValueError("projection owner manifest must be a lowercase SHA-256 digest")

    with transaction.atomic():
        try:
            control = RaceEventProjectionControl.objects.select_for_update().get(
                event_id=event_id
            )
        except RaceEventProjectionControl.DoesNotExist as exc:
            raise RaceEventProjectionOwnershipConflict(
                "projection control does not exist"
            ) from exc

        if (
            control.write_owner == new_owner
            and control.owner_manifest_sha256 == manifest_sha256
            and control.owner_generation == expected_generation + 1
        ):
            return control

        if (
            control.write_owner != expected_owner
            or control.owner_generation != expected_generation
        ):
            raise RaceEventProjectionOwnershipConflict(
                "projection ownership compare-and-swap conflict"
            )

        control.write_owner = new_owner
        control.owner_generation = expected_generation + 1
        control.owner_manifest_sha256 = manifest_sha256
        control.owner_changed_at = timezone.now()
        control.owner_changed_by = changed_by
        control.save(
            update_fields=(
                "write_owner",
                "owner_generation",
                "owner_manifest_sha256",
                "owner_changed_at",
                "owner_changed_by",
                "updated_at",
            )
        )
        return control


def allocate_race_event_revision(
    *,
    event_id: int,
    kind: str,
    phase: str,
    content_sha256: str,
    primary_observation_id: int | None = None,
    expected_owner: str,
    expected_generation: int,
    source_authority: str = "",
    decision_reason: str = "",
    applied_by=None,
) -> RaceEventRevision:
    """Allocate one immutable revision number under projection ownership."""
    if kind not in RaceEventRevisionKind.values:
        raise ValueError("race event revision kind is invalid")
    allowed_phases = {
        RaceEventRevisionKind.RACECARD: {RaceResultPhase.RACECARD},
        RaceEventRevisionKind.RESULT: {
            RaceResultPhase.PROVISIONAL,
            RaceResultPhase.OFFICIAL,
            RaceResultPhase.CORRECTED,
            RaceResultPhase.UNKNOWN,
        },
    }
    if phase not in allowed_phases[kind]:
        raise ValueError("race event revision phase is invalid for its kind")
    if not isinstance(content_sha256, str) or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
        content_sha256
    ):
        raise ValueError("race event revision content hash must be a lowercase SHA-256 digest")
    if expected_owner not in RaceEventProjectionWriteOwner.values:
        raise ValueError("projection owner is invalid")
    if isinstance(expected_generation, bool) or not isinstance(expected_generation, int):
        raise ValueError("projection owner generation must be a non-negative integer")
    if expected_generation < 0:
        raise ValueError("projection owner generation must be a non-negative integer")

    with transaction.atomic():
        try:
            control = RaceEventProjectionControl.objects.select_for_update().get(
                event_id=event_id
            )
        except RaceEventProjectionControl.DoesNotExist as exc:
            raise RaceEventProjectionOwnershipConflict(
                "projection control does not exist"
            ) from exc

        if (
            control.write_owner != expected_owner
            or control.owner_generation != expected_generation
        ):
            raise RaceEventProjectionOwnershipConflict(
                "projection ownership compare-and-swap conflict"
            )

        primary_observation = None
        if primary_observation_id is not None:
            try:
                primary_observation = RaceResultObservation.objects.select_related(
                    "source_identity"
                ).get(pk=primary_observation_id)
            except RaceResultObservation.DoesNotExist as exc:
                raise ValueError("primary race result observation does not exist") from exc
            if primary_observation.source_identity.event_id != event_id:
                raise ValueError("primary observation belongs to another race event")
            if primary_observation.result_phase != phase:
                raise ValueError("primary observation phase does not match revision phase")

        existing = RaceEventRevision.objects.filter(
            event_id=event_id,
            kind=kind,
            phase=phase,
            content_sha256=content_sha256,
        ).first()
        if existing is not None:
            return existing

        if kind == RaceEventRevisionKind.RACECARD:
            counter_field = "next_racecard_revision_no"
        else:
            counter_field = "next_result_revision_no"
        revision_no = getattr(control, counter_field)
        if revision_no < 1:
            raise RaceEventProjectionOwnershipConflict(
                "projection revision counter is invalid"
            )

        revision = RaceEventRevision.objects.create(
            event_id=event_id,
            kind=kind,
            revision_no=revision_no,
            phase=phase,
            content_sha256=content_sha256,
            source_authority=source_authority,
            decision_reason=decision_reason,
            primary_observation=primary_observation,
            applied_by=applied_by,
        )
        setattr(control, counter_field, revision_no + 1)
        control.save(update_fields=(counter_field, "updated_at"))
        return revision


def resolve_race_live_mode(
    *,
    global_mode: str | None,
    region_mode: str | None = None,
    source_mode: str | None = None,
    event_mode: str | None = None,
    terms_mode: str | None = None,
    event_allowed: bool = False,
) -> str:
    """Resolve the effective live publishing mode using fail-closed caps."""
    if (
        event_allowed is not True
        or global_mode not in RACE_LIVE_MODE_ORDER
        or terms_mode not in RACE_LIVE_MODE_ORDER
    ):
        return "off"

    configured_modes = (global_mode, region_mode, source_mode, event_mode, terms_mode)
    if any(mode is not None and mode not in RACE_LIVE_MODE_ORDER for mode in configured_modes):
        return "off"

    effective_rank = min(
        RACE_LIVE_MODE_RANK[mode]
        for mode in configured_modes
        if mode is not None
    )
    return RACE_LIVE_MODE_ORDER[effective_rank]


def resolve_race_live_publication_policy(
    *,
    event_id: int,
    source_identity_id: int,
    now: datetime,
) -> RaceLivePublicationPolicyDecision:
    """Resolve persisted live-publication caps without mutating database state."""

    def reject(
        reason: str,
        *,
        policy_versions: tuple[tuple[str, str, int], ...] = (),
        allowlist_version: int = 0,
        registry_digest: str = "",
        coverage_proof_digest: str = "",
    ) -> RaceLivePublicationPolicyDecision:
        return RaceLivePublicationPolicyDecision(
            allowed=False,
            effective_mode=RaceLivePublicationMode.OFF,
            reason=reason,
            policy_versions=policy_versions,
            allowlist_version=allowlist_version,
            registry_digest=registry_digest,
            coverage_proof_digest=coverage_proof_digest,
        )

    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
        return reject("invalid_event_id")
    if (
        isinstance(source_identity_id, bool)
        or not isinstance(source_identity_id, int)
        or source_identity_id <= 0
    ):
        return reject("invalid_source_identity_id")
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return reject("invalid_now")

    try:
        event = RaceEvent.objects.get(pk=event_id)
    except RaceEvent.DoesNotExist:
        return reject("event_missing")
    try:
        source = RaceResultSourceIdentity.objects.get(pk=source_identity_id)
    except RaceResultSourceIdentity.DoesNotExist:
        return reject("source_identity_missing")
    if source.event_id != event.pk:
        return reject("source_event_mismatch")
    if source.review_status != RaceLiveReviewStatus.APPROVED:
        return reject("source_not_approved")
    if source.terms_status != RaceSourceTermsStatus.APPROVED:
        return reject("terms_not_approved")
    if source.automation_allowed is not True:
        return reject("automation_not_allowed")
    if (
        not isinstance(source.valid_until, datetime)
        or timezone.is_naive(source.valid_until)
        or source.valid_until <= now
    ):
        return reject("source_expired")
    if (
        not isinstance(source.registry_digest, str)
        or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
            source.registry_digest
        )
    ):
        return reject("invalid_registry_digest")

    policy_lookups = (
        ("global", "global", "global_policy_missing"),
        ("region", event.country_region, "region_policy_missing"),
        ("source", source.source_key, "source_policy_missing"),
        ("event", str(event.pk), "event_policy_missing"),
    )
    policies: list[RaceLivePublicationPolicy] = []
    for scope_type, scope_key, missing_reason in policy_lookups:
        policy = RaceLivePublicationPolicy.objects.filter(
            scope_type=scope_type,
            scope_key=scope_key,
        ).first()
        if policy is None:
            return reject(missing_reason)
        policies.append(policy)

    policy_versions = tuple(
        (policy.scope_type, policy.scope_key, policy.version)
        for policy in policies
    )
    if any(policy.mode == RaceLivePublicationMode.OFF for policy in policies):
        return reject(
            "policy_off",
            policy_versions=policy_versions,
            registry_digest=source.registry_digest,
        )
    if any(policy.mode not in RACE_LIVE_MODE_ORDER for policy in policies):
        return reject(
            "invalid_policy_mode",
            policy_versions=policy_versions,
            registry_digest=source.registry_digest,
        )

    allowlist = RaceLiveEventPublicationAllowlist.objects.filter(
        event_id=event.pk,
        source_key=source.source_key,
    ).first()
    if allowlist is None:
        return reject(
            "event_allowlist_missing",
            policy_versions=policy_versions,
            registry_digest=source.registry_digest,
        )
    if allowlist.enabled is not True:
        return reject(
            "event_not_allowlisted",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )
    if allowlist.max_mode == RaceLivePublicationMode.OFF:
        return reject(
            "policy_off",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )
    if allowlist.max_mode not in RACE_LIVE_MODE_ORDER:
        return reject(
            "invalid_allowlist_mode",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )

    for policy in policies:
        if (
            not isinstance(policy.valid_until, datetime)
            or timezone.is_naive(policy.valid_until)
            or policy.valid_until <= now
        ):
            return reject(
                "policy_expired",
                policy_versions=policy_versions,
                allowlist_version=allowlist.version,
                registry_digest=source.registry_digest,
                coverage_proof_digest=allowlist.coverage_proof_digest,
            )
        if policy.registry_digest != source.registry_digest:
            return reject(
                "registry_digest_mismatch",
                policy_versions=policy_versions,
                allowlist_version=allowlist.version,
                registry_digest=source.registry_digest,
                coverage_proof_digest=allowlist.coverage_proof_digest,
            )

    if (
        not isinstance(allowlist.coverage_proof_digest, str)
        or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
            allowlist.coverage_proof_digest
        )
    ):
        return reject(
            "invalid_coverage_digest",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )
    if any(
        policy.coverage_proof_digest != allowlist.coverage_proof_digest
        for policy in policies
    ):
        return reject(
            "coverage_digest_mismatch",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )

    if (
        not isinstance(allowlist.official_verification_route, str)
        or not allowlist.official_verification_route.strip()
        or allowlist.official_verification_route.strip()
        != allowlist.official_verification_route
        or not isinstance(
            allowlist.official_verification_route_version,
            str,
        )
        or not allowlist.official_verification_route_version.strip()
        or allowlist.official_verification_route_version.strip()
        != allowlist.official_verification_route_version
    ):
        return reject(
            "official_route_missing",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )
    if (
        not isinstance(allowlist.official_verification_valid_until, datetime)
        or timezone.is_naive(allowlist.official_verification_valid_until)
        or allowlist.official_verification_valid_until <= now
    ):
        return reject(
            "official_route_expired",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )

    effective_rank = min(
        [
            *(RACE_LIVE_MODE_RANK[policy.mode] for policy in policies),
            RACE_LIVE_MODE_RANK[allowlist.max_mode],
        ]
    )
    effective_mode = RACE_LIVE_MODE_ORDER[effective_rank]
    allowed = effective_mode in {
        RaceLivePublicationMode.PROVISIONAL_PUBLIC,
        RaceLivePublicationMode.OFFICIAL_PUBLIC,
    }
    if allowed:
        if (
            not isinstance(
                allowlist.official_verification_contract_digest,
                str,
            )
            or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
                allowlist.official_verification_contract_digest
            )
        ):
            return reject(
                "official_route_contract_digest_invalid",
                policy_versions=policy_versions,
                allowlist_version=allowlist.version,
                registry_digest=source.registry_digest,
                coverage_proof_digest=allowlist.coverage_proof_digest,
            )
        if (
            not isinstance(allowlist.official_terms_evidence_digest, str)
            or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
                allowlist.official_terms_evidence_digest
            )
        ):
            return reject(
                "official_terms_evidence_digest_invalid",
                policy_versions=policy_versions,
                allowlist_version=allowlist.version,
                registry_digest=source.registry_digest,
                coverage_proof_digest=allowlist.coverage_proof_digest,
            )
    return RaceLivePublicationPolicyDecision(
        allowed=allowed,
        effective_mode=effective_mode,
        reason="publication_allowed" if allowed else "shadow_only",
        policy_versions=policy_versions,
        allowlist_version=allowlist.version,
        registry_digest=source.registry_digest,
        coverage_proof_digest=allowlist.coverage_proof_digest,
    )


def _resolve_race_live_official_authorization_from_loaded_rows(
    *,
    event: RaceEvent | None,
    observation: RaceResultObservation | None,
    authorization: RaceLiveOfficialPublicationAuthorization | None,
    tra_source: RaceResultSourceIdentity | None,
    allowlist: RaceLiveEventPublicationAllowlist | None,
    policy_by_scope: dict[
        tuple[str, str],
        RaceLivePublicationPolicy,
    ],
    phase: str,
    now: datetime,
) -> RaceLiveOfficialAuthorizationDecision:
    def reject(reason: str) -> RaceLiveOfficialAuthorizationDecision:
        return RaceLiveOfficialAuthorizationDecision(False, reason)

    if event is None or observation is None or authorization is None:
        return reject("official_authorization_baseline_missing")
    event_id = event.pk
    source = observation.source_identity
    if source.event_id != event_id or observation.result_phase != phase:
        return reject("official_observation_mismatch")
    if (
        source.result_authority != RaceResultSourceAuthority.OFFICIAL
        or source.review_status != RaceLiveReviewStatus.APPROVED
        or source.terms_status != RaceSourceTermsStatus.MANUAL
        or source.automation_allowed is not False
    ):
        return reject("official_source_not_manual_approved")
    if (
        source.valid_until is None
        or timezone.is_naive(source.valid_until)
        or source.valid_until <= now
    ):
        return reject("official_source_expired")
    if authorization.enabled is not True:
        return reject("official_authorization_disabled")
    if (
        authorization.valid_until is None
        or timezone.is_naive(authorization.valid_until)
        or authorization.valid_until <= now
    ):
        return reject("official_authorization_expired")
    if (
        phase == RaceResultPhase.CORRECTED
        and authorization.max_phase != RaceResultPhase.CORRECTED
    ):
        return reject("official_phase_not_authorized")
    if authorization.max_phase not in {
        RaceResultPhase.OFFICIAL,
        RaceResultPhase.CORRECTED,
    }:
        return reject("official_phase_not_authorized")

    if (
        tra_source is None
        or tra_source.review_status != RaceLiveReviewStatus.APPROVED
        or tra_source.terms_status != RaceSourceTermsStatus.APPROVED
        or tra_source.automation_allowed is not True
        or allowlist is None
        or allowlist.enabled is not True
    ):
        return reject("provisional_policy_baseline_missing")
    if (
        tra_source.valid_until is None
        or timezone.is_naive(tra_source.valid_until)
        or tra_source.valid_until <= now
    ):
        return reject("provisional_source_expired")
    policy_lookups = (
        (RaceLivePublicationScopeType.GLOBAL, "global"),
        (RaceLivePublicationScopeType.REGION, event.country_region),
        (RaceLivePublicationScopeType.SOURCE, "the_racing_api"),
        (RaceLivePublicationScopeType.EVENT, str(event_id)),
    )
    policies = []
    for scope_type, scope_key in policy_lookups:
        policy = policy_by_scope.get((scope_type, scope_key))
        if policy is None:
            return reject("official_coarse_policy_missing")
        if (
            policy.valid_until is None
            or timezone.is_naive(policy.valid_until)
            or policy.valid_until <= now
            or policy.registry_digest != tra_source.registry_digest
            or policy.coverage_proof_digest
            != allowlist.coverage_proof_digest
        ):
            return reject("official_coarse_policy_drift")
        policies.append(policy)
    for policy in policies:
        required_mode = (
            RaceLivePublicationMode.PROVISIONAL_PUBLIC
            if policy.scope_type == RaceLivePublicationScopeType.SOURCE
            else RaceLivePublicationMode.OFFICIAL_PUBLIC
        )
        if RACE_LIVE_MODE_RANK.get(policy.mode, -1) < RACE_LIVE_MODE_RANK[
            required_mode
        ]:
            return reject("official_coarse_policy_mode")

    if authorization.source_key != source.source_key:
        return reject("official_source_key_mismatch")
    if authorization.route != allowlist.official_verification_route:
        return reject("official_route_mismatch")
    if (
        authorization.route_version
        != allowlist.official_verification_route_version
    ):
        return reject("official_route_version_mismatch")
    if authorization.route_registry_digest != source.registry_digest:
        return reject("official_route_registry_mismatch")
    if (
        authorization.contract_digest
        != allowlist.official_verification_contract_digest
    ):
        return reject("official_contract_mismatch")
    if (
        authorization.terms_evidence_digest
        != allowlist.official_terms_evidence_digest
        or source.evidence_sha256 != authorization.terms_evidence_digest
    ):
        return reject("official_terms_mismatch")
    if (
        authorization.coverage_proof_digest
        != allowlist.coverage_proof_digest
    ):
        return reject("official_coverage_mismatch")
    if (
        allowlist.official_verification_valid_until is None
        or timezone.is_naive(
            allowlist.official_verification_valid_until
        )
        or allowlist.official_verification_valid_until <= now
    ):
        return reject("official_route_expired")

    try:
        marker = observation.official_marker_evidence
    except RaceLiveOfficialMarkerEvidence.DoesNotExist:
        return reject("official_marker_missing")
    contract = marker.contract
    if (
        contract.country_region != event.country_region
        or contract.source_key != source.source_key
        or contract.review_status != RaceLiveReviewStatus.APPROVED
        or contract.valid_until is None
        or timezone.is_naive(contract.valid_until)
        or contract.valid_until <= now
        or marker.marker_type not in contract.allowed_marker_types
        or marker.contract_digest != contract.contract_digest
        or marker.contract_digest != authorization.contract_digest
        or marker.parser_version != contract.parser_version
        or marker.parser_version != observation.parser_version
        or marker.raw_sha256 != observation.raw_sha256
    ):
        return reject("official_marker_contract_mismatch")
    return RaceLiveOfficialAuthorizationDecision(
        True,
        "official_route_authorized",
        authorization_version=authorization.version,
        route_registry_digest=authorization.route_registry_digest,
        coverage_proof_digest=authorization.coverage_proof_digest,
    )


def resolve_race_live_official_publication_authorization(
    *,
    event_id: int,
    observation_id: int,
    phase: str,
    now: datetime,
) -> RaceLiveOfficialAuthorizationDecision:
    """Authorize an existing manual official observation without network access."""

    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
        or isinstance(observation_id, bool)
        or not isinstance(observation_id, int)
        or observation_id <= 0
        or phase not in {
            RaceResultPhase.OFFICIAL,
            RaceResultPhase.CORRECTED,
        }
        or not isinstance(now, datetime)
        or timezone.is_naive(now)
    ):
        return RaceLiveOfficialAuthorizationDecision(False, "invalid_input")
    event = RaceEvent.objects.filter(pk=event_id).first()
    observation = (
        RaceResultObservation.objects.select_related(
            "source_identity",
            "official_marker_evidence__contract",
        )
        .filter(pk=observation_id)
        .first()
    )
    authorization = RaceLiveOfficialPublicationAuthorization.objects.filter(
        event_id=event_id
    ).first()
    tra_source = RaceResultSourceIdentity.objects.filter(
        event_id=event_id,
        source_key="the_racing_api",
    ).first()
    allowlist = RaceLiveEventPublicationAllowlist.objects.filter(
        event_id=event_id,
        source_key="the_racing_api",
    ).first()
    policy_by_scope: dict[
        tuple[str, str],
        RaceLivePublicationPolicy,
    ] = {}
    if event is not None:
        policy_by_scope = {
            (policy.scope_type, policy.scope_key): policy
            for policy in RaceLivePublicationPolicy.objects.filter(
                Q(
                    scope_type=RaceLivePublicationScopeType.GLOBAL,
                    scope_key="global",
                )
                | Q(
                    scope_type=RaceLivePublicationScopeType.REGION,
                    scope_key=event.country_region,
                )
                | Q(
                    scope_type=RaceLivePublicationScopeType.SOURCE,
                    scope_key="the_racing_api",
                )
                | Q(
                    scope_type=RaceLivePublicationScopeType.EVENT,
                    scope_key=str(event_id),
                )
            )
        }
    return _resolve_race_live_official_authorization_from_loaded_rows(
        event=event,
        observation=observation,
        authorization=authorization,
        tra_source=tra_source,
        allowlist=allowlist,
        policy_by_scope=policy_by_scope,
        phase=phase,
        now=now,
    )


def resolve_race_live_official_coarse_policy(
    *,
    event_id: int,
    now: datetime,
) -> RaceLivePublicationPolicyDecision:
    """Resolve official publication gates without granting TRA official authority."""

    tra_source = RaceResultSourceIdentity.objects.filter(
        event_id=event_id,
        source_key="the_racing_api",
    ).first()
    if tra_source is None:
        return RaceLivePublicationPolicyDecision(
            False,
            RaceLivePublicationMode.OFF,
            "tra_source_missing",
        )
    base = resolve_race_live_publication_policy(
        event_id=event_id,
        source_identity_id=tra_source.pk,
        now=now,
    )
    if base.allowed is not True:
        return base
    modes = {
        scope_type: mode
        for scope_type, mode in RaceLivePublicationPolicy.objects.filter(
            Q(
                scope_type=RaceLivePublicationScopeType.GLOBAL,
                scope_key="global",
            )
            | Q(
                scope_type=RaceLivePublicationScopeType.REGION,
                scope_key=tra_source.event.country_region,
            )
            | Q(
                scope_type=RaceLivePublicationScopeType.SOURCE,
                scope_key=tra_source.source_key,
            )
            | Q(
                scope_type=RaceLivePublicationScopeType.EVENT,
                scope_key=str(event_id),
            )
        ).values_list("scope_type", "mode")
    }
    if set(modes) != {
        RaceLivePublicationScopeType.GLOBAL,
        RaceLivePublicationScopeType.REGION,
        RaceLivePublicationScopeType.SOURCE,
        RaceLivePublicationScopeType.EVENT,
    }:
        return RaceLivePublicationPolicyDecision(
            False,
            RaceLivePublicationMode.OFF,
            "official_coarse_policy_missing",
            policy_versions=base.policy_versions,
            allowlist_version=base.allowlist_version,
            registry_digest=base.registry_digest,
            coverage_proof_digest=base.coverage_proof_digest,
        )
    if any(
        modes[scope_type] != RaceLivePublicationMode.OFFICIAL_PUBLIC
        for scope_type in (
            RaceLivePublicationScopeType.GLOBAL,
            RaceLivePublicationScopeType.REGION,
            RaceLivePublicationScopeType.EVENT,
        )
    ) or RACE_LIVE_MODE_RANK.get(
        modes[RaceLivePublicationScopeType.SOURCE], -1
    ) < RACE_LIVE_MODE_RANK[RaceLivePublicationMode.PROVISIONAL_PUBLIC]:
        return RaceLivePublicationPolicyDecision(
            False,
            base.effective_mode,
            "official_coarse_policy_insufficient",
            policy_versions=base.policy_versions,
            allowlist_version=base.allowlist_version,
            registry_digest=base.registry_digest,
            coverage_proof_digest=base.coverage_proof_digest,
        )
    return RaceLivePublicationPolicyDecision(
        True,
        RaceLivePublicationMode.OFFICIAL_PUBLIC,
        "official_coarse_policy_allowed",
        policy_versions=base.policy_versions,
        allowlist_version=base.allowlist_version,
        registry_digest=base.registry_digest,
        coverage_proof_digest=base.coverage_proof_digest,
    )


def validate_race_live_provisional_rollback_target(
    *,
    event_id: int,
    now: datetime,
    expected_provisional_revision_id: int | None = None,
    planned_policy_snapshot: dict[str, dict[str, Any]] | None = None,
    expected_allowlist_version: int | None = None,
    expected_publication_id: int | None = None,
    expected_tracking_lock_version: int | None = None,
    expected_current_revision_id: int | None = None,
) -> RaceLiveProvisionalRollbackDecision:
    """Validate the dedicated provisional pointer against immutable audit rows."""

    def reject(reason: str) -> RaceLiveProvisionalRollbackDecision:
        return RaceLiveProvisionalRollbackDecision(False, reason)

    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
        or not isinstance(now, datetime)
        or timezone.is_naive(now)
        or getattr(
            settings,
            "RACE_LIVE_SCHEDULER_ENABLED",
            False,
        )
        is not False
        or getattr(
            settings,
            "RACE_LIVE_MONITOR_ENABLED",
            False,
        )
        is not False
        or tuple(
            getattr(settings, "RACE_LIVE_ENABLED_REGIONS", ())
        )
        != ()
    ):
        return reject("invalid_input")
    control = (
        RaceEventProjectionControl.objects.select_related(
            "last_provisional_result_revision__primary_observation__source_identity"
        )
        .filter(event_id=event_id)
        .first()
    )
    tracking = RaceEventLiveTracking.objects.filter(event_id=event_id).first()
    if (
        tracking is None
        or tracking.tracking_enabled is not False
        or tracking.next_poll_at is not None
        or tracking.active_attempt_token != ""
        or tracking.claim_expires_at is not None
        or (
            expected_tracking_lock_version is not None
            and tracking.lock_version != expected_tracking_lock_version
        )
    ):
        return reject("rollback_tracking_fence_invalid")
    if control is None or control.last_provisional_result_revision_id is None:
        return reject("provisional_pointer_missing")
    if (
        expected_current_revision_id is not None
        and control.current_result_revision_id
        != expected_current_revision_id
    ):
        return reject("current_result_pointer_changed")
    revision = control.last_provisional_result_revision
    if (
        expected_provisional_revision_id is not None
        and revision.pk != expected_provisional_revision_id
    ):
        return reject("provisional_pointer_changed")
    if (
        revision.event_id != event_id
        or revision.kind != RaceEventRevisionKind.RESULT
        or revision.phase != RaceResultPhase.PROVISIONAL
        or revision.published_at is None
        or timezone.is_naive(revision.published_at)
    ):
        return reject("provisional_pointer_invalid")
    publication = RaceEventRevisionPublication.objects.filter(
        revision_id=revision.pk
    ).first()
    if (
        publication is None
        or (
            expected_publication_id is not None
            and publication.pk != expected_publication_id
        )
        or publication.published_at != revision.published_at
        or publication.authorization_kind != "provisional_policy"
        or publication.official_authorization_version != 0
    ):
        return reject("provisional_publication_audit_invalid")
    observation = revision.primary_observation
    if observation is None or observation.result_phase != RaceResultPhase.PROVISIONAL:
        return reject("provisional_observation_invalid")
    source = observation.source_identity
    if (
        source.event_id != event_id
        or source.source_key != "the_racing_api"
        or source.result_authority != RaceResultSourceAuthority.SUPPLEMENTAL
        or source.review_status != RaceLiveReviewStatus.APPROVED
        or source.terms_status != RaceSourceTermsStatus.APPROVED
        or source.automation_allowed is not True
        or source.valid_until is None
        or timezone.is_naive(source.valid_until)
        or source.valid_until <= now
    ):
        return reject("provisional_source_invalid")
    allowlist = RaceLiveEventPublicationAllowlist.objects.filter(
        event_id=event_id,
        source_key=source.source_key,
        enabled=True,
    ).first()
    if (
        allowlist is None
        or (
            expected_allowlist_version is not None
            and allowlist.version != expected_allowlist_version
        )
        or allowlist.coverage_proof_digest
        != publication.coverage_proof_digest
        or source.registry_digest != publication.registry_digest
        or allowlist.version != publication.allowlist_version
    ):
        return reject("provisional_allowlist_drift")
    if planned_policy_snapshot is not None:
        if not isinstance(planned_policy_snapshot, dict):
            return reject("planned_policy_snapshot_invalid")
        event = RaceEvent.objects.filter(pk=event_id).first()
        if event is None:
            return reject("event_missing")
        expected_scopes = (
            (RaceLivePublicationScopeType.GLOBAL, "global"),
            (RaceLivePublicationScopeType.REGION, event.country_region),
            (RaceLivePublicationScopeType.SOURCE, source.source_key),
            (RaceLivePublicationScopeType.EVENT, str(event_id)),
        )
        if set(planned_policy_snapshot) != {
            f"{scope_type}:{scope_key}"
            for scope_type, scope_key in expected_scopes
        }:
            return reject("planned_policy_scope_mismatch")
        actual_policy_states: list[str] = []
        restored_modes: list[str] = []
        for scope_type, scope_key in expected_scopes:
            key = f"{scope_type}:{scope_key}"
            expected = planned_policy_snapshot.get(key)
            policy = RaceLivePublicationPolicy.objects.filter(
                scope_type=scope_type,
                scope_key=scope_key,
            ).first()
            if (
                not isinstance(expected, dict)
                or set(expected) != {"maintenance", "restore"}
                or policy is None
            ):
                return reject("planned_policy_missing")
            maintenance = expected.get("maintenance")
            restore = expected.get("restore")
            if (
                not isinstance(maintenance, dict)
                or not isinstance(restore, dict)
                or set(maintenance)
                != {
                    "mode",
                    "version",
                    "registry_digest",
                    "coverage_proof_digest",
                    "valid_until",
                }
                or set(restore) != set(maintenance)
                or maintenance["mode"] != RaceLivePublicationMode.OFF
                or not isinstance(maintenance["version"], int)
                or isinstance(maintenance["version"], bool)
                or restore["version"] != maintenance["version"] + 1
                or restore["registry_digest"] != source.registry_digest
                or restore["coverage_proof_digest"]
                != allowlist.coverage_proof_digest
                or maintenance["registry_digest"]
                != restore["registry_digest"]
                or maintenance["coverage_proof_digest"]
                != restore["coverage_proof_digest"]
                or maintenance["valid_until"] != restore["valid_until"]
            ):
                return reject("planned_policy_snapshot_invalid")
            try:
                restore_valid_until = datetime.fromisoformat(
                    restore["valid_until"]
                )
            except (TypeError, ValueError):
                return reject("planned_policy_snapshot_invalid")
            if (
                timezone.is_naive(restore_valid_until)
                or restore_valid_until <= now
                or restore["mode"]
                not in {
                    RaceLivePublicationMode.PROVISIONAL_PUBLIC,
                    RaceLivePublicationMode.OFFICIAL_PUBLIC,
                }
            ):
                return reject("planned_policy_unusable")
            if (
                scope_type == RaceLivePublicationScopeType.SOURCE
                and restore["mode"]
                != RaceLivePublicationMode.PROVISIONAL_PUBLIC
            ):
                return reject("planned_source_policy_mode_invalid")
            actual = {
                "mode": policy.mode,
                "version": policy.version,
                "registry_digest": policy.registry_digest,
                "coverage_proof_digest": policy.coverage_proof_digest,
                "valid_until": (
                    policy.valid_until.isoformat()
                    if policy.valid_until is not None
                    else None
                ),
            }
            if actual == maintenance:
                actual_policy_states.append("maintenance")
            elif actual == restore:
                actual_policy_states.append("restore")
            else:
                return reject("planned_policy_drift")
            restored_modes.append(restore["mode"])
        if actual_policy_states not in (
            ["maintenance"] * 4,
            ["restore", "restore", "restore", "maintenance"],
            ["restore"] * 4,
        ):
            return reject("planned_policy_stage_invalid")
        if min(
            RACE_LIVE_MODE_RANK.get(mode, -1)
            for mode in restored_modes
        ) < RACE_LIVE_MODE_RANK[RaceLivePublicationMode.PROVISIONAL_PUBLIC]:
            return reject("planned_policy_effective_mode_denied")
    return RaceLiveProvisionalRollbackDecision(
        True,
        "provisional_rollback_target_valid",
        revision_id=revision.pk,
    )


def restore_race_live_provisional_policies(
    *,
    event_id: int,
    planned_policy_snapshot: dict[str, dict[str, Any]],
    phase: str,
    expected_provisional_revision_id: int,
    expected_allowlist_version: int,
    expected_publication_id: int,
    expected_manifest_sha256: str,
    now: datetime,
    expected_tracking_lock_version: int | None = None,
    expected_current_revision_id: int | None = None,
) -> RaceLiveProvisionalRollbackDecision:
    """Restore reviewed rollback policies in coarse-then-event CAS stages."""

    if (
        phase not in {"coarse", "event"}
        or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
            expected_manifest_sha256
        )
        or getattr(settings, "RACE_LIVE_SCHEDULER_ENABLED", False) is not False
        or getattr(settings, "RACE_LIVE_MONITOR_ENABLED", False) is not False
        or tuple(
            getattr(settings, "RACE_LIVE_ENABLED_REGIONS", ())
        )
        != ()
    ):
        return RaceLiveProvisionalRollbackDecision(
            False, "rollback_policy_input_invalid"
        )
    with transaction.atomic():
        list(
            RaceEventProjectionControl.objects.select_for_update()
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        active_attempt_tokens = list(
            RaceEventLiveTracking.objects.select_for_update()
            .order_by("pk")
            .values_list("active_attempt_token", flat=True)
        )
        if any(active_attempt_tokens):
            return RaceLiveProvisionalRollbackDecision(
                False, "active_claims_exist"
            )
        event = (
            RaceEvent.objects.select_for_update()
            .filter(pk=event_id)
            .first()
        )
        if event is None:
            return RaceLiveProvisionalRollbackDecision(
                False, "event_missing"
            )
        control = (
            RaceEventProjectionControl.objects.select_for_update()
            .filter(event_id=event_id)
            .first()
        )
        tracking = (
            RaceEventLiveTracking.objects.select_for_update()
            .filter(event_id=event_id)
            .first()
        )
        revision = (
            RaceEventRevision.objects.select_for_update()
            .filter(
                pk=expected_provisional_revision_id,
                event_id=event_id,
            )
            .first()
        )
        observation = (
            RaceResultObservation.objects.select_for_update()
            .filter(
                pk=(
                    revision.primary_observation_id
                    if revision is not None
                    else None
                )
            )
            .first()
        )
        source = (
            RaceResultSourceIdentity.objects.select_for_update()
            .filter(
                pk=(
                    observation.source_identity_id
                    if observation is not None
                    else None
                )
            )
            .first()
        )
        allowlist = (
            RaceLiveEventPublicationAllowlist.objects.select_for_update()
            .filter(
                event_id=event_id,
                source_key="the_racing_api",
            )
            .first()
        )
        publication = (
            RaceEventRevisionPublication.objects.select_for_update()
            .filter(revision_id=expected_provisional_revision_id)
            .first()
        )
        if (
            control is None
            or tracking is None
            or revision is None
            or observation is None
            or source is None
            or allowlist is None
            or publication is None
        ):
            return RaceLiveProvisionalRollbackDecision(
                False, "rollback_baseline_missing"
            )
        if (
            expected_current_revision_id is not None
            and control.current_result_revision_id
            != expected_current_revision_id
        ):
            return RaceLiveProvisionalRollbackDecision(
                False, "current_result_pointer_changed"
            )
        validation = validate_race_live_provisional_rollback_target(
            event_id=event_id,
            now=now,
            expected_provisional_revision_id=(
                expected_provisional_revision_id
            ),
            planned_policy_snapshot=planned_policy_snapshot,
            expected_allowlist_version=expected_allowlist_version,
            expected_publication_id=expected_publication_id,
            expected_tracking_lock_version=expected_tracking_lock_version,
            expected_current_revision_id=expected_current_revision_id,
        )
        if validation.allowed is not True:
            return validation
        expected_scopes = (
            (RaceLivePublicationScopeType.GLOBAL, "global"),
            (RaceLivePublicationScopeType.REGION, event.country_region),
            (RaceLivePublicationScopeType.SOURCE, "the_racing_api"),
            (RaceLivePublicationScopeType.EVENT, str(event_id)),
        )
        policies = list(
            RaceLivePublicationPolicy.objects.select_for_update()
            .filter(
                Q(
                    scope_type=RaceLivePublicationScopeType.GLOBAL,
                    scope_key="global",
                )
                | Q(
                    scope_type=RaceLivePublicationScopeType.REGION,
                    scope_key=event.country_region,
                )
                | Q(
                    scope_type=RaceLivePublicationScopeType.SOURCE,
                    scope_key="the_racing_api",
                )
                | Q(
                    scope_type=RaceLivePublicationScopeType.EVENT,
                    scope_key=str(event_id),
                )
            )
            .order_by("scope_type", "scope_key")
        )
        by_key = {
            f"{policy.scope_type}:{policy.scope_key}": policy
            for policy in policies
        }
        if set(by_key) != {
            f"{scope_type}:{scope_key}"
            for scope_type, scope_key in expected_scopes
        }:
            return RaceLiveProvisionalRollbackDecision(
                False, "planned_policy_scope_mismatch"
            )
        target_scope_types = (
            {
                RaceLivePublicationScopeType.GLOBAL,
                RaceLivePublicationScopeType.REGION,
                RaceLivePublicationScopeType.SOURCE,
            }
            if phase == "coarse"
            else {RaceLivePublicationScopeType.EVENT}
        )
        expected_pre_states = {
            RaceLivePublicationScopeType.GLOBAL: (
                "maintenance" if phase == "coarse" else "restore"
            ),
            RaceLivePublicationScopeType.REGION: (
                "maintenance" if phase == "coarse" else "restore"
            ),
            RaceLivePublicationScopeType.SOURCE: (
                "maintenance" if phase == "coarse" else "restore"
            ),
            RaceLivePublicationScopeType.EVENT: "maintenance",
        }
        planned_updates: list[
            tuple[
                RaceLivePublicationPolicy,
                dict[str, Any],
                datetime,
                str,
            ]
        ] = []
        for scope_type, scope_key in expected_scopes:
            key = f"{scope_type}:{scope_key}"
            policy = by_key[key]
            snapshot = planned_policy_snapshot.get(key)
            if (
                not isinstance(snapshot, dict)
                or set(snapshot) != {"maintenance", "restore"}
            ):
                return RaceLiveProvisionalRollbackDecision(
                    False, "planned_policy_snapshot_invalid"
                )
            expected = snapshot[expected_pre_states[scope_type]]
            actual = {
                "mode": policy.mode,
                "version": policy.version,
                "registry_digest": policy.registry_digest,
                "coverage_proof_digest": policy.coverage_proof_digest,
                "valid_until": (
                    policy.valid_until.isoformat()
                    if policy.valid_until is not None
                    else None
                ),
            }
            restore = snapshot["restore"]
            if actual == restore:
                if scope_type in target_scope_types:
                    continue
                if expected_pre_states[scope_type] != "restore":
                    return RaceLiveProvisionalRollbackDecision(
                        False, "planned_policy_stage_invalid"
                    )
            elif actual != expected:
                return RaceLiveProvisionalRollbackDecision(
                    False, "planned_policy_drift"
                )
            if scope_type in target_scope_types and actual != restore:
                try:
                    restored_valid_until = datetime.fromisoformat(
                        restore["valid_until"]
                    )
                except (KeyError, TypeError, ValueError):
                    return RaceLiveProvisionalRollbackDecision(
                        False, "planned_policy_snapshot_invalid"
                    )
                if (
                    timezone.is_naive(restored_valid_until)
                    or restored_valid_until <= now
                ):
                    return RaceLiveProvisionalRollbackDecision(
                        False, "planned_policy_unusable"
                    )
                planned_updates.append(
                    (policy, restore, restored_valid_until, key)
                )
        changed: list[str] = []
        for policy, restore, restored_valid_until, key in planned_updates:
            policy.mode = restore["mode"]
            policy.version = restore["version"]
            policy.registry_digest = restore["registry_digest"]
            policy.coverage_proof_digest = restore[
                "coverage_proof_digest"
            ]
            policy.valid_until = restored_valid_until
            policy.save(
                update_fields=(
                    "mode",
                    "version",
                    "registry_digest",
                    "coverage_proof_digest",
                    "valid_until",
                    "updated_at",
                )
            )
            changed.append(key)
        if changed:
            log_operation(
                action_type=(
                    "race_live_emergency_provisional_policy_restore"
                ),
                target_type="race_event",
                target_id=event_id,
                detail=json.dumps(
                    {
                        "event_id": event_id,
                        "phase": phase,
                        "manifest_sha256": expected_manifest_sha256,
                        "changed_scopes": changed,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        return RaceLiveProvisionalRollbackDecision(
            True,
            (
                "provisional_policy_coarse_restored"
                if phase == "coarse"
                else "provisional_policy_event_restored"
            ),
        )


def restore_last_provisional_result(
    *,
    event_id: int,
    expected_current_revision_id: int,
    expected_provisional_revision_id: int,
    planned_policy_snapshot: dict[str, dict[str, Any]],
    expected_allowlist_version: int,
    expected_publication_id: int,
    expected_tracking_lock_version: int,
    expected_manifest_sha256: str,
    now: datetime,
) -> RaceLiveProvisionalRollbackDecision:
    """Atomically restore the dedicated last-published provisional projection."""

    if (
        getattr(settings, "RACE_LIVE_SCHEDULER_ENABLED", False) is True
        or getattr(settings, "RACE_LIVE_MONITOR_ENABLED", False) is True
        or tuple(
            getattr(settings, "RACE_LIVE_ENABLED_REGIONS", ())
        )
        != ()
    ):
        return RaceLiveProvisionalRollbackDecision(
            False, "race_live_background_tasks_enabled"
        )
    if (
        not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
            expected_manifest_sha256
        )
        or isinstance(expected_tracking_lock_version, bool)
        or expected_tracking_lock_version < 0
    ):
        return RaceLiveProvisionalRollbackDecision(
            False, "rollback_manifest_invalid"
        )
    with transaction.atomic():
        list(
            RaceEventProjectionControl.objects.select_for_update()
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        active_attempt_tokens = list(
            RaceEventLiveTracking.objects.select_for_update()
            .order_by("pk")
            .values_list("active_attempt_token", flat=True)
        )
        if any(active_attempt_tokens):
            return RaceLiveProvisionalRollbackDecision(
                False, "active_claims_exist"
            )
        try:
            event = RaceEvent.objects.select_for_update().get(pk=event_id)
            control = RaceEventProjectionControl.objects.select_for_update().get(
                event_id=event_id
            )
            tracking = RaceEventLiveTracking.objects.select_for_update().get(
                event_id=event_id
            )
        except (
            RaceEvent.DoesNotExist,
            RaceEventProjectionControl.DoesNotExist,
            RaceEventLiveTracking.DoesNotExist,
        ):
            return RaceLiveProvisionalRollbackDecision(False, "baseline_missing")
        if tracking.lock_version != expected_tracking_lock_version:
            return RaceLiveProvisionalRollbackDecision(
                False, "tracking_version_changed"
            )
        if control.current_result_revision_id != expected_current_revision_id:
            return RaceLiveProvisionalRollbackDecision(
                False, "current_revision_changed"
            )
        current_revision = (
            RaceEventRevision.objects.select_for_update()
            .filter(pk=expected_current_revision_id, event_id=event_id)
            .first()
        )
        revision = (
            RaceEventRevision.objects.select_for_update()
            .select_related("primary_observation__source_identity")
            .filter(pk=expected_provisional_revision_id, event_id=event_id)
            .first()
        )
        if current_revision is None or revision is None:
            return RaceLiveProvisionalRollbackDecision(
                False, "revision_baseline_changed"
            )
        observation = (
            RaceResultObservation.objects.select_for_update()
            .filter(pk=revision.primary_observation_id)
            .first()
        )
        source = (
            RaceResultSourceIdentity.objects.select_for_update()
            .filter(
                pk=(
                    observation.source_identity_id
                    if observation is not None
                    else None
                )
            )
            .first()
        )
        allowlist = (
            RaceLiveEventPublicationAllowlist.objects.select_for_update()
            .filter(event_id=event_id, source_key="the_racing_api")
            .first()
        )
        publication = (
            RaceEventRevisionPublication.objects.select_for_update()
            .filter(revision_id=expected_provisional_revision_id)
            .first()
        )
        policies = list(
            RaceLivePublicationPolicy.objects.select_for_update().filter(
                Q(
                    scope_type=RaceLivePublicationScopeType.GLOBAL,
                    scope_key="global",
                )
                | Q(
                    scope_type=RaceLivePublicationScopeType.REGION,
                    scope_key=event.country_region,
                )
                | Q(
                    scope_type=RaceLivePublicationScopeType.SOURCE,
                    scope_key="the_racing_api",
                )
                | Q(
                    scope_type=RaceLivePublicationScopeType.EVENT,
                    scope_key=str(event_id),
                )
            )
        )
        if (
            source is None
            or allowlist is None
            or publication is None
            or len(policies) != 4
        ):
            return RaceLiveProvisionalRollbackDecision(
                False, "rollback_baseline_missing"
            )
        if allowlist.version != expected_allowlist_version:
            return RaceLiveProvisionalRollbackDecision(
                False, "provisional_allowlist_version_changed"
            )
        if publication.pk != expected_publication_id:
            return RaceLiveProvisionalRollbackDecision(
                False, "provisional_publication_changed"
            )
        validation = validate_race_live_provisional_rollback_target(
            event_id=event_id,
            now=now,
            expected_provisional_revision_id=(
                expected_provisional_revision_id
            ),
            planned_policy_snapshot=planned_policy_snapshot,
            expected_allowlist_version=expected_allowlist_version,
            expected_publication_id=expected_publication_id,
        )
        if validation.allowed is not True:
            return validation
        for policy in policies:
            snapshot = planned_policy_snapshot.get(
                f"{policy.scope_type}:{policy.scope_key}",
                {},
            )
            if not isinstance(snapshot, dict):
                return RaceLiveProvisionalRollbackDecision(
                    False, "planned_policy_snapshot_invalid"
                )
            if policy.mode != RaceLivePublicationMode.OFF:
                return RaceLiveProvisionalRollbackDecision(
                    False, "rollback_requires_maintenance_off"
                )
        items = list(
            RaceEventRevisionItem.objects.select_for_update()
            .filter(revision=revision)
            .select_related("participant")
            .order_by("internal_order", "pk")
        )
        if not items:
            return RaceLiveProvisionalRollbackDecision(
                False, "provisional_items_missing"
            )
        result_rows = []
        for index, item in enumerate(items, start=1):
            result_rows.append(
                RaceEventResult(
                    event_id=event_id,
                    finish_position=index,
                    official_finish_position=item.official_finish_position,
                    horse_number=item.horse_number,
                    horse_name=item.participant.canonical_name,
                    jockey_name=item.jockey_name,
                    trainer_name=item.trainer_name,
                    finish_time=item.finish_time,
                    margin=item.margin,
                    barrier=item.barrier,
                    carried_weight=item.carried_weight,
                    running_status=item.status,
                    is_confirmed=False,
                    source_refs={
                        "source_key": source.source_key,
                        "external_race_id": source.external_race_id,
                    },
                    raw_payload={},
                )
            )
        RaceEventResult.objects.filter(event_id=event_id).delete()
        RaceEventResult.objects.bulk_create(result_rows)
        control.current_result_revision = revision
        control.last_known_good_result_revision = revision
        control.save(
            update_fields=(
                "current_result_revision",
                "last_known_good_result_revision",
                "updated_at",
            )
        )
        tracking.state = RaceEventLiveState.PROVISIONAL_RESULT
        tracking.provisional_published_at = revision.published_at
        tracking.official_published_at = None
        tracking.corrected_at = None
        tracking.save(
            update_fields=(
                "state",
                "provisional_published_at",
                "official_published_at",
                "corrected_at",
                "updated_at",
            )
        )
        event.status = RaceEventStatus.FINISHED
        event.result_confirmed_at = None
        event.save(
            update_fields=("status", "result_confirmed_at", "updated_at")
        )
        log_operation(
            action_type="race_live_emergency_provisional_restore",
            target_type="race_event",
            target_id=event_id,
            detail=json.dumps(
                {
                    "event_id": event_id,
                    "from_revision_id": expected_current_revision_id,
                    "restored_revision_id": revision.pk,
                    "manifest_sha256": expected_manifest_sha256,
                    "allowlist_version": expected_allowlist_version,
                    "publication_id": expected_publication_id,
                    "tracking_lock_version": (
                        expected_tracking_lock_version
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        return RaceLiveProvisionalRollbackDecision(
            True,
            "provisional_result_restored",
            revision_id=revision.pk,
        )


def _race_live_official_publication_audit_matches(
    *,
    publication: RaceEventRevisionPublication,
    authorization: RaceLiveOfficialAuthorizationDecision,
    coarse_policy: RaceLivePublicationPolicyDecision,
) -> bool:
    """Keep detail and bulk official-read audit semantics identical."""

    return (
        publication.authorization_kind == "official_route"
        and publication.official_authorization_version >= 1
        and publication.official_authorization_version
        <= authorization.authorization_version
        and publication.registry_digest
        == authorization.route_registry_digest
        and publication.coverage_proof_digest
        == authorization.coverage_proof_digest
        and publication.allowlist_version
        == coarse_policy.allowlist_version
        and publication.policy_versions
        == [list(row) for row in coarse_policy.policy_versions]
    )


def _resolve_data_sync_publication_from_loaded_rows(
    *,
    event: RaceEvent,
    control: RaceEventProjectionControl,
    revision: RaceEventRevision,
    publication: RaceEventRevisionPublication,
    observation: RaceResultObservation,
    source: RaceResultSourceIdentity,
    enrollment: RaceDataSyncEnrollment | None,
    enrollment_source: RaceResultSourceIdentity | None,
    lifecycle: RaceEventLifecycleControl | None,
    lifecycle_membership: RaceEventLifecycleEnforceMembership | None,
    now: datetime,
) -> RaceLivePublicReadDecision:
    """Authorize a data-sync result without borrowing legacy race-live policy."""

    def reject(reason: str) -> RaceLivePublicReadDecision:
        return RaceLivePublicReadDecision(
            visible=False,
            reason=f"data_sync_{reason}",
            revision_id=revision.pk,
            phase=revision.phase,
            effective_mode=RaceLivePublicationMode.OFF,
        )

    if control.write_owner != RaceEventProjectionWriteOwner.DATA_SYNC:
        return reject("writer_owner_mismatch")
    if revision.phase not in {RaceResultPhase.OFFICIAL, RaceResultPhase.CORRECTED}:
        return reject("phase_not_public")
    if event.status != RaceEventStatus.FINISHED or not isinstance(
        event.result_confirmed_at, datetime
    ) or timezone.is_naive(event.result_confirmed_at):
        return reject("event_not_confirmed")

    from stable.services.race_event_lifecycle_enforce import (
        validate_registry_membership_snapshot,
    )

    lifecycle_validation = validate_registry_membership_snapshot(
        membership=lifecycle_membership,
        event=event,
        control=lifecycle,
        now=now,
    )
    if not lifecycle_validation.valid:
        return reject(lifecycle_validation.reason_code)

    from stable.services.race_data_sync_control import (
        resolve_source_route_admission,
    )
    from stable.services.race_data_sync_pipeline import (
        RaceDataSyncFlags,
        resolve_race_data_provider_route,
    )

    flags = RaceDataSyncFlags.from_settings()
    if not (
        flags.enabled
        and flags.result_apply_enabled
        and flags.result_public_enabled
        and source.source_key in flags.providers
        and source.region_code in flags.regions
        and RaceEventRevisionKind.RESULT == revision.kind
        and "result" in flags.data_kinds
    ):
        return reject("runtime_gate_closed")
    if (
        revision.phase == RaceResultPhase.CORRECTED
        and not flags.correction_apply_enabled
    ):
        return reject("correction_gate_closed")

    if enrollment is None:
        return reject("enrollment_missing")
    if (
        enrollment.state != "enrolled"
        or enrollment.event_id != event.pk
        or enrollment.projection_owner_generation != control.owner_generation
        or enrollment.enrollment_generation != control.owner_generation
        or enrollment.manifest_sha256 != control.owner_manifest_sha256
        or not isinstance(enrollment.effective_at, datetime)
        or timezone.is_naive(enrollment.effective_at)
        or enrollment.effective_at > publication.published_at
    ):
        return reject("enrollment_drift")
    digest_values = (
        enrollment.standing_policy_digest,
        enrollment.route_digest,
        enrollment.event_snapshot_sha256,
        enrollment.manifest_sha256,
        enrollment.entry_sha256,
    )
    if any(
        not isinstance(value, str)
        or RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(value) is None
        for value in digest_values
    ):
        return reject("enrollment_digest_invalid")
    standing_policy_digest = str(
        getattr(settings, "RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256", "")
        or ""
    )
    if enrollment.standing_policy_digest != standing_policy_digest:
        return reject("standing_policy_drift")

    if (
        enrollment_source is None
        or enrollment_source.pk != enrollment.source_identity_id
        or enrollment_source.event_id != event.pk
    ):
        return reject("enrollment_source_missing")
    enrollment_reason, enrollment_route = resolve_source_route_admission(
        source=enrollment_source,
        route_digest=enrollment.route_digest,
        data_kinds=("result",),
        now=now,
    )
    if enrollment_reason or enrollment_route is None:
        return reject(enrollment_reason or "enrollment_route_unavailable")

    route = resolve_race_data_provider_route(
        provider=source.source_key,
        region=source.region_code,
        identity_namespace=source.identity_namespace,
        data_kinds=("result",),
    )
    if route is None:
        return reject("route_unavailable")
    admission_reason, admitted_route = resolve_source_route_admission(
        source=source,
        route_digest=route.route_digest,
        data_kinds=("result",),
        now=now,
    )
    if admission_reason or admitted_route is None:
        return reject(admission_reason or "route_unavailable")
    route = admitted_route
    provenance = (
        observation.field_provenance
        if isinstance(observation.field_provenance, dict)
        else {}
    )
    expected_source_class = route.entry.source_class
    if (
        revision.source_authority != expected_source_class
        or provenance.get("provider") != source.source_key
        or provenance.get("region") != source.region_code
        or provenance.get("source_class") != expected_source_class
        or provenance.get("automation_allowed") is not True
        or provenance.get("registry_digest") != route.registry_digest
        or provenance.get("contract_version") != route.entry.contract_version
        or provenance.get("contract_digest") != route.contract_digest
    ):
        return reject("source_contract_drift")
    if (
        publication.reason != "data_sync_result"
        or publication.authorization_kind != "official_route"
        or publication.official_authorization_version != 0
        or publication.allowlist_version != 1
        or publication.registry_digest != route.registry_digest
        or publication.coverage_proof_digest != observation.normalized_sha256
        or publication.policy_versions
        != [["race_data_sync_contract", route.entry.contract_version, 1]]
    ):
        return reject("publication_audit_mismatch")
    return RaceLivePublicReadDecision(
        visible=True,
        reason="data_sync_public_read_allowed",
        revision_id=revision.pk,
        phase=revision.phase,
        effective_mode=RaceLivePublicationMode.OFFICIAL_PUBLIC,
    )


def resolve_race_live_public_read(
    *,
    event_id: int,
    now: datetime,
) -> RaceLivePublicReadDecision:
    """Fail closed unless the current published live result still passes policy."""

    def reject(
        reason: str,
        *,
        revision_id: int | None = None,
        phase: str = "",
        effective_mode: str = RaceLivePublicationMode.OFF,
    ) -> RaceLivePublicReadDecision:
        return RaceLivePublicReadDecision(
            visible=False,
            reason=reason,
            revision_id=revision_id,
            phase=phase,
            effective_mode=effective_mode,
        )

    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
        return reject("invalid_event_id")
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return reject("invalid_now")
    if not RaceEvent.objects.filter(pk=event_id).exists():
        return reject("event_missing")

    control = RaceEventProjectionControl.objects.filter(event_id=event_id).first()
    if control is None:
        return reject("control_missing")
    if control.current_result_revision_id is None:
        return reject("current_result_revision_missing")

    revision = RaceEventRevision.objects.filter(
        pk=control.current_result_revision_id
    ).first()
    if revision is None:
        return reject("current_result_revision_missing")
    revision_id = revision.pk
    phase = revision.phase
    if revision.event_id != event_id:
        return reject(
            "revision_event_mismatch",
            revision_id=revision_id,
            phase=phase,
        )
    if revision.kind != RaceEventRevisionKind.RESULT:
        return reject(
            "revision_kind_mismatch",
            revision_id=revision_id,
            phase=phase,
        )
    if (
        not isinstance(revision.published_at, datetime)
        or timezone.is_naive(revision.published_at)
    ):
        return reject(
            "revision_not_published",
            revision_id=revision_id,
            phase=phase,
        )

    publication = RaceEventRevisionPublication.objects.filter(
        revision_id=revision_id
    ).first()
    if publication is None:
        return reject(
            "publication_audit_missing",
            revision_id=revision_id,
            phase=phase,
        )
    if (
        not isinstance(publication.published_at, datetime)
        or timezone.is_naive(publication.published_at)
        or publication.published_at != revision.published_at
    ):
        return reject(
            "publication_timestamp_mismatch",
            revision_id=revision_id,
            phase=phase,
        )

    if revision.primary_observation_id is None:
        return reject(
            "primary_observation_missing",
            revision_id=revision_id,
            phase=phase,
        )
    observation = RaceResultObservation.objects.filter(
        pk=revision.primary_observation_id
    ).first()
    if observation is None:
        return reject(
            "primary_observation_missing",
            revision_id=revision_id,
            phase=phase,
        )
    if (
        observation.result_phase != phase
        or observation.normalized_sha256 != revision.content_sha256
    ):
        return reject(
            "observation_revision_mismatch",
            revision_id=revision_id,
            phase=phase,
        )

    source = RaceResultSourceIdentity.objects.filter(
        pk=observation.source_identity_id
    ).first()
    if source is None:
        return reject(
            "source_identity_missing",
            revision_id=revision_id,
            phase=phase,
        )
    if source.event_id != event_id:
        return reject(
            "source_event_mismatch",
            revision_id=revision_id,
            phase=phase,
        )
    if control.write_owner == RaceEventProjectionWriteOwner.DATA_SYNC:
        enrollment = (
            RaceDataSyncEnrollment.objects.select_related("source_identity")
            .filter(event_id=event_id)
            .first()
        )
        event = RaceEvent.objects.get(pk=event_id)
        lifecycle = RaceEventLifecycleControl.objects.filter(
            event_id=event_id
        ).first()
        lifecycle_membership = (
            RaceEventLifecycleEnforceMembership.objects.select_related("registry")
            .filter(
                event_id=event_id,
                state="active",
                registry__root_sha256=getattr(
                    settings,
                    "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256",
                    "",
                ),
            )
            .first()
        )
        return _resolve_data_sync_publication_from_loaded_rows(
            event=event,
            control=control,
            revision=revision,
            publication=publication,
            observation=observation,
            source=source,
            enrollment=enrollment,
            enrollment_source=(enrollment.source_identity if enrollment else None),
            lifecycle=lifecycle,
            lifecycle_membership=lifecycle_membership,
            now=now,
        )
    if revision.source_authority != source.result_authority:
        return reject(
            "source_authority_mismatch",
            revision_id=revision_id,
            phase=phase,
        )

    required_mode = {
        RaceResultPhase.PROVISIONAL: RaceLivePublicationMode.PROVISIONAL_PUBLIC,
        RaceResultPhase.OFFICIAL: RaceLivePublicationMode.OFFICIAL_PUBLIC,
        RaceResultPhase.CORRECTED: RaceLivePublicationMode.OFFICIAL_PUBLIC,
    }.get(phase)
    if required_mode is None:
        return reject(
            "unsupported_result_phase",
            revision_id=revision_id,
            phase=phase,
        )

    if phase in {RaceResultPhase.OFFICIAL, RaceResultPhase.CORRECTED}:
        coarse_policy = resolve_race_live_official_coarse_policy(
            event_id=event_id,
            now=now,
        )
        if coarse_policy.allowed is not True:
            return reject(
                f"policy_{coarse_policy.reason}",
                revision_id=revision_id,
                phase=phase,
                effective_mode=coarse_policy.effective_mode,
            )
        official = resolve_race_live_official_publication_authorization(
            event_id=event_id,
            observation_id=observation.pk,
            phase=phase,
            now=now,
        )
        if official.allowed is not True:
            return reject(
                f"official_{official.reason}",
                revision_id=revision_id,
                phase=phase,
            )
        if not _race_live_official_publication_audit_matches(
            publication=publication,
            authorization=official,
            coarse_policy=coarse_policy,
        ):
            return reject(
                "official_publication_audit_mismatch",
                revision_id=revision_id,
                phase=phase,
            )
        return RaceLivePublicReadDecision(
            visible=True,
            reason="official_public_read_allowed",
            revision_id=revision_id,
            phase=phase,
            effective_mode=RaceLivePublicationMode.OFFICIAL_PUBLIC,
        )
    if (
        publication.authorization_kind != "provisional_policy"
        or publication.official_authorization_version != 0
    ):
        return reject(
            "provisional_publication_audit_mismatch",
            revision_id=revision_id,
            phase=phase,
        )
    policy = resolve_race_live_publication_policy(
        event_id=event_id,
        source_identity_id=source.pk,
        now=now,
    )
    if not policy.allowed:
        return reject(
            f"policy_{policy.reason}",
            revision_id=revision_id,
            phase=phase,
            effective_mode=policy.effective_mode,
        )
    if (
        RACE_LIVE_MODE_RANK.get(policy.effective_mode, -1)
        < RACE_LIVE_MODE_RANK[required_mode]
    ):
        return reject(
            "policy_mode_insufficient",
            revision_id=revision_id,
            phase=phase,
            effective_mode=policy.effective_mode,
        )
    if publication.registry_digest != policy.registry_digest:
        return reject(
            "publication_registry_digest_mismatch",
            revision_id=revision_id,
            phase=phase,
            effective_mode=policy.effective_mode,
        )
    if publication.coverage_proof_digest != policy.coverage_proof_digest:
        return reject(
            "publication_coverage_digest_mismatch",
            revision_id=revision_id,
            phase=phase,
            effective_mode=policy.effective_mode,
        )

    return RaceLivePublicReadDecision(
        visible=True,
        reason="public_read_allowed",
        revision_id=revision_id,
        phase=phase,
        effective_mode=policy.effective_mode,
    )


def _resolve_race_live_publication_policy_from_loaded_rows(
    *,
    event: RaceEvent,
    source: RaceResultSourceIdentity,
    now: datetime,
    policy_by_scope: dict[tuple[str, str], RaceLivePublicationPolicy],
    allowlist_by_event_source: dict[
        tuple[int, str], RaceLiveEventPublicationAllowlist
    ],
) -> RaceLivePublicationPolicyDecision:
    """Apply the single-event policy resolver semantics to already-loaded rows."""

    def reject(
        reason: str,
        *,
        policy_versions: tuple[tuple[str, str, int], ...] = (),
        allowlist_version: int = 0,
        registry_digest: str = "",
        coverage_proof_digest: str = "",
    ) -> RaceLivePublicationPolicyDecision:
        return RaceLivePublicationPolicyDecision(
            allowed=False,
            effective_mode=RaceLivePublicationMode.OFF,
            reason=reason,
            policy_versions=policy_versions,
            allowlist_version=allowlist_version,
            registry_digest=registry_digest,
            coverage_proof_digest=coverage_proof_digest,
        )

    if source.event_id != event.pk:
        return reject("source_event_mismatch")
    if source.review_status != RaceLiveReviewStatus.APPROVED:
        return reject("source_not_approved")
    if source.terms_status != RaceSourceTermsStatus.APPROVED:
        return reject("terms_not_approved")
    if source.automation_allowed is not True:
        return reject("automation_not_allowed")
    if (
        not isinstance(source.valid_until, datetime)
        or timezone.is_naive(source.valid_until)
        or source.valid_until <= now
    ):
        return reject("source_expired")
    if (
        not isinstance(source.registry_digest, str)
        or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
            source.registry_digest
        )
    ):
        return reject("invalid_registry_digest")

    policy_lookups = (
        ("global", "global", "global_policy_missing"),
        ("region", event.country_region, "region_policy_missing"),
        ("source", source.source_key, "source_policy_missing"),
        ("event", str(event.pk), "event_policy_missing"),
    )
    policies: list[RaceLivePublicationPolicy] = []
    for scope_type, scope_key, missing_reason in policy_lookups:
        policy = policy_by_scope.get((scope_type, scope_key))
        if policy is None:
            return reject(missing_reason)
        policies.append(policy)

    policy_versions = tuple(
        (policy.scope_type, policy.scope_key, policy.version)
        for policy in policies
    )
    if any(policy.mode == RaceLivePublicationMode.OFF for policy in policies):
        return reject(
            "policy_off",
            policy_versions=policy_versions,
            registry_digest=source.registry_digest,
        )
    if any(policy.mode not in RACE_LIVE_MODE_ORDER for policy in policies):
        return reject(
            "invalid_policy_mode",
            policy_versions=policy_versions,
            registry_digest=source.registry_digest,
        )

    allowlist = allowlist_by_event_source.get((event.pk, source.source_key))
    if allowlist is None:
        return reject(
            "event_allowlist_missing",
            policy_versions=policy_versions,
            registry_digest=source.registry_digest,
        )
    if allowlist.enabled is not True:
        return reject(
            "event_not_allowlisted",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )
    if allowlist.max_mode == RaceLivePublicationMode.OFF:
        return reject(
            "policy_off",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )
    if allowlist.max_mode not in RACE_LIVE_MODE_ORDER:
        return reject(
            "invalid_allowlist_mode",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )

    for policy in policies:
        if (
            not isinstance(policy.valid_until, datetime)
            or timezone.is_naive(policy.valid_until)
            or policy.valid_until <= now
        ):
            return reject(
                "policy_expired",
                policy_versions=policy_versions,
                allowlist_version=allowlist.version,
                registry_digest=source.registry_digest,
                coverage_proof_digest=allowlist.coverage_proof_digest,
            )
        if policy.registry_digest != source.registry_digest:
            return reject(
                "registry_digest_mismatch",
                policy_versions=policy_versions,
                allowlist_version=allowlist.version,
                registry_digest=source.registry_digest,
                coverage_proof_digest=allowlist.coverage_proof_digest,
            )

    if (
        not isinstance(allowlist.coverage_proof_digest, str)
        or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
            allowlist.coverage_proof_digest
        )
    ):
        return reject(
            "invalid_coverage_digest",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )
    if any(
        policy.coverage_proof_digest != allowlist.coverage_proof_digest
        for policy in policies
    ):
        return reject(
            "coverage_digest_mismatch",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )

    if (
        not isinstance(allowlist.official_verification_route, str)
        or not allowlist.official_verification_route.strip()
        or allowlist.official_verification_route.strip()
        != allowlist.official_verification_route
        or not isinstance(
            allowlist.official_verification_route_version,
            str,
        )
        or not allowlist.official_verification_route_version.strip()
        or allowlist.official_verification_route_version.strip()
        != allowlist.official_verification_route_version
    ):
        return reject(
            "official_route_missing",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )
    if (
        not isinstance(allowlist.official_verification_valid_until, datetime)
        or timezone.is_naive(allowlist.official_verification_valid_until)
        or allowlist.official_verification_valid_until <= now
    ):
        return reject(
            "official_route_expired",
            policy_versions=policy_versions,
            allowlist_version=allowlist.version,
            registry_digest=source.registry_digest,
            coverage_proof_digest=allowlist.coverage_proof_digest,
        )

    effective_rank = min(
        [
            *(RACE_LIVE_MODE_RANK[policy.mode] for policy in policies),
            RACE_LIVE_MODE_RANK[allowlist.max_mode],
        ]
    )
    effective_mode = RACE_LIVE_MODE_ORDER[effective_rank]
    allowed = effective_mode in {
        RaceLivePublicationMode.PROVISIONAL_PUBLIC,
        RaceLivePublicationMode.OFFICIAL_PUBLIC,
    }
    if allowed:
        if (
            not isinstance(
                allowlist.official_verification_contract_digest,
                str,
            )
            or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
                allowlist.official_verification_contract_digest
            )
        ):
            return reject(
                "official_route_contract_digest_invalid",
                policy_versions=policy_versions,
                allowlist_version=allowlist.version,
                registry_digest=source.registry_digest,
                coverage_proof_digest=allowlist.coverage_proof_digest,
            )
        if (
            not isinstance(allowlist.official_terms_evidence_digest, str)
            or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
                allowlist.official_terms_evidence_digest
            )
        ):
            return reject(
                "official_terms_evidence_digest_invalid",
                policy_versions=policy_versions,
                allowlist_version=allowlist.version,
                registry_digest=source.registry_digest,
                coverage_proof_digest=allowlist.coverage_proof_digest,
            )
    return RaceLivePublicationPolicyDecision(
        allowed=allowed,
        effective_mode=effective_mode,
        reason="publication_allowed" if allowed else "shadow_only",
        policy_versions=policy_versions,
        allowlist_version=allowlist.version,
        registry_digest=source.registry_digest,
        coverage_proof_digest=allowlist.coverage_proof_digest,
    )


def _resolve_race_live_official_coarse_policy_from_loaded_rows(
    *,
    event: RaceEvent,
    tra_source: RaceResultSourceIdentity | None,
    now: datetime,
    policy_by_scope: dict[tuple[str, str], RaceLivePublicationPolicy],
    allowlist_by_event_source: dict[
        tuple[int, str],
        RaceLiveEventPublicationAllowlist,
    ],
) -> RaceLivePublicationPolicyDecision:
    """Apply the official coarse gate without issuing per-event queries."""

    if tra_source is None:
        return RaceLivePublicationPolicyDecision(
            False,
            RaceLivePublicationMode.OFF,
            "tra_source_missing",
        )
    base = _resolve_race_live_publication_policy_from_loaded_rows(
        event=event,
        source=tra_source,
        now=now,
        policy_by_scope=policy_by_scope,
        allowlist_by_event_source=allowlist_by_event_source,
    )
    if base.allowed is not True:
        return base
    modes = {
        scope_type: policy_by_scope[(scope_type, scope_key)].mode
        for scope_type, scope_key in (
            (RaceLivePublicationScopeType.GLOBAL, "global"),
            (
                RaceLivePublicationScopeType.REGION,
                event.country_region,
            ),
            (
                RaceLivePublicationScopeType.SOURCE,
                tra_source.source_key,
            ),
            (RaceLivePublicationScopeType.EVENT, str(event.pk)),
        )
        if (scope_type, scope_key) in policy_by_scope
    }
    if set(modes) != {
        RaceLivePublicationScopeType.GLOBAL,
        RaceLivePublicationScopeType.REGION,
        RaceLivePublicationScopeType.SOURCE,
        RaceLivePublicationScopeType.EVENT,
    }:
        return RaceLivePublicationPolicyDecision(
            False,
            RaceLivePublicationMode.OFF,
            "official_coarse_policy_missing",
            policy_versions=base.policy_versions,
            allowlist_version=base.allowlist_version,
            registry_digest=base.registry_digest,
            coverage_proof_digest=base.coverage_proof_digest,
        )
    if any(
        modes[scope_type] != RaceLivePublicationMode.OFFICIAL_PUBLIC
        for scope_type in (
            RaceLivePublicationScopeType.GLOBAL,
            RaceLivePublicationScopeType.REGION,
            RaceLivePublicationScopeType.EVENT,
        )
    ) or RACE_LIVE_MODE_RANK.get(
        modes[RaceLivePublicationScopeType.SOURCE], -1
    ) < RACE_LIVE_MODE_RANK[RaceLivePublicationMode.PROVISIONAL_PUBLIC]:
        return RaceLivePublicationPolicyDecision(
            False,
            base.effective_mode,
            "official_coarse_policy_insufficient",
            policy_versions=base.policy_versions,
            allowlist_version=base.allowlist_version,
            registry_digest=base.registry_digest,
            coverage_proof_digest=base.coverage_proof_digest,
        )
    return RaceLivePublicationPolicyDecision(
        True,
        RaceLivePublicationMode.OFFICIAL_PUBLIC,
        "official_coarse_policy_allowed",
        policy_versions=base.policy_versions,
        allowlist_version=base.allowlist_version,
        registry_digest=base.registry_digest,
        coverage_proof_digest=base.coverage_proof_digest,
    )


def resolve_race_live_public_reads(
    *,
    event_ids: Iterable[int],
    now: datetime,
) -> dict[int, RaceLivePublicReadDecision]:
    """Resolve a page of public live-result reads with a fixed query count."""

    def reject(
        reason: str,
        *,
        revision_id: int | None = None,
        phase: str = "",
        effective_mode: str = RaceLivePublicationMode.OFF,
    ) -> RaceLivePublicReadDecision:
        return RaceLivePublicReadDecision(
            visible=False,
            reason=reason,
            revision_id=revision_id,
            phase=phase,
            effective_mode=effective_mode,
        )

    requested_ids = list(event_ids)
    decisions: dict[int, RaceLivePublicReadDecision] = {}
    valid_ids: list[int] = []
    seen_ids: set[int] = set()
    for event_id in requested_ids:
        if (
            isinstance(event_id, bool)
            or not isinstance(event_id, int)
            or event_id <= 0
        ):
            decisions[event_id] = reject("invalid_event_id")
        elif event_id not in seen_ids:
            seen_ids.add(event_id)
            valid_ids.append(event_id)
    if not isinstance(now, datetime) or timezone.is_naive(now):
        for event_id in valid_ids:
            decisions[event_id] = reject("invalid_now")
        return decisions
    if not valid_ids:
        return decisions

    event_by_id = {
        event.pk: event for event in RaceEvent.objects.filter(pk__in=valid_ids)
    }
    control_by_event_id = {
        control.event_id: control
        for control in RaceEventProjectionControl.objects.filter(
            event_id__in=valid_ids
        ).select_related(
            "current_result_revision__primary_observation__source_identity",
            (
                "current_result_revision__primary_observation__"
                "official_marker_evidence__contract"
            ),
        )
    }
    revision_ids = [
        control.current_result_revision_id
        for control in control_by_event_id.values()
        if control.current_result_revision_id is not None
    ]
    publication_by_revision_id = {
        publication.revision_id: publication
        for publication in RaceEventRevisionPublication.objects.filter(
            revision_id__in=revision_ids
        )
    }
    source_keys: set[str] = set()
    for control in control_by_event_id.values():
        revision = control.current_result_revision
        if revision is None or revision.primary_observation is None:
            continue
        source = revision.primary_observation.source_identity
        if source is not None:
            source_keys.add(source.source_key)
    source_keys.add("the_racing_api")
    region_keys = {
        event.country_region for event in event_by_id.values()
    }
    policy_filter = Q(scope_type="global", scope_key="global")
    if region_keys:
        policy_filter |= Q(scope_type="region", scope_key__in=region_keys)
    if source_keys:
        policy_filter |= Q(scope_type="source", scope_key__in=source_keys)
    policy_filter |= Q(
        scope_type="event",
        scope_key__in=[str(event_id) for event_id in valid_ids],
    )
    policy_by_scope = {
        (policy.scope_type, policy.scope_key): policy
        for policy in RaceLivePublicationPolicy.objects.filter(policy_filter)
    }
    allowlist_by_event_source = {
        (allowlist.event_id, allowlist.source_key): allowlist
        for allowlist in RaceLiveEventPublicationAllowlist.objects.filter(
            event_id__in=valid_ids
        )
    }
    tra_source_by_event_id = {
        source.event_id: source
        for source in RaceResultSourceIdentity.objects.filter(
            event_id__in=valid_ids,
            source_key="the_racing_api",
        )
    }
    authorization_by_event_id = {
        authorization.event_id: authorization
        for authorization in (
            RaceLiveOfficialPublicationAuthorization.objects.filter(
                event_id__in=valid_ids,
            )
        )
    }
    data_sync_event_ids = [
        event_id
        for event_id, control in control_by_event_id.items()
        if control.write_owner == RaceEventProjectionWriteOwner.DATA_SYNC
    ]
    enrollment_by_event_id = {
        enrollment.event_id: enrollment
        for enrollment in RaceDataSyncEnrollment.objects.filter(
            event_id__in=data_sync_event_ids
        ).select_related("source_identity")
    }
    lifecycle_by_event_id = {
        lifecycle.event_id: lifecycle
        for lifecycle in RaceEventLifecycleControl.objects.filter(
            event_id__in=data_sync_event_ids
        )
    }
    lifecycle_membership_by_event_id = {
        membership.event_id: membership
        for membership in RaceEventLifecycleEnforceMembership.objects.filter(
            event_id__in=data_sync_event_ids,
            state="active",
            registry__root_sha256=getattr(
                settings,
                "RACE_EVENT_LIFECYCLE_ENFORCE_REGISTRY_SHA256",
                "",
            ),
        )
        .select_related("registry")
    }

    required_mode_by_phase = {
        RaceResultPhase.PROVISIONAL: RaceLivePublicationMode.PROVISIONAL_PUBLIC,
        RaceResultPhase.OFFICIAL: RaceLivePublicationMode.OFFICIAL_PUBLIC,
        RaceResultPhase.CORRECTED: RaceLivePublicationMode.OFFICIAL_PUBLIC,
    }
    for event_id in valid_ids:
        event = event_by_id.get(event_id)
        if event is None:
            decisions[event_id] = reject("event_missing")
            continue
        control = control_by_event_id.get(event_id)
        if control is None:
            decisions[event_id] = reject("control_missing")
            continue
        if control.current_result_revision_id is None:
            decisions[event_id] = reject("current_result_revision_missing")
            continue
        revision = control.current_result_revision
        if revision is None:
            decisions[event_id] = reject("current_result_revision_missing")
            continue
        revision_id = revision.pk
        phase = revision.phase
        if revision.event_id != event_id:
            decisions[event_id] = reject(
                "revision_event_mismatch",
                revision_id=revision_id,
                phase=phase,
            )
            continue
        if revision.kind != RaceEventRevisionKind.RESULT:
            decisions[event_id] = reject(
                "revision_kind_mismatch",
                revision_id=revision_id,
                phase=phase,
            )
            continue
        if (
            not isinstance(revision.published_at, datetime)
            or timezone.is_naive(revision.published_at)
        ):
            decisions[event_id] = reject(
                "revision_not_published",
                revision_id=revision_id,
                phase=phase,
            )
            continue

        publication = publication_by_revision_id.get(revision_id)
        if publication is None:
            decisions[event_id] = reject(
                "publication_audit_missing",
                revision_id=revision_id,
                phase=phase,
            )
            continue
        if (
            not isinstance(publication.published_at, datetime)
            or timezone.is_naive(publication.published_at)
            or publication.published_at != revision.published_at
        ):
            decisions[event_id] = reject(
                "publication_timestamp_mismatch",
                revision_id=revision_id,
                phase=phase,
            )
            continue

        if revision.primary_observation_id is None:
            decisions[event_id] = reject(
                "primary_observation_missing",
                revision_id=revision_id,
                phase=phase,
            )
            continue
        observation = revision.primary_observation
        if observation is None:
            decisions[event_id] = reject(
                "primary_observation_missing",
                revision_id=revision_id,
                phase=phase,
            )
            continue
        if (
            observation.result_phase != phase
            or observation.normalized_sha256 != revision.content_sha256
        ):
            decisions[event_id] = reject(
                "observation_revision_mismatch",
                revision_id=revision_id,
                phase=phase,
            )
            continue

        source = observation.source_identity
        if source is None:
            decisions[event_id] = reject(
                "source_identity_missing",
                revision_id=revision_id,
                phase=phase,
            )
            continue
        if source.event_id != event_id:
            decisions[event_id] = reject(
                "source_event_mismatch",
                revision_id=revision_id,
                phase=phase,
            )
            continue
        if control.write_owner == RaceEventProjectionWriteOwner.DATA_SYNC:
            decisions[event_id] = _resolve_data_sync_publication_from_loaded_rows(
                event=event,
                control=control,
                revision=revision,
                publication=publication,
                observation=observation,
                source=source,
                enrollment=enrollment_by_event_id.get(event_id),
                enrollment_source=(
                    enrollment_by_event_id[event_id].source_identity
                    if event_id in enrollment_by_event_id
                    else None
                ),
                lifecycle=lifecycle_by_event_id.get(event_id),
                lifecycle_membership=lifecycle_membership_by_event_id.get(
                    event_id
                ),
                now=now,
            )
            continue
        if revision.source_authority != source.result_authority:
            decisions[event_id] = reject(
                "source_authority_mismatch",
                revision_id=revision_id,
                phase=phase,
            )
            continue

        required_mode = required_mode_by_phase.get(phase)
        if required_mode is None:
            decisions[event_id] = reject(
                "unsupported_result_phase",
                revision_id=revision_id,
                phase=phase,
            )
            continue
        if phase in {RaceResultPhase.OFFICIAL, RaceResultPhase.CORRECTED}:
            tra_source = tra_source_by_event_id.get(event_id)
            coarse_policy = (
                _resolve_race_live_official_coarse_policy_from_loaded_rows(
                    event=event,
                    tra_source=tra_source,
                    now=now,
                    policy_by_scope=policy_by_scope,
                    allowlist_by_event_source=allowlist_by_event_source,
                )
            )
            if coarse_policy.allowed is not True:
                decisions[event_id] = reject(
                    f"policy_{coarse_policy.reason}",
                    revision_id=revision_id,
                    phase=phase,
                    effective_mode=coarse_policy.effective_mode,
                )
                continue
            official = (
                _resolve_race_live_official_authorization_from_loaded_rows(
                    event=event,
                    observation=observation,
                    authorization=authorization_by_event_id.get(event_id),
                    tra_source=tra_source,
                    allowlist=allowlist_by_event_source.get(
                        (event_id, "the_racing_api")
                    ),
                    policy_by_scope=policy_by_scope,
                    phase=phase,
                    now=now,
                )
            )
            if official.allowed is not True:
                decisions[event_id] = reject(
                    f"official_{official.reason}",
                    revision_id=revision_id,
                    phase=phase,
                )
                continue
            if not _race_live_official_publication_audit_matches(
                publication=publication,
                authorization=official,
                coarse_policy=coarse_policy,
            ):
                decisions[event_id] = reject(
                    "official_publication_audit_mismatch",
                    revision_id=revision_id,
                    phase=phase,
                )
                continue
            decisions[event_id] = RaceLivePublicReadDecision(
                visible=True,
                reason="official_public_read_allowed",
                revision_id=revision_id,
                phase=phase,
                effective_mode=RaceLivePublicationMode.OFFICIAL_PUBLIC,
            )
            continue
        if (
            publication.authorization_kind != "provisional_policy"
            or publication.official_authorization_version != 0
        ):
            decisions[event_id] = reject(
                "provisional_publication_audit_mismatch",
                revision_id=revision_id,
                phase=phase,
            )
            continue
        policy = _resolve_race_live_publication_policy_from_loaded_rows(
            event=event,
            source=source,
            now=now,
            policy_by_scope=policy_by_scope,
            allowlist_by_event_source=allowlist_by_event_source,
        )
        if not policy.allowed:
            decisions[event_id] = reject(
                f"policy_{policy.reason}",
                revision_id=revision_id,
                phase=phase,
                effective_mode=policy.effective_mode,
            )
            continue
        if (
            RACE_LIVE_MODE_RANK.get(policy.effective_mode, -1)
            < RACE_LIVE_MODE_RANK[required_mode]
        ):
            decisions[event_id] = reject(
                "policy_mode_insufficient",
                revision_id=revision_id,
                phase=phase,
                effective_mode=policy.effective_mode,
            )
            continue
        if publication.registry_digest != policy.registry_digest:
            decisions[event_id] = reject(
                "publication_registry_digest_mismatch",
                revision_id=revision_id,
                phase=phase,
                effective_mode=policy.effective_mode,
            )
            continue
        if publication.coverage_proof_digest != policy.coverage_proof_digest:
            decisions[event_id] = reject(
                "publication_coverage_digest_mismatch",
                revision_id=revision_id,
                phase=phase,
                effective_mode=policy.effective_mode,
            )
            continue
        decisions[event_id] = RaceLivePublicReadDecision(
            visible=True,
            reason="public_read_allowed",
            revision_id=revision_id,
            phase=phase,
            effective_mode=policy.effective_mode,
        )
    return decisions


def is_race_live_state_transition_allowed(
    *,
    current_state: str | None,
    next_state: str | None,
) -> bool:
    """Return whether the live race state transition is explicitly approved."""
    if not isinstance(current_state, str) or not isinstance(next_state, str):
        return False
    return (current_state, next_state) in RACE_LIVE_ALLOWED_STATE_TRANSITIONS


def decide_race_result_revision_action(
    *,
    current_state: str,
    current_phase: str | None,
    current_content_sha256: str,
    incoming_phase: str,
    incoming_content_sha256: str,
    source_authority: str,
    official_marker: bool,
    identity_valid: bool,
    payload_complete: bool,
    manual_lock_conflict: bool,
) -> RaceResultRevisionActionDecision:
    """Choose a fail-closed result revision action without database I/O."""
    if not isinstance(identity_valid, bool):
        return RaceResultRevisionActionDecision("reject", "invalid_identity_valid")
    if not isinstance(payload_complete, bool):
        return RaceResultRevisionActionDecision("reject", "invalid_payload_complete")
    if not isinstance(manual_lock_conflict, bool):
        return RaceResultRevisionActionDecision(
            "reject", "invalid_manual_lock_conflict"
        )

    # Evidence quality and an operator freeze take precedence over source policy.
    if not identity_valid:
        return RaceResultRevisionActionDecision("reject", "identity_invalid")
    if not payload_complete:
        return RaceResultRevisionActionDecision("reject", "payload_incomplete")
    if manual_lock_conflict:
        return RaceResultRevisionActionDecision(
            "conflict",
            "manual_lock_conflict",
            conflict=True,
        )
    if not isinstance(official_marker, bool):
        return RaceResultRevisionActionDecision("reject", "invalid_official_marker")

    if not isinstance(current_state, str) or current_state not in RACE_LIVE_STATES:
        return RaceResultRevisionActionDecision("reject", "invalid_current_state")
    if current_phase not in (None, "provisional", "official", "corrected"):
        return RaceResultRevisionActionDecision("reject", "invalid_current_phase")
    if not isinstance(current_content_sha256, str) or (
        current_content_sha256
        and not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
            current_content_sha256
        )
    ):
        return RaceResultRevisionActionDecision(
            "reject", "invalid_current_content_digest"
        )
    expected_current_result = {
        "scheduled": (None, ""),
        "racecard_ready": (None, ""),
        "awaiting_result": (None, ""),
        "provisional_result": ("provisional", "digest"),
        "official_result": ("official", "digest"),
        "corrected_result": ("corrected", "digest"),
    }[current_state]
    expected_phase, expected_digest = expected_current_result
    if current_phase != expected_phase or bool(current_content_sha256) != bool(
        expected_digest
    ):
        return RaceResultRevisionActionDecision(
            "reject", "current_result_inconsistent"
        )

    if incoming_phase not in ("provisional", "official", "corrected"):
        return RaceResultRevisionActionDecision("reject", "invalid_incoming_phase")
    if (
        not isinstance(incoming_content_sha256, str)
        or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(
            incoming_content_sha256
        )
    ):
        return RaceResultRevisionActionDecision("reject", "invalid_content_digest")
    if source_authority not in ("official", "supplemental"):
        return RaceResultRevisionActionDecision(
            "reject", "invalid_source_authority"
        )

    if incoming_phase in ("official", "corrected"):
        if source_authority != "official":
            return RaceResultRevisionActionDecision(
                "reject", "official_authority_required"
            )
        if not official_marker:
            return RaceResultRevisionActionDecision(
                "reject", "official_marker_required"
            )

    if (
        current_phase == incoming_phase
        and current_content_sha256 == incoming_content_sha256
    ):
        return RaceResultRevisionActionDecision("replay", "content_replayed")

    if incoming_phase == "provisional":
        if current_state == "awaiting_result":
            return RaceResultRevisionActionDecision(
                "apply",
                "provisional_result_accepted",
                next_state="provisional_result",
                next_phase="provisional",
            )
        if current_state == "provisional_result":
            reason = (
                "supplemental_result_conflict"
                if source_authority == "supplemental"
                else "provisional_result_conflict"
            )
            return RaceResultRevisionActionDecision(
                "conflict", reason, conflict=True
            )
        return RaceResultRevisionActionDecision("reject", "result_phase_regression")

    if incoming_phase == "official":
        if current_state in ("awaiting_result", "provisional_result"):
            return RaceResultRevisionActionDecision(
                "apply",
                "official_result_accepted",
                next_state="official_result",
                next_phase="official",
            )
        if current_state == "official_result":
            return RaceResultRevisionActionDecision(
                "conflict",
                "official_change_requires_correction",
                conflict=True,
            )
        return RaceResultRevisionActionDecision("reject", "result_phase_regression")

    if current_state not in ("official_result", "corrected_result"):
        return RaceResultRevisionActionDecision(
            "reject", "correction_requires_official_result"
        )
    return RaceResultRevisionActionDecision(
        "apply",
        "official_correction_accepted",
        next_state="corrected_result",
        next_phase="corrected",
    )


def _canonicalize_race_live_strict_json(value: Any) -> Any:
    if isinstance(value, dict):
        canonicalized = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("race live canonical payload keys must be strings")
            canonicalized[key] = _canonicalize_race_live_strict_json(item)
        return canonicalized
    if isinstance(value, list):
        return [_canonicalize_race_live_strict_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("race live canonical payload numbers must be finite")
        if value.is_integer():
            return int(value)
        return value
    raise TypeError("race live canonical payload must contain only strict JSON values")


def build_race_live_canonical_sha256(
    *,
    normalized_payload: dict,
    result_phase: str | None = None,
) -> str:
    """Return the SHA-256 digest of a deterministic strict-JSON object."""
    if not isinstance(normalized_payload, dict):
        raise TypeError("race live canonical payload must be a JSON object")
    if result_phase is not None and result_phase not in {
        "racecard",
        "provisional",
        "official",
        "corrected",
        "unknown",
    }:
        raise ValueError("race live result phase is invalid")
    canonical_payload = _canonicalize_race_live_strict_json(normalized_payload)
    canonical_json = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def record_race_result_observation(
    *,
    source_identity_id: int,
    observed_at: datetime,
    source_updated_at: datetime | None,
    parser_version: str,
    raw_sha256: str,
    result_phase: str,
    normalized_payload: dict,
    field_provenance: dict,
    parse_warnings: list,
    permission_classification: str,
) -> RaceResultObservationRecordDecision:
    """Append one normalized source observation without rewriting prior evidence."""
    if (
        isinstance(source_identity_id, bool)
        or not isinstance(source_identity_id, int)
        or source_identity_id <= 0
    ):
        return RaceResultObservationRecordDecision(False, "invalid_source_identity")
    if not isinstance(observed_at, datetime) or timezone.is_naive(observed_at):
        return RaceResultObservationRecordDecision(False, "invalid_observed_at")
    if source_updated_at is not None and (
        not isinstance(source_updated_at, datetime)
        or timezone.is_naive(source_updated_at)
    ):
        return RaceResultObservationRecordDecision(False, "invalid_source_updated_at")
    if (
        not isinstance(parser_version, str)
        or not parser_version
        or len(parser_version) > 64
        or parser_version.strip() != parser_version
    ):
        return RaceResultObservationRecordDecision(False, "invalid_parser_version")
    if (
        not isinstance(raw_sha256, str)
        or not RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(raw_sha256)
    ):
        return RaceResultObservationRecordDecision(False, "invalid_raw_digest")
    if result_phase not in RaceResultPhase.values:
        return RaceResultObservationRecordDecision(False, "invalid_phase")
    if not isinstance(normalized_payload, dict):
        return RaceResultObservationRecordDecision(False, "invalid_payload")
    try:
        normalized_sha256 = build_race_live_canonical_sha256(
            normalized_payload=normalized_payload
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        return RaceResultObservationRecordDecision(False, "invalid_payload")
    if not isinstance(field_provenance, dict):
        return RaceResultObservationRecordDecision(False, "invalid_provenance")
    try:
        json.dumps(field_provenance, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return RaceResultObservationRecordDecision(False, "invalid_provenance")
    if not isinstance(parse_warnings, list):
        return RaceResultObservationRecordDecision(False, "invalid_warnings")
    try:
        json.dumps(parse_warnings, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return RaceResultObservationRecordDecision(False, "invalid_warnings")
    if (
        not isinstance(permission_classification, str)
        or not permission_classification
        or len(permission_classification) > 32
        or permission_classification.strip() != permission_classification
    ):
        return RaceResultObservationRecordDecision(False, "invalid_permission")

    lookup = {
        "source_identity_id": source_identity_id,
        "normalized_sha256": normalized_sha256,
        "result_phase": result_phase,
    }
    defaults = {
        "observed_at": observed_at,
        "source_updated_at": source_updated_at,
        "parser_version": parser_version,
        "raw_sha256": raw_sha256,
        "normalized_payload": normalized_payload,
        "field_provenance": field_provenance,
        "parse_warnings": parse_warnings,
        "permission_classification": permission_classification,
    }
    try:
        with transaction.atomic():
            if not RaceResultSourceIdentity.objects.filter(
                pk=source_identity_id
            ).exists():
                return RaceResultObservationRecordDecision(False, "source_missing")
            observation, created = RaceResultObservation.objects.get_or_create(
                **lookup,
                defaults=defaults,
            )
    except IntegrityError:
        observation = RaceResultObservation.objects.filter(**lookup).first()
        if observation is None:
            if not RaceResultSourceIdentity.objects.filter(
                pk=source_identity_id
            ).exists():
                return RaceResultObservationRecordDecision(False, "source_missing")
            return RaceResultObservationRecordDecision(False, "observation_conflict")
        created = False

    return RaceResultObservationRecordDecision(
        True,
        "observation_recorded" if created else "observation_replayed",
        created=created,
        observation=observation,
    )


def apply_race_live_racecard_refresh(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    now: datetime,
    normalized_racecard: dict[str, Any],
    raw_sha256: str,
    merge_participants,
) -> RaceLiveRacecardRefreshDecision:
    """Apply one already-fetched pre-off racecard under owner and claim CAS."""

    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
        or not isinstance(now, datetime)
        or timezone.is_naive(now)
        or not isinstance(normalized_racecard, dict)
        or not callable(merge_participants)
        or not isinstance(raw_sha256, str)
        or RACE_PROJECTION_MANIFEST_SHA256_RE.fullmatch(raw_sha256) is None
    ):
        return RaceLiveRacecardRefreshDecision(False, "invalid_input")
    source = RaceResultSourceIdentity.objects.filter(
        event_id=event_id,
        source_key="the_racing_api",
    ).first()
    if source is None:
        return RaceLiveRacecardRefreshDecision(False, "source_missing")
    if normalized_racecard.get("external_race_id") != source.external_race_id:
        return RaceLiveRacecardRefreshDecision(
            False, "external_race_id_mismatch"
        )
    incoming = normalized_racecard.get("participants")
    if not isinstance(incoming, (list, tuple)):
        return RaceLiveRacecardRefreshDecision(False, "participants_invalid")
    observation_payload = {
        **normalized_racecard,
        "schema_version": normalized_racecard.get("schema_version", 1),
        "participants": [dict(row) if isinstance(row, dict) else row for row in incoming],
    }

    with transaction.atomic():
        try:
            RaceEventLifecycleControl.objects.select_for_update().filter(
                event_id=event_id
            ).first()
            event = RaceEvent.objects.select_for_update().get(pk=event_id)
            control = RaceEventProjectionControl.objects.select_for_update().get(
                event_id=event_id
            )
            tracking = RaceEventLiveTracking.objects.select_for_update().get(
                event_id=event_id
            )
        except (
            RaceEvent.DoesNotExist,
            RaceEventProjectionControl.DoesNotExist,
            RaceEventLiveTracking.DoesNotExist,
        ):
            return RaceLiveRacecardRefreshDecision(False, "baseline_missing")
        if (
            control.write_owner != RaceEventProjectionWriteOwner.LIVE
            or control.owner_generation != expected_owner_generation
        ):
            return RaceLiveRacecardRefreshDecision(False, "owner_mismatch")
        if (
            tracking.claim_generation != expected_claim_generation
            or tracking.active_attempt_token != attempt_token
            or tracking.claim_expires_at is None
            or tracking.claim_expires_at <= now
        ):
            return RaceLiveRacecardRefreshDecision(False, "claim_mismatch")
        if tracking.state not in {
            RaceEventLiveState.SCHEDULED,
            RaceEventLiveState.RACECARD_READY,
        }:
            return RaceLiveRacecardRefreshDecision(
                False, "racecard_refresh_window_closed"
            )
        if event.race_datetime is not None and now >= event.race_datetime:
            return RaceLiveRacecardRefreshDecision(
                False, "racecard_refresh_window_closed"
            )
        locks = (
            event.manual_lock_flags
            if isinstance(event.manual_lock_flags, dict)
            else {}
        )
        if (
            locks.get(RaceEventModule.RUNNERS)
            or locks.get(RaceEventModule.RESULTS)
        ):
            return RaceLiveRacecardRefreshDecision(
                False, "event_manual_lock_conflict"
            )
        current = (
            RaceEventRevision.objects.select_for_update()
            .filter(
                pk=control.current_racecard_revision_id,
                event_id=event_id,
                kind=RaceEventRevisionKind.RACECARD,
                phase=RaceResultPhase.RACECARD,
            )
            .first()
        )
        if current is None:
            return RaceLiveRacecardRefreshDecision(
                False, "current_racecard_missing"
            )
        existing_identity_rows = list(
            RaceEventParticipantSourceIdentity.objects.select_for_update()
            .filter(
                source_identity=source,
                participant__event_id=event_id,
            )
            .select_related("participant")
        )
        identity_by_external = {
            row.external_runner_id: row for row in existing_identity_rows
        }
        previous_items = {
            item.participant_id: item
            for item in current.items.select_related("participant").all()
        }
        previous = []
        for identity in existing_identity_rows:
            item = previous_items.get(identity.participant_id)
            if item is None:
                continue
            previous.append(
                {
                    "external_runner_id": identity.external_runner_id,
                    "horse_name": identity.participant.canonical_name,
                    "number": item.horse_number,
                    "draw": item.barrier,
                    "jockey_name": item.jockey_name,
                    "trainer_name": item.trainer_name,
                    "carried_weight": item.carried_weight,
                    "status": item.status,
                }
            )
        try:
            merged = merge_participants(
                previous=tuple(previous),
                incoming=tuple(incoming),
            )
        except (TypeError, ValueError, PermissionError):
            return RaceLiveRacecardRefreshDecision(
                False, "participants_merge_rejected"
            )
        merged_rows = list(merged["participants"])
        canonical_payload = {
            **normalized_racecard,
            "participants": merged_rows,
            "missing_runner_source_gaps": list(
                merged["missing_runner_source_gaps"]
            ),
        }
        proposed_off_time = event.race_datetime
        proposed_local_start_time = event.local_start_time
        source_off_time = normalized_racecard.get("off_time")
        if isinstance(source_off_time, str) and event.timezone_name:
            try:
                parsed_off = datetime.fromisoformat(
                    source_off_time.replace("Z", "+00:00")
                )
                if timezone.is_naive(parsed_off):
                    raise ValueError("source off time must be aware")
                event_timezone = ZoneInfo(event.timezone_name)
                local_off = parsed_off.astimezone(event_timezone)
            except (TypeError, ValueError, KeyError):
                return RaceLiveRacecardRefreshDecision(
                    False, "off_time_change_rejected"
                )
            if (
                local_off.date() != event.local_date
                or (
                    event.race_datetime is not None
                    and abs(
                        (parsed_off - event.race_datetime).total_seconds()
                    )
                    > 12 * 60 * 60
                )
            ):
                return RaceLiveRacecardRefreshDecision(
                    False, "off_time_change_rejected"
                )
            proposed_off_time = parsed_off
            proposed_local_start_time = local_off.time().replace(tzinfo=None)
        content_sha256 = build_race_live_canonical_sha256(
            normalized_payload=canonical_payload
        )
        existing_revision = RaceEventRevision.objects.filter(
            event_id=event_id,
            kind=RaceEventRevisionKind.RACECARD,
            phase=RaceResultPhase.RACECARD,
            content_sha256=content_sha256,
        ).first()

        for row in merged_rows:
            if row["external_runner_id"] in identity_by_external:
                continue
            horse_name = row.get("horse_name")
            if (
                not isinstance(horse_name, str)
                or not horse_name
                or horse_name != horse_name.strip()
            ):
                return RaceLiveRacecardRefreshDecision(
                    False, "new_participant_name_missing"
                )

        legacy_runners = list(
            RaceEventRunner.objects.select_for_update()
            .filter(event_id=event_id)
            .order_by("id")
        )
        for legacy_runner in legacy_runners:
            external_runner_id = str(
                legacy_runner.external_runner_id or ""
            ).strip()
            source_external_runner_id = (
                str(
                    legacy_runner.source_refs.get(
                        "external_runner_id"
                    )
                    or ""
                ).strip()
                if isinstance(legacy_runner.source_refs, dict)
                else ""
            )
            if (
                external_runner_id
                and source_external_runner_id
                and external_runner_id
                != source_external_runner_id
            ):
                return RaceLiveRacecardRefreshDecision(
                    False, "legacy_runner_identity_conflict"
                )
        legacy_by_external: dict[str, RaceEventRunner | None] = {}
        for row in merged_rows:
            external_runner_id = row["external_runner_id"]
            external_matches = [
                runner
                for runner in legacy_runners
                if runner.external_runner_id == external_runner_id
            ][:2]
            if len(external_matches) > 1:
                return RaceLiveRacecardRefreshDecision(
                    False, "legacy_runner_identity_ambiguous"
                )
            legacy_matches = [
                runner
                for runner in legacy_runners
                if not runner.external_runner_id
                and isinstance(runner.source_refs, dict)
                and str(
                    runner.source_refs.get("external_runner_id") or ""
                ).strip()
                == external_runner_id
            ][:2]
            if len(legacy_matches) > 1:
                return RaceLiveRacecardRefreshDecision(
                    False, "legacy_runner_identity_ambiguous"
                )
            if external_matches and legacy_matches:
                return RaceLiveRacecardRefreshDecision(
                    False, "legacy_runner_identity_conflict"
                )
            legacy_by_external[external_runner_id] = (
                external_matches[0]
                if external_matches
                else legacy_matches[0]
                if legacy_matches
                else None
            )

        from stable.services.race_data_sync_pipeline import (
            build_race_data_provider_roster,
            reconcile_racecard_observation,
        )

        contract_region_by_event_region = {
            RacingRegion.HONG_KONG: "hong_kong",
            RacingRegion.UNITED_KINGDOM: "united_kingdom",
            RacingRegion.FRANCE: "france",
            RacingRegion.UNITED_STATES: "united_states",
        }
        contract_region = contract_region_by_event_region.get(event.country_region)
        if event.country_region == RacingRegion.OTHER:
            region_markers = []
            if (
                isinstance(event.source_refs, dict)
                and "race_data_region" in event.source_refs
            ):
                region_markers.append(event.source_refs["race_data_region"])
            if (
                source.review_status == RaceLiveReviewStatus.APPROVED
                and isinstance(source.identity_fields, dict)
                and "race_data_region" in source.identity_fields
            ):
                region_markers.append(source.identity_fields["race_data_region"])
            if region_markers and all(
                isinstance(marker, str) and marker == "ireland"
                for marker in region_markers
            ):
                contract_region = "ireland"
        roster = build_race_data_provider_roster()
        roster_entry = next(
            (
                entry
                for entry in roster.entries
                if entry.provider == source.source_key
                and contract_region in entry.regions
            ),
            None,
        )
        if roster_entry is None or contract_region is None:
            return RaceLiveRacecardRefreshDecision(
                False, "provider_contract_missing"
            )
        observation_decision = record_race_result_observation(
            source_identity_id=source.pk,
            observed_at=now,
            source_updated_at=None,
            parser_version="the_racing_api_racecard_refresh_v2",
            raw_sha256=raw_sha256,
            result_phase=RaceResultPhase.RACECARD,
            normalized_payload=observation_payload,
            field_provenance={
                "provider": source.source_key,
                "region": contract_region,
                "source_class": roster_entry.source_class,
                "registry_digest": roster.registry_digest,
                "contract_version": roster_entry.contract_version,
                "contract_digest": roster_entry.contract_digest,
                "automation_allowed": True,
                "allowed_fields": [
                    "off_time",
                    "local_start_time",
                    "participants.horse_name",
                    "participants.number",
                    "participants.draw",
                    "participants.jockey_name",
                    "participants.trainer_name",
                    "participants.carried_weight",
                    "participants.status",
                    "participants.odds",
                    "participants.popularity",
                ],
            },
            parse_warnings=[],
            permission_classification="licensed_api_automation",
        )
        if (
            observation_decision.recorded is not True
            or observation_decision.observation is None
        ):
            return RaceLiveRacecardRefreshDecision(
                False, f"observation_{observation_decision.reason}"
            )
        observation = observation_decision.observation
        field_decision = reconcile_racecard_observation(
            observation_id=observation.pk,
            expected_event_id=event_id,
            allow_schedule_apply=False,
            task_id="race_live_racecard_refresh",
            run_id=attempt_token[:64],
        )
        if field_decision.status not in {"applied", "replayed"}:
            checkpoint_status = (
                "racecard_needs_review"
                if field_decision.status == "needs_review"
                else field_decision.reason
            )
            tracking.next_poll_at = calculate_race_live_next_poll_at(
                off_time=event.race_datetime,
                now=now,
                state=tracking.state,
            )
            tracking.last_observation_hash = observation.normalized_sha256
            tracking.active_attempt_token = ""
            tracking.claim_expires_at = None
            tracking.checkpoint_payload = {
                "status": checkpoint_status,
                "observation_id": observation.pk,
            }
            tracking.lock_version += 1
            tracking.save()
            decision_reason = (
                "racecard_needs_review"
                if field_decision.status == "needs_review"
                else field_decision.reason
            )
            return RaceLiveRacecardRefreshDecision(
                False, f"field_{decision_reason}"
            )

        canonical_runners = list(
            RaceEventRunner.objects.select_for_update()
            .filter(event_id=event_id)
            .order_by("id")
        )
        canonical_rows = []
        for row in merged_rows:
            external_runner_id = row["external_runner_id"]
            runner = next(
                (
                    candidate
                    for candidate in canonical_runners
                    if (
                        isinstance(candidate.source_refs, dict)
                        and candidate.source_refs.get(source.source_key)
                        == external_runner_id
                    )
                    or candidate.external_runner_id == external_runner_id
                ),
                None,
            )
            if runner is None:
                return RaceLiveRacecardRefreshDecision(
                    False, "canonical_runner_missing"
                )
            canonical_rows.append(
                {
                    "external_runner_id": external_runner_id,
                    "horse_name": runner.horse_name,
                    "number": runner.horse_number,
                    "draw": runner.barrier,
                    "jockey_name": runner.jockey_name,
                    "trainer_name": runner.trainer_name,
                    "carried_weight": runner.carried_weight,
                    "status": runner.running_status,
                    "odds": runner.odds_value,
                    "popularity": runner.popularity,
                }
            )
        merged_rows = canonical_rows
        canonical_payload = {
            **canonical_payload,
            "participants": canonical_rows,
        }
        content_sha256 = build_race_live_canonical_sha256(
            normalized_payload=canonical_payload
        )
        existing_revision = RaceEventRevision.objects.filter(
            event_id=event_id,
            kind=RaceEventRevisionKind.RACECARD,
            phase=RaceResultPhase.RACECARD,
            content_sha256=content_sha256,
        ).first()

        if existing_revision is not None:
            # Preserve the pre-existing deterministic identity remediation for
            # an unchanged revision.  This only fills a blank identity column;
            # provider-controlled racecard fields remain gated by the unified
            # Slice-A ledger above.
            for external_runner_id, legacy_runner in legacy_by_external.items():
                if legacy_runner is not None and not legacy_runner.external_runner_id:
                    legacy_runner.external_runner_id = external_runner_id
                    legacy_runner.save(
                        update_fields=("external_runner_id", "updated_at")
                    )
            tracking.next_poll_at = calculate_race_live_next_poll_at(
                off_time=event.race_datetime,
                now=now,
                state=tracking.state,
            )
            tracking.last_success_at = now
            tracking.last_observation_hash = observation.normalized_sha256
            tracking.active_attempt_token = ""
            tracking.claim_expires_at = None
            tracking.checkpoint_payload = {
                "status": "racecard_replayed",
                "revision_id": existing_revision.pk,
                "missing_runner_source_gaps": list(
                    merged["missing_runner_source_gaps"]
                ),
            }
            tracking.lock_version += 1
            tracking.save()
            return RaceLiveRacecardRefreshDecision(
                True,
                "racecard_replayed",
                revision_id=existing_revision.pk,
                replayed=True,
            )

        participants_by_external: dict[str, RaceEventParticipant] = {}
        for row in merged_rows:
            external_runner_id = row["external_runner_id"]
            identity = identity_by_external.get(external_runner_id)
            if identity is None:
                horse_name = row["horse_name"]
                participant = RaceEventParticipant.objects.create(
                    event_id=event_id,
                    stable_key=(
                        "tra:"
                        + hashlib.sha256(
                            external_runner_id.encode("utf-8")
                        ).hexdigest()
                    ),
                    canonical_name=horse_name,
                    country_region="",
                    review_status=RaceLiveReviewStatus.APPROVED,
                )
                RaceEventParticipantSourceIdentity.objects.create(
                    participant=participant,
                    source_identity=source,
                    external_runner_id=external_runner_id,
                )
            else:
                participant = identity.participant
            participants_by_external[external_runner_id] = participant

        revision = RaceEventRevision.objects.create(
            event_id=event_id,
            kind=RaceEventRevisionKind.RACECARD,
            revision_no=control.next_racecard_revision_no,
            phase=RaceResultPhase.RACECARD,
            content_sha256=content_sha256,
            source_authority=RaceResultSourceAuthority.SUPPLEMENTAL,
            decision_reason="pre-off source racecard refresh",
            primary_observation=observation,
            supersedes=current,
        )
        RaceEventRevisionItem.objects.bulk_create(
            [
                RaceEventRevisionItem(
                    revision=revision,
                    participant=participants_by_external[
                        row["external_runner_id"]
                    ],
                    source_order=index,
                    internal_order=index,
                    status=str(
                        row.get(
                            "status", RaceEventRevisionItemStatus.DECLARED
                        )
                    ),
                    raw_status=str(
                        row.get("status", RaceEventRevisionItemStatus.DECLARED)
                    ),
                    horse_number=str(row.get("number", "")),
                    barrier=str(row.get("draw", row.get("barrier", ""))),
                    jockey_name=str(row.get("jockey_name", "")),
                    trainer_name=str(row.get("trainer_name", "")),
                    carried_weight=str(row.get("carried_weight", "")),
                    field_provenance={
                        "source_key": source.source_key,
                        "external_runner_id": row["external_runner_id"],
                    },
                )
                for index, row in enumerate(merged_rows, start=1)
            ]
        )
        RaceEventRevisionEvidence.objects.create(
            revision=revision,
            observation=observation,
            role="primary",
        )
        control.current_racecard_revision = revision
        control.last_known_good_racecard_revision = current
        control.next_racecard_revision_no += 1
        control.save(
            update_fields=(
                "current_racecard_revision",
                "last_known_good_racecard_revision",
                "next_racecard_revision_no",
                "updated_at",
            )
        )
        # Slice A records schedule candidates but cannot apply them.  Slice C
        # owns the lifecycle generation/claim invalidation transaction.
        tracking.next_poll_at = calculate_race_live_next_poll_at(
            off_time=event.race_datetime,
            now=now,
            state=tracking.state,
        )
        tracking.last_success_at = now
        tracking.last_observation_hash = observation.normalized_sha256
        tracking.active_attempt_token = ""
        tracking.claim_expires_at = None
        tracking.checkpoint_payload = {
            "status": "racecard_refreshed",
            "revision_id": revision.pk,
            "missing_runner_source_gaps": list(
                merged["missing_runner_source_gaps"]
            ),
        }
        tracking.lock_version += 1
        tracking.save()
        return RaceLiveRacecardRefreshDecision(
            True,
            "racecard_refreshed",
            revision_id=revision.pk,
        )


def _publish_race_result_revision(
    *,
    event_id: int,
    revision: RaceEventRevision,
    observation: RaceResultObservation,
    normalized_items: list[dict],
    identities: dict[str, Any],
    tracking: RaceEventLiveTracking,
    published_at: datetime,
    publication_reason: str,
    policy_versions: list[list[Any]] | None = None,
    allowlist_version: int = 1,
    registry_digest: str = "",
    coverage_proof_digest: str = "",
    authorization_kind: str = "provisional_policy",
    official_authorization_version: int = 0,
) -> None:
    """Audit and materialize one result revision inside the caller transaction."""
    if revision.published_at is None:
        # PostgreSQL's immutable guard requires the audit row to exist before the
        # one permitted NULL -> non-NULL publication transition.
        RaceEventRevisionPublication.objects.create(
            revision=revision,
            published_at=published_at,
            reason=publication_reason,
            policy_versions=policy_versions or [],
            allowlist_version=allowlist_version,
            registry_digest=registry_digest,
            coverage_proof_digest=coverage_proof_digest,
            authorization_kind=authorization_kind,
            official_authorization_version=official_authorization_version,
        )
        revision.published_at = published_at
        revision.save(update_fields=("published_at", "updated_at"))
    else:
        publication, created = RaceEventRevisionPublication.objects.get_or_create(
            revision=revision,
            defaults={
                "published_at": revision.published_at,
                "reason": publication_reason,
                "policy_versions": policy_versions or [],
                "allowlist_version": allowlist_version,
                "registry_digest": registry_digest,
                "coverage_proof_digest": coverage_proof_digest,
                "authorization_kind": authorization_kind,
                "official_authorization_version": (
                    official_authorization_version
                ),
            },
        )
        if not created and publication.published_at != revision.published_at:
            raise IntegrityError("revision publication audit timestamp mismatch")

    is_confirmed = revision.phase in (
        RaceResultPhase.OFFICIAL,
        RaceResultPhase.CORRECTED,
    )
    event = RaceEvent.objects.select_for_update().get(pk=event_id)
    if event.status in {
        RaceEventStatus.CANCELLED,
        RaceEventStatus.POSTPONED,
    }:
        raise IntegrityError("cancelled or postponed race cannot publish a result")
    if event.status not in {
        RaceEventStatus.SCHEDULED,
        RaceEventStatus.RUNNING,
        RaceEventStatus.FINISHED,
    }:
        raise IntegrityError("race status cannot publish a result")
    racecard_revision = (
        RaceEventRevision.objects.filter(
            pk=RaceEventProjectionControl.objects.filter(
                event_id=event_id
            ).values_list("current_racecard_revision_id", flat=True).first(),
            event_id=event_id,
            kind=RaceEventRevisionKind.RACECARD,
            phase=RaceResultPhase.RACECARD,
        )
        .first()
    )
    racecard_items = (
        {
            item.participant_id: item
            for item in racecard_revision.items.all()
        }
        if racecard_revision is not None
        else {}
    )

    result_rows: list[RaceEventResult] = []
    for index, item in enumerate(normalized_items, start=1):
        participant = identities[item["external_runner_id"]]
        source_refs: dict[str, Any] = {
            "source_key": observation.source_identity.source_key,
            "external_race_id": observation.source_identity.external_race_id,
            "external_runner_id": item["external_runner_id"],
        }
        field_provenance: dict[str, Any] = {}
        racecard_item = racecard_items.get(participant.pk)
        barrier = item["barrier"]
        jockey_name = item["jockey_name"]
        if (
            publication_reason == "shadow_promotion"
            and observation.source_identity.source_key == "the_racing_api"
            and racecard_item is not None
        ):
            for field_name in ("barrier", "jockey_name"):
                current_value = (
                    barrier if field_name == "barrier" else jockey_name
                )
                fallback_value = getattr(racecard_item, field_name)
                if not current_value and fallback_value:
                    if field_name == "barrier":
                        barrier = racecard_item.barrier
                    else:
                        jockey_name = racecard_item.jockey_name
                    racecard_source_key = (
                        racecard_item.field_provenance.get("source_key")
                        if isinstance(racecard_item.field_provenance, dict)
                        else None
                    )
                    field_provenance[field_name] = {
                        "racecard_revision_id": racecard_revision.pk,
                        "racecard_revision_item_id": racecard_item.pk,
                        "source_key": (
                            racecard_source_key
                            if isinstance(racecard_source_key, str)
                            and racecard_source_key
                            else observation.source_identity.source_key
                        ),
                    }
        if field_provenance:
            source_refs["field_provenance"] = field_provenance
        result_rows.append(
            RaceEventResult(
                event_id=event_id,
                finish_position=index,
                official_finish_position=item["official_finish_position"],
                horse_number=item["number"],
                horse_name=participant.canonical_name,
                jockey_name=jockey_name,
                trainer_name=item["trainer_name"],
                finish_time=item["finish_time"],
                margin=item["margin"],
                barrier=barrier,
                carried_weight=item["carried_weight"],
                running_status=item["status"],
                is_confirmed=is_confirmed,
                source_refs=source_refs,
                raw_payload={},
            )
        )
    RaceEventResult.objects.filter(event_id=event_id).delete()
    RaceEventResult.objects.bulk_create(result_rows)

    tracking_fields = ["updated_at"]
    if revision.phase == RaceResultPhase.PROVISIONAL:
        tracking.provisional_published_at = published_at
        tracking_fields.append("provisional_published_at")
    elif revision.phase == RaceResultPhase.OFFICIAL:
        tracking.official_published_at = published_at
        tracking_fields.append("official_published_at")
    else:
        tracking.corrected_at = published_at
        tracking_fields.append("corrected_at")
    tracking.save(update_fields=tracking_fields)

    if revision.phase == RaceResultPhase.PROVISIONAL:
        control = RaceEventProjectionControl.objects.select_for_update().get(
            event_id=event_id
        )
        control.last_provisional_result_revision = revision
        control.save(
            update_fields=(
                "last_provisional_result_revision",
                "updated_at",
            )
        )

    event.status = RaceEventStatus.FINISHED
    update_fields = ["status", "updated_at"]
    if is_confirmed:
        event.result_confirmed_at = published_at
        update_fields.append("result_confirmed_at")
    event.save(update_fields=update_fields)


def apply_race_result_observation_revision(
    *,
    observation_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    now: datetime,
    source_authority: str,
    official_marker: bool,
    identity_valid: bool,
    payload_complete: bool,
    manual_lock_conflict: bool,
    project_current: bool,
    official_marker_evidence_id: int | None = None,
) -> RaceResultRevisionApplyDecision:
    """Apply one validated observation under the live owner and claim leases."""
    if (
        isinstance(observation_id, bool)
        or not isinstance(observation_id, int)
        or observation_id <= 0
    ):
        return RaceResultRevisionApplyDecision(False, "reject", "invalid_observation")
    for value, reason in (
        (expected_owner_generation, "invalid_owner_generation"),
        (expected_claim_generation, "invalid_claim_generation"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return RaceResultRevisionApplyDecision(False, "reject", reason)
    if (
        not isinstance(attempt_token, str)
        or not attempt_token
        or len(attempt_token) > 64
        or attempt_token.strip() != attempt_token
    ):
        return RaceResultRevisionApplyDecision(False, "reject", "invalid_attempt_token")
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return RaceResultRevisionApplyDecision(False, "reject", "invalid_now")
    if source_authority not in RaceResultSourceAuthority.values:
        return RaceResultRevisionApplyDecision(False, "reject", "invalid_source_authority")
    if official_marker_evidence_id is not None and (
        isinstance(official_marker_evidence_id, bool)
        or not isinstance(official_marker_evidence_id, int)
        or official_marker_evidence_id <= 0
    ):
        return RaceResultRevisionApplyDecision(
            False, "reject", "invalid_official_marker_evidence"
        )
    for value, reason in (
        (official_marker, "invalid_official_marker"),
        (identity_valid, "invalid_identity_valid"),
        (payload_complete, "invalid_payload_complete"),
        (manual_lock_conflict, "invalid_manual_lock_conflict"),
        (project_current, "invalid_project_current"),
    ):
        if not isinstance(value, bool):
            return RaceResultRevisionApplyDecision(False, "reject", reason)

    observation_hint = RaceResultObservation.objects.filter(
        pk=observation_id
    ).values("source_identity__event_id").first()
    if observation_hint is None:
        return RaceResultRevisionApplyDecision(False, "reject", "observation_missing")
    event_id = observation_hint["source_identity__event_id"]

    with transaction.atomic():
        try:
            control = (
                RaceEventProjectionControl.objects.select_for_update(of=("self",))
                .get(event_id=event_id)
            )
        except RaceEventProjectionControl.DoesNotExist:
            return RaceResultRevisionApplyDecision(False, "reject", "control_missing")
        if (
            control.write_owner != RaceEventProjectionWriteOwner.LIVE
            or control.owner_generation != expected_owner_generation
        ):
            return RaceResultRevisionApplyDecision(False, "reject", "owner_mismatch")

        try:
            tracking = RaceEventLiveTracking.objects.select_for_update().get(
                event_id=event_id
            )
        except RaceEventLiveTracking.DoesNotExist:
            return RaceResultRevisionApplyDecision(False, "reject", "tracking_missing")
        if (
            tracking.claim_generation != expected_claim_generation
            or tracking.active_attempt_token != attempt_token
        ):
            return RaceResultRevisionApplyDecision(False, "reject", "claim_mismatch")
        if tracking.claim_expires_at is None:
            return RaceResultRevisionApplyDecision(False, "reject", "claim_missing_expiry")
        if tracking.claim_expires_at <= now:
            return RaceResultRevisionApplyDecision(False, "reject", "claim_expired")

        try:
            observation = RaceResultObservation.objects.get(pk=observation_id)
        except RaceResultObservation.DoesNotExist:
            return RaceResultRevisionApplyDecision(False, "reject", "observation_missing")
        try:
            source_identity = (
                RaceResultSourceIdentity.objects.select_for_update()
                .select_related("event")
                .get(pk=observation.source_identity_id)
            )
        except RaceResultSourceIdentity.DoesNotExist:
            return RaceResultRevisionApplyDecision(False, "reject", "source_missing")
        observation.source_identity = source_identity
        if source_identity.event_id != event_id:
            return RaceResultRevisionApplyDecision(False, "reject", "observation_event_mismatch")
        if source_authority != source_identity.result_authority:
            return RaceResultRevisionApplyDecision(
                False, "reject", "source_authority_mismatch"
            )
        if (
            project_current is True
            and source_identity.result_authority
            == RaceResultSourceAuthority.SUPPLEMENTAL
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "publication_admission_required"
            )
        if (
            source_identity.result_authority == RaceResultSourceAuthority.OFFICIAL
            and source_identity.review_status != RaceLiveReviewStatus.APPROVED
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "official_source_not_approved"
            )
        if observation.result_phase not in (
            RaceResultPhase.PROVISIONAL,
            RaceResultPhase.OFFICIAL,
            RaceResultPhase.CORRECTED,
        ):
            return RaceResultRevisionApplyDecision(False, "reject", "invalid_observation_phase")
        if (
            observation.result_phase == RaceResultPhase.PROVISIONAL
            and official_marker_evidence_id is not None
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "official_marker_evidence_not_allowed"
            )
        if observation.result_phase in (
            RaceResultPhase.OFFICIAL,
            RaceResultPhase.CORRECTED,
        ):
            if official_marker is True and official_marker_evidence_id is None:
                return RaceResultRevisionApplyDecision(
                    False, "reject", "official_marker_evidence_required"
                )
            if official_marker is False and official_marker_evidence_id is not None:
                return RaceResultRevisionApplyDecision(
                    False, "reject", "official_marker_evidence_without_marker"
                )
            if official_marker is True:
                try:
                    marker_evidence = (
                        RaceLiveOfficialMarkerEvidence.objects.select_for_update()
                        .select_related("contract")
                        .get(pk=official_marker_evidence_id)
                    )
                except RaceLiveOfficialMarkerEvidence.DoesNotExist:
                    return RaceResultRevisionApplyDecision(
                        False, "reject", "official_marker_evidence_missing"
                    )
                contract = marker_evidence.contract
                if marker_evidence.observation_id != observation.pk:
                    return RaceResultRevisionApplyDecision(
                        False,
                        "reject",
                        "official_marker_evidence_observation_mismatch",
                    )
                if (
                    contract.source_key != source_identity.source_key
                    or contract.country_region
                    != source_identity.event.country_region
                    or contract.parser_version != observation.parser_version
                ):
                    return RaceResultRevisionApplyDecision(
                        False, "reject", "official_marker_contract_route_mismatch"
                    )
                if contract.review_status != RaceLiveReviewStatus.APPROVED:
                    return RaceResultRevisionApplyDecision(
                        False, "reject", "official_marker_contract_not_approved"
                    )
                if (
                    not isinstance(contract.valid_until, datetime)
                    or timezone.is_naive(contract.valid_until)
                    or contract.valid_until <= now
                ):
                    return RaceResultRevisionApplyDecision(
                        False, "reject", "official_marker_contract_expired"
                    )
                allowed_marker_types = contract.allowed_marker_types
                if not isinstance(allowed_marker_types, list) or any(
                    type(marker_type) is not str
                    for marker_type in allowed_marker_types
                ):
                    return RaceResultRevisionApplyDecision(
                        False,
                        "reject",
                        "official_marker_contract_marker_types_invalid",
                    )
                if (
                    type(marker_evidence.marker_type) is not str
                    or not marker_evidence.marker_type
                    or marker_evidence.marker_type.strip()
                    != marker_evidence.marker_type
                ):
                    return RaceResultRevisionApplyDecision(
                        False, "reject", "official_marker_evidence_marker_type_invalid"
                    )
                if marker_evidence.marker_type not in allowed_marker_types:
                    return RaceResultRevisionApplyDecision(
                        False, "reject", "official_marker_evidence_marker_not_allowed"
                    )
                if marker_evidence.contract_digest != contract.contract_digest:
                    return RaceResultRevisionApplyDecision(
                        False, "reject", "official_marker_evidence_digest_mismatch"
                    )
                if marker_evidence.parser_version != contract.parser_version:
                    return RaceResultRevisionApplyDecision(
                        False, "reject", "official_marker_evidence_parser_mismatch"
                    )
                if marker_evidence.raw_sha256 != observation.raw_sha256:
                    return RaceResultRevisionApplyDecision(
                        False, "reject", "official_marker_evidence_raw_mismatch"
                    )
                if (
                    marker_evidence.source_timestamp is not None
                    and (
                        not isinstance(marker_evidence.source_timestamp, datetime)
                        or timezone.is_naive(marker_evidence.source_timestamp)
                    )
                ):
                    return RaceResultRevisionApplyDecision(
                        False, "reject", "official_marker_evidence_timestamp_invalid"
                    )
        payload = observation.normalized_payload
        if not isinstance(payload, dict):
            return RaceResultRevisionApplyDecision(False, "reject", "invalid_payload")
        try:
            expected_digest = build_race_live_canonical_sha256(
                normalized_payload=payload
            )
        except (TypeError, ValueError, OverflowError, RecursionError):
            return RaceResultRevisionApplyDecision(False, "reject", "invalid_payload")
        if expected_digest != observation.normalized_sha256:
            return RaceResultRevisionApplyDecision(
                False, "reject", "observation_digest_mismatch"
            )
        if payload.get("external_race_id") != source_identity.external_race_id:
            return RaceResultRevisionApplyDecision(False, "reject", "race_identity_mismatch")

        payload_items = payload.get("participants")
        if (
            not isinstance(payload_items, list)
            or not payload_items
            or len(payload_items) > 32767
        ):
            return RaceResultRevisionApplyDecision(False, "reject", "participants_missing")
        external_runner_ids: list[str] = []
        normalized_items: list[dict] = []
        string_fields = {
            "raw_status": 64,
            "finish_time": 64,
            "margin": 64,
            "number": 32,
            "barrier": 32,
            "jockey_name": 255,
            "trainer_name": 255,
            "carried_weight": 64,
        }
        non_finish_statuses = {
            RaceEventRevisionItemStatus.SCRATCHED,
            RaceEventRevisionItemStatus.WITHDRAWN,
            RaceEventRevisionItemStatus.NON_RUNNER,
            RaceEventRevisionItemStatus.DISQUALIFIED,
            RaceEventRevisionItemStatus.DID_NOT_FINISH,
            RaceEventRevisionItemStatus.PULLED_UP,
            RaceEventRevisionItemStatus.UNSEATED_RIDER,
            RaceEventRevisionItemStatus.FELL,
            RaceEventRevisionItemStatus.REFUSED,
        }
        for item in payload_items:
            if not isinstance(item, dict):
                return RaceResultRevisionApplyDecision(False, "reject", "invalid_participant")
            external_runner_id = item.get("external_runner_id")
            if (
                not isinstance(external_runner_id, str)
                or not external_runner_id
                or len(external_runner_id) > 128
                or external_runner_id.strip() != external_runner_id
                or external_runner_id in external_runner_ids
            ):
                return RaceResultRevisionApplyDecision(
                    False, "reject", "invalid_external_runner_id"
                )
            status = item.get("status")
            if status not in RaceEventRevisionItemStatus.values:
                return RaceResultRevisionApplyDecision(False, "reject", "invalid_result_status")
            official_position = item.get("official_finish_position")
            if official_position is None:
                if status not in non_finish_statuses:
                    return RaceResultRevisionApplyDecision(
                        False, "reject", "finish_position_required"
                    )
            elif (
                isinstance(official_position, bool)
                or not isinstance(official_position, int)
                or official_position <= 0
                or official_position > 32767
            ):
                return RaceResultRevisionApplyDecision(
                    False, "reject", "invalid_finish_position"
                )
            cleaned = {
                "external_runner_id": external_runner_id,
                "status": status,
                "official_finish_position": official_position,
            }
            for field, maximum in string_fields.items():
                value = item.get(field, "")
                if not isinstance(value, str) or len(value) > maximum:
                    return RaceResultRevisionApplyDecision(
                        False, "reject", f"invalid_{field}"
                    )
                cleaned[field] = value
            provenance = item.get("field_provenance", {})
            if not isinstance(provenance, dict):
                return RaceResultRevisionApplyDecision(False, "reject", "invalid_provenance")
            try:
                provenance = _canonicalize_race_live_strict_json(provenance)
                json.dumps(provenance, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError, OverflowError, RecursionError):
                return RaceResultRevisionApplyDecision(False, "reject", "invalid_provenance")
            cleaned["field_provenance"] = provenance
            external_runner_ids.append(external_runner_id)
            normalized_items.append(cleaned)

        identities = {
            row.external_runner_id: row.participant
            for row in RaceEventParticipantSourceIdentity.objects.select_related(
                "participant"
            ).filter(
                source_identity_id=observation.source_identity_id,
                external_runner_id__in=external_runner_ids,
                participant__event_id=event_id,
            )
        }
        if len(identities) != len(external_runner_ids):
            return RaceResultRevisionApplyDecision(
                False, "reject", "participant_identity_missing"
            )

        current_revision = control.current_result_revision
        if current_revision is not None and (
            current_revision.event_id != event_id
            or current_revision.kind != RaceEventRevisionKind.RESULT
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "current_revision_inconsistent"
            )
        action = decide_race_result_revision_action(
            current_state=tracking.state,
            current_phase=current_revision.phase if current_revision else None,
            current_content_sha256=(
                current_revision.content_sha256 if current_revision else ""
            ),
            incoming_phase=observation.result_phase,
            incoming_content_sha256=observation.normalized_sha256,
            source_authority=source_identity.result_authority,
            official_marker=official_marker,
            identity_valid=identity_valid,
            payload_complete=payload_complete,
            manual_lock_conflict=manual_lock_conflict,
        )
        if action.action == "reject":
            return RaceResultRevisionApplyDecision(False, "reject", action.reason)
        if action.action == "replay":
            if (
                project_current
                and current_revision is not None
                and current_revision.published_at is None
            ):
                _publish_race_result_revision(
                    event_id=event_id,
                    revision=current_revision,
                    observation=observation,
                    normalized_items=normalized_items,
                    identities=identities,
                    tracking=tracking,
                    published_at=now,
                    publication_reason="shadow_promotion",
                )
                return RaceResultRevisionApplyDecision(
                    True,
                    "promote",
                    "shadow_revision_promoted",
                    current_revision,
                )
            return RaceResultRevisionApplyDecision(
                False, "replay", action.reason, current_revision
            )
        if action.action == "conflict":
            if current_revision is not None:
                current_revision.conflict_status = RaceEventRevisionConflictStatus.PENDING
                current_revision.save(update_fields=("conflict_status", "updated_at"))
            return RaceResultRevisionApplyDecision(
                False, "conflict", action.reason, current_revision
            )

        revision_no = control.next_result_revision_no
        if revision_no < 1:
            return RaceResultRevisionApplyDecision(
                False, "reject", "revision_counter_invalid"
            )
        is_confirmed = observation.result_phase in (
            RaceResultPhase.OFFICIAL,
            RaceResultPhase.CORRECTED,
        )
        revision = RaceEventRevision.objects.create(
            event_id=event_id,
            kind=RaceEventRevisionKind.RESULT,
            revision_no=revision_no,
            phase=observation.result_phase,
            content_sha256=observation.normalized_sha256,
            source_authority=source_identity.result_authority,
            decision_reason=action.reason,
            primary_observation=observation,
            supersedes=current_revision,
            published_at=now if project_current else None,
            official_confirmed_at=now if is_confirmed else None,
        )
        revision_items = [
            RaceEventRevisionItem(
                revision=revision,
                participant=identities[item["external_runner_id"]],
                source_order=index,
                internal_order=index,
                official_finish_position=item["official_finish_position"],
                status=item["status"],
                raw_status=item["raw_status"],
                finish_time=item["finish_time"],
                margin=item["margin"],
                horse_number=item["number"],
                barrier=item["barrier"],
                jockey_name=item["jockey_name"],
                trainer_name=item["trainer_name"],
                carried_weight=item["carried_weight"],
                field_provenance=item["field_provenance"],
            )
            for index, item in enumerate(normalized_items, start=1)
        ]
        RaceEventRevisionItem.objects.bulk_create(revision_items)
        RaceEventRevisionEvidence.objects.create(
            revision=revision,
            observation=observation,
            role="primary",
        )

        control.current_result_revision = revision
        control.last_known_good_result_revision = current_revision or revision
        control.next_result_revision_no = revision_no + 1
        control.save(
            update_fields=(
                "current_result_revision",
                "last_known_good_result_revision",
                "next_result_revision_no",
                "updated_at",
            )
        )
        tracking.state = action.next_state
        tracking.last_observation_hash = observation.normalized_sha256
        tracking.save(update_fields=("state", "last_observation_hash", "updated_at"))

        if project_current:
            _publish_race_result_revision(
                event_id=event_id,
                revision=revision,
                observation=observation,
                normalized_items=normalized_items,
                identities=identities,
                tracking=tracking,
                published_at=now,
                publication_reason="direct_public_apply",
            )

        return RaceResultRevisionApplyDecision(True, "apply", action.reason, revision)


def _admit_race_live_publication_locked(
    *,
    observation_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int | None,
    attempt_token: str | None,
    now: datetime,
    operator_transition: bool,
) -> RaceResultRevisionApplyDecision:
    """Single transactional admission core shared by poll and operator paths."""
    if (
        isinstance(observation_id, bool)
        or not isinstance(observation_id, int)
        or observation_id <= 0
    ):
        return RaceResultRevisionApplyDecision(
            False, "reject", "invalid_observation"
        )
    for value, reason in ((expected_owner_generation, "invalid_owner_generation"),):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return RaceResultRevisionApplyDecision(False, "reject", reason)
    if not isinstance(operator_transition, bool):
        return RaceResultRevisionApplyDecision(
            False, "reject", "invalid_operator_transition"
        )
    if operator_transition:
        if expected_claim_generation is not None or attempt_token is not None:
            return RaceResultRevisionApplyDecision(
                False, "reject", "operator_claim_forbidden"
            )
    else:
        if (
            isinstance(expected_claim_generation, bool)
            or not isinstance(expected_claim_generation, int)
            or expected_claim_generation < 0
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "invalid_claim_generation"
            )
        if (
            not isinstance(attempt_token, str)
            or not attempt_token
            or len(attempt_token) > 64
            or attempt_token.strip() != attempt_token
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "invalid_attempt_token"
            )
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return RaceResultRevisionApplyDecision(False, "reject", "invalid_now")

    with transaction.atomic():
        observation_hint = RaceResultObservation.objects.filter(
            pk=observation_id
        ).values(
            "source_identity__event_id",
            "source_identity_id",
        ).first()
        if observation_hint is None:
            return RaceResultRevisionApplyDecision(
                False, "reject", "observation_missing"
            )
        event_id = observation_hint["source_identity__event_id"]

        try:
            control = (
                RaceEventProjectionControl.objects.select_for_update(of=("self",))
                .get(event_id=event_id)
            )
        except RaceEventProjectionControl.DoesNotExist:
            return RaceResultRevisionApplyDecision(
                False, "reject", "control_missing"
            )
        if (
            control.write_owner != RaceEventProjectionWriteOwner.LIVE
            or control.owner_generation != expected_owner_generation
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "owner_mismatch"
            )

        try:
            tracking = RaceEventLiveTracking.objects.select_for_update().get(
                event_id=event_id
            )
        except RaceEventLiveTracking.DoesNotExist:
            return RaceResultRevisionApplyDecision(
                False, "reject", "tracking_missing"
            )
        if operator_transition:
            if (
                tracking.active_attempt_token != ""
                or tracking.claim_expires_at is not None
            ):
                return RaceResultRevisionApplyDecision(
                    False, "reject", "active_claim_present"
                )
        else:
            if (
                tracking.claim_generation != expected_claim_generation
                or tracking.active_attempt_token != attempt_token
            ):
                return RaceResultRevisionApplyDecision(
                    False, "reject", "claim_mismatch"
                )
            if tracking.claim_expires_at is None:
                return RaceResultRevisionApplyDecision(
                    False, "reject", "claim_missing_expiry"
                )
            if tracking.claim_expires_at <= now:
                return RaceResultRevisionApplyDecision(
                    False, "reject", "claim_expired"
                )
        if tracking.state != RaceEventLiveState.PROVISIONAL_RESULT:
            return RaceResultRevisionApplyDecision(
                False, "reject", "tracking_state_mismatch"
            )

        try:
            event = RaceEvent.objects.select_for_update().get(pk=event_id)
            source_identity = (
                RaceResultSourceIdentity.objects.select_for_update().get(
                    pk=observation_hint["source_identity_id"]
                )
            )
            observation = RaceResultObservation.objects.select_for_update().get(
                pk=observation_id
            )
        except RaceEvent.DoesNotExist:
            return RaceResultRevisionApplyDecision(
                False, "reject", "event_missing"
            )
        except RaceResultObservation.DoesNotExist:
            return RaceResultRevisionApplyDecision(
                False, "reject", "observation_missing"
            )
        except RaceResultSourceIdentity.DoesNotExist:
            return RaceResultRevisionApplyDecision(
                False, "reject", "source_missing"
            )
        observation.source_identity = source_identity
        if (
            observation.source_identity.event_id != event.pk
            or source_identity.event_id != event.pk
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "observation_event_mismatch"
            )
        if (
            source_identity.source_key == "the_racing_api"
            and source_identity.result_authority
            != RaceResultSourceAuthority.SUPPLEMENTAL
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "tra_authority_mismatch"
            )
        if observation.result_phase != RaceResultPhase.PROVISIONAL:
            return RaceResultRevisionApplyDecision(
                False, "reject", "provisional_observation_required"
            )
        try:
            observation_digest = build_race_live_canonical_sha256(
                normalized_payload=observation.normalized_payload
            )
        except (TypeError, ValueError, OverflowError, RecursionError):
            return RaceResultRevisionApplyDecision(
                False, "reject", "invalid_payload"
            )
        if observation_digest != observation.normalized_sha256:
            return RaceResultRevisionApplyDecision(
                False, "reject", "observation_digest_mismatch"
            )

        result_revision_id = control.current_result_revision_id
        racecard_revision_id = control.current_racecard_revision_id
        if result_revision_id is None:
            return RaceResultRevisionApplyDecision(
                False, "reject", "result_revision_missing"
            )
        if racecard_revision_id is None:
            return RaceResultRevisionApplyDecision(
                False, "reject", "racecard_revision_missing"
            )
        try:
            racecard_revision = RaceEventRevision.objects.select_for_update().get(
                pk=racecard_revision_id
            )
            result_revision = RaceEventRevision.objects.select_for_update().get(
                pk=result_revision_id
            )
        except RaceEventRevision.DoesNotExist:
            return RaceResultRevisionApplyDecision(
                False, "reject", "revision_missing"
            )
        if (
            result_revision.event_id != event.pk
            or result_revision.kind != RaceEventRevisionKind.RESULT
            or result_revision.phase != RaceResultPhase.PROVISIONAL
            or result_revision.content_sha256 != observation.normalized_sha256
            or result_revision.primary_observation_id != observation.pk
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "shadow_revision_mismatch"
            )
        already_published = result_revision.published_at is not None
        publication_exists = RaceEventRevisionPublication.objects.filter(
            revision=result_revision
        ).exists()
        if already_published and not publication_exists:
            return RaceResultRevisionApplyDecision(
                False,
                "reject",
                "publication_audit_missing",
                result_revision,
            )
        if not already_published and publication_exists:
            return RaceResultRevisionApplyDecision(
                False,
                "reject",
                "publication_audit_inconsistent",
                result_revision,
            )
        if (
            racecard_revision.event_id != event.pk
            or racecard_revision.kind != RaceEventRevisionKind.RACECARD
            or racecard_revision.phase != RaceResultPhase.RACECARD
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "racecard_revision_inconsistent"
            )

        locked_revision_items = list(
            RaceEventRevisionItem.objects.select_for_update()
            .select_related("participant")
            .filter(
                revision_id__in=(
                    racecard_revision_id,
                    result_revision_id,
                )
            )
            .order_by("revision_id", "internal_order", "pk")
        )
        racecard_items = [
            item
            for item in locked_revision_items
            if item.revision_id == racecard_revision_id
        ]
        result_items = [
            item
            for item in locked_revision_items
            if item.revision_id == result_revision_id
        ]
        racecard_participant_ids = {
            item.participant_id for item in racecard_items
        }
        if not racecard_participant_ids:
            return RaceResultRevisionApplyDecision(
                False, "reject", "participant_set_mismatch"
            )
        participants = list(
            RaceEventParticipant.objects.select_for_update()
            .filter(
                pk__in=racecard_participant_ids,
                event_id=event.pk,
            )
            .order_by("pk")
        )
        if {participant.pk for participant in participants} != racecard_participant_ids:
            return RaceResultRevisionApplyDecision(
                False, "reject", "participant_set_mismatch"
            )
        if any(
            participant.review_status != RaceLiveReviewStatus.APPROVED
            for participant in participants
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "participant_not_approved"
            )

        lock_flags = event.manual_lock_flags
        if (
            not isinstance(lock_flags, dict)
            or bool(lock_flags.get("results"))
            or bool(lock_flags.get("runners"))
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "manual_lock_conflict"
            )

        payload = observation.normalized_payload
        payload_items = payload.get("participants") if isinstance(payload, dict) else None
        if not isinstance(payload_items, list) or not payload_items:
            return RaceResultRevisionApplyDecision(
                False, "reject", "participant_set_mismatch"
            )
        external_runner_ids: list[str] = []
        for item in payload_items:
            external_runner_id = (
                item.get("external_runner_id") if isinstance(item, dict) else None
            )
            if (
                not isinstance(external_runner_id, str)
                or not external_runner_id
                or external_runner_id in external_runner_ids
            ):
                return RaceResultRevisionApplyDecision(
                    False, "reject", "participant_set_mismatch"
                )
            external_runner_ids.append(external_runner_id)

        source_rows = list(
            RaceEventParticipantSourceIdentity.objects.select_for_update()
            .select_related("participant")
            .filter(
                source_identity=source_identity,
                external_runner_id__in=external_runner_ids,
                participant__event_id=event.pk,
            )
            .order_by("participant_id", "pk")
        )
        identities = {
            row.external_runner_id: row.participant for row in source_rows
        }
        observation_participant_ids = {
            participant.pk for participant in identities.values()
        }
        if (
            len(identities) != len(external_runner_ids)
            or observation_participant_ids != racecard_participant_ids
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "participant_set_mismatch"
            )

        result_items.sort(key=lambda item: (item.internal_order, item.pk))
        if (
            {item.participant_id for item in result_items}
            != racecard_participant_ids
            or len(result_items) != len(racecard_participant_ids)
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "participant_set_mismatch"
            )
        external_id_by_participant = {
            row.participant_id: row.external_runner_id for row in source_rows
        }
        normalized_items = [
            {
                "external_runner_id": external_id_by_participant[item.participant_id],
                "status": item.status,
                "official_finish_position": item.official_finish_position,
                "raw_status": item.raw_status,
                "finish_time": item.finish_time,
                "margin": item.margin,
                "number": item.horse_number,
                "barrier": item.barrier,
                "jockey_name": item.jockey_name,
                "trainer_name": item.trainer_name,
                "carried_weight": item.carried_weight,
                "field_provenance": item.field_provenance,
            }
            for item in result_items
        ]

        applicable_policy_filter = (
            Q(scope_type="global", scope_key="global")
            | Q(scope_type="region", scope_key=event.country_region)
            | Q(scope_type="source", scope_key=source_identity.source_key)
            | Q(scope_type="event", scope_key=str(event.pk))
        )
        locked_policies = list(
            RaceLivePublicationPolicy.objects.select_for_update()
            .filter(applicable_policy_filter)
            .order_by("scope_type", "scope_key")
        )
        locked_allowlist = (
            RaceLiveEventPublicationAllowlist.objects.select_for_update()
            .filter(
                event=event,
                source_key=source_identity.source_key,
            )
            .first()
        )
        policy_decision = resolve_race_live_publication_policy(
            event_id=event.pk,
            source_identity_id=source_identity.pk,
            now=now,
        )
        if (
            policy_decision.allowed is not True
            or policy_decision.effective_mode
            not in {
                RaceLivePublicationMode.PROVISIONAL_PUBLIC,
                RaceLivePublicationMode.OFFICIAL_PUBLIC,
            }
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", policy_decision.reason, result_revision
            )
        locked_policy_by_scope = {
            (policy.scope_type, policy.scope_key): policy
            for policy in locked_policies
        }
        if len(locked_policy_by_scope) != len(policy_decision.policy_versions):
            return RaceResultRevisionApplyDecision(
                False, "reject", "publication_policy_changed", result_revision
            )
        for scope_type, scope_key, version in policy_decision.policy_versions:
            policy = locked_policy_by_scope.get((scope_type, scope_key))
            if policy is None or policy.version != version:
                return RaceResultRevisionApplyDecision(
                    False, "reject", "publication_policy_changed", result_revision
                )
        if (
            locked_allowlist is None
            or locked_allowlist.version != policy_decision.allowlist_version
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "publication_policy_changed", result_revision
            )
        if (
            locked_allowlist.coverage_proof_digest
            != policy_decision.coverage_proof_digest
        ):
            return RaceResultRevisionApplyDecision(
                False, "reject", "publication_policy_changed", result_revision
            )

        if (
            not isinstance(event.race_datetime, datetime)
            or timezone.is_naive(event.race_datetime)
        ):
            return RaceResultRevisionApplyDecision(
                False,
                "reject",
                "official_deadline_unavailable",
                result_revision,
            )
        official_deadline = event.race_datetime + timedelta(hours=2)
        incident_lookup = {
            "event": event,
            "provisional_revision": result_revision,
            "official_route_version": (
                locked_allowlist.official_verification_route_version
            ),
        }
        incident_defaults = {
            "official_route": locked_allowlist.official_verification_route,
            "official_route_contract_digest": (
                locked_allowlist.official_verification_contract_digest
            ),
            "official_terms_evidence_digest": (
                locked_allowlist.official_terms_evidence_digest
            ),
            "deadline_at": official_deadline,
            "manual_verification_due_at": now + timedelta(minutes=15),
            "status": RaceLiveOfficialVerificationIncidentStatus.OPEN,
            "next_probe_at": official_deadline,
            "opened_at": now,
        }
        try:
            incident, created = (
                RaceLiveOfficialVerificationIncident.objects.get_or_create(
                    **incident_lookup,
                    defaults=incident_defaults,
                )
            )
        except IntegrityError:
            return RaceResultRevisionApplyDecision(
                False,
                "reject",
                "official_incident_conflict",
                result_revision,
            )
        if not created:
            incident = (
                RaceLiveOfficialVerificationIncident.objects.select_for_update()
                .get(pk=incident.pk)
            )
        if (
            incident.event_id != event.pk
            or incident.provisional_revision_id != result_revision.pk
            or incident.official_route != incident_defaults["official_route"]
            or incident.official_route_version
            != incident_lookup["official_route_version"]
            or incident.official_route_contract_digest
            != incident_defaults["official_route_contract_digest"]
            or incident.official_terms_evidence_digest
            != incident_defaults["official_terms_evidence_digest"]
            or incident.deadline_at != official_deadline
            or not isinstance(incident.opened_at, datetime)
            or timezone.is_naive(incident.opened_at)
            or incident.opened_at > now
            or incident.manual_verification_due_at
            != incident.opened_at + timedelta(minutes=15)
        ):
            return RaceResultRevisionApplyDecision(
                False,
                "reject",
                "official_incident_inconsistent",
                result_revision,
            )

        if already_published:
            return RaceResultRevisionApplyDecision(
                False,
                "replay",
                "shadow_revision_already_published",
                result_revision,
            )

        _publish_race_result_revision(
            event_id=event.pk,
            revision=result_revision,
            observation=observation,
            normalized_items=normalized_items,
            identities=identities,
            tracking=tracking,
            published_at=now,
            publication_reason="shadow_promotion",
            policy_versions=[
                [scope_type, scope_key, version]
                for scope_type, scope_key, version in policy_decision.policy_versions
            ],
            allowlist_version=policy_decision.allowlist_version,
            registry_digest=policy_decision.registry_digest,
            coverage_proof_digest=policy_decision.coverage_proof_digest,
        )
        return RaceResultRevisionApplyDecision(
            True,
            "promote",
            "shadow_revision_promoted",
            result_revision,
        )


def admit_race_live_publication(
    *,
    observation_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    now: datetime,
) -> RaceResultRevisionApplyDecision:
    """Poll/runner entrypoint; requires the existing live provider claim."""
    return _admit_race_live_publication_locked(
        observation_id=observation_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
        operator_transition=False,
    )


def admit_persisted_race_live_publication(
    *,
    observation_id: int,
    expected_owner_generation: int,
    now: datetime,
) -> RaceResultRevisionApplyDecision:
    """Operator entrypoint; requires an empty claim and never creates one."""
    return _admit_race_live_publication_locked(
        observation_id=observation_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=None,
        attempt_token=None,
        now=now,
        operator_transition=True,
    )


def _task_log(task_name: str, status: str, payload: dict | None = None, detail: str = "") -> TaskExecutionLog:
    now = timezone.now()
    return TaskExecutionLog.objects.create(
        task_name=task_name,
        status=status,
        payload=payload or {},
        detail=detail,
        started_at=now,
        finished_at=now,
    )


def _locked(event: RaceEvent, key: str) -> bool:
    flags = event.manual_lock_flags or {}
    return bool(flags.get(key))


def _diff_values(current: Any, candidate: Any) -> dict:
    if current == candidate:
        return {"changed": False, "current": current, "candidate": candidate}
    return {"changed": True, "current": current, "candidate": candidate}


def build_candidate_diff(event: RaceEvent, module: str, payload: dict) -> dict:
    if module == RaceEventModule.BASIC:
        return {
            field: _diff_values(getattr(event, field, None), payload.get(field))
            for field in BASIC_EVENT_FIELDS
            if field in payload
        }
    current_counts = {
        RaceEventModule.HISTORY_WINNERS: event.history_winners.count(),
        RaceEventModule.RUNNERS: event.runners.count(),
        RaceEventModule.RESULTS: event.results.count(),
        RaceEventModule.NEWS_LINKS: event.article_links.count(),
    }
    candidate_count = len(payload) if isinstance(payload, list) else len(payload.get("items", []))
    return {
        "count": {
            "changed": current_counts.get(module, 0) != candidate_count,
            "current": current_counts.get(module, 0),
            "candidate": candidate_count,
        }
    }


def save_data_candidate(
    *,
    event: RaceEvent,
    module: str,
    source_name: str,
    candidate_payload: dict,
    source_url: str = "",
    raw_payload: dict | None = None,
    confidence: int = 0,
) -> RaceEventDataCandidate:
    candidate = RaceEventDataCandidate.objects.create(
        event=event,
        module=module,
        source_name=source_name,
        source_url=source_url,
        confidence=max(0, min(int(confidence or 0), 100)),
        candidate_payload=candidate_payload,
        diff_payload=build_candidate_diff(event, module, candidate_payload),
        raw_payload=raw_payload or {},
    )
    _task_log(
        "race_event_candidate_saved",
        TaskStatus.SUCCESS,
        payload={"event_id": event.pk, "candidate_id": candidate.pk, "module": module, "source_name": source_name},
        detail=f"赛事候选资料已保存：{event} {module} {source_name}",
    )
    return candidate


def _set_unlocked_event_fields(event: RaceEvent, payload: dict) -> list[str]:
    updated_fields: list[str] = []
    for field in BASIC_EVENT_FIELDS:
        if field not in payload or _locked(event, field) or _locked(event, RaceEventModule.BASIC):
            continue
        value = payload[field]
        if getattr(event, field, None) != value:
            setattr(event, field, value)
            updated_fields.append(field)
    return updated_fields


def _clean_race_horse_name(value: Any) -> str:
    return HORSE_COUNTRY_SUFFIX_RE.sub("", str(value or "").strip()).strip()


def _replace_runners(event: RaceEvent, items: Iterable[dict]) -> int:
    if _locked(event, RaceEventModule.RUNNERS):
        return 0
    event.runners.all().delete()
    created = []
    for index, item in enumerate(items, start=1):
        raw_payload = sanitize_structured_row_evidence(item)
        created.append(
            RaceEventRunner(
                event=event,
                sort_order=int(item.get("sort_order") or index),
                horse_number=str(item.get("horse_number") or ""),
                barrier=str(item.get("barrier") or ""),
                horse_name=_clean_race_horse_name(item.get("horse_name")),
                jockey_name=str(item.get("jockey_name") or ""),
                trainer_name=str(item.get("trainer_name") or ""),
                carried_weight=str(item.get("carried_weight") or ""),
                odds_value=str(item.get("odds_value") or ""),
                popularity=str(item.get("popularity") or ""),
                running_status=str(item.get("running_status") or RaceRunnerStatus.DECLARED),
                source_refs=item.get("source_refs") or {},
                raw_payload=raw_payload,
            )
        )
    persisted = [item for item in created if item.horse_name]
    RaceEventRunner.objects.bulk_create(persisted)
    return len(persisted)


def _replace_results(event: RaceEvent, items: Iterable[dict]) -> int:
    if _locked(event, RaceEventModule.RESULTS):
        return 0
    event.results.all().delete()
    created = []
    for item in items:
        if not item.get("finish_position") or not item.get("horse_name"):
            continue
        raw_payload = sanitize_structured_row_evidence(item)
        created.append(
            RaceEventResult(
                event=event,
                finish_position=int(item["finish_position"]),
                official_finish_position=int(item.get("official_finish_position") or item["finish_position"]),
                horse_number=str(item.get("horse_number") or ""),
                horse_name=_clean_race_horse_name(item.get("horse_name")),
                jockey_name=str(item.get("jockey_name") or ""),
                trainer_name=str(item.get("trainer_name") or ""),
                finish_time=str(item.get("finish_time") or ""),
                margin=str(item.get("margin") or ""),
                odds_value=str(item.get("odds_value") or ""),
                popularity=str(item.get("popularity") or ""),
                barrier=str(item.get("barrier") or ""),
                carried_weight=str(item.get("carried_weight") or ""),
                running_status=str(item.get("running_status") or ""),
                is_confirmed=bool(item.get("is_confirmed", True)),
                source_refs=item.get("source_refs") or {},
                raw_payload=raw_payload,
            )
        )
    RaceEventResult.objects.bulk_create(created)
    return len(created)


def _replace_history_winners(event: RaceEvent, items: Iterable[dict]) -> int:
    if _locked(event, RaceEventModule.HISTORY_WINNERS):
        return 0
    event.history_winners.all().delete()
    created = []
    for item in items:
        if not item.get("winner_year") or not item.get("horse_name"):
            continue
        created.append(
            RaceEventHistoryWinner(
                event=event,
                winner_year=int(item["winner_year"]),
                horse_name=_clean_race_horse_name(item.get("horse_name")),
                jockey_name=str(item.get("jockey_name") or ""),
                trainer_name=str(item.get("trainer_name") or ""),
                finish_time=str(item.get("finish_time") or ""),
                margin=str(item.get("margin") or ""),
                source_refs=item.get("source_refs") or {},
            )
        )
    RaceEventHistoryWinner.objects.bulk_create(created)
    return len(created)


def _safe_link_type(value: str) -> str:
    value = (value or "").strip()
    if value in ArticleRaceLinkType.values:
        return value
    return ArticleRaceLinkType.RELATED


def _safe_confidence(value: Any, default: int = 100) -> int:
    try:
        return max(0, min(int(value), 100))
    except (TypeError, ValueError):
        return default


def _apply_news_links(event: RaceEvent, items: Iterable[dict], *, user: User | None, source_name: str) -> dict:
    applied = 0
    skipped_missing_article = 0
    skipped_removed = 0
    now = timezone.now()
    for item in items:
        article_id = item.get("article_id") or item.get("id")
        if not article_id:
            skipped_missing_article += 1
            continue
        article = (
            NewsArticle.objects.filter(
                pk=article_id,
                workflow_status=WorkflowStatus.PUBLISHED,
                published_to_web_at__isnull=False,
            )
            .order_by("pk")
            .first()
        )
        if article is None:
            skipped_missing_article += 1
            continue
        existing = ArticleRaceLink.objects.filter(event=event, article=article).first()
        if existing and existing.status == ArticleRaceLinkStatus.REMOVED:
            skipped_removed += 1
            continue
        ArticleRaceLink.objects.update_or_create(
            event=event,
            article=article,
            defaults={
                "link_type": _safe_link_type(str(item.get("link_type") or "")),
                "status": ArticleRaceLinkStatus.MANUAL,
                "source": f"candidate:{source_name}"[:64],
                "confidence": _safe_confidence(item.get("confidence"), default=100),
                "matched_text": str(item.get("matched_text") or "")[:255],
                "match_reason": str(item.get("match_reason") or "后台应用相关新闻候选"),
                "metadata": item.get("metadata") or {},
                "confirmed_by": user,
                "confirmed_at": now,
            },
        )
        applied += 1
    return {
        "created_count": applied,
        "skipped_missing_article": skipped_missing_article,
        "skipped_removed": skipped_removed,
    }


def _candidate_items(payload: dict | list) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return [item for item in payload.get("items", []) if isinstance(item, dict)]


def apply_race_event_normalization(event: RaceEvent) -> None:
    """Apply field normalization to a RaceEvent and persist normalized fields.

    This is a non-blocking operation: normalization failures are recorded in
    ``normalization_issues`` without aborting the write path.  The normalizer
    reads ``surface``, ``distance_text`` and ``eligibility_text`` from the
    event and writes the computed normalized fields back to the database.
    """
    issues: list[dict[str, str]] = []
    now = timezone.now()
    input_parts: dict[str, str] = {}

    # --- Surface / race-type / layout / going ---
    try:
        surface_result = normalize_surface_race_type_layout_going(
            raw_value=event.surface,
            going_text=None,
        )
        event.normalized_surface = surface_result.surface.value
        event.normalized_race_type = surface_result.race_type.value
        event.course_layout_text = surface_result.course_layout
        event.going_text = surface_result.going_text
        input_parts["surface"] = event.surface
    except Exception as exc:
        issues.append({"field": "surface", "error": str(exc)})

    # --- Distance ---
    try:
        distance_result = normalize_distance(
            raw_value=event.distance_text,
            official_metric_meters=None,
        )
        if distance_result.meters is not None:
            event.distance_meters_normalized = float(distance_result.meters) if distance_result.meters is not None else None
        event.distance_precision = distance_result.precision.value
        input_parts["distance_text"] = event.distance_text
    except Exception as exc:
        issues.append({"field": "distance", "error": str(exc)})

    # --- Eligibility (age / sex restriction) ---
    try:
        eligibility_result = normalize_eligibility(
            raw_value=event.eligibility_text,
        )
        event.minimum_age = eligibility_result.min_age
        event.maximum_age = eligibility_result.max_age
        event.age_open_ended = eligibility_result.age_open_ended
        event.sex_restriction = eligibility_result.sex.value
        event.eligibility_constraints = eligibility_result.extra_constraints
        input_parts["eligibility_text"] = event.eligibility_text
    except Exception as exc:
        issues.append({"field": "eligibility", "error": str(exc)})

    # --- Normalization metadata ---
    event.normalization_version = RACE_FIELD_NORMALIZATION_VERSION
    event.normalization_input_sha256 = compute_input_sha256(**input_parts)
    event.normalization_issues = issues
    event.normalized_at = now

    # Persist only normalization-related fields
    event.save(
        update_fields=[
            "normalized_surface",
            "normalized_race_type",
            "course_layout_text",
            "going_text",
            "distance_meters_normalized",
            "distance_precision",
            "minimum_age",
            "maximum_age",
            "age_open_ended",
            "sex_restriction",
            "eligibility_constraints",
            "normalization_version",
            "normalization_input_sha256",
            "normalization_issues",
            "normalized_at",
            "updated_at",
        ]
    )


def apply_data_candidate(candidate: RaceEventDataCandidate, *, user: User | None = None) -> dict:
    event = candidate.event
    payload = candidate.candidate_payload or {}
    module = candidate.module
    summary: dict[str, Any] = {"module": module, "updated_fields": [], "created_count": 0}
    with transaction.atomic():
        if module == RaceEventModule.BASIC:
            updated_fields = _set_unlocked_event_fields(event, payload)
            if updated_fields:
                event.save(update_fields=[*updated_fields, "updated_at"])
            apply_race_event_normalization(event)
            summary["updated_fields"] = updated_fields
        elif module == RaceEventModule.RUNNERS:
            summary["created_count"] = _replace_runners(event, _candidate_items(payload))
        elif module == RaceEventModule.RESULTS:
            summary["created_count"] = _replace_results(event, _candidate_items(payload))
        elif module == RaceEventModule.HISTORY_WINNERS:
            summary["created_count"] = _replace_history_winners(event, _candidate_items(payload))
        elif module == RaceEventModule.NEWS_LINKS:
            summary.update(_apply_news_links(event, _candidate_items(payload), user=user, source_name=candidate.source_name))
        else:
            summary["skipped"] = "module_requires_manual_view_support"
        candidate.status = RaceEventCandidateStatus.APPLIED
        candidate.applied_by = user
        candidate.applied_at = timezone.now()
        candidate.save(update_fields=["status", "applied_by", "applied_at", "updated_at"])
    log_operation(
        action_type="race_candidate_applied",
        target_type="race_event",
        target_id=event.pk,
        detail=f"应用赛事候选资料 candidate={candidate.pk} module={module} summary={summary}",
        admin=user,
    )
    _task_log(
        "race_event_candidate_applied",
        TaskStatus.SUCCESS,
        payload={"event_id": event.pk, "candidate_id": candidate.pk, "summary": summary},
        detail=f"赛事候选资料已应用：{event} {module}",
    )
    return summary


def update_runner_dynamic_fields(event: RaceEvent, updates: Iterable[dict], *, source_name: str = "") -> dict:
    updated = 0
    skipped = 0
    skipped_ambiguous = 0
    now = timezone.now()
    for item in updates:
        external_runner_id = str(item.get("external_runner_id") or "").strip()
        horse_number = str(item.get("horse_number") or "")
        horse_name = _clean_race_horse_name(item.get("horse_name"))
        queryset = event.runners.all()
        runner = None
        ambiguous = False
        if external_runner_id:
            matches = list(
                queryset.filter(
                    external_runner_id=external_runner_id
                )[:2]
            )
            if not matches:
                matches = list(
                    queryset.filter(
                        external_runner_id="",
                        source_refs__external_runner_id=external_runner_id,
                    )[:2]
                )
            if len(matches) == 1:
                runner = matches[0]
            else:
                ambiguous = len(matches) > 1
        elif horse_number:
            number_matches = list(
                queryset.filter(horse_number=horse_number)
            )
            if len(number_matches) == 1:
                runner = number_matches[0]
            elif len(number_matches) > 1:
                if horse_name:
                    name_matches = [
                        candidate
                        for candidate in number_matches
                        if _clean_race_horse_name(candidate.horse_name)
                        == horse_name
                    ]
                    if len(name_matches) == 1:
                        runner = name_matches[0]
                    else:
                        ambiguous = True
                else:
                    ambiguous = True
            elif horse_name:
                name_matches = [
                    candidate
                    for candidate in queryset
                    if _clean_race_horse_name(candidate.horse_name)
                    == horse_name
                ][:2]
                if len(name_matches) == 1:
                    runner = name_matches[0]
                else:
                    ambiguous = len(name_matches) > 1
        elif horse_name:
            name_matches = [
                candidate
                for candidate in queryset
                if _clean_race_horse_name(candidate.horse_name) == horse_name
            ][:2]
            if len(name_matches) == 1:
                runner = name_matches[0]
            else:
                ambiguous = len(name_matches) > 1
        if runner is None:
            skipped += 1
            if ambiguous:
                skipped_ambiguous += 1
            continue
        changed_fields = []
        for field in DYNAMIC_RUNNER_FIELDS:
            if field in item and getattr(runner, field) != str(item[field]):
                setattr(runner, field, str(item[field]))
                changed_fields.append(field)
        if changed_fields:
            runner.dynamic_updated_at = now
            runner.save(update_fields=[*changed_fields, "dynamic_updated_at", "updated_at"])
            updated += 1
    _task_log(
        "race_event_dynamic_fields_refreshed",
        TaskStatus.SUCCESS,
        payload={
            "event_id": event.pk,
            "source_name": source_name,
            "updated": updated,
            "skipped": skipped,
            "skipped_ambiguous": skipped_ambiguous,
        },
        detail=(
            f"赛事动态字段刷新完成：{event} updated={updated} "
            f"skipped={skipped} ambiguous={skipped_ambiguous}"
        ),
    )
    return {
        "updated": updated,
        "skipped": skipped,
        "skipped_ambiguous": skipped_ambiguous,
    }


def record_dynamic_refresh_failure(event: RaceEvent, *, source_name: str, error: str) -> None:
    _task_log(
        "race_event_dynamic_fields_refreshed",
        TaskStatus.FAILED,
        payload={"event_id": event.pk, "source_name": source_name},
        detail=error,
    )


def _event_match_terms(event: RaceEvent) -> list[str]:
    values = [event.chinese_name, event.original_name]
    values.extend(event.aliases.filter(is_active=True).values_list("text", flat=True))
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = (value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return sorted(result, key=len, reverse=True)


def _article_text(article: NewsArticle, *fields: str) -> str:
    return "\n".join(str(getattr(article, field, "") or "") for field in fields)


def _classify_article_link(article: NewsArticle, event: RaceEvent) -> str:
    if article.content_category in {ContentCategory.PRE_RACE, ContentCategory.PREVIEW, ContentCategory.TIPS}:
        return ArticleRaceLinkType.PRE_RACE
    if article.content_category in {ContentCategory.POST_RACE, ContentCategory.RESULT_BRIEF}:
        return ArticleRaceLinkType.POST_RACE
    if event.local_date and article.published_at:
        article_date = timezone.localdate(article.published_at)
        if article_date < event.local_date:
            return ArticleRaceLinkType.PRE_RACE
        if article_date > event.local_date:
            return ArticleRaceLinkType.POST_RACE
    return ArticleRaceLinkType.RELATED


def _match_article(article: NewsArticle, event: RaceEvent, terms: list[str], *, date_window_days: int) -> RaceArticleMatch | None:
    title_summary = _article_text(article, "title_ja", "title_zh", "translated_title_zh", "summary_zh", "translated_summary_zh")
    body = _article_text(article, "body_ja_normalized", "body_ja_raw", "body_zh", "translated_body_zh")
    for term in terms:
        if source_term_matches_text(title_summary, term, article.source_language):
            return RaceArticleMatch(
                article=article,
                status=ArticleRaceLinkStatus.AUTO,
                link_type=_classify_article_link(article, event),
                confidence=95,
                matched_text=term,
                reason="标题或摘要命中赛事正式名/别名",
            )
    for term in terms:
        if source_term_matches_text(body, term, article.source_language):
            return RaceArticleMatch(
                article=article,
                status=ArticleRaceLinkStatus.CANDIDATE,
                link_type=_classify_article_link(article, event),
                confidence=70,
                matched_text=term,
                reason="正文命中赛事正式名/别名",
            )
    if event.local_date and article.published_at:
        article_date = timezone.localdate(article.published_at)
        if abs((article_date - event.local_date).days) <= date_window_days:
            tags = " ".join(str(item) for item in (article.tags_json or []))
            decision_reason = article.decision_reason or {}
            signals = " ".join([tags, str(decision_reason)])
            for term in terms:
                if source_term_matches_text(signals, term, article.source_language):
                    return RaceArticleMatch(
                        article=article,
                        status=ArticleRaceLinkStatus.CANDIDATE,
                        link_type=_classify_article_link(article, event),
                        confidence=65,
                        matched_text=term,
                        reason="日期窗口内命中标签/自动化决策信号",
                    )
    return None


def associate_articles_for_event(
    event: RaceEvent,
    *,
    articles: Iterable[NewsArticle] | None = None,
    date_window_days: int = 14,
) -> dict:
    terms = _event_match_terms(event)
    if not terms:
        return {"created": 0, "updated": 0, "skipped_removed": 0, "skipped_manual": 0}
    if articles is None:
        queryset = NewsArticle.objects.filter(
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at__isnull=False,
        )
        if event.local_date:
            start = event.local_date - timedelta(days=date_window_days)
            end = event.local_date + timedelta(days=date_window_days)
            queryset = queryset.filter(published_at__date__gte=start, published_at__date__lte=end)
        articles = queryset.order_by("-published_at", "-id")[:500]
    created = 0
    updated = 0
    skipped_removed = 0
    skipped_manual = 0
    for article in articles:
        match = _match_article(article, event, terms, date_window_days=date_window_days)
        if match is None:
            continue
        existing = ArticleRaceLink.objects.filter(event=event, article=article).first()
        if existing and existing.status == ArticleRaceLinkStatus.REMOVED:
            skipped_removed += 1
            continue
        if existing and existing.status == ArticleRaceLinkStatus.MANUAL:
            skipped_manual += 1
            continue
        defaults = {
            "link_type": match.link_type,
            "status": match.status,
            "source": "auto_match",
            "confidence": match.confidence,
            "matched_text": match.matched_text,
            "match_reason": match.reason,
            "metadata": {"date_window_days": date_window_days},
        }
        link, was_created = ArticleRaceLink.objects.update_or_create(event=event, article=article, defaults=defaults)
        created += int(was_created)
        updated += int(not was_created and link.status != ArticleRaceLinkStatus.REMOVED)
    _task_log(
        "race_event_article_association",
        TaskStatus.SUCCESS,
        payload={
            "event_id": event.pk,
            "created": created,
            "updated": updated,
            "skipped_removed": skipped_removed,
            "skipped_manual": skipped_manual,
        },
        detail=f"赛事新闻关联完成：{event}",
    )
    return {
        "created": created,
        "updated": updated,
        "skipped_removed": skipped_removed,
        "skipped_manual": skipped_manual,
    }


def confirm_article_link(link: ArticleRaceLink, *, user: User | None = None) -> ArticleRaceLink:
    link.status = ArticleRaceLinkStatus.MANUAL
    link.confirmed_by = user
    link.confirmed_at = timezone.now()
    link.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
    log_operation(
        action_type="race_article_link_confirmed",
        target_type="article_race_link",
        target_id=link.pk,
        detail=f"确认赛事新闻关联 event={link.event_id} article={link.article_id}",
        admin=user,
    )
    return link


def remove_article_link(link: ArticleRaceLink, *, user: User | None = None) -> ArticleRaceLink:
    link.status = ArticleRaceLinkStatus.REMOVED
    link.removed_by = user
    link.removed_at = timezone.now()
    link.save(update_fields=["status", "removed_by", "removed_at", "updated_at"])
    log_operation(
        action_type="race_article_link_removed",
        target_type="article_race_link",
        target_id=link.pk,
        detail=f"移除赛事新闻关联 event={link.event_id} article={link.article_id}",
        admin=user,
    )
    return link

"""
Race event lifecycle service — pure decision, atomic apply, claim, enrollment.

Phase A: time-based transitions only. No providers, no news gate changes, no
race-live dispatch.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone as django_timezone

from stable.models import (
    RaceEvent,
    RaceEventStatus,
    RaceEventLifecycleControl,
    RaceEventLifecycleMode,
    RaceEventLifecycleTransition,
    RaceEventLifecycleTransitionKind,
)
from stable.services.race_event_public_cache import invalidate_public_race_cache


# ── region → valid timezone contract ──────────────────────────────────

_REGION_TIMEZONE_CONTRACT: dict[str, frozenset[str]] = {
    "japan": frozenset({"Asia/Tokyo"}),
    "hong_kong": frozenset({"Asia/Hong_Kong"}),
    "united_kingdom": frozenset({"Europe/London"}),
    "france": frozenset({"Europe/Paris"}),
}


def _validate_timezone(
    timezone_name: str,
    region: str,
    allowed_us_zones: frozenset[str] | None = None,
) -> str | None:
    """Return an error message if the timezone is invalid for the region, else None."""
    if not timezone_name:
        return "missing timezone_name"
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, KeyError, TypeError):
        return f"invalid IANA timezone: {timezone_name!r}"

    allowed = _REGION_TIMEZONE_CONTRACT.get(region)
    if allowed is not None:
        if timezone_name not in allowed:
            return (
                f"timezone {timezone_name!r} not in region contract "
                f"for {region}: {sorted(allowed)}"
            )
        return None

    if region == "united_states":
        if not timezone_name.startswith("America/"):
            return f"US region requires America/* timezone, got {timezone_name!r}"
        if allowed_us_zones is not None and timezone_name not in allowed_us_zones:
            return (
                f"US timezone {timezone_name!r} not in manifest-approved set: "
                f"{sorted(allowed_us_zones)}"
            )
        return None

    # Phase A supports exactly five regions; everything else fails closed.
    if region not in _REGION_TIMEZONE_CONTRACT and region != "united_states":
        return (
            f"region {region!r} is not supported for lifecycle enrollment. "
            f"Supported: japan, hong_kong, united_kingdom, france, united_states"
        )
    return None


def _local_next_midnight(
    local_date: date,
    timezone_name: str,
) -> datetime:
    tz = ZoneInfo(timezone_name)
    next_day = local_date + timedelta(days=1)
    local_midnight = datetime.combine(next_day, datetime.min.time())
    return local_midnight.replace(tzinfo=tz)


# ── dataclasses ───────────────────────────────────────────────────────

@dataclass
class LifecycleDecision:
    action: str  # "noop" | "transition" | "error"
    to_status: str = ""
    reason_code: str = ""
    effective_at: datetime | None = None
    error_message: str = ""


@dataclass
class ApplyResult:
    action: str = "noop"
    error: str | None = None
    reason_code: str = ""
    transition_id: int | None = None


@dataclass
class LifecycleBatchClaim:
    event_id: int
    schedule_generation: int
    claim_generation: int
    attempt_token: str


# ── pure decision function ────────────────────────────────────────────

def decide_race_lifecycle(
    *,
    race_datetime: datetime | None,
    timezone_name: str,
    status: str,
    now: datetime,
    local_date: date | None = None,
    region: str = "",
    allowed_us_zones: frozenset[str] | None = None,
) -> LifecycleDecision:
    """Pure decision: given current state and *now*, return the next action.

    No database access, no network.
    """
    tz_error = _validate_timezone(timezone_name, region, allowed_us_zones)
    if tz_error is not None:
        return LifecycleDecision(action="error", error_message=tz_error)

    if status == RaceEventStatus.CANCELLED:
        return LifecycleDecision(action="noop", reason_code="terminal_cancelled")
    if status == RaceEventStatus.POSTPONED:
        return LifecycleDecision(action="noop", reason_code="postponed_awaiting_new_time")
    if status == RaceEventStatus.FINISHED:
        return LifecycleDecision(action="noop", reason_code="already_finished")

    if not isinstance(now, datetime) or django_timezone.is_naive(now):
        return LifecycleDecision(action="error", error_message="now must be aware datetime")

    if race_datetime is not None:
        if not isinstance(race_datetime, datetime) or django_timezone.is_naive(race_datetime):
            return LifecycleDecision(
                action="error",
                error_message="race_datetime must be aware datetime",
            )

        finish_boundary = race_datetime + timedelta(minutes=30)
        if now >= finish_boundary:
            return LifecycleDecision(
                action="transition",
                to_status=RaceEventStatus.FINISHED,
                reason_code="time_t_plus_30",
                effective_at=now,
            )

        if now >= race_datetime and status == RaceEventStatus.SCHEDULED:
            return LifecycleDecision(
                action="transition",
                to_status=RaceEventStatus.RUNNING,
                reason_code="time_reached_race_datetime",
                effective_at=now,
            )

        return LifecycleDecision(action="noop", reason_code="before_race_datetime")

    # ── no race_datetime — use local_date ──
    if local_date is None:
        return LifecycleDecision(
            action="error",
            error_message="neither race_datetime nor local_date provided",
        )

    midnight_utc = _local_next_midnight(local_date, timezone_name)
    if now >= midnight_utc:
        return LifecycleDecision(
            action="transition",
            to_status=RaceEventStatus.FINISHED,
            reason_code="local_next_day_midnight",
            effective_at=now,
        )

    return LifecycleDecision(action="noop", reason_code="before_local_midnight")


# ── effective mode resolution ─────────────────────────────────────────

def _effective_mode(global_mode: str, control_mode: str) -> str:
    """Resolve the effective operating mode.

    The global mode is a ceiling that lower modes cannot raise.
    """
    if global_mode not in ("shadow", "enforce"):
        return global_mode  # "off", "dry_run", etc.
    if control_mode not in ("shadow", "enforce"):
        return control_mode
    # Enforce beats shadow only if global also allows enforce
    if global_mode == "shadow":
        return "shadow"
    return control_mode  # global=enforce → use per-control mode


# ── atomic apply ──────────────────────────────────────────────────────

def apply_race_lifecycle_decision(
    *,
    event_id: int,
    expected_generation: int,
    now: datetime,
    mode: str,
    dry_run: bool = False,
    run_id: str = "",
    attempt_token: str = "",
    expected_claim_generation: int = 0,
    allowed_us_zones: frozenset[str] | None = None,
    expected_canary_sha256: str = "",
    expected_canary_event_ids: str = "",
    expected_canary_activation_id: str = "",
) -> ApplyResult:
    """Atomically apply the lifecycle decision for one event.

    Must be called inside transaction.atomic().

    Parameters:
        mode: global lifecycle mode ("off" | "shadow" | "enforce").
              This is a ceiling — shadow caps enforce controls to shadow.
        attempt_token: claim token from the scanner (validates claim identity).
        expected_claim_generation: claim generation from the scanner.
    """
    if dry_run or mode == "dry_run":
        return _apply_dry(event_id, expected_generation, now, allowed_us_zones)

    runtime_enforce = (
        mode == "enforce"
        and (
            getattr(settings, "RACE_EVENT_LIFECYCLE_MODE", "off") == "enforce"
            or expected_canary_sha256
            or expected_canary_event_ids
        )
    )
    prelocked_control = None
    canary_transition_metadata: dict = {}
    # Global enforce still permits per-control shadow.  Read the target mode
    # before taking the ordered cohort locks so an out-of-cohort shadow control
    # keeps producing proposals instead of being rejected by the canary gate.
    # Promotion is allowed only while the runtime is false/off, so a mode
    # change during a live enforce run is itself invalid and is checked below.
    target_control_mode = None
    if runtime_enforce:
        target_control_mode = (
            RaceEventLifecycleControl.objects.filter(event_id=event_id)
            .values_list("mode", flat=True)
            .first()
        )
    if runtime_enforce and target_control_mode == RaceEventLifecycleMode.ENFORCE:
        from stable.services.race_event_lifecycle_canary import (
            CanaryError,
            parse_canary_event_ids,
        )
        try:
            cohort_ids = parse_canary_event_ids(
                expected_canary_event_ids
                or getattr(
                    settings,
                    "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS",
                    "",
                )
            )
        except CanaryError:
            return ApplyResult(
                action="noop", reason_code="canary_runtime_settings_invalid"
            )
        if event_id not in cohort_ids:
            return ApplyResult(action="noop", reason_code="canary_event_out_of_scope")
        cohort_controls = list(
            RaceEventLifecycleControl.objects.select_for_update(of=("self",))
            .filter(event_id__in=cohort_ids)
            .order_by("event_id")
        )
        if tuple(item.event_id for item in cohort_controls) != cohort_ids:
            return ApplyResult(
                action="noop", reason_code="canary_control_cohort_incomplete"
            )
        prelocked_control = next(
            item for item in cohort_controls if item.event_id == event_id
        )

    control = _lock_and_validate_control(
        event_id, expected_generation, attempt_token, expected_claim_generation, now,
        prelocked_control=prelocked_control,
    )
    if isinstance(control, ApplyResult):
        return control  # validation failed

    event = _lock_event(event_id)
    if isinstance(event, ApplyResult):
        return event

    effective = _effective_mode(mode, control.mode)
    if effective not in ("shadow", "enforce"):
        return ApplyResult(action="noop", reason_code=f"effective_mode_{effective}")

    # The canary gate is required only for the real global enforce runtime.
    # Keeping direct, isolated service tests independent of Django's default
    # off setting preserves the pure lower-level API while every production
    # task passes through the independently configured runtime trust root.
    if effective == "enforce" and runtime_enforce:
        if prelocked_control is None:
            return ApplyResult(
                action="noop", reason_code="canary_control_mode_changed"
            )
        from stable.services.race_event_lifecycle_canary import (
            validate_event_for_enforce,
        )

        canary_error = validate_event_for_enforce(
            event=event,
            control=control,
            raw_sha256=expected_canary_sha256
            or getattr(settings, "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256", ""),
            event_ids_text=expected_canary_event_ids
            or getattr(settings, "RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS", ""),
            expected_activation_id=expected_canary_activation_id,
            now=now,
        )
        if canary_error:
            return ApplyResult(action="noop", reason_code=canary_error)
        evidence = control.manifest_data["enforce_canary"]
        canary_transition_metadata = {
            "enforce_canary": {
                "schema_version": 1,
                "raw_sha256": evidence["raw_sha256"],
                "content_sha256": evidence["content_sha256"],
                "event_ids": evidence["event_ids"],
                "approved_commit": evidence["approved_commit"],
                "activation_id": evidence["activation_id"],
            }
        }

    decision = decide_race_lifecycle(
        race_datetime=event.race_datetime,
        timezone_name=event.timezone_name,
        status=event.status,
        now=now,
        local_date=event.local_date,
        region=event.country_region,
        allowed_us_zones=allowed_us_zones,
    )

    if decision.action == "error":
        _record_attempt(control, now, result_code="decision_error", error=decision.error_message)
        _bump_next_refresh_forward(event, control, now)
        return ApplyResult(action="error", error=decision.error_message)
    if decision.action == "noop":
        terminal = decision.reason_code in (
            "already_finished", "terminal_cancelled",
        )
        _record_attempt(control, now, result_code=decision.reason_code)
        _bump_next_refresh_forward(event, control, now, terminal=terminal)
        return ApplyResult(action="noop", reason_code=decision.reason_code)

    if effective == "shadow":
        return _apply_shadow(event, control, decision, now, run_id)
    else:
        return _apply_enforce(
            event,
            control,
            decision,
            now,
            run_id,
            transition_metadata=canary_transition_metadata,
        )

    return ApplyResult(action="noop")


def _lock_and_validate_control(
    event_id: int,
    expected_generation: int,
    attempt_token: str,
    expected_claim_generation: int,
    now: datetime,
    prelocked_control: RaceEventLifecycleControl | None = None,
) -> RaceEventLifecycleControl | ApplyResult:
    """Lock the control row and validate claim identity + generation."""
    if prelocked_control is None:
        try:
            control = RaceEventLifecycleControl.objects.select_for_update(
                of=("self",),
            ).get(event_id=event_id)
        except RaceEventLifecycleControl.DoesNotExist:
            return ApplyResult(action="noop", error="no lifecycle control")
    else:
        control = prelocked_control

    if control.mode == RaceEventLifecycleMode.OFF:
        return ApplyResult(action="noop", reason_code="mode_off")

    if control.schedule_generation != expected_generation:
        return ApplyResult(
            action="generation_stale",
            error="schedule generation mismatch",
            reason_code="generation_stale",
        )

    # Validate claim identity
    if attempt_token:
        if control.claim_token and control.claim_token != attempt_token:
            # Another worker holds an active claim
            if (
                control.claim_expires_at is not None
                and control.claim_expires_at > now
            ):
                return ApplyResult(action="claim_not_expired", reason_code="claim_not_expired")
        if control.claim_generation != expected_claim_generation:
            return ApplyResult(
                action="claim_generation_mismatch",
                error="claim generation mismatch",
                reason_code="claim_generation_mismatch",
            )

    return control


def _lock_event(event_id: int) -> RaceEvent | ApplyResult:
    try:
        return RaceEvent.objects.select_for_update(of=("self",)).get(id=event_id)
    except RaceEvent.DoesNotExist:
        return ApplyResult(action="error", error="event not found")


def _apply_dry(
    event_id: int,
    expected_generation: int,
    now: datetime,
    allowed_us_zones: frozenset[str] | None = None,
) -> ApplyResult:
    try:
        event = RaceEvent.objects.get(id=event_id)
    except RaceEvent.DoesNotExist:
        return ApplyResult(action="error", error="event not found")

    decision = decide_race_lifecycle(
        race_datetime=event.race_datetime,
        timezone_name=event.timezone_name,
        status=event.status,
        now=now,
        local_date=event.local_date,
        region=event.country_region,
        allowed_us_zones=allowed_us_zones,
    )
    return ApplyResult(
        action=decision.action,
        error=decision.error_message if decision.action == "error" else None,
        reason_code=decision.reason_code,
    )


def _apply_shadow(
    event: RaceEvent,
    control: RaceEventLifecycleControl,
    decision: LifecycleDecision,
    now: datetime,
    run_id: str,
) -> ApplyResult:
    dedupe_key = (
        f"proposal:{event.id}:{control.schedule_generation}:"
        f"{decision.reason_code}:{decision.to_status}"
    )
    transition, created = RaceEventLifecycleTransition.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "event": event,
            "from_status": event.status,
            "to_status": decision.to_status,
            "reason_code": decision.reason_code,
            "effective_at": decision.effective_at or now,
            "record_kind": RaceEventLifecycleTransitionKind.PROPOSAL,
            "schedule_generation": control.schedule_generation,
            "trigger_task": "advance_race_event_lifecycle_task",
            "run_id": run_id,
            "source_authority": "time_rule",
        },
    )
    if not created:
        expected_identity = {
            "event_id": event.id,
            "record_kind": RaceEventLifecycleTransitionKind.PROPOSAL,
            "schedule_generation": control.schedule_generation,
            "from_status": event.status,
            "to_status": decision.to_status,
            "reason_code": decision.reason_code,
        }
        conflicting_fields = tuple(
            field_name
            for field_name, expected_value in expected_identity.items()
            if getattr(transition, field_name) != expected_value
        )
        if conflicting_fields:
            error = (
                "existing proposal identity conflict for fields: "
                + ", ".join(conflicting_fields)
            )
            _record_attempt(
                control,
                now,
                result_code="proposal_identity_conflict",
                error=error,
            )
            _bump_next_refresh_forward(event, control, now)
            return ApplyResult(
                action="error",
                error=error,
                reason_code="proposal_identity_conflict",
            )

        _record_attempt(
            control,
            now,
            result_code="proposal_duplicate",
            success=True,
        )
        _bump_next_refresh_forward(event, control, now, to_status=decision.to_status)
        return ApplyResult(action="noop", reason_code="proposal_duplicate")

    _record_attempt(control, now, result_code="shadow_proposed", success=True)
    _recompute_next_refresh(event, control, now, to_status=decision.to_status)
    return ApplyResult(action="proposed", transition_id=transition.id)


def _apply_enforce(
    event: RaceEvent,
    control: RaceEventLifecycleControl,
    decision: LifecycleDecision,
    now: datetime,
    run_id: str,
    transition_metadata: dict | None = None,
) -> ApplyResult:
    applied_dedupe_key = (
        f"applied:{event.id}:{control.schedule_generation}:"
        f"{decision.reason_code}:{decision.to_status}"
    )
    if RaceEventLifecycleTransition.objects.filter(
        dedupe_key=applied_dedupe_key
    ).exists():
        _record_attempt(control, now, result_code="applied_duplicate")
        _bump_next_refresh_forward(event, control, now)
        return ApplyResult(action="noop", reason_code="applied_duplicate")

    proposal_dedupe_key = (
        f"proposal:{event.id}:{control.schedule_generation}:"
        f"{decision.reason_code}:{decision.to_status}"
    )
    based_on = RaceEventLifecycleTransition.objects.filter(
        dedupe_key=proposal_dedupe_key,
        record_kind=RaceEventLifecycleTransitionKind.PROPOSAL,
    ).first()

    transition = RaceEventLifecycleTransition.objects.create(
        event=event,
        from_status=event.status,
        to_status=decision.to_status,
        reason_code=decision.reason_code,
        effective_at=decision.effective_at or now,
        record_kind=RaceEventLifecycleTransitionKind.APPLIED,
        dedupe_key=applied_dedupe_key,
        schedule_generation=control.schedule_generation,
        trigger_task="advance_race_event_lifecycle_task",
        run_id=run_id,
        source_authority="time_rule",
        based_on_proposal=based_on,
        metadata=transition_metadata or {},
    )

    event.status = decision.to_status
    event.save(update_fields=("status", "updated_at"))

    _record_attempt(control, now, result_code="enforce_applied", success=True)
    _recompute_next_refresh(event, control, now)

    transaction.on_commit(invalidate_public_race_cache)

    return ApplyResult(action="applied", transition_id=transition.id)


def _record_attempt(
    control: RaceEventLifecycleControl,
    now: datetime,
    result_code: str = "",
    error: str = "",
    success: bool = False,
) -> None:
    control.last_attempt_at = now
    control.last_result_code = result_code
    control.last_error = error
    if success:
        control.last_success_at = now
        control.consecutive_failures = 0
    elif result_code not in ("noop", "proposal_duplicate", "applied_duplicate",
                              "before_race_datetime", "before_local_midnight",
                              "generation_stale", "claim_not_expired",
                              "claim_generation_mismatch", "mode_off",
                              "effective_mode_off", "already_finished",
                              "terminal_cancelled", "postponed_awaiting_new_time"):
        control.consecutive_failures = control.consecutive_failures + 1
    control.claim_token = ""
    control.claim_expires_at = None
    control.save(
        update_fields=(
            "last_attempt_at", "last_result_code", "last_error",
            "last_success_at", "consecutive_failures",
            "claim_token", "claim_expires_at", "updated_at",
        )
    )


def _recompute_next_refresh(
    event: RaceEvent,
    control: RaceEventLifecycleControl,
    now: datetime,
    to_status: str = "",
) -> None:
    """Set next_refresh_at after a transition (or shadow proposal).

    *to_status* overrides event.status for computing the next due time.
    This is essential for shadow mode, where event.status is unchanged.
    """
    effective_status = to_status or event.status
    if effective_status == RaceEventStatus.FINISHED:
        control.next_refresh_at = None
    elif effective_status == RaceEventStatus.RUNNING:
        if event.race_datetime:
            control.next_refresh_at = event.race_datetime + timedelta(minutes=30)
        else:
            control.next_refresh_at = now + timedelta(hours=24)
    else:
        if event.race_datetime:
            control.next_refresh_at = event.race_datetime
        elif event.local_date:
            control.next_refresh_at = _local_next_midnight(event.local_date, event.timezone_name)
        else:
            control.next_refresh_at = now + timedelta(hours=24)
    control.save(update_fields=("next_refresh_at", "updated_at"))


def _bump_next_refresh_forward(
    event: RaceEvent,
    control: RaceEventLifecycleControl,
    now: datetime,
    terminal: bool = False,
    to_status: str = "",
) -> None:
    """Advance next_refresh_at when past-due, with behaviour varying by state.

    Terminal states → None.  *to_status* overrides event.status for
    computing the correct boundary (used for shadow duplicate where the
    proposal already decided the next logical state).
    """
    if control.next_refresh_at is None or control.next_refresh_at > now:
        return

    effective = to_status or event.status
    if terminal or effective in (
        RaceEventStatus.CANCELLED,
        RaceEventStatus.FINISHED,
        RaceEventStatus.POSTPONED,
    ):
        control.next_refresh_at = None
    elif effective == RaceEventStatus.RUNNING and event.race_datetime:
        control.next_refresh_at = event.race_datetime + timedelta(minutes=30)
    elif event.race_datetime and event.race_datetime > now:
        control.next_refresh_at = event.race_datetime
    else:
        cap = timedelta(hours=6)
        step = timedelta(minutes=5 * (2 ** min(control.consecutive_failures, 6)))
        if step > cap:
            step = cap
        control.next_refresh_at = now + step

    control.save(update_fields=("next_refresh_at", "updated_at"))


# ── claim (scanner) ───────────────────────────────────────────────────

def claim_due_lifecycle_controls(
    *,
    now: datetime,
    batch_size: int,
    ttl_seconds: int,
    enforce_event_ids: tuple[int, ...] | None = None,
) -> list[LifecycleBatchClaim]:
    """Atomically claim a bounded batch of due lifecycle control rows.

    Uses select_for_update(skip_locked) + bulk_update for ~2 queries total.
    """
    if not isinstance(now, datetime) or django_timezone.is_naive(now):
        return []
    if not isinstance(batch_size, int) or batch_size < 1 or batch_size > 200:
        return []
    if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        return []

    with transaction.atomic():
        mode_scope = Q(mode=RaceEventLifecycleMode.SHADOW)
        if enforce_event_ids is None:
            mode_scope |= Q(mode=RaceEventLifecycleMode.ENFORCE)
        elif enforce_event_ids:
            mode_scope |= Q(
                mode=RaceEventLifecycleMode.ENFORCE,
                event_id__in=enforce_event_ids,
            )
        due_rows = list(
            RaceEventLifecycleControl.objects.select_for_update(
                skip_locked=True,
                of=("self",),
            )
            .filter(
                mode_scope,
                next_refresh_at__lte=now,
                manual_pause_reason="",
            )
            .filter(
                Q(claim_token="")
                | (
                    Q(claim_token__gt="")
                    & Q(claim_expires_at__isnull=False)
                    & Q(claim_expires_at__lte=now)
                )
            )
            .order_by("next_refresh_at", "event_id")[:batch_size]
        )

        if not due_rows:
            return []

        claim_expires_at = now + timedelta(seconds=ttl_seconds)
        claims: list[LifecycleBatchClaim] = []
        update_fields = (
            "claim_token", "claim_generation", "claim_expires_at",
            "last_attempt_at",
        )
        for ctrl in due_rows:
            token = uuid.uuid4().hex
            ctrl.claim_token = token
            ctrl.claim_generation += 1
            ctrl.claim_expires_at = claim_expires_at
            ctrl.last_attempt_at = now
            claims.append(
                LifecycleBatchClaim(
                    event_id=ctrl.event_id,
                    schedule_generation=ctrl.schedule_generation,
                    claim_generation=ctrl.claim_generation,
                    attempt_token=token,
                )
            )

        RaceEventLifecycleControl.objects.bulk_update(
            due_rows, fields=update_fields,
        )

        return claims


# ── enrollment reconciler ─────────────────────────────────────────────

def reconcile_lifecycle_controls(
    *,
    event_ids: list[int],
    manifest_sha256: str,
    apply: bool = False,
    eligibility_snapshot: dict[str, dict[str, Any]] | None = None,
    target_modes: dict[str, str] | None = None,
) -> dict[str, int]:
    """Create or update lifecycle controls for the given event IDs.

    On creation: schedule_generation starts at 1.
    On update: schedule_generation is bumped only when local_date or
    race_datetime actually changed (not on every reconcile).

    Returns stats: {created, updated, disabled, replayed, ineligible, total}
    """
    stats: dict[str, int] = {
        "created": 0, "updated": 0, "disabled": 0,
        "replayed": 0, "ineligible": 0, "total": len(event_ids),
    }

    if not apply:
        now = django_timezone.now()
        for event_id in event_ids:
            try:
                event = RaceEvent.objects.get(id=event_id)
            except RaceEvent.DoesNotExist:
                stats["ineligible"] += 1
                continue
            if not _is_eligible(event, eligibility_snapshot):
                stats["ineligible"] += 1
                continue
            # Dry-run: compute lifecycle decision for diagnostics
            decision = decide_race_lifecycle(
                race_datetime=event.race_datetime,
                timezone_name=event.timezone_name,
                status=event.status,
                now=now,
                local_date=event.local_date,
                region=event.country_region,
            )
            if decision.action == "transition":
                stats["eligible_transition"] = stats.get("eligible_transition", 0) + 1
            elif decision.action == "noop":
                stats["eligible_noop"] = stats.get("eligible_noop", 0) + 1
            elif decision.action == "error":
                stats["eligible_error"] = stats.get("eligible_error", 0) + 1
        return stats

    for event_id in event_ids:
        try:
            event = RaceEvent.objects.get(id=event_id)
        except RaceEvent.DoesNotExist:
            stats["ineligible"] += 1
            continue

        if not _is_eligible(event, eligibility_snapshot):
            _ensure_control_disabled(event)
            stats["disabled"] += 1
            continue

        target_mode = (
            target_modes.get(str(event_id), "shadow")
            if target_modes
            else "shadow"
        )

        new_refresh = _initial_next_refresh(event)
        # Frozen schedule hash from manifest — trust root, not live DB
        manifest_schedule_hash = ""
        if target_modes:
            manifest_schedule_hash = target_modes.get(f"schedule_hash:{event_id}", "")
        if not manifest_schedule_hash:
            # Dry-run fallback: compute from live event
            manifest_schedule_hash = _compute_schedule_hash(event)

        manifest_meta: dict[str, Any] = {
            "enrollment_schedule_hash": manifest_schedule_hash,
        }
        # US zone allowlist from frozen manifest
        zones_key = f"us_zones:{event_id}"
        if target_modes and zones_key in target_modes:
            zones = target_modes[zones_key]
            if isinstance(zones, (list, tuple, set, frozenset)):
                manifest_meta["allowed_us_zones"] = sorted(zones)

        try:
            control = RaceEventLifecycleControl.objects.get(event=event)
        except RaceEventLifecycleControl.DoesNotExist:
            RaceEventLifecycleControl.objects.create(
                event=event,
                mode=target_mode,
                enrollment_manifest_sha256=manifest_sha256,
                manifest_data=manifest_meta,
                schedule_generation=1,
                next_refresh_at=new_refresh,
            )
            stats["created"] += 1
            continue

        # Same manifest — replay. All contents are frozen and immutable.
        if control.enrollment_manifest_sha256 == manifest_sha256:
            stats["replayed"] += 1
            continue

        # Different manifest: compare frozen schedule hash
        frozen_hash = control.manifest_data.get("enrollment_schedule_hash", "")
        current_hash = _compute_schedule_hash(event)
        schedule_changed = bool(
            frozen_hash
            and manifest_schedule_hash
            and frozen_hash != manifest_schedule_hash
            and control.schedule_generation > 0
        )
        new_gen = (
            control.schedule_generation + 1
            if schedule_changed
            else control.schedule_generation
        )

        control.mode = target_mode
        control.enrollment_manifest_sha256 = manifest_sha256
        control.manifest_data = manifest_meta
        control.next_refresh_at = new_refresh
        if schedule_changed:
            control.schedule_generation = new_gen
        control.save(
            update_fields=[
                "mode", "enrollment_manifest_sha256", "manifest_data",
                "next_refresh_at", "schedule_generation", "updated_at",
            ]
        )
        stats["updated"] += 1

    return stats


def _is_eligible(
    event: RaceEvent,
    snapshot: dict[str, dict[str, Any]] | None,
) -> bool:
    if snapshot and str(event.id) in snapshot:
        snap = snapshot[str(event.id)]
        return bool(
            snap.get("is_key_race")
            and snap.get("is_published")
            and not snap.get("is_cancelled")
        )
    return (
        event.is_key_race
        and event.visibility_status == "published"
        and event.status != RaceEventStatus.CANCELLED
    )


def _ensure_control_disabled(event: RaceEvent) -> None:
    RaceEventLifecycleControl.objects.filter(event=event).update(
        mode=RaceEventLifecycleMode.OFF,
    )


def _initial_next_refresh(event: RaceEvent) -> datetime | None:
    if event.race_datetime:
        return event.race_datetime
    if event.local_date:
        return _local_next_midnight(event.local_date, event.timezone_name)
    return django_timezone.now() + timedelta(hours=24)


def _compute_schedule_hash(event: RaceEvent) -> str:
    """Stable full SHA-256 of the event schedule fields, for generation bumping."""
    raw = json.dumps(
        [
            event.race_datetime.isoformat() if event.race_datetime else None,
            event.local_date.isoformat() if event.local_date else None,
            event.timezone_name,
        ],
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()

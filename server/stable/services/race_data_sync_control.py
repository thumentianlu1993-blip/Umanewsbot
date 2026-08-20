"""Fail-closed control plane for race-data sync R0.

This module owns enrollment, parent claims and shared-snapshot leases.  It has
no provider transport and never publishes race data by itself.
"""

from __future__ import annotations

import re
import secrets
import hashlib
import json
import os
from pathlib import Path
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Min, Q

from stable import models


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_SNAPSHOT_COMPLETE_TTL_SECONDS = 150
_REVIEWED_ARTIFACT_MAX_BYTES = 1024 * 1024
_LEGACY_TRANSFER_RUNTIME_SWITCHES = (
    "RACE_LIVE_SCHEDULER_ENABLED",
    "RACE_LIVE_MONITOR_ENABLED",
    "RACE_DATA_SYNC_ENABLED",
    "RACE_DATA_SYNC_SCHEDULER_ENABLED",
    "RACE_DATA_SYNC_ALLOW_NETWORK",
    "RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED",
    "RACE_DATA_SYNC_RACECARD_APPLY_ENABLED",
    "RACE_DATA_SYNC_RESULT_APPLY_ENABLED",
    "RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED",
    "RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED",
)


@dataclass(frozen=True)
class ControlDecision:
    action: str
    reason_code: str = ""
    event_id: int | None = None
    generation: int = 0


@dataclass(frozen=True)
class RaceDataSyncClaim:
    event_id: int
    enrollment_generation: int
    owner_generation: int
    claim_generation: int
    attempt_token: str
    enrollment_entry_sha256: str
    route_digest: str
    checkpoint_plan: tuple[dict[str, str | int], ...]
    plan_sha256: str

    @property
    def data_kinds(self) -> tuple[str, ...]:
        return tuple(str(item["data_kind"]) for item in self.checkpoint_plan)


def _claim_plan_sha256(
    *,
    event_id: int,
    enrollment_generation: int,
    owner_generation: int,
    claim_generation: int,
    attempt_token: str,
    enrollment_entry_sha256: str,
    route_digest: str,
    checkpoint_plan: Iterable[dict[str, str | int]],
) -> str:
    payload = {
        "event_id": event_id,
        "enrollment_generation": enrollment_generation,
        "owner_generation": owner_generation,
        "claim_generation": claim_generation,
        "attempt_token": attempt_token,
        "enrollment_entry_sha256": enrollment_entry_sha256,
        "route_digest": route_digest,
        "checkpoint_plan": list(checkpoint_plan),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be aware")


def _require_sha(value: str, label: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256")


def _normalize_data_kinds(values: Iterable[str]) -> tuple[str, ...]:
    kinds = tuple(sorted(set(values)))
    if not kinds or any(value not in models.RaceDataSyncDataKind.values for value in kinds):
        raise ValueError("data_kinds are invalid")
    return kinds


def _normalize_scope(values: Iterable[str], label: str) -> tuple[str, ...]:
    normalized = tuple(sorted({str(value).strip() for value in values if str(value).strip()}))
    if not normalized or any(_TOKEN_RE.fullmatch(value) is None for value in normalized):
        raise ValueError(f"{label} is invalid")
    return normalized


def resolve_source_route_admission(
    *,
    source: models.RaceResultSourceIdentity,
    route_digest: str,
    data_kinds: Iterable[str],
    now: datetime,
):
    if (
        not source.region_code
        or not source.identity_namespace
        or source.review_status != models.RaceLiveReviewStatus.APPROVED
        or source.terms_status != models.RaceSourceTermsStatus.APPROVED
        or not source.automation_allowed
        or not source.proof_network_allowed
        or _SHA256_RE.fullmatch(source.evidence_sha256 or "") is None
        or not source.evidence_url.startswith("https://")
    ):
        return "source_identity_not_admitted", None
    if source.valid_until is None or source.valid_until <= now:
        return "source_identity_expired", None
    from stable.services.race_data_sync_pipeline import (
        resolve_race_data_provider_route,
    )

    binding = resolve_race_data_provider_route(
        provider=source.source_key,
        region=source.region_code,
        identity_namespace=source.identity_namespace,
        data_kinds=data_kinds,
    )
    if binding is None:
        return "provider_route_unavailable", None
    if (
        source.registry_digest != binding.registry_digest
        or route_digest != binding.route_digest
    ):
        return "source_route_drift", None
    return "", binding


def source_admission_reason(
    *,
    source: models.RaceResultSourceIdentity,
    route_digest: str,
    data_kinds: Iterable[str],
    now: datetime,
) -> str:
    reason, _binding = resolve_source_route_admission(
        source=source,
        route_digest=route_digest,
        data_kinds=data_kinds,
        now=now,
    )
    return reason


def _lock_checkpoints_before_source(
    *,
    event: models.RaceEvent,
    tracking: models.RaceEventLiveTracking,
    source_identity_id: int,
) -> tuple[dict | None, dict[str, models.RaceEventLiveProviderCheckpoint]]:
    """Freeze the checkpoint namespace before taking the source row lock."""

    source_hint = (
        models.RaceResultSourceIdentity.objects.filter(
            pk=source_identity_id,
            event=event,
        )
        .values("source_key")
        .first()
    )
    if source_hint is None:
        return None, {}
    checkpoints = {
        row.data_kind: row
        for row in models.RaceEventLiveProviderCheckpoint.objects.select_for_update()
        .filter(tracking=tracking, source_key=source_hint["source_key"])
        .order_by("source_key", "data_kind")
    }
    return source_hint, checkpoints


def acquire_enrollment(
    *,
    event_id: int,
    source_identity_id: int,
    standing_policy_digest: str,
    route_digest: str,
    event_snapshot_sha256: str,
    manifest_sha256: str,
    entry_sha256: str,
    expected_owner: str,
    expected_owner_generation: int,
    data_kinds: Iterable[str],
    now: datetime,
) -> ControlDecision:
    """CAS an unmanaged event into the dedicated data-sync owner.

    Existing LIVE/HISTORICAL/MANUAL_PAUSED owners are never adopted here.
    A future reviewed transfer service must handle LIVE -> DATA_SYNC.
    """

    _require_aware(now, "now")
    for value, label in (
        (standing_policy_digest, "standing_policy_digest"),
        (route_digest, "route_digest"),
        (event_snapshot_sha256, "event_snapshot_sha256"),
        (manifest_sha256, "manifest_sha256"),
        (entry_sha256, "entry_sha256"),
    ):
        _require_sha(value, label)
    if expected_owner not in models.RaceEventProjectionWriteOwner.values:
        raise ValueError("expected_owner is invalid")
    if isinstance(expected_owner_generation, bool) or expected_owner_generation < 0:
        raise ValueError("expected_owner_generation is invalid")
    normalized_kinds = _normalize_data_kinds(data_kinds)

    with transaction.atomic():
        event = (
            models.RaceEvent.objects.select_for_update(of=("self",))
            .filter(pk=event_id)
            .first()
        )
        if event is None:
            return ControlDecision("rejected", "event_missing", event_id)
        control, _ = models.RaceEventProjectionControl.objects.get_or_create(event=event)
        control = models.RaceEventProjectionControl.objects.select_for_update().get(
            pk=control.pk
        )

        if control.write_owner in {
            models.RaceEventProjectionWriteOwner.LIVE,
            models.RaceEventProjectionWriteOwner.HISTORICAL,
            models.RaceEventProjectionWriteOwner.MANUAL_PAUSED,
        }:
            return ControlDecision(
                "rejected",
                "writer_owner_conflict",
                event_id,
                control.owner_generation,
            )
        if (
            control.write_owner != expected_owner
            or control.owner_generation != expected_owner_generation
        ):
            return ControlDecision(
                "rejected",
                "owner_cas_stale",
                event_id,
                control.owner_generation,
            )

        tracking, _ = models.RaceEventLiveTracking.objects.get_or_create(event=event)
        tracking = models.RaceEventLiveTracking.objects.select_for_update().get(
            pk=tracking.pk
        )
        enrollment = (
            models.RaceDataSyncEnrollment.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        source_hint, checkpoints = _lock_checkpoints_before_source(
            event=event,
            tracking=tracking,
            source_identity_id=source_identity_id,
        )
        source = (
            models.RaceResultSourceIdentity.objects.select_for_update()
            .filter(pk=source_identity_id, event=event)
            .first()
        )
        if (
            source is None
            or source_hint is None
            or source.source_key != source_hint["source_key"]
        ):
            return ControlDecision("rejected", "source_identity_missing", event_id)
        source_reason, route_binding = resolve_source_route_admission(
            source=source,
            route_digest=route_digest,
            data_kinds=normalized_kinds,
            now=now,
        )
        if source_reason:
            return ControlDecision("rejected", source_reason, event_id)
        assert route_binding is not None

        if control.write_owner == models.RaceEventProjectionWriteOwner.DATA_SYNC:
            if (
                enrollment is not None
                and enrollment.state == models.RaceDataSyncEnrollmentState.ENROLLED
                and enrollment.source_identity_id == source.pk
                and enrollment.standing_policy_digest == standing_policy_digest
                and enrollment.route_digest == route_digest
                and enrollment.event_snapshot_sha256 == event_snapshot_sha256
                and enrollment.manifest_sha256 == manifest_sha256
                and enrollment.entry_sha256 == entry_sha256
                and enrollment.projection_owner_generation == control.owner_generation
                and enrollment.enrollment_generation == control.owner_generation
            ):
                return ControlDecision(
                    "replay", "", event_id, control.owner_generation
                )
            return ControlDecision(
                "rejected",
                "owner_cas_stale",
                event_id,
                control.owner_generation,
            )

        if control.write_owner != models.RaceEventProjectionWriteOwner.UNMANAGED:
            return ControlDecision(
                "rejected",
                "writer_owner_conflict",
                event_id,
                control.owner_generation,
            )
        if enrollment is not None and enrollment.state != models.RaceDataSyncEnrollmentState.RETIRED:
            return ControlDecision(
                "rejected",
                "enrollment_state_conflict",
                event_id,
                control.owner_generation,
            )

        next_generation = control.owner_generation + 1
        control.write_owner = models.RaceEventProjectionWriteOwner.DATA_SYNC
        control.owner_generation = next_generation
        control.owner_manifest_sha256 = manifest_sha256
        control.owner_changed_at = now
        control.save(
            update_fields=(
                "write_owner",
                "owner_generation",
                "owner_manifest_sha256",
                "owner_changed_at",
                "updated_at",
            )
        )

        if enrollment is None:
            enrollment = models.RaceDataSyncEnrollment(event=event)
        enrollment.source_identity = source
        enrollment.state = models.RaceDataSyncEnrollmentState.ENROLLED
        enrollment.standing_policy_digest = standing_policy_digest
        enrollment.route_digest = route_digest
        enrollment.event_snapshot_sha256 = event_snapshot_sha256
        enrollment.projection_owner_generation = next_generation
        enrollment.enrollment_generation = next_generation
        enrollment.manifest_sha256 = manifest_sha256
        enrollment.entry_sha256 = entry_sha256
        enrollment.reason_code = ""
        enrollment.effective_at = now
        enrollment.retired_at = None
        enrollment.save()

        tracking.tracking_enabled = True
        tracking.next_poll_at = now
        tracking.claim_generation += 1
        tracking.active_attempt_token = ""
        tracking.claim_expires_at = None
        tracking.lock_version += 1
        tracking.save(
            update_fields=(
                "tracking_enabled",
                "next_poll_at",
                "claim_generation",
                "active_attempt_token",
                "claim_expires_at",
                "lock_version",
                "updated_at",
            )
        )
        for data_kind in normalized_kinds:
            checkpoint = checkpoints.get(data_kind)
            if checkpoint is None:
                models.RaceEventLiveProviderCheckpoint.objects.create(
                    tracking=tracking,
                    source_key=source.source_key,
                    data_kind=data_kind,
                    next_poll_at=now,
                    contract_digest=route_binding.contract_digest,
                    registry_digest=route_binding.registry_digest,
                )
            else:
                checkpoint.next_poll_at = now
                checkpoint.contract_digest = route_binding.contract_digest
                checkpoint.registry_digest = route_binding.registry_digest
                checkpoint.save(
                    update_fields=(
                        "next_poll_at",
                        "contract_digest",
                        "registry_digest",
                        "updated_at",
                    )
                )
        return ControlDecision("acquired", "", event_id, next_generation)


def rotate_enrollment(
    *,
    event_id: int,
    source_identity_id: int,
    standing_policy_digest: str,
    route_digest: str,
    event_snapshot_sha256: str,
    successor_manifest_sha256: str,
    successor_entry_sha256: str,
    expected_manifest_sha256: str,
    expected_owner_generation: int,
    data_kinds: Iterable[str],
    now: datetime,
) -> ControlDecision:
    """Rotate an enrolled event to one exact reviewed successor manifest."""

    _require_aware(now, "now")
    for value, label in (
        (standing_policy_digest, "standing_policy_digest"),
        (route_digest, "route_digest"),
        (event_snapshot_sha256, "event_snapshot_sha256"),
        (successor_manifest_sha256, "successor_manifest_sha256"),
        (successor_entry_sha256, "successor_entry_sha256"),
        (expected_manifest_sha256, "expected_manifest_sha256"),
    ):
        _require_sha(value, label)
    if isinstance(expected_owner_generation, bool) or expected_owner_generation < 1:
        raise ValueError("expected_owner_generation is invalid")
    normalized_kinds = _normalize_data_kinds(data_kinds)

    with transaction.atomic():
        event = (
            models.RaceEvent.objects.select_for_update(of=("self",))
            .filter(pk=event_id)
            .first()
        )
        if event is None:
            return ControlDecision("rejected", "event_missing", event_id)
        control = (
            models.RaceEventProjectionControl.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        tracking = (
            models.RaceEventLiveTracking.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        enrollment = (
            models.RaceDataSyncEnrollment.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        source_hint = (
            models.RaceResultSourceIdentity.objects.filter(
                pk=source_identity_id,
                event=event,
            )
            .values("source_key")
            .first()
        )
        locked_checkpoints = (
            tuple(
                models.RaceEventLiveProviderCheckpoint.objects.select_for_update()
                .filter(tracking=tracking)
                .order_by("source_key", "data_kind")
            )
            if tracking is not None
            else ()
        )
        checkpoints = {
            checkpoint.data_kind: checkpoint
            for checkpoint in locked_checkpoints
            if source_hint is not None
            and checkpoint.source_key == source_hint["source_key"]
        }
        source = (
            models.RaceResultSourceIdentity.objects.select_for_update()
            .filter(pk=source_identity_id, event=event)
            .first()
        )
        if (
            control is None
            or tracking is None
            or enrollment is None
            or source is None
            or source_hint is None
            or source.source_key != source_hint["source_key"]
        ):
            return ControlDecision("rejected", "enrollment_missing", event_id)
        if (
            control.write_owner != models.RaceEventProjectionWriteOwner.DATA_SYNC
            or control.owner_generation != expected_owner_generation
            or control.owner_manifest_sha256 != expected_manifest_sha256
            or enrollment.state != models.RaceDataSyncEnrollmentState.ENROLLED
            or enrollment.manifest_sha256 != expected_manifest_sha256
            or enrollment.projection_owner_generation != expected_owner_generation
            or enrollment.enrollment_generation != expected_owner_generation
        ):
            return ControlDecision(
                "rejected", "owner_cas_stale", event_id, control.owner_generation
            )
        if (
            enrollment.source_identity_id != source.pk
            or enrollment.standing_policy_digest != standing_policy_digest
            or enrollment.route_digest != route_digest
        ):
            return ControlDecision(
                "rejected", "enrollment_baseline_drift", event_id, control.owner_generation
            )
        if tracking.active_attempt_token and (
            tracking.claim_expires_at is None or tracking.claim_expires_at > now
        ):
            return ControlDecision(
                "rejected", "active_claim_exists", event_id, control.owner_generation
            )
        source_reason, route_binding = resolve_source_route_admission(
            source=source,
            route_digest=route_digest,
            data_kinds=normalized_kinds,
            now=now,
        )
        if source_reason:
            return ControlDecision(
                "rejected", source_reason, event_id, control.owner_generation
            )
        assert route_binding is not None

        next_generation = control.owner_generation + 1
        control.owner_generation = next_generation
        control.owner_manifest_sha256 = successor_manifest_sha256
        control.owner_changed_at = now
        control.save(
            update_fields=(
                "owner_generation",
                "owner_manifest_sha256",
                "owner_changed_at",
                "updated_at",
            )
        )
        enrollment.event_snapshot_sha256 = event_snapshot_sha256
        enrollment.projection_owner_generation = next_generation
        enrollment.enrollment_generation = next_generation
        enrollment.manifest_sha256 = successor_manifest_sha256
        enrollment.entry_sha256 = successor_entry_sha256
        enrollment.reason_code = ""
        enrollment.effective_at = now
        enrollment.save(
            update_fields=(
                "event_snapshot_sha256",
                "projection_owner_generation",
                "enrollment_generation",
                "manifest_sha256",
                "entry_sha256",
                "reason_code",
                "effective_at",
                "updated_at",
            )
        )
        tracking.tracking_enabled = True
        tracking.claim_generation += 1
        tracking.active_attempt_token = ""
        tracking.claim_expires_at = None
        tracking.lock_version += 1
        tracking.save(
            update_fields=(
                "tracking_enabled",
                "claim_generation",
                "active_attempt_token",
                "claim_expires_at",
                "lock_version",
                "updated_at",
            )
        )
        for kind in normalized_kinds:
            checkpoint = checkpoints.get(kind)
            if checkpoint is None:
                models.RaceEventLiveProviderCheckpoint.objects.create(
                    tracking=tracking,
                    source_key=source.source_key,
                    data_kind=kind,
                    next_poll_at=now,
                    contract_digest=route_binding.contract_digest,
                    registry_digest=route_binding.registry_digest,
                )
            elif (
                checkpoint.next_poll_at is None
                or checkpoint.contract_digest != route_binding.contract_digest
                or checkpoint.registry_digest != route_binding.registry_digest
            ):
                checkpoint.next_poll_at = now
                checkpoint.contract_digest = route_binding.contract_digest
                checkpoint.registry_digest = route_binding.registry_digest
                checkpoint.lock_version += 1
                checkpoint.save(
                    update_fields=(
                        "next_poll_at",
                        "contract_digest",
                        "registry_digest",
                        "lock_version",
                        "updated_at",
                    )
                )
        models.RaceEventLiveProviderCheckpoint.objects.filter(
            tracking=tracking,
            source_key=source.source_key,
        ).exclude(data_kind__in=normalized_kinds).update(next_poll_at=None, updated_at=now)
        next_due = (
            models.RaceEventLiveProviderCheckpoint.objects.filter(tracking=tracking)
            .aggregate(next_poll_at=Min("next_poll_at"))["next_poll_at"]
        )
        tracking.next_poll_at = next_due
        tracking.save(update_fields=("next_poll_at", "updated_at"))
        return ControlDecision("rotated", "", event_id, next_generation)


def disenroll(
    *,
    event_id: int,
    expected_manifest_sha256: str,
    expected_owner_generation: int,
    now: datetime,
) -> ControlDecision:
    _require_aware(now, "now")
    _require_sha(expected_manifest_sha256, "expected_manifest_sha256")
    with transaction.atomic():
        event = (
            models.RaceEvent.objects.select_for_update(of=("self",))
            .filter(pk=event_id)
            .first()
        )
        if event is None:
            return ControlDecision("rejected", "event_missing", event_id)
        control = (
            models.RaceEventProjectionControl.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        tracking = (
            models.RaceEventLiveTracking.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        enrollment = (
            models.RaceDataSyncEnrollment.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        if control is None or tracking is None or enrollment is None:
            return ControlDecision("rejected", "enrollment_missing", event_id)
        checkpoints = tuple(
            models.RaceEventLiveProviderCheckpoint.objects.select_for_update()
            .filter(tracking=tracking)
            .order_by("source_key", "data_kind")
        )
        if (
            control.write_owner != models.RaceEventProjectionWriteOwner.DATA_SYNC
            or control.owner_generation != expected_owner_generation
            or control.owner_manifest_sha256 != expected_manifest_sha256
            or enrollment.manifest_sha256 != expected_manifest_sha256
            or enrollment.projection_owner_generation != expected_owner_generation
        ):
            return ControlDecision(
                "rejected", "owner_cas_stale", event_id, control.owner_generation
            )
        if tracking.active_attempt_token and (
            tracking.claim_expires_at is None or tracking.claim_expires_at > now
        ):
            return ControlDecision(
                "rejected", "active_claim_exists", event_id, control.owner_generation
            )

        control.write_owner = models.RaceEventProjectionWriteOwner.UNMANAGED
        control.owner_generation += 1
        control.owner_manifest_sha256 = ""
        control.owner_changed_at = now
        control.save(
            update_fields=(
                "write_owner",
                "owner_generation",
                "owner_manifest_sha256",
                "owner_changed_at",
                "updated_at",
            )
        )
        tracking.tracking_enabled = False
        tracking.next_poll_at = None
        tracking.claim_generation += 1
        tracking.active_attempt_token = ""
        tracking.claim_expires_at = None
        tracking.lock_version += 1
        tracking.save(
            update_fields=(
                "tracking_enabled",
                "next_poll_at",
                "claim_generation",
                "active_attempt_token",
                "claim_expires_at",
                "lock_version",
                "updated_at",
            )
        )
        for checkpoint in checkpoints:
            checkpoint.next_poll_at = None
            checkpoint.save(update_fields=("next_poll_at", "updated_at"))
        enrollment.state = models.RaceDataSyncEnrollmentState.RETIRED
        enrollment.reason_code = "disenrolled"
        enrollment.retired_at = now
        enrollment.save(
            update_fields=("state", "reason_code", "retired_at", "updated_at")
        )
        return ControlDecision(
            "released", "", event_id, control.owner_generation
        )


def _legacy_transfer_baseline_payload(
    *,
    event: models.RaceEvent,
    control: models.RaceEventProjectionControl,
    tracking: models.RaceEventLiveTracking,
) -> dict:
    checkpoints = list(
        models.RaceEventLiveProviderCheckpoint.objects.filter(tracking=tracking)
        .order_by("source_key", "data_kind")
        .values(
            "source_key",
            "data_kind",
            "next_poll_at",
            "lock_version",
        )
    )
    return {
        "event": {
            "id": event.pk,
            "status": event.status,
            "race_datetime": event.race_datetime.isoformat()
            if event.race_datetime
            else None,
        },
        "projection": {
            "write_owner": control.write_owner,
            "owner_generation": control.owner_generation,
            "owner_manifest_sha256": control.owner_manifest_sha256,
            "current_racecard_revision_id": control.current_racecard_revision_id,
            "last_known_good_racecard_revision_id": control.last_known_good_racecard_revision_id,
            "current_result_revision_id": control.current_result_revision_id,
            "last_known_good_result_revision_id": control.last_known_good_result_revision_id,
            "last_provisional_result_revision_id": control.last_provisional_result_revision_id,
        },
        "tracking": {
            "state": tracking.state,
            "tracking_enabled": tracking.tracking_enabled,
            "claim_generation": tracking.claim_generation,
            "active_attempt_token": tracking.active_attempt_token,
            "claim_expires_at": tracking.claim_expires_at.isoformat()
            if tracking.claim_expires_at
            else None,
            "lock_version": tracking.lock_version,
            "checkpoints": [
                {
                    **row,
                    "next_poll_at": row["next_poll_at"].isoformat()
                    if row["next_poll_at"]
                    else None,
                }
                for row in checkpoints
            ],
        },
    }


def _legacy_transfer_baseline_sha256(
    *,
    event: models.RaceEvent,
    control: models.RaceEventProjectionControl,
    tracking: models.RaceEventLiveTracking,
) -> str:
    encoded = json.dumps(
        _legacy_transfer_baseline_payload(
            event=event,
            control=control,
            tracking=tracking,
        ),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_legacy_transfer_baseline(*, event_id: int) -> str:
    event = models.RaceEvent.objects.filter(pk=event_id).first()
    control = models.RaceEventProjectionControl.objects.filter(event_id=event_id).first()
    tracking = models.RaceEventLiveTracking.objects.filter(event_id=event_id).first()
    if event is None or control is None or tracking is None:
        raise ValueError("legacy transfer subject is incomplete")
    return _legacy_transfer_baseline_sha256(
        event=event,
        control=control,
        tracking=tracking,
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _read_reviewed_json(path_value: str | Path, *, label: str) -> tuple[dict, str]:
    """Read one canonical, immutable-by-identity reviewed artifact."""

    path = Path(path_value)
    try:
        before = path.lstat()
    except OSError as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"{label} must be a regular non-symlink file")
    if before.st_size <= 0 or before.st_size > _REVIEWED_ARTIFACT_MAX_BYTES:
        raise ValueError(f"{label} size is invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{label} cannot be safely opened") from exc
    try:
        opened = os.fstat(descriptor)
        identity_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if tuple(getattr(before, key) for key in identity_fields) != tuple(
            getattr(opened, key) for key in identity_fields
        ):
            raise ValueError(f"{label} changed before open")
        remaining = _REVIEWED_ARTIFACT_MAX_BYTES + 1
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) != opened.st_size
            or len(raw) > _REVIEWED_ARTIFACT_MAX_BYTES
            or tuple(getattr(after, key) for key in identity_fields)
            != tuple(getattr(opened, key) for key in identity_fields)
        ):
            raise ValueError(f"{label} changed while reading")
    finally:
        os.close(descriptor)

    def reject_duplicate(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"{label} contains duplicate JSON keys")
            value[key] = item
        return value

    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(decoded, dict) or raw != _canonical_json_bytes(decoded):
        raise ValueError(f"{label} must be canonical JSON")
    return decoded, hashlib.sha256(raw).hexdigest()


def _assert_legacy_transfer_runtime_closed() -> None:
    if any(getattr(settings, name, False) is True for name in _LEGACY_TRANSFER_RUNTIME_SWITCHES):
        raise ValueError("legacy transfer runtime is currently enabled")
    if str(getattr(settings, "RACE_LIVE_RUNNER_MODE", "disabled")) != "disabled":
        raise ValueError("legacy transfer runtime is currently enabled")


def _validate_transfer_runtime_receipt(
    receipt: object, *, created_at: datetime
) -> str:
    if not isinstance(receipt, dict) or set(receipt) != {
        "schema_version",
        "captured_at",
        "legacy_runtime",
        "queues",
    }:
        raise ValueError("transfer runtime receipt schema is invalid")
    if receipt.get("schema_version") != 1:
        raise ValueError("transfer runtime receipt version is invalid")
    try:
        captured_at = datetime.fromisoformat(
            str(receipt.get("captured_at") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("transfer runtime receipt time is invalid") from exc
    _require_aware(captured_at, "transfer runtime receipt captured_at")
    if not created_at - timedelta(minutes=15) <= captured_at <= created_at:
        raise ValueError("transfer runtime receipt is stale")
    runtime = receipt.get("legacy_runtime")
    if not isinstance(runtime, dict) or set(runtime) != {
        "scheduler_enabled",
        "monitor_enabled",
        "allow_network",
        "racecard_apply_enabled",
        "result_apply_enabled",
    }:
        raise ValueError("transfer runtime receipt runtime is invalid")
    if any(value is not False for value in runtime.values()):
        raise ValueError("transfer runtime is not closed")
    queues = receipt.get("queues")
    if not isinstance(queues, dict) or set(queues) != {"race_live", "race_sync_v2"}:
        raise ValueError("transfer queue receipt is invalid")
    for queue in queues.values():
        if not isinstance(queue, dict) or set(queue) != {
            "drained",
            "message_count",
            "active_claim_count",
        }:
            raise ValueError("transfer queue receipt is invalid")
        if (
            queue.get("drained") is not True
            or type(queue.get("message_count")) is not int
            or queue["message_count"] != 0
            or type(queue.get("active_claim_count")) is not int
            or queue["active_claim_count"] != 0
        ):
            raise ValueError("transfer queue is not drained")
    return _canonical_sha256(receipt)


def build_legacy_transfer_manifest(
    *,
    event_id: int,
    source_identity_id: int,
    standing_policy_digest: str,
    route_digest: str,
    event_snapshot_sha256: str,
    expected_live_manifest_sha256: str,
    expected_owner_generation: int,
    expected_projection_baseline_sha256: str,
    data_kinds: Iterable[str],
    candidate_commit: str,
    created_at: datetime,
    apply_expires_at: datetime,
    runtime_receipt: dict,
) -> dict:
    _require_aware(created_at, "created_at")
    _require_aware(apply_expires_at, "apply_expires_at")
    if not created_at < apply_expires_at <= created_at + timedelta(hours=1):
        raise ValueError("transfer manifest apply window is invalid")
    if _COMMIT_RE.fullmatch(candidate_commit or "") is None:
        raise ValueError("transfer candidate commit is invalid")
    for value, label in (
        (standing_policy_digest, "standing_policy_digest"),
        (route_digest, "route_digest"),
        (event_snapshot_sha256, "event_snapshot_sha256"),
        (expected_live_manifest_sha256, "expected_live_manifest_sha256"),
        (
            expected_projection_baseline_sha256,
            "expected_projection_baseline_sha256",
        ),
    ):
        _require_sha(value, label)
    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
        or isinstance(source_identity_id, bool)
        or not isinstance(source_identity_id, int)
        or source_identity_id <= 0
        or isinstance(expected_owner_generation, bool)
        or not isinstance(expected_owner_generation, int)
        or expected_owner_generation < 1
    ):
        raise ValueError("transfer entry identity is invalid")
    kinds = _normalize_data_kinds(data_kinds)
    receipt_sha256 = _validate_transfer_runtime_receipt(
        runtime_receipt, created_at=created_at
    )
    entry_payload = {
        "event_id": event_id,
        "source_identity_id": source_identity_id,
        "standing_policy_digest": standing_policy_digest,
        "route_digest": route_digest,
        "event_snapshot_sha256": event_snapshot_sha256,
        "expected_live_manifest_sha256": expected_live_manifest_sha256,
        "expected_owner_generation": expected_owner_generation,
        "expected_projection_baseline_sha256": expected_projection_baseline_sha256,
        "data_kinds": list(kinds),
    }
    entry = {**entry_payload, "entry_sha256": _canonical_sha256(entry_payload)}
    payload = {
        "schema_version": 1,
        "candidate_commit": candidate_commit,
        "created_at": created_at.isoformat(),
        "apply_expires_at": apply_expires_at.isoformat(),
        "runtime_receipt_sha256": receipt_sha256,
        "entries": [entry],
    }
    return {**payload, "manifest_sha256": _canonical_sha256(payload)}


def build_legacy_transfer_approval(
    *,
    event_id: int,
    candidate_commit: str,
    transfer_manifest_raw_sha256: str,
    transfer_manifest_sha256: str,
    runtime_receipt_raw_sha256: str,
    runtime_receipt_sha256: str,
    approved_by: str,
    approved_at: datetime,
    apply_expires_at: datetime,
) -> dict:
    """Build the separate approval which operators pin by raw SHA in settings."""

    _require_aware(approved_at, "approved_at")
    _require_aware(apply_expires_at, "apply_expires_at")
    if approved_at >= apply_expires_at:
        raise ValueError("transfer approval window is invalid")
    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
        or _COMMIT_RE.fullmatch(candidate_commit or "") is None
        or not isinstance(approved_by, str)
        or not approved_by.strip()
    ):
        raise ValueError("transfer approval identity is invalid")
    for value, label in (
        (transfer_manifest_raw_sha256, "transfer_manifest_raw_sha256"),
        (transfer_manifest_sha256, "transfer_manifest_sha256"),
        (runtime_receipt_raw_sha256, "runtime_receipt_raw_sha256"),
        (runtime_receipt_sha256, "runtime_receipt_sha256"),
    ):
        _require_sha(value, label)
    payload = {
        "schema_version": 1,
        "operation": "race_data_sync_legacy_transfer",
        "candidate_commit": candidate_commit,
        "approved_by": approved_by.strip(),
        "approved_at": approved_at.isoformat(),
        "apply_expires_at": apply_expires_at.isoformat(),
        "event_ids": [event_id],
        "transfer_manifest_raw_sha256": transfer_manifest_raw_sha256,
        "transfer_manifest_sha256": transfer_manifest_sha256,
        "runtime_receipt_raw_sha256": runtime_receipt_raw_sha256,
        "runtime_receipt_sha256": runtime_receipt_sha256,
    }
    return {**payload, "approval_sha256": _canonical_sha256(payload)}


def transfer_legacy_enrollment(
    *,
    event_id: int,
    transfer_manifest_path: str | Path,
    runtime_receipt_path: str | Path,
    approval_path: str | Path,
    current_commit: str,
    now: datetime,
) -> ControlDecision:
    """Apply one separately approved, raw-SHA-bound legacy transfer bundle."""

    _require_aware(now, "now")
    _assert_legacy_transfer_runtime_closed()
    configured_approval_sha256 = str(
        getattr(settings, "RACE_DATA_SYNC_LEGACY_TRANSFER_APPROVAL_SHA256", "")
        or ""
    )
    _require_sha(
        configured_approval_sha256,
        "RACE_DATA_SYNC_LEGACY_TRANSFER_APPROVAL_SHA256",
    )
    approval, approval_raw_sha256 = _read_reviewed_json(
        approval_path, label="transfer approval"
    )
    if approval_raw_sha256 != configured_approval_sha256:
        raise ValueError("transfer approval is not the configured trust root")
    approval_fields = {
        "schema_version",
        "operation",
        "candidate_commit",
        "approved_by",
        "approved_at",
        "apply_expires_at",
        "event_ids",
        "transfer_manifest_raw_sha256",
        "transfer_manifest_sha256",
        "runtime_receipt_raw_sha256",
        "runtime_receipt_sha256",
        "approval_sha256",
    }
    if set(approval) != approval_fields:
        raise ValueError("transfer approval schema is invalid")
    approval_payload = {
        key: value for key, value in approval.items() if key != "approval_sha256"
    }
    if (
        approval.get("schema_version") != 1
        or approval.get("operation") != "race_data_sync_legacy_transfer"
        or approval.get("approval_sha256") != _canonical_sha256(approval_payload)
        or approval.get("event_ids") != [event_id]
        or not isinstance(approval.get("approved_by"), str)
        or not approval["approved_by"].strip()
    ):
        raise ValueError("transfer approval contract is invalid")
    for label in (
        "transfer_manifest_raw_sha256",
        "transfer_manifest_sha256",
        "runtime_receipt_raw_sha256",
        "runtime_receipt_sha256",
    ):
        _require_sha(approval.get(label), f"approval {label}")
    try:
        approved_at = datetime.fromisoformat(
            str(approval.get("approved_at") or "").replace("Z", "+00:00")
        )
        approval_expires_at = datetime.fromisoformat(
            str(approval.get("apply_expires_at") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("transfer approval time is invalid") from exc
    _require_aware(approved_at, "approved_at")
    _require_aware(approval_expires_at, "approval apply_expires_at")
    if (
        _COMMIT_RE.fullmatch(current_commit or "") is None
        or approval.get("candidate_commit") != current_commit
        or not approved_at <= now < approval_expires_at
    ):
        raise ValueError("transfer approval is outside its apply contract")

    transfer_manifest, transfer_manifest_raw_sha256 = _read_reviewed_json(
        transfer_manifest_path, label="transfer manifest"
    )
    runtime_receipt, runtime_receipt_raw_sha256 = _read_reviewed_json(
        runtime_receipt_path, label="transfer runtime receipt"
    )
    if (
        transfer_manifest_raw_sha256
        != approval["transfer_manifest_raw_sha256"]
        or runtime_receipt_raw_sha256 != approval["runtime_receipt_raw_sha256"]
    ):
        raise ValueError("transfer approval raw artifact binding mismatch")
    required = {
        "schema_version",
        "candidate_commit",
        "created_at",
        "apply_expires_at",
        "runtime_receipt_sha256",
        "entries",
        "manifest_sha256",
    }
    if set(transfer_manifest) != required:
        raise ValueError("transfer manifest schema is invalid")
    if transfer_manifest.get("schema_version") != 1:
        raise ValueError("transfer manifest version is invalid")
    payload = {
        key: value
        for key, value in transfer_manifest.items()
        if key != "manifest_sha256"
    }
    if (
        transfer_manifest.get("manifest_sha256")
        != approval["transfer_manifest_sha256"]
        or _canonical_sha256(payload) != approval["transfer_manifest_sha256"]
    ):
        raise ValueError("transfer manifest digest mismatch")
    if (
        _COMMIT_RE.fullmatch(current_commit or "") is None
        or transfer_manifest.get("candidate_commit") != current_commit
    ):
        raise ValueError("transfer manifest commit mismatch")
    try:
        created_at = datetime.fromisoformat(
            str(transfer_manifest.get("created_at") or "").replace("Z", "+00:00")
        )
        apply_expires_at = datetime.fromisoformat(
            str(transfer_manifest.get("apply_expires_at") or "").replace(
                "Z", "+00:00"
            )
        )
    except ValueError as exc:
        raise ValueError("transfer manifest time is invalid") from exc
    for value, label in ((created_at, "created_at"), (apply_expires_at, "apply_expires_at")):
        _require_aware(value, label)
    if (
        not created_at < apply_expires_at <= created_at + timedelta(hours=1)
        or not created_at <= now < apply_expires_at
        or approval_expires_at != apply_expires_at
        or not created_at <= approved_at < apply_expires_at
    ):
        raise ValueError("transfer manifest is outside its apply window")
    receipt_sha256 = _validate_transfer_runtime_receipt(
        runtime_receipt, created_at=created_at
    )
    if (
        receipt_sha256 != transfer_manifest.get("runtime_receipt_sha256")
        or receipt_sha256 != approval.get("runtime_receipt_sha256")
    ):
        raise ValueError("transfer runtime receipt digest mismatch")
    expected_manifest_sha256 = approval["transfer_manifest_sha256"]
    entries = transfer_manifest.get("entries")
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("transfer manifest entries are invalid")
    entry = entries[0]
    entry_fields = {
        "event_id",
        "source_identity_id",
        "standing_policy_digest",
        "route_digest",
        "event_snapshot_sha256",
        "expected_live_manifest_sha256",
        "expected_owner_generation",
        "expected_projection_baseline_sha256",
        "data_kinds",
        "entry_sha256",
    }
    if not isinstance(entry, dict) or set(entry) != entry_fields:
        raise ValueError("transfer manifest entry schema is invalid")
    entry_payload = {key: value for key, value in entry.items() if key != "entry_sha256"}
    if entry.get("entry_sha256") != _canonical_sha256(entry_payload):
        raise ValueError("transfer manifest entry digest mismatch")
    if entry.get("event_id") != event_id:
        raise ValueError("transfer manifest event mismatch")
    source_identity_id = entry.get("source_identity_id")
    standing_policy_digest = entry.get("standing_policy_digest")
    route_digest = entry.get("route_digest")
    event_snapshot_sha256 = entry.get("event_snapshot_sha256")
    expected_live_manifest_sha256 = entry.get("expected_live_manifest_sha256")
    expected_owner_generation = entry.get("expected_owner_generation")
    expected_projection_baseline_sha256 = entry.get(
        "expected_projection_baseline_sha256"
    )
    normalized_kinds = _normalize_data_kinds(entry.get("data_kinds", ()))
    for value, label in (
        (standing_policy_digest, "standing_policy_digest"),
        (route_digest, "route_digest"),
        (event_snapshot_sha256, "event_snapshot_sha256"),
        (expected_live_manifest_sha256, "expected_live_manifest_sha256"),
        (
            expected_projection_baseline_sha256,
            "expected_projection_baseline_sha256",
        ),
    ):
        _require_sha(value, label)
    if (
        isinstance(source_identity_id, bool)
        or not isinstance(source_identity_id, int)
        or source_identity_id <= 0
        or isinstance(expected_owner_generation, bool)
        or not isinstance(expected_owner_generation, int)
        or expected_owner_generation < 1
    ):
        raise ValueError("transfer manifest entry identity is invalid")

    with transaction.atomic():
        event = models.RaceEvent.objects.select_for_update().filter(pk=event_id).first()
        if event is None:
            return ControlDecision("rejected", "event_missing", event_id)
        control = (
            models.RaceEventProjectionControl.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        tracking = (
            models.RaceEventLiveTracking.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        enrollment = (
            models.RaceDataSyncEnrollment.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        source_hint = (
            models.RaceResultSourceIdentity.objects.filter(
                pk=source_identity_id,
                event=event,
            )
            .values("source_key")
            .first()
        )
        locked_checkpoints = (
            tuple(
                models.RaceEventLiveProviderCheckpoint.objects.select_for_update()
                .filter(tracking=tracking)
                .order_by("source_key", "data_kind")
            )
            if tracking is not None
            else ()
        )
        checkpoints = {
            checkpoint.data_kind: checkpoint
            for checkpoint in locked_checkpoints
            if source_hint is not None
            and checkpoint.source_key == source_hint["source_key"]
        }
        source = (
            models.RaceResultSourceIdentity.objects.select_for_update()
            .filter(pk=source_identity_id, event=event)
            .first()
        )
        if (
            control is None
            or tracking is None
            or source is None
            or source_hint is None
            or source.source_key != source_hint["source_key"]
        ):
            return ControlDecision("rejected", "transfer_subject_missing", event_id)
        if (
            control.write_owner != models.RaceEventProjectionWriteOwner.LIVE
            or control.owner_generation != expected_owner_generation
            or control.owner_manifest_sha256 != expected_live_manifest_sha256
        ):
            return ControlDecision(
                "rejected", "owner_cas_stale", event_id, control.owner_generation
            )
        if tracking.active_attempt_token:
            return ControlDecision(
                "rejected", "active_claim_exists", event_id, control.owner_generation
            )
        if (
            _legacy_transfer_baseline_sha256(
                event=event,
                control=control,
                tracking=tracking,
            )
            != expected_projection_baseline_sha256
        ):
            return ControlDecision(
                "rejected", "transfer_baseline_drift", event_id, control.owner_generation
            )
        source_reason, route_binding = resolve_source_route_admission(
            source=source,
            route_digest=route_digest,
            data_kinds=normalized_kinds,
            now=now,
        )
        if source_reason:
            return ControlDecision(
                "rejected", source_reason, event_id, control.owner_generation
            )
        assert route_binding is not None
        if enrollment is not None and enrollment.state != models.RaceDataSyncEnrollmentState.RETIRED:
            return ControlDecision(
                "rejected", "enrollment_state_conflict", event_id, control.owner_generation
            )

        next_generation = control.owner_generation + 1
        control.write_owner = models.RaceEventProjectionWriteOwner.DATA_SYNC
        control.owner_generation = next_generation
        control.owner_manifest_sha256 = expected_manifest_sha256
        control.owner_changed_at = now
        control.save(
            update_fields=(
                "write_owner",
                "owner_generation",
                "owner_manifest_sha256",
                "owner_changed_at",
                "updated_at",
            )
        )
        if enrollment is None:
            enrollment = models.RaceDataSyncEnrollment(event=event)
        enrollment.source_identity = source
        enrollment.state = models.RaceDataSyncEnrollmentState.ENROLLED
        enrollment.standing_policy_digest = standing_policy_digest
        enrollment.route_digest = route_digest
        enrollment.event_snapshot_sha256 = event_snapshot_sha256
        enrollment.projection_owner_generation = next_generation
        enrollment.enrollment_generation = next_generation
        enrollment.manifest_sha256 = expected_manifest_sha256
        enrollment.entry_sha256 = entry["entry_sha256"]
        enrollment.reason_code = "legacy_transfer"
        enrollment.effective_at = now
        enrollment.retired_at = None
        enrollment.save()

        tracking.tracking_enabled = True
        tracking.next_poll_at = now
        tracking.claim_generation += 1
        tracking.lock_version += 1
        tracking.save(
            update_fields=(
                "tracking_enabled",
                "next_poll_at",
                "claim_generation",
                "lock_version",
                "updated_at",
            )
        )
        for data_kind in normalized_kinds:
            checkpoint = checkpoints.get(data_kind)
            if checkpoint is None:
                models.RaceEventLiveProviderCheckpoint.objects.create(
                    tracking=tracking,
                    source_key=source.source_key,
                    data_kind=data_kind,
                    next_poll_at=now,
                    contract_digest=route_binding.contract_digest,
                    registry_digest=route_binding.registry_digest,
                )
            else:
                checkpoint.next_poll_at = now
                checkpoint.contract_digest = route_binding.contract_digest
                checkpoint.registry_digest = route_binding.registry_digest
                checkpoint.save(
                    update_fields=(
                        "next_poll_at",
                        "contract_digest",
                        "registry_digest",
                        "updated_at",
                    )
                )
        for checkpoint in locked_checkpoints:
            if (
                checkpoint.source_key != source.source_key
                or checkpoint.data_kind not in normalized_kinds
            ):
                checkpoint.next_poll_at = None
                checkpoint.save(update_fields=("next_poll_at", "updated_at"))
        return ControlDecision("transferred", "", event_id, next_generation)


def claim_due_enrollments(
    *,
    now: datetime,
    batch_size: int,
    ttl_seconds: int,
    enabled_providers: Iterable[str],
    enabled_regions: Iterable[str],
    enabled_data_kinds: Iterable[str],
) -> tuple[RaceDataSyncClaim, ...]:
    _require_aware(now, "now")
    if not 1 <= batch_size <= 1000 or not 1 <= ttl_seconds <= 3600:
        raise ValueError("claim bounds are invalid")
    providers = _normalize_scope(enabled_providers, "enabled_providers")
    regions = _normalize_scope(enabled_regions, "enabled_regions")
    data_kinds = _normalize_data_kinds(enabled_data_kinds)
    claims: list[RaceDataSyncClaim] = []
    with transaction.atomic():
        events = list(
            models.RaceEvent.objects.select_for_update(
                skip_locked=True,
                of=("self",),
            )
            .filter(
                live_tracking__tracking_enabled=True,
                live_tracking__next_poll_at__lte=now,
                projection_control__write_owner=models.RaceEventProjectionWriteOwner.DATA_SYNC,
                race_data_sync_enrollment__state=models.RaceDataSyncEnrollmentState.ENROLLED,
                race_data_sync_enrollment__source_identity__source_key__in=providers,
                race_data_sync_enrollment__source_identity__region_code__in=regions,
            )
            .filter(
                Q(live_tracking__active_attempt_token="")
                | Q(live_tracking__claim_expires_at__lte=now)
            )
            .order_by("live_tracking__next_poll_at", "id")[:batch_size]
        )
        for event in events:
            control = (
                models.RaceEventProjectionControl.objects.select_for_update()
                .filter(event=event)
                .first()
            )
            tracking = (
                models.RaceEventLiveTracking.objects.select_for_update()
                .filter(event=event)
                .first()
            )
            enrollment = (
                models.RaceDataSyncEnrollment.objects.select_for_update()
                .filter(event=event)
                .first()
            )
            if control is None or tracking is None or enrollment is None:
                continue
            if (
                not tracking.tracking_enabled
                or tracking.next_poll_at is None
                or tracking.next_poll_at > now
                or (
                    tracking.active_attempt_token
                    and (
                        tracking.claim_expires_at is None
                        or tracking.claim_expires_at > now
                    )
                )
            ):
                continue
            source_hint = (
                models.RaceResultSourceIdentity.objects.filter(
                    pk=enrollment.source_identity_id,
                    event=event,
                )
                .values("source_key", "region_code")
                .first()
            )
            if source_hint is None:
                continue
            checkpoint_rows = tuple(
                models.RaceEventLiveProviderCheckpoint.objects.select_for_update()
                .filter(
                    tracking=tracking,
                    source_key=source_hint["source_key"],
                    data_kind__in=data_kinds,
                    next_poll_at__lte=now,
                )
                .order_by("source_key", "data_kind")
            )
            source = (
                models.RaceResultSourceIdentity.objects.select_for_update()
                .filter(pk=enrollment.source_identity_id, event=event)
                .first()
            )
            if (
                source is None
                or source.source_key != source_hint["source_key"]
                or source.region_code != source_hint["region_code"]
                or source.source_key not in providers
                or source.region_code not in regions
            ):
                continue
            source_reason, route_binding = resolve_source_route_admission(
                source=source,
                route_digest=enrollment.route_digest,
                data_kinds=(row.data_kind for row in checkpoint_rows),
                now=now,
            )
            if (
                control.write_owner
                != models.RaceEventProjectionWriteOwner.DATA_SYNC
                or enrollment.projection_owner_generation
                != control.owner_generation
                or enrollment.enrollment_generation != control.owner_generation
                or source_reason
                or route_binding is None
            ):
                continue
            if not checkpoint_rows or any(
                row.registry_digest != route_binding.registry_digest
                or row.contract_digest != route_binding.contract_digest
                for row in checkpoint_rows
            ):
                continue
            token = secrets.token_hex(16)
            tracking.claim_generation += 1
            tracking.active_attempt_token = token
            tracking.claim_expires_at = now + timedelta(seconds=ttl_seconds)
            tracking.last_attempt_at = now
            tracking.save(
                update_fields=(
                    "claim_generation",
                    "active_attempt_token",
                    "claim_expires_at",
                    "last_attempt_at",
                    "updated_at",
                )
            )
            checkpoint_plan = tuple(
                {
                    "source_key": row.source_key,
                    "data_kind": row.data_kind,
                    "lock_version": row.lock_version,
                }
                for row in checkpoint_rows
            )
            plan_sha256 = _claim_plan_sha256(
                event_id=tracking.event_id,
                enrollment_generation=enrollment.enrollment_generation,
                owner_generation=control.owner_generation,
                claim_generation=tracking.claim_generation,
                attempt_token=token,
                enrollment_entry_sha256=enrollment.entry_sha256,
                route_digest=enrollment.route_digest,
                checkpoint_plan=checkpoint_plan,
            )
            claims.append(
                RaceDataSyncClaim(
                    event_id=tracking.event_id,
                    enrollment_generation=enrollment.enrollment_generation,
                    owner_generation=control.owner_generation,
                    claim_generation=tracking.claim_generation,
                    attempt_token=token,
                    enrollment_entry_sha256=enrollment.entry_sha256,
                    route_digest=enrollment.route_digest,
                    checkpoint_plan=checkpoint_plan,
                    plan_sha256=plan_sha256,
                )
            )
    return tuple(claims)


def fail_race_data_sync_claim(
    *,
    event_id: int,
    expected_enrollment_generation: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    data_kinds: Iterable[str],
    reason_code: str,
    retry_at: datetime,
    now: datetime,
    checkpoint_plan: Iterable[dict[str, str | int]] | None = None,
    expected_enrollment_entry_sha256: str = "",
    expected_plan_sha256: str = "",
) -> ControlDecision:
    """Release one exact parent claim after a provider-side failure.

    A late task cannot clear or reschedule a newer attempt.  Provider
    checkpoints remain the source of the parent's minimum due time.
    """

    _require_aware(now, "now")
    _require_aware(retry_at, "retry_at")
    if retry_at < now:
        raise ValueError("retry_at must not be earlier than now")
    if not isinstance(attempt_token, str) or _TOKEN_RE.fullmatch(attempt_token) is None:
        raise ValueError("attempt_token is invalid")
    if not isinstance(reason_code, str) or re.fullmatch(r"[a-z0-9_-]{1,64}", reason_code) is None:
        raise ValueError("reason_code is invalid")
    kinds = _normalize_data_kinds(data_kinds)
    frozen_plan = tuple(checkpoint_plan or ())
    if frozen_plan:
        _require_sha(expected_enrollment_entry_sha256, "expected_enrollment_entry_sha256")
        _require_sha(expected_plan_sha256, "expected_plan_sha256")

    with transaction.atomic():
        event = (
            models.RaceEvent.objects.select_for_update(of=("self",))
            .filter(pk=event_id)
            .first()
        )
        if event is None:
            return ControlDecision("rejected", "claim_subject_missing", event_id)
        control = (
            models.RaceEventProjectionControl.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        tracking = (
            models.RaceEventLiveTracking.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        enrollment = (
            models.RaceDataSyncEnrollment.objects.select_for_update()
            .filter(event=event)
            .first()
        )
        if tracking is None or control is None or enrollment is None:
            return ControlDecision("rejected", "claim_subject_missing", event_id)
        if (
            control.write_owner != models.RaceEventProjectionWriteOwner.DATA_SYNC
            or control.owner_generation != expected_owner_generation
            or enrollment.state != models.RaceDataSyncEnrollmentState.ENROLLED
            or enrollment.enrollment_generation != expected_enrollment_generation
            or tracking.claim_generation != expected_claim_generation
            or tracking.active_attempt_token != attempt_token
        ):
            return ControlDecision(
                "rejected",
                "claim_cas_stale",
                event_id,
                tracking.claim_generation,
            )
        if frozen_plan:
            computed_plan_sha256 = _claim_plan_sha256(
                event_id=event_id,
                enrollment_generation=expected_enrollment_generation,
                owner_generation=expected_owner_generation,
                claim_generation=expected_claim_generation,
                attempt_token=attempt_token,
                enrollment_entry_sha256=expected_enrollment_entry_sha256,
                route_digest=enrollment.route_digest,
                checkpoint_plan=frozen_plan,
            )
            if (
                enrollment.entry_sha256 != expected_enrollment_entry_sha256
                or computed_plan_sha256 != expected_plan_sha256
            ):
                return ControlDecision(
                    "rejected",
                    "claim_plan_drift",
                    event_id,
                    tracking.claim_generation,
                )

        checkpoint_query = (
            models.RaceEventLiveProviderCheckpoint.objects.select_for_update()
            .filter(tracking=tracking, data_kind__in=kinds)
        )
        if frozen_plan:
            planned_source_keys = {
                row.get("source_key") for row in frozen_plan if isinstance(row, dict)
            }
            if (
                not planned_source_keys
                or any(
                    not isinstance(source_key, str)
                    or _TOKEN_RE.fullmatch(source_key) is None
                    for source_key in planned_source_keys
                )
            ):
                return ControlDecision(
                    "rejected",
                    "claim_plan_drift",
                    event_id,
                    tracking.claim_generation,
                )
            checkpoint_query = checkpoint_query.filter(
                source_key__in=planned_source_keys
            )
        checkpoints = list(checkpoint_query.order_by("source_key", "data_kind"))
        if not checkpoints:
            return ControlDecision(
                "rejected",
                "checkpoint_missing",
                event_id,
                tracking.claim_generation,
            )
        if frozen_plan:
            current_plan = tuple(
                {
                    "source_key": checkpoint.source_key,
                    "data_kind": checkpoint.data_kind,
                    "lock_version": checkpoint.lock_version,
                }
                for checkpoint in checkpoints
            )
            if current_plan != frozen_plan:
                return ControlDecision(
                    "rejected",
                    "checkpoint_cas_stale",
                    event_id,
                    tracking.claim_generation,
                )
        for checkpoint in checkpoints:
            checkpoint.last_attempt_at = now
            checkpoint.consecutive_failures += 1
            checkpoint.circuit_reason = reason_code
            checkpoint.next_poll_at = retry_at
            checkpoint.lock_version += 1
            checkpoint.save(
                update_fields=(
                    "last_attempt_at",
                    "consecutive_failures",
                    "circuit_reason",
                    "next_poll_at",
                    "lock_version",
                    "updated_at",
                )
            )

        parent_due = (
            models.RaceEventLiveProviderCheckpoint.objects.filter(tracking=tracking)
            .aggregate(next_poll_at=Min("next_poll_at"))["next_poll_at"]
        )
        tracking.active_attempt_token = ""
        tracking.claim_expires_at = None
        tracking.next_poll_at = parent_due
        tracking.consecutive_failures += 1
        tracking.circuit_reason = reason_code
        tracking.lock_version += 1
        tracking.save(
            update_fields=(
                "active_attempt_token",
                "claim_expires_at",
                "next_poll_at",
                "consecutive_failures",
                "circuit_reason",
                "lock_version",
                "updated_at",
            )
        )
        return ControlDecision(
            "failed", reason_code, event_id, tracking.claim_generation
        )


def build_snapshot_cache_key(
    *,
    provider: str,
    region: str,
    scope_key: str,
    data_kind: str,
    registry_digest: str,
) -> str:
    for value, label in ((provider, "provider"), (region, "region")):
        if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
            raise ValueError(f"{label} is invalid")
    if (
        not isinstance(scope_key, str)
        or not scope_key
        or scope_key != scope_key.strip()
        or len(scope_key) > 128
        or any(ord(char) < 32 for char in scope_key)
    ):
        raise ValueError("scope_key is invalid")
    if data_kind not in models.RaceDataSyncDataKind.values:
        raise ValueError("data_kind is invalid")
    _require_sha(registry_digest, "registry_digest")
    encoded = json.dumps(
        {
            "schema_version": 1,
            "provider": provider,
            "region": region,
            "scope_key": scope_key,
            "data_kind": data_kind,
            "registry_digest": registry_digest,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"race-data-snapshot-v1:{hashlib.sha256(encoded).hexdigest()}"


def _snapshot_manifest_valid(
    *,
    manifest: object,
    cache_key: str,
    artifact_sha256: str,
    registry_digest: str,
) -> bool:
    return bool(
        isinstance(manifest, dict)
        and set(manifest)
        == {
            "schema_version",
            "complete",
            "cache_key",
            "artifact_sha256",
            "registry_digest",
            "page_count",
            "item_count",
        }
        and manifest.get("schema_version") == 1
        and manifest.get("complete") is True
        and manifest.get("cache_key") == cache_key
        and manifest.get("artifact_sha256") == artifact_sha256
        and manifest.get("registry_digest") == registry_digest
        and type(manifest.get("page_count")) is int
        and manifest["page_count"] >= 1
        and type(manifest.get("item_count")) is int
        and manifest["item_count"] >= 0
    )


def claim_snapshot_lease(
    *,
    provider: str,
    region: str,
    scope_key: str,
    data_kind: str,
    registry_digest: str,
    owner_token: str,
    now: datetime,
    ttl_seconds: int,
) -> ControlDecision:
    _require_aware(now, "now")
    cache_key = build_snapshot_cache_key(
        provider=provider,
        region=region,
        scope_key=scope_key,
        data_kind=data_kind,
        registry_digest=registry_digest,
    )
    if not isinstance(owner_token, str) or _TOKEN_RE.fullmatch(owner_token) is None:
        raise ValueError("owner_token is invalid")
    if not 1 <= ttl_seconds <= 3600:
        raise ValueError("ttl_seconds is invalid")
    with transaction.atomic():
        try:
            lease, created = models.RaceDataSnapshotLease.objects.get_or_create(
                cache_key=cache_key,
                defaults={
                    "state": models.RaceDataSnapshotLeaseState.CLAIMED,
                    "owner_token": owner_token,
                    "lease_generation": 1,
                    "lease_expires_at": now + timedelta(seconds=ttl_seconds),
                },
            )
        except IntegrityError:
            lease = models.RaceDataSnapshotLease.objects.get(cache_key=cache_key)
            created = False
        lease = models.RaceDataSnapshotLease.objects.select_for_update().get(pk=lease.pk)
        if created:
            return ControlDecision("acquired", generation=1)
        if (
            lease.state == models.RaceDataSnapshotLeaseState.COMPLETE
            and lease.lease_expires_at is not None
            and lease.lease_expires_at > now
            and _SHA256_RE.fullmatch(lease.artifact_sha256 or "") is not None
            and _snapshot_manifest_valid(
                manifest=lease.manifest_data,
                cache_key=cache_key,
                artifact_sha256=lease.artifact_sha256,
                registry_digest=registry_digest,
            )
        ):
            return ControlDecision("complete", generation=lease.lease_generation)
        if (
            lease.state == models.RaceDataSnapshotLeaseState.CLAIMED
            and lease.lease_expires_at is not None
            and lease.lease_expires_at > now
        ):
            if lease.owner_token == owner_token:
                return ControlDecision("replay", generation=lease.lease_generation)
            return ControlDecision("busy", "lease_active", generation=lease.lease_generation)
        if lease.retry_after is not None and lease.retry_after > now:
            return ControlDecision("busy", "retry_after", generation=lease.lease_generation)
        lease.state = models.RaceDataSnapshotLeaseState.CLAIMED
        lease.owner_token = owner_token
        lease.lease_generation += 1
        lease.lease_expires_at = now + timedelta(seconds=ttl_seconds)
        lease.artifact_sha256 = ""
        lease.manifest_data = {}
        lease.retry_after = None
        lease.error_code = ""
        lease.save(
            update_fields=(
                "state",
                "owner_token",
                "lease_generation",
                "lease_expires_at",
                "artifact_sha256",
                "manifest_data",
                "retry_after",
                "error_code",
                "updated_at",
            )
        )
        return ControlDecision("taken_over", generation=lease.lease_generation)


def publish_snapshot(
    *,
    provider: str,
    region: str,
    scope_key: str,
    data_kind: str,
    registry_digest: str,
    owner_token: str,
    expected_generation: int,
    artifact_sha256: str,
    manifest: dict,
    now: datetime,
) -> ControlDecision:
    _require_aware(now, "now")
    _require_sha(artifact_sha256, "artifact_sha256")
    cache_key = build_snapshot_cache_key(
        provider=provider,
        region=region,
        scope_key=scope_key,
        data_kind=data_kind,
        registry_digest=registry_digest,
    )
    if not _snapshot_manifest_valid(
        manifest=manifest,
        cache_key=cache_key,
        artifact_sha256=artifact_sha256,
        registry_digest=registry_digest,
    ):
        raise ValueError("manifest must be complete and canonical")
    with transaction.atomic():
        lease = (
            models.RaceDataSnapshotLease.objects.select_for_update()
            .filter(cache_key=cache_key)
            .first()
        )
        if lease is None:
            return ControlDecision("rejected", "lease_missing")
        if (
            lease.state != models.RaceDataSnapshotLeaseState.CLAIMED
            or lease.owner_token != owner_token
            or lease.lease_generation != expected_generation
            or lease.lease_expires_at is None
            or lease.lease_expires_at <= now
        ):
            return ControlDecision(
                "rejected", "lease_cas_stale", generation=lease.lease_generation
            )
        lease.state = models.RaceDataSnapshotLeaseState.COMPLETE
        lease.owner_token = ""
        lease.artifact_sha256 = artifact_sha256
        lease.manifest_data = manifest
        lease.lease_expires_at = now + timedelta(
            seconds=_SNAPSHOT_COMPLETE_TTL_SECONDS
        )
        lease.retry_after = None
        lease.error_code = ""
        lease.save()
        return ControlDecision("published", generation=lease.lease_generation)


def fail_snapshot_lease(
    *,
    provider: str,
    region: str,
    scope_key: str,
    data_kind: str,
    registry_digest: str,
    owner_token: str,
    expected_generation: int,
    error_code: str,
    retry_after: datetime,
    now: datetime,
) -> ControlDecision:
    _require_aware(now, "now")
    _require_aware(retry_after, "retry_after")
    if retry_after <= now:
        raise ValueError("retry_after must be later than now")
    if not isinstance(error_code, str) or re.fullmatch(
        r"[a-z0-9_-]{1,64}", error_code
    ) is None:
        raise ValueError("error_code is invalid")
    cache_key = build_snapshot_cache_key(
        provider=provider,
        region=region,
        scope_key=scope_key,
        data_kind=data_kind,
        registry_digest=registry_digest,
    )
    with transaction.atomic():
        lease = (
            models.RaceDataSnapshotLease.objects.select_for_update()
            .filter(cache_key=cache_key)
            .first()
        )
        if lease is None:
            return ControlDecision("rejected", "lease_missing")
        if (
            lease.state != models.RaceDataSnapshotLeaseState.CLAIMED
            or lease.owner_token != owner_token
            or lease.lease_generation != expected_generation
            or lease.lease_expires_at is None
            or lease.lease_expires_at <= now
        ):
            return ControlDecision(
                "rejected", "lease_cas_stale", generation=lease.lease_generation
            )
        lease.state = models.RaceDataSnapshotLeaseState.FAILED
        lease.owner_token = ""
        lease.lease_expires_at = None
        lease.artifact_sha256 = ""
        lease.manifest_data = {}
        lease.retry_after = retry_after
        lease.error_code = error_code
        lease.save()
        return ControlDecision(
            "failed", error_code, generation=lease.lease_generation
        )


def reserve_race_data_host_request(
    *, host: str, minimum_interval_seconds: int, now: datetime
):
    """Reserve the shared race-live host budget under the stricter route floor."""

    from stable.services.race_events import RaceLiveHostReservationDecision

    if (
        not isinstance(host, str)
        or not host
        or host != host.strip()
        or len(host) > 255
    ):
        return RaceLiveHostReservationDecision(False, "invalid_host")
    if (
        isinstance(minimum_interval_seconds, bool)
        or not isinstance(minimum_interval_seconds, int)
        or not 1 <= minimum_interval_seconds <= 3_600
    ):
        return RaceLiveHostReservationDecision(False, "invalid_minimum_interval")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return RaceLiveHostReservationDecision(False, "invalid_now")

    with transaction.atomic():
        budget = (
            models.RaceLiveHostBudget.objects.select_for_update()
            .filter(host=host)
            .first()
        )
        if budget is None:
            return RaceLiveHostReservationDecision(False, "budget_missing")
        required_ms = minimum_interval_seconds * 1_000
        if budget.min_interval_ms < required_ms:
            return RaceLiveHostReservationDecision(False, "budget_interval_too_low")
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
        budget.save(update_fields=("next_allowed_at", "lock_version", "updated_at"))
        return RaceLiveHostReservationDecision(
            True,
            "reserved",
            next_allowed_at=budget.next_allowed_at,
            reservation_version=budget.lock_version,
        )

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
    if models.RaceDataSyncEnrollment.objects.filter(
        event_id=event.pk, authority_version=2
    ).exists():
        return "multisource_claim_required"
    policy = parse_standing_policy(standing_policy)
    if not (policy.valid_from <= now < policy.valid_until):
        return "standing_policy_expired"
    with transaction.atomic():
        # Lock order is owned by rotate_enrollment's CAS below; reading the
        # enrollment unlocked here is safe because the rotation re-verifies
        # the expected owner manifest and generation before writing.
        enrollment = (
            models.RaceDataSyncEnrollment.objects.select_related("source_identity")
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
    if (
        admission.enrollment is not None
        and observation.source_identity_id != admission.enrollment.source_identity_id
    ):
        return StalledEventAssessment(
            event.pk, revision.pk, observation.pk, False, "not_granted_source"
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


def multisource_conversion_snapshot(event_id):
    """固定转换范围；公开历史、人工覆盖和活动claim均不自动转换。"""
    from stable.services.race_source_identity import event_snapshot

    enrollment = models.RaceDataSyncEnrollment.objects.select_related(
        "source_identity", "event"
    ).get(event_id=event_id)
    event = enrollment.event
    owner = models.RaceEventProjectionControl.objects.get(event=event)
    tracking = models.RaceEventLiveTracking.objects.get(event=event)
    lifecycle = models.RaceEventLifecycleControl.objects.get(event=event)
    if (
        event.visibility_status != "published"
        or event.result_confirmed_at
        or event.status in ("cancelled", "postponed")
        or event.revisions.filter(published_at__isnull=False).exists()
        or event.results.exists()
        or any((event.manual_lock_flags or {}).values())
        or lifecycle.manual_pause_reason
    ):
        raise ValueError("conversion_event_ineligible")
    if (
        owner.write_owner != "data_sync"
        or enrollment.state != "enrolled"
        or owner.owner_generation != enrollment.projection_owner_generation
        or owner.owner_manifest_sha256 != enrollment.manifest_sha256
    ):
        raise ValueError("conversion_owner_mismatch")
    if tracking.active_attempt_token:
        raise ValueError("conversion_active_claim")
    source = enrollment.source_identity
    return dict(
        event_id=event_id,
        event_snapshot=event_snapshot(event),
        authority_version=enrollment.authority_version,
        owner_generation=owner.owner_generation,
        enrollment_generation=enrollment.enrollment_generation,
        manifest_sha256=enrollment.manifest_sha256,
        entry_sha256=enrollment.entry_sha256,
        standing_policy_digest=enrollment.standing_policy_digest,
        source_set_digest=enrollment.source_set_digest,
        lifecycle_version=lifecycle.schedule_generation,
        tracking_version=tracking.lock_version,
        source_id=source.pk,
        source_fields={
            k: str(getattr(source, k))
            for k in (
                "source_key",
                "region_code",
                "identity_namespace",
                "external_race_id",
                "canonical_url",
                "registry_digest",
                "review_status",
                "terms_status",
                "automation_allowed",
                "proof_network_allowed",
                "valid_until",
            )
        },
    )


def multisource_runtime_code_sha():
    """镜像构建时固化的SHA优先；本地回退当前checkout，不能只信CLI自报值。"""
    from pathlib import Path
    import subprocess
    import re

    value = getattr(settings, "UMANEWS_RELEASE_COMMIT", "")
    if not re.fullmatch("[0-9a-f]{40}", value or ""):
        try:
            value = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(settings.BASE_DIR).parent,
                timeout=5,
                text=True,
            ).strip()
        except (OSError, subprocess.SubprocessError):
            raise ValueError("conversion_runtime_sha_unavailable") from None
    if not re.fullmatch("[0-9a-f]{40}", value):
        raise ValueError("conversion_runtime_sha_invalid")
    return value


def prepare_multisource_conversion(*, observations, policy, now, code_sha):
    from stable.services.race_data_source_adapters import canonical_sha
    from stable.services.race_source_identity import resolve_observation
    import re

    if (
        not re.fullmatch("[0-9a-f]{40}", code_sha)
        or code_sha != multisource_runtime_code_sha()
    ):
        raise ValueError("conversion_code_sha_invalid")
    if not isinstance(observations, list) or not 1 <= len(observations) <= 20:
        raise ValueError("conversion_scope_invalid")
    entries = []
    seen = set()
    for value in observations:
        route = policy.route_for(value)
        if route is None:
            raise ValueError("conversion_route_missing")
        match = resolve_observation(value, route=route, now=now)
        if match.status != "exact" or match.event_id in seen:
            raise ValueError("conversion_identity_ambiguous")
        seen.add(match.event_id)
        snapshot = multisource_conversion_snapshot(match.event_id)
        if snapshot["authority_version"] != 1:
            raise ValueError("conversion_not_legacy")
        source = models.RaceResultSourceIdentity.objects.get(pk=snapshot["source_id"])
        if any(
            str(getattr(source, field)) != str(value[key])
            for field, key in (
                ("source_key", "provider"),
                ("region_code", "region"),
                ("identity_namespace", "identity_namespace"),
                ("external_race_id", "external_race_id"),
            )
        ):
            raise ValueError("conversion_source_mismatch")
        entries.append(
            dict(event_id=match.event_id, before=snapshot, observation=value)
        )
    body = dict(
        schema_version=1,
        operation="convert_multisource",
        code_sha=code_sha,
        policy_digest=policy.digest,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=30)).isoformat(),
        entries=sorted(entries, key=lambda e: e["event_id"]),
    )
    return {**body, "manifest_sha256": canonical_sha(body)}


def apply_multisource_conversion(
    *, manifest, expected_sha256, policy, now, code_sha, apply=False
):
    """每event原子CAS；仅关闭态固定manifest，无网络/历史改写/owner重授予。"""
    from stable.services.race_data_source_adapters import canonical_sha, aware
    from stable.services.race_source_identity import (
        resolve_observation,
        identity_key,
        advisory_identity_locks,
    )
    from stable.services.race_data_sync_enrollment import (
        _lock_multisource_event,
        _multisource_manifest,
    )
    from stable.services.race_data_sync_admission import binding_admission_reason

    if code_sha != multisource_runtime_code_sha():
        raise ValueError("conversion_code_sha_invalid")
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if (
        set(body)
        != {
            "schema_version",
            "operation",
            "code_sha",
            "policy_digest",
            "created_at",
            "expires_at",
            "entries",
        }
        or body.get("schema_version") != 1
        or body.get("operation") != "convert_multisource"
        or canonical_sha(body) != expected_sha256
        or manifest.get("manifest_sha256") != expected_sha256
        or body.get("code_sha") != code_sha
        or body.get("policy_digest") != policy.digest
        or not aware(body["created_at"]) <= now < aware(body["expires_at"])
        or aware(body["expires_at"]) - aware(body["created_at"]) > timedelta(minutes=30)
        or not policy.valid(now)
    ):
        raise ValueError("conversion_manifest_invalid")
    ids = [e["event_id"] for e in body["entries"]]
    if not 1 <= len(ids) <= 20 or ids != sorted(set(ids)):
        raise ValueError("conversion_scope_invalid")
    if apply and any(
        getattr(settings, k, False)
        for k in (
            "RACE_DATA_SYNC_ENABLED",
            "RACE_DATA_SYNC_SCHEDULER_ENABLED",
            "RACE_DATA_SYNC_ALLOW_NETWORK",
            "RACE_DATA_MULTISOURCE_APPLY_ENABLED",
            "RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED",
        )
    ):
        raise ValueError("conversion_requires_closed_runtime")
    outcomes = []
    for entry in body["entries"]:
        with transaction.atomic():
            value = entry["observation"]
            route = policy.route_for(value)
            if route is None:
                raise ValueError("conversion_route_missing")
            advisory_identity_locks(value)
            event, lifecycle = _lock_multisource_event(entry["event_id"])
            owner = models.RaceEventProjectionControl.objects.select_for_update().get(
                event=event
            )
            tracking = models.RaceEventLiveTracking.objects.select_for_update().get(
                event=event
            )
            enrollment = models.RaceDataSyncEnrollment.objects.select_for_update().get(
                event=event
            )
            if enrollment.authority_version == 2:
                receipt = (lifecycle.manifest_data or {}).get(
                    "multisource_conversion", {}
                )
                if receipt.get("manifest_sha256") != expected_sha256:
                    raise ValueError("conversion_already_different")
                outcomes.append({"event_id": event.pk, "action": "replay"})
                continue
            if multisource_conversion_snapshot(event.pk) != entry["before"]:
                raise ValueError("conversion_snapshot_drift")
            match = resolve_observation(value, route=route, now=now)
            if match.status != "exact" or match.event_id != event.pk:
                raise ValueError("conversion_identity_drift")
            checkpoints = list(
                models.RaceEventLiveProviderCheckpoint.objects.select_for_update()
                .filter(tracking=tracking)
                .order_by("source_key", "data_kind")
            )
            source = models.RaceResultSourceIdentity.objects.select_for_update().get(
                pk=enrollment.source_identity_id
            )
            now = max(now, timezone.now())
            if (
                not aware(body["created_at"]) <= now < aware(body["expires_at"])
                or not policy.valid(now)
                or not route.valid(now)
            ):
                raise ValueError("conversion_manifest_expired")
            binding_manifest = dict(
                event_id=event.pk,
                source_identity_id=source.pk,
                source_registry_digest=source.registry_digest,
                route=route.payload,
                route_digest=route.digest,
                identity_evidence=match.evidence,
                identity_evidence_sha256=canonical_sha(match.evidence),
                policy_digest=policy.digest,
            )
            binding = models.RaceDataSyncSourceBinding(
                enrollment=enrollment,
                source_identity=source,
                capabilities=route.capabilities,
                route_digest=route.digest,
                contract_digest=route.contract_digest,
                proof_digest=route.proof_digest,
                identity_evidence_sha256=canonical_sha(match.evidence),
                binding_manifest=binding_manifest,
                binding_manifest_sha256=canonical_sha(binding_manifest),
                valid_until=aware(route.valid_until),
            )
            reason = binding_admission_reason(
                binding=binding, route=route, now=now, check_runtime=False
            )
            if reason:
                raise ValueError(reason)
            if apply and any(
                getattr(settings, k, False)
                for k in (
                    "RACE_DATA_SYNC_ENABLED",
                    "RACE_DATA_SYNC_SCHEDULER_ENABLED",
                    "RACE_DATA_SYNC_ALLOW_NETWORK",
                    "RACE_DATA_MULTISOURCE_APPLY_ENABLED",
                    "RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED",
                )
            ):
                raise ValueError("conversion_requires_closed_runtime")
            if not apply:
                outcomes.append({"event_id": event.pk, "action": "dry_run"})
                continue
            key = identity_key(value)
            if key:
                stored, created = models.RaceEventIdentityKey.objects.get_or_create(
                    namespace=key["namespace"],
                    key_sha256=key["key_sha256"],
                    defaults={
                        **key,
                        "event": event,
                        "evidence": match.evidence,
                        "matcher_version": "race-identity-v2",
                    },
                )
                if (
                    stored.event_id != event.pk
                    or stored.key_payload != key["key_payload"]
                ):
                    raise ValueError("conversion_identity_conflict")
            binding.save()
            enrollment.authority_version = 2
            enrollment.standing_policy_digest = policy.digest
            enrollment.route_digest = route.digest
            enrollment.save()
            for checkpoint in checkpoints:
                if checkpoint.source_key == source.source_key:
                    checkpoint.contract_digest = route.contract_digest
                    checkpoint.registry_digest = route.digest
                    checkpoint.next_poll_at = (
                        now if checkpoint.data_kind in route.capabilities else None
                    )
                    checkpoint.lock_version += 1
                    checkpoint.save()
            for kind in route.capabilities:
                models.RaceEventLiveProviderCheckpoint.objects.get_or_create(
                    tracking=tracking,
                    source_key=source.source_key,
                    data_kind=kind,
                    defaults={
                        "next_poll_at": now,
                        "registry_digest": route.digest,
                        "contract_digest": route.contract_digest,
                    },
                )
            lifecycle.manifest_data = {
                **lifecycle.manifest_data,
                "multisource_conversion": {
                    "manifest_sha256": expected_sha256,
                    "before": entry["before"],
                    "applied_at": now.isoformat(),
                },
            }
            lifecycle.save(update_fields=("manifest_data", "updated_at"))
            race_data_sync_control._establish_data_sync_lifecycle_evidence(
                lifecycle=lifecycle,
                event=event,
                standing_policy_digest=policy.digest,
                manifest_sha256=enrollment.manifest_sha256,
                entry_sha256=enrollment.entry_sha256,
                owner_generation=owner.owner_generation,
                now=now,
            )
            _multisource_manifest(enrollment, owner, policy, now, check_runtime=False)
            lifecycle.refresh_from_db()
            lifecycle.manifest_data["multisource_conversion"][
                "after_source_set_digest"
            ] = enrollment.source_set_digest
            lifecycle.save(update_fields=("manifest_data", "updated_at"))
            outcomes.append({"event_id": event.pk, "action": "converted"})
    return outcomes


def verify_multisource_conversion(*, manifest):
    """独立只读检查当前转换收据、唯一binding、旧source摘要及owner未重授予。"""
    from stable.services.race_data_source_adapters import canonical_sha

    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if canonical_sha(body) != manifest.get("manifest_sha256"):
        raise ValueError("conversion_manifest_invalid")
    results = []
    for row in manifest["entries"]:
        event = models.RaceEvent.objects.get(pk=row["event_id"])
        enrollment = models.RaceDataSyncEnrollment.objects.get(event=event)
        owner = models.RaceEventProjectionControl.objects.get(event=event)
        lifecycle = models.RaceEventLifecycleControl.objects.get(event=event)
        source = models.RaceResultSourceIdentity.objects.get(
            pk=row["before"]["source_id"]
        )
        bindings = list(
            enrollment.source_bindings.select_related("source_identity")
            .filter(state="active")
            .order_by("pk")
        )
        receipt = lifecycle.manifest_data.get("multisource_conversion", {})
        binding_rows = [
            dict(
                id=b.pk,
                source_identity_id=b.source_identity_id,
                manifest_sha256=b.binding_manifest_sha256,
            )
            for b in bindings
        ]
        keys = list(
            models.RaceEventIdentityKey.objects.filter(event=event)
            .order_by("namespace", "key_sha256")
            .values("namespace", "key_sha256", "key_payload")
        )
        checkpoints = list(
            models.RaceEventLiveProviderCheckpoint.objects.filter(
                tracking__event=event, source_key=source.source_key
            )
        )
        valid = (
            enrollment.source_set_manifest.get("identity_keys_sha256")
            == canonical_sha(keys)
            and lifecycle.manifest_data.get("race_data_sync_v2")
            == {
                "source_set_digest": enrollment.source_set_digest,
                "source_set_generation": enrollment.source_set_generation,
            }
            and all(
                any(
                    c.data_kind == kind
                    and c.contract_digest == b.contract_digest
                    and c.registry_digest == b.route_digest
                    for c in checkpoints
                )
                for b in bindings
                for kind in b.capabilities
            )
            and receipt.get("after_source_set_digest") == enrollment.source_set_digest
            and enrollment.source_set_manifest.get("bindings") == binding_rows
            and all(
                canonical_sha(b.binding_manifest) == b.binding_manifest_sha256
                and canonical_sha(b.binding_manifest["route"]) == b.route_digest
                and b.capabilities == b.binding_manifest["route"]["capabilities"]
                and b.contract_digest == b.binding_manifest["route"]["contract_digest"]
                and b.proof_digest == b.binding_manifest["route"]["proof_digest"]
                for b in bindings
            )
            and enrollment.authority_version == 2
            and enrollment.source_bindings.filter(state="active").count() == 1
            and owner.owner_generation == row["before"]["owner_generation"]
            and source.registry_digest
            == row["before"]["source_fields"]["registry_digest"]
            and canonical_sha(enrollment.source_set_manifest)
            == enrollment.source_set_digest
            and lifecycle.manifest_data.get("multisource_conversion", {}).get(
                "manifest_sha256"
            )
            == manifest["manifest_sha256"]
        )
        results.append({"event_id": event.pk, "verified": valid})
    return results

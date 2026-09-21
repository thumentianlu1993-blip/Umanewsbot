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

    if models.RaceDataSyncEnrollment.objects.filter(
        event_id=event_id, authority_version=2
    ).exists():
        return validate_multisource_admission(event_id=event_id, now=now, lock=lock)
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


def validate_multisource_admission(
    *, event_id, now, capability=None, binding_id=None, policy=None, lock=False
):
    from stable.services.race_data_source_adapters import (
        load_multisource_policy,
        canonical_sha,
        aware,
    )

    if any(
        getattr(settings, flag, False) is not True
        for flag in (
            "RACE_DATA_MULTISOURCE_APPLY_ENABLED",
            "RACE_DATA_SYNC_ENABLED",
            "RACE_DATA_SYNC_SCHEDULER_ENABLED",
            "RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED",
        )
    ):
        return _deny("multisource_apply_disabled")
    try:
        policy = policy or load_multisource_policy(now=now)
    except (OSError, ValueError, TypeError):
        return _deny("multisource_policy_unavailable")
    if not policy.valid(now):
        return _deny("multisource_policy_expired")
    if lock:
        from stable.services.race_data_sync_enrollment import _lock_multisource_event

        event, lifecycle = _lock_multisource_event(event_id)
    else:
        event = models.RaceEvent.objects.filter(pk=event_id).first()
        lifecycle = models.RaceEventLifecycleControl.objects.filter(
            event_id=event_id
        ).first()
    if event is None:
        return _deny("event_missing")
    if event.status in ("cancelled", "postponed"):
        return _deny("event_not_active")
    if event.visibility_status != "published" or any(
        (event.manual_lock_flags or {}).values()
    ):
        return _deny("manual_or_visibility_block")
    if (
        lifecycle is None
        or lifecycle.manual_pause_reason
        or lifecycle.mode != "enforce"
    ):
        return _deny("lifecycle_control_off")
    if models.RaceEventLifecycleEnforceMembership.objects.filter(
        event_id=event_id,
        state="active",
        registry__state="active",
        registry__is_active=True,
        registry__runtime_valid_until__gt=now,
    ).exists():
        return _deny("lifecycle_authority_conflict")
    projection = models.RaceEventProjectionControl.objects.filter(
        event_id=event_id
    ).first()
    enrollment = models.RaceDataSyncEnrollment.objects.filter(event_id=event_id).first()
    if (
        not enrollment
        or enrollment.authority_version != 2
        or enrollment.state != "enrolled"
    ):
        return _deny("enrollment_missing")
    if (
        not projection
        or projection.write_owner != "data_sync"
        or projection.owner_generation != enrollment.projection_owner_generation
        or projection.owner_manifest_sha256 != enrollment.manifest_sha256
    ):
        return _deny("writer_owner_conflict")
    manifest = enrollment.source_set_manifest
    if (
        not isinstance(manifest, dict)
        or canonical_sha(manifest) != enrollment.source_set_digest
        or manifest.get("policy_digest") != policy.digest
        or enrollment.standing_policy_digest != policy.digest
        or manifest.get("event_id") != event_id
        or manifest.get("source_set_generation") != enrollment.source_set_generation
        or manifest.get("owner_generation") != projection.owner_generation
        or manifest.get("enrollment_generation") != enrollment.enrollment_generation
    ):
        return _deny("source_set_drift")
    expected = {
        "source_set_digest": enrollment.source_set_digest,
        "source_set_generation": enrollment.source_set_generation,
    }
    if lifecycle.manifest_data.get("race_data_sync_v2") != expected:
        return _deny("lifecycle_evidence_drift")
    keys = list(
        models.RaceEventIdentityKey.objects.filter(event_id=event_id)
        .order_by("namespace", "key_sha256")
        .values("namespace", "key_sha256", "key_payload")
    )
    if canonical_sha(keys) != manifest.get("identity_keys_sha256"):
        return _deny("identity_keys_drift")
    if capability:
        selected = manifest.get("selected", {}).get(capability)
        alternate = manifest.get("alternate", {}).get(capability)
        if binding_id is None:
            binding_id = selected
        if binding_id != selected:
            if (
                not isinstance(alternate, dict)
                or alternate.get("binding_id") != binding_id
                or aware(alternate.get("expires_at")) <= now
            ):
                return _deny("binding_not_selected")
    bindings = list(
        enrollment.source_bindings.select_related("source_identity")
        .filter(state="active")
        .order_by("pk")
    )
    if manifest.get("bindings") != [
        dict(
            id=b.pk,
            source_identity_id=b.source_identity_id,
            manifest_sha256=b.binding_manifest_sha256,
        )
        for b in bindings
    ]:
        return _deny("binding_set_drift")
    valid = []
    for binding in bindings:
        if binding_id is not None and binding.pk != binding_id:
            continue
        source = binding.source_identity
        route = policy.route_for(
            dict(
                provider=source.source_key,
                region=source.region_code,
                identity_namespace=source.identity_namespace,
            )
        )
        reason = binding_admission_reason(
            binding=binding, route=route, now=now, capability=capability
        )
        if reason:
            if binding_id == binding.pk:
                return _deny(reason)
            continue
        valid.append((binding, source, route))
    if not valid:
        return _deny("no_valid_binding")
    binding, source, route = valid[0]
    decision = LifecycleAdmissionDecision(
        True,
        "",
        authority="data_sync",
        event=event,
        control=lifecycle,
        enrollment=enrollment,
        source=source,
        route=route,
    )
    return decision


def validate_multisource_publication(
    *, event, control, revision, publication, observation, source, enrollment
):
    """只读发布时授权；当前网络/写开关和来源到期不撤销既有正式版本。"""
    from stable.services.race_data_source_adapters import canonical_sha, aware

    if not getattr(settings, "RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED", False):
        return "public_disabled"
    if (
        any((event.manual_lock_flags or {}).values())
        or event.visibility_status != "published"
    ):
        return "public_manual_lock"
    if (
        source.review_status != "approved"
        or source.terms_status != "approved"
        or not source.automation_allowed
        or source.identity_fields.get("identity_invalidated")
        or source.identity_fields.get("publication_revoked")
    ):
        return "identity_revoked"
    if models.RaceDataSyncSourceBinding.objects.filter(
        enrollment=enrollment, source_identity=source, state="retired"
    ).exists():
        return "binding_revoked"
    if (
        enrollment is None
        or enrollment.authority_version != 2
        or control.write_owner != "data_sync"
    ):
        return "enrollment_missing"
    snapshot = observation.field_provenance.get("multisource_authority", {})
    binding = snapshot.get("binding_manifest")
    manifest = snapshot.get("source_set_manifest")
    if not isinstance(binding, dict) or not isinstance(manifest, dict):
        return "publication_authority_missing"
    if canonical_sha(binding) != snapshot.get(
        "binding_manifest_sha256"
    ) or canonical_sha(manifest) != snapshot.get("source_set_digest"):
        return "publication_authority_drift"
    route = binding.get("route", {})
    selected = manifest.get("selected", {}).get("result")
    authorized = next(
        (
            b
            for b in manifest.get("bindings", [])
            if b.get("source_identity_id") == source.pk
            and b.get("manifest_sha256") == snapshot["binding_manifest_sha256"]
        ),
        None,
    )
    alternate = manifest.get("alternate", {}).get("result", {})
    try:
        valid = (
            aware(route["valid_from"])
            <= publication.published_at
            < aware(route["valid_until"])
        )
        selected_ok = authorized and (
            authorized["id"] == selected
            or (
                authorized["id"] == alternate.get("binding_id")
                and publication.published_at < aware(alternate["expires_at"])
            )
        )
    except (KeyError, ValueError, TypeError):
        return "publication_authority_invalid"
    if (
        not valid
        or not selected_ok
        or binding.get("event_id") != event.pk
        or manifest.get("event_id") != event.pk
        or binding.get("source_identity_id") != source.pk
        or route.get("provider") != source.source_key
        or "result" not in route.get("capabilities", [])
        or canonical_sha(route) != binding.get("route_digest")
        or observation.field_provenance.get("registry_digest")
        != binding.get("route_digest")
        or publication.registry_digest != binding.get("route_digest")
        or publication.allowlist_version != 2
        or publication.reason != "data_sync_result"
        or publication.authorization_kind != "official_route"
        or publication.coverage_proof_digest != observation.normalized_sha256
        or revision.primary_observation_id != observation.pk
        or revision.event_id != event.pk
        or publication.policy_versions
        != [["race_data_sync_contract", route.get("parser_version"), 1]]
    ):
        return "publication_audit_mismatch"
    return ""


def binding_admission_reason(
    *, binding, route, now, capability=None, check_runtime=True
):
    """选源、重算及末端写入共享基础合同；这里不要求该 binding 已被选中。"""
    from stable.services.race_data_source_adapters import canonical_sha

    source = binding.source_identity
    event_id = binding.enrollment.event_id
    if (
        route is None
        or not route.valid(now)
        or binding.state != "active"
        or binding.valid_until <= now
        or binding.route_digest != route.digest
        or binding.contract_digest != route.contract_digest
        or binding.proof_digest != route.proof_digest
        or canonical_sha(binding.binding_manifest) != binding.binding_manifest_sha256
        or binding.binding_manifest.get("route") != route.payload
        or binding.binding_manifest.get("source_identity_id") != source.pk
        or binding.binding_manifest.get("event_id") != event_id
        or binding.binding_manifest.get("identity_evidence_sha256")
        != binding.identity_evidence_sha256
        or canonical_sha(binding.binding_manifest.get("identity_evidence"))
        != binding.identity_evidence_sha256
        or source.event_id != event_id
        or source.review_status != "approved"
        or source.terms_status != "approved"
        or not source.automation_allowed
        or not source.proof_network_allowed
        or source.identity_fields.get("identity_invalidated")
        or source.identity_fields.get("publication_revoked")
        or source.valid_until is None
        or source.valid_until <= now
        or not route.permits_url(source.canonical_url)
        or source.registry_digest
        != binding.binding_manifest.get("source_registry_digest", route.digest)
        or sorted(binding.capabilities) != route.capabilities
        or (capability and capability not in binding.capabilities)
    ):
        return "binding_contract_drift"
    if check_runtime and (
        source.source_key
        not in getattr(settings, "RACE_DATA_SYNC_ENABLED_PROVIDERS", ())
        or source.region_code
        not in getattr(settings, "RACE_DATA_SYNC_ENABLED_REGIONS", ())
        or (
            capability
            and capability
            not in getattr(settings, "RACE_DATA_SYNC_ENABLED_DATA_KINDS", ())
        )
    ):
        return "binding_runtime_disabled"
    evidence = source.identity_fields.get("multisource_v2")
    if evidence:
        from stable.services.race_source_identity import _event_context

        if not _event_context(source.event, evidence, route):
            return "identity_context_mismatch"
    return ""

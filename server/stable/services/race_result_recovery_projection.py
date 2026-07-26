"""Transactional projection primitives for an approved race-result recovery.

This module deliberately reuses the race-live observation/revision models.  It
does not grant network access or publication authority; callers must pass a
validated, official receipt and independently approved manifest digests.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from stable import models


class CanonicalIdentityApprovalError(ValueError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


class RecoveryApplyBlocked(RuntimeError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


class RecoveryLedgerError(RuntimeError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _require_digest(value: str, reason_code: str) -> None:
    if len(value or "") != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise CanonicalIdentityApprovalError(reason_code)


def _advisory_lock_event_ids(event_ids) -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        for event_id in sorted(set(event_ids)):
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                [0x52414345, int(event_id)],
            )


@transaction.atomic
def approve_canonical_link(
    *,
    duplicate_event_id: int,
    canonical_event_id: int,
    identity_sha256: str,
    manifest_sha256: str,
    approved_by_id: int,
    approved_at,
):
    _require_digest(identity_sha256, "identity_digest_invalid")
    _require_digest(manifest_sha256, "manifest_digest_invalid")
    if duplicate_event_id == canonical_event_id:
        raise CanonicalIdentityApprovalError("canonical_self_link")
    _advisory_lock_event_ids((duplicate_event_id, canonical_event_id))
    events = {
        event.pk: event
        for event in models.RaceEvent.objects.select_for_update().filter(
            pk__in=(duplicate_event_id, canonical_event_id)
        )
    }
    if len(events) != 2:
        raise CanonicalIdentityApprovalError("canonical_event_missing")
    duplicate = events[duplicate_event_id]
    canonical = events[canonical_event_id]
    if duplicate.country_region != canonical.country_region:
        raise CanonicalIdentityApprovalError("canonical_region_mismatch")
    if duplicate.year != canonical.year:
        raise CanonicalIdentityApprovalError("canonical_year_mismatch")

    active = list(
        models.RaceEventProductCanonicalLink.objects.select_for_update()
        .filter(is_active=True)
        .filter(
            Q(duplicate_event_id__in=(duplicate_event_id, canonical_event_id))
            | Q(canonical_event_id__in=(duplicate_event_id, canonical_event_id))
        )
    )
    existing = next(
        (
            link
            for link in active
            if link.duplicate_event_id == duplicate_event_id
        ),
        None,
    )
    if existing is not None and (
        existing.canonical_event_id == canonical_event_id
        and existing.identity_sha256 == identity_sha256
        and existing.manifest_sha256 == manifest_sha256
    ):
        return existing
    if existing is not None:
        raise CanonicalIdentityApprovalError("canonical_duplicate_already_active")
    # Product identity is intentionally one level deep.  Rejecting an endpoint
    # already used at either side prevents both chains and cycles.
    if active:
        if any(
            link.duplicate_event_id == canonical_event_id
            or link.canonical_event_id == duplicate_event_id
            for link in active
        ):
            raise CanonicalIdentityApprovalError("canonical_cycle_forbidden")
        raise CanonicalIdentityApprovalError("canonical_chain_forbidden")

    return models.RaceEventProductCanonicalLink.objects.create(
        duplicate_event=duplicate,
        canonical_event=canonical,
        identity_sha256=identity_sha256,
        manifest_sha256=manifest_sha256,
        approved_by_id=approved_by_id,
        approved_at=approved_at,
        is_active=True,
    )


@transaction.atomic
def deactivate_canonical_link(
    *,
    link_id: int,
    expected_manifest_sha256: str,
    deactivated_by_id: int,
    deactivated_at,
):
    link = models.RaceEventProductCanonicalLink.objects.select_for_update().get(
        pk=link_id
    )
    _advisory_lock_event_ids(
        (link.duplicate_event_id, link.canonical_event_id)
    )
    if link.manifest_sha256 != expected_manifest_sha256:
        raise CanonicalIdentityApprovalError("canonical_manifest_drift")
    if not link.is_active:
        return link
    link.is_active = False
    link.deactivated_by_id = deactivated_by_id
    link.deactivated_at = deactivated_at
    link.save(
        update_fields=(
            "is_active",
            "deactivated_by",
            "deactivated_at",
            "updated_at",
        )
    )
    return link


def _operation_for(
    *, event_id: int, manifest_sha256: str, approval_sha256: str
):
    for operation in models.OperationLog.objects.filter(
        action_type="race_result_recovery_apply",
        target_id=str(event_id),
    ):
        try:
            detail = json.loads(operation.detail)
        except (TypeError, ValueError):
            continue
        if (
            detail.get("manifest_sha256") == manifest_sha256
            and detail.get("approval_sha256") == approval_sha256
        ):
            return operation
    return None


def _event_identity(event, control) -> str:
    results = list(
        models.RaceEventResult.objects.filter(event=event)
        .order_by("finish_position", "id")
        .values(
            "finish_position",
            "official_finish_position",
            "horse_number",
            "horse_name",
            "jockey_name",
            "trainer_name",
            "finish_time",
            "margin",
            "barrier",
            "carried_weight",
            "running_status",
            "is_confirmed",
            "source_refs",
        )
    )
    return _digest(
        {
            "event_id": event.pk,
            "status": event.status,
            "data_quality_status": event.data_quality_status,
            "result_confirmed_at": event.result_confirmed_at,
            "write_owner": control.write_owner,
            "owner_generation": control.owner_generation,
            "owner_manifest_sha256": control.owner_manifest_sha256,
            "current_result_revision_id": control.current_result_revision_id,
            "results": results,
        }
    )


def current_recovery_event_identity(event_id: int) -> str:
    event = models.RaceEvent.objects.get(pk=event_id)
    control = models.RaceEventProjectionControl.objects.get(event=event)
    return _event_identity(event, control)


def _before_projection(event, control) -> dict:
    return {
        "event": {
            "status": event.status,
            "data_quality_status": event.data_quality_status,
            "result_confirmed_at": (
                event.result_confirmed_at.isoformat()
                if event.result_confirmed_at
                else None
            ),
        },
        "control": {
            "write_owner": control.write_owner,
            "owner_generation": control.owner_generation,
            "owner_manifest_sha256": control.owner_manifest_sha256,
            "owner_changed_at": (
                control.owner_changed_at.isoformat()
                if control.owner_changed_at
                else None
            ),
            "owner_changed_by_id": control.owner_changed_by_id,
            "next_result_revision_no": control.next_result_revision_no,
            "current_result_revision_id": control.current_result_revision_id,
            "last_known_good_result_revision_id": (
                control.last_known_good_result_revision_id
            ),
            "last_provisional_result_revision_id": (
                control.last_provisional_result_revision_id
            ),
        },
        "results": list(
            models.RaceEventResult.objects.filter(event=event)
            .order_by("finish_position", "id")
            .values(
                "finish_position",
                "official_finish_position",
                "horse_number",
                "horse_name",
                "jockey_name",
                "trainer_name",
                "finish_time",
                "margin",
                "odds_value",
                "popularity",
                "barrier",
                "carried_weight",
                "running_status",
                "is_confirmed",
                "source_refs",
                "raw_payload",
            )
        ),
    }


def _source_identity(event, receipt):
    source_key = receipt.get("source_key")
    source = (
        models.RaceResultSourceIdentity.objects.select_for_update()
        .filter(event=event, source_key=source_key)
        .first()
    )
    if (
        source is None
        or source.review_status != models.RaceLiveReviewStatus.APPROVED
        or source.result_authority != models.RaceResultSourceAuthority.OFFICIAL
    ):
        raise RecoveryApplyBlocked("official_source_identity_missing")
    return source


def _participant_bindings(event, source, rows, manifest_sha256):
    external_ids = [
        row.get("external_runner_id", "")
        for row in rows
        if row.get("external_runner_id", "")
    ]
    if len(set(external_ids)) != len(external_ids):
        raise RecoveryApplyBlocked("participant_identity_missing")
    external_identities = {
        identity.external_runner_id: identity.participant
        for identity in models.RaceEventParticipantSourceIdentity.objects.select_related(
            "participant"
        )
        .select_for_update()
        .filter(
            source_identity=source,
            external_runner_id__in=external_ids,
            participant__event=event,
        )
    }
    if set(external_identities) != set(external_ids):
        raise RecoveryApplyBlocked("participant_identity_missing")
    bindings = {}
    used_participant_ids = set()
    for row in rows:
        runner_id = row.get("external_runner_id", "")
        official_name = row.get("official_name", "")
        horse_number = row.get("horse_number", "")
        if runner_id:
            participant = external_identities[runner_id]
        else:
            matching_names = models.RaceEventParticipant.objects.filter(
                event=event,
                canonical_name=official_name,
            )
            if matching_names.count() != 1:
                raise RecoveryApplyBlocked("participant_ambiguous")
            stable_digest = _digest(
                {
                    "source_key": source.source_key,
                    "runner_id": "",
                    "official_name": official_name,
                    "horse_number": horse_number,
                    "manifest_sha256": manifest_sha256,
                }
            )
            participant = matching_names.filter(
                stable_key=f"recovery:{stable_digest[:96]}"
            ).first()
            if participant is None:
                raise RecoveryApplyBlocked("participant_identity_missing")
            fallback_identities = (
                models.RaceEventParticipantSourceIdentity.objects.select_for_update()
                .filter(
                    participant=participant,
                    source_identity=source,
                    external_runner_id="",
                )
            )
            if fallback_identities.count() != 1:
                raise RecoveryApplyBlocked("participant_identity_missing")
        if participant.canonical_name != official_name:
            raise RecoveryApplyBlocked("participant_name_drift")
        if participant.pk in used_participant_ids:
            raise RecoveryApplyBlocked("participant_duplicate_binding")
        used_participant_ids.add(participant.pk)
        bindings[row["internal_order"]] = participant
    return bindings


def _aware_datetime(value, reason_code):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RecoveryApplyBlocked(reason_code) from exc
    else:
        raise RecoveryApplyBlocked(reason_code)
    if timezone.is_naive(parsed):
        raise RecoveryApplyBlocked(reason_code)
    return parsed


def _revalidate_route_registry(receipt, route_registry, now):
    routes = route_registry.get("routes")
    route = (
        routes.get(receipt.get("route_key"))
        if isinstance(routes, dict)
        else None
    )
    if not isinstance(route, dict) or route.get("revoked") is True:
        raise RecoveryApplyBlocked("route_not_approved")
    if route.get("access_mode") != "manual_browser_only":
        raise RecoveryApplyBlocked("route_access_mode_invalid")
    valid_until = _aware_datetime(
        route.get("valid_until") or route_registry.get("valid_until"),
        "route_validity_invalid",
    )
    receipt_valid_until = _aware_datetime(
        receipt.get("valid_until"), "route_validity_invalid"
    )
    if now > valid_until or now > receipt_valid_until:
        raise RecoveryApplyBlocked("route_expired")
    if route.get("contract_digest") != receipt.get("route_contract_digest"):
        raise RecoveryApplyBlocked("route_digest_drift")
    terms_digest = route.get("terms_digest") or (
        route.get("terms_evidence", {}).get("sha256")
        if isinstance(route.get("terms_evidence"), dict)
        else ""
    )
    if terms_digest != receipt.get("terms_digest"):
        raise RecoveryApplyBlocked("terms_digest_drift")
    if (
        str(route.get("region") or route.get("country_region") or "")
        != receipt.get("region")
        or (
            route.get("source_key")
            and route.get("source_key") != receipt.get("source_key")
        )
    ):
        raise RecoveryApplyBlocked("route_identity_drift")
    parsed = urlsplit(receipt.get("source_url", ""))
    allowed_hosts = route.get("allowed_hosts") or [route.get("host")]
    prefixes = route.get("allowed_path_prefixes") or [route.get("path_prefix")]
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or not any(
            parsed.path.startswith(prefix)
            for prefix in prefixes
            if isinstance(prefix, str) and prefix
        )
    ):
        raise RecoveryApplyBlocked("route_url_outside_allowlist")
    if _digest(route_registry) != receipt.get("route_registry_digest"):
        raise RecoveryApplyBlocked("route_registry_digest_drift")


def _running_status(item_status: str) -> str:
    valid = set(models.RaceRunnerStatus.values)
    if item_status in valid:
        return item_status
    if item_status in {
        models.RaceEventRevisionItemStatus.FINISHED,
        models.RaceEventRevisionItemStatus.DEAD_HEAT,
    }:
        return ""
    return ""


def _reserve_ledger(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(descriptor)


def _publish_ledger(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        _reserve_ledger(temporary, payload)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def apply_recovery_event(
    *,
    event_id: int,
    validated_receipt: dict,
    manifest_sha256: str,
    approval_sha256: str,
    expected_owner: str,
    expected_generation: int,
    expected_before_identity: str,
    route_registry: dict,
    ledger_root,
    applied_by_id: int,
    now,
):
    if len(manifest_sha256 or "") != 64 or len(approval_sha256 or "") != 64:
        raise RecoveryApplyBlocked("approval_digest_invalid")
    existing = _operation_for(
        event_id=event_id,
        manifest_sha256=manifest_sha256,
        approval_sha256=approval_sha256,
    )
    if existing is not None:
        return {
            "status": "already_applied",
            "event_id": event_id,
            "operation_log_id": existing.pk,
        }
    ledger_path = (
        Path(ledger_root)
        / f"event-{event_id}-{manifest_sha256}-{approval_sha256}.json"
    )
    prepared_published = False
    operation_id = None
    db_committed = False
    try:
        with transaction.atomic():
            _advisory_lock_event_ids((event_id,))
            concurrent_existing = _operation_for(
                event_id=event_id,
                manifest_sha256=manifest_sha256,
                approval_sha256=approval_sha256,
            )
            if concurrent_existing is not None:
                return {
                    "status": "already_applied",
                    "event_id": event_id,
                    "operation_log_id": concurrent_existing.pk,
                }
            event = models.RaceEvent.objects.select_for_update().get(pk=event_id)
            control = models.RaceEventProjectionControl.objects.select_for_update().get(
                event=event
            )
            if validated_receipt.get("event_id") != event_id:
                raise RecoveryApplyBlocked("receipt_event_mismatch")
            if validated_receipt.get("authority") != "official":
                raise RecoveryApplyBlocked("receipt_not_official")
            if control.write_owner != expected_owner:
                raise RecoveryApplyBlocked("owner_drift")
            if control.owner_generation != expected_generation:
                raise RecoveryApplyBlocked("owner_generation_drift")
            if control.write_owner == models.RaceEventProjectionWriteOwner.MANUAL_PAUSED:
                raise RecoveryApplyBlocked("owner_manual_paused")
            if control.write_owner == models.RaceEventProjectionWriteOwner.LIVE:
                # Recovery never synthesizes the live incident/tracking/
                # authorization control plane.  A dedicated live transition
                # owns that path (notably event 924).
                raise RecoveryApplyBlocked("live_prerequisites_missing")
            if (
                control.write_owner
                == models.RaceEventProjectionWriteOwner.HISTORICAL
                and control.owner_manifest_sha256 != manifest_sha256
            ):
                raise RecoveryApplyBlocked("owner_manifest_drift")
            before_identity = _event_identity(event, control)
            if before_identity != expected_before_identity:
                raise RecoveryApplyBlocked("before_identity_drift")
            _revalidate_route_registry(
                validated_receipt, route_registry, now
            )

            source = _source_identity(event, validated_receipt)
            rows = sorted(
                validated_receipt["rows"],
                key=lambda row: row["internal_order"],
            )
            participants = _participant_bindings(
                event, source, rows, manifest_sha256
            )
            before_projection = _before_projection(event, control)
            prepared = {
                "schema_version": 1,
                "state": "prepared",
                "event_id": event_id,
                "manifest_sha256": manifest_sha256,
                "approval_sha256": approval_sha256,
                "before_identity": before_identity,
                "before_projection": before_projection,
                "after_identity": "",
                "database_operation_log_id": None,
            }
            _reserve_ledger(ledger_path, prepared)
            prepared_published = True

            if control.write_owner == models.RaceEventProjectionWriteOwner.UNMANAGED:
                control.write_owner = models.RaceEventProjectionWriteOwner.HISTORICAL
                control.owner_generation += 1
                control.owner_manifest_sha256 = manifest_sha256
                control.owner_changed_at = now
                control.owner_changed_by_id = applied_by_id

            normalized_sha = validated_receipt.get("evidence_sha256") or _digest(rows)
            observation, _ = models.RaceResultObservation.objects.get_or_create(
                source_identity=source,
                normalized_sha256=normalized_sha,
                result_phase=models.RaceResultPhase.OFFICIAL,
                defaults={
                    "observed_at": validated_receipt.get("observed_at") or now,
                    "parser_version": "race-result-recovery-v1",
                    "raw_sha256": validated_receipt.get("receipt_sha256")
                    or normalized_sha,
                    "normalized_payload": {"rows": rows},
                    "field_provenance": {
                        "route_key": validated_receipt.get("route_key", ""),
                        "source_url": validated_receipt.get("source_url", ""),
                    },
                    "permission_classification": "manual_official_receipt",
                },
            )
            content_sha = _digest(rows)
            revision = models.RaceEventRevision.objects.create(
                event=event,
                kind=models.RaceEventRevisionKind.RESULT,
                revision_no=control.next_result_revision_no,
                phase=models.RaceResultPhase.OFFICIAL,
                content_sha256=content_sha,
                source_authority=models.RaceResultSourceAuthority.OFFICIAL,
                decision_reason="approved race-result recovery",
                primary_observation=observation,
                supersedes=control.current_result_revision,
                published_at=None,
                official_confirmed_at=now,
                applied_by_id=applied_by_id,
            )
            models.RaceEventRevisionEvidence.objects.create(
                revision=revision,
                observation=observation,
                role="official",
            )
            for row in rows:
                participant = participants[row["internal_order"]]
                models.RaceEventRevisionItem.objects.create(
                    revision=revision,
                    participant=participant,
                    source_order=row.get("source_order"),
                    internal_order=row["internal_order"],
                    official_finish_position=row.get(
                        "official_finish_position"
                    ),
                    status=row["status"],
                    raw_status=row.get("raw_status", ""),
                    finish_time=row.get("finish_time", ""),
                    margin=row.get("margin", ""),
                    horse_number=row.get("horse_number", ""),
                    barrier=row.get("barrier", ""),
                    jockey_name=row.get("jockey_name", ""),
                    trainer_name=row.get("trainer_name", ""),
                    carried_weight=row.get("carried_weight", ""),
                    field_provenance=row.get("field_provenance", {}),
                )

            # The PostgreSQL publication guards require the immutable audit row
            # to exist before the one permitted NULL -> timestamp transition.
            # This records the reviewed recovery route itself; it deliberately
            # does not create or impersonate a race-live allowlist, incident,
            # tracking claim, policy decision, or live authorization.
            models.RaceEventRevisionPublication.objects.create(
                revision=revision,
                published_at=now,
                reason="recovery_official_route",
                policy_versions=[],
                allowlist_version=1,
                registry_digest=validated_receipt.get(
                    "route_contract_digest", ""
                ),
                coverage_proof_digest=validated_receipt.get(
                    "receipt_sha256", ""
                ),
                authorization_kind=(
                    models.RaceLivePublicationAuthorizationKind.OFFICIAL_ROUTE
                ),
                official_authorization_version=0,
            )
            revision.published_at = now
            revision.save(update_fields=("published_at", "updated_at"))

            models.RaceEventResult.objects.filter(event=event).delete()
            for row in rows:
                participant = participants[row["internal_order"]]
                models.RaceEventResult.objects.create(
                    event=event,
                    finish_position=row["internal_order"],
                    official_finish_position=row.get(
                        "official_finish_position"
                    ),
                    horse_number=row.get("horse_number", ""),
                    horse_name=row.get("official_name")
                    or participant.canonical_name,
                    jockey_name=row.get("jockey_name", ""),
                    trainer_name=row.get("trainer_name", ""),
                    finish_time=row.get("finish_time", ""),
                    margin=row.get("margin", ""),
                    barrier=row.get("barrier", ""),
                    carried_weight=row.get("carried_weight", ""),
                    running_status=_running_status(row["status"]),
                    is_confirmed=True,
                    source_refs={
                        "source_key": source.source_key,
                        "source_url": validated_receipt.get("source_url", ""),
                        "receipt_sha256": validated_receipt.get(
                            "receipt_sha256", ""
                        ),
                        "official_finish_position": row.get(
                            "official_finish_position"
                        ),
                    },
                    raw_payload={"raw_status": row.get("raw_status", "")},
                )

            previous_revision = control.current_result_revision
            control.current_result_revision = revision
            control.last_known_good_result_revision = revision
            control.next_result_revision_no += 1
            control.save()
            event.status = models.RaceEventStatus.FINISHED
            event.data_quality_status = models.RaceEventDataQuality.COMPLETE
            event.result_confirmed_at = now
            event.save(
                update_fields=(
                    "status",
                    "data_quality_status",
                    "result_confirmed_at",
                    "updated_at",
                )
            )
            after_identity = _event_identity(event, control)
            operation = models.OperationLog.objects.create(
                admin_id=applied_by_id,
                action_type="race_result_recovery_apply",
                target_type="RaceEvent",
                target_id=str(event_id),
                detail=json.dumps(
                    {
                        "manifest_sha256": manifest_sha256,
                        "approval_sha256": approval_sha256,
                        "before_identity": before_identity,
                        "after_identity": after_identity,
                        "revision_id": revision.pk,
                        "previous_revision_id": (
                            previous_revision.pk if previous_revision else None
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                created_at=now,
            )
            operation_id = operation.pk
            applied = {
                **prepared,
                "state": "applied",
                "after_identity": after_identity,
                "database_operation_log_id": operation_id,
            }
            _publish_ledger(ledger_path, applied)
        db_committed = True
        return {
            "status": "applied",
            "event_id": event_id,
            "revision_id": revision.pk,
            "operation_log_id": operation_id,
            "ledger_path": str(ledger_path),
        }
    except Exception:
        if prepared_published and not db_committed:
            try:
                ledger_path.unlink()
            except FileNotFoundError:
                pass
        raise


def verify_recovery_ledger(ledger_path):
    path = Path(ledger_path)
    try:
        if path.stat().st_mode & 0o077:
            raise RecoveryLedgerError("ledger_permissions_invalid")
    except OSError as exc:
        raise RecoveryLedgerError("ledger_invalid") from exc
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryLedgerError("ledger_invalid") from exc
    if payload.get("state") == "prepared":
        if _operation_for(
            event_id=payload.get("event_id"),
            manifest_sha256=payload.get("manifest_sha256", ""),
            approval_sha256=payload.get("approval_sha256", ""),
        ):
            return {
                "status": "database_applied_ledger_incomplete",
                "rollback_allowed": False,
                "event_id": payload.get("event_id"),
            }
        return {
            "status": "prepared_not_applied",
            "rollback_allowed": False,
            "event_id": payload.get("event_id"),
        }
    operation_id = payload.get("database_operation_log_id")
    operation = (
        models.OperationLog.objects.filter(
            pk=operation_id,
            action_type="race_result_recovery_apply",
            target_id=str(payload.get("event_id")),
        ).first()
        if operation_id
        else None
    )
    operation_matches = False
    if operation is not None:
        try:
            detail = json.loads(operation.detail)
        except (TypeError, ValueError):
            detail = {}
        operation_matches = (
            detail.get("manifest_sha256") == payload.get("manifest_sha256")
            and detail.get("approval_sha256") == payload.get("approval_sha256")
            and detail.get("before_identity") == payload.get("before_identity")
            and detail.get("after_identity") == payload.get("after_identity")
        )
    projection_matches = False
    if operation_matches:
        try:
            projection_matches = (
                current_recovery_event_identity(payload.get("event_id"))
                == payload.get("after_identity")
            )
        except (
            models.RaceEvent.DoesNotExist,
            models.RaceEventProjectionControl.DoesNotExist,
        ):
            projection_matches = False
    return {
        "status": (
            "applied"
            if operation_matches and projection_matches
            else "ledger_database_drift"
        ),
        "rollback_allowed": operation_matches and projection_matches,
        "event_id": payload.get("event_id"),
    }


def rollback_recovery_event(
    *,
    ledger_path,
    expected_manifest_sha256: str,
    rolled_back_by_id: int,
    now,
):
    path = Path(ledger_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    verdict = verify_recovery_ledger(path)
    if verdict["status"] != "applied":
        raise RecoveryLedgerError(verdict["status"])
    if payload.get("manifest_sha256") != expected_manifest_sha256:
        raise RecoveryLedgerError("ledger_manifest_drift")
    before = payload.get("before_projection")
    if not isinstance(before, dict):
        raise RecoveryLedgerError("rollback_before_projection_missing")
    event_id = payload.get("event_id")
    with transaction.atomic():
        _advisory_lock_event_ids((event_id,))
        event = models.RaceEvent.objects.select_for_update().get(pk=event_id)
        control = models.RaceEventProjectionControl.objects.select_for_update().get(
            event=event
        )
        if _event_identity(event, control) != payload.get("after_identity"):
            raise RecoveryLedgerError("rollback_after_projection_drift")
        control_before = before["control"]
        if control.owner_manifest_sha256 != expected_manifest_sha256:
            raise RecoveryLedgerError("rollback_owner_manifest_drift")

        models.RaceEventResult.objects.filter(event=event).delete()
        for row in before.get("results", []):
            models.RaceEventResult.objects.create(event=event, **row)

        event_before = before["event"]
        event.status = event_before["status"]
        event.data_quality_status = event_before["data_quality_status"]
        event.result_confirmed_at = event_before["result_confirmed_at"]
        event.save(
            update_fields=(
                "status",
                "data_quality_status",
                "result_confirmed_at",
                "updated_at",
            )
        )
        for field, value in control_before.items():
            setattr(control, field, value)
        control.save()
        operation = models.OperationLog.objects.create(
            admin_id=rolled_back_by_id,
            action_type="race_result_recovery_rollback",
            target_type="RaceEvent",
            target_id=str(event_id),
            detail=json.dumps(
                {
                    "manifest_sha256": expected_manifest_sha256,
                    "apply_operation_log_id": payload[
                        "database_operation_log_id"
                    ],
                    "restored_identity": _event_identity(event, control),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            created_at=now,
        )
    rollback_path = path.with_name(
        f"{path.stem}.rollback-{operation.pk}.json"
    )
    _reserve_ledger(
        rollback_path,
        {
            "schema_version": 1,
            "state": "rolled_back",
            "event_id": event_id,
            "manifest_sha256": expected_manifest_sha256,
            "apply_ledger": path.name,
            "database_operation_log_id": operation.pk,
        },
    )
    return {
        "status": "rolled_back",
        "event_id": event_id,
        "operation_log_id": operation.pk,
        "ledger_path": str(rollback_path),
    }

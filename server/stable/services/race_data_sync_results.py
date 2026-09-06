from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import unicodedata
from typing import Any

from django.db import transaction
from django.utils import timezone

from stable import models
from stable.services.race_data_sync_control import (
    RaceDataSyncClaim,
    lock_and_validate_race_data_sync_claim_for_apply,
)
from stable.services.race_data_sync_policy import (
    arbitrate_source_value,
    normalize_source_class,
)
from stable.services.race_event_public_cache import invalidate_public_race_cache


_TERMINAL_RESULT_STATUSES = frozenset(
    {
        models.RaceEventRevisionItemStatus.FINISHED,
        models.RaceEventRevisionItemStatus.DEAD_HEAT,
        models.RaceEventRevisionItemStatus.SCRATCHED,
        models.RaceEventRevisionItemStatus.WITHDRAWN,
        models.RaceEventRevisionItemStatus.NON_RUNNER,
        models.RaceEventRevisionItemStatus.DISQUALIFIED,
        models.RaceEventRevisionItemStatus.DID_NOT_FINISH,
        models.RaceEventRevisionItemStatus.PULLED_UP,
        models.RaceEventRevisionItemStatus.UNSEATED_RIDER,
        models.RaceEventRevisionItemStatus.FELL,
        models.RaceEventRevisionItemStatus.REFUSED,
    }
)
_RANKED_RESULT_STATUSES = frozenset(
    {
        models.RaceEventRevisionItemStatus.FINISHED,
        models.RaceEventRevisionItemStatus.DEAD_HEAT,
    }
)


@dataclass(frozen=True)
class DataSyncResultApplyDecision:
    action: str
    reason_code: str = ""
    revision_id: int | None = None
    projected: bool = False


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _normalize_result_rows(payload: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(payload, dict) or set(payload) != {
        "external_race_id",
        "off_time",
        "region",
        "course",
        "race_name",
        "race_status",
        "participants",
    }:
        raise ValueError("result payload schema is invalid")
    participants = payload.get("participants")
    if not isinstance(participants, (list, tuple)) or not 1 <= len(participants) <= 100:
        raise ValueError("result participants are invalid")
    normalized: list[dict[str, Any]] = []
    seen_runner_ids: set[str] = set()
    ranked_positions: list[int] = []
    for source_order, raw in enumerate(participants, start=1):
        if not isinstance(raw, dict):
            raise ValueError("result participant is invalid")
        external_runner_id = str(raw.get("external_runner_id") or "").strip()
        horse_name = str(raw.get("horse_name") or "").strip()
        if (
            not external_runner_id
            or len(external_runner_id) > 128
            or external_runner_id in seen_runner_ids
            or not horse_name
            or len(horse_name) > 255
        ):
            raise ValueError("result participant identity is invalid")
        seen_runner_ids.add(external_runner_id)
        reported_position = raw.get("reported_finish_position")
        if reported_position is not None:
            if (
                isinstance(reported_position, bool)
                or not isinstance(reported_position, int)
                or not 1 <= reported_position <= 100
            ):
                raise ValueError("reported finish position is invalid")
        status = str(raw.get("status") or "").strip()
        if status not in models.RaceEventRevisionItemStatus.values:
            raise ValueError("result participant status is invalid")
        if (status in _RANKED_RESULT_STATUSES) != (reported_position is not None):
            raise ValueError("result position and status are inconsistent")
        if reported_position is not None:
            ranked_positions.append(reported_position)
        normalized.append(
            {
                "source_order": source_order,
                "external_runner_id": external_runner_id,
                "horse_name": horse_name,
                "reported_finish_position": reported_position,
                "status": status,
                "raw_status": str(raw.get("raw_status") or "")[:64],
                "finish_time": str(raw.get("finish_time") or "")[:64],
                "margin": str(raw.get("margin") or "")[:64],
                "number": str(raw.get("number") or "")[:32],
                "barrier": str(raw.get("barrier") or "")[:32],
                "jockey_name": str(raw.get("jockey_name") or "")[:255],
                "trainer_name": str(raw.get("trainer_name") or "")[:255],
                "carried_weight": str(raw.get("carried_weight") or "")[:64],
                "field_provenance": (
                    raw.get("field_provenance")
                    if isinstance(raw.get("field_provenance"), dict)
                    else {}
                ),
            }
        )
    if not ranked_positions:
        raise ValueError("result has no positive finish position")
    counts: dict[int, int] = {}
    for position in ranked_positions:
        counts[position] = counts.get(position, 0) + 1
    ranked_count = 0
    for position, count in sorted(counts.items()):
        if position != ranked_count + 1:
            raise ValueError("result finish order is not a legal competition ranking")
        ranked_count += count
    for row in normalized:
        position = row["reported_finish_position"]
        if position is None:
            continue
        expected_status = (
            models.RaceEventRevisionItemStatus.DEAD_HEAT
            if counts[position] > 1
            else models.RaceEventRevisionItemStatus.FINISHED
        )
        if row["status"] != expected_status:
            raise ValueError("result dead-heat status is inconsistent")
    return tuple(normalized)


def _source_runner_id(
    *, runner: models.RaceEventRunner, source: models.RaceResultSourceIdentity
) -> str:
    refs = runner.source_refs if isinstance(runner.source_refs, dict) else {}
    direct = str(refs.get(source.source_key) or "").strip()
    if direct:
        return direct
    if refs.get("source_key") == source.source_key:
        return str(refs.get("external_runner_id") or "").strip()
    return ""


def _identity_text(value: object) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", str(value or "")).split()
    ).casefold()


def _result_roster_mapping(
    *,
    event: models.RaceEvent,
    source: models.RaceResultSourceIdentity,
    rows: tuple[dict[str, Any], ...],
) -> tuple[tuple[dict[str, Any], models.RaceEventRunner], ...] | None:
    runners = list(
        models.RaceEventRunner.objects.select_for_update()
        .filter(event=event)
        .order_by("id")
    )
    if not runners or len(runners) != len(rows) or any(
        row["status"] not in _TERMINAL_RESULT_STATUSES for row in rows
    ):
        return None
    direct: dict[str, models.RaceEventRunner] = {}
    for runner in runners:
        external_runner_id = _source_runner_id(runner=runner, source=source)
        if not external_runner_id:
            continue
        if external_runner_id in direct:
            return None
        direct[external_runner_id] = runner
    assigned: set[int] = set()
    mapping: list[tuple[dict[str, Any], models.RaceEventRunner]] = []
    for row in rows:
        runner = direct.get(row["external_runner_id"])
        if runner is None:
            number = str(row.get("number") or "").strip()
            name = _identity_text(row.get("horse_name"))
            if not number or not name:
                return None
            candidates = [
                candidate
                for candidate in runners
                if candidate.pk not in assigned
                and not _source_runner_id(runner=candidate, source=source)
                and str(candidate.horse_number or "").strip() == number
                and _identity_text(candidate.horse_name) == name
            ]
            if len(candidates) != 1:
                return None
            runner = candidates[0]
        if runner.pk in assigned:
            return None
        assigned.add(runner.pk)
        mapping.append((row, runner))
    if len(assigned) != len(runners):
        return None
    return tuple(mapping)


def apply_data_sync_result_observation(
    *,
    observation_id: int,
    expected_event_id: int,
    now: datetime,
    project_current: bool,
    correction_apply_enabled: bool,
    claim_guard: RaceDataSyncClaim | None = None,
) -> DataSyncResultApplyDecision:
    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    with transaction.atomic():
        from stable.services.race_event_lifecycle_enforce import (
            lock_current_runtime_registry_membership,
            validate_registry_membership_snapshot,
        )

        membership_validation = None
        data_sync_admission = None
        if project_current:
            # Global lock graph: registry barrier/membership -> lifecycle -> event.
            has_legacy_membership = (
                models.RaceEventLifecycleEnforceMembership.objects.filter(
                    event_id=expected_event_id,
                    state="active",
                    registry__state="active",
                    registry__is_active=True,
                    registry__runtime_valid_until__gt=now,
                ).exists()
            )
            has_data_sync_authority = models.RaceEventLifecycleControl.objects.filter(
                event_id=expected_event_id,
                manifest_data__has_key="race_data_sync",
            ).exists()
            if has_legacy_membership and has_data_sync_authority:
                current_status = (
                    models.RaceEvent.objects.filter(pk=expected_event_id)
                    .values_list("status", flat=True)
                    .first()
                )
                if current_status not in {
                    models.RaceEventStatus.FINISHED,
                    models.RaceEventStatus.CANCELLED,
                }:
                    return DataSyncResultApplyDecision(
                        "rejected", "lifecycle_authority_conflict"
                    )
            if has_legacy_membership:
                membership_validation = lock_current_runtime_registry_membership(
                    event_id=expected_event_id,
                    now=now,
                )
            else:
                from stable.services.race_data_sync_admission import (
                    validate_data_sync_lifecycle_admission,
                )

                data_sync_admission = validate_data_sync_lifecycle_admission(
                    event_id=expected_event_id,
                    now=now,
                    lock=True,
                )
        lifecycle = (
            models.RaceEventLifecycleControl.objects.select_for_update()
            .filter(event_id=expected_event_id)
            .first()
        )
        locked_claim = None
        if claim_guard is not None:
            claim_decision, locked_claim = (
                lock_and_validate_race_data_sync_claim_for_apply(
                    claim=claim_guard,
                    now=timezone.now(),
                    required_data_kinds=(models.RaceDataSyncDataKind.RESULT,),
                )
            )
            if locked_claim is None:
                return DataSyncResultApplyDecision(
                    "rejected", claim_decision.reason_code
                )
            if locked_claim.event.pk != expected_event_id:
                return DataSyncResultApplyDecision(
                    "rejected", "event_identity_mismatch"
                )
        observation = (
            models.RaceResultObservation.objects.select_for_update()
            .select_related("source_identity")
            .filter(pk=observation_id)
            .first()
        )
        if observation is None:
            return DataSyncResultApplyDecision("rejected", "observation_missing")
        source = observation.source_identity
        if source.event_id != expected_event_id:
            return DataSyncResultApplyDecision("rejected", "event_identity_mismatch")
        if observation.result_phase not in {
            models.RaceResultPhase.OFFICIAL,
            models.RaceResultPhase.CORRECTED,
            models.RaceResultPhase.PROVISIONAL,
        }:
            return DataSyncResultApplyDecision("rejected", "result_phase_invalid")
        if (
            source.review_status != models.RaceLiveReviewStatus.APPROVED
            or source.automation_allowed is not True
        ):
            return DataSyncResultApplyDecision("rejected", "source_not_admitted")
        provenance = (
            observation.field_provenance
            if isinstance(observation.field_provenance, dict)
            else {}
        )
        candidate_source_class = normalize_source_class(
            provenance.get("source_class")
        )
        from stable.services.race_data_sync_pipeline import (
            build_race_data_provider_roster,
        )

        roster = build_race_data_provider_roster(configuration_only=True)
        roster_entry = next(
            (
                entry
                for entry in roster.entries
                if entry.provider == source.source_key
                and source.region_code in entry.regions
                and source.identity_namespace in entry.identity_namespaces
                and models.RaceDataSyncDataKind.RESULT in entry.data_kinds
            ),
            None,
        )
        if (
            provenance.get("provider") != source.source_key
            or not candidate_source_class
            or provenance.get("automation_allowed") is not True
            or roster_entry is None
            or candidate_source_class != roster_entry.source_class
            or source.terms_status != models.RaceSourceTermsStatus.APPROVED
            or source.valid_until is None
            or source.valid_until <= now
            or source.registry_digest != roster.registry_digest
            or provenance.get("region") != source.region_code
            or provenance.get("registry_digest") != roster.registry_digest
            or provenance.get("contract_version") != roster_entry.contract_version
            or provenance.get("contract_digest") != roster_entry.contract_digest
        ):
            return DataSyncResultApplyDecision("rejected", "source_contract_mismatch")
        try:
            rows = _normalize_result_rows(observation.normalized_payload)
        except (TypeError, ValueError):
            return DataSyncResultApplyDecision("rejected", "result_payload_incomplete")
        ordered_rows = tuple(
            sorted(
                rows,
                key=lambda row: (
                    row["reported_finish_position"] is None,
                    row["reported_finish_position"] or 101,
                    row["source_order"],
                ),
            )
        )

        event = (
            locked_claim.event
            if locked_claim is not None
            else models.RaceEvent.objects.select_for_update()
            .filter(pk=expected_event_id)
            .first()
        )
        control = (
            locked_claim.control
            if locked_claim is not None
            else models.RaceEventProjectionControl.objects.select_for_update()
            .filter(event_id=expected_event_id)
            .first()
        )
        if event is None or control is None:
            return DataSyncResultApplyDecision("rejected", "projection_subject_missing")
        if control.write_owner != models.RaceEventProjectionWriteOwner.DATA_SYNC:
            return DataSyncResultApplyDecision("rejected", "writer_owner_conflict")
        lifecycle_trusted = False
        lifecycle_reason = "registry_membership_missing"
        if membership_validation is not None:
            lifecycle_reason = membership_validation.reason_code
            if membership_validation.valid:
                lifecycle_snapshot = validate_registry_membership_snapshot(
                    membership=membership_validation.membership,
                    event=event,
                    control=lifecycle,
                    now=now,
                )
                lifecycle_trusted = lifecycle_snapshot.valid
                lifecycle_reason = lifecycle_snapshot.reason_code
        elif data_sync_admission is not None:
            lifecycle_trusted = data_sync_admission.admitted
            lifecycle_reason = data_sync_admission.reason_code
        race_status = str(
            observation.normalized_payload.get("race_status") or ""
        ).strip().casefold()
        terminal_marker = race_status in {
            value.casefold() for value in roster_entry.terminal_markers
        } or bool(
            observation.result_phase == models.RaceResultPhase.CORRECTED
            and provenance.get("correction_marker") is True
        )
        terminal_phase = observation.result_phase in {
            models.RaceResultPhase.OFFICIAL,
            models.RaceResultPhase.CORRECTED,
        }
        if terminal_phase and not terminal_marker:
            return DataSyncResultApplyDecision("rejected", "terminal_marker_missing")
        roster_mapping = None
        participants_by_external_id: dict[
            str, models.RaceEventParticipant | None
        ] = {}
        if terminal_phase:
            roster_mapping = _result_roster_mapping(
                event=event,
                source=source,
                rows=rows,
            )
            if roster_mapping is None:
                return DataSyncResultApplyDecision(
                    "rejected", "result_roster_incomplete"
                )
            existing_identities = list(
                models.RaceEventParticipantSourceIdentity.objects.select_for_update()
                .select_related("participant", "source_identity")
                .filter(participant__event=event)
            )
            identities_by_source_runner = {
                (
                    identity.source_identity.source_key,
                    identity.external_runner_id,
                ): identity
                for identity in existing_identities
                if identity.external_runner_id
            }
            identities_by_result_runner = {
                identity.external_runner_id: identity
                for identity in existing_identities
                if identity.source_identity_id == source.pk
                and identity.external_runner_id
            }
            identities_by_participant_source = {
                (identity.participant_id, identity.source_identity_id): identity
                for identity in existing_identities
            }
            for row, runner in roster_mapping:
                refs = (
                    runner.source_refs
                    if isinstance(runner.source_refs, dict)
                    else {}
                )
                candidate_participants: dict[
                    int, models.RaceEventParticipant
                ] = {}
                for source_key, external_runner_id in refs.items():
                    identity = identities_by_source_runner.get(
                        (str(source_key), str(external_runner_id or "").strip())
                    )
                    if identity is not None:
                        candidate_participants[identity.participant_id] = (
                            identity.participant
                        )
                legacy_source_key = str(refs.get("source_key") or "").strip()
                legacy_external_id = str(
                    refs.get("external_runner_id") or ""
                ).strip()
                if legacy_source_key and legacy_external_id:
                    identity = identities_by_source_runner.get(
                        (legacy_source_key, legacy_external_id)
                    )
                    if identity is not None:
                        candidate_participants[identity.participant_id] = (
                            identity.participant
                        )
                existing_result_identity = identities_by_result_runner.get(
                    row["external_runner_id"]
                )
                if existing_result_identity is not None:
                    candidate_participants[
                        existing_result_identity.participant_id
                    ] = existing_result_identity.participant
                if len(candidate_participants) > 1:
                    return DataSyncResultApplyDecision(
                        "rejected", "participant_identity_conflict"
                    )
                participant = next(
                    iter(candidate_participants.values()), None
                )
                if participant is not None:
                    participant_source_identity = (
                        identities_by_participant_source.get(
                            (participant.pk, source.pk)
                        )
                    )
                    if (
                        participant_source_identity is not None
                        and participant_source_identity.external_runner_id
                        != row["external_runner_id"]
                    ):
                        return DataSyncResultApplyDecision(
                            "rejected", "participant_identity_conflict"
                        )
                participants_by_external_id[row["external_runner_id"]] = (
                    participant
                )
        manual_locks = (
            event.manual_lock_flags
            if isinstance(event.manual_lock_flags, dict)
            else {}
        )
        current = control.current_result_revision
        current_observation = (
            current.primary_observation
            if current is not None and current.primary_observation_id
            else None
        )
        candidate_watermark = observation.source_updated_at or observation.observed_at
        current_watermark = None
        current_source_key = ""
        current_source_class = ""
        current_hash = ""
        if current is not None:
            current_source_class = normalize_source_class(current.source_authority)
            current_hash = current.content_sha256
            if current_observation is not None:
                current_source_key = current_observation.source_identity.source_key
                current_watermark = (
                    current_observation.source_updated_at
                    or current_observation.observed_at
                )
        content_sha256 = _canonical_sha256(observation.normalized_payload)
        arbitration = arbitrate_source_value(
            current_source_key=current_source_key,
            current_source_class=current_source_class,
            current_observed_at=current_watermark,
            candidate_source_key=source.source_key,
            candidate_source_class=candidate_source_class,
            candidate_observed_at=candidate_watermark,
            has_current_value=current is not None,
            values_equal=current_hash == content_sha256,
            manual_locked=bool(
                manual_locks.get("results")
                or manual_locks.get("result")
                or manual_locks.get("status")
            ),
        )
        if current is not None and current_hash == content_sha256:
            return DataSyncResultApplyDecision(
                "replayed", arbitration.reason_code, current.pk, True
            )
        correction_marked = bool(
            observation.result_phase == models.RaceResultPhase.CORRECTED
            and provenance.get("correction_marker") is True
        )
        priority_replacement = bool(
            current is not None
            and arbitration.apply
            and arbitration.reason_code == "higher_priority_source"
        )
        authorized_replacement = correction_marked or priority_replacement
        if (
            current is not None
            and authorized_replacement
            and not correction_apply_enabled
            and arbitration.apply
        ):
            return DataSyncResultApplyDecision(
                "rejected", "correction_apply_disabled", current.pk, True
            )

        phase = (
            models.RaceResultPhase.PROVISIONAL
            if observation.result_phase == models.RaceResultPhase.PROVISIONAL
            else observation.result_phase
        )
        correction_conflict = bool(
            current is not None and not authorized_replacement
        )
        granted_identity_id = models.RaceDataSyncEnrollment.objects.filter(
            event_id=expected_event_id,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
        ).values_list("source_identity_id", flat=True).first()
        initial_from_ungranted_source = bool(
            project_current
            and current is None
            and granted_identity_id is not None
            and observation.source_identity_id != granted_identity_id
        )
        may_project = bool(
            terminal_phase
            and project_current
            and arbitration.apply
            and lifecycle_trusted
            and not correction_conflict
            and not initial_from_ungranted_source
        )
        existing = models.RaceEventRevision.objects.filter(
            event=event,
            kind=models.RaceEventRevisionKind.RESULT,
            content_sha256=content_sha256,
        ).first()
        promote_existing = bool(
            existing is not None
            and may_project
            and existing.published_at is None
            and existing.primary_observation_id == observation.pk
            and existing.phase == phase
            and existing.source_authority == candidate_source_class
            and existing.items.count() == len(rows)
        )
        if existing is not None and not promote_existing:
            return DataSyncResultApplyDecision(
                "replayed",
                "revision_exists",
                existing.pk,
                control.current_result_revision_id == existing.pk,
            )
        if may_project:
            assert roster_mapping is not None
            for row, runner in roster_mapping:
                runner.source_refs = {
                    **(
                        runner.source_refs
                        if isinstance(runner.source_refs, dict)
                        else {}
                    ),
                    source.source_key: row["external_runner_id"],
                }
                runner.save(update_fields=("source_refs", "updated_at"))
        if promote_existing:
            assert existing is not None
            revision = existing
        else:
            revision = models.RaceEventRevision.objects.create(
                event=event,
                kind=models.RaceEventRevisionKind.RESULT,
                revision_no=control.next_result_revision_no,
                phase=phase,
                content_sha256=content_sha256,
                source_authority=candidate_source_class,
                decision_reason=(
                    "correction_marker_missing"
                    if correction_conflict
                    else "not_granted_source"
                    if initial_from_ungranted_source
                    else lifecycle_reason
                    if project_current and arbitration.apply and not lifecycle_trusted
                    else arbitration.reason_code
                ),
                primary_observation=observation,
                supersedes=(
                    current if arbitration.apply and authorized_replacement else None
                ),
                published_at=now if may_project else None,
                # Confirmation belongs to the immutable source revision, not
                # to the later decision to expose it publicly.
                official_confirmed_at=now if terminal_phase else None,
                conflict_status=(
                    models.RaceEventRevisionConflictStatus.PENDING
                    if correction_conflict
                    else models.RaceEventRevisionConflictStatus.NONE
                ),
            )
        if may_project:
            models.RaceEventRevisionPublication.objects.create(
                revision=revision,
                published_at=now,
                reason="data_sync_result",
                policy_versions=[
                    [
                        "race_data_sync_contract",
                        roster_entry.contract_version,
                        1,
                    ]
                ],
                allowlist_version=1,
                registry_digest=roster.registry_digest,
                coverage_proof_digest=observation.normalized_sha256,
                authorization_kind=(
                    models.RaceLivePublicationAuthorizationKind.OFFICIAL_ROUTE
                ),
                official_authorization_version=0,
            )
            if promote_existing:
                # PostgreSQL permits only the audited NULL -> timestamp
                # publication transition.  The audit row must exist first;
                # every other revision identity field remains immutable.
                revision.published_at = now
                revision.save(update_fields=("published_at", "updated_at"))
        if not promote_existing:
            control.next_result_revision_no += 1
            for internal_order, row in enumerate(ordered_rows, start=1):
                stable_key = (
                    f"{source.source_key}:"
                    f"{hashlib.sha256(row['external_runner_id'].encode()).hexdigest()[:48]}"
                )
                participant = participants_by_external_id.get(
                    row["external_runner_id"]
                )
                if participant is None:
                    participant, _ = (
                        models.RaceEventParticipant.objects.get_or_create(
                            event=event,
                            stable_key=stable_key,
                            defaults={
                                "canonical_name": row["horse_name"],
                                "country_region": event.country_region,
                                "review_status": models.RaceLiveReviewStatus.APPROVED,
                            },
                        )
                    )
                models.RaceEventParticipantSourceIdentity.objects.get_or_create(
                    source_identity=source,
                    external_runner_id=row["external_runner_id"],
                    defaults={"participant": participant},
                )
                reported_position = row["reported_finish_position"]
                models.RaceEventRevisionItem.objects.create(
                    revision=revision,
                    participant=participant,
                    source_order=row["source_order"],
                    internal_order=internal_order,
                    reported_finish_position=reported_position,
                    official_finish_position=reported_position,
                    status=row["status"],
                    raw_status=row["raw_status"],
                    finish_time=row["finish_time"],
                    margin=row["margin"],
                    horse_number=row["number"],
                    barrier=row["barrier"],
                    jockey_name=row["jockey_name"],
                    trainer_name=row["trainer_name"],
                    carried_weight=row["carried_weight"],
                    field_provenance=row["field_provenance"],
                )
            models.RaceEventRevisionEvidence.objects.create(
                revision=revision,
                observation=observation,
                role="primary",
            )

        projected = may_project
        if projected:
            models.RaceEventResult.objects.filter(event=event).delete()
            legacy_results = []
            for item, row in zip(
                revision.items.order_by("internal_order"), ordered_rows, strict=True
            ):
                legacy_results.append(
                    models.RaceEventResult(
                        event=event,
                        finish_position=item.internal_order,
                        reported_finish_position=item.reported_finish_position,
                        official_finish_position=item.official_finish_position,
                        horse_number=item.horse_number,
                        horse_name=row["horse_name"],
                        jockey_name=item.jockey_name,
                        trainer_name=item.trainer_name,
                        finish_time=item.finish_time,
                        margin=item.margin,
                        barrier=item.barrier,
                        carried_weight=item.carried_weight,
                        running_status=item.status,
                        is_confirmed=True,
                        source_refs={
                            "source_key": source.source_key,
                            "external_runner_id": row["external_runner_id"],
                            "revision_id": revision.pk,
                        },
                        raw_payload={
                            "raw_status": item.raw_status,
                            "field_provenance": item.field_provenance,
                        },
                    )
                )
            models.RaceEventResult.objects.bulk_create(legacy_results)
            control.current_result_revision = revision
            control.last_known_good_result_revision = revision
            control.last_provisional_result_revision = None
            event_before_status = event.status
            event.status = models.RaceEventStatus.FINISHED
            event.result_confirmed_at = now
            event.save(
                update_fields=("status", "result_confirmed_at", "updated_at")
            )
            models.RaceEventLiveTracking.objects.filter(event=event).update(
                state=(
                    models.RaceEventLiveState.CORRECTED_RESULT
                    if phase == models.RaceResultPhase.CORRECTED
                    else models.RaceEventLiveState.OFFICIAL_RESULT
                ),
                official_published_at=now,
                corrected_at=(
                    now if phase == models.RaceResultPhase.CORRECTED else None
                ),
                updated_at=now,
            )
            if event_before_status != models.RaceEventStatus.FINISHED:
                models.RaceEventLifecycleTransition.objects.get_or_create(
                    dedupe_key=f"data-sync-result:{event.pk}:{revision.pk}:finished",
                    defaults={
                        "event": event,
                        "from_status": event_before_status,
                        "to_status": models.RaceEventStatus.FINISHED,
                        "reason_code": "data_sync_complete_result",
                        "effective_at": now,
                        "source_authority": candidate_source_class,
                        "source_key": source.source_key,
                        "source_url": source.canonical_url,
                        "trigger_task": "sync_race_event_provider_task",
                        "schedule_generation": (
                            lifecycle.schedule_generation if lifecycle else 0
                        ),
                        "record_kind": (
                            models.RaceEventLifecycleTransitionKind.APPLIED
                        ),
                        "metadata": {
                            "observation_id": observation.pk,
                            "revision_id": revision.pk,
                        },
                    },
                )
            transaction.on_commit(invalidate_public_race_cache)
        if phase == models.RaceResultPhase.PROVISIONAL:
            control.last_provisional_result_revision = revision
        control.save(
            update_fields=(
                "next_result_revision_no",
                "current_result_revision",
                "last_known_good_result_revision",
                "last_provisional_result_revision",
                "updated_at",
            )
        )
        return DataSyncResultApplyDecision(
            "applied" if projected else "recorded",
            (
                "shadow_revision_promoted"
                if promote_existing
                else revision.decision_reason
            ),
            revision.pk,
            projected,
        )

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from stable import models
from stable.services.race_events import build_race_live_canonical_sha256
from stable.services.race_live_publication_transition import (
    LoadedRaceLivePublicationTransition,
    RaceLivePublicationTransitionError,
    _canonical_bytes,
    _parse_json,
    _read_safe_file,
    _sha256,
    _validate_output_root,
    apply_race_live_publication_transition,
    dry_run_race_live_publication_transition,
    read_bha_manual_route_registry,
)


class RaceLiveManualOfficialEvidenceError(ValueError):
    """Raised when an offline BHA manual receipt is unsafe or stale."""


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SUBMISSION_KEYS = frozenset(
    {
        "approved_commit",
        "event_id",
        "revision_id",
        "incident_id",
        "source_url",
        "observed_at",
        "evidence_sha256",
        "outcome",
        "marker_type",
        "participants",
    }
)
_RECEIPT_KEYS = _SUBMISSION_KEYS | frozenset(
    {
        "schema_version",
        "route_registry_digest",
        "route_contract_digest",
        "route_terms_digest",
        "route",
        "route_version",
    }
)


def _fail(message: str) -> None:
    raise RaceLiveManualOfficialEvidenceError(message)


def _aware_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(f"{label} 必须是 ISO-8601 aware datetime")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RaceLiveManualOfficialEvidenceError(
            f"{label} 不是合法时间"
        ) from exc
    if timezone.is_naive(result):
        _fail(f"{label} 必须包含时区")
    return result


def _validate_participants(value: Any, *, required: bool) -> list[dict[str, int]]:
    if not isinstance(value, list):
        _fail("participants 必须是 list")
    if required and not value:
        _fail("available receipt 必须包含 participants")
    result: list[dict[str, int]] = []
    participant_ids: set[int] = set()
    positions: set[int] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "participant_id",
            "position",
        }:
            _fail("participant schema 不匹配")
        participant_id = item["participant_id"]
        position = item["position"]
        if (
            isinstance(participant_id, bool)
            or not isinstance(participant_id, int)
            or participant_id <= 0
            or isinstance(position, bool)
            or not isinstance(position, int)
            or position <= 0
            or participant_id in participant_ids
            or position in positions
        ):
            _fail("participant/position 必须为唯一正整数")
        participant_ids.add(participant_id)
        positions.add(position)
        result.append(
            {"participant_id": participant_id, "position": position}
        )
    return result


def _validate_submission(
    submission: dict[str, Any],
    *,
    registry: dict[str, Any],
    registry_digest: str,
) -> dict[str, Any]:
    if not isinstance(submission, dict) or set(submission) != _SUBMISSION_KEYS:
        _fail("manual evidence submission schema 不匹配")
    if _COMMIT_RE.fullmatch(str(submission["approved_commit"])) is None:
        _fail("approved_commit 不合法")
    for key in ("event_id", "revision_id", "incident_id"):
        value = submission[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            _fail(f"{key} 必须是正整数")
    if submission["event_id"] != 924:
        _fail("manual evidence 只允许 event 924")
    source_url = submission["source_url"]
    if (
        not isinstance(source_url, str)
        or source_url != source_url.strip()
        or source_url != registry["official_results_url"]
    ):
        _fail("source_url 必须精确匹配受审 BHA Results URL")
    observed_at = _aware_datetime(submission["observed_at"], "observed_at")
    if _SHA256_RE.fullmatch(str(submission["evidence_sha256"])) is None:
        _fail("evidence_sha256 不合法")
    outcome = submission["outcome"]
    if outcome not in {"available", "unavailable"}:
        _fail("outcome 只允许 available/unavailable")
    marker_type = submission["marker_type"]
    if outcome == "available":
        if marker_type not in registry["allowed_marker_types"]:
            _fail("marker_type 不在受审 allowlist")
        participants = _validate_participants(
            submission["participants"],
            required=True,
        )
    else:
        if marker_type != "" or submission["participants"] != []:
            _fail("unavailable 不得伪造 marker/participants")
        participants = []
    return {
        "schema_version": 1,
        "approved_commit": submission["approved_commit"],
        "event_id": submission["event_id"],
        "revision_id": submission["revision_id"],
        "incident_id": submission["incident_id"],
        "source_url": source_url,
        "observed_at": observed_at.isoformat(),
        "evidence_sha256": submission["evidence_sha256"],
        "outcome": outcome,
        "marker_type": marker_type,
        "participants": participants,
        "route_registry_digest": registry_digest,
        "route_contract_digest": registry["contract_digest"],
        "route_terms_digest": registry["terms_evidence"]["sha256"],
        "route": registry["route"],
        "route_version": registry["parser_version"],
    }


def _validate_root(path_value: str | os.PathLike[str]) -> Path:
    try:
        return _validate_output_root(path_value)
    except RaceLivePublicationTransitionError as exc:
        raise RaceLiveManualOfficialEvidenceError(str(exc)) from exc


def prepare_race_live_manual_official_evidence(
    *,
    submission: dict[str, Any],
    output_root: str | os.PathLike[str],
    run_id: str,
) -> dict[str, Any]:
    if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        _fail("run_id 不合法")
    registry, registry_digest = read_bha_manual_route_registry()
    receipt = _validate_submission(
        submission,
        registry=registry,
        registry_digest=registry_digest,
    )
    root = _validate_root(output_root)
    path = root / f"{run_id}.receipt.json"
    if path.exists():
        _fail("receipt 已存在，禁止覆盖")
    data = _canonical_bytes(receipt) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)
    return {
        "ok": True,
        "event_ids": [receipt["event_id"]],
        "outcome": receipt["outcome"],
        "receipt_path": str(path),
        "receipt_sha256": hashlib.sha256(data).hexdigest(),
        "network_request_count": 0,
    }


def load_race_live_manual_official_evidence(
    *,
    receipt_path: str | os.PathLike[str],
    expected_receipt_sha256: str,
    expected_approved_commit: str,
) -> dict[str, Any]:
    if _SHA256_RE.fullmatch(str(expected_receipt_sha256)) is None:
        _fail("expected receipt SHA-256 不合法")
    if _COMMIT_RE.fullmatch(str(expected_approved_commit)) is None:
        _fail("expected approved commit 不合法")
    try:
        _, data = _read_safe_file(receipt_path)
    except RaceLivePublicationTransitionError as exc:
        raise RaceLiveManualOfficialEvidenceError(str(exc)) from exc
    if hashlib.sha256(data).hexdigest() != expected_receipt_sha256:
        _fail("receipt SHA-256 不匹配")
    try:
        payload = _parse_json(data, "manual evidence receipt")
    except RaceLivePublicationTransitionError as exc:
        raise RaceLiveManualOfficialEvidenceError(str(exc)) from exc
    if not isinstance(payload, dict) or set(payload) != _RECEIPT_KEYS:
        _fail("receipt schema 不匹配")
    registry, registry_digest = read_bha_manual_route_registry()
    submission = {key: payload[key] for key in _SUBMISSION_KEYS}
    normalized = _validate_submission(
        submission,
        registry=registry,
        registry_digest=registry_digest,
    )
    if payload != normalized:
        _fail("receipt canonical contract 不匹配")
    if payload["approved_commit"] != expected_approved_commit:
        _fail("approved commit 不匹配")
    return payload


def _manual_log_detail(receipt_sha256: str, receipt: dict[str, Any]) -> str:
    return json.dumps(
        {
            "approved_commit": receipt["approved_commit"],
            "outcome": receipt["outcome"],
            "receipt_sha256": receipt_sha256,
            "route_contract_digest": receipt["route_contract_digest"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _upsert_official_evidence(
    *,
    receipt: dict[str, Any],
    registry: dict[str, Any],
    registry_digest: str,
    event: models.RaceEvent,
    incident: models.RaceLiveOfficialVerificationIncident,
) -> models.RaceResultObservation:
    source, created = models.RaceResultSourceIdentity.objects.get_or_create(
        event=event,
        source_key=registry["source_key"],
        defaults={
            "external_race_id": f"bha-manual:{event.pk}",
            "canonical_url": receipt["source_url"],
            "host": "www.britishhorseracing.com",
            "identity_fields": {
                "event_id": event.pk,
                "route_contract_digest": receipt[
                    "route_contract_digest"
                ],
            },
            "review_status": models.RaceLiveReviewStatus.APPROVED,
            "result_authority": models.RaceResultSourceAuthority.OFFICIAL,
            "reviewed_at": _aware_datetime(
                receipt["observed_at"],
                "observed_at",
            ),
            "terms_status": models.RaceSourceTermsStatus.MANUAL,
            "automation_allowed": False,
            "proof_network_allowed": False,
            "evidence_url": registry["terms_evidence"]["url"],
            "evidence_sha256": registry["terms_evidence"]["sha256"],
            "valid_until": _aware_datetime(
                registry["valid_until"],
                "valid_until",
            ),
            "registry_digest": registry_digest,
        },
    )
    if not created and (
        source.external_race_id != f"bha-manual:{event.pk}"
        or source.result_authority != models.RaceResultSourceAuthority.OFFICIAL
        or source.automation_allowed is not False
        or source.registry_digest != registry_digest
    ):
        _fail("既有 BHA manual source identity 漂移")

    provisional_items = list(
        incident.provisional_revision.items.select_for_update().order_by(
            "internal_order"
        )
    )
    participant_by_id = {
        item.participant_id: item.participant
        for item in provisional_items
    }
    normalized_participants = []
    for item in receipt["participants"]:
        participant = participant_by_id[item["participant_id"]]
        external_runner_id = f"manual-participant:{participant.pk}"
        identity, identity_created = (
            models.RaceEventParticipantSourceIdentity.objects.get_or_create(
                participant=participant,
                source_identity=source,
                defaults={"external_runner_id": external_runner_id},
            )
        )
        if not identity_created and identity.external_runner_id != external_runner_id:
            _fail("BHA manual participant identity 漂移")
        normalized_participants.append(
            {
                "external_runner_id": external_runner_id,
                "official_finish_position": item["position"],
                "status": models.RaceEventRevisionItemStatus.FINISHED,
            }
        )
    payload = {
        "external_race_id": source.external_race_id,
        "participants": normalized_participants,
    }
    normalized_sha = build_race_live_canonical_sha256(
        normalized_payload=payload
    )
    observation, observation_created = (
        models.RaceResultObservation.objects.get_or_create(
            source_identity=source,
            normalized_sha256=normalized_sha,
            result_phase=models.RaceResultPhase.OFFICIAL,
            defaults={
                "observed_at": _aware_datetime(
                    receipt["observed_at"],
                    "observed_at",
                ),
                "parser_version": registry["parser_version"],
                "raw_sha256": receipt["evidence_sha256"],
                "normalized_payload": payload,
                "field_provenance": {
                    "access_mode": "manual_browser_only",
                    "route_contract_digest": receipt[
                        "route_contract_digest"
                    ],
                },
                "parse_warnings": [],
                "permission_classification": "manual_official_verification",
            },
        )
    )
    if not observation_created and (
        observation.raw_sha256 != receipt["evidence_sha256"]
        or observation.parser_version != registry["parser_version"]
        or observation.normalized_payload != payload
    ):
        _fail("既有 BHA manual observation 漂移")
    contract, contract_created = (
        models.RaceLiveOfficialMarkerContract.objects.get_or_create(
            country_region=event.country_region,
            source_key=registry["source_key"],
            parser_version=registry["parser_version"],
            defaults={
                "allowed_marker_types": registry[
                    "allowed_marker_types"
                ],
                "contract_digest": registry["contract_digest"],
                "valid_until": _aware_datetime(
                    registry["valid_until"],
                    "valid_until",
                ),
                "review_status": models.RaceLiveReviewStatus.APPROVED,
                "version": 1,
            },
        )
    )
    if not contract_created and (
        contract.contract_digest != registry["contract_digest"]
        or contract.allowed_marker_types != registry["allowed_marker_types"]
        or contract.review_status != models.RaceLiveReviewStatus.APPROVED
    ):
        _fail("既有 marker contract 漂移")
    evidence, evidence_created = (
        models.RaceLiveOfficialMarkerEvidence.objects.get_or_create(
            observation=observation,
            defaults={
                "contract": contract,
                "marker_type": receipt["marker_type"],
                "contract_digest": registry["contract_digest"],
                "parser_version": registry["parser_version"],
                "raw_sha256": receipt["evidence_sha256"],
                "source_timestamp": _aware_datetime(
                    receipt["observed_at"],
                    "observed_at",
                ),
            },
        )
    )
    if not evidence_created and (
        evidence.contract_id != contract.pk
        or evidence.marker_type != receipt["marker_type"]
        or evidence.raw_sha256 != receipt["evidence_sha256"]
    ):
        _fail("既有 marker evidence 漂移")
    return observation


def _compare_receipt_to_provisional(
    *,
    receipt: dict[str, Any],
    incident: models.RaceLiveOfficialVerificationIncident,
) -> str:
    provisional_items = list(
        incident.provisional_revision.items.select_for_update().order_by(
            "internal_order"
        )
    )
    expected_ids = {item.participant_id for item in provisional_items}
    actual_ids = {
        item["participant_id"] for item in receipt["participants"]
    }
    if expected_ids != actual_ids or len(expected_ids) != len(
        receipt["participants"]
    ):
        _fail("receipt participant 全集不匹配")
    expected_order = [
        (item.participant_id, item.official_finish_position)
        for item in provisional_items
    ]
    position_by_participant = {
        item["participant_id"]: item["position"]
        for item in receipt["participants"]
    }
    actual_order = [
        (
            item.participant_id,
            position_by_participant[item.participant_id],
        )
        for item in provisional_items
    ]
    return "match" if actual_order == expected_order else "conflict"


def _manual_replay_errors(
    *,
    receipt: dict[str, Any],
    receipt_sha256: str,
    event: models.RaceEvent,
    incident: models.RaceLiveOfficialVerificationIncident,
) -> tuple[str, list[str]]:
    errors: list[str] = []
    if receipt["outcome"] == "unavailable":
        comparison = "unavailable"
        if (
            incident.status
            != models.RaceLiveOfficialVerificationIncidentStatus.OPEN
            or incident.last_probe_at is None
            or incident.next_probe_at is None
        ):
            errors.append("unavailable_incident_mismatch")
        sent_alert_exists = _unavailable_alert_logs(
            incident_id=incident.pk,
        ).filter(status=models.NotificationStatus.SENT).exists()
        if (incident.alert_sent_at is not None) != sent_alert_exists:
            errors.append("unavailable_alert_mismatch")
        if models.RaceResultSourceIdentity.objects.filter(
            event=event,
            source_key="bha_manual",
        ).exists():
            errors.append("unavailable_source_present")
        return comparison, errors

    comparison = _compare_receipt_to_provisional(
        receipt=receipt,
        incident=incident,
    )
    source = models.RaceResultSourceIdentity.objects.filter(
        event=event,
        source_key="bha_manual",
    ).first()
    if (
        source is None
        or source.result_authority
        != models.RaceResultSourceAuthority.OFFICIAL
        or source.review_status != models.RaceLiveReviewStatus.APPROVED
        or source.automation_allowed is not False
        or source.registry_digest != receipt["route_registry_digest"]
        or source.evidence_sha256 != receipt["route_terms_digest"]
    ):
        errors.append("official_source_mismatch")
    observation = None
    if source is not None:
        observation = models.RaceResultObservation.objects.filter(
            source_identity=source,
            raw_sha256=receipt["evidence_sha256"],
            parser_version=receipt["route_version"],
            result_phase=models.RaceResultPhase.OFFICIAL,
        ).first()
    if observation is None:
        errors.append("official_observation_missing")
    else:
        evidence = models.RaceLiveOfficialMarkerEvidence.objects.filter(
            observation=observation,
            marker_type=receipt["marker_type"],
            contract_digest=receipt["route_contract_digest"],
            raw_sha256=receipt["evidence_sha256"],
        ).first()
        if evidence is None:
            errors.append("official_marker_evidence_missing")
    if comparison == "match":
        if (
            incident.status
            != models.RaceLiveOfficialVerificationIncidentStatus.RESOLVED
            or incident.resolved_at is None
        ):
            errors.append("match_incident_mismatch")
    else:
        if incident.status != (
            models.RaceLiveOfficialVerificationIncidentStatus.ESCALATED
        ):
            errors.append("conflict_incident_mismatch")
        event_policy = models.RaceLivePublicationPolicy.objects.filter(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(event.pk),
        ).first()
        if (
            event_policy is None
            or event_policy.mode != models.RaceLivePublicationMode.SHADOW
            or event_policy.version != 3
        ):
            errors.append("conflict_public_read_not_disabled")
    return comparison, errors


def _unavailable_alert_dedupe_key(*, incident_id: int) -> str:
    return f"race_live_official_unavailable_incident:{incident_id}"


def _unavailable_alert_logs(*, incident_id: int):
    dedupe_fragment = json.dumps(
        _unavailable_alert_dedupe_key(incident_id=incident_id)
    )
    return models.NotificationLog.objects.filter(
        type=models.NotificationType.OPS_ANOMALY,
        channel=models.NotificationChannel.EMAIL,
        payload_summary__contains=f'"dedupe_key":{dedupe_fragment}',
    )


def _stage_unavailable_alert_intent_locked(
    *,
    incident: models.RaceLiveOfficialVerificationIncident,
    receipt_sha256: str,
    effective_now: datetime,
) -> tuple[int | None, str]:
    logs = _unavailable_alert_logs(incident_id=incident.pk)
    sent_alert = logs.filter(
        status=models.NotificationStatus.SENT,
    ).first()
    if sent_alert is not None:
        if incident.alert_sent_at is None:
            _fail("已发送告警与 incident 状态不一致")
        return None, models.NotificationStatus.SENT
    if incident.alert_sent_at is not None:
        _fail("incident alert_sent_at 缺少 SENT 通知")

    queued_alert = logs.filter(
        status=models.NotificationStatus.QUEUED,
    ).order_by("pk").first()
    if queued_alert is not None:
        return queued_alert.pk, models.NotificationStatus.QUEUED

    recipients = list(
        getattr(settings, "RACE_LIVE_ALERT_NOTIFY_EMAILS", []) or []
    )
    intent = models.NotificationLog.objects.create(
        type=models.NotificationType.OPS_ANOMALY,
        channel=models.NotificationChannel.EMAIL,
        target=",".join(recipients),
        status=models.NotificationStatus.QUEUED,
        payload_summary=json.dumps(
            {
                "dedupe_key": _unavailable_alert_dedupe_key(
                    incident_id=incident.pk
                ),
                "event_id": incident.event_id,
                "incident_id": incident.pk,
                "reason": "bha_manual_result_unavailable",
                "receipt_sha256": receipt_sha256,
                "staged_at": effective_now.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    return intent.pk, models.NotificationStatus.QUEUED


def _deliver_unavailable_alert_intent(
    *,
    incident_id: int,
    notification_id: int,
    effective_now: datetime,
) -> str:
    with transaction.atomic():
        try:
            incident = (
                models.RaceLiveOfficialVerificationIncident.objects.select_for_update()
                .get(pk=incident_id, event_id=924)
            )
            notification = models.NotificationLog.objects.select_for_update().get(
                pk=notification_id,
                type=models.NotificationType.OPS_ANOMALY,
                channel=models.NotificationChannel.EMAIL,
            )
        except (
            models.RaceLiveOfficialVerificationIncident.DoesNotExist,
            models.NotificationLog.DoesNotExist,
        ) as exc:
            raise RaceLiveManualOfficialEvidenceError(
                "unavailable alert durable intent 缺失"
            ) from exc

        sent_alert = _unavailable_alert_logs(
            incident_id=incident.pk,
        ).filter(status=models.NotificationStatus.SENT).first()
        if sent_alert is not None:
            if incident.alert_sent_at is None:
                _fail("已发送告警与 incident 状态不一致")
            return models.NotificationStatus.SENT
        if incident.alert_sent_at is not None:
            _fail("incident alert_sent_at 缺少 SENT 通知")
        if notification.status != models.NotificationStatus.QUEUED:
            return notification.status

        recipients = [
            value.strip()
            for value in notification.target.split(",")
            if value.strip()
        ]
        try:
            if not recipients:
                raise RuntimeError("race-live 告警未配置收件人")
            delivered = send_mail(
                "[UmaFans] event 924 官方赛果人工复核暂不可用",
                "\n".join(
                    [
                        "event 924 的 BHA 人工官方赛果复核暂不可用。",
                        "",
                        "暂定赛果继续显示，官方复核 incident 保持 open。",
                        f"incident ID: {incident.pk}",
                    ]
                ),
                settings.DEFAULT_FROM_EMAIL,
                recipients,
                fail_silently=False,
            )
            if delivered != 1:
                raise RuntimeError(
                    f"race-live 告警发送数量异常：{delivered}"
                )
            notification.status = models.NotificationStatus.SENT
            notification.sent_at = effective_now
            notification.error_message = ""
            incident.alert_sent_at = effective_now
            incident.save(
                update_fields=("alert_sent_at", "updated_at")
            )
        except Exception as exc:
            notification.status = models.NotificationStatus.FAILED
            notification.sent_at = None
            notification.error_message = str(exc)[:2000]
        notification.save(
            update_fields=(
                "status",
                "sent_at",
                "error_message",
                "updated_at",
            )
        )
        return notification.status


def _validate_manual_evidence_action_input(
    *,
    receipt: dict[str, Any],
    receipt_sha256: str,
    effective_now: datetime,
) -> tuple[dict[str, Any], str]:
    if timezone.is_naive(effective_now):
        _fail("manual evidence action time 必须包含时区")
    if _SHA256_RE.fullmatch(str(receipt_sha256)) is None:
        _fail("receipt SHA-256 不合法")
    registry, registry_digest = read_bha_manual_route_registry(
        now=effective_now
    )
    if (
        not isinstance(receipt, dict)
        or set(receipt) != _RECEIPT_KEYS
        or receipt
        != _validate_submission(
            {key: receipt[key] for key in _SUBMISSION_KEYS},
            registry=registry,
            registry_digest=registry_digest,
        )
    ):
        _fail("receipt canonical contract 不匹配")
    return registry, registry_digest


def _planned_unavailable_alert_status(
    *,
    incident: models.RaceLiveOfficialVerificationIncident,
) -> str:
    logs = _unavailable_alert_logs(incident_id=incident.pk)
    sent_exists = logs.filter(
        status=models.NotificationStatus.SENT,
    ).exists()
    if (incident.alert_sent_at is not None) != sent_exists:
        _fail("unavailable alert post-state 不一致")
    if sent_exists:
        return models.NotificationStatus.SENT
    if logs.filter(status=models.NotificationStatus.QUEUED).exists():
        return models.NotificationStatus.QUEUED
    failed_exists = logs.filter(
        status=models.NotificationStatus.FAILED,
    ).exists()
    return "would_retry" if failed_exists else "would_send"


def _validate_disable_plan(
    *,
    receipt: dict[str, Any],
    disable_manifest: LoadedRaceLivePublicationTransition | None,
) -> None:
    if disable_manifest is None:
        _fail("conflict 必须提供预生成 disable manifest")
    if (
        disable_manifest.payload["event_id"] != receipt["event_id"]
        or disable_manifest.payload["transition"]
        != "disable_public_read"
        or disable_manifest.payload["approved_commit"]
        != receipt["approved_commit"]
    ):
        _fail("disable manifest 与 receipt 不匹配")
    dry_run_race_live_publication_transition(disable_manifest)


def _build_manual_evidence_plan_locked(
    *,
    receipt: dict[str, Any],
    receipt_sha256: str,
    disable_manifest: LoadedRaceLivePublicationTransition | None,
    effective_now: datetime,
    registry: dict[str, Any],
    registry_digest: str,
) -> dict[str, Any]:
    event_id = receipt["event_id"]
    try:
        # Same global lock order as runner and publication transition.
        control = models.RaceEventProjectionControl.objects.select_for_update(
            of=("self",)
        ).get(event_id=event_id)
        models.RaceEventLiveTracking.objects.select_for_update().get(
            event_id=event_id
        )
        event = models.RaceEvent.objects.select_for_update().get(pk=event_id)
        source = models.RaceResultSourceIdentity.objects.select_for_update().get(
            event_id=event_id,
            source_key="the_racing_api",
        )
        result_revision_hint = models.RaceEventRevision.objects.get(
            pk=receipt["revision_id"],
            event_id=event_id,
        )
        models.RaceResultObservation.objects.select_for_update().get(
            pk=result_revision_hint.primary_observation_id,
            source_identity=source,
        )
        racecard_revision = (
            models.RaceEventRevision.objects.select_for_update().get(
                pk=control.current_racecard_revision_id,
                event_id=event_id,
            )
        )
        result_revision = (
            models.RaceEventRevision.objects.select_for_update().get(
                pk=receipt["revision_id"],
                event_id=event_id,
            )
        )
        if (
            control.current_result_revision_id != result_revision.pk
            or result_revision.primary_observation_id
            != result_revision_hint.primary_observation_id
        ):
            _fail("manual evidence current revision 漂移")
    except (
        models.RaceEventProjectionControl.DoesNotExist,
        models.RaceEventLiveTracking.DoesNotExist,
        models.RaceEvent.DoesNotExist,
        models.RaceResultSourceIdentity.DoesNotExist,
        models.RaceResultObservation.DoesNotExist,
        models.RaceEventRevision.DoesNotExist,
    ) as exc:
        raise RaceLiveManualOfficialEvidenceError(
            "manual evidence database baseline 缺失"
        ) from exc

    locked_revision_items = list(
        models.RaceEventRevisionItem.objects.select_for_update()
        .filter(
            revision_id__in=(
                racecard_revision.pk,
                result_revision.pk,
            )
        )
        .order_by("revision_id", "internal_order", "pk")
    )
    racecard_participant_ids = {
        item.participant_id
        for item in locked_revision_items
        if item.revision_id == racecard_revision.pk
    }
    result_participant_ids = {
        item.participant_id
        for item in locked_revision_items
        if item.revision_id == result_revision.pk
    }
    if (
        not racecard_participant_ids
        or racecard_participant_ids != result_participant_ids
    ):
        _fail("manual evidence participant revision baseline 漂移")
    participants = list(
        models.RaceEventParticipant.objects.select_for_update()
        .filter(pk__in=result_participant_ids, event_id=event_id)
        .order_by("pk")
    )
    if (
        {participant.pk for participant in participants}
        != result_participant_ids
        or any(
            participant.review_status
            != models.RaceLiveReviewStatus.APPROVED
            for participant in participants
        )
    ):
        _fail("manual evidence participant baseline 漂移")
    source_rows = list(
        models.RaceEventParticipantSourceIdentity.objects.select_for_update()
        .filter(
            participant_id__in=result_participant_ids,
            source_identity=source,
        )
        .order_by("participant_id", "pk")
    )
    if {row.participant_id for row in source_rows} != result_participant_ids:
        _fail("manual evidence participant source identity 漂移")

    applicable_policy_filter = (
        Q(
            scope_type=models.RaceLivePublicationScopeType.GLOBAL,
            scope_key="global",
        )
        | Q(
            scope_type=models.RaceLivePublicationScopeType.REGION,
            scope_key=event.country_region,
        )
        | Q(
            scope_type=models.RaceLivePublicationScopeType.SOURCE,
            scope_key=source.source_key,
        )
        | Q(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(event_id),
        )
    )
    locked_policies = list(
        models.RaceLivePublicationPolicy.objects.select_for_update()
        .filter(applicable_policy_filter)
        .order_by("scope_type", "scope_key")
    )
    expected_policy_scopes = {
        (models.RaceLivePublicationScopeType.GLOBAL, "global"),
        (
            models.RaceLivePublicationScopeType.REGION,
            event.country_region,
        ),
        (
            models.RaceLivePublicationScopeType.SOURCE,
            source.source_key,
        ),
        (
            models.RaceLivePublicationScopeType.EVENT,
            str(event_id),
        ),
    }
    if {
        (policy.scope_type, policy.scope_key)
        for policy in locked_policies
    } != expected_policy_scopes:
        _fail("manual evidence policy baseline 缺失")
    try:
        allowlist = (
            models.RaceLiveEventPublicationAllowlist.objects.select_for_update()
            .get(
                event_id=event_id,
                source_key=source.source_key,
            )
        )
    except models.RaceLiveEventPublicationAllowlist.DoesNotExist as exc:
        raise RaceLiveManualOfficialEvidenceError(
            "manual evidence allowlist baseline 缺失"
        ) from exc
    try:
        incident = (
            models.RaceLiveOfficialVerificationIncident.objects.select_for_update()
            .select_related("provisional_revision")
            .get(pk=receipt["incident_id"], event_id=event_id)
        )
    except (
        models.RaceLiveOfficialVerificationIncident.DoesNotExist,
    ) as exc:
        raise RaceLiveManualOfficialEvidenceError(
            "manual evidence database baseline 缺失"
        ) from exc

    observed_at = _aware_datetime(
        receipt["observed_at"],
        "observed_at",
    )
    if (
        event.race_datetime is None
        or timezone.is_naive(event.race_datetime)
        or observed_at < event.race_datetime
        or observed_at > effective_now
    ):
        _fail("manual evidence observed_at 不在赛后已发生窗口")
    if incident.provisional_revision_id != receipt["revision_id"]:
        _fail("receipt revision 与 incident 不匹配")
    if (
        incident.official_route != receipt["route"]
        or incident.official_route_version != receipt["route_version"]
        or incident.official_route_contract_digest
        != receipt["route_contract_digest"]
        or incident.official_terms_evidence_digest
        != receipt["route_terms_digest"]
    ):
        _fail("incident route contract 漂移")
    if (
        receipt["route_registry_digest"] != registry_digest
        or receipt["route_contract_digest"] != registry["contract_digest"]
    ):
        _fail("receipt route registry 漂移")
    if (
        allowlist.enabled is not True
        or allowlist.version != 2
        or allowlist.max_mode
        != models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
        or allowlist.official_verification_route != receipt["route"]
        or allowlist.official_verification_route_version
        != receipt["route_version"]
        or allowlist.official_verification_contract_digest
        != receipt["route_contract_digest"]
        or allowlist.official_terms_evidence_digest
        != receipt["route_terms_digest"]
        or allowlist.official_verification_valid_until is None
        or allowlist.official_verification_valid_until <= effective_now
    ):
        _fail("manual evidence allowlist CAS 漂移")

    existing_log = models.OperationLog.objects.filter(
        action_type="race_live_manual_official_evidence",
        target_type="race_event",
        target_id=str(event_id),
        detail__contains=receipt_sha256,
    ).first()
    if existing_log is not None:
        comparison, replay_errors = _manual_replay_errors(
            receipt=receipt,
            receipt_sha256=receipt_sha256,
            event=event,
            incident=incident,
        )
        if replay_errors:
            _fail(
                "manual evidence replay post-state 漂移："
                + ",".join(replay_errors)
            )
        alert_status = "not_applicable"
        if receipt["outcome"] == "unavailable":
            alert_status = _planned_unavailable_alert_status(
                incident=incident,
            )
        return {
            "event": event,
            "incident": incident,
            "registry": registry,
            "registry_digest": registry_digest,
            "comparison": comparison,
            "alert_status": alert_status,
            "replayed": True,
        }

    if incident.status != models.RaceLiveOfficialVerificationIncidentStatus.OPEN:
        _fail("incident 已不是 open")
    if any(
        policy.mode
        != models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
        or policy.version != 2
        or policy.registry_digest != source.registry_digest
        or policy.coverage_proof_digest != allowlist.coverage_proof_digest
        or policy.valid_until is None
        or policy.valid_until <= effective_now
        for policy in locked_policies
    ):
        _fail("manual evidence policy CAS 漂移")

    alert_status = "not_applicable"
    if receipt["outcome"] == "unavailable":
        comparison = "unavailable"
        alert_status = _planned_unavailable_alert_status(
            incident=incident,
        )
    else:
        comparison = _compare_receipt_to_provisional(
            receipt=receipt,
            incident=incident,
        )
        if comparison == "conflict":
            _validate_disable_plan(
                receipt=receipt,
                disable_manifest=disable_manifest,
            )
    return {
        "event": event,
        "incident": incident,
        "registry": registry,
        "registry_digest": registry_digest,
        "comparison": comparison,
        "alert_status": alert_status,
        "replayed": False,
    }


def dry_run_race_live_manual_official_evidence(
    *,
    receipt: dict[str, Any],
    receipt_sha256: str,
    disable_manifest: LoadedRaceLivePublicationTransition | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    effective_now = now or timezone.now()
    registry, registry_digest = _validate_manual_evidence_action_input(
        receipt=receipt,
        receipt_sha256=receipt_sha256,
        effective_now=effective_now,
    )
    with transaction.atomic():
        plan = _build_manual_evidence_plan_locked(
            receipt=receipt,
            receipt_sha256=receipt_sha256,
            disable_manifest=disable_manifest,
            effective_now=effective_now,
            registry=registry,
            registry_digest=registry_digest,
        )
    return {
        "ok": True,
        "mode": "dry_run",
        "event_ids": [receipt["event_id"]],
        "outcome": receipt["outcome"],
        "comparison": plan["comparison"],
        "alert_status": plan["alert_status"],
        "replayed": plan["replayed"],
        "notification_side_effect_count": 0,
        "network_request_count": 0,
    }


def apply_race_live_manual_official_evidence(
    *,
    receipt: dict[str, Any],
    receipt_sha256: str,
    disable_manifest: LoadedRaceLivePublicationTransition | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    effective_now = now or timezone.now()
    registry, registry_digest = _validate_manual_evidence_action_input(
        receipt=receipt,
        receipt_sha256=receipt_sha256,
        effective_now=effective_now,
    )
    event_id = receipt["event_id"]
    notification_id: int | None = None
    with transaction.atomic():
        plan = _build_manual_evidence_plan_locked(
            receipt=receipt,
            receipt_sha256=receipt_sha256,
            disable_manifest=disable_manifest,
            effective_now=effective_now,
            registry=registry,
            registry_digest=registry_digest,
        )
        event = plan["event"]
        incident = plan["incident"]
        comparison = plan["comparison"]
        alert_status = plan["alert_status"]
        replayed = plan["replayed"]
        if replayed:
            if receipt["outcome"] == "unavailable":
                notification_id, alert_status = (
                    _stage_unavailable_alert_intent_locked(
                        incident=incident,
                        receipt_sha256=receipt_sha256,
                        effective_now=effective_now,
                    )
                )
        else:
            incident.last_probe_at = effective_now
            alert_status = "not_applicable"
            if receipt["outcome"] == "unavailable":
                incident.next_probe_at = effective_now + timedelta(hours=24)
                incident.save(
                    update_fields=(
                        "last_probe_at",
                        "next_probe_at",
                        "updated_at",
                    )
                )
                notification_id, alert_status = (
                    _stage_unavailable_alert_intent_locked(
                        incident=incident,
                        receipt_sha256=receipt_sha256,
                        effective_now=effective_now,
                    )
                )
                comparison = "unavailable"
            else:
                _upsert_official_evidence(
                    receipt=receipt,
                    registry=registry,
                    registry_digest=registry_digest,
                    event=event,
                    incident=incident,
                )
                if comparison == "match":
                    incident.status = (
                        models.RaceLiveOfficialVerificationIncidentStatus.RESOLVED
                    )
                    incident.resolved_at = effective_now
                    incident.next_probe_at = None
                    incident.save(
                        update_fields=(
                            "status",
                            "resolved_at",
                            "last_probe_at",
                            "next_probe_at",
                            "updated_at",
                        )
                    )
                else:
                    assert disable_manifest is not None
                    result = apply_race_live_publication_transition(
                        disable_manifest,
                        now=effective_now,
                    )
                    if result["ok"] is not True:
                        _fail("conflict disable 失败")
                    incident.status = (
                        models.RaceLiveOfficialVerificationIncidentStatus.ESCALATED
                    )
                    incident.next_probe_at = None
                    incident.save(
                        update_fields=(
                            "status",
                            "last_probe_at",
                            "next_probe_at",
                            "updated_at",
                        )
                    )

            # This is deliberately the last main-transaction write. SMTP is
            # attempted only after the intent, probe state, and operation
            # evidence have all committed together.
            models.OperationLog.objects.create(
                action_type="race_live_manual_official_evidence",
                target_type="race_event",
                target_id=str(event_id),
                detail=_manual_log_detail(receipt_sha256, receipt),
            )

    if notification_id is not None:
        alert_status = _deliver_unavailable_alert_intent(
            incident_id=incident.pk,
            notification_id=notification_id,
            effective_now=effective_now,
        )
    return {
        "ok": True,
        "event_ids": [event_id],
        "outcome": receipt["outcome"],
        "comparison": comparison,
        "alert_status": alert_status,
        "replayed": replayed,
        "network_request_count": 0,
    }

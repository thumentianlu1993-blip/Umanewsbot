from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json

from django.db import transaction
from django.db.models import CharField, Exists, OuterRef, Q
from django.db.models.functions import Cast
from django.utils import timezone

from stable import models


_RESULT_SLO = timedelta(minutes=30)


def _resolve_data_sync_event_incidents(*, event_id: int, now: datetime) -> int:
    return models.RaceLiveAlertIncident.objects.filter(
        scope_type="data_sync_event",
        scope_key=str(event_id),
    ).exclude(
        status=models.RaceLiveAlertIncidentStatus.RESOLVED
    ).update(
        status=models.RaceLiveAlertIncidentStatus.RESOLVED,
        resolved_at=now,
        last_seen_at=now,
        next_attempt_at=None,
        delivery_token="",
        delivery_lease_expires_at=None,
        updated_at=now,
    )


def stage_data_sync_result_overdue_alert(
    *, event_id: int, now: datetime, reason_code: str
) -> int | None:
    """Stage one data-sync-owned T+30 incident without dispatching legacy work."""

    if timezone.is_naive(now):
        return None
    enrollment = (
        models.RaceDataSyncEnrollment.objects.select_related("event")
        .filter(
            event_id=event_id,
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
        )
        .first()
    )
    if enrollment is None:
        return None
    event = enrollment.event
    if (
        event.race_datetime is None
        or event.result_confirmed_at is not None
        or event.status
        in {
            models.RaceEventStatus.CANCELLED,
            models.RaceEventStatus.POSTPONED,
        }
        or event.race_datetime + _RESULT_SLO > now
    ):
        if event.result_confirmed_at is not None or event.status in {
            models.RaceEventStatus.CANCELLED,
            models.RaceEventStatus.POSTPONED,
        }:
            _resolve_data_sync_event_incidents(event_id=event.pk, now=now)
        return None
    deadline_at = event.race_datetime + _RESULT_SLO
    reference_version = f"data-sync-t30:{event.race_datetime.isoformat()}"
    details = {
        "event_id": event.pk,
        "region": event.country_region,
        "source_key": enrollment.source_identity.source_key,
        "reason_code": str(reason_code)[:64],
        "deadline_at": deadline_at.isoformat(),
    }
    dedupe_key = hashlib.sha256(
        json.dumps(
            {
                "alert_type": models.RaceLiveAlertType.PROVISIONAL_OVERDUE,
                "scope_type": "data_sync_event",
                "scope_key": str(event.pk),
                "reference_version": reference_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with transaction.atomic():
        incident, created = models.RaceLiveAlertIncident.objects.get_or_create(
            dedupe_key=dedupe_key,
            defaults={
                "alert_type": models.RaceLiveAlertType.PROVISIONAL_OVERDUE,
                "scope_type": "data_sync_event",
                "scope_key": str(event.pk),
                "reference_version": reference_version,
                "status": models.RaceLiveAlertIncidentStatus.OPEN,
                "deadline_at": deadline_at,
                "opened_at": now,
                "last_seen_at": now,
                "next_attempt_at": None,
                "details": details,
            },
        )
        if not created and incident.status not in {
            models.RaceLiveAlertIncidentStatus.SENT,
            models.RaceLiveAlertIncidentStatus.RESOLVED,
        }:
            incident.last_seen_at = now
            incident.details = details
            incident.save(update_fields=("last_seen_at", "details", "updated_at"))
        if incident.status in {
            models.RaceLiveAlertIncidentStatus.SENT,
            models.RaceLiveAlertIncidentStatus.RESOLVED,
        }:
            return None
        return incident.pk


def monitor_data_sync_result_slo(
    *, now: datetime, batch_size: int = 100
) -> tuple[int, ...]:
    if (
        timezone.is_naive(now)
        or isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or batch_size < 1
        or batch_size > 500
    ):
        return ()
    deadline = now - _RESULT_SLO
    active_incidents = models.RaceLiveAlertIncident.objects.filter(
        scope_type="data_sync_event",
    ).exclude(status=models.RaceLiveAlertIncidentStatus.RESOLVED)
    active_incident_for_event = active_incidents.filter(
        scope_key=OuterRef("event_scope_key")
    )
    resolved_event_ids = tuple(
        models.RaceDataSyncEnrollment.objects.filter(
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
        )
        .filter(
            Q(event__result_confirmed_at__isnull=False)
            | Q(
                event__status__in=(
                    models.RaceEventStatus.CANCELLED,
                    models.RaceEventStatus.POSTPONED,
                )
            )
        )
        .annotate(event_scope_key=Cast("event_id", output_field=CharField()))
        .annotate(has_active_incident=Exists(active_incident_for_event))
        .filter(has_active_incident=True)
        .order_by("event_id")
        .values_list("event_id", flat=True)
        [:batch_size]
    )
    for event_id in resolved_event_ids:
        _resolve_data_sync_event_incidents(event_id=event_id, now=now)
    event_ids = tuple(
        models.RaceDataSyncEnrollment.objects.filter(
            state=models.RaceDataSyncEnrollmentState.ENROLLED,
            event__race_datetime__isnull=False,
            event__race_datetime__lte=deadline,
            event__result_confirmed_at__isnull=True,
        )
        .exclude(
            event__status__in=(
                models.RaceEventStatus.CANCELLED,
                models.RaceEventStatus.POSTPONED,
            )
        )
        .annotate(event_scope_key=Cast("event_id", output_field=CharField()))
        .annotate(has_active_incident=Exists(active_incident_for_event))
        .filter(has_active_incident=False)
        .order_by("event__race_datetime", "event_id")
        .values_list("event_id", flat=True)[:batch_size]
    )
    staged = []
    for event_id in event_ids:
        incident_id = stage_data_sync_result_overdue_alert(
            event_id=event_id,
            now=now,
            reason_code="result_not_confirmed_by_t30",
        )
        if incident_id is not None:
            staged.append(incident_id)
    return tuple(staged)


def stage_multisource_coverage_incidents(*, coverage, policy, now):
    """仅持久后台缺口，无发送任务；退出七天窗口也不自动 resolve。"""
    from zoneinfo import ZoneInfo
    from stable.services.race_data_source_adapters import canonical_sha
    from django.conf import settings

    if not getattr(settings, "RACE_DATA_COVERAGE_ALERTS_ENABLED", False):
        return
    for row in coverage["entries"]:
        event = models.RaceEvent.objects.get(pk=row["event_id"])
        if row["classification"] in (
            "unsupported_region",
            "manual_pause",
            "owner_conflict",
        ):
            continue
        issue = ""
        if event.result_confirmed_at:
            models.RaceLiveAlertIncident.objects.filter(
                scope_type="multisource_coverage", scope_key=str(event.pk)
            ).exclude(status="resolved").update(
                status="resolved", resolved_at=now, last_seen_at=now
            )
            continue
        if event.status in ("cancelled", "postponed"):
            models.RaceLiveAlertIncident.objects.filter(
                scope_type="multisource_coverage", scope_key=str(event.pk)
            ).exclude(status="resolved").update(
                status="resolved", resolved_at=now, last_seen_at=now
            )
            continue
        # 缺失日历信息不能证明原告警已解决，也不能阻塞其他赛事。
        # 确认赛果/取消等明确终态已在上方处理。
        if row["classification"] in ("missing_date", "missing_timezone"):
            continue
        try:
            age = (
                (
                    now.astimezone(ZoneInfo(event.timezone_name)).date()
                    - event.local_date
                ).days
                if event.local_date
                else None
            )
        except (ValueError, KeyError):
            # census 后字段可能被并发修改；未知状态仍保留原 incident。
            continue
        if event.race_datetime and now >= event.race_datetime + timedelta(minutes=30):
            issue = "result_overdue"
        elif age is not None and age >= 1 and event.race_datetime is None:
            issue = "time_unknown_overdue"
        elif (
            age is not None
            and age >= -1
            and row["classification"] == "enrollment_missing"
        ):
            issue = "enrollment_missing"
        stale = models.RaceLiveAlertIncident.objects.filter(
            scope_type="multisource_coverage", scope_key=str(event.pk)
        ).exclude(status="resolved")
        for previous in stale:
            if previous.details.get("issue") != issue:
                previous.status = "resolved"
                previous.resolved_at = now
                previous.last_seen_at = now
                previous.save(
                    update_fields=(
                        "status",
                        "resolved_at",
                        "last_seen_at",
                        "updated_at",
                    )
                )
        if not issue:
            continue
        key = canonical_sha(
            dict(event_id=event.pk, issue=issue, policy=policy.payload["policy_id"])
        )
        incident, created = models.RaceLiveAlertIncident.objects.get_or_create(
            dedupe_key=key,
            defaults=dict(
                alert_type="official_overdue",
                scope_type="multisource_coverage",
                scope_key=str(event.pk),
                reference_version=policy.payload["policy_id"],
                opened_at=now,
                last_seen_at=now,
                next_attempt_at=None,
                details={
                    "issue": issue,
                    "classification": row["classification"],
                    "policy_digest": policy.digest,
                },
            ),
        )
        if not created:
            incident.last_seen_at = now
            incident.save(update_fields=("last_seen_at", "updated_at"))

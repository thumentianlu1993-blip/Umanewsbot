"""公开赛事全覆盖诊断；不授予抓取权限、不修改比赛事实。"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
import hashlib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.db import connection, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.urls import reverse

from stable import models
from stable.services.race_data_sync_admission import (
    validate_data_sync_lifecycle_admission,
)
from stable.services.race_events import (
    claim_race_live_alert_delivery,
    complete_race_live_alert_delivery,
    resolve_race_live_public_read,
)

CHECK_INTERVAL = timedelta(minutes=5)
EVENT_SCOPES = ("data_sync_event", "multisource_coverage")


def _iso(value):
    return value.isoformat() if value else None


def build_public_race_coverage(*, now, event_ids=None):
    """所有公开 canonical 赛事守恒分类，历史资料和抓取准入分别判断。"""
    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    duplicates = models.RaceEventProductCanonicalLink.objects.filter(
        is_active=True
    ).values("duplicate_event_id")
    confirmed = models.RaceEventResult.objects.filter(
        event_id=OuterRef("pk"), is_confirmed=True
    )
    unconfirmed = models.RaceEventResult.objects.filter(
        event_id=OuterRef("pk"), is_confirmed=False
    )
    events = (
        models.RaceEvent.objects.filter(visibility_status="published")
        .exclude(pk__in=duplicates)
        .annotate(
            has_confirmed_rows=Exists(confirmed),
            has_unconfirmed_rows=Exists(unconfirmed),
        )
        .select_related(
            "race_data_sync_enrollment__source_identity",
            "live_tracking",
            "lifecycle_control",
            "projection_control",
        )
        .only(
            "id",
            "chinese_name",
            "original_name",
            "country_region",
            "local_date",
            "race_datetime",
            "timezone_name",
            "status",
            "manual_lock_flags",
            "result_confirmed_at",
            "race_data_sync_enrollment",
            "live_tracking",
            "lifecycle_control",
            "projection_control",
        )
    )
    if event_ids is not None:
        events = events.filter(pk__in=event_ids)
    rows = []
    for event in events.order_by("pk").iterator(chunk_size=200):
        enrollment = getattr(event, "race_data_sync_enrollment", None)
        tracking = getattr(event, "live_tracking", None)
        lifecycle = getattr(event, "lifecycle_control", None)
        projection = getattr(event, "projection_control", None)
        row = dict(
            event_id=event.pk,
            event_name=event.chinese_name or event.original_name,
            region=event.country_region,
            local_date=str(event.local_date or ""),
            classification="",
            issue="",
            reason_code="",
            next_action="",
            next_check_at=_iso(now + CHECK_INTERVAL),
            next_poll_at=_iso(tracking.next_poll_at) if tracking else None,
            last_attempt_at=_iso(tracking.last_attempt_at) if tracking else None,
        )
        # 既有历史导入可有 confirmed canonical rows 而没有 live 确认时间。
        # data-sync 自有投影仍要求其正式确认字段，不能用零散行绕过发布门禁。
        live_owned = projection and projection.write_owner == "data_sync"
        if not event.has_unconfirmed_rows and (
            event.result_confirmed_at or (event.has_confirmed_rows and not live_owned)
        ):
            row.update(
                classification="confirmed",
                next_action="已确认结果；保留既有更正复核安排",
            )
            if projection and projection.write_owner in ("data_sync", "live"):
                public = resolve_race_live_public_read(event_id=event.pk, now=now)
                if not public.visible:
                    row.update(
                        classification="publication_blocked",
                        issue="publication_blocked",
                        reason_code=public.reason,
                        next_action="核验历史发布依据与当前公开门禁；保留现有赛果和证据，不绕过权限",
                    )
        elif event.status in ("cancelled", "postponed"):
            row.update(
                classification=event.status,
                next_action="保留取消/延期记录，等待明确赛程变更",
            )
        elif any((event.manual_lock_flags or {}).values()) or (
            lifecycle and lifecycle.manual_pause_reason
        ):
            row.update(
                classification="manual_pause",
                next_action="由运营核验人工暂停原因；监控不解除锁",
            )
        elif projection and projection.write_owner not in ("unmanaged", "data_sync"):
            row.update(
                classification="owner_conflict",
                issue="owner_conflict",
                next_action="由运营核对现有写入者；不自动抢占",
            )
        elif not event.local_date:
            row.update(
                classification="missing_date",
                issue="missing_date",
                next_action="运营核验赛历并补齐举办日期",
            )
        else:
            try:
                age = (
                    now.astimezone(ZoneInfo(event.timezone_name)).date()
                    - event.local_date
                ).days
            except (ValueError, ZoneInfoNotFoundError, TypeError):
                row.update(
                    classification="missing_timezone",
                    issue="missing_timezone",
                    next_action="运营核验举办地时区；不推测开赛时间",
                )
            else:
                if age < -4:
                    row.update(
                        classification="awaiting_source_window",
                        next_action="等待举办地 D−4 赛前资料窗口；继续覆盖检查",
                    )
                elif enrollment and enrollment.state == "enrolled":
                    admission = validate_data_sync_lifecycle_admission(
                        event_id=event.pk, now=now, lock=False
                    )
                    source = enrollment.source_identity
                    row["source_key"] = source.source_key
                    row["source_valid_until"] = _iso(source.valid_until)
                    if not admission.admitted:
                        row.update(
                            classification="admission_blocked",
                            issue="admission_blocked",
                            reason_code=admission.reason_code,
                            next_action="运营核验来源身份、有效期和策略，按受审修复路径恢复；不直接延长权限",
                        )
                    else:
                        row.update(
                            classification="enrolled",
                            next_action="继续既有授权内的资料刷新",
                        )
                        if (
                            not tracking
                            or not tracking.tracking_enabled
                            or not tracking.next_poll_at
                        ):
                            row.update(
                                issue="no_next_poll",
                                next_action="核验轮询停止原因，移交补采或恢复现有授权调度",
                            )
                        elif tracking.next_poll_at < now - timedelta(minutes=30):
                            row.update(
                                issue="poll_stalled",
                                next_action="检查任务、租约及来源错误，恢复已授权调度",
                            )
                else:
                    row.update(
                        classification="enrollment_missing",
                        next_action="等待来源身份发现；无可用来源时由运营安排补采",
                    )
                    if age >= -1:
                        row["issue"] = "enrollment_missing"
                # 时间/结果缺口独立于来源原因；后者保留在 reason_code。
                if not row["reason_code"]:
                    row["reason_code"] = row["issue"] or row["classification"]
                if event.race_datetime and now >= event.race_datetime + timedelta(
                    minutes=30
                ):
                    row["issue"] = "result_overdue"
                    row["next_action"] = (
                        "核验正式完整结果并补采；若来源受阻，先处理所列阻断原因"
                    )
                elif (
                    event.race_datetime
                    and event.status == "scheduled"
                    and now >= event.race_datetime + timedelta(minutes=5)
                ):
                    row["issue"] = "lifecycle_not_advanced"
                elif not event.race_datetime and age >= 1:
                    row["issue"] = "time_unknown_overdue"
                    row["next_action"] = (
                        "运营核验实际赛程与完整赛果；不能按日期自动确认完赛"
                    )
        if not row["reason_code"]:
            row["reason_code"] = row["issue"] or row["classification"]
        rows.append(row)
    return dict(
        as_of=_iso(now),
        total=len(rows),
        counts=dict(Counter(r["classification"] for r in rows)),
        issue_counts=dict(Counter(r["issue"] for r in rows if r["issue"])),
        entries=rows,
    )


def _resolve(queryset, now):
    return queryset.exclude(status="resolved").update(
        status="resolved",
        resolved_at=now,
        last_seen_at=now,
        next_attempt_at=None,
        delivery_token="",
        delivery_lease_expires_at=None,
        updated_at=now,
    )


@transaction.atomic
def reconcile_public_race_coverage(*, now):
    """仅持久缺口；旧事件告警复用，离窗不消失，撤回/合并/恢复可收敛。"""
    # 监控并发只争一把事务锁；不持有业务行锁，不与比赛写入者抢 owner。
    # PostgreSQL 事务结束自动释放，worker 崩溃不会留下人工清理的锁。
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [714020261002])
            if not cursor.fetchone()[0]:
                return {
                    "total": 0,
                    "counts": {},
                    "issue_counts": {},
                    "entries": [],
                    "skipped": "monitor_busy",
                }
    report = build_public_race_coverage(now=now)
    if not getattr(settings, "RACE_DATA_COVERAGE_ALERTS_ENABLED", False):
        return report
    active_ids = []
    for row in report["entries"]:
        if not row["issue"]:
            continue
        with transaction.atomic():
            candidates = (
                models.RaceLiveAlertIncident.objects.select_for_update().filter(
                    scope_type__in=EVENT_SCOPES, scope_key=str(row["event_id"])
                )
            )
            incident = (
                candidates.filter(scope_type="data_sync_event").order_by("pk").first()
            )
            if incident is None:
                key = hashlib.sha256(
                    f"public-coverage:{row['event_id']}".encode()
                ).hexdigest()
                incident, _ = models.RaceLiveAlertIncident.objects.get_or_create(
                    dedupe_key=key,
                    defaults=dict(
                        alert_type="official_overdue",
                        scope_type="data_sync_event",
                        scope_key=str(row["event_id"]),
                        opened_at=now,
                    ),
                )
                incident = models.RaceLiveAlertIncident.objects.select_for_update().get(
                    pk=incident.pk
                )
            changed = (incident.details or {}).get("issue") not in (None, row["issue"])
            if incident.status == "resolved" or changed:
                incident.status = "open"
                incident.opened_at = now
                incident.resolved_at = None
                incident.alert_sent_at = None
                incident.delivery_attempts = 0
                incident.next_attempt_at = None
                incident.delivery_token = ""
                incident.delivery_lease_expires_at = None
            incident.details = row
            incident.last_seen_at = now
            incident.save()
            active_ids.append(incident.pk)
            _resolve(candidates.exclude(pk=incident.pk), now)
    _resolve(
        models.RaceLiveAlertIncident.objects.filter(
            scope_type__in=EVENT_SCOPES
        ).exclude(pk__in=active_ids),
        now,
    )
    return report


def deliver_coverage_digest(*, now):
    """一个全局发送租约；汇总新缺口，成功回执不覆盖并发恢复或重开。

    SMTP 接收后进程崩溃仍可能重投（at-least-once）；不声称端到端 exactly-once。
    """
    if not getattr(settings, "RACE_DATA_COVERAGE_ALERTS_ENABLED", False):
        return {"delivered": False, "reason": "disabled"}
    key = hashlib.sha256(b"public-race-coverage-digest-v1").hexdigest()
    with transaction.atomic():
        digest, _ = models.RaceLiveAlertIncident.objects.get_or_create(
            dedupe_key=key,
            defaults=dict(
                alert_type="source_failures",
                scope_type="data_sync_digest",
                scope_key="public_calendar",
                opened_at=now,
            ),
        )
        digest = models.RaceLiveAlertIncident.objects.select_for_update().get(
            pk=digest.pk
        )
        if (
            digest.status == "sending"
            and digest.delivery_lease_expires_at
            and digest.delivery_lease_expires_at > now
        ):
            return {"delivered": False, "reason": "delivery_lease_active"}
        pending = list(
            models.RaceLiveAlertIncident.objects.filter(
                scope_type__in=("data_sync_event", "multisource_policy"),
                status__in=("open", "failed"),
                alert_sent_at__isnull=True,
            ).order_by("pk")
        )
        if not pending:
            return {"delivered": False, "reason": "no_new_gaps"}
        # 新增事件最多每 15 分钟发一封；失败沿原退避重试。
        if digest.alert_sent_at and digest.alert_sent_at > now - timedelta(minutes=15):
            return {"delivered": False, "reason": "digest_throttled"}
        if digest.status in ("sent", "resolved") or (
            digest.delivery_attempts >= 4
            and digest.updated_at <= now - timedelta(hours=6)
        ):
            digest.status = "open"
            digest.delivery_attempts = 0
            digest.next_attempt_at = None
        digest.details = {
            "count": len(pending),
            "incident_ids": [p.pk for p in pending],
        }
        digest.save(
            update_fields=("status", "delivery_attempts", "next_attempt_at", "details")
        )
        claim = claim_race_live_alert_delivery(
            incident_id=digest.pk, now=now, lease_seconds=300
        )
        if not claim.claimed:
            return {"delivered": False, "reason": claim.reason}
    recipients = list(getattr(settings, "RACE_LIVE_ALERT_NOTIFY_EMAILS", ()) or ())
    counts = Counter((p.details or {}).get("issue", "unknown") for p in pending)
    site = str(getattr(settings, "SITE_URL", "https://umafans.run")).rstrip("/")
    lines = [
        f"新增或重新出现的赛事资料缺口：{len(pending)} 项",
        f"分类：{dict(counts)}",
        f"全部缺口与下一步：{site}{reverse('admin:stable_raceevent_coverage')}",
        "",
    ]
    for item in pending[:30]:
        details = item.details or {}
        lines.append(
            f"{details.get('event_name', item.scope_key)} ({item.scope_key})："
            f"{details.get('issue', item.alert_type)} / {details.get('reason_code', '')}\n"
            f"下一步：{details.get('next_action', '检查来源策略并恢复授权配置')}"
        )
    if len(pending) > 30:
        lines.append(f"其余 {len(pending)-30} 项请在后台查看。")
    delivered, error = False, "recipients_missing"
    if recipients:
        try:
            delivered = (
                send_mail(
                    f"[UmaFans] 赛事覆盖告警汇总：{len(pending)} 项",
                    "\n".join(lines),
                    settings.DEFAULT_FROM_EMAIL,
                    recipients,
                    fail_silently=False,
                    connection=get_connection(timeout=30),
                )
                == 1
            )
            error = "" if delivered else "smtp_zero_deliveries"
        except Exception:
            error = "smtp_delivery_failed"
    with transaction.atomic():
        completion = complete_race_live_alert_delivery(
            incident_id=digest.pk,
            delivery_token=claim.delivery_token,
            now=now,
            delivered=delivered,
            error_code=error,
        )
        if delivered and completion.applied:
            for item in pending:
                models.RaceLiveAlertIncident.objects.filter(
                    pk=item.pk,
                    status__in=("open", "failed"),
                    opened_at=item.opened_at,
                    alert_sent_at__isnull=True,
                ).update(
                    status="sent",
                    alert_sent_at=now,
                    last_error_code="",
                    next_attempt_at=None,
                    updated_at=now,
                )
    return {
        "delivered": delivered and completion.applied,
        "reason": completion.reason,
        "count": len(pending),
    }

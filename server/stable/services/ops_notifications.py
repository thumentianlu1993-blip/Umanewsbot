from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from stable.models import NotificationChannel, NotificationLog, NotificationStatus, NotificationType
from stable.services.internal_controls import sanitize_internal_ops_notification
from stable.services.onebot import BotPusher


def send_ops_notification(*, notification_type: str, title: str, payload: dict) -> list[NotificationLog]:
    if (
        not getattr(settings, "MULTIREGION_OPS_NOTIFICATIONS_ENABLED", False)
        or getattr(settings, "MULTIREGION_ROLLBACK_DISABLE_OPS_NOTIFICATIONS", False)
    ):
        return []
    safe_title = title
    if getattr(settings, "SITE_INTERNAL_ONLY_ENABLED", True):
        payload = sanitize_internal_ops_notification(payload)
        if payload is None:
            return []
        safe_title = str(payload.get("task") or notification_type)
    cooldown_minutes = int(getattr(settings, "MULTIREGION_OPS_NOTIFICATION_COOLDOWN_MINUTES", 30))
    cooldown_since = timezone.now() - timedelta(minutes=cooldown_minutes)
    signature = f"{notification_type}:{safe_title}"
    if NotificationLog.objects.filter(
        type=notification_type,
        payload_summary__icontains=signature,
        created_at__gte=cooldown_since,
    ).exists():
        return []

    logs: list[NotificationLog] = []
    summary = f"{signature}\n{json.dumps(payload, ensure_ascii=False, default=str)[:1800]}"
    qq_group_id = (getattr(settings, "MULTIREGION_OPS_NOTIFICATION_QQ_GROUP_ID", "") or "").strip()
    if qq_group_id:
        log = NotificationLog.objects.create(
            type=notification_type,
            channel=NotificationChannel.QQ,
            target=qq_group_id,
            status=NotificationStatus.QUEUED,
            payload_summary=summary,
        )
        try:
            BotPusher().send_group_message(qq_group_id, f"{safe_title}\n{summary}")
            log.status = NotificationStatus.SENT
            log.sent_at = timezone.now()
        except Exception as exc:
            log.status = NotificationStatus.FAILED
            log.error_message = str(exc)[:2000]
        log.save(update_fields=["status", "sent_at", "error_message", "updated_at"])
        logs.append(log)

    emails = list(getattr(settings, "MULTIREGION_OPS_NOTIFICATION_EMAILS", []))
    if emails:
        log = NotificationLog.objects.create(
            type=notification_type,
            channel=NotificationChannel.EMAIL,
            target=",".join(emails),
            status=NotificationStatus.QUEUED,
            payload_summary=summary,
        )
        try:
            send_mail(
                safe_title,
                summary,
                settings.DEFAULT_FROM_EMAIL,
                emails,
                fail_silently=False,
            )
            log.status = NotificationStatus.SENT
            log.sent_at = timezone.now()
        except Exception as exc:
            log.status = NotificationStatus.FAILED
            log.error_message = str(exc)[:2000]
        log.save(update_fields=["status", "sent_at", "error_message", "updated_at"])
        logs.append(log)

    return logs


def send_production_summary_notification(payload: dict) -> list[NotificationLog]:
    return send_ops_notification(
        notification_type=NotificationType.OPS_SUMMARY,
        title="UmaFans 多地区生产摘要",
        payload=payload,
    )

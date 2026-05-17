from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from stable.models import NotificationChannel, NotificationLog, NotificationStatus, NotificationType


def _payload_summary(payload: dict) -> str:
    title = payload.get("title") or payload.get("source") or payload.get("task") or payload.get("type") or "自动化通知"
    parts = [str(title)]
    if payload.get("article_id"):
        parts.append(f"article_id={payload['article_id']}")
    if payload.get("decision_summary"):
        parts.append(str(payload["decision_summary"]))
    if payload.get("error"):
        parts.append(str(payload["error"]))
    return " | ".join(parts)[:1000]


def _subject(notification_type: str) -> str:
    label = dict(NotificationType.choices).get(notification_type, notification_type)
    return f"[Umanewsbot] {label}"


def _email_body(notification_type: str, payload: dict) -> str:
    lines = [_subject(notification_type), ""]
    for key, value in payload.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def send_automation_notification(notification_type: str, payload: dict, channels: list[str] | None = None) -> list[NotificationLog]:
    channels = channels or [NotificationChannel.EMAIL, NotificationChannel.SMS, NotificationChannel.QQ, NotificationChannel.WECHAT]
    logs: list[NotificationLog] = []
    summary = _payload_summary({"type": notification_type, **payload})
    for channel in channels:
        target = ""
        status = NotificationStatus.SKIPPED
        error_message = ""
        sent_at = None
        try:
            if channel == NotificationChannel.EMAIL:
                recipients = list(getattr(settings, "AUTOMATION_NOTIFY_EMAILS", []) or [])
                target = ",".join(recipients)
                if not getattr(settings, "AUTOMATION_ENABLE_EMAIL", False) or not recipients:
                    status = NotificationStatus.SKIPPED
                    error_message = "邮件通知未启用或未配置收件人"
                else:
                    send_mail(
                        _subject(notification_type),
                        _email_body(notification_type, payload),
                        settings.DEFAULT_FROM_EMAIL,
                        recipients,
                        fail_silently=False,
                    )
                    status = NotificationStatus.SENT
                    sent_at = timezone.now()
            else:
                target = channel
                status = NotificationStatus.SKIPPED
                error_message = "该通知渠道已预留，当前 MVP 暂未接入真实发送"
        except Exception as exc:
            status = NotificationStatus.FAILED
            error_message = str(exc)
        logs.append(
            NotificationLog.objects.create(
                type=notification_type,
                channel=channel,
                target=target,
                status=status,
                payload_summary=summary,
                error_message=error_message,
                sent_at=sent_at,
            )
        )
    return logs

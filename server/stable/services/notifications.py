from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from stable.models import NewsArticle, NotificationChannel, NotificationLog, NotificationStatus, NotificationType
from stable.services.automation import is_high_value_article
from stable.services.validation import SEVERITY_BLOCKER, SEVERITY_WARNING, warning_signature


def _payload_summary(payload: dict) -> str:
    title = payload.get("title") or payload.get("source") or payload.get("task") or payload.get("type") or "自动化通知"
    parts = [str(title)]
    if payload.get("article_id"):
        parts.append(f"article_id={payload['article_id']}")
    if payload.get("decision_summary"):
        parts.append(str(payload["decision_summary"]))
    if payload.get("error"):
        parts.append(str(payload["error"]))
    if payload.get("reason"):
        parts.append(f"reason={payload['reason']}")
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


def _warning_payload(article: NewsArticle, warnings: list[dict]) -> dict:
    site_url = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    candidate_path = f"/admin/candidates/{article.id}/"
    return {
        "article_id": article.id,
        "title": article.effective_title,
        "candidate_url": f"{site_url}{candidate_path}" if site_url else candidate_path,
        "source_url": article.source_url,
        "source": f"{article.source_site}:{article.source_mode}",
        "score_total": article.score_total,
        "workflow_status": article.workflow_status,
        "automation_status": article.automation_status,
        "warnings": "；".join(issue.get("message", "") for issue in warnings),
    }


def send_high_value_warning_notification(article: NewsArticle) -> list[NotificationLog]:
    issues = article.gate_issues or []
    warnings = [issue for issue in issues if issue.get("severity") == SEVERITY_WARNING]
    blockers = [issue for issue in issues if issue.get("severity") == SEVERITY_BLOCKER]
    if not warnings or blockers or not is_high_value_article(article):
        return []

    signature = warning_signature(issues)
    dedup_hours = int(getattr(settings, "AUTOMATION_WARNING_EMAIL_DEDUP_HOURS", 24))
    now = timezone.now()
    if (
        article.automation_warning_email_signature == signature
        and article.automation_warning_email_sent_at
        and article.automation_warning_email_sent_at >= now - timedelta(hours=dedup_hours)
    ):
        return [
            NotificationLog.objects.create(
                type=NotificationType.HIGH_VALUE_WARNING,
                channel=NotificationChannel.EMAIL,
                target="",
                status=NotificationStatus.SKIPPED,
                payload_summary=_payload_summary(_warning_payload(article, warnings)),
                error_message="同一文章同一 warning 组合仍在去重窗口内",
            )
        ]

    recipients = list(getattr(settings, "AUTOMATION_WARNING_NOTIFY_EMAILS", []) or [])
    payload = _warning_payload(article, warnings)
    target = ",".join(recipients)
    if not getattr(settings, "AUTOMATION_WARNING_EMAIL_ENABLED", True) or not recipients:
        return [
            NotificationLog.objects.create(
                type=NotificationType.HIGH_VALUE_WARNING,
                channel=NotificationChannel.EMAIL,
                target=target,
                status=NotificationStatus.SKIPPED,
                payload_summary=_payload_summary(payload),
                error_message="高价值 warning 邮件未启用或未配置收件人",
            )
        ]

    try:
        send_mail(
            _subject(NotificationType.HIGH_VALUE_WARNING),
            _email_body(NotificationType.HIGH_VALUE_WARNING, payload),
            settings.DEFAULT_FROM_EMAIL,
            recipients,
            fail_silently=False,
        )
        article.automation_warning_email_signature = signature
        article.automation_warning_email_sent_at = now
        article.save(update_fields=["automation_warning_email_signature", "automation_warning_email_sent_at", "updated_at"])
        status = NotificationStatus.SENT
        error_message = ""
        sent_at = now
    except Exception as exc:
        status = NotificationStatus.FAILED
        error_message = str(exc)
        sent_at = None
    return [
        NotificationLog.objects.create(
            type=NotificationType.HIGH_VALUE_WARNING,
            channel=NotificationChannel.EMAIL,
            target=target,
            status=status,
            payload_summary=_payload_summary(payload),
            error_message=error_message,
            sent_at=sent_at,
        )
    ]

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.utils import timezone

from stable.models import ArticleStatus, NewsArticle, PushLog, PushStatus, PushTarget

from .onebot import BotPusher, qq_channel_enabled, QQChannelDisabled


User = get_user_model()


def build_push_message(article: NewsArticle) -> tuple[str, str | None]:
    lines = [
        article.effective_title,
        f"发布时间：{article.published_at:%Y-%m-%d %H:%M}",
        f"来源：{article.get_source_site_display()} / {article.get_source_mode_display()}",
    ]
    summary = article.effective_summary
    if summary:
        lines.extend(["", summary])
    lines.extend(["", f"原文链接：{article.source_url}"])
    image_url = article.cover_image_url or (article.main_image.public_url if article.main_image else None)
    return "\n".join(lines), image_url


def push_article_to_targets(article: NewsArticle, targets: list[PushTarget], user: User | None = None) -> list[PushLog]:
    if not qq_channel_enabled():
        return []
    pusher = BotPusher()
    logs: list[PushLog] = []
    message, image_url = build_push_message(article)
    for target in targets:
        if not qq_channel_enabled():
            break
        try:
            response = pusher.send_group_message(target.group_id, message, image_url=image_url)
            outcome = dict(status=PushStatus.SUCCESS, response_payload=response, sent_at=timezone.now())
            article.status = ArticleStatus.PUSHED
        except QQChannelDisabled:
            break
        except Exception as exc:
            outcome = dict(status=PushStatus.FAILED, error_message=str(exc))
            article.status = ArticleStatus.PUSH_FAILED
        # 停用不是发送失败；仅实际发送返回成功/失败后写本次投递日志。
        logs.append(PushLog.objects.create(
            article=article, target=target, triggered_by=user,
            request_payload={"message": message, "image_url": image_url}, **outcome))
    if logs:
        article.save(update_fields=["status", "updated_at"])
    return logs


def enqueue_push_for_article(article: NewsArticle, targets: list[PushTarget], user: User | None = None) -> None:
    if not qq_channel_enabled():
        return
    from stable.tasks import push_article_task

    push_article_task.delay(article.id, [target.id for target in targets], user.id if user else None)

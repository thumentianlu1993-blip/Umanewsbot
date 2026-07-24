from __future__ import annotations

import logging

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from stable.models import HistoricalRaceEventTarget, NewsArticle, RaceEvent
from stable.services.operations import log_operation
from stable.services.race_event_public_cache import invalidate_public_race_cache

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def _handle_login(sender, request, user, **kwargs):
    log_operation(
        action_type="login_success",
        target_type="auth",
        target_id=user.pk,
        detail=f"用户 {user.get_username()} 登录成功",
        admin=user,
    )


@receiver(user_logged_out)
def _handle_logout(sender, request, user, **kwargs):
    if user is None:
        return
    log_operation(
        action_type="logout",
        target_type="auth",
        target_id=user.pk,
        detail=f"用户 {user.get_username()} 退出登录",
        admin=user,
    )


@receiver(user_login_failed)
def _handle_login_failed(sender, credentials, request, **kwargs):
    username = credentials.get("username", "")
    log_operation(
        action_type="login_failed",
        target_type="auth",
        target_id="",
        detail=f"登录失败: {username}",
        admin=None,
    )


@receiver([post_save, post_delete], sender=RaceEvent)
@receiver([post_save, post_delete], sender=HistoricalRaceEventTarget)
def _invalidate_public_race_cache(sender, **kwargs):
    invalidate_public_race_cache()


# ---------------------------------------------------------------------------
# Editorial headline invalidation signals
# ---------------------------------------------------------------------------


@receiver(post_save, sender=NewsArticle)
def _invalidate_headline_on_article_change(sender, instance, **kwargs):
    """When an article is saved, after the transaction commits, check if it
    invalidates the current headline selection or active recommendation."""
    from django.db import transaction as db_transaction
    db_transaction.on_commit(
        lambda: _invalidate_headline_for_article(instance.id)
    )


def _invalidate_headline_for_article(article_id: int):
    from stable.services.editorial_headlines import (
        invalidate_headline_state_for_article,
    )

    try:
        invalidate_headline_state_for_article(
            article_id, reason="article_became_ineligible"
        )
    except Exception:
        logger.exception(
            "headline invalidation failed for article_id=%s",
            article_id,
        )
        # Guard the audit write itself — if the database is unavailable
        # we must not propagate a second failure from on_commit.
        try:
            log_operation(
                action_type="signal_error",
                target_type="headline",
                target_id=str(article_id),
                detail=f"headline invalidation failed for article_id={article_id}",
                admin=None,
            )
        except Exception:
            logger.exception(
                "failed to persist signal_error audit for article_id=%s",
                article_id,
            )


@receiver(pre_delete, sender=NewsArticle)
def _invalidate_headline_on_article_delete(sender, instance, **kwargs):
    """Within the delete transaction, clear headline state pointing
    to this article before the FK is SET NULL."""
    from stable.models import HomepageHeadlineSelection, HomepageHeadlineRecommendation

    try:
        selection = (
            HomepageHeadlineSelection.objects.select_for_update()
            .filter(article_id=instance.id)
            .first()
        )
        if selection:
            selection.article = None
            selection.selected_by = None
            selection.selected_at = None
            selection.version = selection.version + 1
            selection.save()
            log_operation(
                action_type="headline_invalidated",
                target_type="headline_selection",
                target_id=str(selection.pk),
                detail=f"article_deleted: article_id={instance.id}, version={selection.version}",
                admin=None,
            )

        active_recs = (
            HomepageHeadlineRecommendation.objects.select_for_update()
            .filter(
                article_id=instance.id,
                status=HomepageHeadlineRecommendation.Status.ACTIVE,
            )
        )
        for rec in active_recs:
            rec.status = HomepageHeadlineRecommendation.Status.INVALIDATED
            rec.save()
            log_operation(
                action_type="headline_recommendation_invalidated",
                target_type="headline_recommendation",
                target_id=str(rec.pk),
                detail=(
                    f"article_deleted: article_id={instance.id}, "
                    f"recommendation_id={rec.pk}"
                ),
                admin=None,
            )
    except Exception:
        logger.exception(
            "headline invalidation on delete failed for article_id=%s",
            instance.id,
        )
        try:
            log_operation(
                action_type="signal_error",
                target_type="headline",
                target_id=str(instance.id),
                detail=(
                    "headline invalidation on delete failed for "
                    f"article_id={instance.id}"
                ),
                admin=None,
            )
        except Exception:
            logger.exception(
                "failed to persist signal_error audit on delete for article_id=%s",
                instance.id,
            )

from __future__ import annotations

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from stable.models import HistoricalRaceEventTarget, RaceEvent
from stable.services.operations import log_operation
from stable.services.race_event_public_cache import invalidate_public_race_cache


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

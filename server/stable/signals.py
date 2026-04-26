from __future__ import annotations

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from stable.services.operations import log_operation


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

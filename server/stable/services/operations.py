from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model

from stable.models import OperationLog


User = get_user_model()


def log_operation(
    *,
    action_type: str,
    target_type: str,
    target_id: Any = "",
    detail: str = "",
    admin: User | None = None,
) -> OperationLog:
    return OperationLog.objects.create(
        admin=admin,
        action_type=action_type,
        target_type=target_type,
        target_id=str(target_id or ""),
        detail=detail,
    )

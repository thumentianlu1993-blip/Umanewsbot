from __future__ import annotations

from django.conf import settings
from kombu.exceptions import OperationalError


def dispatch_task(task, *args, **kwargs):
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return task.run(*args, **kwargs)
    try:
        return task.delay(*args, **kwargs)
    except (OperationalError, ConnectionError):
        return task.run(*args, **kwargs)

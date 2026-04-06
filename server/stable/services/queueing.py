from __future__ import annotations

from kombu.exceptions import OperationalError


def dispatch_task(task, *args, **kwargs):
    try:
        return task.delay(*args, **kwargs)
    except (OperationalError, ConnectionError):
        return task.apply(args=args, kwargs=kwargs)

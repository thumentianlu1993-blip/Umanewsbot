"""P02短时只读探针专用设置；正常服务继续使用app.settings。"""

from .settings import *  # noqa: F403

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

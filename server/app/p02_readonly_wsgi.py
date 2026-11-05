"""仅供关闭态发布探针：屏蔽管理与写入口，使用只读DB和进程内缓存。"""

import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
from django.core.wsgi import get_wsgi_application
from django.db import connection
from stable.services.release_p02_executor import assert_closed_settings
from stable.services.release_p02_recovery import hex_value

django_application = get_wsgi_application()


def readonly_application(environ, start_response, *, delegate=django_application):
    if environ.get("REQUEST_METHOD") not in {"GET", "HEAD"} or environ.get("PATH_INFO") not in {"/healthz/", "/races/"}:
        start_response("503 Service Unavailable", [("Content-Type", "text/plain"), ("Cache-Control", "no-store")])
        return [b"Maintenance"]
    assert_closed_settings()
    revision = Path("/app/.umanews-release-commit").read_text().strip()
    if not hex_value(revision, 40):
        raise ValueError("P02 probe image revision missing")
    with connection.cursor() as cursor:
        cursor.execute("SHOW default_transaction_read_only")
        if cursor.fetchone()[0] != "on":
            raise ValueError("P02 probe database must be readonly")

    def respond(status, headers, exc_info=None):
        return start_response(status, [*headers, ("X-Umanews-P02-Readonly", revision), ("Cache-Control", "no-store")], exc_info)
    return delegate(environ, respond)


application = readonly_application

from __future__ import annotations

from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse


class InternalSiteOnlyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "SITE_INTERNAL_ONLY_ENABLED", True):
            return self.get_response(request)
        if request.user.is_authenticated:
            return self.get_response(request)

        path = request.path_info or "/"
        if self._is_exempt(path):
            return self.get_response(request)
        if path.startswith("/api/"):
            return JsonResponse(
                {"detail": "authentication_required"},
                status=401,
            )

        next_path = request.get_full_path()
        parsed_next = urlsplit(next_path)
        if parsed_next.netloc or not parsed_next.path.startswith("/"):
            next_path = path if path.startswith("/") else "/"
        return redirect_to_login(next_path, settings.LOGIN_URL)

    @staticmethod
    def _is_exempt(path: str) -> bool:
        configured = set(
            getattr(settings, "SITE_INTERNAL_ONLY_EXEMPT_PATHS", []) or []
        )
        configured.update(
            {
                settings.LOGIN_URL,
                settings.LOGOUT_REDIRECT_URL,
                "/login/",
                "/logout/",
                "/admin/logout/",
                f"{settings.DJANGO_ADMIN_URL.rstrip('/')}/login/",
                f"{settings.DJANGO_ADMIN_URL.rstrip('/')}/logout/",
                "/healthz/",
                "/robots.txt",
            }
        )
        if path in configured:
            return True
        static_url = str(getattr(settings, "STATIC_URL", "/static/") or "/static/")
        return static_url.startswith("/") and path.startswith(static_url)

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path

from stable import views as stable_views


def healthcheck(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", stable_views.public_news_feed, name="public-news-feed"),
    path("news/<int:article_id>/", stable_views.public_article_detail, name="public-article-detail"),
    path("news/<str:slug>/", stable_views.legacy_public_article_detail, name="legacy-public-article-detail"),
    path("admin/", include("stable.urls")),
    path("api/", include("stable.api_urls")),
    path("login/", stable_views.legacy_login_redirect, name="legacy-backend-login"),
    path("logout/", stable_views.legacy_logout_redirect, name="legacy-backend-logout"),
    path("console/", stable_views.legacy_console_redirect, name="legacy-console-dashboard"),
    re_path(r"^console/(?P<subpath>.*)$", stable_views.legacy_console_redirect, name="legacy-console-redirect"),
    path(settings.DJANGO_ADMIN_URL.lstrip("/"), admin.site.urls),
    path("healthz/", healthcheck, name="healthcheck"),
]

if settings.DEBUG and settings.MEDIA_STORAGE_BACKEND != "oss":
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

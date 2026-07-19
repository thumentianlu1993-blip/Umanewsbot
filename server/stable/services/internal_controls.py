from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


INTERNAL_ONLY_DISTRIBUTION_BLOCK_REASON = "internal_only_distribution_blocked"
SOURCE_PUBLIC_DISTRIBUTION_BLOCK_REASON = "source_public_distribution_blocked"
MAX_PRIVATE_MEDIA_URL_TTL_SECONDS = 300
MAX_OPS_NOTIFICATION_CONFLICT_IDS = 50
MAX_SAFE_OPS_COUNT = (2**63) - 1
LOCAL_AI_PROVIDERS = frozenset({"dummy", "fallback", "local"})
OPS_NOTIFICATION_SAFE_FIELDS = (
    "task",
    "error_category",
    "count",
    "manual_review_count",
    "publish_ready_count",
    "failed_task_count",
    "conflict_count",
    "conflict_ids",
    "occurred_at",
    "article_id",
    "source_id",
    "window_id",
    "delivery_id",
    "event_id",
    "object_id",
    "run_id",
    "notification_type",
    "region",
)
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def _source_site_value(subject: Any) -> str:
    if isinstance(subject, str):
        return subject.strip()
    if subject is None:
        return ""
    for field in ("canonical_source_site", "source_site"):
        value = str(getattr(subject, field, "") or "").strip()
        if value:
            return value
    source_config = getattr(subject, "source_config", None)
    if source_config is not None:
        return _source_site_value(source_config)
    return ""


def public_distribution_blocked_source_sites() -> frozenset[str]:
    from stable.services.source_permissions import (
        INTERNAL_ONLY_USAGE_SCOPE,
        SOURCE_PERMISSION_REGISTRY,
    )

    return frozenset(
        source_site
        for source_site, record in SOURCE_PERMISSION_REGISTRY.items()
        if (
            record.usage_scope == INTERNAL_ONLY_USAGE_SCOPE
            or record.public_publish_allowed is False
        )
    )


def source_public_distribution_blocker(
    *,
    article: Any = None,
    source: Any = None,
) -> str | None:
    source_site = _source_site_value(source) or _source_site_value(article)
    if source_site in public_distribution_blocked_source_sites():
        return SOURCE_PUBLIC_DISTRIBUTION_BLOCK_REASON
    return None


def external_news_distribution_blocker(
    article: Any = None,
    source: Any = None,
) -> str | None:
    if getattr(settings, "SITE_INTERNAL_ONLY_ENABLED", True):
        return INTERNAL_ONLY_DISTRIBUTION_BLOCK_REASON
    return source_public_distribution_blocker(article=article, source=source)


def filter_news_for_current_site(queryset):
    if getattr(settings, "SITE_INTERNAL_ONLY_ENABLED", True):
        return queryset

    return queryset.exclude(
        source_site__in=public_distribution_blocked_source_sites()
    )


def news_article_visible_on_current_site(article: Any) -> bool:
    if getattr(settings, "SITE_INTERNAL_ONLY_ENABLED", True):
        return True
    return source_public_distribution_blocker(article=article) is None


def external_ai_processing_allowed(provider: str | None) -> bool:
    normalized = str(provider or "").strip().lower()
    if normalized in LOCAL_AI_PROVIDERS:
        return True
    return bool(getattr(settings, "NEWS_EXTERNAL_AI_PROCESSING_ENABLED", False))


def _safe_notification_value(field: str, value: Any) -> Any | None:
    if value is None or isinstance(value, bool):
        return None
    if field == "conflict_ids":
        if (
            not isinstance(value, (list, tuple))
            or len(value) > MAX_OPS_NOTIFICATION_CONFLICT_IDS
            or any(
                isinstance(item, bool)
                or not isinstance(item, int)
                or item <= 0
                or item > MAX_SAFE_OPS_COUNT
                for item in value
            )
        ):
            return None
        return list(value)
    if field in {
        "article_id",
        "source_id",
        "window_id",
        "delivery_id",
        "event_id",
        "object_id",
        "count",
        "manual_review_count",
        "publish_ready_count",
        "failed_task_count",
        "conflict_count",
    }:
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= MAX_SAFE_OPS_COUNT
        ):
            return value
        if (
            isinstance(value, str)
            and value.isdecimal()
            and int(value) <= MAX_SAFE_OPS_COUNT
        ):
            return value
        return None
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if field in {"task", "error_category", "notification_type", "region"}:
        return normalized if _SAFE_IDENTIFIER_RE.fullmatch(normalized) else None
    if field == "run_id":
        return normalized if _SAFE_IDENTIFIER_RE.fullmatch(normalized) else None
    if field == "occurred_at":
        try:
            datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            return None
        return normalized
    return normalized[:160]


def sanitize_internal_ops_notification(payload: Mapping[str, Any] | None) -> dict | None:
    if not isinstance(payload, Mapping):
        return None
    sanitized: dict[str, Any] = {}
    for field in OPS_NOTIFICATION_SAFE_FIELDS:
        if field not in payload:
            continue
        value = _safe_notification_value(field, payload[field])
        if value is not None:
            sanitized[field] = value
    return sanitized or None


def validate_internal_media_configuration() -> None:
    if not getattr(settings, "SITE_INTERNAL_ONLY_ENABLED", True):
        return None

    backend = str(getattr(settings, "MEDIA_STORAGE_BACKEND", "local") or "local").strip().lower()
    if backend == "local":
        return None
    if backend != "oss":
        raise ImproperlyConfigured(
            f"内部模式不支持 MEDIA_STORAGE_BACKEND={backend or '<empty>'}"
        )
    if not getattr(settings, "OSS_PRIVATE_MEDIA_ENABLED", False):
        raise ImproperlyConfigured(
            "内部模式使用 OSS 时必须启用 private media 短期签名 URL"
        )

    ttl = int(getattr(settings, "OSS_PRIVATE_MEDIA_URL_TTL_SECONDS", 0) or 0)
    if ttl < 1 or ttl > MAX_PRIVATE_MEDIA_URL_TTL_SECONDS:
        raise ImproperlyConfigured(
            f"OSS private media URL TTL 必须在 1-{MAX_PRIVATE_MEDIA_URL_TTL_SECONDS} 秒之间"
        )

    required = (
        "OSS_BUCKET_NAME",
        "OSS_ENDPOINT",
        "OSS_ACCESS_KEY_ID",
        "OSS_ACCESS_KEY_SECRET",
    )
    missing = [
        name
        for name in required
        if not str(getattr(settings, name, "") or "").strip()
    ]
    if missing:
        raise ImproperlyConfigured(
            f"OSS private media 配置缺失: {', '.join(missing)}"
        )
    return None


def validate_internal_transport_configuration() -> None:
    if (
        getattr(settings, "DEBUG", False)
        or not getattr(settings, "SITE_INTERNAL_ONLY_ENABLED", True)
    ):
        return None

    insecure_cookie_settings = [
        name
        for name in ("SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE")
        if getattr(settings, name, False) is not True
    ]
    if insecure_cookie_settings:
        raise ImproperlyConfigured(
            "内部模式生产配置必须启用 secure cookies: "
            + ", ".join(insecure_cookie_settings)
        )

    if getattr(settings, "SECURE_SSL_REDIRECT", False) is True:
        return None

    trusted_tls_termination = getattr(
        settings,
        "SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION",
        False,
    )
    proxy_header = getattr(settings, "SECURE_PROXY_SSL_HEADER", None)
    valid_proxy_https_contract = (
        isinstance(proxy_header, (tuple, list))
        and len(proxy_header) == 2
        and isinstance(proxy_header[0], str)
        and proxy_header[0].startswith("HTTP_")
        and str(proxy_header[1]).strip().casefold() == "https"
    )
    if trusted_tls_termination is not True or not valid_proxy_https_contract:
        raise ImproperlyConfigured(
            "内部模式生产配置必须启用 SECURE_SSL_REDIRECT，或显式启用可信 TLS "
            "终止并配置完整 SECURE_PROXY_SSL_HEADER HTTPS 合同"
        )
    return None

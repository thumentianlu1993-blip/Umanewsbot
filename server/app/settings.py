from __future__ import annotations

import os
import sys
from pathlib import Path

from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: str = "") -> list[str]:
    raw = env(key, default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = env("SECRET_KEY", "dev-secret-key-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "*" if DEBUG else "")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_filters",
    "stable.apps.StableConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "app.wsgi.application"
ASGI_APPLICATION = "app.asgi.application"

DB_ENGINE = env("DB_ENGINE", "sqlite").lower()
if DB_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", "horse_news"),
            "USER": env("POSTGRES_USER", "horse_news"),
            "PASSWORD": env("POSTGRES_PASSWORD", "horse_news"),
            "HOST": env("POSTGRES_HOST", "db"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(env("POSTGRES_CONN_MAX_AGE", "60")),
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "connect_timeout": int(env("POSTGRES_CONNECT_TIMEOUT", "10")),
                "sslmode": env("POSTGRES_SSLMODE", "prefer"),
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
RUNNING_TESTS = "test" in sys.argv

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_STORAGE_BACKEND = env("MEDIA_STORAGE_BACKEND", "local").lower()
OSS_PUBLIC_BASE_URL = (env("OSS_PUBLIC_BASE_URL", "") or "").strip()
OSS_ACCESS_KEY_ID = env("OSS_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = env("OSS_ACCESS_KEY_SECRET", "")
OSS_BUCKET_NAME = env("OSS_BUCKET_NAME", "")
OSS_ENDPOINT = env("OSS_ENDPOINT", "")
OSS_MEDIA_PREFIX = env("OSS_MEDIA_PREFIX", "media")
if MEDIA_STORAGE_BACKEND == "oss" and OSS_PUBLIC_BASE_URL:
    MEDIA_URL = f"{OSS_PUBLIC_BASE_URL.rstrip('/')}/"
else:
    MEDIA_URL = env("MEDIA_URL", "/media/")

default_storage_backend = "django.core.files.storage.FileSystemStorage"
if MEDIA_STORAGE_BACKEND == "oss":
    default_storage_backend = "stable.services.oss_storage.AliyunOSSStorage"

STORAGES = {
    "default": {"BACKEND": default_storage_backend},
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if env_bool("USE_STATICFILES_MANIFEST", not DEBUG and not RUNNING_TESTS)
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
    },
}

STATICFILES_STORAGE = STORAGES["staticfiles"]["BACKEND"]

LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/admin/"
LOGOUT_REDIRECT_URL = "/admin/login/"
DJANGO_ADMIN_URL = f"/{(env('DJANGO_ADMIN_URL', '/django-admin/') or '/django-admin/').strip('/')}/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SITE_URL = env("SITE_URL", "http://localhost:8000")

SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_HTTPONLY = env_bool("SESSION_COOKIE_HTTPONLY", True)
CSRF_COOKIE_HTTPONLY = env_bool("CSRF_COOKIE_HTTPONLY", False)
SESSION_COOKIE_SAMESITE = env("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = env("CSRF_COOKIE_SAMESITE", "Lax")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env_bool("USE_X_FORWARDED_HOST", True)
SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "0" if DEBUG else "86400"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
SECURE_REFERRER_POLICY = env("SECURE_REFERRER_POLICY", "same-origin")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = env("SECURE_CROSS_ORIGIN_OPENER_POLICY", "same-origin")
X_FRAME_OPTIONS = env("X_FRAME_OPTIONS", "DENY")

TRANSLATION_PROVIDER = env("TRANSLATION_PROVIDER", "dummy")
TRANSLATION_MODEL = env("TRANSLATION_MODEL", "gpt-5-mini")
OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_BASE_URL = env("OPENAI_BASE_URL")
SILICONFLOW_API_KEY = env("SILICONFLOW_API_KEY")
SILICONFLOW_BASE_URL = env("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
TRANSLATION_TERM_LIMIT = int(env("TRANSLATION_TERM_LIMIT", "20"))
TRANSLATION_TIMEOUT_SECONDS = int(env("TRANSLATION_TIMEOUT_SECONDS", "90"))
TRANSLATION_MAX_TOKENS = int(env("TRANSLATION_MAX_TOKENS", "2400"))
TRANSLATION_MAX_ATTEMPTS = int(env("TRANSLATION_MAX_ATTEMPTS", "2"))
TRANSLATION_UNKNOWN_HORSE_LIMIT = int(env("TRANSLATION_UNKNOWN_HORSE_LIMIT", "12"))
AUTO_TRANSLATE_ON_INGEST = env_bool("AUTO_TRANSLATE_ON_INGEST", True)
AUTO_TRANSLATE_SYNC = env_bool("AUTO_TRANSLATE_SYNC", True)

ONEBOT_BASE_URL = env("ONEBOT_BASE_URL", "http://localhost:3000")
ONEBOT_ACCESS_TOKEN = env("ONEBOT_ACCESS_TOKEN")

CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_WORKER_PREFETCH_MULTIPLIER = int(env("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))
CELERY_TASK_ACKS_LATE = env_bool("CELERY_TASK_ACKS_LATE", True)
CELERY_TASK_TRACK_STARTED = True

CELERY_BEAT_SCHEDULE = {
    "crawl-netkeiba-latest-hourly": {
        "task": "stable.tasks.crawl_netkeiba_latest",
        "schedule": crontab(minute=0),
    },
    "crawl-netkeiba-latest-sunday-rush": {
        "task": "stable.tasks.crawl_netkeiba_latest",
        "schedule": crontab(minute="30,35,40,45,50,55", hour=14, day_of_week="sun"),
        "kwargs": {"max_pages": 5, "rush_window": True},
    },
    "crawl-netkeiba-latest-sunday-rush-end": {
        "task": "stable.tasks.crawl_netkeiba_latest",
        "schedule": crontab(minute="0,5,10,15,20,25,30", hour=15, day_of_week="sun"),
        "kwargs": {"max_pages": 5, "rush_window": True},
    },
    "crawl-netkeiba-access": {
        "task": "stable.tasks.crawl_netkeiba_access",
        "schedule": crontab(minute=0, hour="0,12"),
    },
    "crawl-netkeiba-attention": {
        "task": "stable.tasks.crawl_netkeiba_attention",
        "schedule": crontab(minute=5, hour="0,12"),
    },
    "crawl-jra": {
        "task": "stable.tasks.crawl_jra_news",
        "schedule": crontab(minute=10, hour="0,12"),
    },
}

LOG_LEVEL = env("LOG_LEVEL", "INFO")
LOG_DIR = env("LOG_DIR")
if LOG_DIR:
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
        "verbose": {
            "format": "%(asctime)s %(levelname)s %(name)s [%(process)d:%(thread)d] %(message)s"
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "default"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "celery": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "stable": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

if LOG_DIR:
    LOGGING["handlers"]["app_file"] = {
        "class": "logging.handlers.WatchedFileHandler",
        "filename": str(Path(LOG_DIR) / "app.log"),
        "formatter": "verbose",
    }
    LOGGING["handlers"]["celery_file"] = {
        "class": "logging.handlers.WatchedFileHandler",
        "filename": str(Path(LOG_DIR) / "celery.log"),
        "formatter": "verbose",
    }
    LOGGING["root"]["handlers"].append("app_file")
    LOGGING["loggers"]["celery"]["handlers"].append("celery_file")
    LOGGING["loggers"]["stable"]["handlers"].append("app_file")

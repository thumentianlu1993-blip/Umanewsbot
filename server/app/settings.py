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


def extend_unique(items: list[str], extras: list[str]) -> list[str]:
    seen = set(items)
    merged = list(items)
    for extra in extras:
        if extra not in seen:
            merged.append(extra)
            seen.add(extra)
    return merged


SECRET_KEY = env("SECRET_KEY", "dev-secret-key-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "*" if DEBUG else "")
if "*" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS = extend_unique(ALLOWED_HOSTS, ["127.0.0.1", "localhost", "[::1]", "::1"])
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
            "NAME": env("SQLITE_DB_PATH", str(BASE_DIR / "db.sqlite3")),
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

HISTORICAL_RACE_BACKFILL_ENABLED = env_bool("HISTORICAL_RACE_BACKFILL_ENABLED", False)
HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK = env_bool("HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK", False)
HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET = int(env("HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET", "250"))
HISTORICAL_RACE_BACKFILL_MAX_SOURCE_CACHE_BYTES = int(
    env("HISTORICAL_RACE_BACKFILL_MAX_SOURCE_CACHE_BYTES", str(2 * 1024 * 1024 * 1024))
)
HISTORICAL_RACE_BACKFILL_MIN_FREE_DISK_BYTES = int(
    env("HISTORICAL_RACE_BACKFILL_MIN_FREE_DISK_BYTES", str(5 * 1024 * 1024 * 1024))
)
RACE_EVENT_SITEMAP_SHARD_SIZE = int(env("RACE_EVENT_SITEMAP_SHARD_SIZE", "10000"))
RACE_EVENT_PUBLIC_CACHE_SECONDS = int(env("RACE_EVENT_PUBLIC_CACHE_SECONDS", "300"))
RACE_EVENT_CACHE_URL = env(
    "RACE_EVENT_CACHE_URL",
    env("CELERY_BROKER_URL", "redis://localhost:6379/0"),
)
CACHES = {
    "default": (
        {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "umanews-tests",
        }
        if RUNNING_TESTS
        else {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": RACE_EVENT_CACHE_URL,
            "KEY_PREFIX": "umanews",
        }
    )
}

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

AUTOMATION_ENABLED = env_bool("AUTOMATION_ENABLED", False)
AUTO_REVIEW_THRESHOLD = int(env("AUTO_REVIEW_THRESHOLD", "75"))
MANUAL_REVIEW_THRESHOLD = int(env("MANUAL_REVIEW_THRESHOLD", "45"))
AUTO_REWRITE_ENABLED = env_bool("AUTO_REWRITE_ENABLED", False)
AUTO_PUBLISH_CONTENT_SOURCE = env("AUTO_PUBLISH_CONTENT_SOURCE", "base_translation")
HIGH_VALUE_SOURCE_RULES = env_list("HIGH_VALUE_SOURCE_RULES", "netkeiba:access,netkeiba:attention")
HIGH_VALUE_WARNING_SCORE_THRESHOLD = int(env("HIGH_VALUE_WARNING_SCORE_THRESHOLD", "90"))
AUTO_DUPLICATE_LOOKBACK_DAYS = int(env("AUTO_DUPLICATE_LOOKBACK_DAYS", "7"))
AUTO_DUPLICATE_HIGH_THRESHOLD = float(env("AUTO_DUPLICATE_HIGH_THRESHOLD", "0.86"))
AUTO_DUPLICATE_REVIEW_THRESHOLD = float(env("AUTO_DUPLICATE_REVIEW_THRESHOLD", "0.72"))
AUTO_PUBLISH_BATCH_LIMIT = int(env("AUTO_PUBLISH_BATCH_LIMIT", "4"))
AUTO_PUBLISH_PEAK_BATCH_LIMIT = int(env("AUTO_PUBLISH_PEAK_BATCH_LIMIT", "10"))
AUTO_PUBLISH_PEAK_DAY_OF_WEEK = int(env("AUTO_PUBLISH_PEAK_DAY_OF_WEEK", "6"))
AUTO_PUBLISH_PEAK_START_HOUR = int(env("AUTO_PUBLISH_PEAK_START_HOUR", "13"))
AUTO_PUBLISH_PEAK_END_HOUR = int(env("AUTO_PUBLISH_PEAK_END_HOUR", "16"))
AUTO_PUBLISH_INTERVAL_MINUTES = int(env("AUTO_PUBLISH_INTERVAL_MINUTES", "15"))
REWRITE_CONFIDENCE_MIN = int(env("REWRITE_CONFIDENCE_MIN", "60"))
AUTO_PUBLISH_REQUIRE_COVER = env_bool("AUTO_PUBLISH_REQUIRE_COVER", False)
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS = env_list("MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS", "")
MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES = env_list("MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES", "")
MULTIREGION_AUTO_PUBLISH_REGION_BATCH_LIMITS = env("MULTIREGION_AUTO_PUBLISH_REGION_BATCH_LIMITS", "")
MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS = env("MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS", "")
MULTIREGION_TERM_CANDIDATE_BACKLOG_THRESHOLD = int(env("MULTIREGION_TERM_CANDIDATE_BACKLOG_THRESHOLD", "50"))
MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS = env_list(
    "MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS",
    "class,content,link,agent,oaks,america,numbers",
)
MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS = env_list(
    "MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS",
    "",
)
MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS = env_list(
    "MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS",
    "Alex Hammond,Alive MediCare,Alrazeen,Amenity Support,AmWager,Antelligence Consulting,Assort Work,"
    "Bentiga Orsa,Booked,Brien,CONY JAPAN,Cosmo Achieve,Delma Siliri,DMCA,DYM Career,Flickerjab,"
    "French Blue,Ghostzapper,Glenmalure Flyer,Good,Good Partners,Google,Google Play,HIWU,HorseCenter,"
    "Japan Create,Jiair Madrik,Joint Service,Jpn,Katzoff,Kotohodo Sayouni,Ladies VS Rookies Battle,"
    "Lane,Law,Long Pour,Look,Medaglia,MEDILCY,Merry Christmas,Mid Century,Midshipman,Minute,Motorboat,"
    "Nebula Disc,Noble Granz,NRs,OBSAPR,Our Moneyman,Paddy Power,PayPay,PUBLISHERID,Ragozin,Redbarn,"
    "ReFa,Sax Appeal,Ship Ship Hooray,TAGID,Ten Sovereigns,Thoroughmanager,Tiz,Touch,TVh,Vase,Vidiprinter,"
    "Wide Blizzard,アーバン,イベント,オーナー,オープン,サイト,サノノ,システム,ショウナン,スター,スーパー,"
    "ソンシ,ダービー,チーム,トレセン,トレーニング・センター,フリー,ペース,ボートレースレディースVSルーキーズバトル,"
    "マーク,メール,ユタカ,ユース,リーディング,レコード",
)
MULTIREGION_ATTRIBUTION_ENABLED = env_bool("MULTIREGION_ATTRIBUTION_ENABLED", True)
MULTIREGION_RELATED_REGION_QUERIES_ENABLED = env_bool("MULTIREGION_RELATED_REGION_QUERIES_ENABLED", True)
MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES = env_list(
    "MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES",
    "news,preview,result_brief,feature,flash,pre_race,post_race,official,interview",
)
MULTIREGION_SUPPORTED_PRODUCTION_SOURCE_LANGUAGES = env_list(
    "MULTIREGION_SUPPORTED_PRODUCTION_SOURCE_LANGUAGES",
    "ja,en,zh-hant",
)
REWRITE_PROVIDER = env("REWRITE_PROVIDER", TRANSLATION_PROVIDER)
REWRITE_MODEL = env("REWRITE_MODEL", TRANSLATION_MODEL)
REWRITE_MAX_TOKENS = int(env("REWRITE_MAX_TOKENS", "2600"))
REWRITE_TIMEOUT_SECONDS = int(env("REWRITE_TIMEOUT_SECONDS", str(TRANSLATION_TIMEOUT_SECONDS)))

TERM_DISCOVERY_ENABLED = env_bool("TERM_DISCOVERY_ENABLED", False)
TERM_DISCOVERY_PROVIDER = env("TERM_DISCOVERY_PROVIDER", "rules")
TERM_DISCOVERY_MIN_CONFIDENCE = int(env("TERM_DISCOVERY_MIN_CONFIDENCE", "60"))

EXTERNAL_HORSE_DATA_IMPORT_ENABLED = env_bool("EXTERNAL_HORSE_DATA_IMPORT_ENABLED", False)
EXTERNAL_HORSE_DATA_ALLOW_NETWORK = env_bool("EXTERNAL_HORSE_DATA_ALLOW_NETWORK", False)
EXTERNAL_HORSE_DATA_LOOKBACK_MONTHS = int(env("EXTERNAL_HORSE_DATA_LOOKBACK_MONTHS", "24"))
EXTERNAL_HORSE_DATA_REQUEST_INTERVAL_SECONDS = float(env("EXTERNAL_HORSE_DATA_REQUEST_INTERVAL_SECONDS", "5"))
EXTERNAL_HORSE_DATA_JITTER_SECONDS = float(env("EXTERNAL_HORSE_DATA_JITTER_SECONDS", "2"))
EXTERNAL_HORSE_DATA_MAX_RACES_PER_RUN = int(env("EXTERNAL_HORSE_DATA_MAX_RACES_PER_RUN", "30"))
EXTERNAL_HORSE_DATA_MAX_HORSES_PER_RUN = int(env("EXTERNAL_HORSE_DATA_MAX_HORSES_PER_RUN", "100"))
EXTERNAL_HORSE_DATA_FETCH_ODDS = env_bool("EXTERNAL_HORSE_DATA_FETCH_ODDS", False)
EXTERNAL_HORSE_DATA_FETCH_HORSE_DETAIL = env_bool("EXTERNAL_HORSE_DATA_FETCH_HORSE_DETAIL", True)
HORSE_PROFILE_COMPLETION_ALLOW_NETWORK = env_bool("HORSE_PROFILE_COMPLETION_ALLOW_NETWORK", False)
HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS = float(env("HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS", "8"))
HORSE_PROFILE_COMPLETION_CACHE_DIR = env("HORSE_PROFILE_COMPLETION_CACHE_DIR", "runtime/horse_profile_completion/cache")
HORSE_PROFILE_COMPLETION_BATCH_LIMIT = int(env("HORSE_PROFILE_COMPLETION_BATCH_LIMIT", "10"))
HORSE_PROFILE_COMPLETION_REQUIRE_SOURCE_URL = env_bool("HORSE_PROFILE_COMPLETION_REQUIRE_SOURCE_URL", True)
HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS = int(env("HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS", "1"))
HKJC_IMPORT_NETWORK_BASE_URL = env("HKJC_IMPORT_NETWORK_BASE_URL", "https://racing.hkjc.com")
HKJC_IMPORT_REQUEST_INTERVAL_SECONDS = float(env("HKJC_IMPORT_REQUEST_INTERVAL_SECONDS", "8"))
HKJC_IMPORT_MAX_RACES_PER_RUN = int(env("HKJC_IMPORT_MAX_RACES_PER_RUN", "20"))
HKJC_IMPORT_MAX_HORSES_PER_RUN = int(env("HKJC_IMPORT_MAX_HORSES_PER_RUN", "80"))
HKJC_IMPORT_MAX_REQUESTS_PER_RUN = int(env("HKJC_IMPORT_MAX_REQUESTS_PER_RUN", "200"))
UK_IMPORT_NETWORK_BASE_URL = env("UK_IMPORT_NETWORK_BASE_URL", "https://www.sportinglife.com")
UK_IMPORT_REQUEST_INTERVAL_SECONDS = float(env("UK_IMPORT_REQUEST_INTERVAL_SECONDS", "8"))
UK_IMPORT_MAX_RACES_PER_RUN = int(env("UK_IMPORT_MAX_RACES_PER_RUN", "20"))
UK_IMPORT_MAX_HORSES_PER_RUN = int(env("UK_IMPORT_MAX_HORSES_PER_RUN", "80"))
UK_IMPORT_MAX_REQUESTS_PER_RUN = int(env("UK_IMPORT_MAX_REQUESTS_PER_RUN", "200"))
FRANCE_IMPORT_NETWORK_BASE_URL = env("FRANCE_IMPORT_NETWORK_BASE_URL", "https://www.france-galop.com")
GENY_FRANCE_IMPORT_NETWORK_BASE_URL = env("GENY_FRANCE_IMPORT_NETWORK_BASE_URL", "https://www.geny.com")
FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS = float(env("FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS", "8"))
FRANCE_IMPORT_MAX_RACES_PER_RUN = int(env("FRANCE_IMPORT_MAX_RACES_PER_RUN", "20"))
FRANCE_IMPORT_MAX_HORSES_PER_RUN = int(env("FRANCE_IMPORT_MAX_HORSES_PER_RUN", "80"))
FRANCE_IMPORT_MAX_REQUESTS_PER_RUN = int(env("FRANCE_IMPORT_MAX_REQUESTS_PER_RUN", "200"))
US_IMPORT_ENTRIES_BASE_URL = env("US_IMPORT_ENTRIES_BASE_URL", "https://entries.horseracingnation.com")
US_IMPORT_HRN_BASE_URL = env("US_IMPORT_HRN_BASE_URL", "https://www.horseracingnation.com")
US_IMPORT_REQUEST_INTERVAL_SECONDS = float(env("US_IMPORT_REQUEST_INTERVAL_SECONDS", "8"))
US_IMPORT_MAX_RACES_PER_RUN = int(env("US_IMPORT_MAX_RACES_PER_RUN", "20"))
US_IMPORT_MAX_HORSES_PER_RUN = int(env("US_IMPORT_MAX_HORSES_PER_RUN", "80"))
US_IMPORT_MAX_REQUESTS_PER_RUN = int(env("US_IMPORT_MAX_REQUESTS_PER_RUN", "200"))

EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "25"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "umanewsbot@example.com")
AUTOMATION_ENABLE_EMAIL = env_bool("AUTOMATION_ENABLE_EMAIL", False)
AUTOMATION_NOTIFY_EMAILS = env_list("AUTOMATION_NOTIFY_EMAILS", "")
AUTOMATION_WARNING_EMAIL_ENABLED = env_bool("AUTOMATION_WARNING_EMAIL_ENABLED", True)
AUTOMATION_WARNING_NOTIFY_EMAILS = env_list("AUTOMATION_WARNING_NOTIFY_EMAILS", ",".join(AUTOMATION_NOTIFY_EMAILS))
AUTOMATION_WARNING_EMAIL_DEDUP_HOURS = int(env("AUTOMATION_WARNING_EMAIL_DEDUP_HOURS", "24"))

ONEBOT_BASE_URL = env("ONEBOT_BASE_URL", "http://localhost:3000")
ONEBOT_ACCESS_TOKEN = env("ONEBOT_ACCESS_TOKEN")
ONEBOT_TIMEOUT_SECONDS = int(env("ONEBOT_TIMEOUT_SECONDS", "30"))

QQ_PUSH_ENABLED = env_bool("QQ_PUSH_ENABLED", False)
QQ_PUSH_SCOPE = env("QQ_PUSH_SCOPE", "high_value_only")
QQ_PUSH_IMPORTANCE_STRATEGY = env("QQ_PUSH_IMPORTANCE_STRATEGY", "ranked")
QQ_PUSH_MAX_ATTEMPTS = int(env("QQ_PUSH_MAX_ATTEMPTS", "3"))
QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS = int(env("QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS", "5"))
QQ_PUSH_SENDING_STALE_SECONDS = int(env("QQ_PUSH_SENDING_STALE_SECONDS", "600"))
QQ_PUSH_MIN_INTERVAL_SECONDS = int(env("QQ_PUSH_MIN_INTERVAL_SECONDS", "60"))

MULTIREGION_PRODUCTION_WINDOWS_ENABLED = env_bool("MULTIREGION_PRODUCTION_WINDOWS_ENABLED", False)
MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED = env_bool("MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED", False)
MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED = env_bool("MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED", False)
MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED = env_bool("MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED", False)
MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS = env_list("MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS", "")
MULTIREGION_PRODUCTION_WINDOW_DAILY_MINUTES = int(env("MULTIREGION_PRODUCTION_WINDOW_DAILY_MINUTES", "15"))
MULTIREGION_PRODUCTION_WINDOW_MAJOR_RACE_MINUTES = int(env("MULTIREGION_PRODUCTION_WINDOW_MAJOR_RACE_MINUTES", "5"))
MULTIREGION_PRODUCTION_WINDOW_LOOKBACK_HOURS = int(env("MULTIREGION_PRODUCTION_WINDOW_LOOKBACK_HOURS", "3"))
MULTIREGION_PRODUCTION_WINDOW_LEASE_MINUTES = int(env("MULTIREGION_PRODUCTION_WINDOW_LEASE_MINUTES", "30"))
MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES = int(env("MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES", "15"))
MULTIREGION_CRAWL_MAJOR_RACE_INTERVAL_MINUTES = int(env("MULTIREGION_CRAWL_MAJOR_RACE_INTERVAL_MINUTES", "5"))
MULTIREGION_CRAWL_MAX_SOURCES_PER_TICK = int(env("MULTIREGION_CRAWL_MAX_SOURCES_PER_TICK", "50"))
MULTIREGION_CRAWL_FAILURES_TO_BACKOFF = int(env("MULTIREGION_CRAWL_FAILURES_TO_BACKOFF", "3"))
MULTIREGION_CRAWL_SUCCESSES_TO_RECOVER = int(env("MULTIREGION_CRAWL_SUCCESSES_TO_RECOVER", "3"))
MULTIREGION_CRAWL_BACKOFF_MINUTES = int(env("MULTIREGION_CRAWL_BACKOFF_MINUTES", "60"))
MULTIREGION_CRAWL_BLOCKED_BACKOFF_MINUTES = int(env("MULTIREGION_CRAWL_BLOCKED_BACKOFF_MINUTES", "360"))
MULTIREGION_PUBLISH_REGION_WINDOW_MAX = int(env("MULTIREGION_PUBLISH_REGION_WINDOW_MAX", "5"))
MULTIREGION_PUBLISH_REGION_WINDOW_MIN = int(env("MULTIREGION_PUBLISH_REGION_WINDOW_MIN", "1"))
MULTIREGION_PUBLISH_SOFT_FILL_MIN_SCORE = int(env("MULTIREGION_PUBLISH_SOFT_FILL_MIN_SCORE", "45"))
MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS = int(env("MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS", "3"))
MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY = int(env("MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY", "60"))
MULTIREGION_PUBLISH_SITE_HOURLY_MAX_MAJOR_RACE = int(env("MULTIREGION_PUBLISH_SITE_HOURLY_MAX_MAJOR_RACE", "120"))
MULTIREGION_QQ_REGION_WINDOW_MAX = int(env("MULTIREGION_QQ_REGION_WINDOW_MAX", "3"))
MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY = int(env("MULTIREGION_QQ_GROUP_HOURLY_MAX_DAILY", "12"))
MULTIREGION_QQ_GROUP_HOURLY_MAX_MAJOR_RACE = int(env("MULTIREGION_QQ_GROUP_HOURLY_MAX_MAJOR_RACE", "24"))
MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY = int(env("MULTIREGION_QQ_SITE_HOURLY_MAX_DAILY", "40"))
MULTIREGION_QQ_SITE_HOURLY_MAX_MAJOR_RACE = int(env("MULTIREGION_QQ_SITE_HOURLY_MAX_MAJOR_RACE", "80"))
MULTIREGION_OPS_NOTIFICATIONS_ENABLED = env_bool("MULTIREGION_OPS_NOTIFICATIONS_ENABLED", False)
MULTIREGION_OPS_NOTIFICATION_QQ_GROUP_ID = env("MULTIREGION_OPS_NOTIFICATION_QQ_GROUP_ID", "")
MULTIREGION_OPS_NOTIFICATION_EMAILS = env_list("MULTIREGION_OPS_NOTIFICATION_EMAILS", "")
MULTIREGION_OPS_NOTIFICATION_COOLDOWN_MINUTES = int(env("MULTIREGION_OPS_NOTIFICATION_COOLDOWN_MINUTES", "30"))
MULTIREGION_ROLLBACK_DISABLE_CRAWL_WINDOWS = env_bool("MULTIREGION_ROLLBACK_DISABLE_CRAWL_WINDOWS", False)
MULTIREGION_ROLLBACK_DISABLE_PUBLISH_WINDOWS = env_bool("MULTIREGION_ROLLBACK_DISABLE_PUBLISH_WINDOWS", False)
MULTIREGION_ROLLBACK_DISABLE_QQ_WINDOWS = env_bool("MULTIREGION_ROLLBACK_DISABLE_QQ_WINDOWS", False)
MULTIREGION_ROLLBACK_DISABLE_OPS_NOTIFICATIONS = env_bool("MULTIREGION_ROLLBACK_DISABLE_OPS_NOTIFICATIONS", False)

NEWS_SOURCE_POLL_ENABLED = env_bool("NEWS_SOURCE_POLL_ENABLED", False)
NEWS_SOURCE_POLL_INTERVAL_MINUTES = int(env("NEWS_SOURCE_POLL_INTERVAL_MINUTES", "30"))
NEWS_SOURCE_POLL_MAX_SOURCES = int(env("NEWS_SOURCE_POLL_MAX_SOURCES", "3"))
NEWS_SOURCE_POLL_ALLOWED_REGIONS = env_list("NEWS_SOURCE_POLL_ALLOWED_REGIONS", "")
NEWS_SOURCE_POLL_ALLOWED_SOURCES = env_list("NEWS_SOURCE_POLL_ALLOWED_SOURCES", "")
NEWS_SOURCE_POLL_RUNNING_TIMEOUT_MINUTES = int(env("NEWS_SOURCE_POLL_RUNNING_TIMEOUT_MINUTES", "60"))
NEWS_SOURCE_POLL_RETRY_STALE_RUNNING = env_bool("NEWS_SOURCE_POLL_RETRY_STALE_RUNNING", False)

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
        "schedule": crontab(minute=16),
    },
    "crawl-netkeiba-attention": {
        "task": "stable.tasks.crawl_netkeiba_attention",
        "schedule": crontab(minute=26),
    },
    "crawl-jra": {
        "task": "stable.tasks.crawl_jra_news",
        "schedule": crontab(minute=10, hour="0,12"),
    },
    "crawl-enabled-news-sources": {
        "task": "stable.tasks.crawl_enabled_news_sources_task",
        "schedule": crontab(minute=f"*/{NEWS_SOURCE_POLL_INTERVAL_MINUTES}"),
    },
    "crawl-production-sources-window": {
        "task": "stable.tasks.crawl_production_sources_window_task",
        "schedule": crontab(minute="*/5"),
    },
    "auto-publish-batch": {
        "task": "stable.tasks.auto_publish_batch_task",
        "schedule": crontab(minute=f"*/{AUTO_PUBLISH_INTERVAL_MINUTES}"),
    },
    "publish-production-regions-window": {
        "task": "stable.tasks.publish_production_regions_window_task",
        "schedule": crontab(minute="*/5"),
    },
    "qq-production-regions-window": {
        "task": "stable.tasks.qq_production_regions_window_task",
        "schedule": crontab(minute="*/5"),
    },
    "detect-automation-anomalies": {
        "task": "stable.tasks.detect_automation_anomalies_task",
        "schedule": crontab(minute="*/30"),
    },
    "production-summary-daily": {
        "task": "stable.tasks.production_summary_task",
        "schedule": crontab(minute=5, hour=9),
    },
    "p0-horse-identity-conflicts-daily": {
        "task": "stable.tasks.notify_p0_horse_identity_conflicts_task",
        "schedule": crontab(minute=20, hour=9),
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

"""C021 专用零 DB 设置；不导入生产 settings 或环境变量。"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = 'synthetic-c021-offline-test-only'
DEBUG = False
USE_TZ = True
TIME_ZONE = 'Asia/Shanghai'
LANGUAGE_CODE = 'zh-hans'
STATIC_URL = '/static/'
ROOT_URLCONF = 'public_probe_template_urls'
INSTALLED_APPS = [
    'django.contrib.contenttypes', 'django.contrib.auth', 'stable.apps.StableConfig',
]
DATABASES = {'default': {'ENGINE': 'django.db.backends.dummy'}}
MIDDLEWARE = []
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}}
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'stable' / 'templates'],
    'APP_DIRS': False,
    'OPTIONS': {
        'loaders': ['django.template.loaders.filesystem.Loader'],
        'context_processors': [],
        'libraries': {'race_information': 'stable.templatetags.race_information'},
    },
}]
RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED = False
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

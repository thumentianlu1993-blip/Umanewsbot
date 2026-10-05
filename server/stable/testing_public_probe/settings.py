"""仅供测试类 override_settings 使用的常量；保留正式 apps/PG16 后端。"""
from pathlib import Path

STABLE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_TEST_SETTINGS = {
    'ROOT_URLCONF': 'stable.testing_public_probe.urls',
    'USE_TZ': True,
    'TIME_ZONE': 'Asia/Shanghai',
    'LANGUAGE_CODE': 'zh-hans',
    'STATIC_URL': '/static/',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}},
    'TEMPLATES': [{
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [STABLE_ROOT / 'templates'],
        'APP_DIRS': False,
        'OPTIONS': {
            'loaders': ['django.template.loaders.filesystem.Loader'],
            'context_processors': [],
            'libraries': {'race_information': 'stable.templatetags.race_information'},
        },
    }],
    'RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED': False,
}

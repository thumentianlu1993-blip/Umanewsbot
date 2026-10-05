"""正式 Django collector 的包化导入与类内模板设置隔离回归。"""
from copy import deepcopy
from pathlib import Path
import unittest

from django.conf import settings
from django.db import connection
from django.template.loader import get_template
from django.test import SimpleTestCase, override_settings
from django.test.testcases import DatabaseOperationForbidden
from django.urls import reverse

from stable import test_public_probe_template_adapter as adapter_tests
from stable.testing_public_probe.settings import TEMPLATE_TEST_SETTINGS


class TemplateGlueIsolationTests(SimpleTestCase):
    databases = set()

    def test_standard_label_loads_only_adapter_cases(self):
        # 使用正式 collector 的标准 label，不调整 sys.path 或导入 stable.tests。
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromName('stable.test_public_probe_template_adapter')
        self.assertEqual(loader.errors, [])

        def cases(items):
            for item in items:
                if isinstance(item, unittest.TestSuite):
                    yield from cases(item)
                else:
                    yield item

        loaded = list(cases(suite))
        self.assertTrue(loaded)
        self.assertTrue(all(isinstance(case, adapter_tests.TemplateAdapterFirstRed)
                            for case in loaded))
        identifiers = [case.id() for case in loaded]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(all(ident.startswith(
            'stable.test_public_probe_template_adapter.TemplateAdapterFirstRed.')
            for ident in identifiers))
        self.assertIn('stable.test_public_probe_template_adapter.'
                      'TemplateAdapterFirstRed.test_full_original_bytes_without_projection',
                      identifiers)

    def _check_class_boundary(self, *, fail_probe):
        # 外层模拟相邻测试不同的环境；内层必须覆盖且在正常/失败后完整恢复。
        sentinels = deepcopy(TEMPLATE_TEST_SETTINGS)
        sentinels.update(
            ROOT_URLCONF=__name__,
            TEMPLATES=[{
                'BACKEND': 'django.template.backends.django.DjangoTemplates',
                'DIRS': [], 'APP_DIRS': False,
                'OPTIONS': {'loaders': ['django.template.loaders.filesystem.Loader'],
                            'context_processors': [], 'libraries': {}},
            }],
            TIME_ZONE='UTC', LANGUAGE_CODE='en', USE_TZ=False,
            STATIC_URL='/neighbor-static/',
            RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=True,
            CACHES={'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'neighbor-public-probe-glue-test',
            }},
        )
        observed = {}
        app_config = deepcopy(settings.INSTALLED_APPS)
        database_config = deepcopy(settings.DATABASES)

        class EnvironmentProbe(adapter_tests.TemplateAdapterFirstRed):
            # 只选择此方法，不运行父类业务方法；继承父类真实 settings/SQL 隔离。
            def test_environment_probe(self):
                self.assertEqual(settings.ROOT_URLCONF, 'stable.testing_public_probe.urls')
                self.assertEqual(settings.TIME_ZONE, 'Asia/Shanghai')
                self.assertEqual(settings.LANGUAGE_CODE, 'zh-hans')
                self.assertIs(settings.USE_TZ, True)
                self.assertEqual(settings.STATIC_URL, '/static/')
                self.assertIs(settings.RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED, False)
                self.assertEqual(settings.INSTALLED_APPS, app_config)
                self.assertEqual(settings.DATABASES, database_config)
                for name, route in (
                    ('public-race-calendar', '/races/'),
                    ('public-horse-index', '/horses/'),
                    ('public-horse-follows', '/horses/follows/'),
                ):
                    self.assertEqual(reverse(name), route)
                template = get_template('stable/public/race_calendar.html')
                expected_path = (Path(__file__).resolve().parent / 'templates' /
                                 'stable/public/race_calendar.html')
                self.assertEqual(Path(template.origin.name).resolve(), expected_path)
                self.assertEqual(tuple(template.template.engine.context_processors), ())
                self.assertEqual(settings.CACHES['default']['BACKEND'],
                                 'django.core.cache.backends.dummy.DummyCache')
                with self.assertRaises(DatabaseOperationForbidden):
                    connection.cursor()
                observed['environment_and_sql_verified'] = True
                if fail_probe:
                    self.fail('controlled-class-boundary-failure')

        with override_settings(**sentinels):
            before = {key: deepcopy(getattr(settings, key))
                      for key in TEMPLATE_TEST_SETTINGS}
            cursor_before = connection.cursor
            result = unittest.TestResult()
            unittest.TestSuite([EnvironmentProbe('test_environment_probe')]).run(result)
            self.assertEqual(result.testsRun, 1)
            self.assertEqual(result.errors, [])
            self.assertTrue(observed.get('environment_and_sql_verified'), result.failures)
            self.assertEqual(len(result.failures), int(fail_probe))
            if fail_probe:
                self.assertIn('controlled-class-boundary-failure', result.failures[0][1])
            after = {key: deepcopy(getattr(settings, key))
                     for key in TEMPLATE_TEST_SETTINGS}
            self.assertEqual(after, before)
            self.assertEqual(settings.INSTALLED_APPS, app_config)
            self.assertEqual(settings.DATABASES, database_config)
            self.assertIs(connection.cursor, cursor_before)
            # 内层 class cleanup 不能解除外层 SimpleTestCase 的 SQL 禁用包装。
            with self.assertRaises(DatabaseOperationForbidden):
                connection.cursor()

    def test_class_settings_restore_after_success(self):
        self._check_class_boundary(fail_probe=False)

    def test_class_settings_restore_after_assertion_failure(self):
        self._check_class_boundary(fail_probe=True)

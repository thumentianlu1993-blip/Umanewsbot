"""专用只读探针必须屏蔽管理/写请求，不以普通healthz冒充候选版本证明。"""

from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase, override_settings

from stable.services.release_p02_executor import WRITER_FLAGS


class ReadonlyProbeTests(SimpleTestCase):
    def setUp(self):
        from app import p02_readonly_wsgi as probe
        self.probe = probe

    def test_all_write_methods_and_non_probe_paths_are_closed(self):
        for method, path in (("POST", "/races/"), ("DELETE", "/healthz/"), ("GET", "/admin/"), ("GET", "/login/"), ("GET", "/")):
            with self.subTest(method=method, path=path):
                start, delegate = MagicMock(), MagicMock()
                self.probe.readonly_application({"REQUEST_METHOD": method, "PATH_INFO": path}, start, delegate=delegate)
                self.assertEqual(start.call_args.args[0], "503 Service Unavailable")
                delegate.assert_not_called()

    @override_settings(**{key: False for key in WRITER_FLAGS}, RACE_LIFECYCLE_V2_EVENT_IDS=())
    def test_readonly_connection_and_image_revision_are_required(self):
        delegate = MagicMock(return_value=[b"ok"])
        with patch.object(self.probe.Path, "read_text", return_value="a" * 40), patch.object(self.probe, "connection") as database:
            cursor = database.cursor
            cursor.return_value.__enter__.return_value.fetchone.return_value = ("off",)
            with self.assertRaisesRegex(ValueError, "readonly"):
                self.probe.readonly_application({"REQUEST_METHOD": "GET", "PATH_INFO": "/races/"}, MagicMock(), delegate=delegate)
            delegate.assert_not_called()
            cursor.return_value.__enter__.return_value.fetchone.return_value = ("on",)
            start = MagicMock()
            def respond(environ, response):
                response("200 OK", [("Content-Type", "text/plain")])
                return [b"ok"]
            self.probe.readonly_application({"REQUEST_METHOD": "GET", "PATH_INFO": "/races/"}, start, delegate=respond)
            self.assertIn(("X-Umanews-P02-Readonly", "a" * 40), start.call_args.args[1])

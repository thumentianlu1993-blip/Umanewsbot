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


class StreamingRecoveryCountsTests(SimpleTestCase):
    def test_large_table_rows_use_server_cursor_and_keep_digest(self):
        import hashlib
        from stable.services import release_p02_schema as schema
        batch = [('first',), ('second',)]
        with patch.object(schema, 'connection') as db:
            metadata = db.cursor.return_value.__enter__.return_value
            metadata.fetchall.side_effect = [[('large_table',)], []]
            db.ops.quote_name.side_effect = lambda value: '"' + value + '"'
            stream = db.chunked_cursor.return_value.__enter__.return_value
            stream.fetchmany.side_effect = [batch, []]
            # A normal cursor's execute buffers its full result, even with later fetchmany().
            def reject_buffered_rows(query, *args):
                if query.startswith('SELECT row_to_json'):
                    raise AssertionError('large table was buffered on the client')
            metadata.execute.side_effect = reject_buffered_rows
            actual = schema.counts()
        h = hashlib.sha256()
        for row in batch:
            value = row[0].encode(); h.update(len(value).to_bytes(8, 'big')); h.update(value)
        self.assertEqual(actual, {'tables': {'large_table': {'count': 2, 'sha256': h.hexdigest()}}, 'sequences': {}})
        db.chunked_cursor.assert_called_once()

"""年度目录本地输入合同；所有网络调用均替换为失败哨兵。"""
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from stable.services.race_data_source_adapters import fetch_source_page
from stable.services.us_race_source import ObservationStore

URL = 'https://toba.org/graded-stakes/2026-races/'
NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)
CAPTURED = datetime(2026, 11, 11, tzinfo=timezone.utc)
FIX = Path(__file__).parent / 'fixtures/us_automation/toba.html'


@override_settings(RACE_DATA_MULTISOURCE_APPLY_ENABLED=True, RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ALLOW_NETWORK=True, RACE_DATA_SYNC_ENABLED_PROVIDERS=('us_racing',),
    RACE_DATA_SYNC_ENABLED_REGIONS=('united_states',))
class USCalendarSnapshotTests(SimpleTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = FIX.read_bytes()
        (self.root/'toba.html').write_bytes(self.raw)
        self.entry = dict(year=2026, url=URL, file='toba.html',
            sha256=hashlib.sha256(self.raw).hexdigest(), captured_at=CAPTURED.isoformat())
        self.route = SimpleNamespace(provider='us_racing', region='united_states',
            permits_url=lambda u: True, valid=lambda t: True)
        self.network = patch('stable.services.race_pre_race._fetch_bounded_html',
            side_effect=AssertionError('network forbidden')).start()
        self.addCleanup(patch.stopall)

    def config(self, **changes):
        entry = dict(self.entry, **changes)
        body = json.dumps(dict(schema_version=1, calendars=[entry])).encode()
        (self.root/'index.json').write_bytes(body)
        return override_settings(RACE_DATA_SYNC_US_CALENDAR_SNAPSHOT_FILE=str(self.root/'index.json'),
            RACE_DATA_SYNC_US_CALENDAR_SNAPSHOT_SHA256=hashlib.sha256(body).hexdigest())

    def test_default_fetch_preserves_original_bytes_and_time_without_network(self):
        with self.config():
            store = ObservationStore(route=self.route, now=NOW, fetcher=fetch_source_page)
            doc = store.get(URL)
        self.assertEqual(doc['body'], self.raw)
        self.assertEqual(doc['fetched_at'], CAPTURED.isoformat())
        self.network.assert_not_called()

    def test_invalid_bound_inputs_fail_without_online_fallback(self):
        for changes in [dict(sha256='0'*64), dict(year=2025), dict(captured_at='2026-11-11'),
                        dict(captured_at='2099-01-01T00:00:00+00:00'), dict(file='../toba.html')]:
            with self.subTest(changes=changes), self.config(**changes), self.assertRaises(ValueError):
                fetch_source_page(URL, route=self.route, now=NOW)
        with self.config(), override_settings(RACE_DATA_SYNC_US_CALENDAR_SNAPSHOT_SHA256='0'*64), self.assertRaises(ValueError):
            fetch_source_page(URL, route=self.route, now=NOW)
        with self.config(), self.assertRaises(ValueError):
            fetch_source_page(URL.replace('2026', '2027'), route=self.route, now=NOW)
        self.network.assert_not_called()

    def test_snapshot_does_not_bypass_existing_route_and_switch_guards(self):
        with self.config():
            for field in ['RACE_DATA_SYNC_ALLOW_NETWORK', 'RACE_DATA_SYNC_ENABLED', 'RACE_DATA_MULTISOURCE_APPLY_ENABLED']:
                with self.subTest(field=field), override_settings(**{field:False}), self.assertRaises(ValueError):
                    fetch_source_page(URL, route=self.route, now=NOW)
            for field in ['valid','permits_url']:
                route = SimpleNamespace(**vars(self.route)); setattr(route, field, lambda _: False)
                with self.subTest(field=field), self.assertRaises(ValueError):
                    fetch_source_page(URL, route=route, now=NOW)
        self.network.assert_not_called()

    def test_other_sources_keep_shared_transport_and_explicit_fetchers_are_isolated(self):
        self.network.side_effect = None; self.network.return_value = b'other'
        with self.config():
            self.assertEqual(fetch_source_page('https://usracing.com/graded-stakes-schedule', route=self.route, now=NOW), b'other')
            def archive(url, **kwargs):
                raise ValueError('unlisted_source_page')
            with self.assertRaisesRegex(ValueError, 'unlisted_source_page'):
                ObservationStore(route=self.route, now=NOW, fetcher=archive).get(URL)
        self.network.assert_called_once()

    def test_prepare_checks_real_calendar_year_before_writing(self):
        from stable.services.us_calendar_snapshot import prepare_snapshot
        dest = self.root/'prepared'
        manifest = prepare_snapshot(FIX, dest, year=2026, captured_at=CAPTURED, now=NOW)
        self.assertEqual(manifest['calendars'][0]['sha256'], self.entry['sha256'])
        with self.assertRaises(ValueError):
            prepare_snapshot(FIX, self.root/'wrong', year=2025, captured_at=CAPTURED, now=NOW)
        self.assertFalse((self.root/'wrong').exists())

    def test_unknown_coverage_is_not_claimed_as_not_published(self):
        from stable.services.us_pre_race import fetch_preview
        target = dict(candidate_key='future', provider='toba', local_date='2026-11-21')
        event = SimpleNamespace(source_refs={'us_target_v1':target}, local_date=date(2026,11,21))
        for status, expected in [('awaiting_publication','coverage_unverified'), ('not_published','not_published')]:
            report = dict(targets=[dict(candidate_key='future', documents=[], errors=[], card_status=status)], documents=[], errors=[])
            with patch('stable.services.us_prerelease_collection.collect_prerace',return_value=report):
                value = fetch_preview(event, route=self.route, now=NOW, fetcher=self.network)
            self.assertEqual(value['stage'], expected)

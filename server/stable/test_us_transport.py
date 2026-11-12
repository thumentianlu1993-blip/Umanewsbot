from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch, Mock
from django.test import SimpleTestCase
from stable.services.race_pre_race import _fetch_bounded_html


class USTransportTests(SimpleTestCase):
    def test_pdf_bytes_share_budget_and_snapshot_without_text_reencoding(self):
        raw=b'%PDF-1.7\n\xff\xfe\n'
        response=Mock(status_code=200,headers={'Content-Type':'application/pdf'})
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.iter_content.return_value=[raw]
        def snapshot(**kw):
            payload,requests,used=kw['fetcher']()
            self.assertEqual(requests,1)
            return payload,used
        with patch('requests.get',return_value=response), patch('stable.services.race_data_sync_providers._get_or_fetch_shared_snapshot',side_effect=snapshot), patch('stable.services.race_events.ensure_race_live_host_budget_floor'), patch('stable.services.race_pre_race._reserve_pre_race_request',return_value=SimpleNamespace(reservation_version=1)), patch('stable.services.race_events.record_race_live_host_outcome'):
            value=_fetch_bounded_html('https://www1.drf.com/chart.pdf',now=datetime.now(timezone.utc),provider='us_racing',region='united_states',validator=lambda u:None,enabled=lambda:True,binary=True)
        self.assertEqual(bytes(value),raw)
        self.assertIsNotNone(value.observed_at)

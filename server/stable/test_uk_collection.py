"""英国付费采集编排：离线注入原件，不访问真实网络或数据库。"""
import json
from datetime import date,datetime,timezone
from types import SimpleNamespace
from unittest import TestCase
from stable.test_uk_sources import card,result
from stable.services.uk_collection import fetch_payload, api_url

NOW=datetime(2026,10,30,16,tzinfo=timezone.utc)
class Query:
    def filter(self,**kwargs):return self
    def first(self):return None


def event():
    return SimpleNamespace(country_region='united_kingdom',local_date=date(2026,10,30),
        racecourse='Newmarket',original_name='Example Stakes',source_identities=Query(),
        source_refs={'uk_target_v1':{'external_race_id':'rac_123','name_keys':['examplestakes']}},
        runners=Query())


def route():
    from urllib.parse import urlsplit
    return SimpleNamespace(provider='the_racing_api',region='united_kingdom',parser_version='uk-tra-paid-v1',
        identity_namespace='tra-race',operator='TRA',source_class='licensed_api',timezone='Europe/London',
        valid=lambda now:True,permits_url=lambda url:urlsplit(url).hostname in {'api.theracingapi.com','www.sportinglife.com'},
        venue_aliases={'newmarket':['Newmarket']},digest='a'*64)


class UKCollectionTests(TestCase):
    def test_reads_bound_card_and_result_without_free_paths(self):
        c=card();c['runners'].pop();r=result();r['non_runners']='';calls=[]
        def fetch(url,**kwargs):
            calls.append(url)
            return json.dumps(r if '/results/' in url else c)
        value=fetch_payload(event=event(),route=route(),now=NOW,fetcher=fetch)
        self.assertEqual(len(value['roster']),2)
        self.assertEqual(value['result_phase'],'official')
        self.assertEqual(calls,['https://api.theracingapi.com/v1/racecards/rac_123/pro','https://api.theracingapi.com/v1/results/rac_123'])
        self.assertEqual(len(value['source_documents']),2)

    def test_entry_is_preview_only(self):
        c=card();c['race_status']='entry';c['field_size']='3'
        for x in c['runners']:x['number']=''
        value=fetch_payload(event=event(),route=route(),now=NOW,fetcher=lambda *a,**k:json.dumps(c))
        self.assertEqual(value['stage'],'nominations')
        self.assertFalse(value['roster_complete'])

    def test_binding_cannot_cross_date_venue_or_region(self):
        for key,value in [('date','2026-10-29'),('course','Ascot'),('region','IRE')]:
            c=card();c[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):fetch_payload(event=event(),route=route(),now=NOW,fetcher=lambda *a,**k:json.dumps(c))

    def test_discovery_rejects_ambiguous_candidates(self):
        e=event();e.source_refs['uk_target_v1'].pop('external_race_id')
        c=card();c['race_status']='declared';other=dict(c,race_id='rac_124')
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            fetch_payload(event=e,route=route(),now=NOW,fetcher=lambda *a,**k:{'racecards':[c,other],'total':2})

    def test_empty_list_is_not_published_and_count_drift_fails(self):
        e=event();e.source_refs['uk_target_v1'].pop('external_race_id')
        value=fetch_payload(event=e,route=route(),now=NOW,fetcher=lambda *a,**k:{'racecards':[],'total':0})
        self.assertEqual(value['stage'],'not_published')
        with self.assertRaisesRegex(ValueError,'pagination'):
            fetch_payload(event=e,route=route(),now=NOW,fetcher=lambda *a,**k:{'racecards':[],'total':2})

    def test_near_term_entry_falls_back_to_big_races(self):
        e=event();e.source_refs['uk_target_v1'].pop('external_race_id')
        c=card();c.update(race_status='entry',field_size='3')
        def fetch(url,**kwargs):
            return {'racecards':[c],'total':1} if '/big-races?' in url else {'racecards':[],'total':0}
        value=fetch_payload(event=e,route=route(),now=NOW,fetcher=fetch)
        self.assertEqual(value['stage'],'nominations')

    def test_late_nonrunner_retains_verified_original_card_number(self):
        from stable.services.uk_sources import parse_card
        e=event();c=card();c['runners'][2]['number']='3';c.update(race_status='declared',field_size='3')
        old=parse_card(c)
        old.update(raw_sha256='c'*64,canonical_url=api_url('card',race_id='rac_123'),fetched_at=NOW.isoformat())
        e.source_identities=SimpleNamespace(filter=lambda **kwargs:SimpleNamespace(first=lambda:SimpleNamespace(external_race_id='rac_123',identity_fields={'multisource_v2':old})))
        c['runners'][2]['number']='NR';c['field_size']='2'
        value=fetch_payload(event=e,route=route(),now=NOW,fetcher=lambda *a,**k:c)
        self.assertEqual(value['gaps'],[])
        self.assertEqual(value['roster'][2]['number'],'3')
        self.assertEqual(value['roster'][2]['status'],'non_runner')

    def test_url_builder_rejects_unbounded_identity(self):
        for race_id in ['../secret','rac_123?key=bad','https://evil.test','123']:
            with self.subTest(race_id=race_id),self.assertRaises(ValueError):api_url('card',race_id=race_id)


from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase, override_settings


class UKPaidRuntimeTransportTests(SimpleTestCase):
    """真实运行时发送路径，只替换 DNS/HTTP 与共享预算存储。"""

    def _connection(self):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"racecards": [], "total": 0}'
        response.getheader.side_effect = lambda name, default=None: (
            'application/json' if name == 'Content-Type' else default
        )
        return connection

    def test_paid_urls_reach_pinned_http_transport(self):
        from stable.services import race_live_source_proof as service
        urls = [api_url('card', race_id='rac_123'), api_url('result', race_id='rac_123'),
                api_url('cards', day='2026-11-13'), api_url('cards', day='2026-11-13', skip=180),
                api_url('big', start='2026-11-13', end='2027-01-12')]
        for url in urls:
            with self.subTest(url=url), patch.object(service, '_resolve_public_addresses', return_value=['8.8.8.8']), \
                    patch.object(service, '_PinnedHTTPSConnection', return_value=self._connection()) as connection:
                response = service.the_racing_api_transport(endpoint_name='uk_paid', url=url,
                    username='offline', password='offline', timeout_seconds=15,
                    max_response_bytes=1024, allow_redirects=False)
                self.assertEqual(response.status_code, 200)
                connection.return_value.request.assert_called_once()
                connection.return_value.close.assert_called_once()

    @override_settings(RACE_DATA_SYNC_ENABLED=True, RACE_DATA_SYNC_ALLOW_NETWORK=True,
                       RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
                       RACE_DATA_SYNC_ENABLED_PROVIDERS=('the_racing_api',),
                       RACE_DATA_SYNC_ENABLED_REGIONS=('united_kingdom',))
    def test_runtime_json_keeps_real_response_validation_and_transport(self):
        from stable.services import race_live_source_proof as service
        from stable.services import race_data_sync_providers as providers
        from stable.services.uk_collection import _runtime_json
        def snapshot(**kwargs):
            payload, pages, count = kwargs['fetcher']()
            return payload, 'snapshot'
        with patch.object(providers, '_get_or_fetch_shared_snapshot', side_effect=snapshot), \
                patch.object(providers, 'reserve_race_live_host_request', return_value=SimpleNamespace(reserved=True, reservation_version=1)), \
                patch.object(providers, 'record_race_live_host_outcome', return_value=SimpleNamespace(recorded=True)), \
                patch('stable.services.race_events.ensure_race_live_host_budget_floor'), \
                patch.object(service, '_read_secret', return_value=('offline', 'offline')), \
                patch.object(service, '_resolve_public_addresses', return_value=['8.8.8.8']), \
                patch.object(service, '_PinnedHTTPSConnection', return_value=self._connection()):
            value = _runtime_json(api_url('cards', day='2026-11-13'), route=route(), now=NOW)
        self.assertEqual(value['response'], {'racecards': [], 'total': 0})
        self.assertEqual(len(value['raw_sha256']), 64)

    def test_paid_route_rejects_outside_scope_before_dns(self):
        from stable.services import race_live_source_proof as service
        url = api_url('cards', day='2026-11-13')
        requests = [('uk_paid', url.replace('region_codes=gb', 'region_codes=ire')),
                    ('uk_paid', url.replace('limit=20', 'limit=500')),
                    ('uk_paid', url.replace('skip=0', 'skip=200')),
                    ('uk_paid', url.replace('skip=0', 'skip=1')),
                    ('uk_paid', url.replace('2026-11-13', '2026-02-30')),
                    ('uk_paid', url+'&region_codes=gb'), ('uk_paid', url+'&extra=1'),
                    ('uk_paid', url.replace('https:', 'http:')),
                    ('uk_paid', url.replace('api.theracingapi.com', 'example.com')),
                    ('uk_paid', url+'#fragment'), ('results_today', url),
                    ('uk_paid', api_url('card', race_id='rac_123')+'?x=1'),
                    ('uk_paid', api_url('result', race_id='rac_123').replace('rac_123', 'rac_123/extra')),
                    ('uk_paid', api_url('big', start='2026-11-13', end='2027-01-12').replace('2027-01-12', '2027-01-13'))]
        with patch.object(service, '_resolve_public_addresses') as resolver:
            for name, target in requests:
                with self.subTest(url=target), self.assertRaises((PermissionError, ValueError)):
                    service.the_racing_api_transport(endpoint_name=name, url=target,
                        username='offline', password='offline', timeout_seconds=15,
                        max_response_bytes=1024, allow_redirects=False)
            resolver.assert_not_called()

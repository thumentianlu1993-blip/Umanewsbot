"""只读仓库合成fixture的独立副本；原件和旧日期不变，不访问真实缓存。"""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from stable.services.horse_source_cache_reuse_adapter import (
    CacheReuseAdapterError, adapt_hkjc_source_cache,
)
from stable.services.horse_cache_reuse import plan_cache_reuse
from stable.test_horse_target_inventory import document, event, row, identity

FIXTURE = Path(__file__).parent / 'fixtures/p0_horse_completion/hong_kong.json'
URL = 'https://racing.hkjc.com/racing/information/English/Horse/Horse.aspx?HorseId=HK-001'


def payload():
    p = json.loads(FIXTURE.read_bytes())
    # Test-only source URL substitution; does not turn example.test into real evidence.
    p['source']['url'] = URL
    return p


def encoded(p):
    return (json.dumps(p, ensure_ascii=False, indent=2) + '\n').encode()


def h01():
    p = document()
    p.update(events=[event()], participations=[row(horse_key='hkjc:HK-001')],
             identities=[identity('hkjc:HK-001')])
    return p


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 3, tzinfo=timezone.utc).astimezone(tz) if tz else cls(2026, 10, 3)


class HKJCCacheAdapterTests(SimpleTestCase):
    databases = set()

    def setUp(self):
        super().setUp()
        self.clock = patch('stable.services.p0_horse_completion_source_clients.datetime', FrozenDateTime)
        self.clock.start(); self.addCleanup(self.clock.stop)
        for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                       'urllib.request.urlopen',
                       'django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection',
                       'stable.services.p0_horse_completion_adapters.run_p0_horse_completion_adapter',
                       'stable.services.p0_horse_completion_source_clients._HKJCClient._fetch'):
            guard = patch(target, side_effect=AssertionError('DB/network/producer forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def adapt(self, p=None, raw=None, expected=None, **kw):
        data = raw if raw is not None else encoded(p if p is not None else payload())
        return adapt_hkjc_source_cache(data, expected_sha256=expected if expected is not None else hashlib.sha256(data).hexdigest(),
                                       ref=kw.pop('ref','cache:c1'), source_ref=kw.pop('source_ref','fixture:hkjc'), **kw)

    def reject(self, raw, code):
        with self.assertRaises(CacheReuseAdapterError) as e: self.adapt(raw=raw)
        self.assertEqual(e.exception.code, code)
        self.assertEqual(str(e.exception), code)

    def test_original_bytes_hash_old_time_and_null_profile_preserved(self):
        data = encoded(payload())
        record = self.adapt(raw=data)
        self.assertIsInstance(record, dict)
        self.assertEqual(record['content'].encode(), data)
        self.assertEqual(record['content_sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(record['source_time'], '2026-07-18T00:00:00Z')
        self.assertEqual(record['horse_key'], 'hkjc:HK-001')
        self.assertIsNone(record['profile_id'])
        self.assertEqual(record['parse_status'], 'complete')

    def test_original_example_fixture_is_not_provider_evidence(self):
        self.reject(FIXTURE.read_bytes(), 'provider_origin')

    def test_hash_checked_before_json_or_validator(self):
        with patch('json.loads', side_effect=AssertionError('must not parse')):
            with self.assertRaises(CacheReuseAdapterError) as e: self.adapt(raw=b'not-json', expected='a'*64)
        self.assertEqual(e.exception.code, 'content_hash_mismatch')
        for expected in (None, '', 'bad', True):
            with self.subTest(expected=expected), self.assertRaises(CacheReuseAdapterError) as e:
                adapt_hkjc_source_cache(encoded(payload()), expected_sha256=expected, ref='cache:c1', source_ref='fixture:hkjc')
            self.assertEqual(e.exception.code, 'content_hash_unbound')

    def test_tamper_or_route_digest_cannot_replace_expected_content_digest(self):
        raw = encoded(payload()); sha = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(CacheReuseAdapterError) as e: self.adapt(raw=raw+b' ', expected=sha)
        self.assertEqual(e.exception.code, 'content_hash_mismatch')
        with self.assertRaises(CacheReuseAdapterError):
            self.adapt(raw=raw, expected=hashlib.sha256(b'external:hkjc:HK-001').hexdigest())

    def test_strict_url_origin_path_port_and_credentials(self):
        urls = [URL.replace('https:', 'http:'), URL.replace('racing.hkjc.com','example.test'),
                URL.replace('racing.hkjc.com','racing.hkjc.com.evil.test'),
                URL.replace('racing.hkjc.com','user:secret@racing.hkjc.com'),
                URL.replace('racing.hkjc.com','racing.hkjc.com:444'), URL+'#fragment',
                URL.replace('Horse.aspx','Other.aspx'), URL+'\n', 'https://[invalid']
        for url in urls:
            with self.subTest(url=url):
                p=payload();p['source']['url']=url;self.reject(encoded(p),'provider_origin')

    def test_exact_single_horseid_not_name_or_four_field_fallback(self):
        for query in ('HorseId=other', 'HorseId=HK-001&HorseId=HK-001',
                      'HorseId=HK-001&horseid=HK-001', 'HorseId=', 'HorseId=HK-001&foo=x'):
            p=payload();p['source']['url']=URL.split('?')[0]+'?'+query
            self.reject(encoded(p),'provider_identity_url')
        for value in ('', None, '__legacy_existing_cache_validation_only__', 'with space'):
            p=payload();p['source']['external_horse_id']=value
            self.reject(encoded(p),'stable_identity_missing')

    def test_json_utf8_duplicates_nonfinite_and_limits(self):
        for raw in (b'\xff',): self.reject(raw,'cache_utf8')
        for raw in (b'{', b'[]', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            self.reject(raw,'cache_json')
        self.reject(b'x'*131073,'cache_size')
        with self.assertRaises(CacheReuseAdapterError) as e:self.adapt(raw='notbytes', expected='a'*64)
        self.assertEqual(e.exception.code,'cache_bytes')

    def test_source_format_scope_and_locator_keys(self):
        for field, value in (('schema_version','old'), ('region','japan'), ('adapter_key','wrong')):
            p=payload();p[field]=value;self.reject(encoded(p),'cache_scope')
        p=payload();p['source']['name']='other';self.reject(encoded(p),'cache_scope')
        with self.assertRaises(CacheReuseAdapterError) as e:self.adapt(ref='/private/path')
        self.assertEqual(e.exception.code,'cache_locator')

    def test_strict_validation_missing_fields_partial_career_and_manual_marker(self):
        for mutate in ('field', 'count', 'records', 'manual'):
            p=payload()
            if mutate=='field':p['basic_profile'].pop('trainer_name')
            if mutate=='count':p['career']['source_start_count']=2
            if mutate=='records':p['career']['records']=[]
            if mutate=='manual':p['manual_supplements']=[{'secret':'do not output'}]
            with self.subTest(mutate=mutate):self.reject(encoded(p),'cache_validation')

    def test_missing_naive_and_bad_source_time_rejected_no_mtime_fallback(self):
        for val in ('',None,'2026-07-18T00:00:00','bad'):
            p=payload();p['source']['fetched_at']=val
            self.reject(encoded(p),'source_time')

    def test_old_cache_refresh_and_explicit_fresh_boundary(self):
        record=self.adapt()
        x=plan_cache_reuse(h01(),[record],{'profile:1':'v1'},as_of='2026-10-03T01:00:00+00:00',max_age_seconds=3600)
        self.assertEqual(x['decisions'][0]['status'],'refresh_required')
        self.assertIsNone(x['candidates'][0]['content'])
        x=plan_cache_reuse(h01(),[record],{'profile:1':'v1'},as_of='2026-10-03T01:00:00+00:00',max_age_seconds=77*86400+3600)
        self.assertEqual(x['decisions'][0]['status'],'reusable')

    def test_future_source_time_preserved_then_h02_insufficient(self):
        p=payload();p['source']['fetched_at']='2026-10-04T00:00:00Z'
        r=self.adapt(p=p)
        self.assertEqual(r['source_time'],p['source']['fetched_at'])
        x=plan_cache_reuse(h01(),[r],{'profile:1':'v1'},as_of='2026-10-03T01:00:00Z',max_age_seconds=3600)
        self.assertEqual(x['decisions'][0]['status'],'insufficient')
        self.assertEqual(x['candidates'],[])

    def test_identity_unresolved_retired_conflict_and_staging_are_not_overridden(self):
        r=self.adapt()
        for status in ('missing','retired','conflict'):
            p=h01()
            if status=='missing':p['identities']=[]
            if status=='retired':p['identities'][0]['status']='retired'
            if status=='conflict':p['identities'].append(identity('hkjc:HK-001',profile=2))
            x=plan_cache_reuse(p,[r],{'source:hkjc:HK-001':'v1'},as_of='2026-10-03T01:00:00Z',max_age_seconds=10**8)
            self.assertEqual(len(x['decisions']),1);self.assertEqual(x['candidates'],[])
        p=h01();p['layers']=[dict(target_key='profile:1',cache='present',staging='matched',profile_exists=False,public_state='unpublished',starts=None,incomplete_modules=None)]
        x=plan_cache_reuse(p,[r],{'profile:1':'v1'},as_of='2026-10-03T01:00:00Z',max_age_seconds=10**8)
        self.assertEqual(x['decisions'][0]['public_state'],'unpublished');self.assertFalse(x['published'])

    def test_rejected_record_does_not_drop_h01_target(self):
        rejected=[]
        try:self.adapt(expected='a'*64)
        except CacheReuseAdapterError as e:rejected.append({'ref':'cache:c1','reason':e.code})
        x=plan_cache_reuse(h01(),[],{'profile:1':'v1'},as_of='2026-10-03T01:00:00Z',max_age_seconds=3600)
        self.assertEqual(rejected,[{'ref':'cache:c1','reason':'content_hash_mismatch'}])
        self.assertEqual(len(x['decisions']),1);self.assertEqual(x['decisions'][0]['status'],'refresh_required')

    def test_same_input_owned_output_and_entity_version_dedup(self):
        r=self.adapt(); r2=self.adapt(ref='cache:c2'); p=h01(); original=deepcopy((p,r,r2))
        a=plan_cache_reuse(p,[r,r2],{'profile:1':'v1'},as_of='2026-10-03T01:00:00Z',max_age_seconds=10**8)
        b=plan_cache_reuse(p,[r2,r],{'profile:1':'v1'},as_of='2026-10-03T01:00:00Z',max_age_seconds=10**8)
        self.assertEqual(a,b);self.assertEqual(len(a['candidates']),1);self.assertEqual((p,r,r2),original)
        r['content']='mutated';self.assertNotEqual(r,self.adapt())

    def test_hash_failure_never_calls_strict_validator(self):
        with patch('stable.services.p0_horse_completion_source_clients.validate_p0_horse_source_cache',
                   side_effect=AssertionError('must not validate')) as validator:
            with self.assertRaises(CacheReuseAdapterError):self.adapt(expected='f'*64)
            validator.assert_not_called()

    def test_equivalent_utc_string_and_percent_encoded_id_preserved(self):
        p=payload();p['source']['url']=URL.replace('HK-001','HK%2D001')
        p['source']['fetched_at']='2026-07-18T00:00:00+00:00'
        x=self.adapt(p=p)
        self.assertEqual(x['horse_key'],'hkjc:HK-001')
        self.assertEqual(x['source_time'],'2026-07-18T00:00:00+00:00')
        p['source']['fetched_at']='2026-07-18T08:00:00+08:00'
        self.reject(encoded(p),'source_time')

    def test_nested_duplicate_key_and_invalid_shape_do_not_leak_content(self):
        p=payload()
        raw=encoded(p).replace(b'"name": "hkjc"',b'"name": "hkjc", "name": "secret"')
        self.reject(raw,'cache_json')
        p['source']=None
        self.reject(encoded(p),'cache_scope')

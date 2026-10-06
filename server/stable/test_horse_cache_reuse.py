"""全部合成合同样例；不访问 DB、网络、缓存目录或生产。"""
import copy
import hashlib
import unittest
from stable.services.horse_cache_reuse import plan_cache_reuse
from stable.test_horse_target_inventory import document, event, row, identity


def snapshot():
    p = document()
    p.update(events=[event()], participations=[row()], identities=[identity()])
    return p


def cache(ref='c1', **changes):
    text = '{"name":"Synthetic Horse"}'
    return {**dict(ref=ref, horse_key='jra:1', profile_id=1,
                   source_time='2026-10-03T00:00:00+00:00', source_ref='fixture:c1',
                   content=text, content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                   parse_status='complete'), **changes}


class CacheReuseTests(unittest.TestCase):
    def plan(self, records=None, p=None, versions=None, **kw):
        return plan_cache_reuse(p or snapshot(), records if records is not None else [cache()],
                                versions if versions is not None else {'profile:1': 'v1'},
                                as_of=kw.pop('as_of', '2026-10-03T01:00:00+00:00'),
                                max_age_seconds=kw.pop('max_age_seconds', 3600), **kw)

    def test_fresh_at_boundary_reuses_without_publication_claim(self):
        result = self.plan()
        self.assertEqual([d['status'] for d in result['decisions']], ['reusable'])
        self.assertEqual(result['candidates'][0]['entity_key'], 'profile:1')
        self.assertEqual(result['candidates'][0]['content'], cache()['content'])
        self.assertEqual(result['decisions'][0]['public_state'], 'unknown')

    def test_expired_missing_partial_or_bad_hash_need_refresh(self):
        cases = [([], 'cache_missing'), ([cache(source_time='2026-10-02T00:00:00+00:00')], 'cache_expired'),
                 ([cache(parse_status='partial')], 'cache_partial'),
                 ([cache(content_sha256='f'*64)], 'content_hash_mismatch')]
        for records, reason in cases:
            with self.subTest(reason=reason):
                x = self.plan(records)
                self.assertEqual(x['decisions'][0]['status'], 'refresh_required')
                self.assertIn(reason, x['decisions'][0]['reasons'])
                self.assertIsNone(x['candidates'][0]['content'])

    def test_missing_provenance_or_future_cache_never_reused(self):
        for change, reason in [({'source_time': None}, 'source_time_missing'),
                               ({'content_sha256': None}, 'content_hash_missing'),
                               ({'source_time': '2026-10-03T02:00:00+00:00'}, 'source_time_future')]:
            x = self.plan([cache(**change)])
            self.assertEqual(x['decisions'][0]['status'], 'insufficient')
            self.assertIn(reason, x['decisions'][0]['reasons'])
            self.assertEqual(x['candidates'], [])

    def test_identity_conflict_blocks_even_a_valid_cache(self):
        p = snapshot(); p['identities'].append(identity(profile=2))
        x = self.plan(p=p, versions={'source:jra:1': 'v1'})
        self.assertEqual(x['decisions'][0]['status'], 'identity_conflict')
        self.assertEqual(x['candidates'], [])
        x = self.plan([cache(profile_id=2)])
        self.assertEqual(x['decisions'][0]['status'], 'identity_conflict')

    def test_unverified_identity_and_missing_version_kept_as_gaps(self):
        p = snapshot(); p['identities'] = []
        x = self.plan(p=p, versions={'source:jra:1': 'v1'})
        self.assertEqual(x['decisions'][0]['status'], 'insufficient')
        self.assertEqual(x['candidates'], [])
        self.assertIn('entity_version_missing', self.plan(versions={})['decisions'][0]['reasons'])

    def test_conflicting_equal_time_payload_not_arbitrarily_selected(self):
        c = cache('c2', content='changed', content_sha256=hashlib.sha256(b'changed').hexdigest())
        x = self.plan([cache(), c])
        self.assertEqual(x['decisions'][0]['status'], 'cache_conflict')
        self.assertEqual(x['candidates'], [])

    def test_latest_partial_does_not_fall_back_to_older_good_cache(self):
        x = self.plan([cache(source_time='2026-10-02T23:00:00+00:00'), cache('c2', parse_status='partial')])
        self.assertEqual(x['decisions'][0]['status'], 'refresh_required')
        self.assertEqual(x['decisions'][0]['cache_refs'], ['c2'])

    def test_cross_source_identity_dedup_and_version_idempotency(self):
        p = snapshot(); p['identities'].append(identity('hkjc:2'))
        p['participations'].append(row('r2', horse_key='hkjc:2', participant_key='p2'))
        p['events'][0]['known_roster_count'] = 2
        records = [cache(), cache('c2', horse_key='hkjc:2')]
        x = self.plan(records, p)
        self.assertEqual(len(x['candidates']), 1)
        self.assertEqual(x['candidates'][0]['cache_refs'], ['c1', 'c2'])
        self.assertEqual(x['candidates'][0]['identity_evidence'][0]['evidence_sha'], 'b'*64)
        self.assertEqual(x, self.plan(list(reversed(records)), p))
        self.assertEqual(x['candidates'][0]['idempotency_key'], self.plan(records, p)['candidates'][0]['idempotency_key'])
        self.assertNotEqual(x['candidates'][0]['idempotency_key'], self.plan(records, p, {'profile:1': 'v2'})['candidates'][0]['idempotency_key'])

    def test_staging_only_is_not_public_and_unrelated_horse_not_matched_by_name(self):
        p = snapshot()
        p['layers'] = [dict(target_key='profile:1',cache='present',staging='matched',profile_exists=False,
                            public_state='unpublished',starts=None,incomplete_modules=None)]
        x = self.plan([cache(horse_key='jra:other')], p)
        self.assertEqual(x['decisions'][0]['status'], 'refresh_required')
        self.assertEqual(x['decisions'][0]['public_state'], 'unpublished')
        self.assertEqual(x['unused_cache_refs'], ['c1'])

    def test_owned_output_and_policy_hash_determinism(self):
        p=snapshot(); records=[cache()]; original=copy.deepcopy((p,records))
        x=self.plan(records,p); self.assertEqual((p,records),original)
        digest=x['content_sha256']; x['candidates'][0]['identity_evidence'].clear()
        self.assertEqual(self.plan(records,p)['content_sha256'], digest)
        self.assertNotEqual(digest,self.plan(records,p,max_age_seconds=3599)['content_sha256'])

    def test_bad_schema_timezone_limits_and_duplicate_refs_rejected(self):
        for options in ({'max_age_seconds': True}, {'max_age_seconds': -1}, {'as_of': '2026-10-03T01:00:00'}):
            with self.assertRaises(ValueError): self.plan(**options)
        for records in ([cache(),cache()], [cache(parse_status='guess')], [cache(content=1)],
                        [cache(source_time='bad')], [cache(content_sha256='bad')]):
            with self.assertRaises(ValueError): self.plan(records)
        with self.assertRaises(ValueError):self.plan(versions={'profile:1':True})

    def test_revoked_key_not_recovered_by_cache_claim(self):
        p = snapshot(); p['identities'][0]['status'] = 'retired'
        x = self.plan(p=p, versions={'source:jra:1':'v1'})
        self.assertEqual(x['decisions'][0]['status'],'insufficient')
        self.assertEqual(x['candidates'],[])

    def test_different_horses_same_payload_not_deduplicated(self):
        p=snapshot(); p['identities'].append(identity('jra:2',profile=2))
        p['participations'].append(row('r2',horse_key='jra:2',participant_key='p2'))
        p['events'][0]['known_roster_count']=2
        x=self.plan([cache(),cache('c2',horse_key='jra:2',profile_id=2)],p,
                    {'profile:1':'v1','profile:2':'v1'})
        self.assertEqual(len(x['candidates']),2)
        self.assertNotEqual(x['candidates'][0]['idempotency_key'],x['candidates'][1]['idempotency_key'])

    def test_future_snapshot_and_oversized_content_rejected(self):
        with self.assertRaisesRegex(ValueError,'snapshot_time_future'):
            self.plan(as_of='2026-10-02T23:00:00+00:00')
        with self.assertRaisesRegex(ValueError,'cache_content_limit'):
            self.plan([cache(content='x'*131073)])

    def test_timezone_equal_instant_does_not_create_arbitrary_winner(self):
        x=self.plan([cache(),cache('c2',source_time='2026-10-03T08:00:00+08:00')])
        self.assertEqual(x['decisions'][0]['cache_refs'],['c1','c2'])
        self.assertEqual(x['decisions'][0]['status'],'reusable')

    def test_input_order_does_not_change_h01_priority_or_ownership(self):
        p=snapshot(); p['identities'].append(identity('hkjc:2'))
        p['participations'].append(row('r2',horse_key='hkjc:2',participant_key='p2'))
        p['events'][0]['known_roster_count']=2
        x=self.plan(p=p)
        p['identities'].reverse();p['participations'].reverse()
        self.assertEqual(x,self.plan(p=p))

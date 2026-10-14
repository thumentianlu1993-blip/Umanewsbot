"""Explicit synthetic verdicts; standard library only, no DB/provider execution."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
import hashlib
import json

from stable.services.race_source_arbitration import (
    Observation, FreshnessVerdict, ResultField, arbitrate_result_sources,
)

NOW=datetime(2026,10,14,10,tzinfo=timezone.utc)


def obs(ref, *, priority=100, state='fresh', winner='horse:a', origin=None):
    fields=(ResultField('winner',winner,ref+':winner'),ResultField('finish:horse:a','1',ref+':finish'))
    digest=hashlib.sha256(json.dumps(sorted((f.name,f.value) for f in fields),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return Observation(ref,'version:'+ref,'event:a',3,'provider:'+ref,origin or 'origin:'+ref,
                       priority,'allowed','healthy','matched','confirmed',True,True,False,
                       NOW-timedelta(minutes=2),
                       FreshnessVerdict(state,'asserted-test-rule',ref,'version:'+ref,NOW-timedelta(minutes=1),NOW+timedelta(minutes=1),digest),fields)


def decide(current, candidates=(), **changes):
    args=dict(event_key='event:a',generation=3,as_of=NOW,expected_fields=('winner','finish:horse:a'),current=current,candidates=candidates)
    args.update(changes);return arbitrate_result_sources(**args)


class ArbitrationTests(unittest.TestCase):
    def test_stale_300_selects_fresh_qualified_100_backup(self):
        current=obs('api',priority=300,state='stale');backup=obs('publisher')
        result=decide(current,(backup,))
        self.assertEqual(result.action,'SELECT_BACKUP')
        self.assertEqual(result.selected_observation_ref,'publisher')
        self.assertEqual(result.retained_version_ref,'version:api')
        self.assertEqual(dict(result.field_refs),{'winner':'publisher:winner','finish:horse:a':'publisher:finish'})
        self.assertFalse(result.authenticated);self.assertFalse(result.publication_authorized)
    def test_empty_current_selects_given_qualified_publisher(self):
        self.assertEqual(decide(None,(obs('publisher'),)).action,'SELECT_CANDIDATE')
    def test_new_prediction_and_partial_do_not_downgrade(self):
        for candidate in (replace(obs('later'),maturity='predicted'),replace(obs('partial'),complete=False)):
            self.assertEqual(decide(obs('current'),(candidate,)).action,'KEEP')
    def test_independent_fresh_conflict_precedes_rank(self):
        result=decide(obs('current',priority=300),(obs('backup',winner='horse:b'),))
        self.assertEqual(result.action,'CONFLICT');self.assertIsNone(result.selected_observation_ref)
        self.assertEqual(result.retained_version_ref,'version:current');self.assertEqual(result.blocked_capability,'result')
    def test_same_origin_conflict_not_deduped_away(self):
        self.assertEqual(decide(None,(obs('a',origin='same'),obs('b',origin='same',winner='horse:b'))).action,'CONFLICT')
    def test_mirrors_do_not_outvote_independent_conflict(self):
        candidates=(obs('mirror1',origin='same'),obs('mirror2',origin='same'),obs('other',winner='horse:b'))
        self.assertEqual(decide(None,candidates).action,'CONFLICT')
    def test_missing_rule_unknown_time_future_revoked_generation_no_select(self):
        base=obs('candidate')
        bads=[replace(base,freshness=replace(base.freshness,rule_ref=None)),replace(base,content_at=None),
              replace(base,content_at=NOW+timedelta(seconds=1)),replace(base,revoked=True),replace(base,generation=2),
              replace(base,admission='unknown'),replace(base,identity='unknown'),replace(base,health='failed'),
              replace(base,freshness=replace(base.freshness,state='unknown'))]
        for candidate in bads:
            with self.subTest(candidate=candidate):
                result=decide(None,(candidate,));self.assertEqual(result.action,'NEEDS_EVIDENCE');self.assertIsNone(result.selected_observation_ref)
    def test_verdict_matches_ref_version_as_of_and_content_time(self):
        base=obs('candidate')
        for verdict in [replace(base.freshness,observation_ref='other'),replace(base.freshness,version_ref='other'),
                        replace(base.freshness,assessed_at=NOW+timedelta(seconds=1)),replace(base.freshness,valid_until=NOW),
                        replace(base.freshness,assessed_at=base.content_at-timedelta(seconds=1))]:
            self.assertEqual(decide(None,(replace(base,freshness=verdict),)).action,'NEEDS_EVIDENCE')
    def test_unknown_current_retains_without_select(self):
        self.assertEqual(decide(obs('current',state='unknown'),(obs('backup'),)).action,'NEEDS_EVIDENCE')
    def test_manual_keep_does_not_wash_bad_current(self):
        current=replace(obs('current',state='unknown'),revoked=True)
        result=decide(current,(obs('backup'),),manual_locked=True)
        self.assertEqual(result.action,'KEEP');self.assertEqual(result.reason,'manual_lock')
        self.assertIsNone(result.selected_observation_ref);self.assertIsNone(result.result_sha256)
    def test_field_coverage_missing_not_select(self):
        candidate=replace(obs('candidate'),fields=(ResultField('winner','horse:a','candidate:winner'),))
        self.assertEqual(decide(None,(candidate,)).action,'NEEDS_EVIDENCE')
    def test_order_field_order_and_exact_replay_stable(self):
        a=obs('a');b=obs('b');permuted=replace(a,fields=tuple(reversed(a.fields)))
        first=decide(None,(a,b));second=decide(None,(b,permuted,a))
        self.assertEqual(first,second);self.assertEqual(first.selected_observation_ref,'a')
    def test_equivalent_timezone_times_identical(self):
        a=obs('a');zone=timezone(timedelta(hours=8))
        b=replace(a,content_at=a.content_at.astimezone(zone),freshness=replace(a.freshness,assessed_at=a.freshness.assessed_at.astimezone(zone),valid_until=a.freshness.valid_until.astimezone(zone)))
        self.assertEqual(decide(None,(a,)),decide(None,(b,)))
    def test_valid_current_equal_result_keeps_current(self):
        result=decide(obs('current',priority=100),(obs('api',priority=300),))
        self.assertEqual(result.action,'KEEP');self.assertIsNone(result.selected_observation_ref)
    def test_empty_or_stale_candidates_keep_evidence_gap(self):
        self.assertEqual(decide(None,()).action,'NEEDS_EVIDENCE')
        self.assertEqual(decide(obs('current',state='stale'),(obs('other',state='stale'),)).action,'NEEDS_EVIDENCE')
    def test_bad_types_naive_clock_duplicate_ref_fail_closed(self):
        for changes in [dict(as_of=NOW.replace(tzinfo=None)),dict(generation=True),dict(expected_fields=('winner','winner'))]:
            with self.assertRaises(ValueError):decide(None,(obs('a'),),**changes)
        with self.assertRaises(ValueError):decide(None,(obs('a'),replace(obs('a'),priority=300)))
    def test_mismatched_current_event_cannot_retain_or_replace(self):
        result=decide(replace(obs('current'),event_key='other'),(obs('backup'),))
        self.assertEqual(result.action,'NEEDS_EVIDENCE');self.assertIsNone(result.selected_observation_ref)
    def test_input_bounds_and_no_mutation(self):
        base=obs('a');original=base
        with self.assertRaises(ValueError):decide(None,(base,)*257)
        with self.assertRaises(ValueError):decide(None,(replace(base,qualified=1),))
        with self.assertRaises(ValueError):decide(None,(replace(base,fields=(ResultField('winner','x'*4097,'e'),)),))
        decide(None,(base,));self.assertEqual(base,original)
    def test_digest_binding_missing_or_changed_no_selection(self):
        base=obs('a')
        for digest in (None,'0'*64):
            result=decide(None,(replace(base,freshness=replace(base.freshness,result_sha256=digest)),))
            self.assertEqual(result.action,'NEEDS_EVIDENCE')
        changed=replace(base,fields=(ResultField('winner','horse:b','a:winner'),base.fields[1]))
        self.assertEqual(decide(None,(changed,)).action,'NEEDS_EVIDENCE')
    def test_time_sort_preserves_microseconds_at_extreme_date(self):
        far=datetime(9999,12,31,23,59,50,tzinfo=timezone.utc)
        a=obs('a');z=obs('z')
        def timed(o,offset):
            return replace(o,content_at=far-timedelta(seconds=2)+timedelta(microseconds=offset),
                           freshness=replace(o.freshness,assessed_at=far-timedelta(seconds=1),valid_until=far+timedelta(seconds=1)))
        self.assertEqual(decide(None,(timed(a,0),timed(z,1)),as_of=far).selected_observation_ref,'z')
    def test_malformed_field_and_naive_source_times_value_error(self):
        base=obs('a')
        for bad in (replace(base,fields=(ResultField([], '1','e'),)),
                    replace(base,content_at=NOW.replace(tzinfo=None)),
                    replace(base,freshness=replace(base.freshness,assessed_at=NOW.replace(tzinfo=None)))):
            with self.assertRaises(ValueError):decide(None,(bad,))
    def test_total_input_text_bound_and_empty_value_not_complete(self):
        fields=tuple(ResultField('f:'+str(n),'x'*2048,'e:'+str(n)) for n in range(128))
        with self.assertRaises(ValueError):
            decide(None,tuple(replace(obs(str(n)),fields=fields) for n in range(6)))
        empty=replace(obs('empty'),fields=(ResultField('winner','','e'),ResultField('finish:horse:a','1','e2')))
        self.assertEqual(decide(None,(empty,)).action,'NEEDS_EVIDENCE')
    def test_aware_time_outside_UTC_calendar_range_value_error(self):
        invalid=datetime(1,1,1,tzinfo=timezone(timedelta(hours=8)))
        with self.assertRaises(ValueError):decide(None,(replace(obs('a'),content_at=invalid),))


if __name__=='__main__':unittest.main()

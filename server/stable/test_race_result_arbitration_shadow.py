"""Synthetic caller-shaped snapshots only, no actual apply/record/fallback calls."""
from copy import deepcopy
import hashlib
import json
import unittest
from stable.services.race_result_arbitration_shadow import map_result_arbitration_shadow

NOW='2026-10-14T10:00:00+00:00'


def row(runner, index, ref, place):
    return dict(runner_id=runner,reported_finish_position=place,status='finished',finish_time='2:01.2',
                margin=None,barrier='3',carried_weight='57.0',horse_name='Horse '+str(runner),
                jockey_name='Jockey',trainer_name='Trainer',evidence_ref=ref+'/normalized_payload/participants/'+str(index))


def package(ref, state='fresh', priority=100):
    rows=[row(11,0,ref,1),row(12,1,ref,2)]
    return dict(observation_ref=ref,version_ref='version:'+ref,event_key='event:1',captured_schedule_generation=3,
                provider_key='provider:'+ref,source_priority=priority,http_status=200,error_code='',
                content_clock={'content_at':'2026-10-14T09:58:00+00:00','basis_ref':'synthetic-source-clock-basis'},
                transport_clocks={k:NOW for k in ['observed_at','fetched_at','recorded_at','watermark_at','permission_valid_until','poll_due_at']},
                assessments=dict(admission='allowed',health='healthy',identity='matched',revoked=False,
                                 rows_normalized=True,strong_identity_matched=True,terminal_marker=True,
                                 roster_mapping_complete=True,result_phase='official',correction_marker=False,
                                 origin_group='origin:'+ref,freshness_producer_ref='synthetic-producer-only'),
                freshness=dict(state=state,rule_ref='synthetic-rule-not-authentication',observation_ref=ref,
                               version_ref='version:'+ref,assessed_at='2026-10-14T09:59:00+00:00',
                               valid_until='2026-10-14T10:01:00+00:00',result_sha256='0'*64),rows=rows)


def snapshot():
    return dict(schema_version='r04-shadow-input.v1',event_key='event:1',schedule_generation=3,as_of=NOW,
                expected_runner_ids=[11,12],manual_locked=False,current=package('api','stale',300),candidate=package('publisher'),
                legacy=dict(apply=False,reason_code='lower_priority_source',project_current=True,correction_apply_enabled=True))


def bind_freshness(s):
    c=s['current'];n=s['candidate']
    compare=bool(c and c['provider_key']==n['provider_key']) or (n['assessments']['result_phase']=='corrected' and n['assessments']['correction_marker'] is True)
    for p in [c,n]:
        if p is None:continue
        values=[]
        for r in p['rows']:
            value={k:r[k] for k in ['reported_finish_position','status','finish_time','margin','barrier','carried_weight']}
            if compare:value.update({k:r[k] for k in ['horse_name','jockey_name','trainer_name']})
            values.append(('runner:'+str(r['runner_id']),json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))))
        raw=json.dumps(sorted(values),ensure_ascii=False,separators=(',',':')).encode()
        p['freshness']['result_sha256']=hashlib.sha256(raw).hexdigest()
    return s


class ShadowTests(unittest.TestCase):
    def test_mixed_watermark_only_needs_evidence_no_content_time(self):
        s=snapshot();s['candidate']['content_clock']={'content_at':None,'basis_ref':None}
        result=map_result_arbitration_shadow(s)
        self.assertEqual(result.action,'NEEDS_EVIDENCE')
        self.assertIn('candidate.content_clock_missing',result.gaps)
        self.assertIsNone(dict(result.content_times)['candidate']);self.assertIsNone(result.recommendation)
    def test_complete_synthetic_backup_shadow_only_legacy_unchanged(self):
        s=bind_freshness(snapshot());before=deepcopy(s);r=map_result_arbitration_shadow(s)
        self.assertEqual(r.action,'SELECT_BACKUP');self.assertEqual(s,before)
        self.assertFalse(r.apply);self.assertFalse(r.publication);self.assertFalse(r.execution);self.assertFalse(r.authenticated)
        self.assertEqual(r.recommendation.selected_observation_ref,'publisher')
        self.assertEqual({ref for _,ref in r.recommendation.field_refs},{row['evidence_ref'] for row in s['candidate']['rows']})
    def test_missing_capture_generation_health_origin_producer_no_select(self):
        for key in ['captured_schedule_generation','health','origin_group','freshness_producer_ref']:
            s=snapshot()
            if key=='captured_schedule_generation':s['candidate'][key]=None
            else:s['candidate']['assessments'][key]=None
            r=map_result_arbitration_shadow(s);self.assertEqual(r.action,'NEEDS_EVIDENCE');self.assertIsNone(r.recommendation)
    def test_provisional_official_label_without_validation_gaps(self):
        for key,value in [('result_phase','provisional'),('terminal_marker',False),('roster_mapping_complete',None),('rows_normalized',False),('strong_identity_matched',False)]:
            s=snapshot();s['candidate']['assessments'][key]=value
            self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
    def test_wrong_generation_no_default_owner_or_zero(self):
        s=snapshot();s['candidate']['captured_schedule_generation']=2
        self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
        s=snapshot();s['schedule_generation']=None
        self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
    def test_unpersisted_duplicate_missing_runner_no_clipping(self):
        for kind in ['unpersisted','duplicate','missing','extra']:
            s=snapshot();rows=s['candidate']['rows']
            if kind=='unpersisted':rows[0]['runner_id']=None
            elif kind=='duplicate':rows[1]['runner_id']=11
            elif kind=='missing':rows.pop()
            else:rows.append(row(13,2,'publisher',3))
            self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
    def test_cross_package_pointer_gap(self):
        s=snapshot();s['candidate']['rows'][0]['evidence_ref']='api/normalized_payload/participants/0'
        self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
    def test_cross_provider_names_excluded_with_one_common_policy(self):
        s=snapshot();s['candidate']['rows'][0]['horse_name']='別言語名';bind_freshness(s)
        r=map_result_arbitration_shadow(s);self.assertFalse(r.compare_names);self.assertEqual(r.action,'SELECT_BACKUP')
    def test_same_provider_and_correction_use_names_for_both_packages(self):
        for correction in [False,True]:
            s=snapshot();s['current']['freshness']['state']='fresh'
            if correction:s['candidate']['assessments'].update(result_phase='corrected',correction_marker=True)
            else:s['candidate']['provider_key']=s['current']['provider_key']
            s['candidate']['rows'][0]['horse_name']='Different';bind_freshness(s)
            r=map_result_arbitration_shadow(s);self.assertTrue(r.compare_names);self.assertEqual(r.action,'CONFLICT')
    def test_null_not_zero(self):
        s=snapshot();s['current']['freshness']['state']='fresh'
        s['current']['rows'][1].update(reported_finish_position=None,status='did_not_finish')
        bind_freshness(s);self.assertEqual(map_result_arbitration_shadow(s).action,'CONFLICT')
    def test_row_order_replay_stable(self):
        s=bind_freshness(snapshot());first=map_result_arbitration_shadow(s)
        s['expected_runner_ids'].reverse();s['candidate']['rows'].reverse();s['current']['rows'].reverse()
        self.assertEqual(first,map_result_arbitration_shadow(s))
    def test_payload_types_extras_cycle_fail_closed(self):
        class NotPlain:
            def __getattribute__(self,n):raise AssertionError('ORM/lazy properties must not be read')
        for s in [None,NotPlain(),{'schema_version':'other'}]:
            self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
        s=snapshot();s['owner_generation']=0
        self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
        s=snapshot();s['candidate']['rows'][0]['loop']=s
        self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
    def test_caps_do_not_trim_and_original_hash_domain_not_verdict(self):
        s=snapshot();s['candidate']['rows']*=65
        self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
        s=snapshot();s['candidate']['freshness']['result_sha256']='0'*64
        self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
    def test_manual_snapshot_not_apply_and_rule_unknown(self):
        s=bind_freshness(snapshot());s['manual_locked']=True
        r=map_result_arbitration_shadow(s);self.assertEqual(r.action,'KEEP');self.assertFalse(r.apply)
        s=snapshot();s['candidate']['freshness']=None
        self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
    def test_contradictory_rows_and_correction_condition_no_select(self):
        for changes in [dict(status='unknown'),dict(reported_finish_position=0),dict(reported_finish_position=None),dict(reported_finish_position=True)]:
            s=snapshot();s['candidate']['rows'][0].update(changes)
            self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
        s=snapshot();s['candidate']['assessments'].update(result_phase='corrected',correction_marker=None)
        self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
    def test_one_common_projection_digest_cannot_hide_names(self):
        s=bind_freshness(snapshot())  # Digests for excluded names.
        s['candidate']['provider_key']=s['current']['provider_key']
        s['candidate']['rows'][0]['horse_name']='changed'
        self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
        s=snapshot();s['compare_names']=False
        self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
    def test_future_clock_and_oversize_or_naive_type_not_select(self):
        for change in ['future','naive','size','bool_generation']:
            s=snapshot()
            if change=='future':s['candidate']['content_clock']['content_at']='2026-10-15T10:00:00+00:00'
            elif change=='naive':s['candidate']['content_clock']['content_at']='2026-10-14T10:00:00'
            elif change=='size':s['candidate']['rows'][0]['horse_name']='x'*4097
            else:s['candidate']['captured_schedule_generation']=False
            self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')
    def ranking_rejected(self,side,case):
        s=snapshot();rows=s[side]['rows']
        if case=='duplicate_finished':rows[1]['reported_finish_position']=1
        elif case=='gap':rows[1]['reported_finish_position']=3
        else:
            for r in rows:r.update(status='withdrawn',reported_finish_position=None)
        bind_freshness(s);before=deepcopy(s)
        result=map_result_arbitration_shadow(s)
        self.assertEqual(result.action,'NEEDS_EVIDENCE');self.assertIsNone(result.recommendation)
        self.assertIn(side+'.normalized_ranking_inconsistent',result.gaps)
        self.assertEqual(s,before)
    def test_candidate_duplicate_finished_rank_rejected(self):self.ranking_rejected('candidate','duplicate_finished')
    def test_current_duplicate_finished_rank_rejected(self):self.ranking_rejected('current','duplicate_finished')
    def test_candidate_illegal_competition_gap_rejected(self):self.ranking_rejected('candidate','gap')
    def test_current_illegal_competition_gap_rejected(self):self.ranking_rejected('current','gap')
    def test_candidate_all_unranked_rejected(self):self.ranking_rejected('candidate','all_unranked')
    def test_current_all_unranked_rejected(self):self.ranking_rejected('current','all_unranked')
    def test_legal_dead_heat_both_sides_and_order_stable(self):
        s=snapshot()
        for p in (s['current'],s['candidate']):
            for r in p['rows']:r.update(status='dead_heat',reported_finish_position=1)
        bind_freshness(s);first=map_result_arbitration_shadow(s)
        self.assertEqual(first.action,'SELECT_BACKUP')
        s['candidate']['rows'].reverse();s['current']['rows'].reverse()
        self.assertEqual(first,map_result_arbitration_shadow(s))
    def test_legal_dead_heat_skips_following_rank_and_dnf_keeps_null(self):
        s=snapshot();s['expected_runner_ids']=[11,12,13,14]
        for p in (s['current'],s['candidate']):
            p['rows']=[row(n,i,p['observation_ref'],place) for i,(n,place) in enumerate([(11,1),(12,1),(13,3),(14,None)])]
            p['rows'][0]['status']=p['rows'][1]['status']='dead_heat'
            p['rows'][3]['status']='did_not_finish'
        bind_freshness(s);self.assertEqual(map_result_arbitration_shadow(s).action,'SELECT_BACKUP')
        self.assertIsNone(s['candidate']['rows'][3]['reported_finish_position'])
    def test_single_dead_heat_and_mixed_tie_status_rejected(self):
        for side in ['current','candidate']:
            for kind in ['single','mixed']:
                s=snapshot();rows=s[side]['rows'];rows[0]['status']='dead_heat'
                if kind=='mixed':rows[1]['reported_finish_position']=1
                bind_freshness(s)
                self.assertEqual(map_result_arbitration_shadow(s).action,'NEEDS_EVIDENCE')


if __name__=='__main__':unittest.main()

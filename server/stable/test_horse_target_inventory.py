import copy
import unittest
from stable.services.horse_target_inventory import plan_inventory, compare_snapshots

def document():
    return dict(schema_version=1, as_of='2026-10-03', snapshot_at='2026-10-03T00:00:00+00:00', input_complete=True, policy_sha='a'*64, jg1_scope='unresolved', events=[], participations=[], identities=[], layers=[], news=[], seasons=[])

def event(key='e1', **changes):
    return dict(key=key, region='japan', local_date='2026-10-03', date_precision='exact', grade='G1', grade_verified=True, hk_local_g1=False, current_racecard=None, current_result=None, known_roster_count=1, **changes) if not changes else {**event(key), **changes}

def row(ref='r1', **changes):
    return {**dict(ref=ref,event_key='e1',participant_key='p1',horse_key='jra:1',revision_ref=None,kind='legacy',status='finished',start_evidence=True,birth_year=2010),**changes}

def identity(key='jra:1', profile=1, **changes):
    return {**dict(horse_key=key,profile_id=profile,status='verified',evidence_sha='b'*64,verified_at='2026-10-02T00:00:00+00:00'),**changes}

class InventoryTests(unittest.TestCase):
    def plan(self, events=None, rows=None, ids=None, **changes):
        p=document();p.update(events=events or [event()],participations=rows or [row()],identities=ids if ids is not None else [identity()]);p.update(changes);return plan_inventory(p)
    def test_unverified_old_grade_retains_locatable_candidate(self):
        x=self.plan([event(local_date='2021-01-01',grade='UNKNOWN',grade_verified=False)])
        self.assertEqual(len(x['targets']),1)
        self.assertEqual(x['targets'][0]['refs'],['r1'])
        self.assertIn('candidate',x['targets'][0]['memberships'])
        self.assertEqual(x['counts']['historical_targets'],0)
        self.assertEqual(x['counts']['recent_targets'],0)

    def test_news_identity_conflict_rejected_consistent_and_profile_only_kept(self):
        news=dict(horse_key='jra:1',profile_id=2,published_date='2026-10-03',confirmed=True)
        with self.assertRaisesRegex(ValueError,'news_identity_conflict'):
            self.plan(news=[news])
        for ids in ([identity(),identity(profile=2)], [identity(status='retired')], [identity(status='rejected')]):
            with self.assertRaisesRegex(ValueError,'news_identity_conflict'):
                self.plan(ids=ids,news=[news])
        news['profile_id']=1
        self.assertIn('recent_news',self.plan(news=[news])['targets'][0]['reasons'])
        news.update(horse_key=None,profile_id=2)
        x=self.plan(news=[news])
        self.assertIn('profile:2',{t['key'] for t in x['targets']})

    def test_fixed_window_not_age_and_pending_jg1(self):
        x=self.plan();self.assertEqual(x['targets'][0]['memberships'],['historical','recent']);self.assertFalse(x['complete']);self.assertIn('jg1_unresolved',x['gaps']);self.assertEqual(x['counts']['recent_targets'],1)
    def test_window_edges(self):
        es=[event('e'+str(i),local_date=d) for i,d in enumerate(['2023-10-02','2023-10-03','2026-10-03','2026-10-04'])];rs=[row('r'+str(i),event_key=e['key'],participant_key=str(i),horse_key='jra:'+str(i)) for i,e in enumerate(es)]
        x=self.plan(es,rs,[]);self.assertEqual(x['counts']['recent_targets'],2)
    def test_verified_cross_source_dedup_unresolved_kept(self):
        rs=[row(),row('r2',participant_key='p2',horse_key='hkjc:2')];x=self.plan([event(known_roster_count=2)],rs,[identity(),identity('hkjc:2')]);self.assertEqual(len(x['targets']),1);self.assertEqual(x['counts']['raw_participations'],2)
        y=self.plan(ids=[]);self.assertEqual(y['counts']['unresolved_targets'],1)
    def test_hist_full_roster_not_winner(self):
        rs=[row('r'+str(i),participant_key=str(i),horse_key=None,status='scratched' if i==11 else 'finished',start_evidence=False if i==11 else True) for i in range(12)];x=self.plan([event(known_roster_count=12)],rs,[]);self.assertEqual(x['counts']['historical_targets'],12);self.assertEqual(x['counts']['recent_targets'],11)

    def test_grade_pending_and_exact_date(self):
        for grade,region,hk,expected in [('JPN1','japan',False,1),('LOCAL_GRADE','hong_kong',True,1),('LOCAL_GRADE','germany',True,0)]:
            x=self.plan([event(grade=grade,region=region,hk_local_g1=hk)]);self.assertEqual(x['counts']['historical_targets'],expected)
        x=self.plan([event(grade='JG1')]);self.assertEqual(x['counts']['historical_pending_targets'],1);self.assertEqual(x['counts']['recent_targets'],1)
        x=self.plan([event(local_date='2026-10-01',date_precision='month')]);self.assertEqual(x['counts']['recent_targets'],0);self.assertIn('date_unconfirmed',x['gaps'])
    def test_revoked_identity_and_missing_roster(self):
        for status in ['observed','retired','rejected']:
            x=self.plan(ids=[identity(status=status)]);self.assertEqual(x['counts']['unresolved_targets'],1);self.assertFalse(x['complete'])
        x=self.plan([event(known_roster_count=12)]);self.assertIn('roster_missing',x['gaps'])
        x=self.plan([event(known_roster_count=None)]);self.assertEqual(x['counts']['unknown_roster_events'],1)
    def test_current_revision_legacy_not_double_counted(self):
        rs=[row('old',revision_ref='v1',kind='result'),row('new',revision_ref='v2',kind='result'),row('legacy')]
        x=self.plan([event(current_result='v2')],rs);self.assertEqual(x['targets'][0]['refs'],['new'])
        x=self.plan([event()],rs);self.assertIn('revision_unresolved',x['gaps']);self.assertEqual(x['counts']['recent_targets'],0)
    def test_priority_future_news_season_and_layers(self):
        es=[event(),event('future',local_date='2026-11-02')];rs=[row(),row('future',event_key='future',horse_key='jra:2',participant_key='p2',status='declared',start_evidence=None)]
        x=self.plan(es,rs,news=[dict(horse_key='jra:1',profile_id=1,published_date='2026-07-05',confirmed=True)],layers=[dict(target_key='profile:1',cache='present',staging='ambiguous',profile_exists=True,public_state='unpublished',starts=None,incomplete_modules=None)])
        self.assertIn('recent_news',next(t for t in x['targets'] if t['key']=='profile:1')['reasons']);self.assertEqual(x['counts']['future_targets'],1);self.assertEqual(x['counts']['public_visible_targets'],0)
        self.assertEqual(next(t for t in x['targets'] if t['key']=='profile:1')['layers']['starts'],None)
    def test_deterministic_owned_output_and_validation(self):
        p=document();p.update(events=[event()],participations=[row()],identities=[identity()]);original=copy.deepcopy(p)
        x=plan_inventory(p);self.assertEqual(p,original);self.assertEqual(x,plan_inventory(p));x['targets'].clear();self.assertNotEqual(x,plan_inventory(p))
        for field,val in [('input_complete',1),('jg1_scope','guess'),('schema_version',True),('as_of','2026-10-03T00:00:00')]:
            bad=copy.deepcopy(p);bad[field]=val
            with self.assertRaises(ValueError):plan_inventory(bad)
        bad=copy.deepcopy(p);bad['events'][0]['secret']='password'
        with self.assertRaises(ValueError):plan_inventory(bad)

    def test_season_requires_evidence_and_input_reordering(self):
        seasons=[dict(region='japan',start='2026-01-01',end='2026-12-31',evidence_sha=None,version=None)]
        x=self.plan(seasons=seasons);self.assertNotIn('current_season',x['targets'][0]['reasons'])
        seasons[0].update(evidence_sha='c'*64,version='season-v1');x=self.plan(seasons=seasons);self.assertIn('current_season',x['targets'][0]['reasons'])
        es=[event(),event('e2',region='ireland',local_date='2026-09-01')];rs=[row(),row('r2',event_key='e2',horse_key='hri:2',participant_key='p2')]
        x=self.plan(es,rs,[]);y=self.plan(list(reversed(es)),list(reversed(rs)),[]);self.assertEqual(x,y)
    def test_identity_current_status_conflict_and_participant_collision(self):
        x=self.plan(ids=[identity(),identity(status='retired')]);self.assertEqual(x['counts']['resolved_targets'],0)
        rs=[row(),row('r2',horse_key='hkjc:2')];x=self.plan(rows=rs,ids=[identity(),identity('hkjc:2',2)])
        self.assertIn('participation_conflict',x['gaps']);self.assertEqual(x['counts']['recent_targets'],0)
    def test_layer_zero_and_invalid_numbers(self):
        layers=[dict(target_key='profile:1',cache='missing',staging='matched',profile_exists=True,public_state='blocked',starts=0,incomplete_modules=0)]
        x=self.plan(layers=layers);self.assertEqual(x['targets'][0]['layers']['starts'],0);self.assertEqual(x['counts']['public_visible_targets'],0)
        for val in [True,1.0,-1]:
            layers[0]['starts']=val
            with self.assertRaises(ValueError):self.plan(layers=layers)
    def test_delta_reproducible_concurrent_input_and_no_sensitive_echo(self):
        p=document();p.update(events=[event()],participations=[row()],identities=[identity()]);x=plan_inventory(p)
        p['events'].append(event('e2',local_date='2026-09-01'));p['participations'].append(row('r2',event_key='e2',horse_key='hri:2'))
        y=plan_inventory(p);delta=compare_snapshots(x,y);self.assertEqual(delta['added'],['source:hri:2']);self.assertEqual(compare_snapshots(x,x)['added'],[])
        with self.assertRaises(ValueError) as caught:self.plan(ids=[identity(key='https://secret.invalid/?token=private')])
        self.assertNotIn('private',str(caught.exception))

    def test_unknown_date_retains_candidate_and_conflict_counts(self):
        x=self.plan([event(local_date=None,date_precision='unknown')]);self.assertEqual(len(x['targets']),1);self.assertIn('candidate',x['targets'][0]['memberships'])
        x=self.plan(ids=[identity(),identity(profile=2)]);self.assertEqual(x['counts']['identity_conflict_groups'],1)
    def test_nine_regions_non_major_recent_and_false_scope(self):
        from stable.services.horse_target_inventory import REGIONS
        es=[event('e'+str(i),region=region,grade='OTHER') for i,region in enumerate(REGIONS)]
        rs=[row('r'+str(i),event_key=e['key'],horse_key=None,participant_key=str(i)) for i,e in enumerate(es)]
        x=self.plan(es,rs,[],input_complete=False);self.assertEqual(x['counts']['recent_targets'],9);self.assertIn('input_incomplete',x['gaps'])
    def test_future_and_news_exact_edges(self):
        es=[event('e'+str(i),local_date=d,grade='OTHER') for i,d in enumerate(['2026-10-03','2026-10-04','2026-11-02','2026-11-03'])]
        rs=[row('r'+str(i),event_key=e['key'],horse_key=None,participant_key=str(i),status='declared',start_evidence=None) for i,e in enumerate(es)]
        x=self.plan(es,rs,[]);self.assertEqual(x['counts']['future_targets'],2);self.assertEqual(len(x['targets']),3)
        x=self.plan(news=[dict(horse_key='test:2',profile_id=None,published_date='2026-07-04',confirmed=True)]);self.assertEqual(len(x['targets']),1)
    def test_unknown_start_and_invalid_snapshot_digest(self):
        x=self.plan(rows=[row(status='unknown',start_evidence=None)]);self.assertEqual(x['counts']['recent_targets'],0);self.assertIn('start_unconfirmed',x['gaps'])
        y=copy.deepcopy(x);y['counts']['recent_targets']=999
        with self.assertRaises(ValueError):compare_snapshots(x,y)

    def test_missing_modules_priority_is_not_publication_state(self):
        rs=[row(),row('r2',participant_key='p2',horse_key='hkjc:2')]
        layers=[dict(target_key='profile:'+str(i),cache='present',staging='matched',profile_exists=True,public_state='visible',starts=1,incomplete_modules=0 if i==1 else 2) for i in [1,2]]
        x=self.plan([event(known_roster_count=2)],rs,[identity(),identity('hkjc:2',2)],layers=layers);self.assertEqual(x['targets'][0]['key'],'profile:2')

    def test_json_object_subclasses_and_cycles_rejected_before_copy(self):
        class Custom(dict):
            def __deepcopy__(self,memo):raise RuntimeError('unsafe_copy')
        p=document();p['events']=[Custom(event())]
        with self.assertRaises(ValueError):plan_inventory(p)
        p=document();p['events'].append(p)
        with self.assertRaises(ValueError):plan_inventory(p)

if __name__=='__main__':unittest.main()

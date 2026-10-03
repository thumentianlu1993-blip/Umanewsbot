"""固定 fake 规范输入的纯 unittest；不解析 HTML，不启动 Django。"""
import copy
from dataclasses import FrozenInstanceError
import unittest

from stable.services import content_contracts as f01
from stable.services import public_probe_contracts as probe

NOW = '2026-10-04T00:10:00Z'
ENTITY = dict(kind='race_event', canonical_id='fixture:1', source_refs=[],
              identity_state='verified', candidate_ids=[], evidence_refs=[])
VERSION = dict(schema_version='f01.input.v1', scope=list(f01.INPUT_SCOPE),
               content_sha256='a'*64, generations=dict(owner=1, schedule=1, enrollment=1, source_set=1))


def expected():
    return dict(schema_version='o03.expected.v1', scope_ref='fixture-scope', candidate_sha='b'*64,
                input_version=copy.deepcopy(VERSION), entity=copy.deepcopy(ENTITY), capability='result',
                surface_ref='fixture-detail', audience_ref='anonymous', generation='g1',
                revision_ref='r1', permission_version='p1', content_digest='c'*64, visibility='visible')


def anchor(exp=None):
    exp = expected() if exp is None else exp
    return dict(scope_ref=exp['scope_ref'], candidate_sha=exp['candidate_sha'],
                expectation_sha=f01._sha(exp), input_version=copy.deepcopy(exp['input_version']),
                entity=copy.deepcopy(exp['entity']))


def binding(a):
    return {k:a[k] for k in ('scope_ref','candidate_sha','expectation_sha')}


def read_receipt(exp=None):
    exp = expected() if exp is None else exp
    return dict(schema_version='o03.read.v1', **binding(anchor(exp)),
                input_version=copy.deepcopy(exp['input_version']), entity=copy.deepcopy(exp['entity']),
                capability=exp['capability'], surface_ref=exp['surface_ref'], audience_ref=exp['audience_ref'],
                generation=exp['generation'], receipt_id='read-1', request_started_at='2026-10-04T00:00:00Z',
                response_completed_at='2026-10-04T00:00:01Z', clock_error_ms=0, status=200,
                complete=True, conflict=False, denial_verified=False,
                marker={k:exp[k] for k in ('revision_ref','permission_version','content_digest')},
                body_digest=exp['content_digest'])


class PublicComparisonTests(unittest.TestCase):
    def compare(self, e=None, r=None, a=None):
        e = expected() if e is None else e
        r = read_receipt(e) if r is None else r
        return probe.compare_public(e,r,anchor=anchor(e) if a is None else a,as_of=NOW).to_dict()

    def test_matching_public_has_only_visibility_proof_not_sla(self):
        result = self.compare()
        self.assertEqual(result['status'],'public_read_verified')
        self.assertTrue(result['public_read_verified'])
        self.assertFalse(result['withdrawal_verified'])
        self.assertEqual(result['sla'],'unverified')
        self.assertEqual(result['request_interval'],['2026-10-04T00:00:00Z','2026-10-04T00:00:01Z'])

    def test_old_body_marker_and_permissions_never_pass(self):
        for mutation in (
            lambda r:r.update(body_digest='d'*64),
            lambda r:r['marker'].update(content_digest='d'*64),
            lambda r:r['marker'].update(revision_ref='old'),
            lambda r:r['marker'].update(permission_version='old'),
            lambda r:r.update(marker=None),
            lambda r:r.update(body_digest=None),
            lambda r:r.update(clock_error_ms=None),
            lambda r:r.update(complete=False),
            lambda r:r.update(conflict=True),
            lambda r:r.update(status=304),
            lambda r:r.update(status=206),
        ):
            r=read_receipt(); mutation(r)
            with self.subTest(r=r):
                self.assertEqual(self.compare(r=r)['status'],'visibility_unverified')

    def test_unknown_expected_not_repaired(self):
        for key in ('revision_ref','permission_version','content_digest'):
            e=expected(); e[key]=None
            self.assertEqual(self.compare(e=e)['status'],'visibility_unverified')
        e=expected(); e['entity']['identity_state']='unresolved'; e['entity']['canonical_id']=None
        self.assertEqual(self.compare(e=e)['status'],'visibility_unverified')

    def test_withdrawal_denial_is_not_public_read(self):
        e=expected(); e.update(visibility='withdrawn',revision_ref=None,content_digest=None,permission_version='p2')
        r=read_receipt(e); r.update(status=403,denial_verified=True,body_digest=None)
        result=self.compare(e=e,r=r)
        self.assertEqual(result['status'],'withdrawal_verified')
        self.assertTrue(result['withdrawal_verified']); self.assertFalse(result['public_read_verified'])
        for key,value in [('denial_verified',False),('status',200),('body_digest','d'*64)]:
            bad=copy.deepcopy(r); bad[key]=value
            self.assertEqual(self.compare(e=e,r=bad)['status'],'visibility_unverified')

    def test_external_anchor_and_audience_not_receipt_echo(self):
        for key,value in [('scope_ref','other'),('candidate_sha','d'*64),('expectation_sha','d'*64),
                          ('audience_ref','admin'),('capability','roster'),('generation','g2'),('surface_ref','admin')]:
            r=read_receipt(); r[key]=value
            with self.subTest(key=key), self.assertRaises(f01.ContractError):self.compare(r=r)
        e=expected(); a=anchor(e); e['revision_ref']='attacker'
        with self.assertRaises(f01.ContractError):self.compare(e=e,a=a)
        r=read_receipt(); r['input_version']['generations']['owner']=2
        with self.assertRaises(f01.ContractError):self.compare(r=r)
        r=read_receipt(); r['entity']['canonical_id']='other'
        with self.assertRaises(f01.ContractError):self.compare(r=r)

    def test_strict_shape_time_and_redacted_errors(self):
        for mutation in (lambda r:r.pop('complete'),lambda r:r.update(secret='sensitive-value'),
                         lambda r:r.update(status=True),lambda r:r.update(clock_error_ms=-1),
                         lambda r:r.update(request_started_at='2026-10-04T00:20:00Z'),
                         lambda r:r.update(response_completed_at='2026-10-04T00:20:00Z'),
                         lambda r:r.update(response_completed_at='2026-10-04'),
                         lambda r:r.update(complete=1)):
            r=read_receipt(); mutation(r)
            with self.subTest(r=r),self.assertRaises(f01.ContractError) as caught:self.compare(r=r)
            self.assertNotIn('sensitive-value',str(caught.exception))
        for raw in ('{"x":1,"x":2}', '{"x":NaN}'):
            with self.assertRaises(f01.ContractError):self.compare(r=raw)

    def test_immutable_output_and_inputs_not_mutated(self):
        e=expected(); r=read_receipt(e); a=anchor(e); before=copy.deepcopy([e,r,a])
        dto=probe.compare_public(e,r,anchor=a,as_of=NOW)
        self.assertEqual([e,r,a],before)
        self.assertEqual(dto.to_dict()['status'],'public_read_verified')
        detached=dto.to_dict(); detached['status']='tamper'
        self.assertEqual(dto.to_dict()['status'],'public_read_verified')
        with self.assertRaises(FrozenInstanceError):dto.wire_json='{}'


def cycle_policy():
    return dict(schema_version='o03.cycles.v1', **binding(anchor()), epoch='worker-epoch-1',
                epoch_started_at='2026-10-04T00:00:00Z', period_ms=60000, consecutive_misses=3,
                clock_error_ms=0, host_watchdog_bound=False)


def cycle(index, *, healthy=True, partial=False):
    return dict(receipt_id='cycle-'+str(index), **binding(anchor()), epoch='worker-epoch-1',
                started_at='2026-10-04T00:0%d:00Z'%index,
                completed_at='2026-10-04T00:0%d:10Z'%index,
                coverage_complete=not partial, all_healthy=healthy)


class CycleTests(unittest.TestCase):
    def evaluate(self, receipts, policy=None, at='2026-10-04T00:03:00Z'):
        return probe.evaluate_cycles(cycle_policy() if policy is None else policy, receipts,
                                     anchor=anchor(),as_of=at).to_dict()

    def test_fresh_failed_completed_is_not_business_healthy_or_host_proof(self):
        result=self.evaluate([cycle(0),cycle(1),cycle(2,healthy=False)])
        self.assertEqual(result['cycle_status'],'fresh')
        self.assertEqual(result['business_status'],'unhealthy')
        self.assertEqual(result['host_status'],'host_unverified')
        self.assertEqual(result['consecutive_missing'],0)

    def test_slots_not_number_of_received_failures(self):
        result=self.evaluate([])
        self.assertEqual(result['cycle_status'],'stalled')
        self.assertEqual(result['consecutive_missing'],3)
        result=self.evaluate([cycle(0)])
        self.assertEqual(result['cycle_status'],'gap')
        self.assertEqual(result['consecutive_missing'],2)
        self.assertEqual(self.evaluate([],at='2026-10-04T00:00:59Z')['cycle_status'],'not_evaluable')

    def test_started_partial_and_boundary_cannot_renew_completed(self):
        r=cycle(0);r['completed_at']=None
        self.assertEqual(self.evaluate([r])['cycle_status'],'stalled')
        self.assertEqual(self.evaluate([cycle(0,partial=True)])['cycle_status'],'stalled')
        r=cycle(2); r['completed_at']='2026-10-04T00:03:00Z'
        self.assertEqual(self.evaluate([r])['consecutive_missing'],3)
        r=cycle(2); r['completed_at']='2026-10-04T00:02:59.999999Z'
        self.assertEqual(self.evaluate([r])['consecutive_missing'],0)
        p=cycle_policy();p['clock_error_ms']=1
        self.assertEqual(self.evaluate([r],policy=p,at='2026-10-04T00:03:01Z')['consecutive_missing'],3)

    def test_clock_unknown_and_half_open_matured_boundary(self):
        p=cycle_policy();p['clock_error_ms']=None
        self.assertEqual(self.evaluate([cycle(0)],policy=p)['cycle_status'],'unknown')
        p=cycle_policy();p['clock_error_ms']=1000
        self.assertEqual(self.evaluate([],policy=p,at='2026-10-04T00:01:00Z')['closed_slots'],0)
        self.assertEqual(self.evaluate([],policy=p,at='2026-10-04T00:01:01Z')['closed_slots'],1)

    def test_id_conflict_epoch_future_order_and_slot_conflict_rejected(self):
        r=cycle(0); other=copy.deepcopy(r);other['all_healthy']=False
        same_slot=copy.deepcopy(r);same_slot['receipt_id']='z-other'
        cases=[[r,other],[cycle(1),cycle(0)],[r,same_slot]]
        for field,value in [('epoch','old'),('scope_ref','other'),('completed_at','2026-10-04T00:20:00Z'),
                            ('started_at','2026-10-03T23:59:59Z'),('coverage_complete',1)]:
            bad=copy.deepcopy(r);bad[field]=value;cases.append([bad])
        for receipts in cases:
            with self.subTest(receipts=receipts),self.assertRaises(f01.ContractError):self.evaluate(receipts)
        for field,value in [('period_ms',0),('consecutive_misses',True),('host_watchdog_bound',1)]:
            p=cycle_policy();p[field]=value
            with self.assertRaises(f01.ContractError):self.evaluate([],policy=p)

    def test_duplicate_is_idempotent_and_inputs_immutable(self):
        r=cycle(2);before=copy.deepcopy(r)
        self.assertEqual(self.evaluate([r]),self.evaluate([r,r]))
        self.assertEqual(r,before)

    def test_bound_host_and_healthy_cycle_are_separate(self):
        p=cycle_policy();p['host_watchdog_bound']=True
        result=self.evaluate([cycle(2)],policy=p)
        self.assertEqual(result['host_status'],'host_bound')
        self.assertEqual(result['business_status'],'healthy')
        self.assertEqual(self.evaluate([cycle(2,healthy=None)])['business_status'],'unknown')


def episode_event(index, checks, generation='g1', predecessor=None):
    return dict(event_id='event-%02d'%index, **binding(anchor()), recorded_at='2026-10-04T00:00:%02dZ'%index,
                generation=generation,supersedes_generation=predecessor,
                required_reasons=['content','worker'],checks=checks)


class EpisodeTests(unittest.TestCase):
    def replay(self, events):
        return probe.reconcile_episodes(events,anchor=anchor(),as_of=NOW).to_dict()

    def test_open_silent_change_partial_resolve_and_reopen_history(self):
        events=[episode_event(0,dict(content='unhealthy',worker='unknown')),
                episode_event(1,dict(content='unhealthy',worker='unknown')),
                episode_event(2,dict(content='healthy',worker='unhealthy')),
                episode_event(3,dict(content='healthy',worker='healthy')),
                episode_event(4,dict(content='unhealthy',worker='healthy'))]
        result=self.replay(events)
        self.assertEqual([v['kind'] for v in result['transitions']],['OPEN','CHANGED','RESOLVED','OPEN'])
        self.assertEqual([v['episode_number'] for v in result['episodes']],[1,2])
        self.assertEqual([v['status'] for v in result['episodes']],['resolved','open'])
        self.assertEqual(result['episodes'][0]['opened_at'],events[0]['recorded_at'])

    def test_unknown_or_partial_recovery_cannot_resolve(self):
        events=[episode_event(0,dict(content='unhealthy',worker='unhealthy')),
                episode_event(1,dict(content='unknown',worker='healthy')),
                episode_event(2,dict(content='unknown',worker='healthy'))]
        result=self.replay(events)
        self.assertEqual(result['episodes'][0]['status'],'open')
        self.assertEqual(result['episodes'][0]['reasons'],{'content':'unhealthy'})
        self.assertEqual([v['kind'] for v in result['transitions']],['OPEN','CHANGED'])

    def test_generation_successor_preserves_old_open_problem(self):
        events=[episode_event(0,dict(content='unhealthy',worker='healthy')),
                episode_event(1,dict(content='unknown',worker='healthy'),'g2','g1'),
                episode_event(2,dict(content='healthy',worker='healthy'),'g2')]
        result=self.replay(events)
        self.assertEqual(result['episodes'][0]['status'],'open')
        self.assertEqual(result['episodes'][0]['superseded_by'],'g2')
        self.assertEqual(result['episodes'][1]['status'],'resolved')
        self.assertEqual(result['current_generation'],'g2')

    def test_idempotent_duplicates_and_inputs_not_mutated(self):
        e=episode_event(0,dict(content='unknown',worker='healthy'));before=copy.deepcopy(e)
        self.assertEqual(self.replay([e]),self.replay([e,e]))
        self.assertEqual(e,before)
        self.assertEqual(self.replay([e]),self.replay([e]))
        self.assertEqual(self.replay([])['episodes'],[])

    def test_order_future_conflict_and_generation_forgery_rejected(self):
        first=episode_event(0,dict(content='unhealthy',worker='healthy'))
        second=episode_event(1,dict(content='unhealthy',worker='healthy'))
        conflict=copy.deepcopy(first);conflict['checks']['content']='healthy'
        future=copy.deepcopy(first);future['recorded_at']='2026-10-04T00:11:00Z'
        changed=copy.deepcopy(second);changed['required_reasons']=['content'];changed['checks']={'content':'healthy'}
        for events in ([second,first],[first,conflict],[future],[first,changed],
                       [first,episode_event(1,dict(content='unknown',worker='healthy'),'g2')],
                       [first,episode_event(1,dict(content='unknown',worker='healthy'),'g2','other')],
                       [first,episode_event(1,dict(content='unknown',worker='healthy'),'g2','g1'),
                        episode_event(2,dict(content='healthy',worker='healthy'),'g1','g2')]):
            with self.subTest(events=events),self.assertRaises(f01.ContractError):self.replay(events)

    def test_reason_shapes_and_anchor_conflicts_rejected(self):
        for mutation in (lambda e:e['checks'].pop('worker'),lambda e:e['checks'].update(worker=None),
                         lambda e:e.update(scope_ref='other'),lambda e:e.update(required_reasons=['worker','content']),
                         lambda e:e.update(required_reasons=['content','content']),lambda e:e.update(required_reasons=[]),
                         lambda e:e.update(supersedes_generation='invented'),lambda e:e.update(extra=1)):
            e=episode_event(0,dict(content='unknown',worker='healthy'));mutation(e)
            with self.assertRaises(f01.ContractError):self.replay([e])

    def test_healthy_baseline_emits_no_transition(self):
        result=self.replay([episode_event(0,dict(content='healthy',worker='healthy'))])
        self.assertEqual(result['transitions'],[]);self.assertEqual(result['episodes'],[])


def budget_fixture():
    return dict(targets=2,period_ms=2500,request_timeout_ms=1000,overhead_ms=500,
                request_cap=10,wire_cap=20,decoded_cap=30,cycle_cap=120)


def usage_fixture():
    return [dict(request_bytes=10,wire_bytes=20,decoded_bytes=30) for _ in range(2)]


class BudgetTests(unittest.TestCase):
    def check(self, budget=None, usage=None):
        return probe.check_budget(budget_fixture() if budget is None else budget,
                                  usage_fixture() if usage is None else usage).to_dict()

    def test_exact_capacity_is_feasible_and_preserves_denominator(self):
        result=self.check()
        self.assertEqual(result['status'],'budget_verified')
        self.assertTrue(result['coverage_complete'])
        self.assertEqual(result['expected_targets'],2)
        self.assertEqual(result['observed_targets'],2)
        self.assertEqual(result['time_required_ms'],2500)
        self.assertEqual(result['cycle_bytes'],120)

    def test_time_excess_cannot_skip_targets(self):
        b=budget_fixture();b['period_ms']=2499
        result=self.check(budget=b)
        self.assertEqual(result['status'],'budget_exceeded')
        self.assertIn('time_budget_exceeded',result['reasons'])
        self.assertEqual(result['expected_targets'],2)

    def test_wire_decoded_request_and_cycle_caps_all_apply(self):
        for field in ('request_bytes','wire_bytes','decoded_bytes'):
            usage=usage_fixture();usage[0][field]+=1
            result=self.check(usage=usage)
            self.assertEqual(result['status'],'budget_exceeded')
            self.assertIn(field+'_exceeded',result['reasons'])
        b=budget_fixture();b['cycle_cap']=119
        self.assertIn('cycle_bytes_exceeded',self.check(budget=b)['reasons'])

    def test_missing_or_extra_rows_not_full_coverage(self):
        for usage in ([],usage_fixture()[:1]):
            result=self.check(usage=usage)
            self.assertEqual(result['status'],'coverage_unknown')
            self.assertFalse(result['coverage_complete'])
            self.assertEqual(result['expected_targets'],2)
        self.assertIn('count_conflict',self.check(usage=usage_fixture()+usage_fixture())['reasons'])

    def test_strict_types_limits_and_inputs_immutable(self):
        for key in budget_fixture():
            for value in (True,None,-1,2**63):
                b=budget_fixture();b[key]=value
                with self.subTest(key=key,value=value),self.assertRaises(f01.ContractError):self.check(budget=b)
        for key in ('targets','period_ms','request_timeout_ms','request_cap','wire_cap','decoded_cap','cycle_cap'):
            b=budget_fixture();b[key]=0
            with self.assertRaises(f01.ContractError):self.check(budget=b)
        u=usage_fixture();u[0]['decoded_bytes']=True
        with self.assertRaises(f01.ContractError):self.check(usage=u)
        b=budget_fixture();u=usage_fixture();before=copy.deepcopy([b,u])
        self.check(b,u);self.assertEqual([b,u],before)


class BoundaryTests(unittest.TestCase):
    def test_receipt_bool_generation_cannot_equal_integer_version(self):
        r=read_receipt();r['input_version']['generations']['owner']=True
        with self.assertRaises(f01.ContractError):
            probe.compare_public(expected(),r,anchor=anchor(),as_of=NOW)

    def test_frozen_wire_requires_string(self):
        with self.assertRaises(f01.ContractError):probe.ProbeDocument({'status':'forged'})

    def test_all_batches_reject_over_256_without_truncation(self):
        invocations=[lambda:probe.evaluate_cycles(cycle_policy(),[cycle(0)]*257,anchor=anchor(),as_of=NOW),
                     lambda:probe.reconcile_episodes([episode_event(0,dict(content='unknown',worker='healthy'))]*257,
                                                    anchor=anchor(),as_of=NOW),
                     lambda:probe.check_budget(budget_fixture(),usage_fixture()*129)]
        for call in invocations:
            with self.assertRaises(f01.ContractError):call()
        self.assertEqual(probe.check_budget(dict(budget_fixture(),targets=256,period_ms=256500,cycle_cap=15360),
                                           usage_fixture()*128).to_dict()['status'],'budget_verified')

    def test_f01_wire_guard_limits_cycles_and_private_hooks(self):
        cyclic=[];cyclic.append(cyclic)
        class Hook(dict):
            def __iter__(self):raise AssertionError('custom hook must never run')
        deep=None
        for _ in range(66):deep=[deep]
        inputs=[cyclic,deep,Hook(),{'x':'a'*f01.MAX_WIRE_BYTES},'{"x":1,"x":2}', '{"x":Infinity}']
        for raw in inputs:
            with self.subTest(kind=type(raw)),self.assertRaises(f01.ContractError):
                probe.check_budget(budget_fixture(),raw)

    def test_unknown_old_and_noncanonical_anchor_version_rejected(self):
        for mutation in (lambda a:a['input_version'].update(schema_version='old'),
                         lambda a:a['input_version']['scope'].reverse(),
                         lambda a:a['entity'].update(kind='person'),
                         lambda a:a.update(candidate_sha='BAD'),lambda a:a.update(extra=1)):
            a=anchor();mutation(a)
            with self.assertRaises(f01.ContractError):
                probe.evaluate_cycles(cycle_policy(),[],anchor=a,as_of=NOW)

    def test_clock_and_integer_extremes_stay_bounded(self):
        p=cycle_policy();p['clock_error_ms']=2**63-1
        result=probe.evaluate_cycles(p,[],anchor=anchor(),as_of=NOW).to_dict()
        self.assertEqual(result['closed_slots'],0)
        p=cycle_policy();p['period_ms']=1
        result=probe.evaluate_cycles(p,[],anchor=anchor(),as_of='9999-12-31T23:59:59Z').to_dict()
        self.assertEqual(result['cycle_status'],'stalled')


if __name__ == '__main__':
    unittest.main()

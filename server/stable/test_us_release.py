"""发布事务、批次完整性和定向恢复；仅本地合成数据库与冻结原件。"""
import hashlib,json,tempfile
import threading,time
from copy import deepcopy
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from django.db import connection,connections,transaction
from django.test import TestCase,TransactionTestCase,override_settings
from stable import models
from stable import test_us_workflow as workflow
NOW=workflow.NOW
from stable.services.us_release import execute,snapshot


@override_settings(**workflow.USWorkflowTests._overridden_settings)
class USReleaseTests(TestCase):
    def setUp(self):
        workflow.USWorkflowTests.setUp(self)
        loader=patch("stable.services.us_release.load_multisource_policy",return_value=self.policy)
        loader.start();self.addCleanup(loader.stop)
    fetch=workflow.USWorkflowTests.fetch

    def packet(self,events=None):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);docs=[]
        for i,(url,raw) in enumerate(self.docs.items()):
            name=f'page-{i}.bin';(root/name).write_bytes(raw)
            docs.append(dict(url=url,file=name,sha256=hashlib.sha256(raw).hexdigest(),fetched_at=NOW.isoformat()))
        def bound(name,value):
            raw=json.dumps(value,ensure_ascii=False).encode();(root/name).write_bytes(raw)
            return dict(file=name,sha256=hashlib.sha256(raw).hexdigest())
        events=events or [self.event]
        items=[dict(event_id=e.pk,fields={},result_rows=8) for e in events]
        manifest=dict(schema_version=1,action='us_release_data',policy_digest=self.policy.digest,items=items,rebind=[],
            baseline=bound('baseline.json',snapshot([e.pk for e in events])),archive=bound('archive.json',{'documents':docs}))
        raw=json.dumps(manifest).encode();path=root/'manifest.json';path.write_bytes(raw)
        return path,hashlib.sha256(raw).hexdigest()

    def test_dry_run_apply_replay_and_restore_public_surface(self):
        path,sha=self.packet();old=snapshot([self.event.pk])
        result=execute(path,sha,now=NOW)
        self.assertEqual(result['result_rows'],8)
        self.assertEqual(snapshot([self.event.pk]),old)
        result=execute(path,sha,apply=True,now=NOW)
        self.assertEqual(result['action'],'applied')
        self.assertEqual(execute(path,sha,apply=True,now=NOW)['action'],'replay')
        self.assertEqual(self.event.results.count(),8)
        result=execute(path,sha,restore=True,apply=True,now=NOW)
        self.assertEqual(result['action'],'restored')
        self.event.refresh_from_db()
        self.assertEqual(self.event.status,'scheduled')
        self.assertFalse(self.event.runners.exists())
        self.assertFalse(self.event.results.exists())
        self.assertFalse(models.RaceDataSyncEnrollment.objects.filter(event=self.event).exists())
        self.assertFalse(self.event.live_tracking.tracking_enabled)
        self.assertEqual(self.event.projection_control.write_owner,'unmanaged')
        self.assertTrue(models.RaceEventRevision.objects.filter(event=self.event).exists())

    def test_frozen_result_release_after_48_hours_preserves_source_capture_time(self):
        from datetime import timedelta
        path,sha=self.packet();before=snapshot([self.event.pk]);later=NOW+timedelta(hours=48)
        with patch('django.utils.timezone.now',return_value=later):
            report=execute(path,sha,apply=True,now=later)
            self.assertEqual(report['result_rows'],8)
            source=models.RaceResultSourceIdentity.objects.get(event=self.event,source_key='us_racing')
            self.assertEqual(source.identity_fields['multisource_v2']['fetched_at'],NOW.isoformat())
            self.event.refresh_from_db()
            self.assertEqual(self.event.source_refs['us_race_metadata']['observed_at'],NOW.isoformat())
            observation=models.RaceResultObservation.objects.get(source_identity=source)
            receipt=observation.field_provenance['archive_replay']
            self.assertEqual(receipt['manifest_sha256'],sha)
            self.assertEqual(receipt['source_fetched_at'],NOW.isoformat())
            self.assertEqual(report['events'][0]['archive_replay'],receipt)
            self.assertEqual(execute(path,sha,apply=True,now=later)['action'],'replay')
            execute(path,sha,restore=True,apply=True,now=later)
        for name in ['RaceEvent','RaceEventRunner','RaceEventResult']:
            self.assertEqual(snapshot([self.event.pk])[name],before[name],name)

    def test_archive_second_parse_must_match_bound_observation(self):
        from stable.services import race_data_source_adapters as adapters
        path,sha=self.packet();before=snapshot([self.event.pk]);original=adapters.fetch_bound_observation
        def changed(**kwargs):
            value=original(**kwargs);value['raw_sha256']='f'*64
            return value
        with patch('stable.services.race_data_source_adapters.fetch_bound_observation',side_effect=changed):
            with self.assertRaisesRegex(ValueError,f'result_identity_conflict:{self.event.pk}:archive_observation_mismatch'):
                execute(path,sha,apply=True,now=NOW)
        self.assertEqual(snapshot([self.event.pk]),before)

    def test_archive_release_with_existing_reviewed_roster_survives_source_attachment(self):
        from stable.services.race_pre_race import baseline
        from stable.services.race_data_source_adapters import canonical_sha, fetch_bound_observation
        items=[{'horse_number':row['number'],'horse_name':row['horse_name']} for row in self.value['roster']]
        candidate=models.RaceEventDataCandidate.objects.create(
            event=self.event,module='runners',source_name='reviewed_pre_race_v1',
            source_url=self.value['canonical_url'],fetched_at=NOW,candidate_payload={'items':items},
            raw_payload={'reviewed_pre_race_v1':{'validated':True,'baseline':baseline(self.event),
                'raw_sha256':self.value['raw_sha256'],'row_count':len(items),'items_sha256':canonical_sha(items)}})
        first=fetch_bound_observation(event=self.event,route=self.route,now=NOW,fetcher=self.fetch)
        self.assertEqual(first['identity_seed_receipt']['candidate_id'],candidate.pk)
        path,sha=self.packet();before=snapshot([self.event.pk])
        report=execute(path,sha,apply=True,now=NOW)
        self.assertEqual(report['result_rows'],8)
        source=models.RaceResultSourceIdentity.objects.get(event=self.event,source_key='us_racing')
        self.assertIn('identity_seed_receipt',source.identity_fields['multisource_v2'])
        second=fetch_bound_observation(event=self.event,route=self.route,now=NOW,fetcher=self.fetch)
        self.assertNotIn('identity_seed_receipt',second)
        self.assertEqual(execute(path,sha,apply=True,now=NOW)['action'],'replay')
        execute(path,sha,apply=True,restore=True,now=NOW)
        for name in ['RaceEvent','RaceEventRunner','RaceEventResult']:
            self.assertEqual(snapshot([self.event.pk])[name],before[name],name)
        candidate.refresh_from_db()
        self.assertEqual(candidate.status,'pending')
        self.assertEqual(candidate.candidate_payload,{'items':items})

    def test_commit_probe_recovers_when_command_output_was_lost(self):
        from io import StringIO
        from django.core.management import call_command
        path,sha=self.packet()
        output=StringIO()
        with patch.object(output,'write',side_effect=BrokenPipeError('lost output')):
            with self.assertRaises(BrokenPipeError):
                call_command('run_us_release',manifest=str(path),sha256=sha,apply=True,stdout=output)
        probe=StringIO()
        call_command('run_us_release',manifest=str(path),sha256=sha,probe_commit=True,stdout=probe)
        self.assertTrue(json.loads(probe.getvalue())['committed'])
        self.assertEqual(self.event.results.count(),8)
        execute(path,sha,restore=True,apply=True,now=NOW)
        self.assertFalse(self.event.results.exists())

    def test_commit_probe_distinguishes_rolled_back_dry_run(self):
        from io import StringIO
        from django.core.management import call_command,CommandError
        path,sha=self.packet();execute(path,sha,now=NOW)
        output=StringIO()
        call_command('run_us_release',manifest=str(path),sha256=sha,probe_commit=True,stdout=output)
        self.assertFalse(json.loads(output.getvalue())['committed'])
        with self.assertRaises(CommandError):
            call_command('run_us_release',manifest=str(path),sha256='0'*64,probe_commit=True)

    def test_changed_before_and_after_images_are_rejected(self):
        path,sha=self.packet()
        self.event.distance_text='manual changed';self.event.save()
        with self.assertRaisesRegex(ValueError,'baseline_drift'):execute(path,sha,apply=True,now=NOW)
        self.event.distance_text='';self.event.save()
        path,sha=self.packet();execute(path,sha,apply=True,now=NOW)
        models.RaceEventRunner.objects.filter(event=self.event).update(jockey_name='later edit')
        with self.assertRaisesRegex(ValueError,'restore_after_image_drift'):execute(path,sha,restore=True,apply=True,now=NOW)

    def test_twenty_one_targets_all_processed_across_claim_batches(self):
        events=[self.event]
        for i in range(20):
            events.append(models.RaceEvent.objects.create(year=2026,slug=f'us-release-{i}',original_name=f'Fixture {i}',
                country_region='united_states',racecourse='Churchill Downs',timezone_name='America/New_York',
                local_date=self.event.local_date,visibility_status='published',source_refs=self.event.source_refs))
        path,sha=self.packet(events)
        def observation(*,event,**kwargs):
            value=deepcopy(self.value)
            if event.pk!=self.event.pk:
                value.update(race_number=str(20+event.pk),external_race_id=f'CD:2026-11-07:{20+event.pk}',raw_names=[event.original_name])
                value['us_race_metadata']['external_race_id']=value['external_race_id']
            return value
        from datetime import timedelta
        from stable.services.us_release import run_multisource_claim
        clock=[NOW]
        def slow_claim(**kwargs):
            value=run_multisource_claim(**kwargs);clock[0]+=timedelta(seconds=20)
            return value
        with patch('stable.services.us_release.fetch_bound_observation',side_effect=observation),patch('stable.services.race_data_source_adapters.fetch_bound_observation',side_effect=observation),patch('django.utils.timezone.now',side_effect=lambda:clock[0]),patch('stable.services.us_release.run_multisource_claim',side_effect=slow_claim):
            result=execute(path,sha,apply=True,now=NOW)
        self.assertEqual(len(result['events']),21)
        self.assertEqual(result['result_rows'],21*8)
        self.assertEqual(set(e['rows'] for e in result['events']),{8})

    def test_rebind_baseline_allows_poll_clock_only_and_preserves_policy_guard(self):
        from stable.services.us_release import baseline_matches
        before={'RaceEvent':[{'id':7,'country_region':'japan','manual_lock_flags':{}}],
            'RaceEventLiveTracking':[{'id':9,'event_id':7,'last_attempt_at':'2026-11-11T00:00:00Z','claim_generation':5,'tracking_enabled':True}],
            'RaceDataSyncEnrollment':[{'id':10,'event_id':7,'standing_policy_digest':'old','updated_at':'old'}]}
        after=deepcopy(before);after['RaceEventLiveTracking'][0].update(last_attempt_at='2026-11-12T00:00:00Z',claim_generation=8)
        self.assertTrue(baseline_matches(after,before,[7]))
        after['RaceDataSyncEnrollment'][0]['standing_policy_digest']='changed'
        self.assertFalse(baseline_matches(after,before,[7]))

    def test_rollback_unlinks_new_division_and_restores_parent_eligibility(self):
        self.event.grade_text='G3';self.event.normalized_grade='G3';self.event.save()
        path,_=self.packet();manifest=json.loads(path.read_text());manifest['items'][0]['result_rows']=0
        manifest['items'].append(dict(year=2026,slug='restored-child',name='River City R5',racecourse='Churchill Downs',
            source_url='https://toba.org/graded-stakes/2026-races/',division_parent_id=self.event.pk,
            fields={'local_date':'2026-11-07','timezone_name':'America/New_York','visibility_status':'published'},result_rows=0))
        raw=json.dumps(manifest).encode();path.write_bytes(raw);sha=hashlib.sha256(raw).hexdigest()
        execute(path,sha,apply=True,now=NOW)
        self.assertTrue(self.event.divisions.exists())
        execute(path,sha,apply=True,restore=True,now=NOW)
        self.assertFalse(self.event.divisions.exists())
        self.assertEqual(models.RaceEvent.objects.get(slug='restored-child').visibility_status,'draft')

    def test_release_cannot_change_a_manually_locked_surface(self):
        from stable.services.us_release import _set_fields
        self.event.surface='turf';self.event.manual_lock_flags={'surface':True};self.event.save()
        with self.assertRaisesRegex(ValueError,'manual_field_lock'):
            _set_fields(self.event,{'surface':'dirt'})
        _set_fields(self.event,{'surface':'turf'})
        self.assertEqual(self.event.manual_lock_flags,{'surface':True})

    def test_slow_archive_validation_does_not_start_claims_in_the_past(self):
        from datetime import timedelta
        from stable.services import us_release
        path,sha=self.packet();clock=[NOW]
        original=us_release.fetch_bound_observation
        def slow_validation(**kwargs):
            value=original(**kwargs);clock[0]=NOW+timedelta(minutes=5)
            return value
        with patch('django.utils.timezone.now',side_effect=lambda:clock[0]),patch('stable.services.us_release.fetch_bound_observation',side_effect=slow_validation):
            result=execute(path,sha,apply=True,now=NOW)
        self.assertEqual(result['result_rows'],8)

    def test_restore_preserves_original_public_timestamps(self):
        from datetime import timedelta
        path,sha=self.packet();before=snapshot([self.event.pk])
        execute(path,sha,apply=True,now=NOW)
        with patch('django.utils.timezone.now',return_value=NOW+timedelta(minutes=10)):
            execute(path,sha,restore=True,apply=True,now=NOW+timedelta(minutes=10))
        after=snapshot([self.event.pk])
        for name in ['RaceEvent','RaceEventRunner','RaceEventResult']:
            self.assertEqual(after[name],before[name],name)

    @override_settings(RACE_DATA_SYNC_ENABLED_PROVIDERS=('us_racing','jra'),RACE_DATA_SYNC_ENABLED_REGIONS=('united_states','japan_jra'))
    def test_policy_extension_rebinds_existing_japan_and_restores_it(self):
        from datetime import date
        from stable.test_race_multisource_identity import policy_payload,observation
        from stable.services.race_data_source_adapters import parse_multisource_policy,canonical_sha
        from stable.services.race_source_identity import identity_key
        from stable.services.race_data_sync_enrollment import attach_multisource_observation
        old_data=policy_payload()
        old_data.update(valid_from='2026-01-01T00:00:00Z',valid_until='2028-01-01T00:00:00Z')
        old_data['routes'][0].update(valid_from=old_data['valid_from'],valid_until=old_data['valid_until'])
        old_policy=parse_multisource_policy(old_data,now=NOW)
        other=models.RaceEvent.objects.create(year=2026,slug='old-japan',original_name='オールカマー',country_region='japan',
            racecourse='中山',local_date=date(2026,9,20),timezone_name='Asia/Tokyo',visibility_status='published')
        value=observation(fetched_at=NOW.isoformat())
        models.RaceEventIdentityKey.objects.create(event=other,**identity_key(value))
        decision=attach_multisource_observation(value,policy=old_policy,now=NOW)
        self.assertEqual(decision.action,'acquired')
        old_binding=models.RaceDataSyncSourceBinding.objects.get(enrollment__event=other)
        models.RaceResultSourceIdentity.objects.create(
            event=other,source_key='the_racing_api',external_race_id='old-provider-race',registry_digest='a'*64)
        models.RaceEventLiveProviderCheckpoint.objects.create(
            tracking=other.live_tracking,source_key='the_racing_api',data_kind='result',
            registry_digest='a'*64,contract_digest='b'*64,next_poll_at=NOW)
        old_surface=snapshot([other.pk])
        combined=deepcopy(self.policy.payload);combined['routes']+=old_data['routes']
        self.policy=parse_multisource_policy(combined,now=NOW)
        path,_=self.packet();manifest=json.loads(path.read_text())
        raw=json.dumps(snapshot([self.event.pk,other.pk])).encode();(path.parent/'baseline.json').write_bytes(raw)
        manifest['baseline']['sha256']=hashlib.sha256(raw).hexdigest()
        manifest['rebind']=[dict(event_id=other.pk,old_route_digest=old_binding.route_digest)]
        raw=json.dumps(manifest).encode();path.write_bytes(raw);sha=hashlib.sha256(raw).hexdigest()
        with patch('stable.services.us_release.load_multisource_policy',return_value=self.policy),patch('stable.services.race_data_source_adapters.load_multisource_policy',return_value=self.policy):
            report=execute(path,sha,apply=True,now=NOW)
            self.assertEqual(report['rebind_ids'],[other.pk])
            self.assertEqual(models.RaceDataSyncEnrollment.objects.get(event=other).standing_policy_digest,self.policy.digest)
            self.assertEqual(snapshot([other.pk])['RaceEvent'],old_surface['RaceEvent'])
            execute(path,sha,restore=True,apply=True,now=NOW)
        after=snapshot([other.pk])
        self.assertEqual(after,old_surface)

    def test_restore_old_result_rows_after_replacing_same_positions(self):
        models.RaceEventResult.objects.create(event=self.event,finish_position=1,horse_name='Legacy winner',is_confirmed=True)
        path,sha=self.packet();before=snapshot([self.event.pk])
        execute(path,sha,apply=True,now=NOW)
        self.assertFalse(self.event.results.filter(horse_name='Legacy winner').exists())
        execute(path,sha,restore=True,apply=True,now=NOW)
        self.assertEqual(snapshot([self.event.pk])['RaceEventResult'],before['RaceEventResult'])


@skipUnless(connection.vendor=='postgresql','requires PostgreSQL row locks')
class USReleaseCommitProbePostgresTests(TransactionTestCase):
    def test_probe_waits_for_inflight_transaction_and_sees_its_commit(self):
        from stable.services.us_release import probe_release_commit
        event=models.RaceEvent.objects.create(year=2026,slug='us-commit-probe',
            original_name='Commit probe',country_region='united_states')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'manifest.json'
            raw=json.dumps({'schema_version':1,'action':'us_release_data',
                'items':[{'event_id':event.pk}],'rebind':[]}).encode()
            path.write_bytes(raw);sha=hashlib.sha256(raw).hexdigest()
            ready=threading.Event();state={}
            def probe():
                try:
                    with connections['default'].cursor() as cursor:
                        cursor.execute('SELECT pg_backend_pid()');state['pid']=cursor.fetchone()[0]
                    ready.set();state['result']=probe_release_commit(path,sha)
                except BaseException as exc:state['error']=exc
                finally:connections.close_all()
            thread=threading.Thread(target=probe,daemon=True)
            try:
                with transaction.atomic():
                    models.RaceEvent.objects.select_for_update().get(pk=event.pk)
                    thread.start();self.assertTrue(ready.wait(5))
                    deadline=time.monotonic()+5;blocked=False
                    while time.monotonic()<deadline:
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT pg_stat_clear_snapshot()')
                            cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s',[state['pid']])
                            row=cursor.fetchone()
                        if row and row[0]=='Lock':blocked=True;break
                        if 'error' in state or 'result' in state:break
                        time.sleep(.01)
                    self.assertTrue(blocked,state)
                    models.OperationLog.objects.create(action_type='us_release_data',
                        target_type='manifest',target_id=sha,detail='{}')
            finally:
                if thread.ident is not None:thread.join(10)
            self.assertFalse(thread.is_alive())
            if 'error' in state:raise state['error']
            self.assertTrue(state['result']['committed'])

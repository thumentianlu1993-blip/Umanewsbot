"""英国发布包事务、失败回滚、重放与来源原件绑定。"""
import hashlib,json,tempfile
from pathlib import Path
from django.test import TestCase,override_settings
from unittest.mock import patch
from stable import test_uk_workflow as workflow
from stable.services.uk_release import execute,snapshot
from stable.services.race_data_source_adapters import canonical_sha
from stable.services.uk_collection import api_url
NOW=workflow.NOW

@override_settings(**workflow.UKWorkflowTests._overridden_settings)
class UKReleaseTests(TestCase):
    def setUp(self):
        workflow.UKWorkflowTests.setUp(self);self.source.delete()
        p=patch("stable.services.uk_release.load_multisource_policy",return_value=self.policy);p.start();self.addCleanup(p.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        def put(name,value):
            raw=json.dumps(value,ensure_ascii=False).encode();(self.root/name).write_bytes(raw)
            return {'file':name,'sha256':hashlib.sha256(raw).hexdigest()}
        self.put=put;docs=[]
        for kind,data in [('card',self.card),('result',self.result)]:
            docs.append({**put(kind+'.json',data),'url':api_url(kind,race_id='rac_123'),'fetched_at':NOW.isoformat()})
        item=dict(event_id=self.event.pk,year=2026,name='Example Stakes',racecourse='Newmarket',
            result_rows=2,reset_projection=True,fields={'source_refs':self.event.source_refs})
        self.manifest=dict(schema_version=1,action='uk_release_data',items=[item],rebind=[],policy_digest=self.policy.digest,
            baseline=put('baseline.json',snapshot([self.event.pk],[])),archive=put('archive.json',{'documents':docs}))

    def run_package(self,**kwargs):
        spec=self.put('manifest.json',self.manifest)
        return execute(self.root/'manifest.json',spec['sha256'],now=NOW,**kwargs)

    def test_dry_run_apply_replay_restore(self):
        self.assertEqual(self.run_package()['action'],'dry_run_rolled_back')
        self.assertFalse(self.event.results.exists())
        result=self.run_package(apply=True);self.assertEqual(result['result_rows'],2)
        self.assertEqual(self.run_package(apply=True)['action'],'replay')
        self.assertEqual(self.run_package(restore=True,apply=True)['action'],'restored')
        self.event.refresh_from_db();self.assertEqual(self.event.status,'scheduled');self.assertFalse(self.event.results.exists())

    def test_commit_probe_distinguishes_applied_and_unapplied(self):
        from stable.services.uk_release import probe_release_commit
        spec=self.put('manifest.json',self.manifest)
        self.assertFalse(probe_release_commit(self.root/'manifest.json',spec['sha256'])['committed'])
        self.run_package(apply=True)
        self.assertTrue(probe_release_commit(self.root/'manifest.json',spec['sha256'])['committed'])

    def test_late_failure_rolls_back_all_public_and_control_writes(self):
        self.manifest['items'][0]['result_rows']=3
        before=snapshot([self.event.pk],[])
        with self.assertRaisesRegex(ValueError,'result_count'):self.run_package(apply=True)
        self.assertEqual(snapshot([self.event.pk],[]),before)

    def test_same_provider_legacy_checkpoint_is_rebound(self):
        from stable import models
        tracking=models.RaceEventLiveTracking.objects.create(event=self.event)
        models.RaceEventLiveProviderCheckpoint.objects.create(tracking=tracking,source_key='the_racing_api',
            data_kind='result',contract_digest='a'*64,registry_digest='b'*64)
        self.manifest['baseline']=self.put('baseline.json',snapshot([self.event.pk],[]))
        self.assertEqual(self.run_package(apply=True)['result_rows'],2)
        cp=models.RaceEventLiveProviderCheckpoint.objects.get(tracking=tracking,source_key='the_racing_api',data_kind='result')
        self.assertEqual(cp.registry_digest,self.route.digest)
        self.assertEqual(cp.contract_digest,self.route.contract_digest)

    def test_tampered_archive_rejected(self):
        (self.root/'result.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'archive_digest'):self.run_package(apply=True)

from datetime import date
from django.test import TestCase
from stable import models


class IdentityRepairTests(TestCase):
    def setUp(self):
        self.event=models.RaceEvent.objects.create(pk=829,year=2026,slug='chambly',original_name='PRIX DE CHAMBL Y',
            chinese_name='尚布利',country_region='france',racecourse='Auteuil',local_date=date(2026,9,17),
            timezone_name='Europe/Paris',visibility_status='published')
        self.manifest={'schema_version':1,'repairs':[{'event_id':829,'before':{
            'year':2026,'slug':'chambly','original_name':'PRIX DE CHAMBL Y','country_region':'france',
            'racecourse':'Auteuil','local_date':'2026-09-17','timezone_name':'Europe/Paris'},
            'original_name':'PRIX DE CHAMBLY','aliases':['PRIX DE CHAMBL Y','PRIX DE CHAMBLY']}]}

    def apply(self, **kwargs):
        from stable.management.commands.repair_race_section_identities import repair_identities
        return repair_identities(self.manifest,manifest_sha='a'*64,**kwargs)

    def test_dry_run_writes_nothing(self):
        self.assertEqual(self.apply(apply=False)['mode'],'dry_run')
        self.event.refresh_from_db()
        self.assertEqual(self.event.original_name,'PRIX DE CHAMBL Y')
        self.assertFalse(self.event.aliases.exists())
        self.assertFalse(self.event.data_candidates.exists())

    def test_apply_preserves_path_audits_and_replays(self):
        path=self.event.public_path
        self.assertEqual(self.apply(apply=True)['changed'],[829])
        self.event.refresh_from_db()
        self.assertEqual(self.event.original_name,'PRIX DE CHAMBLY')
        self.assertEqual(self.event.public_path,path)
        self.assertEqual(self.event.aliases.count(),2)
        self.assertEqual(self.apply(apply=True)['replayed'],[829])
        self.assertEqual(models.TaskExecutionLog.objects.filter(task_name='repair_race_section_identities').count(),1)
        self.assertFalse(self.event.data_candidates.exists())
        self.assertIsNone(self.event.race_datetime)
        self.assertEqual(self.event.status,'scheduled')

    def test_drift_or_managed_owner_writes_nothing(self):
        self.event.manual_lock_flags={'basic':True}
        self.event.save()
        with self.assertRaises(ValueError): self.apply(apply=True)
        self.event.manual_lock_flags={}
        self.event.original_name='Manual name'
        self.event.save()
        with self.assertRaises(ValueError): self.apply(apply=True)
        self.event.original_name='PRIX DE CHAMBL Y'
        self.event.save()
        models.RaceEventProjectionControl.objects.create(event=self.event,write_owner='data_sync')
        with self.assertRaises(ValueError): self.apply(apply=True)
        self.assertFalse(self.event.aliases.exists())

    def test_later_failure_rolls_back_whole_two_event_package(self):
        target=models.RaceEvent.objects.create(pk=104,year=2026,slug='all-comers',original_name='オールカマー',
            chinese_name='产经赏',country_region='japan',racecourse='中山',local_date=date(2026,9,20),timezone_name='Asia/Tokyo')
        self.manifest['repairs'].append({'event_id':104,'before':{
            'year':2026,'slug':'all-comers','original_name':'オールカマー','country_region':'japan',
            'racecourse':'中山','local_date':'2026-09-20','timezone_name':'Asia/Tokyo'},'aliases':['産経賞オールカマー']})
        self.manifest['repairs'][0]['before']['original_name']='Drifted baseline'
        with self.assertRaises(ValueError): self.apply(apply=True)
        self.event.refresh_from_db()
        self.assertEqual(self.event.original_name,'PRIX DE CHAMBL Y')
        self.assertFalse(target.aliases.exists())
        self.assertFalse(models.TaskExecutionLog.objects.filter(task_name='repair_race_section_identities').exists())

    def test_existing_french_alias_keeps_metadata_and_audit_is_exact(self):
        alias=models.RaceEventAlias.objects.create(event=self.event,text='PRIX DE CHAMBL Y',source_language='fr',source='annual-pdf',alias_type='official',is_active=True)
        result=self.apply(apply=True)
        alias.refresh_from_db()
        self.assertEqual((alias.source,alias.alias_type,alias.source_language),('annual-pdf','official','fr'))
        self.assertEqual(self.event.aliases.count(),2)
        self.assertEqual(result['events'][0]['added_aliases'],[{'text':'PRIX DE CHAMBLY','source_language':'fr'}])
        self.assertFalse(self.event.aliases.filter(source_language='en').exists())

    def test_inactive_alias_is_not_silently_reactivated_or_duplicated(self):
        models.RaceEventAlias.objects.create(event=self.event,text='PRIX DE CHAMBLY',source_language='fr',source='manual',is_active=False)
        with self.assertRaises(ValueError): self.apply(apply=True)
        self.event.refresh_from_db()
        self.assertEqual(self.event.original_name,'PRIX DE CHAMBL Y')
        self.assertEqual(self.event.aliases.count(),1)
        self.assertFalse(self.event.aliases.filter(is_active=True).exists())

    def test_repository_manifest_dry_run_and_sha_rejection(self):
        from pathlib import Path
        from io import StringIO
        import hashlib,json
        from django.core.management import call_command,CommandError
        path=Path(__file__).resolve().parents[2]/'docs/changes/fix-race-section-gaps/evidence/identity_repairs.json'
        raw=path.read_bytes()
        data=json.loads(raw)
        self.event.delete()
        for row in data['repairs']:
            fields=dict(row['before'])
            fields['local_date']=date.fromisoformat(fields['local_date'])
            models.RaceEvent.objects.create(pk=row['event_id'],chinese_name='核对样本',visibility_status='published',**fields)
        out=StringIO()
        call_command('repair_race_section_identities',manifest=str(path),sha256=hashlib.sha256(raw).hexdigest(),stdout=out)
        self.assertEqual(json.loads(out.getvalue())['changed'],[104,829])
        self.assertFalse(models.RaceEventAlias.objects.exists())
        with self.assertRaises(CommandError):
            call_command('repair_race_section_identities',manifest=str(path),sha256='0'*64,apply=True,stdout=StringIO())
        self.assertFalse(models.RaceEventAlias.objects.exists())

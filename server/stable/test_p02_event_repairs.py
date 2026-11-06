import hashlib
import json
from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.management import call_command, CommandError
from django.test import TestCase
from stable.models import RaceSeries, RaceEvent, HistoricalRaceEventTarget
from stable.management.commands.register_p02_canonical_names import digest
from stable.services.historical_race_batches import materialization_snapshot


class EventRepairTests(TestCase):
    def actions(self):
        series=RaceSeries.objects.create(key='uk-future',canonical_name_original='Future',
            country_region='united_kingdom',review_status='approved')
        target=HistoricalRaceEventTarget.objects.create(race_series=series,year=2026,
            country_region='united_kingdom',original_name='Future',racecourse='Ascot',
            local_date=date(2026,11,15),expectation_status='not_due',resolution_status='source_unavailable',
            source_refs={'calendar':'reviewed'},artifact_sha256='a'*64)
        event=RaceEvent.objects.create(year=2026,edition_year=2026,slug='fr-old',original_name='French Race',
            country_region='france',local_date=date(2026,10,4),racecourse='ParisLongchamp',timezone_name='Asia/Shanghai')
        return [
            {'action':'materialize_scheduled_historical_event','target_id':target.pk,'preconditions':{
                'event_id':None,'local_date':'2026-11-15','expectation_status':'not_due','resolution_status':'source_unavailable',
                'race_series_id':series.pk,'race_series_review_status':'approved','artifact_sha256':'a'*64,
                'source_refs_sha256':digest(target.source_refs),'materialization_snapshot_sha256':digest(materialization_snapshot(target)),'original_name':'Future','racecourse':'Ascot'},
             'result':{'status':'scheduled','visibility_status':'draft','coverage_status_unchanged':True}},
            {'action':'correct_timezone_name','event_id':event.pk,'preconditions':{'original_name':'French Race',
                'local_date':'2026-10-04','racecourse':'ParisLongchamp','timezone_name':'Asia/Shanghai'},
             'set':{'timezone_name':'Europe/Paris'}}]

    def run_manifest(self, actions, apply=False):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'actions.json';p.write_text(json.dumps({'schema':'p02-data-actions-v1','actions':actions}))
            out=StringIO()
            with patch('django.utils.timezone.localdate',return_value=date(2026,11,6)):
                call_command('apply_p02_event_repairs',manifest=str(p),expected_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),apply=apply,stdout=out)
            return json.loads(out.getvalue())

    def test_dry_run_then_apply_and_repeat_preserves_coverage(self):
        actions=self.actions()
        self.run_manifest(actions)
        self.assertIsNone(HistoricalRaceEventTarget.objects.get().event_id)
        result=self.run_manifest(actions,apply=True)
        self.assertEqual(len(result['created_event_ids']),1)
        self.run_manifest(actions,apply=True)
        target=HistoricalRaceEventTarget.objects.get()
        self.assertEqual((target.expectation_status,target.resolution_status),('not_due','source_unavailable'))
        self.assertEqual(target.event.visibility_status,'draft')
        self.assertEqual(RaceEvent.objects.count(),2)
        event=RaceEvent.objects.get(pk=actions[1]['event_id'])
        self.assertEqual(event.timezone_name,'Europe/Paris')
        self.assertEqual(event.local_date,date(2026,10,4))

    def test_late_identity_drift_rolls_back_creation(self):
        actions=self.actions()
        RaceEvent.objects.filter(pk=actions[1]['event_id']).update(original_name='Changed')
        with self.assertRaises(CommandError):self.run_manifest(actions,apply=True)
        self.assertIsNone(HistoricalRaceEventTarget.objects.get().event_id)
        self.assertEqual(RaceEvent.objects.count(),1)

    def test_repeat_rejects_post_apply_target_drift(self):
        actions=self.actions();self.run_manifest(actions,apply=True)
        HistoricalRaceEventTarget.objects.update(original_name='Changed')
        with self.assertRaises(CommandError):self.run_manifest(actions,apply=True)

    def test_rejects_unapproved_timezone_mapping(self):
        actions=self.actions();actions[1]['set']['timezone_name']='America/New_York'
        with self.assertRaises(CommandError):self.run_manifest(actions,apply=True)
        self.assertIsNone(HistoricalRaceEventTarget.objects.get().event_id)

    def test_unexpected_existing_canonical_is_not_adopted(self):
        actions=self.actions()
        RaceEvent.objects.create(year=2026,edition_year=2026,slug='unexpected',
            race_series_id=actions[0]['preconditions']['race_series_id'],original_name='Future',
            country_region='united_kingdom',local_date=date(2026,11,15))
        with self.assertRaises(CommandError):self.run_manifest(actions,apply=True)
        self.assertIsNone(HistoricalRaceEventTarget.objects.get().event_id)

    def test_copied_field_drift_rejects_same_manifest(self):
        actions=self.actions()
        HistoricalRaceEventTarget.objects.update(distance_text='9999m',grade_text='G1')
        with self.assertRaises(CommandError):self.run_manifest(actions,apply=True)
        self.assertIsNone(HistoricalRaceEventTarget.objects.get().event_id)

    def test_dry_run_rejects_empty_source_even_with_matching_digest(self):
        actions=self.actions()
        HistoricalRaceEventTarget.objects.update(source_refs={})
        actions[0]['preconditions']['source_refs_sha256']=digest({})
        actions[0]['preconditions']['materialization_snapshot_sha256']=digest(materialization_snapshot(HistoricalRaceEventTarget.objects.get()))
        with self.assertRaises(CommandError):self.run_manifest(actions)

    def test_dry_run_rejects_slug_conflict(self):
        from stable.services.historical_race_batches import historical_event_slug
        actions=self.actions();target=HistoricalRaceEventTarget.objects.get()
        RaceEvent.objects.create(year=2026,edition_year=2026,slug=historical_event_slug(target,public_year=2026),
            original_name='Unrelated',country_region='united_kingdom')
        with self.assertRaises(CommandError):self.run_manifest(actions)

    def test_repeat_rejects_materialized_canonical_identity_drift(self):
        actions=self.actions();self.run_manifest(actions,apply=True)
        event=HistoricalRaceEventTarget.objects.get().event
        event.country_region='france';event.slug='changed-identity'
        event.save(update_fields={'country_region','slug'})
        with self.assertRaises(CommandError):self.run_manifest(actions,apply=True)

import hashlib
import json
import unicodedata
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command, CommandError
from django.test import TestCase
from stable.models import RaceSeries, RaceEvent, RaceSeriesName


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class CanonicalNameRegistrationTests(TestCase):
    def make_item(self, key):
        series = RaceSeries.objects.create(key=key, canonical_name_original=key, country_region='france',
            review_status='approved', source_refs={'catalog': 'reviewed'})
        event = RaceEvent.objects.create(year=2026, edition_year=2026, slug=key, race_series=series,
            original_name=key, country_region='france')
        snapshot = {k:getattr(series,k) for k in ('id','key','canonical_name_original','country_region','review_status','source_refs')}
        return {'action':'register_existing_reviewed_canonical_name','series_id':series.pk,'event_id':event.pk,
            'text':unicodedata.normalize('NFKC',key),'name_type':'canonical','valid_from_year':2026,'valid_to_year':2026,
            'preconditions':{'series_sha256':digest(snapshot),'event_edition_year':2026,'series_review_status':'approved','no_existing_name_conflict':True},
            'source_refs':{'basis':'existing_approved_series_canonical','series_source_refs':series.source_refs,
                'series_source_refs_sha256':digest(series.source_refs),'source_snapshot':'test.json'}}

    def run_manifest(self, items, apply=False, wrong_sha=False):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'names.json';p.write_text(json.dumps({'count':len(items),'items':items}))
            sha=hashlib.sha256(p.read_bytes()).hexdigest()
            out=StringIO()
            call_command('register_p02_canonical_names', manifest=str(p), expected_sha256='0'*64 if wrong_sha else sha,
                         apply=apply, stdout=out)
            return json.loads(out.getvalue())

    def test_dry_run_and_idempotent_apply(self):
        items=[self.make_item('Exact Name')]
        self.assertEqual(self.run_manifest(items)['would_create'],1)
        self.assertFalse(RaceSeriesName.objects.exists())
        self.run_manifest(items,apply=True)
        self.assertEqual(self.run_manifest(items,apply=True)['would_create'],0)
        self.assertEqual(RaceSeriesName.objects.count(),1)

    def test_late_drift_leaves_no_partial_names(self):
        items=[self.make_item('First'),self.make_item('Second')]
        RaceSeries.objects.filter(pk=items[1]['series_id']).update(review_status='pending')
        with self.assertRaises(CommandError):self.run_manifest(items,apply=True)
        self.assertFalse(RaceSeriesName.objects.exists())

    def test_wrong_digest_or_invented_name_rejected(self):
        items=[self.make_item('Known')]
        with self.assertRaises(CommandError):self.run_manifest(items,apply=True,wrong_sha=True)
        items[0]['text']='Invented Alias'
        with self.assertRaises(CommandError):self.run_manifest(items,apply=True)
        self.assertFalse(RaceSeriesName.objects.exists())

    def test_conflicting_other_series_name_rejected(self):
        item=self.make_item('Known');other=self.make_item('Other')
        RaceSeriesName.objects.create(series_id=other['series_id'],text='Known',valid_from_year=2026,
            valid_to_year=2026,source_refs={'source':'other'})
        with self.assertRaises(CommandError):self.run_manifest([item],apply=True)
        self.assertEqual(RaceSeriesName.objects.count(),1)

    def test_write_failure_rolls_back_entire_batch(self):
        from unittest.mock import patch
        items=[self.make_item('First'),self.make_item('Second')]
        save=RaceSeriesName.save
        calls=[]
        def fail_second(row,*args,**kwargs):
            calls.append(row.text)
            if len(calls)==2:raise RuntimeError('simulated_write_failure')
            return save(row,*args,**kwargs)
        with patch.object(RaceSeriesName,'save',fail_second):
            with self.assertRaisesRegex(RuntimeError,'simulated_write_failure'):
                self.run_manifest(items,apply=True)
        self.assertFalse(RaceSeriesName.objects.exists())

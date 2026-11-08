"""HKJC 完整赛果从真实离线页面到公开字段的回归。"""
from datetime import date
from unittest.mock import patch
from django.test import TestCase, SimpleTestCase, override_settings
from stable import models
from stable.test_hkjc_automation import ROOT, NOW, route
from stable.test_race_multisource_identity import policy_payload
from stable import test_race_multisource_jra as workflow
from stable.services.race_data_source_adapters import parse_hkjc_observation, parse_multisource_policy, run_multisource_claim
from stable.services.race_data_sync_enrollment import attach_multisource_observation
from stable.services.race_data_sync_control import claim_multisource_events
from stable.services.race_information_display import row_fields

URL='https://racing.hkjc.com/en-us/local/information/localresults?racedate=2026/10/19&Racecourse=ST&RaceNo=8'


class HKJCSourceFieldTests(SimpleTestCase):
    def test_real_margin_notation_and_missing_cells_are_normalized(self):
        from stable.services.hkjc_public_fields import margin_value
        for raw,expected in [('7-3/4','7 3/4'),('N','neck'),('HD','head'),('---',''),('SH','short head')]:
            self.assertEqual(margin_value(raw),expected)


    def test_official_non_finish_symbols_keep_status_without_a_rank(self):
        from bs4 import BeautifulSoup
        for symbol,status in [('WV-A','withdrawn'),('WR','withdrawn'),('WX','withdrawn'),('WX-A','withdrawn'),('TNP','non_runner'),('FE','fell')]:
            soup=BeautifulSoup((ROOT/'result-withdrawn.html').read_text(),'html.parser')
            for cell in soup.select('td'):
                if cell.get_text(strip=True)=='WV':cell.string=symbol
            value=parse_hkjc_observation(str(soup),url=URL,route=route(),now=NOW)
            row=next(r for r in value['roster'] if r['number']=='4')
            self.assertEqual(row['status'],status);self.assertIsNone(row['reported_finish_position'])


@override_settings(**{**workflow.JraColdStartTests._overridden_settings,
    'RACE_DATA_SYNC_ENABLED_PROVIDERS':('hkjc',), 'RACE_DATA_SYNC_ENABLED_REGIONS':('hong_kong',)})
class HKJCResultFieldTests(TestCase):
    def setUp(self):
        data=policy_payload('hkjc','hong_kong')
        data.update(valid_from='2026-01-01T00:00:00Z',valid_until='2028-01-01T00:00:00Z')
        data['routes'][0].update(route().payload,country_region='hong_kong')
        self.policy=parse_multisource_policy(data,now=NOW)
        self.page=(ROOT/'result-withdrawn.html').read_text()
        self.value=parse_hkjc_observation(self.page,url=URL,route=self.policy.routes[0],now=NOW)
        series=models.RaceSeries.objects.create(key='test-hkjc-sha-tin',canonical_name_original='Sha Tin Trophy',
            country_region='hong_kong',review_status='approved',source_refs={'primary':URL})
        models.RaceSeriesName.objects.create(series=series,text=self.value['raw_names'][0],
            source_language='en',source_refs={'primary':URL})
        self.event=models.RaceEvent.objects.create(year=2026,edition_year=2026,slug='hkjc-result-fields',
            original_name='Sha Tin Trophy (H)',country_region='hong_kong',racecourse='Sha Tin',
            local_date=date(2026,10,19),timezone_name='Asia/Hong_Kong',status='scheduled',
            visibility_status='published',race_series=series)
        for target,value in [('stable.services.race_data_source_adapters.load_multisource_policy',self.policy),
                             ('django.utils.timezone.now',NOW)]:
            patcher=patch(target,return_value=value);patcher.start();self.addCleanup(patcher.stop)

    def publish(self):
        decision=attach_multisource_observation(self.value,policy=self.policy,now=NOW)
        self.assertEqual(decision.action,'acquired',decision)
        claims=claim_multisource_events(event_ids=[self.event.pk],now=NOW,historical=True)
        self.assertEqual(len(claims),1)
        result=run_multisource_claim(claim=claims[0],now=NOW,fetcher=lambda *a,**kw:self.page)
        self.assertTrue(result['processed'],result)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status,'finished')

    def test_full_roster_fields_survive_publication(self):
        self.publish()
        self.assertEqual(self.event.results.count(),12)
        for row in self.event.results.all():
            fields=row_fields(row)
            self.assertIn('磅',fields['weight'].text)
            self.assertNotEqual(fields['margin'].text,'待核实')
            if row.running_status!='withdrawn':
                self.assertTrue(row.odds_value)
                self.assertNotEqual(fields['odds'].text,'待核实')
        for runner in self.event.runners.all():
            result=self.event.results.get(horse_number=runner.horse_number)
            self.assertEqual(runner.running_status,result.running_status)
        self.assertEqual(self.event.results.get(horse_number='4').running_status,'withdrawn')

    def test_existing_status_lock_is_not_overwritten(self):
        for row in self.value['roster']:
            models.RaceEventRunner.objects.create(event=self.event,horse_number=row['number'],horse_name=row['horse_name'],
                source_refs={'hkjc':row['external_runner_id']},running_status='declared',
                carried_weight='60kg',manual_lock_flags={'running_status':True,'carried_weight':True})
        self.publish()
        self.assertTrue(all(r.running_status=='declared' and r.carried_weight=='60kg' for r in self.event.runners.all()))

    def package(self):
        import tempfile, hashlib, json
        from pathlib import Path
        from stable.management.commands.repair_hkjc_race_fields import snapshot
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);root=Path(folder.name)
        page=root/'result.html';page.write_text(self.page)
        item=dict(event_id=self.event.pk,baseline_sha256=snapshot(self.event),
            result=dict(file=page.name,sha256=hashlib.sha256(page.read_bytes()).hexdigest(),url=URL,
                        external_race_id=self.value['external_race_id']))
        body=dict(schema_version=1,action='repair_hkjc_race_fields',policy_digest=self.policy.digest,items=[item])
        path=root/'manifest.json';path.write_text(json.dumps(body));return path,hashlib.sha256(path.read_bytes()).hexdigest()

    def test_fixed_package_dry_run_apply_and_replay(self):
        from stable.management.commands.repair_hkjc_race_fields import execute, snapshot
        path,sha=self.package();before=snapshot(self.event)
        result=execute(path,sha,now=NOW)
        self.assertEqual(result['action'],'dry_run_rolled_back')
        self.event.refresh_from_db();self.assertEqual(snapshot(self.event),before)
        self.assertEqual(self.event.results.count(),0)
        execute(path,sha,apply=True,now=NOW)
        self.assertEqual(self.event.results.count(),12)
        self.assertEqual(execute(path,sha,apply=True,now=NOW)['action'],'replay')

    def test_package_rejects_changed_source_and_manual_lock(self):
        import hashlib
        from stable.management.commands.repair_hkjc_race_fields import execute
        path,sha=self.package()
        self.event.manual_lock_flags={'race_time':True};self.event.save()
        with self.assertRaises(ValueError):execute(path,sha,apply=True,now=NOW)
        self.assertEqual(self.event.results.count(),0)
        self.event.manual_lock_flags={};self.event.save()
        (path.parent/'result.html').write_text('changed')
        with self.assertRaisesMessage(ValueError,'artifact_digest'):execute(path,sha,apply=True,now=NOW)
        self.assertEqual(self.event.results.count(),0)

    def test_existing_verified_pound_and_odds_values_gain_units(self):
        for row in self.value['roster']:
            models.RaceEventRunner.objects.create(event=self.event,horse_number=row['number'],horse_name=row['horse_name'],
                source_refs={'hkjc':row['external_runner_id']},carried_weight=row['carried_weight'].removesuffix('lb'),
                odds_value=row['odds_value'])
        self.publish()
        for runner in self.event.runners.all():
            self.assertIn('磅',row_fields(runner)['weight'].text)
            self.assertNotEqual(row_fields(runner)['odds'].text,'待核实')

    @override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=True)
    def test_result_bootstrap_is_not_presented_as_a_pre_race_card(self):
        self.publish()
        response=self.client.get(f'/races/{self.event.year}/{self.event.slug}/')
        self.assertContains(response,'参赛记录（赛果来源）')
        self.assertContains(response,'<th>负重</th>',html=True)
        self.assertContains(response,'差距（距头马）')

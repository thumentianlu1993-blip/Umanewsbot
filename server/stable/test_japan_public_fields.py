"""日本官方字段从来源证据到公开表格的回归；不访问网络。"""
from datetime import date
from types import SimpleNamespace

from bs4 import BeautifulSoup
from django.test import SimpleTestCase, TestCase, override_settings

from stable import models
from stable import test_japan_automation as real
from stable import test_race_multisource_jra as workflow
from stable.services import race_pre_race as pre
from stable.services.race_field_normalization import parse_display_margin
from stable.services.race_information_display import row_fields


@override_settings(RACE_DATA_SYNC_ENABLED_FIELDS=('participants.horse_name', 'participants.carried_weight', 'participants.status'))
class JapanPreviewFieldTests(SimpleTestCase):
    def test_existing_registration_preview_has_explicit_kilograms_without_mutation(self):
        event = models.RaceEvent(original_name='武蔵野S', country_region='japan',
            local_date=date(2026, 11, 14), timezone_name='Asia/Tokyo')
        items = [{'horse_name': 'アピーリングルック', 'carried_weight': '55.0',
                  'running_status': 'declared', 'source_refs': {'primary': real.REGISTRATION}}]
        candidate = SimpleNamespace(source_name=pre.JRA, source_url=real.REGISTRATION,
            candidate_payload={'items': items}, fetched_at=real.NOW)
        preview = pre.preview_payload(event, candidate, 'registration', now=real.NOW)
        self.assertEqual(row_fields(preview['rows'][0])['weight'].text, '55千克')
        self.assertNotIn('field_units', items[0]['source_refs'])

    def test_new_jra_registration_retains_unit_contract(self):
        event = SimpleNamespace(original_name='武蔵野S', chinese_name='', racecourse='東京',
            local_date=date(2026, 11, 14), aliases=SimpleNamespace(values_list=lambda *a, **k: []))
        payload = pre.parse_jra_card((real.ROOT/'jra-registration.html').read_text(),
                                    event=event, url=real.REGISTRATION)
        self.assertEqual(row_fields(payload['items'][0])['weight'].text, '55千克')

    def test_japan_margin_notation_has_units_and_preserves_unknowns(self):
        for raw, expected in [('１ 1/2', '1.5马身'), ('1.1/2', '1.5马身'),
                              ('３／４', '0.75马身'), ('大差', '大差')]:
            with self.subTest(raw=raw):
                self.assertEqual(parse_display_margin(raw, unit_hint='length').text, expected)
        self.assertEqual(parse_display_margin('1.1/2').text, '待核实')
        self.assertEqual(parse_display_margin('2秒', unit_hint='length').text, '待核实')


@override_settings(**workflow.JraColdStartTests._overridden_settings)
class JapanResultFieldWorkflowTests(TestCase):
    setUp = workflow.JraColdStartTests.setUp
    fetch = workflow.JraColdStartTests.fetch
    enroll = workflow.JraColdStartTests.enroll
    claim = workflow.JraColdStartTests.claim

    def publish(self):
        self.enroll()
        result = workflow.run_multisource_claim(claim=self.claim(), now=workflow.NOW, fetcher=self.fetch)
        self.assertTrue(result['processed'], result)
        self.event.refresh_from_db()

    def test_published_result_exposes_source_popularity_weight_and_margin(self):
        self.publish()
        rows = list(self.event.results.order_by('finish_position'))
        for result in rows:
            original = result.raw_payload['field_provenance']['source_fields']
            self.assertEqual(result.popularity, original['popularity'])
            self.assertTrue(row_fields(result)['weight'].text.endswith('千克'))
            self.assertNotEqual(row_fields(result)['margin'].text, '待核实')
        self.assertTrue(any(row.popularity for row in rows))

    def test_cancelled_runner_matches_published_result_status(self):
        soup = BeautifulSoup(self.result, 'html.parser')
        last = soup.select('tbody > tr')[-1]
        number = last.select_one('td.num').get_text(strip=True)
        last.select_one('td.place').string = '取消'
        self.result = str(soup)
        self.publish()
        runner = self.event.runners.get(horse_number=number)
        result = self.event.results.get(horse_number=number)
        self.assertEqual(runner.running_status, result.running_status)
        self.assertEqual(runner.get_running_status_display(), '退赛')

    def test_formal_racecard_retains_weight_units(self):
        workflow.JraColdStartTests.test_card_and_schedule_use_bound_source_writer(self)
        for runner in self.event.runners.all():
            self.assertTrue(row_fields(runner)['weight'].text.endswith('千克'))

    @override_settings(RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True,
                       RACE_DATA_SYNC_ENABLED_FIELDS=('off_time', 'local_start_time', 'timezone_name'))
    def test_official_result_supplies_missing_start_time_in_beijing(self):
        from stable.services.race_public_time import public_time
        self.assertIsNone(self.event.race_datetime)
        self.publish()
        self.assertIsNotNone(self.event.race_datetime)
        stamp = public_time(self.event)
        self.assertEqual(stamp.clock.strftime('%H:%M'), '14:45')
        self.assertEqual(self.event.local_start_time.strftime('%H:%M'), '15:45')

    @override_settings(RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=False)
    def test_result_does_not_bypass_schedule_switch(self):
        self.publish()
        self.assertIsNone(self.event.race_datetime)

    @override_settings(RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True,
                       RACE_DATA_SYNC_ENABLED_FIELDS=('off_time', 'local_start_time', 'timezone_name'))
    def test_time_manual_lock_is_preserved(self):
        from stable.services.japan_public_fields import fill_result_time
        with override_settings(RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=False):
            self.publish()
        self.event.manual_lock_flags = {'race_time': True}
        self.event.save()
        revision = self.event.projection_control.current_result_revision
        self.assertFalse(fill_result_time(event=self.event, observation=revision.primary_observation,
            revision=revision, now=workflow.NOW))
        self.assertIsNone(self.event.race_datetime)

    def test_existing_runner_status_manual_lock_is_preserved(self):
        for item in self.candidate.candidate_payload['items']:
            runner = models.RaceEventRunner.objects.create(event=self.event,
                horse_name=item['horse_name'], horse_number=item['horse_number'])
        models.RaceEventFieldAuthority.objects.create(event=self.event, subject_type='participant',
            subject_key='number:' + runner.horse_number, field_name='running_status', manual_lock=True)
        self.publish()
        runner.refresh_from_db()
        self.assertEqual(runner.running_status, 'declared')
        self.assertEqual(self.event.results.get(horse_number=runner.horse_number).running_status, 'finished')


    def seed_pound_runners(self, *, locked):
        for item in self.candidate.candidate_payload['items']:
            external_id = 'number:' + item['horse_number']
            models.RaceEventRunner.objects.create(event=self.event, external_runner_id=external_id,
                horse_name=item['horse_name'], horse_number=item['horse_number'], carried_weight='120',
                source_refs={'jra': external_id, 'field_units': {'carried_weight': 'lb'}},
                manual_lock_flags={'carried_weight': True} if locked else {})

    def test_result_preserves_existing_locked_pound_value_and_unit(self):
        self.seed_pound_runners(locked=True)
        self.publish()
        for runner in self.event.runners.all():
            self.assertEqual(runner.carried_weight, '120')
            self.assertEqual(runner.source_refs['field_units']['carried_weight'], 'lb')
            self.assertTrue(row_fields(runner)['weight'].text.startswith('120磅'))

    def test_racecard_preserves_locked_pound_value_and_unit(self):
        self.seed_pound_runners(locked=True)
        workflow.JraColdStartTests.test_card_and_schedule_use_bound_source_writer(self)
        for runner in self.event.runners.all():
            self.assertEqual(runner.carried_weight, '120')
            self.assertEqual(runner.source_refs['field_units']['carried_weight'], 'lb')

    def test_racecard_updates_unlocked_weight_and_unit_together(self):
        self.seed_pound_runners(locked=False)
        workflow.JraColdStartTests.test_card_and_schedule_use_bound_source_writer(self)
        for runner in self.event.runners.all():
            self.assertNotEqual(runner.carried_weight, '120')
            self.assertEqual(runner.source_refs['field_units']['carried_weight'], 'kg')

    def repair_fixture(self):
        import tempfile, json, hashlib
        from pathlib import Path
        from stable.management.commands.repair_japan_public_fields import projection_snapshot
        self.publish()
        self.event.results.update(popularity='', source_refs={})
        revision = self.event.projection_control.current_result_revision
        source = revision.primary_observation.source_identity
        for result in self.event.results.all():
            result.source_refs = {'revision_id': revision.pk, 'external_runner_id': 'number:' + result.horse_number}
            result.save()
        self.event.runners.update(running_status='declared')
        manifest = dict(schema_version=1, action='repair_japan_public_fields', items=[dict(
            event_id=self.event.pk, revision_id=revision.pk, snapshot_sha256=projection_snapshot(self.event))])
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'manifest.json'; path.write_text(json.dumps(manifest))
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_repair_dry_run_apply_and_idempotence_keep_revision(self):
        from stable.management.commands.repair_japan_public_fields import execute, projection_snapshot
        path, sha = self.repair_fixture()
        before = projection_snapshot(self.event)
        revision = self.event.projection_control.current_result_revision_id
        self.assertEqual(execute(path, sha, now=workflow.NOW)['action'], 'dry_run')
        self.event.refresh_from_db()
        self.assertEqual(projection_snapshot(self.event), before)
        self.assertEqual(execute(path, sha, apply=True, now=workflow.NOW)['action'], 'applied')
        self.assertTrue(self.event.results.exclude(popularity='').exists())
        self.assertFalse(self.event.runners.filter(running_status='declared').exists())
        self.assertEqual(execute(path, sha, apply=True, now=workflow.NOW)['action'], 'replay')
        self.assertEqual(self.event.projection_control.current_result_revision_id, revision)

    def test_repair_rejects_drift_and_rolls_back_partial_writes(self):
        from unittest.mock import patch
        from stable.management.commands.repair_japan_public_fields import execute, projection_snapshot
        path, sha = self.repair_fixture()
        before = projection_snapshot(self.event)
        with patch('stable.management.commands.repair_japan_public_fields.fill_result_time', side_effect=ValueError('last_step')):
            with self.assertRaisesMessage(ValueError, 'last_step'):
                execute(path, sha, apply=True, now=workflow.NOW)
        self.assertEqual(projection_snapshot(self.event), before)
        self.event.results.filter(pk=self.event.results.first().pk).update(popularity='9')
        with self.assertRaisesMessage(ValueError, 'projection_baseline_drift'):
            execute(path, sha, apply=True, now=workflow.NOW)

    def test_repair_reparses_fixed_official_page_and_rejects_changed_facts(self):
        import json, hashlib
        from stable.management.commands.repair_japan_public_fields import execute
        path, sha = self.repair_fixture()
        page = path.parent / 'result.html'; page.write_text(self.result)
        manifest = json.loads(path.read_text())
        manifest['items'][0]['result_page'] = dict(file=page.name, url=workflow.RESULT,
            sha256=hashlib.sha256(page.read_bytes()).hexdigest())
        path.write_text(json.dumps(manifest)); sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(execute(path, sha, now=workflow.NOW)['action'], 'dry_run')
        soup = BeautifulSoup(self.result, 'html.parser')
        soup.select_one('td.horse').string = '別の馬'
        page.write_text(str(soup))
        manifest['items'][0]['result_page']['sha256'] = hashlib.sha256(page.read_bytes()).hexdigest()
        path.write_text(json.dumps(manifest)); sha = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesMessage(ValueError, 'result_page_facts_drift'):
            execute(path, sha, apply=True, now=workflow.NOW)


class NarResultTimeTests(SimpleTestCase):
    def test_verified_linked_card_supplies_result_time(self):
        from unittest.mock import MagicMock, patch
        from stable.services.race_data_source_adapters import fetch_bound_observation, SourceRoute
        card='https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate=2026/09/01&k_raceNo=10&k_babaCode=10'
        result='https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?k_raceDate=2026%2F09%2F01&k_raceNo=10&k_babaCode=10'
        route=SourceRoute(dict(provider='nar',operator='nar',region='japan_nar',identity_namespace='nar-race-v1',
            allowed_hosts=['www.keiba.go.jp'],allowed_path_prefixes=['/KeibaWeb/TodayRaceInfo/'],
            venue_aliases={'nar:10':['盛岡']},timezone='Asia/Tokyo',parser_version='test'),'a'*64)
        event=MagicMock();event.source_identities.filter.return_value.first.return_value=None
        event.runners.exists.return_value=False
        pages={card:(real.ROOT/'nar-card.html').read_text(),result:(real.ROOT/'nar-result.html').read_text()}
        with patch('stable.services.race_source_identity.seed_evidence',return_value=None),patch(
            'stable.services.race_data_source_adapters.discover_source_url',return_value=card):
            value=fetch_bound_observation(event=event,route=route,now=real.NOW,fetcher=lambda url,**k:pages[url])
        self.assertEqual(value['off_time'], '2026-09-01T17:05:00+09:00')
        self.assertEqual(value['time_evidence']['url'], card)

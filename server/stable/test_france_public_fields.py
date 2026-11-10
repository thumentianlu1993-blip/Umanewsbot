"""法国公开字段缺口回归：真实离线来源，不访问第三方服务。"""
import json
import re
from pathlib import Path

from django.test import SimpleTestCase
from django.test import TestCase

ROOT = Path(__file__).parent / 'fixtures/france_automation'


class FranceTimeDisplayTests(SimpleTestCase):
    def test_geny_winner_time_requires_source_and_preserves_decimal_precision(self):
        from stable.services.race_information_display import row_fields
        url = 'https://www.geny.com/course/1681046-2026-09-03-parislongchamp-prix-d-arenberg/arrivee-rapports'
        for raw, expected in [("0'55\"10", '55.10秒'), ("4'07\"4", '4分7.4秒')]:
            self.assertEqual(row_fields(dict(finish_time=raw, source_refs={'primary': url}))['finish_time'].text, expected)
            self.assertEqual(row_fields(dict(finish_time=raw))['finish_time'].state, 'unknown')
        for raw in ["0'60\"10", "1000'01\"00", "0'00\"00", "4'07\"abc"]:
            self.assertEqual(row_fields(dict(finish_time=raw, source_refs={'primary': url}))['finish_time'].state, 'unknown')

    def test_confirmed_horse_history_uses_linked_result_time_source(self):
        from types import SimpleNamespace
        from stable.services.race_information_display import horse_record_fields
        linked = SimpleNamespace(is_confirmed=True, finish_time="4'07\"4", source_refs={
            'primary': 'https://www.geny.com/course/123-2026-11-02-nantes-prix-de-l-avenir/arrivee-rapports'})
        record = SimpleNamespace(_state=SimpleNamespace(fields_cache={'result': linked}))
        self.assertEqual(horse_record_fields(record)['finish_time'].text, '4分7.4秒')


class FranceBasicParserTests(SimpleTestCase):
    def test_zero_clock_is_not_a_midnight_start_even_with_timezone_proof(self):
        from bs4 import BeautifulSoup
        from stable.services.france_sources import parse_geny_observation
        from stable.services.race_data_source_adapters import SourceRoute
        from datetime import datetime,timezone
        page=BeautifulSoup((ROOT/'avenir-result.html').read_text(),'html.parser')
        meta=page.new_tag('meta',attrs={'name':'source-timezone','content':'Europe/Paris'});page.head.append(meta)
        for node in page.find_all(string=lambda text:text and re.fullmatch(r'\d{1,2}h\d{2}',text.strip())):
            node.replace_with('00h00')
        route=SourceRoute(dict(provider='geny',region='france',operator='geny',identity_namespace='geny-race-v1',
            parser_version='test',timezone='Europe/Paris',allowed_hosts=['www.geny.com'],allowed_path_prefixes=['/course/'],
            venue_aliases={'fr:nantes':['Nantes']}),'a'*64)
        value=parse_geny_observation(str(page),url='https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/arrivee-rapports',
            route=route,now=datetime(2026,11,9,tzinfo=timezone.utc),card_page=(ROOT/'avenir-card.html').read_text())
        self.assertEqual(value['off_time'],'')

    def test_geny_real_dom_basic_fields_have_bound_source_evidence(self):
        from datetime import datetime, timezone
        from stable.services.france_sources import parse_geny_observation
        from stable.services.race_data_source_adapters import SourceRoute
        route = SourceRoute(dict(provider='geny', region='france', operator='geny', identity_namespace='geny-race-v1',
            parser_version='test', timezone='Europe/Paris', allowed_hosts=['www.geny.com'], allowed_path_prefixes=['/course/'],
            venue_aliases={'fr:nantes': ['Nantes']}), 'a' * 64)
        base = 'https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/'
        value = parse_geny_observation((ROOT/'avenir-result.html').read_text(), url=base+'arrivee-rapports',
            route=route, now=datetime(2026,11,9,tzinfo=timezone.utc), card_page=(ROOT/'avenir-card.html').read_text())
        basic = value.get('france_basic_v1', {})
        self.assertEqual(basic.get('fields', {}).get('distance', {}).get('value'), '2400 m')
        self.assertEqual(basic['fields']['distance']['unit'], 'metre')
        self.assertEqual(basic['fields']['discipline']['value'], 'flat')
        self.assertEqual(basic['fields']['surface']['value'], 'turf')
        self.assertIn('Autres Que Pur-Sang', basic['fields']['eligibility']['value'])
        self.assertNotIn('Terrain', basic['fields']['eligibility']['value'])
        self.assertEqual(basic['source_url'], base+'arrivee-rapports')
        self.assertEqual(basic['raw_sha256'], value['raw_sha256'])

    def test_fg_complete_conditions_include_later_paragraphs_even_without_roster(self):
        from stable.services.france_sources import parse_france_galop_document
        docs = json.loads((ROOT/'future.json').read_text())
        for doc in [docs[0], docs[-1]]:
            value = parse_france_galop_document(doc)
            basic = value.get('france_basic_v1', {})
            expected = doc['text'][doc['text'].index('Pour '):doc['text'].index('Legal notice')].strip()
            self.assertEqual(basic.get('fields', {}).get('eligibility', {}).get('value'), expected)
            self.assertGreater(len(expected), 255)
            self.assertEqual(basic['fields']['discipline']['value'], 'flat')
            self.assertNotIn('surface', basic['fields'])  # AQPS不证明草地。
        fields = parse_france_galop_document(docs[0])['france_basic_v1']['fields']
        self.assertEqual(fields['distance']['value'], '2100 m')
        self.assertEqual(fields['eligibility']['minimum_age'], 3)
        self.assertTrue(fields['eligibility']['age_open_ended'])
        self.assertEqual(fields['eligibility']['sex_restriction'], 'female')
        # FG币种由已核实的官方programme合同补证，仍只取基础allocation。
        self.assertEqual(fields['prize']['value'], '73200.00')

    def test_fg_linebreaks_preserve_structured_age_and_raw_conditions(self):
        from stable.services.france_sources import parse_france_galop_document
        docs=json.loads((ROOT/'future.json').read_text())
        for title, low, high in [('CHLORIS',4,5),('GUILLEDINES',3,3),('JACQUES DE VIENNE',3,3)]:
            doc=dict(next(d for d in docs if title in d['title']))
            doc['text']=re.sub(r'de (?=\d)', 'de\n', doc['text'])
            field=parse_france_galop_document(doc)['france_basic_v1']['fields']['eligibility']
            self.assertEqual((field['minimum_age'],field['maximum_age']),(low,high),title)
            self.assertIn('\n',field['value'])

    def test_fg_official_base_allocation_uses_eur_contract_not_owner_premium(self):
        from stable.services.france_sources import parse_france_galop_document
        docs=json.loads((ROOT/'future.json').read_text())
        for doc in docs:
            with self.subTest(title=doc['title']):
                value=parse_france_galop_document(doc)['france_basic_v1']['fields']
                self.assertIn('prize',value)
                self.assertEqual(value['prize']['currency'],'EUR')
                self.assertNotIn('Prime Propriétaire',value['prize']['raw'])
        miesque=next(d for d in docs if 'MIESQUE' in d['title'])
        self.assertEqual(parse_france_galop_document(miesque)['france_basic_v1']['fields']['prize']['value'],'73200.00')

    def test_all_59_historical_headers_keep_units_prize_conditions_and_going(self):
        from stable.services.france_basic_fields import parse_basic
        data = json.loads((ROOT/'historical.json').read_text())
        for doc in data['results']:
            fields = parse_basic(doc, identity={})['fields']
            self.assertEqual(set(fields) - {'layout'}, {'distance', 'discipline', 'surface', 'prize', 'eligibility', 'going'}, doc['url'])
            self.assertEqual(fields['prize']['currency'], 'EUR')
            self.assertNotIn('Paris PMU', fields['going']['raw'])


class FranceBasicDisplayTests(SimpleTestCase):
    def test_normalized_flat_prize_direction_and_france_going_are_public(self):
        from stable.services.race_information_display import event_fields
        event = dict(country_region='france', normalized_race_type='flat', surface='turf', course_layout_text='Droite',
            prize_amount='73200.00', prize_currency='EUR', going_text='Très souple',
            source_refs={'france_basic_v1': {'version': 1, 'fields': {
                'layout': {'value': 'Droite'}, 'going': {'value': 'Très souple', 'penetrometer': '3.8'}}}})
        fields = event_fields(event)
        self.assertEqual(fields['race_type'].text, '平地')
        self.assertEqual(fields['prize'].text, '73200欧元')
        self.assertEqual(fields['layout'].text, '右转')
        self.assertIn('Très souple', fields['going'].text)
        self.assertIn('3.8', fields['going'].text)
        self.assertNotEqual(fields['going'].state, 'unknown')

    def test_other_regions_keep_existing_type_display_contract(self):
        from stable.services.race_information_display import event_fields
        self.assertEqual(event_fields({'country_region':'japan','normalized_race_type':'flat'})['race_type'].state,'missing')

    def test_distance_evidence_does_not_follow_an_unrelated_value_change(self):
        from stable.services.race_information_display import event_fields
        event={'country_region':'france','distance_text':'2100m','source_refs':{
            'field_units':{'distance_text':'metre'},'france_basic_v1':{'version':1,'fields':{
                'distance':{'value':'2100 m','unit':'metre','raw':'2.100 mètres'}}}}}
        self.assertEqual(event_fields(event)['distance'].text,'2100米')
        event['distance_text']='2500m'
        self.assertEqual(event_fields(event)['distance'].text,'待核实')

    def test_page_shows_new_fields_and_full_escaped_conditions(self):
        from types import SimpleNamespace
        from django.template.loader import render_to_string
        from stable.services.race_information_display import event_fields
        event = SimpleNamespace(pk=1, country_region='france', prize_amount='73200.00', prize_currency='EUR', eligibility_text='Pour '+('条件\n'*120)+'<script>bad</script>')
        event.public_display = event_fields(event)
        from django.test import override_settings
        with override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=True):
            html = render_to_string('stable/public/race_detail.html', dict(event=event, race_information_enabled=True))
        for label in ['总奖金', '73200欧元', '完整参赛条件', '&lt;script&gt;bad&lt;/script&gt;']:
            self.assertIn(label, html)
        self.assertNotIn('<script>bad</script>', html)


class FrancePrizeSchemaTests(TestCase):
    def test_prize_and_long_conditions_round_trip(self):
        from stable.models import RaceEvent
        fields = {f.name:f for f in RaceEvent._meta.fields}
        self.assertIn('prize_amount', fields)
        self.assertIn('prize_currency', fields)
        self.assertIsNone(fields['eligibility_text'].max_length)
        event = RaceEvent.objects.create(year=2026, original_name='Prix test', country_region='france',
            prize_amount='73200.00', prize_currency='EUR', eligibility_text='Conditions '*100)
        event.refresh_from_db()
        self.assertEqual(str(event.prize_amount), '73200.00')
        self.assertEqual(len(event.eligibility_text), 1100)


from django.test import override_settings
from stable import test_france_automation as france_tests
NOW = france_tests.NOW


@override_settings(**{**france_tests.FrancePreviewWorkflowTests._overridden_settings,
    'RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED': True,
    'RACE_DATA_SYNC_ENABLED_FIELDS': ('off_time', 'local_start_time', 'timezone_name', 'participants.horse_name')})
class FranceImmediateTimeTests(TestCase):
    setUp = france_tests.FrancePreviewWorkflowTests.setUp

    def complete_time(self, *, now=NOW, off='2026-11-20T16:25:00+01:00', stage='not_published', claim=None, observed=None):
        from types import SimpleNamespace
        from stable.services import race_pre_race as pre
        from stable.services.france_pre_race import complete
        claim = claim or pre.claim_pre_race(event_id=self.event.pk, source='france_pre_race_v1', now=now)
        payload = dict(local_date='2026-11-20', venue='Chantilly', race_name='PRIX MIESQUE',
            stage=stage, source_stage=stage, schedule=[], off_time=off,
            items=[] if stage=='not_published' else [dict(horse_name='TEST', running_status='declared')])
        return complete(claim, payload=payload, url='https://www.france-galop.com/fr/course/detail/2026/P/test',
            page=SimpleNamespace(observed_at=observed or now, raw_sha256='a'*64), route=self.route, now=now)

    def test_time_is_public_in_same_completion_without_any_roster(self):
        from stable.services.race_information_display import event_fields
        self.assertTrue(self.complete_time())
        self.event.refresh_from_db()
        self.assertEqual(event_fields(self.event)['time'].text, '23:25（北京时间）')
        self.assertEqual(str(self.event.local_start_time), '16:25:00')
        self.assertFalse(self.event.runners.exists())
        self.assertNotIn('pre_race_handoff', self.event.source_refs)
        self.assertEqual(self.event.status, 'scheduled')

    def test_same_roster_time_correction_and_empty_source(self):
        from datetime import timedelta
        self.assertTrue(self.complete_time(stage='registration'))
        self.assertTrue(self.complete_time(now=NOW+timedelta(hours=4), stage='registration', off='2026-11-20T16:35:00+01:00'))
        self.event.refresh_from_db()
        self.assertEqual(str(self.event.local_start_time), '16:35:00')
        self.assertEqual(self.event.data_candidates.filter(module='runners').count(), 2)
        self.assertTrue(self.complete_time(now=NOW+timedelta(hours=8), off=''))
        self.event.refresh_from_db()
        self.assertEqual(str(self.event.local_start_time), '16:35:00')

    def test_lower_roster_stage_does_not_block_newer_time(self):
        from datetime import timedelta
        self.assertTrue(self.complete_time(stage='declared'))
        self.assertTrue(self.complete_time(now=NOW+timedelta(hours=4),stage='registration',off='2026-11-20T16:45:00+01:00'))
        self.event.refresh_from_db()
        self.assertEqual(str(self.event.local_start_time),'16:45:00')
        latest=self.event.data_candidates.filter(module='runners').latest('id')
        self.assertEqual(latest.candidate_payload['stage'],'declared')

    def test_guard_drift_and_partial_field_admission_do_not_write(self):
        from stable import models
        from stable.services import race_pre_race as pre
        claim = pre.claim_pre_race(event_id=self.event.pk, source='france_pre_race_v1', now=NOW)
        control = models.RaceEventProjectionControl.objects.create(event=self.event, write_owner='unmanaged')
        self.assertFalse(self.complete_time(claim=claim))
        self.event.refresh_from_db()
        self.assertIsNone(self.event.race_datetime)
        control.delete()
        from datetime import timedelta
        with override_settings(RACE_DATA_SYNC_ENABLED_FIELDS=('off_time',)):
            self.assertTrue(self.complete_time(now=NOW+timedelta(hours=4)))
        self.event.refresh_from_db()
        self.assertIsNone(self.event.race_datetime)

    def test_same_value_new_confirmation_blocks_intermediate_old_correction(self):
        from datetime import timedelta
        self.assertTrue(self.complete_time())
        self.assertTrue(self.complete_time(now=NOW+timedelta(hours=4)))
        self.assertTrue(self.complete_time(now=NOW+timedelta(hours=8), observed=NOW+timedelta(hours=2), off='2026-11-20T16:45:00+01:00'))
        self.event.refresh_from_db()
        self.assertEqual(str(self.event.local_start_time),'16:25:00')


_BASIC_ADMISSION = tuple('france_basic.'+field for field in ('distance','discipline','surface','layout','going','prize','eligibility'))
_FORMAL_FIELDS = ('off_time', 'local_start_time', 'timezone_name', 'status',
    *(f'participants.{key}' for key in ('horse_name','number','draw','jockey_name','trainer_name','carried_weight','status','odds','popularity')))


@override_settings(**{**france_tests.FranceResultWorkflowTests._overridden_settings,
    'RACE_DATA_SYNC_ENABLED_FIELDS': (*_FORMAL_FIELDS, *_BASIC_ADMISSION)})
class FranceBasicWorkflowTests(TestCase):
    setUp = france_tests.FranceResultWorkflowTests.setUp
    fetch = france_tests.FranceResultWorkflowTests.fetch

    def run_result(self):
        from stable.services.race_data_source_adapters import fetch_bound_observation, run_multisource_claim
        from stable.services.race_data_sync_enrollment import attach_multisource_observation
        from stable.services.race_data_sync_control import claim_multisource_events
        value = fetch_bound_observation(event=self.event, route=self.policy.routes[0], now=NOW, fetcher=self.fetch)
        self.assertEqual(attach_multisource_observation(value, policy=self.policy, now=NOW).action, 'acquired')
        claims = claim_multisource_events(event_ids=[self.event.pk], now=NOW, historical=True)
        self.assertEqual(len(claims), 1)
        result = run_multisource_claim(claim=claims[0], now=NOW, fetcher=self.fetch)
        self.assertTrue(result['processed'], result)
        self.event.refresh_from_db()

    def test_result_applies_source_basic_fields_with_audited_units(self):
        from stable.services.race_information_display import event_fields
        self.run_result()
        self.assertEqual(self.event.distance_text, '2400 m')
        self.assertEqual(str(self.event.prize_amount), '33900.00')
        self.assertEqual(self.event.prize_currency, 'EUR')
        self.assertEqual(self.event.normalized_race_type, 'flat')
        self.assertEqual(self.event.surface, 'turf')
        self.assertEqual(self.event.minimum_age, 3)
        self.assertEqual(self.event.maximum_age, 3)
        self.assertIn('Autres Que Pur-Sang', self.event.eligibility_text)
        self.assertEqual(event_fields(self.event)['distance'].text, '2400米')
        self.assertTrue(self.event.field_changes.filter(field_name='prize_amount', applied=True).exists())

    def test_closed_basic_admission_preserves_formal_results(self):
        with override_settings(RACE_DATA_SYNC_ENABLED_FIELDS=_FORMAL_FIELDS):
            self.run_result()
        self.assertIsNone(self.event.prize_amount)
        self.assertEqual(self.event.results.count(), 6)

    def test_existing_card_gaps_use_allocated_card_weight_not_result_actual(self):
        from stable import models
        from stable.services.france_sources import parse_geny_card, document_from_html
        card = parse_geny_card(document_from_html((ROOT/'avenir-card.html').read_text(), self.base+'partants-pronostics'))
        ids = []
        for row in card['roster']:
            runner = models.RaceEventRunner.objects.create(event=self.event, horse_name=row['horse_name'],
                horse_number=row['number'], external_runner_id=row['external_runner_id'],
                source_refs={'geny':row['external_runner_id']})
            ids.append(runner.pk)
        self.run_result()
        self.assertEqual(list(self.event.runners.order_by('pk').values_list('pk',flat=True)), ids)
        for row in card['roster']:
            runner = self.event.runners.get(horse_number=row['number'])
            self.assertEqual(runner.carried_weight, row['carried_weight'])
            self.assertEqual(runner.trainer_name, row['trainer_name'])
            self.assertEqual(runner.odds_value, row['odds_value'])
        self.assertEqual(self.event.runners.get(horse_number='2').carried_weight, '60.5 kg')
        self.assertEqual(self.event.results.get(horse_number='2').carried_weight, '60.5 kg')

    def test_basic_changed_evidence_is_not_deduplicated_and_mismatch_is_rejected(self):
        import copy
        from stable.services.race_events import record_race_result_observation
        from stable.services.france_basic_fields import basic_sha
        self.run_result()
        from stable import models
        observation = models.RaceResultObservation.objects.filter(source_identity__event=self.event).first()
        payload=copy.deepcopy(observation.normalized_payload);provenance=copy.deepcopy(observation.field_provenance)
        provenance['france_basic_v1']['fields']['prize'].update(value='44000.00',raw='44 000 €')
        kwargs=dict(source_identity_id=observation.source_identity_id,observed_at=NOW,source_updated_at=None,
            parser_version=observation.parser_version,raw_sha256=observation.raw_sha256,result_phase=observation.result_phase,
            normalized_payload=payload,field_provenance=provenance,parse_warnings=[],permission_classification=observation.permission_classification)
        self.assertIsNone(record_race_result_observation(**kwargs).observation)
        payload['france_basic_sha256']=basic_sha(provenance['france_basic_v1'])
        recorded=record_race_result_observation(**kwargs)
        self.assertTrue(recorded.created)
        self.assertNotEqual(recorded.observation.pk,observation.pk)
        observation.refresh_from_db()
        self.assertEqual(observation.field_provenance['france_basic_v1']['fields']['prize']['value'],'33900.00')

    def test_unchanged_results_still_refresh_basic_fields(self):
        import copy
        from datetime import timedelta
        from unittest.mock import patch
        from stable import models
        from stable.services.france_basic_fields import basic_sha
        from stable.services.race_events import record_race_result_observation
        from stable.services.race_data_sync_results import apply_data_sync_result_observation
        from stable.services.race_data_sync_control import claim_multisource_events
        self.run_result()
        observation=models.RaceResultObservation.objects.filter(source_identity__event=self.event,result_phase='official').first()
        before=list(self.event.results.order_by('pk').values())
        later=NOW+timedelta(hours=1)
        payload=copy.deepcopy(observation.normalized_payload);provenance=copy.deepcopy(observation.field_provenance)
        provenance['france_basic_v1']['fields']['prize'].update(value='44000.00',raw='44 000 €')
        provenance['france_basic_v1']['observed_at']=later.isoformat()
        payload['france_basic_sha256']=basic_sha(provenance['france_basic_v1'])
        recorded=record_race_result_observation(source_identity_id=observation.source_identity_id,observed_at=later,
            source_updated_at=None,parser_version=observation.parser_version,raw_sha256='d'*64,
            result_phase=observation.result_phase,normalized_payload=payload,field_provenance=provenance,
            parse_warnings=[],permission_classification=observation.permission_classification)
        self.assertTrue(recorded.created)
        with patch('django.utils.timezone.now',return_value=later):
            claim=claim_multisource_events(event_ids=[self.event.pk],now=later,historical=True)[0]
            result=apply_data_sync_result_observation(observation_id=recorded.observation.pk,expected_event_id=self.event.pk,
                now=later,project_current=True,correction_apply_enabled=True,claim_guard=claim)
        self.assertEqual(result.reason_code,'same_event_result_evidence')
        self.event.refresh_from_db();self.assertEqual(str(self.event.prize_amount),'44000.00')
        self.assertEqual(list(self.event.results.order_by('pk').values()),before)

    def test_same_results_fill_new_card_evidence_without_changing_results(self):
        import copy
        from datetime import timedelta
        from unittest.mock import patch
        from django.conf import settings
        from stable import models
        from stable.services.france_sources import parse_geny_card, document_from_html
        from stable.services.race_events import record_race_result_observation
        from stable.services.race_data_sync_results import apply_data_sync_result_observation
        from stable.services.race_data_sync_control import claim_multisource_events
        card=parse_geny_card(document_from_html((ROOT/'avenir-card.html').read_text(),self.base+'partants-pronostics'))
        for row in card['roster']:
            models.RaceEventRunner.objects.create(event=self.event,horse_name=row['horse_name'],horse_number=row['number'],
                external_runner_id=row['external_runner_id'],source_refs={'geny':row['external_runner_id']})
        with override_settings(RACE_DATA_SYNC_ENABLED_FIELDS=tuple(f for f in settings.RACE_DATA_SYNC_ENABLED_FIELDS if f!='participants.odds')):
            self.run_result()
        self.assertEqual(set(self.event.runners.values_list('odds_value',flat=True)),{''})
        # 同一重放也须尊重行级手工锁。
        locked=self.event.runners.order_by('pk').first();locked.manual_lock_flags={'odds_value':True};locked.save()
        before=list(self.event.results.order_by('pk').values())
        old=models.RaceResultObservation.objects.filter(source_identity__event=self.event,result_phase='official').first()
        payload=copy.deepcopy(old.normalized_payload);later=NOW+timedelta(hours=1)
        for row in payload['participants']:
            row['field_provenance']['card_fields'].update(observed_at=later.isoformat(),odds_value='5.5')
        recorded=record_race_result_observation(source_identity_id=old.source_identity_id,observed_at=later,
            source_updated_at=None,parser_version=old.parser_version,raw_sha256='d'*64,result_phase=old.result_phase,
            normalized_payload=payload,field_provenance=copy.deepcopy(old.field_provenance),parse_warnings=[],permission_classification=old.permission_classification)
        self.assertTrue(recorded.created)
        with patch('django.utils.timezone.now',return_value=later):
            claim=claim_multisource_events(event_ids=[self.event.pk],now=later,historical=True)[0]
            result=apply_data_sync_result_observation(observation_id=recorded.observation.pk,expected_event_id=self.event.pk,
                now=later,project_current=True,correction_apply_enabled=True,claim_guard=claim)
        self.assertEqual(result.reason_code,'same_event_result_evidence')
        self.assertEqual(set(self.event.runners.exclude(pk=locked.pk).values_list('odds_value',flat=True)),{'5.5'})
        locked.refresh_from_db();self.assertEqual(locked.odds_value,'')
        self.assertEqual(list(self.event.results.order_by('pk').values()),before)

    def test_repair_survives_finished_claim_generation_but_blocks_active_claim(self):
        import copy
        from datetime import timedelta
        from django.db.models import F
        from unittest.mock import patch
        from stable import models
        from stable.services.france_field_repair import execute_repair
        self.run_result()
        old=models.RaceResultObservation.objects.filter(source_identity__event=self.event,result_phase='official').first()
        basic=copy.deepcopy(old.field_provenance['france_basic_v1'])
        basic['fields']['prize'].update(value='44000.00',raw='44 000 €')
        basic['observed_at']=(NOW+timedelta(hours=1)).isoformat()
        repair_now=NOW+timedelta(hours=2)
        packet={'basic':basic};item=dict(event_id=self.event.pk,source_identity_id=old.source_identity_id,groups=['prize'],source={})
        manifest=dict(schema_version=1,action='france_field_repair',policy_digest=self.policy.digest,
            scope=dict(country_region='france',date_from='2026-09-01',date_to='2026-12-31',event_ids=[self.event.pk]),items=[item])
        tracking=models.RaceEventLiveTracking.objects.filter(event=self.event)
        with patch('stable.services.france_field_repair.read_bound',return_value=packet):
            plan=execute_repair(None,manifest,'c'*64,apply=False,restore=False,now=repair_now)
            item.update(before_sha256=plan['events'][0]['before_sha256'],expected_values=plan['events'][0]['after_values'])
            tracking.update(claim_generation=F('claim_generation')+1,active_attempt_token='active',claim_expires_at=repair_now+timedelta(minutes=5))
            with self.assertRaisesRegex(ValueError,'formal_claim_active'):
                execute_repair(None,manifest,'c'*64,apply=True,restore=False,now=repair_now)
            tracking.update(active_attempt_token='',claim_expires_at=None)
            self.assertEqual(execute_repair(None,manifest,'c'*64,apply=True,restore=False,now=repair_now)['action'],'applied')
            tracking.update(claim_generation=F('claim_generation')+1)
            self.assertEqual(execute_repair(None,manifest,'c'*64,apply=True,restore=True,now=repair_now)['action'],'restored')
        self.event.refresh_from_db();self.assertEqual(str(self.event.prize_amount),'33900.00')

    def test_legacy_runner_authority_lock_blocks_restore(self):
        import copy
        from unittest.mock import patch
        from stable import models
        from stable.services.france_field_repair import execute_repair
        self.run_result()
        observation=models.RaceResultObservation.objects.filter(source_identity__event=self.event,result_phase='official').first()
        row=copy.deepcopy(observation.normalized_payload['participants'][0])
        runner=self.event.runners.get(horse_number=row['number'])
        runner.external_runner_id='hrs_legacy';runner.trainer_name='';runner.carried_weight='';runner.odds_value='';runner.save()
        packet={'basic':observation.field_provenance['france_basic_v1'],'card_rows':[row]}
        item=dict(event_id=self.event.pk,source_identity_id=observation.source_identity_id,groups=[],observation_id=observation.pk,
            runners=[{'runner_id':runner.pk,'external_runner_id':row['external_runner_id']}],source={})
        manifest=dict(schema_version=1,action='france_field_repair',policy_digest=self.policy.digest,
            scope=dict(country_region='france',date_from='2026-09-01',date_to='2026-12-31',event_ids=[self.event.pk]),items=[item])
        with patch('stable.services.france_field_repair.read_bound',return_value=packet):
            plan=execute_repair(None,manifest,'d'*64,apply=False,restore=False,now=NOW)
            item.update(before_sha256=plan['events'][0]['before_sha256'],expected_values=plan['events'][0]['after_values'])
            execute_repair(None,manifest,'d'*64,apply=True,restore=False,now=NOW)
            models.RaceEventFieldAuthority.objects.create(event=self.event,subject_type='participant',subject_key='hrs_legacy',
                field_name='trainer_name',manual_lock=True,source_key='the_racing_api',source_class='licensed_api')
            with self.assertRaisesRegex(ValueError,'restore_after_image_drift'):
                execute_repair(None,manifest,'d'*64,apply=True,restore=True,now=NOW)
        runner.refresh_from_db();self.assertNotEqual(runner.trainer_name,'')

    @override_settings(RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True)
    def test_historical_time_restore_compares_instants_after_database_reload(self):
        import copy
        from unittest.mock import patch
        from stable import models
        from stable.services.france_field_repair import execute_repair, TIME_FIELDS
        self.run_result()
        observation=models.RaceResultObservation.objects.filter(source_identity__event=self.event,result_phase='official').first()
        self.event.race_datetime=None;self.event.local_start_time=None;self.event.save()
        self.event.field_authorities.filter(subject_type='event',field_name__in=TIME_FIELDS).delete()
        basic=copy.deepcopy(observation.field_provenance['france_basic_v1'])
        packet={'basic':basic,'off_time':'2026-11-02T15:45:00+01:00',
            'time_evidence':{'source_timezone':'Europe/Paris','kind':'scheduled_start','raw_sha256':basic['raw_sha256']}}
        item=dict(event_id=self.event.pk,source_identity_id=observation.source_identity_id,groups=[],time=True,source={})
        manifest=dict(schema_version=1,action='france_field_repair',policy_digest=self.policy.digest,
            scope=dict(country_region='france',date_from='2026-09-01',date_to='2026-12-31',event_ids=[self.event.pk]),items=[item])
        with patch('stable.services.france_field_repair.read_bound',return_value=packet):
            plan=execute_repair(None,manifest,'e'*64,apply=False,restore=False,now=NOW)
            item.update(before_sha256=plan['events'][0]['before_sha256'],expected_values=plan['events'][0]['after_values'])
            execute_repair(None,manifest,'e'*64,apply=True,restore=False,now=NOW)
            self.event.refresh_from_db();self.assertEqual(self.event.race_datetime.hour,14)
            self.assertEqual(execute_repair(None,manifest,'e'*64,apply=True,restore=True,now=NOW)['action'],'restored')
        self.event.refresh_from_db();self.assertIsNone(self.event.race_datetime)
        self.assertIsNone(self.event.local_start_time);self.assertEqual(self.event.status,'finished')

    def test_field_repair_manifest_dry_run_apply_restore_is_atomic_and_idempotent(self):
        import copy, tempfile, hashlib
        from datetime import timedelta
        from stable.services.france_release import execute
        from stable import models
        self.run_result()
        observation=models.RaceResultObservation.objects.filter(source_identity__event=self.event).first()
        basic=copy.deepcopy(observation.field_provenance['france_basic_v1'])
        basic['observed_at']=(NOW+timedelta(hours=1)).isoformat()
        basic['fields']['prize'].update(value='44000.00',raw='44 000 €')
        original_status=self.event.status
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact=json.dumps({'basic':basic},ensure_ascii=False).encode();(root/'source.json').write_bytes(artifact)
            item=dict(event_id=self.event.pk,source_identity_id=observation.source_identity_id,groups=['prize'],
                source={'file':'source.json','sha256':hashlib.sha256(artifact).hexdigest()})
            manifest=dict(schema_version=1,action='france_field_repair',policy_digest=self.policy.digest,
                scope=dict(country_region='france',date_from='2026-09-01',date_to='2026-12-31',event_ids=[self.event.pk]),items=[item])
            def save():
                data=json.dumps(manifest,ensure_ascii=False).encode();(root/'manifest.json').write_bytes(data)
                return hashlib.sha256(data).hexdigest()
            now=NOW+timedelta(hours=2)
            plan=execute(root/'manifest.json',save(),now=now)
            self.event.refresh_from_db();self.assertEqual(str(self.event.prize_amount),'33900.00')
            item.update(before_sha256=plan['events'][0]['before_sha256'],expected_values=plan['events'][0]['after_values'])
            sha=save()
            self.assertEqual(execute(root/'manifest.json',sha,now=now,apply=True)['action'],'applied')
            self.event.refresh_from_db();self.assertEqual(str(self.event.prize_amount),'44000.00')
            self.assertEqual(self.event.status,original_status)
            self.assertEqual(execute(root/'manifest.json',sha,now=now,apply=True)['action'],'replay')
            from django.db import transaction
            from unittest.mock import patch
            # 后续同值补证也阻断恢复；不是仅比较44000这个业务值。
            with transaction.atomic():
                authority=self.event.field_authorities.get(subject_type='event',field_name='prize_amount')
                authority.observed_at=now+timedelta(hours=1);authority.save()
                with self.assertRaisesRegex(ValueError,'restore_after_image_drift'):
                    execute(root/'manifest.json',sha,now=now,apply=True,restore=True)
                transaction.set_rollback(True)
            with patch('stable.models.OperationLog.objects.create',side_effect=RuntimeError('restore_tail_failure')):
                with self.assertRaisesRegex(RuntimeError,'restore_tail_failure'):
                    execute(root/'manifest.json',sha,now=now,apply=True,restore=True)
            self.event.refresh_from_db();self.assertEqual(str(self.event.prize_amount),'44000.00')
            self.assertEqual(execute(root/'manifest.json',sha,now=now,apply=True,restore=True)['action'],'restored')
            self.event.refresh_from_db();self.assertEqual(str(self.event.prize_amount),'33900.00')
            self.assertEqual(execute(root/'manifest.json',sha,now=now,apply=True,restore=True)['action'],'restore_replay')

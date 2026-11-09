"""法国真实来源语义回归；所有来源输入离线。"""
import copy
import json
from pathlib import Path
from django.test import SimpleTestCase

ROOT = Path(__file__).parent / 'fixtures/france_automation'


class FranceSourceTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data = json.loads((ROOT / 'historical.json').read_text())

    def result(self, i=0):
        from stable.services.france_sources import parse_geny_result
        result = self.data['results'][i]
        card = next(c for c in self.data['cards'] if c['url'].rsplit('/',1)[0] == result['url'].rsplit('/',1)[0])
        return parse_geny_result(result, card)

    def test_real_dom_to_result_observation(self):
        from datetime import datetime,timezone
        from stable.services.france_sources import parse_geny_observation
        from stable.services.race_data_source_adapters import SourceRoute
        route=SourceRoute(dict(provider='geny',region='france',operator='geny',identity_namespace='geny-race-v1',
            parser_version='test',timezone='Europe/Paris',allowed_hosts=['www.geny.com'],allowed_path_prefixes=['/course/'],
            venue_aliases={'fr:nantes':['Nantes']}),'a'*64)
        base='https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/'
        value=parse_geny_observation((ROOT/'avenir-result.html').read_text(),url=base+'arrivee-rapports',route=route,
            now=datetime(2026,11,9,tzinfo=timezone.utc),card_page=(ROOT/'avenir-card.html').read_text())
        self.assertEqual(value['external_race_id'],'1695527')
        self.assertEqual(value['raw_names'],["Prix de l'Avenir"])
        self.assertEqual(value['venue_key'],'fr:nantes')
        self.assertEqual(len(value['roster']),6)
        self.assertTrue(value['roster_complete'])

    def test_geny_daily_discovery_is_bound_to_day_and_course(self):
        from types import SimpleNamespace
        from stable.services.race_data_source_adapters import SourceRoute,discover_source_url
        event=SimpleNamespace(original_name="Prix de l'Avenir",chinese_name='',local_date=date(2027,11,2),racecourse='Nantes',source_refs={})
        route=SourceRoute(dict(provider='geny',allowed_hosts=['www.geny.com'],allowed_path_prefixes=['/programme/','/course/'],
            venue_aliases={'fr:nantes':['Nantes']}),'a'*64)
        links=['/course/123-2027-11-02-nantes-prix-de-l-avenir/partants-pronostics',
            '/course/124-2026-11-02-nantes-prix-de-l-avenir/partants-pronostics',
            '/course/125-2027-11-02-chantilly-prix-de-l-avenir/partants-pronostics']
        def fetch(url,**kw):
            self.assertEqual(url,'https://www.geny.com/programme/2027-11-02')
            return ''.join('<a href="'+s+'">'+s+'</a>' for s in links)
        self.assertEqual(discover_source_url(event=event,route=route,now=NOW,fetcher=fetch),'https://www.geny.com'+links[0])

    def test_formal_card_takes_over_early_entries(self):
        from types import SimpleNamespace
        from stable.services.race_data_source_adapters import SourceRoute
        from stable.services.france_pre_race import fetch_france_pre_race
        base='https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/'
        route=SourceRoute(dict(provider='geny',region='france',operator='geny',identity_namespace='geny-race-v1',
            parser_version='test',timezone='Europe/Paris',allowed_hosts=['www.geny.com'],allowed_path_prefixes=['/course/','/programme/'],
            venue_aliases={'fr:nantes':['Nantes']},valid_from='2026-01-01T00:00:00Z',valid_until='2028-01-01T00:00:00Z'),'a'*64)
        event=SimpleNamespace(original_name="Prix de l'Avenir",chinese_name='',local_date=date(2026,11,2),racecourse='Nantes',source_refs={'primary':base+'partants-pronostics'})
        def fetch(url,**kw):
            self.assertEqual(url,base+'partants-pronostics')
            return (ROOT/'avenir-card.html').read_text()
        url,page,payload,used_route=fetch_france_pre_race(event=event,route=None,now=NOW-timedelta(days=8),fetcher=fetch,policy=SimpleNamespace(routes=[route]))
        self.assertEqual(used_route.provider,'geny')
        self.assertEqual(payload['stage'],'numbered')
        self.assertEqual(len(payload['items']),6)
        self.assertEqual(payload['items'][0]['source_refs']['odds_source'],'Genybet')

    def test_all_historical_cards_reconcile_including_nonrunners(self):
        rows = [row for i in range(59) for row in self.result(i)['roster']]
        self.assertEqual(len(rows),511)
        from collections import Counter
        counts=Counter(r['status'] for r in rows)
        self.assertEqual(counts,dict(finished=486,non_runner=2,fell=9,pulled_up=11,unseated_rider=3))
        self.assertTrue(all(r['carried_weight'].endswith(' kg') for r in rows))

    def test_missing_result_is_not_silently_nonrunner(self):
        from stable.services.france_sources import parse_geny_result
        source=copy.deepcopy(self.data['results'][0]); source['rows'].pop()
        card=next(c for c in self.data['cards'] if c['url'].rsplit('/',1)[0]==source['url'].rsplit('/',1)[0])
        with self.assertRaisesRegex(ValueError,'missing_result'):parse_geny_result(source,card)

    def test_truncated_both_tables_rejected_by_announced_count(self):
        from stable.services.france_sources import parse_geny_result
        source=copy.deepcopy(self.data['results'][0])
        card=copy.deepcopy(next(c for c in self.data['cards'] if c['url'].rsplit('/',1)[0]==source['url'].rsplit('/',1)[0]))
        missing=source['rows'].pop()['leaves'][0].rstrip('.')
        card['rows']=[r for r in card['rows'] if r[0]!=missing]
        with self.assertRaisesRegex(ValueError,'count'):parse_geny_result(source,card)

    def test_all_historical_statuses_and_margins_survive_writer_contract(self):
        from stable.services.race_data_sync_results import _normalize_result_rows
        from stable.services.race_information_display import row_fields
        for i in range(59):
            value=self.result(i)
            rows=_normalize_result_rows(dict(external_race_id=value['external_race_id'],off_time='',region='france',
                course='fixture',race_name='fixture',race_status='complete',participants=value['roster']))
            for row in rows:
                if row['margin']:
                    shown=row_fields(dict(margin=row['margin'],source_refs={'field_units':{'margin':'length'}}))['margin']
                    self.assertNotEqual(shown.state,'unknown',row['margin'])
                    self.assertNotEqual(shown.text,'待核实',row['margin'])

    def test_unknown_status_and_wrong_link_are_rejected(self):
        from stable.services.france_sources import parse_geny_result
        source=copy.deepcopy(self.data['results'][0])
        card=next(c for c in self.data['cards'] if c['url'].rsplit('/',1)[0]==source['url'].rsplit('/',1)[0])
        source['rows'][0]['rank']=''
        with self.assertRaisesRegex(ValueError,'unknown_status'):parse_geny_result(source,card)
        with self.assertRaisesRegex(ValueError,'identity'):parse_geny_result(source,self.data['cards'][-1])

    def test_original_weight_and_separate_odds_and_margin(self):
        rows=sorted(self.result()['roster'],key=lambda r:r['reported_finish_position'])
        self.assertEqual(rows[0]['carried_weight'],'55.5 kg')
        self.assertEqual(rows[0]['finish_time'],'0\'55"10')
        self.assertEqual(rows[1]['field_provenance']['margin_relation'],'previous_finisher')
        self.assertEqual(rows[0]['field_provenance']['odds_quotes'],{'PMU':'2.1','Genybet':'2.3'})
        self.assertEqual(rows[0]['odds_value'],'2.3')

    def test_public_weights_quotes_and_previous_margin_are_explicit(self):
        from django.template.loader import render_to_string
        from types import SimpleNamespace
        row=SimpleNamespace(horse_name='TEST',display_horse_name='TEST',carried_weight='68 kg',
            source_refs={'margin_basis':'previous_finisher','allocated_weight':'70 kg','adjusted_weight':'68 kg',
                'odds_source':'Genybet','odds_observed_at':'2026-11-09T00:00:00+00:00'},odds_value='2.3')
        html=render_to_string('stable/public/race_detail.html',dict(event=SimpleNamespace(pk=1),results=[row],runners=[row]))
        for text in ('差距（距前马）','分配 70 kg','调整后 68 kg','Genybet','2026-11-09T00:00:00+00:00','11-09 08:00（北京时间）'):
            self.assertIn(text,html)

    def test_all_21_official_future_documents_preserve_253_current_entries(self):
        from stable.services.france_sources import parse_france_galop_document
        values=[parse_france_galop_document(d) for d in json.loads((ROOT/'future.json').read_text())]
        self.assertEqual(sum(len(v['items']) for v in values),253)
        self.assertEqual(sum(v['stage']=='not_published' for v in values),10)
        self.assertEqual(sum(v['source_stage']=='probable_runners' for v in values),1)
        self.assertTrue(all(not row['horse_number'] for v in values for row in v['items']))

    def test_entries_are_not_numbered_and_zero_clock_is_unpublished(self):
        from stable.services.france_sources import parse_france_galop_document
        value=parse_france_galop_document(self.fg())
        self.assertEqual(value['stage'],'registration')
        self.assertEqual(value['items'][0]['horse_name'],'LAILISSA (IRE)')
        self.assertEqual(value['items'][0]['horse_number'],'')
        self.assertFalse(value['off_time'])
        self.assertEqual(value['items'][0]['carried_weight'],'56 kg')

    def test_probables_are_explicitly_labelled_and_not_formal_numbers(self):
        from stable.services.france_sources import parse_france_galop_document
        doc=self.fg();doc['text']=doc['text'].replace('Après Engagements : 1 Engagés. 1 Partants.','Après Part. probables : 2 Engagés. 1 Forfaits. 1 Partants probables.').replace('00h00','16h25')
        value=parse_france_galop_document(doc)
        self.assertEqual(value['source_stage'],'probable_runners')
        self.assertEqual(value['stage'],'declared')
        self.assertEqual(value['items'][0]['horse_number'],'')
        self.assertTrue(value['off_time'].endswith('+01:00'))

    def test_fg_empty_and_partial_lists_fail_closed(self):
        from stable.services.france_sources import parse_france_galop_document
        doc=self.fg();doc['tables']=[]
        with self.assertRaises(ValueError):parse_france_galop_document(doc)
        doc['text']+=' AUCUNE LISTE DIFFUSABLE'
        self.assertEqual(parse_france_galop_document(doc)['stage'],'not_published')
        doc=self.fg();doc['text']=doc['text'].replace('1 Partants.','2 Partants.')
        with self.assertRaisesRegex(ValueError,'count'):parse_france_galop_document(doc)

    def test_browser_contract_refuses_expired_or_cross_site_document(self):
        from datetime import datetime,timezone
        from unittest.mock import patch,MagicMock
        from django.test import override_settings
        from stable.services.france_browser_transport import fetch_browser_document
        url=self.fg()['url'];now=datetime(2026,11,9,tzinfo=timezone.utc)
        value=dict(url=url,final_url=url,html='<html><body>Course</body></html>',observed_at=now.isoformat(),
            navigation_count=1,resource_requests=10,elapsed_ms=1000)
        def response(payload):
            r=MagicMock();r.__enter__.return_value=r;r.status_code=200
            r.iter_content.return_value=[json.dumps(payload).encode()]
            return r
        with override_settings(FRANCE_BROWSER_URL='http://france_browser:8080'),patch('django.utils.timezone.now',return_value=now):
            with patch('requests.post',return_value=response(value)):
                self.assertEqual(fetch_browser_document(url)['html'],value['html'])
            for change in [dict(final_url='https://login.example.com/'),dict(observed_at='2026-01-01T00:00:00Z'),dict(navigation_count=3)]:
                with patch('requests.post',return_value=response({**value,**change})),self.assertRaises(ValueError):
                    fetch_browser_document(url)

    @staticmethod
    def fg():
        return dict(url='https://www.france-galop.com/fr/course/detail/2026/P/V3p6QkRwQllwT1AvdkUvZ1pnOHd4dz09',
            title='PRIX MIESQUE | France Galop',text='4ème(P/ 582), — 20/11/2026 00h00, CHANTILLY\nAprès Engagements : 1 Engagés. 1 Partants. - Course Premium -',
            tables=[dict(rows=[['N°','Cheval','Poids','Valeur','Priorité','Propriétaire','Entraîneur','Dép./Pays Ent.','Gains'],
                ['1','LAILISSA (IRE) F.PS. 2 a.','56 kg','40.5','','AGA KHAN STUDS SCEA','M. DELZANGLES','60','16.810']])])


class FranceBrowserBudgetTests(SimpleTestCase):
    def test_geny_reload_contract_is_limited_to_two_same_url_documents(self):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock, patch
        from django.test import override_settings
        from stable.services.france_browser_transport import fetch_browser_document
        now = datetime(2026, 11, 10, tzinfo=timezone.utc)
        programme = 'https://www.geny.com/programme/2026-11-11'
        card = 'https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/partants-pronostics'
        for url, count, resources, accepted in [(programme, 2, 10, True), (programme, 3, 10, False),
                (card, 2, 122, True), (card.replace('partants-pronostics', 'arrivee-rapports'), 2, 192, True),
                (card, 2, 193, False), (card, 1, 97, False),
                ('https://www.france-galop.com/fr/courses/pattern-listed', 2, 10, False)]:
            with self.subTest(url=url, count=count):
                payload = dict(url=url, final_url=url, html='<html><body>Course</body></html>',
                    observed_at=now.isoformat(), navigation_count=count, resource_requests=resources, elapsed_ms=1000)
                response = MagicMock(); response.__enter__.return_value = response; response.status_code = 200
                response.iter_content.return_value = [json.dumps(payload).encode()]
                with override_settings(FRANCE_BROWSER_URL='http://france_browser:8080'), \
                        patch('django.utils.timezone.now', return_value=now), patch('requests.post', return_value=response):
                    if accepted:
                        result = fetch_browser_document(url)
                        self.assertEqual(result['browser']['navigation_count'], 2)
                    else:
                        with self.assertRaises(ValueError):
                            fetch_browser_document(url)

    def test_geny_reload_reserves_both_budgets_and_preserves_other_sources(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from unittest.mock import patch
        from django.test import override_settings
        from stable.services import race_pre_race as pre
        now = datetime(2026, 11, 10, tzinfo=timezone.utc)
        payload = dict(html='<html><body>Programme</body></html>', raw_sha256='a'*64, observed_at=now.isoformat())
        urls = [('https://www.geny.com/programme/2026-11-11', 2),
            ('https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/partants-pronostics', 2),
            ('https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/arrivee-rapports', 2),
            ('https://www.france-galop.com/fr/courses/pattern-listed', 1),
            ('https://www.jra.go.jp/JRADB/accessT.html?CNAME=fixture', 2),
            ('https://www.jra.go.jp/datafile/seiseki/fixture.html', 1)]
        for url, budget in urls:
            with self.subTest(url=url):
                def snapshot(**kwargs):
                    self.assertEqual(kwargs['proposed_requests'], budget)
                    result, actual_requests, request_groups = kwargs['fetcher']()
                    self.assertEqual((actual_requests, request_groups), (budget, 1))
                    return result, False
                with override_settings(FRANCE_BROWSER_URL='http://france_browser:8080', JRA_BROWSER_URL='http://jra_browser:8080'), \
                        patch('stable.services.race_data_sync_providers._get_or_fetch_shared_snapshot', side_effect=snapshot), \
                        patch('stable.services.race_events.ensure_race_live_host_budget_floor'), \
                        patch.object(pre, '_reserve_pre_race_request', return_value=SimpleNamespace(reservation_version=7)) as reserve, \
                        patch('stable.services.race_events.record_race_live_host_outcome'), \
                        patch('stable.services.france_browser_transport.fetch_browser_document', return_value=payload), \
                        patch('stable.services.jra_browser_transport.fetch_browser_document', return_value=payload):
                    self.assertEqual(str(pre._fetch_bounded_html(url, now=now, provider='geny', region='france',
                        validator=lambda value: None, enabled=lambda: True)), payload['html'])
                    self.assertEqual(reserve.call_count, budget)


from datetime import date,datetime,timedelta,timezone
from django.test import TestCase,override_settings
from stable.test_race_pre_race import FLAGS

NOW=datetime(2026,11,9,tzinfo=timezone.utc)

@override_settings(**{**FLAGS,'RACE_DATA_SYNC_FRANCE_PRE_RACE_ENABLED':True,
    'RACE_DATA_SYNC_FRANCE_PRE_RACE_DAYS':60,'RACE_DATA_SYNC_ENABLED_PROVIDERS':('france_galop','geny'),
    'RACE_DATA_SYNC_ENABLED_REGIONS':('france',)})
class FrancePreviewWorkflowTests(TestCase):
    def setUp(self):
        from stable import models
        from stable.services.race_data_source_adapters import SourceRoute
        self.event=models.RaceEvent.objects.create(year=2026,slug='france-miesque-test',original_name='PRIX MIESQUE',
            country_region='france',racecourse='Chantilly',local_date=date(2026,11,20),timezone_name='Europe/Paris',
            status='scheduled',visibility_status='published')
        self.route=SourceRoute(dict(provider='france_galop',region='france',valid_from='2026-01-01T00:00:00Z',
            valid_until='2028-01-01T00:00:00Z',venue_aliases={'fr:chantilly':['Chantilly']},
            allowed_hosts=['www.france-galop.com'],allowed_path_prefixes=['/fr/course/']),'a'*64)

    def test_early_entries_preview_is_idempotent_and_failure_preserves_it(self):
        from stable.services import race_pre_race as pre
        from stable.services.france_pre_race import complete,public_france_preview
        from stable.services.france_sources import parse_france_galop_document
        doc=FranceSourceTests.fg();payload=parse_france_galop_document(doc)
        for now in (NOW,NOW+timedelta(hours=4)):
            claim=pre.claim_pre_race(event_id=self.event.pk,source='france_pre_race_v1',now=now)
            self.assertIsNotNone(claim)
            self.assertTrue(complete(claim,payload=payload,url=doc['url'],page='source',route=self.route,now=now))
        self.event.refresh_from_db();preview=public_france_preview(self.event,now=now)
        self.assertEqual(preview['label'],'报名名单');self.assertEqual(preview['rows'][0].horse_number,'')
        self.assertEqual(preview['rows'][0].source_refs['field_units']['carried_weight'],'kg')
        self.assertEqual(self.event.data_candidates.count(),1)
        later=now+timedelta(hours=4)
        claim=pre.claim_pre_race(event_id=self.event.pk,source='france_pre_race_v1',now=later)
        pre.finish_pre_race(claim,now=later,reason='france_login_required')
        self.event.refresh_from_db()
        self.assertEqual(len(public_france_preview(self.event,now=later)['rows']),1)
        self.assertTrue(public_france_preview(self.event,now=later)['stale'])

    @override_settings(RACE_DATA_SYNC_ENABLED_FIELDS=(*FLAGS['RACE_DATA_SYNC_ENABLED_FIELDS'],'participants.odds'))
    def test_same_price_refresh_retains_real_observation_time(self):
        from types import SimpleNamespace
        from stable.services import race_pre_race as pre
        from stable.services.france_pre_race import complete, public_france_preview
        url='https://www.geny.com/course/123-2026-11-20-chantilly-prix-miesque/partants-pronostics'
        for now in (NOW,NOW+timedelta(hours=4)):
            item=dict(horse_name='TEST',horse_number='1',running_status='declared',
                odds_value='3.2',odds_format='decimal',odds_kind='current',
                source_refs={'odds_source':'Genybet','odds_observed_at':now.isoformat()})
            claim=pre.claim_pre_race(event_id=self.event.pk,source='france_pre_race_v1',now=now)
            self.assertTrue(complete(claim,payload={'stage':'numbered','items':[item]},url=url,
                page=SimpleNamespace(observed_at=now,raw_sha256='a'*64),route=self.route,now=now))
        self.event.refresh_from_db()
        row=public_france_preview(self.event,now=now)['rows'][0]
        self.assertEqual(row.odds_value,'3.2')
        self.assertEqual(row.source_refs['odds_observed_at'],now.isoformat())
        self.event.manual_lock_flags={'runners':True};self.event.save()
        self.assertIsNone(public_france_preview(self.event,now=now))

    def test_disabled_and_other_region_claims_are_rejected(self):
        from stable.services import race_pre_race as pre
        with override_settings(RACE_DATA_SYNC_FRANCE_PRE_RACE_ENABLED=False):
            self.assertIsNone(pre.claim_pre_race(event_id=self.event.pk,source='france_pre_race_v1',now=NOW))
        self.event.country_region='hong_kong';self.event.save()
        self.assertIsNone(pre.claim_pre_race(event_id=self.event.pk,source='france_pre_race_v1',now=NOW))


from stable import test_race_multisource_jra as workflow

@override_settings(**{**workflow.JraColdStartTests._overridden_settings,
    'RACE_DATA_SYNC_ENABLED_PROVIDERS':('geny',),'RACE_DATA_SYNC_ENABLED_REGIONS':('france',)})
class FranceResultWorkflowTests(TestCase):
    def setUp(self):
        from unittest.mock import patch
        from stable import models
        from stable.test_race_multisource_identity import policy_payload
        from stable.services.race_data_source_adapters import parse_multisource_policy
        self.base='https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/'
        data=policy_payload('geny','france')
        data.update(valid_from='2026-01-01T00:00:00Z',valid_until='2028-01-01T00:00:00Z')
        data['routes'][0].update(country_region='france',operator='geny',source_class='trusted_publisher',
            allowed_hosts=['www.geny.com'],allowed_path_prefixes=['/course/','/programme/'],
            timezone='Europe/Paris',venue_aliases={'fr:nantes':['Nantes']},
            valid_from=data['valid_from'],valid_until=data['valid_until'])
        self.policy=parse_multisource_policy(data,now=NOW)
        series=models.RaceSeries.objects.create(key='test-fr-avenir',canonical_name_original="Prix de l'Avenir",
            country_region='france',review_status='approved',source_refs={'primary':self.base+'arrivee-rapports'})
        models.RaceSeriesName.objects.create(series=series,text="Prix de l'Avenir",source_language='fr',source_refs={'primary':self.base+'arrivee-rapports'})
        self.event=models.RaceEvent.objects.create(year=2026,edition_year=2026,slug='fr-avenir-workflow',
            original_name="Prix de l'Avenir",country_region='france',racecourse='Nantes',race_series=series,
            local_date=date(2026,11,2),timezone_name='Europe/Paris',status='scheduled',visibility_status='published',
            source_refs={'primary':self.base+'arrivee-rapports'})
        for target,value in [('django.utils.timezone.now',NOW),('stable.services.race_data_source_adapters.load_multisource_policy',self.policy),('stable.services.france_release.load_multisource_policy',self.policy)]:
            p=patch(target,return_value=value);p.start();self.addCleanup(p.stop)

    def fetch(self,url,**kwargs):
        self.assertTrue(url.startswith(self.base))
        return (ROOT/('avenir-result.html' if url.endswith('arrivee-rapports') else 'avenir-card.html')).read_text()

    def test_independent_card_result_binding_publication_and_replay(self):
        from stable.services.race_data_source_adapters import fetch_bound_observation,run_multisource_claim
        from stable.services.race_data_sync_enrollment import attach_multisource_observation
        from stable.services.race_data_sync_control import claim_multisource_events
        from stable.services.race_information_display import row_fields
        value=fetch_bound_observation(event=self.event,route=self.policy.routes[0],now=NOW,fetcher=self.fetch)
        self.assertTrue(value['roster_complete'])
        decision=attach_multisource_observation(value,policy=self.policy,now=NOW)
        self.assertEqual(decision.action,'acquired',decision)
        claims=claim_multisource_events(event_ids=[self.event.pk],now=NOW,historical=True)
        self.assertEqual(len(claims),1)
        result=run_multisource_claim(claim=claims[0],now=NOW,fetcher=self.fetch)
        self.assertTrue(result['processed'],result)
        self.event.refresh_from_db();self.assertEqual(self.event.status,'finished')
        self.assertEqual(self.event.results.count(),6)
        for row in self.event.results.all():
            fields=row_fields(row)
            self.assertNotEqual(fields['weight'].text,'待核实')
            self.assertNotEqual(fields['odds'].text,'待核实')
            self.assertTrue(row.odds_value)
            self.assertEqual(row.source_refs['odds_source'],'Genybet')
            self.assertEqual(row.source_refs['margin_basis'],'previous_finisher')

class FranceArchiveTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data=json.loads((ROOT / "historical.json").read_text())
    def test_visible_document_replay_preserves_all_511_rows(self):
        from stable.services.france_archive import replay_page
        from stable.services.france_sources import parse_geny_observation
        from stable.services.race_data_source_adapters import SourceRoute
        import re
        total=0
        for result in self.data['results']:
            venue=re.fullmatch(r'.+ à (.+) le \d+ [^ ]+ \d{4} \| Geny',result['title'])[1]
            route=SourceRoute(dict(provider='geny',region='france',operator='geny',identity_namespace='geny-race-v1',
                parser_version='test',timezone='Europe/Paris',allowed_hosts=['www.geny.com'],allowed_path_prefixes=['/course/'],
                venue_aliases={'fr:test':[venue]}),'a'*64)
            card=next(c for c in self.data['cards'] if c['url'].rsplit('/',1)[0]==result['url'].rsplit('/',1)[0])
            value=parse_geny_observation(replay_page(result,observed_at=NOW),url=result['url'],route=route,now=NOW,
                card_page=replay_page(card,observed_at=NOW))
            self.assertEqual(value['roster_complete'],True)
            total+=len(value['roster'])
        self.assertEqual(total,511)

@override_settings(**FranceResultWorkflowTests._overridden_settings)
class FranceReleaseTests(FranceResultWorkflowTests):
    def test_manifest_dry_run_apply_replay_and_atomic_failure(self):
        import hashlib,tempfile
        from stable.services.france_release import execute,event_baseline,series_baseline
        from stable import models
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            archive=json.loads((ROOT/'historical.json').read_text())
            archive={k:[d for d in docs if '/1695527-' in d['url']] for k,docs in archive.items()}
            raw=json.dumps(archive,ensure_ascii=False).encode();(root/'archive.json').write_bytes(raw)
            item=dict(event_id=self.event.pk,event_baseline=event_baseline(self.event),
                series_id=self.event.race_series_id,series_baseline=series_baseline(self.event.race_series),
                fields={},names=["Prix de l'Avenir"],source_url=self.base+'arrivee-rapports',result_rows=6)
            manifest=dict(schema_version=1,action='france_release_data',policy_digest=self.policy.digest,
                archive=dict(file='archive.json',sha256=hashlib.sha256(raw).hexdigest(),observed_at=NOW.isoformat()),
                items=[item],canonical_links=[])
            def save():
                raw=json.dumps(manifest,ensure_ascii=False).encode();(root/'manifest.json').write_bytes(raw)
                return hashlib.sha256(raw).hexdigest()
            sha=save()
            report=execute(root/'manifest.json',sha,now=NOW)
            self.assertEqual(report['action'],'dry_run_rolled_back');self.assertEqual(report['result_rows'],6)
            self.assertEqual(self.event.results.count(),0)
            manifest['items'][0]['result_rows']=7;badsha=save()
            with self.assertRaisesRegex(ValueError,'result_count'):execute(root/'manifest.json',badsha,now=NOW,apply=True)
            self.assertEqual(self.event.results.count(),0)
            manifest['items'][0]['result_rows']=6;sha=save()
            report=execute(root/'manifest.json',sha,now=NOW,apply=True)
            self.assertEqual(report['action'],'applied');self.assertEqual(self.event.results.count(),6)
            ids=list(self.event.results.order_by('pk').values_list('pk',flat=True))
            self.assertEqual(execute(root/'manifest.json',sha,now=NOW,apply=True)['action'],'replay')
            self.assertEqual(list(self.event.results.order_by('pk').values_list('pk',flat=True)),ids)

@override_settings(**{**FranceResultWorkflowTests._overridden_settings,
    'RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED':True,'RACE_DATA_SYNC_RACECARD_APPLY_ENABLED':True,
    'RACE_DATA_SYNC_ENABLED_FIELDS':(*FLAGS['RACE_DATA_SYNC_ENABLED_FIELDS'],'participants.draw','participants.jockey_name','participants.trainer_name','participants.carried_weight','participants.odds','participants.status'),
    'RACE_DATA_SYNC_ENABLED_DATA_KINDS':('race_time','racecard','result')})
class FranceFormalCardTests(FranceResultWorkflowTests):
    def publish_card(self, *, now, changes=None, observed_at=None):
        from unittest.mock import patch
        from bs4 import BeautifulSoup
        from stable.services.race_data_source_adapters import parse_multisource_policy,fetch_bound_observation,run_multisource_claim
        from stable.services.race_data_sync_enrollment import attach_multisource_observation
        from stable.services.race_data_sync_control import claim_due_enrollments
        data=copy.deepcopy(self.policy.payload);data['routes'][0]['capabilities']=['race_time','racecard','result']
        policy=parse_multisource_policy(data,now=now)
        if not self.event.runners.exists():
            self.event.source_refs={'primary':self.base+'partants-pronostics'};self.event.save()
        class Page(str):pass
        def fetch(url,**kwargs):
            self.assertTrue(url.endswith('/partants-pronostics'))
            soup=BeautifulSoup((ROOT/'avenir-card.html').read_text(),'html.parser')
            cells=soup.select('table tr')[1].find_all('td')
            for column,text in (changes or {}).items():cells[column].string=text
            page=Page(str(soup).replace('</head>','<meta name="source-timezone" content="Europe/Paris"></head>').replace('</body>','<p>Départ 13h59</p></body>'))
            page.observed_at=observed_at or now
            return page
        with patch('django.utils.timezone.now',return_value=now),patch('stable.services.race_data_source_adapters.load_multisource_policy',return_value=policy):
            if not self.event.runners.exists():
                value=fetch_bound_observation(event=self.event,route=policy.routes[0],now=now,fetcher=fetch,kind='racecard')
                decision=attach_multisource_observation(value,policy=policy,now=now)
                self.assertEqual(decision.action,'acquired',decision)
            claims=claim_due_enrollments(now=now,batch_size=10,ttl_seconds=240,enabled_providers=("geny",),enabled_regions=("france",),enabled_data_kinds=("race_time","racecard"))
            self.assertEqual(len(claims),1)
            return run_multisource_claim(claim=claims[0],now=now,fetcher=fetch)

    def test_formal_card_persists_weight_price_and_source_after_handoff(self):
        result=self.publish_card(now=NOW-timedelta(days=8))
        self.assertTrue(result['processed'],result)
        self.assertEqual(self.event.runners.count(),6)
        for row in self.event.runners.all():
            self.assertTrue(row.odds_value)
            self.assertEqual(row.source_refs['odds_source'],'Genybet')
            self.assertEqual(row.source_refs['field_units']['carried_weight'],'kg')

    def test_same_slot_changed_horse_requires_review(self):
        now=NOW-timedelta(days=8)
        self.assertTrue(self.publish_card(now=now)['processed'])
        original=list(self.event.runners.order_by('sort_order').values_list('horse_name',flat=True))
        result=self.publish_card(now=now+timedelta(hours=2),changes={2:'DIFFERENT HORSE'})
        self.assertFalse(result['processed'],result)
        self.assertEqual(list(self.event.runners.order_by('sort_order').values_list('horse_name',flat=True)),original)

    def test_same_price_and_allocated_weight_refresh_metadata_but_obey_locks(self):
        now=NOW-timedelta(days=8)
        self.assertTrue(self.publish_card(now=now)['processed'])
        row=self.event.runners.order_by('sort_order').first();price=row.odds_value;weight=row.carried_weight
        later=now+timedelta(hours=2)
        self.assertTrue(self.publish_card(now=later,changes={7:'50'})['processed'])
        row.refresh_from_db()
        self.assertEqual((row.odds_value,row.carried_weight),(price,weight))
        self.assertEqual(row.source_refs['adjusted_weight'],'50 kg')
        self.assertEqual(row.source_refs['odds_observed_at'],later.isoformat())
        # 更旧的缓存内容不能把补充字段或采集时间倒退。
        self.assertTrue(self.publish_card(now=later+timedelta(hours=2),changes={7:'49'},observed_at=now)['processed'])
        row.refresh_from_db();self.assertEqual(row.source_refs['adjusted_weight'],'50 kg')
        self.assertEqual(row.source_refs['odds_observed_at'],later.isoformat())
        row.manual_lock_flags={'carried_weight':True,'odds_value':True};row.save()
        self.assertTrue(self.publish_card(now=later+timedelta(hours=4),changes={7:'48',13:'19'})['processed'])
        row.refresh_from_db()
        self.assertEqual(row.source_refs['adjusted_weight'],'50 kg')
        self.assertEqual(row.source_refs['odds_observed_at'],later.isoformat())
        self.assertEqual(row.odds_value,price)

    def test_race_day_discovery_keeps_card_until_final_result(self):
        from unittest.mock import patch
        from stable.services.race_data_source_adapters import fetch_bound_observation
        now=NOW-timedelta(days=7)+timedelta(hours=9)
        card=(ROOT/'avenir-card.html').read_text().replace('</head>','<meta name="source-timezone" content="Europe/Paris"></head>').replace('</body>','<p>Départ 13h59</p></body>')
        self.event.source_refs={'primary':self.base+'arrivee-rapports'};self.event.save()
        fetched=[]
        def fetch(url,**kw):
            fetched.append(url)
            if url.endswith('partants-pronostics'):return card
            return '<html><head><title>Arrivée et rapports de la course Prix de l’Avenir à Nantes le 2 novembre 2026 | Geny</title></head><body>Résultats non disponibles</body></html>'
        value=fetch_bound_observation(event=self.event,route=self.policy.routes[0],now=now,fetcher=fetch,url_hint=self.base+'arrivee-rapports')
        self.assertEqual(value['result_phase'],'');self.assertEqual(len(value['roster']),6)
        self.assertEqual(fetched,[self.base+'partants-pronostics'])
        value=fetch_bound_observation(event=self.event,route=self.policy.routes[0],now=now+timedelta(hours=8),fetcher=fetch,url_hint=self.base+'arrivee-rapports')
        self.assertEqual(value['result_phase'],'');self.assertEqual(len(value['roster']),6)

@override_settings(**FranceResultWorkflowTests._overridden_settings)
class FranceWholeScopeTests(TestCase):
    def test_80_event_package_materializes_10_aqps_and_replays_511_rows(self):
        import tempfile,hashlib,re
        from unittest.mock import patch
        from django.contrib.auth import get_user_model
        from stable import models
        from stable.test_race_multisource_identity import policy_payload
        from stable.services.france_release import execute,event_baseline,series_baseline,EVENT_FIELDS
        from stable.services.race_data_source_adapters import parse_multisource_policy
        scope=json.loads((ROOT/'release_scope.json').read_text())
        archive=json.loads((ROOT/'historical.json').read_text())
        for row in scope['series']:models.RaceSeries.objects.create(**row)
        for row in scope['events']:
            data={k:row[k] for k in EVENT_FIELDS if k in row};data['country_region']='france'
            data['local_date']=date.fromisoformat(data['local_date'])
            for field in ('local_start_time','race_datetime','result_confirmed_at'):
                data[field]=models.RaceEvent._meta.get_field(field).to_python(data.get(field))
            models.RaceEvent.objects.create(**data)
        # 2026-11-10 真实旧控制状态的离线副本；清除用户/观测外键，保留修订元数据。
        from django.core.management.color import no_style
        from django.db import connection
        from stable.services.france_release_handoff import control_snapshot
        controls=json.loads((ROOT/'legacy_controls.json').read_text())
        legacy_models=[('sources',models.RaceResultSourceIdentity),('revisions',models.RaceEventRevision),
            ('owner',models.RaceEventProjectionControl),('tracking',models.RaceEventLiveTracking),
            ('enrollment',models.RaceDataSyncEnrollment),('checkpoints',models.RaceEventLiveProviderCheckpoint),
            ('lifecycle',models.RaceEventLifecycleControl),('participants',models.RaceEventParticipant),
            ('participant_identities',models.RaceEventParticipantSourceIdentity),('field_authorities',models.RaceEventFieldAuthority),
            ('runner_data',models.RaceEventRunner),('result_data',models.RaceEventResult)]
        for entry in controls:
            for key,model in legacy_models:
                rows=entry[key] if isinstance(entry[key],list) else [entry[key]]
                for row in rows:model.objects.create(**row)
        with connection.cursor() as cursor:
            for sql in connection.ops.sequence_reset_sql(no_style(),[models.RaceEvent,models.RaceSeries]+[m for _,m in legacy_models]):cursor.execute(sql)
        old_sources=list(models.RaceResultSourceIdentity.objects.order_by('pk').values())
        old_revisions=list(models.RaceEventRevision.objects.order_by('pk').values())
        handoffs=[control_snapshot(models.RaceEvent.objects.get(pk=e['event_id'])) for e in controls]
        manifest=scope['manifest']
        manifest['legacy_handoffs']=handoffs
        for item in manifest['items']:
            item['series_baseline']=series_baseline(models.RaceSeries.objects.get(pk=item['series_id']))
            if item['event_id']:
                e=models.RaceEvent.objects.get(pk=item['event_id'])
                original=next(x for x in scope['events'] if x['id']==e.pk)
                if original['results'] and not e.results.exists():
                    doc=next(x for x in archive['results'] if x['url']==item['source_url'])
                    # 生产形状：已有确认赛果、没有v2写权；保留相同已公布马匹与名次数。
                    for pos,row in enumerate(doc['rows'][:original['results']],1):
                        models.RaceEventResult.objects.create(event=e,finish_position=pos,horse_name=row['leaves'][1])
                item['event_baseline']=event_baseline(e)
        manifest['canonical_links'][0]['duplicate_baseline']=event_baseline(models.RaceEvent.objects.get(pk=4))
        venues={}
        for doc in archive['results']:
            venue=re.fullmatch(r'.+ à (.+) le \d+ [^ ]+ \d{4} \| Geny',doc['title'])[1]
            key=venue.lower().replace('-','').replace(' ','')
            venues.setdefault('fr:'+key,set()).add(venue)
        for item in manifest['items']:
            venue=item.get('racecourse') or models.RaceEvent.objects.get(pk=item['event_id']).racecourse
            key=venue.lower().replace('-','').replace(' ','')
            venues.setdefault('fr:'+key,set()).add(venue)
        data=policy_payload('geny','france')
        data.update(valid_from='2026-01-01T00:00:00Z',valid_until='2028-01-01T00:00:00Z')
        data['routes'][0].update(country_region='france',operator='geny',source_class='trusted_publisher',
            allowed_hosts=['www.geny.com'],allowed_path_prefixes=['/course/','/programme/'],
            timezone='Europe/Paris',venue_aliases={k:sorted(v) for k,v in venues.items()},
            valid_from=data['valid_from'],valid_until=data['valid_until'])
        policy=parse_multisource_policy(data,now=NOW);manifest['policy_digest']=policy.digest
        from stable.services.france_archive import replay_page
        from stable.services.france_sources import parse_geny_observation
        for entry in handoffs:
            item=next(i for i in manifest['items'] if i.get('event_id')==entry['event_id'])
            doc=next(d for d in archive['results'] if d['url']==item['source_url'])
            card=next(d for d in archive['cards'] if d['url'].rsplit('/',1)[0]==doc['url'].rsplit('/',1)[0])
            value=parse_geny_observation(replay_page(doc,observed_at=NOW),url=doc['url'],route=policy.routes[0],now=NOW,card_page=replay_page(card,observed_at=NOW))
            runners={r.horse_number:r.pk for r in models.RaceEventRunner.objects.filter(event_id=entry['event_id'])}
            entry['runner_crosswalk']=dict(source_external_race_id=value['external_race_id'],source_raw_sha256=value['raw_sha256'],
                runners={row['external_runner_id']:runners[row['number']] for row in value['roster']})

        actor=get_user_model().objects.create_user(username='release-test')
        with tempfile.TemporaryDirectory() as directory,patch('django.utils.timezone.now',return_value=NOW),patch('stable.services.race_data_source_adapters.load_multisource_policy',return_value=policy),patch('stable.services.france_release.load_multisource_policy',return_value=policy):
            root=Path(directory);raw=json.dumps(archive,ensure_ascii=False).encode();(root/'historical.json').write_bytes(raw)
            manifest['archive'].update(sha256=hashlib.sha256(raw).hexdigest(),observed_at=NOW.isoformat())
            raw=json.dumps(manifest,ensure_ascii=False).encode();(root/'manifest.json').write_bytes(raw)
            sha=hashlib.sha256(raw).hexdigest()
            report=execute(root/'manifest.json',sha,now=NOW,approved_by_id=actor.pk)
            self.assertEqual((len(report['events']),report['result_rows']),(80,511))
            self.assertEqual(models.RaceEvent.objects.count(),71)
            for expected in handoffs:self.assertEqual(control_snapshot(models.RaceEvent.objects.get(pk=expected['event_id'])),{k:v for k,v in expected.items() if k!='runner_crosswalk'})
            # 在最后一场完整赛果已投影后失败，必须回滚此前所有交接、目录及赛果。
            from stable.services import france_release
            original=france_release.run_multisource_claim
            completed=0
            def fail_last(**kwargs):
                nonlocal completed
                result=original(**kwargs);self.assertTrue(result['processed'],result);completed+=1
                if completed==59:raise ValueError('last_result_failure')
                return result
            with patch.object(france_release,'run_multisource_claim',side_effect=fail_last):
                with self.assertRaisesMessage(ValueError,'last_result_failure'):
                    execute(root/'manifest.json',sha,now=NOW,approved_by_id=actor.pk,apply=True)
            self.assertEqual(completed,59)
            self.assertEqual(models.RaceEvent.objects.count(),71)
            self.assertFalse(models.OperationLog.objects.filter(action_type='france_legacy_handoff').exists())
            for expected in handoffs:self.assertEqual(control_snapshot(models.RaceEvent.objects.get(pk=expected['event_id'])),{k:v for k,v in expected.items() if k!='runner_crosswalk'})
            report=execute(root/'manifest.json',sha,now=NOW,approved_by_id=actor.pk,apply=True)
            self.assertEqual(models.RaceEvent.objects.count(),81)
            self.assertEqual(models.RaceEventResult.objects.count(),511)
            self.assertEqual(models.OperationLog.objects.filter(action_type='france_legacy_handoff').count(),10)
            self.assertEqual(list(models.RaceResultSourceIdentity.objects.filter(pk__in=[e['id'] for e in old_sources]).order_by('pk').values()),old_sources)
            self.assertEqual(list(models.RaceEventRevision.objects.filter(pk__in=[e['id'] for e in old_revisions]).order_by('pk').values()),old_revisions)
            for expected in handoffs:
                enrollment=models.RaceDataSyncEnrollment.objects.get(pk=expected['enrollment']['id'])
                self.assertEqual(enrollment.authority_version,2)
                self.assertEqual(enrollment.projection_owner_generation,expected['projection']['owner_generation']+1)

            self.assertEqual(models.RaceEventProductCanonicalLink.objects.get().canonical_event_id,784)
            self.assertEqual(execute(root/'manifest.json',sha,now=NOW,approved_by_id=actor.pk,apply=True)['action'],'replay')

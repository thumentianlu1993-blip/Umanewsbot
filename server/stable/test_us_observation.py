"""真实DRF/SL原件进入通用observation的字段语义。"""
from datetime import datetime, timezone
from unittest import TestCase
from stable import test_us_flat_results as fixtures


class USObservationTests(TestCase):
    def test_physical_margin_off_time_and_race_clock(self):
        from stable.services.us_public_fields import result_participants
        result=fixtures.USFlatResultTests().result('CD2026110708.pdf')
        rows=result_participants(result)
        first, second=rows[:2]
        self.assertEqual(first['margin'],'')
        self.assertEqual(second['margin'],'1/2')
        self.assertEqual(first['field_provenance']['win_odds'],'4.06')
        self.assertTrue(all(not row['finish_time'] for row in rows))
        self.assertEqual(sum(row['status']=='scratched' for row in rows),2)
        self.assertEqual(first['field_provenance']['field_units']['carried_weight'],'lb')
        self.assertEqual(first['field_provenance']['margin_relation'],'previous_physical')
        self.assertEqual(result['off_time'],'2026-11-07T16:25:00-05:00')

    def test_demotion_and_dead_heat_use_reported_placing(self):
        from stable.services.us_public_fields import result_participants
        rows=result_participants(fixtures.USFlatResultTests().result('SA2026100302.pdf'))
        row=next(x for x in rows if x['horse_name']=='Paradise City')
        self.assertEqual(row['reported_finish_position'],2)
        self.assertEqual(row['field_provenance']['physical_finish_position'],1)
        rows=result_participants(fixtures.USFlatResultTests().result('KEE2026103105.pdf'))
        self.assertEqual(sum(x['status']=='dead_heat' for x in rows),2)

    def test_missing_final_program_and_incomplete_roster_rejected(self):
        from stable.services.us_public_fields import result_participants
        result=fixtures.USFlatResultTests().result('CD2026110708.pdf')
        result['runners'].pop()
        with self.assertRaisesRegex(ValueError,'us_result_incomplete'):result_participants(result)

    def test_only_explicit_chart_correction_marker_is_accepted(self):
        from stable.services.us_flat_results import correction_marker
        self.assertEqual(correction_marker('EIGHTH RACE\nCORRECTED CHART\nChurchill'),'CORRECTED CHART')
        self.assertEqual(correction_marker('Revised Chart\nEIGHTH RACE'),'Revised Chart')
        for raw in ['uncorrected chart','previous chart was corrected','Updated.pdf','Race Results Report']:
            self.assertEqual(correction_marker(raw),'')

    def test_nsa_catalogue_book_id_is_not_the_daily_race_number(self):
        import hashlib,json
        from types import SimpleNamespace
        from stable.test_us_prerelease import USSteeplechaseTests,FIX
        from stable.services.us_nsa_sources import parse_results
        from stable.services.us_race_source import source_observation
        fixture=USSteeplechaseTests();case=fixture.CASES[4]
        result=fixture.bundle(case);meta={x['file']:x for x in json.loads((FIX/'provenance.json').read_text())}
        target=next(t for t in parse_results((FIX/case[2]).read_bytes(),url=meta[case[2]]['url'])['items'] if t['race_number']=='5')
        target['venue']='FH'
        now=datetime(2026,11,12,tzinfo=timezone.utc)
        route=SimpleNamespace(provider='us_racing',region='united_states',identity_namespace='us-et',operator='us',
            timezone='America/New_York',venue_aliases={'FH':[]},parser_version='test',permits_url=lambda url:True)
        sources={kind:dict(url=meta[name]['url'],sha256=hashlib.sha256((FIX/name).read_bytes()).hexdigest(),fetched_at=now.isoformat())
            for kind,name in [('chart',case[0]),('official_result',case[2]),('overnight',case[1])]}
        value=source_observation(result,target=target,sources=sources,route=route,now=now)
        self.assertEqual(value['external_race_id'],'FH:2026-10-17:5')
        self.assertEqual(target['source_race_id'],'104')
        with self.assertRaises(ValueError):source_observation(result,target={**target,'book_race_id':'103'},sources=sources,route=route,now=now)

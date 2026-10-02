from datetime import date, time, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, SimpleTestCase, override_settings
from django.template import Template, Context
from django.urls import reverse
from stable.models import RaceEvent, RaceEventResult, TermEntry, TermAlias
from stable.services.race_information_display import prepare_context, row_fields
from stable.services.race_term_display import RaceTermResolver


@override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=True)
class DisplayPageTests(TestCase):
    def setUp(self):
        self.event=RaceEvent.objects.create(year=2026,slug='normalized',original_name='Test Race',chinese_name='测试赛',
            country_region='japan',racecourse='Tokyo',grade_text='Grade 2',normalized_grade='G2',
            surface='turf',distance_text='1 mile',local_date=date(2026,9,18),local_start_time=time(15,40),
            timezone_name='Asia/Tokyo',race_datetime=datetime(2026,9,18,6,40,tzinfo=timezone.utc),visibility_status='published')

    def test_detail_has_standard_units_and_no_raw_grade(self):
        response=self.client.get(self.event.public_path)
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'1英里（约1609米）')
        self.assertNotContains(response,'Grade 2')
        self.assertNotContains(response,'1 mile')
        self.event.refresh_from_db()
        self.assertEqual(self.event.distance_text,'1 mile')

    def test_calendar_and_home_use_same_fields(self):
        for path in ['/races/','/']:
            with self.subTest(path=path):
                with patch('django.utils.timezone.now', return_value=__import__('datetime').datetime(2026,9,18,0,tzinfo=__import__('datetime').timezone.utc)):
                    response=self.client.get(path, {'year':'2026','when':'all','tab':'all'})
                self.assertEqual(response.status_code,200)
                self.assertContains(response,'测试赛')
                self.assertContains(response,'1英里（约1609米）')
                self.assertNotContains(response,'Grade 2')

    def test_strict_term_primary_alias_conflict_does_not_pick_one(self):
        a=TermEntry.objects.create(term_type='horse',source_ja='Equinox',target_zh='春秋分',source_language='en',racing_region='japan')
        b=TermEntry.objects.create(term_type='horse',source_ja='Other',target_zh='别的马',source_language='en',racing_region='japan')
        TermAlias.objects.create(term=b,text='EQUINOX',source_language='en')
        resolver=RaceTermResolver(mode='strict_display_v1').strict
        resolver.add('equinox','horse','japan','en')
        with self.assertNumQueries(2):
            resolver.resolve()
        self.assertEqual(resolver.field('equinox','horse','japan','en').reason_code,'term_conflict')
        self.assertEqual(resolver.field('equinox','horse','japan','en').text,'equinox')

    def test_same_entity_alias_dedup_and_type_region_separation(self):
        a=TermEntry.objects.create(term_type='horse',source_ja='Equinox',target_zh='春秋分',source_language='en',racing_region='japan')
        TermAlias.objects.create(term=a,text='EQUINOX',source_language='en')
        resolver=RaceTermResolver(mode='strict_display_v1').strict
        for i in range(200):
            resolver.add('EQUINOX','horse','japan','en')
        resolver.add('Equinox','race','japan','en')
        resolver.add('Equinox','horse','france','en')
        with self.assertNumQueries(4):resolver.resolve()
        self.assertEqual(resolver.field('EQUINOX','horse','japan','en').text,'春秋分')
        self.assertEqual(resolver.field('Equinox','race','japan','en').text,'Equinox')
        self.assertEqual(resolver.field('Equinox','horse','france','en').text,'Equinox')

    def test_public_result_states_and_dead_heat(self):
        rows=[RaceEventResult(event=self.event,finish_position=i,official_finish_position=1,horse_name='Horse',is_confirmed=True)
              for i in [1,2]]
        context=prepare_context({'event':self.event,'results':rows})
        self.assertEqual([r.public_display['position'].text for r in rows],['并列第1','并列第1'])
        row=RaceEventResult(finish_position=99,official_finish_position=99,running_status='did_not_finish')
        self.assertEqual(row_fields(row)['position'].text,'未完赛')

    def test_missing_visible_rows_never_reloads_hidden_results(self):
        RaceEventResult.objects.create(event=self.event,finish_position=1,horse_name='Hidden horse',is_confirmed=True)
        with self.assertNumQueries(2):
            context=prepare_context({'event':self.event,'results':[],'history_winners':[]})
        self.assertEqual(context['results'],[])
        self.assertNotIn('Hidden horse',str(self.event.public_display))

    def test_preview_namespace_and_dict_autoescape(self):
        for row in [SimpleNamespace(horse_name='<script>alert(1)</script>',carried_weight='57kg'),
                    {'horse_name':'<script>alert(1)</script>','carried_weight':'57kg'}]:
            prepare_context({'event':self.event,'runners':[row]})
            rendered=Template('{% load race_information %}{% race_field row "horse_name" %} / {% race_field row "weight" %}').render(Context({'row':row}))
            self.assertIn('&lt;script&gt;',rendered)
            self.assertIn('57千克',rendered)
            self.assertNotIn('<script>',rendered)

    def test_flag_combinations_restore_model_and_resolver_contract(self):
        term=TermEntry.objects.create(term_type='race',source_ja='Test',target_zh='甲',source_language='en',racing_region='japan')
        other=TermEntry.objects.create(term_type='race',source_ja='Other',target_zh='乙',source_language='en',racing_region='japan')
        TermAlias.objects.create(term=other,text='Test',source_language='en')
        for new in [False,True,False]:
            for old in [False,True]:
                with self.subTest(new=new,old=old), override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=new,RACE_FIELD_NORMALIZED_DISPLAY_ENABLED=old):
                    obj=RaceEvent(grade_text='JpnⅡ',normalized_grade='JPN2',distance_text='9',country_region='united_states')
                    self.assertEqual(obj.grade_badge_label,'Jpn2' if new else 'JPN2')
                    self.assertEqual(obj.display_distance_text,'待核实' if new else '9f')
                    legacy=RaceTermResolver()
                    legacy.add_race_name('Test','japan','en');legacy.resolve()
                    self.assertEqual(legacy.display_race_name('Test','japan','en'),'甲')

    def test_all_template_entrypoints_compile(self):
        from django.template.loader import get_template
        for path in ['race_calendar','race_detail','feed','_hot_list','_flash_race','detail','horse_detail']:
            get_template('stable/public/'+path+'.html')

    def test_review_regressions_whitespace_dead_heat_and_winner_crew(self):
        from stable.services.race_information_display import horse_record_fields
        TermEntry.objects.create(term_type='horse', source_ja='Sunday Silence', target_zh='周日宁静', racing_region='japan', source_language='en')
        resolver=RaceTermResolver(mode='strict_display_v1').strict
        resolver.add('Sunday  Silence','horse','japan','en');resolver.resolve()
        self.assertEqual(resolver.field('Sunday  Silence','horse','japan','en').text,'周日宁静')
        fields=horse_record_fields({'race_date':'2026-09-18','finish_position':'4','normalized_result_status':'dead_heat'})
        self.assertEqual(fields['position'].text,'并列第4')
        self.assertEqual(fields['date'].text,'2026-09-18')
        winner=RaceEventResult(event=self.event,horse_name='Winner',jockey_name='Known Jockey',official_finish_position=1,popularity='1')
        from django.template.loader import render_to_string
        context=prepare_context({'event':self.event,'winner':winner})
        html=render_to_string('stable/public/race_detail.html',context)
        self.assertIn('Known Jockey',html)
        self.assertIn('第1热门',html)
        self.assertNotIn('第 第1热门 人气',html)

    def test_40_events_and_200_unique_runners_use_at_most_ten_term_queries(self):
        events=[SimpleNamespace(original_name=f'Race {i}',racecourse=f'Course {i}',country_region='japan') for i in range(40)]
        rows=[SimpleNamespace(horse_name=f'Horse {i}',jockey_name=f'Jockey {i}',trainer_name=f'Trainer {i}') for i in range(200)]
        with self.assertNumQueries(10):
            prepare_context({'focus_events':events,'event':events[0],'runners':rows})
        self.assertEqual(rows[-1].public_display['horse_name'].text,'Horse 199')

    def test_backend_candidate_preview_is_transient_and_uses_same_fields(self):
        candidate=SimpleNamespace(module='basic',candidate_payload={'grade_text':'GIII','distance_text':'1 mile'},diff_payload={'original':'untouched'})
        prepare_context({'event':self.event,'candidates':[candidate]})
        self.assertIn(('等级','G3'),candidate.normalized_preview[0])
        self.assertIn(('距离','1英里（约1609米）'),candidate.normalized_preview[0])
        self.assertEqual(candidate.diff_payload,{'original':'untouched'})

    def test_article_sidebar_flash_and_five_regions_share_display(self):
        from django.template.loader import render_to_string
        for region in ['japan','hong_kong','united_kingdom','france','united_states']:
            with self.subTest(region=region):
                self.event.country_region=region
                entry={'event':self.event,'winner':'Sample Winner'}
                context=prepare_context({'teaser_event':self.event,'next_key_race':self.event,'today_races':[entry],'flash_race':entry})
                for template in ['detail','_hot_list']:
                    html=render_to_string('stable/public/'+template+'.html',context)
                    self.assertIn('1英里（约1609米）',html)
                    self.assertNotIn('Grade 2',html)
                html=render_to_string('stable/public/_flash_race.html',context)
                self.assertIn('Sample Winner',html)
                self.assertIn('G2',html)

    def test_horse_page_uses_record_adapter_and_does_not_expose_hidden_event(self):
        from stable.models import HorseProfile, HorseRaceRecord
        term=TermEntry.objects.create(term_type='horse',source_ja='Fixture Horse',target_zh='样例马')
        horse=HorseProfile.objects.create(primary_term=term,display_name_zh='样例马',review_status='published')
        record=HorseRaceRecord.objects.create(horse_profile=horse,race_name='历史赛事',race_date=date(2025,1,2),race_year=2025,
            grade_text='GIII',distance_text='1 mile',finish_position='4',normalized_result_status='dead_heat',event=self.event)
        self.event.visibility_status='draft';self.event.chinese_name='Hidden event secret';self.event.save()
        response=self.client.get(horse.public_path)
        self.assertEqual(response.status_code,200)
        for text in ['历史赛事','2025-01-02','G3','1英里（约1609米）','并列第4']:
            self.assertContains(response,text)
        self.assertNotContains(response,'Hidden event secret')

    def test_linked_event_without_date_preserves_record_date_and_major_win_name(self):
        from stable.models import HorseProfile, HorseRaceRecord
        term=TermEntry.objects.create(term_type='horse',source_ja='Winner',target_zh='获胜马')
        horse=HorseProfile.objects.create(primary_term=term,display_name_zh='获胜马',review_status='published')
        self.event.local_date=None;self.event.race_datetime=None;self.event.local_start_time=None;self.event.chinese_name='统一正式名称';self.event.save()
        record=HorseRaceRecord.objects.create(horse_profile=horse,race_name='Old record name',race_date=date(2025,1,2),race_year=2025,
            finish_position='1',event=self.event,is_major_win=True)
        response=self.client.get(horse.public_path)
        self.assertContains(response,'2025-01-02')
        names=[r.public_display['name'].text for r in list(response.context['race_records'])+list(response.context['major_wins'])]
        self.assertEqual(names,['统一正式名称','统一正式名称'])
        self.assertNotContains(response,'Old record name')

    def test_candidate_position_adaptation_does_not_relax_database_row_guard(self):
        candidate=SimpleNamespace(module='results',candidate_payload={'items':[{'horse_name':'Candidate','finish_position':4}]})
        prepare_context({'event':self.event,'candidates':[candidate]})
        self.assertIn(('名次','4'),candidate.normalized_preview[0])
        self.assertEqual(candidate.candidate_payload['items'][0],{'horse_name':'Candidate','finish_position':4})
        row=RaceEventResult(finish_position=4,horse_name='Database row')
        self.assertNotEqual(row_fields(row)['position'].text,'4')


class PublicGradeFilterParityTests(TestCase):
    """公开等级投影必须在分页前用于查询，而不能仅修饰卡片。"""

    def test_raw_g1_without_stored_code_remains_in_g1_filter_under_both_flags(self):
        event = RaceEvent.objects.create(
            year=2025, slug='germany-raw-grade-red', original_name='German grade fixture',
            chinese_name='德国等级回放', country_region='germany', racecourse='Hamburg',
            grade_text='G1', normalized_grade='', local_date=date(2025, 7, 6),
            visibility_status='published', status='finished',
        )
        for flag in (True, False):
            with self.subTest(flag=flag), override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=flag):
                params = {'year': '2025', 'region': 'germany', 'tab': 'all'}
                baseline = self.client.get('/races/', params)
                self.assertContains(baseline, '德国等级回放')
                filtered = self.client.get('/races/', {**params, 'grade': 'g1'})
                self.assertIn(event.pk, [item.pk for group in filtered.context['groups'] for item in group['events']])
                self.assertContains(filtered, 'grade-badge g1')
        event.refresh_from_db()
        self.assertEqual((event.grade_text, event.normalized_grade), ('G1', ''))

    def test_query_code_matches_parser_for_supported_syntax_and_provenance(self):
        import json
        from pathlib import Path
        from stable.services.race_information_display import PublicGradeCode, event_grade_field, filter_public_grade
        cases = json.loads((Path(__file__).resolve().parents[2] /
                            'docs/changes/next-version-capabilities/lanes/C/U01-offline-cases.json').read_text())['cases']
        inputs = [item['event'] for item in cases]
        # 不只测一个Unicode表面写法：包括兼容字母、空白、大小写和符号。
        for prefix in ('G', 'GROUP', 'GRADE', 'GROUPE', 'JPN', 'JG'):
            for suffix in ('I', 'II', 'III', '1', '2', '3'):
                for text in (prefix + suffix, prefix.lower() + ' ' + suffix.lower(),
                             '重賞\t' + prefix + '\u2003' + suffix,
                             prefix + '・-' + suffix):
                    inputs.append(dict(country_region='germany', year=2025,
                                       grade_text=text, normalized_grade=''))
        inputs.extend([
            dict(country_region='germany', year=2025, grade_text='𝔊Ⅰ', normalized_grade=''),
            dict(country_region='germany', year=2025, grade_text='\x1cG1\x1f', normalized_grade=''),
            dict(country_region='germany', year=2025, grade_text='G1'+' '*120, normalized_grade=''),
            dict(country_region='germany', year=2025, grade_text='ﷺ'*40+'G1', normalized_grade=''),
        ])
        refs = {'source_kind':'jra_official_graded_race_list',
                'primary':'https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html'}
        for url in (refs['primary'], 'HTTPS://WWW.JRA.GO.JP/datafile/seiseki/replay/2026/jyusyo.html',
                    refs['primary']+'?x=1#result', '\x1c '+refs['primary'],
                    refs['primary'].replace('https://', 'https:\t//'),
                    refs['primary'].replace('.jp/', '.jp:bad/'),
                    refs['primary'].replace('.jp/', '.jp:443/'),
                    refs['primary'].replace('.jp/', '.jp:0443/'),
                    refs['primary'].replace('.jp/', '.jp:/'),
                    refs['primary'].replace('.jp/', '.jp:444/'),
                    refs['primary'].replace('.jp/', '.jp.evil.example/'),
                    refs['primary'].replace('replay/', 'REPLAY/'),
                    refs['primary'].replace('https://', 'https://user:password@'),
                    None, 42, {}, []):
            inputs.append(dict(country_region='japan', year=2026, grade_text='GIII STRASSE',
                               normalized_grade='', original_name='Straße',
                               source_refs={**refs, 'primary':url}))
        events = []
        for index, payload in enumerate(inputs):
            event = RaceEvent.objects.create(slug=f'grade-parity-{index}',
                chinese_name=f'等级等价{index}', original_name=payload.get('original_name', 'Fixture'),
                country_region=payload['country_region'], year=payload['year'],
                grade_text=payload['grade_text'], normalized_grade=payload['normalized_grade'],
                source_refs=payload.get('source_refs', {}), local_date=date(payload['year'], 7, 6),
                visibility_status='published', status='finished')
            events.append(event)
        queryset = RaceEvent.objects.filter(pk__in=[e.pk for e in events])
        from django.db import connection
        if connection.vendor == 'postgresql':
            from stable.services.race_information_display import _postgresql_grade_capable
            self.assertTrue(_postgresql_grade_capable(connection))
        with self.assertNumQueries(1):
            actual = dict(queryset.annotate(code=PublicGradeCode()).values_list('pk', 'code'))
        for event, item in zip(events, cases):
            self.assertEqual(event_grade_field(event).code or '', item['expected']['code'] or '', item['id'])
            self.assertEqual(event_grade_field(event).text, item['expected']['label'], item['id'])
        for event in events:
            self.assertEqual(actual[event.pk], event_grade_field(event).code or '', event.grade_text)
        for family in (1, 2, 3):
            codes = [f'G{family}', f'JG{family}', f'JPN{family}']
            expected = {e.pk for e in events if event_grade_field(e).code in codes}
            self.assertSetEqual(set(filter_public_grade(queryset, codes).values_list('pk', flat=True)), expected)
        for event in events:
            saved = queryset.get(pk=event.pk)
            self.assertEqual((saved.grade_text, saved.normalized_grade, saved.source_refs),
                             (event.grade_text, event.normalized_grade, event.source_refs))

    def test_missing_postgresql_unicode_capability_closes_grade_projection(self):
        from unittest.mock import Mock, patch
        from stable.services.race_information_display import PublicGradeCode
        compiler = Mock()
        with patch('stable.services.race_information_display._postgresql_grade_capable', return_value=False):
            self.assertEqual(PublicGradeCode().as_postgresql(compiler, Mock()), ('%s', ['']))
        compiler.compile.assert_not_called()

    def test_conflict_does_not_enter_grade_filter_and_unknown_uses_neutral_badge(self):
        from django.template import Context, Template
        from stable.services.race_information_display import filter_public_grade
        event = RaceEvent.objects.create(year=2025, slug='grade-conflict',
            original_name='Conflict', chinese_name='等级冲突', country_region='germany',
            grade_text='G2', normalized_grade='G1', local_date=date(2025, 7, 6),
            visibility_status='published')
        for flag in (False, True):
            with self.subTest(flag=flag), override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=flag):
                self.assertFalse(filter_public_grade(RaceEvent.objects.filter(pk=event.pk), ['G1']).exists())
                html = Template('{% load race_information %}{% race_grade_class event %}|{% race_field event "grade" event.grade_badge_label %}').render(Context({'event':event}))
                self.assertEqual(html, 'g-other|待核实')

    def test_weekly_focus_object_and_query_paths_share_credible_grade(self):
        from stable.views import _public_weekly_focus_events
        from datetime import timedelta
        today = date(2026, 7, 6)
        valid = RaceEvent.objects.create(year=2026, slug='focus-raw', original_name='Focus',
            chinese_name='焦点原始G1', country_region='germany', grade_text='Group I',
            normalized_grade='', local_date=today, visibility_status='published')
        conflict = RaceEvent.objects.create(year=2026, slug='focus-conflict', original_name='Conflict',
            chinese_name='焦点冲突', country_region='germany', grade_text='G2',
            normalized_grade='G1', local_date=today + timedelta(days=1), visibility_status='published')
        hidden = RaceEvent.objects.create(year=2026, slug='focus-hidden', original_name='Hidden',
            chinese_name='隐藏等级', country_region='germany', grade_text='G1',
            normalized_grade='', local_date=today, visibility_status='draft')
        self.assertEqual([e.pk for e in _public_weekly_focus_events('germany', today=today)], [valid.pk])
        # 对象分支的输入已由公开query过滤；不绕过可见性边界传入hidden。
        self.assertEqual([e.pk for e in _public_weekly_focus_events('germany', events=[valid,conflict], today=today)], [valid.pk])

    def test_historical_key_applies_credible_grade_before_pagination(self):
        from stable.views import _race_calendar_queryset
        from django.test import RequestFactory
        from stable.services.race_information_display import event_grade_field
        for index in range(5):
            RaceEvent.objects.create(year=2025, slug=f'paging-g2-{index}', original_name='G2 Fixture',
                chinese_name=f'二级{index}', country_region='germany', grade_text='Group II',
                normalized_grade='', local_date=date(2025, 7, index+1), visibility_status='published')
        targets = []
        for index in range(4):
            targets.append(RaceEvent.objects.create(year=2025, slug=f'paging-g1-{index}', original_name='G1 Fixture',
                chinese_name=f'一级{index}', country_region='germany', grade_text='Group I',
                normalized_grade='', local_date=date(2025, 8, index+1), visibility_status='published'))
        rf = RequestFactory()
        with patch('stable.views.RACE_CALENDAR_PAGE_SIZE', 2):
            rows, _, _, pagination = _race_calendar_queryset(rf.get('/races/',
                {'year':'2025','region':'germany','tab':'key','grade':'g1'}), today=date(2026, 7, 6))
        self.assertEqual([e.pk for e in rows], [e.pk for e in targets[:2]])
        self.assertTrue(pagination['has_next'])
        self.assertTrue(all(event_grade_field(e).code=='G1' for e in rows))

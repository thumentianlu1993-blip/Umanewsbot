"""HKJC 目录只读匹配：不访问第三方或业务数据库。"""
from django.test import SimpleTestCase


def entry(kind, names, target, ident='one'):
    return {'id': ident, 'kind': kind, 'names': names, 'target': target,
            'source': 'https://racing.hkjc.com/zh-hk/overseas/race-card?RaceDate=20261115'}


class NameCatalogTests(SimpleTestCase):
    def catalog(self, *entries):
        from stable.services.hkjc_name_catalog import NameCatalog
        return NameCatalog(entries)

    def test_japanese_and_english_are_explicit_aliases(self):
        c = self.catalog(entry('jockey', ['武豊', 'Yutaka Take'], '武丰'))
        for raw in ['武 豊', 'Yutaka Take', 'Y. Take', 'Y TAKE']:
            with self.subTest(raw=raw):
                self.assertEqual(c.match(raw, 'jockey').text, '武丰')
        self.assertEqual(c.match('Take', 'jockey').text, 'Take')

    def test_abbreviation_checks_all_matching_full_names(self):
        c = self.catalog(entry('jockey', ['Yutaka Take', 'Y Take'], '武丰'),
                         entry('jockey', ['Yuji Take'], '武裕治', 'two'))
        self.assertEqual(c.match('Y. Take', 'jockey').state, 'conflict')
        self.assertEqual(c.match('Yutaka Take', 'jockey').text, '武丰')

    def test_same_translation_does_not_disambiguate_two_full_names(self):
        c = self.catalog(entry('trainer', ['John Smith'], '史密夫'),
                         entry('trainer', ['James Smith'], '史密夫', 'two'))
        self.assertEqual(c.match('J Smith', 'trainer').state, 'conflict')

    def test_observed_initials_and_full_names_can_agree(self):
        c = self.catalog(entry('jockey', ['R L Moore'], '莫雅'),
                         entry('jockey', ['Ryan Lee Moore'], '莫雅', 'two'))
        self.assertEqual(c.match('R.L. Moore', 'jockey').text, '莫雅')

    def test_horse_country_suffix_and_case(self):
        c = self.catalog(entry('horse', ['ドウデュース', 'Do Deuce (JPN)'], '胜局在望'))
        for raw in ['Do Deuce', 'DO DEUCE (JPN)', 'ドウデュース']:
            self.assertEqual(c.match(raw, 'horse').text, '胜局在望')
        self.assertEqual(c.match('D Deuce', 'horse').text, 'D Deuce')

    def test_punctuation_and_accents(self):
        c = self.catalog(entry('trainer', ["André Fabre"], '费伯华'),
                         entry('trainer', ["Aidan O’Brien"], '岳伯仁', 'two'))
        self.assertEqual(c.match('Andre Fabre', 'trainer').text, '费伯华')
        self.assertEqual(c.match("A. O'Brien", 'trainer').text, '岳伯仁')

    def test_type_and_translation_conflict(self):
        c = self.catalog(entry('jockey', ['John Smith'], '甲'),
                         entry('trainer', ['John Smith'], '乙', 'two'),
                         entry('horse', ['Example'], '一', 'three'),
                         entry('horse', ['Example'], '二', 'four'))
        self.assertEqual(c.match('John Smith', 'trainer').text, '乙')
        self.assertEqual(c.match('Example', 'horse').state, 'conflict')
        self.assertEqual(c.match('Unknown', 'horse').text, 'Unknown')

    def test_reject_nonofficial_or_empty_translation(self):
        for e in [entry('horse', ['Example'], ''),
                  {**entry('horse', ['Example'], '例子'), 'source': 'https://hkjc.com.evil.test/a'}]:
            with self.subTest(entry=e):
                with self.assertRaises(ValueError):
                    self.catalog(e)

    def test_no_surname_or_joint_name_inference(self):
        c = self.catalog(entry('trainer', ['John & Thady Gosden'], '高斯登父子'))
        for raw in ['Gosden', 'J Gosden', 'J T Gosden']:
            self.assertEqual(c.match(raw, 'trainer').text, raw)

    def test_configured_display_ignores_venue_and_source_language(self):
        from unittest.mock import patch
        from stable.services.race_term_display import StrictRaceTermResolver
        c = self.catalog(entry('jockey', ['武豊', 'Yutaka Take'], '武丰'))
        with patch('stable.services.hkjc_name_catalog.configured_catalog', return_value=c):
            r = StrictRaceTermResolver()
            r.add('Y. Take', 'jockey', 'france', 'en', 2026)
            r.resolve()
        field = r.field('Y. Take', 'jockey', 'france', 'en', 2026)
        self.assertEqual(field.text, '武丰')
        self.assertEqual(field.reason_code, 'hkjc_initials')

    def test_display_conflict_keeps_original_name(self):
        from unittest.mock import patch
        from stable.services.race_term_display import StrictRaceTermResolver
        c = self.catalog(entry('jockey', ['John Smith'], '甲'),
                         entry('jockey', ['James Smith'], '乙', 'two'))
        with patch('stable.services.hkjc_name_catalog.configured_catalog', return_value=c):
            r = StrictRaceTermResolver()
            r.add('J Smith', 'jockey')
            r.resolve()
        self.assertEqual(r.field('J Smith', 'jockey').text, 'J Smith')
        self.assertEqual(r.field('J Smith', 'jockey').state, 'conflict')

    def test_surname_first_initials_keep_all_tokens(self):
        c = self.catalog(entry('jockey', ['Mickael Barzalona'], '巴米高'))
        self.assertEqual(c.match('Barzalona M.', 'jockey').text, '巴米高')
        self.assertEqual(c.match('Barzalona', 'jockey').text, 'Barzalona')

    def test_prepared_race_rows_use_catalog_without_changing_raw_values(self):
        from unittest.mock import patch
        from stable.services.race_information_display import prepare_context
        c = self.catalog(entry('horse', ['Do Deuce'], '胜局在望'),
                         entry('jockey', ['武豊', 'Yutaka Take'], '武丰', 'two'),
                         entry('trainer', ['Yasuo Tomomichi'], '友道康夫', 'three'))
        row = {'horse_name': 'Do Deuce', 'jockey_name': 'Y Take', 'trainer_name': 'Y Tomomichi'}
        original = dict(row)
        with patch('stable.services.hkjc_name_catalog.configured_catalog', return_value=c):
            prepare_context({'runners': [row]}, force=True)
        self.assertEqual({k: row[k] for k in original}, original)
        self.assertEqual(row['public_display']['horse_name'].text, '胜局在望')
        self.assertEqual(row['public_display']['jockey_name'].text, '武丰')
        self.assertEqual(row['public_display']['trainer_name'].text, '友道康夫')

    def test_japanese_foreign_display_alias_is_not_inferred_without_evidence(self):
        c = self.catalog(entry('jockey', ['Christophe Lemaire', 'C．ルメール'], '李慕华'))
        self.assertEqual(c.match('Ｃ．ルメール', 'jockey').text, '李慕华')
        self.assertEqual(c.match('C. Lemaire', 'jockey').text, '李慕华')
        self.assertEqual(c.match('ルメール', 'jockey').text, 'ルメール')

    def test_file_requires_matching_sha_and_bad_file_falls_back(self):
        import hashlib
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from stable.services.hkjc_name_catalog import configured_catalog, load_catalog
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'names.json'
            path.write_text(json.dumps({'schema': 'hkjc-name-display-v1', 'entries': [
                entry('jockey', ['Yutaka Take'], '武丰')]}))
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(load_catalog(str(path), sha).match('Y Take', 'jockey').text, '武丰')
            with self.settings(RACE_HKJC_NAME_CATALOG_PATH=str(path), RACE_HKJC_NAME_CATALOG_SHA256='wrong'):
                with self.assertLogs('stable.services.hkjc_name_catalog', level='ERROR'):
                    self.assertEqual(configured_catalog().match('Y Take', 'jockey').text, 'Y Take')
        with self.settings(RACE_HKJC_NAME_CATALOG_PATH=''):
            self.assertIsNone(configured_catalog())

    def test_malformed_catalog_with_valid_sha_falls_back_before_caching(self):
        import hashlib
        import json
        from unittest.mock import patch
        from stable.services.hkjc_name_catalog import configured_catalog, load_catalog
        good = entry('jockey', ['Yutaka Take'], '武豊')
        malformed = [[], {'schema': 'hkjc-name-display-v1', 'entries': [
            {key: val for key, val in good.items() if key != 'id'}]}]
        malformed.extend({'schema': 'hkjc-name-display-v1', 'entries': [{**good, field: value}]}
                         for field, value in [('id', []), ('names', 'Yutaka Take'),
                                              ('names', [None]), ('target', None), ('source', None), ('active_years', None)])
        for payload in malformed:
            raw = json.dumps(payload).encode()
            sha = hashlib.sha256(raw).hexdigest()
            load_catalog.cache_clear()
            with self.subTest(payload=payload), self.settings(
                    RACE_HKJC_NAME_CATALOG_PATH='/fixture/catalog.json', RACE_HKJC_NAME_CATALOG_SHA256=sha):
                with patch('pathlib.Path.read_bytes', return_value=raw):
                    with self.assertLogs('stable.services.hkjc_name_catalog', level='ERROR'):
                        self.assertEqual(configured_catalog().match('Y Take', 'jockey').text, 'Y Take')
            self.assertEqual(load_catalog.cache_info().currsize, 0)

    def test_reviewed_alias_group_resolves_compatible_initials_only(self):
        c = self.catalog(
            {**entry('jockey', ['James Spencer'], '史宾沙'), 'identity_group': 'review:35'},
            {**entry('jockey', ['Jamie Spencer'], '史宾沙', 'two'), 'identity_group': 'review:35'})
        self.assertEqual(c.match('J Spencer', 'jockey').text, '史宾沙')
        c = self.catalog(*c.entries, entry('jockey', ['John Spencer'], '史宾沙', 'three'))
        self.assertEqual(c.match('J Spencer', 'jockey').state, 'conflict')

    def test_same_birth_year_requires_country_or_pedigree(self):
        c = self.catalog(
            {**entry('horse', ['Los Angeles (JPN)', 'ロサンゼルス'], '洛杉矶'),
             'identity_group': 'jp', 'identity': {'country': 'JPN', 'birth_year': 2021, 'sire': 'California Chrome'}},
            {**entry('horse', ['Los Angeles (IRE)'], '南加名城', 'two'),
             'identity_group': 'ie', 'identity': {'country': 'IRE', 'birth_year': 2021, 'sire': 'Camelot'}})
        self.assertEqual(c.match('Los Angeles', 'horse', {'birth_year': 2021}).state, 'conflict')
        self.assertEqual(c.match('Los Angeles (JPN)', 'horse').text, '洛杉矶')
        self.assertEqual(c.match('Los Angeles', 'horse', {'sire': 'Camelot (GB)'}).text, '南加名城')
        self.assertEqual(c.match('Los Angeles (IRE)', 'horse', {'sire': 'California Chrome'}).state, 'conflict')
        self.assertEqual(c.match('Los Angeles', 'horse', {'birth_year': 2018}).state, 'conflict')

    def test_explicit_age_and_race_year_disambiguate_but_venue_does_not(self):
        c = self.catalog(
            {**entry('horse', ['Birdman'], '甲'), 'identity': {'birth_year': 2010}},
            {**entry('horse', ['Birdman'], '乙', 'two'), 'identity': {'birth_year': 2021}})
        self.assertEqual(c.match('Birdman', 'horse', {'age': 3, 'race_year': 2024}).text, '乙')
        self.assertEqual(c.match('Birdman', 'horse', {'age': 3}).state, 'conflict')
        self.assertEqual(c.match('Birdman', 'horse', {'country_region': 'japan'}).state, 'conflict')
        self.assertEqual(c.match('Birdman', 'horse', {'birth_year': 2010, 'age': 3, 'race_year': 2024}).state, 'conflict')

    def test_hannon_role_dates_and_per_row_context_do_not_leak(self):
        from unittest.mock import patch
        from stable.services.race_term_display import StrictRaceTermResolver
        c = self.catalog(
            {**entry('trainer', ['Richard Hannon'], '向能'), 'active_years': [None, 2013]},
            {**entry('trainer', ['Richard Hannon'], '向礼伦', 'two'), 'active_years': [2014, None]})
        self.assertEqual(c.match('Richard Hannon', 'trainer').state, 'conflict')
        with patch('stable.services.hkjc_name_catalog.configured_catalog', return_value=c):
            r = StrictRaceTermResolver()
            for year in [2012, 2026]:
                r.add('R Hannon', 'trainer', name_context={'race_year': year})
            r.resolve()
        self.assertEqual(r.field('R Hannon', 'trainer', name_context={'race_year': 2012}).text, '向能')
        self.assertEqual(r.field('R Hannon', 'trainer', name_context={'race_year': 2026}).text, '向礼伦')

    def test_history_winner_uses_own_year_not_parent_event_year(self):
        from unittest.mock import patch
        from stable.services.race_information_display import prepare_context
        c = self.catalog(
            {**entry('trainer', ['Richard Hannon'], '向能'), 'active_years': [None, 2013]},
            {**entry('trainer', ['Richard Hannon'], '向礼伦', 'two'), 'active_years': [2014, None]},
            entry('horse', ['Example'], '例子', 'horse'), entry('jockey', ['Ryan Moore'], '莫雅', 'jockey'))
        row = {'horse_name': 'Example', 'jockey_name': 'Ryan Moore', 'trainer_name': 'R Hannon', 'winner_year': 2012}
        with patch('stable.services.hkjc_name_catalog.configured_catalog', return_value=c):
            prepare_context({'event': {'year': 2026}, 'history_winners': [row]}, force=True)
        self.assertEqual(row['public_display']['trainer_name'].text, '向能')

    def test_review_application_binds_baseline_and_preserves_raw_evidence(self):
        import hashlib
        import importlib.util
        import json
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('apply_hkjc_reviews', Path(__file__).resolve().parents[2] / 'scripts/apply_hkjc_name_reviews.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rows = [dict(entry('horse', ['Curren Chan', 'カレンチャン', '真机灵'], '真机灵'), source_zh_hant='真機靈'),
                dict(entry('horse', ['Curren Chan', 'カレンチャン', '真机伶'], '真机伶', 'two'), source_zh_hant='真機伶')]
        raw = json.dumps({'schema': 'hkjc-name-display-v1', 'entries': rows}).encode()
        decisions = {'schema': 'hkjc-name-reviews-v1', 'catalog_sha256': hashlib.sha256(raw).hexdigest(),
                     'decision_queue_sha256': 'audit', 'cases': [{'number': 30, 'kind': 'horse',
                        'status': 'approved', 'decision': '仅保留真机伶', 'groups': [{
                            'ids': ['one', 'two'], 'target': '真机伶', 'identity_group': 'review:30',
                            'remove_aliases': ['真机灵', '真機靈']}]}]}
        result = module.apply_reviews(raw, decisions)
        c = self.catalog(*result['entries'])
        self.assertEqual(c.match('カレンチャン', 'horse').text, '真机伶')
        self.assertEqual(c.match('真机灵', 'horse').state, 'preserved')
        self.assertEqual(result['entries'][0]['source_zh_hant'], '真機靈')
        self.assertEqual(json.loads(raw)['entries'][0]['target'], '真机灵')
        with self.assertRaises(ValueError):
            module.apply_reviews(raw + b' ', decisions)
        decisions['cases'][0]['status'] = 'pending'
        with self.assertRaises(ValueError):
            module.apply_reviews(raw, decisions)

    def test_missing_identity_cannot_create_false_unique_candidate(self):
        c = self.catalog({**entry('horse', ['Example'], '甲'), 'identity': {'birth_year': 2021}},
                         entry('horse', ['Example'], '乙', 'two'))
        self.assertEqual(c.match('Example', 'horse', {'birth_year': 2021}).state, 'conflict')
        self.assertEqual(c.match('Example', 'horse', {'birth_year': 2018}).state, 'conflict')

    def test_malformed_reviewed_metadata_is_rejected(self):
        for extra in [{'identity': []}, {'identity': {'birth_year': 'bad'}},
                      {'identity_group': []}, {'active_years': None}, {'active_years': ['bad', None]}, {'active_years': [2026, 2013]}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.catalog({**entry('horse', ['Example'], '例子'), **extra})

    def test_fullwidth_country_suffix_cannot_bypass_identity_conflict(self):
        c = self.catalog(entry('horse', ['Gran Dia (JPN)'], '佳日'))
        for raw in ['Gran Dia (IRE)', 'Gran Dia（IRE）', 'Gran Dia (ＩＲＥ)']:
            with self.subTest(raw=raw):
                self.assertEqual(c.match(raw, 'horse').state, 'conflict')
        self.assertEqual(c.match('Gran Dia（ＪＰＮ）', 'horse').text, '佳日')

    def test_chinese_display_glyphs_do_not_change_source_or_other_names(self):
        c = self.catalog(entry('jockey', ['Yutaka Take', '武豊'], '武豊'),
                         entry('horse', ['Example'], '全力一撃', 'two'))
        for name in ['Yutaka Take', '武豊', '武丰']:
            self.assertEqual(c.match(name, 'jockey').text, '武丰')
        self.assertEqual(c.match('Example', 'horse').text, '全力一击')
        self.assertEqual(c.entries[0]['names'], ['Yutaka Take', '武豊'])
        self.assertEqual(c.entries[0]['target'], '武豊')
        from stable.services.hkjc_name_catalog import chinese_display_name
        self.assertEqual(chinese_display_name('齐斋郎研晃乾'), '齐斋郎研晃乾')

    def test_history_without_year_does_not_inherit_parent_including_candidates(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from stable.services.race_information_display import prepare_context
        c = self.catalog(
            {**entry('trainer', ['Richard Hannon'], '向能'), 'active_years': [None, 2013]},
            {**entry('trainer', ['Richard Hannon'], '向礼伦', 'two'), 'active_years': [2014, None]},
            entry('horse', ['Example'], '例子', 'horse'), entry('jockey', ['Ryan Moore'], '莫雅', 'jockey'))
        original = {'horse_name': 'Example', 'jockey_name': 'Ryan Moore', 'trainer_name': 'R Hannon'}
        row = dict(original)
        candidate = SimpleNamespace(module='history_winners', candidate_payload=[dict(original)])
        with patch('stable.services.hkjc_name_catalog.configured_catalog', return_value=c):
            prepare_context({'event': {'year': 2026}, 'history_winners': [row], 'candidates': [candidate]}, force=True)
        self.assertEqual(row['public_display']['trainer_name'].state, 'conflict')
        self.assertEqual(dict(candidate.normalized_preview[0])['练马师'], 'R Hannon')
        self.assertEqual(candidate.candidate_payload, [original])


from pathlib import Path
from datetime import date, datetime, time, timezone
from django.test import TestCase, override_settings

BUNDLED_CATALOG = Path(__file__).parent / 'data' / 'hkjc_name_catalog_20261115.json'
BUNDLED_SHA = '675fa8e79fef4b8cffb495dff1bc4a515732d97fa999aa99eb01db28612f78c5'


@override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=True,
                   RACE_HKJC_NAME_CATALOG_PATH=str(BUNDLED_CATALOG),
                   RACE_HKJC_NAME_CATALOG_SHA256=BUNDLED_SHA)
class HkjcCatalogPublicPageTests(TestCase):
    def setUp(self):
        from stable.models import RaceEvent, RaceEventRunner, RaceEventResult, RaceEventHistoryWinner
        self.event = RaceEvent.objects.create(
            year=2026, slug='hkjc-names-release', original_name='Catalog Race', chinese_name='名称展示测试赛',
            country_region='japan', racecourse='Tokyo', grade_text='G1', normalized_grade='G1',
            surface='turf', distance_text='1600m', local_date=date(2026, 9, 18),
            local_start_time=time(15, 40), timezone_name='Asia/Tokyo',
            race_datetime=datetime(2026, 9, 18, 6, 40, tzinfo=timezone.utc), visibility_status='published',
            status='finished')
        names = dict(horse_name='Do Deuce', jockey_name='Y Take', trainer_name='Y Tomomichi')
        self.runner = RaceEventRunner.objects.create(event=self.event, horse_number='1', **names)
        self.result = RaceEventResult.objects.create(event=self.event, finish_position=1,
            official_finish_position=1, is_confirmed=True, **names)
        self.history = RaceEventHistoryWinner.objects.create(event=self.event, winner_year=2012,
            horse_name='カレンチャン', jockey_name='R Moore', trainer_name='R Hannon')

    def test_bundled_catalog_is_sha_bound_and_has_all_review_decisions(self):
        from stable.services.hkjc_name_catalog import load_catalog
        import json
        catalog = load_catalog(str(BUNDLED_CATALOG), BUNDLED_SHA)
        self.assertEqual(len(catalog.entries), 20519)
        self.assertEqual(json.loads(BUNDLED_CATALOG.read_text())['review']['case_numbers'], list(range(1, 66)))
        self.assertEqual(catalog.match('エーシンフォワード', 'horse').text, '荣进快蹄')
        self.assertEqual(catalog.match('カレンチャン', 'horse').text, '真机伶')
        self.assertEqual(catalog.match('捷足先得', 'horse').state, 'preserved')
        self.assertEqual(catalog.match('真机灵', 'horse').state, 'preserved')

    def test_detail_translates_runners_results_and_history_without_writes(self):
        response = self.client.get(self.event.public_path)
        self.assertEqual(response.status_code, 200)
        for text in ['胜局在望', '武丰', '友道康夫', '真机伶', '莫雅', '向能']:
            self.assertContains(response, text)
        self.assertNotContains(response, '向礼伦')
        for obj in [self.runner, self.result]:
            obj.refresh_from_db()
            self.assertEqual((obj.horse_name, obj.jockey_name, obj.trainer_name),
                             ('Do Deuce', 'Y Take', 'Y Tomomichi'))
        self.history.refresh_from_db()
        self.assertEqual((self.history.horse_name, self.history.trainer_name), ('カレンチャン', 'R Hannon'))

    def test_calendar_winner_uses_catalog(self):
        response = self.client.get('/races/', {'year': '2026', 'tab': 'all', 'when': 'all'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '胜局在望')

    def test_conflicting_and_unknown_names_preserve_source_and_disable_restores_display(self):
        from stable.models import RaceEventRunner
        RaceEventRunner.objects.create(event=self.event, horse_number='2', horse_name='Los Angeles',
                                       jockey_name='J Doyle', trainer_name='Y Takahashi')
        RaceEventRunner.objects.create(event=self.event, horse_number='3', horse_name='Unlisted Catalog Horse',
                                       jockey_name='Unlisted Rider', trainer_name='Unlisted Trainer')
        response = self.client.get(self.event.public_path)
        for name in ['Los Angeles', 'J Doyle', 'Y Takahashi', 'Unlisted Catalog Horse', 'Unlisted Rider', 'Unlisted Trainer']:
            self.assertContains(response, name)
        with self.settings(RACE_HKJC_NAME_CATALOG_PATH='', RACE_HKJC_NAME_CATALOG_SHA256=''):
            response = self.client.get(self.event.public_path)
        self.assertContains(response, 'Do Deuce')
        self.assertNotContains(response, '胜局在望')

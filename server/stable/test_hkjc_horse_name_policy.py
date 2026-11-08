from types import SimpleNamespace

from django.test import TestCase, override_settings

from stable.models import HorseProfile, SourceLanguage, TermEntry, TermType
from stable.services.race_term_display import StrictRaceTermResolver
from stable.services.terms import apply_term_mappings, recognize_horse_names, resolve_article_entities
from stable.views import _attach_race_term_display_names

OFFICIAL = ('source=hkjc_overseas;source_tier=official;requires_review=false;'
            'evidence=https://racing.hkjc.com/en-us/overseas/results?RaceDate=20251228;'
            'original_zh_hant=杏飴')


@override_settings(HORSE_NAMES_REQUIRE_HKJC_ENABLED=True)
class HkjcHorseNamePolicyTests(TestCase):
    def term(self, **kwargs):
        return TermEntry.objects.create(term_type=TermType.HORSE, source_language=SourceLanguage.JAPANESE,
                                       source_ja=kwargs.pop('source_ja', 'アンズアメ'),
                                       target_zh=kwargs.pop('target_zh', '杏饴'), **kwargs)

    def test_strict_display_rejects_manual_name_and_preserves_jockey(self):
        self.term(notes='source=manual_review; mentions hkjc')
        TermEntry.objects.create(term_type=TermType.JOCKEY, source_ja='Rider', target_zh='骑师译名')
        resolver = StrictRaceTermResolver()
        resolver.add('アンズアメ', TermType.HORSE)
        resolver.add('Rider', TermType.JOCKEY)
        resolver.resolve()
        self.assertEqual(resolver.field('アンズアメ', TermType.HORSE).text, 'アンズアメ')
        self.assertEqual(resolver.field('Rider', TermType.JOCKEY).text, '骑师译名')

    @override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=False)
    def test_legacy_display_uses_same_policy(self):
        self.term(notes='source=wpstud')
        runner = SimpleNamespace(horse_name='アンズアメ', jockey_name='Rider')
        _attach_race_term_display_names([(SimpleNamespace(country_region=''), [runner])])
        self.assertEqual(runner.display_horse_name, 'アンズアメ')

    def test_translation_rejects_manual_target_and_protects_original(self):
        term = self.term(notes='source=manual_review')
        resolution = resolve_article_entities('アンズアメが出走', 'アンズアメは牝馬です。')
        horses = [e for e in resolution.entities if e.entity_type == 'horse']
        self.assertTrue(horses)
        self.assertTrue(all(e.needs_preserve and not e.target_zh for e in horses))
        self.assertNotIn('杏饴', str(resolution.accepted_terms))
        self.assertEqual(apply_term_mappings('アンズアメが出走'), 'アンズアメが出走')
        self.assertTrue(recognize_horse_names('アンズアメが出走', '')[0].needs_preserve)
        term.refresh_from_db()
        self.assertEqual(term.target_zh, '杏饴')

    def test_official_name_and_original_binding(self):
        term = self.term(notes=OFFICIAL)
        self.assertEqual(apply_term_mappings('アンズアメ'), '杏饴')
        term.target_zh = '自造中文'; term.save()
        self.assertEqual(apply_term_mappings('アンズアメ'), 'アンズアメ')

    def test_hostname_spoof_and_duplicate_keys_rejected(self):
        for notes in [OFFICIAL.replace('racing.hkjc.com/', 'racing.hkjc.com.evil.test/'),
                      OFFICIAL.replace('https://racing.hkjc.com/', 'https://hkjc.com@evil.test/'),
                      OFFICIAL + ';source=manual_review',
                      OFFICIAL.replace('requires_review=false', 'requires_review=true')]:
            with self.subTest(notes=notes):
                TermEntry.objects.all().delete()
                self.term(notes=notes)
                self.assertEqual(apply_term_mappings('アンズアメ'), 'アンズアメ')

    def test_official_simplified_name_needs_no_original_field(self):
        self.term(notes=OFFICIAL.split(';original_zh_hant=')[0])
        self.assertEqual(apply_term_mappings('アンズアメ'), '杏饴')

    def test_profile_ignores_unverified_display_override_and_pedigree(self):
        term = self.term(notes=OFFICIAL)
        profile = HorseProfile(primary_term=term, display_name_zh='人工别名', original_name='アンズアメ',
                               sire_text='无来源父名', dam_text='Original Dam')
        self.assertEqual(profile.public_display_name, '杏饴')
        self.assertEqual(profile.public_sire_text, '')
        self.assertEqual(profile.public_dam_text, 'Original Dam')
        self.assertEqual(profile.display_name, '人工别名')

    @override_settings(HORSE_NAMES_REQUIRE_HKJC_ENABLED=False)
    def test_disabled_policy_preserves_existing_behavior(self):
        term = self.term(notes='source=manual_review')
        self.assertEqual(apply_term_mappings('アンズアメ'), '杏饴')
        self.assertEqual(HorseProfile(primary_term=term, display_name_zh='人工别名').public_display_name, '人工别名')

    @override_settings(TRANSLATION_MODEL='test', TRANSLATION_MAX_ATTEMPTS=1,
                       TRANSLATION_UNKNOWN_HORSE_LIMIT=1, TRANSLATION_TERM_LIMIT=50)
    def test_actual_translation_protects_all_rejected_horses_even_above_limit(self):
        from unittest.mock import patch
        from stable.models import NewsArticle
        from stable.services.translation import OpenAICompatibleTranslationProvider
        from stable.test_hrn_source_term_translation import fake_translation_response
        self.term(notes='source=manual_review')
        self.term(source_ja='タガノミスト', target_zh='多贺野迷雾', notes='source=manual_review')
        article = NewsArticle(title_ja='アンズアメとタガノミストが出走',
                              body_ja_raw='アンズアメとタガノミストは牝馬です。', source_language='ja')
        provider = OpenAICompatibleTranslationProvider(api_key='test', base_url='https://example.com/v1')
        response = fake_translation_response({'title_zh': '__UMA_KEEP_1__和__UMA_KEEP_2__出赛',
                                              'body_zh': '__UMA_KEEP_1__和__UMA_KEEP_2__是雌马。',
                                              'push_summary_zh': '__UMA_KEEP_1__和__UMA_KEEP_2__出赛'})
        with patch.object(provider, '_request_completion', return_value=response) as request:
            result = provider.translate(article)
        prompt = request.call_args.args[0][1]['content']
        self.assertNotIn('杏饴', prompt)
        self.assertNotIn('多贺野迷雾', prompt)
        self.assertIn('アンズアメ', result.title_zh)
        self.assertIn('タガノミスト', result.title_zh)
        self.assertNotIn('__UMA_KEEP_', result.body_zh)

    def test_historical_report_is_read_only_and_limits_published_fields(self):
        import io, json
        from django.core.management import call_command
        from django.utils import timezone
        from stable.models import NewsArticle, WorkflowStatus
        self.term(notes='source=manual_review')
        article = NewsArticle.objects.create(source_article_id='history', title_ja='原文', title_zh='杏饴出赛',
                                             summary_zh='杏饴', body_zh='正文', published_at=timezone.now(),
                                             workflow_status=WorkflowStatus.PUBLISHED, published_to_web_at=timezone.now())
        output = io.StringIO()
        call_command('report_hkjc_horse_name_impact', stdout=output)
        report = json.loads(output.getvalue())
        self.assertEqual(report['potential_article_count'], 1)
        self.assertEqual({m['field'] for m in report['articles'][0]['matches']}, {'effective_title', 'effective_summary'})
        article.refresh_from_db()
        self.assertEqual(article.title_zh, '杏饴出赛')

    def test_public_profile_pages_hide_overrides_and_pedigree_names(self):
        term = self.term(notes=OFFICIAL)
        profile = HorseProfile.objects.create(primary_term=term, review_status='published',
                                               display_name_zh='不可信人工名', original_name='アンズアメ',
                                               sire_text='不可信父名', dam_text='Original Dam')
        for path in ['/horses/', profile.public_path]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '杏饴')
                self.assertNotContains(response, '不可信人工名')
                self.assertNotContains(response, '不可信父名')
        term.notes = 'source=manual_review'; term.save()
        response = self.client.get(profile.public_path)
        self.assertNotContains(response, '杏饴')
        self.assertContains(response, 'アンズアメ')

    @override_settings(ENGLISH_TERM_CONTEXT_MODE='enforce')
    def test_english_horse_resolution_preserves_unofficial_name(self):
        TermEntry.objects.create(term_type=TermType.HORSE, source_language='en', source_ja='Anzu Ame',
                                 target_zh='杏饴', notes='source=manual_review')
        resolution = resolve_article_entities('Anzu Ame wins the race', 'The filly Anzu Ame won at Tokyo.', source_language='en')
        horses = [entity for entity in resolution.entities if entity.entity_type == 'horse']
        self.assertTrue(horses)
        self.assertTrue(all(entity.needs_preserve and not entity.target_zh for entity in horses))
        self.assertNotIn('杏饴', str(resolution.accepted_terms))

    def test_hkjc_alias_uses_source_evidence_in_two_batch_queries(self):
        from stable.models import TermAlias
        term = self.term(notes=OFFICIAL)
        TermAlias.objects.create(term=term, source_language='en', text='Anzu Ame')
        resolver = StrictRaceTermResolver()
        for _ in range(100):
            resolver.add('Anzu Ame', TermType.HORSE, language='en')
        with self.assertNumQueries(2):
            resolver.resolve()
        self.assertEqual(resolver.field('Anzu Ame', TermType.HORSE, language='en').text, '杏饴')

    @override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=True)
    def test_public_race_result_page_shows_only_verified_chinese_name(self):
        from datetime import date
        from stable.models import RaceEvent, RaceEventResult
        official = self.term(notes=OFFICIAL)
        manual = self.term(source_ja='タガノミスト', target_zh='多贺野迷雾', notes='source=manual_review')
        event = RaceEvent.objects.create(year=2026, slug='hkjc-horse-policy', original_name='Test Race',
                                        country_region='japan', local_date=date(2026, 11, 3), visibility_status='published')
        for index, term in enumerate([official, manual], start=1):
            RaceEventResult.objects.create(event=event, finish_position=index, horse_name=term.source_ja,
                                           is_confirmed=True)
        response = self.client.get(event.public_path)
        self.assertContains(response, '杏饴')
        self.assertContains(response, 'タガノミスト')
        self.assertNotContains(response, '多贺野迷雾')

    @override_settings(TRANSLATION_MODEL='test', TRANSLATION_MAX_ATTEMPTS=1)
    def test_translation_fails_closed_if_model_replaces_protected_horse(self):
        from unittest.mock import patch
        from stable.models import NewsArticle
        from stable.services.translation import OpenAICompatibleTranslationProvider, TranslationResponseError
        from stable.test_hrn_source_term_translation import fake_translation_response
        self.term(notes='source=manual_review')
        article = NewsArticle(title_ja='アンズアメが出走', body_ja_raw='アンズアメは牝馬です。', source_language='ja')
        provider = OpenAICompatibleTranslationProvider(api_key='test', base_url='https://example.com/v1')
        response = fake_translation_response({'title_zh': '杏饴出赛', 'body_zh': '杏饴是雌马。', 'push_summary_zh': '杏饴出赛'})
        with patch.object(provider, '_request_completion', return_value=response):
            with self.assertRaises(TranslationResponseError):
                provider.translate(article)

    @override_settings(TERM_CONSISTENCY_ENABLED=True, TERM_CONSISTENCY_ENFORCE=True)
    def test_publishing_gate_accepts_policy_preserved_original(self):
        from django.utils import timezone
        from stable.models import NewsArticle
        from stable.services.term_consistency import apply_consistency_gate
        self.term(notes='source=manual_review', priority=100)
        article = NewsArticle.objects.create(source_article_id='gate', title_ja='アンズアメが出走',
                                             body_ja_raw='アンズアメは牝馬です。', source_language='ja',
                                             title_zh='アンズアメ出赛', body_zh='アンズアメ是雌马。',
                                             published_at=timezone.now())
        result = apply_consistency_gate(article)
        self.assertTrue(result.passed, result.issues)
        from stable.services.automation import mark_publish_ready
        mark_publish_ready(article)
        article.refresh_from_db()
        self.assertEqual(article.automation_status, 'publish_ready')

    def test_display_policy_does_not_change_existing_horse_scoring_hits(self):
        from stable.models import NewsArticle
        from stable.services.automation import p0_horse_hits
        self.term(notes='source=manual_review', priority=100)
        article = NewsArticle(title_ja='アンズアメが出走', body_ja_raw='アンズアメは牝馬です。', source_language='ja')
        with override_settings(HORSE_NAMES_REQUIRE_HKJC_ENABLED=False):
            baseline = p0_horse_hits(article)
        actual = p0_horse_hits(article)
        self.assertEqual([(hit['source_ja'], hit['priority']) for hit in actual],
                         [(hit['source_ja'], hit['priority']) for hit in baseline])
        self.assertEqual(actual[0]['target_zh'], '')

    def test_raw_chinese_race_names_fall_back_to_identity_or_pending(self):
        self.term(notes='source=manual_review')
        resolver = StrictRaceTermResolver()
        for name in ['杏饴', '无来源中文马名']:
            resolver.add(name, TermType.HORSE)
        resolver.resolve()
        self.assertEqual(resolver.field('杏饴', TermType.HORSE).text, 'アンズアメ')
        self.assertEqual(resolver.field('无来源中文马名', TermType.HORSE).text, '名称待核实')
        with override_settings(RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=False):
            runner = SimpleNamespace(horse_name='杏饴', jockey_name='骑师原文')
            _attach_race_term_display_names([(SimpleNamespace(country_region=''), [runner])])
            self.assertEqual(runner.display_horse_name, 'アンズアメ')
            self.assertEqual(runner.display_jockey_name, '骑师原文')

    def test_raw_official_chinese_and_mixed_unverified_chinese(self):
        self.term(notes=OFFICIAL)
        resolver = StrictRaceTermResolver()
        for name in ['杏饴', '人工马名 (IRE)']:
            resolver.add(name, TermType.HORSE, language='en')
        resolver.resolve()
        self.assertEqual(resolver.field('杏饴', TermType.HORSE, language='en').text, '杏饴')
        self.assertEqual(resolver.field('人工马名 (IRE)', TermType.HORSE, language='en').text, '名称待核实')

    def test_origin_metadata_and_flag_are_bound_to_consistency_snapshot(self):
        from stable.services.term_consistency import _term_snapshot_sha256
        term = self.term(notes=OFFICIAL)
        before = _term_snapshot_sha256()
        term.notes = 'source=manual_review'; term.save()
        self.assertNotEqual(before, _term_snapshot_sha256())
        enabled_snapshot = _term_snapshot_sha256()
        with override_settings(HORSE_NAMES_REQUIRE_HKJC_ENABLED=False):
            self.assertNotEqual(enabled_snapshot, _term_snapshot_sha256())

    def test_output_validation_does_not_accept_unverified_chinese_alias(self):
        from stable.services.validation import _term_preserved
        term = self.term(notes='source=manual_review', aliases_zh=['旧译名'])
        self.assertTrue(_term_preserved(term, 'アンズアメ出赛'))
        self.assertFalse(_term_preserved(term, '杏饴出赛'))
        self.assertFalse(_term_preserved(term, '旧译名出赛'))

    @override_settings(ENGLISH_TERM_CONTEXT_MODE='enforce')
    def test_horse_index_common_word_does_not_become_protected_name(self):
        TermEntry.objects.create(term_type=TermType.HORSE, source_language='en', source_ja='Brilliant',
                                 target_zh='辉煌', notes='source=manual_review')
        resolution = resolve_article_entities('', 'The trainer praised a brilliant performance from the team.', source_language='en')
        matches = [entity for entity in resolution.entities if entity.matched_text.lower() == 'brilliant']
        self.assertTrue(matches)
        self.assertTrue(all(entity.entity_type == 'common_word' and not entity.needs_preserve for entity in matches))

    @override_settings(ENGLISH_TERM_CONTEXT_MODE='enforce')
    def test_conflicting_unofficial_names_keep_the_same_identity_and_score(self):
        from stable.models import NewsArticle
        from stable.services.automation import p0_horse_hits
        for target in ['同名甲', '同名乙']:
            TermEntry.objects.create(term_type=TermType.HORSE, source_language='en', source_ja='Twin Star',
                                     target_zh=target, notes='source=manual_review', priority=100)
        article = NewsArticle(title_ja='Twin Star wins at Ascot',
                              body_ja_raw='The colt Twin Star won the race.', source_language='en')
        with override_settings(HORSE_NAMES_REQUIRE_HKJC_ENABLED=False):
            baseline = p0_horse_hits(article)
        self.assertEqual(baseline, [])
        self.assertEqual(p0_horse_hits(article), baseline)
        resolution = resolve_article_entities(article.title_ja, article.body_ja_raw, source_language='en')
        horses = [entity for entity in resolution.entities if entity.entity_type == 'horse']
        self.assertTrue(horses)
        self.assertTrue(all(entity.term_id is None and entity.needs_preserve for entity in horses))

    def test_historical_report_includes_unverified_alias_of_official_entity(self):
        from django.utils import timezone
        from stable.models import NewsArticle, WorkflowStatus
        from stable.services.horse_name_impact import historical_horse_name_impact
        self.term(notes=OFFICIAL, aliases_zh=['旧译名', '杏饴'])
        article = NewsArticle.objects.create(source_article_id='old-alias', title_ja='アンズアメ',
                                             title_zh='旧译名出赛', body_zh='杏饴', published_at=timezone.now(),
                                             workflow_status=WorkflowStatus.PUBLISHED, published_to_web_at=timezone.now())
        rows = list(historical_horse_name_impact())
        self.assertEqual([row['article_id'] for row in rows], [article.pk])
        self.assertEqual({match['name'] for match in rows[0]['matches']}, {'旧译名'})

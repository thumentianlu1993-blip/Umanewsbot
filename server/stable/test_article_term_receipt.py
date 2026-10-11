"""B107纯codec/SQLite材料/原resolver回归；不覆盖PG step/锁/consumer。"""
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

from django.db import connection
from django.test import TestCase, SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from stable.models import (TermEntry,TermAlias,TermType,SourceLanguage,ExternalHorseAlias,
    RaceEvent,RaceEventRunner,RaceEventResult,ArticleRaceLink,ArticleRaceLinkStatus)
from stable.services import article_term_receipt as receipt, terms, translation_recovery as recovery
from stable.services.term_capture_budget import (CaptureBudget,TermCaptureRefusal,capture_list,
    capture_strings,capture_unique_strings,canonical)
from stable.test_translation_failure_recovery_change import article_for_retry


@override_settings(AUTOMATION_ENABLED=False,ENGLISH_TERM_CONTEXT_MODE='enforce')
class ArticleTermReceiptMaterialTests(TestCase):
    def article(self, *, language='en', title='', body='Blue Horizon won.'):
        return article_for_retry(source_article_id='b107-'+str(uuid4()),source_language=language,
                                 title_ja=title,body_ja_raw=body,body_ja_normalized=body)

    def term(self, name='Blue Horizon', *, language='en', **kwargs):
        return TermEntry.objects.create(source_ja=name,source_language=language,
            term_type=kwargs.pop(
                'term_type',
                TermType.HORSE
            ),target_zh=kwargs.pop(
                'target_zh',
                '蓝色地平线'
            ),**kwargs)

    def view(self, article):
        digest=recovery.translation_input_sha256(article)
        return receipt.source_view(article,{'input_sha256':digest,'source_site':article.source_site,
                                           'source_article_id':article.source_article_id}),digest

    def capture(self, article):
        view,digest=self.view(article)
        return receipt.capture(view,article.pk,digest,timezone.now().isoformat())

    def decode(self, snapshot, article):
        view,digest=self.view(article)
        return receipt.decode(snapshot,view,article.pk,digest)

    def event(self, article):
        event=RaceEvent.objects.create(year=2026,slug='b107-'+str(uuid4()),original_name='B107')
        ArticleRaceLink.objects.create(article=article,event=event,status=ArticleRaceLinkStatus.AUTO)
        return event

    def test_real_sql_projection_alias_and_original_resolution_equivalence(self):
        article=self.article()
        term=self.term(notes='candidate notes',priority=42,aliases_ja=['Horizon'])
        alias=TermAlias.objects.create(term=term,source_language='en',text='Blue Horizon')
        with CaptureQueriesContext(connection) as queries:snapshot=self.capture(article)
        self.assertEqual(len(queries),5)
        self.assertEqual(
            self.decode(
                snapshot,
                article
            ).as_dict(),
            terms.resolve_article_entities_for_article(
                article
            ).as_dict()
        )
        self.assertEqual(
            [
                (
                    x[
                        'kind'
                    ],
                    x[
                        'id'
                    ]
                ) for x in snapshot[
                    'inputs'
                ]
            ],
            [
                (
                    'term',
                    term.pk
                ),
                (
                    'alias',
                    alias.pk
                )
            ]
        )
        sql='\n'.join(q['sql'] for q in queries)
        self.assertIn('LIMIT 129',sql);self.assertIn('LIMIT 65',sql)
        self.assertIn('4097',sql);self.assertIn('_cap_notes',sql)

    def test_no_keys_avoids_dictionary_queries(self):
        article=self.article(language='ja',body='')
        with CaptureQueriesContext(connection) as q:snapshot=self.capture(article)
        self.assertEqual(len(q),0);self.assertEqual(snapshot['inputs'],[])

    def test_three_language_branches_match_original_including_pending_and_notes(self):
        for language,name,body in [
            (
                'en',
                'Blue Horizon',
                'Blue Horizon won.'
            ),
            (
                'ja',
                'ブルーホライズン',
                'ブルーホライズンが勝利した。'
            ),
            (
                'zh',
                '蓝色地平线',
                '蓝色地平线赢了。'
            )
        ]:
            with self.subTest(language=language):
                article=self.article(language=language,body=body)
                self.term(
                    name,
                    language=language,
                    priority=7,
                    notes='original notes',
                    translation_status='pending'
                )
                snapshot=self.capture(article)
                self.assertEqual(
                    self.decode(
                        snapshot,
                        article
                    ).as_dict(),
                    terms.resolve_article_entities_for_article(
                        article
                    ).as_dict()
                )

    def test_non_horse_and_empty_translation_keep_original_classification(self):
        article=self.article(body='There is more than enough time.')
        self.term('More Than Enough',target_zh='',notes='non-horse',term_type=TermType.FIXED_PHRASE)
        self.assertEqual(
            self.decode(
                self.capture(
                    article
                ),
                article
            ).as_dict(),
            terms.resolve_article_entities_for_article(
                article
            ).as_dict()
        )

    def test_external_and_structured_minimum_values_and_deleted_rows_decode_without_sql(self):
        article=self.article(body='Blue Horizon won.')
        external=ExternalHorseAlias.objects.create(
            source_language='en',
            external_horse_id='horse-7',
            name_ja='Blue Horizon',
            normalized_name='Blue Horizon'
        )
        event=self.event(article)
        runner=RaceEventRunner.objects.create(event=event,horse_name='Blue Horizon')
        result=RaceEventResult.objects.create(event=event,horse_name='Blue Horizon',finish_position=1)
        snapshot=self.capture(article)
        before=self.decode(snapshot,article).as_dict()
        self.assertEqual(before,terms.resolve_article_entities_for_article(article).as_dict())
        for item in snapshot['inputs']:
            if item['kind'] in ('runner','result'):
                self.assertEqual(
                    (
                        item[
                            'event_id'
                        ],
                        item[
                            'article_id'
                        ],
                        item[
                            'horse_name_key'
                        ]
                    ),
                    (
                        event.pk,
                        article.pk,
                        'blue horizon'
                    )
                )
        external.delete();runner.delete();result.delete();ArticleRaceLink.objects.all().delete()
        with CaptureQueriesContext(
            connection
        ) as q:self.assertEqual(
            self.decode(
                snapshot,
                article
            ).as_dict(),
            before
        )
        self.assertEqual(len(q),0)

    def test_html_and_excerpt_outside_span_use_full_visible_view(self):
        article=self.article(body='<p>'+('Opening. '*36)+'Blue <b>Horizon</b> won.</p><nav>Menu</nav>')
        self.term()
        snapshot=self.capture(article)
        entity=snapshot['resolution']['entities'][0]
        self.assertGreater(entity['start'],256)
        self.assertEqual(
            self.decode(
                snapshot,
                article
            ).as_dict(),
            terms.resolve_article_entities_for_article(
                article
            ).as_dict()
        )
        bad=deepcopy(snapshot);bad['resolution']['entities'][0]['start']+=3
        with self.assertRaises(TermCaptureRefusal):self.decode(bad,article)

    def test_wrong_types_hash_identity_span_and_extra_schema_fail_closed(self):
        article=self.article();self.term();snapshot=self.capture(article)
        changes=[lambda x:x.update(article_id=True),lambda x:x.update(input_sha256='A'*64),
                 lambda x:x.update(extra='instruction'),lambda x:x['inputs'][0].update(id=True),
                 lambda x:x[
                     'inputs'
                 ][
                     0
                 ].update(
                     row_sha256='bad'
                 ),lambda x:x[
                     'inputs'
                 ].append(
                     deepcopy(
                         x[
                             'inputs'
                         ][
                             0
                         ]
                     )
                 ),
                 lambda x:x['resolution']['entities'][0].update(term_id=99999),
                 lambda x:x['resolution']['entities'][0].update(needs_preserve=1),
                 lambda x:x['resolution']['entities'][0].update(start=1),
                 lambda x:x.update(read_started_at='2026-10-11T00:00:00'),
                 lambda x:x.update(read_started_at='9999-12-31T00:00:00+00:00')]
        for change in changes:
            with self.subTest(change=change):
                bad=deepcopy(snapshot);change(bad)
                with self.assertRaises(TermCaptureRefusal):self.decode(bad,article)
        # updated_at is a DB time, legitimately older than this read interval.
        good=deepcopy(snapshot);good['inputs'][0]['updated_at']='2000-01-01T00:00:00+00:00'
        self.decode(good,article)

    def test_structured_and_external_mapping_tamper_rejects_without_queries(self):
        article=self.article();event=self.event(article)
        RaceEventRunner.objects.create(event=event,horse_name='Blue Horizon')
        ExternalHorseAlias.objects.create(
            source_language='en',
            external_horse_id='h1',
            name_ja='Blue Horizon',
            normalized_name='Blue Horizon'
        )
        snapshot=self.capture(article)
        for key,value in [('event_id',999),('article_id',article.pk+1),('horse_name_key','other horse')]:
            bad=deepcopy(snapshot);next(x for x in bad['inputs'] if x['kind']=='runner')[key]=value
            with CaptureQueriesContext(
                connection
            ) as q, self.assertRaises(
                TermCaptureRefusal
            ):self.decode(
                bad,
                article
            )
            self.assertEqual(len(q),0)
        bad=deepcopy(snapshot);bad['resolution']['entities'][0]['external_horse_ids']=['foreign']
        with self.assertRaises(TermCaptureRefusal):self.decode(bad,article)

    def test_deferred_view_rejects_without_lazy_query(self):
        article=self.article();deferred=type(article).objects.only('pk').get(pk=article.pk)
        expected={
            'input_sha256':recovery.translation_input_sha256(
                article
            ),
            'source_site':article.source_site,
            'source_article_id':article.source_article_id
        }
        with CaptureQueriesContext(
            connection
        ) as q, self.assertRaises(
            TermCaptureRefusal
        ):receipt.source_view(
            deferred,
            expected
        )
        self.assertEqual(len(q),0)

    def test_source_utf8_notes_and_json_limits(self):
        for field,value in [
            (
                'notes',
                'n'*4097
            ),
            (
                'aliases_ja',
                [
                    'name'
                ]*33
            ),
            (
                'aliases_zh',
                [
                    'name'
                ]*33
            ),
            (
                'aliases_ja',
                {
                    'bad':'type'
                }
            ),
            (
                'target_zh',
                '马'*255
            )
        ]:
            with self.subTest(field=field):
                article=self.article();term=self.term(**{field:value})
                if field=='target_zh':
                    self.capture(article) # 765 UTF8 bytes is legal.
                else:
                    with self.assertRaises(TermCaptureRefusal):self.capture(article)
                term.delete()
        for title,body in [('马'*342,'short'),('','马'*2731)]:
            with self.assertRaisesRegex(TermCaptureRefusal,'read_terms_limit'):
                self.capture(self.article(title=title,body=body))

    def test_term_alias_external_runner_result_sql_sentinels_stop_later_selects(self):
        for kind,limit in receipt.LIMITS.items():
            with self.subTest(kind=kind):
                TermEntry.objects.all().delete();ExternalHorseAlias.objects.all().delete();RaceEvent.objects.all().delete()
                article=self.article();event=None
                if kind=='term':
                    TermEntry.objects.bulk_create(
                        [
                            TermEntry(
                                source_ja='Blue Horizon',
                                source_language='en',
                                term_type='horse'
                            ) for _ in range(
                                limit+1
                            )
                        ]
                    )
                elif kind=='alias':
                    owners=TermEntry.objects.bulk_create(
                        [
                            TermEntry(
                                source_ja='owner'+str(
                                    i
                                ),
                                source_language='en'
                            ) for i in range(
                                limit+1
                            )
                        ]
                    )
                    TermAlias.objects.bulk_create(
                        [
                            TermAlias(
                                term=t,
                                source_language='en',
                                text='Blue Horizon'
                            ) for t in owners
                        ]
                    )
                elif kind=='external_alias':
                    ExternalHorseAlias.objects.bulk_create(
                        [
                            ExternalHorseAlias(
                                source_language='en',
                                external_horse_id=str(
                                    i
                                ),
                                name_ja='Blue Horizon',
                                normalized_name='Blue Horizon'
                            ) for i in range(
                                limit+1
                            )
                        ]
                    )
                else:
                    event=self.event(article);model=RaceEventRunner if kind=='runner' else RaceEventResult
                    model.objects.bulk_create(
                        [
                            model(
                                event=event,
                                horse_name='Blue Horizon',
                                **(
                                    {
                                        'finish_position':str(
                                            i
                                        )
                                    } if kind=='result' else {}
                                )
                            ) for i in range(
                                limit+1
                            )
                        ]
                    )
                with CaptureQueriesContext(
                    connection
                ) as q, self.assertRaisesRegex(
                    TermCaptureRefusal,
                    'read_terms_limit'
                ):self.capture(
                    article
                )
                self.assertEqual(len(q),{'alias':1,'term':2,'external_alias':3,'runner':4,'result':5}[kind])
                self.assertIn('LIMIT '+str(limit+1),q[-1]['sql'])

    def test_forty_same_span_two_targets_are_merged_before_final_receipt_limit(self):
        article=self.article()
        TermEntry.objects.bulk_create(
            [
                TermEntry(
                    source_ja='Blue Horizon',
                    source_language='en',
                    term_type='horse',
                    target_zh='甲' if i%2 else '乙'
                ) for i in range(
                    40
                )
            ]
        )
        expected=terms.resolve_article_entities_for_article(article).as_dict()
        # Genuine ORM material reaches the unmodified algorithm; observer does not replace results.
        from unittest.mock import patch
        actual=[];original=terms.resolve_article_entities
        def observe(*args,**kwargs):
            value=original(*args,**kwargs);actual.append(value.as_dict());return value
        with patch.object(terms,'resolve_article_entities',side_effect=observe):
            try:self.capture(article)
            except TermCaptureRefusal as exc:self.assertEqual(
                str(
                    exc
                ),
                'read_terms_limit'
            ) # 40 manifests may exceed8192.
        self.assertEqual(actual,[expected]);self.assertEqual(len(actual[0]['entities']),1)

    def test_projection_input_total_rejects_before_row_append(self):
        self.term()
        budget=CaptureBudget();budget.projection_bytes=512*1024
        with CaptureQueriesContext(
            connection
        ) as q, self.assertRaisesRegex(
            TermCaptureRefusal,
            'read_terms_limit'
        ):
            receipt._project(
                TermEntry.objects.all(),
                'term',
                [
                    'id',
                    'updated_at'
                ],
                {
                    'source_ja':255
                },
                budget=budget
            )
        self.assertEqual(len(q),1);self.assertEqual(budget.collections,0)

    def test_shared_external_identity_is_allowed_but_input_row_id_duplicate_is_not(self):
        article=self.article()
        for source in ('netkeiba','jbis'):
            ExternalHorseAlias.objects.create(
                source=source,
                source_language='en',
                external_horse_id='shared',
                name_ja='Blue Horizon',
                normalized_name='Blue Horizon'
            )
        snapshot=self.capture(article);self.decode(snapshot,article)
        self.assertEqual(len(snapshot['inputs']),2)
        snapshot['inputs'].append(deepcopy(snapshot['inputs'][0]))
        with self.assertRaises(TermCaptureRefusal):self.decode(snapshot,article)

    def test_protected_people_and_suppressed_language_branches_keep_original(self):
        fixtures=[('en','Irad Ortiz Jr. said Blue Horizon won.','Irad Ortiz Jr.','Blue Horizon'),
                  ('ja','ジョン・スミス騎手がブルーホライズンを騎乗。','ジョン・スミス','スミス'),
                  ('zh','蓝色地平线和地平线','蓝色地平线','地平线')]
        for language,body,person,other in fixtures:
            with self.subTest(language=language):
                article=self.article(language=language,body=body)
                self.term(person,language=language,term_type=TermType.JOCKEY)
                self.term(other,language=language)
                index=terms._build_article_entity_index([(language,body)])
                plain=terms.resolve_article_entities('',body,source_language=language,preloaded_index=index)
                budget=CaptureBudget()
                captured=terms.resolve_article_entities(
                    '',
                    body,
                    source_language=language,
                    preloaded_index=index,
                    capture_budget=budget
                )
                self.assertEqual(captured.as_dict(),plain.as_dict());self.assertGreater(budget.collections,0)
                self.assertGreater(budget.objects,0)



class ArticleTermCaptureBudgetTests(SimpleTestCase):
    def test_middle_256_objects_and_final_32_are_separate(self):
        budget=CaptureBudget()
        for i in range(256):terms._make_entity('term','x','body',0,1,capture_budget=budget)
        self.assertEqual(budget.objects,256)
        with self.assertRaisesRegex(TermCaptureRefusal,'read_terms_limit'):
            terms._make_entity('term','x','body',0,1,capture_budget=budget)
        self.assertEqual(budget.objects,256)

    def test_list65_and_string1025_fail_before_growth_even_for_duplicates(self):
        for field in ('external_horse_ids','evidence','entity_evidence','conflict_flags'):
            with self.subTest(field=field):
                budget=CaptureBudget();entity=terms._make_entity('term','x','body',0,1,capture_budget=budget)
                values=getattr(entity,field)
                for _ in range(64):values.append('x')
                with self.assertRaises(TermCaptureRefusal):values.append('x')
                self.assertEqual(len(values),64)
        budget=CaptureBudget()
        with self.assertRaises(TermCaptureRefusal):capture_unique_strings(('x' for _ in range(1025)),budget)
        self.assertEqual(budget.strings,1024)

    def test_collection_and_string_and_total_bytes_fail_before_growth(self):
        budget=CaptureBudget();values=capture_list(budget=budget)
        for _ in range(1024):values.append('')
        with self.assertRaises(TermCaptureRefusal):values.append('')
        self.assertEqual(len(values),1024)
        budget=CaptureBudget();values=capture_strings(budget=budget)
        with self.assertRaises(TermCaptureRefusal):values.append('x'*1025)
        self.assertEqual(values,[])
        for category in ('object','collection','string'):
            budget=CaptureBudget();setattr(budget,category+'_bytes',128*1024)
            with self.assertRaises(TermCaptureRefusal):budget.charge(category,'x')
        budget=CaptureBudget();budget.object_bytes=128*1024;budget.collection_bytes=128*1024
        with self.assertRaises(TermCaptureRefusal):budget.charge('string','x')

    def test_raw_keys129_variants257_and_other_language_streaming(self):
        from unittest.mock import patch
        for values in [('en',[str(i) for i in range(129)]),('zh',[str(i) for i in range(129)])]:
            language,keys=values
            with patch.object(
                terms,
                '_iter_entity_candidate_keys',
                return_value=iter(
                    keys
                )
            ), self.assertRaises(
                TermCaptureRefusal
            ):
                receipt._keys('',language,CaptureBudget())
        with patch.object(
            terms,
            '_iter_entity_candidate_keys',
            return_value=iter(
                [
                    'x'
                ]
            )
        ), patch.object(
            terms,
            '_term_query_key_variants',
            return_value=(
                str(
                    i
                ) for i in range(
                    257
                )
            )
        ), self.assertRaises(
            TermCaptureRefusal
        ):
            receipt._keys('','en',CaptureBudget())

    def test_frozen_codec_builtin_types_and_final_collections(self):
        # Actual resolution dataclasses, then strict primitive schema, no fabricated provider result.
        view=SimpleNamespace(source_site='tdn',source_article_id='pure',source_language='zh',
                             title_ja='',body_ja_raw='星河 '*33,body_ja_normalized='星河 '*33)
        entry=SimpleNamespace(id=1,source_ja='星河',target_zh='星河',term_type='horse',priority=0,
                              race_grade='',notes='',has_translation=True)
        index=terms.ArticleEntityIndex({'zh':[entry]},{'zh':{1:['星河']}},{'zh':[]},{'zh':set()})
        budget=CaptureBudget()
        result=terms.resolve_article_entities(
            '',
            view.body_ja_raw,
            source_language='zh',
            preloaded_index=index,
            capture_budget=budget
        )
        self.assertEqual(len(result.entities),33);self.assertLessEqual(budget.objects,256)
        snapshot={'schema':receipt.SCHEMA,'article_id':1,'input_sha256':recovery.translation_input_sha256(view),
                  'source_language':'zh','read_started_at':timezone.now().isoformat(),'read_finished_at':timezone.now().isoformat(),
                  'inputs':[
                      {
                          'kind':'term',
                          'id':1,
                          'updated_at':timezone.now().isoformat(),
                          'row_sha256':'a'*64
                      }
                  ],
                  'resolution':receipt.serialize_resolution(result)}
        with self.assertRaisesRegex(TermCaptureRefusal,'read_terms_limit'):
            receipt.decode(snapshot,view,1,snapshot['input_sha256'])
        class CustomList(list):pass
        snapshot['inputs']=CustomList(snapshot['inputs'])
        with self.assertRaisesRegex(TermCaptureRefusal,'read_terms_invalid'):
            receipt.decode(snapshot,view,1,snapshot['input_sha256'])

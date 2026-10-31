"""隔离模型回执的组合测试；合成 fixture 不作为真实 gold/自然周验收。"""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import json
import re

from django.conf import settings
from django.test import TransactionTestCase
from django.utils import timezone

from stable.adapters.base import CanonicalNewsDraft
from stable.models import NewsSource, NewsPublicationReceipt, NewsProcessingRun
from stable.services.ingestion import upsert_article_from_draft
from stable.services.news_pipeline import process_news_run, submit_manual_target
from stable.services.news_content import AUDIT_CHECKS
from stable.test_p01_news_budget import POLICY


def workflow_policy(source_id):
    result = deepcopy(POLICY)
    model = {**result["models"]["entity_check"], "quality_tier": "strong", "max_input_bytes": 100000}
    result.update(source_ids=[source_id], activated_at=(timezone.now() - timedelta(hours=1)).isoformat(),
        models={key: dict(model) for key in ("event_classify", "entity_check", "translate_full", "fact_audit", "body_review")})
    return result


def workflow_draft(value="27"):
    return CanonicalNewsDraft(source_site="france_galop_news", source_mode="official", source_article_id="fixture-policy",
        source_url="https://fixture.invalid/doc/D42", title_ja="Official prize update",
        body_ja_raw=f"Authority jurisdiction ZZ published document D42.\n\nThe prize is {value}.",
        body_ja_normalized=f"Authority jurisdiction ZZ published document D42.\n\nThe prize is {value}.",
        original_content_html=f'<div class="field--name-body"><p>Authority jurisdiction ZZ published document D42.</p><p>The prize is {value}.</p></div>',
        published_at=timezone.now(), images=[], racing_region="france", source_language="en",
        metadata={"published_at_verified": True, "published_at_evidence": {"source": "fixture"}})


class WorkflowFixture:
    def setUp(self):
        # 模型 fixture 使用单调合成时钟，隔离模拟器宿主时钟的短时回拨。
        from itertools import count
        base, ticks = timezone.now(), count()
        clock = patch("django.utils.timezone.now", side_effect=lambda: base + timedelta(milliseconds=next(ticks)))
        clock.start()
        self.addCleanup(clock.stop)
        self.source = NewsSource.objects.create(name="P01 fixture", source_site="france_galop_news", source_mode="official", adapter_key="france_galop_news", racing_region="france", source_language="en", production_approved=True, enabled=True)
        self.override = self.settings(NEWS_QUALITY_MODE="shadow", NEWS_QUALITY_POLICY=workflow_policy(self.source.pk))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.article = upsert_article_from_draft(workflow_draft()).article
        self.run = self.article.active_news_run
        self.assertIsNotNone(self.run)
        self.audit_fails = False
        self.calls = []
        self.provider = patch("stable.services.news_model_gateway._single_request", side_effect=self.fake_response)
        self.provider.start()
        self.addCleanup(self.provider.stop)

    def fake_response(self, attempt, payload):
        self.calls.append(attempt.stage)
        source = payload["source"]
        if attempt.stage == "event_classify":
            text = source["blocks"][0]["text"]
            fields = {"organization": "Authority", "jurisdiction": "ZZ", "document_id": "D42"}
            evidence = {key: {"block_id": "b0", "start": text.index(value), "end": text.index(value) + len(value)} for key, value in fields.items()}
            value = re.search(r"\d+", source["blocks"][1]["text"])[0]
            candidates = payload.get("candidates", [])
            candidate = candidates[0] if candidates else None
            prior = next((f for f in candidate["facts"] if f["object"] == value), None) if candidate else None
            data = {"priority": "regional", "primary_region": "france", "reason": "官方奖金规则调整",
                "identity": {"kind": "policy", "fields": fields, "evidence": evidence},
                "comparison": {"event_id": candidate["id"] if candidate else None, "version": candidate["version"] if candidate else 0},
                "facts": [{"subject_ref": "prize", "predicate": "amount", "object": value, "effective_time": "", "modality": "happened", "source_span": {"block_id": "b1", "start": 0, "end": len(source["blocks"][1]["text"])}, "importance": "major", "relation": "repeated" if prior else "new", "prior_fact_ids": [prior["id"]] if prior else []}]}
        elif attempt.stage == "entity_check":
            data = {"coverage": "complete", "entities": [{"block_id": "b0", "start": 0, "end": 9, "text": "Authority", "type": "organization"}]}
        elif attempt.stage == "translate_full":
            token = source["blocks"][0]["text"].split(" jurisdiction")[0]
            value = re.search(r"\d+", source["blocks"][1]["text"])[0]
            data = {"title": "奖金调整公告", "summary": "官方调整奖金", "blocks": [{"id": "b0", "text": f"{token}在ZZ发布文件D42。"}, {"id": "b1", "text": f"奖金为{value}。"}]}
        elif attempt.stage == "fact_audit":
            data = {"verdict": "fail" if self.audit_fails else "pass", "checks": {key: not self.audit_fails for key in AUDIT_CHECKS}, "issues": []}
        else:
            raise AssertionError(attempt.stage)
        return SimpleNamespace(id="fixture-" + str(attempt.pk), choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data), tool_calls=None))], usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20))

    def finish(self, run=None):
        run = run or self.run
        for _ in range(15):
            process_news_run(run.pk)
            run.refresh_from_db()
            if run.state in {"shadow", "published", "review", "rejected", "duplicate", "stale"}:
                break
        return run



class WorkflowTests(WorkflowFixture, TransactionTestCase):
    def test_complete_shadow_pipeline_has_strong_receipts_and_full_text(self):
        run = self.finish()
        self.assertEqual(run.state, "shadow", run.reason)
        self.assertEqual(self.calls, ["event_classify", "entity_check", "translate_full", "fact_audit"])
        self.assertEqual(run.translation_snapshot["body"], "Authority在ZZ发布文件D42。\n\n奖金为27。")
        self.assertTrue(run.quality_snapshot["passed"])
        self.assertFalse(NewsPublicationReceipt.objects.exists())

    def test_only_one_repair_round_then_manual_review(self):
        self.audit_fails = True
        run = self.finish()
        self.assertEqual(run.state, "review")
        self.assertEqual(run.repair_count, 1)
        self.assertEqual(self.calls.count("translate_full"), 2)
        self.assertEqual(self.calls.count("fact_audit"), 2)
        self.assertFalse(NewsPublicationReceipt.objects.exists())

    def test_manual_target_is_audited_exactly_without_translation(self):
        from django.contrib.auth import get_user_model
        editor = get_user_model().objects.create_user("manual-editor")
        manual = {"title_zh": "人工奖金公告", "summary_zh": "官方调整奖金", "body_zh": "Authority在ZZ发布文件D42，奖金为27。"}
        run = submit_manual_target(self.article, manual, editor=editor)
        self.finish(run)
        self.assertEqual(run.state, "shadow", run.reason)
        self.assertNotIn("translate_full", self.calls)
        self.assertEqual(run.translation_snapshot["body"], manual["body_zh"])


class ContextWorkflowTests(WorkflowFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        from stable.test_p01_news_budget import context_policy
        from stable.services.news_pipeline import policy_sha
        value = workflow_policy(self.source.pk)
        value.update(context_policy())
        value['article_cap'] = '1'
        override = self.settings(NEWS_QUALITY_POLICY=value)
        override.enable()
        self.addCleanup(override.disable)
        from stable.services.news_pipeline import start_revision
        self.run = start_revision(self.article)
        self.audit_count = 0
        self.translation_count = 0
        self.first_bad_number = False
        self.first_uncertain = False
        self.profiles = []

    def fake_response(self, attempt, payload):
        response = super().fake_response(attempt, payload) if payload.get('mode') != 'repair_blocks' else None
        if response is None:
            self.calls.append(attempt.stage)
            data = {'base_raw_sha': payload['base_raw_sha'], 'replacements': [{'id': 'b1', 'text': '奖金为27。'}]}
            response = SimpleNamespace(id='patch', choices=[SimpleNamespace(message=SimpleNamespace(content='', tool_calls=None))], usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20))
        else:
            data = json.loads(response.choices[0].message.content)
        if attempt.stage == 'entity_check':
            data['entities'] = [{'block_id': 'b0', 'text': 'Authority', 'type': 'organization', 'context': 'Authority jurisdiction ZZ'}]
        if attempt.stage == 'translate_full':
            self.translation_count += 1
            if self.first_bad_number and self.translation_count == 1:
                data['blocks'][1]['text'] = '奖金为28。'
        if attempt.stage == 'fact_audit':
            self.audit_count += 1
            self.profiles.append(attempt.usage['price'].get('profile'))
            if self.first_uncertain and self.audit_count == 1:
                data.update(verdict='uncertain', issues=[{'kind': 'numbers_units',
                    'source': {'block_id': 'b1', 'quote': '27', 'context': 'The prize is 27.'},
                    'target': {'block_id': 'b1', 'quote': '27', 'context': '奖金为27。'}, 'missing': False}])
        response.choices[0].message.content = json.dumps(data)
        response.choices[0].finish_reason = 'stop'
        return response

    def test_v2_complete_and_publication_revalidates_context(self):
        from stable.services.news_publication import check_publication_evidence
        run = self.finish()
        self.assertEqual(run.state, 'shadow', run.reason)
        self.assertEqual(run.entity_snapshot['occurrences'][0]['context'], 'Authority jurisdiction ZZ')
        check_publication_evidence(run)
        run.entity_snapshot['occurrences'][0]['context'] = 'invented'
        with self.assertRaises(ValueError):
            check_publication_evidence(run)

    def test_hard_failure_repairs_one_block_before_first_full_audit(self):
        self.first_bad_number = True
        run = self.finish()
        self.assertEqual(run.state, 'shadow', run.reason)
        self.assertEqual((self.translation_count, self.audit_count, run.repair_count), (2, 1, 1))
        patch_attempt = run.attempts.filter(stage='translate_full').last()
        self.assertEqual(patch_attempt.usage['input']['required_block_ids'], ['b1'])
        from stable.services.news_publication import check_publication_evidence
        check_publication_evidence(run)

    def test_valid_uncertain_upgrades_once_without_translation_repair(self):
        self.first_uncertain = True
        run = self.finish()
        self.assertEqual(run.state, 'shadow', run.reason)
        self.assertEqual(self.profiles, ['base', 'deep'])
        self.assertEqual(run.repair_count, 0)

    def test_manual_revision_reuses_only_paid_entities_without_new_charge(self):
        from stable.services.news_pipeline import start_revision
        from stable.services.news_publication import check_publication_evidence
        first = self.finish()
        self.assertEqual(first.state, 'shadow', first.reason)
        before = self.calls.count('entity_check')
        target = {key: first.translation_snapshot[key] for key in ('title', 'body', 'summary')}
        revised = start_revision(self.article, snapshot=first.source_snapshot, manual_target=target)
        revised = self.finish(revised)
        self.assertEqual(revised.state, 'shadow', revised.reason)
        self.assertEqual(self.calls.count('entity_check'), before)
        cached = revised.attempts.get(stage='entity_check')
        self.assertEqual(cached.provider, 'cache')
        self.assertFalse(cached.month_budget_id)
        self.assertEqual(cached.actual_cost, 0)
        self.assertEqual(cached.usage['cache_origin'], first.entity_snapshot['strong_attempt_id'])
        check_publication_evidence(revised)

    def test_invalid_or_truncated_response_is_not_audited_or_retried(self):
        original = self.fake_response
        def truncated(attempt, payload):
            response = original(attempt, payload)
            response.choices[0].finish_reason = 'length'
            return response
        self.provider.stop()
        with patch('stable.services.news_model_gateway._single_request', side_effect=truncated):
            run = self.finish()
        self.assertEqual(run.state, 'review')
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(run.attempts.get().actual_cost > 0)
        self.assertEqual(run.attempts.get().state, 'failed')

    def test_high_risk_article_requires_deep_final_audit(self):
        from stable.services.news_pipeline import start_revision
        snapshot = deepcopy(self.run.source_snapshot)
        snapshot['title'] += ' after retirement'
        self.run = start_revision(self.article, snapshot=snapshot)
        run = self.finish()
        self.assertEqual(run.state, 'shadow', run.reason)
        self.assertEqual(self.profiles, ['deep'])

    def test_missing_block_uses_one_full_repair_then_final_audit(self):
        original = self.fake_response
        def missing(attempt, payload):
            response = original(attempt, payload)
            if attempt.stage == 'translate_full' and self.translation_count == 1:
                value = json.loads(response.choices[0].message.content)
                value['blocks'].pop()
                response.choices[0].message.content = json.dumps(value)
            return response
        self.provider.stop()
        with patch('stable.services.news_model_gateway._single_request', side_effect=missing):
            run = self.finish()
        self.assertEqual(run.state, 'shadow', run.reason)
        self.assertEqual((run.repair_count, self.translation_count, self.audit_count), (1, 2, 1))
        from stable.services.news_publication import check_publication_evidence
        check_publication_evidence(run)

    def test_cache_cannot_bypass_unknown_budget(self):
        from stable.models import NewsModelBudget
        from stable.services.news_pipeline import start_revision
        first = self.finish()
        self.assertEqual(first.state, 'shadow')
        before = len(self.calls)
        NewsModelBudget.objects.all().update(state='blocked_unknown')
        revised = start_revision(self.article, snapshot=first.source_snapshot,
            manual_target={key: first.translation_snapshot[key] for key in ('title', 'body', 'summary')})
        revised = self.finish(revised)
        self.assertEqual(revised.state, 'review')
        self.assertEqual(revised.reason, 'unreconciled_bill')
        self.assertEqual(len(self.calls), before)

    def test_deep_uncertain_stops_without_second_upgrade_or_repair(self):
        original = self.fake_response
        def uncertain(attempt, payload):
            if attempt.stage == 'fact_audit':
                self.audit_count = 0
                self.first_uncertain = True
            return original(attempt, payload)
        self.provider.stop()
        with patch('stable.services.news_model_gateway._single_request', side_effect=uncertain):
            run = self.finish()
        self.assertEqual(run.state, 'review')
        self.assertEqual(run.reason, 'deep_uncertain')
        self.assertEqual(self.profiles, ['base', 'deep'])
        self.assertEqual(run.repair_count, 0)

    def test_report_distinguishes_cache_hits_and_unknown_reservation(self):
        from stable.services.news_pipeline import start_revision
        from stable.services.news_quality_report import build_report
        first = self.finish()
        revised = start_revision(self.article, snapshot=first.source_snapshot,
            manual_target={key: first.translation_snapshot[key] for key in ('title', 'body', 'summary')})
        self.finish(revised)
        end = timezone.now() + timedelta(hours=1)
        with patch('stable.services.news_quality_report.timezone.now', return_value=end):
            report = build_report(start=end-timedelta(days=1), end=end)
        self.assertEqual(report['cost']['cache_hits'], 1)
        self.assertEqual(report['cost']['requests'], len(self.calls))
        self.assertEqual(Decimal(report['cost']['unknown_reserved']), 0)

    def test_body_and_entity_cache_survive_new_body_receipt_id(self):
        from stable.services.news_pipeline import start_revision
        from stable.services.news_publication import check_publication_evidence
        snapshot = deepcopy(self.run.source_snapshot)
        snapshot['html'] = snapshot['html'].replace('</div>', '<p>Subscribe for more.</p></div>')
        self.run = start_revision(self.article, snapshot=snapshot)
        original = self.fake_response
        def body_response(attempt, payload):
            if attempt.stage != 'body_review':
                return original(attempt, payload)
            self.calls.append('body_review')
            data = {'decisions': [{'id': 'b2', 'decision': 'remove', 'reason': '模板订阅按钮'}]}
            return SimpleNamespace(id='body', choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
                content=json.dumps(data), tool_calls=None))], usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20))
        self.provider.stop()
        with patch('stable.services.news_model_gateway._single_request', side_effect=body_response):
            first = self.finish()
            self.assertEqual(first.state, 'shadow', first.reason)
            revised = start_revision(self.article, snapshot=snapshot,
                manual_target={key: first.translation_snapshot[key] for key in ('title', 'body', 'summary')})
            revised = self.finish(revised)
        self.assertEqual(revised.state, 'shadow', revised.reason)
        self.assertEqual(self.calls.count('body_review'), 1)
        self.assertEqual(self.calls.count('entity_check'), 1)
        self.assertEqual(revised.attempts.filter(provider='cache').count(), 2)
        self.assertNotEqual(first.clean_snapshot['body_review_attempt_id'], revised.clean_snapshot['body_review_attempt_id'])
        check_publication_evidence(revised)

    def test_verified_event_kind_requires_deep_without_english_keyword(self):
        from stable.services.news_pipeline import required_profile
        run = SimpleNamespace(stage='fact_audit', clean_snapshot={'title': '右前脚の屈腱炎を発症', 'blocks': []},
            editorial_snapshot={'identity': {'kind': 'injury'}}, quality_snapshot={})
        self.assertEqual(required_profile(run), 'deep')
        run.editorial_snapshot['identity']['kind'] = 'retirement'
        self.assertEqual(required_profile(run), 'deep')

    def test_invalid_entity_result_is_not_reused_by_manual_revision(self):
        from stable.services.news_pipeline import start_revision
        original = self.fake_response
        def uncertain(attempt, payload):
            response = original(attempt, payload)
            if attempt.stage == 'entity_check':
                data = json.loads(response.choices[0].message.content)
                data['coverage'] = 'uncertain'
                response.choices[0].message.content = json.dumps(data)
            return response
        self.provider.stop()
        with patch('stable.services.news_model_gateway._single_request', side_effect=uncertain):
            first = self.finish()
        self.assertEqual(first.state, 'review')
        before = self.calls.count('entity_check')
        revised = start_revision(self.article, snapshot=first.source_snapshot,
            manual_target={'title': '公告', 'summary': '奖金公告', 'body': 'Authority在ZZ发布文件D42，奖金为27。'})
        with patch('stable.services.news_model_gateway._single_request', side_effect=original):
            self.finish(revised)
        self.assertEqual(self.calls.count('entity_check'), before + 1)
        self.assertEqual(revised.attempts.get(stage='entity_check').provider, 'openai')

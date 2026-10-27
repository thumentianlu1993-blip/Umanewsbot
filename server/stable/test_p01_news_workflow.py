"""隔离模型回执的组合测试；合成 fixture 不作为真实 gold/自然周验收。"""
from copy import deepcopy
from datetime import timedelta
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

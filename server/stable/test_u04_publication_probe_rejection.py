"""D062 K2：冻结 v7 对新增可见发布时间的单方法负控；源码准备，未执行。

baseline 来自独立已审 fixture；仅改 HTML，不生成或改签 context/expected。
输入摘要仅用于诊断，不写回 adapter 入参，也不提供 K3 或实际 GET 认证。
"""
from copy import deepcopy
import hashlib
import json

from django.test import SimpleTestCase, override_settings

from stable.services.public_probe_template_adapter import parse_template_render
from stable.testing_public_probe.settings import TEMPLATE_TEST_SETTINGS
from stable.testing_public_probe.support import SourceDOM, adapter_inputs, approved_cases


CASE_ID = "P-official-old-detail-strict_display_v1"
PUBLICATION_P = '<p class="muted">赛果发布于2026-07-21 04:15（北京时间）</p>'


@override_settings(**TEMPLATE_TEST_SETTINGS)
class U04PublicationProbeRejectionTests(SimpleTestCase):
    databases = set()

    def test_visible_publication_time_is_unmodeled_under_frozen_v7(self):
        document = approved_cases()
        cases = [c for c in document["positive_and_missing_cases"] if c["case_id"] == CASE_ID]
        self.assertEqual(len(cases), 1, "前件：原批准 case 必须唯一存在")
        case = cases[0]
        inputs = adapter_inputs(document, case)
        frozen = deepcopy(inputs)
        non_html = {key: value for key, value in frozen.items() if key != "html"}
        self.assertEqual(inputs["private"]["template_context"]["live_result_status"], {"is_stale": False})

        # 逐参数摘要包含原 bytes；JSON 参数仅规范化作诊断，不作为新的绑定。
        baseline_hashes = {
            key: hashlib.sha256(
                value if isinstance(value, bytes) else json.dumps(
                    value, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            for key, value in frozen.items()
        }
        baseline = parse_template_render(**inputs)
        print(json.dumps({
            "k2_stage": "baseline", "case_id": CASE_ID,
            "argument_sha256": baseline_hashes,
            "leaf_status": baseline["leaf_status"], "reason": baseline["reason"],
            "body_digest": baseline.get("body_digest"),
            "receipt_constructed": baseline["receipt"] is not None,
            "c013_status": baseline["c013_status"],
        }, ensure_ascii=False, sort_keys=True), flush=True)
        self.assertEqual(inputs, frozen, "前件：baseline 调用不得改写任何输入")
        self.assertEqual(baseline["leaf_status"], "template_fixture_verified")
        self.assertEqual(baseline["reason"], "matching_template_fixture_only")
        self.assertIsNone(baseline["priority_rank"])
        self.assertEqual(baseline["body"], case["expected_body"])
        self.assertEqual(baseline["body_digest"], case["expected_body_sha256"])
        self.assertIsNotNone(baseline["receipt"])
        self.assertEqual(baseline["receipt"]["body_digest"], case["expected_body_sha256"])
        self.assertEqual(baseline["c013_status"], "public_read_verified")
        self.assertIs(baseline["comparison"]["public_read_verified"], True)

        source = SourceDOM(frozen["html"])
        hero = source.one(tag="section", cls="race-hero")
        # closing_start 是 Unicode 字符位置；必须用既有 replace 的字符接口。
        at = hero.closing_start
        self.assertEqual(source.source[at:at + len("</section>")], "</section>")
        prefix = source.source[:at].encode("utf-8")
        suffix = source.source[at:].encode("utf-8")
        insertion = PUBLICATION_P.encode("utf-8")
        self.assertEqual(prefix + suffix, frozen["html"])
        self.assertEqual(frozen["html"].count(insertion), 0)
        mutant_html = source.replace([(at, at, PUBLICATION_P)])
        self.assertEqual(mutant_html, prefix + insertion + suffix)
        self.assertEqual(mutant_html.count(insertion), 1)
        self.assertEqual(mutant_html[:len(prefix)], prefix)
        self.assertEqual(mutant_html[len(prefix) + len(insertion):], suffix)
        self.assertEqual(
            mutant_html[:len(prefix)] + mutant_html[len(prefix) + len(insertion):],
            frozen["html"],
        )

        mutated = SourceDOM(mutant_html)
        mutated_hero = mutated.one(tag="section", cls="race-hero")
        paragraphs = [
            node for node in mutated.select(tag="p", cls="muted")
            if mutated.source[node.start:node.end] == PUBLICATION_P
        ]
        self.assertEqual(len(paragraphs), 1)
        self.assertEqual(paragraphs[0].attrs, {"class": "muted"})
        self.assertLessEqual(mutated_hero.opening_end, paragraphs[0].start)
        self.assertLessEqual(paragraphs[0].end, mutated_hero.closing_start)

        negative_inputs = deepcopy(frozen)
        negative_inputs["html"] = mutant_html
        self.assertEqual({key: value for key, value in negative_inputs.items() if key != "html"}, non_html)
        negative_frozen = deepcopy(negative_inputs)
        negative_hashes = {
            key: hashlib.sha256(
                value if isinstance(value, bytes) else json.dumps(
                    value, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            for key, value in negative_frozen.items()
        }
        self.assertEqual(
            {key: value for key, value in negative_hashes.items() if key != "html"},
            {key: value for key, value in baseline_hashes.items() if key != "html"},
        )
        self.assertNotEqual(negative_hashes["html"], baseline_hashes["html"])
        result = parse_template_render(**negative_inputs)
        print(json.dumps({
            "k2_stage": "visible_time_negative", "case_id": CASE_ID,
            "argument_sha256": negative_hashes, "result": result,
        }, ensure_ascii=False, sort_keys=True), flush=True)
        self.assertEqual(inputs, frozen, "负控调用也不得改写原 baseline 输入")
        self.assertEqual(negative_inputs, negative_frozen, "负控调用不得改写任何参数")
        self.assertEqual({key: value for key, value in negative_inputs.items() if key != "html"}, non_html)
        self.assertEqual(result, {
            "leaf_status": "unverified", "reason": "unmodeled_visible_content",
            "priority_rank": 4, "body": None, "receipt": None,
            "c013_status": "not_constructed", "synthetic_only": True,
            "real_origin_verified": False, "real_permission_verified": False,
            "complete_original_scope": False, "sla": "unverified",
        })

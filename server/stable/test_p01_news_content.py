"""T01–T07/T25：全文、引语表格、严格实体跨度与事实审校。"""
from copy import deepcopy

from django.test import SimpleTestCase
from stable.services.news_editorial import validate_editorial
from stable.services.news_content import (
    AUDIT_CHECKS, ContentBlocked, clean_source, validate_entities, protect_source,
    restore_translation, validate_audit,
)

CLEAN = {"title": "Official update", "source_sha": "a" * 64, "clean_sha": "b" * 64,
    "blocks": [{"id": "b0", "text": "Unknown Horse will race on 27 October."}, {"id": "b1", "text": "The trainer said this is a plan."}]}
ENTITY = {"block_id": "b0", "start": 0, "end": 13, "text": "Unknown Horse", "type": "horse"}


class NewsContentTests(SimpleTestCase):
    def test_fixed_prompts_fit_existing_request_envelope_allowance(self):
        from stable.services.news_prompts import PROMPTS
        # UTF-8字节是保守token上界，2048预留中留256给固定chat封装。
        # 同时满足既有实测runner的系统提示小于2048字节前置条件。
        for stage, prompt in PROMPTS.items():
            with self.subTest(stage=stage):
                self.assertLessEqual(len(prompt.encode("utf-8")), 2048 - 256)

    def test_entity_prompt_example_round_trips_unicode_and_repeated_occurrences(self):
        from stable.services import news_prompts
        from stable.services.news_pipeline import digest
        import json
        example = getattr(news_prompts, "ENTITY_CONTRACT_EXAMPLE", None)
        self.assertIsInstance(example, dict)
        self.assertIn(json.dumps(example, ensure_ascii=False), news_prompts.PROMPTS["entity_check"])
        source = {**example["source"], "source_sha": digest(example["source"]),
            "clean_sha": digest(example["source"])}
        entities = validate_entities(source, example["response"])
        self.assertEqual(len(entities), 3)
        self.assertEqual([(e["block_id"], e["start"], e["end"]) for e in entities],
            [("title", 2, 12), ("b0", 0, 10), ("b0", 13, 23)])
        protected = protect_source(source, entities)
        restored = restore_translation(source, entities, {**protected, "summary": "测试摘要"})
        self.assertEqual(restored["title"], source["title"])
        self.assertEqual(restored["blocks"], source["blocks"])
        wrong = {**example["response"], "entities": [
            {**example["response"]["entities"][0], "start": 3, "end": 13}]}
        with self.assertRaisesRegex(ContentBlocked, "entity_span_invalid"):
            validate_entities(source, wrong)

    def test_broad_nonempty_container_is_not_proof_of_complete_body(self):
        with self.assertRaisesRegex(ContentBlocked, "body_boundary"):
            clean_source({"source_site": "tdn", "title": "Title", "html": "<main><p>Story plus navigation</p></main>"})

    def test_five_region_bodies_preserve_quotes_tables_and_order(self):
        for source, selector in [("jra", ".news_body"), ("hkjc_news", ".horses-racing-news-content"), ("sporting_life", ".article-body"), ("france_galop_news", ".field--name-body"), ("tdn", ".entry-content")]:
            html = f'<html><nav>全站导航</nav><div class="{selector[1:]}"><p>First paragraph.</p><blockquote>He said “Book now is an advertising phrase.”</blockquote><table><tr><th>Horse</th><th>Place</th></tr><tr><td>Alpha</td><td>1</td></tr></table><figcaption>Photo caption.</figcaption><aside>Advertisement</aside></div></html>'
            result = clean_source({"source_site": source, "title": "Title", "html": html}, selectors=[selector])
            text = "\n".join(row["text"] for row in result["blocks"])
            self.assertNotIn("全站导航", text)
            self.assertNotIn("Advertisement", text)
            self.assertIn("Book now", text)
            self.assertIn("Alpha", text)
            self.assertLess(text.index("First"), text.index("Book now"))
            self.assertLess(text.index("Book now"), text.index("Alpha"))
            self.assertIn("Photo caption", text)
            self.assertEqual(len({row["id"] for row in result["blocks"]}), len(result["blocks"]))

    def test_invalid_and_overlapping_entity_spans_are_rejected(self):
        for entities in [[{**ENTITY, "end": 12}], [ENTITY, ENTITY], [{**ENTITY, "block_id": "unknown"}]]:
            with self.assertRaises(ContentBlocked):
                validate_entities(CLEAN, {"coverage": "complete", "entities": entities})

    def test_unknown_horse_is_preserved_without_inventing_chinese_name(self):
        entities = validate_entities(CLEAN, {"coverage": "complete", "entities": [ENTITY]})
        protected = protect_source(CLEAN, entities)
        self.assertNotIn("Unknown Horse", protected["blocks"][0]["text"])
        token = protected["blocks"][0]["text"].split(" will")[0]
        target = restore_translation(CLEAN, entities, {"title": "官方更新", "summary": "计划参赛", "blocks": [{"id": "b0", "text": f"{token}计划于10月27日参赛。"}, {"id": "b1", "text": "练马师表示这是一项计划。"}]})
        self.assertIn("Unknown Horse", target["body"])
        self.assertNotIn(token, target["body"])

    def test_missing_block_or_placeholder_cannot_become_a_full_translation(self):
        entities = validate_entities(CLEAN, {"coverage": "complete", "entities": [ENTITY]})
        for blocks in [[{"id": "b0", "text": "虚构马名计划参赛。"}], [{"id": "b0", "text": "虚构马名计划参赛。"}, {"id": "b1", "text": "计划。"}]]:
            with self.assertRaises(ContentBlocked):
                restore_translation(CLEAN, entities, {"title": "标题", "summary": "摘要", "blocks": blocks})

    def test_matching_numbers_do_not_override_failed_semantic_review(self):
        target = {"title": "更新", "summary": "摘要", "body": "Unknown Horse 已经在27日参赛。", "blocks": [{"id": "b0", "text": "Unknown Horse 已经在27日参赛。"}, {"id": "b1", "text": "练马师证实。"}]}
        result = validate_audit(CLEAN, target, {"verdict": "fail", "checks": {"modality": False}, "issues": [{"kind": "modality", "block_id": "b0", "source_span": [14, 18], "target_span": [14, 16]}]})
        self.assertFalse(result["passed"])

    def test_empty_audit_and_prompt_injection_cannot_grant_a_pass(self):
        target = {"title": "更新", "summary": "摘要", "body": "27", "blocks": [{"id": "b0", "text": "27"}, {"id": "b1", "text": "计划"}]}
        self.assertFalse(validate_audit(CLEAN, target, {"verdict": "pass"})["passed"])
        with self.assertRaises(ContentBlocked):
            validate_entities(CLEAN, {"coverage": "complete", "entities": [], "tools": [{"url": "https://secret.invalid/"}]})

    def test_complete_semantic_review_accepts_equivalent_month_format(self):
        from stable.services.news_content import AUDIT_CHECKS
        target = {"title": "官方更新", "summary": "计划参赛", "body": "Unknown Horse计划于10月27日参赛。\n\n练马师表示这是一项计划。", "blocks": [{"id": "b0", "text": "Unknown Horse计划于10月27日参赛。"}, {"id": "b1", "text": "练马师表示这是一项计划。"}]}
        result = validate_audit(CLEAN, target, {"verdict": "pass", "checks": {key: True for key in AUDIT_CHECKS}, "issues": []})
        self.assertTrue(result["passed"])

    def test_summary_cannot_add_a_number_absent_from_full_source(self):
        from stable.services.news_content import AUDIT_CHECKS
        target = {"title": "官方更新", "summary": "以99马位获胜", "body": "Unknown Horse will race on 27 October.\n\nThe trainer said this is a plan.", "blocks": CLEAN["blocks"]}
        result = validate_audit(CLEAN, target, {"verdict": "pass", "checks": {key: True for key in AUDIT_CHECKS}, "issues": []})
        self.assertFalse(result["passed"])


def audit_pair(source, translated, summary="摘要"):
    clean = {"title": "News", "source_sha": "a" * 64, "clean_sha": "b" * 64,
             "blocks": [{"id": "b0", "text": source}]}
    target = {"title": "新闻", "summary": summary, "body": translated,
              "blocks": [{"id": "b0", "text": translated}]}
    response = {"verdict": "pass", "checks": {key: True for key in AUDIT_CHECKS}, "issues": []}
    return validate_audit(clean, target, response)


class NumericEquivalenceTests(SimpleTestCase):
    def test_real_currency_magnitude_conversions(self):
        for source, target in [
            ("€725 million; €802 million in 2025", "7.25亿欧元；2025年8.02亿欧元"),
            ("€26.2 million and €16.5 million", "2620万欧元和1650万欧元"),
            ("EUR 1,250,000", "125万欧元"),
        ]:
            with self.subTest(source=source):
                self.assertTrue(audit_pair(source, target)["passed"])

    def test_currency_change_amount_change_or_dropped_unit_still_blocks(self):
        for target in ["7.25万美元", "7.25亿美元", "7.26亿欧元", "725欧元", "725000000"]:
            with self.subTest(target=target):
                self.assertFalse(audit_pair("€725 million", target)["passed"])

    def test_real_month_and_chinese_number_conversions(self):
        for source, target in [
            ("at the end of August", "8月底"), ("until April", "直到4月"),
            ("in May", "在五月"), ("gate six", "第6档"),
            ("Class 2", "第二班"), ("Group 1", "一级赛"), ("G1", "一级赛"),
            ("6、7割; 10割; 1本", "六、七成；十成；一趟"),
        ]:
            with self.subTest(source=source):
                self.assertTrue(audit_pair(source, target)["passed"])

    def test_ambiguous_may_is_not_invented_as_a_month(self):
        self.assertFalse(audit_pair("May could win.", "5月可能获胜。")["passed"])
        self.assertTrue(audit_pair("May could win.", "May可能获胜。")["passed"])

    def test_wrong_month_grade_gate_and_ratio_still_block(self):
        for source, target in [("in May", "在六月"), ("G1", "二级赛"),
                               ("Class 2", "第三班"), ("gate six", "第7档"),
                               ("6割", "七成")]:
            with self.subTest(source=source):
                self.assertFalse(audit_pair(source, target)["passed"])

    def test_time_formats_preserve_hour_and_meridiem(self):
        for source, target in [("6.45pm", "下午6时45分"), ("6:45pm", "18:45"),
                               ("12.05am", "凌晨0时05分"), ("12.05am", "凌晨12时05分"), ("12.05pm", "中午12时05分")]:
            with self.subTest(source=source):
                self.assertTrue(audit_pair(source, target)["passed"])

    def test_changed_time_and_meridiem_still_block(self):
        for target in ["上午6时45分", "下午6时46分", "下午7时45分", "6.45"]:
            with self.subTest(target=target):
                self.assertFalse(audit_pair("6.45pm", target)["passed"])

    def test_equivalent_summary_amount_allowed_but_new_amount_rejected(self):
        self.assertTrue(audit_pair("€725 million", "7.25亿欧元", "预算7.25亿欧元")["passed"])
        self.assertFalse(audit_pair("€725 million", "7.25亿欧元", "预算7.26亿欧元")["passed"])

    def test_equivalence_does_not_erase_occurrence_counts(self):
        self.assertFalse(audit_pair("€725 million; €725 million", "7.25亿欧元")["passed"])

    def test_indefinite_articles_do_not_become_new_numeric_facts(self):
        self.assertTrue(audit_pair("It was a good year.", "这是很好的一年。")["passed"])
        self.assertTrue(audit_pair("She won a race.", "她赢了一场比赛。", "一次胜利")["passed"])

    def test_spelled_numbers_can_align_with_explicit_digits(self):
        self.assertTrue(audit_pair("six runners and a dual winner", "6匹参赛马和2胜马")["passed"])
        self.assertFalse(audit_pair("six runners", "7匹参赛马")["passed"])
        self.assertFalse(audit_pair("6 runners and 6 runners", "六匹参赛马")["passed"])

    def test_dollar_odds_are_not_invented_as_a_known_currency(self):
        self.assertTrue(audit_pair("a $1.4 chance", "赔率1.4")["passed"])

    def test_semantic_audit_failure_cannot_be_overridden(self):
        clean = {"title": "News", "source_sha": "a" * 64, "clean_sha": "b" * 64,
                 "blocks": [{"id": "b0", "text": "€725 million"}]}
        target = {"title": "新闻", "summary": "摘要", "body": "7.25亿欧元",
                  "blocks": [{"id": "b0", "text": "7.25亿欧元"}]}
        response = {"verdict": "fail", "checks": {key: True for key in AUDIT_CHECKS}, "issues": []}
        self.assertFalse(validate_audit(clean, target, response)["passed"])

    def test_mixed_arabic_chinese_money_scales(self):
        for source, target in [("€10 million", "1千万欧元"), ("€2 million", "2百万欧元")]:
            with self.subTest(source=source):
                self.assertTrue(audit_pair(source, target)["passed"])
        for source, target in [("€110 million", "1千万欧元"), ("€21 million", "2百万欧元")]:
            with self.subTest(source=source):
                self.assertFalse(audit_pair(source, target)["passed"])

    def test_unsupported_compound_words_do_not_supply_partial_numbers(self):
        for source, target in [("twenty-six runners", "6匹参赛马"), ("one hundred runners", "1匹参赛马"),
                               ("gate twenty-one", "第20档"), ("one hundred and six", "6匹"), ("thirty-six runners", "6匹参赛马"),
                               ("forty-one runners", "1匹参赛马"), ("twenty–six runners", "6匹参赛马"),
                               ("thirty six runners", "6匹参赛马"), ("twenty‑six runners", "6匹参赛马"),
                               ("one and a half lengths", "1马位"), ("two and a quarter lengths", "2马位"),
                               ("two thirds", "2"), ("one point five", "1"), ("six dozen", "6"),
                               ("negative six", "6")]:
            with self.subTest(source=source):
                self.assertFalse(audit_pair(source, target)["passed"])

    def test_clock_chinese_adjacency_and_race_duration(self):
        for source, target in [("The race starts at 18:45.", "比赛在18:45开始。"),
                               ("He won in 1:34.56.", "他以1分34.56秒获胜。")]:
            with self.subTest(source=source):
                self.assertTrue(audit_pair(source, target)["passed"])
        self.assertFalse(audit_pair("He won in 1:34.56.", "他以1分34.57秒获胜。")["passed"])

    def test_explicit_currency_aliases(self):
        for source, target in [("HK$100", "100港币"), ("US$100", "100美金")]:
            with self.subTest(source=source):
                self.assertTrue(audit_pair(source, target)["passed"])
        self.assertFalse(audit_pair("HK$100", "100美金")["passed"])


def policy_response(date_text, canonical="2026-10-22"):
    text = "Authority France equipment " + date_text
    values = {"organization": "Authority", "jurisdiction": "France", "scope": "equipment",
              "effective_date": canonical}
    originals = {**values, "effective_date": date_text}
    evidence = {key: {"block_id": "b0", "start": text.index(value),
                      "end": text.index(value) + len(value)} for key, value in originals.items()}
    clean = {"title": "Policy", "blocks": [{"id": "b0", "text": text}]}
    response = {"primary_region": "france", "priority": "regional", "reason": "规则变更",
                "identity": {"kind": "policy", "fields": values, "evidence": evidence},
                "comparison": {"event_id": None, "version": 0},
                "facts": [{"subject_ref": "Authority", "predicate": "approved", "object": "equipment",
                           "effective_time": canonical, "modality": "happened", "importance": "minor",
                           "relation": "new", "prior_fact_ids": [],
                           "source_span": {"block_id": "b0", "start": 17, "end": 26}}]}
    return clean, response


class EditorialDateEquivalenceTests(SimpleTestCase):
    def test_full_dates_can_match_iso_identity(self):
        for text in ["October 22, 2026", "22 October 2026", "2026年10月22日", "2026-10-22"]:
            with self.subTest(text=text):
                clean, response = policy_response(text)
                self.assertTrue(validate_editorial(clean, response, source_scope="france_galop_news")["identity_key"])

    def test_different_partial_invalid_or_ambiguous_dates_do_not_match(self):
        for text in ["October 23, 2026", "October 22", "22/10/2026", "2026-02-30",
                     "October 22, 2026 planned", "October 22, 2025"]:
            with self.subTest(text=text):
                clean, response = policy_response(text)
                with self.assertRaises(ContentBlocked):
                    validate_editorial(clean, response, source_scope="france_galop_news")

    def test_date_equivalence_does_not_repair_other_bad_evidence_spans(self):
        clean, response = policy_response("October 22, 2026")
        response = deepcopy(response)
        response["identity"]["evidence"]["scope"]["end"] -= 1
        with self.assertRaisesRegex(ContentBlocked, "identity_evidence_mismatch"):
            validate_editorial(clean, response, source_scope="france_galop_news")


class ContextContractTests(SimpleTestCase):
    def test_context_entities_roundtrip_unicode_and_repeated_names(self):
        clean = {**CLEAN, 'title': '😀Alpha', 'blocks': [{'id': 'b0', 'text': 'Alpha wins; Alpha retires.'}]}
        response = {'coverage': 'complete', 'entities': [
            {'block_id': 'title', 'text': 'Alpha', 'type': 'horse', 'context': '😀Alpha'},
            {'block_id': 'b0', 'text': 'Alpha', 'type': 'horse', 'context': 'Alpha wins'},
            {'block_id': 'b0', 'text': 'Alpha', 'type': 'horse', 'context': '; Alpha retires.'}]}
        rows = validate_entities(clean, response, contract_version='context-v2')
        self.assertEqual([(r['start'], r['end']) for r in rows], [(1, 6), (0, 5), (12, 17)])
        self.assertTrue(all(r['context'] for r in rows))
        raw = {**protect_source(clean, rows), 'summary': '摘要'}
        self.assertEqual(restore_translation(clean, rows, raw)['blocks'], clean['blocks'])

    def test_missing_ambiguous_invented_context_or_legacy_spans_fail_closed(self):
        clean = {**CLEAN, 'blocks': [{'id': 'b0', 'text': 'Alpha / Alpha'}]}
        row = {'block_id': 'b0', 'text': 'Alpha', 'type': 'horse', 'context': 'Alpha'}
        for value in [row, {**row, 'context': ''}, {**row, 'context': 'Alpha / Alpha'},
                      {**row, 'context': 'alpha / '}, {**row, 'start': 0, 'end': 5},
                      {k: v for k, v in row.items() if k != 'context'}]:
            with self.subTest(value=value), self.assertRaises(ContentBlocked):
                validate_entities(clean, {'coverage': 'complete', 'entities': [value]}, contract_version='context-v2')

    def test_summary_and_cross_block_audit_issues_use_independent_anchors(self):
        target = {'title': '官方更新', 'summary': '10月28日参赛。', 'blocks': [
            {'id': 'b0', 'text': 'Unknown Horse计划于10月27日参赛。'},
            {'id': 'b1', 'text': '骑师说这是一项计划。'}], 'body': 'unused'}
        response = {'verdict': 'fail', 'checks': {k: False for k in AUDIT_CHECKS}, 'issues': [
            {'kind': 'dates', 'source': {'block_id': 'b0', 'quote': '27 October', 'context': 'race on 27 October.'},
             'target': {'block_id': 'summary', 'quote': '28', 'context': '10月28日参赛。'}, 'missing': False},
            {'kind': 'attribution', 'source': {'block_id': 'b1', 'quote': 'trainer', 'context': 'The trainer said'},
             'target': {'block_id': 'b1', 'quote': '骑师', 'context': '骑师说'}, 'missing': False}]}
        quality = validate_audit(CLEAN, target, response, contract_version='context-v2')
        self.assertFalse(quality['passed'])
        self.assertTrue(quality['evidence_valid'])
        self.assertEqual(quality['repair_block_ids'], ['b1', 'summary'])
        response['issues'][0]['target']['context'] = 'invented'
        self.assertFalse(validate_audit(CLEAN, target, response, contract_version='context-v2')['evidence_valid'])

    def test_patch_bound_to_raw_baseline_and_exact_target_set(self):
        from stable.services import news_content as content
        base = {'title': '标题', 'summary': '摘要', 'blocks': [{'id': 'b0', 'text': '旧译'}, {'id': 'b1', 'text': '不变'}]}
        patch = {'base_raw_sha': content.digest(base), 'replacements': [{'id': 'b0', 'text': '新译'}]}
        merged = content.merge_translation_patch(base, patch, ['b0'])
        self.assertEqual(merged['blocks'][1], base['blocks'][1])
        self.assertEqual(merged['blocks'][0]['text'], '新译')
        self.assertEqual(base['blocks'][0]['text'], '旧译')
        for bad in [{**patch, 'base_raw_sha': 'wrong'}, {**patch, 'replacements': patch['replacements'] * 2},
                    {**patch, 'replacements': [{'id': 'b1', 'text': '越界'}]}]:
            with self.assertRaises(ContentBlocked):
                content.merge_translation_patch(base, bad, ['b0'])

    def test_stable_projection_preserves_content_but_excludes_receipt_id(self):
        from stable.services import news_content as content
        a = {**CLEAN, 'body_review_attempt_id': 1}
        b = {**CLEAN, 'body_review_attempt_id': 2}
        self.assertEqual(content.stable_source(a), content.stable_source(b))
        self.assertNotEqual(content.stable_source(a), content.stable_source({**b, 'title': 'changed'}))

    def test_hard_checks_identify_numeric_block_before_model_audit(self):
        from stable.services import news_content as content
        target = {'title': 'Official update', 'summary': 'A plan', 'blocks': [
            {'id': 'b0', 'text': 'Unknown Horse will race on 28 October.'},
            {'id': 'b1', 'text': CLEAN['blocks'][1]['text']}], 'body': ''}
        value = content.hard_translation_checks(CLEAN, target)
        self.assertEqual(value['repair_block_ids'], ['b0'])
        self.assertFalse(value['passed'])

"""T01–T07/T25：全文、引语表格、严格实体跨度与事实审校。"""
from django.test import SimpleTestCase
from stable.services.news_content import (
    ContentBlocked, clean_source, validate_entities, protect_source,
    restore_translation, validate_audit,
)

CLEAN = {"title": "Official update", "source_sha": "a" * 64, "clean_sha": "b" * 64,
    "blocks": [{"id": "b0", "text": "Unknown Horse will race on 27 October."}, {"id": "b1", "text": "The trainer said this is a plan."}]}
ENTITY = {"block_id": "b0", "start": 0, "end": 13, "text": "Unknown Horse", "type": "horse"}


class NewsContentTests(SimpleTestCase):
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

"""C200 real-caller test-source candidate; no run is claimed here.

All rows are isolated synthetic fixtures. The old --commit entry and the real
resolver remain the oracle boundary; no future helper/flag is imported. The new
binding describes local producer arguments only, never canonical identity,
visible-span validity, source authorization or a complete relationship set.
"""
import copy
import hashlib
import io
import json
from contextlib import contextmanager
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from stable.models import ArticleHorseLink, ArticleRaceLink, NewsArticle, OperationLog
from stable.services import article_entity_reprocessing as service


BINDING_KEY = "article_entity_resolution_binding"
EMPTY_JA_DTO = {
    "source_language": "ja", "entities": [], "suppressed_candidates": [],
    "accepted_terms": [], "accepted_term_ids": [], "machine_horse_tags": [],
}
RAW_HTML_SOURCE = {
    "title_ja": "<b>Aurora 🐎 update</b>",
    "body_ja_raw": "<p>Unused raw source 原文.</p>",
    "body_ja_normalized": "<p>Aurora won. 保留空白  and markup.</p>",
    "source_language": "en",
}
REFRESHED_SOURCE = {
    "title_ja": "<i>Refreshed Aurora 🐎</i>",
    "body_ja_raw": "<p>Aurora ran. 更新原文.</p>",
    "body_ja_normalized": "",
    "source_language": "en",
}
SPACE_SOURCE = {
    "title_ja": "", "body_ja_raw": "未选择的原始字段", "body_ja_normalized": " ",
    "source_language": "",  # raw empty value must remain distinct from effective ja
}


def fixture_digest(value):
    # Independent formula, never service._bd_sha/builder/canonical_chunks.
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@contextmanager
def observe_real_resolver():
    original = service.resolve_article_entities
    observed = []
    def invoke(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append({"args": copy.deepcopy(args), "kwargs": copy.deepcopy(kwargs),
                         "dto": copy.deepcopy(result.as_dict())})
        return result
    with patch.object(service, "resolve_article_entities", side_effect=invoke):
        yield observed


@override_settings(AUTO_REWRITE_ENABLED=False, AUTO_DUPLICATE_HIGH_THRESHOLD=0,
                   AUTO_DUPLICATE_REVIEW_THRESHOLD=0)
class ArticleEntityResolutionBindingProducerTests(TestCase):
    def article(self, source, *, metadata=None, published=False):
        published_at = timezone.now()
        return NewsArticle.objects.create(
            source_site="tdn", source_mode="latest", source_article_id="c200-source",
            source_url="https://example.invalid/c200-source", published_at=published_at,
            workflow_status="published" if published else "pending_translation",
            published_to_web_at=published_at if published else None, tags_json=["keep"],
            translation_metadata=copy.deepcopy(metadata if metadata is not None else {"unrelated": "preserve"}),
            **source,
        )

    def commit(self, article_id, *, translate_sync=False):
        args = ["--article-id", str(article_id), "--commit", "--json"]
        if translate_sync:
            args.append("--translate-sync")
        out = io.StringIO()
        call_command("reprocess_article_entities", *args, stdout=out)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["mode"], "commit")
        return payload["articles"][0]

    def assert_final_call(self, calls, *, title, body, language):
        # Current legacy producer resolves twice. Do not add another resolution
        # merely to generate a binding or fake a full DTO.
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[-1]["args"], (title, body))
        self.assertEqual(calls[-1]["kwargs"], {"source_language": language})
        return calls[-1]["dto"]

    def assert_saved_binding(self, article, *, source, title, body, language, selector, dto):
        article.refresh_from_db()
        for field, value in source.items():
            self.assertEqual(getattr(article, field), value, "fixture source drift: " + field)
        metadata = article.translation_metadata
        self.assertEqual(metadata["article_entity_resolution"], dto)
        self.assertIn(BINDING_KEY, metadata)  # intended real-caller missing-feature assertion
        expected = {
            "schema_version": "n03.resolution-input-binding.v1",
            "producer": "article_entity_reprocessing._commit_article.final",
            "article_id": article.pk,  # local DB locator, never F01 canonical
            "source_fields_sha256": fixture_digest(source),
            "resolver_inputs_sha256": fixture_digest({
                "title": title, "body": body, "effective_language": language,
            }),
            "resolution_sha256": fixture_digest(dto),
            "source_selection": {"title": "title_ja", "body": selector},
            "basis": "exact_resolver_arguments", "unit": "python_codepoints",
            "input_proof_scope": "producer_inputs_only",
        }
        # Exact v1 keys exclude accidental timestamps or invented identity/auth claims.
        self.assertEqual(metadata[BINDING_KEY], expected)
        return copy.deepcopy(metadata[BINDING_KEY])

    def test_commit_persists_exact_source_and_final_resolution_binding(self):
        article = self.article(RAW_HTML_SOURCE)
        with observe_real_resolver() as calls:
            outcome = self.commit(article.pk)
        self.assertEqual(outcome["status"], "committed")
        dto = self.assert_final_call(
            calls, title="<b>Aurora 🐎 update</b>",
            body="<p>Aurora won. 保留空白  and markup.</p>", language="en",
        )
        self.assertEqual(outcome["entities"], dto)
        self.assert_saved_binding(
            article, source=RAW_HTML_SOURCE, title="<b>Aurora 🐎 update</b>",
            body="<p>Aurora won. 保留空白  and markup.</p>", language="en",
            selector="body_ja_normalized", dto=dto,
        )
        self.assertEqual(article.translation_metadata["unrelated"], "preserve")

    def test_translate_sync_binds_refreshed_source_and_final_resolver(self):
        article = self.article(RAW_HTML_SOURCE)
        def provider_boundary(article_id, *, force, suppress_automation):
            self.assertEqual(article_id, article.pk)
            self.assertTrue(force)
            self.assertTrue(suppress_automation)
            self.assertEqual(NewsArticle.objects.filter(pk=article_id).update(**REFRESHED_SOURCE), 1)
            return {"translated": True}
        with patch.object(service.translate_article_task, "run", side_effect=provider_boundary) as provider, \
                observe_real_resolver() as calls:
            outcome = self.commit(article.pk, translate_sync=True)
        provider.assert_called_once_with(article.pk, force=True, suppress_automation=True)
        self.assertEqual(outcome["status"], "committed")
        self.assertEqual(calls[0]["args"], (
            "<b>Aurora 🐎 update</b>", "<p>Aurora won. 保留空白  and markup.</p>",
        ))
        dto = self.assert_final_call(
            calls, title="<i>Refreshed Aurora 🐎</i>",
            body="<p>Aurora ran. 更新原文.</p>", language="en",
        )
        self.assertEqual(outcome["entities"], dto)
        self.assert_saved_binding(
            article, source=REFRESHED_SOURCE, title="<i>Refreshed Aurora 🐎</i>",
            body="<p>Aurora ran. 更新原文.</p>", language="en", selector="body_ja_raw", dto=dto,
        )

    def test_downstream_failure_rolls_back_full_dto_and_binding_together(self):
        # Deliberately untrusted pre-existing fixture marker, not a fake verified
        # producer receipt. This control must restore whatever metadata preceded it.
        original_metadata = {
            "article_entity_resolution": copy.deepcopy(EMPTY_JA_DTO),
            BINDING_KEY: {"schema_version": "fixture.untrusted.old", "marker": "preserve on rollback"},
            "unrelated": "preserve",
        }
        article = self.article(RAW_HTML_SOURCE, metadata=original_metadata, published=True)
        before = NewsArticle.objects.filter(pk=article.pk).values().get()
        horse_links = list(ArticleHorseLink.objects.filter(article_id=article.pk).order_by("id").values())
        race_links = list(ArticleRaceLink.objects.filter(article_id=article.pk).order_by("id").values())
        staged = []
        failure = "C200 controlled post-save link failure"
        def reject_after_save(actual_article, actual_resolution, *, commit):
            self.assertEqual(actual_article.pk, article.pk)
            self.assertTrue(commit)
            staged.append({"metadata": copy.deepcopy(NewsArticle.objects.get(pk=article.pk).translation_metadata),
                           "dto": copy.deepcopy(actual_resolution.as_dict())})
            raise RuntimeError(failure)
        with patch.object(service, "reconcile_article_horse_links", side_effect=reject_after_save), \
                observe_real_resolver() as calls:
            outcome = self.commit(article.pk)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error"], failure)  # no swallowed unrelated fixture error
        self.assertEqual(len(staged), 1)
        dto = self.assert_final_call(
            calls, title="<b>Aurora 🐎 update</b>",
            body="<p>Aurora won. 保留空白  and markup.</p>", language="en",
        )
        self.assertEqual(staged[0]["dto"], dto)
        self.assertEqual(staged[0]["metadata"]["article_entity_resolution"], dto)
        self.assertNotEqual(dto, original_metadata["article_entity_resolution"])
        self.assertEqual(NewsArticle.objects.filter(pk=article.pk).values().get(), before)
        self.assertEqual(list(ArticleHorseLink.objects.filter(article_id=article.pk).order_by("id").values()), horse_links)
        self.assertEqual(list(ArticleRaceLink.objects.filter(article_id=article.pk).order_by("id").values()), race_links)
        self.assertFalse(OperationLog.objects.filter(action_type="article_entities_reprocessed", target_id=str(article.pk)).exists())
        self.assertTrue(OperationLog.objects.filter(action_type="article_entities_reprocess_failed", target_id=str(article.pk)).exists())

    def test_binding_stable_for_repeat_and_changes_for_same_dto_new_input(self):
        article = self.article(SPACE_SOURCE)
        with observe_real_resolver() as calls:
            outcome = self.commit(article.pk)
        self.assertEqual(outcome["status"], "committed")
        dto = self.assert_final_call(calls, title="", body=" ", language="ja")
        self.assertEqual(dto, EMPTY_JA_DTO, "fixture precondition: whitespace contains no entity")
        first = self.assert_saved_binding(
            article, source=SPACE_SOURCE, title="", body=" ", language="ja",
            selector="body_ja_normalized", dto=dto,
        )
        with observe_real_resolver() as calls:
            outcome = self.commit(article.pk)
        self.assertEqual(outcome["status"], "committed")
        repeated_dto = self.assert_final_call(calls, title="", body=" ", language="ja")
        self.assertEqual(repeated_dto, EMPTY_JA_DTO, "fixture precondition: unchanged DTO")
        repeated = self.assert_saved_binding(
            article, source=SPACE_SOURCE, title="", body=" ", language="ja",
            selector="body_ja_normalized", dto=repeated_dto,
        )
        self.assertEqual(repeated, first)
        changed_source = {**SPACE_SOURCE, "body_ja_normalized": "\t"}
        self.assertEqual(NewsArticle.objects.filter(pk=article.pk).update(**changed_source), 1)
        with observe_real_resolver() as calls:
            outcome = self.commit(article.pk)
        self.assertEqual(outcome["status"], "committed")
        changed_dto = self.assert_final_call(calls, title="", body="\t", language="ja")
        self.assertEqual(changed_dto, EMPTY_JA_DTO, "fixture precondition: new whitespace, same DTO")
        changed = self.assert_saved_binding(
            article, source=changed_source, title="", body="\t", language="ja",
            selector="body_ja_normalized", dto=changed_dto,
        )
        self.assertNotEqual(changed["source_fields_sha256"], first["source_fields_sha256"])
        self.assertNotEqual(changed["resolver_inputs_sha256"], first["resolver_inputs_sha256"])
        self.assertEqual(changed["resolution_sha256"], first["resolution_sha256"])

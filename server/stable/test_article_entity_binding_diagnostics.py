"""C191 test-source candidate; execution requires a separate ROOT card.

Synthetic isolated fixtures, never a producer/authenticity claim. New flags are
absent on the fixed parent: those calls ERROR at argparse, not business RED.
Private resource seams below are proposed test interfaces, retrieved inside
methods; absent helpers ERROR without preventing module collection. No skip,
expectedFailure, feature-detection pass, or fabricated successful core result.
"""
import base64
import copy
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.models.query import QuerySet
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from stable import models
from stable.services import article_entity_reprocessing as service
from stable.services import article_entity_binding as core
from stable.services import content_contracts as f01

# Independently frozen literal copied from the exact PR260 test source at author
# time using AST only. No import/build_input/parse/core was executed to prepare it.
AUDIT_LITERAL = {'status': 'SYNTHETIC_STATIC_DATA_ONLY_NOT_PARSER_OR_TEST_EXECUTED', 'article_input': {'schema_version': 'f01.v1', 'evaluated_at': '2026-10-17T11:30:00Z', 'policy_ref': 'f01-policy-draft', 'input_version': {'schema_version': 'f01.input.v1', 'scope': ['entity', 'evidence', 'materials', 'policy_ref', 'protection'], 'content_sha256': 'c7ee1a963061482f3adaa6a362074f336a5c70db9684d50031f273e6ec0ab76e', 'generations': {'owner': None, 'schedule': None, 'enrollment': None, 'source_set': None}}, 'snapshot': {'entity': {'kind': 'article', 'canonical_id': 'article-A1', 'identity_state': 'verified', 'source_refs': [], 'candidate_ids': [], 'evidence_refs': ['E-doc']}, 'materials': [], 'evidence': [{'evidence_id': 'E-doc', 'provider_key': 'fixture-official_operator', 'source_class': 'official_operator', 'independence_key': 'fixture-origin-e-date', 'capability': 'identity', 'artifact_sha256': '88435301d532cbe53b77cba03f3b3377498d6fb2c98822b56ea14e21d5cce7c4', 'locator': '/body', 'observed_at': '2026-10-17T11:00:00Z', 'source_time': {'precision': 'unknown', 'published_at': None, 'last_absent_at': None, 'first_seen_at': '2026-10-17T11:00:00Z'}, 'contract_ref': {'route_digest': 'e050efd0a0e23d85c6a1f4dc256aaf88bc6179d0a5a69a50fe274c3e414ddda7', 'contract_digest': '304aeb6aeb9281204cf0b2723b2d0d855d70719de14de5aa270752aa275e307b', 'proof_digest': 'b5a666eb4586fa4015f3c37018c0e6d6f37d28297d8484dd74150d488b0a4338', 'valid_until': '2026-10-30T00:00:00Z', 'revoked': False}}], 'protection': {'paused': False, 'fields': [], 'modules': [], 'reason': 'synthetic L01 fixture', 'actor_ref': None, 'changed_at': None, 'protection_sha256': '9c8f6addb1e76b4c6545cdfca366f045406c06d0934eaef627003bfad5790b63'}, 'policy_ref': 'f01-policy-draft'}}, 'identity_inputs': [{'schema_version': 'f01.v1', 'evaluated_at': '2026-10-17T11:30:00Z', 'policy_ref': 'f01-policy-draft', 'input_version': {'schema_version': 'f01.input.v1', 'scope': ['entity', 'evidence', 'materials', 'policy_ref', 'protection'], 'content_sha256': '622e9bc82ccc0a48428a5f160c8bdf080514f8f65e0a602b10e2af67ab594f30', 'generations': {'owner': None, 'schedule': None, 'enrollment': None, 'source_set': None}}, 'snapshot': {'entity': {'kind': 'horse', 'canonical_id': 'horse-H1', 'identity_state': 'verified', 'source_refs': [], 'candidate_ids': [], 'evidence_refs': ['E-horse']}, 'materials': [], 'evidence': [{'evidence_id': 'E-horse', 'provider_key': 'fixture-official_operator', 'source_class': 'official_operator', 'independence_key': 'fixture-origin-e-date', 'capability': 'identity', 'artifact_sha256': '18bc562d6d3776902780115a606ac946ed75f4991cc4fadd2f456bbb0cbbc081', 'locator': '/canonical_id', 'observed_at': '2026-10-17T11:00:00Z', 'source_time': {'precision': 'unknown', 'published_at': None, 'last_absent_at': None, 'first_seen_at': '2026-10-17T11:00:00Z'}, 'contract_ref': {'route_digest': 'e050efd0a0e23d85c6a1f4dc256aaf88bc6179d0a5a69a50fe274c3e414ddda7', 'contract_digest': '304aeb6aeb9281204cf0b2723b2d0d855d70719de14de5aa270752aa275e307b', 'proof_digest': 'b5a666eb4586fa4015f3c37018c0e6d6f37d28297d8484dd74150d488b0a4338', 'valid_until': '2026-10-30T00:00:00Z', 'revoked': False}}], 'protection': {'paused': False, 'fields': [], 'modules': [], 'reason': 'synthetic L01 fixture', 'actor_ref': None, 'changed_at': None, 'protection_sha256': '9c8f6addb1e76b4c6545cdfca366f045406c06d0934eaef627003bfad5790b63'}, 'policy_ref': 'f01-policy-draft'}}], 'relation_inputs': [{'schema_version': 'f01.v1', 'evaluated_at': '2026-10-17T11:30:00Z', 'policy_ref': 'f01-policy-draft', 'input_version': {'schema_version': 'f01.input.v1', 'scope': ['entity', 'evidence', 'materials', 'policy_ref', 'protection'], 'content_sha256': '8849b9b2da7cbb07bf0c263cbf879c6d34e99658e5d062492b04a244811e9abc', 'generations': {'owner': None, 'schedule': None, 'enrollment': None, 'source_set': None}}, 'snapshot': {'entity': {'kind': 'horse', 'canonical_id': 'horse-H1', 'identity_state': 'verified', 'source_refs': [], 'candidate_ids': [], 'evidence_refs': ['E-rel']}, 'materials': [{'capability': 'relationship', 'maturity': 'confirmed', 'completeness': 'complete', 'validation': 'passed', 'revision_ref': 'l01-rel-rev1', 'supersedes_ref': None, 'evidence_refs': ['E-rel'], 'data': {'source_ref': 'article-A1', 'target_ref': 'horse-H1', 'relation_type': 'horse_subject'}}], 'evidence': [{'evidence_id': 'E-rel', 'provider_key': 'fixture-official_operator', 'source_class': 'official_operator', 'independence_key': 'fixture-origin-e-date', 'capability': 'relationship', 'artifact_sha256': '6969e238e208a1f525c6a093cfbc63e267915ceb84b04531f934887cfc9f6318', 'locator': '/assertions/0', 'observed_at': '2026-10-17T11:00:00Z', 'source_time': {'precision': 'unknown', 'published_at': None, 'last_absent_at': None, 'first_seen_at': '2026-10-17T11:00:00Z'}, 'contract_ref': {'route_digest': 'e050efd0a0e23d85c6a1f4dc256aaf88bc6179d0a5a69a50fe274c3e414ddda7', 'contract_digest': '304aeb6aeb9281204cf0b2723b2d0d855d70719de14de5aa270752aa275e307b', 'proof_digest': 'b5a666eb4586fa4015f3c37018c0e6d6f37d28297d8484dd74150d488b0a4338', 'valid_until': '2026-10-30T00:00:00Z', 'revoked': False}}], 'protection': {'paused': False, 'fields': [], 'modules': [], 'reason': 'synthetic L01 fixture', 'actor_ref': None, 'changed_at': None, 'protection_sha256': '9c8f6addb1e76b4c6545cdfca366f045406c06d0934eaef627003bfad5790b63'}, 'policy_ref': 'f01-policy-draft'}}], 'source_document': {'title': '', 'body': 'Aurora won.'}, 'source_document_raw_utf8_canonical_sha256': '88435301d532cbe53b77cba03f3b3377498d6fb2c98822b56ea14e21d5cce7c4', 'resolution_payload': {'source_language': 'en', 'entities': [{'entity_type': 'horse', 'matched_text': 'Aurora', 'canonical_text': 'Aurora', 'target_zh': '', 'field_name': 'body', 'start': 0, 'end': 6, 'confidence': 99, 'evidence': ['synthetic structured identity occurrence'], 'conflict_flags': [], 'needs_preserve': True, 'term_id': None, 'external_horse_ids': [], 'priority': 0, 'term_type': 'horse', 'classification': 'confirmed_horse', 'reason': 'synthetic_control', 'matched_context': 'Aurora won.', 'entity_evidence': ['synthetic structured identity occurrence'], 'matched_span': [0, 6], 'primary_external_horse_id': ''}], 'suppressed_candidates': [], 'accepted_terms': [], 'accepted_term_ids': [], 'machine_horse_tags': []}, 'relationship_artifacts': {'6969e238e208a1f525c6a093cfbc63e267915ceb84b04531f934887cfc9f6318': {'schema_version': 'l01.relationship-assertions.v1', 'assertions': [{'assertion_id': 'assertion-1', 'revision_ref': 'l01-rel-rev1', 'article': {'kind': 'article', 'canonical_id': 'article-A1', 'input_wire_sha256': 'bcdd2116104277592087d5d0d21f1b76fdc4a772724edb37840ce61f0c278b5a', 'source_document_sha256': '88435301d532cbe53b77cba03f3b3377498d6fb2c98822b56ea14e21d5cce7c4'}, 'occurrence': {'field_name': 'body', 'start': 0, 'end': 6, 'matched_text': 'Aurora', 'entity_payload_sha256': '8523af9947b6dffa1cbe67d0cc6a680d6f4b5efb2ca094e73f0dc5f7f912945a'}, 'target': {'kind': 'horse', 'canonical_id': 'horse-H1', 'identity_input_wire_sha256': '030500cd157cf91a4b115d42d7fb1b3434bae43a2b53f82f7461d7408ab07a06', 'source_ref': None}, 'role': 'horse_subject', 'status': 'active'}]}}, 'contexts': [{'occurrence': {'field_name': 'body', 'start': 0, 'end': 6, 'matched_text': 'Aurora', 'entity_payload_sha256': '8523af9947b6dffa1cbe67d0cc6a680d6f4b5efb2ca094e73f0dc5f7f912945a'}, 'target_identity_input_wire_sha256': '030500cd157cf91a4b115d42d7fb1b3434bae43a2b53f82f7461d7408ab07a06', 'source_ref': None, 'role': 'horse_subject', 'relation_input_wire_sha256': 'a022e32f109513e7265f0e818c9b54babbcf79e68d36cb11ffbb89ee1c30aa1c', 'evidence_id': 'E-rel'}], 'hash_definition': 'SHA256 of json.dumps(value,sort_keys=True,separators=(comma,colon),ensure_ascii=False,allow_nan=False).encode(UTF8); artifacts here stored as JSON objects only, future test must serialize to exact canonical bytes', 'expected_conditional_result': 'one proposed_binding if every F01 document parses and all structural/state predicates match; not source authenticity or production authorization', 'hash_graph': 'source bytes -> article input; identity source -> identity input; both input wire hashes -> assertion bytes -> relation evidence/material -> separate relation input -> sidecar; no circular fingerprint'}

SOURCE_FIELDS = ("title_ja", "body_ja_raw", "body_ja_normalized", "source_language")
VALUES_FIELDS = ("id", *SOURCE_FIELDS, "translation_metadata", "updated_at")
WATCH_MODELS = (models.NewsArticle, models.ArticleHorseLink, models.ArticleRaceLink,
                models.RaceNewsExposure, models.QQPushDelivery, models.OperationLog,
                models.TranslationRun)
SECRET = "C191_PRIVATE_PATH_BODY_EXCEPTION_SENTINEL"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def resolution():
    return copy.deepcopy(AUDIT_LITERAL["resolution_payload"])


def envelope(article):
    # Literal original wires; no serializer deriving verified identities.
    c = copy.deepcopy(AUDIT_LITERAL)
    return {"schema_version": "l01.readonly-audit.v1", "article_id": article.pk,
            "observed_source_fields_sha256": sha({k: getattr(article, k) for k in SOURCE_FIELDS}),
            "persisted_resolution_sha256": sha(article.translation_metadata["article_entity_resolution"]),
            "article_input": c["article_input"], "identity_inputs": c["identity_inputs"],
            "relation_inputs": c["relation_inputs"], "contexts": c["contexts"],
            "source_document_base64": base64.b64encode(canonical(c["source_document"])).decode("ascii"),
            "relationship_artifacts_base64": {k: base64.b64encode(canonical(v)).decode("ascii")
                                                for k, v in c["relationship_artifacts"].items()}}


@contextmanager
def bundle_file(data):
    # realpath is only for this safe temporary fixture: macOS /var is a symlink.
    # Consumer must itself reject symlinks, not call resolve on user input.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(os.path.realpath(tmp)) / "explicit.json"
        path.write_bytes(data)
        yield str(path)
        assert path.read_bytes() == data, "consumer modified explicit original"


@contextmanager
def real_spies():
    # Capture direct imports as well as canonical functions. One shared wrapper
    # counts one actual invocation, and delegates the unchanged original.
    with ExitStack() as stack:
        spies = {}
        for name, module in (("f01", f01), ("core", core)):
            attr = "parse_input" if name == "f01" else "plan_article_entity_bindings"
            original = getattr(module, attr)
            spy = Mock(wraps=original)
            aliases = [(module, attr)]
            aliases += [(service, k) for k, v in vars(service).items() if v is original]
            for owner, key in aliases:
                stack.enter_context(patch.object(owner, key, spy))
            spies[name] = spy
        stack.enter_context(patch.object(f01, "build_input", side_effect=AssertionError("no producer repair")))
        for name in ("resolve_article_entities", "_tag_plan", "reconcile_article_horse_links",
                     "build_article_entity_reprocess_plan", "_commit_article", "reprocess_article_entities"):
            stack.enter_context(patch.object(service, name, side_effect=AssertionError("forbidden " + name)))
        stack.enter_context(patch.object(service.translate_article_task, "run", side_effect=AssertionError("translate")))
        stack.enter_context(patch.object(service.translate_article_task, "delay", side_effect=AssertionError("enqueue")))
        yield spies


@override_settings(AUTO_REWRITE_ENABLED=False, AUTO_DUPLICATE_HIGH_THRESHOLD=0,
                   AUTO_DUPLICATE_REVIEW_THRESHOLD=0)
class BindingDiagnosticCommandTests(TestCase):
    def article(self, *, metadata=None, **changes):
        count = models.NewsArticle.objects.count()
        fields = dict(source_site="tdn", source_mode="latest", source_article_id="c191-" + str(count),
                      source_url="https://example.invalid/c191/" + str(count),
                      source_language="en", title_ja="", body_ja_raw="Aurora won.",
                      body_ja_normalized="Aurora won.", published_at=timezone.now(),
                      tags_json=["keep"], translation_metadata={"article_entity_resolution": resolution()})
        if metadata is not None:
            fields["translation_metadata"] = metadata
        fields.update(changes)
        return models.NewsArticle.objects.create(**fields)

    def state(self):
        return {m._meta.label: list(m.objects.order_by("pk").values()) for m in WATCH_MODELS}

    def invoke(self, ids, *, path=None, extra=(), error=None, queries=1, audit_core=0, f01_min=0):
        before = self.state()
        out = io.StringIO(); err = io.StringIO(); values = []
        original_values = QuerySet.values
        def trace_values(qs, *fields, **kwargs):
            if qs.model is models.NewsArticle:
                values.append((fields, kwargs))
            return original_values(qs, *fields, **kwargs)
        def readonly(execute, sql, params, many, context):
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), "diagnostic attempted non-SELECT SQL")
            return execute(sql, params, many, context)
        args = ["--binding-diagnostics", "--json"]
        for pk in ids:
            args += ["--article-id", str(pk)]
        if path is not None:
            args += ["--binding-input", path]
        args += list(extra)
        with real_spies() as spies, patch.object(QuerySet, "values", trace_values), \
                patch.object(os, "open", wraps=os.open) as file_opens, \
                connection.execute_wrapper(readonly), CaptureQueriesContext(connection) as captured:
            if error is None:
                call_command("reprocess_article_entities", *args, stdout=out, stderr=err)
            else:
                try:
                    call_command("reprocess_article_entities", *args, stdout=out, stderr=err)
                except CommandError as exc:
                    # Missing flags remain a real interface ERROR, never a
                    # manufactured business AssertionError or expected RED.
                    if str(exc) != error:
                        raise
                    self.assertIsNone(exc.__cause__)
                    self.assertTrue(exc.__suppress_context__)
                else:
                    self.fail("missing diagnostic rejection: " + error)
            if path is None or error in ("invalid_flags", "invalid_ids"):
                self.assertEqual(file_opens.call_count, 0)
            self.assertEqual(spies["core"].call_count, audit_core)
            if audit_core:
                args_used, kwargs_used = spies["core"].call_args
                supplied = args_used[0] if args_used else kwargs_used["resolution_payload"]
                original = next(r for r in before["stable.NewsArticle"] if r["id"] == ids[0])
                self.assertEqual(supplied, original["translation_metadata"]["article_entity_resolution"])
                self.last_core_arguments = kwargs_used
            self.assertGreaterEqual(spies["f01"].call_count, f01_min)
            if not f01_min:
                self.assertEqual(spies["f01"].call_count, 0)
        self.assertEqual(len(captured), queries)
        self.assertEqual(len(values), queries)
        if queries:
            self.assertEqual(set(values[0][0]), set(VALUES_FIELDS))
            self.assertEqual(len(values[0][0]), 8)
            self.assertEqual(values[0][1], {})
        self.assertEqual(self.state(), before)
        output = out.getvalue()
        payload = json.loads(output)  # rejects concatenated/partial normal output
        if error:
            self.assertLessEqual(len(output.encode()), 1024)
            self.assertEqual(payload["code"], error)
            self.assertEqual(payload["articles"], [])
            self.assertEqual(payload["proposed_bindings"], [])
            self.assertFalse(payload["input_accepted"])
            self.assertEqual(payload["status"], "diagnostic/input_limit" if error == "input_limit" else "diagnostic/error")
            self.assertNotIn(SECRET, output + err.getvalue())
            if path:
                self.assertNotIn(path, output + err.getvalue())
        return payload

    def test_saved_full_snapshot_stays_candidate_without_reidentification(self):
        a = self.article()
        target = models.PushTarget.objects.create(name="C191 existing", group_id="c191-existing")
        models.QQPushDelivery.objects.create(article=a, target=target, status="sent",
                                            message_id="c191-sent-before", sent_at=timezone.now())
        p = self.invoke([a.pk])
        row = p["articles"][0]
        self.assertTrue(row["snapshot_accepted"])
        self.assertEqual(row["proposed_bindings"], [])
        self.assertEqual(row["persisted_snapshot_version"], "unversioned")
        self.assertEqual(row["canonical_article_mapping"], "unproven")
        self.assertEqual(row["source_coordinate_binding"], "unproven")
        self.assertEqual(row["candidates"][0]["entity_payload_sha256"],
                         "8523af9947b6dffa1cbe67d0cc6a680d6f4b5efb2ca094e73f0dc5f7f912945a")
        self.assertEqual(row["candidates"][0]["occurrence"],
                         {"field_name": "body", "start": 0, "end": 6, "matched_text": "Aurora"})

    def test_missing_fragment_and_bad_snapshot_have_distinct_gaps(self):
        cases = [({}, "persisted_resolution_missing"),
                 ({"entities": resolution()["entities"], "suppressed_entities": []}, "full_snapshot_unavailable"),
                 ({"article_entity_resolution": {"entities": []}}, "invalid_snapshot")]
        for metadata, code in cases:
            with self.subTest(code=code):
                a = self.article(metadata=metadata)
                p = self.invoke([a.pk]); row = p["articles"][0]
                self.assertEqual(row["code"], code)
                self.assertFalse(row["snapshot_accepted"])
                self.assertIsNone(row["counts"])
                self.assertEqual(row["proposed_bindings"], [])

    def test_first_seen_order_missing_row_and_no_extra_query(self):
        a = self.article(); b = self.article(); missing = max(a.pk, b.pk) + 99
        p = self.invoke([b.pk, a.pk, b.pk, missing])
        self.assertEqual(p["article_ids"], [b.pk, a.pk, missing])
        self.assertEqual([r["article_id"] for r in p["articles"]], [b.pk, a.pk, missing])
        self.assertEqual(p["articles"][-1]["code"], "article_not_found")
        self.assertEqual(p["status"], "completed_with_gaps")

    def test_id_lower_and_upper_literals(self):
        for pk, admitted in [(0, False), (1, True), (2, True),
                             (9223372036854775807, True), (9223372036854775808, False)]:
            with self.subTest(pk=pk):
                self.invoke([pk], error=None if admitted else "invalid_ids", queries=int(admitted))

    def test_id_raw_64_and_unique_16_then_one_over(self):
        self.invoke([7] * 64)
        self.invoke([7] * 65, error="input_limit", queries=0)
        self.invoke(list(range(1, 17)))
        self.invoke(list(range(1, 18)), error="input_limit", queries=0)

    def test_exact_audit_raw_count_rejects_zero_two_and_duplicate(self):
        for ids in ([], [7, 8], [7, 7]):
            with self.subTest(ids=ids):
                self.invoke(ids, path=SECRET, error="invalid_ids", queries=0)

    def test_write_flags_reject_before_file_or_database(self):
        for flags in (("--commit",), ("--translate-sync",), ("--commit", "--translate-sync")):
            with self.subTest(flags=flags):
                self.invoke([7], path=SECRET, extra=flags, error="invalid_flags", queries=0)

    def test_bundle_without_diagnostic_is_invalid_before_any_database(self):
        # Missing --binding-input on parent is ERROR; later asserts the new contract.
        out = io.StringIO()
        with self.assertNumQueries(0):
            try:
                call_command("reprocess_article_entities", "--binding-input", SECRET,
                             "--article-id", "7", "--json", stdout=out)
            except CommandError as exc:
                if str(exc) != "invalid_flags": raise
            else: self.fail("missing invalid_flags")
        self.assertEqual(json.loads(out.getvalue())["code"], "invalid_flags")

    def test_complete_literal_audit_uses_real_f01_and_original_core_conditionally(self):
        a = self.article(); data = canonical(envelope(a))
        with bundle_file(data) as path:
            p = self.invoke([a.pk], path=path, audit_core=1, f01_min=3)
        row = p["articles"][0]
        self.assertEqual(row["proposed_bindings"], [])
        self.assertEqual(row["canonical_article_mapping"], "unproven")
        self.assertEqual(row["source_coordinate_binding"], "unproven")
        self.assertEqual(self.last_core_arguments["source_document"], canonical(AUDIT_LITERAL["source_document"]))
        self.assertEqual(self.last_core_arguments["relationship_artifacts"],
                         {k: canonical(v) for k, v in AUDIT_LITERAL["relationship_artifacts"].items()})
        nested = row["explicit_input_audit"]["core_result"]
        self.assertEqual(nested["scope"], "conditional_structural_proposals_only")
        self.assertEqual(len(nested["proposed_bindings"]), 1)
        self.assertEqual(nested["proposed_bindings"][0]["target"]["canonical_id"], "horse-H1")
        self.assertEqual(nested["proposed_bindings"][0]["role"], "horse_subject")
        self.assertNotIn("caller_verified", row)

    def test_audit_scope_drift_never_enters_f01_or_core(self):
        a = self.article()
        for key in ("article_id", "observed_source_fields_sha256", "persisted_resolution_sha256"):
            b = envelope(a); b[key] = a.pk + 1 if key == "article_id" else "0" * 64
            with self.subTest(key=key), bundle_file(canonical(b)) as path:
                self.invoke([a.pk], path=path, error="input_scope_mismatch", queries=0 if key == "article_id" else 1)

    def test_audit_missing_row_and_missing_full_snapshot_reject(self):
        a = self.article(); b = envelope(a)
        models.NewsArticle.objects.filter(pk=a.pk).delete()
        with bundle_file(canonical(b)) as path:
            self.invoke([a.pk], path=path, error="article_not_found")
        a = self.article(); b = envelope(a)
        a.translation_metadata = {}; a.save(update_fields=["translation_metadata"])
        with bundle_file(canonical(b)) as path:
            self.invoke([a.pk], path=path, error="persisted_resolution_missing")

    def test_real_f01_bad_digest_rejects_before_core(self):
        a = self.article(); b = envelope(a)
        b["article_input"]["input_version"]["content_sha256"] = "0" * 64
        with bundle_file(canonical(b)) as path:
            self.invoke([a.pk], path=path, error="f01_invalid", f01_min=1)

    def test_real_core_shape_failure_has_no_fallback_or_success(self):
        a = self.article(); b = envelope(a)
        # Native key/types remain valid. Negative coordinate is original core's
        # semantic input error, not an envelope shape/parser failure.
        b["contexts"][0]["occurrence"]["start"] = -1
        with bundle_file(canonical(b)) as path:
            self.invoke([a.pk], path=path, error="binding_input_invalid", audit_core=1, f01_min=3)

    def test_artifact_bytes_are_not_repaired_to_match_digest(self):
        a = self.article(); b = envelope(a)
        key = next(iter(b["relationship_artifacts_base64"]))
        b["relationship_artifacts_base64"][key] = base64.b64encode(b'{"schema_version":"l01.relationship-assertions.v1","assertions":[]}').decode()
        with bundle_file(canonical(b)) as path:
            p = self.invoke([a.pk], path=path, audit_core=1, f01_min=3)
        self.assertEqual(p["articles"][0]["explicit_input_audit"]["core_result"]["proposed_bindings"], [])
        self.assertEqual(p["articles"][0]["proposed_bindings"], [])

    def test_strict_json_and_utf8_reject_before_database(self):
        data_codes = [(b"\xff" + SECRET.encode(), "input_utf8_invalid"),
                      (b'{"a":1,"a":2}', "input_json_invalid"),
                      (b'{"x":NaN}', "input_json_invalid"), (b'{"x":Infinity}', "input_json_invalid"),
                      (b'{"x":1e309}', "input_json_invalid"), (b'{"x":"\\ud800"}', "input_json_invalid"),
                      (b'{"x":"\\q"}', "input_json_invalid"), (b'{', "input_json_invalid"),
                      (b'{}', "input_shape_invalid")]
        for data, code in data_codes:
            with self.subTest(data=data), bundle_file(data) as path:
                self.invoke([7], path=path, error=code, queries=0)

    def test_forbidden_package_keys_cannot_override_database_resolution(self):
        a = self.article(); b = envelope(a); b["resolution_payload"] = resolution()
        with bundle_file(canonical(b)) as path:
            self.invoke([a.pk], path=path, error="input_shape_invalid", queries=0)

    def test_source_raw_fields_are_hashed_without_fallback_or_cleaning(self):
        a = self.article(body_ja_raw="<p>" + SECRET + "</p>", body_ja_normalized="")
        b = envelope(a)
        b["observed_source_fields_sha256"] = sha({"title_ja": "", "body_ja_raw": a.body_ja_raw,
                                                   "body_ja_normalized": a.body_ja_raw, "source_language": "en"})
        with bundle_file(canonical(b)) as path:
            self.invoke([a.pk], path=path, error="input_scope_mismatch")

    def test_oversized_returned_row_rejects_whole_invocation_not_prefix(self):
        a = self.article(); b = self.article(body_ja_raw=SECRET + "x" * 65537)
        self.invoke([a.pk, b.pk], error="input_limit")
        # Actual DB fixture intentionally returns the whole large TextField.
        # This proves application admission only, never a database allocation cap.

    def test_query_exception_is_redacted_without_retry(self):
        with patch.object(QuerySet, "_fetch_all", side_effect=RuntimeError(SECRET)):
            # state() must run outside this patch, so exercise public command directly.
            out = io.StringIO()
            with real_spies() as spies:
                try:
                    call_command("reprocess_article_entities", "--binding-diagnostics", "--article-id", "7",
                                 "--json", stdout=out)
                except CommandError as exc:
                    if str(exc) != "diagnostic_query_error": raise
                else: self.fail("query error was not rejected")
            self.assertEqual(spies["core"].call_count, 0)
            self.assertNotIn(SECRET, out.getvalue())
            self.assertLessEqual(len(out.getvalue().encode()), 1024)

    def test_final_output_rejection_does_not_retry_previously_admitted_core(self):
        # Controlled renderer input growth, not a fabricated F01/core result.
        # The real encoder must reject; the command must emit only error JSON.
        encode = getattr(service, "_binding_diagnostic_encode_output")
        def oversized(value, **kwargs):
            if kwargs.get("scope") == "invocation" and value.get("input_accepted") is not False:
                value = {**value, "test_padding": "x" * 262144}
            return encode(value, **kwargs)
        a = self.article()
        with bundle_file(canonical(envelope(a))) as path, \
                patch.object(service, "_binding_diagnostic_encode_output", side_effect=oversized):
            self.invoke([a.pk], path=path, error="input_limit", audit_core=1, f01_min=3)

    def test_default_final_output_rejection_has_zero_core(self):
        encode = getattr(service, "_binding_diagnostic_encode_output")
        def oversized(value, **kwargs):
            if kwargs.get("scope") == "invocation" and value.get("input_accepted") is not False:
                value = {**value, "test_padding": "x" * 262144}
            return encode(value, **kwargs)
        a = self.article()
        with patch.object(service, "_binding_diagnostic_encode_output", side_effect=oversized):
            self.invoke([a.pk], error="input_limit")

    def test_old_default_command_remains_dry_run_without_diagnostic_obligation(self):
        a = self.article(); before = self.state(); out = io.StringIO()
        call_command("reprocess_article_entities", "--article-id", str(a.pk), "--json", stdout=out)
        self.assertEqual(json.loads(out.getvalue())["mode"], "dry_run")
        self.assertEqual(self.state(), before)

    def test_old_commit_command_preserves_published_identity(self):
        a = self.article(workflow_status="published", published_to_web_at=timezone.now())
        published = a.published_to_web_at; out = io.StringIO()
        call_command("reprocess_article_entities", "--article-id", str(a.pk), "--commit", "--json", stdout=out)
        self.assertEqual(json.loads(out.getvalue())["mode"], "commit")
        a.refresh_from_db(); self.assertEqual(a.published_to_web_at, published)
        self.assertEqual(a.workflow_status, "published")
        self.assertTrue(models.OperationLog.objects.filter(action_type="article_entities_reprocessed", target_id=str(a.pk)).exists())


class DiagnosticResourceSeamTests(SimpleTestCase):
    """Proposed private seams in the existing service, not new public APIs.

    json_preflight(bytes, decoded=False) only scans budgets before tree parsing;
    native_preflight(value, scope=...) validates a returned row/aggregate;
    decode_package(dict) admits all sizes before any decode;
    read_file(str) returns bounded bytes; encode_output(value, as_json=True)
    returns one complete encoded output. All reject with CommandError(literal).
    These methods are absent on parent. Method-local getattr deliberately ERRORs.
    The seam names/signatures are reviewable candidate choices, not claims that
    production helpers already exist. No fallback stand-in executes a guard.
    """
    def setUp(self):
        self.guards = ExitStack(); self.addCleanup(self.guards.close)
        for module, name in ((f01, "parse_input"), (f01, "build_input"),
                             (core, "plan_article_entity_bindings")):
            original = getattr(module, name)
            for key, value in list(vars(service).items()):
                if value is original:
                    self.guards.enter_context(patch.object(service, key, side_effect=AssertionError("premature semantic call")))
            self.guards.enter_context(patch.object(module, name, side_effect=AssertionError("premature semantic call")))

    def helper(self, suffix):
        return getattr(service, "_binding_diagnostic_" + suffix)

    def rejected(self, fn, value, code="input_limit", **kwargs):
        with self.assertRaises(CommandError) as raised:
            fn(value, **kwargs)
        self.assertEqual(str(raised.exception), code)
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn(SECRET, str(raised.exception))

    def json_admit(self, data):
        # No full JSON tree allocation is permitted in this scanner.
        fn = self.helper("json_preflight")
        with patch.object(json, "loads", side_effect=AssertionError("tree parse before preflight")):
            return fn(data)

    def test_json_depth_24_admitted_25_rejected(self):
        self.json_admit(b"[" * 24 + b"0" + b"]" * 24)
        self.rejected(self.json_admit, b"[" * 25 + b"0" + b"]" * 25)

    def test_json_nodes_16384_admitted_16385_rejected(self):
        # root1 + 63*(array1+256 scalars) + last(array1+191/192) = 16384/5.
        for tail in (191, 192):
            value = [[0] * 256 for _ in range(63)] + [[0] * tail]
            data = canonical(value)
            if tail == 191: self.json_admit(data)
            else: self.rejected(self.json_admit, data)

    def test_array_256_and_object_128_then_one_over(self):
        for value, over in (([0] * 256, [0] * 257),
                            ({str(i): 0 for i in range(128)}, {str(i): 0 for i in range(129)})):
            self.json_admit(canonical(value)); self.rejected(self.json_admit, canonical(over))

    def test_utf8_key_256_and_value_262144_then_one_over(self):
        self.json_admit(canonical({"界" * 85 + "a": 0}))
        self.rejected(self.json_admit, canonical({"界" * 85 + "ab": 0}))
        self.json_admit(canonical(["x" * 262144]))
        self.rejected(self.json_admit, canonical(["x" * 262145]))

    def test_number_token_64_then_65_and_integer_bits_192_then_193(self):
        # Finite zero with fraction avoids conflating token length with int bits.
        self.json_admit(b"[0." + b"0" * 62 + b"]")
        self.rejected(self.json_admit, b"[0." + b"0" * 63 + b"]")
        fn = self.helper("native_preflight")
        fn({"n": (1 << 192) - 1}, scope="metadata")
        self.rejected(fn, {"n": 1 << 192}, scope="metadata")

    def test_brackets_inside_strings_and_escaped_major_keys(self):
        self.json_admit(canonical({"x": "[" * 25 + "]" * 25}))
        for key, count in (("identity_inputs", 8), ("relation_inputs", 16), ("contexts", 64)):
            at = canonical({key: [{}] * count}).replace(key.encode(), ("\\u%04x" % ord(key[0]) + key[1:]).encode())
            over = canonical({key: [{}] * (count + 1)}).replace(key.encode(), ("\\u%04x" % ord(key[0]) + key[1:]).encode())
            self.json_admit(at); self.rejected(self.json_admit, over)

    def test_artifact_count_8_then_9(self):
        self.json_admit(canonical({"relationship_artifacts_base64": {str(i): "" for i in range(8)}}))
        self.rejected(self.json_admit, canonical({"relationship_artifacts_base64": {str(i): "" for i in range(9)}}))

    def test_inner_f01_source_evidence_materials_and_reference_counts(self):
        for key, maximum in (("source_refs", 8), ("evidence", 32), ("materials", 32),
                             ("candidate_ids", 32), ("evidence_refs", 32)):
            for count in (maximum, maximum + 1):
                snapshot = {key: [None] * count} if key in ("evidence", "materials") else {"entity": {key: [None] * count}}
                data = canonical({"article_input": {"snapshot": snapshot}})
                if count == maximum: self.json_admit(data)
                else: self.rejected(self.json_admit, data)

    def test_f01_canonical_single_65536_and_total_262144_boundaries(self):
        fn = self.helper("decode_package")
        a = SimpleNamespace(pk=7, title_ja="", body_ja_raw="Aurora won.", body_ja_normalized="Aurora won.",
                            source_language="en", translation_metadata={"article_entity_resolution": resolution()})
        # Empty F01 wire is deliberate: this helper budgets only, not F01 parse.
        def doc(n): return {"x": "a" * (n - 8)}
        b = envelope(a); b["article_input"] = doc(65536); b["identity_inputs"] = []; b["relation_inputs"] = []
        fn(b)
        b["article_input"] = doc(65537); self.rejected(fn, b)
        b["article_input"] = doc(65536); b["identity_inputs"] = [doc(65536)] * 3
        fn(b)
        # 65536 + 2*65536 + 65535 + 2 = 262145, every doc <=65536.
        b["identity_inputs"] = [doc(65536)] * 2 + [doc(65535), {}]
        self.rejected(fn, b)

    def test_base64_individual_and_total_prediction_before_any_decode(self):
        fn = self.helper("decode_package")
        a = SimpleNamespace(pk=7, title_ja="", body_ja_raw="Aurora won.", body_ja_normalized="Aurora won.",
                            source_language="en", translation_metadata={"article_entity_resolution": resolution()})
        def padded(n): return b'{}' + b' ' * (n - 2)
        # Decoded semantic source {} may be refused downstream; only budget seam
        # handles decode, source shape belongs to original core.
        for source_n, artifact_n, count in ((131073, 2, 1), (2, 65537, 1), (131072, 65536, 3)):
            b = envelope(a); b["source_document_base64"] = base64.b64encode(padded(source_n)).decode()
            b["relationship_artifacts_base64"] = {format(i, "064x"): base64.b64encode(padded(artifact_n)).decode() for i in range(count)}
            with patch.object(base64, "b64decode", side_effect=AssertionError("decode before all predictions fit")):
                self.rejected(fn, b)
        b = envelope(a); b["source_document_base64"] = base64.b64encode(padded(131072)).decode()
        b["relationship_artifacts_base64"] = {format(i, "064x"): base64.b64encode(padded(65536)).decode() for i in range(2)}
        fn(b)  # decoded total exactly262144, source174764chars/artifact87384chars
        b["source_document_base64"] = base64.b64encode(padded(131072)).decode()
        b["relationship_artifacts_base64"][format(2, "064x")] = base64.b64encode(b" ").decode()
        with patch.object(base64, "b64decode", side_effect=AssertionError("total+1 decoded")):
            self.rejected(fn, b)

    def test_base64_alphabet_padding_whitespace_and_noncanonical_bits(self):
        fn = self.helper("decode_package")
        a = SimpleNamespace(pk=7, title_ja="", body_ja_raw="Aurora won.", body_ja_normalized="Aurora won.",
                            source_language="en", translation_metadata={"article_entity_resolution": resolution()})
        for invalid in ("!!!!", "e30=\n", "e30", "e=30", "e31="):
            b = envelope(a); b["source_document_base64"] = invalid
            self.rejected(fn, b, "input_base64_invalid")

    def test_decoded_assertions_32_and_total_128_then_one_over(self):
        fn = self.helper("decode_package")
        a = SimpleNamespace(pk=7, title_ja="", body_ja_raw="Aurora won.", body_ja_normalized="Aurora won.",
                            source_language="en", translation_metadata={"article_entity_resolution": resolution()})
        for counts, admitted in (([32], True), ([33], False), ([32] * 4, True), ([32] * 4 + [1], False)):
            b = envelope(a)
            b["relationship_artifacts_base64"] = {format(i, "064x"): base64.b64encode(canonical({"assertions": [{}] * n})).decode()
                                                  for i, n in enumerate(counts)}
            if admitted: fn(b)
            else: self.rejected(fn, b)

    def test_decoded_total_nodes_16384_then_one_over(self):
        fn = self.helper("decode_package")
        a = SimpleNamespace(pk=7, title_ja="", body_ja_raw="Aurora won.", body_ja_normalized="Aurora won.",
                            source_language="en", translation_metadata={"article_entity_resolution": resolution()})
        # Four decoded arrays, each root1 + 16*(array1+250)=4017.
        # Total 4*4017 + source(1+315)=16384; split source315 into two arrays
        # to respect256: source root1 + array1+157 + array1+156 =316.
        for n in (156, 157):
            b = envelope(a)
            source = [[0] * 157, [0] * n]  # 316/317nodes
            b["source_document_base64"] = base64.b64encode(canonical(source)).decode()
            b["relationship_artifacts_base64"] = {format(i, "064x"): base64.b64encode(canonical([[0] * 250 for _ in range(16)])).decode() for i in range(4)}
            if n == 156: fn(b)
            else: self.rejected(fn, b)

    def test_decoded_depth_and_source_fields(self):
        fn = self.helper("decode_package")
        a = SimpleNamespace(pk=7, title_ja="", body_ja_raw="Aurora won.", body_ja_normalized="Aurora won.",
                            source_language="en", translation_metadata={"article_entity_resolution": resolution()})
        for key, cap in (("title", 4096), ("body", 65536)):
            for size in (cap, cap + 1):
                b = envelope(a); doc = {"title": "", "body": ""}; doc[key] = "x" * size
                b["source_document_base64"] = base64.b64encode(canonical(doc)).decode()
                if size == cap: fn(b)
                else: self.rejected(fn, b)
        b = envelope(a); b["source_document_base64"] = base64.b64encode(b"[" * 25 + b"0" + b"]" * 25).decode()
        self.rejected(fn, b)

    def test_source_four_field_utf8_and_combined_caps(self):
        fn = self.helper("native_preflight")
        for key, cap in (("title_ja", 4096), ("body_ja_raw", 65536),
                         ("body_ja_normalized", 65536), ("source_language", 64)):
            row = dict.fromkeys(SOURCE_FIELDS, ""); row[key] = "x" * cap
            fn(row, scope="source")
            row[key] += "x"; self.rejected(fn, row, scope="source")
        row = dict(title_ja="", body_ja_raw="x" * 65536, body_ja_normalized="x" * 65536, source_language="")
        fn(row, scope="source"); row["source_language"] = "e"; self.rejected(fn, row, scope="source")
        row = dict.fromkeys(SOURCE_FIELDS, ""); row["source_language"] = None
        fn(row, scope="source")

    def test_source_canonical_escaped_bytes_262144_then_one_over(self):
        fn = self.helper("native_preflight")
        # Count bytes independently; control chars expand6x but fit per-fieldUTF8.
        row = dict.fromkeys(SOURCE_FIELDS, "")
        overhead = len(canonical(row))
        amount, rem = divmod(262144 - overhead, 6)
        row["body_ja_raw"] = "\x01" * amount + "x" * rem
        self.assertEqual(len(canonical(row)), 262144)
        fn(row, scope="source"); row["body_ja_raw"] += "x"
        self.rejected(fn, row, scope="source")

    def test_metadata_string_16384_then_one_over_and_native_bad_values(self):
        fn = self.helper("native_preflight")
        fn({"x": "x" * 16384}, scope="metadata")
        self.rejected(fn, {"x": "x" * 16385}, scope="metadata")
        for value in (float("nan"), float("inf"), object()):
            self.rejected(fn, {"x": value}, "invalid_snapshot", scope="metadata")
        cycle = []; cycle.append(cycle)
        self.rejected(fn, {"x": cycle}, "invalid_snapshot", scope="metadata")

    def test_metadata_canonical_262144_then_one_over(self):
        fn = self.helper("native_preflight")
        v = {str(i): "x" * 16000 for i in range(16)}
        v["pad"] = "x" * (262144 - len(canonical({**v, "pad": ""})))
        self.assertEqual(len(canonical(v)), 262144); fn(v, scope="metadata")
        v["pad"] += "x"; self.rejected(fn, v, scope="metadata")

    def test_native_huge_leaf_is_rejected_before_hash_copy_or_encoding(self):
        fn = self.helper("native_preflight")
        v = {"x": "x" * 16385}
        with patch.object(hashlib, "sha256", side_effect=AssertionError("hash before length guard")), \
                patch.object(copy, "deepcopy", side_effect=AssertionError("copy before length guard")), \
                patch.object(json, "dumps", side_effect=AssertionError("encode before length guard")), \
                patch.object(json.JSONEncoder, "iterencode", side_effect=AssertionError("encode before length guard")):
            self.rejected(fn, v, scope="metadata")

    def test_native_type_checks_do_not_call_metaclass_equality(self):
        fn = self.helper("native_preflight")
        class Meta(type):
            def __eq__(cls, other): raise AssertionError("metaclass equality")
            def __hash__(cls): raise AssertionError("metaclass hash")
        class Value(metaclass=Meta):
            def __iter__(self): raise AssertionError("iterator hook")
        self.rejected(fn, {"x": Value()}, "invalid_snapshot", scope="metadata")

    def test_resolution_lists_and_entity_reference_counts(self):
        fn = self.helper("native_preflight")
        for key, cap, item in (("entities", 32, resolution()["entities"][0]),
                               ("suppressed_candidates", 32, resolution()["entities"][0]),
                               ("accepted_terms", 32, {"term_type": "race", "source_ja": "A", "target_zh": "A",
                                                        "matched_text": "A", "race_grade": "", "priority": 0, "notes": ""}),
                               ("accepted_term_ids", 64, 7), ("machine_horse_tags", 32, "A")):
            v = resolution(); v[key] = [copy.deepcopy(item) for _ in range(cap)]
            fn(v, scope="resolution")
            v[key].append(copy.deepcopy(item)); self.rejected(fn, v, scope="resolution")
        for key in ("evidence", "conflict_flags", "external_horse_ids", "entity_evidence"):
            v = resolution(); v["entities"][0][key] = ["x"] * 64
            fn(v, scope="resolution"); v["entities"][0][key].append("x")
            self.rejected(fn, v, scope="resolution")

    def test_entity_string_4096_and_full_resolution_131072_then_one_over(self):
        fn = self.helper("native_preflight")
        v = resolution(); v["entities"][0]["matched_context"] = "x" * 4096
        fn(v, scope="resolution"); v["entities"][0]["matched_context"] += "x"
        self.rejected(fn, v, scope="resolution")
        v = resolution(); e = v["entities"][0]
        v["entities"] = [copy.deepcopy(e) for _ in range(32)]
        remaining = 131072 - len(canonical(v))
        for entity in v["entities"]:
            take = min(4096 - len(entity["matched_context"]), remaining)
            entity["matched_context"] += "x" * take; remaining -= take
        self.assertEqual(remaining, 0); self.assertEqual(len(canonical(v)), 131072)
        fn(v, scope="resolution")
        v["entities"][-1]["reason"] += "x"; self.rejected(fn, v, scope="resolution")

    def test_accepted_input_total_1048576_then_one_over(self):
        fn = self.helper("native_preflight")
        # aggregate seam consumes already accepted source+metadata values.
        v = []
        for _ in range(16):
            v.extend([dict.fromkeys(SOURCE_FIELDS, ""),
                      {"w": "x" * 16000, "x": "x" * 16384,
                       "y": "x" * 16384, "z": "x" * 16384}])
        v[0]["body_ja_raw"] = "x" * (1048576 - sum(len(canonical(x)) for x in v))
        self.assertEqual(sum(len(canonical(x)) for x in v), 1048576)
        fn(v, scope="aggregate")
        v[0]["body_ja_raw"] += "x"; self.rejected(fn, v, scope="aggregate")

    def test_output_complete_json_article_invocation_and_text_limits(self):
        fn = self.helper("encode_output")
        # Renderer accepts a complete payload, not a fake resolver/core result.
        # Raw string-sized synthetic fields exercise byte counting/atomic emit.
        for cap, scope in ((65536, "article"), (262144, "invocation")):
            v = {"x": "a" * (cap - 8)}
            self.assertEqual(len(canonical(v)), cap)
            encoded = fn(v, as_json=True, scope=scope)
            self.assertEqual(encoded, canonical(v))
            v["x"] += "a"; self.rejected(fn, v, as_json=True, scope=scope)
        self.assertEqual(fn("x" * 4096, as_json=False, scope="text"), b"x" * 4096)
        self.rejected(fn, "x" * 4097, as_json=False, scope="text")

    def test_id_native_bool_is_rejected_without_object_hooks(self):
        fn = self.helper("validate_ids")
        for value in (True, False, "7", 7.0):
            self.rejected(fn, [value], "invalid_ids", explicit=False)
        class Trap:
            def __int__(self): raise AssertionError("int hook")
            def __str__(self): raise AssertionError("str hook")
        self.rejected(fn, [Trap()], "invalid_ids", explicit=False)
        self.assertEqual(fn([7, 3, 7, 99], explicit=False), [7, 3, 99])
        self.assertEqual(fn([7], explicit=True), [7])
        for ids in ([], [7, 8], [7, 7]):
            self.rejected(fn, ids, "invalid_ids", explicit=True)


class DiagnosticFileAdmissionTests(SimpleTestCase):
    def setUp(self):
        DiagnosticResourceSeamTests.setUp(self)

    def read(self, path):
        return getattr(service, "_binding_diagnostic_read_file")(path)

    def reject(self, path, code):
        with self.assertRaises(CommandError) as raised:
            self.read(path)
        self.assertEqual(str(raised.exception), code)
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)

    def test_path_syntax_rejects_without_fspath_or_open(self):
        class PathTrap:
            def __fspath__(self): raise AssertionError("fspath")
        with patch.object(os, "open", side_effect=AssertionError("open before lexical guard")):
            for value in ("", "\0", "https://" + SECRET, "file:///" + SECRET, "//host/x", PathTrap()):
                self.reject(value, "input_location_invalid")

    def test_path_utf8_4096_and_components_64_then_one_over(self):
        # Missing final file is acceptable for stage-only boundary: reaches stat,
        # whereas +1 must fail input_limit without filesystem calls.
        for path in ("/" + "a/" * 63 + "b", "/" + "a" * 4095):
            with patch.object(os, "open", side_effect=OSError(errno.EACCES, SECRET)):
                self.reject(path, "input_io_error")
        with patch.object(os, "open", side_effect=AssertionError("over path opens")):
            self.reject("/" + "a/" * 64 + "b", "input_limit")
            self.reject("a" * 4097, "input_limit")

    def test_real_regular_file_exact_1mib_and_plus_one(self):
        fn = getattr(service, "_binding_diagnostic_read_file")
        for size in (1048576, 1048577):
            data = b"{}" + b" " * (size - 2)
            with bundle_file(data) as path:
                if size == 1048576: self.assertEqual(fn(path), data)
                else: self.reject(path, "input_limit")

    def test_parent_and_final_symlinks_are_rejected(self):
        # Safe temporary links only; no FIFO/device/socket is created.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(os.path.realpath(tmp)); (base / "actual").mkdir()
            (base / "actual" / "input").write_bytes(b"{}")
            (base / "link").symlink_to(base / "actual", target_is_directory=True)
            (base / "filelink").symlink_to(base / "actual" / "input")
            self.reject(str(base / "link" / "input"), "input_file_type")
            self.reject(str(base / "filelink"), "input_file_type")

    @contextmanager
    def fd_double(self, *, visible=stat.S_IFREG, final=stat.S_IFREG, data=b"{}", changed=False,
                  read_error=False, partial=False, advertised=None):
        # Virtual descriptors only. Instrument no more than3 simultaneously owned,
        # close on every path, bounded n, bytes<=1MiB+1, <=32 actual reads.
        owned = set(); calls = []; opens = []; position = 0; stats = 0
        def meta(mode, size):
            return SimpleNamespace(st_mode=mode | 0o600, st_size=size, st_dev=1, st_ino=9,
                                   st_mtime_ns=1, st_ctime_ns=1)
        def open_fd(path, flags, *args, **kw):
            fd = 100 + len(opens); opens.append((path, flags, kw)); owned.add(fd)
            self.assertLessEqual(len(owned), 3)
            return fd
        def close_fd(fd):
            self.assertIn(fd, owned); owned.remove(fd)
        def stat_fd(fd):
            nonlocal stats
            self.assertIn(fd, owned)
            flags = opens[fd - 100][1]
            if flags & os.O_DIRECTORY: return meta(stat.S_IFDIR, 0)
            stats += 1; m = meta(final, len(data) if advertised is None else advertised)
            if changed and stats > 1: m.st_ctime_ns = 2
            return m
        def read_fd(fd, n):
            nonlocal position
            self.assertIn(fd, owned); self.assertTrue(0 < n <= 65536)
            self.assertEqual(final, stat.S_IFREG, "read special FD")
            calls.append(n); self.assertLessEqual(len(calls), 32)
            if read_error: raise OSError(errno.EIO, SECRET)
            take = min(n, 1) if partial else n
            chunk = data[position:position + take]; position += len(chunk)
            self.assertLessEqual(position, 1048577)
            return chunk
        with patch.object(os, "open", side_effect=open_fd), patch.object(os, "close", side_effect=close_fd), \
                patch.object(os, "stat", return_value=meta(visible, len(data) if advertised is None else advertised)), \
                patch.object(os, "fstat", side_effect=stat_fd), patch.object(os, "read", side_effect=read_fd):
            try: yield calls, opens
            finally: self.assertEqual(owned, set(), "FD leak")

    def test_nonregular_stat_modes_are_never_opened_for_content(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFDIR):
            with self.subTest(mode=mode), self.fd_double(visible=mode) as (reads, opens):
                self.reject("/input", "input_file_type")
                self.assertEqual(reads, [])
                self.assertTrue(all(flags & os.O_DIRECTORY for _, flags, _ in opens))

    def test_regular_stat_to_special_fd_race_never_reads(self):
        with self.fd_double(final=stat.S_IFIFO) as (reads, opens):
            self.reject("/input", "input_file_type"); self.assertEqual(reads, [])
            final_flags = opens[-1][1]
            for flag in (os.O_NOFOLLOW, os.O_NONBLOCK, os.O_CLOEXEC):
                self.assertTrue(final_flags & flag)

    def test_growth_detection_budget_and_short_read_32_call_limit(self):
        with self.fd_double(data=b"x" * 1048578, advertised=0) as (reads, _):
            self.reject("/input", "input_limit")
            self.assertLessEqual(sum(reads), 1048577)
        with self.fd_double(data=b"x" * 31, partial=True) as (reads, _):
            self.assertEqual(self.read("/input"), b"x" * 31); self.assertEqual(len(reads), 32)
        with self.fd_double(data=b"x" * 32, partial=True) as (reads, _):
            self.reject("/input", "input_limit"); self.assertEqual(len(reads), 32)

    def test_changed_fstat_and_io_failure_close_without_retry(self):
        with self.fd_double(changed=True): self.reject("/input", "input_changed")
        with self.fd_double(read_error=True): self.reject("/input", "input_io_error")
        with patch.object(os, "open", side_effect=OSError(errno.EACCES, SECRET)):
            self.reject("/" + SECRET, "input_io_error")

    def test_missing_nofollow_capability_fails_closed(self):
        with patch.dict(os.__dict__), patch.object(os, "open", side_effect=AssertionError("weak open")):
            del os.O_NOFOLLOW
            self.reject("/input", "input_io_error")

"""L01 literal synthetic contracts. No ORM, producer authentication or write authority."""
import copy
import hashlib
import json
import unittest

from stable.services import content_contracts as f01
from stable.services.article_entity_binding import BindingInputError, plan_article_entity_bindings

# Literal C184 fixture, embedded here; no runtime packet needed by the tests.
LITERAL = {'status': 'SYNTHETIC_STATIC_DATA_ONLY_NOT_PARSER_OR_TEST_EXECUTED', 'article_input': {'schema_version': 'f01.v1', 'evaluated_at': '2026-10-17T11:30:00Z', 'policy_ref': 'f01-policy-draft', 'input_version': {'schema_version': 'f01.input.v1', 'scope': ['entity', 'evidence', 'materials', 'policy_ref', 'protection'], 'content_sha256': 'c7ee1a963061482f3adaa6a362074f336a5c70db9684d50031f273e6ec0ab76e', 'generations': {'owner': None, 'schedule': None, 'enrollment': None, 'source_set': None}}, 'snapshot': {'entity': {'kind': 'article', 'canonical_id': 'article-A1', 'identity_state': 'verified', 'source_refs': [], 'candidate_ids': [], 'evidence_refs': ['E-doc']}, 'materials': [], 'evidence': [{'evidence_id': 'E-doc', 'provider_key': 'fixture-official_operator', 'source_class': 'official_operator', 'independence_key': 'fixture-origin-e-date', 'capability': 'identity', 'artifact_sha256': '88435301d532cbe53b77cba03f3b3377498d6fb2c98822b56ea14e21d5cce7c4', 'locator': '/body', 'observed_at': '2026-10-17T11:00:00Z', 'source_time': {'precision': 'unknown', 'published_at': None, 'last_absent_at': None, 'first_seen_at': '2026-10-17T11:00:00Z'}, 'contract_ref': {'route_digest': 'e050efd0a0e23d85c6a1f4dc256aaf88bc6179d0a5a69a50fe274c3e414ddda7', 'contract_digest': '304aeb6aeb9281204cf0b2723b2d0d855d70719de14de5aa270752aa275e307b', 'proof_digest': 'b5a666eb4586fa4015f3c37018c0e6d6f37d28297d8484dd74150d488b0a4338', 'valid_until': '2026-10-30T00:00:00Z', 'revoked': False}}], 'protection': {'paused': False, 'fields': [], 'modules': [], 'reason': 'synthetic L01 fixture', 'actor_ref': None, 'changed_at': None, 'protection_sha256': '9c8f6addb1e76b4c6545cdfca366f045406c06d0934eaef627003bfad5790b63'}, 'policy_ref': 'f01-policy-draft'}}, 'identity_inputs': [{'schema_version': 'f01.v1', 'evaluated_at': '2026-10-17T11:30:00Z', 'policy_ref': 'f01-policy-draft', 'input_version': {'schema_version': 'f01.input.v1', 'scope': ['entity', 'evidence', 'materials', 'policy_ref', 'protection'], 'content_sha256': '622e9bc82ccc0a48428a5f160c8bdf080514f8f65e0a602b10e2af67ab594f30', 'generations': {'owner': None, 'schedule': None, 'enrollment': None, 'source_set': None}}, 'snapshot': {'entity': {'kind': 'horse', 'canonical_id': 'horse-H1', 'identity_state': 'verified', 'source_refs': [], 'candidate_ids': [], 'evidence_refs': ['E-horse']}, 'materials': [], 'evidence': [{'evidence_id': 'E-horse', 'provider_key': 'fixture-official_operator', 'source_class': 'official_operator', 'independence_key': 'fixture-origin-e-date', 'capability': 'identity', 'artifact_sha256': '18bc562d6d3776902780115a606ac946ed75f4991cc4fadd2f456bbb0cbbc081', 'locator': '/canonical_id', 'observed_at': '2026-10-17T11:00:00Z', 'source_time': {'precision': 'unknown', 'published_at': None, 'last_absent_at': None, 'first_seen_at': '2026-10-17T11:00:00Z'}, 'contract_ref': {'route_digest': 'e050efd0a0e23d85c6a1f4dc256aaf88bc6179d0a5a69a50fe274c3e414ddda7', 'contract_digest': '304aeb6aeb9281204cf0b2723b2d0d855d70719de14de5aa270752aa275e307b', 'proof_digest': 'b5a666eb4586fa4015f3c37018c0e6d6f37d28297d8484dd74150d488b0a4338', 'valid_until': '2026-10-30T00:00:00Z', 'revoked': False}}], 'protection': {'paused': False, 'fields': [], 'modules': [], 'reason': 'synthetic L01 fixture', 'actor_ref': None, 'changed_at': None, 'protection_sha256': '9c8f6addb1e76b4c6545cdfca366f045406c06d0934eaef627003bfad5790b63'}, 'policy_ref': 'f01-policy-draft'}}], 'relation_inputs': [{'schema_version': 'f01.v1', 'evaluated_at': '2026-10-17T11:30:00Z', 'policy_ref': 'f01-policy-draft', 'input_version': {'schema_version': 'f01.input.v1', 'scope': ['entity', 'evidence', 'materials', 'policy_ref', 'protection'], 'content_sha256': '8849b9b2da7cbb07bf0c263cbf879c6d34e99658e5d062492b04a244811e9abc', 'generations': {'owner': None, 'schedule': None, 'enrollment': None, 'source_set': None}}, 'snapshot': {'entity': {'kind': 'horse', 'canonical_id': 'horse-H1', 'identity_state': 'verified', 'source_refs': [], 'candidate_ids': [], 'evidence_refs': ['E-rel']}, 'materials': [{'capability': 'relationship', 'maturity': 'confirmed', 'completeness': 'complete', 'validation': 'passed', 'revision_ref': 'l01-rel-rev1', 'supersedes_ref': None, 'evidence_refs': ['E-rel'], 'data': {'source_ref': 'article-A1', 'target_ref': 'horse-H1', 'relation_type': 'horse_subject'}}], 'evidence': [{'evidence_id': 'E-rel', 'provider_key': 'fixture-official_operator', 'source_class': 'official_operator', 'independence_key': 'fixture-origin-e-date', 'capability': 'relationship', 'artifact_sha256': '6969e238e208a1f525c6a093cfbc63e267915ceb84b04531f934887cfc9f6318', 'locator': '/assertions/0', 'observed_at': '2026-10-17T11:00:00Z', 'source_time': {'precision': 'unknown', 'published_at': None, 'last_absent_at': None, 'first_seen_at': '2026-10-17T11:00:00Z'}, 'contract_ref': {'route_digest': 'e050efd0a0e23d85c6a1f4dc256aaf88bc6179d0a5a69a50fe274c3e414ddda7', 'contract_digest': '304aeb6aeb9281204cf0b2723b2d0d855d70719de14de5aa270752aa275e307b', 'proof_digest': 'b5a666eb4586fa4015f3c37018c0e6d6f37d28297d8484dd74150d488b0a4338', 'valid_until': '2026-10-30T00:00:00Z', 'revoked': False}}], 'protection': {'paused': False, 'fields': [], 'modules': [], 'reason': 'synthetic L01 fixture', 'actor_ref': None, 'changed_at': None, 'protection_sha256': '9c8f6addb1e76b4c6545cdfca366f045406c06d0934eaef627003bfad5790b63'}, 'policy_ref': 'f01-policy-draft'}}], 'source_document': {'title': '', 'body': 'Aurora won.'}, 'source_document_raw_utf8_canonical_sha256': '88435301d532cbe53b77cba03f3b3377498d6fb2c98822b56ea14e21d5cce7c4', 'resolution_payload': {'source_language': 'en', 'entities': [{'entity_type': 'horse', 'matched_text': 'Aurora', 'canonical_text': 'Aurora', 'target_zh': '', 'field_name': 'body', 'start': 0, 'end': 6, 'confidence': 99, 'evidence': ['synthetic structured identity occurrence'], 'conflict_flags': [], 'needs_preserve': True, 'term_id': None, 'external_horse_ids': [], 'priority': 0, 'term_type': 'horse', 'classification': 'confirmed_horse', 'reason': 'synthetic_control', 'matched_context': 'Aurora won.', 'entity_evidence': ['synthetic structured identity occurrence'], 'matched_span': [0, 6], 'primary_external_horse_id': ''}], 'suppressed_candidates': [], 'accepted_terms': [], 'accepted_term_ids': [], 'machine_horse_tags': []}, 'relationship_artifacts': {'6969e238e208a1f525c6a093cfbc63e267915ceb84b04531f934887cfc9f6318': {'schema_version': 'l01.relationship-assertions.v1', 'assertions': [{'assertion_id': 'assertion-1', 'revision_ref': 'l01-rel-rev1', 'article': {'kind': 'article', 'canonical_id': 'article-A1', 'input_wire_sha256': 'bcdd2116104277592087d5d0d21f1b76fdc4a772724edb37840ce61f0c278b5a', 'source_document_sha256': '88435301d532cbe53b77cba03f3b3377498d6fb2c98822b56ea14e21d5cce7c4'}, 'occurrence': {'field_name': 'body', 'start': 0, 'end': 6, 'matched_text': 'Aurora', 'entity_payload_sha256': '8523af9947b6dffa1cbe67d0cc6a680d6f4b5efb2ca094e73f0dc5f7f912945a'}, 'target': {'kind': 'horse', 'canonical_id': 'horse-H1', 'identity_input_wire_sha256': '030500cd157cf91a4b115d42d7fb1b3434bae43a2b53f82f7461d7408ab07a06', 'source_ref': None}, 'role': 'horse_subject', 'status': 'active'}]}}, 'contexts': [{'occurrence': {'field_name': 'body', 'start': 0, 'end': 6, 'matched_text': 'Aurora', 'entity_payload_sha256': '8523af9947b6dffa1cbe67d0cc6a680d6f4b5efb2ca094e73f0dc5f7f912945a'}, 'target_identity_input_wire_sha256': '030500cd157cf91a4b115d42d7fb1b3434bae43a2b53f82f7461d7408ab07a06', 'source_ref': None, 'role': 'horse_subject', 'relation_input_wire_sha256': 'a022e32f109513e7265f0e818c9b54babbcf79e68d36cb11ffbb89ee1c30aa1c', 'evidence_id': 'E-rel'}], 'hash_definition': 'SHA256 of json.dumps(value,sort_keys=True,separators=(comma,colon),ensure_ascii=False,allow_nan=False).encode(UTF8); artifacts here stored as JSON objects only, future test must serialize to exact canonical bytes', 'expected_conditional_result': 'one proposed_binding if every F01 document parses and all structural/state predicates match; not source authenticity or production authorization', 'hash_graph': 'source bytes -> article input; identity source -> identity input; both input wire hashes -> assertion bytes -> relation evidence/material -> separate relation input -> sidecar; no circular fingerprint'}


def raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def document(value):
    # Real public serializer, never a mocked passed gate.
    return f01.build_input(value["snapshot"], evaluated_at=value["evaluated_at"],
                           policy_ref=value["policy_ref"], generations=value["input_version"]["generations"])


def fixture():
    c = copy.deepcopy(LITERAL)
    c["packs"] = list(c.pop("relationship_artifacts").values())
    c["relation_indices"] = [0]
    c["evidence_pack_indices"] = [[0]]
    return c


def refresh_article(c):
    docsha = digest(c["source_document"])
    c["article_input"]["snapshot"]["evidence"][0]["artifact_sha256"] = docsha
    a = document(c["article_input"])
    for pack in c["packs"]:
        for claim in pack["assertions"]:
            claim["article"].update(input_wire_sha256=digest(a.to_dict()), source_document_sha256=docsha)


def refresh_occurrence(c, index=0):
    entity = c["resolution_payload"]["entities"][index]
    occ = {k: entity[k] for k in ("field_name", "start", "end", "matched_text")}
    occ["entity_payload_sha256"] = digest(entity)
    c["contexts"][index]["occurrence"] = copy.deepcopy(occ)
    c["packs"][index]["assertions"][0]["occurrence"] = copy.deepcopy(occ)


def retarget(c, kind, canonical, role, *, align_entity=True):
    t = c["identity_inputs"][0]
    t["snapshot"]["entity"].update(kind=kind, canonical_id=canonical)
    target = document(t)
    c["relation_inputs"][0]["snapshot"]["entity"] = copy.deepcopy(target.to_dict()["snapshot"]["entity"])
    c["relation_inputs"][0]["snapshot"]["entity"]["evidence_refs"] = ["E-rel"]
    claim = c["packs"][0]["assertions"][0]
    claim["target"].update(kind=kind, canonical_id=canonical, identity_input_wire_sha256=digest(target.to_dict()))
    claim["role"] = role
    c["contexts"][0].update(target_identity_input_wire_sha256=digest(target.to_dict()), role=role)
    m = c["relation_inputs"][0]["snapshot"]["materials"][0]
    m["data"].update(target_ref=canonical, relation_type=role)
    if align_entity and kind == "race_event":
        # Actual N03 _make_entity("term", ..., term=RACE) wire, not a horse.
        e = c["resolution_payload"]["entities"][0]
        e.update(entity_type="term", term_type="race", classification="", term_id=501, confidence=95,
                 evidence=["formal_term"], entity_evidence=["formal_term"], needs_preserve=False,
                 reason="", matched_context="")
        refresh_occurrence(c)


class ArticleEntityBindingTests(unittest.TestCase):
    def invoke(self, c, *, overrides=None):
        before = copy.deepcopy(c)
        article = document(c["article_input"])
        identities = [document(x) for x in c["identity_inputs"]]
        artifacts = {digest(x): raw(x) for x in c["packs"]}
        relations = []
        for i, original in enumerate(c["relation_inputs"]):
            value = copy.deepcopy(original)
            for e, pack_index in zip(value["snapshot"]["evidence"], c["evidence_pack_indices"][i]):
                e["artifact_sha256"] = digest(c["packs"][pack_index])
            relations.append(document(value))
        contexts = copy.deepcopy(c["contexts"])
        for context, index in zip(contexts, c["relation_indices"]):
            context["relation_input_wire_sha256"] = digest(relations[index].to_dict())
        # Every semantic case reaches real F01 parsing before L01.
        for doc in [article, *identities, *relations]:
            self.assertEqual(f01.parse_input(doc.to_json()).to_dict(), doc.to_dict())
        arguments = dict(resolution_payload=c["resolution_payload"], article_input=article,
            identity_inputs=identities, relation_inputs=relations, source_document=raw(c["source_document"]),
            relationship_artifacts=artifacts, contexts=contexts)
        if overrides is not None:
            arguments.update(overrides)
        result = plan_article_entity_bindings(**arguments)
        self.assertEqual(c, before)
        self.assertEqual(result["scope"], "conditional_structural_proposals_only")
        return result

    def candidate(self, c, reason=None):
        result = self.invoke(c)
        self.assertEqual(result["proposed_bindings"], [])
        self.assertTrue(result["candidates"])
        if reason:
            self.assertIn(reason, {v for item in result["candidates"] for v in item["reasons"]})
        return result

    def test_complete_literal_subject_control(self):
        r = self.invoke(fixture())
        self.assertEqual(len(r["proposed_bindings"]), 1)
        self.assertEqual(r["candidates"], [])
        self.assertEqual(r["proposed_bindings"][0]["target"]["canonical_id"], "horse-H1")
        self.assertEqual(r["proposed_bindings"][0]["role"], "horse_subject")

    def test_same_name_distinct_horses_are_not_merged(self):
        c = fixture()
        other = fixture()
        retarget(other, "horse", "horse-H2", "horse_subject")
        c["source_document"]["body"] = "Aurora won. Aurora ran."
        e = copy.deepcopy(other["resolution_payload"]["entities"][0]); e.update(start=12, end=18, matched_span=[12, 18])
        c["resolution_payload"]["entities"].append(e)
        c["identity_inputs"].append(other["identity_inputs"][0])
        c["relation_inputs"].append(other["relation_inputs"][0]); c["packs"].append(other["packs"][0])
        c["contexts"].append(other["contexts"][0]); c["relation_indices"].append(1); c["evidence_pack_indices"].append([1])
        refresh_article(c); refresh_occurrence(c, 1)
        r = self.invoke(c)
        self.assertEqual({x["target"]["canonical_id"] for x in r["proposed_bindings"]}, {"horse-H1", "horse-H2"})
        self.assertEqual(r["candidates"], [])

    def test_historical_edition_is_explicit_not_nearest_year(self):
        c = fixture(); retarget(c, "race_event", "event-E2025", "event_historical")
        r = self.invoke(c)
        self.assertEqual(r["proposed_bindings"][0]["target"]["canonical_id"], "event-E2025")
        self.assertEqual(r["proposed_bindings"][0]["role"], "event_historical")

    def test_series_only_does_not_select_event(self):
        c = fixture(); retarget(c, "race_event", "event-E2025", "series_only")
        self.candidate(c, "role_not_bindable")

    def test_no_chinese_name_still_has_identity(self):
        c = fixture(); self.assertEqual(c["resolution_payload"]["entities"][0]["target_zh"], "")
        self.assertEqual(self.invoke(c)["proposed_bindings"][0]["occurrence"]["matched_text"], "Aurora")

    def test_parent_and_offspring_remain_candidates(self):
        for role in ("parent", "offspring", "unknown"):
            with self.subTest(role=role):
                c = fixture(); retarget(c, "horse", "horse-H1", role); self.candidate(c, "role_not_bindable")

    def test_same_occurrence_two_target_claims_are_ambiguous(self):
        c = fixture(); retarget(c, "race_event", "event-E2025", "event_current")
        other = fixture(); retarget(other, "race_event", "event-E2026", "event_current")
        c["identity_inputs"].extend(other["identity_inputs"]); c["relation_inputs"].extend(other["relation_inputs"])
        c["packs"].extend(other["packs"]); c["contexts"].extend(other["contexts"])
        c["relation_indices"].append(1); c["evidence_pack_indices"].append([1])
        self.candidate(c, "claim_conflict")

    def test_distinct_occurrence_events_may_coexist(self):
        c = fixture(); retarget(c, "race_event", "event-E2025", "event_historical")
        other = fixture(); retarget(other, "race_event", "event-E2026", "event_current")
        c["source_document"]["body"] = "Aurora won. Aurora ran."
        e = copy.deepcopy(other["resolution_payload"]["entities"][0]); e.update(start=12, end=18, matched_span=[12, 18])
        c["resolution_payload"]["entities"].append(e); c["identity_inputs"].extend(other["identity_inputs"])
        c["relation_inputs"].extend(other["relation_inputs"]); c["packs"].extend(other["packs"]); c["contexts"].extend(other["contexts"])
        c["relation_indices"].append(1); c["evidence_pack_indices"].append([1]); refresh_article(c); refresh_occurrence(c, 1)
        self.assertEqual({x["target"]["canonical_id"] for x in self.invoke(c)["proposed_bindings"]}, {"event-E2025", "event-E2026"})

    def test_source_only_verified_is_not_canonical(self):
        c = fixture(); e = c["identity_inputs"][0]["snapshot"]["entity"]
        e.update(canonical_id=None, source_refs=[{"source":"s","namespace":"horse","external_id":"1"}])
        self.candidate(c)

    def test_full_namespace_not_bare_external_id(self):
        c = fixture(); c["contexts"][0]["source_ref"] = {"source":"other","namespace":"race","external_id":"1"}
        self.candidate(c, "target_binding_mismatch")

    def test_payload_staleness_commonword_and_suppressed(self):
        for mutation in ("stale", "common_word", "ambiguous", "conflict", "suppressed"):
            with self.subTest(mutation=mutation):
                c = fixture(); e = c["resolution_payload"]["entities"][0]
                if mutation == "stale": e["reason"] = "new-version"
                elif mutation == "conflict": e["conflict_flags"] = ["identity_conflict"]; refresh_occurrence(c)
                elif mutation == "suppressed": c["resolution_payload"]["suppressed_candidates"].append(copy.deepcopy(e))
                else: e["entity_type"] = mutation; refresh_occurrence(c)
                self.candidate(c)

    def test_duplicate_deterministic_and_input_immutable(self):
        c = fixture(); c["contexts"] *= 2; c["relation_indices"] *= 2
        a = self.invoke(c); c["contexts"].reverse(); c["relation_indices"].reverse()
        self.assertEqual(a, self.invoke(c)); self.assertEqual(len(a["proposed_bindings"]), 1)

    def test_valid_f01_relation_belongs_to_other_article(self):
        c = fixture(); claim = c["packs"][0]["assertions"][0]
        claim["article"]["canonical_id"] = "article-A2"
        c["relation_inputs"][0]["snapshot"]["materials"][0]["data"]["source_ref"] = "article-A2"
        self.candidate(c, "article_binding_mismatch")

    def test_same_article_old_wire_version(self):
        c = fixture(); c["packs"][0]["assertions"][0]["article"]["input_wire_sha256"] = "a" * 64
        self.candidate(c, "article_binding_mismatch")

    def test_other_occurrence_cannot_support_current_span(self):
        c = fixture(); c["packs"][0]["assertions"][0]["occurrence"].update(start=12, end=18)
        self.candidate(c, "occurrence_binding_mismatch")

    def test_parent_evidence_cannot_be_redeclared_subject(self):
        c = fixture(); c["packs"][0]["assertions"][0]["role"] = "parent"
        c["relation_inputs"][0]["snapshot"]["materials"][0]["data"]["relation_type"] = "parent"
        self.candidate(c, "role_binding_mismatch")

    def test_reverse_relation_material_direction(self):
        c = fixture(); c["relation_inputs"][0]["snapshot"]["materials"][0]["data"].update(source_ref="horse-H1", target_ref="article-A1")
        self.candidate(c, "material_binding_mismatch")

    def test_other_target_or_edition_not_rebound(self):
        c = fixture(); retarget(c, "race_event", "event-E2025", "event_historical")
        c["contexts"][0]["target_identity_input_wire_sha256"] = "b" * 64
        self.candidate(c, "target_binding_mismatch")

    def test_material_conflict_rejected_and_pending(self):
        for state in ("conflict", "rejected", "pending"):
            with self.subTest(state=state):
                c = fixture(); c["relation_inputs"][0]["snapshot"]["materials"][0]["validation"] = state
                self.candidate(c, "material_not_eligible")

    def test_material_maturity_and_completeness(self):
        for field, value in (("maturity","unknown"),("maturity","provisional"),("maturity","corrected"),("completeness","partial"),("completeness","unknown")):
            with self.subTest(field=field, value=value):
                c = fixture(); m = c["relation_inputs"][0]["snapshot"]["materials"][0]; m[field] = value
                if value == "corrected": m["supersedes_ref"] = "prior-revision"
                self.candidate(c, "material_not_eligible")

    def test_contract_revocation_expiry_boundary_and_future(self):
        for mode in ("revoked", "expired", "equal", "future"):
            with self.subTest(mode=mode):
                c = fixture(); e = c["relation_inputs"][0]["snapshot"]["evidence"][0]
                if mode == "revoked": e["contract_ref"]["revoked"] = True
                elif mode == "expired": e["contract_ref"]["valid_until"] = "2026-10-16T11:30:00Z"
                elif mode == "equal": e["contract_ref"]["valid_until"] = "2026-10-17T11:30:00Z"
                else: e["observed_at"] = "2026-10-18T11:30:00Z"
                self.candidate(c, "evidence_not_eligible")

    def test_same_span_different_payload_and_role_cannot_split_group(self):
        c = fixture(); e = copy.deepcopy(c["resolution_payload"]["entities"][0]); e["reason"] = "different"
        c["resolution_payload"]["entities"].append(e)
        self.candidate(c, "occurrence_conflict")
        c = fixture(); claim = copy.deepcopy(c["packs"][0]["assertions"][0]); claim.update(assertion_id="second", role="parent")
        c["packs"][0]["assertions"].append(claim)
        self.candidate(c, "claim_conflict")

    def test_artifact_reference_and_material_evidence_are_required(self):
        for mode in ("locator", "capability", "material_ref"):
            with self.subTest(mode=mode):
                c = fixture(); e = c["relation_inputs"][0]["snapshot"]["evidence"][0]
                if mode == "locator": e["locator"] = "/assertions/01"
                elif mode == "capability": e["capability"] = "identity"
                else: c["relation_inputs"][0]["snapshot"]["materials"][0]["evidence_refs"] = []
                self.candidate(c)

    def test_assertion_revocation_and_supersession(self):
        for status in ("revoked", "superseded"):
            with self.subTest(status=status):
                c = fixture(); c["packs"][0]["assertions"][0]["status"] = status
                self.candidate(c, "assertion_not_active")

    def test_paused_article_and_inconsistent_evaluation(self):
        c = fixture(); c["article_input"]["snapshot"]["protection"]["paused"] = True; refresh_article(c)
        self.candidate(c, "input_not_eligible")
        c = fixture(); c["relation_inputs"][0]["evaluated_at"] = "2026-10-17T11:31:00Z"
        self.candidate(c, "evaluation_mismatch")

    def test_structural_errors_are_not_semantic_red(self):
        c = fixture(); c["contexts"][0]["occurrence"]["start"] = True
        with self.assertRaisesRegex(BindingInputError, "structure"):
            self.invoke(c)

    def _metaclass_boundary(self, raising):
        hooks = []
        class HostileMeta(type):
            def __eq__(cls, other):
                hooks.append("eq")
                if raising:
                    raise AssertionError("untrusted metaclass equality executed")
                return False
            def __ne__(cls, other):
                hooks.append("ne")
                if raising:
                    raise AssertionError("untrusted metaclass inequality executed")
                return True
        class Alien(metaclass=HostileMeta):
            pass
        for argument in ("resolution_payload", "identity_inputs", "relation_inputs", "contexts", "article_input", "relationship_artifacts"):
            with self.subTest(argument=argument, raising=raising):
                with self.assertRaisesRegex(BindingInputError, "^structure$"):
                    self.invoke(fixture(), overrides={argument: Alien()})
                self.assertEqual(hooks, [])
        bad = copy.deepcopy(LITERAL["resolution_payload"])
        bad["entities"][0]["confidence"] = Alien()
        with self.assertRaisesRegex(BindingInputError, "^structure$"):
            self.invoke(fixture(), overrides={"resolution_payload": bad})
        self.assertEqual(hooks, [])

    def test_recording_metaclass_is_never_called_at_public_boundary(self):
        self._metaclass_boundary(False)

    def test_raising_metaclass_is_never_called_at_public_boundary(self):
        self._metaclass_boundary(True)

    def test_n03_existing_horse_matrix_keeps_positive_bindings(self):
        for entity_type, term_type, classification in (
            ("horse", "horse", "confirmed_horse"), ("horse", "horse", ""),
            ("unknown_horse", "", "confirmed_horse"), ("unknown_horse", "", ""),
        ):
            with self.subTest(entity_type=entity_type, term_type=term_type, classification=classification):
                c = fixture()
                c["resolution_payload"]["entities"][0].update(entity_type=entity_type, term_type=term_type, classification=classification)
                refresh_occurrence(c)
                r = self.invoke(c)
                self.assertEqual(len(r["proposed_bindings"]), 1)
                self.assertEqual(r["proposed_bindings"][0]["target"]["kind"], "horse")
                self.assertEqual(r["candidates"], [])

    def test_horse_occurrence_cannot_be_redeclared_race_event(self):
        c = fixture()
        retarget(c, "race_event", "event-E2025", "event_historical", align_entity=False)
        self.assertEqual(c["resolution_payload"]["entities"][0]["classification"], "confirmed_horse")
        self.candidate(c, "entity_kind_mismatch")

    def test_race_occurrence_cannot_be_redeclared_horse(self):
        c = fixture(); retarget(c, "race_event", "event-E2025", "event_historical")
        retarget(c, "horse", "horse-H1", "horse_subject", align_entity=False)
        self.assertEqual(c["resolution_payload"]["entities"][0]["term_type"], "race")
        self.candidate(c, "entity_kind_mismatch")

    def test_ambiguous_classification_and_unsupported_n03_combinations(self):
        for entity_type, term_type, classification in (
            ("horse", "horse", "ambiguous"), ("horse", "horse", "common_word"),
            ("term", "race", "confirmed_horse"), ("term", "jockey", ""),
            ("race_event", "race", ""), ("horse", "race", "confirmed_horse"),
        ):
            with self.subTest(entity_type=entity_type, term_type=term_type, classification=classification):
                c = fixture()
                c["resolution_payload"]["entities"][0].update(entity_type=entity_type, term_type=term_type, classification=classification)
                refresh_occurrence(c)
                self.candidate(c, "entity_not_eligible")

    def _span_case(self, field, text, start, end, matched):
        c = fixture(); c["source_document"][field] = text
        c["article_input"]["snapshot"]["evidence"][0]["locator"] = "/" + field
        e = c["resolution_payload"]["entities"][0]
        e.update(field_name=field, start=start, end=end, matched_span=[start, end],
                 matched_text=matched, canonical_text=matched, matched_context=text)
        refresh_article(c); refresh_occurrence(c)
        return c

    def test_exact_source_end_is_valid_for_title_and_body(self):
        for field in ("title", "body"):
            with self.subTest(field=field):
                c = self._span_case(field, "Aurora", 0, 6, "Aurora")
                r = self.invoke(c)
                self.assertEqual(len(r["proposed_bindings"]), 1)
                self.assertEqual(r["proposed_bindings"][0]["occurrence"]["end"], 6)
                self.assertEqual(r["candidates"], [])

    def test_source_end_plus_one_and_large_overrun_are_candidates(self):
        for field in ("title", "body"):
            for end in (7, 1000000):
                with self.subTest(field=field, end=end):
                    c = self._span_case(field, "Aurora", 0, end, "Aurora")
                    self.candidate(c, "occurrence_binding_mismatch")

    def test_unicode_span_uses_codepoints_and_rejects_truncated_overrun(self):
        for field in ("title", "body"):
            with self.subTest(field=field):
                c = self._span_case(field, "星🌟馬", 1, 3, "🌟馬")
                r = self.invoke(c)
                self.assertEqual(len(r["proposed_bindings"]), 1)
                self.assertEqual(r["proposed_bindings"][0]["occurrence"]["matched_text"], "🌟馬")
                self.assertEqual(r["proposed_bindings"][0]["occurrence"]["end"], 3)
                c = self._span_case(field, "星🌟馬", 1, 4, "🌟馬")
                self.candidate(c, "occurrence_binding_mismatch")

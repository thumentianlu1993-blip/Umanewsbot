"""L01 conditional structural proposals. No ORM, clock, I/O or write authority.

Authenticity, permission and completeness of supplied assertions belong to the
producer. Passing this consumer proves only the frozen inputs agree.
"""
from datetime import datetime
import hashlib
import json
import re

from stable.services import content_contracts as f01

_SCOPE = "conditional_structural_proposals_only"
_ROLES = {"horse_subject", "event_current", "event_historical", "parent", "offspring", "series_only", "unknown"}
_OCC = {"field_name", "start", "end", "matched_text", "entity_payload_sha256"}
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class BindingInputError(ValueError):
    """Stable structural code, never source text or credentials."""


def _require(condition):
    if not condition:
        raise BindingInputError("structure")


def _guard(value, depth=0, budget=None):
    budget = [100000] if budget is None else budget
    budget[0] -= 1
    _require(depth <= 64 and budget[0] >= 0)
    if type(value) is dict:
        _require(all(type(k) is str for k in value))
        for item in value.values():
            _guard(item, depth + 1, budget)
    elif type(value) is list:
        for item in value:
            _guard(item, depth + 1, budget)
    else:
        _require(value is None or type(value) is str or type(value) is int or type(value) is bool)


def _raw(value):
    _guard(value)
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise BindingInputError("structure") from None
    _require(len(data) <= 1048576)
    return data


def _hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _hash(value):
    return _hash_bytes(_raw(value))


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result)
        result[key] = value
    return result


def _read(data):
    _require(type(data) is bytes and len(data) <= 1048576)
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                            parse_constant=lambda _: _require(False))
        _raw(result)
        return result
    except (UnicodeError, ValueError, RecursionError, OverflowError):
        raise BindingInputError("structure") from None


def _object(value, keys):
    _require(type(value) is dict and set(value) == set(keys))


def _text(value):
    _require(type(value) is str and bool(value))


def _digest(value):
    _require(type(value) is str and _HASH.fullmatch(value) is not None)


def _source_ref(value):
    if value is not None:
        _object(value, ("source", "namespace", "external_id"))
        for item in value.values():
            _text(item)


def _occurrence(value):
    _object(value, _OCC)
    _require(value["field_name"] in ("title", "body"))
    _require(type(value["start"]) is int and type(value["end"]) is int
             and 0 <= value["start"] < value["end"])
    _text(value["matched_text"])
    _digest(value["entity_payload_sha256"])


def _context(value):
    _object(value, ("occurrence", "target_identity_input_wire_sha256", "source_ref", "role",
                    "relation_input_wire_sha256", "evidence_id"))
    _occurrence(value["occurrence"])
    for key in ("target_identity_input_wire_sha256", "relation_input_wire_sha256"):
        _digest(value[key])
    _source_ref(value["source_ref"])
    _require(type(value["role"]) is str and value["role"] in _ROLES)
    _text(value["evidence_id"])


def _assertion(value):
    _object(value, ("assertion_id", "revision_ref", "article", "occurrence", "target", "role", "status"))
    _text(value["assertion_id"]); _text(value["revision_ref"])
    _object(value["article"], ("kind", "canonical_id", "input_wire_sha256", "source_document_sha256"))
    _require(value["article"]["kind"] == "article")
    _text(value["article"]["canonical_id"])
    _digest(value["article"]["input_wire_sha256"]); _digest(value["article"]["source_document_sha256"])
    _occurrence(value["occurrence"])
    _object(value["target"], ("kind", "canonical_id", "identity_input_wire_sha256", "source_ref"))
    _require(value["target"]["kind"] in ("horse", "race_event"))
    _text(value["target"]["canonical_id"])
    _digest(value["target"]["identity_input_wire_sha256"])
    _source_ref(value["target"]["source_ref"])
    _require(type(value["role"]) is str and value["role"] in _ROLES
             and value["status"] in ("active", "revoked", "superseded"))


def _documents(values):
    _require(type(values) is list or type(values) is tuple)
    result = {}
    for value in values:
        _require(type(value) is f01.LoaderInput)
        # Re-use F01's strict parser, never a caller-provided verified flag.
        doc = f01.parse_input(value.to_json())
        result[_hash_bytes(doc.to_json().encode())] = doc.to_dict()
    return result


def _time(value):
    return datetime.fromisoformat(value)


def _evidence_ready(evidence, evaluated):
    contract = evidence["contract_ref"]
    return (not contract["revoked"] and _time(evidence["observed_at"]) <= evaluated
            < _time(contract["valid_until"]))


def _ready(doc, kind, evaluated):
    snapshot = doc["snapshot"]; entity = snapshot["entity"]
    refs = set(entity["evidence_refs"])
    evidence = [e for e in snapshot["evidence"] if e["evidence_id"] in refs and e["capability"] == "identity"]
    return (entity["kind"] == kind and entity["identity_state"] == "verified"
            and entity["canonical_id"] is not None and not entity["candidate_ids"]
            and not snapshot["protection"]["paused"] and bool(evidence)
            and all(_evidence_ready(e, evaluated) for e in evidence))


def _entity_kind(entity):
    """Only combinations emitted by current N03, never a sidecar override.

    Japanese formal horses/aliases leave classification empty; English horse
    decisions use confirmed_horse. Non-horse formal race terms use term/race/"".
    A verified F01 identity cannot upgrade an unsupported N03 classification.
    """
    values = (entity["entity_type"], entity.get("term_type"), entity.get("classification"))
    if not all(type(value) is str for value in values):
        return None
    return {
        ("horse", "horse", "confirmed_horse"): "horse",
        ("horse", "horse", ""): "horse",
        ("unknown_horse", "", "confirmed_horse"): "horse",
        ("unknown_horse", "", ""): "horse",
        ("term", "race", ""): "race_event",
    }.get(values)


def _key(occurrence):
    # The article/version/document prefix is fixed for this invocation.
    return (occurrence["field_name"], occurrence["start"], occurrence["end"])


def _claim_errors(claim, relation, evidence, target, article_ref, evaluated):
    errors = set()
    if claim["status"] != "active":
        errors.add("assertion_not_active")
    if evidence["capability"] != "relationship" or not _evidence_ready(evidence, evaluated):
        errors.add("evidence_not_eligible")
    if _time(relation["evaluated_at"]) != evaluated:
        errors.add("evaluation_mismatch")
    if relation["snapshot"]["protection"]["paused"]:
        errors.add("input_not_eligible")
    if target is None:
        errors.add("target_binding_mismatch")
    else:
        identity = target["snapshot"]["entity"]
        if (not _ready(target, claim["target"]["kind"], evaluated)
                or _time(target["evaluated_at"]) != evaluated):
            errors.add("input_not_eligible")
        if (identity["kind"] != claim["target"]["kind"] or identity["canonical_id"] != claim["target"]["canonical_id"]
                or (claim["target"]["source_ref"] is not None and claim["target"]["source_ref"] not in identity["source_refs"])):
            errors.add("target_binding_mismatch")
        rel_entity = relation["snapshot"]["entity"]
        if (rel_entity["kind"], rel_entity["canonical_id"], rel_entity["source_refs"], rel_entity["identity_state"]) != (
                identity["kind"], identity["canonical_id"], identity["source_refs"], identity["identity_state"]) or rel_entity["candidate_ids"]:
            errors.add("target_binding_mismatch")
    role = claim["role"]
    if role not in ("horse_subject", "event_current", "event_historical"):
        errors.add("role_not_bindable")
    if ((role == "horse_subject" and claim["target"]["kind"] != "horse")
            or (role in ("event_current", "event_historical") and claim["target"]["kind"] != "race_event")):
        errors.add("role_binding_mismatch")
    # Material applicability is established by the evidence-to-record link,
    # not just article/target IDs: another occurrence may discuss the same
    # target in a different role. All records for this group are scanned above.
    materials = [m for m in relation["snapshot"]["materials"] if m["capability"] == "relationship"
                 and evidence["evidence_id"] in m["evidence_refs"]]
    if not materials:
        errors.add("material_binding_mismatch")
    for material in materials:
        if (material["validation"] != "passed" or material["maturity"] != "confirmed"
                or material["completeness"] != "complete" or material["supersedes_ref"] is not None):
            errors.add("material_not_eligible")
        if (material["revision_ref"] != claim["revision_ref"] or evidence["evidence_id"] not in material["evidence_refs"]
                or material["data"] != {"source_ref": article_ref["canonical_id"],
                                         "target_ref": claim["target"]["canonical_id"], "relation_type": role}):
            errors.add("material_binding_mismatch")
    return errors


def plan_article_entity_bindings(resolution_payload, *, article_input, identity_inputs, relation_inputs,
                                source_document, relationship_artifacts, contexts):
    """Return per-occurrence suggestions/candidates relative to supplied evidence.

    No wall-clock validity, source authentication, global completeness or writing
    is established by this function. It does not call an entity recognizer.
    """
    _raw(resolution_payload)
    _object(resolution_payload, ("source_language", "entities", "suppressed_candidates", "accepted_terms",
                                 "accepted_term_ids", "machine_horse_tags"))
    for key in ("entities", "suppressed_candidates", "accepted_terms", "accepted_term_ids", "machine_horse_tags"):
        _require(type(resolution_payload[key]) is list)
    _require((type(contexts) is list or type(contexts) is tuple) and type(relationship_artifacts) is dict)
    articles = _documents([article_input]); article_wire, article = next(iter(articles.items()))
    identities = _documents(identity_inputs); relations = _documents(relation_inputs)
    source = _read(source_document); _object(source, ("title", "body"))
    _require(all(type(x) is str for x in source.values()))
    source_sha = _hash_bytes(source_document)
    evaluated = _time(article["evaluated_at"])
    article_ref = {"kind": "article", "canonical_id": article["snapshot"]["entity"]["canonical_id"],
                   "input_wire_sha256": article_wire, "source_document_sha256": source_sha}
    article_ready = _ready(article, "article", evaluated)
    artifacts = {}
    for digest, data in relationship_artifacts.items():
        _digest(digest)
        _require(type(data) is bytes)
        # Missing/wrong artifact bytes are a normal unresolved proof, not a repaired hash.
        if _hash_bytes(data) != digest:
            continue
        pack = _read(data); _object(pack, ("schema_version", "assertions"))
        _require(pack["schema_version"] == "l01.relationship-assertions.v1" and type(pack["assertions"]) is list)
        for claim in pack["assertions"]:
            _assertion(claim)
        artifacts[digest] = pack["assertions"]

    groups = {}
    def group(occ):
        key = _key(occ)
        if key not in groups:
            groups[key] = {"occurrences": [], "contexts": [], "claims": [], "errors": set(), "entity_kinds": set()}
        return groups[key]
    suppressed = {_hash(e) for e in resolution_payload["suppressed_candidates"]}
    for entity in resolution_payload["entities"]:
        _require(type(entity) is dict and all(k in entity for k in ("field_name", "start", "end", "matched_text", "entity_type", "conflict_flags")))
        _require(type(entity["entity_type"]) is str and type(entity["conflict_flags"]) is list
                 and all(type(flag) is str for flag in entity["conflict_flags"]))
        occ = {k: entity[k] for k in ("field_name", "start", "end", "matched_text")}; occ["entity_payload_sha256"] = _hash(entity)
        _occurrence(occ); g = group(occ); g["occurrences"].append(occ)
        kind = _entity_kind(entity)
        if kind is None:
            g["errors"].add("entity_not_eligible")
        else:
            g["entity_kinds"].add(kind)
        if (entity["entity_type"] in ("common_word", "ambiguous") or entity["conflict_flags"] or _hash(entity) in suppressed):
            g["errors"].add("entity_not_eligible")
        if (occ["end"] > len(source[occ["field_name"]])
                or source[occ["field_name"]][occ["start"]:occ["end"]] != occ["matched_text"]
                or ("matched_span" in entity and entity["matched_span"] != [occ["start"], occ["end"]])):
            g["errors"].add("occurrence_binding_mismatch")
    for context in contexts:
        _raw(context); _context(context); group(context["occurrence"])["contexts"].append(context)

    # Inspect every supplied record of every referenced artifact, not only the
    # record a sidecar selects. A second role/revocation cannot be hidden by it.
    proofs = {}
    linked_artifacts = set()
    for wire, relation in relations.items():
        for evidence in relation["snapshot"]["evidence"]:
            digest = evidence["artifact_sha256"]
            if evidence["capability"] == "relationship" and digest in artifacts:
                linked_artifacts.add(digest)
                match = re.fullmatch(r"/assertions/(0|[1-9][0-9]*)", evidence["locator"])
                if match and int(match[1]) < len(artifacts[digest]):
                    proofs.setdefault((digest, int(match[1])), []).append((wire, relation, evidence))
    for digest in sorted(linked_artifacts):
        for index, claim in enumerate(artifacts[digest]):
            if claim["article"] != article_ref or _key(claim["occurrence"]) not in groups:
                continue
            g = groups[_key(claim["occurrence"])]; g["claims"].append(claim)
            if claim["target"]["kind"] not in g["entity_kinds"]:
                g["errors"].add("entity_kind_mismatch")
            evidence_proofs = proofs.get((digest, index), [])
            if not evidence_proofs:
                g["errors"].add("assertion_unbound")
            for wire, relation, evidence in evidence_proofs:
                g["errors"].update(_claim_errors(claim, relation, evidence,
                    identities.get(claim["target"]["identity_input_wire_sha256"]), article_ref, evaluated))
                if claim["occurrence"] not in g["occurrences"]:
                    g["errors"].add("occurrence_binding_mismatch")

    result = {"scope": _SCOPE, "proposed_bindings": [], "candidates": []}
    for key, g in sorted(groups.items()):
        errors = g["errors"]
        if not article_ready:
            errors.add("input_not_eligible")
        field = key[0]
        doc_evidence = [e for e in article["snapshot"]["evidence"] if e["evidence_id"] in article["snapshot"]["entity"]["evidence_refs"]
                        and e["capability"] == "identity" and e["artifact_sha256"] == source_sha and e["locator"] == "/" + field]
        if not doc_evidence or not all(_evidence_ready(e, evaluated) for e in doc_evidence):
            errors.add("source_document_unbound")
        occurrences = {_hash(o): o for o in g["occurrences"]}
        if len(occurrences) != 1:
            errors.add("occurrence_conflict")
        if not g["contexts"]:
            errors.add("context_missing")
        choices = set(); citations = {}
        selected = None
        for context in g["contexts"]:
            if context["occurrence"] not in g["occurrences"]:
                errors.add("occurrence_binding_mismatch")
            relation = relations.get(context["relation_input_wire_sha256"])
            if relation is None:
                errors.add("assertion_unbound"); continue
            evidence = next((e for e in relation["snapshot"]["evidence"] if e["evidence_id"] == context["evidence_id"]), None)
            if evidence is None or evidence["capability"] != "relationship":
                errors.add("assertion_unbound"); continue
            match = re.fullmatch(r"/assertions/(0|[1-9][0-9]*)", evidence["locator"])
            pack = artifacts.get(evidence["artifact_sha256"])
            if not match or pack is None or int(match[1]) >= len(pack):
                errors.add("assertion_unbound"); continue
            claim = pack[int(match[1])]
            if claim["target"]["kind"] not in g["entity_kinds"]:
                errors.add("entity_kind_mismatch")
            if claim["article"] != article_ref:
                errors.add("article_binding_mismatch")
            if claim["occurrence"] != context["occurrence"]:
                errors.add("occurrence_binding_mismatch")
            if (claim["target"]["identity_input_wire_sha256"] != context["target_identity_input_wire_sha256"]
                    or claim["target"]["source_ref"] != context["source_ref"]):
                errors.add("target_binding_mismatch")
            if claim["role"] != context["role"]:
                errors.add("role_binding_mismatch")
            errors.update(_claim_errors(claim, relation, evidence,
                identities.get(claim["target"]["identity_input_wire_sha256"]), article_ref, evaluated))
            choices.add((_hash(claim["target"]), claim["role"]))
            selected = claim
            citation = {"relation_input_wire_sha256": context["relation_input_wire_sha256"], "evidence_id": evidence["evidence_id"],
                        "artifact_sha256": evidence["artifact_sha256"], "locator": evidence["locator"],
                        "assertion_id": claim["assertion_id"], "revision_ref": claim["revision_ref"]}
            citations[_hash(citation)] = citation
        claims = {(_hash(c["target"]), c["role"]) for c in g["claims"]} | choices
        if len(claims) > 1:
            errors.add("claim_conflict")
        occurrence = min(g["occurrences"] or [c["occurrence"] for c in g["contexts"]], key=_hash)
        row = {"article_ref": article_ref, "occurrence": occurrence, "target": selected["target"] if selected and len(claims) == 1 else None,
               "role": selected["role"] if selected and len(claims) == 1 else "unknown", "reasons": sorted(errors),
               "evidence": [citations[k] for k in sorted(citations)]}
        result["candidates" if errors else "proposed_bindings"].append(row)
    # Return detached JSON values, never aliases into a caller's mutable input.
    return json.loads(_raw(result))

"""Bounded N02 candidate-copy validation. No provider, persistence or publish authority.

`packet` and `profile` are independent trusted-caller inputs, not model output.
Their hashes prove local binding only, never source/annotation/profile issuance.
"""
import hashlib
import json
import re
from stable.services.text import normalize_whitespace

LIMIT_KEYS = frozenset({"packet_bytes", "verdict_bytes", "result_bytes", "blocks", "field_bytes",
                        "reason_bytes", "quote_bytes", "depth"})
ATTEMPTS = {"available", "unavailable", "refused", "timeout", "invalid"}
SHA = re.compile(r"[0-9a-f]{64}\Z")


class ReviewInputError(ValueError):
    pass


def _fail(code):
    raise ReviewInputError(code)


def _fields(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        _fail("schema_invalid")


def _string(value, cap, *, nonempty=True):
    if type(value) is not str or (nonempty and not value.strip()) or len(value) > cap:
        _fail("field_invalid")
    try:
        if len(value.encode("utf-8")) > cap:
            _fail("field_size_limit")
    except UnicodeEncodeError:
        _fail("input_utf8_invalid")


def _wire(value, byte_limit, depth_limit):
    """Bounded canonical encoding; exact JSON builtins, no user hooks/coercion."""
    chunks, size, ancestors = [], 0, set()
    def emit(text):
        nonlocal size
        try:
            raw = text.encode("utf-8")
        except UnicodeEncodeError:
            _fail("input_utf8_invalid")
        size += len(raw)
        if size > byte_limit:
            _fail("byte_size_limit")
        chunks.append(raw)
    def walk(item, depth):
        if depth > depth_limit:
            _fail("depth_limit")
        kind = type(item)
        if kind in (dict, list):
            if id(item) in ancestors or len(item) > byte_limit:
                _fail("container_invalid")
            ancestors.add(id(item))
            if kind is dict:
                if any(type(k) is not str for k in item):
                    _fail("json_type_invalid")
                emit("{")
                for index, key in enumerate(sorted(item)):
                    if index: emit(",")
                    walk(key, depth + 1); emit(":"); walk(item[key], depth + 1)
                emit("}")
            else:
                emit("[")
                for index, child in enumerate(item):
                    if index: emit(",")
                    walk(child, depth + 1)
                emit("]")
            ancestors.remove(id(item))
        elif kind is str:
            if len(item) > byte_limit: _fail("byte_size_limit")
            emit(json.dumps(item, ensure_ascii=False))
        elif kind in (int, bool) or item is None:
            if kind is int and item.bit_length() > 63: _fail("integer_range")
            emit(json.dumps(item))
        else:
            _fail("json_type_invalid")
    walk(value, 0)
    return b"".join(chunks)


def _profile(profile):
    if profile is None: _fail("profile_missing")
    _fields(profile, {"id", "purpose", "source_site", "policy_ref", "limits"})
    for key in ("id", "source_site", "policy_ref"): _string(profile[key], 1024)
    if type(profile["purpose"]) is not str or profile["purpose"] not in {"TEST_ONLY", "CALLER_SUPPLIED"}:
        _fail("profile_invalid")
    _fields(profile["limits"], LIMIT_KEYS)
    for value in profile["limits"].values():
        if type(value) is not int or not 0 < value <= 2147483647: _fail("profile_invalid")
    if profile["limits"]["depth"] > 64: _fail("profile_invalid")
    # Fixed-shape profile snapshot; not a production default or issuer check.
    return json.loads(_wire(profile, 16384, 8))


def _packet(packet, profile):
    limits = profile["limits"]
    packet = json.loads(_wire(packet, limits["packet_bytes"], limits["depth"]))
    _fields(packet, {"schema_version", "source", "capture_sha256", "policy_ref", "body_parse_status",
                     "protection", "template", "trace"})
    if type(packet["schema_version"]) is not int or packet["schema_version"] != 1: _fail("schema_invalid")
    _fields(packet["source"], {"site", "article_ref", "capture_ref"})
    for value in packet["source"].values(): _string(value, limits["field_bytes"])
    _string(packet["policy_ref"], limits["field_bytes"])
    if profile["source_site"] != packet["source"]["site"] or profile["policy_ref"] != packet["policy_ref"]:
        _fail("profile_scope_mismatch")
    if type(packet["capture_sha256"]) is not str or not SHA.fullmatch(packet["capture_sha256"]): _fail("capture_invalid")
    status = packet["body_parse_status"]
    if type(status) is not str or status not in {"ok", "selector_not_found", "empty_after_cleaning", "parse_error"}:
        _fail("schema_invalid")
    if status != "ok": _fail("source_body_unavailable")
    protection, template = packet["protection"], packet["template"]
    _fields(protection, {"state", "ref", "protected_ids"})
    _fields(template, {"state", "ref", "version"})
    for context in (protection, template):
        if type(context["state"]) is not str or context["state"] not in {"known", "unknown"}: _fail("context_invalid")
        if context["ref"] is not None: _string(context["ref"], limits["field_bytes"])
        if context["state"] == "known" and context["ref"] is None: _fail("context_invalid")
    if template["version"] is not None: _string(template["version"], limits["field_bytes"])
    if template["state"] == "known" and template["version"] is None: _fail("context_invalid")
    trace = packet["trace"]
    _fields(trace, {"removed_count", "removed_rules", "trace_version", "body_html_sha256",
                    "before_text", "after_text", "blocks"})
    if type(trace["trace_version"]) is not int or trace["trace_version"] != 1: _fail("trace_invalid")
    if trace["body_html_sha256"] != packet["capture_sha256"]: _fail("capture_invalid")
    if type(trace["removed_rules"]) is not dict or type(trace["removed_count"]) is not int or trace["removed_count"] < 0:
        _fail("trace_invalid")
    for name, count in trace["removed_rules"].items():
        _string(name, limits["field_bytes"])
        if type(count) is not int or count < 0: _fail("trace_invalid")
    if trace["removed_count"] != sum(trace["removed_rules"].values()): _fail("trace_invalid")
    for key in ("before_text", "after_text"): _string(trace[key], limits["field_bytes"], nonempty=False)
    if type(trace["blocks"]) is not list or len(trace["blocks"]) > limits["blocks"]: _fail("block_limit")
    eligible, seen = [], set()
    for block in trace["blocks"]:
        _fields(block, {"block_id", "locator", "original_text", "text", "decision", "reasons"}, {"original_html_sha256"})
        for key in ("block_id", "locator", "original_text", "text"):
            _string(block[key], limits["field_bytes"], nonempty=key in {"block_id", "locator"})
        expected = "body-" + hashlib.sha256(json.dumps([packet["source"]["site"], packet["capture_sha256"],
                      block["locator"], block["original_text"]], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:20]
        if block["block_id"] != expected or block["block_id"] in seen: _fail("block_identity_invalid")
        seen.add(block["block_id"])
        if type(block["decision"]) is not str or block["decision"] not in {"kept", "modified", "removed"}: _fail("trace_invalid")
        if type(block["reasons"]) is not list: _fail("trace_invalid")
        for reason in block["reasons"]: _string(reason, limits["field_bytes"])
        if "original_html_sha256" in block and (type(block["original_html_sha256"]) is not str or not SHA.fullmatch(block["original_html_sha256"])):
            _fail("trace_invalid")
        if block["decision"] == "removed":
            if block["text"]: _fail("trace_invalid")
        elif not block["text"]: _fail("trace_invalid")
        else: eligible.append(block)
    reconstructed = normalize_whitespace("\n\n".join(b["text"] for b in eligible))
    if not reconstructed or reconstructed != trace["after_text"]: _fail("trace_reconstruction_invalid")
    protected = protection["protected_ids"]
    if type(protected) is not list or any(type(v) is not str for v in protected) or len(protected) != len(set(protected)):
        _fail("protection_invalid")
    if not set(protected) <= {b["block_id"] for b in eligible}: _fail("protection_invalid")
    digest = hashlib.sha256(_wire({"packet": packet, "profile": profile}, limits["packet_bytes"] + 16384,
                                 limits["depth"] + 1)).hexdigest()
    return packet, eligible, digest


def input_digest(packet, profile):
    """Explicit caller profile required; full trusted-input binding, not authorization."""
    profile = _profile(profile)
    return _packet(packet, profile)[2]


def _blocked(reason, digest=None):
    # Fixed small refusal envelope, independent of an invalid/tiny requested cap.
    return {"status": "review_blocked", "reason": reason, "candidate_text": None, "diff": [],
            "input_digest": digest, "decision_digest": None, "quality_gaps": [],
            "publish_eligible": False, "qualified": False}


def review_candidate(packet, verdict, *, profile=None, attempt="available"):
    digest = None
    try:
        profile = _profile(profile)
        packet, blocks, digest = _packet(packet, profile)
        limits = profile["limits"]
        if type(attempt) is not str or attempt not in ATTEMPTS: _fail("attempt_invalid")
        if attempt != "available": _fail("model_" + attempt)
        verdict = json.loads(_wire(verdict, limits["verdict_bytes"], limits["depth"]))
        _fields(verdict, {"schema_version", "input_digest", "policy_ref", "decisions"})
        if type(verdict["schema_version"]) is not int or verdict["schema_version"] != 1: _fail("schema_invalid")
        if verdict["input_digest"] != digest: _fail("input_digest_mismatch")
        if verdict["policy_ref"] != packet["policy_ref"]: _fail("policy_ref_mismatch")
        decisions = verdict["decisions"]
        if type(decisions) is not list or len(decisions) != len(blocks): _fail("decision_coverage_invalid")
        by_id = {b["block_id"]: b for b in blocks}
        chosen = {}
        for item in decisions:
            _fields(item, {"block_id", "action", "reason", "evidence"})
            if type(item["block_id"]) is not str or item["block_id"] not in by_id or item["block_id"] in chosen:
                _fail("decision_coverage_invalid")
            if type(item["action"]) is not str or item["action"] not in {"keep", "delete"}: _fail("action_invalid")
            _string(item["reason"], limits["reason_bytes"])
            evidence = item["evidence"]
            _fields(evidence, {"start", "end", "quote"})
            start, end, text = evidence["start"], evidence["end"], by_id[item["block_id"]]["text"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text): _fail("evidence_range_invalid")
            _string(evidence["quote"], limits["quote_bytes"])
            if evidence["quote"] != text[start:end]: _fail("evidence_quote_invalid")
            if item["action"] == "delete":
                if start != 0 or end != len(text): _fail("delete_coverage_invalid")
                if item["block_id"] in packet["protection"]["protected_ids"]: _fail("protected_block_delete")
            chosen[item["block_id"]] = item
        ordered = [chosen[b["block_id"]] for b in blocks]
        kept = [b["text"] for b in blocks if chosen[b["block_id"]]["action"] == "keep"]
        candidate = normalize_whitespace("\n\n".join(kept))
        if not candidate: _fail("review_empty_result")
        diff = [{"block_id": b["block_id"], "before_text": b["text"], "after_text": "",
                 "action": "delete", "reason": chosen[b["block_id"]]["reason"],
                 "evidence": chosen[b["block_id"]]["evidence"]}
                for b in blocks if chosen[b["block_id"]]["action"] == "delete"]
        gaps = ["quality_policy_unresolved"]
        if packet["template"]["state"] == "unknown": gaps.append("template_baseline_missing")
        unknown = packet["protection"]["state"] == "unknown"
        if unknown: gaps.append("protection_context_unknown")
        if profile["purpose"] == "TEST_ONLY": gaps.append("test_only_profile")
        result = {"status": "needs_manual_review" if unknown else "candidate_valid", "reason": "candidate_only",
                  "candidate_text": candidate, "diff": diff, "input_digest": digest,
                  "decision_digest": hashlib.sha256(_wire(ordered, limits["verdict_bytes"], limits["depth"])).hexdigest(),
                  "quality_gaps": gaps, "publish_eligible": False, "qualified": False}
        try:
            _wire(result, limits["result_bytes"], limits["depth"])
        except ReviewInputError as exc:
            if str(exc) == "byte_size_limit": _fail("result_size_limit")
            raise
        return result
    except ReviewInputError as exc:
        return _blocked(str(exc), digest)

"""以结构化来源证据生成事件键；不接受模型自行声明的跨源身份。"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from stable.services.news_pipeline import digest, REGIONS
from stable.services.news_content import ContentBlocked, bounded_json, block_map

RESPONSE_SCHEMA = {
    "priority": "major|regional|reject|uncertain", "primary_region": list(REGIONS),
    "reason": "基于事件价值的理由，不按来源或榜单加分",
    "identity": {"kind": "race|retirement|injury|policy|appointment", "fields": "按类型提供完整规范元组",
        "evidence": "每个 fields 键映射为 {block_id,start,end} 原文证据"},
    "facts": [{"subject_ref": "已核主体或原文主体", "predicate": "事实谓词", "object": "原文事实值",
        "effective_time": "明确事实时间或空字符串", "modality": "happened|planned|possible|negated",
        "source_span": {"block_id": "ID", "start": 0, "end": 1},
        "importance": "major|minor", "relation": "new|repeated|correction",
        "prior_fact_ids": ["只引用提供的候选事实ID"],
        "correction": "仅 correction 必填 {receipt_id,old_body_span:{start,end},old_text}，精确引用旧稿"}],
    "comparison": {"event_id": "候选事件UUID或null", "version": 0},
}


def norm(value):
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ContentBlocked("identity_value_invalid")
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def iso_date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise ContentBlocked("identity_date_invalid") from None


def identity_key(kind, fields, *, source_scope="", aliases=None):
    aliases = aliases or {}
    if type(fields) is not dict:
        raise ContentBlocked("identity_fields_invalid")
    if kind == "race":
        if set(fields) == {"canonical_race_id"}:
            ref = "race:" + str(fields["canonical_race_id"])
            parts = [ref]
        elif set(fields) == {"source_race_id"} and source_scope:
            ref = f"race:{source_scope}:{fields['source_race_id']}"
            parts = [aliases.get(ref, ref)]
        elif set(fields) == {"organizer", "venue", "local_date", "race_number"}:
            if not re.fullmatch(r"[1-9][0-9]?", fields["race_number"]):
                raise ContentBlocked("identity_race_number_invalid")
            parts = [norm(fields["organizer"]), norm(fields["venue"]), iso_date(fields["local_date"]), fields["race_number"]]
        else:
            raise ContentBlocked("identity_incomplete")
    elif kind in {"retirement", "injury"}:
        if set(fields) != {"subject_ref", "episode_ref"} or not re.fullmatch(r"horse:[^:]+(?::[^:]+)?", fields["subject_ref"]):
            raise ContentBlocked("identity_incomplete")
        episode = fields["episode_ref"]
        if episode.startswith("date:"):
            pieces = episode.split(":")
            if len(pieces) != 3 or pieces[2] != kind:
                raise ContentBlocked("identity_episode_invalid")
            iso_date(pieces[1])
        elif not re.fullmatch(r"announcement:[^:]+:[^:]+", episode):
            raise ContentBlocked("identity_episode_invalid")
        parts = [aliases.get(fields["subject_ref"], fields["subject_ref"]), aliases.get(episode, episode)]
    elif kind in {"policy", "appointment"}:
        common = {"organization", "jurisdiction"}
        if set(fields) == common | {"document_id"}:
            parts = [aliases.get(norm(fields["organization"]), norm(fields["organization"])), norm(fields["jurisdiction"]), fields["document_id"]]
        elif set(fields) == common | {"effective_date", "scope"}:
            parts = [aliases.get(norm(fields["organization"]), norm(fields["organization"])), norm(fields["jurisdiction"]), iso_date(fields["effective_date"]), norm(fields["scope"])]
        else:
            raise ContentBlocked("identity_incomplete")
    else:
        raise ContentBlocked("identity_kind_unknown")
    if any(type(part) is not str or not part.strip() for part in parts):
        raise ContentBlocked("identity_incomplete")
    return "news-event-v1:" + kind + ":" + digest(parts)


def span_text(clean, span):
    texts = block_map(clean)
    if type(span) is not dict or set(span) != {"block_id", "start", "end"}:
        raise ContentBlocked("editorial_span_schema")
    block, start, end = span["block_id"], span["start"], span["end"]
    if block not in texts or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(texts[block]):
        raise ContentBlocked("editorial_span_invalid")
    return texts[block][start:end]


def fact_key(fact):
    return digest({key: norm(fact[key]) if fact[key] else "" for key in ("subject_ref", "predicate", "object", "effective_time", "modality")})


def validate_editorial(clean, response, *, source_scope, candidates=(), aliases=None, binding=None):
    if len(candidates) > 20:
        raise ContentBlocked("recall_overflow")
    bounded_json(response)
    required = {"priority", "primary_region", "reason", "identity", "facts", "comparison"}
    if type(response) is not dict or set(response) != required:
        raise ContentBlocked("editorial_schema")
    priority = response["priority"]
    if priority not in {"major", "regional", "reject", "uncertain"} or response["primary_region"] not in REGIONS:
        raise ContentBlocked("editorial_priority_or_region")
    if type(response["reason"]) is not str or not 0 < len(response["reason"]) <= 1000:
        raise ContentBlocked("editorial_reason_missing")
    if priority in {"reject", "uncertain"}:
        return {**response, "identity_key": None, "facts": []}
    identity = response["identity"]
    if type(identity) is not dict or set(identity) != {"kind", "fields", "evidence"}:
        raise ContentBlocked("identity_schema")
    fields, evidence = identity["fields"], identity["evidence"]
    if type(fields) is not dict or type(evidence) is not dict or set(fields) != set(evidence):
        raise ContentBlocked("identity_evidence_missing")
    aliases = aliases or {}
    for key, value in fields.items():
        original = span_text(clean, evidence[key])
        if type(value) is not str:
            raise ContentBlocked("identity_value_invalid")
        if key == "canonical_race_id":
            if aliases.get("mention:" + original) != "race:" + value:
                raise ContentBlocked("canonical_identity_unverified")
        elif key == "subject_ref":
            source_ref = f"horse:{source_scope}:{original}"
            if value not in {source_ref, aliases.get(source_ref), aliases.get("mention:" + original)}:
                raise ContentBlocked("subject_identity_unverified")
        elif key == "episode_ref":
            expected = f"date:{original}:{identity['kind']}" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", original) else f"announcement:{source_scope}:{original}"
            if value != expected and aliases.get(expected) != value:
                raise ContentBlocked("episode_identity_unverified")
        elif norm(value) != norm(original):
            raise ContentBlocked("identity_evidence_mismatch")
    key = identity_key(identity["kind"], fields, source_scope=source_scope, aliases=aliases)
    comparison = response["comparison"]
    if type(comparison) is not dict or set(comparison) != {"event_id", "version"} or type(comparison["version"]) is not int or comparison["version"] < 0:
        raise ContentBlocked("comparison_schema")
    chosen = next((row for row in candidates if str(row["id"]) == comparison["event_id"]), None)
    if comparison["event_id"] is not None and chosen is None:
        raise ContentBlocked("comparison_event_unknown")
    if binding:
        if not chosen or binding["event_id"] != str(chosen["id"]):
            raise ContentBlocked("manual_event_binding_mismatch")
        key = chosen["identity_key"]
    if chosen and (chosen["identity_key"] != key or chosen["version"] != comparison["version"]):
        raise ContentBlocked("comparison_identity_or_version")
    if not chosen and comparison["version"] != 0:
        raise ContentBlocked("comparison_version_unknown")
    prior = {fact["id"] for fact in chosen.get("facts", [])} if chosen else set()
    if type(response["facts"]) is not list or not 1 <= len(response["facts"]) <= 128:
        raise ContentBlocked("facts_missing_or_unbounded")
    facts, seen = [], set()
    for fact in response["facts"]:
        keys = {"subject_ref", "predicate", "object", "effective_time", "modality", "source_span", "importance", "relation", "prior_fact_ids"}
        if isinstance(fact, dict) and fact.get("relation") == "correction":
            keys.add("correction")
        if type(fact) is not dict or set(fact) != keys:
            raise ContentBlocked("fact_schema")
        original = span_text(clean, fact["source_span"])
        for name in ("subject_ref", "predicate", "object"):
            norm(fact[name])
        if fact["modality"] not in {"happened", "planned", "possible", "negated"} or fact["importance"] not in {"major", "minor"} or fact["relation"] not in {"new", "repeated", "correction"}:
            raise ContentBlocked("fact_value_invalid")
        if norm(fact["object"]) not in norm(original):
            raise ContentBlocked("fact_object_evidence_missing")
        if type(fact["effective_time"]) is not str or len(fact["effective_time"]) > 64:
            raise ContentBlocked("fact_time_invalid")
        ids = fact["prior_fact_ids"]
        if type(ids) is not list or any(type(item) is not str or item not in prior for item in ids):
            raise ContentBlocked("prior_fact_unknown")
        if fact["relation"] in {"repeated", "correction"} and not ids:
            raise ContentBlocked("prior_fact_evidence_missing")
        if fact["relation"] == "correction":
            validate_correction(fact, chosen)
        fid = fact_key(fact)
        if fid in seen:
            raise ContentBlocked("duplicate_fact")
        seen.add(fid)
        facts.append({**fact, "id": fid})
    return {**response, "identity_key": key, "facts": facts}


def validate_correction(fact, candidate):
    correction = fact.get("correction")
    if type(correction) is not dict or set(correction) != {"receipt_id", "old_body_span", "old_text"}:
        raise ContentBlocked("correction_target_missing")
    receipt = next((row for row in (candidate or {}).get("receipts", []) if row["id"] == correction["receipt_id"]), None)
    if not receipt or not set(fact["prior_fact_ids"]).issubset(receipt["fact_ids"]):
        raise ContentBlocked("correction_target_fact_mismatch")
    span = correction["old_body_span"]
    if type(span) is not dict or set(span) != {"start", "end"}:
        raise ContentBlocked("correction_span_invalid")
    start, end = span["start"], span["end"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(receipt["body"]):
        raise ContentBlocked("correction_span_invalid")
    if correction["old_text"] != receipt["body"][start:end]:
        raise ContentBlocked("correction_old_text_mismatch")


def correction_targets(editorial):
    return [fact["correction"] for fact in editorial.get("facts", []) if fact["relation"] == "correction"]


def audit_corrections(editorial, response):
    """旧文定位由程序核验，是否有实质错误及新稿是否有证据由强审校确认。"""
    targets = correction_targets(editorial)
    checked = response.get("corrections", [])
    expected = [{"receipt_id": row["receipt_id"], "old_body_span": row["old_body_span"],
                 "substantive": True, "supported": True} for row in targets]
    if checked != expected:
        raise ContentBlocked("correction_not_substantively_verified")
    return {key: value for key, value in response.items() if key != "corrections"}

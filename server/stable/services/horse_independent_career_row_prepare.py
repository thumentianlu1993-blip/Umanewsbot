"""私有HKJC单行履历离线准备；不是消费、发布或来源许可入口。

原始carrier可以只覆盖部分履历；complete仅描述已校验的选行投影。
身份/时效来自显式历史snapshot/as_of，不冒当前DB或当前来源鲜度。
不调用旧_apply，不写record/candidate；下划线不构成Python安全沙箱。
"""
from copy import deepcopy
import hashlib
import json
import re

from django.core.management.base import CommandError

from . import horse_cache_reuse
from . import horse_basic_profile_prepare_input as inputs
from .horse_source_cache_reuse_adapter import CacheReuseAdapterError, _provider_identity
from .horse_target_inventory import _key
from .p0_horse_completion_adapters import (
    _normalize_race_record, _valid_http_url, normalize_p0_horse_race_records,
)

_LABELS = dict(preparation_capability_only=True, source_permission_status="not_evaluated",
               public_consumer_authorized=False)


def _reject(reason):
    raise ValueError(reason) from None


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest_shape(value, reason):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        _reject(reason)


def _canonical(value, reason):
    try:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _reject(reason)
    if len(raw) > inputs.MAX_BYTES:
        _reject(reason)
    return raw


def _permission(binding):
    if type(binding) is not dict or set(binding) != {"reference", "sha256"}:
        _reject("row_permission_binding")
    try:
        _key(binding["reference"])
    except ValueError:
        _reject("row_permission_binding")
    _digest_shape(binding["sha256"], "row_permission_binding")
    return deepcopy(binding)  # Inert external anchor, never a grant decision.


def _evidence_markers(payload):
    stack = [payload]
    budget = 100000
    while stack:
        value = stack.pop()
        budget -= 1
        if budget < 0:
            _reject("row_json")
        if type(value) is dict:
            if ("manual_supplements" in value or "manual_supplement_outcomes" in value
                    or value.get("entry_method") == "manual_review"
                    or value.get("evidence_role") == "manual_supplement"):
                _reject("row_manual_marker")
            if (any(value.get(key) for key in ("failure_reason", "failure_reasons", "conflict"))
                    or value.get("record_authority_status") == "source_blocked"
                    or any(value.get(key) in ("failed", "failure", "error", "blocked", "invalid")
                           for key in ("status", "fetch_status", "parse_status"))):
                _reject("row_source_failed")
            stack.extend(value.values())
        elif type(value) is list:
            stack.extend(value)


def _carrier(raw_bytes, expected_sha256, selected_row_sha256, source_ref):
    if type(raw_bytes) is not bytes or len(raw_bytes) > inputs.MAX_BYTES:
        _reject("row_input_bytes")
    _digest_shape(expected_sha256, "row_source_digest")
    if _digest(raw_bytes) != expected_sha256:
        _reject("row_source_digest")
    _digest_shape(selected_row_sha256, "row_selected_digest")
    try:
        payload = inputs._strict_json(raw_bytes, allow_float=True)
    except CommandError:
        _reject("row_json")
    if type(payload) is not dict:
        _reject("row_json")
    _evidence_markers(payload)
    source, career = payload.get("source"), payload.get("career")
    if (payload.get("schema_version") != "p0-horse-source-cache.v2"
            or payload.get("region") != "hong_kong" or payload.get("adapter_key") != "hong_kong_hkjc"
            or type(source) is not dict or source.get("name") != "hkjc"
            or type(career) is not dict or type(career.get("records")) is not list
            or any(type(record) is not dict for record in career["records"])
            or type(career.get("source_start_count")) is not int
            or not 0 <= career["source_start_count"] <= 10**12):
        _reject("row_source_scope")
    # Avoid malformed nested reference collections being silently lost/coerced.
    for record in career["records"]:
        refs = record.get("source_refs")
        if type(refs) is dict and "sources" in refs and type(refs["sources"]) is not list:
            _reject("row_source_scope")
    try:
        _key(source_ref)
        horse_key = _provider_identity(source)
        inputs._utc(source.get("fetched_at"), "row_source_identity")
    except (ValueError, CacheReuseAdapterError, CommandError):
        _reject("row_source_identity")
    selected = [record for record in career["records"]
                if _digest(_canonical(record, "row_json")) == selected_row_sha256]
    if len(selected) != 1:
        _reject("row_selection_missing_or_ambiguous")
    return payload, horse_key, selected[0]


def _selected_projection(selected, source):
    required = ("provider", "region", "operator", "identity_namespace", "external_horse_id",
                "external_race_id", "venue_key", "race_date", "race_number", "timezone",
                "source_name", "source_url", "race_name", "racecourse", "distance_text")
    if any(type(selected.get(key)) is not str or not selected[key].strip() for key in required):
        _reject("row_identity")
    if (selected["provider"] != "hkjc" or selected["source_name"] != "hkjc"
            or selected["region"] != "hong_kong" or selected["operator"] != "hkjc"
            or selected["identity_namespace"] != "hkjc-race-v1"
            or selected["timezone"] != "Asia/Hong_Kong"
            or selected["external_horse_id"] != source["external_horse_id"]
            or selected.get("event_id") is not None or selected.get("result_id") is not None
            or not _valid_http_url(selected["source_url"])):
        _reject("row_identity")
    # Reuse, rather than replace, the three existing normalization routes.
    # Explicit start/result fields cannot override a non-start/unknown finish.
    original = _normalize_race_record(selected)
    no_start = _normalize_race_record({key: value for key, value in selected.items() if key != "start_status"})
    finish_only = _normalize_race_record({key: value for key, value in selected.items()
                                         if key not in ("start_status", "result_status")})
    if any(record["start_status"] != "started" or record["race_date_precision"] != "exact"
           for record in (original, no_start, finish_only)):
        _reject("row_not_started_exact")
    return original


def _project_hkjc_career_row(raw_bytes, *, expected_sha256, selected_row_sha256,
                           source_ref, permission_binding):
    """绑定原件选恰一行；父coverage始终来自全部观察行，不伪补缺场。"""
    permission = _permission(permission_binding)
    payload, horse_key, selected = _carrier(raw_bytes, expected_sha256, selected_row_sha256, source_ref)
    source, career = payload["source"], payload["career"]
    projection = _selected_projection(selected, source)
    try:
        parent = normalize_p0_horse_race_records(
            career["records"], source_start_count=career["source_start_count"],
            official_start_count_source=career.get("official_start_count_source", ""),
            official_start_count_source_url=career.get("official_start_count_source_url", ""),
            official_start_count_verified_at=career.get("official_start_count_verified_at", ""),
            record_authority_status=career.get("record_authority_status", "unknown"))["career_history"]
    except ValueError:
        _reject("row_source_scope")
    module = dict(validation_scope="career_row",
                  source_binding=dict(source_ref=source_ref, raw_sha256=expected_sha256, source_name="hkjc",
                                      external_horse_id=source["external_horse_id"], horse_key=horse_key,
                                      url=source["url"], fetched_at=source["fetched_at"]),
                  selected_row=deepcopy(selected), selected_row_sha256=selected_row_sha256,
                  projection=projection, projection_sha256=_digest(_canonical(projection, "row_json")),
                  coverage=dict(parent_career=parent,
                                selected_row=dict(status="complete", record_count=1, actual_start_count=1)),
                  permission_binding=permission, **_LABELS)
    _canonical(module, "row_input_bytes")
    return module


def _career_row_h02_record(module, *, raw_bytes, expected_sha256, selected_row_sha256,
                          source_ref, permission_binding):
    """从同一原件重建后适配H02八字段，绝不把partial原件重标complete。"""
    rebuilt = _project_hkjc_career_row(raw_bytes, expected_sha256=expected_sha256,
                                      selected_row_sha256=selected_row_sha256,
                                      source_ref=source_ref, permission_binding=permission_binding)
    content = _canonical(rebuilt, "row_input_bytes")
    if type(module) is not dict or _canonical(module, "row_projection_binding") != content:
        _reject("row_projection_binding")
    source = rebuilt["source_binding"]
    return dict(ref="h03-career-row:" + selected_row_sha256, horse_key=source["horse_key"],
                profile_id=None, source_time=source["fetched_at"], source_ref=source_ref,
                content=content.decode("utf-8"), content_sha256=_digest(content), parse_status="complete")


def _packet(raw):
    if type(raw) is not bytes or len(raw) > inputs.MAX_BYTES:
        _reject("row_input_packet")
    try:
        packet = inputs._strict_packet(raw)
        inputs._parts(packet["source_file"], "row_input_packet")
        _key(packet["cache_ref"])
        _key(packet["source_ref"])
        inputs._utc(packet["as_of"], "row_input_packet")
    except (CommandError, ValueError):
        _reject("row_input_packet")
    return packet


def _prepare_independent_career_row(*, packet, source_raw, expected_source_sha256,
                                   selected_row_sha256, permission_binding):
    """真实投影→重建bridge→H01/H02，仅返回未消费准备结果。"""
    checked = _packet(packet)
    module = _project_hkjc_career_row(
        source_raw, expected_sha256=expected_source_sha256, selected_row_sha256=selected_row_sha256,
        source_ref=checked["source_ref"], permission_binding=permission_binding)
    record = _career_row_h02_record(
        module, raw_bytes=source_raw, expected_sha256=expected_source_sha256,
        selected_row_sha256=selected_row_sha256, source_ref=checked["source_ref"],
        permission_binding=permission_binding)
    if checked["cache_ref"] != record["ref"]:
        _reject("row_input_packet")
    try:
        plan = horse_cache_reuse.plan_cache_reuse(
            checked["snapshot"], [record], checked["entity_versions"],
            as_of=checked["as_of"], max_age_seconds=checked["max_age_seconds"])
    except ValueError:
        _reject("row_h02_not_reusable")
    if len(plan["decisions"]) != 1 or len(plan["candidates"]) != 1:
        _reject("row_h02_not_reusable")
    decision, candidate = plan["decisions"][0], plan["candidates"][0]
    entity_key = candidate["entity_key"]
    if (candidate["action"] != "reusable" or decision["status"] != "reusable"
            or not re.fullmatch(r"profile:[1-9][0-9]*", entity_key)
            or int(entity_key.removeprefix("profile:")) > 10**12
            or set(checked["entity_versions"]) != {entity_key}
            or decision["profile_exists"] is not True or decision["public_state"] != "unpublished"
            or not candidate["identity_evidence"] or candidate["cache_refs"] != [record["ref"]]
            or candidate["content"] != record["content"] or plan["unused_cache_refs"]):
        _reject("row_h02_not_reusable")
    binding = dict(source_sha256=expected_source_sha256, selected_row_sha256=selected_row_sha256,
                   projection_sha256=module["projection_sha256"], module_sha256=_digest(_canonical(module, "row_json")),
                   packet_sha256=_digest(packet),
                   entity_versions_sha256=_digest(_canonical(checked["entity_versions"], "row_input_packet")),
                   entity_key=entity_key, entity_version=candidate["entity_version"],
                   h02_idempotency_key=candidate["idempotency_key"], h02_plan_sha256=plan["content_sha256"],
                   permission_binding=deepcopy(module["permission_binding"]), source_ref=checked["source_ref"])
    return dict(row_module=module, record=record, plan=plan, candidate=candidate, binding=binding,
                writer_payload=deepcopy(module["projection"]), **_LABELS,
                committed=False, published=False, record_id=None, candidate_id=None)
